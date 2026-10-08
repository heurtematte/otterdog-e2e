"""Exit status and verbosity of the offline CLI (O-EXIT-CODES, O-VERBOSITY): validation errors, load errors,
crashes, the -v levels and -vv tracebacks; plan without GitHub (O-LPLAN-ERRORS).

otterdog's commands end in ``_execute_operation`` (otterdog/cli.py:972-1001): the exit status is the largest value an
organization returned, and any exception that escapes an operation is printed by ``print_exception`` (a boxed
``Error: <message>`` on stdout, a rich traceback on stderr with ``-vv`` and more) and exits 2. ``validate`` returns the
number of validation errors (otterdog/operations/validate.py:102) and 1 for a configuration it cannot load (jsonnet
evaluation errors are caught RuntimeErrors: ``Validation failed`` + ``failed to load configuration``), while schema
errors (jsonschema ValidationError) and unknown organizations escape as exceptions (exit 2). Verified offline on v1.6.1
and main 9bdeb75 (identical cli.py, validate.py and logging.py). Since eclipse-csi/otterdog#777 (FIX_777) a schema error
is a load error too: ``Validation failed`` + ``failed to load configuration: invalid value at '<path>': <message>``,
exit 1, no traceback even with ``-vv``; the tests accept the behaviour of the SUT under test (conftest.SutHistory).

``-v`` (otterdog/logging.py init_logging) prints the Info messages (otherwise counted in a hint), ``-vv`` adds DEBUG
logger lines and tracebacks on stderr, ``-vvv`` TRACE lines.

KB-034: the error count IS the exit status, so two validation errors exit 2 like a crash and 256 errors exit 0 (the
status is taken modulo 256), for validate and local-plan alike; KB-025: a secret value with two ':' crashes the
validation. Both are asserted as the correct behaviour in their own known-bug tests (non-strict xfail), the other tests
stay strict.
"""

from __future__ import annotations

import warnings
from typing import Protocol

import pytest

from otterdog_e2e.otterdog.output import normalize_text, strip_ansi
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, DiffOptions, OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

RUN = offline_run_context()
REPO = RUN.name("exit")
DESCRIPTION_ERROR = "setting 'description' exceeds maximum allowed length of 160 chars."
SQUASH_ERROR = f"repository[name=\"{REPO}\"] has 'squash_merge_commit_title' of value 'NOPE'"
SCHEMA_ERROR = "123 is not of type 'boolean'"
TRACEBACK = "Traceback (most recent call last)"
# eclipse-csi/otterdog#777 (squash commit on main): schema errors become load errors (exit 1) instead of crashes (exit 2)
FIX_777 = "7ffc5e5d8bf8a7db7d2757a3fa40af89dc98e6e3"
SCHEMA_LOAD_ERROR = "failed to load configuration: invalid value at 'repositories[name="
FAILED_SUMMARY = "Validation failed: "
# one fragment set per validation outcome (the error counts are otterdog's, verified offline)
ONE_ERROR = ConfigFragments(settings=["description: std.repeat('d', 161)"])
TWO_ERRORS = ConfigFragments(repositories=[f"orgs.newRepo('{REPO}') {{ squash_merge_commit_title: 'NOPE' }}"])
# 256 run repositories with an invalid topic: a comprehension, so a raw layer-2 field (``extra``)
MANY_ERRORS = ConfigFragments(
    extra=[f"_repositories+: [orgs.newRepo('{RUN.prefix}-r%d' % i) {{ topics: ['Bad'] }} for i in std.range(1, 256)]"]
)
SCHEMA_TYPE_ERROR = ConfigFragments(repositories=[f"orgs.newRepo('{REPO}') {{ has_wiki: 123 }}"])
EVALUATION_ERROR = ConfigFragments(
    repositories=[f"orgs.newRepo('{REPO}') {{ description: error 'e2e: deliberate evaluation error' }}"]
)
DUMMY_SECRET = ConfigFragments(
    repositories=[
        f"orgs.newRepo('{REPO}') {{ secrets: [orgs.newRepoSecret('{RUN.const('S')}') {{ value: '********' }}] }}"
    ]
)
DUMMY_INFO = f'Info: repo_secret[name="{RUN.const("S")}"] only has a dummy value, resource will be skipped.'
INFOS_HINT = "in order to print validation infos, enable printing info messages by adding '-v' flag."
PLAN_INFOS_HINT = "there have been 1 validation infos, enable verbose output to display them."
SECRET_WITH_COLONS = ConfigFragments(
    repositories=[
        f"orgs.newRepo('{REPO}') {{ secrets: [orgs.newRepoSecret('{RUN.const('C')}') {{ value: 'pass:a:b' }}] }}"
    ]
)


