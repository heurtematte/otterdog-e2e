"""Harness CLI with several targets: run/pr/janitor start one child process per target (batch.py), doctor checks
each target with its own environment copy, the other commands refuse lists; ``otterdog-e2e targets``; ``cache prune``
keeps the scratch of running sessions; RunRequest.harness_args round trip."""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import sys
import textwrap
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import filelock
import pytest
from click.testing import CliRunner

from otterdog_e2e import cli
from otterdog_e2e.redact import Redactor
from otterdog_e2e.settings import HarnessSettings
from otterdog_e2e.testing.fakes import fake_sha, make_settings

PROJECT = Path(__file__).resolve().parents[2]
TOKEN = "ghp_" + "c" * 36
PIN = fake_sha("pr-head")
RUN_ID_SHOWN_RE = re.compile(r"\brun [0-9a-z]{6}[0-9a-f]{2}\b")


@dataclass
class Batch:
    """A project (free and team profiles, suite dirs), a HOME with instance env files and the recorded children."""

    settings: HarnessSettings
    config: Path
    codes: dict[str, int] = field(default_factory=dict)
    children: list[dict[str, Any]] = field(default_factory=list)
    pytest_calls: list[list[str]] = field(default_factory=list)

    def instance(self, name: str, profile: str | None, org_id: int, **extra: str) -> None:
        """Write ~/.config/otterdog-e2e/<name>.env of an instance of the org ``<name>-e2e``."""
        values = {
            "E2E_ORG": f"{name}-e2e",
            "E2E_ORG_ID": str(org_id),
            "E2E_ADMIN_LOGIN": f"{name}-admin",
            "E2E_ADMIN_TOKEN": TOKEN,
            **({"E2E_PROFILE": profile} if profile else {}),
            **extra,
        }
        path = self.config / f"{name}.env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
        path.chmod(0o600)

    def runner(
        self, argv: Sequence[str], *, env: dict[str, str], on_line: Callable[[str], None], log_path: Path | None = None
    ) -> int:
        """procs.run_harness stand-in: records the child (its -v flags apart), writes its run.json (run commands) and
        answers its code."""
        args = list(argv[4:])
        verbose = 0
        while args and args[0] == "-v":
            args.pop(0)
            verbose += 1
        values = dict(arg.removeprefix("--").split("=", 1) for arg in args if arg.startswith("--") and "=" in arg)
        child = {"argv": list(argv), "args": args, "env": env, "values": values, "log": log_path, "verbose": verbose}
        self.children.append(child)
        if "run-id" in values:
            run_dir = (Path(values["artifacts"]) if "artifacts" in values else self.settings.artifacts_root) / values[
                "run-id"
            ]
            run_dir.mkdir(parents=True, exist_ok=True)
            run = {"run_id": values["run-id"], "command": f"otterdog-e2e {args[0]} --target {values['target']}"}
            (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
        on_line(f"child of {values.get('target')}")
        return self.codes.get(values.get("target", ""), 0)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Batch:
    """Instances acme (free, org 11), beta (team, org 22) and free (the profile, org 33); children and pytest faked."""
    root = tmp_path / "project"
    (root / "targets").mkdir(parents=True)
    for profile in ("free", "team"):
        shutil.copy(PROJECT / "targets" / f"{profile}.yaml", root / "targets" / f"{profile}.yaml")
    for suite in cli.SUITES:
        (root / "tests" / suite).mkdir(parents=True)
    home = tmp_path / "home"
    config = home / ".config" / "otterdog-e2e"
    config.mkdir(parents=True)
    state = Batch(make_settings(root), config)
    for key in [key for key in os.environ if key.startswith("E2E_")]:
        monkeypatch.delenv(key)
    for key in ("PYTEST_ADDOPTS", "GITHUB_STEP_SUMMARY", "CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: state.settings)
    fresh = Redactor()
    for module in ("otterdog_e2e.settings", "otterdog_e2e.batch", "otterdog_e2e.cli", "otterdog_e2e.procs"):
        monkeypatch.setattr(f"{module}.REDACTOR", fresh)
    monkeypatch.setattr("otterdog_e2e.procs.run_harness", state.runner)

    def run_pytest(args: list[str], *, command: str | None = None) -> int:
        """In-process pytest of a single target: recorded."""
        state.pytest_calls.append(list(args))
        return 0

    monkeypatch.setattr(cli, "run_pytest", run_pytest)
    state.instance("acme", "free", 11)
    state.instance("beta", "team", 22)
    state.instance("free", None, 33)
    return state


def invoke(*args: str) -> Any:
    """Run the CLI (stderr kept apart)."""
    return CliRunner().invoke(cli.main, list(args))


# --- run -----------------------------------------------------------------------------------------------------------------
def test_run_starts_one_child_per_target(world: Batch) -> None:
    """run --target acme,beta: python -m otterdog_e2e run per target with its own run id and the shared artifacts
    root; the parent's environment (never an env-file value); prefixed output; the most severe exit code; the batch
    summary below the artifacts root."""
    world.codes = {"beta": 1}
    before = dict(os.environ)
    result = invoke("run", "--target", "acme,beta", "--suite", "cli", "--sut", "branch:main", "-k", "not slow", "-x")
    assert result.exit_code == 1, result.output
    assert dict(os.environ) == before
    acme, beta = world.children
    root = world.settings.artifacts_root
    assert acme["argv"][:4] == [sys.executable, "-P", "-m", "otterdog_e2e"] and acme["verbose"] == 0
    assert acme["args"] == [
        "run",
        "--suite=cli",
        "--target=acme",
        "--sut=branch:main",
        f"--run-id={acme['values']['run-id']}",
        f"--artifacts={root}",
        "-knot slow",
        "--",
        "-x",
    ]
    assert acme["values"]["run-id"] != beta["values"]["run-id"]
    for child in (acme, beta):
        assert "E2E_ORG" not in child["env"] and "E2E_ADMIN_TOKEN" not in child["env"]
        assert "E2E_PROFILE" not in child["env"] and child["env"]["HOME"] == os.environ["HOME"]
        assert child["log"].parent == root
    assert "[acme] child of acme" in result.stdout and "[beta] child of beta" in result.stdout
    assert "profile free, org acme-e2e (id 11)" in result.stderr and "2 targets, sequential" in result.stderr
    summaries = sorted(root.glob("batch-*.md"))
    assert len(summaries) == 1 and summaries[0].with_suffix(".json").is_file()
    document = json.loads(summaries[0].with_suffix(".json").read_text(encoding="utf-8"))
    assert [(row["instance"], row["profile"], row["exit_code"]) for row in document["targets"]] == [
        ("acme", "free", 0),
        ("beta", "team", 1),
    ]
    assert document["targets"][0]["command"] == "otterdog-e2e run --target acme"
    assert f"batch summary: {summaries[0]}" in result.stderr and world.pytest_calls == []


def test_a_single_target_stays_in_process(world: Batch) -> None:
    """--target acme (or a list expanding to one target) keeps today's in-process pytest run."""
    result = invoke("run", "--target", "acme", "--suite", "cli")
    assert result.exit_code == 0, result.output
    assert world.children == [] and "--e2e-target=acme" in world.pytest_calls[0]
    (world.config / "lists").mkdir()
    (world.config / "lists" / "solo").write_text("beta\n", encoding="utf-8")
    assert invoke("run", "--target", "@solo", "--suite", "cli").exit_code == 0
    assert world.children == [] and "--e2e-target=beta" in world.pytest_calls[1]


def test_run_expands_all_and_lists(world: Batch) -> None:
    """@all is every instance env file; @<list> a list file; repeated --target values add up."""
    assert invoke("run", "--target", "@all", "--suite", "cli").exit_code == 0
    assert [child["values"]["target"] for child in world.children] == ["acme", "beta", "free"]
    world.children.clear()
    (world.config / "lists").mkdir()
    (world.config / "lists" / "nightly").write_text("# orgs\nbeta\n", encoding="utf-8")
    assert invoke("run", "--target", "@nightly", "--target", "acme", "--suite", "cli").exit_code == 0
    assert [child["values"]["target"] for child in world.children] == ["beta", "acme"]
    result = invoke("run", "--target", "@missing", "--suite", "cli")
    assert result.exit_code == 2 and "no list file" in result.output


def test_run_refuses_a_run_id_with_several_targets(world: Batch) -> None:
    """--run-id names one run."""
    result = invoke("run", "--target", "acme,beta", "--run-id", "t3c7z8a5")
    assert result.exit_code == 2 and "cannot be used with several targets" in result.output
    assert world.children == []


def test_run_refuses_broken_targets_before_starting_anything(world: Batch) -> None:
    """A target that cannot be loaded is a usage error naming it; nothing runs."""
    world.instance("gamma", None, 44)
    result = invoke("run", "--target", "acme,gamma", "--suite", "cli")
    assert result.exit_code == 2 and "gamma: target 'gamma' not found" in result.output
    assert world.children == []


def test_parallel_runs_need_distinct_orgs_and_get_ports(world: Batch) -> None:
    """--parallel: one org per target (usage error otherwise); each relay child gets its own E2E_WEBAPP_PORT."""
    world.instance("acme2", "team", 11)
    result = invoke("run", "--target", "acme,acme2", "--parallel", "2", "--suite", "cli")
    assert result.exit_code == 2 and "test the same organization" in result.output and world.children == []
    result = invoke("run", "--target", "acme,beta,free", "--parallel", "3", "--suite", "cli")
    assert result.exit_code == 0, result.output
    ports = {child["values"]["target"]: child["env"]["E2E_WEBAPP_PORT"] for child in world.children}
    assert len(set(ports.values())) == 3 and "parallel 3" in result.stderr
    assert all(f"webapp port {port}" in result.stderr for port in ports.values())


def test_fail_fast_stops_the_batch(world: Batch) -> None:
    """--fail-fast: no target starts after a failure; the exit code is the failure's."""
    world.codes = {"acme": 5}
    result = invoke("run", "--target", "acme,beta", "--fail-fast", "--suite", "cli")
    assert result.exit_code == 5 and len(world.children) == 1
    assert "[beta] not started (--fail-fast: an earlier target failed)" in result.stdout
    assert "sequential, fail-fast" in result.stderr


def test_harness_args_round_trip(world: Batch, tmp_path: Path) -> None:
    """The child arguments of a request parse back into the very same pytest arguments (every option, flag and
    pass-through argument survives, values never read as options)."""
    request = cli.RunRequest(
        suites=("cli", "webapp"),
        target="acme",
        sut="branch:main",
        base_sut="tag:v1.6.0",
        reset_sut="tag:v1.6.1",
        tags="smoke,repo",
        scenario="cli.repo.*",
        keyword="-weird and not slow",
        run_id="t3c7z8a5",
        change="check-merge",
        webapp_image="otterdog-e2e/otterdog:x",
        artifacts=str(tmp_path / "art"),
        keep=True,
        no_reset=True,
        strict_diff=True,
        extra=("-x", "--maxfail=2", "--", "tests/cli/test_x.py"),
        allow_web_ui=True,
    )
    args = request.harness_args()
    assert args[0] == "run" and args[args.index("--") + 1 :] == list(request.extra)
    result = invoke(*args)
    assert result.exit_code == 0, result.output
    assert world.pytest_calls == [request.pytest_args(world.settings.project_root)]


# --- pr ------------------------------------------------------------------------------------------------------------------
def test_pr_starts_one_child_per_target(world: Batch) -> None:
    """pr N --sha S --target acme,beta: one child pr per target with its own run id; the batch summary."""
    world.codes = {"acme": 2}
    result = invoke("pr", "790", "--sha", PIN, "--target", "acme,beta", "--strict-diff")
    assert result.exit_code == 2, result.output
    first = world.children[0]
    assert first["args"] == [
        "pr",
        "790",
        f"--sha={PIN}",
        "--target=acme",
        "--suite=auto",
        f"--run-id={first['values']['run-id']}",
        "--strict-diff",
    ]
    assert f"PR #790 @ {PIN[:12]} on 2 targets: acme, beta" in result.stderr
    assert len(list(world.settings.artifacts_root.glob("batch-*.json"))) == 1


def test_pr_children_get_an_explicit_change() -> None:
    """A --change other than the PR itself reaches the child pr commands and the reproduce command; the PR's own
    number is implied (never repeated)."""
    entry = SimpleNamespace(target="acme", run_id="t3c7z8a5")
    args = cli.pr_child_args(
        790, PIN, entry=entry, suites="auto", strict_diff=False, allow_web_ui=False, change="check-merge"
    )  # type: ignore[arg-type]
    assert args[-1] == "--change=check-merge"
    assert "--change" not in " ".join(
        cli.pr_child_args(790, PIN, entry=entry, suites="auto", strict_diff=False, allow_web_ui=False)  # type: ignore[arg-type]
    )
    command = cli.pr_command(790, PIN, target=None, suites="auto", strict_diff=False, allow_web_ui=False, change="792")
    assert command[-2:] == ["--change", "792"]


def test_pr_run_id(world: Batch, monkeypatch: pytest.MonkeyPatch) -> None:
    """pr --run-id: one target only, validated, passed to plan_pr (the child of a batch gets its own)."""
    planned: list[Any] = []

    def plan_pr(number: int, sha: str, **kwargs: Any) -> cli.RunRequest:
        """Record the plan request."""
        planned.append(kwargs)
        return cli.RunRequest(suites=("offline",), sut=f"pr:{number}@{sha}", run_id=kwargs["run_id"])

    monkeypatch.setattr(cli, "plan_pr", plan_pr)
    assert invoke("pr", "790", "--sha", PIN, "--target", "acme", "--run-id", "t3c7z8a5").exit_code == 0
    assert planned[0]["run_id"] == "t3c7z8a5" and "--e2e-run-id=t3c7z8a5" in world.pytest_calls[0]
    result = invoke("pr", "790", "--sha", PIN, "--target", "acme,beta", "--run-id", "t3c7z8a5")
    assert result.exit_code == 2 and "several targets" in result.output
    assert invoke("pr", "790", "--sha", PIN, "--run-id", "../x").exit_code == 2
    assert world.children == []


# --- janitor -------------------------------------------------------------------------------------------------------------
def test_janitor_sweeps_several_targets_in_turn(world: Batch) -> None:
    """One child janitor per target (no batch summary); --run-id and --force-takeover name one run of one target."""
    result = invoke("janitor", "--target", "acme,beta", "--older-than", "2h", "--apply")
    assert result.exit_code == 0, result.output
    assert [child["args"] for child in world.children] == [
        ["janitor", "--target=acme", "--older-than=2h", "--apply"],
        ["janitor", "--target=beta", "--older-than=2h", "--apply"],
    ]
    assert all(child["log"] is None for child in world.children)
    assert not list(world.settings.artifacts_root.glob("batch-*"))
    # the children get no --run-id (each sweeps under a run id of its own): no planned run id is ever printed
    assert not RUN_ID_SHOWN_RE.search(result.output), result.output
    assert "[acme] profile free, org acme-e2e (id 11)\n" in result.stderr
    for extra in (["--run-id", "t3c7z8a5"], ["--run-id", "t3c7z8a5", "--force-takeover"]):
        result = invoke("janitor", "--target", "acme,beta", *extra)
        assert result.exit_code == 2 and "give one target" in result.output
    assert invoke("janitor", "--target", "acme,beta", "--force-takeover").exit_code == 2
    assert len(world.children) == 2


def test_children_get_the_verbosity_of_the_batch(world: Batch) -> None:
    """-v / -vv of the batch command reach every child, before its subcommand (the group option of main)."""
    result = invoke("-vv", "janitor", "--target", "acme,beta")
    assert result.exit_code == 0, result.output
    assert [child["verbose"] for child in world.children] == [2, 2]
    assert world.children[0]["argv"][4:7] == ["-v", "-v", "janitor"]
    world.children.clear()
    assert invoke("-v", "run", "--target", "acme,beta", "--suite", "cli").exit_code == 0
    assert [child["verbose"] for child in world.children] == [1, 1] and world.children[0]["args"][0] == "run"


# --- signals -------------------------------------------------------------------------------------------------------------
SLOW_COMMAND = """
    import os, time
    from otterdog_e2e import cli

    @cli.main.command("e2e-test-slow")
    def slow() -> None:
        try:
            print("ready", os.getpid(), flush=True)
            time.sleep(30)
        finally:
            print("cleanup started", flush=True)
            time.sleep(1)
            print("cleanup done", flush=True)

    cli.main(["e2e-test-slow"], prog_name="otterdog-e2e")
"""


def test_sigterm_lets_every_command_clean_up() -> None:
    """A SIGTERM (a batch forwards it to its janitor children) raises KeyboardInterrupt in the command, so its cleanup
    runs (E2EContext.close: lease release) instead of the process dying; a second SIGTERM during the cleanup is
    ignored."""
    lines: list[str] = []

    def on_line(line: str) -> None:
        """SIGTERM the child once ready, and again while it cleans up."""
        lines.append(line)
        if line.startswith("ready "):
            lines.append(f"pid {line.split()[1]}")
            os.kill(int(line.split()[1]), signal.SIGTERM)
        elif line == "cleanup started":
            os.kill(int(lines[1].split()[1]), signal.SIGTERM)

    from otterdog_e2e import procs

    code = procs.run_harness(
        [sys.executable, "-P", "-c", textwrap.dedent(SLOW_COMMAND)], env=dict(os.environ), on_line=on_line
    )
    assert "cleanup started" in lines and "cleanup done" in lines, lines
    assert code == 1  # click's Abort after the KeyboardInterrupt, not -15


def test_the_termination_guard_is_installed_for_the_command_and_restored(
    world: Batch, monkeypatch: pytest.MonkeyPatch
) -> None:
    """While a command runs, SIGTERM is the guard's (main thread); afterwards the previous handlers are back."""
    before = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    seen: list[Any] = []

    def list_instances(settings: Any, environ: Any) -> list[Any]:
        """Record the handler in place during the command."""
        seen.append(signal.getsignal(signal.SIGTERM))
        return []

    monkeypatch.setattr("otterdog_e2e.batch.list_instances", list_instances)
    assert invoke("targets").exit_code == 0
    assert getattr(seen[0], "__self__", None).__class__ is cli.TerminationGuard
    assert {sig: signal.getsignal(sig) for sig in before} == before


def test_the_guard_ignores_a_sigterm_after_a_first_interruption(monkeypatch: pytest.MonkeyPatch) -> None:
    """The first SIGTERM raises KeyboardInterrupt, later ones are ignored; a SIGINT keeps raising and counts as the
    first interruption; an interrupted in-process pytest session (exit code 2) counts too."""
    import click

    guard = cli.TerminationGuard()
    with pytest.raises(KeyboardInterrupt):
        guard.on_sigterm(signal.SIGTERM, None)
    guard.on_sigterm(signal.SIGTERM, None)  # ignored: the cleanup is running
    other = cli.TerminationGuard()
    assert other.install()
    try:
        with pytest.raises(KeyboardInterrupt):
            other.on_sigint(signal.SIGINT, None)
        other.on_sigterm(signal.SIGTERM, None)
    finally:
        other.uninstall()
    third = cli.TerminationGuard()
    monkeypatch.setattr("pytest.main", lambda args: 2)
    with click.Context(cli.main) as context:
        context.meta[cli._GUARD_KEY] = third
        assert cli.run_pytest(["tests/unit"]) == 2
    assert third.interrupted


# --- doctor --------------------------------------------------------------------------------------------------------------
def test_doctor_checks_every_target_with_its_own_environment(world: Batch, monkeypatch: pytest.MonkeyPatch) -> None:
    """One report per target: each context loads its own env files into a copy of the environment (the org of one
    target never leaks into another), --json is a list, exit 1 when one target fails."""
    before = dict(os.environ)
    seen: dict[str, str | None] = {}

    def run(self: cli.Doctor) -> list[cli.CheckRow]:
        """Load the target and report its org (beta FAILs)."""
        seen[f"before:{self.ctx.options.target}"] = self.ctx.environ.get("E2E_ORG")
        target = self.ctx.load_target()
        seen[str(target.name)] = self.ctx.environ.get("E2E_ORG")
        self.add("target", cli.FAIL if target.name == "beta" else cli.OK, f"{target.name} {target.org}")
        return self.rows

    monkeypatch.setattr(cli.Doctor, "run", run)
    result = invoke("doctor", "--target", "acme,beta", "--json")
    assert result.exit_code == 1, result.output
    reports = json.loads(result.stdout)
    assert [(report["target"], report["ok"]) for report in reports] == [("acme", True), ("beta", False)]
    assert reports[1]["checks"][0]["detail"] == "beta beta-e2e"
    assert seen == {"before:acme": None, "acme": "acme-e2e", "before:beta": None, "beta": "beta-e2e"}
    assert dict(os.environ) == before
    result = invoke("doctor", "--target", "acme", "--target", "free")
    assert result.exit_code == 0, result.output
    assert "=== target acme ===" in result.stdout and "=== target free ===" in result.stdout
    assert "doctor: 2 targets, 0 with failures" in result.stdout
    single = json.loads(invoke("doctor", "--target", "acme", "--json").stdout)
    assert single["target"] == "acme" and single["ok"] is True  # one target: today's document


@pytest.mark.parametrize("command", [["doctor"], ["janitor"]])
def test_doctor_and_janitor_need_a_target(world: Batch, command: list[str]) -> None:
    """An empty --target (or a list of blanks) is a usage error, not a crash."""
    for value in ("", " , "):
        result = invoke(*command, "--target", value)
        assert result.exit_code == 2 and "no target given" in result.output


# --- commands of one target ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "args",
    [
        ["bootstrap", "--target", "acme,beta"],
        ["bootstrap", "--target", "@all", "--apply"],
        ["relay", "--target", "acme,beta", "--forward-to", "http://127.0.0.1:5000/x"],
        ["app-manifest", "--target", "@nightly", "--webhook-url", "https://sink.example/x"],
        ["inject", "--target", "acme,beta", "--overlay", str(PROJECT / "pyproject.toml")],
    ],
)
def test_single_target_commands_refuse_lists(world: Batch, args: list[str]) -> None:
    """bootstrap, relay, app-manifest and inject act on one org: a list is a usage error naming the commands that take
    one (inject: before its ad-hoc scenario is written into a run scratch)."""
    result = invoke(*args)
    assert result.exit_code == 2, result.output
    assert "only accepted by run, pr, doctor, janitor" in result.output
    assert not (world.settings.cache_dir / "run").exists() and world.pytest_calls == []


# --- targets -------------------------------------------------------------------------------------------------------------
def test_targets_lists_instances_and_profiles(world: Batch) -> None:
    """Instance, profile, org and env file of every instance env file and profile; problems below; --json."""
    result = invoke("targets")
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["INSTANCE", "PROFILE", "ORG", "ENV", "FILE"]
    assert lines[1].split() == ["acme", "free", "acme-e2e", str(world.config / "acme.env")]
    assert lines[3].split() == ["free", "free", "free-e2e", str(world.config / "free.env")]
    assert lines[4].split() == ["team", "team", "-", "-"] and lines[5].startswith("  problem: ")
    data = json.loads(invoke("targets", "--json").stdout)
    assert [entry["name"] for entry in data] == ["acme", "beta", "free", "team"]
    assert data[1] == {
        "name": "beta",
        "profile": "team",
        "org": "beta-e2e",
        "env_file": str(world.config / "beta.env"),
        "problem": None,
    }
    assert TOKEN not in result.output


def test_targets_without_anything(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No env file and no profile: one explaining line."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path / "p"))
    result = invoke("targets")
    assert result.exit_code == 0 and "no target instance" in result.output


# --- cache prune ---------------------------------------------------------------------------------------------------------
def test_cache_prune_keeps_the_scratch_of_running_sessions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run scratch whose lock (run/<id>.lock) a session holds is never pruned, however old; free ones go with
    their lock file."""
    cache = tmp_path / "cache"
    for age, name in enumerate(["r3", "r2", "r1"]):
        (cache / "run" / name).mkdir(parents=True)
        (cache / "run" / f"{name}.lock").touch()
        os.utime(cache / "run" / name, (1_700_000_000 - age * 100, 1_700_000_000 - age * 100))
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path))
    monkeypatch.setattr("otterdog_e2e.sut.image.docker_available", lambda: False)
    with filelock.FileLock(str(cache / "run" / "r1.lock"), timeout=0):
        result = invoke("cache", "prune", "--keep", "1")
    assert result.exit_code == 0, result.output
    assert sorted(path.name for path in (cache / "run").iterdir()) == ["r1", "r1.lock", "r3", "r3.lock"]
    assert "pruned 1 cache entry" in result.output
    assert sorted(path.name for path in cli.prune_cache_dirs(cache, keep=1)) == ["r1"]  # released: pruned now


def test_cache_prune_removes_exact_sidecars_and_keeps_held_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pruning src/v1.2 removes v1.2.lock, v1.2.image.lock and v1.2.e2e-export.json only (never the sidecars of the
    kept v1.2.1); an entry whose export lock or image build lock is held is kept; the unheld image locks of untrusted
    SUTs (untrusted/<label>.image.lock) are removed, a held one stays."""
    cache = tmp_path / "cache"
    src = cache / "src"
    sidecars = (".lock", ".image.lock", ".e2e-export.json")
    for age, name in enumerate(["v1.2.1", "v1.2", "v1.1", "v1.0"]):
        (src / name).mkdir(parents=True)
        for suffix in sidecars:
            (src / f"{name}{suffix}").touch()
        os.utime(src / name, (1_700_000_000 - age * 100, 1_700_000_000 - age * 100))
    untrusted = cache / "untrusted"
    untrusted.mkdir()
    for name in ("pr-1-abc.image.lock", "pr-2-def.image.lock", "pr-3-ghi"):
        (untrusted / name).touch()
    with (
        filelock.FileLock(str(src / "v1.1.image.lock"), timeout=0),
        filelock.FileLock(str(untrusted / "pr-2-def.image.lock"), timeout=0),
    ):
        removed = cli.prune_cache_dirs(cache, keep=1)
    assert sorted(path.name for path in removed) == ["pr-1-abc.image.lock", "v1.0", "v1.2"]
    kept = sorted(path.name for path in src.iterdir())
    assert kept == sorted(f"{name}{suffix}" for name in ("v1.2.1", "v1.1") for suffix in ("", *sidecars))
    assert sorted(path.name for path in untrusted.iterdir()) == ["pr-2-def.image.lock", "pr-3-ghi"]


def test_lock_held(tmp_path: Path) -> None:
    """context.lock_held: a missing lock file is free, a held one (another holder, even of this process) is held, a
    released one is free again; never waits."""
    from otterdog_e2e.context import lock_held

    path = tmp_path / "x.lock"
    assert not lock_held(path) and not path.exists()
    with filelock.FileLock(str(path), timeout=0):
        assert lock_held(path)
    assert not lock_held(path)
