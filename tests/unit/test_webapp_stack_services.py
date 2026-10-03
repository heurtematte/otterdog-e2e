"""WebappStack fail-fast and configuration helpers: single services, environment-override restarts, the dtrack profile.

docker is never run (procs.run is replaced). Verified for real against the webapp image of otterdog main 9bdeb75 in
local docker (dummy credentials): mongodb stopped -> a pull_request delivery answers 500 and the webapp logs "failed to
process webhook delivery <id> ..."; restart_webapp with GITHUB_WEBHOOK_ENDPOINT=/e2e/hooks moves the receiver (old
path 404), the container sees the overrides, the override file holds no value; the dtrack profile starts the mock,
published on 127.0.0.1 only.
"""

from __future__ import annotations

import stat
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
import yaml

from otterdog_e2e.settings import AppCredentials
from otterdog_e2e.testing.fakes import FAKE_ORG, make_run_context, make_verified_org
from otterdog_e2e.webapp import stack as stack_module
from otterdog_e2e.webapp.api import WebappApi
from otterdog_e2e.webapp.stack import (
    COMPOSE_VARIABLES,
    DTRACK_INTERNAL_URL,
    SERVICES,
    WEBAPP_ENV_OVERRIDES,
    DtrackMock,
    WebappSettings,
    WebappStack,
    WebappStackError,
    check_env_overrides,
    dummy_webapp_settings,
    parse_published_address,
    read_dtrack_mock,
)

PORT = 5988
WEBHOOK_SECRET = "e2e-services-webhook-secret-0123456789"
FAKE_PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEservicesunittest\n-----END RSA PRIVATE KEY-----\n"


class FakeDocker:
    """Records procs.run calls; answers per compose subcommand (the first argument after the global options)."""

    GLOBAL_OPTIONS = ("--project-name", "--project-directory", "--env-file", "--file", "--profile")

    def __init__(self) -> None:
        """No calls yet; every subcommand succeeds with empty output."""
        self.calls: list[dict[str, Any]] = []
        self.answers: dict[str, tuple[int, str, str]] = {}

    @classmethod
    def split(cls, argv: Sequence[str]) -> tuple[list[str], list[str]]:
        """(global options, subcommand and its arguments) of a ``docker compose`` argv."""
        index = 2
        while index < len(argv) and argv[index] in cls.GLOBAL_OPTIONS:
            index += 2
        return list(argv[2:index]), list(argv[index:])

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """procs.run replacement."""
        self.calls.append({"argv": list(argv), **kwargs})
        code, stdout, stderr = self.answers.get(self.split(argv)[1][0], (0, "", ""))
        return subprocess.CompletedProcess(list(argv), code, stdout, stderr)

    def commands(self) -> list[list[str]]:
        """Subcommands with their arguments, in call order."""
        return [self.split(call["argv"])[1] for call in self.calls]

    def options(self, index: int = -1) -> list[str]:
        """Global options of a call."""
        return self.split(self.calls[index]["argv"])[0]


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    """Replace procs.run in the stack module, neutralize atexit and the health probe."""
    fake = FakeDocker()
    monkeypatch.setattr(stack_module.procs, "run", fake)
    monkeypatch.setattr(stack_module.atexit, "register", lambda fn: None)
    monkeypatch.setattr(stack_module.atexit, "unregister", lambda fn: None)
    monkeypatch.setattr(WebappApi, "health", lambda self: True)
    return fake


def settings(**overrides: Any) -> WebappSettings:
    """Live-looking settings."""
    values: dict[str, Any] = {
        "org": FAKE_ORG,
        "configs_repo": "otterdog-e2e-configs",
        "config_token": "ghp_" + "s3rv1c3s" * 5,
        "app": AppCredentials(app_id="123456", private_key_pem=FAKE_PEM, webhook_secret=WEBHOOK_SECRET, slug="e2e-app"),
        "validation_context": "e2e/otterdog-validate",
        "sync_context": "e2e/otterdog-sync",
        "admin_team": "otterdog-admins",
        "approval_team": "project-leads",
        "port": PORT,
    }
    values.update(overrides)
    return WebappSettings(**values)


