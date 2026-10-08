"""``otterdog-e2e assist`` (docs/ai-assistance.md): context bundles and checks of AI-assisted test writing; no AI is
called, agents read the bundles.

pr-context gathers an upstream otterdog PR from anonymous public reads; check validates the files an agent wrote and
lints its live scenarios offline (the offline suite through run_pytest, like ``run``); triage pre-classifies the
failures of a run directory, scrubbed first; coverage lists the features of scenarios/coverage.yaml to work on.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from otterdog_e2e.cli.common import FULL_SHA_RE, _check_addopts, _echo, _echo_json, _handled, _settings, main
from otterdog_e2e.cli.maintenance import register_environment_secrets
from otterdog_e2e.cli.run import RunRequest, _artifacts_dir, run_pytest
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.settings import HarnessSettings

logger = logging.getLogger(__name__)

# --- assist: context bundles and checks of AI-assisted test writing (otterdog_e2e.assist, docs/ai-assistance.md) ----
ASSIST_OUT_HELP = "directory receiving the bundle directory (default: <artifacts root>/assist)"
ASSIST_JSON_HELP = "print the bundle summary as JSON"


@main.group()
def assist() -> None:
    """Context bundles and checks for AI-assisted test writing (no AI is called: agents read the bundles)."""


@contextlib.contextmanager
def _assist_errors() -> Iterator[None]:
    """AssistUsageError becomes a usage error (exit 2), AssistError a one-line error (exit 1)."""
    from otterdog_e2e.assist.bundle import AssistError, AssistUsageError

    try:
        yield
    except AssistUsageError as exc:
        raise click.UsageError(str(exc)) from None
    except AssistError as exc:
        raise click.ClickException(REDACTOR(str(exc))) from None


def _assist_out(out: Path | None, settings: HarnessSettings) -> Path:
    """Parent directory of a bundle: --out, else <artifacts root>/assist."""
    from otterdog_e2e.assist.bundle import assist_root

    return out.expanduser().resolve() if out is not None else assist_root(settings.artifacts_root)


def _echo_bundle(summary: Mapping[str, Any], *, as_json: bool, lines: Sequence[str]) -> None:
    """The summary of a bundle: JSON, or ``lines`` and the bundle path."""
    if as_json:
        _echo_json(summary)
        return
    for line in lines:
        _echo(line)
    _echo(f"bundle: {summary['bundle']}")


@assist.command("pr-context")
@click.argument("number", type=click.IntRange(min=1))
@click.option("--sha", default=None, help="40-hex commit of the PR to pin (default: the current head, printed)")
@click.option(
    "--upstream", default=None, help="owner/repo of otterdog (default: E2E_OTTERDOG_REPO, else eclipse-csi/otterdog)"
)
@click.option("--out", default=None, type=click.Path(file_okay=False, path_type=Path), help=ASSIST_OUT_HELP)
@click.option("--json", "as_json", is_flag=True, help=ASSIST_JSON_HELP)
@_handled
def assist_pr_context(number: int, sha: str | None, upstream: str | None, out: Path | None, as_json: bool) -> None:
    """Context bundle of the upstream otterdog PR NUMBER from anonymous public reads: the PR, its files and patches,
    suggested tags, SUT and base, the coverage features it touches, related scenarios, the scenarios already
    referencing the PR and the next commands."""
    from otterdog_e2e.assist import pr_context
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.settings import UPSTREAM_REPO_RE

    if sha is not None and not FULL_SHA_RE.match(sha.strip().lower()):
        raise click.UsageError(f"--sha {sha!r} is not a 40-hex commit sha")
    settings = _settings()
    repo = upstream or settings.upstream_repo
    if not UPSTREAM_REPO_RE.match(repo):
        raise click.UsageError(f"--upstream must be <owner>/<repo>, got {repo!r}")
    http = GitHubHttp(None, read_only=True, identity="anonymous")
    with _assist_errors():
        context = pr_context.build_pr_context(number, sha=sha, upstream=repo, http=http, settings=settings)
        _path, summary = pr_context.write_pr_context(context, _assist_out(out, settings))
    if sha is None:
        _echo(f"pinned the current head {context.sha}: pass --sha {context.sha} to keep testing this commit", err=True)
    head = "the current head" if summary["pin_is_head"] else "NOT the current head"
    lines = [
        f"PR #{number} ({repo}): {summary['changed_files']} changed file(s), pinned {context.sha} ({head})",
        (
            f"suggested: --sut {summary['suggested_sut']} --base-sut {summary['suggested_base'] or 'auto'}; "
            f"tags {','.join(summary['suggested_tags'])}"
        ),
        (
            f"touched coverage features: {summary['touched_features']}; related scenarios: {summary['related_scenarios']}; "
            f"scenarios referencing #{number}: {', '.join(summary['referencing_scenarios']) or 'none yet'}"
        ),
        *(f"warning: {warning}" for warning in summary["warnings"]),
    ]
    _echo_bundle(summary, as_json=as_json, lines=lines)


def _assist_lint(settings: HarnessSettings, sut_spec: str, scenario_ids: Sequence[str]) -> tuple[int, Path]:
    """Offline lint of live scenarios: the ``-k lint`` items of the offline suite restricted to their ids, run like
    ``run`` (untrusted SUTs in docker); pytest's output goes to stderr. Returns (pytest exit code, run directory)."""
    from otterdog_e2e.assist.check import lint_keyword
    from otterdog_e2e.naming import new_run_context

    request = RunRequest(
        suites=("offline",), sut=sut_spec, keyword=lint_keyword(scenario_ids), run_id=new_run_context().run_id
    )
    _echo(f"offline lint of {len(scenario_ids)} live scenario(s) with {sut_spec}: run {request.run_id}", err=True)
    with contextlib.redirect_stdout(sys.stderr):
        code = run_pytest(
            request.pytest_args(settings.project_root), command=request.command_line(settings.project_root)
        )
    return code, _artifacts_dir(settings, request)


