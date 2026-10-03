"""Error handling of the live CLI: missing web credentials, missing configuration, failing patches.

cli.plan.missing-web-credentials: the commands that read web-only settings unless ``-n`` is given (plan, apply,
    check-status, import, show-live, local-apply) resolve the FULL credentials first (username, password, TOTP seed;
    credentials/env_provider.py ``get_credentials(only_token=False)``) and stop with 'invalid credentials' and
    "environment variable '<VAR>' for key 'username' not found", exit 1, before any web access: the workspace's
    otterdog.json names variables that are never set, so no login can ever be attempted.
cli.cmd.missing-config: commands that need the local org configuration (validate, local-plan, plan, apply,
    check-status, list-members, delete-file, sync-template, push-config, open-pr) report its absence ('configuration
    file ... does not (yet) exist, run fetch-config or import first') and exit 1.
cli.cmd.apply-failed-patches: a patch GitHub refuses (repository team permissions of a team that does not exist: the
    repository is created, ``PUT /orgs/{org}/teams/<team>/repos/...`` answers 404) prints 'failed to apply patch: ADD -
    repository[name="..."]' with the GitHub error, the other patches are applied, and the exit code is the number of
    failed patches (otterdog/operations/apply.py handle_finish); the next plan still shows the permissions pending.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.otterdog.workspace import CREDENTIAL_ENV, WorkspaceLayout

if TYPE_CHECKING:
    from conftest import LiveConfig
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import Target

pytestmark = [pytest.mark.tags("cli")]

# variables never set for an otterdog process: procs.sanitized_env drops every inherited E2E_* name and the runner
# only passes the CREDENTIAL_ENV ones
UNSET_WEB_VARIABLES = {
    "username": "E2E_OTTERDOG_NO_WEB_USERNAME",
    "password": "E2E_OTTERDOG_NO_WEB_PASSWORD",
    "twofa_seed": "E2E_OTTERDOG_NO_WEB_TOTP_SEED",
}
# (command, arguments without -n)
WEB_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("plan",),
    ("apply", "-f"),
    ("check-status",),
    ("import", "-f"),
    ("show-live",),
    ("local-apply", "-f"),
)
DIFF_MISSING = "does not yet exist, run fetch-config or import first."  # operations/diff_operation.py
FILE_MISSING = "does not exist, run 'fetch-config' or 'import' first."  # operations/__init__.py
# (command and arguments, expected message); "{name}" is a run-prefixed name that never exists
CONFIG_COMMANDS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("validate",), FILE_MISSING),
    (("local-plan",), DIFF_MISSING),
    (("plan", "-n"), DIFF_MISSING),
    (("apply", "-f", "-n"), DIFF_MISSING),
    (("check-status", "-n"), DIFF_MISSING),
    (("list-members",), FILE_MISSING),
    (("delete-file", "-r", "{name}", "--path", "E2E.md"), FILE_MISSING),
    (("sync-template", "-r", "{name}"), FILE_MISSING),
    (("push-config", "-f", "-m", "otterdog-e2e"), FILE_MISSING),
    (("open-pr", "-b", "{name}", "-t", "otterdog-e2e", "-a", "{name}"), FILE_MISSING),
)


def token_only_layout(workspace: ConfigWorkspace) -> WorkspaceLayout:
    """The workspace's otterdog.json with the web-login variables of its organization renamed to UNSET_WEB_VARIABLES
    (the token variable is kept: token-only commands still work)."""
    document = copy.deepcopy(workspace.otterdog_json())
    credentials = document["organizations"][0]["credentials"]
    assert credentials["api_token"] == CREDENTIAL_ENV["api_token"], credentials
    credentials.update(UNSET_WEB_VARIABLES)
    return WorkspaceLayout(document=document)


@pytest.mark.scenario("cli.plan.missing-web-credentials", priority="P2")
@pytest.mark.parametrize("command", WEB_COMMANDS, ids=lambda command: command[0])
def test_web_commands_need_the_web_credentials(
    command: tuple[str, ...],
    baseline: BaselineManager,
    target: Target,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """Without ``-n`` and without web credentials the command stops at 'invalid credentials' (exit 1) naming the
    missing username variable; import writes no file."""
    fresh_workspace.use_layout(token_only_layout(fresh_workspace))
    if command[0] != "import":
        fresh_workspace.write_org_config(baseline.text())
    if command[0] == "local-apply":
        fresh_workspace.write_base_config(baseline.text())
    result = make_cli(fresh_workspace).run(*command)
    text = cli_lines(result)
    assert "Error: invalid credentials" in text, f"{command[0]}: no credential error:\n{text[-2000:]}"
    expected = f"environment variable '{UNSET_WEB_VARIABLES['username']}' for key 'username' not found"
    assert expected in text, f"{command[0]}:\n{text[-2000:]}"
    assert result.exit_code == 1, f"{command[0]}: exit {result.exit_code}"
    assert "Plan:" not in text and "Executed plan:" not in text, f"{command[0]} went on:\n{text[-2000:]}"
    if command[0] == "import":
        assert not fresh_workspace.org_config_file_for(target.org).exists(), "import wrote a configuration"


@pytest.mark.scenario("cli.cmd.missing-config", priority="P2")
@pytest.mark.parametrize(("command", "message"), CONFIG_COMMANDS, ids=[command[0] for command, _ in CONFIG_COMMANDS])
def test_commands_need_the_org_config(
    command: tuple[str, ...],
    message: str,
    target: Target,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """Without ``orgs/<org>/<org>.jsonnet`` the command names the missing file and exits 1."""
    config_file = fresh_workspace.org_config_file_for(target.org)
    assert not config_file.exists(), config_file
    name = run_ctx.name("missing")
    result = make_cli(fresh_workspace).run(*(arg.format(name=name) for arg in command))
    text = cli_lines(result)
    assert "configuration file '" in text and config_file.name in text and message in text, text[-2000:]
    assert result.exit_code == 1, f"{command[0]}: exit {result.exit_code}"


@pytest.mark.scenario("cli.cmd.apply-failed-patches", priority="P1")
@pytest.mark.tags("repo", "teams")
@pytest.mark.timeout(1500)
def test_failed_patches_set_the_exit_code(
    live_config: LiveConfig,
    oracle: Oracle,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """Two repositories granting a team that does not exist: exactly two 'failed to apply patch' errors and a non-zero
    exit, a third repository is created normally, the failing repositories exist without any team access, the next
    plan shows the permissions still pending. The exit status is only required to be non-zero: otterdog exits with the
    number of failed patches (apply.py), the count-as-exit-status design KB-034 calls a bug for validate and plan, so a
    fix clamping it to 1 must not look like a regression (BAT-04)."""
    ok_repo, failing = live_config.name("fp-ok"), (live_config.name("fp-a"), live_config.name("fp-b"))
    missing_team = live_config.name("no-such-team")
    assert oracle.team(missing_team) is None, f"team {missing_team} exists"
    snippets = [f"orgs.newRepo('{ok_repo}') {{ description: 'otterdog e2e: applied' }}"] + [
        f"orgs.newRepo('{name}') {{ description: 'otterdog e2e: failing patch', "
        f"team_permissions: {{ '{missing_team}': 'pull' }} }}"
        for name in failing
    ]
    text = live_config.render(*snippets)
    live_config.write(text)
    live_config.touch()
    result = live_config.cli.apply(repo_filter=live_config.run_ctx.repo_filter())
    output = cli_lines(result)
    assert not result.timed_out and result.infra_error is None, output[-3000:]
    failed = result.apply().failed_patches
    expected = {f'ADD - repository[name="{name}"]' for name in failing}
    assert set(failed) == expected, f"failed patches {failed}, expected {sorted(expected)}:\n{output[-3000:]}"
    for name in failing:
        assert f"failed to update team permission for team {missing_team} on repo {name}" in output, output[-3000:]
    assert result.exit_code != 0, f"exit {result.exit_code} with {len(failed)} failed patch(es)"
    for name in (ok_repo, *failing):
        assert live_config.wait_repo(name) is not None, f"{name} was not created"
    for name in failing:  # no team got access instead of the missing one
        granted = [team.get("slug") for team in oracle.repo_teams(name)]
        assert not granted, f"{name} grants {granted} although its only team permission failed"
    planned = live_config.cli.plan(repo_filter=live_config.run_ctx.repo_filter()).plan()
    pending = {
        obj.value for obj in planned.objects if obj.kind == "repository" and "team_permissions" in obj.changed_keys
    }
    assert pending == set(failing), f"pending team permissions {sorted(pending)}:\n{planned.raw[-3000:]}"
