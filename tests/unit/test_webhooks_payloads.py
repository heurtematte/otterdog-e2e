"""Synthetic webhook payloads (SPEC 13.3) carry every field otterdog's pydantic models require.

REQUIRED mirrors otterdog/webapp/webhook/github_models.py (otterdog main @9bdeb75): pydantic is not installed in the
harness venv, so the builders were validated against the real models offline during development (every builder
output: model_validate OK; PullRequest.get_pr_status OPEN / MERGED); this test keeps that contract from regressing.
The review, installation, workflow_job and workflow_run builders were validated the same way inside the webapp image
of otterdog main 9bdeb75 (``docker run --network none ... model_validate``).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import pytest

from otterdog_e2e.webhooks import payloads as p
from otterdog_e2e.webhooks.relay import payload_head_sha, payload_pull_number
from otterdog_e2e.webhooks.signing import serialize_payload

ORG = "e2e-test-org"
REPO = "e2e-t3c7z8a5-config"
DATETIME = "datetime"  # pydantic datetime: ISO string
NULLABLE = "nullable"  # required key, None allowed

# model -> {field: type or nested model name}; only REQUIRED fields (no default in github_models.py)
REQUIRED: dict[str, dict[str, Any]] = {
    "Installation": {"id": int},
    "Organization": {"login": str, "id": int, "node_id": str},
    "Actor": {"login": str, "id": int, "node_id": str, "type": str},
    "Repository": {
        "id": int,
        "node_id": str,
        "name": str,
        "full_name": str,
        "private": bool,
        "owner": "Actor",
        "default_branch": str,
    },
    "Ref": {"label": str, "ref": str, "sha": str, "user": "Actor", "repo": ("Repository", NULLABLE)},
    "PullRequest": {
        "id": int,
        "node_id": str,
        "number": int,
        "state": str,
        "locked": bool,
        "title": str,
        "draft": bool,
        "user": "Actor",
        "author_association": str,
        "created_at": DATETIME,
        "updated_at": DATETIME,
        "head": "Ref",
        "base": "Ref",
    },
    "Comment": {"id": int, "node_id": str, "user": "Actor", "body": str, "created_at": str, "updated_at": str},
    "Issue": {"number": int, "node_id": str, "title": str, "state": str, "author_association": str, "html_url": str},
    "AssociatedPullRequest": {"url": str, "html_url": str},
    "Commit": {"added": list, "modified": list, "removed": list},
    "PullRequestEvent": {
        "sender": "Actor",
        "action": str,
        "number": int,
        "pull_request": "PullRequest",
        "repository": "Repository",
    },
    "IssueCommentEvent": {
        "sender": "Actor",
        "action": str,
        "issue": "Issue",
        "comment": "Comment",
        "repository": "Repository",
    },
    "PushEvent": {
        "sender": "Actor",
        "ref": str,
        "before": str,
        "after": str,
        "repository": "Repository",
        "commits": ("Commit", list),
        "created": bool,
        "deleted": bool,
        "forced": bool,
    },
    "Review": {
        "author_association": str,
        "body": (str, NULLABLE),
        "commit_id": str,
        "id": int,
        "node_id": str,
        "state": str,
        "submitted_at": (DATETIME, NULLABLE),
        "user": ("Actor", NULLABLE),
    },
    "WorkflowJob": {
        "name": str,
        "id": int,
        "workflow_name": (str, NULLABLE),
        "run_id": int,
        "status": str,
        "head_sha": str,
        "created_at": str,
        "started_at": str,
        "labels": list,
    },
    "WorkflowRun": {
        "name": str,
        "id": int,
        "run_number": int,
        "run_attempt": int,
        "status": str,
        "head_sha": str,
        "created_at": str,
        "run_started_at": str,
        "referenced_workflows": (list, NULLABLE),
    },
    "PullRequestReviewEvent": {
        "sender": "Actor",
        "action": str,
        "pull_request": "PullRequest",
        "review": "Review",
        "repository": "Repository",
    },
    "InstallationEvent": {"sender": "Actor", "action": str},
    "WorkflowJobEvent": {"sender": "Actor", "action": str, "workflow_job": "WorkflowJob", "repository": "Repository"},
    "WorkflowRunEvent": {"sender": "Actor", "action": str, "workflow_run": "WorkflowRun", "repository": "Repository"},
}
EVENT_MODELS = (
    "PullRequestEvent",
    "IssueCommentEvent",
    "PushEvent",
    "Issue",
    "PullRequestReviewEvent",
    "InstallationEvent",
    "WorkflowJobEvent",
    "WorkflowRunEvent",
)
OPTIONAL_MODELS = {
    "installation": "Installation",
    "organization": "Organization",
    "pull_request": "AssociatedPullRequest",
}
ASSOCIATIONS = set(p.AUTHOR_ASSOCIATIONS)


def problems(data: Any, model: str, path: str = "$") -> list[str]:
    """Violations of REQUIRED for ``data`` as ``model`` (optional sub-models are checked when present)."""
    if not isinstance(data, dict):
        return [f"{path}: {model} must be an object"]
    found: list[str] = []
    for name, kind in REQUIRED[model].items():
        nullable = isinstance(kind, tuple) and NULLABLE in kind
        if name not in data:
            found.append(f"{path}.{name}: missing")
            continue
        value = data[name]
        if nullable and value is None:
            continue
        kind = kind[0] if isinstance(kind, tuple) and (nullable or kind[1] is not list) else kind
        found += _check(value, kind, f"{path}.{name}")
    for name, sub in OPTIONAL_MODELS.items():
        if name == "pull_request" and model in ("PullRequestEvent", "PullRequestReviewEvent"):
            continue  # the required PullRequest, already checked
        if model in EVENT_MODELS and data.get(name) is not None:
            found += problems(data[name], sub, f"{path}.{name}")
    if "author_association" in REQUIRED[model] and data.get("author_association") not in ASSOCIATIONS:
        found.append(f"{path}.author_association: {data.get('author_association')!r} not in otterdog's enum")
    return found


def _check(value: Any, kind: Any, path: str) -> list[str]:
    """Type check of one field."""
    if isinstance(kind, tuple):  # (model, list): list of sub-models
        if not isinstance(value, list):
            return [f"{path}: list expected"]
        return [issue for index, item in enumerate(value) for issue in problems(item, kind[0], f"{path}[{index}]")]
    if isinstance(kind, str) and kind in REQUIRED:
        return problems(value, kind, path)
    if kind == DATETIME:
        try:
            datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return [f"{path}: not an ISO datetime: {value!r}"]
        return []
    if kind is int and isinstance(value, bool):
        return [f"{path}: bool is not an int"]
    return [] if isinstance(value, kind) else [f"{path}: {type(value).__name__} is not {kind.__name__}"]


def pull(**overrides: Any) -> dict[str, Any]:
    """A synthetic pull request of the config repo."""
    values: dict[str, Any] = {"head_ref": "e2e/t3c7z8a5/case", "head_sha": "a" * 40}
    values.update(overrides)
    return p.synthetic_pull_request(ORG, REPO, 7, **values)


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (
            "PullRequestEvent",
            lambda: p.pull_request_payload("opened", org=ORG, repo=REPO, pull_request=pull(), installation_id=42),
        ),
        (
            "PullRequestEvent",
            lambda: p.pull_request_payload("closed", org=ORG, repo=REPO, pull_request=pull(merged=True)),
        ),
        (
            "IssueCommentEvent",
            lambda: p.issue_comment_payload(org=ORG, repo=REPO, number=7, body="/otterdog help", installation_id=42),
        ),
        (
            "IssueCommentEvent",
            lambda: p.issue_comment_payload(org=ORG, repo=REPO, number=9, body="x", is_pull_request=False),
        ),
        (
            "PushEvent",
            lambda: p.push_payload(
                org=ORG, repo=REPO, ref="refs/heads/main", after="d" * 40, modified=["otterdog/x.jsonnet"]
            ),
        ),
        (
            "PushEvent",
            lambda: p.push_payload(org=ORG, repo=REPO, ref="refs/heads/gone", after=p.ZERO_SHA, before="e" * 40),
        ),
        (
            "PullRequestReviewEvent",
            lambda: p.pull_request_review_payload(
                "submitted", org=ORG, repo=REPO, pull_request=pull(), installation_id=1
            ),
        ),
        (
            "PullRequestReviewEvent",
            lambda: p.pull_request_review_payload(
                "dismissed", org=ORG, repo=REPO, pull_request=pull(), state="dismissed"
            ),
        ),
        ("InstallationEvent", lambda: p.installation_payload("suspend", installation_id=42, org=ORG)),
        ("InstallationEvent", lambda: p.installation_payload("unsuspend", installation_id=42)),
        (
            "WorkflowJobEvent",
            lambda: p.workflow_job_payload(
                org=ORG, repo=REPO, run_id=5, labels=["macos-latest-large"], installation_id=1
            ),
        ),
        (
            "WorkflowJobEvent",
            lambda: p.workflow_job_payload("completed", org=ORG, repo=REPO, run_id=5, workflow_name=None),
        ),
        (
            "WorkflowRunEvent",
            lambda: p.workflow_run_payload(
                org=ORG,
                repo=REPO,
                run_id=6,
                referenced_workflows=[{"path": "o/r/.github/workflows/s.yml@main", "sha": "b" * 40}],
            ),
        ),
        ("WorkflowRunEvent", lambda: p.workflow_run_payload("requested", org=ORG, repo=REPO, run_id=7)),
        ("PullRequest", pull),
        ("Repository", lambda: p.synthetic_repository(ORG, REPO)),
        ("Organization", lambda: p.synthetic_organization(ORG)),
        ("Actor", lambda: p.synthetic_user("e2e-author")),
    ],
)
def test_builders_satisfy_otterdog_models(model: str, payload: Any) -> None:
    """Every required field of the pydantic model is present with the right type."""
    data = payload()
    assert problems(data, model) == []
    json.loads(serialize_payload(data))  # JSON-serializable as relayed/injected


def test_mirror_detects_missing_fields() -> None:
    """The mirror itself catches the classic mistakes (no Ref.repo key, FIRST_TIMER, missing sender)."""
    data = pull()
    del data["head"]["repo"]
    data["author_association"] = "FIRST_TIMER"  # what GitHub sends; otterdog's enum value is FIRST_TIME
    found = problems(data, "PullRequest")
    assert "$.head.repo: missing" in found and any("FIRST_TIMER" in issue for issue in found)
    event = p.pull_request_payload("opened", org=ORG, repo=REPO, pull_request=pull())
    del event["sender"]
    assert problems(event, "PullRequestEvent") == ["$.sender: missing"]


def test_pull_request_states() -> None:
    """merged=True closes the PR and sets merged_at; open PRs have no closed/merged timestamps."""
    opened = pull()
    assert opened["state"] == "open" and opened["closed_at"] is None and opened["merged_at"] is None
    assert opened["merged"] is False and opened["draft"] is False
    merged = pull(merged=True, merge_commit_sha="c" * 40, updated_at="2026-10-02T12:00:00Z")
    assert merged["state"] == "closed" and merged["merged_at"] == "2026-10-02T12:00:00Z" == merged["closed_at"]
    assert merged["merge_commit_sha"] == "c" * 40
    closed = pull(state="closed")
    assert closed["closed_at"] is not None and closed["merged_at"] is None
    assert pull(author_association="FIRST_TIMER")["author_association"] == "FIRST_TIMER"  # negative tests allowed


def test_pull_request_refs_and_ids() -> None:
    """Refs live in the config repo of the org; ids are stable per object."""
    data = pull(base_sha="b" * 40)
    assert data["head"]["ref"] == "e2e/t3c7z8a5/case" and data["head"]["label"] == f"{ORG}:e2e/t3c7z8a5/case"
    assert data["base"]["ref"] == "main" and data["base"]["sha"] == "b" * 40
    assert data["base"]["repo"]["full_name"] == f"{ORG}/{REPO}"
    assert data["base"]["user"]["type"] == "Organization"
    assert data["id"] == pull()["id"] and p.stable_id("a") != p.stable_id("b")
    assert data["html_url"] == f"https://github.com/{ORG}/{REPO}/pull/7"


def test_pull_request_payload_envelope() -> None:
    """number mirrors the PR, repository is the PR's base repo, installation/organization only when given."""
    data = p.pull_request_payload("synchronize", org=ORG, repo=REPO, pull_request=pull(), sender="e2e-author")
    assert data["number"] == 7 and data["repository"]["name"] == REPO and data["organization"]["login"] == ORG
    assert data["sender"]["login"] == "e2e-author" and "installation" not in data
    with_installation = p.pull_request_payload("opened", org=ORG, repo=REPO, pull_request=pull(), installation_id=99)
    assert with_installation["installation"]["id"] == 99
    assert payload_pull_number(data) == 7 and payload_head_sha(data) == "a" * 40


