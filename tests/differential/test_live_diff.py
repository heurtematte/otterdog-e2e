"""Differential tier, live part (SPEC 12.3 F6, 19: D-LIVE-PLAN): base vs head plans of selected live scenarios.

Every live scenario (scenarios/cli, scenarios/regressions, scenarios/enterprise) with ``observe: true`` runs through
DifferentialRunner.observe_live: per step, the configuration is rendered with each side's own template, then
``validate`` and ``plan -n`` run with the base SUT, then with the head SUT. Nothing is ever applied and nothing needs
a cleanup: step k plans against an organization without the objects of the earlier steps. The observations go to
observations/{base,head}.jsonl next to the offline ones, so the session's differential report and the PR manifest
check of test_offline_diff.py cover both.

Items are live and differential: they need --e2e-target and --e2e-base-sut (skipped at collection otherwise), and
the plugin gates them on the scenario's requires/plan/identities marks before any fixture runs. Like the offline
recording items, they fail only when the observations are meaningless (an exception of the runner, or a side
that recorded nothing). Base and head may legitimately differ, and the report shows how.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.context import SutPair, get_context
from otterdog_e2e.observe import load_observations
from otterdog_e2e.scenarios.collect import collect_scenarios, scenario_params
from otterdog_e2e.scenarios.engine import DifferentialRunner
from otterdog_e2e.sut.template import TEMPLATE_SOURCE_DIR

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.scenarios.model import Scenario

LIVE_SCENARIO_DIRS = ("cli", "regressions", "enterprise")


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One recording item per live scenario with ``observe: true`` (marks from collect.scenario_marks: live, ...)."""
    if "scenario" not in metafunc.fixturenames:
        return
    root = get_context(metafunc.config).settings.scenarios_dir
    observed = [s for s in collect_scenarios([root / name for name in LIVE_SCENARIO_DIRS]) if s.observe]
    metafunc.parametrize("scenario", scenario_params(observed))


@pytest.fixture
def live_runner(sut_pair: SutPair, e2e: E2EContext) -> DifferentialRunner:
    """DifferentialRunner over the live sides: each side renders with its own template and the session's names."""
    runner = DifferentialRunner(
        base=sut_pair.base,
        head=sut_pair.head,
        renderer_factory=lambda side: e2e.renderer(side.template),
        template_src_for=lambda side: side.installed.sut.source_dir / TEMPLATE_SOURCE_DIR,
    )
    runner.run_ctx = e2e.run_ctx
    runner.variables = e2e.scenario_variables()
    return runner


def test_live_scenario_observed(scenario: Scenario, live_runner: DifferentialRunner) -> None:
    """Validate and plan every step of one live scenario on base then head (never apply); both sides recorded."""
    live_runner.observe_live(scenario)
    for side in live_runner.sides:
        recorded = [o for o in load_observations(side.recorder.out_file) if o.scenario == scenario.id]
        assert recorded, f"{side.role} SUT {side.installed.sut.label} recorded nothing for {scenario.id}"
