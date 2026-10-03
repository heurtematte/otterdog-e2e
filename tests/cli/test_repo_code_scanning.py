"""cli.repo.code-scanning (repositories.code-scanning, regression.458-411-435-code-scanning-live): code scanning default
setup of an existing repository, enabled with a query suite and languages, then disabled.

code_scanning_default_setup_enabled, code_scanning_default_query_suite and code_scanning_default_languages map to
PATCH /repos/{owner}/{repo}/code-scanning/default-setup {state, query_suite, languages}
(providers/github/rest/repo_client.py:464-486, :568-590); the query suite and the languages are compared only while
the setup is enabled (models/repository.py:734-760). Validation checks the configured languages against the languages
GitHub detects in the repository (GET .../languages), 'actions' always counting as detected (#411, v1.0.x), and
the read-back filters the 'javascript-typescript' value GitHub may report (#435). A repository that does not exist yet
cannot be validated (#767: validation error, regression.767-code-scanning-new-repo), so the repository is created
first; a probe commits a Python file and a workflow (only workflow_dispatch: it never runs) and waits until GitHub's
language detection lists Python; the enable step then configures the 'extended' suite for ['actions', 'python'],
the disable step turns the setup off. GitHub configures the default setup asynchronously: the state checks wait for
it (timeouts below) before the converge plans run. Code scanning is free on public repositories of every plan;
GitHub Actions stays enabled (template default), which the default setup needs.

The repository languages are read with Oracle.repo_languages (GET /repos/{org}/{repo}/languages).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.scenarios.model import load_scenario

if TYPE_CHECKING:
    from pathlib import Path

    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.scenarios.engine import ScenarioEngine
    from otterdog_e2e.scenarios.model import Scenario

pytestmark = [pytest.mark.tags("repo", "workflows")]

SCENARIO_ID = "cli.repo.code-scanning"
REPO_SLUG = "code-scan"
LANGUAGE_TIMEOUT = 300.0  # GitHub's language detection runs after the push
LANGUAGE_INTERVAL = 10.0
PROBE_FILES = {
    "src/e2e_probe.py": (
        '"""otterdog-e2e code scanning probe (never imported)."""\n\n\n'
        "def answer() -> int:\n"
        '    """Return the answer."""\n'
        "    return 42\n"
    ),
    ".github/workflows/e2e-probe.yml": (
        "# otterdog-e2e code scanning probe: dispatch only, never triggered by a push\n"
        "name: e2e-probe\n"
        "on: workflow_dispatch\n"
        "permissions: {}\n"
        "jobs:\n"
        "  noop:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - run: echo otterdog-e2e\n"
    ),
}

SCENARIO_YAML = """\
id: cli.repo.code-scanning
tier: cli
title: Code scanning default setup of an existing repository
priority: P1
tags: [repo, workflows]
steps:
  - name: create
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-code-scan') {
            description: "otterdog e2e: code scanning default setup",
          }
    plan:
      expect: changes
      contains: ['+ add repository[name="{{ p }}-code-scan"]']
      counts: {add: 1, change: 0, delete: 0}
    state:
      - {kind: repo_code_scanning_default_setup, repo: "{{ p }}-code-scan", match: {state: not-configured}}

  - name: enable
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-code-scan') {
            description: "otterdog e2e: code scanning default setup",
            code_scanning_default_setup_enabled: true,
            code_scanning_default_query_suite: "extended",
            code_scanning_default_languages: ["actions", "python"],
          }
    validate:
      ok: true
      not_contains: ["is not detected in the repository", "could not validate 'code_scanning_default_languages'"]
    plan:
      expect: changes
      contains: ['~ repository[name="{{ p }}-code-scan"]']
      counts: {add: 0, delete: 0}
    apply:
      expect: ok
      not_contains: ["failed to update code scanning config"]
    state:
      - kind: repo_code_scanning_default_setup
        repo: "{{ p }}-code-scan"
        match: {state: configured, query_suite: extended, languages: {$unordered: [actions, python]}}
        timeout: 600

  - name: disable
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-code-scan') {
            description: "otterdog e2e: code scanning default setup",
            code_scanning_default_setup_enabled: false,
          }
    plan:
      expect: changes
      contains: ['~ repository[name="{{ p }}-code-scan"]']
      counts: {add: 0, change: 1, delete: 0}
    state:
      - kind: repo_code_scanning_default_setup
        repo: "{{ p }}-code-scan"
        match: {state: not-configured}
        timeout: 300
"""


def inline_scenario(tmp_path: Path, text: str) -> Scenario:
    """The scenario of ``text`` loaded with the strict scenario model (written to ``tmp_path``)."""
    path = tmp_path / "scenario.yaml"
    path.write_text(text, encoding="utf-8")
    return load_scenario(path)


def run_steps(engine: ScenarioEngine, scenario: Scenario, probes: Mapping[str, Callable[[], None]]) -> None:
    """Run the steps one by one (steps are declarative), each probe right after its step, and the scenario's cleanup
    once at the end; a failing cleanup fails the test unless an earlier failure is already propagating."""
    reason = engine.skip_reason(scenario)
    if reason:
        pytest.skip(reason)
    failed = False
    try:
        for step in scenario.steps:
            outcome = engine.run(dataclasses.replace(scenario, steps=[step]), cleanup=False)
            if outcome.skipped:
                pytest.skip(outcome.skipped)
            probe = probes.get(step.name)
            if probe is not None:
                probe()
    except BaseException:
        failed = True
        raise
    finally:
        try:
            engine.cleanup(scenario)
        except Exception as exc:
            if not failed:
                raise AssertionError(f"cleanup of {scenario.id} failed: {type(exc).__name__}: {exc}") from exc


def python_detected(oracle: Oracle, repo: str) -> dict[str, Any] | None:
    """The detected languages of ``repo`` once they include Python, else None."""
    languages = oracle.repo_languages(repo) or {}
    return dict(languages) if "Python" in languages else None


@pytest.mark.scenario(SCENARIO_ID)
@pytest.mark.timeout(1800)
def test_code_scanning_default_setup(
    scenario_engine: ScenarioEngine, oracle: Oracle, mutator: Mutator, run_ctx: RunContext, tmp_path: Path
) -> None:
    """The default setup is configured with the extended suite for actions and python, converges, then is disabled."""
    scenario = inline_scenario(tmp_path, SCENARIO_YAML)
    repo = run_ctx.name(REPO_SLUG)

    def commit_sources() -> None:
        """Commit a Python file and a dispatch-only workflow, then wait until GitHub detects Python."""
        branch = waiting.wait_until(
            lambda: oracle.default_branch(repo), timeout=60.0, interval=5.0, what=f"default branch of {repo}"
        )
        mutator.commit_files(repo, branch, PROBE_FILES, "otterdog-e2e: code scanning probe sources")
        languages = waiting.wait_until(
            lambda: python_detected(oracle, repo),
            timeout=LANGUAGE_TIMEOUT,
            interval=LANGUAGE_INTERVAL,
            what=f"Python among the detected languages of {repo}",
        )
        assert "Python" in languages, languages

    run_steps(scenario_engine, scenario, {"create": commit_sources})
