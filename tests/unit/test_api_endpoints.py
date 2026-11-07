"""Coverage of otterdog's HTTP write requests by the live scenarios (scenarios/api_endpoints.yaml, docs/api-coverage.md).

scenarios/api_endpoints.yaml lists every write request otterdog sends to GitHub, named as otterdog's request
statistics name them; live scenario steps assert the requests of their apply with ``apply.api`` (sent / not_sent).
These tests keep both honest (the checks live in otterdog_e2e.api_coverage, shared with ``otterdog-e2e assist check
scenarios/api_endpoints.yaml``):

* the inventory loads (unique write endpoints, sources, triggers, scopes) and its features exist in the coverage matrix;
* every write endpoint a live scenario names is in the inventory (``not_sent`` of a misspelt endpoint always passes);
* docs/api-coverage.md is exactly what render_markdown() produces.

After editing the inventory or the ``apply.api`` of a scenario, regenerate the documentation:

    .venv/bin/python tests/unit/test_api_endpoints.py --write
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path

from otterdog_e2e.api_coverage import REGENERATE, ApiAssertion, ApiCoverageProject, collect_assertions, method_of

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


def test_collect_assertions_reads_the_steps() -> None:
    """collect_assertions walks the steps' apply.api of the given scenarios."""
    from types import SimpleNamespace

    from otterdog_e2e.otterdog.api_usage import ApiSpec

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
