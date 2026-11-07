"""Polling and retry helpers with injectable clock and sleep (used by checks, converge loops, relay and webapp waits).

Intervals are either a constant (seconds) or a schedule whose last step repeats, e.g. ``(5, 10, 20)`` waits 5 s, 10 s,
then 20 s between every later attempt (the converge backoff of SPEC 12.1).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, Sequence
from typing import Any, TypeAlias, TypeVar

T = TypeVar("T")

Interval: TypeAlias = float | Sequence[float]
CONVERGE_BACKOFF: tuple[float, ...] = (5.0, 10.0, 20.0)


class WaitTimeoutError(TimeoutError):
    """A condition did not hold in time; carries the last observed value and the number of attempts."""

    def __init__(self, what: str, timeout: float | None, *, last: Any = None, attempts: int = 0) -> None:
        """Build the error message from what was awaited, the budget and the attempts."""
        budget = f"within {timeout:g} s" if timeout is not None else "within the attempt budget"
        super().__init__(f"{what}: not satisfied {budget} ({attempts} attempt(s))")
        self.what = what
        self.timeout = timeout
        self.last = last
        self.attempts = attempts


class Deadline:
    """A point in time ``timeout`` seconds from now (``None`` = never expires)."""

    def __init__(self, timeout: float | None, *, clock: Callable[[], float] = time.monotonic) -> None:
        """Start the deadline now."""
        self._clock = clock
        self._start = clock()
        self.timeout = timeout

    def elapsed(self) -> float:
        """Seconds since the deadline was created."""
        return self._clock() - self._start

    def remaining(self) -> float:
        """Seconds left (never negative; infinite without timeout)."""
        if self.timeout is None:
            return float("inf")
        return max(0.0, self.timeout - self.elapsed())

    def expired(self) -> bool:
        """True once the timeout has elapsed."""
        return self.timeout is not None and self.elapsed() >= self.timeout


def intervals(interval: Interval) -> Iterator[float]:
    """Yield successive delays: a constant forever, or the given steps with the last one repeated."""
    steps = [float(interval)] if isinstance(interval, int | float) else [float(step) for step in interval]
    if not steps or any(step < 0 for step in steps):
        raise ValueError(f"invalid interval {interval!r}")
    yield from steps[:-1]
    while True:
        yield steps[-1]


def poll(
    fn: Callable[[], T],
    *,
    until: Callable[[T], bool],
    timeout: float | None = None,
    max_attempts: int | None = None,
    interval: Interval = 5.0,
    what: str = "condition",
    raise_on_timeout: bool = True,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Call ``fn`` until ``until(value)`` holds and return that value; at least one of timeout/max_attempts is required.

    When the budget is exhausted, raise WaitTimeoutError (``last`` = last value) or, with ``raise_on_timeout=False``, return
    the last value. The function is always called once more after the final sleep, which never overshoots the deadline.
    """
    if timeout is None and max_attempts is None:
        raise ValueError("poll() needs a timeout or max_attempts")
    deadline = Deadline(timeout, clock=clock)
    delays = intervals(interval)
    attempts = 0
    while True:
        attempts += 1
        value = fn()
        if until(value):
            return value
        exhausted = deadline.expired() or (max_attempts is not None and attempts >= max_attempts)
        if exhausted:
            if raise_on_timeout:
                raise WaitTimeoutError(what, timeout, last=value, attempts=attempts)
            return value
        sleep(min(next(delays), deadline.remaining()))


def wait_until(
    condition: Callable[[], T],
    *,
    timeout: float,
    interval: Interval = 5.0,
    what: str = "condition",
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Call ``condition`` until it returns a truthy value and return it; raise WaitTimeoutError after ``timeout`` seconds."""
    return poll(condition, until=bool, timeout=timeout, interval=interval, what=what, sleep=sleep, clock=clock)


def retry(
    fn: Callable[[], T],
    *,
    retry_if: Callable[[Exception], bool],
    timeout: float | None = None,
    max_attempts: int | None = None,
    interval: Interval = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> T:
    """Call ``fn``, retrying exceptions accepted by ``retry_if`` until the budget is exhausted (then re-raise)."""
    if timeout is None and max_attempts is None:
        raise ValueError("retry() needs a timeout or max_attempts")
    deadline = Deadline(timeout, clock=clock)
    delays = intervals(interval)
    attempts = 0
    while True:
        attempts += 1
        try:
            return fn()
        except Exception as exc:
            exhausted = deadline.expired() or (max_attempts is not None and attempts >= max_attempts)
            if exhausted or not retry_if(exc):
                raise
        sleep(min(next(delays), deadline.remaining()))
