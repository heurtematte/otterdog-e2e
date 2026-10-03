"""Parsing and normalization of otterdog CLI output (SPEC 11.3).

Output is produced with COLUMNS=4096 NO_COLOR=1 TERM=dumb (procs.SET_ENV), so nothing wraps. Grammar (verified with
otterdog 1.7.0.dev19 offline, samples in tests/unit/data, OC-10):

* object headers: ``  ~ repository[name="x"] {`` / ``  + add repo_secret[name="S", repository=r] {`` /
  ``  - remove ...`` / ``  ! ...`` (forced); the block ends with ``<same indent><symbol> }``. Nested objects have
  their own blocks (``repository=<repo>`` parent; ``environment=<env>`` for env secrets/variables); removing a whole
  repository prints ONE block (its nested objects are neither printed nor counted).
* plain lines after a block: ``Note: setting '<k>' is read-only, will be skipped.`` and
  ``Warning: removing secret for webhook with url '<u>'``;
* ``Plan: A to add, C to change, D to delete.`` counts changed keys (not objects) and is printed only without
  validation errors (``Planning aborted due to validation errors.`` instead);
* messages are rich tables: ``╷`` / ``│ Error:   <msg>`` / ``│          <continuation>`` / ``╵`` (Warning, Info alike),
  never indented; logger lines (RichHandler) are ``WARNING  <msg><padding> <file>.py:<line>`` (OC-08);
* apply: ``Executed plan: A added, C changed, D deleted.`` (or ``D live resources ignored.``), ``No changes required.``,
  ``N resource(s) would be deleted with flag '--delete-resources'.``, error boxes ``failed to apply patch: <OP> -
  <header>``, and a progress bar ``   ━━━━━   11% -:--:--``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from otterdog_e2e.naming import extract_run_id

HEADER_RE = re.compile(
    r"^\s*(?:(\+) add|(-) remove|(~)|(!)) (?P<kind>[a-z_]+)"
    r'(?:\[(?P<key>[a-z_]+)="(?P<val>[^"]*)"(?:, (?P<pkind>[a-z_]+)=(?P<pval>[^\]]+))?\]'
    r"|\[(?P<pk2>[a-z_]+)=(?P<pv2>[^\]]+)\])? \{$"
)
# the same header when the object's dict is empty (``print_dict`` prints ``{}`` on the header line)
EMPTY_HEADER_RE = re.compile(HEADER_RE.pattern.removesuffix(r" \{$") + r" \{\}$")
LOGGER_LINE_RE = re.compile(r"^(TRACE|DEBUG|INFO|WARNING|ERROR|CRITICAL)\s+")
LOGGER_SOURCE_SUFFIX_RE = re.compile(r"\s{2,}[\w.\-]+\.py:\d+\s*$")
PROGRESS_RE = re.compile(r"[━╸╺]+\s+\d+%\s+(?:\d+:\d\d:\d\d|-:--:--)")
READ_ONLY_NOTE_RE = re.compile(r"Note: setting '(?P<key>[^']+)' is read-only, will be skipped\.")
UNKNOWN_PROPERTIES_RE = re.compile(r"ignoring unknown properties found while validating")
PLAN_OPS = ("add", "remove", "change", "forced")
_KEY_LINE_RE = re.compile(r"^(?P<indent>\s*)[~+\-!] (?P<key>[A-Za-z_][\w\-]*)\s*=")

ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-Z\\-_]")
BOX_TOP_RE = re.compile(r"^\s*╷\s*$")
BOX_LINE_RE = re.compile(r"^\s*│(?P<content>.*)$")
BOX_BOTTOM_RE = re.compile(r"^\s*╵\s*$")
BOX_LEVEL_RE = re.compile(r"^(?P<level>[A-Z][a-z]+):\s+(?P<text>.*)$")
PLAIN_MESSAGE_RE = re.compile(r"^\s*(?P<level>Note|Warning|Error|Info): (?P<text>.+?)\s*$")
LOGGER_LEVELS = {"WARNING": "Warning", "ERROR": "Error", "CRITICAL": "Error"}
PLAN_SUMMARY_RE = re.compile(
    r"^\s*Plan: (?P<add>\d+) to add, (?P<change>\d+) to change, (?P<delete>\d+) to delete\.\s*$"
)
PLAN_ABORTED_TEXT = "Planning aborted due to validation errors."
CURRENT_CONFIG_ERROR = "failed to load current configuration"
INFOS_HINT_RE = re.compile(r"there have been (?P<infos>\d+) validation infos, enable verbose output to display them\.")
INFOS_HIDDEN_TEXT = "in order to print validation infos, enable printing info messages by adding '-v' flag."
VALIDATION_OK_RE = re.compile(r"^\s*Validation succeeded\s*$")
VALIDATION_SUMMARY_RE = re.compile(
    r"^\s*Validation (?P<result>succeeded|failed)'?: (?P<infos>\d+) info\(s\), (?P<warnings>\d+) warning\(s\), "
    r"(?P<errors>\d+) error\(s\)\s*$"
)
# the configuration could not be loaded: jsonnet errors, missing file, JSON-schema errors (OC-10)
LOAD_ERROR_RE = re.compile(
    r"failed to load configuration|configuration file '[^']*' does not (?:yet )?exist|Failed validating '"
)
EXECUTED_RE = re.compile(
    r"^\s*Executed plan: (?P<added>\d+) added, (?P<changed>\d+) changed, (?P<deleted>\d+) "
    r"(?P<mode>deleted|live resources ignored)\.\s*$"
)
NO_CHANGES_RE = re.compile(r"^\s*No changes required\.\s*$")
WOULD_DELETE_RE = re.compile(r"^\s*(?P<count>\d+) resource\(s\) would be deleted with flag '--delete-resources'\.\s*$")
FAILED_PATCH_PREFIX = "failed to apply patch: "

SHA_RE = re.compile(r"\b[0-9a-f]{40}\b")
TIMESTAMP_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?")
DURATION_RE = re.compile(r"\b\d+(?:\.\d+)?\s?(?:ms|s|secs?|seconds?)\b")
TMP_PATH_RE = re.compile(r"(?<![\w./-])(?:/private)?(?:/tmp|/var/tmp|/var/folders)/[^\s'\":]*")
# values otterdog prints from Python sets, in an order that changes from run to run (KB-038): "{'a', 'b'}" (set repr)
# and ('"a" | "b"') (code scanning languages); differential observations sort them
SET_REPR_RE = re.compile(r"\{('[^'{}]*'(?:, '[^'{}]*')+)\}")
SET_ALTERNATIVES_RE = re.compile(r'\(("[^"()]*"(?: \| "[^"()]*")+)\)')
_OPS = {"+": "add", "-": "remove", "~": "change", "!": "forced"}


def strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences."""
    return ANSI_RE.sub("", text)


