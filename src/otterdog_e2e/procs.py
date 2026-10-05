"""The only place that starts subprocesses (SPEC 5.6, SEC-10).

Every child gets a sanitized environment: credentials and interpreter/git/pip/ssh hooks of the operator are removed,
output is made deterministic (wide, colourless, unbuffered, UTF-8) and, unless ``keep_home``, HOME/XDG point at a
scratch home so the operator's dotfiles (~/.gitconfig, ~/.netrc, ~/.config/gh, ~/.vault-token, ~/.env) are never read.

Children run in their own session (process group): on timeout or interruption the whole group gets SIGTERM, then
SIGKILL after TERMINATE_GRACE seconds, so no grandchild (git, pip, a docker CLI) keeps running behind the harness.
Remote docker daemons over ``ssh://`` are not supported (SSH_AUTH_SOCK is removed for every child).

run_harness() is the exception to the sanitized environment: it starts the harness itself (``python -P -m
otterdog_e2e``, one child per target of a batch) with the parent's pristine environment, streams its redacted output
line by line and forwards SIGINT/SIGTERM to it (forward_signals; a signal forwarded before the child was registered
is sent to it right after, each signal exactly once).
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import shlex
import signal
import subprocess
import threading
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

from otterdog_e2e.redact import REDACTOR

__all__ = [
    "FORWARDED_SIGNALS",
    "HARNESS_STOP_GRACE",
    "REMOVED_ENV_KEYS",
    "REMOVED_ENV_PATTERNS",
    "SET_ENV",
    "TERMINATE_GRACE",
    "CalledProcessError",
    "CompletedProcess",
    "TimeoutExpired",
    "default_home",
    "forward_signals",
    "run",
    "run_harness",
    "sanitized_env",
    "set_default_home",
    "unshare_available",
]

_logger = logging.getLogger(__name__)

REMOVED_ENV_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        # SPEC 5.6
        r"^E2E_",
        r"^OTTER",
        r"^OTTERDOG_",
        r"^GITHUB_TOKEN$",
        r"^GH_",
        r"^GITHUB_PAT",
        r"^ACTIONS_",
        r"_TOKEN$",
        r"_SECRET$",
        r"_PASSWORD$",
        r"_TOTP",
        # hardening: credential-like words anywhere in the name (AWS_SECRET_ACCESS_KEY, POETRY_PYPI_TOKEN_<REPO>, ...)
        r"(^|_)(TOKEN|SECRET|PASSWORD|PASSWD|PASSPHRASE|CREDENTIALS?|API_?KEY|ACCESS_KEY|PRIVATE_KEY)(_|$)",
        # credential stores used by otterdog providers (bitwarden, vault, pass)
        r"^(BW|VAULT|PASSWORD_STORE)_",
        # operator configuration of the tools the harness drives (git config injection, indexes, interpreters)
        r"^GIT_",
        r"^SSH_",
        r"^(PIP|POETRY)_",
        r"^PYTHON",
    )
)
REMOVED_ENV_KEYS: frozenset[str] = frozenset(
    {
        "SSH_AUTH_SOCK",
        "GIT_ASKPASS",
        "SSH_ASKPASS",
        "PYTHONPATH",
        "PYTHONSTARTUP",
        "VIRTUAL_ENV",
        "PIP_INDEX_URL",
        "PIP_EXTRA_INDEX_URL",
        "FORCE_COLOR",
        # hardening: credential files, workflow command files of GitHub Actions, forced terminal/colour modes
        "KUBECONFIG",
        "GNUPGHOME",
        "GITHUB_ENV",
        "GITHUB_OUTPUT",
        "GITHUB_PATH",
        "GITHUB_STATE",
        "GITHUB_STEP_SUMMARY",
        "CLICOLOR_FORCE",
        "PY_COLORS",
        "TTY_COMPATIBLE",
        "TTY_INTERACTIVE",
    }
)
SET_ENV: Mapping[str, str] = {
    "COLUMNS": "4096",
    "LINES": "1000",
    "NO_COLOR": "1",
    "TERM": "dumb",
    "PYTHON_DOTENV_DISABLED": "1",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONUNBUFFERED": "1",
    "PYTHONIOENCODING": "utf-8",
    "PYTHON_KEYRING_BACKEND": "keyring.backends.null.Keyring",  # poetry never reaches (or waits on) the user keyring
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "NETRC": "/dev/null",
}
_XDG_DIRS = {
    "XDG_CONFIG_HOME": ".config",
    "XDG_CACHE_HOME": ".cache",
    "XDG_DATA_HOME": ".local/share",
    "XDG_STATE_HOME": ".local/state",
}
TERMINATE_GRACE = 5.0  # seconds between SIGTERM and SIGKILL of a timed-out or interrupted process group

_default_home: Path | None = None


def set_default_home(path: Path | None) -> None:
    """Set the HOME used when no explicit ``home`` is given (the plugin sets ``settings.scratch(run_id)/"home"``)."""
    global _default_home
    _default_home = path


def default_home() -> Path:
    """The configured default HOME, else ``<E2E_CACHE_DIR or ~/.cache/otterdog-e2e>/home``."""
    if _default_home is not None:
        return _default_home
    cache_dir = os.environ.get("E2E_CACHE_DIR") or "~/.cache/otterdog-e2e"
    return Path(cache_dir).expanduser() / "home"


def _removed(key: str) -> bool:
    """True when an inherited variable must not reach a child process."""
    return key in REMOVED_ENV_KEYS or any(pattern.search(key) for pattern in REMOVED_ENV_PATTERNS)


def sanitized_env(
    extra: Mapping[str, str] | None = None,
    *,
    home: Path | None = None,
    keep_home: bool = False,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Child environment: ``base`` (os.environ) minus credentials and hooks, plus SET_ENV, scratch HOME/XDG, ``extra``."""
    source = os.environ if base is None else base
    env = {key: value for key, value in source.items() if not _removed(key)}
    env.update(SET_ENV)
    if not keep_home:
        home_dir = home if home is not None else default_home()
        env["HOME"] = str(home_dir)
        env.update({key: str(home_dir / sub) for key, sub in _XDG_DIRS.items()})
    if extra:
        env.update({key: str(value) for key, value in extra.items()})  # Path values are common
    return env


