"""Base of the ``otterdog-e2e`` command line (SPEC 16): the click group ``main`` every command module registers on and
the helpers the commands share.

Every command builds an E2EContext (_context; _session adds the process setup and always closes it: lease release,
scrub); output is redacted (_echo, _echo_json) and harness errors become redacted one-line messages (_handled, exit 1).
check_passthrough holds the pass-through rules of ``run``, ``pr`` and ``inject`` (and of PYTEST_ADDOPTS), target_names
parses the --target lists of the commands running several targets, and ``main`` installs the TerminationGuard: SIGTERM
cleans up like Ctrl-C.
"""

from __future__ import annotations

import contextlib
import functools
import ipaddress
import json
import logging
import os
import re
import shlex
import signal
import sys
import threading
import urllib.parse
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import click

from otterdog_e2e.context import E2EContext, E2EOptions, describe_error
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.settings import HarnessSettings, Target

logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])

# pass-through pytest args starting with these are rejected by `run` and `pr` (they could override the SUT or plugins,
# or print secrets); "@" is pytest's argument-file prefix
REJECTED_PASSTHROUGH = (
    "--e2e-",
    "-p",
    "-c",
    "-o",
    "--rootdir",
    "--confcutdir",
    "--basetemp",
    "--pyargs",
    "--showlocals",
    "--override-ini",
    "--config-file",
    "-l",
    "@",
)
_LONG_REJECTED = tuple(prefix for prefix in REJECTED_PASSTHROUGH if prefix.startswith("--"))
_SHORT_REJECTED = frozenset(prefix[1] for prefix in REJECTED_PASSTHROUGH if len(prefix) == 2 and prefix[0] == "-")
_SHORT_WITH_VALUE = frozenset("kmrcopW")  # pytest short options taking a value: the rest of the cluster is that value
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_ARG_RE = re.compile(r"^[0-9a-z]{6}[0-9a-f]{2}$")
CONFIG_HOME = Path("~/.config/otterdog-e2e")


# --- shared helpers -------------------------------------------------------------------------------------------------
def check_passthrough(args: Sequence[str]) -> None:
    """click.UsageError when a pass-through argument starts with one of REJECTED_PASSTHROUGH."""
    for arg in args:
        if _rejected(arg):
            raise click.UsageError(
                f"pass-through argument {arg!r} is not allowed (it could change the SUT, load plugins or print secrets)"
            )


def _rejected(arg: str) -> bool:
    """True for @files, rejected long options and short-option clusters containing -p/-c/-o/-l."""
    if arg.startswith("@"):
        return True
    if arg.startswith("--"):
        name = arg.split("=", 1)[0]
        return any(name.startswith(prefix) if prefix.endswith("-") else name == prefix for prefix in _LONG_REJECTED)
    if not arg.startswith("-") or len(arg) < 2:
        return False
    for char in arg[1:]:
        if char in _SHORT_REJECTED:
            return True
        if char in _SHORT_WITH_VALUE:
            return False
    return False


def _check_addopts(environ: Mapping[str, str]) -> None:
    """PYTEST_ADDOPTS obeys the same pass-through rules."""
    check_passthrough(shlex.split(environ.get("PYTEST_ADDOPTS", "")))


def _handled(func: F) -> F:
    """Report harness errors as a redacted one-line click error (exit 1) instead of a traceback."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call the command, converting unexpected exceptions."""
        try:
            return func(*args, **kwargs)
        except (click.ClickException, click.exceptions.Exit, click.Abort):
            raise
        except Exception as exc:
            logger.debug("command failed", exc_info=True)
            raise click.ClickException(describe_error(exc)) from exc

    return wrapper  # type: ignore[return-value]


TARGET_LIST_COMMANDS = ("run", "pr", "doctor", "janitor")  # the commands accepting several targets (batch.py)


def _single_target(target: str | None) -> str | None:
    """``target`` unless it is a list of targets (UsageError: only TARGET_LIST_COMMANDS run several targets)."""
    from otterdog_e2e.batch import is_target_list

    if target is not None and is_target_list(target):
        raise click.UsageError(
            f"--target {target!r}: a list of targets (a,b / @all / @<list>) is only accepted by"
            f" {', '.join(TARGET_LIST_COMMANDS)}; give this command one target"
        )
    return target


TARGET_HELP = "target: an instance (~/.config/otterdog-e2e/<instance>.env with E2E_PROFILE), a profile or a file"
TARGETS_HELP = (
    f"{TARGET_HELP}; several: repeat it or give a comma list, @all (every instance env file) or @<list>"
    " (~/.config/otterdog-e2e/lists/<list>)"
)


def target_names(values: Sequence[str], *, required: bool = False) -> tuple[str, ...]:
    """The targets of the --target values of run/pr/doctor/janitor (batch.parse_targets; UsageError for a bad list,
    or for no target at all when ``required``)."""
    from otterdog_e2e.batch import ALL_INSTANCES, BatchError, parse_targets

    settings = _settings() if any(ALL_INSTANCES in value for value in values) else None  # @all keeps profile names
    try:
        names = parse_targets(values, os.environ, settings)
    except BatchError as exc:
        raise click.UsageError(str(exc)) from None
    if required and not names:
        raise click.UsageError("--target: no target given")
    return names


