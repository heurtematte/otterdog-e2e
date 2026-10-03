"""BaselineManager (SPEC 11.5, 5.4): fail-closed removal guard, guarded apply, reset sequence, push, config guard."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.naming import RunContext
from otterdog_e2e.otterdog.baseline import BaselineManager, combine_apply_results
from otterdog_e2e.otterdog.output import PlanObject, PlanResult, parse_apply, parse_plan
from otterdog_e2e.otterdog.render import OrgConfigRenderer, build_baseline
from otterdog_e2e.otterdog.runner import OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import HarnessSettings, Identity, IdentitySpec, Target, WebappSpec
from otterdog_e2e.sut.cli_install import InstalledCli
from otterdog_e2e.sut.spec import ResolvedSut, SutSpec
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli, FakeOracle, make_verified_org

DATA = Path(__file__).parent / "data"
ORG = "e2e-test-org"
RUN = RunContext("t3c7z8a5")
OTHER_RUN = "t3b00000"  # plausible run id of another (purgeable or not) session
LEGEND = "\nActions are indicated with the following symbols:\n  + create\n  ~ modify\n  ! forced update\n  - delete\n"


def sample(name: str) -> str:
    """Text of a golden sample."""
    return (DATA / f"{name}.txt").read_text(encoding="utf-8")


def plan_text(*blocks: str, counts: tuple[int, int, int] | None = None) -> str:
    """A plan output in otterdog's exact grammar (blocks are ``(symbol, header, [body lines])`` strings)."""
    body = "".join(f"\n  {block}\n" for block in blocks)
    summary = (
        "" if counts is None else f"  \n  Plan: {counts[0]} to add, {counts[1]} to change, {counts[2]} to delete.\n"
    )
    return f"Planning execution:\n{LEGEND}\nProject {ORG}[github_id={ORG}] (1/1)\n{body}{summary}"


def remove(header: str) -> str:
    """A ``- remove <header>`` block."""
    return f'- remove {header} {{\n    - name = "x"\n  - }}'


def make_target() -> Target:
    """Target of the test org (declared logins: admin, approver)."""
    identities = {
        "admin": IdentitySpec("admin", "e2e-admin-bot", "E2E_ADMIN_TOKEN"),
        "approver": IdentitySpec("approver", "e2e-approver-bot", "E2E_APPROVER_TOKEN"),
    }
    return Target(
        name="free",
        description="test",
        org=ORG,
        org_id=424242,
        allowed_org_ids=(424242,),
        expected_plan="free",
        marker="[otterdog-e2e]",
        capability_overrides={"add": (), "remove": ()},
        configs_repo="otterdog-e2e-configs",
        org_config_repo="auto",
        defaults_repo="otterdog-e2e-defaults",
        template_mode="auto",
        template_url=None,
        identities=identities,
        app=None,
        admin_team="otterdog-admins",
        approval_team="project-leads",
        contributors_team="e2e-contributors",
        webapp=WebappSpec("relay", None, None, "v", "s", 1, 5000),
        fixture_repos=("otterdog-e2e-fixture-a",),
        extra_protected_repos=("human-repo",),
        baseline_settings={},
        source_path=Path("targets/free.yaml"),
    )


def make_oracle(target: Target) -> FakeOracle:
    """Live org holding every baseline repo and team."""
    oracle = FakeOracle(ORG)
    for repo in (target.config_repo_for(RUN), target.configs_repo, target.defaults_repo, *target.fixture_repos):
        oracle.add_repo(repo)
    for team in (target.admin_team, target.approval_team, target.contributors_team):
        oracle.add_team(team)
    return oracle


def make_manager(tmp_path: Path, *, purgeable: set[str] | None = None, cli: Any = None) -> BaselineManager:
    """BaselineManager over a FakeCli (reset CLI) and a FakeOracle."""
    target = make_target()
    renderer = OrgConfigRenderer(
        template=offline_template(),
        org=ORG,
        plan="free",
        org_profile={"description": "[otterdog-e2e] test org", "billing_email": "b@example.org"},
        baseline=build_baseline(target, RUN),
        marker=target.marker,
        hide_cache_limit=False,
    )
    workspace = ConfigWorkspace(tmp_path / "reset-ws", org=ORG, template=offline_template(), config_repo=".otterdog")
    allowed = {RUN.run_id} if purgeable is None else purgeable
    return BaselineManager(
        reset_cli=cli or FakeCli(org=ORG, workspace=workspace, strict=False),
        renderer=renderer,
        target=target,
        run_ctx=RUN,
        oracle=make_oracle(target),  # type: ignore[arg-type]
        purgeable=lambda run_id: run_id in allowed,
        protected_repos=target.protected_repos(RUN),
    )


