"""otterdog commands that change the content of repositories: dispatch-workflow, delete-file, sync-template.

Every repository is a run repository applied by the SUT (``live_config``: baseline + the repository, removed with the
run's objects after the test); files are committed with the admin mutator; results are read back with the oracle.

cli.dispatch-workflow: ``dispatch-workflow -r <repo> --workflow <file>`` dispatches the workflow on the default branch
    ("workflow '<file>' dispatched for repo '<repo>'", a workflow_dispatch run appears); an unknown workflow prints
    "failed to dispatch workflow ..." and an unknown repository fails (otterdog/operations/dispatch_workflow.py,
    providers/github/rest/repo_client.py dispatch_workflow).
cli.kb.dispatch-workflow-exit-code (known bug KB-045): a refused dispatch must not exit 0.
cli.delete-file: ``delete-file -r <repo> --path <p> [-m <msg>]`` deletes a file of a CONFIGURED repository with the
    given commit message (default "Deleting file '<p>' with otterdog."); a missing file creates no commit; a
    repository the configuration does not declare is never touched (otterdog/operations/delete_file.py).
cli.kb.delete-file-missing (known bug KB-044): a file that does not exist is reported 'succeeded'.
cli.kb.delete-file-refused (known bug KB-043): a refused deletion (protected default branch) crashes with an
    UnboundLocalError instead of printing 'failure deleting file' and exiting 1.
cli.sync-template: ``sync-template -r <repo>`` re-copies every file of the template repository into a repository
    created from it, renders the post_process_template_content files with the {{org}}/{{repo}} variables, prints
    "updated file '<path>'" per changed file and nothing on a second run; repositories without template_repository
    are skipped (otterdog/operations/sync_template.py, repo_client.sync_from_template_repository).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.github.http import GitHubError

if TYPE_CHECKING:
    from conftest import LiveConfig
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import Target

logger = logging.getLogger(__name__)

pytestmark = [pytest.mark.tags("cli", "repo")]

WORKFLOW_FILE = "e2e-dispatch.yml"
WORKFLOW_PATH = f".github/workflows/{WORKFLOW_FILE}"
WORKFLOW = """name: e2e-dispatch
on:
  workflow_dispatch:
jobs:
  noop:
    runs-on: ubuntu-latest
    steps:
      - run: echo "otterdog e2e dispatch"
