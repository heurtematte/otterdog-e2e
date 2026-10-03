"""The config-repo PR workflow driven against the webapp (SPEC 13.4).

ConfigRepoFlow targets the ORG CONFIG repo (``target.config_repo_for(run_ctx)``) while otterdog.json lives in
``target.configs_repo``. Before pushing, approving, merging or commenting ``/otterdog merge|apply``, every config text
passes ``guard(base_text, head_text)`` (BaselineManager.guard_config_change: a local-plan with the trusted reset CLI,
SEC-07; it raises SafetyError to refuse, its return value is ignored): the webapp applies merges with
delete_resources=True. For approvals, merges and ``/otterdog merge|apply`` the guard gets ``allow_invalid_head`` only
when the SUT's own validation status on the head is failure/error (guard_pr, DESTR-04). Failure messages tell
"delivery not observed within N s (infra)" from "webapp did not react within M s (SUT)".

Waits (GH-04): every harness action records its triggering delivery (pull_request opened/synchronize/closed,
pull_request_review submitted, issue_comment created). With a relay, wait_status / wait_comment / wait_merged first wait
for that delivery (matched by PR number plus head sha or comment id, never by clocks alone) and then count their own
timeout from the delivery's forward time. Webapp facts: comments are posted by ``<slug>[bot]`` (GraphQL author login
``<slug>``), markers are ``<!-- Otterdog Comment: <name> -->`` (templates/comment/*), commands are matched with
re.match(r"/otterdog\\s+<cmd>") at the very start of the body, the config lives at ``otterdog/<org>.jsonnet``.

Beyond the basic flow: multi-file PRs and PRs touching only non-config files (``open_pr_files`` / ``push_files``),
draft PRs (``open_pr(draft=True)``, ``mark_ready``, ``convert_to_draft``), ``reopen``, comment edits and deletions
(``edit_comment`` re-runs the guard for /otterdog merge|apply: the webapp handles ``edited`` comments like new ones),
``request_changes`` and ``dismiss_review``, the merge methods merge|squash|rebase, and ``adopt_pr`` for PRs the harness
did not open but that belong to this run (otterdog open-pr branches ``otterdog/e2e-<run>-*``, blueprint remediation
branches ``otterdog/blueprint/e2e-<run>-*``). Only PRs, comments and reviews of this flow can be changed. The
mutations go through the identity's Mutator (reopen_pull, mark_pull_ready, convert_pull_to_draft, edit_comment,
delete_comment, dismiss_review), which checks again that the PR head is a run branch of the repository
(naming.branch_run_id); a Mutator stand-in without one of them raises ConfigRepoError naming it.
"""

from __future__ import annotations

import dataclasses
import inspect
import logging
import posixpath
import re
import time
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from otterdog_e2e import naming, waiting
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.webhooks.relay import DeliveryRelay, RelayedDelivery

_logger = logging.getLogger(__name__)

MARKERS = {
    name: f"<!-- Otterdog Comment: {name} -->"
    for name in ("help", "team-info", "validate", "check-sync", "automerge", "blueprint-dismissal")
}
APPLIED_TEXTS = ("The following changes have been applied successfully", "[!CAUTION]")
GUARDED_COMMANDS = ("/otterdog merge", "/otterdog apply")
INVALID_STATES = frozenset({"failure", "error"})  # validation statuses of a PR the SUT itself will never apply
SYNC_FAILED_DESCRIPTION = "otterdog sync check failed, check comment history"
_MARKER_RE = re.compile(r"<!--\s*Otterdog Comment:\s*([\w-]+)\s*-->")
_GUARDED_RE = re.compile(r"/otterdog\s+(merge|apply)")  # comment_handlers.py: pattern.match on the raw body
DELIVERY_CLOCK_SKEW = timedelta(seconds=60)  # GitHub's delivered_at vs. the harness clock
POLL_INTERVAL = 5.0
BOT_SUFFIX = "[bot]"
GITHUB_WRAP_WIDTH = 110  # IndentingPrinter(output_for_github=True) uses a 110-column rich console
_ANSI_RE = re.compile(r"(\x9B|\x1B\[)[0-?]*[ -/]*[@-~]")
_BOX_CHARS_RE = re.compile(r"[─-╿]")  # box drawing characters of otterdog's default message box
# a diff/box column character followed by whitespace: at a line start, standalone, or glued to the previous word by
# escape_for_github ("a - b" -> "a- b"); never part of '-->', '<!--', '->', '[!NOTE]' or 'C++'
_DIFF_MARK_RE = re.compile(r"""(?<![^\s\w"'\)\]\}])[-+!~](?=\s|$)""")
_WS_RE = re.compile(r"\s+")
_CONTEXT_ALIASES = ("validation", "validate", "sync")
MERGE_METHODS = ("merge", "squash", "rebase")  # PUT pulls/{n}/merge merge_method
BLUEPRINT_BRANCH_PREFIX = naming.BLUEPRINT_BRANCH_PREFIX  # remediation branches: otterdog/blueprint/<id>


class FlowError(AssertionError):
    """A config-repo flow expectation failed; ``infra`` tells harness/GitHub problems from SUT problems."""

    infra = False


