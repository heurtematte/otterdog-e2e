"""Live ScenarioEngine extensions: plan/apply diff options and repo_filter overrides (with their safety rule), converge
with the apply's filter, validate -v and info counts, exit codes, per-step known bugs (expected failures, strict
steps of fixed bugs, unexpected passes, raise_for_failures xfail) and observe_live with the step options."""

from __future__ import annotations

import json
import textwrap
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.capabilities import from_plan
from otterdog_e2e.known_bugs import KnownBug
from otterdog_e2e.otterdog import output as od_output
from otterdog_e2e.otterdog.output import ApplyResult, PlanObject, PlanResult, ValidationResult
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, DiffOptions
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.scenarios.engine import (
    DifferentialRunner,
    KnownBugNotReproducedWarning,
    ScenarioEngine,
    ScenarioFailedError,
    ScenarioOutcome,
    StepBug,
    SutSide,
    filtered_counts,
    known_bugs_near,
    record_phase_problems,
    step_bug,
)
from otterdog_e2e.scenarios.model import Scenario, StepSpec, load_scenario
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli, FakeOracle, FakeWorkspace, make_run_context

RUN = make_run_context()
P = RUN.prefix
VARIABLES: dict[str, Any] = {
    "org": "e2e-test-org",
    "plan": "free",
    "logins": {"admin": "e2e-admin"},
    "app_slug": "otterdog-e2e-app",
    "teams": {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"},
}


@pytest.fixture(autouse=True)
def _plain_normalize_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """normalize_text is an identity (the results below are canned)."""
    monkeypatch.setattr(od_output, "normalize_text", lambda text, ctx=None: text)


@dataclass
class Canned(CliResult):
    """A CliResult whose parsed form is given directly."""

    parsed: Any = None

    def plan(self) -> Any:
        """The canned PlanResult."""
        return self.parsed

    def apply(self) -> Any:
        """The canned ApplyResult."""
        return self.parsed

    def validation(self) -> Any:
        """The canned ValidationResult."""
        return self.parsed


def canned(command: str, parsed: Any = None, *, stdout: str = "", exit_code: int = 0, **kw: Any) -> Canned:
    """A Canned result of ``otterdog <command>``."""
    return Canned(["otterdog", command], exit_code, stdout, "", 0.01, Path("/nonexistent"), parsed=parsed, **kw)


def add(name: str) -> PlanObject:
    """An added repository."""
    return PlanObject("add", "repository", "name", name, None, None, f'+ add repository[name="{name}"] {{', [])


def planned(*objects: PlanObject) -> PlanResult:
    """A PlanResult with the counts of the objects."""
    counts = filtered_counts(list(objects))
    return PlanResult(counts["add"], counts["change"], counts["delete"], list(objects), False, None, [], "")


def validated(ok: bool = True, errors: int = 0, infos: int | None = 0) -> ValidationResult:
    """A ValidationResult."""
    return ValidationResult(ok, infos, 0, errors, [], False, "")


def applied(added: int = 1) -> ApplyResult:
    """A successful ApplyResult."""
    return ApplyResult(added, 0, 0, None, False, False, None, [], [], "")


NOOP = planned()


class FakeBaseline:
    """BaselineManager stand-in."""

    def __init__(self) -> None:
        """Record calls."""
        self.reset_cli = FakeCli(workspace=FakeWorkspace())
        self.calls: list[tuple[Any, ...]] = []
        self.run_objects_left = False

    def text(self) -> str:
        """The baseline config."""
        return "BASELINE"

    def check_changes(self, plan: PlanResult) -> None:
        """Accept every change (recorded apart from ``calls``)."""
        self.changes_checked = [*getattr(self, "changes_checked", []), plan]

    def check_removals(self, plan: PlanResult) -> None:
        """Accept every removal."""
        self.calls.append(("check_removals", plan))

    def guarded_apply(self, cli: Any, *, repo_filter: str | None, delete: bool) -> ApplyResult:
        """Record the cleanup."""
        self.calls.append(("guarded_apply", repo_filter, delete))
        return ApplyResult(0, 0, 0, 0, True, False, 0, [], [], "")

    def reset(self) -> ApplyResult:
        """Record a reset."""
        self.calls.append(("reset",))
        return ApplyResult(0, 0, 0, 0, True, False, 0, [], [], "")


class FakeRenderer:
    """OrgConfigRenderer stand-in."""

    def render(
        self, fragments: ConfigFragments | None = None, *, include_baseline: bool = True, plan: str | None = None
    ) -> str:
        """Serialize the fragments."""
        return json.dumps(fragments.to_mapping() if fragments else None)


@dataclass
class Rig:
    """An engine over fakes."""

    engine: ScenarioEngine
    cli: FakeCli
    oracle: FakeOracle
    baseline: FakeBaseline
    sleeps: list[float]


def rig(*, bugs: dict[str, KnownBug] | None = None) -> Rig:
    """ScenarioEngine over a strict FakeCli (known bugs given explicitly, never read from disk)."""
    cli = FakeCli(workspace=FakeWorkspace(), strict=True)
    oracle, baseline, sleeps = FakeOracle(), FakeBaseline(), []
    engine = ScenarioEngine(
        cli=cli,  # type: ignore[arg-type]
        renderer=FakeRenderer(),  # type: ignore[arg-type]
        oracle=oracle,  # type: ignore[arg-type]
        run_ctx=RUN,
        capabilities=from_plan("free"),
        baseline=baseline,  # type: ignore[arg-type]
        variables=VARIABLES,
        sleep=sleeps.append,
    )
    engine.known_bugs = bugs if bugs is not None else {}
    return Rig(engine, cli, oracle, baseline, sleeps)


def scenario(tmp_path: Path, text: str, name: str = "case") -> Scenario:
    """Load a live scenario written under tmp_path/cli/."""
    path = tmp_path / "cli" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return load_scenario(path)


# --- diff options ----------------------------------------------------------------------------------------------------
OPTIONS = """
id: cli.options
title: options
steps:
  - name: force
    fragments: {repositories: ["orgs.newRepo('{{ p }}-a')"]}
    plan: {repo_filter: "{{ p }}-a", update_secrets: true, update_filter: "{{ P }}_A*", verbose: true}
    apply: {update_webhooks: true, only_secrets: true, verbose: true}
"""


def test_plan_and_apply_options_reach_the_cli_and_converge_uses_the_apply_filter(tmp_path: Path) -> None:
    """The step's flags go to plan/apply; the apply inherits the plan's filter; converge plans with that filter and
    no update flag."""
    r = rig()
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-a"))))
    r.cli.queue("apply", canned("apply", applied()))
    r.cli.queue("plan", canned("plan", NOOP))
    assert r.engine.run(scenario(tmp_path, OPTIONS)).ok
    plan, apply, converge = r.cli.calls
    assert plan.kwargs["options"] == DiffOptions(
        f"{P}-a", update_secrets=True, update_filter=f"{RUN.const_prefix}A*", verbose=True
    )
    assert apply.kwargs["options"] == DiffOptions(f"{P}-a", update_webhooks=True, only_secrets=True, verbose=True)
    assert apply.kwargs["delete"] is False
    assert converge.kwargs["options"] == DiffOptions(f"{P}-a")
    assert r.baseline.calls[-1] == ("guarded_apply", f"{P}-*", True)  # cleanup keeps the run filter


def test_default_filters_are_unchanged(tmp_path: Path) -> None:
    """Without overrides: -r <run>-* for plan, apply and converge; org_level: no filter."""
    r = rig()
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-a"))))
    r.cli.queue("apply", canned("apply", applied()))
    r.cli.queue("plan", canned("plan", NOOP))
    text = "id: d\ntitle: d\nsteps: [{fragments: {}}]\n"
    assert r.engine.run(scenario(tmp_path, text)).ok
    assert [call.kwargs["options"] for call in r.cli.calls] == [DiffOptions(f"{P}-*")] * 3


def test_apply_filter_override_and_its_converge(tmp_path: Path) -> None:
    """apply.repo_filter narrows the apply; converge follows it."""
    r = rig()
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-a"), add(f"{P}-b"))))
    r.cli.queue("apply", canned("apply", applied()))
    r.cli.queue("plan", canned("plan", NOOP))
    text = "id: f\ntitle: f\nsteps: [{fragments: {}, apply: {repo_filter: '{{ p }}-b'}}]\n"
    assert r.engine.run(scenario(tmp_path, text)).ok
    assert [call.kwargs["repo_filter"] for call in r.cli.calls] == [f"{P}-*", f"{P}-b", f"{P}-b"]


def test_a_foreign_filter_never_reaches_otterdog(tmp_path: Path) -> None:
    """The engine re-checks rendered filters with the real run prefix (a variable could change the prefix)."""
    r = rig()
    text = "id: s\ntitle: s\nvariables: {target: x}\nsteps: [{fragments: {}, plan: {repo_filter: '{{ p }}-{{ target }}'}}]\n"
    loaded = scenario(tmp_path, text)
    loaded.steps[0].plan.repo_filter = "other-*"  # what a bad render could produce
    with pytest.raises(ScenarioFailedError, match="plan: SafetyError: repo_filter 'other-\\*' does not start"):
        r.engine.run(loaded)
    assert r.cli.calls == []


def test_a_plan_override_equal_to_the_target_plan_skips(tmp_path: Path) -> None:
    """BAT-16: variables.plan equal to the live plan renders no mismatch: the scenario is skipped (on Team for
    cli.plan-mismatch, which declares plan team), not failed."""
    r = rig()  # capabilities of a free org
    same = "id: m\ntitle: m\nvariables: {plan: free}\nsteps: [{fragments: {}, plan: {expect: noop}}]\n"
    outcome = r.engine.run(scenario(tmp_path, same))
    assert outcome.skipped is not None and "the target's own plan" in outcome.skipped and r.cli.calls == []
    other = "id: n\ntitle: n\nvariables: {plan: team}\nsteps: [{fragments: {}, plan: {expect: noop}}]\n"
    r.cli.queue("plan", canned("plan", NOOP))
    assert r.engine.run(scenario(tmp_path, other, name="other")).skipped is None


def test_org_level_scenarios_may_filter_freely(tmp_path: Path) -> None:
    """org_level: the plan is unfiltered by default and any filter is a narrowing."""
    r = rig()
    r.cli.queue("plan", canned("plan", NOOP))
    text = "id: o\ntitle: o\norg_level: true\nsteps: [{fragments: {}, plan: {expect: noop, repo_filter: '*'}}]\n"
    assert r.engine.run(scenario(tmp_path, text)).ok
    assert r.cli.calls[0].kwargs["repo_filter"] == "*" and r.baseline.calls == [("reset",)]


# --- apply -d guard (DESTR-02) --------------------------------------------------------------------------------------
def remove(name: str) -> PlanObject:
    """A removed repository."""
    return PlanObject("remove", "repository", "name", name, None, None, f'- remove repository[name="{name}"] {{', [])


@pytest.mark.parametrize(
    ("step", "match"),
    [
        ("{plan: {only_secrets: true, update_secrets: true}, apply: {delete: true}}", "differ in: only_secrets"),
        ("{plan: {update_webhooks: true}, apply: {delete: true}}", "differ in: update_webhooks"),
        ("{apply: {delete: true, update_secrets: true}}", "differ in: update_secrets"),
        (
            "{plan: {update_secrets: true, update_filter: 'x*'}, apply: {delete: true, update_secrets: true}}",
            "differ in: update_filter",
        ),
        (
            (
                "{plan: {only_secrets: true, update_secrets: true}, apply: {delete: true, only_secrets: true,"
                " update_secrets: true}}"
            ),
            "cannot be combined with only_secrets",
        ),
    ],
)
def test_deleting_steps_use_the_flags_of_their_plan(tmp_path: Path, step: str, match: str) -> None:
    """The model refuses an apply -d whose diff flags differ from its plan's (the guard checks that plan) and
    only_secrets with delete (a secrets-only plan hides every other removal)."""
    from otterdog_e2e.scenarios.model import ScenarioError

    text = f"id: g\ntitle: g\nsteps: [{{fragments: {{}}, {step[1:-1]}}}]\n"
    with pytest.raises(ScenarioError, match=match):
        scenario(tmp_path, text)


def test_apply_delete_is_guarded_by_a_plan_with_the_apply_flags(tmp_path: Path) -> None:
    """DESTR-02: a deleting apply whose flags differ from the step's plan (a spec built in Python, bypassing the
    model) is guarded by a fresh plan with exactly the apply's options; check_removals sees what -d deletes."""
    r = rig()
    secret = f"{RUN.const_prefix}S"
    forced = PlanObject("forced", "org_secret", "name", secret, None, None, f'! org_secret[name="{secret}"] {{', [])
    secrets_only = planned(forced)  # --only-secrets: the repository removal is not shown
    full = planned(remove(f"{P}-gone"))
    r.cli.queue("plan", canned("plan", secrets_only))
    r.cli.queue("plan", canned("plan", full))
    r.cli.queue("apply", canned("apply", applied(0)))
    r.cli.queue("plan", canned("plan", NOOP))
    loaded = scenario(tmp_path, "id: g\ntitle: g\nsteps: [{fragments: {}, apply: {delete: true}}]\n")
    loaded.steps[0].plan.only_secrets = True  # what the model now refuses
    loaded.steps[0].plan.update_secrets = True
    outcome = r.engine.run(loaded)
    plan, guard, apply, _converge = r.cli.calls
    assert plan.kwargs["options"] == DiffOptions(f"{P}-*", update_secrets=True, only_secrets=True)
    assert guard.kwargs["options"] == apply.kwargs["options"] == DiffOptions(f"{P}-*")
    assert apply.kwargs["delete"] is True
    assert ("check_removals", full) in r.baseline.calls and ("check_removals", secrets_only) not in r.baseline.calls
    assert any("guarded by a plan with the apply's diff flags" in note for note in outcome.steps[0].notes)


def test_every_apply_runs_the_change_guard(tmp_path: Path) -> None:
    """DESTR-07: the baseline's change guard sees the plan of every apply (with or without -d); its refusal stops the
    step before otterdog applies anything."""
    r = rig()
    gone = planned(add(f"{P}-a"))
    r.cli.queue("plan", canned("plan", gone))
    r.cli.queue("apply", canned("apply", applied()))
    r.cli.queue("plan", canned("plan", NOOP))
    assert r.engine.run(scenario(tmp_path, "id: c\ntitle: c\nsteps: [{fragments: {}}]\n")).ok
    assert r.baseline.changes_checked == [gone]

    def refuse(plan: PlanResult) -> None:
        """An extra protected repository would change."""
        raise SafetyError("refusing an apply that changes objects the baseline reset can never restore")

    r = rig()
    r.baseline.check_changes = refuse  # type: ignore[method-assign]
    r.cli.queue("plan", canned("plan", gone))
    with pytest.raises(ScenarioFailedError, match="apply: SafetyError: refusing an apply that changes"):
        r.engine.run(scenario(tmp_path, "id: c\ntitle: c\nsteps: [{fragments: {}}]\n"))
    assert [call.command for call in r.cli.calls] == ["plan"]


def test_leftovers_of_an_earlier_item_are_removed_before_the_scenario(tmp_path: Path) -> None:
    """BAT-06: when the last removal of the run's objects failed, the scenario's cleanup runs first (its plans cover
    the whole run); leftovers that cannot be removed fail it with a message naming them, before any step runs."""
    text = "id: l\ntitle: l\nsteps: [{fragments: {}, plan: {expect: noop}}]\n"
    r = rig()
    r.baseline.run_objects_left = True
    r.cli.queue("plan", canned("plan", NOOP))
    assert r.engine.run(scenario(tmp_path, text)).ok
    assert [call[0] for call in r.baseline.calls] == ["guarded_apply", "guarded_apply"]  # before, then cleanup

    r = rig()
    r.baseline.run_objects_left = True

    def refused(cli: Any, *, repo_filter: str | None, delete: bool) -> ApplyResult:
        """The leftovers belong to no purgeable run (a guard refusal)."""
        raise SafetyError("refusing destructive otterdog apply")

    r.baseline.guarded_apply = refused  # type: ignore[method-assign]
    with pytest.raises(ScenarioFailedError, match="leftovers: objects an earlier item of this run left behind"):
        r.engine.run(scenario(tmp_path, text))
    assert r.cli.calls == []


def test_apply_delete_reuses_the_step_plan_when_the_flags_match(tmp_path: Path) -> None:
    """Same flags (verbose aside): the step's own plan guards the apply, no extra plan."""
    r = rig()
    gone = planned(remove(f"{P}-gone"))
    r.cli.queue("plan", canned("plan", gone))
    r.cli.queue("apply", canned("apply", applied(0)))
    r.cli.queue("plan", canned("plan", NOOP))
    text = "id: g\ntitle: g\nsteps: [{fragments: {}, plan: {verbose: true}, apply: {delete: true}}]\n"
    assert r.engine.run(scenario(tmp_path, text)).ok
    assert [call.command for call in r.cli.calls] == ["plan", "apply", "plan"]
    assert ("check_removals", gone) in r.baseline.calls


# --- validate and exit codes -----------------------------------------------------------------------------------------
def test_validate_verbose_infos_and_exit_codes(tmp_path: Path) -> None:
    """validate -v, info counts and exit codes of validate and plan are checked."""
    r = rig()
    r.cli.queue("validate", canned("validate", validated(infos=1), exit_code=0))
    r.cli.queue("plan", canned("plan", NOOP, exit_code=0))
    text = """
    id: v
    title: v
    steps:
      - fragments: {}
        validate: {verbose: true, infos: 2, exit_code: 1}
        plan: {expect: noop, exit_code: 0}
    """
    with pytest.raises(ScenarioFailedError) as info:
        r.engine.run(scenario(tmp_path, text))
    assert r.cli.calls[0].kwargs["verbose"] is True
    assert info.value.outcome.failures == [
        "step 'step-1' validate: expected exit code 1, got 0",
        "step 'step-1' validate: expected 2 info(s), got 1",
    ]


def test_info_minimum_and_plan_exit_code(tmp_path: Path) -> None:
    """infos_min passes with enough Infos; a plan exit code mismatch is reported."""
    r = rig()
    r.cli.queue("validate", canned("validate", validated(infos=3)))
    r.cli.queue("plan", canned("plan", NOOP, exit_code=0))
    text = "id: m\ntitle: m\nsteps: [{fragments: {}, validate: {verbose: true, infos_min: 2}, plan: {expect: noop, exit_code: 2}}]\n"
    with pytest.raises(ScenarioFailedError, match="plan: expected exit code 2, got 0"):
        r.engine.run(scenario(tmp_path, text))


# --- known bugs per step ---------------------------------------------------------------------------------------------
KB = """
id: cli.kb
title: kb
steps:
  - name: buggy
    known_bug: KB-025
    fragments: {}
    plan: {expect: noop}
  - name: strict
    fragments: {}
    plan: {expect: noop}
"""


def open_bug(status: str = "confirmed", fixed_in: str | None = None) -> KnownBug:
    """KB-025 with a status."""
    return KnownBug("KB-025", "pass:a:b crashes validation", status=status, fixed_in=fixed_in)


def test_a_known_bug_step_fails_as_expected_and_the_scenario_goes_on(tmp_path: Path) -> None:
    """The step's mismatch is an expected failure (not a failure), the next step runs strict, the run xfails."""
    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))  # the bug: changes instead of noop
    r.cli.queue("plan", canned("plan", NOOP))
    with pytest.raises(pytest.xfail.Exception, match=r"KB-025: pass:a:b crashes validation \(step 'buggy'\)"):
        r.engine.run(scenario(tmp_path, KB))
    assert [call.command for call in r.cli.calls] == ["plan", "plan"]
    assert r.baseline.calls[-1][0] == "guarded_apply"  # cleanup ran before the xfail


