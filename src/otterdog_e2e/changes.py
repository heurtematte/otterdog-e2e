"""Changes referenced by scenarios: what a differential run of one change expects (SPEC 14).

Scenarios stay organised by the behaviour they pin, never by pull request. A scenario names the changes that
implemented, fixed or changed that behaviour in its ``references`` (YAML scenarios) or in the ``references`` keyword
of its ``pytest.mark.scenario(<id>, references=[...])`` marker (Python tests). Each reference is a mapping with exactly
one of ``pr: <n>`` (an eclipse-csi/otterdog pull request) or ``change: <slug>`` (a named change without an upstream
pull request, e.g. a maintainer branch) and optionally:

* ``note``: why the scenario references the change (what it changed, the known-bad behaviour, the evidence);
* ``expected_deltas``: the differences between base and head the change is expected to cause in THIS scenario,
  mappings ``{step?, kind?, key?, note?}`` of fnmatch patterns (unset = any) matched like
  differential.ExpectedDelta with the scenario implied; a step pattern must match a step of the scenario (Python
  tests have no steps);
* ``base``: the SUT spec of the differential base of the change (release, tag, branch or sha), the default
  ``--base-sut`` of ``otterdog-e2e run``/``pr`` for this change;
* ``template``: the template both differential sides vendor (own: each SUT its own, head or base: that side's).

A run selects one change (``--change``, pytest ``--e2e-change``, E2E_CHANGE: ``N``, ``#N`` or a slug; default: N of a
head SUT ``pr:N@<sha>``). load_change gathers every scenario referencing it (YAML files of the scenario tier
directories read leniently, Python tests read from their AST, never imported) into a ChangeSpec: the referencing
scenario ids pass the --e2e-tags filter, their expected deltas feed the differential report, their ``base`` and
``template`` set the base and templates of the comparison. Two references of one change with different ``base`` or
``template`` values are an error (ChangeError).
"""

from __future__ import annotations

import ast
import fnmatch
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from otterdog_e2e.differential import ExpectedDelta

PR_RE = re.compile(r"^#?(?P<number>[0-9]+)$")
SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,62}$")  # starts with a letter: never confused with a PR number
REFERENCE_KEYS = ("pr", "change", "note", "expected_deltas", "base", "template")
DELTA_KEYS = ("step", "kind", "key", "note")
TEMPLATE_MODES = ("own", "head", "base")  # which template each differential side vendors (default own)
DEFAULT_TEMPLATE = "own"
BASE_KINDS = ("release", "tag", "branch", "sha")  # a base is a pinned, trusted spec (never a PR or a checkout)
YAML_SCENARIO_DIRS = ("offline", "cli", "enterprise")  # scenarios/<dir>
PYTHON_TEST_DIRS = ("offline", "cli", "webhooks", "webapp", "enterprise", "differential", "web_ui")  # tests/<dir>
SCENARIO_SUFFIXES = (".yaml", ".yml")
REFERENCES_KEY = "references"


class ChangeError(ValueError):
    """Invalid reference, change identifier or conflicting references of one change."""


# --- change identifiers -------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ChangeId:
    """One change: an upstream pull request (``pr``) or a named change without one (``slug``)."""

    pr: int | None = None
    slug: str | None = None

    @classmethod
    def parse(cls, text: str) -> ChangeId:
        """``N`` or ``#N`` (a pull request, N > 0) or a slug (``[a-z][a-z0-9-]*``); ChangeError otherwise."""
        value = str(text).strip()
        match = PR_RE.match(value)
        if match is not None:
            number = int(match["number"])
            if number <= 0:
                raise ChangeError(f"change {text!r}: a pull request number is positive")
            return cls(pr=number)
        if SLUG_RE.match(value):
            return cls(slug=value)
        raise ChangeError(
            f"change {text!r} is neither a pull request number (N or #N) nor a change slug ({SLUG_RE.pattern})"
        )

    def __str__(self) -> str:
        """The command line form: ``790`` or ``check-merge``."""
        return str(self.pr) if self.pr is not None else str(self.slug)

    @property
    def label(self) -> str:
        """``#790`` or ``check-merge``."""
        return f"#{self.pr}" if self.pr is not None else str(self.slug)

    def sort_key(self) -> tuple[int, int, str]:
        """Pull requests first (by number), then slugs."""
        return (0, self.pr, "") if self.pr is not None else (1, 0, str(self.slug))


def default_change(option: str | None, sut: str | None) -> ChangeId | None:
    """The change of a run: ``option`` when given (ChangeError when malformed), else N of a ``pr:N@<sha>`` SUT spec,
    else None."""
    if option is not None and str(option).strip():
        return ChangeId.parse(str(option))
    kind, _, value = str(sut or "").strip().partition(":")
    if kind.strip().lower() != "pr":
        return None
    number = value.split("@", 1)[0].strip().lstrip("#")
    return ChangeId(pr=int(number)) if number.isdigit() and int(number) > 0 else None


