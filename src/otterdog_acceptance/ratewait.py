"""Pauses for GitHub's rate limits instead of failures (E2E_RATE_WAIT_MAX).

A live session shares the core budget of its identities with the otterdog CLI under test and, in CI, with the other
instances of the nightly when they use the same accounts: otterdog itself never waits for a rate limit, so a session
that runs dry fails every command until the budget resets. Two pauses avoid that:

- before each live item, the session reads GET /rate_limit (free) for the identities it uses; while one is below
  E2E_MIN_RATE_REMAINING it pauses until that budget resets (``pause_for_rate_limit``), then runs the item;
- an otterdog command that hit a primary or secondary rate limit (``rate_limited``) pauses the same way and runs once
  more when that is safe: a read-only command, or one whose recorded requests (OTTERDOG_STATS_FILE) contain no write
  (OtterdogCli._rate_retry).

A pause never counts against the timeout of the item: pytest-timeout's SIGALRM timer is suspended meanwhile
(``alarm_suspended``). The pauses of one item or command add up to at most E2E_RATE_WAIT_MAX seconds (default 3600,
one reset window); beyond, the item is skipped ("github rate budget: ...") or the command keeps its failure, as before.
0 disables the pauses.
"""

from __future__ import annotations

import contextlib
import re
import signal
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

RATE_WAIT_ENV = "E2E_RATE_WAIT_MAX"
DEFAULT_RATE_WAIT_MAX = 3600.0  # seconds: one reset window of the primary rate limit
RESET_MARGIN = 5.0  # seconds after the announced reset (clock skew between GitHub and the runner)
MIN_PAUSE = 15.0  # a reset already past while the budget is still low: read again after this
SECONDARY_PAUSE = 60.0  # a limit hit while every core budget is above the threshold: a secondary rate limit
RATE_LIMIT_RE = re.compile(r"secondary rate limit|API rate limit exceeded", re.IGNORECASE)


@dataclass(frozen=True)
class CoreBudget:
    """The core budget of one identity (GET /rate_limit)."""

    remaining: int
    reset: float | None  # epoch seconds, None when GitHub gave none


def pause_sleep(seconds: float) -> None:
    """The sleep of a session's pauses (a seam for tests)."""
    time.sleep(seconds)


def core_budget(body: Mapping[str, Any]) -> CoreBudget | None:
    """``resources.core`` of a GET /rate_limit body, None when it has no remaining count."""
    resources = body.get("resources")
    core = resources.get("core") if isinstance(resources, Mapping) else None
    if not isinstance(core, Mapping) or not isinstance(core.get("remaining"), int):
        return None
    reset = core.get("reset")
    return CoreBudget(core["remaining"], float(reset) if isinstance(reset, (int, float)) else None)


def rate_limited(text: str | None) -> bool:
    """True when ``text`` (an otterdog infra error line) reports a primary or secondary rate limit."""
    return bool(text and RATE_LIMIT_RE.search(text))


def low_budget_reason(low: Mapping[str, int], threshold: int) -> str:
    """The skip reason of the rate gate (matched by the infra patterns of the reports)."""
    details = ", ".join(f"{name} {remaining}" for name, remaining in sorted(low.items()))
    return f"github rate budget: core remaining {details} < {threshold}"


@contextlib.contextmanager
def alarm_suspended() -> Iterator[None]:
    """Suspend pytest-timeout's SIGALRM timer (its ``signal`` method) and re-arm it with the time it had left; a no-op
    outside the main thread or without an armed timer (``thread`` method, no timeout)."""
    if threading.current_thread() is not threading.main_thread() or not hasattr(signal, "setitimer"):
        yield
        return
    remaining, interval = signal.getitimer(signal.ITIMER_REAL)
    if remaining <= 0:
        yield
        return
    signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, remaining, interval)


@dataclass(frozen=True)
class RatePause:
    """One pause: what waited, how long, and the budgets that made it wait (empty for a secondary limit)."""

    what: str
    seconds: float
    low: Mapping[str, int]

    def describe(self) -> str:
        """Terminal line of the pause."""
        if not self.low:
            return f"rate limit: {self.what} hit a secondary rate limit, pausing {self.seconds:.0f} s"
        details = ", ".join(f"{name} {remaining}" for name, remaining in sorted(self.low.items()))
        until = time.strftime("%H:%M:%S", time.gmtime(time.time() + self.seconds))
        return f"rate limit: core remaining {details}, {self.what} pauses {self.seconds:.0f} s (until {until} UTC)"


def pause_for_rate_limit(
    what: str,
    read_budgets: Callable[[], Mapping[str, CoreBudget]],
    *,
    threshold: int,
    max_wait: float,
    after_limit: bool = False,
    on_pause: Callable[[RatePause], None] = lambda pause: None,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.time,
) -> str | None:
    """Pause while a budget of ``read_budgets()`` is below ``threshold``: until its reset (+ RESET_MARGIN), then read
    again; None once every budget is back (or when there is none to read), else the reason it gave up.

    ``after_limit`` (a command just hit a limit): when no budget is low, the limit was a secondary one, and the pause is
    SECONDARY_PAUSE once. The pauses add up to at most ``max_wait`` seconds; the next one that would exceed it gives up.
    """
    waited = 0.0
    while True:
        budgets = read_budgets()
        low = {name: budget for name, budget in budgets.items() if budget.remaining < threshold}
        counts = {name: budget.remaining for name, budget in low.items()}
        if low:
            resets = [budget.reset for budget in low.values() if budget.reset is not None]
            if len(resets) < len(low):
                return low_budget_reason(counts, threshold) + " (no reset time)"
            delay = max(max(resets) - clock() + RESET_MARGIN, MIN_PAUSE)
        elif after_limit and waited == 0:
            if not budgets:
                return f"{what}: rate limit hit and no budget readable"
            delay = SECONDARY_PAUSE
        else:
            return None
        if waited + delay > max_wait:
            reason = low_budget_reason(counts, threshold) if counts else f"{what}: secondary rate limit"
            return f"{reason} (a pause of {delay:.0f} s exceeds {RATE_WAIT_ENV}={max_wait:g})"
        on_pause(RatePause(what, delay, counts))
        with alarm_suspended():
            sleep(delay)
        waited += delay
