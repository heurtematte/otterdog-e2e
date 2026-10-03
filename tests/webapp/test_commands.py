"""``/otterdog`` comment commands on an open config PR and the sync check (SPEC 19, coverage area webapp-commands).

W-CMD-HELP: ``/otterdog help`` re-posts the help comment and minimizes the previous one as outdated.
W-CMD-VALIDATE (P1): ``/otterdog validate`` re-validates the head (new validate comment for the head sha, the previous
one minimized, status success again).
W-DRIFT-CHECKSYNC (P1): a run repository declared on main drifts on GitHub; the sync check of a new PR and then
``/otterdog check-sync`` report it (out-of-sync comment naming the repository and its live value, sync description
"otterdog sync check failed, ..." while the state stays success by design); the comment is a ``> [!WARNING]`` alert
since otterdog#765 (975cf1b, v1.6.0), a ``> [!NOTE]`` before.

The battery adds:

* W-CMD-TEAM-INFO (P1): the team-info comment of a contributor's PR (on open and on ``/otterdog team-info``) names
  the author, the role GitHub reports and the author's teams; /api author_can_auto_merge is false;
* W-CMD-VALIDATE-INFO (P2): ``/otterdog validate info`` adds the Info messages the default validation only counts;
* W-CMD-NEG (P1): command matching (start of the body only, ``\\s+`` between the words, prefix match without word
  boundary, one command per comment), edited comments re-run their command, deleted comments, issue comments and
  comments of other repositories are ignored;
* W-SYNC-FAILURE (P2, KB-040): a sync check that crashes (main raises while it loads) posts a ``failure`` status,
  no comment and a failed task; its description claims out-of-sync changes (KB-040);
* W-SYNC-INVALID-MAIN (P2, KB-067): a main that fails validation cannot be planned, yet the sync check reports
  "completed successfully" and in_sync true.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.config_repo import MARKERS, comment_contains, normalize_comment
from otterdog_e2e.webhooks.payloads import issue_comment_payload

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.config_repo import ConfigPr
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.webhooks.injector import WebhookInjector

pytestmark = [pytest.mark.webapp]

FIX_765 = "975cf1b24cf17d3dd819242e2d8f6ed7e9d56d55"  # fix: raise out-of-sync notification level (#765)
DUMMY_INFO = "only has a dummy value, resource will be skipped"  # models/secret.py:45-48 (Info)
SYNTHETIC_NUMBER = 900_000_000  # an issue / PR number no repository of the test org has (a stray task would 404)


class MisleadingSyncFailureError(AssertionError):
    """A crashed sync check is described as detected out-of-sync changes (KB-040)."""


class SyncCheckIgnoresValidationErrorsError(AssertionError):
    """The sync check reports "in sync" for a main whose validation fails (the plan never compared anything)."""


def _alert_lines(body: str) -> list[str]:
    """The non-empty lines of a comment, stripped."""
    return [line.strip() for line in body.strip().splitlines() if line.strip()]


def _team_info_checks(s: WebappScenario, pr: ConfigPr, body: str, author: str) -> None:
    """The team-info comment names the author with a link, GitHub's author_association of the PR and the link of
    the contributors team (the author's only baseline team)."""
    match = s.texts.TEAM_INFO_RE.search(body)
    assert match, f"team-info comment without the author's role (SUT): {body[:1500]!r}"
    association = s.pull(pr).get("author_association")
    assert match.group("role") == association, (
        f"team-info shows the role {match.group('role')!r}, GitHub reports {association!r} for PR #{pr.number} (SUT)"
    )
    assert f"([{author}](https://github.com/{author}))" in body, f"team-info does not link the author {author}"
    contributors = f"https://github.com/orgs/{s.org}/teams/{s.target.contributors_team}"
    assert contributors in body, f"team-info does not list the contributors team ({contributors}): {body[:1500]!r}"
    for team in (s.target.admin_team, s.target.approval_team):
        assert f"/teams/{team})" not in body, f"team-info lists {team}, the author is not a member: {body[:1500]!r}"


@pytest.mark.scenario("W-CMD-HELP", priority="P0")
@pytest.mark.tags("webapp")
def test_help_command(webapp_scenario: WebappScenario) -> None:
    """``/otterdog help``: a new help comment, the previous one minimized as outdated, the new one visible."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.harmless_text())
    first = s.wait_comment(pr, marker="help")

    s.flow.comment(pr, "/otterdog help")
    second = s.wait_comment(pr, marker="help", exclude=[first])
    assert comment_contains(second.get("body") or "", texts.HELP), "re-posted help comment without its greeting"

    s.wait_minimized(pr, first)
    assert not s.current_comment(pr, second).get("is_minimized"), "the new help comment is minimized"


@pytest.mark.scenario("W-CMD-VALIDATE", priority="P1")
@pytest.mark.tags("webapp", "repo")
def test_validate_command(webapp_scenario: WebappScenario) -> None:
    """``/otterdog validate``: a new validate comment for the head sha, the previous one minimized, success again."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.harmless_text())
    s.wait_validation(pr)
    first = s.wait_comment(pr, marker="validate")

    s.flow.comment(pr, "/otterdog validate")
    second = s.wait_comment(pr, marker="validate", exclude=[first])
    body = second.get("body") or ""
    assert comment_contains(body, f"{texts.DIFF_FOR} {pr.head_sha}"), f"new validate comment is not for {pr.head_sha}"
    assert comment_contains(body, s.harmless_repo), f"new validate comment does not name {s.harmless_repo}"

    s.wait_minimized(pr, first)
    status = s.wait_validation(pr)
    assert texts.VALIDATION_SUCCESS_RE.search(status.get("description") or ""), f"unexpected status: {status}"


@pytest.mark.scenario("W-DRIFT-CHECKSYNC", priority="P1")
@pytest.mark.tags("webapp", "repo")
def test_drift_check_sync(webapp_scenario: WebappScenario, mutator: Mutator) -> None:
    """Drift of a declared run repository: out-of-sync comment (a WARNING alert since #765) and sync description,
    again after the command."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name = s.run_repo()
    declared, live = f"e2e {s.run_ctx.run_id} declared", f"e2e {s.run_ctx.run_id} drifted"
    s.declare_live({name: declared})
    mutator.patch_repo(name, description=live)  # the drift: GitHub no longer matches config repo main

    pr = s.open_pr(s.harmless_text(repos={name: declared}))
    first = s.wait_check_sync_comment(pr)
    body = first.get("body") or ""
    assert comment_contains(body, texts.OUT_OF_SYNC), f"check-sync comment without its warning: {body[:500]!r}"
    assert comment_contains(body, name), f"check-sync comment does not name {name}: {body[:2000]!r}"
    assert comment_contains(body, live), f"check-sync comment does not show the live value {live!r}"
    lines = _alert_lines(body)
    included = s.webapp_includes(FIX_765)
    alerts = {True: ("> [!WARNING]",), False: ("> [!NOTE]",), None: ("> [!WARNING]", "> [!NOTE]")}[included]
    assert lines[:1] == [MARKERS["check-sync"]] and len(lines) > 1 and lines[1] in alerts, (
        f"the check-sync comment must start with its marker and a {' or '.join(alerts)} alert "
        f"(otterdog#765 {'included' if included else 'not included' if included is False else 'unknown'}): {lines[:3]}"
    )
    status = s.wait_sync(pr)
    assert status.get("state") == "success", f"the sync status never blocks a merge: {status}"
    assert texts.SYNC_FAILED_RE.search(status.get("description") or ""), f"sync status hides the drift: {status}"

    s.flow.comment(pr, "/otterdog check-sync")
    second = s.wait_check_sync_comment(pr, exclude=[first])
    body = second.get("body") or ""
    assert comment_contains(body, texts.OUT_OF_SYNC) and comment_contains(body, name), (
        f"check-sync command did not report the drift of {name}: {body[:2000]!r}"
    )
    s.wait_minimized(pr, first)
    status = s.wait_sync(pr)
    assert texts.SYNC_FAILED_RE.search(status.get("description") or ""), f"sync status after the command: {status}"


@pytest.mark.scenario("W-CMD-TEAM-INFO", priority="P1")
@pytest.mark.tags("webapp", "teams")
@pytest.mark.identities("author")
def test_team_info_command(webapp_scenario: WebappScenario) -> None:
    """Contributor PR: team-info comment on open (author, role, contributors team), /api author_can_auto_merge
    false; ``/otterdog team-info`` by the author posts a new one and minimizes the first."""
    s = webapp_scenario
    author = s.login("author")
    pr = s.open_pr(s.harmless_text(), identity="author")
    first = s.wait_comment(pr, marker="team-info")
    _team_info_checks(s, pr, first.get("body") or "", author)
    record = s.wait_api_pull(
        pr, until=lambda r: r.get("author_can_auto_merge") is not None, what="author team membership known"
    )
    assert record.get("author_can_auto_merge") is False, (
        f"a member of {s.target.contributors_team} only cannot auto-merge without approval (SUT): {record}"
    )

    s.flow.comment(pr, "/otterdog team-info", identity="author")
    second = s.wait_comment(pr, marker="team-info", exclude=[first])
    _team_info_checks(s, pr, second.get("body") or "", author)
    s.wait_minimized(pr, first)
    assert not s.current_comment(pr, second).get("is_minimized"), "the new team-info comment is minimized"


@pytest.mark.scenario("W-CMD-VALIDATE-INFO", priority="P2")
@pytest.mark.tags("webapp", "secrets")
def test_validate_info_command(webapp_scenario: WebappScenario) -> None:
    """A dummy repository secret (Info "only has a dummy value"): the default validation only counts the infos,
    ``/otterdog validate info`` prints them; the default comment is minimized."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name = s.run_ctx.const("w-info")
    pr = s.open_pr(s.render(repositories=[s.patch(s.harmless_repo, s.secret(name, "********"))]))
    s.wait_validation(pr)
    first = s.wait_comment(pr, marker="validate")
    body = first.get("body") or ""
    assert not comment_contains(body, DUMMY_INFO), f"the default validation prints Info messages: {body[:2000]!r}"
    hint = texts.INFOS_HINT_RE.search(normalize_comment(body))
    assert hint and int(hint.group("infos")) >= 1, f"the default validation does not count the infos: {body[:2000]!r}"

    s.flow.comment(pr, "/otterdog validate info")
    second = s.wait_comment(pr, marker="validate", exclude=[first])
    info_body = second.get("body") or ""
    assert comment_contains(info_body, f"{texts.DIFF_FOR} {pr.head_sha}"), "the info validation is not for the head"
    assert comment_contains(info_body, f'repo_secret[name="{name}"] {DUMMY_INFO}'), (
        f"/otterdog validate info does not print the Info of {name} (SUT): {info_body[:2500]!r}"
    )
    assert not texts.INFOS_HINT_RE.search(normalize_comment(info_body)), "infos still hidden at INFO level (SUT)"
    s.wait_minimized(pr, first)
    status = s.wait_validation(pr)
    assert status.get("description") == texts.VALIDATION_SUCCESS, f"the info validation must succeed: {status}"


@pytest.mark.scenario("W-CMD-NEG", priority="P1")
@pytest.mark.tags("webapp", "webhooks-app")
@pytest.mark.timeout(1800, func_only=True)  # seven comment rounds, each settled before the next
def test_comment_matching_and_edits(
    webapp_scenario: WebappScenario, injector: WebhookInjector, installation_id: int
) -> None:
    """re.match at the start of the body: 'please /otterdog help' is ignored, '/otterdog   validate' validates,
    '/otterdog helpme ...' helps, a second line is ignored; an edit into a command runs it, a deletion is ignored;
    synthetic issue comments and comments of another repository schedule nothing."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.harmless_text())
    s.wait_settled(pr)
    help_1 = s.wait_comment(pr, marker="help")
    validate_1 = s.wait_comment(pr, marker="validate")
    s.quiesce()

    seen, at = s.bot_comment_ids(pr), s.now()
    plain = s.flow.comment(pr, "please /otterdog help")
    s.settle(pr, event="issue_comment", action="created", after=at)
    assert not s.new_bot_comments(pr, seen), "a command that does not start the comment ran (SUT)"

    s.flow.comment(pr, "/otterdog   validate")
    validate_2 = s.wait_comment(pr, marker="validate", exclude=[validate_1])
    assert comment_contains(validate_2.get("body") or "", f"{texts.DIFF_FOR} {pr.head_sha}"), "validate (spaces)"
    s.wait_minimized(pr, validate_1)

    s.flow.comment(pr, "/otterdog helpme, the rest of the comment is ignored")
    help_2 = s.wait_comment(pr, marker="help", exclude=[help_1])
    assert comment_contains(help_2.get("body") or "", texts.HELP), "'/otterdog helpme' must run help (prefix match)"
    s.wait_minimized(pr, help_1)
    s.quiesce()

    seen, at = s.bot_comment_ids(pr), s.now()
    s.flow.comment(pr, "/otterdog validate\n/otterdog help")
    s.settle(pr, event="issue_comment", action="created", after=at)  # before any wait consumes the delivery
    s.wait_comment(pr, marker="validate", exclude=[validate_1, validate_2])
    second_line = s.new_bot_comments(pr, seen, marker="help")
    assert not second_line, f"the command of the second line ran too (SUT): {second_line}"

    s.flow.edit_comment(pr, plain, "/otterdog help")
    help_3 = s.wait_comment(pr, marker="help", exclude=[help_1, help_2])
    assert comment_contains(help_3.get("body") or "", texts.HELP), "the edited comment did not run its command"
    s.wait_minimized(pr, help_2)
    s.quiesce()

    seen, at = s.bot_comment_ids(pr), s.now()
    s.flow.delete_comment(pr, plain)
    s.settle(pr, event="issue_comment", action="deleted", after=at)
    assert not s.new_bot_comments(pr, seen), "a deleted comment made the webapp react (SUT)"

    at = s.now()
    synthetic = {
        "issue of the config repo": issue_comment_payload(
            org=s.org,
            repo=s.repo,
            number=SYNTHETIC_NUMBER,
            body="/otterdog help",
            installation_id=installation_id,
            is_pull_request=False,
        ),
        "pull request of another repository": issue_comment_payload(
            org=s.org,
            repo=s.harmless_repo,
            number=SYNTHETIC_NUMBER + 1,
            body="/otterdog help",
            installation_id=installation_id,
        ),
    }
    for what, payload in synthetic.items():
        response = injector.send("issue_comment", payload)
        assert response.status_code == 204, f"the receiver refused the synthetic comment on an {what}"
    s.quiesce()
    stray = [
        task
        for task in s.api.tasks(org_id=s.org, type_="HelpCommentTask")
        if task.get("pull_request") in (SYNTHETIC_NUMBER, SYNTHETIC_NUMBER + 1)
    ]
    assert not stray, f"the webapp handled comments outside config-repo pull requests (SUT): {stray}"


@pytest.mark.scenario("W-SYNC-FAILURE", priority="P2")
@pytest.mark.tags("webapp", "teams", "repo")
@pytest.mark.known_bug("KB-040")
@pytest.mark.xfail(raises=MisleadingSyncFailureError, strict=False, reason="KB-040: misleading sync failure status")
def test_sync_check_crash(webapp_scenario: WebappScenario) -> None:
    """Main raises while it loads (team_permissions schema error, KB-032): the sync check of a PR and of
    ``/otterdog check-sync`` crash: status failure, no check-sync comment, failed tasks, in_sync never set. The
    failure description must not claim detected out-of-sync changes (KB-040)."""
    s = webapp_scenario
    broken = s.render(repositories=[s.patch(s.harmless_repo, s.schema_error())])
    s.flow.reset_main(broken, message=f"otterdog-e2e {s.run_ctx.run_id}: {s.sid} main raises while it loads")
    opened_at = s.now()
    pr = s.open_pr(s.harmless_text())

    first = s.wait_sync(pr)
    assert first.get("state") == "failure", f"a crashed sync check must fail its status (SUT): {first}"
    task = s.wait_task("CheckConfigurationInSyncTask", pr, after=opened_at)
    assert task.get("status") == "failed", f"the crashed sync task is not recorded as failed (SUT): {task}"
    s.quiesce()
    assert not s.flow.bot_comments(pr, marker="check-sync"), "a crashed sync check posted a check-sync comment"
    record = s.api_pull(pr) or {}
    assert record.get("in_sync") is None, f"a crashed sync check must not decide in_sync (SUT): {record}"

    commented_at = s.now()
    s.flow.comment(pr, "/otterdog check-sync")
    task = s.wait_task("CheckConfigurationInSyncTask", pr, after=commented_at, timeout=420.0)  # >= 60 s backoff
    assert task.get("status") == "failed", f"/otterdog check-sync on a broken main did not fail (SUT): {task}"
    second = s.wait_sync(pr)
    assert second.get("state") == "failure", f"status after /otterdog check-sync: {second}"
    s.write_evidence({"status": second, "task": task})
    description = str(second.get("description") or "")
    if "out of sync" in description:  # texts.SYNC_CRASH on every version so far
        raise MisleadingSyncFailureError(f"a crashed sync check is described as drift: {description!r}")


@pytest.mark.scenario("W-SYNC-INVALID-MAIN", priority="P2")
@pytest.mark.tags("webapp", "repo")
@pytest.mark.known_bug("KB-067")
@pytest.mark.xfail(
    raises=SyncCheckIgnoresValidationErrorsError,
    strict=False,
    reason="KB-067: a sync check of a main that fails validation reports the configuration as in sync",
)
def test_sync_check_of_an_invalid_main(webapp_scenario: WebappScenario) -> None:
    """Main declares a repository with an invalid topic (validation error): the sync plan of main aborts before
    comparing anything with GitHub, so the sync check cannot tell whether the org is in sync. otterdog's callback
    sees an empty diff and reports "completed successfully" / in_sync true; the valid PR head itself validates."""
    s, texts = webapp_scenario, webapp_scenario.texts
    invalid = s.run_repo("invalid-topic")
    main = s.render(repositories=[s.new_repo(invalid, s.describe("invalid topic, never applied"), s.invalid_topic())])
    s.flow.reset_main(main, message=f"otterdog-e2e {s.run_ctx.run_id}: {s.sid} main fails validation")
    pr = s.open_pr(s.harmless_text())  # valid head: removes the invalid repository again, changes a description

    status = s.wait_validation(pr)
    assert status.get("description") == texts.VALIDATION_SUCCESS, f"the PR head itself is valid: {status}"
    sync = s.wait_sync(pr)
    assert sync.get("state") in ("success", "failure"), f"no final sync status: {sync}"
    s.quiesce()
    record = s.api_pull(pr) or {}
    s.write_evidence({"sync": sync, "record": record})
    assert s.oracle.repo(invalid) is None, f"{invalid} of an invalid main must never exist"
    if sync.get("description") == texts.SYNC_SUCCESS or record.get("in_sync") is True:
        raise SyncCheckIgnoresValidationErrorsError(
            f"main fails validation, the sync check still says {sync.get('description')!r} / in_sync "
            f"{record.get('in_sync')!r}"
        )
