"""blueprints.py: definitions (YAML as otterdog reads them), guarded definition files, webapp triggers and status reads,
remediation PRs, workflows emitting workflow_job / workflow_run events, cleanup.

The definition documents were also loaded with otterdog main's own read_blueprint / read_policy (pydantic models) in
the webapp image of otterdog main 9bdeb75 (docker, no network) during development.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
import responses
import yaml

from otterdog_e2e import blueprints as bp
from otterdog_e2e.blueprints import (
    BlueprintDefinition,
    BlueprintError,
    BlueprintHelper,
    PolicyDefinition,
    RequiredFile,
)
from otterdog_e2e.config_repo import ConfigRepoFlow, DeliveryTimeoutError, ReactionTimeoutError
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import (
    FAKE_ORG,
    FakeGitHubHttp,
    FakeOracle,
    RecordingMutator,
    fake_sha,
    make_run_context,
)
from otterdog_e2e.waiting import WaitTimeoutError
from otterdog_e2e.webapp.api import WebappApi
from otterdog_e2e.webhooks.relay import RelayedDelivery

BASE = "http://127.0.0.1:5996"
RUN_CTX = make_run_context()
RUN = RUN_CTX.run_id
CONFIGS = "otterdog-e2e-configs"
CONFIG_REPO = RUN_CTX.name("config")
REPO = RUN_CTX.name("bp-a")
NOW = datetime(2026, 10, 3, 8, 0, tzinfo=UTC)
# fields of otterdog's models (otterdog/webapp/blueprints/*.py, policies/*.py) besides id/path/name/description
BLUEPRINT_FIELDS = {
    "required_file": {"repo_selector", "files"},
    "pin_workflow": {"repo_selector"},
    "append_configuration": {"condition", "content", "reviewers"},
    "scorecard_integration": {"repo_selector", "scorecard_action", "workflow_name", "workflow_content"},
}
POLICY_FIELDS = {"macos_large_runners": {"allowed"}, "dependency_track_upload": {"artifact_name", "workflow_filter"}}


class FakeTime:
    """Fake monotonic clock; hooks run on sleep."""

    def __init__(self) -> None:
        """t=0."""
        self.now = 0.0
        self.hooks: list[Callable[[], None]] = []

    def clock(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance; run the next hook."""
        self.now += seconds
        if self.hooks:
            self.hooks.pop(0)()


def world(
    *, larger_runners: bool = False, purgeable: Callable[[str], bool] | None = None, **kwargs: Any
) -> SimpleNamespace:
    """A helper on fake GitHub reads (oracle + its read-only http), a recording mutator and the webapp API."""
    oracle = FakeOracle()
    oracle.http = FakeGitHubHttp(read_only=True, strict=False)  # type: ignore[attr-defined]
    mutator = RecordingMutator(oracle=oracle)
    api = WebappApi(BASE)
    fake = FakeTime()
    api.sleep, api.clock = fake.sleep, fake.clock
    helper = BlueprintHelper(
        org=FAKE_ORG,
        configs_repo=CONFIGS,
        config_repo=CONFIG_REPO,
        run_ctx=RUN_CTX,
        oracle=oracle,  # type: ignore[arg-type]
        mutator=mutator,  # type: ignore[arg-type]
        api=api,
        larger_runners=larger_runners,
        purgeable=purgeable,
        **kwargs,
    )
    helper.sleep, helper.clock = fake.sleep, fake.clock
    helper.now = lambda: NOW
    return SimpleNamespace(helper=helper, oracle=oracle, http=oracle.http, mutator=mutator, api=api, time=fake)


def required_file(slug: str = "bp") -> BlueprintDefinition:
    """A required_file blueprint of this run."""
    return BlueprintDefinition.required_file(
        RUN_CTX.name(slug),
        files=[RequiredFile("E2E_BLUEPRINT.md", "repo={{repo_name}}\n", strict=True)],
        name_pattern=f"{RUN_CTX.prefix}-bp-.*",
        name="E2E required file",
    )


