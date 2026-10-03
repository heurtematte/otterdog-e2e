"""OtterdogCli (SPEC 11.2) driving a fake otterdog: a tiny python script printing canned output and recording its
argv, cwd, environment and stdin."""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.otterdog import runner as runner_module
from otterdog_e2e.otterdog.runner import OtterdogCli, infra_error_line
from otterdog_e2e.otterdog.runtime import DockerRuntime, set_container_scope
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import HarnessSettings, Identity
from otterdog_e2e.sut.cli_install import IMAGE_OTTERDOG_BIN, InstalledCli
from otterdog_e2e.sut.spec import ResolvedSut, SutSpec
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import make_verified_org

DATA = Path(__file__).parent / "data"
ORG = "e2e-test-org"
TOKEN = "ghp_" + "Rz8" * 12  # token-shaped: redacted by pattern and registered literally
WRAPPER = '#!/bin/sh\nexec "{python}" "{script}" "$@"\n'  # short shebang: long interpreter paths break it
FAKE_OTTERDOG = """
import json, os, sys, time
from pathlib import Path

here = Path(__file__).resolve().parent
args = sys.argv[1:]
command = args[0].lstrip("-") if args else ""
link = Path(".cache/async_http")
keys = ("HOME", "COLUMNS", "NO_COLOR", "TERM", "PYTHON_DOTENV_DISABLED", "E2E_CACHE_DIR", "E2E_LEAK")
record = {{
    "argv": sys.argv,
    "cwd": os.getcwd(),
    "env": {{k: v for k, v in os.environ.items() if k.startswith("E2E_OTTERDOG") or k in keys}},
    "stdin": sys.stdin.read(),
    "cache_link": os.readlink(link) if link.is_symlink() else None,
    "cache_target": str(link.resolve()) if link.is_symlink() else None,
}}
with open(here / "calls.jsonl", "a") as handle:
    handle.write(json.dumps(record) + "\\n")
outputs = here / "outputs"
if (outputs / f"{{command}}.sleep").exists():
    time.sleep(float((outputs / f"{{command}}.sleep").read_text()))
if (outputs / f"{{command}}.txt").exists():
    sys.stdout.write((outputs / f"{{command}}.txt").read_text())
if (outputs / f"{{command}}.err").exists():
    sys.stderr.write((outputs / f"{{command}}.err").read_text())
if command == "check-status" and (outputs / "check-status.json").exists():
    Path(args[args.index("-j") + 1]).write_text((outputs / "check-status.json").read_text())
if (outputs / "plant.json").exists():  # what a malicious SUT leaves in its (mounted) cwd: links and FIFOs
    for item in json.loads((outputs / "plant.json").read_text()):
        planted = Path(item["path"])
        planted.parent.mkdir(parents=True, exist_ok=True)
        if planted.is_symlink() or planted.is_file():
            planted.unlink()
        if "link" in item:
            planted.symlink_to(item["link"])
        else:
            os.mkfifo(planted)
sys.exit(int((outputs / f"{{command}}.exit").read_text()) if (outputs / f"{{command}}.exit").exists() else 0)
"""


