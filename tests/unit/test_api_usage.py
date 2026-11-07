"""The requests of an otterdog command (otterdog_e2e.otterdog.api_usage): otterdog's statistics report, the
``apply.api`` expectations of a scenario step (model and engine) and the inventory of write requests."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e.otterdog.api_usage import (
    ApiSpec,
    ApiUsage,
    api_problems,
    endpoint_problem,
    is_write,
    load_inventory,
    parse_api_usage,
    unknown_endpoints,
)
from otterdog_e2e.scenarios.model import ScenarioError, load_scenario

# the shape otterdog 1.7.0 writes (otterdog/providers/github/stats/report.py ApiUsageReport.to_json), trimmed
REPORT: dict[str, Any] = {
    "command": "apply",
    "outcome": "success",
    "duration_seconds": 3.2,
    "total": {"requests": 9},
    "apis": {
        "rest": {
            "requests": 7,
            "errors": {"403": 1},
            "endpoints": {
                "GET /repos/{owner}/{repo}": {"requests": 3, "quota_cost": 3},
                "PATCH /repos/{owner}/{repo}": {"requests": 1, "quota_cost": 1},
                "PUT /orgs/{org}/teams/{name}/repos/{owner}/{repo}": {"requests": 2, "quota_cost": 2},
                "DELETE /orgs/{org}/teams/{name}/repos/{owner}/{repo}": {"requests": 1, "quota_cost": 1},
            },
        },
        "graphql": {
            "requests": 2,
            "errors": {},
            "endpoints": {
                "query get-branch-protection-rules": {"requests": 1, "quota_cost": 1},
                "mutation createBranchProtectionRule": {"requests": 1, "quota_cost": 1},
            },
        },
        "web": {"requests": 0, "errors": {}, "endpoints": {}},
    },
    "rate_limits": {},
    "organizations": {},
}
TEAM_REPO = "PUT /orgs/{org}/teams/{name}/repos/{owner}/{repo}"


def test_parse_merges_the_apis_and_keeps_the_errors() -> None:
    parsed = parse_api_usage(json.dumps(REPORT))
    assert parsed.count("PATCH /repos/{owner}/{repo}") == 1 and parsed.count(TEAM_REPO) == 2
    assert parsed.count("mutation createBranchProtectionRule") == 1 and parsed.count("POST /orgs/{org}/repos") == 0
    assert parsed.errors == {"rest:403": 1} and parsed.outcome == "success"
    assert list(parsed.writes()) == [
        "DELETE /orgs/{org}/teams/{name}/repos/{owner}/{repo}",
        "PATCH /repos/{owner}/{repo}",
        TEAM_REPO,
        "mutation createBranchProtectionRule",
    ]
    assert parsed.summary().startswith("DELETE /orgs/{org}/teams/{name}/repos/{owner}/{repo}, PATCH")
    assert f"{TEAM_REPO} x2" in parsed.summary()
    assert ApiUsage().summary() == "no write request"


@pytest.mark.parametrize(
    "text",
    ["not json", "[]", '{"apis": []}', '{"apis": {"rest": 1}}', '{"apis": {"rest": {"endpoints": {"GET /x": 3}}}}'],
)
def test_parse_refuses_what_is_not_a_report(text: str) -> None:
    with pytest.raises(ValueError):
        parse_api_usage(text)


def test_endpoint_names() -> None:
    assert endpoint_problem("PATCH /repos/{owner}/{repo}") is None
    assert endpoint_problem("mutation deleteBranchProtectionRule") is None
    for bad in ("PATCH /repos/acme repo", "patch /repos", "PATCH repos", "mutation", "POST /x?y=1", 3):
        assert endpoint_problem(bad), bad
    assert is_write("DELETE /orgs/{org}/hooks/{id}") and is_write("mutation createBranchProtectionRule")
    assert not is_write("GET /orgs/{org}") and not is_write("query get-team-membership") and not is_write("nope")


def test_api_problems_name_the_requests_sent() -> None:
    sent = ApiUsage({"PATCH /repos/{owner}/{repo}": 1, TEAM_REPO: 1, "GET /repos/{owner}/{repo}": 2})
    assert api_problems(ApiSpec(sent=[TEAM_REPO], not_sent=["DELETE /repos/{owner}/{repo}"]), sent) == []
    problems = api_problems(ApiSpec(sent=["POST /orgs/{org}/repos"], not_sent=["PATCH /repos/{owner}/{repo}"]), sent)
    assert problems == [
        "apply.api: expected request(s) not sent: POST /orgs/{org}/repos",
        "apply.api: unexpected request(s) sent: PATCH /repos/{owner}/{repo} x1",
        f"apply.api: the write requests sent: PATCH /repos/{{owner}}/{{repo}}, {TEAM_REPO}",
    ]


# --- the scenario model ------------------------------------------------------------------------------------------------
LIVE = """
id: cli.repo.api
title: api
tags: [repo]
steps:
  - name: change
    fragments:
      repositories: ["orgs.newRepo('{{ p }}-api') { description: 'e2e api' }"]
    apply:
      api: %s
