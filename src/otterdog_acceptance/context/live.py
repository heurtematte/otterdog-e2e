"""Live facet of the session context (SPEC 5.1, SPEC 15): what a session needs on GitHub.

LiveFacet loads the target and its identities, runs verify_target (the VerifiedOrg every mutation path requires) and
the App checks (verify_app, installation preflight), and builds the GitHub clients of the identities: read-only, or
write-scoped to the verified org and refusing writes once the org lease of the session is lost. It acquires the org
lease (heartbeat, takeover of dead runs), reads the ledger and the active runs, and builds the janitor of purgeable
runs.
"""

from __future__ import annotations

import itertools
import logging
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from otterdog_acceptance.context.helpers import (
    describe_error,
    installation_problems,
    lease_holder,
    parse_time,
    target_env_name,
)
from otterdog_acceptance.context.state import ContextError, ContextState

if TYPE_CHECKING:
    from otterdog_acceptance.github.app import AppAuth
    from otterdog_acceptance.github.http import GitHubHttp
    from otterdog_acceptance.github.janitor import Janitor, JanitorItem
    from otterdog_acceptance.github.lease import OrgLease
    from otterdog_acceptance.github.mutate import Mutator
    from otterdog_acceptance.github.oracle import Oracle
    from otterdog_acceptance.ratewait import CoreBudget
    from otterdog_acceptance.safety import AppIsolation, VerifiedOrg
    from otterdog_acceptance.settings import AppCredentials, Target

logger = logging.getLogger(__name__)

LEASE_WAIT_ENV = "E2E_LEASE_WAIT"  # seconds to wait for a busy org lease (default 0: fail fast)
MIN_RATE_REMAINING = 800  # E2E_MIN_RATE_REMAINING: live items pause (or are skipped) below this core budget
MIN_RATE_ENV = "E2E_MIN_RATE_REMAINING"
RATE_READ_MAX_AGE = 30.0  # seconds a GET /rate_limit serves the gates of the next live items
MUTATOR_IDENTITIES = ("admin", "author", "approver", "outsider")


