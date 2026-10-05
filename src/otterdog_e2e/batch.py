"""Several targets in one command (``run``, ``pr``, ``doctor``, ``janitor``): target lists, batch plans, one child
process per target and the batch summary.

Target lists: ``--target a,b``, a repeated ``--target``, ``@all`` (every instance with an env file
``~/.config/otterdog-e2e/<instance>.env``) and ``@<list>`` (the file ``~/.config/otterdog-e2e/lists/<list>``: one
instance per line, ``#`` comments). A single target keeps the in-process path of the commands.

Why child processes: the env files of a target fill os.environ without overriding it (settings.load_env_files), so a
second target in the same process would inherit the org, ids and tokens of the first. The parent therefore never
loads an env file into its own environment: plan_batch() reads the env files of each target into a private copy (to
validate the target, learn its profile and org, and register its secrets with the redactor) and every child gets the
parent's pristine environment (procs.run_harness) and loads its own files. ``doctor`` runs in-process with one copy of
the environment per target instead (read-only, no session).

Exported per-instance values would reach every instance (the env files never override the environment): with several
targets, plan_batch refuses an exported E2E_ORG, E2E_ORG_ID or E2E_PROFILE, and an exported login (``*_LOGIN``) or
secret (SECRET_KEY_RE) that the env file of an instance sets to another value (the error names variables, never
values).

Runs are sequential by default. ``--parallel N`` refuses two targets of one org (a test org serves one session at a
time: the org lease) and two ``external`` targets of one webapp URL, and gives each relay child a free loopback port
(E2E_WEBAPP_PORT) unless the instance pins one (two pinned equal ports are refused); ``--fail-fast`` starts no further
target after a failure, a forwarded SIGINT/SIGTERM neither. Every target gets its own run id (artifacts
``<root>/<run id>/``, unchanged; janitor children get none: their lines show no run id); the batch adds
``<root>/batch-<id>.md`` and ``.json`` (appended to GITHUB_STEP_SUMMARY when set) and one redacted log per target
``<root>/batch-<id>-<instance>.log``. batch_exit_code(): 0 when every target exited 0, else the most severe child code
(EXIT_SEVERITY: 3 > 2 > 4 > 1 > 5).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import sys
import threading
import time
import urllib.parse
from collections.abc import Callable, Iterable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e import procs
from otterdog_e2e.differential import md_cell, md_code
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.settings import HarnessSettings, Target

logger = logging.getLogger(__name__)

ALL_INSTANCES = "@all"
LIST_PREFIX = "@"
LISTS_SUBDIR = "lists"  # below ~/.config/otterdog-e2e: one file per list of instances
ENV_FILE_SUFFIX = ".env"
BATCH_PREFIX = "batch-"
WEBAPP_PORT_ENV = "E2E_WEBAPP_PORT"
# per-instance variables of the env files: exported, one value would serve every instance of a batch
INSTANCE_ENV_KEYS = ("E2E_ORG", "E2E_ORG_ID", "E2E_PROFILE")
LOGIN_ENV_SUFFIX = "_LOGIN"
LOOPBACK = "127.0.0.1"
# child exit codes from the most to the least severe: internal error, interrupted, usage error, tests failed, no tests
# collected (pytest's codes; harness errors exit 1)
EXIT_SEVERITY = (3, 2, 4, 1, 5)
INTERRUPTED_EXIT = 2
INTERNAL_ERROR_EXIT = 3
_PORT_ATTEMPTS = 100
_PORT_PROBES = (40001, 40002)  # two E2E_WEBAPP_PORT values: a profile that follows both does not pin its port


class BatchError(ValueError):
    """An invalid list of targets or batch plan (the command line reports it as a usage error)."""


# --- target lists ----------------------------------------------------------------------------------------------------
def is_target_list(value: str | None) -> bool:
    """True when one --target value names several targets (a comma list, @all or @<list>)."""
    text = (value or "").strip()
    return "," in text or text.startswith(LIST_PREFIX)


def _config_dir(environ: Mapping[str, str] | None) -> Path:
    """~/.config/otterdog-e2e of ``environ`` (settings.user_config_dir)."""
    from otterdog_e2e.settings import user_config_dir

    return user_config_dir(environ)


def env_file_instances(environ: Mapping[str, str] | None = None, settings: HarnessSettings | None = None) -> list[str]:
    """Instances with an env file ``~/.config/otterdog-e2e/<instance>.env``, sorted: the valid instance names
    (settings.instance_name_problem) and the profiles of ``settings`` (a profile keeps the wider target-name rule);
    other files (``acme.bak.env``, ``my_org.env`` without such a profile) can never be loaded and are ignored."""
    from otterdog_e2e.settings import instance_name_problem, profile_names

    directory = _config_dir(environ)
    if not directory.is_dir():
        return []
    names = [
        path.name.removesuffix(ENV_FILE_SUFFIX)
        for path in directory.iterdir()
        if path.name.endswith(ENV_FILE_SUFFIX) and path.is_file()
    ]
    odd = [name for name in names if instance_name_problem(name) is not None]
    profiles = set(profile_names(settings)) if odd and settings is not None else set()
    return sorted(name for name in names if name not in odd or name in profiles)


def list_file(name: str, environ: Mapping[str, str] | None = None) -> Path:
    """``~/.config/otterdog-e2e/lists/<name>`` of ``@<name>`` (BatchError when the name is not a plain file name)."""
    from otterdog_e2e.settings import TARGET_NAME_RE

    if not TARGET_NAME_RE.fullmatch(name):
        raise BatchError(f"@{name}: invalid list name (expected {TARGET_NAME_RE.pattern})")
    return _config_dir(environ) / LISTS_SUBDIR / name


def read_target_list(name: str, environ: Mapping[str, str] | None = None) -> list[str]:
    """The instances of ``@<name>``: one per line, ``#`` starts a comment, blank lines skipped (BatchError when the
    file is missing, unreadable, empty or holds a list, an @-reference or spaces on a line)."""
    path = list_file(name, environ)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise BatchError(f"@{name}: no list file {path} (one instance per line, # comments)") from None
    except (OSError, UnicodeDecodeError) as exc:
        raise BatchError(f"@{name}: cannot read {path}: {type(exc).__name__}") from None
    items = []
    for number, line in enumerate(text.splitlines(), start=1):
        item = line.split("#", 1)[0].strip()
        if not item:
            continue
        if item.startswith(LIST_PREFIX) or "," in item or any(char.isspace() for char in item):
            raise BatchError(f"{path}:{number}: {item!r}: one instance per line (no list, @-reference or space)")
        items.append(item)
    if not items:
        raise BatchError(f"@{name}: {path} lists no instance")
    return items


def parse_targets(
    values: str | Sequence[str] | None,
    environ: Mapping[str, str] | None = None,
    settings: HarnessSettings | None = None,
) -> tuple[str, ...]:
    """The targets of --target values (repeated and/or comma separated, @all and @<list> expanded) in order, without
    duplicates or empty items; BatchError for an unknown list or an @all without any instance env file (``settings``:
    the profiles @all accepts beside the instance names, env_file_instances)."""
    if values is None:
        return ()
    found: list[str] = []
    for value in [values] if isinstance(values, str) else values:
        for item in (part.strip() for part in str(value).split(",")):
            if not item:
                continue
            if item == ALL_INSTANCES:
                names = env_file_instances(environ, settings)
                if not names:
                    raise BatchError(
                        f"{ALL_INSTANCES}: no instance env file (<instance>{ENV_FILE_SUFFIX}) in"
                        f" {_config_dir(environ)}: create one with `otterdog-e2e setup --target <instance>`"
                    )
                found += names
            elif item.startswith(LIST_PREFIX):
                found += read_target_list(item.removeprefix(LIST_PREFIX), environ)
            else:
                found.append(item)
    return tuple(dict.fromkeys(found))


def instance_environ(
    target: str, settings: HarnessSettings, environ: Mapping[str, str] | None = None
) -> dict[str, str]:
    """A copy of ``environ`` (os.environ) completed with the env files of ``target`` without overriding it: what the
    target's own session sees. ``environ`` itself is never changed; the secret values are registered with REDACTOR."""
    from otterdog_e2e.settings import load_env_files, target_env_name

    env = dict(os.environ if environ is None else environ)
    load_env_files(target_env_name(target), settings.project_root, env)
    return env


