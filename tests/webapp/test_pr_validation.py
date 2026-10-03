"""PR validation by the webapp (SPEC 19, coverage areas webapp-events / webapp-pr): status, validate comment, records.

W-PR-VALID changes the description of a declared fixture repository: the validation status of the head sha goes
``pending`` then ``success``, the sync check ``pending`` then "otterdog sync check completed successfully" (the
baseline is in sync, so no check-sync comment), the validate comment shows the diff of that repository for that sha,
and the author (a user, not a bot) gets the help comment. W-PR-INVALID pushes a config with a syntax error: the status
ends ``error``, the validate comment carries the load failure and the webapp records the PR as invalid.

The battery adds the PR lifecycle and the content rules of a validation:

* W-PR-SYNCHRONIZE (P0): every new commit is validated again (new validate comment for its sha, the previous one
  minimized), the sync status of a commit pushed within an hour of the previous one is copied from it without a new
  sync run (no pending status, check_sync.py:91-124), and a broken last commit turns the status and record invalid;
* W-PR-DRAFT (P1): a draft is neither commented nor validated, ``ready_for_review`` triggers help, team-info,
  validation and sync check, ``converted_to_draft`` only updates the record;
* W-PR-REOPEN (P2): an unmerged close drops the record from /api (no ApplyChangesTask, no apply comment), a reopen
  validates the same head again;
* W-PR-EVAL-ERROR (P1): a configuration whose evaluation raises (an uncaught jsonschema error, KB-032) gets the
  friendly evaluation error instead of a traceback, status ``error``;
* W-PR-WARNINGS (P1): secrets and cost-related changes (#770, #771) are flagged in the validate comment and in the
  record and refused by ``/otterdog merge``, while a new repository with the default cache size stays auto-mergeable;
* W-PR-NO-CHANGES (P2): a PR touching only README.md is "No changes." and success, the org config plus README.md
  in one commit (a multi-file PR) is validated on its config change; neither is ever auto-mergeable;
* W-PR-IMPORT-CONFINEMENT (P1): an import outside the org directory is refused before any file is read;
* W-SYNC-PROPAGATION-DRIFT (P2, KB-066): the copied sync status of a new commit must keep an out-of-sync result.

Nothing here is merged: every PR is closed and its branch deleted by the webapp_case teardown.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.config_repo import comment_contains, normalize_comment

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.config_repo import ConfigPr
    from otterdog_e2e.github.mutate import Mutator

pytestmark = [pytest.mark.webapp]

FIX_771 = "476bf5ecc82fff626580e5808ba6b9f50062a6ab"  # Fix grammatic issues in validation warnings (#771)
FIX_770 = "c4f75eb3aaee64ddf62c7bb53e870f9f0c4454d9"  # Fix cost policy auto merge (#770, v1.6.1)
FIX_IMPORTS = "326d62d193712183df28fec3d7ecb4cae537fc91"  # Confine jsonnet imports to the org directory (v1.3.2)
# validate_pull_request.py:196-205; before #771 the warnings read "some of requested changes ..."
SECRETS_WARNING = "requested changes require secrets, need to apply these changes manually"
COST_WARNING = "requested changes may incur costs, need review by the designated team"
WORDING_771 = "some of the requested changes"
WORDING_BEFORE_771 = "some of requested changes"
IMPORT_REFUSED = "is not allowed"  # utils.py _make_jsonnet_import_callback: "import of '<path>' is not allowed"
IMPORT_ATTEMPTED = "can't resolve"  # what an unconfined evaluation of a missing import reports


class CostAutoMergeRegressionError(AssertionError):
    """Cost-related changes are handled like before otterdog#770 (c4f75eb): a new repository with the default cache
    size counts as cost-related, or the refusal of ``/otterdog merge`` does not name costs."""


class ImportConfinementRegressionError(AssertionError):
    """A jsonnet import outside the org directory was attempted (the confinement of v1.3.2 is missing)."""


class PropagatedSyncStatusError(AssertionError):
    """The sync status copied to a new commit claims "in sync" although the copied status reported drift."""


def _statuses(s: WebappScenario, pr: ConfigPr, context: str) -> list[tuple[str, str]]:
    """(state, description) of every ``context`` status of the PR head, oldest first."""
    return [
        (str(status.get("state")), str(status.get("description") or ""))
        for status in reversed(s.commit_statuses(pr.head_sha, context))
    ]


def _assert_one_propagated_sync_status(s: WebappScenario, pr: ConfigPr, copied: dict[str, object]) -> None:
    """The sync status of ``pr``'s head was copied from the previous commit: one final status, no pending one,
    with the state of the copied status."""
    statuses = _statuses(s, pr, "sync")
    assert len(statuses) == 1 and statuses[0][0] != "pending", (
        f"the sync check of {pr.head_sha[:12]}, pushed minutes after the previous commit, ran again instead of "
        f"copying the previous status (check_sync.py:91-124) (SUT): {statuses}"
    )
    assert statuses[0][0] == copied.get("state"), f"copied sync state {statuses[0]} != {copied} (SUT)"


@pytest.mark.scenario("W-PR-VALID", priority="P0")
@pytest.mark.tags("webapp", "repo", "smoke")
def test_valid_config_pr(webapp_scenario: WebappScenario) -> None:
    """Fixture repo description change: pending then success status on the head sha, validate comment naming the
    repository and the sha, help comment for the user author, in-sync sync status without check-sync comment, /api
    record valid and open."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.harmless_text())

    status = s.wait_validation(pr, state="success")
    assert texts.VALIDATION_SUCCESS_RE.search(status.get("description") or ""), f"unexpected status: {status}"

    validate = s.wait_comment(pr, marker="validate")
    body = validate.get("body") or ""
    assert comment_contains(body, texts.VALIDATE), f"validate comment without its heading: {body[:500]!r}"
    assert comment_contains(body, f"{texts.DIFF_FOR} {pr.head_sha}"), f"validate comment is not for {pr.head_sha}"
    assert comment_contains(body, s.harmless_repo), f"validate comment does not name {s.harmless_repo}: {body[:2000]!r}"
    assert "description" in normalize_comment(body), f"validate comment shows no description diff: {body[:2000]!r}"

    help_comment = s.wait_comment(pr, marker="help")
    assert comment_contains(help_comment.get("body") or "", texts.HELP), "help comment without its greeting"

    record = s.wait_api_pull(pr, until=lambda r: r.get("valid") is True, what="valid")
    assert record.get("status") == "open", f"/api record of an open PR: {record}"

    sync = s.wait_sync(pr)
    check_sync = s.flow.bot_comments(pr, marker="check-sync")
    assert sync.get("state") == "success" and sync.get("description") == texts.SYNC_SUCCESS, (
        f"the baseline org is in sync, the sync status says {sync} (SUT); "
        f"check-sync comment: {[(c.get('body') or '')[:1500] for c in check_sync]}"
    )
    assert not check_sync, "a check-sync comment was posted although the organization is in sync (SUT)"
    for context, pending, final in (
        ("validation", texts.VALIDATION_PENDING, texts.VALIDATION_SUCCESS),
        ("sync", texts.SYNC_PENDING, texts.SYNC_SUCCESS),
    ):
        statuses = _statuses(s, pr, context)
        assert statuses and statuses[0] == ("pending", pending), (
            f"the first {context} status of {pr.head_sha[:12]} must be pending {pending!r} (SUT): {statuses}"
        )
        assert statuses[-1] == ("success", final), f"the last {context} status must be {final!r} (SUT): {statuses}"


