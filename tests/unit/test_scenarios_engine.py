"""Live ScenarioEngine: phases, abort-on-failure, negative mode, converge backoff, needles, guarded cleanup."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.capabilities import from_plan
from otterdog_e2e.otterdog import output as od_output
from otterdog_e2e.otterdog.output import ApplyResult, Message, PlanObject, PlanResult, ValidationResult
from otterdog_e2e.otterdog.render import ConfigFragments, RenderError
from otterdog_e2e.otterdog.runner import CliResult, DiffOptions
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.scenarios.engine import (
    ScenarioEngine,
    ScenarioFailedError,
    classify_apply,
    filtered_counts,
)
from otterdog_e2e.scenarios.model import Scenario, load_scenario
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli, FakeOracle, make_run_context

RUN = make_run_context()
P = RUN.prefix
REPO = f"{P}-basic"
VARIABLES: dict[str, Any] = {
    "org": "e2e-test-org",
    "plan": "free",
    "logins": {"admin": "e2e-admin"},
    "app_slug": "otterdog-e2e-app",
    "teams": {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"},
}


# --- fakes and builders ----------------------------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _plain_normalize_text(monkeypatch: pytest.MonkeyPatch) -> None:
    """normalize_text (WP-D) is replaced by a whitespace-preserving identity: these tests build parsed results."""

    def normalize_text(text: str, ctx: Any = None) -> str:
        """Identity."""
        return text

    monkeypatch.setattr(od_output, "normalize_text", normalize_text)


@dataclass
class Canned(CliResult):
    """A CliResult whose parsed form (PlanResult, ApplyResult or ValidationResult) is given directly."""

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


def obj(op: str, kind: str, value: str = "", *, parent: str | None = None, body: Sequence[str] = ()) -> PlanObject:
    """A PlanObject with an otterdog-like header."""
    symbol = {"add": "+ add", "remove": "- remove", "change": "~", "forced": "!"}[op]
    if value:
        suffix = f", repository={parent}" if parent else ""
        header = f'  {symbol} {kind}[name="{value}"{suffix}] {{'
    else:
        header = f"  {symbol} {kind} {{"
    key = "name" if value else ""
    return PlanObject(op, kind, key, value, "repository" if parent else None, parent, header, list(body))


def planned(
    *objects: PlanObject,
    add: int | None = None,
    change: int | None = None,
    delete: int | None = None,
    validation: ValidationResult | None = None,
    aborted: bool = False,
) -> PlanResult:
    """A PlanResult; missing counts are derived from the objects."""
    counts = filtered_counts(list(objects))
    return PlanResult(
        add=counts["add"] if add is None and not aborted else add,
        change=counts["change"] if change is None and not aborted else change,
        delete=counts["delete"] if delete is None and not aborted else delete,
        objects=list(objects),
        aborted=aborted,
        validation=validation,
        messages=[],
        raw="",
    )


def validated(ok: bool = True, errors: int = 0, warnings: int = 0) -> ValidationResult:
    """A ValidationResult."""
    return ValidationResult(ok, 0, warnings, errors, [], False, "")


def applied(
    added: int = 1, *, failed: Sequence[str] = (), aborted_validation: bool = False, no_changes: bool = False
) -> ApplyResult:
    """An ApplyResult."""
    return ApplyResult(
        added=None if aborted_validation else added,
        changed=0,
        deleted=0,
        ignored=None,
        no_changes=no_changes,
        aborted_validation=aborted_validation,
        pending_deletions=None,
        failed_patches=list(failed),
        messages=[],
        raw="",
    )


ADD_REPO = obj("add", "repository", REPO)
ADD_REPO_TEXT = f'  + add repository[name="{REPO}"] {{'
NOOP = planned()


class FakeWorkspace:
    """ConfigWorkspace stand-in recording the files written."""

    def __init__(self, org: str = "e2e-test-org") -> None:
        """Bind to a fake org."""
        self.org = org
        self.project = org
        self.template = offline_template()
        self.org_dir = Path("/nonexistent/orgs") / org
        self.writes: list[str] = []
        self.base_writes: list[str] = []
        self.otterdog_json_writes = 0

    @property
    def config_file(self) -> Path:
        """otterdog.json (exists once written)."""
        return Path("/nonexistent/otterdog.json") if not self.otterdog_json_writes else Path("/")

    def write_org_config(self, text: str) -> Path:
        """Record the org config."""
        self.writes.append(text)
        return self.org_dir / f"{self.org}.jsonnet"

    def write_base_config(self, text: str) -> Path:
        """Record the -BASE config."""
        self.base_writes.append(text)
        return self.org_dir / f"{self.org}.jsonnet-BASE"

    def write_otterdog_json(self) -> Path:
        """Count otterdog.json writes."""
        self.otterdog_json_writes += 1
        return self.org_dir.parent.parent / "otterdog.json"


class FakeRenderer:
    """OrgConfigRenderer stand-in: JSON of the fragments and the plan override."""

    def __init__(self, error: Exception | None = None) -> None:
        """Optionally fail every render."""
        self.calls: list[tuple[ConfigFragments | None, str | None]] = []
        self.error = error

    def render(
        self, fragments: ConfigFragments | None = None, *, include_baseline: bool = True, plan: str | None = None
    ) -> str:
        """Record and serialize."""
        if self.error is not None:
            raise self.error
        self.calls.append((fragments, plan))
        return json.dumps({"fragments": fragments.to_mapping() if fragments else None, "plan": plan})


class FakeBaseline:
    """BaselineManager stand-in recording guard, cleanup and reset calls."""

    def __init__(self, *, refuse: bool = False, result: ApplyResult | None = None, error: Exception | None = None):
        """Use a FakeCli as the trusted reset CLI."""
        self.reset_cli = FakeCli(workspace=FakeWorkspace())
        self.refuse = refuse
        self.result = result or applied(0, no_changes=True)
        self.error = error
        self.calls: list[tuple[Any, ...]] = []
        self.run_objects_left = False

    def text(self) -> str:
        """The baseline config."""
        self.calls.append(("text",))
        return "BASELINE"

    def check_changes(self, plan: PlanResult) -> None:
        """Accept every change (recorded apart from ``calls``)."""
        self.changes_checked = [*getattr(self, "changes_checked", []), plan]

    def check_removals(self, plan: PlanResult) -> None:
        """Record; SafetyError when refusing."""
        self.calls.append(("check_removals", plan))
        if self.refuse:
            raise SafetyError('refusing to remove team[name="prod-team"]')

    def guarded_apply(self, cli: Any, *, repo_filter: str | None, delete: bool) -> ApplyResult:
        """Record the cleanup apply."""
        self.calls.append(("guarded_apply", cli, repo_filter, delete))
        if self.error is not None:
            raise self.error
        return self.result

    def reset(self) -> ApplyResult:
        """Record a reset."""
        self.calls.append(("reset",))
        return self.result


def scenario(tmp_path: Path, text: str, name: str = "case") -> Scenario:
    """Load a scenario written under tmp_path/cli/."""
    path = tmp_path / "cli" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return load_scenario(path)


@dataclass
class Rig:
    """An engine with its fakes."""

    engine: ScenarioEngine
    cli: FakeCli
    oracle: FakeOracle
    baseline: FakeBaseline
    renderer: FakeRenderer
    sleeps: list[float]


def rig(*, plan: str = "free", extra: Sequence[str] = (), **kw: Any) -> Rig:
    """Build a ScenarioEngine over fakes (sleep records instead of sleeping)."""
    cli = FakeCli(workspace=FakeWorkspace(), strict=True)
    oracle = kw.pop("oracle", None) or FakeOracle()
    baseline = kw.pop("baseline", None) or FakeBaseline()
    renderer = kw.pop("renderer", None) or FakeRenderer()
    sleeps: list[float] = []
    engine = ScenarioEngine(
        cli=cli,  # type: ignore[arg-type]
        renderer=renderer,  # type: ignore[arg-type]
        oracle=oracle,  # type: ignore[arg-type]
        run_ctx=RUN,
        capabilities=from_plan(plan, extra),
        baseline=baseline,  # type: ignore[arg-type]
        variables=VARIABLES,
        sleep=sleeps.append,
    )
    return Rig(engine, cli, oracle, baseline, renderer, sleeps)


CREATE = """
id: cli.repo.create
title: create
steps:
  - name: create
    fragments:
      repositories: ["orgs.newRepo('{{ p }}-basic') { description: 'e2e basic' }"]
    validate: {}
    plan: {expect: changes, contains: ['repository[name="{{ p }}-basic"]'], counts: {add: 1}}
    state: [{kind: repo, name: "{{ p }}-basic", match: {description: e2e basic}}]
