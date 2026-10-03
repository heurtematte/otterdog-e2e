"""The fakes of otterdog_e2e.testing.fakes mirror the real interfaces and behave as documented."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from otterdog_e2e import naming
from otterdog_e2e.github.app import AppAuth
from otterdog_e2e.github.http import GitHubError, GitHubHttp
from otterdog_e2e.github.mutate import Mutator
from otterdog_e2e.github.oracle import Oracle
from otterdog_e2e.otterdog.runner import OtterdogCli
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.scenarios.checks import CHECK_KINDS, LIST_KINDS
from otterdog_e2e.testing.fakes import (
    FAKE_ORG,
    FAKE_RUN_ID,
    FakeAppAuth,
    FakeCli,
    FakeGitHubHttp,
    FakeOracle,
    RecordingMutator,
    fake_sha,
    make_run_context,
    make_verified_org,
)

RUN = make_run_context()


def _public_methods(cls: type) -> dict[str, list[str]]:
    """Public callables of a class and their parameter names."""
    methods = {}
    for name, value in vars(cls).items():
        if name.startswith("_") or not callable(value):
            continue
        methods[name] = list(inspect.signature(value).parameters)
    return methods


@pytest.mark.parametrize(
    ("real", "fake"),
    [(Oracle, FakeOracle), (OtterdogCli, FakeCli), (Mutator, RecordingMutator), (GitHubHttp, FakeGitHubHttp)],
)
def test_fake_mirrors_real_interface(real: type, fake: type) -> None:
    """Every public method of the real class exists on the fake with the same parameter names."""
    real_methods = _public_methods(real)
    fake_methods = _public_methods(fake)
    missing = sorted(set(real_methods) - set(fake_methods))
    assert not missing, f"{fake.__name__} misses {missing}"
    mismatched = {
        name: (params, fake_methods[name]) for name, params in real_methods.items() if fake_methods[name] != params
    }
    assert not mismatched, mismatched


def test_fake_app_auth_mirrors_relay_interface() -> None:
    """The AppAuth members used by the relay, flows and doctor exist on FakeAppAuth with the same parameters."""
    for name in (
        "jwt",
        "get_app",
        "installations",
        "installation_for_org",
        "installation_token",
        "hook_config",
        "list_deliveries",
        "get_delivery",
    ):
        assert list(inspect.signature(getattr(FakeAppAuth, name)).parameters) == list(
            inspect.signature(getattr(AppAuth, name)).parameters
        ), name
    for name in ("slug", "bot_login", "rate_remaining", "rate_reset"):
        assert isinstance(inspect.getattr_static(FakeAppAuth, name), property), name
        assert isinstance(inspect.getattr_static(AppAuth, name), property), name
    app = FakeAppAuth()
    assert app.rate_reset is None
    app.rate_reset = datetime(2026, 1, 1, tzinfo=UTC)
    assert app.rate_reset == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize("kind", sorted(CHECK_KINDS))
def test_check_kinds_map_to_oracle_methods(kind: str) -> None:
    """CHECK_KINDS (scenarios.checks) names real Oracle methods with exactly those parameters."""
    method, names = CHECK_KINDS[kind]
    parameters = list(inspect.signature(getattr(Oracle, method)).parameters)
    assert parameters[1:] == list(names)
    assert set(LIST_KINDS) <= set(CHECK_KINDS)


# --- FakeOracle ----------------------------------------------------------------------------------------------------
def test_fake_oracle_defaults_and_set() -> None:
    """Unknown single lookups are None, lists are [], stored answers are copies."""
    oracle = FakeOracle()
    assert oracle.org()["login"] == FAKE_ORG and oracle.plan_name() == "free"
    assert oracle.repo("missing") is None and oracle.repos() == [] and oracle.team_members("t") == []
    oracle.set("pages", "r", value={"build_type": "workflow"})
    page = oracle.pages("r")
    page["build_type"] = "changed"
    assert oracle.pages("r") == {"build_type": "workflow"}
    with pytest.raises(AttributeError):
        oracle.set("no_such_lookup", value=1)
    assert ("pages", ("r",)) in oracle.calls


def test_fake_oracle_derived_lookups() -> None:
    """Single lookups search the corresponding lists (repos, teams, hooks, variables, rulesets, ...)."""
    oracle = FakeOracle()
    repo = RUN.name("basic")
    oracle.add_repo(repo, description="e2e basic", topics=["e2e"])
    oracle.add_team(RUN.name("team"), members=["e2e-author"])
    oracle.add_repo_hook(repo, RUN.hook_url("repo"))
    oracle.add_org_hook(RUN.hook_url("org"))
    oracle.set("org_variables", value=[{"name": RUN.const("var"), "value": "x"}])
    oracle.set("repo_rulesets", repo, value=[{"name": RUN.name("rs"), "enforcement": "active"}])
    oracle.set("branch_protection_rules", repo, value=[{"pattern": "main"}])
    oracle.set("custom_properties", value=[{"property_name": RUN.prop("tier")}])
    oracle.set("environments", repo, value=[{"name": "prod"}])
    assert oracle.repo(repo)["description"] == "e2e basic"
    assert oracle.repo_topics(repo) == ["e2e"]
    assert oracle.default_branch(repo) == "main"
    assert oracle.team(RUN.name("team"))["slug"] == RUN.name("team")
    assert oracle.team_members(RUN.name("team")) == ["e2e-author"]
    assert oracle.repo_hook_by_url(repo, RUN.hook_url("repo"))["config"]["url"] == RUN.hook_url("repo")
    assert oracle.org_hook_by_url(RUN.hook_url("org")) is not None
    assert oracle.org_hook_by_url("https://elsewhere.example.org/") is None
    assert oracle.org_variable(RUN.const("var"))["value"] == "x"
    assert oracle.repo_ruleset(repo, RUN.name("rs"))["enforcement"] == "active"
    assert oracle.branch_protection_rule(repo, "main") == {"pattern": "main"}
    assert oracle.custom_property(RUN.prop("tier")) is not None
    assert oracle.environment(repo, "prod") == {"name": "prod"}
    oracle.remove_repo(repo)
    assert oracle.repo(repo) is None


def test_fake_oracle_statuses_comments_files_pulls() -> None:
    """Commit statuses (newest first), PR comments, file contents and pulls."""
    oracle = FakeOracle()
    sha = fake_sha("head")
    oracle.add_status(".otterdog", sha, "e2e/otterdog-validate", "pending")
    oracle.add_status(".otterdog", sha, "e2e/otterdog-validate", "success", "valid")
    assert oracle.latest_status(".otterdog", sha, "e2e/otterdog-validate")["state"] == "success"
    assert oracle.latest_status(".otterdog", sha, "other") is None
    assert len(oracle.combined_status(".otterdog", sha)["statuses"]) == 1
    oracle.add_pr_comment(".otterdog", 3, "<!-- Otterdog Comment: validate -->", author="otterdog-e2e-app[bot]")
    (comment,) = oracle.pr_comments(".otterdog", 3)
    assert comment["author"] == "otterdog-e2e-app" and comment["id"].startswith("IC_")
    oracle.add_file(".otterdog", "otterdog/o.jsonnet", "main text")
    oracle.add_file(".otterdog", "otterdog/o.jsonnet", "branch text", ref="e2e/x")
    assert oracle.file_content(".otterdog", "otterdog/o.jsonnet") == "main text"
    assert oracle.file_content(".otterdog", "otterdog/o.jsonnet", "e2e/x") == "branch text"
    assert oracle.file_content(".otterdog", "otterdog/o.jsonnet", "other") == "main text"
    oracle.add_pull(".otterdog", {"number": 9, "state": "open"})
    assert oracle.pull(".otterdog", 9)["state"] == "open"
    assert oracle.pull(".otterdog", 10) is None


def test_fake_oracle_unavailable_and_lookup() -> None:
    """Unavailable listings answer [] and are recorded; lookup dispatches through CHECK_KINDS."""
    oracle = FakeOracle()
    oracle.mark_unavailable("org_rulesets", status=403)
    assert oracle.org_rulesets() == []
    assert oracle.unavailable == {("org_rulesets", FAKE_ORG): 403}
    oracle.add_repo(RUN.name("basic"))
    assert oracle.lookup("repo", name=RUN.name("basic"))["name"] == RUN.name("basic")
    assert oracle.lookup("org")["login"] == FAKE_ORG
    with pytest.raises(TypeError):
        oracle.lookup("repo_secret", repo="r")
    with pytest.raises(KeyError):
        oracle.lookup("unknown_kind")


# --- FakeCli -------------------------------------------------------------------------------------------------------
def test_fake_cli_defaults_and_queue() -> None:
    """Commands pop queued results, else realistic defaults; calls are recorded."""
    cli = FakeCli()
    assert cli.version().startswith("otterdog.sh, version ")
    assert "Plan: 0 to add, 0 to change, 0 to delete." in cli.plan().stdout
    assert "Validation succeeded" in cli.validate(local=True).stdout
    queued = cli.queue("apply", stdout="Executed plan: 1 added, 0 changed, 0 deleted.", exit_code=0)
    assert cli.apply(delete=True, repo_filter=RUN.repo_filter()) is queued
    assert cli.apply().stdout.strip().endswith("No changes required.")
    cli.queue("check-status", status={"org_id": FAKE_ORG, "in_sync": True})
    result, status = cli.check_status(Path("status.json"))
    assert result.exit_code == 0 and status == {"org_id": FAKE_ORG, "in_sync": True}
    assert cli.calls_to("apply")[0].kwargs["delete"] is True
    assert cli.calls_to("apply")[0].kwargs["repo_filter"] == RUN.repo_filter()
    assert cli.run("show-live", "-x").argv == ["otterdog", "show-live", "-x"]
    assert cli.pending() == {}


def test_fake_cli_strict() -> None:
    """strict FakeCli refuses unqueued commands."""
    cli = FakeCli(strict=True)
    cli.queue("validate", stdout="ok")
    assert cli.validate().stdout == "ok"
    with pytest.raises(AssertionError, match="no result queued"):
        cli.validate()


# --- RecordingMutator ----------------------------------------------------------------------------------------------
def test_recording_mutator_records_and_updates_oracle() -> None:
    """Calls are recorded with plausible return values; a linked FakeOracle reflects them."""
    oracle = FakeOracle()
    mutator = RecordingMutator(oracle=oracle)
    assert mutator.org == FAKE_ORG
    created = mutator.create_repo(RUN.name("basic"), description="d")
    assert created["name"] == RUN.name("basic") and oracle.repo(RUN.name("basic")) is not None
    pull = mutator.create_pull(".otterdog", head=RUN.branch("pr"), base="main", title="t")
    assert pull["number"] == 1 and oracle.pull(".otterdog", 1)["head"]["ref"] == RUN.branch("pr")
    assert mutator.create_pull(".otterdog", head="b", base="main", title="t")["number"] == 2
    sha = mutator.commit_files(".otterdog", RUN.branch("pr"), {"otterdog/o.jsonnet": "text", "gone": None}, "msg")
    assert len(sha) == 40 and oracle.file_content(".otterdog", "otterdog/o.jsonnet", RUN.branch("pr")) == "text"
    assert mutator.merge_pull(".otterdog", 1, sha=sha)["merged"] is True
    assert mutator.review(".otterdog", 1)["state"] == "APPROVED"
    mutator.delete_repo(RUN.name("basic"))
    assert oracle.repo(RUN.name("basic")) is None
    mutator.set_org_description("[otterdog-e2e] new")
    assert oracle.org()["description"] == "[otterdog-e2e] new"
    assert [call.method for call in mutator.calls][:2] == ["create_repo", "create_pull"]
    assert mutator.calls_to("merge_pull")[0].kwargs == {"method": "squash", "sha": sha}


def test_recording_mutator_guards() -> None:
    """Deletion guards of SPEC 5.2 (names, refs, hook URLs; force only for names)."""
    oracle = FakeOracle()
    mutator = RecordingMutator(oracle=oracle)
    for call in (
        lambda: mutator.delete_repo(".otterdog"),
        lambda: mutator.delete_team("otterdog-admins"),
        lambda: mutator.delete_org_secret("PROD_SECRET"),
        lambda: mutator.delete_org_variable("PROD_VAR"),
        lambda: mutator.delete_org_ruleset(1, name="prod"),
        lambda: mutator.delete_custom_property("tier"),
        lambda: mutator.delete_ref(".otterdog", "heads/main"),
    ):
        with pytest.raises(SafetyError):
            call()
    mutator.delete_repo(".otterdog-old", force=True)
    mutator.delete_ref("otterdog-e2e-configs", "heads/e2e-lease")
    mutator.delete_ref(".otterdog", f"heads/e2e/{FAKE_RUN_ID}/x")
    foreign = oracle.add_org_hook("https://ci.example.org/hook")
    mine = oracle.add_org_hook(RUN.hook_url("org"))
    with pytest.raises(SafetyError):
        mutator.delete_org_hook(foreign["id"])
    mutator.delete_org_hook(mine["id"])
    assert RecordingMutator(guard=False).delete_repo(".otterdog") is None


def test_recording_mutator_pull_request_edits() -> None:
    """reopen_pull reopens the oracle's PR (run branches only, blueprint remediation branches of the run included);
    delete_comment drops the comment from the oracle's pr_comments."""
    oracle = FakeOracle()
    mutator = RecordingMutator(oracle=oracle)
    oracle.add_pull(".otterdog", {"number": 7, "state": "closed", "head": {"ref": RUN.branch("pr")}}, state="all")
    oracle.add_pull(RUN.name("r"), {"number": 8, "head": {"ref": f"otterdog/blueprint/{RUN.name('bp')}"}})
    oracle.add_pull(".otterdog", {"number": 9, "head": {"ref": "feature/x"}})
    mutator.reopen_pull(".otterdog", 7)
    assert oracle.pull(".otterdog", 7)["state"] == "open"
    mutator.reopen_pull(RUN.name("r"), 8)
    with pytest.raises(SafetyError):
        mutator.reopen_pull(".otterdog", 9)
    kept = oracle.add_pr_comment(".otterdog", 7, "keep")
    gone = oracle.add_pr_comment(".otterdog", 7, "gone")
    mutator.delete_comment(".otterdog", gone["database_id"])
    assert [comment["body"] for comment in oracle.pr_comments(".otterdog", 7)] == [kept["body"]]
    assert [call.method for call in mutator.calls] == ["reopen_pull", "reopen_pull", "delete_comment"]


