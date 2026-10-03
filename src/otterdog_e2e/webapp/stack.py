"""The SUT webapp in docker compose (resources/compose.e2e.yaml) or an external loopback deployment (SPEC 13.1).

Every compose value is passed through the environment of the ``docker compose`` process (COMPOSE_VARIABLES, given
as procs.run extra_env); never write ``docker compose config`` / ``docker inspect`` output to artifacts. The App key is
a 0600 file in scratch mounted as a compose secret; ``down -v --remove-orphans`` always runs (finally/atexit).

Webapp facts (otterdog/webapp/config.py, app.py): every REQUIRED_NON_EMPTY_SETTINGS entry must be non-empty or the app
refuses to start; GITHUB_APP_PRIVATE_KEY is the PATH of the PEM; under DEBUG app.py logs ``"CACHE_CONTROL = " + value``
(an unset value is the bool False -> TypeError) and any non-empty string enables Cache-Control headers, hence "";
GITHUB_APPROVAL_TEAMS entries are re.search patterns (``^<team>$`` is exact).

Fail-fast and configuration cases (coverage webapp-runtime.*, receiver.hook-exception): ``stop_service`` /
``start_service`` stop and start one compose service (mongodb and valkey keep their data in memory: a restart empties
them, call init() and wait_ready() afterwards); ``restart_webapp(env)`` recreates the webapp container with environment
overrides (WEBAPP_ENV_OVERRIDES only, e.g. ``GITHUB_ADMIN_TEAMS`` with spaces, approval team patterns, another
``GITHUB_WEBHOOK_ENDPOINT``), whose values reach compose as variables of its process environment through a generated
compose.override.yaml, never written to a file. The ``dtrack`` profile runs the Dependency-Track mock
(resources/dtrack_mock.py, ``DtrackMock`` client) and points DEPENDENCY_TRACK_URL at it: at ``up()`` with
``WebappSettings.dtrack_mock``, or later with ``enable_dtrack_mock()`` (recreates the webapp).
"""

from __future__ import annotations

import atexit
import json
import logging
import os
import re
import secrets
import shutil
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

import jinja2
import requests

from otterdog_e2e import procs, read_resource, waiting
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import AppCredentials
from otterdog_e2e.webapp.api import (
    VERSION_RE,
    WebappApi,
    WebappApiError,
    floor_to_millis,
    local_session,
    parse_timestamp,
    require_loopback_url,
)

if TYPE_CHECKING:
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.safety import VerifiedOrg

__all__ = [
    "COMPOSE_OPTIONAL_VARIABLES",
    "COMPOSE_REQUIRED_VARIABLES",
    "COMPOSE_RESOURCE",
    "COMPOSE_VARIABLES",
    "DTRACK_INTERNAL_URL",
    "DTRACK_MOCK_RESOURCE",
    "DTRACK_PROFILE",
    "DTRACK_SERVICE",
    "DUMMY_CONFIG_TOKEN",
    "DUMMY_OVERRIDES",
    "HYPERCORN_RESOURCE",
    "LOOPBACK_HOSTS",
    "SERVICES",
    "VERSION_RE",
    "WEBAPP_ENV_OVERRIDES",
    "WEBHOOK_PATH",
    "DtrackMock",
    "ExternalWebapp",
    "WebappNotReadyError",
    "WebappSettings",
    "WebappStack",
    "WebappStackError",
    "check_env_overrides",
    "dummy_webapp_settings",
    "generate_dummy_app_credentials",
    "is_dummy",
    "wait_webapp_ready",
]

_logger = logging.getLogger(__name__)

