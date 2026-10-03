"""OtterdogCli diff options (plan_with / local_plan_with / apply_with, runner.DiffOptions) and the raw ``invoke`` API,
driving a fake otterdog script that records its argv, environment and cwd. Flags verified against otterdog/cli.py
@9bdeb75: plan, local-plan and apply share -r/--repo-filter, --update-webhooks, --update-secrets, --only-secrets and
--update-filter; local-plan has no -n."""

from __future__ import annotations

import json
import stat
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.otterdog.runner import CONFIG_ROOT_ENV, DiffOptions, OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace, WorkspaceLayout
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import HarnessSettings, Identity
from otterdog_e2e.sut.cli_install import InstalledCli
from otterdog_e2e.sut.spec import ResolvedSut, SutSpec
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli, make_verified_org

ORG = "e2e-test-org"
TOKEN = "ghp_" + "Kq7" * 12
FILTER = "e2e-t3c7z8a5-*"
WRAPPER = '#!/bin/sh\nexec "{python}" "{script}" "$@"\n'
FAKE_OTTERDOG = """
import json, os, sys
from pathlib import Path

here = Path(__file__).resolve().parent
keys = ("OTTERDOG_CONFIG_ROOT", "E2E_OTTERDOG_API_TOKEN", "E2E_OTTERDOG_E2E_OFFLINE_TOKEN", "E2E_STUB")
record = {"argv": sys.argv[1:], "cwd": os.getcwd(), "env": {k: os.environ[k] for k in keys if k in os.environ}}
with open(here / "calls.jsonl", "a") as handle:
    handle.write(json.dumps(record) + "\\n")
command = sys.argv[1].lstrip("-") if len(sys.argv) > 1 else ""
output = here / f"{command or 'none'}.txt"
sys.stdout.write(output.read_text() if output.exists() else "")
sys.exit(2 if command in ("", "bogus") else 0)
"""


class Env:
    """A fake installation and workspace under tmp_path."""

    def __init__(self, tmp_path: Path) -> None:
        """Write the fake otterdog and an otterdog.json."""
        self.bin_dir = tmp_path / "bin"
        self.bin_dir.mkdir()
        program = self.bin_dir / "fake_otterdog.py"
        program.write_text(FAKE_OTTERDOG)
        script = self.bin_dir / "otterdog"
        script.write_text(WRAPPER.format(python=sys.executable, script=program))
        script.chmod(0o755)
        sut = ResolvedSut(SutSpec("release:latest", "release", "latest"), "v1.6.1", "b" * 40, "1.6.1", "1.6.1",
                          tmp_path / "src", "https://github.com/eclipse-csi/otterdog", True)  # fmt: skip
        self.installed = InstalledCli(sut, "host", None, script, None, "otterdog.sh, version 1.6.1")
        self.settings = HarnessSettings(tmp_path, tmp_path / "cache", tmp_path / "art", "eclipse-csi/otterdog",
                                        tmp_path, tmp_path)  # fmt: skip
        self.scratch = tmp_path / "scratch"
        self.artifacts = tmp_path / "artifacts"
        self.workspace = ConfigWorkspace(tmp_path / "ws", org=ORG, template=offline_template(), config_repo=".otterdog")
        self.workspace.write_otterdog_json()

    def cli(self, *, offline: bool = False) -> OtterdogCli:
        """OtterdogCli over the fake installation (live by default)."""
        return OtterdogCli(
            self.installed,
            self.workspace,
            verified=None if offline else make_verified_org(ORG),
            identity=None if offline else Identity("admin", "e2e-admin-bot", TOKEN),
            scratch=self.scratch,
            artifacts_dir=self.artifacts,
            settings=self.settings,
            offline=offline,
        )

    def calls(self) -> list[dict[str, Any]]:
        """Recorded invocations."""
        path = self.bin_dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """The fake environment (no unshare: the offline sandbox is not under test here)."""
    from otterdog_e2e.otterdog import runner as runner_module

    monkeypatch.setattr(runner_module, "_unshare_available", lambda: False)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.setenv("OTTERDOG_CONFIG_ROOT", "/home/operator/real-otterdog-configs")
    return Env(tmp_path)


# --- DiffOptions -----------------------------------------------------------------------------------------------------
def test_diff_options_argv_order() -> None:
    """-r first, then --update-secrets, --update-webhooks, --only-secrets, --update-filter <p>, -v."""
    options = DiffOptions(FILTER, update_webhooks=True, update_secrets=True, only_secrets=True, update_filter="E2E_*")
    assert options.repo_args() == ["-r", FILTER]
    assert options.flag_args() == [
        "--update-secrets",
        "--update-webhooks",
        "--only-secrets",
        "--update-filter",
        "E2E_*",
    ]
    assert DiffOptions(verbose=True).args() == ["-v"] and DiffOptions().args() == []
    with pytest.raises(ValueError, match="non-empty pattern"):
        DiffOptions(repo_filter="")


