"""ConfigRepoFlow (SPEC 13.4): guards before every risky action, delivery-then-reaction waits with infra/SUT
messages, exclude_ids comment matching, normalize_comment on real otterdog comment bodies."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e.config_repo import (
    APPLIED_TEXTS,
    MARKERS,
    ConfigPr,
    ConfigRepoError,
    ConfigRepoFlow,
    DeliveryTimeoutError,
    FlowError,
    ReactionTimeoutError,
    comment_contains,
    comment_marker,
    normalize_comment,
)
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FAKE_ORG, FakeOracle, RecordingMutator, fake_sha, make_run_context
from otterdog_e2e.waiting import WaitTimeoutError
from otterdog_e2e.webhooks.relay import RelayedDelivery

VCTX = "e2e/otterdog-validate"
SCTX = "e2e/otterdog-sync"
BOT = "otterdog-e2e-app"
MAIN_SHA = fake_sha("main")
BASE_TEXT = "local orgs = import 'vendor/template/otterdog-defaults.libsonnet';\norgs.newOrg('o', 'o') {}\n"
PATH = f"otterdog/{FAKE_ORG}.jsonnet"

# validation comment rendered offline by otterdog main's own code path (IndentingPrinter(output_for_github=True) +
# LocalPlanOperation + escape_for_github + templates/comment/validation_comment.txt), trimmed, trailing spaces kept
REAL_VALIDATION_COMMENT = "\n".join(
    [
        "<!-- Otterdog Comment: validate -->",
        "Please find below the validation of the requested configuration changes:",
        "",
        "<details>",
        "<summary>Diff for 0123456789abcdef0123456789abcdef01234567</summary>",
        "",
        "```diff",
        "",
        "Project e2e-offline[github_id=e2e-offline]",
        "",
        '-  remove repository[name="e2e-t3c7z8a5-w-old"] {',
        "-    allow_auto_merge                           = false",
        '-    description                                = "e2e- old repo to remove"',
        "-  }",
        "",
        "  ",
        '!   repository[name="otterdog-e2e-fixture-a"] {',
        '!     description = "fixture" -> "fixture changed"',
        "!   }",
        "",
        '+  add repository[name="e2e-t3c7z8a5-w-apply-with-a-really-long-repository-name-for-wrapping"] {',
        (
            '+    description                                = "e2e apply- a description that is long enough to be wrapped'
            " by the rich console at one hundred and ten "
        ),
        'columns"',
        "+  }",
        "  ",
        "  Plan: 1 to add, 1 to change, 1 to delete.",
        "!" + " " * 109,
        "! Warning:   some of the requested changes require secrets, need to apply these changes manually and a long   ",
        "!            tail to wrap the box line" + " " * 72,
        "!" + " " * 109,
        "```",
        "",
        "</details>",
        "",
        "",
        "### Warnings",
        "",
        "",
        "- some of the requested changes require secrets, need to apply these changes manually",
        "",
        "cc @e2e-test-org/otterdog-admins",
    ]
)
APPLIED_COMMENT = (
    "\n> [!NOTE]\n> The following changes have been applied successfully:\n\n```diff\n+  add repository[x]\n```\n"
)


class FakeRelay:
    """DeliveryRelay stand-in: wait_for scans a fixed list of deliveries."""

    def __init__(self) -> None:
        """No deliveries yet."""
        self.deliveries: list[RelayedDelivery] = []
        self.timeouts: list[float] = []

    def wait_for(self, predicate: Callable[[RelayedDelivery], bool], *, timeout: float = 300) -> RelayedDelivery:
        """First matching delivery or WaitTimeoutError."""
        self.timeouts.append(timeout)
        for delivery in self.deliveries:
            if predicate(delivery):
                return delivery
        raise WaitTimeoutError("relayed delivery matching the predicate", timeout)

    def add(self, delivery_id: int, event: str, action: str | None, **fields: Any) -> RelayedDelivery:
        """Append a forwarded delivery (delivered/forwarded now unless given)."""
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


class FakeTime:
    """Monotonic clock advanced by sleep(); hooks run on sleep."""

    def __init__(self) -> None:
        """t=0."""
        self.now = 0.0
        self.hooks: list[Callable[[], None]] = []

    def clock(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance; run the next hook."""
        self.now += seconds
        if self.hooks:
            self.hooks.pop(0)()


