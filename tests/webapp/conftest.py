"""Shared fixtures and helpers of the webapp tier (SPEC 19: the W-* scenarios against the webapp under test).

Waiting rules: every wait on the webapp goes through the delivery-then-reaction helpers of ConfigRepoFlow
(``wait_delivery`` / ``wait_status`` / ``wait_comment`` / ``wait_merged``): a delivery that never reaches the webapp
is an infrastructure problem (DeliveryTimeoutError, "(infra)"), a webapp that does not react to a delivery it got is a
problem of the system under test (ReactionTimeoutError, "(SUT)"), and each reaction budget is counted from the forward
time of its triggering delivery. Follow-up reads after an observed reaction (webapp /api records, oracle state,
minimized comments) poll through ``WebappScenario.reaction``, which raises ReactionTimeoutError too. Tests never
sleep blindly (tests/unit/test_suite_webapp_static.py enforces it).

Exact otterdog texts (``Texts``), verified in SRC (otterdog main 9bdeb75, after v1.6.1) and unchanged since v1.4.0:

* commit statuses (otterdog/webapp/tasks/validate_pull_request.py:233-271, check_sync.py:214-257): validation
  ``pending`` "validating configuration change using otterdog", ``success`` "otterdog validation completed
  successfully", ``error`` "otterdog validation failed, check validation result in comment history", ``failure``
  "otterdog validation failed, please contact an admin" (task exception); sync ``success`` "otterdog sync check
  completed successfully", ``success`` (sic) "otterdog sync check failed, check comment history" when out of sync,
  ``failure`` "otterdog detected out of sync changes, but they will not prevent a successful merge";
* comments (otterdog/webapp/templates/comment/*.txt): help "Thank you for raising a pull request to update the
  configuration of your GitHub organization.", validate "Please find below the validation of the requested
  configuration changes:" + "Diff for <head sha>", automerge "This Pull Request is eligible for auto-merging",
  check-sync "The current configuration is out-of-sync with the live settings:" (``[!NOTE]`` up to v1.5.0,
  ``[!WARNING]`` since v1.6.0), apply "The following changes have been applied successfully:" or "[!CAUTION] The changes
  could not be applied successfully" (no marker: both contain "applied successfully");
* a head that does not load prints "failed to load configuration" (operations/diff_operation.py:164), an evaluation
  crash "Validation failed while evaluating the configuration" (validate_pull_request.py:188);
* commands (webhook/comment_handlers.py) match ``re.match(r"/otterdog\\s+<cmd>")``; ``/otterdog help`` (not listed by
  the help comment) re-posts the help comment, the HelpCommentTask / ValidatePullRequestTask / check-sync task first
  minimize their previous comments as OUTDATED (tasks/__init__.py:210-225);
* pending statuses (validate_pull_request.py:233-242, check_sync.py:214-223): validation "validating configuration
  change using otterdog", sync "checking if configuration is in-sync using otterdog"; a sync check propagated from the
  previous commit (synchronize within an hour, check_sync.py:91-124) posts its final status without a pending one;
* the evaluation error of a validation (validate_pull_request.py:183-192): "Validation failed while evaluating the
  configuration. Please contact an admin if you believe this is incorrect."; an identical org file "No changes."
  (validate_pull_request.py:152-155); warnings (validate_pull_request.py:196-205, wording of #771 since 476bf5e:
  "some of the requested changes ...", before "some of requested changes ...");
* team-info (team_membership_comment.txt): "The author ([<login>](https://github.com/<login>)) of this PR is associated
  with this organization in the role of `<association>`." plus "- [<team name>](https://github.com/orgs/<org>/teams/
  <team name>)" lines; the automerge problems comment (automerge_problems.txt) "This pull request cannot be
  auto-merged via `/otterdog merge`" with one paragraph per problem (db/models.py:117-200, merge_pull_request.py:66-83);
* done / apply permissions (wrong_team_done_comment.txt, wrong_team_apply_comment.txt): "Only members of the admin
  team(s) `<org>/<team>` are allowed to mark the PR as being completed." / "... to apply the changes manually.";
  done_comment.txt "The PR has been marked as being completed."; a partial apply (applied_changes_comment.txt) "The
  pull request was only partially applied as it requires some access to secrets or the Web UI".

The texts are matched with ``config_repo.comment_contains`` (verbatim or after ``normalize_comment``) and tolerant
regexes, so wording outside these anchors may change between versions; the wordings that changed in a release are
checked against the SUT's history (``WebappScenario.webapp_includes``).

Negative checks ("the webapp does not react") wait for the delivery of the harness action first (``settle``: the
relayed delivery reached the webapp, infra otherwise) and then for the webapp's tasks to settle (``quiesce``); only
then the absence of a comment, status or task means something. With the external transport (no relay) the delivery
cannot be observed and such checks only rely on ``quiesce``.

Helpers live here, not in a helper module: ``--import-mode=importlib`` keeps test modules from importing each other
(and from importing this conftest at run time). Tests reach everything through the ``webapp_scenario`` fixture
(``webapp_scenario.texts`` for the texts); test modules import WebappScenario under TYPE_CHECKING only.
"""

from __future__ import annotations

import dataclasses
import json
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, TypeVar

import pytest

from otterdog_e2e import procs, waiting
from otterdog_e2e.config_repo import (
    APPLIED_TEXTS,
    ConfigPr,
    DeliveryTimeoutError,
    ReactionTimeoutError,
    check_forwarded,
    comment_contains,
)
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.scenarios.collect import TIER_TIMEOUTS
from otterdog_e2e.webapp.api import parse_timestamp

if TYPE_CHECKING:
    from otterdog_e2e.config_repo import ConfigRepoFlow
    from otterdog_e2e.context import E2EContext, WebappCase
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.settings import Target
    from otterdog_e2e.webapp.api import WebappApi
    from otterdog_e2e.webhooks.relay import RelayedDelivery

T = TypeVar("T")


