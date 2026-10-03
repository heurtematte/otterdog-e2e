"""Host installation of the otterdog CLI for trusted SUTs (SPEC 10.4).

Untrusted SUTs never run on the host: install_cli raises SafetyError for them (unless ``--e2e-trust-code <sha>`` was
given interactively, refused in CI: see grant_host_trust); they run through image_cli (the CLI inside the SUT image).

Installs use a private Poetry tool venv (never the operator's poetry: Poetry 2 installs a project's
``requires-plugins`` next to Poetry and writes their console scripts into Poetry's own bin directory) and a locked
``poetry sync`` in a build copy of the exported source, with POETRY_DYNAMIC_VERSIONING_BYPASS set to the computed
version because exports carry no git history.

The web-UI tier (docs/web-ui-testing.md) also needs the Firefox build of the SUT's Playwright: ensure_playwright_firefox
runs ``<venv>/bin/python -m playwright install firefox`` (what ``otterdog install-deps`` does) with
``PLAYWRIGHT_BROWSERS_PATH=<E2E_CACHE_DIR>/ms-playwright`` (the scratch HOME of children would hide the default
``~/.cache/ms-playwright``), for trusted host installs only. Its system libraries are not installed (that needs root:
``playwright install-deps firefox`` on the CI runner, see .github/workflows/e2e-webui.yml).
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import re
import shutil
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from filelock import FileLock

from otterdog_e2e import procs
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.sut.source import check_tree_symlinks
from otterdog_e2e.sut.version import public_version, validate_version

if TYPE_CHECKING:
    from otterdog_e2e.settings import HarnessSettings
    from otterdog_e2e.sut.image import BuiltImage
    from otterdog_e2e.sut.spec import ResolvedSut

POETRY_VERSION = "2.4.1"
PDV_VERSION = "1.10.0"
IMAGE_OTTERDOG_BIN = "/app/.venv/bin/otterdog"
INSTALL_MARKER = ".e2e-installed.json"
TOOL_MARKER = ".e2e-tool.json"
RUNTIMES = ("host", "docker")
TOOL_TIMEOUT = 1200.0
SYNC_TIMEOUT = 1800.0
VERSION_TIMEOUT = 300.0
PLAYWRIGHT_TIMEOUT = 1800.0  # browser download (about 100 MB)
PLAYWRIGHT_BROWSERS_DIR = "ms-playwright"  # below E2E_CACHE_DIR, shared by the trusted SUTs (one dir per build)
PLAYWRIGHT_BROWSERS_ENV = "PLAYWRIGHT_BROWSERS_PATH"
CONTAINER_TMP = "/tmp"  # noqa: S108 - a tmpfs inside the container, not a host path
# pip never reads the operator's pip.conf (index credentials, proxies) and never prompts
PIP_ENV: Mapping[str, str] = {"PIP_CONFIG_FILE": os.devnull, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INPUT": "1"}
_VERSION_OUTPUT_RE = re.compile(r"version\s+(\S+)")

_logger = logging.getLogger(__name__)


@dataclass
class InstalledCli:
    """An otterdog CLI ready to run: a host venv (runtime "host") or the CLI inside an image (runtime "docker")."""

    sut: ResolvedSut
    runtime: str
    venv_dir: Path | None
    otterdog_bin: Path | None
    image: str | None
    version_output: str


def _tail(text: str, lines: int = 25) -> str:
    """Last lines of a command output, redacted."""
    return REDACTOR("\n".join(text.strip().splitlines()[-lines:]))


def _checked(result: procs.CompletedProcess[str], what: str) -> procs.CompletedProcess[str]:
    """RuntimeError with the output tail when a command failed."""
    if result.returncode != 0:
        raise RuntimeError(f"{what} failed with exit {result.returncode}:\n{_tail(result.stdout + result.stderr)}")
    return result


def _read_json(path: Path) -> dict[str, Any] | None:
    """A JSON object from ``path`` (None when missing or invalid)."""
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_sentinel(path: Path) -> None:
    """Empty ``.env``: python-dotenv's upward search (otterdog's env provider) stops here, before $HOME."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_text("")
    path.chmod(0o600)