def test_plan_local_plan_and_apply_with_options(env: Env) -> None:
    """The *_with methods put every flag in otterdog's syntax; plan/apply keep -n, local-plan has none."""
    cli = env.cli()
    options = DiffOptions(FILTER, update_secrets=True, update_filter="E2E_T3C7Z8A5_A*", verbose=True)
    cli.plan_with(options)
    cli.apply_with(DiffOptions(FILTER, only_secrets=True, update_webhooks=True), delete=True)
    cli.local_plan_with(DiffOptions("e2e-t3c7z8a5-a", update_webhooks=True), suffix="-OTHER", local=True)
    config = str(env.workspace.config_file.resolve())
    assert [call["argv"] for call in env.calls()] == [
        ["plan", "-c", config, "-n", "-r", FILTER, "--update-secrets", "--update-filter", "E2E_T3C7Z8A5_A*", "-v", ORG],
        ["apply", "-c", config, "-f", "-n", "-r", FILTER, "-d", "--update-webhooks", "--only-secrets", ORG],
        ["local-plan", "-c", config, "-s", "-OTHER", "-r", "e2e-t3c7z8a5-a", "--update-webhooks", "--local", ORG],
    ]


def test_the_pinned_methods_keep_their_argv(env: Env) -> None:
    """plan/apply/local_plan delegate to the *_with methods with the exact argv of before."""
    cli = env.cli()
    cli.plan(repo_filter=FILTER)
    cli.apply(repo_filter=FILTER, delete=True, update_secrets=True, update_webhooks=True)
    cli.local_plan()
    config = str(env.workspace.config_file.resolve())
    assert [call["argv"] for call in env.calls()] == [
        ["plan", "-c", config, "-n", "-r", FILTER, ORG],
        ["apply", "-c", config, "-f", "-n", "-r", FILTER, "-d", "--update-secrets", "--update-webhooks", ORG],
        ["local-plan", "-c", config, "-s", "-BASE", "--local", ORG],
    ]


def test_live_verbose_is_limited_to_one_v(env: Env) -> None:
    """DiffOptions(verbose=True) adds one -v; a second -v of a live invocation is refused before anything runs."""
    with pytest.raises(SafetyError, match="more than -v"):
        env.cli().invoke("plan", "-v", "-v")
    assert env.calls() == []
    env.cli(offline=True).invoke("validate", "-vv")
    assert env.calls()[0]["argv"] == ["validate", "-vv"]


# --- invoke ----------------------------------------------------------------------------------------------------------
def test_invoke_passes_the_arguments_exactly(env: Env) -> None:
    """No -c, --local nor organization; a fresh empty cwd; artifacts named after the first argument; the inherited
    OTTERDOG_CONFIG_ROOT never reaches otterdog."""
    (env.bin_dir / "help.txt").write_text("Usage: otterdog [OPTIONS] COMMAND [ARGS]...\n")
    cli = env.cli(offline=True)
    result = cli.invoke("--help")
    assert result.argv == ["otterdog", "--help"] and result.exit_code == 0 and "Usage:" in result.stdout
    bare = cli.invoke()
    assert bare.argv == ["otterdog"] and bare.exit_code == 2
    usage = cli.invoke("open-pr", "-b", "x", "-t", "y")
    first, second, third = env.calls()
    assert first["argv"] == ["--help"] and second["argv"] == [] and third["argv"] == ["open-pr", "-b", "x", "-t", "y"]
    assert all(CONFIG_ROOT_ENV not in call["env"] for call in env.calls())
    assert first["env"]["E2E_OTTERDOG_API_TOKEN"] == "offline-dummy-token"
    assert sorted(p.name for p in Path(first["cwd"]).iterdir()) == [".cache"]  # the HTTP cache link only
    assert (
        result.cwd.name.endswith("-help")
        and bare.cwd.name.endswith("-otterdog")
        and usage.cwd.name.endswith("-open-pr")
    )
    cmd = (env.artifacts / "cli" / result.cwd.name / "cmd.txt").read_text()
    assert cmd.splitlines()[0] == "otterdog --help"


def test_invoke_config_root_points_otterdog_at_the_workspace(env: Env) -> None:
    """config_root=True sets OTTERDOG_CONFIG_ROOT to the workspace root (noted in cmd.txt); the workspace layout
    decides which file otterdog finds there."""
    cli = env.cli(offline=True)
    env.workspace.use_layout(WorkspaceLayout(format="jsonnet"))
    result = cli.invoke("validate", "--local", config_root=True, observe=None)
    (call,) = env.calls()
    assert call["argv"] == ["validate", "--local"]
    assert call["env"][CONFIG_ROOT_ENV] == str(env.workspace.root.resolve())
    assert (env.workspace.root / "otterdog.jsonnet").is_file()
    assert (
        f"# env: {CONFIG_ROOT_ENV}={env.workspace.root.resolve()}"
        in (env.artifacts / "cli" / result.cwd.name / "cmd.txt").read_text()
    )