def make_stack(tmp_path: Path, **overrides: Any) -> WebappStack:
    """A live stack bound to the fake verified org."""
    return WebappStack(
        settings(**overrides),
        verified=make_verified_org(),
        image="otterdog-e2e/otterdog:v1.6.1",
        run_ctx=make_run_context(),
        scratch=tmp_path / "scratch",
        artifacts_dir=tmp_path / "artifacts",
    )


@pytest.fixture
def up(tmp_path: Path, docker: FakeDocker) -> WebappStack:
    """A stack that is up (one compose up recorded)."""
    stack = make_stack(tmp_path)
    stack.up(timeout=60)
    return stack


# --- dtrack profile ------------------------------------------------------------------------------------------------
def test_default_stack_has_no_profile_and_no_mock_url(tmp_path: Path, docker: FakeDocker) -> None:
    """Without the mock: no --profile, DEPENDENCY_TRACK_URL stays at the unreachable default."""
    stack = make_stack(tmp_path)
    env = stack.compose_environment()
    assert set(env) == set(COMPOSE_VARIABLES)
    assert env["E2E_DEPENDENCY_TRACK_URL"] == "http://127.0.0.1:9" and env["E2E_DTRACK_MOCK_STATUS"] == "200"
    assert env["E2E_DTRACK_MOCK_IMAGE"] == "python:3.12-alpine"
    stack.up(timeout=60)
    assert "--profile" not in docker.options() and not stack.dtrack_enabled
    with pytest.raises(WebappStackError):
        stack.dtrack()


def test_stack_with_the_mock_starts_the_profile(tmp_path: Path, docker: FakeDocker) -> None:
    """dtrack_mock=True: --profile dtrack on every call, the webapp points at the mock, down keeps the profile."""
    stack = make_stack(tmp_path, dtrack_mock=True, dtrack_status=503)
    env = stack.compose_environment()
    assert env["E2E_DEPENDENCY_TRACK_URL"] == DTRACK_INTERNAL_URL == "http://dtrack-mock:8080"
    assert env["E2E_DTRACK_MOCK_STATUS"] == "503"
    stack.up(timeout=60)
    assert docker.options()[-4:-2] == ["--profile", "dtrack"]
    docker.answers["port"] = (0, "127.0.0.1:49153\n", "")
    client = stack.dtrack()
    assert isinstance(client, DtrackMock) and client.base_url == "http://127.0.0.1:49153"
    assert docker.commands()[-1] == ["port", "dtrack-mock", "8080"]
    assert stack.dtrack() is client and len(docker.calls) == 2  # the port is read once
    stack.down()
    assert docker.commands()[-1][0] == "down" and docker.options()[-4:-2] == ["--profile", "dtrack"]
    stack.up(timeout=60)
    docker.answers["port"] = (0, "127.0.0.1:49154\n", "")
    assert stack.dtrack().base_url == "http://127.0.0.1:49154"  # a new container, a new port


def test_offline_settings_can_enable_the_mock(tmp_path: Path) -> None:
    """dummy_webapp_settings(dtrack_mock=True); an initial mock status that is no HTTP status is refused."""
    offline = dummy_webapp_settings(dtrack_mock=True)
    assert offline.dtrack_mock is True and offline.dtrack_status == 200
    broken = WebappSettings(**{**offline.__dict__, "dtrack_status": 42})
    with pytest.raises(ValueError, match="dtrack_status"):
        WebappStack(
            broken, verified=None, image="x", run_ctx=make_run_context(), scratch=tmp_path, artifacts_dir=tmp_path
        )


