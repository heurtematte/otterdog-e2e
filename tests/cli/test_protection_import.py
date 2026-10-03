"""cli.import.protections (regression.675-ruleset-unset-defaults): ``import`` of a repository's protections round-trips.

#675 (v1.3.4, "Fix ruleset default value when UNSET"): ruleset values the template leaves UNSET or sets to a nested
default (newPullRequest(), newStatusChecks(), null merge queue) must be rendered by ``import`` so that the imported
configuration compares equal to the live ruleset (models/ruleset.py:460-495 and Ruleset.to_jsonnet). The test creates
a public run repository with a branch protection rule (allowances, an 'any:' and a plain status check) and two
rulesets: a default-branch ruleset with bypass actors, a partial pull request rule, status checks (plain and the
GitHub Actions integration id) and a merge queue, and a tag ruleset without pull request and status check rules,
whose import must spell them null (the branch ruleset's nested settings are printed as 'required_pull_request+:' and
'required_status_checks+:' extensions of the template defaults, the merge queue as orgs.newMergeQueue()). It then
imports the organization (``import -f -n``) into a fresh workspace, cuts
the repository's block out of the imported jsonnet (otterdog prints one 'orgs.newRepo(...) {' ... '},' block per
repository at one indentation level) and plans that block with the session's baseline: nothing may change for the
repository. Planning the block with the regular baseline (instead of the imported organization settings) keeps
organization-level import issues (KB-024) out of this round trip.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml

from otterdog_e2e.scenarios.model import load_scenario

if TYPE_CHECKING:
    from pathlib import Path

    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.scenarios.engine import ScenarioEngine
    from otterdog_e2e.scenarios.model import Scenario
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli", "rulesets", "bpr", "repo")]

SCENARIO_ID = "cli.import.protections"
REPO_SLUG = "imp-protect"

CREATE_YAML = """\
id: cli.import.protections
tier: cli
title: Protections of a repository for the import round trip
priority: P2
tags: [rulesets, bpr, repo]
steps:
  - name: create
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-imp-protect') {
            description: "otterdog e2e: import of protections",
            branch_protection_rules: [
              orgs.newBranchProtectionRule('main') {
                required_approving_review_count: 1,
                requires_status_checks: true,
                required_status_checks+: ["e2e-plain", "any:e2e-any"],
                restricts_review_dismissals: true,
                review_dismissal_allowances: ["@{{ logins.admin }}"],
                bypass_force_push_allowances: ["@{{ logins.admin }}"],
              },
            ],
            rulesets: [
              orgs.newRepoRuleset('{{ p }}-imp-branch') {
                include_refs+: ["~DEFAULT_BRANCH"],
                bypass_actors: ["#OrganizationAdmin", "#Maintain:pull_request"],
                required_pull_request+: {
                  required_approving_review_count: 1,
                  requires_last_push_approval: true,
                },
                required_status_checks: orgs.newStatusChecks() {
                  strict: true,
                  do_not_enforce_on_create: true,
                  status_checks: ["e2e-plain", "15368:e2e/actions"],
                },
                required_merge_queue: orgs.newMergeQueue() {
                  merge_method: "SQUASH",
                  build_concurrency: 2,
                },
              },
              orgs.newRepoRuleset('{{ p }}-imp-tags') {
                target: "tag",
                include_refs+: ["~ALL"],
                allows_updates: false,
                required_pull_request: null,
                required_status_checks: null,
              },
            ],
          }
    plan:
      expect: changes
      contains:
        - '+ add branch_protection_rule[pattern="main", repository={{ p }}-imp-protect]'
        - '+ add repo_ruleset[name="{{ p }}-imp-branch", repository={{ p }}-imp-protect]'
        - '+ add repo_ruleset[name="{{ p }}-imp-tags", repository={{ p }}-imp-protect]'
      counts: {add: 4, change: 0, delete: 0}
"""


def inline_scenario(path: Path, document: str | dict) -> Scenario:
    """The scenario of ``document`` (YAML text or a mapping) loaded with the strict scenario model from ``path``."""
    text = document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False, width=1000)
    path.write_text(text, encoding="utf-8")
    return load_scenario(path)


def repo_block(text: str, repo: str) -> str:
    """The 'orgs.newRepo('<repo>') { ... }' block of an imported configuration, without its trailing comma."""
    lines = text.splitlines()
    pattern = re.compile(rf"^(\s*)orgs\.newRepo\('{re.escape(repo)}'\)")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match is None:
            continue
        closing = f"{match.group(1)}}},"
        for end in range(index + 1, len(lines)):
            if lines[end] == closing:
                return "\n".join([*lines[index:end], f"{match.group(1)}}}"])
        raise AssertionError(f"the imported block of {repo} has no closing line {closing!r}")
    raise AssertionError(f"the import does not declare repository {repo}")


def roundtrip_document(block: str) -> dict:
    """A one-step scenario planning the imported block (Jinja-protected) with the baseline: no change expected."""
    return {
        "id": SCENARIO_ID,
        "tier": "cli",
        "title": "Imported protections plan no change",
        "priority": "P2",
        "tags": ["rulesets", "bpr", "repo"],
        "steps": [
            {
                "name": "roundtrip",
                "fragments": {"repositories": ["{% raw %}" + block + "{% endraw %}"]},
                "validate": {"ok": True},
                "plan": {"expect": "noop"},
            }
        ],
    }


@pytest.mark.scenario(SCENARIO_ID)
@pytest.mark.timeout(1200)
def test_imported_protections_plan_no_change(
    scenario_engine: ScenarioEngine,
    e2e: E2EContext,
    sut: InstalledCli,
    template_ref: TemplateRef,
    run_ctx: RunContext,
    tmp_path: Path,
) -> None:
    """The imported repository block declares both rulesets (nested defaults and nulls spelled out) and the rule, and
    planning it against the live organization changes nothing."""
    create = inline_scenario(tmp_path / "create.yaml", CREATE_YAML)
    reason = scenario_engine.skip_reason(create)
    if reason:
        pytest.skip(reason)
    repo = run_ctx.name(REPO_SLUG)
    failed = False
    try:
        scenario_engine.run(create, cleanup=False)
        workspace = e2e.workspace(e2e.unique_name("import-protections"), template_ref)
        cli = e2e.cli(sut, workspace, name=f"ws-{workspace.root.name}")
        cli.import_config(force=True).assert_ok("import -f -n")
        block = repo_block(workspace.read_org_config(), repo)
        expected = [
            "orgs.newBranchProtectionRule('main')",
            f"orgs.newRepoRuleset('{run_ctx.name('imp-branch')}')",
            f"orgs.newRepoRuleset('{run_ctx.name('imp-tags')}')",
            "required_merge_queue: orgs.newMergeQueue()",
            "required_status_checks+:",
            "required_pull_request+:",
            "required_pull_request: null",
            "required_status_checks: null",
            '"15368:e2e/actions"',
            '"any:e2e-any"',
            '"#Maintain:pull_request"',
        ]
        missing = [item for item in expected if item not in block]
        assert not missing, f"the imported block of {repo} lacks {missing}:\n{block}"
        roundtrip = inline_scenario(tmp_path / "roundtrip.yaml", roundtrip_document(block))
        scenario_engine.run(roundtrip, cleanup=False)
    except BaseException:
        failed = True
        raise
    finally:
        try:
            scenario_engine.cleanup(create)
        except Exception as exc:
            if not failed:
                raise AssertionError(f"cleanup of {create.id} failed: {type(exc).__name__}: {exc}") from exc