# --- references ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DeltaPattern:
    """An expected delta of a reference (the scenario is the referencing one; None fields match anything)."""

    step: str | None = None
    kind: str | None = None
    key: str | None = None
    note: str = ""

    def to_json(self) -> dict[str, Any]:
        """The set fields."""
        data = {"step": self.step, "kind": self.kind, "key": self.key, "note": self.note or None}
        return {name: value for name, value in data.items() if value is not None}


@dataclass(frozen=True)
class Reference:
    """One entry of a scenario's ``references`` (``template`` None: not declared, the default is own)."""

    change: ChangeId
    note: str = ""
    expected_deltas: tuple[DeltaPattern, ...] = ()
    base: str | None = None
    template: str | None = None

    def to_json(self) -> dict[str, Any]:
        """The YAML form of the reference (only the declared keys)."""
        data: dict[str, Any] = {"pr": self.change.pr} if self.change.pr is not None else {"change": self.change.slug}
        if self.note:
            data["note"] = self.note
        if self.expected_deltas:
            data["expected_deltas"] = [delta.to_json() for delta in self.expected_deltas]
        if self.base is not None:
            data["base"] = self.base
        if self.template is not None:
            data["template"] = self.template
        return data


def parse_references(value: Any, where: str = REFERENCES_KEY, *, steps: Sequence[str] | None) -> list[Reference]:
    """``references`` of a scenario (None -> []): a list of mappings (module docstring); ChangeError naming the key
    path otherwise. ``steps``: the step names of a YAML scenario (an expected delta's ``step`` pattern must match one
    of them); None for a Python test, whose references may not name a step."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ChangeError(f"{where}: expected a list of references ({{pr: <n>}} or {{change: <slug>}})")
    references = [_reference(item, f"{where}[{index}]", steps) for index, item in enumerate(value)]
    seen: set[ChangeId] = set()
    for index, reference in enumerate(references):
        if reference.change in seen:
            raise ChangeError(f"{where}[{index}]: {reference.change.label} is referenced twice")
        seen.add(reference.change)
    return references


def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    """A mapping with string keys."""
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ChangeError(f"{where}: expected a mapping, got {type(value).__name__}")
    return value


def _check_keys(data: Mapping[str, Any], allowed: Sequence[str], where: str) -> None:
    """ChangeError for unknown keys."""
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ChangeError(f"{where}: unknown key(s) {unknown}, allowed: {sorted(allowed)}")


def _text(value: Any, where: str, *, allow_empty: bool = False) -> str:
    """A string (non-empty unless ``allow_empty``)."""
    if not isinstance(value, str) or (not value.strip() and not allow_empty):
        raise ChangeError(f"{where}: expected a non-empty string, got {value!r}")
    return value


def _reference(value: Any, where: str, steps: Sequence[str] | None) -> Reference:
    """One reference: exactly one of pr/change, then its optional keys."""
    data = _mapping(value, where)
    _check_keys(data, REFERENCE_KEYS, where)
    if ("pr" in data) == ("change" in data):
        raise ChangeError(f"{where}: give exactly one of 'pr' (an otterdog pull request) or 'change' (a slug)")
    if "pr" in data:
        number = data["pr"]
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            raise ChangeError(f"{where}.pr: expected a positive pull request number, got {number!r}")
        change = ChangeId(pr=number)
    else:
        slug = data["change"]
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            raise ChangeError(f"{where}.change: {slug!r} is not a change slug ({SLUG_RE.pattern})")
        change = ChangeId(slug=slug)
    note = _text(data["note"], f"{where}.note", allow_empty=True) if data.get("note") is not None else ""
    template = data.get("template")
    if template is not None and template not in TEMPLATE_MODES:
        raise ChangeError(f"{where}.template: {template!r} is not one of {list(TEMPLATE_MODES)}")
    return Reference(
        change=change,
        note=note.strip(),
        expected_deltas=_deltas(data.get("expected_deltas"), f"{where}.expected_deltas", steps),
        base=_base(data.get("base"), f"{where}.base"),
        template=template,
    )


def _base(value: Any, where: str) -> str | None:
    """A SUT spec of one of BASE_KINDS (None when not set)."""
    if value is None:
        return None
    text = _text(value, where).strip()
    from otterdog_e2e.sut.spec import parse_sut_spec

    try:
        kind = parse_sut_spec(text).kind
    except ValueError as exc:
        raise ChangeError(f"{where}: {text!r} is not a SUT spec: {exc}") from None
    if kind not in BASE_KINDS:
        raise ChangeError(f"{where}: {text!r} is a {kind} spec, a base is one of {list(BASE_KINDS)}")
    return text


def _deltas(value: Any, where: str, steps: Sequence[str] | None) -> tuple[DeltaPattern, ...]:
    """``expected_deltas`` of a reference (unique entries; step patterns checked against ``steps``)."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ChangeError(f"{where}: expected a list of mappings {{step?, kind?, key?, note?}}")
    deltas: list[DeltaPattern] = []
    for index, item in enumerate(value):
        at = f"{where}[{index}]"
        data = _mapping(item, at)
        _check_keys(data, DELTA_KEYS, at)
        fields = {
            name: _text(data[name], f"{at}.{name}") if data.get(name) is not None else None
            for name in ("step", "kind", "key")
        }
        note = _text(data["note"], f"{at}.note", allow_empty=True).strip() if data.get("note") is not None else ""
        delta = DeltaPattern(fields["step"], fields["kind"], fields["key"], note)
        if delta.step is not None:
            if steps is None:
                raise ChangeError(f"{at}.step: a Python test has no steps (leave 'step' out)")
            if not any(fnmatch.fnmatchcase(name, delta.step) for name in steps):
                raise ChangeError(f"{at}.step: {delta.step!r} matches no step of the scenario (steps: {list(steps)})")
        if any((other.step, other.kind, other.key) == (delta.step, delta.kind, delta.key) for other in deltas):
            raise ChangeError(f"{at}: duplicate expected delta (step {delta.step}, kind {delta.kind}, key {delta.key})")
        deltas.append(delta)
    return tuple(deltas)


