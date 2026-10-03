"""Merged config PRs are applied by the webapp (SPEC 19, coverage areas webapp-pr / webapp-automerge / webapp-events).

W-MERGE-APPLY: a PR adding the run repository e2e-<run>-w-apply is squash-merged by the admin once validated;
the apply comment reports success and names the repository, the repository exists on GitHub with the declared
description, /api lists the PR as merged and completed, and the push of the merge to main is fetched again
(FetchConfigTask; /api/organizations/<org> holds the new repository).
W-AUTOMERGE: the author (contributors team only) opens the PR, the approver (approval team) approves, the webapp
offers auto-merge, the author comments ``/otterdog merge``, the webapp merges and applies.
W-REBASE-MULTI (P1, regression otterdog#773): a two-commit PR (one new run repository per commit) is rebase-merged;
both commits are applied. Webapps predating the fix (ba3d1f9, not in v1.6.1) apply only the last commit: there the
test is a strict xfail limited to that regression.

The battery adds the other merge methods, removals, partial and failed applies and the auto-merge rules:

* W-MERGE-COMMIT-APPLY (P0): a merge commit applies both commits (base = first parent);
* W-PR-CLOSED (P0): unmerged closes and merges into another branch than the default one are never applied;
* W-MERGE-DELETE (P0): a merged removal deletes the repository (delete_resources=True); removals never auto-merge;
* W-MERGE-SECRET (P1): a secret is never applied by the webapp (partially_applied); ``/otterdog done`` and
  ``/otterdog apply`` of a contributor get the wrong-team comments, the admin's ``/otterdog done`` completes it;
* W-CMD-APPLY (P1): a failing apply (the repository exists already) is retried with ``/otterdog apply`` by an admin
  after the cause was removed; a contributor's retry is refused, a retry of a completed PR does nothing;
* W-MERGE-APPLY-CRASH (P1): a local-apply that raises (KB-039 as the trigger) gets the friendly "Applying the
  configuration failed." comment (no exception text), apply_status partially_applied;
* W-MERGE-INVALID (P1): an invalid PR merged through the API is never applied (no comment, not_applied);
* W-AUTOMERGE-AUTHOR-TEAM (P0): an approval-team author auto-merges without review; an invalid PR is refused;
* W-AUTOMERGE-THIRD-PARTY (P1): ``/otterdog merge`` by an outsider is refused, by the approver accepted;
* W-AUTOMERGE-DISMISS (P1): requested changes and a dismissed approval leave the PR without required approvals;
* W-AUTOMERGE-DRIFT (P1, regression v1.1.0/v1.2.0): a drifted org still auto-merges and the apply leaves the drift;
* W-MERGE-TEAM-HOOK (P2, regression v1.0.1 #325, KB-068): the webapp's local-apply updates a team (strict) and
  a webhook declared with a wildcard url, which must keep its live url (otterdog PATCHes the pattern as the url).

Every run repository and run team is removed by the webapp_case teardown (main back to the baseline, guarded
``apply -d -r e2e-<run>-*`` with the trusted reset CLI).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.config_repo import comment_contains

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.config_repo import ConfigPr
    from otterdog_e2e.github.mutate import Mutator

pytestmark = [pytest.mark.webapp]

FIX_773 = "ba3d1f9f1595c0b40b246c20f8d49420596e305c"  # fix: apply all commits of rebase-merged pull requests (#773)


class RebaseRegressionError(AssertionError):
    """Only the last commit of a rebase-merged PR was applied (otterdog#773)."""


class WildcardWebhookUpdateError(AssertionError):
    """A change of a webhook declared with a wildcard url lost the live url (or failed to apply)."""


@pytest.mark.scenario("W-MERGE-APPLY", priority="P0")
@pytest.mark.tags("webapp", "repo", "smoke")
def test_merge_applies_config(webapp_scenario: WebappScenario) -> None:
    """Admin squash merge of a validated PR: apply comment, repository created, /api merged + completed, the push of
    the merge fetched again (FetchConfigTask, stored configuration with the new repository)."""
    s = webapp_scenario
    name, description = s.run_ctx.name("w-apply"), s.describe("created by the webapp apply")  # SPEC 19 name
    pr = s.open_pr(s.text(repos={name: description}))
    s.wait_settled(pr)
    validate = s.wait_comment(pr, marker="validate")
    assert comment_contains(validate.get("body") or "", name), f"the validation plan does not add {name}"

    merged_at = s.now()
    s.flow.merge(pr, method="squash")
    pull = s.wait_merged(pr)
    applied = s.wait_applied(pr)
    assert comment_contains(applied.get("body") or "", name), f"the apply comment does not name {name}"

    repo = s.wait_repo(name)
    assert repo.get("description") == description, f"{name} description on GitHub: {repo.get('description')!r}"

    record = s.wait_api_pull(
        pr,
        until=lambda r: r.get("status") == "merged" and r.get("apply_status") == "completed",
        what="merged and completed",
    )
    assert record.get("merged_at"), f"/api record of a merged PR without merged_at: {record}"
    merged = {
        (r.get("id") or {}).get("pull_request") for r in s.api.merged_pull_requests(org_id=s.org, repo_name=s.repo)
    }
    assert pr.number in merged, f"/api/pullrequests/merged does not list PR #{pr.number}"

    s.wait_push(str(pull.get("merge_commit_sha") or ""))  # the push of the merge reached the webapp (infra)
    fetch = s.wait_repo_task("FetchConfigTask", after=merged_at)
    assert fetch.get("status") == "finished", f"the push of the merge was not fetched (SUT): {fetch}"
    stored = s.reaction(
        lambda: s.api.organization(s.org),
        until=lambda config: name in s.stored_repositories(config),
        what=f"/api/organizations/{s.org} lists {name}",
        timeout=120,
    )
    assert s.stored_repositories(stored)[name].get("description") == description, "stored description"


@pytest.mark.scenario("W-AUTOMERGE", priority="P0")
@pytest.mark.tags("webapp", "teams", "repo")
@pytest.mark.identities("author", "approver")
def test_automerge_after_approval(webapp_scenario: WebappScenario) -> None:
    """Contributor PR: no auto-merge offer before approval, automerge comment after it, ``/otterdog merge`` by the
    author merges and applies."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name, description = s.run_repo(), s.describe("auto-merged by the webapp")
    pr = s.open_pr(s.text(repos={name: description}), identity="author")
    s.wait_settled(pr)
    s.quiesce()
    early = s.flow.bot_comments(pr, marker="automerge")
    assert not early, "auto-merge offered before any approval: the author identity must be a contributor only"

    s.flow.approve(pr, identity="approver")
    automerge = s.wait_comment(pr, marker="automerge")
    assert comment_contains(automerge.get("body") or "", texts.AUTOMERGE), "automerge comment without its offer"

    s.flow.comment(pr, "/otterdog merge", identity="author")
    s.wait_merged(pr)
    applied = s.wait_applied(pr)
    assert comment_contains(applied.get("body") or "", name), f"the apply comment does not name {name}"
    s.wait_repo(name)


@pytest.mark.scenario("W-REBASE-MULTI", priority="P1")
@pytest.mark.tags("webapp", "repo")
def test_rebase_merge_applies_every_commit(request: pytest.FixtureRequest, webapp_scenario: WebappScenario) -> None:
    """Two commits, rebase merge: the repositories of both commits are created and named by the apply comment."""
    s = webapp_scenario
    s.xfail_unless_includes(
        request,
        FIX_773,
        error=RebaseRegressionError,
        reason="the webapp under test predates otterdog#773 (ba3d1f9): a rebase merge applies its last commit only",
        strict=True,  # merged upstream: every later version descends from ba3d1f9
    )
    first, second = s.run_repo("1"), s.run_repo("2")
    one, two = s.describe("first commit"), s.describe("second commit")
    pr = s.open_pr([s.text(repos={first: one}), s.text(repos={first: one, second: two})])
    s.wait_settled(pr)

    s.flow.merge(pr, method="rebase")
    s.wait_merged(pr)
    body = s.wait_applied(pr).get("body") or ""
    s.wait_repo(second)  # the last commit is applied by every version
    checks = {
        f"repository {first} exists": s.oracle.repo(first) is not None,
        f"the apply comment names {first}": comment_contains(body, first),
    }
    missing = [what for what, ok in checks.items() if not ok]
    if missing:
        raise RebaseRegressionError(f"the first commit of rebase-merged PR #{pr.number} was not applied: {missing}")
    assert comment_contains(body, second), f"the apply comment does not name {second}"


@pytest.mark.scenario("W-MERGE-COMMIT-APPLY", priority="P0")
@pytest.mark.tags("webapp", "repo")
def test_merge_commit_applies_every_commit(webapp_scenario: WebappScenario) -> None:
    """Two commits merged with a merge commit: the base of the apply is the first parent, so the repositories of both
    commits are created and named by the apply comment; /api completed."""
    s = webapp_scenario
    first, second = s.run_repo("1"), s.run_repo("2")
    one, two = s.describe("first commit"), s.describe("second commit")
    pr = s.open_pr([s.text(repos={first: one}), s.text(repos={first: one, second: two})])
    s.wait_settled(pr)

    s.flow.merge(pr, method="merge")
    pull = s.wait_merged(pr)
    merge_commit = s.oracle.git_commit(s.repo, str(pull.get("merge_commit_sha") or ""))
    parents = (merge_commit or {}).get("parents") or []
    assert len(parents) == 2, f"merge method 'merge' must create a merge commit: {merge_commit}"
    body = s.wait_applied(pr).get("body") or ""
    for name, description in ((first, one), (second, two)):
        assert comment_contains(body, name), f"the apply comment does not name {name} (SUT): {body[:2000]!r}"
        repo = s.wait_repo(name)
        assert repo.get("description") == description, f"{name} description on GitHub: {repo.get('description')!r}"
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "completed", what="completed")


@pytest.mark.scenario("W-PR-CLOSED", priority="P0")
@pytest.mark.tags("webapp", "repo")
def test_closed_prs_are_never_applied(webapp_scenario: WebappScenario) -> None:
    """A PR closed without merge leaves /api (status closed) without ApplyChangesTask or apply comment; a PR merged
    into another branch than the default one is recorded as merged but never applied (webhook/__init__.py:176-178):
    no ApplyChangesTask, no apply comment, its repository is not created."""
    s, texts = webapp_scenario, webapp_scenario.texts
    closed_repo, side_repo = s.run_repo("closed"), s.run_repo("side")
    pr = s.open_pr(s.text(repos={closed_repo: s.describe("closed, never applied")}), suffix="closed")
    s.wait_settled(pr)
    closed_at = s.now()
    s.flow.close(pr)
    s.settle(pr, event="pull_request", action="closed", after=closed_at)
    s.wait_api_pull_gone(pr, what="after its unmerged close")
    assert s.latest_task_created("ApplyChangesTask", pr) is None, "an unmerged PR was given to ApplyChangesTask (SUT)"
    assert not [c for c in s.flow.bot_comments(pr) if comment_contains(c.get("body") or "", texts.APPLY_RESULT)]
    assert s.oracle.repo(closed_repo) is None, f"{closed_repo} of an unmerged PR exists (SUT)"

    side: ConfigPr | None = None
    base: str | None = None
    try:
        side, base = s.open_side_pr(s.text(repos={side_repo: s.describe("merged into a side branch")}), suffix="side")
        s.wait_validation(side)  # validated like every config PR (against main)
        s.wait_sync(side)
        merged_at = s.now()
        s.flow.mutators["admin"].merge_pull(s.repo, side.number, method="squash", sha=side.head_sha)
        s.flow.wait_delivery(side, event="pull_request", action="closed", after=merged_at)
        s.quiesce()
        record = s.wait_api_pull(side, until=lambda r: r.get("status") == "merged", what="merged into its base")
        assert record.get("apply_status") == "not_applied", f"a PR merged into {base} was applied: {record}"
        assert s.latest_task_created("ApplyChangesTask", side) is None, f"ApplyChangesTask for a PR into {base} (SUT)"
        applied = [c for c in s.flow.bot_comments(side) if comment_contains(c.get("body") or "", texts.APPLY_RESULT)]
        assert not applied, f"apply comment on a PR merged into {base} (SUT): {applied}"
        assert s.oracle.repo(side_repo) is None, f"{side_repo} of a PR merged into {base} exists (SUT)"
    finally:
        s.remove_side_pr(side, base)


@pytest.mark.scenario("W-MERGE-DELETE", priority="P0")
@pytest.mark.tags("webapp", "repo")
def test_merged_removal_is_applied(webapp_scenario: WebappScenario) -> None:
    """A PR removing a declared run repository: the validation shows the removal, auto-merge is never offered and
    ``/otterdog merge`` refused (deletions); the admin's merge deletes the repository on GitHub."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name = s.run_repo()
    s.declare_live({name: s.describe("removed by a merged PR")})
    pr = s.open_pr(s.text())  # the baseline: main without the run repository
    s.wait_settled(pr)
    body = s.wait_comment(pr, marker="validate").get("body") or ""
    assert comment_contains(body, f'remove repository[name="{name}"]'), (
        f"the validate comment does not show the removal of {name} (SUT): {body[:2000]!r}"
    )
    s.wait_api_pull(pr, until=lambda r: r.get("supports_auto_merge") is False, what="deletion: no auto-merge")
    s.quiesce()
    assert not s.flow.bot_comments(pr, marker="automerge"), "auto-merge offered for a deletion (SUT)"
    s.flow.comment(pr, "/otterdog merge")
    problems = s.wait_problems(pr)
    assert comment_contains(problems, texts.NOT_AUTO_MERGEABLE), f"refusal without its reason: {problems!r}"
    s.assert_still_open(pr, "deletions are never auto-merged")

    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    applied = s.wait_applied(pr).get("body") or ""
    assert comment_contains(applied, f'remove repository[name="{name}"]'), (
        f"the apply comment does not name the removal of {name} (SUT): {applied[:2000]!r}"
    )
    s.reaction(lambda: s.oracle.repo(name), until=lambda repo: repo is None, what=f"{name} deleted", timeout=120)
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "completed", what="completed")


