"""OfflineEngine extensions: validate -v, local-plan diff flags, plan assertions when the plan fails (show is not
checked when validation is expected to fail), ``commands.show``, per-step workspace layouts, offline profile settings
(OfflineConfigRenderer) and per-step known bugs."""

from __future__ import annotations

import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.known_bugs import KnownBug
from otterdog_e2e.otterdog import output as od_output
from otterdog_e2e.otterdog.output import PlanObject, PlanResult, ValidationResult
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments, RenderError
from otterdog_e2e.otterdog.runner import CliResult, DiffOptions
from otterdog_e2e.otterdog.workspace import WorkspaceLayout
from otterdog_e2e.scenarios.model import Scenario, load_scenario, render_step
from otterdog_e2e.scenarios.offline import (
    OFFLINE_MARKER,
    OFFLINE_ORG,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    OfflineEngine,
    offline_run_context,
)
from otterdog_e2e.sut import template as sut_template
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli, FakeWorkspace

RUN = offline_run_context()


@pytest.fixture(autouse=True)
def vendored(monkeypatch: pytest.MonkeyPatch) -> list[Path]:
    """normalize_text is an identity; vendor_template records the org dirs it vendors into."""
    calls: list[Path] = []
    monkeypatch.setattr(od_output, "normalize_text", lambda text, ctx=None: text)
    monkeypatch.setattr(sut_template, "vendor_template", lambda src, org_dir, ref: calls.append(org_dir))
    return calls


@dataclass
class Canned(CliResult):
    """A CliResult whose parsed form is given directly."""

    parsed: Any = None

    def plan(self) -> Any:
        """The canned PlanResult."""
        return self.parsed

    def validation(self) -> Any:
        """The canned ValidationResult."""
        return self.parsed


def canned(command: str, parsed: Any = None, *, stdout: str = "", exit_code: int = 0) -> Canned:
    """A Canned result."""
    return Canned(["otterdog", command], exit_code, stdout, "", 0.01, Path("/nonexistent"), parsed=parsed)


def validated(ok: bool = True, errors: int = 0, infos: int | None = 0) -> ValidationResult:
    """A ValidationResult."""
    return ValidationResult(ok, infos, 0, errors, [], False, "")


def aborted() -> PlanResult:
    """A local-plan stopped by validation errors."""
    return PlanResult(None, None, None, [], True, validated(ok=False, errors=1), [], "")


def cli(**kw: Any) -> FakeCli:
    """A strict FakeCli of the offline org with a FakeWorkspace."""
    fake = FakeCli(org=OFFLINE_ORG, workspace=FakeWorkspace(OFFLINE_ORG), strict=kw.pop("strict", True))
    fake.recorder = None  # type: ignore[attr-defined]
    return fake


def engine(fake: FakeCli, *, bugs: dict[str, KnownBug] | None = None) -> OfflineEngine:
    """OfflineEngine over the fake (known bugs explicit)."""
    runner = OfflineEngine(
        cli=fake,  # type: ignore[arg-type]
        workspace=fake.workspace,
        template_src=Path("/nonexistent/template"),
        run_ctx=RUN,
    )
    runner.known_bugs = bugs if bugs is not None else {}
    return runner


def write(tmp_path: Path, text: str, name: str = "case") -> Scenario:
    """Load an offline scenario."""
    path = tmp_path / "offline" / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return load_scenario(path)


# --- flags -----------------------------------------------------------------------------------------------------------
def test_validate_verbose_and_local_plan_flags(tmp_path: Path) -> None:
    """validate gets verbose, local-plan the plan's diff flags."""
    fake = cli()
    fake.queue("validate", canned("validate", validated(infos=2)))
    fake.queue("local-plan", canned("local-plan", PlanResult(0, 0, 0, [], False, None, [], "")))
    fake.queue("show", canned("show"))
    text = """
    id: o.flags
    title: flags
    steps:
      - base_fragments: {}
        fragments: {}
        validate: {verbose: true, infos: 2}
        plan: {expect: noop, repo_filter: "{{ p }}-a", only_secrets: true, update_secrets: true, verbose: true}
    """
    assert engine(fake).run(write(tmp_path, text)).ok
    validate, local_plan, _show = fake.calls
    assert validate.kwargs["verbose"] is True and validate.kwargs["local"] is True
    assert local_plan.kwargs["options"] == DiffOptions(
        f"{RUN.prefix}-a", update_secrets=True, only_secrets=True, verbose=True
    )
    assert local_plan.kwargs["suffix"] == "-BASE" and local_plan.kwargs["local"] is True


