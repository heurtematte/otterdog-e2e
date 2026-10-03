"""ConfigRepoFlow beyond the basic PR flow: multi-file PRs, drafts, reopen, comment edits and deletions, request-changes
and dismissed reviews, merge methods, adopted run PRs; their delivery triggers and guards.

The Mutator methods of these flows (reopen_pull, mark_pull_ready, convert_pull_to_draft, edit_comment, delete_comment,
dismiss_review) come from the shared RecordingMutator (whose parity with the real Mutator test_testing_fakes checks),
guards included; ConfigRepoError names a method a Mutator stand-in lacks.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e.config_repo import (
    MERGE_METHODS,
    ConfigPr,
    ConfigRepoError,
    ConfigRepoFlow,
    DeliveryTimeoutError,
    ReactionTimeoutError,
    check_forwarded,
    checked_paths,
    run_branch,
)
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FAKE_ORG, FakeOracle, RecordingMutator, fake_sha, make_run_context
from otterdog_e2e.waiting import WaitTimeoutError
from otterdog_e2e.webhooks.relay import RelayedDelivery

VCTX = "e2e/otterdog-validate"
SCTX = "e2e/otterdog-sync"
MAIN_SHA = fake_sha("main")
BASE_TEXT = "local orgs = import 'vendor/template/otterdog-defaults.libsonnet';\norgs.newOrg('o', 'o') {}\n"
PATH = f"otterdog/{FAKE_ORG}.jsonnet"
RUN = make_run_context().run_id


class FakeRelay:
    """DeliveryRelay stand-in: wait_for scans a fixed list of deliveries."""

    def __init__(self) -> None:
        """No deliveries yet."""
        self.deliveries: list[RelayedDelivery] = []

    def wait_for(self, predicate: Callable[[RelayedDelivery], bool], *, timeout: float = 300) -> RelayedDelivery:
        """First matching delivery or WaitTimeoutError."""
        for delivery in self.deliveries:
            if predicate(delivery):
                return delivery
        raise WaitTimeoutError("relayed delivery matching the predicate", timeout)

    def add(self, delivery_id: int, event: str, action: str | None, **fields: Any) -> RelayedDelivery:
        """Append a forwarded delivery."""
        now = datetime.now(UTC)
        values: dict[str, Any] = {
            "id": delivery_id,
            "guid": f"guid-{delivery_id}",
            "event": event,
            "action": action,
            "installation_id": 4242,
            "repository_id": 1,
            "pull_number": None,
            "delivered_at": now,
            "seen_at": now,
            "forwarded_at": now,
            "github_status_code": 202,
            "relay_status": 204,
        }
        values.update(fields)
        delivery = RelayedDelivery(**values)
        self.deliveries.append(delivery)
        return delivery


def build(relay: FakeRelay | None = None, mutator_class: type[RecordingMutator] = RecordingMutator) -> SimpleNamespace:
    """A flow on the run's config repo with recording mutators and a fake oracle."""
    oracle = FakeOracle()
    run_ctx = make_run_context()
    repo = run_ctx.name("config")
    oracle.set("branch_sha", repo, "main", value=MAIN_SHA)
    oracle.add_file(repo, PATH, BASE_TEXT, ref="main")
    mutators = {name: mutator_class(oracle=oracle) for name in ("admin", "author", "approver", "outsider")}
    guarded: list[tuple[str, str]] = []

    def guard(base: str, head: str) -> None:
        """Record; refuse texts containing FORBIDDEN."""
        guarded.append((base, head))
        if "FORBIDDEN" in head:
            raise SafetyError("plan removes protected repository otterdog-e2e-configs")

    flow = ConfigRepoFlow(
        org=FAKE_ORG,
        repo=repo,
        oracle=oracle,
        mutators=mutators,
        run_ctx=run_ctx,
        validation_context=VCTX,
        sync_context=SCTX,
        guard=guard,
        bot_login="otterdog-e2e-app[bot]",
        relay=relay,  # type: ignore[arg-type]
        delivery_timeout=60,
    )
    flow.sleep, flow.clock = (lambda seconds: None), (lambda: 0.0)
    return SimpleNamespace(flow=flow, oracle=oracle, repo=repo, mutators=mutators, guarded=guarded, run=run_ctx)