def render_org(workspace: ConfigWorkspace, fragments: ConfigFragments) -> str:
    """The configuration of the offline organization with ``fragments``, rendered as OfflineEngine renders it."""
    renderer = OfflineConfigRenderer(
        template=workspace.template,
        org=workspace.org,
        plan=OFFLINE_DEFAULT_PLAN,
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
        project=workspace.project,
    )
    return renderer.render(fragments)


class SutHistory(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when it cannot tell."""


def schema_errors_are_load_errors(history: SutHistory, result: CliResult) -> bool:
    """Whether the SUT contains #777 (schema errors are load errors); when the mirror cannot tell, the observed exit
    status decides (with a warning), so the other assertions still check one of the two consistent behaviours."""
    found = history.contains(FIX_777)
    if found is None:
        warnings.warn(f"cannot tell whether {history.label} contains #777 ({FIX_777[:7]})", stacklevel=2)
        return result.exit_code == 1
    return found


def validate(cli: OtterdogCli, fragments: ConfigFragments, *args: str) -> CliResult:
    """Write the configuration and run ``validate --local [args]``."""
    cli.workspace.write_org_config(render_org(cli.workspace, fragments))
    return cli.run("validate", *args, local=True)


def text_of(result: CliResult) -> str:
    """The normalized output (boxes unwrapped)."""
    return normalize_text(result.output)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(text_of(result).splitlines()[-lines:])


@pytest.mark.scenario("O-EXIT-CODES")
def test_validation_outcomes_set_the_exit_status(vendored_cli: OtterdogCli) -> None:
    """A valid configuration exits 0 ('Validation succeeded'); one validation error exits 1 with the error and the
    'Validation failed: 0 info(s), 0 warning(s), 1 error(s)' summary."""
    valid = validate(vendored_cli, ConfigFragments())
    assert valid.exit_code == 0 and valid.validation().ok, tail(valid)
    assert "Validation succeeded" in text_of(valid), tail(valid)

    one = validate(vendored_cli, ONE_ERROR)
    parsed = one.validation()
    assert one.exit_code == 1, f"one validation error exited {one.exit_code}\n{tail(one)}"
    assert (parsed.ok, parsed.infos, parsed.warnings, parsed.errors) == (False, 0, 0, 1), tail(one)
    assert parsed.errors_text() == [DESCRIPTION_ERROR], parsed.errors_text()


@pytest.mark.scenario("O-EXIT-CODES")
def test_load_errors_and_crashes(vendored_cli: OtterdogCli, sut_history: SutHistory) -> None:
    """A jsonnet evaluation error is a configuration otterdog cannot load: 'Validation failed' / 'failed to load
    configuration' and exit 1. A schema type error escapes the operation before #777 (a boxed 'Error: <message>' on
    stdout, no validation summary, nothing on stderr, exit 2) and is a load error naming the invalid value since #777
    (exit 1). An unknown organization escapes the operation: exit 2."""
    evaluation = validate(vendored_cli, EVALUATION_ERROR)
    text = text_of(evaluation)
    assert evaluation.exit_code == 1, f"an evaluation error exited {evaluation.exit_code}\n{tail(evaluation)}"
    assert "Error: Validation failed" in text and "failed to load configuration: " in text, tail(evaluation)
    assert "e2e: deliberate evaluation error" in text, tail(evaluation)
    assert evaluation.validation().load_error, tail(evaluation)

    schema = validate(vendored_cli, SCHEMA_TYPE_ERROR)
    text = text_of(schema)
    assert SCHEMA_ERROR in text and "Validation succeeded" not in text, tail(schema)
    assert TRACEBACK not in schema.output, tail(schema)
    if schema_errors_are_load_errors(sut_history, schema):
        assert schema.exit_code == 1, f"since #777 a schema error is a load error, exited {schema.exit_code}"
        assert "Error: Validation failed" in text and SCHEMA_LOAD_ERROR in text, tail(schema)
        assert schema.validation().load_error, tail(schema)
    else:
        assert schema.exit_code == 2, f"a schema error exited {schema.exit_code}\n{tail(schema)}"
        assert f"Error: {SCHEMA_ERROR}" in text and "Failed validating 'type' in schema" in text, tail(schema)
        assert FAILED_SUMMARY not in text, tail(schema)

    vendored_cli.workspace.write_org_config(render_org(vendored_cli.workspace, ConfigFragments()))
    unknown = vendored_cli.run("validate", "--local", "e2e-offline-nope", org=False)
    text = text_of(unknown)
    assert unknown.exit_code == 2, f"an unknown organization exited {unknown.exit_code}\n{tail(unknown)}"
    assert "Error: unknown organization with name / github_id 'e2e-offline-nope'" in text, tail(unknown)
    assert "Project " not in text, f"no organization may be processed\n{tail(unknown)}"


@pytest.mark.scenario("O-EXIT-CODES")
def test_debug_verbosity_prints_the_traceback(vendored_cli: OtterdogCli, sut_history: SutHistory) -> None:
    """With -vv an escaped exception is a rich traceback on stderr ending with '<type>: <message>' instead of the
    boxed error on stdout, and DEBUG lines are printed; the exit status stays 2. The schema error used here escapes
    before #777 only: since #777 it is a load error (exit 1, boxed on stdout, no traceback)."""
    result = validate(vendored_cli, SCHEMA_TYPE_ERROR, "-vv")
    stderr, stdout = strip_ansi(result.stderr), normalize_text(result.stdout)
    assert "DEBUG " in stdout and "loading configuration for organization 'e2e-offline'" in stdout, stdout[-1500:]
    if schema_errors_are_load_errors(sut_history, result):
        assert result.exit_code == 1, f"exit {result.exit_code}\n{tail(result)}"
        assert TRACEBACK not in stderr and SCHEMA_LOAD_ERROR in stdout, f"{stdout[-1500:]}\n{stderr[-1500:]}"
        return
    assert result.exit_code == 2, f"exit {result.exit_code}\n{tail(result)}"
    assert TRACEBACK in stderr, f"no traceback on stderr with -vv\n{stderr[-1500:]}"
    assert f"ValidationError: {SCHEMA_ERROR}" in stderr, stderr[-1500:]
    assert "_execute_operation" in stderr, "the traceback does not reach otterdog/cli.py _execute_operation"
    assert f"Error: {SCHEMA_ERROR}" not in stdout, f"the error box is printed despite -vv\n{stdout[-1500:]}"


