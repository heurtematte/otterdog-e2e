"""How an installed otterdog CLI is executed: on the host or inside the SUT docker image (SPEC 10.7, 5.5).

DockerRuntime confines untrusted SUTs: ``docker run --rm -i --read-only --tmpfs /tmp --user uid:gid -e HOME=/tmp``,
the workspace bind-mounted at /ws, an 0600 env-file holding ONLY the E2E_OTTERDOG_* credentials (plus the non-secret
OTTERDOG_CONFIG_ROOT and OTTERDOG_STATS_FILE paths), ``--network none`` when offline, entrypoint
/app/.venv/bin/otterdog; paths inside args are rewritten from the workdir to /ws. On top of the SPEC flags it drops
every capability and forbids privilege escalation (the CLI needs neither). ``-i`` forwards stdin (the answer to a prompt; /dev/null when the command gets no input), without a TTY.

The images ship no bytecode and set PYTHONDONTWRITEBYTECODE, so on the read-only root every command compiled all the
modules it imports (about 1.2 s of the 2 s of an offline validate). Offline commands of an image identified by its id
therefore write and read their bytecode in a host directory of that image only (``<cache>/pycache/sha256-<id>``,
mounted at /pycache, PYTHONPYCACHEPREFIX): shared by the offline commands of the same code, never mounted into a live
command (network, credentials), another image or the host's own Python.

Every container runs with ``--init`` and a unique ``--name otterdog-e2e-<run>-<seq>``: otterdog as PID 1 would ignore
the SIGTERM the docker CLI proxies on a timeout, so a timed-out untrusted ``apply`` could keep mutating GitHub. The
runner therefore removes the named container (``docker rm -f``, DockerRuntime.remove) whenever a command times out or
is interrupted.

The runner (OtterdogCli) decides the layout: for a container runtime (``in_container``) the mounted workdir is the
workspace root and otterdog's cwd is ``<workspace>/cwd`` (``/ws/cwd``), so ``-c``, ``-j`` and the HTTP cache all live
under the mount; credentials travel only in the env-file, never on the command line.
"""

from __future__ import annotations

import logging
import os
import re
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from otterdog_e2e import procs
from otterdog_e2e.sut.cli_install import IMAGE_OTTERDOG_BIN

if TYPE_CHECKING:
    from otterdog_e2e.sut.cli_install import InstalledCli

CONTAINER_WORKDIR = "/ws"
CONTAINER_CWD = f"{CONTAINER_WORKDIR}/cwd"
CWD_DIR = "cwd"  # name of otterdog's cwd inside the mounted workdir (container runtimes)
CONTAINER_ENV = {"HOME": "/tmp", "COLUMNS": "4096", "NO_COLOR": "1", "PYTHON_DOTENV_DISABLED": "1"}  # noqa: S108
HARDENING = ("--cap-drop", "ALL", "--security-opt", "no-new-privileges")
CONTAINER_PREFIX = "otterdog-e2e"  # container names: otterdog-e2e-<run>-<seq>
REMOVE_TIMEOUT = 60.0  # seconds allowed for ``docker rm -f``
PYCACHE_DIR = "pycache"  # bytecode of offline docker commands: <cache>/pycache/sha256-<image id>
CONTAINER_PYCACHE = "/pycache"
_IMAGE_ID_RE = re.compile(r"sha256:([0-9a-f]{64})")

log = logging.getLogger(__name__)

_container_scope: str | None = None
_PROCESS_SCOPE = f"p{secrets.token_hex(4)}"  # container-name scope of a process without a run (unit tests, tools)


def set_container_scope(run_id: str | None) -> None:
    """Run id used in container names (set by E2EContext.start_session; None restores the per-process token)."""
    global _container_scope
    _container_scope = run_id


def container_scope() -> str:
    """The run id set by set_container_scope, else a random token of this process."""
    return _container_scope or _PROCESS_SCOPE


def container_name(seq: int | str) -> str:
    """``otterdog-e2e-<run>-<seq>``: unique per invocation (run id + the runner's process-wide command number)."""
    suffix = f"{seq:04d}" if isinstance(seq, int) else seq
    return f"{CONTAINER_PREFIX}-{container_scope()}-{suffix}"


def pycache_dir(root: Path, image: str | None) -> Path | None:
    """``root/sha256-<id>``: the bytecode directory of an image given by its id; None for a tag, which may move to
    other code."""
    match = _IMAGE_ID_RE.fullmatch(image or "")
    return root / f"sha256-{match.group(1)}" if match else None


class CliRuntime(Protocol):
    """Builds the argv and extra environment of one otterdog invocation."""

    label: str

    def command(self, args: Sequence[str], *, workdir: Path, env_file: Path | None) -> list[str]:
        """Full argv to pass to procs.run."""
        ...

    def env(self, credentials: Mapping[str, str]) -> dict[str, str]:
        """Extra environment for procs.run (credentials for the host; none for docker, they go via env_file)."""
        ...


