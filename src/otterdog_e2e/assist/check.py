"""``otterdog-e2e assist check``: validation of the files an agent wrote or changed (never trusted as written).

Without paths, the files of the work tree under scenarios/ and tests/ that ``git status --porcelain`` reports
(changed_files; deleted files are listed, not checked). Each file is checked by its kind:

* scenario YAML: the real model (scenarios.model.load_scenario: keys, fragments, files, secrets, templates, tiers and
  the ``references`` to otterdog PRs or named changes: exactly one of pr/change, a base that is a release, tag, branch
  or sha spec, expected delta steps of the scenario, no duplicates), an id unique across the scenario directories, the
  references of each change consistent across the repository (one ``base`` and one ``template``: changes.conflicts),
  ``known_bug`` ids that exist and link back (known_bugs.check_references, step-level rules included), and the
  conventions the unit tests enforce (an id and a file name naming the behaviour, never a PR number; live: id prefix
  of the directory, a model area tag, known-bug tag and priority, the regression documentation, the plan of
  enterprise scenarios; offline: a title, a description of at least 20 words, tags of the vocabulary starting with
  ``offline``, ``observe: true``);
* scenarios/coverage.yaml: every check of the coverage matrix tests (coverage_matrix.MatrixProject.all_problems,
  generated documentation included);
* scenarios/known_bugs.yaml: it loads, sorted by id, ``status: fixed`` exactly with ``fixed_in``, evidence, listed
  scenarios exist, scenario and step links (check_references), a docs/known-issues.md section per bug;
* jsonnet files below scenarios/: the scenarios referencing them are checked (a file nobody references is noted);
* Python tests: they parse, their ``known_bug`` markers name existing bugs, the ``references`` of their
  ``pytest.mark.scenario`` markers are valid literals (changes.python_references) and their scenario ids carry no PR
  number (run them with pytest).

The command then lints the live scenarios offline (the ``-k lint`` items of the offline suite restricted to their ids:
lint_keyword, lint_result) unless a problem was found (an invalid scenario breaks the offline suite's collection).
"""

from __future__ import annotations

import ast
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from otterdog_e2e.assist.repo import ProjectIndex, marker_args

if TYPE_CHECKING:
    from otterdog_e2e.known_bugs import KnownBug
    from otterdog_e2e.scenarios.model import Scenario

GIT_PATHS = ("scenarios", "tests")
COVERAGE_NAME = "coverage.yaml"
KNOWN_BUGS_NAME = "known_bugs.yaml"
JSONNET_SUFFIXES = (".jsonnet", ".libsonnet")
YAML_SUFFIXES = (".yaml", ".yml")
LIVE_DIRS = ("cli", "regressions", "enterprise")
ID_PREFIXES = {"cli": "cli.", "regressions": "regression.", "enterprise": "enterprise."}
OFFLINE_MIN_DESCRIPTION_WORDS = 20
# a run of 3+ digits in a scenario id or file name reads as a PR or issue number: name the behaviour instead
NUMBER_RE = re.compile(r"(?<![0-9])[0-9]{3,}(?![0-9])")
DIGITS_RE = re.compile(r"[0-9]+")
LINT_TEST = "test_live_scenario_lint"
LINT_ITEM_RE = re.compile(rf"{LINT_TEST}\[(?P<id>[^/\]]+)/(?P<step>.+)\]$")
LINT_MESSAGE_LINES = 4
_LOCATION_RE = re.compile(r"^(?P<where>[A-Za-z_][\w.\-\[\]]*): (?P<message>.+)$", re.DOTALL)
_KNOWN_ISSUE_RE = re.compile(r"(?m)^### ")


@dataclass(frozen=True, order=True)
class Problem:
    """One problem: the file (relative to the project), where in it (a key path, a feature, a step) and what."""

    file: str
    location: str
    message: str

    def to_json(self) -> dict[str, str]:
        """``{file, location, message}``."""
        return asdict(self)


