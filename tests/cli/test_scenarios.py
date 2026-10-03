"""Live CLI tier: every YAML scenario of scenarios/cli and scenarios/regressions (SPEC 12.4, 19).

One item per scenario, parametrized at collection (``test_cli_scenario[<scenario id>]``); the plugin adds the
scenario marks (live, requires, plan, identities, tags, known_bug, org_level, scenario, timeout) and skips every item
without --e2e-target. The ScenarioEngine runs the steps with the SUT CLI (``plan``/``apply -n`` filtered to this run's
repositories unless org_level), checks the oracle and converges, then cleans up with the trusted reset CLI (guarded
``apply -d``; full baseline reset for org_level scenarios). Scenarios with a probe (tests/cli/conftest.py PROBES) run
it between two steps.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.context import get_context
from otterdog_e2e.scenarios.collect import generate_scenario_tests

if TYPE_CHECKING:
    from otterdog_e2e.scenarios.model import Scenario

SCENARIO_DIRS = ("cli", "regressions")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize ``scenario`` with the scenarios of scenarios/cli and scenarios/regressions."""
    root = get_context(metafunc.config).settings.scenarios_dir
    generate_scenario_tests(metafunc, [root / name for name in SCENARIO_DIRS])


def test_cli_scenario(scenario: Scenario, run_scenario: Callable[[Scenario], None]) -> None:
    """Run one live CLI scenario end to end (skips when the target lacks a capability or plan)."""
    run_scenario(scenario)
