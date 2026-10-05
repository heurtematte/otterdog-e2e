"""procs.run_harness: harness children of a batch (pristine environment, own session, redacted line streaming, log file)
and procs.forward_signals (SIGINT/SIGTERM forwarded to the children, handlers restored)."""

from __future__ import annotations

import os
import signal
import stat
import sys
import textwrap
import threading
import time
from pathlib import Path

import pytest

from otterdog_e2e import procs
from otterdog_e2e.redact import Redactor

SECRET = "e2e-harness-child-secret-value-42"


def python(code: str) -> list[str]:
    """argv running ``code`` with this interpreter."""
    return [sys.executable, "-c", textwrap.dedent(code)]


@pytest.fixture
def redactor(monkeypatch: pytest.MonkeyPatch) -> Redactor:
    """A fresh Redactor used by procs (keeps the process-wide REDACTOR clean)."""
    fresh = Redactor()
    monkeypatch.setattr(procs, "REDACTOR", fresh)
    return fresh


def test_run_harness_passes_the_environment_unchanged_and_streams_redacted_lines(
    tmp_path: Path, redactor: Redactor
) -> None:
    """The child sees E2E_* and secret-named variables (sanitized_env would strip them); stdout and stderr are merged
    and every line is redacted, handed to on_line and appended to the 0600 log file."""
    redactor.add(SECRET)
    code = """
        import os, sys
        print("org", os.environ.get("E2E_ORG"))
        print("token", os.environ.get("E2E_ADMIN_TOKEN"))
        print("stderr line", file=sys.stderr, flush=True)
        sys.exit(3)
    """
    env = {**os.environ, "E2E_ORG": "acme-e2e", "E2E_ADMIN_TOKEN": SECRET, "PYTHONUNBUFFERED": "1"}
    assert "E2E_ORG" not in procs.sanitized_env(base=env)
    lines: list[str] = []
    log = tmp_path / "child.log"
    assert procs.run_harness(python(code), env=env, on_line=lines.append, log_path=log) == 3
    assert lines == ["org acme-e2e", "token ***", "stderr line"]
    assert log.read_text(encoding="utf-8").splitlines() == lines
    assert stat.S_IMODE(log.stat().st_mode) == 0o600
    procs.run_harness(python("print('again')"), env=env, on_line=lines.append, log_path=log)
    assert log.read_text(encoding="utf-8").splitlines()[-1] == "again"  # appended
    assert SECRET not in log.read_text(encoding="utf-8")


def test_run_harness_children_run_in_their_own_session(tmp_path: Path) -> None:
    """start_new_session: a terminal Ctrl-C reaches the parent only (which forwards it); stdin is /dev/null."""
    code = """
        import os, sys
        print(os.getsid(0), os.getpgrp() == os.getpid(), sys.stdin.read() == "")
    """
    lines: list[str] = []
    assert procs.run_harness(python(code), env=os.environ, on_line=lines.append) == 0
    sid, leader, empty_stdin = lines[0].split()
    assert int(sid) != os.getsid(0) and leader == "True" and empty_stdin == "True"


def test_run_harness_refuses_symlinked_logs_and_empty_commands(tmp_path: Path) -> None:
    """The log file is never written through a symlink; argv is required."""
    target = tmp_path / "elsewhere.txt"
    target.write_text("keep\n", encoding="utf-8")
    link = tmp_path / "child.log"
    link.symlink_to(target)
    with pytest.raises(OSError):
        procs.run_harness(python("print(1)"), env=os.environ, on_line=lambda line: None, log_path=link)
    assert target.read_text(encoding="utf-8") == "keep\n"
    with pytest.raises(ValueError, match="needs a command"):
        procs.run_harness([], env=os.environ, on_line=lambda line: None)


CHILD_WAITING_FOR_A_SIGNAL = """
    import signal, sys, time
    def stop(signum, frame):
        print("got", signum, flush=True)
        sys.exit(7)
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print("ready", flush=True)
    time.sleep(60)
    print("never", flush=True)
"""


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_signals_of_the_parent_are_forwarded_to_the_child(sig: signal.Signals) -> None:
    """SIGINT/SIGTERM of this process go to the child's process group (not to this process): the child cleans up and
    exits with its own code; the handlers of this process are restored afterwards."""
    before = {name: signal.getsignal(name) for name in procs.FORWARDED_SIGNALS}
    lines: list[str] = []

    def on_line(line: str) -> None:
        """Signal this very process once the child is ready."""
        lines.append(line)
        if line == "ready":
            os.kill(os.getpid(), sig)

    started = time.monotonic()
    code = procs.run_harness(python(CHILD_WAITING_FOR_A_SIGNAL), env=os.environ, on_line=on_line)
    assert code == 7 and lines == ["ready", f"got {int(sig)}"]
    assert time.monotonic() - started < 30
    assert {name: signal.getsignal(name) for name in procs.FORWARDED_SIGNALS} == before