def _context(
    target: str | None = None, *, make_dirs: bool = True, artifacts: bool = True, **options: Any
) -> E2EContext:
    """A fresh E2EContext for one command (one target: a list of targets is a usage error)."""
    return E2EContext.create(
        E2EOptions(target=_single_target(target), **options), make_dirs=make_dirs, artifacts=artifacts
    )


@contextlib.contextmanager
def _session(target: str | None = None, *, artifacts: bool = True, **options: Any) -> Iterator[E2EContext]:
    """E2EContext with process setup (scratch HOME, log redaction); always closed (lease release, scrub)."""
    context = _context(target, artifacts=artifacts, **options)
    context.start_session(argv=[REDACTOR(arg) for arg in sys.argv])
    try:
        yield context
    finally:
        context.close()


def _echo(text: str = "", *, err: bool = False) -> None:
    """click.echo of redacted text."""
    click.echo(REDACTOR(text), err=err)


def _echo_json(data: Any) -> None:
    """Pretty JSON on stdout (redacted)."""
    _echo(json.dumps(data, indent=2, sort_keys=True, default=str))


def _settings() -> HarnessSettings:
    """HarnessSettings from the environment."""
    from otterdog_e2e.settings import harness_settings

    return harness_settings(os.environ)


def _declared_login(target: Target, name: str) -> str | None:
    """Login declared for an identity in the target (F8), None when absent."""
    spec = target.identities.get(name)
    return spec.login if spec is not None and spec.login else None


def _is_loopback_url(url: str) -> bool:
    """True when the URL's host is localhost or a loopback address."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _public_member(context: E2EContext, org: str, login: str) -> bool:
    """GET /orgs/{org}/public_members/{login}: 204 public, 404 private or not a member."""
    response = context.http("admin").request(
        "GET", f"/orgs/{org}/public_members/{login}", expected=(204,), allow=(404,)
    )
    return response.status_code == 204


class TerminationGuard:
    """SIGTERM raises KeyboardInterrupt in every command (main thread), so its cleanup runs: E2EContext.close releases
    the org lease and scrubs, like after a Ctrl-C (a batch parent forwards SIGTERM to its janitor children too).

    Only the first interruption is raised, a SIGINT included (its own behaviour is kept): GitHub cancels with SIGINT,
    then SIGTERM 7.5 s later, and a second KeyboardInterrupt would abort the cleanup in progress. One handler at a
    time: while pytest runs in-process (run, pr, inject) the plugin's InterruptGuard replaces this SIGTERM handler and
    restores it (run_pytest marks an interrupted session here), and procs.forward_signals replaces both handlers while
    batch children run.
    """

    def __init__(self) -> None:
        """Nothing interrupted yet."""
        self.interrupted = False
        self._previous: dict[int, Any] = {}

    def install(self) -> bool:
        """Install the handlers (main thread only; a SIGINT that Python does not handle, e.g. ignored, is left as is)."""
        if threading.current_thread() is not threading.main_thread():
            return False
        self._previous[signal.SIGTERM] = signal.signal(signal.SIGTERM, self.on_sigterm)
        if callable(signal.getsignal(signal.SIGINT)):
            self._previous[signal.SIGINT] = signal.signal(signal.SIGINT, self.on_sigint)
        return True

    def uninstall(self) -> None:
        """Restore the previous handlers."""
        if threading.current_thread() is not threading.main_thread():
            return
        for signum, handler in self._previous.items():
            signal.signal(signum, signal.SIG_DFL if handler is None else handler)
        self._previous.clear()

    def on_sigterm(self, signum: int, frame: Any) -> None:
        """First interruption: KeyboardInterrupt; a later SIGTERM is logged while the cleanup runs."""
        if self.interrupted:
            logger.warning("signal %d ignored: cleanup in progress", signum)
            return
        self.interrupted = True
        raise KeyboardInterrupt(f"signal {signum}")

    def on_sigint(self, signum: int, frame: Any) -> None:
        """A SIGINT behaves as before (the previous handler: KeyboardInterrupt) and counts as the first interruption."""
        self.interrupted = True
        previous = self._previous.get(signal.SIGINT)
        if callable(previous):
            previous(signum, frame)
        else:  # pragma: no cover - install() only wraps a callable handler
            raise KeyboardInterrupt


_GUARD_KEY = "otterdog_e2e.termination_guard"  # click Context.meta: the TerminationGuard of the running command


def _termination_guard() -> TerminationGuard | None:
    """The TerminationGuard of the running command (None outside a command or off the main thread)."""
    context = click.get_current_context(silent=True)
    guard = context.meta.get(_GUARD_KEY) if context is not None else None
    return guard if isinstance(guard, TerminationGuard) else None


def _verbosity() -> int:
    """The -v count given to the main group (0 outside a command)."""
    context = click.get_current_context(silent=True)
    return int(context.find_root().params.get("verbose") or 0) if context is not None else 0


@click.group()
@click.version_option(package_name="otterdog-e2e", prog_name="otterdog-e2e")
@click.option("-v", "--verbose", count=True, help="log more (-v info, -vv debug)")
@click.pass_context
def main(context: click.Context, verbose: int) -> None:
    """End-to-end test harness for otterdog."""
    from otterdog_e2e import redact

    redact.install_logging_filter()
    if verbose:
        logging.basicConfig(level=logging.DEBUG if verbose > 1 else logging.INFO, format="%(levelname)s %(message)s")
    guard = TerminationGuard()
    if guard.install():
        context.meta[_GUARD_KEY] = guard
        context.call_on_close(guard.uninstall)