def test_validation_error_plans_assert_their_output_and_skip_the_show_check(tmp_path: Path) -> None:
    """plan.expect validation_error: contains/not_contains are checked, show may fail (the config may not load)."""
    fake = cli()
    fake.queue("validate", canned("validate", validated(ok=False, errors=1), exit_code=1))
    fake.queue("local-plan", canned("local-plan", aborted(), stdout="Planning aborted due to validation errors.\nboom"))
    fake.queue("show", canned("show", exit_code=1))
    text = """
    id: o.invalid
    title: invalid
    steps:
      - base_fragments: {}
        fragments: {}
        plan: {expect: validation_error, contains: [boom], not_contains: ["Plan:"], exit_code: 1}
    """
    outcome = engine(fake).run(write(tmp_path, text))
    assert outcome.failures == ["step 'step-1' local-plan: expected exit code 1, got 0"]
    fake = cli()
    fake.queue("validate", canned("validate", validated(ok=False, errors=1), exit_code=1))
    fake.queue("local-plan", canned("local-plan", aborted(), stdout="Planning aborted", exit_code=1))
    fake.queue("show", canned("show", exit_code=1))
    assert engine(fake).run(write(tmp_path, text.replace("[boom]", "[aborted]"), name="b")).ok


def test_commands_show_checks_the_show_phase(tmp_path: Path) -> None:
    """commands.show replaces the default show check; show runs once."""
    fake = cli()
    fake.queue("validate", canned("validate", validated()))
    fake.queue("show", canned("show", stdout="Showing organization resources:", exit_code=0))
    text = (
        "id: o.show\ntitle: s\nsteps: [{fragments: {}, commands: {show: {contains: [Showing], not_contains: [x]}}}]\n"
    )
    assert engine(fake).run(write(tmp_path, text)).ok
    assert [call.command for call in fake.calls] == ["validate", "show"]
    fake = cli()
    fake.queue("validate", canned("validate", validated()))
    fake.queue("show", canned("show", stdout="nothing"))
    outcome = engine(fake).run(write(tmp_path, text, name="t"))
    assert outcome.failures == ["step 'step-1' show: show: output does not contain 'Showing'"]


# --- workspace layouts -----------------------------------------------------------------------------------------------
LAYOUTS = """
id: o.layouts
title: layouts
steps:
  - name: jsonnet
    fragments: {}
    workspace: {format: jsonnet, orgs: [e2e-offline-2], defaults_override: {jsonnet: {config_dir: orgs-override}}}
  - name: no-vendor
    fragments: {}
    workspace: {vendor: false}
    validate: {ok: false, contains: [does not exist]}
  - name: default
    fragments: {}
"""


def test_each_step_gets_its_workspace_layout(tmp_path: Path, vendored: list[Path]) -> None:
    """Layouts switch per step (config written again, template vendored or removed), back to the harness layout."""
    fake = cli(strict=False)
    workspace: FakeWorkspace = fake.workspace
    fake.queue("validate", canned("validate", validated()))
    fake.queue("validate", canned("validate", validated(ok=False), stdout="template file 'x' does not exist"))
    fake.queue("validate", canned("validate", validated()))
    outcome = engine(fake).run(write(tmp_path, LAYOUTS))
    assert outcome.ok, outcome.failures
    root = workspace.root
    assert workspace.otterdog_json_writes == 4  # prepare + three switches
    first, second, third = workspace.documents[1:]
    assert [entry["github_id"] for entry in first["organizations"]] == [OFFLINE_ORG, "e2e-offline-2"]
    assert len(second["organizations"]) == len(third["organizations"]) == 1
    assert vendored == [root / "orgs" / OFFLINE_ORG, root / "orgs-override" / OFFLINE_ORG, root / "orgs" / OFFLINE_ORG]
    assert workspace.cleaned == 1 and workspace.layout.is_default and root / "otterdog.json" in workspace.files
    jsonnet_write = workspace.writes[0]
    assert "orgs.newOrg('e2e-offline', 'e2e-offline')" in jsonnet_write


def test_steps_without_workspace_never_touch_the_layout(tmp_path: Path) -> None:
    """Stand-in workspaces without a layout keep working while no step asks for one; a step that does fails."""

    class Minimal:
        """A workspace without layouts."""

        org = OFFLINE_ORG
        project = OFFLINE_ORG
        template = offline_template()
        org_dir = Path("/nonexistent/orgs/e2e-offline")

        def write_otterdog_json(self) -> Path:
            """Nothing."""
            return self.org_dir

        def write_org_config(self, text: str) -> Path:
            """Nothing."""
            return self.org_dir

    fake = FakeCli(org=OFFLINE_ORG, workspace=Minimal())
    runner = OfflineEngine(cli=fake, workspace=fake.workspace, template_src=Path("/x"), run_ctx=RUN)  # type: ignore[arg-type]
    runner.known_bugs = {}
    assert runner.run(write(tmp_path, "id: o.m\ntitle: m\nsteps: [{fragments: {}}]\n")).ok
    outcome = runner.run(
        write(tmp_path, "id: o.n\ntitle: n\nsteps: [{fragments: {}, workspace: {vendor: false}}]\n", "n")
    )
    assert outcome.failures and "does not support workspace layouts" in outcome.failures[0]


