"""cli.repo.from-template (repositories.template-repositories): template repositories, repositories generated from them
with post-processed content, and repositories created without an initial commit.

is_template marks a repository as a template; template_repository '<owner>/<repo>' makes otterdog create the repository
with POST /repos/{owner}/{repo}/generate (include_all_branches false) instead of POST /orgs/{org}/repos, patch the
other settings, wait for the README and render each file listed in post_process_template_content with chevron
(mustache) and the variables org and repo (providers/github/rest/repo_client.py:195-250, :430-433). template_repository
is read-only afterwards (models/repository.py:73) and auto_init / post_process_template_content are model-only, so the
generated repositories converge. auto_init false creates the repository without any commit or branch; otterdog then
skips the default branch update (repo_client.py:592-599).

Steps: template (a template repository), probe (commits README.md and NOTICE.md, both with mustache tags, to the
template; YAML cannot write files), generate (one repository generated from the template with README.md post-processed,
one empty repository without auto_init), probe (the generated contents: README.md rendered with the generated
repository's name and the organization, NOTICE.md, which is not listed, left unrendered). The cleanup removes the three
repositories.
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
    from otterdog_e2e.settings import Target

pytestmark = [pytest.mark.tags("repo")]

SCENARIO_ID = "cli.repo.from-template"
TEMPLATE_SLUG = "tpl"
GENERATED_SLUG = "tpl-gen"
CONTENT_TIMEOUT = 120.0
CONTENT_INTERVAL = 5.0
# mustache tags rendered by otterdog for the files listed in post_process_template_content (chevron: org, repo)
README_TEMPLATE = "# {{repo}}\n\nGenerated from an otterdog-e2e template repository in {{org}}.\n"
NOTICE_TEMPLATE = "{{repo}} is not post-processed: this tag stays as it is.\n"

SCENARIO_YAML = """\
id: cli.repo.from-template
tier: cli
title: Template repositories, generated repositories and repositories without an initial commit
priority: P2
tags: [repo]
steps:
  - name: template
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-tpl') {
            description: "otterdog e2e: template repository",
            is_template: true,
          }
    plan:
      expect: changes
      contains: ['+ add repository[name="{{ p }}-tpl"]']
      counts: {add: 1, change: 0, delete: 0}
    state:
      - {kind: repo, name: "{{ p }}-tpl", match: {is_template: true}}

  - name: generate
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-tpl') {
            description: "otterdog e2e: template repository",
            is_template: true,
          }
        - |
          orgs.newRepo('{{ p }}-tpl-gen') {
            description: "otterdog e2e: generated from a template",
            template_repository: "{{ org }}/{{ p }}-tpl",
            post_process_template_content: ["README.md"],
          }
        - |
          orgs.newRepo('{{ p }}-tpl-empty') {
            description: "otterdog e2e: no initial commit",
            auto_init: false,
          }
    plan:
      expect: changes
      contains:
        - '+ add repository[name="{{ p }}-tpl-gen"]'
        - '+ add repository[name="{{ p }}-tpl-empty"]'
      not_contains: ['~ repository[name="{{ p }}-tpl"]']
      counts: {add: 2, change: 0, delete: 0}
    state:
      - kind: repo
        name: "{{ p }}-tpl-gen"
        match: {is_template: false, template_repository: {full_name: "{{ org }}/{{ p }}-tpl"}}
      - {kind: repo, name: "{{ p }}-tpl-empty", match: {is_template: false}}
      - {kind: repo_branches, repo: "{{ p }}-tpl-empty", equals: []}
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
def test_repository_from_template(
    scenario_engine: ScenarioEngine,
    oracle: Oracle,
    mutator: Mutator,
    run_ctx: RunContext,
    target: Target,
    tmp_path: Path,
) -> None:
    """The generated repository has the template's files, README.md rendered for it, NOTICE.md left as it is."""
    scenario = inline_scenario(tmp_path, SCENARIO_YAML)
    template = run_ctx.name(TEMPLATE_SLUG)
    generated = run_ctx.name(GENERATED_SLUG)

    def commit_template_files() -> None:
        """Commit README.md and NOTICE.md with mustache tags to the template repository."""
        branch = waiting.wait_until(
            lambda: oracle.default_branch(template), timeout=60.0, interval=5.0, what=f"default branch of {template}"
        )
        files = {"README.md": README_TEMPLATE, "NOTICE.md": NOTICE_TEMPLATE}
        mutator.commit_files(template, branch, files, "otterdog-e2e: template content with mustache tags")
        waiting.wait_until(
            lambda: oracle.file_content(template, "NOTICE.md") == NOTICE_TEMPLATE,
            timeout=CONTENT_TIMEOUT,
            interval=CONTENT_INTERVAL,
            what=f"NOTICE.md of {template}",
        )

    def check_generated_contents() -> None:
        """README.md of the generated repository is rendered for it, NOTICE.md (not listed) keeps its tag."""
        rendered = f"# {generated}\n\nGenerated from an otterdog-e2e template repository in {target.org}.\n"
        readme = waiting.poll(
            lambda: oracle.file_content(generated, "README.md"),
            until=lambda content: content == rendered,
            timeout=CONTENT_TIMEOUT,
            interval=CONTENT_INTERVAL,
            what=f"rendered README.md of {generated}",
            raise_on_timeout=False,
        )
        assert readme == rendered, f"README.md of {generated} was not rendered with org/repo: {readme!r}"
        notice = oracle.file_content(generated, "NOTICE.md")
        assert notice == NOTICE_TEMPLATE, f"NOTICE.md of {generated} is not listed but changed: {notice!r}"

    run_steps(scenario_engine, scenario, {"template": commit_template_files, "generate": check_generated_contents})