def sync_pull(world: SimpleNamespace, pr: ConfigPr, **fields: Any) -> None:
    """The oracle's view of the PR (open, head at the ConfigPr's sha)."""
    value = {
        "number": pr.number,
        "state": "open",
        "merged": False,
        "head": {"sha": pr.head_sha, "ref": pr.branch},
        "base": {"ref": "main"},
    }
    value.update(fields)
    world.oracle.set("pull", world.repo, pr.number, value=value)


def calls(mutator: RecordingMutator, method: str) -> list[Any]:
    """Recorded calls of ``method``."""
    return mutator.calls_to(method)


# --- multi-file PRs ------------------------------------------------------------------------------------------------
def test_open_pr_files_commits_every_file_once_and_guards_the_config() -> None:
    """One commit with the org config and other files; only the config text is guarded."""
    world = build()
    files = {PATH: "head config", "README.md": "# docs", "otterdog/blueprints/e2e-x.yml": None}
    pr = world.flow.open_pr_files(slug="multi", files=files, title="e2e: multi-file", body="b")
    assert world.guarded == [(BASE_TEXT, "head config")]
    admin = world.mutators["admin"]
    assert [call.method for call in admin.calls] == ["create_branch", "commit_files", "create_pull"]
    commit = admin.calls[1]
    assert commit.args[1] == f"e2e/{RUN}/multi" and commit.args[2] == files
    assert commit.args[3] == f"e2e {RUN} multi: 3 file(s)"
    assert pr.branch == f"e2e/{RUN}/multi" and pr.head_sha and admin.calls[2].kwargs["draft"] is False
    sync_pull(world, pr)
    world.guarded.clear()
    world.flow.approve(pr)
    assert world.guarded == [(BASE_TEXT, "head config")]  # the head text is known without a read


def test_pr_touching_only_other_files_is_guarded_with_the_base_text() -> None:
    """No org config in the PR: nothing to guard at open; later guards use main's text as the head text."""
    world = build()
    pr = world.flow.open_pr_files(slug="docs", files={"README.md": "# x"}, title="e2e: docs only", message="docs")
    assert world.guarded == [] and world.mutators["admin"].calls[1].args[3] == "docs"
    sync_pull(world, pr)
    world.flow.merge(pr, method="merge")
    assert world.guarded == [(BASE_TEXT, BASE_TEXT)]
    assert calls(world.mutators["admin"], "merge_pull")[0].kwargs == {"method": "merge", "sha": pr.head_sha}


def test_open_pr_files_refusals() -> None:
    """Deleting the org config, bad paths, empty mappings and destructive texts are refused before any write."""
    world = build()
    with pytest.raises(ConfigRepoError, match="deleting"):
        world.flow.open_pr_files(slug="x", files={PATH: None}, title="t")
    for bad in ({"../x": "a"}, {"/abs": "a"}, {"a/../b": "a"}, {".git/config": "a"}, {"a\\b": "a"}, {"": "a"}, {}):
        with pytest.raises(ValueError):
            world.flow.open_pr_files(slug="x", files=bad, title="t")
    with pytest.raises(ValueError):
        checked_paths({"README.md": 3})  # type: ignore[dict-item]
    with pytest.raises(SafetyError):
        world.flow.open_pr_files(slug="x", files={PATH: "FORBIDDEN", "README.md": "x"}, title="t")
    assert world.mutators["admin"].calls == []


def test_push_files_keeps_the_known_head_text() -> None:
    """push_files: one commit, guarded config texts, synchronize trigger; a commit without config keeps the head
    text."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="v1", title="t", identity="author")
    second = world.flow.push_files(pr, {"README.md": "x"}, message="docs")
    assert world.mutators["author"].calls[-1].args == (world.repo, pr.branch, {"README.md": "x"}, "docs")
    assert world.flow._texts_by_sha[second.head_sha] == "v1"
    third = world.flow.push_files(second, {PATH: "v2", "a.txt": None}, message="config", identity="admin")
    assert world.guarded[-1] == (BASE_TEXT, "v2") and world.flow._texts_by_sha[third.head_sha] == "v2"
    assert world.mutators["admin"].calls[-1].method == "commit_files"
    with pytest.raises(ConfigRepoError):
        world.flow.push_files(third, {PATH: None}, message="x")


# --- drafts and reopen ---------------------------------------------------------------------------------------------
def test_draft_ready_convert_and_reopen() -> None:
    """mark_ready / convert_to_draft / reopen act as the PR's identity and set their pull_request triggers."""
    world = build()
    pr = world.flow.open_pr(slug="d", config_texts="x", title="t", identity="author", draft=True)
    assert world.flow.mark_ready(pr) == {}
    assert world.flow._triggers[pr.number].action == "ready_for_review"
    assert world.flow.convert_to_draft(pr, identity="admin") == {}
    assert world.flow._triggers[pr.number].action == "converted_to_draft"
    world.flow.close(pr)
    world.flow.reopen(pr)
    trigger = world.flow._triggers[pr.number]
    assert (trigger.event, trigger.action, trigger.head_sha) == ("pull_request", "reopened", pr.head_sha)
    author, admin = world.mutators["author"], world.mutators["admin"]
    assert [c.args for c in calls(author, "mark_pull_ready")] == [(world.repo, pr.number)]
    assert [c.args for c in calls(admin, "convert_pull_to_draft")] == [(world.repo, pr.number)]
    assert [c.args for c in calls(author, "reopen_pull")] == [(world.repo, pr.number)]


