"""Running otterdog commands against a workspace and capturing their results (SPEC 11.2).

Each command runs in a fresh private dir ``scratch/cli/<seq>-<command>`` whose ``.cache/async_http`` is a symlink to
the per-SUT/identity HTTP cache (5.7; live caches stay in the run's scratch: they hold the token, see
http_cache_dir); redacted cmd/stdout/stderr/exit_code copies go to ``artifacts_dir/cli/``.
Live commands always use ``-n`` (no web UI) and never more than ``-v``.

Flags (verified against otterdog/cli.py): ``-c`` is a per-command option (``--version`` is a group option and rejects
it), ``list-projects`` takes no organization, ``plan``/``apply``/``import``/``check-status`` use ``-n`` = --no-web-ui
while ``push-config -n`` means --no-diff (not used: the diff/validation path of push-config is what users run, ``-f``
skips its prompts), ``open-pr`` requires ``-b -t -a`` and always prompts (stdin ``y``), ``check-status -j`` writes a
JSON list (nothing when the command fails early), ``fetch-config``/``import`` prompt before overwriting unless ``-f``.
The diff commands (``plan``, ``local-plan``, ``apply``, ``local-apply``) share ``-r/--repo-filter``,
``--update-webhooks``, ``--update-secrets``, ``--only-secrets`` and ``--update-filter`` (DiffOptions; ``plan_with``,
``local_plan_with``, ``apply_with``). ``invoke`` runs ``otterdog <args>`` exactly as given (no ``-c``, ``--local`` nor
organization: ``--help``, click usage errors, configuration discovery with OTTERDOG_CONFIG_ROOT).

Container runtimes (DockerRuntime) mount the workspace root at /ws and run in ``<workspace>/cwd``; their HTTP cache
lives in ``<workspace>/.http-cache`` (a relative symlink, valid inside and outside the container). Each docker command
runs as container ``otterdog-e2e-<run>-<seq>`` (``seq`` = the command number of its cwd/artifacts dir); when the
command times out or is interrupted (KeyboardInterrupt, SIGTERM, pytest-timeout) that container is removed with
``docker rm -f`` so an untrusted otterdog never keeps running behind the harness. Offline host runs are sandboxed
with ``unshare -rn`` when available (fail closed in CI otherwise).

Web mode (WebOtterdogCli, docs/web-ui-testing.md): ``plan``/``apply``/``import``/``check-status`` run WITHOUT ``-n``
and the commands that log in to github.com (WEB_LOGIN_COMMANDS) get the admin bot's username, password and TOTP seed
through the E2E_OTTERDOG_* credential variables, ``PLAYWRIGHT_BROWSERS_PATH=<E2E_CACHE_DIR>/ms-playwright``, and run
inside the LoginGate (one web login at a time, a full TOTP window apart). Only trusted SUTs on the host get a web
mode: the credentials never reach a container or an untrusted SUT. A recognized blocking login failure (wrong
password, lockout, login challenge, SSO) blocks the gate so later commands do not lock the bot out. Playwright dumps
(``web_*.html``/``.png``, written by otterdog into its cwd at -vv and more, which live commands never get) stay in
the private scratch dir and are never exported.
"""

from __future__ import annotations

import contextlib
import functools
import itertools
import json
import logging
import os
import re
import shlex
import shutil
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e import procs
from otterdog_e2e.otterdog.output import parse_apply, parse_plan, parse_validation, strip_ansi
from otterdog_e2e.otterdog.runtime import CONTAINER_WORKDIR, CWD_DIR, DockerRuntime, container_name, runtime_for
from otterdog_e2e.otterdog.workspace import (
    credentials_env,
    neutralize_untrusted_tree,
    read_untrusted_text,
    web_credentials_env,
    write_private_text,
)
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.observe import ObservationRecorder
    from otterdog_e2e.otterdog.output import ApplyResult, PlanResult, ValidationResult
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import HarnessSettings, Identity, WebCredentials
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.webui.gate import GateTicket, LoginGate

INFRA_ERROR_RE = re.compile(
    r"secondary rate limit|API rate limit exceeded|Cannot connect to host api.github.com", re.IGNORECASE
)
# commands that take no organization positional
NO_ORG_COMMANDS = frozenset({"--version", "list-projects"})
TAIL_LINES = 40
HTTP_CACHE_LINK = Path(".cache") / "async_http"
CONTAINER_HTTP_CACHE = ".http-cache"
CHECK_STATUS_FILE = "check-status.json"
ARTIFACT_FILES = ("cmd.txt", "stdout.txt", "stderr.txt", "exit_code.txt")
OFFLINE_IDENTITY = "offline"
TIMEOUT_EXIT_CODE = -1
_VERBOSE_RE = re.compile(r"^-(v+)$")
# web mode: commands that log in to github.com without -n, and commands that only do so with one of their flags
WEB_LOGIN_COMMANDS = frozenset(
    {"plan", "apply", "import", "show-live", "check-status", "install-app", "uninstall-app", "review-permissions"}
    | {"web-login"}
)
WEB_FLAG_COMMANDS: Mapping[str, tuple[str, ...]] = {"list-advisories": ("-w", "--use-web")}
NO_WEB_UI_FLAGS = ("-n", "--no-web-ui")
PLAYWRIGHT_BROWSERS_ENV = "PLAYWRIGHT_BROWSERS_PATH"
WEB_DUMP_GLOB = "web_*"  # otterdog's Playwright page dumps (html + png), written into its cwd
WEB_TIMEOUT = 1800.0  # web commands: browser start, page loads, up to two logins (apply)
CONFIG_ROOT_ENV = "OTTERDOG_CONFIG_ROOT"  # where otterdog looks for otterdog.jsonnet / otterdog.json without -c
INVOKE_NAME = "otterdog"  # cwd/artifacts name of ``invoke()`` without arguments
ENV_NAME_RE = re.compile(r"^[A-Z_][A-Z0-9_]*$")  # variables invoke(env=...) may add (offline only)

