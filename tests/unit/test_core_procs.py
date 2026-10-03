"""WP-A: the subprocess gateway: sanitized environment, scratch HOME, redaction and process-group cleanup (SPEC 5.6)."""

from __future__ import annotations

import json
import logging
import os
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import procs
from otterdog_e2e.redact import Redactor

SPEC_REMOVED = {
    "E2E_ADMIN_TOKEN": "x",
    "E2E_ORG": "org",
    "e2e_lower": "x",
    "OTTERDOG_CONFIG_ROOT": "/real/configs",
    "OTTER_API_TOKEN": "x",
    "GITHUB_TOKEN": "x",
    "GH_TOKEN": "x",
    "GH_ENTERPRISE_TOKEN": "x",
    "GITHUB_PAT_ADMIN": "x",
    "ACTIONS_RUNTIME_TOKEN": "x",
    "ACTIONS_ID_TOKEN_REQUEST_URL": "https://x",
    "NPM_TOKEN": "x",
    "MY_SECRET": "x",
    "DB_PASSWORD": "x",
    "ADMIN_TOTP_SEED": "x",
    "SSH_AUTH_SOCK": "/tmp/ssh",
    "GIT_ASKPASS": "x",
    "SSH_ASKPASS": "x",
    "PYTHONPATH": "/x",
    "PYTHONSTARTUP": "/x",
    "VIRTUAL_ENV": "/venv",
    "PIP_INDEX_URL": "https://x",
    "PIP_EXTRA_INDEX_URL": "https://x",
    "FORCE_COLOR": "1",
}
HARDENING_REMOVED = {
    "AWS_SECRET_ACCESS_KEY": "x",
    "AWS_ACCESS_KEY_ID": "x",
    "POETRY_PYPI_TOKEN_PYPI": "x",
    "POETRY_HTTP_BASIC_PRIVATE_USERNAME": "x",
    "OPENAI_API_KEY": "x",
    "GOOGLE_APPLICATION_CREDENTIALS": "/x.json",
    "SOME_PRIVATE_KEY_PATH": "/x",
    "BW_SESSION": "x",
    "VAULT_ADDR": "https://vault",
    "VAULT_USERNAME": "x",
    "PASSWORD_STORE_DIR": "/x",
    "KUBECONFIG": "/x",
    "GNUPGHOME": "/x",
    "GIT_DIR": "/elsewhere/.git",
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "credential.helper",
    "GIT_SSH_COMMAND": "ssh -i key",
    "SSH_AGENT_PID": "1",
    "PIP_CONFIG_FILE": "/x",
    "PYTHONHOME": "/x",
    "PYTHONWARNINGS": "error",
    "GITHUB_ENV": "/runner/env",
    "GITHUB_OUTPUT": "/runner/out",
    "GITHUB_PATH": "/runner/path",
    "GITHUB_STATE": "/runner/state",
    "GITHUB_STEP_SUMMARY": "/runner/summary",
    "CLICOLOR_FORCE": "1",
    "PY_COLORS": "1",
    "TTY_COMPATIBLE": "1",
    "TTY_INTERACTIVE": "1",
}
KEPT = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "TMPDIR": "/tmp",
    "HTTPS_PROXY": "http://proxy:3128",
    "NO_PROXY": "localhost",
    "SSL_CERT_FILE": "/etc/ssl/cert.pem",
    "DOCKER_HOST": "unix:///run/user/1000/docker.sock",
    "DOCKER_CONFIG": "/home/operator/.docker",
    "GITHUB_ACTIONS": "true",
    "GITHUB_RUN_ID": "42",
    "CI": "true",
    "RUNNER_TEMP": "/runner/tmp",
    "USER": "operator",
}
BASE_ENV = {
    **SPEC_REMOVED,
    **HARDENING_REMOVED,
    **KEPT,
    "HOME": "/home/operator",
    "XDG_CONFIG_HOME": "/home/operator/.c",
}


@pytest.fixture
def redactor(monkeypatch: pytest.MonkeyPatch) -> Redactor:
    """A fresh Redactor used by procs (keeps the process-wide REDACTOR clean)."""
    fresh = Redactor()
    monkeypatch.setattr(procs, "REDACTOR", fresh)
    return fresh


