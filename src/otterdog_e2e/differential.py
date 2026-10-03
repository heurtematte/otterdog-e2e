"""Differential comparison of base vs head observations and otterdog PR manifests (SPEC 14, F6).

Only scenarios recorded on BOTH sides are compared; others are listed as not comparable, never as deltas. Within a
comparable scenario an observation missing on one side is a delta (base or head is None). A PR manifest
(scenarios/otterdog-prs/<N>.yaml) declares the scenarios to run and the deltas the PR is expected to cause; expected
deltas match with fnmatch patterns (None = any), and those that match nothing are reported as "not observed".
"""

from __future__ import annotations

import difflib
import fnmatch
import html
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

import yaml

from otterdog_e2e.observe import base_key, duplicate_key, load_observations
from otterdog_e2e.redact import REDACTOR, Redactor

if TYPE_CHECKING:
    from otterdog_e2e.observe import Observation

TEMPLATE_MODES = ("own", "head", "base")  # which template each side uses (default: each SUT's own)
MARKDOWN_FILE = "differential.md"
JSON_FILE = "differential.json"
MARKDOWN_MAX_BYTES = 900 * 1024  # stays below GitHub's 1 MiB job summary limit
SIDES = ("base", "head")
_FENCE_RE = re.compile(r"`{3,}")


class PrManifestError(ValueError):
    """Invalid PR manifest (unknown keys, wrong types or values)."""


@dataclass
class ExpectedDelta:
    """A delta a PR is expected to cause; fields are fnmatch patterns, None fields match anything."""

    scenario: str
    step: str | None = None
    kind: str | None = None
    key: str | None = None
    note: str = ""

    def matches(self, scenario: str, step: str, kind: str, key: str) -> bool:
        """True when every non-None field matches the delta's coordinate (keys also match without a #n suffix)."""
        if not fnmatch.fnmatchcase(scenario, self.scenario):
            return False
        if self.step is not None and not fnmatch.fnmatchcase(step, self.step):
            return False
        if self.kind is not None and not fnmatch.fnmatchcase(kind, self.kind):
            return False
        return self.key is None or any(fnmatch.fnmatchcase(candidate, self.key) for candidate in {key, base_key(key)})

    def label(self) -> str:
        """``scenario/step/kind/key`` with ``*`` for unset fields."""
        return "/".join(part if part is not None else "*" for part in (self.scenario, self.step, self.kind, self.key))


@dataclass
class PrManifest:
    """scenarios/otterdog-prs/<N>.yaml (``pr: 0`` for a local change without an upstream PR)."""

    pr: int
    title: str = ""
    base: str | None = None
    template: str = "own"
    tags: list[str] = field(default_factory=list)
    scenarios: list[str] = field(default_factory=list)
    scenario_dirs: list[str] = field(default_factory=list)
    expected_deltas: list[ExpectedDelta] = field(default_factory=list)
    markers: dict[str, str] = field(default_factory=dict)
    notes: str = ""


MANIFEST_KEYS = frozenset(PrManifest.__dataclass_fields__)
EXPECTED_DELTA_KEYS = frozenset(ExpectedDelta.__dataclass_fields__)


