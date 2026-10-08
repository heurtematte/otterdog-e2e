"""Scenario lint: every step of every live scenario validated offline with the SUT CLI (no GitHub, no target).

Each step of scenarios/cli and scenarios/enterprise is rendered for the offline organization ``e2e-offline`` (its
description carries the safety marker; plan = ``variables.plan``, else the scenario's ``min_plan``) with the SUT's
own examples/template vendored, then checked with ``validate --local`` through the same
machinery as the offline tier (OfflineEngine variables and renderer, offline OtterdogCli: dummy token, no network).
Broken jsonnet, misplaced or misspelled fields (otterdog's "ignoring unknown properties" warning), bad library or
fragment files and wrong expectations show up here, before any live run.

Expectations: a step whose ``validate.ok`` is false or whose ``plan.expect`` is ``validation_error`` must produce
validation errors, reported as such: a printed summary with at least one error or a schema violation; a crash
(traceback, AttributeError) or a configuration that does not load is a lint failure (BAT-09). Every other step must
validate (warnings are fine; the offline org has no baseline repositories or teams, so live-only facts are not
checked). Steps declaring teams are linted without their ``teams`` fragments when they expect to validate (otterdog
lists the org members as soon as a team exists, a GitHub call even with --local): the rest of the step is still
checked. Not linted, skipped with the reason: steps expecting a validation error that use teams, steps using
code_scanning_default_languages or newTeam outside a teams fragment, and scenarios whose ``fixed_in`` the SUT
predates.

A mismatch is an expected failure (xfail with the bug, the step's own first) only when a known bug the SUT has covers
the validate phase: the step's own ``known_bug`` (unless its ``phases`` leave validate out), else a bug of the
scenario. Unknown-property warnings (typos, misplaced fragments) are never expected failures, and a crash only when
that bug documents it (its ``crash_signature`` appears in the output, e.g. KB-008 on SUTs with #790). The items
carry no scenario mark, so the known bugs of their scenarios never turn a clean lint into an XPASS.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

import pytest

from otterdog_e2e.context import E2EContext, get_context
from otterdog_e2e.known_bugs import KnownBug, bugs_for_scenario
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
from otterdog_e2e.scenarios.collect import collect_scenarios
from otterdog_e2e.scenarios.engine import (
    fixed_in_skip_reason,
    step_bug,
    unknown_properties_expected,
    validation_problems,
)
from otterdog_e2e.scenarios.model import Scenario, StepSpec, ValidateSpec, offline_problems, render_step
from otterdog_e2e.scenarios.offline import OfflineEngine, offline_run_context
from otterdog_e2e.sut.cli_install import InstalledCli

LIVE_DIRS = ("cli", "enterprise")
TAIL_LINES = 25
CRASH_MARKERS = ("Traceback (most recent call last)", "object has no attribute")
CRASH_PROBLEM_PREFIX = "otterdog crashed"
SCHEMA_ERROR_MARKER = "Failed validating '"  # a jsonschema violation: otterdog reports it as a validation error
TEAM_BLOCKERS = frozenset({"teams fragments", "newTeam"})


@dataclass(frozen=True)
class LintCase:
    """One step of one live scenario."""

    scenario: Scenario
    step: StepSpec


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One ``test_live_scenario_lint[<scenario id>/<step>]`` item per step of every live scenario."""
    if "lint_case" not in metafunc.fixturenames:
        return
    root = get_context(metafunc.config).settings.scenarios_dir
    scenarios = collect_scenarios([root / name for name in LIVE_DIRS])
    cases = [
        pytest.param(LintCase(scenario, step), id=f"{scenario.id}/{step.name}")
        for scenario in scenarios
        for step in scenario.steps
    ]
    metafunc.parametrize("lint_case", cases)


def lint_plan(scenario: Scenario) -> str:
    """The plan the step is validated with: ``variables.plan``, else the scenario's ``min_plan``."""
    return scenario.plan_override or scenario.min_plan


def expects_validation_errors(step: StepSpec) -> bool:
    """True when the step asserts that validation fails (``validate.ok`` false or ``plan.expect`` validation_error)."""
    if step.validate is not None and step.validate.ok is False:
        return True
    return step.plan is not None and step.plan.expect == "validation_error"


def affecting_bug(
    context: E2EContext, scenario: Scenario, step: StepSpec, sut_version: str | None
) -> tuple[str, KnownBug | None] | None:
    """(xfail reason, bug) of the first known bug the SUT still has that covers validation: the step's own
    ``known_bug`` (engine.step_bug; a bug whose ``phases`` leave validate out makes the lint strict), then the
    scenario's bugs; an id missing from known_bugs.yaml counts as affecting (like the plugin's collection xfail), with
    no bug object; None without one."""
    bugs = context.known_bugs()
    own = step_bug(step, bugs, sut_version)
    if own is not None:
        return (f"{own.reason} (step {step.name!r})", bugs.get(own.id)) if own.covers("validate") else None
    if scenario.known_bug is not None and scenario.known_bug not in bugs:
        return f"{scenario.known_bug}: not listed in known_bugs.yaml", None
    declared = scenario.known_bug
    affecting = [bug for bug in bugs_for_scenario(bugs, scenario.id, declared=declared) if bug.affects(sut_version)]
    return (affecting[0].xfail_reason, affecting[0]) if affecting else None


