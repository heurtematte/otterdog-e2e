"""Oracle: error semantics, endpoints, media types, GraphQL lookups and normalize() (SPEC 9.3, 4)."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from typing import Any

import pytest
import responses
from responses import matchers

from otterdog_e2e.github.http import GITHUB_API, GitHubError, GitHubHttp
from otterdog_e2e.github.oracle import BPR_FIELDS, Oracle, normalize
from otterdog_e2e.testing.fakes import FAKE_ORG

ORG = f"{GITHUB_API}/orgs/{FAKE_ORG}"
REPO = f"{GITHUB_API}/repos/{FAKE_ORG}/r"
GRAPHQL = f"{GITHUB_API}/graphql"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked api.github.com."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def oracle() -> Oracle:
    """Oracle over a read-only client (no sleeping)."""
    http = GitHubHttp("ghp_" + "OracleTestToken0123456789abcdefghijkl", read_only=True, sleep=lambda _: None)
    return Oracle(http, FAKE_ORG)


def must(value: Any) -> Any:
    """``value`` asserted non-None (narrows Optional lookups)."""
    assert value is not None
    return value


def sent(call: Any) -> Any:
    """Decoded JSON body of a recorded request."""
    return json.loads(call.request.body or "{}")


def not_found(api: responses.RequestsMock, url: str) -> None:
    """Register a 404 for ``url``."""
    api.add(responses.GET, url, status=404, json={"message": "Not Found"})


# --- error semantics -----------------------------------------------------------------------------------------------
def test_single_lookups_return_none_on_404(api: responses.RequestsMock, oracle: Oracle) -> None:
    """repo, team, membership, secrets, variables, environments, pages, pulls -> None on 404."""
    for url in (
        f"{REPO}",
        f"{ORG}/teams/t",
        f"{ORG}/memberships/u",
        f"{ORG}/actions/secrets/S",
        f"{ORG}/actions/variables/V",
        f"{REPO}/actions/secrets/S",
        f"{REPO}/actions/variables/V",
        f"{REPO}/environments/e",
        f"{REPO}/environments/e/secrets/S",
        f"{REPO}/environments/e/variables/V",
        f"{REPO}/pages",
        f"{REPO}/pulls/1",
        f"{ORG}/actions/permissions",
        f"{REPO}/actions/permissions/workflow",
    ):
        not_found(api, url)
    assert oracle.repo("r") is None and oracle.team("t") is None and oracle.membership("u") is None
    assert oracle.org_secret("S") is None and oracle.org_variable("V") is None
    assert oracle.repo_secret("r", "S") is None and oracle.repo_variable("r", "V") is None
    assert oracle.environment("r", "e") is None
    assert oracle.environment_secret("r", "e", "S") is None and oracle.environment_variable("r", "e", "V") is None
    assert oracle.pages("r") is None and oracle.pull("r", 1) is None
    assert oracle.org_actions_permissions() is None and oracle.repo_workflow_permissions("r") is None
    assert oracle.default_branch("r") is None


def test_list_lookups_return_empty_and_record_unavailable(api: responses.RequestsMock, oracle: Oracle) -> None:
    """403/404 listings -> [] with unavailable[(kind, scope)]; a later success clears the record."""
    api.add(responses.GET, f"{ORG}/rulesets", status=403, json={"message": "Upgrade to GitHub Team"})
    api.add(responses.GET, f"{ORG}/rulesets", json=[{"id": 1, "name": "rs"}])
    not_found(api, f"{REPO}/rulesets")
    not_found(api, f"{REPO}/environments/prod/deployment-branch-policies")
    api.add(responses.GET, f"{ORG}/properties/schema", status=403, json={"message": "Forbidden"})
    not_found(api, f"{REPO}/properties/values")
    assert oracle.org_rulesets() == []
    assert oracle.repo_rulesets("r") == []
    assert oracle.environment_branch_policies("r", "prod") == []
    assert oracle.custom_properties() == [] and oracle.custom_property("p") is None
    assert oracle.repo_custom_property_values("r") == {}
    assert oracle.unavailable == {
        ("org_rulesets", FAKE_ORG): 403,
        ("repo_rulesets", "r"): 404,
        ("environment_branch_policies", "r/prod"): 404,
        ("custom_properties", FAKE_ORG): 403,
        ("repo_custom_property_values", "r"): 404,
    }
    assert oracle.org_rulesets() == [{"id": 1, "name": "rs"}]
    assert ("org_rulesets", FAKE_ORG) not in oracle.unavailable


def test_other_errors_raise(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Errors other than 403/404 (lists) or 404 (single objects) raise GitHubError."""
    api.add(responses.GET, f"{ORG}/repos", status=500, json={"message": "boom"})
    api.add(responses.GET, f"{ORG}/teams/t", status=403, json={"message": "Forbidden"})
    with pytest.raises(GitHubError) as info:
        oracle.repos()
    assert info.value.status == 500
    with pytest.raises(GitHubError):
        oracle.team("t")


