"""H-ORG-HOOK (P1, org_level): an otterdog-managed organization webhook, created, pinged and removed (SPEC 19).

The SUT CLI applies an org webhook whose URL lies under the never-resolving HOOK_BASE (``-r e2e-<run>-*``: org
webhooks are org-level objects, always diffed); the oracle sees it with the declared settings and the plan converges;
a ping is recorded in the hook's delivery log by GitHub (the delivery itself fails: ``.invalid`` never resolves);
the guarded ``apply -d`` (removals limited to purgeable run objects) removes it. Teardown: full baseline reset.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.github.oracle import deliveries_since
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.waiting import CONVERGE_BACKOFF

if TYPE_CHECKING:
    from conftest import WebhookHelpers
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import OtterdogCli

pytestmark = [pytest.mark.org_level]

HOOK_EVENTS = ["push"]


@pytest.mark.scenario("H-ORG-HOOK", priority="P1")
@pytest.mark.tags("webhooks")
@pytest.mark.usefixtures("org_level_reset")
def test_org_webhook_lifecycle(
    otterdog: OtterdogCli,
    renderer: OrgConfigRenderer,
    baseline: BaselineManager,
    oracle: Oracle,
    mutator: Mutator,
    run_ctx: RunContext,
    webhook_helpers: type[WebhookHelpers],
) -> None:
    """Create (plan add, apply, oracle, converge), ping (GitHub delivery log), remove (guarded apply -d, oracle)."""
    helpers = webhook_helpers
    url = run_ctx.hook_url("h-org-hook")
    scope, needles = run_ctx.repo_filter(), run_ctx.needles()
    hook = f"orgs.newOrgWebhook({json.dumps(url)}) {{ content_type: 'json', events: {json.dumps(HOOK_EVENTS)} }}"

    otterdog.workspace.write_org_config(renderer.render(ConfigFragments(webhooks=[hook])))
    plan = otterdog.plan(repo_filter=scope).assert_ok("plan (org webhook added)").plan()
    added = [obj for obj in plan.objects_for(needles) if obj.kind == "org_webhook" and obj.op == "add"]
    assert added, f"the plan does not add the org webhook {url}: {[obj.header for obj in plan.objects]}"
    helpers.assert_applied(otterdog.apply(repo_filter=scope), "apply (org webhook added)")

    live = helpers.reaction(
        lambda: oracle.org_hook_by_url(url),
        until=lambda h: h is not None,
        what=f"org hook {url}",
        timeout=helpers.STATE_TIMEOUT,
    )
    assert live.get("active") is True, f"org hook not active: {live}"
    assert (live.get("config") or {}).get("content_type") == "json", f"org hook content type: {live.get('config')}"
    assert sorted(live.get("events") or []) == HOOK_EVENTS, f"org hook events: {live.get('events')}"
    helpers.reaction(
        lambda: otterdog.plan(repo_filter=scope).plan(),
        until=lambda p: p.is_noop(needles),
        what="plan converged after the org webhook was applied",
        timeout=helpers.CONVERGE_TIMEOUT,
        interval=CONVERGE_BACKOFF,
    )

    hook_id = int(live["id"])
    known = {delivery.get("id") for delivery in oracle.org_hook_deliveries(hook_id)}
    pinged_at = mutator.ping_org_hook(hook_id)  # GitHub's time: the creation ping logged late never counts (BAT-10)
    pings = helpers.reaction(
        lambda: [
            d
            for d in deliveries_since(oracle.org_hook_deliveries(hook_id), pinged_at, event="ping")
            if d.get("id") not in known
        ],
        until=bool,
        what=f"ping delivery of org hook {hook_id} in GitHub's delivery log",
        timeout=helpers.HOOK_DELIVERY_TIMEOUT,
        infra=True,
    )
    assert pings[0].get("event") == "ping"

    otterdog.workspace.write_org_config(baseline.text())
    removed = baseline.guarded_apply(otterdog, repo_filter=scope, delete=True)
    assert not removed.aborted_validation and not removed.failed_patches, f"removal failed:\n{removed.raw[-2000:]}"
    helpers.reaction(
        lambda: oracle.org_hook_by_url(url),
        until=lambda h: h is None,
        what=f"{url} removed",
        timeout=helpers.STATE_TIMEOUT,
    )
