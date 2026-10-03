"""Policies of the webapp (coverage area ``policies``): definitions, macos_large_runners and dependency_track_upload.

Facts verified in otterdog main 9bdeb75 (identical in v1.6.1):

* definitions: global ``policies/*.yml`` of the configs repo (one per type, read by /internal/init and by the push
  handler of the org config repo) and org ``otterdog/policies/*.yml`` of the config repo, fetched by FetchPoliciesTask
  on /internal/init and on a push to config repo main touching that directory; an org policy is merged over the
  global one of its type (Policy.merge, policies/__init__.py:42-55): path from the org file, name and description from
  the org file when it sets them, macos ``allowed`` and dependency-track ``workflow_filter`` from the org config, the
  ``artifact_name`` always from the global one (dependency_track_upload.py:235-238). FetchPoliciesTask only catches
  ValueError/RuntimeError (tasks/fetch_policies.py:70-85): a file without ``type`` or ``config`` (KeyError) fails the
  whole task (W-POL-LOAD-MALFORMED). The project page /projects/<project> lists the org's policies (tab
  ``policy-<n>`` named by the type: name, Reference link, config, the org's counters);
* macos_large_runners: a ``workflow_job`` ``queued`` delivery is evaluated inside the webhook handler
  (webhook/__init__.py:351-385): jobs whose labels start with ``macos`` and end with ``large`` are cancelled through
  the API unless ``allowed``; counters total_workflow_jobs (every queued job), permitted_on_restricted_runners and
  cancelled_on_restricted_runners are summed over the orgs on /admin/policies;
* dependency_track_upload: a ``workflow_run`` ``completed`` delivery with conclusion success whose referenced
  workflows match ``workflow_filter`` (re.search on the path) schedules UploadSBOMTask, which downloads the
  ``artifact_name`` artifact of the run and PUTs ``{projectName, projectVersion, parentUUID, autoCreate: true, bom:
  base64(bom.json)}`` (metadata.json gives the project) with X-Api-Key to DEPENDENCY_TRACK_URL/api/v1/bom; any answer
  but 200 fails the task (tasks/policies/upload_sbom.py:86-110).

W-POL-LOAD: global policies load on init, org policies on push and merge over them, removing the org file restores the
global values.
W-POL-LOAD-MALFORMED (KB-069): a policy file without ``type`` must not keep the valid policies from loading
(non-strict xfail scoped to PolicyLoadingError).
W-POL-MACOS: a job on macos-latest-large is cancelled by the App while the policy disallows it and only counted while
it allows it (the harness cancels it then); never dispatched where larger runners exist (they would bill).
W-POL-SBOM: a successful run calling the reusable SBOM workflow uploads its SBOM to the Dependency-Track mock; with a
workflow_filter that does not match nothing is uploaded; an upload answered 500 fails UploadSBOMTask.

Definitions, workflow runs and run repositories are removed by the ``blueprints`` fixture and the webapp_case teardown.
"""

from __future__ import annotations

import json
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
import yaml

from otterdog_e2e import waiting
from otterdog_e2e.blueprints import GLOBAL, POLICY, PolicyDefinition
from otterdog_e2e.config_repo import DeliveryTimeoutError, ReactionTimeoutError, check_forwarded
from otterdog_e2e.webapp.api import HtmlNode, floor_to_millis, parse_html, parse_timestamp

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.blueprints import BlueprintHelper
    from otterdog_e2e.webapp.stack import DtrackMock
    from otterdog_e2e.webhooks.relay import DeliveryRelay, RelayedDelivery

pytestmark = [pytest.mark.webapp]

DATA_DIR = Path(__file__).resolve().parent / "data" / "policies"
MACOS = "macos_large_runners"
SBOM = "dependency_track_upload"
FETCH_POLICIES = "FetchPoliciesTask"
UPLOAD_TASK = "UploadSBOMTask"
TOTAL, PERMITTED, CANCELLED = (
    "total_workflow_jobs",
    "permitted_on_restricted_runners",
    "cancelled_on_restricted_runners",
)
FINAL = ("finished", "failed")
DUMMY_TOKEN_PREFIX = "e2e-dummy"  # DEPENDENCY_TRACK_TOKEN of the compose stack (resources/compose.e2e.yaml)
DEFAULT_PARENT = "00000000-0000-0000-0000-000000000000"  # parent-project default of blueprints.sbom_store_workflow
EXPECTED_BOM = {"bomFormat": "CycloneDX", "specVersion": "1.5", "version": 1, "components": []}
CLOCK_SKEW = timedelta(seconds=60)
# budgets (seconds)
DELIVERY_TIMEOUT = 300.0
LOAD_TIMEOUT = 240.0
COUNTER_TIMEOUT = 180.0
RUN_TIMEOUT = 900.0  # runner pickup + the SBOM job (GitHub-hosted)
UPLOAD_TIMEOUT = 300.0
LONG_TIMEOUT = 2700


