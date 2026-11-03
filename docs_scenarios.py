"""MkDocs hooks of the scenario explorer (``hooks:`` in mkdocs.yml, after docs_hooks.py).

The site gets a browsable view of every test, generated when the site is built from the sources of the commit being
built, so it never drifts from them:

* one page per YAML scenario (``scenarios/<tier>/<domain>/<file>.yaml`` -> ``scenarios/<tier>/<domain>/<file>.md``):
  what it tests, its context (tier, SUT versions, capabilities, otterdog pull requests, known bugs, the features of
  the coverage matrix it covers and their otterdog sources), each step (the jsonnet it adds, the otterdog commands it
  runs, what it expects of them and of GitHub), the Python code that refers to it, how to run it and its YAML source;
* one page per Python test module of a tier (``tests/<tier>/test_*.py`` -> ``scenarios/python-tests/<tier>/...``):
  every test with its markers, docstring, covered features and source;
* overview pages whose tables filter and sort in the browser (docs/assets/explorer.js), and their place in the
  navigation: the nav entry ``scenarios/index.md`` of mkdocs.yml becomes a section holding them all.

Links to code point to GitHub: the harness at ``main`` (the branch the site is built from), otterdog at the commit of
the coverage matrix (``otterdog.ref`` of scenarios/coverage.yaml). The edit button of a generated page opens its source.

Only the standard library is needed at import time (PyYAML and packaging, dependencies of MkDocs, are imported by the
functions that need them): tests/unit/test_docs_scenarios.py imports this file without MkDocs.
"""

from __future__ import annotations

import ast
import inspect
import logging
import posixpath
import re
import textwrap
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files
    from mkdocs.structure.pages import Page

# below the "mkdocs" logger, so its warnings count for `mkdocs build --strict`
log = logging.getLogger("mkdocs.plugins.docs_scenarios")

# the generated pages live below docs/<EXPLORER>/ (a directory that must not exist in the repository)
EXPLORER = "scenarios"
INDEX = f"{EXPLORER}/index.md"
PYTHON_DIR = f"{EXPLORER}/python-tests"
PYTHON_INDEX = f"{PYTHON_DIR}/index.md"
# the branch the site is built from (also in docs_hooks.py and the edit_uri of mkdocs.yml)
BRANCH = "main"
UPSTREAM = "https://github.com/eclipse-csi/otterdog"
SCENARIOS_DIR = "scenarios"
TESTS_DIR = "tests"
CHECKS = "src/otterdog_e2e/scenarios/checks.py"
ORACLE = "src/otterdog_e2e/github/oracle.py"
COVERAGE = "scenarios/coverage.yaml"
KNOWN_BUGS = "scenarios/known_bugs.yaml"
KNOWN_ISSUES = "known-issues.md"
COVERAGE_MATRIX = "coverage-matrix.md"
WRITING = "writing-scenarios.md"

Slugify = Callable[[str, str], str]


@dataclass(frozen=True)
class Tier:
    """A YAML scenario tier: its directory, the module that collects it, the engine and what a step runs."""

    name: str
    title: str
    runner: str
    engine: str
    needs: str
    runs: str


# links in these texts are relative to docs/, prefixed with {docs} (the way from the page back to docs/)
TIERS = (
    Tier(
        "offline",
        "Offline scenarios",
        "tests/offline/test_scenarios.py",
        "src/otterdog_e2e/scenarios/offline.py",
        "the SUT only: no organization, no credential, no network",
        "The otterdog CLI of the SUT runs against the minimal organization `e2e-offline` (plan `free` unless the "
        "scenario's `variables.plan` says otherwise), with the SUT's template vendored and the network blocked. "
        "Every step is an independent case, one pytest item `test_offline_scenario[<id>/<step>]` with a fresh "
        "workspace: `validate --local` (always), `local-plan --local` against a `-BASE` configuration when the step "
        "gives one, `show --local`, then the extra commands. "
        "See [Offline scenarios]({docs}writing-scenarios.md#offline-scenarios).",
    ),
    Tier(
        "cli",
        "Live CLI scenarios",
        "tests/cli/test_scenarios.py",
        "src/otterdog_e2e/scenarios/engine.py",
        "a target organization (`TARGET`) and its admin identity",
        "One pytest item per scenario, on the target organization. Each step writes the organization's baseline plus "
        "its fragments, runs `validate` (when given), `plan`, `apply` (when the plan expects changes), checks the "
        "GitHub state through the independent read-only oracle and plans again until this run's objects are a no-op "
        "(converge). Steps are chained: each one starts from the state the previous one left, the first failure stops "
        "the scenario, the cleanup always runs. Every object carries the run prefix, and plans are filtered with "
        "`-r <prefix>-*` unless the scenario is organization-level. Every step is also linted offline "
        "(`validate --local`). See [Steps are declarative]({docs}writing-scenarios.md#steps-are-declarative).",
    ),
    Tier(
        "enterprise",
        "Enterprise scenarios",
        "tests/enterprise/test_scenarios.py",
        "src/otterdog_e2e/scenarios/engine.py",
        "a target organization with plan `enterprise` and its admin identity",
        "Live scenarios like the [live CLI ones]({docs}scenarios/cli/index.md), for the features only GitHub "
        "Enterprise Cloud offers: they run on a target organization with plan `enterprise`.",
    ),
)
TIER_BY_NAME = {tier.name: tier for tier in TIERS}


@dataclass(frozen=True)
class PythonTier:
    """A tier of Python tests (``tests/<name>/test_*.py``) and how to run one of its tests."""

    name: str
    title: str
    needs: str
    make: str
    live: bool


PYTHON_TIERS = (
    PythonTier("offline", "Offline", "the SUT (docker for the webapp part)", "make offline", live=False),
    PythonTier("cli", "Live CLI", "a target organization and its admin identity", "make cli TARGET=<instance>", True),
    PythonTier(
        "webhooks", "Webhooks", "a target organization (+ the e2e GitHub App)", "make webhooks TARGET=<instance>", True
    ),
    PythonTier(
        "webapp",
        "Webapp",
        "a target organization, the e2e GitHub App and docker",
        "make webapp TARGET=<instance>",
        True,
    ),
    PythonTier(
        "web_ui",
        "Web UI",
        "a target organization, the admin bot's web credentials, a trusted SUT",
        "make web-ui TARGET=<instance>",
        live=True,
    ),
    PythonTier(
        "enterprise",
        "Enterprise",
        "a target organization with plan `enterprise`",
        "make enterprise TARGET=<instance>",
        True,
    ),
    PythonTier(
        "differential",
        "Differential",
        "a base SUT (+ a target for the live part)",
        "make differential BASE_SUT=<sut>",
        False,
    ),
)
PYTHON_TIER_BY_NAME = {tier.name: tier for tier in PYTHON_TIERS}

# fragment key -> where the renderer inserts it (docs/writing-scenarios.md#fragments)
FRAGMENT_KEYS = {
    "settings": "fields of the org settings object",
    "custom_properties": "settings.custom_properties",
    "teams": "teams",
    "secrets": "org secrets",
    "variables": "org variables",
    "webhooks": "org webhooks",
    "rulesets": "org rulesets",
    "roles": "org roles",
    "repositories": "_repositories",
    "extra": "raw fields of the org object",
}
DIFF_FLAGS = (
    ("update_secrets", "--update-secrets"),
    ("update_webhooks", "--update-webhooks"),
    ("only_secrets", "--only-secrets"),
    ("verbose", "-v"),
)
PLAN_EXPECT = {
    "changes": "expects **changes**",
    "noop": "expects **no change**",
    "validation_error": "expects a **validation error**",
    "error": "expects an **error**",
    "any": "accepts **any outcome** (only the output is checked)",
}
APPLY_EXPECT = {
    "ok": "expects **success**",
    "error": "expects an **error**",
    "validation_error": "expects a **validation error**",
    "any": "accepts **any outcome**",
}
# offline extra commands that load the configuration take --local (scenarios/offline.py NO_LOCAL_COMMANDS)
NO_LOCAL_COMMANDS = ("--version", "list-projects")
PRIORITIES = {"P0": "P0 (pr-fast lane)", "P1": "P1 (nightly-full lane)", "P2": "P2 (when time allows)"}

# Markdown helpers
BACKTICKS_RE = re.compile(r"`+")
FENCE_RUN_RE = re.compile(r"^[ \t]*(`{3,})", re.MULTILINE)
ESCAPE_RE = re.compile(r"([\\`*_\[\]~])")
# a line break before a line opening with an id and a colon (``O-WEB-SIG: ...``): a paragraph of its own
ID_LINE_RE = re.compile(r"(?<=\S)\n(?=[A-Z][A-Za-z0-9]*(?:[-.][A-Za-z0-9]+)+: )")
LIST_ITEM_RE = re.compile(r"^[ ]*(?:[-*+]|\d{1,3}[.)])[ ]+")
# what prose links: URLs, code spans, repository paths (otterdog's or the harness'), pull requests, known bugs
TOKEN_RE = re.compile(
    r"(?P<url>https?://[^\s<>()`]+[^\s<>()`.,;:!?'\"])"
    # code spans may wrap, never across a blank line
    r"|``(?P<code2>(?:[^\n]|\n(?![ \t]*\n))+?)``"
    r"|`(?P<code1>(?:[^`\n]|\n(?![ \t]*\n))+)`"
    r"|(?<![\w/.-])(?P<path>(?:otterdog|src|tests|scenarios|docs|\.github)/[\w./-]*\w)"
    r"(?::(?P<first>\d+)(?:-(?P<last>\d+))?)?"
    r"|(?<![\w&#/])(?P<pr>(?:eclipse-csi/otterdog)?#(?P<number>\d{2,5}))(?![\w-])"
    r"|(?P<kb>\bKB-\d{3}\b)"
)
# an otterdog pull request or issue URL, shown as #<n>
UPSTREAM_ITEM_RE = re.compile(re.escape(UPSTREAM) + r"/(?:pull|issues)/(?P<number>\d+)")
PATH_RE = re.compile(
    r"(?P<path>(?:otterdog|src|tests|scenarios|docs|\.github)/[\w./-]*\w)(?::(?P<first>\d+)(?:-(?P<last>\d+))?)?"
)
KB_RE = re.compile(r"KB-\d{3}")
KB_HEADING_RE = re.compile(r"^###[ ]+(?P<id>KB-\d{3})\b.*$", re.MULTILINE)
H2_RE = re.compile(r"^##[ ]+(?P<title>.+?)[ ]*$", re.MULTILINE)
LINK_RE = re.compile(r"\[(?P<text>[^\]]*)\]\([^)]*\)")
TABLE_SPLIT_RE = re.compile(r"(?<!\\)\|")
# the first cell of a State checks row: one or more check kinds as code spans
KINDS_CELL_RE = re.compile(r"`[a-z0-9_]+`(?:, `[a-z0-9_]+`)*")
# a quoted scenario id in Python code, optionally followed by /<step>
QUOTED_ID_RE = re.compile(r"""["'](?P<id>[A-Za-z0-9][A-Za-z0-9_.-]*)(?:/[A-Za-z0-9_.-]*)?["']""")
SHORT_TITLE_RE = re.compile(r"\s*\([^()]*\)\s*$")


