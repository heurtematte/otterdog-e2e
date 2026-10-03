"""Web mode of the otterdog runner (WebOtterdogCli): argv without -n, the web login only for login commands, the
Playwright browsers path, the LoginGate, refusals for containers/untrusted SUTs, redaction, page dumps."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.otterdog.runner import (
    WEB_LOGIN_COMMANDS,
    OtterdogCli,
    WebMode,
    WebOtterdogCli,
    check_web_runtime,
)
from otterdog_e2e.otterdog.workspace import CREDENTIAL_ENV, ConfigWorkspace, web_credentials_env
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import HarnessSettings, Identity, WebCredentials
from otterdog_e2e.sut.cli_install import InstalledCli
from otterdog_e2e.sut.spec import ResolvedSut, SutSpec
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import make_verified_org
from otterdog_e2e.webui.gate import LoginGate, WebLoginBlockedError

ORG = "e2e-test-org"
TOKEN = "ghp_" + "Wq7" * 12
PASSWORD = "bot-password-Zx81-not-real"
SEED = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"
WRAPPER = '#!/bin/sh\nexec "{python}" "{script}" "$@"\n'
FAKE_OTTERDOG = """
import json, os, sys
from pathlib import Path

here = Path(__file__).resolve().parent
args = sys.argv[1:]
command = args[0].lstrip("-") if args else ""
keys = ("HOME", "PLAYWRIGHT_BROWSERS_PATH", "E2E_ADMIN_PASSWORD")
record = {
    "argv": sys.argv[1:],
    "env": {k: v for k, v in os.environ.items() if k.startswith("E2E_OTTERDOG") or k in keys},
    "stdin": sys.stdin.read(),
}
with open(here / "calls.jsonl", "a") as handle:
    handle.write(json.dumps(record) + "\\n")
outputs = here / "outputs"
if (outputs / f"{command}.dumps").exists():
    Path("web_2026_https___github.com_login.html").write_text("<html>page</html>")
    Path("web_2026_https___github.com_login.png").write_bytes(b"png")
if (outputs / f"{command}.leak").exists():
    print("password=" + os.environ.get("E2E_OTTERDOG_PASSWORD", "") + " seed=" + os.environ.get("E2E_OTTERDOG_TOTP_SEED", ""))
if (outputs / f"{command}.txt").exists():
    sys.stdout.write((outputs / f"{command}.txt").read_text())
sys.exit(int((outputs / f"{command}.exit").read_text()) if (outputs / f"{command}.exit").exists() else 0)
"""


class Clock:
    """Fake wall clock for the gate (sleep advances it)."""

    def __init__(self) -> None:
        """Start at a fixed epoch."""
        self.now = 1_800_000_000.0

    def __call__(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance."""
        self.now += seconds


