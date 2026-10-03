"""Known otterdog bugs exercised by Python checks of the live CLI tier (scenarios/known_bugs.yaml).

Each test asserts the CORRECT behaviour and carries ``known_bug(<id>)``: the plugin turns it into a non-strict xfail,
so the test reports XFAIL while the bug exists and XPASS once it is fixed (then update known_bugs.yaml). YAML
scenarios linked to known bugs live in scenarios/cli/kb-*.yaml.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.otterdog.render import ConfigFragments

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace

ABORTED_TEXT = "Planning aborted due to validation errors."  # operations/plan.py:123


@pytest.mark.scenario("cli.kb.apply-exit-code")
@pytest.mark.known_bug("KB-001")
@pytest.mark.tags("cli", "repo", "known-bug")
def test_apply_fails_on_validation_errors(
    e2e: E2EContext,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
) -> None:
    """``apply -f -n`` of a configuration with a validation error must exit non-zero (KB-001: it exits 0).

    The configuration is the baseline plus a run repository with an invalid topic (an ERROR on every plan), so
    validation aborts the apply before anything is changed; the repository must not exist afterwards.
    """
    repo = run_ctx.name("kb-apply-exit")
    snippet = f'orgs.newRepo(\'{repo}\') {{ description: "otterdog e2e: KB-001", topics: ["Invalid_Topic"] }}'
    fresh_workspace.write_org_config(renderer.render(ConfigFragments(repositories=[snippet])))
    result = make_cli(fresh_workspace).apply(repo_filter=run_ctx.repo_filter())
    try:
        assert not result.timed_out and result.infra_error is None, result.output[-2000:]
        assert ABORTED_TEXT in result.output, f"validation did not abort the apply:\n{result.output[-2000:]}"
        assert result.exit_code != 0, f"apply exited {result.exit_code} although validation failed (KB-001)"
    finally:
        if oracle.repo(repo) is not None:  # validation unexpectedly passed: remove what the apply created
            e2e.remove_run_objects(baseline, baseline.reset_cli)