# --- sources -----------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Scenario:
    """One YAML scenario file."""

    path: str
    tier: str
    domain: str
    data: Mapping[str, Any]
    text: str
    step_lines: tuple[tuple[int, int], ...]

    @property
    def id(self) -> str:
        """The scenario id (the file name when the YAML has none)."""
        return str(self.data.get("id") or Path(self.path).stem)

    @property
    def title(self) -> str:
        """One line."""
        return str(self.data.get("title") or self.id)

    @property
    def uri(self) -> str:
        """The generated page, below docs/."""
        return f"{EXPLORER}/{self.tier}/{self.domain}/{Path(self.path).stem}.md"

    @property
    def steps(self) -> list[Mapping[str, Any]]:
        """The steps (a malformed one as an empty mapping)."""
        steps = self.data.get("steps")
        return [step if isinstance(step, Mapping) else {} for step in steps] if isinstance(steps, list) else []

    @property
    def tags(self) -> list[str]:
        """Selection tags."""
        tags = self.data.get("tags")
        return [str(tag) for tag in tags] if isinstance(tags, list) else []

    def step_name(self, index: int) -> str:
        """The name of step ``index`` (0-based): its ``name``, else ``step-<n>``."""
        return str(self.steps[index].get("name") or f"step-{index + 1}")

    def known_bugs(self) -> list[str]:
        """The known bugs of the scenario and of its steps, in order."""
        found = [_kb_id(self.data.get("known_bug"))] + [_kb_id(step.get("known_bug")) for step in self.steps]
        return list(dict.fromkeys(kb for kb in found if kb))


@dataclass(frozen=True)
class PythonTest:
    """One test function (or method) of a module."""

    name: str
    line: int
    end: int
    doc: str
    scenario: str | None
    priority: str | None
    tags: tuple[str, ...]
    known_bugs: tuple[str, ...]
    references: tuple[str, ...]
    marks: tuple[str, ...]
    source: str

    @property
    def heading(self) -> str:
        """Its heading on the module page: ``test_x``, or ``TestClass.test_x`` for a method."""
        return self.name.replace("::", ".")

    @property
    def summary(self) -> str:
        """The first sentence of its docstring."""
        return first_sentence(self.doc)


@dataclass(frozen=True)
class PythonModule:
    """One ``tests/<tier>/test_*.py`` module."""

    path: str
    tier: str
    doc: str
    marks: tuple[str, ...]
    tags: tuple[str, ...]
    tests: tuple[PythonTest, ...]

    @property
    def name(self) -> str:
        """The file name."""
        return Path(self.path).name

    @property
    def uri(self) -> str:
        """The generated page, below docs/."""
        return f"{PYTHON_DIR}/{self.tier}/{Path(self.path).stem}.md"


@dataclass
class Site:
    """Everything the generated pages show or link to."""

    root: Path
    repo_url: str
    slugify: Slugify
    upstream_ref: str = BRANCH
    release: str = ""
    scenarios: list[Scenario] = field(default_factory=list)
    modules: list[PythonModule] = field(default_factory=list)
    known_bugs: dict[str, Mapping[str, Any]] = field(default_factory=dict)
    kb_anchors: dict[str, str] = field(default_factory=dict)
    features: dict[str, list[Mapping[str, Any]]] = field(default_factory=dict)
    area_anchors: dict[str, str] = field(default_factory=dict)
    check_kinds: dict[str, tuple[str, tuple[str, ...]]] = field(default_factory=dict)
    check_values: dict[str, str] = field(default_factory=dict)
    oracle_lines: dict[str, int] = field(default_factory=dict)
    mentions: dict[str, list[tuple[str, int, str]]] = field(default_factory=dict)


def _kb_id(value: Any) -> str | None:
    """The id of a ``known_bug`` value (``KB-nnn`` or ``{id: KB-nnn, phases: [...]}``)."""
    if isinstance(value, Mapping):
        value = value.get("id")
    return str(value) if value else None


def _yaml(text: str) -> Any:
    """Data of a YAML document."""
    import yaml

    return yaml.safe_load(text)


def step_lines(text: str) -> tuple[tuple[int, int], ...]:
    """(first, last) line, 1-based, of every step of a scenario file; trailing blank and comment lines excluded."""
    import yaml

    node = yaml.compose(text, Loader=yaml.SafeLoader)
    if not isinstance(node, yaml.MappingNode):
        return ()
    lines = text.split("\n")
    for key, value in node.value:
        if key.value != "steps" or not isinstance(value, yaml.SequenceNode):
            continue
        spans: list[tuple[int, int]] = []
        for item in value.value:
            first, end = item.start_mark.line, item.end_mark
            # the mapping ends where the next token starts: at the next item's "- " or at the end of the file
            before = lines[end.line][: end.column].strip() if end.line < len(lines) else ""
            last = end.line - 1 if before in ("", "-") else end.line
            while last > first and (not lines[last].strip() or lines[last].lstrip().startswith("#")):
                last -= 1
            spans.append((first + 1, max(first, last) + 1))
        return tuple(spans)
    return ()


def load_scenarios(root: Path) -> list[Scenario]:
    """Every scenario of scenarios/<tier>/<domain>/, ordered by tier, domain and file name."""
    scenarios: list[Scenario] = []
    for tier in TIERS:
        for path in sorted((root / SCENARIOS_DIR / tier.name).glob("*/*.yaml")):
            text = path.read_text(encoding="utf-8")
            data = _yaml(text)
            if not isinstance(data, Mapping):
                log.warning("Scenario file '%s' is not a mapping: no page.", path.relative_to(root))
                continue
            rel = path.relative_to(root).as_posix()
            scenarios.append(Scenario(rel, tier.name, path.parent.name, data, text, step_lines(text)))
    return scenarios


def _mark(expr: ast.expr) -> tuple[str, ast.Call | None] | None:
    """(name, call) of a ``pytest.mark.<name>`` or ``pytest.mark.<name>(...)`` expression."""
    call = expr if isinstance(expr, ast.Call) else None
    target = call.func if call is not None else expr
    if (
        isinstance(target, ast.Attribute)
        and isinstance(target.value, ast.Attribute)
        and target.value.attr == "mark"
        and isinstance(target.value.value, ast.Name)
        and target.value.value.id == "pytest"
    ):
        return target.attr, call
    return None


def _string(node: ast.expr, constants: Mapping[str, str]) -> str | None:
    """A string literal, or a module constant holding one."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return constants.get(node.id)
    return None


@dataclass
class _Marks:
    """The marks of a test, its class and its module, read from the source."""

    scenario: str | None = None
    priority: str | None = None
    tags: list[str] = field(default_factory=list)
    known_bugs: list[str] = field(default_factory=list)
    references: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)

    def add(self, exprs: Iterable[ast.expr], source: str, constants: Mapping[str, str]) -> None:
        """Read the pytest marks among ``exprs``."""
        for expr in exprs:
            found = _mark(expr)
            if found is None:
                continue
            name, call = found
            args = [_string(arg, constants) for arg in call.args] if call is not None else []
            keywords = {keyword.arg: keyword.value for keyword in call.keywords if keyword.arg} if call else {}
            if name == "scenario" and args and args[0]:
                self.scenario = args[0]
                priority = keywords.get("priority")
                self.priority = _string(priority, constants) if priority is not None else self.priority
                self.references += _mark_references(keywords.get("references"))
            elif name == "tags":
                self.tags += [arg for arg in args if arg]
            elif name == "known_bug":
                self.known_bugs += [arg for arg in args if arg]
            else:
                segment = ast.get_source_segment(source, expr) or f"pytest.mark.{name}"
                text = " ".join(segment.removeprefix("pytest.mark.").split())
                self.other.append(text if len(text) <= 120 else text[:117] + "...")


def _mark_references(node: ast.expr | None) -> list[str]:
    """The ``references`` keyword of a scenario mark: ``#<pr>`` or the change slug of each entry."""
    if node is None:
        return []
    try:
        value = ast.literal_eval(node)
    except ValueError:
        return []
    found: list[str] = []
    for entry in value if isinstance(value, list) else []:
        if isinstance(entry, Mapping) and entry.get("pr"):
            found.append(f"#{entry['pr']}")
        elif isinstance(entry, Mapping) and entry.get("change"):
            found.append(str(entry["change"]))
    return found


