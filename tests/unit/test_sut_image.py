"""Webapp images (SPEC 10.5): docker build argv, labels, trust namespaces and reuse rules (docker is faked)."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from filelock import FileLock, Timeout

from otterdog_e2e import procs
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.sut.image import (
    OCI_VERSION_LABEL,
    REVISION_LABEL,
    TRUSTED_LABEL,
    VERSION_LABEL,
    BuiltImage,
    build_lock_path,
    build_webapp_image,
    check_extra_args,
    docker_available,
    prebuilt_image,
)
from otterdog_e2e.sut.spec import ResolvedSut, parse_sut_spec

SHA = "d0d3b0832d8e21a9da86e0ef967859d2634af894"
IMAGE_ID = "sha256:" + "ab" * 32


@dataclass
class FakeDocker:
    """procs.run stand-in answering docker sub-commands; ``images`` maps refs to inspect documents."""

    images: dict[str, dict[str, Any]] = field(default_factory=dict)
    build_rc: int = 0
    calls: list[list[str]] = field(default_factory=list)
    keep_home: list[bool] = field(default_factory=list)
    pullable: dict[str, dict[str, Any]] = field(default_factory=dict)

    def __call__(self, argv: list[str], *, cwd: Path | None = None, extra_env: dict[str, str] | None = None,
                 timeout: float = 600, input: str | None = None, keep_home: bool = False, home: Path | None = None,
                 check: bool = False) -> procs.CompletedProcess[str]:  # fmt: skip
        """Answer one docker command."""
        args = [str(arg) for arg in argv]
        self.calls.append(args)
        self.keep_home.append(keep_home)
        assert args[0] == "docker", args
        handler: Callable[[list[str]], tuple[int, str, str]] = {
            "image": self._inspect,
            "build": self._build,
            "pull": self._pull,
        }[args[1]]
        rc, out, err = handler(args)
        return procs.CompletedProcess(args, rc, out, err)

    def _inspect(self, args: list[str]) -> tuple[int, str, str]:
        """docker image inspect --format {{json .}} <ref>."""
        info = self.images.get(args[-1])
        return (0, json.dumps(info), "") if info else (1, "", f"Error: No such image: {args[-1]}")

    def _build(self, args: list[str]) -> tuple[int, str, str]:
        """docker build ... --iidfile <file> ...: writes the image id."""
        if self.build_rc:
            return self.build_rc, "", "ERROR: failed to solve: process did not complete successfully"
        Path(args[args.index("--iidfile") + 1]).write_text(IMAGE_ID)
        return 0, "", "#12 DONE 0.4s\n"

    def _pull(self, args: list[str]) -> tuple[int, str, str]:
        """docker pull <ref>."""
        if args[-1] not in self.pullable:
            return 1, "", "manifest unknown"
        self.images[args[-1]] = self.pullable[args[-1]]
        return 0, "", ""

    def builds(self) -> list[list[str]]:
        """Recorded docker build commands."""
        return [call for call in self.calls if call[1] == "build"]


@pytest.fixture()
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    """Patch procs.run with a FakeDocker (and clear E2E_DOCKER_BUILD_ARGS)."""
    fake = FakeDocker()
    monkeypatch.setattr(procs, "run", fake)
    monkeypatch.delenv("E2E_DOCKER_BUILD_ARGS", raising=False)
    return fake


def make_sut(tmp_path: Path, *, trusted: bool = True, dirty: bool = False) -> ResolvedSut:
    """A resolved SUT whose source dir has docker/Dockerfile."""
    label = "local-d0d3b08-dirty-1a2b3c4d" if dirty else ("main-d0d3b08" if trusted else "pr792-d0d3b08")
    version = "1.7.0.dev19+e2e.gd0d3b08" + (".dirty.1a2b3c4d" if dirty else "")
    image_version = "1.7.0.dev19+e2e.gd0d3b08" + (".dirty" if dirty else "")
    source = tmp_path / label
    (source / "docker").mkdir(parents=True)
    (source / "docker" / "Dockerfile").write_text("FROM scratch\n")
    spec = parse_sut_spec(("dirty:/x" if dirty else "main") if trusted else f"pr:792@{SHA}")
    return ResolvedSut(
        spec, label, SHA, version, image_version, source, "https://github.com/eclipse-csi/otterdog", trusted
    )


def _option_values(argv: list[str], option: str) -> list[str]:
    """Every value of a repeated ``--option value``."""
    return [argv[i + 1] for i, arg in enumerate(argv) if arg == option]


def test_build_trusted_image(tmp_path: Path, docker: FakeDocker) -> None:
    """docker build -f docker/Dockerfile --build-arg version=<image_version> + labels + trusted tag, context last."""
    sut = make_sut(tmp_path)
    image = build_webapp_image(sut)
    assert image == BuiltImage("otterdog-e2e/otterdog:main-d0d3b08", IMAGE_ID, sut.image_version, SHA, True)
    (argv,) = docker.builds()
    assert argv[:4] == ["docker", "build", "-f", "docker/Dockerfile"]
    assert _option_values(argv, "--build-arg") == [f"version={sut.image_version}"]
    assert sorted(_option_values(argv, "--label")) == sorted(
        [
            f"{REVISION_LABEL}={SHA}",
            f"{TRUSTED_LABEL}=true",
            f"{VERSION_LABEL}={sut.version}",
            f"{OCI_VERSION_LABEL}={sut.image_version}",
        ]
    )
    assert _option_values(argv, "-t") == ["otterdog-e2e/otterdog:main-d0d3b08"]
    assert argv[-1] == str(sut.source_dir)
    assert all(docker.keep_home)  # the docker CLI needs its own config


def test_dirty_build_uses_the_hash_free_version(tmp_path: Path, docker: FakeDocker) -> None:
    """F12: the build arg has no dirty hash, the labels keep it."""
    sut = make_sut(tmp_path, dirty=True)
    build_webapp_image(sut)
    (argv,) = docker.builds()
    assert _option_values(argv, "--build-arg") == ["version=1.7.0.dev19+e2e.gd0d3b08.dirty"]
    assert f"{VERSION_LABEL}=1.7.0.dev19+e2e.gd0d3b08.dirty.1a2b3c4d" in _option_values(argv, "--label")
    assert _option_values(argv, "-t") == ["otterdog-e2e/otterdog:local-d0d3b08-dirty-1a2b3c4d"]


def _labels(sut: ResolvedSut, **overrides: str) -> dict[str, Any]:
    """An inspect document with the labels of ``sut``."""
    labels = {
        REVISION_LABEL: sut.sha,
        TRUSTED_LABEL: "true" if sut.trusted else "false",
        VERSION_LABEL: sut.version,
        OCI_VERSION_LABEL: sut.image_version,
        **overrides,
    }
    return {"Id": "sha256:cached", "Config": {"Labels": labels}}


def test_trusted_image_reuse(tmp_path: Path, docker: FakeDocker) -> None:
    """A trusted tag is reused only if all harness labels match; force always rebuilds."""
    sut = make_sut(tmp_path)
    docker.images["otterdog-e2e/otterdog:main-d0d3b08"] = _labels(sut)
    image = build_webapp_image(sut)
    assert (image.image_id, image.trusted, docker.builds()) == ("sha256:cached", True, [])
    build_webapp_image(sut, force=True)
    assert len(docker.builds()) == 1
    for bad in ({REVISION_LABEL: "0" * 40}, {TRUSTED_LABEL: "false"}, {VERSION_LABEL: "1.6.1"}):
        docker.images["otterdog-e2e/otterdog:main-d0d3b08"] = _labels(sut, **bad)
        assert build_webapp_image(sut).image_id == IMAGE_ID
    assert len(docker.builds()) == 4


def test_untrusted_images_live_in_their_own_namespace_and_are_never_reused(tmp_path: Path, docker: FakeDocker) -> None:
    """otterdog-e2e/untrusted:<label>, trusted=false label, no inspect/reuse."""
    sut = make_sut(tmp_path, trusted=False)
    docker.images["otterdog-e2e/untrusted:pr792-d0d3b08"] = _labels(sut)
    image = build_webapp_image(sut)
    assert (image.tag, image.trusted, image.image_id) == ("otterdog-e2e/untrusted:pr792-d0d3b08", False, IMAGE_ID)
    (argv,) = docker.builds()
    assert f"{TRUSTED_LABEL}=false" in _option_values(argv, "--label")
    assert not [call for call in docker.calls if call[1] == "image"]


def test_builds_of_one_tag_hold_its_file_lock(tmp_path: Path, docker: FakeDocker) -> None:
    """The reuse check and the docker build run under ``<label>.image.lock`` next to the source (parallel sessions of
    one SUT build its image once); the lock is released afterwards, also after a failed build."""
    sut = make_sut(tmp_path)
    lock_path = build_lock_path(sut)
    assert lock_path == sut.source_dir.parent / "main-d0d3b08.image.lock"
    held: list[bool] = []
    build = docker._build

    def locked_build(args: list[str]) -> tuple[int, str, str]:
        """Check that another holder cannot take the lock during the build."""
        try:
            with FileLock(str(lock_path), timeout=0):
                held.append(False)
        except Timeout:
            held.append(True)
        return build(args)

    docker._build = locked_build  # type: ignore[method-assign]
    build_webapp_image(sut)
    assert held == [True]
    with FileLock(str(lock_path), timeout=0):
        pass  # released
    docker.build_rc = 1
    with pytest.raises(RuntimeError, match="docker build of"):
        build_webapp_image(sut, force=True)
    with FileLock(str(lock_path), timeout=0):
        pass  # released after the failure too
    untrusted = make_sut(tmp_path / "u", trusted=False)
    assert build_lock_path(untrusted) == untrusted.source_dir.parent / "pr792-d0d3b08.image.lock"


def test_a_concurrent_build_of_the_same_tag_waits_and_reuses_the_image(tmp_path: Path, docker: FakeDocker) -> None:
    """A second session (thread) building the same trusted tag waits for the first build, then reuses its image."""
    sut = make_sut(tmp_path)
    started, release = threading.Event(), threading.Event()
    build = docker._build

    def slow_build(args: list[str]) -> tuple[int, str, str]:
        """Build, wait for the test, then register the image as built (labels of the SUT)."""
        started.set()
        assert release.wait(10)
        result = build(args)
        docker.images["otterdog-e2e/otterdog:main-d0d3b08"] = _labels(sut)
        return result

    docker._build = slow_build  # type: ignore[method-assign]
    images: list[BuiltImage] = []
    first = threading.Thread(target=lambda: images.append(build_webapp_image(sut)))
    first.start()
    assert started.wait(10)
    second = threading.Thread(target=lambda: images.append(build_webapp_image(sut)))
    second.start()
    second.join(0.3)
    assert second.is_alive()  # waiting for the lock
    release.set()
    first.join(10)
    second.join(10)
    assert len(docker.builds()) == 1 and sorted(image.image_id for image in images) == sorted(
        [IMAGE_ID, "sha256:cached"]
    )


def test_extra_build_args_are_appended(tmp_path: Path, docker: FakeDocker, monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E_DOCKER_BUILD_ARGS then extra_args, before the context directory."""
    monkeypatch.setenv("E2E_DOCKER_BUILD_ARGS", "--network=host --build-arg 'HTTP_PROXY=http://proxy:3128'")
    sut = make_sut(tmp_path)
    build_webapp_image(sut, force=True, extra_args=["--platform", "linux/amd64"])
    (argv,) = docker.builds()
    assert argv[-6:] == [
        "--network=host",
        "--build-arg",
        "HTTP_PROXY=http://proxy:3128",
        "--platform",
        "linux/amd64",
        str(sut.source_dir),
    ]
    assert _option_values(argv, "--build-arg")[0] == f"version={sut.image_version}"