def test_enable_dtrack_mock_on_a_running_stack(
    up: WebappStack, docker: FakeDocker, monkeypatch: pytest.MonkeyPatch
) -> None:
    """enable_dtrack_mock: up --force-recreate dtrack-mock webapp with the profile and the mock URL, then the client
    answers ``status``; a second call reuses everything."""
    configured: list[int] = []
    monkeypatch.setattr(DtrackMock, "set_response", lambda self, status=200, body=None: configured.append(status) or {})
    docker.answers["port"] = (0, "127.0.0.1:40000\n", "")
    client = up.enable_dtrack_mock(status=500, timeout=90)
    recreate = docker.commands()[1]
    assert recreate == [
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "90",
        "--no-deps",
        "--force-recreate",
        "dtrack-mock",
        "webapp",
    ]
    assert docker.options(1)[-4:-2] == ["--profile", "dtrack"]
    assert docker.calls[1]["extra_env"]["E2E_DEPENDENCY_TRACK_URL"] == DTRACK_INTERNAL_URL
    assert up.dtrack_enabled and client.base_url == "http://127.0.0.1:40000" and configured == [500]
    up.enable_dtrack_mock()
    assert len([c for c in docker.commands() if c[0] == "up"]) == 2 and configured == [500, 200]


def test_enable_dtrack_mock_failure_rolls_back(up: WebappStack, docker: FakeDocker) -> None:
    """A failed recreate leaves the mock disabled and reports the redacted stderr and the log tail."""
    docker.answers["up"] = (1, "", "pull access denied for python")
    with pytest.raises(WebappStackError, match="pull access denied"):
        up.enable_dtrack_mock()
    assert not up.dtrack_enabled
    assert "E2E_DEPENDENCY_TRACK_URL" in docker.calls[1]["extra_env"]


def test_enable_dtrack_mock_needs_a_running_stack(tmp_path: Path, docker: FakeDocker) -> None:
    """Nothing started: refused before any compose call."""
    with pytest.raises(WebappStackError, match="not up"):
        make_stack(tmp_path).enable_dtrack_mock()
    assert docker.calls == []


@pytest.mark.parametrize(
    ("output", "address"),
    [
        ("127.0.0.1:32768\n", "127.0.0.1:32768"),
        ("\n127.0.0.1:1\n", "127.0.0.1:1"),
        ("localhost:8080", "127.0.0.1:8080"),
    ],
)
def test_parse_published_address(output: str, address: str) -> None:
    """docker compose port output: the last line, loopback only."""
    assert parse_published_address(output) == address


@pytest.mark.parametrize("output", ["", "0.0.0.0:32768", "192.168.1.2:80", "127.0.0.1:http"])
def test_parse_published_address_refuses_other_bindings(output: str) -> None:
    """No output, a public binding or garbage: WebappStackError."""
    with pytest.raises(WebappStackError):
        parse_published_address(output)


def test_write_files_installs_the_mock_script(tmp_path: Path) -> None:
    """dtrack_mock.py is written next to the compose file (0644, readable by the mock's container user)."""
    stack = make_stack(tmp_path)
    stack.write_files()
    assert stack.dtrack_mock_file.read_text() == read_dtrack_mock()
    assert stat.S_IMODE(stack.dtrack_mock_file.stat().st_mode) == 0o644
    assert "def make_server" in read_dtrack_mock() and not stack.override_file.exists()


# --- single services -----------------------------------------------------------------------------------------------
def test_stop_and_start_a_service(up: WebappStack, docker: FakeDocker) -> None:
    """stop: compose stop --timeout 10 <service>; start: up --wait --no-deps --no-recreate <service>."""
    up.stop_service("mongodb")
    up.start_service("mongodb", timeout=45)
    assert docker.commands()[1:] == [
        ["stop", "--timeout", "10", "mongodb"],
        ["up", "--detach", "--wait", "--wait-timeout", "45", "--no-deps", "--no-recreate", "mongodb"],
    ]
    up.start_service("webapp")  # the webapp is also waited for on /internal/health (patched healthy)
    assert docker.commands()[-1][-1] == "webapp"


def test_service_names_and_state(up: WebappStack, docker: FakeDocker, tmp_path: Path) -> None:
    """Unknown services and the mock without its profile are refused; a stack that is not up refuses too."""
    assert set(SERVICES) == {"webapp", "mongodb", "redis", "dtrack-mock"}
    with pytest.raises(ValueError):
        up.stop_service("postgres")
    with pytest.raises(ValueError, match="not enabled"):
        up.start_service("dtrack-mock")
    with pytest.raises(WebappStackError, match="not up"):
        make_stack(tmp_path / "other").stop_service("redis")


