"""cli.repo.default-branch (repositories.default-branch, P0): rename and switch the default branch of a repository.

otterdog changes ``default_branch`` in two ways (providers/github/rest/repo_client.py:592-611): when the configured
branch exists, it PATCHes the repository's default branch (a switch); otherwise it renames the current default branch
(POST .../branches/{branch}/rename). New repositories created with auto_init get their default branch through the
same update right after creation (repo_client.py:267-268), so a configured 'master' renames the initial 'main'.

The scenario is declarative YAML run by the live ScenarioEngine step by step; a probe that YAML cannot express creates
the branch of the switch with the admin Mutator between two steps (a run branch ``e2e/<run>/develop`` of the run
repository). Steps: create (main renamed to master), rename (master renamed to trunk, a single branch remains),
probe (branch e2e/<run>/develop created from trunk), switch (the existing branch becomes the default, trunk stays).
Each step converges; the scenario cleanup removes the repository.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING

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

pytestmark = [pytest.mark.tags("repo")]

SCENARIO_ID = "cli.repo.default-branch"
REPO_SLUG = "def-branch"
BRANCH_SLUG = "develop"
BRANCH_TIMEOUT = 60.0
BRANCH_INTERVAL = 5.0

SCENARIO_YAML = """\
id: cli.repo.default-branch
tier: cli
title: Rename and switch the default branch of a repository
priority: P0
tags: [repo]
steps:
  - name: create
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-def-branch') {
            description: "otterdog e2e: default branch",
            default_branch: "master",
          }
    plan:
      expect: changes
      contains: ['+ add repository[name="{{ p }}-def-branch"]']
      counts: {add: 1, change: 0, delete: 0}
    state:
      - {kind: repo_default_branch, repo: "{{ p }}-def-branch", equals: master}
      - {kind: repo_branches, repo: "{{ p }}-def-branch", equals: [master]}

  - name: rename
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-def-branch') {
            description: "otterdog e2e: default branch",
            default_branch: "trunk",
          }
    plan:
      expect: changes
      contains: ['~ repository[name="{{ p }}-def-branch"]']
      counts: {add: 0, change: 1, delete: 0}
    state:
      - {kind: repo_default_branch, repo: "{{ p }}-def-branch", equals: trunk}
      - {kind: repo_branches, repo: "{{ p }}-def-branch", equals: [trunk]}

  - name: switch
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-def-branch') {
            description: "otterdog e2e: default branch",
            default_branch: "e2e/{{ run }}/develop",
          }
    plan:
      expect: changes
      contains: ['~ repository[name="{{ p }}-def-branch"]']
      counts: {add: 0, change: 1, delete: 0}
    state:
      - {kind: repo_default_branch, repo: "{{ p }}-def-branch", equals: "e2e/{{ run }}/develop"}
      - {kind: repo_branches, repo: "{{ p }}-def-branch", match: {$unordered: [trunk, "e2e/{{ run }}/develop"]}}
      - {kind: repo_branch, repo: "{{ p }}-def-branch", branch: trunk, absent: false}
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


@pytest.mark.scenario(SCENARIO_ID)
def test_default_branch_rename_and_switch(
    scenario_engine: ScenarioEngine, oracle: Oracle, mutator: Mutator, run_ctx: RunContext, tmp_path: Path
) -> None:
    """A missing default branch is a rename of the current one, an existing one a switch that keeps the old branch."""
    scenario = inline_scenario(tmp_path, SCENARIO_YAML)
    repo = run_ctx.name(REPO_SLUG)
    develop = run_ctx.branch(BRANCH_SLUG)

    def create_develop() -> None:
        """Create the run branch e2e/<run>/develop from trunk (the switch target) and wait until GitHub lists it."""
        sha = waiting.wait_until(
            lambda: oracle.branch_sha(repo, "trunk"),
            timeout=BRANCH_TIMEOUT,
            interval=BRANCH_INTERVAL,
            what=f"head of branch trunk of {repo}",
        )
        mutator.create_branch(repo, develop, sha)
        waiting.wait_until(
            lambda: oracle.repo_branch(repo, develop),
            timeout=BRANCH_TIMEOUT,
            interval=BRANCH_INTERVAL,
            what=f"branch {develop} of {repo}",
        )

    run_steps(scenario_engine, scenario, {"rename": create_develop})