# --- definitions ---------------------------------------------------------------------------------------------------
def test_blueprint_documents_match_otterdogs_models() -> None:
    """id/type/name/description/config; the config keys are fields of the type's model (flattened by otterdog)."""
    definitions = [
        required_file(),
        BlueprintDefinition.pin_workflow(
            RUN_CTX.name("pin"), name_pattern=[f"{RUN_CTX.prefix}-a", f"{RUN_CTX.prefix}-b"]
        ),
        BlueprintDefinition.append_configuration(
            RUN_CTX.name("append"),
            condition=f'$count($.repositories[name = "{RUN_CTX.prefix}-dotgithub"]) = 0',
            content=f"{{\n  _repositories+:: [ orgs.newRepo('{RUN_CTX.prefix}-dotgithub') ],\n}}",
            reviewers=["{{project_name}}-project-leads"],
        ),
        BlueprintDefinition.scorecard_integration(
            RUN_CTX.name("sc"), workflow_content=bp.scorecard_workflow(RUN), name_pattern=".*", workflow_name="sc.yml"
        ),
    ]
    for definition in definitions:
        document = yaml.safe_load(definition.to_yaml())
        assert document == definition.to_document()
        assert document["id"] == definition.id and document["type"] == definition.type
        assert set(document["config"]) <= BLUEPRINT_FIELDS[definition.type], definition.type
        assert definition.remediation_branch == f"otterdog/blueprint/{definition.id}"
        assert definition.pr_title.startswith("chore(otterdog): ") and definition.id in definition.pr_title
        assert definition.task_type in bp.TASK_TYPES.values()
    rf = yaml.safe_load(definitions[0].to_yaml())
    assert rf["config"]["files"] == [{"path": "E2E_BLUEPRINT.md", "content": "repo={{repo_name}}\n", "strict": True}]
    assert (
        rf["config"]["repo_selector"] == {"name_pattern": f"{RUN_CTX.prefix}-bp-.*"}
        and rf["name"] == "E2E required file"
    )
    assert "description" not in rf
    assert yaml.safe_load(definitions[1].to_yaml())["config"]["repo_selector"]["name_pattern"] == [
        f"{RUN_CTX.prefix}-a",
        f"{RUN_CTX.prefix}-b",
    ]
    assert BlueprintDefinition.pin_workflow(RUN_CTX.name("all")).to_document()["config"] == {}


def test_blueprint_definition_refusals() -> None:
    """Unknown types, non-e2e ids and empty file lists are refused."""
    with pytest.raises(ValueError):
        BlueprintDefinition(RUN_CTX.name("x"), "nope")
    for bad_id in ("default-security-policy", f"{RUN_CTX.prefix}-a/b"):
        with pytest.raises(ValueError):
            BlueprintDefinition(bad_id, "pin_workflow")
    with pytest.raises(ValueError):
        BlueprintDefinition.required_file(RUN_CTX.name("x"), files=[])


def test_policy_documents_match_otterdogs_models() -> None:
    """type/name/description/config (config is required by read_policy)."""
    macos = PolicyDefinition.macos_large_runners(allowed=False, name="mac")
    dtrack = PolicyDefinition.dependency_track_upload(artifact_name="e2e-sbom", workflow_filter=r"store-sbom\.yml")
    for definition in (macos, dtrack):
        document = yaml.safe_load(definition.to_yaml())
        assert document["type"] == definition.type and set(document["config"]) == POLICY_FIELDS[definition.type]
    assert yaml.safe_load(macos.to_yaml()) == {
        "type": "macos_large_runners",
        "name": "mac",
        "config": {"allowed": False},
    }
    with pytest.raises(ValueError):
        PolicyDefinition("nope")
    with pytest.raises(re.error):
        PolicyDefinition.dependency_track_upload(artifact_name="a", workflow_filter="(")


# --- definition files ----------------------------------------------------------------------------------------------
def test_org_definitions_are_committed_to_the_org_config_repo() -> None:
    """add_blueprint / add_policy / add_definition_text: <dir>/e2e-<run>-<slug>.yml on the default branch."""
    w = world()
    w.oracle.set("default_branch", CONFIG_REPO, value="main")
    definition = required_file()
    path = w.helper.add_blueprint(definition)
    assert path == f"otterdog/blueprints/{definition.id}.yml"
    (commit,) = w.mutator.calls_to("commit_files")
    assert commit.args[:3] == (CONFIG_REPO, "main", {path: definition.to_yaml()})
    policy = w.helper.add_policy(PolicyDefinition.macos_large_runners(allowed=True))
    assert policy == f"otterdog/policies/{RUN_CTX.prefix}-macos-large-runners.yml"
    raw = w.helper.add_definition_text("blueprint", "broken", "id: x\n")
    assert raw == f"otterdog/blueprints/{RUN_CTX.prefix}-broken.yml"
    assert set(w.helper.written) == {(CONFIG_REPO, path), (CONFIG_REPO, policy), (CONFIG_REPO, raw)}
    with pytest.raises(BlueprintError, match="already defines"):
        w.helper.add_policy(PolicyDefinition.macos_large_runners(allowed=False), slug="other")
    w.helper.add_policy(PolicyDefinition.macos_large_runners(allowed=False))  # the same file may be rewritten