@pytest.fixture
def fast_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Short SIGTERM -> SIGKILL grace period."""
    monkeypatch.setattr(procs, "TERMINATE_GRACE", 0.5)


def python(code: str) -> list[str]:
    """argv running ``code`` with the current interpreter."""
    return [sys.executable, "-c", textwrap.dedent(code)]


# --- sanitized_env --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("key", sorted(SPEC_REMOVED) + sorted(HARDENING_REMOVED))
def test_sanitized_env_removes_credentials_and_hooks(key: str, tmp_path: Path) -> None:
    """SPEC 5.6 removals plus credential-like names, credential stores and tool configuration of the operator."""
    assert key not in procs.sanitized_env(base=BASE_ENV, home=tmp_path)


def test_sanitized_env_keeps_neutral_variables(tmp_path: Path) -> None:
    """PATH, locale, proxies, CA bundles, docker endpoint and CI metadata reach children."""
    env = procs.sanitized_env(base=BASE_ENV, home=tmp_path)
    assert {key: env[key] for key in KEPT} == KEPT


def test_sanitized_env_sets_deterministic_output_and_scratch_home(tmp_path: Path) -> None:
    """SET_ENV and HOME/XDG (state included) below the scratch home override inherited values."""
    env = procs.sanitized_env(base=BASE_ENV, home=tmp_path / "home")
    assert {key: env[key] for key in procs.SET_ENV} == dict(procs.SET_ENV)
    assert env["PYTHONIOENCODING"] == "utf-8"
    assert env["PYTHON_KEYRING_BACKEND"] == "keyring.backends.null.Keyring"
    assert env["HOME"] == str(tmp_path / "home")
    assert env["XDG_CONFIG_HOME"] == str(tmp_path / "home" / ".config")
    assert env["XDG_STATE_HOME"] == str(tmp_path / "home" / ".local" / "state")
    assert not (tmp_path / "home").exists()


def test_sanitized_env_keep_home_and_extra_last(tmp_path: Path) -> None:
    """keep_home keeps the operator HOME/XDG (docker); extra wins over removals and SET_ENV."""
    extra = {"E2E_OTTERDOG_API_TOKEN": "tok", "COLUMNS": "80", "GITHUB_WEBHOOK_SECRET": "s"}
    env = procs.sanitized_env(extra, base=BASE_ENV, keep_home=True)
    assert env["HOME"] == "/home/operator"
    assert env["XDG_CONFIG_HOME"] == "/home/operator/.c"
    assert (env["E2E_OTTERDOG_API_TOKEN"], env["COLUMNS"], env["GITHUB_WEBHOOK_SECRET"]) == ("tok", "80", "s")


POETRY_PIP_INHERITED = {
    "POETRY_REPOSITORIES_PRIVATE_URL": "https://pypi.internal/simple",
    "POETRY_HTTP_BASIC_PRIVATE_USERNAME": "operator",
    "POETRY_HTTP_BASIC_PRIVATE_PASSWORD": "pypi-password",
    "POETRY_PYPI_TOKEN_PRIVATE": "pypi-token",
    "POETRY_VIRTUALENVS_PATH": "/home/operator/.venvs",
    "POETRY_CACHE_DIR": "/home/operator/.cache/pypoetry",
    "POETRY_HOME": "/home/operator/.poetry",
    "PIP_REQUIRE_VIRTUALENV": "true",
    "PIP_INDEX_URL": "https://user:pass@pypi.internal/simple",
    "PIP_TRUSTED_HOST": "pypi.internal",
    "PIP_CERT": "/home/operator/ca.pem",
    "pip_index_url": "https://lower-case.example/simple",
    "Poetry_Virtualenvs_In_Project": "false",
}


def _poetry_pip(env: dict[str, str]) -> dict[str, str]:
    """The POETRY_* / PIP_* entries of an environment (any case)."""
    return {key: value for key, value in env.items() if key.upper().startswith(("POETRY_", "PIP_"))}


def test_sanitized_env_drops_inherited_poetry_and_pip_variables(tmp_path: Path) -> None:
    """Every inherited ^POETRY_ / ^PIP_ variable (index credentials, repositories, virtualenv paths), whatever its
    case, is dropped; callers re-add exactly what they need through extra (applied last, e.g. cli_install)."""
    env = procs.sanitized_env(base={**POETRY_PIP_INHERITED, "PATH": "/usr/bin"}, home=tmp_path)
    assert _poetry_pip(env) == {} and env["PATH"] == "/usr/bin"
    extra = {"POETRY_CACHE_DIR": str(tmp_path / "poetry-cache"), "PIP_CONFIG_FILE": os.devnull}
    assert _poetry_pip(procs.sanitized_env(extra, base=POETRY_PIP_INHERITED, home=tmp_path)) == extra


def test_run_children_never_inherit_poetry_or_pip_configuration(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A real child sees only the POETRY_/PIP_ variables given in extra_env."""
    for key, value in POETRY_PIP_INHERITED.items():
        monkeypatch.setenv(key, value)
    code = "import json, os; print(json.dumps(dict(os.environ)))"
    result = procs.run(python(code), home=tmp_path / "home", extra_env={"POETRY_NO_INTERACTION": "1"})
    assert _poetry_pip(json.loads(result.stdout)) == {"POETRY_NO_INTERACTION": "1"}


