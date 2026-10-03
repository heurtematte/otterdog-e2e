"""C-PUSH-FETCH (SPEC 19, P0) and C-OPEN-PR (P1): the CLI's config-repo commands on the session config repository.

The org config repository of the session is target.config_repo_for(run_ctx) (``e2e-<run>-config`` with
org_config_repo auto; declared in the baseline, so the reset created it). otterdog stores the definition at
``otterdog/<org>.jsonnet`` on its default branch (operations/push_config.py, fetch_config.py).

- push-fetch: push-config a variant of the baseline (an extra jsonnet comment, so the content really changes), read
  it back through the oracle (contents API), fetch-config it into a second, empty workspace, then push the baseline
  back (always) so the repository holds the baseline for later tiers.
- open-pr: with the baseline on the default branch, open-pr a variant from branch ``e2e-<run>-open-pr``; otterdog
  creates ``otterdog/e2e-<run>-open-pr`` (operations/open_pull_request.py) and a pull request that must exist with
  that head and the variant as content. The pull request is closed and the branch deleted afterwards (the janitor
  sweeps both too: they carry this run's id).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli")]

PUSHED_TEXT = "organization definition pushed to repo"  # operations/push_config.py
NOTHING_PUSHED_TEXT = "no changes, nothing pushed"
FETCHED_TEXT = "organization definition fetched from default branch"  # operations/fetch_config.py
CREATED_PR_RE = re.compile(r"created pull request #(\d+)")  # operations/open_pull_request.py
CONTENT_TIMEOUT = 60.0


def definition_path(target: Target) -> str:
    """Path of the org definition in the config repository."""
    return f"otterdog/{target.org}.jsonnet"


def variant(text: str, run_ctx: RunContext, purpose: str) -> str:
    """The baseline with one trailing jsonnet comment (a real content change, no model change)."""
    return text.rstrip("\n") + f"\n// otterdog-e2e {purpose} of run {run_ctx.run_id}\n"


def push(cli: OtterdogCli, workspace: ConfigWorkspace, text: str, message: str) -> CliResult:
    """Write ``text`` as the org config and push-config it (``-f``: no prompt; the diff/validation path is kept)."""
    workspace.write_org_config(text)
    return cli.push_config(message=message).assert_ok("push-config")


def wait_content(oracle: Oracle, repo: str, path: str, expected: str, *, ref: str | None = None) -> str | None:
    """The file content once it equals ``expected`` (contents API reads can lag a commit by a few seconds)."""
    return waiting.poll(
        lambda: oracle.file_content(repo, path, ref=ref),
        until=lambda content: content == expected,
        timeout=CONTENT_TIMEOUT,
        interval=3.0,
        what=f"{repo}:{path}{'@' + ref if ref else ''} equal to the pushed configuration",
        raise_on_timeout=False,
    )


@pytest.mark.scenario("cli.push-fetch")
def test_push_fetch_round_trip(
    e2e: E2EContext,
    baseline: BaselineManager,
    oracle: Oracle,
    target: Target,
    run_ctx: RunContext,
    template_ref: TemplateRef,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
) -> None:
    """push-config -> contents API -> fetch-config into an empty workspace gives back the pushed text."""
    repo, path = target.config_repo_for(run_ctx), definition_path(target)
    cli = make_cli(fresh_workspace)
    text = variant(baseline.text(), run_ctx, "push-fetch round trip")
    failed = False
    try:
        pushed = push(cli, fresh_workspace, text, f"otterdog-e2e {run_ctx.run_id}: push-fetch round trip")
        assert PUSHED_TEXT in pushed.output, pushed.output[-2000:]
        remote = wait_content(oracle, repo, path, text)
        assert remote == text, f"{repo}:{path} does not hold the pushed configuration ({len(remote or '')} chars)"
        fetch_workspace = e2e.workspace(e2e.unique_name("push-fetch-target"), template_ref)
        fetched = make_cli(fetch_workspace).fetch_config().assert_ok("fetch-config")
        assert FETCHED_TEXT in fetched.output, fetched.output[-2000:]
        assert fetch_workspace.read_org_config() == text, "fetch-config did not write the pushed configuration"
    except BaseException:
        failed = True
        raise
    finally:
        restore_baseline(cli, fresh_workspace, baseline, run_ctx, failed=failed)


def restore_baseline(
    cli: OtterdogCli, workspace: ConfigWorkspace, baseline: BaselineManager, run_ctx: RunContext, *, failed: bool
) -> None:
    """Push the baseline back to the config repository; a failure only fails the test when nothing failed before."""
    try:
        restored = push(cli, workspace, baseline.text(), f"otterdog-e2e {run_ctx.run_id}: restore the baseline")
        assert PUSHED_TEXT in restored.output or NOTHING_PUSHED_TEXT in restored.output, restored.output[-2000:]
    except AssertionError:
        if not failed:
            raise


@pytest.mark.scenario("cli.open-pr")
def test_open_pr(
    baseline: BaselineManager,
    oracle: Oracle,
    mutator: Mutator,
    target: Target,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
) -> None:
    """open-pr opens a pull request from otterdog/e2e-<run>-open-pr carrying the local configuration."""
    repo, path = target.config_repo_for(run_ctx), definition_path(target)
    cli = make_cli(fresh_workspace)
    push(cli, fresh_workspace, baseline.text(), f"otterdog-e2e {run_ctx.run_id}: baseline before open-pr")
    branch = run_ctx.name("open-pr")
    head_ref = f"otterdog/{branch}"
    text = variant(baseline.text(), run_ctx, "open-pr")
    fresh_workspace.write_org_config(text)
    author = target.identities["admin"].login
    assert author, "the target declares no admin login"
    number: int | None = None
    try:
        result = cli.open_pr(branch=branch, title=f"otterdog-e2e {run_ctx.run_id}: open-pr", author=author)
        result.assert_ok("open-pr")
        match = CREATED_PR_RE.search(result.output)
        assert match, f"open-pr printed no pull request number:\n{result.output[-2000:]}"
        number = int(match.group(1))
        pull: dict[str, Any] | None = oracle.pull(repo, number)
        assert pull is not None, f"pull request #{number} not found in {repo}"
        head, base = pull.get("head") or {}, pull.get("base") or {}
        assert pull.get("state") == "open", f"pull request #{number} is {pull.get('state')!r}"
        assert head.get("ref") == head_ref, f"pull request #{number} head is {head.get('ref')!r}, not {head_ref!r}"
        expected_base = oracle.default_branch(repo) or "main"
        assert base.get("ref") == expected_base, f"pull request #{number} base is {base.get('ref')!r}"
        assert wait_content(oracle, repo, path, text, ref=head_ref) == text, f"{head_ref} lacks the local config"
    finally:
        if number is not None:
            mutator.close_pull(repo, number)
        mutator.delete_ref(repo, f"heads/{head_ref}")
