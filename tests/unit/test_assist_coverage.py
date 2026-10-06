"""otterdog_e2e.assist.coverage and ``otterdog-e2e assist coverage``: filters, ordering, gap outline needs, one
feature with what to imitate, the bundle and the usage errors."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_e2e import cli
from otterdog_e2e.assist import coverage
from otterdog_e2e.assist.bundle import AssistError, AssistUsageError
from otterdog_e2e.testing.fakes import make_settings

OUTLINE = {
    "scenario": "O-VAL-NEW",
    "file": "scenarios/offline/val-new.yaml",
    "steps": ["validate a ruleset without strict"],
    "assertions": ["the error names required_status_checks.strict"],
    "needs": ["available: validate.contains", "harness: a webhook delivery fixture", "target"],
}


def feature(fid: str, area: str, status: str, priority: str, tier: str, **extra: Any) -> dict[str, Any]:
    """A feature entry of the matrix."""
    entry: dict[str, Any] = {
        "id": fid,
        "area": area,
        "title": f"title of {fid}",
        "source": [f"otterdog/{fid}.py:1"],
        "operations": ["validate"],
        "min_plan": "free",
        "tier": tier,
        "ui_only": False,
        "priority": priority,
        "status": status,
        "covered_by": [],
        **extra,
    }
    if status != "covered" and "gap_outline" not in extra:
        entry["gap_outline"] = OUTLINE
    return entry


FEATURES = [
    feature("rulesets.a", "rulesets", "covered", "P0", "cli", covered_by=["cli.ruleset.x"]),
    feature("rulesets.b", "rulesets", "gap", "P1", "offline"),
    feature(
        "rulesets.c", "rulesets", "partial", "P0", "offline", covered_by=["O-VAL", "tests/offline/test_v.py::test_v"]
    ),
    feature("teams.a", "teams", "gap", "P0", "cli"),
    feature("teams.b", "teams", "partial", "P2", "cli", covered_by=["cli.team.x"]),
    feature("rulesets.d", "rulesets", "gap", "P0", "offline"),
]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A checkout with a small matrix, scenarios and a Python test."""
    data = {
        "schema_version": 1,
        "otterdog": {"ref": "9bdeb75f3e82a6cbd107d6bc3c9ec90392475c08"},
        "areas": [{"id": "rulesets", "title": "Rulesets"}, {"id": "teams", "title": "Teams"}],
        "features": FEATURES,
    }
    (tmp_path / "scenarios" / "cli").mkdir(parents=True)
    (tmp_path / "scenarios" / "offline").mkdir()
    (tmp_path / "tests" / "offline").mkdir(parents=True)
    (tmp_path / "scenarios" / "coverage.yaml").write_text(json.dumps(data))
    (tmp_path / "scenarios" / "cli" / "rules.yaml").write_text("id: cli.ruleset.x\ntags: [rulesets]\n")
    (tmp_path / "scenarios" / "offline" / "val.yaml").write_text("id: O-VAL\ntags: [offline, rulesets]\n")
    (tmp_path / "scenarios" / "offline" / "val-new.yaml").write_text("id: O-OTHER\ntags: [offline]\n")
    (tmp_path / "tests" / "offline" / "test_v.py").write_text("def test_v():\n    '''v'''\n")
    return tmp_path


def ids(listing: dict[str, Any]) -> list[str]:
    """Feature ids of a listing."""
    return [item["id"] for item in listing["features"]]


def test_default_lists_gaps_and_partials_by_priority_then_status(project: Path) -> None:
    """Default status gap,partial; P0 first, then gap before partial, then id."""
    listing = coverage.build_coverage(project, coverage.parse_query())
    assert ids(listing) == ["rulesets.d", "teams.a", "rulesets.c", "rulesets.b", "teams.b"]
    assert listing["totals"] == {"features": 6, "covered": 1, "partial": 2, "gap": 3}
    assert listing["filters"]["status"] == ["gap", "partial"]


@pytest.mark.parametrize(
    ("options", "expected"),
    [
        ({"status": ["gap"]}, ["rulesets.d", "teams.a", "rulesets.b"]),
        ({"status": ["all"]}, ["rulesets.d", "teams.a", "rulesets.c", "rulesets.a", "rulesets.b", "teams.b"]),
        ({"status": ["covered,partial"]}, ["rulesets.c", "rulesets.a", "teams.b"]),
        ({"priority": ["P1", "P2"]}, ["rulesets.b", "teams.b"]),
        ({"area": ["teams"]}, ["teams.a", "teams.b"]),
        ({"tier": ["offline"], "priority": ["P0"]}, ["rulesets.d", "rulesets.c"]),
        ({"area": ["rulesets"], "tier": ["cli"]}, []),
    ],
)
def test_filters(project: Path, options: dict[str, Any], expected: list[str]) -> None:
    """Filters combine (AND); values are comma separated or repeated."""
    assert ids(coverage.build_coverage(project, coverage.parse_query(**options))) == expected


def test_needs_are_split_into_available_and_missing(project: Path) -> None:
    """``available:`` needs name what the harness provides (prefix removed), the others are missing."""
    listing = coverage.build_coverage(project, coverage.parse_query(status=["gap"]))
    item = listing["features"][0]
    assert item["needs_available"] == ["validate.contains"]
    assert item["needs_missing"] == ["harness: a webhook delivery fixture", "target"]
    assert item["gap_outline"]["scenario"] == "O-VAL-NEW"


