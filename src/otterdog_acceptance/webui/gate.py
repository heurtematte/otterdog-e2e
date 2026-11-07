"""Login gate of the web-UI tier: one web login of the bot account at a time, spaced by a full TOTP window.

otterdog logs in to github.com with the bot's username, password and a TOTP code computed from its seed
(``Credentials.totp``). It only avoids reusing a code inside one process (``_last_totp``); two otterdog processes that
log in within the same 30 s window send the same code, and GitHub refuses a code that was already used. Every web
command of the harness therefore runs inside ``LoginGate.session()``:

* a file lock (cross-process, ``filelock``) serializes the web commands of every harness process of the machine;
* the gate state (a small JSON file next to the lock: account, last start and end, number of logins) makes the next
  session wait until ``spacing`` seconds (default 32: one TOTP window plus clock margin) passed since the END of the
  previous web command (a command may log in at any time while it runs, ``apply`` even twice), so two logins never
  share a TOTP window; a holder that died mid-command counts as ending when the next session acquires the lock;
* a blocking failure (wrong password, too many failed attempts, a login challenge, SSO) blocks the gate until a given
  time, so a broken setup cannot lock the bot account out with repeated attempts: ``session()`` raises
  WebLoginBlockedError and the web_ui gating skips the remaining web tests.

The files live in the private harness cache (``<E2E_CACHE_DIR>/webui/<account>.{lock,json}``, mode 0700, never in the
artifacts) and hold no secret. Logins from another machine (CI and a workstation using the same bot) are not seen:
use one bot account per target and never run the web-UI tier of a target from two places at once (the org lease
already serializes the sessions of one org).
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import time
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from filelock import FileLock

_logger = logging.getLogger(__name__)

TOTP_PERIOD = 30.0  # seconds per TOTP code (otterdog: mintotp defaults, SHA1, 6 digits)
SPACING_MARGIN = 2.0  # clock skew margin on top of one TOTP window
DEFAULT_SPACING = TOTP_PERIOD + SPACING_MARGIN
SPACING_ENV = "E2E_WEB_LOGIN_SPACING"  # seconds; values below TOTP_PERIOD are raised to it
GATE_DIR = "webui"
LOCK_TIMEOUT = 3 * 3600.0  # a web command waiting for another one (apply: two logins, slow pages)
MAX_SLEEP = 5.0  # waits are sliced so interruptions and timeouts are noticed
DEFAULT_BLOCK = 6 * 3600.0  # how long a blocking failure stops further web logins
_ACCOUNT_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class WebLoginBlockedError(RuntimeError):
    """Web logins of the account are blocked after a failure that repeated attempts would make worse."""


@dataclass
class GateState:
    """Persisted state of one account's gate (no secret)."""

    account: str
    last_start: float | None = None
    last_end: float | None = None
    logins: int = 0
    holder: str | None = None
    blocked_until: float | None = None
    blocked_reason: str | None = None

    def to_json(self) -> dict[str, Any]:
        """JSON form (timestamps as epoch seconds)."""
        return asdict(self)

    @classmethod
    def from_json(cls, account: str, data: Any) -> GateState:
        """State from its JSON form (unknown or malformed fields are dropped)."""
        state = cls(account)
        if not isinstance(data, dict):
            return state
        for name in ("last_start", "last_end", "blocked_until"):
            value = data.get(name)
            if isinstance(value, int | float) and not isinstance(value, bool):
                setattr(state, name, float(value))
        logins = data.get("logins")
        state.logins = logins if isinstance(logins, int) and not isinstance(logins, bool) and logins >= 0 else 0
        for name in ("holder", "blocked_reason"):
            value = data.get(name)
            setattr(state, name, str(value) if isinstance(value, str) else None)
        return state


@dataclass
class GateTicket:
    """One web command admitted by the gate: how long it waited and when it started."""

    what: str
    waited: float
    started_at: float
    login_number: int


