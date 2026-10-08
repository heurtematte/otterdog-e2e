"""Small helpers of the session context (SPEC 15), also used by the harness commands: comma lists and option text,
environment flags and CI detection, durations and timestamps, redacted error descriptions, file locks, the holder text
of the org lease, the App installation preflight and the literals hiding a differential side's printed version and
workspace root in its observations.
"""

from __future__ import annotations

import getpass
import re
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.otterdog.runner import OtterdogCli

LEASE_HOLDER_ENV = "E2E_LEASE_HOLDER"  # overrides the holder text written into the (public) lease commit
CI_ENV_KEYS = ("CI", "GITHUB_ACTIONS")
WORKSPACE_PLACEHOLDER = "<WORKSPACE>"  # differential observations: each side's workspace root
PERMISSION_LEVELS: Mapping[str, int] = {"read": 1, "write": 2, "admin": 3}
_DURATION_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*([smhd]?)\s*$")
_DURATION_UNITS: Mapping[str, float] = {"": 1, "s": 1, "m": 60, "h": 3600, "d": 86400}
_VERSION_RE = re.compile(r"version\s+(\S+)")
_TRUE_TEXT = frozenset({"1", "true", "yes", "on"})


# --- small helpers -------------------------------------------------------------------------------------------------
def split_csv(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Comma separated values (or a sequence of them) as a tuple of stripped, non-empty strings."""
    if value is None:
        return ()
    parts = value.split(",") if isinstance(value, str) else [p for item in value for p in str(item).split(",")]
    return tuple(part.strip() for part in parts if part.strip())


def text_or_none(value: Any) -> str | None:
    """Stripped string value, None for None and blank strings."""
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def env_flag(environ: Mapping[str, str], name: str) -> bool:
    """True when ``name`` is set to 1/true/yes/on (case-insensitive)."""
    return str(environ.get(name, "")).strip().lower() in _TRUE_TEXT


def in_ci(environ: Mapping[str, str]) -> bool:
    """True when CI or GITHUB_ACTIONS is set to a truthy value."""
    return any(environ.get(key, "").strip().lower() not in ("", "0", "false", "no") for key in CI_ENV_KEYS)


def target_env_name(value: str) -> str:
    """Name used for the env files of a target given by name or path (``targets/free.yaml`` -> ``free``):
    settings.target_env_name, which refuses malformed names (TargetError)."""
    from otterdog_e2e import settings

    return settings.target_env_name(value)


def lock_held(path: Path) -> bool:
    """True when another holder has the file lock ``path`` right now (a missing lock file is free; never waits)."""
    import filelock

    if not path.exists():
        return False
    try:
        with filelock.FileLock(str(path), timeout=0):
            return False
    except filelock.Timeout:
        return True


def parse_duration(text: str) -> timedelta:
    """``90``/``90s``, ``10m``, ``6h``, ``2d`` as a timedelta (ValueError otherwise)."""
    match = _DURATION_RE.match(text)
    if not match:
        raise ValueError(f"invalid duration {text!r} (examples: 90s, 10m, 6h, 2d)")
    return timedelta(seconds=float(match.group(1)) * _DURATION_UNITS[match.group(2)])


def parse_time(value: Any) -> datetime | None:
    """ISO timestamp (``Z``, offset or naive = UTC) as an aware datetime, None when absent or invalid."""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def describe_error(exc: BaseException) -> str:
    """Redacted ``Type: message`` of an exception."""
    return REDACTOR(f"{type(exc).__name__}: {exc}")


def interactive_terminal() -> bool:
    """True when the process's original stdin is a terminal (pytest replaces sys.stdin while capturing output)."""
    stream = sys.__stdin__
    try:
        return bool(stream is not None and stream.isatty())
    except (AttributeError, OSError, ValueError):  # closed or detached stdin
        return False


def lease_holder(environ: Mapping[str, str]) -> str:
    """Holder text of the org lease (public commit message): the CI run, else ``local:<user>``."""
    override = environ.get(LEASE_HOLDER_ENV)
    if override:
        return override
    if environ.get("GITHUB_ACTIONS") == "true":
        repository = environ.get("GITHUB_REPOSITORY", "?")
        return f"ci:{repository}/actions/runs/{environ.get('GITHUB_RUN_ID', '?')}"
    try:
        return f"local:{getpass.getuser()}"
    except (OSError, KeyError):
        return "local"


def installation_problems(installation: Mapping[str, Any], *, permissions: bool = True) -> list[str]:
    """Why an App installation cannot serve the webapp tier (selection all, not suspended, permissions, events)."""
    from otterdog_e2e.appmanifest import DEFAULT_EVENTS, DEFAULT_PERMISSIONS

    problems = []
    if installation.get("repository_selection") != "all":
        problems.append(f"repository_selection is {installation.get('repository_selection')!r}, expected 'all'")
    if installation.get("suspended_at"):
        problems.append(f"installation suspended since {installation['suspended_at']}")
    if permissions:
        granted = installation.get("permissions") or {}
        missing = [
            f"{name} ({granted.get(name, 'none')} < {level})"
            for name, level in DEFAULT_PERMISSIONS.items()
            if PERMISSION_LEVELS.get(str(granted.get(name, "")), 0) < PERMISSION_LEVELS[level]
        ]
        if missing:
            problems.append(f"permissions missing: {', '.join(missing)}")
        events = sorted(set(DEFAULT_EVENTS) - set(installation.get("events") or []))
        if events:
            problems.append(f"events not subscribed: {', '.join(events)}")
    return problems


def printed_version(version_output: str) -> str | None:
    """Version printed by ``otterdog --version`` (``otterdog.sh, version 1.6.1`` -> ``1.6.1``)."""
    match = _VERSION_RE.search(version_output)
    return match.group(1) if match else None


def workspace_literals(cli: OtterdogCli) -> list[tuple[str, str]]:
    """Literals hiding a differential side's workspace root in its observations: the host path (as given and
    resolved) and, for container runtimes (untrusted SUTs), the mount point the CLI sees instead (``/ws/``).

    Each side renders into its own workspace (scratch/workspaces/diff-<mode>-<role>) and otterdog prints absolute
    config paths (e.g. jsonnet load errors), so without them every such output would be a spurious delta.
    """
    from otterdog_e2e.otterdog.runtime import CONTAINER_WORKDIR

    root = cli.workspace.root
    pairs = [(form, WORKSPACE_PLACEHOLDER) for form in dict.fromkeys((str(root), str(root.resolve())))]
    if getattr(cli.runtime, "in_container", False):
        pairs.append((f"{CONTAINER_WORKDIR}/", f"{WORKSPACE_PLACEHOLDER}/"))
    return pairs
