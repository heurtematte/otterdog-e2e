"""Coverage matrix of otterdog's features against the e2e battery (scenarios/coverage.yaml, docs/coverage-matrix.md).

scenarios/coverage.yaml is the machine-readable inventory of what otterdog (main @9bdeb75) can do: CLI commands and
flags, every property of the configuration model grouped into features, validation rules, diff semantics, the webapp
(webhook events, comment commands, tasks, auto-merge, apply, blueprints, policies, /api and /internal) and notable
CHANGELOG fixes. Each feature says which existing scenario ids (scenarios/{offline,cli,regressions,enterprise}) or
pytest node ids (tests/<tier>/...::test_x) cover it, and gaps carry an outline precise enough to write the missing test.

These tests keep the file honest:

* strict schema (keys, types, enums, unique dotted ids, status rules: covered/partial need covering items,
  partial/gap need a gap outline, gap has none);
* every covered_by item exists (scenario ids through the scenarios loader, node ids through the test file's AST) and
  is not a harness unit test;
* exhaustiveness: every property of every constructor of otterdog's example template (the vendored copy in
  tests/unit/data/template, identical to examples/template at 9bdeb75) belongs to a feature, and the inventory keys
  (CLI commands, webhook events, comment commands, tasks, endpoints, pages, blueprint and policy types, comment
  markers, statuses, receiver checks) match EXPECTED_INVENTORY;
* docs/coverage-matrix.md is exactly what render_markdown() produces.

After editing the YAML, regenerate the documentation:

    .venv/bin/python tests/unit/test_coverage_matrix.py --write

Coverage per area (also printed by ``pytest tests/unit/test_coverage_matrix.py -s -k summary``):

    .venv/bin/python tests/unit/test_coverage_matrix.py
"""

from __future__ import annotations

import ast
import re
import sys
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from otterdog_e2e.known_bugs import load as load_known_bugs
from otterdog_e2e.scenarios.collect import collect_scenarios

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / "scenarios" / "coverage.yaml"
DOC = ROOT / "docs" / "coverage-matrix.md"
TEMPLATE = ROOT / "tests" / "unit" / "data" / "template" / "otterdog-defaults.libsonnet"
KNOWN_BUGS = ROOT / "scenarios" / "known_bugs.yaml"
SCENARIO_DIRS = ("offline", "cli", "regressions", "enterprise")
REGENERATE = ".venv/bin/python tests/unit/test_coverage_matrix.py --write"

TOP_KEYS = (
    "schema_version",
    "title",
    "description",
    "otterdog",
    "areas",
    "tiers",
    "operations",
    "models",
    "findings",
    "features",
)
FEATURE_KEYS = (
    "id",
    "area",
    "title",
    "source",
    "model",
    "properties",
    "inventory",
    "operations",
    "min_plan",
    "tier",
    "ui_only",
    "priority",
    "status",
    "covered_by",
    "known_bugs",
    "findings",
    "notes",
    "gap_outline",
    "verified_on",
)
REQUIRED_FEATURE_KEYS = (
    "id",
    "area",
    "title",
    "source",
    "operations",
    "min_plan",
    "tier",
    "ui_only",
    "priority",
    "status",
    "covered_by",
)
VERIFIED_KEYS = ("target", "sut", "run", "date")  # a green live run of the covering items (verified_on entries)
VERIFIED_RE = {
    "target": re.compile(r"^[a-z][a-z0-9_-]*$"),
    "sut": re.compile(r"^\S+$"),
    "run": re.compile(r"^[0-9a-z]{6}[0-9a-f]{2}$"),
    "date": re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]$"),
}
OUTLINE_KEYS = ("scenario", "file", "steps", "assertions", "needs")
REQUIRED_OUTLINE_KEYS = ("scenario", "steps", "assertions", "needs")
MODEL_KEYS = ("id", "constructor", "source", "extends", "nested", "extra")
FINDING_KEYS = ("id", "title", "source", "verified", "suggestion")
AREA_KEYS = ("id", "title")

STATUSES = ("covered", "partial", "gap")
PRIORITIES = ("P0", "P1", "P2")
PLANS = ("free", "team", "enterprise")
TIERS = ("offline", "cli", "webhooks", "webapp", "web_ui", "enterprise")
# tests/<dir> of the pytest node ids that may cover a feature (tests/unit only tests the harness itself)
NODE_DIRS = ("offline", "cli", "webhooks", "webapp", "enterprise", "differential", "web_ui")

FEATURE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9_-]*)+$")
AREA_ID_RE = re.compile(r"^[a-z][a-z0-9-]*$")
FINDING_ID_RE = re.compile(r"^F-[0-9]{2,}$")
KNOWN_BUG_RE = re.compile(r"^KB-[0-9]{3,}$")
# otterdog repository paths (or a prefixed external source such as "ws:" or "chart:") with a line or line range
SOURCE_RE = re.compile(r"^(?:[a-z]+:)?[A-Za-z0-9_.\-/]+:[0-9]+(-[0-9]+)?$")
NODE_ID_RE = re.compile(r"^tests/(?P<dir>[a-z_]+)/(?P<file>[A-Za-z0-9_/]+\.py)::(?P<path>[A-Za-z0-9_:]+)(\[.+\])?$")
INVENTORY_RE = re.compile(r"^(?P<kind>[a-z]+):(?P<value>\S.*)$")

