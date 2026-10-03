"""WebappStack / ExternalWebapp (SPEC 13.1): compose environment, scratch files, no secrets in argv or logs, teardown,
readiness rule; docker is never run (procs.run is replaced)."""

from __future__ import annotations

import logging
import stat
import subprocess
import tomllib
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import responses
from cryptography.hazmat.primitives import serialization

from otterdog_e2e import read_resource
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import AppCredentials
from otterdog_e2e.testing.fakes import FAKE_ORG, make_run_context, make_verified_org
from otterdog_e2e.webapp import stack as stack_module
from otterdog_e2e.webapp.api import RemoteEndpointError, WebappApi
from otterdog_e2e.webapp.stack import (
    COMPOSE_VARIABLES,
    DUMMY_CONFIG_TOKEN,
    ExternalWebapp,
    WebappNotReadyError,
    WebappSettings,
    WebappStack,
    WebappStackError,
    dummy_webapp_settings,
    generate_dummy_app_credentials,
    is_dummy,
    wait_webapp_ready,
)

PORT = 5987
BASE = f"http://127.0.0.1:{PORT}"
CONFIG_TOKEN = "ghp_" + "c0nf1gR3ad" * 4  # token-shaped: redacted by pattern too
WEBHOOK_SECRET = "e2e-stack-webhook-secret-0123456789"
FAKE_PEM = (
    "-----BEGIN RSA PRIVATE KEY-----\n"
    + "MIIEowIBAAKCAQEAstackunittest0123456789abcdef\n" * 3
    + "-----END RSA PRIVATE KEY-----\n"
)