class Texts:
    """Verified otterdog texts and patterns (module docstring), reachable from tests as ``webapp_scenario.texts``."""

    VALIDATION_SUCCESS_RE = re.compile(r"validation completed successfully", re.IGNORECASE)
    VALIDATION_FAILED_RE = re.compile(r"validation failed", re.IGNORECASE)
    SYNC_IN_SYNC_RE = re.compile(r"sync check completed successfully", re.IGNORECASE)
    SYNC_FAILED_RE = re.compile(r"sync check failed|out of sync", re.IGNORECASE)
    HELP = "Thank you for raising a pull request to update the configuration of your GitHub organization"
    VALIDATE = "Please find below the validation of the requested configuration changes"
    DIFF_FOR = "Diff for"
    AUTOMERGE = "eligible for auto-merging"
    OUT_OF_SYNC = "out-of-sync with the live settings"
    APPLY_RESULT = "applied successfully"  # both branches of applied_changes_comment.txt
    APPLY_SUCCESS, APPLY_FAILURE = APPLIED_TEXTS
    LOAD_FAILURE_RE = re.compile(r"failed to load configuration|Validation failed while evaluating", re.IGNORECASE)
    OUTDATED_REASON = "outdated"  # GraphQL minimizedReason of comments minimized with classifier OUTDATED
    # exact commit status descriptions (validate_pull_request.py:233-271, check_sync.py:214-257)
    VALIDATION_PENDING = "validating configuration change using otterdog"
    VALIDATION_SUCCESS = "otterdog validation completed successfully"
    VALIDATION_ERROR = "otterdog validation failed, check validation result in comment history"
    SYNC_PENDING = "checking if configuration is in-sync using otterdog"
    SYNC_SUCCESS = "otterdog sync check completed successfully"
    SYNC_OUT_OF_SYNC = "otterdog sync check failed, check comment history"
    SYNC_CRASH = "otterdog detected out of sync changes, but they will not prevent a successful merge"  # KB-040
    # validation comment bodies (validate_pull_request.py:146-205)
    EVALUATION_ERROR = "Validation failed while evaluating the configuration."
    CONTACT_ADMIN = "Please contact an admin if you believe this is incorrect."
    NO_CHANGES = "No changes."
    WARNINGS_HEADING = "### Warnings"
    INFOS_HINT_RE = re.compile(r"there have been (?P<infos>\d+) validation infos")  # diff_operation.py:242-245
    # team-info, automerge problems, done / apply permissions (templates/comment/*.txt, db/models.py)
    TEAM_INFO_RE = re.compile(r"of this PR is associated with this organization in the role of `(?P<role>[A-Z_]+)`")
    AUTOMERGE_PROBLEMS = "This pull request cannot be auto-merged via `/otterdog merge`"
    NOT_AUTO_MERGEABLE = "pull request cannot be automatically merged"  # supports_auto_merge False (models.py:153)
    COST_REASON = "may incur costs"  # in that sentence since #770 (c4f75eb, v1.6.1)
    NON_CONFIG_REASON = "touches non-configuration files"
    NOT_VALID = "pull request is not valid"  # models.py:147-150
    APPROVAL_MISSING = "No approval from a member of"  # automerge_eligibility.txt via models.py:172-180
    THIRD_PARTY_RE = re.compile(r"Only the author of the pull request, a member of .+ is allowed to auto-merge\.")
    WRONG_TEAM_DONE = "are allowed to mark the PR as being completed"
    WRONG_TEAM_APPLY = "are allowed to apply the changes manually"
    DONE = "The PR has been marked as being completed"
    PARTIAL_APPLY = "only partially applied as it requires some access to secrets or the Web UI"
    APPLY_CRASH = "Applying the configuration failed."  # apply_changes.py:213-221 (exception inside the apply)
    PATCH_FAILURE = "failed to apply patch"  # operations/apply.py:148-151


# --- budgets (seconds; counted from the forward time of the triggering delivery) ------------------------------------
VALIDATION_TIMEOUT = 300.0  # template clone + local-plan
SYNC_TIMEOUT = 420.0  # >= 60 s backoff after the previous sync task + a full live plan
COMMENT_TIMEOUT = 300.0
APPLY_TIMEOUT = 480.0  # merge -> ApplyChangesTask (local-apply against the live org) -> comment
MERGE_TIMEOUT = 240.0
API_TIMEOUT = 120.0  # /api records are written right after the status/comment of the same task
STATE_TIMEOUT = 120.0  # oracle reads after an observed apply
MINIMIZE_TIMEOUT = 60.0  # outdated comments are minimized before the new comment is created
QUIET_FOR = 10.0
QUIESCE_TIMEOUT = 240.0
BRANCH_TIMEOUT = 120.0  # DeleteBranchTask right after the closed delivery
INSTALLATION_TIMEOUT = 120.0  # update_installation_status runs as a background task of the installation delivery
# tests running several PR flows (validation + sync + merge + apply each) get this call timeout instead of the tier's
LONG_FLOW_TIMEOUT = 1800

SYNTAX_ERROR_TAIL = "// otterdog-e2e: deliberate syntax error (W-PR-INVALID), this configuration must not load\n}\n"
# the repository schema only accepts pull, triage, push, maintain and admin: an uncaught jsonschema error while the
# configuration loads (KB-032), i.e. an evaluation error in the webapp and a load error for the config guard
SCHEMA_ERROR_PERMISSION = "e2e-not-a-permission"
# a topic otterdog refuses with a validation error ("Only lower-case, numbers and '-' are allowed characters.",
# models/repository.py:414-420): the configuration loads, validation fails, nothing is applied
INVALID_TOPIC = "E2E_Not_A_Topic"
CREATED_PR_RE = re.compile(r"created pull request #(\d+)")  # operations/open_pull_request.py:140-143
PR_BODY = (
    "Opened by the otterdog-e2e harness (scenario {scenario}, run {run}). The harness closes it and deletes its "
    "branch; it is merged only when the scenario says so."
)
TIER_DIR = Path(__file__).resolve().parent