class PolicyLoadingError(AssertionError):
    """One malformed policy file kept the valid policies of the org from loading (W-POL-LOAD-MALFORMED, KB-069)."""


# --- helpers --------------------------------------------------------------------------------------------------------
def _data(file_name: str, /, **values: str) -> str:
    """tests/webapp/data/policies/<name> with its ``@KEY@`` placeholders replaced."""
    text = (DATA_DIR / file_name).read_text(encoding="utf-8")
    for key, value in values.items():
        text = text.replace(f"@{key.upper()}@", value)
    leftover = re.findall(r"@[A-Z]+@", text)
    assert not leftover, f"unreplaced placeholders {leftover} in {file_name}"
    return text


def _skip_if_foreign_global(bp: BlueprintHelper, *types: str) -> None:
    """Skip when the configs repo holds a global policy of ``types`` that this test did not write (another owner's, or
    a leftover of an earlier test of this run): org policies merge over it, so its values (the dependency-track
    artifact name above all) would leak into this test."""
    for path, text in bp.listing(POLICY, GLOBAL).items():
        if (bp.configs_repo, path) in bp.written:
            continue
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError:
            continue
        if isinstance(document, dict) and document.get("type") in types:
            pytest.skip(f"{bp.configs_repo}/{path} defines a foreign global {document.get('type')} policy")


def _blob_url(org: str, repo: str, path: str) -> str:
    """URL of a definition file as otterdog records it (global paths always name main: utils.py:255)."""
    return f"https://github.com/{org}/{repo}/blob/main/{path}"


def _project_page(s: WebappScenario, bp: BlueprintHelper) -> str:
    """HTML of /projects/<project> (rendered from the webapp database)."""
    return s.api.get(f"/projects/{urllib.parse.quote(bp.project_name(), safe='')}").text


def _card(pane: HtmlNode | None) -> dict[str, str] | None:
    """name (first card title), path (the Reference link) and config text of a policy pane."""
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


def _policy_cards(page: str) -> dict[str, dict[str, str]]:
    """{policy type: card} of the project page (tabs ``policy-<n>-tab`` named by the type)."""
    root = parse_html(page)
    cards: dict[str, dict[str, str]] = {}
    for link in root.iter("a"):
        match = re.fullmatch(r"(policy-\d+)-tab", link.attrs.get("id", ""))
        card = _card(root.find_id(match.group(1))) if match else None
        if card is not None:
            cards[link.text()] = card
    return cards


def _config(text: str) -> dict[str, Any] | None:
    """The config of a policy card as a dict: otterdog's PrettyFormatter prints repr() keys and json values
    (``{ 'allowed' : true }``); None when the text is not of that form."""
    try:
        value = json.loads(re.sub(r"'((?:[^'\\]|\\.)*)'\s*:", r'"\1":', text))
    except ValueError:
        return None
    return value if isinstance(value, dict) else None


def _wait_cards(
    s: WebappScenario, bp: BlueprintHelper, *, until: Any, what: str, timeout: float = LOAD_TIMEOUT
) -> dict[str, dict[str, str]]:
    """The policy cards of the project page once ``until(cards)`` holds (ReactionTimeoutError, SUT)."""
    cards: dict[str, dict[str, str]] = s.reaction(
        lambda: _policy_cards(_project_page(s, bp)), until=until, what=what, timeout=timeout
    )
    return cards


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
    """After committing org policies: the push delivery of config repo main and the FetchPoliciesTask it scheduled."""
    pushed = bp.now()
    _wait_push(relay, s.repo, s.flow.main_sha(), after=pushed)
    return bp.wait_fetch(after=pushed, tasks=(FETCH_POLICIES,))[FETCH_POLICIES]


