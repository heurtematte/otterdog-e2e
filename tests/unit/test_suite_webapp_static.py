"""Static checks of the webapp and webhooks tiers (SPEC 19 catalogue; tests/webapp, tests/webhooks).

The tier modules are imported by path (like pytest's importlib mode, without collecting them) and inspected without
GitHub, docker or a target:

* the catalogue is complete: every W-* / H-* scenario of SPEC 19 has exactly one test carrying its
  ``scenario(id, priority=...)`` marker and tags from the selection vocabulary (selection.SCENARIO_TAGS);
* gating markers match what a test needs: ``webapp`` on every test of tests/webapp and on any test reaching a webapp
  fixture (directly or through the tier conftest fixtures), never on tests that do not need it (the webapp gate also
  requires the App and, for the compose transport, docker); ``docker`` only on tests requesting docker-only fixtures
  (the webapp gate already requires docker for the compose stack: an extra docker marker would wrongly skip the
  external transport); ``identities(...)`` exactly the non-admin identities a test acts as; ``org_level`` only with
  an org-level cleanup;
* nothing sleeps blindly (no time.sleep / asyncio.sleep in the tiers) and test modules never poll on their own: waits
  go through ConfigRepoFlow's delivery-then-reaction helpers and the classified helpers of the tier conftests;
* expected failures are scoped: every xfail mark of the tiers names the regression exception it tolerates
  (``raises=``), so infra and flow failures are never hidden; no imperative ``pytest.xfail()``;
* the tier conftest helpers behave: config texts, classified waits, minimized comments, regression xfails, call-only
  timeouts.
"""

from __future__ import annotations

import ast
import importlib.util
import inspect
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.config_repo import ConfigPr, ConfigRepoFlow, DeliveryTimeoutError, ReactionTimeoutError
from otterdog_e2e.otterdog.render import OrgConfigRenderer, build_baseline, org_profile
from otterdog_e2e.pytest_plugin import COMPOSE_FIXTURES, FIXTURE_IDENTITIES
from otterdog_e2e.selection import SCENARIO_TAGS
from otterdog_e2e.sut.image import BuiltImage
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import (
    FAKE_MARKER,
    FAKE_ORG,
    FakeOracle,
    RecordingMutator,
    default_org_json,
    fake_sha,
    make_run_context,
    make_target,
)

PROJECT = Path(__file__).resolve().parents[2]
TIER_DIRS = {"webapp": PROJECT / "tests" / "webapp", "webhooks": PROJECT / "tests" / "webhooks"}
CATALOGUE = {  # SPEC 19 (P0 unless noted)
    "W-BOOT": "P0",
    "W-PR-VALID": "P0",
    "W-PR-INVALID": "P0",
    "W-CMD-HELP": "P0",
    "W-CMD-VALIDATE": "P1",
    "W-MERGE-APPLY": "P0",
    "W-AUTOMERGE": "P0",
    "W-DRIFT-CHECKSYNC": "P1",
    "W-REBASE-MULTI": "P1",
    "W-PR-STALE-SNAPSHOT": "P1",
    "W-CMD-CHECK-MERGE": "P2",  # manifest local-check-merge.yaml (local feature branch, skipped elsewhere)
    "W-PR-WEBUI": "P1",  # tests/webapp/test_web_ui_flags.py (docs/web-ui-testing.md: the webapp never uses the UI)
    "H-APP-DELIVERY": "P0",
    "H-ORG-HOOK": "P1",
}
PRIORITIES = ("P0", "P1", "P2")
TIER_PREFIXES = {"webapp": "W-", "webhooks": "H-"}  # scenario ids of the battery's new tests
ORG_LEVEL = frozenset({"H-ORG-HOOK"})
# plugin fixtures needing the webapp under test (the compose-only ones skip with another transport: no docker marker)
WEBAPP_FIXTURES = frozenset(
    {"webapp", "webapp_api", "relay", "config_flow", "webapp_case", "injector", "webapp_otterdog_json", "blueprints"}
    | COMPOSE_FIXTURES
)
DOCKER_FIXTURES = frozenset({"webapp_image"})
ORG_LEVEL_CLEANUPS = frozenset({"org_level_reset", "webapp_case"})
NON_ADMIN_IDENTITIES = frozenset({"author", "approver", "outsider", "config_reader"})
# ConfigRepoFlow methods acting as a non-admin identity by default (config_repo.py: approve, request_changes)
DEFAULT_IDENTITY_CALLS = {"approve": "approver", "request_changes": "approver"}
POLLING_NAMES = frozenset({"poll", "wait_until", "retry", "Deadline"})  # otterdog_e2e.waiting
SLEEP_MODULES = frozenset({"time", "asyncio"})
BOT = "otterdog-e2e-app"
REPO = "e2e-t3c7z8a5-config"


# --- loading ------------------------------------------------------------------------------------------------------
@dataclass
class TierTest:
    """One test function of a tier module."""

    tier: str
    module: ModuleType
    name: str
    func: Callable[..., Any]
    node: ast.FunctionDef

    @property
    def marks(self) -> list[Any]:
        """Function marks plus the module's pytestmark (pytest.Mark objects)."""
        module_marks = getattr(self.module, "pytestmark", [])
        module_marks = module_marks if isinstance(module_marks, list) else [module_marks]
        return [getattr(mark, "mark", mark) for mark in [*getattr(self.func, "pytestmark", []), *module_marks]]

    def marked(self, name: str) -> list[Any]:
        """Marks named ``name``."""
        return [mark for mark in self.marks if mark.name == name]

    def mark_args(self, name: str) -> set[str]:
        """Union of the positional arguments of the ``name`` marks."""
        return {str(arg) for mark in self.marked(name) for arg in mark.args}

    @property
    def fixtures(self) -> set[str]:
        """Fixture names requested by the signature and by usefixtures marks."""
        return set(inspect.signature(self.func).parameters) | self.mark_args("usefixtures")

    @property
    def nodeid(self) -> str:
        """Readable id for assertion messages."""
        return f"tests/{self.tier}/{Path(self.module.__file__ or '').name}::{self.name}"


@dataclass
class Tiers:
    """The loaded modules of both tiers."""

    conftests: dict[str, ModuleType]
    modules: list[ModuleType]
    tests: list[TierTest]
    trees: dict[Path, ast.Module]

    def conftest(self, tier: str) -> ModuleType:
        """The conftest module of a tier."""
        return self.conftests[tier]


