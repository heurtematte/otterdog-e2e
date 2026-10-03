"""WP-A: plan matrix, read-only capability probes, environment caps and overrides (SPEC 8)."""

from __future__ import annotations

import json
import logging
from typing import Any

import pytest
import responses

from otterdog_e2e.capabilities import (
    PLAN_MATRIX,
    PLANS,
    Cap,
    Capabilities,
    apply_overrides,
    environment_caps,
    from_plan,
    plans_at_least,
    probe_capabilities,
    probe_status,
)
from otterdog_e2e.github.http import GitHubHttp
from otterdog_e2e.settings import Identity
from otterdog_e2e.testing.fakes import FAKE_ORG, FakeGitHubHttp, make_verified_org

API = "https://api.github.com"
FIXTURE = "otterdog-e2e-fixture-a"
SCHEMA = f"/orgs/{FAKE_ORG}/properties/schema"
REPO_LIMIT = f"/repos/{FAKE_ORG}/{FIXTURE}/actions/cache/storage-limit"
ORG_LIMIT = f"/orgs/{FAKE_ORG}/actions/cache/storage-limit"
DOCUMENTED_ORG_LIMIT = f"/organizations/{FAKE_ORG}/actions/cache/storage-limit"  # recorded only (KB-006 evidence)
ROLES = f"/orgs/{FAKE_ORG}/custom-repository-roles"
ADMIN = Identity("admin", "e2e-admin-bot", "wpa-admin-token-01")
NO_OVERRIDES: dict[str, list[str]] = {"add": [], "remove": []}


def probes_http(statuses: dict[str, int]) -> FakeGitHubHttp:
    """Fake admin client answering each probe path with the given status (missing paths: 404)."""
    http = FakeGitHubHttp(identity="admin", scopes={"repo"}, strict=False)
    for path, status in statuses.items():
        http.add("GET", path, status=status, json={} if status == 200 else {"message": "Not Found"})
    return http


def probe(http: Any, *, plan: str = "free", **kw: Any) -> Capabilities:
    """probe_capabilities with defaults for the fake org."""
    options: dict[str, Any] = {
        "identities": {"admin": ADMIN, "oracle": Identity("oracle", None, ADMIN.token)},
        "app_ok": False,
        "docker_ok": False,
        "overrides": NO_OVERRIDES,
        "fixture_repo": FIXTURE,
    }
    options.update(kw)
    return probe_capabilities(http, make_verified_org(plan=plan), **options)


# --- plan matrix ----------------------------------------------------------------------------------------------------
def test_plan_matrix_matches_spec() -> None:
    """Exact contents of SPEC 8 (free < team < enterprise)."""
    team_extra = {
        Cap.PRIVATE_REPO_BRANCH_PROTECTION,
        Cap.PRIVATE_REPO_RULESETS,
        Cap.PRIVATE_REPO_ENVIRONMENTS,
        Cap.ORG_RULESETS,
        Cap.PUSH_RULESETS,
        Cap.ORG_SECRETS_PRIVATE_REPOS,
        Cap.LARGER_RUNNERS,
    }
    enterprise_extra = {
        Cap.PRIVATE_REPO_ENV_PROTECTION_RULES,
        Cap.PRIVATE_PAGES,
        Cap.RULESET_EVALUATE,
        Cap.CUSTOM_ORG_ROLES,
        Cap.INTERNAL_REPOS,
        Cap.OTTERDOG_ORG_RULESETS,
        Cap.MERGE_QUEUE_PRIVATE,
    }
    assert PLAN_MATRIX["free"] == {Cap.PUBLIC_REPOS, Cap.SECRET_SCANNING_PUBLIC}
    assert PLAN_MATRIX["team"] == PLAN_MATRIX["free"] | team_extra
    assert PLAN_MATRIX["enterprise"] == PLAN_MATRIX["team"] | enterprise_extra
    assert tuple(PLAN_MATRIX) == PLANS
    assert len(Cap) == 27  # 26 of SPEC 8 + WEB_UI (derived by the session, docs/web-ui-testing.md)


def test_from_plan_and_plans_at_least() -> None:
    """from_plan adds/removes; plans_at_least orders plans; unknown plans fail."""
    caps = from_plan("team", extra=[Cap.APP], remove=["larger_runners"])
    assert caps.plan == "team" and caps.has("app") and not caps.has(Cap.LARGER_RUNNERS) and caps.probes == {}
    assert plans_at_least("free") == PLANS
    assert plans_at_least("enterprise") == ("enterprise",)
    with pytest.raises(ValueError):
        plans_at_least("pro")