def build(relay: FakeRelay | None = None, guard: Callable[[str, str], None] | None = None) -> SimpleNamespace:
    """A flow on the run's config repo with recording mutators and a fake oracle."""
    oracle = FakeOracle()
    run_ctx = make_run_context()
    repo = run_ctx.name("config")
    oracle.set("branch_sha", repo, "main", value=MAIN_SHA)
    oracle.add_file(repo, PATH, BASE_TEXT, ref="main")
    mutators = {name: RecordingMutator(oracle=oracle) for name in ("admin", "author", "approver")}
    guarded: list[tuple[str, str]] = []

    def default_guard(base: str, head: str) -> None:
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
        guard=guard or default_guard,
        bot_login=f"{BOT}[bot]",
        relay=relay,  # type: ignore[arg-type]
        delivery_timeout=120,
    )
    fake = FakeTime()
    flow.sleep, flow.clock = fake.sleep, fake.clock
    return SimpleNamespace(
        flow=flow, oracle=oracle, repo=repo, mutators=mutators, guarded=guarded, time=fake, run=run_ctx
    )


def sync_pull(world: SimpleNamespace, pr: ConfigPr, **fields: Any) -> None:
    """Make the oracle's PR head match the ConfigPr (what GitHub reports after the harness pushed)."""
    value = {"number": pr.number, "state": "open", "merged": False, "head": {"sha": pr.head_sha, "ref": pr.branch}}
    value.update(fields)
    world.oracle.set("pull", world.repo, pr.number, value=value)


def calls(mutator: RecordingMutator) -> list[str]:
    """Method names recorded by a mutator."""
    return [call.method for call in mutator.calls]


# --- main and PRs --------------------------------------------------------------------------------------------------
def test_config_path_and_main() -> None:
    """The org config lives at otterdog/<org>.jsonnet on the default branch."""
    world = build()
    assert world.flow.config_path == PATH
    assert world.flow.main_sha() == MAIN_SHA and world.flow.main_config() == BASE_TEXT
    world.oracle.remove("branch_sha", world.repo, "main")
    with pytest.raises(ConfigRepoError):
        world.flow.main_sha()


def test_open_pr_guards_every_text_before_any_write() -> None:
    """Each text is guarded against main; then branch e2e/<run>/<slug>, one commit per text, PR to main."""
    world = build()
    pr = world.flow.open_pr(slug="w-pr-valid", config_texts=["one", "two"], title="e2e: valid", body="b")
    assert world.guarded == [(BASE_TEXT, "one"), (BASE_TEXT, "two")]
    admin = world.mutators["admin"]
    assert calls(admin) == ["create_branch", "commit_files", "commit_files", "create_pull"]
    branch = f"e2e/{world.run.run_id}/w-pr-valid"
    assert admin.calls[0].args == (world.repo, branch, MAIN_SHA)
    assert [call.args[2] for call in admin.calls[1:3]] == [{PATH: "one"}, {PATH: "two"}]
    assert admin.calls[3].kwargs == {"head": branch, "base": "main", "title": "e2e: valid", "body": "b", "draft": False}
    assert pr.branch == branch and pr.number == 1 and pr.author == "e2e-admin"
    assert pr.head_sha and pr.url.endswith("/pull/1") and pr.comment_ids_before == frozenset()


def test_open_pr_rejected_by_the_guard_writes_nothing() -> None:
    """A destructive text (SEC-07) raises SafetyError before the branch exists."""
    world = build()
    with pytest.raises(SafetyError):
        world.flow.open_pr(slug="bad", config_texts=["ok", "FORBIDDEN"], title="t")
    assert world.mutators["admin"].calls == []