def _load(path: Path, name: str, loaded: list[str]) -> ModuleType:
    """Import ``path`` as module ``name`` (registered in sys.modules while the test runs: dataclasses need it)."""
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None, f"cannot load {path}"
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    loaded.append(name)
    spec.loader.exec_module(module)
    return module


def _test_functions(module: ModuleType, tree: ast.Module, tier: str) -> list[TierTest]:
    """The module-level test_* functions of a loaded module with their AST nodes."""
    nodes = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    return [
        TierTest(tier, module, name, getattr(module, name), node)
        for name, node in nodes.items()
        if name.startswith("test_") and callable(getattr(module, name, None))
    ]


def tier_files() -> dict[Path, str]:
    """Every conftest and test module of the tiers -> its tier (conftests first)."""
    files: dict[Path, str] = {}
    for tier, directory in TIER_DIRS.items():
        files[directory / "conftest.py"] = tier
        files.update(dict.fromkeys(sorted(directory.glob("test_*.py")), tier))
    return files


@pytest.fixture
def trees() -> dict[Path, ast.Module]:
    """The parsed modules of the tiers (no import: the source-level checks hold even when an import breaks)."""
    return {path: ast.parse(path.read_text(encoding="utf-8")) for path in tier_files()}


@pytest.fixture
def tiers(trees: dict[Path, ast.Module]) -> Iterator[Tiers]:
    """Every conftest and test module of tests/webapp and tests/webhooks, imported under the unit tier's no-network
    guard (removed from sys.modules afterwards)."""
    loaded: list[str] = []
    conftests: dict[str, ModuleType] = {}
    modules: list[ModuleType] = []
    tests: list[TierTest] = []
    try:
        for path, tier in tier_files().items():
            module = _load(path, f"_suite_static_{tier}_{path.stem}", loaded)
            if path.name == "conftest.py":
                conftests[tier] = module
                continue
            modules.append(module)
            tests.extend(_test_functions(module, trees[path], tier))
        yield Tiers(conftests, modules, tests, trees)
    finally:
        for name in loaded:
            sys.modules.pop(name, None)


def _is_fixture_decorator(decorator: ast.expr) -> bool:
    """``@pytest.fixture`` or ``@pytest.fixture(...)``."""
    target = decorator.func if isinstance(decorator, ast.Call) else decorator
    return isinstance(target, ast.Attribute) and target.attr == "fixture"


def conftest_fixture_deps(trees: dict[Path, ast.Module]) -> dict[str, set[str]]:
    """Fixtures defined in the tier conftests -> the fixtures they request (``request`` excluded)."""
    deps: dict[str, set[str]] = {}
    for path, tree in trees.items():
        if path.name != "conftest.py":
            continue
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and any(_is_fixture_decorator(d) for d in node.decorator_list):
                deps[node.name] = {arg.arg for arg in node.args.args} - {"request"}
    return deps


def fixture_closure(names: set[str], deps: dict[str, set[str]]) -> set[str]:
    """``names`` plus every fixture they reach through tier conftest fixtures."""
    closure, todo = set(), list(names)
    while todo:
        name = todo.pop()
        if name not in closure:
            closure.add(name)
            todo.extend(deps.get(name, ()))
    return closure


def identities_used(node: ast.AST) -> set[str]:
    """Non-admin identities a test acts as: ``identity="<name>"`` keywords, ``mutators["<name>"]`` subscripts,
    ConfigRepoFlow calls whose default identity is not admin (``approve`` without ``identity``) and the identity
    mutator fixtures it requests (pytest_plugin.FIXTURE_IDENTITIES: ``approver_mutator`` acts as approver, ...)."""
    used: set[str] = set()
    if isinstance(node, ast.FunctionDef):
        used |= {FIXTURE_IDENTITIES[arg.arg] for arg in node.args.args if arg.arg in FIXTURE_IDENTITIES}
    for child in ast.walk(node):
        if isinstance(child, ast.keyword) and child.arg == "identity" and isinstance(child.value, ast.Constant):
            used.add(str(child.value.value))
        elif isinstance(child, ast.Subscript) and isinstance(child.slice, ast.Constant):
            used.add(str(child.slice.value))
        elif isinstance(child, ast.Call) and isinstance(child.func, ast.Attribute):
            default = DEFAULT_IDENTITY_CALLS.get(child.func.attr)
            if default and not any(keyword.arg == "identity" for keyword in child.keywords):
                used.add(default)
    return used & NON_ADMIN_IDENTITIES


