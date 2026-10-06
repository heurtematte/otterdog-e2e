"""YAML scenario model (SPEC 12.1, F5).

Semantics: steps are DECLARATIVE (config(step k) = baseline + fragments(step k)); phases per step are render+write ->
validate (if given) -> plan -> apply (if plan.expect == changes and apply is not null) -> state -> converge; the first
failing phase aborts the remaining steps, cleanup always runs. Jinja2 (StrictUndefined) is applied ONCE, by
render_step, with the vars run, p, P, hook_base, org, plan, logins.<name>, app_slug, app_id,
teams.<admin|approval|contributors> plus the scenario's ``variables``.

Loading is strict (ScenarioError): unknown keys (YAML duplicate keys included), bad values, duplicate ids or step
names, settings fragments setting plan/description/billing_email (offline: plan only, nothing is applied), secret
values that are not dummies (``****``, ``e2e-dummy-<8 [0-9a-z]>`` e.g. ``e2e-dummy-{{ run }}``, ``pass:<path>`` and
``<provider>:e2e/<path>`` references; offline also the KB-025 crash literal ``pass:a:b``), offline fragments using
``newTeam``/teams or ``code_scanning_default_languages`` with an enabled setup (they call GitHub even with --local,
OC-04), fragments ending with a line comment, unknown template variables, ``logins.<role>`` of an optional identity
not declared in ``identities``, and tier rules: offline scenarios never apply, check state, use logins, depend on
capabilities or use org_level, and their plan expectations need a BASE configuration (local-plan); live scenarios
never use base_fragments, config, base_config, workspace or commands, must be org_level when they change settings
(settings carry no run prefix, so only an org-level plan and reset can see and undo them) and filter repositories
with this run's prefix only (``repo_filter`` of plan/apply starts with ``{{ p }}-`` unless org_level).

Step options (verified against otterdog/cli.py @9bdeb75): ``validate.verbose`` runs ``validate -v`` (Info messages,
``infos``/``infos_min`` counts); ``plan`` and ``apply`` take the diff flags ``repo_filter`` (-r), ``update_secrets``,
``update_webhooks``, ``only_secrets``, ``update_filter`` and ``verbose`` (offline: local-plan flags); ``exit_code``
checks the exit status of validate and plan; a step's ``known_bug`` turns the failures of that step alone into
expected failures (engine.ScenarioOutcome.expected_failures) while the other steps stay strict; an offline step's
``workspace`` (otterdog.workspace.WorkspaceLayout) changes otterdog's own configuration for that step (otterdog.jsonnet,
extra organizations, .otterdog-defaults.json, base_url, config_dir, no vendored template).

``references`` (changes.parse_references) name the changes behind the behaviour a scenario pins: otterdog pull
requests (``pr: <n>``) or named changes without one (``change: <slug>``), each with an optional note, the deltas it is
expected to cause in this scenario between base and head (``expected_deltas``; a ``step`` pattern must match a step of
the scenario), its differential ``base`` and ``template``. Scenarios are named after the behaviour, never after a PR.

Jsonnet may come from files (otterdog_e2e.inject): a fragment entry or a step ``overlay`` is an inline string or
``{file: <path>, raw: <bool>, vars: <mapping>}``, scenario ``libraries`` map a jsonnet identifier to a path (or such
a mapping) and are attached to the ConfigFragments of every step (render.py inlines them), offline steps may give a
complete ``config`` / ``base_config`` file. Paths are relative to the scenario file and stay inside the project; the
files are read at load time, Jinja-rendered by render_step (unless raw, with their own ``vars``) and checked like
inline snippets, plus: no import/importstr/importbin anywhere (except the template import of a config file), overlays
merge settings (``settings+:``) without plan/description/billing_email and need org_level (live) when they touch
them. Problems of file content name ``<file>:<line>``.
"""

from __future__ import annotations

import copy
import functools
import re
from collections.abc import Callable, Collection, Iterator, Mapping
from dataclasses import dataclass, field, fields, is_dataclass, replace
from pathlib import Path
from typing import Any

import jinja2
import jinja2.meta
import jinja2.nodes
import jinja2.sandbox
import yaml

from otterdog_e2e.capabilities import PLANS, Cap
from otterdog_e2e.changes import (
    DELTA_KEYS,
    REFERENCE_KEYS,
    SLUG_RE,
    TEMPLATE_MODES,
    ChangeError,
    Reference,
    parse_references,
)
from otterdog_e2e.inject import (
    CONFIG_ROLES,
    CONFIG_VARIABLES,
    FILE_KEYS,
    FileContext,
    InjectError,
    SourceText,
    has_jinja,
    load_source,
    render_source,
)
from otterdog_e2e.known_bugs import KNOWN_BUG_ID_RE
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.otterdog.render import FRAGMENT_KEYS, ConfigFragments, library_name_problem
from otterdog_e2e.otterdog.workspace import (
    CONFIG_DIR,
    CONFIG_FORMATS,
    ORG_ENTRY_KEYS,
    WorkspaceLayout,
    dir_name_problem,
)
from otterdog_e2e.scenarios.checks import validate_check
from otterdog_e2e.settings import IDENTITY_ROLES
from otterdog_e2e.sut.template import offline_template

TIERS = ("cli", "offline", "enterprise")
PRIORITIES = ("P0", "P1", "P2")
PLAN_EXPECTS = ("changes", "noop", "validation_error", "error", "any")
APPLY_EXPECTS = ("ok", "error", "validation_error", "any")
CLEANUP_MODES = ("auto", "none")
MISSING_CAPABILITY_KEYS = ("validate", "plan", "apply", "state", "converge")
FORBIDDEN_SETTINGS = ("plan", "description", "billing_email")  # set by the baseline layer only (use variables.plan)
OFFLINE_FORBIDDEN_SETTINGS = ("plan",)  # offline: the profile may be set (nothing is applied), the plan never
OFFLINE_FORBIDDEN = ("newTeam", "code_scanning_default_languages")  # would call GitHub even with --local (OC-04)
DUMMY_SECRET_RE = re.compile(r"^(\*+|e2e-dummy-[0-9a-z]{8})$")  # otterdog echoes plain secret values (SPEC 5.8)
# provider references are paths, never secrets: pass (real configs use 'pass:bots/...'; shell-safe characters only,
# since otterdog resolves them with a shell command at apply time) and any other provider than pass/bitwarden/vault
# (otterdog warns and uses the literal) below an 'e2e/' path
SECRET_REFERENCE_RE = re.compile(r"^pass:[A-Za-z0-9_][A-Za-z0-9._/-]*$")
E2E_SECRET_REFERENCE_RE = re.compile(r"^(?!(?:pass|bitwarden|vault):)[a-z][a-z0-9_-]*:e2e/[A-Za-z0-9._/-]+$")
# offline only: a reference with several ':' (KB-025, 'pass:a:b' crashes validation with a ValueError)
OFFLINE_SECRET_RE = re.compile(r"^pass:[A-Za-z0-9._/-]+(?::[A-Za-z0-9._/-]+)+$")
DUMMY_HINT = "'********', 'e2e-dummy-<8 chars [0-9a-z]>' or a 'pass:<path>' reference"
IGNORED_FILES = ("known_bugs.yaml",)
SCENARIO_SUFFIXES = (".yaml", ".yml")

# extra offline commands a step may run (observed by differential runs); each takes the vendored template (--local);
# ``show`` gives the expectations of the show phase (show runs once per step anyway)
OFFLINE_EXTRA_COMMANDS = ("show", "show-default", "canonical-diff", "list-projects", "--version")
# scenario directory name -> tiers its files may declare (a missing ``tier`` is inferred from the first one)
DIRECTORY_TIERS: Mapping[str, tuple[str, ...]] = {
    "offline": ("offline",),
    "cli": ("cli",),
    "regressions": ("cli",),
    "enterprise": ("enterprise",),
}
# Jinja variables provided by the engines (``plan`` may be overridden by the scenario's ``variables``); offline
# config/base_config files also get CONFIG_VARIABLES (import_path, project)
TEMPLATE_VARIABLES = ("run", "p", "P", "hook_base", "org", "plan", "logins", "app_slug", "app_id", "teams")
RESERVED_VARIABLES = (*(name for name in TEMPLATE_VARIABLES if name != "plan"), *CONFIG_VARIABLES)
TEAM_ROLES = ("admin", "approval", "contributors")
# statements reading other files: refused in every snippet (the webapp evaluates ONE file; an import could read the
# workspace, e.g. otterdog's HTTP cache), except the template import of an offline config file
IMPORT_KEYWORDS = ("import", "importstr", "importbin")

SCENARIO_KEYS = (
    "id",
    "title",
    "description",
    "tier",
    "priority",
    "min_plan",
    "requires",
    "expect_failure_without",
    "identities",
    "tags",
    "known_bug",
    "org_level",
    "observe",
    "variables",
    "libraries",
    "fixed_in",
    "references",
    "timeout",
    "steps",
    "cleanup",
)
STEP_KEYS = (
    "name",
    "known_bug",
    "fragments",
    "overlay",
    "base_fragments",
    "config",
    "base_config",
    "workspace",
    "validate",
    "plan",
    "apply",
    "state",
    "converge",
    "on_missing_capability",
    "commands",
)
VALIDATE_KEYS = (
    "ok",
    "errors",
    "warnings_min",
    "infos",
    "infos_min",
    "exit_code",
    "verbose",
    "contains",
    "not_contains",
)
# flags of otterdog's diff commands (runner.DiffOptions): plan/local-plan and apply
DIFF_OPTION_KEYS = ("repo_filter", "update_secrets", "update_webhooks", "update_filter", "only_secrets", "verbose")
DIFF_FLAG_KEYS = ("update_secrets", "update_webhooks", "only_secrets", "verbose")
PLAN_KEYS = ("expect", "contains", "not_contains", "counts", "exit_code", *DIFF_OPTION_KEYS)
APPLY_KEYS = ("expect", "delete", *DIFF_OPTION_KEYS, "contains", "not_contains")
COMMAND_KEYS = ("exit_code", "contains", "not_contains")
COUNT_KEYS = ("add", "change", "delete")
# offline step ``workspace`` (otterdog.workspace.WorkspaceLayout); its defaults override may only set these keys (no
# credential provider settings: a provider would run its CLI or contact a server)
WORKSPACE_KEYS = ("format", "orgs", "defaults_override", "base_url", "config_dir", "vendor")
DEFAULTS_OVERRIDE_KEYS: Mapping[str, tuple[str, ...] | None] = {
    "base_url": None,
    "jsonnet": ("base_template", "config_dir"),
    "github": ("config_repo", "exclude_teams"),
    "cost_policy": ("free_max_cache_size_gb",),
}

ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*$")
STEP_NAME_RE = ID_RE
TAG_RE = re.compile(r"^[a-z0-9][a-z0-9_.\-]*$")
VARIABLE_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_CALL_RE = re.compile(r"^new(Org|Repo|Env)Secret$")
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER_RE = re.compile(r"[0-9][0-9.eE+\-]*")
_STRING_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "b": "\b", "f": "\f"}

