"""The only place that starts subprocesses (SPEC 5.6, SEC-10).

Every child gets a sanitized environment: credentials and interpreter/git/pip/ssh hooks of the operator are removed,
output is made deterministic (wide, colourless, unbuffered, UTF-8) and, unless ``keep_home``, HOME/XDG point at a
scratch home so the operator's dotfiles (~/.gitconfig, ~/.netrc, ~/.config/gh, ~/.vault-token, ~/.env) are never read.

Children run in their own session (process group): on timeout or interruption the whole group gets SIGTERM, then
SIGKILL after TERMINATE_GRACE seconds, so no grandchild (git, pip, a docker CLI) keeps running behind the harness.
Remote docker daemons over ``ssh://`` are not supported (SSH_AUTH_SOCK is removed for every child).
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import signal
import subprocess
import time
from collections.abc import Mapping, Sequence
from pathlib import Path
from subprocess import CalledProcessError, CompletedProcess, TimeoutExpired

from otterdog_e2e.redact import REDACTOR

__all__ = [
    "REMOVED_ENV_KEYS",
    "REMOVED_ENV_PATTERNS",
    "SET_ENV",
    "TERMINATE_GRACE",
    "CalledProcessError",
    "CompletedProcess",
    "TimeoutExpired",
    "default_home",
    "run",
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