def sleep_calls(tree: ast.Module) -> list[str]:
    """Blind sleeps of a module: time.sleep / asyncio.sleep references, ``from time import sleep``, bare sleep()."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr == "sleep" and isinstance(node.value, ast.Name):
            if node.value.id in SLEEP_MODULES:
                found.append(f"line {node.lineno}: {node.value.id}.sleep")
        elif isinstance(node, ast.ImportFrom) and node.module in SLEEP_MODULES:
            found += [f"line {node.lineno}: from {node.module} import sleep" for a in node.names if a.name == "sleep"]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "sleep":
            found.append(f"line {node.lineno}: sleep()")
    return found


def own_polls(tree: ast.Module) -> list[str]:
    """Direct uses of otterdog_e2e.waiting polling in a test module (only the classified conftest helpers poll)."""
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in POLLING_NAMES and isinstance(node.value, ast.Name):
            if node.value.id == "waiting":
                found.append(f"line {node.lineno}: waiting.{node.attr}")
        elif isinstance(node, ast.ImportFrom) and (node.module or "").endswith("waiting"):
            found += [f"line {node.lineno}: import {a.name}" for a in node.names if a.name in POLLING_NAMES]
    return found


def unscoped_xfails(tree: ast.Module) -> list[str]:
    """``pytest.mark.xfail(...)`` without ``raises=`` and imperative ``pytest.xfail(...)`` calls of a module."""
    found = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "xfail"):
            continue
        owner = node.func.value
        if isinstance(owner, ast.Name) and owner.id == "pytest":
            found.append(f"line {node.lineno}: pytest.xfail()")
        elif not any(keyword.arg == "raises" for keyword in node.keywords):
            found.append(f"line {node.lineno}: xfail mark without raises=")
    return found


# --- catalogue and markers ----------------------------------------------------------------------------------------
def test_both_tiers_are_loaded(tiers: Tiers) -> None:
    """Both tiers have a conftest and test modules, every module imports without a target or network."""
    assert set(tiers.conftests) == set(TIER_DIRS)
    assert {test.tier for test in tiers.tests} == set(TIER_DIRS)


def test_catalogue_is_complete(tiers: Tiers) -> None:
    """Every SPEC 19 webapp/webhooks scenario has exactly one test with its scenario(id, priority) marker; the
    battery's other tests carry one scenario(id, priority=P0|P1|P2) marker each, with W-* (webapp) or H-* (webhooks)
    ids, and need no registration here (scenarios/coverage.yaml lists their node ids)."""
    seen: dict[str, list[str]] = {}
    for test in tiers.tests:
        marks = test.marked("scenario")
        assert len(marks) == 1 and len(marks[0].args) == 1, f"{test.nodeid}: exactly one scenario(id) marker"
        scenario = str(marks[0].args[0])
        seen.setdefault(scenario, []).append(test.nodeid)
        priority = marks[0].kwargs.get("priority")
        if scenario in CATALOGUE:
            assert priority == CATALOGUE[scenario], (
                f"{test.nodeid}: priority {priority!r}, catalogue {CATALOGUE[scenario]!r}"
            )
        else:
            assert priority in PRIORITIES, f"{test.nodeid}: scenario {scenario} needs priority= one of {PRIORITIES}"
            assert scenario.startswith(TIER_PREFIXES[test.tier]), f"{test.nodeid}: {TIER_PREFIXES[test.tier]}* ids"
    missing = sorted(set(CATALOGUE) - set(seen))
    assert not missing, f"catalogue scenarios without a test: {missing}"
    duplicates = {scenario: ids for scenario, ids in seen.items() if len(ids) > 1}
    assert not duplicates, f"scenarios implemented twice: {duplicates}"


def test_tags_use_the_selection_vocabulary(tiers: Tiers) -> None:
    """Every test is tagged (``--e2e-tags`` selection) with tags of selection.SCENARIO_TAGS only."""
    for test in tiers.tests:
        tags = test.mark_args("tags")
        assert tags, f"{test.nodeid}: no tags(...) marker"
        assert tags <= set(SCENARIO_TAGS), f"{test.nodeid}: unknown tags {sorted(tags - set(SCENARIO_TAGS))}"


def test_webapp_marker_matches_webapp_fixtures(tiers: Tiers) -> None:
    """``webapp`` on every tests/webapp test and on every test reaching a webapp fixture, on no other test."""
    deps = conftest_fixture_deps(tiers.trees)
    for test in tiers.tests:
        needs = bool(fixture_closure(test.fixtures, deps) & WEBAPP_FIXTURES)
        marked = bool(test.marked("webapp"))
        if test.tier == "webapp":
            assert needs and marked, f"{test.nodeid}: webapp tier tests need the webapp and its marker"
        assert marked == needs, f"{test.nodeid}: webapp marker {marked} but webapp fixtures needed: {needs}"


def test_docker_marker_only_for_docker_fixtures(tiers: Tiers) -> None:
    """``docker`` exactly on tests requesting docker-only fixtures (the webapp gate covers the compose stack)."""
    deps = conftest_fixture_deps(tiers.trees)
    for test in tiers.tests:
        needs = bool(fixture_closure(test.fixtures, deps) & DOCKER_FIXTURES)
        assert bool(test.marked("docker")) == needs, f"{test.nodeid}: docker marker vs docker-only fixtures"


def test_identities_marker_matches_the_identities_used(tiers: Tiers) -> None:
    """``identities(...)`` lists exactly the non-admin identities the test acts as (missing ones skip, not fail)."""
    for test in tiers.tests:
        used = identities_used(test.node)
        declared = test.mark_args("identities")
        assert declared == used, f"{test.nodeid}: identities marker {sorted(declared)}, used {sorted(used)}"
    automerge = next(test for test in tiers.tests if test.mark_args("scenario") == {"W-AUTOMERGE"})
    assert automerge.mark_args("identities") == {"author", "approver"}


def test_org_level_scenarios_reset_the_baseline(tiers: Tiers) -> None:
    """``org_level`` on the catalogue's org-level scenarios (and on any battery test changing org-level state), each
    with a cleanup that resets the baseline (webapp_case resets it for org_level items, org_level_reset otherwise)."""
    deps = conftest_fixture_deps(tiers.trees)
    for test in tiers.tests:
        org_level = bool(test.marked("org_level"))
        if test.mark_args("scenario") & ORG_LEVEL:
            assert org_level, f"{test.nodeid}: org_level marker"
        elif test.mark_args("scenario") & set(CATALOGUE):
            assert not org_level, f"{test.nodeid}: org_level marker on a catalogue scenario that is not org-level"
        if org_level:
            assert fixture_closure(test.fixtures, deps) & ORG_LEVEL_CLEANUPS, f"{test.nodeid}: no org-level cleanup"


def test_nothing_sleeps_blindly(trees: dict[Path, ast.Module]) -> None:
    """No time.sleep / asyncio.sleep in any module of the tiers (conftests included)."""
    offenders = {str(path.relative_to(PROJECT)): found for path, tree in trees.items() if (found := sleep_calls(tree))}
    assert not offenders, f"blind sleeps: {offenders}"


def test_test_modules_wait_through_classified_helpers(trees: dict[Path, ast.Module]) -> None:
    """Test modules never poll with otterdog_e2e.waiting directly (no infra/SUT classification there)."""
    offenders = {
        str(path.relative_to(PROJECT)): found
        for path, tree in trees.items()
        if path.name != "conftest.py" and (found := own_polls(tree))
    }
    assert not offenders, f"unclassified waits: {offenders}"


def test_xfails_are_scoped_to_their_regression(trees: dict[Path, ast.Module]) -> None:
    """Every xfail mark of the tiers carries ``raises=`` (the regression's own exception); no pytest.xfail()."""
    offenders = {
        str(path.relative_to(PROJECT)): found for path, tree in trees.items() if (found := unscoped_xfails(tree))
    }
    assert not offenders, f"unscoped expected failures: {offenders}"
    code = "pytest.xfail('x')\nmark = pytest.mark.xfail(reason='r')\nok = pytest.mark.xfail(reason='r', raises=E)\n"
    assert unscoped_xfails(ast.parse(code)) == ["line 1: pytest.xfail()", "line 2: xfail mark without raises="]


def known_bug_tests_without_scoped_xfail(tree: ast.Module) -> list[str]:
    """Test functions carrying ``pytest.mark.known_bug(...)`` without a ``pytest.mark.xfail(..., raises=...)``
    decorator (the plugin's xfail of a known bug would otherwise tolerate any failure of the body)."""
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) or not node.name.startswith("test_"):
            continue
        calls = [decorator for decorator in node.decorator_list if isinstance(decorator, ast.Call)]
        names = {call.func.attr for call in calls if isinstance(call.func, ast.Attribute)}
        scoped = any(
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "xfail"
            and any(keyword.arg == "raises" for keyword in call.keywords)
            for call in calls
        )
        if "known_bug" in names and not scoped:
            found.append(f"line {node.lineno}: {node.name}")
    return found