def affecting_bug_reason(
    context: E2EContext, scenario: Scenario, step: StepSpec, sut_version: str | None
) -> str | None:
    """xfail reason of affecting_bug, None without one."""
    found = affecting_bug(context, scenario, step, sut_version)
    return found[0] if found else None


def lint_fragments(step: StepSpec, fragments: ConfigFragments) -> tuple[ConfigFragments | None, str | None]:
    """(fragments to lint, note) of a rendered step: the step's own fragments, without its ``teams`` fragments when
    they are the only GitHub-calling construct of a step that expects to validate; (None, skip reason) when the step
    cannot be linted offline."""
    blockers = offline_problems(fragments)
    if not blockers:
        return fragments, None
    if fragments.teams and set(blockers) <= TEAM_BLOCKERS and not expects_validation_errors(step):
        stripped = dataclasses.replace(fragments, teams=[])
        if not offline_problems(stripped):
            return stripped, "linted without its teams fragments (team validation lists the org members on GitHub)"
    return None, f"not linted offline ({', '.join(blockers)}): their validation calls GitHub even with --local"


def error_report_problems(result: CliResult) -> list[str]:
    """Why the output of a step expecting validation errors does not report them as validation errors: a crash, a
    configuration that does not load (other than a schema violation) or no printed error at all (BAT-09)."""
    output = result.output
    crash = [marker for marker in CRASH_MARKERS if marker in output]
    if crash:
        return [
            f"{CRASH_PROBLEM_PREFIX} instead of reporting validation errors ({crash[0]!r}, exit {result.exit_code})"
        ]
    parsed = result.validation()
    if SCHEMA_ERROR_MARKER in output:
        return []
    if parsed.load_error:
        return ["the configuration does not load (broken jsonnet?) instead of failing validation"]
    if not parsed.errors:
        return [f"no validation error reported (exit {result.exit_code}, errors {parsed.errors})"]
    return []


def test_live_scenario_lint(
    lint_case: LintCase,
    offline_cli: OtterdogCli,
    template_src: Path,
    sut: InstalledCli,
    offline_context: E2EContext,
) -> None:
    """validate --local of one rendered live step: errors exactly when the step expects a validation error."""
    scenario, step = lint_case.scenario, lint_case.step
    reason = fixed_in_skip_reason(scenario, sut.sut.version)
    if reason:
        pytest.skip(reason)
    engine = OfflineEngine(
        cli=offline_cli,
        workspace=offline_cli.workspace,
        template_src=template_src,
        run_ctx=offline_run_context(),
        variables={"plan": lint_plan(scenario)},
    )
    engine.prepare()
    rendered = render_step(step, engine.variables_for(scenario))
    fragments, note = lint_fragments(step, rendered.fragments)
    if fragments is None:
        pytest.skip(note)
    config = engine.renderer_for(scenario).render(fragments, plan=engine.plan_for(scenario))
    offline_cli.workspace.write_org_config(config)
    result = offline_cli.validate(local=True)
    expected = ValidateSpec(ok=not expects_validation_errors(step))
    unknown_ok = unknown_properties_expected(rendered)
    problems = validation_problems(expected, result, unknown_ok=unknown_ok)
    strict = [problem for problem in problems if problem.startswith("otterdog ignored unknown properties")]
    if expects_validation_errors(step):
        strict += error_report_problems(result)
    if not problems and not strict:
        return
    summary = "; ".join(dict.fromkeys([*problems, *strict]))
    crashes = [problem for problem in strict if problem.startswith(CRASH_PROBLEM_PREFIX)]
    found = affecting_bug(offline_context, scenario, step, sut.sut.version)
    if found is not None and len(crashes) == len(strict):
        reason, bug = found
        # unknown properties, unloadable configs and silent validations stay failures; a crash only with its bug
        if not crashes or (bug is not None and bug.explains_crash(result.output)):
            pytest.xfail(f"{reason} ({summary})")
    tail = "\n".join(normalize_text(result.output).splitlines()[-TAIL_LINES:])
    pytest.fail(
        f"{scenario.id} step {step.name!r} (plan {lint_plan(scenario)}, {scenario.source}): {summary}"
        f"{f' [{note}]' if note else ''}\nvalidate --local output (last {TAIL_LINES} lines):\n{tail}",
        pytrace=False,
    )
