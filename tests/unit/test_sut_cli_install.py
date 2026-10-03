"""Host CLI installs (SPEC 10.4) and the image CLI, with procs.run replaced by a recording fake (no poetry, no docker)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from otterdog_e2e import procs
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import HarnessSettings
from otterdog_e2e.sut import cli_install
from otterdog_e2e.sut.cli_install import (
    IMAGE_OTTERDOG_BIN,
    INSTALL_MARKER,
    PDV_VERSION,
    POETRY_VERSION,
    ensure_poetry_tool,
    grant_host_trust,
    image_cli,
    install_cli,
    installed_version,
)
from otterdog_e2e.sut.image import BuiltImage
from otterdog_e2e.sut.spec import ResolvedSut, parse_sut_spec

SHA = "9bdeb75f3e82a6cbd107d6bc3c9ec90392475c08"
VERSION = "1.7.0.dev15+e2e.g9bdeb75"


@dataclass
class Call:
    """One recorded procs.run call."""

    argv: list[str]
    cwd: Path | None
    env: dict[str, str]
    keep_home: bool


Handler = Callable[[Call], tuple[int, str, str]]


@dataclass
class FakeProcs:
    """procs.run stand-in: first matching handler answers (rc, stdout, stderr); unknown commands fail the test."""

    handlers: list[tuple[Callable[[list[str]], bool], Handler]] = field(default_factory=list)
    calls: list[Call] = field(default_factory=list)

    def on(self, match: Callable[[list[str]], bool], handler: Handler) -> FakeProcs:
        """Register a handler."""
        self.handlers.append((match, handler))
        return self

    def __call__(self, argv: list[str], *, cwd: Path | None = None, extra_env: dict[str, str] | None = None,
                 timeout: float = 600, input: str | None = None, keep_home: bool = False, home: Path | None = None,
                 check: bool = False) -> procs.CompletedProcess[str]:  # fmt: skip
        """Record and answer one command."""
        args = [str(arg) for arg in argv]
        call = Call(args, cwd, dict(extra_env or {}), keep_home)
        self.calls.append(call)
        for match, handler in self.handlers:
            if match(args):
                rc, out, err = handler(call)
                if check and rc:
                    raise procs.CalledProcessError(rc, args, out, err)
                return procs.CompletedProcess(args, rc, out, err)
        raise AssertionError(f"unexpected command {args}")

    def matching(self, word: str) -> list[Call]:
        """Calls whose argv contains ``word``."""
        return [call for call in self.calls if word in call.argv]


def _touch(path: Path) -> None:
    """Create an (empty) executable file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\n")
    path.chmod(0o755)


@dataclass
class Toolchain:
    """FakeProcs wired like python/pip/poetry/otterdog behave; ``reported`` is what otterdog --version prints."""

    fake: FakeProcs
    reported: str = VERSION
    sync_rc: int = 0

    def install(self, monkeypatch: pytest.MonkeyPatch) -> Toolchain:
        """Patch procs.run."""
        self.fake.on(lambda a: a[1:3] == ["-m", "venv"], self._venv)
        self.fake.on(lambda a: a[1:4] == ["-m", "pip", "install"], lambda c: (0, "Successfully installed poetry\n", ""))
        self.fake.on(
            lambda a: a[0].endswith("/bin/poetry") and a[-1] == "--version",
            lambda c: (0, f"Poetry (version {POETRY_VERSION})\n", ""),
        )
        self.fake.on(lambda a: "sync" in a, self._sync)
        self.fake.on(
            lambda a: a[0].endswith("/.venv/bin/otterdog"), lambda c: (0, f"otterdog.sh, version {self.reported}\n", "")
        )
        monkeypatch.setattr(procs, "run", self.fake)
        return self

    def _venv(self, call: Call) -> tuple[int, str, str]:
        """python -m venv <dir>."""
        venv = Path(call.argv[3])
        _touch(venv / "bin" / "python")
        _touch(venv / "bin" / "poetry")
        return 0, "", ""

    def _sync(self, call: Call) -> tuple[int, str, str]:
        """poetry -C <build> sync: creates <build>/.venv/bin/otterdog."""
        if self.sync_rc:
            return (
                self.sync_rc,
                "",
                "Because otterdog depends on nothing-real (9.9) which doesn't exist, solving failed.",
            )
        build = Path(call.argv[call.argv.index("-C") + 1])
        _touch(build / ".venv" / "bin" / "otterdog")
        return 0, "Installing the current project: otterdog (1.7.0.dev15)\n", ""


