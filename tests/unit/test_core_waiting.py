"""WP-A: polling and retry helpers (deterministic clock)."""

from __future__ import annotations

import pytest

from otterdog_e2e import waiting


class Clock:
    """Monotonic fake clock advanced by sleep()."""

    def __init__(self) -> None:
        """Start at 0."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance time."""
        self.sleeps.append(seconds)
        self.now += seconds


def test_intervals_reject_negative_steps() -> None:
    """Negative delays are configuration errors."""
    with pytest.raises(ValueError):
        next(waiting.intervals(-1))
    with pytest.raises(ValueError):
        next(waiting.intervals((1, -2)))


def test_poll_converge_backoff_schedule() -> None:
    """The converge schedule 5/10/20 s is honoured and clipped at the deadline."""
    clock = Clock()
    with pytest.raises(waiting.WaitTimeoutError) as info:
        waiting.poll(
            lambda: 0,
            until=lambda v: False,
            timeout=40,
            interval=waiting.CONVERGE_BACKOFF,
            sleep=clock.sleep,
            clock=clock,
        )
    assert clock.sleeps == [5, 10, 20, 5]
    assert info.value.attempts == 5 and info.value.timeout == 40


def test_poll_zero_timeout_calls_once() -> None:
    """timeout=0 still calls the function once."""
    clock = Clock()
    assert waiting.poll(lambda: 7, until=lambda v: v == 7, timeout=0, sleep=clock.sleep, clock=clock) == 7
    with pytest.raises(waiting.WaitTimeoutError):
        waiting.poll(lambda: 7, until=lambda v: False, timeout=0, sleep=clock.sleep, clock=clock)
    assert clock.sleeps == []


def test_wait_timeout_error_message_without_timeout() -> None:
    """Attempt-bounded waits describe their budget."""
    error = waiting.WaitTimeoutError("status", None, last={"state": "pending"}, attempts=3)
    assert "attempt budget" in str(error) and "3 attempt(s)" in str(error)
    assert error.last == {"state": "pending"} and isinstance(error, TimeoutError)


def test_retry_respects_timeout_and_non_retryable_errors() -> None:
    """retry stops at the deadline and never retries rejected exceptions."""
    clock = Clock()
    attempts: list[int] = []

    def failing() -> None:
        """Always fail with a retryable error."""
        attempts.append(1)
        raise ConnectionError("down")

    with pytest.raises(ConnectionError):
        waiting.retry(failing, retry_if=lambda e: True, timeout=12, interval=5, sleep=clock.sleep, clock=clock)
    assert clock.sleeps == [5, 5, 2] and len(attempts) == 4
    with pytest.raises(ValueError):
        waiting.retry(lambda: None, retry_if=lambda e: True)


def test_wait_until_timeout() -> None:
    """wait_until raises after its timeout with the last falsy value."""
    clock = Clock()
    with pytest.raises(waiting.WaitTimeoutError) as info:
        waiting.wait_until(list, timeout=3, interval=1, what="deliveries", sleep=clock.sleep, clock=clock)
    assert info.value.last == [] and "deliveries" in str(info.value)
