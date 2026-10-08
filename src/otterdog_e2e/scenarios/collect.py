"""From YAML scenarios to pytest items (SPEC 12.4, F4).

Test modules (tests/offline/test_scenarios.py, tests/cli/test_scenarios.py, tests/enterprise/test_scenarios.py,
tests/differential/test_offline_diff.py) call generate_scenario_tests from ``pytest_generate_tests``; the plugin applies
scenario_marks in ``pytest_collection_modifyitems`` via ``item.callspec.params["scenario"]``.

A live scenario is one item (a journey: its steps depend on the state the previous ones left, the first failure stops
it). The offline tier asks for one item per step (``per_step``: Scenario.cases), since offline steps share no state:
each case passes or fails on its own, and a failing case never hides the result of the next ones.

generate_scenario_tests already attaches the marks to each parameter (``pytest.param(..., marks=...)``) so selection by
``-m`` works without the plugin; apply_scenario_marks is idempotent (it skips items that carry the ``scenario`` mark),
so the plugin may call it for every item. Node ids are ``<test>[<scenario id>]``, e.g.
``tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.lifecycle]``, and ``<test>[<scenario id>/<step>]`` for a case,
e.g. ``tests/offline/test_scenarios.py::test_offline_scenario[O-VAL-REPO/too-many-topics]``.

Selection (item_selected, used by the plugin and by scenario_selected): ``--e2e-scenario`` and ``--e2e-tags`` are two
filters; inside one filter the comma separated values are ORed (any glob matches the scenario id or, for a case, its
``<scenario id>/<step>``, case-sensitive fnmatch; the item carries any of the tags), between the two filters it is AND; an empty filter keeps everything.
Items of tests/unit and tests/offline (TAGS_EXEMPT_TIERS) are exempt from ``--e2e-tags`` (the offline regression tier
always runs in full) but not from ``--e2e-scenario``: once globs are given, items without a matching scenario id
(unit tests included) are deselected. The scenarios referencing the change under test (``--e2e-change``, changes.py)
are extra scenarios of the tags filter: an item whose scenario id matches one of them passes it like a tagged item.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e.capabilities import plans_at_least
from otterdog_e2e.scenarios.model import Scenario, ScenarioError, load_scenarios

if TYPE_CHECKING:
    from _pytest.mark.structures import ParameterSet

SCENARIO_PARAM = "scenario"
TAGS_EXEMPT_TIERS = frozenset({"unit", "offline"})  # tier directories --e2e-tags never deselects (module docstring)
# pytest timeout (seconds) per tier directory / scenario tier (SPEC 2). web_ui: one web command at its runner timeout
# (otterdog.runner.WEB_TIMEOUT, 1800 s: Firefox, page loads, up to two bot logins a TOTP window apart) plus 5 minutes
# of oracle checks and login-gate waits; items running several web commands (the settings round trip) set their own.
TIER_TIMEOUTS: dict[str, int] = {
    "offline": 300,
    "cli": 600,
    "enterprise": 600,
    "webhooks": 900,
    "webapp": 900,
    "differential": 600,
    "web_ui": 2100,
}
# extra seconds of org_level live scenarios: unfiltered plans and a full BaselineManager.reset() as cleanup
ORG_LEVEL_EXTRA_TIMEOUT = 600


def scenario_timeout(scenario: Scenario) -> int:
    """pytest timeout of a scenario's item: its ``timeout`` key, else the tier timeout (+ ORG_LEVEL_EXTRA_TIMEOUT for
    org_level live scenarios)."""
    if scenario.timeout is not None:
        return scenario.timeout
    extra = ORG_LEVEL_EXTRA_TIMEOUT if scenario.org_level and scenario.is_live else 0
    return TIER_TIMEOUTS[scenario.tier] + extra


def scenario_marks(scenario: Scenario) -> list[pytest.MarkDecorator]:
    """Marks of a scenario: live (cli/enterprise), requires, plan (plans >= min_plan), identities, tags, known_bug,
    org_level, scenario(id) and timeout(scenario_timeout); the timeout of a live scenario covers its call only
    (``func_only``: the first live item would otherwise pay for the session setup, see pytest_plugin)."""
    marks: list[pytest.MarkDecorator] = []
    if scenario.is_live:
        marks.append(pytest.mark.live)
        marks.append(pytest.mark.plan(*plans_at_least(scenario.min_plan)))
    else:
        marks.append(pytest.mark.offline)
    if scenario.requires:
        marks.append(pytest.mark.requires(*scenario.requires))
    if scenario.identities:
        marks.append(pytest.mark.identities(*scenario.identities))
    if scenario.tags:
        marks.append(pytest.mark.tags(*scenario.tags))
    if scenario.known_bug:
        marks.append(pytest.mark.known_bug(scenario.known_bug))
    if scenario.org_level:
        marks.append(pytest.mark.org_level)
    marks.append(pytest.mark.scenario(scenario.id))
    if scenario.is_live:
        marks.append(pytest.mark.timeout(scenario_timeout(scenario), func_only=True))
    else:
        marks.append(pytest.mark.timeout(scenario_timeout(scenario)))
    return marks


def collect_scenarios(directories: Sequence[Path], *, tier: str | None = None) -> list[Scenario]:
    """Scenarios of several directories (load_scenarios each; ids must be unique across them, and the references of
    one change must not declare different ``base`` or ``template`` values: changes.conflicts)."""
    from otterdog_e2e.changes import ReferencingScenario, conflicts

    scenarios = [scenario for directory in directories for scenario in load_scenarios(directory, tier=tier)]
    seen: dict[str, Path] = {}
    for scenario in scenarios:
        if scenario.id in seen:
            raise ScenarioError(f"duplicate scenario id {scenario.id!r} in {seen[scenario.id]} and {scenario.source}")
        seen[scenario.id] = scenario.source
    entries = [
        ReferencingScenario(scenario.id, scenario.source, "yaml", reference)
        for scenario in scenarios
        for reference in scenario.references
    ]
    problems = conflicts(entries)
    if problems:
        raise ScenarioError("; ".join(problems))
    return scenarios


def scenario_params(scenarios: Iterable[Scenario], *, per_step: bool = False) -> list[ParameterSet]:
    """One ``pytest.param`` per scenario (id = scenario id), or per case with ``per_step`` (Scenario.cases, id =
    ``<scenario id>/<step>``); marks = scenario_marks."""
    items = [case for scenario in scenarios for case in scenario.cases()] if per_step else list(scenarios)
    return [pytest.param(item, marks=scenario_marks(item), id=item.case_id) for item in items]


def generate_scenario_tests(
    metafunc: pytest.Metafunc, directories: Sequence[Path], *, tier: str | None = None, per_step: bool = False
) -> None:
    """``metafunc.parametrize("scenario", <scenarios of directories>)`` when the test takes it (scenario_params)."""
    if SCENARIO_PARAM not in metafunc.fixturenames:
        return
    scenarios = collect_scenarios(directories, tier=tier)
    metafunc.parametrize(SCENARIO_PARAM, scenario_params(scenarios, per_step=per_step))


def item_scenario(item: pytest.Item) -> Scenario | None:
    """The Scenario a parametrized item runs (None for other items)."""
    callspec = getattr(item, "callspec", None)
    value: Any = callspec.params.get(SCENARIO_PARAM) if callspec is not None else None
    return value if isinstance(value, Scenario) else None


def apply_scenario_marks(item: pytest.Item) -> None:
    """Add scenario_marks to a parametrized item (no-op for items without a scenario parameter)."""
    scenario = item_scenario(item)
    if scenario is None:
        return
    if any(mark.args[:1] == (scenario.id,) for mark in item.iter_markers(SCENARIO_PARAM)):
        return
    for mark in scenario_marks(scenario):
        item.add_marker(mark)


def _clean(values: Iterable[str]) -> list[str]:
    """Stripped, non-empty option values."""
    return [value.strip() for value in values if value and value.strip()]


def _matches(scenario_id: str | None, patterns: Sequence[str], case_id: str | None = None) -> bool:
    """True when the scenario id (or the case id) matches one of the fnmatch patterns (case-sensitive)."""
    ids = [name for name in (scenario_id, case_id) if name is not None]
    return any(fnmatch.fnmatchcase(name, pattern) for name in ids for pattern in patterns)


def item_selected(
    scenario_id: str | None,
    item_tags: Iterable[str],
    *,
    globs: Iterable[str] = (),
    tags: Iterable[str] = (),
    tags_exempt: bool = False,
    extra_scenarios: Iterable[str] = (),
    case_id: str | None = None,
) -> bool:
    """The selection rule of the module docstring: (no globs or the id or ``case_id`` matches one) AND (no tags,
    ``tags_exempt`` (tests/unit, tests/offline), the item carries one of them, or the id matches an
    ``extra_scenarios`` glob)."""
    patterns = _clean(globs)
    if patterns and not _matches(scenario_id, patterns, case_id):
        return False
    wanted = set(_clean(tags))
    if not wanted or tags_exempt or wanted & set(item_tags):
        return True
    return _matches(scenario_id, _clean(extra_scenarios))


def scenario_selected(
    scenario: Scenario,
    *,
    globs: Iterable[str] = (),
    tags: Iterable[str] = (),
    tags_exempt: bool = False,
    extra_scenarios: Iterable[str] = (),
) -> bool:
    """item_selected for a Scenario: --e2e-scenario globs AND --e2e-tags (any value inside one filter); pass
    ``tags_exempt`` for the items of tests/unit and tests/offline (offline scenarios run by tests/differential are
    tag-filtered); empty filters select all."""
    return item_selected(
        scenario.id,
        scenario.tags,
        globs=globs,
        tags=tags,
        tags_exempt=tags_exempt,
        extra_scenarios=extra_scenarios,
        case_id=scenario.case_id if scenario.case is not None else None,
    )


def split_option(value: str | Sequence[str] | None) -> list[str]:
    """Comma separated option values (``"a, b"`` or ``["a,b", "c"]``) as a clean list."""
    if not value:
        return []
    parts = [value] if isinstance(value, str) else list(value)
    return [item.strip() for part in parts for item in part.split(",") if item.strip()]