# --- check_removals ----------------------------------------------------------------------------------------------
def test_purgeable_e2e_removals_are_allowed(tmp_path: Path) -> None:
    """Every removal of the real remove samples carries the purgeable run id (own name or parent)."""
    manager = make_manager(tmp_path)
    for name in (
        "local-plan-remove",
        "local-plan-remove-filtered",
        "local-plan-env-nested-remove",
        "local-plan-remove-repo",
    ):
        manager.check_removals(parse_plan(sample(name)))


def test_removals_of_non_purgeable_runs_are_refused(tmp_path: Path) -> None:
    """A run id that is not purgeable (not in the ledger, or a live lease holder) blocks the apply."""
    with pytest.raises(SafetyError, match="run t3c7z8a5 is not purgeable"):
        make_manager(tmp_path, purgeable=set()).check_removals(parse_plan(sample("local-plan-remove")))


def test_non_e2e_and_protected_removals_are_refused(tmp_path: Path) -> None:
    """Objects without a run id, baseline teams and protected repos (even the run's own config repo) are refused."""
    manager = make_manager(tmp_path)
    with pytest.raises(SafetyError, match=r'team\[name="otterdog-admins"\].*baseline team'):
        manager.check_removals(parse_plan(sample("local-plan-remove-teams")))
    for header, reason in (
        ('repository[name="human-repo"]', "protected repository"),
        ('repository[name="e2e-t3c7z8a5-config"]', "protected repository"),
        ('repository[name="playground"]', "carries no e2e run id"),
        ('org_secret[name="PROD_TOKEN"]', "carries no e2e run id"),
        ('repo_secret[name="HUMAN", repository=otterdog-e2e-fixture-a]', "carries no e2e run id"),
        ('org_webhook[url="https://hooks.example.org/x"]', "carries no e2e run id"),
    ):
        with pytest.raises(SafetyError, match=reason):
            manager.check_removals(parse_plan(plan_text(remove(header), counts=(0, 0, 1))))


def test_nested_removals_are_attributed_through_their_parent(tmp_path: Path) -> None:
    """Nested objects of run repos/environments are purgeable; e2e-named objects inside protected repos too."""
    manager = make_manager(tmp_path)
    plan = parse_plan(
        plan_text(
            remove('repo_secret[name="HUMAN", repository=e2e-t3c7z8a5-basic]'),
            remove('env_secret[name="TOKEN", environment=e2e-t3c7z8a5-env]'),
            remove('repo_secret[name="E2E_T3C7Z8A5_X", repository=otterdog-e2e-fixture-a]'),
            remove('repo_webhook[url="https://otterdog-e2e.invalid/t3c7z8a5/h", repository=otterdog-e2e-configs]'),
            counts=(0, 0, 4),
        )
    )
    manager.check_removals(plan)


def test_guard_fails_closed(tmp_path: Path) -> None:
    """Count mismatch, missing summary or validation abort: the plan cannot be verified."""
    manager = make_manager(tmp_path)
    mismatch = plan_text(remove('repository[name="e2e-t3c7z8a5-x"]'), counts=(0, 0, 2))
    with pytest.raises(SafetyError, match=r"announces 2 deletion\(s\) but 1"):
        manager.check_removals(parse_plan(mismatch))
    unparsed = plan_text("- remove repository named e2e-t3c7z8a5-x {\n  - }", counts=(0, 0, 1))
    with pytest.raises(SafetyError, match="announces 1 deletion"):
        manager.check_removals(parse_plan(unparsed))
    for name in ("plan-validation-error", "plan-network", "local-plan-missing-base"):
        with pytest.raises(SafetyError, match="did not complete"):
            manager.check_removals(parse_plan(sample(name)))