def test_definition_names_and_scopes_are_guarded() -> None:
    """Only names of this run; known kinds and scopes."""
    w = world()
    with pytest.raises(SafetyError):
        w.helper.definition_path("blueprint", "org", "e2e-t3c7z8b6-other-run")
    with pytest.raises(SafetyError):
        w.helper.definition_path("policy", "global", "macos")
    with pytest.raises(ValueError):
        w.helper.definition_path("theme", "org", RUN_CTX.name("x"))
    with pytest.raises(ValueError):
        w.helper.repo_for("enterprise")
    with pytest.raises(SafetyError):
        w.helper.add_blueprint(BlueprintDefinition("e2e-t3c7z8b6-foreign", "pin_workflow"))
    assert w.mutator.calls == []


def test_global_definitions_are_unique_per_type() -> None:
    """A global definition of the same type by someone else (or a finished run) is refused: the webapp keeps one."""
    w = world()
    listing = [
        {"type": "file", "path": "blueprints/default-security-policy.yml"},
        {"type": "file", "path": f"blueprints/{RUN_CTX.prefix}-mine.yml"},
        {"type": "dir", "path": "blueprints/sub"},
        {"type": "file", "path": "blueprints/README.md"},
    ]
    w.http.add("GET", f"/repos/{FAKE_ORG}/{CONFIGS}/contents/blueprints", json=listing, repeat=True)
    w.oracle.add_file(CONFIGS, "blueprints/default-security-policy.yml", "id: dsp\ntype: required_file\n", ref="main")
    w.oracle.add_file(CONFIGS, f"blueprints/{RUN_CTX.prefix}-mine.yml", "id: x\ntype: pin_workflow\n", ref="main")
    with pytest.raises(BlueprintError, match=r"default-security-policy\.yml already defines a global blueprint"):
        w.helper.add_blueprint(required_file(), scope="global")
    w.helper.add_blueprint(BlueprintDefinition.pin_workflow(RUN_CTX.name("pin")), scope="global")  # own file ignored
    (commit,) = w.mutator.calls_to("commit_files")
    assert commit.args[0] == CONFIGS and list(commit.args[2]) == [f"blueprints/{RUN_CTX.prefix}-pin.yml"]
    assert w.helper.listing("blueprint", "global") == {
        "blueprints/default-security-policy.yml": "id: dsp\ntype: required_file\n",
        f"blueprints/{RUN_CTX.prefix}-mine.yml": "id: x\ntype: pin_workflow\n",
    }


def test_remove_and_sweep_stale() -> None:
    """remove(): one deleting commit per repository; sweep_stale(): files of purgeable runs only."""
    w = world(purgeable=lambda run_id: run_id == "t3c7z8b6")
    w.helper.add_blueprint(required_file())
    w.helper.add_policy(PolicyDefinition.macos_large_runners(allowed=True), scope="global")
    w.mutator.calls.clear()
    removed = w.helper.remove()
    assert len(removed) == 2 and w.helper.written == {}
    commits = {call.args[0]: call.args[2] for call in w.mutator.calls_to("commit_files")}
    assert commits[CONFIG_REPO] == {f"otterdog/blueprints/{RUN_CTX.name('bp')}.yml": None}
    assert commits[CONFIGS] == {f"policies/{RUN_CTX.prefix}-macos-large-runners.yml": None}
    w.helper.add_policy(PolicyDefinition.macos_large_runners(allowed=False), scope="global")  # type freed by remove
    w.mutator.calls.clear()
    stale = [
        {"type": "file", "path": "policies/e2e-t3c7z8b6-macos.yml"},  # finished run
        {"type": "file", "path": "policies/e2e-t3c7z8c7-macos.yml"},  # active run: kept
        {"type": "file", "path": f"policies/{RUN_CTX.prefix}-macos-large-runners.yml"},  # this run: kept
        {"type": "file", "path": "policies/macos.yml"},  # not e2e: kept
    ]
    w.http.add("GET", f"/repos/{FAKE_ORG}/{CONFIGS}/contents/policies", json=stale, repeat=True)
    for entry in stale:
        w.oracle.add_file(CONFIGS, entry["path"], "type: macos_large_runners\nconfig: {allowed: false}\n", ref="main")
    assert w.helper.sweep_stale() == [f"{CONFIGS}/policies/e2e-t3c7z8b6-macos.yml"]
    (commit,) = w.mutator.calls_to("commit_files")
    assert commit.args[2] == {"policies/e2e-t3c7z8b6-macos.yml": None}
    assert world().helper.sweep_stale() == []  # without purgeable nothing is removed


# --- webapp triggers and reads -------------------------------------------------------------------------------------
def task(type_: str, status: str, created_at: str, repo: str = CONFIG_REPO) -> dict[str, Any]:
    """A /api/tasks row."""
    return {
        "type": type_,
        "org_id": FAKE_ORG,
        "repo_name": repo,
        "pull_request": 0,
        "status": status,
        "created_at": created_at,
    }