def _mkdir_private(path: Path) -> None:
    """Create ``path`` and its missing parents with mode 0700 (existing directories are left untouched)."""
    missing = []
    current = path
    while not current.exists() and current != current.parent:
        missing.append(current)
        current = current.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)


def _prepare_home(env: Mapping[str, str]) -> None:
    """Create the scratch HOME and its XDG dirs (mode 0700) so tools can write their caches."""
    for key in ("HOME", *_XDG_DIRS):
        _mkdir_private(Path(env[key]))


def _redacted(args: Sequence[str]) -> list[str]:
    """argv with registered secrets and token shapes masked (for exceptions and logs)."""
    return [REDACTOR(arg) for arg in args]


def _signal_group(process: subprocess.Popen[str], sig: int) -> None:
    """Send ``sig`` to the child's process group (the child itself where groups are unavailable)."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(process.pid, sig)
        else:  # pragma: no cover - non-POSIX
            process.send_signal(sig)
    except (ProcessLookupError, PermissionError):
        pass


def _stop(process: subprocess.Popen[str]) -> tuple[str, str]:
    """Terminate the child's process group (SIGTERM, then SIGKILL) and return the output collected so far."""
    for sig in (signal.SIGTERM, getattr(signal, "SIGKILL", signal.SIGTERM)):
        _signal_group(process, sig)
        try:
            return process.communicate(timeout=TERMINATE_GRACE)
        except TimeoutExpired:
            continue
    process.kill()  # pipes still held by processes that left the group: give up on the remaining output
    return "", ""