def ensure_poetry_tool(settings: HarnessSettings) -> Path:
    """Private poetry venv cache_dir/tools/poetry-<POETRY_VERSION> with poetry-dynamic-versioning; returns its poetry."""
    tools = settings.cache_dir / "tools"
    tools.mkdir(mode=0o700, parents=True, exist_ok=True)
    venv = tools / f"poetry-{POETRY_VERSION}"
    poetry, marker = venv / "bin" / "poetry", venv / TOOL_MARKER
    expected = {"poetry": POETRY_VERSION, "pdv": PDV_VERSION}
    with FileLock(str(tools / f"poetry-{POETRY_VERSION}.lock"), timeout=TOOL_TIMEOUT):
        if poetry.exists() and _read_json(marker) == expected:
            return poetry
        _logger.info("creating the poetry %s tool venv %s", POETRY_VERSION, venv)
        shutil.rmtree(venv, ignore_errors=True)
        _checked(procs.run([sys.executable, "-m", "venv", str(venv)], timeout=VERSION_TIMEOUT), "python -m venv")
        packages = [f"poetry=={POETRY_VERSION}", f"poetry-dynamic-versioning[plugin]=={PDV_VERSION}"]
        pip = [str(venv / "bin" / "python"), "-m", "pip", "install", "--only-binary", ":all:", *packages]
        _checked(procs.run(pip, extra_env=PIP_ENV, timeout=TOOL_TIMEOUT), "pip install poetry")
        out = _checked(procs.run([str(poetry), "--version"], timeout=VERSION_TIMEOUT), "poetry --version").stdout
        if POETRY_VERSION not in out:
            raise RuntimeError(f"{poetry} reports {out.strip()!r}, expected {POETRY_VERSION}")
        marker.write_text(json.dumps(expected))
    return poetry


def poetry_env(sut: ResolvedSut, settings: HarnessSettings) -> dict[str, str]:
    """Environment of ``poetry sync``: in-project venv from Poetry's own python, bypass version, private cache."""
    return {
        "POETRY_VIRTUALENVS_IN_PROJECT": "true",
        "POETRY_VIRTUALENVS_CREATE": "true",
        "POETRY_VIRTUALENVS_USE_POETRY_PYTHON": "true",
        "POETRY_DYNAMIC_VERSIONING_BYPASS": sut.version,
        "POETRY_NO_INTERACTION": "1",
        "POETRY_CACHE_DIR": str(settings.cache_dir / "poetry-cache"),
        **PIP_ENV,
    }


def installed_version(output: str) -> str | None:
    """Version printed by ``otterdog --version`` ("otterdog.sh, version 1.7.0.dev19+e2e.gd0d3b08")."""
    match = _VERSION_OUTPUT_RE.search(output)
    return match.group(1) if match else None


def check_version_output(sut: ResolvedSut, output: str, *, what: str) -> None:
    """RuntimeError unless ``--version`` output names the SUT's public version."""
    found = installed_version(output)
    expected = public_version(sut.version)
    if found is None or public_version(found) != expected:
        raise RuntimeError(f"{what} prints {output.strip()!r}, expected otterdog {expected}")
    if found not in (sut.version, sut.image_version):
        _logger.warning("%s reports %s instead of %s", what, found, sut.version)


def _verified_host_cli(sut: ResolvedSut, build: Path) -> InstalledCli:
    """InstalledCli of the build venv after checking its ``otterdog --version``."""
    otterdog = build / ".venv" / "bin" / "otterdog"
    if not otterdog.exists():
        raise RuntimeError(f"{otterdog} was not installed")
    result = procs.run([str(otterdog), "--version"], cwd=build, timeout=VERSION_TIMEOUT)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"{otterdog} --version failed with exit {result.returncode}:\n{_tail(result.stderr)}")
    check_version_output(sut, output, what=str(otterdog))
    return InstalledCli(sut, "host", build / ".venv", otterdog, None, output)