"""


# --- step flow -------------------------------------------------------------------------------------------------------
def test_step_phases_in_order_then_guarded_cleanup(tmp_path: Path) -> None:
    """render -> validate -> plan -> apply -> state -> converge, then cleanup with the trusted reset CLI."""
    r = rig()
    r.oracle.add_repo(REPO, description="e2e basic")
    r.cli.queue("validate", canned("validate", validated()))
    r.cli.queue("plan", canned("plan", planned(ADD_REPO), stdout=ADD_REPO_TEXT))
    r.cli.queue("apply", canned("apply", applied()))
    r.cli.queue("plan", canned("plan", NOOP))
    outcome = r.engine.run(scenario(tmp_path, CREATE))
    assert outcome.ok and [c.command for c in r.cli.calls] == ["validate", "plan", "apply", "plan"]
    plan_call, apply_call = r.cli.calls[1], r.cli.calls[2]
    assert plan_call.kwargs["repo_filter"] == f"{P}-*" and plan_call.kwargs["options"] == DiffOptions(f"{P}-*")
    assert apply_call.kwargs == {
        "options": DiffOptions(repo_filter=f"{P}-*"),
        "repo_filter": f"{P}-*",
        "update_webhooks": False,
        "update_secrets": False,
        "only_secrets": False,
        "update_filter": None,
        "verbose": False,
        "delete": False,
        "local": False,
        "observe": None,
    }
    assert REPO in r.cli.workspace.writes[0]
    step = outcome.steps[0]
    assert set(step.results) == {"validate", "plan", "apply", "converge"} and step.checks[0].ok
    assert set(step.durations) == {"render", "validate", "plan", "apply", "state", "converge"}
    assert "converge: noop after 1 plan(s)" in step.notes and r.sleeps == []
    assert r.baseline.calls == [("text",), ("guarded_apply", r.baseline.reset_cli, f"{P}-*", True)]
    reset_workspace = r.baseline.reset_cli.workspace
    assert reset_workspace.writes == ["BASELINE"] and reset_workspace.otterdog_json_writes == 1


def test_first_failing_phase_aborts_but_cleanup_runs(tmp_path: Path) -> None:
    """A plan mismatch stops the scenario; the next step never runs; cleanup still runs; failures are reported."""
    r = rig()
    r.cli.queue("plan", canned("plan", NOOP, stdout="Plan: 0 to add, 0 to change, 0 to delete."))
    text = CREATE.replace("    validate: {}\n", "") + "  - name: never\n    fragments: {}\n"
    with pytest.raises(ScenarioFailedError) as info:
        r.engine.run(scenario(tmp_path, text))
    outcome = info.value.outcome
    assert [c.command for c in r.cli.calls] == ["plan"] and [s.name for s in outcome.steps] == ["create"]
    assert outcome.steps[0].failed_phase == "plan"
    assert any("step 'create' plan: expected changes, got noop" in f for f in outcome.failures)
    assert any("counts.add: expected 1, got 0" in f for f in outcome.failures)
    assert "plan output (last 30 lines):\nPlan: 0 to add" in str(info.value)
    assert isinstance(info.value, AssertionError)
    assert ("guarded_apply", r.baseline.reset_cli, f"{P}-*", True) in r.baseline.calls


def test_validate_runs_only_when_given_and_checks_expectations(tmp_path: Path) -> None:
    """A step without validate skips it; a failing expectation stops before the plan."""
    r = rig()
    r.cli.queue("validate", canned("validate", validated(ok=False, errors=1), exit_code=1))
    with pytest.raises(ScenarioFailedError, match="expected validation to succeed, it failed"):
        r.engine.run(scenario(tmp_path, CREATE))
    assert [c.command for c in r.cli.calls] == ["validate"]


def test_plan_null_skips_plan_apply_and_converge(tmp_path: Path) -> None:
    """A validate-only step."""
    r = rig()
    r.cli.queue("validate", canned("validate", validated()))
    text = """
    id: v
    title: v
    steps: [{fragments: {}, validate: {}, plan: null}]
    """
    assert r.engine.run(scenario(tmp_path, text)).ok and [c.command for c in r.cli.calls] == ["validate"]


def test_plan_expect_noop_and_validation_error_never_apply(tmp_path: Path) -> None:
    """apply runs only when the plan expects changes."""
    r = rig()
    invalid = planned(aborted=True, validation=validated(ok=False, errors=1))
    r.cli.queue("plan", canned("plan", NOOP))
    r.cli.queue("plan", canned("plan", invalid, stdout="Planning aborted due to validation errors.", exit_code=1))
    text = """
    id: n
    title: n
    steps:
      - {name: same, fragments: {}, plan: {expect: noop}}
      - {name: bad, fragments: {}, plan: {expect: validation_error, contains: [Planning aborted]}}
    """
    assert r.engine.run(scenario(tmp_path, text)).ok
    assert [c.command for c in r.cli.calls] == ["plan", "plan"]


def test_variables_plan_overrides_the_rendered_plan(tmp_path: Path) -> None:
    """``variables.plan`` reaches both the renderer and the Jinja ``plan`` variable."""
    r = rig()
    r.cli.queue("plan", canned("plan", NOOP))
    text = """
    id: m
    title: m
    variables: {plan: team}
    steps: [{fragments: {}, plan: {expect: noop, contains: ["{{ plan }}"]}}]
    """
    r.cli.queue("plan", canned("plan", NOOP))
    with pytest.raises(ScenarioFailedError, match="output does not contain 'team'"):
        r.engine.run(scenario(tmp_path, text))
    assert r.renderer.calls[0][1] == "team"


def test_render_errors_are_phase_failures(tmp_path: Path) -> None:
    """A RenderError fails the render phase; nothing runs; cleanup still runs."""
    r = rig(renderer=FakeRenderer(RenderError("settings fragments must not set ['plan']")))
    with pytest.raises(ScenarioFailedError, match="render: RenderError: settings fragments must not set"):
        r.engine.run(scenario(tmp_path, CREATE))
    assert r.cli.calls == [] and r.baseline.calls[-1][0] == "guarded_apply"


def test_requires_and_min_plan_skip_without_side_effects(tmp_path: Path) -> None:
    """Missing capabilities or a lower plan skip the scenario: no CLI call, no cleanup."""
    r = rig()
    needs = scenario(tmp_path, "id: a\ntitle: a\nrequires: [custom_properties]\nsteps: [{fragments: {}}]\n", "a")
    outcome = r.engine.run(needs)
    assert outcome.ok and outcome.skipped == "missing capabilities: custom_properties"
    team = scenario(tmp_path, "id: b\ntitle: b\nmin_plan: team\nsteps: [{fragments: {}}]\n", "b")
    assert r.engine.run(team).skipped == "plan 'free' is below min_plan 'team'"
    assert r.cli.calls == [] and r.baseline.calls == []


@pytest.mark.parametrize(
    ("sut_version", "skipped"),
    [("1.6.1", True), ("1.7.0.dev15+e2e.g9bdeb75", False), ("1.7.0", False), (None, False)],
)
def test_fixed_in_skips_older_suts(tmp_path: Path, sut_version: str | None, skipped: bool) -> None:
    """A scenario whose fixed_in the SUT predates is skipped before any CLI call (unknown versions run it)."""
    r = rig()
    r.cli.installed = type("Installed", (), {"sut": type("Sut", (), {"version": sut_version})()})()  # type: ignore[attr-defined]
    fixed = scenario(tmp_path, "id: f\ntitle: f\nfixed_in: '1.7.0.dev15'\nsteps: [{fragments: {}, plan: null}]\n", "f")
    reason = r.engine.skip_reason(fixed)
    if skipped:
        assert reason == "SUT 1.6.1 predates otterdog 1.7.0.dev15, the first version f asserts"
        assert r.engine.run(fixed).skipped == reason and r.cli.calls == [] and r.baseline.calls == []
    else:
        assert reason is None


def test_offline_scenarios_are_refused(tmp_path: Path) -> None:
    """The live engine never runs offline scenarios."""
    path = tmp_path / "offline" / "o.yaml"
    path.parent.mkdir()
    path.write_text("id: o\ntitle: o\nsteps: [{fragments: {}}]\n")
    with pytest.raises(ValueError, match="use OfflineEngine"):
        rig().engine.run(load_scenario(path))


# --- negative mode ---------------------------------------------------------------------------------------------------
NEGATIVE = """
id: C-NEG-PRIVATE-BPR
title: private bpr
expect_failure_without: [private_repo_branch_protection]
steps:
  - name: create
    fragments: {repositories: ["orgs.newRepo('{{ p }}-priv') { private: true }"]}
    state: [{kind: repo, name: "{{ p }}-priv", absent: false}]
    on_missing_capability: {apply: {expect: error}, state: [], converge: false}
