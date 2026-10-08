"""Scenario collection helpers: marks, parametrization, idempotent mark application and selection (SPEC 12.4)."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.scenarios.collect import (
    ORG_LEVEL_EXTRA_TIMEOUT,
    TAGS_EXEMPT_TIERS,
    TIER_TIMEOUTS,
    apply_scenario_marks,
    collect_scenarios,
    generate_scenario_tests,
    item_scenario,
    item_selected,
    scenario_marks,
    scenario_params,
    scenario_selected,
    split_option,
)
from otterdog_e2e.scenarios.model import Scenario, ScenarioError, load_scenario

LIVE = """
id: cli.team.basic
title: team
min_plan: team
requires: [custom_properties]
identities: [author]
tags: [teams, smoke]
known_bug: KB-003
org_level: true
steps: [{fragments: {}}]
"""
OFFLINE = "id: O-VAL-OK\ntitle: ok\ntags: [offline]\nsteps: [{fragments: {}}]\n"


def write(root: Path, relative: str, text: str) -> Path:
    """Write a dedented file."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return path


def marks_by_name(marks: list[pytest.MarkDecorator]) -> dict[str, tuple[Any, ...]]:
    """Mark name -> args."""
    return {mark.name: mark.args for mark in marks}


def test_live_scenario_marks(tmp_path: Path) -> None:
    """live, plan(>= min_plan), requires, identities, tags, known_bug, org_level, scenario, timeout."""
    scenario = load_scenario(write(tmp_path, "cli/team.yaml", LIVE))
    assert marks_by_name(scenario_marks(scenario)) == {
        "live": (),
        "plan": ("team", "enterprise"),
        "requires": ("custom_properties",),
        "identities": ("author",),
        "tags": ("teams", "smoke"),
        "known_bug": ("KB-003",),
        "org_level": (),
        "scenario": ("cli.team.basic",),
        "timeout": (TIER_TIMEOUTS["cli"] + ORG_LEVEL_EXTRA_TIMEOUT,),  # org_level: a full reset as cleanup
    }


def test_scenario_timeout_key_overrides_the_tier_timeout(tmp_path: Path) -> None:
    """A scenario's ``timeout`` replaces the tier (and org_level) timeout; it must be a positive integer."""
    scenario = load_scenario(write(tmp_path, "cli/team.yaml", LIVE + "timeout: 960\n"))
    assert scenario.timeout == 960 and marks_by_name(scenario_marks(scenario))["timeout"] == (960,)
    plain = load_scenario(write(tmp_path, "cli/plain.yaml", LIVE.replace("org_level: true", "org_level: false")))
    assert marks_by_name(scenario_marks(plain))["timeout"] == (TIER_TIMEOUTS["cli"],)
    for bad in ("0", "-5", "1.5", "true", "'600'"):
        with pytest.raises(ScenarioError, match="timeout"):
            load_scenario(write(tmp_path, "cli/bad.yaml", LIVE + f"timeout: {bad}\n"))


def test_offline_scenario_marks(tmp_path: Path) -> None:
    """Offline scenarios are never live and carry no plan gate."""
    scenario = load_scenario(write(tmp_path, "offline/ok.yaml", OFFLINE))
    assert marks_by_name(scenario_marks(scenario)) == {
        "offline": (),
        "tags": ("offline",),
        "scenario": ("O-VAL-OK",),
        "timeout": (300,),
    }


class FakeMetafunc:
    """pytest.Metafunc stand-in recording parametrize calls."""

    def __init__(self, fixturenames: list[str]) -> None:
        """Requested fixtures."""
        self.fixturenames = fixturenames
        self.calls: list[tuple[str, list[Any]]] = []

    def parametrize(self, argnames: str, argvalues: list[Any], **kwargs: Any) -> None:
        """Record."""
        self.calls.append((argnames, list(argvalues)))


def test_generate_scenario_tests(tmp_path: Path) -> None:
    """One parameter per scenario of the directories, id = scenario id, marks attached."""
    write(tmp_path, "cli/teams/team.yaml", LIVE)
    write(tmp_path, "other/r.yaml", "id: regression.one\ntier: cli\ntitle: r\nsteps: [{fragments: {}}]\n")
    metafunc = FakeMetafunc(["scenario", "tmp_path"])
    generate_scenario_tests(metafunc, [tmp_path / "cli", tmp_path / "other"], tier="cli")  # type: ignore[arg-type]
    ((argnames, params),) = metafunc.calls
    assert argnames == "scenario" and [p.id for p in params] == ["cli.team.basic", "regression.one"]
    assert isinstance(params[0].values[0], Scenario) and "live" in [m.name for m in params[0].marks]
    untouched = FakeMetafunc(["tmp_path"])
    generate_scenario_tests(untouched, [tmp_path / "cli"])  # type: ignore[arg-type]
    assert untouched.calls == []