def test_open_pr_identity_and_texts() -> None:
    """Unknown identities and empty text lists are refused; the author identity opens its own PRs."""
    world = build()
    with pytest.raises(ConfigRepoError):
        world.flow.open_pr(slug="x", config_texts="t", title="t", identity="outsider")
    with pytest.raises(ValueError):
        world.flow.open_pr(slug="x", config_texts=[], title="t")
    world.flow.open_pr(slug="mine", config_texts="t", title="t", identity="author", draft=True)
    assert calls(world.mutators["author"])[-1] == "create_pull" and world.mutators["admin"].calls == []
    assert world.mutators["author"].calls[-1].kwargs["draft"] is True


def test_reset_main() -> None:
    """Identical text: no commit; otherwise guarded commit on main; no current config: unguarded first commit."""
    world = build()
    assert world.flow.reset_main(BASE_TEXT, message="reset") == MAIN_SHA
    assert world.mutators["admin"].calls == [] and world.guarded == []
    sha = world.flow.reset_main("baseline v2", message="e2e reset")
    assert world.guarded == [(BASE_TEXT, "baseline v2")]
    (call,) = world.mutators["admin"].calls
    assert call.method == "commit_files" and call.args == (world.repo, "main", {PATH: "baseline v2"}, "e2e reset")
    assert sha
    world.oracle.remove("file_content", world.repo, PATH, "main")
    world.oracle.remove("file_content", world.repo, PATH, None)
    world.flow.reset_main("first", message="m")
    assert world.guarded == [(BASE_TEXT, "baseline v2")]


def test_push_commit() -> None:
    """Guarded against main, pushed by the PR's identity, new head sha and comment snapshot returned."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="v1", title="t", identity="author")
    world.oracle.add_pr_comment(world.repo, pr.number, "old validate " + MARKERS["validate"], author=BOT)
    updated = world.flow.push_commit(pr, "v2", message="second")
    assert world.guarded[-1] == (BASE_TEXT, "v2")
    assert world.mutators["author"].calls[-1].args == (world.repo, pr.branch, {PATH: "v2"}, "second")
    assert updated.head_sha != pr.head_sha and updated.number == pr.number
    assert len(updated.comment_ids_before) == 1
    with pytest.raises(SafetyError):
        world.flow.push_commit(pr, "FORBIDDEN", message="x")


# --- guards --------------------------------------------------------------------------------------------------------
def test_comment_guard_only_for_merge_and_apply() -> None:
    """/otterdog merge|apply re-run the guard on the current head text; other comments do not."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="head text", title="t")
    sync_pull(world, pr)
    world.guarded.clear()
    world.flow.comment(pr, "/otterdog help")
    world.flow.comment(pr, "/otterdog validate info")
    assert world.guarded == []
    world.flow.comment(pr, "/otterdog merge")
    world.flow.comment(pr, "/otterdog   apply")
    assert world.guarded == [(BASE_TEXT, "head text"), (BASE_TEXT, "head text")]
    assert [call.args[2] for call in world.mutators["admin"].calls if call.method == "comment"][
        -1
    ] == "/otterdog   apply"


def test_guard_refusal_blocks_the_command() -> None:
    """If the head became destructive, the merge command is never posted."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="ok", title="t")
    other_sha = fake_sha("pushed by someone else")
    sync_pull(world, pr, head={"sha": other_sha})
    world.oracle.add_file(world.repo, PATH, "FORBIDDEN", ref=other_sha)
    with pytest.raises(SafetyError):
        world.flow.comment(pr, "/otterdog merge")
    assert "comment" not in calls(world.mutators["admin"])


def test_guard_needs_a_readable_head() -> None:
    """An unreadable head config refuses to proceed."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="ok", title="t")
    sync_pull(world, pr, head={"sha": fake_sha("unknown")})
    world.oracle.remove("file_content", world.repo, PATH, None)
    with pytest.raises(SafetyError):
        world.flow.approve(pr)


