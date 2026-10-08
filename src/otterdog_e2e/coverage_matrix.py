"""Validation and rendering of the coverage matrix (scenarios/coverage.yaml -> docs/coverage-matrix.md).

scenarios/coverage.yaml is the machine-readable inventory of what otterdog (main @9bdeb75) can do: CLI commands and
flags, every property of the configuration model grouped into features, validation rules, diff semantics, the webapp
and notable CHANGELOG fixes. Each feature says which existing scenario ids (scenarios/{offline,cli,enterprise}) or
pytest node ids (tests/<tier>/...::test_x) cover it, and gaps carry an outline precise enough to write the missing
test.

MatrixProject binds the checks to one otterdog-e2e checkout (its scenarios, test modules, known bugs, the vendored
example template and the generated documentation):

* strict schema (keys, types, enums, unique dotted ids, status rules: covered/partial need covering items,
  partial/gap need a gap outline, gap has none; covered needs an item that runs strictly on the default SUT);
* every covered_by item exists (scenario ids through the scenarios loader, node ids through the test file's AST) and
  is not a harness unit test; known bugs exist; every finding is referenced;
* exhaustiveness: every property of every constructor of otterdog's example template (the vendored copy in
  tests/unit/data/template) belongs to a feature, and the inventory keys match EXPECTED_INVENTORY;
* docs/coverage-matrix.md is exactly what render_markdown() produces.

tests/unit/test_coverage_matrix.py runs these checks (and ``--write`` regenerates the documentation); ``otterdog-e2e
assist check scenarios/coverage.yaml`` reports the same problems (MatrixProject.all_problems).
"""

from __future__ import annotations

import ast
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from functools import cached_property
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

if TYPE_CHECKING:
    from otterdog_e2e.known_bugs import KnownBug
    from otterdog_e2e.scenarios.model import Scenario

MATRIX_FILE = Path("scenarios") / "coverage.yaml"  # below the otterdog-e2e project root
DOC_FILE = Path("docs") / "coverage-matrix.md"
TEMPLATE_FILE = Path("tests") / "unit" / "data" / "template" / "otterdog-defaults.libsonnet"
KNOWN_BUGS_FILE = Path("scenarios") / "known_bugs.yaml"
SCENARIO_DIRS = ("offline", "cli", "enterprise")
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
AVAILABLE_PREFIX = "available:"  # a gap_outline need the harness already provides (docs/battery-guide.md)

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


class MatrixError(ValueError):
    """A coverage matrix file that cannot be read (invalid YAML, duplicate keys, not a mapping)."""


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


def load_matrix(path: Path) -> dict[str, Any]:
    """The coverage matrix of ``path`` (strict: duplicate keys refused); MatrixError when it is no YAML mapping."""
    try:
        data = yaml.load(path.read_text(encoding="utf-8"), Loader=_StrictLoader)  # noqa: S506 - SafeLoader subclass
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise MatrixError(f"{path}: cannot be read: {' '.join(str(exc).split())}") from None
    if not isinstance(data, dict):
        raise MatrixError(f"{path} must hold a mapping")
    return data


def outline_needs(outline: Mapping[str, Any] | None) -> tuple[list[str], list[str]]:
    """(available, missing) needs of a gap outline: a need starting with ``available:`` names what the harness already
    provides (prefix removed), the others are still missing."""
    available: list[str] = []
    missing: list[str] = []
    for need in (outline or {}).get("needs") or []:
        text = str(need).strip()
        if text.startswith(AVAILABLE_PREFIX):
            available.append(text[len(AVAILABLE_PREFIX) :].strip())
        else:
            missing.append(text)
    return available, missing


def source_path(source: str) -> str:
    """The otterdog path of a feature source (``path:line[-line]`` without the line part and a ``ws:`` prefix)."""
    path = re.sub(r":[0-9]+(?:-[0-9]+)?$", "", source.strip())
    return re.sub(r"^[a-z]+:", "", path)


