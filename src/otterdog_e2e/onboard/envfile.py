"""Instance names and env files: the only code that WRITES env files (docs/onboarding.md).

``settings.parse_env_text`` stays the only parser: ``update_env_file`` locates the assignments with the parser's own
line rules (multi-line quoted values span several lines, the last assignment wins) and writes values that the parser
reads back exactly: plain values unquoted, everything else double-quoted with ``\\``, ``"``, ``$``, newline, carriage
return and tab escaped. Characters that ``str.splitlines`` treats as line ends besides ``\\n``/``\\r`` (form feed,
``\\x1c``-``\\x1e``, NEL, U+2028/U+2029) and NUL cannot be represented and are refused.

Writes are atomic (a 0600 temp file in the same directory, then ``os.replace``), never follow a symlink (the file or
its directory), keep comments and unrelated lines byte for byte, and create a missing directory with mode 0700. The
functions return key NAMES only, never values.
"""

from __future__ import annotations

import contextlib
import os
import re
import secrets
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from otterdog_e2e.safety import SafetyError

# _ENV_LINE_RE and _closing_quote are the parser's own line rules: an assignment is found exactly where
# parse_env_text sees it (no second parser)
from otterdog_e2e.settings import (
    _ENV_LINE_RE,
    ENV_NAME_RE,
    INSTANCE_NAME_RE,
    RESERVED_INSTANCE_NAMES,
    RESERVED_INSTANCE_SUFFIXES,
    _closing_quote,
    parse_env_text,
    user_config_dir,
)

ENV_FILE_SUFFIX = ".env"
# values written without quotes (parse_env_text strips unquoted values and cuts them at whitespace + '#'); every
# pattern of this module is used with fullmatch: ``$`` would also match before a trailing newline
_PLAIN_VALUE_RE = re.compile(r"[A-Za-z0-9_./:@%+,=~^?&-]+")
_ESCAPES = {"\\": "\\\\", '"': '\\"', "$": "\\$", "\n": "\\n", "\r": "\\r", "\t": "\\t"}
# line ends of str.splitlines() that parse_env_text has no escape for, and NUL
_UNREPRESENTABLE_RE = re.compile("[\x00\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]")
_EXPORT_RE = re.compile(r"^\s*export\s")
_OPEN_FLAGS = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)


class EnvFileError(ValueError):
    """An env file cannot be updated (bad key, unrepresentable value, unterminated quote); never quotes a value."""


class InstanceNameError(ValueError):
    """Not a valid instance name (INSTANCE_NAME_RE, no reserved name or suffix)."""


def check_instance_name(name: str) -> str:
    """``name`` when it is a valid instance name (InstanceNameError otherwise)."""
    if not INSTANCE_NAME_RE.fullmatch(name or ""):
        raise InstanceNameError(
            f"invalid instance name {name!r}: lower-case letters, digits and '-', at most 39 characters "
            f"({INSTANCE_NAME_RE.pattern})"
        )
    if name in RESERVED_INSTANCE_NAMES:
        raise InstanceNameError(
            f"invalid instance name {name!r}: the name is reserved (~/.config/otterdog-e2e/{name}/ holds the target "
            "lists @<list>)"
        )
    for suffix in RESERVED_INSTANCE_SUFFIXES:
        if name.endswith(suffix):
            raise InstanceNameError(
                f"invalid instance name {name!r}: the suffix {suffix} is reserved for the CI environment "
                f"e2e-<instance>{suffix}"
            )
    return name


def instance_env_path(instance: str, environ: Mapping[str, str]) -> Path:
    """``~/.config/otterdog-e2e/<instance>.env`` (HOME of ``environ``)."""
    return user_config_dir(environ) / f"{check_instance_name(instance)}{ENV_FILE_SUFFIX}"


def instance_app_dir(instance: str, environ: Mapping[str, str]) -> Path:
    """``~/.config/otterdog-e2e/<instance>/``: the App credentials written by the manifest exchange (0700)."""
    return user_config_dir(environ) / check_instance_name(instance)


def known_instances(environ: Mapping[str, str]) -> dict[str, Path]:
    """Instance name -> env file of every ``~/.config/otterdog-e2e/<instance>.env`` with a valid instance name."""
    directory = user_config_dir(environ)
    if not directory.is_dir():
        return {}
    found = {}
    for path in sorted(directory.glob(f"*{ENV_FILE_SUFFIX}")):
        name = path.name.removesuffix(ENV_FILE_SUFFIX)
        with contextlib.suppress(InstanceNameError):
            found[check_instance_name(name)] = path
    return found


def format_env_value(value: str, *, key: str = "value") -> str:
    """The right-hand side of ``KEY=`` that parse_env_text reads back as exactly ``value`` (EnvFileError when no form
    exists); the error names ``key``, never the value."""
    if _UNREPRESENTABLE_RE.search(value):
        raise EnvFileError(
            f"{key}: the value contains a NUL or a line separator other than \\n/\\r that env files cannot hold"
        )
    if _PLAIN_VALUE_RE.fullmatch(value):
        return value
    return '"' + "".join(_ESCAPES.get(char, char) for char in value) + '"'