class _ManifestReader:
    """Typed accessors over the raw mapping of one manifest file (errors name the file and the key)."""

    def __init__(self, path: Path, data: Mapping[str, Any]) -> None:
        """Bind the file path (for messages) and its decoded mapping."""
        self.path = path
        self.data = data

    def error(self, message: str) -> PrManifestError:
        """PrManifestError prefixed with the manifest path."""
        return PrManifestError(f"{self.path}: {message}")

    def pr(self) -> int:
        """Required non-negative integer ``pr`` (a numeric file name must equal it)."""
        value = self.data.get("pr")
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise self.error("'pr' must be a non-negative integer (0 for a local change)")
        if self.path.stem.isdigit() and int(self.path.stem) != value:
            raise self.error(f"'pr: {value}' does not match the file name")
        return value

    def text(self, key: str, default: str = "") -> str:
        """Optional string (None -> default)."""
        value = self.data.get(key)
        if value is None:
            return default
        if not isinstance(value, str):
            raise self.error(f"'{key}' must be a string")
        return value

    def optional_text(self, key: str) -> str | None:
        """Optional non-empty string or None."""
        value = self.text(key)
        return value or None

    def strings(self, key: str) -> list[str]:
        """Optional list of non-empty strings."""
        value = self.data.get(key)
        if value is None:
            return []
        if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
            raise self.error(f"'{key}' must be a list of non-empty strings")
        return list(value)

    def relative_dirs(self, key: str) -> list[str]:
        """List of relative directories (no absolute paths, no '..')."""
        values = self.strings(key)
        for value in values:
            path = PurePosixPath(value)
            if path.is_absolute() or ".." in path.parts:
                raise self.error(f"'{key}' entries must be relative paths without '..': {value!r}")
        return values

    def string_map(self, key: str) -> dict[str, str]:
        """Optional mapping of strings to strings."""
        value = self.data.get(key)
        if value is None:
            return {}
        if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
            raise self.error(f"'{key}' must be a mapping of strings to strings")
        return dict(value)

    def expected_deltas(self) -> list[ExpectedDelta]:
        """``expected_deltas``: mappings {scenario, step?, kind?, key?, note?} or bare scenario patterns."""
        value = self.data.get("expected_deltas")
        if value is None:
            return []
        if not isinstance(value, list):
            raise self.error("'expected_deltas' must be a list")
        return [self.expected_delta(index, item) for index, item in enumerate(value)]

    def expected_delta(self, index: int, item: Any) -> ExpectedDelta:
        """One expected delta entry."""
        where = f"expected_deltas[{index}]"
        if isinstance(item, str) and item:
            return ExpectedDelta(scenario=item)
        if not isinstance(item, dict):
            raise self.error(f"{where} must be a mapping or a scenario pattern")
        unknown = sorted(set(item) - EXPECTED_DELTA_KEYS)
        if unknown:
            raise self.error(f"{where} has unknown keys {unknown}")
        if not isinstance(item.get("scenario"), str) or not item["scenario"]:
            raise self.error(f"{where} needs a non-empty 'scenario' pattern")
        for name in ("step", "kind", "key"):
            if item.get(name) is not None and not isinstance(item[name], str):
                raise self.error(f"{where}.{name} must be a string")
        note = item.get("note") or ""
        if not isinstance(note, str):
            raise self.error(f"{where}.note must be a string")
        return ExpectedDelta(item["scenario"], item.get("step"), item.get("kind"), item.get("key"), note)