def test_a_preset_workspace_layout_is_restored_by_default_steps(tmp_path: Path, vendored: list[Path]) -> None:
    """A workspace left in another layout (an earlier scenario on the same workspace) goes back to the default."""
    fake = cli(strict=False)
    fake.workspace.layout = WorkspaceLayout(format="jsonnet")
    assert engine(fake).run(write(tmp_path, "id: o.p\ntitle: p\nsteps: [{fragments: {}}]\n")).ok
    assert fake.workspace.layout.is_default and fake.workspace.otterdog_json_writes == 2


# --- profile settings ------------------------------------------------------------------------------------------------
def renderer() -> OfflineConfigRenderer:
    """The offline renderer of the engine."""
    return OfflineConfigRenderer(
        template=offline_template(),
        org=OFFLINE_ORG,
        plan="free",
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
    )


def test_profile_settings_move_to_an_overlay_and_leave_layer_one() -> None:
    """description/billing_email/name snippets become '{ settings+: {...} }' before the step's overlays; layer 1 drops
    those keys (a hidden 'name:: null' would keep 'name: x' hidden); other settings stay in layer 2."""
    fragments = ConfigFragments(
        settings=[
            "description: std.repeat('d', 161),",
            "name: 'E2E', blog: 'https://x.invalid'",
            "web_commit_signoff_required: true",
        ],
        overlays=["{ _e2e:: 1 }"],
    )
    text = renderer().render(fragments)
    assert (
        "settings+: {\n    description: std.repeat('d', 161),\n    name: 'E2E', blog: 'https://x.invalid',\n  },\n}"
        in text
    )
    assert text.index("description: std.repeat") < text.index("{ _e2e:: 1 }")
    hidden = {line.strip() for line in text.splitlines()}
    assert "name:: null," not in hidden and "blog:: null," not in hidden and "billing_email:: null," in hidden
    assert '"[otterdog-e2e] offline organization"' not in text  # layer 1 no longer sets the description
    assert "    web_commit_signoff_required: true," in text
    plain = renderer().render(ConfigFragments(settings=["web_commit_signoff_required: true"]))
    assert "name:: null," in {line.strip() for line in plain.splitlines()}
    assert '"[otterdog-e2e] offline organization"' in plain


def test_the_plan_is_never_a_profile_setting() -> None:
    """A snippet setting the plan next to a profile key is refused (the plan comes from variables.plan)."""
    with pytest.raises(RenderError, match=r"must not set \['plan'\]"):
        renderer().render(ConfigFragments(settings=["description: 'x', plan: 'team'"]))


def test_the_engine_renders_offline_profile_steps(tmp_path: Path) -> None:
    """End to end: the loader accepts the profile fragment offline and the engine writes the overlay."""
    fake = cli()
    fake.queue("validate", canned("validate", validated(ok=False, errors=1), exit_code=1))
    fake.queue("show", canned("show"))
    text = """
    id: o.profile
    title: profile
    steps:
      - fragments: {settings: ["description: std.repeat('d', 161)"]}
        validate: {ok: false, errors: 1}
    """
    assert engine(fake).run(write(tmp_path, text)).ok
    assert "settings+: {\n    description: std.repeat('d', 161),\n  }," in fake.workspace.writes[0]


# --- known bugs ------------------------------------------------------------------------------------------------------
KB = """
id: o.kb
title: kb
steps:
  - name: crash
    known_bug: KB-025
    fragments: {secrets: ["orgs.newOrgSecret('{{ P }}_C') { value: 'pass:a:b' }"]}
    validate: {ok: true}
  - name: after
    fragments: {}
    validate: {ok: true}
"""


