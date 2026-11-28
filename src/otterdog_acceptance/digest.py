"""The results digest of one CI session: the GitHub Actions notice the nightly dashboard reads (docs/nightly.md).

The e2e job prints it as a workflow command (``::notice title=otterdog-acceptance results::<message>``), so GitHub keeps
it as an annotation of the job's check run, which anyone may read through the public API of a public repository: the
dashboard's live view fetches it from the browser, docs_nightly.py when it builds the history of the site. It holds
what a public page may show and nothing else: outcome counts, the SUT, the shard, durations, and the node ids of the
failed, errored and xpassed items with their known bugs. Never a failure text, a command output or a GitHub text:
those come from the SUT or from GitHub and stay in the scrubbed artifacts.

The message, line by line (docs_nightly.parse_notice and docs/assets/nightly.js read it back):

* ``766 passed, 0 failed, 0 errors, 61 skipped, 42 xfailed, 0 xpassed``: always the six counts, in this order;
* ``key: value`` lines: ``sut`` (label and short sha), ``instance``, ``shard``, ``lane``, ``session`` (the outcome of
  the session step), ``seconds`` (the session's wall time), ``failed``, ``error`` and ``xpassed`` (one item per line:
  ``<node id> · KB-n · infra``), ``known bugs`` (the ids of the xfailed items, space separated) and ``more`` (the
  problem lines left out beyond MAX_PROBLEMS).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from otterdog_acceptance.report import KNOWN_BUG_RE, RunData, TestRecord, parse_time

NOTICE_TITLE = "otterdog-acceptance results"
COUNTED = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
COUNT_LABELS = {"error": "errors"}
PROBLEM_OUTCOMES = ("failed", "error", "xpassed")
MAX_PROBLEMS = 30
MAX_TEXT = 300
SEPARATOR = " · "
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+-]{0,99}$")


def clean(text: Any, limit: int = MAX_TEXT) -> str:
    """One line of at most ``limit`` characters: control characters become spaces, the separator a slash."""
    value = _CONTROL_RE.sub(" ", str(text)).replace(SEPARATOR.strip(), "/").strip()
    return value if len(value) <= limit else value[: limit - 1] + "…"


def label(value: Any) -> str | None:
    """A short identifier (instance, shard, SUT spec, outcome) or None when it is not one."""
    text = str(value or "").strip()
    return text if _LABEL_RE.match(text) else None


@dataclass
class Problem:
    """A failed, errored or xpassed item."""

    outcome: str
    nodeid: str
    known_bugs: list[str] = field(default_factory=list)
    infra: bool = False

    def line(self) -> str:
        """``<outcome>: <node id> · KB-n · infra``."""
        parts = [clean(self.nodeid), *self.known_bugs, *(["infra"] if self.infra else [])]
        return f"{self.outcome}: {SEPARATOR.join(parts)}"


@dataclass
class Digest:
    """The digest of the run directories of one session."""

    counts: dict[str, int]
    problems: list[Problem]
    known_bugs: list[str]
    meta: dict[str, str]
    seconds: int | None = None

    def message(self) -> str:
        """The notice's message (module docstring)."""
        lines = [", ".join(f"{self.counts.get(name, 0)} {COUNT_LABELS.get(name, name)}" for name in COUNTED)]
        lines += [f"{key}: {value}" for key, value in self.meta.items() if value]
        if self.seconds is not None:
            lines.append(f"seconds: {self.seconds}")
        lines += [problem.line() for problem in self.problems[:MAX_PROBLEMS]]
        if self.known_bugs:
            lines.append(f"known bugs: {' '.join(self.known_bugs)}")
        if len(self.problems) > MAX_PROBLEMS:
            lines.append(f"more: {len(self.problems) - MAX_PROBLEMS}")
        return "\n".join(lines)

    def notice(self) -> str:
        """The workflow command GitHub turns into an annotation of the job."""
        return f"::notice title={NOTICE_TITLE}::{escape_data(self.message())}"


def escape_data(text: str) -> str:
    """The data of a workflow command: ``%``, CR and LF escaped (a line break can never start another command)."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def known_bugs_of(record: TestRecord) -> list[str]:
    """The KB ids of an item: its known_bug, else those named by its reason."""
    found = KNOWN_BUG_RE.findall(" ".join(text for text in (record.known_bug, record.reason) if text))
    return sorted(set(found), key=lambda kb: int(kb.split("-")[1]))


def _sut_text(run: Mapping[str, Any]) -> str | None:
    """``<label> <short sha>`` of run.json's sut, when it is a resolved SUT."""
    sut = run.get("sut")
    if not isinstance(sut, Mapping):
        return label(sut)
    name = label(sut.get("label") or sut.get("spec"))
    sha = sut.get("sha")
    short = sha[:12] if isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{7,40}", sha) else None
    return " ".join(part for part in (name, short) if part) or None


def build(directories: Sequence[Path], meta: Mapping[str, Any]) -> Digest:
    """The digest of the run directories of one session (``meta``: instance, shard, lane, session, sut, when known;
    a value that is not a short identifier is left out)."""
    runs = [RunData.load(directory) for directory in directories if directory.is_dir()]
    records = [record for data in runs for record in data.records]
    counts = {name: sum(record.outcome == name for record in records) for name in COUNTED}
    problems = [
        Problem(record.outcome, record.nodeid, known_bugs_of(record), record.is_infra if record.is_failure else False)
        for record in records
        if record.outcome in PROBLEM_OUTCOMES
    ]
    problems.sort(key=lambda problem: PROBLEM_OUTCOMES.index(problem.outcome))
    xfailed = sorted(
        {kb for record in records if record.outcome == "xfailed" for kb in known_bugs_of(record)},
        key=lambda kb: int(kb.split("-")[1]),
    )
    fields = {key: label(meta.get(key)) for key in ("instance", "shard", "lane", "session")}
    sut = next((text for data in runs if (text := _sut_text(data.run))), None) or label(meta.get("sut"))
    return Digest(
        counts=counts,
        problems=problems,
        known_bugs=xfailed,
        meta={"sut": sut or "", **{key: value or "" for key, value in fields.items()}},
        seconds=_seconds(data.run for data in runs),
    )


def _seconds(runs: Iterable[Mapping[str, Any]]) -> int | None:
    """Wall time from the first start to the last finish of the runs."""
    starts, ends = [], []
    for run in runs:
        start, end = parse_time(run.get("started_at")), parse_time(run.get("finished_at"))
        if start and end:
            starts.append(start)
            ends.append(end)
    return round((max(ends) - min(starts)).total_seconds()) if starts else None