def load_pr_manifest(path: Path) -> PrManifest:
    """Load and validate a PR manifest (ValueError on unknown keys or bad values)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PrManifestError(f"{path}: invalid YAML: {exc}") from exc
    reader = _ManifestReader(path, data if isinstance(data, dict) else {})
    if not isinstance(data, dict):
        raise reader.error("a PR manifest must be a mapping")
    unknown = sorted(set(data) - MANIFEST_KEYS)
    if unknown:
        raise reader.error(f"unknown keys {unknown} (allowed: {sorted(MANIFEST_KEYS)})")
    template = reader.text("template", "own")
    if template not in TEMPLATE_MODES:
        raise reader.error(f"'template' must be one of {TEMPLATE_MODES}, not {template!r}")
    return PrManifest(
        pr=reader.pr(),
        title=reader.text("title"),
        base=reader.optional_text("base"),
        template=template,
        tags=reader.strings("tags"),
        scenarios=reader.strings("scenarios"),
        scenario_dirs=reader.relative_dirs("scenario_dirs"),
        expected_deltas=reader.expected_deltas(),
        markers=reader.string_map("markers"),
        notes=reader.text("notes"),
    )


@dataclass
class Delta:
    """One difference between base and head for (scenario, step, kind, key)."""

    scenario: str
    step: str
    kind: str
    key: str
    base: str | None
    head: str | None
    diff: str
    expected: bool
    note: str = ""

    @property
    def label(self) -> str:
        """``scenario / step / kind / key`` (empty step shown as ``-``)."""
        return " / ".join((self.scenario, self.step or "-", self.kind, self.key))

    @property
    def change(self) -> str:
        """Kind of delta: changed, missing on base or missing on head."""
        if self.base is None:
            return "missing on base"
        if self.head is None:
            return "missing on head"
        return "changed"


@dataclass
class DiffReport:
    """Result of compare(): deltas, the number of unchanged observations and non-comparable scenarios.

    Additive fields: ``unmatched_expected`` (expected deltas that matched no delta), ``not_comparable_sides``
    (scenario -> the only side it was recorded on) and ``unchanged_by_scenario`` (scenario -> unchanged count).
    """

    base_label: str
    head_label: str
    deltas: list[Delta] = field(default_factory=list)
    unchanged: int = 0
    not_comparable: list[str] = field(default_factory=list)
    unmatched_expected: list[ExpectedDelta] = field(default_factory=list)
    not_comparable_sides: dict[str, str] = field(default_factory=dict)
    unchanged_by_scenario: dict[str, int] = field(default_factory=dict)

    def unexpected(self) -> list[Delta]:
        """Deltas not covered by an ExpectedDelta."""
        return [delta for delta in self.deltas if not delta.expected]

    def expected(self) -> list[Delta]:
        """Deltas covered by an ExpectedDelta."""
        return [delta for delta in self.deltas if delta.expected]

    def to_markdown(self, *, max_diff_lines: int = 60) -> str:
        """Human report (summary table, unexpected then expected deltas with truncated diffs)."""
        return _MarkdownWriter(self, max_diff_lines).render()

    def to_json(self) -> dict[str, Any]:
        """JSON form (differential.json) with counts of expected/unexpected deltas."""
        data = asdict(self)
        data["counts"] = {"unexpected": len(self.unexpected()), "expected": len(self.expected())}
        return data

    def write(self, directory: Path, *, redactor: Redactor = REDACTOR) -> tuple[Path, Path]:
        """Write differential.md and differential.json (both redacted) into ``directory``."""
        directory.mkdir(parents=True, exist_ok=True)
        markdown, data = directory / MARKDOWN_FILE, directory / JSON_FILE
        markdown.write_text(redactor(self.to_markdown()), encoding="utf-8")
        data.write_text(redactor(json.dumps(self.to_json(), indent=1, ensure_ascii=False)) + "\n", encoding="utf-8")
        return markdown, data


def _index(observations: Iterable[Observation]) -> dict[tuple[str, str, str, str], Observation]:
    """Observations by identity, in input order; repeated identities get the recorder's #n key suffix."""
    index: dict[tuple[str, str, str, str], Observation] = {}
    for observation in observations:
        identity = observation.identity
        occurrence = 1
        while identity in index:
            occurrence += 1
            identity = (*observation.identity[:3], duplicate_key(observation.key, occurrence))
        index[identity] = observation
    return index


def unified_diff(base: str | None, head: str | None, *, base_label: str, head_label: str) -> str:
    """Unified diff of two observation contents (None = not recorded on that side)."""
    lines = difflib.unified_diff(
        (base or "").splitlines(),
        (head or "").splitlines(),
        fromfile=f"base ({base_label})" if base is not None else "base (not recorded)",
        tofile=f"head ({head_label})" if head is not None else "head (not recorded)",
        lineterm="",
    )
    text = "\n".join(lines)
    if not text and base != head:
        return "(contents differ only in line endings or trailing whitespace)"
    return text


def _first_match(expected: Sequence[ExpectedDelta], identity: tuple[str, str, str, str]) -> int | None:
    """Index of the first expected delta matching an identity."""
    return next((index for index, item in enumerate(expected) if item.matches(*identity)), None)