@pytest.mark.scenario("W-MERGE-SECRET", priority="P1")
@pytest.mark.tags("webapp", "secrets", "repo", "teams")
@pytest.mark.identities("author")
def test_secret_needs_a_manual_apply(webapp_scenario: WebappScenario) -> None:
    """A new run repository with a secret, merged by the admin: the webapp creates the repository but never the
    secret (partially_applied, "only partially applied"); a contributor's ``/otterdog done`` and ``/otterdog apply``
    get the wrong-team comments and change nothing; the admin's ``/otterdog done`` completes the PR."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name, secret = s.run_repo(), s.run_ctx.const("w-merge-secret")
    fields = s.secret(secret, f"e2e-dummy-{s.run_ctx.run_id}")
    pr = s.open_pr(s.render(repositories=[s.new_repo(name, s.describe("repository with a secret"), fields)]))
    s.wait_settled(pr)
    s.wait_api_pull(
        pr,
        until=lambda r: r.get("requires_manual_apply") is True and r.get("supports_auto_merge") is False,
        what="manual apply, no auto-merge",
    )

    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    applied = s.wait_applied(pr).get("body") or ""
    assert comment_contains(applied, name) and comment_contains(applied, texts.PARTIAL_APPLY), (
        f"the apply comment must create {name} and report a partial apply (SUT): {applied[:2500]!r}"
    )
    s.wait_repo(name)
    assert s.oracle.repo_secret(name, secret) is None, f"the webapp must never apply the secret {secret} (SUT)"
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "partially_applied", what="partially applied")

    admin_teams = f"{s.org}/{s.target.admin_team}"
    for command, text in (("/otterdog done", texts.WRONG_TEAM_DONE), ("/otterdog apply", texts.WRONG_TEAM_APPLY)):
        s.flow.comment(pr, command, identity="author")
        refused = s.wait_comment(pr, contains=text).get("body") or ""
        assert comment_contains(refused, admin_teams), f"{command} refusal does not name {admin_teams}: {refused!r}"
        s.quiesce()
        record = s.api_pull(pr) or {}
        assert record.get("apply_status") == "partially_applied", f"{command} by a contributor changed {record}"

    s.flow.comment(pr, "/otterdog done")
    s.wait_comment(pr, contains=texts.DONE)
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "completed", what="completed by /otterdog done")
    assert s.oracle.repo_secret(name, secret) is None, "/otterdog done must not apply anything"


@pytest.mark.scenario("W-CMD-APPLY", priority="P1")
@pytest.mark.tags("webapp", "repo", "teams")
@pytest.mark.identities("author")
@pytest.mark.timeout(1800, func_only=True)  # merge, failed apply, refused retry, successful retry, no-op retry
def test_failed_apply_is_retried_by_an_admin(webapp_scenario: WebappScenario, mutator: Mutator) -> None:
    """The PR adds a repository that already exists on GitHub (created out of band): the apply fails ([!CAUTION],
    'failed to apply patch', apply_status partially_applied). ``/otterdog apply`` by a contributor is refused; once
    the repository is gone the admin's ``/otterdog apply`` creates it (completed); another one does nothing."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name, declared = s.run_repo(), s.describe("created by the retried apply")
    mutator.create_repo(name, description=s.describe("created out of band before the merge"))
    s.wait_repo(name)
    pr = s.open_pr(s.text(repos={name: declared}))
    s.wait_settled(pr)

    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    failed = s.wait_comment(pr, contains=texts.APPLY_RESULT)
    body = failed.get("body") or ""
    assert comment_contains(body, texts.APPLY_FAILURE) and comment_contains(body, texts.PATCH_FAILURE), (
        f"the apply of an existing repository must fail (SUT): {body[:2500]!r}"
    )
    assert comment_contains(body, name), f"the failed apply does not name {name}: {body[:2500]!r}"
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "partially_applied", what="failed apply recorded")

    s.flow.comment(pr, "/otterdog apply", identity="author")
    refused = s.wait_comment(pr, contains=texts.WRONG_TEAM_APPLY).get("body") or ""
    assert comment_contains(refused, f"{s.org}/{s.target.admin_team}"), f"refusal without the admin team: {refused!r}"
    s.quiesce()
    assert (s.api_pull(pr) or {}).get("apply_status") == "partially_applied", "a refused apply changed the record"

    mutator.delete_repo(name)  # the cause of the failure, removed out of band
    s.reaction(lambda: s.oracle.repo(name), until=lambda repo: repo is None, what=f"{name} deleted", timeout=120)
    s.flow.comment(pr, "/otterdog apply")
    retried = s.wait_applied(pr, exclude=[failed])
    assert comment_contains(retried.get("body") or "", name), f"the retried apply does not name {name}"
    repo = s.wait_repo(name)
    assert repo.get("description") == declared, f"{name} was not created by the retried apply: {repo}"
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "completed", what="completed by /otterdog apply")

    seen, at = s.bot_comment_ids(pr), s.now()
    s.flow.comment(pr, "/otterdog apply")
    s.settle(pr, event="issue_comment", action="created", after=at)
    task = s.wait_task("ApplyChangesTask", pr, after=at)
    assert task.get("status") == "finished", f"/otterdog apply of a completed PR must be skipped, not fail: {task}"
    assert not s.new_bot_comments(pr, seen), "/otterdog apply of a completed PR applied again (SUT)"