def _module_marks(tree: ast.Module) -> list[ast.expr]:
    """The expressions of ``pytestmark = ...`` (a mark or a list of marks)."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in node.targets):
            return list(node.value.elts) if isinstance(node.value, ast.List | ast.Tuple) else [node.value]
    return []


def parse_module(source: str, path: str, tier: str) -> PythonModule:
    """The tests of a Python test module: top-level ``test*`` functions and the ``test*`` methods of ``Test*``
    classes, with their marks (the module's ``pytestmark`` and the class decorators included)."""
    tree = ast.parse(source)
    lines = source.split("\n")
    constants = {
        target.id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)
        for target in node.targets
        if isinstance(target, ast.Name)
    }
    module_marks = _Marks()
    module_marks.add(_module_marks(tree), source, constants)

    def test_of(node: ast.FunctionDef | ast.AsyncFunctionDef, name: str, inherited: Sequence[ast.expr]) -> PythonTest:
        marks = _Marks()
        marks.add([*_module_marks(tree), *inherited, *node.decorator_list], source, constants)
        first = min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])
        end = node.end_lineno or node.lineno
        return PythonTest(
            name=name,
            line=first,
            end=end,
            doc=ast.get_docstring(node) or "",
            scenario=marks.scenario,
            priority=marks.priority,
            tags=tuple(dict.fromkeys(marks.tags)),
            known_bugs=tuple(dict.fromkeys(marks.known_bugs)),
            references=tuple(dict.fromkeys(marks.references)),
            marks=tuple(dict.fromkeys(item for item in marks.other if item not in module_marks.other)),
            source=textwrap.dedent("\n".join(lines[first - 1 : end])),
        )

    tests: list[PythonTest] = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name.startswith("test"):
            tests.append(test_of(node, node.name, ()))
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and item.name.startswith("test"):
                    tests.append(test_of(item, f"{node.name}::{item.name}", node.decorator_list))
    return PythonModule(
        path=path,
        tier=tier,
        doc=ast.get_docstring(tree) or "",
        marks=tuple(module_marks.other),
        tags=tuple(dict.fromkeys(module_marks.tags)),
        tests=tuple(tests),
    )


def load_modules(root: Path) -> list[PythonModule]:
    """Every ``tests/<tier>/test_*.py`` module of the Python tiers."""
    modules: list[PythonModule] = []
    for tier in PYTHON_TIERS:
        for path in sorted((root / TESTS_DIR / tier.name).glob("test_*.py")):
            rel = path.relative_to(root).as_posix()
            modules.append(parse_module(path.read_text(encoding="utf-8"), rel, tier.name))
    return modules


def heading_text(markdown: str) -> str:
    """The text of a Markdown heading as the toc extension slugifies it: links as their text, no code or emphasis
    markers."""
    return LINK_RE.sub(lambda match: match["text"], markdown).replace("`", "").replace("**", "").strip()


def kb_anchors(known_issues: str, slugify: Slugify) -> dict[str, str]:
    """KB id -> anchor of its ``### KB-nnn — ...`` section in docs/known-issues.md."""
    return {
        match["id"]: slugify(heading_text(match.group(0).removeprefix("###")), "-")
        for match in KB_HEADING_RE.finditer(known_issues)
    }


def area_anchors(areas: Iterable[Mapping[str, Any]], matrix: str, slugify: Slugify) -> dict[str, str]:
    """Coverage area id -> anchor of its ``## <title>`` section in docs/coverage-matrix.md (areas without one are
    left out)."""
    headings = {heading_text(match["title"]) for match in H2_RE.finditer(matrix)}
    found: dict[str, str] = {}
    for area in areas:
        title = str(area.get("title") or "")
        if area.get("id") and title in headings:
            found[str(area["id"])] = slugify(title, "-")
    return found


def features_by_item(features: Iterable[Mapping[str, Any]]) -> dict[str, list[Mapping[str, Any]]]:
    """``covered_by`` item (a scenario id, or ``<path>::<test>`` without parameters) -> the features it covers."""
    found: dict[str, list[Mapping[str, Any]]] = {}
    for feature in features:
        for item in feature.get("covered_by") or []:
            key = re.sub(r"\[.*\]$", "", str(item))
            if "::" not in key and not key.startswith(f"{TESTS_DIR}/"):
                key = key.split("/", 1)[0]  # a case <scenario id>/<step> counts for its scenario
            found.setdefault(key, []).append(feature)
    return found


def check_kinds(source: str) -> dict[str, tuple[str, tuple[str, ...]]]:
    """``CHECK_KINDS`` of src/otterdog_e2e/scenarios/checks.py: check kind -> (oracle method, parameters)."""
    target: ast.expr
    value: ast.expr | None
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign):
            target, value = node.target, node.value
        elif isinstance(node, ast.Assign) and len(node.targets) == 1:
            target, value = node.targets[0], node.value
        else:
            continue
        if isinstance(target, ast.Name) and target.id == "CHECK_KINDS" and value is not None:
            kinds = ast.literal_eval(value)
            return {str(kind): (str(method), tuple(params)) for kind, (method, params) in kinds.items()}
    return {}


def check_values(writing: str) -> dict[str, str]:
    """Check kind -> what it reads, from the tables of the State checks section of docs/writing-scenarios.md (the
    cell as written, links reduced to their text); a row may name several kinds (`` `a`, `b` ``)."""
    start = writing.find("\n## State checks")
    end = writing.find("\n## ", start + 1)
    found: dict[str, str] = {}
    for line in writing[start:end].split("\n") if start >= 0 else []:
        cells = [cell.strip() for cell in TABLE_SPLIT_RE.split(line.strip())[1:-1]]
        if len(cells) == 3 and KINDS_CELL_RE.fullmatch(cells[0]):
            for kind in re.findall(r"`([^`]+)`", cells[0]):
                found[kind] = LINK_RE.sub(lambda match: match["text"], cells[2])
    return found


def function_lines(source: str) -> dict[str, int]:
    """Function and method name -> line of its ``def`` (the first one of a name)."""
    found: dict[str, int] = {}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.setdefault(node.name, node.lineno)
    return found


def mentions(files: Iterable[tuple[str, str]], ids: set[str]) -> dict[str, list[tuple[str, int, str]]]:
    """Scenario id -> (path, line, stripped line) of every Python line quoting it (``"<id>"`` or ``"<id>/<step>"``)."""
    found: dict[str, list[tuple[str, int, str]]] = {}
    for path, source in files:
        for number, line in enumerate(source.split("\n"), start=1):
            for scenario in dict.fromkeys(match["id"] for match in QUOTED_ID_RE.finditer(line)):
                if scenario in ids:
                    found.setdefault(scenario, []).append((path, number, line.strip()))
    return found