def test_the_outcome_records_the_expected_failures(tmp_path: Path) -> None:
    """outcome.expected_failures / expected_bugs, step flags and notes; ok stays True."""
    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("plan", canned("plan", NOOP))
    outcome, loaded = ScenarioOutcome("cli.kb"), scenario(tmp_path, KB)
    for step in loaded.steps:
        assert r.engine._run_step(loaded, step, r.engine.variables_for(loaded), [], outcome) == []
    assert outcome.ok and outcome.failures == []
    assert outcome.expected_failures and outcome.expected_failures[0].startswith("step 'buggy' plan: expected noop")
    assert outcome.expected_bugs == {"buggy": "KB-025: pass:a:b crashes validation"}
    buggy, strict = outcome.steps
    assert buggy.known_bug == "KB-025" and buggy.expected_failure and not strict.expected_failure
    assert outcome.xfail_reason.startswith("KB-025: pass:a:b crashes validation (step 'buggy'): step 'buggy' plan")
    assert any("expected failure (KB-025)" in note for note in buggy.notes)


def test_failures_of_other_steps_still_fail(tmp_path: Path) -> None:
    """A strict step failing after an expected failure fails the scenario (both are reported)."""
    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-y"))))
    with pytest.raises(ScenarioFailedError) as info:
        r.engine.run(scenario(tmp_path, KB))
    outcome = info.value.outcome
    assert outcome.failures and outcome.failures[0].startswith("step 'strict' plan: expected noop")
    assert outcome.xfail_reason is None and "expected failures (known bugs: KB-025" in str(info.value)