def test_guard_on_constructed_plan_results(tmp_path: Path) -> None:
    """The rules hold for PlanResults built by hand (no text): counts vs objects, attribution, protection."""
    manager = make_manager(tmp_path)

    def obj(op: str, kind: str, value: str, parent: str | None = None, body: list[str] | None = None) -> PlanObject:
        """A PlanObject with a header like otterdog's."""
        return PlanObject(
            op, kind, "name", value, "repository" if parent else None, parent, f"{kind}[{value}]", body or []
        )

    def result(objects: list[PlanObject], delete: int | None) -> PlanResult:
        """A completed PlanResult (``delete`` None means no summary)."""
        return PlanResult(0 if delete is not None else None, 0, delete, objects, delete is None, None, [], "")

    own = obj("remove", "repo_variable", "V", parent="e2e-t3c7z8a5-basic")
    assert manager.guard_problems(result([own], 1)) == []
    assert manager.guard_problems(result([own], 0)) == ["'Plan:' announces 0 deletion(s) but 1 '- remove' header(s)"]
    assert manager.guard_problems(result([], None))[0].startswith("the plan did not complete")
    foreign = obj("remove", "team", f"e2e-{OTHER_RUN}-team")
    assert manager.guard_problems(result([own, foreign], 2)) == [
        f"team[e2e-{OTHER_RUN}-team]: run {OTHER_RUN} is not purgeable"
    ]
    forced = obj("forced", "settings", "", body=['    ! description = "a" -> "a"'])
    assert manager.guard_problems(result([forced], 0), delete=False) == ["settings[]: changes the org description"]
    added = obj("add", "repository", "otterdog-e2e-configs")
    assert manager.guard_problems(result([added], 0)) == []  # additions/changes of protected repos are not removals


def test_description_changes_are_refused(tmp_path: Path) -> None:
    """A ``~ settings`` change of the description (safety marker) is refused, with or without -d (OC-01)."""
    manager = make_manager(tmp_path)
    plan = parse_plan(sample("local-plan-description-removed"))
    with pytest.raises(SafetyError, match="changes the org description"):
        manager.check_removals(plan)
    assert manager.guard_problems(plan, delete=False) == ["~ settings {: changes the org description"]
    assert manager.guard_problems(parse_plan(sample("local-plan-readonly")), delete=False) == []


# --- guarded_apply -----------------------------------------------------------------------------------------------
def test_guarded_apply_plans_checks_then_applies(tmp_path: Path) -> None:
    """plan -r F -> guard -> apply -r F -d; the parsed apply result is returned."""
    manager = make_manager(tmp_path)
    cli = manager.reset_cli
    cli.queue("plan", stdout=sample("local-plan-remove-filtered"))
    cli.queue("apply", stdout=sample("apply-executed"))
    result = manager.guarded_apply(cli, repo_filter="e2e-t3c7z8a5-*", delete=True)
    assert (result.added, result.deleted) == (8, 1)
    assert [(call.command, call.kwargs.get("repo_filter"), call.kwargs.get("delete")) for call in cli.calls] == [
        ("plan", "e2e-t3c7z8a5-*", None),
        ("apply", "e2e-t3c7z8a5-*", True),
    ]


def test_guarded_apply_refuses_before_applying(tmp_path: Path) -> None:
    """A refused plan never reaches apply; the error lists the offending headers."""
    manager = make_manager(tmp_path)
    cli = manager.reset_cli
    cli.queue("plan", stdout=sample("local-plan-remove-teams"))
    with pytest.raises(SafetyError, match="otterdog-admins"):
        manager.guarded_apply(cli, repo_filter=None, delete=True)
    assert [call.command for call in cli.calls] == ["plan"]


def test_guarded_apply_refuses_after_the_lease_was_lost(tmp_path: Path) -> None:
    """DESTR-03: write_check (E2EContext.check_lease_not_lost) runs before the guard plan of every apply and reset."""
    manager = make_manager(tmp_path)

    def lost() -> None:
        """The session's lease was taken over."""
        raise SafetyError("the org lease of run t3c7z8a5 was lost")

    manager.write_check = lost
    with pytest.raises(SafetyError, match="was lost"):
        manager.guarded_apply(manager.reset_cli, repo_filter="e2e-t3c7z8a5-*", delete=True)
    with pytest.raises(SafetyError, match="was lost"):
        manager.reset()
    assert manager.reset_cli.calls == []


