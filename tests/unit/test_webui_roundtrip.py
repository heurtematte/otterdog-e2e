"""The web-settings round trip (webui.roundtrip): toggles, snapshots, and the whole scenario on a simulated org where
the SUT (apply/plan), the trusted reader (``show-live``, parsed by the real parser) and REST share one live state."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import pytest

from otterdog_e2e.otterdog.runner import CliResult
from otterdog_e2e.testing.fakes import FakeCli, cli_result
from otterdog_e2e.webui import mapping
from otterdog_e2e.webui.oracle import TrustedWebReader
from otterdog_e2e.webui.roundtrip import (
    WebSettingsRoundTrip,
    combine_snapshot,
    expected_changes,
    plan_toggles,
    toggled_branch,
)

RUN = "t3c7z8a5"
REPO = "e2e-test-org/otterdog-e2e-fixture-a"
ORIGINAL: dict[str, Any] = {
    "members_can_change_repo_visibility": False,
    "members_can_delete_repositories": True,
    "members_can_delete_issues": False,
    "readers_can_create_discussions": True,
    "members_can_create_teams": True,
    "two_factor_requirement": False,
    "default_branch_name": "main",
    "packages_containers_public": True,
    "packages_containers_internal": True,
    "members_can_change_project_visibility": True,
    "has_discussions": False,
    "discussion_source_repository": None,
}
PINNED_RE = re.compile(r"^(?P<key>[a-z_]+)::: (?P<value>.*)$")


def pinned(text: str) -> dict[str, Any]:
    """The ``key::: value`` fields of a fake config text."""
    return {m["key"]: json.loads(m["value"]) for m in map(PINNED_RE.match, text.splitlines()) if m}


@dataclass
class World:
    """Live org state shared by the fakes; knobs to break the SUT."""

    live: dict[str, Any] = field(default_factory=lambda: dict(ORIGINAL))
    sut_unreadable: set[str] = field(default_factory=set)  # keys the SUT's web reader misses (UNSET)
    trusted_unreadable: set[str] = field(default_factory=lambda: {"two_factor_requirement"})
    trusted_lies: dict[str, Any] = field(default_factory=dict)  # values the trusted reader reports wrongly
    fail_applies: list[int] = field(default_factory=list)  # apply numbers (1-based) that fail
    stale_plan: dict[str, Any] = field(default_factory=dict)  # values the SUT's plan reads instead of the live ones
    applies: int = 0
    logins: int = 0

    def diff(self, wanted: Mapping[str, Any], live: Mapping[str, Any]) -> dict[str, tuple[Any, Any]]:
        """What otterdog plans: pinned web keys differing from what its reader sees (discussion rule included)."""
        changes = {}
        for key, value in wanted.items():
            if key in self.sut_unreadable or not mapping.web_setting(key).writable:
                continue
            if key == "discussion_source_repository" and wanted.get("has_discussions") is False:
                continue
            if live.get(key) != value:
                changes[key] = (live.get(key), value)
        return changes

    def output(self, changes: Mapping[str, tuple[Any, Any]], summary: str) -> str:
        """otterdog-like plan output with a ``~ settings`` block."""
        lines = ["Project e2e-test-org[github_id=e2e-test-org] (1/1)", ""]
        if changes:
            lines.append("  ~ settings {")
            lines += [f"    ~ {k} = {json.dumps(old)} -> {json.dumps(new)}" for k, (old, new) in changes.items()]
            lines.append("  ~ }")
        return "\n".join([*lines, "", f"  {summary}", ""])


@dataclass
class FakeWorkspace:
    """Keeps the last org config written."""

    text: str = ""

    def write_org_config(self, text: str) -> None:
        """Store the config."""
        self.text = text


class FakeSut:
    """Web-mode SUT: apply and plan read the live state like otterdog (one or two logins)."""

    def __init__(self, world: World) -> None:
        """Bind the world."""
        self.world = world
        self.workspace = FakeWorkspace()

    def apply(self) -> CliResult:
        """Plan against the live state, then change it (unless this apply is set to fail)."""
        world = self.world
        world.applies += 1
        world.logins += 2
        wanted = pinned(self.workspace.text)
        changes = world.diff(wanted, world.live)
        if world.applies in world.fail_applies:
            return cli_result(
                "apply", world.output(changes, "") + "failed to apply patch: CHANGE - settings\n", exit_code=1
            )
        for key, (_old, new) in changes.items():
            world.live[key] = new
        if wanted.get("has_discussions") is False:
            world.live["discussion_source_repository"] = None
        text = world.output(changes, f"Executed plan: 0 added, {len(changes)} changed, 0 live resources ignored.")
        return cli_result("apply", text)

    def plan(self) -> CliResult:
        """Plan only (``stale_plan`` simulates a broken reader)."""
        self.world.logins += 1
        changes = self.world.diff(pinned(self.workspace.text), {**self.world.live, **self.world.stale_plan})
        return cli_result("plan", self.world.output(changes, f"Plan: 0 to add, {len(changes)} to change, 0 to delete."))


class FakeTrustedCli(FakeCli):
    """Trusted web-mode CLI whose ``show-live`` prints the live settings block."""

    def __init__(self, world: World) -> None:
        """Bind the world."""
        super().__init__()
        self.world = world
        self.web = object()
        self.installed = type("Installed", (), {"sut": type("Sut", (), {"trusted": True, "label": "v1.6.1"})()})()

    def run(self, command: str, *args: str, **kwargs: Any) -> CliResult:
        """``show-live``: the settings block of the live state (unreadable keys left out)."""
        assert command == "show-live"
        self.world.logins += 1
        values = {**self.world.live, **self.world.trusted_lies}
        lines = ["Showing live resources:", "", "  settings {", '    plan = "free"']
        for key in sorted(values):
            if key not in self.world.trusted_unreadable:
                lines.append(f"    {key} = {json.dumps(values[key])}")
        lines.append("  }")
        return cli_result("show-live", "\n".join(lines) + "\n")


def round_trip(world: World, **kwargs: Any) -> tuple[WebSettingsRoundTrip, dict[str, list[Any]]]:
    """A round trip over ``world`` (REST = the REST-readable live values) and the bookkeeping calls it made."""
    calls: dict[str, list[Any]] = {"record": [], "restored": [], "trusted_restore": []}

    def trusted_restore(values: Mapping[str, Any]) -> Any:
        """Fallback restore: puts the values back."""
        calls["trusted_restore"].append(dict(values))
        world.live.update(values)
        return type("Applied", (), {"failed_patches": [], "aborted_validation": False})()

    defaults: dict[str, Any] = {
        "sut": FakeSut(world),
        "reader": TrustedWebReader(FakeTrustedCli(world)),
        "rest": lambda: {key: world.live[key] for key in mapping.REST_READABLE},
        "render": lambda values: "\n".join(mapping.jsonnet_fields(values)),
        "plan": "free",
        "run_id": RUN,
        "discussion_repo": REPO,
        "record": lambda values: calls["record"].append(dict(values)),
        "restored": lambda: calls["restored"].append(True),
        "trusted_restore": trusted_restore,
        "verify_timeout": 0,
        "sleep": lambda seconds: None,
    }
    defaults.update(kwargs)
    return WebSettingsRoundTrip(**defaults), calls


def step_names(report: Any) -> list[tuple[str, bool]]:
    """(name, ok) of the report's steps."""
    return [(step.name, step.ok) for step in report.steps]


