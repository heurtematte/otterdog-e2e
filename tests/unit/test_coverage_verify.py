"""coverage_verify: the green live runs of the matrix's features (verified_on) and ``assist verify-coverage``."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from otterdog_acceptance import cli, coverage_verify
from otterdog_acceptance.coverage_verify import RunStamp, VerifyError
from otterdog_acceptance.report import RunData, load_coverage
from otterdog_acceptance.testing.fakes import make_settings

MATRIX = """\
# a comment that must stay
features:
  - id: repos.live
    area: repositories
    status: covered
    covered_by: [cli.repo.a, tests/cli/test_x.py::test_y]

  - id: repos.refused
    area: repositories
    status: partial
    covered_by: [cli.repo.b]
    verified_on:
      - {target: "free", sut: "v1.7.1", run: "toaaaa11", date: "2026-11-01"}

  # ==== a section comment
  - id: repos.offline-only
    area: repositories
    status: covered
    covered_by: [O-VAL-A]

  - id: repos.xfail-only
    area: repositories
    status: covered
    covered_by: [cli.repo.c]

  - id: repos.gap
    area: repositories
    status: gap
    covered_by: []
"""


def result(nodeid: str, outcome: str, tier: str = "cli", scenario: str | None = None) -> dict[str, Any]:
    """One results.jsonl line."""
    markers = ["offline"] if tier == "offline" else ["live"]
    return {"nodeid": nodeid, "outcome": outcome, "tier": tier, "scenario": scenario, "markers": markers}


def run_dir(tmp_path: Path, name: str, lines: list[dict[str, Any]], **run: Any) -> Path:
    """A run directory with run.json and results.jsonl."""
    directory = tmp_path / "runs" / name
    directory.mkdir(parents=True)
    data = {
        "run_id": name,
        "target": {"name": "free"},
        "sut": {"label": "v1.8.0", "is_dirty": False},
        "finished_at": "2026-11-25T15:00:00+00:00",
        **run,
    }
    (directory / "run.json").write_text(json.dumps(data))
    (directory / "results.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    return directory


GREEN = [
    result("tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.a]", "passed", scenario="cli.repo.a"),
    result("tests/cli/test_x.py::test_y[one]", "passed"),
    result("tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.b]", "failed", scenario="cli.repo.b"),
    result("tests/offline/test_scenarios.py::test_offline_scenario[O-VAL-A/s]", "passed", "offline", "O-VAL-A"),
    result("tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.c]", "xfailed", scenario="cli.repo.c"),
]


@pytest.fixture
def matrix_file(tmp_path: Path) -> Path:
    """A small matrix."""
    path = tmp_path / "coverage.yaml"
    path.write_text(MATRIX)
    return path


def verify(matrix_file: Path, directory: Path) -> coverage_verify.RunVerification:
    """verify_run on one directory."""
    return coverage_verify.verify_run(load_coverage(matrix_file), RunData.load(directory, coverage_file=matrix_file))


def test_a_run_verifies_the_features_whose_live_items_passed(matrix_file: Path, tmp_path: Path) -> None:
    """Passed live items verify (a node id matches its parametrizations), a failed one refuses, offline items and
    xfails alone verify nothing."""
    found = verify(matrix_file, run_dir(tmp_path, "tp2aaaa1", GREEN))
    assert found.stamp == RunStamp("free", "v1.8.0", "tp2aaaa1", "2026-11-25")
    assert found.verified == {
        "repos.live": [
            "tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.a]",
            "tests/cli/test_x.py::test_y[one]",
        ]
    }
    assert found.refused == {"repos.refused": ["tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.b]"]}


@pytest.mark.parametrize(
    ("lines", "run", "reason"),
    [
        (GREEN, {"sut": {"label": "dirty-1234", "is_dirty": True}}, "the SUT dirty-1234 has uncommitted changes"),
        (GREEN, {"finished_at": None, "started_at": None}, "run.json lacks the target, the SUT label or the date"),
        ([], {}, "no test result (results.jsonl)"),
        ([GREEN[3]], {}, "no live item ran"),
    ],
)
def test_runs_that_record_nothing(
    matrix_file: Path, tmp_path: Path, lines: list[dict[str, Any]], run: dict[str, Any], reason: str
) -> None:
    """A dirty SUT, an incomplete run.json, no results or no live result: nothing is recorded."""
    found = verify(matrix_file, run_dir(tmp_path, "tp2aaaa1", lines, **run))
    assert found.skipped == reason and found.verified == {}


def test_merge_keeps_the_newest_run_per_target_and_sut() -> None:
    """One entry per (target, sut), the newest wins, newest first, VERIFIED_KEEP at most, malformed ones dropped."""
    old = [
        {"target": "free", "sut": "v1.8.0", "run": "tp1aaaa1", "date": "2026-11-20"},
        {"target": "free", "sut": "v1.7.1", "run": "to9aaaa1", "date": "2026-11-01"},
        {"target": "free", "sut": "main-aaaaaaa", "run": "tp0aaaa1", "date": "2026-11-10"},
        {"target": "free", "sut": "main-bbbbbbb", "run": "tp0bbbb1", "date": "2026-11-12"},
        {"target": "free", "sut": 1.8},
    ]
    new = [{"target": "free", "sut": "v1.8.0", "run": "tp2aaaa1", "date": "2026-11-25"}]
    assert coverage_verify.merge_entries(old, new) == [
        {"target": "free", "sut": "v1.8.0", "run": "tp2aaaa1", "date": "2026-11-25"},
        {"target": "free", "sut": "main-bbbbbbb", "run": "tp0bbbb1", "date": "2026-11-12"},
        {"target": "free", "sut": "main-aaaaaaa", "run": "tp0aaaa1", "date": "2026-11-10"},
        {"target": "free", "sut": "v1.7.1", "run": "to9aaaa1", "date": "2026-11-01"},
    ]


def test_write_replaces_the_block_and_keeps_the_layout(matrix_file: Path) -> None:
    """The verified_on block becomes the last key of the feature, before the blank line and the section comment;
    the dates stay strings; an unknown feature is an error."""
    text = matrix_file.read_text()
    entry = {"target": "free", "sut": "v1.8.0", "run": "tp2aaaa1", "date": "2026-11-25"}
    written = coverage_verify.write_verified(text, {"repos.live": [entry], "repos.refused": [entry]})
    assert written.startswith("# a comment that must stay\n") and "  # ==== a section comment\n" in written
    assert (
        '    covered_by: [cli.repo.a, tests/cli/test_x.py::test_y]\n    verified_on:\n      - {target: "free", '
        'sut: "v1.8.0", run: "tp2aaaa1", date: "2026-11-25"}\n\n  - id: repos.refused\n'
    ) in written
    assert written.count("verified_on:") == 2 and "toaaaa11" not in written
    data = yaml.safe_load(written)
    assert data["features"][0]["verified_on"] == [entry] and data["features"][1]["verified_on"] == [entry]
    assert coverage_verify.write_verified(written, {}) == written
    with pytest.raises(VerifyError, match=r"features missing from the matrix: repos\.unknown"):
        coverage_verify.write_verified(text, {"repos.unknown": [entry]})


def test_updates_only_list_changed_features(matrix_file: Path, tmp_path: Path) -> None:
    """A feature whose list stays the same is not updated."""
    found = verify(matrix_file, run_dir(tmp_path, "tp2aaaa1", GREEN))
    current = coverage_verify.current_verified(yaml.safe_load(matrix_file.read_text()))
    updates = coverage_verify.verified_updates(current, [found])
    assert list(updates) == ["repos.live"]
    assert coverage_verify.verified_updates({"repos.live": updates["repos.live"]}, [found]) == {}


# --- the command ------------------------------------------------------------------------------------------------------
@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A checkout holding the small matrix; the page rendering is stubbed (it needs a whole checkout)."""
    root = tmp_path / "project"
    (root / "scenarios").mkdir(parents=True)
    (root / "docs").mkdir()
    (root / "scenarios" / "coverage.yaml").write_text(MATRIX)
    monkeypatch.setattr("otterdog_acceptance.settings.harness_settings", lambda environ=None: make_settings(root))
    monkeypatch.setattr(
        "otterdog_acceptance.coverage_matrix.load_matrix", lambda path: yaml.safe_load(path.read_text())
    )
    monkeypatch.setattr(
        "otterdog_acceptance.coverage_matrix.MatrixProject.render_markdown", lambda self, data: "# rendered\n"
    )
    return root