# sample values for the load-time render of fragments (syntax, attribute typos, secret and settings checks)
_SAMPLE_RUN = new_run_context("t3c7z8a5")
_SAMPLE_VARIABLES: Mapping[str, Any] = {
    **_SAMPLE_RUN.template_vars(),
    "org": "e2e-sample-org",
    "plan": "free",
    "logins": {role: f"e2e-sample-{role.replace('_', '-')}" for role in IDENTITY_ROLES},
    "app_slug": "e2e-sample-app",
    "app_id": "123456",
    "teams": {role: f"e2e-sample-{role}" for role in TEAM_ROLES},
    "import_path": offline_template().import_path,  # config files only (CONFIG_VARIABLES)
    "project": "e2e-sample-org",
}


class ScenarioError(ValueError):
    """Invalid scenario file (unknown keys, duplicate ids, forbidden fragments, non-dummy secrets, ...)."""


@dataclass
class ValidateSpec:
    """Expected ``validate`` outcome of a step (``ok`` defaults to ``errors == 0``); ``verbose`` runs ``validate -v``
    (otterdog prints Info messages only then: ``infos``/``infos_min`` need it); ``exit_code`` None = not checked."""

    ok: bool | None = None
    errors: int | None = None
    warnings_min: int | None = None
    contains: list[str] = field(default_factory=list)
    not_contains: list[str] = field(default_factory=list)
    infos: int | None = None
    infos_min: int | None = None
    exit_code: int | None = None
    verbose: bool = False


@dataclass
class PlanSpec:
    """Expected ``plan`` outcome: expect (PLAN_EXPECTS), contained text, counts (add/change/delete), exit code (None =
    not checked) and the diff flags of the command (``repo_filter`` None = the engine's default filter)."""

    expect: str = "changes"
    contains: list[str] = field(default_factory=list)
    not_contains: list[str] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    exit_code: int | None = None
    repo_filter: str | None = None
    update_secrets: bool = False
    update_webhooks: bool = False
    update_filter: str | None = None
    only_secrets: bool = False
    verbose: bool = False


@dataclass
class ApplySpec:
    """Expected ``apply`` outcome and its flags (``repo_filter`` None = the plan's filter)."""

    expect: str = "ok"
    delete: bool = False
    update_secrets: bool = False
    update_webhooks: bool = False
    contains: list[str] = field(default_factory=list)
    not_contains: list[str] = field(default_factory=list)
    update_filter: str | None = None
    only_secrets: bool = False
    repo_filter: str | None = None
    verbose: bool = False


@dataclass
class CommandSpec:
    """Expected outcome of an extra offline command (exit code None = any)."""

    exit_code: int | None = 0
    contains: list[str] = field(default_factory=list)
    not_contains: list[str] = field(default_factory=list)


@dataclass
class StepSpec:
    """One declarative step of a scenario (``fragments`` also carries the scenario's libraries and the step's
    overlays; ``config``/``base_config``: complete offline configs replacing the rendering, SourceText until
    render_step; ``known_bug``: the step's failures are expected while the bug affects the SUT; ``workspace``: the
    offline WorkspaceLayout of the step (None = the harness layout); ``offline``: the step belongs to an offline
    scenario, render_step then applies the offline rules)."""

    name: str
    fragments: ConfigFragments = field(default_factory=ConfigFragments)
    base_fragments: ConfigFragments | None = None
    validate: ValidateSpec | None = None
    plan: PlanSpec | None = field(default_factory=PlanSpec)
    apply: ApplySpec | None = field(default_factory=ApplySpec)
    state: list[dict[str, Any]] = field(default_factory=list)
    converge: bool = True
    on_missing_capability: dict[str, Any] = field(default_factory=dict)
    commands: dict[str, CommandSpec] = field(default_factory=dict)
    config: str | None = None
    base_config: str | None = None
    known_bug: str | None = None
    workspace: WorkspaceLayout | None = None
    offline: bool = False
    known_bug_phases: tuple[str, ...] | None = None  # None: every phase (known_bug: {id: ..., phases: [...]})

    def for_missing_capability(self) -> StepSpec:
        """The negative variant of the step: on_missing_capability overrides applied (parsed, already merged)."""
        return replace(self, **copy.deepcopy(self.on_missing_capability))


@dataclass
class Scenario:
    """A scenario file: metadata, steps and its source path."""

    id: str
    title: str
    tier: str
    steps: list[StepSpec]
    source: Path
    description: str = ""
    priority: str = "P1"
    min_plan: str = "free"
    requires: list[str] = field(default_factory=list)
    expect_failure_without: list[str] = field(default_factory=list)
    identities: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    known_bug: str | None = None
    org_level: bool = False
    observe: bool = False
    variables: dict[str, Any] = field(default_factory=dict)
    cleanup: str = "auto"
    fixed_in: str | None = None  # first otterdog version (PEP 440) with the fix/feature asserted: older SUTs skip
    timeout: int | None = None  # pytest timeout (s) of the scenario's item, instead of collect.scenario_timeout()
    libraries: dict[str, str] = field(default_factory=dict)  # name -> SourceText, attached to every step's fragments
    references: list[Reference] = field(default_factory=list)  # changes (PRs) behind the behaviour (changes.py)

    @property
    def is_live(self) -> bool:
        """True for scenarios that need a real org (tier cli or enterprise)."""
        return self.tier in ("cli", "enterprise")

    @property
    def plan_override(self) -> str | None:
        """``variables.plan``: the plan rendered into settings instead of the target's (negative tests)."""
        plan = self.variables.get("plan")
        return plan if isinstance(plan, str) else None


# --- loading ---------------------------------------------------------------------------------------------------------
class _StrictLoader(yaml.SafeLoader):
    """SafeLoader refusing duplicate mapping keys (YAML merge keys ``<<`` excepted)."""

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        """Check the explicit keys of the mapping for duplicates, then construct it."""
        seen: set[Any] = set()
        for key_node, _ in node.value:
            if key_node.tag == "tag:yaml.org,2002:merge":
                continue
            key = self.construct_object(key_node, deep=True)
            try:
                duplicate = key in seen
                seen.add(key)
            except TypeError:  # unhashable key: SafeConstructor reports it
                continue
            if duplicate:
                raise ScenarioError(f"duplicate key {key!r} (line {key_node.start_mark.line + 1})")
        return super().construct_mapping(node, deep=deep)


def load_scenario(path: Path) -> Scenario:
    """Load and validate one scenario YAML file (ScenarioError on any rule of SPEC 12.1 (7)); the files it references
    are relative to it and must stay inside the project."""
    return _load(Path(path), FileContext(Path(path).absolute().parent))


def load_adhoc_scenario(path: Path) -> Scenario:
    """load_scenario for the scenario written by ``otterdog-e2e inject``: its files may lie anywhere (absolute
    paths), every content rule still applies."""
    return _load(Path(path), FileContext(Path(path).absolute().parent, external=True))


def _load(path: Path, files: FileContext) -> Scenario:
    """Parse and validate ``path`` resolving its file references with ``files`` (errors prefixed with the path)."""
    try:
        return _parse_scenario(_read_yaml(path), path, files)
    except ScenarioError as exc:
        raise ScenarioError(f"{path}: {exc}") from None


def load_scenarios(directory: Path, *, tier: str | None = None) -> list[Scenario]:
    """Load every *.yaml below ``directory`` (sorted; ignores known_bugs.yaml and dotfiles; duplicate ids fail)."""
    if tier is not None and tier not in TIERS:
        raise ScenarioError(f"unknown tier {tier!r}, expected one of {TIERS}")
    scenarios = [load_scenario(path) for path in scenario_files(Path(directory))]
    _check_unique_ids(scenarios)
    return [scenario for scenario in scenarios if tier is None or scenario.tier == tier]


def scenario_files(directory: Path) -> list[Path]:
    """Scenario files below ``directory`` (missing directory -> []), sorted, without ignored files/dirs/dotfiles."""
    if not directory.is_dir():
        return []
    found = []
    for path in sorted(directory.rglob("*")):
        relative = path.relative_to(directory)
        if not path.is_file() or path.suffix not in SCENARIO_SUFFIXES or path.name in IGNORED_FILES:
            continue
        if any(part.startswith(".") for part in relative.parts):
            continue
        found.append(path)
    return found


def _check_unique_ids(scenarios: list[Scenario]) -> None:
    """ScenarioError naming both files when two scenarios share an id."""
    seen: dict[str, Path] = {}
    for scenario in scenarios:
        if scenario.id in seen:
            raise ScenarioError(f"duplicate scenario id {scenario.id!r} in {seen[scenario.id]} and {scenario.source}")
        seen[scenario.id] = scenario.source


def _read_yaml(path: Path) -> Any:
    """Parse a YAML file strictly (duplicate keys refused)."""
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ScenarioError(f"cannot read scenario: {exc}") from None
    try:
        return yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - _StrictLoader is a SafeLoader
    except yaml.YAMLError as exc:
        raise ScenarioError(f"invalid YAML: {exc}") from None


# --- typed field readers ---------------------------------------------------------------------------------------------
def _mapping(value: Any, where: str) -> Mapping[str, Any]:
    """``value`` as a mapping with string keys."""
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ScenarioError(f"{where}: expected a mapping with string keys, got {type(value).__name__}")
    return value


def _check_keys(data: Mapping[str, Any], allowed: Collection[str], where: str) -> None:
    """ScenarioError for keys outside ``allowed``."""
    unknown = sorted(set(data) - set(allowed))
    if unknown:
        raise ScenarioError(f"{where}: unknown key(s) {unknown}, allowed: {sorted(allowed)}")


def _str(value: Any, where: str, *, pattern: re.Pattern[str] | None = None, allow_empty: bool = False) -> str:
    """A string (non-empty unless allow_empty, matching ``pattern`` when given)."""
    if not isinstance(value, str) or (not value and not allow_empty):
        raise ScenarioError(f"{where}: expected a non-empty string, got {value!r}")
    if pattern is not None and not pattern.match(value):
        raise ScenarioError(f"{where}: {value!r} does not match {pattern.pattern}")
    return value


def _bool(value: Any, where: str) -> bool:
    """A YAML boolean."""
    if not isinstance(value, bool):
        raise ScenarioError(f"{where}: expected true or false, got {value!r}")
    return value


def _int(value: Any, where: str) -> int:
    """A non-negative integer (booleans refused)."""
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ScenarioError(f"{where}: expected a non-negative integer, got {value!r}")
    return value


def _choice(value: Any, choices: Collection[str], where: str) -> str:
    """One of ``choices``."""
    if value not in choices:
        raise ScenarioError(f"{where}: {value!r} is not one of {list(choices)}")
    return str(value)


def _str_list(value: Any, where: str, *, pattern: re.Pattern[str] | None = None) -> list[str]:
    """A list of strings (a single string counts as a one-item list; null -> [])."""
    if value is None:
        return []
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list):
        raise ScenarioError(f"{where}: expected a list of strings, got {type(value).__name__}")
    return [_str(item, f"{where}[{index}]", pattern=pattern) for index, item in enumerate(items)]


def _capabilities(value: Any, where: str) -> list[str]:
    """A list of capability names (capabilities.Cap values)."""
    names = _str_list(value, where)
    for name in names:
        try:
            Cap(name)
        except ValueError:
            raise ScenarioError(
                f"{where}: unknown capability {name!r}, expected one of {[c.value for c in Cap]}"
            ) from None
    return names


