"""Oracle feature lookups of the battery: Actions settings, security, roles, members, branches, access, workflow runs,
advisories, delivery details and the detailed branch protection rule (endpoints, parameters, 403/404/409 semantics)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
import responses
from responses import matchers

from otterdog_e2e.github.http import GITHUB_API, GitHubError, GitHubHttp
from otterdog_e2e.github.oracle import (
    BPR_ALLOWANCES,
    BPR_DETAIL_QUERY,
    BPR_FIELDS,
    BPR_QUERY,
    SECURITY_MANAGER_ROLE,
    Oracle,
)
from otterdog_e2e.testing.fakes import FAKE_ORG

ORG = f"{GITHUB_API}/orgs/{FAKE_ORG}"
ORGANIZATIONS = f"{GITHUB_API}/organizations/{FAKE_ORG}"
REPO = f"{GITHUB_API}/repos/{FAKE_ORG}/r"
GRAPHQL = f"{GITHUB_API}/graphql"
NOT_FOUND = {"message": "Not Found"}


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked api.github.com."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def oracle() -> Oracle:
    """Oracle over a read-only client (no sleeping)."""
    http = GitHubHttp("ghp_" + "OracleFeatureToken0123456789abcdefghij", read_only=True, sleep=lambda _: None)
    return Oracle(http, FAKE_ORG)


def per_page(**params: str) -> list[Any]:
    """Matcher of the exact query parameters of a paginated listing (per_page 100 plus ``params``)."""
    return [matchers.query_param_matcher({"per_page": "100", **params})]


def no_params() -> list[Any]:
    """Matcher of a request without query parameters."""
    return [matchers.query_param_matcher({})]


def sent(call: Any) -> Any:
    """Decoded JSON body of a recorded request."""
    return json.loads(call.request.body or "{}")


# --- organization Actions settings ---------------------------------------------------------------------------------
def test_org_selected_actions_and_feature_semantics(api: responses.RequestsMock, oracle: Oracle) -> None:
    """200 -> the object; 409 (policy not 'selected') -> None without a record; 404 -> None recorded unavailable."""
    url = f"{ORG}/actions/permissions/selected-actions"
    body = {"github_owned_allowed": True, "verified_allowed": False, "patterns_allowed": ["actions/*"]}
    api.add(responses.GET, url, json=body, match=no_params())
    api.add(responses.GET, url, status=409, json={"message": "Conflict"})
    api.add(responses.GET, url, status=404, json=NOT_FOUND)
    api.add(responses.GET, url, json=body)
    assert oracle.org_selected_actions() == body
    assert oracle.org_selected_actions() is None and oracle.unavailable == {}
    assert oracle.org_selected_actions() is None
    assert oracle.unavailable == {("org_selected_actions", FAKE_ORG): 404}
    assert oracle.org_selected_actions() == body
    assert oracle.unavailable == {}  # a later answer clears the record


def test_feature_lookups_raise_on_other_errors(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Statuses that are neither 'unavailable' nor 'absent' raise GitHubError."""
    api.add(responses.GET, f"{ORG}/actions/permissions/fork-pr-contributor-approval", status=500, json={})
    with pytest.raises(GitHubError) as info:
        oracle.org_fork_pr_approval()
    assert info.value.status == 500