def test_generate_scenario_tests_per_step(tmp_path: Path) -> None:
    """per_step: one parameter per step, the scenario narrowed to it (a case: same id, metadata and marks, ``case``
    = the step), id = <scenario id>/<step>."""
    write(tmp_path, "offline/repo/val.yaml", OFFLINE.replace("[{fragments: {}}]", "[{name: a}, {name: b}]"))
    metafunc = FakeMetafunc(["scenario"])
    generate_scenario_tests(metafunc, [tmp_path / "offline"], tier="offline", per_step=True)  # type: ignore[arg-type]
    ((_, params),) = metafunc.calls
    assert [p.id for p in params] == ["O-VAL-OK/a", "O-VAL-OK/b"]
    cases = [p.values[0] for p in params]
    assert [(case.id, case.case, [step.name for step in case.steps]) for case in cases] == [
        ("O-VAL-OK", "a", ["a"]),
        ("O-VAL-OK", "b", ["b"]),
    ]
    assert marks_by_name(list(params[1].marks))["scenario"] == ("O-VAL-OK",)
    assert scenario_params(cases[:1])[0].id == "O-VAL-OK/a"


def test_collect_scenarios_refuses_duplicates_across_directories(tmp_path: Path) -> None:
    """Ids are unique across all the directories of a test module."""
    write(tmp_path, "cli/a.yaml", LIVE)
    write(tmp_path, "other/b.yaml", "tier: cli\n" + textwrap.dedent(LIVE).lstrip("\n"))
    with pytest.raises(ScenarioError, match="duplicate scenario id"):
        collect_scenarios([tmp_path / "cli", tmp_path / "other"])
    assert collect_scenarios([tmp_path / "missing"]) == []


class FakeItem:
    """pytest.Item stand-in with a callspec and markers."""

    def __init__(self, params: dict[str, Any], marks: list[pytest.Mark] | None = None) -> None:
        """Parametrized item."""
        self.callspec = type("Callspec", (), {"params": params})()
        self.own_markers: list[pytest.Mark] = list(marks or [])

    def iter_markers(self, name: str | None = None) -> Any:
        """Markers with that name."""
        return (mark for mark in self.own_markers if name is None or mark.name == name)

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        """Append."""
        self.own_markers.append(marker.mark)


def test_apply_scenario_marks_is_idempotent(tmp_path: Path) -> None:
    """Marks are added once (items parametrized through scenario_params already carry them)."""
    scenario = load_scenario(write(tmp_path, "cli/team.yaml", LIVE))
    item = FakeItem({"scenario": scenario})
    apply_scenario_marks(item)  # type: ignore[arg-type]
    count = len(item.own_markers)
    apply_scenario_marks(item)  # type: ignore[arg-type]
    assert count == len(scenario_marks(scenario)) == len(item.own_markers)
    assert item_scenario(item) is scenario  # type: ignore[arg-type]
    plain = FakeItem({"other": 1})
    apply_scenario_marks(plain)  # type: ignore[arg-type]
    assert plain.own_markers == [] and item_scenario(plain) is None  # type: ignore[arg-type]
    marked = FakeItem({"scenario": scenario}, [m.mark for m in scenario_params([scenario])[0].marks])
    apply_scenario_marks(marked)  # type: ignore[arg-type]
    assert len(marked.own_markers) == count


@pytest.mark.parametrize(
    ("globs", "tags", "selected"),
    [
        ((), (), True),
        (("cli.*",), (), True),
        (("O-*", "cli.team.*"), (), True),
        (("O-*",), (), False),
        ((), ("teams",), True),
        ((), ("webapp", "smoke"), True),
        ((), ("webapp",), False),
        (("cli.*",), ("webapp",), False),
        (("CLI.*",), (), False),
    ],
)
def test_scenario_selected(tmp_path: Path, globs: tuple[str, ...], tags: tuple[str, ...], selected: bool) -> None:
    """Any glob (case-sensitive fnmatch on the id) and any tag; both filters must pass when given."""
    scenario = load_scenario(write(tmp_path, "cli/team.yaml", LIVE))
    assert scenario_selected(scenario, globs=globs, tags=tags) is selected


