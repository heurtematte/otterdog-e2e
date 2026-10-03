"""W-CMD-CHECK-MERGE (P2): ``/otterdog check-merge`` reports auto-merge eligibility and never merges.

The command exists only in the maintainer's local feature branch feat/check-merge-command (manifest
scenarios/otterdog-prs/local-check-merge.yaml, SUT ``dirty:<otterdog checkout>``, base v1.6.0): its
CheckMergeCommentHandler schedules a CheckMergeTask, which minimizes the previous check-merge comments of the PR as
outdated and posts a ``<!-- Otterdog Comment: check-merge -->`` comment. For an open PR the comment says whether the PR
is eligible for auto-merge via ``/otterdog merge``; ineligible PRs also get the problems and an outdated-branch note.
Closed or merged PRs get a note instead. The task never merges.

SUTs without the feature (every upstream release so far) skip: the source the webapp image was built from has no
otterdog/webapp/tasks/check_merge.py, and such a webapp ignores the command (the manifest's expected delta: base posts
nothing). External webapps and prebuilt images skip too, because the harness cannot tell whether they have the
feature.

W-CMD-CHECK-MERGE-REFRESH (P2, pending.automerge-state-refresh): check-merge refreshes a stale author_can_auto_merge
from the live team membership (tasks/automerge_state.py refresh_automerge_state: membership and approvals are
re-read unless already known to be sufficient). The approval teams of the org are overridden in otterdog.json with a
run team (webapp_otterdog_json); the contributor's PR is not eligible, the contributor joins the run team, and the
next ``/otterdog check-merge`` says eligible and records author_can_auto_merge true.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e.config_repo import comment_contains

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.github.mutate import Mutator

pytestmark = [pytest.mark.webapp]

FEATURE_FILE = "otterdog/webapp/tasks/check_merge.py"  # CheckMergeTask of feat/check-merge-command
MARKER = "check-merge"  # <!-- Otterdog Comment: check-merge --> (manifest local-check-merge.yaml)
# check_merge_comment.txt: "... is eligible for auto-merge, comment `/otterdog merge` ..." or "... is currently not
# eligible for auto-merge via `/otterdog merge`" (open PRs)
ELIGIBILITY_RE = re.compile(r"(not )?eligible for auto-merge", re.IGNORECASE)
NOT_ELIGIBLE = "is currently not eligible for auto-merge"
ELIGIBLE = "This pull request is eligible for auto-merge"


def _skip_without_feature(s: WebappScenario) -> None:
    """Skip unless the source of the webapp under test has the check-merge command."""
    has_feature = s.webapp_source_has(FEATURE_FILE)
    if not has_feature:
        known = "has no" if has_feature is False else "cannot tell whether it has"
        pytest.skip(f"webapp under test {known} the /otterdog check-merge command ({FEATURE_FILE})")


@pytest.mark.scenario("W-CMD-CHECK-MERGE", priority="P2")
@pytest.mark.tags("webapp")
def test_check_merge_command(webapp_scenario: WebappScenario) -> None:
    """``/otterdog check-merge`` twice on an open PR: an eligibility comment each time, the first one minimized as
    outdated, and the PR stays open (the command never merges)."""
    s = webapp_scenario
    _skip_without_feature(s)
    pr = s.open_pr(s.harmless_text())
    s.wait_settled(pr)  # eligibility depends on the validation and sync results

    s.flow.comment(pr, "/otterdog check-merge")
    first = s.wait_comment(pr, marker=MARKER)
    body = first.get("body") or ""
    assert ELIGIBILITY_RE.search(body), f"check-merge comment without an eligibility verdict (SUT): {body[:1500]!r}"

    s.flow.comment(pr, "/otterdog check-merge")
    second = s.wait_comment(pr, marker=MARKER, exclude=[first])
    assert comment_contains(second.get("body") or "", "auto-merge"), "second check-merge comment without a verdict"
    s.wait_minimized(pr, first)

    pull = s.oracle.pull(s.repo, pr.number)
    assert pull is not None and pull.get("state") == "open" and not pull.get("merged"), (
        f"/otterdog check-merge must never merge PR #{pr.number} (SUT): state {pull and pull.get('state')!r}"
    )
    s.write_evidence({"pr": pr.number, "first": body, "second": second.get("body") or ""})


@pytest.mark.scenario("W-CMD-CHECK-MERGE-REFRESH", priority="P2")
@pytest.mark.tags("webapp", "teams")
@pytest.mark.identities("author")
def test_check_merge_refreshes_the_team_membership(
    webapp_scenario: WebappScenario,
    webapp_otterdog_json: Callable[[Mapping[str, Any]], None],
    mutator: Mutator,
) -> None:
    """Approval team = a run team (otterdog.json override): the contributor's PR is not eligible; once the
    contributor is a member of that team, ``/otterdog check-merge`` re-reads the membership: eligible, /api
    author_can_auto_merge true, the first verdict minimized."""
    s = webapp_scenario
    _skip_without_feature(s)
    team = s.run_repo("approvers")
    mutator.create_team(team, description=s.describe("approval team of the check-merge refresh"))
    try:
        webapp_otterdog_json({"approval_teams": [f"^{team}$"]})
        pr = s.open_pr(s.harmless_text(), identity="author")
        s.wait_settled(pr)
        s.wait_api_pull(pr, until=lambda r: r.get("author_can_auto_merge") is False, what="author not eligible")

        s.flow.comment(pr, "/otterdog check-merge", identity="author")
        first = s.wait_comment(pr, marker=MARKER)
        assert comment_contains(first.get("body") or "", NOT_ELIGIBLE), f"eligible before joining: {first!r}"

        mutator.add_team_member(team, s.login("author"))
        s.flow.comment(pr, "/otterdog check-merge", identity="author")
        second = s.wait_comment(pr, marker=MARKER, exclude=[first])
        assert comment_contains(second.get("body") or "", ELIGIBLE), (
            f"check-merge kept the stale team membership of the author (SUT): {(second.get('body') or '')[:1500]!r}"
        )
        s.wait_api_pull(pr, until=lambda r: r.get("author_can_auto_merge") is True, what="refreshed membership")
        s.wait_minimized(pr, first)
        s.assert_still_open(pr, "/otterdog check-merge never merges")
    finally:
        mutator.delete_team(team)