def _tasks_after(s: WebappScenario, type_: str, repo: str, after: datetime) -> list[dict[str, Any]]:
    """Tasks of ``type_`` for ``repo`` created after ``after`` (any status), newest first."""
    floor = floor_to_millis(after)
    return [
        task
        for task in s.api.tasks(org_id=s.org, type_=type_, repo_name=repo)
        if (created := parse_timestamp(task.get("created_at"))) is not None and created >= floor
    ]


def _wait_task(s: WebappScenario, type_: str, repo: str, *, after: datetime, timeout: float) -> dict[str, Any]:
    """The newest final ``type_`` task of ``repo`` created after ``after`` (ReactionTimeoutError, SUT)."""
    try:
        return s.api.wait_task(type_=type_, org_id=s.org, after=after, repo_name=repo, timeout=timeout)
    except waiting.WaitTimeoutError as exc:
        raise ReactionTimeoutError(f"webapp did not run {type_} for {repo} within {timeout:g} s (SUT): {exc}") from None


def _counter(counters: dict[str, int], name: str) -> int:
    """A policy counter (0 before the first event of the policy type)."""
    return int(counters.get(name, 0))


# --- definitions ----------------------------------------------------------------------------------------------------
@pytest.mark.scenario("W-POL-LOAD", priority="P2")
@pytest.mark.tags("webapp", "webhooks-app")
def test_policy_definitions_are_loaded_and_merged(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper, relay: DeliveryRelay
) -> None:
    """Global policies load on /internal/init; org policies pushed to config repo main merge over them (path, name,
    allowed and workflow_filter from the org, description and artifact_name kept from the global one); removing the
    org macos policy restores the global values."""
    s, bp = webapp_scenario, blueprints
    _skip_if_foreign_global(bp, MACOS, SBOM)
    run = s.run_ctx.run_id
    global_description = f"e2e {run} global macos description"
    global_macos = PolicyDefinition.macos_large_runners(
        allowed=False, name=f"e2e {run} global macos", description=global_description
    )
    global_sbom = PolicyDefinition.dependency_track_upload(
        artifact_name=s.run_ctx.name("global-sbom"), workflow_filter=s.run_ctx.name("global-filter")
    )
    global_macos_path = bp.add_policy(global_macos, scope=GLOBAL)
    global_sbom_path = bp.add_policy(global_sbom, scope=GLOBAL)
    fetch = bp.reload(tasks=(FETCH_POLICIES,))[FETCH_POLICIES]
    assert fetch.get("status") == "finished", f"{FETCH_POLICIES} after /internal/init failed (SUT): {fetch}"
    page = _project_page(s, bp)
    cards = _policy_cards(page)
    macos, sbom = cards.get(MACOS), cards.get(SBOM)
    assert macos is not None and sbom is not None, f"global policies missing from the project page: {sorted(cards)}"
    assert macos["name"] == global_macos.name, f"global macos card: {macos}"
    assert macos["path"] == _blob_url(s.org, bp.configs_repo, global_macos_path), f"global macos card: {macos}"
    assert _config(macos["config"]) == {"allowed": False}, f"global macos config: {macos['config']!r}"
    assert global_description in page, "the global macos description is not shown"  # rendered by a script
    assert sbom["name"] == "Overview" and sbom["path"] == _blob_url(s.org, bp.configs_repo, global_sbom_path)
    assert _config(sbom["config"]) == dict(global_sbom.config), f"global dependency-track config: {sbom['config']!r}"

    org_macos = PolicyDefinition.macos_large_runners(allowed=True, name=f"e2e {run} org macos")
    org_sbom = PolicyDefinition.dependency_track_upload(
        artifact_name=s.run_ctx.name("org-sbom"), workflow_filter=s.run_ctx.name("org-filter"), name=f"e2e {run} org"
    )
    org_macos_path = bp.add_policy(org_macos)
    org_sbom_path = bp.add_policy(org_sbom)
    fetch = _push_fetch(s, bp, relay)
    assert fetch.get("status") == "finished", f"push-triggered {FETCH_POLICIES} failed (SUT): {fetch}"
    org_macos_url, org_sbom_url = _blob_url(s.org, s.repo, org_macos_path), _blob_url(s.org, s.repo, org_sbom_path)
    cards = _wait_cards(
        s,
        bp,
        until=lambda found: (
            (found.get(MACOS) or {}).get("path") == org_macos_url
            and (found.get(SBOM) or {}).get("path") == org_sbom_url
        ),
        what="org policies merged over the global ones",
    )
    page = _project_page(s, bp)
    macos, sbom = cards[MACOS], cards[SBOM]
    assert macos["name"] == org_macos.name, f"merged macos card: {macos}"
    assert _config(macos["config"]) == {"allowed": True}, f"the org 'allowed' does not win: {macos['config']!r}"
    assert global_description in page, "the merged policy lost the global description (the org sets none)"
    assert sbom["name"] == org_sbom.name, f"merged dependency-track card: {sbom}"
    expected = {
        "artifact_name": global_sbom.config["artifact_name"],
        "workflow_filter": org_sbom.config["workflow_filter"],
    }
    assert _config(sbom["config"]) == expected, f"merged dependency-track config: {sbom['config']!r}"

    bp.remove_policy(org_macos)
    _push_fetch(s, bp, relay)
    cards = _wait_cards(
        s,
        bp,
        until=lambda found: (
            (found.get(MACOS) or {}).get("path") == _blob_url(s.org, bp.configs_repo, global_macos_path)
        ),
        what="global macos policy back after the removal of the org one",
    )
    assert cards[MACOS]["name"] == global_macos.name and _config(cards[MACOS]["config"]) == {"allowed": False}
    assert cards[SBOM]["path"] == org_sbom_url, f"the org dependency-track policy was lost: {cards[SBOM]}"


