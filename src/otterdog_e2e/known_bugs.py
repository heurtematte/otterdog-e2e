"""Known otterdog defects (scenarios/known_bugs.yaml) turned into non-strict xfail marks (SPEC 12.5).

The file is a YAML list of ``{id: KB-001, title, status: suspected|confirmed|fixed, evidence: [path:line], upstream:
url|null, fixed_in: null, scenarios: [ids]}``. A scenario is linked to a bug through its ``known_bug: KB-001`` field or
through the bug's ``scenarios`` list; collection adds ``pytest.mark.xfail(reason="<id>: <title>", strict=False)`` so a
fix shows up as XPASS instead of hiding the test. Once an entry has ``status: fixed`` its tests run without xfail (they
guard against regressions), except on SUTs whose version predates a PEP 440 ``fixed_in`` (KnownBug.affects).

A STEP may declare ``known_bug`` too (scenarios.engine.step_bug): only that step's failures are expected, so such a bug
must not list the scenario (check_references reports it), or the whole item would xfail at collection.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

KNOWN_BUG_STATUSES = ("suspected", "confirmed", "fixed")
KNOWN_BUG_ID_RE = re.compile(r"^KB-[0-9]{3,}$")
KNOWN_BUG_KEYS = ("id", "title", "status", "evidence", "upstream", "fixed_in", "scenarios", "crash_signature")


class KnownBugError(ValueError):
    """Invalid known_bugs.yaml (bad structure, duplicate ids, unknown keys or statuses)."""


class KnownBugReproduced(AssertionError):  # noqa: N818 - names the outcome, not an error of the harness
    """A known bug showed exactly where it is expected. The plugin's xfail of YAML scenario items accepts only this
    exception (``raises=``): the engines report expected failures with ``pytest.xfail``, so anything else raised by
    such an item (a strict step, a harness error, a failed cleanup) stays a failure instead of an XFAIL (BAT-03)."""


@dataclass
class KnownBug:
    """One entry of known_bugs.yaml."""

    id: str
    title: str
    status: str = "suspected"
    evidence: list[str] = field(default_factory=list)
    upstream: str | None = None
    fixed_in: str | None = None
    scenarios: list[str] = field(default_factory=list)
    # text that only this bug's crash prints (e.g. "object has no attribute 'get_model_header'"): a crash is an
    # expected failure only when its output carries the signature of a bug that covers it; other crashes stay failures
    crash_signature: str | None = None

    def explains_crash(self, output: str) -> bool:
        """True when the bug documents a crash and ``output`` carries its signature."""
        return self.crash_signature is not None and self.crash_signature != "" and self.crash_signature in output

    @property
    def xfail_reason(self) -> str:
        """Reason of the xfail mark: ``<id>: <title>``."""
        return f"{self.id}: {self.title}"

    def xfail_mark(self) -> pytest.MarkDecorator:
        """``pytest.mark.xfail(reason=<id>: <title>, strict=False)`` (an XPASS reveals a fix)."""
        return pytest.mark.xfail(reason=self.xfail_reason, strict=False)

    @property
    def fixed(self) -> bool:
        """True once the bug has status ``fixed``: its tests then guard against regressions instead of xfailing."""
        return self.status == "fixed"

    def affects(self, sut_version: str | None) -> bool:
        """Whether the bug is expected in a SUT: always unless fixed; a fixed bug only in SUT versions older than a
        PEP 440 ``fixed_in`` (never for an unknown SUT version or a non-version ``fixed_in`` such as ``pr-792``)."""
        if not self.fixed:
            return True
        from otterdog_e2e.sut.version import predates

        return predates(sut_version, self.fixed_in) is True


def load(path: Path) -> dict[str, KnownBug]:
    """Load known_bugs.yaml (a list of mappings) keyed by id; ValueError on duplicates, unknown keys or statuses."""
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise KnownBugError(f"{path}: invalid YAML: {exc}") from None
    if data is None:
        return {}
    if not isinstance(data, list):
        raise KnownBugError(f"{path}: expected a list of known bugs, got {type(data).__name__}")
    bugs: dict[str, KnownBug] = {}
    for index, item in enumerate(data):
        bug = _parse_bug(item, f"{path}[{index}]")
        if bug.id in bugs:
            raise KnownBugError(f"{path}: duplicate known bug id {bug.id!r}")
        bugs[bug.id] = bug
    return bugs


def bugs_for_scenario(bugs: Mapping[str, KnownBug], scenario_id: str, *, declared: str | None = None) -> list[KnownBug]:
    """Bugs covering a scenario: its declared ``known_bug`` (must exist, else KeyError) and bugs listing it."""
    found = []
    if declared is not None:
        if declared not in bugs:
            raise KeyError(f"scenario {scenario_id!r} declares unknown known bug {declared!r}")
        found.append(bugs[declared])
    found += [bug for bug in bugs.values() if scenario_id in bug.scenarios and bug.id != declared]
    return found


def check_references(
    bugs: Mapping[str, KnownBug],
    scenarios: Iterable[tuple[str, str | None]],
    steps: Iterable[tuple[str, str, str]] = (),
) -> list[str]:
    """Dangling links between bugs and (scenario id, declared known_bug) pairs, as readable problems.

    ``steps`` are the (scenario id, step name, known_bug) triples of steps declaring a bug of their own: the bug must
    exist, and must not list the scenario unless the scenario declares the same bug (a bug listing a scenario xfails
    the whole item at collection, so the other steps would no longer be strict).
    """
    pairs = list(scenarios)
    ids = {scenario_id for scenario_id, _ in pairs}
    declared_by = dict(pairs)
    problems = [
        f"scenario {scenario_id!r} declares unknown known bug {declared!r}"
        for scenario_id, declared in pairs
        if declared is not None and declared not in bugs
    ]
    for scenario_id, step, bug_id in steps:
        if bug_id not in bugs:
            problems.append(f"scenario {scenario_id!r} step {step!r} declares unknown known bug {bug_id!r}")
        elif scenario_id in bugs[bug_id].scenarios and declared_by.get(scenario_id) != bug_id:
            problems.append(
                f"{bug_id} lists scenario {scenario_id!r}, whose step {step!r} declares it: the whole item would xfail"
                " (keep step-level bugs out of the bug's scenarios list)"
            )
    for bug in bugs.values():
        problems += [f"{bug.id} lists unknown scenario {name!r}" for name in bug.scenarios if name not in ids]
    return problems


def _parse_bug(item: Any, where: str) -> KnownBug:
    """Validate one known bug mapping."""
    if not isinstance(item, Mapping):
        raise KnownBugError(f"{where}: expected a mapping, got {type(item).__name__}")
    unknown = sorted(set(map(str, item)) - set(KNOWN_BUG_KEYS))
    if unknown:
        raise KnownBugError(f"{where}: unknown key(s) {unknown}, allowed: {list(KNOWN_BUG_KEYS)}")
    bug_id = item.get("id")
    if not isinstance(bug_id, str) or not KNOWN_BUG_ID_RE.match(bug_id):
        raise KnownBugError(f"{where}: id {bug_id!r} does not match {KNOWN_BUG_ID_RE.pattern}")
    status = item.get("status", "suspected")
    if status not in KNOWN_BUG_STATUSES:
        raise KnownBugError(f"{where}: status {status!r} is not one of {list(KNOWN_BUG_STATUSES)}")
    return KnownBug(
        id=bug_id,
        title=_text(item.get("title"), f"{where}.title"),
        status=status,
        evidence=_texts(item.get("evidence"), f"{where}.evidence"),
        upstream=_optional_text(item.get("upstream"), f"{where}.upstream"),
        fixed_in=_optional_text(item.get("fixed_in"), f"{where}.fixed_in"),
        scenarios=_texts(item.get("scenarios"), f"{where}.scenarios"),
        crash_signature=_optional_text(item.get("crash_signature"), f"{where}.crash_signature"),
    )


def _text(value: Any, where: str) -> str:
    """A non-empty string."""
    if not isinstance(value, str) or not value.strip():
        raise KnownBugError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def _optional_text(value: Any, where: str) -> str | None:
    """A non-empty string or None."""
    return None if value is None else _text(value, where)


def _texts(value: Any, where: str) -> list[str]:
    """A list of non-empty strings (null -> [])."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise KnownBugError(f"{where}: expected a list of strings, got {type(value).__name__}")
    return [_text(item, f"{where}[{index}]") for index, item in enumerate(value)]
