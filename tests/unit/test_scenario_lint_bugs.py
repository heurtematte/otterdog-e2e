"""The offline scenario lint's helpers (tests/offline/test_scenario_lint.py): the lint plan, the validation-error
expectation and the known bug that turns a lint mismatch into an expected failure (a step's own known_bug first)."""

from __future__ import annotations

import importlib.util
import sys
import textwrap
from functools import cache
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

from otterdog_e2e.known_bugs import KnownBug
from otterdog_e2e.scenarios.model import Scenario, load_scenario

ROOT = Path(__file__).resolve().parents[2]
LINT_MODULE = ROOT / "tests" / "offline" / "test_scenario_lint.py"
DATA = ROOT / "tests" / "unit" / "data"
BUGS = {
    "KB-025": KnownBug("KB-025", "a secret value with two ':' crashes validation", status="confirmed"),
    "KB-030": KnownBug("KB-030", "required property crash", status="confirmed", scenarios=["cli.lint.listed"]),
    "KB-090": KnownBug("KB-090", "fixed long ago", status="fixed", fixed_in="1.6.0"),
}


@cache
def lint() -> ModuleType:
    """tests/offline/test_scenario_lint.py as a standalone module (test modules cannot import each other)."""
    name = "otterdog_e2e_scenario_lint_under_test"
    spec = importlib.util.spec_from_file_location(name, LINT_MODULE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def scenario(tmp_path: Path, text: str) -> Scenario:
    """Load a live scenario written to scenarios/cli/ below ``tmp_path``."""
    directory = tmp_path / "scenarios" / "cli"
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "case.yaml"
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return load_scenario(path)


def context() -> SimpleNamespace:
    """What the lint reads from the E2EContext: known_bugs()."""
    return SimpleNamespace(known_bugs=lambda: BUGS)


def test_lint_plan_and_validation_error_expectations(tmp_path: Path) -> None:
    """The lint validates with variables.plan, else min_plan; validate.ok false or plan validation_error expect errors."""
    case = scenario(
        tmp_path,
        """
        id: cli.lint.plan
        title: t
        min_plan: team
        steps:
          - {name: ok, fragments: {}}
          - {name: invalid, fragments: {}, validate: {ok: false}}
          - {name: rejected, fragments: {}, plan: {expect: validation_error}}
        """,
    )
    assert lint().lint_plan(case) == "team"
    assert [lint().expects_validation_errors(step) for step in case.steps] == [False, True, True]


def test_a_step_known_bug_comes_first(tmp_path: Path) -> None:
    """A step's own known_bug decides (with the step named); other steps fall back to the scenario's bugs."""
    case = scenario(
        tmp_path,
        """
        id: cli.lint.listed
        title: t
        steps:
          - {name: crash, known_bug: KB-025, fragments: {}}
          - {name: other, fragments: {}}
        """,
    )
    crash, other = case.steps
    reason = lint().affecting_bug_reason(context(), case, crash, "1.6.1")
    assert reason == "KB-025: a secret value with two ':' crashes validation (step 'crash')"
    assert lint().affecting_bug_reason(context(), case, other, "1.6.1") == "KB-030: required property crash"


def test_fixed_and_unknown_bugs(tmp_path: Path) -> None:
    """A fixed bug the SUT contains is no excuse (strict); an id missing from known_bugs.yaml counts as affecting."""
    case = scenario(
        tmp_path,
        """
        id: cli.lint.fixed
        title: t
        steps:
          - {name: fixed, known_bug: KB-090, fragments: {}}
          - {name: unknown, known_bug: KB-999, fragments: {}}
        """,
    )
    fixed, unknown = case.steps
    assert lint().affecting_bug_reason(context(), case, fixed, "1.6.1") is None
    assert lint().affecting_bug_reason(context(), case, fixed, "1.5.0").startswith("KB-090: fixed long ago")
    assert lint().affecting_bug_reason(context(), case, unknown, "1.6.1") == (
        "KB-999: not listed in known_bugs.yaml (step 'unknown')"
    )
    plain = scenario(tmp_path, "id: cli.lint.none\ntitle: t\nsteps: [{name: s, fragments: {}}]\n")
    assert lint().affecting_bug_reason(context(), plain, plain.steps[0], "1.6.1") is None


def test_a_step_bug_that_leaves_validate_out_keeps_the_lint_strict(tmp_path: Path) -> None:
    """BAT-09: known_bug {id, phases: [converge]} never excuses a lint mismatch; an unscoped step bug or one naming
    validate does."""
    case = scenario(
        tmp_path,
        """
        id: cli.lint.phases
        title: t
        steps:
          - {name: converge-bug, known_bug: {id: KB-025, phases: [converge]}, fragments: {}}
          - {name: validate-bug, known_bug: {id: KB-025, phases: [validate, plan]}, fragments: {}}
        """,
    )
    converge, validate = case.steps
    assert lint().affecting_bug_reason(context(), case, converge, "1.6.1") is None
    assert lint().affecting_bug_reason(context(), case, validate, "1.6.1").startswith("KB-025")


def cli_result(output: str, exit_code: int = 1) -> Any:
    """A CliResult carrying ``output`` (validation parsed from it)."""
    from otterdog_e2e.otterdog.runner import CliResult

    return CliResult(["otterdog", "validate"], exit_code, output, "", 0.1, Path("/nonexistent"))


def test_error_steps_need_reported_validation_errors() -> None:
    """BAT-09: a step expecting validation errors passes the lint only when otterdog reports them (a summary with
    errors, or a schema violation); a crash, a load error or no error at all fail."""
    problems = lint().error_report_problems
    summary = "Validation failed: 0 info(s), 0 warning(s), 1 error(s)\n"
    assert problems(cli_result(summary)) == []
    schema = (DATA / "validate-schema.txt").read_text(encoding="utf-8")
    assert problems(cli_result(schema)) == []
    crash = "Error: 'RequiredStatusChecks' object has no attribute 'get_model_header'\n"
    assert problems(cli_result(crash, 2))[0].startswith("otterdog crashed")
    traceback = "Traceback (most recent call last):\n  File x\nKeyError: 'a'\n"
    assert problems(cli_result(traceback, 2))[0].startswith("otterdog crashed")
    assert problems(cli_result("Validation succeeded: 0 info(s), 0 warning(s), 0 error(s)\n", 0))[0].startswith(
        "no validation error reported"
    )


def test_team_steps_are_linted_without_their_teams(tmp_path: Path) -> None:
    """BAT-09: a step expecting to validate is linted with its teams fragments removed (team validation calls
    GitHub); a step expecting a validation error with teams, or code scanning languages, is still skipped."""
    from otterdog_e2e.otterdog.render import ConfigFragments

    case = scenario(
        tmp_path,
        """
        id: cli.lint.teams
        title: t
        steps:
          - name: ok
            fragments:
              teams: ["orgs.newTeam('{{ p }}-t') { members: [] }"]
              repositories: ["orgs.newRepo('{{ p }}-r')"]
          - name: invalid
            fragments: {teams: ["orgs.newTeam('{{ p }}-t') { privacy: 'closed' }"]}
            validate: {ok: false}
        """,
    )
    ok, invalid = case.steps
    fragments = ConfigFragments(teams=["orgs.newTeam('x')"], repositories=["orgs.newRepo('y')"])
    linted, note = lint().lint_fragments(ok, fragments)
    assert linted is not None and linted.teams == [] and linted.repositories == ["orgs.newRepo('y')"]
    assert note is not None and "without its teams" in note
    skipped, reason = lint().lint_fragments(invalid, ConfigFragments(teams=["orgs.newTeam('x')"]))
    assert skipped is None and reason is not None and "teams fragments" in reason
    languages = ConfigFragments(repositories=["orgs.newRepo('y') { code_scanning_default_languages: ['python'] }"])
    assert lint().lint_fragments(ok, languages)[0] is None