# --- pure helpers -------------------------------------------------------------------------------------------------
def test_plan_toggles_on_free() -> None:
    """Booleans negated, branch renamed, discussions on with the fixture repo; 2FA and internal packages skipped."""
    toggles, skipped = plan_toggles(ORIGINAL, plan="free", run_id=RUN, discussion_repo=REPO)
    assert toggles == {
        "members_can_change_repo_visibility": True,
        "members_can_delete_repositories": False,
        "members_can_delete_issues": True,
        "readers_can_create_discussions": False,
        "members_can_create_teams": False,
        "default_branch_name": toggled_branch(RUN),
        "packages_containers_public": False,
        "members_can_change_project_visibility": False,
        "has_discussions": True,
        "discussion_source_repository": REPO,
    }
    assert set(skipped) == {"two_factor_requirement", "packages_containers_internal"}
    assert "2FA" in skipped["two_factor_requirement"] and "free" in skipped["packages_containers_internal"]


def test_plan_toggles_on_enterprise_and_edge_values() -> None:
    """Enterprise toggles internal packages; discussions on -> off; the run branch -> main; unread/unreadable keys."""
    values = {
        **ORIGINAL,
        "has_discussions": True,
        "discussion_source_repository": REPO,
        "default_branch_name": "e2e-t3c7z8a5",
    }
    values.pop("members_can_create_teams")
    values["readers_can_create_discussions"] = None
    toggles, skipped = plan_toggles(
        values,
        plan="enterprise",
        run_id=RUN,
        discussion_repo=None,
        readable=set(values) - {"members_can_delete_issues"},
    )
    assert toggles["packages_containers_internal"] is False
    assert toggles["has_discussions"] is False and toggles["discussion_source_repository"] is None
    assert toggles["default_branch_name"] == "main"
    assert "UNSET" in skipped["members_can_create_teams"] and "UNSET" in skipped["readers_can_create_discussions"]
    assert "did not return it" in skipped["members_can_delete_issues"]
    _toggles, no_repo = plan_toggles(ORIGINAL, plan="free", run_id=RUN, discussion_repo=None)
    assert "fixture repository" in no_repo["has_discussions"]


