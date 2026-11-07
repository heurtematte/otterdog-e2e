"""Coverage of otterdog's HTTP write requests by the live scenarios (scenarios/api_endpoints.yaml -> docs/api-coverage.md).

The inventory (otterdog.api_usage.load_inventory) lists every write request otterdog sends to GitHub, named as its
request statistics name them. A live scenario step asserts the requests of its apply with ``apply.api`` (``sent``,
``not_sent``). ApiCoverageProject binds the two for one otterdog-e2e checkout:

* every write endpoint a scenario names is in the inventory (a typo would assert nothing: ``not_sent`` of a misspelt
  endpoint always passes);
* every ``feature`` of the inventory exists in scenarios/coverage.yaml;
* docs/api-coverage.md is exactly what render_markdown() produces: per endpoint the steps that assert it is sent,
  the steps that assert it is not, and the endpoints of the CLI no step asserts yet (the gaps), with the shares per
  HTTP method.

tests/unit/test_api_endpoints.py runs these checks (``--write`` regenerates the documentation); ``otterdog-e2e assist
check scenarios/api_endpoints.yaml`` reports the same problems.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

from otterdog_e2e.otterdog.api_usage import (
    ENDPOINT_RE,
    INVENTORY_FILE,
    ApiInventory,
    InventoryEndpoint,
    is_write,
    load_inventory,
)

DOC_FILE = Path("docs") / "api-coverage.md"
COVERAGE_FILE = Path("scenarios") / "coverage.yaml"
LIVE_DIRS = ("cli", "enterprise")
REGENERATE = ".venv/bin/python tests/unit/test_api_endpoints.py --write"
METHOD_ORDER = ("POST", "PUT", "PATCH", "DELETE", "mutation")


@dataclass(frozen=True)
class ApiAssertion:
    """One endpoint named by a step's ``apply.api``: the scenario, the step and the list (``sent``/``not_sent``)."""

    scenario: str
    step: str
    expectation: str
    endpoint: str

    @property
    def label(self) -> str:
        """``<scenario id>/<step>``."""
        return f"{self.scenario}/{self.step}"


def method_of(endpoint: str) -> str:
    """The HTTP method of a REST endpoint, ``mutation`` or ``query`` for GraphQL."""
    match = ENDPOINT_RE.match(endpoint)
    if match is None:
        return "?"
    return match.group("method") or match.group("operation")


def collect_assertions(scenarios: Iterable[object]) -> list[ApiAssertion]:
    """Every endpoint named by the ``apply.api`` of the steps of ``scenarios`` (scenarios.model.Scenario)."""
    found = []
    for scenario in scenarios:
        for step in getattr(scenario, "steps", []):
            apply = getattr(step, "apply", None)
            api = getattr(apply, "api", None)
            if api is None:
                continue
            for expectation in ("sent", "not_sent"):
                for endpoint in getattr(api, expectation):
                    found.append(ApiAssertion(scenario.id, step.name, expectation, endpoint))  # type: ignore[attr-defined]
    return found