def test_one_feature_with_what_to_imitate(project: Path) -> None:
    """--feature: filters ignored, covering items of the area (same tier first), tagged scenarios, the outline's
    file and scenario state, commands (offline run for an offline feature)."""
    listing = coverage.build_coverage(project, coverage.parse_query(feature="rulesets.b", status=["covered"]))
    (item,) = listing["features"]
    imitate = item["imitate"]
    assert [entry["item"] for entry in imitate["same_area"]] == [
        "O-VAL",
        "tests/offline/test_v.py::test_v",
        "cli.ruleset.x",
    ]
    assert imitate["same_area"][0] == {
        "item": "O-VAL",
        "tier": "offline",
        "files": ["scenarios/offline/val.yaml"],
        "features": ["rulesets.c"],
    }
    assert imitate["same_area"][1]["files"] == ["tests/offline/test_v.py"]
    assert [entry["id"] for entry in imitate["tagged"]] == ["O-VAL", "cli.ruleset.x"] and imitate["tags"] == [
        "rulesets"
    ]
    assert imitate["outline_file"] == {"path": "scenarios/offline/val-new.yaml", "exists": True}
    assert imitate["outline_scenario"] == {"id": "O-VAL-NEW", "exists": False}
    assert listing["commands"][-1] == "otterdog-e2e run --suite offline --sut release:latest --scenario O-VAL-NEW"
    assert ".venv/bin/python tests/unit/test_coverage_matrix.py --write" in listing["commands"]
    live = coverage.build_coverage(project, coverage.parse_query(feature="teams.a"))
    assert "--target <instance>" in live["commands"][-1] and "the user runs it" in live["commands"][-1]


def test_usage_errors(project: Path) -> None:
    """Unknown values, areas and features are usage errors (close feature ids suggested)."""
    with pytest.raises(AssistUsageError, match="--status: unknown value"):
        coverage.parse_query(status=["gaps"])
    with pytest.raises(AssistUsageError, match="--priority"):
        coverage.parse_query(priority=["P3"])
    with pytest.raises(AssistUsageError, match="--tier"):
        coverage.parse_query(tier=["unit"])
    with pytest.raises(AssistUsageError, match="unknown area"):
        coverage.build_coverage(project, coverage.parse_query(area=["nope"]))
    with pytest.raises(AssistUsageError, match=r"unknown feature 'rulesets\.x' \(did you mean rulesets"):
        coverage.build_coverage(project, coverage.parse_query(feature="rulesets.x"))
    (project / "scenarios" / "coverage.yaml").write_text("a: [\n")
    with pytest.raises(AssistError, match="cannot be read"):
        coverage.build_coverage(project, coverage.parse_query())


def test_bundle_and_markdown(project: Path, tmp_path: Path) -> None:
    """coverage.json and coverage.md below <parent>/coverage; the markdown lists the table and the outlines."""
    listing = coverage.build_coverage(project, coverage.parse_query(feature="rulesets.b"))
    path, summary = coverage.write_coverage(listing, tmp_path / "assist")
    assert path == tmp_path / "assist" / "coverage" and summary["files"] == ["coverage.json", "coverage.md"]
    assert summary["features"] == [
        {"id": "rulesets.b", "status": "gap", "priority": "P1", "tier": "offline", "min_plan": "free", "ui_only": False}
    ]
    markdown = (path / "coverage.md").read_text()
    assert (
        "Feature `rulesets.b`." in markdown
        and "- Suggested: `O-VAL-NEW` in `scenarios/offline/val-new.yaml`" in markdown
    )
    assert "    - available: validate.contains" in markdown and "    - missing: target" in markdown
    assert "- Outline file `scenarios/offline/val-new.yaml`: exists (extend it)" in markdown
    assert json.loads((path / "coverage.json").read_text())["features"][0]["id"] == "rulesets.b"


# --- the command -------------------------------------------------------------------------------------------------------
@pytest.fixture
def settings(project: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Settings of the checkout."""
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(project))
    return project


def test_command_lists_and_writes_the_bundle(settings: Path) -> None:
    """One line per feature, a count, the bundle path."""
    result = CliRunner().invoke(cli.main, ["assist", "coverage", "--status", "gap", "--priority", "P0"])
    assert result.exit_code == 0, result.output
    assert result.output.splitlines()[:3] == [
        "P0 gap      offline    rulesets.d",
        "P0 gap      cli        teams.a",
        "2 feature(s) of 6",
    ]
    assert f"bundle: {settings / 'artifacts' / 'assist' / 'coverage'}" in result.output


def test_command_json_and_out(settings: Path, tmp_path: Path) -> None:
    """--json prints the summary; --out chooses the parent directory."""
    result = CliRunner().invoke(
        cli.main, ["assist", "coverage", "--feature", "teams.a", "--json", "--out", str(tmp_path / "o")]
    )
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    assert summary["bundle"] == str(tmp_path / "o" / "coverage") and summary["filters"]["feature"] == "teams.a"


@pytest.mark.parametrize("args", [["--status", "nope"], ["--area", "nope"], ["--feature", "nope"], ["--tier", "unit"]])
def test_command_usage_errors(settings: Path, args: list[str]) -> None:
    """Exit 2 for unknown filter values and features."""
    result = CliRunner().invoke(cli.main, ["assist", "coverage", *args])
    assert result.exit_code == 2, result.output