class ContainerRuntime:
    """DockerRuntime stand-in: runs the fake script, remembers the env-file content."""

    in_container = True
    label = "docker:v1.6.1"

    def __init__(self, script: Path) -> None:
        """Run ``script``."""
        self.script = script
        self.env_files: list[str] = []

    def command(self, args: Sequence[str], *, workdir: Path, env_file: Path | None) -> list[str]:
        """Record the 0600 env-file."""
        assert env_file is not None and stat.S_IMODE(env_file.stat().st_mode) == 0o600
        self.env_files.append(env_file.read_text())
        return [str(self.script), *args]

    def env(self, credentials: Mapping[str, str]) -> dict[str, str]:
        """Nothing travels in the process environment."""
        return {}


def test_invoke_config_root_in_a_container_uses_the_env_file(env: Env) -> None:
    """Containers get OTTERDOG_CONFIG_ROOT=/ws through the env-file, never the process environment."""
    cli = env.cli(offline=True)
    runtime = ContainerRuntime(env.installed.otterdog_bin)  # type: ignore[arg-type]
    cli.runtime = runtime  # type: ignore[assignment]
    cli.invoke("list-projects", config_root=True)
    assert f"{CONFIG_ROOT_ENV}=/ws" in runtime.env_files[0].splitlines()
    assert CONFIG_ROOT_ENV not in env.calls()[0]["env"]
    cli.invoke("--help")
    assert all(not line.startswith(CONFIG_ROOT_ENV) for line in runtime.env_files[1].splitlines())


def test_invoke_env_is_offline_only_and_reaches_the_process(env: Env) -> None:
    """env= adds variables (e.g. the dummy token of a custom credential variable) to offline commands only; names
    are checked; the values are noted in cmd.txt."""
    cli = env.cli(offline=True)
    result = cli.invoke("validate", "--local", env={"E2E_OTTERDOG_E2E_OFFLINE_TOKEN": "dummy-123", "E2E_STUB": "1"})
    (call,) = env.calls()
    assert call["env"]["E2E_OTTERDOG_E2E_OFFLINE_TOKEN"] == "dummy-123" and call["env"]["E2E_STUB"] == "1"
    assert "# env: E2E_STUB=1" in (env.artifacts / "cli" / result.cwd.name / "cmd.txt").read_text()
    with pytest.raises(ValueError, match="names must match"):
        cli.invoke("--help", env={"lower": "x"})
    with pytest.raises(SafetyError, match="offline only"):
        env.cli().invoke("--help", env={"E2E_STUB": "1"})
    assert len(env.calls()) == 1


def test_invoke_records_observations(env: Env) -> None:
    """``observe`` records the raw stdout like run()."""
    records: list[tuple[str, str, Any, Any]] = []

    class Recorder:
        """Collects record() calls."""

        def record(self, kind: str, key: str, content: Any, *, meta: Any = None) -> None:
            """Remember the observation."""
            records.append((kind, key, content, meta))

    (env.bin_dir / "help.txt").write_text("Usage: otterdog\n")
    cli = env.cli(offline=True)
    cli.recorder = Recorder()  # type: ignore[assignment]
    cli.invoke("--help", observe="help")
    assert records == [("cli", "help", "Usage: otterdog\n", {"exit_code": 0})]


# --- FakeCli ---------------------------------------------------------------------------------------------------------
def test_fake_cli_records_the_new_methods() -> None:
    """FakeCli: *_with calls are recorded under their command with the options and their fields; invoke under its
    first argument."""
    cli = FakeCli(strict=True)
    cli.queue("plan", stdout="planned")
    cli.queue("--help", stdout="usage")
    options = DiffOptions(FILTER, update_secrets=True)
    assert cli.plan_with(options).stdout == "planned"
    assert cli.invoke("--help", config_root=True).stdout == "usage"
    plan, help_call = cli.calls
    assert plan.command == "plan" and plan.kwargs["options"] is options and plan.kwargs["update_secrets"] is True
    assert plan.kwargs["repo_filter"] == FILTER and plan.kwargs["local"] is False
    assert help_call.command == "--help" and help_call.kwargs["invoke"] is True and help_call.kwargs["config_root"]
    lax = FakeCli()
    lax.apply_with(DiffOptions(only_secrets=True), delete=True)
    lax.local_plan_with(DiffOptions(), suffix="-X")
    lax.invoke()
    assert [call.command for call in lax.calls] == ["apply", "local-plan", ""]
    assert lax.calls[0].kwargs["delete"] is True and lax.calls[0].kwargs["only_secrets"] is True
    assert lax.calls[1].kwargs["suffix"] == "-X"
