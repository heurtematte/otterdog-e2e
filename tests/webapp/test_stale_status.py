"""W-PR-STALE-SNAPSHOT (P1): a stale webhook snapshot must not turn a merged PR back to open (fixed by otterdog #792).

Mechanics (FACTS tests.json "BRANCH 1", scenario CS792-01): tasks store the webhook snapshot they were scheduled with
when they finish (``update_or_create_pull_request``); before #792 the snapshot's lifecycle fields (status, draft,
created/updated/closed/merged_at) overwrite the database unconditionally, so a late task holding the old open snapshot
reopens a merged and applied PR in /api. Deterministic reproduction: after a merged and applied PR, inject a signed
``pull_request`` ``converted_to_draft`` delivery carrying the PR as it was while open (captured right after opening,
so its updated_at is strictly older than the merge; the same-second variant CS792-02 is out of scope). That action
schedules only an UpdatePullRequestTask (webhook/__init__.py:112-128).

Expected on SUTs including #792: the /api record stays ``merged`` with apply_status ``completed`` and the PR stays out
of /api/pullrequests/open. SUTs without the fix (v1.6.1, main 9bdeb75) show it ``open`` again (known bug KB-018 of
scenarios/known_bugs.yaml). Unless the webapp image is known to contain the fix commit 2c5f977 (the PR's first commit,
which fixes this strictly-older variant), the test is a NON-strict xfail limited to StaleStatusRegressionError: base
SUTs xfail, fixed ones xpass (also after a squash merge upstream, whose commit sha differs), and any other failure
(infra, flow) still fails. The before/after records are written to <artifacts>/webapp/w-pr-stale-snapshot.json
either way: that file is the base-vs-head evidence of the expected delta its reference to #792 declares (the
in-session differential only compares CLI observations, so the report lists that delta as not observed).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.webhooks.payloads import pull_request_payload

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.webhooks.injector import WebhookInjector

pytestmark = [pytest.mark.webapp]

FIX_792 = "2c5f9775994f35d813d23119b0ed313c49ac32fc"  # fix: do not revert pull request status with an outdated snapshot
STALE_ACTION = "converted_to_draft"  # schedules UpdatePullRequestTask only (no validation, help or apply task)
TASK = "UpdatePullRequestTask"
CLOCK_SLACK = timedelta(seconds=30)  # webapp container clock vs harness clock (task created_at is naive UTC)
KNOWN_BUG = "stale webhook snapshots overwrite the status of merged pull requests (otterdog#792 not included)"


class StaleStatusRegressionError(AssertionError):
    """A stale snapshot moved a merged PR back in its lifecycle (the bug otterdog#792 fixes)."""


REFERENCES = [
    {
        "pr": 792,
        "note": (
            "fix/stale-pr-status-overwrite (open when referenced): head d0d3b0832d8e21a9da86e0ef967859d2634af894 = 4"
            " commits on top of main 9bdeb75 touching only otterdog/webapp/db/service.py (update_or_create_pull_request)"
            " and its test: 2c5f977 do not revert pull request status with an outdated snapshot, e3285b6 make the"
            " status update atomic, f0bf0c6 make the creation race in the test, d0d3b08 do not go back in the lifecycle"
            " within the same second. Bug on the base: a task scheduled with a webhook snapshot stores the snapshot's"
            " lifecycle fields when it finishes, so a late snapshot (the backed-off sync check, any stale 'open' event)"
            " turns a merged PR back to 'open' (incident osgi/.eclipsefdn#25). No base: the differential compares with"
            " the merge base of the PR head (9bdeb75, `otterdog-e2e pr 792 --sha d0d3b08...`, --base-sut auto); the"
            " head is an untrusted pr: SUT (docker image) and the webapp tier needs a config_reader identity. The PR"
            " changes the webapp's database layer only: the CLI is identical, so every offline scenario must be"
            " unchanged between base and head (any offline delta is unexpected); no bot comment or commit status may"
            " be created by the injected stale event on either side, only the stored pull request state differs."
        ),
        "template": "own",
        "expected_deltas": [
            {
                "note": (
                    "after a merge, a stale converted_to_draft snapshot injected with a valid signature (204) leaves the"
                    " PR merged on head (it stays in /api/pullrequests/merged, merged_at/closed_at kept); on base it"
                    " reappears in /api/pullrequests/open with status open and merged_at null"
                )
            }
        ],
    }
]


@pytest.mark.scenario("W-PR-STALE-SNAPSHOT", priority="P1", references=REFERENCES)
@pytest.mark.tags("webapp", "webhooks-app")
def test_stale_snapshot_keeps_merged_status(
    request: pytest.FixtureRequest, webapp_scenario: WebappScenario, injector: WebhookInjector, installation_id: int
) -> None:
    """Merge + apply, then a signed stale ``converted_to_draft`` snapshot: /api keeps the PR merged and completed."""
    s = webapp_scenario
    reason = s.known_bug_reason("/pull/792", KNOWN_BUG)
    s.xfail_unless_includes(request, FIX_792, error=StaleStatusRegressionError, reason=reason, strict=False)
    name = s.run_repo()
    pr = s.open_pr(s.text(repos={name: s.describe("merged before the stale snapshot")}))
    snapshot = s.oracle.pull(s.repo, pr.number)  # the open snapshot, strictly older than the merge
    assert snapshot is not None and snapshot.get("state") == "open", f"PR #{pr.number} snapshot: {snapshot}"
    s.wait_settled(pr)

    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    s.wait_applied(pr)
    before = s.wait_api_pull(
        pr,
        until=lambda r: r.get("status") == "merged" and r.get("apply_status") == "completed",
        what="merged and completed",
    )
    s.quiesce()  # the merge's own tasks are done: the next task of the PR is the injected one

    previous = s.latest_task_created(TASK, pr)
    injected_at = datetime.now(UTC)
    floor = previous + timedelta(milliseconds=1) if previous is not None else injected_at - CLOCK_SLACK
    payload = pull_request_payload(
        STALE_ACTION,
        org=s.org,
        repo=s.repo,
        pull_request=snapshot,
        installation_id=installation_id,
        sender=str((snapshot.get("user") or {}).get("login") or "e2e-injector"),
    )
    response = injector.send("pull_request", payload)
    assert response.status_code == 204, f"the receiver refused the signed stale delivery: HTTP {response.status_code}"
    task = s.wait_task(TASK, pr, after=floor)
    after = s.api.pull_request(s.org, s.repo, pr.number)
    listed_open = s.api.open_pull_requests(org_id=s.org, repo_name=s.repo)
    open_numbers = {(record.get("id") or {}).get("pull_request") for record in listed_open}
    s.write_evidence(
        {
            "pull_request": pr.number,
            "injected": {"action": STALE_ACTION, "snapshot_updated_at": snapshot.get("updated_at"), "at": injected_at},
            "task": task,
            "before": before,
            "after": after,
            "listed_open_after": pr.number in open_numbers,
        }
    )

    assert task.get("status") == "finished", f"{TASK} for the stale snapshot did not finish: {task}"
    assert after is not None, f"PR #{pr.number} vanished from /api after the stale snapshot"
    assert after.get("apply_status") == "completed", f"apply status lost after the stale snapshot: {after}"
    symptoms = {
        "status": after.get("status") != "merged",
        "merged_at": not after.get("merged_at"),
        "listed open": pr.number in open_numbers,
    }
    reverted = sorted(field for field, broken in symptoms.items() if broken)
    if reverted:
        raise StaleStatusRegressionError(
            f"a stale {STALE_ACTION} snapshot moved merged PR #{pr.number} back ({', '.join(reverted)}): {after}"
        )
