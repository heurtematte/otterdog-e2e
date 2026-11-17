"""Outcome comparison of two runs on one SUT (``otterdog-acceptance compare-runs``): the check of the harness itself.

The differential tier runs two otterdog versions with one harness, so a delta can only come from otterdog. This is the
converse: one otterdog (the same resolved SUT in both run.json files) run by two harness revisions (run.json
``harness``, context.helpers.harness_revision), so an item whose outcome changed (passed, failed, error, skipped,
xfailed, xpassed) can only come from the harness. A harness change that makes a test pass for a wrong reason (an
assertion that no longer checks anything), stops reproducing a known bug or breaks a fixture shows up here, where a
single run of the new harness stays green. Every change must be explained by the harness commits between the runs;
items run by one side only (new, removed or deselected tests) are listed apart and are not changes.

Two runs are comparable when their SUTs are the same otterdog (SUT_KEYS of the resolved SUT entries, base SUT
included) and their targets the same (offline runs have none). ``make harness-check`` runs the offline tier with the
harness of a base revision and of the working tree, then this comparison.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from otterdog_acceptance.differential import md_cell, md_code
from otterdog_acceptance.report import RunData, TestRecord, harness_text, sut_text

# the keys of a resolved SUT entry (ResolvedSut.to_json()) that make two entries the same otterdog
SUT_KEYS = ("label", "sha", "version", "dirty_hash", "runtime")
SUT_ROLES = (("sut", "SUT under test"), ("base", "base SUT"))
REASON_LIMIT = 160


@dataclass
class OutcomeChange:
    """An item run by both runs whose outcome differs; ``reason`` is the run's skip/xfail reason or failure."""

    nodeid: str
    baseline: str
    run: str
    reason: str | None = None


@dataclass
class RunComparison:
    """The outcome changes between a baseline run and a run, the items of one side only, and why the two runs are not
    comparable (``problems``: different SUTs or targets)."""

    baseline: RunData
    run: RunData
    changes: list[OutcomeChange] = field(default_factory=list)
    only_baseline: list[str] = field(default_factory=list)
    only_run: list[str] = field(default_factory=list)
    unchanged: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def comparable(self) -> bool:
        """True when both runs ran the same SUTs on the same target."""
        return not self.problems

    def to_json(self) -> dict[str, Any]:
        """JSON form (``compare-runs --json``)."""
        return {
            "baseline": _side(self.baseline),
            "run": _side(self.run),
            "comparable": self.comparable,
            "problems": list(self.problems),
            "unchanged": self.unchanged,
            "changes": [vars(change) for change in self.changes],
            "only_baseline": list(self.only_baseline),
            "only_run": list(self.only_run),
        }


def sut_identity(entry: Any) -> dict[str, Any] | None:
    """The SUT_KEYS of a resolved SUT entry of run.json; None for anything else (a spec string is not pinned)."""
    if not isinstance(entry, Mapping):
        return None
    return {key: entry.get(key) for key in SUT_KEYS}


def comparability_problems(baseline: RunData, run: RunData) -> list[str]:
    """Why two runs do not test the same otterdog the same way: a SUT role resolved differently (or not recorded as a
    resolved SUT) or a different target."""
    problems = []
    for key, label in SUT_ROLES:
        left, right = baseline.run.get(key), run.run.get(key)
        if left is None and right is None:
            continue
        if left is None or right is None:
            problems.append(f"only the {'run' if left is None else 'baseline'} has a {label}: {_sut(left or right)}")
        elif sut_identity(left) is None or sut_identity(right) is None:
            problems.append(f"the {label} is not a resolved SUT in both run.json files ({_sut(left)} vs {_sut(right)})")
        elif sut_identity(left) != sut_identity(right):
            problems.append(f"different {label}: {_sut(left)} vs {_sut(right)}")
    if baseline.target != run.target:
        problems.append(f"different targets: {baseline.target or 'none'} vs {run.target or 'none'}")
    return problems