@pytest.mark.scenario("O-EXIT-CODES")
def test_local_plan_exit_status(vendored_cli: OtterdogCli) -> None:
    """local-plan aborts on validation errors ('Planning aborted due to validation errors.', no Plan: line) and exits
    with their number (1 here), and exits 0 when the plan succeeds."""
    workspace = vendored_cli.workspace
    workspace.write_base_config(render_org(workspace, ConfigFragments()))
    workspace.write_org_config(render_org(workspace, ONE_ERROR))
    aborted = vendored_cli.local_plan()
    plan = aborted.plan()
    assert aborted.exit_code == 1, f"exit {aborted.exit_code}\n{tail(aborted)}"
    assert plan.aborted and plan.add is None, tail(aborted)
    assert "Planning aborted due to validation errors." in text_of(aborted), tail(aborted)
    workspace.write_org_config(render_org(workspace, ConfigFragments(repositories=[f"orgs.newRepo('{REPO}')"])))
    planned = vendored_cli.local_plan()
    assert planned.exit_code == 0 and (planned.plan().add, planned.plan().delete) == (1, 0), tail(planned)


@pytest.mark.scenario("O-KB-EXIT-STATUS-ERROR-COUNT")
@pytest.mark.known_bug("KB-034")
def test_validation_errors_never_exit_like_a_crash(vendored_cli: OtterdogCli) -> None:
    """Validation errors should exit 1 whatever their number, keeping 2 for crashes: today two errors exit 2 and 256
    errors exit 0 (validate and local-plan), KB-034."""
    two = validate(vendored_cli, TWO_ERRORS)
    assert two.validation().errors == 2 and SQUASH_ERROR in text_of(two), tail(two)
    workspace = vendored_cli.workspace
    workspace.write_base_config(render_org(workspace, ConfigFragments()))
    many = validate(vendored_cli, MANY_ERRORS)
    assert many.validation().errors == 256, tail(many)
    plan = vendored_cli.local_plan()
    assert "Planning aborted due to validation errors." in text_of(plan), tail(plan)
    codes = {"validate, 2 errors": two.exit_code, "validate, 256 errors": many.exit_code, "local-plan": plan.exit_code}
    assert codes == dict.fromkeys(codes, 1), f"validation errors must exit 1: {codes}"