@pytest.mark.scenario("W-MERGE-APPLY-CRASH", priority="P1")
@pytest.mark.tags("webapp", "rulesets", "repo")
def test_crashing_apply_gets_a_friendly_comment(webapp_scenario: WebappScenario) -> None:
    """A merged PR whose local-apply raises (the trigger is KB-039: a ``#Admin`` bypass actor validates, building the
    ruleset payload raises KeyError): the apply comment is the [!CAUTION] one with the friendly "Applying the
    configuration failed." instead of the exception, apply_status partially_applied (FAILED is only used for
    exceptions outside the local-apply); the repository patch before the crash is applied, the ruleset is not."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name, ruleset = s.run_repo(), s.run_repo("rs")
    fields = (
        f"rulesets: [orgs.newRepoRuleset({json.dumps(ruleset)}) "
        '{ bypass_actors: ["#Admin"], required_status_checks: null }]'
    )
    pr = s.open_pr(s.render(repositories=[s.new_repo(name, s.describe("ruleset whose apply raises"), fields)]))
    status = s.wait_validation(pr, state=None)
    if status.get("state") != "success":
        pytest.skip(f"the '#Admin' bypass actor no longer validates (KB-039 fixed?): {status}")
    s.wait_sync(pr)

    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    body = s.wait_comment(pr, contains=texts.APPLY_RESULT).get("body") or ""
    if comment_contains(body, texts.APPLY_SUCCESS) and not comment_contains(body, texts.APPLY_FAILURE):
        pytest.skip("the apply of the '#Admin' bypass actor no longer raises (KB-039 fixed?)")
    assert comment_contains(body, texts.APPLY_CRASH) and comment_contains(body, texts.CONTACT_ADMIN), (
        f"a crashing apply must get the friendly message (SUT): {body[:2500]!r}"
    )
    leaked = [word for word in ("KeyError", "Traceback", "#Admin") if word in body]
    assert not leaked, f"the apply comment shows the raw exception {leaked} (SUT): {body[:2500]!r}"
    s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "partially_applied", what="crashed apply recorded")
    s.wait_repo(name)  # the patch before the crash
    assert s.oracle.repo_ruleset(name, ruleset) is None, f"the ruleset {ruleset} of the crashed patch exists"


@pytest.mark.scenario("W-MERGE-INVALID", priority="P1")
@pytest.mark.tags("webapp", "repo")
def test_invalid_merged_pr_is_not_applied(webapp_scenario: WebappScenario) -> None:
    """A PR failing validation (invalid topic) merged through the API (no /otterdog): the ApplyChangesTask skips it
    (finished, no comment), nothing is created on GitHub, /api keeps it merged and not_applied."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name = s.run_repo()
    fields = s.invalid_topic()
    pr = s.open_pr(s.render(repositories=[s.new_repo(name, s.describe("invalid, never applied"), fields)]))
    status = s.wait_validation(pr, state="error")
    assert status.get("description") == texts.VALIDATION_ERROR, f"an invalid topic fails the validation: {status}"
    s.wait_sync(pr)
    s.wait_api_pull(pr, until=lambda r: r.get("valid") is False, what="invalid")

    merged_at = s.now()
    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    task = s.wait_task("ApplyChangesTask", pr, after=merged_at)
    assert task.get("status") == "finished", f"ApplyChangesTask must skip an invalid PR, not fail: {task}"
    s.quiesce()
    applied = [c for c in s.flow.bot_comments(pr) if comment_contains(c.get("body") or "", texts.APPLY_RESULT)]
    assert not applied, f"an invalid merged PR was applied (SUT): {applied}"
    assert s.oracle.repo(name) is None, f"{name} of an invalid PR exists on GitHub (SUT)"
    record = s.wait_api_pull(pr, until=lambda r: r.get("status") == "merged", what="merged")
    assert record.get("apply_status") == "not_applied", f"an invalid merged PR is not applied: {record}"