class Env:
    """A fake installation, workspace and settings under tmp_path."""

    def __init__(self, tmp_path: Path, *, trusted: bool = True) -> None:
        """Write the fake otterdog script and the workspace."""
        self.root = tmp_path
        self.bin_dir = tmp_path / "fake-otterdog"
        self.outputs = self.bin_dir / "outputs"
        self.outputs.mkdir(parents=True)
        program = self.bin_dir / "fake_otterdog.py"
        program.write_text(FAKE_OTTERDOG.format())
        self.script = self.bin_dir / "otterdog"
        self.script.write_text(WRAPPER.format(python=sys.executable, script=program))
        self.script.chmod(0o755)
        sut = ResolvedSut(
            spec=SutSpec("release:latest", "release", "latest"),
            label="v1.6.1",
            sha="b" * 40,
            version="1.6.1",
            image_version="1.6.1",
            source_dir=tmp_path / "src",
            repo_url="https://github.com/eclipse-csi/otterdog",
            trusted=trusted,
        )
        self.installed = InstalledCli(sut, "host", None, self.script, None, "otterdog.sh, version 1.6.1")
        self.settings = HarnessSettings(
            project_root=tmp_path,
            cache_dir=tmp_path / "cache",
            artifacts_root=tmp_path / "artifacts",
            upstream_repo="eclipse-csi/otterdog",
            targets_dir=tmp_path / "targets",
            scenarios_dir=tmp_path / "scenarios",
        )
        self.scratch = tmp_path / "scratch"
        self.artifacts = tmp_path / "artifacts" / "run"
        self.workspace = ConfigWorkspace(
            self.scratch / "workspace", org=ORG, template=offline_template(), config_repo=".otterdog"
        )
        self.workspace.write_otterdog_json()

    def output(self, command: str, text: str, *, exit_code: int | None = None, sleep: float | None = None) -> None:
        """Canned stdout (and exit code / delay) of a command."""
        (self.outputs / f"{command}.txt").write_text(text)
        if exit_code is not None:
            (self.outputs / f"{command}.exit").write_text(str(exit_code))
        if sleep is not None:
            (self.outputs / f"{command}.sleep").write_text(str(sleep))

    def calls(self) -> list[dict[str, Any]]:
        """Recorded invocations of the fake otterdog."""
        path = self.bin_dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def cli(self, *, offline: bool = False, identity: Identity | None = None, **kwargs: Any) -> OtterdogCli:
        """OtterdogCli over the fake installation (live by default, with the admin identity)."""
        if identity is None and not offline:
            identity = Identity("admin", "e2e-admin-bot", TOKEN)
        verified = None if offline else make_verified_org(ORG)
        return OtterdogCli(
            self.installed,
            self.workspace,
            verified=verified,
            identity=identity,
            scratch=self.scratch,
            artifacts_dir=self.artifacts,
            settings=self.settings,
            offline=offline,
            **kwargs,
        )


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """Fake environment; the caller's E2E_* variables must never reach otterdog."""
    monkeypatch.setenv("E2E_LEAK", "leaked-value-123456")
    monkeypatch.setenv("E2E_CACHE_DIR", str(tmp_path / "cache"))
    return Env(tmp_path)


def test_run_layout_env_and_artifacts(env: Env) -> None:
    """Fresh cwd under scratch/cli, HTTP cache link, credentials via env only, redacted artifacts."""
    env.output("validate", f"Validating organization configurations:\n  token {TOKEN}\n  Validation succeeded\n")
    cli = env.cli()
    result = cli.validate(local=True)
    config = str(env.workspace.config_file.resolve())
    assert result.argv == ["otterdog", "validate", "-c", config, "--local", ORG]
    assert result.exit_code == 0 and not result.timed_out and result.infra_error is None
    assert result.validation().ok and TOKEN in result.stdout
    (call,) = env.calls()
    assert call["argv"][1:] == result.argv[1:]
    assert Path(call["cwd"]) == result.cwd and result.cwd.parent == env.scratch / "cli"
    assert result.cwd.name.endswith("-validate") and result.cwd.name[:4].isdigit()
    # live caches hold the token (pickled Authorization header): they stay in the run's scratch (ISO-04)
    assert call["cache_target"] == str(env.scratch / "http-cache" / "v1.6.1-admin")
    assert stat.S_IMODE((env.scratch / "http-cache" / "v1.6.1-admin").stat().st_mode) == 0o700
    assert not (env.settings.cache_dir / "http-cache" / "v1.6.1-admin").exists()
    assert call["env"]["E2E_OTTERDOG_API_TOKEN"] == TOKEN
    assert call["env"]["E2E_OTTERDOG_USERNAME"] == "unset"
    assert "E2E_LEAK" not in call["env"] and "E2E_CACHE_DIR" not in call["env"]
    assert call["env"]["HOME"] == str(env.scratch / "home")
    assert (call["env"]["COLUMNS"], call["env"]["NO_COLOR"], call["env"]["TERM"]) == ("4096", "1", "dumb")
    artifacts = env.artifacts / "cli" / result.cwd.name
    assert sorted(path.name for path in artifacts.iterdir()) == ["cmd.txt", "exit_code.txt", "stderr.txt", "stdout.txt"]
    assert TOKEN not in (artifacts / "stdout.txt").read_text() and "***" in (artifacts / "stdout.txt").read_text()
    assert (artifacts / "exit_code.txt").read_text() == "0\n"
    cmd = (artifacts / "cmd.txt").read_text()
    assert cmd.splitlines()[0] == f"otterdog validate -c {config} --local {ORG}" and TOKEN not in cmd