class HostRuntime:
    """Runs ``<venv>/bin/otterdog`` directly; credentials are passed as extra env."""

    in_container = False

    def __init__(self, installed: InstalledCli) -> None:
        """Bind to a host-installed CLI (runtime "host")."""
        self.installed = installed
        self.label = f"host:{installed.sut.label}"

    def command(self, args: Sequence[str], *, workdir: Path, env_file: Path | None) -> list[str]:
        """[<venv>/bin/otterdog, *args]."""
        if self.installed.otterdog_bin is None:
            raise ValueError(f"installed CLI {self.installed.sut.label!r} has no otterdog binary")
        return [str(self.installed.otterdog_bin), *map(str, args)]

    def env(self, credentials: Mapping[str, str]) -> dict[str, str]:
        """The credentials themselves."""
        return dict(credentials)


class DockerRuntime:
    """Runs the CLI inside the SUT image with the confinement options of the module docstring."""

    in_container = True

    def __init__(self, installed: InstalledCli, *, offline: bool = False, pycache_root: Path | None = None) -> None:
        """Bind to an image CLI (runtime "docker"); offline adds ``--network none`` and, with ``pycache_root`` and an
        image id, the bytecode directory of that image (module docstring)."""
        self.installed = installed
        self.offline = offline
        self.pycache = pycache_dir(pycache_root, installed.image) if offline and pycache_root is not None else None
        self.label = f"docker:{installed.sut.label}"

    def command(
        self, args: Sequence[str], *, workdir: Path, env_file: Path | None, name: str | None = None
    ) -> list[str]:
        """docker run --rm --init --name <name> -i ... --entrypoint /app/.venv/bin/otterdog <image> *args (workdir
        paths rewritten to /ws); ``name`` defaults to a fresh random ``otterdog-e2e-<run>-<token>``. The bytecode
        directory is created here (0700): docker would create a missing mount source as root."""
        if not self.installed.image:
            raise ValueError(f"installed CLI {self.installed.sut.label!r} has no image")
        if env_file is None:
            raise ValueError("DockerRuntime needs an env-file with the E2E_OTTERDOG_* credentials")
        name = name or container_name(secrets.token_hex(4))
        argv = ["docker", "run", "--rm", "--init", "--name", name, "-i"]
        argv += ["--read-only", "--tmpfs", "/tmp", "--user", f"{os.getuid()}:{os.getgid()}"]  # noqa: S108
        argv += HARDENING
        for key, value in CONTAINER_ENV.items():
            argv += ["-e", f"{key}={value}"]
        argv += ["--env-file", str(env_file), "-v", f"{workdir}:{CONTAINER_WORKDIR}", "-w", CONTAINER_CWD]
        if self.offline:
            argv += ["--network", "none"]
        if self.pycache is not None:
            self.pycache.mkdir(mode=0o700, parents=True, exist_ok=True)
            argv += ["-e", "PYTHONDONTWRITEBYTECODE=", "-e", f"PYTHONPYCACHEPREFIX={CONTAINER_PYCACHE}"]
            argv += ["-v", f"{self.pycache}:{CONTAINER_PYCACHE}"]
        argv += ["--entrypoint", IMAGE_OTTERDOG_BIN, self.installed.image]
        return argv + [rewrite_path(str(arg), workdir) for arg in args]

    def env(self, credentials: Mapping[str, str]) -> dict[str, str]:
        """No extra env (credentials travel in the 0600 env-file)."""
        return {}

    @staticmethod
    def remove(name: str) -> bool:
        """``docker rm -f <name>`` (never raises): a timed-out or interrupted container must not keep running."""
        try:
            result = procs.run(["docker", "rm", "-f", name], keep_home=True, timeout=REMOVE_TIMEOUT)
        except (OSError, procs.TimeoutExpired) as exc:
            log.error("could not remove container %s: %s", name, exc)
            return False
        if result.returncode != 0:  # already gone (``--rm``) or the daemon refused
            log.info("docker rm -f %s exited %s: %s", name, result.returncode, result.stderr.strip())
            return False
        log.warning("removed container %s after a timeout or interruption", name)
        return True


def rewrite_path(arg: str, workdir: Path) -> str:
    """``arg`` with a leading host ``workdir`` replaced by the container mount point /ws."""
    root = str(workdir).rstrip("/")
    if arg == root:
        return CONTAINER_WORKDIR
    if arg.startswith(root + "/"):
        return CONTAINER_WORKDIR + arg[len(root) :]
    return arg


def runtime_for(installed: InstalledCli, *, offline: bool = False, pycache_root: Path | None = None) -> CliRuntime:
    """HostRuntime for runtime "host", DockerRuntime for runtime "docker" (``pycache_root``: offline docker only)."""
    if installed.runtime == "host":
        return HostRuntime(installed)
    if installed.runtime == "docker":
        return DockerRuntime(installed, offline=offline, pycache_root=pycache_root)
    raise ValueError(f"unknown CLI runtime {installed.runtime!r} (expected 'host' or 'docker')")