@dataclass
class _Box:
    """One rich message box: line range (inclusive) and its message."""

    start: int
    end: int
    level: str
    lines: list[str]

    @property
    def text(self) -> str:
        """Message text: first line plus continuation lines, left-trimmed."""
        return "\n".join(self.lines).strip()


def _box_message(content: Sequence[str]) -> tuple[str, list[str]]:
    """Level and left-trimmed message lines of the content column of a box."""
    lines = [line.strip() for line in content]
    while lines and not lines[-1]:
        lines.pop()
    while lines and not lines[0]:
        lines.pop(0)
    if not lines:
        return "", []
    match = BOX_LEVEL_RE.match(lines[0])
    if match is None:
        return "", lines
    return match.group("level"), [match.group("text").strip(), *lines[1:]]


def _boxes(lines: Sequence[str]) -> list[_Box]:
    """Every ``╷ │ … ╵`` message box (a box cut by the end of the output counts too)."""
    boxes: list[_Box] = []
    index = 0
    while index < len(lines):
        if not BOX_TOP_RE.match(lines[index]):
            index += 1
            continue
        end = index + 1
        content: list[str] = []
        while end < len(lines) and (match := BOX_LINE_RE.match(lines[end])):
            content.append(match.group("content"))
            end += 1
        closed = end < len(lines) and BOX_BOTTOM_RE.match(lines[end]) is not None
        if content and (closed or end == len(lines)):
            level, message = _box_message(content)
            last = end if closed else end - 1
            boxes.append(_Box(index, last, level, message))
            index = last + 1
        else:
            index += 1
    return boxes


