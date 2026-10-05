"""Session context of the harness (SPEC 15, F3): the composition root shared by the pytest plugin and the CLI.

An E2EContext is created per pytest session (``config.stash[E2E_CONTEXT_KEY]``, see get_context) or per harness
command. Its live part (target, identities, VerifiedOrg, capabilities, docker/App availability, the org lease) is
built by ensure_live() at the first live item only, so offline-only runs never touch GitHub; gating hooks and session
fixtures read the same context. Collaborators are imported lazily inside methods: the plugin is loaded by every pytest
session and must stay cheap and robust to import.

Web-UI tier (docs/web-ui-testing.md): probe() adds Cap.WEB_UI only when web_ui_problems() is empty (admin web
credentials, --e2e-allow-web-ui, a trusted SUT, no github.saml_sso, web logins not blocked); web_cli() builds the
web-mode CLIs (SUT under test or the trusted reset SUT, host installs only) sharing one LoginGate per bot account.

Webapp tier extras: ``extras["dtrack_mock"]`` (set by the plugin when a selected item uses the ``dtrack_mock``
fixture) starts the compose stack with the Dependency-Track mock; dtrack_mock() returns its client (enabling it on a
running stack when needed); blueprint_helper() wires a blueprints.BlueprintHelper to a webapp case; scenario
variables carry ``app_id`` (the e2e App id, "" without an App) next to ``app_slug``.
"""

from __future__ import annotations

import atexit
import dataclasses
import getpass
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, TypeGuard, TypeVar, cast

import pytest

from otterdog_e2e import __version__
from otterdog_e2e.naming import RunContext, new_run_context
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.blueprints import BlueprintHelper
    from otterdog_e2e.capabilities import Capabilities
    from otterdog_e2e.config_repo import ConfigRepoFlow
    from otterdog_e2e.differential import PrManifest
    from otterdog_e2e.github.app import AppAuth
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.github.janitor import Janitor, JanitorItem
    from otterdog_e2e.github.lease import OrgLease
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.known_bugs import KnownBug
    from otterdog_e2e.observe import ObservationRecorder
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import NormalizeContext
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import OtterdogCli, WebOtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.safety import AppIsolation, VerifiedOrg
    from otterdog_e2e.scenarios.engine import SutSide
    from otterdog_e2e.settings import AppCredentials, HarnessSettings, Identity, Target, WebCredentials
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.image import BuiltImage
    from otterdog_e2e.sut.spec import ResolvedSut
    from otterdog_e2e.sut.template import TemplateRef
    from otterdog_e2e.webapp.api import WebappApi
    from otterdog_e2e.webapp.stack import DtrackMock, ExternalWebapp, WebappStack
    from otterdog_e2e.webhooks.relay import DeliveryRelay
    from otterdog_e2e.webui.gate import LoginGate

    Deployment = WebappStack | ExternalWebapp

logger = logging.getLogger(__name__)
T = TypeVar("T")

# option dest -> environment fallback (pytest options of SPEC 15)
OPTION_ENV: Mapping[str, str] = {
    "e2e_target": "E2E_TARGET",
    "e2e_sut": "E2E_SUT",
    "e2e_base_sut": "E2E_BASE_SUT",
    "e2e_reset_sut": "E2E_RESET_SUT",
    "e2e_tags": "E2E_TAGS",
    "e2e_scenario": "E2E_SCENARIO",
    "e2e_artifacts": "E2E_ARTIFACTS",
    "e2e_run_id": "E2E_RUN_ID",
    "e2e_webapp_image": "E2E_WEBAPP_IMAGE",
    "e2e_pr_manifest": "E2E_PR_MANIFEST",
    "e2e_allow_web_ui": "E2E_ALLOW_WEB_UI",  # a flag: true/1/yes enables it
}
DEFAULT_SUT = "release:latest"
DEFAULT_RESET_SUT = "release:latest"
AUTO_BASE = "auto"  # --e2e-base-sut auto = the merge base of the SUT (ResolvedSut.base_sha)
MIN_RATE_REMAINING = 800  # E2E_MIN_RATE_REMAINING: live items are skipped below this core budget
MIN_RATE_ENV = "E2E_MIN_RATE_REMAINING"
LEASE_WAIT_ENV = "E2E_LEASE_WAIT"  # seconds to wait for a busy org lease (default 0: fail fast)
LEASE_HOLDER_ENV = "E2E_LEASE_HOLDER"  # overrides the holder text written into the (public) lease commit
LANE_ENV = "E2E_LANE"  # pr-fast | nightly-full (recorded in run.json)
INVOCATION_ENV = "E2E_INVOCATION"  # set by `otterdog-e2e run|pr`: the harness command recorded as run.json command
CI_ENV_KEYS = ("CI", "GITHUB_ACTIONS")
SUT_ROLES = ("head", "base", "reset")
MUTATOR_IDENTITIES = ("admin", "author", "approver", "outsider")
RUN_FILE = "run.json"
RESULTS_FILE = "results.jsonl"
OBSERVATIONS_DIR = "observations"
KNOWN_BUGS_FILE = "known_bugs.yaml"
OFFLINE_CONFIG_REPO = ".otterdog"
DEFAULT_TEAMS: Mapping[str, str] = {
    "admin": "otterdog-admins",
    "approval": "project-leads",
    "contributors": "e2e-contributors",
}
WEBAPP_READY_TIMEOUT = 300.0
HTTP_CACHE_DIR = "http-cache"  # live HTTP caches of the run (scratch) / offline ones of every run (E2E_CACHE_DIR)
WORKSPACE_PLACEHOLDER = "<WORKSPACE>"  # differential observations: each side's workspace root
PERMISSION_LEVELS: Mapping[str, int] = {"read": 1, "write": 2, "admin": 3}
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$")
_DURATION_UNITS: Mapping[str, float] = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_VERSION_RE = re.compile(r"version\s+(\S+)")
WEB_ROLES = ("head", "reset")  # SUT roles that may get a web-mode CLI (trusted host installs only)
_TRUE_TEXT = frozenset({"1", "true", "yes", "on"})


class ContextError(RuntimeError):
    """The session cannot provide a resource (missing configuration, identity, App, ...)."""


# --- small helpers -------------------------------------------------------------------------------------------------
def split_csv(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Comma separated values (or a sequence of them) as a tuple of stripped, non-empty strings."""
    if value is None:
        return ()
    parts = value.split(",") if isinstance(value, str) else [p for item in value for p in str(item).split(",")]
    return tuple(part.strip() for part in parts if part.strip())


def text_or_none(value: Any) -> str | None:
    """Stripped string value, None for None and blank strings."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def env_flag(environ: Mapping[str, str], name: str) -> bool:
    """True when ``name`` is set to 1/true/yes/on (case-insensitive)."""
    return str(environ.get(name, "")).strip().lower() in _TRUE_TEXT


def in_ci(environ: Mapping[str, str]) -> bool:
    """True when CI or GITHUB_ACTIONS is set to a truthy value."""
    return any(environ.get(key, "").strip().lower() not in ("", "0", "false", "no") for key in CI_ENV_KEYS)


def target_env_name(value: str) -> str:
    """Name used for the env files of a target given by name or path (``targets/free.yaml`` -> ``free``):
    settings.target_env_name, which refuses malformed names (TargetError)."""
    from otterdog_e2e import settings

    return settings.target_env_name(value)


def lock_held(path: Path) -> bool:
    """True when another holder has the file lock ``path`` right now (a missing lock file is free; never waits)."""
    import filelock

    if not path.exists():
        return False
    try:
        with filelock.FileLock(str(path), timeout=0):
            return False
    except filelock.Timeout:
        return True


def parse_duration(text: str) -> timedelta:
    """``90``/``90s``, ``10m``, ``6h``, ``2d`` as a timedelta (ValueError otherwise)."""
    match = _DURATION_RE.match(text)
    if not match:
        raise ValueError(f"invalid duration {text!r} (examples: 90s, 10m, 6h, 2d)")
    return timedelta(seconds=float(match.group(1)) * _DURATION_UNITS[match.group(2)])


def parse_time(value: Any) -> datetime | None:
    """ISO timestamp (``Z``, offset or naive = UTC) as an aware datetime, None when absent or invalid."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def describe_error(exc: BaseException) -> str:
    """Redacted ``Type: message`` of an exception."""
    return REDACTOR(f"{type(exc).__name__}: {exc}")


def interactive_terminal() -> bool:
    """True when the process's original stdin is a terminal (pytest replaces sys.stdin while capturing output)."""
    stream = sys.__stdin__
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, OSError, ValueError):  # closed or detached stdin
        return False


def lease_holder(environ: Mapping[str, str]) -> str:
    """Holder text of the org lease (public commit message): the CI run, else ``local:<user>``."""
    override = environ.get(LEASE_HOLDER_ENV)
    if override:
        return override
    if environ.get("GITHUB_ACTIONS") == "true":
        repository = environ.get("GITHUB_REPOSITORY", "?")
        return f"ci:{repository}/actions/runs/{environ.get('GITHUB_RUN_ID', '?')}"
    try:
        return f"local:{getpass.getuser()}"
    except (OSError, KeyError):
        return "local"


def installation_problems(installation: Mapping[str, Any], *, permissions: bool = True) -> list[str]:
    """Why an App installation cannot serve the webapp tier (selection all, not suspended, permissions, events)."""
    from otterdog_e2e.appmanifest import DEFAULT_EVENTS, DEFAULT_PERMISSIONS

    problems = []
    if installation.get("repository_selection") != "all":
        problems.append(f"repository_selection is {installation.get('repository_selection')!r}, expected 'all'")
    if installation.get("suspended_at"):
        problems.append(f"installation suspended since {installation['suspended_at']}")
    if permissions:
        granted = installation.get("permissions") or {}
        missing = [
            f"{name} ({granted.get(name, 'none')} < {level})"
            for name, level in DEFAULT_PERMISSIONS.items()
            if PERMISSION_LEVELS.get(str(granted.get(name, "")), 0) < PERMISSION_LEVELS[level]
        ]
        if missing:
            problems.append(f"permissions missing: {', '.join(missing)}")
        events = sorted(set(DEFAULT_EVENTS) - set(installation.get("events") or []))
        if events:
            problems.append(f"events not subscribed: {', '.join(events)}")
    return problems