@dataclass
class CheckResult:
    """What check_files found: the files and their kind, the problems, notes and the live scenarios to lint."""

    files: list[dict[str, str]] = field(default_factory=list)
    problems: list[Problem] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    live: dict[str, str] = field(default_factory=dict)  # live scenario id -> its file, linted offline
    lint: dict[str, Any] | None = None

    @property
    def ok(self) -> bool:
        """True without any problem (lint problems included)."""
        return not self.problems

    def to_json(self) -> dict[str, Any]:
        """The JSON printed by ``assist check --json``."""
        return {
            "kind": "check",
            "ok": self.ok,
            "files": sorted(self.files, key=lambda item: item["path"]),
            "problems": [problem.to_json() for problem in sorted(set(self.problems))],
            "notes": sorted(set(self.notes)),
            "lint": self.lint,
        }


# --- the files to check --------------------------------------------------------------------------------------------------
def changed_files(project_root: Path) -> tuple[list[Path], list[str]]:
    """(existing files, deleted paths) changed in the work tree under scenarios/ and tests/ (``git status
    --porcelain``, untracked files included; renamed files count by their new name)."""
    from otterdog_e2e.sut.source import LOCAL_GIT_ENV, GitCommandError, run_git

    try:
        result = run_git(
            ["status", "--porcelain=v1", "-z", "--untracked-files=all", "--", *GIT_PATHS],
            cwd=project_root,
            extra_env=LOCAL_GIT_ENV,
            timeout=120,
        )
    except GitCommandError as exc:
        raise ValueError(f"cannot list the changed files (give the paths to check): {exc}") from None
    entries = result.stdout.split("\0")
    existing: set[Path] = set()
    deleted: set[str] = set()
    index = 0
    while index < len(entries):
        entry = entries[index]
        index += 1
        if len(entry) < 4:
            continue
        status, path = entry[:2], entry[3:]
        if status[0] in "RC":
            index += 1  # the next entry is the original path of a rename or copy
        if "D" in status:
            deleted.add(path)
            continue
        if (project_root / path).is_file():
            existing.add(project_root / path)
    return sorted(existing), sorted(deleted)


def file_kind(path: Path, root: Path) -> str:
    """Kind of a file: coverage, known-bugs, scenario, jsonnet, python or other."""
    relative = _relative(path, root)
    parts = PurePosixPath(relative).parts
    in_scenarios = len(parts) > 1 and parts[0] == "scenarios"
    if path.suffix == ".py":
        return "python"
    if in_scenarios and path.suffix in JSONNET_SUFFIXES:
        return "jsonnet"
    if path.suffix not in YAML_SUFFIXES or not in_scenarios:
        return "other"
    if relative == f"scenarios/{COVERAGE_NAME}":
        return "coverage"
    if path.name == KNOWN_BUGS_NAME:
        return "known-bugs"
    return "scenario"


def _relative(path: Path, root: Path) -> str:
    """POSIX path relative to the project root (absolute outside it)."""
    resolved = Path(path).resolve()
    try:
        return resolved.relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return str(resolved)


def _top_dir(path: Path, root: Path) -> str | None:
    """The directory right below scenarios/ holding a scenario file (None outside scenarios/)."""
    parts = PurePosixPath(_relative(path, root)).parts
    return parts[1] if len(parts) > 2 and parts[0] == "scenarios" else None


def split_location(message: str) -> tuple[str, str]:
    """(location, message) of a model error ``steps[0].plan: ...`` (no location when it does not start with one)."""
    match = _LOCATION_RE.match(message)
    if match is None:
        return "", message
    return match.group("where"), match.group("message")


