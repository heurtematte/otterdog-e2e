"""Offline tier: every YAML scenario of scenarios/offline against the SUT CLI (SPEC 12.3, 12.4, 19).

OfflineEngine runs, per step, validate --local, local-plan --local (steps with base_fragments), show --local and the
step's extra commands on the minimal e2e-offline organization with the SUT's own examples/template vendored. Failures
of the scenario's expectations fail the item with the outcome summary (output tails included). Offline items are
exempt from --e2e-tags: the offline regression tier always runs in full (selection still honours --e2e-scenario).

Some behaviour legitimately depends on the SUT's history (a fix that is in some SUTs and not in others). Such steps
leave the varying expectation out of the YAML and SUT_EXPECTATIONS asserts the outcome that matches the SUT under
test, decided by the ancestry of the fix commit in the upstream mirror (conftest.SutHistory). A known upstream defect
detected that way is reported as an expected failure (pytest.xfail) and the item passes again once it is fixed.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

import pytest

from otterdog_e2e.context import get_context
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.runner import CliResult
from otterdog_e2e.scenarios.collect import generate_scenario_tests
from otterdog_e2e.scenarios.engine import ScenarioOutcome, StepOutcome
from otterdog_e2e.scenarios.model import Scenario
from otterdog_e2e.scenarios.offline import OfflineEngine
from otterdog_e2e.sut.template import PUBLISHED_TEMPLATE_FILE

# eclipse-csi/otterdog#790 "fix: validate required status checks of rulesets" (squash commit on main)
FIX_790 = "9bdeb75f3e82a6cbd107d6bc3c9ec90392475c08"
MISSING_STRICT = "has not set required parameter 'required_status_checks.strict'."
PLANNING_ABORTED = "Planning aborted due to validation errors"
# #790 validates org rulesets with the organization as parent object, which has no get_model_header (upstream defect)
ORG_RULESET_CRASH = "object has no attribute 'get_model_header'"


class History(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when undecidable."""


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One ``test_offline_scenario`` item per scenarios/offline/*.yaml (marks from collect.scenario_marks)."""
    scenarios_dir = get_context(metafunc.config).settings.scenarios_dir
    generate_scenario_tests(metafunc, [scenarios_dir / "offline"], tier="offline")


@pytest.mark.timeout(1800)  # the first offline item installs (or builds the image of) the SUT
def test_sut_template_can_be_vendored(template_src: Path) -> None:
    """The SUT ships the example template every offline scenario vendors (and is installed before the scenarios)."""
    assert (template_src / PUBLISHED_TEMPLATE_FILE).stat().st_size > 0
    assert sorted(path.name for path in template_src.glob("*.libsonnet")), f"no *.libsonnet in {template_src}"


def test_offline_scenario(scenario: Scenario, offline_engine: OfflineEngine, sut_history: History) -> None:
    """Run one offline scenario; then the SUT-dependent expectations of its steps (SUT_EXPECTATIONS)."""
    outcome = offline_engine.run(scenario)
    if outcome.skipped:
        pytest.skip(outcome.skipped)
    outcome.raise_for_failures()
    for check in SUT_EXPECTATIONS.get(scenario.id, ()):
        check(outcome, sut_history)


# --- SUT-dependent expectations -------------------------------------------------------------------------------------
def step_outcome(outcome: ScenarioOutcome, name: str) -> StepOutcome:
    """The StepOutcome named ``name`` (AssertionError when the step did not run)."""
    for step in outcome.steps:
        if step.name == name:
            return step
    raise AssertionError(f"step {name!r} of {outcome.scenario} did not run (steps: {[s.name for s in outcome.steps]})")


def result_of(step: StepOutcome, command: str) -> CliResult:
    """The CliResult of ``command`` in a step (AssertionError when it did not run)."""
    result = step.results.get(command)
    if result is None:
        raise AssertionError(f"step {step.name!r} did not run {command} (ran: {sorted(step.results)})")
    return result


def tail(result: CliResult, lines: int = 25) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


def has_commit(history: History, commit: str, what: str) -> bool | None:
    """history.contains(commit); a warning when the mirror cannot decide (the check then accepts both behaviours)."""
    found = history.contains(commit)
    if found is None:
        warnings.warn(f"cannot tell whether {history.label} contains {what} ({commit[:7]})", stacklevel=2)
    return found


def expect_ruleset_strict(outcome: ScenarioOutcome, history: History) -> None:
    """O-VAL-RULESET-STRICT step no-strict: SUTs containing #790 refuse the ruleset at validation (and local-plan
    aborts); older SUTs validate it and plan the repository and its ruleset."""
    step = step_outcome(outcome, "no-strict")
    validate, local_plan = result_of(step, "validate"), result_of(step, "local-plan")
    validation, plan = validate.validation(), local_plan.plan()
    has_fix = has_commit(history, FIX_790, "#790")
    if has_fix is None:  # either behaviour, but a refusal must be the #790 error
        if not validation.ok:
            assert MISSING_STRICT in normalize_text(validate.output), tail(validate)
        return
    if has_fix:
        assert not validation.ok and validation.errors == 1, (
            f"{history.label} contains #790 ({FIX_790[:7]}): validate must report the missing 'strict' as 1 error, "
            f"got ok={validation.ok} errors={validation.errors}\n{tail(validate)}"
        )
        assert MISSING_STRICT in normalize_text(validate.output), tail(validate)
        assert validate.exit_code != 0, f"validate exited 0 despite the validation error\n{tail(validate)}"
        assert PLANNING_ABORTED in normalize_text(local_plan.output), tail(local_plan)
        assert plan.add is None, f"local-plan printed a Plan: line despite the validation error\n{tail(local_plan)}"
        return
    assert validation.ok, (
        f"{history.label} does not contain #790 ({FIX_790[:7]}): the ruleset passes validation there, got "
        f"errors={validation.errors}\n{tail(validate)}"
    )
    assert MISSING_STRICT not in normalize_text(validate.output), tail(validate)
    assert (plan.add, plan.change, plan.delete) == (2, 0, 0), (
        f"local-plan must add the repository and its ruleset\n{tail(local_plan)}"
    )


def expect_org_ruleset_strict(outcome: ScenarioOutcome, history: History) -> None:
    """O-VAL-ORG-RULESET-STRICT: without #790 the org ruleset validates; with it the missing 'strict' must be a
    validation error, and the AttributeError crash of current SUTs is an expected failure (known upstream defect)."""
    validate = result_of(step_outcome(outcome, "org-no-strict"), "validate")
    validation, text = validate.validation(), normalize_text(validate.output)
    has_fix = has_commit(history, FIX_790, "#790")
    if has_fix is False:
        assert validation.ok, f"{history.label} predates #790: the org ruleset validates there\n{tail(validate)}"
        return
    if ORG_RULESET_CRASH in text:
        pytest.xfail(
            "known otterdog defect since #790: validating an org ruleset without required_status_checks.strict "
            f"crashes ({ORG_RULESET_CRASH}, exit {validate.exit_code}) instead of reporting the missing parameter"
        )
    if has_fix:
        assert not validation.ok and MISSING_STRICT in text, (
            f"{history.label} contains #790: the missing 'strict' of the org ruleset must be a validation error\n"
            f"{tail(validate)}"
        )


SUT_EXPECTATIONS: dict[str, tuple[Callable[[ScenarioOutcome, History], None], ...]] = {
    "O-VAL-RULESET-STRICT": (expect_ruleset_strict,),
    "O-VAL-ORG-RULESET-STRICT": (expect_org_ruleset_strict,),
}