def printed_version(version_output: str) -> str | None:
    """Version printed by ``otterdog --version`` (``otterdog.sh, version 1.6.1`` -> ``1.6.1``)."""
    match = _VERSION_RE.search(version_output)
    return match.group(1) if match else None


def workspace_literals(cli: OtterdogCli) -> list[tuple[str, str]]:
    """Literals hiding a differential side's workspace root in its observations: the host path (as given and
    resolved) and, for container runtimes (untrusted SUTs), the mount point the CLI sees instead (``/ws/``).

    Each side renders into its own workspace (scratch/workspaces/diff-<mode>-<role>) and otterdog prints absolute
    config paths (e.g. jsonnet load errors), so without them every such output would be a spurious delta.
    """
    from otterdog_e2e.otterdog.runtime import CONTAINER_WORKDIR

    root = cli.workspace.root
    pairs = [(form, WORKSPACE_PLACEHOLDER) for form in dict.fromkeys((str(root), str(root.resolve())))]
    if getattr(cli.runtime, "in_container", False):
        pairs.append((f"{CONTAINER_WORKDIR}/", f"{WORKSPACE_PLACEHOLDER}/"))
    return pairs


# --- options -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class E2EOptions:
    """The --e2e-* options of a session (env fallbacks applied)."""

    target: str | None = None
    sut: str = DEFAULT_SUT
    base_sut: str | None = None
    reset_sut: str = DEFAULT_RESET_SUT
    tags: tuple[str, ...] = ()
    scenario: tuple[str, ...] = ()
    artifacts: Path | None = None
    run_id: str | None = None
    keep: bool = False
    no_reset: bool = False
    webapp_image: str | None = None
    pr_manifest: Path | None = None
    strict_diff: bool = False
    no_http_cache: bool = False
    allow_remote_webapp: bool = False
    trust_code: str | None = None
    allow_web_ui: bool = False

    @classmethod
    def from_config(cls, config: pytest.Config) -> E2EOptions:
        """Read the options registered by pytest_plugin.pytest_addoption."""

        def text(dest: str) -> str | None:
            """Option value as a stripped string or None."""
            return text_or_none(config.getoption(dest, None))

        def flag(dest: str) -> bool:
            """Boolean option value."""
            return bool(config.getoption(dest, False))

        artifacts, manifest = text("e2e_artifacts"), text("e2e_pr_manifest")
        return cls(
            target=text("e2e_target"),
            sut=text("e2e_sut") or DEFAULT_SUT,
            base_sut=text("e2e_base_sut"),
            reset_sut=text("e2e_reset_sut") or DEFAULT_RESET_SUT,
            tags=split_csv(text("e2e_tags")),
            scenario=split_csv(text("e2e_scenario")),
            artifacts=Path(artifacts).expanduser() if artifacts else None,
            run_id=text("e2e_run_id"),
            keep=flag("e2e_keep"),
            no_reset=flag("e2e_no_reset"),
            webapp_image=text("e2e_webapp_image"),
            pr_manifest=Path(manifest).expanduser() if manifest else None,
            strict_diff=flag("e2e_strict_diff"),
            no_http_cache=flag("e2e_no_http_cache"),
            allow_remote_webapp=flag("e2e_allow_remote_webapp"),
            trust_code=text("e2e_trust_code"),
            allow_web_ui=flag("e2e_allow_web_ui"),
        )


class SutPair(NamedTuple):
    """Base and head sides of a differential run (unpackable: ``base, head = sut_pair``)."""

    base: SutSide
    head: SutSide


@dataclass
class WebappCase:
    """State of one isolated webapp test (F10), created by E2EContext.begin_webapp_case."""

    flow: ConfigRepoFlow
    api: WebappApi
    org: str
    baseline_text: str
    started_at: datetime
    seen_comment_ids: frozenset[str] = frozenset()