@dataclass
class LoginGate:
    """Serializes and spaces the web logins of one bot account (module docstring)."""

    directory: Path
    account: str
    spacing: float = DEFAULT_SPACING
    clock: Callable[[], float] = time.time
    sleep: Callable[[float], None] = time.sleep
    lock_timeout: float = LOCK_TIMEOUT
    lock_factory: Callable[[str, float], AbstractContextManager[Any]] | None = None
    session_logins: int = field(default=0, init=False)
    tickets: list[GateTicket] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        """Validate the account name and the spacing (never less than one TOTP window)."""
        if not self.account or not _ACCOUNT_RE.sub("", self.account):
            raise ValueError(f"invalid gate account {self.account!r}")
        self.spacing = max(float(self.spacing), TOTP_PERIOD)

    # --- files ------------------------------------------------------------------------------------------------------
    @property
    def _stem(self) -> str:
        """File name stem of the account (filesystem safe, case-insensitive like GitHub logins)."""
        return _ACCOUNT_RE.sub("_", self.account.lower())

    @property
    def lock_path(self) -> Path:
        """``<directory>/<account>.lock``."""
        return self.directory / f"{self._stem}.lock"

    @property
    def state_path(self) -> Path:
        """``<directory>/<account>.json``."""
        return self.directory / f"{self._stem}.json"

    def _lock(self) -> AbstractContextManager[Any]:
        """The cross-process lock (FileLock unless a factory was injected)."""
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        if self.lock_factory is not None:
            return self.lock_factory(str(self.lock_path), self.lock_timeout)
        return FileLock(str(self.lock_path), timeout=self.lock_timeout)

    def state(self) -> GateState:
        """The persisted state (a fresh one when missing or unreadable)."""
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return GateState(self.account)
        return GateState.from_json(self.account, data)

    def _write(self, state: GateState) -> None:
        """Persist the state atomically (0600)."""
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.state_path.with_name(f".{self.state_path.name}.{os.getpid()}.tmp")
        descriptor = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state.to_json(), handle, sort_keys=True)
        os.replace(tmp, self.state_path)

    # --- blocking ---------------------------------------------------------------------------------------------------
    def blocked(self, state: GateState | None = None) -> str | None:
        """Why web logins are blocked right now (None when they are not)."""
        state = state or self.state()
        if state.blocked_until is None or state.blocked_until <= self.clock():
            return None
        until = datetime.fromtimestamp(state.blocked_until, UTC).strftime("%Y-%m-%d %H:%M UTC")
        return f"web logins of {self.account} are blocked until {until}: {state.blocked_reason or 'unknown reason'}"

    def block(self, reason: str, *, duration: float = DEFAULT_BLOCK) -> None:
        """Block further web logins of the account for ``duration`` seconds (persisted for every harness process)."""
        with self._lock():
            state = self.state()
            state.blocked_until = self.clock() + duration
            state.blocked_reason = reason
            self._write(state)
        _logger.error("web logins of %s blocked for %.0f s: %s", self.account, duration, reason)

    def unblock(self) -> None:
        """Lift a block (the operator checked the bot account)."""
        with self._lock():
            state = self.state()
            state.blocked_until = state.blocked_reason = None
            self._write(state)

    # --- sessions ---------------------------------------------------------------------------------------------------
    def earliest_start(self, state: GateState, now: float) -> float:
        """When the next web command may start: ``spacing`` after the end of the previous one (after ``now`` when its
        holder died mid-command, i.e. started without ending)."""
        if state.last_start is None and state.last_end is None:
            return now
        ended = state.last_end
        if ended is None or (state.last_start is not None and ended < state.last_start):
            ended = now
        return ended + self.spacing

    @contextlib.contextmanager
    def session(self, what: str) -> Iterator[GateTicket]:
        """Admit one web command: lock, wait for the spacing, record its start (and its end on exit).

        WebLoginBlockedError when the account is blocked. Waits are sliced (MAX_SLEEP) so interruptions are noticed.
        """
        with self._lock():
            state = self.state()
            reason = self.blocked(state)
            if reason:
                raise WebLoginBlockedError(reason)
            arrived = self.clock()
            ready = self.earliest_start(state, arrived)
            while (now := self.clock()) < ready:
                self.sleep(min(ready - now, MAX_SLEEP))
            started = self.clock()
            state.last_start, state.last_end = started, None
            state.logins += 1
            state.holder = f"pid {os.getpid()}: {what}"
            self._write(state)
            self.session_logins += 1
            ticket = GateTicket(what, round(started - arrived, 3), started, state.logins)
            self.tickets.append(ticket)
            if ticket.waited:
                _logger.info("web login gate: %s waited %.1f s for the TOTP window", what, ticket.waited)
            try:
                yield ticket
            finally:
                state = self.state()
                state.last_end = self.clock()
                state.holder = None
                self._write(state)

    def summary(self) -> dict[str, Any]:
        """Account, spacing, logins of this process and total wait (run.json)."""
        return {
            "account": self.account,
            "spacing_seconds": self.spacing,
            "session_logins": self.session_logins,
            "waited_seconds": round(sum(ticket.waited for ticket in self.tickets), 3),
            "commands": [ticket.what for ticket in self.tickets],
        }


