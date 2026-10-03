"""The live-tier scenario files, the known-bug registry and their links (SPEC 12.1, 12.5, 19).

Checks the real files of the project (no network): every YAML of scenarios/cli, scenarios/regressions and
scenarios/enterprise loads with the strict model; scenario ids are unique across every scenario directory; the
SPEC 19 catalogue is implemented with its priorities; every object a fragment creates carries the run prefix and
every webhook URL lies under naming.HOOK_BASE (cleanup and the janitor only ever remove such objects); tags use the
selection vocabulary; known_bugs.yaml loads, its evidence is well formed, every bug referenced by a scenario or a
Python test exists and links back, and docs/known-issues.md mirrors every entry (confirmed ones with a reproduction).
"""

from __future__ import annotations

import ast
import importlib.util
import json
import re
import shutil
import sys
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

from otterdog_e2e import procs
from otterdog_e2e.capabilities import PLANS
from otterdog_e2e.known_bugs import KnownBug, load
from otterdog_e2e.naming import is_e2e_name, new_run_context
from otterdog_e2e.otterdog.render import OrgConfigRenderer, build_baseline, org_profile
from otterdog_e2e.scenarios.collect import ORG_LEVEL_EXTRA_TIMEOUT, TIER_TIMEOUTS, collect_scenarios, scenario_timeout
from otterdog_e2e.scenarios.engine import fixed_in_skip_reason
from otterdog_e2e.scenarios.model import Scenario, load_scenarios, render_step, scenario_files
from otterdog_e2e.selection import SCENARIO_TAGS
from otterdog_e2e.settings import IDENTITY_ROLES
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FAKE_MARKER, FAKE_ORG, default_org_json, make_target

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
LIVE_DIRS = ("cli", "regressions", "enterprise")
KNOWN_BUGS = SCENARIOS / "known_bugs.yaml"
KNOWN_ISSUES_DOC = ROOT / "docs" / "known-issues.md"
# Python test tiers (offline included): their scenario(id) / known_bug(id) markers are link targets of
# known_bugs.yaml; a known-bug test gets a scenario id of its own (cli.kb.<name>, O-KB-<NAME>, ...) so that the bug's
# scenarios list does not xfail the other tests of a shared id
TEST_DIRS = tuple(ROOT / "tests" / name for name in ("offline", "cli", "enterprise", "webhooks", "webapp", "web_ui"))
CLI_CONFTEST = ROOT / "tests" / "cli" / "conftest.py"
TEMPLATE_DIR = ROOT / "tests" / "unit" / "data" / "template"  # examples/template of otterdog main @9bdeb75
JSONNET = shutil.which("jsonnet")