def _box_index(boxes: Iterable[_Box]) -> dict[int, _Box]:
    """Boxes by their first line."""
    return {box.start: box for box in boxes}


def _outside_boxes(lines: Sequence[str], boxes: Sequence[_Box]) -> list[tuple[int, str]]:
    """(index, line) of every line that is not part of a box."""
    inside = {index for box in boxes for index in range(box.start, box.end + 1)}
    return [(index, line) for index, line in enumerate(lines) if index not in inside]


def unbox(text: str) -> str:
    """Replace rich box drawings (╷ │ ╵ …) of error/warning/info boxes by plain, left-trimmed lines.

    ``│ Error:   msg`` becomes ``Error: msg``; continuation lines are left-trimmed; other lines (e.g. the
    list-projects table) are kept as they are.
    """
    lines = text.splitlines()
    boxes = _box_index(_boxes(lines))
    result: list[str] = []
    index = 0
    while index < len(lines):
        box = boxes.get(index)
        if box is None:
            result.append(lines[index])
            index += 1
            continue
        if box.lines:
            first = f"{box.level}: {box.lines[0]}" if box.level else box.lines[0]
            result.extend([first, *box.lines[1:]])
        index = box.end + 1
    return "\n".join(result) + ("\n" if text.endswith("\n") else "")


@dataclass
class Message:
    """A diagnostic printed by otterdog: level (Error/Warning/Info/Note), text and source (box/plain/logger)."""

    level: str
    text: str
    source: str


def _logger_message(line: str) -> tuple[str, str] | None:
    """(otterdog level, message) of a WARNING/ERROR/CRITICAL logger line, None for other lines."""
    match = LOGGER_LINE_RE.match(line)
    if match is None or match.group(1) not in LOGGER_LEVELS:
        return None
    text = LOGGER_SOURCE_SUFFIX_RE.sub("", line[match.end() :]).strip()
    return LOGGER_LEVELS[match.group(1)], text


def _line_message(line: str) -> Message | None:
    """Message of a plain ``Note:``/``Warning:``/``Error:`` line or a logger line, else None."""
    logged = _logger_message(line)
    if logged is not None:
        return Message(logged[0], logged[1], "logger")
    if LOGGER_LINE_RE.match(line):
        return None
    match = PLAIN_MESSAGE_RE.match(line)
    return Message(match.group("level"), match.group("text"), "plain") if match else None


def parse_messages(text: str) -> list[Message]:
    """Boxed Error/Warning/Info messages, plain ``Note:``/``Warning:`` lines and logger lines (WARNING/ERROR)."""
    lines = strip_ansi(text).splitlines()
    boxes = _box_index(_boxes(lines))
    messages: list[Message] = []
    index = 0
    while index < len(lines):
        box = boxes.get(index)
        if box is not None:
            messages.append(Message(box.level, box.text, "box"))
            index = box.end + 1
            continue
        message = _line_message(lines[index])
        if message is not None:
            messages.append(message)
        index += 1
    return messages


@dataclass
class ValidationResult:
    """Parsed ``validate`` output (counts are None when no summary was printed, e.g. on a load error)."""

    ok: bool
    infos: int | None
    warnings: int | None
    errors: int | None
    messages: list[Message]
    load_error: bool
    raw: str

    def errors_text(self) -> list[str]:
        """Texts of the error messages."""
        return [message.text for message in self.messages if message.level == "Error"]


