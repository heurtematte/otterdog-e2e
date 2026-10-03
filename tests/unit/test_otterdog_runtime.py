"""CLI runtimes (SPEC 10.7): host argv/env and the confined docker argv with path rewriting."""

from __future__ import annotations

import os
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import procs
from otterdog_e2e.otterdog import runtime as runtime_module
from otterdog_e2e.otterdog.runtime import (
    DockerRuntime,
    HostRuntime,
    container_name,
    container_scope,
    rewrite_path,
    runtime_for,
)
from otterdog_e2e.sut.cli_install import InstalledCli
from otterdog_e2e.sut.spec import ResolvedSut, SutSpec


def installed(runtime: str, *, image: str | None = None, binary: Path | None = None) -> InstalledCli:
    """InstalledCli of a fake SUT."""
    sut = ResolvedSut(
        spec=SutSpec("pr:792@" + "d" * 40, "pr", "792", "d" * 40),
        label="pr792-ddddddd",
        sha="d" * 40,
        version="1.7.0.dev3+e2e.gddddddd",
        image_version="1.7.0.dev3+e2e.gddddddd",
        source_dir=Path("/nonexistent/src"),
        repo_url="https://github.com/eclipse-csi/otterdog",
        trusted=runtime == "host",
    )
    return InstalledCli(sut, runtime, None, binary, image, "otterdog.sh, version 1.7.0")


def test_host_runtime() -> None:
    """[<venv>/bin/otterdog, *args]; credentials passed as extra env."""
    runtime = HostRuntime(installed("host", binary=Path("/venv/bin/otterdog")))
    assert runtime.command(["validate", "-c", "/ws/otterdog.json"], workdir=Path("/ws"), env_file=None) == [
        "/venv/bin/otterdog",
        "validate",
        "-c",
        "/ws/otterdog.json",
    ]
    assert runtime.env({"E2E_OTTERDOG_API_TOKEN": "t"}) == {"E2E_OTTERDOG_API_TOKEN": "t"}
    assert runtime.label == "host:pr792-ddddddd" and not runtime.in_container
    with pytest.raises(ValueError, match="no otterdog binary"):
        HostRuntime(installed("host")).command(["--version"], workdir=Path("/"), env_file=None)


@pytest.mark.parametrize("offline", [False, True])
def test_docker_runtime_argv(offline: bool) -> None:
    """Confinement flags of SPEC 10.7 (+ --init, unique --name, cap-drop/no-new-privileges), env-file, /ws mount,
    rewritten paths."""
    runtime = DockerRuntime(installed("docker", image="otterdog-e2e/untrusted:pr792-ddddddd"), offline=offline)
    workdir = Path("/scratch/ws")
    argv = runtime.command(
        ["plan", "-c", "/scratch/ws/otterdog.json", "-n", "-j", "/scratch/wsx/out.json", "e2e-test-org"],
        workdir=workdir,
        env_file=Path("/scratch/env/0001-plan.env"),
        name="otterdog-e2e-t3c7z8a5-0001",
    )
    expected = [
        "docker",
        "run",
        "--rm",
        "--init",
        "--name",
        "otterdog-e2e-t3c7z8a5-0001",
        "--read-only",
        "--tmpfs",
        "/tmp",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "-e",
        "HOME=/tmp",
        "-e",
        "COLUMNS=4096",
        "-e",
        "NO_COLOR=1",
        "-e",
        "PYTHON_DOTENV_DISABLED=1",
        "--env-file",
        "/scratch/env/0001-plan.env",
        "-v",
        "/scratch/ws:/ws",
        "-w",
        "/ws/cwd",
        *(["--network", "none"] if offline else []),
        "--entrypoint",
        "/app/.venv/bin/otterdog",
        "otterdog-e2e/untrusted:pr792-ddddddd",
        "plan",
        "-c",
        "/ws/otterdog.json",
        "-n",
        "-j",
        "/scratch/wsx/out.json",
        "e2e-test-org",
    ]
    assert argv == expected
    assert runtime.env({"E2E_OTTERDOG_API_TOKEN": "t"}) == {} and runtime.in_container
    assert not any("E2E_OTTERDOG_API_TOKEN" in arg for arg in argv)