def test_each_command_gets_a_fresh_cwd(env: Env) -> None:
    """Sequence numbers make cwd/artifact names unique; nothing leaks from one command to the next."""
    cli = env.cli()
    first = cli.show()
    (first.cwd / "leftover").write_text("x")
    second = cli.show()
    assert first.cwd != second.cwd and not (second.cwd / "leftover").exists()
    assert int(second.cwd.name[:4]) > int(first.cwd.name[:4])


def test_version_and_list_projects_argv(env: Env) -> None:
    """``--version`` is exactly [otterdog, --version]; list-projects gets -c but no org positional."""
    env.output("version", "otterdog.sh, version 1.6.1\n")
    cli = env.cli()
    assert cli.version() == "otterdog.sh, version 1.6.1"
    cli.list_projects()
    version_call, projects_call = env.calls()
    assert version_call["argv"][1:] == ["--version"]
    assert projects_call["argv"][1:] == ["list-projects", "-c", str(env.workspace.config_file.resolve())]


def test_command_flags(env: Env) -> None:
    """Exact flags of every command (verified against otterdog/cli.py)."""
    cli = env.cli()
    cli.plan(repo_filter="e2e-t3c7z8a5-*")
    cli.apply(repo_filter="e2e-t3c7z8a5-*", delete=True, update_secrets=True, update_webhooks=True)
    cli.apply()
    cli.local_plan(local=False)
    cli.import_config()
    cli.push_config(message="e2e push")
    cli.fetch_config(ref="main", pull_request=3)
    cli.fetch_config()
    cli.open_pr(branch="e2e-t3c7z8a5-pr", title="E2E PR", author="e2e-author-bot")
    cli.show(local=False)
    cli.show_default()
    cli.canonical_diff()
    cli.list_members()
    cli.check_token_permissions()
    cli.validate(verbose=True)
    config = str(env.workspace.config_file.resolve())
    observed = [call["argv"][1:] for call in env.calls()]
    assert observed == [
        ["plan", "-c", config, "-n", "-r", "e2e-t3c7z8a5-*", ORG],
        [
            "apply",
            "-c",
            config,
            "-f",
            "-n",
            "-r",
            "e2e-t3c7z8a5-*",
            "-d",
            "--update-secrets",
            "--update-webhooks",
            ORG,
        ],
        ["apply", "-c", config, "-f", "-n", ORG],
        ["local-plan", "-c", config, "-s", "-BASE", ORG],
        ["import", "-c", config, "-f", "-n", ORG],
        ["push-config", "-c", config, "-f", "-m", "e2e push", ORG],
        ["fetch-config", "-c", config, "-f", "-r", "main", "-p", "3", ORG],
        ["fetch-config", "-c", config, "-f", ORG],
        ["open-pr", "-c", config, "-b", "e2e-t3c7z8a5-pr", "-t", "E2E PR", "-a", "e2e-author-bot", ORG],
        ["show", "-c", config, ORG],
        ["show-default", "-c", config, "--local", ORG],
        ["canonical-diff", "-c", config, "--local", ORG],
        ["list-members", "-c", config, ORG],
        ["check-token-permissions", "-c", config, ORG],
        ["validate", "-c", config, "-v", ORG],
    ]
    stdin = {call["argv"][1]: call["stdin"] for call in env.calls()}
    assert stdin["open-pr"] == "y\n" and stdin["plan"] == ""