@responses.activate
def test_reload_waits_for_both_fetch_tasks() -> None:
    """reload(): /internal/init, then the newest Fetch{Blueprints,Policies}Task created after it, finished or failed."""
    w = world()
    responses.get(f"{BASE}/internal/init", json={})
    responses.get(
        f"{BASE}/api/tasks",
        json={
            "data": [
                task("FetchBlueprintsTask", "failed", "2026-10-03T08:00:01"),
                task("FetchBlueprintsTask", "finished", "2026-10-03T07:00:00"),
            ]
        },
    )
    responses.get(f"{BASE}/api/tasks", json={"data": [task("FetchPoliciesTask", "finished", "2026-10-03T08:00:02")]})
    found = w.helper.reload()
    assert found["FetchBlueprintsTask"]["status"] == "failed" and found["FetchPoliciesTask"]["status"] == "finished"
    assert responses.calls[0].request.url == f"{BASE}/internal/init"


@responses.activate
def test_reload_timeout_is_a_sut_failure() -> None:
    """No fetch task after the init: ReactionTimeoutError."""
    w = world()
    responses.get(f"{BASE}/internal/init", json={})
    responses.get(f"{BASE}/api/tasks", json={"data": []})
    with pytest.raises(ReactionTimeoutError, match="FetchBlueprintsTask"):
        w.helper.reload(timeout=10)


@responses.activate
def test_check_and_wait_evaluation() -> None:
    """check(limit) calls /internal/check/<limit>; wait_evaluation waits for the type's task of the repository."""
    w = world()
    responses.get(f"{BASE}/internal/check/1", json={})
    assert w.helper.check(1) == NOW
    responses.get(f"{BASE}/api/tasks", json={"data": [task("CheckFilesTask", "finished", "2026-10-03T08:00:03", REPO)]})
    found = w.helper.wait_evaluation(required_file(), REPO, after=NOW)
    assert found["type"] == "CheckFilesTask"
    params = responses.calls[-1].request.params
    assert params["type"] == "^CheckFilesTask$" and params["repo_name"] == "^" + re.escape(REPO) + "$"
    responses.replace(responses.GET, f"{BASE}/api/tasks", json={"data": []})
    with pytest.raises(ReactionTimeoutError, match="did not evaluate"):
        w.helper.wait_evaluation(required_file(), REPO, after=NOW, timeout=5)


PROJECT_PAGE = """<html><body><div id="blueprint-{id}" role="tabpanel"><table><thead><tr><th>Repository</th>
<th>Updated At</th><th>Status</th><th>Remediation PR</th></tr></thead><tbody>{rows}</tbody></table></div></body></html>"""
ROW = "<tr><td><a>{repo}</a></td><td>2026-10-03 08:00:00</td><td>{status}</td><td>{pr}</td></tr>"


@responses.activate
def test_statuses_and_wait_status() -> None:
    """Statuses come from the project page (project name read once); wait_status polls until the wanted one."""
    w = world()
    blueprint_id = RUN_CTX.name("bp")
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": FAKE_ORG, "project_name": "e2e-project"}])
    pending = PROJECT_PAGE.format(id=blueprint_id, rows=ROW.format(repo=REPO, status="NOT_CHECKED", pr="N/A"))
    done = PROJECT_PAGE.format(
        id=blueprint_id, rows=ROW.format(repo=REPO, status="REMEDIATION_PREPARED", pr="<a>#7</a>")
    )
    responses.get(f"{BASE}/projects/e2e-project", body=pending)
    responses.get(f"{BASE}/projects/e2e-project", body=done)
    row = w.helper.wait_status(blueprint_id, REPO, "remediation_prepared")
    assert row == {"status": "remediation_prepared", "updated_at": "2026-10-03 08:00:00", "remediation_pr": 7}
    assert len([c for c in responses.calls if c.request.url.endswith("/api/organizations")]) == 1
    assert w.helper.statuses(RUN_CTX.name("unknown")) == {}
    with pytest.raises(ValueError):
        w.helper.wait_status(blueprint_id, REPO, "approved")
    with pytest.raises(ReactionTimeoutError, match="did not set"):
        w.helper.wait_status(blueprint_id, REPO, {"success", "recheck"}, timeout=10)