# --- scenario and step parsing ---------------------------------------------------------------------------------------
def _parse_scenario(data: Any, path: Path, files: FileContext) -> Scenario:
    """Scenario from the YAML document of ``path`` (all rules checked; file references resolved with ``files``)."""
    if data is None:
        raise ScenarioError("empty scenario file")
    root = _mapping(data, "scenario")
    _check_keys(root, SCENARIO_KEYS, "scenario")
    for required in ("id", "title", "steps"):
        if required not in root:
            raise ScenarioError(f"scenario: missing required key {required!r}")
    tier = _tier(root.get("tier"), path)
    expect_failure_without = _capabilities(root.get("expect_failure_without"), "expect_failure_without")
    libraries = _libraries(root.get("libraries"), files)
    steps = _parse_steps(root["steps"], tier=tier, negative=bool(expect_failure_without), files=files)
    scenario = Scenario(
        id=_str(root["id"], "id", pattern=ID_RE),
        title=_str(root["title"], "title"),
        tier=tier,
        steps=steps,
        source=path,
        libraries=libraries,
        description=_str(root.get("description", ""), "description", allow_empty=True),
        priority=_choice(root.get("priority", "P1"), PRIORITIES, "priority"),
        min_plan=_choice(root.get("min_plan", "free"), PLANS, "min_plan"),
        requires=_capabilities(root.get("requires"), "requires"),
        expect_failure_without=expect_failure_without,
        identities=[
            _choice(name, IDENTITY_ROLES, "identities") for name in _str_list(root.get("identities"), "identities")
        ],
        tags=_str_list(root.get("tags"), "tags", pattern=TAG_RE),
        known_bug=_known_bug(root.get("known_bug")),
        org_level=_bool(root.get("org_level", False), "org_level"),
        observe=_bool(root.get("observe", False), "observe"),
        variables=_variables(root.get("variables")),
        cleanup=_choice(root.get("cleanup", "auto"), CLEANUP_MODES, "cleanup"),
        fixed_in=_fixed_in(root.get("fixed_in")),
        timeout=_timeout(root.get("timeout")),
        references=_references(root.get("references"), [step.name for step in steps]),
    )
    for step in scenario.steps:  # libraries go into every render of the scenario (the -BASE config included)
        step.fragments.libraries = dict(libraries)
        if step.base_fragments is not None:
            step.base_fragments.libraries = dict(libraries)
    _check_tier_rules(scenario)
    _check_templates(scenario)
    return scenario


def tier_directory(path: Path) -> str | None:
    """Name of the tier directory a scenario file belongs to (a DIRECTORY_TIERS key), or None.

    It is the outermost ancestor named like a tier directory below the nearest ``scenarios`` directory, so a file of a
    subdirectory belongs to the directory right below ``scenarios/``: ``scenarios/cli/org/x.yaml`` to ``cli`` and
    ``scenarios/offline/cli/output/show.yaml`` to ``offline`` (not to the inner ``cli``).
    """
    found = None
    for parent in path.parents:
        if parent.name == "scenarios":
            break
        if parent.name in DIRECTORY_TIERS:
            found = parent.name
    return found


def _tier(value: Any, path: Path) -> str:
    """Declared tier, checked against (or inferred from) the scenario's tier directory (DIRECTORY_TIERS)."""
    directory = tier_directory(path)
    allowed = DIRECTORY_TIERS.get(directory) if directory is not None else None
    if value is None:
        if allowed is None:
            raise ScenarioError(f"scenario: missing 'tier' (one of {TIERS})")
        return allowed[0]
    tier = _choice(value, TIERS, "tier")
    if allowed is not None and tier not in allowed:
        raise ScenarioError(f"tier {tier!r} does not belong in scenarios/{directory}/ (allowed: {allowed})")
    return tier


KNOWN_BUG_PHASES = ("validate", "plan", "apply", "state", "converge", "local-plan", "show", "commands")


def _known_bug(value: Any, where: str = "known_bug") -> str | None:
    """Known bug id (``KB-<nnn>``) or None."""
    return None if value is None else _str(value, where, pattern=KNOWN_BUG_ID_RE)


def _step_known_bug(value: Any, where: str) -> tuple[str | None, tuple[str, ...] | None]:
    """A step's ``known_bug``: an id, or ``{id, phases}`` limiting the bug to the failures of those phases (a
    converge bug then never hides a plan, apply or state failure of its step)."""
    if not isinstance(value, Mapping):
        return _known_bug(value, where), None
    unknown = sorted(set(value) - {"id", "phases"})
    if unknown:
        raise ScenarioError(f"{where}: unknown key(s) {unknown}, expected id and phases")
    bug_id = _known_bug(value.get("id"), f"{where}.id")
    if bug_id is None:
        raise ScenarioError(f"{where}.id: required")
    phases = value.get("phases")
    if not isinstance(phases, list) or not phases or not all(isinstance(phase, str) for phase in phases):
        raise ScenarioError(f"{where}.phases: a non-empty list of phases ({', '.join(KNOWN_BUG_PHASES)})")
    bad = sorted(set(phases) - set(KNOWN_BUG_PHASES))
    if bad:
        raise ScenarioError(f"{where}.phases: unknown phase(s) {bad}, expected {list(KNOWN_BUG_PHASES)}")
    return bug_id, tuple(dict.fromkeys(phases))


def _fixed_in(value: Any) -> str | None:
    """``fixed_in``: a PEP 440 otterdog version (``1.7.0.dev15``), without local part, or None."""
    if value is None:
        return None
    from otterdog_e2e.sut.version import version_key

    text = _str(value, "fixed_in")
    try:
        version_key(text)
    except ValueError:
        raise ScenarioError(f"fixed_in: {text!r} is not a PEP 440 version (e.g. 1.7.0.dev15)") from None
    if "+" in text:
        raise ScenarioError(f"fixed_in: {text!r} has a local version part (+...), use the public version")
    return text


def _references(value: Any, steps: list[str]) -> list[Reference]:
    """``references``: the changes behind the scenario's behaviour (changes.parse_references; step patterns of
    expected deltas must match a step)."""
    try:
        return parse_references(value, "references", steps=steps)
    except ChangeError as exc:
        raise ScenarioError(str(exc)) from None


def _timeout(value: Any) -> int | None:
    """``timeout``: a positive number of seconds (int), or None."""
    if value is None:
        return None
    if _int(value, "timeout") <= 0:
        raise ScenarioError(f"timeout: expected a positive number of seconds, got {value!r}")
    return int(value)


def _variables(value: Any) -> dict[str, Any]:
    """Extra Jinja variables (identifier names; only ``plan`` may override an engine variable)."""
    if value is None:
        return {}
    variables = dict(_mapping(value, "variables"))
    for name in variables:
        _str(name, f"variables.{name}", pattern=VARIABLE_NAME_RE)
        if name in RESERVED_VARIABLES:
            raise ScenarioError(f"variables: {name!r} is provided by the engine and cannot be overridden")
        if name in SCENARIO_KEYS:
            raise ScenarioError(f"variables: {name!r} is a scenario key, set it at the top level of the scenario")
    if "plan" in variables:
        _str(variables["plan"], "variables.plan")
    return variables


def _parse_steps(value: Any, *, tier: str, negative: bool, files: FileContext) -> list[StepSpec]:
    """Steps of a scenario (non-empty list, unique names)."""
    if not isinstance(value, list) or not value:
        raise ScenarioError("steps: expected a non-empty list of steps")
    steps = [_parse_step(item, index, tier=tier, negative=negative, files=files) for index, item in enumerate(value)]
    names = [step.name for step in steps]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    if duplicates:
        raise ScenarioError(f"steps: duplicate step name(s) {duplicates}")
    return steps


def _parse_step(value: Any, index: int, *, tier: str, negative: bool, files: FileContext) -> StepSpec:
    """One step; offline steps never apply, live steps never use base_fragments/config/base_config/commands."""
    where = f"steps[{index}]"
    data = _mapping(value, where)
    _check_keys(data, STEP_KEYS, where)
    offline = tier == "offline"
    fragments = _fragments(data.get("fragments"), f"{where}.fragments", files) or ConfigFragments()
    fragments.overlays = _overlays(data.get("overlay"), f"{where}.overlay", files)
    step = StepSpec(
        name=_str(data.get("name", f"step-{index + 1}"), f"{where}.name", pattern=STEP_NAME_RE),
        fragments=fragments,
        base_fragments=_fragments(data.get("base_fragments"), f"{where}.base_fragments", files),
        validate=_parse_validate(data.get("validate"), f"{where}.validate"),
        plan=_parse_plan(data.get("plan", {}), f"{where}.plan"),
        apply=None if offline else _parse_apply(data.get("apply", {}), f"{where}.apply"),
        state=_parse_state(data.get("state"), f"{where}.state"),
        converge=_bool(data.get("converge", True), f"{where}.converge"),
        commands=_parse_commands(data.get("commands"), f"{where}.commands"),
        config=_config_file(data.get("config"), f"{where}.config", files, role="config"),
        base_config=_config_file(data.get("base_config"), f"{where}.base_config", files, role="base_config"),
        known_bug=_step_known_bug(data.get("known_bug"), f"{where}.known_bug")[0],
        known_bug_phases=_step_known_bug(data.get("known_bug"), f"{where}.known_bug")[1],
        workspace=_parse_workspace(data.get("workspace"), f"{where}.workspace"),
        offline=offline,
    )
    _check_step_tier(data, step, where, offline=offline)
    if "on_missing_capability" in data:
        if not negative:
            raise ScenarioError(f"{where}.on_missing_capability: requires expect_failure_without")
        step.on_missing_capability = _parse_overrides(data["on_missing_capability"], step, where)
    for variant in (step, step.for_missing_capability()):
        _check_apply_filter(variant, where)
    return step


def _check_step_tier(data: Mapping[str, Any], step: StepSpec, where: str, *, offline: bool) -> None:
    """Tier restrictions of a step (offline: no apply/state, plan expectations need a BASE config; live: no
    base_fragments/config/base_config/workspace/commands) and the exclusive keys of complete configs (config replaces
    fragments and overlay, base_config base_fragments)."""
    if offline and data.get("apply") is not None:
        raise ScenarioError(f"{where}.apply: offline scenarios cannot apply")
    if offline and step.state:
        raise ScenarioError(f"{where}.state: offline scenarios have no oracle")
    if offline and data.get("plan") is not None and step.base_fragments is None and step.base_config is None:
        raise ScenarioError(
            f"{where}.plan: offline plan expectations are checked by local-plan, which only runs against a BASE "
            "configuration: add base_fragments: {} (the bare organization) or base_config"
        )
    if not offline and step.base_fragments is not None:
        raise ScenarioError(f"{where}.base_fragments: only offline scenarios use a BASE config (local-plan)")
    for key in ("config", "base_config"):
        if not offline and getattr(step, key) is not None:
            raise ScenarioError(f"{where}.{key}: only offline scenarios replace the rendered configuration")
    if not offline and step.workspace is not None:
        raise ScenarioError(f"{where}.workspace: only offline scenarios change otterdog's own configuration")
    if not offline and step.commands:
        raise ScenarioError(f"{where}.commands: only offline scenarios run extra commands")
    if step.config is not None and not step.fragments.is_empty():  # overlays included
        raise ScenarioError(f"{where}.config: a complete configuration replaces the rendering, drop fragments/overlay")
    if step.base_config is not None and step.base_fragments is not None:
        raise ScenarioError(f"{where}.base_config: give base_fragments or base_config, not both")