# --- per-tier timeout ---------------------------------------------------------------------------------------------
@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Webapp items get the tier timeout for the test call only (``func_only``): the first webapp item would
    otherwise also pay for the session setup it triggers (SUT image build, compose stack, baseline reset)."""
    add_call_timeouts(config, items, TIER_DIR, TIER_TIMEOUTS["webapp"])


def add_call_timeouts(config: pytest.Config, items: Sequence[pytest.Item], directory: Path, timeout: float) -> None:
    """``timeout(<timeout>, func_only=True)`` on the items of ``directory`` without a timeout marker (only when
    pytest-timeout is loaded: its marker is unknown otherwise and --strict-markers would refuse it)."""
    if not config.pluginmanager.hasplugin("timeout"):
        return
    for item in items:
        if Path(item.path).resolve().is_relative_to(directory) and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(timeout, func_only=True))


# --- config texts -------------------------------------------------------------------------------------------------
def repo_fragment(name: str, description: str) -> str:
    """A new public repository with the template defaults: ``orgs.newRepo(<name>) { description: ... }``."""
    return f"orgs.newRepo({json.dumps(name)}) {{ description: {json.dumps(description)} }}"


def description_override(name: str, description: str) -> str:
    """A layer-2 ``_repositories`` entry merged into the declared repository ``name`` (the template merges
    repositories by name with mergeByKey, later entries win): only its description changes."""
    return f"{{ name: {json.dumps(name)}, description: {json.dumps(description)} }}"


def repo_patch(name: str, fields: str) -> str:
    """A layer-2 ``_repositories`` entry merged into the declared repository ``name`` with the jsonnet ``fields``
    (``secrets+: [...]``, ``workflows+: {...}``; mergeByKey merges it with ``+``, so ``+:`` fields extend)."""
    return f"{{ name: {json.dumps(name)}, {fields} }}"


def new_repo(name: str, description: str, fields: str = "") -> str:
    """A new repository with the template defaults, a description and extra jsonnet ``fields``."""
    extra = f", {fields}" if fields else ""
    return f"orgs.newRepo({json.dumps(name)}) {{ description: {json.dumps(description)}{extra} }}"


def repo_secret(name: str, value: str) -> str:
    """``secrets+: [orgs.newRepoSecret(<name>) { value: <value> }]`` (repository secrets of repo_patch/new_repo)."""
    return f"secrets+: [orgs.newRepoSecret({json.dumps(name)}) {{ value: {json.dumps(value)} }}]"


def cache_size(gigabytes: int) -> str:
    """``workflows+: { max_cache_size_gb::: <n> }``: visible even when the renderer hides the template's cache limit
    (OrgConfigRenderer hide_cache_limit, ``max_cache_size_gb:: null`` in newRepo)."""
    return f"workflows+: {{ max_cache_size_gb::: {int(gigabytes)} }}"


def statuses_of(statuses: Sequence[Mapping[str, Any]], context: str) -> list[dict[str, Any]]:
    """The commit statuses of ``context`` in the order given (GitHub lists them newest first)."""
    return [dict(status) for status in statuses if status.get("context") == context]


def config_text(
    renderer: OrgConfigRenderer,
    *,
    repos: Mapping[str, str] | None = None,
    overrides: Mapping[str, str] | None = None,
) -> str:
    """Baseline config plus new repositories (name -> description) and description overrides of declared ones."""
    fragments = [repo_fragment(name, description) for name, description in (repos or {}).items()]
    fragments += [description_override(name, description) for name, description in (overrides or {}).items()]
    return renderer.render(ConfigFragments(repositories=fragments))


def syntax_error_text(baseline_text: str) -> str:
    """The baseline config followed by a stray ``}``: jsonnet refuses to load it (the webapp reports an error)."""
    return baseline_text.rstrip() + "\n" + SYNTAX_ERROR_TAIL


def harmless_repo(target: Target) -> str:
    """Baseline repository whose description PR-only scenarios change: the first fixture repo, else the configs
    repo (both are declared by the baseline; such PRs are never merged)."""
    return next(iter(target.fixture_repos), target.configs_repo)


def comment_ids(comment: Mapping[str, Any]) -> set[str]:
    """GraphQL node id and database id of a comment (as strings)."""
    return {str(value) for value in (comment.get("id"), comment.get("database_id")) if value is not None}


def slugify(scenario_id: str) -> str:
    """Branch / repository slug of a scenario id (``W-MERGE-APPLY`` -> ``w-merge-apply``)."""
    return re.sub(r"[^a-z0-9-]+", "-", scenario_id.lower()).strip("-")


# --- the scenario helper ------------------------------------------------------------------------------------------
@dataclass
class WebappScenario:
    """One isolated webapp scenario (``webapp_case``): config texts, PR actions and classified waits."""

    texts: ClassVar[type[Texts]] = Texts
    SCHEMA_ERROR_PERMISSION: ClassVar[str] = SCHEMA_ERROR_PERMISSION
    INVALID_TOPIC: ClassVar[str] = INVALID_TOPIC

    sid: str
    e2e: E2EContext
    case: WebappCase
    flow: ConfigRepoFlow
    api: WebappApi
    renderer: OrgConfigRenderer
    baseline: BaselineManager
    oracle: Oracle
    run_ctx: RunContext
    target: Target

    # --- names --------------------------------------------------------------------------------------------------
    @property
    def org(self) -> str:
        """Exact-case login of the test org (the webapp's org id)."""
        return self.case.org

    @property
    def repo(self) -> str:
        """The org config repo of this run."""
        return self.flow.repo

    @property
    def slug(self) -> str:
        """Branch / repository slug of the scenario (slugify of its id)."""
        return slugify(self.sid)

    @property
    def harmless_repo(self) -> str:
        """The declared repository whose description PR-only scenarios change (harmless_repo)."""
        return harmless_repo(self.target)

    def run_repo(self, suffix: str = "") -> str:
        """Run repository name ``e2e-<run>-<slug>[-<suffix>]`` (removed by the webapp_case teardown)."""
        return self.run_ctx.name(f"{self.slug}-{suffix}" if suffix else self.slug)

    def describe(self, what: str) -> str:
        """A description naming the run and scenario (recognizable on GitHub)."""
        return f"otterdog e2e {self.run_ctx.run_id} {self.sid}: {what}"

    # --- config texts -------------------------------------------------------------------------------------------
    def baseline_text(self) -> str:
        """The rendered baseline (what config repo main holds at the start of the case)."""
        return self.case.baseline_text

    def text(self, *, repos: Mapping[str, str] | None = None, overrides: Mapping[str, str] | None = None) -> str:
        """Baseline plus new repositories and description overrides (config_text)."""
        return config_text(self.renderer, repos=repos, overrides=overrides)

    def harmless_text(self, *, repos: Mapping[str, str] | None = None) -> str:
        """A non-destructive change: the description of the harmless repository (plus ``repos``, kept declared)."""
        return self.text(repos=repos, overrides={self.harmless_repo: self.describe("description change")})

    def syntax_error_text(self) -> str:
        """The baseline with a syntax error (syntax_error_text)."""
        return syntax_error_text(self.baseline_text())

    def render(self, *, repositories: Sequence[str] = (), teams: Sequence[str] = ()) -> str:
        """Baseline plus raw layer-2 repository and team fragments (new_repo, repo_patch, ``orgs.newTeam(...)``)."""
        return self.renderer.render(ConfigFragments(repositories=list(repositories), teams=list(teams)))

    @staticmethod
    def patch(name: str, fields: str) -> str:
        """Layer-2 fields merged into the declared repository ``name`` (repo_patch)."""
        return repo_patch(name, fields)

    @staticmethod
    def new_repo(name: str, description: str, fields: str = "") -> str:
        """A new repository fragment with extra jsonnet fields (new_repo)."""
        return new_repo(name, description, fields)

    @staticmethod
    def secret(name: str, value: str) -> str:
        """``secrets+:`` fields with one repository secret (repo_secret)."""
        return repo_secret(name, value)

    @staticmethod
    def cache(gigabytes: int) -> str:
        """``workflows+:`` fields managing max_cache_size_gb (cache_size)."""
        return cache_size(gigabytes)

    def schema_error(self) -> str:
        """Repository fields the repository schema refuses (a team_permissions value outside its enum): the
        configuration raises an uncaught jsonschema error while it loads (KB-032)."""
        return f"team_permissions+: {{ {json.dumps(self.target.admin_team)}: {json.dumps(SCHEMA_ERROR_PERMISSION)} }}"

    @staticmethod
    def invalid_topic() -> str:
        """Repository fields failing validation (a topic with upper-case letters and '_'): loads, never applied."""
        return f"topics: [{json.dumps(INVALID_TOPIC)}]"

    def declare_live(self, repos: Mapping[str, str]) -> str:
        """Precondition outside the SUT: ``repos`` are created live by the TRUSTED reset CLI (guarded apply, no -d)
        and declared on config repo main; returns the new main text. The webapp_case teardown removes both."""
        text = self.text(repos=repos)
        self.declare_live_text(text, what=sorted(repos))
        missing = [name for name in repos if self.oracle.repo(name) is None]
        assert not missing, f"repositories {missing} missing after the trusted apply (precondition)"
        return text

    def declare_live_text(self, text: str, *, what: object, main_text: str | None = None) -> str:
        """Precondition outside the SUT: the TRUSTED reset CLI applies ``text`` (guarded, ``-r e2e-<run>-*``, no -d;
        org-level run objects such as run teams are applied too) and config repo main gets ``main_text`` (default:
        ``text``, e.g. a wildcard webhook url the live hook matches); returns the main text. The webapp_case teardown
        removes the run objects (guarded ``apply -d``) and restores main."""
        cli = self.baseline.reset_cli
        cli.workspace.write_org_config(text)
        result = self.baseline.guarded_apply(cli, repo_filter=self.run_ctx.repo_filter(), delete=False)
        assert not result.aborted_validation and not result.failed_patches, (
            f"the trusted reset CLI could not create {what} (precondition):\n{REDACTOR(result.raw)[-2000:]}"
        )
        main = text if main_text is None else main_text
        self.flow.reset_main(main, message=f"otterdog-e2e {self.run_ctx.run_id}: {self.sid} declares {what}")
        return main

    def login(self, identity: str) -> str:
        """Declared GitHub login of an identity (the target's identities; AssertionError when it has none)."""
        spec = self.target.identities.get(identity)
        login = spec.login if spec is not None else None
        assert login, f"the target declares no login for identity {identity!r}"
        return login

    # --- PR actions ---------------------------------------------------------------------------------------------
    def open_pr(
        self, texts: str | Sequence[str], *, identity: str = "admin", suffix: str = "", draft: bool = False
    ) -> ConfigPr:
        """Open the scenario's config PR (one commit per text, each guarded) on branch e2e/<run>/<slug>[-suffix]."""
        slug = f"{self.slug}-{suffix}" if suffix else self.slug
        return self.flow.open_pr(
            slug=slug,
            config_texts=texts,
            title=f"e2e {self.run_ctx.run_id} {self.sid}",
            identity=identity,
            draft=draft,
            body=PR_BODY.format(scenario=self.sid, run=self.run_ctx.run_id),
        )

    def open_pr_files(
        self, files: Mapping[str, str | None], *, identity: str = "admin", suffix: str = "", message: str | None = None
    ) -> ConfigPr:
        """Open the scenario's PR with ONE commit writing ``files`` (the org config among them guarded, other files
        such as README.md as they are) on branch e2e/<run>/<slug>[-suffix]."""
        slug = f"{self.slug}-{suffix}" if suffix else self.slug
        return self.flow.open_pr_files(
            slug=slug,
            files=files,
            title=f"e2e {self.run_ctx.run_id} {self.sid}",
            identity=identity,
            body=PR_BODY.format(scenario=self.sid, run=self.run_ctx.run_id),
            message=message,
        )

    def pull(self, pr: ConfigPr) -> dict[str, Any]:
        """The pull request as GitHub shows it now (AssertionError when it is gone)."""
        pull = self.oracle.pull(self.repo, pr.number)
        assert pull is not None, f"PR #{pr.number} of {self.repo} not found"
        return pull

    def refreshed(self, pr: ConfigPr) -> ConfigPr:
        """``pr`` with its current head sha on GitHub (the webapp itself pushed to the branch, e.g. update-branch)."""
        head = str((self.pull(pr).get("head") or {}).get("sha") or pr.head_sha)
        return dataclasses.replace(pr, head_sha=head)

    def api_pull(self, pr: ConfigPr) -> dict[str, Any] | None:
        """The /api record of the PR (open or merged lists), None when neither lists it (closed, or unknown)."""
        return self.api.pull_request(self.org, self.repo, pr.number)

    def wait_api_pull_gone(self, pr: ConfigPr, *, what: str, timeout: float = API_TIMEOUT) -> None:
        """Wait until /api/pullrequests/open and /merged no longer list the PR (a closed record)."""
        self.reaction(
            lambda: self.api_pull(pr),
            until=lambda record: record is None,
            what=f"/api no longer lists PR #{pr.number} {what}",
            timeout=timeout,
        )

    # --- negative checks ----------------------------------------------------------------------------------------
    def now(self) -> datetime:
        """The flow's clock (aware UTC): the ``after`` of settle / wait_repo_task."""
        return self.flow.now()

    def settle(self, pr: ConfigPr, *, event: str, action: str | None, after: datetime) -> None:
        """The delivery of a harness action on ``pr`` (``event``/``action`` delivered after ``after``) reached the
        webapp (DeliveryTimeoutError "(infra)" otherwise), then no task of the org is pending or running: the base of
        every "the webapp did not react" assertion."""
        self.flow.wait_delivery(pr, event=event, action=action, after=after)
        self.quiesce()

    def bot_comment_ids(self, pr: ConfigPr) -> set[str]:
        """Node and database ids of every bot comment currently on the PR."""
        return {value for comment in self.flow.bot_comments(pr) for value in comment_ids(comment)}

    def new_bot_comments(
        self, pr: ConfigPr, before: Collection[str], *, marker: str | None = None
    ) -> list[dict[str, Any]]:
        """Bot comments of the PR (with ``marker`` when given) that are not in ``before`` (bot_comment_ids)."""
        known = set(before)
        return [comment for comment in self.flow.bot_comments(pr, marker=marker) if not comment_ids(comment) & known]

    def wait_problems(
        self, pr: ConfigPr, *, exclude: Sequence[Mapping[str, Any]] = (), timeout: float = COMMENT_TIMEOUT
    ) -> str:
        """Body of the new automerge problems comment of a refused ``/otterdog merge`` (automerge_problems.txt)."""
        comment = self.wait_comment(pr, contains=Texts.AUTOMERGE_PROBLEMS, exclude=exclude, timeout=timeout)
        return str(comment.get("body") or "")

    def assert_still_open(self, pr: ConfigPr, why: str) -> None:
        """The PR is open and not merged on GitHub (AssertionError naming ``why`` otherwise)."""
        pull = self.pull(pr)
        assert pull.get("state") == "open" and not pull.get("merged"), (
            f"PR #{pr.number} must stay open ({why}) (SUT): state {pull.get('state')!r}, merged {pull.get('merged')!r}"
        )

    # --- commit statuses ----------------------------------------------------------------------------------------
    def status_context(self, context: str) -> str:
        """The configured commit status context of ``validation`` / ``sync`` (other names are kept)."""
        aliases = {"validation": self.flow.validation_context, "sync": self.flow.sync_context}
        return aliases.get(context, context)

    def commit_statuses(self, sha: str, context: str) -> list[dict[str, Any]]:
        """Every commit status of ``context`` (``validation`` / ``sync`` aliases) on ``sha``, newest first
        (Oracle.commit_statuses: GET /repos/{org}/{repo}/commits/{sha}/statuses)."""
        return statuses_of(list(self.oracle.commit_statuses(self.repo, sha)), self.status_context(context))

    # --- pushes and stored configurations -----------------------------------------------------------------------
    def wait_push(self, sha: str) -> RelayedDelivery | None:
        """The relayed push delivery of the config repo whose ``after`` is ``sha`` (e.g. a merge commit), checked as
        forwarded to the webapp (DeliveryTimeoutError "(infra)" otherwise); None without delivery tracking."""
        relay = self.flow.relay
        if relay is None:
            return None

        def matches(delivery: RelayedDelivery) -> bool:
            """The push of ``sha`` to the config repo."""
            return delivery.event == "push" and delivery.repository_name == self.repo and delivery.head_sha == sha

        try:
            delivery = relay.wait_for(matches, timeout=self.flow.delivery_timeout)
        except waiting.WaitTimeoutError:
            raise DeliveryTimeoutError(
                f"push delivery of {sha[:12]} to {self.repo} not observed within {self.flow.delivery_timeout:g} s "
                "(infra): check the App webhook/sink and the relay (deliveries.jsonl)"
            ) from None
        check_forwarded(delivery, f"the push of {sha[:12]} to {self.repo}")
        return delivery

    @staticmethod
    def stored_repositories(config: Mapping[str, Any] | None) -> dict[str, dict[str, Any]]:
        """name -> repository of a configuration stored by the webapp (/api/organizations/<org>, evaluated jsonnet)."""
        repositories = (config or {}).get("repositories") or []
        return {str(repo["name"]): dict(repo) for repo in repositories if isinstance(repo, dict) and repo.get("name")}

    # --- PRs into another branch than the default one -----------------------------------------------------------
    def open_side_pr(self, text: str, *, suffix: str) -> tuple[ConfigPr, str]:
        """A config PR whose base is NOT the default branch: base ``e2e/<run>/<slug>-<suffix>-base`` and head
        ``e2e/<run>/<slug>-<suffix>`` (one commit with ``text``, guarded against main: the webapp validates every PR
        against the default branch) branched from main; returns the PR (not managed by the flow, which only opens and
        adopts PRs to main) and its base branch. ``remove_side_pr`` deletes both branches."""
        base, head = self.run_ctx.branch(f"{self.slug}-{suffix}-base"), self.run_ctx.branch(f"{self.slug}-{suffix}")
        self.flow.guard_config(self.flow.main_config() or "", text)
        mutator = self.flow.mutators["admin"]
        main_sha = self.flow.main_sha()
        mutator.create_branch(self.repo, base, main_sha)
        mutator.create_branch(self.repo, head, main_sha)
        message = f"e2e {self.run_ctx.run_id} {self.slug}-{suffix}: config change for {base}"
        sha = mutator.commit_files(self.repo, head, {self.flow.config_path: text}, message)
        pull = mutator.create_pull(
            self.repo,
            head=head,
            base=base,
            title=f"e2e {self.run_ctx.run_id} {self.sid} into {base}",
            body=PR_BODY.format(scenario=self.sid, run=self.run_ctx.run_id),
        )
        user = str((pull.get("user") or {}).get("login") or "admin")
        pr = ConfigPr(int(pull["number"]), head, sha, str(pull.get("html_url") or ""), user, frozenset())
        return pr, base

    def remove_side_pr(self, pr: ConfigPr | None, base: str | None) -> None:
        """Close an open side PR and delete its head and base branches (run branches; gone ones are ignored)."""
        mutator = self.flow.mutators["admin"]
        if pr is not None and (self.oracle.pull(self.repo, pr.number) or {}).get("state") == "open":
            mutator.close_pull(self.repo, pr.number)
        for branch in (pr.branch if pr is not None else None, base):
            if branch:
                mutator.delete_ref(self.repo, f"heads/{branch}")

    # --- otterdog open-pr ---------------------------------------------------------------------------------------
    def open_pr_with_cli(self, cli: OtterdogCli, text: str, *, suffix: str) -> ConfigPr:
        """``otterdog open-pr`` of ``text`` (guarded first, like every config text) with the CLI ``cli`` of a fresh
        workspace: branch ``otterdog/e2e-<run>-<slug>-<suffix>`` and a PR to main, adopted by the flow (guards,
        cleanup). The webapp handles it like any config PR, plus the otterdog/* branch rules."""
        branch = self.run_ctx.name(f"{self.slug}-{suffix}")
        self.flow.guard_config(self.flow.main_config() or "", text)
        cli.workspace.write_org_config(text)
        result = cli.open_pr(branch=branch, title=f"e2e {self.run_ctx.run_id} {self.sid}", author=self.login("admin"))
        result.assert_ok("open-pr")
        match = CREATED_PR_RE.search(result.output)
        assert match, f"open-pr printed no pull request number:\n{REDACTOR(result.output)[-2000:]}"
        pr = self.flow.adopt_pr(int(match.group(1)))
        assert pr.branch == f"otterdog/{branch}", f"open-pr opened PR #{pr.number} from {pr.branch!r}"
        return pr

    # --- tasks without a pull request ---------------------------------------------------------------------------
    def wait_repo_task(
        self,
        type_: str,
        *,
        after: datetime,
        repo: str | None = None,
        pull_request: int | None = None,
        timeout: float = API_TIMEOUT,
    ) -> dict[str, Any]:
        """The newest finished/failed ``type_`` task of ``repo`` (default: the config repo) created after ``after``,
        of any pull request unless ``pull_request`` is given (FetchConfigTask, DeleteBranchTask and
        FetchAllPullRequestsTask record none: pull_request 0)."""
        repo_name = repo or self.repo
        try:
            return self.api.wait_task(
                type_=type_,
                org_id=self.org,
                after=after,
                repo_name=repo_name,
                pull_request=pull_request,
                timeout=timeout,
            )
        except waiting.WaitTimeoutError as exc:
            raise ReactionTimeoutError(
                f"webapp did not run {type_} for {repo_name} within {timeout:g} s (SUT): {exc}"
            ) from None

    # --- branches and installations -----------------------------------------------------------------------------
    def wait_branch_gone(self, branch: str, *, timeout: float = BRANCH_TIMEOUT) -> None:
        """Wait until ``branch`` no longer exists in the config repo (GET git/ref/heads/<branch> 404)."""
        self.reaction(
            lambda: self.oracle.branch_sha(self.repo, branch),
            until=lambda sha: sha is None,
            what=f"branch {branch} of {self.repo} deleted",
            timeout=timeout,
        )

    def installation(self) -> dict[str, Any] | None:
        """The org's row of /admin/organizations: {installation_id, status, project_name}."""
        return self.api.installations().get(self.org)

    def wait_installation(
        self, *, status: str, installation_id: int | None = None, timeout: float = INSTALLATION_TIMEOUT
    ) -> dict[str, Any]:
        """The org's /admin/organizations row once its status (and installation id, when given) match."""

        def matches(row: dict[str, Any] | None) -> bool:
            """Status and id as wanted."""
            return (
                row is not None
                and row.get("status") == status
                and (installation_id is None or row.get("installation_id") == installation_id)
            )

        row = self.reaction(
            self.installation,
            until=matches,
            what=f"installation of {self.org} {status} (id {installation_id})",
            timeout=timeout,
        )
        assert row is not None  # reaction() only returns accepted values
        return row

    # --- classified waits ---------------------------------------------------------------------------------------
    def reaction(self, fn: Callable[[], T], *, until: Callable[[T], bool], what: str, timeout: float) -> T:
        """Poll ``fn`` until ``until`` holds (flow interval/sleep/clock); ReactionTimeoutError "(SUT)" otherwise."""
        try:
            return waiting.poll(
                fn,
                until=until,
                timeout=timeout,
                interval=self.flow.poll_interval,
                what=what,
                sleep=self.flow.sleep,
                clock=self.flow.clock,
            )
        except waiting.WaitTimeoutError as exc:
            last = REDACTOR(repr(exc.last))[:1500]
            raise ReactionTimeoutError(
                f"webapp did not react within {timeout:g} s (SUT): {what}; last: {last}"
            ) from None

    def wait_validation(
        self, pr: ConfigPr, *, state: str | None = "success", timeout: float = VALIDATION_TIMEOUT
    ) -> dict[str, Any]:
        """Final validation status of the PR head; AssertionError unless its state is ``state`` (None: any state)."""
        status = self.flow.wait_status(pr, "validation", final=True, timeout=timeout)
        assert state is None or status.get("state") == state, (
            f"validation status of PR #{pr.number} at {pr.head_sha[:12]} is {status.get('state')!r} "
            f"({status.get('description')!r}), expected {state!r} (SUT)"
        )
        return status

    def wait_sync(self, pr: ConfigPr, *, timeout: float = SYNC_TIMEOUT) -> dict[str, Any]:
        """Final sync status of the PR head (its state is success even when out of sync, by design)."""
        return self.flow.wait_status(pr, "sync", final=True, timeout=timeout)

    def wait_settled(self, pr: ConfigPr) -> tuple[dict[str, Any], dict[str, Any]]:
        """Validation success and a final sync status: the open-PR tasks are done, so a merge cannot race them
        (otterdog#792: a late sync task could store its stale open snapshot over the merged state)."""
        return self.wait_validation(pr), self.wait_sync(pr)

    def wait_comment(
        self,
        pr: ConfigPr,
        *,
        marker: str | None = None,
        contains: str | None = None,
        exclude: Sequence[Mapping[str, Any]] = (),
        timeout: float = COMMENT_TIMEOUT,
    ) -> dict[str, Any]:
        """First new bot comment with ``marker`` / ``contains`` (comments in ``exclude`` do not count)."""
        excluded = {value for comment in exclude for value in comment_ids(comment)}
        return self.flow.wait_comment(pr, marker=marker, contains=contains, exclude_ids=excluded, timeout=timeout)

    def wait_check_sync_comment(
        self, pr: ConfigPr, *, exclude: Sequence[Mapping[str, Any]] = (), timeout: float = SYNC_TIMEOUT
    ) -> dict[str, Any]:
        """First new check-sync (out-of-sync) comment; the sync budget covers the task's backoff and live plan."""
        return self.wait_comment(pr, marker="check-sync", exclude=exclude, timeout=timeout)

    def current_comment(self, pr: ConfigPr, comment: Mapping[str, Any]) -> dict[str, Any]:
        """The PR comment ``comment`` as GitHub shows it now (AssertionError when it disappeared)."""
        wanted = comment.get("id")
        found = next((c for c in self.oracle.pr_comments(self.repo, pr.number) if c.get("id") == wanted), None)
        assert found is not None, f"comment {wanted} of PR #{pr.number} disappeared"
        return found

    def wait_applied(
        self, pr: ConfigPr, *, exclude: Sequence[Mapping[str, Any]] = (), timeout: float = APPLY_TIMEOUT
    ) -> dict[str, Any]:
        """The (first new) apply comment of a merged PR; AssertionError (SUT) unless it reports success."""
        excluded = {value for comment in exclude for value in comment_ids(comment)}
        comment = self.flow.wait_comment(pr, contains=Texts.APPLY_RESULT, exclude_ids=excluded, timeout=timeout)
        body = comment.get("body") or ""
        assert comment_contains(body, Texts.APPLY_SUCCESS) and Texts.APPLY_FAILURE not in body, (
            f"the webapp could not apply PR #{pr.number} (SUT):\n{REDACTOR(body)[:3000]}"
        )
        return comment

    def wait_merged(self, pr: ConfigPr, *, timeout: float = MERGE_TIMEOUT) -> dict[str, Any]:
        """The PR once GitHub reports it merged (ConfigRepoFlow.wait_merged)."""
        return self.flow.wait_merged(pr, timeout=timeout)

    def wait_minimized(
        self, pr: ConfigPr, comment: Mapping[str, Any], *, timeout: float = MINIMIZE_TIMEOUT
    ) -> dict[str, Any]:
        """The PR comment ``comment`` once GitHub reports it minimized (as outdated when a reason is given)."""
        wanted = comment.get("id")

        def current() -> dict[str, Any] | None:
            """The comment as GitHub shows it now."""
            return next((c for c in self.oracle.pr_comments(self.repo, pr.number) if c.get("id") == wanted), None)

        found = self.reaction(
            current,
            until=lambda value: value is not None and value.get("is_minimized") is True,
            what=f"comment {wanted} of PR #{pr.number} minimized",
            timeout=timeout,
        )
        assert found is not None  # reaction() only returns accepted values
        reason = str(found.get("minimized_reason") or Texts.OUTDATED_REASON)
        assert reason.lower() == Texts.OUTDATED_REASON, f"comment {wanted} minimized as {reason!r}, not outdated (SUT)"
        return found

    def wait_api_pull(
        self, pr: ConfigPr, *, until: Callable[[dict[str, Any]], bool], what: str, timeout: float = API_TIMEOUT
    ) -> dict[str, Any]:
        """The webapp's /api record of the PR once ``until(record)`` holds."""
        record = self.reaction(
            lambda: self.api.pull_request(self.org, self.repo, pr.number),
            until=lambda value: value is not None and until(value),
            what=f"/api record of PR #{pr.number} {what}",
            timeout=timeout,
        )
        assert record is not None  # reaction() only returns accepted values
        return record

    def wait_repo(self, name: str, *, timeout: float = STATE_TIMEOUT) -> dict[str, Any]:
        """GET /repos/{org}/{name} once the repository exists (oracle)."""
        repo = self.reaction(
            lambda: self.oracle.repo(name),
            until=lambda value: value is not None,
            what=f"repository {name} exists",
            timeout=timeout,
        )
        assert repo is not None  # reaction() only returns accepted values
        return repo

    def quiesce(self) -> None:
        """No webapp task of the org pending or running for QUIET_FOR seconds (ReactionTimeoutError otherwise)."""
        try:
            self.api.quiesce(org_id=self.org, quiet_for=QUIET_FOR, timeout=QUIESCE_TIMEOUT)
        except waiting.WaitTimeoutError as exc:
            raise ReactionTimeoutError(
                f"webapp tasks did not settle within {QUIESCE_TIMEOUT:g} s (SUT): {exc}"
            ) from None

    def latest_task_created(self, type_: str, pr: ConfigPr) -> datetime | None:
        """created_at (aware UTC) of the newest ``type_`` task of the PR, None when there is none."""
        stamps = [
            parse_timestamp(task.get("created_at"))
            for task in self.api.tasks(org_id=self.org, type_=type_, repo_name=self.repo)
            if task.get("pull_request") == pr.number
        ]
        return max((stamp for stamp in stamps if stamp is not None), default=None)

    def wait_task(self, type_: str, pr: ConfigPr, *, after: datetime, timeout: float = API_TIMEOUT) -> dict[str, Any]:
        """The newest finished/failed ``type_`` task of the PR created after ``after`` (ReactionTimeoutError)."""
        try:
            return self.api.wait_task(
                type_=type_, org_id=self.org, after=after, repo_name=self.repo, pull_request=pr.number, timeout=timeout
            )
        except waiting.WaitTimeoutError as exc:
            raise ReactionTimeoutError(
                f"webapp did not run {type_} for PR #{pr.number} within {timeout:g} s (SUT): {exc}"
            ) from None

    def webapp_includes(self, commit: str) -> bool | None:
        """Whether the webapp under test contains upstream ``commit``: answered for a compose stack whose image
        revision and ``commit`` are both in the upstream mirror; None when unknown (external webapp, prebuilt image
        without revision label, commit or revision missing from the mirror)."""
        if self.target.webapp.transport != "relay":
            return None
        from otterdog_e2e.sut.source import UpstreamMirror

        revision = self.e2e.image_for("head").revision  # memoized: the image the compose stack runs
        mirror = UpstreamMirror(self.e2e.settings.cache_dir, self.e2e.settings.upstream_repo)
        try:
            if not revision or not (mirror.has_commit(commit) and mirror.has_commit(revision)):
                return None
            return mirror.is_ancestor(commit, revision)
        except (OSError, ValueError, procs.CalledProcessError, procs.TimeoutExpired):  # mirror unusable: unknown
            return None

    def webapp_source_has(self, relative: str) -> bool | None:
        """Whether the source the webapp under test was built from contains the file ``relative`` (features that
        exist only in a local or PR build, e.g. uncommitted ones of a dirty: SUT): answered for a compose stack built
        from the SUT; None for an external webapp or a prebuilt --e2e-webapp-image."""
        if self.target.webapp.transport != "relay" or self.e2e.options.webapp_image:
            return None
        source = Path(self.e2e.resolve(self.e2e.options.sut).source_dir)  # memoized: the image's build context
        return (source / relative).is_file()

    def xfail_unless_includes(
        self,
        request: pytest.FixtureRequest,
        commit: str,
        *,
        error: type[BaseException],
        reason: str,
        strict: bool,
    ) -> bool | None:
        """Regression scoped to ``error`` (other failures, infra included, still fail): no mark when the webapp under
        test includes the fix ``commit``. Without it: ``strict`` xfail when every later version descends from that
        commit (an XPASS means the detection is wrong); non-strict xfail when the fix may still land as another
        commit (squash merge of an open PR) or inclusion is unknown, so an XPASS reveals the fix. Returns the
        inclusion (webapp_includes). A known-bug xfail added at collection (known_bugs.yaml listing the scenario)
        wins: pytest evaluates xfail marks at setup and re-reads them after the call only when there was none."""
        included = self.webapp_includes(commit)
        if included is False or (included is None and not strict):
            request.node.add_marker(pytest.mark.xfail(reason=reason, strict=strict and included is False, raises=error))
        return included

    def known_bug_reason(self, upstream_suffix: str, default: str) -> str:
        """xfail reason (``<id>: <title>``) of the known_bugs.yaml entry whose upstream URL ends with the suffix."""
        for bug in self.e2e.known_bugs().values():
            if (bug.upstream or "").rstrip("/").endswith(upstream_suffix):
                return bug.xfail_reason
        return default

    def write_evidence(self, data: Mapping[str, Any]) -> Path:
        """Redacted ``<artifacts>/webapp/<slug>.json`` with the scenario's observations (for reports and diffs)."""
        path = self.e2e.artifacts_dir / "webapp" / f"{self.slug}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(
            {"scenario": self.sid, "run": self.run_ctx.run_id, **data}, indent=2, sort_keys=True, default=str
        )
        path.write_text(REDACTOR(text) + "\n", encoding="utf-8")
        return path


@pytest.fixture
def webapp_scenario(
    request: pytest.FixtureRequest,
    e2e: E2EContext,
    webapp_case: WebappCase,
    config_flow: ConfigRepoFlow,
    webapp_api: WebappApi,
    renderer: OrgConfigRenderer,
    baseline: BaselineManager,
    oracle: Oracle,
    run_ctx: RunContext,
    target: Target,
) -> WebappScenario:
    """WebappScenario of the current test (its scenario(id) marker names branches, run repos and PR titles)."""
    marker = request.node.get_closest_marker("scenario")
    sid = str(marker.args[0]) if marker is not None and marker.args else request.node.name
    return WebappScenario(
        sid=sid,
        e2e=e2e,
        case=webapp_case,
        flow=config_flow,
        api=webapp_api,
        renderer=renderer,
        baseline=baseline,
        oracle=oracle,
        run_ctx=run_ctx,
        target=target,
    )