@pytest.mark.scenario("W-PR-INVALID", priority="P0")
@pytest.mark.tags("webapp", "template")
def test_invalid_config_pr(webapp_scenario: WebappScenario) -> None:
    """Config with a syntax error: error status, validate comment with the load failure, /api record invalid."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.syntax_error_text())

    status = s.wait_validation(pr, state="error")
    assert texts.VALIDATION_FAILED_RE.search(status.get("description") or ""), f"unexpected status: {status}"

    validate = s.wait_comment(pr, marker="validate")
    body = validate.get("body") or ""
    assert comment_contains(body, f"{texts.DIFF_FOR} {pr.head_sha}"), f"validate comment is not for {pr.head_sha}"
    assert texts.LOAD_FAILURE_RE.search(normalize_comment(body)), f"no load failure in the comment: {body[:2000]!r}"

    s.wait_api_pull(pr, until=lambda r: r.get("valid") is False, what="invalid")


@pytest.mark.scenario("W-PR-SYNCHRONIZE", priority="P0")
@pytest.mark.tags("webapp", "repo", "template")
def test_new_commits_are_validated_again(webapp_scenario: WebappScenario) -> None:
    """Three commits: each head gets its own validation and validate comment (the previous one minimized); the sync
    status of commits 2 and 3 is copied from the previous commit; the broken third commit makes the PR invalid."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.harmless_text())
    s.wait_validation(pr)
    first = s.wait_comment(pr, marker="validate")
    first_sync = s.wait_sync(pr)
    assert _statuses(s, pr, "sync")[0][0] == "pending", "the sync check of the first commit did not run (SUT)"

    second_description = s.describe("second commit")
    second_pr = s.flow.push_commit(
        pr,
        s.text(overrides={s.harmless_repo: second_description}),
        message=f"e2e {s.run_ctx.run_id} {s.sid}: second valid change",
    )
    status = s.wait_validation(second_pr)
    assert status.get("description") == texts.VALIDATION_SUCCESS, f"validation of the second commit: {status}"
    second = s.wait_comment(second_pr, marker="validate")
    body = second.get("body") or ""
    assert comment_contains(body, f"{texts.DIFF_FOR} {second_pr.head_sha}"), (
        f"the validate comment after the push is not for {second_pr.head_sha} (SUT): {body[:1500]!r}"
    )
    assert comment_contains(body, second_description), "the new validate comment does not show the new description"
    s.wait_minimized(second_pr, first)
    second_sync = s.wait_sync(second_pr)
    _assert_one_propagated_sync_status(s, second_pr, first_sync)
    assert second_sync.get("description") == first_sync.get("description"), (
        f"copied sync description {second_sync.get('description')!r} != {first_sync.get('description')!r} (SUT)"
    )

    third_pr = s.flow.push_commit(
        second_pr, s.syntax_error_text(), message=f"e2e {s.run_ctx.run_id} {s.sid}: broken last commit"
    )
    status = s.wait_validation(third_pr, state="error")
    assert status.get("description") == texts.VALIDATION_ERROR, f"validation of the broken commit: {status}"
    third = s.wait_comment(third_pr, marker="validate")
    body = third.get("body") or ""
    assert comment_contains(body, f"{texts.DIFF_FOR} {third_pr.head_sha}"), f"not the comment of {third_pr.head_sha}"
    assert texts.LOAD_FAILURE_RE.search(normalize_comment(body)), f"no load failure in the comment: {body[:2000]!r}"
    s.wait_minimized(third_pr, second)
    assert not s.current_comment(third_pr, third).get("is_minimized"), "the newest validate comment is minimized"
    s.wait_api_pull(third_pr, until=lambda r: r.get("valid") is False, what="invalid after the broken commit")
    s.wait_sync(third_pr)
    _assert_one_propagated_sync_status(s, third_pr, second_sync)