DELETE_GUARD_FLAGS = ("update_secrets", "update_webhooks", "only_secrets", "update_filter")  # diff flags of -d steps


def _check_apply_filter(step: StepSpec, where: str) -> None:
    """``apply -d`` is guarded by the step's own plan (DESTR-02): an apply that deletes must use the plan's repository
    filter and exactly the plan's diff flags (``--only-secrets`` hides every non-secret removal from a plan, so a
    secrets-only guard plan would let an unrestricted ``apply -d`` delete what the guard never saw)."""
    apply, plan = step.apply, step.plan
    if apply is None or not apply.delete:
        return
    if apply.repo_filter is not None and apply.repo_filter != (plan.repo_filter if plan is not None else None):
        raise ScenarioError(
            f"{where}.apply.repo_filter: an apply with delete: true removes what the step's plan showed (the guard "
            "checks that plan): set repo_filter on plan only, the apply uses it"
        )
    planned = {
        flag: getattr(plan, flag) if plan is not None else getattr(PlanSpec(), flag) for flag in DELETE_GUARD_FLAGS
    }
    applied = {flag: getattr(apply, flag) for flag in DELETE_GUARD_FLAGS}
    different = sorted(flag for flag in DELETE_GUARD_FLAGS if planned[flag] != applied[flag])
    if different:
        raise ScenarioError(
            f"{where}.apply: an apply with delete: true must use the diff flags of the step's plan (the guard checks "
            f"that plan); they differ in: {', '.join(different)}"
        )
    if applied["only_secrets"]:
        raise ScenarioError(
            f"{where}.apply: delete: true cannot be combined with only_secrets (the guard plan would not show the "
            "other removals)"
        )


def _fragments(value: Any, where: str, files: FileContext) -> ConfigFragments | None:
    """ConfigFragments of a fragments mapping (None stays None); an entry is an inline string or a file reference."""
    if value is None:
        return None
    data = _mapping(value, where)
    unknown = sorted(set(data) - set(FRAGMENT_KEYS))
    if unknown:
        raise ScenarioError(f"{where}: unknown fragment key(s) {unknown}, expected {list(FRAGMENT_KEYS)}")
    values: dict[str, Any] = {}  # FRAGMENT_KEYS -> list[str]
    for key, entries in data.items():
        items = entries if isinstance(entries, list) else ([] if entries is None else [entries])
        values[key] = [
            _snippet(item, f"{where}.{key}[{index}]", files, label=f"fragments.{key}[{index}]", role="fragment")
            for index, item in enumerate(items)
        ]
    return ConfigFragments(**values)


def _overlays(value: Any, where: str, files: FileContext) -> list[str]:
    """The step's overlays: an inline string, a file reference or a list of them (null -> [])."""
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    return [
        _snippet(item, f"{where}[{index}]", files, label=f"overlay[{index}]", role="overlay")
        for index, item in enumerate(items)
    ]


def _snippet(value: Any, where: str, files: FileContext, *, label: str, role: str) -> str:
    """An inline jsonnet string, or the SourceText of a ``{file, raw, vars}`` mapping."""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return _file_reference(value, where, files, label=label, role=role)
    raise ScenarioError(f"{where}: expected a jsonnet string or a {{file: <path>}} mapping, got {type(value).__name__}")


def _file_reference(value: Any, where: str, files: FileContext, *, label: str, role: str) -> SourceText:
    """The SourceText of a ``{file: <path>, raw: <bool>, vars: <mapping>}`` mapping (a string is a path)."""
    data: Mapping[str, Any] = {"file": value} if isinstance(value, str) else _mapping(value, where)
    _check_keys(data, FILE_KEYS, where)
    if "file" not in data:
        raise ScenarioError(f"{where}: missing 'file' (the path of the jsonnet file, relative to the scenario)")
    path = _str(data["file"], f"{where}.file")
    raw = _bool(data.get("raw", False), f"{where}.raw")
    variables = _file_variables(data.get("vars"), f"{where}.vars")
    if raw and variables:
        raise ScenarioError(f"{where}.vars: a raw file is never rendered, its vars would be ignored")
    try:
        return load_source(path, files, label=label, role=role, raw=raw, variables=variables)
    except InjectError as exc:
        raise ScenarioError(f"{where}.file: {exc}") from None


def _file_variables(value: Any, where: str) -> dict[str, Any]:
    """``vars`` of a file reference: identifier names that do not shadow an engine variable (null -> {})."""
    if value is None:
        return {}
    variables = dict(_mapping(value, where))
    for name in variables:
        _str(name, f"{where}.{name}", pattern=VARIABLE_NAME_RE)
        if name in TEMPLATE_VARIABLES or name in CONFIG_VARIABLES:
            raise ScenarioError(f"{where}: {name!r} is provided by the engine and cannot be overridden")
    return copy.deepcopy(variables)


def _libraries(value: Any, files: FileContext) -> dict[str, str]:
    """Scenario ``libraries``: jsonnet identifier -> path or ``{file, raw, vars}`` (null -> {})."""
    if value is None:
        return {}
    libraries: dict[str, str] = {}
    for name, item in _mapping(value, "libraries").items():
        problem = library_name_problem(name)
        if problem:
            raise ScenarioError(f"libraries: {problem}")
        where = f"libraries.{name}"
        libraries[name] = _file_reference(item, where, files, label=where, role="library")
    return libraries


def _config_file(value: Any, where: str, files: FileContext, *, role: str) -> str | None:
    """``config`` / ``base_config``: the SourceText of a ``{file, raw, vars}`` mapping (null -> None)."""
    if value is None:
        return None
    if not isinstance(value, Mapping):
        raise ScenarioError(f"{where}: expected a {{file: <path>}} mapping, got {type(value).__name__}")
    return _file_reference(value, where, files, label=role, role=role)


def _parse_validate(value: Any, where: str, base: ValidateSpec | None = None) -> ValidateSpec | None:
    """ValidateSpec of a mapping merged over ``base`` (null -> None)."""
    if value is None:
        return None
    data = _mapping(value, where)
    _check_keys(data, VALIDATE_KEYS, where)
    spec = copy.deepcopy(base) if base is not None else ValidateSpec()
    for key in ("errors", "warnings_min", "infos", "infos_min"):
        if key in data:
            setattr(spec, key, _int(data[key], f"{where}.{key}"))
    if "exit_code" in data:
        spec.exit_code = None if data["exit_code"] is None else _int(data["exit_code"], f"{where}.exit_code")
    if "verbose" in data:
        spec.verbose = _bool(data["verbose"], f"{where}.verbose")
    if "contains" in data:
        spec.contains = _str_list(data["contains"], f"{where}.contains")
    if "not_contains" in data:
        spec.not_contains = _str_list(data["not_contains"], f"{where}.not_contains")
    if "ok" in data:
        spec.ok = _bool(data["ok"], f"{where}.ok")
    elif "errors" in data or spec.ok is None:
        spec.ok = not spec.errors
    if spec.errors is not None and spec.ok != (spec.errors == 0):
        raise ScenarioError(f"{where}: ok {spec.ok} contradicts errors {spec.errors}")
    counted = [key for key in ("infos", "infos_min") if getattr(spec, key) is not None]
    if counted and not spec.verbose:
        raise ScenarioError(
            f"{where}: {' and '.join(counted)} need verbose: true (without -v validate hides its Info messages)"
        )
    return spec


def _parse_diff_options(data: Mapping[str, Any], spec: PlanSpec | ApplySpec, where: str) -> None:
    """Set the diff flags of ``data`` (DIFF_OPTION_KEYS) on ``spec``; an update_filter needs a forced update."""
    for key in DIFF_FLAG_KEYS:
        if key in data:
            setattr(spec, key, _bool(data[key], f"{where}.{key}"))
    for key in ("repo_filter", "update_filter"):
        if key in data:
            setattr(spec, key, None if data[key] is None else _str(data[key], f"{where}.{key}"))
    if spec.update_filter is not None and not (spec.update_secrets or spec.update_webhooks):
        raise ScenarioError(
            f"{where}.update_filter: it only selects what update_secrets / update_webhooks force, set one of them"
        )


def _parse_plan(value: Any, where: str, base: PlanSpec | None = None) -> PlanSpec | None:
    """PlanSpec of a mapping merged over ``base`` (null -> None: no plan, apply nor converge)."""
    if value is None:
        return None
    data = _mapping(value, where)
    _check_keys(data, PLAN_KEYS, where)
    spec = copy.deepcopy(base) if base is not None else PlanSpec()
    if "expect" in data:
        spec.expect = _choice(data["expect"], PLAN_EXPECTS, f"{where}.expect")
    if "contains" in data:
        spec.contains = _str_list(data["contains"], f"{where}.contains")
    if "not_contains" in data:
        spec.not_contains = _str_list(data["not_contains"], f"{where}.not_contains")
    if "counts" in data:
        counts = _mapping(data["counts"], f"{where}.counts")
        _check_keys(counts, COUNT_KEYS, f"{where}.counts")
        spec.counts = {key: _int(count, f"{where}.counts.{key}") for key, count in counts.items()}
    if "exit_code" in data:
        spec.exit_code = None if data["exit_code"] is None else _int(data["exit_code"], f"{where}.exit_code")
    _parse_diff_options(data, spec, where)
    return spec


def _parse_apply(value: Any, where: str, base: ApplySpec | None = None) -> ApplySpec | None:
    """ApplySpec of a mapping merged over ``base`` (null -> None: no apply)."""
    if value is None:
        return None
    data = _mapping(value, where)
    _check_keys(data, APPLY_KEYS, where)
    spec = copy.deepcopy(base) if base is not None else ApplySpec()
    if "expect" in data:
        spec.expect = _choice(data["expect"], APPLY_EXPECTS, f"{where}.expect")
    if "delete" in data:
        spec.delete = _bool(data["delete"], f"{where}.delete")
    if "contains" in data:
        spec.contains = _str_list(data["contains"], f"{where}.contains")
    if "not_contains" in data:
        spec.not_contains = _str_list(data["not_contains"], f"{where}.not_contains")
    _parse_diff_options(data, spec, where)
    return spec