def read_env_file(path: Path) -> dict[str, str]:
    """Values of an env file (settings.parse_env_text), empty when the file does not exist."""
    if not path.is_file():
        return {}
    return parse_env_text(path.read_text(encoding="utf-8"), source=str(path))


@dataclass(frozen=True)
class _Assignment:
    """One assignment of an env file: lines [start, end) of the file, ``export`` prefix kept on rewrite."""

    key: str
    start: int
    end: int
    export: bool


def _assignments(lines: list[str], source: str) -> list[_Assignment]:
    """Assignments in file order, found with parse_env_text's rules (EnvFileError for an unterminated quote: the parser
    would swallow every following line, appended keys included)."""
    found = []
    index = 0
    while index < len(lines):
        line, start = lines[index], index
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            continue
        raw = match["value"].lstrip()
        if raw[:1] in ("'", '"'):
            quote, body = raw[0], raw[1:]
            while _closing_quote(body, quote) is None and index < len(lines):
                body += "\n" + lines[index]
                index += 1
            if _closing_quote(body, quote) is None:
                raise EnvFileError(
                    f"{source}:{start + 1}: {match['key']} has an unterminated quoted value: fix the file first"
                )
        found.append(_Assignment(match["key"], start, index, bool(_EXPORT_RE.match(line))))
    return found


def _refuse_links(path: Path) -> None:
    """SafetyError when the env file or its directory is a symlink, or the file is not a regular file."""
    if path.parent.is_symlink():
        raise SafetyError(f"refusing to write an env file through a symlinked directory: {path.parent}")
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        return
    if stat.S_ISLNK(mode):
        raise SafetyError(f"refusing to write an env file through a symlink: {path}")
    if not stat.S_ISREG(mode):
        raise SafetyError(f"refusing to write {path}: not a regular file")


def _read_existing(path: Path) -> str | None:
    """Text of the env file (never through a symlink), None when it does not exist."""
    try:
        descriptor = os.open(path, os.O_RDONLY | _OPEN_FLAGS)
    except FileNotFoundError:
        return None
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        return handle.read()


def _private_parent(path: Path) -> None:
    """Create the missing directory of ``path`` with mode 0700 (an existing directory is left as it is)."""
    if path.parent.exists():
        return
    path.parent.mkdir(mode=0o700, parents=True)
    os.chmod(path.parent, 0o700)


def _write_atomic(path: Path, text: str) -> None:
    """Write ``text`` to a fresh 0600 temp file next to ``path`` and rename it over ``path``."""
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | _OPEN_FLAGS, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(temporary)
        raise


def _header_lines(header: str) -> list[str]:
    """Comment lines of a header text ('# ' added where missing)."""
    return [line if line.startswith("#") else f"# {line}".rstrip() for line in header.splitlines()]


def update_env_file(path: Path, updates: Mapping[str, str | None], *, header: str | None = None) -> list[str]:
    """Set (str) or remove (None) keys of an env file and return the names of the keys that changed.

    The last assignment of a key is replaced in place (``export`` kept) and its earlier assignments are dropped (they
    may hold a former secret); new keys are appended; None removes every assignment of the key; comments and other
    lines are kept byte for byte. ``header`` (comment lines) starts a file created here. Nothing is written when no
    effective value changes. The file is written atomically with mode 0600, never through a symlink, its missing
    directory is created with mode 0700.
    """
    path = Path(path)
    rendered: dict[str, str | None] = {}
    for key, value in updates.items():
        if not ENV_NAME_RE.fullmatch(key):
            raise EnvFileError(f"invalid env variable name {key!r}")
        if value is not None and not isinstance(value, str):
            raise EnvFileError(f"{key}: expected a string value, got {type(value).__name__}")
        rendered[key] = None if value is None else format_env_value(value, key=key)
    _refuse_links(path)
    existing = _read_existing(path)
    text = existing or ""
    current = parse_env_text(text, source=str(path))
    lines = text.splitlines(keepends=True)
    by_key: dict[str, list[_Assignment]] = {}
    for assignment in _assignments(text.splitlines(), str(path)):
        by_key.setdefault(assignment.key, []).append(assignment)
    replaced: dict[int, str] = {}
    dropped: set[int] = set()
    appended: list[str] = []
    changed: list[str] = []
    for key, value in updates.items():
        occurrences = by_key.get(key, [])
        if value is None:
            if occurrences:
                dropped.update(index for item in occurrences for index in range(item.start, item.end))
                changed.append(key)
            continue
        if current.get(key) == value and occurrences:
            continue
        line = f"{key}={rendered[key]}\n"
        if occurrences:
            last = occurrences[-1]
            dropped.update(index for item in occurrences for index in range(item.start, item.end))
            replaced[last.start] = ("export " if last.export else "") + line
        else:
            appended.append(line)
        changed.append(key)
    if not changed:
        return []
    output = [
        replaced.get(index, line) for index, line in enumerate(lines) if index not in dropped or index in replaced
    ]
    if existing is None and header:
        output = [f"{line}\n" for line in _header_lines(header)] + output
    if output and not output[-1].endswith(("\n", "\r")):
        output[-1] += "\n"
    _private_parent(path)
    _refuse_links(path)  # the directory may have been created just now: checked again right before the write
    _write_atomic(path, "".join(output + appended))
    return changed
