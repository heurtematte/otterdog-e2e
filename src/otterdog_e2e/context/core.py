"""E2EContext (SPEC 15, F3): the composition root, assembled from the facets of the session context.

E2EContext adds the life cycle of a session to the facets (live, SUT, web UI, webapp, run data): create() (settings,
run context, scratch and artifacts dirs; no GitHub access), start_session() (scratch lock, log redaction, scratch HOME,
run-scoped container names, run.json, an atexit close), ensure_live() at the first live item (target, verification,
capability probes, org lease, built once: a failure is kept in live_error) and close() (finalizers, lease release,
untrusted sources deleted, artifacts scrubbed, scratch dropped).
"""

from __future__ import annotations

import atexit
import dataclasses
import logging
import os
import shutil
from collections.abc import Callable, MutableMapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from otterdog_e2e import __version__
from otterdog_e2e.context.helpers import describe_error, lock_held
from otterdog_e2e.context.rundata import RunDataFacet
from otterdog_e2e.context.state import HTTP_CACHE_DIR, ContextError, E2EOptions
from otterdog_e2e.context.webapp import WebappFacet
from otterdog_e2e.context.webui import WebUiFacet
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.capabilities import Capabilities
    from otterdog_e2e.settings import HarnessSettings

logger = logging.getLogger(__name__)

LANE_ENV = "E2E_LANE"  # pr-fast | nightly-full (recorded in run.json)
INVOCATION_ENV = "E2E_INVOCATION"  # set by `otterdog-e2e run|pr`: the harness command recorded as run.json command


class E2EContext(WebUiFacet, WebappFacet, RunDataFacet):
    """Everything the gating hooks, session fixtures and harness commands share; live fields stay None until
    ensure_live() (or the explicit load_target/verify/probe/acquire_lease steps of a command)."""

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