def test_known_bug_tests_name_the_exception_they_tolerate(trees: dict[Path, ast.Module]) -> None:
    """BAT-08: every webapp and webhooks test marked known_bug pairs it with an xfail(raises=...) decorator (or the
    webapp_case machinery's own raises=, for tests without the marker), so oracle timeouts, the first apply or the
    teardown never become XFAIL."""
    offenders = {
        str(path.relative_to(PROJECT)): found
        for path, tree in trees.items()
        if (found := known_bug_tests_without_scoped_xfail(tree))
    }
    assert not offenders, f"known-bug tests without xfail(raises=...): {offenders}"
    code = (
        "@pytest.mark.known_bug('KB-1')\ndef test_a():\n    pass\n\n"
        "@pytest.mark.known_bug('KB-1')\n@pytest.mark.xfail(raises=E, strict=False)\ndef test_b():\n    pass\n"
    )
    assert known_bug_tests_without_scoped_xfail(ast.parse(code)) == ["line 2: test_a"]


def test_test_modules_import_conftest_only_for_typing(trees: dict[Path, ast.Module]) -> None:
    """``from conftest import ...`` only under TYPE_CHECKING (importlib mode: conftest is not importable)."""
    for path, tree in trees.items():
        guarded = {
            id(node)
            for block in ast.walk(tree)
            if isinstance(block, ast.If) and isinstance(block.test, ast.Name) and block.test.id == "TYPE_CHECKING"
            for node in ast.walk(block)
        }
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "conftest":
                assert id(node) in guarded, f"{path.relative_to(PROJECT)}:{node.lineno}: runtime conftest import"


def test_sleep_detector_catches_blind_sleeps() -> None:
    """The detectors themselves: sleeps and direct polls are found, injected sleep callables are not."""
    code = "import time\nfrom time import sleep\ntime.sleep(1)\nsleep(2)\nwaiting.poll(f, until=bool, timeout=1)\n"
    assert len(sleep_calls(ast.parse(code))) == 3
    assert own_polls(ast.parse(code)) == ["line 5: waiting.poll"]
    assert not sleep_calls(ast.parse("waiting.poll(f, until=bool, timeout=1, sleep=self.flow.sleep)\n"))


def test_identity_detector_sees_identity_fixtures() -> None:
    """The identity mutator fixtures count as acting as their identity; the webapp helper fixtures need the webapp."""
    node = ast.parse("def test_x(approver_mutator, contributor_mutator, blueprints):\n    flow.comment(pr, 'x')\n")
    assert identities_used(node.body[0]) == {"approver", "author"}
    reviews = ast.parse("def test_y():\n    flow.request_changes(pr)\n    flow.dismiss_review(pr, review)\n")
    assert identities_used(reviews.body[0]) == {"approver"}  # request_changes reviews as the approver by default
    assert {"blueprints", "webapp_env", "webapp_stack", "dtrack_mock", "webapp_otterdog_json"} <= WEBAPP_FIXTURES


# --- conftest helpers ---------------------------------------------------------------------------------------------
def _renderer() -> OrgConfigRenderer:
    """A realistic renderer of the fake org (baseline of make_target)."""
    return OrgConfigRenderer(
        template=offline_template(),
        org=FAKE_ORG,
        plan="free",
        org_profile=org_profile(default_org_json()),
        baseline=build_baseline(make_target(), make_run_context()),
        marker=FAKE_MARKER,
        hide_cache_limit=True,
    )


def test_config_texts(tiers: Tiers) -> None:
    """New repositories, description overrides (merged by name) and the syntax error text (validated offline with
    otterdog 1.7.0.dev19: 1 add / 1 description change / load error accepted by the config guard)."""
    wapp = tiers.conftest("webapp")
    renderer = _renderer()
    baseline = renderer.render()
    text = wapp.config_text(renderer, repos={"e2e-t3c7z8a5-w-x": "new"}, overrides={"otterdog-e2e-fixture-a": "x"})
    layer2 = text[len(baseline.rsplit("} {", 1)[0]) :]
    assert 'orgs.newRepo("e2e-t3c7z8a5-w-x") { description: "new" }' in layer2
    assert '{ name: "otterdog-e2e-fixture-a", description: "x" }' in layer2
    assert "_repositories+:" in layer2
    assert wapp.config_text(renderer) == baseline
    broken = wapp.syntax_error_text(baseline)
    assert (
        broken.startswith(baseline.rstrip()) and broken.endswith("}\n") and broken.count("}") == baseline.count("}") + 1
    )
    assert wapp.harmless_repo(make_target()) == "otterdog-e2e-fixture-a"
    assert wapp.harmless_repo(make_target(fixture_repos=())) == "otterdog-e2e-configs"
    assert wapp.slugify("W-PR-STALE-SNAPSHOT") == "w-pr-stale-snapshot"
    hooks = tiers.conftest("webhooks").WebhookHelpers
    assert hooks.harmless_text(renderer, make_target(), "x") == wapp.config_text(
        renderer, overrides={"otterdog-e2e-fixture-a": "x"}
    )


class FakeTime:
    """Monotonic clock advanced by sleep()."""

    def __init__(self) -> None:
        """t=0."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def clock(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the clock."""
        self.sleeps.append(seconds)
        self.now += seconds


