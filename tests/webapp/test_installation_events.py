"""W-INSTALLATION-EVENTS (P2): ``installation`` deliveries change the webapp's installation record (coverage feature
webapp-events.installation; webhook/__init__.py:339-348, db/service.py:64-104 and 278-334).

The deliveries are synthetic (WebhookInjector, signed with the App webhook secret) and carry the REAL installation id:
GitHub's installation is never touched. /admin/organizations shows the record (WebappApi.installations()):

* ``suspend``: status suspended;
* ``unsuspend``: status installed and a data refresh (FetchConfigTask and FetchAllPullRequestsTask of the config repo);
* ``deleted``: status not_installed with installation id 0 (the org's data stays: the org is still configured);
* ``created``: the webapp reads the installation from GitHub (GET /app/installations/{id}): installed with the real
  id again, plus the data refresh.

``/internal/init`` restores the record from GitHub's installation list afterwards if anything failed in between
(E2EContext.reload_webapp), so later tests always find the installation installed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.webhooks.payloads import installation_payload

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.webapp.stack import ExternalWebapp, WebappStack
    from otterdog_e2e.webhooks.injector import WebhookInjector

pytestmark = [pytest.mark.webapp]

REFRESH_TASKS = ("FetchConfigTask", "FetchAllPullRequestsTask")  # db/service.py update_data_for_installation


@pytest.mark.scenario("W-INSTALLATION-EVENTS", priority="P2")
@pytest.mark.tags("webapp", "webhooks-app")
def test_installation_events_update_the_record(
    webapp_scenario: WebappScenario,
    injector: WebhookInjector,
    installation_id: int,
    webapp: WebappStack | ExternalWebapp,
) -> None:
    """suspend -> suspended; unsuspend -> installed + data refresh; deleted -> not_installed, id 0; created ->
    installed with the real id + data refresh."""
    s = webapp_scenario
    before = s.installation()
    assert before is not None and before.get("status") == "installed", f"precondition: installed record {before}"
    assert before.get("installation_id") == installation_id, f"precondition: the real installation id {before}"
    restored = False
    try:
        for action, status, record_id, refreshed in (
            ("suspend", "suspended", installation_id, False),
            ("unsuspend", "installed", installation_id, True),
            ("deleted", "not_installed", 0, False),
            ("created", "installed", installation_id, True),
        ):
            at = s.now()
            payload = installation_payload(action, installation_id=installation_id, org=s.org)
            response = injector.send("installation", payload)
            assert response.status_code == 204, f"the receiver refused the {action} delivery: {response.status_code}"
            row = s.wait_installation(status=status, installation_id=record_id)
            assert row.get("project_name") == before.get("project_name"), f"{action} changed the project: {row}"
            for task_type in REFRESH_TASKS if refreshed else ():
                task = s.wait_repo_task(task_type, after=at)
                assert task.get("status") == "finished", f"{task_type} after {action}: {task}"
        restored = True
    finally:
        if not restored:  # leave an installed record for the next tests whatever failed
            s.e2e.reload_webapp(webapp)
    s.quiesce()
    assert (s.installation() or {}).get("status") == "installed", "the installation record is not restored"
