"""Check kinds of the battery (scenarios.checks.CHECK_KINDS): validation, evaluation over FakeOracle and the real
Oracle, the FakeOracle builders and the RecordingMutator probes that keep the fake state consistent."""

from __future__ import annotations

from typing import Any

import pytest

from otterdog_e2e.github.oracle import Oracle
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.scenarios.checks import CHECK_KINDS, LIST_KINDS, CheckError, evaluate_check, validate_check
from otterdog_e2e.testing.fakes import (
    FAKE_ORG,
    FAKE_RUN_ID,
    FakeGitHubHttp,
    FakeOracle,
    RecordingMutator,
    make_verified_org,
)

P = f"e2e-{FAKE_RUN_ID}"
REPO = f"{P}-r"
HOOK = f"https://otterdog-e2e.invalid/{FAKE_RUN_ID}/hook"

NEW_KINDS = {
    "org_selected_actions",
    "org_actions_selected_repositories",
    "org_fork_pr_approval",
    "org_fork_pr_workflows_private_repos",
    "org_cache_storage_limit",
    "org_cache_storage_limit_orgs_path",
    "security_managers",
    "org_role_teams",
    "code_security_defaults",
    "code_security_configuration",
    "org_members",
    "org_members_2fa_disabled",
    "org_membership",
    "org_invitations",
    "org_security_advisories",
    "team_membership",
    "team_invitations",
    "repo_selected_actions",
    "repo_fork_pr_approval",
    "repo_fork_pr_workflows_private_repos",
    "repo_cache_storage_limit",
    "workflow",
    "workflow_runs",
    "repo_workflow_runs",
    "repo_security_and_analysis",
    "repo_vulnerability_alerts",
    "repo_automated_security_fixes",
    "repo_private_vulnerability_reporting",
    "repo_code_scanning_default_setup",
    "repo_security_advisories",
    "repo_security_advisory",
    "repo_branches",
    "repo_branch",
    "repo_default_branch",
    "repo_teams",
    "repo_collaborators",
    "repo_collaborator_permission",
    "repo_invitations",
    "org_webhook_delivery",
    "repo_webhook_delivery",
}


def ok(oracle: Any, check: dict[str, Any]) -> bool:
    """evaluate_check(...).ok, with the message on failure."""
    result = evaluate_check(oracle, check)
    assert result.ok, result.message
    return True


def fails(oracle: Any, check: dict[str, Any], text: str = "") -> str:
    """The message of a failing check (asserting it fails and contains ``text``)."""
    result = evaluate_check(oracle, check)
    assert not result.ok and text in result.message, result.message
    return result.message


# --- vocabulary ----------------------------------------------------------------------------------------------------
def test_new_kinds_are_registered() -> None:
    """Every kind of the battery exists; list kinds refuse ``absent``, single kinds accept it."""
    assert set(CHECK_KINDS) >= NEW_KINDS
    for kind in NEW_KINDS:
        params = dict.fromkeys(CHECK_KINDS[kind][1], "x")
        if kind in LIST_KINDS:
            with pytest.raises(CheckError, match="absent is only valid"):
                validate_check({"kind": kind, **params, "absent": True})
        else:
            validate_check({"kind": kind, **params, "absent": True})
        validate_check({"kind": kind, **params, "unavailable": True})


@pytest.mark.parametrize(
    ("check", "match"),
    [
        ({"kind": "repo_branch", "repo": "r", "absent": True}, r"parameter\(s\) \['branch'\]"),
        ({"kind": "team_membership", "slug": "t", "username": "u", "absent": True}, "unknown key"),
        ({"kind": "org_webhook_delivery", "url": "u", "match": {}}, r"\['event'\]"),
        ({"kind": "repo_collaborator_permission", "repo": "r", "login": "", "absent": True}, "non-empty"),
    ],
)
def test_new_kinds_validate_their_parameters(check: dict[str, Any], match: str) -> None:
    """Parameters of the new kinds are required, named and non-empty."""
    with pytest.raises(CheckError, match=match):
        validate_check(check)