def test_issue_comment_payload() -> None:
    """Comments on PRs carry issue.pull_request; plain issues do not; comment timestamps are strings."""
    data = p.issue_comment_payload(
        org=ORG, repo=REPO, number=7, body="/otterdog merge", comment_id=55, installation_id=1
    )
    assert data["issue"]["pull_request"]["html_url"].endswith("/pull/7")
    assert data["comment"]["id"] == 55 and data["comment"]["body"] == "/otterdog merge"
    assert isinstance(data["comment"]["created_at"], str)
    assert payload_pull_number(data) == 7
    plain = p.issue_comment_payload(org=ORG, repo=REPO, number=3, body="x", is_pull_request=False)
    assert "pull_request" not in plain["issue"] and plain["issue"]["html_url"].endswith("/issues/3")


def test_push_payload() -> None:
    """created/deleted follow the zero sha; commits list the touched paths; deleting pushes have no commits."""
    data = p.push_payload(org=ORG, repo=REPO, ref="refs/heads/main", after="d" * 40, added=["a"], removed=["b"])
    assert data["created"] is True and data["deleted"] is False and data["forced"] is False
    (commit,) = data["commits"]
    assert commit["added"] == ["a"] and commit["removed"] == ["b"] and commit["modified"] == []
    assert data["pusher"]["name"] == "e2e-user" and payload_head_sha(data) == "d" * 40
    gone = p.push_payload(org=ORG, repo=REPO, ref="refs/heads/x", after=p.ZERO_SHA, before="e" * 40)
    assert (
        gone["deleted"] is True and gone["created"] is False and gone["commits"] == [] and gone["head_commit"] is None
    )