def test_command_dry_run_then_write(project: Path, tmp_path: Path) -> None:
    """A dry run reports, --write records and regenerates the page; a parent directory of runs is expanded."""
    run_dir(tmp_path, "tp2aaaa1", GREEN)
    (tmp_path / "runs" / "leaks.json").write_text("{}")
    runs = str(tmp_path / "runs")
    dry = CliRunner().invoke(cli.main, ["assist", "verify-coverage", runs])
    assert dry.exit_code == 0, dry.output
    assert "run tp2aaaa1 on free with v1.8.0 (2026-11-25): 1 feature(s) verified, 1 refused" in dry.output
    assert "  refused repos.refused: tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.b]" in dry.output
    assert "dry run, --write records them in" in dry.output and "tp2aaaa1" not in (project / MATRIX_PATH).read_text()
    written = CliRunner().invoke(cli.main, ["assist", "verify-coverage", runs, "--write", "--json"])
    assert written.exit_code == 0, written.output
    summary = json.loads(written.output)
    assert summary["written"] is True and list(summary["updates"]) == ["repos.live"]
    assert '"tp2aaaa1"' in (project / MATRIX_PATH).read_text()
    assert (project / "docs" / "coverage-matrix.md").read_text() == "# rendered\n"


def test_command_needs_a_run_directory(project: Path, tmp_path: Path) -> None:
    """Directories without run.json are a usage error."""
    (tmp_path / "empty").mkdir()
    found = CliRunner().invoke(cli.main, ["assist", "verify-coverage", str(tmp_path / "empty")])
    assert found.exit_code == 2 and "no run directory" in found.output


MATRIX_PATH = Path("scenarios") / "coverage.yaml"
