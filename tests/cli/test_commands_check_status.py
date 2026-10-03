"""``check-status -n [-r <filter>] -j <file>``: the validity and sync status of a configuration against the live org.

check-status prints ``Archived: <b>``, ``Validation status: <b>`` and ``Synchronization status: <b>`` and writes a JSON
list ``[{org_id, is_archived, validation_status: {is_valid, infos, warnings, errors}, sync_status: {in_sync,
additions, changes, deletions}}]`` (otterdog/operations/check_status.py): ``is_valid`` means no warning and no error
(infos do not count), ``in_sync`` additionally no patch at all (read-only ones included), ``changes`` counts the
changed keys that are not read-only, like ``plan``. With validation errors the live org is not compared.

cli.check-status: two run repositories (one with a plain secret value: a warning) are applied, then the same live
    state is checked against configurations that warn, change one or both repositories (``-r`` limits the
    repositories compared), add one, delete both, or only differ by the read-only plan; and an invalid configuration.
cli.kb.check-status-exit-code (known bug KB-011): an invalid configuration must not exit 0.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.workspace import read_untrusted_text

if TYPE_CHECKING:
    from conftest import LiveConfig
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.safety import VerifiedOrg

pytestmark = [pytest.mark.tags("cli", "repo", "org-settings")]

STATUS_FILE = "check-status.json"
OTHER_PLAN = {"free": "team", "team": "free", "enterprise": "team"}  # a configured plan that differs from the live one


def check_status(cli: OtterdogCli, repo_filter: str) -> tuple[CliResult, dict[str, Any]]:
    """``check-status -n -r <filter> -j check-status.json`` and the JSON entry of the org (AssertionError when the
    command wrote none)."""
    result = cli.run("check-status", "-n", "-r", repo_filter, "-j", STATUS_FILE)
    # the SUT (maybe an untrusted container) wrote it: never follow a link it planted (ISO-01)
    text = read_untrusted_text(result.cwd / STATUS_FILE, within=result.cwd)
    assert text is not None, f"check-status wrote no {STATUS_FILE} (exit {result.exit_code}):\n{result.output[-3000:]}"
    entries = json.loads(text)
    org = cli.workspace.org.lower()
    entry = next((item for item in entries if str(item.get("org_id", "")).lower() == org), None)
    assert entry is not None, f"no entry for {cli.workspace.org} in {entries}"
    return result, entry


def status_lines(text: str, *, valid: bool, in_sync: bool) -> list[str]:
    """The three status lines check-status prints that are missing from ``text``."""
    expected = ["Archived: False", f"Validation status: {valid}", f"Synchronization status: {in_sync}"]
    return [line for line in expected if line not in text]


def sync(entry: dict[str, Any]) -> tuple[bool, int, int, int]:
    """(in_sync, additions, changes, deletions) of an entry."""
    status = entry["sync_status"]
    return status["in_sync"], status["additions"], status["changes"], status["deletions"]


@pytest.mark.scenario("cli.check-status", priority="P0")
@pytest.mark.timeout(1500)
def test_check_status_reports_validity_and_sync(
    live_config: LiveConfig,
    oracle: Oracle,
    verified_org: VerifiedOrg,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """After the apply, check-status of the same configuration is valid-but-warning and out of sync with no change;
    pending description changes count per filtered repository (as plan counts them); a new repository is one addition,
    missing ones are deletions; a configured plan that differs from the live one is out of sync with zero counts."""
    run_ctx, cli = live_config.run_ctx, live_config.cli
    repo_a, repo_b, repo_c = live_config.name("cs-a"), live_config.name("cs-b"), live_config.name("cs-c")
    secret = live_config.const("cs")

    def repo(name: str, description: str, *, with_secret: bool = False) -> str:
        """A run repository expression (the secret holds a plain dummy value: a validation warning)."""
        secrets = f", secrets: [orgs.newRepoSecret('{secret}') {{ value: 'e2e-dummy-{run_ctx.run_id}' }}]"
        return f"orgs.newRepo('{name}') {{ description: '{description}'{secrets if with_secret else ''} }}"

    applied = live_config.render(repo(repo_a, "a", with_secret=True), repo(repo_b, "a"))
    live_config.apply(applied, what="apply the check-status repositories")
    ready = waiting.poll(
        lambda: oracle.repo(repo_b) is not None and oracle.repo_secret(repo_a, secret) is not None,
        until=bool,
        timeout=90.0,
        interval=3.0,
        what="the check-status repositories",
        raise_on_timeout=False,
    )
    assert ready, f"{repo_a} (with its secret) or {repo_b} is missing after the apply"
    run_filter, nothing = run_ctx.repo_filter(), live_config.name("cs-none-*")

    # the baseline alone, no run repository compared: valid and in sync
    live_config.write(live_config.render())
    result, entry = check_status(cli, nothing)
    assert entry["validation_status"]["is_valid"] is True, entry
    assert sync(entry) == (True, 0, 0, 0), f"the baseline is not in sync: {entry}"
    assert entry["is_archived"] is False and result.exit_code == 0, (entry, result.exit_code)
    assert not status_lines(cli_lines(result), valid=True, in_sync=True), cli_lines(result)[-2000:]
    infos = entry["validation_status"]["infos"]

    # the applied configuration: one warning (the plain secret value), nothing to change, yet not in sync
    live_config.write(applied)
    result, entry = check_status(cli, run_filter)
    assert entry["validation_status"] == {"is_valid": False, "infos": infos, "warnings": 1, "errors": 0}, entry
    assert sync(entry) == (False, 0, 0, 0), entry
    assert not status_lines(cli_lines(result), valid=False, in_sync=False), cli_lines(result)[-2000:]

    # both descriptions changed: -r on one repository counts its change only, -r on the run counts both (= plan)
    changed = live_config.render(repo(repo_a, "b", with_secret=True), repo(repo_b, "b"))
    live_config.write(changed)
    for repo_filter, expected in ((repo_b, 1), (run_filter, 2)):
        _, entry = check_status(cli, repo_filter)
        assert sync(entry) == (False, 0, expected, 0), (repo_filter, entry)
        plan = cli.plan(repo_filter=repo_filter).plan()
        assert (plan.add, plan.change, plan.delete) == (0, expected, 0), (repo_filter, plan.raw[-2000:])

    # a new repository is one addition, the run's repositories missing from the configuration are deletions
    live_config.write(live_config.render(repo(repo_a, "a", with_secret=True), repo(repo_b, "a"), repo(repo_c, "c")))
    _, entry = check_status(cli, run_filter)
    assert sync(entry) == (False, 1, 0, 0), entry
    live_config.write(live_config.render())
    _, entry = check_status(cli, run_filter)
    assert sync(entry) == (False, 0, 0, 2), entry
    assert entry["validation_status"]["is_valid"] is True, entry

    # a configured plan that differs from the live one: a read-only change, nothing counted, not in sync
    other = OTHER_PLAN[verified_org.plan]
    live_config.write(live_config.render(plan=other))
    result, entry = check_status(cli, nothing)
    status = entry["validation_status"]
    assert status["errors"] == 0 and status["is_valid"] is (status["warnings"] == 0), entry
    assert sync(entry) == (False, 0, 0, 0), f"plan {other} on a {verified_org.plan} org: {entry}"
    planned = cli.plan(repo_filter=nothing).plan()
    assert planned.is_noop() and any(obj.read_only_keys == ["plan"] for obj in planned.objects), planned.raw[-2000:]


def invalid_config(baseline: BaselineManager, name: str) -> str:
    """The baseline plus a run repository with an invalid topic (a validation error; never applied)."""
    snippet = f'orgs.newRepo(\'{name}\') {{ description: "otterdog e2e: invalid", topics: ["Invalid_Topic"] }}'
    return baseline.renderer.render(ConfigFragments(repositories=[snippet]))


@pytest.mark.scenario("cli.check-status", priority="P0")
def test_check_status_of_an_invalid_configuration(
    baseline: BaselineManager,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """A validation error: is_valid false with the error counted, nothing compared (zero counts), not in sync."""
    cli = make_cli(fresh_workspace)
    fresh_workspace.write_org_config(invalid_config(baseline, baseline.run_ctx.name("cs-invalid")))
    result, entry = check_status(cli, baseline.run_ctx.repo_filter())
    status = entry["validation_status"]
    assert status["is_valid"] is False and status["errors"] >= 1, entry
    assert sync(entry) == (False, 0, 0, 0), entry
    assert not status_lines(cli_lines(result), valid=False, in_sync=False), cli_lines(result)[-2000:]


@pytest.mark.scenario("cli.kb.check-status-exit-code", priority="P2")
@pytest.mark.known_bug("KB-011")
@pytest.mark.tags("known-bug")
def test_check_status_fails_for_an_invalid_configuration(
    baseline: BaselineManager,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
) -> None:
    """check-status of an invalid configuration exits non-zero (KB-011: it always exits 0)."""
    cli = make_cli(fresh_workspace)
    fresh_workspace.write_org_config(invalid_config(baseline, baseline.run_ctx.name("cs-invalid-exit")))
    result, entry = check_status(cli, baseline.run_ctx.repo_filter())
    assert entry["validation_status"]["is_valid"] is False, entry
    assert result.exit_code != 0, f"check-status of an invalid configuration exited {result.exit_code}"