def _communicate(
    args: list[str], *, cwd: Path | None, env: Mapping[str, str], input: str | None, timeout: float
) -> tuple[int, str, str]:
    """Run ``args`` in a new session and return (exit code, stdout, stderr); the group is stopped on timeout/interrupt."""
    with subprocess.Popen(
        args,
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        start_new_session=True,
    ) as process:
        try:
            stdout, stderr = process.communicate(input, timeout=timeout)
        except TimeoutExpired:
            stdout, stderr = _stop(process)
            raise TimeoutExpired(_redacted(args), timeout, output=stdout, stderr=stderr) from None
        except BaseException:
            _stop(process)
            raise
        return process.returncode, stdout, stderr


def run(
    argv: Sequence[str],
    *,
    cwd: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    timeout: float = 600,
    input: str | None = None,
    keep_home: bool = False,
    home: Path | None = None,
    check: bool = False,
) -> CompletedProcess[str]:
    """Run ``argv`` (never through a shell) with a sanitized env; captures text output, stdin is /dev/null unless input.

    Raises TimeoutExpired after ``timeout`` seconds (the child's process group is terminated first) and, with
    ``check``, CalledProcessError on a non-zero exit; both carry a redacted command.
    """
    args = [str(arg) for arg in argv]  # Path arguments are common
    if not args:
        raise ValueError("run() needs a command")
    env = sanitized_env(extra_env, home=home, keep_home=keep_home)
    if not keep_home:
        _prepare_home(env)
    shown = REDACTOR(shlex.join(args))
    _logger.debug("run: %s (cwd=%s)", shown, cwd)
    started = time.monotonic()
    try:
        returncode, stdout, stderr = _communicate(args, cwd=cwd, env=env, input=input, timeout=timeout)
    except TimeoutExpired:
        _logger.warning("timed out after %g s: %s", timeout, shown)
        raise
    _logger.debug("exit %s after %.1f s: %s", returncode, time.monotonic() - started, REDACTOR(args[0]))
    if check and returncode != 0:
        raise CalledProcessError(returncode, _redacted(args), stdout, stderr)
    return CompletedProcess(args, returncode, stdout, stderr)


def unshare_available() -> bool:
    """True when ``unshare -rn true`` succeeds (offline sandbox: new user + network namespace)."""
    try:
        return run(["unshare", "-rn", "true"], timeout=10, keep_home=True).returncode == 0
    except (OSError, TimeoutExpired):
        return False


# --- harness children (batch runs: one child process per target) ----------------------------------------------------
HARNESS_STOP_GRACE = 600.0  # seconds a harness child may clean up (lease release, sweep) after SIGTERM before SIGKILL
FORWARDED_SIGNALS = (signal.SIGINT, signal.SIGTERM)


class _HarnessChild:
    """A running harness child and how many of the forwarded signals it got (``lock``: one sender at a time)."""

    def __init__(self) -> None:
        """No signal delivered yet."""
        self.delivered = 0
        self.lock = threading.Lock()


_harness_children: dict[subprocess.Popen[str], _HarnessChild] = {}
_harness_lock = threading.RLock()  # re-entrant: the forwarding handler may interrupt the main thread holding it
_forwarded = threading.Event()  # set once a signal was forwarded (shared by nested forward_signals blocks)
_forwarded_signals: list[int] = []  # every signal forwarded since the outermost forward_signals block began
_forward_depth = 0


def _deliver(process: subprocess.Popen[str], child: _HarnessChild) -> None:
    """Send ``process`` every forwarded signal it did not get yet, each exactly once: whoever holds ``child.lock``
    sends (a handler interrupting a sender in the main thread, or racing one in a worker, leaves it to that sender,
    which checks again after sending)."""
    while child.delivered < len(_forwarded_signals):
        if not child.lock.acquire(blocking=False):  # atomic: a signal handler cannot interleave inside it
            return
        try:
            pending = _forwarded_signals[child.delivered :]
            child.delivered += len(pending)
        finally:
            child.lock.release()
        for signum in pending:
            _signal_group(process, signum)


def _forward_signal(signum: int, frame: object) -> None:
    """Signal handler of forward_signals(): send the signal to the process group of every running harness child (a
    child registered later gets it when it registers, _register_child)."""
    with _harness_lock:
        _forwarded_signals.append(signum)
        _forwarded.set()
        children = list(_harness_children.items())
    _logger.warning("forwarding signal %d to %d harness child process(es)", signum, len(children))
    for process, child in children:
        _deliver(process, child)