def test_infra_errors_are_detected(env: Env) -> None:
    """GitHub rate limits / connection failures set infra_error; assert_ok reports them."""
    env.output("plan", (DATA / "plan-network.txt").read_text(), exit_code=2)
    result = env.cli().plan()
    assert result.infra_error == (
        "Error: Cannot connect to host api.github.com:443 ssl:default [Temporary failure in name resolution]"
    )
    with pytest.raises(AssertionError, match="infra error"):
        result.assert_ok("plan")
    assert infra_error_line("You have exceeded a secondary rate limit") is not None
    assert infra_error_line("API rate limit exceeded for user ID 1.") is not None
    assert infra_error_line("Plan: 0 to add, 0 to change, 0 to delete.") is None


def test_timeouts_become_results(env: Env) -> None:
    """A command running past its timeout is killed and reported as timed out."""
    env.output("validate", "partial\n", sleep=5)
    result = env.cli().run("validate", timeout=0.5)
    assert result.timed_out and result.exit_code == -1
    with pytest.raises(AssertionError, match="timed out"):
        result.assert_ok()


def test_live_check_refuses_live_commands_only(env: Env) -> None:
    """DESTR-03: live_check (lost org lease) refuses every live command before otterdog starts; offline commands
    are not affected."""

    def lost() -> None:
        """The session's lease was taken over."""
        raise SafetyError("the org lease of run t3c7z8a5 was lost")

    cli = env.cli()
    cli.live_check = lost
    with pytest.raises(SafetyError, match="was lost"):
        cli.validate()
    assert env.calls() == []
    offline = env.cli(offline=True)
    offline.live_check = lost
    offline.validate()
    assert len(env.calls()) == 1


def test_check_status_returns_the_org_entry(env: Env, tmp_path: Path) -> None:
    """-n -j: otterdog writes a JSON list; the entry of the workspace org is returned and the file copied."""
    entries = [
        {"org_id": "other-org", "sync_status": {"in_sync": False}},
        {"org_id": "E2E-Test-Org", "sync_status": {"in_sync": True}},
    ]
    (env.outputs / "check-status.json").write_text(json.dumps(entries))
    env.output("check-status", (DATA / "check-status.txt").read_text())
    target = tmp_path / "out" / "status.json"
    result, entry = env.cli().check_status(target)
    assert result.argv[1:] == [
        "check-status",
        "-c",
        str(env.workspace.config_file.resolve()),
        "-n",
        "-j",
        "check-status.json",
        ORG,
    ]
    assert entry == entries[1]
    assert json.loads(target.read_text()) == entries
    assert (env.artifacts / "cli" / result.cwd.name / "check-status.json").is_file()
    (env.outputs / "check-status.json").unlink()
    assert env.cli().check_status(target)[1] is None


def test_observations_get_raw_stdout(env: Env) -> None:
    """``observe`` records the RAW stdout with meta exit_code under kind "cli"."""

    class Recorder:
        """Collects record() calls."""

        def __init__(self) -> None:
            self.records: list[tuple[str, str, Any, Mapping[str, Any] | None]] = []

        def record(self, kind: str, key: str, content: Any, *, meta: Mapping[str, Any] | None = None) -> None:
            self.records.append((kind, key, content, meta))

    raw = (DATA / "validate-unknown-property.txt").read_text()
    env.output("validate", raw, exit_code=0)
    recorder = Recorder()
    env.cli(recorder=recorder).validate(local=True, observe="validate")  # type: ignore[arg-type]
    assert recorder.records == [("cli", "validate", raw, {"exit_code": 0})]
    env.cli(recorder=recorder).validate()  # type: ignore[arg-type]
    assert len(recorder.records) == 1


def test_safety_rules(env: Env) -> None:
    """Live CLIs need a VerifiedOrg of the workspace org; live commands never get more than -v."""
    with pytest.raises(SafetyError, match="VerifiedOrg"):
        OtterdogCli(
            env.installed,
            env.workspace,
            verified=None,
            identity=None,
            scratch=env.scratch,
            artifacts_dir=env.artifacts,
            settings=env.settings,
        )
    with pytest.raises(SafetyError, match="not the verified org"):
        OtterdogCli(
            env.installed,
            env.workspace,
            verified=make_verified_org("other-org"),
            identity=None,
            scratch=env.scratch,
            artifacts_dir=env.artifacts,
            settings=env.settings,
        )
    with pytest.raises(SafetyError, match="more than -v"):
        env.cli().run("validate", "-vv")
    with pytest.raises(SafetyError, match="more than -v"):
        env.cli().run("validate", "-v", "--verbose")
    assert env.calls() == []


