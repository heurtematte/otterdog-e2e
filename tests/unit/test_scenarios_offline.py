"""OfflineEngine (validate/local-plan/show --local, observation scopes) and DifferentialRunner (never applies)."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.otterdog import output as od_output
from otterdog_e2e.otterdog.output import PlanObject, PlanResult, ValidationResult
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.scenarios import offline as offline_module
from otterdog_e2e.scenarios.engine import DifferentialRunner, SutSide
from otterdog_e2e.scenarios.model import Scenario, load_scenario
from otterdog_e2e.scenarios.offline import OFFLINE_ORG, OFFLINE_RUN_ID, OfflineEngine, offline_run_context
from otterdog_e2e.sut import template as sut_template
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli, make_run_context

RUN = offline_run_context()


@pytest.fixture(autouse=True)
def _fakes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[Path, Path]]:
    """normalize_text is an identity; vendor_template only records its arguments."""
    vendored: list[tuple[Path, Path]] = []

    def normalize_text(text: str, ctx: Any = None) -> str:
        """Identity."""
        return text

    def vendor_template(template_src_dir: Path, org_dir: Path, ref: Any) -> None:
        """Record the vendoring."""
        vendored.append((template_src_dir, org_dir))

    monkeypatch.setattr(od_output, "normalize_text", normalize_text)
    monkeypatch.setattr(sut_template, "vendor_template", vendor_template)
    return vendored


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
    """A Canned result of ``otterdog <command>``."""
    return Canned(["otterdog", command], exit_code, stdout, "", 0.01, Path("/nonexistent"), parsed=parsed)


def validated(ok: bool = True, errors: int = 0) -> ValidationResult:
    """A ValidationResult."""
    return ValidationResult(ok, 0, 0, errors, [], False, "")


def local_plan(*objects: PlanObject) -> PlanResult:
    """A local-plan PlanResult with raw counts of the objects."""
    adds = sum(1 for o in objects if o.op == "add")
    return PlanResult(adds, 0, 0, list(objects), False, None, [], "")


class FakeWorkspace:
    """ConfigWorkspace stand-in recording the files written."""

    def __init__(self, org: str = OFFLINE_ORG, root: Path = Path("/nonexistent/ws")) -> None:
        """Bind to the offline org."""
        self.org = org
        self.project = org
        self.template = offline_template()
        self.org_dir = root / "orgs" / org
        self.writes: list[str] = []
        self.base_writes: list[str] = []
        self.otterdog_json_writes = 0

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


class FakeRecorder:
    """ObservationRecorder stand-in recording its scopes."""

    def __init__(self) -> None:
        """No scope yet."""
        self.scopes: list[tuple[str, str | None]] = []

    @contextmanager
    def scope(self, scenario: str, step: str | None = None) -> Iterator[None]:
        """Record the scope."""
        self.scopes.append((scenario, step))
        yield

    def record(self, kind: str, key: str, content: Any, *, meta: Any = None) -> None:
        """Unused: FakeCli does not record."""


def offline_cli(org: str = OFFLINE_ORG, *, recorder: FakeRecorder | None = None, strict: bool = True) -> FakeCli:
    """A FakeCli with a workspace (and a recorder attribute like OtterdogCli)."""
    cli = FakeCli(org=org, workspace=FakeWorkspace(org), strict=strict)
    cli.recorder = recorder  # type: ignore[attr-defined]
    return cli


def write_scenario(tmp_path: Path, text: str, tier_dir: str = "offline", name: str = "case") -> Scenario:
    """Load a scenario written under tmp_path/<tier_dir>/."""
    path = tmp_path / tier_dir / f"{name}.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return load_scenario(path)


def engine(cli: FakeCli, **kw: Any) -> OfflineEngine:
    """An OfflineEngine over a fake CLI (template sources: a fake path)."""
    return OfflineEngine(
        cli=cli,  # type: ignore[arg-type]
        workspace=cli.workspace,
        template_src=Path("/nonexistent/template"),
        run_ctx=RUN,
        **kw,
    )


LPLAN = """
id: O-LPLAN-ADD
title: local-plan add
observe: true
steps:
  - name: add
    base_fragments: {}
    fragments:
      repositories: ["orgs.newRepo('{{ p }}-basic') { description: 'e2e basic' }"]
    validate: {}
    plan: {expect: changes, counts: {add: 1}, contains: ['add repository[name="{{ p }}-basic"]']}
    commands: {show-default: {}, --version: {contains: [version]}}
