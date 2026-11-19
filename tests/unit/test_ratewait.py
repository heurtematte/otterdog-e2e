"""ratewait: the pauses for GitHub's rate limits (budget reads, reset waits, the suspended pytest-timeout timer)."""

from __future__ import annotations

import signal
from collections.abc import Iterator, Mapping

import pytest

from otterdog_acceptance import ratewait
from otterdog_acceptance.ratewait import (
    MIN_PAUSE,
    RESET_MARGIN,
    SECONDARY_PAUSE,
    CoreBudget,
    RatePause,
    alarm_suspended,
    core_budget,
    pause_for_rate_limit,
    rate_limited,
)

NOW = 1_800_000_000.0


class Clock:
    """A fake clock that sleeps by moving forward; the budgets reset when it passes their reset time."""

    def __init__(self, budgets: Mapping[str, CoreBudget]) -> None:
        """Start at NOW with ``budgets``."""
        self.now = NOW
        self.budgets = dict(budgets)
        self.sleeps: list[float] = []
        self.pauses: list[RatePause] = []

    def sleep(self, seconds: float) -> None:
        """Move forward; every budget whose reset has passed is full again."""
        self.sleeps.append(seconds)
        self.now += seconds
        for name, budget in list(self.budgets.items()):
            if budget.reset is not None and budget.reset <= self.now:
                self.budgets[name] = CoreBudget(5000, self.now + 3600)

    def read(self) -> Mapping[str, CoreBudget]:
        """The current budgets."""
        return dict(self.budgets)

    def pause(self, what: str, **kwargs: object) -> str | None:
        """pause_for_rate_limit over this clock (threshold 800, one hour at most unless given)."""
        options: dict[str, object] = {"threshold": 800, "max_wait": 3600.0, **kwargs}
        return pause_for_rate_limit(
            what,
            self.read,
            on_pause=self.pauses.append,
            sleep=self.sleep,
            clock=lambda: self.now,
            **options,  # type: ignore[arg-type]
        )


def test_core_budget_and_rate_limited() -> None:
    """GET /rate_limit bodies and the infra error lines of otterdog."""
    body = {"resources": {"core": {"limit": 5000, "remaining": 12, "reset": 1_800_000_100}}}
    assert core_budget(body) == CoreBudget(12, 1_800_000_100.0)
    assert core_budget({"resources": {"core": {"remaining": 3}}}) == CoreBudget(3, None)
    assert core_budget({}) is None and core_budget({"resources": {"core": {}}}) is None
    assert rate_limited('"message": "API rate limit exceeded for user ID 351898494."')
    assert rate_limited("You have exceeded a secondary rate limit")
    assert not rate_limited("Error: Cannot connect to host api.github.com:443") and not rate_limited(None)


def test_enough_budget_never_pauses() -> None:
    """Every budget at or above the threshold: no pause, the item goes on."""
    clock = Clock({"admin": CoreBudget(800, NOW + 60), "oracle": CoreBudget(4000, NOW + 60)})
    assert clock.pause("item") is None and clock.sleeps == [] and clock.pauses == []


def test_a_low_budget_pauses_until_its_reset() -> None:
    """Below the threshold: one pause until the reset (+ margin), then the budgets are read again and the item goes
    on; the pause names the low identities."""
    clock = Clock({"admin": CoreBudget(120, NOW + 600), "oracle": CoreBudget(4000, NOW + 900)})
    assert clock.pause("tests/cli/test_scenarios.py::test_cli_scenario[cli.org.secret]") is None
    assert clock.sleeps == [600 + RESET_MARGIN]
    (pause,) = clock.pauses
    assert pause.low == {"admin": 120} and pause.seconds == 600 + RESET_MARGIN
    assert pause.describe().startswith("rate limit: core remaining admin 120, tests/cli/test_scenarios.py::")


def test_a_pause_waits_for_the_latest_reset_and_at_least_min_pause() -> None:
    """Two low identities: until the later reset; a reset already past: MIN_PAUSE, then read again."""
    clock = Clock({"admin": CoreBudget(10, NOW + 100), "author": CoreBudget(0, NOW + 300)})
    assert clock.pause("item") is None and clock.sleeps == [300 + RESET_MARGIN]
    stale = Clock({"admin": CoreBudget(10, NOW - 30)})
    assert stale.pause("item") is None and stale.sleeps == [MIN_PAUSE]


def test_a_pause_longer_than_the_maximum_gives_up() -> None:
    """A reset further than E2E_RATE_WAIT_MAX: no pause, the reason keeps the skip message of the gate."""
    clock = Clock({"admin": CoreBudget(120, NOW + 3000)})
    reason = clock.pause("item", max_wait=600.0)
    assert reason == (
        "github rate budget: core remaining admin 120 < 800 (a pause of 3005 s exceeds E2E_RATE_WAIT_MAX=600)"
    )
    assert clock.sleeps == []
    assert clock.pause("item", max_wait=0.0) is not None and clock.sleeps == []


def test_a_low_budget_without_reset_time_gives_up() -> None:
    """No reset time (an old snapshot): the gate skips as before."""
    clock = Clock({"admin": CoreBudget(120, None)})
    assert clock.pause("item") == "github rate budget: core remaining admin 120 < 800 (no reset time)"


def test_after_a_limit_with_full_budgets_one_secondary_pause() -> None:
    """A command hit a limit while every core budget is fine: a secondary rate limit, one SECONDARY_PAUSE."""
    clock = Clock({"admin": CoreBudget(4000, NOW + 600)})
    assert clock.pause("otterdog plan", after_limit=True) is None
    assert clock.sleeps == [SECONDARY_PAUSE] and clock.pauses[0].low == {}
    assert "secondary rate limit" in clock.pauses[0].describe()
    exhausted = Clock({"admin": CoreBudget(0, NOW + 120)})
    assert exhausted.pause("otterdog plan", after_limit=True) is None and exhausted.sleeps == [120 + RESET_MARGIN]
    assert Clock({}).pause("otterdog plan", after_limit=True) == "otterdog plan: rate limit hit and no budget readable"
    assert Clock({}).pause("item") is None


@pytest.fixture
def alarm() -> Iterator[list[int]]:
    """A SIGALRM handler recording its calls; the timer and the handler are restored afterwards."""
    fired: list[int] = []
    previous = signal.signal(signal.SIGALRM, lambda signum, frame: fired.append(signum))
    try:
        yield fired
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def test_alarm_suspended_pauses_the_timer_and_rearms_what_was_left(alarm: list[int]) -> None:
    """pytest-timeout's signal timer is off during the pause and gets back the time it had left."""
    signal.setitimer(signal.ITIMER_REAL, 50.0)
    with alarm_suspended():
        assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    remaining = signal.getitimer(signal.ITIMER_REAL)[0]
    assert 49.0 < remaining <= 50.0 and alarm == []
    signal.setitimer(signal.ITIMER_REAL, 0)
    with alarm_suspended():  # no timer: nothing to suspend or re-arm
        pass
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0


def test_pause_sleep_is_the_seam_of_the_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """The context sleeps through ratewait.pause_sleep (patched by the plugin tests)."""
    slept: list[float] = []
    monkeypatch.setattr(ratewait.time, "sleep", slept.append)
    ratewait.pause_sleep(3.0)
    assert slept == [3.0]