def _scenario(tiers: Tiers, *, transport: str = "relay", e2e: Any = None) -> tuple[Any, FakeOracle, ConfigPr]:
    """A WebappScenario on a FakeOracle (no relay: reaction budgets start at the call) and an open ConfigPr."""
    wapp = tiers.conftest("webapp")
    oracle = FakeOracle()
    run_ctx = make_run_context()
    flow = ConfigRepoFlow(
        org=FAKE_ORG,
        repo=REPO,
        oracle=oracle,  # type: ignore[arg-type]
        mutators={"admin": RecordingMutator(oracle=oracle)},  # type: ignore[dict-item]
        run_ctx=run_ctx,
        validation_context="e2e/otterdog-validate",
        sync_context="e2e/otterdog-sync",
        guard=lambda base, head: None,
        bot_login=f"{BOT}[bot]",
    )
    fake = FakeTime()
    flow.sleep, flow.clock = fake.sleep, fake.clock
    target = make_target()
    if transport != "relay":
        target = make_target(webapp=SimpleNamespace(transport=transport))
    scenario = wapp.WebappScenario(
        sid="W-TEST",
        e2e=e2e or SimpleNamespace(),
        case=SimpleNamespace(org=FAKE_ORG, baseline_text=""),
        flow=flow,
        api=SimpleNamespace(),
        renderer=_renderer(),
        baseline=SimpleNamespace(),
        oracle=oracle,
        run_ctx=run_ctx,
        target=target,
    )
    pr = ConfigPr(7, run_ctx.branch("w-test"), fake_sha("head"), "", "e2e-admin", frozenset())
    return scenario, oracle, pr


def test_wait_applied_accepts_success_and_reports_failures(tiers: Tiers) -> None:
    """The apply comment wait ends on both outcomes; a [!CAUTION] comment fails as a SUT problem."""
    scenario, oracle, pr = _scenario(tiers)
    texts = scenario.texts
    oracle.add_pr_comment(REPO, pr.number, f"> [!NOTE]\n> {texts.APPLY_SUCCESS}:\n```diff\n+ add x\n```", author=BOT)
    assert texts.APPLY_SUCCESS in scenario.wait_applied(pr)["body"]

    scenario, oracle, pr = _scenario(tiers)
    oracle.add_pr_comment(REPO, pr.number, "> [!CAUTION]\n> The changes could not be applied successfully", author=BOT)
    with pytest.raises(AssertionError, match=r"could not apply PR #7 \(SUT\)"):
        scenario.wait_applied(pr)


def test_reaction_timeouts_are_classified(tiers: Tiers) -> None:
    """WebappScenario.reaction -> ReactionTimeoutError (SUT); WebhookHelpers.reaction -> infra or SUT."""
    scenario, _, _ = _scenario(tiers)
    with pytest.raises(ReactionTimeoutError, match=r"within 30 s \(SUT\): thing"):
        scenario.reaction(lambda: None, until=lambda value: value is not None, what="thing", timeout=30)
    hooks = tiers.conftest("webhooks").WebhookHelpers
    with pytest.raises(DeliveryTimeoutError, match=r"ping: not observed within 0 s \(infra\)"):
        hooks.reaction(list, until=bool, what="ping", timeout=0, infra=True)
    with pytest.raises(ReactionTimeoutError, match=r"hook: not observed within 0 s \(SUT\)"):
        hooks.reaction(lambda: None, until=lambda value: value is not None, what="hook", timeout=0)
    assert hooks.reaction(lambda: 3, until=bool, what="x", timeout=0) == 3


def test_wait_minimized(tiers: Tiers) -> None:
    """A comment minimized as outdated is returned; another reason fails; a never minimized one times out."""
    scenario, oracle, pr = _scenario(tiers)
    comment = oracle.add_pr_comment(REPO, pr.number, "<!-- Otterdog Comment: help -->", author=BOT)
    with pytest.raises(ReactionTimeoutError, match="minimized"):
        scenario.wait_minimized(pr, comment, timeout=10)
    stored = oracle.pr_comments(REPO, pr.number)[0] | {"is_minimized": True, "minimized_reason": "outdated"}
    oracle.set("pr_comments", REPO, pr.number, value=[stored])
    assert scenario.wait_minimized(pr, comment)["is_minimized"] is True
    oracle.set("pr_comments", REPO, pr.number, value=[stored | {"minimized_reason": "SPAM"}])
    with pytest.raises(AssertionError, match="not outdated"):
        scenario.wait_minimized(pr, comment)


