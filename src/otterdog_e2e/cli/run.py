"""``otterdog-e2e run`` and ``otterdog-e2e pr`` (SPEC 16): test suites through pytest, exit code pytest's.

A RunRequest turns the options into pytest arguments (``--e2e-x=value`` forms, so values never look like options) and
run_pytest calls ``pytest.main`` in-process: the plugin's safety model (verify_target, lease, gating, redaction) applies
unchanged. ``pr`` plans the run of an upstream PR pinned to its head sha (plan_pr): tags from its changed files, base
and extra scenarios from the references of its change. With several targets both start one child process per target
(run_targets, batch.py) and exit with the most severe child code.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import shlex
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import click

from otterdog_e2e.cli.common import (
    FULL_SHA_RE,
    RUN_ID_ARG_RE,
    TARGETS_HELP,
    _check_addopts,
    _echo,
    _handled,
    _session,
    _settings,
    _termination_guard,
    _verbosity,
    check_passthrough,
    main,
    target_names,
)
from otterdog_e2e.context import AUTO_BASE, INVOCATION_ENV, split_csv
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.batch import BatchEntry
    from otterdog_e2e.changes import ChangeId, ChangeSpec
    from otterdog_e2e.settings import HarnessSettings

logger = logging.getLogger(__name__)

SUITES = ("unit", "offline", "cli", "webhooks", "webapp", "enterprise", "differential", "web_ui")
DEFAULT_SUITES = ("offline", "cli", "webhooks", "webapp", "enterprise")
PR_LIVE_SUITES = ("cli", "webhooks", "webapp", "enterprise")
WEB_UI_SUITE = "web_ui"  # tests/web_ui: a default suite only with --allow-web-ui (docs/web-ui-testing.md)


# --- run and pr -----------------------------------------------------------------------------------------------------
@dataclass
class RunRequest:
    """What ``run``/``pr`` pass to pytest (always as ``--e2e-x=value`` so values never look like options)."""

    suites: tuple[str, ...]
    target: str | None = None
    sut: str | None = None
    base_sut: str | None = None
    reset_sut: str | None = None
    tags: str | None = None
    scenario: str | None = None
    keyword: str | None = None
    run_id: str | None = None
    change: str | None = None  # the change under test (ChangeId text: N or a slug), --e2e-change
    webapp_image: str | None = None
    artifacts: str | None = None
    keep: bool = False
    no_reset: bool = False
    strict_diff: bool = False
    extra: tuple[str, ...] = ()
    extra_scenarios: tuple[str, ...] = ()  # scenarios referencing the change (informational: pytest reads them)
    allow_web_ui: bool = False  # --e2e-allow-web-ui: web-UI items may log in as the admin bot (web_ui gating)

    def pytest_args(self, project_root: Path) -> list[str]:
        """pytest.main arguments: suite directories, --e2e-* options, -k, pass-through arguments."""
        args = [str(_suite_dir(project_root, suite)) for suite in self.suites]
        values = {
            "--e2e-target": self.target,
            "--e2e-sut": self.sut,
            "--e2e-base-sut": self.base_sut,
            "--e2e-reset-sut": self.reset_sut,
            "--e2e-tags": self.tags,
            "--e2e-scenario": self.scenario,
            "--e2e-run-id": self.run_id,
            "--e2e-change": self.change,
            "--e2e-webapp-image": self.webapp_image,
            "--e2e-artifacts": self.artifacts,
        }
        args += [f"{flag}={value}" for flag, value in values.items() if value]
        flags = {
            "--e2e-keep": self.keep,
            "--e2e-no-reset": self.no_reset,
            "--e2e-strict-diff": self.strict_diff,
            "--e2e-allow-web-ui": self.allow_web_ui,
        }
        args += [flag for flag, enabled in flags.items() if enabled]
        if self.keyword:
            args.append(f"-k{self.keyword}")
        return [*args, *self.extra]

    def command_line(self, project_root: Path) -> str:
        """The equivalent ``otterdog-e2e run`` command (run.json ``command``: summary.md "How to reproduce"); the run
        id, artifacts root and keep flag are left out (a new run gets its own)."""
        argv = ["otterdog-e2e", "run", "--suite", ",".join(self.suites)]
        options = {
            "--target": self.target,
            "--sut": self.sut,
            "--base-sut": self.base_sut,
            "--reset-sut": self.reset_sut,
            "--tags": self.tags,
            "--scenario": self.scenario,
            "-k": self.keyword,
            "--change": self.change,
            "--webapp-image": self.webapp_image,
        }
        argv += [part for flag, value in options.items() if value for part in (flag, value)]
        flags = (
            ("--no-reset", self.no_reset),
            ("--strict-diff", self.strict_diff),
            ("--allow-web-ui", self.allow_web_ui),
        )
        argv += [flag for flag, enabled in flags if enabled]
        return shlex.join([*argv, *self.extra])

    def harness_args(self) -> list[str]:
        """``run`` arguments starting this very run in a child process (``python -m otterdog_e2e run ...``: one per
        target of a batch): ``--option=value`` forms (a value never reads as an option), the run id, artifacts root
        and keep flag included, the pass-through arguments after ``--``."""
        options = {
            "--suite": ",".join(self.suites),
            "--target": self.target,
            "--sut": self.sut,
            "--base-sut": self.base_sut,
            "--reset-sut": self.reset_sut,
            "--tags": self.tags,
            "--scenario": self.scenario,
            "--run-id": self.run_id,
            "--artifacts": self.artifacts,
            "--webapp-image": self.webapp_image,
            "--change": self.change,
        }
        args = ["run", *(f"{flag}={value}" for flag, value in options.items() if value)]
        args += [f"-k{self.keyword}"] if self.keyword else []
        flags = (
            ("--keep", self.keep),
            ("--no-reset", self.no_reset),
            ("--strict-diff", self.strict_diff),
            ("--allow-web-ui", self.allow_web_ui),
        )
        args += [flag for flag, enabled in flags if enabled]
        return [*args, "--", *self.extra]


def _suite_dir(project_root: Path, suite: str) -> Path:
    """tests/<suite> of the project (UsageError for unknown suites or missing directories)."""
    if suite not in SUITES:
        raise click.UsageError(f"unknown suite {suite!r}, expected one of {', '.join(SUITES)}")
    path = project_root / "tests" / suite
    if not path.is_dir():
        raise click.UsageError(f"suite {suite!r}: {path} does not exist")
    return path


SUITE_HELP = f"test tier(s) to run, repeatable or comma separated: {', '.join(SUITES)}"
ALLOW_WEB_UI_HELP = (
    "allow the web-UI tier (--e2e-allow-web-ui): otterdog logs in to github.com as the admin bot (web credentials,"
    " trusted SUTs only; docs/web-ui-testing.md)"
)
CHANGE_HELP = (
    "change under test: N or #N (an otterdog PR) or a change slug; the scenarios referencing it (their references)"
    " give the expected deltas of the differential, extra scenarios of --tags, the default --base-sut and the template"
    " (default: N of a pr:N@<sha> SUT)"
)


def default_suites(*, base_sut: str | None, allow_web_ui: bool) -> tuple[str, ...]:
    """Suites of ``run`` without --suite: every e2e tier; differential with a base SUT, web_ui with --allow-web-ui."""
    return (
        *DEFAULT_SUITES,
        *(("differential",) if base_sut else ()),
        *((WEB_UI_SUITE,) if allow_web_ui else ()),
    )


def parse_suites(values: Sequence[str]) -> tuple[str, ...]:
    """--suite values (repeated and/or comma separated) validated against SUITES."""
    suites = split_csv(values)
    unknown = [suite for suite in suites if suite not in SUITES]
    if unknown:
        raise click.BadParameter(f"unknown suite(s) {', '.join(unknown)}; expected {', '.join(SUITES)}")
    return suites


def run_pytest(args: Sequence[str], *, command: str | None = None) -> int:
    """pytest.main in-process (keeps the credentials of this process; the plugin is loaded by its entry point).

    ``command``: the harness command line, recorded in run.json (summary.md "How to reproduce") via INVOCATION_ENV.
    """
    import pytest

    logger.info("pytest %s", shlex.join(args))
    previous = os.environ.get(INVOCATION_ENV)
    if command:
        os.environ[INVOCATION_ENV] = command
    try:
        code = int(pytest.main(list(args)))
        guard = _termination_guard()
        if code == int(pytest.ExitCode.INTERRUPTED) and guard is not None:
            guard.interrupted = True  # the plugin's guard handled the first signal: a later SIGTERM is ignored
        return code
    finally:
        if previous is None:
            os.environ.pop(INVOCATION_ENV, None)
        else:
            os.environ[INVOCATION_ENV] = previous


def _artifacts_dir(settings: HarnessSettings, request: RunRequest) -> Path:
    """Artifacts directory of a run started by run/pr."""
    root = Path(request.artifacts).expanduser().resolve() if request.artifacts else settings.artifacts_root
    return root / str(request.run_id)


def _echo_run_report(settings: HarnessSettings, request: RunRequest, code: int) -> None:
    """Where the run's summary and differential report are (and the delta counts), after pytest's own output."""
    sys.stdout.flush()  # pytest's final summary line may still sit in the stdout buffer: keep it first
    directory = _artifacts_dir(settings, request)
    _echo(f"pytest exit code {code}; artifacts: {directory}", err=True)
    differential = directory / "differential.json"
    if differential.is_file():
        counts = json.loads(differential.read_text(encoding="utf-8")).get("counts") or {}
        _echo(
            f"differential: {counts.get('unexpected', 0)} unexpected, {counts.get('expected', 0)} expected delta(s)",
            err=True,
        )


# --- several targets: one child process per target (batch.py) -------------------------------------------------------

PARALLEL_HELP = (
    "with several targets: run up to N targets at once (distinct orgs; relay webapps get free loopback ports)"
)
FAIL_FAST_HELP = "with several targets: start no further target after one failed"
RUN_ID_LIST_ERROR = "--run-id names one run: it cannot be used with several targets (each target gets its own run id)"


def run_targets(
    names: Sequence[str],
    child_args: Callable[[BatchEntry], Sequence[str]],
    *,
    settings: HarnessSettings,
    artifacts_root: Path,
    parallel: int = 1,
    fail_fast: bool = False,
    reproduce: Callable[[BatchEntry], str] | None = None,
    summary: bool = True,
    run_ids: bool = True,
) -> int:
    """Run one harness child per target (batch.plan_batch, batch.run_batch) and return the batch exit code.

    The plan is checked before anything runs (UsageError for an invalid target, exported per-instance values, two
    parallel targets of one org or of one external webapp, equal pinned webapp ports); each child gets the -v count
    of this command before its arguments; child lines are echoed with a ``[<instance>] `` prefix; with ``summary``
    the batch writes ``batch-<id>.md``/``.json`` and one log per target below ``artifacts_root``. ``run_ids`` False:
    the children get no --run-id (janitor), so no run id is printed.
    """
    from otterdog_e2e import batch

    try:
        plan = batch.plan_batch(
            names, settings, environ=os.environ, parallel=parallel, fail_fast=fail_fast, run_ids=run_ids
        )
    except batch.BatchError as exc:
        raise click.UsageError(str(exc)) from None
    verbose = ["-v"] * _verbosity()
    _echo(f"batch {plan.batch_id}: {len(plan.entries)} targets, {plan.mode}", err=True)
    for entry in plan.entries:
        run = f", run {entry.run_id}" if plan.run_ids else ""
        port = f", webapp port {entry.webapp_port}" if entry.webapp_port is not None else ""
        _echo(f"[{entry.instance}] profile {entry.profile}, org {entry.org} (id {entry.org_id}){run}{port}", err=True)
    results = batch.run_batch(
        plan,
        lambda entry: [*verbose, *child_args(entry)],
        echo=_echo,
        environ=os.environ,
        log_dir=artifacts_root if summary else None,
    )
    code = batch.batch_exit_code(result.exit_code for result in results)
    sys.stdout.flush()
    _echo(f"batch {plan.batch_id}: exit code {code}", err=True)
    for line in batch.result_lines(results, run_ids=plan.run_ids):
        _echo(f"  {line}", err=True)
    if summary:
        markdown, _json = batch.write_batch_summary(
            plan,
            results,
            artifacts_root,
            environ=os.environ,
            reproduce=reproduce,
            command=shlex.join(["otterdog-e2e", *(REDACTOR(arg) for arg in sys.argv[1:])]),
        )
        _echo(f"batch summary: {markdown}", err=True)
    return code


@main.command(context_settings={"ignore_unknown_options": True})
@click.option("--target", "targets", multiple=True, help=TARGETS_HELP)
@click.option("--parallel", default=1, show_default=True, type=click.IntRange(min=1), help=PARALLEL_HELP)
@click.option("--fail-fast", is_flag=True, help=FAIL_FAST_HELP)
@click.option("--sut", "sut_spec", default=None, help="SUT spec")
@click.option("--base-sut", default=None, help="base SUT spec (differential)")
@click.option("--reset-sut", default=None, help="trusted reset SUT spec")
@click.option(
    "--suite", "suites", multiple=True, callback=lambda ctx, param, value: parse_suites(value), help=SUITE_HELP
)
@click.option(
    "--tags",
    default=None,
    help="comma separated tags: keep items with any of them (offline/unit exempt; AND --scenario)",
)
@click.option("--scenario", default=None, help="comma separated scenario id globs: keep matching items (AND --tags)")
@click.option("-k", "keyword", default=None, help="pytest -k expression")
@click.option("--run-id", default=None, help="run id (default: a new one)")
@click.option("--artifacts", default=None, help="artifacts root directory")
@click.option("--webapp-image", default=None, help="prebuilt webapp image")
@click.option("--keep", is_flag=True, help="keep run resources after the session")
@click.option("--no-reset", is_flag=True, help="skip the baseline reset")
@click.option("--strict-diff", is_flag=True, help="fail on unexpected differential deltas")
@click.option("--allow-web-ui", is_flag=True, help=ALLOW_WEB_UI_HELP + "; adds web_ui to the default suites")
@click.option("--change", "change", default=None, help=CHANGE_HELP)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
@_handled
def run(
    targets: tuple[str, ...],
    parallel: int,
    fail_fast: bool,
    sut_spec: str | None,
    base_sut: str | None,
    reset_sut: str | None,
    suites: tuple[str, ...],
    tags: str | None,
    scenario: str | None,
    keyword: str | None,
    run_id: str | None,
    artifacts: str | None,
    webapp_image: str | None,
    keep: bool,
    no_reset: bool,
    strict_diff: bool,
    allow_web_ui: bool,
    change: str | None,
    pytest_args: tuple[str, ...],
) -> None:
    """Run test suites through pytest (pass-through args checked by check_passthrough).

    Several targets (``--target a,b``, repeated, @all, @<list>): one child process per target with its own run id,
    sequential unless --parallel; the exit code is 0 only when every target passed, else the most severe one.
    """
    from otterdog_e2e.naming import new_run_context

    check_passthrough(pytest_args)
    _check_addopts(os.environ)
    names = target_names(targets)
    several = len(names) > 1
    if several and run_id:
        raise click.UsageError(RUN_ID_LIST_ERROR)
    settings = _settings()
    spec = _load_change(settings, _change_id(change, sut_spec))
    if not base_sut and spec is not None and spec.base:
        base_sut = spec.base
    request = RunRequest(
        suites=suites or default_suites(base_sut=base_sut, allow_web_ui=allow_web_ui),
        target=names[0] if len(names) == 1 else None,
        sut=sut_spec,
        base_sut=base_sut,
        reset_sut=reset_sut,
        tags=tags,
        scenario=scenario,
        keyword=keyword,
        run_id=None if several else run_id or new_run_context().run_id,
        change=str(spec.change) if spec is not None else None,
        webapp_image=webapp_image,
        artifacts=artifacts,
        keep=keep,
        no_reset=no_reset,
        strict_diff=strict_diff,
        extra=pytest_args,
        extra_scenarios=tuple(spec.scenarios) if spec is not None else (),
        allow_web_ui=allow_web_ui,
    )
    if spec is not None:
        _echo(_change_line(spec, request.base_sut), err=True)
    if several:
        root = Path(artifacts).expanduser().resolve() if artifacts else settings.artifacts_root
        template = dataclasses.replace(request, artifacts=str(root))
        sys.exit(
            run_targets(
                names,
                lambda entry: dataclasses.replace(template, target=entry.target, run_id=entry.run_id).harness_args(),
                settings=settings,
                artifacts_root=root,
                parallel=parallel,
                fail_fast=fail_fast,
                reproduce=lambda entry: dataclasses.replace(request, target=entry.target).command_line(
                    settings.project_root
                ),
            )
        )
    code = run_pytest(request.pytest_args(settings.project_root), command=request.command_line(settings.project_root))
    _echo_run_report(settings, request, code)
    sys.exit(code)


def _change_id(option: str | None, sut_spec: str | None) -> ChangeId | None:
    """--change parsed, else N of a ``pr:N@<sha>`` SUT, else None (UsageError when malformed)."""
    from otterdog_e2e.changes import ChangeError, default_change

    try:
        return default_change(option, sut_spec)
    except ChangeError as exc:
        raise click.UsageError(f"--change: {exc}") from None


def _load_change(settings: HarnessSettings, change: ChangeId | None) -> ChangeSpec | None:
    """The ChangeSpec of ``change`` from the repository's references (None without a change; UsageError for invalid
    or conflicting references)."""
    if change is None:
        return None
    from otterdog_e2e.changes import ChangeError, load_change

    try:
        return load_change(settings.scenarios_dir, settings.project_root / "tests", change)
    except ChangeError as exc:
        raise click.UsageError(f"--change {change}: {exc}") from None


def _change_line(spec: ChangeSpec, base_sut: str | None) -> str:
    """One line about the change under test: its referencing scenarios, expected deltas, base and template."""
    scenarios = ",".join(spec.scenarios) or "none (no scenario references it)"
    return (
        f"change {spec.label}: referencing scenarios {scenarios}; {len(spec.expected_deltas)} expected delta(s); "
        f"base {base_sut or '-'}; template {spec.template}"
    )


def pr_suites(value: str, target: str | None) -> tuple[str, ...]:
    """``auto``: offline + differential (+ the live tiers with a target); else a validated comma list."""
    if value == "auto":
        return ("offline", "differential", *(PR_LIVE_SUITES if target else ()))
    suites = parse_suites([value])
    if not suites:
        raise click.UsageError(f"--suite: expected auto or a comma list of {', '.join(SUITES)}")
    return suites


def plan_pr(
    number: int,
    sha: str,
    *,
    target: str | None,
    suites: str,
    settings: HarnessSettings,
    run_id: str | None = None,
    change: str | None = None,
) -> RunRequest:
    """Resolve the PR (pin checked), gather the references of its change, derive base and tags (``run_id``: default a
    new one; ``change``: default the PR itself).

    tags = selection.select_tags(changed files). The scenarios referencing the change are EXTRA scenarios: pytest
    reads them (--e2e-change) and lets them pass the tags filter. They are never passed as --e2e-scenario, which
    restricts every tier (offline and unit included) and is ANDed with --e2e-tags. The base is the ``base`` of the
    references, else the merge base of the PR head (``auto``).
    """
    from otterdog_e2e.naming import new_run_context
    from otterdog_e2e.selection import select_tags

    spec = f"pr:{number}@{sha}"
    change_spec = _load_change(settings, _change_id(change or str(number), spec))
    with _session(sut=spec, artifacts=False) as context:
        changed = list(context.resolve(spec).changed_files)
    return RunRequest(
        suites=pr_suites(suites, target),
        target=target,
        sut=spec,
        base_sut=(change_spec.base if change_spec is not None and change_spec.base else AUTO_BASE),
        tags=",".join(sorted(select_tags(changed))),
        run_id=run_id or new_run_context().run_id,
        change=str(change_spec.change) if change_spec is not None else None,
        extra_scenarios=tuple(change_spec.scenarios) if change_spec is not None else (),
    )


PR_WEB_UI_NOTE = (
    "--allow-web-ui: a pr: SUT is untrusted and the web-UI tier only runs trusted SUTs, so its web_ui items skip with"
    " the reason; test a trusted build of the PR instead (run --sut dirty:<checkout> --suite web_ui --allow-web-ui)"
)


def pr_command(
    number: int,
    sha: str,
    *,
    target: str | None,
    suites: str,
    strict_diff: bool,
    allow_web_ui: bool,
    change: str | None = None,
) -> list[str]:
    """The ``otterdog-e2e pr`` command of one target (run.json ``command``: summary.md "How to reproduce");
    ``change`` only when it is not the PR itself."""
    command = ["otterdog-e2e", "pr", str(number), "--sha", sha, *(["--target", target] if target else [])]
    command += [*(["--suite", suites] if suites != "auto" else []), *(["--strict-diff"] if strict_diff else [])]
    command += ["--change", change] if change else []
    return command + (["--allow-web-ui"] if allow_web_ui else [])


def pr_child_args(
    number: int,
    sha: str,
    *,
    entry: BatchEntry,
    suites: str,
    strict_diff: bool,
    allow_web_ui: bool,
    change: str | None = None,
) -> list[str]:
    """``pr`` arguments of the child process of one batch target (``--option=value`` forms, its own run id)."""
    args = ["pr", str(number), f"--sha={sha}", f"--target={entry.target}", f"--suite={suites}"]
    args += [f"--run-id={entry.run_id}", *(["--strict-diff"] if strict_diff else [])]
    args += [f"--change={change}"] if change else []
    return args + (["--allow-web-ui"] if allow_web_ui else [])


@main.command()
@click.argument("number", type=int)
@click.option("--sha", required=True, help="40-hex head sha to test (pin)")
@click.option("--target", "targets", multiple=True, help=TARGETS_HELP)
@click.option("--suite", "suites", default="auto", help="auto (from the PR's changed files) or a comma list")
@click.option("--strict-diff", is_flag=True, help="fail on unexpected differential deltas")
@click.option("--allow-web-ui", is_flag=True, help=ALLOW_WEB_UI_HELP)
@click.option("--run-id", default=None, help="run id (default: a new one; one target only)")
@click.option("--parallel", default=1, show_default=True, type=click.IntRange(min=1), help=PARALLEL_HELP)
@click.option("--fail-fast", is_flag=True, help=FAIL_FAST_HELP)
@click.option("--change", "change", default=None, help="change under test (default: the PR itself); " + CHANGE_HELP)
@_handled
def pr(
    number: int,
    sha: str,
    targets: tuple[str, ...],
    suites: str,
    strict_diff: bool,
    allow_web_ui: bool,
    run_id: str | None,
    parallel: int,
    fail_fast: bool,
    change: str | None,
) -> None:
    """Test otterdog PR NUMBER at SHA: regression suites, differential vs its base, the scenarios referencing it.

    Several targets: one child ``pr`` process per target with its own run id (sequential unless --parallel).
    """
    sha = sha.strip().lower()
    if number <= 0 or not FULL_SHA_RE.match(sha):
        raise click.UsageError("pr needs a positive PR number and --sha with the 40-hex head commit")
    explicit = _change_id(change, None) if change is not None and change.strip() else None
    change = str(explicit) if explicit is not None and explicit != _change_id(str(number), None) else None
    if run_id is not None and not RUN_ID_ARG_RE.match(run_id):
        raise click.UsageError(f"--run-id {run_id!r} is not a run id ({RUN_ID_ARG_RE.pattern})")
    names = target_names(targets)
    if len(names) > 1 and run_id is not None:
        raise click.UsageError(RUN_ID_LIST_ERROR)
    _check_addopts(os.environ)
    settings = _settings()
    if len(names) > 1:
        _echo(f"PR #{number} @ {sha[:12]} on {len(names)} targets: {', '.join(names)}", err=True)
        if allow_web_ui:
            _echo(PR_WEB_UI_NOTE, err=True)
        sys.exit(
            run_targets(
                names,
                lambda entry: pr_child_args(
                    number,
                    sha,
                    entry=entry,
                    suites=suites,
                    strict_diff=strict_diff,
                    allow_web_ui=allow_web_ui,
                    change=change,
                ),
                settings=settings,
                artifacts_root=settings.artifacts_root,
                parallel=parallel,
                fail_fast=fail_fast,
                reproduce=lambda entry: shlex.join(
                    pr_command(
                        number,
                        sha,
                        target=entry.target,
                        suites=suites,
                        strict_diff=strict_diff,
                        allow_web_ui=allow_web_ui,
                        change=change,
                    )
                ),
            )
        )
    target = names[0] if names else None
    request = dataclasses.replace(
        plan_pr(number, sha, target=target, suites=suites, settings=settings, run_id=run_id, change=change),
        strict_diff=strict_diff,
        allow_web_ui=allow_web_ui,
    )
    _echo(
        f"PR #{number} @ {sha[:12]}: base {request.base_sut}, tags {request.tags}, change {request.change or '-'}, "
        f"referencing scenarios {','.join(request.extra_scenarios) or '-'}",
        err=True,
    )
    if allow_web_ui:
        _echo(PR_WEB_UI_NOTE, err=True)
    command = pr_command(
        number,
        sha,
        target=target,
        suites=suites,
        strict_diff=strict_diff,
        allow_web_ui=allow_web_ui,
        change=change,
    )
    code = run_pytest(request.pytest_args(settings.project_root), command=shlex.join(command))
    _echo_run_report(settings, request, code)
    sys.exit(code)