def test_changes_the_reset_cannot_restore_are_refused(tmp_path: Path) -> None:
    """DESTR-07: a change without a run id is allowed for the org settings, baseline repositories (nested objects
    included) and baseline teams only; an extra protected repository, an unmanaged team or an org-level object
    named by hand is refused."""
    from otterdog_e2e.otterdog.baseline import unmanaged_changes
    from otterdog_e2e.otterdog.output import PlanObject, PlanResult

    def obj(op: str, kind: str, value: str, parent: tuple[str, str] | None = None) -> PlanObject:
        """A plan object with a one-key body."""
        tail = f", repository={parent[1]}]" if parent else "]"
        header = f'  {"~" if op == "change" else "!"} {kind}[name="{value}"{tail} {{'
        return PlanObject(
            op, kind, "name", value, *(parent or (None, None)), header, ["    ~ archived = false -> true"]
        )

    manager = make_manager(tmp_path)
    repos, teams = manager.baseline_repos, manager.baseline_teams
    allowed = [
        PlanObject("change", "settings", "", "", None, None, "  ~ settings {", ["    ~ description = a -> b"]),
        obj("change", "repository", repos[0]),
        obj("change", "branch_protection_rule", "main", ("repository", repos[-1])),
        obj("change", "team", teams[0]),
        obj("change", "repository", "e2e-t3c7z8a5-x"),
    ]
    refused = [
        obj("change", "repository", "precious-website"),  # an extra protected repository
        obj("forced", "repo_secret", "TOKEN", ("repository", "precious-website")),
        obj("change", "team", "hand-made-team"),
        obj("change", "org_webhook", "https://hooks.example.org/x"),
    ]
    plan = PlanResult(0, len(allowed) + len(refused), 0, [*allowed, *refused], False, None, [], "")
    found = unmanaged_changes(plan, repos=repos, teams=teams)
    assert found == [o.header.strip().removesuffix("{").rstrip() for o in refused]
    with pytest.raises(SafetyError, match="never restore"):
        manager.check_changes(plan)
    manager.check_changes(PlanResult(0, len(allowed), 0, allowed, False, None, [], ""))


def test_failed_run_cleanups_are_remembered(tmp_path: Path) -> None:
    """BAT-06: a removal of this run's objects (-d -r e2e-<run>-*) that fails (refused or failed patches) sets
    run_objects_left; the next successful one clears it; other applies never touch it."""
    manager = make_manager(tmp_path, purgeable=set())
    cli = manager.reset_cli
    run_filter = manager.run_ctx.repo_filter()
    cli.queue("plan", stdout=sample("local-plan-remove-teams"))  # refused by the guard
    with pytest.raises(SafetyError):
        manager.guarded_apply(cli, repo_filter=run_filter, delete=True)
    assert manager.run_objects_left
    cli.queue("plan", stdout=sample("local-plan-remove-teams"))
    with pytest.raises(SafetyError):
        manager.guarded_apply(cli, repo_filter="otterdog-e2e-configs", delete=True)  # not a run cleanup
    assert manager.run_objects_left
    clean = make_manager(tmp_path / "clean")
    clean.reset_cli.queue("plan", stdout=sample("local-plan-remove-filtered"))
    clean.reset_cli.queue("apply", stdout=sample("apply-executed"))
    clean.run_objects_left = True
    clean.guarded_apply(clean.reset_cli, repo_filter=clean.run_ctx.repo_filter(), delete=True)
    assert not clean.run_objects_left


def test_guarded_apply_without_delete_ignores_removals(tmp_path: Path) -> None:
    """Without -d removals are never applied, so foreign leftovers do not block (descriptions still do)."""
    manager = make_manager(tmp_path, purgeable=set())
    cli = manager.reset_cli
    cli.queue(
        "plan",
        stdout=plan_text(
            '+ add repository[name="e2e-t3c7z8a5-new"] {\n    + name = "x"\n  + }',
            remove('team[name="humans"]'),
            counts=(1, 0, 1),
        ),
    )
    cli.queue("apply", stdout=sample("apply-executed-ignored"))
    result = manager.guarded_apply(cli, repo_filter=None, delete=False)
    assert result.pending_deletions == 1 and cli.calls[1].kwargs["delete"] is False