def test_a_fixed_bug_makes_the_step_strict(tmp_path: Path) -> None:
    """status fixed (and a SUT that is not older than fixed_in): the step guards against the regression."""
    r = rig(bugs={"KB-025": open_bug("fixed", "1.7.0")})
    r.cli.installed = type("I", (), {"sut": type("S", (), {"version": "1.7.1"})()})()  # type: ignore[attr-defined]
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    with pytest.raises(ScenarioFailedError, match="step 'buggy' plan: expected noop"):
        r.engine.run(scenario(tmp_path, KB))


def test_a_fixed_bug_still_affects_older_suts(tmp_path: Path) -> None:
    """A SUT predating fixed_in keeps the expected failure."""
    r = rig(bugs={"KB-025": open_bug("fixed", "1.7.0")})
    r.cli.installed = type("I", (), {"sut": type("S", (), {"version": "1.6.1"})()})()  # type: ignore[attr-defined]
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("plan", canned("plan", NOOP))
    with pytest.raises(pytest.xfail.Exception):
        r.engine.run(scenario(tmp_path, KB))


def test_an_unlisted_bug_affects_every_sut(tmp_path: Path) -> None:
    """An id missing from known_bugs.yaml counts as affecting (the reason says so)."""
    r = rig(bugs={})
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("plan", canned("plan", NOOP))
    with pytest.raises(pytest.xfail.Exception, match=r"KB-025: not listed in known_bugs\.yaml"):
        r.engine.run(scenario(tmp_path, KB))