@pytest.mark.scenario("W-PR-DRAFT", priority="P1")
@pytest.mark.tags("webapp", "repo")
def test_draft_pr_lifecycle(webapp_scenario: WebappScenario) -> None:
    """Draft: record only (draft true), no comment, no status. Ready: help, team-info and validate comments, success,
    sync check, draft false. Converted back: draft true again, no new comment and no new status."""
    s, texts = webapp_scenario, webapp_scenario.texts
    opened_at = s.now()
    pr = s.open_pr(s.harmless_text(), draft=True)
    s.settle(pr, event="pull_request", action="opened", after=opened_at)
    s.wait_api_pull(pr, until=lambda r: r.get("draft") is True and r.get("status") == "open", what="draft and open")
    assert not s.flow.bot_comments(pr), f"the webapp commented a draft PR (SUT): {s.flow.bot_comments(pr)}"
    for context in ("validation", "sync"):
        assert not s.commit_statuses(pr.head_sha, context), f"a draft PR got a {context} status (SUT)"

    s.flow.mark_ready(pr)
    s.wait_validation(pr)
    validate = s.wait_comment(pr, marker="validate")
    assert comment_contains(validate.get("body") or "", f"{texts.DIFF_FOR} {pr.head_sha}"), "validate comment sha"
    help_comment = s.wait_comment(pr, marker="help")
    assert comment_contains(help_comment.get("body") or "", texts.HELP), "help comment without its greeting"
    team_info = s.wait_comment(pr, marker="team-info")
    assert texts.TEAM_INFO_RE.search(team_info.get("body") or ""), "team-info comment without the author's role"
    s.wait_sync(pr)
    s.wait_api_pull(pr, until=lambda r: r.get("draft") is False and r.get("valid") is True, what="ready and valid")

    seen = s.bot_comment_ids(pr)
    validation_statuses = s.commit_statuses(pr.head_sha, "validation")
    converted_at = s.now()
    s.flow.convert_to_draft(pr)
    s.settle(pr, event="pull_request", action="converted_to_draft", after=converted_at)
    s.wait_api_pull(pr, until=lambda r: r.get("draft") is True, what="draft again")
    assert not s.new_bot_comments(pr, seen), "converted_to_draft must only update the record (SUT)"
    assert s.commit_statuses(pr.head_sha, "validation") == validation_statuses, "converting to draft re-validated"