@pytest.mark.scenario("W-POL-LOAD-MALFORMED", priority="P2")
@pytest.mark.tags("webapp")
@pytest.mark.known_bug("KB-069")
@pytest.mark.xfail(
    raises=PolicyLoadingError,
    strict=False,
    reason="KB-069: one unreadable definition file fails the whole FetchPoliciesTask",
)
def test_malformed_policy_does_not_block_the_others(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper
) -> None:
    """A policy file without ``type`` is skipped and the valid org policy next to it loads (the malformed file is
    committed first, so no fetch can load the valid one before it exists)."""
    s, bp = webapp_scenario, blueprints
    run = s.run_ctx.run_id
    bp.add_definition_text(POLICY, f"{s.slug}-untyped", _data("definition-without-type.yml", run=run))
    valid = PolicyDefinition.macos_large_runners(allowed=False, name=f"e2e {run} valid macos")
    path = bp.add_policy(valid)
    fetch = bp.reload(tasks=(FETCH_POLICIES,))[FETCH_POLICIES]
    card = _policy_cards(_project_page(s, bp)).get(MACOS)
    s.write_evidence({"fetch": fetch, "macos_card": card})
    if fetch.get("status") != "finished" or card is None or card["path"] != _blob_url(s.org, s.repo, path):
        raise PolicyLoadingError(
            f"a policy file without 'type' kept {path} from loading: {FETCH_POLICIES} {fetch.get('status')} "
            f"({str(fetch.get('log'))[:300]!r}), macos card {card}"
        )
    assert card["name"] == valid.name and _config(card["config"]) == {"allowed": False}, f"macos card: {card}"