# --- the checkout: scenarios, test modules, known bugs ---------------------------------------------------------------
class MatrixProject:
    """The coverage matrix of one otterdog-e2e checkout and what its checks look up there (scenario ids and tiers, the
    test functions of test modules, known-bug gates); every lookup is read once."""

    def __init__(self, root: Path) -> None:
        """Bind the checks to the project root (nothing is read yet)."""
        self.root = Path(root)
        self.matrix_path = self.root / MATRIX_FILE
        self.doc_path = self.root / DOC_FILE
        self.template_path = self.root / TEMPLATE_FILE
        self.known_bugs_path = self.root / KNOWN_BUGS_FILE
        self._tests: dict[str, frozenset[str]] = {}
        self._known_bug_tests: dict[str, frozenset[str]] = {}

    @cached_property
    def data(self) -> dict[str, Any]:
        """scenarios/coverage.yaml (strict: duplicate keys refused; MatrixError otherwise)."""
        return load_matrix(self.matrix_path)

    def features(self) -> list[dict[str, Any]]:
        """The feature entries."""
        return list(self.data.get("features") or [])

    @cached_property
    def scenarios(self) -> list[Scenario]:
        """Every scenario of the tier directories (strict scenarios loader: ScenarioError on any invalid file)."""
        from otterdog_e2e.scenarios.collect import collect_scenarios

        return collect_scenarios([self.root / "scenarios" / name for name in SCENARIO_DIRS])

    @cached_property
    def known_bugs(self) -> dict[str, KnownBug]:
        """scenarios/known_bugs.yaml by id."""
        from otterdog_e2e.known_bugs import load as load_known_bugs

        return load_known_bugs(self.known_bugs_path)

    def scenario_index(self) -> dict[str, str]:
        """Scenario id -> tier of every scenario of the tier directories."""
        return {scenario.id: scenario.tier for scenario in self.scenarios}

    def defined_tests(self, relative: str) -> frozenset[str]:
        """``name`` and ``Class::name`` of the test functions defined in a test module (empty when it does not exist)."""
        if relative not in self._tests:
            found: set[str] = set()
            tree = self._module(relative)
            for node in tree.body if tree is not None else ():
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                    found.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef):
                            found.add(f"{node.name}::{item.name}")
            self._tests[relative] = frozenset(found)
        return self._tests[relative]

    def _module(self, relative: str) -> ast.Module | None:
        """The parsed test module ``relative`` (None when it does not exist)."""
        path = self.root / relative
        return ast.parse(path.read_text(encoding="utf-8")) if path.is_file() else None

    @cached_property
    def scenario_gates(self) -> dict[str, tuple[bool, bool]]:
        """Scenario id -> (a scenario-level known bug: the whole item xfails while it exists; fixed_in: the scenario is
        skipped on SUTs that predate an unreleased fix, release:latest among them)."""
        listed = {name for bug in self.known_bugs.values() if not bug.fixed for name in bug.scenarios}
        return {s.id: (bool(s.known_bug) or s.id in listed, s.fixed_in is not None) for s in self.scenarios}

    def known_bug_tests(self, relative: str) -> frozenset[str]:
        """Test functions of a module decorated with ``pytest.mark.known_bug(...)`` and no scoped
        ``pytest.mark.xfail(raises=...)``: the whole body is an expected failure while the bug exists (``name`` and
        ``Class::name``). A scoped xfail tolerates only its exception: the rest of the test stays strict."""
        if relative not in self._known_bug_tests:
            found: set[str] = set()
            tree = self._module(relative)
            for node in tree.body if tree is not None else ():
                if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and _known_bug_test(node):
                    found.add(node.name)
                elif isinstance(node, ast.ClassDef):
                    found.update(
                        f"{node.name}::{item.name}"
                        for item in node.body
                        if isinstance(item, ast.FunctionDef | ast.AsyncFunctionDef) and _known_bug_test(item)
                    )
            self._known_bug_tests[relative] = frozenset(found)
        return self._known_bug_tests[relative]

    def strict_on_default_sut(self, item: str) -> bool:
        """True for a covering item that runs strictly on the default SUT: not a known-bug item, not gated by
        fixed_in."""
        if item in self.scenario_gates:
            known_bug, gated = self.scenario_gates[item]
            return not known_bug and not gated
        match = NODE_ID_RE.match(item)
        if match is None:
            return True  # reference_problems reports it
        return match["path"] not in self.known_bug_tests(f"tests/{match['dir']}/{match['file']}")

    def item_tier(self, item: str) -> str | None:
        """Tier of a covered_by item: the scenario's tier, or the tests/<dir> of a node id (None when unknown)."""
        index = self.scenario_index()
        if item in index:
            return index[item]
        match = NODE_ID_RE.match(item)
        return match["dir"] if match else None

    # --- validation --------------------------------------------------------------------------------------------------
    def schema_problems(self, data: Mapping[str, Any]) -> list[str]:
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
        area_ids: list[Any] = [area.get("id") for area in areas]
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
        model_ids: list[Any] = [model.get("id") for model in models]
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
        finding_ids: list[Any] = [finding.get("id") for finding in findings]
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
            problems += self.feature_problems(entry, index, set(area_ids), operations, set(model_ids), set(finding_ids))
        return problems

    def feature_problems(
        self, entry: Any, index: int, areas: set[str], operations: set[str], models: set[str], findings: set[str]
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
            _is_str_list(entry["known_bugs"], allow_empty=False)
            and all(KNOWN_BUG_RE.match(b) for b in entry["known_bugs"])
        ):
            problems.append(f"{where}: known_bugs must be a non-empty list of KB-nnn")
        if "findings" in entry and not (
            _is_str_list(entry["findings"], allow_empty=False) and set(entry["findings"]) <= findings
        ):
            problems.append(f"{where}: findings must reference the findings section, got {entry['findings']!r}")
        if "notes" in entry and not (isinstance(entry["notes"], str) and entry["notes"].strip()):
            problems.append(f"{where}: notes must be a non-empty string")
        problems += [f"{where}: {problem}" for problem in self.verified_problems(entry)]
        problems += [f"{where}: {problem}" for problem in self.status_problems(entry)]
        return problems

    def verified_problems(self, entry: Mapping[str, Any]) -> list[str]:
        """``verified_on``: a non-empty list of {target, sut, run, date} of green live runs (BAT-13: live coverage
        counts as verified only once such a run is recorded); never on gaps or features without a live covering item."""
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
        if entry["status"] == "gap" or not any(
            self.item_tier(item) not in (None, "offline") for item in entry["covered_by"]
        ):
            problems.append("verified_on records live runs: the feature needs a live covering item")
        return problems

    def status_problems(self, entry: Mapping[str, Any]) -> list[str]:
        """covered/partial need covering items, gap has none; partial/gap need an outline, covered has none; covered
        needs an item that runs strictly on the default SUT: not only known-bug items (XFAIL while the bug exists) or
        scenarios gated by ``fixed_in`` (skipped on release:latest) (BAT-13)."""
        status, covered_by, outline = entry["status"], entry["covered_by"], entry.get("gap_outline")
        problems = []
        if status in ("covered", "partial") and not covered_by:
            problems.append(f"status {status} needs at least one covered_by item")
        if status == "covered" and covered_by and not any(self.strict_on_default_sut(item) for item in covered_by):
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

    def reference_problems(self, entries: Iterable[Mapping[str, Any]]) -> list[str]:
        """covered_by items that do not exist (scenario ids, node ids) or point to harness unit tests."""
        problems = []
        index = self.scenario_index()
        for entry in entries:
            for item in entry.get("covered_by") or []:
                if item in index:
                    continue
                match = NODE_ID_RE.match(item)
                if match is None:
                    problems.append(f"{entry['id']}: {item!r} is neither a scenario id nor a pytest node id")
                    continue
                if match["dir"] not in NODE_DIRS:
                    problems.append(f"{entry['id']}: {item!r} is not a test of an e2e tier {NODE_DIRS}")
                    continue
                relative = f"tests/{match['dir']}/{match['file']}"
                if match["path"] not in self.defined_tests(relative):
                    problems.append(f"{entry['id']}: {item!r} does not exist ({relative} defines no {match['path']})")
        return problems

    def known_bug_problems(self) -> list[str]:
        """known_bugs entries of the features that scenarios/known_bugs.yaml does not define."""
        bugs = self.known_bugs
        return [
            f"{entry['id']}: unknown known bug {bug!r}"
            for entry in self.features()
            for bug in entry.get("known_bugs") or []
            if bug not in bugs
        ]

    def finding_problems(self) -> list[str]:
        """Findings no feature references (every new finding is referenced by at least one feature)."""
        referenced = {finding for entry in self.features() for finding in entry.get("findings") or []}
        defined = {finding["id"] for finding in self.data.get("findings") or [] if isinstance(finding, dict)}
        return [f"finding {finding!r} is referenced by no feature" for finding in sorted(defined - referenced)]

    def template_problems(self) -> list[str]:
        """Each key of each constructor of otterdog's example template belongs to a feature of its model, and features
        only list template keys (or the model's declared extra, model-only fields)."""
        tpl = template_keys(self.template_path.read_text(encoding="utf-8"))
        models = {model["id"]: model for model in self.data["models"]}
        problems = [
            f"constructor {constructor!r} of a model is not found in the template"
            for constructor in sorted(m["constructor"] for m in models.values() if m["constructor"] not in tpl)
        ]
        listed: dict[str, set[str]] = {}
        for entry in self.features():
            if "model" in entry:
                listed.setdefault(entry["model"], set()).update(entry["properties"])
        for mid, model in models.items():
            expected = model_keys(model, models, tpl)
            allowed = expected | set(model.get("extra") or [])
            have = listed.get(mid, set())
            problems += [f"{mid}: template key {key!r} belongs to no feature" for key in sorted(expected - have)]
            problems += [
                f"{mid}: {key!r} is neither a template key nor a declared extra" for key in sorted(have - allowed)
            ]
            problems += [
                f"{mid}: extra field {key!r} belongs to no feature"
                for key in sorted(set(model.get("extra") or []) - have)
            ]
        return problems

    def inventory_problems(self) -> list[str]:
        """Differences between the inventory keys of the features and EXPECTED_INVENTORY (otterdog main @9bdeb75)."""
        keys: dict[str, set[str]] = {}
        problems = []
        for entry in self.features():
            for key in entry.get("inventory") or []:
                match = INVENTORY_RE.match(key)
                if match is None:
                    problems.append(f"{entry['id']}: invalid inventory key {key!r}")
                    continue
                keys.setdefault(match["kind"], set()).add(match["value"])
        for kind, expected in EXPECTED_INVENTORY.items():
            have = keys.get(kind, set())
            problems += [f"{kind}: {value!r} is inventoried by no feature" for value in expected if value not in have]
            problems += [f"{kind}: unknown {value!r}" for value in sorted(have - set(expected))]
        problems += [f"unknown inventory kind {kind!r}" for kind in sorted(set(keys) - set(EXPECTED_INVENTORY))]
        return problems

    def markdown_problems(self) -> list[str]:
        """docs/coverage-matrix.md differs from the rendering of the matrix (regenerate it after editing the YAML)."""
        current = self.doc_path.read_text(encoding="utf-8") if self.doc_path.is_file() else ""
        if current == self.render_markdown(self.data):
            return []
        return [f"{DOC_FILE.as_posix()} is stale, regenerate it: {REGENERATE}"]

    def all_problems(self) -> list[str]:
        """Every problem the matrix tests report: schema first; with a valid schema the references, known bugs,
        findings, template and inventory exhaustiveness and the generated documentation."""
        problems = self.schema_problems(self.data)
        if problems:
            return problems
        problems += self.reference_problems(self.features())
        problems += self.known_bug_problems()
        problems += self.finding_problems()
        problems += self.template_problems()
        problems += self.inventory_problems()
        return problems + self.markdown_problems()

    # --- statistics and rendering ------------------------------------------------------------------------------------
    def offline_verified(self, entry: Mapping[str, Any]) -> bool:
        """True when a covering item belongs to the offline tier (the only tier that has run against real SUTs)."""
        return any(self.item_tier(item) == "offline" for item in entry.get("covered_by") or [])

    def verification(self, entry: Mapping[str, Any]) -> str:
        """Verification cell of a covered or partial feature: offline and/or live (verified_on), else unverified."""
        if entry["status"] == "gap":
            return "-"
        kinds = [
            label for label, ok in (("offline", self.offline_verified(entry)), ("live", live_verified(entry))) if ok
        ]
        return ", ".join(kinds) or "**unverified**"

    def summary_rows(self, groups: Sequence[tuple[str, Sequence[Mapping[str, Any]]]]) -> list[list[str]]:
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
                    str(sum(1 for entry in claimed if self.offline_verified(entry))),
                    str(sum(1 for entry in claimed if live_verified(entry))),
                    str(sum(1 for entry in claimed if not self.offline_verified(entry) and not live_verified(entry))),
                ]
            )
        return rows

    def summary_text(self, data: Mapping[str, Any]) -> str:
        """Plain-text coverage per area (printed by the summary test and the script)."""
        groups = [(area["id"], entries) for area, entries in area_groups(data)]
        rows = [*self.summary_rows(groups), *self.summary_rows([("TOTAL", list(data["features"]))])]
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

    def render_markdown(self, data: Mapping[str, Any]) -> str:
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
            md_text(data["description"]),
            "",
            (
                f"**{len(entries)} features** in {len(data['areas'])} areas: {total['covered']} covered, "
                f"{total['partial']} partial, {total['gap']} gaps; covered {percent(entries, weighted=False):.0f}%, "
                f"weighted {percent(entries, weighted=True):.0f}% (a partial feature counts half). "
                "*Offline-verified* counts the covered or partial features with at least one covering item in the "
                "offline tier; *live-verified* those with a recorded green live run of their covering items "
                "(`verified_on`: target, SUT, run id, date); *unverified* the others: their coverage is implemented "
                "but has never run, so it is a claim, not evidence. A covered feature needs at least one covering item "
                "that runs strictly on the default SUT (not only known-bug xfails or scenarios skipped by `fixed_in`)."
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
        out += md_table(header, [*self.summary_rows(groups), *self.summary_rows([("**Total**", entries)])], align)
        out += ["", "## Summary by tier", ""]
        tier_groups = [(f"`{tier}`", [e for e in entries if e["tier"] == tier]) for tier in TIERS]
        out += md_table(["Tier", *header[1:]], self.summary_rows(tier_groups), align)
        out += ["", "## Summary by priority", ""]
        prio_groups = [(prio, [e for e in entries if e["priority"] == prio]) for prio in PRIORITIES]
        out += md_table(["Priority", *header[1:]], self.summary_rows(prio_groups), align)
        out += ["", "Tiers:", ""]
        out += [f"- `{tier}`: {md_text(text)}" for tier, text in data["tiers"].items()]
        out += ["", "Operations:", ""]
        out += [f"- `{op}`: {md_text(text)}" for op, text in data["operations"].items()]
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
                md_text(f["title"]),
                ", ".join(f"`{s}`" for s in f["source"]),
                md_text(f["verified"]),
                md_text(f["suggestion"]),
            ]
            for f in data["findings"]
        ]
        out += md_table(["Id", "Finding", "Source", "Verified", "Suggestion"], rows)
        for area, group in area_groups(data):
            out += self.render_area(area, group)
        return "\n".join(out).rstrip("\n") + "\n"

    def render_area(self, area: Mapping[str, Any], group: Sequence[Mapping[str, Any]]) -> list[str]:
        """The section of one area: a table of its features, then the details of notes, partials and gaps."""
        found = counts(group)
        out = [""]
        # the summary links to #<area id>: an explicit anchor when the heading's own anchor is another (never a
        # duplicate id)
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
                md_text(e["title"]) + (" (UI only)" if e["ui_only"] else ""),
                e["tier"],
                e["min_plan"],
                e["priority"],
                {"covered": "covered", "partial": "**partial**", "gap": "**gap**"}[e["status"]],
                self.verification(e),
                code_list(e["covered_by"]),
            ]
            for e in group
        ]
        out += md_table(["Id", "Feature", "Tier", "Plan", "Prio", "Status", "Verified", "Covered by"], rows)
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