def spacing_from_env(environ: dict[str, str] | Any) -> float:
    """E2E_WEB_LOGIN_SPACING (seconds) or DEFAULT_SPACING; never below one TOTP window."""
    raw = str(environ.get(SPACING_ENV) or "").strip()
    if not raw:
        return DEFAULT_SPACING
    try:
        value = float(raw)
    except ValueError:
        _logger.warning("ignoring %s=%r (not a number of seconds)", SPACING_ENV, raw)
        return DEFAULT_SPACING
    return max(value, TOTP_PERIOD)


# --- failures of otterdog's web client (otterdog/providers/github/web.py) -----------------------------------------
@dataclass(frozen=True)
class WebFailure:
    """A recognized web-client failure: kind, whether (and how long, seconds) it blocks further logins, a hint."""

    kind: str
    blocking: bool
    hint: str
    block_seconds: float = DEFAULT_BLOCK


WEB_FAILURES: tuple[tuple[re.Pattern[str], WebFailure], ...] = (
    (
        re.compile(r"too many failed login attempts", re.IGNORECASE),
        WebFailure("lockout", True, "GitHub throttles the bot's logins: wait, then check the password"),
    ),
    (
        re.compile(r"incorrect username or password", re.IGNORECASE),
        WebFailure("credentials", True, "wrong username or password of the bot account"),
    ),
    (
        re.compile(r"incorrect 2FA TOTP|the 2FA TOTP seed is not valid", re.IGNORECASE),
        WebFailure("totp", True, "wrong TOTP seed (or a code reused within 30 s by another process)", 3600.0),
    ),
    (
        re.compile(r"unexpected page after login|device verification", re.IGNORECASE),
        WebFailure(
            "challenge",
            True,
            "GitHub asked for an extra verification (device verification, 2FA method): log in once interactively"
            " (otterdog web-login) and make the authenticator app the default 2FA method",
        ),
    ),
    (
        re.compile(r"single sign-on login which is currently not supported", re.IGNORECASE),
        WebFailure(
            "sso", True, "the org enforces SAML SSO: set github.saml_sso: true (the web-UI tier is skipped)", 86400.0
        ),
    ),
    (
        re.compile(r"logged in with unexpected user", re.IGNORECASE),
        WebFailure("account", True, "the browser session belongs to another account"),
    ),
    (
        re.compile(r"unable to launch browser", re.IGNORECASE),
        WebFailure("browser", False, "Playwright Firefox is missing: playwright install firefox (and its deps)"),
    ),
    (
        re.compile(r"username not available|password not available|totp_secret not available", re.IGNORECASE),
        WebFailure("token-only", False, "the command resolved token-only credentials (KB-002)"),
    ),
    (
        re.compile(r"could not log in to web UI", re.IGNORECASE),
        WebFailure("login", False, "the login page changed or timed out (see the command output)"),
    ),
)


def classify_web_failure(text: str) -> WebFailure | None:
    """The first recognized web-client failure in otterdog output, None when there is none."""
    for pattern, failure in WEB_FAILURES:
        if pattern.search(text):
            return failure
    return None


def web_ui_problems(
    *,
    credentials: bool,
    allowed: bool,
    sut_trusted: bool | None,
    saml_sso: bool,
    blocked: str | None = None,
    credentials_error: str | None = None,
) -> list[str]:
    """Why the WEB_UI capability is missing (empty: web-UI tests may run).

    WEB_UI = admin web credentials present AND --e2e-allow-web-ui AND trusted SUT AND not github.saml_sso AND web
    logins not blocked.
    """
    problems = []
    if credentials_error:
        problems.append(f"web-UI credentials invalid: {credentials_error}")
    elif not credentials:
        problems.append("no web-UI credentials for the admin bot (E2E_ADMIN_PASSWORD, E2E_ADMIN_TOTP_SEED)")
    if not allowed:
        problems.append("web-UI tests are not allowed: pass --e2e-allow-web-ui (or set E2E_ALLOW_WEB_UI=1)")
    if sut_trusted is not True:
        problems.append(
            "the SUT is untrusted (or its trust is unknown): web-UI credentials never reach untrusted code"
            if sut_trusted is False
            else "the trust of the SUT cannot be decided: web-UI credentials never reach untrusted code"
        )
    if saml_sso:
        problems.append("github.saml_sso is true: otterdog's web client cannot log in through SAML SSO")
    if blocked:
        problems.append(blocked)
    return problems