# --- referencing scenarios ----------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class ReferencingScenario:
    """A reference and the scenario declaring it: a YAML file (``kind`` yaml) or a Python test (``test``)."""

    scenario: str
    source: Path
    kind: str
    reference: Reference
    test: str | None = None


@dataclass
class ChangeSpec:
    """What the scenarios referencing one change declare for its differential run."""

    change: ChangeId
    base: str | None = None
    template: str = DEFAULT_TEMPLATE
    scenarios: list[str] = field(default_factory=list)
    expected_deltas: list[ExpectedDelta] = field(default_factory=list)
    referencing: list[ReferencingScenario] = field(default_factory=list)

    @property
    def label(self) -> str:
        """``#790`` or ``check-merge``."""
        return self.change.label


def conflicts(entries: Iterable[ReferencingScenario]) -> list[str]:
    """Changes whose references declare different ``base`` or ``template`` values (one message per change and key)."""
    by_change: dict[ChangeId, list[ReferencingScenario]] = {}
    for entry in entries:
        by_change.setdefault(entry.reference.change, []).append(entry)
    problems = []
    for change in sorted(by_change, key=ChangeId.sort_key):
        for key in ("base", "template"):
            values: dict[str, list[str]] = {}
            for entry in by_change[change]:
                value = getattr(entry.reference, key)
                if value is not None:
                    values.setdefault(value, []).append(entry.scenario)
            if len(values) > 1:
                listed = "; ".join(
                    f"{value!r} in {', '.join(sorted(set(ids)))}" for value, ids in sorted(values.items())
                )
                problems.append(f"{change.label}: conflicting '{key}' of its references ({listed})")
    return problems


def change_spec(change: ChangeId, entries: Iterable[ReferencingScenario]) -> ChangeSpec:
    """The ChangeSpec of ``change`` from every referencing entry (ChangeError when its references conflict)."""
    from otterdog_e2e.differential import ExpectedDelta

    selected = [entry for entry in entries if entry.reference.change == change]
    problems = conflicts(selected)
    if problems:
        raise ChangeError("; ".join(problems))
    spec = ChangeSpec(change=change, referencing=selected)
    spec.base = next((entry.reference.base for entry in selected if entry.reference.base), None)
    spec.template = next((entry.reference.template for entry in selected if entry.reference.template), DEFAULT_TEMPLATE)
    spec.scenarios = list(dict.fromkeys(entry.scenario for entry in selected))
    for entry in selected:
        for delta in entry.reference.expected_deltas:
            expected = ExpectedDelta(entry.scenario, delta.step, delta.kind, delta.key, delta.note)
            if expected not in spec.expected_deltas:
                spec.expected_deltas.append(expected)
    return spec


