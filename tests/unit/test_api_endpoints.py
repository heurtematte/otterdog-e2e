"""Coverage of otterdog's HTTP write requests by the live scenarios (scenarios/api_endpoints.yaml,
docs/api-coverage.md).

scenarios/api_endpoints.yaml lists every write request otterdog sends to GitHub, named as otterdog's request
statistics name them; live scenario steps assert the requests of their apply with ``apply.api`` (sent / not_sent).
These tests keep both honest (the checks live in otterdog_acceptance.api_coverage, shared with ``otterdog-acceptance
assist check scenarios/api_endpoints.yaml``):

* the inventory loads (unique write endpoints, sources, triggers, scopes) and its features exist in the coverage matrix;
* every write endpoint a live scenario names is in the inventory (``not_sent`` of a misspelt endpoint always passes);
* the endpoints marked ``untestable`` (an identity provider no test organization has) are counted and listed apart,
  and no step asserts one of them as sent;
* docs/api-coverage.md is exactly what render_markdown() produces.

After editing the inventory or the ``apply.api`` of a scenario, regenerate the documentation:

    .venv/bin/python tests/unit/test_api_endpoints.py --write
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from otterdog_acceptance.api_coverage import REGENERATE, ApiAssertion, ApiCoverageProject, collect_assertions, method_of
from otterdog_acceptance.otterdog.api_usage import ApiInventory, InventoryEndpoint

ROOT = Path(__file__).resolve().parents[2]
PROJECT = ApiCoverageProject(ROOT)


def test_inventory_and_scenarios_agree() -> None:
    """Every write endpoint named by a live scenario is in the inventory, every feature of the inventory exists."""
    assert PROJECT.problems() == []


def test_markdown_is_up_to_date() -> None:
    """docs/api-coverage.md is the rendering of the inventory and the scenarios."""
    assert PROJECT.markdown_problems() == [], f"regenerate it: {REGENERATE}"


def test_the_inventory_covers_every_verb() -> None:
    """The inventory holds the four write methods and the GraphQL mutations of branch protection rules."""
    methods = {method_of(entry.endpoint) for entry in PROJECT.inventory.endpoints if entry.scope == "cli"}
    assert methods == {"POST", "PUT", "PATCH", "DELETE", "mutation"}
    names = PROJECT.inventory.names()
    assert {"PATCH /repos/{owner}/{repo}", "DELETE /orgs/{org}/teams/{name}/repos/{owner}/{repo}"} <= names
    assert {f"mutation {op}BranchProtectionRule" for op in ("create", "update", "delete")} <= names


def test_a_misspelt_endpoint_is_a_problem(tmp_path: Path) -> None:
    """A scenario naming an endpoint the inventory does not list is reported (GET endpoints are free)."""
    project = ApiCoverageProject(ROOT)
    project.__dict__["assertions"] = [
        ApiAssertion("cli.x", "s", "not_sent", "PATCH /repos/{owner}/{repository}"),
        ApiAssertion("cli.x", "s", "sent", "GET /repos/{owner}/{repo}"),
    ]
    problems = project.problems()
    assert len(problems) == 1 and "cli.x/s: apply.api.not_sent names PATCH /repos/{owner}/{repository}" in problems[0]


IDP_ENDPOINTS = {
    "PATCH /orgs/{org}/teams/{name}/team-sync/group-mappings",
    "PATCH /orgs/{org}/teams/{name}/external-groups",
    "DELETE /orgs/{org}/teams/{name}/external-groups",
}


def test_the_identity_provider_endpoints_are_the_untestable_ones() -> None:
    """Team synchronization and external groups need an identity provider no test organization has: they are the
    untestable endpoints of the inventory, each with its reason, and no step asserts them as sent."""
    untestable = PROJECT.inventory.untestable()
    assert set(untestable) == IDP_ENDPOINTS
    assert all("identity provider" in reason for reason in untestable.values())
    assert PROJECT.untestable_assertions() == []


def project_with(inventory: ApiInventory, assertions: list[ApiAssertion]) -> ApiCoverageProject:
    """An ApiCoverageProject of the repository whose inventory and assertions are replaced."""
    project = ApiCoverageProject(ROOT)
    project.__dict__["inventory"] = inventory
    project.__dict__["assertions"] = assertions
    return project


SMALL_INVENTORY = ApiInventory(
    "a" * 40,
    (
        InventoryEndpoint("PATCH /repos/{owner}/{repo}", "rc.py:1", "a setting changes", "repositories.lifecycle"),
        InventoryEndpoint("DELETE /repos/{owner}/{repo}", "rc.py:2", "a repository is removed"),
        InventoryEndpoint("PATCH /orgs/{org}/teams/{name}/external-groups", "tc.py:3", "connected", untestable="EMU"),
        InventoryEndpoint("mutation minimizeComment", "gq.py:4", "outdated comments", scope="webapp"),
    ),
)


def test_untestable_endpoints_are_counted_and_listed_apart() -> None:
    """The shares count the testable CLI endpoints only, the untestable ones per method apart; the page says
    '1 of 2 testable', marks the untestable endpoint '_not testable_' (not a gap) and lists it with its reason."""
    project = project_with(SMALL_INVENTORY, [ApiAssertion("cli.x", "s", "sent", "PATCH /repos/{owner}/{repo}")])
    assert project.shares() == {"PATCH": (1, 1), "DELETE": (0, 1)}
    assert project.untestable_shares() == {"PATCH": 1}
    text = project.render_markdown()
    assert "**1 of 2** testable endpoints the CLI sends are asserted as sent by at least one step; 1 more" in text
    assert "| PATCH | 1 | 1 | 1 |" in text and "| DELETE | 0 | 1 | 0 |" in text
    assert "| `DELETE /repos/{owner}/{repo}` | a repository is removed | **none** |  |" in text
    assert "| `PATCH /orgs/{org}/teams/{name}/external-groups` | connected | _not testable_ |  |" in text
    assert (
        "## Not testable" in text and "| `PATCH /orgs/{org}/teams/{name}/external-groups` | connected | EMU |" in text
    )
    assert "_webapp only_" in text


def test_an_untestable_endpoint_asserted_as_sent_is_a_problem() -> None:
    """A step asserting an untestable endpoint as sent could never pass (or the mark is wrong): a problem; asserting
    that it is not sent stays possible."""
    endpoint = "PATCH /orgs/{org}/teams/{name}/external-groups"
    project = project_with(
        SMALL_INVENTORY,
        [ApiAssertion("cli.x", "s", "sent", endpoint), ApiAssertion("cli.x", "t", "not_sent", endpoint)],
    )
    problems = project.problems()
    assert len(problems) == 1 and problems[0].startswith(f"cli.x/s: apply.api.sent names {endpoint}")
    assert "marks untestable (EMU)" in problems[0]
    text = project_with(ApiInventory("a" * 40, SMALL_INVENTORY.endpoints[:2]), []).render_markdown()
    assert (
        "Not testable" not in text and "| Method | Asserted sent | Endpoints |" in text and "| PATCH | 0 | 1 |" in text
    )


def test_collect_assertions_reads_the_steps() -> None:
    """collect_assertions walks the steps' apply.api of the given scenarios."""
    from types import SimpleNamespace

    from otterdog_acceptance.otterdog.api_usage import ApiSpec

    step = SimpleNamespace(name="s", apply=SimpleNamespace(api=ApiSpec(sent=["POST /x"], not_sent=["PUT /y"])))
    other = SimpleNamespace(name="t", apply=None)
    scenario = SimpleNamespace(id="cli.a", steps=[step, other])
    assert [(a.label, a.expectation, a.endpoint) for a in collect_assertions([scenario])] == [
        ("cli.a/s", "sent", "POST /x"),
        ("cli.a/s", "not_sent", "PUT /y"),
    ]


def main(argv: Sequence[str]) -> int:
    """``--write`` regenerates docs/api-coverage.md; always print the shares per method."""
    if "--write" in argv:
        PROJECT.doc_path.write_text(PROJECT.render_markdown(), encoding="utf-8")
        sys.stdout.write(f"wrote {PROJECT.doc_path.relative_to(ROOT)}\n")
    for method, (covered, total) in PROJECT.shares().items():
        sys.stdout.write(f"{method:9} {covered:3} / {total:3} asserted sent\n")
    untestable = sum(PROJECT.untestable_shares().values())
    if untestable:
        sys.stdout.write(f"{'':9} {untestable:3} not testable (untestable in scenarios/api_endpoints.yaml)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