"""


def live(tmp_path: Path, api: str) -> Any:
    """Load a live scenario whose single step has the given ``apply.api`` (YAML flow)."""
    path = tmp_path / "cli" / "repo" / "api.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(LIVE % api).lstrip("\n"))
    return load_scenario(path)


def test_model_parses_apply_api(tmp_path: Path) -> None:
    spec = live(tmp_path, f"{{sent: ['{TEAM_REPO}'], not_sent: ['PATCH /repos/{{owner}}/{{repo}}']}}").steps[0].apply
    assert spec.api == ApiSpec(sent=[TEAM_REPO], not_sent=["PATCH /repos/{owner}/{repo}"])
    assert live(tmp_path, "null").steps[0].apply.api is None


@pytest.mark.parametrize(
    ("api", "message"),
    [
        ("{sent: ['PATCH repos']}", "is not an endpoint"),
        ("{sent: ['POST /orgs/{org}/repos'], not_sent: ['POST /orgs/{org}/repos']}", "both sent and not_sent"),
        ("{sent: ['POST /orgs/{org}/repos', 'POST /orgs/{org}/repos']}", "duplicate endpoints"),
        ("{}", "give sent and/or not_sent"),
        ("{sent: ['POST /orgs/{org}/repos'], count: 1}", "count"),
    ],
)
def test_model_refuses_invalid_apply_api(tmp_path: Path, api: str, message: str) -> None:
    with pytest.raises(ScenarioError, match=message):
        live(tmp_path, api)


# --- the engine --------------------------------------------------------------------------------------------------------
def engine_problems(spec: ApiSpec | None, usage: ApiUsage | None, version: str | None) -> tuple[list[str], list[str]]:
    """ScenarioEngine._api_problems over a stand-in engine whose SUT has ``version``; (problems, notes)."""
    from otterdog_e2e.scenarios.engine import ScenarioEngine, StepOutcome

    installed = SimpleNamespace(sut=SimpleNamespace(version=version))
    engine = SimpleNamespace(cli=SimpleNamespace(installed=installed))
    outcome = StepOutcome("step")
    result = SimpleNamespace(api_usage=usage)
    apply = SimpleNamespace(api=spec)
    problems = ScenarioEngine._api_problems(engine, apply, result, outcome)  # type: ignore[arg-type]
    return problems, outcome.notes


def test_engine_checks_the_requests_of_the_apply() -> None:
    spec = ApiSpec(not_sent=["PATCH /repos/{owner}/{repo}"])
    assert engine_problems(spec, ApiUsage({TEAM_REPO: 1}), "1.8.0.dev3") == ([], [])
    problems, _ = engine_problems(spec, ApiUsage({"PATCH /repos/{owner}/{repo}": 1}), "1.8.0.dev3")
    assert problems[0] == "apply.api: unexpected request(s) sent: PATCH /repos/{owner}/{repo} x1"
    assert engine_problems(None, None, "1.7.1") == ([], [])


def test_engine_skips_the_check_on_suts_without_statistics() -> None:
    """Before 1.7.0 otterdog writes no report: noted, not failed; a newer SUT without a report fails the check."""
    spec = ApiSpec(sent=[TEAM_REPO])
    problems, notes = engine_problems(spec, None, "1.6.1")
    assert problems == [] and notes == ["apply.api not checked: SUT 1.6.1 predates otterdog 1.7.0 (#881)"]
    problems, notes = engine_problems(spec, None, "1.7.1")
    assert problems == [
        "apply.api: otterdog wrote no request statistics (OTTERDOG_STATS_FILE), the requests are unknown"
    ]


# --- the inventory -----------------------------------------------------------------------------------------------------
INVENTORY = """
otterdog: {ref: %s}
endpoints:
  - {endpoint: 'PATCH /repos/{owner}/{repo}', source: rc.py:1, trigger: a setting changes, feature: repositories.lifecycle}
  - {endpoint: 'mutation minimizeComment', source: gq.py:2, trigger: outdated comments, scope: webapp}
"""


def test_inventory_loads_and_names_unknown_endpoints(tmp_path: Path) -> None:
    path = tmp_path / "api_endpoints.yaml"
    path.write_text(INVENTORY % ("a" * 40))
    inventory = load_inventory(path)
    assert inventory.names() == {"PATCH /repos/{owner}/{repo}", "mutation minimizeComment"}
    assert inventory.endpoints[1].scope == "webapp" and inventory.endpoints[0].feature == "repositories.lifecycle"
    assert unknown_endpoints(
        ["PATCH /repos/{owner}/{repo}", "GET /x", "PUT /orgs/{org}/x", "PUT /orgs/{org}/x"], inventory
    ) == ["PUT /orgs/{org}/x"]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        (INVENTORY % "main", "otterdog.ref"),
        (INVENTORY % ("a" * 40) + "  - {endpoint: 'GET /orgs/{org}', source: x, trigger: y}\n", "not a write request"),
        (INVENTORY % ("a" * 40) + "  - {endpoint: 'mutation minimizeComment', source: x, trigger: y}\n", "duplicate"),
        (INVENTORY % ("a" * 40) + "  - {endpoint: 'POST /orgs/{org}/repos', source: x}\n", "'trigger' must be"),
        (INVENTORY % ("a" * 40) + "  - {endpoint: 'POST /x', source: x, trigger: y, scope: app}\n", "scope must be"),
        (INVENTORY % ("a" * 40) + "  - {endpoint: 'POST /x', source: x, trigger: y, why: z}\n", "unknown key"),
    ],
)
def test_inventory_refusals(tmp_path: Path, text: str, message: str) -> None:
    path = tmp_path / "api_endpoints.yaml"
    path.write_text(text)
    with pytest.raises(ValueError, match=message):
        load_inventory(path)