class ApiCoverageProject:
    """The inventory, the live scenarios and the generated documentation of one checkout."""

    def __init__(self, root: Path) -> None:
        """Bind to the project root."""
        self.root = Path(root)

    @property
    def inventory_path(self) -> Path:
        """scenarios/api_endpoints.yaml."""
        return self.root / INVENTORY_FILE

    @property
    def doc_path(self) -> Path:
        """docs/api-coverage.md."""
        return self.root / DOC_FILE

    @cached_property
    def inventory(self) -> ApiInventory:
        """The parsed inventory (ValueError when invalid)."""
        return load_inventory(self.inventory_path)

    @cached_property
    def assertions(self) -> list[ApiAssertion]:
        """The ``apply.api`` endpoints of every live scenario (scenarios/cli, scenarios/enterprise)."""
        from otterdog_e2e.scenarios.model import load_scenarios

        scenarios = [s for name in LIVE_DIRS for s in load_scenarios(self.root / "scenarios" / name)]
        return collect_assertions(scenarios)

    def feature_ids(self) -> set[str]:
        """The feature ids of scenarios/coverage.yaml."""
        data = yaml.safe_load((self.root / COVERAGE_FILE).read_text(encoding="utf-8"))
        return {str(feature["id"]) for feature in data.get("features", []) if isinstance(feature, dict)}

    def problems(self) -> list[str]:
        """Unknown endpoints named by scenarios, unknown features of the inventory."""
        names = self.inventory.names()
        problems = [
            f"{a.label}: apply.api.{a.expectation} names {a.endpoint}, which scenarios/api_endpoints.yaml does not "
            "list (a misspelt endpoint asserts nothing)"
            for a in self.assertions
            if is_write(a.endpoint) and a.endpoint not in names
        ]
        features = self.feature_ids()
        problems += [
            f"api_endpoints.yaml: {entry.endpoint}: unknown feature {entry.feature!r} of scenarios/coverage.yaml"
            for entry in self.inventory.endpoints
            if entry.feature is not None and entry.feature not in features
        ]
        return problems

    def markdown_problems(self) -> list[str]:
        """docs/api-coverage.md differs from render_markdown()."""
        current = self.doc_path.read_text(encoding="utf-8") if self.doc_path.is_file() else ""
        if current != self.render_markdown():
            return [f"{DOC_FILE} is stale, regenerate it: {REGENERATE}"]
        return []

    def all_problems(self) -> list[str]:
        """Every problem (assist check scenarios/api_endpoints.yaml)."""
        return self.problems() + self.markdown_problems()

    # --- rendering -------------------------------------------------------------------------------------------------
    def by_endpoint(self) -> dict[str, dict[str, list[str]]]:
        """endpoint -> {"sent": [labels], "not_sent": [labels]} (sorted, unique)."""
        result: dict[str, dict[str, list[str]]] = {}
        for assertion in self.assertions:
            entry = result.setdefault(assertion.endpoint, {"sent": [], "not_sent": []})
            if assertion.label not in entry[assertion.expectation]:
                entry[assertion.expectation].append(assertion.label)
        for entry in result.values():
            entry["sent"].sort()
            entry["not_sent"].sort()
        return result

    def shares(self) -> dict[str, tuple[int, int]]:
        """Per method (POST, PUT, PATCH, DELETE, mutation): (endpoints a step asserts sent, CLI endpoints)."""
        asserted = self.by_endpoint()
        totals: Counter[str] = Counter()
        covered: Counter[str] = Counter()
        for entry in self.inventory.endpoints:
            if entry.scope != "cli":
                continue
            method = method_of(entry.endpoint)
            totals[method] += 1
            if asserted.get(entry.endpoint, {}).get("sent"):
                covered[method] += 1
        return {method: (covered[method], totals[method]) for method in METHOD_ORDER if totals[method]}

    def render_markdown(self) -> str:
        """docs/api-coverage.md."""
        inventory = self.inventory
        asserted = self.by_endpoint()
        shares = self.shares()
        covered = sum(c for c, _ in shares.values())
        total = sum(t for _, t in shares.values())
        lines = [
            "# HTTP request coverage",
            "",
            f"<!-- generated from scenarios/api_endpoints.yaml and the live scenarios: {REGENERATE} -->",
            "",
            (
                "Every write request otterdog sends to GitHub (REST `POST`, `PUT`, `PATCH`, `DELETE` and GraphQL "
                "mutations), listed in [scenarios/api_endpoints.yaml](../scenarios/api_endpoints.yaml) at otterdog "
                f"`{inventory.ref[:7]}`, and the live scenario steps whose `apply.api` asserts it. A step asserts the "
                "requests of its apply from otterdog's request statistics (otterdog 1.7.0 and later, "
                "[writing scenarios](writing-scenarios.md#http-requests-of-an-apply)): `sent` means the apply sent at "
                "least one such request, `not sent` that it sent none (for instance no `PATCH /repos/{owner}/{repo}` "
                "when only `team_permissions` change, otterdog#924)."
            ),
            "",
            f"**{covered} of {total}** endpoints the CLI sends are asserted as sent by at least one step.",
            "",
            "| Method | Asserted sent | Endpoints |",
            "|---|---:|---:|",
            *(f"| {method} | {c} | {t} |" for method, (c, t) in shares.items()),
            "",
            (
                "Endpoints nobody asserts yet are the gaps of this page: a scenario that adds, changes or removes the "
                "object should name them in the `apply.api.sent` of the step (the `fill-coverage-gap` skill)."
            ),
            "",
        ]
        lines += ["## Endpoints", ""]
        lines += ["| Endpoint | Trigger | Asserted sent by | Asserted not sent by |", "|---|---|---|---|"]
        entry: InventoryEndpoint
        for entry in inventory.endpoints:
            found = asserted.get(entry.endpoint, {"sent": [], "not_sent": []})
            sent = _labels(found["sent"]) or ("_webapp only_" if entry.scope == "webapp" else "**none**")
            not_sent = _labels(found["not_sent"])
            lines.append(f"| `{entry.endpoint}` | {_cell(entry.trigger)} | {sent} | {not_sent} |")
        lines.append("")
        return "\n".join(lines)


def _labels(labels: list[str]) -> str:
    """Scenario/step labels as code spans, comma separated."""
    return ", ".join(f"`{label}`" for label in labels)


def _cell(text: str) -> str:
    """A table cell: one line, pipes escaped, placeholders in code spans kept readable."""
    return " ".join(text.split()).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
