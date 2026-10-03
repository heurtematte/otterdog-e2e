"""C-BASELINE (SPEC 19, P0): right after the baseline reset the SUT reports the org as valid and in sync.

The ``baseline`` fixture performs BaselineManager.reset() at its first use (unless --e2e-no-reset) with the trusted
reset SUT. This test then asks the SUT UNDER TEST: ``check-status -n -j`` (otterdog/operations/check_status.py) on
the baseline configuration must report no validation notice and ``in_sync`` (no patch at all, read-only ones
included). Note that check-status exits 0 whatever the status (KB-011): the JSON entry is what is asserted. On a
mismatch the SUT's plan is attached to the failure to show which objects differ.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import Target

pytestmark = [pytest.mark.scenario("cli.baseline"), pytest.mark.tags("smoke", "cli", "org-settings")]

MAX_LISTED = 15


def test_baseline_in_sync_after_reset(
    baseline: BaselineManager,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    target: Target,
) -> None:
    """check-status of the baseline config: valid (no notice) and in sync."""
    fresh_workspace.write_org_config(baseline.text())
    cli = make_cli(fresh_workspace)
    result, entry = cli.check_status(fresh_workspace.root / "check-status.json")
    result.assert_ok("check-status")
    assert entry is not None, f"check-status wrote no entry for {target.org}:\n{result.output[-2000:]}"
    validation, sync = entry.get("validation_status") or {}, entry.get("sync_status") or {}
    assert validation.get("errors") == 0, f"the baseline does not validate: {validation}\n{result.output[-2000:]}"
    if validation.get("is_valid") is True and sync.get("in_sync") is True:
        return
    pytest.fail(f"baseline not in sync after the reset: validation {validation}, sync {sync}; {_pending(cli)}")


def _pending(cli: OtterdogCli) -> str:
    """The SUT's plan objects that are not read-only (diagnosis of an out-of-sync baseline)."""
    plan = cli.plan().plan()
    pending = [obj.header.strip() for obj in plan.objects if not obj.is_read_only]
    shown = "; ".join(pending[:MAX_LISTED]) + (f"; ... ({len(pending)} in total)" if len(pending) > MAX_LISTED else "")
    return f"plan: {plan.add} to add, {plan.change} to change, {plan.delete} to delete: {shown or 'no object'}"
