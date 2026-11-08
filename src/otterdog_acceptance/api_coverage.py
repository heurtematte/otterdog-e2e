"""Coverage of otterdog's HTTP write requests by the live scenarios (scenarios/api_endpoints.yaml ->
docs/api-coverage.md).

The inventory (otterdog.api_usage.load_inventory) lists every write request otterdog sends to GitHub, named as its
request statistics name them. A live scenario step asserts the requests of its apply with ``apply.api`` (``sent``,
``not_sent``). ApiCoverageProject binds the two for one otterdog-acceptance checkout:

* every write endpoint a scenario names is in the inventory (a typo would assert nothing: ``not_sent`` of a misspelt
  endpoint always passes);
* no step asserts as sent an endpoint the inventory marks ``untestable`` (no test organization can make otterdog
  send it: the step could never pass, or the mark is wrong);
* every ``feature`` of the inventory exists in scenarios/coverage.yaml;
* docs/api-coverage.md is exactly what render_markdown() produces: per endpoint the steps that assert it is sent,
  the steps that assert it is not, and the testable endpoints of the CLI no step asserts yet (the gaps), with the
  shares per HTTP method; the untestable endpoints are counted and listed apart with their reason.

tests/unit/test_api_endpoints.py runs these checks (``--write`` regenerates the documentation); ``otterdog-acceptance
assist check scenarios/api_endpoints.yaml`` reports the same problems.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

import yaml

from otterdog_acceptance.otterdog.api_usage import (
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
        from otterdog_acceptance.scenarios.model import load_scenarios

        scenarios = [s for name in LIVE_DIRS for s in load_scenarios(self.root / "scenarios" / name)]
        return collect_assertions(scenarios)

    def feature_ids(self) -> set[str]:
        """The feature ids of scenarios/coverage.yaml."""
        data = yaml.safe_load((self.root / COVERAGE_FILE).read_text(encoding="utf-8"))
        return {str(feature["id"]) for feature in data.get("features", []) if isinstance(feature, dict)}

    def problems(self) -> list[str]:
        """Unknown endpoints named by scenarios, untestable endpoints asserted as sent, unknown features of the
        inventory."""
        names = self.inventory.names()
        problems = [
            f"{a.label}: apply.api.{a.expectation} names {a.endpoint}, which scenarios/api_endpoints.yaml does not "
            "list (a misspelt endpoint asserts nothing)"
            for a in self.assertions
            if is_write(a.endpoint) and a.endpoint not in names
        ]
        problems += [untestable_problem(a.label, a.endpoint, reason) for a, reason in self.untestable_assertions()]
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

    def untestable_assertions(self) -> list[tuple[ApiAssertion, str]]:
        """The ``sent`` assertions of endpoints the inventory marks untestable, with the inventory's reason."""
        untestable = self.inventory.untestable()
        return [
            (a, untestable[a.endpoint]) for a in self.assertions if a.expectation == "sent" and a.endpoint in untestable
        ]

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
        """Per method (POST, PUT, PATCH, DELETE, mutation): (endpoints a step asserts sent, testable CLI endpoints);
        the untestable endpoints count in neither (untestable_shares)."""
        asserted = self.by_endpoint()
        totals: Counter[str] = Counter()
        covered: Counter[str] = Counter()
        for entry in self.inventory.endpoints:
            if not entry.testable:
                continue
            method = method_of(entry.endpoint)
            totals[method] += 1
            if asserted.get(entry.endpoint, {}).get("sent"):
                covered[method] += 1
        return {method: (covered[method], totals[method]) for method in METHOD_ORDER if totals[method]}

    def untestable_shares(self) -> dict[str, int]:
        """Per method: the CLI endpoints the inventory marks untestable."""
        counts = Counter(method_of(e.endpoint) for e in self.inventory.endpoints if e.scope == "cli" and not e.testable)
        return {method: counts[method] for method in METHOD_ORDER if counts[method]}

    def render_markdown(self) -> str:
        """docs/api-coverage.md."""
        inventory = self.inventory
        asserted = self.by_endpoint()
        shares = self.shares()
        not_testable = self.untestable_shares()
        covered = sum(c for c, _ in shares.values())
        total = sum(t for _, t in shares.values())
        untestable = [entry for entry in inventory.endpoints if entry.scope == "cli" and not entry.testable]
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
            (
                f"**{covered} of {total}** testable endpoints the CLI sends are asserted as sent by at least one step"
                + (
                    f"; {len(untestable)} more cannot be tested on a test organization ([not testable](#not-testable))."
                    if untestable
                    else "."
                )
            ),
            "",
            *self._method_table(shares, not_testable),
            "",
            (
                "Testable endpoints nobody asserts yet are the gaps of this page: a scenario that adds, changes or "
                "removes the object should name them in the `apply.api.sent` of the step (the `fill-coverage-gap` "
                "skill)."
            ),
            "",
        ]
        lines += ["## Endpoints", ""]
        lines += ["| Endpoint | Trigger | Asserted sent by | Asserted not sent by |", "|---|---|---|---|"]
        entry: InventoryEndpoint
        for entry in inventory.endpoints:
            found = asserted.get(entry.endpoint, {"sent": [], "not_sent": []})
            sent = _labels(found["sent"]) or _no_assertion(entry)
            not_sent = _labels(found["not_sent"])
            lines.append(f"| `{entry.endpoint}` | {_cell(entry.trigger)} | {sent} | {not_sent} |")
        lines.append("")
        if untestable:
            lines += [
                "## Not testable",
                "",
                (
                    "Endpoints of the CLI that no test organization can make otterdog send (`untestable` in the "
                    "inventory). They are not gaps: a step asserting one of them as sent is refused, a `not_sent` "
                    "assertion stays possible. Remove the mark when a test organization gets the prerequisite."
                ),
                "",
                "| Endpoint | Trigger | Why it cannot be tested |",
                "|---|---|---|",
                *(
                    f"| `{entry.endpoint}` | {_cell(entry.trigger)} | {_cell(entry.untestable or '')} |"
                    for entry in untestable
                ),
                "",
            ]
        return "\n".join(lines)

    @staticmethod
    def _method_table(shares: dict[str, tuple[int, int]], not_testable: dict[str, int]) -> list[str]:
        """The table of the shares per method; a 'Not testable' column (and a row for a method whose endpoints are all
        untestable) only when the inventory marks some endpoint untestable."""
        if not not_testable:
            return [
                "| Method | Asserted sent | Endpoints |",
                "|---|---:|---:|",
                *(f"| {method} | {c} | {t} |" for method, (c, t) in shares.items()),
            ]
        methods = [method for method in METHOD_ORDER if method in shares or method in not_testable]
        return [
            "| Method | Asserted sent | Testable endpoints | Not testable |",
            "|---|---:|---:|---:|",
            *(
                f"| {method} | {shares.get(method, (0, 0))[0]} | {shares.get(method, (0, 0))[1]} | "
                f"{not_testable.get(method, 0)} |"
                for method in methods
            ),
        ]


def untestable_problem(label: str, endpoint: str, reason: str) -> str:
    """The problem of a step asserting an untestable endpoint as sent."""
    return (
        f"{label}: apply.api.sent names {endpoint}, which scenarios/api_endpoints.yaml marks untestable ({reason}): "
        "no test organization makes otterdog send it; remove the mark if this one can"
    )


def _no_assertion(entry: InventoryEndpoint) -> str:
    """The 'asserted sent by' cell of an endpoint no step asserts: webapp only, not testable or a gap."""
    if entry.scope == "webapp":
        return "_webapp only_"
    if entry.untestable is not None:
        return "_not testable_"
    return "**none**"


def _labels(labels: list[str]) -> str:
    """Scenario/step labels as code spans, comma separated."""
    return ", ".join(f"`{label}`" for label in labels)


def _cell(text: str) -> str:
    """A table cell: one line, pipes escaped, placeholders in code spans kept readable."""
    return " ".join(text.split()).replace("|", "\\|").replace("<", "&lt;").replace(">", "&gt;")