def _reusable(sut: ResolvedSut, build: Path, groups: Sequence[str]) -> InstalledCli | None:
    """The existing install when its marker matches (sha, version, groups) and ``--version`` still works."""
    marker = _read_json(build / INSTALL_MARKER)
    if marker is None or marker.get("sha") != sut.sha or marker.get("version") != sut.version:
        return None
    if not set(groups) <= set(marker.get("groups") or ()):
        return None
    try:
        return _verified_host_cli(sut, build)
    except RuntimeError as ex:
        _logger.info("rebuilding %s: %s", build, ex)
        return None


def _prepare_build(sut: ResolvedSut, build: Path) -> None:
    """Fresh build copy of the exported source (symlinks kept as links, re-checked) with a sentinel .env."""
    if build.exists():
        shutil.rmtree(build)
    shutil.copytree(sut.source_dir, build, symlinks=True)
    check_tree_symlinks(build)
    _write_sentinel(build / ".env")


def install_cli(
    sut: ResolvedSut, settings: HarnessSettings, *, with_app: bool = False, force: bool = False
) -> InstalledCli:
    """``poetry -C <build> sync --only main[,app]`` in cache_dir/build/<label>-cli; verifies ``--version``.

    SafetyError if not sut.trusted; writes sentinel .env files at <build>/.env and cache_dir/.env; env
    POETRY_VIRTUALENVS_IN_PROJECT=true POETRY_DYNAMIC_VERSIONING_BYPASS=<version> POETRY_NO_INTERACTION=1
    POETRY_CACHE_DIR=cache_dir/poetry-cache; marker .e2e-installed.json {sha, version}.
    """
    if not sut.trusted:
        raise SafetyError(f"SUT {sut.label} is untrusted: it only runs inside its docker image (image_cli)")
    validate_version(sut.version)
    groups = ["main", "app"] if with_app else ["main"]
    build = settings.cache_dir / "build" / f"{sut.label}-cli"
    build.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    _write_sentinel(settings.cache_dir / ".env")
    with FileLock(str(build.parent / f"{sut.label}-cli.lock"), timeout=SYNC_TIMEOUT):
        reused = None if force else _reusable(sut, build, groups)
        if reused is not None:
            _logger.info("reusing the otterdog CLI %s (%s)", build, reused.version_output)
            return reused
        poetry = ensure_poetry_tool(settings)
        _prepare_build(sut, build)
        argv = [str(poetry), "-C", str(build), "sync", "--only", ",".join(groups), "--no-interaction", "--no-ansi"]
        _logger.info("installing otterdog %s (%s) into %s", sut.version, sut.label, build)
        result = procs.run(argv, cwd=build, extra_env=poetry_env(sut, settings), timeout=SYNC_TIMEOUT)
        _checked(result, f"poetry sync of {sut.label}")
        installed = _verified_host_cli(sut, build)
        marker = {"label": sut.label, "sha": sut.sha, "version": sut.version, "groups": groups}
        (build / INSTALL_MARKER).write_text(json.dumps(marker))
    return installed


def image_version_argv(image: str) -> list[str]:
    """``docker run`` of ``otterdog --version`` inside an image, confined like DockerRuntime (no network)."""
    return [
        "docker", "run", "--rm", "--network", "none", "--read-only", "--tmpfs", CONTAINER_TMP,
        "--user", f"{os.getuid()}:{os.getgid()}", "-e", f"HOME={CONTAINER_TMP}", "-e", "PYTHON_DOTENV_DISABLED=1",
        "--entrypoint", IMAGE_OTTERDOG_BIN, image, "--version",
    ]  # fmt: skip