# --- macos_large_runners --------------------------------------------------------------------------------------------
@pytest.mark.scenario("W-POL-MACOS", priority="P2")
@pytest.mark.tags("webapp", "workflows", "webhooks-app")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_macos_large_runner_jobs_are_cancelled_unless_allowed(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper
) -> None:
    """allowed false: the queued job is cancelled by the App (run cancelled, cancelled counter +1); allowed true: the
    job is only counted (permitted counter +1, the run still waits for a runner until the harness cancels it)."""
    s, bp = webapp_scenario, blueprints
    if bp.larger_runners:
        pytest.skip("the org has larger runners: a job on macos-latest-large would run and be billed")
    run = s.run_ctx.run_id
    repo = s.run_repo("a")
    s.declare_live({repo: s.describe("macOS larger runner jobs")})
    workflow = bp.add_large_runner_workflow(repo)
    bp.add_policy(PolicyDefinition.macos_large_runners(allowed=False, name=f"e2e {run} deny macos"))
    bp.reload(tasks=(FETCH_POLICIES,))
    card = _policy_cards(_project_page(s, bp)).get(MACOS)
    assert card is not None and _config(card["config"]) == {"allowed": False}, f"deny policy not loaded: {card}"

    before = bp.policy_status(MACOS)
    denied = bp.dispatch(repo, workflow)
    queued = bp.wait_workflow_delivery(
        "workflow_job", repo=repo, action="queued", run_id=denied.run_id, after=denied.after
    )
    run_id = denied.run_id or queued.run_id
    cancelled = bp.wait_run(
        repo, workflow, after=denied.after, run_id=run_id, until=lambda r: r.get("status") == "completed"
    )
    assert cancelled.get("conclusion") == "cancelled", f"run {run_id} on a disallowed larger runner: {cancelled}"
    counters = bp.wait_policy_counter(
        MACOS, CANCELLED, at_least=_counter(before, CANCELLED) + 1, timeout=COUNTER_TIMEOUT
    )
    assert _counter(counters, TOTAL) >= _counter(before, TOTAL) + 1, f"total_workflow_jobs not counted: {counters}"
    assert _counter(counters, PERMITTED) == _counter(before, PERMITTED), (
        f"a denied job counted as permitted: {counters}"
    )

    bp.add_policy(PolicyDefinition.macos_large_runners(allowed=True, name=f"e2e {run} allow macos"))
    bp.reload(tasks=(FETCH_POLICIES,))
    card = _policy_cards(_project_page(s, bp)).get(MACOS)
    assert card is not None and _config(card["config"]) == {"allowed": True}, f"allow policy not loaded: {card}"
    middle = bp.policy_status(MACOS)
    permitted = bp.dispatch(repo, workflow)
    queued = bp.wait_workflow_delivery(
        "workflow_job", repo=repo, action="queued", run_id=permitted.run_id, after=permitted.after
    )
    run_id = permitted.run_id or queued.run_id
    assert run_id is not None, "neither the dispatch nor the workflow_job delivery names the run"
    counters = bp.wait_policy_counter(
        MACOS, PERMITTED, at_least=_counter(middle, PERMITTED) + 1, timeout=COUNTER_TIMEOUT
    )
    assert _counter(counters, CANCELLED) == _counter(middle, CANCELLED), (
        f"an allowed job counted as cancelled: {counters}"
    )
    waiting_run = s.oracle.workflow_run(repo, run_id) or {}
    assert waiting_run.get("status") != "completed", f"the App cancelled an allowed larger-runner job: {waiting_run}"
    bp.cancel_run(repo, run_id)
    done = bp.wait_run(
        repo, workflow, after=permitted.after, run_id=run_id, until=lambda r: r.get("status") == "completed"
    )
    assert done.get("conclusion") == "cancelled", f"the harness could not cancel run {run_id}: {done}"


# --- dependency_track_upload ----------------------------------------------------------------------------------------
def _upload_of(project: str) -> Any:
    """Predicate of the mock's BOM uploads naming ``project``."""
    return lambda entry: ((entry.get("json") or {}).get("projectName")) == project