def test_foreign_prs_are_refused() -> None:
    """Only PRs the flow opened or adopted can be changed."""
    world = build()
    foreign = ConfigPr(99, "feature/x", "a" * 40, "u", "someone", frozenset())
    for action in (world.flow.mark_ready, world.flow.convert_to_draft, world.flow.reopen):
        with pytest.raises(ConfigRepoError, match="not opened or adopted"):
            action(foreign)


class BareMutator:
    """A Mutator offering only what opening a PR needs."""

    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        """Nothing to record."""

    def commit_files(self, repo: str, branch: str, files: Any, message: str) -> str:
        """A fake commit."""
        return fake_sha((branch, message))

    def create_pull(self, repo: str, **kwargs: Any) -> dict[str, Any]:
        """A fake PR."""
        return {"number": 1, "html_url": "https://github.com/x/y/pull/1", "user": {"login": "e2e-admin"}}


def test_missing_mutator_methods_are_named() -> None:
    """A Mutator without a mutation of the flow: ConfigRepoError naming the method."""
    world = build()
    world.flow.mutators = {"admin": BareMutator()}
    pr = world.flow.open_pr(slug="m", config_texts="x", title="t")
    for action, name in (
        (world.flow.reopen, "reopen_pull"),
        (world.flow.mark_ready, "mark_pull_ready"),
        (world.flow.convert_to_draft, "convert_pull_to_draft"),
    ):
        with pytest.raises(ConfigRepoError, match=name):
            action(pr)


# --- comments ------------------------------------------------------------------------------------------------------
def test_edit_and_delete_own_comments() -> None:
    """edit_comment (by the comment's author unless told otherwise) and delete_comment with their triggers."""
    world = build()
    pr = world.flow.open_pr(slug="c", config_texts="head", title="t")
    sync_pull(world, pr)
    note = world.flow.comment(pr, "hello", identity="author")
    world.guarded.clear()
    edited = world.flow.edit_comment(pr, note, "/otterdog help")
    assert (edited["id"], edited["body"]) == (note["id"], "/otterdog help") and world.guarded == []
    assert calls(world.mutators["author"], "edit_comment")[0].args == (world.repo, note["id"], "/otterdog help")
    trigger = world.flow._triggers[pr.number]
    assert (trigger.event, trigger.action, trigger.comment_id) == ("issue_comment", "edited", note["id"])
    world.flow.delete_comment(pr, note["id"], identity="admin")
    assert calls(world.mutators["admin"], "delete_comment")[0].args == (world.repo, note["id"])
    assert world.flow._triggers[pr.number].action == "deleted"
    with pytest.raises(ConfigRepoError):
        world.flow.edit_comment(pr, note, "again")  # deleted: no longer the flow's


def test_edits_into_merge_or_apply_are_guarded() -> None:
    """The webapp runs edited commands: editing into /otterdog merge re-runs the guard (and may refuse)."""
    world = build()
    pr = world.flow.open_pr(slug="g", config_texts="ok", title="t")
    sync_pull(world, pr)
    note = world.flow.comment(pr, "first")
    world.guarded.clear()
    world.flow.edit_comment(pr, note, "/otterdog merge")
    assert world.guarded == [(BASE_TEXT, "ok")]
    other = fake_sha("pushed")
    sync_pull(world, pr, head={"sha": other, "ref": pr.branch})
    world.oracle.add_file(world.repo, PATH, "FORBIDDEN", ref=other)
    with pytest.raises(SafetyError):
        world.flow.edit_comment(pr, note, "/otterdog apply")
    assert len(calls(world.mutators["admin"], "edit_comment")) == 1