COMPOSE_RESOURCE = "compose.e2e.yaml"
HYPERCORN_RESOURCE = "hypercorn.toml.j2"
WEBHOOK_PATH = "/github-webhook/receive"
# interpolation variables of compose.e2e.yaml (required ones first); WebappStack passes exactly these
COMPOSE_REQUIRED_VARIABLES = (
    "E2E_WEBAPP_IMAGE",
    "E2E_HYPERCORN_CFG",
    "E2E_GITHUB_APP_KEY_FILE",
    "E2E_BASE_URL",
    "E2E_CONFIG_OWNER",
    "E2E_CONFIG_TOKEN",
    "E2E_GITHUB_APP_ID",
    "E2E_WEBHOOK_SECRET",
    "E2E_SECRET_KEY",
)
COMPOSE_OPTIONAL_VARIABLES = (
    "E2E_WEBAPP_PORT",
    "E2E_WEBAPP_PULL_POLICY",
    "E2E_CONFIGS_REPO",
    "E2E_VALIDATION_CONTEXT",
    "E2E_SYNC_CONTEXT",
    "E2E_ADMIN_TEAMS",
    "E2E_APPROVAL_TEAMS",
    "E2E_DEPENDENCY_TRACK_URL",
    "E2E_DTRACK_MOCK_IMAGE",
    "E2E_DTRACK_MOCK_STATUS",
)
COMPOSE_VARIABLES = COMPOSE_REQUIRED_VARIABLES + COMPOSE_OPTIONAL_VARIABLES
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
LOCAL_IMAGE_PREFIX = "otterdog-e2e/"  # images built by sut.image (never pulled)
DUMMY_CONFIG_TOKEN = "e2e-dummy-config-token"  # noqa: S105 - OTTERDOG_CONFIG_TOKEN of offline stacks, no secret
DUMMY_APP_SLUG = "otterdog-e2e-dummy"
READY_INTERVAL = 3.0
HEALTH_TIMEOUT = 60.0
COMPOSE_DOWN_TIMEOUT = 180.0
SERVICE_TIMEOUT = 300.0
LOG_TAIL = 150
SERVICES = ("webapp", "mongodb", "redis", "dtrack-mock")  # services of compose.e2e.yaml
# Dependency-Track mock (compose profile, resources/dtrack_mock.py)
DTRACK_PROFILE = "dtrack"
DTRACK_SERVICE = "dtrack-mock"
DTRACK_MOCK_RESOURCE = "dtrack_mock.py"
DTRACK_MOCK_IMAGE = "python:3.12-alpine"
DTRACK_CONTAINER_PORT = 8080
DTRACK_INTERNAL_URL = f"http://{DTRACK_SERVICE}:{DTRACK_CONTAINER_PORT}"  # what the webapp container reaches
NO_DTRACK_URL = "http://127.0.0.1:9"  # compose default: nothing listens there
OVERRIDE_FILE = "compose.override.yaml"
OVERRIDE_VARIABLE_PREFIX = "E2E_ENV_"  # compose variable carrying the value of an environment override
# webapp settings restart_webapp may override (otterdog/webapp/config.py); secrets, App, MongoDB, Redis, the config
# repository and ghproxy are never overridable
WEBAPP_ENV_OVERRIDES = frozenset(
    {
        "GITHUB_ADMIN_TEAMS",
        "GITHUB_APPROVAL_TEAMS",
        "GITHUB_WEBHOOK_ENDPOINT",
        "GITHUB_WEBHOOK_VALIDATION_CONTEXT",
        "GITHUB_WEBHOOK_SYNC_CONTEXT",
        "BLUEPRINT_CHECK_INTERVAL",
        "PULL_REQUEST_STATISTICS_CACHE_TTL",
        "DEPENDENCY_TRACK_URL",
        "DEPENDENCY_TRACK_TOKEN",
        "PROJECTS_BASE_URL",
        "DEBUG",
        "CACHE_CONTROL",
        # dummies only: QuartAuth and the login routes exist once an OAuth client id is configured (no login is
        # possible with them, the pages only answer as they would without a session)
        "GITHUB_OAUTH_CLIENT_ID",
        "GITHUB_OAUTH_CLIENT_SECRET",
    }
)
DUMMY_OVERRIDES = frozenset({"DEPENDENCY_TRACK_TOKEN", "GITHUB_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_SECRET"})
_ENDPOINT_RE = re.compile(r"^/[A-Za-z0-9/_.~-]*$")
_DUMMY_VALUE_RE = re.compile(r"^e2e-dummy[A-Za-z0-9_.-]*$")
_TEAM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_DUMMY_CREDENTIALS: set[AppCredentials] = set()  # minted by generate_dummy_app_credentials (offline stacks)


class WebappStackError(RuntimeError):
    """The webapp stack failed to start, to initialize or to report readiness (message carries the log tail)."""


class WebappNotReadyError(WebappStackError):
    """The webapp did not become ready for the org within the timeout."""


@dataclass
class WebappSettings:
    """Values the webapp container is configured with."""

    org: str
    configs_repo: str
    config_token: str
    app: AppCredentials
    validation_context: str
    sync_context: str
    admin_team: str
    approval_team: str
    workers: int = 1
    port: int = 5000
    dtrack_mock: bool = False  # start the compose profile ``dtrack`` (Dependency-Track mock) with the stack
    dtrack_status: int = 200  # initial answer of the mock to BOM uploads (DtrackMock.set_response changes it)