def test_combine_snapshot() -> None:
    """REST first, trusted values for the others; disagreements are problems; REST-only 2FA is a note."""
    rest = {"members_can_create_teams": True, "two_factor_requirement": False, "default_branch_name": None}
    trusted = {"members_can_create_teams": False, "has_discussions": True, "default_branch_name": "main"}
    snapshot = combine_snapshot(rest, trusted)
    assert snapshot.values["members_can_create_teams"] is True and snapshot.values["has_discussions"] is True
    assert snapshot.values["default_branch_name"] == "main"
    assert snapshot.problems == ["members_can_create_teams: REST says true, the trusted reader false"]
    assert any("REST returned null" in note for note in snapshot.notes)
    assert any("two_factor_requirement: read through REST only" in note for note in snapshot.notes)
    assert "packages_containers_public" in snapshot.unread
    assert "two_factor_requirement" not in snapshot.writable()


def test_expected_changes() -> None:
    """The discussion source is ignored while discussions are off in the configuration."""
    before = {"has_discussions": True, "discussion_source_repository": REPO, "members_can_create_teams": True}
    after = {"has_discussions": False, "discussion_source_repository": None, "members_can_create_teams": True}
    assert expected_changes(before, after, after) == ["has_discussions"]
    assert expected_changes(after, before, before) == ["has_discussions", "discussion_source_repository"]


# --- the scenario ---------------------------------------------------------------------------------------------------
def test_round_trip_happy_path() -> None:
    """Every step passes, the original values are back, 8 logins, the bookkeeping is called."""
    world = World()
    trip, calls = round_trip(world)
    report = trip.run()
    assert report.ok, report.summary()
    assert step_names(report) == [
        ("snapshot", True),
        ("set", True),
        ("verify", True),
        ("converge", True),
        ("restore", True),
        ("verify-restore", True),
    ]
    assert world.live == ORIGINAL and world.logins == 8
    assert calls["record"] == [{key: ORIGINAL[key] for key in mapping.WRITABLE}]
    assert calls["restored"] == [True] and calls["trusted_restore"] == []
    assert report.to_json()["toggles"]["default_branch_name"] == toggled_branch(RUN)
    assert "web settings round trip: ok" in report.summary()


def test_round_trip_marks_web_only_keys_self_checked_when_the_reader_is_the_sut() -> None:
    """BAT-17: when the trusted reader runs the SUT's own code, the toggled keys REST cannot read have no independent
    oracle: the report lists them as self-checked (summary and evidence); with another reset SUT nothing is listed."""
    world = World()
    trip, _calls = round_trip(world, reader_is_sut=True)
    report = trip.run()
    assert report.ok, report.summary()
    expected = sorted(key for key in report.toggles if key not in mapping.REST_READABLE)
    assert expected and report.self_checked == expected
    assert all(key in mapping.WRITABLE for key in expected)
    assert "self-checked only" in report.summary() and report.to_json()["self_checked"] == expected
    other, _ = round_trip(World())
    assert other.run().self_checked == []