@responses.activate
def test_remediations_dismissed_and_policy_counters() -> None:
    """The /api listings are filtered on the org; policy counters come from /admin/policies."""
    w = world()
    responses.get(f"{BASE}/api/blueprints/remediations", json={"data": [{"remediation_pr": 7}], "itemsCount": 1})
    responses.get(f"{BASE}/api/blueprints/dismissed", json={"data": [], "itemsCount": 0})
    assert w.helper.remediations(blueprint_id=RUN_CTX.name("bp")) == [{"remediation_pr": 7}]
    assert responses.calls[0].request.params["id[org_id]"] == "^" + re.escape(FAKE_ORG) + "$"
    assert w.helper.dismissed(repo=REPO) == []
    page = (
        "<div class='card'><h3 class='card-title'>macos_large_runners</h3><table><thead><tr><th>Total Workflow Jobs</th>"
        "<th>Cancelled On Restricted Runners</th></tr></thead><tbody><tr><td>{total}</td><td>{cancelled}</td></tr>"
        "</tbody></table></div>"
    )
    responses.get(f"{BASE}/admin/policies", body="<html></html>")
    responses.get(f"{BASE}/admin/policies", body=page.format(total=1, cancelled=0))
    responses.get(f"{BASE}/admin/policies", body=page.format(total=2, cancelled=1))
    assert w.helper.policy_status("macos_large_runners") == {}
    counters = w.helper.wait_policy_counter("macos_large_runners", "cancelled_on_restricted_runners", at_least=1)
    assert counters == {"total_workflow_jobs": 2, "cancelled_on_restricted_runners": 1}
    with pytest.raises(ValueError):
        w.helper.policy_status("nope")
    with pytest.raises(ReactionTimeoutError):
        w.helper.wait_policy_counter("macos_large_runners", "total_workflow_jobs", at_least=9, timeout=10)


def test_without_api_the_reads_are_refused() -> None:
    """A helper without the webapp API refuses webapp operations."""
    w = world()
    w.helper.api = None
    with pytest.raises(BlueprintError):
        w.helper.check()


# --- remediation pull requests -------------------------------------------------------------------------------------
def remediation_pull(number: int, *, repo: str = REPO, slug: str = "bp", state: str = "open") -> dict[str, Any]:
    """A remediation PR of this run's blueprint."""
    return {
        "number": number,
        "state": state,
        "title": required_file(slug).pr_title,
        "head": {"ref": f"otterdog/blueprint/{RUN_CTX.name(slug)}", "sha": fake_sha(("rem", number))},
        "base": {"ref": "main"},
    }


def test_wait_remediation_pr() -> None:
    """The newest PR of the remediation branch; ReactionTimeoutError when the webapp opens none."""
    w = world()
    w.time.hooks.append(lambda: w.oracle.add_pull(REPO, remediation_pull(3), state="open"))
    w.oracle.add_pull(REPO, {"number": 1, "head": {"ref": "feature"}}, state="open")
    pull = w.helper.wait_remediation_pr(REPO, required_file(), timeout=30)
    assert pull["number"] == 3 and pull["title"] == required_file().pr_title and w.time.now == 5
    w.oracle.add_pull(REPO, remediation_pull(5), state="open")
    assert [p["number"] for p in w.helper.remediation_prs(REPO, RUN_CTX.name("bp"), state="open")] == [5, 3]
    with pytest.raises(ReactionTimeoutError, match="no remediation PR"):
        w.helper.wait_remediation_pr(REPO, RUN_CTX.name("other"), timeout=10)
    with pytest.raises(SafetyError):
        w.helper.wait_remediation_pr(REPO, "default-security-policy", timeout=10)


def test_close_reopen_and_merge_remediation_prs() -> None:
    """close/reopen/merge only remediation PRs of this run; reopen restores the deleted branch first."""
    w = world()
    w.oracle.set("pull", REPO, 3, value=remediation_pull(3))
    w.helper.close_remediation_pr(REPO, 3)
    w.helper.reopen_remediation_pr(REPO, 3)
    head = remediation_pull(3)["head"]
    assert w.mutator.calls_to("create_ref")[0].args == (REPO, f"refs/heads/{head['ref']}", head["sha"])
    assert [c.method for c in w.mutator.calls] == ["close_pull", "create_ref", "reopen_pull"]
    w.oracle.set("branch_sha", REPO, head["ref"], value=head["sha"])
    w.helper.reopen_remediation_pr(REPO, 3)  # branch present: no ref created
    assert len(w.mutator.calls_to("create_ref")) == 1
    w.helper.merge_remediation_pr(REPO, 3, method="rebase")
    assert w.mutator.calls_to("merge_pull")[0].kwargs == {"method": "rebase", "sha": head["sha"]}


def test_remediation_pr_guards() -> None:
    """Foreign branches, foreign repositories and unknown PRs are refused."""
    w = world()
    w.oracle.set("pull", REPO, 4, value={"number": 4, "head": {"ref": "otterdog/blueprint/default-security-policy"}})
    w.oracle.set("pull", REPO, 6, value={"number": 6, "head": {"ref": f"e2e/{RUN}/case"}})
    for number in (4, 6):
        with pytest.raises(SafetyError):
            w.helper.close_remediation_pr(REPO, number)
    with pytest.raises(SafetyError):
        w.helper.close_remediation_pr("otterdog-e2e-fixture-a", 3)
    with pytest.raises(BlueprintError, match="no pull request"):
        w.helper.close_remediation_pr(REPO, 404)
    assert w.mutator.calls == []


