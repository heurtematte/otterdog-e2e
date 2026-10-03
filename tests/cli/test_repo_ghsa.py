"""cli.repo.ghsa-ignored (repositories.ghsa-forks-ignored): the temporary private fork of a repository security advisory
is never loaded, planned or removed by otterdog.

GitHub names the temporary private fork of a draft advisory '<repo>-ghsa-xxxx-xxxx-xxxx'; otterdog drops such names
from the organization's repositories before anything else (GitHubProvider.get_repos with utils.is_ghsa_repo,
otterdog/providers/github/__init__.py:234-237, otterdog/utils.py:520-526), so a configuration that does not declare
the fork never plans its removal, not even with ``apply -d`` and a repository filter (``-r e2e-<run>-*``) that matches
its name. Steps: create (a public run repository), probe (a draft advisory with an e2e summary and its temporary
private fork, created with the admin Mutator; GitHub creates the fork asynchronously), untouched (the same
configuration plans nothing, the fork appears nowhere in the plan), guarded-delete (a description change applied with
``apply -d``: the fork is neither planned nor deleted, it still exists). The test then closes the advisory and deletes
the fork itself, before the scenario cleanup removes the repository (advisories cannot be deleted through the API; the
run repository's deletion and the janitor remove what is left after a failure).
"""

from __future__ import annotations

import dataclasses
import logging
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

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.tags("repo")]

SCENARIO_ID = "cli.repo.ghsa-ignored"
REPO_SLUG = "advisory"
FORK_TIMEOUT = 300.0  # "it may take up to 5 minutes" (POST .../security-advisories/{ghsa_id}/forks)
FORK_INTERVAL = 10.0

SCENARIO_YAML = """\
id: cli.repo.ghsa-ignored
tier: cli
title: The temporary private fork of a security advisory is ignored
priority: P2
tags: [repo]
steps:
  - name: create
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-advisory') {
            description: "otterdog e2e: repository with a security advisory",
          }
    plan:
      expect: changes
      contains: ['+ add repository[name="{{ p }}-advisory"]']
      counts: {add: 1, change: 0, delete: 0}
    state:
      - {kind: repo, name: "{{ p }}-advisory", match: {private: false}}

  - name: untouched
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-advisory') {
            description: "otterdog e2e: repository with a security advisory",
          }
    plan:
      expect: noop
      not_contains: ['repository[name="{{ p }}-advisory-ghsa-']

  - name: guarded-delete
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-advisory') {
            description: "otterdog e2e: repository with a security advisory (updated)",
          }
    plan:
      expect: changes
      contains: ['~ repository[name="{{ p }}-advisory"]']
      not_contains: ['repository[name="{{ p }}-advisory-ghsa-']
      counts: {add: 0, change: 1, delete: 0}
    apply:
      delete: true
      not_contains: ['{{ p }}-advisory-ghsa-']
    state:
      - kind: repo
        name: "{{ p }}-advisory"
        match: {description: "otterdog e2e: repository with a security advisory (updated)"}
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
@pytest.mark.timeout(1200)
def test_advisory_fork_is_ignored(
    scenario_engine: ScenarioEngine, oracle: Oracle, mutator: Mutator, run_ctx: RunContext, tmp_path: Path
) -> None:
    """Neither plan nor ``apply -d`` touches the advisory's temporary private fork, which keeps existing."""
    scenario = inline_scenario(tmp_path, SCENARIO_YAML)
    repo = run_ctx.name(REPO_SLUG)
    created: dict[str, Any] = {}

    def create_advisory_fork() -> None:
        """A draft advisory (e2e summary) and its temporary private fork '<repo>-ghsa-...', private and existing."""
        advisory = mutator.create_security_advisory(repo, summary=f"{run_ctx.prefix}-advisory: otterdog-e2e probe")
        created["ghsa_id"] = ghsa_id = str(advisory["ghsa_id"])
        fork = mutator.create_advisory_fork(repo, ghsa_id)
        created["fork"] = name = str(fork["name"])
        assert name.startswith(f"{repo}-ghsa-"), f"unexpected temporary fork name {name!r}"
        live = waiting.wait_until(
            lambda: oracle.repo(name), timeout=FORK_TIMEOUT, interval=FORK_INTERVAL, what=f"temporary fork {name}"
        )
        assert live.get("private") is True, f"temporary fork {name} is not private"

    def remove_probe_objects() -> None:
        """Close the advisory and delete its temporary fork (best effort, before the repository is removed)."""
        if "ghsa_id" in created:
            try:
                mutator.close_security_advisory(repo, created.pop("ghsa_id"))
            except (RuntimeError, OSError) as exc:  # a courtesy: deleting the repository removes its advisories
                logger.info("closing the advisory of %s failed: %s", repo, type(exc).__name__)
        if "fork" in created:
            mutator.delete_repo(created.pop("fork"))

    def fork_left_alone() -> None:
        """The guarded apply -d did not touch the temporary fork: it still exists; then the probe objects go."""
        name = created["fork"]
        assert oracle.repo(name) is not None, f"apply -d removed the temporary fork {name}"
        remove_probe_objects()

    try:
        run_steps(scenario_engine, scenario, {"create": create_advisory_fork, "guarded-delete": fork_left_alone})
    finally:
        remove_probe_objects()