def _register_child(process: subprocess.Popen[str]) -> None:
    """Register a just-started harness child, then send it the signals forwarded before (a signal that arrived
    between Popen and the registration found no child to forward to)."""
    child = _HarnessChild()
    with _harness_lock:
        _harness_children[process] = child
    _deliver(process, child)


@contextlib.contextmanager
def forward_signals() -> Iterator[threading.Event]:
    """While the block runs, SIGINT and SIGTERM of this process are forwarded to the harness children of run_harness()
    instead of interrupting this process (each child cleans up and exits with its own code); the yielded Event is set
    once a signal was forwarded (callers start no further child). Handlers can only be installed by the main thread:
    elsewhere the block relies on an enclosing block of the main thread."""
    global _forward_depth
    if threading.current_thread() is not threading.main_thread():
        yield _forwarded
        return
    if _forward_depth == 0:
        with _harness_lock:
            _forwarded.clear()
            _forwarded_signals.clear()
    previous = {sig: signal.signal(sig, _forward_signal) for sig in FORWARDED_SIGNALS}
    _forward_depth += 1
    try:
        yield _forwarded
    finally:
        _forward_depth -= 1
        for sig, handler in previous.items():
            signal.signal(sig, signal.SIG_DFL if handler is None else handler)


def _open_log(path: Path) -> int:
    """File descriptor of a child's log file: appended, mode 0600, never through a symlink."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    return os.open(path, flags, 0o600)


def _stop_harness(process: subprocess.Popen[str]) -> None:
    """Ask a harness child's process group to stop (SIGTERM: every otterdog-e2e command turns it into a
    KeyboardInterrupt and cleans up, cli.TerminationGuard), keep draining its output while it cleans up, then SIGKILL
    after HARNESS_STOP_GRACE seconds."""
    _signal_group(process, signal.SIGTERM)
    try:
        process.communicate(timeout=HARNESS_STOP_GRACE)
    except (TimeoutExpired, ValueError, OSError):
        _signal_group(process, getattr(signal, "SIGKILL", signal.SIGTERM))
        with contextlib.suppress(TimeoutExpired, ValueError, OSError):
            process.communicate(timeout=TERMINATE_GRACE)


def run_harness(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
    on_line: Callable[[str], None],
    log_path: Path | None = None,
) -> int:
    """Run a harness child (``python -m otterdog_e2e ...``) to completion and return its exit code (a negative
    signal number when a signal killed it).

    Unlike run(), the child gets ``env`` unchanged: the parent's pristine environment (E2E_* settings and the
    credentials of CI included; never sanitized_env(), which strips them), so the child loads the env files of its
    own target itself. It runs in its own session with stdin /dev/null; stdout and stderr are merged and read line
    by line: each line is redacted, appended to ``log_path`` (0600) and handed to ``on_line`` (the caller prefixes
    ``[<target>] ``). SIGINT/SIGTERM of this process are forwarded to the child while it runs (forward_signals); if
    this process fails while reading (an exception in ``on_line``), the child is stopped first.
    """
    args = [str(arg) for arg in argv]  # Path arguments are common
    if not args:
        raise ValueError("run_harness() needs a command")
    _logger.debug("harness child: %s", REDACTOR(shlex.join(args)))
    log_fd = _open_log(log_path) if log_path is not None else None
    try:
        with (
            forward_signals(),
            subprocess.Popen(
                args,
                env=dict(env),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                encoding="utf-8",
                errors="replace",
                start_new_session=True,
            ) as process,
        ):
            _register_child(process)
            try:
                assert process.stdout is not None
                for raw in process.stdout:
                    line = REDACTOR(raw.rstrip("\r\n"))
                    if log_fd is not None:
                        os.write(log_fd, (line + "\n").encode("utf-8"))
                    on_line(line)
                return process.wait()
            except BaseException:
                _stop_harness(process)
                raise
            finally:
                with _harness_lock:
                    _harness_children.pop(process, None)
    finally:
        if log_fd is not None:
            os.close(log_fd)