# --- the checker -------------------------------------------------------------------------------------------------------
class Checker:
    """Checks files of the checkout at ``root`` (the scenario index and the known bugs are read once)."""

    def __init__(self, root: Path) -> None:
        """Bind the checks to the project root."""
        self.root = Path(root).resolve()
        self.index = ProjectIndex(self.root)
        self.result = CheckResult()
        self._bugs: dict[str, KnownBug] | None = None
        self._bugs_error: str | None = None
        self._checked: set[Path] = set()

    def problem(self, path: Path | str, location: str, message: str) -> None:
        """Record a problem of a file."""
        file = path if isinstance(path, str) else _relative(path, self.root)
        self.result.problems.append(Problem(file, location, " ".join(str(message).split())))

    def bugs(self) -> dict[str, KnownBug]:
        """scenarios/known_bugs.yaml ({} when it cannot be read: run() reports the error once)."""
        if self._bugs is None:
            from otterdog_e2e.known_bugs import KnownBugError, load

            try:
                self._bugs = load(self.root / "scenarios" / KNOWN_BUGS_NAME)
            except KnownBugError as exc:
                self._bugs, self._bugs_error = {}, str(exc)
        return self._bugs

    def run(self, paths: Iterable[Path], deleted: Sequence[str] = ()) -> CheckResult:
        """Check every path (sorted, each once) and return the result."""
        for relative in sorted(set(deleted)):
            self.result.files.append({"path": relative, "kind": "deleted"})
            self.result.notes.append(f"{relative}: deleted (references to it are checked by the unit tests)")
        for path in sorted({Path(path).resolve() for path in paths}):
            self.check(path)
        if self._bugs_error and not any(p.file.endswith(KNOWN_BUGS_NAME) for p in self.result.problems):
            self.problem(f"scenarios/{KNOWN_BUGS_NAME}", "", self._bugs_error)
        return self.result

    def check(self, path: Path) -> None:
        """Check one file by its kind (once)."""
        if path in self._checked:
            return
        self._checked.add(path)
        kind = file_kind(path, self.root) if path.exists() else "missing"
        self.result.files.append({"path": _relative(path, self.root), "kind": kind})
        if kind == "missing":
            self.problem(path, "", "no such file")
            return
        handler = {
            "coverage": self.check_coverage,
            "known-bugs": self.check_known_bugs,
            "scenario": self.check_scenario,
            "jsonnet": self.check_jsonnet,
            "python": self.check_python,
        }.get(kind)
        if handler is None:
            self.result.notes.append(f"{_relative(path, self.root)}: not checked (no rule for this kind of file)")
            return
        handler(path)

    # --- scenarios -------------------------------------------------------------------------------------------------
    def check_scenario(self, path: Path) -> Scenario | None:
        """A scenario file: the model, a unique id, its known bugs and the repository conventions."""
        from otterdog_e2e.scenarios.model import ScenarioError, load_scenario

        try:
            scenario = load_scenario(path)
        except ScenarioError as exc:
            location, message = split_location(str(exc).removeprefix(f"{path}: "))
            self.problem(path, location, message)
            return None
        others = [ref.path for ref in self.index.yaml_scenarios.get(scenario.id, []) if ref.path.resolve() != path]
        for other in sorted(others):
            self.problem(path, "id", f"duplicate scenario id {scenario.id!r} (also in {_relative(other, self.root)})")
        self._scenario_bugs(path, scenario)
        self._references(path, scenario)
        self._conventions(path, scenario)
        if scenario.is_live:
            self.result.live[scenario.id] = _relative(path, self.root)
        return scenario

    def _scenario_bugs(self, path: Path, scenario: Scenario) -> None:
        """Known bugs of the scenario and its steps exist; a scenario-level bug lists the scenario; a step-level bug
        does not (known_bugs.check_references)."""
        from otterdog_e2e.known_bugs import check_references

        bugs = self.bugs()
        if self._bugs_error:
            return
        steps = [(scenario.id, step.name, step.known_bug) for step in scenario.steps if step.known_bug]
        for problem in check_references(bugs, [(scenario.id, scenario.known_bug)], steps):
            if " lists unknown scenario " not in problem:
                self.problem(path, "known_bug", problem)
        bug = bugs.get(scenario.known_bug or "")
        if bug is not None and scenario.id not in bug.scenarios:
            self.problem(path, "known_bug", f"{bug.id} does not list {scenario.id!r} in its scenarios")

    def _references(self, path: Path, scenario: Scenario) -> None:
        """The changes the scenario references: their references across the repository agree on ``base`` and
        ``template`` (the model checked the scenario's own entries)."""
        from otterdog_e2e.changes import ChangeError, ReferencingScenario, conflicts

        changes = {reference.change for reference in scenario.references}
        if not changes:
            return
        try:
            entries = self.index.references()
        except ChangeError as exc:
            self.problem(path, "references", f"the references of the repository cannot be read: {exc}")
            return
        others = [entry for entry in entries if entry.reference.change in changes and entry.source.resolve() != path]
        own = [ReferencingScenario(scenario.id, path, "yaml", reference) for reference in scenario.references]
        for problem in conflicts([*others, *own]):
            self.problem(path, "references", problem)

    def _named_after_behaviour(self, path: Path, scenario_id: str, numbers: set[int], *, where: str = "id") -> None:
        """A scenario id and its file name name the behaviour: no number of a referenced PR, no PR-like number."""
        for label, text in ((where, scenario_id), ("file name", path.stem)):
            found = NUMBER_RE.findall(text)
            referenced = sorted({int(number) for number in DIGITS_RE.findall(text)} & numbers)
            if referenced:
                self.problem(
                    path,
                    label,
                    f"{text!r} carries the number of a PR it references ({', '.join(f'#{n}' for n in referenced)}): "
                    "name the behaviour, the PR goes in the references",
                )
            elif found:
                self.problem(
                    path, label, f"{text!r} carries a PR-like number ({', '.join(found)}): name the behaviour instead"
                )

    def _conventions(self, path: Path, scenario: Scenario) -> None:
        """The conventions of tests/unit/test_yaml_cli.py (live) and tests/unit/test_yaml_offline.py (offline)."""
        from otterdog_e2e.selection import MODEL_TAGS, SCENARIO_TAGS

        numbers = {reference.change.pr for reference in scenario.references if reference.change.pr is not None}
        self._named_after_behaviour(path, scenario.id, numbers)
        top = _top_dir(path, self.root)
        if top in LIVE_DIRS:
            if not scenario.id.startswith(ID_PREFIXES[top]):
                self.problem(path, "id", f"ids of scenarios/{top}/ start with {ID_PREFIXES[top]!r}")
            if not set(MODEL_TAGS) & set(scenario.tags):
                self.problem(
                    path, "tags", f"no model area tag ({', '.join(MODEL_TAGS)}): path-based selection misses it"
                )
            if scenario.known_bug is not None and ("known-bug" not in scenario.tags or scenario.priority == "P0"):
                self.problem(
                    path, "known_bug", "a scenario linked to a known bug has the 'known-bug' tag and is not P0"
                )
            if (scenario.tier == "enterprise") != (scenario.min_plan == "enterprise"):
                self.problem(path, "min_plan", "scenarios/enterprise need min_plan enterprise, the others never do")
            if top == "regressions":
                self._regression(path, scenario)
        elif top == "offline":
            if len(scenario.description.split()) < OFFLINE_MIN_DESCRIPTION_WORDS:
                self.problem(
                    path, "description", f"describe why the scenario exists ({OFFLINE_MIN_DESCRIPTION_WORDS} words)"
                )
            if not scenario.tags or scenario.tags[0] != "offline":
                self.problem(path, "tags", "the tags of an offline scenario start with 'offline'")
            unknown = sorted(set(scenario.tags) - set(SCENARIO_TAGS))
            if unknown:
                self.problem(
                    path, "tags", f"unknown tag(s) {unknown}, the selection vocabulary is {list(SCENARIO_TAGS)}"
                )
            if not scenario.observe:
                self.problem(path, "observe", "offline scenarios set observe: true (recorded by tests/differential)")

    def _regression(self, path: Path, scenario: Scenario) -> None:
        """A regression references the PR(s) of its fix (``references: [{pr: <n>}]``) and links them in its
        description, has the regression tag, an id naming the behaviour, and states the known-bad version."""
        numbers = [reference.change.pr for reference in scenario.references if reference.change.pr is not None]
        if not numbers:
            self.problem(path, "references", "a regression references the PR(s) of its fix: references: [{pr: <n>}]")
            return
        if "regression" not in scenario.tags:
            self.problem(path, "tags", "a regression has the 'regression' tag")
        for number in numbers:
            if not re.search(rf"otterdog/(pull|issues)/{number}\b", scenario.description):
                self.problem(path, "description", f"link the upstream otterdog/pull/{number} (or issues/{number})")
        if "Known-bad" not in scenario.description:
            self.problem(path, "description", "state the known-bad version ('Known-bad: ...')")

    # --- coverage matrix and known bugs ----------------------------------------------------------------------------
    def check_coverage(self, path: Path) -> None:
        """scenarios/coverage.yaml: every check of the coverage matrix tests (the generated doc included)."""
        from otterdog_e2e.coverage_matrix import MatrixError, MatrixProject
        from otterdog_e2e.known_bugs import KnownBugError
        from otterdog_e2e.scenarios.model import ScenarioError

        project = MatrixProject(self.root)
        try:
            problems = project.all_problems()
        except MatrixError as exc:
            self.problem(path, "", str(exc).removeprefix(f"{path}: "))
            return
        except (ScenarioError, KnownBugError, OSError) as exc:
            self.problem(path, "", f"the matrix cannot be checked: {exc}")
            return
        for problem in problems:
            match = re.match(r"^feature '(?P<id>[^']+)': (?P<message>.+)$", problem, re.DOTALL)
            if match is not None:
                self.problem(path, f"feature {match.group('id')}", match.group("message"))
            else:
                self.problem(path, "", problem)

    def check_known_bugs(self, path: Path) -> None:
        """scenarios/known_bugs.yaml: loads, order, fixed_in, evidence, scenario links and its documentation."""
        import yaml

        from otterdog_e2e.known_bugs import KnownBugError, check_references, load

        try:
            bugs = load(path)
        except KnownBugError as exc:
            self.problem(path, "", str(exc).removeprefix(f"{path}: "))
            return
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        ids = [str(item.get("id")) for item in raw if isinstance(item, dict)]
        if ids != sorted(ids):
            self.problem(path, "", "keep the entries sorted by id")
        for bug in bugs.values():
            if (bug.status == "fixed") != (bug.fixed_in is not None):
                self.problem(path, bug.id, "status fixed goes with fixed_in (and fixed_in only with status fixed)")
            if not bug.evidence:
                self.problem(path, bug.id, "no evidence (path:line of otterdog, or e2e: <file of this project>)")
        yaml_refs = [ref for refs in self.index.yaml_scenarios.values() for ref in refs]
        pairs = [(ref.id, ref.known_bug) for ref in yaml_refs]
        pairs += [
            (scenario_id, None)
            for scenario_id in self.index.python_scenarios
            if scenario_id not in self.index.yaml_scenarios
        ]
        steps = [(ref.id, step, bug_id) for ref in yaml_refs for step, bug_id in ref.step_bugs]
        for problem in check_references(bugs, pairs, steps):
            match = re.match(r"^(KB-\d+) ", problem)
            self.problem(path, match.group(1) if match else "", problem)
        self._known_issues(path, bugs)

    def _known_issues(self, path: Path, bugs: Mapping[str, KnownBug]) -> None:
        """docs/known-issues.md has a '### KB-nnn' section per bug stating its status."""
        doc = self.root / "docs" / "known-issues.md"
        if not doc.is_file():
            return
        sections = {
            match.group(1): part
            for part in _KNOWN_ISSUE_RE.split(doc.read_text(encoding="utf-8"))[1:]
            if (match := re.match(r"(KB-\d{3,})\b", part))
        }
        for bug in bugs.values():
            if bug.id not in sections:
                self.problem(path, bug.id, "docs/known-issues.md has no '### " + bug.id + "' section")
            elif f"Status: **{bug.status}**" not in sections[bug.id]:
                self.problem(
                    path, bug.id, f"its docs/known-issues.md section does not state 'Status: **{bug.status}**'"
                )

    # --- jsonnet and Python ------------------------------------------------------------------------------------------
    def check_jsonnet(self, path: Path) -> None:
        """A jsonnet file below scenarios/: the scenarios referencing it are checked (their model reads it)."""
        users = sorted(
            ref.path for refs in self.index.yaml_scenarios.values() for ref in refs if path in _file_refs(ref.path)
        )
        if not users:
            self.result.notes.append(
                f"{_relative(path, self.root)}: referenced by no scenario (tests/unit/test_scenarios_files_repo.py "
                "wants every shared file used by a scenario or an inject recipe, and documented)"
            )
        for user in users:
            self.check(user.resolve())

    def check_python(self, path: Path) -> None:
        """A Python file: it parses; the known_bug markers of its tests name existing bugs; the references of its
        scenario markers are valid; its scenario ids name the behaviour (no PR number)."""
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError as exc:
            self.problem(path, f"line {exc.lineno}", f"syntax error: {exc.msg}")
            return
        except (OSError, UnicodeDecodeError, ValueError) as exc:
            self.problem(path, "", f"cannot be read: {exc}")
            return
        bugs = self.bugs()
        if not self._bugs_error:
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    for bug_id in marker_args(node.decorator_list, "known_bug"):
                        if bug_id not in bugs:
                            self.problem(path, node.name, f"known_bug marker names unknown bug {bug_id!r}")
        self._python_references(path, tree)
        self.result.notes.append(f"{_relative(path, self.root)}: parsed only, run it with pytest")

    def _python_references(self, path: Path, tree: ast.Module) -> None:
        """The references of the scenario markers (literals, valid entries, consistent with the repository) and the
        scenario ids of the module (no PR number)."""
        from otterdog_e2e.changes import ChangeError, conflicts, python_references

        try:
            own = python_references(path)
        except ChangeError as exc:
            self.problem(path, "references", str(exc).removeprefix(f"{path}:"))
            return
        numbers: dict[str, set[int]] = {}
        for entry in own:
            if entry.reference.change.pr is not None:
                numbers.setdefault(entry.scenario, set()).add(entry.reference.change.pr)
        scenario_ids = {
            scenario_id
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
            for scenario_id in marker_args(node.decorator_list, "scenario")
        }
        for scenario_id in sorted(scenario_ids | set(numbers)):
            self._named_after_behaviour(path, scenario_id, numbers.get(scenario_id, set()), where=scenario_id)
        changes = {entry.reference.change for entry in own}
        if not changes:
            return
        try:
            entries = self.index.references()
        except ChangeError as exc:
            self.problem(path, "references", f"the references of the repository cannot be read: {exc}")
            return
        others = [entry for entry in entries if entry.reference.change in changes and entry.source.resolve() != path]
        for problem in conflicts([*others, *own]):
            self.problem(path, "references", problem)