def test_approve_and_merge_are_guarded_and_pinned() -> None:
    """approve: guard + APPROVE review by the approver; merge: guard + squash merge pinned to the head sha."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="head", title="t")
    sync_pull(world, pr)
    world.guarded.clear()
    world.flow.approve(pr)
    review = world.mutators["approver"].calls[-1]
    assert review.method == "review" and review.kwargs["event"] == "APPROVE"
    world.flow.merge(pr)
    merge = world.mutators["admin"].calls[-1]
    assert merge.method == "merge_pull" and merge.kwargs == {"method": "squash", "sha": pr.head_sha}
    assert world.guarded == [(BASE_TEXT, "head"), (BASE_TEXT, "head")]


def test_an_invalid_head_is_merged_unchecked_only_when_the_sut_reports_it_invalid() -> None:
    """DESTR-04: pushes accept a head the trusted CLI finds invalid (the default guard flag), but approve, merge and
    /otterdog merge|apply pass allow_invalid_head only when the SUT's validation status on the head is failure or
    error; otherwise the removal check must pass (the SUT may consider valid what release:latest cannot load)."""
    flags: list[bool] = []

    def guard(base: str, head: str, *, allow_invalid_head: bool = True) -> None:
        """Record the flag of each guard call."""
        flags.append(allow_invalid_head)

    world = build(guard=guard)  # type: ignore[arg-type]
    pr = world.flow.open_pr(slug="s", config_texts="head", title="t")
    sync_pull(world, pr)
    assert flags == [True]  # the push: the default
    flags.clear()
    world.flow.approve(pr)
    world.flow.comment(pr, "/otterdog merge")
    assert flags == [False, False]  # no validation status yet: strict
    world.oracle.add_status(world.repo, pr.head_sha, VCTX, "success")
    world.flow.merge(pr)
    assert flags[-1] is False  # valid for the SUT: strict
    for state in ("failure", "error"):
        world.oracle.add_status(world.repo, pr.head_sha, VCTX, state)
        flags.clear()
        world.flow.approve(pr)
        assert flags == [True], state  # the SUT will never apply it


def test_apply_after_merge_also_checks_the_pre_merge_base() -> None:
    """After a merge main holds the head text: /otterdog apply is guarded against the pre-merge base too."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="merged text", title="t")
    sync_pull(world, pr)
    world.flow.merge(pr)
    world.oracle.add_file(world.repo, PATH, "merged text", ref="main")  # GitHub after the squash merge
    world.guarded.clear()
    world.flow.comment(pr, "/otterdog apply")
    assert world.guarded == [("merged text", "merged text"), (BASE_TEXT, "merged text")]


# --- comments ------------------------------------------------------------------------------------------------------
def test_bot_comments_filter_author_and_markers() -> None:
    """slug and slug[bot] authors count; markers by name, full marker text or PR-specific names."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    world.oracle.add_pr_comment(world.repo, pr.number, MARKERS["help"] + "\nThank you", author=BOT)
    world.oracle.add_pr_comment(world.repo, pr.number, MARKERS["validate"] + "\nDiff", author=f"{BOT}[bot]")
    world.oracle.add_pr_comment(world.repo, pr.number, "<!-- Otterdog Comment: check-merge -->", author=BOT)
    world.oracle.add_pr_comment(world.repo, pr.number, MARKERS["validate"], author="e2e-author")
    world.oracle.set(  # GraphQL returns logins without [bot]; keep a REST-style author too
        "pr_comments",
        world.repo,
        pr.number,
        value=[
            {**c, "author": f"{BOT}[bot]"} if "Diff" in c["body"] else c
            for c in world.oracle.pr_comments(world.repo, pr.number)
        ],
    )
    assert len(world.flow.bot_comments(pr)) == 3
    assert [comment_marker(c["body"]) for c in world.flow.bot_comments(pr, marker="validate")] == ["validate"]
    assert len(world.flow.bot_comments(pr, marker=MARKERS["help"])) == 1
    assert len(world.flow.bot_comments(pr, marker="check-merge")) == 1


def test_bot_login_is_required_for_comment_reads() -> None:
    """Without the App slug bot comments cannot be identified."""
    world = build()
    world.flow.bot_login = None
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    with pytest.raises(ConfigRepoError):
        world.flow.bot_comments(pr)


def test_wait_comment_excludes_known_ids_and_matches_normalized_text() -> None:
    """Old comments (exclude_ids, comment_ids_before) are skipped; contains survives diff columns and wrapping."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    old = world.oracle.add_pr_comment(world.repo, pr.number, REAL_VALIDATION_COMMENT, author=BOT)
    world.time.hooks.append(
        lambda: world.oracle.add_pr_comment(world.repo, pr.number, REAL_VALIDATION_COMMENT, author=BOT)
    )
    found = world.flow.wait_comment(
        pr, marker="validate", contains="e2e - old repo to remove", exclude_ids={old["id"]}, timeout=60
    )
    assert found["id"] != old["id"] and world.time.now == 5
    snapshot = world.flow.comment_ids(pr)
    newer = ConfigPr(**{**pr.__dict__, "comment_ids_before": snapshot})
    world.time.hooks.append(lambda: world.oracle.add_pr_comment(world.repo, pr.number, APPLIED_COMMENT, author=BOT))
    applied = world.flow.wait_comment(newer, contains=APPLIED_TEXTS[0], timeout=60)
    assert applied["body"] == APPLIED_COMMENT


