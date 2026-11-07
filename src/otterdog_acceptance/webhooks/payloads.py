"""Minimal payloads accepted by otterdog's pydantic event models (SPEC 13.3).

Verified against otterdog/webapp/webhook/github_models.py: Event needs ``sender`` (Actor) and has optional
``installation`` {id[, node_id]} and ``organization`` {login, id, node_id}; Actor needs login, id, node_id, type;
Repository needs id, node_id, name, full_name, private, owner, default_branch; PullRequest needs id, node_id, number,
state, locked, title, draft, user, author_association (enum: FIRST_TIMER is spelled 'FIRST_TIME' there),
created_at/updated_at (datetimes) and head/base Refs {label, ref, sha, user, repo (required, nullable)}; Issue needs
number, node_id, title, state, author_association, html_url (pull_request {url, html_url} marks a PR); Comment needs id,
node_id, user, body, created_at/updated_at (strings); PushEvent needs ref, before, after, repository, commits
[{added, modified, removed}], created, deleted, forced; Review needs author_association, body, commit_id, id,
node_id, state, submitted_at, user (nullable); WorkflowJob needs name, id, workflow_name (nullable), run_id, status,
head_sha, created_at, started_at, labels; WorkflowRun needs name, id, run_number, run_attempt, status, head_sha,
created_at, run_started_at, referenced_workflows (nullable list of {path, sha[, ref]}); InstallationEvent only needs
action and sender (the handler reads installation.id). Real GitHub payloads carry many more fields: builders add the
few that make logs and EVENT_DESCRIPTIONS readable (urls, pusher, zen, ...).

Caution: a queued workflow_job of a restricted runner ('macos...large') makes the webapp CANCEL that run id in that
repository on GitHub when the org's macos_large_runners policy denies it, and a successful workflow_run matching the
dependency_track_upload policy makes it download the run's artifacts: inject them for run repositories (e2e names)
and run ids of this run only.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

ZERO_SHA = "0" * 40
DEFAULT_SENDER = "e2e-user"
AUTHOR_ASSOCIATIONS = (
    "COLLABORATOR",
    "CONTRIBUTOR",
    "FIRST_TIME",  # otterdog's AuthorAssociation.FIRST_TIMER value (GitHub sends FIRST_TIMER, which otterdog drops)
    "FIRST_TIME_CONTRIBUTOR",
    "MANNEQUIN",
    "MEMBER",
    "NONE",
    "OWNER",
)
DEFAULT_ORG_ID = 1000
PULL_REQUEST_STATES = ("open", "closed")
REVIEW_STATES = ("approved", "changes_requested", "commented", "dismissed")
INSTALLATION_ACTIONS = ("created", "deleted", "suspend", "unsuspend", "new_permissions_accepted")
WORKFLOW_JOB_ACTIONS = ("queued", "in_progress", "completed", "waiting")
WORKFLOW_RUN_ACTIONS = ("requested", "in_progress", "completed")
_API = "https://api.github.com"
_WEB = "https://github.com"


def stable_id(seed: str, *, base: int = 10_000) -> int:
    """Deterministic positive id derived from ``seed`` (synthetic objects get stable, distinct ids)."""
    return base + int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16) % 1_000_000_000


def timestamp(value: datetime | str | None = None) -> str:
    """GitHub timestamp ``YYYY-MM-DDTHH:MM:SSZ`` of ``value`` (default: now); strings are returned unchanged."""
    if isinstance(value, str):
        return value
    moment = (value or datetime.now(UTC)).astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def synthetic_user(login: str = DEFAULT_SENDER, *, user_id: int = 1, type_: str = "User") -> dict[str, Any]:
    """An Actor (login, id, node_id, type)."""
    return {
        "login": login,
        "id": user_id,
        "node_id": f"{'O' if type_ == 'Organization' else 'U'}_e2e{user_id}",
        "type": type_,
        "site_admin": False,
        "html_url": f"{_WEB}/{login}",
    }


def synthetic_organization(login: str, *, org_id: int = DEFAULT_ORG_ID) -> dict[str, Any]:
    """An Organization (login, id, node_id)."""
    return {"login": login, "id": org_id, "node_id": f"O_e2e{org_id}", "url": f"{_API}/orgs/{login}"}


def synthetic_installation(installation_id: int) -> dict[str, Any]:
    """The ``installation`` object of an App delivery."""
    return {"id": installation_id, "node_id": f"MDIzOkludGVncmF0aW9uSW5zdGFsbGF0aW9u{installation_id}"}


def synthetic_repository(
    owner: str, name: str, *, repo_id: int = 2000, private: bool = False, default_branch: str = "main"
) -> dict[str, Any]:
    """A Repository owned by ``owner``."""
    return {
        "id": repo_id,
        "node_id": f"R_e2e{repo_id}",
        "name": name,
        "full_name": f"{owner}/{name}",
        "private": private,
        "owner": synthetic_user(owner, user_id=DEFAULT_ORG_ID, type_="Organization"),
        "html_url": f"{_WEB}/{owner}/{name}",
        "url": f"{_API}/repos/{owner}/{name}",
        "default_branch": default_branch,
    }


def _ref(owner: str, repository: dict[str, Any], ref: str, sha: str) -> dict[str, Any]:
    """A head/base Ref of a pull request in ``repository``."""
    return {"label": f"{owner}:{ref}", "ref": ref, "sha": sha, "user": repository["owner"], "repo": repository}


def synthetic_pull_request(
    owner: str,
    repo: str,
    number: int,
    *,
    head_ref: str,
    head_sha: str,
    base_ref: str = "main",
    base_sha: str = ZERO_SHA,
    author: str = DEFAULT_SENDER,
    author_association: str = "MEMBER",
    state: str = "open",
    draft: bool = False,
    merged: bool | None = None,
    title: str = "e2e",
    body: str | None = None,
    merge_commit_sha: str | None = None,
    created_at: datetime | str | None = None,
    updated_at: datetime | str | None = None,
) -> dict[str, Any]:
    """A PullRequest with head/base refs in ``owner/repo`` (merged=True implies state closed; values outside
    AUTHOR_ASSOCIATIONS / PULL_REQUEST_STATES are kept, for negative tests)."""
    if merged:
        state = "closed"
    created = timestamp(created_at)
    updated = timestamp(updated_at) if updated_at is not None else created
    repository = synthetic_repository(owner, repo)
    return {
        "url": f"{_API}/repos/{owner}/{repo}/pulls/{number}",
        "html_url": f"{_WEB}/{owner}/{repo}/pull/{number}",
        "id": stable_id(f"{owner}/{repo}#{number}"),
        "node_id": f"PR_e2e{number}",
        "number": number,
        "state": state,
        "locked": False,
        "title": title,
        "body": body,
        "draft": draft,
        "merged": bool(merged),
        "merge_commit_sha": merge_commit_sha,
        "user": synthetic_user(author, user_id=stable_id(author)),
        "author_association": author_association,
        "created_at": created,
        "updated_at": updated,
        "closed_at": updated if state == "closed" else None,
        "merged_at": updated if merged else None,
        "head": _ref(owner, repository, head_ref, head_sha),
        "base": _ref(owner, repository, base_ref, base_sha),
    }


def _envelope(payload: dict[str, Any], *, org: str | None, installation_id: int | None, sender: str) -> dict[str, Any]:
    """Add the Event fields: sender, organization (when org) and installation (when installation_id)."""
    payload["sender"] = synthetic_user(sender, user_id=stable_id(sender))
    if org is not None:
        payload["organization"] = synthetic_organization(org)
    if installation_id is not None:
        payload["installation"] = synthetic_installation(installation_id)
    return payload


def ping_payload(
    *, hook_id: int = 1, installation_id: int | None = None, sender: str = DEFAULT_SENDER
) -> dict[str, Any]:
    """A ping event (zen, hook_id, hook, sender[, installation])."""
    hook = {
        "type": "App",
        "id": hook_id,
        "name": "web",
        "active": True,
        "events": ["issue_comment", "pull_request", "pull_request_review", "push"],
        "config": {"content_type": "json", "insecure_ssl": "0", "url": "https://otterdog-e2e.invalid/ping"},
    }
    payload = {"zen": "Keep it logically awesome.", "hook_id": hook_id, "hook": hook}
    return _envelope(payload, org=None, installation_id=installation_id, sender=sender)


def pull_request_payload(
    action: str,
    *,
    org: str,
    repo: str,
    pull_request: Mapping[str, Any],
    installation_id: int | None = None,
    sender: str = DEFAULT_SENDER,
) -> dict[str, Any]:
    """A pull_request event (action, number, pull_request, repository, organization, sender[, installation])."""
    pull = dict(pull_request)
    base_repo = (pull.get("base") or {}).get("repo")
    repository = dict(base_repo) if isinstance(base_repo, Mapping) else synthetic_repository(org, repo)
    payload = {"action": action, "number": pull["number"], "pull_request": pull, "repository": repository}
    return _envelope(payload, org=org, installation_id=installation_id, sender=sender)


def issue_comment_payload(
    *,
    org: str,
    repo: str,
    number: int,
    body: str,
    installation_id: int | None = None,
    action: str = "created",
    sender: str = DEFAULT_SENDER,
    author_association: str = "MEMBER",
    comment_id: int = 1,
    is_pull_request: bool = True,
) -> dict[str, Any]:
    """An issue_comment event on issue/PR ``number``."""
    now = timestamp()
    user = synthetic_user(sender, user_id=stable_id(sender))
    kind = "pull" if is_pull_request else "issues"
    issue: dict[str, Any] = {
        "url": f"{_API}/repos/{org}/{repo}/issues/{number}",
        "html_url": f"{_WEB}/{org}/{repo}/{kind}/{number}",
        "id": stable_id(f"{org}/{repo}#{number}"),
        "node_id": f"{'PR' if is_pull_request else 'I'}_e2e{number}",
        "number": number,
        "title": "e2e",
        "state": "open",
        "user": user,
        "author_association": author_association,
        "draft": False,
        "body": None,
    }
    if is_pull_request:
        issue["pull_request"] = {
            "url": f"{_API}/repos/{org}/{repo}/pulls/{number}",
            "html_url": f"{_WEB}/{org}/{repo}/pull/{number}",
            "merged_at": None,
        }
    comment = {
        "url": f"{_API}/repos/{org}/{repo}/issues/comments/{comment_id}",
        "html_url": f"{_WEB}/{org}/{repo}/{kind}/{number}#issuecomment-{comment_id}",
        "id": comment_id,
        "node_id": f"IC_e2e{comment_id}",
        "user": user,
        "body": body,
        "author_association": author_association,
        "created_at": now,
        "updated_at": now,
    }
    payload = {"action": action, "issue": issue, "comment": comment, "repository": synthetic_repository(org, repo)}
    return _envelope(payload, org=org, installation_id=installation_id, sender=sender)


def push_payload(
    *,
    org: str,
    repo: str,
    ref: str,
    after: str,
    before: str = ZERO_SHA,
    installation_id: int | None = None,
    added: Sequence[str] = (),
    modified: Sequence[str] = (),
    removed: Sequence[str] = (),
    sender: str = DEFAULT_SENDER,
) -> dict[str, Any]:
    """A push event with one commit listing the added/modified/removed paths."""
    deleted = after == ZERO_SHA
    commit = {
        "id": after,
        "tree_id": ZERO_SHA,
        "distinct": True,
        "message": "e2e",
        "timestamp": timestamp(),
        "url": f"{_WEB}/{org}/{repo}/commit/{after}",
        "author": {"name": sender, "email": f"{sender}@users.noreply.github.com", "username": sender},
        "committer": {"name": sender, "email": f"{sender}@users.noreply.github.com", "username": sender},
        "added": list(added),
        "removed": list(removed),
        "modified": list(modified),
    }
    payload = {
        "ref": ref,
        "before": before,
        "after": after,
        "repository": synthetic_repository(org, repo),
        "pusher": {"name": sender, "email": f"{sender}@users.noreply.github.com"},
        "created": before == ZERO_SHA,
        "deleted": deleted,
        "forced": False,
        "base_ref": None,
        "compare": f"{_WEB}/{org}/{repo}/compare/{before[:12]}...{after[:12]}",
        "commits": [] if deleted else [commit],
        "head_commit": None if deleted else commit,
    }
    return _envelope(payload, org=org, installation_id=installation_id, sender=sender)


def unknown_event_payload(
    event: str = "star", *, org: str | None = None, installation_id: int | None = None, sender: str = DEFAULT_SENDER
) -> dict[str, Any]:
    """A payload for an event otterdog does not handle (accepted with 204)."""
    payload: dict[str, Any] = {"action": "created", "e2e_event": event, "starred_at": timestamp()}
    if org is not None:
        payload["repository"] = synthetic_repository(org, "e2e-unknown-event")
    return _envelope(payload, org=org, installation_id=installation_id, sender=sender)


def pull_request_review_payload(
    action: str,
    *,
    org: str,
    repo: str,
    pull_request: Mapping[str, Any],
    state: str = "approved",
    reviewer: str = DEFAULT_SENDER,
    review_id: int = 1,
    body: str | None = None,
    author_association: str = "MEMBER",
    installation_id: int | None = None,
    submitted_at: datetime | str | None = None,
) -> dict[str, Any]:
    """A pull_request_review event (submitted / edited / dismissed) of ``reviewer`` on ``pull_request``."""
    pull = dict(pull_request)
    base_repo = (pull.get("base") or {}).get("repo")
    repository = dict(base_repo) if isinstance(base_repo, Mapping) else synthetic_repository(org, repo)
    review = {
        "id": review_id,
        "node_id": f"PRR_e2e{review_id}",
        "user": synthetic_user(reviewer, user_id=stable_id(reviewer)),
        "body": body,
        "commit_id": (pull.get("head") or {}).get("sha") or ZERO_SHA,
        "state": state,
        "author_association": author_association,
        "submitted_at": timestamp(submitted_at),
        "html_url": f"{_WEB}/{org}/{repo}/pull/{pull.get('number')}#pullrequestreview-{review_id}",
    }
    payload = {"action": action, "review": review, "pull_request": pull, "repository": repository}
    return _envelope(payload, org=org, installation_id=installation_id, sender=reviewer)


def installation_payload(
    action: str,
    *,
    installation_id: int,
    org: str | None = None,
    app_id: int = 1,
    app_slug: str = "otterdog-e2e-app",
    sender: str = DEFAULT_SENDER,
    suspended: bool | None = None,
) -> dict[str, Any]:
    """An installation event (created / deleted / suspend / unsuspend ...) of an App installation on ``org``."""
    is_suspended = action == "suspend" if suspended is None else suspended
    account = synthetic_user(org or "e2e-org", user_id=DEFAULT_ORG_ID, type_="Organization")
    installation = {
        **synthetic_installation(installation_id),
        "account": account,
        "app_id": app_id,
        "app_slug": app_slug,
        "repository_selection": "all",
        "target_type": "Organization",
        "suspended_at": timestamp() if is_suspended else None,
    }
    payload: dict[str, Any] = {"action": action, "installation": installation}
    payload["sender"] = synthetic_user(sender, user_id=stable_id(sender))
    return payload


def workflow_job_payload(
    action: str = "queued",
    *,
    org: str,
    repo: str,
    run_id: int,
    job_id: int | None = None,
    labels: Sequence[str] = ("ubuntu-latest",),
    name: str = "e2e",
    workflow_name: str | None = "e2e",
    head_sha: str = ZERO_SHA,
    head_branch: str | None = "main",
    conclusion: str | None = None,
    installation_id: int | None = None,
    sender: str = DEFAULT_SENDER,
) -> dict[str, Any]:
    """A workflow_job event of job ``job_id`` (default: derived from the run) of run ``run_id`` in ``org/repo``."""
    now = timestamp()
    job = {
        "id": job_id if job_id is not None else stable_id(f"{org}/{repo}/runs/{run_id}/job"),
        "run_id": run_id,
        "name": name,
        "workflow_name": workflow_name,
        "status": {"completed": "completed", "in_progress": "in_progress"}.get(action, "queued"),
        "conclusion": conclusion,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "labels": list(labels),
        "runner_id": None,
        "runner_name": None,
        "created_at": now,
        "started_at": now,
        "completed_at": now if action == "completed" else None,
        "html_url": f"{_WEB}/{org}/{repo}/actions/runs/{run_id}",
    }
    payload = {"action": action, "workflow_job": job, "repository": synthetic_repository(org, repo)}
    return _envelope(payload, org=org, installation_id=installation_id, sender=sender)


def workflow_run_payload(
    action: str = "completed",
    *,
    org: str,
    repo: str,
    run_id: int,
    name: str = "e2e",
    conclusion: str | None = "success",
    referenced_workflows: Sequence[Mapping[str, Any]] | None = None,
    head_sha: str = ZERO_SHA,
    head_branch: str | None = "main",
    run_number: int = 1,
    run_attempt: int = 1,
    installation_id: int | None = None,
    sender: str = DEFAULT_SENDER,
) -> dict[str, Any]:
    """A workflow_run event of run ``run_id`` in ``org/repo``; ``referenced_workflows`` items are {path, sha[, ref]}
    (the reusable workflows the run called, e.g. ``<org>/<repo>/.github/workflows/x.yml@<ref>``)."""
    now = timestamp()
    run = {
        "id": run_id,
        "name": name,
        "run_number": run_number,
        "run_attempt": run_attempt,
        "status": "completed" if action == "completed" else "in_progress",
        "conclusion": conclusion if action == "completed" else None,
        "head_sha": head_sha,
        "head_branch": head_branch,
        "event": "workflow_dispatch",
        "created_at": now,
        "run_started_at": now,
        "referenced_workflows": None if referenced_workflows is None else [dict(item) for item in referenced_workflows],
        "html_url": f"{_WEB}/{org}/{repo}/actions/runs/{run_id}",
    }
    payload = {"action": action, "workflow_run": run, "repository": synthetic_repository(org, repo)}
    return _envelope(payload, org=org, installation_id=installation_id, sender=sender)