@dataclass
class PlanObject:
    """One object block of a plan: op (PLAN_OPS), kind, header key/value, nested parent, header line and body lines.

    The parser attaches the plain ``Note:`` lines printed right after a block (read-only keys) to ``notes`` (or to
    ``body``); read-only detection looks at both.
    """

    op: str
    kind: str
    key: str
    value: str
    parent_kind: str | None
    parent: str | None
    header: str
    body: list[str]
    notes: list[str] = field(default_factory=list)

    @property
    def changed_keys(self) -> list[str]:
        """Keys at the first nesting level of the body (``~ key = ...``, ``+ key = ...``, ...), in order."""
        matches = [m for m in (_KEY_LINE_RE.match(line) for line in self.body) if m]
        if not matches:
            return []
        indent = min(len(m.group("indent")) for m in matches)
        return [m.group("key") for m in matches if len(m.group("indent")) == indent]

    @property
    def read_only_keys(self) -> list[str]:
        """Keys reported as read-only (``Note: setting '<k>' is read-only, will be skipped.``)."""
        return [m.group("key") for m in (READ_ONLY_NOTE_RE.search(line) for line in [*self.body, *self.notes]) if m]

    @property
    def is_read_only(self) -> bool:
        """True for a change whose every changed key is read-only (otterdog skips it and does not count it)."""
        changed = self.changed_keys
        return self.op in ("change", "forced") and bool(changed) and set(changed) <= set(self.read_only_keys)

    @property
    def run_id(self) -> str | None:
        """Run id carried by the object's value or its parent (naming.extract_run_id)."""
        return extract_run_id(self.value) or (extract_run_id(self.parent) if self.parent else None)


@dataclass
class PlanResult:
    """Parsed ``plan`` / ``local-plan`` output; counts are the raw ``Plan:`` numbers (None when not printed)."""

    add: int | None
    change: int | None
    delete: int | None
    objects: list[PlanObject]
    aborted: bool
    validation: ValidationResult | None
    messages: list[Message]
    raw: str

    def objects_for(self, needles: Sequence[str]) -> list[PlanObject]:
        """Objects whose header contains any of ``needles`` (e.g. RunContext.needles())."""
        return [obj for obj in self.objects if any(needle in obj.header for needle in needles)]

    def is_noop(self, needles: Sequence[str] | None = None) -> bool:
        """True when nothing but read-only changes is planned (for objects matching ``needles`` when given).

        Without needles the ``Plan:`` counts must also be 0; an aborted or summary-less plan is never a no-op.
        """
        if self.aborted or self.add is None:
            return False
        objects = self.objects if needles is None else self.objects_for(needles)
        if any(not obj.is_read_only for obj in objects):
            return False
        return needles is not None or (self.add, self.change, self.delete) == (0, 0, 0)

    def removals(self) -> list[PlanObject]:
        """Objects the plan would remove (op "remove"), nested ones included."""
        return [obj for obj in self.objects if obj.op == "remove"]

    def op_counts(self, needles: Sequence[str] | None = None) -> dict[str, int]:
        """Number of objects per op (PLAN_OPS), read-only changes excluded, optionally restricted to ``needles``."""
        objects = self.objects if needles is None else self.objects_for(needles)
        counts = dict.fromkeys(PLAN_OPS, 0)
        for obj in objects:
            if not obj.is_read_only:
                counts[obj.op] += 1
        return counts


@dataclass
class ApplyResult:
    """Parsed ``apply`` output (``Executed plan: A added, C changed, D deleted|live resources ignored.``)."""

    added: int | None
    changed: int | None
    deleted: int | None
    ignored: int | None
    no_changes: bool
    aborted_validation: bool
    pending_deletions: int | None
    failed_patches: list[str]
    messages: list[Message]
    raw: str


def _level_counts(boxes: Iterable[_Box]) -> dict[str, int]:
    """Number of boxes per level."""
    counts: dict[str, int] = {}
    for box in boxes:
        counts[box.level] = counts.get(box.level, 0) + 1
    return counts