"""


def test_negative_mode_applies_on_missing_capability(tmp_path: Path) -> None:
    """Free lacks the capability: the expected failure passes, state and converge are skipped."""
    r = rig()
    r.cli.queue("plan", canned("plan", planned(obj("add", "repository", f"{P}-priv"))))
    r.cli.queue("apply", canned("apply", applied(failed=["ADD - repository: 403 Upgrade to GitHub Pro"]), exit_code=1))
    outcome = r.engine.run(scenario(tmp_path, NEGATIVE))
    step = outcome.steps[0]
    assert outcome.ok and step.negative and step.checks == []
    assert any("negative mode: missing private_repo_branch_protection" in note for note in step.notes)
    assert [c.command for c in r.cli.calls] == ["plan", "apply"]


def test_positive_mode_when_capability_present(tmp_path: Path) -> None:
    """With the capability the normal expectations apply: the same apply error is a failure."""
    r = rig(plan="team")
    r.cli.queue("plan", canned("plan", planned(obj("add", "repository", f"{P}-priv"))))
    r.cli.queue("apply", canned("apply", applied(failed=["ADD - repository: 403"]), exit_code=1))
    with pytest.raises(ScenarioFailedError, match="apply: expected ok, got error"):
        r.engine.run(scenario(tmp_path, NEGATIVE))


# --- converge --------------------------------------------------------------------------------------------------------
def _created(r: Rig) -> None:
    """Queue validate/plan/apply results of CREATE with the repo visible to the oracle."""
    r.oracle.add_repo(REPO, description="e2e basic")
    r.cli.queue("validate", canned("validate", validated()))
    r.cli.queue("plan", canned("plan", planned(ADD_REPO), stdout=ADD_REPO_TEXT))
    r.cli.queue("apply", canned("apply", applied()))


def test_converge_polls_with_backoff(tmp_path: Path) -> None:
    """Plans are retried after 5 then 10 s until this run's objects are a no-op."""
    r = rig()
    _created(r)
    pending = planned(obj("change", "repository", REPO, body=["    ~ description = 'x' -> 'e2e basic'"]))
    r.cli.queue("plan", canned("plan", pending))
    r.cli.queue("plan", canned("plan", pending))
    r.cli.queue("plan", canned("plan", NOOP))
    outcome = r.engine.run(scenario(tmp_path, CREATE))
    assert outcome.ok and r.sleeps == [5.0, 10.0]
    assert "converge: noop after 3 plan(s)" in outcome.steps[0].notes


