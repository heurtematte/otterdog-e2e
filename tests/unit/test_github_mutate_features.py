"""Mutator probe and drift calls of the battery: payloads, e2e-only guards (before any request), dry-run, retries,
pull request guards and GraphQL mutations (SPEC 5.2, 9.4)."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any

import pytest
import responses

from otterdog_e2e.github.http import GITHUB_API, GitHubError, GitHubHttp
from otterdog_e2e.github.mutate import (
    CONVERT_TO_DRAFT_MUTATION,
    DISPATCH_ATTEMPTS,
    DRY_RUN_GHSA,
    READY_FOR_REVIEW_MUTATION,
    Mutator,
)
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FAKE_ORG, FAKE_RUN_ID, make_verified_org

TOKEN = "ghp_" + "MutatorFeatureToken0123456789abcdefgh"
P = f"e2e-{FAKE_RUN_ID}"
RUN_REPO = f"{P}-r"
REPO = f"{GITHUB_API}/repos/{FAKE_ORG}/{RUN_REPO}"
CONFIG = f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog"
ORG = f"{GITHUB_API}/orgs/{FAKE_ORG}"
GRAPHQL = f"{GITHUB_API}/graphql"
GHSA = "GHSA-abcd-efgh-ijkl"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked api.github.com; unregistered requests fail."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def sleeps() -> list[float]:
    """Recorded sleeps."""
    return []


@pytest.fixture
def mutator(sleeps: list[float]) -> Mutator:
    """A Mutator over a client write-scoped to the fake verified org."""
    verified = make_verified_org()
    http = GitHubHttp(TOKEN, write_scope=verified, sleep=sleeps.append, min_write_interval=0.0)
    return Mutator(http, verified)


def body(call: Any) -> Any:
    """JSON body of a recorded request."""
    return json.loads(call.request.body or "{}")


def run_pull(number: int, *, ref: str = f"e2e/{FAKE_RUN_ID}/x", repo: str = ".otterdog") -> dict[str, Any]:
    """A pull request answer whose head is ``ref`` in ``repo`` of the test org."""
    return {
        "number": number,
        "node_id": f"PR_{number}",
        "head": {"ref": ref, "repo": {"full_name": f"{FAKE_ORG}/{repo}"}},
    }


# --- guards ---------------------------------------------------------------------------------------------------------
GUARDED: list[tuple[str, Callable[[Mutator], Any]]] = [
    ("set_repo_topics", lambda m: m.set_repo_topics(".otterdog", ["x"])),
    ("add_repo_collaborator", lambda m: m.add_repo_collaborator("otterdog-e2e-configs", "u")),
    ("remove_repo_collaborator", lambda m: m.remove_repo_collaborator(".otterdog", "u")),
    ("delete_repo_invitation", lambda m: m.delete_repo_invitation(".otterdog", 1)),
    ("create_team", lambda m: m.create_team("project-leads")),
    ("patch_team", lambda m: m.patch_team("otterdog-admins", privacy="secret")),
    ("patch_team rename", lambda m: m.patch_team(f"{P}-t", name="admins")),
    ("add_team_member", lambda m: m.add_team_member("project-leads", "u")),
    ("remove_team_member", lambda m: m.remove_team_member("project-leads", "u")),
    ("dispatch_workflow", lambda m: m.dispatch_workflow(".otterdog", "ci.yml", "main")),
    ("cancel_workflow_run", lambda m: m.cancel_workflow_run(".otterdog", 1)),
    ("rerun_workflow_run", lambda m: m.rerun_workflow_run(".otterdog", 1)),
    ("create_security_advisory repo", lambda m: m.create_security_advisory(".otterdog", summary=f"{P}-a")),
    ("create_security_advisory summary", lambda m: m.create_security_advisory(RUN_REPO, summary="real issue")),
    ("create_advisory_fork", lambda m: m.create_advisory_fork(".otterdog", GHSA)),
    ("close_security_advisory", lambda m: m.close_security_advisory(".otterdog", GHSA)),
    ("create_code_security_configuration", lambda m: m.create_code_security_configuration("GitHub recommended")),
    ("set_code_security_default", lambda m: m.set_code_security_default(1, name="prod", default_for_new_repos="all")),
    ("delete_code_security_configuration", lambda m: m.delete_code_security_configuration(1, name="prod")),
]


@pytest.mark.parametrize(("label", "call"), GUARDED, ids=[label for label, _ in GUARDED])
def test_probe_writes_refuse_non_e2e_objects(
    api: responses.RequestsMock, mutator: Mutator, label: str, call: Callable[[Mutator], Any]
) -> None:
    """Every probe/drift write on a non-e2e object raises SafetyError before any request."""
    with pytest.raises(SafetyError):
        call(mutator)
    assert len(api.calls) == 0, label


@pytest.mark.parametrize(("label", "call"), GUARDED, ids=[label for label, _ in GUARDED])
def test_guards_apply_in_dry_run(label: str, call: Callable[[Mutator], Any]) -> None:
    """dry_run keeps the guards."""
    dry = Mutator(GitHubHttp(TOKEN, read_only=True), make_verified_org(), dry_run=True)
    with pytest.raises(SafetyError):
        call(dry)


def test_value_checks(mutator: Mutator) -> None:
    """Team roles, default_for_new_repos values and advisory severities are checked locally."""
    with pytest.raises(ValueError, match="team role"):
        mutator.add_team_member(f"{P}-t", "u", role="owner")
    with pytest.raises(ValueError, match="default_for_new_repos"):
        mutator.set_code_security_default(1, name=f"{P}-c", default_for_new_repos="everything")
    with pytest.raises(ValueError, match="severity"):
        mutator.create_security_advisory(RUN_REPO, summary=f"{P}-a", severity="urgent")


# --- topics, collaborators, invitations ------------------------------------------------------------------------------
def test_topics_collaborators_invitations(api: responses.RequestsMock, mutator: Mutator) -> None:
    """PUT topics {names}; collaborator PUT {permission} (204 member -> {}, 201 invitation); DELETEs ignore 404."""
    api.add(responses.PUT, f"{REPO}/topics", json={"names": ["e2e", "drift"]})
    api.add(responses.PUT, f"{REPO}/collaborators/member", status=204)
    api.add(responses.PUT, f"{REPO}/collaborators/outsider", status=201, json={"id": 8, "permissions": "write"})
    api.add(responses.DELETE, f"{REPO}/collaborators/member", status=204)
    api.add(responses.DELETE, f"{REPO}/invitations/8", status=404, json={"message": "Not Found"})
    assert mutator.set_repo_topics(RUN_REPO, ["e2e", "drift"]) == ["e2e", "drift"]
    assert body(api.calls[0]) == {"names": ["e2e", "drift"]}
    assert mutator.add_repo_collaborator(RUN_REPO, "member") == {}
    assert body(api.calls[1]) == {"permission": "push"}
    assert mutator.add_repo_collaborator(RUN_REPO, "outsider", permission="maintain")["id"] == 8
    assert body(api.calls[2]) == {"permission": "maintain"}
    mutator.remove_repo_collaborator(RUN_REPO, "member")
    mutator.delete_repo_invitation(RUN_REPO, 8)
    assert [call.request.method for call in api.calls] == ["PUT", "PUT", "PUT", "DELETE", "DELETE"]


# --- teams ------------------------------------------------------------------------------------------------------------
def test_team_calls(api: responses.RequestsMock, mutator: Mutator) -> None:
    """create_team, patch_team, team memberships (PUT {role}, DELETE)."""
    team = f"{P}-excluded-a"
    api.add(responses.POST, f"{ORG}/teams", status=201, json={"slug": team, "privacy": "secret"})
    api.add(
        responses.PATCH, f"{ORG}/teams/{team}", json={"slug": team, "notification_setting": "notifications_disabled"}
    )
    api.add(responses.GET, f"{ORG}/memberships/dev", json={"state": "active", "role": "member"})
    api.add(responses.PUT, f"{ORG}/teams/{team}/memberships/dev", json={"role": "maintainer", "state": "active"})
    api.add(responses.DELETE, f"{ORG}/teams/{team}/memberships/dev", status=204)
    assert mutator.create_team(team, privacy="secret", notification_setting="notifications_disabled")["slug"] == team
    assert body(api.calls[0]) == {
        "name": team,
        "description": "",
        "privacy": "secret",
        "notification_setting": "notifications_disabled",
    }
    mutator.patch_team(team, notification_setting="notifications_disabled")
    assert body(api.calls[1]) == {"notification_setting": "notifications_disabled"}
    assert mutator.add_team_member(team, "dev", role="maintainer")["state"] == "active"
    assert body(api.calls[3]) == {"role": "maintainer"}
    mutator.remove_team_member(team, "dev")
    assert [call.request.method for call in api.calls] == ["POST", "PATCH", "GET", "PUT", "DELETE"]


def test_add_team_member_never_invites_non_members(api: responses.RequestsMock, mutator: Mutator) -> None:
    """GitHub would invite a non-member into the org: the membership must exist (active or pending) first."""
    api.add(responses.GET, f"{ORG}/memberships/stranger", status=404, json={"message": "Not Found"})
    with pytest.raises(SafetyError, match="not an org member"):
        mutator.add_team_member(f"{P}-t", "stranger")
    assert [call.request.method for call in api.calls] == ["GET"]


# --- workflows --------------------------------------------------------------------------------------------------------
def test_dispatch_workflow_payload_and_details(api: responses.RequestsMock, mutator: Mutator) -> None:
    """{ref, inputs, return_run_details: true}; the run details are returned; a 204 answer gives {}."""
    url = f"{REPO}/actions/workflows/e2e-dispatch.yml/dispatches"
    details = {"workflow_run_id": 42, "run_url": "https://api.github.com/x", "html_url": "https://github.com/x"}
    api.add(responses.POST, url, json=details)
    api.add(responses.POST, url, status=204)
    assert mutator.dispatch_workflow(RUN_REPO, "e2e-dispatch.yml", "main", {"mode": "deny"}) == details
    assert body(api.calls[0]) == {"ref": "main", "return_run_details": True, "inputs": {"mode": "deny"}}
    assert mutator.dispatch_workflow(RUN_REPO, "e2e-dispatch.yml", "main") == {}
    assert body(api.calls[1]) == {"ref": "main", "return_run_details": True}


def test_dispatch_workflow_retries_a_workflow_not_indexed_yet(
    api: responses.RequestsMock, mutator: Mutator, sleeps: list[float]
) -> None:
    """404 and 422 right after the push are retried 5 s apart; the retry budget is DISPATCH_ATTEMPTS tries."""
    url = f"{REPO}/actions/workflows/e2e.yml/dispatches"
    api.add(responses.POST, url, status=404, json={"message": "Not Found"})
    api.add(responses.POST, url, status=422, json={"message": "Workflow does not have 'workflow_dispatch' trigger"})
    api.add(responses.POST, url, status=204)
    assert mutator.dispatch_workflow(RUN_REPO, "e2e.yml", "main") == {}
    assert sleeps == [5.0, 5.0]
    api.replace(responses.POST, url, status=422, json={"message": "Workflow does not have 'workflow_dispatch' trigger"})
    with pytest.raises(GitHubError) as info:
        mutator.dispatch_workflow(RUN_REPO, "e2e.yml", "main")
    assert info.value.status == 422 and len(sleeps) == 2 + DISPATCH_ATTEMPTS - 1


def test_cancel_and_rerun(api: responses.RequestsMock, mutator: Mutator) -> None:
    """cancel/force-cancel answer 202 (True) or 409 (completed: False); rerun answers 201."""
    api.add(responses.POST, f"{REPO}/actions/runs/7/cancel", status=202, json={})
    api.add(responses.POST, f"{REPO}/actions/runs/8/cancel", status=409, json={"message": "Cannot cancel"})
    api.add(responses.POST, f"{REPO}/actions/runs/9/force-cancel", status=202, json={})
    api.add(responses.POST, f"{REPO}/actions/runs/7/rerun", status=201, json={})
    assert mutator.cancel_workflow_run(RUN_REPO, 7) is True
    assert mutator.cancel_workflow_run(RUN_REPO, 8) is False
    assert mutator.cancel_workflow_run(RUN_REPO, 9, force_cancel=True) is True
    mutator.rerun_workflow_run(RUN_REPO, 7)
    assert [str(call.request.url).rsplit("/", 2)[-1] for call in api.calls] == [
        "cancel",
        "cancel",
        "force-cancel",
        "rerun",
    ]


# --- security advisories ----------------------------------------------------------------------------------------------
def test_security_advisory_lifecycle(api: responses.RequestsMock, mutator: Mutator) -> None:
    """Create a draft (documented body), its temporary fork (202), then close it (PATCH state closed)."""
    advisory = {"ghsa_id": GHSA, "state": "draft", "summary": f"{P}-ghsa probe"}
    api.add(responses.POST, f"{REPO}/security-advisories", status=201, json=advisory)
    api.add(
        responses.POST,
        f"{REPO}/security-advisories/{GHSA}/forks",
        status=202,
        json={"name": f"{RUN_REPO}-ghsa-abcd-efgh-ijkl", "private": True},
    )
    api.add(responses.GET, f"{REPO}/security-advisories/{GHSA}", json=advisory)
    api.add(responses.PATCH, f"{REPO}/security-advisories/{GHSA}", json={**advisory, "state": "closed"})
    assert mutator.create_security_advisory(RUN_REPO, summary=f"{P}-ghsa probe")["ghsa_id"] == GHSA
    assert body(api.calls[0]) == {
        "summary": f"{P}-ghsa probe",
        "description": f"{P}-ghsa probe",
        "severity": "low",
        "vulnerabilities": [{"package": {"ecosystem": "other", "name": RUN_REPO}}],
        "start_private_fork": False,
    }
    assert mutator.create_advisory_fork(RUN_REPO, GHSA)["name"].endswith("-ghsa-abcd-efgh-ijkl")
    assert mutator.close_security_advisory(RUN_REPO, GHSA)["state"] == "closed"
    assert body(api.calls[-1]) == {"state": "closed"}


def test_close_security_advisory_checks_the_live_advisory(api: responses.RequestsMock, mutator: Mutator) -> None:
    """A vanished advisory is a no-op, a closed one is not patched again, a foreign summary is refused."""
    api.add(responses.GET, f"{REPO}/security-advisories/GHSA-gone-0000-0000", status=404, json={"message": "x"})
    api.add(
        responses.GET,
        f"{REPO}/security-advisories/GHSA-done-0000-0000",
        json={"ghsa_id": "GHSA-done-0000-0000", "state": "closed", "summary": f"{P}-x"},
    )
    api.add(
        responses.GET,
        f"{REPO}/security-advisories/GHSA-real-0000-0000",
        json={"ghsa_id": "GHSA-real-0000-0000", "state": "draft", "summary": "a real report"},
    )
    assert mutator.close_security_advisory(RUN_REPO, "GHSA-gone-0000-0000") == {}
    assert mutator.close_security_advisory(RUN_REPO, "GHSA-done-0000-0000")["state"] == "closed"
    with pytest.raises(SafetyError):
        mutator.close_security_advisory(RUN_REPO, "GHSA-real-0000-0000")
    assert all(call.request.method == "GET" for call in api.calls)


# --- code security configurations -----------------------------------------------------------------------------------
def test_code_security_configuration_lifecycle(api: responses.RequestsMock, mutator: Mutator) -> None:
    """Create (name, description, settings), set as default (live name checked), delete (live name checked)."""
    name = f"{P}-csd"
    api.add(responses.POST, f"{ORG}/code-security/configurations", status=201, json={"id": 12, "name": name})
    api.add(responses.GET, f"{ORG}/code-security/configurations/12", json={"id": 12, "name": name})
    api.add(
        responses.PUT,
        f"{ORG}/code-security/configurations/12/defaults",
        json={"default_for_new_repos": "public", "configuration": {"id": 12}},
    )
    api.add(responses.DELETE, f"{ORG}/code-security/configurations/12", status=204)
    created = mutator.create_code_security_configuration(name, dependency_graph="enabled")
    assert created["id"] == 12
    assert body(api.calls[0]) == {"name": name, "description": "otterdog-e2e probe", "dependency_graph": "enabled"}
    assert mutator.set_code_security_default(12, name=name, default_for_new_repos="public")["default_for_new_repos"]
    assert body(api.calls[2]) == {"default_for_new_repos": "public"}
    mutator.delete_code_security_configuration(12, name=name)
    assert [call.request.method for call in api.calls] == ["POST", "GET", "PUT", "GET", "DELETE"]


def test_code_security_configuration_live_name_checks(api: responses.RequestsMock, mutator: Mutator) -> None:
    """Another live name is refused; a vanished configuration is a 404 for set-default and a no-op for delete."""
    name = f"{P}-csd"
    api.add(responses.GET, f"{ORG}/code-security/configurations/1", json={"id": 1, "name": "GitHub recommended"})
    api.add(responses.GET, f"{ORG}/code-security/configurations/2", status=404, json={"message": "Not Found"})
    with pytest.raises(SafetyError):
        mutator.set_code_security_default(1, name=name, default_for_new_repos="none")
    with pytest.raises(SafetyError):
        mutator.delete_code_security_configuration(1, name=name)
    with pytest.raises(GitHubError) as info:
        mutator.set_code_security_default(2, name=name, default_for_new_repos="none")
    assert info.value.status == 404
    mutator.delete_code_security_configuration(2, name=name)
    assert all(call.request.method == "GET" for call in api.calls)


# --- pull request edits -----------------------------------------------------------------------------------------------
def test_edit_comment_on_a_run_pull_request(api: responses.RequestsMock, mutator: Mutator) -> None:
    """The comment's issue_url gives the pull request, whose head must be a run branch of the repository."""
    api.add(
        responses.GET,
        f"{CONFIG}/issues/comments/55",
        json={"id": 55, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/3"},
    )
    api.add(responses.GET, f"{CONFIG}/pulls/3", json=run_pull(3))
    api.add(responses.PATCH, f"{CONFIG}/issues/comments/55", json={"id": 55, "body": "/otterdog done"})
    assert mutator.edit_comment(".otterdog", 55, "/otterdog done")["body"] == "/otterdog done"
    assert body(api.calls[-1]) == {"body": "/otterdog done"}


@pytest.mark.parametrize(
    ("comment", "pull"),
    [
        (None, None),  # the comment does not exist
        ({"id": 55, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/3"}, None),  # an issue, not a PR
        ({"id": 55, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/3"}, run_pull(3, ref="main")),
        (
            {"id": 55, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/3"},
            run_pull(3, repo="someone-fork"),
        ),
        ({"id": 55}, None),  # no issue_url
    ],
)
def test_edit_comment_guard(
    api: responses.RequestsMock, mutator: Mutator, comment: dict[str, Any] | None, pull: dict[str, Any] | None
) -> None:
    """Missing comments, issues, non-run branches and fork heads are refused without any write."""
    api.add(responses.GET, f"{CONFIG}/issues/comments/55", status=200 if comment else 404, json=comment or {})
    api.add(responses.GET, f"{CONFIG}/pulls/3", status=200 if pull else 404, json=pull or {"message": "Not Found"})
    with pytest.raises(SafetyError):
        mutator.edit_comment(".otterdog", 55, "x")
    assert all(call.request.method == "GET" for call in api.calls)


def test_dismiss_review_and_draft_mutations(api: responses.RequestsMock, mutator: Mutator) -> None:
    """dismissals {message, event DISMISS}; ready/draft GraphQL mutations with the pull request node id."""
    api.add(responses.GET, f"{CONFIG}/pulls/3", json=run_pull(3))
    api.add(responses.PUT, f"{CONFIG}/pulls/3/reviews/77/dismissals", json={"id": 77, "state": "DISMISSED"})
    api.add(responses.POST, GRAPHQL, json={"data": {"markPullRequestReadyForReview": {"pullRequest": {}}}})
    api.add(responses.POST, GRAPHQL, json={"data": {"convertPullRequestToDraft": {"pullRequest": {}}}})
    assert mutator.dismiss_review(".otterdog", 3, 77)["state"] == "DISMISSED"
    assert body(api.calls[1]) == {"message": "e2e: dismissed", "event": "DISMISS"}
    mutator.mark_pull_ready(".otterdog", 3)
    mutator.convert_pull_to_draft(".otterdog", 3)
    graphql = [body(call) for call in api.calls if str(call.request.url) == GRAPHQL]
    assert graphql == [
        {"query": READY_FOR_REVIEW_MUTATION, "variables": {"id": "PR_3"}},
        {"query": CONVERT_TO_DRAFT_MUTATION, "variables": {"id": "PR_3"}},
    ]


def test_pull_request_guards_refuse_foreign_heads(api: responses.RequestsMock, mutator: Mutator) -> None:
    """dismiss_review and the draft mutations need a run branch head."""
    api.add(responses.GET, f"{CONFIG}/pulls/4", json=run_pull(4, ref="feature/x"))
    for call in (
        lambda: mutator.dismiss_review(".otterdog", 4, 1),
        lambda: mutator.mark_pull_ready(".otterdog", 4),
        lambda: mutator.convert_pull_to_draft(".otterdog", 4),
    ):
        with pytest.raises(SafetyError):
            call()
    assert all(call.request.method == "GET" for call in api.calls)


def test_reopen_pull_and_delete_comment(api: responses.RequestsMock, mutator: Mutator) -> None:
    """reopen_pull PATCHes state open; delete_comment DELETEs a comment of a run pull request (gone: no-op)."""
    api.add(responses.GET, f"{CONFIG}/pulls/3", json=run_pull(3))
    api.add(responses.PATCH, f"{CONFIG}/pulls/3", json={"number": 3, "state": "open"})
    mutator.reopen_pull(".otterdog", 3)
    assert body(api.calls[-1]) == {"state": "open"}
    api.add(
        responses.GET,
        f"{CONFIG}/issues/comments/56",
        json={"id": 56, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/3"},
    )
    api.add(responses.DELETE, f"{CONFIG}/issues/comments/56", status=204)
    mutator.delete_comment(".otterdog", 56)
    assert api.calls[-1].request.method == "DELETE"
    api.add(responses.GET, f"{CONFIG}/issues/comments/57", status=404, json={"message": "Not Found"})
    count = len(api.calls)
    mutator.delete_comment(".otterdog", 57)
    assert len(api.calls) == count + 1  # only the GET


@pytest.mark.parametrize(
    "pull",
    [
        run_pull(4, ref="feature/x"),
        run_pull(4, repo="someone-fork"),
        run_pull(4, ref="otterdog/blueprint/default-security-policy"),
    ],
)
def test_reopen_and_delete_comment_guards(api: responses.RequestsMock, mutator: Mutator, pull: dict[str, Any]) -> None:
    """Foreign heads, fork heads and other blueprints' branches are refused without any write."""
    api.add(responses.GET, f"{CONFIG}/pulls/4", json=pull)
    api.add(
        responses.GET,
        f"{CONFIG}/issues/comments/58",
        json={"id": 58, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/4"},
    )
    with pytest.raises(SafetyError):
        mutator.reopen_pull(".otterdog", 4)
    with pytest.raises(SafetyError):
        mutator.delete_comment(".otterdog", 58)
    assert all(call.request.method == "GET" for call in api.calls)


def test_reopen_and_delete_comment_in_dry_run(api: responses.RequestsMock) -> None:
    """dry_run: the guard reads run, nothing is written."""
    dry = Mutator(GitHubHttp(TOKEN, read_only=True), make_verified_org(), dry_run=True)
    api.add(responses.GET, f"{CONFIG}/pulls/3", json=run_pull(3))
    api.add(
        responses.GET,
        f"{CONFIG}/issues/comments/9",
        json={"id": 9, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/3"},
    )
    dry.reopen_pull(".otterdog", 3)
    dry.delete_comment(".otterdog", 9)
    assert {call.request.method for call in api.calls} == {"GET"}


def test_blueprint_remediation_branches_of_the_run_are_run_branches(
    api: responses.RequestsMock, mutator: Mutator
) -> None:
    """The webapp's remediation PR of a run blueprint (otterdog/blueprint/e2e-<run>-...) may be reopened and edited."""
    pull = run_pull(5, ref=f"otterdog/blueprint/{P}-required-file", repo=RUN_REPO)
    api.add(responses.GET, f"{REPO}/pulls/5", json=pull)
    api.add(responses.PATCH, f"{REPO}/pulls/5", json={"number": 5, "state": "open"})
    api.add(responses.POST, GRAPHQL, json={"data": {"markPullRequestReadyForReview": {"pullRequest": {}}}})
    mutator.reopen_pull(RUN_REPO, 5)
    mutator.mark_pull_ready(RUN_REPO, 5)
    assert [call.request.method for call in api.calls] == ["GET", "PATCH", "GET", "POST"]


# --- dry run ----------------------------------------------------------------------------------------------------------
def test_dry_run_never_writes(api: responses.RequestsMock) -> None:
    """dry_run: only the guard reads are sent; writes return placeholders."""
    verified = make_verified_org()
    dry = Mutator(GitHubHttp(TOKEN, read_only=True), verified, dry_run=True)
    api.add(responses.GET, f"{CONFIG}/pulls/3", json=run_pull(3))
    api.add(
        responses.GET,
        f"{CONFIG}/issues/comments/5",
        json={"id": 5, "issue_url": f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog/issues/3"},
    )
    api.add(responses.GET, f"{REPO}/security-advisories/{GHSA}", json={"summary": f"{P}-x", "state": "draft"})
    api.add(responses.GET, f"{ORG}/code-security/configurations/3", json={"id": 3, "name": f"{P}-c"})
    api.add(responses.GET, f"{ORG}/memberships/u", json={"state": "pending", "role": "member"})
    assert dry.set_repo_topics(RUN_REPO, ["a"]) == ["a"]
    assert dry.add_repo_collaborator(RUN_REPO, "u") == {"dry_run": True}
    dry.remove_repo_collaborator(RUN_REPO, "u")
    dry.delete_repo_invitation(RUN_REPO, 1)
    assert dry.create_team(f"{P}-t")["dry_run"] is True
    assert dry.patch_team(f"{P}-t", privacy="secret") == {"slug": f"{P}-t", "privacy": "secret"}
    assert dry.add_team_member(f"{P}-t", "u")["dry_run"] is True
    dry.remove_team_member(f"{P}-t", "u")
    assert dry.dispatch_workflow(RUN_REPO, "e2e.yml", "main") == {"dry_run": True}
    assert dry.cancel_workflow_run(RUN_REPO, 1) is True
    dry.rerun_workflow_run(RUN_REPO, 1)
    assert dry.create_security_advisory(RUN_REPO, summary=f"{P}-x")["ghsa_id"] == DRY_RUN_GHSA
    assert dry.create_advisory_fork(RUN_REPO, GHSA)["dry_run"] is True
    assert dry.close_security_advisory(RUN_REPO, GHSA)["dry_run"] is True
    assert dry.create_code_security_configuration(f"{P}-c")["dry_run"] is True
    assert dry.set_code_security_default(3, name=f"{P}-c", default_for_new_repos="none")["dry_run"] is True
    dry.delete_code_security_configuration(3, name=f"{P}-c")
    assert dry.edit_comment(".otterdog", 5, "x")["dry_run"] is True
    assert dry.dismiss_review(".otterdog", 3, 1)["dry_run"] is True
    dry.mark_pull_ready(".otterdog", 3)
    dry.convert_pull_to_draft(".otterdog", 3)
    assert {call.request.method for call in api.calls} == {"GET"}
