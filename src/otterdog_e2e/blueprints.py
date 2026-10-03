"""Blueprints, policies and workflow events of the webapp tier: definitions, remediation PRs, statuses, workflows.

Verified in otterdog main @9bdeb75 (otterdog/webapp/blueprints/*, policies/*, tasks/fetch_*.py, tasks/blueprints/*,
utils.py, internal/routes.py, webhook/__init__.py):

* blueprint YAML: ``id`` and ``type`` (required_file | pin_workflow | append_configuration | scorecard_integration)
  required, ``name``, ``description``, ``config`` (flattened into the model). Global definitions live in
  ``blueprints/*.yml`` of the configs repository (OTTERDOG_CONFIG_REPO, read with OTTERDOG_CONFIG_TOKEN) and are
  de-duplicated by TYPE (one global blueprint per type); org definitions in ``otterdog/blueprints/*.yml`` of the org
  config repository, where a global id wins over an org id. Remediation branches are ``otterdog/blueprint/<id>``, PR
  titles ``chore(otterdog): ...`` (PR_TITLES); a PR closed unmerged dismisses the blueprint for its repository (also
  found again on GitHub after a database loss), a merged one sets it to ``recheck``;
* policy YAML: ``type`` (macos_large_runners | dependency_track_upload), ``name``, ``description`` and ``config``
  (required). Global ``policies/*.yml`` (one per type), org ``otterdog/policies/*.yml`` merged over the global one
  (``Policy.merge``: name/description/path from the org file, macos ``allowed`` and dependency-track
  ``workflow_filter`` from the org config, ``artifact_name`` stays global);
* /internal/init reloads the global definitions and schedules FetchBlueprintsTask / FetchPoliciesTask per active
  installation; a push to the config repository's default branch touching ``otterdog/blueprints`` or
  ``otterdog/policies`` schedules them too; /internal/check[/<limit>] evaluates the blueprints whose last check is
  older than BLUEPRINT_CHECK_INTERVAL (0 in the e2e stack);
* the macos_large_runners policy cancels queued jobs whose labels start with ``macos`` and end with ``large`` unless
  allowed (counters on /admin/policies); dependency_track_upload uploads the ``artifact_name`` artifact (bom.json +
  metadata.json) of successful runs whose referenced workflows match ``workflow_filter`` (re.search) to
  DEPENDENCY_TRACK_URL (the compose dtrack mock).

Safety: definitions are files named ``e2e-<run>-<slug>.yml`` in those four directories only, blueprint ids carry the
run id (so do their remediation branches), workflows ``.github/workflows/e2e-<run>-<slug>.yml`` go to this run's
repositories only, remediation PRs are only closed, reopened or merged when their branch belongs to this run (config
repository merges go through the guarded ConfigRepoFlow), and a larger-runner job is only dispatched where no runner
can pick it up (no ``larger_runners`` capability: a Free org) unless billing is explicitly accepted. Every mutation
goes through the Mutator (commit_files, close_pull, merge_pull, create_ref, reopen_pull, dispatch_workflow,
cancel_workflow_run); cleanup() cancels the runs, closes the PRs and removes the definitions it created.
"""

from __future__ import annotations

import logging
import posixpath
import re
import time
import urllib.parse
from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import yaml

from otterdog_e2e import naming, waiting
from otterdog_e2e.config_repo import (
    BLUEPRINT_BRANCH_PREFIX,
    DeliveryTimeoutError,
    ReactionTimeoutError,
    check_forwarded,
    run_branch,
)
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.webapp.api import parse_timestamp

if TYPE_CHECKING:
    from otterdog_e2e.config_repo import ConfigRepoFlow
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.webapp.api import WebappApi
    from otterdog_e2e.webhooks.relay import DeliveryRelay, RelayedDelivery

_logger = logging.getLogger(__name__)

BLUEPRINT = "blueprint"
POLICY = "policy"
KINDS = (BLUEPRINT, POLICY)
GLOBAL = "global"  # the configs repository (OTTERDOG_CONFIG_REPO)
ORG = "org"  # the org config repository
SCOPES = (GLOBAL, ORG)
DEFINITION_DIRS: Mapping[tuple[str, str], str] = {
    (BLUEPRINT, GLOBAL): "blueprints",
    (BLUEPRINT, ORG): "otterdog/blueprints",
    (POLICY, GLOBAL): "policies",
    (POLICY, ORG): "otterdog/policies",
}
BLUEPRINT_TYPES = ("required_file", "pin_workflow", "append_configuration", "scorecard_integration")
POLICY_TYPES = ("macos_large_runners", "dependency_track_upload")
BLUEPRINT_STATUSES = ("not_checked", "success", "failure", "remediation_prepared", "dismissed", "recheck")
PR_TITLES: Mapping[str, str] = {  # otterdog/webapp/tasks/blueprints/*.py
    "required_file": "chore(otterdog): adding / updating file(s) due to blueprint `{id}`",
    "pin_workflow": "chore(otterdog): pinning workflows due to blueprint `{id}`",
    "append_configuration": "chore(otterdog): updating configuration due to blueprint `{id}`",
    "scorecard_integration": "chore(otterdog): adding scorecard analysis workflow due to blueprint `{id}`",
}
TASK_TYPES: Mapping[str, str] = {  # TaskModel.type of the evaluation task of each blueprint type
    "required_file": "CheckFilesTask",
    "pin_workflow": "PinWorkflowTask",
    "append_configuration": "AppendConfigurationTask",
    "scorecard_integration": "CheckScorecardIntegrationTask",
}
FETCH_TASKS = ("FetchBlueprintsTask", "FetchPoliciesTask")
POLICY_COUNTERS = ("total_workflow_jobs", "permitted_on_restricted_runners", "cancelled_on_restricted_runners")
DISMISSAL_MARKER = "<!-- Otterdog Comment: blueprint-dismissal -->"
WORKFLOW_DIR = ".github/workflows"
DEFINITION_SUFFIX = ".yml"
# action pins of this repository's own workflows (.github/workflows/*.yml)
CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"  # v7.0.1
UPLOAD_ARTIFACT_ACTION = "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a"  # v7.0.1
SCORECARD_ACTION = "ossf/scorecard-action@2d1146689b8cda280b9bc96326124645441f03bc"  # v2.4.4
LARGE_RUNNER_LABEL = "macos-latest-large"
ACTIVE_RUN_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending", "action_required"})
CLOCK_SKEW = timedelta(seconds=60)
_RUNS_ON_RE = re.compile(r"^\s*runs-on:\s*(.+?)\s*$", re.MULTILINE)
_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")


