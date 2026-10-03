"""The webapp never drives the GitHub web UI (docs/web-ui-testing.md): W-PR-WEBUI (P1).

A config PR whose only change is a web-only setting (``members_can_delete_issues``: REST-readable, harmless) is
validated like any other PR, but:

* the validation comment warns that the change needs the Web UI ("some of [the] requested changes require accessing
  the Web UI, need to apply these changes manually", otterdog/webapp/tasks/validate_pull_request.py:199-202) and the
  /api record has ``requires_manual_apply`` true and ``supports_auto_merge`` false (validate_pull_request.py:278-286);
* ``/otterdog merge`` is refused ("cannot be auto-merged", automerge_problems.txt; the problem names "requires web UI
  changes", db/models.py:153-157) and the PR stays open;
* once merged by the admin, the apply comment reports a partial apply (applied_changes_comment.txt: "only partially
  applied as it requires some access to secrets or the Web UI"), /api says ``partially_applied`` and the live setting
  is UNCHANGED (REST oracle): the webapp applies with ``no_web_ui=True`` (tasks/apply_changes.py:188-200);
* ``/otterdog done`` by an admin team member completes it (done_comment.txt, apply_status ``completed``).

Config repo main first pins the live value of the setting, so the PR diff is exactly the web-only change whatever
the template default is; the webapp_case teardown resets main to the baseline (nothing changed live).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.config_repo import comment_contains
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.webui.mapping import jsonnet_fields, web_setting

if TYPE_CHECKING:
    from conftest import WebappScenario

pytestmark = [pytest.mark.webapp]

SETTING = web_setting("members_can_delete_issues")
WEB_UI_WARNING = "require accessing the Web UI, need to apply these changes manually"  # "some of [the] requested ..."
AUTOMERGE_REFUSED = "cannot be auto-merged"
WEB_UI_PROBLEM = "requires web UI changes"
PARTIAL_APPLY = "only partially applied as it requires some access to secrets or the Web UI"
DONE = "The PR has been marked as being completed"


def _text(s: WebappScenario, value: bool) -> str:
    """The baseline with the web-only setting pinned to ``value``."""
    return s.renderer.render(ConfigFragments(settings=jsonnet_fields({SETTING.key: value})))


def _live(s: WebappScenario) -> bool | None:
    """The live value of the setting through REST (GET /orgs/{org}, owner token)."""
    assert SETTING.rest_field is not None
    value = (s.oracle.org() or {}).get(SETTING.rest_field)
    return value if isinstance(value, bool) else None


@pytest.mark.scenario("W-PR-WEBUI", priority="P1")
@pytest.mark.tags("webapp", "org-settings")
def test_web_ui_setting_needs_a_manual_apply(webapp_scenario: WebappScenario) -> None:
    """Web-only change: flagged, not auto-mergeable, merged without effect on GitHub, completed by /otterdog done."""
    s = webapp_scenario
    live = _live(s)
    assert live is not None, f"GET /orgs/{{org}} returns no {SETTING.rest_field}: the oracle needs an owner token"
    s.flow.reset_main(_text(s, live), message=f"otterdog-e2e {s.run_ctx.run_id}: W-PR-WEBUI pins {SETTING.key}")
    pr = s.open_pr(_text(s, not live))

    s.wait_validation(pr)
    body = s.wait_comment(pr, marker="validate").get("body") or ""
    assert comment_contains(body, SETTING.key), f"the validation diff does not show {SETTING.key}"
    assert comment_contains(body, WEB_UI_WARNING), "the validation comment does not warn about the Web UI"
    s.wait_api_pull(
        pr,
        until=lambda r: r.get("requires_manual_apply") is True and r.get("supports_auto_merge") is False,
        what="flagged as requiring the web UI (manual apply, no auto-merge)",
    )

    s.flow.comment(pr, "/otterdog merge")
    refused = s.wait_comment(pr, contains=AUTOMERGE_REFUSED).get("body") or ""
    assert comment_contains(refused, WEB_UI_PROBLEM), f"the auto-merge refusal does not name the web UI:\n{refused}"
    assert not (s.oracle.pull(s.repo, pr.number) or {}).get("merged"), "a web-UI change was auto-merged"

    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    applied = s.wait_applied(pr).get("body") or ""
    assert comment_contains(applied, PARTIAL_APPLY), "the apply comment does not report a partial apply"
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "partially_applied", what="partially applied")
    after = s.reaction(lambda: _live(s), until=lambda value: value is not None, what=SETTING.key, timeout=60)
    assert after == live, f"the webapp changed {SETTING.key} ({live} -> {after}): it must never use the web UI"

    s.flow.comment(pr, "/otterdog done")
    s.wait_comment(pr, contains=DONE)
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "completed", what="completed by /otterdog done")