# --- evaluation over FakeOracle --------------------------------------------------------------------------------------
def test_actions_and_feature_kinds() -> None:
    """Feature settings match; a setting marked unavailable satisfies ``unavailable``, and ``absent`` only with
    ``unavailable_ok`` (an unavailable answer is no evidence of absence, BAT-11)."""
    oracle = FakeOracle()
    oracle.add_repo(REPO)
    oracle.set("org_selected_actions", value={"github_owned_allowed": True, "patterns_allowed": ["actions/*"]})
    oracle.set("org_actions_selected_repositories", value=[REPO, ".otterdog"])
    oracle.set("org_fork_pr_approval", value={"approval_policy": "all_external_contributors"})
    oracle.set("repo_cache_storage_limit", REPO, value={"max_cache_size_gb": 5})
    oracle.mark_unavailable("org_cache_storage_limit_orgs_path", status=404)
    ok(oracle, {"kind": "org_selected_actions", "match": {"github_owned_allowed": True}})
    ok(oracle, {"kind": "org_actions_selected_repositories", "contains": [REPO]})
    ok(oracle, {"kind": "org_fork_pr_approval", "match": {"approval_policy": "all_external_contributors"}})
    ok(oracle, {"kind": "repo_cache_storage_limit", "repo": REPO, "match": {"max_cache_size_gb": 5}})
    ok(oracle, {"kind": "org_cache_storage_limit_orgs_path", "unavailable": True})
    fails(oracle, {"kind": "org_cache_storage_limit_orgs_path", "absent": True}, "cannot be trusted")
    ok(oracle, {"kind": "org_cache_storage_limit_orgs_path", "absent": True, "unavailable_ok": True})
    fails(oracle, {"kind": "org_cache_storage_limit_orgs_path", "match": {"max_cache_size_gb": 5}}, "unavailable")
    ok(oracle, {"kind": "org_cache_storage_limit", "unavailable": False})
    ok(oracle, {"kind": "repo_selected_actions", "repo": REPO, "absent": True})


def test_security_kinds() -> None:
    """security_and_analysis comes from the repository, flags default to disabled on existing repositories."""
    oracle = FakeOracle()
    oracle.add_repo(REPO, security_and_analysis={"secret_scanning": {"status": "enabled"}})
    oracle.set("repo_vulnerability_alerts", REPO, value={"enabled": True})
    oracle.set("repo_code_scanning_default_setup", REPO, value={"state": "configured", "languages": ["python"]})
    oracle.mark_unavailable("repo_private_vulnerability_reporting", REPO, status=422)
    ok(
        oracle,
        {"kind": "repo_security_and_analysis", "repo": REPO, "match": {"secret_scanning": {"status": "enabled"}}},
    )
    ok(oracle, {"kind": "repo_vulnerability_alerts", "repo": REPO, "match": {"enabled": True}})
    ok(oracle, {"kind": "repo_automated_security_fixes", "repo": REPO, "equals": {"enabled": False}})
    fails(oracle, {"kind": "repo_automated_security_fixes", "repo": f"{P}-missing", "absent": True}, "parent repo")
    ok(
        oracle,
        {"kind": "repo_code_scanning_default_setup", "repo": REPO, "match": {"languages": {"$unordered": ["python"]}}},
    )
    ok(oracle, {"kind": "repo_private_vulnerability_reporting", "repo": REPO, "unavailable": True})