def test_fake_cli_web_mode_attributes() -> None:
    """FakeCli exposes ``web`` and ``installed`` like OtterdogCli (None by default; web-mode stand-ins set them)."""
    assert FakeCli().web is None and FakeCli().installed is None
    marker = object()
    assert FakeCli(web=marker, installed="sut").web is marker


# --- FakeAppAuth ---------------------------------------------------------------------------------------------------
def test_fake_app_auth_deliveries() -> None:
    """Deliveries are listed newest first with cursor pagination; details carry the payload."""
    app = FakeAppAuth()
    start = datetime(2026, 1, 1, tzinfo=UTC)
    for minute in range(5):
        app.add_delivery(
            "pull_request", {"action": "opened", "number": minute}, delivered_at=start + timedelta(minutes=minute)
        )
    other = app.add_delivery("push", {"ref": "refs/heads/main"}, installation_id=999, delivered_at=start)
    page, cursor = app.list_deliveries(per_page=2)
    assert [item["action"] for item in page] == ["opened", "opened"]
    assert page[0]["delivered_at"] > page[1]["delivered_at"]
    assert "request" not in page[0] and page[0]["installation_id"] == app.installation_id
    seen = list(page)
    while cursor:
        page, cursor = app.list_deliveries(per_page=2, cursor=cursor)
        seen += page
    assert len(seen) == 6
    assert app.get_delivery(other["id"])["request"]["payload"] == {"ref": "refs/heads/main"}
    assert other["installation_id"] == 999
    with pytest.raises(KeyError):
        app.get_delivery(1)
    assert app.bot_login == "otterdog-e2e-test[bot]"
    assert app.installation_for_org(FAKE_ORG)["repository_selection"] == "all"
    assert app.installation_for_org("other-org") is None
    app.rate_remaining = 10
    assert app.rate_remaining == 10