def env_file_values(target: str, settings: HarnessSettings, environ: Mapping[str, str]) -> dict[str, str]:
    """What the env files of ``target`` set, as settings.load_env_files reads them (the first file setting a key wins;
    ``environ`` only gives HOME); unreadable files are skipped."""
    from otterdog_e2e.settings import env_file_candidates, parse_env_text, target_env_name

    values: dict[str, str] = {}
    for path in env_file_candidates(target_env_name(target), settings.project_root, environ):
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for key, value in parse_env_text(text, source=str(path)).items():
            values.setdefault(key, value)
    return values


# --- instances (otterdog-e2e targets) --------------------------------------------------------------------------------
@dataclass(frozen=True)
class InstanceInfo:
    """One target instance as ``otterdog-e2e targets`` lists it (``problem``: why its target cannot be loaded)."""

    name: str
    profile: str | None
    org: str | None
    env_file: str | None
    problem: str | None = None


def list_instances(settings: HarnessSettings, environ: Mapping[str, str] | None = None) -> list[InstanceInfo]:
    """Instances with an env file (``~/.config/otterdog-e2e/<instance>.env``) and the profiles of targets/ (each an
    instance of its own name), sorted: profile, org (of the loaded target, else E2E_ORG) and the first env file found.
    Read-only: the env files are read into copies of ``environ``."""
    from otterdog_e2e.safety import SafetyError
    from otterdog_e2e.settings import env_file_candidates, load_target, profile_names, resolve_target_ref

    env = os.environ if environ is None else environ
    infos = []
    for name in sorted(set(env_file_instances(env, settings)) | set(profile_names(settings))):
        files = [path for path in env_file_candidates(name, settings.project_root, env) if path.is_file()]
        instance_env: Mapping[str, str] = env
        profile = org = problem = None
        try:
            instance_env = instance_environ(name, settings, env)
            profile = resolve_target_ref(name, settings, instance_env).profile
            org = load_target(name, settings, instance_env).org
        except (SafetyError, ValueError) as exc:  # TargetError is a ValueError
            org = (instance_env.get("E2E_ORG") or "").strip() or None
            # a profile nobody configured as an instance yet: say how to, not which variable is missing
            unconfigured = not files and org is None and name in profile_names(settings)
            problem = f"not configured (otterdog-e2e setup --target {name})" if unconfigured else REDACTOR(str(exc))
        infos.append(InstanceInfo(name, profile, org, str(files[0]) if files else None, problem))
    return infos


