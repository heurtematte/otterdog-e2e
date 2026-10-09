"""``otterdog-e2e report``, ``targets``, ``scrub-artifacts`` and ``cache prune`` (SPEC 16): local maintenance of the
run artifacts, the target instances and the harness cache; none of them contacts GitHub.

scrub-artifacts registers the secret values of its environment first (register_environment_secrets: a separate scrub
process knows no secret of the session); cache prune never removes an entry whose lock a running session, export,
install or image build holds.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import shutil
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import click

from otterdog_e2e.cli.common import CONFIG_HOME, _echo, _echo_json, _handled, _settings, main
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.batch import InstanceInfo
    from otterdog_e2e.redact import Redactor

logger = logging.getLogger(__name__)

PRUNABLE_CACHE_DIRS = ("run", "build", "src", "http-cache")
# private exports of untrusted SUTs (removed by their session): cache prune only removes their unheld image locks
UNTRUSTED_CACHE_DIR = "untrusted"


# --- reports and cache ----------------------------------------------------------------------------------------------
@main.command()
@click.argument("directory", type=click.Path(file_okay=False, exists=True))
@_handled
def report(directory: str) -> None:
    """Print the summary of a run artifacts directory."""
    from otterdog_e2e import report as report_module

    _echo(report_module.build_summary(Path(directory)))


def render_instances(instances: Sequence[InstanceInfo]) -> str:
    """Table of ``otterdog-e2e targets``: instance, profile, org and env file, a ``problem:`` line under the instances
    whose target cannot be loaded."""
    if not instances:
        return f"no target instance: no {CONFIG_HOME}/<instance>.env file and no targets/<profile>.yaml"
    header = ("INSTANCE", "PROFILE", "ORG", "ENV FILE")
    rows = [(info.name, info.profile or "-", info.org or "-", info.env_file or "-") for info in instances]
    widths = [max(len(row[index]) for row in (header, *rows)) for index in range(3)]
    lines = []
    for row, info in zip((header, *rows), (None, *instances), strict=True):
        lines.append(
            "  ".join(value.ljust(width) for value, width in zip(row[:3], widths, strict=True)) + f"  {row[3]}"
        )
        if info is not None and info.problem:
            lines.append(f"  problem: {info.problem}")
    return "\n".join(lines)


@main.command("targets")
@click.option("--json", "as_json", is_flag=True, help="print the instances as JSON")
@_handled
def targets_command(as_json: bool) -> None:
    """List the target instances: the env files ~/.config/otterdog-e2e/<instance>.env and the profiles of targets/
    (instance, profile, org, env file; read-only, nothing is contacted)."""
    from otterdog_e2e.batch import list_instances

    instances = list_instances(_settings(), os.environ)
    if as_json:
        _echo_json([dataclasses.asdict(info) for info in instances])
    else:
        _echo(render_instances(instances))


def register_environment_secrets(environ: Mapping[str, str], redactor: Redactor | None = None) -> int:
    """Register with the redactor (default REDACTOR) the values of the variables whose name matches SECRET_KEY_RE
    (``*_TOKEN``, ``*_SECRET``, ``*_PASSWORD``, ``*_TOTP_SEED``, ``*_PRIVATE_KEY``); returns how many were long enough
    to register. A separate scrub process (the CI scrub step) knows no secret of the session: without this, a leaked
    value that has no token shape (the web-UI password, a TOTP seed, a webhook secret) would pass the scan. A vault
    reference is resolved first (vaults.py): the scan needs the value, and fails closed when it cannot be read."""
    from otterdog_e2e.redact import MIN_SECRET_LENGTH, SECRET_KEY_RE
    from otterdog_e2e.vaults import VaultError, is_reference, resolve

    values = []
    for key, value in environ.items():
        if not SECRET_KEY_RE.search(key):
            continue
        if is_reference(value):
            try:
                value = resolve(value, environ)
            except VaultError as exc:
                raise click.ClickException(f"{key}: {exc} (the scan needs the value to find it)") from None
        if len(value) >= MIN_SECRET_LENGTH:
            values.append(value)
    (REDACTOR if redactor is None else redactor).add(*values)
    return len(values)


@main.command("scrub-artifacts")
@click.argument("directory", type=click.Path(file_okay=False))
@_handled
def scrub_artifacts(directory: str) -> None:
    """Scrub a run artifacts directory (exit 1 when leaks were found and removed).

    The secret values of the process environment (SECRET_KEY_RE names) are registered first, so the scan also finds
    leaked secrets that have no token shape.
    """
    from otterdog_e2e import report as report_module

    logger.info("scrub: %d secret value(s) of the environment registered", register_environment_secrets(os.environ))
    leaks = report_module.scrub_artifacts(Path(directory), REDACTOR)
    for leak in leaks:
        _echo(f"removed file leaking a secret: {leak}", err=True)
    if leaks:
        sys.exit(1)
    _echo("no leak found")


def cache_sidecars(base: Path, name: str) -> list[Path]:
    """The sidecar files of the cache entry ``base/name``: its file lock ``<name>.lock`` (run scratch, source export,
    ``build/<label>-cli`` install), the image build lock ``<name>.image.lock`` and the export marker
    ``<name>.e2e-export.json`` (exact names: ``v1.2`` never owns the files of ``v1.2.1``)."""
    from otterdog_e2e.sut.image import BUILD_LOCK_SUFFIX
    from otterdog_e2e.sut.spec import EXPORT_MARKER_SUFFIX

    return [base / f"{name}{suffix}" for suffix in (".lock", BUILD_LOCK_SUFFIX, EXPORT_MARKER_SUFFIX)]


def prune_cache_dirs(cache_dir: Path, *, keep: int) -> list[Path]:
    """Keep the ``keep`` newest entries of run/, build/, src/ and http-cache/ (their exact sidecar files,
    cache_sidecars, go too); an entry whose ``<name>.lock`` or ``<name>.image.lock`` is held right now (a running
    session, an export, an install or an image build) is never removed. The image build locks of untrusted SUTs
    (``untrusted/<label>.image.lock``) that nobody holds are removed as well."""
    from otterdog_e2e.context import lock_held
    from otterdog_e2e.sut.image import BUILD_LOCK_SUFFIX

    removed: list[Path] = []
    for sub in PRUNABLE_CACHE_DIRS:
        base = cache_dir / sub
        if not base.is_dir() or base.is_symlink():
            continue
        entries = [entry for entry in base.iterdir() if entry.is_dir() and not entry.is_symlink()]
        entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        for entry in entries[keep:]:
            sidecars = cache_sidecars(base, entry.name)
            held = [path for path in sidecars if path.name.endswith(".lock") and lock_held(path)]
            if held:
                logger.warning("not pruning %s: %s is held (a running session or build)", entry, held[0].name)
                continue
            shutil.rmtree(entry)
            for sidecar in sidecars:
                if sidecar.is_file() or sidecar.is_symlink():
                    sidecar.unlink()
            removed.append(entry)
    untrusted = cache_dir / UNTRUSTED_CACHE_DIR
    if untrusted.is_dir() and not untrusted.is_symlink():
        for lock in sorted(untrusted.glob(f"*{BUILD_LOCK_SUFFIX}")):
            if (lock.is_file() and not lock.is_symlink()) and not lock_held(lock):
                lock.unlink()
                removed.append(lock)
    return removed


def prune_images(*, keep: int) -> list[str]:
    """Remove all but the ``keep`` newest images of the trusted and untrusted harness repositories."""
    from otterdog_e2e import procs
    from otterdog_e2e.sut.image import TRUSTED_IMAGE_REPO, UNTRUSTED_IMAGE_REPO, docker_available

    if not docker_available():
        return []
    removed = []
    for repository in (TRUSTED_IMAGE_REPO, UNTRUSTED_IMAGE_REPO):
        listing = procs.run(
            ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}", repository], keep_home=True, timeout=60
        )
        tags = [line.strip() for line in listing.stdout.splitlines() if line.strip() and not line.endswith(":<none>")]
        for tag in tags[keep:]:  # docker lists the newest images first
            if procs.run(["docker", "image", "rm", tag], keep_home=True, timeout=120).returncode == 0:
                removed.append(tag)
    return removed


@main.group()
def cache() -> None:
    """Manage the harness cache."""


@cache.command("prune")
@click.option(
    "--keep", default=3, show_default=True, type=click.IntRange(min=0), help="number of recent builds/runs to keep"
)
@_handled
def cache_prune(keep: int) -> None:
    """Remove old builds, venvs, images and run scratch directories (never an entry whose lock a running session or
    build holds) and the unheld image build locks of untrusted SUTs."""
    removed = prune_cache_dirs(_settings().cache_dir, keep=keep)
    images = prune_images(keep=keep)
    for path in removed:
        _echo(f"removed {path}")
    for image in images:
        _echo(f"removed image {image}")
    _echo(f"pruned {len(removed)} cache entr{'y' if len(removed) == 1 else 'ies'} and {len(images)} image(s)", err=True)
