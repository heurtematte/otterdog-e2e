"""GitHub-side mutual exclusion per org and the run ledger (SPEC 5.3).

The lease is the ref ``refs/heads/e2e-lease`` in ``target.configs_repo`` pointing at a commit whose message is JSON
``{"run_id", "holder", "expires_at"}`` (plus ``"refs"``: template tags in use, see reference()); creating a ref is
atomic (422 = held). The ledger is one tag ``refs/tags/e2e-run/<run_id>`` per run, pointing at the run's lease commit.
Git refs are not managed by otterdog, so ``apply -d`` never deletes them.

Renewals and steals are compare-and-swap updates: the new lease commit is a child of the commit the ref is expected to
point at and the ref is PATCHed with ``force: false``, so GitHub rejects the update (fast-forward check) when another
session moved the ref meanwhile. A failed renewal marks the lease as lost (``held`` becomes False).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.naming import RUN_ID_RE
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext

logger = logging.getLogger(__name__)

LEASE_BRANCH = "e2e-lease"
LEASE_REF = f"heads/{LEASE_BRANCH}"
LEDGER_PREFIX = "tags/e2e-run/"
DEFAULT_TTL = timedelta(hours=3)
HEARTBEAT_INTERVAL = 600.0
# janitor --run-id: a lease renewed less than this ago belongs to a session that is probably still running (DESTR-05)
LIVE_RENEWAL_WINDOW = timedelta(seconds=2 * HEARTBEAT_INTERVAL)
WAIT_POLL_INTERVAL = 30.0  # acquire(wait=...) re-checks a busy lease every 30 s
BASE_COMMIT_TIMEOUT = 30.0  # a just auto-initialized lease repository answers 404/409 for a few seconds (F3)
BASE_COMMIT_INTERVAL = 3.0
ACQUIRE_ATTEMPTS = 3  # the lease ref may vanish between the 422 and the holder read
UNPARSEABLE_HOLDER = "<unparseable lease record>"


def format_time(value: datetime) -> str:
    """ISO-8601 UTC timestamp with a ``Z`` suffix (second precision)."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_time(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp as aware UTC (naive values are taken as UTC); None when malformed."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _ref_exists_error(exc: GitHubError) -> bool:
    """True for the 422 of POST git/refs on an existing ref (not e.g. a repository rule violation)."""
    return exc.status == 422 and "already exists" in exc.body.lower()


def record_expired(record: Mapping[str, Any], now: datetime) -> bool:
    """True when a lease record's expires_at is in the past (or unreadable)."""
    expires = parse_time(record.get("expires_at"))
    return expires is None or expires <= now


class LeaseBusy(RuntimeError):  # noqa: N818 - name fixed by SPEC 5.3
    """The org lease is held by another unexpired holder."""

    def __init__(self, holder: dict[str, Any], message: str | None = None) -> None:
        """Keep the current holder record ({run_id, holder, expires_at})."""
        self.holder = holder
        super().__init__(message or f"org lease held by {holder.get('holder')!r} (run {holder.get('run_id')!r})")


@dataclass(frozen=True)
class _Takeover:
    """janitor --run-id: whose unexpired lease acquire() may replace, and on which evidence."""

    run_id: str
    force: bool = False
    trusted_holder: str | None = None