def test_round_trip_restores_after_a_failed_set() -> None:
    """The SUT cannot apply: restore and verification still run, the report fails."""
    world = World(fail_applies=[1])
    report = round_trip(world)[0].run()
    assert not report.ok and report.restored
    assert step_names(report) == [("snapshot", True), ("set", False), ("restore", True), ("verify-restore", True)]
    assert "apply exit code 1" in report.failures()[0] and world.live == ORIGINAL


def test_round_trip_falls_back_to_the_trusted_restore() -> None:
    """The SUT cannot restore: the trusted CLI restores, both oracles verify it."""
    world = World(fail_applies=[2])
    trip, calls = round_trip(world)
    report = trip.run()
    assert report.restored and not report.ok
    assert [name for name, _ in step_names(report)][-3:] == ["restore", "trusted-restore", "verify-trusted-restore"]
    assert calls["trusted_restore"] and world.live == ORIGINAL and calls["restored"] == [True]


def test_round_trip_changes_nothing_when_the_oracles_disagree() -> None:
    """The trusted reader contradicts REST: no apply, no record, nothing to restore."""
    world = World(trusted_lies={"members_can_create_teams": False})
    trip, calls = round_trip(world)
    report = trip.run()
    assert not report.ok and not report.changed and world.applies == 0 and calls["record"] == []
    assert "the oracles disagree" in report.failures()[0]


def test_round_trip_detects_a_sut_reader_that_misses_a_setting() -> None:
    """The SUT's reader misses a setting the trusted reader reads: its plan lacks the key, the set step fails."""
    world = World(sut_unreadable={"members_can_change_project_visibility"})
    report = round_trip(world)[0].run()
    assert not report.ok and report.restored
    assert "expected" in report.failures()[0] and "members_can_change_project_visibility" in report.failures()[0]


def test_round_trip_detects_a_plan_that_does_not_converge() -> None:
    """The SUT's plan still wants a change after the apply: converge fails, the restore still runs."""
    world = World(stale_plan={"members_can_delete_issues": False})
    report = round_trip(world)[0].run()
    assert not report.ok and report.restored
    assert [name for name, ok in step_names(report) if not ok] == ["converge"]
    assert "members_can_delete_issues" in report.failures()[0] and world.live == ORIGINAL


def test_round_trip_reports_when_nothing_can_be_toggled() -> None:
    """No setting readable by otterdog: nothing changes."""
    world = World(trusted_unreadable=set(mapping.WEB_KEYS))
    report = round_trip(world, rest=dict)[0].run()
    assert not report.ok and not report.changed and world.applies == 0
    assert report.failures() == ["toggles: no web setting can be toggled on this target"]


def test_round_trip_survives_exceptions_in_steps() -> None:
    """A step raising (e.g. a blocked login gate) is a failed step; the restore steps run and are reported."""
    world = World()

    class Exploding(FakeSut):
        """The SUT's first apply raises."""

        def apply(self) -> CliResult:
            """Raise once."""
            if world.applies == 0:
                world.applies += 1
                raise RuntimeError("web logins of e2e-admin are blocked")
            return super().apply()

    report = round_trip(world, sut=Exploding(world))[0].run()
    assert step_names(report)[1] == ("set", False) and "blocked" in report.failures()[0]
    assert report.restored and world.live == ORIGINAL


@pytest.mark.parametrize("plan", ["free", "team", "enterprise"])
def test_toggles_cover_every_applicable_writable_setting(plan: str) -> None:
    """With everything readable, every writable setting the plan offers is toggled (plus the discussion source)."""
    toggles, _skipped = plan_toggles(ORIGINAL, plan=plan, run_id=RUN, discussion_repo=REPO)
    applicable: Iterable[str] = (s.key for s in mapping.WEB_SETTINGS if s.writable and s.applicable(plan))
    assert set(toggles) == set(applicable)