"""


def queue_lplan(cli: FakeCli) -> None:
    """Results of one LPLAN step."""
    header = f'  + add repository[name="{RUN.prefix}-basic"] {{'
    add = PlanObject("add", "repository", "name", f"{RUN.prefix}-basic", None, None, header, [])
    cli.queue("validate", canned("validate", validated(), stdout="Validation succeeded"))
    cli.queue("local-plan", canned("local-plan", local_plan(add), stdout=header))
    cli.queue("show", canned("show"))
    cli.queue("show-default", canned("show-default"))
    cli.queue("--version", canned("--version", stdout="otterdog.sh, version 1.6.1"))


# --- offline engine --------------------------------------------------------------------------------------------------
def test_offline_step_commands_and_flags(tmp_path: Path, _fakes: list[tuple[Path, Path]]) -> None:
    """validate --local, local-plan -s -BASE --local, show --local, then the extra commands."""
    cli = offline_cli()
    queue_lplan(cli)
    outcome = engine(cli).run(write_scenario(tmp_path, LPLAN))
    assert outcome.ok, outcome.failures
    assert [(c.command, c.kwargs.get("local")) for c in cli.calls] == [
        ("validate", True),
        ("local-plan", True),
        ("show", True),
        ("show-default", True),
        ("--version", False),
    ]
    assert cli.calls[1].kwargs["suffix"] == "-BASE"
    assert cli.calls[3].kwargs["org"] is True and cli.calls[4].kwargs["org"] is False
    workspace = cli.workspace
    assert workspace.otterdog_json_writes == 1 and _fakes == [(Path("/nonexistent/template"), workspace.org_dir)]
    assert len(workspace.writes) == 1 and len(workspace.base_writes) == 1
    assert set(outcome.steps[0].results) == {"validate", "local-plan", "show", "show-default", "--version"}


def test_offline_renders_the_minimal_org(tmp_path: Path) -> None:
    """The real renderer: minimal e2e-offline org, plan free by default, deterministic run prefix, no baseline."""
    cli = offline_cli()
    queue_lplan(cli)
    engine(cli).run(write_scenario(tmp_path, LPLAN))
    head, base = cli.workspace.writes[0], cli.workspace.base_writes[0]
    assert "orgs.newOrg('e2e-offline', 'e2e-offline')" in head and '"free"' in head
    assert f"orgs.newRepo('e2e-{OFFLINE_RUN_ID}-basic')" in head and f"e2e-{OFFLINE_RUN_ID}-basic" not in base
    assert "teams+:" not in head and "_repositories+:" not in head.split("} {")[0] and "[otterdog-e2e]" in head


def test_offline_plan_comes_from_variables(tmp_path: Path) -> None:
    """``variables.plan`` (scenario first, then engine) sets the offline org plan."""
    cli = offline_cli()
    cli.queue("validate", canned("validate", validated()))
    cli.queue("show", canned("show"))
    scenario = write_scenario(tmp_path, "id: p\ntitle: p\nvariables: {plan: enterprise}\nsteps: [{fragments: {}}]\n")
    assert engine(cli, variables={"plan": "team"}).run(scenario).ok
    assert '"enterprise"' in cli.workspace.writes[0]
    cli = offline_cli()
    cli.queue("validate", canned("validate", validated()))
    cli.queue("show", canned("show"))
    plain = write_scenario(tmp_path, "id: q\ntitle: q\nsteps: [{fragments: {}}]\n", name="q")
    assert engine(cli, variables={"plan": "team"}).run(plain).ok and '"team"' in cli.workspace.writes[0]


def test_offline_failure_returns_the_outcome_and_aborts(tmp_path: Path) -> None:
    """A failing phase stops the scenario (no exception: run() returns the outcome)."""
    cli = offline_cli()
    cli.queue("validate", canned("validate", validated(ok=False, errors=1), exit_code=1))
    text = """
    id: O-VAL
    title: v
    steps:
      - {name: one, fragments: {}, validate: {ok: true}}
      - {name: two, fragments: {}}
    """
    outcome = engine(cli).run(write_scenario(tmp_path, text))
    assert not outcome.ok and [c.command for c in cli.calls] == ["validate"]
    assert outcome.failures == [
        "step 'one' validate: expected validation to succeed, it failed (1 error(s), 0 warning(s))"
    ]
    with pytest.raises(AssertionError, match="scenario O-VAL failed"):
        outcome.raise_for_failures()


def test_show_may_fail_when_validation_is_expected_to_fail(tmp_path: Path) -> None:
    """Invalid configs (O-VAL-SYNTAX) still run show for observation, without asserting on it."""
    cli = offline_cli()
    cli.queue("validate", canned("validate", validated(ok=False), stdout="failed to load configuration", exit_code=1))
    cli.queue("show", canned("show", exit_code=2))
    text = "id: s\ntitle: s\nsteps: [{fragments: {}, validate: {ok: false, contains: [failed to load]}}]\n"
    assert engine(cli).run(write_scenario(tmp_path, text)).ok
    cli = offline_cli()
    cli.queue("validate", canned("validate", validated()))
    cli.queue("show", canned("show", exit_code=2))
    other = write_scenario(tmp_path, "id: t\ntitle: t\nsteps: [{fragments: {}}]\n", name="t")
    assert engine(cli).run(other).failures == ["step 'step-1' show: show exited 2"]


def test_unknown_properties_fail_validate_without_expectations(tmp_path: Path) -> None:
    """The misplaced-fragment warning fails a step even when it has no validate expectations."""
    cli = offline_cli()
    warning = "WARNING  ignoring unknown properties found while validating organization config"
    cli.queue("validate", canned("validate", validated(), stdout=warning))
    outcome = engine(cli).run(write_scenario(tmp_path, "id: u\ntitle: u\nsteps: [{fragments: {}}]\n"))
    assert len(outcome.failures) == 1 and "ignored unknown properties" in outcome.failures[0]


def test_observe_scopes_and_keys(tmp_path: Path) -> None:
    """observe: true records every command under recorder.scope(scenario, step) with stable keys."""
    recorder = FakeRecorder()
    cli = offline_cli(recorder=recorder)
    queue_lplan(cli)
    assert engine(cli).run(write_scenario(tmp_path, LPLAN)).ok
    assert recorder.scopes == [("O-LPLAN-ADD", "add")]
    keys = [c.kwargs.get("observe") for c in cli.calls]
    assert keys == ["validate", "local-plan", "show", "show-default", "version"]


def test_no_observation_without_observe(tmp_path: Path) -> None:
    """Scenarios without observe: true record nothing (no scope, no keys)."""
    recorder = FakeRecorder()
    cli = offline_cli(recorder=recorder)
    cli.queue("validate", canned("validate", validated()))
    cli.queue("show", canned("show"))
    assert engine(cli).run(write_scenario(tmp_path, "id: n\ntitle: n\nsteps: [{fragments: {}}]\n")).ok
    assert recorder.scopes == [] and all(c.kwargs.get("observe") is None for c in cli.calls)


def test_keep_going_runs_every_phase(tmp_path: Path) -> None:
    """keep_going (differential recordings) continues after a failed phase and step."""
    cli = offline_cli()
    for _ in range(2):
        cli.queue("validate", canned("validate", validated(ok=False, errors=1), exit_code=1))
        cli.queue("show", canned("show"))
    text = "id: k\ntitle: k\nsteps: [{name: a, fragments: {}, validate: {}}, {name: b, fragments: {}, validate: {}}]\n"
    runner = engine(cli)
    runner.keep_going = True
    outcome = runner.run(write_scenario(tmp_path, text))
    assert [c.command for c in cli.calls] == ["validate", "show", "validate", "show"] and len(outcome.failures) == 2


def test_offline_engine_refuses_live_clis_and_scenarios(tmp_path: Path) -> None:
    """Only an offline CLI without identity; only offline scenarios."""
    cli = offline_cli()
    cli.identity = object()  # type: ignore[attr-defined]
    with pytest.raises(SafetyError):
        engine(cli)
    live = offline_cli()
    live.offline = False  # type: ignore[attr-defined]
    with pytest.raises(SafetyError):
        engine(live)
    scenario = write_scenario(tmp_path, "id: c\ntitle: c\nsteps: [{fragments: {}}]\n", tier_dir="cli")
    with pytest.raises(ValueError, match="use ScenarioEngine"):
        engine(offline_cli()).run(scenario)


def test_prepare_failure_is_reported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A missing template directory is a failure of the prepare phase."""

    def broken(template_src_dir: Path, org_dir: Path, ref: Any) -> None:
        """Vendoring fails."""
        raise FileNotFoundError(template_src_dir)

    monkeypatch.setattr(sut_template, "vendor_template", broken)
    outcome = engine(offline_cli()).run(write_scenario(tmp_path, "id: f\ntitle: f\nsteps: [{fragments: {}}]\n"))
    assert outcome.failures and outcome.failures[0].startswith("prepare: FileNotFoundError")