def test_infra_problems_and_harness_errors_are_never_expected() -> None:
    """record_phase_problems keeps infra problems and the errors of the phase (exceptions) as failures."""
    from otterdog_e2e.scenarios.engine import StepOutcome

    outcome, step = ScenarioOutcome("s"), StepOutcome("x")
    step.errors.append("SafetyError: refusing")
    bug = StepBug("KB-001", "KB-001: t", True)
    problems = ["[infra] rate limit", "SafetyError: refusing", "expected noop, got changes"]
    assert record_phase_problems(outcome, step, "plan", problems, bug) == problems[:2]
    assert outcome.failures == ["step 'x' plan: [infra] rate limit", "step 'x' plan: SafetyError: refusing"]
    assert outcome.expected_failures == ["step 'x' plan: expected noop, got changes"]


KB_STATE = """
id: cli.kb-state
title: kb state
steps:
  - name: buggy
    known_bug: KB-025
    fragments: {}
    plan: {expect: changes}
    state: [{kind: repo, name: "{{ p }}-x", match: {private: false}}]
    converge: false
"""


class LookupFailingOracle(FakeOracle):
    """An oracle whose repo lookup raises (a harness bug, or a network error)."""

    def __init__(self, error: Exception) -> None:
        """Raise ``error`` on every repo lookup."""
        super().__init__()
        self.error = error

    def repo(self, name: str) -> dict[str, Any] | None:
        """Fail."""
        raise self.error