def test_converge_failure_lists_pending_objects(tmp_path: Path) -> None:
    """Four plans (backoff 5/10/20 s) without a no-op fail the converge phase."""
    r = rig()
    _created(r)
    removal = planned(obj("remove", "repo_secret", f"{RUN.const_prefix}SEC", parent=REPO))
    for _ in range(4):
        r.cli.queue("plan", canned("plan", removal))
    with pytest.raises(ScenarioFailedError) as info:
        r.engine.run(scenario(tmp_path, CREATE))
    message = str(info.value)
    assert "converge: not converged after 4 plan(s), last plan: changes" in message
    assert f'- remove repo_secret[name="{RUN.const_prefix}SEC", repository={REPO}]' in message
    assert "delete: true" in message and r.sleeps == [5.0, 10.0, 20.0]


def test_read_only_changes_count_as_converged(tmp_path: Path) -> None:
    """``Note: setting 'x' is read-only`` changes never block convergence."""
    r = rig()
    _created(r)
    read_only = obj("change", "repository", REPO, body=["    ~ archived = false -> true"])
    read_only.notes.append("Note: setting 'archived' is read-only, will be skipped.")
    r.cli.queue("plan", canned("plan", planned(read_only, change=0)))
    assert r.engine.run(scenario(tmp_path, CREATE)).ok


