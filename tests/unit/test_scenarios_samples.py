"""Engine expectations on REAL otterdog 1.7.0.dev19 output (tests/unit/data golden samples, real parsers).

The samples were rendered with run id t3c7z8a5 (testing.fakes.FAKE_RUN_ID), so RunContext.needles() select the
scenario's own objects exactly as in a live run.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.capabilities import from_plan
from otterdog_e2e.otterdog.output import parse_plan
from otterdog_e2e.otterdog.runner import CliResult, infra_error_line
from otterdog_e2e.scenarios.engine import (
    ScenarioEngine,
    ScenarioFailedError,
    apply_problems,
    classify_apply,
    classify_plan,
    filtered_counts,
    infra_problems,
    plan_problems,
    relevant_objects,
    unknown_properties_problem,
    validation_problems,
)
from otterdog_e2e.scenarios.model import ApplySpec, PlanSpec, ValidateSpec, load_scenario
from otterdog_e2e.testing.fakes import FakeCli, FakeOracle, make_run_context

DATA = Path(__file__).parent / "data"
RUN = make_run_context()
NEEDLES = RUN.needles()


@cache
def samples() -> dict[str, Any]:
    """samples.json (case -> argv, exit code, ...)."""
    return json.loads((DATA / "samples.json").read_text())


def sample(name: str) -> CliResult:
    """The CliResult OtterdogCli would have returned for a sample (infra_error as the runner computes it)."""
    stdout = (DATA / f"{name}.txt").read_text()
    exit_code = int(samples()[name]["exit_code"])
    return CliResult(["otterdog", name], exit_code, stdout, "", 0.1, DATA, infra_error=infra_error_line(stdout))


PLAN_SAMPLES = sorted(name for name in samples() if name.startswith(("local-plan-", "plan-")))


@pytest.mark.parametrize("name", [n for n in PLAN_SAMPLES if parse_plan(sample(n).output).add is not None])
def test_filtered_counts_reproduce_otterdog_plan_counts(name: str) -> None:
    """Recounting all objects (change = changed non-read-only keys) gives otterdog's own ``Plan:`` numbers."""
    plan = parse_plan(sample(name).output)
    assert filtered_counts(plan.objects) == {"add": plan.add, "change": plan.change, "delete": plan.delete}


@pytest.mark.parametrize(
    ("name", "live", "offline"),
    [
        ("local-plan-add", "changes", "changes"),
        ("local-plan-change", "changes", "changes"),
        ("local-plan-remove", "changes", "changes"),
        ("local-plan-forced", "changes", "changes"),
        ("local-plan-noop", "noop", "noop"),
        ("local-plan-readonly", "noop", "noop"),
        ("local-plan-cache-limit-hidden", "noop", "noop"),
        ("local-plan-description-removed", "noop", "changes"),
        ("local-plan-unknown-property", "noop", "noop"),
        ("local-plan-validation-error", "validation_error", "validation_error"),
        ("plan-validation-error", "validation_error", "validation_error"),
        ("local-plan-missing-base", "error", "error"),
        ("plan-network", "error", "error"),
    ],
)
def test_plan_classification(name: str, live: str, offline: str) -> None:
    """Live (this run's objects) and offline (everything) classification of real plans."""
    result = sample(name)
    plan = parse_plan(result.output)
    assert classify_plan(result, plan, relevant_objects(plan, NEEDLES), unfiltered=False) == live
    assert classify_plan(result, plan, relevant_objects(plan, None), unfiltered=True) == offline


def test_org_level_scenarios_see_settings_changes() -> None:
    """org_level adds the settings object: a settings change is a change, its read-only plan note is not."""
    removed = sample("local-plan-description-removed")
    plan = parse_plan(removed.output)
    assert classify_plan(removed, plan, relevant_objects(plan, NEEDLES, org_level=True), unfiltered=False) == "changes"
    readonly = sample("local-plan-readonly")
    plan = parse_plan(readonly.output)
    assert classify_plan(readonly, plan, relevant_objects(plan, NEEDLES, org_level=True), unfiltered=False) == "noop"


def test_counts_of_this_run_when_the_plan_has_foreign_changes() -> None:
    """local-plan-change also changes a fixture repo and org settings: counts are recomputed on run objects."""
    result = sample("local-plan-change")
    plan = parse_plan(result.output)
    spec = PlanSpec(expect="changes", counts={"change": 8})
    assert plan_problems(spec, result, plan, needles=NEEDLES) == []
    assert plan_problems(PlanSpec(counts={"change": 10}), result, plan, needles=None) == []  # offline: raw numbers