def test_offline_known_bug_steps_are_expected_failures(tmp_path: Path) -> None:
    """The crash step's failure is expected, the next step runs; raise_for_failures xfails with the bug."""
    fake = cli()
    fake.queue("validate", canned("validate", validated(ok=False), stdout="too many values to unpack", exit_code=2))
    fake.queue("validate", canned("validate", validated()))
    fake.queue("show", canned("show"))
    bug = KnownBug("KB-025", "a value with two ':' crashes validation")
    outcome = engine(fake, bugs={"KB-025": bug}).run(write(tmp_path, KB))
    assert outcome.ok and [step.name for step in outcome.steps] == ["crash", "after"]
    assert outcome.expected_failures == [
        "step 'crash' validate: expected validation to succeed, it failed (0 error(s), 0 warning(s))"
    ]
    assert [call.command for call in fake.calls] == ["validate", "validate", "show"]  # the crash step stops there
    with pytest.raises(pytest.xfail.Exception, match="KB-025: a value with two ':' crashes validation"):
        outcome.raise_for_failures()


def test_offline_keep_going_records_every_phase_of_a_known_bug_step(tmp_path: Path) -> None:
    """keep_going (differential): the phases after an expected failure run too, nothing is a failure."""
    fake = cli(strict=False)
    fake.queue("validate", canned("validate", validated(ok=False), exit_code=2))
    runner = engine(fake, bugs={})
    runner.keep_going = True
    outcome = runner.run(write(tmp_path, KB))
    assert outcome.ok and outcome.expected_bugs == {"crash": "KB-025: not listed in known_bugs.yaml"}
    assert [call.command for call in fake.calls] == ["validate", "show", "validate", "show"]


def test_a_known_bug_step_that_passes_offline_is_recorded(tmp_path: Path) -> None:
    """No failure in a known-bug step: unexpected pass."""
    fake = cli(strict=False)
    outcome = engine(fake, bugs={"KB-025": KnownBug("KB-025", "t")}).run(write(tmp_path, KB))
    assert outcome.unexpected_passes == ["KB-025: t (step 'crash')"] and not outcome.expected_failures


def test_render_step_keeps_the_offline_rules(tmp_path: Path) -> None:
    """render_step of an offline step accepts the offline-only dummies and profile keys (step.offline)."""
    step = write(tmp_path, KB).steps[0]
    assert step.offline and render_step(step, {**RUN.template_vars(), "plan": "free"}).fragments.secrets


# --- the real OtterdogCli --------------------------------------------------------------------------------------------
def test_layout_config_file_reaches_the_real_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the jsonnet layout the real CLI gets ``-c <root>/otterdog.jsonnet``; the file exists on disk."""
    from otterdog_e2e import procs
    from otterdog_e2e.otterdog import runner as runner_module
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import HarnessSettings
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.spec import ResolvedSut, SutSpec

    seen: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        """Answer validate/show with success."""
        seen.append(list(argv))
        return procs.CompletedProcess(argv, 0, "Validating organization configurations:\n  Validation succeeded\n", "")

    monkeypatch.setattr(procs, "run", run)
    monkeypatch.setattr(runner_module, "_unshare_available", lambda: False)
    monkeypatch.delenv("CI", raising=False)
    sut = ResolvedSut(SutSpec("release:latest", "release", "latest"), "v1.6.1", "b" * 40, "1.6.1", "1.6.1",
                      tmp_path / "src", "https://github.com/eclipse-csi/otterdog", True)  # fmt: skip
    settings = HarnessSettings(tmp_path, tmp_path / "c", tmp_path / "a", "eclipse-csi/otterdog", tmp_path, tmp_path)
    workspace = ConfigWorkspace(tmp_path / "ws", org=OFFLINE_ORG, template=offline_template(), config_repo=".otterdog")
    real = OtterdogCli(
        InstalledCli(sut, "host", None, tmp_path / "otterdog", None, ""),
        workspace,
        verified=None,
        identity=None,
        scratch=tmp_path / "scratch",
        artifacts_dir=tmp_path / "artifacts",
        settings=settings,
        offline=True,
    )
    text = "id: o.real\ntitle: r\nsteps: [{fragments: {}, workspace: {format: jsonnet}}]\n"
    runner = OfflineEngine(cli=real, workspace=workspace, template_src=tmp_path, run_ctx=RUN)
    runner.known_bugs = {}
    monkeypatch.setattr(sut_template, "vendor_template", lambda *args: None)
    assert runner.run(write(tmp_path, text)).ok
    assert seen[0][1:3] == ["validate", "-c"] and seen[0][3] == str((tmp_path / "ws" / "otterdog.jsonnet").resolve())
    assert (tmp_path / "ws" / "otterdog.jsonnet").is_file() and not (tmp_path / "ws" / "otterdog.json").exists()
    assert workspace.org_config_file.is_file()


def test_plan_objects_are_parsed_after_layout_switches(tmp_path: Path) -> None:
    """A smoke check of the PlanObject helpers used above (keeps the imports honest)."""
    obj = PlanObject("add", "repository", "name", f"{RUN.prefix}-a", None, None, "+ add repository", [])
    assert obj.run_id == RUN.run_id