def test_offline_run_context_is_deterministic() -> None:
    """Both differential sides and every run render identical names."""
    assert offline_run_context() == offline_run_context()
    assert offline_run_context().prefix == f"e2e-{OFFLINE_RUN_ID}" and offline_module.OFFLINE_DEFAULT_PLAN == "free"


# --- differential runner ---------------------------------------------------------------------------------------------
class SideRenderer:
    """Renderer stand-in of one SUT side."""

    def __init__(self, role: str) -> None:
        """Remember the side."""
        self.role = role
        self.calls: list[tuple[ConfigFragments | None, str | None]] = []

    def render(
        self, fragments: ConfigFragments | None = None, *, include_baseline: bool = True, plan: str | None = None
    ) -> str:
        """Record and serialize."""
        self.calls.append((fragments, plan))
        return json.dumps({"role": self.role, "fragments": fragments.to_mapping() if fragments else None})


def side(role: str, org: str = OFFLINE_ORG, *, strict: bool = True) -> SutSide:
    """A SutSide over a FakeCli with a recorder (non-strict: default otterdog outputs)."""
    recorder = FakeRecorder()
    cli = offline_cli(org, recorder=recorder, strict=strict)
    return SutSide(role=role, installed=None, cli=cli, recorder=recorder, template=offline_template())  # type: ignore[arg-type]