def test_a_failing_reader_stops_the_child(tmp_path: Path) -> None:
    """An exception while reading (on_line) stops the child's group (SIGTERM, output drained) and propagates."""
    code = """
        import os, time
        print(os.getpid(), flush=True)
        time.sleep(60)
    """
    pids: list[int] = []

    def on_line(line: str) -> None:
        """Record the child's pid, then fail."""
        pids.append(int(line))
        raise RuntimeError("echo failed")

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="echo failed"):
        procs.run_harness(python(code), env=os.environ, on_line=on_line)
    assert time.monotonic() - started < 30
    with pytest.raises(ProcessLookupError):
        os.kill(pids[0], 0)  # stopped and reaped


def test_forward_signals_sets_a_shared_event_and_restores_handlers() -> None:
    """Nested blocks share one Event (set by a forwarded signal, cleared by the next outermost block); without a child
    the signal is swallowed; other threads install nothing."""
    previous = signal.getsignal(signal.SIGTERM)
    with procs.forward_signals() as outer:
        assert not outer.is_set() and signal.getsignal(signal.SIGTERM) is not previous
        with procs.forward_signals() as inner:
            assert inner is outer
            os.kill(os.getpid(), signal.SIGTERM)
            assert inner.wait(5)
        assert signal.getsignal(signal.SIGTERM) is not previous  # still forwarding
    assert signal.getsignal(signal.SIGTERM) is previous and outer.is_set()
    with procs.forward_signals() as again:
        assert not again.is_set()
    seen: list[object] = []

    def worker() -> None:
        """A non-main thread: no handler change."""
        with procs.forward_signals() as event:
            seen.append((event, signal.getsignal(signal.SIGTERM)))

    thread = threading.Thread(target=worker)
    thread.start()
    thread.join()
    assert seen == [(again, previous)]


CHILD_STOPPED_BY_A_SIGNAL = """
    import signal, sys, time
    def stop(signum, frame):
        print("got", signum, flush=True)
        sys.exit(7)
    signal.signal(signal.SIGTERM, stop)
    print("ready", flush=True)
    time.sleep(5)
    print("not signalled", flush=True)
"""


def test_a_signal_between_popen_and_the_registration_reaches_the_child(monkeypatch: pytest.MonkeyPatch) -> None:
    """A signal forwarded while the child exists but is not registered yet (the handler runs right after Popen
    returns) found no child to forward to: the registration sends it the signals forwarded before."""
    import subprocess

    real_popen = subprocess.Popen

    class SignalledPopen(real_popen):  # type: ignore[misc,valid-type]
        """Popen whose creation is followed, before the harness registers the child, by a signal of this process."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            """Start the child, then SIGTERM this process (the forwarding handler runs here)."""
            super().__init__(*args, **kwargs)
            os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(subprocess, "Popen", SignalledPopen)
    lines: list[str] = []
    started = time.monotonic()
    code = procs.run_harness(python(CHILD_STOPPED_BY_A_SIGNAL), env=os.environ, on_line=lines.append)
    # delivered at once: the child either handles it or dies of it before its handler is installed, never sleeps on
    assert code in (7, -int(signal.SIGTERM)) and "not signalled" not in lines, (code, lines)
    assert time.monotonic() - started < 5


def test_each_forwarded_signal_reaches_a_child_exactly_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """Whoever holds a child's delivery lock sends: a handler interrupting a delivery leaves the new signal to it (sent
    once, never twice), and a child registered late gets every signal forwarded in the block, in order."""
    sent: list[tuple[object, int]] = []
    monkeypatch.setattr(procs, "_signal_group", lambda process, sig: sent.append((process, sig)))
    process: object = object()
    with procs.forward_signals():
        procs._forward_signal(signal.SIGINT, None)  # no child yet
        child = procs._HarnessChild()
        assert child.lock.acquire()  # a delivery in progress (the main thread, interrupted by the handler)
        procs._deliver(process, child)  # type: ignore[arg-type]
        assert sent == []
        child.lock.release()
        procs._deliver(process, child)  # type: ignore[arg-type]
        procs._deliver(process, child)  # type: ignore[arg-type]
        assert sent == [(process, signal.SIGINT)]
        procs._forward_signal(signal.SIGTERM, None)  # unregistered: the next delivery sends it
        procs._deliver(process, child)  # type: ignore[arg-type]
        assert sent == [(process, signal.SIGINT), (process, signal.SIGTERM)]
    with procs.forward_signals():
        assert procs._forwarded_signals == []  # a new outermost block starts afresh