def test_plan_expectations_on_real_output() -> None:
    """contains on normalized output, validation errors, network errors as infra."""
    added = sample("local-plan-add")
    spec = PlanSpec(contains=[f'+ add repository[name="{RUN.prefix}-basic"]'], counts={"add": 10})
    assert plan_problems(spec, added, parse_plan(added.output), needles=NEEDLES) == []
    invalid = sample("local-plan-validation-error")
    expect_invalid = PlanSpec(expect="validation_error", contains=["Planning aborted due to validation errors"])
    assert plan_problems(expect_invalid, invalid, parse_plan(invalid.output), needles=NEEDLES) == []
    assert infra_problems(sample("plan-network"))[0].startswith("[infra] ")


def test_unknown_properties_on_real_output() -> None:
    """The logger warning fails a step unless expected; the message drops RichHandler's file:line column."""
    result = sample("validate-unknown-property")
    problem = unknown_properties_problem(result, expected=False)
    assert problem is not None and "ignoring unknown properties" in problem and ".py:" not in problem
    assert unknown_properties_problem(result, expected=True) is None
    assert validation_problems(ValidateSpec(ok=True), result) == [problem]
    assert unknown_properties_problem(sample("local-plan-unknown-property"), expected=False) is not None


@pytest.mark.parametrize(
    ("name", "spec", "ok"),
    [
        ("validate-ok", ValidateSpec(ok=True), True),
        ("validate-errors", ValidateSpec(ok=False, errors=3), True),
        ("validate-errors", ValidateSpec(ok=True), False),
        ("validate-syntax", ValidateSpec(ok=False, contains=["failed to load configuration"]), True),
        ("validate-plan-gate", ValidateSpec(ok=False, errors=1), True),
        ("validate-790", ValidateSpec(ok=False), True),
        ("validate-warnings", ValidateSpec(ok=True, warnings_min=1), True),
        ("validate-infos-hidden", ValidateSpec(ok=True), True),
        ("validate-network", ValidateSpec(ok=True), False),
    ],
)
def test_validation_expectations_on_real_output(name: str, spec: ValidateSpec, ok: bool) -> None:
    """ok/errors/warnings/contains against real validate outputs."""
    assert (validation_problems(spec, sample(name)) == []) is ok


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("apply-executed", "ok"),
        ("apply-executed-ignored", "ok"),
        ("local-apply-no-changes", "ok"),
        ("apply-failed-patch", "error"),
        ("apply-validation-error", "validation_error"),
        ("apply-network", "error"),
        ("local-apply-network", "error"),
    ],
)
def test_apply_classification_on_real_output(name: str, expected: str) -> None:
    """apply ok semantics, including the validation abort that exits 0 upstream (known bug)."""
    result = sample(name)
    assert classify_apply(result, result.apply()) == expected
    assert (apply_problems(ApplySpec(expect=expected), result, result.apply()) == []) is True


def test_real_description_removal_is_never_applied(tmp_path: Path) -> None:
    """The live engine refuses to apply a real plan that removes the org description (safety marker)."""
    path = tmp_path / "cli" / "desc.yaml"
    path.parent.mkdir()
    path.write_text("id: desc\ntitle: desc\norg_level: true\nsteps: [{fragments: {}}]\n")
    cli = FakeCli(strict=True, workspace=type("W", (), {"write_org_config": lambda self, text: None})())
    cli.queue("plan", sample("local-plan-description-removed"))
    baseline = type(
        "B",
        (),
        {"reset": lambda self: None, "calls": [], "run_objects_left": False, "check_changes": lambda self, p: None},
    )()
    engine = ScenarioEngine(
        cli=cli,  # type: ignore[arg-type]
        renderer=type("R", (), {"render": lambda self, fragments=None, **kw: "{}"})(),  # type: ignore[arg-type]
        oracle=FakeOracle(),  # type: ignore[arg-type]
        run_ctx=RUN,
        capabilities=from_plan("free"),
        baseline=baseline,  # type: ignore[arg-type]
        variables={},
        sleep=lambda seconds: None,
    )
    with pytest.raises(ScenarioFailedError, match="refusing to apply a plan that changes the org description"):
        engine.run(load_scenario(path))
    assert [call.command for call in cli.calls] == ["plan"]