# otterdog main @9bdeb75: what must be inventoried (keys of the features' ``inventory`` lists)
EXPECTED_INVENTORY: dict[str, tuple[str, ...]] = {
    # otterdog/cli.py:179-969 (29 subcommands; --version is a group option)
    "command": (
        "apply",
        "approve-blueprints",
        "canonical-diff",
        "check-status",
        "check-token-permissions",
        "delete-file",
        "dispatch-workflow",
        "fetch-config",
        "import",
        "install-app",
        "install-deps",
        "list-advisories",
        "list-apps",
        "list-blueprints",
        "list-members",
        "list-projects",
        "local-apply",
        "local-plan",
        "open-pr",
        "plan",
        "push-config",
        "review-permissions",
        "show",
        "show-default",
        "show-live",
        "sync-template",
        "uninstall-app",
        "validate",
        "web-login",
    ),
    # otterdog/webapp/webhook/__init__.py:74-420 (event/action pairs that schedule work)
    "event": (
        "pull_request/opened",
        "pull_request/synchronize",
        "pull_request/ready_for_review",
        "pull_request/converted_to_draft",
        "pull_request/reopened",
        "pull_request/closed",
        "pull_request_review/submitted",
        "pull_request_review/edited",
        "pull_request_review/dismissed",
        "issue_comment/created",
        "issue_comment/edited",
        "push",
        "installation/created",
        "installation/deleted",
        "installation/suspend",
        "installation/unsuspend",
        "workflow_job/queued",
        "workflow_run/completed",
    ),
    # otterdog/webapp/webhook/comment_handlers.py:48-176 (handler order of webhook/__init__.py:61-69)
    "comment": (
        "/otterdog help",
        "/otterdog team-info",
        "/otterdog check-sync",
        "/otterdog done",
        "/otterdog apply",
        "/otterdog merge",
        "/otterdog validate",
        "/otterdog validate info",
    ),
    # otterdog/webapp/tasks/**: TaskModel.type of every task class
    "task": (
        "ApplyChangesTask",
        "AutoMergeCommentTask",
        "CheckConfigurationInSyncTask",
        "CompletePullRequestTask",
        "DeleteBranchTask",
        "FetchAllPullRequestsTask",
        "FetchBlueprintsTask",
        "FetchConfigTask",
        "FetchPoliciesTask",
        "HelpCommentTask",
        "MergePullRequestTask",
        "RetrieveTeamMembershipTask",
        "UpdatePullRequestTask",
        "ValidatePullRequestTask",
        "CheckFilesTask",
        "PinWorkflowTask",
        "AppendConfigurationTask",
        "CheckScorecardIntegrationTask",
        "SyncScorecardResultTask",
        "UpdateBlueprintStatusTask",
        "UploadSBOMTask",
    ),
    # otterdog/webapp/api/routes.py:37-183, otterdog/webapp/internal/routes.py:33-106, webhook receiver
    "endpoint": (
        "GET /api/organizations",
        "GET /api/organizations/<github_id>",
        "GET /api/projects/<project_name>",
        "GET /api/tasks",
        "GET /api/pullrequests/open",
        "GET /api/pullrequests/merged",
        "GET /api/pullrequests/statistics/progress",
        "GET /api/blueprints/remediations",
        "GET /api/blueprints/dismissed",
        "GET /api/scorecard/results",
        "GET /api/graphql",
        "POST /api/graphql",
        "GET /internal/health",
        "GET /internal/init",
        "GET /internal/check",
        "GET /internal/check/<limit>",
        "GET /internal/<template>",
        "POST /github-webhook/receive",
    ),
    # otterdog/webapp/home/routes.py:50-532, otterdog/webapp/auth/routes.py:22-118
    "page": (
        "/",
        "/index",
        "/robots.txt",
        "/favicon.ico",
        "/myprojects",
        "/allprojects",
        "/query",
        "/organizations/<org>",
        "/organizations/<org>/<subpath>",
        "/projects/<project>",
        "/projects/<project>/defaults",
        "/projects/<project>/playground",
        "/projects/<project>/repos/<repo>",
        "/admin/organizations",
        "/admin/pullrequests",
        "/admin/blueprints",
        "/admin/policies",
        "/admin/tasks",
        "/scorecard/checks",
        "/<template>",
        "/login",
        "/github",
        "/github/authorized",
        "/logout",
    ),
    # otterdog/webapp/blueprints/__init__.py:30-34, otterdog/webapp/policies/__init__.py:24-26
    "blueprint": ("required_file", "pin_workflow", "append_configuration", "scorecard_integration"),
    "policy": ("dependency_track_upload", "macos_large_runners"),
    # first line of otterdog/webapp/templates/comment/*.txt
    "marker": ("help", "team-info", "validate", "check-sync", "automerge", "blueprint-dismissal"),
    # commit statuses: validate_pull_request.py:233-271, check_sync.py:214-257
    "status": (
        "validation/pending",
        "validation/success",
        "validation/error",
        "validation/failure",
        "sync/pending",
        "sync/success",
        "sync/success-out-of-sync",
        "sync/failure",
    ),
    # otterdog/webapp/webhook/github_webhook.py:63-121
    "receiver": (
        "missing-signature",
        "invalid-signature",
        "sha256-only",
        "missing-event",
        "missing-content-type",
        "json",
        "form",
        "unknown-content-type",
        "null-body",
        "accepted",
        "hook-exception",
    ),
}


# --- loading ---------------------------------------------------------------------------------------------------------
class _StrictLoader(yaml.SafeLoader):
    """SafeLoader refusing duplicate mapping keys."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Check the explicit keys of the mapping for duplicates, then construct it."""
        seen: set[Any] = set()
        for key_node, _ in node.value:
            key = self.construct_object(key_node, deep=True)
            if key in seen:
                raise yaml.constructor.ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