class Env:
    """A fake trusted host installation, workspace, settings, web credentials and gate under tmp_path."""

    def __init__(self, tmp_path: Path) -> None:
        """Write the fake otterdog and the workspace."""
        self.bin_dir = tmp_path / "fake-otterdog"
        self.outputs = self.bin_dir / "outputs"
        self.outputs.mkdir(parents=True)
        program = self.bin_dir / "fake_otterdog.py"
        program.write_text(FAKE_OTTERDOG)
        script = self.bin_dir / "otterdog"
        script.write_text(WRAPPER.format(python=sys.executable, script=program))
        script.chmod(0o755)
        self.settings = HarnessSettings(
            project_root=tmp_path,
            cache_dir=tmp_path / "cache",
            artifacts_root=tmp_path / "artifacts",
            upstream_repo="eclipse-csi/otterdog",
            targets_dir=tmp_path / "targets",
            scenarios_dir=tmp_path / "scenarios",
        )
        self.script = script
        self.scratch = tmp_path / "scratch"
        self.artifacts = tmp_path / "artifacts" / "run"
        self.workspace = ConfigWorkspace(
            self.scratch / "workspace", org=ORG, template=offline_template(), config_repo=".otterdog"
        )
        self.workspace.write_otterdog_json()
        self.clock = Clock()
        self.gate = LoginGate(
            self.settings.cache_dir / "webui", account="e2e-admin", clock=self.clock, sleep=self.clock.sleep
        )
        self.credentials = WebCredentials("admin", "e2e-admin", "e2e-admin", PASSWORD, SEED)
        self.browsers = self.settings.cache_dir / "ms-playwright"

    def installed(self, *, trusted: bool = True, runtime: str = "host") -> InstalledCli:
        """InstalledCli of the fake otterdog."""
        sut = ResolvedSut(
            spec=SutSpec("release:latest", "release", "latest"),
            label="v1.6.1",
            sha="c" * 40,
            version="1.6.1",
            image_version="1.6.1",
            source_dir=self.bin_dir,
            repo_url="https://github.com/eclipse-csi/otterdog",
            trusted=trusted,
        )
        image = "otterdog-e2e/untrusted:x" if runtime == "docker" else None
        return InstalledCli(sut, runtime, None, self.script, image, "otterdog.sh, version 1.6.1")

    def web_cli(self, **kwargs: Any) -> WebOtterdogCli:
        """WebOtterdogCli over the fake installation (admin identity, web mode)."""
        identity = kwargs.pop("identity", Identity("admin", "e2e-admin", TOKEN))
        return WebOtterdogCli(
            kwargs.pop("installed", self.installed()),
            self.workspace,
            verified=make_verified_org(ORG),
            identity=identity,
            web=WebMode(self.credentials, self.gate, self.browsers),
            scratch=self.scratch,
            artifacts_dir=self.artifacts,
            settings=self.settings,
            **kwargs,
        )

    def plain_cli(self) -> OtterdogCli:
        """An ordinary live OtterdogCli over the same installation."""
        return OtterdogCli(
            self.installed(),
            self.workspace,
            verified=make_verified_org(ORG),
            identity=Identity("admin", "e2e-admin", TOKEN),
            scratch=self.scratch,
            artifacts_dir=self.artifacts,
            settings=self.settings,
        )

    def calls(self) -> list[dict[str, Any]]:
        """Recorded invocations."""
        path = self.bin_dir / "calls.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def output(self, command: str, text: str = "", *, exit_code: int | None = None, flag: str | None = None) -> None:
        """Canned output, exit code or behaviour flag (dumps, leak) of a command."""
        (self.outputs / f"{command}.txt").write_text(text)
        if exit_code is not None:
            (self.outputs / f"{command}.exit").write_text(str(exit_code))
        if flag is not None:
            (self.outputs / f"{command}.{flag}").write_text("1")


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Env:
    """Fake environment; the caller's admin password must never reach otterdog through inheritance."""
    monkeypatch.setenv("E2E_ADMIN_PASSWORD", "inherited-password-123456")
    return Env(tmp_path)


def test_web_mode_omits_the_no_web_ui_flag(env: Env) -> None:
    """plan/apply/import/check-status: ``-n`` for ordinary CLIs, never in web mode."""
    plain, web = env.plain_cli(), env.web_cli()
    for cli in (plain, web):
        cli.plan(repo_filter="e2e-*")
        cli.apply()
        cli.import_config()
        cli.check_status(env.scratch / "status.json")
    argvs = [call["argv"] for call in env.calls()]
    for argv in argvs[:4]:
        assert "-n" in argv, argv
    for argv in argvs[4:]:
        assert "-n" not in argv and "--no-web-ui" not in argv, argv
    assert argvs[4][:1] == ["plan"] and argvs[4][-3:] == ["-r", "e2e-*", ORG]
    assert argvs[5][:2] == ["apply", "-c"] and "-f" in argvs[5]
    assert argvs[6][0] == "import" and "-f" in argvs[6]
    assert argvs[7][0] == "check-status" and "-j" in argvs[7]


