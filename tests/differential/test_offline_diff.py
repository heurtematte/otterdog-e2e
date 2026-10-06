"""Differential tier, offline part (SPEC 12.3 F6, 19: D-OFFLINE): base vs head on every observed offline scenario.

Every scenarios/offline/*.yaml with ``observe: true`` runs through DifferentialRunner.observe_offline: the base SUT
(--e2e-base-sut, ``auto`` = merge base of the SUT) then the head SUT (--e2e-sut) render the same steps (deterministic
offline run context) and record every command's normalized output into observations/{base,head}.jsonl; the plugin
compares both files at session end into differential.{md,json} (--e2e-strict-diff fails the session on unexpected
deltas). With a change under test (--e2e-change or E2E_CHANGE, default: N of a pr:N@<sha> SUT), the ``template`` of
the references of the scenarios referencing it picks the template both sides vendor (own: each SUT its own
examples/template; head/base: both use that side's) and test_change_expected_deltas_observed, the last item of the
module, checks that every expected delta of a scenario recorded on both sides was observed.

A recording item fails only when its observations are meaningless: infrastructure problems (timeouts, sandbox or
network errors) or harness problems (template vendoring, rendering). Scenario expectations are NOT asserted here:
base and head legitimately differ, the offline tier asserts the head SUT and the report shows the differences.
"""

from __future__ import annotations

import fnmatch
import logging
import warnings
from collections.abc import Callable
from pathlib import Path

import pytest

from otterdog_e2e.changes import ChangeSpec
from otterdog_e2e.context import SutPair, get_context
from otterdog_e2e.differential import compare
from otterdog_e2e.observe import load_observations
from otterdog_e2e.scenarios.collect import collect_scenarios, scenario_params
from otterdog_e2e.scenarios.engine import INFRA_PREFIX, DifferentialRunner, ScenarioOutcome, SutSide
from otterdog_e2e.scenarios.model import Scenario
from otterdog_e2e.selection import SCENARIO_TAGS
from otterdog_e2e.sut.template import PUBLISHED_TEMPLATE_FILE, TEMPLATE_SOURCE_DIR

logger = logging.getLogger(__name__)

# failures of these phases are harness or infrastructure problems: the recorded observations cannot be compared
HARNESS_PHASES = (" prepare: ", " render: ")
# the differential tier is tag-filtered (otterdog-e2e pr always passes --e2e-tags): the session-wide items carry every
# tag so they are selected whenever a recording item can be
EVERY_TAG = pytest.mark.tags(*SCENARIO_TAGS)


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One recording item per offline scenario with ``observe: true`` (marks from collect.scenario_marks)."""
    if "scenario" not in metafunc.fixturenames:
        return
    scenarios_dir = get_context(metafunc.config).settings.scenarios_dir
    observed = [s for s in collect_scenarios([scenarios_dir / "offline"], tier="offline") if s.observe]
    metafunc.parametrize("scenario", scenario_params(observed))


def template_dir(side: SutSide) -> Path:
    """examples/template of a side's SUT source."""
    return side.installed.sut.source_dir / TEMPLATE_SOURCE_DIR


def template_chooser(pair: SutPair, change: ChangeSpec | None) -> Callable[[SutSide], Path]:
    """template_src_for of the runner: each side's own template, or the side the change's ``template`` names."""
    mode = change.template if change is not None else "own"
    if mode == "own":
        return template_dir
    chosen = template_dir(pair.head if mode == "head" else pair.base)
    return lambda side: chosen


@pytest.fixture
def runner(sut_pair: SutPair, change_spec: ChangeSpec | None) -> DifferentialRunner:
    """DifferentialRunner over the offline sides (deterministic offline run context, templates per change).

    Each side's workspace root (and the container mount point of a docker side) is already a placeholder in its
    observations (context.workspace_literals), so printed config paths compare equal across sides.
    """
    return DifferentialRunner(
        base=sut_pair.base,
        head=sut_pair.head,
        renderer_factory=None,
        template_src_for=template_chooser(sut_pair, change_spec),
    )