# --- reading the repository ---------------------------------------------------------------------------------------------
def yaml_references(path: Path) -> list[ReferencingScenario]:
    """References of one scenario file read leniently (the model validates the rest; ChangeError for invalid
    references, files without an id or references give [])."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if f"{REFERENCES_KEY}:" not in text:
        return []
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError:
        return []
    if not isinstance(data, dict) or not isinstance(data.get("id"), str) or data.get(REFERENCES_KEY) is None:
        return []
    raw_steps = data.get("steps")
    raw_steps = raw_steps if isinstance(raw_steps, list) else []
    steps = [str(step["name"]) for step in raw_steps if isinstance(step, dict) and step.get("name") is not None]
    try:
        references = parse_references(data[REFERENCES_KEY], steps=steps)
    except ChangeError as exc:
        raise ChangeError(f"{path}: {exc}") from None
    return [ReferencingScenario(data["id"], path, "yaml", reference) for reference in references]


def python_references(path: Path) -> list[ReferencingScenario]:
    """References of the ``pytest.mark.scenario(<id>, references=[...])`` markers of a test module (test functions and
    the module's ``pytestmark``), read from its AST: the id and the references must be literals or module-level
    constants (ChangeError otherwise, naming the line)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if REFERENCES_KEY not in text:
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except (SyntaxError, ValueError):
        return []
    constants = _module_constants(tree)
    found: list[ReferencingScenario] = []
    module_marks = _module_marks(tree)
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            functions = [item for item in node.body if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef)]
            marks = [*node.decorator_list, *module_marks]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            functions, marks = [node], module_marks
        else:
            continue
        for function in functions:
            if not function.name.startswith("test"):
                continue
            for call in _scenario_marks([*function.decorator_list, *marks]):
                found += _marker_references(path, call, function.name, constants)
    return found


def _module_constants(tree: ast.Module) -> dict[str, ast.expr]:
    """Module-level ``NAME = <expr>`` assignments (single target)."""
    constants: dict[str, ast.expr] = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            constants[node.targets[0].id] = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.value is not None:
            constants[node.target.id] = node.value
    return constants


def _module_marks(tree: ast.Module) -> list[ast.expr]:
    """Elements of a module-level ``pytestmark`` (a list, a tuple or one mark)."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "pytestmark" for target in node.targets):
            return list(node.value.elts) if isinstance(node.value, ast.List | ast.Tuple) else [node.value]
    return []


def _scenario_marks(nodes: Sequence[ast.expr]) -> list[ast.Call]:
    """The ``pytest.mark.scenario(...)`` calls among decorator / pytestmark nodes."""
    return [
        node
        for node in nodes
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "scenario"
        and isinstance(node.func.value, ast.Attribute)
        and node.func.value.attr == "mark"
    ]


def _literal(node: ast.expr, constants: Mapping[str, ast.expr]) -> Any:
    """The literal value of a node (a module constant name is resolved once); ValueError otherwise."""
    if isinstance(node, ast.Name) and node.id in constants:
        node = constants[node.id]
    return ast.literal_eval(node)


def _marker_references(
    path: Path, call: ast.Call, test: str, constants: Mapping[str, ast.expr]
) -> list[ReferencingScenario]:
    """The references of one scenario marker call ([] without the ``references`` keyword)."""
    keyword = next((item for item in call.keywords if item.arg == REFERENCES_KEY), None)
    if keyword is None:
        return []
    where = f"{path}:{call.lineno}"
    try:
        scenario = _literal(call.args[0], constants) if call.args else None
        value = _literal(keyword.value, constants)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        raise ChangeError(f"{where}: the scenario id and its references must be literals") from None
    if not isinstance(scenario, str) or not scenario:
        raise ChangeError(f"{where}: pytest.mark.scenario(...) with references needs a literal scenario id")
    try:
        references = parse_references(value, f"{test}: {REFERENCES_KEY}", steps=None)
    except ChangeError as exc:
        raise ChangeError(f"{where}: {exc}") from None
    return [ReferencingScenario(scenario, path, "python", reference, test) for reference in references]


def scenario_paths(scenarios_dir: Path) -> list[Path]:
    """YAML scenario files of the tier directories (scenarios.model.scenario_files of each)."""
    from otterdog_e2e.scenarios.model import scenario_files

    return [path for name in YAML_SCENARIO_DIRS for path in scenario_files(Path(scenarios_dir) / name)]


def python_test_files(tests_dir: Path) -> list[Path]:
    """Python test modules (``test_*.py``) of the e2e tier directories."""
    paths: list[Path] = []
    for name in PYTHON_TEST_DIRS:
        directory = Path(tests_dir) / name
        if directory.is_dir():
            paths += sorted(path for path in directory.rglob("test_*.py") if "__pycache__" not in path.parts)
    return paths


def collect_references(scenarios_dir: Path, tests_dir: Path) -> list[ReferencingScenario]:
    """Every reference of the repository: YAML scenarios, then Python tests (ChangeError for invalid ones)."""
    entries: list[ReferencingScenario] = []
    for path in scenario_paths(scenarios_dir):
        entries += yaml_references(path)
    for path in python_test_files(tests_dir):
        entries += python_references(path)
    return entries


def load_change(scenarios_dir: Path, tests_dir: Path, change: ChangeId) -> ChangeSpec:
    """The ChangeSpec of one change from the repository (ChangeError for invalid or conflicting references)."""
    return change_spec(change, collect_references(scenarios_dir, tests_dir))