def test_org_actions_selected_repositories(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Names of the ``repositories`` of the listing; 409 (enabled_repositories not 'selected') -> []."""
    url = f"{ORG}/actions/permissions/repositories"
    api.add(
        responses.GET,
        url,
        json={"total_count": 2, "repositories": [{"name": "a"}, {"name": "e2e-x"}]},
        match=per_page(),
    )
    api.add(responses.GET, url, status=409, json={"message": "Conflict"})
    api.add(responses.GET, url, status=403, json={"message": "Forbidden"})
    assert oracle.org_actions_selected_repositories() == ["a", "e2e-x"]
    assert oracle.org_actions_selected_repositories() == []
    assert oracle.org_actions_selected_repositories() == []
    assert oracle.unavailable == {("org_actions_selected_repositories", FAKE_ORG): 403}


def test_org_fork_pr_settings(api: responses.RequestsMock, oracle: Oracle) -> None:
    """fork-pr-contributor-approval and fork-pr-workflows-private-repos (404 unavailable on the plan)."""
    api.add(
        responses.GET,
        f"{ORG}/actions/permissions/fork-pr-contributor-approval",
        json={"approval_policy": "first_time_contributors"},
    )
    api.add(responses.GET, f"{ORG}/actions/permissions/fork-pr-workflows-private-repos", status=404, json=NOT_FOUND)
    assert oracle.org_fork_pr_approval() == {"approval_policy": "first_time_contributors"}
    assert oracle.org_fork_pr_workflows_private_repos() is None
    assert oracle.unavailable == {("org_fork_pr_workflows_private_repos", FAKE_ORG): 404}


def test_org_cache_storage_limit_on_both_paths(api: responses.RequestsMock, oracle: Oracle) -> None:
    """The documented /organizations/{org} path and otterdog's /orgs/{org} path (KB-006); 402 is unavailable too."""
    api.add(responses.GET, f"{ORGANIZATIONS}/actions/cache/storage-limit", json={"max_cache_size_gb": 10})
    api.add(responses.GET, f"{ORG}/actions/cache/storage-limit", status=404, json=NOT_FOUND)
    api.add(responses.GET, f"{REPO}/actions/cache/storage-limit", status=402, json={"message": "Payment required"})
    assert oracle.org_cache_storage_limit() == {"max_cache_size_gb": 10}
    assert oracle.org_cache_storage_limit_orgs_path() is None
    assert oracle.repo_cache_storage_limit("r") is None
    assert oracle.unavailable == {
        ("org_cache_storage_limit_orgs_path", FAKE_ORG): 404,
        ("repo_cache_storage_limit", "r"): 402,
    }
    assert api.calls[0].request.url == f"{ORGANIZATIONS}/actions/cache/storage-limit"


# --- repository Actions settings ------------------------------------------------------------------------------------
def test_repo_actions_feature_lookups(api: responses.RequestsMock, oracle: Oracle) -> None:
    """selected-actions (409 absent), fork-pr approval, fork-pr workflows of private repos, cache storage limit."""
    api.add(responses.GET, f"{REPO}/actions/permissions/selected-actions", status=409, json={"message": "Conflict"})
    api.add(
        responses.GET,
        f"{REPO}/actions/permissions/fork-pr-contributor-approval",
        json={"approval_policy": "all_external_contributors"},
    )
    api.add(
        responses.GET,
        f"{REPO}/actions/permissions/fork-pr-workflows-private-repos",
        status=403,
        json={"message": "Forbidden"},
    )
    api.add(responses.GET, f"{REPO}/actions/cache/storage-limit", json={"max_cache_size_gb": 5})
    assert oracle.repo_selected_actions("r") is None
    assert oracle.repo_fork_pr_approval("r") == {"approval_policy": "all_external_contributors"}
    assert oracle.repo_fork_pr_workflows_private_repos("r") is None
    assert oracle.repo_cache_storage_limit("r") == {"max_cache_size_gb": 5}
    assert oracle.unavailable == {("repo_fork_pr_workflows_private_repos", "r"): 403}


# --- repository security --------------------------------------------------------------------------------------------
def test_vulnerability_alerts_204_404_semantics(api: responses.RequestsMock, oracle: Oracle) -> None:
    """204 -> enabled; 404 on an existing repository -> disabled; 404 on a missing repository -> None."""
    url = f"{REPO}/vulnerability-alerts"
    api.add(responses.GET, url, status=204)
    api.add(responses.GET, url, status=404, json=NOT_FOUND)
    api.add(responses.GET, url, status=404, json=NOT_FOUND)
    api.add(responses.GET, REPO, json={"name": "r"})
    api.add(responses.GET, REPO, status=404, json=NOT_FOUND)
    assert oracle.repo_vulnerability_alerts("r") == {"enabled": True}
    assert oracle.repo_vulnerability_alerts("r") == {"enabled": False}
    assert oracle.repo_vulnerability_alerts("r") is None


def test_automated_security_fixes(api: responses.RequestsMock, oracle: Oracle) -> None:
    """200 -> {enabled, paused}; 404 (not enabled) on an existing repository -> {enabled: False}."""
    url = f"{REPO}/automated-security-fixes"
    api.add(responses.GET, url, json={"enabled": True, "paused": False})
    api.add(responses.GET, url, status=404, json=NOT_FOUND)
    api.add(responses.GET, REPO, json={"name": "r"})
    assert oracle.repo_automated_security_fixes("r") == {"enabled": True, "paused": False}
    assert oracle.repo_automated_security_fixes("r") == {"enabled": False}


def test_private_vulnerability_reporting(api: responses.RequestsMock, oracle: Oracle) -> None:
    """200 -> {enabled}; 422 -> None recorded unavailable; 404 (no repository) -> None without a record."""
    url = f"{REPO}/private-vulnerability-reporting"
    api.add(responses.GET, url, json={"enabled": True})
    api.add(responses.GET, url, status=422, json={"message": "Bad Request"})
    api.add(responses.GET, url, status=404, json=NOT_FOUND)
    assert oracle.repo_private_vulnerability_reporting("r") == {"enabled": True}
    assert oracle.repo_private_vulnerability_reporting("r") is None
    assert oracle.unavailable == {("repo_private_vulnerability_reporting", "r"): 422}
    assert oracle.repo_private_vulnerability_reporting("r") is None
    assert oracle.unavailable == {}


def test_code_scanning_default_setup(api: responses.RequestsMock, oracle: Oracle) -> None:
    """The default setup object; 403 (GitHub Advanced Security not enabled) is unavailable; 503 raises."""
    url = f"{REPO}/code-scanning/default-setup"
    setup = {"state": "configured", "languages": ["python"], "query_suite": "extended"}
    api.add(responses.GET, url, json=setup)
    api.add(responses.GET, url, status=403, json={"message": "Advanced Security must be enabled"})
    api.add(responses.GET, url, status=503, json={"message": "unavailable"})
    assert oracle.repo_code_scanning_default_setup("r") == setup
    assert oracle.repo_code_scanning_default_setup("r") is None
    assert oracle.unavailable == {("repo_code_scanning_default_setup", "r"): 403}
    with pytest.raises(GitHubError):
        oracle.repo_code_scanning_default_setup("r")


def test_security_and_analysis_block(api: responses.RequestsMock, oracle: Oracle) -> None:
    """security_and_analysis of the repository; None when the block or the repository is missing."""
    block = {"secret_scanning": {"status": "enabled"}, "dependabot_security_updates": {"status": "disabled"}}
    api.add(responses.GET, REPO, json={"name": "r", "security_and_analysis": block})
    api.add(responses.GET, REPO, json={"name": "r"})
    api.add(responses.GET, REPO, status=404, json=NOT_FOUND)
    assert oracle.repo_security_and_analysis("r") == block
    assert oracle.repo_security_and_analysis("r") is None
    assert oracle.repo_security_and_analysis("r") is None


def test_security_advisories(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Repository and organization advisory listings (per_page 100) and one advisory by GHSA id."""
    advisory = {"ghsa_id": "GHSA-abcd-efgh-ijkl", "state": "draft", "summary": "e2e-t3c7z8a5-x"}
    api.add(responses.GET, f"{REPO}/security-advisories", json=[advisory], match=per_page())
    api.add(responses.GET, f"{ORG}/security-advisories", json=[advisory], match=per_page())
    api.add(responses.GET, f"{REPO}/security-advisories/GHSA-abcd-efgh-ijkl", json=advisory)
    api.add(responses.GET, f"{REPO}/security-advisories/GHSA-0000-0000-0000", status=404, json=NOT_FOUND)
    assert oracle.repo_security_advisories("r") == [advisory]
    assert oracle.org_security_advisories() == [advisory]
    assert oracle.repo_security_advisory("r", "GHSA-abcd-efgh-ijkl") == advisory
    assert oracle.repo_security_advisory("r", "GHSA-0000-0000-0000") is None


# --- organization roles, security managers, code security ------------------------------------------------------
def test_security_managers_through_the_organization_role(api: responses.RequestsMock, oracle: Oracle) -> None:
    """The security_manager role is found by name, its teams are listed (slugs); org-roles takes no per_page."""
    roles = {"total_count": 2, "roles": [{"id": 1, "name": "all_repo_read"}, {"id": 7, "name": SECURITY_MANAGER_ROLE}]}
    api.add(responses.GET, f"{ORG}/organization-roles", json=roles, match=no_params())
    api.add(
        responses.GET,
        f"{ORG}/organization-roles/7/teams",
        json=[{"slug": "e2e-t3c7z8a5-sec", "assignment": "direct"}, {"slug": "security"}],
        match=per_page(),
    )
    assert oracle.security_managers() == ["e2e-t3c7z8a5-sec", "security"]
    assert oracle.unavailable == {}


def test_org_role_teams_unavailable_cases(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Missing role -> [] recorded 404; roles feature disabled (422) -> [] recorded 422; other errors raise."""
    api.add(responses.GET, f"{ORG}/organization-roles", json={"total_count": 1, "roles": [{"id": 3, "name": "x"}]})
    api.add(responses.GET, f"{ORG}/organization-roles/3/teams", status=422, json={"message": "not enabled"})
    api.add(responses.GET, f"{ORG}/organization-roles/3/teams", status=500, json={"message": "boom"})
    assert oracle.security_managers() == []
    assert oracle.unavailable == {("org_role_teams", SECURITY_MANAGER_ROLE): 404}
    assert oracle.org_role_teams("x") == []
    assert oracle.unavailable[("org_role_teams", "x")] == 422
    with pytest.raises(GitHubError):
        oracle.org_role_teams("x")


def test_code_security_configurations_and_defaults(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Configurations (paginated, found by name) and the defaults listing (one response, no per_page)."""
    configurations = [{"id": 17, "name": "GitHub recommended", "target_type": "global"}, {"id": 18, "name": "e2e-c"}]
    api.add(responses.GET, f"{ORG}/code-security/configurations", json=configurations, match=per_page())
    defaults = [{"default_for_new_repos": "public", "configuration": {"id": 18, "name": "e2e-c"}}]
    api.add(responses.GET, f"{ORG}/code-security/configurations/defaults", json=defaults, match=no_params())
    api.add(responses.GET, f"{ORG}/code-security/configurations/defaults", status=403, json={"message": "Forbidden"})
    assert oracle.code_security_configuration("e2e-c") == {"id": 18, "name": "e2e-c"}
    assert oracle.code_security_configuration("missing") is None
    assert oracle.code_security_default_configurations() == defaults
    assert oracle.code_security_default_configurations() == []
    assert oracle.unavailable == {("code_security_default_configurations", FAKE_ORG): 403}


def test_org_roles_is_one_response(api: responses.RequestsMock, oracle: Oracle) -> None:
    """GET /orgs/{org}/organization-roles is not paginated: no per_page, ``roles`` items, 404 recorded."""
    api.add(responses.GET, f"{ORG}/organization-roles", status=404, json=NOT_FOUND)
    assert oracle.org_roles() == []
    assert oracle.unavailable == {("org_roles", FAKE_ORG): 404}
    assert api.calls[0].request.url == f"{ORG}/organization-roles"


# --- members, teams, invitations ----------------------------------------------------------------------------------
def test_members_with_role_and_2fa(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Two listings role=admin and role=member; filter=2fa_disabled for the 2FA list."""
    api.add(responses.GET, f"{ORG}/members", json=[{"login": "owner"}], match=per_page(role="admin"))
    api.add(responses.GET, f"{ORG}/members", json=[{"login": "dev"}], match=per_page(role="member"))
    api.add(responses.GET, f"{ORG}/members", json=[{"login": "dev"}], match=per_page(filter="2fa_disabled"))
    assert oracle.members_with_role() == [{"login": "owner", "role": "admin"}, {"login": "dev", "role": "member"}]
    assert oracle.members_2fa_disabled() == ["dev"]


def test_invitations_and_team_membership(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Pending org and team invitations; team membership (None on 404)."""
    invitation = {"id": 1, "login": "newbie", "role": "direct_member"}
    api.add(responses.GET, f"{ORG}/invitations", json=[invitation], match=per_page())
    api.add(responses.GET, f"{ORG}/teams/t/invitations", json=[invitation], match=per_page())
    api.add(responses.GET, f"{ORG}/teams/t/memberships/dev", json={"role": "maintainer", "state": "active"})
    api.add(responses.GET, f"{ORG}/teams/t/memberships/gone", status=404, json=NOT_FOUND)
    assert oracle.org_invitations() == [invitation]
    assert oracle.team_invitations("t") == [invitation]
    assert oracle.team_membership("t", "dev") == {"role": "maintainer", "state": "active"}
    assert oracle.team_membership("t", "gone") is None


# --- commit statuses and languages ------------------------------------------------------------------------------------
def test_commit_statuses_list_every_status_newest_first(api: responses.RequestsMock, oracle: Oracle) -> None:
    """GET .../commits/{ref}/statuses over Link pages (the ref is URL-encoded); 404 -> [] recorded unavailable."""
    url = f"{REPO}/commits/e2e%2Fbranch/statuses"
    newest = {"context": "e2e/validate", "state": "success", "description": "otterdog validation succeeded"}
    pending = {"context": "e2e/validate", "state": "pending", "description": "validating configuration change"}
    api.add(
        responses.GET,
        url,
        json=[newest],
        headers={"Link": f'<{url}?per_page=100&page=2>; rel="next"'},
        match=per_page(),
    )
    api.add(responses.GET, url, json=[pending], match=per_page(page="2"))
    assert oracle.commit_statuses("r", "e2e/branch") == [newest, pending]
    api.add(responses.GET, f"{REPO}/commits/{'0' * 40}/statuses", status=404, json=NOT_FOUND)
    assert oracle.commit_statuses("r", "0" * 40) == []
    assert oracle.unavailable == {("commit_statuses", f"r/{'0' * 40}"): 404}


def test_repo_languages(api: responses.RequestsMock, oracle: Oracle) -> None:
    """GET .../languages: bytes per language, {} before any detection, None for an absent repository."""
    api.add(responses.GET, f"{REPO}/languages", json={"Python": 1234, "Shell": 56}, match=no_params())
    api.add(responses.GET, f"{REPO}/languages", json={})
    api.add(responses.GET, f"{GITHUB_API}/repos/{FAKE_ORG}/gone/languages", status=404, json=NOT_FOUND)
    assert oracle.repo_languages("r") == {"Python": 1234, "Shell": 56}
    assert oracle.repo_languages("r") == {}
    assert oracle.repo_languages("gone") is None


# --- branches and access ---------------------------------------------------------------------------------------------
def test_repo_branches_follow_pagination(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Branch names over Link pages; 404 -> [] recorded unavailable."""
    url = f"{REPO}/branches"
    api.add(
        responses.GET,
        url,
        json=[{"name": "main", "protected": True}],
        headers={"Link": f'<{url}?per_page=100&page=2>; rel="next"'},
        match=per_page(),
    )
    api.add(responses.GET, url, json=[{"name": "master", "protected": False}], match=per_page(page="2"))
    assert oracle.repo_branches("r") == ["main", "master"]
    api.add(responses.GET, f"{GITHUB_API}/repos/{FAKE_ORG}/gone/branches", status=404, json=NOT_FOUND)
    assert oracle.repo_branches("gone") == []
    assert oracle.unavailable == {("repo_branches", "gone"): 404}


def test_repo_branch_encoding_and_renames(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Branch names are URL-encoded; a renamed branch redirects to another name (None); 404 -> None."""
    api.add(responses.GET, f"{REPO}/branches/release%2F1.x", json={"name": "release/1.x", "protected": False})
    api.add(
        responses.GET,
        f"{REPO}/branches/main",
        status=301,
        headers={"Location": f"{REPO}/branches/master"},
    )
    api.add(responses.GET, f"{REPO}/branches/master", json={"name": "master", "protected": False})
    api.add(responses.GET, f"{REPO}/branches/none", status=404, json=NOT_FOUND)
    assert oracle.repo_branch("r", "release/1.x") == {"name": "release/1.x", "protected": False}
    assert oracle.repo_branch("r", "main") is None
    assert oracle.repo_branch("r", "master") == {"name": "master", "protected": False}
    assert oracle.repo_branch("r", "none") is None


def test_repo_teams_collaborators_invitations(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Teams, direct collaborators (affiliation=direct), one collaborator permission, invitations."""
    api.add(responses.GET, f"{REPO}/teams", json=[{"slug": "t", "permission": "push"}], match=per_page())
    collaborator = {"login": "dev", "role_name": "write", "permissions": {"push": True}}
    api.add(responses.GET, f"{REPO}/collaborators", json=[collaborator], match=per_page(affiliation="direct"))
    api.add(
        responses.GET,
        f"{REPO}/collaborators/dev/permission",
        json={"permission": "write", "role_name": "maintain", "user": {"login": "dev"}},
    )
    api.add(responses.GET, f"{REPO}/collaborators/x/permission", status=404, json=NOT_FOUND)
    api.add(responses.GET, f"{REPO}/invitations", json=[{"id": 4, "invitee": {"login": "out"}}], match=per_page())
    assert oracle.repo_teams("r") == [{"slug": "t", "permission": "push"}]
    assert oracle.repo_collaborators("r") == [collaborator]
    assert oracle.repo_collaborator_permission("r", "dev")["role_name"] == "maintain"  # type: ignore[index]
    assert oracle.repo_collaborator_permission("r", "x") is None
    assert oracle.repo_invitations("r") == [{"id": 4, "invitee": {"login": "out"}}]


# --- workflows -------------------------------------------------------------------------------------------------------
def test_workflow_runs_listings(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Runs of a workflow file (``workflow_runs`` items), of the repository, a run, its latest jobs, the workflow."""
    run = {"id": 9, "status": "queued", "event": "workflow_dispatch"}
    api.add(
        responses.GET,
        f"{REPO}/actions/workflows/e2e.yml/runs",
        json={"total_count": 1, "workflow_runs": [run]},
        match=per_page(),
    )
    api.add(responses.GET, f"{REPO}/actions/runs", json={"total_count": 1, "workflow_runs": [run]}, match=per_page())
    api.add(responses.GET, f"{REPO}/actions/runs/9", json=run)
    api.add(
        responses.GET,
        f"{REPO}/actions/runs/9/jobs",
        json={"total_count": 1, "jobs": [{"id": 1, "labels": ["macos-latest-large"]}]},
        match=per_page(filter="latest"),
    )
    api.add(responses.GET, f"{REPO}/actions/workflows/e2e.yml", json={"id": 3, "state": "active"})
    api.add(responses.GET, f"{REPO}/actions/workflows/none.yml", status=404, json=NOT_FOUND)
    assert oracle.workflow_runs("r", "e2e.yml") == [run]
    assert oracle.repo_workflow_runs("r") == [run]
    assert oracle.workflow_run("r", 9) == run
    assert oracle.workflow_run_jobs("r", 9) == [{"id": 1, "labels": ["macos-latest-large"]}]
    assert oracle.workflow("r", "e2e.yml") == {"id": 3, "state": "active"}
    assert oracle.workflow("r", "none.yml") is None


def test_find_workflow_runs_sends_only_given_filters(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Server-side filters are query parameters; None filters are not sent; 404 -> [] recorded unavailable."""
    filters = {"event": "workflow_dispatch", "branch": "main", "status": "queued", "created": ">=2026-10-03"}
    api.add(
        responses.GET,
        f"{REPO}/actions/workflows/e2e.yml/runs",
        json={"total_count": 0, "workflow_runs": []},
        match=per_page(**filters),
    )
    api.add(
        responses.GET,
        f"{REPO}/actions/runs",
        json={"total_count": 1, "workflow_runs": [{"id": 1}]},
        match=per_page(head_sha="a" * 40),
    )
    assert oracle.find_workflow_runs("r", workflow="e2e.yml", **filters) == []
    assert oracle.find_workflow_runs("r", head_sha="a" * 40) == [{"id": 1}]
    api.add(responses.GET, f"{REPO}/actions/workflows/x.yml/runs", status=404, json=NOT_FOUND)
    assert oracle.find_workflow_runs("r", workflow="x.yml") == []
    assert oracle.unavailable == {("find_workflow_runs", "r/x.yml"): 404}


# --- webhook delivery details ---------------------------------------------------------------------------------------
def test_latest_delivery_details_by_url(api: responses.RequestsMock, oracle: Oracle) -> None:
    """The newest delivery of the event is read in full (request headers); None without hook or delivery."""
    url = "https://otterdog-e2e.invalid/t3c7z8a5/h"
    api.add(responses.GET, f"{ORG}/hooks", json=[{"id": 2, "config": {"url": url}}])
    api.add(
        responses.GET,
        f"{ORG}/hooks/2/deliveries",
        json=[{"id": 31, "event": "repository"}, {"id": 30, "event": "ping"}, {"id": 29, "event": "ping"}],
    )
    detail = {"id": 30, "event": "ping", "request": {"headers": {"X-Hub-Signature-256": "sha256=abc"}}}
    api.add(responses.GET, f"{ORG}/hooks/2/deliveries/30", json=detail)
    api.add(responses.GET, f"{REPO}/hooks", json=[{"id": 5, "config": {"url": url}}])
    api.add(responses.GET, f"{REPO}/hooks/5/deliveries", json=[{"id": 40, "event": "push"}])
    api.add(responses.GET, f"{REPO}/hooks/5/deliveries/40", json={"id": 40, "event": "push", "request": {}})
    assert oracle.org_hook_latest_delivery_by_url(url, "ping") == detail
    assert oracle.org_hook_latest_delivery_by_url(url, "push") is None
    assert oracle.org_hook_latest_delivery_by_url("https://none", "ping") is None
    assert oracle.repo_hook_latest_delivery_by_url("r", url, "push") == {"id": 40, "event": "push", "request": {}}
    assert oracle.repo_hook_latest_delivery_by_url("r", "https://none", "push") is None
    api.add(responses.GET, f"{REPO}/hooks/5/deliveries/41", status=404, json=NOT_FOUND)
    assert oracle.repo_hook_delivery("r", 5, 41) is None


# --- branch protection rules ------------------------------------------------------------------------------------------
def actor(typename: str, **fields: str) -> dict[str, Any]:
    """An allowance node with its actor."""
    return {"actor": {"__typename": typename, **fields}}


def test_bpr_detail_flattens_allowance_actors(api: responses.RequestsMock, oracle: Oracle) -> None:
    """branch_protection_rule uses the detailed query; the 4 allowance connections become otterdog actor names."""
    rule = {
        "id": "BPR_1",
        "pattern": "main",
        "restrictsReviewDismissals": True,
        "requiredStatusChecks": [{"context": "e2e-plain", "app": {"slug": "github-actions"}}],
        "bypassPullRequestAllowances": {
            "totalCount": 3,
            "nodes": [
                actor("Team", combinedSlug=f"{FAKE_ORG}/e2e-t3c7z8a5-maint"),
                actor("User", login="e2e-admin"),
                actor("App", slug="e2e-app"),
            ],
        },
        "bypassForcePushAllowances": {"totalCount": 1, "nodes": [{"actor": None}]},
        "pushAllowances": {"totalCount": 0, "nodes": []},
        "reviewDismissalAllowances": {"totalCount": 2, "nodes": [actor("User", login="e2e-admin")]},
    }
    connection = {
        "pageInfo": {"hasNextPage": False, "endCursor": None},
        "nodes": [rule, {"id": "BPR_2", "pattern": "x"}],
    }
    api.add(responses.POST, GRAPHQL, json={"data": {"repository": {"branchProtectionRules": connection}}})
    detail = oracle.branch_protection_rule("r", "main")
    assert detail is not None
    assert detail["bypassPullRequestAllowances"] == [f"@{FAKE_ORG}/e2e-t3c7z8a5-maint", "@e2e-admin", "e2e-app"]
    assert detail["bypassForcePushAllowances"] == [] and detail["pushAllowances"] == []
    assert detail["reviewDismissalAllowances"] == ["@e2e-admin"]
    assert detail["requiredStatusChecks"] == [{"context": "e2e-plain", "app": {"slug": "github-actions"}}]
    query = json.loads(api.calls[0].request.body or "{}")["query"]
    assert query == BPR_DETAIL_QUERY
    assert all(name in query for name in (*BPR_ALLOWANCES, *BPR_FIELDS, "requiredStatusChecks"))


def test_bpr_listing_stays_cheap_and_has_the_new_fields(api: responses.RequestsMock, oracle: Oracle) -> None:
    """branch_protection_rules (janitor) sends the summary query: new scalar fields, status checks, no allowances."""
    connection = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [{"id": "BPR_1", "pattern": "main"}]}
    api.add(responses.POST, GRAPHQL, json={"data": {"repository": {"branchProtectionRules": connection}}})
    assert oracle.branch_protection_rules("r") == [{"id": "BPR_1", "pattern": "main"}]
    query = json.loads(api.calls[0].request.body or "{}")["query"]
    assert query == BPR_QUERY
    assert "lockAllowsFetchAndMerge" in query and "requiredDeploymentEnvironments" in query
    assert not any(name in query for name in BPR_ALLOWANCES)


def test_bpr_detail_not_found_and_absent_pattern(api: responses.RequestsMock, oracle: Oracle) -> None:
    """A missing repository is unavailable (kind branch_protection_rules); a missing pattern is None."""
    api.add(
        responses.POST,
        GRAPHQL,
        json={"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve"}]},
    )
    assert oracle.branch_protection_rule("gone", "main") is None
    assert oracle.unavailable == {("branch_protection_rules", "gone"): 404}
    connection = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [{"id": "BPR_1", "pattern": "x"}]}
    api.add(responses.POST, GRAPHQL, json={"data": {"repository": {"branchProtectionRules": connection}}})
    assert oracle.branch_protection_rule("r", "main") is None


def test_bpr_detail_warns_about_truncated_allowances(
    api: responses.RequestsMock, oracle: Oracle, caplog: pytest.LogCaptureFixture
) -> None:
    """More actors than one page: the first ones are returned and a warning names the connection."""
    rule = {
        "id": "BPR_1",
        "pattern": "main",
        "pushAllowances": {"totalCount": 101, "nodes": [actor("User", login="a")]},
    }
    connection = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": [rule]}
    api.add(responses.POST, GRAPHQL, json={"data": {"repository": {"branchProtectionRules": connection}}})
    detail = oracle.branch_protection_rule("r", "main")
    assert detail is not None and detail["pushAllowances"] == ["@a"]
    assert "pushAllowances: 101 actors" in caplog.text


# --- dispatch ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("kind", "params"),
    [
        ("org_selected_actions", {}),
        ("security_managers", {}),
        ("repo_vulnerability_alerts", {"repo": "r"}),
        ("repo_default_branch", {"repo": "r"}),
        ("org_webhook_delivery", {"url": "https://otterdog-e2e.invalid/x", "event": "ping"}),
    ],
)
def test_new_kinds_dispatch_through_lookup(
    api: responses.RequestsMock, oracle: Oracle, kind: str, params: dict[str, str]
) -> None:
    """Oracle.lookup reaches the new methods with the check parameters."""
    api.add(responses.GET, f"{ORG}/actions/permissions/selected-actions", json={"github_owned_allowed": True})
    api.add(responses.GET, f"{ORG}/organization-roles", json={"roles": []})
    api.add(responses.GET, f"{REPO}/vulnerability-alerts", status=204)
    api.add(responses.GET, REPO, json={"name": "r", "default_branch": "main"})
    api.add(responses.GET, f"{ORG}/hooks", json=[])
    oracle.lookup(kind, **params)