@pytest.mark.parametrize(
    "args",
    [
        ["-t", "otterdog-e2e/otterdog:main-d0d3b08"],
        ["--tag=x"],
        ["-tx"],
        ["-f", "Other.Dockerfile"],
        ["--file=Other"],
        ["--label", f"{TRUSTED_LABEL}=true"],
        [f"--label={REVISION_LABEL}=abc"],
        ["--build-arg", "version=9.9.9"],
        ["--iidfile", "/tmp/x"],
        ["--output", "type=local,dest=/"],
        ["--push"],
    ],
)
def test_extra_build_args_cannot_override_harness_values(args: list[str]) -> None:
    """Tag, Dockerfile, harness labels, the version build-arg and outputs stay under harness control."""
    with pytest.raises(SafetyError):
        check_extra_args(args)


def test_build_failures_and_missing_dockerfile(tmp_path: Path, docker: FakeDocker) -> None:
    """Build errors carry the output tail; a source without docker/Dockerfile is refused before docker runs."""
    docker.build_rc = 1
    with pytest.raises(RuntimeError, match="failed to solve"):
        build_webapp_image(make_sut(tmp_path / "a", trusted=False))
    sut = make_sut(tmp_path / "b", trusted=False)
    (sut.source_dir / "docker" / "Dockerfile").unlink()
    with pytest.raises(FileNotFoundError):
        build_webapp_image(sut)


