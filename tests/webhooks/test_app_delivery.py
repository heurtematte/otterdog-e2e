"""H-APP-DELIVERY: a real App delivery reaches the webapp through the pull relay (SPEC 19, 13.3).

Opening a config PR makes GitHub deliver ``pull_request``/``opened`` to the App's (sink) hook URL; the relay finds it
in the App delivery log (GET /app/hook/deliveries, our installation only), re-signs it with the webhook secret and
forwards it to the loopback receiver, which answers 204. The relay records it in <artifacts>/deliveries.jsonl and
the webapp processes it (UpdatePullRequestTask of the PR). The PR is never merged; webapp_case closes it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import WebhookHelpers
    from otterdog_e2e.config_repo import ConfigRepoFlow
    from otterdog_e2e.context import WebappCase
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.settings import Target
    from otterdog_e2e.webapp.api import WebappApi
    from otterdog_e2e.webhooks.relay import DeliveryRelay

pytestmark = [pytest.mark.webapp]

SCENARIO = "H-APP-DELIVERY"


@pytest.mark.scenario(SCENARIO, priority="P0")
@pytest.mark.tags("webhooks-app", "webapp", "smoke")
def test_config_pr_delivery_is_relayed(
    webapp_case: WebappCase,
    config_flow: ConfigRepoFlow,
    relay: DeliveryRelay,
    webapp_api: WebappApi,
    renderer: OrgConfigRenderer,
    run_ctx: RunContext,
    target: Target,
    installation_id: int,
    webhook_helpers: type[WebhookHelpers],
) -> None:
    """pull_request/opened of the installation forwarded with 204, recorded in deliveries.jsonl, processed."""
    helpers = webhook_helpers
    description = f"otterdog e2e {run_ctx.run_id} {SCENARIO}: description change"
    opened_after = datetime.now(UTC)
    pr = config_flow.open_pr(
        slug="h-app-delivery",
        config_texts=helpers.harmless_text(renderer, target, description),
        title=f"e2e {run_ctx.run_id} {SCENARIO}",
        body=helpers.pr_body(SCENARIO, run_ctx.run_id),
    )

    delivery = config_flow.wait_delivery(pr, event="pull_request", action="opened", after=opened_after)
    assert delivery is not None, "the config flow has no relay: deliveries cannot be observed"
    assert delivery.installation_id == installation_id, f"delivery of another installation: {delivery}"
    assert delivery.pull_number == pr.number, f"delivery for PR #{delivery.pull_number}, expected #{pr.number}"
    assert delivery.head_sha in (None, pr.head_sha), f"delivery for head {delivery.head_sha}, expected {pr.head_sha}"
    assert delivery.relay_status == 204, f"the receiver answered the relayed delivery with HTTP {delivery.relay_status}"
    assert delivery.forwarded_at is not None and delivery.error is None, f"relay error: {delivery.error}"

    records = [r for r in helpers.delivery_records(relay.deliveries_file) if r.get("id") == delivery.id]
    assert len(records) == 1, f"deliveries.jsonl holds {len(records)} record(s) of delivery {delivery.id}"
    record = records[0]
    expected = {
        "guid": delivery.guid,
        "event": "pull_request",
        "action": "opened",
        "installation_id": installation_id,
        "pull_number": pr.number,
        "relay_status": 204,
    }
    mismatches = {key: record.get(key) for key, value in expected.items() if record.get(key) != value}
    assert not mismatches, f"deliveries.jsonl record of {delivery.guid} differs: {mismatches}"
    assert record.get("forwarded_at"), f"deliveries.jsonl record without forward time: {record}"

    task = helpers.wait_task(
        webapp_api,
        type_="UpdatePullRequestTask",
        org=webapp_case.org,
        repo=config_flow.repo,
        pull_request=pr.number,
        after=opened_after,
    )
    assert task.get("status") == "finished", f"the webapp failed to process the relayed delivery: {task}"
