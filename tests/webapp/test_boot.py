"""W-BOOT: the webapp under test is up, initialized for the test org and reachable by relayed deliveries (SPEC 19).

The ``webapp`` fixture already performed the SPEC 15 start sequence (compose up or external URL, baseline on config
repo main, otterdog.json in the configs repo, /internal/init, wait_ready); this test re-checks every observable of
that state, so a broken boot fails here with a precise message instead of inside a PR flow.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.sut.version import public_version
from otterdog_e2e.webhooks.payloads import ping_payload

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.settings import Target
    from otterdog_e2e.webapp.api import WebappApi
    from otterdog_e2e.webapp.stack import ExternalWebapp, WebappStack
    from otterdog_e2e.webhooks.injector import WebhookInjector
    from otterdog_e2e.webhooks.relay import DeliveryRelay

pytestmark = [pytest.mark.webapp]


@pytest.mark.scenario("W-BOOT", priority="P0")
@pytest.mark.tags("webapp", "webhooks-app", "smoke")
def test_webapp_boot(
    e2e: E2EContext,
    webapp: WebappStack | ExternalWebapp,
    webapp_api: WebappApi,
    relay: DeliveryRelay,
    injector: WebhookInjector,
    baseline: BaselineManager,
    target: Target,
) -> None:
    """Healthy, org listed with its configuration fetched from the run's config repo, SUT version deployed, relay
    polling, receiver accepting deliveries signed with the App webhook secret."""
    org = target.org
    assert webapp_api.health(), "GET /internal/health did not answer 200"

    listed = [row.get("github_id") for row in webapp_api.organizations()]
    assert org in listed, f"/api/organizations does not list {org!r} (exact case): {listed}"

    config = webapp_api.organization(org)
    assert config is not None, f"/api/organizations/{org} is 404: the configuration was never fetched"
    declared = {repo.get("name") for repo in config.get("repositories") or [] if isinstance(repo, dict)}
    missing = sorted(set(baseline.baseline_repos) - declared)
    assert not missing, f"the configuration stored by the webapp lacks the baseline repositories {missing}"

    # newest completed fetch (a push to main by an earlier test's teardown may have started another one meanwhile)
    fetches = [
        task
        for task in webapp_api.tasks(org_id=org, type_="FetchConfigTask", page_size=20)
        if task.get("status") in ("finished", "failed")
    ]
    assert fetches, f"no completed FetchConfigTask recorded for {org}"
    assert fetches[0].get("status") == "finished", f"newest completed FetchConfigTask of {org} failed: {fetches[0]}"

    if hasattr(webapp, "down"):  # compose stack: the image was built from (or given as) the SUT under test
        image = e2e.image_for("head")
        deployed = webapp.deployed_version()
        if image.version:
            assert deployed is not None, "GET /index shows no 'OtterDog - v<version>' footer"
            assert public_version(deployed) == public_version(image.version), (
                f"webapp shows version {deployed!r}, the image {image.tag} was built as {image.version!r}"
            )

    assert relay.running(), "the delivery relay is not polling"
    response = injector.send("ping", ping_payload())
    assert response.status_code == 204, (
        f"the receiver answered a signed ping with HTTP {response.status_code}: relayed deliveries would be refused "
        "(webhook secret mismatch?)"
    )
