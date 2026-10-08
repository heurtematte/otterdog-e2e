"""Index of the scenarios and tests of an otterdog-e2e checkout, for the assist commands (read leniently; the
``references`` to otterdog PRs and named changes are read with changes.collect_references).

Scenario ids come from two places: the YAML files of the scenario tier directories (scenarios/offline, cli,
enterprise; read with yaml.safe_load only, so one broken file never hides the others: ``assist check``
validates files with the real model) and the ``pytest.mark.scenario("<id>")`` markers of the Python tests of the e2e
tiers (read from the AST, never imported). A covered_by item of the coverage matrix is such a scenario id or a pytest
node id (``tests/<tier>/<file>.py::test_x``); files_of resolves both to repository files.
"""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from otterdog_e2e.coverage_matrix import NODE_DIRS, NODE_ID_RE, SCENARIO_DIRS
from otterdog_e2e.scenarios.model import DIRECTORY_TIERS, scenario_files, tier_directory

if TYPE_CHECKING:
    from otterdog_e2e.changes import ReferencingScenario


@dataclass(frozen=True)
class ScenarioRef:
    """Where a scenario id is defined: a YAML file (``kind`` yaml) or a Python test (``kind`` python, ``test`` names
    the function), its tier, tags and title (first docstring line of a Python test); for YAML files also the step
    names, the scenario's ``known_bug`` and the (step, bug id) pairs of steps declaring one."""

    id: str
    kind: str
    path: Path
    tier: str | None
    tags: tuple[str, ...] = ()
    title: str = ""
    test: str | None = None
    steps: tuple[str, ...] = ()
    known_bug: str | None = None
    step_bugs: tuple[tuple[str, str], ...] = ()


class ProjectIndex:
    """Scenario ids and test files of the checkout at ``root`` (each source is read once)."""

    def __init__(self, root: Path) -> None:
        """Bind the index to the project root."""
        self.root = Path(root)
        self.scenarios_dir = self.root / "scenarios"
        self.tests_dir = self.root / "tests"
        self._references: list[ReferencingScenario] | None = None

    def relative(self, path: Path) -> str:
        """POSIX path relative to the project root (the absolute path outside it)."""
        resolved = Path(path).resolve()
        try:
            return resolved.relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(resolved)

    def yaml_files(self) -> list[Path]:
        """Scenario files of the tier directories (scenarios.model.scenario_files of each, sorted)."""
        return [path for name in SCENARIO_DIRS for path in scenario_files(self.scenarios_dir / name)]

    @cached_property
    def yaml_scenarios(self) -> dict[str, list[ScenarioRef]]:
        """Scenario id -> the YAML files declaring it (a list: duplicates are kept for the checks)."""
        found: dict[str, list[ScenarioRef]] = {}
        for path in self.yaml_files():
            ref = read_scenario_ref(path)
            if ref is not None:
                found.setdefault(ref.id, []).append(ref)
        return found

    @cached_property
    def python_scenarios(self) -> dict[str, list[ScenarioRef]]:
        """Scenario id -> the Python tests of the e2e tiers marked ``pytest.mark.scenario(<id>)``."""
        found: dict[str, list[ScenarioRef]] = {}
        for tier in NODE_DIRS:
            directory = self.tests_dir / tier
            if not directory.is_dir():
                continue
            for path in sorted(directory.rglob("test_*.py")):
                for ref in python_scenario_refs(path, tier):
                    found.setdefault(ref.id, []).append(ref)
        return found

    def references(self) -> list[ReferencingScenario]:
        """Every ``references`` entry of the checkout (changes.collect_references; changes.ChangeError when one is
        invalid)."""
        from otterdog_e2e.changes import collect_references

        if self._references is None:
            self._references = collect_references(self.scenarios_dir, self.tests_dir)
        return self._references

    def scenario_ids(self) -> set[str]:
        """Every scenario id of the checkout (YAML and Python)."""
        return set(self.yaml_scenarios) | set(self.python_scenarios)

    def refs(self, scenario_id: str) -> list[ScenarioRef]:
        """Definitions of a scenario id (YAML first, then Python tests)."""
        return [*self.yaml_scenarios.get(scenario_id, []), *self.python_scenarios.get(scenario_id, [])]

    def files_of(self, item: str) -> list[str]:
        """Repository files of a covered_by item: the files defining a scenario id, the module of a node id."""
        match = NODE_ID_RE.match(item)
        if match is not None:
            path = self.tests_dir / match["dir"] / match["file"]
            return [self.relative(path)] if path.is_file() else []
        return sorted({self.relative(ref.path) for ref in self.refs(item)})

    def tagged(self, tags: Iterable[str]) -> list[ScenarioRef]:
        """Scenario definitions carrying at least one of ``tags`` (sorted by id, then file)."""
        wanted = set(tags)
        refs = [
            ref
            for group in (self.yaml_scenarios, self.python_scenarios)
            for definitions in group.values()
            for ref in definitions
            if wanted & set(ref.tags)
        ]
        return sorted(refs, key=lambda ref: (ref.id, self.relative(ref.path), ref.test or ""))