def test_service_failures_carry_stderr_and_log_tail(up: WebappStack, docker: FakeDocker) -> None:
    """A failing compose call raises WebappStackError with the redacted stderr and the webapp log tail."""
    docker.answers["stop"] = (1, "", f"no such service, secret {WEBHOOK_SECRET}")
    docker.answers["logs"] = (0, "webapp-1 | shutting down app\n", "")
    with pytest.raises(WebappStackError) as info:
        up.stop_service("redis")
    assert "no such service" in str(info.value) and "shutting down app" in str(info.value)
    assert WEBHOOK_SECRET not in str(info.value)


def test_running_services(up: WebappStack, docker: FakeDocker) -> None:
    """ps --services --status running, one name per line."""
    docker.answers["ps"] = (0, "redis\nwebapp\n\n", "")
    assert up.running_services() == ["redis", "webapp"]
    assert docker.commands()[-1] == ["ps", "--services", "--status", "running"]


def test_service_states(up: WebappStack, docker: FakeDocker) -> None:
    """ps --all with a tab-separated format: running services have no exit code, exited ones their code."""
    docker.answers["ps"] = (0, "mongodb\trunning\t0\nwebapp\texited\t0\nredis\texited\t137\n\n", "")
    assert up.service_states() == {"mongodb": ("running", None), "webapp": ("exited", 0), "redis": ("exited", 137)}
    assert docker.commands()[-1] == ["ps", "--all", "--format", "{{.Service}}\t{{.State}}\t{{.ExitCode}}"]


# --- environment overrides -----------------------------------------------------------------------------------------
def test_restart_webapp_with_overrides(up: WebappStack, docker: FakeDocker) -> None:
    """The override file maps each key to a compose variable (no value is written), the values travel in the compose
    environment, the webapp is recreated alone, the webhook URL follows the endpoint; {} restores the defaults."""
    overrides = {"GITHUB_ADMIN_TEAMS": "a, otterdog-admins", "GITHUB_WEBHOOK_ENDPOINT": "/e2e/hooks"}
    up.restart_webapp(overrides, timeout=30)
    assert docker.commands()[1] == [
        "up",
        "--detach",
        "--wait",
        "--wait-timeout",
        "30",
        "--no-deps",
        "--force-recreate",
        "webapp",
    ]
    options = docker.options(1)
    assert options[-4:] == ["--file", str(up.compose_file), "--file", str(up.override_file)]
    text = up.override_file.read_text()
    assert "otterdog-admins" not in text and "/e2e/hooks" not in text
    document = yaml.safe_load(text)
    assert document["services"]["webapp"]["environment"] == {
        "GITHUB_ADMIN_TEAMS": "${E2E_ENV_GITHUB_ADMIN_TEAMS}",
        "GITHUB_WEBHOOK_ENDPOINT": "${E2E_ENV_GITHUB_WEBHOOK_ENDPOINT}",
    }
    env = docker.calls[1]["extra_env"]
    assert (
        env["E2E_ENV_GITHUB_ADMIN_TEAMS"] == "a, otterdog-admins"
        and env["E2E_ENV_GITHUB_WEBHOOK_ENDPOINT"] == "/e2e/hooks"
    )
    assert up.webhook_url == f"http://127.0.0.1:{PORT}/e2e/hooks" and up.env_overrides == overrides
    up.logs()
    assert "--file" in docker.options() and str(up.override_file) in docker.options()  # every later call too
    up.restart_webapp({})
    assert not up.override_file.exists() and up.env_overrides == {}
    assert up.webhook_url == f"http://127.0.0.1:{PORT}/github-webhook/receive"
    assert str(up.override_file) not in docker.options()