def _file_refs(scenario_file: Path) -> set[Path]:
    """Files a scenario references (``file:`` entries and library paths), resolved against its directory."""
    import yaml

    try:
        data = yaml.safe_load(scenario_file.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return set()
    found: set[Path] = set()

    def walk(value: Any, key: str | None = None) -> None:
        """Collect ``file`` values and library entries."""
        if isinstance(value, dict):
            for name, item in value.items():
                if isinstance(item, str) and (key == "libraries" or name in ("file", "config", "base_config")):
                    found.add((scenario_file.parent / item).resolve())
                else:
                    walk(item, str(name))
        elif isinstance(value, list):
            for item in value:
                walk(item, key)

    walk(data)
    return found


def check_files(project_root: Path, paths: Iterable[Path], deleted: Sequence[str] = ()) -> CheckResult:
    """Check ``paths`` (and record ``deleted``) in the checkout at ``project_root``."""
    return Checker(project_root).run(paths, deleted)


def lint_skipped(result: CheckResult, *, no_lint: bool) -> str | None:
    """Why the offline lint does not run for this result (None: it runs): --no-lint, no live scenario, or problems
    (an invalid scenario file breaks the collection of the offline suite)."""
    if no_lint:
        return "--no-lint"
    if not result.live:
        return "no live scenario (scenarios/cli, regressions, enterprise) among the checked files"
    if result.problems:
        return "fix the problems first: an invalid scenario breaks the collection of the offline suite"
    return None


# --- offline lint -------------------------------------------------------------------------------------------------------
def lint_keyword(scenario_ids: Iterable[str]) -> str:
    """The pytest -k expression selecting the lint items of these scenarios (``test_live_scenario_lint[<id>/<step>]``;
    ``[<id>/`` matches the id exactly)."""
    ids = sorted(set(scenario_ids))
    if not ids:
        raise ValueError("no scenario to lint")
    return f"{LINT_TEST} and ({' or '.join(f'[{scenario_id}/' for scenario_id in ids)})"


def lint_result(
    run_dir: Path, exit_code: int, live: Mapping[str, str], *, sut: str
) -> tuple[dict[str, Any], list[Problem]]:
    """(the lint summary, its problems) from the results of the lint run: failed or errored items are problems of
    their scenario file, a scenario without any lint item or a pytest failure without results too."""
    from otterdog_e2e.report import RESULTS_FILE, SUMMARY_FILE, aggregate_results, read_jsonl

    lines, _malformed = read_jsonl(run_dir / RESULTS_FILE)
    records = [record for record in aggregate_results(lines) if LINT_ITEM_RE.search(record.nodeid)]
    problems: list[Problem] = []
    notes: list[str] = []
    seen: set[str] = set()
    outcomes: dict[str, int] = {}
    for record in sorted(records, key=lambda item: item.nodeid):
        match = LINT_ITEM_RE.search(record.nodeid)
        assert match is not None  # filtered above
        scenario_id, step = match.group("id"), match.group("step")
        seen.add(scenario_id)
        outcomes[record.outcome] = outcomes.get(record.outcome, 0) + 1
        file = live.get(scenario_id, scenario_id)
        if record.is_failure:
            text = "\n".join((record.failure or "no failure text").splitlines()[:LINT_MESSAGE_LINES])
            problems.append(Problem(file, f"step {step}", f"offline lint {record.outcome}: {text}"))
        elif record.outcome in ("skipped", "xfailed"):
            notes.append(f"{file}: step {step} {record.outcome}: {record.reason or '-'}")
    summary = run_dir / SUMMARY_FILE
    for scenario_id in sorted(set(live) - seen):
        problems.append(Problem(live[scenario_id], "", "no lint item ran for this scenario (see the lint summary)"))
    if exit_code != 0 and not problems:
        problems.append(Problem("(lint)", "", f"the lint run exited with pytest code {exit_code}, see {summary}"))
    data = {
        "ran": True,
        "sut": sut,
        "scenarios": sorted(live),
        "keyword": lint_keyword(live) if live else None,
        "exit_code": exit_code,
        "run_dir": str(run_dir),
        "summary": str(summary),
        "outcomes": dict(sorted(outcomes.items())),
        "notes": sorted(notes),
    }
    return data, problems


# --- rendering -----------------------------------------------------------------------------------------------------------
def render_text(result: CheckResult) -> str:
    """The human summary of ``assist check``: checked files, problems (file, location, message), lint, notes."""
    data = result.to_json()
    lines = [
        f"checked {len(data['files'])} file(s): "
        + (", ".join(f"{item['path']} ({item['kind']})" for item in data["files"]) or "none")
    ]
    for problem in data["problems"]:
        where = f"{problem['file']}" + (f" [{problem['location']}]" if problem["location"] else "")
        lines.append(f"PROBLEM {where}: {problem['message']}")
    lint = data["lint"]
    if lint is None:
        lines.append("lint: not run")
    elif not lint.get("ran"):
        lines.append(f"lint: skipped ({lint.get('skipped')})")
    else:
        outcomes = ", ".join(f"{count} {name}" for name, count in lint["outcomes"].items()) or "no item"
        lines.append(f"lint ({lint['sut']}): {outcomes}; exit code {lint['exit_code']}; summary {lint['summary']}")
        lines += [f"  {note}" for note in lint["notes"]]
    lines += [f"note: {note}" for note in data["notes"]]
    lines.append("OK: no problem found" if result.ok else f"FAILED: {len(data['problems'])} problem(s)")
    return "\n".join(lines)