@assist.command("check")
@click.argument("paths", nargs=-1, type=click.Path(path_type=Path))
@click.option(
    "--sut",
    "sut_spec",
    default="release:latest",
    show_default=True,
    help="SUT of the offline lint of live scenarios (untrusted SUTs run in docker, as with run)",
)
@click.option("--no-lint", is_flag=True, help="skip the offline lint of the live scenarios")
@click.option("--json", "as_json", is_flag=True, help="print the result as JSON")
@_handled
def assist_check(paths: tuple[Path, ...], sut_spec: str, no_lint: bool, as_json: bool) -> None:
    """Validate the files an agent wrote: scenarios (their references included), scenarios/coverage.yaml,
    known_bugs.yaml, jsonnet files and Python tests (default: the files changed under scenarios/ and tests/ according
    to git status), then lint the live scenarios offline. Exit 1 when a problem is found."""
    from otterdog_e2e.assist import check as check_module

    settings = _settings()
    deleted: list[str] = []
    files = list(paths)
    if not files:
        try:
            files, deleted = check_module.changed_files(settings.project_root)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from None
    result = check_module.check_files(settings.project_root, files, deleted)
    skipped = check_module.lint_skipped(result, no_lint=no_lint)
    if skipped is not None:
        result.lint = {"ran": False, "skipped": skipped, "sut": sut_spec}
    else:
        _check_addopts(os.environ)
        code, run_dir = _assist_lint(settings, sut_spec, sorted(result.live))
        result.lint, problems = check_module.lint_result(run_dir, code, result.live, sut=sut_spec)
        result.problems += problems
    if as_json:
        _echo_json(result.to_json())
    else:
        _echo(check_module.render_text(result))
    sys.exit(0 if result.ok else 1)