def python_sources(root: Path) -> list[tuple[str, str]]:
    """(path, source) of the Python files that may adjust a scenario: the tier tests and the package."""
    paths = [path for tier in PYTHON_TIERS for path in sorted((root / TESTS_DIR / tier.name).glob("*.py"))]
    paths += sorted((root / "src").rglob("*.py"))
    return [(path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")) for path in paths]


def load_site(root: Path, repo_url: str, slugify: Slugify) -> Site:
    """Read the scenarios, the Python tests and what their pages link to."""
    coverage = _yaml((root / COVERAGE).read_text(encoding="utf-8")) or {}
    upstream = coverage.get("otterdog") or {}
    site = Site(
        root=root,
        repo_url=repo_url.rstrip("/"),
        slugify=slugify,
        upstream_ref=str(upstream.get("ref") or BRANCH),
        release=str(upstream.get("release") or ""),
    )
    site.scenarios = load_scenarios(root)
    site.modules = load_modules(root)
    bugs = _yaml((root / KNOWN_BUGS).read_text(encoding="utf-8")) or []
    site.known_bugs = {str(bug["id"]): bug for bug in bugs if isinstance(bug, Mapping) and bug.get("id")}
    docs = root / "docs"
    site.kb_anchors = kb_anchors((docs / KNOWN_ISSUES).read_text(encoding="utf-8"), slugify)
    site.features = features_by_item(coverage.get("features") or [])
    matrix = (docs / COVERAGE_MATRIX).read_text(encoding="utf-8")
    site.area_anchors = area_anchors(coverage.get("areas") or [], matrix, slugify)
    site.check_kinds = check_kinds((root / CHECKS).read_text(encoding="utf-8"))
    site.check_values = check_values((docs / WRITING).read_text(encoding="utf-8"))
    site.oracle_lines = function_lines((root / ORACLE).read_text(encoding="utf-8"))
    site.mentions = mentions(python_sources(root), {scenario.id for scenario in site.scenarios})
    return site


# --- Markdown ------------------------------------------------------------------------------------------------------------
def code(text: str) -> str:
    """An inline code span showing ``text`` verbatim (line breaks as ``\\n``)."""
    text = text.replace("\n", "\\n")
    if not text:
        return '`""`'
    fence = "`" * (max((len(run) for run in BACKTICKS_RE.findall(text)), default=0) + 1)
    pad = " " if text[0] == "`" or text[-1] == "`" or (text[0] == " " and text[-1] == " ") else ""
    return f"{fence}{pad}{text}{pad}{fence}"


def fenced(text: str, lang: str = "", *, indent: str = "", options: str = "") -> list[str]:
    """A fenced code block (longer fence than any inside), every line prefixed with ``indent``."""
    fence = "`" * max(3, max((len(run) for run in FENCE_RUN_RE.findall(text)), default=0) + 1)
    head = f"{fence}{lang}" + (f" {options}" if options else "")
    body = text.rstrip("\n").split("\n")
    return [f"{indent}{line}" if line else "" for line in (head, *body, fence)]


def escape(text: str) -> str:
    """Plain text as Markdown: HTML special characters as entities, Markdown punctuation escaped."""
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return ESCAPE_RE.sub(r"\\\1", text)


def _plain(text: str, at_line_start: bool) -> str:
    """Escaped prose between tokens; the list markers starting its lines are kept, a leading ``#`` or ``+`` that would
    start a heading or a list is escaped."""
    lines: list[str] = []
    for number, line in enumerate(text.split("\n")):
        if number == 0 and not at_line_start:
            lines.append(escape(line))
            continue
        item = LIST_ITEM_RE.match(line)
        head = item.group(0) if item else line[: len(line) - len(line.lstrip(" "))]
        body = escape(line[len(head) :])
        lines.append(head + ("\\" + body if not item and body.startswith(("#", "+")) else body))
    return "\n".join(lines)


def cell(markdown: str) -> str:
    """Markdown of a table cell: pipes escaped (docs_hooks.py restores the ones inside code spans)."""
    return markdown.replace("\n", " ").replace("|", "\\|")


def flow(value: Any) -> str:
    """A YAML value on one line (flow style); strings as they are."""
    if isinstance(value, str):
        return value
    import yaml

    text = yaml.safe_dump(value, default_flow_style=True, sort_keys=False, allow_unicode=True, width=1_000_000)
    return text.strip().removesuffix("...").strip()


def first_sentence(text: str, limit: int = 180) -> str:
    """The first sentence of the first paragraph of ``text``, on one line, at most ``limit`` characters."""
    paragraph = " ".join(text.strip().split("\n\n")[0].split())
    match = re.search(r"(?<=[.:;])\s+(?=[A-Z(`])", paragraph)
    sentence = paragraph[: match.start()] if match else paragraph
    return sentence if len(sentence) <= limit else sentence[: limit - 3].rstrip() + "..."


def lines_fragment(first: int | None, last: int | None = None) -> str:
    """``#L<first>`` or ``#L<first>-L<last>`` (GitHub line links), empty without lines."""
    if first is None:
        return ""
    return f"#L{first}" + (f"-L{last}" if last is not None and last != first else "")


def is_newer(version: str, release: str) -> bool:
    """Whether otterdog ``version`` (PEP 440) comes after ``release`` (``v1.7.1``); False when either is unreadable."""
    try:
        from packaging.version import InvalidVersion, Version
    except ImportError:  # pragma: no cover - packaging comes with MkDocs and pytest
        return False
    try:
        return Version(version) > Version(release.removeprefix("v"))
    except InvalidVersion:
        return False


class Writer:
    """Markdown of one generated page: links relative to the page, GitHub URLs of the sources, linked prose."""

    def __init__(self, site: Site, uri: str) -> None:
        self.site = site
        self.uri = uri

    # links
    def rel(self, target: str) -> str:
        """A page below docs/, relative to this page."""
        return posixpath.relpath(target, posixpath.dirname(self.uri) or ".")

    @property
    def docs(self) -> str:
        """The way from this page back to docs/ (``../..//`` style, empty for a top-level page)."""
        depth = self.uri.count("/")
        return "../" * depth

    def blob(self, path: str, first: int | None = None, last: int | None = None) -> str:
        """A harness file on GitHub."""
        return f"{self.site.repo_url}/blob/{BRANCH}/{quote(path)}{lines_fragment(first, last)}"

    def upstream(self, path: str, first: int | None = None, last: int | None = None) -> str:
        """An otterdog file on GitHub, at the commit of the coverage matrix."""
        return f"{UPSTREAM}/blob/{self.site.upstream_ref}/{quote(path)}{lines_fragment(first, last)}"

    @staticmethod
    def pull(number: str | int) -> str:
        """An otterdog pull request."""
        return f"{UPSTREAM}/pull/{number}"

    def kb(self, kb_id: str) -> str:
        """A known bug: its section of known-issues.md."""
        anchor = self.site.kb_anchors.get(kb_id)
        return self.rel(KNOWN_ISSUES) + (f"#{anchor}" if anchor else "")

    def kb_link(self, kb_id: str) -> str:
        """``[KB-nnn](...)`` with the bug's title."""
        return f"[{kb_id}]({self.kb(kb_id)})"

    def source_link(self, path: str, first: int | None = None, last: int | None = None) -> str:
        """``[`path:lines`](url)``: otterdog files upstream, harness files on main (docs pages on the site), a path
        that is not in the repository as plain code."""
        label = code(path + (f":{first}" if first else "") + (f"-{last}" if first and last else ""))
        if path.startswith("otterdog/"):
            return f"[{label}]({self.upstream(path, first, last)})"
        if not (self.site.root / path).exists():
            return label
        if path.startswith("docs/") and path.endswith(".md") and "/" not in path.removeprefix("docs/"):
            return f"[{label}]({self.rel(path.removeprefix('docs/'))})"
        return f"[{label}]({self.blob(path, first, last)})"

    # prose
    def token(self, match: re.Match[str]) -> str:
        """Markdown of one TOKEN_RE match."""
        if match["url"]:
            upstream = UPSTREAM_ITEM_RE.fullmatch(match["url"])
            return f"[#{upstream['number']}]({match['url']})" if upstream else f"<{match['url']}>"
        content = match["code2"] if match["code2"] is not None else match["code1"]
        if content is not None:
            content = " ".join(content.split("\n"))
            inner = content.strip()
            path = PATH_RE.fullmatch(inner)
            if path:
                first, last = path["first"], path["last"]
                return self.source_link(path["path"], int(first) if first else None, int(last) if last else None)
            if KB_RE.fullmatch(inner):
                return f"[{code(inner)}]({self.kb(inner)})"
            return code(content)
        if match["path"]:
            first, last = match["first"], match["last"]
            return self.source_link(match["path"], int(first) if first else None, int(last) if last else None)
        if match["pr"]:
            return f"[{escape(match['pr'])}]({self.pull(match['number'])})"
        return self.kb_link(match["kb"])

    def inline(self, text: str) -> str:
        """One line of prose: tokens linked, the rest escaped."""
        out: list[str] = []
        last = 0
        for match in TOKEN_RE.finditer(text):
            out += [escape(text[last : match.start()]), self.token(match)]
            last = match.end()
        out.append(escape(text[last:]))
        return "".join(out)

    def prose(self, text: str) -> str:
        """Free text (a description, a docstring) as Markdown: paragraphs and list items kept, tokens linked (a code
        span may wrap), the rest escaped."""
        text = ID_LINE_RE.sub("\n\n", inspect.cleandoc(text))
        out: list[str] = []
        last = 0
        for match in TOKEN_RE.finditer(text):
            out += [_plain(text[last : match.start()], last == 0 or text[last - 1] == "\n"), self.token(match)]
            last = match.end()
        out.append(_plain(text[last:], last == 0 or text[last - 1] == "\n"))
        return "".join(out).strip("\n")

    def tags(self, tags: Iterable[str], index: str) -> str:
        """Tags as links to the filtered table of ``index``."""
        return " ".join(f"[{code(tag)}]({self.rel(index)}?Tags={quote(tag)})" for tag in tags)


def nav_label(scenario: Scenario, taken: set[str]) -> str:
    """The navigation label of a scenario: its title without a trailing parenthesis, the whole title when the short
    form is taken in its section."""
    short = SHORT_TITLE_RE.sub("", scenario.title) or scenario.title
    label = short if short not in taken else scenario.title
    taken.add(label)
    return label


def scenario_notes(scenario: Scenario, release: str) -> list[str]:
    """Short flags of a scenario for the overview tables."""
    data = scenario.data
    notes: list[str] = []
    if data.get("fixed_in"):
        newer = " (unreleased)" if release and is_newer(str(data["fixed_in"]), release) else ""
        notes.append(f"otterdog ≥ {data['fixed_in']}{newer}")
    notes += scenario.known_bugs()
    if data.get("org_level"):
        notes.append("org-level")
    if data.get("min_plan") and data.get("min_plan") != "free":
        notes.append(f"plan ≥ {data['min_plan']}")
    if data.get("requires"):
        notes.append("needs " + ", ".join(str(cap) for cap in data["requires"]))
    if data.get("observe"):
        notes.append("observed (differential)")
    return notes


# --- scenario pages -----------------------------------------------------------------------------------------------------
def scenario_page(site: Site, scenario: Scenario) -> str:
    """The page of one YAML scenario."""
    w = Writer(site, scenario.uri)
    data = scenario.data
    tier = TIER_BY_NAME[scenario.tier]
    out = [f"# {escape(scenario.title)}", ""]
    out += [
        (
            f"{code(scenario.id)} · [{code(scenario.path)}]({w.blob(scenario.path)}) · "
            f"[{tier.title}]({w.rel(f'{EXPLORER}/{tier.name}/index.md')}) · "
            f"[{code(scenario.domain)}]({w.rel(f'{EXPLORER}/{tier.name}/index.md')}?Domain={quote(scenario.domain)})"
        ),
        "",
    ]
    out += _context_table(w, scenario)
    if data.get("known_bug"):
        out += _known_bug_admonition(w, _kb_id(data["known_bug"]) or "", "every step of this scenario")
    description = str(data.get("description") or "").strip()
    out += ["## What it tests", "", w.prose(description) if description else "*No description.*", ""]
    out += _run_block(w, scenario)
    out += _references(w, data.get("references"))
    out += _known_bugs_section(w, scenario)
    out += _features_section(w, site.features.get(scenario.id, []))
    out += _variables(w, scenario)
    out += _steps(w, scenario)
    out += _code_section(w, scenario)
    return "\n".join(out).rstrip("\n") + "\n"


def _context_table(w: Writer, scenario: Scenario) -> list[str]:
    """The context of a scenario: where it runs, on which SUTs, plans and capabilities."""
    data = scenario.data
    tier = TIER_BY_NAME[scenario.tier]
    rows = [
        ("Tier", f"**{scenario.tier}**: needs {tier.needs}"),
        ("Priority", PRIORITIES.get(str(data.get("priority") or "P1"), str(data.get("priority")))),
        ("Tags", w.tags(scenario.tags, INDEX) or "none"),
        ("Steps", f"{len(scenario.steps)}" + (" independent cases" if scenario.tier == "offline" else ", chained")),
    ]
    if data.get("fixed_in"):
        fixed = str(data["fixed_in"])
        unreleased = f", after the latest release {w.site.release}" if is_newer(fixed, w.site.release) else ""
        rows.append(("otterdog versions", f"≥ {code(fixed)}{unreleased}: older SUTs skip the scenario"))
    if data.get("min_plan"):
        rows.append(("GitHub plan", f"{code(str(data['min_plan']))} or higher, skipped on lower plans"))
    capabilities = f"[capabilities]({w.rel('capability-matrix.md')})"
    if data.get("requires"):
        rows.append(
            ("Requires", " ".join(code(str(c)) for c in data["requires"]) + f": skipped without these {capabilities}")
        )
    if data.get("expect_failure_without"):
        caps = " ".join(code(str(c)) for c in data["expect_failure_without"])
        rows.append(("Negative test", f"without {caps} the steps expect their `on_missing_capability` outcome"))
    if data.get("identities"):
        roles = " ".join(code(str(role)) for role in data["identities"])
        rows.append(("Identities", f"{roles} ([roles]({w.rel('roles.md')})): skipped when one is missing"))
    if data.get("org_level"):
        rows.append(("Organization-level", "yes: unfiltered plans, full baseline reset as cleanup"))
    if data.get("observe"):
        rows.append(("Differential", "observed: outputs recorded on the base and the head SUT and compared"))
    if data.get("timeout"):
        rows.append(("Timeout", f"{data['timeout']} s"))
    if data.get("cleanup") == "none":
        rows.append(("Cleanup", "**none**: objects are kept (debugging only)"))
    out = ["| Context | |", "|---|---|"]
    out += [f"| {name} | {cell(value)} |" for name, value in rows]
    return [*out, ""]


def _known_bug_admonition(w: Writer, kb_id: str, scope: str, phases: Sequence[str] = ()) -> list[str]:
    """A bug admonition: what the known bug is and what it makes expected."""
    bug = w.site.known_bugs.get(kb_id, {})
    title = str(bug.get("title") or "not in scenarios/known_bugs.yaml")
    status = str(bug.get("status") or "unknown")
    fixed = f", fixed in otterdog {bug['fixed_in']}" if bug.get("fixed_in") else ""
    where = f" (phases {', '.join(code(phase) for phase in phases)})" if phases else ""
    return [
        f'!!! bug "Known bug {kb_id}"',
        "",
        (
            f"    {w.kb_link(kb_id)}: {w.inline(title)} ({escape(status)}{escape(fixed)}). The failures of {scope}{where} "
            "are expected while the bug affects the SUT; a SUT without the bug reports an unexpected pass."
        ),
        "",
    ]


def _run_block(w: Writer, scenario: Scenario) -> list[str]:
    """How to run the scenario, and the code that runs it."""
    tier = TIER_BY_NAME[scenario.tier]
    sid = scenario.id
    if scenario.tier == "offline":
        first = scenario.step_name(0) if scenario.steps else "<step>"
        commands = [
            "# every case, on the latest otterdog release",
            f"make one SCENARIO='{sid}'",
            "# one case",
            f"make one SCENARIO='{sid}/{first}'",
            "# against otterdog main",
            f"make one SCENARIO='{sid}' SUT=branch:main",
        ]
    else:
        commands = [
            "# offline lint of every step (validate --local, no GitHub)",
            f"make lint-scenarios ARGS=\"-k '{sid}/'\"",
            "# live, on the latest otterdog release, then on otterdog main",
            f"make one SCENARIO='{sid}' TARGET=<instance>",
            f"make one SCENARIO='{sid}' TARGET=<instance> SUT=branch:main",
        ]
    runner = next((module for module in w.site.modules if module.path == tier.runner), None)
    runner_link = f"[{code(tier.runner)}]({w.rel(runner.uri)})" if runner else w.source_link(tier.runner)
    out = ["## Run it", "", tier.runs.format(docs=w.docs), ""]
    out += fenced("\n".join(commands), "shell")
    out += [
        "",
        (
            f"Collected by {runner_link}, run by {w.source_link(tier.engine)}. "
            f"Artifacts, selection and SUT specs: [Local development]({w.rel('local-development.md')})."
        ),
        "",
    ]
    return out


def _references(w: Writer, references: Any) -> list[str]:
    """The otterdog changes behind the behaviour, with their expected deltas."""
    if not isinstance(references, list) or not references:
        return []
    out = ["## otterdog changes behind it", ""]
    for ref in references:
        if not isinstance(ref, Mapping):
            continue
        if ref.get("pr"):
            name = f"[eclipse-csi/otterdog#{ref['pr']}]({w.pull(ref['pr'])})"
        else:
            name = f"change {code(str(ref.get('change') or '?'))}"
        note = f": {w.inline(' '.join(str(ref['note']).split()))}" if ref.get("note") else ""
        out.append(f"- {name}{note}")
        for key in ("base", "template"):
            if ref.get(key):
                out.append(f"    - {key}: {code(flow(ref[key]))}")
        for delta in ref.get("expected_deltas") or []:
            if isinstance(delta, Mapping):
                where = ", ".join(f"{key} {code(str(delta[key]))}" for key in ("step", "kind", "key") if delta.get(key))
                note = f": {w.inline(str(delta['note']))}" if delta.get("note") else ""
                out.append(f"    - expected delta ({where or 'any'}){note}")
    out += ["", f"See [References]({w.rel(WRITING)}#references) for the expected deltas of a change.", ""]
    return out


def _known_bugs_section(w: Writer, scenario: Scenario) -> list[str]:
    """The known bugs of the scenario, its steps, and the registry entries naming it."""
    bugs = scenario.known_bugs()
    bugs += [
        kb for kb, bug in w.site.known_bugs.items() if scenario.id in (bug.get("scenarios") or []) and kb not in bugs
    ]
    if not bugs:
        return []
    out = ["## Known otterdog bugs", "", "| Bug | Title | Status | Fixed in | Where |", "|---|---|---|---|---|"]
    for kb in bugs:
        bug = w.site.known_bugs.get(kb, {})
        steps = [scenario.step_name(i) for i, step in enumerate(scenario.steps) if _kb_id(step.get("known_bug")) == kb]
        where = "scenario" if _kb_id(scenario.data.get("known_bug")) == kb else ""
        where = where or (", ".join(code(step) for step in steps) if steps else "registry")
        fixed = str(bug.get("fixed_in") or "")
        upstream = f" ({w.inline(str(bug['upstream']))})" if bug.get("upstream") else ""
        out.append(
            f"| {w.kb_link(kb)} | {cell(w.inline(str(bug.get('title') or '')))} | {escape(str(bug.get('status') or ''))} "
            f"| {cell(escape(fixed) + upstream)} | {cell(where)} |"
        )
    return [*out, ""]


def _features_section(w: Writer, features: Sequence[Mapping[str, Any]]) -> list[str]:
    """The coverage-matrix features this test covers, with the otterdog code they point to."""
    if not features:
        return []
    out = [
        "## Features covered",
        "",
        (
            f"Features of the [coverage matrix]({w.rel(COVERAGE_MATRIX)}) listing this test in `covered_by`, with the "
            f"otterdog sources they were inventoried from (at {code(w.site.upstream_ref[:7])})."
        ),
        "",
    ]
    for feature in features:
        area = str(feature.get("area") or "")
        anchor = w.site.area_anchors.get(area)
        area_link = f"[{escape(area)}]({w.rel(COVERAGE_MATRIX)}#{anchor})" if anchor else escape(area)
        status = str(feature.get("status") or "")
        out.append(
            f"- **{code(str(feature.get('id')))}** ({escape(status)}, {escape(str(feature.get('priority') or ''))}, "
            f"area {area_link}): {w.inline(str(feature.get('title') or ''))}"
        )
        sources = [w.inline(str(source)) for source in feature.get("source") or []]
        if sources:
            out.append(f"    - otterdog: {', '.join(sources)}")
    return [*out, ""]


def _variables(w: Writer, scenario: Scenario) -> list[str]:
    """Scenario variables and inlined jsonnet libraries."""
    out: list[str] = []
    variables = scenario.data.get("variables")
    if isinstance(variables, Mapping) and variables:
        out += ["## Variables", "", "| Variable | Value |", "|---|---|"]
        out += [f"| {code(str(name))} | {cell(code(flow(value)))} |" for name, value in variables.items()]
        out += ["", f"Jinja variables of every string ([Template variables]({w.rel(WRITING)}#template-variables)).", ""]
    libraries = scenario.data.get("libraries")
    if isinstance(libraries, Mapping) and libraries:
        out += ["## Libraries", "", "Inlined as `local <name> = (<file>);` in every rendered configuration.", ""]
        for name, ref in libraries.items():
            out += _file_entry(w, scenario, ref, f"local {name}")
    return out


def _resolve(scenario: Scenario, ref: Any) -> tuple[str | None, Mapping[str, Any]]:
    """The repository path of a ``{file, raw, vars}`` reference (or a bare path), relative to the scenario file."""
    spec: Mapping[str, Any] = ref if isinstance(ref, Mapping) else {"file": ref}
    file = spec.get("file")
    if not isinstance(file, str):
        return None, spec
    return posixpath.normpath(posixpath.join(posixpath.dirname(scenario.path), file)), spec


def _file_entry(w: Writer, scenario: Scenario, ref: Any, label: str) -> list[str]:
    """A jsonnet file a scenario inlines: its link, options and content (collapsible)."""
    path, spec = _resolve(scenario, ref)
    if path is None:
        return [f"- {escape(label)}: {code(flow(ref))}", ""]
    options = []
    if spec.get("raw"):
        options.append("inserted as written (`raw`)")
    if spec.get("vars"):
        options.append(f"vars {code(flow(spec['vars']))}")
    out = [f"{escape(label)}: {w.source_link(path)}" + (f" ({', '.join(options)})" if options else ""), ""]
    target = w.site.root / path
    if target.is_file():
        out += [f'??? abstract "{path}"', ""]
        out += fenced(target.read_text(encoding="utf-8"), "jsonnet", indent="    ")
        out.append("")
    return out


def _fragments_block(w: Writer, scenario: Scenario, fragments: Any, files: list[str]) -> list[str]:
    """The jsonnet of a fragments mapping, as one code block (each key introduced by a comment); file entries are
    inlined there and listed in ``files``."""
    if not isinstance(fragments, Mapping) or not fragments:
        return []
    lines: list[str] = []
    for key, value in fragments.items():
        lines.append(f"// {key} -> {FRAGMENT_KEYS.get(str(key), str(key))}")
        for entry in value if isinstance(value, list) else [value]:
            if isinstance(entry, str):
                lines.append(entry.rstrip() + ",")
                continue
            path, spec = _resolve(scenario, entry)
            if path is None:
                lines.append(f"// {flow(entry)}")
                continue
            files.append(path)
            vars_ = f", vars {flow(spec['vars'])}" if spec.get("vars") else ""
            lines.append(f"// file {path}{vars_}")
            target = w.site.root / path
            lines.append(target.read_text(encoding="utf-8").rstrip() + "," if target.is_file() else "// (missing)")
    return fenced("\n".join(lines), "jsonnet")


def _steps(w: Writer, scenario: Scenario) -> list[str]:
    """Every step: its configuration, the commands it runs and what it expects."""
    out = ["## Steps", ""]
    if scenario.tier == "offline":
        out.append(
            "Each step is an independent case with a fresh workspace (pytest item `<id>/<step>`), nothing is applied."
        )
    else:
        out.append(
            "Steps run in order on the target organization; the configuration of a step is the baseline plus **its own** "
            "fragments only, so an object a step does not repeat is removed (and deleted by a step applying with `-d`)."
        )
    out += [
        "",
        (
            f"In strings, `{{{{ p }}}}` is the run prefix (`e2e-<run>`, offline `e2e-spduo000`), `{{{{ P }}}}` its upper-case "
            f"form, `{{{{ hook_base }}}}` the run's webhook URL base ([Template variables]({w.rel(WRITING)}#template-variables))."
        ),
        "",
    ]
    for index, step in enumerate(scenario.steps):
        out += _step(w, scenario, index, step)
    return out


def _step(w: Writer, scenario: Scenario, index: int, step: Mapping[str, Any]) -> list[str]:
    """One step."""
    name = scenario.step_name(index)
    out = [f"### {index + 1}. {escape(name)}", ""]
    if index < len(scenario.step_lines):
        first, last = scenario.step_lines[index]
        source = f"[lines {first}-{last}]({w.blob(scenario.path, first, last)})"
        case = f" · case {code(f'{scenario.id}/{name}')}" if scenario.tier == "offline" else ""
        out += [f"Source: {source}{case}", ""]
    known = step.get("known_bug")
    if known:
        phases = known.get("phases") if isinstance(known, Mapping) else None
        out += _known_bug_admonition(w, _kb_id(known) or "", "this step", [str(p) for p in phases or []])
    out += _configuration(w, scenario, step)
    out += _offline_phases(w, step) if scenario.tier == "offline" else _live_phases(w, scenario, step)
    alternative = step.get("on_missing_capability")
    if isinstance(alternative, Mapping) and alternative:
        missing = [str(cap) for cap in scenario.data.get("expect_failure_without") or []]
        caps = ", ".join(code(cap) for cap in missing) or "an expected capability"
        out += [f'!!! note "Without {escape(", ".join(missing))}"', ""]
        out += [f"    When {caps} is missing, the step expects instead:", ""]
        out += ["    " + line if line else "" for line in _live_phases(w, scenario, missing_capability_step(step))]
    return out


def missing_capability_step(step: Mapping[str, Any]) -> dict[str, Any]:
    """The step as it runs when an ``expect_failure_without`` capability is missing: ``validate``, ``plan`` and
    ``apply`` of ``on_missing_capability`` merged over the step's, ``state`` and ``converge`` replaced."""
    alternative = step.get("on_missing_capability") or {}
    merged = dict(step)
    for key, value in alternative.items():
        current = step.get(key)
        if key in ("validate", "plan", "apply") and isinstance(current, Mapping) and isinstance(value, Mapping):
            merged[key] = {**current, **value}
        else:
            merged[key] = value
    return merged


def _configuration(w: Writer, scenario: Scenario, step: Mapping[str, Any]) -> list[str]:
    """What the step writes: fragments, overlay, BASE configuration, complete configurations, workspace."""
    out: list[str] = []
    files: list[str] = []
    if step.get("config"):
        out += ["**Configuration**: a complete organization configuration, written as it is:", ""]
        out += _file_entry(w, scenario, step["config"], "config")
    elif step.get("fragments"):
        base = "the minimal organization `e2e-offline`" if scenario.tier == "offline" else "the organization's baseline"
        out += [f"**Configuration**: {base} plus:", ""]
        out += [*_fragments_block(w, scenario, step["fragments"], files), ""]
    else:
        base = "the minimal organization `e2e-offline`" if scenario.tier == "offline" else "the organization's baseline"
        out += [f"**Configuration**: {base}, without fragment.", ""]
    overlay = step.get("overlay")
    if overlay:
        out += ["**Overlay** (object mixin applied after both layers):", ""]
        for entry in overlay if isinstance(overlay, list) else [overlay]:
            out += (
                [*fenced(entry, "jsonnet"), ""]
                if isinstance(entry, str)
                else _file_entry(w, scenario, entry, "overlay")
            )
    if step.get("base_config"):
        out += ["**BASE configuration** (`-BASE`, the current state `local-plan` compares with), from a file:", ""]
        out += _file_entry(w, scenario, step["base_config"], "base_config")
    elif "base_fragments" in step and step["base_fragments"] is not None:
        if step["base_fragments"]:
            out += [
                "**BASE configuration** (`-BASE`, the current state `local-plan` compares with): `e2e-offline` plus:",
                "",
            ]
            out += [*_fragments_block(w, scenario, step["base_fragments"], files), ""]
        else:
            out += [
                "**BASE configuration** (`-BASE`, the current state `local-plan` compares with): the bare organization.",
                "",
            ]
    if files:
        out += ["Files: " + ", ".join(w.source_link(path) for path in dict.fromkeys(files)), ""]
    if step.get("workspace"):
        out += [f"**Workspace** ([variant]({w.rel(WRITING)}#workspace-variants-offline)):", ""]
        out += [*fenced(_dump(step["workspace"]), "yaml"), ""]
    return out


def _dump(value: Any) -> str:
    """A YAML value in block style."""
    import yaml

    return str(yaml.safe_dump(value, sort_keys=False, allow_unicode=True, width=120))


def _output_checks(spec: Mapping[str, Any]) -> list[str]:
    """``contains`` and ``not_contains`` as list items."""
    items = [f"- output contains {code(str(text))}" for text in spec.get("contains") or []]
    items += [f"- output does not contain {code(str(text))}" for text in spec.get("not_contains") or []]
    return items


def _exit_code(spec: Mapping[str, Any]) -> str:
    """The exit code expectation of a spec, if any."""
    if "exit_code" not in spec:
        return ""
    return "; any exit code" if spec["exit_code"] is None else f"; exit code {spec['exit_code']}"


def _diff_flags(spec: Mapping[str, Any]) -> str:
    """The command-line flags of a plan or apply spec (repo filter aside)."""
    flags = [flag for key, flag in DIFF_FLAGS if spec.get(key)]
    if spec.get("update_filter"):
        flags.append(f"--update-filter '{spec['update_filter']}'")
    return "".join(f" {flag}" for flag in flags)


def _validate_line(spec: Mapping[str, Any], *, local: bool) -> list[str]:
    """The validate phase."""
    command = "otterdog validate" + (" --local" if local else "") + (" -v" if spec.get("verbose") else "")
    ok, errors = spec.get("ok"), spec.get("errors")
    if ok is False or (ok is None and errors not in (None, 0)):
        expects = "expects validation to **fail**"
        if errors not in (None, 0):
            expects += f" with exactly {errors} error(s)"
    else:
        expects = "expects validation to **pass** (no error)"
    if spec.get("warnings_min"):
        expects += f", at least {spec['warnings_min']} warning(s)"
    if spec.get("infos") is not None:
        expects += f", exactly {spec['infos']} Info message(s)"
    if spec.get("infos_min"):
        expects += f", at least {spec['infos_min']} Info message(s)"
    return [f"**validate** · {code(command)}: {expects}{_exit_code(spec)}.", "", *_output_checks(spec), ""]


def _plan_line(spec: Mapping[str, Any], command: str) -> list[str]:
    """A plan or local-plan phase."""
    expect = str(spec.get("expect") or "changes")
    text = PLAN_EXPECT.get(expect, f"expects {code(expect)}")
    counts = spec.get("counts")
    if isinstance(counts, Mapping) and counts:
        text += ", plan summary " + ", ".join(f"{value} to {key}" for key, value in counts.items())
    return [f"**plan** · {code(command)}: {text}{_exit_code(spec)}.", "", *_output_checks(spec), ""]


def _offline_phases(w: Writer, step: Mapping[str, Any]) -> list[str]:
    """The phases of an offline case."""
    out: list[str] = []
    validate = step.get("validate")
    if isinstance(validate, Mapping):
        out += _validate_line(validate, local=True)
    else:
        out += ["**validate** · `otterdog validate --local`: runs, its outcome is not checked.", ""]
    plan: Mapping[str, Any] = step["plan"] if isinstance(step.get("plan"), Mapping) else {}
    has_base = bool(step.get("base_config")) or ("base_fragments" in step and step["base_fragments"] is not None)
    if has_base and step.get("plan", {}) is not None:
        flags = (f" -r '{plan['repo_filter']}'" if plan.get("repo_filter") else "") + _diff_flags(plan)
        out += _plan_line(plan, f"otterdog local-plan --local{flags}")
    commands: Mapping[str, Any] = step["commands"] if isinstance(step.get("commands"), Mapping) else {}
    show = commands.get("show")
    if isinstance(show, Mapping):
        out += [f"**show** · `otterdog show --local`: expects exit code {show.get('exit_code', 0)}.", ""]
        out += [*_output_checks(show), ""] if _output_checks(show) else []
    else:
        invalid = isinstance(validate, Mapping) and (
            validate.get("ok") is False or (validate.get("ok") is None and validate.get("errors") not in (None, 0))
        )
        invalid = invalid or plan.get("expect") == "validation_error"
        expects = "may fail (validation is expected to fail)" if invalid else "must exit 0"
        out += [f"**show** · `otterdog show --local`: {expects}.", ""]
    for name, spec in commands.items():
        if name == "show" or not isinstance(spec, Mapping):
            continue
        command = f"otterdog {name}" + ("" if name in NO_LOCAL_COMMANDS else " --local")
        exit_code = spec.get("exit_code", 0)
        expects = "any exit code" if exit_code is None else f"exit code {exit_code}"
        out += [f"**{escape(str(name))}** · {code(command)}: expects {expects}.", "", *_output_checks(spec), ""]
    return out


def _live_phases(w: Writer, scenario: Scenario, step: Mapping[str, Any]) -> list[str]:
    """The phases of a live step: validate, plan, apply, state, converge."""
    out: list[str] = []
    validate = step.get("validate")
    if isinstance(validate, Mapping):
        out += _validate_line(validate, local=False)
    org_level = bool(scenario.data.get("org_level"))
    plan = step.get("plan", {})
    applied = False
    if plan is None:
        out += ["**plan** · skipped (`plan: null`): no plan, apply or converge.", ""]
    else:
        plan = plan if isinstance(plan, Mapping) else {}
        plan_filter = plan.get("repo_filter") or (None if org_level else "{{ p }}-*")
        plan_flags = (f" -r '{plan_filter}'" if plan_filter else "") + _diff_flags(plan)
        out += _plan_line(plan, f"otterdog plan -n{plan_flags}")
        apply = step.get("apply", {})
        if str(plan.get("expect") or "changes") != "changes" or apply is None:
            reason = "`apply: null`" if apply is None else "the plan expects no changes"
            out += [f"**apply** · not run ({reason}).", ""]
        else:
            apply = apply if isinstance(apply, Mapping) else {}
            apply_filter = apply.get("repo_filter") or plan_filter
            flags = (" -d" if apply.get("delete") else "") + (f" -r '{apply_filter}'" if apply_filter else "")
            command = f"otterdog apply -f -n{flags}{_diff_flags(apply)}"
            expect = str(apply.get("expect") or "ok")
            deletes = " Removals are applied (`-d`)." if apply.get("delete") else ""
            text = APPLY_EXPECT.get(expect, f"expects {code(expect)}")
            out += [f"**apply** · {code(command)}: {text}.{deletes}", "", *_output_checks(apply), ""]
            applied = True
    out += _state(w, step.get("state"))
    if applied:
        if step.get("converge", True):
            out += [
                "**converge** · plans again (the apply's filter, no update flag) until this run's objects are a no-op.",
                "",
            ]
        else:
            out += ["**converge** · skipped (`converge: false`).", ""]
    return out


def _state(w: Writer, checks: Any) -> list[str]:
    """The GitHub state checks of a step, as a table."""
    if not isinstance(checks, list) or not checks:
        return []
    out = [
        (
            f"**state** · GitHub, read by the independent oracle and retried up to 60 s "
            f"([State checks]({w.rel(WRITING)}#state-checks)):"
        ),
        "",
        "| Check | Of | Expects | Reads |",
        "|---|---|---|---|",
    ]
    for check in checks:
        if not isinstance(check, Mapping):
            continue
        kind = str(check.get("kind") or "?")
        method, params = w.site.check_kinds.get(kind, ("", ()))
        line = w.site.oracle_lines.get(method)
        kind_md = f"[{code(kind)}]({w.blob(ORACLE, line)})" if line else code(kind)
        of = ", ".join(f"{param} {code(str(check.get(param)))}" for param in params if param in check)
        expects = []
        for form in ("match", "equals", "contains"):
            if form in check:
                expects.append(f"{form} {code(flow(check[form]))}")
        if "absent" in check:
            expects.append("**absent**" if check["absent"] else "present")
        if "unavailable" in check:
            expects.append("**unavailable** (the endpoint refuses)" if check["unavailable"] else "available")
        if check.get("timeout"):
            expects.append(f"within {check['timeout']} s")
        if check.get("unavailable_ok"):
            expects.append("an unavailable endpoint passes")
        reads = w.site.check_values.get(kind, "")
        out.append(f"| {kind_md} | {cell(of or '-')} | {cell('; '.join(expects))} | {cell(reads)} |")
    return [*out, ""]


def _code_section(w: Writer, scenario: Scenario) -> list[str]:
    """The Python code that refers to the scenario and the YAML source."""
    out = ["## Code", ""]
    found = w.site.mentions.get(scenario.id, [])
    if found:
        out += [
            "Python code that refers to this scenario (SUT-dependent expectations, extra checks, fixtures):",
            "",
        ]
        for path, number, text in found:
            short = text if len(text) <= 110 else text[:107] + "..."
            out.append(f"- [{code(f'{path}:{number}')}]({w.blob(path, number)}): {code(short)}")
        out.append("")
    out += [f'??? example "{scenario.path}"', ""]
    out += fenced(scenario.text, "yaml", indent="    ", options='linenums="1"')
    return [*out, ""]


# --- overview pages ------------------------------------------------------------------------------------------------------
FILTER_MARKER = '<div class="e2e-filter" data-columns="{columns}"></div>'
# front matter of the overview pages: their tables get the width of the table of contents
WIDE = ["---", "hide:", "  - toc", "---", ""]


def scenario_table(w: Writer, scenarios: Sequence[Scenario], *, with_tier: bool = True) -> list[str]:
    """A filterable table of scenarios."""
    columns = ["Tier", "Domain", "Priority", "Tags"] if with_tier else ["Domain", "Priority", "Tags"]
    head = ["Scenario", *(["Tier"] if with_tier else []), "Domain", "Priority", "Tags", "Steps", "Notes"]
    out = [FILTER_MARKER.format(columns=",".join(columns)), ""]
    out += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for scenario in scenarios:
        row = [
            f"[{escape(scenario.title)}]({w.rel(scenario.uri)})<br>{code(scenario.id)}",
            *([scenario.tier] if with_tier else []),
            scenario.domain,
            str(scenario.data.get("priority") or "P1"),
            ", ".join(scenario.tags),
            str(len(scenario.steps)),
            ", ".join(scenario_notes(scenario, w.site.release)),
        ]
        out.append("| " + " | ".join(cell(value) for value in row) + " |")
    return [*out, ""]


def explorer_index(site: Site) -> str:
    """The overview page: what the explorer shows, the tiers and every YAML scenario."""
    w = Writer(site, INDEX)
    steps = sum(len(scenario.steps) for scenario in site.scenarios)
    tests = sum(len(module.tests) for module in site.modules)
    out = [
        *WIDE,
        "# Scenario explorer",
        "",
        (
            f"Every test of the harness, one page each: **{len(site.scenarios)} YAML scenarios** ({steps} steps) and "
            f"**{tests} Python tests** in {len(site.modules)} modules. The pages are generated from the sources of "
            f"`{BRANCH}` when the site is built ({w.source_link('docs_scenarios.py')}), so they always match the code."
        ),
        "",
        "A scenario page shows:",
        "",
        (
            "- **what it tests** and its **context**: tier and what it needs, otterdog versions (`fixed_in`), GitHub plan, "
            "capabilities, the otterdog pull requests behind the behaviour, known otterdog bugs and the features of the "
            f"[coverage matrix]({w.rel(COVERAGE_MATRIX)}) it covers, with links to their otterdog sources;"
        ),
        (
            "- **every step**: the jsonnet it adds to the configuration, the otterdog commands it runs, what it expects of "
            "their outputs and of the GitHub state;"
        ),
        (
            "- **the code**: the Python code that adjusts it, its runner and engine, and its YAML source (the pencil button "
            "edits it on GitHub);"
        ),
        "- **how to run it** with `make one`.",
        "",
        (
            f"The [scenario catalog]({w.rel('scenario-catalog.md')}) gives the status and the history of each entry, "
            f"[Writing scenarios]({w.rel(WRITING)}) the format."
        ),
        "",
        "## Tiers",
        "",
        "| Tier | Scenarios | Steps | Needs |",
        "|---|---|---|---|",
    ]
    for tier in TIERS:
        selected = [scenario for scenario in site.scenarios if scenario.tier == tier.name]
        if selected:
            count = sum(len(scenario.steps) for scenario in selected)
            link = f"[{tier.title}]({w.rel(f'{EXPLORER}/{tier.name}/index.md')})"
            out.append(f"| {link} | {len(selected)} | {count} | {cell(tier.needs)} |")
    out.append(f"| [Python tests]({w.rel(PYTHON_INDEX)}) | {tests} tests | | per tier |")
    out += [
        "",
        "## All scenarios",
        "",
        (
            "Type to filter (every word must match: id, title, tag, bug, version...), pick values in the lists, click a "
            "column header to sort."
        ),
        "",
    ]
    out += scenario_table(w, site.scenarios)
    return "\n".join(out)


def tier_index(site: Site, tier: Tier) -> str:
    """The overview page of one YAML tier."""
    uri = f"{EXPLORER}/{tier.name}/index.md"
    w = Writer(site, uri)
    selected = [scenario for scenario in site.scenarios if scenario.tier == tier.name]
    runner = next((module for module in site.modules if module.path == tier.runner), None)
    runner_link = f"[{code(tier.runner)}]({w.rel(runner.uri)})" if runner else w.source_link(tier.runner)
    out = [
        *WIDE,
        f"# {tier.title}",
        "",
        (
            f"{len(selected)} scenarios of [{code(f'scenarios/{tier.name}/')}]({site.repo_url}/tree/{BRANCH}/scenarios/"
            f"{tier.name}), collected by {runner_link}, run by {w.source_link(tier.engine)}. Needs {tier.needs}."
        ),
        "",
        tier.runs.format(docs=w.docs),
        "",
        "| Domain | Scenarios | Steps |",
        "|---|---|---|",
    ]
    for domain in sorted({scenario.domain for scenario in selected}):
        in_domain = [scenario for scenario in selected if scenario.domain == domain]
        steps = sum(len(scenario.steps) for scenario in in_domain)
        out.append(f"| [{code(domain)}](?Domain={quote(domain)}) | {len(in_domain)} | {steps} |")
    out += ["", "## Scenarios", ""]
    out += scenario_table(w, selected, with_tier=False)
    return "\n".join(out)


# --- Python test pages ----------------------------------------------------------------------------------------------------
def module_page(site: Site, module: PythonModule) -> str:
    """The page of one Python test module."""
    w = Writer(site, module.uri)
    tier = PYTHON_TIER_BY_NAME[module.tier]
    out = [
        f"# {escape(module.name)}",
        "",
        (
            f"[{code(module.path)}]({w.blob(module.path)}) · [{tier.title} tests]({w.rel(PYTHON_INDEX)}?Tier="
            f"{quote(tier.name)}) · {len(module.tests)} tests · needs {tier.needs}"
        ),
        "",
    ]
    yaml_tier = next((t for t in TIERS if t.runner == module.path), None)
    if yaml_tier is not None:
        out += [
            f'!!! info "Runs the YAML scenarios of {code(f"scenarios/{yaml_tier.name}/")}"',
            "",
            f"    See [{yaml_tier.title}]({w.rel(f'{EXPLORER}/{yaml_tier.name}/index.md')}).",
            "",
        ]
    if module.marks or module.tags:
        marks = ([f"tags({', '.join(module.tags)})"] if module.tags else []) + list(module.marks)
        out += ["Module marks: " + ", ".join(code(mark) for mark in marks), ""]
    if module.doc:
        out += [w.prose(module.doc), ""]
    stem = Path(module.path).stem
    out += fenced(f'# every test of this module\n{tier.make} ARGS="-k {stem}"', "shell")
    out += ["", "## Tests", ""]
    for test in module.tests:
        out += _python_test(w, module, test, tier)
    return "\n".join(out)


def _python_test(w: Writer, module: PythonModule, test: PythonTest, tier: PythonTier) -> list[str]:
    """One test of a module page."""
    out = [f"### {escape(test.heading)}", ""]
    facts = [f"[line {test.line}]({w.blob(module.path, test.line, test.end)})"]
    if test.scenario:
        facts.append(f"scenario {code(test.scenario)}")
    if test.priority:
        facts.append(escape(test.priority))
    if test.tags:
        facts.append("tags " + w.tags(test.tags, PYTHON_INDEX))
    facts += [w.kb_link(kb) for kb in test.known_bugs]
    facts += [w.inline(ref) for ref in test.references]
    out += [" · ".join(facts), ""]
    if test.marks:
        out += ["Marks: " + ", ".join(code(mark) for mark in test.marks), ""]
    if test.doc:
        out += [w.prose(test.doc), ""]
    features = w.site.features.get(f"{module.path}::{test.name}", []) + (
        w.site.features.get(test.scenario, []) if test.scenario else []
    )
    if features:
        unique = list({str(feature.get("id")): feature for feature in features}.values())
        anchors = w.site.area_anchors
        items = [
            f"[{code(str(f.get('id')))}]({w.rel(COVERAGE_MATRIX)}#{anchors[str(f.get('area'))]})"
            if str(f.get("area")) in anchors
            else code(str(f.get("id")))
            for f in unique
        ]
        out += ["Covers: " + ", ".join(items), ""]
    if test.scenario:
        target = "" if not tier.live else " TARGET=<instance>"
        command = f"make one SCENARIO='{test.scenario}'{target}"
    else:
        command = f"{tier.make} ARGS=\"-k '{test.name.split('::')[-1]}'\""
    out += fenced(command, "shell")
    out += ["", '??? example "Source"', ""]
    out += fenced(test.source, "python", indent="    ", options=f'linenums="{test.line}"')
    return [*out, ""]


def python_index(site: Site) -> str:
    """The overview page of the Python tests."""
    w = Writer(site, PYTHON_INDEX)
    out = [
        *WIDE,
        "# Python tests",
        "",
        (
            "The tests written in Python (the tiers YAML cannot express: CLI behaviour, the webapp, webhooks, the web UI, "
            "differential runs), one page per module with the docstring, marks and source of every test. "
            f"See [Python tests]({w.rel(WRITING)}#python-tests) for how they are written."
        ),
        "",
        "| Tier | Modules | Tests | Needs |",
        "|---|---|---|---|",
    ]
    for tier in PYTHON_TIERS:
        modules = [module for module in site.modules if module.tier == tier.name]
        if modules:
            tests = sum(len(module.tests) for module in modules)
            out.append(f"| [{tier.title}](?Tier={quote(tier.name)}) | {len(modules)} | {tests} | {cell(tier.needs)} |")
    out += ["", "## All tests", ""]
    head = ["Test", "Tier", "Module", "Scenario", "Priority", "Tags", "Summary"]
    out += [FILTER_MARKER.format(columns="Tier,Module,Priority,Tags"), ""]
    out += ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for module in site.modules:
        for test in module.tests:
            anchor = site.slugify(test.heading, "-")
            row = [
                f"[{escape(test.heading)}]({w.rel(module.uri)}#{anchor})",
                module.tier,
                module.name,
                code(test.scenario) if test.scenario else "",
                test.priority or "",
                ", ".join(dict.fromkeys([*module.tags, *test.tags])),
                w.inline(test.summary),
            ]
            out.append("| " + " | ".join(cell(value) for value in row) + " |")
    return "\n".join([*out, ""])


# --- site --------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Generated:
    """A generated page: its Markdown and the repository file its edit button opens."""

    markdown: str
    source: str


def pages(site: Site) -> dict[str, Generated]:
    """Every generated page, by its path below docs/."""
    found = {INDEX: Generated(explorer_index(site), "docs_scenarios.py")}
    for tier in TIERS:
        if any(scenario.tier == tier.name for scenario in site.scenarios):
            found[f"{EXPLORER}/{tier.name}/index.md"] = Generated(tier_index(site, tier), "docs_scenarios.py")
    for scenario in site.scenarios:
        found[scenario.uri] = Generated(scenario_page(site, scenario), scenario.path)
    found[PYTHON_INDEX] = Generated(python_index(site), "docs_scenarios.py")
    for module in site.modules:
        found[module.uri] = Generated(module_page(site, module), module.path)
    return found


def nav(site: Site) -> list[Any]:
    """The entries of the explorer section: overview, YAML tiers (by domain), Python tests (by tier)."""
    entries: list[Any] = [INDEX]
    for tier in TIERS:
        selected = [scenario for scenario in site.scenarios if scenario.tier == tier.name]
        if not selected:
            continue
        domains: list[Any] = [f"{EXPLORER}/{tier.name}/index.md"]
        for domain in sorted({scenario.domain for scenario in selected}):
            taken: set[str] = set()
            in_domain = [scenario for scenario in selected if scenario.domain == domain]
            domains.append({domain: [{nav_label(scenario, taken): scenario.uri} for scenario in in_domain]})
        entries.append({tier.title: domains})
    python: list[Any] = [PYTHON_INDEX]
    for python_tier in PYTHON_TIERS:
        modules = [module for module in site.modules if module.tier == python_tier.name]
        if modules:
            python.append({python_tier.title: [{module.name: module.uri} for module in modules]})
    entries.append({"Python tests": python})
    return entries


def expand_nav(entries: list[Any], section: list[Any]) -> bool:
    """Replace the nav entry of INDEX (``title: scenarios/index.md``) by a section of that title; True when found."""
    for position, entry in enumerate(entries):
        if isinstance(entry, Mapping) and len(entry) == 1:
            title, value = next(iter(entry.items()))
            if value == INDEX:
                entries[position] = {title: section}
                return True
            if isinstance(value, list) and expand_nav(value, section):
                return True
    return False


# --- MkDocs hooks ------------------------------------------------------------------------------------------------------
_GENERATED: dict[str, Generated] = {}


def on_config(config: MkDocsConfig) -> MkDocsConfig:
    """Read the sources, generate the pages and put the explorer section in the navigation."""
    from markdown.extensions.toc import slugify as default_slugify
    from mkdocs.exceptions import PluginError

    slugify = config.mdx_configs.get("toc", {}).get("slugify", default_slugify)
    root = Path(config.docs_dir).parent
    site = load_site(root, config.repo_url or "", slugify)
    _GENERATED.clear()
    _GENERATED.update(pages(site))
    if not isinstance(config.nav, list) or not expand_nav(config.nav, nav(site)):
        raise PluginError(f"mkdocs.yml: the nav must hold an entry '<title>: {INDEX}' (the scenario explorer)")
    return config


def on_files(files: Files, *, config: MkDocsConfig) -> Files:
    """Add the generated pages."""
    from mkdocs.exceptions import PluginError
    from mkdocs.structure.files import File

    for uri, page in _GENERATED.items():
        if files.get_file_from_path(uri) is not None:
            raise PluginError(f"docs/{uri} must not exist: the scenario explorer generates it")
        files.append(File.generated(config, uri, content=page.markdown))
    return files


def on_pre_page(page: Page, *, config: MkDocsConfig, files: Files) -> Page:
    """The edit button of a generated page opens its source (the scenario, the test module, this file)."""
    generated = _GENERATED.get(page.file.src_uri)
    if generated is not None and config.repo_url:
        page.edit_url = f"{config.repo_url.rstrip('/')}/edit/{BRANCH}/{generated.source}"
    return page