# --- probes ---------------------------------------------------------------------------------------------------------
def test_probe_status_records_statuses_and_errors() -> None:
    """Recorded statuses for 2xx/4xx, ints for other HTTP errors, 'error: ...' otherwise; never raises."""
    http = probes_http({SCHEMA: 200, ORG_LIMIT: 403})
    http.add("GET", ROLES, status=500, json={"message": "boom"})

    def explode(call: Any) -> tuple[Any, ...]:
        """A client-side failure."""
        raise ConnectionError("connection reset wpa-admin-token-01")

    http.add("GET", REPO_LIMIT, responder=explode)
    assert probe_status(http, SCHEMA) == 200
    assert probe_status(http, ORG_LIMIT) == 403
    assert probe_status(http, ROLES) == 500
    assert probe_status(http, f"/orgs/{FAKE_ORG}/missing") == 404
    error = probe_status(http, REPO_LIMIT)
    assert isinstance(error, str) and error.startswith("error: ConnectionError")


def test_probe_capabilities_free_org_with_all_probes_green() -> None:
    """200 on the schema and both cache limits -> CUSTOM_PROPERTIES and ACTIONS_CACHE_LIMIT; statuses recorded."""
    http = probes_http({SCHEMA: 200, REPO_LIMIT: 200, ORG_LIMIT: 200})
    caps = probe(http)
    assert caps.plan == "free"
    assert caps.caps == PLAN_MATRIX["free"] | {Cap.CUSTOM_PROPERTIES, Cap.ACTIONS_CACHE_LIMIT}
    assert caps.probes == {
        "properties_schema": 200,
        "repo_cache_storage_limit": 200,
        "org_cache_storage_limit": 200,
        "org_cache_storage_limit_documented": 404,
        "custom_repository_roles": 404,
        "overrides": {"add": [], "remove": []},
    }
    json.dumps(caps.to_json())
    assert all(call.method == "GET" for call in http.calls)


@pytest.mark.parametrize(
    ("statuses", "fixture"),
    [
        ({SCHEMA: 200, REPO_LIMIT: 200, ORG_LIMIT: 404}, FIXTURE),
        ({SCHEMA: 200, REPO_LIMIT: 403, ORG_LIMIT: 200}, FIXTURE),
        ({SCHEMA: 200, ORG_LIMIT: 200}, None),
    ],
)
def test_probe_capabilities_cache_limit_needs_both_probes(statuses: dict[str, int], fixture: str | None) -> None:
    """ACTIONS_CACHE_LIMIT only when the repo AND org storage-limit reads succeed (OC-06)."""
    http = probes_http(statuses)
    caps = probe(http, fixture_repo=fixture)
    assert not caps.has(Cap.ACTIONS_CACHE_LIMIT)
    assert caps.has(Cap.CUSTOM_PROPERTIES)
    if fixture is None:
        assert caps.probes["repo_cache_storage_limit"] is None
        assert http.calls_to("GET", "/repos/*") == []


def test_probe_capabilities_never_raises() -> None:
    """A broken client only loses the probe-derived capabilities."""

    class Broken:
        """Client whose every request fails."""

        def request(self, *args: Any, **kwargs: Any) -> Any:
            """Fail."""
            raise RuntimeError("network down")

    caps = probe(Broken(), plan="team")
    assert caps.caps == PLAN_MATRIX["team"]
    assert all(str(value).startswith("error: RuntimeError") for key, value in caps.probes.items() if key != "overrides")


def test_probe_capabilities_never_grants_ghas_private_from_probes() -> None:
    """GHAS_PRIVATE only comes from the target overrides (GH-08)."""
    http = probes_http({SCHEMA: 200, REPO_LIMIT: 200, ORG_LIMIT: 200, ROLES: 200})
    assert not probe(http, plan="enterprise").has(Cap.GHAS_PRIVATE)
    http = probes_http({})
    assert probe(http, plan="enterprise", overrides={"add": ["ghas_private"]}).has(Cap.GHAS_PRIVATE)


def test_probe_capabilities_environment_caps() -> None:
    """APP/DOCKER flags, IDENTITY_* for configured identities, SEPARATE_ORACLE for a distinct oracle token."""
    identities = {
        "admin": ADMIN,
        "oracle": Identity("oracle", None, "wpa-oracle-token-2"),
        "author": Identity("author", None, "wpa-author-token-3"),
        "approver": Identity("approver", None, "wpa-approver-token-4"),
        "outsider": Identity("outsider", None, "wpa-outsider-token-5"),
        "config_reader": Identity("config_reader", None, "wpa-reader-token-6"),
    }
    caps = probe(probes_http({}), identities=identities, app_ok=True, docker_ok=True)
    expected_env = {
        Cap.APP,
        Cap.DOCKER,
        Cap.IDENTITY_AUTHOR,
        Cap.IDENTITY_APPROVER,
        Cap.IDENTITY_OUTSIDER,
        Cap.IDENTITY_CONFIG_READER,
        Cap.SEPARATE_ORACLE,
    }
    assert expected_env <= caps.caps
    minimal = probe(probes_http({}))
    assert not (expected_env & minimal.caps)