def _parse_workspace(value: Any, where: str) -> WorkspaceLayout | None:
    """The WorkspaceLayout of an offline step's ``workspace`` mapping (null -> None, the harness layout)."""
    if value is None:
        return None
    data = _mapping(value, where)
    _check_keys(data, WORKSPACE_KEYS, where)
    config_dir = _str(data.get("config_dir", CONFIG_DIR), f"{where}.config_dir")
    problem = dir_name_problem(config_dir, f"{where}.config_dir")
    if problem:
        raise ScenarioError(problem)
    orgs = data.get("orgs")
    if orgs is not None and not isinstance(orgs, list):
        raise ScenarioError(f"{where}.orgs: expected a list of organization entries, got {type(orgs).__name__}")
    base_url = data.get("base_url")
    try:
        return WorkspaceLayout(
            format=_choice(data.get("format", "json"), CONFIG_FORMATS, f"{where}.format"),
            orgs=tuple(_workspace_org(item, f"{where}.orgs[{index}]") for index, item in enumerate(orgs or [])),
            defaults_override=_defaults_override(data.get("defaults_override"), f"{where}.defaults_override"),
            base_url=None if base_url is None else _str(base_url, f"{where}.base_url"),
            config_dir=config_dir,
            vendor=_bool(data.get("vendor", True), f"{where}.vendor"),
        )
    except ScenarioError:
        raise
    except ValueError as exc:
        raise ScenarioError(f"{where}: {exc}") from None


def _workspace_org(value: Any, where: str) -> str | dict[str, Any]:
    """An extra organization entry: a github_id, or a mapping of ORG_ENTRY_KEYS (``credentials`` only null: the
    harness writes the env provider, another provider would run its CLI)."""
    if isinstance(value, str):
        return _str(value, where)
    data = dict(_mapping(value, where))
    _check_keys(data, ORG_ENTRY_KEYS, where)
    if data.get("credentials") is not None:
        raise ScenarioError(f"{where}.credentials: only null (the harness writes the env credential provider)")
    return copy.deepcopy(data)


def _defaults_override(value: Any, where: str) -> dict[str, Any] | None:
    """The content of .otterdog-defaults.json: DEFAULTS_OVERRIDE_KEYS (and their known sub-keys) only."""
    if value is None:
        return None
    data = dict(_mapping(value, where))
    _check_keys(data, DEFAULTS_OVERRIDE_KEYS, where)
    for key, allowed in DEFAULTS_OVERRIDE_KEYS.items():
        if allowed is not None and data.get(key) is not None:
            _check_keys(_mapping(data[key], f"{where}.{key}"), allowed, f"{where}.{key}")
    return copy.deepcopy(data)


