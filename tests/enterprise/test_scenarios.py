"""Enterprise tier: the YAML scenarios of scenarios/enterprise (SPEC 2, 12.4, 19).

Every scenario has min_plan enterprise (plan mark ``plan("enterprise")``) and requires the matching capabilities, so
on a Free or Team target the items skip before any fixture runs; without --e2e-target they skip at collection.
Scenarios linked to a known bug (known_bug field or known_bugs.yaml) are non-strict xfails. The same ScenarioEngine as
the CLI tier runs them (SUT CLI, oracle, converge, guarded cleanup with the trusted reset CLI).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.context import get_context
from otterdog_e2e.scenarios.collect import generate_scenario_tests

if TYPE_CHECKING:
    from otterdog_e2e.scenarios.engine import ScenarioEngine
    from otterdog_e2e.scenarios.model import Scenario

SCENARIO_DIRS = ("enterprise",)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize ``scenario`` with the scenarios of scenarios/enterprise."""
    root = get_context(metafunc.config).settings.scenarios_dir
    generate_scenario_tests(metafunc, [root / name for name in SCENARIO_DIRS])


def test_enterprise_scenario(scenario: Scenario, scenario_engine: ScenarioEngine) -> None:
    """Run one enterprise scenario end to end (skips when the target lacks a capability or the plan)."""
    reason = scenario_engine.skip_reason(scenario)
    if reason:
        pytest.skip(reason)
    outcome = scenario_engine.run(scenario)
    if outcome.skipped:
        pytest.skip(outcome.skipped)