def test_ping_and_unknown_event() -> None:
    """ping has zen/hook_id/hook; the unknown event is an org event only when org is given."""
    ping = p.ping_payload(hook_id=12, installation_id=5)
    assert ping["hook_id"] == 12 == ping["hook"]["id"] and ping["zen"] and ping["installation"]["id"] == 5
    assert problems(ping["sender"], "Actor") == []
    star = p.unknown_event_payload()
    assert "organization" not in star and "repository" not in star
    star_org = p.unknown_event_payload("star", org=ORG, installation_id=5)
    assert star_org["organization"]["login"] == ORG and star_org["installation"]["id"] == 5


def test_timestamp_format() -> None:
    """GitHub-style UTC timestamps; strings pass through."""
    assert p.timestamp(datetime.fromisoformat("2026-10-02T14:00:00+02:00")) == "2026-10-02T12:00:00Z"
    assert p.timestamp("2026-01-01T00:00:00Z") == "2026-01-01T00:00:00Z"
    assert p.timestamp().endswith("Z")


def test_review_payload() -> None:
    """The review targets the PR head, belongs to the reviewer (also the sender) and carries the state."""
    data = p.pull_request_review_payload(
        "submitted",
        org=ORG,
        repo=REPO,
        pull_request=pull(),
        state="changes_requested",
        reviewer="e2e-approver",
        review_id=9,
    )
    review = data["review"]
    assert review["id"] == 9 and review["state"] == "changes_requested" and review["commit_id"] == "a" * 40
    assert review["user"]["login"] == data["sender"]["login"] == "e2e-approver"
    assert data["repository"]["name"] == REPO and payload_pull_number(data) == 7 and payload_head_sha(data) == "a" * 40
    assert set(p.REVIEW_STATES) >= {"approved", "changes_requested", "dismissed"}