def test_wait_comment_timeout_is_a_sut_failure() -> None:
    """No matching comment: ReactionTimeoutError naming the bot comments that were seen."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    world.oracle.add_pr_comment(world.repo, pr.number, MARKERS["help"] + "\nThanks", author=BOT)
    with pytest.raises(ReactionTimeoutError) as info:
        world.flow.wait_comment(pr, marker="validate", timeout=30)
    assert "webapp did not react within 30 s" in str(info.value) and "help" in str(info.value)
    assert info.value.infra is False and isinstance(info.value, FlowError) and isinstance(info.value, AssertionError)


# --- statuses ------------------------------------------------------------------------------------------------------
def test_wait_status_final_and_aliases() -> None:
    """final waits past pending; final=False returns the first status; 'validation'/'sync' are aliases."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    world.oracle.add_status(world.repo, pr.head_sha, VCTX, "pending")
    assert world.flow.wait_status(pr, "validation", final=False)["state"] == "pending"
    world.time.hooks.append(lambda: world.oracle.add_status(world.repo, pr.head_sha, VCTX, "success", "completed"))
    assert world.flow.wait_status(pr, VCTX)["state"] == "success"
    world.oracle.add_status(
        world.repo, pr.head_sha, SCTX, "success", "otterdog sync check failed, check comment history"
    )
    assert world.flow.wait_status(pr, "sync")["description"].startswith("otterdog sync check failed")