def test_converge_skipped_when_disabled_or_apply_not_ok(tmp_path: Path) -> None:
    """``converge: false`` or an apply that did not succeed (expect any) skip the converge plans."""
    r = rig()
    r.cli.queue("plan", canned("plan", planned(ADD_REPO)))
    r.cli.queue("apply", canned("apply", applied(failed=["boom"]), exit_code=1))
    text = """
    id: d
    title: d
    steps: [{fragments: {}, apply: {expect: any}}]
    """
    assert r.engine.run(scenario(tmp_path, text)).ok and [c.command for c in r.cli.calls] == ["plan", "apply"]


# --- needles, counts, org_level ---------------------------------------------------------------------------------------
def test_foreign_objects_are_ignored_and_counts_filtered(tmp_path: Path) -> None:
    """Objects of other runs or humans neither make changes nor count when the plan has foreign changes."""
    r = rig()
    r.oracle.add_repo(REPO, description="e2e basic")
    foreign = obj("change", "repository", "human-repo", body=["    ~ description = 'a' -> 'b'"])
    other_run = obj("add", "team", "e2e-other-team")
    r.cli.queue("validate", canned("validate", validated()))
    r.cli.queue("plan", canned("plan", planned(ADD_REPO, foreign, other_run), stdout=ADD_REPO_TEXT))  # raw: 2 add
    r.cli.queue("apply", canned("apply", applied()))
    r.cli.queue("plan", canned("plan", planned(foreign, other_run)))  # converged for this run
    outcome = r.engine.run(scenario(tmp_path, CREATE))
    assert outcome.ok and "converge: noop after 1 plan(s)" in outcome.steps[0].notes


