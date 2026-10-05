"""Docker images of the otterdog webapp built from a SUT (SPEC 10.5).

Trusted SUTs are tagged ``otterdog-e2e/otterdog:<label>``, untrusted ones ``otterdog-e2e/untrusted:<label>``; the
command-line labels (revision, trust, version) override any LABEL of the SUT's Dockerfile. Only a trusted tag whose
labels match exactly is reused; untrusted images are always rebuilt (the layer cache still applies). The build arg
``version`` is the hash-free image version so dirty edits keep the dependency layers cached (F12).

Builds of one tag are serialized across processes (a file lock next to the SUT source, ``<label>.image.lock``): the
sessions of a parallel batch testing the same SUT build its image once and the others reuse it.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from filelock import FileLock

from otterdog_e2e import procs
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.sut.spec import ResolvedSut

TRUSTED_IMAGE_REPO = "otterdog-e2e/otterdog"
UNTRUSTED_IMAGE_REPO = "otterdog-e2e/untrusted"
REVISION_LABEL = "org.opencontainers.image.revision"
TRUSTED_LABEL = "otterdog-e2e.trusted"
VERSION_LABEL = "otterdog-e2e.version"  # full SUT version (dirty hash included)
OCI_VERSION_LABEL = "org.opencontainers.image.version"  # the version baked into the image
DOCKERFILE = "docker/Dockerfile"
BUILD_ARGS_ENV = "E2E_DOCKER_BUILD_ARGS"
BUILD_TIMEOUT = 3600.0
PULL_TIMEOUT = 1800.0
BUILD_LOCK_TIMEOUT = BUILD_TIMEOUT + 600.0  # waiting for another session's build of the same tag
BUILD_LOCK_SUFFIX = ".image.lock"
# flags of E2E_DOCKER_BUILD_ARGS / extra_args that would override the tag, Dockerfile, labels or outputs
_FORBIDDEN_FLAGS = ("-t", "--tag", "-f", "--file", "--iidfile", "-o", "--output", "--push", "-q", "--quiet")
_PROTECTED_KEYS = {
    "--label": (REVISION_LABEL, TRUSTED_LABEL, VERSION_LABEL, OCI_VERSION_LABEL),
    "--build-arg": ("version",),
}

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BuiltImage:
    """A local docker image of the SUT webapp."""

    tag: str
    image_id: str
    version: str
    revision: str
    trusted: bool


def image_tag(sut: ResolvedSut) -> str:
    """otterdog-e2e/otterdog:<label> (trusted) or otterdog-e2e/untrusted:<label>."""
    return f"{TRUSTED_IMAGE_REPO if sut.trusted else UNTRUSTED_IMAGE_REPO}:{sut.label}"


def image_labels(sut: ResolvedSut) -> dict[str, str]:
    """Labels set on the docker build command line."""
    return {
        REVISION_LABEL: sut.sha,
        TRUSTED_LABEL: "true" if sut.trusted else "false",
        VERSION_LABEL: sut.version,
        OCI_VERSION_LABEL: sut.image_version,
    }


def _flag_value(args: Sequence[str], index: int) -> tuple[str, str | None]:
    """(flag, value) of ``args[index]`` for ``--flag=value`` or ``--flag value`` forms."""
    arg = args[index]
    if arg.startswith("--") and "=" in arg:
        flag, _, value = arg.partition("=")
        return flag, value
    return arg, args[index + 1] if index + 1 < len(args) else None


def check_extra_args(args: Sequence[str]) -> None:
    """SafetyError for extra build args that would change the tag, Dockerfile, outputs or harness labels."""
    for index, arg in enumerate(args):
        flag, value = _flag_value(args, index)
        short_attached = any(arg.startswith(f) and len(arg) > 2 for f in _FORBIDDEN_FLAGS if len(f) == 2)
        if flag in _FORBIDDEN_FLAGS or short_attached:
            raise SafetyError(f"docker build argument {arg!r} is not allowed (the harness sets it)")
        if flag in _PROTECTED_KEYS and value is not None and value.split("=", 1)[0] in _PROTECTED_KEYS[flag]:
            raise SafetyError(f"docker build argument {flag} {value!r} would override a harness value")


def _inspect(ref: str) -> dict[str, Any] | None:
    """``docker image inspect`` of one image (None when it does not exist locally); never written to artifacts."""
    result = procs.run(["docker", "image", "inspect", "--format", "{{json .}}", ref], keep_home=True, timeout=120)
    if result.returncode != 0:
        return None
    try:
        data = json.loads(result.stdout)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def _labels(info: Mapping[str, Any]) -> dict[str, str]:
    """Config.Labels of an inspected image."""
    return dict((info.get("Config") or {}).get("Labels") or {})


def build_lock_path(sut: ResolvedSut) -> Path:
    """File lock of the image build of ``sut``: ``<label>.image.lock`` next to its source (trusted sources live in
    ``<cache>/src``, untrusted exports in ``<cache>/untrusted``: one lock per tag). ``cache prune`` never removes a
    held one: a trusted lock goes with its pruned ``src/<label>`` entry, an untrusted one (its export is removed by
    its session) once nobody holds it."""
    return sut.source_dir.parent / f"{sut.label}{BUILD_LOCK_SUFFIX}"


def build_webapp_image(sut: ResolvedSut, *, force: bool = False, extra_args: Sequence[str] = ()) -> BuiltImage:
    """docker build -f docker/Dockerfile --build-arg version=<image_version> with revision/trust labels.

    Tag otterdog-e2e/otterdog:<label> (trusted) or otterdog-e2e/untrusted:<label>; a trusted tag is reused only if
    its revision label matches and otterdog-e2e.trusted=true; E2E_DOCKER_BUILD_ARGS are appended. The reuse check and
    the build hold the tag's file lock (build_lock_path): a concurrent session waits, then reuses the image.
    """
    lock_path = build_lock_path(sut)
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with FileLock(str(lock_path), timeout=BUILD_LOCK_TIMEOUT):
        return _build_locked(sut, force=force, extra_args=extra_args)


def _build_locked(sut: ResolvedSut, *, force: bool, extra_args: Sequence[str]) -> BuiltImage:
    """build_webapp_image under the tag's lock: reuse a matching trusted image, else docker build."""
    tag, labels = image_tag(sut), image_labels(sut)
    if sut.trusted and not force:
        info = _inspect(tag)
        if info is not None and all(_labels(info).get(key) == value for key, value in labels.items()):
            _logger.info("reusing the image %s (%s)", tag, str(info.get("Id", ""))[:19])
            return BuiltImage(tag, str(info.get("Id", "")), sut.image_version, sut.sha, True)
    if not (sut.source_dir / DOCKERFILE).is_file():
        raise FileNotFoundError(f"{sut.source_dir / DOCKERFILE} does not exist")
    extra = [*shlex.split(os.environ.get(BUILD_ARGS_ENV, "")), *extra_args]
    check_extra_args(extra)
    label_args = [item for key, value in labels.items() for item in ("--label", f"{key}={value}")]
    with tempfile.TemporaryDirectory(prefix="otterdog-e2e-iid-") as tmp:
        iidfile = Path(tmp) / "iid"
        argv = [
            "docker", "build", "-f", DOCKERFILE, "--build-arg", f"version={sut.image_version}", *label_args,
            "-t", tag, "--iidfile", str(iidfile), *extra, str(sut.source_dir),
        ]  # fmt: skip
        _logger.info("building %s from %s (version %s)", tag, sut.sha[:12], sut.image_version)
        result = procs.run(argv, cwd=sut.source_dir, keep_home=True, timeout=BUILD_TIMEOUT)
        if result.returncode != 0:
            tail = "\n".join((result.stdout + result.stderr).strip().splitlines()[-30:])
            raise RuntimeError(f"docker build of {tag} failed with exit {result.returncode}:\n{REDACTOR(tail)}")
        image_id = iidfile.read_text().strip() if iidfile.exists() else ""
    return BuiltImage(tag, image_id, sut.image_version, sut.sha, sut.trusted)