def test_environment_caps_without_oracle_or_admin() -> None:
    """SEPARATE_ORACLE needs both identities with different tokens."""
    assert environment_caps({}, app_ok=False, docker_ok=False) == set()
    only_oracle = {"oracle": Identity("oracle", None, "t-1")}
    assert environment_caps(only_oracle, app_ok=False, docker_ok=True) == {Cap.DOCKER}


def test_probe_capabilities_overrides_apply_last(caplog: pytest.LogCaptureFixture) -> None:
    """Overrides win over plan and probes (remove beats add); unknown names are ignored with a warning."""
    http = probes_http({SCHEMA: 200})
    overrides = {
        "add": ["ghas_private", "LARGER_RUNNERS", "warp_drive"],
        "remove": ["custom_properties", "larger_runners"],
    }
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.capabilities"):
        caps = probe(http, plan="enterprise", overrides=overrides)
    assert caps.has(Cap.GHAS_PRIVATE)
    assert not caps.has(Cap.CUSTOM_PROPERTIES)
    assert not caps.has(Cap.LARGER_RUNNERS)
    assert "warp_drive" in caplog.text
    assert caps.probes["overrides"] == {
        "add": ["LARGER_RUNNERS", "ghas_private", "warp_drive"],
        "remove": ["custom_properties", "larger_runners"],
    }


def test_apply_overrides_tolerates_missing_keys() -> None:
    """Missing add/remove keys mean no change."""
    assert apply_overrides({Cap.APP}, {}) == {Cap.APP}
    assert apply_overrides({Cap.APP}, {"remove": ["app"]}) == set()


def test_probe_capabilities_enterprise_sanity_warning(caplog: pytest.LogCaptureFixture) -> None:
    """An enterprise org without custom-repository-roles (200) is reported, not fatal."""
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.capabilities"):
        caps = probe(probes_http({}), plan="enterprise")
    assert caps.caps == PLAN_MATRIX["enterprise"]
    assert "custom-repository-roles" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.capabilities"):
        probe(probes_http({ROLES: 200}), plan="enterprise")
    assert "custom-repository-roles" not in caplog.text


def test_probe_capabilities_unknown_plan_is_tolerated(caplog: pytest.LogCaptureFixture) -> None:
    """A plan outside the matrix yields no plan capabilities and a warning."""
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.capabilities"):
        caps = probe(probes_http({}), plan="business")
    assert caps.caps == frozenset() and "unknown plan" in caplog.text


# --- the real GitHubHttp (WP-B) through `responses` -----------------------------------------------------------------
def test_probe_capabilities_with_real_http() -> None:
    """Read-only probes through the real client: 200/403/404 are recorded, nothing is written."""
    with responses.RequestsMock() as rsps:
        rsps.get(f"{API}{SCHEMA}", json=[{"property_name": "x"}])
        rsps.get(f"{API}{REPO_LIMIT}", json={"max_cache_size_gb": 10})
        rsps.get(f"{API}{ORG_LIMIT}", status=404, json={"message": "Not Found"})
        rsps.get(f"{API}{DOCUMENTED_ORG_LIMIT}", json={"max_cache_size_gb": 10})
        rsps.get(f"{API}{ROLES}", status=403, json={"message": "Must have admin rights"})
        caps = probe(GitHubHttp(ADMIN.token, sleep=lambda _s: None, read_only=True))
        assert all(call.request.method == "GET" for call in rsps.calls)
    assert caps.has(Cap.CUSTOM_PROPERTIES) and not caps.has(Cap.ACTIONS_CACHE_LIMIT)
    assert caps.probes["org_cache_storage_limit"] == 404
    assert caps.probes["org_cache_storage_limit_documented"] == 200
    assert caps.probes["custom_repository_roles"] == 403


def test_documented_cache_limit_path_is_recorded_but_never_grants_the_capability() -> None:
    """GitHub's documented org path answering 200 while otterdog's /orgs/ path does not (KB-006): the capability stays
    off (the renderer must not show a setting otterdog cannot manage) and both statuses are recorded."""
    caps = probe(probes_http({SCHEMA: 200, REPO_LIMIT: 200, ORG_LIMIT: 404, DOCUMENTED_ORG_LIMIT: 200}))
    assert not caps.has(Cap.ACTIONS_CACHE_LIMIT)
    assert (caps.probes["org_cache_storage_limit"], caps.probes["org_cache_storage_limit_documented"]) == (404, 200)