@pytest.mark.parametrize(
    ("error", "infra"),
    [
        (TypeError("'NoneType' object is not subscriptable"), False),
        (ConnectionError("Connection reset by peer"), True),
    ],
)
def test_failed_state_lookups_of_a_known_bug_step_stay_failures(tmp_path: Path, error: Exception, infra: bool) -> None:
    """BAT-02: a state check that could not be evaluated (an Oracle exception: harness bug or network) is never the
    expected failure of the step's known bug; network errors are tagged [infra]."""
    r = rig(bugs={"KB-025": open_bug()})
    r.engine.oracle = LookupFailingOracle(error)  # type: ignore[assignment]
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("apply", canned("apply", applied()))
    with pytest.raises(ScenarioFailedError) as info:
        r.engine.run(scenario(tmp_path, KB_STATE))
    outcome = info.value.outcome
    assert outcome.expected_failures == [] and outcome.xfail_reason is None
    assert len(outcome.failures) == 1 and f"lookup failed: {type(error).__name__}" in outcome.failures[0]
    assert ("[infra]" in outcome.failures[0]) is infra and outcome.infra is infra


def test_a_phase_scoped_known_bug_only_explains_its_phases(tmp_path: Path) -> None:
    """known_bug {id, phases: [converge]}: a plan failure of the step is a failure (strict), a converge failure is
    expected."""
    text = KB.replace("known_bug: KB-025", "known_bug: {id: KB-025, phases: [converge]}")
    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))  # plan mismatch: not explained by the bug
    with pytest.raises(ScenarioFailedError, match="step 'buggy' plan: expected noop"):
        r.engine.run(scenario(tmp_path, text))
    converge = KB.replace("known_bug: KB-025", "known_bug: {id: KB-025, phases: [converge]}").replace(
        "    plan: {expect: noop}\n  - name: strict", "    plan: {expect: changes}\n  - name: strict", 1
    )
    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("apply", canned("apply", applied()))
    for _ in range(4):  # never converges: the bug
        r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("plan", canned("plan", NOOP))
    with pytest.raises(pytest.xfail.Exception, match="KB-025"):
        r.engine.run(scenario(tmp_path, converge))