@pytest.mark.scenario("W-PR-REOPEN", priority="P2")
@pytest.mark.tags("webapp", "repo")
def test_closed_pr_is_validated_again_when_reopened(webapp_scenario: WebappScenario) -> None:
    """Closed without merge: gone from /api (status closed), no ApplyChangesTask, no apply comment. Reopened: open
    record again (not applied), a new validate comment for the same head, the previous one minimized."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.harmless_text())
    s.wait_settled(pr)
    first = s.wait_comment(pr, marker="validate")
    s.wait_api_pull(pr, until=lambda r: r.get("status") == "open", what="open")

    closed_at = s.now()
    s.flow.close(pr)
    s.settle(pr, event="pull_request", action="closed", after=closed_at)
    s.wait_api_pull_gone(pr, what="after its unmerged close")
    assert s.latest_task_created("ApplyChangesTask", pr) is None, "an unmerged PR was given to ApplyChangesTask (SUT)"
    applied = [c for c in s.flow.bot_comments(pr) if comment_contains(c.get("body") or "", texts.APPLY_RESULT)]
    assert not applied, f"apply comment on an unmerged PR (SUT): {applied}"

    s.flow.reopen(pr)
    s.wait_validation(pr)
    second = s.wait_comment(pr, marker="validate", exclude=[first])
    assert comment_contains(second.get("body") or "", f"{texts.DIFF_FOR} {pr.head_sha}"), "not the reopened head"
    s.wait_minimized(pr, first)
    record = s.wait_api_pull(pr, until=lambda r: r.get("status") == "open", what="open again after the reopen")
    assert record.get("apply_status") == "not_applied", f"a reopened PR was never applied: {record}"
    pending = [status for status in _statuses(s, pr, "validation") if status[0] == "pending"]
    assert len(pending) == 2, f"the reopen did not run a second validation of {pr.head_sha[:12]} (SUT): {pending}"


@pytest.mark.scenario("W-PR-EVAL-ERROR", priority="P1")
@pytest.mark.tags("webapp", "teams", "repo")
def test_evaluation_error_gets_a_friendly_comment(webapp_scenario: WebappScenario) -> None:
    """A team_permissions value outside the schema raises while the configuration loads (KB-032): the validate
    comment shows the friendly evaluation error (no exception text), status error, /api record invalid."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.render(repositories=[s.patch(s.harmless_repo, s.schema_error())]))

    status = s.wait_validation(pr, state="error")
    assert status.get("description") == texts.VALIDATION_ERROR, (
        f"an evaluation error is a failed validation, not a crashed task (SUT): {status}"
    )
    body = s.wait_comment(pr, marker="validate").get("body") or ""
    assert comment_contains(body, f"{texts.DIFF_FOR} {pr.head_sha}"), f"validate comment is not for {pr.head_sha}"
    assert comment_contains(body, texts.EVALUATION_ERROR) and comment_contains(body, texts.CONTACT_ADMIN), (
        f"the validate comment lacks the friendly evaluation error (SUT): {body[:2000]!r}"
    )
    leaked = [word for word in ("Traceback", "Failed validating", s.SCHEMA_ERROR_PERMISSION) if word in body]
    assert not leaked, f"the validate comment shows the raw evaluator output {leaked} (SUT): {body[:2000]!r}"
    s.wait_api_pull(pr, until=lambda r: r.get("valid") is False, what="invalid")


