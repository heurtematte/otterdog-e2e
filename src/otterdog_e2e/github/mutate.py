"""Harness-side writes to the test org: setup, drift, PR flows and teardown (SPEC 9.4).

Requires a VerifiedOrg and (unless dry_run) a GitHubHttp write-scoped to it; the client paces mutating calls at least
``min_write_interval`` (1 s) apart. Deletion guards (SPEC 5.2): names must satisfy ``naming.is_e2e_name`` (delete_ref:
``naming.is_deletable_ref``; delete_org_hook / delete_repo_hook: the live config.url must start with
``naming.HOOK_BASE``; ruleset/role deletions: the live object must carry the given e2e name); ``force=True`` is only
for bootstrap after interactive confirmation. Force-updating a ref is limited to deletable (e2e) refs, and
renaming/archiving/changing the visibility of a non-e2e repository is refused.

Beyond SPEC 9.4 the janitor needs: delete_org_role, delete_repo_ruleset, delete_branch_protection_rule,
delete_environment, delete_repo_secret, delete_repo_variable. Identity-side calls (accept an org invitation, publicize a
membership) are module functions taking the identity's own write-scoped client.

Probe and drift calls of the battery change run objects only (SafetyError before any write otherwise): workflow
dispatch, cancel and re-run, security advisories, collaborators, topics and invitations of e2e repositories; teams
(creation, changes, memberships; add_team_member only for existing org members, GitHub would invite anybody else) and
code security configurations with e2e names (set default and delete also check the live name). Pull request edits
(edit_comment, delete_comment, dismiss_review, mark_pull_ready, convert_pull_to_draft, reopen_pull) require a pull
request whose head is a run branch of the same repository (naming.branch_run_id: ``e2e/<run>/...``,
``otterdog/e2e-<run>-...`` or the blueprint remediation branch ``otterdog/blueprint/e2e-<run>-...``). Security
advisories cannot be deleted through the API: their summary must start with an e2e prefix and close_security_advisory
closes them (deleting the run repository removes them).
"""

from __future__ import annotations

import base64
import logging
import math
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeVar

from otterdog_e2e import naming
from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.safety import VerifiedOrg

logger = logging.getLogger(__name__)
T = TypeVar("T")

DRY_RUN_SHA = "0" * 40
FILE_MODE = "100644"
EMPTY_REPO_TIMEOUT = 30.0  # create_branch / commit_files retry 409 (empty repository) for up to 30 s
EMPTY_REPO_INTERVAL = 3.0
MERGE_RETRIES = 3  # merge_pull retries 405 (not mergeable yet) 3 times, 5 s apart
MERGE_INTERVAL = 5.0
FAST_FORWARD_ATTEMPTS = 3  # commit_files re-reads the branch when its PATCH is not a fast-forward (422)
DISPATCH_ATTEMPTS = 6  # dispatch_workflow retries 404/422 (a just-pushed workflow is not indexed yet) 5 s apart
DISPATCH_INTERVAL = 5.0
# repository fields that are never changed on protected (non-e2e) repositories
GUARDED_REPO_FIELDS = frozenset({"name", "archived", "private", "visibility", "default_branch"})
TEAM_ROLES = frozenset({"member", "maintainer"})
DEFAULT_FOR_NEW_REPOS = frozenset({"all", "none", "private_and_internal", "public"})
ADVISORY_SEVERITIES = frozenset({"critical", "high", "medium", "low"})
DRY_RUN_GHSA = "GHSA-0000-0000-0000"

BPR_NODE_QUERY = (
    "query($id: ID!) { node(id: $id) { ... on BranchProtectionRule { pattern repository { name owner { login } } } } }"
)
DELETE_BPR_MUTATION = (
    "mutation($id: ID!) { deleteBranchProtectionRule(input: {branchProtectionRuleId: $id}) { clientMutationId } }"
)
READY_FOR_REVIEW_MUTATION = (
    "mutation($id: ID!) { markPullRequestReadyForReview(input: {pullRequestId: $id}) { pullRequest { isDraft } } }"
)
CONVERT_TO_DRAFT_MUTATION = (
    "mutation($id: ID!) { convertPullRequestToDraft(input: {pullRequestId: $id}) { pullRequest { isDraft } } }"
)


def _q(value: str) -> str:
    """URL-encode one path segment."""
    return urllib.parse.quote(str(value), safe="")


def _full_ref(ref: str) -> str:
    """``refs/<ref>`` for ``heads/<b>`` / ``tags/<t>`` (already qualified refs are kept)."""
    return ref if ref.startswith("refs/") else f"refs/{ref}"


def _short_ref(ref: str) -> str:
    """``heads/<b>`` / ``tags/<t>`` without the ``refs/`` prefix."""
    return ref.removeprefix("refs/")


def _issue_number(issue_url: Any) -> int | None:
    """The issue (pull request) number at the end of an ``issue_url`` (``.../issues/<n>``), or None."""
    head, _, number = str(issue_url or "").rpartition("/issues/")
    return int(number) if head and number.isdigit() else None


def accept_org_invitation(http: GitHubHttp, verified: VerifiedOrg) -> dict[str, Any]:
    """PATCH /user/memberships/orgs/{org} {state: active} with the invited identity's own write-scoped client."""
    return dict(http.patch(f"/user/memberships/orgs/{_q(verified.login)}", json={"state": "active"}) or {})