def test_scenario_selected_by_case(tmp_path: Path) -> None:
    """A case is selected by a glob on its scenario id (every case) or on <scenario id>/<step> (that case only)."""
    scenario = load_scenario(write(tmp_path, "offline/repo/val.yaml", OFFLINE.replace("[{fragments: {}}]", "[{}, {}]")))
    first, second = scenario.cases()
    assert scenario_selected(first, globs=("O-VAL-OK",)) and scenario_selected(second, globs=("O-VAL-*",))
    assert scenario_selected(first, globs=("O-VAL-OK/step-1",)) and not scenario_selected(second, globs=("*/step-1",))
    assert not scenario_selected(scenario, globs=("O-VAL-OK/step-1",)), "the whole scenario is not that case"


def test_scenario_selected_exemption_and_change_scenarios(tmp_path: Path) -> None:
    """tags_exempt (tests/unit, tests/offline) ignores --e2e-tags, never --e2e-scenario; the scenarios referencing the
    change under test pass the tags filter like tagged items."""
    scenario = load_scenario(write(tmp_path, "cli/team.yaml", LIVE))
    assert scenario_selected(scenario, tags=("webapp",), tags_exempt=True)
    assert not scenario_selected(scenario, globs=("O-*",), tags=("webapp",), tags_exempt=True)
    assert scenario_selected(scenario, tags=("webapp",), extra_scenarios=("cli.team.*",))
    assert not scenario_selected(scenario, globs=("O-*",), tags=("webapp",), extra_scenarios=("cli.team.*",))
    assert not scenario_selected(scenario, tags=("webapp",), extra_scenarios=("cli.repo.*",))
    assert sorted(TAGS_EXEMPT_TIERS) == ["offline", "unit"]


@pytest.mark.parametrize(
    ("scenario_id", "tags", "kwargs", "selected"),
    [
        (None, (), {}, True),  # no filter: everything
        (None, (), {"globs": ["cli.*"]}, False),  # --e2e-scenario deselects items without a scenario id
        (None, (), {"globs": ["cli.*"], "tags_exempt": True}, False),  # ... unit/offline items included
        (None, (), {"tags": ["smoke"], "tags_exempt": True}, True),  # unit/offline items ignore --e2e-tags
        (None, ("smoke",), {"tags": ["webapp", "smoke"]}, True),  # tags: OR
        (None, ("teams",), {"tags": ["webapp", "smoke"]}, False),
        ("cli.repo.basic", (), {"globs": ["O-*", "cli.repo.*"]}, True),  # globs: OR
        ("cli.repo.basic", ("repo",), {"globs": ["cli.*"], "tags": ["webapp"]}, False),  # AND between the filters
        ("cli.repo.basic", ("repo",), {"globs": ["cli.*"], "tags": ["repo"]}, True),
        ("cli.repo.basic", (), {"tags": ["webapp"], "extra_scenarios": ["cli.repo.*"]}, True),
        (None, (), {"tags": ["webapp"], "extra_scenarios": ["*"]}, False),  # extra scenarios need a scenario id
        ("cli.repo.basic", ("repo",), {"globs": [" ", ""], "tags": ["", " "]}, True),  # blank values are ignored
        ("O-VAL", (), {"globs": ["O-VAL/limits"], "case_id": "O-VAL/limits"}, True),  # a glob on the case id
        ("O-VAL", (), {"globs": ["O-VAL/limits"], "case_id": "O-VAL/topics"}, False),
        ("O-VAL", (), {"globs": ["O-VAL"], "case_id": "O-VAL/topics"}, True),  # every case of the scenario
    ],
)
def test_item_selected(scenario_id: str | None, tags: tuple[str, ...], kwargs: dict[str, Any], selected: bool) -> None:
    """The shared rule of the plugin and scenario_selected: OR inside a filter, AND between them."""
    assert item_selected(scenario_id, tags, **kwargs) is selected


def test_split_option() -> None:
    """Comma separated option values."""
    assert split_option("a, b,,c ") == ["a", "b", "c"]
    assert split_option(["a,b", " c"]) == ["a", "b", "c"]
    assert split_option(None) == [] and split_option("") == []


def test_every_e2e_tier_directory_has_a_timeout() -> None:
    """The plugin gives each item of a tier directory its tier timeout (scenario items: their scenario's): every e2e
    tier has one; a web_ui item outlives one web command at the runner's own timeout (Firefox, page loads, two bot
    logins)."""
    from otterdog_e2e.otterdog.runner import WEB_TIMEOUT
    from otterdog_e2e.pytest_plugin import TIER_DIRS

    tiers = {"offline", "cli", "webhooks", "webapp", "enterprise", "differential", "web_ui"}
    assert tiers <= set(TIER_TIMEOUTS) <= set(TIER_DIRS) - {"unit"}
    assert TIER_TIMEOUTS["web_ui"] > WEB_TIMEOUT
    assert all(isinstance(seconds, int) and seconds > 0 for seconds in TIER_TIMEOUTS.values())