KB_SCENARIO = """
id: cli.kb.whole
title: kb whole
known_bug: KB-025
steps:
  - name: setup
    fragments: {}
    plan: {expect: noop}
  - name: reproduce
    fragments: {}
    plan: {expect: noop}
  - name: after
    fragments: {}
    plan: {expect: noop}
"""


def test_a_scenario_level_bug_is_scoped_to_its_steps_and_never_hides_the_cleanup(tmp_path: Path) -> None:
    """BAT-03: a scenario-level known bug makes the expectation failures of the steps expected (the first one ends
    the reproduction: later steps do not run, the cleanup does); a failing cleanup is a failure, not an XFAIL."""
    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", NOOP))
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))  # the bug
    with pytest.raises(pytest.xfail.Exception, match=r"KB-025: pass:a:b crashes validation \(step 'reproduce'\)"):
        r.engine.run(scenario(tmp_path, KB_SCENARIO))
    assert [call.command for call in r.cli.calls] == ["plan", "plan"] and r.baseline.calls[-1][0] == "guarded_apply"

    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", NOOP))
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))

    def failing_cleanup(cli: Any, *, repo_filter: str | None, delete: bool) -> ApplyResult:
        """The cleanup leaves objects behind."""
        return ApplyResult(0, 0, 0, 0, False, False, None, ["failed to apply patch: remove repository"], [], "")

    r.baseline.guarded_apply = failing_cleanup  # type: ignore[method-assign]
    with pytest.raises(ScenarioFailedError, match="cleanup: CleanupError"):
        r.engine.run(scenario(tmp_path, KB_SCENARIO))


