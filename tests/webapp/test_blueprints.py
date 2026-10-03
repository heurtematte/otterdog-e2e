"""Blueprints of the webapp (coverage area ``blueprints``): definitions, /internal/check, remediation PRs and statuses.

Facts verified in otterdog main 9bdeb75 (identical in v1.6.1; texts unchanged since v1.4.0):

* definitions: org files ``otterdog/blueprints/*.yml`` of the config repo are fetched by FetchBlueprintsTask, scheduled
  by a push to config repo main touching that directory (webhook/__init__.py:262-315, the handler also re-reads the
  global ones) and by /internal/init; global files ``blueprints/*.yml`` of the configs repo are read by /internal/init
  and come first, so an org definition with a global id is skipped ("only the first encountered blueprint will be taken
  into account", docs/reference/blueprints/index.md). A definition raising KeyError, ValueError or RuntimeError (no
  ``type``, no ``id``, an unknown type, a pydantic error) is logged as ``failed reading blueprint from path '<path>'``
  and skipped (tasks/fetch_blueprints.py:78-93); a file that is no YAML mapping fails the whole task (KB-069,
  W-BP-LOAD-YAML). The project page /projects/<project> renders one ``blueprint-<id>`` tab per known blueprint (card
  title = name, ``Reference`` link = the definition URL, the config, the Status table);
* evaluation: /internal/check[/<limit>] evaluates the ``limit`` (default 50) blueprints of every org with the oldest
  ``last_checked`` (never checked first) unless they were checked less than BLUEPRINT_CHECK_INTERVAL seconds ago (0 in
  the e2e stack, configurable since otterdog#766 = v1.6.0, an hour before) and logs ``skipping blueprint with id '<id>'
  for org '<org>', last checked at ...`` at debug level otherwise (internal/routes.py:54-93); a repository is evaluated
  while its status is not_checked, recheck or failure (or for a changed definition, recheck_needed) and an evaluation
  task (CheckFilesTask, PinWorkflowTask, AppendConfigurationTask, CheckScorecardIntegrationTask) has no blueprint id:
  tasks are told apart by type and repository; a push to the default branch of a repository re-evaluates its
  blueprints when the commits touch their files (required paths, .github/workflows, otterdog/*.jsonnet);
* remediation: a PR from ``otterdog/blueprint/<id>`` (title PR_TITLES, body naming the blueprint, its definition URL,
  the dismissal note and the dashboard ``/organizations/<org>#blueprint-<id>``) sets ``remediation_prepared``; closing
  it unmerged sets ``dismissed`` with a ``blueprint-dismissal`` comment and the webapp deletes the branch (any closed
  ``otterdog/*`` head), reopening sets ``remediation_prepared`` again, merging sets ``recheck`` (and the push of the
  merge usually re-evaluates it to ``success`` first); since otterdog#766 a closed unmerged remediation PR found on
  GitHub restores ``dismissed`` when the stored status is lost (tasks/blueprints/__init__.py:50-104).

W-BP-LOAD: definitions load on push and init, a definition without type is skipped, a global id wins, removal unloads.
W-BP-LOAD-YAML (KB-069): invalid YAML in one definition must not block the others (non-strict xfail, scoped).
W-BP-GLOBAL-PUSH (KB-015): a push to the configs repo should reload the global definitions (non-strict xfail, scoped).
W-BP-UPDATE (KB-070): one fetch must store every changed field of a definition; ``recheck or update_if_changed(...)``
stops at the first changed one (db/service.py:933-961), so a new name is stored with the old config (scoped xfail).
W-BP-RECHECK-LOST (KB-071): a changed definition must be rechecked even when another fetch runs before the check;
every fetch assigns recheck_needed (db/service.py:958), so the second one clears it (scoped xfail).
W-BP-TYPE-CHANGE (KB-072): a definition that keeps its id and changes its type must keep /internal/check working;
the stored blueprint is keyed by its type (db/models.py:245-258) and never re-typed, so the new config fails the old
type's validation and /internal/check answers 500 on every call (scoped xfail; the test removes the definition).
W-BP-CHECK: BLUEPRINT_CHECK_INTERVAL skips due checks, /internal/check/1 evaluates the never-checked blueprint only.
W-BP-REQUIRED-FILE: required_file remediation PR (mustache context), /api/blueprints/remediations, strict files are
rewritten in the existing branch on a recheck while non-strict ones keep maintainer edits, merge -> success, a push
removing a required file re-evaluates the repository at once.
W-BP-DISMISS: close -> dismissed (comment, branch deleted, /api/blueprints/dismissed), check -> no new PR, reopen ->
reinstated, a lost status is restored from GitHub (regression of #766, strict xfail on older webapps).
W-BP-PIN: pin_workflow pins ``uses: owner/repo@tag`` to the tag's commit (``@<sha> # <tag>``), keeps ignore comments,
main references and local actions; merge -> success. A docker:// step makes otterdog skip the whole file (KB-073,
checked last: non-strict xfail scoped to DockerActionPinningError).
W-BP-APPEND: append_configuration opens a config PR appending the rendered snippet (team reviewers requested); the
webapp validates it, merging applies the new repository and the blueprint reports success.
W-BP-SCORECARD: scorecard_integration adds .github/workflows/scorecard-analysis.yml; merge -> success; the next check
runs SyncScorecardResultTask (no result is stored for a repository without published results).

Every definition, workflow and remediation PR is removed by the ``blueprints`` fixture, every run repository by the
webapp_case teardown. Tests that need a blueprint evaluated twice skip on webapps predating otterdog#766.
"""

from __future__ import annotations

import dataclasses
import json
import re
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from otterdog_e2e import waiting
from otterdog_e2e.blueprints import (
    BLUEPRINT,
    DISMISSAL_MARKER,
    GLOBAL,
    BlueprintDefinition,
    RequiredFile,
    scorecard_workflow,
)
from otterdog_e2e.config_repo import DeliveryTimeoutError, ReactionTimeoutError, check_forwarded, comment_contains
from otterdog_e2e.webapp.api import HtmlNode, WebappApiError, floor_to_millis, parse_html, parse_timestamp

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.blueprints import BlueprintHelper
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.webapp.stack import ExternalWebapp, WebappStack
    from otterdog_e2e.webhooks.relay import DeliveryRelay, RelayedDelivery

pytestmark = [pytest.mark.webapp]

DATA_DIR = Path(__file__).resolve().parent / "data" / "blueprints"
FIX_766 = "16f7f324009b0e64c1767174619c0858c50518a6"  # BLUEPRINT_CHECK_INTERVAL + dismissal found on GitHub (v1.6.0)
FETCH_BLUEPRINTS = "FetchBlueprintsTask"
UPDATE_STATUS_TASK = "UpdateBlueprintStatusTask"
CHECK_FILES_TASK = "CheckFilesTask"
APPEND_TASK = "AppendConfigurationTask"
SYNC_SCORECARD_TASK = "SyncScorecardResultTask"
FINAL = ("finished", "failed")
DISMISSAL_TEXT = "has been dismissed for this repo"  # templates/comment/dismissal_comment.txt
PR_DISMISS_NOTE = "Closing this PR without merging will dismiss this blueprint for this repository."
SKIPPING_LOG = "skipping blueprint with id '{id}' for org '{org}'"  # internal/routes.py:67-72 (debug)
FAILED_READING_LOG = "failed reading blueprint from path '{path}'"  # tasks/fetch_blueprints.py:92
DUPLICATE_LOG = "duplicate blueprint with id '{id}' in path '{path}', skipping"  # fetch_blueprints.py:88
STRICT_FILE = "E2E_BLUEPRINT.md"
LAX_FILE = "E2E_LAX.md"
# mustache context of required_file (tasks/blueprints/check_files.py:70-80)
STRICT_TEMPLATE = (
    "repo={{repo_name}}\norg={{github_id}}\nproject={{project_name}}\nblueprint={{blueprint_id}}\n"
    "description={{repo.description}}\nurl={{repo_url}}\n"
)
LAX_TEMPLATE = "lax file of {{repo_name}}\n"
MAINTAINER_EDIT = "edited by a maintainer of {repo}\n"
SCORECARD_WORKFLOW = ".github/workflows/scorecard-analysis.yml"  # ScorecardIntegrationBlueprint.workflow_name default
PINNED_CHECKOUT_RE = re.compile(r"^(\s+- uses: )actions/checkout@([0-9a-f]{40}) # (v4(?:\.\d+){0,2})$")
CHECKOUT_LINE = "      - uses: actions/checkout@v4"
LOG_TAIL = 4000
CLOCK_SKEW = timedelta(seconds=60)  # GitHub's delivered_at vs. the harness clock
# budgets (seconds)
DELIVERY_TIMEOUT = 300.0
LOAD_TIMEOUT = 240.0  # push delivery -> FetchBlueprintsTask -> project page
STORE_TIMEOUT = 240.0  # config repo main -> FetchConfigTask -> /api/organizations/<org>
EVALUATION_TIMEOUT = 300.0
STATUS_TIMEOUT = 300.0
GITHUB_TIMEOUT = 120.0  # GitHub-side preconditions (workflow registration, branch deletion)
GLOBAL_RELOAD_TIMEOUT = 180.0
LONG_TIMEOUT = 2400


