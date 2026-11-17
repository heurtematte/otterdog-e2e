"""compare-runs, the check of the harness itself: two runs of one SUT by two harness revisions, item by item; and the
harness revision every run records (run.json ``harness``)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_acceptance.cli import main
from otterdog_acceptance.compare_runs import compare_runs, render
from otterdog_acceptance.context.helpers import MAX_DIRTY_FILES, harness_revision
from otterdog_acceptance.report import harness_text

V171 = {"label": "v1.7.1", "sha": "2" * 40, "version": "1.7.1", "dirty_hash": None, "runtime": "host", "trusted": True}
MAIN = {**V171, "label": "sha-a196494", "sha": "a" * 40, "version": "1.8.0.dev27"}


def write_run(
    root: Path, run_id: str, outcomes: dict[str, str], *, sut: Any = V171, commit: str = "1" * 40, **run: Any
) -> Path:
    """A run directory: run.json (SUT, harness) and one results.jsonl line per item (outcome, reason)."""
    directory = root / run_id
    directory.mkdir(parents=True)
    info = {"run_id": run_id, "harness_version": "0.1.0", "harness": {"commit": commit, "dirty": False}, "sut": sut}
    (directory / "run.json").write_text(json.dumps({**info, **run}))
    lines = [
        {"nodeid": f"tests/offline/test_x.py::{name}", "outcome": outcome, "when": "call", "tier": "offline"}
        | ({"reason": "KB-001: t"} if outcome.startswith("x") else {})
        for name, outcome in outcomes.items()
    ]
    (directory / "results.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines))
    return directory


def test_unchanged_outcomes_exit_0(tmp_path: Path) -> None:
    """Same SUT, same outcome for every item run by both: exit 0, whatever the harness commits."""
    outcomes = {"test_a": "passed", "test_b": "xfailed", "test_c": "skipped"}
    baseline = write_run(tmp_path, "base0001", outcomes)
    run = write_run(tmp_path, "head0001", outcomes, commit="9" * 40)
    result = CliRunner().invoke(main, ["compare-runs", str(baseline), str(run)])
    assert result.exit_code == 0, result.output
    assert "**UNCHANGED**: 3 item(s) run by both, 3 with the same outcome" in result.output
    assert "0.1.0 @ `111111111111`" in result.output and "0.1.0 @ `999999999999`" in result.output


def test_outcome_changes_exit_1_and_name_the_items(tmp_path: Path) -> None:
    """An xfail that now passes (the harness lost the bug) or a pass that now fails is a change; items of one side
    only are listed apart and are not changes."""
    baseline = write_run(tmp_path, "base0001", {"test_a": "passed", "test_b": "xfailed", "test_gone": "passed"})
    run = write_run(tmp_path, "head0001", {"test_a": "failed", "test_b": "xpassed", "test_new": "passed"})
    comparison = compare_runs(baseline, run)
    assert [(change.nodeid.split("::")[-1], change.baseline, change.run) for change in comparison.changes] == [
        ("test_a", "passed", "failed"),
        ("test_b", "xfailed", "xpassed"),
    ]
    assert comparison.only_baseline == ["tests/offline/test_x.py::test_gone"]
    assert comparison.only_run == ["tests/offline/test_x.py::test_new"]
    text = render(comparison)
    assert "**2 OUTCOME CHANGE(S)**: 2 item(s) run by both, 0 with the same outcome; 1 only in the baseline" in text
    assert "| `tests/offline/test_x.py::test_b` | xfailed | xpassed | KB-001: t |" in text
    result = CliRunner().invoke(main, ["compare-runs", "--json", str(baseline), str(run)])
    assert result.exit_code == 1
    data = json.loads(result.output)
    assert data["comparable"] and data["unchanged"] == 0 and len(data["changes"]) == 2
    assert data["baseline"]["harness"]["commit"] == "1" * 40


@pytest.mark.parametrize(
    ("baseline_run", "run_run", "problem"),
    [
        ({}, {"sut": MAIN}, "different SUT under test: `v1.7.1`"),
        ({}, {"sut": "release:latest"}, "the SUT under test is not a resolved SUT in both run.json files"),
        ({}, {"base": V171}, "only the run has a base SUT: `v1.7.1`"),
        ({"target": "enterprise"}, {}, "different targets: enterprise vs none"),
    ],
)
def test_runs_of_different_suts_are_not_comparable(
    tmp_path: Path, baseline_run: dict[str, Any], run_run: dict[str, Any], problem: str
) -> None:
    """Only one otterdog on both sides tells the harness apart: other SUTs or targets exit 2 without a verdict."""
    baseline = write_run(tmp_path, "base0001", {"test_a": "passed"}, **baseline_run)
    run = write_run(tmp_path, "head0001", {"test_a": "failed"}, **run_run)
    result = CliRunner().invoke(main, ["compare-runs", str(baseline), str(run)])
    assert result.exit_code == 2
    assert "**NOT COMPARABLE**" in result.output and problem in result.output
    assert "OUTCOME CHANGE" not in result.output


def git(root: Path, *args: str) -> None:
    """Run git in ``root`` (no user configuration needed)."""
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        check=True,
        capture_output=True,
    )


def test_harness_revision_names_the_commit_and_the_local_changes_that_matter(tmp_path: Path) -> None:
    """run.json ``harness``: HEAD, and the local changes below the paths that change results (an untracked scenario
    counts; a note at the root does not)."""
    git(tmp_path, "init", "-q")
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "a.py").write_text("x = 1\n")
    git(tmp_path, "add", "-A")
    git(tmp_path, "commit", "-q", "-m", "init", "--no-gpg-sign")  # a throwaway repository of the test
    clean = harness_revision(tmp_path)
    assert clean is not None and len(clean["commit"]) == 40
    assert clean["dirty"] is False and clean["dirty_count"] == 0 and clean["dirty_files"] == []
    (tmp_path / "notes.txt").write_text("not a harness file\n")
    assert harness_revision(tmp_path)["dirty"] is False  # type: ignore[index]
    (tmp_path / "src" / "a.py").write_text("x = 2\n")
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "new.yaml").write_text("id: new\n")
    dirty = harness_revision(tmp_path)
    assert dirty is not None and dirty["dirty"] is True and dirty["dirty_count"] == 2
    assert sorted(dirty["dirty_files"]) == ["scenarios/new.yaml", "src/a.py"]
    assert MAX_DIRTY_FILES >= 2
    assert harness_revision(tmp_path / "src") is not None  # any directory of the checkout
    outside = tmp_path.parent / f"{tmp_path.name}-not-a-checkout"
    outside.mkdir()
    assert harness_revision(outside) is None


def test_harness_text() -> None:
    """The Harness row of the run summary: version, short commit, local changes; nothing for older run.json files."""
    assert harness_text({}) is None
    assert harness_text({"harness_version": "0.1.0"}) == "0.1.0"
    commit = {"commit": "a" * 40, "dirty": False}
    assert harness_text({"harness_version": "0.1.0", "harness": commit}) == "0.1.0 @ `aaaaaaaaaaaa`"
    dirty = {**commit, "dirty": True, "dirty_count": 3}
    assert harness_text({"harness_version": "0.1.0", "harness": dirty}) == "0.1.0 @ `aaaaaaaaaaaa`, 3 local change(s)"