def test_observe_offline_runs_base_then_head_with_their_own_templates(
    tmp_path: Path, _fakes: list[tuple[Path, Path]]
) -> None:
    """Each side vendors its own template sources and records the scenario (keep going, forced observation)."""
    base, head = side("base"), side("head")
    for current in (base, head):
        current.cli.queue("validate", canned("validate", validated(ok=current.role == "head")))
        current.cli.queue("show", canned("show"))
    runner = DifferentialRunner(
        base=base, head=head, renderer_factory=None, template_src_for=lambda s: Path(f"/src/{s.role}/examples/template")
    )
    text = "id: O-VAL-790\ntitle: v\nsteps: [{fragments: {}, validate: {}}]\n"
    runner.observe_offline(write_scenario(tmp_path, text))
    assert [src for src, _ in _fakes] == [Path("/src/base/examples/template"), Path("/src/head/examples/template")]
    for current in (base, head):
        assert [c.command for c in current.cli.calls] == ["validate", "show"]  # show ran despite the base failure
        assert current.recorder.scopes == [("O-VAL-790", "step-1")]
        assert [c.kwargs["observe"] for c in current.cli.calls] == ["validate", "show"]
    assert not runner.outcomes["O-VAL-790"]["base"].ok and runner.outcomes["O-VAL-790"]["head"].ok