# SPEC 19 catalogue -> (scenario id, priority; "P0 unless noted"); YAML scenarios
CATALOGUE: dict[str, tuple[str, str]] = {
    "C-REPO-LIFECYCLE": ("cli.repo.lifecycle", "P0"),
    "C-TEAM": ("cli.team", "P0"),
    "C-SECRETS": ("cli.secrets", "P0"),
    "C-REPO-WEBHOOK": ("cli.repo.webhook", "P0"),
    "C-NEG-PRIVATE-BPR": ("cli.neg.private-bpr", "P0"),
    "C-BPR-PUBLIC": ("cli.bpr.public", "P1"),
    "C-RULESET-PUBLIC": ("cli.ruleset.public", "P1"),
    "C-ENV": ("cli.environment", "P1"),
    "C-ORG-VARIABLE": ("cli.org.variable", "P1"),
    "C-CUSTOM-PROPERTY": ("cli.custom-property", "P1"),
    "C-PLAN-MISMATCH": ("cli.plan-mismatch", "P1"),
    "C-NEG-PRIVATE-RULESET": ("cli.neg.private-ruleset", "P2"),
    "E-ORG-ROLE": ("enterprise.org-role", "P0"),
    "E-ORG-RULESET": ("enterprise.org-ruleset", "P0"),
    "E-PRIVATE-BPR": ("enterprise.private-bpr", "P0"),
    "E-ENV-REVIEWERS-PRIVATE": ("enterprise.env-reviewers-private", "P0"),
}
# SPEC 19 catalogue entries implemented as Python tests (pytest.mark.scenario ids)
PYTHON_CATALOGUE = {
    "C-SMOKE": "cli.smoke",
    "C-BASELINE": "cli.baseline",
    "C-PUSH-FETCH": "cli.push-fetch",
    "C-OPEN-PR": "cli.open-pr",
    "C-IMPORT": "cli.import",
}
# SPEC 12.5 seed: every one must stay in the registry (ids are stable references for docs and reports)
SEED_IDS = tuple(f"KB-{index:03d}" for index in range(1, 20))
MODEL_TAGS = frozenset(SCENARIO_TAGS) - {"smoke", "offline", "webapp", "webhooks-app"}
# constructors creating org-level objects or repositories: their first argument must be a run-prefixed name
NAMED_CONSTRUCTORS = (
    "newRepo",
    "newTeam",
    "newOrgRuleset",
    "newOrgRole",
    "newCustomProperty",
    "newOrgVariable",
    "newOrgSecret",
    "newRepoSecret",
    "newRepoVariable",
)
URL_CONSTRUCTORS = ("newRepoWebhook", "newOrgWebhook")
_CONSTRUCTOR_RE = re.compile(r"orgs\.(\w+)\(\s*(['\"])(.*?)\2")
_ALIASES_RE = re.compile(r"aliases\s*:\s*\[([^\]]*)\]")
_QUOTED_RE = re.compile(r"(['\"])(.*?)\1")
_EVIDENCE_RE = re.compile(r"^(?P<path>(otterdog|docs|examples)/[\w./\-]+):(?P<start>\d+)(-(?P<end>\d+))?$")
_CHART_EVIDENCE_RE = re.compile(r"^chart: [\w./\-]+:\d+(-\d+)?$")
_OPENAPI_EVIDENCE_RE = re.compile(r"^openapi: \S.*$")
_E2E_EVIDENCE_RE = re.compile(r"^e2e: (?P<path>[\w./\-]+)( \(.+\))?$")  # a file of this project
SAMPLE_RUN = new_run_context("t3c7z8a5")


# --- loading -------------------------------------------------------------------------------------------------------
@cache
def live_scenarios() -> tuple[Scenario, ...]:
    """Every scenario of the live directories, loaded with the strict model (ids unique across them)."""
    return tuple(collect_scenarios([SCENARIOS / name for name in LIVE_DIRS]))


@cache
def scenarios_by_id() -> dict[str, Scenario]:
    """Live scenarios keyed by id."""
    return {scenario.id: scenario for scenario in live_scenarios()}


@cache
def known_bugs() -> dict[str, KnownBug]:
    """scenarios/known_bugs.yaml."""
    return load(KNOWN_BUGS)