def test_login_commands_get_the_web_login_others_do_not(env: Env) -> None:
    """Username, password and seed only reach login commands (with PLAYWRIGHT_BROWSERS_PATH); others get "unset"."""
    cli = env.web_cli()
    cli.plan()
    cli.validate()
    cli.show(local=True)
    cli.list_advisories(use_web=False)
    login, validate, show, advisories = env.calls()
    assert login["env"][CREDENTIAL_ENV["username"]] == "e2e-admin"
    assert login["env"][CREDENTIAL_ENV["password"]] == PASSWORD
    assert login["env"][CREDENTIAL_ENV["twofa_seed"]] == SEED
    assert login["env"][CREDENTIAL_ENV["api_token"]] == TOKEN
    assert login["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(env.browsers)
    for call in (validate, show, advisories):
        assert (
            call["env"][CREDENTIAL_ENV["password"]] == "unset" and call["env"][CREDENTIAL_ENV["twofa_seed"]] == "unset"
        )
        assert "PLAYWRIGHT_BROWSERS_PATH" not in call["env"]
    for call in env.calls():
        assert "E2E_ADMIN_PASSWORD" not in call["env"], "inherited secrets never reach otterdog"
        assert call["env"]["HOME"] == str(env.scratch / "home")


def test_the_gate_admits_every_login_command_and_only_those(env: Env) -> None:
    """One gate session per login command, spaced a TOTP window apart; none for offline-style commands."""
    cli = env.web_cli()
    cli.plan()
    cli.show(local=True)
    cli.show_live()
    cli.list_advisories(use_web=True)
    cli.list_advisories(use_web=False)
    cli.run("plan", "-n")  # an explicit -n never logs in
    assert [ticket.what for ticket in env.gate.tickets] == ["plan", "show-live", "list-advisories"]
    assert env.gate.tickets[1].waited == pytest.approx(env.gate.spacing)
    cmd = (env.artifacts / "cli").glob("*-show-live/cmd.txt")
    assert "# web_ui: login gate admitted show-live after" in next(cmd).read_text()
    assert {"plan", "apply", "import", "show-live", "check-status", "web-login"} <= WEB_LOGIN_COMMANDS


def test_ui_command_argv(env: Env) -> None:
    """install-app/uninstall-app -a, review-permissions without -g, list-advisories -s -w, web-login stdin."""
    cli = env.web_cli()
    cli.install_app("probe-app")
    cli.uninstall_app("probe-app")
    cli.review_permissions()
    cli.review_permissions(app_slug="probe-app")
    cli.list_advisories(states=("triage", "draft"))
    cli.web_login()
    argvs = [call["argv"] for call in env.calls()]
    assert argvs[0][0] == "install-app" and argvs[0][-3:] == ["-a", "probe-app", ORG]
    assert argvs[1][0] == "uninstall-app" and argvs[1][-3:] == ["-a", "probe-app", ORG]
    assert argvs[2][0] == "review-permissions" and "-g" not in argvs[2] and "-a" not in argvs[2]
    assert argvs[3][-3:] == ["-a", "probe-app", ORG]
    assert argvs[4][0] == "list-advisories" and argvs[4][-6:] == ["-s", "triage", "-s", "draft", "-w", ORG]
    assert argvs[5][0] == "web-login" and env.calls()[5]["stdin"] == "\n"
    assert len(env.gate.tickets) == 6


def test_web_credentials_never_reach_artifacts(env: Env) -> None:
    """A command printing the password and seed: stdout and cmd.txt copies are redacted."""
    env.output("plan", "Plan: 0 to add, 0 to change, 0 to delete.\n", flag="leak")
    cli = env.web_cli()
    result = cli.plan()
    assert PASSWORD in result.stdout  # the raw result keeps it (otterdog printed it)
    for path in (env.artifacts / "cli").rglob("*.txt"):
        text = path.read_text()
        assert PASSWORD not in text and SEED not in text, path


def test_blocking_login_failure_blocks_the_gate(env: Env) -> None:
    """``incorrect username or password``: noted, the gate blocks, the next web command is refused."""
    env.output("plan", "planning aborted: incorrect username or password\n", exit_code=1)
    cli = env.web_cli()
    result = cli.plan()
    assert any("credentials failure" in note for note in result.notes)
    assert env.gate.blocked() is not None
    with pytest.raises(WebLoginBlockedError):
        cli.show_live()
    cli.validate()  # commands that do not log in still run


def test_non_blocking_failure_only_notes(env: Env) -> None:
    """``unable to launch browser``: noted, the gate stays open."""
    env.output("show-live", "RuntimeError: unable to launch browser, make sure you have installed ...\n", exit_code=2)
    result = env.web_cli().show_live()
    assert any("browser failure" in note for note in result.notes) and env.gate.blocked() is None


def test_page_dumps_stay_in_scratch(env: Env) -> None:
    """web_*.html/png written into the cwd are noted and never copied to the artifacts."""
    env.output("apply", "Executed plan: 0 added, 1 changed, 0 live resources ignored.\n", flag="dumps")
    result = env.web_cli().apply()
    assert sorted(path.name for path in result.cwd.glob("web_*")) == [
        "web_2026_https___github.com_login.html",
        "web_2026_https___github.com_login.png",
    ]
    assert any("2 page dump(s) kept in the scratch cwd" in note for note in result.notes)
    assert not list(env.artifacts.rglob("web_*"))
    assert result.cwd.is_relative_to(env.scratch)


def test_web_mode_never_gets_more_than_one_v(env: Env) -> None:
    """-vv and more trace TOTP codes and locals: refused."""
    cli = env.web_cli()
    with pytest.raises(SafetyError, match="more than -v"):
        cli.run("plan", "-vv")
    cli.run("plan", "-v")


def test_web_mode_refusals(env: Env) -> None:
    """No web mode for docker runtimes, untrusted SUTs, other identities or another account's token."""
    with pytest.raises(SafetyError, match="container"):
        env.web_cli(installed=env.installed(runtime="docker"))
    with pytest.raises(SafetyError, match="untrusted"):
        env.web_cli(installed=env.installed(trusted=False))
    with pytest.raises(SafetyError, match="admin identity"):
        env.web_cli(identity=Identity("author", "e2e-author", TOKEN))
    with pytest.raises(SafetyError, match="not the account"):
        env.web_cli(identity=Identity("admin", "someone-else", TOKEN))
    check_web_runtime(env.installed(), Identity("admin", "E2E-Admin", TOKEN), env.credentials)  # case-insensitive


def test_ordinary_clis_have_no_web_mode(env: Env) -> None:
    """OtterdogCli.web is None and its commands never get the web login."""
    cli = env.plain_cli()
    assert cli.web is None
    cli.run("show-live", "-n")
    (call,) = env.calls()
    assert call["env"][CREDENTIAL_ENV["password"]] == "unset" and not env.gate.tickets


def test_web_credentials_env() -> None:
    """The token plus the three web values."""
    values = web_credentials_env(
        Identity("admin", "a", TOKEN), WebCredentials("admin", "a", "a@example.org", PASSWORD, SEED)
    )
    assert values == {
        "E2E_OTTERDOG_API_TOKEN": TOKEN,
        "E2E_OTTERDOG_USERNAME": "a@example.org",
        "E2E_OTTERDOG_PASSWORD": PASSWORD,
        "E2E_OTTERDOG_TOTP_SEED": SEED,
    }
    assert "bot-password" not in repr(WebCredentials("admin", "a", "a", PASSWORD, SEED))


def test_failure_texts_in_a_successful_output_never_block(env: Env) -> None:
    """A plan quoting a failure text (e.g. in a description diff) exits 0: noted, not blocking."""
    env.output(
        "plan", '  ~ description = "incorrect username or password"\nPlan: 0 to add, 1 to change, 0 to delete.\n'
    )
    result = env.web_cli().plan()
    assert result.exit_code == 0 and env.gate.blocked() is None
    assert any("credentials failure" in note for note in result.notes)
