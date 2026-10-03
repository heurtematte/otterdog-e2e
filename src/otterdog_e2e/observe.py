"""Observations of SUT behaviour recorded for the differential comparison (SPEC 14, F6).

Files: ``observations/{base,head}.jsonl`` (one JSON object per Observation, UTF-8). OtterdogCli passes CLI outputs RAW
with meta {"exit_code": N}; only the recorder normalizes: text becomes ``"exit_code: N\\n" + normalize_text(text, ctx)``
(so exit-code regressions show even when stdout is identical), mappings/lists become sorted, indented JSON without
volatile keys (oracle.normalize). Content and meta are redacted before they are written.

Observations are attached to the scenario/step of the innermost ``scope()``; recording outside a scope is a programming
error. A key recorded twice in the same scenario/step/kind gets a ``#<n>`` suffix (``plan``, ``plan#2``, ...) instead of
silently overwriting the first observation.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import re
import threading
from collections.abc import Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e.github.oracle import normalize
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.otterdog.output import NormalizeContext

OBSERVATIONS_DIR = "observations"
EXIT_CODE_META = "exit_code"
SEQ_META = "seq"
DUPLICATE_SEPARATOR = "#"
_DUPLICATE_RE = re.compile(r"^(?P<key>.+)#(?P<n>[2-9]|[1-9]\d+)$")
_REQUIRED_FIELDS = ("sut", "role", "scenario", "step", "kind", "key", "content")

log = logging.getLogger(__name__)

ObservationKey = tuple[str, str, str, str]  # (scenario, step, kind, key)


@dataclass(frozen=True)
class Observation:
    """One recorded fact: which SUT/role, scenario/step, kind (e.g. "cli", "oracle") and key, normalized content."""

    sut: str
    role: str
    scenario: str
    step: str
    kind: str
    key: str
    content: str
    meta: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def identity(self) -> tuple[str, str, str, str]:
        """Comparison key across SUTs: (scenario, step, kind, key)."""
        return (self.scenario, self.step, self.kind, self.key)

    def to_json(self) -> dict[str, Any]:
        """JSON object of one observations.jsonl line."""
        return dataclasses.asdict(self)


def base_key(key: str) -> str:
    """Key without the ``#<n>`` duplicate suffix added by the recorder."""
    match = _DUPLICATE_RE.match(key)
    return match.group("key") if match else key


def duplicate_key(key: str, occurrence: int) -> str:
    """Key of the n-th observation of the same identity (1 -> key, 2 -> key#2, ...)."""
    return key if occurrence <= 1 else f"{key}{DUPLICATE_SEPARATOR}{occurrence}"