def test_roles_members_and_invitations_kinds() -> None:
    """security_managers falls back to the security_manager role teams; members carry their role."""
    oracle = FakeOracle()
    oracle.set("org_role_teams", "security_manager", value=[f"{P}-sec"])
    oracle.set("members_with_role", value=[{"login": "owner", "role": "admin"}, {"login": "dev", "role": "member"}])
    oracle.set("membership", "dev", value={"state": "active", "role": "member"})
    oracle.set("org_invitations", value=[{"login": "newbie", "role": "direct_member"}])
    oracle.add_team(f"{P}-t", members=["dev"])
    ok(oracle, {"kind": "security_managers", "equals": [f"{P}-sec"]})
    ok(oracle, {"kind": "org_role_teams", "name": "security_manager", "contains": [f"{P}-sec"]})
    ok(oracle, {"kind": "org_members", "contains": [{"login": "owner", "role": "admin"}]})
    ok(oracle, {"kind": "org_membership", "login": "dev", "match": {"role": "member"}})
    ok(oracle, {"kind": "org_invitations", "contains": [{"login": "newbie"}]})
    ok(oracle, {"kind": "team_membership", "slug": f"{P}-t", "login": "dev", "match": {"state": "active"}})
    ok(oracle, {"kind": "team_membership", "slug": f"{P}-t", "login": "other", "absent": True})
    oracle.set("security_managers", value=[])
    ok(oracle, {"kind": "security_managers", "equals": []})


def test_code_security_kinds_follow_the_builders() -> None:
    """A configuration with a default appears in code_security_defaults."""
    oracle = FakeOracle()
    oracle.add_code_security_configuration("GitHub recommended")
    created = oracle.add_code_security_configuration(f"{P}-csd", default_for_new_repos="public")
    ok(oracle, {"kind": "code_security_configuration", "name": f"{P}-csd", "match": {"id": created["id"]}})
    ok(oracle, {"kind": "code_security_defaults", "match": [{"default_for_new_repos": "public"}]})
    ok(oracle, {"kind": "code_security_configuration", "name": "missing", "absent": True})


def test_branch_kinds() -> None:
    """Branches from add_branch; repo_default_branch is the repository's default_branch."""
    oracle = FakeOracle()
    oracle.add_repo(REPO, default_branch="master")
    oracle.add_branch(REPO, "master", protected=True)
    oracle.add_branch(REPO, "develop")
    ok(oracle, {"kind": "repo_branches", "repo": REPO, "equals": ["master", "develop"]})
    ok(oracle, {"kind": "repo_branch", "repo": REPO, "branch": "master", "match": {"protected": True}})
    ok(oracle, {"kind": "repo_branch", "repo": REPO, "branch": "main", "absent": True})
    ok(oracle, {"kind": "repo_default_branch", "repo": REPO, "equals": "master"})
    develop = oracle.repo_branch(REPO, "develop")
    assert develop is not None and oracle.branch_sha(REPO, "develop") == develop["commit"]["sha"]


def test_workflow_kinds() -> None:
    """Runs from add_workflow_run, newest first, per workflow and for the whole repository."""
    oracle = FakeOracle()
    first = oracle.add_workflow_run(REPO, "a.yml", status="completed", conclusion="success")
    second = oracle.add_workflow_run(REPO, "b.yml")
    oracle.set("workflow", REPO, "a.yml", value={"id": 1, "state": "active"})
    ok(oracle, {"kind": "workflow", "repo": REPO, "workflow": "a.yml", "match": {"state": "active"}})
    ok(oracle, {"kind": "workflow_runs", "repo": REPO, "workflow": "a.yml", "match": [{"conclusion": "success"}]})
    ok(oracle, {"kind": "repo_workflow_runs", "repo": REPO, "match": [{"id": second["id"]}, {"id": first["id"]}]})
    assert oracle.find_workflow_runs(REPO, status="success") == [first]
    assert oracle.find_workflow_runs(REPO, workflow="b.yml", event="workflow_dispatch") == [second]
    assert oracle.find_workflow_runs(REPO, branch="other") == []
    assert oracle.workflow_run(REPO, first["id"]) == first and oracle.workflow_run(REPO, 0) is None