def image_cli(sut: ResolvedSut, image: BuiltImage) -> InstalledCli:
    """InstalledCli of runtime "docker": the CLI inside the webapp image (/app/.venv/bin/otterdog)."""
    if image.revision and image.revision != sut.sha:
        raise SafetyError(f"image {image.tag} was built from {image.revision[:12]}, not from {sut.sha[:12]}")
    if image.trusted and not sut.trusted:
        raise SafetyError(f"image {image.tag} is labelled trusted but SUT {sut.label} is untrusted")
    ref = image.image_id or image.tag
    result = procs.run(image_version_argv(ref), keep_home=True, timeout=VERSION_TIMEOUT)
    output = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"otterdog --version in {image.tag} failed with exit {result.returncode}:\n{_tail(output)}")
    check_version_output(sut, output, what=f"image {image.tag}")
    return InstalledCli(sut, "docker", None, Path(IMAGE_OTTERDOG_BIN), ref, output)


def grant_host_trust(
    sut: ResolvedSut, trust_code: str, *, interactive: bool, environ: Mapping[str, str] | None = None
) -> ResolvedSut:
    """``--e2e-trust-code <sha>``: a copy of an untrusted SUT allowed on the host (exact sha, interactive, never CI)."""
    env = os.environ if environ is None else environ
    if env.get("CI", "").strip().lower() not in ("", "0", "false"):
        raise SafetyError("--e2e-trust-code is refused when CI is set")
    if not interactive:
        raise SafetyError("--e2e-trust-code is only accepted from an interactive terminal")
    if trust_code.strip().lower() != sut.sha:
        raise SafetyError(f"--e2e-trust-code {trust_code!r} is not the full sha {sut.sha} of {sut.label}")
    _logger.warning("operator trusts %s (%s): it will be installed and run on the host", sut.label, sut.sha)
    return dataclasses.replace(sut, trusted=True)


def playwright_browsers_path(settings: HarnessSettings) -> Path:
    """``<E2E_CACHE_DIR>/ms-playwright``: the Playwright browsers of the web-UI tier (never under the artifacts)."""
    return settings.cache_dir / PLAYWRIGHT_BROWSERS_DIR


def firefox_installed(settings: HarnessSettings) -> list[str]:
    """Names of the Playwright Firefox builds present in the browsers dir (``firefox-<revision>``)."""
    path = playwright_browsers_path(settings)
    if not path.is_dir():
        return []
    return sorted(entry.name for entry in path.iterdir() if entry.is_dir() and entry.name.startswith("firefox-"))


def ensure_playwright_firefox(installed: InstalledCli, settings: HarnessSettings) -> Path:
    """``<venv>/bin/python -m playwright install firefox`` into playwright_browsers_path() (idempotent, locked).

    Runs the SUT's own Playwright, so only trusted host installs qualify (SafetyError otherwise); returns the path to
    pass as PLAYWRIGHT_BROWSERS_PATH.
    """
    if installed.runtime != "host" or installed.venv_dir is None:
        raise SafetyError(f"Playwright browsers are installed for host CLIs only ({installed.sut.label})")
    if not installed.sut.trusted:
        raise SafetyError(f"SUT {installed.sut.label} is untrusted: its Playwright never runs on the host")
    python = installed.venv_dir / "bin" / "python"
    if not python.exists():
        raise RuntimeError(f"{python} does not exist: reinstall the SUT")
    path = playwright_browsers_path(settings)
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)
    env = {**PIP_ENV, PLAYWRIGHT_BROWSERS_ENV: str(path)}
    with FileLock(str(path.parent / f"{PLAYWRIGHT_BROWSERS_DIR}.lock"), timeout=PLAYWRIGHT_TIMEOUT):
        _logger.info("installing the Playwright Firefox of %s into %s", installed.sut.label, path)
        argv = [str(python), "-m", "playwright", "install", "firefox"]
        result = procs.run(argv, cwd=installed.venv_dir.parent, extra_env=env, timeout=PLAYWRIGHT_TIMEOUT)
        _checked(result, f"playwright install firefox ({installed.sut.label})")
    return path