@pytest.mark.scenario("W-POL-SBOM", priority="P2")
@pytest.mark.tags("webapp", "workflows", "webhooks-app")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_sbom_upload_to_dependency_track(
    webapp_scenario: WebappScenario, blueprints: BlueprintHelper, relay: DeliveryRelay, dtrack_mock: DtrackMock
) -> None:
    """A matching successful run uploads {projectName, projectVersion, parentUUID, autoCreate, bom} with the API key;
    a non-matching workflow_filter uploads nothing; an upload answered 500 fails UploadSBOMTask."""
    s, bp = webapp_scenario, blueprints
    _skip_if_foreign_global(bp, SBOM)
    repo, project = s.run_repo("a"), s.run_ctx.name(f"{s.slug}-project")
    s.declare_live({repo: s.describe("SBOM upload")})
    sbom = bp.add_sbom_workflows(repo, artifact_name=s.run_ctx.name("sbom-data"), project_name=project)
    matching = PolicyDefinition.dependency_track_upload(
        artifact_name=sbom.artifact_name, workflow_filter=sbom.workflow_filter, name=f"e2e {s.run_ctx.run_id} sbom"
    )
    bp.add_policy(matching)
    fetch = _push_fetch(s, bp, relay)
    assert fetch.get("status") == "finished", f"{FETCH_POLICIES} failed (SUT): {fetch}"

    first = bp.dispatch(repo, sbom.caller)
    run = bp.wait_run(
        repo,
        sbom.caller,
        after=first.after,
        run_id=first.run_id,
        until=lambda r: r.get("status") == "completed",
        timeout=RUN_TIMEOUT,
    )
    assert run.get("conclusion") == "success", f"the SBOM workflow run failed (infra: GitHub Actions): {run}"
    bp.wait_workflow_delivery("workflow_run", repo=repo, action="completed", run_id=int(run["id"]))
    task = _wait_task(s, UPLOAD_TASK, repo, after=first.after, timeout=UPLOAD_TIMEOUT)
    assert task.get("status") == "finished", f"{UPLOAD_TASK} of run {run['id']} failed (SUT): {task}"
    try:
        uploads = dtrack_mock.wait_uploads(1, predicate=_upload_of(project), timeout=UPLOAD_TIMEOUT)
    except waiting.WaitTimeoutError:
        raise ReactionTimeoutError(f"no BOM upload for {project} reached the Dependency-Track mock (SUT)") from None
    upload = uploads[0]
    body, headers = upload.get("json") or {}, upload.get("headers") or {}
    assert upload.get("method") == "PUT" and upload.get("path") == "/api/v1/bom", f"upload request: {upload}"
    assert str(headers.get("X-Api-Key", "")).startswith(DUMMY_TOKEN_PREFIX), "the upload lacks the API key header"
    assert str(headers.get("Content-Type", "")).startswith("application/json"), f"upload headers: {headers}"
    assert body.get("projectVersion") == "1.0.0" and body.get("parentUUID") == DEFAULT_PARENT, f"upload body: {body}"
    assert body.get("autoCreate") is True, f"upload body: {body}"
    assert upload.get("bom") == EXPECTED_BOM, f"uploaded BOM: {upload.get('bom')} ({upload.get('bom_error')})"

    nomatch = re.escape(f".github/workflows/{s.run_ctx.name('not-the-store')}.yml")
    bp.add_policy(PolicyDefinition.dependency_track_upload(artifact_name=sbom.artifact_name, workflow_filter=nomatch))
    _push_fetch(s, bp, relay)
    dtrack_mock.clear()
    second = bp.dispatch(repo, sbom.caller)
    run = bp.wait_run(
        repo,
        sbom.caller,
        after=second.after,
        run_id=second.run_id,
        until=lambda r: r.get("status") == "completed",
        timeout=RUN_TIMEOUT,
    )
    assert run.get("conclusion") == "success", f"the SBOM workflow run failed (infra: GitHub Actions): {run}"
    bp.wait_workflow_delivery("workflow_run", repo=repo, action="completed", run_id=int(run["id"]))
    s.quiesce()  # the policy decides inside the delivery: a matching run would have scheduled its task by now
    assert not _tasks_after(s, UPLOAD_TASK, repo, second.after), "a run of a non-matching workflow was uploaded"
    assert not dtrack_mock.uploads(), f"the mock received uploads for a non-matching run: {dtrack_mock.uploads()}"

    bp.add_policy(matching)
    _push_fetch(s, bp, relay)
    dtrack_mock.set_response(500)
    third = bp.dispatch(repo, sbom.caller)
    run = bp.wait_run(
        repo,
        sbom.caller,
        after=third.after,
        run_id=third.run_id,
        until=lambda r: r.get("status") == "completed",
        timeout=RUN_TIMEOUT,
    )
    assert run.get("conclusion") == "success", f"the SBOM workflow run failed (infra: GitHub Actions): {run}"
    bp.wait_workflow_delivery("workflow_run", repo=repo, action="completed", run_id=int(run["id"]))
    task = _wait_task(s, UPLOAD_TASK, repo, after=third.after, timeout=UPLOAD_TIMEOUT)
    assert task.get("status") == "failed", f"{UPLOAD_TASK} succeeded although Dependency-Track answered 500: {task}"
    assert "failed to upload SBOM" in str(task.get("log")), f"{UPLOAD_TASK} log: {task.get('log')!r}"
    rejected = dtrack_mock.uploads()
    assert [entry.get("status") for entry in rejected] == [500], f"uploads answered by the mock: {rejected}"