def compare(
    base: Iterable[Observation],
    head: Iterable[Observation],
    *,
    base_label: str,
    head_label: str,
    expected: Sequence[ExpectedDelta] = (),
) -> DiffReport:
    """Compare observations of both sides (only scenarios recorded on both; others -> not_comparable)."""
    base_index, head_index = _index(base), _index(head)
    sides = {"base": {key[0] for key in base_index}, "head": {key[0] for key in head_index}}
    comparable = sides["base"] & sides["head"]
    report = DiffReport(base_label, head_label)
    for role in SIDES:
        for scenario in sides[role] - comparable:
            report.not_comparable_sides[scenario] = role
    report.not_comparable = sorted(report.not_comparable_sides)
    matched: set[int] = set()
    for identity in dict.fromkeys([*base_index, *head_index]):
        if identity[0] not in comparable:
            continue
        old, new = base_index.get(identity), head_index.get(identity)
        old_text, new_text = (old.content if old else None), (new.content if new else None)
        if old_text is not None and old_text == new_text:
            report.unchanged += 1
            report.unchanged_by_scenario[identity[0]] = report.unchanged_by_scenario.get(identity[0], 0) + 1
            continue
        hit = _first_match(expected, identity)
        if hit is not None:
            matched.add(hit)
        diff = unified_diff(old_text, new_text, base_label=base_label, head_label=head_label)
        note = expected[hit].note if hit is not None else ""
        report.deltas.append(Delta(*identity, old_text, new_text, diff, hit is not None, note))
    report.unmatched_expected = [item for index, item in enumerate(expected) if index not in matched]
    return report


def compare_files(
    base_file: Path,
    head_file: Path,
    *,
    base_label: str | None = None,
    head_label: str | None = None,
    expected: Sequence[ExpectedDelta] = (),
) -> DiffReport:
    """compare() of two observation files; labels default to the SUT label recorded in each file."""
    base, head = load_observations(base_file), load_observations(head_file)
    return compare(
        base,
        head,
        base_label=base_label or (base[0].sut if base else "base"),
        head_label=head_label or (head[0].sut if head else "head"),
        expected=expected,
    )


# --- markdown -----------------------------------------------------------------------------------------------------
def md_cell(text: str) -> str:
    """Text safe inside a markdown table cell (pipes escaped, newlines flattened)."""
    return text.replace("|", "\\|").replace("\r", " ").replace("\n", " ")


def md_code(text: str) -> str:
    """Inline code span that survives backticks in ``text``."""
    longest = max((len(run) for run in re.findall(r"`+", text)), default=0)
    ticks = "`" * (longest + 1)
    padding = " " if text.startswith("`") or text.endswith("`") else ""
    return f"{ticks}{padding}{text}{padding}{ticks}"


def md_fence(body: str, language: str = "") -> str:
    """Fenced code block whose fence is longer than any backtick run of ``body``."""
    longest = max((len(run) for run in _FENCE_RE.findall(body)), default=2)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{body}\n{fence}"


def truncate_lines(text: str, max_lines: int, *, hint: str = "") -> str:
    """At most ``max_lines`` lines (<= 0: no limit), with a note about the omitted ones."""
    lines = text.splitlines()
    if max_lines <= 0 or len(lines) <= max_lines:
        return text
    more = len(lines) - max_lines
    return "\n".join([*lines[:max_lines], f"... ({more} more lines{hint})"])


def _verdict(report: DiffReport) -> str:
    """One-line outcome of the comparison."""
    unexpected = len(report.unexpected())
    if unexpected:
        return f"**{unexpected} unexpected delta(s)** between base and head."
    if report.deltas:
        return "Only expected deltas: every difference is declared by the PR manifest."
    return "No differences between base and head on the comparable scenarios."