@pytest.mark.scenario("W-PR-WARNINGS", priority="P1")
@pytest.mark.tags("webapp", "secrets", "workflows", "repo")
@pytest.mark.timeout(1800, func_only=True)  # three PRs: validation, sync check and a refused merge each
def test_validation_warnings(request: pytest.FixtureRequest, webapp_scenario: WebappScenario) -> None:
    """Secret: secrets warning, manual apply, no auto-merge. Cost change: cost warning, no auto-merge, refused naming
    costs (#770). New repository with the default cache size: no warning, auto-merge offered (#770). The warnings
    use the wording of #771 on SUTs that include 476bf5e (the older one before, either when unknown)."""
    s, texts = webapp_scenario, webapp_scenario.texts
    s.xfail_unless_includes(
        request,
        FIX_770,
        error=CostAutoMergeRegressionError,
        reason="the webapp under test predates otterdog#770 (c4f75eb): default cache sizes count as costs",
        strict=True,  # merged upstream and released in v1.6.1
    )
    pin = s.patch(s.harmless_repo, s.cache(10))  # main and every head manage the cache size: the diffs are exact
    s.flow.reset_main(s.render(repositories=[pin]), message=f"otterdog-e2e {s.run_ctx.run_id}: {s.sid} pins cache")
    secret = s.patch(s.harmless_repo, s.secret(s.run_ctx.const("w-warn"), f"e2e-dummy-{s.run_ctx.run_id}"))
    cost = s.patch(s.harmless_repo, s.cache(5))
    new = s.new_repo(s.run_repo("default-cache"), s.describe("new repository, default cache size"), s.cache(10))
    secret_pr = s.open_pr(s.render(repositories=[pin, secret]), suffix="secret")
    cost_pr = s.open_pr(s.render(repositories=[pin, cost]), suffix="cost")
    new_pr = s.open_pr(s.render(repositories=[pin, new]), suffix="new-repo")

    included_771 = s.webapp_includes(FIX_771)
    for pr, warning in ((secret_pr, SECRETS_WARNING), (cost_pr, COST_WARNING)):
        s.wait_validation(pr)
        body = s.wait_comment(pr, marker="validate").get("body") or ""
        new_wording = comment_contains(body, f"{WORDING_771} {warning}")
        old_wording = comment_contains(body, f"{WORDING_BEFORE_771} {warning}")
        assert comment_contains(body, texts.WARNINGS_HEADING) and (new_wording or old_wording), (
            f"PR #{pr.number}: the validate comment does not warn {warning!r} (SUT): {body[-2500:]!r}"
        )
        if included_771 is not None:
            expected = WORDING_771 if included_771 else WORDING_BEFORE_771
            assert new_wording if included_771 else old_wording, (
                f"PR #{pr.number}: the webapp {'includes' if included_771 else 'predates'} #771 (476bf5e), the "
                f"warning must read {expected!r} (SUT): {body[-1500:]!r}"
            )
    s.wait_api_pull(
        secret_pr,
        until=lambda r: r.get("requires_manual_apply") is True and r.get("supports_auto_merge") is False,
        what="secret: manual apply, no auto-merge",
    )
    cost_record = s.wait_api_pull(cost_pr, until=lambda r: r.get("supports_auto_merge") is not None, what="decided")
    assert cost_record.get("supports_auto_merge") is False and cost_record.get("requires_manual_apply") is False, (
        f"a cost-related change needs a review but no manual apply (SUT): {cost_record}"
    )

    s.wait_validation(new_pr)
    new_body = s.wait_comment(new_pr, marker="validate").get("body") or ""
    if comment_contains(new_body, texts.WARNINGS_HEADING):
        raise CostAutoMergeRegressionError(f"a new repository with the default cache size got warnings: {new_body!r}")
    s.wait_api_pull(new_pr, until=lambda r: r.get("supports_auto_merge") is True, what="new repo: auto-mergeable")
    automerge = s.wait_comment(new_pr, marker="automerge")
    assert comment_contains(automerge.get("body") or "", texts.AUTOMERGE), "automerge comment without its offer"

    for pr in (secret_pr, cost_pr, new_pr):
        s.wait_sync(pr)
    s.quiesce()  # validation, team-info and sync tasks are done: none of them offered auto-merge
    for pr, reason in ((secret_pr, None), (cost_pr, texts.COST_REASON)):
        assert not s.flow.bot_comments(pr, marker="automerge"), f"PR #{pr.number}: auto-merge offered (SUT)"
        s.flow.comment(pr, "/otterdog merge")
        problems = s.wait_problems(pr)
        assert comment_contains(problems, texts.NOT_AUTO_MERGEABLE), f"refusal without its reason: {problems!r}"
        if reason is not None and not comment_contains(problems, reason):
            raise CostAutoMergeRegressionError(f"the refusal of PR #{pr.number} does not name costs: {problems!r}")
        s.assert_still_open(pr, "/otterdog merge was refused")
    s.write_evidence({"secret_pr": secret_pr.number, "cost_pr": cost_pr.number, "new_pr": new_pr.number})