class FakeDocker:
    """Records procs.run calls and answers per compose subcommand."""

    def __init__(self) -> None:
        """No calls yet; every subcommand succeeds with empty output."""
        self.calls: list[dict[str, Any]] = []
        self.answers: dict[str, tuple[int, str, str]] = {}

    def __call__(self, argv: Sequence[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        """procs.run replacement."""
        argv = list(argv)
        self.calls.append({"argv": argv, **kwargs})
        command = argv[argv.index("--file") + 2]
        code, stdout, stderr = self.answers.get(command, (0, "", ""))
        return subprocess.CompletedProcess(argv, code, stdout, stderr)

    def commands(self) -> list[str]:
        """Compose subcommands in call order."""
        return [call["argv"][call["argv"].index("--file") + 2] for call in self.calls]


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    """Replace procs.run in the stack module and neutralize atexit."""
    fake = FakeDocker()
    monkeypatch.setattr(stack_module.procs, "run", fake)
    registered: list[Any] = []
    monkeypatch.setattr(stack_module.atexit, "register", registered.append)
    monkeypatch.setattr(
        stack_module.atexit, "unregister", lambda fn: registered.remove(fn) if fn in registered else None
    )
    fake.registered = registered  # type: ignore[attr-defined]
    return fake


@pytest.fixture
def healthy(monkeypatch: pytest.MonkeyPatch) -> None:
    """The published port answers /internal/health."""
    monkeypatch.setattr(WebappApi, "health", lambda self: True)


def live_settings(**overrides: Any) -> WebappSettings:
    """Settings of a live stack (real-looking credentials)."""
    values: dict[str, Any] = {
        "org": FAKE_ORG,
        "configs_repo": "otterdog-e2e-configs",
        "config_token": CONFIG_TOKEN,
        "app": AppCredentials(app_id="123456", private_key_pem=FAKE_PEM, webhook_secret=WEBHOOK_SECRET, slug="e2e-app"),
        "validation_context": "e2e/otterdog-validate",
        "sync_context": "e2e/otterdog-sync",
        "admin_team": "otterdog-admins",
        "approval_team": "project-leads",
        "workers": 2,
        "port": PORT,
    }
    values.update(overrides)
    return WebappSettings(**values)


def make_stack(
    tmp_path: Path, settings: WebappSettings | None = None, *, image: str = "otterdog-e2e/otterdog:v1.6.1"
) -> WebappStack:
    """A live stack bound to the fake verified org."""
    return WebappStack(
        settings or live_settings(),
        verified=make_verified_org(),
        image=image,
        run_ctx=make_run_context(),
        scratch=tmp_path / "scratch",
        artifacts_dir=tmp_path / "artifacts",
    )


def secrets_of(stack: WebappStack) -> list[str]:
    """Every secret the stack handles."""
    pem_line = "MIIEowIBAAKCAQEAstackunittest0123456789abcdef"
    return [stack.secret_key, stack.settings.app.webhook_secret, stack.settings.config_token, pem_line]


# --- construction --------------------------------------------------------------------------------------------------
def test_names_and_urls(tmp_path: Path) -> None:
    """Project name carries the run id; the webapp is only reachable on 127.0.0.1."""
    stack = make_stack(tmp_path)
    assert stack.project_name == "otterdog-e2e-t3c7z8a5"
    assert stack.base_url == BASE and stack.webhook_url == f"{BASE}/github-webhook/receive"
    assert stack.api.base_url == BASE


def test_binding_to_the_verified_org(tmp_path: Path) -> None:
    """Live credentials need the VerifiedOrg of the same org; invalid settings are refused."""
    with pytest.raises(SafetyError):
        make_stack(tmp_path, live_settings(org="some-other-org"))
    with pytest.raises(SafetyError):
        WebappStack(
            live_settings(),
            verified=None,
            image="x",
            run_ctx=make_run_context(),
            scratch=tmp_path,
            artifacts_dir=tmp_path,
        )
    for overrides in ({"workers": 0}, {"port": 0}, {"admin_team": "a, b"}, {"approval_team": "^x$"}):
        with pytest.raises(ValueError):
            make_stack(tmp_path, live_settings(**overrides))
    with pytest.raises(ValueError):
        make_stack(tmp_path, image="")


def test_offline_stack_needs_dummy_credentials(tmp_path: Path) -> None:
    """verified=None is accepted only with generate_dummy_app_credentials + DUMMY_CONFIG_TOKEN."""
    settings = dummy_webapp_settings(port=PORT)
    assert is_dummy(settings) and settings.config_token == DUMMY_CONFIG_TOKEN
    WebappStack(
        settings,
        verified=None,
        image="otterdog-e2e/otterdog:v1.6.1",
        run_ctx=make_run_context(),
        scratch=tmp_path,
        artifacts_dir=tmp_path,
    )
    forged = WebappSettings(**{**settings.__dict__, "config_token": CONFIG_TOKEN})
    assert not is_dummy(forged)
    with pytest.raises(SafetyError):
        WebappStack(
            forged, verified=None, image="x", run_ctx=make_run_context(), scratch=tmp_path, artifacts_dir=tmp_path
        )


def test_generate_dummy_app_credentials() -> None:
    """Random RSA 2048 PEM, app id "1", random secret, all redacted."""
    first, second = generate_dummy_app_credentials(), generate_dummy_app_credentials()
    key = serialization.load_pem_private_key(first.private_key_pem.encode(), password=None)
    assert key.key_size == 2048  # type: ignore[union-attr]
    assert first.app_id == "1" and first.webhook_secret != second.webhook_secret
    assert first.private_key_pem != second.private_key_pem
    assert REDACTOR(f"x {first.webhook_secret} y") == "x *** y"
    assert "BEGIN RSA PRIVATE KEY" not in REDACTOR(first.private_key_pem)
    assert "webhook_secret" not in repr(first) or first.webhook_secret not in repr(first)


# --- environment and files -----------------------------------------------------------------------------------------
def test_compose_environment_matches_the_compose_file(tmp_path: Path) -> None:
    """Exactly COMPOSE_VARIABLES, with the SPEC 13.1 values."""
    stack = make_stack(tmp_path)
    env = stack.compose_environment()
    assert set(env) == set(COMPOSE_VARIABLES)
    assert env["E2E_BASE_URL"] == BASE and env["E2E_WEBAPP_PORT"] == str(PORT)
    assert env["E2E_CONFIG_OWNER"] == FAKE_ORG and env["E2E_CONFIGS_REPO"] == "otterdog-e2e-configs"
    assert env["E2E_CONFIG_TOKEN"] == CONFIG_TOKEN and env["E2E_WEBHOOK_SECRET"] == WEBHOOK_SECRET
    assert env["E2E_GITHUB_APP_ID"] == "123456" and len(env["E2E_SECRET_KEY"]) == 64
    assert env["E2E_ADMIN_TEAMS"] == "otterdog-admins" and env["E2E_APPROVAL_TEAMS"] == "^project-leads$"
    assert env["E2E_VALIDATION_CONTEXT"] == "e2e/otterdog-validate" and env["E2E_SYNC_CONTEXT"] == "e2e/otterdog-sync"
    assert env["E2E_GITHUB_APP_KEY_FILE"] == str(stack.key_file) and env["E2E_HYPERCORN_CFG"] == str(
        stack.hypercorn_file
    )
    assert env["E2E_WEBAPP_PULL_POLICY"] == "never"
    assert (
        make_stack(tmp_path, image="ghcr.io/eclipse-csi/otterdog:v1.6.1").compose_environment()[
            "E2E_WEBAPP_PULL_POLICY"
        ]
        == "missing"
    )
    assert make_stack(tmp_path).secret_key != stack.secret_key  # per run


def test_secrets_are_registered_with_the_redactor(tmp_path: Path) -> None:
    """SECRET_KEY, webhook secret, config token and key are redacted everywhere."""
    stack = make_stack(tmp_path)
    text = " ".join(secrets_of(stack))
    assert all(secret not in REDACTOR(text) for secret in secrets_of(stack))


def test_write_files(tmp_path: Path) -> None:
    """Compose file copy, empty env file, hypercorn config and a 0600 key in a 0700 dir, all under scratch."""
    stack = make_stack(tmp_path)
    stack.write_files()
    assert stack.run_dir == tmp_path / "scratch" / "webapp"
    assert stack.compose_file.read_text() == read_resource("compose.e2e.yaml")
    assert stack.env_file.read_text() == ""
    assert stat.S_IMODE(stack.key_file.stat().st_mode) == 0o600 and stack.key_file.read_text() == FAKE_PEM
    assert stat.S_IMODE(stack.secrets_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(stack.run_dir.stat().st_mode) == 0o700
    config = tomllib.loads(stack.hypercorn_file.read_text())
    assert config["bind"] == "0.0.0.0:5000" and config["workers"] == 2 and config["accesslog"] == "-"
    assert not (tmp_path / "artifacts").exists()  # nothing secret or not lands in artifacts


# --- lifecycle -----------------------------------------------------------------------------------------------------
def test_up_runs_compose_without_secrets_in_argv_or_logs(
    tmp_path: Path, docker: FakeDocker, healthy: None, caplog: pytest.LogCaptureFixture
) -> None:
    """up: one ``compose up --detach --wait`` with the variables in the env (keep_home), nothing secret logged."""
    caplog.set_level(logging.DEBUG)
    stack = make_stack(tmp_path)
    stack.up(timeout=120)
    (call,) = docker.calls
    argv = call["argv"]
    assert argv[:4] == ["docker", "compose", "--project-name", "otterdog-e2e-t3c7z8a5"]
    assert argv[argv.index("--file") + 1] == str(stack.compose_file)
    assert argv[argv.index("--env-file") + 1] == str(stack.env_file)
    assert argv[argv.index("--project-directory") + 1] == str(stack.run_dir)
    assert argv[-5:] == ["up", "--detach", "--wait", "--wait-timeout", "120"]
    assert call["keep_home"] is True and call["extra_env"] == stack.compose_environment()
    assert call["cwd"] == stack.run_dir
    flat = " ".join(argv) + " " + caplog.text
    assert all(secret not in flat for secret in secrets_of(stack))
    assert docker.registered == [stack._atexit_down]  # type: ignore[attr-defined]


def test_down_is_idempotent_and_removes_the_key(tmp_path: Path, docker: FakeDocker, healthy: None) -> None:
    """down -v --remove-orphans once, key removed, atexit hook dropped; a second down does nothing."""
    stack = make_stack(tmp_path)
    stack.up()
    stack.down()
    stack.down()
    assert docker.commands() == ["up", "down"]
    down = docker.calls[1]["argv"]
    assert down[-5:] == ["down", "--volumes", "--remove-orphans", "--timeout", "10"]
    assert not stack.key_file.exists() and not stack.secrets_dir.exists()
    assert docker.registered == []  # type: ignore[attr-defined]


def test_down_without_up_never_calls_docker(tmp_path: Path, docker: FakeDocker) -> None:
    """Nothing was started: no compose call."""
    make_stack(tmp_path).down()
    assert docker.calls == []


def test_failed_down_keeps_the_atexit_retry(tmp_path: Path, docker: FakeDocker, healthy: None) -> None:
    """A failing down is logged, the key is still removed and the atexit hook stays registered."""
    stack = make_stack(tmp_path)
    stack.up()
    docker.answers["down"] = (1, "", "daemon unavailable")
    stack.down()
    assert not stack.key_file.exists()
    assert docker.registered == [stack._atexit_down]  # type: ignore[attr-defined]


def test_up_failure_saves_logs_tears_down_and_reports_redacted_tail(tmp_path: Path, docker: FakeDocker) -> None:
    """compose up fails: logs saved to artifacts (redacted), stack torn down, error carries the redacted log tail."""
    stack = make_stack(tmp_path)
    docker.answers["up"] = (1, "", f"container webapp is unhealthy {stack.secret_key}")
    docker.answers["logs"] = (0, f"webapp-1 | GITHUB_WEBHOOK_SECRET={WEBHOOK_SECRET} failed to start\n", "")
    with pytest.raises(WebappStackError) as info:
        stack.up(timeout=60)
    message = str(info.value)
    assert "failed to start" in message and "unhealthy" in message
    assert all(secret not in message for secret in secrets_of(stack))
    assert docker.commands() == ["up", "logs", "logs", "down"]
    log_file = tmp_path / "artifacts" / "webapp" / "compose.log"
    assert "failed to start" in log_file.read_text() and WEBHOOK_SECRET not in log_file.read_text()
    assert not stack.key_file.exists()


def test_logs_are_redacted_and_saved(tmp_path: Path, docker: FakeDocker) -> None:
    """logs() masks the run's secrets; save_logs writes artifacts/webapp/compose.log."""
    stack = make_stack(tmp_path)
    docker.answers["logs"] = (0, f"SECRET_KEY={stack.secret_key} token {CONFIG_TOKEN}\n", "")
    assert stack.logs(tail=5) == "SECRET_KEY=*** token ***\n"
    assert docker.calls[-1]["argv"][-5:] == ["logs", "--no-color", "--timestamps", "--tail", "5"]
    path = stack.save_logs()
    assert path == tmp_path / "artifacts" / "webapp" / "compose.log"
    assert path.read_text() == "SECRET_KEY=*** token ***\n"


def test_logs_survive_a_missing_docker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No docker binary: logs() explains instead of raising."""

    def missing(*args: Any, **kwargs: Any) -> None:
        """procs.run without docker."""
        raise FileNotFoundError("docker")

    monkeypatch.setattr(stack_module.procs, "run", missing)
    assert "unavailable" in make_stack(tmp_path).logs()


@responses.activate
def test_init_failure_carries_the_log_tail(tmp_path: Path, docker: FakeDocker) -> None:
    """/internal/init != 200 raises WebappStackError with the webapp log tail."""
    stack = make_stack(tmp_path)
    responses.get(f"{BASE}/internal/init", status=500, json={})
    docker.answers["logs"] = (0, "webapp-1 | refreshing otterdog config failed\n", "")
    with pytest.raises(WebappStackError) as info:
        stack.init()
    assert "refreshing otterdog config failed" in str(info.value)
    assert stack.init_at is not None
    responses.replace(responses.GET, f"{BASE}/internal/init", json={})
    stack.init()


# --- readiness -----------------------------------------------------------------------------------------------------
class FakeTime:
    """Fake monotonic clock driven by sleep()."""

    def __init__(self) -> None:
        """t=0."""
        self.now = 0.0

    def clock(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance."""
        self.now += seconds


def ready_api() -> WebappApi:
    """WebappApi with a fake clock."""
    api = WebappApi(BASE)
    fake = FakeTime()
    api.sleep, api.clock = fake.sleep, fake.clock
    return api


def fetch_task(status: str, created_at: str = "2026-10-02T12:00:05") -> dict[str, Any]:
    """A FetchConfigTask row."""
    return {"type": "FetchConfigTask", "org_id": FAKE_ORG, "status": status, "created_at": created_at, "log": "boom"}


@responses.activate
def test_wait_ready_rule() -> None:
    """Org listed (exact case) -> config fetched (200) -> newest FetchConfigTask finished."""
    orgs = f"{BASE}/api/organizations"
    responses.get(orgs, json=[{"github_id": FAKE_ORG.upper(), "project_name": "x"}])  # wrong case is not enough
    responses.get(orgs, json=[{"github_id": FAKE_ORG, "project_name": "x"}])
    responses.get(f"{BASE}/api/organizations/{FAKE_ORG}", status=404, json={})
    responses.get(f"{BASE}/api/organizations/{FAKE_ORG}", json={"github_id": FAKE_ORG})
    responses.get(f"{BASE}/api/tasks", json={"data": [fetch_task("scheduled")]})
    responses.get(f"{BASE}/api/tasks", json={"data": [fetch_task("finished")]})
    wait_webapp_ready(ready_api(), org=FAKE_ORG, timeout=120)
    task_calls = [call for call in responses.calls if "/api/tasks" in call.request.url]
    assert task_calls[-1].request.params["type"] == "^FetchConfigTask$"


@responses.activate
def test_wait_ready_failed_fetch_config_fails_fast_with_log_tail() -> None:
    """A failed newest FetchConfigTask cannot become ready: immediate error with the task log and the log tail."""
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": FAKE_ORG}])
    responses.get(f"{BASE}/api/organizations/{FAKE_ORG}", json={})
    responses.get(f"{BASE}/api/tasks", json={"data": [fetch_task("failed")]})
    api = ready_api()
    with pytest.raises(WebappNotReadyError) as info:
        wait_webapp_ready(api, org=FAKE_ORG, timeout=300, log_tail=lambda: "LOG TAIL")
    assert "failed: boom" in str(info.value) and "LOG TAIL" in str(info.value)
    assert api.clock() == 0  # no waiting


@responses.activate
def test_wait_ready_ignores_tasks_older_than_init() -> None:
    """With ``after`` (init time) an old finished FetchConfigTask does not count; timeout explains why."""
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": FAKE_ORG}])
    responses.get(f"{BASE}/api/organizations/{FAKE_ORG}", json={})
    responses.get(f"{BASE}/api/tasks", json={"data": [fetch_task("finished", "2026-10-02T11:00:00")]})
    with pytest.raises(WebappNotReadyError) as info:
        wait_webapp_ready(ready_api(), org=FAKE_ORG, timeout=10, after=datetime(2026, 10, 2, 12, tzinfo=UTC))
    assert "no FetchConfigTask" in str(info.value)


@responses.activate
def test_wait_ready_tolerates_transient_errors() -> None:
    """Connection errors / 5xx while the webapp starts count as not ready."""
    responses.get(f"{BASE}/api/organizations", status=502, body="bad gateway")
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": FAKE_ORG}])
    responses.get(f"{BASE}/api/organizations/{FAKE_ORG}", json={})
    responses.get(f"{BASE}/api/tasks", json={"data": [fetch_task("finished")]})
    wait_webapp_ready(ready_api(), org=FAKE_ORG, timeout=60)


@responses.activate
def test_stack_wait_ready_uses_init_time(tmp_path: Path, docker: FakeDocker) -> None:
    """WebappStack.wait_ready filters tasks created before its own init()."""
    stack = make_stack(tmp_path)
    fake = FakeTime()
    stack.api.sleep, stack.api.clock = fake.sleep, fake.clock
    stack.init_at = datetime(2026, 10, 2, 12, tzinfo=UTC)
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": FAKE_ORG}])
    responses.get(f"{BASE}/api/organizations/{FAKE_ORG}", json={})
    responses.get(f"{BASE}/api/tasks", json={"data": [fetch_task("finished", "2026-10-02T12:00:00.000")]})
    stack.wait_ready(timeout=5)


# --- external transport --------------------------------------------------------------------------------------------
def test_external_webapp_is_loopback_only() -> None:
    """Remote URLs (base or init) need allow_remote."""
    with pytest.raises(RemoteEndpointError):
        ExternalWebapp("https://otterdog.eclipse.org", init_url=None)
    with pytest.raises(RemoteEndpointError):
        ExternalWebapp("http://127.0.0.1:5000", init_url="https://otterdog.eclipse.org/internal/init")
    remote = ExternalWebapp("https://otterdog.example.org/", init_url=None, allow_remote=True)
    assert remote.webhook_url == "https://otterdog.example.org/github-webhook/receive"
    local = ExternalWebapp("http://localhost:5000", init_url=None)
    assert local.api.base_url == "http://localhost:5000"
    local.init()  # no init URL: nothing to call
    assert local.init_at is None


@responses.activate
def test_external_webapp_init_url() -> None:
    """init() GETs the configured init URL and fails on non-200."""
    webapp = ExternalWebapp("http://127.0.0.1:5000", init_url="http://127.0.0.1:5001/internal/init")
    responses.get("http://127.0.0.1:5001/internal/init", json={})
    webapp.init()
    assert webapp.init_at is not None
    responses.replace(responses.GET, "http://127.0.0.1:5001/internal/init", status=500, json={})
    with pytest.raises(WebappStackError):
        webapp.init()