class _MarkdownWriter:
    """Builds DiffReport.to_markdown() within MARKDOWN_MAX_BYTES (later deltas lose their diff when over budget)."""

    def __init__(self, report: DiffReport, max_diff_lines: int) -> None:
        """Bind the report and the per-delta diff line limit."""
        self.report = report
        self.max_diff_lines = max_diff_lines
        self.size = 0

    def render(self) -> str:
        """Every section, joined."""
        report = self.report
        parts = [
            f"# Differential report: {md_code(report.base_label)} (base) vs {md_code(report.head_label)} (head)",
            _verdict(report),
            self.counts_table(),
        ]
        if report.deltas or report.unchanged:
            parts.append(self.scenario_table())
        self.size = sum(len(part.encode()) for part in parts)
        parts.append(self.delta_section("Unexpected deltas", report.unexpected()))
        parts.append(self.delta_section("Expected deltas", report.expected()))
        parts.extend(self.unmatched_section())
        parts.extend(self.not_comparable_section())
        return "\n\n".join(part for part in parts if part) + "\n"

    def counts_table(self) -> str:
        """Summary counts."""
        report = self.report
        rows = [
            ("Unexpected deltas", len(report.unexpected())),
            ("Expected deltas", len(report.expected())),
            ("Unchanged observations", report.unchanged),
            ("Not comparable scenarios", len(report.not_comparable)),
            ("Expected deltas not observed", len(report.unmatched_expected)),
        ]
        return "\n".join(["| | Count |", "|---|---:|", *(f"| {name} | {count} |" for name, count in rows)])

    def scenario_table(self) -> str:
        """Scenario x outcome matrix of the comparable scenarios."""
        report = self.report
        scenarios = dict.fromkeys([*report.unchanged_by_scenario, *(delta.scenario for delta in report.deltas)])
        lines = ["| Scenario | Unchanged | Expected | Unexpected | Result |", "|---|---:|---:|---:|---|"]
        for scenario in scenarios:
            deltas = [delta for delta in report.deltas if delta.scenario == scenario]
            unexpected = sum(not delta.expected for delta in deltas)
            expected = len(deltas) - unexpected
            result = "**unexpected change**" if unexpected else "expected change" if expected else "unchanged"
            unchanged = report.unchanged_by_scenario.get(scenario, 0)
            lines.append(f"| {md_cell(md_code(scenario))} | {unchanged} | {expected} | {unexpected} | {result} |")
        return "\n".join(lines)

    def delta_section(self, title: str, deltas: list[Delta]) -> str:
        """Collapsible <details> block per delta (diff omitted once the size budget is spent)."""
        if not deltas:
            return ""
        blocks = [f"## {title} ({len(deltas)})"]
        for index, delta in enumerate(deltas):
            block = self.delta_block(delta)
            if self.size + len(block.encode()) > MARKDOWN_MAX_BYTES:
                blocks.append(self.overflow_list(deltas[index:]))
                break
            self.size += len(block.encode())
            blocks.append(block)
        return "\n\n".join(blocks)

    def delta_block(self, delta: Delta) -> str:
        """<details> with the delta coordinates as summary and the truncated diff."""
        step, kind = html.escape(delta.step or "-"), html.escape(delta.kind)
        summary = (
            f"<code>{html.escape(delta.scenario)}</code> / {step} / {kind} / <code>{html.escape(delta.key)}</code>"
        )
        summary += f" ({delta.change})"
        diff = truncate_lines(delta.diff, self.max_diff_lines, hint="; full contents in differential.json")
        note = f"\n\nNote: {delta.note}" if delta.note else ""
        return f"<details><summary>{summary}</summary>{note}\n\n{md_fence(diff, 'diff')}\n\n</details>"

    def overflow_list(self, deltas: list[Delta]) -> str:
        """Remaining deltas as one-line items (size budget reached)."""
        lines = [f"Size budget reached: {len(deltas)} more delta(s) listed without diff (see {JSON_FILE})."]
        for index, delta in enumerate(deltas):
            line = f"- {md_code(delta.label)} ({delta.change})"
            if self.size + len(line.encode()) > MARKDOWN_MAX_BYTES:
                lines.append(f"- ... and {len(deltas) - index} more")
                break
            self.size += len(line.encode()) + 1
            lines.append(line)
        return "\n".join(lines)

    def unmatched_section(self) -> list[str]:
        """Expected deltas (PR manifest) that matched no delta."""
        items = self.report.unmatched_expected
        if not items:
            return []
        lines = [f"- {md_code(item.label())}" + (f" — {item.note}" if item.note else "") for item in items]
        header = (
            f"## Expected deltas not observed ({len(items)})\n\n"
            "The PR manifest declares these deltas but base and head behaved identically (or the scenario was not "
            "comparable): the change may not have the intended effect."
        )
        return [header + "\n\n" + "\n".join(lines)]

    def not_comparable_section(self) -> list[str]:
        """Scenarios recorded on one side only (never deltas)."""
        sides = self.report.not_comparable_sides
        names = self.report.not_comparable
        if not names:
            return []
        lines = [
            f"- {md_code(name)}" + (f" — recorded on {sides[name]} only" if name in sides else "") for name in names
        ]
        return [f"## Not comparable ({len(names)})\n\n" + "\n".join(lines)]