def test_sanitized_env_stringifies_extra_values(tmp_path: Path) -> None:
    """Path (or other) values in extra become strings, as subprocess requires."""
    env = procs.sanitized_env({"POETRY_CACHE_DIR": tmp_path / "cache", "WORKERS": 2}, base={}, home=tmp_path)  # type: ignore[dict-item]
    assert (env["POETRY_CACHE_DIR"], env["WORKERS"]) == (str(tmp_path / "cache"), "2")


def test_sanitized_env_defaults_to_os_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without base, os.environ is filtered."""
    monkeypatch.setenv("E2E_WPA_TOKEN", "x")
    monkeypatch.setenv("WPA_NEUTRAL", "kept")
    env = procs.sanitized_env(home=tmp_path)
    assert "E2E_WPA_TOKEN" not in env and env["WPA_NEUTRAL"] == "kept"


# --- run ------------------------------------------------------------------------------------------------------------
def test_run_child_sees_only_the_sanitized_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Credentials of the harness process never reach the child; scratch HOME and extra env do."""
    for key in ("E2E_ADMIN_TOKEN", "GITHUB_TOKEN", "OTTERDOG_CONFIG_ROOT", "AWS_SECRET_ACCESS_KEY", "GIT_DIR"):
        monkeypatch.setenv(key, "must-not-leak")
    keys = ["E2E_ADMIN_TOKEN", "GITHUB_TOKEN", "OTTERDOG_CONFIG_ROOT", "AWS_SECRET_ACCESS_KEY", "GIT_DIR"]
    keys += ["HOME", "GIT_CONFIG_GLOBAL", "NETRC", "E2E_OTTERDOG_API_TOKEN"]
    code = f"import json, os; print(json.dumps({{k: os.environ.get(k) for k in {keys!r}}}))"
    home = tmp_path / "home"
    result = procs.run(python(code), home=home, extra_env={"E2E_OTTERDOG_API_TOKEN": "otterdog-only"})
    seen = json.loads(result.stdout)
    assert {key: seen[key] for key in keys[:5]} == dict.fromkeys(keys[:5])
    assert seen["HOME"] == str(home)
    assert (seen["GIT_CONFIG_GLOBAL"], seen["NETRC"], seen["E2E_OTTERDOG_API_TOKEN"]) == (
        "/dev/null",
        "/dev/null",
        "otterdog-only",
    )


def test_run_creates_a_private_scratch_home(tmp_path: Path) -> None:
    """HOME, its missing parents and the XDG dirs are created with mode 0700."""
    home = tmp_path / "a" / "b" / "home"
    procs.run(python("pass"), home=home)
    for directory in (tmp_path / "a", tmp_path / "a" / "b", home, home / ".config", home / ".local" / "state"):
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700, directory


def test_run_cwd_paths_input_and_result(tmp_path: Path) -> None:
    """cwd is honoured, Path arguments are accepted, input feeds stdin, the result is a CompletedProcess."""
    script = tmp_path / "echo.py"
    script.write_text("import os, sys\nprint(os.getcwd())\nprint(sys.stdin.read().strip())\n", encoding="utf-8")
    result = procs.run([Path(sys.executable), script], cwd=tmp_path, input="hello\n", home=tmp_path / "h")
    assert isinstance(result, subprocess.CompletedProcess)
    assert result.args == [sys.executable, str(script)]
    assert result.stdout.splitlines() == [str(tmp_path), "hello"]
    assert result.returncode == 0 and result.stderr == ""


def test_run_rejects_an_empty_command() -> None:
    """There is nothing to run."""
    with pytest.raises(ValueError, match="needs a command"):
        procs.run([])


def test_run_check_raises_with_a_redacted_command(tmp_path: Path, redactor: Redactor) -> None:
    """CalledProcessError keeps the output but masks secrets in the command."""
    redactor.add("wpa-argv-secret-1")
    with pytest.raises(subprocess.CalledProcessError) as info:
        procs.run([*python("import sys; print('out'); sys.exit(3)"), "wpa-argv-secret-1"], home=tmp_path, check=True)
    assert info.value.returncode == 3 and info.value.stdout == "out\n"
    assert "wpa-argv-secret-1" not in str(info.value) and "***" in str(info.value.cmd)
    assert procs.run(python("raise SystemExit(4)"), home=tmp_path).returncode == 4


