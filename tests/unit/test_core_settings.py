"""WP-A: harness settings, project root discovery, env files and ${VAR} expansion (SPEC 6.1)."""

from __future__ import annotations

import logging
import os
import stat
from pathlib import Path

import pytest

from otterdog_e2e import settings
from otterdog_e2e.redact import Redactor
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import (
    HarnessSettings,
    env_file_candidates,
    expand_env,
    find_project_root,
    harness_settings,
    load_env_files,
    parse_env_text,
    target_env_name,
    user_config_dir,
)

PROJECT = Path(__file__).resolve().parents[2]
RUN_ID = "t3c7z8a5"


@pytest.fixture
def redactor(monkeypatch: pytest.MonkeyPatch) -> Redactor:
    """A fresh Redactor used by settings (keeps the process-wide REDACTOR clean)."""
    fresh = Redactor()
    monkeypatch.setattr(settings, "REDACTOR", fresh)
    return fresh


def _project(root: Path, name: str = "otterdog-e2e") -> Path:
    """Create a directory with a pyproject.toml declaring ``name``."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text(f'[project]\nname = "{name}"\n', encoding="utf-8")
    return root


# --- expand_env -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("${A}", "alpha"),
        ("x-${A}-y", "x-alpha-y"),
        ("${UNSET}", ""),
        ("${UNSET:-fallback}", "fallback"),
        ("${EMPTY:-fallback}", "fallback"),
        ("${EMPTY}", ""),
        ("${A:-fallback}", "alpha"),
        ("${UNSET:-}", ""),
        ("${A}${B}", "alphabeta"),
        ("$A and $$ stay", "$A and $$ stay"),
        ("${REF}", "${A}"),  # values are never re-expanded
        ("${UNSET:-a b/c,d}", "a b/c,d"),
        ("plain", "plain"),
    ],
)
def test_expand_env(value: str, expected: str) -> None:
    """${VAR} and ${VAR:-default} with shell semantics; no recursion."""
    environ = {"A": "alpha", "B": "beta", "EMPTY": "", "REF": "${A}"}
    assert expand_env(value, environ) == expected


@pytest.mark.parametrize("value", ["${A", "${1A}", "${A:?error}", "${}", "x ${A-default}"])
def test_expand_env_rejects_malformed_references(value: str) -> None:
    """Anything that starts like a reference but is not one fails loudly."""
    with pytest.raises(ValueError, match="malformed variable reference"):
        expand_env(value, {"A": "x"})


# --- project root / settings ----------------------------------------------------------------------------------------
def test_find_project_root_from_nested_dir_and_file(tmp_path: Path) -> None:
    """The nearest pyproject.toml named otterdog-e2e wins; other projects are skipped."""
    root = _project(tmp_path / "proj")
    nested = _project(root / "sub" / "other", name="not-the-harness") / "deep"
    nested.mkdir()
    (nested / "file.txt").write_text("x", encoding="utf-8")
    assert find_project_root(nested) == root
    assert find_project_root(nested / "file.txt") == root


def test_find_project_root_ignores_broken_pyproject(tmp_path: Path) -> None:
    """Malformed pyproject files are not project roots."""
    root = _project(tmp_path / "proj")
    broken = root / "broken"
    broken.mkdir()
    (broken / "pyproject.toml").write_text("[project\nname=", encoding="utf-8")
    assert find_project_root(broken) == root


def test_find_project_root_not_found(tmp_path: Path) -> None:
    """An explicit start outside any project fails with a hint."""
    with pytest.raises(FileNotFoundError, match="E2E_PROJECT_ROOT"):
        find_project_root(tmp_path)


def test_find_project_root_defaults_to_cwd_then_package(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without start, cwd is searched first, then the package location (this checkout)."""
    monkeypatch.chdir(tmp_path)
    assert find_project_root() == PROJECT
    root = _project(tmp_path / "proj")
    monkeypatch.chdir(root)
    assert find_project_root() == root