def read_scenario_ref(path: Path) -> ScenarioRef | None:
    """The id, tier, tags and title of a scenario file read without validation (None when unreadable or id-less)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("id"), str):
        return None
    tier = data.get("tier")
    if not isinstance(tier, str):
        directory = tier_directory(path)
        tier = DIRECTORY_TIERS[directory][0] if directory is not None and directory in DIRECTORY_TIERS else None
    raw_tags = data.get("tags")
    tags = [raw_tags] if isinstance(raw_tags, str) else raw_tags if isinstance(raw_tags, list) else []
    title = data.get("title") if isinstance(data.get("title"), str) else ""
    steps: list[str] = []
    step_bugs: list[tuple[str, str]] = []
    raw_steps = data.get("steps")
    for index, step in enumerate(raw_steps if isinstance(raw_steps, list) else []):
        if not isinstance(step, dict):
            continue
        name = str(step.get("name") or f"step-{index + 1}")
        steps.append(name)
        bug = step.get("known_bug")
        bug_id = bug.get("id") if isinstance(bug, dict) else bug
        if isinstance(bug_id, str) and bug_id:
            step_bugs.append((name, bug_id))
    known_bug = data.get("known_bug") if isinstance(data.get("known_bug"), str) else None
    return ScenarioRef(
        data["id"],
        "yaml",
        path,
        tier,
        tuple(str(tag) for tag in tags),
        str(title),
        steps=tuple(steps),
        known_bug=known_bug,
        step_bugs=tuple(step_bugs),
    )


def python_scenario_refs(path: Path, tier: str) -> list[ScenarioRef]:
    """The ``pytest.mark.scenario(<id>)`` markers of the test functions of a module (module ``pytestmark`` included),
    with the ``pytest.mark.tags(...)`` of the function and module."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, SyntaxError, ValueError):
        return []
    module_marks = _module_marks(tree)
    refs = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or not node.name.startswith("test_"):
            continue
        marks = [*node.decorator_list, *module_marks]
        tags = tuple(dict.fromkeys(marker_args(marks, "tags")))
        title = (ast.get_docstring(node) or "").strip().split("\n", 1)[0]
        for scenario_id in dict.fromkeys(marker_args(marks, "scenario")):
            refs.append(ScenarioRef(scenario_id, "python", path, tier, tags, title, node.name))
    return refs


def _module_marks(tree: ast.Module) -> list[ast.expr]:
    """Elements of a module-level ``pytestmark = [...]`` (or the single mark)."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == "pytestmark" for target in node.targets):
            return list(node.value.elts) if isinstance(node.value, ast.List | ast.Tuple) else [node.value]
    return []


def marker_args(nodes: Sequence[ast.expr], name: str) -> list[str]:
    """String arguments of the ``pytest.mark.<name>(...)`` calls among ``nodes``."""
    found = []
    for node in nodes:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name:
            found += [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
    return found