def prebuilt_image(ref: str) -> BuiltImage:
    """Describe an existing image (``--e2e-webapp-image``) from docker inspect (pulled when missing locally)."""
    info = _inspect(ref)
    if info is None:
        pulled = procs.run(["docker", "pull", ref], keep_home=True, timeout=PULL_TIMEOUT)
        if pulled.returncode != 0:
            raise RuntimeError(
                f"docker pull {ref} failed with exit {pulled.returncode}: {REDACTOR(pulled.stderr[-500:])}"
            )
        info = _inspect(ref)
        if info is None:
            raise RuntimeError(f"image {ref} cannot be inspected after pulling it")
    labels = _labels(info)
    version = labels.get(OCI_VERSION_LABEL) or labels.get(VERSION_LABEL) or ""
    revision = labels.get(REVISION_LABEL, "")
    return BuiltImage(ref, str(info.get("Id", "")), version, revision, labels.get(TRUSTED_LABEL) == "true")


def docker_available() -> bool:
    """True when the docker daemon answers (``docker version``)."""
    try:
        result = procs.run(["docker", "version", "--format", "{{.Server.Version}}"], keep_home=True, timeout=30)
    except (OSError, procs.TimeoutExpired):
        return False
    return result.returncode == 0 and bool(result.stdout.strip())