def test_config_repo_remediations_merge_through_the_guarded_flow() -> None:
    """append_configuration PRs live in the config repo: adopted by the ConfigRepoFlow and merged with its guard."""
    w = world()
    guarded: list[tuple[str, str]] = []
    flow = ConfigRepoFlow(
        org=FAKE_ORG,
        repo=CONFIG_REPO,
        oracle=w.oracle,  # type: ignore[arg-type]
        mutators={"admin": w.mutator},  # type: ignore[dict-item]
        run_ctx=RUN_CTX,
        validation_context="v",
        sync_context="s",
        guard=lambda base, head: guarded.append((base, head)),
    )
    w.oracle.add_file(CONFIG_REPO, f"otterdog/{FAKE_ORG}.jsonnet", "base", ref="main")
    pull = remediation_pull(9, repo=CONFIG_REPO, slug="append")
    w.oracle.set("pull", CONFIG_REPO, 9, value=pull)
    w.oracle.add_file(CONFIG_REPO, f"otterdog/{FAKE_ORG}.jsonnet", "base + { }", ref=pull["head"]["sha"])
    with pytest.raises(BlueprintError, match="ConfigRepoFlow"):
        w.helper.merge_remediation_pr(CONFIG_REPO, 9)
    w.helper.flow = flow
    w.helper.merge_remediation_pr(CONFIG_REPO, 9, method="squash")
    assert guarded == [("base", "base + { }")]
    assert w.mutator.calls_to("merge_pull")[0].args == (CONFIG_REPO, 9)


# --- workflows -----------------------------------------------------------------------------------------------------
def test_workflow_builders_are_valid_yaml() -> None:
    """Every builder produces a workflow_dispatch / workflow_call workflow with pinned third-party actions."""
    store_path = f".github/workflows/{RUN_CTX.prefix}-sbom-store.yml"
    texts = {
        "large": bp.large_runner_workflow(RUN),
        "store": bp.sbom_store_workflow(RUN, artifact_name="e2e-sbom"),
        "caller": bp.sbom_caller_workflow(
            RUN,
            store_workflow=bp.reusable_workflow_ref(FAKE_ORG, REPO, store_path),
            project_name="p",
            parent_project="u",
        ),
        "unpinned": bp.unpinned_workflow(RUN),
        "scorecard": bp.scorecard_workflow(RUN),
    }
    documents = {name: yaml.safe_load(text) for name, text in texts.items()}
    triggers = {name: document.get("on", document.get(True)) for name, document in documents.items()}
    assert set(triggers["store"]) == {"workflow_call"} and all(
        set(trigger) == {"workflow_dispatch"} for name, trigger in triggers.items() if name != "store"
    )
    assert documents["large"]["jobs"]["large"]["runs-on"] == "macos-latest-large"
    assert documents["large"]["jobs"]["large"]["timeout-minutes"] == 1
    store_steps = documents["store"]["jobs"]["store"]["steps"]
    assert store_steps[1]["uses"] == bp.UPLOAD_ARTIFACT_ACTION and store_steps[1]["with"]["name"] == "e2e-sbom"
    assert (
        "${{ inputs.project-name }}" in texts["store"]
        and "bom.json" in texts["store"]
        and "metadata.json" in texts["store"]
    )
    caller = documents["caller"]["jobs"]["sbom"]
    assert caller["uses"] == f"{FAKE_ORG}/{REPO}/{store_path}@main" and caller["with"]["parent-project"] == "u"
    assert documents["unpinned"]["jobs"]["build"]["steps"][0]["uses"] == "actions/checkout@v4"
    for action in (bp.CHECKOUT_ACTION, bp.SCORECARD_ACTION, bp.UPLOAD_ARTIFACT_ACTION):
        assert re.fullmatch(r"[\w.-]+/[\w.-]+@[0-9a-f]{40}", action)
    assert re.search(bp.sbom_workflow_filter(store_path), f"{FAKE_ORG}/{REPO}/{store_path}@refs/heads/main")
    assert re.search(bp.sbom_workflow_filter(store_path), f"./{store_path}")


@pytest.mark.parametrize(
    ("runs_on", "labels", "larger"),
    [
        ("macos-latest-large", ["macos-latest-large"], True),
        ("[self-hosted, macos-14-xlarge]", ["self-hosted", "macos-14-xlarge"], True),
        ('"macos-13-large" # a comment', ["macos-13-large"], True),
        ("ubuntu-latest", ["ubuntu-latest"], False),
        ("macos-latest", ["macos-latest"], False),
    ],
)
def test_runner_labels(runs_on: str, labels: list[str], larger: bool) -> None:
    """runs-on labels and the policy's restricted-runner rule (macos* ... *large)."""
    content = f"jobs:\n  a:\n    runs-on: {runs_on}\n    steps: []\n"
    assert bp.runner_labels(content) == labels and bp.uses_larger_runner(content) is larger