@EVERY_TAG
@pytest.mark.timeout(3600)  # first differential item: resolves and installs both SUTs (or builds their images)
def test_sides_are_ready(sut_pair: SutPair, change_spec: ChangeSpec | None) -> None:
    """Both SUTs are installed, ship the example template and record into their own observation files."""
    for side in sut_pair:
        source = template_dir(side)
        assert (source / PUBLISHED_TEMPLATE_FILE).is_file(), f"{side.role} SUT {side.installed.sut.label}: no {source}"
        assert side.recorder.role == side.role and side.recorder.out_file.name == f"{side.role}.jsonl"
    base, head = sut_pair.base.installed.sut, sut_pair.head.installed.sut
    if base.sha == head.sha and not (base.is_dirty or head.is_dirty):
        warnings.warn(f"base and head are the same commit {head.sha[:12]}: no delta is expected", stacklevel=1)
    logger.info("differential: base %s (%s) vs head %s (%s)", base.label, base.sha[:12], head.label, head.sha[:12])
    if change_spec is not None:
        logger.info(
            "change %s: %d referencing scenario(s), %d expected delta(s), base %s, template %s",
            change_spec.label, len(change_spec.scenarios), len(change_spec.expected_deltas), change_spec.base or "-",
            change_spec.template,
        )  # fmt: skip


def harness_problems(outcome: ScenarioOutcome) -> list[str]:
    """Failures that make the recorded observations meaningless (infrastructure, vendoring, rendering)."""
    return [
        failure
        for failure in outcome.failures
        if INFRA_PREFIX in failure or failure.startswith("prepare:") or any(p in failure for p in HARNESS_PHASES)
    ]


def test_offline_scenario_observed(
    scenario: Scenario, runner: DifferentialRunner, record_property: Callable[[str, object], None]
) -> None:
    """Record one scenario on base then head (never asserting its expectations, see the module docstring)."""
    runner.observe_offline(scenario)
    outcomes = runner.outcomes[scenario.id]
    problems = {role: harness_problems(outcome) for role, outcome in outcomes.items()}
    for role, outcome in outcomes.items():
        record_property(f"{role}_expectation_failures", len(outcome.failures))
        if outcome.failures:
            logger.info("%s: %s expectations not met:\n%s", scenario.id, role, "\n".join(outcome.failures))
    assert set(outcomes) == {"base", "head"}, f"recorded sides: {sorted(outcomes)}"
    failing = {role: found for role, found in problems.items() if found}
    assert not failing, "observations not comparable:\n" + "\n".join(
        f"{role}: {problem}" for role, found in failing.items() for problem in found
    )


@EVERY_TAG
def test_change_expected_deltas_observed(sut_pair: SutPair, change_spec: ChangeSpec | None) -> None:
    """Every expected delta of the change under test (references of its scenarios) whose scenario was recorded on
    both sides shows up as a delta (``expected deltas not observed`` would mean the change does not change what its
    references claim)."""
    if change_spec is None:
        pytest.skip("no change under test (--e2e-change / E2E_CHANGE, or a pr:N@<sha> SUT)")
    base_file, head_file = sut_pair.base.recorder.out_file, sut_pair.head.recorder.out_file
    base, head = load_observations(base_file), load_observations(head_file)
    comparable = {o.scenario for o in base} & {o.scenario for o in head}
    applicable = [
        expected
        for expected in change_spec.expected_deltas
        if any(fnmatch.fnmatchcase(scenario, expected.scenario) for scenario in comparable)
    ]
    if not applicable:
        pytest.skip(f"no expected delta of change {change_spec.label} concerns a scenario recorded in this session")
    report = compare(
        base,
        head,
        base_label=sut_pair.base.installed.sut.label,
        head_label=sut_pair.head.installed.sut.label,
        expected=applicable,
    )
    missing = report.unmatched_expected
    assert not missing, (
        f"change {change_spec.label}: expected delta(s) not observed between {report.base_label} and "
        f"{report.head_label}: "
        + "; ".join(f"{item.label()} ({item.note})" if item.note else item.label() for item in missing)
    )
    logger.info(
        "change %s: %d expected delta(s) observed, %d unexpected", change_spec.label, len(report.expected()),
        len(report.unexpected()),
    )  # fmt: skip