@pytest.mark.scenario("W-PR-NO-CHANGES", priority="P2")
@pytest.mark.tags("webapp", "repo")
@pytest.mark.timeout(1800, func_only=True)  # two PRs, each validated, sync-checked and refused
def test_non_configuration_change(webapp_scenario: WebappScenario) -> None:
    """README.md only: "No changes." and success; the org config plus README.md in one commit (multi-file PR): the
    config diff is validated. Both are valid but never auto-mergeable (non-configuration file): no automerge
    comment, ``/otterdog merge`` refused naming that reason, the PRs stay open."""
    s, texts = webapp_scenario, webapp_scenario.texts
    readme = f"# otterdog e2e\n\nRun {s.run_ctx.run_id}, scenario {s.sid}: a change of a non-configuration file.\n"
    readme_pr = s.open_pr_files({"README.md": readme}, suffix="readme")
    multi_pr = s.open_pr_files({s.flow.config_path: s.harmless_text(), "README.md": readme}, suffix="multi")

    status = s.wait_validation(readme_pr)
    assert status.get("description") == texts.VALIDATION_SUCCESS, f"identical org config: {status}"
    body = s.wait_comment(readme_pr, marker="validate").get("body") or ""
    assert comment_contains(body, f"{texts.DIFF_FOR} {readme_pr.head_sha}"), "validate comment of the README PR"
    assert comment_contains(body, texts.NO_CHANGES), f"an unchanged org config must say 'No changes.' (SUT): {body!r}"
    status = s.wait_validation(multi_pr)
    assert status.get("description") == texts.VALIDATION_SUCCESS, f"multi-file PR validation: {status}"
    body = s.wait_comment(multi_pr, marker="validate").get("body") or ""
    assert comment_contains(body, s.harmless_repo) and not comment_contains(body, texts.NO_CHANGES), (
        f"the multi-file PR must be validated on its org config change (SUT): {body[:2000]!r}"
    )

    for pr in (readme_pr, multi_pr):
        record = s.wait_api_pull(pr, until=lambda r: r.get("supports_auto_merge") is not None, what="decided")
        assert record.get("valid") is True and record.get("supports_auto_merge") is False, (
            f"PR #{pr.number} touches README.md: valid but never auto-mergeable (SUT): {record}"
        )
        s.wait_sync(pr)
    s.quiesce()
    for pr in (readme_pr, multi_pr):
        assert not s.flow.bot_comments(pr, marker="automerge"), f"PR #{pr.number}: auto-merge offered (SUT)"
        s.flow.comment(pr, "/otterdog merge")
        problems = s.wait_problems(pr)
        assert comment_contains(problems, texts.NOT_AUTO_MERGEABLE) and comment_contains(
            problems, texts.NON_CONFIG_REASON
        ), f"the refusal of PR #{pr.number} does not name the non-configuration file: {problems!r}"
        s.assert_still_open(pr, "a non-configuration change is never auto-merged")