def test_guarded_apply_skips_noop_plans(tmp_path: Path) -> None:
    """Nothing to add/change/delete: apply is not run (it would print 'No changes required.')."""
    manager = make_manager(tmp_path)
    cli = manager.reset_cli
    cli.queue("plan", stdout=sample("local-plan-readonly"))
    result = manager.guarded_apply(cli, repo_filter="otterdog-e2e-configs", delete=True)
    assert result.no_changes and (result.added, result.changed, result.deleted) == (0, 0, 0)
    assert [call.command for call in cli.calls] == ["plan"]
    cli.queue("plan", stdout=sample("local-plan-remove-repo"))
    pending = manager.guarded_apply(cli, repo_filter=None, delete=False)
    assert pending.no_changes and pending.pending_deletions == 1


def test_guarded_apply_raises_on_infra_errors(tmp_path: Path) -> None:
    """Rate limits/timeouts while planning are infra failures (AssertionError), not guard decisions."""
    manager = make_manager(tmp_path)
    cli = manager.reset_cli
    cli.queue("plan", stdout=sample("plan-network"), exit_code=2, infra_error="Cannot connect to host api.github.com")
    with pytest.raises(AssertionError, match="infra error"):
        manager.guarded_apply(cli, repo_filter=None, delete=True)


# --- reset ---------------------------------------------------------------------------------------------------------
def queue_reset(cli: FakeCli, *, in_sync: bool = True) -> None:
    """Outputs of a reset whose step 2 sees leftovers of this run and of another run."""
    leftovers = plan_text(
        '+ add repository[name="e2e-t3c7z8a5-config"] {\n    + name = "e2e-t3c7z8a5-config"\n  + }',
        remove('repository[name="e2e-t3c7z8a5-gone"]'),
        remove(f'org_variable[name="E2E_{OTHER_RUN.upper()}_VAR"]'),
        remove('repository[name="playground"]'),
        counts=(1, 0, 3),
    )
    cli.queue("plan", stdout=leftovers)
    cli.queue("apply", stdout=sample("apply-executed-ignored"))
    cli.queue("plan", stdout=plan_text(remove('repository[name="e2e-t3c7z8a5-gone"]'), counts=(0, 0, 1)))
    cli.queue("apply", stdout=sample("apply-executed"))
    cli.queue("check-status", status={"org_id": ORG, "sync_status": {"in_sync": in_sync}})