def test_fixed_in_skips_older_suts_except_in_differential_runs(tmp_path: Path, _fakes: list[tuple[Path, Path]]) -> None:
    """The offline tier skips a scenario whose fixed_in the SUT predates; DifferentialRunner records both sides."""
    text = "id: O-FIX\ntitle: f\nfixed_in: 1.7.0.dev15\nsteps: [{fragments: {}, validate: {}}]\n"
    fixed = write_scenario(tmp_path, text)
    old = type("Installed", (), {"sut": type("Sut", (), {"version": "1.6.1"})()})()
    cli = offline_cli()
    cli.installed = old  # type: ignore[attr-defined]
    outcome = engine(cli).run(fixed)
    assert outcome.skipped == "SUT 1.6.1 predates otterdog 1.7.0.dev15, the first version O-FIX asserts"
    assert cli.calls == []
    base, head = side("base"), side("head")
    base.cli.installed = old  # type: ignore[attr-defined]
    for current in (base, head):
        current.cli.queue("validate", canned("validate", validated()))
        current.cli.queue("show", canned("show"))
    runner = DifferentialRunner(base=base, head=head, renderer_factory=None, template_src_for=lambda s: tmp_path)
    runner.observe_offline(fixed)
    assert runner.outcomes["O-FIX"]["base"].skipped is None and [c.command for c in base.cli.calls] == [
        "validate",
        "show",
    ]


LIVE = """
id: cli.repo.plan
title: plan only
steps:
  - name: create
    fragments: {repositories: ["orgs.newRepo('{{ p }}-a')"]}
  - name: update
    fragments: {repositories: ["orgs.newRepo('{{ p }}-a') { description: 'x' }"]}
    apply: {delete: true}
"""


def test_observe_live_validates_and_plans_both_sides_and_never_applies(tmp_path: Path) -> None:
    """Per step: write the rendered config on each side, validate + plan (base first); no apply, no cleanup."""
    base, head = side("base", "e2e-test-org", strict=False), side("head", "e2e-test-org", strict=False)
    renderers = {"base": SideRenderer("base"), "head": SideRenderer("head")}
    runner = DifferentialRunner(
        base=base, head=head, renderer_factory=lambda s: renderers[s.role], template_src_for=lambda s: Path("/x")
    )
    session = make_run_context()
    runner.variables = {**session.template_vars(), "org": "e2e-test-org", "plan": "free"}  # run_ctx stays offline
    runner.observe_live(write_scenario(tmp_path, LIVE, tier_dir="cli"))
    for current in (base, head):
        assert [c.command for c in current.cli.calls] == ["validate", "plan", "validate", "plan"]
        assert all(c.kwargs["repo_filter"] == f"{session.prefix}-*" for c in current.cli.calls[1::2])
        assert [c.kwargs["observe"] for c in current.cli.calls] == ["validate", "plan"] * 2
        assert current.recorder.scopes == [("cli.repo.plan", "create"), ("cli.repo.plan", "update")]
        assert len(current.cli.workspace.writes) == 2
        assert f"{session.prefix}-a" in current.cli.workspace.writes[0]
    assert len(renderers["base"].calls) == 2 and len(renderers["head"].calls) == 2