def test_harness_settings_defaults(tmp_path: Path) -> None:
    """Defaults: ~/.cache/otterdog-e2e (HOME of environ, created 0700), <root>/artifacts, upstream otterdog."""
    root = _project(tmp_path / "proj")
    home = tmp_path / "home"
    config = harness_settings({"E2E_PROJECT_ROOT": str(root), "HOME": str(home)})
    assert config.project_root == root
    assert config.cache_dir == home / ".cache" / "otterdog-e2e"
    assert stat.S_IMODE(config.cache_dir.stat().st_mode) == 0o700
    assert config.artifacts_root == root / "artifacts"
    assert not config.artifacts_root.exists()
    assert config.upstream_repo == "eclipse-csi/otterdog"
    assert config.targets_dir == root / "targets"
    assert config.scenarios_dir == root / "scenarios"


def test_harness_settings_overrides(tmp_path: Path) -> None:
    """E2E_CACHE_DIR, E2E_ARTIFACTS and E2E_OTTERDOG_REPO override the defaults; '~' uses environ's HOME."""
    root = _project(tmp_path / "proj")
    environ = {
        "E2E_PROJECT_ROOT": str(root),
        "HOME": str(tmp_path / "home"),
        "E2E_CACHE_DIR": "~/my-cache",
        "E2E_ARTIFACTS": str(tmp_path / "out"),
        "E2E_OTTERDOG_REPO": "my-fork/otterdog",
    }
    config = harness_settings(environ)
    assert config.cache_dir == tmp_path / "home" / "my-cache"
    assert config.cache_dir.is_dir()
    assert config.artifacts_root == tmp_path / "out"
    assert config.upstream_repo == "my-fork/otterdog"