def test_reset_sequence(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """1 write baseline, 2 apply (no -d), 3 -d per purgeable run, 4 -d per baseline repo, 5 check-status, 6 oracle."""
    manager = make_manager(tmp_path)
    cli = manager.reset_cli
    queue_reset(cli)
    with caplog.at_level(logging.WARNING):
        result = manager.reset()
    assert cli.workspace.read_org_config() == manager.text() and cli.workspace.config_file.is_file()
    assert [(c.command, c.kwargs.get("repo_filter"), c.kwargs.get("delete")) for c in cli.calls] == [
        ("plan", None, None),
        ("apply", None, False),
        ("plan", "e2e-t3c7z8a5-*", None),
        ("apply", "e2e-t3c7z8a5-*", True),
        ("plan", "e2e-t3c7z8a5-config", None),
        ("plan", "otterdog-e2e-configs", None),
        ("plan", "otterdog-e2e-defaults", None),
        ("plan", "otterdog-e2e-fixture-a", None),
        ("check-status", None, None),
    ]
    assert (result.added, result.changed, result.deleted, result.ignored) == (16, 0, 1, 1)
    assert f"non-purgeable runs ['{OTHER_RUN}']" in caplog.text


def test_reset_warns_when_not_in_sync(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """check-status in_sync false is a warning listing the remaining plan objects."""
    manager = make_manager(tmp_path)
    queue_reset(manager.reset_cli, in_sync=False)
    with caplog.at_level(logging.WARNING):
        manager.reset()
    assert "org not in sync" in caplog.text


def test_reset_verifies_the_live_baseline(tmp_path: Path) -> None:
    """Missing baseline repos/teams or a lost marker after the reset are SafetyErrors."""
    manager = make_manager(tmp_path)
    queue_reset(manager.reset_cli)
    oracle = manager.oracle
    oracle.remove_repo("otterdog-e2e-defaults")  # type: ignore[attr-defined]
    oracle.set("org", value={"login": ORG, "description": "no marker"})  # type: ignore[attr-defined]
    with pytest.raises(SafetyError, match=r"otterdog-e2e-defaults.*lost the safety marker"):
        manager.reset()


def test_push_and_text(tmp_path: Path) -> None:
    """push() commits the baseline text through ConfigRepoFlow.reset_main."""

    class Flow:
        """Records reset_main calls."""

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def reset_main(self, text: str, *, message: str, identity: str = "admin") -> str:
            self.calls.append((text, message))
            return "c" * 40

    manager = make_manager(tmp_path)
    flow = Flow()
    assert manager.push(flow) == "c" * 40  # type: ignore[arg-type]
    assert flow.calls == [(manager.text(), "otterdog-e2e: baseline of run t3c7z8a5")]
    assert "e2e-t3c7z8a5-config" in manager.text() and "otterdog-admins" in manager.text()


def test_combine_apply_results() -> None:
    """Counts are summed (None wins), ignored/pending come from the first apply, failures are concatenated."""
    executed = parse_apply(sample("apply-executed"))
    failed = parse_apply(sample("apply-failed-patch"))
    network = parse_apply(sample("apply-network"))
    combined = combine_apply_results([executed, failed])
    assert (combined.added, combined.deleted, combined.failed_patches) == (16, 2, failed.failed_patches)
    assert combine_apply_results([executed, network]).added is None
    assert combine_apply_results([]).no_changes


# --- config guard (real OtterdogCli over a fake otterdog script) ---------------------------------------------------
FAKE = """
import sys
from pathlib import Path
here = Path(__file__).resolve().parent
(here / "argv.txt").write_text(" ".join(sys.argv[1:]))
sys.stdout.write((here / "local-plan.txt").read_text())
"""


def reset_cli(tmp_path: Path) -> OtterdogCli:
    """A live OtterdogCli whose otterdog prints bin/local-plan.txt."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    program = bin_dir / "fake_otterdog.py"
    program.write_text(FAKE)
    script = bin_dir / "otterdog"
    script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{program}" "$@"\n')
    script.chmod(0o755)
    sut = ResolvedSut(
        SutSpec("release:latest", "release", "latest"),
        "v1.6.1",
        "b" * 40,
        "1.6.1",
        "1.6.1",
        tmp_path,
        "https://github.com/eclipse-csi/otterdog",
        True,
    )
    settings = HarnessSettings(
        tmp_path, tmp_path / "cache", tmp_path / "art", "eclipse-csi/otterdog", tmp_path, tmp_path
    )
    workspace = ConfigWorkspace(
        tmp_path / "scratch" / "reset-ws", org=ORG, template=offline_template(), config_repo="r"
    )
    workspace.write_otterdog_json()
    return OtterdogCli(
        InstalledCli(sut, "host", None, script, None, ""),
        workspace,
        verified=make_verified_org(ORG),
        identity=Identity("admin", "e2e-admin-bot", "e2e-test-token-123456"),
        scratch=tmp_path / "scratch",
        artifacts_dir=tmp_path / "art",
        settings=settings,
    )


def test_guard_config_change(tmp_path: Path) -> None:
    """local-plan base -> head in a dedicated guard workspace; refused removals raise before any push/merge."""
    cli = reset_cli(tmp_path)
    manager = make_manager(tmp_path, cli=cli)
    (tmp_path / "bin" / "local-plan.txt").write_text(sample("local-plan-remove"))
    plan = manager.guard_config_change("base text", "head text")
    assert plan.delete == 10
    guard_workspace = tmp_path / "scratch" / "guard-workspace"
    assert (guard_workspace / "orgs" / ORG / f"{ORG}.jsonnet").read_text() == "head text"
    assert (guard_workspace / "orgs" / ORG / f"{ORG}.jsonnet-BASE").read_text() == "base text"
    assert (
        (tmp_path / "bin" / "argv.txt")
        .read_text()
        .startswith(f"local-plan -c {guard_workspace.resolve()}/otterdog.json -s -BASE")
    )
    assert cli.workspace.org_config_file.exists() is False  # the reset workspace is untouched
    assert manager.guard_cli().artifacts_dir == tmp_path / "art" / "guard"  # reports: role "reset"
    (tmp_path / "bin" / "local-plan.txt").write_text(sample("local-plan-remove-teams"))
    with pytest.raises(SafetyError, match="baseline team"):
        manager.guard_config_change("base", "head")


# --- config guard rules (a FakeCli guard CLI replaying real local-plan samples) ----------------------------------
def guard_manager(
    tmp_path: Path, *outputs: tuple[str, int, str | None], purgeable: set[str] | None = None, timed_out: bool = False
) -> tuple[BaselineManager, FakeCli]:
    """A manager whose guard CLI replays local-plan results (sample name, exit code, infra error)."""
    manager = make_manager(tmp_path, purgeable=purgeable)
    workspace = ConfigWorkspace(tmp_path / "guard-ws", org=ORG, template=offline_template(), config_repo=".otterdog")
    cli = FakeCli(org=ORG, workspace=workspace, strict=True)
    for name, exit_code, infra in outputs:
        cli.queue("local-plan", stdout=sample(name), exit_code=exit_code, infra_error=infra, timed_out=timed_out)
    manager._guard_cli = cli  # type: ignore[assignment]
    return manager, cli


def test_config_guard_checks_removals_and_uses_the_baseline_for_an_empty_base(tmp_path: Path) -> None:
    """Removals of the own run pass; an empty base (no config on main yet) is the baseline text."""
    manager, cli = guard_manager(tmp_path, ("local-plan-remove", 0, None), ("local-plan-noop", 0, None))
    assert manager.guard_config_change("", "head text").delete == 10
    assert cli.workspace.base_config_file.read_text() == manager.text()
    assert cli.workspace.read_org_config() == "head text"
    manager.guard_config_change("main text", "head text 2")
    assert cli.workspace.base_config_file.read_text() == "main text"


def test_config_guard_switches_to_local_once_the_template_is_vendored(tmp_path: Path) -> None:
    """The first local-plan fetches the template; once otterdog vendored it, later checks run with --local."""
    manager, cli = guard_manager(tmp_path, ("local-plan-noop", 0, None), ("local-plan-noop", 0, None))
    manager.guard_config_change("base", "head")
    vendored = cli.workspace.org_dir / cli.workspace.template.import_path
    vendored.parent.mkdir(parents=True)
    vendored.write_text("{}\n")
    manager.guard_config_change("base", "head")
    assert [call.kwargs["local"] for call in cli.calls_to("local-plan")] == [False, True]


def test_config_guard_refuses_foreign_and_protected_removals(tmp_path: Path) -> None:
    """Removals of a run that is not purgeable and of baseline teams are refused (SEC-07)."""
    manager, _cli = guard_manager(tmp_path, ("local-plan-remove", 0, None), purgeable=set())
    with pytest.raises(SafetyError, match="not purgeable"):
        manager.guard_config_change("main", "head")
    manager, _cli = guard_manager(tmp_path, ("local-plan-remove-teams", 0, None))
    with pytest.raises(SafetyError, match="baseline team"):
        manager.guard_config_change("main", "head")


def test_config_guard_accepts_heads_that_are_invalid_on_purpose(tmp_path: Path) -> None:
    """A head failing validation is accepted (the webapp never applies it) unless allow_invalid_head=False."""
    manager, _cli = guard_manager(tmp_path, ("local-plan-validation-error", 1, None))
    plan = manager.guard_config_change("main", "invalid head")
    assert plan.validation is not None and not plan.validation.ok
    manager, _cli = guard_manager(tmp_path, ("local-plan-validation-error", 1, None))
    with pytest.raises(SafetyError, match=r"local-plan failed \(exit 1\)"):
        manager.guard_config_change("main", "invalid head", allow_invalid_head=False)


@pytest.mark.parametrize(
    ("output", "timed_out", "match"),
    [
        (("plan-network", 1, "Cannot connect to host api.github.com"), False, "incomplete.*Cannot connect"),
        (("local-plan-noop", -1, None), True, r"incomplete \(timed out\)"),
        (("local-plan-missing-base", 1, None), False, r"local-plan failed \(exit 1\)"),  # base unloadable: never ok
    ],
)
def test_config_guard_refuses_incomplete_plans(
    tmp_path: Path, output: tuple[str, int, str | None], timed_out: bool, match: str
) -> None:
    """Infra errors, timeouts and a base that cannot be loaded are refused (fail closed)."""
    manager, _cli = guard_manager(tmp_path, output, timed_out=timed_out)
    with pytest.raises(SafetyError, match=match):
        manager.guard_config_change("main", "head")