@pytest.fixture()
def settings(tmp_path: Path) -> HarnessSettings:
    """Harness settings rooted in tmp_path."""
    return HarnessSettings(
        tmp_path, tmp_path / "cache", tmp_path / "artifacts", "eclipse-csi/otterdog", tmp_path, tmp_path
    )


def make_sut(
    tmp_path: Path, *, trusted: bool = True, version: str = VERSION, label: str = "main-9bdeb75"
) -> ResolvedSut:
    """A resolved SUT with a tiny exported source tree."""
    source = tmp_path / "src" / label
    (source / "otterdog").mkdir(parents=True, exist_ok=True)
    (source / "pyproject.toml").write_text('[project]\nname = "otterdog"\n')
    (source / "otterdog" / "__init__.py").write_text("")
    spec = parse_sut_spec("main" if trusted else f"pr:792@{SHA}")
    return ResolvedSut(spec, label, SHA, version, version, source, "https://github.com/eclipse-csi/otterdog", trusted)


def test_install_cli_refuses_untrusted_suts(
    tmp_path: Path, settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """SEC-03: untrusted code never runs on the host (no command is even started)."""
    fake = FakeProcs()
    monkeypatch.setattr(procs, "run", fake)
    with pytest.raises(SafetyError, match="untrusted"):
        install_cli(make_sut(tmp_path, trusted=False), settings)
    assert fake.calls == []


def test_install_cli_locked_sync_in_a_build_copy(
    tmp_path: Path, settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool venv, build copy + sentinel .env files, poetry sync env/argv, --version check and the install marker."""
    tools = Toolchain(FakeProcs()).install(monkeypatch)
    sut = make_sut(tmp_path)
    installed = install_cli(sut, settings)
    build = settings.cache_dir / "build" / "main-9bdeb75-cli"
    assert (installed.runtime, installed.venv_dir, installed.image) == ("host", build / ".venv", None)
    assert installed.otterdog_bin == build / ".venv" / "bin" / "otterdog"
    assert installed.version_output == f"otterdog.sh, version {VERSION}"
    assert (build / "pyproject.toml").exists() and (build / "otterdog" / "__init__.py").exists()
    for sentinel in (build / ".env", settings.cache_dir / ".env"):
        assert sentinel.read_text() == "" and (sentinel.stat().st_mode & 0o777) == 0o600
    (sync,) = tools.fake.matching("sync")
    poetry = settings.cache_dir / "tools" / f"poetry-{POETRY_VERSION}" / "bin" / "poetry"
    assert sync.argv == [str(poetry), "-C", str(build), "sync", "--only", "main", "--no-interaction", "--no-ansi"]
    assert sync.env["POETRY_VIRTUALENVS_IN_PROJECT"] == "true"
    assert sync.env["POETRY_DYNAMIC_VERSIONING_BYPASS"] == VERSION
    assert sync.env["POETRY_NO_INTERACTION"] == "1"
    assert sync.env["POETRY_CACHE_DIR"] == str(settings.cache_dir / "poetry-cache")
    assert sync.env["PIP_CONFIG_FILE"] == os.devnull and not sync.keep_home
    marker = json.loads((build / INSTALL_MARKER).read_text())
    assert marker == {"label": "main-9bdeb75", "sha": SHA, "version": VERSION, "groups": ["main"]}
    assert not (sut.source_dir / ".venv").exists() and not (sut.source_dir / ".env").exists()  # source stays clean


def test_install_cli_reuse_groups_and_force(
    tmp_path: Path, settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A matching marker is reused (only --version runs); the app group or force trigger a new sync."""
    tools = Toolchain(FakeProcs()).install(monkeypatch)
    sut = make_sut(tmp_path)
    install_cli(sut, settings)
    install_cli(sut, settings)
    assert len(tools.fake.matching("sync")) == 1
    install_cli(sut, settings, with_app=True)
    assert tools.fake.matching("sync")[-1].argv[4:6] == ["--only", "main,app"]
    install_cli(sut, settings)  # main is a subset of main,app: reused
    assert len(tools.fake.matching("sync")) == 2
    install_cli(sut, settings, force=True)
    assert len(tools.fake.matching("sync")) == 3
    assert len(tools.fake.matching("venv")) == 1  # the tool venv is created once


def test_install_cli_verifies_the_version(
    tmp_path: Path, settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A CLI reporting another version (e.g. 0.0.0 without the plugin) fails; no marker is written."""
    Toolchain(FakeProcs(), reported="0.0.0").install(monkeypatch)
    with pytest.raises(RuntimeError, match=r"expected otterdog 1\.7\.0\.dev15"):
        install_cli(make_sut(tmp_path), settings)
    assert not (settings.cache_dir / "build" / "main-9bdeb75-cli" / INSTALL_MARKER).exists()


def test_install_cli_version_prefix_is_not_enough(
    tmp_path: Path, settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1.7.0.dev1 must not accept a CLI reporting 1.7.0.dev15."""
    Toolchain(FakeProcs(), reported="1.7.0.dev15").install(monkeypatch)
    with pytest.raises(RuntimeError, match="expected otterdog"):
        install_cli(make_sut(tmp_path, version="1.7.0.dev1+e2e.g9bdeb75"), settings)


def test_install_cli_reports_sync_failures(
    tmp_path: Path, settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """poetry sync errors surface with the output tail."""
    Toolchain(FakeProcs(), sync_rc=1).install(monkeypatch)
    with pytest.raises(RuntimeError, match="solving failed"):
        install_cli(make_sut(tmp_path), settings)


def test_install_cli_rejects_placeholder_versions(
    tmp_path: Path, settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """0.0.0.dev0 & co are refused before anything is built."""
    fake = FakeProcs()
    monkeypatch.setattr(procs, "run", fake)
    with pytest.raises(ValueError, match="placeholder"):
        install_cli(make_sut(tmp_path, version="0.0.0.dev0"), settings)
    assert fake.calls == []


def test_ensure_poetry_tool_pins_versions(settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Private venv with poetry==2.4.1 and poetry-dynamic-versioning[plugin]==1.10.0, binary wheels only, reused."""
    tools = Toolchain(FakeProcs()).install(monkeypatch)
    poetry = ensure_poetry_tool(settings)
    assert poetry == settings.cache_dir / "tools" / "poetry-2.4.1" / "bin" / "poetry"
    venv_call, pip_call = tools.fake.calls[0], tools.fake.calls[1]
    assert venv_call.argv == [sys.executable, "-m", "venv", str(poetry.parent.parent)]
    assert pip_call.argv[-4:] == [
        "--only-binary",
        ":all:",
        "poetry==2.4.1",
        f"poetry-dynamic-versioning[plugin]=={PDV_VERSION}",
    ]
    assert pip_call.env["PIP_CONFIG_FILE"] == os.devnull
    assert ensure_poetry_tool(settings) == poetry
    assert len(tools.fake.calls) == 3  # venv, pip, poetry --version: nothing more on reuse


def test_ensure_poetry_tool_checks_the_installed_version(
    settings: HarnessSettings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tool venv reporting another poetry is refused and not marked as ready."""
    other = FakeProcs().on(  # registered first: it wins over the Toolchain's poetry --version handler
        lambda a: a[0].endswith("/bin/poetry") and a[-1] == "--version", lambda c: (0, "Poetry (version 2.5.1)\n", "")
    )
    Toolchain(other).install(monkeypatch)
    with pytest.raises(RuntimeError, match=r"expected 2\.4\.1"):
        ensure_poetry_tool(settings)
    assert not (settings.cache_dir / "tools" / "poetry-2.4.1" / ".e2e-tool.json").exists()


def _image(sut: ResolvedSut, *, revision: str | None = None, trusted: bool | None = None) -> BuiltImage:
    """A BuiltImage of ``sut``."""
    trust = sut.trusted if trusted is None else trusted
    return BuiltImage(
        "otterdog-e2e/untrusted:pr792-9bdeb75", "sha256:feed", sut.image_version, revision or sut.sha, trust
    )


def test_image_cli_runs_the_version_check_confined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """runtime "docker", in-image otterdog, the image id (not the tag) is what runs; --version without network."""
    fake = FakeProcs().on(lambda a: a[:2] == ["docker", "run"], lambda c: (0, f"otterdog.sh, version {VERSION}\n", ""))
    monkeypatch.setattr(procs, "run", fake)
    sut = make_sut(tmp_path, trusted=False, label="pr792-9bdeb75")
    installed = image_cli(sut, _image(sut))
    assert (installed.runtime, installed.venv_dir, installed.image) == ("docker", None, "sha256:feed")
    assert installed.otterdog_bin == Path(IMAGE_OTTERDOG_BIN)
    (call,) = fake.calls
    assert call.keep_home and call.argv[-3:] == ["--entrypoint", IMAGE_OTTERDOG_BIN, "sha256:feed", "--version"][-3:]
    for flag in ("--rm", "--read-only", "--network"):
        assert flag in call.argv
    assert call.argv[call.argv.index("--network") + 1] == "none"
    assert call.argv[call.argv.index("--user") + 1] == f"{os.getuid()}:{os.getgid()}"


def test_image_cli_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Revision mismatch, a trusted label on untrusted code and a wrong version are refused."""
    fake = FakeProcs().on(lambda a: a[:2] == ["docker", "run"], lambda c: (0, "otterdog.sh, version 1.6.1\n", ""))
    monkeypatch.setattr(procs, "run", fake)
    sut = make_sut(tmp_path, trusted=False, label="pr792-9bdeb75")
    with pytest.raises(SafetyError, match="built from"):
        image_cli(sut, _image(sut, revision="0" * 40))
    with pytest.raises(SafetyError, match="labelled trusted"):
        image_cli(sut, _image(sut, trusted=True))
    with pytest.raises(RuntimeError, match="expected otterdog"):
        image_cli(sut, _image(sut))


def test_grant_host_trust(tmp_path: Path) -> None:
    """--e2e-trust-code: exact sha, interactive only, never in CI; returns a trusted copy."""
    sut = make_sut(tmp_path, trusted=False, label="pr792-9bdeb75")
    with pytest.raises(SafetyError, match="CI"):
        grant_host_trust(sut, SHA, interactive=True, environ={"CI": "true"})
    with pytest.raises(SafetyError, match="interactive"):
        grant_host_trust(sut, SHA, interactive=False, environ={})
    with pytest.raises(SafetyError, match="full sha"):
        grant_host_trust(sut, SHA[:7], interactive=True, environ={})
    trusted = grant_host_trust(sut, SHA.upper(), interactive=True, environ={"CI": "false"})
    assert trusted.trusted and not sut.trusted and trusted.sha == sut.sha


def test_installed_version_parsing() -> None:
    """click's version_option output."""
    assert installed_version("otterdog.sh, version 1.7.0.dev19+e2e.gd0d3b08\n") == "1.7.0.dev19+e2e.gd0d3b08"
    assert installed_version("garbage") is None
    assert cli_install.public_version("1.7.0.dev19+e2e.gd0d3b08") == "1.7.0.dev19"