def _is_load_error(messages: Iterable[Message]) -> bool:
    """True when an error message says the (expected) configuration could not be loaded."""
    return any(
        message.level == "Error"
        and LOAD_ERROR_RE.search(message.text)
        and not message.text.startswith(CURRENT_CONFIG_ERROR)
        for message in messages
    )


def parse_validation(text: str) -> ValidationResult:
    """Parse validate output (``Validation succeeded``/``failed``: counts; boxed load errors -> load_error)."""
    lines = strip_ansi(text).splitlines()
    boxes = _boxes(lines)
    plain = [line for _, line in _outside_boxes(lines, boxes)]
    messages = parse_messages(text)
    for line in plain:
        match = VALIDATION_SUMMARY_RE.match(line)
        if match:
            infos, warnings, errors = (int(match.group(name)) for name in ("infos", "warnings", "errors"))
            return ValidationResult(
                match.group("result") == "succeeded", infos, warnings, errors, messages, False, text
            )
    if any(VALIDATION_OK_RE.match(line) for line in plain):
        shown = _level_counts(boxes).get("Info", 0)
        hidden = any(INFOS_HIDDEN_TEXT in line for line in plain)
        return ValidationResult(True, None if hidden and not shown else shown, 0, 0, messages, False, text)
    return ValidationResult(False, None, None, None, messages, _is_load_error(messages), text)


def _plan_object(match: re.Match[str], line: str, body: list[str]) -> PlanObject:
    """PlanObject of a matched header line."""
    symbol = next(group for group in match.groups()[:4] if group)
    keyed = match.group("key") is not None
    return PlanObject(
        op=_OPS[symbol],
        kind=match.group("kind"),
        key=match.group("key") or "",
        value=match.group("val") if keyed else "",
        parent_kind=match.group("pkind") if keyed else match.group("pk2"),
        parent=match.group("pval") if keyed else match.group("pv2"),
        header=line.strip(),
        body=body,
    )


def _read_block(lines: Sequence[str], start: int, match: re.Match[str]) -> tuple[list[str], int]:
    """Body lines of the block starting at ``start`` and the index after its closing ``<symbol> }`` line."""
    line = lines[start]
    symbol = next(group for group in match.groups()[:4] if group)
    closing = line[: len(line) - len(line.lstrip())] + symbol + " }"
    body: list[str] = []
    index = start + 1
    while index < len(lines):
        current = lines[index]
        if current.rstrip() == closing:
            return body, index + 1
        if HEADER_RE.match(current) or EMPTY_HEADER_RE.match(current):
            break
        body.append(current)
        index += 1
    return body, index


@dataclass
class _PlanScan:
    """Raw facts collected from a plan output."""

    objects: list[PlanObject] = field(default_factory=list)
    counts: tuple[int | None, int | None, int | None] = (None, None, None)
    aborted_at: int | None = None
    first_diff_line: int | None = None
    infos_hint: int | None = None


def _scan_plan(lines: Sequence[str], boxes: dict[int, _Box]) -> _PlanScan:
    """Objects, counts, validation abort and the first diff line of a plan output."""
    scan = _PlanScan()
    index = 0
    while index < len(lines):
        if index in boxes:
            index = boxes[index].end + 1
            continue
        line = lines[index]
        match = HEADER_RE.match(line)
        header = match or EMPTY_HEADER_RE.match(line)
        if header is not None:
            scan.first_diff_line = index if scan.first_diff_line is None else scan.first_diff_line
            body, index = _read_block(lines, index, match) if match else ([], index + 1)
            scan.objects.append(_plan_object(header, line, body))
            continue
        _scan_plain_line(scan, index, line)
        index += 1
    return scan


def _scan_plain_line(scan: _PlanScan, index: int, line: str) -> None:
    """Record a summary, abort, infos hint or note line of a plan output."""
    summary = PLAN_SUMMARY_RE.match(line)
    hint = INFOS_HINT_RE.search(line)
    if summary:
        scan.counts = (int(summary.group("add")), int(summary.group("change")), int(summary.group("delete")))
        scan.first_diff_line = index if scan.first_diff_line is None else scan.first_diff_line
    elif line.strip() == PLAN_ABORTED_TEXT:
        scan.aborted_at = index
        scan.first_diff_line = index if scan.first_diff_line is None else scan.first_diff_line
    elif hint:
        scan.infos_hint = int(hint.group("infos"))
    elif scan.objects and (plain := PLAIN_MESSAGE_RE.match(line)) and plain.group("level") in ("Note", "Warning"):
        scan.objects[-1].notes.append(line.strip())