def test_restart_failure_keeps_the_previous_overrides(up: WebappStack, docker: FakeDocker) -> None:
    """A failed recreate restores the previous overrides (and their file)."""
    up.restart_webapp({"BLUEPRINT_CHECK_INTERVAL": "3600"})
    docker.answers["up"] = (1, "", "container webapp is unhealthy")
    with pytest.raises(WebappStackError, match="unhealthy"):
        up.restart_webapp({"GITHUB_APPROVAL_TEAMS": "^e2e-.*$"})
    assert up.env_overrides == {"BLUEPRINT_CHECK_INTERVAL": "3600"}
    assert "E2E_ENV_BLUEPRINT_CHECK_INTERVAL" in up.override_file.read_text()


def test_restart_needs_a_running_stack(tmp_path: Path, docker: FakeDocker) -> None:
    """Nothing started: refused."""
    with pytest.raises(WebappStackError, match="not up"):
        make_stack(tmp_path).restart_webapp({"DEBUG": "False"})


def test_check_env_overrides_accepts_the_allowlist() -> None:
    """Every allowed key with a plausible value passes (values are kept verbatim, regex patterns included)."""
    values = {
        "GITHUB_ADMIN_TEAMS": "a, otterdog-admins",
        "GITHUB_APPROVAL_TEAMS": "^project-leads$,e2e-.*",
        "GITHUB_WEBHOOK_ENDPOINT": "/github-webhook/receive-2",
        "GITHUB_WEBHOOK_VALIDATION_CONTEXT": "e2e/validate",
        "GITHUB_WEBHOOK_SYNC_CONTEXT": "e2e/sync",
        "BLUEPRINT_CHECK_INTERVAL": "3600",
        "PULL_REQUEST_STATISTICS_CACHE_TTL": "0",
        "DEPENDENCY_TRACK_URL": "http://dtrack-mock:8080",
        "DEPENDENCY_TRACK_TOKEN": "e2e-dummy-other",
        "PROJECTS_BASE_URL": "https://otterdog-e2e.invalid/p/",
        "DEBUG": "False",
        "CACHE_CONTROL": "",
        "GITHUB_OAUTH_CLIENT_ID": "e2e-dummy-oauth-client",
        "GITHUB_OAUTH_CLIENT_SECRET": "e2e-dummy-oauth-secret",
    }
    assert set(values) == set(WEBAPP_ENV_OVERRIDES)
    assert check_env_overrides(values) == values
    for url in ("http://127.0.0.1:9", "http://localhost:1", "http://dtrack.e2e.invalid/x"):
        check_env_overrides({"DEPENDENCY_TRACK_URL": url})


@pytest.mark.parametrize(
    "env",
    [
        {"GITHUB_WEBHOOK_SECRET": "x"},
        {"OTTERDOG_CONFIG_TOKEN": "x"},
        {"SECRET_KEY": "x"},
        {"MONGO_URI": "mongodb://elsewhere"},
        {"GHPROXY_URI": "http://ghproxy"},
        {"GITHUB_ADMIN_TEAMS": "a\nb"},
        {"GITHUB_ADMIN_TEAMS": 3},
        {"GITHUB_WEBHOOK_ENDPOINT": "github-webhook"},
        {"GITHUB_WEBHOOK_ENDPOINT": "/a b"},
        {"DEPENDENCY_TRACK_URL": "https://dependencytrack.example.org"},
        {"DEPENDENCY_TRACK_URL": "ftp://127.0.0.1"},
        {"DEPENDENCY_TRACK_TOKEN": "odt_realLookingToken"},
        {"GITHUB_OAUTH_CLIENT_ID": "Iv1.0123456789abcdef"},
        {"GITHUB_OAUTH_CLIENT_SECRET": "0123456789abcdef0123456789abcdef01234567"},
    ],
)
def test_check_env_overrides_refuses(env: dict[str, Any]) -> None:
    """Secrets, the App, MongoDB/Redis/ghproxy, multi-line values, bad endpoints, foreign Dependency-Track URLs and
    non-dummy tokens are refused."""
    with pytest.raises(ValueError):
        check_env_overrides(env)