class BlueprintError(RuntimeError):
    """Misuse of the blueprint helpers (foreign names, conflicting global definitions, unknown workflows)."""


# --- definitions ---------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class RequiredFile:
    """One file of a required_file blueprint (``content`` is a mustache template: repo_name, github_id, ...)."""

    path: str
    content: str
    strict: bool = False

    def to_config(self) -> dict[str, Any]:
        """The ``files`` entry of the blueprint config."""
        return {"path": self.path, "content": self.content, "strict": self.strict}


def _selector(name_pattern: str | Sequence[str] | None) -> dict[str, Any]:
    """``{repo_selector: {name_pattern}}`` (re.fullmatch on repository names; a list is joined with '|')."""
    if name_pattern is None:
        return {}
    pattern = name_pattern if isinstance(name_pattern, str) else list(name_pattern)
    return {"repo_selector": {"name_pattern": pattern}}


def _dump(document: Mapping[str, Any]) -> str:
    """YAML text of a definition document (keys in insertion order)."""
    return yaml.safe_dump(dict(document), sort_keys=False, default_flow_style=False, allow_unicode=True, width=1000)


@dataclass(frozen=True)
class BlueprintDefinition:
    """A blueprint definition: id (this run's ``e2e-<run>-<slug>``), type, config, optional name and description."""

    id: str
    type: str
    config: Mapping[str, Any] = field(default_factory=dict)
    name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Known type, an e2e id (its remediation branch then carries the run id)."""
        if self.type not in BLUEPRINT_TYPES:
            raise ValueError(f"unknown blueprint type {self.type!r}, expected one of {BLUEPRINT_TYPES}")
        if not naming.is_e2e_name(self.id) or "/" in self.id:
            raise ValueError(f"blueprint id {self.id!r} must be an e2e name (e2e-<run>-<slug>)")

    @property
    def remediation_branch(self) -> str:
        """``otterdog/blueprint/<id>``."""
        return f"{BLUEPRINT_BRANCH_PREFIX}{self.id}"

    @property
    def pr_title(self) -> str:
        """Title of the remediation PR the webapp opens."""
        return PR_TITLES[self.type].format(id=self.id)

    @property
    def task_type(self) -> str:
        """TaskModel.type of the evaluation task."""
        return TASK_TYPES[self.type]

    def to_document(self) -> dict[str, Any]:
        """The YAML document: id, type, name, description, config."""
        document: dict[str, Any] = {"id": self.id, "type": self.type}
        if self.name is not None:
            document["name"] = self.name
        if self.description is not None:
            document["description"] = self.description
        document["config"] = dict(self.config)
        return document

    def to_yaml(self) -> str:
        """The definition file's text."""
        return _dump(self.to_document())

    @classmethod
    def required_file(
        cls,
        blueprint_id: str,
        *,
        files: Sequence[RequiredFile | Mapping[str, Any]],
        name_pattern: str | Sequence[str] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> BlueprintDefinition:
        """required_file: repositories matching ``name_pattern`` must contain ``files``."""
        if not files:
            raise ValueError("a required_file blueprint needs at least one file")
        entries = [item.to_config() if isinstance(item, RequiredFile) else dict(item) for item in files]
        return cls(blueprint_id, "required_file", {**_selector(name_pattern), "files": entries}, name, description)

    @classmethod
    def pin_workflow(
        cls,
        blueprint_id: str,
        *,
        name_pattern: str | Sequence[str] | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> BlueprintDefinition:
        """pin_workflow: ``uses:`` references of the matching repositories' workflows get pinned to commit shas."""
        return cls(blueprint_id, "pin_workflow", _selector(name_pattern), name, description)

    @classmethod
    def append_configuration(
        cls,
        blueprint_id: str,
        *,
        condition: str,
        content: str,
        reviewers: Sequence[str] = (),
        name: str | None = None,
        description: str | None = None,
    ) -> BlueprintDefinition:
        """append_configuration: when the JSONata ``condition`` holds on the stored org configuration, a config PR
        appends `` + <content>`` (mustache) to the org file and requests ``reviewers`` (team slugs)."""
        config = {"condition": condition, "content": content, "reviewers": list(reviewers)}
        return cls(blueprint_id, "append_configuration", config, name, description)

    @classmethod
    def scorecard_integration(
        cls,
        blueprint_id: str,
        *,
        workflow_content: str,
        name_pattern: str | Sequence[str] | None = None,
        workflow_name: str | None = None,
        scorecard_action: str | None = None,
        name: str | None = None,
        description: str | None = None,
    ) -> BlueprintDefinition:
        """scorecard_integration: matching repositories without a workflow using ``scorecard_action`` get
        ``.github/workflows/<workflow_name>`` (``workflow_content``, mustache) through a PR."""
        config: dict[str, Any] = {**_selector(name_pattern), "workflow_content": workflow_content}
        if workflow_name is not None:
            config["workflow_name"] = workflow_name
        if scorecard_action is not None:
            config["scorecard_action"] = scorecard_action
        return cls(blueprint_id, "scorecard_integration", config, name, description)


@dataclass(frozen=True)
class PolicyDefinition:
    """A policy definition: type, config, optional name and description (policies have no id)."""

    type: str
    config: Mapping[str, Any] = field(default_factory=dict)
    name: str | None = None
    description: str | None = None

    def __post_init__(self) -> None:
        """Known type."""
        if self.type not in POLICY_TYPES:
            raise ValueError(f"unknown policy type {self.type!r}, expected one of {POLICY_TYPES}")

    def to_document(self) -> dict[str, Any]:
        """The YAML document: type, name, description, config (``config`` is required by read_policy)."""
        document: dict[str, Any] = {"type": self.type}
        if self.name is not None:
            document["name"] = self.name
        if self.description is not None:
            document["description"] = self.description
        document["config"] = dict(self.config)
        return document

    def to_yaml(self) -> str:
        """The definition file's text."""
        return _dump(self.to_document())

    @classmethod
    def macos_large_runners(
        cls, *, allowed: bool, name: str | None = None, description: str | None = None
    ) -> PolicyDefinition:
        """macos_large_runners: queued jobs on ``macos*large`` runners are cancelled unless ``allowed``."""
        return cls("macos_large_runners", {"allowed": bool(allowed)}, name, description)

    @classmethod
    def dependency_track_upload(
        cls, *, artifact_name: str, workflow_filter: str, name: str | None = None, description: str | None = None
    ) -> PolicyDefinition:
        """dependency_track_upload: the ``artifact_name`` artifact of successful runs referencing a workflow matching
        ``workflow_filter`` (re.search) is uploaded to Dependency-Track."""
        re.compile(workflow_filter)
        return cls(
            "dependency_track_upload",
            {"artifact_name": artifact_name, "workflow_filter": workflow_filter},
            name,
            description,
        )


# --- workflow files ------------------------------------------------------------------------------------------------
def runner_labels(content: str) -> list[str]:
    """The ``runs-on`` labels of a workflow file (a single label or a flow list such as ``[self-hosted, x]``)."""
    labels: list[str] = []
    for match in _RUNS_ON_RE.finditer(content):
        value = match.group(1).split("#", 1)[0]
        labels.extend(label for label in _LABEL_RE.findall(value.replace("'", " ").replace('"', " ")))
    return labels


def uses_larger_runner(content: str) -> bool:
    """True when a job runs on a restricted macOS larger runner (the policy's rule: ``macos*`` ... ``*large``)."""
    return any(label.startswith("macos") and label.endswith("large") for label in runner_labels(content))


def large_runner_workflow(run_id: str, *, label: str = LARGE_RUNNER_LABEL) -> str:
    """A workflow_dispatch workflow with one job on ``label`` (a queued workflow_job for the macos_large_runners
    policy); on a Free org no runner ever picks it up, the policy or the harness cancels it."""
    return f"""# otterdog-e2e {run_id}: emits a queued workflow_job on {label} (macos_large_runners policy)
name: e2e-{run_id}-large-runner
on:
  workflow_dispatch: {{}}
permissions: {{}}
jobs:
  large:
    runs-on: {label}
    timeout-minutes: 1
    steps:
      - run: echo "otterdog-e2e {run_id} - this job is cancelled by the policy or the harness"
"""


def reusable_workflow_ref(org: str, repo: str, path: str, *, ref: str = "main") -> str:
    """``<org>/<repo>/<path>@<ref>``: how a run calls (and GitHub records in referenced_workflows) a reusable
    workflow."""
    return f"{org}/{repo}/{path}@{ref}"


def sbom_store_workflow(run_id: str, *, artifact_name: str) -> str:
    """A reusable workflow (on: workflow_call) storing bom.json + metadata.json as the artifact ``artifact_name``
    (what the dependency_track_upload policy downloads); inputs project-name, project-version, parent-project."""
    return f"""# otterdog-e2e {run_id}: reusable workflow storing SBOM data (dependency_track_upload policy)
name: e2e-{run_id}-store-sbom
on:
  workflow_call:
    inputs:
      project-name: {{type: string, required: true}}
      project-version: {{type: string, required: true}}
      parent-project: {{type: string, required: false, default: "00000000-0000-0000-0000-000000000000"}}
permissions: {{}}
jobs:
  store:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    steps:
      - name: write the SBOM data
        env:
          PROJECT_NAME: ${{{{ inputs.project-name }}}}
          PROJECT_VERSION: ${{{{ inputs.project-version }}}}
          PARENT_PROJECT: ${{{{ inputs.parent-project }}}}
        run: |
          mkdir -p e2e-sbom
          python3 - <<'PY'
          import json, os
          bom = {{"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "components": []}}
          meta = {{"projectName": os.environ["PROJECT_NAME"], "projectVersion": os.environ["PROJECT_VERSION"],
                  "parentProject": os.environ["PARENT_PROJECT"]}}
          json.dump(bom, open("e2e-sbom/bom.json", "w"))
          json.dump(meta, open("e2e-sbom/metadata.json", "w"))
          PY
      - uses: {UPLOAD_ARTIFACT_ACTION}
        with:
          name: {artifact_name}
          path: e2e-sbom/
          retention-days: 1
"""


def sbom_caller_workflow(
    run_id: str, *, store_workflow: str, project_name: str, project_version: str = "1.0.0", parent_project: str = ""
) -> str:
    """A workflow_dispatch workflow calling the reusable ``store_workflow`` (``<org>/<repo>/<path>@<ref>``): its
    completed run references it (workflow_run.referenced_workflows)."""
    parent = f"\n      parent-project: {parent_project}" if parent_project else ""
    return f"""# otterdog-e2e {run_id}: calls the reusable SBOM workflow (dependency_track_upload policy)
name: e2e-{run_id}-sbom
on:
  workflow_dispatch: {{}}
permissions: {{}}
jobs:
  sbom:
    uses: {store_workflow}
    with:
      project-name: {project_name}
      project-version: {project_version}{parent}
"""


def sbom_workflow_filter(store_path: str) -> str:
    """workflow_filter matching the reusable workflow ``store_path`` (re.search on referenced_workflows[].path)."""
    return re.escape(store_path)


def unpinned_workflow(run_id: str, *, uses: str = "actions/checkout@v4") -> str:
    """A workflow_dispatch workflow using an unpinned action (``uses: owner/repo@tag``) for the pin_workflow
    blueprint; it is never dispatched by the helpers."""
    return f"""# otterdog-e2e {run_id}: an unpinned action reference (pin_workflow blueprint)
name: e2e-{run_id}-unpinned
on:
  workflow_dispatch: {{}}
permissions: {{}}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: {uses}
"""


def scorecard_workflow(run_id: str) -> str:
    """workflow_content of a scorecard_integration blueprint: the scorecard action on workflow_dispatch only (merging
    the remediation PR starts nothing)."""
    return f"""# otterdog-e2e {run_id}: scorecard analysis added by the scorecard_integration blueprint
name: e2e-{run_id}-scorecard
on:
  workflow_dispatch: {{}}
permissions: read-all
jobs:
  analysis:
    runs-on: ubuntu-latest
    permissions:
      id-token: write
    steps:
      - uses: {CHECKOUT_ACTION}
        with:
          persist-credentials: false
      - uses: {SCORECARD_ACTION}
        with:
          results_file: results.sarif
          results_format: sarif
          publish_results: false
"""


@dataclass(frozen=True)
class WorkflowDispatch:
    """One workflow dispatch of the helper: the run id when GitHub returned it (return_run_details)."""

    repo: str
    workflow: str  # file name
    after: datetime  # just before the dispatch
    run_id: int | None = None


@dataclass(frozen=True)
class SbomWorkflows:
    """The two workflow files of the dependency_track_upload case."""

    caller: str  # .github/workflows/e2e-<run>-<slug>.yml (dispatch this one)
    store: str  # .github/workflows/e2e-<run>-<slug>-store.yml (reusable)
    workflow_filter: str  # matches the store workflow in referenced_workflows
    artifact_name: str


# --- the helper ----------------------------------------------------------------------------------------------------
def _utc_now() -> datetime:
    """Current aware UTC time."""
    return datetime.now(UTC)


def _q(value: str) -> str:
    """URL-encode one path segment."""
    return urllib.parse.quote(str(value), safe="")


def _call(mutator: Mutator, name: str, *args: Any, **kwargs: Any) -> Any:
    """``mutator.<name>(*args, **kwargs)``; BlueprintError when a Mutator stand-in lacks the mutation (the real Mutator
    and testing.fakes.RecordingMutator offer every one the helper uses)."""
    method = getattr(mutator, name, None)
    if method is None:
        raise BlueprintError(f"the Mutator has no {name}(): otterdog_e2e.github.mutate must provide it")
    return method(*args, **kwargs)


class BlueprintHelper:
    """Blueprint and policy definitions, webapp triggers and reads, remediation PRs and workflow events of one test.

    ``api`` (the webapp under test) is needed for reload/check/status reads, ``flow`` for config-repository
    remediation merges, ``relay`` for workflow delivery waits; ``purgeable`` (E2EContext.purgeable) lets
    sweep_stale() remove definitions left by finished runs, which would shadow this run's global ones.
    """

    def __init__(
        self,
        *,
        org: str,
        configs_repo: str,
        config_repo: str,
        run_ctx: RunContext,
        oracle: Oracle,
        mutator: Mutator,
        api: WebappApi | None = None,
        flow: ConfigRepoFlow | None = None,
        relay: DeliveryRelay | None = None,
        larger_runners: bool = False,
        purgeable: Callable[[str], bool] | None = None,
        timeout: float = 300,
    ) -> None:
        """Bind the helper (nothing is written yet)."""
        self.org = org
        self.configs_repo = configs_repo
        self.config_repo = config_repo
        self.run_ctx = run_ctx
        self.oracle = oracle
        self.mutator = mutator
        self.api = api
        self.flow = flow
        self.relay = relay
        self.larger_runners = larger_runners
        self.purgeable = purgeable
        self.timeout = timeout
        self.poll_interval = 5.0
        self.sleep: Callable[[float], None] = time.sleep  # injectable for tests
        self.clock: Callable[[], float] = time.monotonic
        self.now: Callable[[], datetime] = _utc_now
        self.written: dict[tuple[str, str], str] = {}  # (repo, path) -> text of every definition file written
        self._types: dict[tuple[str, str, str], str] = {}  # (kind, scope, type) -> path (one per type and scope)
        self._workflows: dict[tuple[str, str], str] = {}  # (repo, path) -> content
        self._dispatches: list[WorkflowDispatch] = []
        self._remediation_repos: dict[str, set[str]] = {}  # blueprint id -> repos whose remediation PRs were seen
        self._project_name: str | None = None

    # --- names and guards -----------------------------------------------------------------------------------------
    def blueprint_id(self, slug: str) -> str:
        """``e2e-<run>-<slug>``: a blueprint id (and remediation branch) of this run."""
        return self.run_ctx.name(slug)

    def _own_name(self, name: str, what: str) -> None:
        """SafetyError unless ``name`` is an e2e name of THIS run."""
        if not naming.is_e2e_name(name) or naming.extract_run_id(name) != self.run_ctx.run_id:
            raise SafetyError(f"{what} {name!r} is not a name of run {self.run_ctx.run_id}")

    def _own_repo(self, repo: str) -> None:
        """SafetyError unless ``repo`` is a repository of this run (``e2e-<run>-*``)."""
        self._own_name(repo, "repository")

    def definition_path(self, kind: str, scope: str, stem: str) -> str:
        """``<dir>/<stem>.yml`` of a definition (DEFINITION_DIRS); ``stem`` must be a name of this run."""
        if (kind, scope) not in DEFINITION_DIRS:
            raise ValueError(f"unknown definition kind/scope {kind!r}/{scope!r}")
        self._own_name(stem, f"{kind} file")
        return f"{DEFINITION_DIRS[(kind, scope)]}/{stem}{DEFINITION_SUFFIX}"

    def repo_for(self, scope: str) -> str:
        """Repository holding the definitions of ``scope``: the configs repo (global) or the org config repo."""
        if scope not in SCOPES:
            raise ValueError(f"unknown scope {scope!r}, expected one of {SCOPES}")
        return self.configs_repo if scope == GLOBAL else self.config_repo

    def _branch(self, repo: str) -> str:
        """Default branch of ``repo``."""
        return self.oracle.default_branch(repo) or "main"

    def _require_api(self) -> WebappApi:
        """The webapp API (BlueprintError without one)."""
        if self.api is None:
            raise BlueprintError("this helper has no webapp API (webapp tier only)")
        return self.api

    # --- definitions ----------------------------------------------------------------------------------------------
    def listing(self, kind: str, scope: str) -> dict[str, str]:
        """{path: text} of the definition files (*.yml / *.yaml) of a directory on its repository's default branch."""
        repo = self.repo_for(scope)
        directory = DEFINITION_DIRS[(kind, scope)]
        url = f"/repos/{_q(self.org)}/{_q(repo)}/contents/{directory}"
        entries = self.oracle.http.get(url, params={"ref": self._branch(repo)}, allow_404=True)
        texts: dict[str, str] = {}
        for entry in entries if isinstance(entries, list) else []:
            path = str(entry.get("path") or "")
            if entry.get("type") == "file" and path.endswith((".yml", ".yaml")):
                text = self.oracle.file_content(repo, path, ref=self._branch(repo))
                if text is not None:
                    texts[path] = text
        return texts

    def _check_global_type(self, kind: str, type_: str) -> None:
        """BlueprintError when a global definition of another run or owner already has ``type_`` (global definitions
        are keyed by type: the webapp would keep only one of them)."""
        for path, text in self.listing(kind, GLOBAL).items():
            stem = posixpath.basename(path).rsplit(".", 1)[0]
            if naming.extract_run_id(stem) == self.run_ctx.run_id:
                continue
            try:
                document = yaml.safe_load(text)
            except yaml.YAMLError:
                continue
            if isinstance(document, dict) and document.get("type") == type_:
                raise BlueprintError(
                    f"{self.configs_repo}/{path} already defines a global {kind} of type {type_!r}: the webapp keeps "
                    "one global definition per type (sweep_stale() removes those of finished runs)"
                )

    def _write(self, kind: str, scope: str, stem: str, text: str, type_: str | None) -> str:
        """Commit one definition file (guarded name; one definition per type and scope) and remember it."""
        path = self.definition_path(kind, scope, stem)
        if type_ is not None:
            key = (kind, scope, type_)
            existing = self._types.get(key)
            if existing is not None and existing != path:
                raise BlueprintError(f"{existing} already defines a {scope} {kind} of type {type_!r} in this test")
            if scope == GLOBAL:
                self._check_global_type(kind, type_)
            self._types[key] = path
        repo = self.repo_for(scope)
        message = f"otterdog-e2e {self.run_ctx.run_id}: {kind} definition {stem}"
        self.mutator.commit_files(repo, self._branch(repo), {path: text}, message)
        self.written[(repo, path)] = text
        _logger.info("wrote %s %s/%s", kind, repo, path)
        return path

    def add_blueprint(self, definition: BlueprintDefinition, *, scope: str = ORG) -> str:
        """Commit ``definition`` as ``<dir>/<id>.yml`` (org: otterdog/blueprints of the org config repo, global:
        blueprints of the configs repo); returns its path. Reload or push-triggered fetches make the webapp see it."""
        self._own_name(definition.id, "blueprint id")
        return self._write(BLUEPRINT, scope, definition.id, definition.to_yaml(), definition.type)

    def add_policy(self, definition: PolicyDefinition, *, scope: str = ORG, slug: str | None = None) -> str:
        """Commit ``definition`` as ``<dir>/e2e-<run>-<slug>.yml`` (slug: the type with '-'); returns its path."""
        stem = self.run_ctx.name(slug or definition.type.replace("_", "-"))
        return self._write(POLICY, scope, stem, definition.to_yaml(), definition.type)

    def add_definition_text(self, kind: str, slug: str, text: str, *, scope: str = ORG) -> str:
        """Commit a raw definition file ``e2e-<run>-<slug>.yml`` (malformed or partial definitions)."""
        if kind not in KINDS:
            raise ValueError(f"unknown definition kind {kind!r}")
        return self._write(kind, scope, self.run_ctx.name(slug), text, None)

    def remove(self, paths: Iterable[tuple[str, str]] | None = None) -> list[tuple[str, str]]:
        """Delete definition files written by this helper (default: all), one commit per repository; returns them."""
        wanted = list(self.written) if paths is None else [entry for entry in paths if entry in self.written]
        by_repo: dict[str, list[str]] = {}
        for repo, path in wanted:
            by_repo.setdefault(repo, []).append(path)
        for repo, files in by_repo.items():
            message = f"otterdog-e2e {self.run_ctx.run_id}: remove {len(files)} definition(s)"
            self.mutator.commit_files(repo, self._branch(repo), dict.fromkeys(files), message)
            for path in files:
                self.written.pop((repo, path), None)
        self._types = {key: path for key, path in self._types.items() if any(path == p for _, p in self.written)}
        return wanted

    def remove_blueprint(self, definition: BlueprintDefinition | str, *, scope: str = ORG) -> None:
        """Delete the definition file of a blueprint written by this helper."""
        blueprint_id = definition if isinstance(definition, str) else definition.id
        repo = self.repo_for(scope)
        self.remove([(repo, self.definition_path(BLUEPRINT, scope, blueprint_id))])

    def remove_policy(self, definition: PolicyDefinition | str, *, scope: str = ORG, slug: str | None = None) -> None:
        """Delete the definition file of a policy written by this helper."""
        type_ = definition if isinstance(definition, str) else definition.type
        repo = self.repo_for(scope)
        self.remove([(repo, self.definition_path(POLICY, scope, self.run_ctx.name(slug or type_.replace("_", "-"))))])

    def sweep_stale(self) -> list[str]:
        """Delete definition files of finished runs (``e2e-<run>-*`` of runs ``purgeable`` accepts) from the four
        definition directories; returns the deleted paths (nothing without ``purgeable``)."""
        if self.purgeable is None:
            return []
        deleted: list[str] = []
        for scope in SCOPES:
            repo = self.repo_for(scope)
            stale: list[str] = []
            for kind in KINDS:
                for path in self.listing(kind, scope):
                    run_id = naming.extract_run_id(posixpath.basename(path))
                    if run_id is not None and run_id != self.run_ctx.run_id and self.purgeable(run_id):
                        stale.append(path)
            if stale:
                message = f"otterdog-e2e {self.run_ctx.run_id}: remove {len(stale)} stale definition(s)"
                self.mutator.commit_files(repo, self._branch(repo), dict.fromkeys(stale), message)
                deleted += [f"{repo}/{path}" for path in stale]
        if deleted:
            _logger.info("removed stale definitions of finished runs: %s", deleted)
        return deleted

    # --- webapp triggers ------------------------------------------------------------------------------------------
    def reload(self, *, timeout: float | None = None, tasks: Sequence[str] = FETCH_TASKS) -> dict[str, dict[str, Any]]:
        """/internal/init (global definitions reloaded, Fetch{Blueprints,Policies}Task scheduled) and the newest
        task of each ``tasks`` type created after it once final (finished or failed: a malformed definition can fail
        the fetch); ReactionTimeoutError when one never ends."""
        api = self._require_api()
        after = self.now()
        api.init()
        return self.wait_fetch(after=after, timeout=timeout, tasks=tasks)

    def wait_fetch(
        self, *, after: datetime, timeout: float | None = None, tasks: Sequence[str] = FETCH_TASKS
    ) -> dict[str, dict[str, Any]]:
        """The newest FetchBlueprintsTask / FetchPoliciesTask of the org created after ``after`` once final (also
        after a push to the config repository touching otterdog/blueprints or otterdog/policies)."""
        api = self._require_api()
        found: dict[str, dict[str, Any]] = {}
        for task_type in tasks:
            try:
                found[task_type] = api.wait_task(
                    type_=task_type, org_id=self.org, after=after, timeout=timeout or self.timeout
                )
            except waiting.WaitTimeoutError:
                raise ReactionTimeoutError(
                    f"webapp did not run {task_type} for {self.org} within {timeout or self.timeout:g} s (SUT)"
                ) from None
        return found

    def check(self, limit: int | None = None) -> datetime:
        """GET /internal/check[/<limit>] (evaluate due blueprints); returns the time just before the call."""
        api = self._require_api()
        after = self.now()
        api.check(limit)
        return after

    def wait_evaluation(
        self, definition: BlueprintDefinition, repo: str, *, after: datetime, timeout: float | None = None
    ) -> dict[str, Any]:
        """The evaluation task of ``definition`` for ``repo`` (CheckFilesTask, PinWorkflowTask, ...) created after
        ``after`` once final."""
        api = self._require_api()
        try:
            return api.wait_task(
                type_=definition.task_type,
                org_id=self.org,
                repo_name=repo,
                after=after,
                timeout=timeout or self.timeout,
            )
        except waiting.WaitTimeoutError:
            raise ReactionTimeoutError(
                f"webapp did not evaluate blueprint {definition.id} for {repo} within {timeout or self.timeout:g} s"
                f" ({definition.task_type}) (SUT)"
            ) from None

    # --- statuses -------------------------------------------------------------------------------------------------
    def remediations(self, *, blueprint_id: str | None = None, repo: str | None = None) -> list[dict[str, Any]]:
        """/api/blueprints/remediations rows of the org (status remediation_prepared)."""
        return self._require_api().blueprint_remediations(org_id=self.org, repo_name=repo, blueprint_id=blueprint_id)

    def dismissed(self, *, blueprint_id: str | None = None, repo: str | None = None) -> list[dict[str, Any]]:
        """/api/blueprints/dismissed rows of the org (status dismissed)."""
        return self._require_api().dismissed_blueprints(org_id=self.org, repo_name=repo, blueprint_id=blueprint_id)

    def project_name(self) -> str:
        """The org's project name in the webapp (/api/organizations)."""
        if self._project_name is None:
            name = self._require_api().project_name(self.org)
            if name is None:
                raise BlueprintError(f"the webapp does not list {self.org} (/api/organizations)")
            self._project_name = name
        return self._project_name

    def statuses(self, blueprint_id: str) -> dict[str, dict[str, Any]]:
        """{repo: {status, updated_at, remediation_pr}} of a blueprint (project page; {} while the webapp does not
        know the blueprint)."""
        return self._require_api().blueprint_statuses(self.project_name(), blueprint_id) or {}

    def wait_status(
        self, blueprint_id: str, repo: str, statuses: str | Collection[str], *, timeout: float | None = None
    ) -> dict[str, Any]:
        """The status row of ``blueprint_id`` for ``repo`` once its status is one of ``statuses``."""
        wanted = {statuses} if isinstance(statuses, str) else set(statuses)
        unknown = wanted - set(BLUEPRINT_STATUSES)
        if unknown:
            raise ValueError(f"unknown blueprint statuses {sorted(unknown)}, expected {BLUEPRINT_STATUSES}")
        try:
            row: dict[str, Any] = self._poll(
                lambda: self.statuses(blueprint_id).get(repo),
                lambda value: value is not None and value.get("status") in wanted,
                timeout,
                f"blueprint {blueprint_id} status of {repo} in {sorted(wanted)}",
            )
        except waiting.WaitTimeoutError as exc:
            raise ReactionTimeoutError(
                f"webapp did not set blueprint {blueprint_id} of {repo} to {sorted(wanted)} within "
                f"{timeout or self.timeout:g} s (last: {exc.last}) (SUT)"
            ) from None
        return row

    def policy_status(self, policy_type: str) -> dict[str, int]:
        """Counters of a policy type (/admin/policies; {} before its first event)."""
        if policy_type not in POLICY_TYPES:
            raise ValueError(f"unknown policy type {policy_type!r}")
        return self._require_api().policy_status().get(policy_type, {})

    def wait_policy_counter(
        self, policy_type: str, counter: str, *, at_least: int, timeout: float | None = None
    ) -> dict[str, int]:
        """The counters of ``policy_type`` once ``counter`` reached ``at_least``."""
        try:
            counters: dict[str, int] = self._poll(
                lambda: self.policy_status(policy_type),
                lambda value: int(value.get(counter, 0)) >= at_least,
                timeout,
                f"policy {policy_type} counter {counter} >= {at_least}",
            )
        except waiting.WaitTimeoutError as exc:
            raise ReactionTimeoutError(
                f"policy {policy_type} counter {counter} did not reach {at_least} within {timeout or self.timeout:g} s"
                f" (last: {exc.last}) (SUT)"
            ) from None
        return counters

    def _poll(self, fn: Callable[[], Any], until: Callable[[Any], bool], timeout: float | None, what: str) -> Any:
        """waiting.poll with the helper's interval, sleep and clock."""
        return waiting.poll(
            fn,
            until=until,
            timeout=timeout or self.timeout,
            interval=self.poll_interval,
            what=what,
            sleep=self.sleep,
            clock=self.clock,
        )

    # --- remediation pull requests --------------------------------------------------------------------------------
    def remediation_prs(self, repo: str, blueprint_id: str, *, state: str = "all") -> list[dict[str, Any]]:
        """PRs of ``repo`` from ``otterdog/blueprint/<blueprint_id>``, newest first."""
        branch = f"{BLUEPRINT_BRANCH_PREFIX}{blueprint_id}"
        pulls = [pull for pull in self.oracle.pulls(repo, state) if (pull.get("head") or {}).get("ref") == branch]
        if pulls:
            self._remediation_repos.setdefault(blueprint_id, set()).add(repo)
        return sorted(pulls, key=lambda pull: int(pull.get("number") or 0), reverse=True)

    def wait_remediation_pr(
        self, repo: str, definition: BlueprintDefinition | str, *, state: str = "open", timeout: float | None = None
    ) -> dict[str, Any]:
        """The newest remediation PR of a blueprint in ``repo`` (``state`` open, closed or all) once it exists."""
        blueprint_id = definition if isinstance(definition, str) else definition.id
        self._own_name(blueprint_id, "blueprint id")
        self._remediation_repos.setdefault(blueprint_id, set()).add(repo)
        try:
            pulls: list[dict[str, Any]] = self._poll(
                lambda: self.remediation_prs(repo, blueprint_id, state=state),
                bool,
                timeout,
                f"remediation PR of {blueprint_id} in {repo}",
            )
        except waiting.WaitTimeoutError:
            raise ReactionTimeoutError(
                f"webapp opened no remediation PR ({BLUEPRINT_BRANCH_PREFIX}{blueprint_id}) in {repo} within "
                f"{timeout or self.timeout:g} s (SUT)"
            ) from None
        return pulls[0]

    def _remediation_pull(self, repo: str, number: int) -> dict[str, Any]:
        """The PR, refused (SafetyError) unless it comes from a remediation branch of this run in a run repository or
        the org config repository."""
        if repo != self.config_repo:
            self._own_repo(repo)
        pull = self.oracle.pull(repo, int(number))
        if not pull:
            raise BlueprintError(f"{self.org}/{repo} has no pull request #{number}")
        branch = str((pull.get("head") or {}).get("ref") or "")
        if not branch.startswith(BLUEPRINT_BRANCH_PREFIX) or not run_branch(branch, self.run_ctx.run_id):
            raise SafetyError(f"PR #{number} of {repo} comes from {branch!r}, not a remediation branch of this run")
        return pull

    def close_remediation_pr(self, repo: str, number: int) -> None:
        """Close (dismiss) a remediation PR of this run; the webapp deletes its branch and records the dismissal."""
        self._remediation_pull(repo, number)
        self.mutator.close_pull(repo, int(number))

    def reopen_remediation_pr(self, repo: str, number: int, *, restore_branch: bool = True) -> None:
        """Reopen a closed remediation PR of this run (reinstates the blueprint); its branch, deleted by the webapp on
        close, is recreated at the PR's head first (GitHub refuses to reopen a PR without its head branch)."""
        pull = self._remediation_pull(repo, number)
        head = pull.get("head") or {}
        branch, sha = str(head.get("ref")), str(head.get("sha") or "")
        if restore_branch and sha and self.oracle.branch_sha(repo, branch) is None:
            self.mutator.create_ref(repo, f"refs/heads/{branch}", sha)
        _call(self.mutator, "reopen_pull", repo, int(number))

    def merge_remediation_pr(self, repo: str, number: int, *, method: str = "squash") -> dict[str, Any]:
        """Merge a remediation PR of this run at its head sha; in the org config repository through the guarded
        ConfigRepoFlow (the webapp applies merged configs with deletions)."""
        pull = self._remediation_pull(repo, number)
        if repo == self.config_repo:
            if self.flow is None:
                raise BlueprintError("merging a config-repository remediation PR needs the ConfigRepoFlow")
            return self.flow.merge(self.flow.adopt_pr(int(number)), method=method)
        sha = str((pull.get("head") or {}).get("sha") or "") or None
        return dict(self.mutator.merge_pull(repo, int(number), method=method, sha=sha) or {})

    # --- workflows ------------------------------------------------------------------------------------------------
    def workflow_path(self, slug: str) -> str:
        """``.github/workflows/e2e-<run>-<slug>.yml``."""
        return f"{WORKFLOW_DIR}/{self.run_ctx.name(slug)}.yml"

    def add_workflow(self, repo: str, slug: str, content: str, *, message: str | None = None) -> str:
        """Commit a workflow file to the default branch of a repository of this run; returns its path (the admin
        token needs the ``workflow`` scope)."""
        self._own_repo(repo)
        path = self.workflow_path(slug)
        commit = message or f"otterdog-e2e {self.run_ctx.run_id}: workflow {posixpath.basename(path)}"
        self.mutator.commit_files(repo, self._branch(repo), {path: content}, commit)
        self._workflows[(repo, path)] = content
        return path

    def add_large_runner_workflow(
        self, repo: str, *, slug: str = "large-runner", label: str = LARGE_RUNNER_LABEL
    ) -> str:
        """add_workflow of large_runner_workflow (macos_large_runners policy cases)."""
        return self.add_workflow(repo, slug, large_runner_workflow(self.run_ctx.run_id, label=label))

    def add_sbom_workflows(
        self, repo: str, *, artifact_name: str, slug: str = "sbom", project_name: str | None = None
    ) -> SbomWorkflows:
        """The reusable SBOM workflow and its caller in ``repo`` (dependency_track_upload policy cases)."""
        self._own_repo(repo)
        store = self.workflow_path(f"{slug}-store")
        self.add_workflow(repo, f"{slug}-store", sbom_store_workflow(self.run_ctx.run_id, artifact_name=artifact_name))
        caller = self.add_workflow(
            repo,
            slug,
            sbom_caller_workflow(
                self.run_ctx.run_id,
                store_workflow=reusable_workflow_ref(self.org, repo, store, ref=self._branch(repo)),
                project_name=project_name or self.run_ctx.name(slug),
            ),
        )
        return SbomWorkflows(caller, store, sbom_workflow_filter(store), artifact_name)

    def dispatch(
        self,
        repo: str,
        workflow: str,
        *,
        ref: str | None = None,
        inputs: Mapping[str, Any] | None = None,
        allow_billing: bool = False,
    ) -> WorkflowDispatch:
        """Dispatch a workflow added by this helper (workflow_dispatch); returns the dispatch (its run id when GitHub
        returned it). A job on a macOS larger runner is refused where a runner could pick it up and bill it
        (``larger_runners``) unless ``allow_billing``."""
        self._own_repo(repo)
        path = workflow if workflow.startswith(f"{WORKFLOW_DIR}/") else f"{WORKFLOW_DIR}/{workflow}"
        content = self._workflows.get((repo, path))
        if content is None:
            raise BlueprintError(f"{repo}/{path} was not added by this helper: only its own workflows are dispatched")
        if uses_larger_runner(content) and self.larger_runners and not allow_billing:
            raise SafetyError(
                f"{path} runs on a macOS larger runner and this org has larger runners: the job would run and be "
                "billed (pass allow_billing=True to accept it)"
            )
        after = self.now()
        file_name = posixpath.basename(path)
        result = _call(
            self.mutator, "dispatch_workflow", repo, file_name, ref=ref or self._branch(repo), inputs=dict(inputs or {})
        )
        raw_id = result.get("workflow_run_id") if isinstance(result, Mapping) else None
        run_id = raw_id if isinstance(raw_id, int) and not isinstance(raw_id, bool) else None
        dispatched = WorkflowDispatch(repo, file_name, after, run_id)
        self._dispatches.append(dispatched)
        return dispatched

    def workflow_runs(self, repo: str, workflow: str, *, after: datetime | None = None) -> list[dict[str, Any]]:
        """Runs of a workflow (Oracle.workflow_runs: GET .../actions/workflows/{file}/runs, at most 200), newest
        first, created after ``after`` minus the clock skew when given."""
        file_name = posixpath.basename(workflow)
        runs = [run for run in self.oracle.workflow_runs(repo, file_name) or [] if isinstance(run, dict)]
        if after is not None:
            floor = after - CLOCK_SKEW
            runs = [run for run in runs if (parse_timestamp(run.get("created_at")) or floor) >= floor]
        return runs

    def wait_run(
        self,
        repo: str,
        workflow: str,
        *,
        after: datetime,
        run_id: int | None = None,
        until: Callable[[dict[str, Any]], bool] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """The newest run of ``workflow`` created after ``after`` (run ``run_id`` when known; once ``until(run)``
        holds when given). A run that never appears is an infra failure (GitHub Actions), an ``until`` that never
        holds a SUT reaction failure."""

        def newest() -> dict[str, Any] | None:
            """The newest matching run."""
            runs = self.workflow_runs(repo, workflow, after=after)
            if run_id is not None:
                runs = [run for run in runs if run.get("id") == run_id]
            return runs[0] if runs else None

        try:
            run: dict[str, Any] = self._poll(
                newest,
                lambda value: value is not None and (until is None or until(value)),
                timeout,
                f"run of {repo}/{workflow}",
            )
        except waiting.WaitTimeoutError as exc:
            if exc.last is None:
                raise DeliveryTimeoutError(
                    f"no run of {repo}/{workflow} appeared within {timeout or self.timeout:g} s (infra: GitHub Actions)"
                ) from None
            raise ReactionTimeoutError(
                f"run {exc.last.get('id')} of {repo}/{workflow} is {exc.last.get('status')}/"
                f"{exc.last.get('conclusion')} after {timeout or self.timeout:g} s (SUT)"
            ) from None
        return run

    def cancel_run(self, repo: str, run_id: int) -> None:
        """Cancel a workflow run of a repository of this run."""
        self._own_repo(repo)
        _call(self.mutator, "cancel_workflow_run", repo, int(run_id))

    def wait_workflow_delivery(
        self,
        event: str,
        *,
        repo: str,
        action: str | None = None,
        run_id: int | None = None,
        after: datetime | None = None,
        timeout: float | None = None,
    ) -> RelayedDelivery:
        """The relayed workflow_job / workflow_run delivery of ``repo`` (and run), checked as forwarded (infra / SUT
        classification of ConfigRepoFlow)."""
        if self.relay is None:
            raise BlueprintError("waiting for deliveries needs the relay (webapp transport relay or external)")
        try:
            delivery = self.relay.wait_event(
                event, action=action, repository_name=repo, run_id=run_id, after=after, timeout=timeout or self.timeout
            )
        except waiting.WaitTimeoutError:
            raise DeliveryTimeoutError(
                f"{event}/{action or '*'} delivery of {repo} (run {run_id}) not observed within "
                f"{timeout or self.timeout:g} s (infra): is the App subscribed to workflow events?"
            ) from None
        check_forwarded(delivery, f"{repo} run {delivery.run_id}")
        return delivery

    def cancel_pending_runs(self) -> list[int]:
        """Cancel the runs of dispatched workflows that are still queued or running; returns their ids."""
        cancelled: list[int] = []
        for dispatched in self._dispatches:
            for run in self.workflow_runs(dispatched.repo, dispatched.workflow, after=dispatched.after):
                run_id = run.get("id")
                if run.get("status") in ACTIVE_RUN_STATUSES and isinstance(run_id, int) and run_id not in cancelled:
                    self.cancel_run(dispatched.repo, run_id)
                    cancelled.append(run_id)
        return cancelled

    # --- teardown -------------------------------------------------------------------------------------------------
    def cleanup(self) -> None:
        """Cancel pending runs, close the open remediation PRs of this run's blueprints, remove the definitions and
        make the webapp reload them; every step runs, failures are raised together (BlueprintError)."""
        failures: list[str] = []

        def attempt(what: str, step: Callable[[], Any]) -> None:
            """Run one cleanup step, collecting its failure."""
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - every step runs; reported together
                failures.append(f"{what}: {REDACTOR(f'{type(exc).__name__}: {exc}')}")

        attempt("cancel workflow runs", self.cancel_pending_runs)
        attempt("close remediation PRs", self._close_remediation_prs)
        removed = bool(self.written)
        attempt("remove definitions", self.remove)
        if removed and self.api is not None:
            attempt("reload the webapp definitions", self.reload)
        self._dispatches.clear()
        if failures:
            _logger.warning("blueprint cleanup incomplete: %s", failures)
            raise BlueprintError("blueprint cleanup failed: " + "; ".join(failures))

    def _close_remediation_prs(self) -> None:
        """Close the open remediation PRs of the blueprints whose PRs were seen (and of the config repository)."""
        for blueprint_id, repos in self._remediation_repos.items():
            for repo in sorted(repos | {self.config_repo}):
                for pull in self.remediation_prs(repo, blueprint_id, state="open"):
                    self.mutator.close_pull(repo, int(pull["number"]))