class DeliveryTimeoutError(FlowError):
    """The delivery triggered by a harness action was not observed (or not forwarded): infrastructure problem."""

    infra = True


class ReactionTimeoutError(FlowError):
    """The webapp did not react to an observed delivery in time: problem of the system under test."""

    infra = False


class ConfigRepoError(RuntimeError):
    """Misuse of the flow (unknown identity, missing bot login, unreadable config)."""


@dataclass
class ConfigPr:
    """A config PR opened by the harness, with the ids of comments that existed before it."""

    number: int
    branch: str
    head_sha: str
    url: str
    author: str
    comment_ids_before: frozenset[str]


@dataclass
class _Trigger:
    """The last harness action on a PR and, once observed, the delivery it caused."""

    event: str
    action: str | None
    after: datetime
    head_sha: str | None = None
    comment_id: int | None = None
    delivery: RelayedDelivery | None = None


def _utc_now() -> datetime:
    """Current aware UTC time."""
    return datetime.now(UTC)


def run_branch(ref: str, run_id: str) -> bool:
    """True for a PR head branch of run ``run_id``: ``e2e/<run>/...``, ``otterdog/e2e-<run>-...`` (open-pr) or a
    blueprint remediation branch ``otterdog/blueprint/e2e-<run>-...`` (naming.branch_run_id)."""
    return naming.branch_run_id(ref) == run_id


def check_forwarded(delivery: RelayedDelivery, what: str) -> None:
    """FlowError when a relayed delivery was not handed to the webapp (infra), was rejected (infra: secret or signing
    mismatch) or made the webapp fail (5xx: SUT); ``what`` names it in the message."""
    if delivery.relay_status is None:
        raise DeliveryTimeoutError(
            f"{delivery.event} delivery {delivery.guid} for {what} was not forwarded (infra): {delivery.error}"
        )
    if delivery.relay_status >= 500:
        raise ReactionTimeoutError(
            f"webapp failed on {delivery.event} delivery {delivery.guid} for {what} (HTTP {delivery.relay_status}) (SUT)"
        )
    if delivery.relay_status >= 300:
        raise DeliveryTimeoutError(
            f"webapp rejected relayed {delivery.event} delivery {delivery.guid} (HTTP {delivery.relay_status}): "
            "webhook secret or relay signing mismatch (infra)"
        )


def checked_paths(files: Mapping[str, str | None]) -> dict[str, str | None]:
    """Validated copy of a {path: text or None (delete)} mapping: non-empty, repository-relative POSIX paths without
    ``..`` or ``.git`` components (ValueError)."""
    if not files:
        raise ValueError("at least one file is needed")
    checked: dict[str, str | None] = {}
    for path, text in files.items():
        normalized = posixpath.normpath(path) if isinstance(path, str) and path else ""
        parts = normalized.split("/")
        if (
            not normalized
            or normalized != path
            or path.startswith("/")
            or "\\" in path
            or ".." in parts
            or ".git" in parts
        ):
            raise ValueError(f"invalid repository path {path!r}")
        if text is not None and not isinstance(text, str):
            raise ValueError(f"the content of {path!r} must be a string (or None to delete the file)")
        checked[path] = text
    return checked