def test_access_and_advisory_kinds() -> None:
    """Teams, collaborators (derived permission) and advisories (org listing derived from the repositories)."""
    oracle = FakeOracle()
    oracle.add_repo(REPO)
    oracle.set("repo_teams", REPO, value=[{"slug": f"{P}-t", "permission": "push"}])
    oracle.set("repo_collaborators", REPO, value=[{"login": "dev", "role_name": "maintain"}])
    advisory = oracle.add_security_advisory(REPO, summary=f"{P}-ghsa")
    ok(oracle, {"kind": "repo_teams", "repo": REPO, "contains": [{"slug": f"{P}-t", "permission": "push"}]})
    ok(oracle, {"kind": "repo_collaborators", "repo": REPO, "contains": [{"login": "dev"}]})
    permission = {"kind": "repo_collaborator_permission", "repo": REPO, "login": "dev"}
    ok(oracle, {**permission, "match": {"permission": "write", "role_name": "maintain"}})
    ok(oracle, {**permission, "login": "nobody", "absent": True})
    ok(oracle, {"kind": "repo_security_advisories", "repo": REPO, "match": [{"state": "draft"}]})
    ok(oracle, {"kind": "repo_security_advisory", "repo": REPO, "ghsa_id": advisory["ghsa_id"], "absent": False})
    ok(oracle, {"kind": "org_security_advisories", "contains": [{"summary": f"{P}-ghsa"}]})


def test_webhook_delivery_kinds() -> None:
    """The newest delivery of the event, in full; absent without hook or matching delivery."""
    oracle = FakeOracle()
    oracle.add_repo(REPO)
    hook = oracle.add_org_hook(HOOK)
    oracle.set("org_hook_deliveries", hook["id"], value=[{"id": 2, "event": "ping"}, {"id": 1, "event": "ping"}])
    headers = {"X-Hub-Signature-256": "sha256=abc"}
    oracle.set("org_hook_delivery", hook["id"], 2, value={"id": 2, "request": {"headers": headers}})
    check = {"kind": "org_webhook_delivery", "url": HOOK, "event": "ping"}
    ok(oracle, {**check, "match": {"request": {"headers": {"X-Hub-Signature-256": {"$regex": "^sha256="}}}}})
    ok(oracle, {**check, "event": "push", "absent": True})
    repo_hook = oracle.add_repo_hook(REPO, HOOK)
    oracle.set("repo_hook_deliveries", REPO, repo_hook["id"], value=[{"id": 9, "event": "push", "request": {}}])
    ok(oracle, {"kind": "repo_webhook_delivery", "repo": REPO, "url": HOOK, "event": "push", "match": {"id": 9}})
    ok(oracle, {"kind": "repo_webhook_delivery", "repo": REPO, "url": f"{HOOK}x", "event": "push", "absent": True})