def test_only_foreign_changes_are_a_noop(tmp_path: Path) -> None:
    """A plan whose only changes belong to others is ``noop`` for the scenario."""
    r = rig()
    r.cli.queue("plan", canned("plan", planned(obj("remove", "repository", "e2e-zzzzzz00-left"))))
    text = "id: f\ntitle: f\nsteps: [{fragments: {}, plan: {expect: noop}}]\n"
    assert r.engine.run(scenario(tmp_path, text)).ok


def test_raw_counts_when_no_foreign_changes(tmp_path: Path) -> None:
    """Without foreign changes the raw ``Plan:`` numbers are compared."""
    r = rig()
    r.cli.queue("validate", canned("validate", validated()))
    r.cli.queue("plan", canned("plan", planned(ADD_REPO, add=2), stdout=ADD_REPO_TEXT))
    with pytest.raises(ScenarioFailedError) as info:
        r.engine.run(scenario(tmp_path, CREATE))
    assert info.value.outcome.failures == ["step 'create' plan: counts.add: expected 1, got 2"]


def test_filtered_counts_follow_otterdog_counting() -> None:
    """change = changed non-read-only keys, add/delete = objects."""
    changed = obj("change", "repository", REPO, body=["    ~ description = 'a' -> 'b'", "    ~ archived = x -> y"])
    changed.notes.append("Note: setting 'archived' is read-only, will be skipped.")
    counts = filtered_counts([changed, ADD_REPO, obj("remove", "team", f"{P}-t")])
    assert counts == {"add": 1, "change": 1, "delete": 1}


def test_org_level_plans_unfiltered_include_settings_and_reset(tmp_path: Path) -> None:
    """org_level: no -r filter, the settings object is this scenario's, cleanup is a full reset."""
    r = rig()
    settings = obj("change", "settings", body=["    ~ web_commit_signoff_required = false -> true"])
    r.cli.queue("plan", canned("plan", planned(settings)))
    r.cli.queue("apply", canned("apply", applied(0)))
    r.cli.queue("plan", canned("plan", planned(settings)))
    r.cli.queue("plan", canned("plan", NOOP))
    text = """
    id: org
    title: org
    org_level: true
    steps: [{fragments: {settings: ["web_commit_signoff_required: true"]}}]
    """
    outcome = r.engine.run(scenario(tmp_path, text))
    assert outcome.ok and all(c.kwargs["repo_filter"] is None for c in r.cli.calls)
    assert r.sleeps == [5.0] and r.baseline.calls == [("reset",)]