# --- endpoints, params and item keys -------------------------------------------------------------------------------
def test_variables_use_per_page_30(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Every variables listing caps per_page at 30 and unwraps ``variables``."""
    page = {"total_count": 1, "variables": [{"name": "V", "value": "1"}]}
    per_page_30 = [matchers.query_param_matcher({"per_page": "30"})]
    api.add(responses.GET, f"{ORG}/actions/variables", json=page, match=per_page_30)
    api.add(responses.GET, f"{REPO}/actions/variables", json=page, match=per_page_30)
    api.add(responses.GET, f"{REPO}/environments/e/variables", json=page, match=per_page_30)
    assert oracle.org_variables() == page["variables"]
    assert oracle.repo_variables("r") == page["variables"]
    assert oracle.environment_variables("r", "e") == page["variables"]


def test_wrapped_listings_and_repos_type_all(api: responses.RequestsMock, oracle: Oracle) -> None:
    """secrets/environments/roles/topics item keys, members and team member logins, repos?type=all."""
    api.add(responses.GET, f"{ORG}/actions/secrets", json={"total_count": 1, "secrets": [{"name": "S"}]})
    api.add(responses.GET, f"{REPO}/environments", json={"total_count": 1, "environments": [{"name": "e"}]})
    api.add(responses.GET, f"{ORG}/organization-roles", json={"total_count": 1, "roles": [{"id": 8, "name": "r"}]})
    api.add(responses.GET, f"{REPO}/topics", json={"names": ["a", "b"]})
    api.add(responses.GET, f"{ORG}/members", json=[{"login": "m1"}, {"login": "m2"}])
    api.add(responses.GET, f"{ORG}/teams/t/members", json=[{"login": "m1"}])
    api.add(
        responses.GET,
        f"{ORG}/repos",
        json=[{"name": "r"}],
        match=[matchers.query_param_matcher({"type": "all", "per_page": "100"})],
    )
    assert oracle.org_secrets() == [{"name": "S"}]
    assert oracle.environments("r") == [{"name": "e"}]
    assert oracle.org_roles() == [{"id": 8, "name": "r"}]
    assert oracle.repo_topics("r") == ["a", "b"]
    assert oracle.members() == ["m1", "m2"] and oracle.team_members("t") == ["m1"]
    assert oracle.repos() == [{"name": "r"}]


def test_selected_repositories(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Selected repositories of org secrets/variables are names; 409 (visibility not selected) -> []."""
    body = {"total_count": 2, "repositories": [{"name": "a"}, {"name": "b"}]}
    api.add(responses.GET, f"{ORG}/actions/secrets/S/repositories", json=body)
    api.add(responses.GET, f"{ORG}/actions/variables/V/repositories", status=409)
    assert oracle.org_secret_repositories("S") == ["a", "b"]
    assert oracle.org_variable_repositories("V") == []


def test_team_repo_permission_media_type_and_mapping(api: responses.RequestsMock, oracle: Oracle) -> None:
    """vnd.github.v3.repository+json role_name, mapped to otterdog's vocabulary; 404 -> None."""
    url = f"{ORG}/teams/t/repos/{FAKE_ORG}/r"
    media = [matchers.header_matcher({"Accept": "application/vnd.github.v3.repository+json"})]
    api.add(responses.GET, url, json={"name": "r", "role_name": "write"}, match=media)
    api.add(responses.GET, url, json={"name": "r", "role_name": "read"}, match=media)
    api.add(responses.GET, url, json={"name": "r", "role_name": "e2e-custom"}, match=media)
    api.add(
        responses.GET,
        url,
        json={"name": "r", "permissions": {"pull": True, "triage": True, "push": False}},
        match=media,
    )
    api.add(responses.GET, url, status=404, match=media)
    assert [oracle.team_repo_permission("t", "r") for _ in range(5)] == ["push", "pull", "e2e-custom", "triage", None]


def test_org_and_repo_rulesets_by_name(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Rulesets are found by name in the listing, then read in full (repo rulesets without parents)."""
    api.add(responses.GET, f"{ORG}/rulesets", json=[{"id": 4, "name": "e2e-x"}])
    api.add(responses.GET, f"{ORG}/rulesets/4", json={"id": 4, "name": "e2e-x", "rules": [{"type": "creation"}]})
    no_parents = matchers.query_param_matcher({"includes_parents": "false", "per_page": "100"})
    api.add(responses.GET, f"{REPO}/rulesets", json=[{"id": 5, "name": "main"}], match=[no_parents])
    api.add(
        responses.GET,
        f"{REPO}/rulesets/5",
        json={"id": 5, "name": "main", "rules": []},
        match=[matchers.query_param_matcher({"includes_parents": "false"})],
    )
    assert must(oracle.org_ruleset("e2e-x"))["rules"] == [{"type": "creation"}]
    assert oracle.org_ruleset("other") is None
    assert must(oracle.repo_ruleset("r", "main"))["id"] == 5


def test_hooks_by_url_and_deliveries(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Hooks are matched on config.url; delivery logs follow the cursor links."""
    hook_url = "https://otterdog-e2e.invalid/t3c7z8a5/h"
    api.add(
        responses.GET,
        f"{ORG}/hooks",
        json=[{"id": 1, "config": {"url": "https://x"}}, {"id": 2, "config": {"url": hook_url}}],
    )
    api.add(responses.GET, f"{REPO}/hooks", json=[{"id": 3, "config": {"url": hook_url}}])
    deliveries = f"{REPO}/hooks/3/deliveries"
    api.add(
        responses.GET,
        deliveries,
        json=[{"id": 11}],
        headers={"Link": f'<{deliveries}?per_page=100&cursor=v1_5>; rel="next"'},
        match=[matchers.query_param_matcher({"per_page": "100"})],
    )
    api.add(
        responses.GET,
        deliveries,
        json=[{"id": 10}],
        match=[matchers.query_param_matcher({"per_page": "100", "cursor": "v1_5"})],
    )
    api.add(responses.GET, f"{ORG}/hooks/2/deliveries", json=[{"id": 9, "event": "ping"}])
    assert must(oracle.org_hook_by_url(hook_url))["id"] == 2
    assert oracle.org_hook_by_url("https://none") is None
    assert must(oracle.repo_hook_by_url("r", hook_url))["id"] == 3
    assert [d["id"] for d in oracle.repo_hook_deliveries("r", 3)] == [11, 10]
    assert oracle.org_hook_deliveries(2) == [{"id": 9, "event": "ping"}]
    # by URL (check kinds org_webhook_deliveries / repo_webhook_deliveries): [] while the hook does not exist
    assert oracle.org_hook_deliveries_by_url(hook_url) == [{"id": 9, "event": "ping"}]
    assert [d["id"] for d in oracle.repo_hook_deliveries_by_url("r", hook_url)] == [11, 10]
    assert oracle.org_hook_deliveries_by_url("https://none") == []
    assert oracle.repo_hook_deliveries_by_url("r", "https://none") == []


def test_org_role_by_name(api: responses.RequestsMock, oracle: Oracle) -> None:
    """org_role looks the role up by name in GET /orgs/{org}/organization-roles (``roles`` items)."""
    api.add(
        responses.GET,
        f"{ORG}/organization-roles",
        json={"total_count": 2, "roles": [{"id": 1, "name": "all_repo_read"}, {"id": 8, "name": "e2e-x-role"}]},
    )
    assert must(oracle.org_role("e2e-x-role"))["id"] == 8
    assert oracle.org_role("missing") is None


def test_environment_names_are_url_encoded(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Environment names must be URL encoded (slashes as %2F)."""
    api.add(responses.GET, f"{REPO}/environments/prod%2Feu", json={"name": "prod/eu"})
    api.add(
        responses.GET,
        f"{REPO}/environments/prod%2Feu/deployment-branch-policies",
        json={"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]},
    )
    assert oracle.environment("r", "prod/eu") == {"name": "prod/eu"}
    assert oracle.environment_branch_policies("r", "prod/eu") == [{"name": "main", "type": "branch"}]
    assert api.calls[0].request.url == f"{REPO}/environments/prod%2Feu"


def test_custom_properties_and_values(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Custom property definitions by property_name; repo values as a mapping."""
    api.add(
        responses.GET, f"{ORG}/properties/schema", json=[{"property_name": "e2e-t3c7z8a5-p", "value_type": "string"}]
    )
    api.add(
        responses.GET,
        f"{REPO}/properties/values",
        json=[{"property_name": "a", "value": "1"}, {"property_name": "b", "value": ["x"]}],
    )
    assert must(oracle.custom_property("e2e-t3c7z8a5-p"))["value_type"] == "string"
    assert oracle.repo_custom_property_values("r") == {"a": "1", "b": ["x"]}


# --- git, contents, statuses ---------------------------------------------------------------------------------------
def test_git_lookups(api: responses.RequestsMock, oracle: Oracle) -> None:
    """branch_sha via git/ref (singular; None on 404/409), git_commit, matching_refs filtered by prefix."""
    api.add(
        responses.GET,
        f"{REPO}/git/ref/heads/main",
        json={"ref": "refs/heads/main", "object": {"sha": "a" * 40, "type": "commit"}},
    )
    not_found(api, f"{REPO}/git/ref/heads/gone")
    api.add(
        responses.GET,
        f"{GITHUB_API}/repos/{FAKE_ORG}/empty/git/ref/heads/main",
        status=409,
        json={"message": "Git Repository is empty."},
    )
    api.add(
        responses.GET,
        f"{REPO}/git/commits/{'a' * 40}",
        json={"sha": "a" * 40, "message": "m", "tree": {"sha": "t" * 40}},
    )
    refs = [
        {"ref": "refs/tags/e2e-run/t3c7z8a5", "object": {"sha": "b" * 40}},
        {"ref": "refs/tags/e2e-runner", "object": {"sha": "c" * 40}},
    ]
    api.add(responses.GET, f"{REPO}/git/matching-refs/tags/e2e-run", json=refs)
    api.add(
        responses.GET,
        f"{GITHUB_API}/repos/{FAKE_ORG}/empty/git/matching-refs/heads/e2e",
        status=409,
        json={"message": "Git Repository is empty."},
    )
    assert oracle.branch_sha("r", "main") == "a" * 40
    assert oracle.branch_sha("r", "gone") is None and oracle.branch_sha("empty", "main") is None
    assert must(oracle.git_commit("r", "a" * 40))["tree"]["sha"] == "t" * 40
    assert oracle.matching_refs("r", "tags/e2e-run/") == [refs[0]]
    assert oracle.matching_refs("empty", "heads/e2e/") == []
    assert oracle.unavailable[("matching_refs", "empty/heads/e2e/")] == 409


def test_file_content(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Base64 file content is decoded; directories and 404 -> None; ref is passed through."""
    text = "local orgs = import 'vendor/x';\n"
    encoded = base64.encodebytes(text.encode()).decode()  # GitHub wraps base64 lines
    api.add(
        responses.GET,
        f"{REPO}/contents/otterdog/{FAKE_ORG}.jsonnet",
        json={"type": "file", "encoding": "base64", "content": encoded},
        match=[matchers.query_param_matcher({"ref": "e2e/t3c7z8a5/x"})],
    )
    api.add(responses.GET, f"{REPO}/contents/otterdog", json=[{"type": "file", "name": "a"}])
    not_found(api, f"{REPO}/contents/missing.txt")
    assert oracle.file_content("r", f"otterdog/{FAKE_ORG}.jsonnet", ref="e2e/t3c7z8a5/x") == text
    assert oracle.file_content("r", "otterdog") is None
    assert oracle.file_content("r", "missing.txt") is None


def test_combined_and_latest_status(api: responses.RequestsMock, oracle: Oracle) -> None:
    """Combined status per sha (latest per context); 404 -> empty pending."""
    sha = "d" * 40
    statuses = [
        {"context": "e2e/otterdog-validate", "state": "success"},
        {"context": "e2e/otterdog-sync", "state": "pending"},
    ]
    api.add(responses.GET, f"{REPO}/commits/{sha}/status", json={"state": "pending", "sha": sha, "statuses": statuses})
    not_found(api, f"{REPO}/commits/{'e' * 40}/status")
    assert oracle.combined_status("r", sha)["state"] == "pending"
    assert must(oracle.latest_status("r", sha, "e2e/otterdog-validate"))["state"] == "success"
    assert oracle.latest_status("r", sha, "other") is None
    assert oracle.combined_status("r", "e" * 40) == {
        "sha": "e" * 40,
        "state": "pending",
        "total_count": 0,
        "statuses": [],
    }


def test_pulls_and_issue_comments(api: responses.RequestsMock, oracle: Oracle) -> None:
    """pulls(state) and issue comments listings."""
    api.add(
        responses.GET,
        f"{REPO}/pulls",
        json=[{"number": 3}],
        match=[matchers.query_param_matcher({"state": "all", "per_page": "100"})],
    )
    api.add(responses.GET, f"{REPO}/issues/3/comments", json=[{"id": 1, "body": "b"}])
    assert oracle.pulls("r", "all") == [{"number": 3}]
    assert oracle.issue_comments("r", 3) == [{"id": 1, "body": "b"}]


# --- GraphQL ---------------------------------------------------------------------------------------------------------
def test_branch_protection_rules_graphql_pagination(api: responses.RequestsMock, oracle: Oracle) -> None:
    """BPRs come from GraphQL with the v1 fields, following pageInfo; pattern lookup works."""

    def page(nodes: list[dict], has_next: bool, cursor: str | None) -> dict:
        """One branchProtectionRules page."""
        info = {"hasNextPage": has_next, "endCursor": cursor}
        return {"data": {"repository": {"branchProtectionRules": {"pageInfo": info, "nodes": nodes}}}}

    api.add(responses.POST, GRAPHQL, json=page([{"id": "BPR_1", "pattern": "main"}], True, "c1"))
    api.add(responses.POST, GRAPHQL, json=page([{"id": "BPR_2", "pattern": "e2e-*"}], False, None))
    rules = oracle.branch_protection_rules("r")
    assert [rule["pattern"] for rule in rules] == ["main", "e2e-*"]
    first, second = (sent(call) for call in api.calls)
    assert first["variables"] == {"owner": FAKE_ORG, "name": "r", "after": None}
    assert second["variables"]["after"] == "c1"
    assert all(field in first["query"] for field in BPR_FIELDS)
    api.add(responses.POST, GRAPHQL, json=page([{"id": "BPR_2", "pattern": "e2e-*"}], False, None))
    assert must(oracle.branch_protection_rule("r", "e2e-*"))["id"] == "BPR_2"


def test_graphql_not_found_is_unavailable(api: responses.RequestsMock, oracle: Oracle) -> None:
    """NOT_FOUND/FORBIDDEN GraphQL errors -> [] recorded unavailable; other errors raise."""
    api.add(
        responses.POST,
        GRAPHQL,
        json={"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "Could not resolve"}]},
    )
    api.add(responses.POST, GRAPHQL, json={"errors": [{"type": "INTERNAL", "message": "boom"}]})
    assert oracle.branch_protection_rules("gone") == []
    assert oracle.unavailable[("branch_protection_rules", "gone")] == 404
    with pytest.raises(GitHubError):
        oracle.branch_protection_rules("r")


def test_pr_comments_shape(api: responses.RequestsMock, oracle: Oracle) -> None:
    """GraphQL comments: id, database_id, author without [bot], body, is_minimized, minimized_reason, created_at."""
    nodes = [
        {
            "id": "IC_1",
            "databaseId": 1,
            "author": {"login": "otterdog-e2e-app"},
            "body": "<!-- Otterdog Comment: help -->",
            "isMinimized": True,
            "minimizedReason": "outdated",
            "createdAt": "2030-01-01T00:00:00Z",
        },
        {
            "id": "IC_2",
            "databaseId": 2,
            "author": {"login": "someone[bot]"},
            "body": "x",
            "isMinimized": False,
            "minimizedReason": None,
            "createdAt": "2030-01-01T00:01:00Z",
        },
        {
            "id": "IC_3",
            "databaseId": 3,
            "author": None,
            "body": "ghost",
            "isMinimized": False,
            "minimizedReason": None,
            "createdAt": "2030-01-01T00:02:00Z",
        },
    ]
    connection = {"pageInfo": {"hasNextPage": False, "endCursor": None}, "nodes": nodes}
    api.add(responses.POST, GRAPHQL, json={"data": {"repository": {"pullRequest": {"comments": connection}}}})
    comments = oracle.pr_comments("r", 7)
    assert comments[0] == {
        "id": "IC_1",
        "database_id": 1,
        "author": "otterdog-e2e-app",
        "body": "<!-- Otterdog Comment: help -->",
        "is_minimized": True,
        "minimized_reason": "outdated",
        "created_at": "2030-01-01T00:00:00Z",
    }
    assert comments[1]["author"] == "someone" and comments[2]["author"] is None
    assert sent(api.calls[0])["variables"]["number"] == 7


# --- dispatch and normalize ----------------------------------------------------------------------------------------
def test_lookup_dispatches_check_kinds(api: responses.RequestsMock, oracle: Oracle) -> None:
    """CHECK_KINDS dispatch with named parameters; missing parameters and unknown kinds fail."""
    api.add(responses.GET, REPO, json={"name": "r", "default_branch": "main"})
    api.add(responses.GET, f"{REPO}/actions/secrets/S", json={"name": "S"})
    assert oracle.lookup("repo", name="r")["name"] == "r"
    assert oracle.lookup("repo_secret", repo="r", name="S") == {"name": "S"}
    with pytest.raises(TypeError):
        oracle.lookup("repo_secret", repo="r")
    with pytest.raises(KeyError):
        oracle.lookup("no-such-kind")


def test_org_and_plan(api: responses.RequestsMock, oracle: Oracle) -> None:
    """org() and plan_name() (owners see plan.name)."""
    api.add(responses.GET, ORG, json={"login": FAKE_ORG, "plan": {"name": "free"}})
    assert oracle.plan_name() == "free"


def test_normalize_drops_volatile_keys() -> None:
    """VOLATILE_KEYS and ``*_url`` keys are removed recursively; lists keep their order."""
    data = {
        "id": 1,
        "node_id": "x",
        "url": "u",
        "hooks_url": "h",
        "updated_at": "t",
        "items": [{"etag": "e", "v": 2}, 3],
    }
    assert normalize(data) == {"id": 1, "items": [{"v": 2}, 3]}
    assert normalize(("a", {"_links": {}})) == ["a", {}]


def test_deliveries_since_ignores_deliveries_logged_late() -> None:
    """BAT-10: only deliveries (of the event) delivered at or after GitHub's time of the ping (minus 2 s of rounding)
    count: a creation ping or an earlier ping that shows up in the log later is never taken for the new one."""
    from datetime import UTC, datetime

    from otterdog_e2e.github.oracle import deliveries_since

    pinged_at = datetime(2026, 10, 3, 10, 0, 0, tzinfo=UTC)
    deliveries = [
        {"id": 3, "event": "ping", "delivered_at": "2026-10-03T10:00:01Z"},  # the new ping
        {"id": 2, "event": "push", "delivered_at": "2026-10-03T10:00:02Z"},
        {"id": 4, "event": "ping", "delivered_at": "2026-10-03T09:59:59Z"},  # rounding: still this ping
        {"id": 1, "event": "ping", "delivered_at": "2026-10-03T09:57:30Z"},  # the creation ping, logged late
        {"id": 5, "event": "ping", "delivered_at": None},
    ]
    assert [d["id"] for d in deliveries_since(deliveries, pinged_at, event="ping")] == [3, 4]
    assert [d["id"] for d in deliveries_since(deliveries, pinged_at)] == [3, 2, 4]