def _plan_validation(
    scan: _PlanScan, boxes: Sequence[_Box], messages: list[Message], raw: str
) -> ValidationResult | None:
    """Validation outcome visible in a plan output (None when the plan stopped before it could tell)."""
    current = next((b for b in boxes if b.level == "Error" and b.text.startswith(CURRENT_CONFIG_ERROR)), None)
    limit = scan.first_diff_line if scan.first_diff_line is not None else (current.start if current else -1)
    counts = _level_counts(box for box in boxes if limit < 0 or box.start < limit)
    infos = scan.infos_hint if scan.infos_hint is not None else counts.get("Info", 0)
    if scan.aborted_at is not None:
        return ValidationResult(False, infos, counts.get("Warning", 0), counts.get("Error", 0), messages, False, raw)
    if scan.counts[0] is not None or current is not None:
        # validation runs before the current configuration is loaded: it passed when that load is what failed
        return ValidationResult(True, infos, counts.get("Warning", 0), 0, messages, False, raw)
    if _is_load_error(messages):
        return ValidationResult(False, None, None, None, messages, True, raw)
    return None


def parse_plan(text: str) -> PlanResult:
    """Parse plan/local-plan output into objects (HEADER_RE), counts, abort flag and messages.

    ``aborted`` is True when validation errors stopped the plan or no ``Plan:`` summary was printed (load, credential
    or GitHub errors); ``validation`` reflects the validation messages printed before the diff (None when unknown).
    """
    lines = strip_ansi(text).splitlines()
    box_list = _boxes(lines)
    scan = _scan_plan(lines, _box_index(box_list))
    messages = parse_messages(text)
    validation = _plan_validation(scan, box_list, messages, text)
    add, change, delete = scan.counts
    aborted = scan.aborted_at is not None or add is None
    return PlanResult(add, change, delete, scan.objects, aborted, validation, messages, text)


def parse_apply(text: str) -> ApplyResult:
    """Parse apply output (summary, no-changes, pending deletions, failed patches, validation abort).

    ``Executed plan: ... D deleted.`` sets deleted=D (ignored 0); ``... D live resources ignored.`` sets ignored=D and
    pending_deletions=D (deleted 0); ``No changes required.`` sets the counts to 0 and pending_deletions to the
    ``N resource(s) would be deleted`` number. Counts stay None when apply stopped early.
    """
    lines = strip_ansi(text).splitlines()
    boxes = _boxes(lines)
    plain = [line for _, line in _outside_boxes(lines, boxes)]
    messages = parse_messages(text)
    failed = [
        message.text.removeprefix(FAILED_PATCH_PREFIX).splitlines()[0]
        for message in messages
        if message.level == "Error" and message.text.startswith(FAILED_PATCH_PREFIX)
    ]
    aborted_validation = any(line.strip() == PLAN_ABORTED_TEXT for line in plain)
    no_changes = any(NO_CHANGES_RE.match(line) for line in plain)
    would_delete = next((int(m.group("count")) for m in map(WOULD_DELETE_RE.match, plain) if m), None)
    executed = next((m for m in map(EXECUTED_RE.match, plain) if m), None)
    added = changed = deleted = ignored = pending = None
    if executed is not None:
        added, changed = int(executed.group("added")), int(executed.group("changed"))
        count = int(executed.group("deleted"))
        deleted, ignored = (count, 0) if executed.group("mode") == "deleted" else (0, count)
        pending = ignored
    elif no_changes:
        added = changed = deleted = 0
        ignored = pending = would_delete or 0
    return ApplyResult(
        added, changed, deleted, ignored, no_changes, aborted_validation, pending, failed, messages, text
    )