# --- RecordingMutator keeps the FakeOracle consistent ----------------------------------------------------------------
def test_recording_mutator_probes_update_the_oracle() -> None:
    """Team memberships, topics, collaborators, runs, advisories and code security configurations."""
    oracle = FakeOracle()
    mutator = RecordingMutator(oracle=oracle)
    oracle.add_repo(REPO)
    team = mutator.create_team(f"{P}-t", privacy="secret")
    assert oracle.team(f"{P}-t")["privacy"] == "secret" and team["slug"] == f"{P}-t"  # type: ignore[index]
    mutator.add_team_member(f"{P}-t", "dev")
    ok(oracle, {"kind": "team_members", "slug": f"{P}-t", "equals": ["dev"]})
    ok(oracle, {"kind": "team_membership", "slug": f"{P}-t", "login": "dev", "absent": False})
    mutator.remove_team_member(f"{P}-t", "dev")
    ok(oracle, {"kind": "team_members", "slug": f"{P}-t", "equals": []})
    assert mutator.patch_team(f"{P}-t", notification_setting="notifications_disabled")["privacy"] == "secret"
    ok(oracle, {"kind": "team", "slug": f"{P}-t", "match": {"notification_setting": "notifications_disabled"}})
    mutator.set_repo_topics(REPO, ["drift"])
    ok(oracle, {"kind": "repo_topics", "name": REPO, "equals": ["drift"]})
    mutator.add_repo_collaborator(REPO, "dev", permission="push")
    ok(oracle, {"kind": "repo_collaborator_permission", "repo": REPO, "login": "dev", "match": {"permission": "write"}})
    mutator.remove_repo_collaborator(REPO, "dev")
    ok(oracle, {"kind": "repo_collaborators", "repo": REPO, "equals": []})

    details = mutator.dispatch_workflow(REPO, "e2e.yml", "main", {"mode": "deny"})
    run = {"kind": "workflow_runs", "repo": REPO, "workflow": "e2e.yml"}
    ok(oracle, {**run, "match": [{"id": details["workflow_run_id"], "status": "queued", "head_branch": "main"}]})
    assert mutator.cancel_workflow_run(REPO, details["workflow_run_id"]) is True
    ok(oracle, {**run, "match": [{"status": "completed", "conclusion": "cancelled"}]})
    assert mutator.cancel_workflow_run(REPO, details["workflow_run_id"]) is False
    mutator.rerun_workflow_run(REPO, details["workflow_run_id"])
    ok(oracle, {**run, "match": [{"status": "queued", "run_attempt": 2}]})

    advisory = mutator.create_security_advisory(REPO, summary=f"{P}-ghsa probe")
    fork = mutator.create_advisory_fork(REPO, advisory["ghsa_id"])
    assert oracle.repo(fork["name"])["fork"] is True  # type: ignore[index]
    assert mutator.close_security_advisory(REPO, advisory["ghsa_id"])["state"] == "closed"
    ok(
        oracle,
        {"kind": "repo_security_advisory", "repo": REPO, "ghsa_id": advisory["ghsa_id"], "match": {"state": "closed"}},
    )

    configuration = mutator.create_code_security_configuration(f"{P}-csd", dependency_graph="enabled")
    mutator.set_code_security_default(configuration["id"], name=f"{P}-csd", default_for_new_repos="all")
    ok(oracle, {"kind": "code_security_defaults", "match": [{"default_for_new_repos": "all"}]})
    mutator.set_code_security_default(configuration["id"], name=f"{P}-csd", default_for_new_repos="none")
    ok(oracle, {"kind": "code_security_defaults", "equals": []})
    mutator.delete_code_security_configuration(configuration["id"], name=f"{P}-csd")
    ok(oracle, {"kind": "code_security_configuration", "name": f"{P}-csd", "absent": True})
    assert [call.method for call in mutator.calls][:2] == ["create_team", "add_team_member"]


def test_recording_mutator_guards_and_pull_requests() -> None:
    """Guards of the fake mirror the Mutator; draft mutations update the oracle's pull request."""
    oracle = FakeOracle()
    mutator = RecordingMutator(oracle=oracle)
    for call in (
        lambda: mutator.add_team_member("project-leads", "dev"),
        lambda: mutator.set_repo_topics(".otterdog", ["x"]),
        lambda: mutator.dispatch_workflow(".otterdog", "ci.yml", "main"),
        lambda: mutator.create_security_advisory(REPO, summary="real report"),
        lambda: mutator.create_code_security_configuration("GitHub recommended"),
        lambda: mutator.delete_code_security_configuration(1, name="GitHub recommended"),
        lambda: mutator.patch_team(f"{P}-t", name="admins"),
    ):
        with pytest.raises(SafetyError):
            call()
    pull = mutator.create_pull(".otterdog", head=f"e2e/{FAKE_RUN_ID}/x", base="main", title="t", draft=True)
    mutator.mark_pull_ready(".otterdog", pull["number"])
    assert oracle.pull(".otterdog", pull["number"])["draft"] is False  # type: ignore[index]
    mutator.convert_pull_to_draft(".otterdog", pull["number"])
    assert oracle.pull(".otterdog", pull["number"])["draft"] is True  # type: ignore[index]
    assert mutator.dismiss_review(".otterdog", pull["number"], 3)["state"] == "DISMISSED"
    foreign = mutator.create_pull(".otterdog", head="feature/x", base="main", title="t")
    with pytest.raises(SafetyError):
        mutator.dismiss_review(".otterdog", foreign["number"], 3)
    assert RecordingMutator(guard=False).add_team_member("project-leads", "dev")["state"] == "active"
    oracle.set("members", value=["dev"])  # once the fake knows the members, a stranger is refused like a non-member
    oracle.add_team(f"{P}-t")
    assert mutator.add_team_member(f"{P}-t", "dev")["state"] == "active"
    with pytest.raises(SafetyError, match="not an org member"):
        mutator.add_team_member(f"{P}-t", "stranger")
    oracle.set("membership", "invited", value={"state": "pending", "role": "member"})
    mutator.add_team_member(f"{P}-t", "invited")
    assert oracle.team_members(f"{P}-t") == ["dev", "invited"]