def sample_variables(scenario: Scenario) -> dict[str, Any]:
    """Jinja variables of a live render (sample run t3c7z8a5), the scenario's own variables last."""
    return {
        **SAMPLE_RUN.template_vars(),
        "org": "e2e-sample-org",
        "plan": "free",
        "logins": {role: f"e2e-sample-{role.replace('_', '-')}" for role in IDENTITY_ROLES},
        "app_slug": "e2e-sample-app",
        "app_id": "123456",
        "teams": {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"},
        **scenario.variables,
    }


def rendered_snippets(scenario: Scenario) -> Iterator[tuple[str, str]]:
    """(step name, rendered fragment snippet) of every step of a scenario."""
    variables = sample_variables(scenario)
    for step in scenario.steps:
        rendered = render_step(step, variables)
        for snippets in rendered.fragments.to_mapping().values():
            for snippet in snippets:
                yield step.name, snippet


def other_scenario_ids() -> list[tuple[str, Path]]:
    """Ids declared by YAML files of the other scenario directories (offline...), read without validation."""
    found = []
    for directory in sorted(path for path in SCENARIOS.iterdir() if path.is_dir() and path.name not in LIVE_DIRS):
        for path in scenario_files(directory):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue  # another tier's file: its own tests report it
            if isinstance(data, dict) and isinstance(data.get("id"), str):
                found.append((data["id"], path))
    return found


@cache
def python_markers() -> dict[str, dict[str, set[str]]]:
    """``{"scenario": {id: tests}, "known_bug": {id: scenario ids of those tests}}`` of the Python tests of the e2e
    tiers (TEST_DIRS)."""
    scenarios: dict[str, set[str]] = {}
    bugs: dict[str, set[str]] = {}
    for directory in TEST_DIRS:
        for path in sorted(directory.glob("test_*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            module_scenarios = set(_marker_args(_module_marks(tree), "scenario"))
            for node in tree.body:
                if not isinstance(node, ast.FunctionDef) or not node.name.startswith("test_"):
                    continue
                own = set(_marker_args(node.decorator_list, "scenario")) | module_scenarios
                for scenario_id in own:
                    scenarios.setdefault(scenario_id, set()).add(f"{path.name}::{node.name}")
                for bug_id in _marker_args(node.decorator_list, "known_bug"):
                    bugs.setdefault(bug_id, set()).update(own)
    return {"scenario": scenarios, "known_bug": bugs}


def _module_marks(tree: ast.Module) -> list[ast.expr]:
    """Elements of a module-level ``pytestmark = [...]`` (or the single mark)."""
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "pytestmark" for t in node.targets):
            return list(node.value.elts) if isinstance(node.value, ast.List | ast.Tuple) else [node.value]
    return []


def _marker_args(nodes: list[ast.expr], name: str) -> list[str]:
    """String arguments of ``pytest.mark.<name>(...)`` calls among ``nodes``."""
    found = []
    for node in nodes:
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == name:
            found += [arg.value for arg in node.args if isinstance(arg, ast.Constant) and isinstance(arg.value, str)]
    return found


def doc_sections() -> dict[str, str]:
    """docs/known-issues.md sections keyed by the KB id of their '### KB-nnn' heading."""
    text = KNOWN_ISSUES_DOC.read_text(encoding="utf-8")
    sections: dict[str, str] = {}
    for part in re.split(r"(?m)^### ", text)[1:]:
        match = re.match(r"(KB-\d{3,})\b", part)
        if match:
            sections[match.group(1)] = part
    return sections


@cache
def load_cli_conftest() -> ModuleType:
    """tests/cli/conftest.py as a standalone module (test modules cannot import each other with importlib mode).

    The module is registered in sys.modules under a private name before it runs: dataclasses resolve the string
    annotations of ``from __future__ import annotations`` through it.
    """
    name = "otterdog_e2e_cli_conftest_under_test"
    spec = importlib.util.spec_from_file_location(name, CLI_CONFTEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


# --- scenario files ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("directory", LIVE_DIRS)
def test_every_scenario_file_loads(directory: str) -> None:
    """load_scenarios accepts every file of the directory (strict model: keys, fragments, secrets, templates)."""
    files = scenario_files(SCENARIOS / directory)
    assert files, f"scenarios/{directory} holds no scenario"
    scenarios = load_scenarios(SCENARIOS / directory)
    assert len(scenarios) == len(files)
    expected_tier = "enterprise" if directory == "enterprise" else "cli"
    assert {scenario.tier for scenario in scenarios} == {expected_tier}


def test_scenario_ids_are_unique_across_every_scenario_directory() -> None:
    """No live scenario id is reused by another live file nor by a file of another tier."""
    ids = [scenario.id for scenario in live_scenarios()]
    assert len(ids) == len(set(ids))
    clashes = [(scenario_id, str(path)) for scenario_id, path in other_scenario_ids() if scenario_id in ids]
    assert not clashes, clashes


def tier_dir(scenario: Scenario) -> str:
    """The directory right below scenarios/ holding the scenario file (subdirectories group files by topic)."""
    return scenario.source.relative_to(SCENARIOS).parts[0]


def test_scenario_ids_follow_the_directory_convention() -> None:
    """cli/ -> 'cli.', regressions/ -> 'regression.<pr>-', enterprise/ -> 'enterprise.' (subdirectories included)."""
    prefixes = {"cli": "cli.", "regressions": "regression.", "enterprise": "enterprise."}
    for scenario in live_scenarios():
        assert scenario.id.startswith(prefixes[tier_dir(scenario)]), (scenario.id, scenario.source)


def test_spec_catalogue_is_implemented() -> None:
    """Every SPEC 19 CLI/enterprise catalogue entry exists with its priority (Python ones as scenario markers)."""
    by_id = scenarios_by_id()
    for entry, (scenario_id, priority) in CATALOGUE.items():
        assert scenario_id in by_id, f"{entry}: scenario {scenario_id} is missing"
        assert by_id[scenario_id].priority == priority, (entry, by_id[scenario_id].priority)
    markers = python_markers()["scenario"]
    missing = {entry: scenario_id for entry, scenario_id in PYTHON_CATALOGUE.items() if scenario_id not in markers}
    assert not missing, f"Python catalogue entries without a test: {missing}"


def test_enterprise_scenarios_need_the_enterprise_plan() -> None:
    """scenarios/enterprise: min_plan enterprise (plan mark), and nothing else asks for enterprise."""
    for scenario in live_scenarios():
        if scenario.tier == "enterprise":
            assert scenario.min_plan == "enterprise", scenario.id
        else:
            assert scenario.min_plan in PLANS and scenario.min_plan != "enterprise", scenario.id


def test_regressions_document_the_pr_and_the_known_bad_version() -> None:
    """Every regression names its upstream PR/issue (tag pr-<n> and a link) and the known-bad version."""
    for scenario in live_scenarios():
        if tier_dir(scenario) != "regressions":
            continue
        numbers = [tag.removeprefix("pr-") for tag in scenario.tags if tag.startswith("pr-")]
        assert numbers, f"{scenario.id}: no pr-<number> tag"
        assert "regression" in scenario.tags, scenario.id
        assert scenario.id.split(".", 1)[1].startswith(numbers[0]), (scenario.id, numbers)
        for number in numbers:
            assert re.search(rf"otterdog/(pull|issues)/{number}\b", scenario.description), (scenario.id, number)
        assert "Known-bad" in scenario.description, f"{scenario.id}: no known-bad version in the description"


def test_scenarios_use_the_selection_tag_vocabulary() -> None:
    """At least one model-area tag of selection.SCENARIO_TAGS, so path-based selection (pr lane) finds them."""
    for scenario in live_scenarios():
        assert MODEL_TAGS & set(scenario.tags), f"{scenario.id}: tags {scenario.tags} have no model area"


def test_known_bug_scenarios_are_tagged_and_low_priority() -> None:
    """Scenarios linked to a known bug carry the 'known-bug' tag and are never P0 (their failure is expected)."""
    for scenario in live_scenarios():
        if scenario.known_bug is not None:
            assert "known-bug" in scenario.tags, scenario.id
            assert scenario.priority != "P0", scenario.id


def test_created_objects_carry_the_run_prefix() -> None:
    """Every repository/team/org object/secret/variable a fragment names starts with the run prefix (e2e-<run>- or
    E2E_<RUN>_): cleanup (guarded apply -d) and the janitor only ever remove such objects."""
    problems = []
    for scenario in live_scenarios():
        for step, snippet in rendered_snippets(scenario):
            assert "orgs.extendRepo(" not in snippet, f"{scenario.id}/{step}: extendRepo would modify a baseline repo"
            for constructor, _, name in _CONSTRUCTOR_RE.findall(snippet):
                if constructor in NAMED_CONSTRUCTORS and not is_e2e_name(name):
                    problems.append(f"{scenario.id}/{step}: {constructor}({name!r})")
    assert not problems, problems


def test_webhook_urls_lie_under_the_hook_base() -> None:
    """Webhook URLs (and their aliases) use {{ hook_base }}: https://otterdog-e2e.invalid/<run>/... (never a server)."""
    problems = []
    for scenario in live_scenarios():
        for step, snippet in rendered_snippets(scenario):
            urls = [
                name for constructor, _, name in _CONSTRUCTOR_RE.findall(snippet) if constructor in URL_CONSTRUCTORS
            ]
            for aliases in _ALIASES_RE.findall(snippet):
                urls += [value for _, value in _QUOTED_RE.findall(aliases) if "://" in value]
            problems += [f"{scenario.id}/{step}: {url}" for url in urls if not url.startswith(SAMPLE_RUN.hook_base)]
    assert not problems, problems


def test_probes_point_at_existing_steps() -> None:
    """tests/cli/conftest.py PROBES: each scenario exists and has the probe's step."""
    module = load_cli_conftest()
    by_id = scenarios_by_id()
    assert module.PROBES, "no probe registered"
    for scenario_id, probe in module.PROBES.items():
        assert scenario_id in by_id, scenario_id
        assert probe.after in [step.name for step in by_id[scenario_id].steps], (scenario_id, probe.after)


def test_webhook_probe_matches_the_scenario() -> None:
    """The webhook probe looks for repo <prefix>-hooks and hook <hook_base>repo-hook, which the update step keeps."""
    scenario = scenarios_by_id()["cli.repo.webhook"]
    snippets = [snippet for step, snippet in rendered_snippets(scenario) if step == "update"]
    assert any(f"orgs.newRepo('{SAMPLE_RUN.prefix}-hooks')" in snippet for snippet in snippets)
    assert any(f"orgs.newRepoWebhook('{SAMPLE_RUN.hook_base}repo-hook')" in snippet for snippet in snippets)


def test_long_scenarios_get_an_extended_timeout() -> None:
    """The probe scenario declares the tier timeout + its probe budget; org_level scenarios (full reset as cleanup)
    get collect.ORG_LEVEL_EXTRA_TIMEOUT on top of the tier timeout; the others the tier timeout."""
    module = load_cli_conftest()
    by_id = scenarios_by_id()
    webhook = by_id["cli.repo.webhook"]
    assert webhook.id in module.PROBES and webhook.timeout is not None
    budget = module.HOOK_LOOKUP_TIMEOUT + module.HOOK_DELIVERY_TIMEOUT
    assert scenario_timeout(webhook) == webhook.timeout >= TIER_TIMEOUTS["cli"] + budget
    for scenario in live_scenarios():
        if scenario.timeout is not None:
            continue
        expected = TIER_TIMEOUTS[scenario.tier] + (ORG_LEVEL_EXTRA_TIMEOUT if scenario.org_level else 0)
        assert scenario_timeout(scenario) == expected, scenario.id
    assert {s.id for s in live_scenarios() if s.timeout is not None} <= set(module.PROBES), "unexplained timeouts"


UNRELEASED_FIXES = {  # scenario -> first otterdog version with the change it asserts (v1.6.1 + n commits on main)
    "regression.767-code-scanning-new-repo": "1.7.0.dev2",
    "regression.791-731-private-repo": "1.7.0.dev14",
    "regression.790-repo-ruleset-without-strict": "1.7.0.dev15",
    "regression.779-user-bypass-actors": "1.7.0.dev7",
    "enterprise.org-ruleset.790-missing-strict": "1.7.0.dev15",  # #790 behaviour (BAT-05: KB-008 needs #790)
}


def test_unreleased_regressions_skip_on_older_suts() -> None:
    """Regressions of fixes merged after v1.6.1 (fixed_in) skip on release:latest (1.6.1) and run on main/PR
    builds; no other live scenario declares fixed_in."""
    by_id = scenarios_by_id()
    for scenario_id, version in UNRELEASED_FIXES.items():
        scenario = by_id[scenario_id]
        assert scenario.fixed_in == version, scenario_id
        assert fixed_in_skip_reason(scenario, "1.6.1"), scenario_id
        assert fixed_in_skip_reason(scenario, "1.7.0.dev15+e2e.g9bdeb75") is None, scenario_id
        assert fixed_in_skip_reason(scenario, "1.7.0.dev19+e2e.gd0d3b08.dirty.1a2b3c4d") is None, scenario_id
        assert fixed_in_skip_reason(scenario, "1.7.0") is None, scenario_id
        assert fixed_in_skip_reason(scenario, None) is None, scenario_id  # unknown version: run it
    others = [s for s in live_scenarios() if s.id not in UNRELEASED_FIXES]
    assert not [s.id for s in others if s.fixed_in is not None]


def test_split_scenario_keeps_every_step_once() -> None:
    """The probe split gives the steps up to the probe step, then the rest (declarative steps stay valid)."""
    module = load_cli_conftest()
    scenario = scenarios_by_id()["cli.repo.webhook"]
    head, tail = module.split_scenario(scenario, "update")
    assert [step.name for step in head.steps] == ["create", "update"]
    assert [step.name for step in tail.steps] == ["remove-hook"]
    assert head.id == tail.id == scenario.id
    with pytest.raises(ValueError, match="no step"):
        module.split_scenario(scenario, "missing")


def manifest(text: str, root: Path) -> dict[str, Any]:
    """Manifest a rendered org config with the local jsonnet binary against the vendored template copy."""
    org_dir = root / "orgs" / FAKE_ORG
    if not (org_dir / "vendor" / "template").is_dir():
        shutil.copytree(TEMPLATE_DIR, org_dir / "vendor" / "template")
    config = org_dir / f"{FAKE_ORG}.jsonnet"
    config.write_text(text, encoding="utf-8")
    completed = procs.run([str(JSONNET), config.name], cwd=org_dir, timeout=60, home=root / "home")
    assert completed.returncode == 0, completed.stderr[-2000:]
    data: dict[str, Any] = json.loads(completed.stdout)
    return data


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
def test_every_step_renders_and_manifests(tmp_path: Path) -> None:
    """Every step of every live scenario renders with the real renderer (baseline of a fake target, hidden cache
    limit) and evaluates with jsonnet; the repositories and teams it declares are in the manifested org and the org
    description keeps the safety marker. (Validation against otterdog itself runs offline in the scratch checks.)"""
    target = make_target()
    for scenario in live_scenarios():
        plan = "enterprise" if scenario.tier == "enterprise" else "free"
        renderer = OrgConfigRenderer(
            template=offline_template(),
            org=FAKE_ORG,
            plan=plan,
            org_profile=org_profile(default_org_json(plan=plan)),
            baseline=build_baseline(target, SAMPLE_RUN),
            marker=FAKE_MARKER,
            hide_cache_limit=True,
        )
        variables = sample_variables(scenario)
        for step in scenario.steps:
            rendered = render_step(step, variables)
            org = manifest(renderer.render(rendered.fragments, plan=scenario.plan_override), tmp_path)
            where = f"{scenario.id}/{step.name}"
            assert FAKE_MARKER in org["settings"]["description"], where
            assert org["settings"]["plan"] == (scenario.plan_override or plan), where
            snippets = [snippet for snippets in rendered.fragments.to_mapping().values() for snippet in snippets]
            declared = {
                name for snippet in snippets for kind, _, name in _CONSTRUCTOR_RE.findall(snippet) if kind == "newRepo"
            }
            repos = {repo["name"] for repo in org["repositories"]}
            assert declared <= repos, (where, sorted(declared - repos))
            teams = {
                name for snippet in snippets for kind, _, name in _CONSTRUCTOR_RE.findall(snippet) if kind == "newTeam"
            }
            assert teams <= {team["name"] for team in org["teams"]}, where


PRIVATE_ADD_FIXED_IN = "1.7.0.dev14"  # #791 (b5f7bb1): first otterdog that creates private repos without Code Security


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
def test_private_repositories_are_never_created_by_their_first_apply(tmp_path: Path) -> None:
    """BAT-01: otterdog before 1.7.0.dev14 sends the code scanning default setup PATCH (state not-configured) after
    creating ANY repository, which GitHub refuses for a private repository without Code Security (Free, and Team or
    Enterprise without it): the apply fails. A live scenario that runs on release:latest therefore creates its
    repositories public and makes them private in a later step (cli.repo.visibility); only scenarios that skip such
    SUTs (fixed_in >= 1.7.0.dev14, e.g. regression.791-731-private-repo) may create a private repository directly."""
    from otterdog_e2e.sut.version import predates

    target = make_target()
    problems = []
    for scenario in live_scenarios():
        if scenario.fixed_in and not predates(scenario.fixed_in, PRIVATE_ADD_FIXED_IN):
            continue
        plan = "enterprise" if scenario.tier == "enterprise" else "free"
        renderer = OrgConfigRenderer(
            template=offline_template(),
            org=FAKE_ORG,
            plan=plan,
            org_profile=org_profile(default_org_json(plan=plan)),
            baseline=build_baseline(target, SAMPLE_RUN),
            marker=FAKE_MARKER,
            hide_cache_limit=True,
        )
        variables = sample_variables(scenario)
        existing: set[str] = set()
        for step in scenario.steps:
            rendered = render_step(step, variables)
            org = manifest(renderer.render(rendered.fragments, plan=scenario.plan_override), tmp_path)
            repos = {repo["name"]: repo for repo in org["repositories"] if is_e2e_name(repo["name"])}
            applies = rendered.plan is not None and rendered.plan.expect == "changes" and rendered.apply is not None
            if applies:
                problems += [
                    f"{scenario.id}/{step.name}: creates the private repository {name}"
                    for name, repo in repos.items()
                    if name not in existing and repo.get("private") is True
                ]
                existing = set(repos)
    assert not problems, problems


# --- known bugs -------------------------------------------------------------------------------------------------------
def test_known_bugs_file_loads_with_the_spec_seed() -> None:
    """known_bugs.yaml loads (unique ids, known keys and statuses) and keeps every SPEC 12.5 seed entry."""
    bugs = known_bugs()
    missing = [bug_id for bug_id in SEED_IDS if bug_id not in bugs]
    assert not missing, missing
    assert {bug.status for bug in bugs.values()} <= {"suspected", "confirmed", "fixed"}
    raw = yaml.safe_load(KNOWN_BUGS.read_text(encoding="utf-8"))
    assert [item["id"] for item in raw] == sorted(item["id"] for item in raw), "keep the entries sorted by id"


def test_known_bug_evidence_is_precise() -> None:
    """Evidence entries are path:line[-line] (otterdog repository paths), 'chart: ...', 'openapi: ...' or
    'e2e: <existing file of this project> (note)'."""
    for bug in known_bugs().values():
        assert bug.evidence, f"{bug.id} has no evidence"
        for item in bug.evidence:
            match = _EVIDENCE_RE.match(item)
            if match is None:
                e2e = _E2E_EVIDENCE_RE.match(item)
                if e2e is not None:
                    assert (ROOT / e2e.group("path")).is_file(), (bug.id, item)
                    continue
                assert _CHART_EVIDENCE_RE.match(item) or _OPENAPI_EVIDENCE_RE.match(item), (bug.id, item)
                continue
            end = match.group("end")
            assert end is None or int(end) >= int(match.group("start")), (bug.id, item)


def test_fixed_bugs_name_the_fixing_version() -> None:
    """status fixed requires fixed_in (and a fix never stays 'suspected' with fixed_in set)."""
    for bug in known_bugs().values():
        assert (bug.status == "fixed") == (bug.fixed_in is not None), bug.id


def test_known_bug_scenarios_exist() -> None:
    """Every scenario listed by a known bug is a YAML scenario or the scenario(id) marker of a Python e2e test."""
    yaml_ids = set(scenarios_by_id()) | {scenario_id for scenario_id, _ in other_scenario_ids()}
    python_ids = set(python_markers()["scenario"])
    for bug in known_bugs().values():
        unknown = [name for name in bug.scenarios if name not in yaml_ids | python_ids]
        assert not unknown, f"{bug.id} lists unknown scenarios {unknown}"


def test_scenario_known_bugs_exist_and_link_back() -> None:
    """A scenario's known_bug exists in known_bugs.yaml and the bug lists the scenario."""
    bugs = known_bugs()
    for scenario in live_scenarios():
        if scenario.known_bug is None:
            continue
        assert scenario.known_bug in bugs, f"{scenario.id}: unknown known bug {scenario.known_bug}"
        assert scenario.id in bugs[scenario.known_bug].scenarios, f"{scenario.known_bug} does not list {scenario.id}"


def test_python_known_bug_markers_exist_and_link_back() -> None:
    """known_bug(...) markers of Python e2e tests (offline included) exist and the bug lists the test's scenario id."""
    bugs = known_bugs()
    for bug_id, scenario_ids in python_markers()["known_bug"].items():
        assert bug_id in bugs, f"unknown known bug {bug_id} in a Python e2e test"
        assert scenario_ids, f"the test marked {bug_id} has no scenario(id) marker"
        assert scenario_ids <= set(bugs[bug_id].scenarios), (bug_id, scenario_ids)


def test_every_linked_bug_has_a_test() -> None:
    """Every scenario id a bug lists belongs to a scenario/test that declares the same bug (no dangling links)."""
    by_id = scenarios_by_id()
    python = python_markers()["known_bug"]
    other_tiers = {scenario_id for scenario_id, _ in other_scenario_ids()}
    for bug in known_bugs().values():
        for name in bug.scenarios:
            if name in other_tiers:
                continue  # offline/differential scenarios: their own tier checks their known_bug field
            if name in by_id:
                assert by_id[name].known_bug == bug.id, (bug.id, name)
            else:
                assert name in python.get(bug.id, set()), (bug.id, name)


def test_known_issues_doc_mirrors_the_registry() -> None:
    """docs/known-issues.md has one '### KB-nnn' section per bug, with its status; confirmed ones give a
    reproduction, linked scenarios are named."""
    sections = doc_sections()
    for bug in known_bugs().values():
        assert bug.id in sections, f"docs/known-issues.md has no section for {bug.id}"
        section = sections[bug.id]
        assert f"Status: **{bug.status}**" in section, f"{bug.id}: status {bug.status} not stated"
        if bug.status == "confirmed":
            assert "Reproduction" in section, f"{bug.id} is confirmed but documents no reproduction"
        for name in bug.scenarios:
            assert f"`{name}`" in section, f"{bug.id}: scenario {name} not named in the doc"
    extra = sorted(set(sections) - set(known_bugs()))
    assert not extra, f"docs/known-issues.md documents unknown bugs {extra}"


def load_test_module(relative: str) -> ModuleType:
    """A tests/cli module as a standalone module (like load_cli_conftest)."""
    name = "otterdog_e2e_" + relative.replace("/", "_").removesuffix(".py") + "_under_test"
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_import_round_trip_tolerates_kb024_only() -> None:
    """BAT-07: the import tests tolerate exactly KB-024 (its error alone, not on enterprise) and neutralize only that
    key; any other validation error fails them."""
    module = load_test_module("tests/cli/test_import.py")
    error = "enabling 'members_can_create_private_pages' requires an 'enterprise' plan."
    assert module.kb024_only([error], "free") and module.kb024_only([error], "team")
    assert not module.kb024_only([error], "enterprise")
    assert not module.kb024_only([error, "repository 'x' has invalid topics"], "free")
    assert not module.kb024_only(["repository 'x' has invalid topics"], "free") and not module.kb024_only([], "free")
    text = "settings+: {\n  members_can_create_private_pages: true,\n  members_can_create_public_pages: true,\n}"
    new, count = module.PRIVATE_PAGES_RE.subn("members_can_create_private_pages:: null", text)
    assert count == 1 and "members_can_create_private_pages:: null," in new and "public_pages: true" in new
    assert issubclass(module.PrivatePagesNotAllowedError, AssertionError)
