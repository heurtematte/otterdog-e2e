"""Offline engine: scenarios against a local, vendored template without GitHub (SPEC 12.3, OC-04).

Commands are restricted to validate --local, local-plan --local (when base_fragments are given), show --local,
show-default, canonical-diff, list-projects and --version; the CLI is built with offline=True (dummy token, unshare
sandbox when available, ``--network none`` for untrusted SUTs, fail closed in CI without a sandbox). The org is the
minimal "e2e-offline" (plan from scenario variables, default free) with no baseline repos.

Per step: render + write (the ``-BASE`` file too when base_fragments or base_config are given; first the step's
``workspace`` layout: otterdog.json or otterdog.jsonnet, extra organizations, .otterdog-defaults.json, vendored
template or not) -> validate (always run, ``-v`` with ``validate.verbose``, checked when the step gives expectations)
-> local-plan (when base_fragments or base_config; the plan's diff flags) -> show (must exit 0 unless validation is
expected to fail, ``commands.show`` gives its own expectations) -> extra ``commands``. A step's ``config`` /
``base_config`` file (rendered by render_step with the extra variables ``import_path`` and ``project``) is written as
it is instead of the rendered configuration. With ``observe`` (scenario ``observe: true`` or DifferentialRunner) every
command is recorded through the CLI's ObservationRecorder inside ``recorder.scope(scenario, step)``.

Offline settings fragments may set the organization profile (description, billing_email, name, ...: nothing is
applied): OfflineConfigRenderer moves those snippets into an overlay ``{ settings+: {...} }`` right after layer 2 and
leaves the keys out of layer 1, so a plain ``key: value`` is visible (layer 1 hides the profile keys the offline
organization does not have). A step's ``known_bug`` makes its failures expected (engine.record_phase_problems).
"""

from __future__ import annotations

import dataclasses
import functools
from collections.abc import Mapping
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e.otterdog.render import (
    ORG_PROFILE_FIELDS,
    BaselineSpec,
    ConfigFragments,
    OrgConfigRenderer,
    RenderError,
    settings_keys,
)
from otterdog_e2e.otterdog.workspace import WorkspaceLayout
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.scenarios.engine import (
    ScenarioOutcome,
    StepBug,
    StepOutcome,
    add_tail,
    command_problems,
    deterministic_run_context,
    diff_options,
    fixed_in_skip_reason,
    infra_problems,
    known_bugs_near,
    plan_problems,
    record_phase_problems,
    record_scenario_passed,
    record_step_passed,
    run_phase,
    scenario_bug,
    start_step_bug,
    step_bug,
    sut_version_of,
    unknown_properties_expected,
    unknown_properties_problem,
    validation_problems,
)
from otterdog_e2e.scenarios.model import render_step
from otterdog_e2e.settings import IDENTITY_ROLES
from otterdog_e2e.sut import template as sut_template

if TYPE_CHECKING:
    from otterdog_e2e.known_bugs import KnownBug
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.scenarios.model import Scenario, StepSpec

OFFLINE_ORG = "e2e-offline"
OFFLINE_COMMANDS = ("validate", "local-plan", "show", "show-default", "canonical-diff", "list-projects", "--version")
OFFLINE_DEFAULT_PLAN = "free"
OFFLINE_RUN_ID = "spduo000"  # base36(2025-01-01T00:00Z) + "00": identical names on every run and on both SUT sides
OFFLINE_MARKER = "[otterdog-e2e]"
OFFLINE_APP_ID = "1"  # {{ app_id }} of offline scenarios (the app id of the dummy webapp credentials)
OFFLINE_PROFILE: Mapping[str, Any] = {"description": f"{OFFLINE_MARKER} offline organization"}
OFFLINE_TEAMS: Mapping[str, str] = {
    "admin": "otterdog-admins",
    "approval": "project-leads",
    "contributors": "e2e-contributors",
}
OFFLINE_PHASES = ("render", "validate", "local-plan", "show", "commands")
BASE_SUFFIX = "-BASE"  # ConfigWorkspace.base_config_file = <org config> + BASE_SUFFIX
NO_ORG_COMMANDS = ("--version", "list-projects")
NO_LOCAL_COMMANDS = ("--version", "list-projects")  # they never load the template
SHOW_COMMAND = "show"  # commands.show: expectations of the show phase (show always runs once per step)
DEFAULT_LAYOUT = WorkspaceLayout()


def offline_run_context() -> RunContext:
    """The deterministic run context of offline and differential renders (run id OFFLINE_RUN_ID)."""
    return deterministic_run_context(OFFLINE_RUN_ID)


def observation_key(command: str) -> str:
    """Observation key of a command (``--version`` -> ``version``)."""
    return command.lstrip("-")