def _jsonable(value: Any) -> Any:
    """Deterministic JSON-friendly form: dataclasses -> dicts, tuples -> lists, sets -> sorted lists."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _jsonable(dataclasses.asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, set | frozenset):
        return sorted((_jsonable(item) for item in value), key=repr)
    if isinstance(value, list | tuple):
        return [_jsonable(item) for item in value]
    return value


def render_content(content: Any, meta: Mapping[str, Any], ctx: NormalizeContext | None) -> str:
    """Normalized text of an observation (see the module docstring)."""
    if isinstance(content, bytes | bytearray):
        content = bytes(content).decode("utf-8", errors="replace")
    if isinstance(content, str):
        text = normalize_text(content, ctx)
        if EXIT_CODE_META in meta:
            return f"{EXIT_CODE_META}: {meta[EXIT_CODE_META]}\n{text}"
        return text
    return json.dumps(normalize(_jsonable(content)), sort_keys=True, indent=1, default=str, ensure_ascii=False)


def _redact_value(value: Any) -> Any:
    """Redact every string of a JSON-like value."""
    if isinstance(value, str):
        return REDACTOR(value)
    if isinstance(value, dict):
        return {key: _redact_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    return value


class ObservationRecorder:
    """Appends normalized observations of one SUT side to a JSONL file."""

    def __init__(
        self, sut_label: str, role: str, out_file: Path, normalize_ctx: NormalizeContext | None = None
    ) -> None:
        """Bind the recorder to a SUT label, its role (base/head) and the output file."""
        self.sut_label = sut_label
        self.role = role
        self.out_file = out_file
        self.normalize_ctx = normalize_ctx
        self._lock = threading.RLock()
        self._scopes: list[tuple[str, str]] = []
        self._occurrences: dict[ObservationKey, int] = {}
        self._seq = 0
        self._seed_from_file()

    def _seed_from_file(self) -> None:
        """Continue duplicate numbering and sequence of an existing file written for the same SUT and role."""
        for observation in iter_observations(self.out_file):
            if (observation.sut, observation.role) != (self.sut_label, self.role):
                continue
            identity = (observation.scenario, observation.step, observation.kind, base_key(observation.key))
            self._occurrences[identity] = self._occurrences.get(identity, 0) + 1
            self._seq += 1

    @property
    def current_scope(self) -> tuple[str, str] | None:
        """(scenario, step) of the innermost active scope, None outside any scope."""
        with self._lock:
            return self._scopes[-1] if self._scopes else None

    def scope(self, scenario: str, step: str | None = None) -> AbstractContextManager[None]:
        """Context manager setting the scenario/step attached to observations recorded inside it."""
        if not scenario:
            raise ValueError("an observation scope needs a scenario id")
        return self._scoped(scenario, step or "")

    @contextmanager
    def _scoped(self, scenario: str, step: str) -> Iterator[None]:
        """Push (scenario, step) for the duration of the with block."""
        with self._lock:
            self._scopes.append((scenario, step))
            depth = len(self._scopes)
        try:
            yield
        finally:
            with self._lock:
                del self._scopes[depth - 1 :]

    def record(self, kind: str, key: str, content: Any, *, meta: Mapping[str, Any] | None = None) -> None:
        """str -> ("exit_code: N\\n" when meta has exit_code) + normalize_text(content, ctx); mapping/list ->
        json.dumps(oracle.normalize(content), sort_keys=True, indent=1)."""
        scope = self.current_scope
        if scope is None:
            raise RuntimeError(f"ObservationRecorder.record({kind!r}, {key!r}) called outside scope()")
        meta_data = _jsonable(dict(meta or {}))
        text = REDACTOR(render_content(content, meta_data, self.normalize_ctx))
        with self._lock:
            identity = (scope[0], scope[1], kind, key)
            occurrence = self._occurrences.get(identity, 0) + 1
            self._occurrences[identity] = occurrence
            self._seq += 1
            meta_data = {**meta_data, SEQ_META: self._seq}
            observation = Observation(
                sut=self.sut_label,
                role=self.role,
                scenario=scope[0],
                step=scope[1],
                kind=kind,
                key=duplicate_key(key, occurrence),
                content=text,
                meta=_redact_value(json.loads(json.dumps(meta_data, default=str))),
            )
            self._append(observation)

    def _append(self, observation: Observation) -> None:
        """Write one JSONL line (parent directories created on demand)."""
        self.out_file.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(observation.to_json(), sort_keys=True, ensure_ascii=False)
        with self.out_file.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _from_json(data: Any) -> Observation | None:
    """Observation of a decoded JSONL line (None when a required field is missing or not a string)."""
    if not isinstance(data, dict) or any(not isinstance(data.get(name), str) for name in _REQUIRED_FIELDS):
        return None
    meta = data.get("meta")
    return Observation(
        sut=data["sut"],
        role=data["role"],
        scenario=data["scenario"],
        step=data["step"],
        kind=data["kind"],
        key=data["key"],
        content=data["content"],
        meta=meta if isinstance(meta, dict) else {},
    )


def load_observations(path: Path) -> list[Observation]:
    """Read a JSONL observation file (missing file -> [])."""
    return list(iter_observations(path))


def iter_observations(path: Path) -> Iterator[Observation]:
    """Lazily iterate a JSONL observation file (blank lines skipped, malformed lines logged and skipped)."""
    if not path.is_file():
        return
    with path.open(encoding="utf-8", errors="replace") as handle:
        for number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                observation = _from_json(json.loads(line))
            except json.JSONDecodeError:
                observation = None
            if observation is None:
                log.warning("%s:%d: skipping malformed observation line", path, number)
                continue
            yield observation