def test_foreign_comments_are_refused() -> None:
    """Comments the flow did not post (or posted on another PR) cannot be edited or deleted."""
    world = build()
    pr = world.flow.open_pr(slug="f", config_texts="x", title="t")
    other = world.flow.open_pr(slug="f2", config_texts="x", title="t")
    note = world.flow.comment(other, "on the other PR")
    for comment in (12345, {"id": "IC_x"}, note, True):
        with pytest.raises(ConfigRepoError, match="not posted"):
            world.flow.delete_comment(pr, comment)  # type: ignore[arg-type]


# --- reviews -------------------------------------------------------------------------------------------------------
def test_request_changes_and_dismiss() -> None:
    """request_changes is not guarded; dismiss_review dismisses a review of this flow as admin, with a message."""
    world = build()
    pr = world.flow.open_pr(slug="r", config_texts="x", title="t", identity="author")
    sync_pull(world, pr)
    world.guarded.clear()
    review = world.flow.request_changes(pr)
    assert world.guarded == [] and review["state"] == "CHANGES_REQUESTED"
    assert calls(world.mutators["approver"], "review")[0].kwargs == {
        "event": "REQUEST_CHANGES",
        "body": "e2e: changes requested",
    }
    approval = world.flow.approve(pr)
    result = world.flow.dismiss_review(pr, approval, message="stale approval")
    assert result["state"] == "DISMISSED"
    dismissal = calls(world.mutators["admin"], "dismiss_review")[0]
    assert dismissal.args == (world.repo, pr.number, approval["id"]) and dismissal.kwargs == {
        "message": "stale approval"
    }
    trigger = world.flow._triggers[pr.number]
    assert (trigger.event, trigger.action, trigger.head_sha) == ("pull_request_review", "dismissed", pr.head_sha)


def test_review_refusals() -> None:
    """Empty bodies/messages and reviews of other PRs or other flows are refused."""
    world = build()
    pr = world.flow.open_pr(slug="v", config_texts="x", title="t")
    other = world.flow.open_pr(slug="v2", config_texts="x", title="t")
    with pytest.raises(ValueError):
        world.flow.request_changes(pr, body=" ")
    review = world.flow.request_changes(other)
    with pytest.raises(ConfigRepoError, match="not submitted"):
        world.flow.dismiss_review(pr, review)
    with pytest.raises(ConfigRepoError):
        world.flow.dismiss_review(pr, 777)
    with pytest.raises(ValueError):
        world.flow.dismiss_review(other, review, message="")


# --- merge methods -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("method", MERGE_METHODS)
def test_merge_methods(method: str) -> None:
    """merge, squash and rebase are passed through (pinned to the head sha)."""
    world = build()
    pr = world.flow.open_pr(slug="m", config_texts="x", title="t")
    sync_pull(world, pr)
    world.flow.merge(pr, method=method)
    assert calls(world.mutators["admin"], "merge_pull")[0].kwargs == {"method": method, "sha": pr.head_sha}


def test_unknown_merge_method_is_refused() -> None:
    """Anything else fails before the guard or GitHub."""
    world = build()
    pr = world.flow.open_pr(slug="m", config_texts="x", title="t")
    world.guarded.clear()
    with pytest.raises(ValueError):
        world.flow.merge(pr, method="fast-forward")
    assert world.guarded == [] and not calls(world.mutators["admin"], "merge_pull")


# --- adopted PRs ---------------------------------------------------------------------------------------------------
def test_adopt_a_run_pr_then_merge_it_guarded() -> None:
    """A blueprint remediation PR of this run: registered with its comments, merged through the guard; the cleanup
    closes it without deleting its otterdog/* branch (the webapp does)."""
    world = build()
    branch = f"otterdog/blueprint/e2e-{RUN}-append"
    head = fake_sha("blueprint head")
    world.oracle.set(
        "pull",
        world.repo,
        41,
        value={
            "number": 41,
            "state": "open",
            "head": {"ref": branch, "sha": head},
            "base": {"ref": "main"},
            "user": {"login": "app[bot]"},
        },
    )
    world.oracle.add_file(world.repo, PATH, BASE_TEXT + "+ { }\n", ref=head)
    world.oracle.add_pr_comment(world.repo, 41, "validate")
    pr = world.flow.adopt_pr(41)
    assert (pr.branch, pr.head_sha, pr.author) == (branch, head, "app[bot]") and len(pr.comment_ids_before) == 1
    world.flow.merge(pr, method="squash")
    assert world.guarded[-1] == (BASE_TEXT, BASE_TEXT + "+ { }\n")
    world.flow.cleanup()
    admin = world.mutators["admin"]
    assert [c.args for c in calls(admin, "close_pull")] == [(world.repo, 41)] and not calls(admin, "delete_ref")