def test_a_scenario_level_bug_that_does_not_show_is_an_unexpected_pass(tmp_path: Path) -> None:
    """Every step passes: one unexpected pass for the scenario (KnownBugNotReproducedWarning), never per step."""
    r = rig(bugs={"KB-025": open_bug()})
    for _ in range(3):
        r.cli.queue("plan", canned("plan", NOOP))
    with pytest.warns(KnownBugNotReproducedWarning, match=r"\(scenario\) passed"):
        outcome = r.engine.run(scenario(tmp_path, KB_SCENARIO))
    assert outcome.ok and outcome.unexpected_passes == ["KB-025: pass:a:b crashes validation (scenario)"]


def test_render_errors_of_a_known_bug_step_are_failures(tmp_path: Path) -> None:
    """Exceptions (here a SafetyError of a bad filter) are harness errors, not the bug."""
    r = rig(bugs={"KB-025": open_bug()})
    loaded = scenario(tmp_path, KB)
    loaded.steps[0].plan.repo_filter = "foreign-*"
    with pytest.raises(ScenarioFailedError, match="step 'buggy' plan: SafetyError"):
        r.engine.run(loaded)


def test_a_known_bug_step_that_passes_warns(tmp_path: Path) -> None:
    """A known-bug step that passes is an unexpected pass: recorded and warned about, the run passes."""
    r = rig(bugs={"KB-025": open_bug()})
    r.cli.queue("plan", canned("plan", NOOP))
    r.cli.queue("plan", canned("plan", NOOP))
    with pytest.warns(
        KnownBugNotReproducedWarning, match=r"KB-025: pass:a:b crashes validation \(step 'buggy'\) passed"
    ):
        outcome = r.engine.run(scenario(tmp_path, KB))
    assert outcome.ok and outcome.unexpected_passes == ["KB-025: pass:a:b crashes validation (step 'buggy')"]
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        outcome.raise_for_failures()  # warned once per outcome