# --- the real Oracle over FakeGitHubHttp -----------------------------------------------------------------------------
def test_feature_kinds_with_the_real_oracle() -> None:
    """unavailable/absent for a plan-gated setting, the 409 'does not apply' case and a 204 flag."""
    http = FakeGitHubHttp(read_only=True)
    repo = f"/repos/{FAKE_ORG}/{REPO}"
    http.add("GET", f"/organizations/{FAKE_ORG}/actions/cache/storage-limit", status=403, json={}, repeat=True)
    http.add("GET", f"/orgs/{FAKE_ORG}/actions/permissions/selected-actions", status=409, json={}, repeat=True)
    http.add("GET", f"{repo}/vulnerability-alerts", status=204, repeat=True)
    http.add("GET", f"{repo}/private-vulnerability-reporting", json={"enabled": False}, repeat=True)
    oracle = Oracle(http, FAKE_ORG)  # type: ignore[arg-type]
    ok(oracle, {"kind": "org_cache_storage_limit", "unavailable": True})
    fails(oracle, {"kind": "org_cache_storage_limit", "absent": True}, "cannot be trusted")
    ok(oracle, {"kind": "org_cache_storage_limit", "absent": True, "unavailable_ok": True})
    ok(oracle, {"kind": "org_selected_actions", "absent": True})  # 409: the setting does not apply (no record)
    ok(oracle, {"kind": "org_selected_actions", "unavailable": False})
    ok(oracle, {"kind": "repo_vulnerability_alerts", "repo": REPO, "match": {"enabled": True}})
    ok(oracle, {"kind": "repo_private_vulnerability_reporting", "repo": REPO, "match": {"enabled": False}})
    assert oracle.unavailable == {("org_cache_storage_limit", FAKE_ORG): 403}


def test_verified_org_helpers_are_unchanged() -> None:
    """The fakes keep working with the shared helpers (sanity for the parity suite)."""
    assert RecordingMutator(make_verified_org()).org == FAKE_ORG


def test_absent_and_empty_answers_need_an_available_listing_and_a_parent() -> None:
    """BAT-11: absent / equals [] answered by a listing that answered 403/404 are failures (retried), unless the
    check opts in with unavailable_ok; an absent nested object needs its parent (repository, team, environment)."""
    oracle = FakeOracle()
    oracle.add_repo(REPO)
    oracle.add_team(f"{P}-t")
    oracle.mark_unavailable("repo_rulesets", REPO, status=403)
    oracle.mark_unavailable("org_rulesets", status=403)
    oracle.mark_unavailable("team_members", f"{P}-gone", status=404)
    fails(oracle, {"kind": "repo_ruleset", "repo": REPO, "name": "r", "absent": True}, "cannot be trusted")
    fails(oracle, {"kind": "org_ruleset", "name": "r", "absent": True}, "cannot be trusted")
    fails(oracle, {"kind": "team_members", "slug": f"{P}-gone", "equals": []}, "cannot be trusted")
    ok(oracle, {"kind": "repo_ruleset", "repo": REPO, "name": "r", "absent": True, "unavailable_ok": True})
    ok(oracle, {"kind": "team_members", "slug": f"{P}-t", "equals": []})
    fails(oracle, {"kind": "bpr", "repo": f"{P}-deleted", "pattern": "main", "absent": True}, "parent repo")
    fails(oracle, {"kind": "team_repo_permission", "slug": f"{P}-none", "repo": REPO, "absent": True}, "parent team")
    fails(oracle, {"kind": "env_secret", "repo": REPO, "env": "prod", "name": "S", "absent": True}, "environment")
    ok(oracle, {"kind": "team_repo_permission", "slug": f"{P}-t", "repo": REPO, "absent": True})