def test_adopt_refuses_foreign_and_missing_prs() -> None:
    """Branches of other runs or people, other bases and unknown PRs are refused."""
    world = build()
    for number, branch, base in ((1, "feature/x", "main"), (2, "e2e/t3c7z8b6/x", "main"), (3, f"e2e/{RUN}/x", "dev")):
        world.oracle.set(
            "pull",
            world.repo,
            number,
            value={"number": number, "head": {"ref": branch, "sha": "a" * 40}, "base": {"ref": base}},
        )
    with pytest.raises(SafetyError):
        world.flow.adopt_pr(1)
    with pytest.raises(SafetyError):
        world.flow.adopt_pr(2)
    with pytest.raises(ConfigRepoError, match="targets"):
        world.flow.adopt_pr(3)
    with pytest.raises(ConfigRepoError, match="no pull request"):
        world.flow.adopt_pr(404)


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (f"e2e/{RUN}/case", True),
        (f"refs/heads/e2e/{RUN}/case", True),
        (f"otterdog/e2e-{RUN}-open-pr", True),
        (f"otterdog/blueprint/e2e-{RUN}-bp", True),
        ("otterdog/blueprint/e2e-t3c7z8b6-bp", False),
        ("otterdog/blueprint/default-security-policy", False),
        ("main", False),
        (f"feature/e2e-{RUN}-x", False),
    ],
)
def test_run_branch(ref: str, expected: bool) -> None:
    """Branches of this run: e2e/<run>/..., open-pr branches and blueprint remediation branches."""
    assert run_branch(ref, RUN) is expected


# --- deliveries ----------------------------------------------------------------------------------------------------
def test_new_triggers_match_their_deliveries() -> None:
    """ready_for_review (head sha), edited (comment id) and dismissed reviews wait for exactly their delivery."""
    relay = FakeRelay()
    world = build(relay)
    pr = world.flow.open_pr(slug="t", config_texts="x", title="t", draft=True)
    sync_pull(world, pr)
    after = datetime.now(UTC) - timedelta(seconds=1)
    world.flow.mark_ready(pr)
    relay.add(1, "pull_request", "opened", pull_number=pr.number, head_sha=pr.head_sha)
    ready = relay.add(2, "pull_request", "ready_for_review", pull_number=pr.number, head_sha=pr.head_sha)
    assert world.flow.wait_delivery(pr, event="pull_request", action="ready_for_review", after=after) is ready
    note = world.flow.comment(pr, "x")
    world.flow.edit_comment(pr, note, "/otterdog help")
    relay.add(3, "issue_comment", "edited", pull_number=pr.number, comment_id=note["id"] + 1)
    edited = relay.add(4, "issue_comment", "edited", pull_number=pr.number, comment_id=note["id"])
    assert world.flow.wait_delivery(pr, event="issue_comment", action="edited", after=after) is edited
    review = world.flow.approve(pr)
    world.flow.dismiss_review(pr, review)
    dismissed = relay.add(5, "pull_request_review", "dismissed", pull_number=pr.number, head_sha=pr.head_sha)
    assert world.flow.wait_delivery(pr, event="pull_request_review", action="dismissed", after=after) is dismissed


def test_check_forwarded_classification() -> None:
    """Not forwarded / rejected = infra, 5xx = SUT, 2xx passes."""
    relay = FakeRelay()
    ok = relay.add(1, "workflow_job", "queued")
    check_forwarded(ok, "e2e repo run 1")
    with pytest.raises(DeliveryTimeoutError, match="not forwarded"):
        check_forwarded(relay.add(2, "workflow_job", "queued", relay_status=None, error="x"), "w")
    with pytest.raises(DeliveryTimeoutError, match="secret"):
        check_forwarded(relay.add(3, "workflow_job", "queued", relay_status=401), "w")
    with pytest.raises(ReactionTimeoutError, match=r"for w \(HTTP 500\) \(SUT\)"):
        check_forwarded(relay.add(4, "workflow_job", "queued", relay_status=500), "w")