class DefinitionLoadingError(AssertionError):
    """One unreadable definition file kept the valid definitions of the org from loading (W-BP-LOAD-YAML, KB-069)."""


class GlobalPushReloadError(AssertionError):
    """A push to the configs repository did not reload the global definitions (KB-015)."""


class DockerActionPinningError(AssertionError):
    """pin_workflow skipped a workflow because one of its steps uses a docker:// action (W-BP-PIN, KB-073)."""


class DismissalLostError(AssertionError):
    """A dismissed remediation PR was recreated after the stored status was lost (fixed by otterdog#766)."""


class BlueprintUpdateError(AssertionError):
    """A definition change touching several fields was stored only partly by one fetch (W-BP-UPDATE, KB-070)."""


class RecheckLostError(AssertionError):
    """A changed definition was not re-evaluated because a later fetch reset its recheck flag (KB-071)."""


class BlueprintTypeChangeError(AssertionError):
    """A definition that changed its type (same id) broke /internal/check (the type is part of the stored key)."""


# --- helpers --------------------------------------------------------------------------------------------------------
def _data(file_name: str, /, **values: str) -> str:
    """tests/webapp/data/blueprints/<name> with its ``@KEY@`` placeholders replaced."""
    text = (DATA_DIR / file_name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@{key.upper()}@", value)
    leftover = re.findall(r"@[A-Z]+@", text)
    assert not leftover, f"unreplaced placeholders {leftover} in {file_name}"
    return text


def _require_rechecks(s: WebappScenario) -> None:
    """Skip on webapps predating otterdog#766 (v1.6.0): BLUEPRINT_CHECK_INTERVAL was a hardcoded hour, so a blueprint
    is evaluated at most once an hour and a lifecycle needing a second evaluation cannot run within one test."""
    if s.webapp_includes(FIX_766) is False:
        pytest.skip("the webapp under test predates otterdog#766 (v1.6.0): blueprints are re-evaluated at most hourly")


def _foreign_globals(bp: BlueprintHelper, kind: str) -> dict[str, str]:
    """{type: path} of the global definitions of the configs repo that this test did not write (other owners, or
    leftovers of an earlier test of this run whose cleanup failed: the webapp keeps one global definition per type)."""
    found: dict[str, str] = {}
    for path, text in bp.listing(kind, GLOBAL).items():
        if (bp.configs_repo, path) in bp.written:
            continue
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(document, dict) and isinstance(document.get("type"), str):
            found.setdefault(document["type"], path)
    return found


def _skip_if_foreign_global(bp: BlueprintHelper, kind: str, *types: str) -> None:
    """Skip when the configs repo holds a global definition of ``types`` this test did not write (the webapp keeps one
    global definition per type: this test could not isolate its own)."""
    foreign = _foreign_globals(bp, kind)
    clashing = {type_: path for type_, path in foreign.items() if type_ in types}
    if clashing:
        pytest.skip(
            f"{bp.configs_repo} holds foreign global {kind} definitions {clashing}: they would shadow this test"
        )


def _blob_url(org: str, repo: str, branch: str, path: str) -> str:
    """URL of a definition file as otterdog records it (``path`` of the blueprint)."""
    return f"https://github.com/{org}/{repo}/blob/{branch}/{path}"


def _project_page(s: WebappScenario, bp: BlueprintHelper) -> str:
    """HTML of /projects/<project> (rendered from the webapp database)."""
    return s.api.get(f"/projects/{urllib.parse.quote(bp.project_name(), safe='')}").text


def _card(pane: HtmlNode | None) -> dict[str, str] | None:
    """name (first card title), path (the Reference link) and config text of a blueprint or policy pane."""
    if pane is None:
        return None
    titles = [node.text() for node in pane.iter("h3") if node.has_class("card-title")]
    links = [
        node.attrs.get("href", "")
        for node in pane.iter("a")
        if node.attrs.get("target") == "_blank" and node.text() == node.attrs.get("href")
    ]
    configs = [node.text() for node in pane.iter("pre")]
    return {
        "name": titles[0] if titles else "",
        "path": links[0] if links else "",
        "config": configs[0] if configs else "",
    }


def _blueprint_card(page: str, blueprint_id: str) -> dict[str, str] | None:
    """The ``blueprint-<id>`` pane of the project page, None when the webapp does not know the blueprint."""
    return _card(parse_html(page).find_id(f"blueprint-{blueprint_id}"))


def _wait_card(
    s: WebappScenario, bp: BlueprintHelper, blueprint_id: str, *, until: Any, what: str, timeout: float = LOAD_TIMEOUT
) -> dict[str, str] | None:
    """The blueprint's card once ``until(card)`` holds (ReactionTimeoutError, SUT)."""
    card: dict[str, str] | None = s.reaction(
        lambda: _blueprint_card(_project_page(s, bp), blueprint_id), until=until, what=what, timeout=timeout
    )
    return card


def _wait_push(relay: DeliveryRelay, repo: str, sha: str, *, after: datetime) -> RelayedDelivery:
    """The relayed push delivery of ``repo`` at ``sha``, checked as forwarded (infra / SUT classification)."""

    def matches(delivery: RelayedDelivery) -> bool:
        """The push of exactly this commit."""
        return (
            delivery.event == "push"
            and delivery.repository_name == repo
            and delivery.head_sha == sha
            and delivery.delivered_at >= after - CLOCK_SKEW
        )

    try:
        delivery = relay.wait_for(matches, timeout=DELIVERY_TIMEOUT)
    except waiting.WaitTimeoutError:
        raise DeliveryTimeoutError(
            f"push delivery of {repo}@{sha[:12]} not observed within {DELIVERY_TIMEOUT:g} s (infra)"
        ) from None
    check_forwarded(delivery, f"push of {repo}@{sha[:12]}")
    return delivery


def _push_fetch(s: WebappScenario, bp: BlueprintHelper, relay: DeliveryRelay) -> dict[str, Any]:
    """After committing org definitions: the push delivery of config repo main and the FetchBlueprintsTask it
    scheduled, once final. Used instead of reload() where a definition change must be checked: every fetch overwrites
    the recheck flag, so a second fetch before /internal/check would drop the recheck (W-BP-RECHECK-LOST)."""
    pushed = bp.now()
    _wait_push(relay, s.repo, s.flow.main_sha(), after=pushed)
    return bp.wait_fetch(after=pushed, tasks=(FETCH_BLUEPRINTS,))[FETCH_BLUEPRINTS]


def _tasks_after(s: WebappScenario, type_: str, repo: str, after: datetime) -> list[dict[str, Any]]:
    """Final tasks of ``type_`` for ``repo`` created after ``after``, newest first."""
    floor = floor_to_millis(after)
    found = []
    for task in s.api.tasks(org_id=s.org, type_=type_, repo_name=repo):
        created = parse_timestamp(task.get("created_at"))
        if created is not None and created >= floor and task.get("status") in FINAL:
            found.append(task)
    return found


def _wait_task(
    s: WebappScenario,
    type_: str,
    repo: str,
    *,
    after: datetime,
    pull_request: int | None = None,
    timeout: float = EVALUATION_TIMEOUT,
) -> dict[str, Any]:
    """The newest final ``type_`` task of ``repo`` (and PR) created after ``after`` (ReactionTimeoutError, SUT)."""
    try:
        return s.api.wait_task(
            type_=type_, org_id=s.org, after=after, repo_name=repo, pull_request=pull_request, timeout=timeout
        )
    except waiting.WaitTimeoutError as exc:
        raise ReactionTimeoutError(f"webapp did not run {type_} for {repo} within {timeout:g} s (SUT): {exc}") from None


def _wait_tasks(s: WebappScenario, type_: str, repo: str, *, after: datetime, count: int) -> list[dict[str, Any]]:
    """Exactly ``count`` final ``type_`` tasks of ``repo`` created after ``after`` once the webapp is quiet."""
    s.reaction(
        lambda: _tasks_after(s, type_, repo, after),
        until=lambda tasks: len(tasks) >= count,
        what=f"{count} {type_} task(s) for {repo}",
        timeout=EVALUATION_TIMEOUT,
    )
    s.quiesce()
    tasks = _tasks_after(s, type_, repo, after)
    assert len(tasks) == count, f"{len(tasks)} {type_} task(s) for {repo} after {after}, expected {count}: {tasks}"
    return tasks


def _wait_stored(s: WebappScenario, names: list[str]) -> None:
    """The configuration stored by the webapp declares ``names`` (FetchConfigTask after the push to main)."""

    def declared() -> set[str]:
        """Repository names of /api/organizations/<org>."""
        config = s.api.organization(s.org) or {}
        return {str(repo.get("name")) for repo in config.get("repositories") or [] if isinstance(repo, dict)}

    s.reaction(
        declared,
        until=lambda found: set(names) <= found,
        what=f"stored configuration of {s.org} declares {sorted(names)}",
        timeout=STORE_TIMEOUT,
    )


def _wait_github(s: WebappScenario, fn: Any, *, until: Any, what: str) -> Any:
    """GitHub-side precondition (not a webapp reaction): DeliveryTimeoutError "(infra)" when it never holds."""
    try:
        return s.reaction(fn, until=until, what=what, timeout=GITHUB_TIMEOUT)
    except ReactionTimeoutError as exc:
        raise DeliveryTimeoutError(f"GitHub precondition not met within {GITHUB_TIMEOUT:g} s (infra): {exc}") from None


def _pr_files(s: WebappScenario, repo: str, number: int) -> dict[str, str]:
    """{filename: status} of a pull request (GET pulls/{n}/files)."""
    path = f"/repos/{urllib.parse.quote(s.org, safe='')}/{urllib.parse.quote(repo, safe='')}/pulls/{int(number)}/files"
    files = s.oracle.http.get(path, params={"per_page": 100}) or []
    return {str(item.get("filename")): str(item.get("status")) for item in files if isinstance(item, dict)}


def _bot_comments(s: WebappScenario, repo: str, number: int, marker: str) -> list[dict[str, Any]]:
    """Comments of the App bot carrying ``marker`` on a PR of any repository of the org."""
    slug = (s.flow.bot_login or "").removesuffix("[bot]")
    return [
        comment
        for comment in s.oracle.pr_comments(repo, number)
        if comment.get("author") in (slug, f"{slug}[bot]") and marker in (comment.get("body") or "")
    ]


def _assert_remediation_body(
    s: WebappScenario, pull: dict[str, Any], definition: BlueprintDefinition, path: str
) -> None:
    """The remediation PR body names the blueprint and its definition, says how to dismiss it and links the dashboard
    (templates/comment/blueprint_pr_body.txt)."""
    body = pull.get("body") or ""
    expected = {
        "the blueprint name and definition": f"[{definition.name}]({path})",
        "the dismissal note": PR_DISMISS_NOTE,
        "the dashboard": f"/organizations/{s.org}#blueprint-{definition.id}",
    }
    missing = [what for what, text in expected.items() if not comment_contains(body, text)]
    assert not missing, f"remediation PR #{pull.get('number')} body lacks {missing} (SUT):\n{body[:2000]}"


def _after_merge(
    s: WebappScenario, bp: BlueprintHelper, definition: BlueprintDefinition, repo: str, number: int, merged_at: datetime
) -> dict[str, Any]:
    """After merging remediation PR #number: the UpdateBlueprintStatusTask of the PR finished, the status is recheck or
    already success (the push of the merge re-evaluates the repository), and once a check ran (webapps with #766)
    success without a remediation PR; returns the last status row."""
    task = _wait_task(s, UPDATE_STATUS_TASK, repo, after=merged_at, pull_request=number)
    assert task.get("status") == "finished", f"{UPDATE_STATUS_TASK} of merged PR #{number} failed (SUT): {task}"
    row = bp.wait_status(definition.id, repo, ("recheck", "success"), timeout=STATUS_TIMEOUT)
    if s.webapp_includes(FIX_766) is not False:
        bp.check()
        row = bp.wait_status(definition.id, repo, "success", timeout=STATUS_TIMEOUT)
    assert row.get("remediation_pr") is None, f"status of {definition.id} for {repo} keeps a remediation PR: {row}"
    return row


def _remediation_ids(rows: list[dict[str, Any]]) -> set[tuple[Any, Any, Any, Any]]:
    """(org, repo, blueprint id, PR) of /api/blueprints/remediations|dismissed rows."""
    return {
        (
            (row.get("id") or {}).get("org_id"),
            (row.get("id") or {}).get("repo_name"),
            (row.get("id") or {}).get("blueprint_id"),
            row.get("remediation_pr"),
        )
        for row in rows
    }


def _nomatch(s: WebappScenario, suffix: str = "nomatch") -> str:
    """A repository name pattern no repository matches (e2e-<run>-<slug>-<suffix>)."""
    return s.run_ctx.name(f"{s.slug}-{suffix}")


# --- loading --------------------------------------------------------------------------------------------------------
@pytest.mark.scenario("W-BP-LOAD", priority="P2")
@pytest.mark.tags("webapp", "webhooks-app")
def test_blueprint_definitions_are_loaded(
    webapp_scenario: WebappScenario,
    blueprints: BlueprintHelper,
    relay: DeliveryRelay,
    webapp: WebappStack | ExternalWebapp,
) -> None:
    """Org definitions load with the push of config repo main (an untyped one is logged and skipped); an init loads a
    global definition, which then wins over an org definition of the same id; removing an org file unloads it."""
    s, bp = webapp_scenario, blueprints
    _skip_if_foreign_global(bp, BLUEPRINT, "pin_workflow")
    run, nomatch = s.run_ctx.run_id, _nomatch(s)
    loaded = BlueprintDefinition.pin_workflow(
        bp.blueprint_id(s.slug), name_pattern=nomatch, name=f"e2e {run} org pin", description=s.describe("org")
    )
    untyped_id = bp.blueprint_id(f"{s.slug}-untyped")
    started = bp.now()
    loaded_path = bp.add_blueprint(loaded)
    untyped_path = bp.add_definition_text(
        BLUEPRINT, f"{s.slug}-untyped", _data("definition-without-type.yml", run=run, id=untyped_id, nomatch=nomatch)
    )
    pushed = bp.now()
    _wait_push(relay, s.repo, s.flow.main_sha(), after=pushed)
    card = _wait_card(s, bp, loaded.id, until=lambda c: c is not None, what=f"blueprint {loaded.id} loaded on push")
    assert card is not None  # _wait_card only returns accepted values
    assert card["name"] == loaded.name, f"card title of {loaded.id}: {card}"
    assert card["path"] == _blob_url(s.org, s.repo, "main", loaded_path), f"definition URL of {loaded.id}: {card}"
    assert nomatch in card["config"], f"the config of {loaded.id} lacks its repo selector: {card}"
    assert _blueprint_card(_project_page(s, bp), untyped_id) is None, "a definition without 'type' was loaded (SUT)"
    fetches = _tasks_after(s, FETCH_BLUEPRINTS, s.repo, started)
    assert fetches, f"no {FETCH_BLUEPRINTS} ran after the pushes to {s.repo} (SUT)"
    failed = [task for task in fetches if task.get("status") != "finished"]
    assert not failed, f"{FETCH_BLUEPRINTS} failed on a definition without 'type' instead of skipping it: {failed}"
    if hasattr(webapp, "logs"):  # compose stack: the skipped file is reported with its path
        logs = webapp.logs(tail=LOG_TAIL)
        assert FAILED_READING_LOG.format(path=untyped_path) in logs, f"the webapp log does not report {untyped_path}"

    # a global definition, loaded by /internal/init, wins over an org definition pushed later with the same id
    dup_id = bp.blueprint_id(f"{s.slug}-dup")
    global_dup = BlueprintDefinition.pin_workflow(dup_id, name_pattern=nomatch, name=f"e2e {run} global dup")
    global_path = bp.add_blueprint(global_dup, scope=GLOBAL)
    fetch = bp.reload(tasks=(FETCH_BLUEPRINTS,))[FETCH_BLUEPRINTS]
    assert fetch.get("status") == "finished", f"{FETCH_BLUEPRINTS} after /internal/init failed (SUT): {fetch}"
    expected = _blob_url(s.org, bp.configs_repo, "main", global_path)  # global paths always name 'main' (utils.py:300)
    card = _blueprint_card(_project_page(s, bp), dup_id)
    assert card is not None and card["name"] == global_dup.name and card["path"] == expected, (
        f"/internal/init did not load the global blueprint {dup_id} (SUT): {card}"
    )
    org_dup = BlueprintDefinition.required_file(
        dup_id, files=[RequiredFile("E2E_NEVER.md", "never")], name_pattern=nomatch, name=f"e2e {run} org dup"
    )
    org_dup_path = bp.add_blueprint(org_dup)
    fetch = _push_fetch(s, bp, relay)
    assert fetch.get("status") == "finished", f"push-triggered {FETCH_BLUEPRINTS} failed (SUT): {fetch}"
    card = _blueprint_card(_project_page(s, bp), dup_id)
    assert card is not None and card["name"] == global_dup.name and card["path"] == expected, (
        f"an org definition replaced the global blueprint {dup_id} of the same id (SUT): {card}"
    )
    assert "'files'" not in card["config"], f"{dup_id} shows the org (required_file) config: {card}"
    if hasattr(webapp, "logs"):  # compose stack: the skipped org definition is reported
        logs = webapp.logs(tail=LOG_TAIL)
        duplicate = DUPLICATE_LOG.format(id=dup_id, path=org_dup_path)
        assert duplicate in logs, f"the webapp log does not report the duplicate org definition {org_dup_path}"

    # removing the org file unloads the org blueprint, the global one stays
    bp.remove_blueprint(loaded)
    _push_fetch(s, bp, relay)
    _wait_card(s, bp, loaded.id, until=lambda c: c is None, what=f"blueprint {loaded.id} unloaded after its removal")
    card = _blueprint_card(_project_page(s, bp), dup_id)
    assert card is not None and card["name"] == global_dup.name, f"{dup_id} lost its global definition: {card}"


@pytest.mark.scenario("W-BP-LOAD-YAML", priority="P2")
@pytest.mark.tags("webapp")
@pytest.mark.known_bug("KB-069")
@pytest.mark.xfail(
    raises=DefinitionLoadingError,
    strict=False,
    reason="KB-069: one unreadable definition file fails the whole FetchBlueprintsTask",
)
def test_invalid_yaml_definition_does_not_block_the_others(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper
) -> None:
    """A definition file that is not YAML is skipped and the valid definition next to it loads (the broken file is
    committed first, so no fetch can load the valid one before the broken file exists)."""
    s, bp = webapp_scenario, blueprints
    run, nomatch = s.run_ctx.run_id, _nomatch(s)
    broken_id = bp.blueprint_id(f"{s.slug}-broken")
    bp.add_definition_text(
        BLUEPRINT, f"{s.slug}-broken", _data("definition-invalid-yaml.yml", run=run, id=broken_id, nomatch=nomatch)
    )
    valid = BlueprintDefinition.pin_workflow(bp.blueprint_id(s.slug), name_pattern=nomatch, name=f"e2e {run} valid")
    bp.add_blueprint(valid)
    fetch = bp.reload(tasks=(FETCH_BLUEPRINTS,))[FETCH_BLUEPRINTS]
    card = _blueprint_card(_project_page(s, bp), valid.id)
    s.write_evidence({"fetch": fetch, "valid_card": card})
    if fetch.get("status") != "finished" or card is None:
        raise DefinitionLoadingError(
            f"one invalid YAML definition kept {valid.id} from loading: {FETCH_BLUEPRINTS} {fetch.get('status')} "
            f"({str(fetch.get('log'))[:300]!r}), card {card}"
        )
    assert card["name"] == valid.name, f"card of {valid.id}: {card}"


@pytest.mark.scenario("W-BP-GLOBAL-PUSH", priority="P2")
@pytest.mark.tags("webapp", "webhooks-app")
@pytest.mark.known_bug("KB-015")
@pytest.mark.xfail(
    raises=GlobalPushReloadError,
    strict=False,
    reason="KB-015: pushes to the configs repo arrive as App deliveries and never reach the reload branch",
)
def test_global_definitions_reload_on_configs_push(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper, relay: DeliveryRelay
) -> None:
    """A global definition pushed to the configs repo is loaded without /internal/init (webhook/__init__.py:319-334)."""
    s, bp = webapp_scenario, blueprints
    _skip_if_foreign_global(bp, BLUEPRINT, "pin_workflow")
    definition = BlueprintDefinition.pin_workflow(
        bp.blueprint_id(s.slug), name_pattern=_nomatch(s), name=f"e2e {s.run_ctx.run_id} global pushed"
    )
    path = bp.add_blueprint(definition, scope=GLOBAL)
    pushed = bp.now()
    branch = s.oracle.default_branch(bp.configs_repo) or "main"
    sha = s.oracle.branch_sha(bp.configs_repo, branch)
    assert sha, f"{bp.configs_repo} has no branch {branch!r}"
    _wait_push(relay, bp.configs_repo, sha, after=pushed)
    try:
        card = _wait_card(
            s,
            bp,
            definition.id,
            until=lambda c: c is not None,
            what=f"global blueprint {definition.id} loaded after the push to {bp.configs_repo}",
            timeout=GLOBAL_RELOAD_TIMEOUT,
        )
    except ReactionTimeoutError:
        raise GlobalPushReloadError(
            f"the push of {bp.configs_repo}/{path} was forwarded but the webapp did not reload its global blueprints "
            f"within {GLOBAL_RELOAD_TIMEOUT:g} s"
        ) from None
    assert card is not None and card["path"] == _blob_url(s.org, bp.configs_repo, "main", path), f"card: {card}"


@pytest.mark.scenario("W-BP-UPDATE", priority="P2")
@pytest.mark.tags("webapp")
@pytest.mark.known_bug("KB-070")
@pytest.mark.xfail(
    raises=BlueprintUpdateError,
    strict=False,
    reason="KB-070: a definition change touching several fields is stored one field per FetchBlueprintsTask",
)
def test_changed_definition_is_stored_by_one_fetch(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper, relay: DeliveryRelay
) -> None:
    """A commit changing the name and the repo selector of a definition is stored completely by the fetch it triggers
    (the new name proves that this fetch ran; db/service.py:933-961 stops at the first changed field)."""
    s, bp = webapp_scenario, blueprints
    first, second = _nomatch(s, "nomatch-1"), _nomatch(s, "nomatch-2")
    definition = BlueprintDefinition.pin_workflow(
        bp.blueprint_id(s.slug), name_pattern=first, name=f"e2e {s.run_ctx.run_id} v1"
    )
    bp.add_blueprint(definition)
    fetch = _push_fetch(s, bp, relay)
    assert fetch.get("status") == "finished", f"{FETCH_BLUEPRINTS} failed (SUT): {fetch}"
    card = _wait_card(s, bp, definition.id, until=lambda c: c is not None and first in c["config"], what="v1 loaded")
    assert card is not None and card["name"] == definition.name, f"v1 card: {card}"

    updated = BlueprintDefinition.pin_workflow(definition.id, name_pattern=second, name=f"e2e {s.run_ctx.run_id} v2")
    bp.add_blueprint(updated)
    fetch = _push_fetch(s, bp, relay)
    assert fetch.get("status") == "finished", f"{FETCH_BLUEPRINTS} of the update failed (SUT): {fetch}"
    card = _blueprint_card(_project_page(s, bp), definition.id)
    assert card is not None and card["name"] == updated.name, f"the fetch of the update did not store its name: {card}"
    s.write_evidence({"after_one_fetch": card})
    if second not in card["config"] or first in card["config"]:
        raise BlueprintUpdateError(
            f"one fetch stored the new name of {definition.id} but kept the old repo selector: {card['config']!r}"
        )


@pytest.mark.scenario("W-BP-RECHECK-LOST", priority="P2")
@pytest.mark.tags("webapp")
@pytest.mark.known_bug("KB-071")
@pytest.mark.xfail(
    raises=RecheckLostError,
    strict=False,
    reason="KB-071: every FetchBlueprintsTask overwrites recheck_needed, a second fetch drops a pending recheck",
)
def test_changed_definition_is_rechecked_after_another_fetch(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper, relay: DeliveryRelay
) -> None:
    """A changed definition of a blueprint in status success is re-evaluated by the next /internal/check (control:
    one fetch), also when another fetch (an /internal/init) ran in between (db/service.py:958 assigns the flag)."""
    s, bp = webapp_scenario, blueprints
    _require_rechecks(s)
    definition = BlueprintDefinition.append_configuration(
        bp.blueprint_id(s.slug),
        condition=f'$count($.repositories[name = "{s.repo}"]) = 0',  # the config repo is declared: false, success
        content="{}",
        name=f"e2e {s.run_ctx.run_id} recheck",
        description="version 1",
    )
    bp.add_blueprint(definition)
    bp.reload(tasks=(FETCH_BLUEPRINTS,))
    task = bp.wait_evaluation(definition, s.repo, after=bp.check())
    assert task.get("status") == "finished", f"{APPEND_TASK} failed (SUT): {task}"
    bp.wait_status(definition.id, s.repo, "success")
    s.quiesce()

    bp.add_blueprint(dataclasses.replace(definition, description="version 2"))
    _push_fetch(s, bp, relay)
    _wait_tasks(s, APPEND_TASK, s.repo, after=bp.check(), count=1)  # control: the changed definition is rechecked

    bp.add_blueprint(dataclasses.replace(definition, description="version 3"))
    _push_fetch(s, bp, relay)
    bp.reload(tasks=(FETCH_BLUEPRINTS,))  # a second fetch of the same definitions before the check
    checked = bp.check()
    s.quiesce()
    rechecks = _tasks_after(s, APPEND_TASK, s.repo, checked)
    if not rechecks:
        raise RecheckLostError(f"the changed definition {definition.id} was not re-evaluated after a second fetch")
    assert len(rechecks) == 1, f"{len(rechecks)} evaluations of {definition.id}: {rechecks}"


@pytest.mark.scenario("W-BP-TYPE-CHANGE", priority="P2")
@pytest.mark.tags("webapp")
@pytest.mark.known_bug("KB-072")
@pytest.mark.xfail(
    raises=BlueprintTypeChangeError,
    strict=False,
    reason="KB-072: a blueprint keeps its type when its definition changes type, /internal/check then fails",
)
def test_changed_type_keeps_the_check_working(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper, relay: DeliveryRelay
) -> None:
    """The definition file of a required_file blueprint becomes a pin_workflow one (same id): after the fetches that
    store it (two are needed, see W-BP-UPDATE) /internal/check still answers 200 and the project page shows the new
    config. The definition is removed again before the test ends: a failing check would block every blueprint."""
    s, bp = webapp_scenario, blueprints
    run, nomatch = s.run_ctx.run_id, _nomatch(s)
    blueprint_id = bp.blueprint_id(s.slug)
    before = BlueprintDefinition.required_file(
        blueprint_id, files=[RequiredFile("E2E_NEVER.md", "never")], name_pattern=nomatch, name=f"e2e {run} v1"
    )
    after = BlueprintDefinition.pin_workflow(blueprint_id, name_pattern=nomatch, name=f"e2e {run} v2")
    bp.add_blueprint(before)
    _push_fetch(s, bp, relay)
    card = _wait_card(s, bp, blueprint_id, until=lambda c: c is not None, what=f"{blueprint_id} loaded")
    assert card is not None and "'files'" in card["config"], f"required_file definition not loaded: {card}"
    bp.check()  # the required_file blueprint is evaluated (no repository matches) and gets its last_checked
    try:
        bp.add_blueprint(after)  # the same file: otterdog/blueprints/<id>.yml
        _push_fetch(s, bp, relay)
        for _ in range(2):  # one changed field per fetch (W-BP-UPDATE): name, then config
            bp.reload(tasks=(FETCH_BLUEPRINTS,))
        card = _blueprint_card(_project_page(s, bp), blueprint_id)
        s.write_evidence({"card": card})
        try:
            bp.check()
        except WebappApiError as exc:
            raise BlueprintTypeChangeError(
                f"/internal/check answers HTTP {exc.status} once {blueprint_id} changed from required_file to "
                f"pin_workflow (stored config: {card and card['config']!r})"
            ) from None
        assert card is not None and card["name"] == after.name, f"the type change was not stored: {card}"
        assert "'files'" not in card["config"] and nomatch in card["config"], f"stored config: {card['config']!r}"
    finally:
        bp.remove_blueprint(after)  # the fetch drops the inconsistent blueprint: /internal/check works again
        bp.reload(tasks=(FETCH_BLUEPRINTS,))


# --- /internal/check ------------------------------------------------------------------------------------------------
def _failing_append(bp: BlueprintHelper, s: WebappScenario, suffix: str) -> BlueprintDefinition:
    """An append_configuration blueprint whose condition is a JSONata string, not a boolean: every evaluation of the
    config repo ends in status failure without any GitHub write, and failure is re-evaluated by every due check."""
    blueprint_id = bp.blueprint_id(f"{s.slug}-{suffix}")
    return BlueprintDefinition.append_configuration(
        blueprint_id,
        condition=json.dumps(f"{blueprint_id} is not a boolean"),
        content="{}",
        name=f"e2e {s.run_ctx.run_id} failing check {suffix}",
    )


def _add_org_definition(bp: BlueprintHelper, s: WebappScenario, suffix: str, definition: BlueprintDefinition) -> None:
    """Commit an org blueprint whose type another definition of this test already uses (the helper's add_blueprint
    keeps one definition per type and scope; org blueprints are additive)."""
    assert definition.id == bp.blueprint_id(f"{s.slug}-{suffix}")
    bp.add_definition_text(BLUEPRINT, f"{s.slug}-{suffix}", definition.to_yaml())


@pytest.mark.scenario("W-BP-CHECK", priority="P2")
@pytest.mark.tags("webapp")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_check_interval_and_limit(
    webapp_scenario: WebappScenario,
    blueprints: BlueprintHelper,
    webapp_env: Callable[[Mapping[str, str]], None],
    webapp: WebappStack | ExternalWebapp,
) -> None:
    """With BLUEPRINT_CHECK_INTERVAL=3600 a second /internal/check skips both evaluated blueprints (logged at debug
    level); with 0 again /internal/check/1 evaluates only the never-checked blueprint and /internal/check all three."""
    s, bp = webapp_scenario, blueprints
    _require_rechecks(s)
    foreign = _foreign_globals(bp, BLUEPRINT)
    if "append_configuration" in foreign:
        pytest.skip(
            f"foreign global append_configuration blueprint {foreign['append_configuration']} evaluates the "
            "config repo too: the evaluation counts would be off"
        )
    first, second, third = (_failing_append(bp, s, suffix) for suffix in ("1", "2", "3"))
    _add_org_definition(bp, s, "1", first)
    _add_org_definition(bp, s, "2", second)
    bp.reload(tasks=(FETCH_BLUEPRINTS,))
    checked = bp.check()
    _wait_tasks(s, APPEND_TASK, s.repo, after=checked, count=2)
    for definition in (first, second):
        row = bp.wait_status(definition.id, s.repo, "failure")
        assert row.get("remediation_pr") is None, f"a failing condition prepared a remediation: {row}"

    webapp_env({"BLUEPRINT_CHECK_INTERVAL": "3600"})
    skipped = bp.check()
    s.quiesce()
    evaluated = _tasks_after(s, APPEND_TASK, s.repo, skipped)
    assert not evaluated, f"/internal/check evaluated blueprints checked less than an hour ago (SUT): {evaluated}"
    if hasattr(webapp, "logs"):  # compose: DEBUG=True logs the skipped blueprints (docs/reference/blueprints)
        logs = webapp.logs(tail=LOG_TAIL)
        quiet = [d.id for d in (first, second) if SKIPPING_LOG.format(id=d.id, org=s.org) not in logs]
        assert not quiet, f"no 'skipping blueprint' debug line for {quiet} in the webapp log"

    webapp_env({})  # BLUEPRINT_CHECK_INTERVAL back to 0 (compose default)
    _add_org_definition(bp, s, "3", third)
    bp.reload(tasks=(FETCH_BLUEPRINTS,))
    limited = bp.check(1)
    _wait_tasks(s, APPEND_TASK, s.repo, after=limited, count=1)
    row = bp.wait_status(third.id, s.repo, "failure")
    assert row is not None, f"/internal/check/1 did not evaluate the never-checked blueprint {third.id}"

    everything = bp.check()
    _wait_tasks(s, APPEND_TASK, s.repo, after=everything, count=3)


# --- required_file and the remediation lifecycle -------------------------------------------------------------------
def _strict_content(*, repo: str, org: str, project: str, blueprint_id: str, description: str) -> str:
    """STRICT_TEMPLATE rendered for ``repo`` (chevron, html-escaping: descriptions of the harness need none)."""
    return (
        f"repo={repo}\norg={org}\nproject={project}\nblueprint={blueprint_id}\ndescription={description}\n"
        f"url=https://github.com/{org}/{repo}\n"
    )


@pytest.mark.scenario("W-BP-REQUIRED-FILE", priority="P2")
@pytest.mark.tags("webapp", "repo")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_required_file_remediation(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper, relay: DeliveryRelay, mutator: Mutator
) -> None:
    """Remediation PR with rendered files, /api/blueprints/remediations, strict rewrite on a recheck (non-strict edits
    kept), merge -> success, and a push removing the strict file re-evaluates the repository at once."""
    s, bp = webapp_scenario, blueprints
    _require_rechecks(s)
    repo, description = s.run_repo("a"), s.describe("required_file target")
    s.declare_live({repo: description})
    definition = BlueprintDefinition.required_file(
        bp.blueprint_id(s.slug),
        files=[RequiredFile(STRICT_FILE, STRICT_TEMPLATE, strict=True), RequiredFile(LAX_FILE, LAX_TEMPLATE)],
        name_pattern=[repo, f"{_nomatch(s)}-.*"],
        name=f"e2e {s.run_ctx.run_id} required files",
        description=s.describe("required_file blueprint"),
    )
    path = bp.add_blueprint(definition)
    bp.reload()
    _wait_stored(s, [repo])
    task = bp.wait_evaluation(definition, repo, after=bp.check())
    assert task.get("status") == "finished", f"{definition.task_type} of {repo} failed (SUT): {task}"

    pull = bp.wait_remediation_pr(repo, definition)
    number, branch = int(pull["number"]), definition.remediation_branch
    expected = _strict_content(
        repo=repo, org=s.org, project=bp.project_name(), blueprint_id=definition.id, description=description
    )
    assert pull.get("title") == definition.pr_title, f"remediation PR title: {pull.get('title')!r}"
    assert (pull.get("base") or {}).get("ref") == "main", f"remediation PR base: {pull.get('base')}"
    _assert_remediation_body(s, pull, definition, _blob_url(s.org, s.repo, "main", path))
    assert _pr_files(s, repo, number) == {STRICT_FILE: "added", LAX_FILE: "added"}, "remediation PR files"
    assert s.oracle.file_content(repo, STRICT_FILE, ref=branch) == expected, "strict file not rendered as expected"
    assert s.oracle.file_content(repo, LAX_FILE, ref=branch) == f"lax file of {repo}\n", "lax file not rendered"

    row = bp.wait_status(definition.id, repo, "remediation_prepared")
    assert row.get("remediation_pr") == number, f"status row of {repo}: {row}"
    assert set(bp.statuses(definition.id)) == {repo}, "repositories outside the selector got a status"
    remediations = _remediation_ids(bp.remediations(blueprint_id=definition.id))
    assert remediations == {(s.org, repo, definition.id, number)}, f"/api/blueprints/remediations: {remediations}"

    # a changed definition forces a recheck: the strict file is rewritten, the non-strict one keeps the maintainer edit
    edit = MAINTAINER_EDIT.format(repo=repo)
    mutator.commit_files(repo, branch, {STRICT_FILE: edit, LAX_FILE: edit}, f"otterdog-e2e {s.run_ctx.run_id}: edit")
    changed = dataclasses.replace(definition, description=s.describe("required_file blueprint, changed"))
    bp.add_blueprint(changed)
    fetch = _push_fetch(s, bp, relay)  # exactly one fetch: it sets the recheck flag of the changed definition
    assert fetch.get("status") == "finished", f"{FETCH_BLUEPRINTS} of the changed definition failed (SUT): {fetch}"
    task = bp.wait_evaluation(changed, repo, after=bp.check())
    assert task.get("status") == "finished", f"recheck of {repo} failed (SUT): {task}"
    s.reaction(
        lambda: s.oracle.file_content(repo, STRICT_FILE, ref=branch),
        until=lambda text: text == expected,
        what=f"strict {STRICT_FILE} rewritten in {branch}",
        timeout=STATUS_TIMEOUT,
    )
    assert s.oracle.file_content(repo, LAX_FILE, ref=branch) == edit, "the non-strict file lost the maintainer edit"
    numbers = [int(p["number"]) for p in bp.remediation_prs(repo, definition.id)]
    assert numbers == [number], f"the recheck opened another remediation PR: {numbers}"
    assert bp.wait_status(definition.id, repo, "remediation_prepared").get("remediation_pr") == number

    merged_at = bp.now()
    bp.merge_remediation_pr(repo, number)
    _after_merge(s, bp, changed, repo, number, merged_at)
    assert not bp.remediations(blueprint_id=definition.id), "a merged remediation is still listed as open"
    assert s.oracle.file_content(repo, STRICT_FILE, ref="main") == expected, f"{STRICT_FILE} not merged to main"
    s.quiesce()

    # a push to the default branch touching a required file re-evaluates the repository without /internal/check
    removed_at = bp.now()
    mutator.commit_files(repo, "main", {STRICT_FILE: None}, f"otterdog-e2e {s.run_ctx.run_id}: remove {STRICT_FILE}")
    task = _wait_task(s, CHECK_FILES_TASK, repo, after=removed_at)
    assert task.get("status") == "finished", f"push-triggered {CHECK_FILES_TASK} failed (SUT): {task}"
    renewed = bp.wait_remediation_pr(repo, definition)
    assert int(renewed["number"]) != number, "the push did not lead to a new remediation PR"
    assert _pr_files(s, repo, int(renewed["number"])) == {STRICT_FILE: "added"}, "new remediation PR files"
    row = bp.wait_status(definition.id, repo, "remediation_prepared")
    assert row.get("remediation_pr") == int(renewed["number"]), f"status after the push: {row}"


@pytest.mark.scenario("W-BP-DISMISS", priority="P2")
@pytest.mark.tags("webapp", "repo")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_closed_remediation_dismisses_the_blueprint(
    request: pytest.FixtureRequest, webapp_scenario: WebappScenario, blueprints: BlueprintHelper
) -> None:
    """Close -> dismissed (comment, branch deleted by the webapp, /api/blueprints/dismissed); a check opens no new PR;
    reopen -> reinstated; after a second close and a lost status (definition removed and re-added) the closed PR on
    GitHub restores the dismissal instead of a new PR (otterdog#766)."""
    s, bp = webapp_scenario, blueprints
    s.xfail_unless_includes(
        request,
        FIX_766,
        error=DismissalLostError,
        reason="the webapp under test predates otterdog#766 (16f7f32): a lost dismissal recreates the remediation PR",
        strict=True,  # merged upstream: every later version descends from 16f7f32
    )
    repo = s.run_repo("a")
    s.declare_live({repo: s.describe("dismissal target")})
    definition = BlueprintDefinition.required_file(
        bp.blueprint_id(s.slug),
        files=[RequiredFile("E2E_DISMISS.md", "dismiss me in {{repo_name}}\n")],
        name_pattern=repo,
        name=f"e2e {s.run_ctx.run_id} dismissal",
    )
    bp.add_blueprint(definition)
    bp.reload()
    _wait_stored(s, [repo])
    bp.wait_evaluation(definition, repo, after=bp.check())
    pull = bp.wait_remediation_pr(repo, definition)
    number, branch = int(pull["number"]), definition.remediation_branch
    assert _wait_github(
        s, lambda: s.oracle.branch_sha(repo, branch), until=bool, what=f"remediation branch {branch} exists"
    )

    closed_at = bp.now()
    bp.close_remediation_pr(repo, number)
    task = _wait_task(s, UPDATE_STATUS_TASK, repo, after=closed_at, pull_request=number)
    assert task.get("status") == "finished", f"{UPDATE_STATUS_TASK} of closed PR #{number} failed (SUT): {task}"
    row = bp.wait_status(definition.id, repo, "dismissed")
    assert row.get("remediation_pr") == number, f"dismissed status row: {row}"
    comments = s.reaction(
        lambda: _bot_comments(s, repo, number, DISMISSAL_MARKER),
        until=bool,
        what=f"blueprint-dismissal comment on {repo}#{number}",
        timeout=STATUS_TIMEOUT,
    )
    first_dismissal = comments[0]
    body = first_dismissal.get("body") or ""
    assert comment_contains(body, f"The blueprint `{definition.id}` {DISMISSAL_TEXT}"), f"dismissal comment: {body!r}"
    s.reaction(
        lambda: s.oracle.branch_sha(repo, branch),
        until=lambda sha: sha is None,
        what=f"the webapp deletes {branch} of the closed PR",
        timeout=STATUS_TIMEOUT,
    )
    assert _remediation_ids(bp.dismissed(blueprint_id=definition.id)) == {(s.org, repo, definition.id, number)}
    assert not bp.remediations(blueprint_id=definition.id), "a dismissed blueprint is still listed as remediation"

    checked = bp.check()
    s.quiesce()
    assert not _tasks_after(s, CHECK_FILES_TASK, repo, checked), "a dismissed blueprint was evaluated again (SUT)"
    numbers = [int(p["number"]) for p in bp.remediation_prs(repo, definition.id)]
    assert numbers == [number], f"a check after the dismissal opened another remediation PR: {numbers}"
    assert bp.wait_status(definition.id, repo, "dismissed").get("remediation_pr") == number

    reopened_at = bp.now()
    bp.reopen_remediation_pr(repo, number)
    task = _wait_task(s, UPDATE_STATUS_TASK, repo, after=reopened_at, pull_request=number)
    assert task.get("status") == "finished", f"{UPDATE_STATUS_TASK} of reopened PR #{number} failed (SUT): {task}"
    row = bp.wait_status(definition.id, repo, "remediation_prepared")
    assert row.get("remediation_pr") == number, f"reinstated status row: {row}"
    assert _remediation_ids(bp.remediations(blueprint_id=definition.id)) == {(s.org, repo, definition.id, number)}
    assert not bp.dismissed(blueprint_id=definition.id), "a reinstated blueprint is still listed as dismissed"

    closed_again = bp.now()
    bp.close_remediation_pr(repo, number)
    _wait_task(s, UPDATE_STATUS_TASK, repo, after=closed_again, pull_request=number)
    bp.wait_status(definition.id, repo, "dismissed")
    s.reaction(
        lambda: _bot_comments(s, repo, number, DISMISSAL_MARKER),
        until=lambda found: len(found) >= 2,
        what=f"second blueprint-dismissal comment on {repo}#{number}",
        timeout=STATUS_TIMEOUT,
    )
    s.reaction(
        lambda: next(
            (c for c in s.oracle.pr_comments(repo, number) if c.get("id") == first_dismissal.get("id")), {}
        ).get("is_minimized"),
        until=bool,
        what=f"the first dismissal comment of {repo}#{number} minimized as outdated",
        timeout=STATUS_TIMEOUT,
    )

    # the stored status gets lost: the closed PR on GitHub must restore the dismissal (otterdog#766)
    bp.remove_blueprint(definition)
    bp.reload(tasks=(FETCH_BLUEPRINTS,))
    assert s.api.blueprint_statuses(bp.project_name(), definition.id) is None, f"{definition.id} still loaded"
    assert not bp.dismissed(blueprint_id=definition.id), "status rows of a removed blueprint survived"
    bp.add_blueprint(definition)
    bp.reload(tasks=(FETCH_BLUEPRINTS,))
    task = bp.wait_evaluation(definition, repo, after=bp.check())
    row = bp.wait_status(definition.id, repo, ("dismissed", "remediation_prepared"))
    open_prs = [int(p["number"]) for p in bp.remediation_prs(repo, definition.id, state="open")]
    if row.get("status") != "dismissed" or open_prs:
        raise DismissalLostError(
            f"after the status loss {repo} got {row} and open remediation PRs {open_prs} instead of the dismissal of "
            f"closed PR #{number}"
        )
    assert row.get("remediation_pr") == number, f"restored dismissal does not name PR #{number}: {row}"
    assert task.get("status") == "finished", f"{CHECK_FILES_TASK} restoring the dismissal failed: {task}"


# --- pin_workflow ---------------------------------------------------------------------------------------------------
@pytest.mark.scenario("W-BP-PIN", priority="P2")
@pytest.mark.tags("webapp", "workflows")
@pytest.mark.known_bug("KB-073")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
@pytest.mark.xfail(
    raises=DockerActionPinningError,
    strict=False,
    reason="KB-073: pin_workflow skips a workflow that references a docker:// action",
)
def test_pin_workflow_remediation(webapp_scenario: WebappScenario, blueprints: BlueprintHelper) -> None:
    """The remediation PR pins ``actions/checkout@v4`` to its tag's commit and keeps the other references; merging it
    gives success. Last (scoped xfail): a workflow with a docker:// step must get its checkout pinned too."""
    s, bp = webapp_scenario, blueprints
    repo = s.run_repo("a")
    s.declare_live({repo: s.describe("pin_workflow target")})
    run = s.run_ctx.run_id
    plain = bp.add_workflow(repo, "pin", _data("unpinned-workflow.yml", run=run, name=s.run_ctx.name("pin")))
    docker = bp.add_workflow(
        repo, "pin-docker", _data("docker-action-workflow.yml", run=run, name=s.run_ctx.name("pin-docker"))
    )
    for workflow in (plain, docker):
        _wait_github(
            s,
            lambda workflow=workflow: s.oracle.workflow(repo, Path(workflow).name),
            until=lambda found: found is not None,
            what=f"GitHub lists the workflow {workflow} of {repo}",
        )
    definition = BlueprintDefinition.pin_workflow(
        bp.blueprint_id(s.slug), name_pattern=repo, name=f"e2e {run} pin workflows"
    )
    path = bp.add_blueprint(definition)
    bp.reload()
    _wait_stored(s, [repo])
    task = bp.wait_evaluation(definition, repo, after=bp.check())
    assert task.get("status") == "finished", f"{definition.task_type} of {repo} failed (SUT): {task}"
    pull = bp.wait_remediation_pr(repo, definition)
    number, branch = int(pull["number"]), definition.remediation_branch
    assert pull.get("title") == definition.pr_title, f"remediation PR title: {pull.get('title')!r}"
    _assert_remediation_body(s, pull, definition, _blob_url(s.org, s.repo, "main", path))

    original = s.oracle.file_content(repo, plain, ref="main") or ""
    pinned = s.oracle.file_content(repo, plain, ref=branch) or ""
    before, after = original.splitlines(), pinned.splitlines()
    assert len(before) == len(after), f"pinning changed the line count of {plain}:\n{pinned}"
    changed = [(old, new) for old, new in zip(before, after, strict=True) if old != new]
    assert len(changed) == 1 and changed[0][0] == CHECKOUT_LINE, f"lines changed in {plain}: {changed}"
    match = PINNED_CHECKOUT_RE.match(changed[0][1])
    assert match, f"checkout line not pinned to '<sha> # <v4 tag>': {changed[0][1]!r}"
    sha, tag = match.group(2), match.group(3)
    commit = s.oracle.http.get(f"/repos/actions/checkout/commits/{urllib.parse.quote(tag, safe='')}") or {}
    assert commit.get("sha") == sha, f"actions/checkout {tag} is commit {commit.get('sha')}, the PR pins {sha}"
    docker_pinned = s.oracle.file_content(repo, docker, ref=branch)
    bp.wait_status(definition.id, repo, "remediation_prepared")

    merged_at = bp.now()
    bp.merge_remediation_pr(repo, number)
    _after_merge(s, bp, definition, repo, number, merged_at)
    assert s.oracle.file_content(repo, plain, ref="main") == pinned, f"pinned {plain} not merged to main"

    s.write_evidence({"plain": pinned, "docker": docker_pinned, "pr": number, "tag": tag})
    docker_lines = (docker_pinned or "").splitlines()
    if docker_pinned is None or not any(PINNED_CHECKOUT_RE.match(line) for line in docker_lines):
        raise DockerActionPinningError(f"{docker} is not pinned by remediation PR #{number} (a docker:// step)")
    assert "      - uses: docker://alpine:3.20" in docker_lines, f"the docker:// reference was changed: {docker_pinned}"


# --- append_configuration -------------------------------------------------------------------------------------------
def _team_slug(name: str) -> str:
    """GitHub slug of a team name (python-slugify of otterdog's reviewers for the names the harness uses)."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


@pytest.mark.scenario("W-BP-APPEND", priority="P2")
@pytest.mark.tags("webapp", "repo", "teams")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_append_configuration_remediation(webapp_scenario: WebappScenario, blueprints: BlueprintHelper) -> None:
    """A config PR appends the rendered snippet to otterdog/<org>.jsonnet and requests the approval team; the webapp
    validates it; merging applies the new repository and the blueprint then reports success."""
    s, bp = webapp_scenario, blueprints
    added = s.run_repo("added")
    snippet = (
        "{ _repositories+: [ orgs.newRepo('" + added + "') "
        "{ description: 'appended by blueprint {{blueprint_id}} for {{github_id}}' } ] }"
    )
    definition = BlueprintDefinition.append_configuration(
        bp.blueprint_id(s.slug),
        condition=f'$count($.repositories[name = "{added}"]) = 0',
        content=snippet,
        reviewers=[s.target.approval_team],
        name=f"e2e {s.run_ctx.run_id} append configuration",
    )
    bp.add_blueprint(definition)
    bp.reload()
    task = bp.wait_evaluation(definition, s.repo, after=bp.check())
    assert task.get("status") == "finished", f"{definition.task_type} of {s.repo} failed (SUT): {task}"
    pull = bp.wait_remediation_pr(s.repo, definition)
    number, branch = int(pull["number"]), definition.remediation_branch
    assert pull.get("title") == definition.pr_title, f"remediation PR title: {pull.get('title')!r}"
    description = f"appended by blueprint {definition.id} for {s.org}"
    rendered = snippet.replace("{{blueprint_id}}", definition.id).replace("{{github_id}}", s.org)
    head = s.oracle.file_content(s.repo, s.flow.config_path, ref=branch)
    assert head == s.baseline_text().rstrip() + " + " + rendered, f"patched configuration of PR #{number}:\n{head}"
    org, repo = urllib.parse.quote(s.org, safe=""), urllib.parse.quote(s.repo, safe="")
    requested = s.oracle.http.get(f"/repos/{org}/{repo}/pulls/{number}/requested_reviewers") or {}
    teams = {str(team.get("slug")) for team in requested.get("teams") or []}
    assert _team_slug(s.target.approval_team) in teams, f"review not requested from the approval team: {requested}"
    assert bp.wait_status(definition.id, s.repo, "remediation_prepared").get("remediation_pr") == number

    pr = s.flow.adopt_pr(number)  # its validation may have started before the adoption: comments are read directly
    s.wait_validation(pr)
    validations = s.reaction(
        lambda: s.flow.bot_comments(pr, marker="validate"),
        until=bool,
        what=f"validate comment on remediation PR #{number}",
        timeout=STATUS_TIMEOUT,
    )
    body = validations[-1].get("body") or ""
    assert comment_contains(body, added), f"the validation of PR #{number} does not add {added}:\n{body[:2000]}"
    merged_at = bp.now()
    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    applied = s.wait_applied(pr)
    assert comment_contains(applied.get("body") or "", added), f"the apply comment does not name {added}"
    created = s.wait_repo(added)
    assert created.get("description") == description, f"{added} on GitHub: {created.get('description')!r}"
    _wait_stored(s, [added])  # a check before the stored configuration declares it would remediate again
    _after_merge(s, bp, definition, s.repo, number, merged_at)


# --- scorecard_integration ------------------------------------------------------------------------------------------
@pytest.mark.scenario("W-BP-SCORECARD", priority="P2")
@pytest.mark.tags("webapp", "workflows")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_scorecard_integration_remediation(webapp_scenario: WebappScenario, blueprints: BlueprintHelper) -> None:
    """The remediation PR adds the rendered scorecard workflow; merging gives success; the next check syncs the
    scorecard result (none is stored for a repository that never published one)."""
    s, bp = webapp_scenario, blueprints
    _require_rechecks(s)
    repo = s.run_repo("a")
    s.declare_live({repo: s.describe("scorecard target")})
    content = scorecard_workflow(s.run_ctx.run_id) + "# added to {{repo_name}} by blueprint {{blueprint_id}}\n"
    definition = BlueprintDefinition.scorecard_integration(
        bp.blueprint_id(s.slug), workflow_content=content, name_pattern=repo, name=f"e2e {s.run_ctx.run_id} scorecard"
    )
    path = bp.add_blueprint(definition)
    bp.reload()
    _wait_stored(s, [repo])
    task = bp.wait_evaluation(definition, repo, after=bp.check())
    assert task.get("status") == "finished", f"{definition.task_type} of {repo} failed (SUT): {task}"
    pull = bp.wait_remediation_pr(repo, definition)
    number, branch = int(pull["number"]), definition.remediation_branch
    assert pull.get("title") == definition.pr_title, f"remediation PR title: {pull.get('title')!r}"
    _assert_remediation_body(s, pull, definition, _blob_url(s.org, s.repo, "main", path))
    assert _pr_files(s, repo, number) == {SCORECARD_WORKFLOW: "added"}, "remediation PR files"
    rendered = content.replace("{{repo_name}}", repo).replace("{{blueprint_id}}", definition.id)
    assert s.oracle.file_content(repo, SCORECARD_WORKFLOW, ref=branch) == rendered, "scorecard workflow not rendered"
    bp.wait_status(definition.id, repo, "remediation_prepared")

    merged_at = bp.now()
    bp.merge_remediation_pr(repo, number)
    _wait_github(
        s,
        lambda: s.oracle.workflow(repo, Path(SCORECARD_WORKFLOW).name),
        until=lambda found: found is not None,
        what=f"GitHub lists {SCORECARD_WORKFLOW} of {repo}",
    )
    _after_merge(s, bp, definition, repo, number, merged_at)

    synced = bp.check()
    sync = _wait_task(s, SYNC_SCORECARD_TASK, repo, after=synced)
    assert sync.get("status") == "finished", (
        f"{SYNC_SCORECARD_TASK} of {repo} failed (is api.securityscorecards.dev reachable from the webapp?): {sync}"
    )
    assert s.api.scorecard_results(org_id=s.org, repo_name=repo) == [], f"scorecard result stored for {repo}"
    page = s.api.get(f"/projects/{urllib.parse.quote(bp.project_name(), safe='')}/repos/{repo}").text
    viewer = f"scorecard.dev/viewer/?uri=github.com/{s.org}/{repo}"
    assert viewer not in page, f"the repository page of {repo} links a scorecard result that was never published"