def test_installation_payload() -> None:
    """installation.id is what otterdog reads; suspend marks suspended_at; no organization envelope."""
    suspended = p.installation_payload("suspend", installation_id=42, org=ORG)
    assert suspended["installation"]["id"] == 42 and suspended["installation"]["suspended_at"] is not None
    assert suspended["installation"]["account"]["login"] == ORG and "organization" not in suspended
    assert p.installation_payload("unsuspend", installation_id=42)["installation"]["suspended_at"] is None
    assert p.installation_payload("created", installation_id=1, suspended=True)["installation"]["suspended_at"]
    assert "suspend" in p.INSTALLATION_ACTIONS and "unsuspend" in p.INSTALLATION_ACTIONS


def test_workflow_payloads() -> None:
    """workflow_job: labels, run id, queued status; workflow_run: conclusion only when completed, referenced
    workflows copied (None stays None)."""
    job = p.workflow_job_payload(org=ORG, repo=REPO, run_id=11, labels=("macos-latest-large",), installation_id=1)
    assert job["workflow_job"]["labels"] == ["macos-latest-large"] and job["workflow_job"]["run_id"] == 11
    assert job["workflow_job"]["status"] == "queued" and job["workflow_job"]["completed_at"] is None
    assert job["organization"]["login"] == ORG and job["installation"]["id"] == 1
    assert job["workflow_job"]["id"] == p.workflow_job_payload(org=ORG, repo=REPO, run_id=11)["workflow_job"]["id"]
    done = p.workflow_job_payload("completed", org=ORG, repo=REPO, run_id=11, conclusion="cancelled")
    assert done["workflow_job"]["status"] == "completed" and done["workflow_job"]["conclusion"] == "cancelled"
    refs = [{"path": f"{ORG}/{REPO}/.github/workflows/store.yml@main", "sha": "c" * 40}]
    run = p.workflow_run_payload(org=ORG, repo=REPO, run_id=12, referenced_workflows=refs)
    assert run["workflow_run"]["conclusion"] == "success" and run["workflow_run"]["referenced_workflows"] == refs
    assert run["workflow_run"]["referenced_workflows"][0] is not refs[0]
    requested = p.workflow_run_payload("requested", org=ORG, repo=REPO, run_id=13)
    assert requested["workflow_run"]["conclusion"] is None and requested["workflow_run"]["referenced_workflows"] is None
    assert requested["workflow_run"]["status"] == "in_progress"