def test_offline_cli_uses_the_dummy_token(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Offline: no VerifiedOrg needed, dummy token, -vvv allowed, offline cache name."""
    monkeypatch.setattr(runner_module, "_unshare_available", lambda: False)
    monkeypatch.delenv("CI", raising=False)
    result = env.cli(offline=True).run("validate", "-vvv", local=True)
    (call,) = env.calls()
    assert call["env"]["E2E_OTTERDOG_API_TOKEN"] == "offline-dummy-token"
    assert call["cache_target"] == str(env.settings.cache_dir / "http-cache" / "v1.6.1-offline")
    assert result.exit_code == 0


def test_offline_sandbox(env: Env, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """unshare -rn when available; fail closed in CI without it; warn otherwise. Live commands are never wrapped."""
    cli = env.cli(offline=True)
    monkeypatch.setattr(runner_module, "_unshare_available", lambda: True)
    assert cli._sandbox() == ["unshare", "-rn"]
    assert env.cli()._sandbox() == []
    monkeypatch.setattr(runner_module, "_unshare_available", lambda: False)
    monkeypatch.setenv("CI", "true")
    with pytest.raises(SafetyError, match="sandbox"):
        cli._sandbox()
    monkeypatch.delenv("CI")
    with caplog.at_level(logging.WARNING):
        assert cli._sandbox() == []
    assert "without a network sandbox" in caplog.text


def test_http_cache_variants(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Untrusted SUTs get a per-run cache in scratch (http_cache_root: the run's directory when given);
    http_cache=False leaves no link."""
    env = Env(tmp_path, trusted=False)
    result = env.cli().show()
    assert env.calls()[0]["cache_target"] == str(env.scratch / "http-cache" / "v1.6.1-admin")
    env.cli(http_cache_root=tmp_path / "run-cache").show()
    assert env.calls()[1]["cache_target"] == str(tmp_path / "run-cache" / "v1.6.1-admin")
    env.calls().clear()
    assert result.cwd.joinpath(".cache", "async_http").is_symlink()
    no_cache = env.cli(http_cache=False).show()
    assert env.calls()[2]["cache_link"] is None and not no_cache.cwd.joinpath(".cache").exists()


class ContainerRuntime:
    """Stand-in for DockerRuntime: runs the fake script directly but checks the container contract."""

    in_container = True
    label = "docker:v1.6.1"

    def __init__(self, script: Path) -> None:
        """Run ``script``; remember what the runner passed."""
        self.script = script
        self.seen: list[dict[str, Any]] = []

    def command(self, args: Sequence[str], *, workdir: Path, env_file: Path | None) -> list[str]:
        """Record workdir and env-file (it must exist, 0600, with only the credentials)."""
        assert env_file is not None and env_file.is_file()
        self.seen.append(
            {
                "workdir": workdir,
                "env_file": env_file,
                "mode": stat.S_IMODE(env_file.stat().st_mode),
                "content": env_file.read_text(),
            }
        )
        return [str(self.script), *args]

    def env(self, credentials: Mapping[str, str]) -> dict[str, str]:
        """Credentials travel in the env-file only."""
        return {}


def test_container_layout(env: Env) -> None:
    """Container runtimes: workdir = workspace root, cwd = <workspace>/cwd, relative cache link, 0600 env-file."""
    cli = env.cli()
    runtime = ContainerRuntime(env.script)
    cli.runtime = runtime
    result = cli.validate()
    (seen,) = runtime.seen
    assert seen["workdir"] == env.workspace.root.resolve()
    assert result.cwd == env.workspace.root.resolve() / "cwd"
    assert seen["mode"] == 0o600 and seen["env_file"].parent == env.scratch / "env"
    assert seen["content"].splitlines() == [
        f"E2E_OTTERDOG_API_TOKEN={TOKEN}",
        "E2E_OTTERDOG_USERNAME=unset",
        "E2E_OTTERDOG_PASSWORD=unset",
        "E2E_OTTERDOG_TOTP_SEED=unset",
    ]
    assert not seen["env_file"].exists()
    (call,) = env.calls()
    assert "E2E_OTTERDOG_API_TOKEN" not in call["env"]
    assert call["cache_link"] == os.path.join("..", "..", ".http-cache", "v1.6.1-admin")
    assert call["cache_target"] == str(env.workspace.root.resolve() / ".http-cache" / "v1.6.1-admin")
    cli.validate()
    assert env.calls()[1]["cwd"] == str(result.cwd)  # recreated in place for the next command


def plant(env: Env, *items: dict[str, str]) -> None:
    """Make the fake otterdog plant links (``{"path", "link"}``) or FIFOs (``{"path"}``), paths relative to its cwd."""
    (env.outputs / "plant.json").write_text(json.dumps(list(items)))


def container_cli(env: Env) -> OtterdogCli:
    """A live CLI whose runtime is the container stand-in (the workspace root is the mount)."""
    cli = env.cli()
    cli.runtime = ContainerRuntime(env.script)
    return cli


def test_check_status_never_follows_a_link_planted_by_the_container(env: Env, tmp_path: Path) -> None:
    """ISO-01: check-status.json as a link to a host file (read primitive) and the destination json_file as a link
    to a host path (write primitive): the links leading out of the mount are removed after the command, so the host
    file is neither read, exported nor overwritten."""
    secret = tmp_path / "host-secret.txt"
    secret.write_text("aws_secret_access_key = not-a-token-shaped-value\n")
    host_target = tmp_path / "host-target.pth"
    plant(
        env,
        {"path": "check-status.json", "link": str(secret)},
        {"path": "../check-status.json", "link": str(host_target)},
    )
    cli = container_cli(env)
    json_file = env.workspace.root / "check-status.json"
    result, entry = cli.check_status(json_file)
    assert entry is None and not host_target.exists() and not json_file.exists()
    assert secret.read_text().startswith("aws_secret_access_key")
    exported = max((env.artifacts / "cli").iterdir())  # <seq>-check-status (container cwds are all "cwd")
    assert exported.name.endswith("check-status") and not (exported / "check-status.json").exists()
    assert "not-a-token-shaped-value" not in "".join(path.read_text() for path in exported.iterdir())
    assert any("removed 2 planted link(s)" in note for note in result.notes)
    assert "removed 2 planted link(s)" in (exported / "cmd.txt").read_text()


def test_check_status_writes_a_regular_copy_after_a_planted_destination_link(env: Env, tmp_path: Path) -> None:
    """A real check-status file is copied to json_file even when the container had planted a link there."""
    entries = [{"org_id": ORG, "sync_status": {"in_sync": True}}]
    (env.outputs / "check-status.json").write_text(json.dumps(entries))
    host_target = tmp_path / "elsewhere" / "status.json"
    plant(env, {"path": "../check-status.json", "link": str(host_target)})
    json_file = env.workspace.root / "check-status.json"
    _result, entry = container_cli(env).check_status(json_file)
    assert entry == entries[0] and not host_target.exists()
    assert not json_file.is_symlink() and json.loads(json_file.read_text()) == entries
    assert stat.S_IMODE(json_file.stat().st_mode) == 0o600


def test_a_planted_fifo_cannot_block_the_host(env: Env) -> None:
    """A FIFO named check-status.json is removed (a blocking read would hang the session)."""
    plant(env, {"path": "check-status.json"})
    result, entry = container_cli(env).check_status(env.scratch / "status.json")
    assert entry is None and not (result.cwd / "check-status.json").exists()


def test_planted_parent_links_cannot_redirect_writes_or_deletions(env: Env, tmp_path: Path) -> None:
    """A link replacing <ws>/orgs (to a host dir holding templates/ and <org>/) is removed after the command: the
    next config write and template cleanup stay inside the workspace."""
    host = tmp_path / "host-dir"
    (host / "templates").mkdir(parents=True)
    (host / "templates" / "keep.txt").write_text("host data")
    (host / ORG).mkdir()
    plant(env, {"path": "../orgs", "link": str(host)})
    cli = container_cli(env)
    cli.validate()
    assert not (env.workspace.root / "orgs").is_symlink()
    env.workspace.write_org_config("{}\n")
    env.workspace.clean_template_cache()
    assert (host / "templates" / "keep.txt").read_text() == "host data" and not (host / ORG / f"{ORG}.jsonnet").exists()
    assert env.workspace.read_org_config() == "{}\n"


def test_an_interruption_wins_over_a_failing_neutralization(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """The mount is neutralized after an interrupted container command too, but the interruption propagates even
    when the neutralization fails."""
    cli = container_cli(env)
    seen: list[str] = []

    def interrupted(*args: Any, **kwargs: Any) -> Any:
        """Ctrl-C while the container runs."""
        raise KeyboardInterrupt

    def broken(root: Path) -> list[str]:
        """The neutralization cannot inspect the mount."""
        seen.append(str(root))
        raise SafetyError("cannot inspect")

    monkeypatch.setattr(cli, "_execute", interrupted)
    monkeypatch.setattr(runner_module, "neutralize_untrusted_tree", broken)
    with pytest.raises(KeyboardInterrupt):
        cli.validate()
    assert seen == [str(env.workspace.root.resolve())]


def test_links_inside_the_mount_and_host_runtimes_are_left_alone(env: Env) -> None:
    """Links resolving inside the mount (the HTTP cache link among them) are kept; host runtimes are trusted and
    never swept."""
    plant(env, {"path": "inner-link", "link": "../otterdog.json"})
    result = container_cli(env).validate()
    assert (result.cwd / "inner-link").is_symlink() and (result.cwd / ".cache" / "async_http").is_symlink()
    assert not any("planted" in note for note in result.notes)
    host_result = env.cli().validate()
    assert (host_result.cwd / "inner-link").is_symlink()


# --- docker runtime: named containers, removed on timeout or interruption -------------------------------------------
class FakeDockerRun:
    """procs.run stand-in for the docker CLI: ``docker run`` gives ``run_outcome``; ``docker rm -f`` is recorded."""

    def __init__(self, run_outcome: BaseException | None = None) -> None:
        """``run_outcome``: exception raised by ``docker run`` (None: exit 0 with a validate output)."""
        self.run_outcome = run_outcome
        self.calls: list[list[str]] = []
        self.env_file_present: list[bool] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> runner_module.procs.CompletedProcess[str]:
        """Record the argv; raise or answer."""
        self.calls.append(list(argv))
        if argv[:2] == ["docker", "run"]:
            self.env_file_present.append(Path(argv[argv.index("--env-file") + 1]).is_file())
            if self.run_outcome is not None:
                raise self.run_outcome
            return runner_module.procs.CompletedProcess(argv, 0, "Validation succeeded\n", "")
        return runner_module.procs.CompletedProcess(argv, 0, "", "")

    def run_argv(self) -> list[str]:
        """The single ``docker run`` argv."""
        (argv,) = [call for call in self.calls if call[:2] == ["docker", "run"]]
        return argv

    def removed(self) -> list[str]:
        """Names passed to ``docker rm -f``."""
        return [call[3] for call in self.calls if call[:3] == ["docker", "rm", "-f"]]


class PytestTimeoutFailure(BaseException):
    """What pytest-timeout raises inside the running test (signal method)."""


def docker_cli(env: Env) -> OtterdogCli:
    """A live OtterdogCli whose runtime is the real DockerRuntime (image id instead of a host binary)."""
    sut = env.installed.sut
    installed = InstalledCli(sut, "docker", None, Path(IMAGE_OTTERDOG_BIN), "sha256:" + "f" * 64, "otterdog 1.6.1")
    return OtterdogCli(
        installed,
        env.workspace,
        verified=make_verified_org(ORG),
        identity=Identity("admin", "e2e-admin-bot", TOKEN),
        scratch=env.scratch,
        artifacts_dir=env.artifacts,
        settings=env.settings,
    )


@pytest.fixture
def run_scope() -> Iterator[str]:
    """Container names scoped to the fake run id."""
    set_container_scope("t3c7z8a5")
    yield "t3c7z8a5"
    set_container_scope(None)


def _seq_of(env: Env, command: str) -> str:
    """Command number of the (only) artifacts dir of ``command``."""
    (directory,) = [d.name for d in (env.artifacts / "cli").iterdir() if d.name.endswith(f"-{command}")]
    return directory.split("-", 1)[0]


def test_docker_commands_run_with_init_and_a_unique_name(
    env: Env, run_scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """--init and --name otterdog-e2e-<run>-<seq> (seq = the command's artifacts number); no rm when it completes."""
    docker = FakeDockerRun()
    monkeypatch.setattr(runner_module.procs, "run", docker)
    result = docker_cli(env).validate()
    argv = docker.run_argv()
    assert result.exit_code == 0 and argv[:6] == ["docker", "run", "--rm", "--init", "--name", argv[5]]
    assert argv[5] == f"otterdog-e2e-{run_scope}-{_seq_of(env, 'validate')}"
    assert docker.removed() == [] and docker.env_file_present == [True]
    assert (
        f"--name {argv[5]}" in (env.artifacts / "cli" / f"{_seq_of(env, 'validate')}-validate" / "cmd.txt").read_text()
    )


def test_timed_out_docker_commands_are_removed(env: Env, run_scope: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """A timeout removes the container (docker rm -f <name>) before the timed-out result is returned."""
    docker = FakeDockerRun(runner_module.procs.TimeoutExpired(["docker", "run"], 0.5, output=b"partial\n"))
    monkeypatch.setattr(runner_module.procs, "run", docker)
    result = docker_cli(env).plan()
    name = docker.run_argv()[5]
    assert result.timed_out and result.exit_code == -1 and result.stdout == "partial\n"
    assert docker.removed() == [name] and docker.calls[-1] == ["docker", "rm", "-f", name]
    assert not list((env.scratch / "env").iterdir())  # the credentials env-file is gone


@pytest.mark.parametrize("interruption", [KeyboardInterrupt(), SystemExit(143), PytestTimeoutFailure("Timeout >600s")])
def test_interrupted_docker_commands_are_removed(
    env: Env, run_scope: str, monkeypatch: pytest.MonkeyPatch, interruption: BaseException
) -> None:
    """Ctrl-C, SIGTERM (SystemExit/KeyboardInterrupt) and pytest-timeout remove the container, then propagate."""
    docker = FakeDockerRun(interruption)
    monkeypatch.setattr(runner_module.procs, "run", docker)
    with pytest.raises(type(interruption)):
        docker_cli(env).apply(delete=True)
    assert docker.removed() == [docker.run_argv()[5]]
    assert not list((env.scratch / "env").iterdir())


def test_errors_before_a_container_starts_do_not_remove(
    env: Env, run_scope: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ordinary error (no docker binary) started no container: nothing to remove, the error propagates."""
    docker = FakeDockerRun(FileNotFoundError("docker"))
    monkeypatch.setattr(runner_module.procs, "run", docker)
    with pytest.raises(FileNotFoundError):
        docker_cli(env).validate()
    assert docker.removed() == []


def test_a_failing_removal_never_hides_the_timeout(
    env: Env, run_scope: str, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """docker rm -f failing (daemon gone) is logged; the command is still reported as timed out."""
    docker = FakeDockerRun(runner_module.procs.TimeoutExpired(["docker", "run"], 0.5))
    monkeypatch.setattr(runner_module.procs, "run", docker)

    def failing_remove(name: str) -> bool:
        """The docker daemon went away."""
        raise RuntimeError(f"cannot remove {name}")

    monkeypatch.setattr(DockerRuntime, "remove", staticmethod(failing_remove))
    with caplog.at_level(logging.ERROR):
        assert docker_cli(env).validate().timed_out
    assert "could not remove container" in caplog.text


def test_host_and_stand_in_runtimes_have_no_container(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:
    """Host commands that time out remove nothing (procs already killed their process group)."""
    calls: list[list[str]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        """Time out every command."""
        calls.append(list(argv))
        raise runner_module.procs.TimeoutExpired(argv, 0.1)

    monkeypatch.setattr(runner_module.procs, "run", fake_run)
    assert env.cli().validate().timed_out
    assert len(calls) == 1 and calls[0][0] == str(env.script)
