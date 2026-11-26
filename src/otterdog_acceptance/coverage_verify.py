"""Live verification of the coverage matrix: the green live runs of a feature's covering items (``verified_on``).

The matrix (scenarios/coverage.yaml) says which tests cover a feature; a covered or partial feature with live covering
items stays *unverified* until a run shows that they work against GitHub (BAT-13). This module turns run directories
(run.json, results.jsonl) into that evidence:

* a run verifies a feature when at least one of its live covering items passed in it and none failed or errored
  (an xfail of a known bug and a skip are neutral); report.exercised_features maps the run's results to the features
  (a scenario id matches its scenario's items, a node id its test and every parametrization of it);
* a run refuses a feature when one of its live covering items failed or errored: the reason is listed, the feature
  keeps the runs already recorded;
* the entry is ``{target, sut, run, date}`` of the run (target instance, SUT label of run.json such as ``v1.8.0`` or
  ``main-fa01483``, run id, day it finished); runs of a SUT with uncommitted changes record nothing.

write_verified edits the YAML as text, so its comments and layout stay: the ``verified_on`` block of a feature is
replaced, one entry per (target, SUT) where the newest run wins, at most VERIFIED_KEEP entries, newest first.
``otterdog-acceptance assist verify-coverage RUN_DIR...`` runs it (a dry run without ``--write``);
docs/coverage-matrix.md must be regenerated afterwards (tests/unit/test_coverage_matrix.py --write).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from otterdog_acceptance.report import CoverageMatrix, RunData, exercised_features, lookup

VERIFIED_KEEP = 4  # entries kept per feature, newest first
GREEN = frozenset({"passed"})
NEUTRAL = frozenset({"xfailed", "skipped"})
_ID_LINE = re.compile(r"^  - id: (?P<id>\S+)\s*$")
_BLOCK_END = re.compile(r"^(?:  - |  #|\S)")  # the next feature, a section comment or a top-level key
_VERIFIED_LINE = re.compile(r"^    verified_on:")
_ENTRY_LINE = re.compile(r"^      - ")


class VerifyError(ValueError):
    """A run directory that cannot verify anything (no run.json, no live result) or a matrix that cannot be edited."""


@dataclass(frozen=True)
class RunStamp:
    """The ``verified_on`` entry of a run."""

    target: str
    sut: str
    run: str
    date: str

    def entry(self) -> dict[str, str]:
        """As written in scenarios/coverage.yaml."""
        return {"target": self.target, "sut": self.sut, "run": self.run, "date": self.date}


@dataclass
class RunVerification:
    """What one run says about the features of the matrix."""

    directory: Path
    stamp: RunStamp | None
    skipped: str | None = None  # why the run records nothing
    verified: dict[str, list[str]] = field(default_factory=dict)  # feature id -> its passed live items
    refused: dict[str, list[str]] = field(default_factory=dict)  # feature id -> its failed or errored live items


def run_stamp(data: RunData) -> tuple[RunStamp | None, str | None]:
    """(the entry of the run, None), or (None, why the run cannot verify anything)."""
    target = data.target
    label = lookup(data.run, "sut.label")
    finished = str(lookup(data.run, "finished_at", "started_at") or "")
    if not data.run:
        return None, "no run.json"
    if lookup(data.run, "sut.is_dirty") is True:
        return None, f"the SUT {label} has uncommitted changes"
    if not target or not label or not re.match(r"^20\d{2}-\d{2}-\d{2}", finished):
        return None, "run.json lacks the target, the SUT label or the date"
    return RunStamp(str(target), str(label).replace(" ", "-"), data.run_id, finished[:10]), None


def verify_run(matrix: CoverageMatrix, data: RunData) -> RunVerification:
    """The features this run verifies or refuses (module docstring)."""
    if not data.records:
        return RunVerification(data.directory, None, "no test result (results.jsonl)")
    stamp, skipped = run_stamp(data)
    result = RunVerification(data.directory, stamp, skipped)
    if stamp is None:
        return result
    live = [record for record in data.records if record.is_live]
    if not any(record.ran for record in live):
        result.skipped = "no live item ran"
        return result
    for feature, records in exercised_features(matrix, live):
        if feature.status not in ("covered", "partial"):
            continue
        failed = [record.nodeid for record in records if record.outcome not in GREEN | NEUTRAL]
        passed = [record.nodeid for record in records if record.outcome in GREEN]
        if failed:
            result.refused[feature.id] = failed
        elif passed:
            result.verified[feature.id] = passed
    return result


def merge_entries(existing: Iterable[Mapping[str, Any]], new: Iterable[Mapping[str, str]]) -> list[dict[str, str]]:
    """``existing`` and ``new`` entries: one per (target, sut), the newest run wins, newest first, VERIFIED_KEEP at
    most (entries with an unexpected shape are dropped)."""
    keyed: dict[tuple[str, str], dict[str, str]] = {}
    for entry in [*existing, *new]:
        if not isinstance(entry, Mapping) or not all(isinstance(entry.get(k), str) for k in RunStamp.__annotations__):
            continue
        item = {key: str(entry[key]) for key in RunStamp.__annotations__}
        key = (item["target"], item["sut"])
        if key not in keyed or (item["date"], item["run"]) >= (keyed[key]["date"], keyed[key]["run"]):
            keyed[key] = item
    ordered = sorted(keyed.values(), key=lambda item: (item["date"], item["run"]), reverse=True)
    return ordered[:VERIFIED_KEEP]


def verified_updates(
    current: Mapping[str, Sequence[Mapping[str, Any]]], results: Iterable[RunVerification]
) -> dict[str, list[dict[str, str]]]:
    """Feature id -> its new ``verified_on`` list, for the features whose list changes."""
    added: dict[str, list[dict[str, str]]] = {}
    for result in results:
        if result.stamp is None:
            continue
        for feature_id in result.verified:
            added.setdefault(feature_id, []).append(result.stamp.entry())
    updates = {}
    for feature_id, entries in added.items():
        merged = merge_entries(current.get(feature_id) or [], entries)
        if merged != [dict(entry) for entry in current.get(feature_id) or []]:
            updates[feature_id] = merged
    return updates


def entry_line(entry: Mapping[str, str]) -> str:
    """One ``verified_on`` item as a flow mapping, every value quoted (a bare date would load as a date)."""
    values = ", ".join(f"{key}: {json.dumps(entry[key])}" for key in RunStamp.__annotations__)
    return f"      - {{{values}}}"


def write_verified(text: str, updates: Mapping[str, Sequence[Mapping[str, str]]]) -> str:
    """``text`` (scenarios/coverage.yaml) with the ``verified_on`` block of every feature of ``updates`` replaced,
    as the last key of the feature (VerifyError for a feature id it lacks)."""
    lines = text.split("\n")
    starts = {match["id"]: index for index, line in enumerate(lines) if (match := _ID_LINE.match(line))}
    missing = sorted(set(updates) - set(starts))
    if missing:
        raise VerifyError(f"features missing from the matrix: {', '.join(missing)}")
    for feature_id in sorted(updates, key=lambda fid: starts[fid], reverse=True):
        start = starts[feature_id]
        end = next((i for i in range(start + 1, len(lines)) if _BLOCK_END.match(lines[i])), len(lines))
        while end > start + 1 and not lines[end - 1].strip():
            end -= 1
        block = lines[start:end]
        kept: list[str] = []
        skipping = False
        for line in block:
            if _VERIFIED_LINE.match(line):
                skipping = True
                continue
            if skipping and _ENTRY_LINE.match(line):
                continue
            skipping = False
            kept.append(line)
        entries = updates[feature_id]
        if entries:
            kept += ["    verified_on:", *(entry_line(entry) for entry in entries)]
        lines[start:end] = kept
    return "\n".join(lines)


def current_verified(data: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    """Feature id -> its recorded ``verified_on`` list (the loaded matrix)."""
    return {
        str(entry["id"]): list(entry.get("verified_on") or [])
        for entry in data.get("features") or []
        if isinstance(entry, Mapping) and entry.get("id")
    }


def summary(results: Sequence[RunVerification], updates: Mapping[str, Sequence[Mapping[str, str]]]) -> list[str]:
    """Human-readable lines: per run its stamp and counts, the refused features with their failing items, the
    features whose ``verified_on`` changes."""
    out: list[str] = []
    for result in results:
        if result.stamp is None or result.skipped:
            out.append(f"{result.directory}: nothing to record ({result.skipped})")
            continue
        stamp = result.stamp
        out.append(
            f"{result.directory}: run {stamp.run} on {stamp.target} with {stamp.sut} ({stamp.date}): "
            f"{len(result.verified)} feature(s) verified, {len(result.refused)} refused"
        )
        for feature_id, failed in sorted(result.refused.items()):
            out.append(f"  refused {feature_id}: {', '.join(failed[:3])}{' ...' if len(failed) > 3 else ''}")
    out.append(f"{len(updates)} feature(s) get a new verified_on list")
    return out