def test_prebuilt_image_reads_labels_and_pulls_when_missing(docker: FakeDocker) -> None:
    """--e2e-webapp-image: inspect (pull first when absent); trust only from the harness label."""
    ref = "ghcr.io/eclipse-csi/otterdog:dev"
    docker.pullable[ref] = {
        "Id": "sha256:dev",
        "Config": {"Labels": {REVISION_LABEL: SHA, OCI_VERSION_LABEL: "1.7.0-SNAPSHOT"}},
    }
    image = prebuilt_image(ref)
    assert image == BuiltImage(ref, "sha256:dev", "1.7.0-SNAPSHOT", SHA, False)
    assert [call[1] for call in docker.calls] == ["image", "pull", "image"]
    with pytest.raises(RuntimeError, match="docker pull"):
        prebuilt_image("ghcr.io/eclipse-csi/otterdog:missing")


def test_docker_available(monkeypatch: pytest.MonkeyPatch) -> None:
    """True only when the daemon answers with a server version."""
    answers: list[Any] = [
        procs.CompletedProcess(["docker"], 0, "27.3.1\n", ""),
        procs.CompletedProcess(["docker"], 1, "", "Cannot connect"),
        OSError("no docker"),
    ]

    def fake(argv: list[str], **kw: Any) -> procs.CompletedProcess[str]:
        """Pop the next answer."""
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    monkeypatch.setattr(procs, "run", fake)
    assert docker_available() is True
    assert docker_available() is False
    assert docker_available() is False