def test_wait_status_timeout_message() -> None:
    """A status stuck in pending is reported as a SUT failure with its state."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    world.oracle.add_status(world.repo, pr.head_sha, VCTX, "pending")
    with pytest.raises(ReactionTimeoutError) as info:
        world.flow.wait_status(pr, VCTX, timeout=20)
    assert "is pending" in str(info.value) and "(SUT; no delivery tracking" in str(info.value)


# --- deliveries ----------------------------------------------------------------------------------------------------
def test_reactions_first_wait_for_the_triggering_delivery() -> None:
    """open_pr -> pull_request/opened (same PR and head sha) must be relayed before the status wait starts."""
    relay = FakeRelay()
    world = build(relay)
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    relay.add(1, "pull_request", "opened", pull_number=pr.number + 1, head_sha=pr.head_sha)  # other PR
    relay.add(2, "pull_request", "opened", pull_number=pr.number, head_sha=fake_sha("other"))  # other head
    relay.add(3, "pull_request", "opened", pull_number=pr.number, head_sha=pr.head_sha)
    world.oracle.add_status(world.repo, pr.head_sha, VCTX, "success")
    assert world.flow.wait_status(pr, VCTX)["state"] == "success"
    assert relay.timeouts == [120]
    world.flow.wait_status(pr, VCTX)  # the trigger delivery is remembered: no second delivery wait
    assert relay.timeouts == [120]


def test_missing_delivery_is_an_infra_failure() -> None:
    """Nothing relayed: DeliveryTimeoutError mentioning (infra), before any status poll."""
    world = build(FakeRelay())
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    with pytest.raises(DeliveryTimeoutError) as info:
        world.flow.wait_status(pr, VCTX)
    assert "not observed within 120 s (infra)" in str(info.value) and info.value.infra is True
    assert world.time.now == 0


@pytest.mark.parametrize(
    ("fields", "error", "text"),
    [
        (
            {"relay_status": None, "forwarded_at": None, "error": "forward failed"},
            DeliveryTimeoutError,
            "not forwarded",
        ),
        ({"relay_status": 400}, DeliveryTimeoutError, "secret"),
        ({"relay_status": 500}, ReactionTimeoutError, "(SUT)"),
    ],
)
def test_bad_forwards_are_classified(fields: dict[str, Any], error: type[FlowError], text: str) -> None:
    """Not forwarded / 4xx = infra; webapp 5xx = SUT."""
    relay = FakeRelay()
    world = build(relay)
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    relay.add(1, "pull_request", "opened", pull_number=pr.number, head_sha=pr.head_sha, **fields)
    with pytest.raises(error) as info:
        world.flow.wait_status(pr, VCTX)
    assert text in str(info.value)


def test_synchronize_and_comment_deliveries_are_matched_exactly() -> None:
    """Pushes match on the new head sha, comments on the comment id."""
    relay = FakeRelay()
    world = build(relay)
    pr = world.flow.open_pr(slug="s", config_texts="v1", title="t")
    pr2 = world.flow.push_commit(pr, "v2", message="m")
    relay.add(1, "pull_request", "synchronize", pull_number=pr.number, head_sha=pr.head_sha)
    wanted = relay.add(2, "pull_request", "synchronize", pull_number=pr.number, head_sha=pr2.head_sha)
    after = datetime.now(UTC) - timedelta(seconds=1)
    assert world.flow.wait_delivery(pr2, event="pull_request", action="synchronize", after=after) is wanted
    posted = world.flow.comment(pr2, "/otterdog help")
    relay.add(3, "issue_comment", "created", pull_number=pr.number, comment_id=posted["id"] + 1)
    mine = relay.add(4, "issue_comment", "created", pull_number=pr.number, comment_id=posted["id"])
    assert world.flow.wait_delivery(pr2, event="issue_comment", action="created", after=after) is mine


def test_deliveries_are_consumed_and_old_ones_ignored() -> None:
    """A delivery serves one wait; deliveries older than after - 60 s never match."""
    relay = FakeRelay()
    world = build(relay)
    pr = ConfigPr(7, "e2e/x/y", "a" * 40, "u", "e2e-admin", frozenset())
    now = datetime.now(UTC)
    relay.add(1, "push", None, delivered_at=now - timedelta(minutes=5))
    first = relay.add(2, "push", None)
    assert world.flow.wait_delivery(pr, event="push", after=now) is first
    with pytest.raises(DeliveryTimeoutError):
        world.flow.wait_delivery(pr, event="push", after=now)


def test_reaction_timeout_counts_from_the_forward_time() -> None:
    """The status wait has ``timeout`` minus the time elapsed since the delivery was forwarded."""
    relay = FakeRelay()
    world = build(relay)
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    earlier = datetime.now(UTC) - timedelta(seconds=100)
    relay.add(1, "pull_request", "opened", pull_number=pr.number, head_sha=pr.head_sha, forwarded_at=earlier)
    with pytest.raises(ReactionTimeoutError) as info:
        world.flow.wait_status(pr, VCTX, timeout=120)
    assert "within 120 s (SUT)" in str(info.value)
    assert 15 <= world.time.now <= 25  # ~20 s left, not 120


def test_wait_delivery_without_relay_returns_none() -> None:
    """External transport: no delivery tracking."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    assert world.flow.wait_delivery(pr, event="pull_request", action="opened", after=datetime.now(UTC)) is None