def compare_runs(baseline_dir: Path, run_dir: Path) -> RunComparison:
    """Compare the outcome of every item of two run directories (results.jsonl), baseline first."""
    baseline = RunData.load(baseline_dir, coverage_file=None)
    run = RunData.load(run_dir, coverage_file=None)
    comparison = RunComparison(baseline, run, problems=comparability_problems(baseline, run))
    before = {record.nodeid: record for record in baseline.records}
    after = {record.nodeid: record for record in run.records}
    for nodeid, record in after.items():
        old = before.get(nodeid)
        if old is None:
            comparison.only_run.append(nodeid)
        elif old.outcome == record.outcome:
            comparison.unchanged += 1
        else:
            comparison.changes.append(OutcomeChange(nodeid, old.outcome, record.outcome, _reason(record)))
    comparison.only_baseline = [nodeid for nodeid in before if nodeid not in after]
    return comparison


def render(comparison: RunComparison) -> str:
    """Markdown report: both runs, the verdict, the outcome changes, then the items of one side only."""
    baseline, run = comparison.baseline, comparison.run
    rows = [
        ("Run", md_code(baseline.run_id), md_code(run.run_id)),
        ("Harness", harness_text(baseline.run) or "-", harness_text(run.run) or "-"),
    ]
    for key, label in SUT_ROLES:
        if baseline.run.get(key) is not None or run.run.get(key) is not None:
            rows.append((label[0].upper() + label[1:], _sut(baseline.run.get(key)), _sut(run.run.get(key))))
    if baseline.target or run.target:
        rows.append(("Target", md_code(baseline.target or "none"), md_code(run.target or "none")))
    lines = [f"# Harness comparison: {md_code(baseline.run_id)} -> {md_code(run.run_id)}", ""]
    lines += ["| | Baseline | Run |", "|---|---|---|"]
    lines += [f"| {label} | {left} | {right} |" for label, left, right in rows]
    lines.append("")
    if not comparison.comparable:
        lines.append("**NOT COMPARABLE**: the runs did not test the same otterdog the same way.")
        lines += ["", *(f"- {md_cell(problem)}" for problem in comparison.problems)]
        return "\n".join(lines) + "\n"
    both = comparison.unchanged + len(comparison.changes)
    verdict = "**UNCHANGED**" if not comparison.changes else f"**{len(comparison.changes)} OUTCOME CHANGE(S)**"
    lines.append(
        f"{verdict}: {both} item(s) run by both, {comparison.unchanged} with the same outcome; "
        f"{len(comparison.only_baseline)} only in the baseline, {len(comparison.only_run)} only in the run."
    )
    if comparison.changes:
        lines += ["", "## Outcome changes", ""]
        lines.append("Explain each one by a harness commit between the runs (the SUT is the same).")
        lines += ["", "| Item | Baseline | Run | Reason (run) |", "|---|---|---|---|"]
        for change in comparison.changes:
            reason = md_cell(change.reason) if change.reason else ""
            lines.append(f"| {md_code(change.nodeid)} | {change.baseline} | {change.run} | {reason} |")
    for title, nodeids in (
        ("Only in the baseline (removed or deselected)", comparison.only_baseline),
        ("Only in the run (new or newly selected)", comparison.only_run),
    ):
        if nodeids:
            lines += ["", f"## {title}", "", *(f"- {md_code(nodeid)}" for nodeid in nodeids)]
    return "\n".join(lines) + "\n"


def _reason(record: TestRecord) -> str | None:
    """The run's skip/xfail reason or failure of an item, shortened."""
    text = record.failure or record.reason
    if not text:
        return None
    text = " ".join(text.split())
    return text if len(text) <= REASON_LIMIT else text[: REASON_LIMIT - 1] + "…"


def _sut(entry: Any) -> str:
    """A SUT entry in one line (``-`` when absent)."""
    return sut_text(entry) or "-"


def _side(data: RunData) -> dict[str, Any]:
    """The facts of one run for the JSON form."""
    return {
        "run_id": data.run_id,
        "directory": str(data.directory),
        "harness_version": data.run.get("harness_version"),
        "harness": data.run.get("harness"),
        "sut": sut_identity(data.run.get("sut")),
        "base": sut_identity(data.run.get("base")),
        "target": data.target,
    }
