"""LoginGate of the web-UI tier (webui.gate): serialized web logins a full TOTP window apart, blocking failures."""

from __future__ import annotations

import json
import stat
import threading
from pathlib import Path

import pytest

from otterdog_e2e.webui.gate import (
    DEFAULT_SPACING,
    TOTP_PERIOD,
    GateState,
    LoginGate,
    WebLoginBlockedError,
    classify_web_failure,
    spacing_from_env,
    web_ui_problems,
)


class FakeClock:
    """Wall clock whose sleep advances time (records the sleeps)."""

    def __init__(self, now: float = 1_800_000_000.0) -> None:
        """Start at ``now`` (epoch seconds)."""
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the clock."""
        self.sleeps.append(seconds)
        self.now += seconds


def gate(directory: Path, clock: FakeClock, **kwargs: object) -> LoginGate:
    """A gate of the bot ``e2e-admin`` on ``directory`` driven by ``clock``."""
    return LoginGate(directory, account="E2E-Admin", clock=clock, sleep=clock.sleep, **kwargs)  # type: ignore[arg-type]


def test_first_login_does_not_wait(tmp_path: Path) -> None:
    """A fresh account starts at once; start, end and the login count are persisted."""
    clock = FakeClock()
    first = gate(tmp_path, clock)
    with first.session("plan") as ticket:
        assert ticket.waited == 0 and ticket.login_number == 1
        clock.now += 20
    state = first.state()
    assert state.last_start == 1_800_000_000.0 and state.last_end == 1_800_000_020.0 and state.logins == 1
    assert clock.sleeps == [] and first.session_logins == 1


def test_next_login_waits_a_full_window_after_the_previous_end(tmp_path: Path) -> None:
    """Two gates on the same directory (two processes): the second starts ``spacing`` after the first ENDED."""
    clock = FakeClock()
    with gate(tmp_path, clock).session("apply"):
        clock.now += 45  # apply: two logins during these 45 s
    clock.now += 2
    other = gate(tmp_path, clock)
    with other.session("show-live") as ticket:
        assert ticket.waited == pytest.approx(DEFAULT_SPACING - 2)
        assert ticket.started_at - other.state().last_start == 0
    assert sum(clock.sleeps) == pytest.approx(DEFAULT_SPACING - 2) and max(clock.sleeps) <= 5.0
    assert other.state().logins == 2


def test_spacing_is_never_below_one_totp_window(tmp_path: Path) -> None:
    """Configured spacings below 30 s are raised to it; E2E_WEB_LOGIN_SPACING is honoured above it."""
    assert gate(tmp_path, FakeClock(), spacing=5).spacing == TOTP_PERIOD
    assert spacing_from_env({}) == DEFAULT_SPACING
    assert spacing_from_env({"E2E_WEB_LOGIN_SPACING": "90"}) == 90.0
    assert spacing_from_env({"E2E_WEB_LOGIN_SPACING": "3"}) == TOTP_PERIOD
    assert spacing_from_env({"E2E_WEB_LOGIN_SPACING": "soon"}) == DEFAULT_SPACING


def test_a_holder_that_died_mid_command_counts_as_ending_now(tmp_path: Path) -> None:
    """A recorded start without end (crashed process): the next session waits a full spacing from its arrival."""
    clock = FakeClock()
    first = gate(tmp_path, clock)
    first._write(GateState(first.account, last_start=clock.now - 3600, last_end=None, logins=4))
    with first.session("plan") as ticket:
        assert ticket.waited == pytest.approx(DEFAULT_SPACING)
    assert first.state().logins == 5


def test_end_is_recorded_when_the_command_fails(tmp_path: Path) -> None:
    """An exception inside the session still records its end (the next login waits for it)."""
    clock = FakeClock()
    first = gate(tmp_path, clock)
    with pytest.raises(RuntimeError), first.session("apply"):
        clock.now += 7
        raise RuntimeError("boom")
    assert first.state().last_end == clock.now and first.state().holder is None


def test_blocking_stops_every_process_until_it_expires(tmp_path: Path) -> None:
    """block() is persisted: another gate refuses to start until the block expires or is lifted."""
    clock = FakeClock()
    first = gate(tmp_path, clock)
    first.block("credentials: wrong username or password of the bot account", duration=600)
    other = gate(tmp_path, clock)
    reason = other.blocked()
    assert reason is not None and "blocked until" in reason and "wrong username or password" in reason
    with pytest.raises(WebLoginBlockedError, match="wrong username"), other.session("plan"):
        pass
    clock.now += 601
    assert other.blocked() is None
    with other.session("plan"):
        pass
    other.block("again", duration=600)
    other.unblock()
    assert first.blocked() is None


def test_state_files_are_private_and_hold_no_secret(tmp_path: Path) -> None:
    """0700 directory, 0600 state file, only timestamps, counts, holder and block reason."""
    clock = FakeClock()
    directory = tmp_path / "webui"
    with gate(directory, clock).session("plan"):
        pass
    state_path = directory / "e2e-admin.json"
    assert stat.S_IMODE(directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(state_path.stat().st_mode) == 0o600
    assert set(json.loads(state_path.read_text())) == {
        "account",
        "last_start",
        "last_end",
        "logins",
        "holder",
        "blocked_until",
        "blocked_reason",
    }


def test_corrupt_state_is_ignored(tmp_path: Path) -> None:
    """An unreadable state file means a fresh state (and is rewritten by the next session)."""
    clock = FakeClock()
    first = gate(tmp_path, clock)
    tmp_path.mkdir(exist_ok=True)
    first.state_path.write_text("{not json")
    assert first.state() == GateState(first.account)
    assert GateState.from_json("a", {"logins": -3, "last_start": "x", "holder": 5}) == GateState("a")


def test_real_file_lock_serializes_sessions(tmp_path: Path) -> None:
    """Two gates (separate FileLock objects, like two processes) never hold sessions at the same time."""
    clock = FakeClock()
    events: list[str] = []
    entered, release = threading.Event(), threading.Event()

    def first() -> None:
        """Hold a session until released."""
        with gate(tmp_path, clock).session("apply"):
            events.append("first-in")
            entered.set()
            release.wait(10)
            events.append("first-out")

    def second() -> None:
        """Start a session once the first one is in."""
        entered.wait(10)
        with gate(tmp_path, clock, lock_timeout=10).session("plan"):
            events.append("second-in")

    threads = [threading.Thread(target=first), threading.Thread(target=second)]
    for thread in threads:
        thread.start()
    entered.wait(10)
    threading.Event().wait(0.3)  # the second thread is now blocked on the lock
    assert events == ["first-in"]
    release.set()
    for thread in threads:
        thread.join(10)
    assert events == ["first-in", "first-out", "second-in"]


def test_invalid_account_names() -> None:
    """The account is a file name stem: it must contain at least one safe character."""
    with pytest.raises(ValueError):
        LoginGate(Path("/nonexistent"), account="")
    with pytest.raises(ValueError):
        LoginGate(Path("/nonexistent"), account="///")


def test_summary(tmp_path: Path) -> None:
    """Logins of this process and their total wait (run.json web_ui)."""
    clock = FakeClock()
    one = gate(tmp_path, clock)
    with one.session("show-live"):
        pass
    with one.session("apply"):
        pass
    summary = one.summary()
    assert summary["session_logins"] == 2 and summary["commands"] == ["show-live", "apply"]
    assert summary["waited_seconds"] == pytest.approx(DEFAULT_SPACING) and summary["account"] == "E2E-Admin"


@pytest.mark.parametrize(
    ("text", "kind", "blocking"),
    [
        ("RuntimeError: incorrect username or password", "credentials", True),
        ("too many failed login attempts, please try again later", "lockout", True),
        ("RuntimeError: incorrect 2FA TOTP", "totp", True),
        ("the 2FA TOTP seed is not valid: Incorrect padding", "totp", True),
        ("unexpected page after login, expected 'Two-factor authentication' in title", "challenge", True),
        (
            "Your organization requires single sign-on login which is currently not supported by the web client.",
            "sso",
            True,
        ),
        ("logged in with unexpected user someone", "account", True),
        ("unable to launch browser, make sure you have installed required dependencies", "browser", False),
        ("RuntimeError: username not available", "token-only", False),
        ("could not log in to web UI: Timeout 10000ms exceeded", "login", False),
    ],
)
def test_classify_web_failure(text: str, kind: str, blocking: bool) -> None:
    """The failure texts of otterdog/providers/github/web.py and credentials/__init__.py."""
    failure = classify_web_failure(f"Planning ...\n{text}\n")
    assert failure is not None and failure.kind == kind and failure.blocking is blocking


def test_classify_ignores_ordinary_output() -> None:
    """No failure in a normal plan."""
    assert classify_web_failure("Plan: 0 to add, 1 to change, 0 to delete.") is None


def test_web_ui_problems() -> None:
    """WEB_UI = credentials AND allowed AND trusted SUT AND no SAML SSO AND not blocked."""
    ok = {"credentials": True, "allowed": True, "sut_trusted": True, "saml_sso": False}
    assert web_ui_problems(**ok) == []  # type: ignore[arg-type]
    assert "no web-UI credentials" in web_ui_problems(**{**ok, "credentials": False})[0]  # type: ignore[arg-type]
    assert "--e2e-allow-web-ui" in web_ui_problems(**{**ok, "allowed": False})[0]  # type: ignore[arg-type]
    assert "untrusted" in web_ui_problems(**{**ok, "sut_trusted": False})[0]  # type: ignore[arg-type]
    assert "cannot be decided" in web_ui_problems(**{**ok, "sut_trusted": None})[0]  # type: ignore[arg-type]
    assert "SAML SSO" in web_ui_problems(**{**ok, "saml_sso": True})[0]  # type: ignore[arg-type]
    assert web_ui_problems(**ok, blocked="web logins of x are blocked") == ["web logins of x are blocked"]  # type: ignore[arg-type]
    invalid = web_ui_problems(**{**ok, "credentials": False}, credentials_error="E2E_ADMIN_TOTP_SEED: not base32")  # type: ignore[arg-type]
    assert invalid == ["web-UI credentials invalid: E2E_ADMIN_TOTP_SEED: not base32"]
    assert len(web_ui_problems(credentials=False, allowed=False, sut_trusted=False, saml_sso=True)) == 4