class OfflineConfigRenderer(OrgConfigRenderer):
    """OrgConfigRenderer of the offline organization: settings fragments may also set the profile keys
    (ORG_PROFILE_FIELDS: description, billing_email, name, ...), never ``plan`` (variables.plan).

    The snippets setting a profile key move into an overlay ``{ settings+: { <snippets> } }`` inserted before the
    step's own overlays, and layer 1 leaves those keys out (it hides the profile keys the offline organization does
    not have, which a plain ``key:`` would keep hidden). Without such snippets the output is OrgConfigRenderer's.
    """

    _shown: frozenset[str] = frozenset()

    def render(
        self, fragments: ConfigFragments | None = None, *, include_baseline: bool = True, plan: str | None = None
    ) -> str:
        """Render like OrgConfigRenderer, with the profile snippets of ``fragments.settings`` in an overlay."""
        fragments = fragments or ConfigFragments()
        profile = [snippet for snippet in fragments.settings if set(settings_keys(snippet)) & set(ORG_PROFILE_FIELDS)]
        if not profile:
            return super().render(fragments, include_baseline=include_baseline, plan=plan)
        keys = {key for snippet in profile for key in settings_keys(snippet)}
        if "plan" in keys:
            raise RenderError("settings fragments must not set ['plan'] (use variables.plan)")
        body = "".join(f"    {snippet.strip().strip(',').strip()},\n" for snippet in profile)
        overlay = "{\n  settings+: {\n" + body + "  },\n}"
        moved = dataclasses.replace(
            fragments,
            settings=[snippet for snippet in fragments.settings if snippet not in profile],
            overlays=[overlay, *fragments.overlays],
        )
        self._shown = frozenset(keys & set(ORG_PROFILE_FIELDS))
        try:
            return super().render(moved, include_baseline=include_baseline, plan=plan)
        finally:
            self._shown = frozenset()

    def profile_fields(self, plan: str) -> list[str]:
        """OrgConfigRenderer.profile_fields without the profile keys the current render's fragments set."""
        fields = super().profile_fields(plan)
        if not self._shown:
            return fields
        return [item for item in fields if item.split(":", 1)[0].strip() not in self._shown]


@dataclass
class _OfflineStep:
    """Mutable state of one offline step while its phases run."""

    scenario: Scenario
    step: StepSpec
    outcome: StepOutcome
    variables: Mapping[str, Any]
    renderer: OrgConfigRenderer
    observe: bool
    rendered: StepSpec | None = None
    unknown_ok: bool = False
    bug: StepBug | None = None