class ConfigRepoFlow:
    """Opens, updates, comments, approves, merges and closes config PRs and waits for the webapp's reactions."""

    def __init__(
        self,
        *,
        org: str,
        repo: str,
        oracle: Oracle,
        mutators: Mapping[str, Mutator],
        run_ctx: RunContext,
        validation_context: str,
        sync_context: str,
        guard: Callable[..., object],
        bot_login: str | None = None,
        relay: DeliveryRelay | None = None,
        delivery_timeout: float = 300,
        default_branch: str = "main",
    ) -> None:
        """Bind the flow to the org config repo; ``mutators`` maps identity names (admin, author, approver) to Mutators."""
        self.org = org
        self.repo = repo
        self.oracle = oracle
        self.mutators = dict(mutators)
        self.run_ctx = run_ctx
        self.validation_context = validation_context
        self.sync_context = sync_context
        self.guard = guard
        self.bot_login = bot_login
        self.relay = relay
        self.delivery_timeout = delivery_timeout
        self.default_branch = default_branch
        self.poll_interval = POLL_INTERVAL
        self.sleep: Callable[[float], None] = time.sleep  # injectable for tests
        self.clock: Callable[[], float] = time.monotonic
        self.now: Callable[[], datetime] = _utc_now
        self._prs: dict[int, ConfigPr] = {}
        self._identities: dict[int, str] = {}
        self._base_texts: dict[int, str] = {}
        self._texts_by_sha: dict[str, str] = {}
        self._triggers: dict[int, _Trigger] = {}
        self._consumed: set[int] = set()
        self._comments: dict[int, tuple[int, str]] = {}  # comment id -> (PR number, identity) of comments posted here
        self._reviews: dict[int, tuple[int, str]] = {}  # review id -> (PR number, identity) of reviews submitted here
        self._adopted: set[int] = set()  # PRs registered with adopt_pr (not opened by the flow)

    @property
    def config_path(self) -> str:
        """Path of the org config in the config repo: ``otterdog/<org>.jsonnet``."""
        return f"otterdog/{self.org}.jsonnet"

    # --- main branch ----------------------------------------------------------------------------------------------
    def main_sha(self) -> str:
        """Head sha of the default branch."""
        sha = self.oracle.branch_sha(self.repo, self.default_branch)
        if not sha:
            raise ConfigRepoError(f"{self.org}/{self.repo} has no branch {self.default_branch!r}")
        return sha

    def main_config(self) -> str | None:
        """Config text on the default branch (None when absent)."""
        return self.oracle.file_content(self.repo, self.config_path, ref=self.default_branch)

    def reset_main(self, text: str, *, message: str, identity: str = "admin") -> str:
        """Commit ``text`` to the default branch (guarded); returns the commit sha."""
        current = self.main_config()
        if current == text:
            return self.main_sha()
        if current is not None:
            self.guard_config(current, text)
        sha = self._mutator(identity).commit_files(self.repo, self.default_branch, {self.config_path: text}, message)
        self._texts_by_sha[sha] = text
        _logger.info("reset %s/%s:%s to %s (%s)", self.org, self.repo, self.default_branch, sha[:12], message)
        return sha

    # --- pull requests --------------------------------------------------------------------------------------------
    def open_pr(
        self,
        *,
        slug: str,
        config_texts: str | Sequence[str],
        title: str,
        identity: str = "admin",
        draft: bool = False,
        body: str = "",
    ) -> ConfigPr:
        """Branch ``run_ctx.branch(slug)`` with one commit per text (each guarded against main) and a PR to main."""
        texts = [config_texts] if isinstance(config_texts, str) else list(config_texts)
        if not texts:
            raise ValueError("open_pr needs at least one config text")
        base_text = self.main_config() or ""
        for text in texts:
            self.guard_config(base_text, text)
        mutator = self._mutator(identity)
        branch = self.run_ctx.branch(slug)
        mutator.create_branch(self.repo, branch, self.main_sha())
        head_sha = ""
        for index, text in enumerate(texts, start=1):
            message = f"e2e {self.run_ctx.run_id} {slug}: config {index}/{len(texts)}"
            head_sha = mutator.commit_files(self.repo, branch, {self.config_path: text}, message)
            self._texts_by_sha[head_sha] = text
        return self._create_pull(
            mutator,
            branch=branch,
            head_sha=head_sha,
            title=title,
            body=body,
            draft=draft,
            identity=identity,
            base_text=base_text,
        )

    def open_pr_files(
        self,
        *,
        slug: str,
        files: Mapping[str, str | None],
        title: str,
        identity: str = "admin",
        draft: bool = False,
        body: str = "",
        message: str | None = None,
    ) -> ConfigPr:
        """Branch ``run_ctx.branch(slug)`` with ONE commit writing (text) or deleting (None) ``files`` and a PR to main:
        multi-file PRs (the org config besides other files) and PRs touching only other files (README.md, blueprint
        or policy definitions, ...). The org config text, when included, is guarded against main; deleting it is
        refused."""
        changes = self._checked_changes(files)
        base_text = self.main_config() or ""
        config_text = changes.get(self.config_path)
        if config_text is not None:
            self.guard_config(base_text, config_text)
        mutator = self._mutator(identity)
        branch = self.run_ctx.branch(slug)
        mutator.create_branch(self.repo, branch, self.main_sha())
        commit = message or f"e2e {self.run_ctx.run_id} {slug}: {len(changes)} file(s)"
        head_sha = mutator.commit_files(self.repo, branch, changes, commit)
        self._texts_by_sha[head_sha] = config_text if config_text is not None else base_text
        return self._create_pull(
            mutator,
            branch=branch,
            head_sha=head_sha,
            title=title,
            body=body,
            draft=draft,
            identity=identity,
            base_text=base_text,
        )

    def _checked_changes(self, files: Mapping[str, str | None]) -> dict[str, str | None]:
        """checked_paths of ``files``; ConfigRepoError when the org config would be deleted."""
        changes = checked_paths(files)
        if self.config_path in changes and changes[self.config_path] is None:
            raise ConfigRepoError(f"deleting {self.config_path} is refused (the webapp would apply an empty org)")
        return changes

    def _create_pull(
        self,
        mutator: Mutator,
        *,
        branch: str,
        head_sha: str,
        title: str,
        body: str,
        draft: bool,
        identity: str,
        base_text: str,
    ) -> ConfigPr:
        """Open the PR of ``branch`` to main, register it and its pull_request/opened trigger."""
        after = self.now()
        pull = mutator.create_pull(
            self.repo, head=branch, base=self.default_branch, title=title, body=body, draft=draft
        )
        pr = ConfigPr(
            number=int(pull["number"]),
            branch=branch,
            head_sha=head_sha,
            url=str(pull.get("html_url") or ""),
            author=str((pull.get("user") or {}).get("login") or identity),
            comment_ids_before=frozenset(),
        )
        self._register(pr, identity, base_text)
        self._triggers[pr.number] = _Trigger("pull_request", "opened", after, head_sha=head_sha)
        _logger.info("opened config PR #%d %s (%s)%s", pr.number, pr.url, branch, " as draft" if draft else "")
        return pr

    def _register(self, pr: ConfigPr, identity: str, base_text: str) -> None:
        """Remember a PR for cleanup and guards."""
        self._prs[pr.number] = pr
        self._identities[pr.number] = identity
        self._base_texts[pr.number] = base_text

    def push_commit(self, pr: ConfigPr, text: str, *, message: str, identity: str | None = None) -> ConfigPr:
        """Push one more (guarded) commit to the PR branch; returns the PR with its new head sha."""
        self.guard_config(self.main_config() or "", text)
        before = self.comment_ids(pr)
        identity = identity or self._identities.get(pr.number, "admin")
        sha = self._mutator(identity).commit_files(self.repo, pr.branch, {self.config_path: text}, message)
        self._texts_by_sha[sha] = text
        self._triggers[pr.number] = _Trigger("pull_request", "synchronize", self.now(), head_sha=sha)
        updated = dataclasses.replace(pr, head_sha=sha, comment_ids_before=before)
        self._prs[pr.number] = updated
        return updated

    def push_files(
        self, pr: ConfigPr, files: Mapping[str, str | None], *, message: str, identity: str | None = None
    ) -> ConfigPr:
        """Push one commit writing or deleting ``files`` to the PR branch (the org config among them guarded against
        main, never deleted); returns the PR with its new head sha."""
        changes = self._checked_changes(files)
        config_text = changes.get(self.config_path)
        if config_text is not None:
            self.guard_config(self.main_config() or "", config_text)
        before = self.comment_ids(pr)
        identity = identity or self._identities.get(pr.number, "admin")
        sha = self._mutator(identity).commit_files(self.repo, pr.branch, changes, message)
        previous = self._texts_by_sha.get(pr.head_sha)
        text = config_text if config_text is not None else previous
        if text is not None:
            self._texts_by_sha[sha] = text
        self._triggers[pr.number] = _Trigger("pull_request", "synchronize", self.now(), head_sha=sha)
        updated = dataclasses.replace(pr, head_sha=sha, comment_ids_before=before)
        self._prs[pr.number] = updated
        return updated

    def comment(self, pr: ConfigPr, body: str, *, identity: str = "admin") -> dict[str, Any]:
        """Comment on the PR (guard re-run first when the body starts with a GUARDED_COMMANDS entry)."""
        if _GUARDED_RE.match(body.lstrip()):
            self.guard_pr(pr)
        after = self.now()
        result = self._mutator(identity).comment(self.repo, pr.number, body)
        comment_id = result.get("id") if isinstance(result.get("id"), int) else None
        if comment_id is not None:
            self._comments[comment_id] = (pr.number, identity)
        self._triggers[pr.number] = _Trigger("issue_comment", "created", after, comment_id=comment_id)
        return result

    def edit_comment(
        self, pr: ConfigPr, comment: Mapping[str, Any] | int, body: str, *, identity: str | None = None
    ) -> dict[str, Any]:
        """Edit a comment this flow posted on the PR (by its author unless ``identity``); the webapp runs the first
        /otterdog command of an edited comment like a new one, so /otterdog merge|apply bodies are guarded first."""
        comment_id, owner = self._own_comment(pr, comment)
        if _GUARDED_RE.match(body.lstrip()):
            self.guard_pr(pr)
        after = self.now()
        result = dict(_call(self._mutator(identity or owner), "edit_comment", self.repo, comment_id, body) or {})
        self._triggers[pr.number] = _Trigger("issue_comment", "edited", after, comment_id=comment_id)
        return result

    def delete_comment(self, pr: ConfigPr, comment: Mapping[str, Any] | int, *, identity: str | None = None) -> None:
        """Delete a comment this flow posted on the PR (issue_comment ``deleted``: otterdog ignores it)."""
        comment_id, owner = self._own_comment(pr, comment)
        after = self.now()
        _call(self._mutator(identity or owner), "delete_comment", self.repo, comment_id)
        self._comments.pop(comment_id, None)
        self._triggers[pr.number] = _Trigger("issue_comment", "deleted", after, comment_id=comment_id)

    def _own_comment(self, pr: ConfigPr, comment: Mapping[str, Any] | int) -> tuple[int, str]:
        """(comment id, identity that posted it) of a comment of this flow on ``pr`` (ConfigRepoError otherwise)."""
        raw = comment.get("id") if isinstance(comment, Mapping) else comment
        comment_id = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        owner = self._comments.get(comment_id) if comment_id is not None else None
        if comment_id is None or owner is None or owner[0] != pr.number:
            raise ConfigRepoError(
                f"comment {raw!r} was not posted on PR #{pr.number} by this flow: refusing to change it"
            )
        return comment_id, owner[1]

    def approve(self, pr: ConfigPr, *, identity: str = "approver") -> dict[str, Any]:
        """Approving review (guarded)."""
        self.guard_pr(pr)
        after = self.now()
        review = self._mutator(identity).review(self.repo, pr.number, event="APPROVE", body="e2e approval")
        self._remember_review(pr, review, identity)
        self._triggers[pr.number] = _Trigger("pull_request_review", "submitted", after, head_sha=pr.head_sha)
        return review

    def request_changes(
        self, pr: ConfigPr, *, identity: str = "approver", body: str = "e2e: changes requested"
    ) -> dict[str, Any]:
        """A REQUEST_CHANGES review (a body is required by GitHub); never makes a PR mergeable, so not guarded."""
        if not body.strip():
            raise ValueError("a REQUEST_CHANGES review needs a body")
        after = self.now()
        review = self._mutator(identity).review(self.repo, pr.number, event="REQUEST_CHANGES", body=body)
        self._remember_review(pr, review, identity)
        self._triggers[pr.number] = _Trigger("pull_request_review", "submitted", after, head_sha=pr.head_sha)
        return review

    def dismiss_review(
        self,
        pr: ConfigPr,
        review: Mapping[str, Any] | int,
        *,
        message: str = "e2e: review dismissed",
        identity: str = "admin",
    ) -> dict[str, Any]:
        """Dismiss a review this flow submitted (PUT .../reviews/{id}/dismissals; admin by default: dismissing needs
        write access); pull_request_review ``dismissed`` makes the webapp recompute the approvals."""
        raw = review.get("id") if isinstance(review, Mapping) else review
        review_id = raw if isinstance(raw, int) and not isinstance(raw, bool) else None
        known = self._reviews.get(review_id) if review_id is not None else None
        if review_id is None or known is None or known[0] != pr.number:
            raise ConfigRepoError(
                f"review {raw!r} was not submitted on PR #{pr.number} by this flow: refusing to dismiss"
            )
        if not message.strip():
            raise ValueError("a review dismissal needs a message")
        after = self.now()
        result = dict(
            _call(self._mutator(identity), "dismiss_review", self.repo, pr.number, review_id, message=message) or {}
        )
        self._triggers[pr.number] = _Trigger("pull_request_review", "dismissed", after, head_sha=pr.head_sha)
        return result

    def _remember_review(self, pr: ConfigPr, review: Mapping[str, Any], identity: str) -> None:
        """Record the id of a review submitted by this flow (dismiss_review only dismisses those)."""
        review_id = review.get("id")
        if isinstance(review_id, int) and not isinstance(review_id, bool):
            self._reviews[review_id] = (pr.number, identity)

    def mark_ready(self, pr: ConfigPr, *, identity: str | None = None) -> dict[str, Any]:
        """Mark a draft PR of this flow ready for review (GraphQL markPullRequestReadyForReview): the webapp then posts
        the help and team comments and validates (pull_request ``ready_for_review``)."""
        self._own_pr(pr)
        after = self.now()
        mutator = self._mutator(identity or self._identities.get(pr.number, "admin"))
        result = dict(_call(mutator, "mark_pull_ready", self.repo, pr.number) or {})
        self._triggers[pr.number] = _Trigger("pull_request", "ready_for_review", after, head_sha=pr.head_sha)
        return result

    def convert_to_draft(self, pr: ConfigPr, *, identity: str | None = None) -> dict[str, Any]:
        """Convert a PR of this flow to a draft (GraphQL convertPullRequestToDraft; pull_request
        ``converted_to_draft``: the webapp only updates its record)."""
        self._own_pr(pr)
        after = self.now()
        mutator = self._mutator(identity or self._identities.get(pr.number, "admin"))
        result = dict(_call(mutator, "convert_pull_to_draft", self.repo, pr.number) or {})
        self._triggers[pr.number] = _Trigger("pull_request", "converted_to_draft", after, head_sha=pr.head_sha)
        return result

    def reopen(self, pr: ConfigPr, *, identity: str | None = None) -> None:
        """Reopen a closed (not merged) PR of this flow (pull_request ``reopened``: validation and sync check again;
        the webapp also refreshes the blueprint status of ``otterdog/*`` branches)."""
        self._own_pr(pr)
        after = self.now()
        _call(self._mutator(identity or self._identities.get(pr.number, "admin")), "reopen_pull", self.repo, pr.number)
        self._triggers[pr.number] = _Trigger("pull_request", "reopened", after, head_sha=pr.head_sha)

    def adopt_pr(self, number: int, *, identity: str = "admin") -> ConfigPr:
        """Register an open PR of the config repo that this run produced without the flow (otterdog open-pr, a
        blueprint remediation PR): its head branch must carry this run's id (run_branch) and target main; the flow
        then guards, merges, comments and cleans it up like its own PRs."""
        pull = self.oracle.pull(self.repo, int(number))
        if not pull:
            raise ConfigRepoError(f"{self.org}/{self.repo} has no pull request #{number}")
        head = pull.get("head") or {}
        branch = str(head.get("ref") or "")
        if not run_branch(branch, self.run_ctx.run_id):
            raise SafetyError(f"PR #{number} comes from {branch!r}, not a branch of run {self.run_ctx.run_id}")
        base = str((pull.get("base") or {}).get("ref") or "")
        if base != self.default_branch:
            raise ConfigRepoError(f"PR #{number} targets {base!r}, not {self.default_branch!r}")
        pr = ConfigPr(
            number=int(number),
            branch=branch,
            head_sha=str(head.get("sha") or ""),
            url=str(pull.get("html_url") or ""),
            author=str((pull.get("user") or {}).get("login") or ""),
            comment_ids_before=self.comment_ids(ConfigPr(int(number), branch, "", "", "", frozenset())),
        )
        self._register(pr, identity, self.main_config() or "")
        self._adopted.add(pr.number)
        _logger.info("adopted config PR #%d %s (%s)", pr.number, pr.url, branch)
        return pr

    def _own_pr(self, pr: ConfigPr) -> None:
        """ConfigRepoError unless the flow opened or adopted ``pr``."""
        if pr.number not in self._prs:
            raise ConfigRepoError(f"PR #{pr.number} was not opened or adopted by this flow: refusing to change it")

    def merge(self, pr: ConfigPr, *, method: str = "squash", identity: str = "admin") -> dict[str, Any]:
        """Merge the PR at its head sha (guarded) with ``method`` merge|squash|rebase."""
        if method not in MERGE_METHODS:
            raise ValueError(f"unknown merge method {method!r}, expected one of {MERGE_METHODS}")
        self.guard_pr(pr)
        self._base_texts[pr.number] = self.main_config() or self._base_texts.get(pr.number, "")
        after = self.now()
        result = self._mutator(identity).merge_pull(self.repo, pr.number, method=method, sha=pr.head_sha)
        self._triggers[pr.number] = _Trigger("pull_request", "closed", after, head_sha=pr.head_sha)
        return result

    def close(self, pr: ConfigPr, *, identity: str = "admin") -> None:
        """Close the PR."""
        after = self.now()
        self._mutator(identity).close_pull(self.repo, pr.number)
        self._triggers[pr.number] = _Trigger("pull_request", "closed", after, head_sha=pr.head_sha)

    # --- guards ---------------------------------------------------------------------------------------------------
    def guard_config(self, base_text: str, head_text: str) -> None:
        """Run the injected guard (SafetyError when merging head over base could delete protected objects)."""
        self.guard(base_text, head_text)

    def guard_pr(self, pr: ConfigPr) -> None:
        """Re-run the guard for the PR's current head text against main (and against its pre-merge base) before an
        approval, a merge or ``/otterdog merge|apply`` (the webapp then applies with delete_resources).

        The SUT decides whether the PR is valid, not the trusted reset CLI: a head the guard's CLI cannot load or
        validate is accepted only when the SUT itself reports the PR invalid (a ``failure``/``error`` validation status
        on that head sha); otherwise the removal check must pass (DESTR-04: a head valid for a newer SUT, invalid for
        release:latest, would otherwise be merged and applied unchecked)."""
        sha, head_text = self._head(pr)
        invalid_for_sut = self._sut_reports_invalid(sha)
        bases = [self.main_config() or ""]
        recorded = self._base_texts.get(pr.number)
        if recorded is not None and recorded not in bases:
            bases.append(recorded)
        for base_text in bases:
            self._guard_merge(base_text, head_text, allow_invalid_head=invalid_for_sut)

    def _guard_merge(self, base_text: str, head_text: str, *, allow_invalid_head: bool) -> None:
        """The injected guard with ``allow_invalid_head`` (stand-ins taking two texts get them only)."""
        try:
            parameters = list(inspect.signature(self.guard).parameters.values())
        except (TypeError, ValueError):
            parameters = []
        takes_flag = any(
            parameter.name == "allow_invalid_head" or parameter.kind is inspect.Parameter.VAR_KEYWORD
            for parameter in parameters
        )
        if takes_flag:
            self.guard(base_text, head_text, allow_invalid_head=allow_invalid_head)
        else:
            self.guard(base_text, head_text)

    def _sut_reports_invalid(self, sha: str) -> bool:
        """True when the SUT's validation status on ``sha`` is failure or error (it will never apply that head)."""
        status = self.oracle.latest_status(self.repo, sha, self.validation_context) or {}
        return status.get("state") in INVALID_STATES

    def _head(self, pr: ConfigPr) -> tuple[str, str]:
        """(sha, config text) of the PR's current head on GitHub (SafetyError when the text cannot be read)."""
        pull = self.oracle.pull(self.repo, pr.number) or {}
        sha = (pull.get("head") or {}).get("sha") or pr.head_sha
        text = self._texts_by_sha.get(sha)
        if text is None:
            text = self.oracle.file_content(self.repo, self.config_path, ref=sha)
        if text is None:
            raise SafetyError(f"cannot read {self.config_path} at {sha} of PR #{pr.number}: refusing to proceed")
        return sha, text

    def _head_text(self, pr: ConfigPr) -> str:
        """Config text at the PR's current head on GitHub (SafetyError when it cannot be read)."""
        return self._head(pr)[1]

    def _mutator(self, identity: str) -> Mutator:
        """Mutator of an identity (ConfigRepoError when the identity is not configured)."""
        try:
            return self.mutators[identity]
        except KeyError:
            raise ConfigRepoError(f"no mutator for identity {identity!r} (have {sorted(self.mutators)})") from None

    # --- deliveries -----------------------------------------------------------------------------------------------
    def wait_delivery(
        self, pr: ConfigPr, *, event: str, action: str | None = None, after: datetime
    ) -> RelayedDelivery | None:
        """Wait for the relayed delivery triggered by a harness action (None for the external transport)."""
        if self.relay is None:
            return None
        trigger = self._triggers.get(pr.number)
        keys = trigger if trigger and trigger.event == event and action in (None, trigger.action) else None
        predicate = self._delivery_predicate(pr, event, action, after, keys)
        try:
            delivery = self.relay.wait_for(predicate, timeout=self.delivery_timeout)
        except waiting.WaitTimeoutError:
            raise DeliveryTimeoutError(
                f"{event}/{action or '*'} delivery for PR #{pr.number} not observed within "
                f"{self.delivery_timeout:g} s (infra): check the App webhook/sink and the relay (deliveries.jsonl)"
            ) from None
        self._consumed.add(delivery.id)
        if keys is not None:
            keys.delivery = delivery
        self._check_forwarded(pr, delivery)
        return delivery

    def _delivery_predicate(
        self, pr: ConfigPr, event: str, action: str | None, after: datetime, keys: _Trigger | None
    ) -> Callable[[RelayedDelivery], bool]:
        """Predicate selecting the delivery of a harness action on ``pr``."""
        floor = after - DELIVERY_CLOCK_SKEW

        def matches(delivery: RelayedDelivery) -> bool:
            """True for an unconsumed delivery of this event/action and PR (exact head sha / comment id if known)."""
            if delivery.id in self._consumed or delivery.event != event:
                return False
            if action is not None and delivery.action != action:
                return False
            if delivery.delivered_at < floor:
                return False
            if event != "push" and delivery.pull_number != pr.number:
                return False
            if keys is not None and keys.head_sha and delivery.head_sha not in (None, keys.head_sha):
                return False
            return keys is None or not keys.comment_id or delivery.comment_id in (None, keys.comment_id)

        return matches

    @staticmethod
    def _check_forwarded(pr: ConfigPr, delivery: RelayedDelivery) -> None:
        """FlowError when the observed delivery was not handed to the webapp or the webapp failed on it."""
        check_forwarded(delivery, f"PR #{pr.number}")

    def _remaining(self, pr: ConfigPr, timeout: float) -> float:
        """Seconds left for a reaction: waits for the PR's trigger delivery, counts ``timeout`` from its forward."""
        trigger = self._triggers.get(pr.number)
        if self.relay is None or trigger is None:
            return timeout
        if trigger.delivery is None:
            self.wait_delivery(pr, event=trigger.event, action=trigger.action, after=trigger.after)
        delivery = trigger.delivery
        if delivery is None:
            return timeout
        started = delivery.forwarded_at or delivery.seen_at
        return max(0.0, timeout - (self.now() - started).total_seconds())

    def _poll(self, fn: Callable[[], Any], until: Callable[[Any], bool], timeout: float, what: str) -> Any:
        """waiting.poll with the flow's interval, sleep and clock."""
        return waiting.poll(
            fn, until=until, timeout=timeout, interval=self.poll_interval, what=what, sleep=self.sleep, clock=self.clock
        )

    def _transport(self) -> str:
        """Suffix of reaction failures: whether delivery tracking was available."""
        return "SUT" if self.relay is not None else "SUT; no delivery tracking with the external transport"

    # --- reactions ------------------------------------------------------------------------------------------------
    def _context(self, context: str) -> str:
        """Commit status context, accepting the aliases 'validation'/'validate' and 'sync'."""
        if context in _CONTEXT_ALIASES:
            return self.sync_context if context == "sync" else self.validation_context
        return context

    def wait_status(self, pr: ConfigPr, context: str, *, final: bool = True, timeout: float = 300) -> dict[str, Any]:
        """Latest commit status of ``context`` on the PR head (final: not pending)."""
        context = self._context(context)
        remaining = self._remaining(pr, timeout)

        def done(status: dict[str, Any] | None) -> bool:
            """Status present (and not pending when final)."""
            return status is not None and (not final or status.get("state") != "pending")

        try:
            return self._poll(
                lambda: self.oracle.latest_status(self.repo, pr.head_sha, context),
                done,
                remaining,
                f"status {context} on {pr.head_sha[:12]}",
            )
        except waiting.WaitTimeoutError as exc:
            state = (exc.last or {}).get("state") if isinstance(exc.last, dict) else None
            raise ReactionTimeoutError(
                f"webapp did not react within {timeout:g} s ({self._transport()}): status {context!r} of PR "
                f"#{pr.number} at {pr.head_sha[:12]} is {state or 'absent'}"
            ) from None

    def comment_ids(self, pr: ConfigPr) -> frozenset[str]:
        """Ids (GraphQL node ids) of every comment currently on the PR."""
        return frozenset(str(comment.get("id")) for comment in self.oracle.pr_comments(self.repo, pr.number))

    def bot_comments(self, pr: ConfigPr, *, marker: str | None = None) -> list[dict[str, Any]]:
        """Comments of the App bot (author == slug or slug[bot]), optionally with a MARKERS marker."""
        if not self.bot_login:
            raise ConfigRepoError("bot_login (the App slug) is required to read bot comments")
        slug = self.bot_login.removesuffix(BOT_SUFFIX)
        authors = {slug, f"{slug}{BOT_SUFFIX}"}
        name = _marker_name(marker) if marker is not None else None
        return [
            comment
            for comment in self.oracle.pr_comments(self.repo, pr.number)
            if comment.get("author") in authors and (name is None or comment_marker(comment.get("body") or "") == name)
        ]

    def wait_comment(
        self,
        pr: ConfigPr,
        *,
        marker: str | None = None,
        contains: str | None = None,
        exclude_ids: Collection[str] = (),
        timeout: float = 240,
    ) -> dict[str, Any]:
        """First bot comment matching marker/contains whose id is not excluded."""
        excluded = {str(value) for value in exclude_ids} | set(pr.comment_ids_before)
        remaining = self._remaining(pr, timeout)

        def find() -> dict[str, Any] | None:
            """First new matching bot comment, or None."""
            for comment in self.bot_comments(pr, marker=marker):
                ids = {str(comment.get("id")), str(comment.get("database_id"))}
                if ids & excluded:
                    continue
                if contains is None or comment_contains(comment.get("body") or "", contains):
                    return comment
            return None

        try:
            return self._poll(find, lambda comment: comment is not None, remaining, f"bot comment on #{pr.number}")
        except waiting.WaitTimeoutError:
            seen = [
                f"{comment_marker(c.get('body') or '') or '-'}: {(c.get('body') or '').strip()[:80]!r}"
                for c in self.bot_comments(pr)
            ]
            raise ReactionTimeoutError(
                f"webapp did not react within {timeout:g} s ({self._transport()}): no new bot comment on PR "
                f"#{pr.number} with marker={marker!r} contains={contains!r}; bot comments: {REDACTOR(str(seen))}"
            ) from None

    def wait_merged(self, pr: ConfigPr, *, timeout: float = 120) -> dict[str, Any]:
        """The PR once GitHub reports it merged."""
        remaining = self._remaining(pr, timeout)

        def merged_or_closed(pull: dict[str, Any] | None) -> bool:
            """Merged, or closed without merge (which never becomes merged)."""
            return pull is not None and (bool(pull.get("merged")) or pull.get("state") == "closed")

        try:
            pull = self._poll(
                lambda: self.oracle.pull(self.repo, pr.number), merged_or_closed, remaining, f"PR #{pr.number} merged"
            )
        except waiting.WaitTimeoutError:
            raise ReactionTimeoutError(
                f"webapp did not react within {timeout:g} s ({self._transport()}): PR #{pr.number} is not merged"
            ) from None
        if not pull.get("merged"):
            raise ReactionTimeoutError(f"PR #{pr.number} was closed without being merged (SUT)")
        return pull

    # --- teardown -------------------------------------------------------------------------------------------------
    def cleanup(self) -> None:
        """Close the PRs and delete the branches opened by this flow."""
        failures: list[str] = []
        for number, pr in list(self._prs.items()):
            mutator = self.mutators.get("admin") or self.mutators.get(self._identities.get(number, ""))
            if mutator is None:
                failures.append(f"#{number}: no mutator")
                continue
            try:
                pull = self.oracle.pull(self.repo, number) or {}
                if pull.get("state") == "open":
                    mutator.close_pull(self.repo, number)
                if naming.is_deletable_ref(f"heads/{pr.branch}"):  # otterdog/* branches: the webapp deletes them
                    mutator.delete_ref(self.repo, f"heads/{pr.branch}")
            except (RuntimeError, OSError) as exc:  # best effort: the janitor sweeps leftovers by run id
                failures.append(f"#{number}: {REDACTOR(str(exc))}")
                continue
            self._prs.pop(number, None)
        if failures:
            _logger.warning("config flow cleanup incomplete for %s/%s: %s", self.org, self.repo, failures)