def _known_bug_test(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """True when the test is a known-bug test (``known_bug`` mark) without a scoped xfail (``xfail(raises=...)``)."""

    def mark_calls(name: str) -> list[ast.Call]:
        """The ``<...>.<name>(...)`` decorators of the test function."""
        return [
            decorator
            for decorator in node.decorator_list
            if isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == name
        ]

    scoped = any(any(k.arg == "raises" for k in call.keywords) for call in mark_calls("xfail"))
    return bool(mark_calls("known_bug")) and not scoped


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


# --- helpers -----------------------------------------------------------------------------------------------------------
def _is_str_list(value: Any, *, allow_empty: bool = True) -> bool:
    """A list of non-empty strings (non-empty itself unless allow_empty)."""
    return (
        isinstance(value, list)
        and (allow_empty or len(value) > 0)
        and all(isinstance(item, str) and item.strip() for item in value)
    )


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


def live_verified(entry: Mapping[str, Any]) -> bool:
    """True when a green live run of the covering items is recorded (``verified_on``)."""
    return bool(entry.get("verified_on"))


def area_groups(data: Mapping[str, Any]) -> list[tuple[Mapping[str, Any], list[Mapping[str, Any]]]]:
    """(area, its features) in area order."""
    entries = list(data["features"])
    return [(area, [e for e in entries if e["area"] == area["id"]]) for area in data["areas"]]


_MD_ESCAPES = str.maketrans({"<": "&lt;", ">": "&gt;", "*": "\\*", "~": "\\~"})


def md_text(value: Any) -> str:
    """Free text as markdown: whitespace flattened; '<', '>', '*' and '~' escaped outside code spans (GitHub drops
    unknown tags such as '<org>' and turns '*' / '~' pairs into emphasis or strikethrough)."""
    parts = " ".join(str(value).split()).split("`")
    return "`".join(part if index % 2 else part.translate(_MD_ESCAPES) for index, part in enumerate(parts))


def heading_anchor(title: str) -> str:
    """The anchor GitHub gives a heading, and the documentation site too (toc slugify of mkdocs.yml): lower case,
    punctuation dropped, spaces as dashes."""
    return re.sub(r"[^\w\- ]", "", title.lower()).replace(" ", "-")


def md_cell(text: Any) -> str:
    """A markdown table cell (pipes escaped, newlines flattened)."""
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def code_list(items: Iterable[str]) -> str:
    """Comma-separated code spans (or a dash)."""
    values = [f"`{item}`" for item in items]
    return ", ".join(values) if values else "-"


def md_table(header: Sequence[str], rows: Iterable[Sequence[str]], align: str | None = None) -> list[str]:
    """Markdown table lines."""
    lines = ["| " + " | ".join(header) + " |", "|" + (align or "|".join("---" for _ in header)) + "|"]
    lines += ["| " + " | ".join(md_cell(cell) for cell in row) + " |" for row in rows]
    return lines


# nested bullets are indented by 4 spaces per level: GitHub accepts 2, but Python-Markdown (MkDocs, the documentation
# site) only nests a list indented by 4 and would flatten the details
LIST_INDENT = " " * 4


def render_details(e: Mapping[str, Any]) -> list[str]:
    """The detail bullet list of one feature."""
    out = [f"- **`{e['id']}`** ({e['status']}, {e['priority']}, `{e['tier']}`): {md_text(e['title'])}"]
    out.append(f"{LIST_INDENT}- Source: {', '.join(f'`{s}`' for s in e['source'])}")
    if e.get("properties"):
        out.append(f"{LIST_INDENT}- Properties (`{e['model']}`): {', '.join(f'`{p}`' for p in e['properties'])}")
    out.append(f"{LIST_INDENT}- Operations: {', '.join(e['operations'])}")
    if e.get("known_bugs"):
        out.append(f"{LIST_INDENT}- Known bugs: {', '.join(e['known_bugs'])}")
    if e.get("findings"):
        out.append(f"{LIST_INDENT}- New findings: {', '.join(e['findings'])}")
    if e.get("notes"):
        out.append(f"{LIST_INDENT}- Notes: {md_text(e['notes'])}")
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
            out += [f"{LIST_INDENT * 2}- {md_text(item)}" for item in outline[key]]
    return out