class OfflineEngine:
    """Runs tier-offline scenarios with an offline OtterdogCli.

    ``observe`` (None = follow the scenario's ``observe`` flag), ``keep_going`` (run every phase and step even after
    a failure, for differential recordings), ``skip_older_suts`` (skip scenarios whose ``fixed_in`` the SUT
    predates; DifferentialRunner turns it off) and ``known_bugs`` (None = the known_bugs.yaml above each scenario
    file; decides the steps' known_bug) may be set after construction.
    """

    def __init__(
        self,
        *,
        cli: OtterdogCli,
        workspace: ConfigWorkspace,
        template_src: Path,
        run_ctx: RunContext,
        variables: Mapping[str, Any] | None = None,
    ) -> None:
        """Bind the offline CLI, its workspace and the template sources to vendor."""
        if getattr(cli, "offline", True) is not True or getattr(cli, "identity", None) is not None:
            raise SafetyError("OfflineEngine needs an offline OtterdogCli (offline=True, no identity: dummy token)")
        self.cli = cli
        self.workspace = workspace
        self.template_src = template_src
        self.run_ctx = run_ctx
        self.variables = dict(variables or {})
        self.observe: bool | None = None
        self.keep_going = False
        self.skip_older_suts = True
        self.known_bugs: Mapping[str, KnownBug] | None = None
        self._prepared = False
        self._layout: WorkspaceLayout = getattr(workspace, "layout", DEFAULT_LAYOUT)  # what prepare() writes

    def run(self, scenario: Scenario) -> ScenarioOutcome:
        """validate --local, local-plan --local (with a BASE config), show --local per step; returns the outcome."""
        if scenario.tier != "offline":
            raise ValueError(f"scenario {scenario.id} is tier {scenario.tier}: use ScenarioEngine")
        outcome = ScenarioOutcome(scenario.id)
        if self.skip_older_suts:
            outcome.skipped = fixed_in_skip_reason(scenario, sut_version_of(self.cli))
            if outcome.skipped:
                return outcome
        prepare = StepOutcome("prepare")
        problems = run_phase(prepare, "prepare", self.prepare)
        if problems:
            outcome.steps.append(prepare)
            outcome.failures += [f"prepare: {problem}" for problem in problems]
            return outcome
        variables = self.variables_for(scenario)
        renderer = self.renderer_for(scenario)
        observe = scenario.observe if self.observe is None else self.observe
        bugs = self.bugs_for(scenario)
        version = sut_version_of(self.cli)
        inherited = scenario_bug(scenario, bugs, version)
        for step in scenario.steps:
            state = _OfflineStep(scenario, step, StepOutcome(step.name), variables, renderer, observe)
            state.bug = step_bug(step, bugs, version, inherited)
            start_step_bug(state.outcome, state.bug, version)
            outcome.steps.append(state.outcome)
            failed = self._run_step(state, outcome)
            ended = inherited is not None and step.known_bug is None and state.outcome.expected_failure
            if (failed or ended) and not self.keep_going:
                break
        record_scenario_passed(outcome, inherited)
        return outcome

    def bugs_for(self, scenario: Scenario) -> Mapping[str, KnownBug]:
        """Known bugs deciding the scenario's step known_bug: ``known_bugs``, else known_bugs_near(source)."""
        return self.known_bugs if self.known_bugs is not None else known_bugs_near(scenario.source)

    def prepare(self) -> list[str]:
        """Write otterdog.json and vendor the template sources into the org dir (once per engine)."""
        if not self._prepared:
            self.workspace.write_otterdog_json()
            sut_template.vendor_template(self.template_src, self.workspace.org_dir, self.workspace.template)
            self._prepared = True
        return []

    def use_layout(self, layout: WorkspaceLayout | None) -> None:
        """Switch the workspace to ``layout`` (None = the harness layout) when it is not the current one: write its
        configuration, then vendor the template into the org dir (``vendor``) or remove the vendored copies."""
        layout = layout or DEFAULT_LAYOUT
        if layout == self._layout:
            return
        if not hasattr(self.workspace, "layout"):
            raise ValueError(f"the workspace {type(self.workspace).__name__} does not support workspace layouts")
        self.workspace.layout = layout
        self.workspace.write_otterdog_json()
        if layout.vendor:
            sut_template.vendor_template(self.template_src, self.workspace.org_dir, self.workspace.template)
        else:
            self.workspace.clean_template_cache()
        self._layout = layout

    def plan_for(self, scenario: Scenario) -> str:
        """Plan of the offline org: variables.plan of the scenario, then of the engine, default free."""
        return scenario.plan_override or str(self.variables.get("plan") or OFFLINE_DEFAULT_PLAN)

    def variables_for(self, scenario: Scenario) -> dict[str, Any]:
        """Jinja variables: run context, offline org/plan, placeholder logins/teams, the template import path and the
        project (config files), engine then scenario variables."""
        base: dict[str, Any] = {
            **self.run_ctx.template_vars(),
            "org": self.workspace.org,
            "logins": {role: f"e2e-offline-{role.replace('_', '-')}" for role in IDENTITY_ROLES},
            "app_slug": "e2e-offline-app",
            "app_id": OFFLINE_APP_ID,
            "teams": dict(OFFLINE_TEAMS),
            "import_path": self.workspace.template.import_path,
            "project": self.workspace.project,
        }
        return {**base, **self.variables, **scenario.variables, "plan": self.plan_for(scenario)}

    def renderer_for(self, scenario: Scenario) -> OrgConfigRenderer:
        """Renderer of the minimal offline org (no baseline repos/teams; the template's defaults only; settings
        fragments may set the profile: OfflineConfigRenderer)."""
        return OfflineConfigRenderer(
            template=self.workspace.template,
            org=self.workspace.org,
            plan=self.plan_for(scenario),
            org_profile=OFFLINE_PROFILE,
            baseline=BaselineSpec(),
            marker=OFFLINE_MARKER,
            hide_cache_limit=False,
            project=self.workspace.project,
        )

    def _run_step(self, state: _OfflineStep, outcome: ScenarioOutcome) -> bool:
        """Run the phases of one step inside the recorder scope; returns True when a phase failed (the expected
        failures of a known-bug step stop the step only)."""
        failed = False
        with self._scope(state):
            for phase in OFFLINE_PHASES:
                problems = run_phase(state.outcome, phase, functools.partial(self._phase, phase, state))
                if problems:
                    add_tail(state.outcome, phase)
                    failures = record_phase_problems(outcome, state.outcome, phase, problems, state.bug)
                    failed = failed or bool(failures)
                    if not self.keep_going or phase == "render":
                        break
            else:
                record_step_passed(outcome, state.outcome, state.bug)
        return failed

    def _scope(self, state: _OfflineStep) -> AbstractContextManager[None]:
        """Recorder scope (scenario, step) when observing, else a no-op."""
        recorder = getattr(self.cli, "recorder", None)
        if not state.observe or recorder is None:
            return nullcontext()
        return recorder.scope(state.scenario.id, state.step.name)

    def _key(self, state: _OfflineStep, command: str) -> str | None:
        """Observation key of ``command`` when observing."""
        return observation_key(command) if state.observe else None

    def _phase(self, phase: str, state: _OfflineStep) -> list[str] | None:
        """Dispatch one phase."""
        handlers = {
            "render": self._render,
            "validate": self._validate,
            "local-plan": self._local_plan,
            "show": self._show,
            "commands": self._commands,
        }
        return handlers[phase](state)

    def _render(self, state: _OfflineStep) -> list[str]:
        """Render the step (Jinja once), switch to its workspace layout, then write the org config (the step's config
        file, else the rendered fragments), plus the -BASE config (base_config file, else base_fragments) when the
        step has one."""
        rendered = state.rendered = render_step(state.step, state.variables)
        state.unknown_ok = unknown_properties_expected(rendered)
        self.use_layout(rendered.workspace)
        plan = self.plan_for(state.scenario)
        if rendered.config is not None:
            self.workspace.write_org_config(rendered.config)
        else:
            self.workspace.write_org_config(state.renderer.render(rendered.fragments, plan=plan))
        if rendered.base_config is not None:
            self.workspace.write_base_config(rendered.base_config)
        elif rendered.base_fragments is not None:
            self.workspace.write_base_config(state.renderer.render(rendered.base_fragments, plan=plan))
        return []

    def _validate(self, state: _OfflineStep) -> list[str]:
        """``validate --local [-v]``: always run; expectations only when the step gives them."""
        assert state.rendered is not None
        spec = state.rendered.validate
        verbose = spec is not None and spec.verbose
        result = self.cli.validate(local=True, verbose=verbose, observe=self._key(state, "validate"))
        state.outcome.results["validate"] = result
        if spec is not None:
            return validation_problems(spec, result, unknown_ok=state.unknown_ok)
        return _unchecked_problems(result, unknown_ok=state.unknown_ok)

    def _local_plan(self, state: _OfflineStep) -> list[str] | None:
        """``local-plan -s -BASE --local`` with the plan's diff flags when the step has base_fragments or a
        base_config file; contains/not_contains are checked even when the plan fails (validation errors, errors)."""
        assert state.rendered is not None
        if state.rendered.base_fragments is None and state.rendered.base_config is None:
            return None
        spec = state.rendered.plan
        options = diff_options(spec, repo_filter=spec.repo_filter if spec is not None else None)
        result = self.cli.local_plan_with(
            options, suffix=BASE_SUFFIX, local=True, observe=self._key(state, "local-plan")
        )
        state.outcome.results["local-plan"] = result
        if spec is None:
            return _unchecked_problems(result, unknown_ok=state.unknown_ok)
        problems = infra_problems(result)
        if problems:
            return problems
        return plan_problems(spec, result, result.plan(), needles=None, unknown_ok=state.unknown_ok)

    def _show(self, state: _OfflineStep) -> list[str]:
        """``show --local``: recorded; checked against ``commands.show`` when given, else it must exit 0 unless the
        step expects validation to fail (``validate.ok`` false or ``plan.expect`` validation_error)."""
        assert state.rendered is not None
        result = self.cli.run("show", local=True, observe=self._key(state, "show"))
        state.outcome.results["show"] = result
        spec = state.rendered.commands.get(SHOW_COMMAND)
        if spec is not None:
            return command_problems(SHOW_COMMAND, spec, result)
        if _expects_invalid(state.rendered):
            return []
        problems = infra_problems(result)
        if not problems and result.exit_code != 0:
            problems.append(f"show exited {result.exit_code}")
        return problems

    def _commands(self, state: _OfflineStep) -> list[str] | None:
        """Extra commands of the step (show-default, canonical-diff, list-projects, --version; ``show`` is the show
        phase's)."""
        assert state.rendered is not None
        commands = {name: spec for name, spec in state.rendered.commands.items() if name != SHOW_COMMAND}
        if not commands:
            return None
        problems: list[str] = []
        for command, spec in commands.items():
            result = self.cli.run(
                command,
                org=command not in NO_ORG_COMMANDS,
                local=command not in NO_LOCAL_COMMANDS,
                observe=self._key(state, command),
            )
            state.outcome.results[command] = result
            problems += command_problems(command, spec, result)
        return problems


def _expects_invalid(step: StepSpec) -> bool:
    """True when the step expects validation to fail: ``validate.ok`` false or ``plan.expect`` validation_error (the
    configuration may not even load, so show fails too)."""
    if step.validate is not None and step.validate.ok is False:
        return True
    return step.plan is not None and step.plan.expect == "validation_error"


def _unchecked_problems(result: CliResult, *, unknown_ok: bool) -> list[str]:
    """Problems of a command run without expectations: infra errors and ignored unknown properties."""
    problems = infra_problems(result)
    unknown = unknown_properties_problem(result, expected=unknown_ok)
    return problems + ([unknown] if unknown else [])