# --- plans -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class BatchEntry:
    """One target of a batch: the --target value of its child, what it resolves to and its own run id."""

    target: str
    instance: str
    profile: str
    org: str
    org_id: int
    run_id: str
    transport: str = "relay"
    webapp_port: int | None = None  # E2E_WEBAPP_PORT given to the child (parallel relay children without a pinned one)

    def child_env(self, environ: Mapping[str, str]) -> dict[str, str]:
        """Environment of the child: ``environ`` (the parent's, never env-file values) with unbuffered output and the
        assigned webapp port."""
        env = {**environ, "PYTHONUNBUFFERED": "1"}
        if self.webapp_port is not None:
            env[WEBAPP_PORT_ENV] = str(self.webapp_port)
        return env


@dataclass(frozen=True)
class BatchPlan:
    """The targets of one batch, in order, with the execution mode (``parallel`` children at a time)."""

    batch_id: str
    entries: tuple[BatchEntry, ...]
    parallel: int = 1
    fail_fast: bool = False
    run_ids: bool = True  # False: the children get no --run-id (janitor), so no run id is shown

    @property
    def mode(self) -> str:
        """``sequential`` or ``parallel N``, with ``, fail-fast``."""
        mode = "sequential" if self.parallel <= 1 else f"parallel {self.parallel}"
        return mode + (", fail-fast" if self.fail_fast else "")


