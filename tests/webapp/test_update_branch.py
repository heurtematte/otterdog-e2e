"""W-CMD-UPDATE-BRANCH (P2): ``/otterdog update-branch [rebase|merge]`` and the outdated-branch note of the local
feature branch feat/check-merge-command (pending features pending.update-branch-command, pending.outdated-branch-note).

The commands exist only in the maintainer's local feature branch (named change ``check-merge``, referenced below;
SUT ``dirty:<otterdog checkout>``, base v1.6.0): UpdateBranchCommentHandler matches
``/otterdog\\s+update-branch(\\s+(rebase|merge))?`` (default rebase), UpdateBranchTask refuses everybody but the PR
author and the admin teams (update_branch_comment.txt "Only the author of the pull request (@<author>) or a member of
the admin team(s) ... is allowed to update its branch."), otherwise updates the branch through GraphQL
updatePullRequestBranch and comments "The branch of this pull request has been updated with the <n> commit(s) of
`<base>` using a <method>, the configuration will be validated again." (+ the rewritten-history note for a rebase).
ValidatePullRequestTask adds outdated_branch_note.txt ("> [!IMPORTANT]" ... "is <n> commit(s) behind `<base>`") when
the head is behind its base.

Flow: the author's PR; main advances by one commit (a comment line on top of the baseline: no model change, no
conflict); ``/otterdog validate`` shows the note; the approver (neither author nor admin) is refused; the author's
``update-branch merge`` adds a merge commit and the re-validation drops the note; main advances again and the admin's
``update-branch`` (rebase) rebases the PR commit onto main. SUTs without the feature skip, like W-CMD-CHECK-MERGE.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.config_repo import comment_contains

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.config_repo import ConfigPr

pytestmark = [pytest.mark.webapp]

FEATURE_FILE = "otterdog/webapp/tasks/update_branch.py"  # UpdateBranchTask of feat/check-merge-command
MARKER = "update-branch"  # <!-- Otterdog Comment: update-branch -->
OUTDATED_NOTE = "> [!IMPORTANT]"
NOT_ALLOWED = "is allowed to update its branch"
REWRITTEN = "The history of the branch has been rewritten"
UPDATED_BY_MERGE = "has been updated with the 1 commit(s) of `main` using a merge"


def _behind(base: str, commits: int) -> str:
    """The outdated-branch note of a head ``commits`` behind ``base``."""
    return f"is {commits} commit(s) behind `{base}`"


def _advance_main(s: WebappScenario, step: str) -> str:
    """One more commit on main: a jsonnet comment on top of the baseline (no model change); returns its sha."""
    text = f"// otterdog-e2e {s.run_ctx.run_id} {s.sid}: main advanced ({step})\n{s.baseline_text()}"
    return s.flow.reset_main(text, message=f"otterdog-e2e {s.run_ctx.run_id}: {s.sid} advances main ({step})")


def _wait_new_head(s: WebappScenario, pr: ConfigPr, what: str) -> ConfigPr:
    """The PR once the webapp pushed a new head to its branch."""
    s.reaction(
        lambda: s.refreshed(pr).head_sha,
        until=lambda sha: sha != pr.head_sha,
        what=f"head of PR #{pr.number} updated ({what})",
        timeout=120,
    )
    return s.refreshed(pr)


REFERENCES = [
    {
        "change": "check-merge",
        "note": (
            "tasks/update_branch.py and outdated_branch_note.txt of the check-merge change (feat/check-merge-command):"
            " the '/otterdog update-branch' command and its '<!-- Otterdog Comment: update-branch -->' marker"
        ),
    }
]


@pytest.mark.scenario("W-CMD-UPDATE-BRANCH", priority="P2", references=REFERENCES)
@pytest.mark.tags("webapp", "teams")
@pytest.mark.identities("author", "approver")
@pytest.mark.timeout(1800, func_only=True)  # two branch updates, each validated again
def test_update_branch_command(webapp_scenario: WebappScenario) -> None:
    """Outdated note, refusal of a third party, merge update by the author (note gone), rebase by an admin."""
    s = webapp_scenario
    has_feature = s.webapp_source_has(FEATURE_FILE)
    if not has_feature:
        known = "has no" if has_feature is False else "cannot tell whether it has"
        pytest.skip(f"webapp under test {known} the /otterdog update-branch command ({FEATURE_FILE})")
    author = s.login("author")
    pr = s.open_pr(s.harmless_text(), identity="author")
    s.wait_settled(pr)
    first = s.wait_comment(pr, marker="validate")
    assert not comment_contains(first.get("body") or "", OUTDATED_NOTE), "outdated note on an up-to-date branch"

    _advance_main(s, "first")
    s.flow.comment(pr, "/otterdog validate", identity="author")
    noted = s.wait_comment(pr, marker="validate", exclude=[first])
    assert comment_contains(noted.get("body") or "", _behind("main", 1)), (
        f"the validation of a head one commit behind main has no outdated note (SUT): {noted.get('body')!r}"
    )

    s.flow.comment(pr, "/otterdog update-branch", identity="approver")
    refused = s.wait_comment(pr, marker=MARKER)
    body = refused.get("body") or ""
    assert comment_contains(body, NOT_ALLOWED) and f"(@{author})" in body, f"third party not refused: {body!r}"
    assert s.refreshed(pr).head_sha == pr.head_sha, "a refused update-branch changed the branch (SUT)"

    s.flow.comment(pr, "/otterdog update-branch merge", identity="author")
    merged_note = s.wait_comment(pr, marker=MARKER, exclude=[refused])
    body = merged_note.get("body") or ""
    assert comment_contains(body, UPDATED_BY_MERGE), f"update-branch merge comment (SUT): {body!r}"
    merged = _wait_new_head(s, pr, "merge")
    parents = (s.oracle.git_commit(s.repo, merged.head_sha) or {}).get("parents") or []
    assert len(parents) == 2, f"update-branch merge must add a merge commit: {parents}"
    s.wait_validation(merged)
    revalidated = s.wait_comment(merged, marker="validate", exclude=[first, noted])
    assert not comment_contains(revalidated.get("body") or "", OUTDATED_NOTE), "outdated note after the update (SUT)"
    s.wait_minimized(merged, refused)

    _advance_main(s, "second")
    s.flow.comment(merged, "/otterdog update-branch")  # the admin; rebase is the default method
    rebased_note = s.wait_comment(merged, marker=MARKER, exclude=[refused, merged_note])
    body = rebased_note.get("body") or ""
    assert comment_contains(body, "using a rebase") and comment_contains(body, REWRITTEN), f"rebase comment: {body!r}"
    rebased = _wait_new_head(s, merged, "rebase")
    parents = (s.oracle.git_commit(s.repo, rebased.head_sha) or {}).get("parents") or []
    assert len(parents) == 1, f"a rebased branch ends with a single-parent commit, not a merge: {parents}"
    s.wait_validation(rebased)
    after_rebase = s.wait_comment(rebased, marker="validate", exclude=[first, noted, revalidated])
    assert not comment_contains(after_rebase.get("body") or "", OUTDATED_NOTE), (
        "the rebased head is still behind main (outdated note in its validation) (SUT)"
    )
