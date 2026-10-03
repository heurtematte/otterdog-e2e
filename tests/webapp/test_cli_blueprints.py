"""W-CLI-BLUEPRINTS (P1): the CLI commands ``list-blueprints`` and ``approve-blueprints`` against the webapp under test
(coverage features cli.list-blueprints, cli.approve-blueprints; otterdog/cli.py:378-397,
operations/list_blueprints.py, operations/approve_blueprints.py).

Both commands read ``<defaults.base_url>/api/blueprints/remediations`` anonymously (``RuntimeError("no base_url set
which is required when using operation '<command>'")`` without a base_url: the CLI prints it and exits 2) and import
otterdog.webapp.db.models: they need otterdog's ``app`` dependency group, which the session's CLIs leave out, so the
test installs the SUT CLI with it (sut.cli_install.install_cli with_app=True; trusted SUTs on the host only: the
CLI must reach the webapp's loopback URL). ``list-blueprints`` prints a "Projects" table (Index, Blueprint ID, GitHub
ID, Repo, PR url); ``approve-blueprints`` loads the local configuration (the repository must be declared), merges each
listed remediation PR with the repository's merge method (rebase, else squash, else merge) and prints "Merging PR
#<n>: merged.". The webapp then records the merged remediation (UpdateBlueprintStatusTask: recheck), deletes the
``otterdog/blueprint/<id>`` branch (DeleteBranchTask) and, at the next check, sets the blueprint to success.

The remediation PR comes from an org ``required_file`` blueprint of this run on a run repository (BlueprintHelper,
cleaned up by the ``blueprints`` fixture); ``-b <blueprint id>`` always restricts both commands to it (without it
approve-blueprints would merge every remediation PR of the organization).
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.blueprints import BlueprintDefinition, RequiredFile
from otterdog_e2e.otterdog.workspace import WorkspaceLayout
from otterdog_e2e.sut.cli_install import install_cli

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.blueprints import BlueprintHelper
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.sut.cli_install import InstalledCli

pytestmark = [pytest.mark.webapp]

FIX_766 = "16f7f324009b0e64c1767174619c0858c50518a6"  # BLUEPRINT_CHECK_INTERVAL: rechecks within the hour (v1.6.0)
REQUIRED_FILE = "E2E_CLI_BLUEPRINT.md"
NO_BASE_URL = "no base_url set which is required when using operation 'list-blueprints'"
STATUS_TIMEOUT = 300.0


def table_rows(output: str) -> list[list[str]]:
    """Body rows of the rich tables in ``output`` (cells of ``│ ... │`` lines whose first cell is a number)."""
    rows = []
    for line in output.splitlines():
        text = line.strip()
        if not text.startswith("│"):
            continue
        cells = [cell.strip() for cell in text.strip("│").split("│")]
        if cells and cells[0].isdigit():
            rows.append(cells)
    return rows


def without_base_url(document: dict[str, object]) -> dict[str, object]:
    """A copy of an otterdog.json document without ``defaults.base_url``."""
    copied = copy.deepcopy(document)
    defaults = copied.get("defaults")
    if isinstance(defaults, dict):
        defaults.pop("base_url", None)
    return copied


@pytest.mark.scenario("W-CLI-BLUEPRINTS", priority="P1")
@pytest.mark.tags("webapp", "cli", "repo")
@pytest.mark.timeout(1800, func_only=True)  # remediation PR, two CLI installs/commands, merge and recheck
def test_list_and_approve_blueprints(
    webapp_scenario: WebappScenario,
    blueprints: BlueprintHelper,
    e2e: E2EContext,
    sut: InstalledCli,
    fresh_workspace: ConfigWorkspace,
) -> None:
    """list-blueprints lists the run's remediation PR (and refuses to run without base_url); approve-blueprints
    merges it; the webapp records the merge, deletes the remediation branch and the blueprint becomes success."""
    s, bp = webapp_scenario, blueprints
    if sut.runtime != "host":
        pytest.skip(f"the SUT CLI runs in {sut.runtime!r}: list/approve-blueprints need the webapp loopback URL")
    repo = s.run_repo("target")
    main_text = s.declare_live({repo: s.describe("required_file target of the blueprint commands")})
    definition = BlueprintDefinition.required_file(
        bp.blueprint_id(s.slug),
        files=[RequiredFile(REQUIRED_FILE, "required by the e2e blueprint of {{repo_name}}\n", strict=True)],
        name_pattern=repo,
        name=f"e2e {s.run_ctx.run_id} blueprint commands",
        description=s.describe("required_file blueprint of list/approve-blueprints"),
    )
    bp.add_blueprint(definition)
    bp.reload()
    task = bp.wait_evaluation(definition, repo, after=bp.check())
    assert task.get("status") == "finished", f"{definition.task_type} of {repo} failed (SUT): {task}"
    number = int(bp.wait_remediation_pr(repo, definition)["number"])
    bp.wait_status(definition.id, repo, "remediation_prepared", timeout=STATUS_TIMEOUT)

    installed = install_cli(sut.sut, e2e.settings, with_app=True)  # list/approve-blueprints import webapp models
    workspace = fresh_workspace
    workspace.use_layout(WorkspaceLayout(base_url=s.api.base_url))
    workspace.write_org_config(main_text)  # approve-blueprints merges PRs of repositories the config declares
    cli = e2e.cli(installed, workspace, name="w-cli-blueprints")
    listed = cli.run("list-blueprints", "-b", definition.id).assert_ok("list-blueprints")
    pr_url = f"https://github.com/{s.org}/{repo}/pull/{number}"
    rows = [row[1:] for row in table_rows(listed.output)]
    assert rows == [[definition.id, s.org, repo, pr_url]], (
        f"list-blueprints must list exactly the remediation PR of {definition.id} (SUT): {rows}\n{listed.output[-2000:]}"
    )

    workspace.use_layout(WorkspaceLayout(document=without_base_url(workspace.otterdog_json())))
    missing = cli.run("list-blueprints", "-b", definition.id)
    assert missing.exit_code == 2 and NO_BASE_URL in missing.output, (
        f"list-blueprints without base_url: exit {missing.exit_code} (expected 2 and {NO_BASE_URL!r}):\n"
        f"{missing.output[-2000:]}"
    )
    workspace.use_layout(WorkspaceLayout(base_url=s.api.base_url))

    merged_at = bp.now()
    approved = cli.run("approve-blueprints", "-b", definition.id).assert_ok("approve-blueprints")
    assert f"Merging PR #{number}: merged." in approved.output, f"approve-blueprints:\n{approved.output[-2000:]}"
    pull = s.reaction(
        lambda: s.oracle.pull(repo, number),
        until=lambda value: value is not None and bool(value.get("merged")),
        what=f"remediation PR #{number} of {repo} merged by approve-blueprints",
        timeout=120,
    )
    assert pull is not None
    status_task = s.wait_repo_task("UpdateBlueprintStatusTask", after=merged_at, repo=repo, pull_request=number)
    assert status_task.get("status") == "finished", f"UpdateBlueprintStatusTask of the merge (SUT): {status_task}"
    branch_task = s.wait_repo_task("DeleteBranchTask", after=merged_at, repo=repo)
    assert branch_task.get("status") == "finished", (
        f"DeleteBranchTask of {definition.remediation_branch}: {branch_task}"
    )
    s.reaction(
        lambda: s.oracle.branch_sha(repo, definition.remediation_branch),
        until=lambda sha: sha is None,
        what=f"{definition.remediation_branch} of {repo} deleted",
        timeout=120,
    )
    row = bp.wait_status(definition.id, repo, ("recheck", "success"), timeout=STATUS_TIMEOUT)
    if s.webapp_includes(FIX_766) is not False:  # rechecks within the hour need BLUEPRINT_CHECK_INTERVAL
        bp.check()
        row = bp.wait_status(definition.id, repo, "success", timeout=STATUS_TIMEOUT)
    assert row.get("remediation_pr") is None, f"blueprint status keeps the merged remediation PR: {row}"
    assert not bp.remediations(blueprint_id=definition.id), "a merged remediation is still listed as open"
    s.write_evidence({"list": listed.output[-3000:], "approve": approved.output[-3000:], "status": row})
