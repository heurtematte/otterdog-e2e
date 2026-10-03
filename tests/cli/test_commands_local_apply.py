"""``local-apply [-s SUFFIX] [-f] -n [-d] -r <filter>``: applies the diff BETWEEN TWO LOCAL configurations to GitHub.

This is what the webapp's ApplyChangesTask runs after a merge (otterdog/operations/local_apply.py): the ``-BASE`` file
plays the live org and the org configuration the expected one, the live org is never read. Steps on one run
repository, every removal checked by the config guard first (``BaselineManager.guard_config_change``, a trusted
local-plan of the same two files):

cli.local-apply:
  1. BASE = baseline, config = baseline + repository: without ``-f`` the prompt is refused ('Apply cancelled.', exit 0,
     nothing created); with ``-f`` 'Executed plan: 1 added, 0 changed, 0 live resources ignored.' and the repository
     exists;
  2. a live drift (the description changed with the mutator) and BASE = config: 'No changes required.', the drift
     stays (local-apply compares the two files, not GitHub);
  3. BASE = the repository, config = baseline: without ``-d`` nothing is deleted ('1 resource(s) would be deleted with
     flag '--delete-resources'.'); with ``-d`` 'Executed plan: 0 added, 0 changed, 1 deleted.' and the repository is
     gone.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e import waiting

if TYPE_CHECKING:
    from conftest import LiveConfig
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.otterdog.runner import CliResult

pytestmark = [pytest.mark.tags("cli", "repo")]

HEADER = "Applying local changes:"
PROMPT = "Do you want to perform these actions? (Only 'yes' or 'y' will be accepted to approve)"
DRIFT = "otterdog e2e: live drift"


@pytest.mark.scenario("cli.local-apply", priority="P1")
@pytest.mark.timeout(1500)
def test_local_apply_applies_the_local_diff(
    live_config: LiveConfig,
    mutator: Mutator,
    oracle: Oracle,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """local-apply adds, ignores live drift and (only with -d) deletes, following the BASE -> config diff."""
    repo = live_config.name("local-apply")
    run_filter = live_config.run_ctx.repo_filter()
    baseline_text = live_config.render()
    with_repo = live_config.render(f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: local-apply' }}")
    cli = live_config.cli

    def local_apply(*flags: str, answer: str | None = None) -> str:
        """``local-apply -n -r <run filter> <flags>``: its normalized output (AssertionError unless it exits 0)."""
        result = cli.run("local-apply", "-n", "-r", run_filter, *flags, input=answer)
        return cli_lines(result.assert_ok(f"local-apply {' '.join(flags)}"))

    live_config.touch()
    live_config.write(baseline_text, suffix="-BASE")
    live_config.write(with_repo)
    refused = local_apply(answer="n\n")
    assert HEADER in refused and f'+ add repository[name="{repo}"]' in refused, refused[-3000:]
    assert PROMPT in refused and "Apply cancelled." in refused, refused[-3000:]
    assert oracle.repo(repo) is None, f"{repo} was created although the apply was cancelled"
    added = local_apply("-f")
    assert "Executed plan: 1 added, 0 changed, 0 live resources ignored." in added, added[-3000:]
    created = live_config.wait_repo(repo)
    assert created is not None and created.get("description") == "otterdog e2e: local-apply", created

    mutator.patch_repo(repo, description=DRIFT)
    drifted = waiting.poll(
        lambda: (oracle.repo(repo) or {}).get("description"),
        until=lambda description: description == DRIFT,
        timeout=60.0,
        interval=3.0,
        what=f"the drifted description of {repo}",
        raise_on_timeout=False,
    )
    assert drifted == DRIFT, f"the drift of {repo} is not visible: {drifted!r}"
    live_config.write(with_repo, suffix="-BASE")
    unchanged = local_apply("-f")
    assert "No changes required." in unchanged and "Executed plan:" not in unchanged, unchanged[-3000:]
    live = oracle.repo(repo) or {}
    assert live.get("description") == DRIFT, f"local-apply touched the live drift: {live}"

    live_config.write(with_repo, suffix="-BASE")
    live_config.write(baseline_text)
    live_config.baseline.guard_config_change(with_repo, baseline_text, allow_invalid_head=False)
    kept = local_apply("-f")
    assert f'- remove repository[name="{repo}"]' in kept, kept[-3000:]
    assert "1 resource(s) would be deleted with flag '--delete-resources'." in kept, kept[-3000:]
    assert oracle.repo(repo) is not None, f"{repo} was deleted without -d"
    deleted = local_apply("-f", "-d")
    assert "Executed plan: 0 added, 0 changed, 1 deleted." in deleted, deleted[-3000:]
    assert live_config.wait_repo(repo, present=False) is None, f"{repo} still exists after local-apply -d"