def test_step_bug_and_known_bugs_near(tmp_path: Path) -> None:
    """step_bug resolves the step's id; known_bugs_near finds scenarios/known_bugs.yaml inside the project."""
    step = StepSpec(name="s", known_bug="KB-002")
    assert step_bug(StepSpec(name="s"), {}, None) is None
    assert step_bug(step, {}, None) == StepBug("KB-002", "KB-002: not listed in known_bugs.yaml", True)
    project = tmp_path / "project"
    (project / "scenarios" / "cli").mkdir(parents=True)
    (project / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (project / "scenarios" / "known_bugs.yaml").write_text("- {id: KB-002, title: install-app, status: fixed}\n")
    bugs = known_bugs_near(project / "scenarios" / "cli" / "x.yaml")
    assert bugs["KB-002"].fixed and step_bug(step, bugs, "1.6.1") == StepBug("KB-002", "KB-002: install-app", False)
    (tmp_path / "known_bugs.yaml").write_text("- {id: KB-009, title: outside}\n")
    elsewhere = project / "other"
    elsewhere.mkdir()
    assert known_bugs_near(elsewhere / "x.yaml") == {}  # the search stops at the project root
    (project / "scenarios" / "known_bugs.yaml").write_text("not: [a list\n")
    assert known_bugs_near(project / "scenarios" / "cli" / "x.yaml") == {}  # invalid files are logged, not raised


def test_the_engine_reads_the_known_bugs_next_to_the_scenario(tmp_path: Path) -> None:
    """Without engine.known_bugs the bug comes from the known_bugs.yaml above the scenario file."""
    r = rig()
    r.engine.known_bugs = None
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    (tmp_path / "known_bugs.yaml").write_text("- {id: KB-025, title: from disk}\n")
    r.cli.queue("plan", canned("plan", planned(add(f"{P}-x"))))
    r.cli.queue("plan", canned("plan", NOOP))
    with pytest.raises(pytest.xfail.Exception, match="KB-025: from disk"):
        r.engine.run(scenario(tmp_path, KB))


# --- observe_live ----------------------------------------------------------------------------------------------------
class Recorder:
    """ObservationRecorder stand-in."""

    def __init__(self) -> None:
        """No scope yet."""
        self.scopes: list[tuple[str, str | None]] = []

    def scope(self, scenario: str, step: str | None = None) -> Any:
        """Record the scope."""
        from contextlib import nullcontext

        self.scopes.append((scenario, step))
        return nullcontext()


def side(role: str) -> SutSide:
    """A SutSide over a lax FakeCli."""
    cli = FakeCli(workspace=FakeWorkspace())
    return SutSide(role=role, installed=None, cli=cli, recorder=Recorder(), template=offline_template())  # type: ignore[arg-type]


def test_observe_live_uses_the_step_options(tmp_path: Path) -> None:
    """validate -v and the plan's diff flags (repo_filter included) are recorded on both sides; never apply."""
    base, head = side("base"), side("head")
    runner = DifferentialRunner(base=base, head=head, renderer_factory=lambda s: FakeRenderer(), template_src_for=Path)  # type: ignore[arg-type,return-value]
    runner.variables = {**RUN.template_vars(), **VARIABLES}
    text = """
    id: cli.observe
    title: observe
    steps:
      - name: a
        fragments: {}
        validate: {verbose: true}
        plan: {repo_filter: "{{ p }}-a", update_webhooks: true}
      - name: b
        fragments: {}
    """
    runner.observe_live(scenario(tmp_path, text))
    for current in (base, head):
        calls: Sequence[Any] = current.cli.calls
        assert [call.command for call in calls] == ["validate", "plan", "validate", "plan"]
        assert calls[0].kwargs["verbose"] is True and calls[2].kwargs["verbose"] is False
        assert calls[1].kwargs["options"] == DiffOptions(f"{P}-a", update_webhooks=True)
        assert calls[3].kwargs["options"] == DiffOptions(f"{P}-*")