# --- apply semantics -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("result", "expected"),
    [
        (canned("apply", applied()), "ok"),
        (canned("apply", applied(0, no_changes=True)), "ok"),
        (canned("apply", applied(failed=["failed to apply patch: ADD"]), exit_code=1), "error"),
        (canned("apply", applied(), exit_code=2), "error"),
        (canned("apply", applied(aborted_validation=True)), "validation_error"),
        (
            canned("apply", applied(None), stdout="Planning aborted due to validation errors.\nNo changes required."),
            "validation_error",
        ),  # type: ignore[arg-type]
        (canned("apply", applied(None)), "error"),  # type: ignore[arg-type]
    ],
)
def test_classify_apply(result: Canned, expected: str) -> None:
    """ok = exit 0 + summary + no failed patch; the validation abort (exit 0 upstream) is validation_error."""
    assert classify_apply(result, result.parsed) == expected


def test_unknown_properties_warning_fails_unless_expected(tmp_path: Path) -> None:
    """A misplaced fragment is only visible as a logger warning: it fails the step unless a contains expects it."""
    warning = "WARNING  ignoring unknown properties found while validating organization config: ('x' was unexpected)"
    r = rig()
    r.cli.queue("plan", canned("plan", planned(ADD_REPO), stdout=warning))
    text = "id: u\ntitle: u\nsteps: [{fragments: {}, apply: null}]\n"
    with pytest.raises(ScenarioFailedError, match="otterdog ignored unknown properties"):
        r.engine.run(scenario(tmp_path, text, "u"))
    r = rig()
    r.cli.queue("plan", canned("plan", planned(ADD_REPO), stdout=warning))
    expected = (
        "id: e\ntitle: e\nsteps: [{fragments: {}, apply: null, plan: {contains: [ignoring unknown properties]}}]\n"
    )
    assert r.engine.run(scenario(tmp_path, expected, "e")).ok


def test_apply_delete_is_guarded_by_check_removals(tmp_path: Path) -> None:
    """``apply: {delete: true}`` runs only after BaselineManager.check_removals accepted the step's plan."""
    r = rig()
    removal = planned(obj("remove", "repository", REPO))
    r.cli.queue("plan", canned("plan", removal))
    r.cli.queue("apply", canned("apply", applied(0)))
    r.cli.queue("plan", canned("plan", NOOP))
    text = "id: del\ntitle: del\nsteps: [{fragments: {}, apply: {delete: true}}]\n"
    assert r.engine.run(scenario(tmp_path, text)).ok
    assert r.baseline.calls[0] == ("check_removals", removal) and r.cli.calls[1].kwargs["delete"] is True


def test_refused_removals_never_apply(tmp_path: Path) -> None:
    """A SafetyError of the guard fails the apply phase before otterdog runs."""
    r = rig(baseline=FakeBaseline(refuse=True))
    r.cli.queue("plan", canned("plan", planned(ADD_REPO, obj("remove", "team", "prod-team"))))
    text = "id: del\ntitle: del\nsteps: [{fragments: {}, apply: {delete: true}}]\n"
    with pytest.raises(ScenarioFailedError, match="apply: SafetyError: refusing to remove"):
        r.engine.run(scenario(tmp_path, text))
    assert [c.command for c in r.cli.calls] == ["plan"]


def test_description_changes_are_never_applied(tmp_path: Path) -> None:
    """A plan touching the org description (safety marker) is refused even without -d."""
    r = rig()
    touched = obj("change", "settings", body=['    - description = "[otterdog-e2e] test org"'])
    r.cli.queue("plan", canned("plan", planned(ADD_REPO, touched)))
    text = "id: desc\ntitle: desc\nsteps: [{fragments: {}}]\n"
    with pytest.raises(ScenarioFailedError, match="refusing to apply a plan that changes the org description"):
        r.engine.run(scenario(tmp_path, text))
    assert [c.command for c in r.cli.calls] == ["plan"]


# --- state checks ----------------------------------------------------------------------------------------------------
def test_state_checks_retry_with_the_engine_sleep(tmp_path: Path) -> None:
    """Failing checks are retried every 5 s (injected sleep) until they pass."""
    r = rig()
    _created(r)
    r.cli.queue("plan", canned("plan", NOOP))
    seen: list[str] = []
    repo = r.oracle.repo

    def late(name: str) -> dict[str, Any] | None:
        """The repo becomes visible on the third lookup."""
        seen.append(name)
        return repo(name) if len(seen) >= 3 else None

    r.oracle.repo = late  # type: ignore[method-assign]
    assert r.engine.run(scenario(tmp_path, CREATE)).ok and r.sleeps == [5.0, 5.0]