def test_fake_app_tokens_look_real_and_are_redacted() -> None:
    """Fake JWTs and installation tokens have real token shapes, so redaction applies to them."""
    from otterdog_e2e.redact import Redactor

    app = FakeAppAuth()
    redactor = Redactor()
    assert redactor(app.jwt()) == "***"
    assert redactor(app.installation_token(app.installation_id)) == "***"


# --- FakeGitHubHttp ------------------------------------------------------------------------------------------------
def test_fake_http_routes_and_error_semantics() -> None:
    """Routes, fnmatch patterns, repeat, allow_404, allow_unavailable and GitHubError (SPEC 4)."""
    http = FakeGitHubHttp()
    http.add("GET", f"/orgs/{FAKE_ORG}", json={"login": FAKE_ORG}, repeat=True)
    http.add("GET", f"/repos/{FAKE_ORG}/missing", status=404, json={"message": "Not Found"})
    http.add("GET", f"/orgs/{FAKE_ORG}/rulesets", status=403, json={"message": "Upgrade"})
    http.add("GET", f"/repos/{FAKE_ORG}/*/environments", json={"environments": [{"name": "prod"}]})
    http.add("POST", f"/repos/{FAKE_ORG}/x/git/refs", status=422, json={"message": "Reference already exists"})
    assert http.get(f"/orgs/{FAKE_ORG}") == {"login": FAKE_ORG}
    assert http.get(f"/orgs/{FAKE_ORG}")["login"] == FAKE_ORG
    assert http.get(f"/repos/{FAKE_ORG}/missing", allow_404=True) is None
    assert http.paginate(f"/orgs/{FAKE_ORG}/rulesets", allow_unavailable=True) == []
    assert http.unavailable == {f"/orgs/{FAKE_ORG}/rulesets": 403}
    assert http.paginate(f"/repos/{FAKE_ORG}/r/environments", item_key="environments") == [{"name": "prod"}]
    with pytest.raises(GitHubError) as info:
        http.post(f"/repos/{FAKE_ORG}/x/git/refs", json={"ref": "refs/heads/e2e-lease", "sha": fake_sha(1)})
    assert info.value.status == 422
    assert http.calls_to("POST", "*/git/refs")[0].json["ref"] == "refs/heads/e2e-lease"
    with pytest.raises(AssertionError, match="unexpected request"):
        http.get("/unregistered")
    assert FakeGitHubHttp(strict=False).get("/x", allow_404=True) is None