@pytest.mark.scenario("W-PR-IMPORT-CONFINEMENT", priority="P1")
@pytest.mark.tags("webapp", "template")
def test_imports_are_confined_to_the_org_directory(
    request: pytest.FixtureRequest, webapp_scenario: WebappScenario
) -> None:
    """A repository description imported from ``../<file>`` (outside the org directory): the import is refused
    before any read ("is not allowed", not "can't resolve"), the validation fails cleanly, /api record invalid."""
    s, texts = webapp_scenario, webapp_scenario.texts
    s.xfail_unless_includes(
        request,
        FIX_IMPORTS,
        error=ImportConfinementRegressionError,
        reason="the webapp under test predates the import confinement of v1.3.2 (326d62d)",
        strict=True,
    )
    outside = f"../{s.run_repo('outside')}.libsonnet"  # resolves next to the org directory, exists nowhere
    pr = s.open_pr(s.render(repositories=[s.patch(s.harmless_repo, f"description: importstr {json.dumps(outside)}")]))

    status = s.wait_validation(pr, state="error")
    assert status.get("description") == texts.VALIDATION_ERROR, f"a refused import fails the validation: {status}"
    body = s.wait_comment(pr, marker="validate").get("body") or ""
    plain = normalize_comment(body)
    assert comment_contains(body, f"{texts.DIFF_FOR} {pr.head_sha}"), f"validate comment is not for {pr.head_sha}"
    if IMPORT_ATTEMPTED in plain:
        raise ImportConfinementRegressionError(f"the webapp tried to read {outside}: {body[:2000]!r}")
    assert texts.LOAD_FAILURE_RE.search(plain) and IMPORT_REFUSED in plain and outside in plain, (
        f"the validate comment does not report the refused import of {outside} (SUT): {body[:2000]!r}"
    )
    s.wait_api_pull(pr, until=lambda r: r.get("valid") is False, what="invalid")


@pytest.mark.scenario("W-SYNC-PROPAGATION-DRIFT", priority="P2")
@pytest.mark.tags("webapp", "repo")
@pytest.mark.known_bug("KB-066")
@pytest.mark.xfail(
    raises=PropagatedSyncStatusError,
    strict=False,
    reason="KB-066: a sync status copied to a new commit always reads 'completed successfully'",
)
def test_out_of_sync_status_survives_a_new_commit(webapp_scenario: WebappScenario, mutator: Mutator) -> None:
    """Drifted org, PR out of sync; a second commit pushed within the hour copies the previous sync status. The
    copy must keep "otterdog sync check failed" and /api in_sync false: the state of both outcomes is success, so
    otterdog's copy (state == success -> in sync) turns the drift into "completed successfully"."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name = s.run_repo()
    declared, live = s.describe("declared"), s.describe("drifted")
    s.declare_live({name: declared})
    mutator.patch_repo(name, description=live)  # the drift: GitHub no longer matches config repo main

    pr = s.open_pr(s.harmless_text(repos={name: declared}))
    drift = s.wait_check_sync_comment(pr)
    assert comment_contains(drift.get("body") or "", name), "the check-sync comment does not name the drifted repo"
    first = s.wait_sync(pr)
    assert first.get("description") == texts.SYNC_OUT_OF_SYNC, f"out-of-sync status of the first commit: {first}"
    s.wait_api_pull(pr, until=lambda r: r.get("in_sync") is False, what="out of sync")

    second_pr = s.flow.push_commit(
        pr,
        s.text(repos={name: declared}, overrides={s.harmless_repo: s.describe("second commit")}),
        message=f"e2e {s.run_ctx.run_id} {s.sid}: second commit within the hour",
    )
    s.wait_validation(second_pr)
    copied = s.wait_sync(second_pr)
    _assert_one_propagated_sync_status(s, second_pr, first)
    s.quiesce()
    record = s.api_pull(second_pr) or {}
    s.write_evidence({"first": first, "copied": copied, "record": record})
    if copied.get("description") != texts.SYNC_OUT_OF_SYNC or record.get("in_sync") is not False:
        raise PropagatedSyncStatusError(
            f"the sync status copied to {second_pr.head_sha[:12]} hides the drift of {name}: "
            f"{copied.get('description')!r}, /api in_sync {record.get('in_sync')!r}"
        )