def test_wait_merged() -> None:
    """Merged PRs are returned; a PR closed without merge fails at once."""
    world = build()
    pr = world.flow.open_pr(slug="s", config_texts="x", title="t")
    sync_pull(world, pr)
    world.time.hooks.append(lambda: sync_pull(world, pr, state="closed", merged=True))
    assert world.flow.wait_merged(pr)["merged"] is True and world.time.now == 5
    other = world.flow.open_pr(slug="s2", config_texts="x", title="t")
    sync_pull(world, other, state="closed", merged=False)
    with pytest.raises(ReactionTimeoutError) as info:
        world.flow.wait_merged(other)
    assert "closed without being merged" in str(info.value)


def test_cleanup_closes_open_prs_and_deletes_branches() -> None:
    """Open PRs are closed, merged ones only lose their branch; refs are heads/e2e/<run>/<slug>."""
    world = build()
    open_pr = world.flow.open_pr(slug="open", config_texts="x", title="t")
    merged_pr = world.flow.open_pr(slug="merged", config_texts="x", title="t")
    sync_pull(world, open_pr)
    sync_pull(world, merged_pr, state="closed", merged=True)
    world.flow.cleanup()
    admin = world.mutators["admin"]
    assert [c.args for c in admin.calls if c.method == "close_pull"] == [(world.repo, open_pr.number)]
    refs = [c.args[1] for c in admin.calls if c.method == "delete_ref"]
    assert refs == [f"heads/{open_pr.branch}", f"heads/{merged_pr.branch}"]
    world.flow.cleanup()  # nothing left
    assert len([c for c in admin.calls if c.method == "delete_ref"]) == 2


# --- comment text --------------------------------------------------------------------------------------------------
def test_markers_and_applied_texts() -> None:
    """Upstream markers only (templates/comment/*); the apply result comment has no marker."""
    assert set(MARKERS) == {"help", "team-info", "validate", "check-sync", "automerge", "blueprint-dismissal"}
    assert comment_marker(REAL_VALIDATION_COMMENT) == "validate"
    assert comment_marker(APPLIED_COMMENT) is None and APPLIED_TEXTS[0] in APPLIED_COMMENT
    assert comment_marker("<!--Otterdog Comment:  check-sync-->") == "check-sync"


@pytest.mark.parametrize(
    "needle",
    [
        'remove repository[name="e2e-t3c7z8a5-w-old"]',
        '- remove repository[name="e2e-t3c7z8a5-w-old"] {',
        'description = "fixture" -> "fixture changed"',
        '~ repository[name="otterdog-e2e-fixture-a"]',
        "e2e - old repo to remove",  # escape_for_github turned ' - ' into '- '
        "e2e apply - a description that is long enough to be wrapped by the rich console at one hundred and ten columns",
        "need to apply these changes manually and a long tail to wrap the box line",  # box wrapped at 110 columns
        "Plan: 1 to add, 1 to change, 1 to delete.",
        "<!-- Otterdog Comment: validate -->",
        "cc @e2e-test-org/otterdog-admins",
    ],
)
def test_normalize_comment_on_a_real_validation_comment(needle: str) -> None:
    """Assertions written against plain otterdog output match the GitHub-escaped, wrapped comment."""
    assert comment_contains(REAL_VALIDATION_COMMENT, needle)


def test_normalize_comment_rules() -> None:
    """Diff columns and box borders go, '->' '[!NOTE]' 'C++' and hyphenated names stay, whitespace collapses."""
    assert normalize_comment("!   repository {\n!     a = 1 -> 2\n!   }") == "repository { a = 1 -> 2 }"
    assert normalize_comment("> [!NOTE]\n> C++ e2e-t3c7z8a5-x") == "> [!NOTE] > C++ e2e-t3c7z8a5-x"
    assert normalize_comment("│ Error:   Validation failed │\n╰──────╯") == "Error: Validation failed"
    assert normalize_comment("\x1b[31m+ add\x1b[0m") == "add"
    assert normalize_comment("a - b") == normalize_comment("a- b") == "a b"
    assert not comment_contains(REAL_VALIDATION_COMMENT, 'repository[name="e2e-t3c7z8a5-w-new"]')
    assert not comment_contains("plain text", " - ")  # a needle that normalizes to nothing never matches