# --- the context ---------------------------------------------------------------------------------------------------
@dataclass
class E2EContext:
    """Everything the gating hooks, session fixtures and harness commands share; live fields stay None until
    ensure_live() (or the explicit load_target/verify/probe/acquire_lease steps of a command)."""

    options: E2EOptions
    settings: HarnessSettings
    run_ctx: RunContext
    scratch: Path
    artifacts_dir: Path
    target: Target | None = None
    identities: dict[str, Identity] = field(default_factory=dict)
    verified: VerifiedOrg | None = None
    capabilities: Capabilities | None = None
    docker_ok: bool | None = None
    app_ok: bool | None = None
    lease: OrgLease | None = None
    live_error: str | None = None
    finalizers: list[Callable[[], None]] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    environ: MutableMapping[str, str] = field(default_factory=lambda: os.environ, repr=False)
    run_info: dict[str, Any] = field(default_factory=dict, repr=False)
    leaks: list[Path] = field(default_factory=list)
    scrub_error: str | None = None
    closed: bool = False
    _live_attempted: bool = field(default=False, repr=False)
    _http: dict[tuple[str, str], GitHubHttp] = field(default_factory=dict, repr=False)
    _memos: dict[str, Any] = field(default_factory=dict, repr=False)
    _session_lock: Any = field(default=None, repr=False)  # filelock of the run's scratch (one session per run id)

    # --- creation and teardown ----------------------------------------------------------------------------------
    @classmethod
    def create(
        cls,
        options: E2EOptions,
        *,
        environ: MutableMapping[str, str] | None = None,
        settings: HarnessSettings | None = None,
        make_dirs: bool = True,
        artifacts: bool = True,
    ) -> E2EContext:
        """Settings, run context, scratch (0700) and artifacts dirs of a new session; no GitHub access.

        ``make_dirs=False`` creates nothing (read-only commands); ``artifacts=False`` skips the artifacts dir only.
        """
        from otterdog_e2e.settings import harness_settings

        env = os.environ if environ is None else environ
        settings = settings or harness_settings(env)
        if options.artifacts is not None:
            settings = dataclasses.replace(settings, artifacts_root=options.artifacts.resolve())
        run_ctx = new_run_context(options.run_id)
        scratch = settings.cache_dir / "run" / run_ctx.run_id
        artifacts_dir = settings.artifacts_root / run_ctx.run_id
        if make_dirs:
            scratch = settings.scratch(run_ctx.run_id)
            if artifacts:
                artifacts_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        return cls(
            options=options,
            settings=settings,
            run_ctx=run_ctx,
            scratch=scratch,
            artifacts_dir=artifacts_dir,
            environ=env,
        )

    def start_session(self, *, argv: Sequence[str] = ()) -> None:
        """Process-wide setup: log redaction, scratch HOME for subprocesses (SEC-10), run-scoped docker container
        names (otterdog-e2e-<run>-<seq>), the first run.json and an atexit close() (lease release, scrub) for
        sessions that die before their normal teardown."""
        from otterdog_e2e import procs, redact
        from otterdog_e2e.otterdog import runtime

        self._lock_scratch()  # before anything else: a refused session must not touch (or later drop) the scratch
        redact.install_logging_filter()
        procs.set_default_home(self.scratch / "home")
        runtime.set_container_scope(self.run_ctx.run_id)
        atexit.register(self.close)
        self.write_run_info(
            run_id=self.run_ctx.run_id,
            started_at=self.run_ctx.created_at.isoformat(),
            harness_version=__version__,
            argv=[str(arg) for arg in argv],
            command=REDACTOR(self.environ.get(INVOCATION_ENV) or "") or None,
            lane=self.environ.get(LANE_ENV),
            target=self.options.target,
            sut=self.options.sut,
            base=self.options.base_sut,
            reset_sut=self.options.reset_sut,
            tags=list(self.options.tags),
            scenarios=list(self.options.scenario),
        )

    def scratch_lock_path(self) -> Path:
        """``<cache>/run/<run id>.lock``: held by the session using the run's scratch (outside the scratch, so
        dropping the scratch never races with the lock; ``cache prune`` removes it with the run directory)."""
        return self.scratch.parent / f"{self.run_ctx.run_id}.lock"

    def _lock_scratch(self) -> None:
        """Take the run's scratch lock without waiting; ContextError when another session of this machine uses the
        same run id (DESTR-03: it would share, and at its end delete, this session's scratch)."""
        if self._session_lock is not None:
            return
        import filelock

        path = self.scratch_lock_path()
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        lock = filelock.FileLock(str(path), timeout=0)
        try:
            lock.acquire()
        except filelock.Timeout:
            raise ContextError(
                f"run id {self.run_ctx.run_id} is in use by another session on this machine ({path}): every session "
                "needs its own run id"
            ) from None
        self._session_lock = lock

    def _unlock_scratch(self) -> None:
        """Release the scratch lock taken by start_session (no-op otherwise)."""
        lock, self._session_lock = self._session_lock, None
        if lock is not None:
            lock.release()

    @property
    def is_live(self) -> bool:
        """True once ensure_live() succeeded and while this session still holds the org lease (a lease that was lost,
        e.g. taken over after a failed renewal, ends the live session: no more writes)."""
        return self.verified is not None and self.live_error is None and self.lease is not None and self.lease.held

    def live_problem(self) -> str | None:
        """Why a verified session is not live (None when it is live or was never verified)."""
        if self.verified is None or self.live_error is not None:
            return None
        if self.lease is None:
            return "the org lease is not held by this session"
        if not self.lease.held:
            return "the org lease of this session was lost (taken over or deleted): no further writes"
        return None

    def add_finalizer(self, finalizer: Callable[[], None]) -> None:
        """Register a cleanup run by close() in reverse order (relay stop, webapp down, ...)."""
        self.finalizers.append(finalizer)

    def close(self) -> None:
        """Run finalizers (reverse order), release the lease, delete untrusted SUT sources, scrub artifacts, drop the
        scratch dir (not with keep)."""
        if self.closed:
            return
        self.closed = True
        atexit.unregister(self.close)
        while self.finalizers:
            finalizer = self.finalizers.pop()
            try:
                finalizer()
            except Exception as exc:  # noqa: BLE001 - one failing finalizer must not skip the others
                logger.error("session finalizer failed: %s", describe_error(exc))
        try:
            self.release_lease()
        except Exception as exc:  # noqa: BLE001 - the lease expires on its own; scrubbing must still run
            logger.error("could not release the org lease: %s", describe_error(exc))
        self._record_web_logins()
        self._cleanup_untrusted_sources()
        self._scrub()
        self._drop_scratch()
        self._purge_live_http_caches()

    def _purge_live_http_caches(self) -> None:
        """Delete the HTTP caches of live identities that older harness versions kept in ``<E2E_CACHE_DIR>/http-cache``
        across runs: otterdog pickles the request headers, the token's Authorization header included (ISO-04). Only
        the caches of offline commands (dummy token, ``*-offline``) are shared across runs now."""
        root = self.settings.cache_dir / HTTP_CACHE_DIR
        if not root.is_dir() or root.is_symlink():
            return
        for entry in root.iterdir():
            if entry.name.endswith("-offline"):
                continue
            try:
                if entry.is_dir() and not entry.is_symlink():
                    shutil.rmtree(entry)
                else:
                    entry.unlink()
            except OSError as exc:
                logger.warning("could not delete the live HTTP cache %s: %s", entry, exc)

    def _cleanup_untrusted_sources(self) -> None:
        """sut.spec.cleanup_source for every resolved untrusted SUT (its private export; atexit is the fallback)."""
        resolved = [value for key, value in self._memos.items() if key.startswith("resolved:")]
        untrusted = [sut for sut in resolved if not getattr(sut, "trusted", True)]
        if not untrusted:
            return
        from otterdog_e2e.sut.spec import cleanup_source

        for sut in untrusted:
            try:
                cleanup_source(sut)
            except Exception as exc:  # noqa: BLE001 - every export is attempted; atexit retries the rest
                logger.warning("could not delete the source of %s: %s", getattr(sut, "label", sut), describe_error(exc))

    def _scrub(self) -> None:
        """report.scrub_artifacts on the run's artifacts dir (leaks and errors are kept on the context)."""
        if not self.artifacts_dir.is_dir():
            return
        from otterdog_e2e import report

        try:
            self.leaks = list(report.scrub_artifacts(self.artifacts_dir, REDACTOR))
        except Exception as exc:  # noqa: BLE001 - recorded: a failed scrub fails the session
            self.scrub_error = describe_error(exc)
            logger.error("artifact scrub failed: %s", self.scrub_error)
        for leak in self.leaks:
            logger.error("removed artifact leaking a secret: %s", leak)

    def _drop_scratch(self) -> None:
        """Restore the process defaults of start_session, then remove the private scratch dir (tokens may sit in
        otterdog's HTTP cache) unless --e2e-keep."""
        from otterdog_e2e import procs
        from otterdog_e2e.otterdog import runtime

        procs.set_default_home(None)
        if runtime.container_scope() == self.run_ctx.run_id:
            runtime.set_container_scope(None)
        try:
            if not self.options.keep and self.scratch.is_dir() and not self.scratch.is_symlink():
                if self._session_lock is None and not self._scratch_unused():
                    logger.warning(
                        "not deleting %s: another session of run %s uses it", self.scratch, self.run_ctx.run_id
                    )
                    return
                shutil.rmtree(self.scratch, ignore_errors=True)
        finally:
            self._unlock_scratch()

    def _scratch_unused(self) -> bool:
        """True when no session holds the run's scratch lock (checked by contexts that never started a session)."""
        return not lock_held(self.scratch_lock_path())

    # --- memoization and requirements ---------------------------------------------------------------------------
    def _memo(self, key: str, factory: Callable[[], T]) -> T:
        """Value of ``factory`` computed once per context."""
        if key not in self._memos:
            self._memos[key] = factory()
        return cast(T, self._memos[key])

    def require_target(self) -> Target:
        """The loaded target (ContextError before load_target)."""
        if self.target is None:
            raise ContextError("no target loaded")
        return self.target

    def require_verified(self) -> VerifiedOrg:
        """The VerifiedOrg (ContextError before verify)."""
        if self.verified is None:
            raise ContextError("the target org has not been verified (no live session)")
        return self.verified

    def require_capabilities(self) -> Capabilities:
        """The probed capabilities (ContextError before probe)."""
        if self.capabilities is None:
            raise ContextError("capabilities have not been probed (no live session)")
        return self.capabilities

    def require_identity(self, name: str) -> Identity:
        """A configured identity (ContextError naming its token env var otherwise)."""
        identity = self.identities.get(name)
        if identity is not None:
            return identity
        spec = self.target.identities.get(name) if self.target is not None else None
        hint = f" (set {spec.token_env})" if spec is not None and spec.token_env else ""
        raise ContextError(f"identity {name!r} is not configured{hint}")

    # --- live session ---------------------------------------------------------------------------------------------
    def ensure_live(self) -> None:
        """Load target + identities, verify_target, probe capabilities, docker/app checks, acquire the lease (+heartbeat).

        Failures are stored in live_error (live items then skip/fail with that reason) instead of raising repeatedly.
        """
        if self.is_live or self._live_attempted:
            return
        self._live_attempted = True
        try:
            self._go_live()
        except Exception as exc:  # noqa: BLE001 - stored once, reported by every live item
            self.live_error = describe_error(exc)
            logger.error("live session setup failed: %s", self.live_error)
            self._abort_live()
        except BaseException as exc:
            # pytest-timeout's Failed, KeyboardInterrupt, SystemExit: never leave a verified session without its
            # lease (every later live item would then write without the lease and the ledger tag)
            self.live_error = describe_error(exc) or type(exc).__name__
            logger.error("live session setup interrupted: %s", self.live_error)
            self._abort_live()
            raise

    def _go_live(self) -> None:
        """Every live precondition, in order: target, verification, probes, lease, run.json."""
        target = self.load_target()
        verified = self.verify()
        capabilities = self.probe()
        self.acquire_lease()
        self.write_run_info(
            target={"name": target.name, "profile": target.profile, "org": verified.login, "plan": verified.plan},
            org=verified.login,
            plan=verified.plan,
            capabilities=capabilities.to_json(),
            transport=target.webapp.transport,
        )

    def _abort_live(self) -> None:
        """Forget a partially built live state and release the lease if it was taken."""
        self.verified = None
        try:
            self.release_lease()
        except Exception as exc:  # noqa: BLE001 - best effort while aborting: the lease expires on its own
            logger.warning("could not release the org lease: %s", describe_error(exc))

    def load_target(self) -> Target:
        """Load the env files, the target and its identities (no GitHub access); TargetError when invalid."""
        if self.target is not None:
            return self.target
        from otterdog_e2e.settings import TargetError, load_env_files, load_target, resolve_identities

        if not self.options.target:
            raise TargetError("no target: pass --e2e-target (or set E2E_TARGET)")
        load_env_files(target_env_name(self.options.target), self.settings.project_root, self.environ)
        target = load_target(self.options.target, self.settings, self.environ)
        self.identities = resolve_identities(target, self.environ)
        self.target = target
        return target

    def verify(self, *, require_marker: bool = True, check_identities: bool = True) -> VerifiedOrg:
        """verify_target with the admin token (SPEC 5.1): the VerifiedOrg every mutation path requires."""
        from otterdog_e2e.safety import verify_target

        target = self.load_target()
        verified = verify_target(
            self.http("admin"),
            target,
            self.identities,
            require_marker=require_marker,
            check_identities=check_identities,
        )
        self.verified = verified
        return verified

    def probe(self) -> Capabilities:
        """Docker and App readiness, then probe_capabilities (read-only) of the verified org; WEB_UI when
        web_ui_problems() is empty (the reason is kept in extras["web_ui_reason"])."""
        from otterdog_e2e.capabilities import Cap, probe_capabilities, with_capabilities

        target, verified = self.require_target(), self.require_verified()
        self.docker_ok = self.docker_available()
        self.app_ok, self.extras["app_reason"] = self.check_app()
        capabilities = probe_capabilities(
            self.http("admin"),
            verified,
            identities=self.identities,
            app_ok=self.app_ok,
            docker_ok=self.docker_ok,
            overrides=target.capability_overrides,
            fixture_repo=next(iter(target.fixture_repos), None),
        )
        problems = self.web_ui_problems()
        self.extras["web_ui_reason"] = "; ".join(problems)
        if not problems:
            capabilities = with_capabilities(capabilities, Cap.WEB_UI, overrides=target.capability_overrides)
        self.capabilities = capabilities
        self.write_run_info(web_ui={"enabled": capabilities.has(Cap.WEB_UI), "reason": "; ".join(problems) or None})
        return self.capabilities

    def check_app(self) -> tuple[bool, str]:
        """(ready, reason): App credentials present, owned by the test org and installed on test orgs only
        (verify_app), installed on the org for all repositories and not suspended. An App that fails verify_app
        also sets ``extras["app_unsafe"]``: the webapp gate then fails its items instead of skipping them."""
        from otterdog_e2e.safety import SafetyError

        self.extras.pop("app_unsafe", None)
        try:
            if self.app_credentials() is None:
                return False, "no GitHub App configured"
            self.verify_app()
            installation = self.app_auth().installation_for_org(self.require_target().org)
        except SafetyError as exc:
            reason = f"unsafe GitHub App: {describe_error(exc)}"
            logger.error("%s", reason)
            self.extras["app_unsafe"] = True
            return False, reason
        except Exception as exc:  # noqa: BLE001 - readiness probe: the reason becomes the skip reason
            return False, f"App check failed: {describe_error(exc)}"
        if installation is None:
            return False, "the GitHub App is not installed on the org"
        problems = installation_problems(installation, permissions=False)
        return not problems, "; ".join(problems)

    # --- GitHub clients -------------------------------------------------------------------------------------------
    def http(self, name: str, *, write: bool = False) -> GitHubHttp:
        """Cached GitHubHttp of an identity: read-only, or (write) write-scoped to the verified org."""
        key = (name, "write" if write else "read")
        if key not in self._http:
            from otterdog_e2e.github.http import GitHubHttp

            token = self.require_identity(name).token
            scope = self.require_verified() if write else None
            client = GitHubHttp(token, write_scope=scope, read_only=not write, identity=name)
            if write:
                client.write_guard = self.check_lease_not_lost
            self._http[key] = client
        return self._http[key]

    def check_lease_not_lost(self) -> None:
        """SafetyError once the org lease this session acquired is lost (a failed renewal: taken over or deleted):
        the writes of the session stop (GitHub clients, guarded otterdog applies, live otterdog commands). Before the
        lease is acquired and after it is released nothing is refused (bootstrap, the lease itself)."""
        from otterdog_e2e.safety import SafetyError

        lease = self.lease
        if lease is not None and not lease.held:
            raise SafetyError(
                f"the org lease of run {self.run_ctx.run_id} was lost (taken over or deleted): refusing further writes"
            )

    def public_http(self) -> GitHubHttp:
        """Anonymous read-only client for public upstream reads (SUT resolution)."""

        def build() -> GitHubHttp:
            """Create the anonymous client."""
            from otterdog_e2e.github.http import GitHubHttp

            return GitHubHttp(None, read_only=True, identity="anonymous")

        return self._memo("public_http", build)

    def oracle(self) -> Oracle:
        """Read-only Oracle of the test org (the oracle identity; the admin client when it falls back to admin)."""

        def build() -> Oracle:
            """Create the oracle."""
            from otterdog_e2e.github.oracle import Oracle

            oracle, admin = self.identities.get("oracle"), self.identities.get("admin")
            separate = oracle is not None and (admin is None or oracle.token != admin.token)
            return Oracle(self.http("oracle" if separate else "admin"), self.require_target().org)

        return self._memo("oracle", build)

    def mutator(self, name: str = "admin") -> Mutator:
        """Write-scoped Mutator of an identity (requires the VerifiedOrg)."""

        def build() -> Mutator:
            """Create the mutator."""
            from otterdog_e2e.github.mutate import Mutator

            return Mutator(self.http(name, write=True), self.require_verified())

        return self._memo(f"mutator:{name}", build)

    def mutators(self) -> dict[str, Mutator]:
        """Mutators of every configured identity able to act on PRs (admin, author, approver, outsider)."""
        return {name: self.mutator(name) for name in MUTATOR_IDENTITIES if name in self.identities}

    def app_credentials(self) -> AppCredentials | None:
        """App credentials of the target (None when not configured)."""

        def build() -> AppCredentials | None:
            """Resolve the credentials from the environment."""
            from otterdog_e2e.settings import resolve_app_credentials

            return resolve_app_credentials(self.require_target(), self.environ)

        return self._memo("app_credentials", build)

    def require_app_credentials(self) -> AppCredentials:
        """App credentials (ContextError when the App is not configured)."""
        credentials = self.app_credentials()
        if credentials is None:
            raise ContextError(
                "no GitHub App configured (E2E_APP_ID, E2E_APP_PRIVATE_KEY[_FILE], E2E_APP_WEBHOOK_SECRET)"
            )
        return credentials

    def app_auth(self) -> AppAuth:
        """AppAuth of the e2e App."""

        def build() -> AppAuth:
            """Create the App authenticator."""
            from otterdog_e2e.github.app import AppAuth

            return AppAuth(self.require_app_credentials())

        return self._memo("app_auth", build)

    def verify_app(self) -> AppIsolation:
        """safety.verify_app of the e2e App against the target (never cached: GET /app and GET /app/installations
        are read again on every call); SafetyError when the App could reach a non-test organization."""
        from otterdog_e2e.safety import verify_app

        isolation = verify_app(self.app_auth(), self.require_target())
        installs = len(isolation.installations)
        self.write_run_info(app={"slug": isolation.slug, "owner": isolation.owner, "installations": installs})
        return isolation

    def installation_id(self) -> int:
        """Installation id of the App on the org after verify_app and the full preflight (GH-09: selection,
        suspension, permissions and events)."""

        def build() -> int:
            """Verify the App, look the installation up and check it."""
            self.verify_app()
            installation = self.app_auth().installation_for_org(self.require_target().org)
            if installation is None:
                raise ContextError("the GitHub App is not installed on the org (install it on All repositories)")
            problems = installation_problems(installation)
            if problems:
                raise ContextError("GitHub App installation not ready: " + "; ".join(problems))
            return int(installation["id"])

        return self._memo("installation_id", build)

    # --- org lease and purgeable runs -----------------------------------------------------------------------------
    def lease_handle(self) -> OrgLease:
        """The OrgLease object of this run (not acquired); also serves read-only ledger and holder queries."""

        def build() -> OrgLease:
            """Create the lease object on target.configs_repo."""
            from otterdog_e2e.github.lease import OrgLease

            target = self.require_target()
            return OrgLease(
                self.mutator("admin"),
                self.oracle(),
                repo=target.configs_repo,
                run_ctx=self.run_ctx,
                holder=lease_holder(self.environ),
            )

        return self._memo("lease_handle", build)

    def acquire_lease(
        self,
        *,
        wait: float | None = None,
        heartbeat: bool = True,
        takeover_run: str | None = None,
        force_takeover: bool = False,
    ) -> OrgLease:
        """Acquire the org lease (E2E_LEASE_WAIT seconds of patience) and start its heartbeat.

        ``takeover_run`` (janitor --run-id): an unexpired lease of that run is replaced by a compare-and-swap update
        when the run looks dead (no renewal for 20 minutes, or the holder is this CI job; ``force_takeover`` skips the
        check); a lease renewed recently raises LeaseBusy (DESTR-05: never delete the lease of a live session).
        """
        if self.lease is not None:
            return self.lease
        lease = self.lease_handle()
        trusted = lease_holder(self.environ) if self.environ.get("GITHUB_ACTIONS") == "true" else None
        lease.acquire(
            wait=self.lease_wait() if wait is None else wait,
            takeover_run=takeover_run,
            force_takeover=force_takeover,
            trusted_holder=trusted,
        )
        self.lease = lease
        if heartbeat:
            lease.start_heartbeat()
        return lease

    def require_lease(self, what: str) -> OrgLease:
        """The org lease this session holds (ContextError naming ``what`` when it is not held, or was lost)."""
        lease = self.lease
        if lease is None or not lease.held:
            raise ContextError(f"{what} needs the org lease held by this session (acquire it first)")
        return lease

    def lease_wait(self) -> float:
        """Seconds to wait for a busy lease (E2E_LEASE_WAIT, default 0)."""
        return float(self.environ.get(LEASE_WAIT_ENV) or 0)

    def release_lease(self) -> None:
        """Stop the heartbeat and release the lease (no-op when not held)."""
        lease, self.lease = self.lease, None
        if lease is None:
            return
        try:
            lease.stop_heartbeat()
        finally:
            lease.release()

    def ledger(self) -> frozenset[str]:
        """Run ids registered in the ledger (read once per context)."""
        return self._memo("ledger", lambda: frozenset(self.lease_handle().ledger()))

    def active_run_ids(self) -> frozenset[str]:
        """Run id of an unexpired lease held by another run (empty while this context holds the lease)."""

        def build() -> frozenset[str]:
            """Read the current lease holder."""
            if self.lease is not None:
                return frozenset()
            record = self.lease_handle().holder_record()
            if not record or not record.get("run_id"):
                return frozenset()
            expires = parse_time(record.get("expires_at"))
            if expires is not None and expires <= datetime.now(UTC):
                return frozenset()
            return frozenset({str(record["run_id"])})

        return self._memo("active_runs", build)

    def purgeable(self, run_id: str) -> bool:
        """SPEC 9.5: in the ledger and not an unexpired lease holder (this run is purgeable for itself)."""
        if run_id == self.run_ctx.run_id:
            return True
        return run_id in self.ledger() and run_id not in self.active_run_ids()

    def permanent_repos(self) -> tuple[str, ...]:
        """Repos that outlive runs: configs, defaults, fixtures, extra protected and a fixed org config repo."""
        target = self.require_target()
        names = [target.configs_repo, target.defaults_repo, *target.fixture_repos, *target.extra_protected_repos]
        if target.org_config_repo != "auto":
            names.append(target.org_config_repo)
        return tuple(dict.fromkeys(names))

    def janitor(self, purgeable: Callable[[str], bool]) -> Janitor:
        """Janitor of the org restricted to the run ids accepted by ``purgeable``."""
        from otterdog_e2e.github.janitor import Janitor

        target = self.require_target()
        return Janitor(
            self.oracle(),
            self.mutator("admin"),
            lease=self.lease or self.lease_handle(),
            configs_repo=target.configs_repo,
            defaults_repo=target.defaults_repo,
            protected_repos=self.permanent_repos(),
            purgeable=purgeable,
        )

    def sweep_own_run(self) -> list[JanitorItem]:
        """Delete what this run left behind (its per-session config repo included); used at session end."""
        janitor = self.janitor(lambda run_id: run_id == self.run_ctx.run_id)
        return list(janitor.sweep(janitor.scan()))

    # --- systems under test ---------------------------------------------------------------------------------------
    def spec_for(self, role: str) -> str:
        """SUT spec of a role: head (--e2e-sut), base (--e2e-base-sut, ``auto`` = merge base), reset."""
        if role == "head":
            return self.options.sut
        if role == "reset":
            return self.options.reset_sut
        if role != "base":
            raise ValueError(f"unknown SUT role {role!r}, expected one of {SUT_ROLES}")
        base = self.options.base_sut
        if not base:
            raise ContextError("no base SUT: pass --e2e-base-sut (or set E2E_BASE_SUT)")
        if base != AUTO_BASE:
            return base
        base_sha = self.resolve(self.options.sut).base_sha
        if not base_sha:
            raise ContextError(
                f"--e2e-base-sut auto: {self.options.sut!r} has no merge base (only pr:, path: and dirty: SUTs have"
                " one); pass the base explicitly, e.g. --e2e-base-sut sha:<parent commit> or tag:v1.6.1"
            )
        return f"sha:{base_sha}"

    def resolve(self, spec: str) -> ResolvedSut:
        """resolve_sut of a spec string (once per context)."""

        def build() -> ResolvedSut:
            """Parse and resolve the spec."""
            from otterdog_e2e.sut.spec import parse_sut_spec, resolve_sut

            return resolve_sut(parse_sut_spec(spec), self.settings, http=self.public_http())

        return self._memo(f"resolved:{spec}", build)

    def installed(self, role: str) -> InstalledCli:
        """InstalledCli of a role: host venv for trusted SUTs, the CLI of the SUT image otherwise (SPEC 5.5)."""
        return self._memo(f"installed:{role}", lambda: self._install(role))

    def _install(self, role: str) -> InstalledCli:
        """Install (or wrap) the CLI of a role and record it in run.json."""
        from otterdog_e2e.safety import SafetyError
        from otterdog_e2e.sut.cli_install import image_cli, install_cli

        resolved = self.resolve(self.spec_for(role))
        if role == "reset" and not resolved.trusted:
            raise SafetyError(f"the reset SUT {resolved.label} is not trusted: resets never run untrusted code")
        if resolved.trusted:
            installed = install_cli(resolved, self.settings)
        else:
            granted = self._host_trust(resolved)
            if granted is not None:
                installed = install_cli(granted, self.settings)
            else:
                installed = image_cli(resolved, self.image_for(role))
        self._record_sut(role, installed)
        return installed

    def _host_trust(self, resolved: ResolvedSut) -> ResolvedSut | None:
        """--e2e-trust-code <sha>: cli_install.grant_host_trust for the untrusted SUT of exactly that sha (from an
        interactive terminal, never in CI: SafetyError otherwise); None when the code does not name this SUT (it then
        runs in its docker image)."""
        code = (self.options.trust_code or "").strip().lower()
        if not code:
            return None
        if code != resolved.sha:
            logger.warning("--e2e-trust-code %s does not name %s: it runs in its docker image", code, resolved.label)
            return None
        from otterdog_e2e.safety import SafetyError
        from otterdog_e2e.sut.cli_install import grant_host_trust

        if in_ci(self.environ):
            raise SafetyError("--e2e-trust-code is refused when CI is set")
        return grant_host_trust(resolved, code, interactive=interactive_terminal(), environ=self.environ)

    def sut_trusted(self, role: str = "head") -> bool | None:
        """Trust of a role's SUT (gating, SPEC 5.5): decided by its spec (pr: never; release, tag, branch:main, path,
        dirty: always), else by resolve_sut (sha: and other branches, which may fetch the upstream mirror); None when
        it cannot be decided (the SUT fixtures then report the resolution error)."""

        def build() -> bool | None:
            """Parse, then resolve only when the spec does not decide."""
            from otterdog_e2e.sut.spec import parse_sut_spec

            try:
                spec = self.spec_for(role)
                parsed = parse_sut_spec(spec)
                if parsed.kind == "pr" or parsed.trusted:
                    return parsed.trusted
                return bool(self.resolve(spec).trusted)
            except Exception as exc:  # noqa: BLE001 - undecided here; the fixtures surface the real error
                logger.warning("cannot tell whether the %s SUT is trusted: %s", role, describe_error(exc))
                return None

        return self._memo(f"trusted:{role}", build)

    def _record_sut(self, role: str, installed: InstalledCli) -> None:
        """Store a SUT and its printed version in run.json."""
        key = {"head": "sut", "base": "base", "reset": "reset_sut"}[role]
        versions = {**(self.run_info.get("versions") or {}), role: installed.version_output.strip()}
        self.write_run_info(**{key: {**installed.sut.to_json(), "runtime": installed.runtime}}, versions=versions)
        if role == "head":
            self.extras["sut_label"] = installed.sut.label

    def sut_label(self) -> str:
        """Label of the SUT under test once installed, else its spec."""
        return str(self.extras.get("sut_label") or self.options.sut)

    def sut_version(self) -> str | None:
        """PEP 440 version of the SUT under test (resolve_sut, no install); None when it cannot be resolved (the SUT
        fixtures then report the resolution error)."""
        try:
            return str(self.resolve(self.options.sut).version) or None
        except Exception as exc:  # noqa: BLE001 - unknown version: callers fall back to their default behaviour
            logger.warning("cannot resolve the version of the SUT %s: %s", self.options.sut, describe_error(exc))
            return None

    def image_for(self, role: str) -> BuiltImage:
        """Webapp image of a role (head: --e2e-webapp-image when given)."""

        def build() -> BuiltImage:
            """Build (or describe the prebuilt) image."""
            from otterdog_e2e.sut.image import build_webapp_image, prebuilt_image

            if role == "head" and self.options.webapp_image:
                return prebuilt_image(self.options.webapp_image)
            return build_webapp_image(self.resolve(self.spec_for(role)))

        return self._memo(f"image:{role}", build)

    def docker_available(self) -> bool:
        """True when the docker daemon answers (checked once)."""

        def build() -> bool:
            """Ask docker."""
            from otterdog_e2e.sut.image import docker_available

            try:
                return bool(docker_available())
            except Exception as exc:  # noqa: BLE001 - any failure means docker cannot be used
                logger.info("docker is not available: %s", describe_error(exc))
                return False

        return self._memo("docker", build)

    def template_for(self, role: str) -> TemplateRef:
        """Base template of a role's SUT per target.template_mode. Publishing to the defaults repo happens only while
        this session holds the org lease (ContextError otherwise); the published or reused tag is then recorded in the
        lease (OrgLease.reference) so a concurrent janitor keeps it (SEC-17)."""

        def build() -> TemplateRef:
            """Resolve (and maybe publish) the template."""
            from otterdog_e2e.sut.template import TemplatePublisher, needs_publisher, resolve_template

            target = self.require_target()
            resolved = self.resolve(self.spec_for(role))
            lease, publisher = None, None
            if needs_publisher(target.template_mode, resolved):
                lease = self.require_lease(f"publishing the template of {resolved.label}")
                publisher = TemplatePublisher(
                    self.http("admin", write=True), self.require_verified(), target.defaults_repo
                )
            template = resolve_template(
                target.template_mode,
                resolved,
                upstream_repo=self.settings.upstream_repo,
                publisher=publisher,
                url=target.template_url,
            )
            if lease is not None and template.tag:
                lease.reference(f"tags/{template.tag}")
            return template

        return self._memo(f"template:{role}", build)

    # --- otterdog drivers -----------------------------------------------------------------------------------------
    def renderer(self, template: TemplateRef) -> OrgConfigRenderer:
        """OrgConfigRenderer of the org: live profile (keys GitHub did not return stay hidden, i.e. unmanaged), baseline
        of the run, cache limit hidden when unsupported."""
        from otterdog_e2e.capabilities import Cap
        from otterdog_e2e.otterdog.render import OrgConfigRenderer, build_baseline, org_profile

        target, verified = self.require_target(), self.require_verified()
        return OrgConfigRenderer(
            template=template,
            org=target.org,
            plan=verified.plan,
            org_profile=org_profile(verified.org_json),
            baseline=build_baseline(target, self.run_ctx),
            marker=target.marker,
            hide_cache_limit=not self.require_capabilities().has(Cap.ACTIONS_CACHE_LIMIT),
        )

    def baseline_manager(self, reset_cli: OtterdogCli, renderer: OrgConfigRenderer) -> BaselineManager:
        """BaselineManager of the run (trusted reset CLI, purgeable = ledger runs, protected repos of the target)."""
        from otterdog_e2e.otterdog.baseline import BaselineManager

        target = self.require_target()
        manager = BaselineManager(
            reset_cli=reset_cli,
            renderer=renderer,
            target=target,
            run_ctx=self.run_ctx,
            oracle=self.oracle(),
            purgeable=self.purgeable,
            protected_repos=target.protected_repos(self.run_ctx),
        )
        manager.write_check = self.check_lease_not_lost
        return manager

    def workspace(self, name: str, template: TemplateRef) -> ConfigWorkspace:
        """A ConfigWorkspace of the test org in scratch/workspaces/<name> with otterdog.json written."""
        from otterdog_e2e.otterdog.workspace import ConfigWorkspace

        target = self.require_target()
        workspace = ConfigWorkspace(
            self.scratch / "workspaces" / name,
            org=target.org,
            template=template,
            config_repo=target.config_repo_for(self.run_ctx),
        )
        workspace.write_otterdog_json()
        return workspace

    def offline_workspace(self, name: str) -> ConfigWorkspace:
        """A ConfigWorkspace of the offline org with the offline template placeholder (vendoring is up to the user)."""
        from otterdog_e2e.otterdog.workspace import ConfigWorkspace
        from otterdog_e2e.scenarios.offline import OFFLINE_ORG
        from otterdog_e2e.sut.template import offline_template

        workspace = ConfigWorkspace(
            self.scratch / "workspaces" / name,
            org=OFFLINE_ORG,
            template=offline_template(),
            config_repo=OFFLINE_CONFIG_REPO,
        )
        workspace.write_otterdog_json()
        return workspace

    def unique_name(self, hint: str) -> str:
        """``<seq>-<hint>`` with filesystem-safe characters (fresh workspaces)."""
        seq = int(self.extras.get("name_seq", 0)) + 1
        self.extras["name_seq"] = seq
        return f"{seq:03d}-{re.sub(r'[^A-Za-z0-9_.-]+', '_', hint)[:60]}"

    def cli(
        self,
        installed: InstalledCli,
        workspace: ConfigWorkspace,
        *,
        name: str,
        artifacts: str | None = None,
        identity: str = "admin",
        recorder: ObservationRecorder | None = None,
        offline: bool = False,
    ) -> OtterdogCli:
        """OtterdogCli with its own scratch (scratch/cli/<name>) and artifacts subdir (None = the run dir: SUT)."""
        from otterdog_e2e.otterdog.runner import OtterdogCli

        cli = OtterdogCli(
            installed,
            workspace,
            verified=None if offline else self.require_verified(),
            identity=None if offline else self.require_identity(identity),
            scratch=self.scratch / "cli" / name,
            artifacts_dir=self.artifacts_dir / artifacts if artifacts else self.artifacts_dir,
            settings=self.settings,
            recorder=recorder,
            offline=offline,
            http_cache=not self.options.no_http_cache,
            http_cache_root=self.scratch / HTTP_CACHE_DIR,
        )
        if not offline:
            cli.live_check = self.check_lease_not_lost
        return cli

    # --- differential ---------------------------------------------------------------------------------------------
    def recorder(self, role: str) -> ObservationRecorder:
        """ObservationRecorder of a differential side (observations/<role>.jsonl), one per role."""

        def build() -> ObservationRecorder:
            """Create the recorder."""
            from otterdog_e2e.observe import ObservationRecorder

            installed = self.installed(role)
            return ObservationRecorder(
                installed.sut.label,
                role,
                self.artifacts_dir / OBSERVATIONS_DIR / f"{role}.jsonl",
                normalize_ctx=self.normalize_context(installed),
            )

        return self._memo(f"recorder:{role}", build)

    def normalize_context(self, installed: InstalledCli) -> NormalizeContext:
        """Literals hiding run-specific strings (scratch path, run prefixes, printed version) in observations."""
        from otterdog_e2e.otterdog.output import NormalizeContext

        literals = [
            (str(self.scratch), "<SCRATCH>"),
            (self.run_ctx.prefix, "e2e-<RUN>"),
            (self.run_ctx.const_prefix, "E2E_<RUN>_"),
            (self.run_ctx.run_id, "<RUN>"),
        ]
        version = printed_version(installed.version_output)
        if version:
            literals.append((version, "<VERSION>"))
        return NormalizeContext(literals=literals)

    def sut_pair(self, *, live: bool) -> SutPair:
        """Base/head SutSides (cached per mode): offline sides use the offline workspace and template placeholder,
        live sides each SUT's own template; both record observations."""
        mode = "live" if live else "offline"
        return self._memo(f"pair:{mode}", lambda: SutPair(self._side("base", live=live), self._side("head", live=live)))

    def _side(self, role: str, *, live: bool) -> SutSide:
        """One SutSide (CLI artifacts under <role>/<mode>/ so reports attribute base and head); its workspace root
        is hidden in its observations (workspace_literals)."""
        from otterdog_e2e.scenarios.engine import SutSide
        from otterdog_e2e.sut.template import offline_template

        mode = "live" if live else "offline"
        installed = self.installed(role)
        template = self.template_for(role) if live else offline_template()
        name = f"diff-{mode}-{role}"
        workspace = self.workspace(name, template) if live else self.offline_workspace(name)
        recorder = self.recorder(role)
        cli = self.cli(installed, workspace, name=name, artifacts=f"{role}/{mode}", recorder=recorder, offline=not live)
        if recorder.normalize_ctx is not None:
            known = recorder.normalize_ctx.literals
            known.extend(pair for pair in workspace_literals(cli) if pair not in known)
        return SutSide(role=role, installed=installed, cli=cli, recorder=recorder, template=template)

    # --- web UI (docs/web-ui-testing.md) ----------------------------------------------------------------------------
    def web_credentials(self) -> WebCredentials | None:
        """Web-UI credentials of the admin bot (None when not configured); invalid ones raise WebCredentialsError."""

        def build() -> WebCredentials | None:
            """Resolve them from the environment."""
            from otterdog_e2e.settings import resolve_web_credentials

            return resolve_web_credentials(self.require_target(), self.environ)

        return self._memo("web_credentials", build)

    def web_gate(self) -> LoginGate:
        """The LoginGate of the bot account (one per context; its files are shared by every harness process)."""

        def build() -> LoginGate:
            """Create the gate in <E2E_CACHE_DIR>/webui."""
            from otterdog_e2e.webui.gate import GATE_DIR, LoginGate, spacing_from_env

            credentials = self.web_credentials()
            if credentials is None:
                raise ContextError("no web-UI credentials (E2E_ADMIN_PASSWORD, E2E_ADMIN_TOTP_SEED)")
            return LoginGate(
                self.settings.cache_dir / GATE_DIR,
                account=credentials.login,
                spacing=spacing_from_env(self.environ),
            )

        return self._memo("web_gate", build)

    def web_ui_problems(self) -> list[str]:
        """Why the WEB_UI capability is missing (empty: web-UI tests may run); see webui.gate.web_ui_problems."""
        from otterdog_e2e.settings import TargetError
        from otterdog_e2e.webui.gate import web_ui_problems

        target = self.require_target()
        credentials, error = None, None
        try:
            credentials = self.web_credentials()
        except TargetError as exc:
            error = describe_error(exc)
        blocked = self.web_gate().blocked() if credentials is not None else None
        return web_ui_problems(
            credentials=credentials is not None,
            allowed=self.options.allow_web_ui,
            sut_trusted=self.sut_trusted("head"),
            saml_sso=target.saml_sso,
            blocked=blocked,
            credentials_error=error,
        )

    def web_browsers(self, role: str) -> Path:
        """PLAYWRIGHT_BROWSERS_PATH with the Firefox of a role's SUT installed (once per role and session)."""

        def build() -> Path:
            """Install the browser with the role's own Playwright (trusted host installs only)."""
            from otterdog_e2e.sut.cli_install import ensure_playwright_firefox

            return ensure_playwright_firefox(self.installed(role), self.settings)

        return self._memo(f"web_browsers:{role}", build)

    def web_cli(self, role: str, *, name: str) -> WebOtterdogCli:
        """A web-mode CLI of ``role`` ("head": the SUT under test, "reset": the trusted reader) with its own workspace
        (``webui-<name>``, the head template like reset_cli), cached per (role, name).

        ContextError when web_ui_problems() is not empty; SafetyError for an untrusted SUT, even one granted host
        trust with --e2e-trust-code (the decision uses the spec's own trust).
        """
        if role not in WEB_ROLES:
            raise ValueError(f"web CLIs exist for the roles {WEB_ROLES}, not {role!r}")

        def build() -> WebOtterdogCli:
            """Check, install the browser, create the workspace and the CLI."""
            from otterdog_e2e.otterdog.runner import WebMode, WebOtterdogCli
            from otterdog_e2e.safety import SafetyError

            problems = self.web_ui_problems()
            if problems:
                raise ContextError("web-UI tier unavailable: " + "; ".join(problems))
            resolved = self.resolve(self.spec_for(role))
            if not resolved.trusted:
                raise SafetyError(f"web-UI credentials never reach the untrusted SUT {resolved.label}")
            credentials = self.web_credentials()
            assert credentials is not None  # web_ui_problems() checked it
            mode = WebMode(credentials=credentials, gate=self.web_gate(), browsers_path=self.web_browsers(role))
            workspace = self.workspace(f"webui-{name}", self.template_for("head"))
            cli = WebOtterdogCli(
                self.installed(role),
                workspace,
                verified=self.require_verified(),
                identity=self.require_identity("admin"),
                web=mode,
                scratch=self.scratch / "cli" / f"webui-{name}",
                artifacts_dir=self.artifacts_dir / "reset" if role == "reset" else self.artifacts_dir,
                settings=self.settings,
                http_cache=not self.options.no_http_cache,
                http_cache_root=self.scratch / HTTP_CACHE_DIR,
            )
            cli.live_check = self.check_lease_not_lost
            return cli

        return self._memo(f"web_cli:{role}:{name}", build)

    def restore_web_settings(self, baseline: BaselineManager) -> bool:
        """Session-end safety net: restore the web-only settings recorded by the web-UI tier with the trusted web CLI
        when a restore is pending; True when nothing is pending afterwards (errors are logged, never raised)."""
        if not getattr(baseline, "web_restore_pending", False):  # stand-in managers of unit tests have no web state
            return True
        try:
            cli = self.web_cli("reset", name="restore")
            baseline.restore_web_settings(cli)
        except Exception as exc:  # noqa: BLE001 - teardown: reported, the rest of the cleanup still runs
            logger.error("could not restore the web-only org settings: %s", describe_error(exc))
        if baseline.web_restore_pending:
            logger.error(
                "the web-only org settings of %s may still differ from %s: the next web-UI session on this machine "
                "restores them first (%s), or restore them in the GitHub UI (docs/web-ui-testing.md#recovery)",
                self.require_target().org,
                baseline.web_snapshot,
                self.web_snapshot_path(),
            )
            return False
        self.drop_web_snapshot()
        return True

    def web_snapshot_path(self) -> Path:
        """``<E2E_CACHE_DIR>/webui/pending-restore-<org id>.json``: original web values not restored yet (no secret)."""
        from otterdog_e2e.webui.gate import GATE_DIR

        return self.settings.cache_dir / GATE_DIR / f"pending-restore-{self.require_target().org_id}.json"

    def save_web_snapshot(self, values: Mapping[str, Any]) -> None:
        """Persist the ORIGINAL web values before the web-UI tier changes them (first record wins, survives a hard
        kill of the session: the next web session restores them first)."""
        path = self.web_snapshot_path()
        if path.exists():
            return
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        record = {
            "org": self.require_target().org,
            "org_id": self.require_target().org_id,
            "run_id": self.run_ctx.run_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "values": dict(values),
        }
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)

    def load_web_snapshot(self) -> dict[str, Any] | None:
        """The persisted pending restore of the target org ({org, org_id, run_id, recorded_at, values}), else None."""
        try:
            record = json.loads(self.web_snapshot_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        target = self.require_target()
        if not isinstance(record, dict) or record.get("org_id") != target.org_id:
            return None
        return record if isinstance(record.get("values"), dict) else None

    def drop_web_snapshot(self) -> None:
        """Forget the persisted pending restore (the original values are verified back)."""
        self.web_snapshot_path().unlink(missing_ok=True)

    def _record_web_logins(self) -> None:
        """run.json web_ui: the login gate summary of this session (when a web CLI was used)."""
        gate = self._memos.get("web_gate")
        if gate is not None:
            self.write_run_info(web_ui={**(self.run_info.get("web_ui") or {}), **gate.summary()})

    # --- webapp ---------------------------------------------------------------------------------------------------
    def config_token(self) -> str:
        """OTTERDOG_CONFIG_TOKEN: the config_reader token, else the admin token for trusted SUTs only (SEC-11)."""
        if "config_reader" in self.identities:
            return self.identities["config_reader"].token
        if self.resolve(self.options.sut).trusted:
            return self.require_identity("admin").token
        raise ContextError("untrusted SUT: the webapp tier needs a config_reader identity (E2E_CONFIG_READ_TOKEN)")

    def webapp_deployment(self) -> Deployment:
        """WebappStack (transport relay) or ExternalWebapp (transport external) of the target, not started."""
        from otterdog_e2e.webapp.stack import ExternalWebapp, WebappSettings, WebappStack

        target, verified = self.require_target(), self.require_verified()
        spec = target.webapp
        if spec.transport == "external":
            if not spec.external_url:
                raise ContextError("webapp transport 'external' needs webapp.external_url (E2E_EXTERNAL_URL)")
            return ExternalWebapp(
                spec.external_url, init_url=spec.external_init_url, allow_remote=self.options.allow_remote_webapp
            )
        if spec.transport != "relay":
            raise ContextError(f"webapp transport {spec.transport!r} cannot serve webapp tests")
        app = self.require_app_credentials()
        # the stack hands the private key to the SUT image (untrusted PR images included): re-checked at every start
        self.verify_app()
        settings = WebappSettings(
            org=target.org,
            configs_repo=target.configs_repo,
            config_token=self.config_token(),
            app=app,
            validation_context=spec.validation_context,
            sync_context=spec.sync_context,
            admin_team=target.admin_team,
            approval_team=target.approval_team,
            workers=spec.workers,
            port=spec.port,
            dtrack_mock=bool(self.extras.get("dtrack_mock")),
        )
        return WebappStack(
            settings,
            verified=verified,
            image=self.image_for("head").tag,
            run_ctx=self.run_ctx,
            scratch=self.scratch / "webapp",
            artifacts_dir=self.artifacts_dir,
        )

    def start_webapp(self, baseline: BaselineManager, template: TemplateRef) -> Deployment:
        """SPEC 15 order: stack up -> config repo main = baseline -> otterdog.json in the configs repo ->
        /internal/init -> wait_ready; records the ready time used as the relay's ``since``."""
        deployment = self.webapp_deployment()
        if _is_stack(deployment):
            deployment.up()
        try:
            baseline.push(self.config_flow(baseline))
            self.publish_otterdog_json(template)
            deployment.init()
            self._wait_ready(deployment)
        except BaseException:
            self.stop_webapp(deployment)
            raise
        self.extras["webapp_ready_at"] = datetime.now(UTC)
        self._record_webapp_version(deployment)
        return deployment

    def reload_webapp(self, deployment: Deployment) -> None:
        """/internal/init (otterdog.json, global policies and blueprints, installations) and wait until the webapp is
        ready for the org again."""
        deployment.init()
        self._wait_ready(deployment)

    def _wait_ready(self, deployment: Deployment) -> None:
        """wait_ready of a stack or an external webapp (which needs the org)."""
        if _is_stack(deployment):
            deployment.wait_ready(timeout=WEBAPP_READY_TIMEOUT)
        else:
            external = cast("ExternalWebapp", deployment)
            external.wait_ready(org=self.require_target().org, timeout=WEBAPP_READY_TIMEOUT)

    def _record_webapp_version(self, deployment: Deployment) -> None:
        """Store the version shown by the webapp in run.json (compose stacks only)."""
        if _is_stack(deployment):
            try:
                version = deployment.deployed_version()
            except Exception as exc:  # noqa: BLE001 - informational only
                logger.warning("could not read the webapp version: %s", describe_error(exc))
                return
            self.write_run_info(versions={**(self.run_info.get("versions") or {}), "webapp": version})

    def stop_webapp(self, deployment: Deployment) -> None:
        """Save the logs and stop a compose stack (external webapps are left alone)."""
        if _is_stack(deployment):
            try:
                deployment.save_logs()
            except Exception as exc:  # noqa: BLE001 - the stack must go down even without logs
                logger.warning("could not save the webapp logs: %s", describe_error(exc))
            finally:
                deployment.down()

    def publish_otterdog_json(
        self, template: TemplateRef, *, organization: Mapping[str, Sequence[str] | None] | None = None
    ) -> None:
        """Commit the webapp's otterdog.json to the configs repo (only when its content changes); ``organization``
        overrides the org entry's admin_teams / approval_teams (a list of team names or patterns; None drops the key,
        so the GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS of the webapp apply). Call it again without overrides to
        restore the run's file, and reload_webapp() to make the webapp read it."""
        from otterdog_e2e.otterdog.workspace import webapp_otterdog_json

        target = self.require_target()
        data = webapp_otterdog_json(target, template, config_repo=target.config_repo_for(self.run_ctx))
        if organization:
            entry = data["organizations"][0]
            for key, value in check_organization_overrides(organization).items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
        content = json.dumps(data, indent=2) + "\n"
        oracle = self.oracle()
        branch = oracle.default_branch(target.configs_repo) or "main"
        if oracle.file_content(target.configs_repo, "otterdog.json", ref=branch) == content:
            return
        message = f"otterdog-e2e: otterdog.json of run {self.run_ctx.run_id}"
        self.mutator("admin").commit_files(target.configs_repo, branch, {"otterdog.json": content}, message)

    def config_flow(
        self,
        baseline: BaselineManager,
        *,
        relay: DeliveryRelay | None = None,
        bot_login: str | None = None,
    ) -> ConfigRepoFlow:
        """ConfigRepoFlow on the run's org config repo, guarded by BaselineManager.guard_config_change (SEC-07)."""
        from otterdog_e2e.config_repo import ConfigRepoFlow

        target = self.require_target()
        return ConfigRepoFlow(
            org=target.org,
            repo=target.config_repo_for(self.run_ctx),
            oracle=self.oracle(),
            mutators=self.mutators(),
            run_ctx=self.run_ctx,
            validation_context=target.webapp.validation_context,
            sync_context=target.webapp.sync_context,
            guard=baseline.guard_config_change,
            bot_login=bot_login,
            relay=relay,
        )

    def start_relay(self, deployment: Deployment) -> DeliveryRelay:
        """DeliveryRelay forwarding the installation's deliveries since the webapp ready time, started."""
        from otterdog_e2e.webhooks.relay import DeliveryRelay

        relay = DeliveryRelay(
            self.app_auth(),
            forward_url=deployment.webhook_url,
            secret=self.require_app_credentials().webhook_secret,
            since=self.extras.get("webapp_ready_at") or datetime.now(UTC),
            installation_id=self.installation_id(),
            org=self.require_target().org,
            artifacts_dir=self.artifacts_dir,
            allow_remote=self.options.allow_remote_webapp,
        )
        relay.start()
        return relay

    def begin_webapp_case(self, flow: ConfigRepoFlow, api: WebappApi, baseline: BaselineManager) -> WebappCase:
        """F10 before: config repo main == baseline (reset_main otherwise), webapp quiet, comment ids snapshot."""
        text = baseline.text()
        if flow.main_config() != text:
            flow.reset_main(text, message=f"otterdog-e2e {self.run_ctx.run_id}: reset to baseline")
        org = self.require_target().org
        api.quiesce(org_id=org)
        return WebappCase(
            flow=flow,
            api=api,
            org=org,
            baseline_text=text,
            started_at=datetime.now(UTC),
            seen_comment_ids=self._open_pr_comment_ids(flow),
        )

    def _open_pr_comment_ids(self, flow: ConfigRepoFlow) -> frozenset[str]:
        """Ids of the comments on the open PRs of the config repo."""
        oracle = self.oracle()
        ids: set[str] = set()
        for pull in oracle.pulls(flow.repo):
            ids.update(str(comment.get("id")) for comment in oracle.pr_comments(flow.repo, int(pull["number"])))
        return frozenset(ids)

    def end_webapp_case(
        self, case: WebappCase, *, baseline: BaselineManager, reset_cli: OtterdogCli, org_level: bool
    ) -> None:
        """F10 after: close PRs/branches, main back to baseline, guarded ``apply -d -r <p>-*``, full reset for
        org_level tests; every step runs, failures are raised together."""

        def reset_main() -> None:
            """Restore the baseline on main when a test changed it."""
            if case.flow.main_config() != case.baseline_text:
                case.flow.reset_main(case.baseline_text, message=f"otterdog-e2e {self.run_ctx.run_id}: restore")

        steps: list[tuple[str, Callable[[], Any]]] = [
            ("close PRs and delete branches", case.flow.cleanup),
            ("reset config repo main", reset_main),
            ("remove run objects", lambda: self.remove_run_objects(baseline, reset_cli)),
        ]
        if org_level:
            steps.append(("baseline reset", baseline.reset))
        errors = []
        for what, step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - every cleanup step runs; failures are raised together
                errors.append(f"{what}: {describe_error(exc)}")
        if errors:
            raise ContextError("webapp case cleanup failed: " + "; ".join(errors))

    def remove_run_objects(self, baseline: BaselineManager, reset_cli: OtterdogCli) -> None:
        """Baseline-only config + guarded ``apply -d -r e2e-<run>-*`` with the trusted reset CLI."""
        reset_cli.workspace.write_org_config(baseline.text())
        baseline.guarded_apply(reset_cli, repo_filter=self.run_ctx.repo_filter(), delete=True)

    def dtrack_mock(self, deployment: Deployment) -> DtrackMock:
        """Client of the Dependency-Track mock of a compose stack, started (with the webapp recreated to use it) when
        the stack runs without it; ContextError for an external webapp (its DEPENDENCY_TRACK_URL is not ours)."""
        from otterdog_e2e.webapp.stack import WebappStackError

        if not _is_stack(deployment):
            raise ContextError("the Dependency-Track mock needs the compose webapp stack (webapp transport relay)")
        try:
            return deployment.dtrack() if deployment.dtrack_enabled else deployment.enable_dtrack_mock()
        except WebappStackError as exc:
            raise ContextError(f"Dependency-Track mock unavailable: {describe_error(exc)}") from exc

    def blueprint_helper(self, case: WebappCase, *, relay: DeliveryRelay | None = None) -> BlueprintHelper:
        """BlueprintHelper of a webapp case: org config repo of the run, the configs repo, the admin Mutator, the
        case's flow and API, the relay, the larger-runner capability (billing guard) and the purgeable runs."""
        from otterdog_e2e.blueprints import BlueprintHelper
        from otterdog_e2e.capabilities import Cap

        target = self.require_target()
        return BlueprintHelper(
            org=target.org,
            configs_repo=target.configs_repo,
            config_repo=target.config_repo_for(self.run_ctx),
            run_ctx=self.run_ctx,
            oracle=self.oracle(),
            mutator=self.mutator("admin"),
            api=case.api,
            flow=case.flow,
            relay=relay,
            larger_runners=self.require_capabilities().has(Cap.LARGER_RUNNERS),
            purgeable=self.purgeable,
        )

    # --- scenario variables ---------------------------------------------------------------------------------------
    def scenario_variables(self) -> dict[str, Any]:
        """Jinja variables of live scenarios (SPEC 12.1 (8)); logins are the DECLARED ones (F8)."""
        target, verified = self.require_target(), self.require_verified()
        return {
            **self.run_ctx.template_vars(),
            "org": target.org,
            "plan": verified.plan,
            "logins": {name: spec.login for name, spec in target.identities.items() if spec.login},
            "app_slug": self._app_slug(),
            "app_id": self._app_id(),
            "teams": {
                "admin": target.admin_team,
                "approval": target.approval_team,
                "contributors": target.contributors_team,
            },
        }

    def _app_slug(self) -> str:
        """Declared App slug (target or credentials), empty when unknown."""
        target = self.require_target()
        if target.app is not None and target.app.slug:
            return target.app.slug
        try:
            credentials = self.app_credentials()
        except Exception as exc:  # noqa: BLE001 - a broken App config must not break CLI scenarios
            logger.info("App credentials unavailable: %s", describe_error(exc))
            return ""
        return (credentials.slug or "") if credentials is not None else ""

    def _app_id(self) -> str:
        """Id of the e2e App (app-bound status checks ``<id>:<context>``, Integration bypass actors), "" when no App
        is configured."""
        try:
            credentials = self.app_credentials()
        except Exception as exc:  # noqa: BLE001 - a broken App config must not break CLI scenarios
            logger.info("App credentials unavailable: %s", describe_error(exc))
            return ""
        return str(credentials.app_id or "") if credentials is not None else ""

    def offline_variables(self) -> dict[str, Any]:
        """Jinja variables of offline scenarios: the offline org, plan free, default team names, no logins."""
        from otterdog_e2e.scenarios.offline import OFFLINE_DEFAULT_PLAN, OFFLINE_ORG

        return {
            **self.run_ctx.template_vars(),
            "org": OFFLINE_ORG,
            "plan": OFFLINE_DEFAULT_PLAN,
            "logins": {},
            "app_slug": "",
            "app_id": "",
            "teams": dict(DEFAULT_TEAMS),
        }

    # --- reporting --------------------------------------------------------------------------------------------------
    def write_run_info(self, **fields: Any) -> None:
        """Merge ``fields`` into run.json (redacted) when the artifacts dir exists."""
        self.run_info.update(fields)
        if self.artifacts_dir.is_dir():
            text = json.dumps(self.run_info, indent=2, sort_keys=True, default=str)
            (self.artifacts_dir / RUN_FILE).write_text(REDACTOR(text) + "\n", encoding="utf-8")

    def append_result(self, line: Mapping[str, Any]) -> None:
        """Append one redacted line to results.jsonl."""
        if not self.artifacts_dir.is_dir():
            return
        with (self.artifacts_dir / RESULTS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(REDACTOR(json.dumps(line, sort_keys=True, default=str)) + "\n")

    def rate_remaining(self) -> dict[str, int]:
        """Lowest core x-ratelimit-remaining seen per identity (from the clients' last responses)."""
        rates: dict[str, int] = {}
        for (name, _mode), http in self._http.items():
            core = (http.rate_snapshot() or {}).get("core") or {}
            remaining = core.get("remaining") if isinstance(core, Mapping) else None
            if remaining is None:
                continue
            rates[name] = min(int(remaining), rates.get(name, int(remaining)))
        return rates

    def min_rate_threshold(self) -> int:
        """E2E_MIN_RATE_REMAINING (default MIN_RATE_REMAINING)."""
        return int(self.environ.get(MIN_RATE_ENV) or MIN_RATE_REMAINING)

    def known_bugs(self) -> dict[str, KnownBug]:
        """scenarios/known_bugs.yaml keyed by id (empty when the file does not exist)."""

        def build() -> dict[str, KnownBug]:
            """Load the file."""
            path = self.settings.scenarios_dir / KNOWN_BUGS_FILE
            if not path.is_file():
                return {}
            from otterdog_e2e import known_bugs

            return dict(known_bugs.load(path))

        return self._memo("known_bugs", build)

    def pr_manifest(self) -> PrManifest | None:
        """The --e2e-pr-manifest PrManifest (None when not given)."""

        def build() -> PrManifest | None:
            """Load the manifest."""
            if self.options.pr_manifest is None:
                return None
            from otterdog_e2e import differential

            return differential.load_pr_manifest(self.options.pr_manifest)

        return self._memo("pr_manifest", build)


ORGANIZATION_OVERRIDES = frozenset({"admin_teams", "approval_teams"})  # keys of publish_otterdog_json(organization=)


def check_organization_overrides(overrides: Mapping[str, Any]) -> dict[str, list[str] | None]:
    """Validated otterdog.json org-entry overrides: ORGANIZATION_OVERRIDES keys, lists of non-empty strings or None
    (ValueError)."""
    checked: dict[str, list[str] | None] = {}
    for key, value in overrides.items():
        if key not in ORGANIZATION_OVERRIDES:
            raise ValueError(
                f"otterdog.json key {key!r} cannot be overridden (allowed: {sorted(ORGANIZATION_OVERRIDES)})"
            )
        if value is None:
            checked[key] = None
            continue
        if isinstance(value, str) or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"{key} must be a list of team names or patterns, got {value!r}")
        checked[key] = list(value)
    return checked


def _is_stack(deployment: Any) -> TypeGuard[WebappStack]:
    """True for a compose WebappStack (it can be stopped), False for an ExternalWebapp (duck-typed for fakes)."""
    return hasattr(deployment, "down")


E2E_CONTEXT_KEY: pytest.StashKey[E2EContext] = pytest.StashKey[E2EContext]()


def get_context(config: pytest.Config) -> E2EContext:
    """The session's E2EContext (created on first use: settings, run context, scratch and artifacts dirs)."""
    context = config.stash.get(E2E_CONTEXT_KEY, None)
    if context is None:
        context = E2EContext.create(E2EOptions.from_config(config))
        try:
            context.start_session(argv=[REDACTOR(str(arg)) for arg in config.invocation_params.args])
        except ContextError as exc:  # e.g. the run id is used by another session of this machine
            raise pytest.UsageError(str(exc)) from None
        config.stash[E2E_CONTEXT_KEY] = context
    return context


def peek_context(config: pytest.Config) -> E2EContext | None:
    """The session's E2EContext if one was created (never creates it)."""
    return config.stash.get(E2E_CONTEXT_KEY, None)