def _parse_state(value: Any, where: str) -> list[dict[str, Any]]:
    """Oracle checks (forms of scenarios.checks, validated)."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ScenarioError(f"{where}: expected a list of checks")
    checks = []
    for index, item in enumerate(value):
        check = dict(_mapping(item, f"{where}[{index}]"))
        try:
            validate_check(check)
        except ValueError as exc:
            raise ScenarioError(f"{where}[{index}]: {exc}") from None
        checks.append(copy.deepcopy(check))
    return checks


def _parse_commands(value: Any, where: str) -> dict[str, CommandSpec]:
    """Extra offline commands: {command: {exit_code, contains, not_contains}} (null spec -> defaults)."""
    if value is None:
        return {}
    data = _mapping(value, where)
    commands = {}
    for command, spec_data in data.items():
        _choice(command, OFFLINE_EXTRA_COMMANDS, f"{where}.{command}")
        spec = CommandSpec()
        if spec_data is not None:
            spec_map = _mapping(spec_data, f"{where}.{command}")
            _check_keys(spec_map, COMMAND_KEYS, f"{where}.{command}")
            if "exit_code" in spec_map:
                exit_code = spec_map["exit_code"]
                spec.exit_code = None if exit_code is None else _int(exit_code, f"{where}.{command}.exit_code")
            spec.contains = _str_list(spec_map.get("contains"), f"{where}.{command}.contains")
            spec.not_contains = _str_list(spec_map.get("not_contains"), f"{where}.{command}.not_contains")
        commands[command] = spec
    return commands


def _parse_overrides(value: Any, step: StepSpec, where: str) -> dict[str, Any]:
    """on_missing_capability: parsed replacements of validate/plan/apply (merged over the step's), state, converge."""
    where = f"{where}.on_missing_capability"
    data = _mapping(value, where)
    _check_keys(data, MISSING_CAPABILITY_KEYS, where)
    overrides: dict[str, Any] = {}
    if "validate" in data:
        overrides["validate"] = _parse_validate(data["validate"], f"{where}.validate", step.validate)
    if "plan" in data:
        overrides["plan"] = _parse_plan(data["plan"], f"{where}.plan", step.plan)
    if "apply" in data:
        overrides["apply"] = _parse_apply(data["apply"], f"{where}.apply", step.apply)
    if "state" in data:
        overrides["state"] = _parse_state(data["state"], f"{where}.state")
    if "converge" in data:
        overrides["converge"] = _bool(data["converge"], f"{where}.converge")
    return overrides


# --- cross-field rules -----------------------------------------------------------------------------------------------
def _check_tier_rules(scenario: Scenario) -> None:
    """Offline scenarios cannot depend on the live org; live ones must be org_level to change settings."""
    if scenario.tier == "offline":
        for name in ("requires", "expect_failure_without", "identities"):
            if getattr(scenario, name):
                raise ScenarioError(f"{name}: offline scenarios cannot depend on live capabilities or identities")
        if scenario.org_level:
            raise ScenarioError("org_level: offline scenarios have no org to reset")
        if scenario.min_plan != "free":
            raise ScenarioError("min_plan: offline scenarios set their plan with variables.plan")
        return
    for step in scenario.steps:
        if step.fragments.settings and not scenario.org_level:
            raise ScenarioError(f"step {step.name!r}: settings fragments change org-level state, set org_level: true")


def _check_templates(scenario: Scenario) -> None:
    """Jinja syntax and variable names of every string (file content and vars included); sample render of the step
    for the fragment, overlay and config rules."""
    environment = _environment()
    known = {*TEMPLATE_VARIABLES, *scenario.variables, *environment.globals}
    variables = {**_SAMPLE_VARIABLES, **scenario.variables}
    offline = scenario.tier == "offline"
    for step in scenario.steps:
        for text in _iter_strings(step):
            for template, names, where in _templates_of(text, known):
                _check_template_names(environment, template, names, step.name, where=where)
                _check_logins(environment, template, scenario, step.name, where=where)
        try:
            render = functools.partial(_render_text, environment, variables=variables, step=step.name)
            rendered = _map_strings(step, render)
        except ScenarioError:
            raise
        except ValueError as exc:  # a rendered value refused by its dataclass (e.g. a workspace entry)
            raise ScenarioError(f"step {step.name!r}: {exc}") from None
        problems = step_problems(rendered, offline=offline, import_path=_SAMPLE_VARIABLES["import_path"])
        if not offline and not scenario.org_level:
            problems += [
                f"overlay[{index}] changes the organization settings: set org_level: true"
                for index, overlay in enumerate(rendered.fragments.overlays)
                if overlay_changes_settings(overlay)
            ]
            problems += repo_filter_problems(rendered, _SAMPLE_RUN.prefix)
        if problems:
            raise ScenarioError(f"step {step.name!r}: " + "; ".join(problems))


def repo_filter_problems(step: StepSpec, prefix: str) -> list[str]:
    """Repository filters of a rendered live step (plan, apply, and their on_missing_capability variants) that could
    reach other repositories than this run's: each ``repo_filter`` must start with ``<prefix>-`` (the engine checks
    it again with the real run prefix; only org_level scenarios may plan or apply other repositories)."""
    problems = []
    for variant in (step, step.for_missing_capability()):
        for label, spec in (("plan", variant.plan), ("apply", variant.apply)):
            pattern = getattr(spec, "repo_filter", None)
            if pattern is not None and not pattern.startswith(f"{prefix}-"):
                problems.append(
                    f"{label}.repo_filter {pattern!r} does not start with the run prefix ('{{{{ p }}}}-', here "
                    f"'{prefix}-'): only org_level scenarios may plan or apply other repositories"
                )
    return list(dict.fromkeys(problems))


def _templates_of(text: str, known: Collection[str]) -> list[tuple[str, Collection[str], str | None]]:
    """(template, known names, location) to check for a string of a step: an inline string as it is; a file's string
    vars (scenario names) and its text unless raw (plus its vars, and import_path/project for config files)."""
    if not isinstance(text, SourceText):
        return [(text, known, None)]
    origin = text.origin
    found: list[tuple[str, Collection[str], str | None]] = [
        (value, known, f"{origin.location()} vars.{name}")
        for name, item in origin.vars.items()
        for value in _value_strings(item)
    ]
    if not origin.raw:
        names = {*known, *origin.vars, *(CONFIG_VARIABLES if origin.role in CONFIG_ROLES else ())}
        found.append((text, names, None))
    return found


def _value_strings(value: Any) -> list[str]:
    """Every string of a ``vars`` value (nested lists and mappings included)."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [text for item in value for text in _value_strings(item)]
    if isinstance(value, Mapping):
        return [text for item in value.values() for text in _value_strings(item)]
    return []


def _check_template_names(
    environment: jinja2.Environment, text: str, known: Collection[str], step: str, *, where: str | None = None
) -> None:
    """ScenarioError for Jinja syntax errors and variables no engine provides (file content: ``<file>:<line>``)."""
    if not has_jinja(text):
        return
    try:
        tree = environment.parse(str(text))
    except jinja2.TemplateSyntaxError as exc:
        location = _template_location(text, where, exc.lineno)
        raise ScenarioError(f"step {step!r}: Jinja syntax error in {location}: {exc.message or exc}") from None
    unknown = sorted(set(jinja2.meta.find_undeclared_variables(tree)) - set(known))
    if unknown:
        lines = [node.lineno for node in tree.find_all(jinja2.nodes.Name) if node.name in unknown]
        location = _template_location(text, where, min(lines) if lines else None)
        raise ScenarioError(f"step {step!r}: unknown template variable(s) {unknown} in {location}")


def _template_location(text: str, where: str | None, line: int | None) -> str:
    """``<file label> (<file>:<line>)`` for file content, ``<where> <excerpt>`` or the excerpt for inline strings."""
    if isinstance(text, SourceText):
        return text.origin.location(line)
    return f"{where} {_excerpt(text)}" if where else _excerpt(text)


def _check_logins(
    environment: jinja2.Environment, text: str, scenario: Scenario, step: str, *, where: str | None = None
) -> None:
    """``logins.<role>``: offline scenarios have none; live ones must declare every optional role in ``identities``
    (targets without it then skip the scenario instead of failing its render)."""
    if "logins" not in text or not has_jinja(text):
        return
    tree = environment.parse(str(text))
    roles = {node.attr for node in tree.find_all(jinja2.nodes.Getattr) if _is_logins(node.node)}
    roles |= {
        str(getattr(node.arg, "value", node.arg))
        for node in tree.find_all(jinja2.nodes.Getitem)
        if _is_logins(node.node)
    }
    location = f" ({_template_location(text, where, None)})" if isinstance(text, SourceText) or where else ""
    if roles and scenario.tier == "offline":
        raise ScenarioError(f"step {step!r}: offline scenarios have no logins ({sorted(roles)}){location}")
    unknown = sorted(roles - set(IDENTITY_ROLES))
    if unknown:
        raise ScenarioError(
            f"step {step!r}: unknown identities {unknown} in logins (one of {list(IDENTITY_ROLES)}){location}"
        )
    undeclared = sorted(roles - {"admin", *scenario.identities})
    if undeclared:
        raise ScenarioError(f"step {step!r}: uses logins {undeclared}: declare them in identities{location}")


def _is_logins(node: jinja2.nodes.Node) -> bool:
    """True for the ``logins`` variable node."""
    return isinstance(node, jinja2.nodes.Name) and node.name == "logins"


# --- rendering -------------------------------------------------------------------------------------------------------
def render_step(step: StepSpec, variables: Mapping[str, Any]) -> StepSpec:
    """Copy of ``step`` with every string (fragments, files, contains, state, ...) rendered once by Jinja2
    StrictUndefined; file content with its own rules (raw, vars). The rendered fragments, libraries, overlays and
    config files are checked again (secrets, imports: variables could smuggle them in), with the offline rules for
    the steps of offline scenarios (``step.offline``)."""
    environment = _environment()
    rendered = _map_strings(step, functools.partial(_render_text, environment, variables=variables, step=step.name))
    import_path = variables.get("import_path")
    path = import_path if isinstance(import_path, str) else None
    problems = step_problems(rendered, offline=rendered.offline, import_path=path)
    if problems:
        raise ScenarioError(f"step {step.name!r}: " + "; ".join(problems))
    return rendered


def _environment() -> jinja2.Environment:
    """Sandboxed, strict Jinja environment (jsonnet output: no escaping, undefined variables fail)."""
    return jinja2.sandbox.SandboxedEnvironment(  # autoescape off: renders jsonnet and plain text, not HTML
        undefined=jinja2.StrictUndefined, keep_trailing_newline=True, autoescape=False
    )


def _render_text(environment: jinja2.Environment, text: str, variables: Mapping[str, Any], step: str) -> str:
    """Render one string (ScenarioError on undefined variables or syntax errors); a file's text with its rules."""
    if isinstance(text, SourceText):
        try:
            return render_source(environment, text, variables)
        except InjectError as exc:
            raise ScenarioError(f"step {step!r}: {exc}") from None
    if not has_jinja(text):
        return text
    try:
        return environment.from_string(text).render(**variables)
    except jinja2.TemplateError as exc:
        raise ScenarioError(f"step {step!r}: cannot render {_excerpt(text)}: {exc}") from None


def _excerpt(text: str, limit: int = 80) -> str:
    """Short repr of a template string for error messages."""
    return repr(text if len(text) <= limit else text[: limit - 3] + "...")


def _map_strings(value: Any, fn: Callable[[str], str], *, skip: Collection[str] = ("name",)) -> Any:
    """Copy of ``value`` with ``fn`` applied to every string (dict keys included; ``skip`` = top-level fields kept)."""
    if isinstance(value, str):
        return fn(value)
    if isinstance(value, list):
        return [_map_strings(item, fn, skip=()) for item in value]
    if isinstance(value, tuple):
        return tuple(_map_strings(item, fn, skip=()) for item in value)
    if isinstance(value, Mapping):
        return {_map_strings(key, fn, skip=()): _map_strings(item, fn, skip=()) for key, item in value.items()}
    if is_dataclass(value) and not isinstance(value, type):
        changes = {
            f.name: _map_strings(getattr(value, f.name), fn, skip=()) for f in fields(value) if f.name not in skip
        }
        return replace(value, **changes)
    return value


def _iter_strings(value: Any) -> Iterator[str]:
    """Every string of a step (dict keys included), in field order."""
    found: list[str] = []

    def collect(text: str) -> str:
        """Remember ``text`` and keep it unchanged."""
        found.append(text)
        return text

    _map_strings(value, collect)
    yield from found


# --- fragment scanning (best effort: intentionally broken jsonnet is valid scenario input) ---------------------------
@dataclass(frozen=True)
class _Token:
    """A jsonnet token: kind (ident, string, number, colon, punct), its text (strings decoded) and its line."""

    kind: str
    text: str
    line: int = 1


_CLOSERS = {"(": ")", "[": "]", "{": "}"}
_SECRET_FRAMES = ("secret-call", "secret-object")
# constructs whose validation calls GitHub even with --local (OC-04) -> why
_GITHUB_CONSTRUCTS = {
    "newTeam": "team validation calls GitHub",
    "code_scanning_default_languages": "validation calls GitHub",
}


def fragment_problems(fragments: ConfigFragments, *, offline: bool) -> list[str]:
    """Rule violations of rendered fragments, libraries and overlays: protected settings (offline: the plan only),
    non-dummy secrets (offline: the KB-025 literal is a dummy too), import statements, trailing line comments
    (fragments), overlays replacing settings or setting protected keys, and (offline)
    teams/newTeam/code_scanning_default_languages. Secret problems never quote the snippet; problems of file content
    name ``<file>:<line>``."""
    problems = []
    if offline and fragments.teams:
        problems.append("offline scenarios cannot define teams (validation would call GitHub)")
    for key, snippets in fragments.to_mapping().items():
        for index, snippet in enumerate(snippets):
            problems += _snippet_problems(snippet, f"fragments.{key}[{index}]", kind=key, offline=offline)
    for name, text in fragments.libraries.items():
        problems += _snippet_problems(text, f"libraries.{name}", kind="library", offline=offline)
    for index, text in enumerate(fragments.overlays):
        problems += _snippet_problems(text, f"overlay[{index}]", kind="overlay", offline=offline)
    return problems


def config_problems(
    text: str, *, label: str = "config", offline: bool = True, import_path: str | None = None
) -> list[str]:
    """Rule violations of a complete offline configuration: import statements other than the template import
    (``import '<import_path>'``), non-dummy secrets and the offline restrictions."""
    return _snippet_problems(text, label, kind="config", offline=offline, import_path=import_path)


def step_problems(step: StepSpec, *, offline: bool, import_path: str | None = None) -> list[str]:
    """Rule violations of a rendered step: its fragments, BASE fragments and config files (duplicates dropped:
    the libraries are part of both fragment sets)."""
    problems = fragment_problems(step.fragments, offline=offline)
    if step.base_fragments is not None:
        problems += fragment_problems(step.base_fragments, offline=offline)
    for label, text in (("config", step.config), ("base_config", step.base_config)):
        if text is not None:
            problems += config_problems(text, label=label, offline=offline, import_path=import_path)
    return list(dict.fromkeys(problems))


def offline_problems(fragments: ConfigFragments) -> list[str]:
    """The constructs of rendered fragments (libraries and overlays included) whose validation calls GitHub even
    with --local: ``teams`` fragments, ``newTeam``, ``code_scanning_default_languages`` (OC-04)."""
    found = ["teams fragments"] if fragments.teams else []
    snippets = [snippet for items in fragments.to_mapping().values() for snippet in items]
    for snippet in [*snippets, *fragments.libraries.values(), *fragments.overlays]:
        found += [construct for _, construct in _github_constructs(_tokens(snippet)[0])]
    return list(dict.fromkeys(found))


def overlay_changes_settings(text: str) -> bool:
    """True when an overlay defines ``settings`` (best effort: the object literals of its expression)."""
    return bool(_overlay_settings(_tokens(text)[0]))


def _snippet_problems(
    snippet: str, label: str, *, kind: str, offline: bool, import_path: str | None = None
) -> list[str]:
    """Problems of one rendered snippet; ``kind`` is a FRAGMENT_KEYS key, ``library``, ``overlay`` or ``config``."""
    tokens, trailing_comment = _tokens(snippet)
    found: list[tuple[int | None, str, bool]] = []  # (line, message, the location may quote the snippet)
    forbidden = OFFLINE_FORBIDDEN_SETTINGS if offline else FORBIDDEN_SETTINGS
    if trailing_comment and kind in FRAGMENT_KEYS:
        found.append((_last_line(snippet), "ends with a line comment (the renderer appends a comma)", True))
    if kind == "settings":
        protected = [token for token in _top_level_fields(tokens) if token.text in forbidden]
        if protected:
            names = sorted({token.text for token in protected})
            found.append((protected[0].line, f"settings fragments must not set {names} (use variables.plan)", True))
    if kind == "overlay":
        found += [(line, message, True) for line, message in _overlay_problems(tokens, forbidden=forbidden)]
    secrets = _SecretScanner(tokens, secrets_list=kind == "secrets", offline=offline).scan()
    found += [(line, message, False) for line, message in secrets]
    found += [(line, message, True) for line, message in _import_problems(tokens, kind=kind, import_path=import_path)]
    if offline:
        found += [
            (line, f"offline scenarios cannot use {construct} ({_GITHUB_CONSTRUCTS[construct]})", True)
            for line, construct in _github_constructs(tokens)
        ]
    if isinstance(snippet, SourceText):  # file content: in the order of the file
        found.sort(key=lambda item: item[0] or 0)
    return [f"{_problem_location(snippet, label, line, quote=quote)}: {message}" for line, message, quote in found]


def _problem_location(snippet: str, label: str, line: int | None, *, quote: bool) -> str:
    """``<label> (<file>:<line>)`` for file content; ``<label> <excerpt>`` inline (the label alone: no quote)."""
    if isinstance(snippet, SourceText):
        return f"{label} ({snippet.origin.display}{f':{line}' if line else ''})"
    return f"{label} {_excerpt(snippet, 50)}" if quote else label


def _last_line(text: str) -> int:
    """Number of the last non-blank line of ``text``."""
    return text.rstrip().count("\n") + 1


def _tokens(text: str) -> tuple[list[_Token], bool]:
    """Tokens of a jsonnet snippet (comments/whitespace dropped) with their lines, and whether the snippet ends with a
    line comment."""
    tokens: list[_Token] = []
    index, line, trailing_comment = 0, 1, False
    while index < len(text):
        char = text[index]
        if char.isspace():
            line += char == "\n"
            index += 1
        elif text.startswith("//", index) or char == "#":
            end = text.find("\n", index)
            index, trailing_comment = (len(text) if end < 0 else end), True
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            stop = len(text) if end < 0 else end + 2
            line += text.count("\n", index, stop)
            index, trailing_comment = stop, False
        else:
            token, stop = _next_token(text, index)
            tokens.append(_Token(token.kind, token.text, line))
            line += text.count("\n", index, stop)
            index, trailing_comment = stop, False
    return tokens, trailing_comment


def _next_token(text: str, index: int) -> tuple[_Token, int]:
    """The token starting at ``index`` (not whitespace nor comment) and the index after it."""
    char = text[index]
    if text.startswith("|||", index):
        end = text.find("|||", index + 3)
        stop = len(text) if end < 0 else end
        return _Token("string", text[index + 3 : stop].strip()), (len(text) if end < 0 else end + 3)
    if char in "\"'" or (char == "@" and text[index + 1 : index + 2] in ("'", '"')):
        return _read_string(text, index)
    for kind, pattern in (("ident", _IDENT_RE), ("number", _NUMBER_RE)):
        match = pattern.match(text, index)
        if match:
            return _Token(kind, match.group()), match.end()
    if char == ":":
        end = index
        while end < len(text) and text[end] == ":":
            end += 1
        return _Token("colon", text[index:end]), end
    return _Token("punct", char), index + 1


def _read_string(text: str, index: int) -> tuple[_Token, int]:
    """A quoted ('..', "..") or verbatim (@'..', @"..") string token and the index after it."""
    verbatim = text[index] == "@"
    index += 1 if verbatim else 0
    quote, index, chars = text[index], index + 1, []
    while index < len(text):
        char = text[index]
        if verbatim and char == quote:
            if text.startswith(quote * 2, index):
                chars.append(quote)
                index += 2
                continue
            return _Token("string", "".join(chars)), index + 1
        if not verbatim and char == "\\" and index + 1 < len(text):
            chars.append(_STRING_ESCAPES.get(text[index + 1], text[index + 1]))
            index += 2
            continue
        if char == quote:
            return _Token("string", "".join(chars)), index + 1
        chars.append(char)
        index += 1
    return _Token("string", "".join(chars)), index


def _field_name(tokens: list[_Token], index: int) -> tuple[str | None, int]:
    """(name, index after the colon) when tokens[index] starts an object field ``name[+]:``, else (None, index)."""
    token = tokens[index]
    if token.kind not in ("ident", "string"):
        return None, index
    after = index + 1
    if after < len(tokens) and tokens[after].kind == "punct" and tokens[after].text == "+":
        after += 1
    if after < len(tokens) and tokens[after].kind == "colon":
        return token.text, after + 1
    return None, index


def _top_level_fields(tokens: list[_Token]) -> list[_Token]:
    """Name tokens of the fields defined at nesting depth 0 of a settings snippet (``key: v, other+: {...}``)."""
    names, depth, previous = [], 0, None
    for index, token in enumerate(tokens):
        if token.kind == "punct" and token.text in _CLOSERS:
            depth += 1
        elif token.kind == "punct" and token.text in _CLOSERS.values():
            depth = max(0, depth - 1)
        elif depth == 0 and (previous is None or (previous.kind == "punct" and previous.text == ",")):
            name, _ = _field_name(tokens, index)
            if name is not None:
                names.append(token)
        previous = token
    return names


def _is_punct(token: _Token, text: str) -> bool:
    """True for the punctuation token ``text``."""
    return token.kind == "punct" and token.text == text


def _closing(tokens: list[_Token], start: int) -> int:
    """Index of the bracket closing the opener at ``start`` (len(tokens) when it is never closed)."""
    depth = 0
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.kind == "punct" and token.text in _CLOSERS:
            depth += 1
        elif token.kind == "punct" and token.text in _CLOSERS.values():
            depth -= 1
            if depth == 0:
                return index
    return len(tokens)


def _object_fields(tokens: list[_Token], start: int) -> list[tuple[int, int]]:
    """(name index, value index) of the direct fields of the object literal opened at ``start``."""
    end = _closing(tokens, start)
    found, index, expect_field = [], start + 1, True
    while index < end:
        token = tokens[index]
        if token.kind == "punct" and token.text in _CLOSERS:  # a nested value, or a computed field name [..]
            index, expect_field = _closing(tokens, index) + 1, False
            continue
        if _is_punct(token, ","):
            index, expect_field = index + 1, True
            continue
        if expect_field:
            name, after = _field_name(tokens, index)
            if name is not None:
                found.append((index, after))
                index, expect_field = after, False
                continue
        index, expect_field = index + 1, False
    return found


def _overlay_settings(tokens: list[_Token]) -> list[tuple[_Token, bool, list[_Token]]]:
    """(name token, merged with ``+:``, direct field tokens of its object) of every ``settings`` field of the object
    literals at the top of an overlay expression (``{...}``, ``{...} + {...}``, ``cond then {...} else {...}``)."""
    found = []
    index, depth = 0, 0
    while index < len(tokens):
        token = tokens[index]
        if _is_punct(token, "{") and depth == 0:
            for name_index, value_index in _object_fields(tokens, index):
                if tokens[name_index].text != "settings":
                    continue
                merged = _is_punct(tokens[name_index + 1], "+")
                inner = []
                if value_index < len(tokens) and _is_punct(tokens[value_index], "{"):
                    inner = [tokens[field] for field, _ in _object_fields(tokens, value_index)]
                found.append((tokens[name_index], merged, inner))
            index = _closing(tokens, index) + 1
            continue
        if token.kind == "punct" and token.text in _CLOSERS:
            depth += 1
        elif token.kind == "punct" and token.text in _CLOSERS.values():
            depth = max(0, depth - 1)
        index += 1
    return found


def _overlay_problems(
    tokens: list[_Token], *, forbidden: Collection[str] = FORBIDDEN_SETTINGS
) -> list[tuple[int, str]]:
    """An overlay must merge settings (``settings+:``) and must not set the ``forbidden`` keys (plan, description,
    billing_email; offline: plan)."""
    problems = []
    replaced = "replaces the organization settings: write settings+: (settings: drops the live profile and the marker)"
    for name, merged, inner in _overlay_settings(tokens):
        if not merged:
            problems.append((name.line, replaced))
        protected = sorted({token.text for token in inner if token.text in forbidden})
        if protected:
            problems.append((name.line, f"overlays must not set settings {protected} (use variables.plan)"))
    return problems


def _import_problems(tokens: list[_Token], *, kind: str, import_path: str | None) -> list[tuple[int, str]]:
    """import/importstr/importbin statements; a config file may only ``import '<import_path>'`` (the template)."""
    problems = []
    for index, token in enumerate(tokens):
        if token.kind != "ident" or token.text not in IMPORT_KEYWORDS:
            continue
        target = tokens[index + 1] if index + 1 < len(tokens) else None
        if (
            kind == "config"
            and token.text == "import"
            and import_path
            and target is not None
            and target.kind == "string"
            and target.text == import_path
        ):
            continue
        hint = f"only import '{import_path or '<template import path>'}'" if kind == "config" else "use libraries"
        message = f"{token.text} is not allowed: the webapp evaluates one file, an import could read the workspace"
        problems.append((token.line, f"{message} ({hint})"))
    return problems


class _SecretScanner:
    """Finds secret values in a token stream: webhook ``secret`` fields anywhere and ``value`` fields of secret
    objects (``new{Org,Repo,Env}Secret(..) {..}`` incl. ``+``/chained objects, items of ``secrets: [..]`` arrays and
    top-level objects of a ``secrets`` fragment)."""

    def __init__(self, tokens: list[_Token], *, secrets_list: bool, offline: bool = False) -> None:
        """Scan ``tokens``; ``secrets_list`` marks a ``secrets`` fragment (its objects are secrets); ``offline``
        accepts the offline-only dummies (OFFLINE_SECRET_RE)."""
        self.tokens = tokens
        self.offline = offline
        self.stack: list[tuple[str, str]] = []  # (closer, frame kind)
        self.secret_next = secrets_list  # the next "{" opens a secret object
        self.pending_call = False  # previous token was a secret constructor name
        self.pending_secrets = False  # previous tokens were a ``secrets:`` field name
        self.problems: list[tuple[int, str]] = []

    def scan(self) -> list[tuple[int, str]]:
        """(line, problem) of every non-dummy secret value."""
        index = 0
        while index < len(self.tokens):
            index = self._advance(index)
        return self.problems

    def _advance(self, index: int) -> int:
        """Handle the token at ``index``; returns the index of the next token to look at."""
        token = self.tokens[index]
        if token.kind == "punct":
            self._punct(token.text)
            return index + 1
        is_call = token.kind == "ident" and bool(_SECRET_CALL_RE.match(token.text))
        name, after = _field_name(self.tokens, index)
        self.pending_call, self.secret_next, self.pending_secrets = is_call, False, name == "secrets"
        in_secret_object = self.stack[-1:] == [("}", "secret-object")]
        if name == "secret" or (name == "value" and in_secret_object):
            problem = _dummy_problem(name, self.tokens, after, offline=self.offline)
            if problem:
                line = self.tokens[after].line if after < len(self.tokens) else token.line
                self.problems.append((line, problem))
        return max(after, index + 1)

    def _punct(self, char: str) -> None:
        """Track brackets and the flags deciding whether an object is a secret."""
        if char in _CLOSERS:
            self.stack.append((_CLOSERS[char], self._frame_kind(char)))
            self.secret_next = False
        elif char in _CLOSERS.values():
            kind = self.stack.pop()[1] if self.stack and self.stack[-1][0] == char else ""
            self.secret_next = kind in _SECRET_FRAMES  # newRepoSecret(..) {..} {..}: chained objects
        else:
            self.secret_next = self.secret_next and char == "+"  # newRepoSecret(..) + {..}
        self.pending_call = self.pending_secrets = False

    def _frame_kind(self, opener: str) -> str:
        """Kind of the frame an opening bracket starts."""
        if opener == "(":
            return "secret-call" if self.pending_call else ""
        if opener == "[":
            return "secrets-array" if self.pending_secrets else ""
        in_secrets_array = self.stack[-1:] == [("]", "secrets-array")]
        return "secret-object" if self.secret_next or in_secrets_array else ""


def is_dummy_secret(value: str, *, offline: bool = False) -> bool:
    """True for a secret value a scenario may hold: empty, ``****``, ``e2e-dummy-<8 [0-9a-z]>``, a ``pass:<path>``
    reference (shell-safe path), a ``<provider>:e2e/<path>`` reference of a provider otterdog does not resolve, and
    offline the KB-025 literal (``pass:a:b``, several ``:``)."""
    if not value or DUMMY_SECRET_RE.match(value) or SECRET_REFERENCE_RE.match(value):
        return True
    if E2E_SECRET_REFERENCE_RE.match(value):
        return True
    return offline and bool(OFFLINE_SECRET_RE.match(value))


def _dummy_problem(name: str, tokens: list[_Token], index: int, *, offline: bool = False) -> str | None:
    """Problem of the value expression starting at ``index`` (a dummy literal, an empty string or null is fine)."""
    end = index + 1
    terminated = end >= len(tokens) or (tokens[end].kind == "punct" and tokens[end].text in ",}")
    if index >= len(tokens) or not terminated:
        return f"{name} must be a literal dummy value ({DUMMY_HINT})"
    value = tokens[index]
    if value.kind == "ident" and value.text == "null":
        return None
    if value.kind == "string" and is_dummy_secret(value.text, offline=offline):
        return None
    return f"{name} is not a dummy value: use {DUMMY_HINT} (otterdog prints it)"


def _github_constructs(tokens: list[_Token]) -> list[tuple[int, str]]:
    """(line, construct) of the constructs that make validate/local-plan call GitHub even with --local (OC-04).

    code_scanning_default_languages only makes validation read the repository languages from GitHub while the default
    setup is enabled (Repository.requires_language_validation, otterdog >= 1.4): languages set in an object that also
    sets ``code_scanning_default_setup_enabled: false`` are validated offline (the language enum)."""
    found = []
    team = next((token for token in tokens if token.kind == "ident" and token.text == "newTeam"), None)
    if team is not None:
        found.append((team.line, "newTeam"))
    for index, token in enumerate(tokens):
        if _field_name(tokens, index)[0] == "code_scanning_default_languages" and not _setup_disabled_beside(
            tokens, index
        ):
            found.append((token.line, "code_scanning_default_languages"))
            break
    return found


def _setup_disabled_beside(tokens: list[_Token], index: int) -> bool:
    """True when the object holding the field at ``index`` also sets ``code_scanning_default_setup_enabled`` to the
    literal ``false`` (a field of the same object, at its own nesting depth)."""
    depth, start = 0, None
    for position in range(index - 1, -1, -1):  # the opening brace of the enclosing object
        token = tokens[position]
        if token.kind == "punct" and token.text in _CLOSERS.values():
            depth += 1
        elif token.kind == "punct" and token.text in _CLOSERS:
            if depth == 0:
                start = position if token.text == "{" else None
                break
            depth -= 1
    if start is None:
        return False
    depth = 0
    for position in range(start + 1, len(tokens)):
        token = tokens[position]
        if token.kind == "punct" and token.text in _CLOSERS:
            depth += 1
        elif token.kind == "punct" and token.text in _CLOSERS.values():
            if depth == 0:
                return False
            depth -= 1
        elif depth == 0:
            name, after = _field_name(tokens, position)
            if name == "code_scanning_default_setup_enabled":
                value = tokens[after] if after < len(tokens) else None
                closed = after + 1 >= len(tokens) or tokens[after + 1].text in (",", "}")
                return value is not None and value.kind == "ident" and value.text == "false" and closed
    return False


# --- editor support --------------------------------------------------------------------------------------------------
SCHEMA_FILE = ".vscode/scenario.schema.json"  # yaml.schemas of .vscode/settings.json (redhat.vscode-yaml)


def json_schema() -> dict[str, Any]:
    """JSON schema (draft-07) of the scenario YAML keys for editors (completion and key checks only).

    The loader stays the reference for every rule (Jinja, fragment and secret checks, tier rules, ...); a unit test
    keeps the committed SCHEMA_FILE equal to this function's output.
    """
    from otterdog_e2e.scenarios.checks import CHECK_KINDS

    strings = {"type": "array", "items": {"type": "string"}}
    file_ref = {
        "type": "object",
        "properties": {
            "file": {
                "type": "string",
                "description": "jsonnet file, relative to the scenario file (inside the project)",
            },
            "raw": {"type": "boolean", "description": "true: insert the file as it is (no Jinja rendering)"},
            "vars": {"type": "object", "description": "extra Jinja variables of this file"},
        },
        "required": ["file"],
        "additionalProperties": False,
    }
    entry = {"oneOf": [{"type": "string"}, file_ref]}
    snippets = {"oneOf": [{"type": "string"}, file_ref, {"type": "array", "items": entry}]}
    fragments = {
        "type": "object",
        "properties": dict.fromkeys(FRAGMENT_KEYS, snippets),
        "additionalProperties": False,
    }
    counts = {
        "type": "object",
        "properties": {key: {"type": "integer"} for key in COUNT_KEYS},
        "additionalProperties": False,
    }
    texts = {"contains": strings, "not_contains": strings}
    exit_code = {"type": ["integer", "null"], "description": "expected exit code (null: not checked)"}
    validate_properties = {
        "ok": {"type": "boolean"},
        "errors": {"type": "integer"},
        "warnings_min": {"type": "integer"},
        "infos": {"type": "integer", "description": "exact number of Info messages (needs verbose: true)"},
        "infos_min": {"type": "integer", "description": "minimum number of Info messages (needs verbose: true)"},
        "exit_code": exit_code,
        "verbose": {"type": "boolean", "description": "validate -v: otterdog prints its Info messages"},
    }
    validate = {
        "type": ["object", "null"],
        "properties": {key: (validate_properties | texts)[key] for key in VALIDATE_KEYS},
        "additionalProperties": False,
    }
    pattern = {"type": ["string", "null"]}
    diff_options = {
        "repo_filter": pattern | {"description": "-r: shell pattern of the repositories (live: starts with {{ p }}-)"},
        "update_secrets": {"type": "boolean", "description": "--update-secrets: forced update of every secret"},
        "update_webhooks": {"type": "boolean", "description": "--update-webhooks: forced update of webhooks"},
        "update_filter": pattern | {"description": "--update-filter: secret names / webhook urls forced (pattern)"},
        "only_secrets": {"type": "boolean", "description": "--only-secrets: only secret changes"},
        "verbose": {"type": "boolean", "description": "-v: Info messages"},
    }
    plan_properties = {"expect": {"enum": list(PLAN_EXPECTS)}, "counts": counts, "exit_code": exit_code}
    plan = {
        "type": ["object", "null"],
        "properties": {key: (plan_properties | diff_options | texts)[key] for key in PLAN_KEYS},
        "additionalProperties": False,
    }
    apply_properties = {"expect": {"enum": list(APPLY_EXPECTS)}, "delete": {"type": "boolean"}}
    apply = {
        "type": ["object", "null"],
        "properties": {key: (apply_properties | diff_options | texts)[key] for key in APPLY_KEYS},
        "additionalProperties": False,
    }
    org_entry = {
        "type": "object",
        "properties": {key: {"description": "otterdog.json organization entry key"} for key in ORG_ENTRY_KEYS}
        | {"credentials": {"type": "null"}},
        "additionalProperties": False,
    }
    workspace = {
        "type": ["object", "null"],
        "description": "offline only: otterdog's own configuration for this step (WorkspaceLayout)",
        "properties": {
            "format": {"enum": list(CONFIG_FORMATS)},
            "orgs": {"type": "array", "items": {"oneOf": [{"type": "string"}, org_entry]}},
            "defaults_override": {
                "type": ["object", "null"],
                "description": "content of .otterdog-defaults.json (merged over the defaults of otterdog.json)",
                "properties": {key: {} for key in DEFAULTS_OVERRIDE_KEYS},
                "additionalProperties": False,
            },
            "base_url": {"type": ["string", "null"]},
            "config_dir": {"type": "string", "pattern": r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$"},
            "vendor": {"type": "boolean", "description": "false: no vendored template (--local commands fail)"},
        },
        "additionalProperties": False,
    }
    state = {
        "type": ["array", "null"],
        "items": {"type": "object", "properties": {"kind": {"enum": sorted(CHECK_KINDS)}}, "required": ["kind"]},
    }
    command = {
        "type": ["object", "null"],
        "properties": {"exit_code": {"type": ["integer", "null"]}} | texts,
        "additionalProperties": False,
    }
    phases = {"validate": validate, "plan": plan, "apply": apply, "state": state, "converge": {"type": "boolean"}}
    config = {"oneOf": [file_ref, {"type": "null"}]}
    step_properties: dict[str, Any] = {
        "name": {"type": "string", "pattern": STEP_NAME_RE.pattern},
        "known_bug": {
            "oneOf": [
                {"type": ["string", "null"], "pattern": KNOWN_BUG_ID_RE.pattern},
                {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "pattern": KNOWN_BUG_ID_RE.pattern},
                        "phases": {"type": "array", "items": {"enum": list(KNOWN_BUG_PHASES)}, "minItems": 1},
                    },
                    "required": ["id", "phases"],
                    "additionalProperties": False,
                },
            ],
            "description": "known bug of this step only (optionally of some of its phases): its failures are expected"
            " while the bug affects the SUT",
        },
        "fragments": fragments,
        "overlay": snippets,
        "base_fragments": {"oneOf": [fragments, {"type": "null"}]},
        "config": config,
        "base_config": config,
        "workspace": workspace,
        **phases,
        "on_missing_capability": {
            "type": "object",
            "properties": {key: phases[key] for key in MISSING_CAPABILITY_KEYS},
            "additionalProperties": False,
        },
        "commands": {
            "type": ["object", "null"],
            "properties": dict.fromkeys(OFFLINE_EXTRA_COMMANDS, command),
            "additionalProperties": False,
        },
    }
    step = {
        "type": "object",
        "properties": {key: step_properties[key] for key in STEP_KEYS},
        "additionalProperties": False,
    }
    capabilities = {"type": "array", "items": {"enum": [cap.value for cap in Cap]}}
    delta: dict[str, Any] = {
        "type": "object",
        "description": "a delta between base and head the change causes in this scenario (fnmatch patterns)",
        "properties": {
            "step": {"type": "string", "description": "step name pattern (a step of this scenario)"},
            "kind": {"type": "string", "description": "observation kind pattern (cli, oracle, ...)"},
            "key": {"type": "string", "description": "observation key pattern (validate, local-plan, ...)"},
            "note": {"type": "string"},
        },
        "additionalProperties": False,
    }
    reference_properties: dict[str, Any] = {
        "pr": {"type": "integer", "minimum": 1, "description": "eclipse-csi/otterdog pull request number"},
        "change": {"type": "string", "pattern": SLUG_RE.pattern, "description": "named change without upstream PR"},
        "note": {"type": "string", "description": "what the change did to this behaviour"},
        "expected_deltas": {"type": "array", "items": delta},
        "base": {"type": "string", "description": "differential base of the change (release, tag, branch or sha spec)"},
        "template": {"enum": list(TEMPLATE_MODES), "description": "template both differential sides vendor"},
    }
    assert set(reference_properties) == set(REFERENCE_KEYS) and set(delta["properties"]) == set(DELTA_KEYS)
    reference = {
        "oneOf": [
            {
                "type": "object",
                "properties": {key: value for key, value in reference_properties.items() if key != other},
                "required": [required],
                "additionalProperties": False,
            }
            for required, other in (("pr", "change"), ("change", "pr"))
        ]
    }
    properties: dict[str, Any] = {
        "id": {"type": "string", "pattern": ID_RE.pattern},
        "title": {"type": "string"},
        "description": {"type": "string"},
        "tier": {"enum": list(TIERS)},
        "priority": {"enum": list(PRIORITIES)},
        "min_plan": {"enum": list(PLANS)},
        "requires": capabilities,
        "expect_failure_without": capabilities,
        "identities": {"type": "array", "items": {"enum": list(IDENTITY_ROLES)}},
        "tags": {"type": "array", "items": {"type": "string", "pattern": TAG_RE.pattern}},
        "known_bug": {"type": ["string", "null"], "pattern": KNOWN_BUG_ID_RE.pattern},
        "org_level": {"type": "boolean"},
        "observe": {"type": "boolean"},
        "variables": {"type": "object"},
        "libraries": {
            "type": "object",
            "description": "jsonnet identifier -> library file, inlined as 'local <name> = (<file>);'",
            "propertyNames": {"pattern": r"^[A-Za-z_][A-Za-z0-9_]*$"},
            "additionalProperties": {"oneOf": [{"type": "string"}, file_ref]},
        },
        "fixed_in": {"type": "string", "description": "first otterdog version (PEP 440) the scenario asserts"},
        "references": {
            "type": "array",
            "description": "otterdog pull requests (pr) or named changes (change) behind this behaviour",
            "items": reference,
        },
        "timeout": {"type": "integer", "minimum": 1, "description": "pytest timeout of the item, in seconds"},
        "steps": {"type": "array", "minItems": 1, "items": step},
        "cleanup": {"enum": list(CLEANUP_MODES)},
    }
    return {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "title": "otterdog-e2e scenario",
        "description": f"Generated by otterdog_e2e.scenarios.model.json_schema() into {SCHEMA_FILE}: do not edit.",
        "type": "object",
        "properties": {key: properties[key] for key in SCENARIO_KEYS},
        "required": ["id", "title", "steps"],
        "additionalProperties": False,
    }