def test_fake_http_responder_graphql_and_read_only() -> None:
    """Callable responders, GraphQL data/errors and the read-only guard."""
    http = FakeGitHubHttp(read_only=True, scopes={"repo", "admin:org"})
    http.add("POST", "/graphql", responder=lambda call: (200, {"data": {"echo": call.json["variables"]}}), repeat=True)
    assert http.graphql("query { viewer { login } }", {"a": 1}) == {"echo": {"a": 1}}
    with pytest.raises(SafetyError):
        http.graphql("mutation { x }")
    with pytest.raises(SafetyError):
        http.delete(f"/repos/{FAKE_ORG}/x")
    assert http.oauth_scopes() == {"repo", "admin:org"}
    errors = FakeGitHubHttp()
    errors.add("POST", "/graphql", json={"errors": [{"message": "bad"}]}, repeat=True)
    with pytest.raises(GitHubError):
        errors.graphql("{ x }")
    assert errors.graphql("{ x }", allow_errors=True) == {}
    assert FakeGitHubHttp().oauth_scopes() is None


def test_helpers() -> None:
    """make_verified_org/make_run_context/fake_sha produce valid, deterministic values."""
    verified = make_verified_org(plan="enterprise")
    assert verified.plan == "enterprise" and "[otterdog-e2e]" in verified.org_json["description"]
    assert naming.RUN_ID_RE.match(FAKE_RUN_ID) and naming.extract_run_id(RUN.name("x")) == FAKE_RUN_ID
    assert fake_sha("a") == fake_sha("a") != fake_sha("b") and len(fake_sha("a")) == 40