@assist.command("triage")
@click.argument("run_dir", metavar="RUN_DIR|latest")
@click.option("--baseline", default=None, help="run directory or run id to compare with: new vs already failing")
@click.option("--out", default=None, type=click.Path(file_okay=False, path_type=Path), help=ASSIST_OUT_HELP)
@click.option("--json", "as_json", is_flag=True, help=ASSIST_JSON_HELP)
@_handled
def assist_triage(run_dir: str, baseline: str | None, out: Path | None, as_json: bool) -> None:
    """Triage bundle of a run directory (a path, a run id or latest): the directory is scrubbed first (no bundle when
    a leak is found), then every failure is pre-classified (known-bug, infrastructure, harness, sut, unknown) with its
    evidence, commands, output excerpts and artifact paths."""
    from otterdog_e2e.assist import triage

    settings = _settings()
    with _assist_errors():
        directory = triage.resolve_run_dir(run_dir, settings.artifacts_root)
        base = triage.resolve_run_dir(baseline, settings.artifacts_root, allow_latest=False) if baseline else None
        if base is not None and base == directory:
            raise click.UsageError("--baseline names the triaged run itself")
        logger.info(
            "triage: %d secret value(s) of the environment registered", register_environment_secrets(os.environ)
        )
        scrub = triage.scrub_or_refuse(directory, REDACTOR)
        data = triage.build_triage(directory, project_root=settings.project_root, baseline=base, scrub=scrub)
        _path, summary = triage.write_triage(data, _assist_out(out, settings))
    counts = ", ".join(f"{count} {name}" for name, count in summary["counts"].items() if count) or "none"
    lines = [f"run {summary['run_id']} ({summary['run_dir']}): {summary['failures']} failure(s): {counts}"]
    if summary["baseline"] is not None:
        lines.append("baseline: " + ", ".join(f"{count} {name}" for name, count in summary["baseline"].items()))
    if summary["xpassed"]:
        lines.append(f"{summary['xpassed']} unexpectedly passing item(s): their known bug may be fixed")
    _echo_bundle(summary, as_json=as_json, lines=lines)


@assist.command("coverage")
@click.option(
    "--status", "statuses", multiple=True, help="gap, partial, covered or all; comma list (default: gap,partial)"
)
@click.option("--priority", "priorities", multiple=True, help="P0, P1, P2; comma list or repeated")
@click.option("--area", "areas", multiple=True, help="area ids of scenarios/coverage.yaml; comma list or repeated")
@click.option("--tier", "tiers", multiple=True, help="offline, cli, webhooks, webapp, web_ui, enterprise; comma list")
@click.option("--feature", default=None, help="one feature id: details, what to imitate, commands (filters ignored)")
@click.option("--out", default=None, type=click.Path(file_okay=False, path_type=Path), help=ASSIST_OUT_HELP)
@click.option("--json", "as_json", is_flag=True, help=ASSIST_JSON_HELP)
@_handled
def assist_coverage(
    statuses: tuple[str, ...],
    priorities: tuple[str, ...],
    areas: tuple[str, ...],
    tiers: tuple[str, ...],
    feature: str | None,
    out: Path | None,
    as_json: bool,
) -> None:
    """Features of scenarios/coverage.yaml to work on (sorted by priority, then status) with their gap outlines; with
    --feature one feature, the tests to imitate and the commands that validate it and regenerate the matrix doc."""
    from otterdog_e2e.assist import coverage

    settings = _settings()
    with _assist_errors():
        query = coverage.parse_query(status=statuses, priority=priorities, area=areas, tier=tiers, feature=feature)
        listing = coverage.build_coverage(settings.project_root, query)
        _path, summary = coverage.write_coverage(listing, _assist_out(out, settings))
    lines = [f"{item['priority']} {item['status']:<8} {item['tier']:<10} {item['id']}" for item in summary["features"]]
    lines.append(f"{len(summary['features'])} feature(s) of {summary['totals']['features']}")
    _echo_bundle(summary, as_json=as_json, lines=lines)