class LiveFacet(ContextState):
    """Target, verification, App checks, GitHub clients and org lease of a session (live fields stay None until they
    are built)."""

    # --- live state, target and verification ----------------------------------------------------------------------
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

    def shard_name(self) -> str | None:
        """The shard of the target (E2E_SHARD of the environment or of the target's env files, shards.py), None without
        a target or a shard: every live item runs. TargetError for a malformed target name."""
        from otterdog_acceptance.settings import load_env_files
        from otterdog_acceptance.shards import SHARD_ENV

        if not self.options.target:
            return None
        load_env_files(target_env_name(self.options.target), self.settings.project_root, self.environ)
        return (self.environ.get(SHARD_ENV) or "").strip() or None

    def load_target(self) -> Target:
        """Load the env files, the target and its identities (no GitHub access); TargetError when invalid."""
        if self.target is not None:
            return self.target
        from otterdog_acceptance.settings import TargetError, load_env_files, load_target, resolve_identities

        if not self.options.target:
            raise TargetError("no target: pass --e2e-target (or set E2E_TARGET)")
        load_env_files(target_env_name(self.options.target), self.settings.project_root, self.environ)
        target = load_target(self.options.target, self.settings, self.environ)
        self.identities = resolve_identities(target, self.environ)
        self.target = target
        return target

    def verify(self, *, require_marker: bool = True, check_identities: bool = True) -> VerifiedOrg:
        """verify_target with the admin token (SPEC 5.1): the VerifiedOrg every mutation path requires."""
        from otterdog_acceptance.safety import verify_target

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

    def check_app(self) -> tuple[bool, str]:
        """(ready, reason): App credentials present, owned by the test org and installed on test orgs only
        (verify_app), installed on the org for all repositories and not suspended. An App that fails verify_app
        also sets ``extras["app_unsafe"]``: the webapp gate then fails its items instead of skipping them."""
        from otterdog_acceptance.safety import SafetyError

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
            from otterdog_acceptance.github.http import GitHubHttp

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
        from otterdog_acceptance.safety import SafetyError

        lease = self.lease
        if lease is not None and not lease.held:
            raise SafetyError(
                f"the org lease of run {self.run_ctx.run_id} was lost (taken over or deleted): refusing further writes"
            )

    # --- rate budgets ----------------------------------------------------------------------------------------------
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

    def rate_wait_max(self) -> float:
        """E2E_RATE_WAIT_MAX (default 3600 s): the longest pause for the rate limit of one item or command; 0 disables
        the pauses (ContextError when it is not a number)."""
        from otterdog_acceptance.ratewait import DEFAULT_RATE_WAIT_MAX, RATE_WAIT_ENV

        raw = (self.environ.get(RATE_WAIT_ENV) or "").strip()
        try:
            return max(float(raw), 0.0) if raw else DEFAULT_RATE_WAIT_MAX
        except ValueError:
            raise ContextError(f"{RATE_WAIT_ENV} must be a number of seconds, got {raw!r}") from None

    def rate_budgets(self, *, max_age: float = 0.0) -> dict[str, CoreBudget]:
        """Core budgets of the identities this session talks to: GET /rate_limit (free), else the last headers seen;
        a read younger than ``max_age`` seconds is reused (the gates of consecutive items)."""
        from otterdog_acceptance.ratewait import CoreBudget, core_budget

        cached = self.extras.get("rate_budgets")
        if max_age > 0 and cached is not None and time.monotonic() - cached[0] < max_age:
            return dict(cached[1])
        budgets: dict[str, CoreBudget] = {}
        for name in sorted({name for name, _mode in self._http}):
            http = self.http(name)
            budget = None
            try:
                budget = core_budget(http.rate_limit())
            except Exception as exc:  # noqa: BLE001 - the last headers seen stand in for an unreadable budget
                logger.warning("GET /rate_limit (%s) failed: %s", name, describe_error(exc))
            if budget is None:
                core = (http.rate_snapshot() or {}).get("core") or {}
                remaining, reset = core.get("remaining"), core.get("reset")
                if isinstance(remaining, int):
                    budget = CoreBudget(remaining, float(reset) if isinstance(reset, int) else None)
            if budget is not None:
                budgets[name] = budget
        self.extras["rate_budgets"] = (time.monotonic(), dict(budgets))
        return budgets

    def pause_for_rate_limit(self, what: str, *, after_limit: bool = False) -> str | None:
        """Pause while an identity's core budget is below E2E_MIN_RATE_REMAINING, until its reset
        (ratewait.pause_for_rate_limit, at most E2E_RATE_WAIT_MAX seconds); None when ``what`` (an item, a command)
        may go on, else the reason it gave up. ``after_limit``: a command just hit a limit (OtterdogCli.rate_pause).
        Every pause is logged, written to the terminal (extras["notify"]) and recorded in run.json (rate_pauses)."""
        from otterdog_acceptance import ratewait

        def announce(pause: ratewait.RatePause) -> None:
            """Log, terminal line and run.json record of one pause."""
            line = pause.describe()
            logger.warning("%s", line)
            notify = self.extras.get("notify")
            if callable(notify):
                notify(f"otterdog-acceptance: {line}")
            record = {
                "what": pause.what,
                "seconds": round(pause.seconds),
                "low": dict(pause.low),
                "at": datetime.now(UTC).isoformat(timespec="seconds"),
            }
            self.write_run_info(rate_pauses=[*(self.run_info.get("rate_pauses") or []), record])

        reads = itertools.count()

        def read() -> dict[str, CoreBudget]:
            """The first read of an item's gate may reuse a recent one; a command that hit a limit and every read
            after a pause read GitHub again."""
            first = next(reads) == 0
            return self.rate_budgets(max_age=RATE_READ_MAX_AGE if first and not after_limit else 0.0)

        return ratewait.pause_for_rate_limit(
            what,
            read,
            threshold=self.min_rate_threshold(),
            max_wait=self.rate_wait_max(),
            after_limit=after_limit,
            on_pause=announce,
            sleep=lambda seconds: ratewait.pause_sleep(seconds),
        )

    def rate_pause_after_limit(self, what: str) -> str | None:
        """OtterdogCli.rate_pause: the pause of a live command that hit a rate limit, before it runs again."""
        return self.pause_for_rate_limit(what, after_limit=True)

    def public_http(self) -> GitHubHttp:
        """Anonymous read-only client for public upstream reads (SUT resolution)."""

        def build() -> GitHubHttp:
            """Create the anonymous client."""
            from otterdog_acceptance.github.http import GitHubHttp

            return GitHubHttp(None, read_only=True, identity="anonymous")

        return self._memo("public_http", build)

    def oracle(self) -> Oracle:
        """Read-only Oracle of the test org (the oracle identity; the admin client when it falls back to admin)."""

        def build() -> Oracle:
            """Create the oracle."""
            from otterdog_acceptance.github.oracle import Oracle

            oracle, admin = self.identities.get("oracle"), self.identities.get("admin")
            separate = oracle is not None and (admin is None or oracle.token != admin.token)
            return Oracle(self.http("oracle" if separate else "admin"), self.require_target().org)

        return self._memo("oracle", build)

    def mutator(self, name: str = "admin") -> Mutator:
        """Write-scoped Mutator of an identity (requires the VerifiedOrg)."""

        def build() -> Mutator:
            """Create the mutator."""
            from otterdog_acceptance.github.mutate import Mutator

            return Mutator(self.http(name, write=True), self.require_verified())

        return self._memo(f"mutator:{name}", build)

    def mutators(self) -> dict[str, Mutator]:
        """Mutators of every configured identity able to act on PRs (admin, author, approver, outsider)."""
        return {name: self.mutator(name) for name in MUTATOR_IDENTITIES if name in self.identities}

    def app_credentials(self) -> AppCredentials | None:
        """App credentials of the target (None when not configured)."""

        def build() -> AppCredentials | None:
            """Resolve the credentials from the environment."""
            from otterdog_acceptance.settings import resolve_app_credentials

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
            from otterdog_acceptance.github.app import AppAuth

            return AppAuth(self.require_app_credentials())

        return self._memo("app_auth", build)

    def verify_app(self) -> AppIsolation:
        """safety.verify_app of the e2e App against the target (never cached: GET /app and GET /app/installations
        are read again on every call); SafetyError when the App could reach a non-test organization."""
        from otterdog_acceptance.safety import verify_app

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
            from otterdog_acceptance.github.lease import OrgLease

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
        from otterdog_acceptance.github.janitor import Janitor

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