def free_loopback_port() -> int:
    """A TCP port of 127.0.0.1 that is free right now (chosen by the OS; another process may still take it)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((LOOPBACK, 0))
        return int(sock.getsockname()[1])


def _run_ids(count: int) -> list[str]:
    """``count`` distinct new run ids (ids of one second differ by their random part only)."""
    from otterdog_e2e.naming import new_run_context

    ids: list[str] = []
    while len(ids) < count:
        run_id = new_run_context().run_id
        if run_id not in ids:
            ids.append(run_id)
    return ids


_Resolved = tuple[str, "Target", dict[str, str]]  # (--target value, its Target, its environment copy)


def _resolve_all(targets: Sequence[str], settings: HarnessSettings, environ: Mapping[str, str]) -> list[_Resolved]:
    """Every target loaded with its own environment copy; BatchError listing every target that cannot be loaded or
    names an instance twice."""
    from otterdog_e2e.safety import SafetyError
    from otterdog_e2e.settings import load_target

    resolved, problems = [], []
    for value in targets:
        try:
            env = instance_environ(value, settings, environ)
            resolved.append((value, load_target(value, settings, env), env))
        except (SafetyError, ValueError) as exc:  # TargetError is a ValueError
            problems.append(f"{value}: {REDACTOR(str(exc))}")
    seen: dict[str, str] = {}
    for value, target, _env in resolved:
        if target.name in seen:
            problems.append(f"{value}: the instance {target.name} is already listed (as {seen[target.name]})")
        seen.setdefault(target.name, value)
    if problems:
        raise BatchError("cannot run the batch, fix these targets first:\n" + "\n".join(f"  - {p}" for p in problems))
    return resolved


def _check_exported_instance_keys(environ: Mapping[str, str]) -> None:
    """BatchError when the environment sets E2E_ORG, E2E_ORG_ID or E2E_PROFILE: the env files never override it, so
    every instance of the batch would test one org with one profile."""
    exported = [key for key in INSTANCE_ENV_KEYS if key in environ]
    if exported:
        raise BatchError(
            f"{', '.join(exported)} {'is' if len(exported) == 1 else 'are'} set in the environment: the env files never"
            " override the environment, so every target of the batch would get that one value (one org, one profile"
            f" for all); unset {'it' if len(exported) == 1 else 'them'} (each instance's"
            " ~/.config/otterdog-e2e/<instance>.env sets its own) or give one target"
        )


def _check_exported_overrides(
    resolved: Sequence[_Resolved], settings: HarnessSettings, environ: Mapping[str, str]
) -> None:
    """BatchError when the environment sets a login (``*_LOGIN``) or a secret (SECRET_KEY_RE) that the env file of an
    instance sets to another value: the exported one would win for every instance (the bot of one instance tried for
    another). Names the variables and instances, never a value."""
    from otterdog_e2e.redact import SECRET_KEY_RE

    clashes: dict[str, list[str]] = {}
    for value, target, _env in resolved:
        for key, file_value in env_file_values(value, settings, environ).items():
            if key not in environ or not (key.endswith(LOGIN_ENV_SUFFIX) or SECRET_KEY_RE.search(key)):
                continue
            if environ[key].strip() != file_value.strip():
                clashes.setdefault(key, []).append(target.name)
    if clashes:
        details = "; ".join(f"{key} (env file of {', '.join(names)})" for key, names in sorted(clashes.items()))
        raise BatchError(
            f"the environment overrides what the env files of the batch set differently: {details}; the exported value"
            " would serve every target: unset these variables (each env file keeps its own) or give one target"
        )


def _check_distinct_orgs(resolved: Sequence[_Resolved]) -> None:
    """BatchError when two targets of a parallel batch test the same organization (one session per org at a time)."""
    by_org: dict[int, list[str]] = {}
    for _value, target, _env in resolved:
        by_org.setdefault(target.org_id, []).append(target.name)
    shared = [f"{', '.join(names)} (org id {org_id})" for org_id, names in by_org.items() if len(names) > 1]
    if shared:
        raise BatchError(
            f"--parallel: {'; '.join(shared)} test the same organization: an org serves one session at a time (the"
            " org lease would make the others fail): run them sequentially (without --parallel)"
        )


def _webapp_url_key(url: str) -> tuple[str, str, str]:
    """An external webapp URL compared case-insensitively on scheme and host, without a trailing slash."""
    parts = urllib.parse.urlsplit(url.strip())
    return parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/")


def _check_distinct_external_urls(resolved: Sequence[_Resolved]) -> None:
    """BatchError when two ``external`` targets of a parallel batch use the same webapp URL (one webapp serves one
    org: two sessions would reconfigure it for each other)."""
    by_url: dict[tuple[str, str, str], list[str]] = {}
    for _value, target, _env in resolved:
        if target.webapp.transport == "external" and target.webapp.external_url:
            by_url.setdefault(_webapp_url_key(target.webapp.external_url), []).append(target.name)
    shared = [names for names in by_url.values() if len(names) > 1]
    if shared:
        raise BatchError(
            f"--parallel: {'; '.join(', '.join(names) for names in shared)} use the same external webapp URL: one"
            " webapp serves one session at a time: run them sequentially (without --parallel)"
        )


def _port_follows_env(value: str, settings: HarnessSettings, env: Mapping[str, str]) -> bool:
    """True when the webapp port of the target is E2E_WEBAPP_PORT (False: its profile pins a literal port)."""
    from otterdog_e2e.settings import load_target

    return all(
        load_target(value, settings, {**env, WEBAPP_PORT_ENV: str(port)}).webapp.port == port for port in _PORT_PROBES
    )


def _webapp_ports(
    resolved: Sequence[_Resolved], settings: HarnessSettings, free_port: Callable[[], int]
) -> dict[str, int]:
    """E2E_WEBAPP_PORT of the relay children of a parallel batch that pin no port (E2E_WEBAPP_PORT unset for the
    instance and a profile that reads it): distinct free loopback ports. BatchError when two pin the same port."""
    pinned: dict[int, str] = {}
    free: list[str] = []
    for value, target, env in resolved:
        if target.webapp.transport != "relay":
            continue
        if (env.get(WEBAPP_PORT_ENV) or "").strip() or not _port_follows_env(value, settings, env):
            other = pinned.setdefault(target.webapp.port, target.name)
            if other != target.name:
                raise BatchError(
                    f"--parallel: {other} and {target.name} pin the same webapp port {target.webapp.port}"
                    f" ({WEBAPP_PORT_ENV}): unset it for one of them (the batch then picks a free port) or run them"
                    " sequentially"
                )
        else:
            free.append(target.name)
    ports: dict[str, int] = {}
    for name in free:
        used = set(pinned) | set(ports.values())
        port = next((port for port in (free_port() for _ in range(_PORT_ATTEMPTS)) if port not in used), None)
        if port is None:
            raise BatchError(f"--parallel: no free loopback port found for the webapp of {name}")
        ports[name] = port
    return ports


def plan_batch(
    targets: Sequence[str],
    settings: HarnessSettings,
    *,
    environ: Mapping[str, str] | None = None,
    parallel: int = 1,
    fail_fast: bool = False,
    free_port: Callable[[], int] = free_loopback_port,
    run_ids: bool = True,
) -> BatchPlan:
    """Resolve every target (its env files read into a private copy of ``environ``, never into os.environ) and give
    each a distinct run id (shown only with ``run_ids``: the children get it as --run-id); with several targets,
    refuse exported per-instance values (E2E_ORG, E2E_ORG_ID, E2E_PROFILE; logins and secrets an env file sets
    differently); with ``parallel`` > 1, refuse two targets of one org, of one external webapp URL and pinned equal
    webapp ports, and give each relay child that pins no port a free loopback port. BatchError for any problem,
    before anything runs."""
    if parallel < 1:
        raise BatchError(f"--parallel must be at least 1, got {parallel}")
    if not targets:
        raise BatchError("a batch needs at least one target")
    env = os.environ if environ is None else environ
    if len(targets) > 1:
        _check_exported_instance_keys(env)
    resolved = _resolve_all(targets, settings, env)
    if len(resolved) > 1:
        _check_exported_overrides(resolved, settings, env)
    workers = min(parallel, len(resolved))
    ports: dict[str, int] = {}
    if workers > 1:
        _check_distinct_orgs(resolved)
        _check_distinct_external_urls(resolved)
        ports = _webapp_ports(resolved, settings, free_port)
    batch_id, *ids = _run_ids(len(resolved) + 1)
    entries = tuple(
        BatchEntry(
            target=value,
            instance=target.name,
            profile=target.profile,
            org=target.org,
            org_id=target.org_id,
            run_id=run_id,
            transport=target.webapp.transport,
            webapp_port=ports.get(target.name),
        )
        for (value, target, _env), run_id in zip(resolved, ids, strict=True)
    )
    return BatchPlan(batch_id, entries, workers, fail_fast, run_ids)


# --- execution -------------------------------------------------------------------------------------------------------
@dataclass
class BatchResult:
    """What one target of a batch did: its exit code (None: never started), start time and duration (seconds)."""

    entry: BatchEntry
    exit_code: int | None = None
    started_at: datetime | None = None
    duration: float | None = None

    @property
    def status(self) -> str:
        """``passed``, ``failed`` or ``not started``."""
        if self.exit_code is None:
            return "not started"
        return "passed" if self.exit_code == 0 else "failed"


def harness_argv(args: Sequence[str]) -> list[str]:
    """``python -P -m otterdog_e2e <args>`` with this interpreter (the child runs this very harness installation):
    ``-P`` keeps the working directory off sys.path, so an ``otterdog_e2e`` package in the directory the batch was
    started from (``src/`` of another checkout) is never imported by a child holding the whole environment."""
    return [sys.executable, "-P", "-m", "otterdog_e2e", *args]


def log_name(plan: BatchPlan, entry: BatchEntry) -> str:
    """File name of the redacted output of one child: ``batch-<id>-<instance>.log``."""
    return f"{BATCH_PREFIX}{plan.batch_id}-{entry.instance}.log"


def _seconds(duration: float) -> str:
    """``12.3 s`` / ``3m 05s`` (report.fmt_duration)."""
    from otterdog_e2e.report import fmt_duration

    return fmt_duration(duration)


def run_batch(
    plan: BatchPlan,
    child_args: Callable[[BatchEntry], Sequence[str]],
    *,
    echo: Callable[[str], None],
    environ: Mapping[str, str] | None = None,
    log_dir: Path | None = None,
    runner: Callable[..., int] | None = None,
) -> list[BatchResult]:
    """One child per entry (``python -m otterdog_e2e <child_args(entry)>``, procs.run_harness), sequentially or
    ``plan.parallel`` at a time; every line is echoed with the prefix ``[<instance>] `` (and kept in
    ``<log_dir>/batch-<id>-<instance>.log``). Each child gets ``environ`` (os.environ: never env-file values) plus
    BatchEntry.child_env. After a forwarded SIGINT/SIGTERM, or a failure with ``fail_fast``, no further target starts
    (exit code None)."""
    env = os.environ if environ is None else environ
    run = procs.run_harness if runner is None else runner
    results = [BatchResult(entry) for entry in plan.entries]
    stop = threading.Event()
    if log_dir is not None:
        log_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    with procs.forward_signals() as interrupted:

        def one(result: BatchResult) -> None:
            """Run the child of one entry (unless the batch stopped)."""
            entry = result.entry
            prefix = f"[{entry.instance}] "
            if stop.is_set() or interrupted.is_set():
                why = "interrupted" if interrupted.is_set() else "--fail-fast: an earlier target failed"
                echo(f"{prefix}not started ({why})")
                return
            log_path = log_dir / log_name(plan, entry) if log_dir is not None else None
            result.started_at, began = datetime.now(UTC), time.monotonic()
            try:
                code = run(
                    harness_argv(child_args(entry)),
                    env=entry.child_env(env),
                    on_line=lambda line: echo(prefix + line),
                    log_path=log_path,
                )
            except OSError as exc:
                echo(f"{prefix}cannot start the child process: {type(exc).__name__}: {exc}")
                code = INTERNAL_ERROR_EXIT
            result.exit_code, result.duration = code, time.monotonic() - began
            shown = f" (run {entry.run_id})" if plan.run_ids else ""
            echo(f"{prefix}exit code {code} after {_seconds(result.duration)}{shown}")
            if code != 0 and plan.fail_fast:
                stop.set()

        if plan.parallel <= 1:
            for result in results:
                one(result)
        else:
            with ThreadPoolExecutor(max_workers=plan.parallel, thread_name_prefix="otterdog-e2e-batch") as pool:
                list(pool.map(one, results))
    return results


def _normalized(code: int) -> int:
    """A child exit code on the EXIT_SEVERITY scale: killed by a signal = interrupted, unknown = internal error."""
    if code < 0:
        return INTERRUPTED_EXIT
    return code if code == 0 or code in EXIT_SEVERITY else INTERNAL_ERROR_EXIT


def batch_exit_code(codes: Iterable[int | None]) -> int:
    """0 only when every target exited 0, else the most severe code (EXIT_SEVERITY: 3 > 2 > 4 > 1 > 5; a child killed
    by a signal counts as 2, an unknown code as 3). Targets never started (None) count as interrupted (2) only when no
    started target failed (an interrupted batch never passes; --fail-fast keeps the failure's code)."""
    values = list(codes)
    started = [_normalized(code) for code in values if code is not None]
    failing = [code for code in started if code != 0]
    if failing:
        return min(failing, key=EXIT_SEVERITY.index)
    return INTERRUPTED_EXIT if len(started) < len(values) else 0


# --- summary ---------------------------------------------------------------------------------------------------------
def batch_rows(
    plan: BatchPlan,
    results: Sequence[BatchResult],
    root: Path,
    *,
    reproduce: Callable[[BatchEntry], str] | None = None,
) -> list[dict[str, Any]]:
    """One JSON row per target: instance, profile, org, run id, exit code, status, duration, tallies (read from the
    child's ``<root>/<run id>/``) and the command reproducing it (its run.json command, else ``reproduce``)."""
    from otterdog_e2e.report import RUN_FILE, run_overview

    rows = []
    for result in results:
        entry = result.entry
        run_dir = root / entry.run_id
        overview = run_overview(run_dir) if (run_dir / RUN_FILE).is_file() else {}
        command = overview.get("command") or (reproduce(entry) if reproduce is not None else None)
        rows.append(
            {
                "instance": entry.instance,
                "profile": entry.profile,
                "org": overview.get("org") or entry.org,
                "org_id": entry.org_id,
                "run_id": entry.run_id,
                "artifacts": str(run_dir),
                "log": log_name(plan, entry),
                "exit_code": result.exit_code,
                "status": result.status,
                "started_at": result.started_at.isoformat() if result.started_at else None,
                "duration_seconds": round(result.duration, 1) if result.duration is not None else None,
                "tests": overview.get("tests", 0),
                "tallies": overview.get("tallies", {}),
                "webapp_port": entry.webapp_port,
                "command": command,
            }
        )
    return rows


def batch_markdown(plan: BatchPlan, rows: Sequence[Mapping[str, Any]], exit_code: int) -> str:
    """Markdown summary of a batch: verdict and one table row per target (instance, profile, org, run id, exit code,
    duration, results, reproduce command)."""
    from otterdog_e2e.report import fmt_duration, tally_text

    failed = [row for row in rows if row.get("exit_code") != 0]
    if exit_code == 0:
        verdict = f"**PASSED**: {len(rows)} target(s) passed"
    else:
        verdict = f"**FAILED** (exit code {exit_code}): {len(failed)} of {len(rows)} target(s) did not pass"
    lines = [
        f"# otterdog-e2e batch {md_code(plan.batch_id)}",
        "",
        f"{verdict} ({plan.mode}).",
        "",
        "| Instance | Profile | Org | Run id | Exit code | Duration | Results | Reproduce |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        duration = row.get("duration_seconds")
        cells = [
            md_code(str(row["instance"])),
            md_code(str(row["profile"])),
            md_code(str(row["org"])),
            md_code(str(row["run_id"])),
            "not started" if row.get("exit_code") is None else str(row["exit_code"]),
            fmt_duration(float(duration)) if duration is not None else "-",
            tally_text(row.get("tallies") or {}),
            md_code(str(row["command"])) if row.get("command") else "-",
        ]
        lines.append("| " + " | ".join(md_cell(cell) for cell in cells) + " |")
    logs = f"`{BATCH_PREFIX}{plan.batch_id}-<instance>.log`"
    lines += ["", f"Each target's own report: `<artifacts>/<run id>/summary.md`; its console output: {logs}."]
    return "\n".join(lines) + "\n"


def _write_private(path: Path, text: str) -> None:
    """Write ``text`` (redacted) to ``path`` with mode 0600."""
    path.write_text(REDACTOR(text), encoding="utf-8")
    os.chmod(path, 0o600)


def write_batch_summary(
    plan: BatchPlan,
    results: Sequence[BatchResult],
    root: Path,
    *,
    environ: Mapping[str, str] | None = None,
    reproduce: Callable[[BatchEntry], str] | None = None,
    command: str | None = None,
) -> tuple[Path, Path]:
    """``<root>/batch-<id>.md`` and ``.json`` (redacted) of a finished batch; the markdown is appended to
    GITHUB_STEP_SUMMARY when set. ``command``: the batch's own command line (recorded in the JSON)."""
    env = os.environ if environ is None else environ
    code = batch_exit_code(result.exit_code for result in results)
    rows = batch_rows(plan, results, root, reproduce=reproduce)
    markdown = batch_markdown(plan, rows, code)
    data = {
        "batch_id": plan.batch_id,
        "command": command,
        "mode": plan.mode,
        "parallel": plan.parallel,
        "fail_fast": plan.fail_fast,
        "exit_code": code,
        "finished_at": datetime.now(UTC).isoformat(),
        "targets": rows,
    }
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    markdown_path, json_path = root / f"{BATCH_PREFIX}{plan.batch_id}.md", root / f"{BATCH_PREFIX}{plan.batch_id}.json"
    _write_private(markdown_path, markdown)
    _write_private(json_path, json.dumps(data, indent=2, sort_keys=True) + "\n")
    summary = env.get("GITHUB_STEP_SUMMARY")
    if summary:
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(REDACTOR(markdown) + "\n")
    return markdown_path, json_path


def result_lines(results: Sequence[BatchResult], *, run_ids: bool = True) -> list[str]:
    """One line per target for the console: instance, status, exit code, duration and run id (unless ``run_ids`` is
    False: BatchPlan.run_ids)."""
    width = max([len(result.entry.instance) for result in results] + [8])
    lines = []
    for result in results:
        code = "-" if result.exit_code is None else str(result.exit_code)
        took = _seconds(result.duration) if result.duration is not None else "-"
        entry = result.entry
        line = f"{entry.instance:<{width}}  {result.status:<11}  exit {code:<3}  {took:>8}"
        lines.append(f"{line}  run {entry.run_id}" if run_ids else line)
    return lines