"""
WORKFLOW_TIMEOUT = 120.0  # a pushed workflow is indexed asynchronously
RUN_TIMEOUT = 180.0  # the run of a dispatch shows up after a few seconds
DISPATCH_ATTEMPTS = 3  # GitHub can refuse the first dispatches of a workflow it just indexed (404/422)
DISPATCH_INTERVAL = 10.0
UNBOUND_RE = re.compile(r"UnboundLocalError|cannot access local variable|referenced before assignment")


def repo_config(live_config: LiveConfig, *repositories: str) -> str:
    """The baseline plus the repository expressions."""
    return live_config.render(*repositories)


def head_commit(oracle: Oracle, repo: str, branch: str = "main") -> dict[str, Any]:
    """Head commit of ``branch`` (sha and message)."""
    sha = oracle.branch_sha(repo, branch)
    assert sha, f"{repo} has no branch {branch}"
    commit = oracle.git_commit(repo, sha)
    assert commit is not None, f"{repo}@{sha} not found"
    return {"sha": sha, "message": str(commit.get("message") or "")}


def wait_head_change(oracle: Oracle, repo: str, old_sha: str, branch: str = "main") -> dict[str, Any]:
    """The head commit once it differs from ``old_sha`` (the last one read when it never does)."""
    return waiting.poll(
        lambda: head_commit(oracle, repo, branch),
        until=lambda commit: commit["sha"] != old_sha,
        timeout=60.0,
        interval=3.0,
        what=f"a new commit on {repo}@{branch}",
        raise_on_timeout=False,
    )


# --- dispatch-workflow -------------------------------------------------------------------------------------------------
def dispatch(cli: OtterdogCli, repo: str, workflow: str) -> CliResult:
    """``dispatch-workflow -r <repo> --workflow <workflow>`` (no org config needed: only the token)."""
    return cli.run("dispatch-workflow", "-r", repo, "--workflow", workflow)


@pytest.mark.scenario("cli.dispatch-workflow", priority="P2")
@pytest.mark.tags("workflows")
@pytest.mark.timeout(1200)
def test_dispatch_workflow_starts_a_run(
    live_config: LiveConfig,
    mutator: Mutator,
    oracle: Oracle,
    target: Target,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """A workflow_dispatch workflow of a run repository is dispatched on the default branch (a workflow_dispatch run
    of that workflow appears); an unknown workflow is reported as not dispatched; an unknown repository fails."""
    repo = live_config.name("dispatch")
    live_config.apply(
        repo_config(live_config, f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: dispatch-workflow' }}"),
        what="apply the workflow repository",
    )
    assert live_config.wait_repo(repo) is not None, f"{repo} was not created"
    branch = oracle.default_branch(repo) or "main"
    mutator.commit_files(
        repo, branch, {WORKFLOW_PATH: WORKFLOW}, f"otterdog-e2e {live_config.run_ctx.run_id}: workflow"
    )
    indexed = waiting.poll(
        lambda: oracle.workflow(repo, WORKFLOW_FILE),
        until=lambda workflow: bool(workflow) and workflow.get("state") == "active",
        timeout=WORKFLOW_TIMEOUT,
        interval=5.0,
        what=f"workflow {WORKFLOW_FILE} of {repo} active",
        raise_on_timeout=False,
    )
    assert indexed and indexed.get("state") == "active", f"{WORKFLOW_FILE} never became active: {indexed}"
    cli = live_config.cli
    dispatched = f"workflow '{WORKFLOW_FILE}' dispatched for repo '{repo}'"
    result = waiting.poll(
        lambda: dispatch(cli, repo, WORKFLOW_FILE),
        until=lambda done: dispatched in cli_lines(done),
        max_attempts=DISPATCH_ATTEMPTS,
        interval=DISPATCH_INTERVAL,
        what=f"dispatch of {WORKFLOW_FILE}",
        raise_on_timeout=False,
    )
    text = cli_lines(result)
    assert f"Dispatching workflow '{WORKFLOW_FILE}' in organization repo '{repo}':" in text, text[-2000:]
    assert dispatched in text and result.exit_code == 0, f"exit {result.exit_code}:\n{text[-2000:]}"
    runs: list[dict[str, Any]] = []
    try:
        runs = waiting.poll(
            lambda: oracle.find_workflow_runs(repo, workflow=WORKFLOW_FILE, event="workflow_dispatch"),
            until=bool,
            timeout=RUN_TIMEOUT,
            interval=5.0,
            what=f"a workflow_dispatch run of {WORKFLOW_FILE}",
            raise_on_timeout=False,
        )
        assert runs, f"no workflow_dispatch run of {WORKFLOW_FILE} in {repo} after the dispatch"
        assert {run.get("head_branch") for run in runs} == {branch}, [run.get("head_branch") for run in runs]
        missing = dispatch(cli, repo, "e2e-missing.yml")
        missing_text = cli_lines(missing)
        assert f"failed to dispatch workflow 'e2e-missing.yml' for repo '{repo}'" in missing_text, missing_text[-2000:]
        assert "dispatched for repo" not in missing_text, missing_text[-2000:]
        unknown_repo = live_config.name("no-such-repo")
        unknown = dispatch(cli, unknown_repo, WORKFLOW_FILE)
        assert unknown.exit_code != 0, f"dispatch to a missing repository exited 0:\n{unknown.output[-2000:]}"
        assert f"{target.org}/{unknown_repo}" in cli_lines(unknown), unknown.output[-2000:]
    finally:
        for run in runs:  # a no-op job: cancelling only saves runner time (409 when it already completed)
            try:
                mutator.cancel_workflow_run(repo, int(run["id"]))
            except GitHubError as exc:
                logger.info("cancelling run %s of %s failed: %s", run.get("id"), repo, exc)


@pytest.mark.scenario("cli.kb.dispatch-workflow-exit-code", priority="P2")
@pytest.mark.known_bug("KB-045")
@pytest.mark.tags("workflows", "known-bug")
def test_failed_dispatch_exits_non_zero(
    baseline: BaselineManager,
    target: Target,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """A dispatch GitHub refuses (no such workflow in the session's config repository: a 404, nothing changes) is a
    failure: 'failed to dispatch workflow' and a non-zero exit (KB-045: exit 0)."""
    repo = target.config_repo_for(run_ctx)
    result = dispatch(make_cli(fresh_workspace), repo, "e2e-missing.yml")
    text = cli_lines(result)
    assert f"failed to dispatch workflow 'e2e-missing.yml' for repo '{repo}'" in text, text[-2000:]
    assert result.exit_code != 0, f"a refused dispatch exited {result.exit_code}"


# --- delete-file -------------------------------------------------------------------------------------------------------
def delete_file(cli: OtterdogCli, repo: str, path: str, *message: str) -> CliResult:
    """``delete-file -r <repo> --path <path> [-m <message>]``."""
    return cli.run("delete-file", "-r", repo, "--path", path, *(["-m", message[0]] if message else []))


def deleting_line(target: Target, repo: str, path: str) -> str:
    """The line otterdog prints for a configured repository (before the outcome)."""
    return f"Deleting file '{path}' in repository '{target.org}/{repo}':"


@pytest.mark.scenario("cli.delete-file", priority="P2")
@pytest.mark.timeout(1200)
def test_delete_file_removes_a_configured_file(
    live_config: LiveConfig,
    mutator: Mutator,
    oracle: Oracle,
    target: Target,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``delete-file`` removes a file of a configured repository with ``-m`` as commit message, then another one with
    the default message; a file that does not exist creates no commit; an unconfigured repository is left alone."""
    repo = live_config.name("delete-file")
    text = repo_config(live_config, f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: delete-file' }}")
    live_config.apply(text, what="apply the repository")
    assert live_config.wait_repo(repo) is not None, f"{repo} was not created"
    files = {
        "E2E.md": "otterdog e2e: deleted with -m\n",
        "E2E-2.md": "otterdog e2e: deleted with the default message\n",
    }
    mutator.commit_files(repo, "main", dict(files), f"otterdog-e2e {live_config.run_ctx.run_id}: files to delete")
    for path, content in files.items():
        assert live_config.wait_file(repo, path, content) == content, f"{repo}:{path} was not committed"
    cli = live_config.cli
    before = head_commit(oracle, repo)
    message = f"otterdog-e2e {live_config.run_ctx.run_id}: delete E2E.md"
    deleted = delete_file(cli, repo, "E2E.md", message).assert_ok("delete-file -m")
    output = cli_lines(deleted)
    assert "Deleting file 'E2E.md' in organization repository" in output, output[-2000:]
    assert f"{deleting_line(target, repo, 'E2E.md')} succeeded" in output, output[-2000:]
    assert live_config.wait_file(repo, "E2E.md", None) is None, "E2E.md still exists"
    after = wait_head_change(oracle, repo, before["sha"])
    assert after["message"] == message, after
    default = delete_file(cli, repo, "E2E-2.md").assert_ok("delete-file")
    assert f"{deleting_line(target, repo, 'E2E-2.md')} succeeded" in cli_lines(default), default.output[-2000:]
    assert live_config.wait_file(repo, "E2E-2.md", None) is None, "E2E-2.md still exists"
    latest = wait_head_change(oracle, repo, after["sha"])
    assert latest["message"] == "Deleting file 'E2E-2.md' with otterdog.", latest
    delete_file(cli, repo, "E2E.md").assert_ok("delete-file of a missing file")
    assert head_commit(oracle, repo)["sha"] == latest["sha"], "deleting a missing file created a commit"
    unconfigured = live_config.name("delete-file-unconfigured")
    live_config.touch()
    mutator.create_repo(unconfigured, description="otterdog e2e: not in the configuration", auto_init=True)
    readme = waiting.poll(
        lambda: oracle.file_content(unconfigured, "README.md"),
        until=lambda content: content is not None,
        timeout=60.0,
        interval=3.0,
        what=f"{unconfigured}:README.md",
        raise_on_timeout=False,
    )
    assert readme is not None, f"{unconfigured} has no README.md"
    ignored = delete_file(cli, unconfigured, "README.md").assert_ok("delete-file of an unconfigured repository")
    assert f"in repository '{target.org}/{unconfigured}'" not in cli_lines(ignored), ignored.output[-2000:]
    assert oracle.file_content(unconfigured, "README.md") == readme, "a repository outside the configuration changed"


@pytest.mark.scenario("cli.kb.delete-file-missing", priority="P2")
@pytest.mark.known_bug("KB-044")
@pytest.mark.tags("known-bug")
def test_delete_file_reports_a_missing_file(
    baseline: BaselineManager,
    target: Target,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """Deleting a file that does not exist (in the session's config repository, declared by the baseline) must not be
    reported 'succeeded' (KB-044: otterdog prints 'succeeded', in red, for a file it did not find)."""
    fresh_workspace.write_org_config(baseline.text())
    repo, path = target.config_repo_for(run_ctx), f"{run_ctx.name('missing')}.md"
    result = delete_file(make_cli(fresh_workspace), repo, path).assert_ok("delete-file of a missing file")
    text = cli_lines(result)
    assert deleting_line(target, repo, path) in text, text[-2000:]
    assert f"{deleting_line(target, repo, path)} succeeded" not in text, "a missing file was reported 'succeeded'"


@pytest.mark.scenario("cli.kb.delete-file-refused", priority="P2")
@pytest.mark.known_bug("KB-043")
@pytest.mark.tags("bpr", "known-bug")
@pytest.mark.timeout(1500)
def test_delete_file_reports_a_refused_deletion(
    live_config: LiveConfig,
    mutator: Mutator,
    oracle: Oracle,
    target: Target,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """A deletion GitHub refuses (the default branch requires pull requests, admins included) prints 'failure deleting
    file' and exits 1, the file stays (KB-043: the refused DELETE leaves ``deleted_file`` unbound, the command
    crashes with an UnboundLocalError and exits 2)."""
    repo = live_config.name("delete-refused")
    plain = f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: refused delete-file' }}"
    live_config.apply(repo_config(live_config, plain), what="apply the repository")
    assert live_config.wait_repo(repo) is not None, f"{repo} was not created"
    content = "otterdog e2e: a protected file\n"
    mutator.commit_files(repo, "main", {"E2E.md": content}, f"otterdog-e2e {live_config.run_ctx.run_id}: file")
    assert live_config.wait_file(repo, "E2E.md", content) == content, "E2E.md was not committed"
    protected = (
        f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: refused delete-file', branch_protection_rules: ["
        "orgs.newBranchProtectionRule('main') { is_admin_enforced: true, required_approving_review_count: 1 }] }"
    )
    live_config.apply(repo_config(live_config, protected), what="apply the branch protection")
    rule = waiting.poll(
        lambda: oracle.branch_protection_rule(repo, "main"),
        until=lambda found: bool(found) and found.get("isAdminEnforced") is True,
        timeout=60.0,
        interval=3.0,
        what=f"the admin-enforced protection of {repo}@main",
        raise_on_timeout=False,
    )
    assert rule and rule.get("isAdminEnforced") is True, f"main of {repo} is not protected: {rule}"
    result = delete_file(live_config.cli, repo, "E2E.md", "otterdog-e2e: refused delete")
    text = cli_lines(result)
    assert oracle.file_content(repo, "E2E.md") == content, "the protected file was deleted"
    assert not UNBOUND_RE.search(text), f"delete-file crashed:\n{text[-2000:]}"
    assert "failure deleting file" in text, text[-2000:]
    assert result.exit_code == 1, f"exit {result.exit_code}"


# --- sync-template -----------------------------------------------------------------------------------------------------
@pytest.mark.scenario("cli.sync-template", priority="P2")
@pytest.mark.tags("template")
@pytest.mark.timeout(1800)
def test_sync_template_recopies_the_template(
    live_config: LiveConfig,
    mutator: Mutator,
    oracle: Oracle,
    target: Target,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """A repository created from a run template repository renders README.md (post_process_template_content); after
    the template changes, ``sync-template`` copies every changed file (README.md rendered again, TEMPLATE.txt
    verbatim, the new NEW.txt) and prints one 'updated file' line each; a second run updates nothing; the template
    itself (no template_repository) is skipped."""
    template, repo = live_config.name("tpl-source"), live_config.name("tpl-copy")
    run_id = live_config.run_ctx.run_id
    template_repo = (
        f"orgs.newRepo('{template}') {{ description: 'otterdog e2e: template repository', is_template: true }}"
    )
    live_config.apply(repo_config(live_config, template_repo), what="apply the template repository")
    assert live_config.wait_repo(template) is not None, f"{template} was not created"
    first = {"README.md": "# {{org}}/{{repo}} template v1\n", "TEMPLATE.txt": "static {{org}} v1\n"}
    mutator.commit_files(template, "main", dict(first), f"otterdog-e2e {run_id}: template v1")
    for path, content in first.items():
        assert live_config.wait_file(template, path, content) == content, f"{template}:{path} was not committed"
    copy_repo = (
        f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: created from a template', "
        f"template_repository: '{target.org}/{template}', post_process_template_content: ['README.md'] }}"
    )
    config = repo_config(live_config, template_repo, copy_repo)
    live_config.apply(config, what="apply the repository created from the template")
    assert live_config.wait_repo(repo) is not None, f"{repo} was not created"
    rendered = f"# {target.org}/{repo} template v1\n"
    assert live_config.wait_file(repo, "README.md", rendered) == rendered, "README.md was not rendered at creation"
    second = {
        "README.md": "# {{org}}/{{repo}} template v2\n",
        "TEMPLATE.txt": "static {{org}} v2\n",
        "NEW.txt": "otterdog e2e: added to the template\n",
    }
    mutator.commit_files(template, "main", dict(second), f"otterdog-e2e {run_id}: template v2")
    for path, content in second.items():
        assert live_config.wait_file(template, path, content) == content, f"{template}:{path} was not committed"
    cli = live_config.cli
    synced = cli.run("sync-template", "-r", repo).assert_ok("sync-template")
    text = cli_lines(synced)
    assert f'Syncing repository["{repo}"]' in text, text[-2000:]
    updated = set(re.findall(r"updated file '([^']+)'", text))
    assert updated == set(second), f"updated files {sorted(updated)}, expected {sorted(second)}"
    expected = {
        "README.md": f"# {target.org}/{repo} template v2\n",
        "TEMPLATE.txt": second["TEMPLATE.txt"],
        "NEW.txt": second["NEW.txt"],
    }
    for path, content in expected.items():
        assert live_config.wait_file(repo, path, content) == content, f"{repo}:{path} not synced"
    again = cli_lines(cli.run("sync-template", "-r", repo).assert_ok("sync-template (second run)"))
    assert f'Syncing repository["{repo}"]' in again, again[-2000:]
    assert "updated file" not in again, f"the second sync updated files:\n{again[-2000:]}"
    skipped = cli_lines(cli.run("sync-template", "-r", template).assert_ok("sync-template of the template"))
    assert "Syncing repository[" not in skipped, f"a repository without template_repository was synced:\n{skipped}"