def test_observe_live_preconditions(tmp_path: Path) -> None:
    """observe_live needs a renderer factory and a live scenario."""
    runner = DifferentialRunner(base=side("base"), head=side("head"), renderer_factory=None, template_src_for=Path)
    with pytest.raises(ValueError, match="renderer_factory"):
        runner.observe_live(write_scenario(tmp_path, LIVE, tier_dir="cli"))
    runner.renderer_factory = lambda s: SideRenderer(s.role)  # type: ignore[assignment,return-value]
    with pytest.raises(ValueError, match="observe_offline"):
        runner.observe_live(write_scenario(tmp_path, "id: o\ntitle: o\nsteps: [{fragments: {}}]\n", name="o"))


# --- the real offline OtterdogCli (procs.run patched: no process) -----------------------------------------------------
REAL_OUTPUTS = {
    "validate": "Validating organization configurations:\n\nProject e2e-offline[github_id=e2e-offline] (1/1)\n"
    "  Validation succeeded\n",
    "local-plan": "Printing local diff:\n\nProject e2e-offline[github_id=e2e-offline] (1/1)\n\n"
    f'  + add repository[name="{RUN.prefix}-basic"] {{\n    + name = "{RUN.prefix}-basic"\n  + }}\n\n'
    "  Plan: 1 to add, 0 to change, 0 to delete.\n",
    "show": "Showing organization resources:\n",
}


def test_offline_engine_argv_with_the_real_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """validate/local-plan/show get ``-c <otterdog.json>``, ``--local`` and the org; the dummy token is the env."""
    from otterdog_e2e import procs
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import HarnessSettings
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.spec import ResolvedSut, SutSpec

    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        """Record otterdog argvs and answer with a realistic output (other commands, e.g. the unshare probe: ok)."""
        command = next((arg for arg in argv if arg in REAL_OUTPUTS), None)
        if command is None:
            return procs.CompletedProcess(argv, 0, "", "")
        calls.append((list(argv), dict(kwargs.get("extra_env") or {})))
        return procs.CompletedProcess(argv, 0, REAL_OUTPUTS[command], "")

    monkeypatch.setattr(procs, "run", run)
    monkeypatch.delenv("CI", raising=False)
    binary = tmp_path / "bin" / "otterdog"
    sut = ResolvedSut(SutSpec("release:latest", "release", "latest"), "v1.6.1", "b" * 40, "1.6.1", "1.6.1",
                      tmp_path / "src", "https://github.com/eclipse-csi/otterdog", True)  # fmt: skip
    settings = HarnessSettings(
        tmp_path, tmp_path / "cache", tmp_path / "art", "eclipse-csi/otterdog", tmp_path, tmp_path
    )
    workspace = ConfigWorkspace(tmp_path / "ws", org=OFFLINE_ORG, template=offline_template(), config_repo=".otterdog")
    cli = OtterdogCli(
        InstalledCli(sut, "host", None, binary, None, ""),
        workspace,
        verified=None,
        identity=None,
        scratch=tmp_path / "scratch",
        artifacts_dir=tmp_path / "artifacts",
        settings=settings,
        offline=True,
    )
    scenario = write_scenario(
        tmp_path, LPLAN.replace("    commands: {show-default: {}, --version: {contains: [version]}}\n", "")
    )
    outcome = OfflineEngine(cli=cli, workspace=workspace, template_src=tmp_path, run_ctx=RUN).run(scenario)
    assert outcome.ok, outcome.failures
    config = str(workspace.config_file.resolve())
    tails = [argv[argv.index(str(binary)) + 1 :] for argv, _ in calls]
    assert tails == [
        ["validate", "-c", config, "--local", OFFLINE_ORG],
        ["local-plan", "-c", config, "-s", "-BASE", "--local", OFFLINE_ORG],
        ["show", "-c", config, "--local", OFFLINE_ORG],
    ]
    assert all(env["E2E_OTTERDOG_API_TOKEN"] == "offline-dummy-token" for _, env in calls)
    assert workspace.config_file.is_file() and workspace.base_config_file.is_file()
    assert f"{RUN.prefix}-basic" in workspace.read_org_config()