@dataclass
class NormalizeContext:
    """Literal replacements applied by normalize_text, as (literal, placeholder) pairs (longest literal first)."""

    literals: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def for_paths(
        cls, *paths: Path | str, placeholder: str = "<TMP>", extra: Iterable[tuple[str, str]] = ()
    ) -> NormalizeContext:
        """Context replacing each path (and its resolved form) by ``placeholder``, plus ``extra`` pairs."""
        literals = list(extra)
        for path in paths:
            for form in {str(path), str(Path(path).resolve())}:
                literals.append((form, placeholder))
        return cls(literals)


def _normalize_logger_line(line: str) -> str:
    """Logger line without its ``file.py:LINE`` suffix and padding: ``WARNING message``."""
    match = LOGGER_LINE_RE.match(line)
    if match is None:
        return line
    message = LOGGER_SOURCE_SUFFIX_RE.sub("", line[match.end() :]).strip()
    return f"{match.group(1)} {message}".rstrip()


def _sort_logger_runs(lines: list[str]) -> list[str]:
    """Sort every run of consecutive logger lines (their order depends on concurrent repo loading, OC-08)."""
    result: list[str] = []
    run: list[str] = []
    for line in lines:
        if LOGGER_LINE_RE.match(line):
            run.append(line)
            continue
        result.extend(sorted(run))
        run = []
        result.append(line)
    result.extend(sorted(run))
    return result


def _collapse_blank_runs(lines: list[str]) -> list[str]:
    """Keep at most one blank line in a row."""
    result: list[str] = []
    for line in lines:
        if not line and result and not result[-1]:
            continue
        result.append(line)
    return result


def sort_set_values(text: str) -> str:
    """Sort the values of the Python sets otterdog prints in validation messages (SET_REPR_RE, SET_ALTERNATIVES_RE),
    whose order depends on the interpreter's hash seed (KB-038)."""
    text = SET_REPR_RE.sub(lambda m: "{" + ", ".join(sorted(m.group(1).split(", "))) + "}", text)
    return SET_ALTERNATIVES_RE.sub(lambda m: "(" + " | ".join(sorted(m.group(1).split(" | "))) + ")", text)


def _apply_context(text: str, ctx: NormalizeContext) -> str:
    """Literal replacements (longest first), then <SHA>, <TS>, <DUR> and <TMP> placeholders, and set values sorted."""
    for literal, placeholder in sorted(ctx.literals, key=lambda pair: -len(pair[0])):
        if literal:
            text = text.replace(literal, placeholder)
    text = SHA_RE.sub("<SHA>", text)
    text = TIMESTAMP_RE.sub("<TS>", text)
    text = DURATION_RE.sub("<DUR>", text)
    return sort_set_values(TMP_PATH_RE.sub("<TMP>", text))


def normalize_text(text: str, ctx: NormalizeContext | None = None) -> str:
    """Deterministic form of CLI output for matching (ctx None) and differential observations (ctx given).

    strip_ansi; unbox; logger lines: strip LOGGER_SOURCE_SUFFIX_RE, collapse padding, sort runs of consecutive logger
    lines; PROGRESS_RE -> <PROGRESS>; rstrip; collapse blank runs. With ctx: literal replacements (longest first),
    40-hex -> <SHA>, ISO timestamps -> <TS>, durations -> <DUR>, scratch/tmp paths -> <TMP>, the values of printed
    Python sets sorted (sort_set_values, KB-038).
    """
    lines = [_normalize_logger_line(line.rstrip()) for line in unbox(strip_ansi(text)).splitlines()]
    lines = [PROGRESS_RE.sub("<PROGRESS>", line).rstrip() for line in lines]
    lines = _collapse_blank_runs(_sort_logger_runs(lines))
    while lines and not lines[-1]:
        lines.pop()
    result = "\n".join(lines) + ("\n" if lines else "")
    return _apply_context(result, ctx) if ctx is not None else result