@pytest.mark.scenario("O-KB-SECRET-WITH-COLONS")
@pytest.mark.known_bug("KB-025")
def test_secret_reference_with_colons_validates(vendored_cli: OtterdogCli) -> None:
    """A secret value 'pass:a:b' (provider pass, path 'a:b') should validate; today the split into exactly two parts
    crashes the validation ('too many values to unpack (expected 2)', exit 2), KB-025."""
    result = validate(vendored_cli, SECRET_WITH_COLONS)
    assert "too many values to unpack" not in text_of(result), tail(result)
    assert result.exit_code == 0 and result.validation().ok, tail(result)


@pytest.mark.scenario("O-LPLAN-ERRORS")
def test_plan_without_github_exits_2(vendored_cli: OtterdogCli) -> None:
    """plan reads the live organization: in the network sandbox of the offline tier GitHub is unreachable, the
    connection error escapes the operation ('Error: Cannot connect to host api.github.com...'), no Plan: line is
    printed and the exit status is 2 (the error of a crash, unlike the 1 of 'planning aborted')."""
    vendored_cli.workspace.write_org_config(
        render_org(vendored_cli.workspace, ConfigFragments(repositories=[f"orgs.newRepo('{REPO}')"]))
    )
    result = vendored_cli.plan(local=True)
    text = text_of(result)
    assert result.exit_code == 2, f"exit {result.exit_code}\n{tail(result)}"
    assert "Error: Cannot connect to host api.github.com" in text, tail(result)
    assert result.infra_error is not None, "the harness classifies the unreachable GitHub as an infra error"
    plan = result.plan()
    assert plan.aborted and plan.add is None and "planning aborted" not in text, tail(result)


def logger_levels(result: CliResult) -> set[str]:
    """The levels of the logger lines printed on stdout (``DEBUG  <message>``, ``TRACE  <message>``, ...)."""
    levels = {"TRACE", "DEBUG", "INFO", "WARNING", "ERROR"}
    return {line.split(" ", 1)[0] for line in strip_ansi(result.stdout).splitlines() if line.split(" ", 1)[0] in levels}


@pytest.mark.scenario("O-VERBOSITY")
def test_verbosity_levels(vendored_cli: OtterdogCli) -> None:
    """Without -v the Info of a dummy secret is only counted ('in order to print validation infos ...'); -v prints
    the Info box and drops the hint; -vv adds DEBUG logger lines and -vvv TRACE lines; the result is the same at every
    level. local-plan counts the hidden Info ('there have been 1 validation infos ...') and prints it with -v."""
    workspace = vendored_cli.workspace
    workspace.write_org_config(render_org(workspace, DUMMY_SECRET))
    results = {flags: validate(vendored_cli, DUMMY_SECRET, *flags) for flags in ((), ("-v",), ("-vv",), ("-vvv",))}
    for flags, result in results.items():
        assert result.exit_code == 0 and "Validation succeeded" in text_of(result), (flags, tail(result))
    quiet, info, debug, trace = results.values()
    assert INFOS_HINT in text_of(quiet) and DUMMY_INFO not in text_of(quiet), tail(quiet)
    assert DUMMY_INFO in text_of(info) and INFOS_HINT not in text_of(info), tail(info)
    assert (logger_levels(quiet), logger_levels(info)) == (set(), set()), "no logger line below -vv"
    assert "DEBUG" in logger_levels(debug) and "TRACE" not in logger_levels(debug), logger_levels(debug)
    assert {"DEBUG", "TRACE"} <= logger_levels(trace), logger_levels(trace)

    workspace.write_base_config(render_org(workspace, ConfigFragments()))
    hidden, shown = vendored_cli.local_plan(), vendored_cli.local_plan_with(DiffOptions(verbose=True))
    assert hidden.exit_code == 0 and PLAN_INFOS_HINT in text_of(hidden) and DUMMY_INFO not in text_of(hidden)
    assert shown.exit_code == 0 and DUMMY_INFO in text_of(shown) and PLAN_INFOS_HINT not in text_of(shown)