def generate_dummy_app_credentials() -> AppCredentials:
    """Random RSA 2048 PEM, app_id "1" and a random webhook secret (offline tier); all registered with REDACTOR."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL, serialization.NoEncryption()
    ).decode("ascii")
    creds = AppCredentials(app_id="1", private_key_pem=pem, webhook_secret=secrets.token_hex(20), slug=DUMMY_APP_SLUG)
    REDACTOR.add(creds.private_key_pem, creds.webhook_secret)
    _DUMMY_CREDENTIALS.add(creds)
    return creds


def dummy_webapp_settings(
    org: str = "e2e-offline", *, workers: int = 1, port: int = 5000, dtrack_mock: bool = False
) -> WebappSettings:
    """WebappSettings of an offline stack: dummy App credentials and config token, e2e contexts and teams."""
    return WebappSettings(
        org=org,
        configs_repo="otterdog-e2e-configs",
        config_token=DUMMY_CONFIG_TOKEN,
        app=generate_dummy_app_credentials(),
        validation_context="e2e/otterdog-validate",
        sync_context="e2e/otterdog-sync",
        admin_team="otterdog-admins",
        approval_team="project-leads",
        workers=workers,
        port=port,
        dtrack_mock=dtrack_mock,
    )


def is_dummy(settings: WebappSettings) -> bool:
    """True when the settings carry no real credential (generate_dummy_app_credentials + DUMMY_CONFIG_TOKEN)."""
    return settings.app in _DUMMY_CREDENTIALS and settings.config_token == DUMMY_CONFIG_TOKEN


def _check_settings(settings: WebappSettings, verified: VerifiedOrg | None, image: str) -> None:
    """SafetyError/ValueError for a stack that is not bound to the verified org or has invalid settings."""
    if verified is None:
        if not is_dummy(settings):
            raise SafetyError("a WebappStack without VerifiedOrg only runs with dummy credentials (offline tier)")
    elif settings.org != verified.login:
        raise SafetyError(f"webapp org {settings.org!r} is not the verified org {verified.login!r}")
    if not image:
        raise ValueError("webapp image is required")
    if settings.workers < 1 or not 0 < settings.port < 65536:
        raise ValueError(f"invalid webapp workers/port: {settings.workers}/{settings.port}")
    if not 100 <= settings.dtrack_status <= 599:
        raise ValueError(f"dtrack_status {settings.dtrack_status} is not an HTTP status")
    for name, team in (("admin_team", settings.admin_team), ("approval_team", settings.approval_team)):
        if not _TEAM_RE.match(team):  # GITHUB_ADMIN_TEAMS entries are not stripped; ',' separates entries
            raise ValueError(f"{name} {team!r} must be a single team slug")


def _check_dtrack_url(value: str) -> None:
    """DEPENDENCY_TRACK_URL overrides: the mock, a loopback address or an ``.invalid`` host (SBOMs and the token
    never leave the machine)."""
    parts = urllib.parse.urlsplit(value)
    host = (parts.hostname or "").lower()
    if parts.scheme not in ("http", "https") or not (
        host == DTRACK_SERVICE or host in LOOPBACK_HOSTS or host.startswith("127.") or host.endswith(".invalid")
    ):
        raise ValueError(
            f"DEPENDENCY_TRACK_URL {value!r} must point to the mock ({DTRACK_INTERNAL_URL}), a loopback address or an "
            ".invalid host"
        )


def check_env_overrides(env: Mapping[str, str]) -> dict[str, str]:
    """Validated copy of webapp environment overrides: WEBAPP_ENV_OVERRIDES keys, single-line string values, a
    ``/``-path webhook endpoint, a contained Dependency-Track URL and dummy values (e2e-dummy...) for the
    Dependency-Track token and the OAuth client (DUMMY_OVERRIDES), else ValueError."""
    checked: dict[str, str] = {}
    for key, value in env.items():
        if key not in WEBAPP_ENV_OVERRIDES:
            raise ValueError(f"{key!r} cannot be overridden (allowed: {sorted(WEBAPP_ENV_OVERRIDES)})")
        if not isinstance(value, str) or any(char in value for char in "\r\n\x00"):
            raise ValueError(f"the override of {key} must be a single-line string, got {value!r}")
        if key == "GITHUB_WEBHOOK_ENDPOINT" and not _ENDPOINT_RE.match(value):
            raise ValueError(f"GITHUB_WEBHOOK_ENDPOINT {value!r} must be a path such as /github-webhook/receive")
        if key == "DEPENDENCY_TRACK_URL":
            _check_dtrack_url(value)
        if key in DUMMY_OVERRIDES and not _DUMMY_VALUE_RE.match(value):
            raise ValueError(f"{key} overrides must be dummies (e2e-dummy...)")
        checked[key] = value
    return checked


def read_dtrack_mock() -> str:
    """Source of resources/dtrack_mock.py (package data next to the compose file)."""
    return (files("otterdog_e2e") / "resources" / DTRACK_MOCK_RESOURCE).read_text(encoding="utf-8")


def _readiness(api: WebappApi, org: str, after: datetime | None) -> str | None:
    """Why the webapp is not ready for ``org`` yet (None when ready); WebappNotReadyError when it cannot become ready."""
    listed = [row.get("github_id") for row in api.organizations()]
    if org not in listed:
        return f"/api/organizations does not list {org!r} (listed: {listed}); is otterdog.json loaded (/internal/init)?"
    if api.organization(org) is None:
        return f"/api/organizations/{org} is 404: no configuration fetched yet (is the App installed on {org}?)"
    floor = floor_to_millis(after) if after is not None else None
    tasks = [
        task
        for task in api.tasks(org_id=org, type_="FetchConfigTask", page_size=10)
        if floor is None or (parse_timestamp(task.get("created_at")) or floor) >= floor
    ]
    if not tasks:
        return f"no FetchConfigTask for {org} yet"
    newest = tasks[0]
    if newest.get("status") == "failed":
        raise WebappNotReadyError(f"FetchConfigTask of {org} failed: {REDACTOR(str(newest.get('log')))[:2000]}")
    if newest.get("status") != "finished":
        return f"newest FetchConfigTask of {org} is {newest.get('status')}"
    return None


def wait_webapp_ready(
    api: WebappApi,
    *,
    org: str,
    timeout: float = 300,
    after: datetime | None = None,
    log_tail: Callable[[], str] | None = None,
) -> None:
    """Poll until /api/organizations lists ``org`` (exact), /api/organizations/<org> is 200 and the newest
    FetchConfigTask of the org (created after ``after``) finished; WebappNotReadyError otherwise."""
    reasons: list[str] = []

    def check() -> bool:
        """One readiness probe (transient HTTP errors count as not ready)."""
        try:
            reason = _readiness(api, org, after)
        except (requests.RequestException, WebappApiError) as exc:
            reason = f"webapp API not answering: {type(exc).__name__}: {exc}"
        reasons.append(reason or "ready")
        return reason is None

    try:
        waiting.wait_until(
            check,
            timeout=timeout,
            interval=READY_INTERVAL,
            what=f"webapp ready for {org}",
            sleep=api.sleep,
            clock=api.clock,
        )
    except waiting.WaitTimeoutError as exc:
        tail = f"\n--- webapp log tail ---\n{log_tail()}" if log_tail is not None else ""
        raise WebappNotReadyError(f"webapp not ready for {org} within {timeout:g} s: {reasons[-1]}{tail}") from exc
    except WebappNotReadyError as exc:
        tail = f"\n--- webapp log tail ---\n{log_tail()}" if log_tail is not None else ""
        raise WebappNotReadyError(f"{exc}{tail}") from exc


class DtrackMock:
    """Client of the Dependency-Track mock (resources/dtrack_mock.py) on its 127.0.0.1 port mapping."""

    def __init__(self, base_url: str, *, timeout: float = 10.0, session: requests.Session | None = None) -> None:
        """Bind the loopback base URL (RemoteEndpointError otherwise); requests session with trust_env False."""
        require_loopback_url(base_url, what="Dependency-Track mock URL")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = local_session(session)
        self.sleep: Callable[[float], None] = time.sleep  # injectable for tests
        self.clock: Callable[[], float] = time.monotonic

    def _call(self, method: str, path: str, *, json_body: Any = None) -> Any:
        """One request to the mock; WebappApiError unless 200; returns the decoded JSON."""
        url = f"{self.base_url}{path}"
        response = self.session.request(method, url, json=json_body, timeout=self.timeout, allow_redirects=False)
        if response.status_code != 200:
            raise WebappApiError(method, url, response.status_code, response.text)
        return response.json()

    def health(self) -> bool:
        """GET /health == 200 (connection errors count as unhealthy)."""
        try:
            self._call("GET", "/health")
        except (requests.RequestException, WebappApiError, ValueError):
            return False
        return True

    def recorded(self) -> list[dict[str, Any]]:
        """Every request recorded by the mock (GET /requests, oldest first; BOM uploads carry the decoded ``bom``)."""
        return list(self._call("GET", "/requests") or [])

    def uploads(self) -> list[dict[str, Any]]:
        """The recorded BOM uploads (PUT or POST /api/v1/bom)."""
        return [entry for entry in self.recorded() if entry.get("path") == "/api/v1/bom"]

    def clear(self) -> None:
        """Forget the recorded requests."""
        self._call("DELETE", "/requests")

    def set_response(self, status: int = 200, body: str | None = None) -> dict[str, Any]:
        """Answer later uploads with ``status`` (otterdog only accepts 200) and ``body`` (None: a token document)."""
        return dict(self._call("POST", "/config", json_body={"status": status, "body": body}))

    def config(self) -> dict[str, Any]:
        """The configured upload answer ({status, body})."""
        return dict(self._call("GET", "/config"))

    def wait_uploads(
        self,
        count: int = 1,
        *,
        predicate: Callable[[dict[str, Any]], bool] | None = None,
        timeout: float = 300,
        interval: float = 5,
    ) -> list[dict[str, Any]]:
        """At least ``count`` uploads matching ``predicate`` (waiting.WaitTimeoutError otherwise)."""

        def matching() -> list[dict[str, Any]]:
            """The uploads accepted by the predicate."""
            return [entry for entry in self.uploads() if predicate is None or predicate(entry)]

        found: list[dict[str, Any]] = waiting.poll(
            matching,
            until=lambda entries: len(entries) >= count,
            timeout=timeout,
            interval=interval,
            what=f"{count} BOM upload(s) at the Dependency-Track mock",
            sleep=self.sleep,
            clock=self.clock,
        )
        return found


class WebappStack:
    """docker compose project ``otterdog-e2e-<run_id>``: webapp + mongodb + redis (+ dtrack-mock) on a private network."""

    def __init__(
        self,
        settings: WebappSettings,
        *,
        verified: VerifiedOrg | None,
        image: str,
        run_ctx: RunContext,
        scratch: Path,
        artifacts_dir: Path,
    ) -> None:
        """Bind the stack (nothing starts yet); ``verified`` may be None only for dummy (offline) credentials."""
        _check_settings(settings, verified, image)
        self.settings = settings
        self.verified = verified
        self.image = image
        self.run_ctx = run_ctx
        self.scratch = scratch
        self.artifacts_dir = artifacts_dir
        self.run_dir = scratch / "webapp"
        self.secrets_dir = self.run_dir / "secrets"
        self.key_file = self.secrets_dir / "github_app_key.pem"
        self.hypercorn_file = self.run_dir / "hypercorn-cfg.toml"
        self.compose_file = self.run_dir / COMPOSE_RESOURCE
        self.env_file = self.run_dir / "compose.env"  # empty: overrides COMPOSE_ENV_FILES / a stray .env
        self.override_file = self.run_dir / OVERRIDE_FILE
        self.dtrack_mock_file = self.run_dir / DTRACK_MOCK_RESOURCE
        self.secret_key = secrets.token_hex(32)
        self.init_at: datetime | None = None
        self.api = WebappApi(self.base_url)
        self._compose_used = False
        self._env_overrides: dict[str, str] = {}
        self._dtrack = settings.dtrack_mock
        self._dtrack_client: DtrackMock | None = None
        self._profiles_used: set[str] = {DTRACK_PROFILE} if settings.dtrack_mock else set()
        REDACTOR.add(self.secret_key, settings.app.webhook_secret, settings.config_token, settings.app.private_key_pem)

    @property
    def project_name(self) -> str:
        """Compose project name ``otterdog-e2e-<run_id>``."""
        return f"otterdog-e2e-{self.run_ctx.run_id}"

    @property
    def base_url(self) -> str:
        """http://127.0.0.1:<port>."""
        return f"http://127.0.0.1:{self.settings.port}"

    @property
    def webhook_path(self) -> str:
        """Path of the webhook receiver: GITHUB_WEBHOOK_ENDPOINT (an override of restart_webapp, else the default)."""
        return self._env_overrides.get("GITHUB_WEBHOOK_ENDPOINT", WEBHOOK_PATH)

    @property
    def webhook_url(self) -> str:
        """URL of the webhook receiver: <base_url>/github-webhook/receive (or the overridden endpoint)."""
        return f"{self.base_url}{self.webhook_path}"

    @property
    def env_overrides(self) -> dict[str, str]:
        """The webapp environment overrides in effect (restart_webapp)."""
        return dict(self._env_overrides)

    @property
    def dtrack_enabled(self) -> bool:
        """True when the Dependency-Track mock runs with the stack (profile ``dtrack``)."""
        return self._dtrack

    # --- files and environment -----------------------------------------------------------------------------------
    def compose_environment(self) -> dict[str, str]:
        """The COMPOSE_VARIABLES values. CONTAINS SECRETS: only for procs.run extra_env, never log or write it."""
        settings = self.settings
        return {
            "E2E_WEBAPP_IMAGE": self.image,
            "E2E_HYPERCORN_CFG": str(self.hypercorn_file),
            "E2E_GITHUB_APP_KEY_FILE": str(self.key_file),
            "E2E_BASE_URL": self.base_url,
            "E2E_CONFIG_OWNER": settings.org,
            "E2E_CONFIG_TOKEN": settings.config_token,
            "E2E_GITHUB_APP_ID": settings.app.app_id,
            "E2E_WEBHOOK_SECRET": settings.app.webhook_secret,
            "E2E_SECRET_KEY": self.secret_key,
            "E2E_WEBAPP_PORT": str(settings.port),
            "E2E_WEBAPP_PULL_POLICY": "never" if self.image.startswith(LOCAL_IMAGE_PREFIX) else "missing",
            "E2E_CONFIGS_REPO": settings.configs_repo,
            "E2E_VALIDATION_CONTEXT": settings.validation_context,
            "E2E_SYNC_CONTEXT": settings.sync_context,
            "E2E_ADMIN_TEAMS": settings.admin_team,
            "E2E_APPROVAL_TEAMS": f"^{settings.approval_team}$",
            "E2E_DEPENDENCY_TRACK_URL": DTRACK_INTERNAL_URL if self._dtrack else NO_DTRACK_URL,
            "E2E_DTRACK_MOCK_IMAGE": DTRACK_MOCK_IMAGE,
            "E2E_DTRACK_MOCK_STATUS": str(settings.dtrack_status),
            **{_override_variable(key): value for key, value in sorted(self._env_overrides.items())},
        }

    def write_files(self) -> None:
        """Write the compose file, an empty env file, hypercorn-cfg.toml, the Dependency-Track mock script and the App
        key (0600, dir 0700) to scratch."""
        for directory in (self.scratch, self.run_dir, self.secrets_dir):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        self.compose_file.write_text(read_resource(COMPOSE_RESOURCE), encoding="utf-8")
        self.env_file.write_text("", encoding="utf-8")
        self.hypercorn_file.write_text(self.render_hypercorn(), encoding="utf-8")
        self.hypercorn_file.chmod(0o644)  # read by the container user
        self.dtrack_mock_file.write_text(read_dtrack_mock(), encoding="utf-8")
        self.dtrack_mock_file.chmod(0o644)  # read by the mock's container user (nobody)
        self._write_override_file()
        fd = os.open(self.key_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as handle:
            handle.write(self.settings.app.private_key_pem)
        os.chmod(self.key_file, 0o600)

    def _write_override_file(self) -> None:
        """compose.override.yaml of the environment overrides (values are compose variables: nothing secret or not
        is written), removed when there is none."""
        if not self._env_overrides:
            self.override_file.unlink(missing_ok=True)
            return
        lines = ["# generated by otterdog-e2e (WebappStack.restart_webapp): webapp environment overrides", "services:"]
        lines += ["  webapp:", "    environment:"]
        lines += [
            f"      {key}: {json.dumps('${' + _override_variable(key) + '}')}" for key in sorted(self._env_overrides)
        ]
        self.override_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def render_hypercorn(self) -> str:
        """hypercorn-cfg.toml from resources/hypercorn.toml.j2 (bind 0.0.0.0:5000, workers, access log on stdout)."""
        environment = jinja2.Environment(undefined=jinja2.StrictUndefined, autoescape=False)  # noqa: S701 - TOML
        return environment.from_string(read_resource(HYPERCORN_RESOURCE)).render(workers=self.settings.workers)

    def compose_argv(self, *args: str, profiles: Sequence[str] | None = None) -> list[str]:
        """``docker compose`` argv bound to this project: explicit project name, directory, env file, the active
        profiles (default: the dtrack profile when enabled), the compose file and the override file when overrides are
        in effect."""
        active = sorted({DTRACK_PROFILE} if self._dtrack else set()) if profiles is None else list(profiles)
        argv = [
            "docker",
            "compose",
            "--project-name",
            self.project_name,
            "--project-directory",
            str(self.run_dir),
            "--env-file",
            str(self.env_file),
        ]
        for profile in active:
            argv += ["--profile", profile]
        argv += ["--file", str(self.compose_file)]
        if self._env_overrides:
            argv += ["--file", str(self.override_file)]
        return [*argv, *args]

    def _compose(
        self, *args: str, timeout: float, profiles: Sequence[str] | None = None
    ) -> procs.CompletedProcess[str]:
        """Run ``docker compose <args>`` with the compose variables in its environment (docker needs HOME)."""
        return procs.run(
            self.compose_argv(*args, profiles=profiles),
            cwd=self.run_dir,
            extra_env=self.compose_environment(),
            timeout=timeout,
            keep_home=True,
        )

    def _compose_checked(self, *args: str, timeout: float, what: str) -> procs.CompletedProcess[str]:
        """``_compose`` raising WebappStackError (redacted stderr and the log tail) on a non-zero exit."""
        result = self._compose(*args, timeout=timeout)
        if result.returncode != 0:
            raise WebappStackError(
                f"{what} failed (exit {result.returncode}): {REDACTOR(result.stderr)[-3000:]}"
                f"\n--- webapp log tail ---\n{self.logs(tail=LOG_TAIL)}"
            )
        return result

    # --- lifecycle ------------------------------------------------------------------------------------------------
    def up(self, *, timeout: float = 300) -> None:
        """Render hypercorn.toml and the key file into scratch, ``compose up -d --wait``; SECRET_KEY/secret redacted."""
        self.write_files()
        self._compose_used = True
        self._dtrack_client = None  # a new mock container gets a new port
        atexit.register(self._atexit_down)
        try:
            result = self._compose(
                "up", "--detach", "--wait", "--wait-timeout", str(max(int(timeout), 1)), timeout=timeout + 120
            )
            if result.returncode != 0:
                raise WebappStackError(
                    f"docker compose up failed (exit {result.returncode}): {REDACTOR(result.stderr)[-3000:]}"
                    f"\n--- webapp log tail ---\n{self.logs(tail=LOG_TAIL)}"
                )
            waiting.wait_until(self.health, timeout=HEALTH_TIMEOUT, interval=1.0, what="webapp /internal/health")
        except BaseException:
            self._save_logs_quietly()
            self.down()
            raise
        _logger.info("webapp stack %s up on %s (image %s)", self.project_name, self.base_url, self.image)

    def health(self) -> bool:
        """GET /internal/health == 200."""
        return self.api.health()

    # --- single services (fail-fast cases) ------------------------------------------------------------------------
    def _service(self, service: str) -> str:
        """``service`` when it is a service of the stack (ValueError otherwise; dtrack-mock needs the profile)."""
        if service not in SERVICES:
            raise ValueError(f"unknown compose service {service!r}, expected one of {SERVICES}")
        if service == DTRACK_SERVICE and not self._dtrack:
            raise ValueError(
                "the Dependency-Track mock is not enabled (WebappSettings.dtrack_mock, enable_dtrack_mock)"
            )
        if not self._compose_used:
            raise WebappStackError(f"the stack {self.project_name} is not up")
        return service

    def stop_service(self, service: str, *, timeout: float = SERVICE_TIMEOUT) -> None:
        """``docker compose stop <service>``: e.g. redis or mongodb for fail-fast cases (their data lives in memory:
        a restart starts them empty), the webapp for webapp-down cases."""
        self._compose_checked(
            "stop", "--timeout", "10", self._service(service), timeout=timeout, what=f"stopping {service}"
        )
        _logger.info("webapp stack %s: service %s stopped", self.project_name, service)

    def start_service(self, service: str, *, timeout: float = SERVICE_TIMEOUT) -> None:
        """Start a stopped service again and wait until it is healthy (``up --wait --no-deps --no-recreate``); the
        webapp is also waited for on /internal/health. After mongodb or redis, call init() and wait_ready()."""
        self._compose_checked(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            str(max(int(timeout), 1)),
            "--no-deps",
            "--no-recreate",
            self._service(service),
            timeout=timeout + 120,
            what=f"starting {service}",
        )
        if service == "webapp":
            waiting.wait_until(self.health, timeout=HEALTH_TIMEOUT, interval=1.0, what="webapp /internal/health")
        _logger.info("webapp stack %s: service %s started", self.project_name, service)

    def running_services(self) -> list[str]:
        """Names of the running services (``docker compose ps --services --status running``)."""
        result = self._compose_checked(
            "ps", "--services", "--status", "running", timeout=120, what="listing the running services"
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]

    def service_states(self) -> dict[str, tuple[str, int | None]]:
        """``{service: (state, exit code)}`` of every container of the stack, stopped and exited ones included
        (``docker compose ps --all``); the exit code is None while a service runs."""
        result = self._compose_checked(
            "ps",
            "--all",
            "--format",
            "{{.Service}}\t{{.State}}\t{{.ExitCode}}",
            timeout=120,
            what="listing the service states",
        )
        states: dict[str, tuple[str, int | None]] = {}
        for line in result.stdout.splitlines():
            parts = line.strip().split("\t")
            if len(parts) != 3 or not parts[0]:
                continue
            service, state, code = parts
            states[service] = (state, int(code) if state == "exited" and code.lstrip("-").isdigit() else None)
        return states

    def restart_webapp(self, env: Mapping[str, str] | None = None, *, timeout: float = SERVICE_TIMEOUT) -> None:
        """Recreate the webapp container with exactly ``env`` as environment overrides (None or {}: the defaults again)
        and wait until it is healthy; MongoDB and Redis keep their data. ``webhook_url`` follows an overridden
        GITHUB_WEBHOOK_ENDPOINT (re-point injectors and relays)."""
        overrides = check_env_overrides(env or {})
        if not self._compose_used:
            raise WebappStackError(f"the stack {self.project_name} is not up")
        previous = self._env_overrides
        self._env_overrides = overrides
        try:
            self._write_override_file()
            self._recreate(("webapp",), timeout=timeout, what="recreating the webapp")
        except BaseException:
            self._env_overrides = previous
            self._write_override_file()
            raise
        _logger.info("webapp stack %s: webapp recreated with overrides %s", self.project_name, sorted(overrides))

    def _recreate(self, services: Sequence[str], *, timeout: float, what: str) -> None:
        """``up --detach --wait --no-deps --force-recreate <services>`` and the webapp health check."""
        self._compose_checked(
            "up",
            "--detach",
            "--wait",
            "--wait-timeout",
            str(max(int(timeout), 1)),
            "--no-deps",
            "--force-recreate",
            *services,
            timeout=timeout + 120,
            what=what,
        )
        waiting.wait_until(self.health, timeout=HEALTH_TIMEOUT, interval=1.0, what="webapp /internal/health")

    # --- Dependency-Track mock ------------------------------------------------------------------------------------
    def enable_dtrack_mock(self, *, status: int = 200, timeout: float = SERVICE_TIMEOUT) -> DtrackMock:
        """Start the mock (profile ``dtrack``) and recreate the webapp with DEPENDENCY_TRACK_URL pointing to it, unless
        the stack already runs it; returns its client, set to answer uploads with ``status``."""
        if not self._dtrack:
            if not self._compose_used:
                raise WebappStackError(f"the stack {self.project_name} is not up")
            self._dtrack = True
            self._profiles_used.add(DTRACK_PROFILE)
            try:
                self._recreate((DTRACK_SERVICE, "webapp"), timeout=timeout, what="starting the Dependency-Track mock")
            except BaseException:
                self._dtrack = False
                raise
        client = self.dtrack()
        client.set_response(status)
        return client

    def dtrack(self) -> DtrackMock:
        """Client of the running mock (its 127.0.0.1 port from ``docker compose port``)."""
        if not self._dtrack:
            raise WebappStackError("the Dependency-Track mock is not enabled (WebappSettings.dtrack_mock)")
        if self._dtrack_client is None:
            result = self._compose_checked(
                "port", DTRACK_SERVICE, str(DTRACK_CONTAINER_PORT), timeout=60, what="reading the mock's port"
            )
            self._dtrack_client = DtrackMock(f"http://{parse_published_address(result.stdout)}")
        return self._dtrack_client

    def init(self) -> None:
        """GET /internal/init; raise with the webapp log tail unless 200."""
        self.init_at = datetime.now(UTC)
        try:
            self.api.init()
        except (WebappApiError, requests.RequestException) as exc:
            raise WebappStackError(
                f"GET /internal/init failed: {exc}\n--- webapp log tail ---\n{self.logs(tail=LOG_TAIL)}"
            ) from exc

    def wait_ready(self, *, timeout: float = 300) -> None:
        """/api/organizations lists github_id == org, /api/organizations/<org> is 200 and the newest FetchConfigTask
        of the org finished."""
        wait_webapp_ready(
            self.api,
            org=self.settings.org,
            timeout=timeout,
            after=self.init_at,
            log_tail=lambda: self.logs(tail=LOG_TAIL),
        )

    def deployed_version(self) -> str | None:
        """Version shown by GET /index (VERSION_RE), None when absent."""
        return self.api.deployed_version()

    def logs(self, *, tail: int | None = None) -> str:
        """Redacted ``docker compose logs`` of the project."""
        args = ["logs", "--no-color", "--timestamps"] + (["--tail", str(tail)] if tail is not None else [])
        try:
            result = self._compose(*args, timeout=120)
        except (OSError, procs.TimeoutExpired) as exc:
            return f"<docker compose logs unavailable: {type(exc).__name__}: {exc}>"
        text = result.stdout if result.returncode == 0 else f"{result.stdout}\n{result.stderr}"
        return REDACTOR(text)

    def save_logs(self) -> Path:
        """Write the redacted logs to artifacts_dir/webapp/ and return the file."""
        path = self.artifacts_dir / "webapp" / "compose.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.logs(), encoding="utf-8")
        return path

    def _save_logs_quietly(self) -> None:
        """save_logs() for failure paths: never raises."""
        if not self._compose_used:
            return
        try:
            self.save_logs()
        except OSError as exc:  # diagnostics must not hide the original failure
            _logger.warning("could not save webapp logs: %s", REDACTOR(str(exc)))

    def down(self) -> None:
        """``docker compose down -v --remove-orphans`` (every profile ever enabled) and remove the key file
        (idempotent)."""
        try:
            if self._compose_used:
                result = self._compose(
                    "down",
                    "--volumes",
                    "--remove-orphans",
                    "--timeout",
                    "10",
                    timeout=COMPOSE_DOWN_TIMEOUT,
                    profiles=sorted(self._profiles_used),
                )
                if result.returncode != 0:
                    _logger.warning("docker compose down failed: %s", REDACTOR(result.stderr)[-2000:])
                else:
                    self._compose_used = False
                    self._dtrack_client = None
        except (OSError, procs.TimeoutExpired) as exc:  # keep the atexit retry; never mask the caller's error
            _logger.warning("docker compose down failed: %s", REDACTOR(f"{type(exc).__name__}: {exc}"))
        finally:
            shutil.rmtree(self.secrets_dir, ignore_errors=True)
            if not self._compose_used:
                atexit.unregister(self._atexit_down)

    def _atexit_down(self) -> None:
        """Interpreter-exit safety net: tear the project down (errors are logged)."""
        try:
            self.down()
        except (RuntimeError, OSError) as exc:  # atexit handlers must not raise
            _logger.warning("webapp stack %s teardown failed: %s", self.project_name, REDACTOR(str(exc)))

    def __enter__(self) -> Self:
        """Start the stack."""
        self.up()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Save logs and stop the stack."""
        try:
            self.save_logs()
        finally:
            self.down()


def _override_variable(key: str) -> str:
    """Compose variable carrying the value of the webapp environment override ``key``: ``E2E_ENV_<key>``."""
    return f"{OVERRIDE_VARIABLE_PREFIX}{key}"


def parse_published_address(output: str) -> str:
    """``127.0.0.1:<port>`` from ``docker compose port`` output (WebappStackError for other addresses)."""
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    if not lines:
        raise WebappStackError("docker compose port printed nothing")
    host, _, port = lines[-1].rpartition(":")
    if host not in ("127.0.0.1", "localhost") or not port.isdigit():
        raise WebappStackError(f"the Dependency-Track mock is not published on 127.0.0.1: {lines[-1]!r}")
    return f"127.0.0.1:{int(port)}"


class ExternalWebapp:
    """A webapp the harness does not run (transport external): loopback only unless allow_remote."""

    def __init__(self, base_url: str, *, init_url: str | None, allow_remote: bool = False) -> None:
        """Bind the base URL (validated loopback unless allow_remote) and the optional init URL."""
        require_loopback_url(base_url, allow_remote=allow_remote, what="external webapp URL")
        if init_url:
            require_loopback_url(init_url, allow_remote=allow_remote, what="external webapp init URL")
        self.base_url = base_url.rstrip("/")
        self.init_url = init_url or None
        self.allow_remote = allow_remote
        self.init_at: datetime | None = None
        self._api = WebappApi(self.base_url)

    @property
    def api(self) -> WebappApi:
        """WebappApi on base_url."""
        return self._api

    def init(self) -> None:
        """GET init_url when configured."""
        if self.init_url is None:
            _logger.info("external webapp: no init URL configured, /internal/init not called")
            return
        self.init_at = datetime.now(UTC)
        try:
            response = local_session().get(self.init_url, timeout=180, allow_redirects=False)
        except requests.RequestException as exc:
            raise WebappStackError(f"GET {REDACTOR(self.init_url)} failed: {exc}") from exc
        if response.status_code != 200:
            raise WebappStackError(f"GET {REDACTOR(self.init_url)} -> HTTP {response.status_code}")

    def wait_ready(self, *, org: str, timeout: float = 300) -> None:
        """Same readiness rule as WebappStack.wait_ready."""
        wait_webapp_ready(self.api, org=org, timeout=timeout, after=self.init_at)

    def deployed_version(self) -> str | None:
        """Version shown by GET /index, None when absent."""
        return self.api.deployed_version()

    @property
    def webhook_url(self) -> str:
        """<base_url>/github-webhook/receive."""
        return f"{self.base_url}{WEBHOOK_PATH}"