def test_webapp_includes(tiers: Tiers, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown (None) for external webapps and images without revision; the mirror decides otherwise."""
    scenario, _, _ = _scenario(tiers, transport="external")
    assert scenario.webapp_includes(fake_sha("fix")) is None

    images = {"head": BuiltImage("otterdog-e2e/otterdog:x", "sha256:1", "1.7.0", "", True)}
    e2e = SimpleNamespace(
        image_for=images.__getitem__, settings=SimpleNamespace(cache_dir=Path("/x"), upstream_repo="o/r")
    )
    scenario, _, _ = _scenario(tiers, e2e=e2e)
    assert scenario.webapp_includes(fake_sha("fix")) is None

    class Mirror:
        """UpstreamMirror stand-in: fix is an ancestor of rev only."""

        def __init__(self, cache_dir: Path, repo: str) -> None:
            """Ignore the location."""

        def has_commit(self, rev: str) -> bool:
            """Every commit is known."""
            return True

        def is_ancestor(self, a: str, b: str) -> bool:
            """fix -> rev."""
            return (a, b) == (fake_sha("fix"), fake_sha("rev"))

    monkeypatch.setattr("otterdog_e2e.sut.source.UpstreamMirror", Mirror)
    images["head"] = BuiltImage("otterdog-e2e/otterdog:x", "sha256:1", "1.7.0", fake_sha("rev"), True)
    assert scenario.webapp_includes(fake_sha("fix")) is True
    assert scenario.webapp_includes(fake_sha("other")) is False


def test_call_timeouts_only_for_tier_items(tiers: Tiers, tmp_path: Path) -> None:
    """Items of the tier directory without a timeout marker get timeout(<t>, func_only=True); nothing without the
    pytest-timeout plugin."""
    wapp = tiers.conftest("webapp")
    tmp_path = tmp_path.resolve()

    class Item:
        """pytest.Item stand-in."""

        def __init__(self, path: Path, timeout: bool = False) -> None:
            """No marks yet."""
            self.path = path
            self.added: list[Any] = []
            self.timeout = timeout

        def get_closest_marker(self, name: str) -> Any:
            """A timeout marker when configured."""
            return object() if name == "timeout" and self.timeout else None

        def add_marker(self, mark: Any) -> None:
            """Record."""
            self.added.append(mark)

    inside, other, explicit = (
        Item(tmp_path / "test_a.py"),
        Item(tmp_path.parent / "test_b.py"),
        Item(tmp_path / "t.py", True),
    )
    config = SimpleNamespace(pluginmanager=SimpleNamespace(hasplugin=lambda name: name == "timeout"))
    wapp.add_call_timeouts(config, [inside, other, explicit], tmp_path, 900)
    assert [(m.mark.name, m.mark.args, m.mark.kwargs) for m in inside.added] == [
        ("timeout", (900,), {"func_only": True})
    ]
    assert not other.added and not explicit.added
    fresh = Item(tmp_path / "test_c.py")
    wapp.add_call_timeouts(
        SimpleNamespace(pluginmanager=SimpleNamespace(hasplugin=lambda name: False)), [fresh], tmp_path, 900
    )
    assert not fresh.added


def test_delivery_records_skip_partial_lines(tiers: Tiers, tmp_path: Path) -> None:
    """deliveries.jsonl parsing keeps complete JSON objects only."""
    hooks = tiers.conftest("webhooks").WebhookHelpers
    path = tmp_path / "deliveries.jsonl"
    path.write_text('{"id": 1, "relay_status": 204}\n[1]\n{"id": 2, "rel', encoding="utf-8")
    assert hooks.delivery_records(path) == [{"id": 1, "relay_status": 204}]
    assert hooks.delivery_records(None) == [] and hooks.delivery_records(tmp_path / "missing.jsonl") == []


def test_xfail_unless_includes(tiers: Tiers, monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression xfails: none when the fix is included; strict when it is missing and every later version contains
    it; non-strict when it may land as another commit or inclusion is unknown; always scoped to the error."""

    class Mirror:
        """UpstreamMirror stand-in: only fix_known is an ancestor of the revision."""

        def __init__(self, cache_dir: Path, repo: str) -> None:
            """Ignore the location."""

        def has_commit(self, rev: str) -> bool:
            """Every commit is known."""
            return True

        def is_ancestor(self, a: str, b: str) -> bool:
            """fix_known -> rev."""
            return a == fake_sha("fix_known")

    monkeypatch.setattr("otterdog_e2e.sut.source.UpstreamMirror", Mirror)
    image = BuiltImage("otterdog-e2e/otterdog:x", "sha256:1", "1.7.0", fake_sha("rev"), True)
    e2e = SimpleNamespace(
        image_for={"head": image}.__getitem__, settings=SimpleNamespace(cache_dir=Path("/x"), upstream_repo="o/r")
    )

    def marks(commit: str, *, strict: bool, transport: str = "relay") -> list[Any]:
        """xfail marks added for one call."""
        scenario, _, _ = _scenario(tiers, transport=transport, e2e=e2e)
        added: list[Any] = []
        request = SimpleNamespace(node=SimpleNamespace(add_marker=added.append))
        scenario.xfail_unless_includes(request, commit, error=KeyError, reason="kb", strict=strict)
        return [(m.mark.name, m.mark.kwargs) for m in added]

    scoped = {"reason": "kb", "raises": KeyError}
    assert marks(fake_sha("fix_known"), strict=True) == []
    assert marks(fake_sha("fix_known"), strict=False) == []
    assert marks(fake_sha("missing"), strict=True) == [("xfail", {**scoped, "strict": True})]
    assert marks(fake_sha("missing"), strict=False) == [("xfail", {**scoped, "strict": False})]
    assert marks(fake_sha("missing"), strict=True, transport="external") == []
    assert marks(fake_sha("missing"), strict=False, transport="external") == [("xfail", {**scoped, "strict": False})]


def test_known_bug_reason(tiers: Tiers) -> None:
    """The known bug whose upstream URL ends with the suffix names the xfail; a default otherwise."""
    from otterdog_e2e.known_bugs import KnownBug

    bug = KnownBug("KB-018", "stale snapshots", upstream="https://github.com/eclipse-csi/otterdog/pull/792/")
    scenario, _, _ = _scenario(tiers, e2e=SimpleNamespace(known_bugs=lambda: {bug.id: bug}))
    assert scenario.known_bug_reason("/pull/792", "default") == "KB-018: stale snapshots"
    assert scenario.known_bug_reason("/pull/999", "default") == "default"


# --- battery helpers of the webapp conftest -----------------------------------------------------------------------
def test_battery_config_fragments(tiers: Tiers) -> None:
    """repo_patch / new_repo / repo_secret / cache_size: the layer-2 snippets of the battery (tried offline with
    otterdog v1.6.1: a secret patch adds one repo_secret with a credential-provider warning, a new repository with
    ``max_cache_size_gb::: 10`` adds it unchanged, the invalid topic is a validation error, the team_permissions value
    outside the schema enum a load error, an ``importstr`` of ``../<file>`` a load error)."""
    wapp = tiers.conftest("webapp")
    secret = wapp.repo_secret("E2E_T3C7Z8A5_S", "e2e-dummy-t3c7z8a5")
    assert secret == 'secrets+: [orgs.newRepoSecret("E2E_T3C7Z8A5_S") { value: "e2e-dummy-t3c7z8a5" }]'
    assert wapp.repo_patch("otterdog-e2e-fixture-a", secret) == f'{{ name: "otterdog-e2e-fixture-a", {secret} }}'
    assert wapp.cache_size(10) == "workflows+: { max_cache_size_gb::: 10 }"
    assert wapp.new_repo("e2e-t3c7z8a5-w-x", "d") == 'orgs.newRepo("e2e-t3c7z8a5-w-x") { description: "d" }'
    assert wapp.new_repo("e2e-t3c7z8a5-w-x", "d", wapp.cache_size(5)) == (
        'orgs.newRepo("e2e-t3c7z8a5-w-x") { description: "d", workflows+: { max_cache_size_gb::: 5 } }'
    )
    scenario, _, _ = _scenario(tiers)
    assert scenario.schema_error() == 'team_permissions+: { "otterdog-admins": "e2e-not-a-permission" }'
    assert scenario.invalid_topic() == 'topics: ["E2E_Not_A_Topic"]'
    team = 'orgs.newTeam("e2e-t3c7z8a5-w-team") { description: "t", members: [] }'
    text = scenario.render(repositories=[scenario.patch("otterdog-e2e-fixture-a", secret)], teams=[team])
    baseline = _renderer().render()
    layer2 = text[len(baseline.rsplit("} {", 1)[0]) :]
    assert f'{{ name: "otterdog-e2e-fixture-a", {secret} }}' in layer2 and team in layer2
    assert scenario.render() == baseline


def test_commit_statuses_and_bot_comments(tiers: Tiers) -> None:
    """commit_statuses lists every status of a context (aliases validation / sync) newest first through
    Oracle.commit_statuses; new_bot_comments ignores known ids."""
    scenario, oracle, pr = _scenario(tiers)
    statuses = [
        {"context": "e2e/otterdog-validate", "state": "success"},
        {"context": "e2e/otterdog-sync", "state": "pending"},
        {"context": "e2e/otterdog-validate", "state": "pending"},
        {"context": "other", "state": "error"},
    ]
    oracle.set("commit_statuses", REPO, pr.head_sha, value=statuses)
    assert [s["state"] for s in scenario.commit_statuses(pr.head_sha, "validation")] == ["success", "pending"]
    assert scenario.commit_statuses(pr.head_sha, "sync") == [statuses[1]]
    assert scenario.commit_statuses(pr.head_sha, "other") == [{"context": "other", "state": "error"}]
    assert ("commit_statuses", (REPO, pr.head_sha)) in oracle.calls

    help_comment = oracle.add_pr_comment(REPO, pr.number, "<!-- Otterdog Comment: help -->", author=BOT)
    oracle.add_pr_comment(REPO, pr.number, "/otterdog help", author="e2e-admin")
    seen = scenario.bot_comment_ids(pr)
    assert seen == {help_comment["id"], str(help_comment["database_id"])}
    validate = oracle.add_pr_comment(REPO, pr.number, "<!-- Otterdog Comment: validate -->", author=BOT)
    assert [c["id"] for c in scenario.new_bot_comments(pr, seen)] == [validate["id"]]
    assert scenario.new_bot_comments(pr, seen, marker="help") == []


def test_settle_and_tasks_without_pull_request(tiers: Tiers) -> None:
    """settle: the trigger delivery (none without a relay) then quiesce; wait_repo_task: no pull request filter, a
    missing task is a SUT reaction timeout."""
    scenario, _, pr = _scenario(tiers)
    quiesced: list[dict[str, Any]] = []
    waited: list[dict[str, Any]] = []

    def wait_task(**kwargs: Any) -> dict[str, Any]:
        """Record; Missing never finishes."""
        waited.append(kwargs)
        if kwargs["type_"] == "Missing":
            raise waiting.WaitTimeoutError("webapp task Missing", kwargs["timeout"])
        return {"type": kwargs["type_"], "status": "finished"}

    scenario.api = SimpleNamespace(quiesce=lambda **kwargs: quiesced.append(kwargs), wait_task=wait_task)
    now = scenario.now()
    scenario.settle(pr, event="issue_comment", action="created", after=now)
    assert quiesced == [{"org_id": FAKE_ORG, "quiet_for": 10.0, "timeout": 240.0}]
    assert scenario.wait_repo_task("DeleteBranchTask", after=now) == {"type": "DeleteBranchTask", "status": "finished"}
    assert waited[0] == {
        "type_": "DeleteBranchTask",
        "org_id": FAKE_ORG,
        "after": now,
        "repo_name": REPO,
        "pull_request": None,
        "timeout": 120.0,
    }
    with pytest.raises(ReactionTimeoutError, match=rf"Missing for {REPO} within 120 s \(SUT\)"):
        scenario.wait_repo_task("Missing", after=now)
    scenario.wait_repo_task("UpdateBlueprintStatusTask", after=now, repo="e2e-t3c7z8a5-w-x", pull_request=3)
    assert (waited[-1]["repo_name"], waited[-1]["pull_request"]) == ("e2e-t3c7z8a5-w-x", 3)


def test_installation_and_push_waits(tiers: Tiers) -> None:
    """wait_installation polls /admin/organizations; wait_push matches the push of a sha to the config repo, checks
    its forward, and is a no-op without a relay."""
    from otterdog_e2e.webhooks.relay import RelayedDelivery

    scenario, _, _ = _scenario(tiers)
    rows = iter([{}, {FAKE_ORG: {"installation_id": 7, "status": "installed", "project_name": "p"}}])
    current: dict[str, Any] = {}

    def installations() -> dict[str, Any]:
        """The next page state, then the last one."""
        current.update(next(rows, current))
        return dict(current)

    scenario.api = SimpleNamespace(installations=installations)
    assert scenario.wait_installation(status="installed", installation_id=7)["project_name"] == "p"
    with pytest.raises(ReactionTimeoutError, match=r"installation of e2e-test-org suspended"):
        scenario.wait_installation(status="suspended", timeout=10)

    sha = fake_sha("merge")
    assert scenario.wait_push(sha) is None  # no relay: no delivery tracking
    now = scenario.now()

    def delivery(head_sha: str, repository: str, relay_status: int | None) -> RelayedDelivery:
        """A relayed push."""
        return RelayedDelivery(
            1,
            "g",
            "push",
            None,
            1,
            1,
            None,
            now,
            now,
            now if relay_status else None,
            200,
            relay_status,
            head_sha=head_sha,
            repository_name=repository,
        )

    class Relay:
        """DeliveryRelay stand-in: wait_for over a fixed list."""

        def __init__(self, deliveries: list[RelayedDelivery]) -> None:
            """Remember the deliveries."""
            self.deliveries = deliveries

        def wait_for(self, predicate: Callable[[RelayedDelivery], bool], *, timeout: float) -> RelayedDelivery:
            """The first matching delivery or a timeout."""
            found = next((d for d in self.deliveries if predicate(d)), None)
            if found is None:
                raise waiting.WaitTimeoutError("relayed delivery", timeout)
            return found

    scenario.flow.relay = Relay([delivery(sha, "other-repo", 204), delivery(sha, REPO, 204)])  # type: ignore[assignment]
    assert scenario.wait_push(sha).repository_name == REPO  # type: ignore[union-attr]
    with pytest.raises(DeliveryTimeoutError, match=r"push delivery of .* not observed .* \(infra\)"):
        scenario.wait_push(fake_sha("other"))
    scenario.flow.relay = Relay([delivery(sha, REPO, None)])  # type: ignore[assignment]
    with pytest.raises(DeliveryTimeoutError, match="was not forwarded"):
        scenario.wait_push(sha)


def test_open_pr_with_cli_adopts_the_otterdog_branch(tiers: Tiers) -> None:
    """open-pr runs on the guarded text, the printed number is adopted (head otterdog/e2e-<run>-<slug>-<suffix>);
    no number printed is an assertion error."""
    from otterdog_e2e.testing.fakes import FAKE_LOGINS, FakeCli, FakeWorkspace

    scenario, oracle, _ = _scenario(tiers)
    branch = "otterdog/e2e-t3c7z8a5-w-test-x"
    pull = {"number": 42, "head": {"ref": branch, "sha": fake_sha("h")}, "base": {"ref": "main"}, "user": {}}
    oracle.add_pull(REPO, pull)
    guarded: list[str] = []
    scenario.flow.guard = lambda base, head: guarded.append(head)
    cli = FakeCli(workspace=FakeWorkspace())
    cli.queue("open-pr", stdout=f"created pull request #42 at https://github.com/{FAKE_ORG}/{REPO}/pull/42\n")
    pr = scenario.open_pr_with_cli(cli, "config text", suffix="x")  # type: ignore[arg-type]
    assert (pr.number, pr.branch, guarded, cli.workspace.writes) == (42, branch, ["config text"], ["config text"])
    assert cli.calls_to("open-pr")[0].kwargs == {
        "branch": "e2e-t3c7z8a5-w-test-x",
        "title": "e2e t3c7z8a5 W-TEST",
        "author": FAKE_LOGINS["admin"],
    }
    cli.queue("open-pr", stdout="no local changes, no PR has been opened\n")
    with pytest.raises(AssertionError, match="no pull request number"):
        scenario.open_pr_with_cli(cli, "config text", suffix="y")  # type: ignore[arg-type]


def test_pull_state_helpers(tiers: Tiers) -> None:
    """refreshed / assert_still_open / wait_api_pull_gone / wait_branch_gone / wait_problems / wait_applied(exclude)
    / stored_repositories / statuses_of / login."""
    wapp = tiers.conftest("webapp")
    scenario, oracle, pr = _scenario(tiers)
    texts = scenario.texts
    oracle.add_pull(REPO, {"number": pr.number, "state": "open", "merged": False, "head": {"sha": fake_sha("new")}})
    assert scenario.refreshed(pr).head_sha == fake_sha("new")
    scenario.assert_still_open(pr, "never merged")
    oracle.set("pull", REPO, pr.number, value={"number": pr.number, "state": "closed", "merged": True})
    with pytest.raises(AssertionError, match=r"must stay open \(never merged\)"):
        scenario.assert_still_open(pr, "never merged")

    records = iter([{"id": {"pull_request": pr.number}}, None])
    scenario.api = SimpleNamespace(pull_request=lambda org, repo, number: next(records, None))
    scenario.wait_api_pull_gone(pr, what="after its close")
    oracle.add_branch(REPO, "otterdog/e2e-t3c7z8a5-w-test")
    with pytest.raises(ReactionTimeoutError, match="deleted"):
        scenario.wait_branch_gone("otterdog/e2e-t3c7z8a5-w-test", timeout=10)
    oracle.remove("branch_sha", REPO, "otterdog/e2e-t3c7z8a5-w-test")
    scenario.wait_branch_gone("otterdog/e2e-t3c7z8a5-w-test")

    problems = f"> [!WARNING]\n> {texts.AUTOMERGE_PROBLEMS}\n\n{texts.NOT_VALID}, check the comment\n"
    oracle.add_pr_comment(REPO, pr.number, problems, author=BOT)
    assert texts.NOT_VALID in scenario.wait_problems(pr)
    failed = oracle.add_pr_comment(
        REPO, pr.number, "> [!CAUTION]\n> The changes could not be applied successfully", author=BOT
    )
    with pytest.raises(AssertionError, match="could not apply"):
        scenario.wait_applied(pr)
    oracle.add_pr_comment(REPO, pr.number, f"> [!NOTE]\n> {texts.APPLY_SUCCESS}:\n", author=BOT)
    assert texts.APPLY_SUCCESS in scenario.wait_applied(pr, exclude=[failed])["body"]

    stored = {"repositories": [{"name": "a", "description": "d"}, {"description": "no name"}, "x"]}
    assert scenario.stored_repositories(stored) == {"a": {"name": "a", "description": "d"}}
    assert scenario.stored_repositories(None) == {}
    ordered = [{"context": "a", "id": 2}, {"context": "b", "id": 1}, {"context": "a", "id": 0}]
    assert wapp.statuses_of(ordered, "a") == [{"context": "a", "id": 2}, {"context": "a", "id": 0}]
    assert scenario.login("approver") == "e2e-approver"
    scenario.target = make_target(identities={})
    with pytest.raises(AssertionError, match="no login for identity 'approver'"):
        scenario.login("approver")


def test_texts_match_the_templates(tiers: Tiers) -> None:
    """The battery's regexes match otterdog's texts (templates and messages of main 9bdeb75, unchanged since v1.5.0)."""
    texts = tiers.conftest("webapp").Texts
    third_party = (
        "Only the author of the pull request, a member of team 'project-leads', "
        f"or a member of team '{FAKE_ORG}/otterdog-admins' is allowed to auto-merge."
    )
    assert texts.THIRD_PARTY_RE.search(third_party)
    team_info = (
        "<!-- Otterdog Comment: team-info -->\nThe author ([e2e-author](https://github.com/e2e-author)) of this PR "
        "is associated with this organization in the role of `MEMBER`.\n"
    )
    match = texts.TEAM_INFO_RE.search(team_info)
    assert match is not None and match.group("role") == "MEMBER"
    hint = texts.INFOS_HINT_RE.search("there have been 2 validation infos, enable verbose output to display them.")
    assert hint is not None and hint.group("infos") == "2"