@cache
def matrix() -> dict[str, Any]:
    """scenarios/coverage.yaml (strict: duplicate keys refused)."""
    data = yaml.load(MATRIX.read_text(encoding="utf-8"), Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    assert isinstance(data, dict), f"{MATRIX} must hold a mapping"
    return data


def features() -> list[dict[str, Any]]:
    """The feature entries."""
    return list(matrix().get("features") or [])


@cache
def scenario_index() -> dict[str, str]:
    """Scenario id -> tier of every scenario of the tier directories (strict scenarios loader)."""
    scenarios = collect_scenarios([ROOT / "scenarios" / name for name in SCENARIO_DIRS])
    return {scenario.id: scenario.tier for scenario in scenarios}


@cache
def defined_tests(relative: str) -> frozenset[str]:
    """``name`` and ``Class::name`` of the test functions defined in a test module (empty when it does not exist)."""
    path = ROOT / relative
    if not path.is_file():
        return frozenset()
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.add(node.name)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                    found.add(f"{node.name}::{item.name}")
    return frozenset(found)


@cache
def scenario_gates() -> dict[str, tuple[bool, bool]]:
    """Scenario id -> (a scenario-level known bug: the whole item xfails while it exists; fixed_in: the scenario is
    skipped on SUTs that predate an unreleased fix, release:latest among them)."""
    bugs = load_known_bugs(KNOWN_BUGS)
    listed = {name for bug in bugs.values() if not bug.fixed for name in bug.scenarios}
    scenarios = collect_scenarios([ROOT / "scenarios" / name for name in SCENARIO_DIRS])
    return {s.id: (bool(s.known_bug) or s.id in listed, s.fixed_in is not None) for s in scenarios}


@cache
def known_bug_tests(relative: str) -> frozenset[str]:
    """Test functions of a module decorated with ``pytest.mark.known_bug(...)`` and no scoped
    ``pytest.mark.xfail(raises=...)``: the whole body is an expected failure while the bug exists (``name`` and
    ``Class::name``). A scoped xfail tolerates only its exception: the rest of the test stays strict."""
    path = ROOT / relative
    if not path.is_file():
        return frozenset()
    tree = ast.parse(path.read_text(encoding="utf-8"))

    def mark_calls(node: ast.FunctionDef | ast.AsyncFunctionDef, name: str) -> list[ast.Call]:
        """The ``<...>.<name>(...)`` decorators of a test function."""
        return [
            decorator
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == name
        ]

    def marked(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """True when the test is a known-bug test without a scoped xfail."""
        scoped = any(any(k.arg == "raises" for k in call.keywords) for call in mark_calls(node, "xfail"))
        return bool(mark_calls(node, "known_bug")) and not scoped

    found: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and marked(node):
            found.add(node.name)
        elif isinstance(node, ast.ClassDef):
            found.update(
                f"{node.name}::{item.name}"
                for item in node.body
                if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and marked(item)
            )
    return frozenset(found)


def strict_on_default_sut(item: str) -> bool:
    """True for a covering item that runs strictly on the default SUT: not a known-bug item, not gated by fixed_in."""
    if item in scenario_gates():
        known_bug, gated = scenario_gates()[item]
        return not known_bug and not gated
    match = NODE_ID_RE.match(item)
    if match is None:
        return True  # reference_problems reports it
    return match["path"] not in known_bug_tests(f"tests/{match['dir']}/{match['file']}")


def item_tier(item: str) -> str | None:
    """Tier of a covered_by item: the scenario's tier, or the tests/<dir> of a node id (None when unknown)."""
    if item in scenario_index():
        return scenario_index()[item]
    match = NODE_ID_RE.match(item)
    return match["dir"] if match else None


# --- the example template --------------------------------------------------------------------------------------------
_HEADER_RE = re.compile(r"^local (?P<name>\w+)\([^)]*\)\s*=\s*(?:(?P<base>\w+)\([^)]*\)\s*)?(?P<rest>[{;]?)")
_KEY_RE = re.compile(r"^\s*(?P<key>[A-Za-z_]\w*)\s*:{1,3}\s*(?P<rest>.*)$")


def template_keys(text: str) -> dict[str, set[str]]:
    """Keys of every constructor of the template, by path: ``newRepo``, ``newRepo.workflows``, ``newOrg.settings``,
    ``newOrg.settings.workflows``, ... (inherited keys included, e.g. newOrgRuleset has the keys of newRepoRuleset)."""
    keys: dict[str, set[str]] = {}
    bases: dict[str, str] = {}
    stack: list[str] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].rstrip()  # the template's comments start with '#'
        if not line.strip():
            continue
        if not stack:
            header = _HEADER_RE.match(line)
            if header is None:
                continue
            name = header["name"]
            keys.setdefault(name, set())
            if header["base"]:
                bases[name] = header["base"]
            if header["rest"] == "{":
                stack = [name]
            continue
        key = _KEY_RE.match(line)
        if key is not None:
            keys.setdefault(".".join(stack), set()).add(key["key"])
            rest = key["rest"].rstrip(",").strip()
            if rest.startswith("{") and not rest.endswith("}"):
                stack.append(key["key"])
                continue
        for _ in range(line.count("}") - line.count("{")):
            if stack:
                stack.pop()
    for _ in bases:  # one pass per base resolves chains of extensions
        for name, base in bases.items():
            for path, inherited in list(keys.items()):
                if path == base or path.startswith(f"{base}."):
                    keys.setdefault(name + path[len(base) :], set()).update(inherited)
    return keys


def model_keys(
    model: Mapping[str, Any], models: Mapping[str, Mapping[str, Any]], tpl: Mapping[str, set[str]]
) -> set[str]:
    """Template keys a model's features must list: its constructor's keys minus nested collections and the keys of
    the model it extends."""
    own = set(tpl.get(model["constructor"], set())) - set(model.get("nested") or [])
    base = model.get("extends")
    if base:
        own -= set(tpl.get(models[base]["constructor"], set()))
    return own


# --- validation -------------------------------------------------------------------------------------------------------
def _is_str_list(value: Any, *, allow_empty: bool = True) -> bool:
    """A list of non-empty strings (non-empty itself unless allow_empty)."""
    return (
        isinstance(value, list)
        and (allow_empty or len(value) > 0)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


def schema_problems(data: Mapping[str, Any]) -> list[str]:
    """Every structural problem of the matrix (empty list when it is valid)."""
    problems: list[str] = []
    unknown = sorted(set(data) - set(TOP_KEYS))
    missing = sorted(set(TOP_KEYS) - set(data))
    problems += [f"unknown top-level key {key!r}" for key in unknown]
    problems += [f"missing top-level key {key!r}" for key in missing]
    if missing:
        return problems
    if data["schema_version"] != 1:
        problems.append(f"schema_version must be 1, got {data['schema_version']!r}")

    areas = _list_of_mappings(data["areas"], "areas", AREA_KEYS, AREA_KEYS, problems)
    area_ids = [area.get("id") for area in areas]
    problems += [
        f"areas: invalid id {aid!r}" for aid in area_ids if not isinstance(aid, str) or not AREA_ID_RE.match(aid)
    ]
    problems += [f"areas: duplicate id {aid!r}" for aid, n in Counter(area_ids).items() if n > 1]
    for name, expected in (("tiers", TIERS), ("operations", None)):
        value = data[name]
        if not isinstance(value, dict) or not all(isinstance(v, str) and v for v in value.values()):
            problems.append(f"{name} must map ids to descriptions")
        elif expected is not None and tuple(value) != expected:
            problems.append(f"{name} must be exactly {list(expected)}, got {list(value)}")
    operations = set(data["operations"]) if isinstance(data["operations"], dict) else set()

    models = _list_of_mappings(data["models"], "models", MODEL_KEYS, ("id", "constructor", "source"), problems)
    model_ids = [model.get("id") for model in models]
    problems += [f"models: duplicate id {mid!r}" for mid, n in Counter(model_ids).items() if n > 1]
    for model in models:
        if model.get("extends") is not None and model["extends"] not in model_ids:
            problems.append(f"model {model.get('id')!r} extends unknown model {model['extends']!r}")
        for key in ("nested", "extra"):
            if key in model and not _is_str_list(model[key], allow_empty=False):
                problems.append(f"model {model.get('id')!r}: {key} must be a non-empty list of strings")
        if not isinstance(model.get("source"), str) or not SOURCE_RE.match(model["source"]):
            problems.append(f"model {model.get('id')!r}: invalid source {model.get('source')!r}")

    findings = _list_of_mappings(data["findings"], "findings", FINDING_KEYS, FINDING_KEYS, problems)
    finding_ids = [finding.get("id") for finding in findings]
    problems += [f"findings: duplicate id {fid!r}" for fid, n in Counter(finding_ids).items() if n > 1]
    for finding in findings:
        fid = finding.get("id")
        if not isinstance(fid, str) or not FINDING_ID_RE.match(fid):
            problems.append(f"findings: invalid id {fid!r}")
        if not _is_str_list(finding.get("source"), allow_empty=False) or not all(
            SOURCE_RE.match(s) for s in finding.get("source") or []
        ):
            problems.append(f"finding {fid!r}: source must be a non-empty list of path:line")
        for key in ("title", "verified", "suggestion"):
            if not isinstance(finding.get(key), str) or not finding[key].strip():
                problems.append(f"finding {fid!r}: {key} must be a non-empty string")

    entries = data["features"]
    if not isinstance(entries, list) or not entries:
        return [*problems, "features must be a non-empty list"]
    ids = [entry.get("id") if isinstance(entry, dict) else None for entry in entries]
    problems += [f"duplicate feature id {fid!r}" for fid, n in Counter(ids).items() if n > 1]
    for index, entry in enumerate(entries):
        problems += feature_problems(entry, index, set(area_ids), operations, set(model_ids), set(finding_ids))
    return problems


def _list_of_mappings(
    value: Any, where: str, allowed: Sequence[str], required: Sequence[str], problems: list[str]
) -> list[dict[str, Any]]:
    """The mappings of a list section (problems appended for non-mappings, unknown or missing keys)."""
    if not isinstance(value, list):
        problems.append(f"{where} must be a list")
        return []
    result = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            problems.append(f"{where}[{index}] must be a mapping")
            continue
        problems += [f"{where}[{index}]: unknown key {key!r}" for key in sorted(set(item) - set(allowed))]
        problems += [f"{where}[{index}]: missing key {key!r}" for key in required if key not in item]
        result.append(item)
    return result


def feature_problems(
    entry: Any, index: int, areas: set[str], operations: set[str], models: set[str], findings: set[str]
) -> list[str]:
    """Problems of one feature entry."""
    if not isinstance(entry, dict):
        return [f"features[{index}] must be a mapping"]
    fid = entry.get("id")
    where = f"feature {fid!r}" if isinstance(fid, str) else f"features[{index}]"
    problems = [f"{where}: unknown key {key!r}" for key in sorted(set(entry) - set(FEATURE_KEYS))]
    problems += [f"{where}: missing key {key!r}" for key in REQUIRED_FEATURE_KEYS if key not in entry]
    if problems:
        return problems
    checks: list[tuple[bool, str]] = [
        (isinstance(fid, str) and bool(FEATURE_ID_RE.match(fid)), f"invalid id {fid!r} (dotted lowercase)"),
        (entry["area"] in areas, f"unknown area {entry['area']!r}"),
        (isinstance(entry["title"], str) and bool(entry["title"].strip()), "title must be a non-empty string"),
        (
            _is_str_list(entry["source"], allow_empty=False) and all(SOURCE_RE.match(s) for s in entry["source"]),
            f"source must be a non-empty list of path:line, got {entry['source']!r}",
        ),
        (
            _is_str_list(entry["operations"], allow_empty=False) and set(entry["operations"]) <= operations,
            f"operations must be a non-empty list of {sorted(operations)}, got {entry['operations']!r}",
        ),
        (entry["min_plan"] in PLANS, f"min_plan must be one of {PLANS}"),
        (entry["tier"] in TIERS, f"tier must be one of {TIERS}"),
        (isinstance(entry["ui_only"], bool), "ui_only must be a boolean"),
        (entry["priority"] in PRIORITIES, f"priority must be one of {PRIORITIES}"),
        (entry["status"] in STATUSES, f"status must be one of {STATUSES}"),
        (_is_str_list(entry["covered_by"]), "covered_by must be a list of strings"),
        (not entry["ui_only"] or entry["tier"] == "web_ui", "ui_only features belong to tier web_ui"),
    ]
    problems += [f"{where}: {message}" for ok, message in checks if not ok]
    if "model" in entry or "properties" in entry:
        if entry.get("model") not in models:
            problems.append(f"{where}: model must be one of the models, got {entry.get('model')!r}")
        if not _is_str_list(entry.get("properties"), allow_empty=False):
            problems.append(f"{where}: a model feature needs a non-empty properties list")
    if "inventory" in entry and not (
        _is_str_list(entry["inventory"], allow_empty=False)
        and all(INVENTORY_RE.match(key) for key in entry["inventory"])
    ):
        problems.append(f"{where}: inventory must be a non-empty list of '<kind>:<value>'")
    if "known_bugs" in entry and not (
        _is_str_list(entry["known_bugs"], allow_empty=False) and all(KNOWN_BUG_RE.match(b) for b in entry["known_bugs"])
    ):
        problems.append(f"{where}: known_bugs must be a non-empty list of KB-nnn")
    if "findings" in entry and not (
        _is_str_list(entry["findings"], allow_empty=False) and set(entry["findings"]) <= findings
    ):
        problems.append(f"{where}: findings must reference the findings section, got {entry['findings']!r}")
    if "notes" in entry and not (isinstance(entry["notes"], str) and entry["notes"].strip()):
        problems.append(f"{where}: notes must be a non-empty string")
    problems += [f"{where}: {problem}" for problem in verified_problems(entry)]
    problems += [f"{where}: {problem}" for problem in status_problems(entry)]
    return problems


def verified_problems(entry: Mapping[str, Any]) -> list[str]:
    """``verified_on``: a non-empty list of {target, sut, run, date} of green live runs (BAT-13: live coverage counts
    as verified only once such a run is recorded); never on gaps or features without a live covering item."""
    if "verified_on" not in entry:
        return []
    runs = entry["verified_on"]
    if not isinstance(runs, list) or not runs:
        return ["verified_on must be a non-empty list of {target, sut, run, date}"]
    problems = []
    for index, run in enumerate(runs):
        if not isinstance(run, dict) or set(run) != set(VERIFIED_KEYS):
            problems.append(f"verified_on[{index}] must have exactly the keys {list(VERIFIED_KEYS)}")
            continue
        problems += [
            f"verified_on[{index}].{key}: invalid value {run[key]!r}"
            for key, pattern in VERIFIED_RE.items()
            if not isinstance(run[key], str) or not pattern.match(run[key])
        ]
    if entry["status"] == "gap" or not any(item_tier(item) not in (None, "offline") for item in entry["covered_by"]):
        problems.append("verified_on records live runs: the feature needs a live covering item")
    return problems


def status_problems(entry: Mapping[str, Any]) -> list[str]:
    """covered/partial need covering items, gap has none; partial/gap need an outline, covered has none; covered
    needs an item that runs strictly on the default SUT: not only known-bug items (XFAIL while the bug exists) or
    scenarios gated by ``fixed_in`` (skipped on release:latest) (BAT-13)."""
    status, covered_by, outline = entry["status"], entry["covered_by"], entry.get("gap_outline")
    problems = []
    if status in ("covered", "partial") and not covered_by:
        problems.append(f"status {status} needs at least one covered_by item")
    if status == "covered" and covered_by and not any(strict_on_default_sut(item) for item in covered_by):
        problems.append(
            "status covered needs an item that runs strictly on the default SUT (every item is a known-bug xfail "
            "or skipped on release:latest by fixed_in): use partial"
        )
    if status == "gap" and covered_by:
        problems.append("status gap must not list covered_by items (use partial)")
    if status == "covered" and outline is not None:
        problems.append("a covered feature has no gap_outline (use partial)")
    if status in ("partial", "gap"):
        if not isinstance(outline, dict):
            return [*problems, f"status {status} needs a gap_outline mapping"]
        problems += [f"gap_outline: unknown key {key!r}" for key in sorted(set(outline) - set(OUTLINE_KEYS))]
        problems += [f"gap_outline: missing key {key!r}" for key in REQUIRED_OUTLINE_KEYS if key not in outline]
        if not isinstance(outline.get("scenario"), str) or not outline["scenario"].strip():
            problems.append("gap_outline.scenario must name the suggested scenario or test id")
        if "file" in outline and not (
            isinstance(outline["file"], str) and outline["file"].startswith(("scenarios/", "tests/", "src/"))
        ):
            problems.append("gap_outline.file must be a path below scenarios/, tests/ or src/")
        for key in ("steps", "assertions", "needs"):
            if not _is_str_list(outline.get(key), allow_empty=False):
                problems.append(f"gap_outline.{key} must be a non-empty list of strings")
    return problems


def reference_problems(entries: Iterable[Mapping[str, Any]]) -> list[str]:
    """covered_by items that do not exist (scenario ids, node ids) or point to harness unit tests."""
    problems = []
    for entry in entries:
        for item in entry.get("covered_by") or []:
            if item in scenario_index():
                continue
            match = NODE_ID_RE.match(item)
            if match is None:
                problems.append(f"{entry['id']}: {item!r} is neither a scenario id nor a pytest node id")
                continue
            if match["dir"] not in NODE_DIRS:
                problems.append(f"{entry['id']}: {item!r} is not a test of an e2e tier {NODE_DIRS}")
                continue
            relative = f"tests/{match['dir']}/{match['file']}"
            if match["path"] not in defined_tests(relative):
                problems.append(f"{entry['id']}: {item!r} does not exist ({relative} defines no {match['path']})")
    return problems


# --- statistics and rendering ----------------------------------------------------------------------------------------
def counts(entries: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Number of features per status (all statuses present)."""
    found = Counter(entry["status"] for entry in entries)
    return {status: found.get(status, 0) for status in STATUSES}


def percent(entries: Sequence[Mapping[str, Any]], *, weighted: bool) -> float:
    """Share of covered features (weighted: a partial feature counts half)."""
    if not entries:
        return 0.0
    found = counts(entries)
    score = found["covered"] + (found["partial"] / 2 if weighted else 0)
    return 100.0 * score / len(entries)


def offline_verified(entry: Mapping[str, Any]) -> bool:
    """True when a covering item belongs to the offline tier (the only tier that has run against real SUTs)."""
    return any(item_tier(item) == "offline" for item in entry.get("covered_by") or [])


def live_verified(entry: Mapping[str, Any]) -> bool:
    """True when a green live run of the covering items is recorded (``verified_on``)."""
    return bool(entry.get("verified_on"))


def verification(entry: Mapping[str, Any]) -> str:
    """Verification cell of a covered or partial feature: offline and/or live (verified_on), else unverified."""
    if entry["status"] == "gap":
        return "-"
    kinds = [label for label, ok in (("offline", offline_verified(entry)), ("live", live_verified(entry))) if ok]
    return ", ".join(kinds) or "**unverified**"


def summary_rows(groups: Sequence[tuple[str, Sequence[Mapping[str, Any]]]]) -> list[list[str]]:
    """Rows of a summary table: label, features, covered, partial, gap, covered %, weighted %, offline-verified,
    live-verified (covered/partial features with a recorded green live run), unverified (neither)."""
    rows = []
    for label, entries in groups:
        found = counts(entries)
        claimed = [entry for entry in entries if entry["status"] != "gap"]
        rows.append(
            [
                label,
                str(len(entries)),
                str(found["covered"]),
                str(found["partial"]),
                str(found["gap"]),
                f"{percent(entries, weighted=False):.0f}%",
                f"{percent(entries, weighted=True):.0f}%",
                str(sum(1 for entry in claimed if offline_verified(entry))),
                str(sum(1 for entry in claimed if live_verified(entry))),
                str(sum(1 for entry in claimed if not offline_verified(entry) and not live_verified(entry))),
            ]
        )
    return rows


def area_groups(data: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], list[Mapping[str, Any]]]]:
    """(area, its features) in area order."""
    entries = list(data["features"])
    return [(area, [e for e in entries if e["area"] == area["id"]]) for area in data["areas"]]


def summary_text(data: Mapping[str, Any]) -> str:
    """Plain-text coverage per area (printed by the summary test and the script)."""
    groups = [(area["id"], entries) for area, entries in area_groups(data)]
    rows = [*summary_rows(groups), *summary_rows([("TOTAL", list(data["features"]))])]
    header = [
        "area",
        "features",
        "covered",
        "partial",
        "gap",
        "covered%",
        "weighted%",
        "offline-verified",
        "live-verified",
        "unverified",
    ]
    widths = [max(len(row[i]) for row in [header, *rows]) for i in range(len(header))]
    lines = [
        "  ".join(cell.ljust(widths[i]) if i == 0 else cell.rjust(widths[i]) for i, cell in enumerate(row))
        for row in [header, *rows]
    ]
    return "\n".join(lines) + "\n"


_MD_ESCAPES = str.maketrans({"<": "&lt;", ">": "&gt;", "*": "\\*", "~": "\\~"})


def _text(value: Any) -> str:
    """Free text as markdown: whitespace flattened; '<', '>', '*' and '~' escaped outside code spans (GitHub drops
    unknown tags such as '<org>' and turns '*' / '~' pairs into emphasis or strikethrough)."""
    parts = " ".join(str(value).split()).split("`")
    return "`".join(part if index % 2 else part.translate(_MD_ESCAPES) for index, part in enumerate(parts))


def heading_anchor(title: str) -> str:
    """The anchor GitHub gives a heading, and the documentation site too (toc slugify of mkdocs.yml): lower case,
    punctuation dropped, spaces as dashes."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def _cell(text: Any) -> str:
    """A markdown table cell (pipes escaped, newlines flattened)."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def _code_list(items: Iterable[str]) -> str:
    """Comma-separated code spans (or a dash)."""
    values = [f"`{item}`" for item in items]
    return ", ".join(values) if values else "-"


def _table(header: Sequence[str], rows: Iterable[Sequence[str]], align: str | None = None) -> list[str]:
    """Markdown table lines."""
    lines = ["| " + " | ".join(header) + " |", "|" + (align or "|".join("---" for _ in header)) + "|"]
    lines += ["| " + " | ".join(_cell(cell) for cell in row) + " |" for row in rows]
    return lines


def render_markdown(data: Mapping[str, Any]) -> str:
    """docs/coverage-matrix.md, generated from the matrix."""
    entries = list(data["features"])
    total = counts(entries)
    out = [
        "# Coverage matrix",
        "",
        "<!-- Generated from scenarios/coverage.yaml by tests/unit/test_coverage_matrix.py: do not edit by hand. -->",
        "",
        f"> Generated from [`scenarios/coverage.yaml`](../scenarios/coverage.yaml) (`{REGENERATE}`).",
        "> Edit the YAML, then regenerate: `tests/unit/test_coverage_matrix.py` fails when this file is stale.",
        "",
        data["title"].strip(),
        "",
        _text(data["description"]),
        "",
        (
            f"**{len(entries)} features** in {len(data['areas'])} areas: {total['covered']} covered, "
            f"{total['partial']} partial, {total['gap']} gaps; covered {percent(entries, weighted=False):.0f}%, "
            f"weighted {percent(entries, weighted=True):.0f}% (a partial feature counts half). "
            "*Offline-verified* counts the covered or partial features with at least one covering item in the offline "
            "tier; *live-verified* those with a recorded green live run of their covering items (`verified_on`: "
            "target, SUT, run id, date); *unverified* the others: their coverage is implemented but has never run, "
            "so it is a claim, not evidence. A covered feature needs at least one covering item that runs strictly "
            "on the default SUT (not only known-bug xfails or scenarios skipped by `fixed_in`)."
        ),
        "",
        "## Summary by area",
        "",
    ]
    header = [
        "Area",
        "Features",
        "Covered",
        "Partial",
        "Gap",
        "Covered %",
        "Weighted %",
        "Offline-verified",
        "Live-verified",
        "Unverified",
    ]
    align = "---|--:|--:|--:|--:|--:|--:|--:|--:|--:"
    groups = [(f"[{area['title']}](#{area['id']})", group) for area, group in area_groups(data)]
    out += _table(header, [*summary_rows(groups), *summary_rows([("**Total**", entries)])], align)
    out += ["", "## Summary by tier", ""]
    tier_groups = [(f"`{tier}`", [e for e in entries if e["tier"] == tier]) for tier in TIERS]
    out += _table(["Tier", *header[1:]], summary_rows(tier_groups), align)
    out += ["", "## Summary by priority", ""]
    prio_groups = [(prio, [e for e in entries if e["priority"] == prio]) for prio in PRIORITIES]
    out += _table(["Priority", *header[1:]], summary_rows(prio_groups), align)
    out += ["", "Tiers:", ""]
    out += [f"- `{tier}`: {_text(text)}" for tier, text in data["tiers"].items()]
    out += ["", "Operations:", ""]
    out += [f"- `{op}`: {_text(text)}" for op, text in data["operations"].items()]
    out += [
        "",
        "## New findings",
        "",
        "Defects found while building the inventory (not yet in `scenarios/known_bugs.yaml`):",
        "",
    ]
    rows = [
        [
            f"`{f['id']}`",
            _text(f["title"]),
            ", ".join(f"`{s}`" for s in f["source"]),
            _text(f["verified"]),
            _text(f["suggestion"]),
        ]
        for f in data["findings"]
    ]
    out += _table(["Id", "Finding", "Source", "Verified", "Suggestion"], rows)
    for area, group in area_groups(data):
        out += render_area(area, group)
    return "\n".join(out).rstrip("\n") + "\n"


def render_area(area: Mapping[str, Any], group: Sequence[Mapping[str, Any]]) -> list[str]:
    """The section of one area: a table of its features, then the details of notes, partials and gaps."""
    found = counts(group)
    out = [""]
    # the summary links to #<area id>: an explicit anchor when the heading's own anchor is another (never a duplicate id)
    if heading_anchor(area["title"]) != area["id"]:
        out += [f'<a id="{area["id"]}"></a>', ""]
    out += [
        f"## {area['title']}",
        "",
        (
            f"`{area['id']}`: {len(group)} features, {found['covered']} covered, {found['partial']} partial, "
            f"{found['gap']} gaps (weighted {percent(group, weighted=True):.0f}%)."
        ),
        "",
    ]
    rows = [
        [
            f"`{e['id']}`",
            _text(e["title"]) + (" (UI only)" if e["ui_only"] else ""),
            e["tier"],
            e["min_plan"],
            e["priority"],
            {"covered": "covered", "partial": "**partial**", "gap": "**gap**"}[e["status"]],
            verification(e),
            _code_list(e["covered_by"]),
        ]
        for e in group
    ]
    out += _table(["Id", "Feature", "Tier", "Plan", "Prio", "Status", "Verified", "Covered by"], rows)
    detailed = [
        e
        for e in group
        if e["status"] != "covered"
        or e.get("notes")
        or e.get("known_bugs")
        or e.get("findings")
        or e.get("verified_on")
    ]
    if detailed:
        out += ["", "Details:", ""]
    for e in detailed:
        out += render_details(e)
    return out


# nested bullets are indented by 4 spaces per level: GitHub accepts 2, but Python-Markdown (MkDocs, the documentation
# site) only nests a list indented by 4 and would flatten the details
LIST_INDENT = " " * 4


def render_details(e: Mapping[str, Any]) -> list[str]:
    """The detail bullet list of one feature."""
    out = [f"- **`{e['id']}`** ({e['status']}, {e['priority']}, `{e['tier']}`): {_text(e['title'])}"]
    out.append(f"{LIST_INDENT}- Source: {', '.join(f'`{s}`' for s in e['source'])}")
    if e.get("properties"):
        out.append(f"{LIST_INDENT}- Properties (`{e['model']}`): {', '.join(f'`{p}`' for p in e['properties'])}")
    out.append(f"{LIST_INDENT}- Operations: {', '.join(e['operations'])}")
    if e.get("known_bugs"):
        out.append(f"{LIST_INDENT}- Known bugs: {', '.join(e['known_bugs'])}")
    if e.get("findings"):
        out.append(f"{LIST_INDENT}- New findings: {', '.join(e['findings'])}")
    if e.get("notes"):
        out.append(f"{LIST_INDENT}- Notes: {_text(e['notes'])}")
    for run in e.get("verified_on") or []:
        out.append(
            f"{LIST_INDENT}- Verified on `{run['target']}` with `{run['sut']}`: run `{run['run']}` ({run['date']})"
        )
    outline = e.get("gap_outline")
    if outline:
        target = f"`{outline['scenario']}`" + (f" in `{outline['file']}`" if outline.get("file") else "")
        out.append(f"{LIST_INDENT}- Suggested: {target}")
        for label, key in (("Steps", "steps"), ("Assert", "assertions"), ("Needs", "needs")):
            out.append(f"{LIST_INDENT}- {label}:")
            out += [f"{LIST_INDENT * 2}- {_text(item)}" for item in outline[key]]
    return out


# --- tests -------------------------------------------------------------------------------------------------------------
def test_matrix_schema() -> None:
    """Keys, types, enums, unique ids and the status rules hold for every entry."""
    problems = schema_problems(matrix())
    assert not problems, "scenarios/coverage.yaml:\n" + "\n".join(problems)


def test_covered_by_items_exist() -> None:
    """Every covered_by item is a scenario id of the loader or an existing e2e test function."""
    problems = reference_problems(features())
    assert not problems, "\n".join(problems)


def test_known_bug_references_exist() -> None:
    """known_bugs entries of the features exist in scenarios/known_bugs.yaml."""
    bugs = load_known_bugs(KNOWN_BUGS)
    unknown = [(e["id"], bug) for e in features() for bug in e.get("known_bugs") or [] if bug not in bugs]
    assert not unknown, f"unknown known bugs: {unknown}"


def test_findings_are_referenced() -> None:
    """Every new finding is referenced by at least one feature (and only defined findings are referenced)."""
    referenced = {finding for e in features() for finding in e.get("findings") or []}
    defined = {finding["id"] for finding in matrix()["findings"]}
    assert defined <= referenced, f"findings no feature references: {sorted(defined - referenced)}"


def test_every_template_property_is_inventoried() -> None:
    """Each key of each constructor of otterdog's example template belongs to a feature of its model, and features only
    list template keys (or the model's declared extra, model-only fields)."""
    tpl = template_keys(TEMPLATE.read_text(encoding="utf-8"))
    models = {model["id"]: model for model in matrix()["models"]}
    missing_constructors = sorted(m["constructor"] for m in models.values() if m["constructor"] not in tpl)
    assert not missing_constructors, f"constructors not found in the template: {missing_constructors}"
    listed: dict[str, set[str]] = {}
    for e in features():
        if "model" in e:
            listed.setdefault(e["model"], set()).update(e["properties"])
    problems = []
    for mid, model in models.items():
        expected = model_keys(model, models, tpl)
        allowed = expected | set(model.get("extra") or [])
        have = listed.get(mid, set())
        problems += [f"{mid}: template key {key!r} belongs to no feature" for key in sorted(expected - have)]
        problems += [f"{mid}: {key!r} is neither a template key nor a declared extra" for key in sorted(have - allowed)]
        problems += [
            f"{mid}: extra field {key!r} belongs to no feature" for key in sorted(set(model.get("extra") or []) - have)
        ]
    assert not problems, "\n".join(problems)


def test_inventory_is_exhaustive() -> None:
    """The inventory keys of the features are exactly EXPECTED_INVENTORY (otterdog main @9bdeb75)."""
    keys: dict[str, set[str]] = {}
    for e in features():
        for key in e.get("inventory") or []:
            match = INVENTORY_RE.match(key)
            assert match, key
            keys.setdefault(match["kind"], set()).add(match["value"])
    problems = []
    for kind, expected in EXPECTED_INVENTORY.items():
        have = keys.get(kind, set())
        problems += [f"{kind}: {value!r} is inventoried by no feature" for value in expected if value not in have]
        problems += [f"{kind}: unknown {value!r}" for value in sorted(have - set(expected))]
    problems += [f"unknown inventory kind {kind!r}" for kind in sorted(set(keys) - set(EXPECTED_INVENTORY))]
    assert not problems, "\n".join(problems)


def test_coverage_summary() -> None:
    """Print the coverage per area (captured: ``-s`` shows it) and check the counts add up."""
    data = matrix()
    sys.stdout.write("\n" + summary_text(data))
    assert sum(counts(list(data["features"])).values()) == len(data["features"])


def test_markdown_is_up_to_date() -> None:
    """docs/coverage-matrix.md is the rendering of the matrix (regenerate it after editing the YAML)."""
    expected = render_markdown(matrix())
    current = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""
    assert current == expected, f"{DOC.relative_to(ROOT)} is stale, regenerate it: {REGENERATE}"


def test_covered_needs_an_item_that_runs_strictly_on_the_default_sut() -> None:
    """BAT-13: known-bug xfails (scenario-level bugs, unscoped known_bug tests) and fixed_in scenarios alone do not make
    a feature covered; a scoped known-bug test (xfail(raises=...)) and a plain scenario do."""
    assert not strict_on_default_sut("regression.779-user-bypass-actors")  # fixed_in 1.7.0.dev7
    assert strict_on_default_sut("cli.kb.team-permissions-removal")  # a step-level bug: the rest stays strict
    assert not strict_on_default_sut("cli.kb.variables-pagination")  # scenario-level KB-003
    assert not strict_on_default_sut("tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors")
    assert strict_on_default_sut("tests/webapp/test_commands.py::test_sync_check_crash")  # xfail(raises=...)
    assert strict_on_default_sut("cli.repo.visibility")
    entry = {"status": "covered", "covered_by": ["regression.779-user-bypass-actors"], "gap_outline": None}
    assert any("runs strictly on the default SUT" in problem for problem in status_problems(entry))


def test_verified_on_records_green_live_runs() -> None:
    """BAT-13: verified_on lists {target, sut, run, date} of live runs, only for features with a live item."""
    run = {"target": "free", "sut": "release:latest", "run": "t3c7z8a5", "date": "2026-10-03"}
    live = {"status": "covered", "covered_by": ["cli.repo.visibility"], "verified_on": [run]}
    assert verified_problems(live) == [] and live_verified(live) and verification(live) == "live"
    assert verified_problems({**live, "verified_on": []})
    assert verified_problems({**live, "verified_on": [{**run, "run": "latest"}]}) == [
        "verified_on[0].run: invalid value 'latest'"
    ]
    offline_only = {"status": "covered", "covered_by": ["O-VAL-OK"], "verified_on": [run]}
    assert verified_problems(offline_only) == ["verified_on records live runs: the feature needs a live covering item"]
    assert verification({"status": "covered", "covered_by": ["cli.repo.visibility"]}) == "**unverified**"


def test_template_parser_reads_nested_and_inherited_keys() -> None:
    """The template parser handles nested objects, inheritance and aliases (newRepoWebhook = newOrgWebhook)."""
    tpl = template_keys(TEMPLATE.read_text(encoding="utf-8"))
    assert {"max_cache_size_gb", "fork_pr_approval_policy", "enabled"} <= tpl["newRepo.workflows"]
    assert {"enabled_repositories", "selected_repositories"} <= tpl["newOrg.settings.workflows"]
    assert {"include_repo_names", "required_merge_queue", "bypass_actors"} <= tpl["newOrgRuleset"]
    assert tpl["newRepoWebhook"] == tpl["newOrgWebhook"]
    assert tpl["newEnvSecret"] == tpl["newRepoSecret"] == {"name", "value"}
    assert "workflows" in tpl["newOrg.settings"] and "plan" in tpl["newOrg.settings"]


def test_markdown_text_escapes_outside_code_spans() -> None:
    """Free text keeps code spans verbatim and escapes what GitHub would turn into tags, emphasis or strikethrough."""
    assert _text("a <org>  *x*\n`<y> *z*` ~w~") == "a &lt;org&gt; \\*x\\* `<y> *z*` \\~w\\~"
    assert _cell(_text("('a' | 'b')")) == "('a' \\| 'b')"


def main(argv: Sequence[str]) -> int:
    """``--write`` regenerates docs/coverage-matrix.md; without arguments, print the coverage per area."""
    data = matrix()
    if "--write" in argv:
        DOC.write_text(render_markdown(data), encoding="utf-8")
        sys.stdout.write(f"wrote {DOC.relative_to(ROOT)}\n")
    sys.stdout.write(summary_text(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