@pytest.mark.scenario("W-AUTOMERGE-AUTHOR-TEAM", priority="P0")
@pytest.mark.tags("webapp", "teams", "repo")
@pytest.mark.identities("approver")
def test_approval_team_author_merges_without_review(webapp_scenario: WebappScenario) -> None:
    """The approver (approval team) authors the PR: author_can_auto_merge true, auto-merge offered without any
    review, ``/otterdog merge`` merges and applies. An invalid PR of the same author is refused as not valid."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name, description = s.run_repo(), s.describe("auto-merged by its approval-team author")
    pr = s.open_pr(s.text(repos={name: description}), identity="approver")
    s.wait_settled(pr)
    record = s.wait_api_pull(pr, until=lambda r: r.get("author_can_auto_merge") is True, what="author eligible")
    assert record.get("has_required_approvals") is None, f"no review was submitted: {record}"
    automerge = s.wait_comment(pr, marker="automerge")
    assert comment_contains(automerge.get("body") or "", texts.AUTOMERGE), "automerge comment without its offer"

    s.flow.comment(pr, "/otterdog merge", identity="approver")
    s.wait_merged(pr)
    applied = s.wait_applied(pr)
    assert comment_contains(applied.get("body") or "", name), f"the apply comment does not name {name}"
    s.wait_repo(name)

    invalid = s.open_pr(s.syntax_error_text(), identity="approver", suffix="invalid")
    s.wait_validation(invalid, state="error")
    s.wait_sync(invalid)
    s.quiesce()
    assert not s.flow.bot_comments(invalid, marker="automerge"), "auto-merge offered for an invalid PR (SUT)"
    s.flow.comment(invalid, "/otterdog merge", identity="approver")
    problems = s.wait_problems(invalid)
    assert comment_contains(problems, texts.NOT_VALID), f"the refusal does not say 'not valid': {problems!r}"
    s.assert_still_open(invalid, "an invalid PR is never auto-merged")


@pytest.mark.scenario("W-AUTOMERGE-THIRD-PARTY", priority="P1")
@pytest.mark.tags("webapp", "teams", "repo")
@pytest.mark.identities("author", "approver", "outsider")
def test_merge_command_of_a_third_party(webapp_scenario: WebappScenario) -> None:
    """Eligible contributor PR (approved): ``/otterdog merge`` by an outsider is refused ("Only the author of the pull
    request, a member of ... is allowed to auto-merge."), by the approver (approval team) merged and applied."""
    s, texts = webapp_scenario, webapp_scenario.texts
    name, description = s.run_repo(), s.describe("merged on behalf of its author")
    pr = s.open_pr(s.text(repos={name: description}), identity="author")
    s.wait_settled(pr)
    s.flow.approve(pr, identity="approver")
    s.wait_comment(pr, marker="automerge")

    s.flow.comment(pr, "/otterdog merge", identity="outsider")
    problems = s.wait_problems(pr)
    assert texts.THIRD_PARTY_RE.search(problems), f"the refusal does not name who may merge (SUT): {problems!r}"
    s.assert_still_open(pr, "an outsider may not merge")

    s.flow.comment(pr, "/otterdog merge", identity="approver")
    s.wait_merged(pr)
    applied = s.wait_applied(pr)
    assert comment_contains(applied.get("body") or "", name), f"the apply comment does not name {name}"
    s.wait_repo(name)


@pytest.mark.scenario("W-AUTOMERGE-DISMISS", priority="P1")
@pytest.mark.tags("webapp", "teams", "repo")
@pytest.mark.identities("author", "approver")
def test_dismissed_approval_blocks_the_merge(webapp_scenario: WebappScenario) -> None:
    """Contributor PR: requested changes leave has_required_approvals false (no offer); the approval sets it and
    offers auto-merge; the admin dismisses the approval: false again, ``/otterdog merge`` by the author is refused
    for the missing approval and the PR stays open."""
    s, texts = webapp_scenario, webapp_scenario.texts
    pr = s.open_pr(s.text(repos={s.run_repo(): s.describe("never merged")}), identity="author")
    s.wait_settled(pr)

    s.flow.request_changes(pr)
    s.wait_api_pull(pr, until=lambda r: r.get("has_required_approvals") is False, what="changes requested")
    s.quiesce()
    assert not s.flow.bot_comments(pr, marker="automerge"), "auto-merge offered with changes requested (SUT)"

    review = s.flow.approve(pr)
    s.wait_comment(pr, marker="automerge")
    s.wait_api_pull(pr, until=lambda r: r.get("has_required_approvals") is True, what="approved")

    s.flow.dismiss_review(pr, review)
    s.wait_api_pull(pr, until=lambda r: r.get("has_required_approvals") is False, what="approval dismissed")
    s.flow.comment(pr, "/otterdog merge", identity="author")
    problems = s.wait_problems(pr)
    assert comment_contains(problems, texts.APPROVAL_MISSING), f"the refusal does not name the approval: {problems!r}"
    s.assert_still_open(pr, "the approval was dismissed")


@pytest.mark.scenario("W-AUTOMERGE-DRIFT", priority="P1")
@pytest.mark.tags("webapp", "repo")
def test_drifted_org_still_auto_merges(webapp_scenario: WebappScenario, mutator: Mutator) -> None:
    """A declared run repository drifts: the PR adding another repository is out of sync (check-sync comment, in_sync
    false) yet offered for auto-merge; ``/otterdog merge`` merges, the apply creates the new repository only and
    leaves the drifted description as it is on GitHub."""
    s, texts = webapp_scenario, webapp_scenario.texts
    drifted, added = s.run_repo("drifted"), s.run_repo("added")
    declared, live = s.describe("declared"), s.describe("drifted on GitHub")
    s.declare_live({drifted: declared})
    mutator.patch_repo(drifted, description=live)
    pr = s.open_pr(s.text(repos={drifted: declared, added: s.describe("added by an auto-merged PR")}))

    drift = s.wait_check_sync_comment(pr)
    assert comment_contains(drift.get("body") or "", drifted), f"the check-sync comment does not name {drifted}"
    status = s.wait_sync(pr)
    assert status.get("state") == "success" and status.get("description") == texts.SYNC_OUT_OF_SYNC, f"{status}"
    s.wait_api_pull(pr, until=lambda r: r.get("in_sync") is False, what="out of sync")
    s.wait_comment(pr, marker="automerge")  # an out-of-sync organization does not block auto-merge

    s.flow.comment(pr, "/otterdog merge")
    s.wait_merged(pr)
    body = s.wait_applied(pr).get("body") or ""
    assert comment_contains(body, added), f"the apply comment does not name {added}"
    assert not comment_contains(body, drifted), f"the apply touched the drifted {drifted} (SUT): {body[:2000]!r}"
    s.wait_repo(added)
    assert (s.oracle.repo(drifted) or {}).get("description") == live, "the apply replayed more than the PR diff (SUT)"


@pytest.mark.scenario("W-MERGE-TEAM-HOOK", priority="P2")
@pytest.mark.tags("webapp", "teams", "webhooks", "repo")
@pytest.mark.known_bug("KB-068")
@pytest.mark.xfail(
    raises=WildcardWebhookUpdateError,
    strict=False,
    reason="KB-068: a changed wildcard webhook is PATCHed with the pattern as its url and without its secret",
)
def test_team_and_wildcard_webhook_are_applied(webapp_scenario: WebappScenario) -> None:
    """A run team and a run repository whose webhook url carries a token, declared on main with a wildcard url
    (``.../<slug>*``): the merged PR changing the team description and the webhook events is applied by the webapp
    (local-apply, #325 finds the hook by its prefix): the team description is updated (strict); the hook must get
    the new events and keep its live url. otterdog PATCHes the whole expected hook, ``config.url`` = the pattern
    itself (verified offline: RepositoryWebhook.to_provider_data), so the token part is overwritten (or GitHub
    refuses the url and the patch fails): WildcardWebhookUpdateError, a scoped expected failure."""
    s, texts = webapp_scenario, webapp_scenario.texts
    team, repo = s.run_repo("team"), s.run_repo("hooks")
    hook_prefix = s.run_ctx.hook_url(s.slug)
    live_url, wildcard = f"{hook_prefix}?token=e2e-dummy-{s.run_ctx.run_id}", f"{hook_prefix}*"
    declared, updated = s.describe("declared team"), s.describe("team updated by the webapp")

    def config(team_description: str, url: str, events: list[str]) -> str:
        """Baseline plus the run team and the run repository with one webhook."""
        team_fragment = (
            f"orgs.newTeam({json.dumps(team)}) {{ description: {json.dumps(team_description)}, "
            'privacy: "visible", members: [] }'
        )
        hook = f'orgs.newRepoWebhook({json.dumps(url)}) {{ content_type: "json", events: {json.dumps(events)} }}'
        repo_fragment = s.new_repo(repo, s.describe("webhook with a token"), f"webhooks: [{hook}]")
        return s.render(repositories=[repo_fragment], teams=[team_fragment])

    s.declare_live_text(
        config(declared, live_url, ["push"]), what=[team, repo], main_text=config(declared, wildcard, ["push"])
    )
    hooks = [h for h in s.oracle.repo_hooks(repo) if str((h.get("config") or {}).get("url")).startswith(hook_prefix)]
    assert [h.get("config", {}).get("url") for h in hooks] == [live_url], f"precondition: one hook {live_url}: {hooks}"

    pr = s.open_pr(config(updated, wildcard, ["push", "pull_request"]))
    s.wait_settled(pr)
    body = s.wait_comment(pr, marker="validate").get("body") or ""
    assert comment_contains(body, team) and comment_contains(body, wildcard), f"validation of the change: {body!r}"
    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    applied = s.wait_comment(pr, contains=texts.APPLY_RESULT).get("body") or ""  # success or failure
    s.reaction(
        lambda: s.oracle.team(team),
        until=lambda value: value is not None and value.get("description") == updated,
        what=f"team {team} description updated by the apply",
        timeout=120,
    )
    hooks = [h for h in s.oracle.repo_hooks(repo) if str((h.get("config") or {}).get("url")).startswith(hook_prefix)]
    s.write_evidence({"apply": applied, "hooks": hooks})
    problems = [
        what
        for what, broken in (
            ("the apply failed", comment_contains(applied, texts.APPLY_FAILURE)),
            ("not exactly one matching hook", len(hooks) != 1),
            ("the live url was rewritten", [h.get("config", {}).get("url") for h in hooks] != [live_url]),
            (
                "the events were not updated",
                [sorted(h.get("events") or []) for h in hooks] != [["pull_request", "push"]],
            ),
        )
        if broken
    ]
    if problems:
        raise WildcardWebhookUpdateError(f"wildcard webhook {wildcard} after the apply: {problems}; hooks {hooks}")