def test_state_check_timeout_fails_with_message(tmp_path: Path) -> None:
    """After 60 s of retries a failing check fails the state phase."""
    r = rig()
    _created(r)
    r.oracle.remove_repo(REPO)
    with pytest.raises(ScenarioFailedError, match=rf"state: repo\(name='{REPO}'\): not found"):
        r.engine.run(scenario(tmp_path, CREATE))
    assert sum(r.sleeps) == 60.0


# --- cleanup and infra -----------------------------------------------------------------------------------------------
def test_cleanup_modes(tmp_path: Path) -> None:
    """``cleanup: none`` and run(cleanup=False) leave objects for the janitor."""
    r = rig()
    r.cli.queue("plan", canned("plan", NOOP))
    r.cli.queue("plan", canned("plan", NOOP))
    text = "id: k\ntitle: k\ncleanup: none\nsteps: [{fragments: {}, plan: {expect: noop}}]\n"
    assert r.engine.run(scenario(tmp_path, text, "k")).ok
    auto = "id: a\ntitle: a\nsteps: [{fragments: {}, plan: {expect: noop}}]\n"
    assert r.engine.run(scenario(tmp_path, auto, "a"), cleanup=False).ok
    assert r.baseline.calls == []


@pytest.mark.parametrize(
    ("baseline", "match"),
    [
        (FakeBaseline(result=applied(failed=["REMOVE - team: 403"])), r"cleanup: CleanupError: .*1 failed patch"),
        (
            FakeBaseline(error=SafetyError("REMOVE of a protected object")),
            "cleanup: SafetyError: REMOVE of a protected",
        ),
    ],
)
def test_cleanup_failures_are_reported(tmp_path: Path, baseline: FakeBaseline, match: str) -> None:
    """A failing or refused cleanup fails an otherwise passing scenario."""
    r = rig(baseline=baseline)
    r.cli.queue("plan", canned("plan", NOOP))
    text = "id: c\ntitle: c\nsteps: [{fragments: {}, plan: {expect: noop}}]\n"
    with pytest.raises(ScenarioFailedError, match=match):
        r.engine.run(scenario(tmp_path, text))


def test_infra_errors_are_marked(tmp_path: Path) -> None:
    """Rate limits and timeouts are infra failures, never parsed as product behaviour."""
    r = rig()
    r.cli.queue("plan", canned("plan", None, infra_error="API rate limit exceeded", exit_code=2))
    text = "id: i\ntitle: i\nsteps: [{fragments: {}, plan: {expect: any}}]\n"
    with pytest.raises(ScenarioFailedError) as info:
        r.engine.run(scenario(tmp_path, text))
    assert info.value.outcome.infra and "[infra] API rate limit exceeded" in str(info.value)


def test_plan_error_detail_names_the_error_message(tmp_path: Path) -> None:
    """An unexpected plan error reports otterdog's first error message."""
    r = rig()
    broken = planned(aborted=True)
    broken.messages.append(Message("Error", "planning aborted: boom\ndetails", "box"))
    r.cli.queue("plan", canned("plan", broken, exit_code=1))
    text = "id: x\ntitle: x\nsteps: [{fragments: {}}]\n"
    with pytest.raises(
        ScenarioFailedError, match=r"expected changes, got error \(exit code 1: planning aborted: boom\)"
    ):
        r.engine.run(scenario(tmp_path, text))


def test_engine_refuses_variables_of_another_run() -> None:
    """A ``p`` variable that is not the run prefix would make cleanup and guards miss the scenario's objects."""
    with pytest.raises(ValueError, match="do not belong to run"):
        ScenarioEngine(
            cli=FakeCli(),  # type: ignore[arg-type]
            renderer=FakeRenderer(),  # type: ignore[arg-type]
            oracle=FakeOracle(),  # type: ignore[arg-type]
            run_ctx=RUN,
            capabilities=from_plan("free"),
            baseline=FakeBaseline(),  # type: ignore[arg-type]
            variables={**VARIABLES, "p": "e2e-other000"},
        )