log = logging.getLogger(__name__)

_sequence = itertools.count(1)
_sequence_lock = threading.Lock()


def _next_sequence() -> int:
    """Process-wide command number (several OtterdogCli instances share one scratch and artifacts dir)."""
    with _sequence_lock:
        return next(_sequence)


@functools.lru_cache(maxsize=1)
def _unshare_available() -> bool:
    """Cached procs.unshare_available()."""
    return procs.unshare_available()


def _slug(value: str) -> str:
    """File-name friendly form of a command or label."""
    return re.sub(r"[^\w.-]+", "_", value.lstrip("-")) or "cmd"


def _decode(value: str | bytes | None) -> str:
    """Text of partial subprocess output (TimeoutExpired carries bytes or str)."""
    if value is None:
        return ""
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value


def _verbosity(args: Sequence[str]) -> int:
    """Number of ``-v`` given in ``args`` (``-vv`` counts 2, ``--verbose`` 1)."""
    count = 0
    for arg in args:
        match = _VERBOSE_RE.match(arg)
        count += len(match.group(1)) if match else int(arg == "--verbose")
    return count


def infra_error_line(text: str) -> str | None:
    """The (redacted) line of ``text`` reporting a GitHub rate limit or connection failure, None when absent."""
    for line in strip_ansi(text).splitlines():
        if INFRA_ERROR_RE.search(line):
            return REDACTOR(re.sub(r"\s+", " ", line.strip(" \t│╷╵")))
    return None


@dataclass
class CliResult:
    """Outcome of one otterdog invocation."""

    argv: list[str]
    exit_code: int
    stdout: str
    stderr: str
    duration: float
    cwd: Path
    timed_out: bool = False
    infra_error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def output(self) -> str:
        """stdout followed by stderr (when not empty)."""
        if not self.stderr:
            return self.stdout
        if not self.stdout:
            return self.stderr
        separator = "" if self.stdout.endswith("\n") else "\n"
        return f"{self.stdout}{separator}{self.stderr}"

    def plan(self) -> PlanResult:
        """Parse the output as plan/local-plan output."""
        return parse_plan(self.output)

    def apply(self) -> ApplyResult:
        """Parse the output as apply output."""
        return parse_apply(self.output)

    def validation(self) -> ValidationResult:
        """Parse the output as validate output."""
        return parse_validation(self.output)

    def assert_ok(self, what: str = "") -> CliResult:
        """Return self when the command exited 0 in time without infra error, else AssertionError with a redacted tail."""
        if self.exit_code == 0 and not self.timed_out and self.infra_error is None:
            return self
        tail = "\n".join(self.output.splitlines()[-TAIL_LINES:])
        reason = "timed out" if self.timed_out else f"exit code {self.exit_code}"
        if self.infra_error:
            reason += f", infra error: {self.infra_error}"
        label = what or " ".join(self.argv[1:3])
        raise AssertionError(REDACTOR(f"otterdog {label} failed ({reason}):\n{tail}"))


@dataclass(frozen=True)
class DiffOptions:
    """Options shared by otterdog's diff commands (plan, local-plan, apply, local-apply; otterdog/cli.py @9bdeb75).

    * ``repo_filter``: ``-r/--repo-filter``, a shell pattern of the repositories included (otterdog's default ``*``;
      organization-level objects are never filtered);
    * ``update_webhooks`` / ``update_secrets``: ``--update-webhooks`` / ``--update-secrets``, forced ('!') updates of
      webhooks with a secret / of secrets regardless of changes (values are never compared otherwise);
    * ``only_secrets``: ``--only-secrets``, only secret changes are planned or applied;
    * ``update_filter``: ``--update-filter``, a shell pattern of the webhook urls / secret names a forced update
      includes (default ``*``; it selects nothing without update_webhooks or update_secrets);
    * ``verbose``: ``-v`` (Info messages are printed; never more than one ``-v``).
    """

    repo_filter: str | None = None
    update_webhooks: bool = False
    update_secrets: bool = False
    only_secrets: bool = False
    update_filter: str | None = None
    verbose: bool = False

    def __post_init__(self) -> None:
        """Patterns are non-empty strings (argv elements, never a shell)."""
        for name in ("repo_filter", "update_filter"):
            value = getattr(self, name)
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError(f"DiffOptions.{name} must be a non-empty pattern, got {value!r}")

    def repo_args(self) -> list[str]:
        """``-r <repo_filter>`` (empty without a filter)."""
        return ["-r", self.repo_filter] if self.repo_filter else []

    def flag_args(self) -> list[str]:
        """``--update-secrets``, ``--update-webhooks``, ``--only-secrets``, ``--update-filter <p>``, ``-v`` (in this
        order, the ones that are set)."""
        flags = [
            flag
            for flag, on in (
                ("--update-secrets", self.update_secrets),
                ("--update-webhooks", self.update_webhooks),
                ("--only-secrets", self.only_secrets),
            )
            if on
        ]
        if self.update_filter:
            flags += ["--update-filter", self.update_filter]
        return flags + (["-v"] if self.verbose else [])

    def args(self) -> list[str]:
        """repo_args() then flag_args()."""
        return [*self.repo_args(), *self.flag_args()]