def publicize_membership(http: GitHubHttp, verified: VerifiedOrg, login: str) -> None:
    """PUT /orgs/{org}/public_members/{login} with the member's own write-scoped client."""
    http.put(f"/orgs/{_q(verified.login)}/public_members/{_q(login)}", expected=(204,))


class _BranchMovedError(GitHubError):
    """The fast-forward PATCH of commit_files was rejected (the branch moved since it was read)."""

    def __init__(self, message: str) -> None:
        """Keep the original error text."""
        super().__init__(422, "PATCH", "git/refs", message)


class Mutator:
    """Mutating GitHub calls scoped to the verified test org."""

    def __init__(self, http: GitHubHttp, verified: VerifiedOrg, *, dry_run: bool = False) -> None:
        """Bind a write-scoped client to the verified org (dry_run logs instead of writing)."""
        scope = getattr(http, "write_scope", None)
        if not dry_run and (scope is None or scope.org_id != verified.org_id or getattr(http, "read_only", False)):
            raise SafetyError(f"Mutator needs a GitHubHttp write-scoped to the verified org {verified.login!r}")
        self.http = http
        self.verified = verified
        self.dry_run = dry_run

    @property
    def org(self) -> str:
        """Login of the verified org."""
        return self.verified.login

    # --- helpers ------------------------------------------------------------------------------------------------
    def _repo(self, repo: str) -> str:
        """``/repos/{org}/{repo}`` path prefix."""
        return f"/repos/{_q(self.org)}/{_q(repo)}"

    @property
    def _orgp(self) -> str:
        """``/orgs/{org}`` path prefix."""
        return f"/orgs/{_q(self.org)}"

    def _sleep(self, seconds: float) -> None:
        """Sleep with the client's (injectable) sleep function."""
        sleep: Callable[[float], None] | None = getattr(self.http, "sleep", None)
        if sleep is not None:
            sleep(seconds)

    def _write(self, method: str, path: str, *, json: Any = None, **kw: Any) -> Any:
        """One mutating call (logged only in dry_run); returns the decoded body."""
        if self.dry_run:
            logger.info("dry-run: %s %s", method, path)
            return None
        logger.debug("%s %s", method, path)
        return getattr(self.http, method.lower())(path, json=json, **kw)

    def _delete(self, path: str) -> None:
        """DELETE ignoring 404 (logged only in dry_run)."""
        if self.dry_run:
            logger.info("dry-run: DELETE %s", path)
            return
        logger.info("DELETE %s", path)
        self.http.delete(path, allow_404=True)

    def _check_name(self, kind: str, name: str, *, force: bool = False) -> None:
        """SafetyError for deleting a non-e2e name without force."""
        if force:
            logger.warning("force-deleting %s %r (bootstrap)", kind, name)
            return
        if not naming.is_e2e_name(name):
            raise SafetyError(f"refusing to delete {kind} {name!r}: not an e2e name")

    @staticmethod
    def _require_e2e(kind: str, name: str, action: str) -> None:
        """SafetyError unless ``name`` is an e2e name: probe and drift writes only touch run objects."""
        if not naming.is_e2e_name(name):
            raise SafetyError(f"refusing to {action} {kind} {name!r}: not an e2e name")

    def _check_e2e_pull(self, repo: str, number: int) -> dict[str, Any]:
        """The pull request when its head is a run branch of ``repo`` itself (else SafetyError, also in dry-run)."""
        pull = self.http.get(f"{self._repo(repo)}/pulls/{int(number)}", allow_404=True)
        if not isinstance(pull, dict):
            raise SafetyError(f"refusing to change pull request {repo}#{number}: not found")
        head = pull.get("head") or {}
        ref = str(head.get("ref") or "")
        source = str((head.get("repo") or {}).get("full_name") or "")
        if naming.branch_run_id(ref) is None or source.lower() != f"{self.org}/{repo}".lower():
            raise SafetyError(
                f"refusing to change pull request {repo}#{number}: its head {source or '?'}:{ref} is not a run branch"
            )
        return pull

    def _graphql_write(self, label: str, document: str, variables: Mapping[str, Any]) -> None:
        """One GraphQL mutation (logged only in dry_run)."""
        if self.dry_run:
            logger.info("dry-run: %s", label)
            return
        logger.info("%s", label)
        self.http.graphql(document, variables)

    def _retry_status(self, fn: Callable[[], T], statuses: Sequence[int], attempts: int, interval: float) -> T:
        """Call ``fn``, retrying GitHubErrors whose status is in ``statuses`` (``attempts`` tries in total)."""
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except GitHubError as exc:
                if exc.status not in statuses or attempt >= attempts:
                    raise
                logger.info("HTTP %s, retrying in %.0f s (%d/%d)", exc.status, interval, attempt, attempts)
                self._sleep(interval)
        raise AssertionError("unreachable")

    def _empty_repo_retry(self, fn: Callable[[], T]) -> T:
        """Retry 409 (empty repository) for up to EMPTY_REPO_TIMEOUT seconds."""
        attempts = math.ceil(EMPTY_REPO_TIMEOUT / EMPTY_REPO_INTERVAL) + 1
        return self._retry_status(fn, (409,), attempts, EMPTY_REPO_INTERVAL)

    # --- git ----------------------------------------------------------------------------------------------------
    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        """POST git/refs refs/heads/{branch}; retries 409 (empty repo) for up to 30 s."""
        self._empty_repo_retry(lambda: self.create_ref(repo, f"refs/heads/{branch}", from_sha))

    def delete_ref(self, repo: str, ref: str) -> None:
        """DELETE git/refs/{ref} for ``heads/<b>`` or ``tags/<t>`` (guarded by naming.is_deletable_ref; 404/422 ignored)."""
        short = _short_ref(ref)
        if not naming.is_deletable_ref(short):
            raise SafetyError(f"refusing to delete ref {ref!r} in {repo!r}: not an e2e ref")
        path = f"{self._repo(repo)}/git/refs/{urllib.parse.quote(short, safe='/')}"
        if self.dry_run:
            logger.info("dry-run: DELETE %s", path)
            return
        logger.info("DELETE %s", path)
        self.http.request("DELETE", path, allow=(404, 422))

    def put_file(self, repo: str, path: str, content: str, message: str, *, branch: str, sha: str | None = None) -> str:
        """PUT contents/{path} on ``branch`` (``sha`` of the file being replaced); returns the commit sha."""
        body: dict[str, Any] = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("ascii"),
            "branch": branch,
        }
        if sha:
            body["sha"] = sha
        url = f"{self._repo(repo)}/contents/{urllib.parse.quote(path.lstrip('/'), safe='/')}"
        result = self._write("PUT", url, json=body)
        return str(result["commit"]["sha"]) if result else DRY_RUN_SHA

    def commit_files(self, repo: str, branch: str, files: Mapping[str, str | None], message: str) -> str:
        """One commit writing (str) or deleting (None, only if present) files on ``branch``; returns the commit sha.

        GET git/ref/heads/{b} -> GET git/commits/{sha} -> POST git/trees {base_tree, tree} -> POST git/commits ->
        PATCH git/refs/heads/{b} {sha, force: false}. 409 (empty repo) is retried for 30 s; a 422 of the PATCH (the
        branch moved meanwhile) restarts the flow (3 attempts). An unchanged tree still produces a commit.
        """
        if self.dry_run:
            logger.info("dry-run: commit %d file(s) to %s:%s", len(files), repo, branch)
            return DRY_RUN_SHA
        for attempt in range(1, FAST_FORWARD_ATTEMPTS + 1):
            try:
                return self._empty_repo_retry(lambda: self._commit_once(repo, branch, files, message))
            except _BranchMovedError:
                if attempt >= FAST_FORWARD_ATTEMPTS:
                    raise
                logger.info(
                    "%s:%s moved while committing, retrying (%d/%d)", repo, branch, attempt, FAST_FORWARD_ATTEMPTS
                )
        raise AssertionError("unreachable")

    def _commit_once(self, repo: str, branch: str, files: Mapping[str, str | None], message: str) -> str:
        """One pass of the commit_files flow."""
        ref_path = urllib.parse.quote(f"heads/{branch}", safe="/")
        head = self.http.get(f"{self._repo(repo)}/git/ref/{ref_path}")["object"]["sha"]
        base_tree = self.http.get(f"{self._repo(repo)}/git/commits/{head}")["tree"]["sha"]
        entries: list[dict[str, Any]] = [
            {"path": path, "mode": FILE_MODE, "type": "blob", "content": content}
            for path, content in files.items()
            if content is not None
        ]
        deletions = [path for path, content in files.items() if content is None]
        present = self._present_paths(repo, base_tree, head, deletions)
        entries += [
            {"path": path, "mode": FILE_MODE, "type": "blob", "sha": None} for path in deletions if path in present
        ]
        tree = self.http.post(f"{self._repo(repo)}/git/trees", json={"base_tree": base_tree, "tree": entries})
        commit = self.create_commit(repo, tree_sha=tree["sha"], parents=[head], message=message)
        try:
            self.update_ref(repo, f"heads/{branch}", commit, force=False)
        except GitHubError as exc:
            if exc.status == 422:
                raise _BranchMovedError(str(exc)) from exc
            raise
        return commit

    def _present_paths(self, repo: str, base_tree: str, head: str, paths: Sequence[str]) -> set[str]:
        """Which of ``paths`` exist in ``base_tree`` (recursive tree listing, per-path lookups when truncated)."""
        if not paths:
            return set()
        listing = self.http.get(f"{self._repo(repo)}/git/trees/{base_tree}", params={"recursive": "1"})
        present = {entry["path"] for entry in listing.get("tree", []) if entry.get("type") == "blob"}
        if not listing.get("truncated"):
            return present & set(paths)
        found = set()
        for path in paths:
            url = f"{self._repo(repo)}/contents/{urllib.parse.quote(path, safe='/')}"
            if path in present or self.http.get(url, params={"ref": head}, allow_404=True) is not None:
                found.add(path)
        return found

    def create_commit(self, repo: str, *, tree_sha: str, parents: Sequence[str], message: str) -> str:
        """POST git/commits; returns the commit sha."""
        body = {"message": message, "tree": tree_sha, "parents": list(parents)}
        result = self._write("POST", f"{self._repo(repo)}/git/commits", json=body)
        return str(result["sha"]) if result else DRY_RUN_SHA

    def create_ref(self, repo: str, ref: str, sha: str) -> dict[str, Any]:
        """POST git/refs {ref: "refs/<ref>", sha}; a 422 (already exists) raises GitHubError."""
        full = _full_ref(ref)
        result = self._write("POST", f"{self._repo(repo)}/git/refs", json={"ref": full, "sha": sha})
        return dict(result) if result else {"ref": full, "object": {"sha": sha, "type": "commit"}, "dry_run": True}

    def update_ref(self, repo: str, ref: str, sha: str, *, force: bool = False) -> None:
        """PATCH git/refs/{ref} {sha, force} (force only for deletable e2e refs: it can drop history)."""
        short = _short_ref(ref)
        if force and not naming.is_deletable_ref(short):
            raise SafetyError(f"refusing to force-update ref {ref!r} in {repo!r}: not an e2e ref")
        path = f"{self._repo(repo)}/git/refs/{urllib.parse.quote(short, safe='/')}"
        self._write("PATCH", path, json={"sha": sha, "force": force})

    # --- pull requests ------------------------------------------------------------------------------------------
    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str = "", draft: bool = False
    ) -> dict[str, Any]:
        """POST pulls; returns the pull request."""
        payload = {"head": head, "base": base, "title": title, "body": body, "draft": draft}
        return dict(self._write("POST", f"{self._repo(repo)}/pulls", json=payload) or {"dry_run": True})

    def comment(self, repo: str, number: int, body: str) -> dict[str, Any]:
        """POST issues/{number}/comments; returns the comment."""
        path = f"{self._repo(repo)}/issues/{int(number)}/comments"
        return dict(self._write("POST", path, json={"body": body}) or {"dry_run": True})

    def review(self, repo: str, number: int, *, event: str = "APPROVE", body: str = "") -> dict[str, Any]:
        """POST pulls/{number}/reviews; returns the review."""
        payload: dict[str, Any] = {"event": event}
        if body:
            payload["body"] = body
        path = f"{self._repo(repo)}/pulls/{int(number)}/reviews"
        return dict(self._write("POST", path, json=payload) or {"dry_run": True})

    def merge_pull(self, repo: str, number: int, *, method: str = "squash", sha: str | None = None) -> dict[str, Any]:
        """PUT pulls/{number}/merge; retries 405 3x 5 s apart, never retries 409 when ``sha`` is given."""
        payload: dict[str, Any] = {"merge_method": method}
        if sha:
            payload["sha"] = sha
        path = f"{self._repo(repo)}/pulls/{int(number)}/merge"
        statuses = (405,) if sha else (405, 409)
        result = self._retry_status(
            lambda: self._write("PUT", path, json=payload), statuses, MERGE_RETRIES + 1, MERGE_INTERVAL
        )
        return dict(result or {"dry_run": True})

    def close_pull(self, repo: str, number: int) -> None:
        """PATCH pulls/{number} {state: closed}."""
        self._write("PATCH", f"{self._repo(repo)}/pulls/{int(number)}", json={"state": "closed"})

    def reopen_pull(self, repo: str, number: int) -> None:
        """PATCH pulls/{number} {state: open}: reopen a closed pull request of a run branch (GitHub refuses it while
        the head branch is deleted: recreate it first with create_ref)."""
        self._check_e2e_pull(repo, number)
        self._write("PATCH", f"{self._repo(repo)}/pulls/{int(number)}", json={"state": "open"})

    def edit_comment(self, repo: str, comment_id: int, body: str) -> dict[str, Any]:
        """PATCH issues/comments/{id} {body}: the comment must belong to a pull request of a run branch (the webapp
        re-runs an edited ``/otterdog`` command)."""
        path = f"{self._repo(repo)}/issues/comments/{int(comment_id)}"
        comment = self.http.get(path, allow_404=True)
        number = _issue_number(comment.get("issue_url")) if isinstance(comment, dict) else None
        if number is None:
            raise SafetyError(f"refusing to edit comment {comment_id} of {repo}: not found or not on a pull request")
        self._check_e2e_pull(repo, number)
        return dict(
            self._write("PATCH", path, json={"body": body}) or {"id": comment_id, "body": body, "dry_run": True}
        )

    def delete_comment(self, repo: str, comment_id: int) -> None:
        """DELETE issues/comments/{id} (204; a vanished comment is left alone): the comment must belong to a pull
        request of a run branch (the webapp ignores ``deleted`` issue_comment events)."""
        path = f"{self._repo(repo)}/issues/comments/{int(comment_id)}"
        comment = self.http.get(path, allow_404=True)
        if comment is None:
            logger.info("comment %s of %s already gone", comment_id, repo)
            return
        number = _issue_number(comment.get("issue_url")) if isinstance(comment, dict) else None
        if number is None:
            raise SafetyError(f"refusing to delete comment {comment_id} of {repo}: not on a pull request")
        self._check_e2e_pull(repo, number)
        self._delete(path)

    def dismiss_review(
        self, repo: str, number: int, review_id: int, *, message: str = "e2e: dismissed"
    ) -> dict[str, Any]:
        """PUT pulls/{number}/reviews/{review_id}/dismissals {message, event: DISMISS} (a run branch pull request)."""
        self._check_e2e_pull(repo, number)
        path = f"{self._repo(repo)}/pulls/{int(number)}/reviews/{int(review_id)}/dismissals"
        result = self._write("PUT", path, json={"message": message, "event": "DISMISS"})
        return dict(result or {"id": review_id, "state": "DISMISSED", "dry_run": True})

    def mark_pull_ready(self, repo: str, number: int) -> None:
        """GraphQL markPullRequestReadyForReview (draft -> ready; pull request of a run branch)."""
        pull = self._check_e2e_pull(repo, number)
        self._graphql_write(
            f"markPullRequestReadyForReview {repo}#{number}", READY_FOR_REVIEW_MUTATION, {"id": pull["node_id"]}
        )

    def convert_pull_to_draft(self, repo: str, number: int) -> None:
        """GraphQL convertPullRequestToDraft (ready -> draft; pull request of a run branch)."""
        pull = self._check_e2e_pull(repo, number)
        self._graphql_write(
            f"convertPullRequestToDraft {repo}#{number}", CONVERT_TO_DRAFT_MUTATION, {"id": pull["node_id"]}
        )

    # --- repositories, teams and org objects ---------------------------------------------------------------------
    def patch_repo(self, repo: str, **fields: Any) -> dict[str, Any]:
        """PATCH /repos/{org}/{repo} (drift injection); returns the repository (GUARDED_REPO_FIELDS: e2e repos only)."""
        guarded = sorted(GUARDED_REPO_FIELDS & set(fields))
        if guarded and not naming.is_e2e_name(repo):
            raise SafetyError(f"refusing to change {guarded} of non-e2e repository {repo!r}")
        return dict(self._write("PATCH", self._repo(repo), json=fields) or {"name": repo, **fields})

    def create_repo(
        self, name: str, *, private: bool = False, description: str = "", auto_init: bool = True
    ) -> dict[str, Any]:
        """POST /orgs/{org}/repos (bootstrap for protected names, else e2e names only)."""
        if not naming.is_e2e_name(name):
            logger.info("creating non-e2e repository %r (bootstrap)", name)
        payload = {"name": name, "private": private, "description": description, "auto_init": auto_init}
        result = self._write("POST", f"{self._orgp}/repos", json=payload)
        return dict(result or {"name": name, "private": private, "default_branch": "main", "dry_run": True})

    def delete_repo(self, name: str, *, force: bool = False) -> None:
        """DELETE /repos/{org}/{name} (e2e names only unless force)."""
        self._check_name("repository", name, force=force)
        self._delete(self._repo(name))

    def delete_team(self, slug: str, *, force: bool = False) -> None:
        """DELETE /orgs/{org}/teams/{slug} (e2e names only unless force)."""
        self._check_name("team", slug, force=force)
        self._delete(f"{self._orgp}/teams/{_q(slug)}")

    def _check_hook(self, path: str, hook_id: int) -> bool:
        """True when the hook exists and its live config.url is under HOOK_BASE (SafetyError otherwise)."""
        hook = self.http.get(path, allow_404=True)
        if hook is None:
            logger.info("hook %s already gone", hook_id)
            return False
        url = str((hook.get("config") or {}).get("url") or "")
        if not url.startswith(naming.HOOK_BASE):
            raise SafetyError(f"refusing to delete hook {hook_id}: url {url!r} is not under {naming.HOOK_BASE}")
        return True

    def delete_org_hook(self, hook_id: int) -> None:
        """DELETE /orgs/{org}/hooks/{id} (only when the live config.url starts with HOOK_BASE)."""
        path = f"{self._orgp}/hooks/{int(hook_id)}"
        if self._check_hook(path, hook_id):
            self._delete(path)

    def delete_repo_hook(self, repo: str, hook_id: int) -> None:
        """DELETE /repos/{org}/{repo}/hooks/{id} (only when the live config.url starts with HOOK_BASE)."""
        path = f"{self._repo(repo)}/hooks/{int(hook_id)}"
        if self._check_hook(path, hook_id):
            self._delete(path)

    def delete_org_secret(self, name: str) -> None:
        """DELETE /orgs/{org}/actions/secrets/{name} (e2e names only)."""
        self._check_name("org secret", name)
        self._delete(f"{self._orgp}/actions/secrets/{_q(name)}")

    def delete_org_variable(self, name: str) -> None:
        """DELETE /orgs/{org}/actions/variables/{name} (e2e names only)."""
        self._check_name("org variable", name)
        self._delete(f"{self._orgp}/actions/variables/{_q(name)}")

    def _check_live_name(self, kind: str, path: str, name: str, *, key: str = "name") -> bool:
        """True when the object at ``path`` exists and carries ``name`` (SafetyError on a different name)."""
        live = self.http.get(path, allow_404=True)
        if live is None:
            logger.info("%s %r already gone", kind, name)
            return False
        if live.get(key) != name:
            raise SafetyError(f"refusing to delete {kind} {path}: live name {live.get(key)!r} != {name!r}")
        return True

    def delete_org_ruleset(self, ruleset_id: int, *, name: str) -> None:
        """DELETE /orgs/{org}/rulesets/{id} (``name`` must be an e2e name and match the live ruleset)."""
        self._check_name("org ruleset", name)
        path = f"{self._orgp}/rulesets/{int(ruleset_id)}"
        if self._check_live_name("org ruleset", path, name):
            self._delete(path)

    def delete_custom_property(self, name: str) -> None:
        """DELETE /orgs/{org}/properties/schema/{name} (e2e names only)."""
        self._check_name("custom property", name)
        self._delete(f"{self._orgp}/properties/schema/{_q(name)}")

    def delete_org_role(self, role_id: int, *, name: str) -> None:
        """DELETE /orgs/{org}/organization-roles/{id} (``name`` must be an e2e name and match the live role)."""
        self._check_name("org role", name)
        path = f"{self._orgp}/organization-roles/{int(role_id)}"
        if self._check_live_name("org role", path, name):
            self._delete(path)

    def delete_repo_ruleset(self, repo: str, ruleset_id: int, *, name: str) -> None:
        """DELETE /repos/{org}/{repo}/rulesets/{id} (``name`` must be an e2e name and match the live ruleset)."""
        self._check_name("repo ruleset", name)
        path = f"{self._repo(repo)}/rulesets/{int(ruleset_id)}"
        if self._check_live_name("repo ruleset", path, name):
            self._delete(path)

    def delete_branch_protection_rule(self, repo: str, rule_id: str, *, pattern: str) -> None:
        """GraphQL deleteBranchProtectionRule (the pattern must carry a run id; the live rule must be ours)."""
        if naming.extract_run_id(pattern) is None:
            raise SafetyError(f"refusing to delete branch protection rule {pattern!r}: no e2e run id")
        node = (self.http.graphql(BPR_NODE_QUERY, {"id": rule_id}).get("node")) or {}
        repository = node.get("repository") or {}
        owner = str((repository.get("owner") or {}).get("login") or "")
        if not node:
            logger.info("branch protection rule %r already gone", pattern)
            return
        if node.get("pattern") != pattern or repository.get("name") != repo or owner.lower() != self.org.lower():
            raise SafetyError(
                f"refusing to delete branch protection rule {rule_id}: it is not {self.org}/{repo}:{pattern}"
            )
        if self.dry_run:
            logger.info("dry-run: deleteBranchProtectionRule %s:%s", repo, pattern)
            return
        logger.info("deleteBranchProtectionRule %s:%s", repo, pattern)
        self.http.graphql(DELETE_BPR_MUTATION, {"id": rule_id})

    def delete_environment(self, repo: str, name: str) -> None:
        """DELETE /repos/{org}/{repo}/environments/{name} (e2e names only)."""
        self._check_name("environment", name)
        self._delete(f"{self._repo(repo)}/environments/{_q(name)}")

    def delete_repo_secret(self, repo: str, name: str) -> None:
        """DELETE /repos/{org}/{repo}/actions/secrets/{name} (e2e names only)."""
        self._check_name("repo secret", name)
        self._delete(f"{self._repo(repo)}/actions/secrets/{_q(name)}")

    def delete_repo_variable(self, repo: str, name: str) -> None:
        """DELETE /repos/{org}/{repo}/actions/variables/{name} (e2e names only)."""
        self._check_name("repo variable", name)
        self._delete(f"{self._repo(repo)}/actions/variables/{_q(name)}")

    def ping_repo_hook(self, repo: str, hook_id: int) -> datetime:
        """POST /repos/{org}/{repo}/hooks/{id}/pings; returns GitHub's time of the ping (its Date header, else the
        local clock): deliveries older than that are not this ping's."""
        self._write("POST", f"{self._repo(repo)}/hooks/{int(hook_id)}/pings", expected=(204,))
        return self._server_time()

    def ping_org_hook(self, hook_id: int) -> datetime:
        """POST /orgs/{org}/hooks/{id}/pings; returns GitHub's time of the ping (see ping_repo_hook)."""
        self._write("POST", f"{self._orgp}/hooks/{int(hook_id)}/pings", expected=(204,))
        return self._server_time()

    def _server_time(self) -> datetime:
        """GitHub's Date of the last response of the client (the local clock when it sent none)."""
        last = getattr(self.http, "last_date", None)
        return last if isinstance(last, datetime) and not self.dry_run else datetime.now(UTC)

    def ensure_membership(self, login: str) -> dict[str, Any]:
        """PUT /orgs/{org}/memberships/{login} {role: member} (bootstrap only); returns the membership.

        An existing membership (active or pending) is returned unchanged, so an owner is never demoted.
        """
        path = f"{self._orgp}/memberships/{_q(login)}"
        current = self.http.get(path, allow_404=True)
        if current is not None:
            return dict(current)
        return dict(self._write("PUT", path, json={"role": "member"}) or {"state": "pending", "dry_run": True})

    def set_org_description(self, description: str) -> None:
        """PATCH /orgs/{org} {description} (bootstrap only, after interactive confirmation)."""
        self._write("PATCH", self._orgp, json={"description": description})

    # --- repository drift: topics, collaborators, invitations --------------------------------------------------
    def set_repo_topics(self, repo: str, topics: Sequence[str]) -> list[str]:
        """PUT /repos/{org}/{repo}/topics {names} (replaces every topic; e2e repositories only); returns the topics."""
        self._require_e2e("repository", repo, "change the topics of")
        result = self._write("PUT", f"{self._repo(repo)}/topics", json={"names": list(topics)})
        return [str(topic) for topic in (result or {}).get("names", topics)]

    def add_repo_collaborator(self, repo: str, login: str, *, permission: str = "push") -> dict[str, Any]:
        """PUT /repos/{org}/{repo}/collaborators/{login} {permission} (e2e repositories only): an org member gets
        access at once ({}), anybody else an invitation (returned) that the user must accept."""
        self._require_e2e("repository", repo, "add a collaborator to")
        path = f"{self._repo(repo)}/collaborators/{_q(login)}"
        result = self._write("PUT", path, json={"permission": permission}, expected=(201, 204))
        if self.dry_run:
            return {"dry_run": True}
        return dict(result) if isinstance(result, dict) else {}

    def remove_repo_collaborator(self, repo: str, login: str) -> None:
        """DELETE /repos/{org}/{repo}/collaborators/{login} (e2e repositories only; 404 ignored)."""
        self._require_e2e("repository", repo, "remove a collaborator from")
        self._delete(f"{self._repo(repo)}/collaborators/{_q(login)}")

    def delete_repo_invitation(self, repo: str, invitation_id: int) -> None:
        """DELETE /repos/{org}/{repo}/invitations/{id} (an unanswered collaborator invitation; e2e repositories)."""
        self._require_e2e("repository", repo, "delete an invitation of")
        self._delete(f"{self._repo(repo)}/invitations/{int(invitation_id)}")

    # --- teams --------------------------------------------------------------------------------------------------
    def create_team(
        self, name: str, *, description: str = "", privacy: str = "closed", notification_setting: str | None = None
    ) -> dict[str, Any]:
        """POST /orgs/{org}/teams (e2e names only; GitHub makes the creating account a maintainer of the team)."""
        self._require_e2e("team", name, "create")
        payload: dict[str, Any] = {"name": name, "description": description, "privacy": privacy}
        if notification_setting is not None:
            payload["notification_setting"] = notification_setting
        result = self._write("POST", f"{self._orgp}/teams", json=payload)
        return dict(result or {"name": name, "slug": name, "privacy": privacy, "dry_run": True})

    def patch_team(self, slug: str, **fields: Any) -> dict[str, Any]:
        """PATCH /orgs/{org}/teams/{slug} (drift: description, privacy, notification_setting, ...; e2e teams only, a new
        name must be an e2e name too); returns the team."""
        self._require_e2e("team", slug, "change")
        if "name" in fields:
            self._require_e2e("team name", str(fields["name"]), "rename a team to")
        return dict(self._write("PATCH", f"{self._orgp}/teams/{_q(slug)}", json=fields) or {"slug": slug, **fields})

    def add_team_member(self, slug: str, login: str, *, role: str = "member") -> dict[str, Any]:
        """PUT /orgs/{org}/teams/{slug}/memberships/{login} {role} (member | maintainer; e2e teams only); returns the
        membership. ``login`` must already be an org member, active or pending (GET /orgs/{org}/memberships/{login}):
        for anybody else GitHub would send an invitation to the organization."""
        self._require_e2e("team", slug, "change the members of")
        if role not in TEAM_ROLES:
            raise ValueError(f"team role must be one of {sorted(TEAM_ROLES)}, got {role!r}")
        if self.http.get(f"{self._orgp}/memberships/{_q(login)}", allow_404=True) is None:
            raise SafetyError(
                f"refusing to add {login!r} to team {slug!r}: not an org member (GitHub would invite them)"
            )
        path = f"{self._orgp}/teams/{_q(slug)}/memberships/{_q(login)}"
        return dict(self._write("PUT", path, json={"role": role}) or {"role": role, "state": "active", "dry_run": True})

    def remove_team_member(self, slug: str, login: str) -> None:
        """DELETE /orgs/{org}/teams/{slug}/memberships/{login} (e2e teams only; 404 ignored)."""
        self._require_e2e("team", slug, "change the members of")
        self._delete(f"{self._orgp}/teams/{_q(slug)}/memberships/{_q(login)}")

    # --- workflows ----------------------------------------------------------------------------------------------
    def dispatch_workflow(
        self, repo: str, workflow_file: str, ref: str, inputs: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """POST actions/workflows/{workflow_file}/dispatches {ref, inputs, return_run_details} (e2e repositories only);
        returns {workflow_run_id, run_url, html_url} ({} when GitHub answers 204 without details). 404 and 422 (a
        workflow pushed moments ago is not indexed yet) are retried 5 s apart for 25 s."""
        self._require_e2e("repository", repo, "dispatch a workflow of")
        payload: dict[str, Any] = {"ref": ref, "return_run_details": True}
        if inputs:
            payload["inputs"] = dict(inputs)
        path = f"{self._repo(repo)}/actions/workflows/{_q(workflow_file)}/dispatches"
        result = self._retry_status(
            lambda: self._write("POST", path, json=payload, expected=(200, 204)),
            (404, 422),
            DISPATCH_ATTEMPTS,
            DISPATCH_INTERVAL,
        )
        if self.dry_run:
            return {"dry_run": True}
        return dict(result) if isinstance(result, dict) else {}

    def cancel_workflow_run(self, repo: str, run_id: int, *, force_cancel: bool = False) -> bool:
        """POST actions/runs/{run_id}/cancel (or force-cancel; e2e repositories only); False when GitHub answers 409
        (the run already completed)."""
        self._require_e2e("repository", repo, "cancel a workflow run of")
        path = f"{self._repo(repo)}/actions/runs/{int(run_id)}/{'force-cancel' if force_cancel else 'cancel'}"
        if self.dry_run:
            logger.info("dry-run: POST %s", path)
            return True
        logger.info("POST %s", path)
        return self.http.request("POST", path, expected=(202,), allow=(409,)).status_code == 202

    def rerun_workflow_run(self, repo: str, run_id: int) -> None:
        """POST actions/runs/{run_id}/rerun (e2e repositories only)."""
        self._require_e2e("repository", repo, "re-run a workflow run of")
        self._write("POST", f"{self._repo(repo)}/actions/runs/{int(run_id)}/rerun", expected=(201,))

    # --- repository security advisories -------------------------------------------------------------------------
    def create_security_advisory(
        self,
        repo: str,
        *,
        summary: str,
        description: str = "",
        severity: str = "low",
        ecosystem: str = "other",
        package: str | None = None,
        start_private_fork: bool = False,
    ) -> dict[str, Any]:
        """POST /repos/{org}/{repo}/security-advisories: a draft advisory (e2e repositories only; the summary must start
        with an e2e prefix since advisories cannot be deleted); returns it (ghsa_id, state, private_fork)."""
        self._require_e2e("repository", repo, "create a security advisory in")
        self._require_e2e("security advisory summary", summary, "create a security advisory with the")
        if severity not in ADVISORY_SEVERITIES:
            raise ValueError(f"severity must be one of {sorted(ADVISORY_SEVERITIES)}, got {severity!r}")
        payload = {
            "summary": summary,
            "description": description or summary,
            "severity": severity,
            "vulnerabilities": [{"package": {"ecosystem": ecosystem, "name": package or repo}}],
            "start_private_fork": start_private_fork,
        }
        result = self._write("POST", f"{self._repo(repo)}/security-advisories", json=payload)
        return dict(result or {"ghsa_id": DRY_RUN_GHSA, "state": "draft", "summary": summary, "dry_run": True})

    def create_advisory_fork(self, repo: str, ghsa_id: str) -> dict[str, Any]:
        """POST .../security-advisories/{ghsa_id}/forks: the temporary private fork ``<repo>-ghsa-...`` (created
        asynchronously, up to 5 minutes; e2e repositories only); returns the fork repository."""
        self._require_e2e("repository", repo, "fork a security advisory of")
        path = f"{self._repo(repo)}/security-advisories/{_q(ghsa_id)}/forks"
        result = self._write("POST", path, expected=(202,))
        return dict(result or {"name": f"{repo}-{ghsa_id.lower()}", "private": True, "dry_run": True})

    def close_security_advisory(self, repo: str, ghsa_id: str) -> dict[str, Any]:
        """PATCH .../security-advisories/{ghsa_id} {state: closed} (e2e repositories, e2e summaries; an already
        closed or vanished advisory is left alone); returns the advisory ({} when it is gone)."""
        self._require_e2e("repository", repo, "close a security advisory of")
        path = f"{self._repo(repo)}/security-advisories/{_q(ghsa_id)}"
        live = self.http.get(path, allow_404=True)
        if not isinstance(live, dict):
            logger.info("security advisory %s of %s already gone", ghsa_id, repo)
            return {}
        self._require_e2e("security advisory summary", str(live.get("summary") or ""), "close an advisory with the")
        if live.get("state") == "closed":
            return dict(live)
        return dict(
            self._write("PATCH", path, json={"state": "closed"}) or {**live, "state": "closed", "dry_run": True}
        )

    # --- code security configurations ---------------------------------------------------------------------------
    def create_code_security_configuration(
        self, name: str, *, description: str = "otterdog-e2e probe", **settings: Any
    ) -> dict[str, Any]:
        """POST /orgs/{org}/code-security/configurations {name, description, **settings} (e2e names only; settings
        are the documented fields, e.g. dependency_graph='enabled'); returns the configuration (id)."""
        self._require_e2e("code security configuration", name, "create")
        payload = {"name": name, "description": description, **settings}
        result = self._write("POST", f"{self._orgp}/code-security/configurations", json=payload)
        return dict(result or {"id": 0, "name": name, "dry_run": True})

    def set_code_security_default(
        self, configuration_id: int, *, name: str, default_for_new_repos: str
    ) -> dict[str, Any]:
        """PUT .../code-security/configurations/{id}/defaults {default_for_new_repos} (all | none | public |
        private_and_internal; ``name`` must be an e2e name and match the live configuration)."""
        if default_for_new_repos not in DEFAULT_FOR_NEW_REPOS:
            raise ValueError(f"default_for_new_repos must be one of {sorted(DEFAULT_FOR_NEW_REPOS)}")
        self._require_e2e("code security configuration", name, "change the defaults of")
        path = f"{self._orgp}/code-security/configurations/{int(configuration_id)}"
        if not self._check_live_name("code security configuration", path, name):
            raise GitHubError(404, "GET", path, f"code security configuration {name!r} not found")
        result = self._write("PUT", f"{path}/defaults", json={"default_for_new_repos": default_for_new_repos})
        return dict(result or {"default_for_new_repos": default_for_new_repos, "dry_run": True})

    def delete_code_security_configuration(self, configuration_id: int, *, name: str) -> None:
        """DELETE /orgs/{org}/code-security/configurations/{id} (``name`` must be an e2e name and match the live
        configuration; repositories attached to it keep their settings)."""
        self._check_name("code security configuration", name)
        path = f"{self._orgp}/code-security/configurations/{int(configuration_id)}"
        if self._check_live_name("code security configuration", path, name):
            self._delete(path)
