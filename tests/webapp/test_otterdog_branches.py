"""W-OPEN-PR-BRANCH (P2): the webapp deletes the ``otterdog/*`` head branch of a closed PR, and a branch GitHub
already deleted is no error (regression otterdog#713, 2bbd1a4, v1.5.0).

``otterdog open-pr`` (the trusted reset CLI on a fresh workspace) opens config PRs from ``otterdog/<branch>``; the
webapp schedules a DeleteBranchTask for every ``closed`` pull_request delivery of such a branch, merged or not
(webhook/__init__.py:89-97, tasks/delete_branch.py). The task records no pull request number (TaskModel without
it), so it is matched by type and creation time.

1. PR A is closed: a DeleteBranchTask finishes and the branch is gone (GET git/ref/heads/otterdog/... 404).
2. PR B loses its head branch first (the harness deletes it, as GitHub does after a merge with
   delete_branch_on_merge): GitHub closes the PR, the closed delivery arrives with the branch already gone, and the
   DeleteBranchTask must finish all the same (404/422 of DELETE git/refs tolerated since #713) instead of failing.

Nothing is merged; the PRs are adopted by the flow (closed and their branches deleted again by the teardown, a
no-op for gone branches).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.sut.cli_install import InstalledCli

pytestmark = [pytest.mark.webapp]

FIX_713 = "2bbd1a4f67b828660b131f010919e4274f1856ef"  # fix: mange already deleted branch by github (#713)


class DeletedBranchRegressionError(AssertionError):
    """The DeleteBranchTask failed on a branch GitHub had already deleted (otterdog#713)."""


@pytest.mark.scenario("W-OPEN-PR-BRANCH", priority="P2")
@pytest.mark.tags("webapp", "cli")
def test_otterdog_branches_are_deleted(
    request: pytest.FixtureRequest,
    webapp_scenario: WebappScenario,
    e2e: E2EContext,
    reset_sut: InstalledCli,
    fresh_workspace: ConfigWorkspace,
    mutator: Mutator,
) -> None:
    """open-pr PRs: closing one makes the webapp delete its otterdog/* branch; deleting the branch of the other one
    first (GitHub closes the PR) leaves the webapp a branch that is gone, which its DeleteBranchTask tolerates."""
    s = webapp_scenario
    s.xfail_unless_includes(
        request,
        FIX_713,
        error=DeletedBranchRegressionError,
        reason="the webapp under test predates otterdog#713 (2bbd1a4): deleting a gone branch fails the task",
        strict=True,  # released in v1.5.0
    )
    cli = e2e.cli(reset_sut, fresh_workspace, name="w-open-pr-branch")
    closed = s.open_pr_with_cli(cli, s.harmless_text(), suffix="closed")
    s.wait_validation(closed)  # validated like any config PR
    s.wait_sync(closed)

    closed_at = s.now()
    s.flow.close(closed)
    s.flow.wait_delivery(closed, event="pull_request", action="closed", after=closed_at)
    task = s.wait_repo_task("DeleteBranchTask", after=closed_at)
    assert task.get("status") == "finished", f"DeleteBranchTask of {closed.branch}: {task}"
    s.wait_branch_gone(closed.branch)

    gone = s.open_pr_with_cli(cli, s.harmless_text(), suffix="gone")
    s.wait_validation(gone)
    s.wait_sync(gone)
    s.quiesce()
    deleted_at = s.now()
    mutator.delete_ref(s.repo, f"heads/{gone.branch}")  # GitHub closes a PR whose head branch is deleted
    s.flow.close(gone)  # a no-op when GitHub closed it already: either way one closed delivery follows the deletion
    s.flow.wait_delivery(gone, event="pull_request", action="closed", after=deleted_at)
    assert s.oracle.branch_sha(s.repo, gone.branch) is None, f"precondition: {gone.branch} deleted before the close"
    task = s.wait_repo_task("DeleteBranchTask", after=deleted_at)
    s.write_evidence({"closed": closed.number, "gone": gone.number, "task": task})
    if task.get("status") != "finished":
        raise DeletedBranchRegressionError(f"DeleteBranchTask of the gone {gone.branch} failed: {task}")