def _call(mutator: Mutator, name: str, *args: Any, **kwargs: Any) -> Any:
    """``mutator.<name>(*args, **kwargs)``; ConfigRepoError when a Mutator stand-in lacks the mutation (the real
    Mutator and testing.fakes.RecordingMutator offer every one the flow uses)."""
    method = getattr(mutator, name, None)
    if method is None:
        raise ConfigRepoError(f"the Mutator has no {name}(): otterdog_e2e.github.mutate must provide it for this flow")
    return method(*args, **kwargs)


def _marker_name(marker: str) -> str:
    """Marker name of ``marker``: a MARKERS key, another name (PR-specific markers) or a full marker comment."""
    if marker in MARKERS:
        return marker
    return comment_marker(marker) or marker


def comment_marker(body: str) -> str | None:
    """Name of the ``<!-- Otterdog Comment: <name> -->`` marker in a comment body, or None."""
    match = _MARKER_RE.search(body)
    return match.group(1) if match else None


def comment_contains(body: str, text: str) -> bool:
    """True when ``text`` occurs in ``body`` verbatim or after normalize_comment of both."""
    if text in body:
        return True
    needle = normalize_comment(text)
    return bool(needle) and needle in normalize_comment(body)


def normalize_comment(body: str) -> str:
    """Comparable comment text: strips '-', '!', '+', '~' diff columns and box borders, unwraps ~110-column lines,
    collapses whitespace (the result is a single line; apply it to both sides of a comparison)."""
    text = _BOX_CHARS_RE.sub(" ", _ANSI_RE.sub("", body))
    text = _DIFF_MARK_RE.sub(" ", text)
    return _WS_RE.sub(" ", text).strip()