@pytest.fixture
def scope() -> Iterator[str]:
    """Container names scoped to a fixed run id (restored afterwards)."""
    runtime_module.set_container_scope("t3c7z8a5")
    yield "t3c7z8a5"
    runtime_module.set_container_scope(None)


def test_container_names(scope: str) -> None:
    """otterdog-e2e-<run>-<seq>; without a name each command gets a fresh one; no run id: a per-process token."""
    assert container_name(7) == "otterdog-e2e-t3c7z8a5-0007"
    assert container_name("abc") == "otterdog-e2e-t3c7z8a5-abc"
    runtime = DockerRuntime(installed("docker", image="i"))

    def name_of(argv: list[str]) -> str:
        """Value of --name."""
        return argv[argv.index("--name") + 1]

    first = name_of(runtime.command(["--version"], workdir=Path("/w"), env_file=Path("/e")))
    second = name_of(runtime.command(["--version"], workdir=Path("/w"), env_file=Path("/e")))
    assert first != second and all(re.fullmatch(r"otterdog-e2e-t3c7z8a5-[0-9a-f]{8}", n) for n in (first, second))
    runtime_module.set_container_scope(None)
    assert re.fullmatch(r"otterdog-e2e-p[0-9a-f]{8}-0001", container_name(1))
    assert container_scope() == container_scope()  # stable within the process


class FakeDocker:
    """procs.run stand-in recording docker invocations (``outcome``: exit code or exception to raise)."""

    def __init__(self, outcome: int | BaseException = 0) -> None:
        """Answer every call with ``outcome``."""
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    def __call__(self, argv: list[str], **kwargs: Any) -> procs.CompletedProcess[str]:
        """Record, then return or raise."""
        self.calls.append({"argv": list(argv), **kwargs})
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return procs.CompletedProcess(argv, self.outcome, "", "Error: No such container" if self.outcome else "")


@pytest.mark.parametrize(
    ("outcome", "removed"),
    [(0, True), (1, False), (FileNotFoundError("docker"), False), (procs.TimeoutExpired(["docker"], 60), False)],
)
def test_docker_remove(monkeypatch: pytest.MonkeyPatch, outcome: int | BaseException, removed: bool) -> None:
    """docker rm -f <name> with the operator's docker config (keep_home); failures are logged, never raised."""
    docker = FakeDocker(outcome)
    monkeypatch.setattr(procs, "run", docker)
    assert DockerRuntime.remove("otterdog-e2e-t3c7z8a5-0003") is removed
    (call,) = docker.calls
    assert call["argv"] == ["docker", "rm", "-f", "otterdog-e2e-t3c7z8a5-0003"]
    assert call["keep_home"] is True and call["timeout"] == runtime_module.REMOVE_TIMEOUT


def test_docker_runtime_requires_image_and_env_file() -> None:
    """No image or no env-file is a configuration error."""
    with pytest.raises(ValueError, match="no image"):
        DockerRuntime(installed("docker")).command(["--version"], workdir=Path("/w"), env_file=Path("/e"))
    with pytest.raises(ValueError, match="env-file"):
        DockerRuntime(installed("docker", image="i")).command(["--version"], workdir=Path("/w"), env_file=None)


def test_rewrite_path() -> None:
    """Only paths under the workdir are rewritten to /ws."""
    assert rewrite_path("/a/b", Path("/a/b")) == "/ws"
    assert rewrite_path("/a/b/c/d.json", Path("/a/b/")) == "/ws/c/d.json"
    assert rewrite_path("/a/bc", Path("/a/b")) == "/a/bc"
    assert rewrite_path("validate", Path("/a")) == "validate"


def test_runtime_for() -> None:
    """Dispatch on InstalledCli.runtime; offline only matters for docker."""
    assert isinstance(runtime_for(installed("host", binary=Path("/b"))), HostRuntime)
    docker = runtime_for(installed("docker", image="i"), offline=True)
    assert isinstance(docker, DockerRuntime) and docker.offline
    with pytest.raises(ValueError, match="unknown CLI runtime"):
        runtime_for(installed("podman"))