class OrgLease:
    """Acquire, renew and release the org lease; register and list ledger runs.

    ``clock`` (aware UTC now) and ``sleep`` are attributes so tests can replace them.
    """

    def __init__(
        self,
        mutator: Mutator,
        oracle: Oracle,
        *,
        repo: str,
        run_ctx: RunContext,
        holder: str,
        ttl: timedelta = DEFAULT_TTL,
    ) -> None:
        """Bind the lease to ``repo`` (target.configs_repo) for this run."""
        self.mutator = mutator
        self.oracle = oracle
        self.repo = repo
        self.run_ctx = run_ctx
        self.holder = holder
        self.ttl = ttl
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.sleep: Callable[[float], None] = time.sleep
        self.refs: list[str] = []
        self.lost = False
        self._lease_sha: str | None = None
        self._tree_sha: str | None = None
        self._record: dict[str, Any] | None = None
        self._ledger_registered = False
        self._lock = threading.RLock()
        self._stop: threading.Event | None = None
        self._thread: threading.Thread | None = None

    # --- state --------------------------------------------------------------------------------------------------
    @property
    def held(self) -> bool:
        """True while this session holds the lease (False after release() or a lost renewal)."""
        return self._lease_sha is not None and not self.lost

    @property
    def record(self) -> dict[str, Any] | None:
        """Our current lease record (None when not held)."""
        return dict(self._record) if self._record is not None and self.held else None

    def is_expired(self, record: dict[str, Any], now: datetime | None = None) -> bool:
        """True when a lease record's expires_at is in the past (or unreadable)."""
        return record_expired(record, now or self.clock())

    def _new_record(self) -> dict[str, Any]:
        """A fresh record for this run, expiring ``ttl`` from now."""
        record: dict[str, Any] = {
            "run_id": self.run_ctx.run_id,
            "holder": self.holder,
            "expires_at": format_time(self.clock() + self.ttl),
        }
        if self.refs:
            record["refs"] = sorted(set(self.refs))
        return record

    @staticmethod
    def _message(record: dict[str, Any]) -> str:
        """Commit message of a lease commit (the JSON record)."""
        return json.dumps(record, sort_keys=True)

    def _parse_record(self, commit: dict[str, Any]) -> dict[str, Any]:
        """Lease record of a commit; unparseable messages expire ``ttl`` after the commit date."""
        try:
            record = json.loads(str(commit.get("message", "")).strip())
        except ValueError:
            record = None
        if isinstance(record, dict) and parse_time(record.get("expires_at")) is not None:
            return record
        committed = parse_time((commit.get("committer") or {}).get("date"))
        expires = format_time(committed + self.ttl) if committed is not None else None
        return {"run_id": None, "holder": UNPARSEABLE_HOLDER, "expires_at": expires}

    def _current(self) -> tuple[str, dict[str, Any]] | None:
        """(sha, record) the lease ref points at, or None when the lease is free."""
        current = self._current_commit()
        return (current[0], current[1]) if current is not None else None

    def _current_commit(self) -> tuple[str, dict[str, Any], datetime | None] | None:
        """(sha, record, committer date = last acquisition or renewal) of the lease ref, None when it is free."""
        sha = self.oracle.branch_sha(self.repo, LEASE_BRANCH)
        if sha is None:
            return None
        commit = self.oracle.git_commit(self.repo, sha) or {}
        return sha, self._parse_record(commit), parse_time((commit.get("committer") or {}).get("date"))

    def _base_commit(self) -> tuple[str, str]:
        """(sha, tree sha) of the head of the lease repo's default branch; retried for BASE_COMMIT_TIMEOUT seconds
        while the repository has no readable head yet (bootstrap creates it with auto_init right before taking the
        lease: GitHub answers 404/409 until the initial commit is written)."""
        waited = 0.0
        while True:
            branch = self.oracle.default_branch(self.repo)
            sha = self.oracle.branch_sha(self.repo, branch) if branch else None
            commit = self.oracle.git_commit(self.repo, sha) if sha else None
            if commit:
                return sha or "", str(commit["tree"]["sha"])
            if waited >= BASE_COMMIT_TIMEOUT:
                raise RuntimeError(
                    f"lease repository {self.mutator.org}/{self.repo} has no readable default branch head after "
                    f"{waited:g} s: create it (otterdog-e2e bootstrap --apply) or check that it is initialized"
                )
            logger.info("lease repository %s has no readable head yet, retrying", self.repo)
            self.sleep(BASE_COMMIT_INTERVAL)
            waited += BASE_COMMIT_INTERVAL

    def _commit(self, tree_sha: str, parent: str, record: dict[str, Any]) -> str:
        """Create a lease commit carrying ``record``."""
        return self.mutator.create_commit(self.repo, tree_sha=tree_sha, parents=[parent], message=self._message(record))

    def _set_held(self, sha: str, tree_sha: str, record: dict[str, Any]) -> None:
        """Remember that we hold the lease on ``sha``."""
        with self._lock:
            self._lease_sha, self._tree_sha, self._record = sha, tree_sha, record
            self.lost = False

    # --- acquire / renew / release ------------------------------------------------------------------------------
    def acquire(
        self,
        *,
        wait: float = 0,
        steal_expired: bool = True,
        takeover_run: str | None = None,
        force_takeover: bool = False,
        trusted_holder: str | None = None,
    ) -> None:
        """Create refs/heads/e2e-lease on our lease commit (steal it when expired) and register the ledger tag.

        422 => held: read the holder; if expired and steal_expired, move the ref to our commit (a child of the expired
        lease commit, PATCH force=false: a compare-and-swap that loses against a concurrent stealer); else re-check
        every 30 s for up to ``wait`` seconds, then raise LeaseBusy. refs/tags/e2e-run/<run_id> must not already
        exist (SafetyError raised before the lease is touched; a concurrent registration releases the lease again).
        A lease held by another session is never taken over while it is unexpired, even when it names the same run id
        and holder (another session reusing the run id): only this object's own lease commit counts as ours.

        ``takeover_run`` (janitor --run-id): an unexpired lease of that run is taken over with the same compare-and-
        swap update (never a DELETE: a session that acquired the lease meanwhile keeps it) when the run looks dead:
        its last renewal is older than LIVE_RENEWAL_WINDOW (the heartbeat renews every 10 minutes), or its holder is
        ``trusted_holder`` (the CI job of the janitor itself), or ``force_takeover``; LeaseBusy otherwise (DESTR-05).
        """
        if self.mutator.dry_run:
            raise SafetyError("the org lease cannot be held with a dry-run mutator")
        if self.held:
            return
        if not self._ledger_registered and self.in_ledger(
            self.run_ctx.run_id
        ):  # before the lease is touched (DESTR-03)
            raise SafetyError(
                f"run id {self.run_ctx.run_id} is already registered in the ledger: a run id serves one session only"
            )
        budget = max(0.0, float(wait))
        takeover = _Takeover(takeover_run, force_takeover, trusted_holder) if takeover_run else None
        while True:
            try:
                self._acquire_once(steal_expired=steal_expired, takeover=takeover)
                break
            except LeaseBusy:
                if budget <= 0:
                    raise
                delay = min(WAIT_POLL_INTERVAL, budget)
                logger.info("org lease busy, re-checking in %.0f s", delay)
                self.sleep(delay)
                budget -= delay
        try:
            self._register_ledger()
        except BaseException:
            self.release()
            raise
        logger.info("acquired the org lease of %s/%s for run %s", self.mutator.org, self.repo, self.run_ctx.run_id)

    def _acquire_once(self, *, steal_expired: bool, takeover: _Takeover | None = None) -> None:
        """One acquisition attempt (LeaseBusy when another unexpired holder has it)."""
        base, tree = self._base_commit()
        for _ in range(ACQUIRE_ATTEMPTS):
            record = self._new_record()
            commit = self._commit(tree, base, record)
            try:
                self.mutator.create_ref(self.repo, f"refs/{LEASE_REF}", commit)
            except GitHubError as exc:
                if not _ref_exists_error(exc):
                    raise
            else:
                self._set_held(commit, tree, record)
                return
            current = self._current_commit()
            if current is not None:
                self._take_over(current, tree, steal_expired=steal_expired, takeover=takeover)
                return
        raise LeaseBusy({}, f"the lease ref of {self.mutator.org}/{self.repo} keeps changing")

    def _take_over(
        self,
        current: tuple[str, dict[str, Any], datetime | None],
        tree: str,
        *,
        steal_expired: bool,
        takeover: _Takeover | None = None,
    ) -> None:
        """Steal an expired (or our own stale) lease, or the lease of a dead ``takeover`` run, with a compare-and-swap
        update, else raise LeaseBusy."""
        sha, holder, renewed_at = current
        ours = self._lease_sha is not None and sha == self._lease_sha  # this object's own lease commit only
        expired = self.is_expired(holder)
        taken = takeover is not None and not ours and not expired and holder.get("run_id") == takeover.run_id
        if taken:
            assert takeover is not None
            self._check_takeover(takeover, holder, renewed_at)
        elif not ours and not expired:
            if holder.get("run_id") == self.run_ctx.run_id:
                raise LeaseBusy(holder, f"org lease held by another session of run {self.run_ctx.run_id!r}")
            raise LeaseBusy(holder)
        if not ours and not taken and not steal_expired:
            raise LeaseBusy(holder, f"org lease of {holder.get('holder')!r} expired but stealing is disabled")
        record = self._new_record()
        commit = self._commit(tree, sha, record)
        try:
            self.mutator.update_ref(self.repo, LEASE_REF, commit, force=False)
        except GitHubError as exc:
            if exc.status not in (409, 422):
                raise
            raise LeaseBusy(self.holder_record() or holder, "lost the race for an expired org lease") from exc
        if taken:
            logger.warning("took over the org lease of run %r (%r)", holder.get("run_id"), holder.get("holder"))
        elif not ours:
            logger.warning("stole the expired org lease of %r (run %r)", holder.get("holder"), holder.get("run_id"))
        self._set_held(commit, tree, record)

    def _check_takeover(self, takeover: _Takeover, holder: Mapping[str, Any], renewed_at: datetime | None) -> None:
        """LeaseBusy unless the unexpired lease of ``takeover.run_id`` belongs to a session that looks dead."""
        if takeover.force:
            return
        if takeover.trusted_holder and holder.get("holder") == takeover.trusted_holder:
            return  # the CI job of this janitor: its session step is over
        age = self.clock() - renewed_at if renewed_at is not None else None
        if age is not None and age >= LIVE_RENEWAL_WINDOW:
            return
        when = f"{int(age.total_seconds())} s ago" if age is not None else "at an unknown time"
        raise LeaseBusy(
            dict(holder),
            f"run {takeover.run_id!r} ({holder.get('holder')!r}) renewed the org lease {when}: it may still be "
            f"running; stop it, wait until the lease expires ({holder.get('expires_at')}) or pass --force-takeover",
        )

    def _register_ledger(self) -> None:
        """Create refs/tags/e2e-run/<run_id> (SafetyError when the run id is already in the ledger)."""
        if self._ledger_registered or self._lease_sha is None:
            return
        try:
            self.mutator.create_ref(self.repo, f"refs/{LEDGER_PREFIX}{self.run_ctx.run_id}", self._lease_sha)
        except GitHubError as exc:
            if _ref_exists_error(exc):
                raise SafetyError(f"run id {self.run_ctx.run_id} is already registered in the ledger") from exc
            raise
        self._ledger_registered = True

    def renew(self) -> None:
        """New lease commit with an extended expires_at; the fast-forward PATCH only succeeds while we hold the lease.

        The new commit is a child of our current lease commit, so a lease taken over meanwhile rejects the update:
        LeaseBusy is raised and the lease is marked lost.
        """
        with self._lock:
            if not self.held or self._lease_sha is None or self._tree_sha is None:
                raise LeaseBusy(self.holder_record() or {}, "the org lease is not held by this session")
            record = self._new_record()
            commit = self._commit(self._tree_sha, self._lease_sha, record)
            try:
                self.mutator.update_ref(self.repo, LEASE_REF, commit, force=False)
            except GitHubError as exc:
                if exc.status not in (404, 409, 422):
                    raise
                self.lost = True
                logger.error("the org lease of run %s was lost", self.run_ctx.run_id)
                raise LeaseBusy(self.holder_record() or {}, "the org lease was taken over or deleted") from exc
            self._lease_sha, self._record = commit, record

    def release(self) -> None:
        """DELETE refs/heads/e2e-lease if we hold it."""
        self.stop_heartbeat()
        with self._lock:
            if not self.held:
                self._lease_sha = None
                return
            try:
                current = self._current()
                if current is not None and current[0] == self._lease_sha:
                    self.mutator.delete_ref(self.repo, LEASE_REF)
                    logger.info("released the org lease of %s/%s", self.mutator.org, self.repo)
                else:
                    logger.warning("the org lease is no longer ours; leaving it in place")
            finally:
                self._lease_sha, self._record = None, None

    # --- ledger -------------------------------------------------------------------------------------------------
    def in_ledger(self, run_id: str) -> bool:
        """True when refs/tags/e2e-run/<run_id> exists."""
        ref = f"refs/{LEDGER_PREFIX}{run_id}"
        return any(item.get("ref") == ref for item in self.oracle.matching_refs(self.repo, f"{LEDGER_PREFIX}{run_id}"))

    def ledger(self) -> list[str]:
        """Run ids of GET /repos/{org}/{repo}/git/matching-refs/tags/e2e-run/."""
        prefix = f"refs/{LEDGER_PREFIX}"
        names = (
            str(ref.get("ref", "")).removeprefix(prefix) for ref in self.oracle.matching_refs(self.repo, LEDGER_PREFIX)
        )
        return sorted({name for name in names if RUN_ID_RE.match(name)})

    def holder_record(self) -> dict[str, Any] | None:
        """Current lease record ({run_id, holder, expires_at}) or None when the lease is free."""
        current = self._current()
        return current[1] if current is not None else None

    def purgeable_fn(self) -> Callable[[str], bool]:
        """Snapshot of SPEC 9.5 ``purgeable``: run id in the ledger and not an unexpired foreign holder's run id."""
        ledger = set(self.ledger())
        holder = self.holder_record()
        active = holder.get("run_id") if holder is not None and not self.is_expired(holder) else None
        own = self.run_ctx.run_id

        def purgeable(run_id: str) -> bool:
            """True when the janitor/reset may delete objects of ``run_id``."""
            return run_id in ledger and (run_id == own or run_id != active)

        return purgeable

    def reference(self, *refs: str) -> None:
        """Record refs (e.g. ``tags/sut-<label>-<hash>``) used by this session, so the janitor keeps them."""
        self.refs.extend(ref.removeprefix("refs/") for ref in refs)
        if self.held:
            self.renew()

    # --- heartbeat ----------------------------------------------------------------------------------------------
    def start_heartbeat(self, interval: float = HEARTBEAT_INTERVAL) -> None:
        """Renew the lease every ``interval`` seconds from a daemon thread."""
        if self._thread is not None and self._thread.is_alive():
            return
        stop = threading.Event()

        def beat() -> None:
            """Renew until stopped or the lease is lost."""
            while not stop.wait(interval):
                try:
                    self.renew()
                except LeaseBusy:
                    logger.exception("org lease heartbeat stopped")
                    return
                except Exception:
                    logger.warning("org lease renewal failed; retrying at the next heartbeat", exc_info=True)

        self._stop = stop
        self._thread = threading.Thread(target=beat, name=f"e2e-lease-{self.run_ctx.run_id}", daemon=True)
        self._thread.start()

    def stop_heartbeat(self) -> None:
        """Stop the heartbeat thread (idempotent)."""
        if self._stop is not None:
            self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=30)