def test_harness_settings_uses_os_environ(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Without environ, os.environ is used and the project root is found from cwd."""
    root = _project(tmp_path / "proj")
    monkeypatch.delenv("E2E_PROJECT_ROOT", raising=False)
    monkeypatch.delenv("E2E_ARTIFACTS", raising=False)
    monkeypatch.delenv("E2E_OTTERDOG_REPO", raising=False)
    monkeypatch.setenv("E2E_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(root)
    config = harness_settings()
    assert config.project_root == root
    assert config.cache_dir == tmp_path / "cache"


@pytest.mark.parametrize("repo", ["otterdog", "a/b/c", "owner/re po", "-x/otterdog", "owner/repo;rm"])
def test_harness_settings_rejects_bad_upstream_repo(tmp_path: Path, repo: str) -> None:
    """E2E_OTTERDOG_REPO is interpolated into git URLs: only owner/name is accepted."""
    root = _project(tmp_path / "proj")
    environ = {"E2E_PROJECT_ROOT": str(root), "E2E_CACHE_DIR": str(tmp_path / "c"), "E2E_OTTERDOG_REPO": repo}
    with pytest.raises(ValueError, match="E2E_OTTERDOG_REPO"):
        harness_settings(environ)


@pytest.mark.parametrize("cache", ["out", "out/cache"])
def test_harness_settings_refuses_cache_inside_artifacts(tmp_path: Path, cache: str) -> None:
    """SEC-01: scratch dirs (credentials) must never be under the uploaded artifacts."""
    root = _project(tmp_path / "proj")
    environ = {
        "E2E_PROJECT_ROOT": str(root),
        "E2E_CACHE_DIR": str(tmp_path / cache),
        "E2E_ARTIFACTS": str(tmp_path / "out"),
    }
    with pytest.raises(SafetyError, match="must not be inside E2E_ARTIFACTS"):
        harness_settings(environ)
    assert not (tmp_path / cache).exists()


def test_harness_settings_missing_project_root(tmp_path: Path) -> None:
    """E2E_PROJECT_ROOT must be a directory."""
    with pytest.raises(FileNotFoundError):
        harness_settings({"E2E_PROJECT_ROOT": str(tmp_path / "missing"), "E2E_CACHE_DIR": str(tmp_path / "c")})


def test_scratch_is_private_and_rejects_path_tricks(tmp_path: Path) -> None:
    """scratch() creates cache_dir/run/<id> with 0700 and refuses ids that would escape it."""
    config = HarnessSettings(tmp_path, tmp_path / "cache", tmp_path / "artifacts", "o/r", tmp_path, tmp_path)
    scratch = config.scratch(RUN_ID)
    assert scratch == tmp_path / "cache" / "run" / RUN_ID
    assert stat.S_IMODE((tmp_path / "cache" / "run").stat().st_mode) == 0o700
    for bad in ("", ".", "..", "../x", "a/b", "a\\b", "a\0b"):
        with pytest.raises(ValueError, match="invalid run id"):
            config.scratch(bad)


def test_user_config_dir(tmp_path: Path) -> None:
    """~/.config/otterdog-e2e below HOME of environ."""
    assert user_config_dir({"HOME": str(tmp_path)}) == tmp_path / ".config" / "otterdog-e2e"


# --- env files ------------------------------------------------------------------------------------------------------
def test_parse_env_text_formats() -> None:
    """Comments, export, quotes (single literal, double with escapes), inline comments, no interpolation."""
    lines = [
        "# a comment",
        "",
        "PLAIN=value",
        "SPACED = spaced value  ",
        "export EXPORTED=1",
        "INLINE=abc # trailing comment",
        "HASH=abc#def",
        "SINGLE='lit $X \\n # not a comment'",
        'DOUBLE="a\\nb \\"q\\" \\\\ ${NOPE}"',
        "EMPTY=",
        "REF=${PLAIN}",
        "DUP=first",
        "DUP=second",
    ]
    assert parse_env_text("\n".join(lines)) == {
        "PLAIN": "value",
        "SPACED": "spaced value",
        "EXPORTED": "1",
        "INLINE": "abc",
        "HASH": "abc#def",
        "SINGLE": "lit $X \\n # not a comment",
        "DOUBLE": 'a\nb "q" \\ ${NOPE}',
        "EMPTY": "",
        "REF": "${PLAIN}",
        "DUP": "second",
    }


def test_parse_env_text_multiline_quoted_pem() -> None:
    """A quoted value may span lines (inline PEM keys)."""
    text = 'KEY="-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"\nNEXT=1\n'
    assert parse_env_text(text) == {
        "KEY": "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----",
        "NEXT": "1",
    }


def test_parse_env_text_skips_malformed_lines_without_values(caplog: pytest.LogCaptureFixture) -> None:
    """Malformed lines are skipped with a warning that never shows their content."""
    text = "this is not an assignment s3cr3t-value\n1BAD=x\nOK=1\nOPEN='never closed s3cr3t-value\n"
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.settings"):
        assert parse_env_text(text, source="f.env") == {"OK": "1"}
    assert "f.env:1" in caplog.text and "f.env:2" in caplog.text and "unterminated" in caplog.text
    assert "s3cr3t-value" not in caplog.text


def test_target_env_name() -> None:
    """Target names map to env file names; target file paths use their stem; odd names are refused."""
    assert target_env_name("free") == "free"
    assert target_env_name("targets/enterprise.yaml") == "enterprise"
    assert target_env_name("../elsewhere/free.yml") == "free"
    for bad in ("Free!", "", "a b", "x/Bad Name.yaml"):
        with pytest.raises(ValueError):
            target_env_name(bad)


def test_env_file_candidates_order(tmp_path: Path) -> None:
    """Precedence: user config file, project target file, project generic file."""
    environ = {"HOME": str(tmp_path / "home")}
    assert env_file_candidates("free", tmp_path, environ) == [
        tmp_path / "home" / ".config" / "otterdog-e2e" / "free.env",
        tmp_path / ".env.e2e.free",
        tmp_path / ".env.e2e",
    ]
    assert env_file_candidates(None, tmp_path, environ) == [tmp_path / ".env.e2e"]


def _write(path: Path, text: str, mode: int = 0o600) -> Path:
    """Write a file with ``mode``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    os.chmod(path, mode)
    return path


def test_load_env_files_precedence_and_no_override(tmp_path: Path, redactor: Redactor) -> None:
    """Earlier files win, the environment is never overridden, missing files are skipped."""
    home, root = tmp_path / "home", tmp_path / "proj"
    user = _write(home / ".config" / "otterdog-e2e" / "free.env", "E2E_ORG=from-user\nE2E_A=user\n")
    target = _write(root / ".env.e2e.free", "E2E_ORG=from-target\nE2E_B=target\nE2E_A=target\n")
    generic = _write(root / ".env.e2e", "E2E_ORG=from-generic\nE2E_C=generic\nE2E_EXISTING=file\n")
    environ = {"HOME": str(home), "E2E_EXISTING": "env"}
    assert load_env_files("free", root, environ) == [user, target, generic]
    assert environ == {
        "HOME": str(home),
        "E2E_EXISTING": "env",
        "E2E_ORG": "from-user",
        "E2E_A": "user",
        "E2E_B": "target",
        "E2E_C": "generic",
    }


def test_load_env_files_without_target_and_without_files(tmp_path: Path, redactor: Redactor) -> None:
    """Without a target only <root>/.env.e2e is read; no files -> nothing loaded."""
    root = tmp_path / "proj"
    environ = {"HOME": str(tmp_path / "home")}
    assert load_env_files(None, root, environ) == []
    generic = _write(root / ".env.e2e", "E2E_X=1\n")
    _write(root / ".env.e2e.free", "E2E_Y=1\n")
    assert load_env_files(None, root, environ) == [generic]
    assert "E2E_Y" not in environ


def test_load_env_files_registers_only_secret_keys(tmp_path: Path, redactor: Redactor) -> None:
    """SEC-09: only *_TOKEN/_SECRET/_PASSWORD/_TOTP_SEED/_PRIVATE_KEY values are registered (no over-redaction)."""
    root = tmp_path / "proj"
    _write(
        root / ".env.e2e",
        "E2E_ORG=wpa-org-not-secret\nE2E_ADMIN_TOKEN=wpa-admin-token-123\nE2E_APP_WEBHOOK_SECRET=wpa-hook-secret-9\n"
        "E2E_ADMIN_LOGIN=wpa-admin-login\nE2E_APP_PRIVATE_KEY_FILE=/x/wpa-key-path.pem\n",
    )
    environ = {
        "HOME": str(tmp_path / "home"),
        "E2E_ADMIN_TOKEN": "already-set-in-env",
        "CI_DEPLOY_PASSWORD": "wpa-ci-password-5",
        "E2E_OUTSIDER_LOGIN": "wpa-outsider-login",
    }
    load_env_files(None, root, environ)
    text = "wpa-org-not-secret wpa-admin-token-123 wpa-hook-secret-9 wpa-admin-login /x/wpa-key-path.pem"
    assert redactor(text) == "wpa-org-not-secret *** *** wpa-admin-login /x/wpa-key-path.pem"
    assert environ["E2E_ADMIN_TOKEN"] == "already-set-in-env"
    # secrets already in the environment (CI) are registered too; other values are not
    assert redactor("already-set-in-env wpa-ci-password-5 wpa-outsider-login") == "*** *** wpa-outsider-login"


def test_load_env_files_warns_about_shared_files(
    tmp_path: Path, redactor: Redactor, caplog: pytest.LogCaptureFixture
) -> None:
    """Secrets files readable by group/others are reported."""
    root = tmp_path / "proj"
    _write(root / ".env.e2e", "E2E_X=1\n", mode=0o644)
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.settings"):
        load_env_files(None, root, {"HOME": str(tmp_path / "home")})
    assert "chmod 600" in caplog.text


def test_load_env_files_defaults_to_os_environ(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, redactor: Redactor
) -> None:
    """Without environ the files fill os.environ (HOME of the process for the user file)."""
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("E2E_WPA_LOADED", "placeholder")  # registers the variable for removal after the test
    monkeypatch.delenv("E2E_WPA_LOADED")
    root = tmp_path / "proj"
    _write(tmp_path / "home" / ".config" / "otterdog-e2e" / "free.env", "E2E_WPA_LOADED=yes\n")
    assert load_env_files("free", root) == [tmp_path / "home" / ".config" / "otterdog-e2e" / "free.env"]
    assert os.environ["E2E_WPA_LOADED"] == "yes"