def test_add_workflow_and_dispatch_guards() -> None:
    """Workflows go to this run's repositories; only own workflows are dispatched; a larger-runner job is refused
    where runners exist unless billing is accepted."""
    w = world(larger_runners=True)
    path = w.helper.add_large_runner_workflow(REPO)
    assert path == f".github/workflows/{RUN_CTX.prefix}-large-runner.yml"
    (commit,) = w.mutator.calls_to("commit_files")
    assert commit.args[0] == REPO and "macos-latest-large" in commit.args[2][path]
    with pytest.raises(SafetyError, match="billed"):
        w.helper.dispatch(REPO, path)
    dispatched = w.helper.dispatch(REPO, path, allow_billing=True, inputs={"x": "1"})
    file_name = f"{RUN_CTX.prefix}-large-runner.yml"
    (queued,) = w.oracle.workflow_runs(REPO, file_name)  # the shared RecordingMutator queues the dispatched run
    assert (dispatched.after, dispatched.run_id, dispatched.workflow) == (NOW, queued["id"], file_name)
    (dispatch,) = w.mutator.calls_to("dispatch_workflow")
    assert dispatch.args == (REPO, file_name, "main", {"x": "1"})  # Mutator.dispatch_workflow(repo, file, ref, inputs)
    with pytest.raises(BlueprintError, match="not added by this helper"):
        w.helper.dispatch(REPO, "ci.yml")
    with pytest.raises(SafetyError):
        w.helper.add_workflow("otterdog-e2e-fixture-a", "x", "name: x\n")
    free = world(larger_runners=False)
    free.helper.add_large_runner_workflow(REPO)
    free.helper.dispatch(REPO, f"{RUN_CTX.prefix}-large-runner.yml")  # a file name works too; no runner on Free


def test_add_sbom_workflows() -> None:
    """The reusable store workflow and its caller; the filter matches the store workflow."""
    w = world()
    sbom = w.helper.add_sbom_workflows(REPO, artifact_name="e2e-sbom")
    assert sbom.store == f".github/workflows/{RUN_CTX.prefix}-sbom-store.yml"
    assert sbom.caller == f".github/workflows/{RUN_CTX.prefix}-sbom.yml" and sbom.artifact_name == "e2e-sbom"
    files = {path: text for call in w.mutator.calls_to("commit_files") for path, text in call.args[2].items()}
    assert f"uses: {FAKE_ORG}/{REPO}/{sbom.store}@main" in files[sbom.caller]
    assert re.search(sbom.workflow_filter, f"{FAKE_ORG}/{REPO}/{sbom.store}@main")


def run(run_id: int, created_at: str, status: str = "queued", conclusion: str | None = None) -> dict[str, Any]:
    """A workflow run."""
    return {"id": run_id, "created_at": created_at, "status": status, "conclusion": conclusion}


def test_workflow_runs_wait_and_cancel() -> None:
    """Runs after the dispatch (clock skew allowed, Oracle.workflow_runs); a run that never appears is infra, one that
    never reaches ``until`` is a SUT reaction failure; cancel_run guards the repository."""
    w = world()
    file_name = f"{RUN_CTX.prefix}-large-runner.yml"
    w.oracle.set(
        "workflow_runs", REPO, file_name, value=[run(2, "2026-10-03T08:00:30Z"), run(1, "2026-10-03T07:00:00Z")]
    )
    assert [r["id"] for r in w.helper.workflow_runs(REPO, file_name, after=NOW)] == [2]
    w.oracle.set("workflow_runs", REPO, file_name, value=[run(2, "2026-10-03T08:00:30Z", "completed", "cancelled")])
    found = w.helper.wait_run(
        REPO, f".github/workflows/{file_name}", after=NOW, run_id=2, until=lambda r: r["conclusion"] == "cancelled"
    )
    assert found["id"] == 2
    with pytest.raises(ReactionTimeoutError, match="completed/cancelled"):
        w.helper.wait_run(REPO, file_name, after=NOW, until=lambda r: False, timeout=10)
    with pytest.raises(DeliveryTimeoutError, match="infra"):
        w.helper.wait_run(REPO, file_name, after=NOW, run_id=3, timeout=10)
    with pytest.raises(DeliveryTimeoutError, match="infra"):
        w.helper.wait_run(REPO, "e2e-other.yml", after=NOW, timeout=10)
    w.helper.cancel_run(REPO, 2)
    assert w.mutator.calls_to("cancel_workflow_run")[0].args == (REPO, 2)
    with pytest.raises(SafetyError):
        w.helper.cancel_run("otterdog-e2e-fixture-a", 2)