@dataclass(frozen=True)
class WebMode:
    """What a web-mode CLI needs: the bot's web credentials, the login gate and the Playwright browsers dir."""

    credentials: WebCredentials
    gate: LoginGate
    browsers_path: Path


def check_web_runtime(installed: InstalledCli, identity: Identity | None, credentials: WebCredentials) -> None:
    """SafetyError unless web credentials may reach this CLI: a host install of a trusted SUT, run as the identity
    (the admin) whose machine account the web login belongs to."""
    if installed.runtime != "host":
        raise SafetyError(f"web-UI credentials never reach container runtimes ({installed.sut.label} runs in docker)")
    if not installed.sut.trusted:
        raise SafetyError(f"web-UI credentials never reach untrusted SUTs ({installed.sut.label})")
    if identity is None or identity.name != credentials.identity:
        raise SafetyError(f"the web mode runs as the {credentials.identity} identity (its token and its web login)")
    if not identity.login or identity.login.lower() != credentials.login.lower():
        raise SafetyError(
            f"the web login {credentials.login!r} is not the account of the {identity.name} token ({identity.login!r})"
        )


class OtterdogCli:
    """Drives one installed otterdog CLI against one workspace (verified None only when offline)."""

    def __init__(
        self,
        installed: InstalledCli,
        workspace: ConfigWorkspace,
        *,
        verified: VerifiedOrg | None,
        identity: Identity | None,
        scratch: Path,
        artifacts_dir: Path,
        settings: HarnessSettings,
        recorder: ObservationRecorder | None = None,
        timeout: float = 900,
        offline: bool = False,
        http_cache: bool = True,
        http_cache_root: Path | None = None,
    ) -> None:
        """Bind the CLI; identity None means the offline dummy token; ``http_cache_root``: the run's private directory
        of live HTTP caches (default ``scratch/http-cache``)."""
        if verified is None and not offline:
            raise SafetyError("a live OtterdogCli requires a VerifiedOrg (verified=None is only allowed offline)")
        if verified is not None and workspace.org != verified.login:
            raise SafetyError(f"workspace org {workspace.org!r} is not the verified org {verified.login!r}")
        self.installed = installed
        self.workspace = workspace
        self.verified = verified
        self.identity = identity
        self.scratch = scratch
        self.artifacts_dir = artifacts_dir
        self.settings = settings
        self.recorder = recorder
        self.timeout = timeout
        self.offline = offline
        self.http_cache = http_cache
        self.http_cache_root = http_cache_root
        self.runtime = runtime_for(installed, offline=offline)
        self._web: WebMode | None = None  # set by WebOtterdogCli only
        # precondition of every live command (E2EContext.check_lease_not_lost: refused once the org lease was lost)
        self.live_check: Callable[[], None] | None = None
        if identity is not None:
            REDACTOR.add(identity.token)

    @property
    def web(self) -> WebMode | None:
        """The web mode (WebOtterdogCli), None for ordinary CLIs (live commands always use -n)."""
        return self._web

    def _no_web_ui(self) -> list[str]:
        """``-n`` (--no-web-ui) unless the CLI is in web mode."""
        return [] if self._web is not None else ["-n"]

    def _logs_in(self, logical: Sequence[str]) -> bool:
        """True when the command logs in to the GitHub web UI (web mode, WEB_LOGIN_COMMANDS without -n)."""
        if self._web is None or not logical:
            return False
        command, args = logical[0], logical[1:]
        if command in WEB_FLAG_COMMANDS:
            return any(flag in args for flag in WEB_FLAG_COMMANDS[command])
        return command in WEB_LOGIN_COMMANDS and not any(flag in args for flag in NO_WEB_UI_FLAGS)

    # --- generic command ------------------------------------------------------------------------------------------
    def run(
        self,
        command: str,
        *args: str,
        org: bool = True,
        input: str | None = None,
        timeout: float | None = None,
        local: bool = False,
        observe: str | None = None,
    ) -> CliResult:
        """Run ``otterdog <command> -c <config> [args] [--local] [<org>]`` in a fresh cwd and record the result.

        ``-c`` is passed for every command except ``--version``; the org positional when ``org`` and the command takes
        one; infra_error is set when the output matches INFRA_ERROR_RE; ``observe`` records RAW stdout with
        meta {"exit_code"} under that key.
        """
        _, result = self._run_named(command, args, org=org, input=input, timeout=timeout, local=local)
        self._record(observe, result)
        return result

    def invoke(
        self,
        *args: str,
        input: str | None = None,
        timeout: float | None = None,
        config_root: bool = False,
        env: Mapping[str, str] | None = None,
        observe: str | None = None,
    ) -> CliResult:
        """Run ``otterdog <args>`` exactly as given: no ``-c``, ``--local`` nor organization positional (``--help``,
        ``otterdog`` alone, click usage errors such as ``open-pr`` without ``-a``, configuration discovery).

        The command runs in a fresh, empty cwd like every other one, so without ``-c`` otterdog finds no
        configuration there; ``config_root`` sets OTTERDOG_CONFIG_ROOT (stripped from every other command) to the
        workspace root (``/ws`` in a container), where otterdog then looks for otterdog.jsonnet, then otterdog.json.
        ``env`` (offline CLIs only: SafetyError otherwise) adds variables, e.g. the dummy token of a custom credential
        variable name or a PATH with stub provider binaries; names match ``[A-Z_][A-Z0-9_]*`` and are noted in
        cmd.txt (redacted). Credentials, the sandbox, the live ``-v`` limit and the artifacts are those of run().
        """
        logical = [str(arg) for arg in args]
        extra = {CONFIG_ROOT_ENV: self._config_root()} if config_root else {}
        if env:
            if not self.offline:
                raise SafetyError("invoke(env=...) is offline only: live commands get the identity's credentials only")
            bad = sorted(key for key in env if not isinstance(key, str) or not ENV_NAME_RE.match(key))
            if bad or not all(isinstance(value, str) for value in env.values()):
                raise ValueError(
                    f"invoke(env=...): names must match {ENV_NAME_RE.pattern} and values be strings: {bad}"
                )
            extra.update(env)
        label = logical[0] if logical else INVOKE_NAME
        _, result = self._run_logical(label, logical, input=input, timeout=timeout, extra_env=extra)
        self._record(observe, result)
        return result

    def _config_root(self) -> str:
        """OTTERDOG_CONFIG_ROOT of ``invoke(config_root=True)``: the workspace root as the CLI sees it."""
        return CONTAINER_WORKDIR if self._in_container else str(self.workspace.root.resolve())

    def _record(self, observe: str | None, result: CliResult) -> None:
        """Record the RAW stdout with meta {"exit_code"} under ``observe`` (when given and a recorder is bound)."""
        if observe is not None and self.recorder is not None:
            self.recorder.record("cli", observe, result.stdout, meta={"exit_code": result.exit_code})

    def _run_named(
        self,
        command: str,
        args: Sequence[str],
        *,
        org: bool = True,
        input: str | None = None,
        timeout: float | None = None,
        local: bool = False,
    ) -> tuple[str, CliResult]:
        """Run one command; returns its sequence name (cwd/artifacts dir name) and result."""
        logical = self._arguments(command, args, org=org, local=local)
        return self._run_logical(command, logical, input=input, timeout=timeout)

    def _run_logical(
        self,
        label: str,
        logical: list[str],
        *,
        input: str | None = None,
        timeout: float | None = None,
        extra_env: Mapping[str, str] | None = None,
    ) -> tuple[str, CliResult]:
        """Run otterdog with the logical argv ``logical`` in a fresh cwd named after ``label``; returns the sequence
        name (cwd/artifacts dir name) and the result."""
        if not self.offline and _verbosity(logical) > 1:
            raise SafetyError("live otterdog commands never get more than -v (higher levels trace secrets)")
        if not self.offline and self.live_check is not None:
            self.live_check()  # E2EContext: refused once the session's org lease was lost (DESTR-03)
        seq = _next_sequence()
        name = f"{seq:04d}-{_slug(label)}"
        cwd = self._fresh_cwd(name)
        limit = self.timeout if timeout is None else timeout
        try:
            result, process = self._execute(
                name, logical, cwd, input=input, timeout=limit, seq=seq, extra_env=extra_env
            )
        except BaseException:
            try:  # the interruption or error in flight wins; the mount is still neutralized when possible
                self._neutralize_mount()
            except Exception as exc:  # noqa: BLE001 - logged, the original exception propagates
                log.error("could not neutralize the mounted workspace: %s", exc)
            raise
        removed = self._neutralize_mount()
        if removed:
            result.notes.append(
                f"untrusted workspace: removed {len(removed)} planted link(s): {', '.join(removed[:20])}"
            )
        self._export(name, result, process)
        return name, result

    def _neutralize_mount(self) -> list[str]:
        """After a container command: remove the links leading out of the mounted workspace and the special files
        the container left there (workspace.neutralize_untrusted_tree, ISO-01); no-op for host runtimes."""
        if not self._in_container:
            return []
        removed = neutralize_untrusted_tree(self._workdir)
        if removed:
            log.warning("removed %d link(s)/special file(s) planted in %s: %s", len(removed), self._workdir, removed)
        return removed

    def _arguments(self, command: str, args: Sequence[str], *, org: bool, local: bool) -> list[str]:
        """otterdog arguments (host paths): command, -c, args, --local, org."""
        if command == "--version":
            return ["--version"]
        arguments = [command, "-c", str(self.workspace.config_file.resolve()), *map(str, args)]
        if local:
            arguments.append("--local")
        if org and command not in NO_ORG_COMMANDS:
            arguments.append(self.workspace.org)
        return arguments

    @property
    def _in_container(self) -> bool:
        """True when the runtime runs otterdog inside a container (mounted workspace layout)."""
        return bool(getattr(self.runtime, "in_container", False))

    @property
    def _workdir(self) -> Path:
        """Directory mounted into container runtimes: the workspace root."""
        return self.workspace.root.resolve()

    def _fresh_cwd(self, name: str) -> Path:
        """Create the empty working directory of one command (with the HTTP cache link) and return it."""
        if self._in_container:
            cwd = self._workdir / CWD_DIR
        else:
            (self.scratch / "cli").mkdir(mode=0o700, parents=True, exist_ok=True)
            cwd = self.scratch / "cli" / name
        if cwd.is_symlink() or cwd.is_file():
            cwd.unlink()
        elif cwd.exists():
            shutil.rmtree(cwd)
        cwd.mkdir(mode=0o700, parents=True)
        if self.http_cache:
            self._link_http_cache(cwd)
        return cwd

    def _identity_name(self) -> str:
        """Identity part of the HTTP cache name."""
        return self.identity.name if self.identity is not None else OFFLINE_IDENTITY

    def http_cache_dir(self) -> Path:
        """HTTP cache of this SUT and identity: in the workspace (container); shared across runs only for offline
        trusted host commands (dummy token); else in the run's private scratch (``http_cache_root``), deleted at session
        end: otterdog's cache pickles the request headers, the live token's Authorization header included (ISO-04)."""
        name = _slug(f"{self.installed.sut.label}-{self._identity_name()}")
        if self._in_container:
            return self._workdir / CONTAINER_HTTP_CACHE / name
        if self.offline and self.installed.sut.trusted:
            return self.settings.cache_dir / "http-cache" / name
        return (self.http_cache_root or self.scratch / "http-cache") / name

    def _link_http_cache(self, cwd: Path) -> None:
        """Make ``cwd/.cache/async_http`` a symlink to the HTTP cache dir (relative inside container workdirs)."""
        target = self.http_cache_dir()
        target.mkdir(mode=0o700, parents=True, exist_ok=True)
        link = cwd / HTTP_CACHE_LINK
        link.parent.mkdir(mode=0o700, exist_ok=True)
        link.symlink_to(os.path.relpath(target, link.parent) if self._in_container else target)

    def _sandbox(self) -> list[str]:
        """``unshare -rn`` prefix for offline host commands (SafetyError in CI when no sandbox is available)."""
        if not self.offline or self._in_container:
            return []
        if _unshare_available():
            return ["unshare", "-rn"]
        if os.environ.get("CI"):
            raise SafetyError("offline otterdog commands need a network sandbox (unshare -rn), unavailable in CI")
        log.warning("unshare -rn is unavailable: offline otterdog commands run without a network sandbox")
        return []

    def _write_env_file(self, name: str, credentials: Mapping[str, str]) -> Path:
        """0600 docker env-file with ONLY the E2E_OTTERDOG_* credentials (outside the mounted workdir), plus
        OTTERDOG_CONFIG_ROOT for ``invoke(config_root=True)``."""
        directory = self.scratch / "env"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = directory / f"{name}.env"
        path.unlink(missing_ok=True)
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.writelines(f"{key}={value}\n" for key, value in credentials.items())
        return path

    def _container(self, seq: int) -> str | None:
        """Container name of command ``seq`` for a docker runtime (None for host and stand-in runtimes)."""
        return container_name(seq) if isinstance(self.runtime, DockerRuntime) else None

    def _command(self, logical: list[str], env_file: Path | None, container: str | None) -> list[str]:
        """Process argv: sandbox prefix + the runtime's argv (docker runtimes get the container name)."""
        runtime = self.runtime
        if container is not None and isinstance(runtime, DockerRuntime):
            argv = runtime.command(logical, workdir=self._workdir, env_file=env_file, name=container)
        else:
            argv = runtime.command(logical, workdir=self._workdir, env_file=env_file)
        return self._sandbox() + argv

    def _remove_container(self, container: str | None) -> None:
        """``docker rm -f`` the container of a timed-out or interrupted command (never raises)."""
        if container is None or not isinstance(self.runtime, DockerRuntime):
            return
        try:
            self.runtime.remove(container)
        except Exception as exc:  # noqa: BLE001 - cleanup must not hide the timeout/interruption being handled
            log.error("could not remove container %s: %s", container, exc)

    def _execute(
        self,
        name: str,
        logical: list[str],
        cwd: Path,
        *,
        input: str | None,
        timeout: float,
        seq: int,
        extra_env: Mapping[str, str] | None = None,
    ) -> tuple[CliResult, list[str]]:
        """Run the command through the runtime and procs.run (timeouts become timed_out results); result and argv.

        ``extra_env`` (non-secret variables such as OTTERDOG_CONFIG_ROOT) reaches the process environment on the host
        and the env-file in a container. The container of a docker command is removed when it times out or is
        interrupted (KeyboardInterrupt, SystemExit, pytest-timeout's Failed: every BaseException that is not an
        Exception), then the interruption propagates; ordinary errors (e.g. no docker binary) never started a container.
        """
        web = self._logs_in(logical)
        if web and (self._in_container or self.offline):
            raise SafetyError("web-UI credentials never reach container runtimes or offline commands")
        credentials = self._credentials(web)
        extra = dict(extra_env or {})
        env_file = self._write_env_file(name, {**credentials, **extra}) if self._in_container else None
        container = self._container(seq)
        notes: list[str] = [f"env: {key}={value}" for key, value in extra.items()]
        started = time.monotonic()
        try:
            with self._login_gate(logical[0] if web else None, notes):
                started = time.monotonic()
                argv = self._command(logical, env_file, container)
                host_extra = {} if self._in_container else extra
                completed = procs.run(
                    argv,
                    cwd=cwd,
                    extra_env={**self.runtime.env(credentials), **self._web_env(web), **host_extra},
                    timeout=timeout,
                    input=input,
                    keep_home=self._in_container,
                    home=None if self._in_container else self.scratch / "home",
                )
            exit_code, stdout, stderr, timed_out = completed.returncode, completed.stdout, completed.stderr, False
        except procs.TimeoutExpired as exc:
            self._remove_container(container)
            exit_code, stdout, stderr, timed_out = TIMEOUT_EXIT_CODE, _decode(exc.stdout), _decode(exc.stderr), True
        except BaseException as exc:
            if not isinstance(exc, Exception):
                self._remove_container(container)
            raise
        finally:
            if env_file is not None:
                env_file.unlink(missing_ok=True)
        duration = time.monotonic() - started
        infra = infra_error_line(stdout + "\n" + stderr)
        result = CliResult(["otterdog", *logical], exit_code, stdout, stderr, duration, cwd, timed_out, infra, notes)
        if web:
            self._after_web_command(result)
        return result, argv

    def _credentials(self, web: bool) -> dict[str, str]:
        """E2E_OTTERDOG_* values: the identity's token, plus the web login for web commands ("unset" otherwise)."""
        if web and self._web is not None:
            return web_credentials_env(self.identity, self._web.credentials)
        return credentials_env(self.identity)

    def _web_env(self, web: bool) -> dict[str, str]:
        """PLAYWRIGHT_BROWSERS_PATH for web commands (the browsers installed by cli_install.ensure_playwright_firefox)."""
        if not web or self._web is None:
            return {}
        return {PLAYWRIGHT_BROWSERS_ENV: str(self._web.browsers_path)}

    @contextlib.contextmanager
    def _login_gate(self, what: str | None, notes: list[str]) -> Iterator[GateTicket | None]:
        """The LoginGate session of a web command (no-op for other commands); its wait is noted in cmd.txt."""
        if what is None or self._web is None:
            yield None
            return
        with self._web.gate.session(what) as ticket:
            notes.append(
                f"web_ui: login gate admitted {what} after {ticket.waited:.1f} s (login #{ticket.login_number})"
            )
            yield ticket

    def _after_web_command(self, result: CliResult) -> None:
        """Block the gate on a blocking login failure; note Playwright dumps (kept in scratch, never exported)."""
        from otterdog_e2e.webui.gate import classify_web_failure

        assert self._web is not None
        failure = classify_web_failure(result.output)
        if failure is not None:
            result.notes.append(f"web_ui: {failure.kind} failure: {failure.hint}")
            # otterdog exits non-zero on every login failure: a diff that merely quotes such a text never blocks
            if failure.blocking and (result.exit_code != 0 or result.timed_out):
                self._web.gate.block(f"{failure.kind}: {failure.hint}", duration=failure.block_seconds)
        dumps = sorted(path.name for path in result.cwd.glob(WEB_DUMP_GLOB))
        if dumps:
            log.warning("otterdog left %d web page dump(s) in %s (scratch only)", len(dumps), result.cwd)
            result.notes.append(f"web_ui: {len(dumps)} page dump(s) kept in the scratch cwd (never exported)")

    def _export(self, name: str, result: CliResult, process: Sequence[str]) -> None:
        """Write the redacted cmd/stdout/stderr/exit_code copies to artifacts_dir/cli/<name>/."""
        directory = self.artifacts_dir / "cli" / name
        directory.mkdir(parents=True, exist_ok=True)
        command = "\n".join(
            [
                shlex.join(result.argv),
                f"# process: {shlex.join(process)}",
                f"# runtime: {self.runtime.label}",
                f"# cwd: {result.cwd}",
                f"# duration: {result.duration:.3f} s",
                f"# timed_out: {str(result.timed_out).lower()}",
                f"# infra_error: {result.infra_error or 'none'}",
                *(f"# {note}" for note in result.notes),
            ]
        )
        texts = {"cmd.txt": command + "\n", "stdout.txt": result.stdout, "stderr.txt": result.stderr}
        texts["exit_code.txt"] = f"{result.exit_code}\n"
        for file_name, text in texts.items():
            (directory / file_name).write_text(REDACTOR(text), encoding="utf-8")

    # --- commands ---------------------------------------------------------------------------------------------------
    def version(self) -> str:
        """Output of exactly ``[otterdog, "--version"]``."""
        return self.run("--version", org=False).assert_ok("--version").stdout.strip()

    def validate(self, *, local: bool = False, verbose: bool = False, observe: str | None = None) -> CliResult:
        """``validate`` (``-v`` when verbose)."""
        return self.run("validate", *(["-v"] if verbose else []), local=local, observe=observe)

    def plan(self, *, repo_filter: str | None = None, local: bool = False, observe: str | None = None) -> CliResult:
        """``plan -n [-r <filter>]`` (no ``-n`` in web mode)."""
        return self.plan_with(DiffOptions(repo_filter=repo_filter), local=local, observe=observe)

    def plan_with(self, options: DiffOptions, *, local: bool = False, observe: str | None = None) -> CliResult:
        """``plan -n [-r <filter>] [--update-secrets] [--update-webhooks] [--only-secrets] [--update-filter <p>] [-v]``
        (DiffOptions; no ``-n`` in web mode)."""
        return self.run("plan", *self._no_web_ui(), *options.args(), local=local, observe=observe)

    def apply(
        self,
        *,
        repo_filter: str | None = None,
        delete: bool = False,
        update_secrets: bool = False,
        update_webhooks: bool = False,
        local: bool = False,
        observe: str | None = None,
    ) -> CliResult:
        """``apply -f -n [-r <filter>] [-d] [--update-secrets] [--update-webhooks]`` (no ``-n`` in web mode)."""
        options = DiffOptions(repo_filter=repo_filter, update_secrets=update_secrets, update_webhooks=update_webhooks)
        return self.apply_with(options, delete=delete, local=local, observe=observe)

    def apply_with(
        self, options: DiffOptions, *, delete: bool = False, local: bool = False, observe: str | None = None
    ) -> CliResult:
        """``apply -f -n [-r <filter>] [-d] [--update-secrets] [--update-webhooks] [--only-secrets]
        [--update-filter <p>] [-v]`` (DiffOptions; no ``-n`` in web mode)."""
        args = ["-f", *self._no_web_ui(), *options.repo_args(), *(["-d"] if delete else []), *options.flag_args()]
        return self.run("apply", *args, local=local, observe=observe)

    def local_plan(self, *, suffix: str = "-BASE", local: bool = True, observe: str | None = None) -> CliResult:
        """``local-plan -s <suffix>`` (compares the org config with the ``<suffix>`` file)."""
        return self.local_plan_with(DiffOptions(), suffix=suffix, local=local, observe=observe)

    def local_plan_with(
        self, options: DiffOptions, *, suffix: str = "-BASE", local: bool = True, observe: str | None = None
    ) -> CliResult:
        """``local-plan -s <suffix> [-r <filter>] [--update-secrets] [--update-webhooks] [--only-secrets]
        [--update-filter <p>] [-v]`` (DiffOptions; local-plan has no ``-n``)."""
        return self.run("local-plan", "-s", suffix, *options.args(), local=local, observe=observe)

    def import_config(self, *, force: bool = True) -> CliResult:
        """``import -f -n`` (no ``-n`` in web mode)."""
        return self.run("import", *(["-f"] if force else []), *self._no_web_ui())

    def push_config(self, *, message: str) -> CliResult:
        """``push-config -m <message>`` (``-n`` = --no-diff for push-config; HOME isolated by procs).

        Runs ``push-config -f -m <message>``: ``-f`` skips the prompts; the diff against the config repo (which
        overwrites ``<org>.jsonnet-BASE`` and validates the config) is kept, so invalid configs are not pushed.
        """
        return self.run("push-config", "-f", "-m", message)

    def fetch_config(self, *, ref: str | None = None, pull_request: int | None = None) -> CliResult:
        """``fetch-config -f [-r <ref>] [-p <pull request>]``."""
        args = ["-f", *(["-r", ref] if ref else []), *(["-p", str(pull_request)] if pull_request is not None else [])]
        return self.run("fetch-config", *args)

    def open_pr(self, *, branch: str, title: str, author: str) -> CliResult:
        """``open-pr -b <branch> -t <title> -a <author> <org>`` with stdin "y\\n" (ref otterdog/<branch>)."""
        return self.run("open-pr", "-b", branch, "-t", title, "-a", author, input="y\n")

    def check_status(self, json_file: Path) -> tuple[CliResult, dict | None]:
        """``check-status -n -j <file>`` (no ``-n`` in web mode); returns the result and the list entry of workspace.org
        (None if missing).

        otterdog writes the file relative to its cwd (so container runtimes can write it); it is then read as a regular
        file of the cwd without following links (workspace.read_untrusted_text: an untrusted SUT may plant a link to a
        host file there), written to ``json_file`` (a planted link there is replaced, never followed) and, redacted,
        next to the command's artifacts.
        """
        name, result = self._run_named("check-status", [*self._no_web_ui(), "-j", CHECK_STATUS_FILE])
        # the file may come from an untrusted container: never follow a link, neither to read it nor to copy it
        text = read_untrusted_text(result.cwd / CHECK_STATUS_FILE, within=result.cwd)
        if text is None:
            return result, None
        if json_file.absolute() != (result.cwd / CHECK_STATUS_FILE).absolute():
            write_private_text(json_file, text)
        (self.artifacts_dir / "cli" / name / CHECK_STATUS_FILE).write_text(REDACTOR(text), encoding="utf-8")
        return result, self._status_entry(text)

    def _status_entry(self, text: str) -> dict[str, Any] | None:
        """Entry of workspace.org in a check-status JSON list (org_id compared case-insensitively)."""
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            log.warning("check-status wrote invalid JSON")
            return None
        entries = data if isinstance(data, list) else [data]
        org = self.workspace.org.lower()
        return next((e for e in entries if isinstance(e, dict) and str(e.get("org_id", "")).lower() == org), None)

    def show(self, *, local: bool = True) -> CliResult:
        """``show``."""
        return self.run("show", local=local)

    def show_default(self, *, local: bool = True) -> CliResult:
        """``show-default``."""
        return self.run("show-default", local=local)

    def canonical_diff(self, *, local: bool = True) -> CliResult:
        """``canonical-diff``."""
        return self.run("canonical-diff", local=local)

    def list_projects(self) -> CliResult:
        """``list-projects`` (no positional)."""
        return self.run("list-projects", org=False)

    def list_members(self) -> CliResult:
        """``list-members``."""
        return self.run("list-members")

    def check_token_permissions(self) -> CliResult:
        """``check-token-permissions``."""
        return self.run("check-token-permissions")