def test_run_logs_a_redacted_command(tmp_path: Path, redactor: Redactor, caplog: pytest.LogCaptureFixture) -> None:
    """The DEBUG log line of every command is redacted."""
    redactor.add("wpa-argv-secret-2")
    with caplog.at_level(logging.DEBUG, logger="otterdog_e2e.procs"):
        procs.run([*python("pass"), "--token=wpa-argv-secret-2"], home=tmp_path)
    assert "--token=***" in caplog.text and "wpa-argv-secret-2" not in caplog.text


def _alive(pid: int) -> bool:
    """True while ``pid`` exists (zombies are reaped quickly by init)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _wait_gone(pid: int, timeout: float = 5.0) -> bool:
    """Wait until ``pid`` disappears."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def test_run_timeout_kills_the_whole_process_group(tmp_path: Path, redactor: Redactor, fast_grace: None) -> None:
    """On timeout the child AND its grandchildren are stopped; the partial output and a redacted command are kept."""
    redactor.add("wpa-argv-secret-3")
    code = """
        import subprocess, sys, time
        grandchild = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
        print(grandchild.pid, flush=True)
        time.sleep(60)
    """
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as info:
        procs.run([*python(code), "wpa-argv-secret-3"], home=tmp_path, timeout=1.0)
    assert time.monotonic() - started < 10
    grandchild = int(str(info.value.output).split()[0])
    assert _wait_gone(grandchild), "grandchild survived the timeout"
    assert "wpa-argv-secret-3" not in str(info.value)


def test_run_timeout_sends_sigterm_first(tmp_path: Path, fast_grace: None) -> None:
    """Children get SIGTERM first: a graceful handler can still flush its output."""
    code = """
        import signal, sys, time
        def bye(*_):
            print("graceful exit", flush=True)
            sys.exit(0)
        signal.signal(signal.SIGTERM, bye)
        print("ready", flush=True)
        time.sleep(60)
    """
    with pytest.raises(subprocess.TimeoutExpired) as info:
        procs.run(python(code), home=tmp_path, timeout=1.0)
    assert str(info.value.output).split() == ["ready", "graceful", "exit"]


def test_run_timeout_escalates_to_sigkill(tmp_path: Path, fast_grace: None) -> None:
    """A child ignoring SIGTERM is killed after the grace period."""
    code = """
        import signal, time
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        print("stubborn", flush=True)
        time.sleep(60)
    """
    started = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired) as info:
        procs.run(python(code), home=tmp_path, timeout=1.0)
    assert time.monotonic() - started < 10
    assert "stubborn" in str(info.value.output)


def test_run_interrupt_stops_the_child(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """KeyboardInterrupt (SIGINT, or SIGTERM via the plugin handler) stops the child group and propagates."""
    original = subprocess.Popen.communicate
    state = {"calls": 0}

    def interrupted(self: subprocess.Popen[str], input: str | None = None, timeout: float | None = None) -> Any:
        """Interrupt the first wait, then behave normally."""
        state["calls"] += 1
        if state["calls"] == 1:
            raise KeyboardInterrupt
        return original(self, input, timeout)

    stopped: list[subprocess.Popen[str]] = []
    real_stop = procs._stop

    def recording_stop(process: subprocess.Popen[str]) -> tuple[str, str]:
        """Remember which process was stopped."""
        stopped.append(process)
        return real_stop(process)

    monkeypatch.setattr(subprocess.Popen, "communicate", interrupted)
    monkeypatch.setattr(procs, "_stop", recording_stop)
    with pytest.raises(KeyboardInterrupt):
        procs.run(python("import time; time.sleep(60)"), home=tmp_path)
    assert len(stopped) == 1 and stopped[0].poll() is not None


# --- unshare --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (subprocess.CompletedProcess(["unshare"], 0, "", ""), True),
        (subprocess.CompletedProcess(["unshare"], 1, "", "unshare: Operation not permitted"), False),
        (FileNotFoundError("unshare"), False),
        (subprocess.TimeoutExpired(["unshare"], 10), False),
    ],
)
def test_unshare_available(monkeypatch: pytest.MonkeyPatch, outcome: Any, expected: bool) -> None:
    """True only when ``unshare -rn true`` exits 0; missing binaries and timeouts mean False."""
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(argv: list[str], **kwargs: Any) -> Any:
        """Record the call and return/raise the outcome."""
        calls.append((argv, kwargs))
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(procs, "run", fake_run)
    assert procs.unshare_available() is expected
    assert calls[0][0] == ["unshare", "-rn", "true"] and calls[0][1]["keep_home"] is True


def test_unshare_available_on_this_host() -> None:
    """The real probe returns a bool and never raises."""
    assert isinstance(procs.unshare_available(), bool)