class FakeRelay:
    """DeliveryRelay stand-in with wait_event."""

    def __init__(self, delivery: RelayedDelivery | None) -> None:
        """Answer with ``delivery`` (None: time out)."""
        self.delivery = delivery
        self.calls: list[dict[str, Any]] = []

    def wait_event(self, event: str, **kwargs: Any) -> RelayedDelivery:
        """Record; answer or time out."""
        self.calls.append({"event": event, **kwargs})
        if self.delivery is None:
            raise WaitTimeoutError("relayed delivery", kwargs.get("timeout", 0))
        return self.delivery


def delivery(status: int | None = 204) -> RelayedDelivery:
    """A relayed workflow_job delivery."""
    return RelayedDelivery(
        id=1,
        guid="g",
        event="workflow_job",
        action="queued",
        installation_id=1,
        repository_id=1,
        pull_number=None,
        delivered_at=NOW,
        seen_at=NOW,
        forwarded_at=NOW,
        github_status_code=202,
        relay_status=status,
        repository_name=REPO,
        run_id=2,
    )


def test_wait_workflow_delivery() -> None:
    """Delivery waits go through relay.wait_event and the infra/SUT forward classification."""
    w = world()
    with pytest.raises(BlueprintError, match="relay"):
        w.helper.wait_workflow_delivery("workflow_job", repo=REPO)
    w.helper.relay = FakeRelay(delivery())
    assert w.helper.wait_workflow_delivery("workflow_job", repo=REPO, action="queued", run_id=2, after=NOW).run_id == 2
    assert w.helper.relay.calls[0] == {
        "event": "workflow_job",
        "action": "queued",
        "repository_name": REPO,
        "run_id": 2,
        "after": NOW,
        "timeout": 300,
    }
    w.helper.relay = FakeRelay(delivery(500))
    with pytest.raises(ReactionTimeoutError, match="SUT"):
        w.helper.wait_workflow_delivery("workflow_job", repo=REPO)
    w.helper.relay = FakeRelay(None)
    with pytest.raises(DeliveryTimeoutError, match="workflow events"):
        w.helper.wait_workflow_delivery("workflow_run", repo=REPO, timeout=5)


# --- cleanup -------------------------------------------------------------------------------------------------------
@responses.activate
def test_cleanup_cancels_closes_removes_and_reloads() -> None:
    """Pending runs cancelled, open remediation PRs closed, definitions removed, the webapp reloaded."""
    w = world()
    w.helper.add_blueprint(required_file())
    path = w.helper.add_large_runner_workflow(REPO)
    w.helper.dispatch(REPO, path)
    w.oracle.set(
        "workflow_runs",
        REPO,
        f"{RUN_CTX.prefix}-large-runner.yml",
        value=[run(8, "2026-10-03T08:00:10Z"), run(7, "2026-10-03T08:00:05Z", "completed", "success")],
    )
    w.oracle.add_pull(REPO, remediation_pull(3), state="open")
    w.helper.remediation_prs(REPO, RUN_CTX.name("bp"), state="open")  # the helper saw the PR's repository
    responses.get(f"{BASE}/internal/init", json={})
    responses.get(
        f"{BASE}/api/tasks",
        json={
            "data": [
                task("FetchBlueprintsTask", "finished", "2026-10-03T08:00:01"),
                task("FetchPoliciesTask", "finished", "2026-10-03T08:00:01"),
            ]
        },
    )
    w.helper.cleanup()
    assert [c.args for c in w.mutator.calls_to("cancel_workflow_run")] == [(REPO, 8)]
    assert [c.args for c in w.mutator.calls_to("close_pull")] == [(REPO, 3)]
    assert w.mutator.calls_to("commit_files")[-1].args[2] == {f"otterdog/blueprints/{RUN_CTX.name('bp')}.yml": None}
    assert w.helper.written == {} and any(c.request.url.endswith("/internal/init") for c in responses.calls)


def test_cleanup_reports_every_failure() -> None:
    """Each step runs; the failures are raised together."""
    w = world()
    w.helper.add_blueprint(required_file())

    def broken(*args: Any, **kwargs: Any) -> str:
        """A failing commit."""
        raise RuntimeError("422 branch protected")

    w.mutator.commit_files = broken  # type: ignore[method-assign]
    w.helper.api = None
    with pytest.raises(BlueprintError, match="remove definitions: RuntimeError: 422 branch protected"):
        w.helper.cleanup()
    assert w.helper.written  # still known: a later cleanup can retry


def test_now_is_timezone_aware() -> None:
    """The default clock is aware UTC (task and run timestamps are compared with it)."""
    helper = BlueprintHelper(
        org=FAKE_ORG,
        configs_repo=CONFIGS,
        config_repo=CONFIG_REPO,
        run_ctx=RUN_CTX,
        oracle=FakeOracle(),
        mutator=RecordingMutator(),  # type: ignore[arg-type]
    )
    assert helper.now().tzinfo is not None and abs(helper.now() - datetime.now(UTC)) < timedelta(seconds=5)