class WebOtterdogCli(OtterdogCli):
    """OtterdogCli in web mode (docs/web-ui-testing.md): plan/apply/import/check-status without ``-n``, the bot's web
    login for the commands of WEB_LOGIN_COMMANDS, each of them admitted by the LoginGate; plus the UI-driven commands.

    Refused (SafetyError) for container runtimes, untrusted SUTs and identities other than the web credentials' one.
    """

    def __init__(
        self,
        installed: InstalledCli,
        workspace: ConfigWorkspace,
        *,
        verified: VerifiedOrg,
        identity: Identity,
        web: WebMode,
        scratch: Path,
        artifacts_dir: Path,
        settings: HarnessSettings,
        recorder: ObservationRecorder | None = None,
        timeout: float = WEB_TIMEOUT,
        http_cache: bool = True,
        http_cache_root: Path | None = None,
    ) -> None:
        """Bind a trusted host CLI to the web mode (never offline: the web UI is github.com)."""
        check_web_runtime(installed, identity, web.credentials)
        super().__init__(
            installed,
            workspace,
            verified=verified,
            identity=identity,
            scratch=scratch,
            artifacts_dir=artifacts_dir,
            settings=settings,
            recorder=recorder,
            timeout=timeout,
            offline=False,
            http_cache=http_cache,
            http_cache_root=http_cache_root,
        )
        REDACTOR.add(web.credentials.password, web.credentials.totp_seed)
        self._web = web

    def show_live(self) -> CliResult:
        """``show-live`` without -n: the live configuration, web settings included (1 login)."""
        return self.run("show-live")

    def install_app(self, app_slug: str) -> CliResult:
        """``install-app -a <slug>`` (installs the App through the web UI unless it is installed already)."""
        return self.run("install-app", "-a", app_slug)

    def uninstall_app(self, app_slug: str) -> CliResult:
        """``uninstall-app -a <slug>`` (uninstalls the App through the web UI when it is installed)."""
        return self.run("uninstall-app", "-a", app_slug)

    def review_permissions(self, *, app_slug: str | None = None) -> CliResult:
        """``review-permissions [-a <slug>]``: lists the pending permission requests (never ``-g``: no approval)."""
        return self.run("review-permissions", *(["-a", app_slug] if app_slug else []))

    def list_advisories(self, *, states: Sequence[str] = ("all",), use_web: bool = True) -> CliResult:
        """``list-advisories -s <state>... [-w]`` (``-w`` scrapes the advisory pages for the latest comment date)."""
        args = [part for state in states for part in ("-s", state)]
        return self.run("list-advisories", *args, *(["-w"] if use_web else []))

    def web_login(self, *, timeout: float | None = None) -> CliResult:
        """``web-login``: opens a VISIBLE browser logged in as the bot, then logs out at the first line of stdin (the
        harness sends one immediately). Needs a display: local runs only."""
        return self.run("web-login", input="\n", timeout=timeout)
