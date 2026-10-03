"""Mutator: SPEC 5.2 deletion guards, commit_files flow, retries, dry-run and identity helpers (SPEC 9.4)."""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import responses

from otterdog_e2e.github.http import GITHUB_API, GitHubError, GitHubHttp
from otterdog_e2e.github.mutate import DRY_RUN_SHA, Mutator, accept_org_invitation, publicize_membership
from otterdog_e2e.naming import HOOK_BASE
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FAKE_ORG, FAKE_RUN_ID, make_verified_org

TOKEN = "ghp_" + "MutatorTestToken0123456789abcdefghijk"
REPO = f"{GITHUB_API}/repos/{FAKE_ORG}/r"
ORG = f"{GITHUB_API}/orgs/{FAKE_ORG}"
P = f"e2e-{FAKE_RUN_ID}"
C = f"E2E_{FAKE_RUN_ID.upper()}_"
HEAD, TREE, NEW_TREE, COMMIT = "1" * 40, "2" * 40, "3" * 40, "4" * 40


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked api.github.com; unregistered requests fail."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def sleeps() -> list[float]:
    """Recorded sleeps."""
    return []


@pytest.fixture
def mutator(sleeps: list[float]) -> Mutator:
    """A Mutator over a client write-scoped to the fake verified org."""
    verified = make_verified_org()
    http = GitHubHttp(TOKEN, write_scope=verified, sleep=sleeps.append, min_write_interval=0.0)
    return Mutator(http, verified)


def body(call: responses.Call) -> dict:
    """JSON body of a recorded request."""
    return json.loads(call.request.body or "{}")


# --- construction --------------------------------------------------------------------------------------------------
def test_mutator_requires_a_client_scoped_to_the_verified_org() -> None:
    """Unscoped, read-only or foreign-scoped clients are refused (dry-run accepts any client)."""
    verified = make_verified_org()
    other = make_verified_org("other-test-org", org_id=7)
    with pytest.raises(SafetyError):
        Mutator(GitHubHttp(TOKEN), verified)
    with pytest.raises(SafetyError):
        Mutator(GitHubHttp(TOKEN, write_scope=other), verified)
    with pytest.raises(SafetyError):
        Mutator(GitHubHttp(TOKEN, write_scope=verified, read_only=True), verified)
    assert Mutator(GitHubHttp(TOKEN, read_only=True), verified, dry_run=True).org == FAKE_ORG


# --- deletion guards -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("method", "args"),
    [
        ("delete_repo", (".otterdog",)),
        ("delete_repo", ("otterdog-e2e-configs",)),
        ("delete_repo", ("e2e-sandbox-x",)),
        ("delete_team", ("otterdog-admins",)),
        ("delete_org_secret", ("PROD_TOKEN",)),
        ("delete_org_variable", ("E2E_NOTARUNID_X",)),
        ("delete_custom_property", ("visibility-tier",)),
        ("delete_environment", ("r", "github-pages")),
        ("delete_repo_secret", ("r", "DEPLOY_KEY")),
        ("delete_repo_variable", ("r", "VERSION")),
        ("delete_ref", ("r", "heads/main")),
        ("delete_ref", ("r", "tags/v1.6.1")),
        ("delete_ref", ("r", "heads/e2e/sandbox1/x")),
    ],
)
def test_deletion_guards_refuse_non_e2e_names(
    api: responses.RequestsMock, mutator: Mutator, method: str, args: tuple
) -> None:
    """Non-e2e names raise SafetyError before any request."""
    with pytest.raises(SafetyError):
        getattr(mutator, method)(*args)
    assert len(api.calls) == 0


def test_deletions_of_e2e_names(api: responses.RequestsMock, mutator: Mutator) -> None:
    """e2e names are deleted (404 ignored); force=True bypasses the name guard for bootstrap."""
    deletions = [
        f"{REPO.rsplit('/', 1)[0]}/{P}-basic",
        f"{ORG}/teams/{P}-team",
        f"{ORG}/actions/secrets/{C}TOKEN",
        f"{ORG}/actions/variables/{C}VAR",
        f"{ORG}/properties/schema/{P}-prop",
        f"{REPO}/environments/{P}-env",
        f"{REPO}/actions/secrets/{C}S",
        f"{REPO}/actions/variables/{C}V",
        f"{GITHUB_API}/repos/{FAKE_ORG}/old-sandbox",
    ]
    for url in deletions:
        api.add(responses.DELETE, url, status=204)
    api.replace(responses.DELETE, f"{ORG}/teams/{P}-team", status=404, json={"message": "Not Found"})
    mutator.delete_repo(f"{P}-basic")
    mutator.delete_team(f"{P}-team")
    mutator.delete_org_secret(f"{C}TOKEN")
    mutator.delete_org_variable(f"{C}VAR")
    mutator.delete_custom_property(f"{P}-prop")
    mutator.delete_environment("r", f"{P}-env")
    mutator.delete_repo_secret("r", f"{C}S")
    mutator.delete_repo_variable("r", f"{C}V")
    mutator.delete_repo("old-sandbox", force=True)
    assert [call.request.method for call in api.calls] == ["DELETE"] * len(deletions)


def test_delete_ref_guard_and_tolerance(api: responses.RequestsMock, mutator: Mutator) -> None:
    """Only e2e refs are deleted (git/refs plural path); 404 and 422 (no such ref) are ignored."""
    branch = f"heads/e2e/{FAKE_RUN_ID}/x"
    api.add(responses.DELETE, f"{REPO}/git/refs/{branch}", status=204)
    api.add(
        responses.DELETE,
        f"{REPO}/git/refs/heads/otterdog/{P}-pr",
        status=422,
        json={"message": "Reference does not exist"},
    )
    api.add(responses.DELETE, f"{REPO}/git/refs/tags/e2e-run/{FAKE_RUN_ID}", status=404)
    api.add(responses.DELETE, f"{REPO}/git/refs/heads/e2e-lease", status=204)
    api.add(responses.DELETE, f"{REPO}/git/refs/tags/sut-v1.6.1-abcd1234", status=204)
    mutator.delete_ref("r", branch)
    mutator.delete_ref("r", f"refs/heads/otterdog/{P}-pr")
    mutator.delete_ref("r", f"tags/e2e-run/{FAKE_RUN_ID}")
    mutator.delete_ref("r", "heads/e2e-lease")
    mutator.delete_ref("r", "tags/sut-v1.6.1-abcd1234")
    assert len(api.calls) == 5


def test_delete_hooks_check_the_live_url(api: responses.RequestsMock, mutator: Mutator) -> None:
    """Hooks are deleted only when their live config.url is under HOOK_BASE; a vanished hook is a no-op."""
    api.add(responses.GET, f"{ORG}/hooks/1", json={"id": 1, "config": {"url": "https://ci.example.org/hook"}})
    api.add(responses.GET, f"{ORG}/hooks/2", json={"id": 2, "config": {"url": f"{HOOK_BASE}{FAKE_RUN_ID}/h"}})
    api.add(responses.DELETE, f"{ORG}/hooks/2", status=204)
    api.add(responses.GET, f"{ORG}/hooks/3", status=404, json={"message": "Not Found"})
    api.add(responses.GET, f"{REPO}/hooks/4", json={"id": 4, "config": {"url": "https://otterdog-e2e.invalid.evil/x"}})
    with pytest.raises(SafetyError):
        mutator.delete_org_hook(1)
    mutator.delete_org_hook(2)
    mutator.delete_org_hook(3)
    with pytest.raises(SafetyError):
        mutator.delete_repo_hook("r", 4)
    assert [call.request.method for call in api.calls] == ["GET", "GET", "DELETE", "GET", "GET"]


def test_ruleset_and_role_deletions_check_live_names(api: responses.RequestsMock, mutator: Mutator) -> None:
    """Rulesets/roles: the name must be an e2e name AND match the live object."""
    api.add(responses.GET, f"{ORG}/rulesets/7", json={"id": 7, "name": "protect-main"})
    api.add(responses.GET, f"{ORG}/rulesets/8", json={"id": 8, "name": f"{P}-rs"})
    api.add(responses.DELETE, f"{ORG}/rulesets/8", status=204)
    api.add(responses.GET, f"{ORG}/organization-roles/9", json={"id": 9, "name": f"{P}-role"})
    api.add(responses.DELETE, f"{ORG}/organization-roles/9", status=204)
    api.add(responses.GET, f"{REPO}/rulesets/10", json={"id": 10, "name": f"{P}-repo-rs"})
    api.add(responses.DELETE, f"{REPO}/rulesets/10", status=204)
    with pytest.raises(SafetyError):
        mutator.delete_org_ruleset(7, name=f"{P}-rs")
    with pytest.raises(SafetyError):
        mutator.delete_org_ruleset(7, name="protect-main")
    mutator.delete_org_ruleset(8, name=f"{P}-rs")
    mutator.delete_org_role(9, name=f"{P}-role")
    mutator.delete_repo_ruleset("r", 10, name=f"{P}-repo-rs")
    assert [c.request.method for c in api.calls].count("DELETE") == 3


def test_delete_branch_protection_rule_verifies_the_node(api: responses.RequestsMock, mutator: Mutator) -> None:
    """The BPR node must belong to org/repo and carry the pattern before the GraphQL mutation is sent."""
    graphql = f"{GITHUB_API}/graphql"
    ours = {"pattern": f"e2e/{FAKE_RUN_ID}/*", "repository": {"name": "r", "owner": {"login": FAKE_ORG}}}
    foreign = {**ours, "repository": {"name": "otterdog", "owner": {"login": "eclipse-csi"}}}
    api.add(responses.POST, graphql, json={"data": {"node": foreign}})
    api.add(responses.POST, graphql, json={"data": {"node": ours}})
    api.add(responses.POST, graphql, json={"data": {"deleteBranchProtectionRule": {"clientMutationId": None}}})
    with pytest.raises(SafetyError):
        mutator.delete_branch_protection_rule("r", "BPR_x", pattern="main")
    with pytest.raises(SafetyError):
        mutator.delete_branch_protection_rule("r", "BPR_x", pattern=f"e2e/{FAKE_RUN_ID}/*")
    mutator.delete_branch_protection_rule("r", "BPR_y", pattern=f"e2e/{FAKE_RUN_ID}/*")
    last = body(api.calls[-1])
    assert last["query"].startswith("mutation") and last["variables"] == {"id": "BPR_y"}


# --- git -----------------------------------------------------------------------------------------------------------
def register_commit_flow(api: responses.RequestsMock, *, tree: list[dict], truncated: bool = False) -> None:
    """Responses of the commit_files flow on branch main."""
    api.add(responses.GET, f"{REPO}/git/ref/heads/main", json={"ref": "refs/heads/main", "object": {"sha": HEAD}})
    api.add(responses.GET, f"{REPO}/git/commits/{HEAD}", json={"sha": HEAD, "tree": {"sha": TREE}})
    api.add(responses.GET, f"{REPO}/git/trees/{TREE}", json={"sha": TREE, "tree": tree, "truncated": truncated})
    api.add(responses.POST, f"{REPO}/git/trees", status=201, json={"sha": NEW_TREE})
    api.add(responses.POST, f"{REPO}/git/commits", status=201, json={"sha": COMMIT})
    api.add(responses.PATCH, f"{REPO}/git/refs/heads/main", json={"ref": "refs/heads/main", "object": {"sha": COMMIT}})


def test_commit_files_flow(api: responses.RequestsMock, mutator: Mutator) -> None:
    """ref -> commit -> recursive tree -> tree(base_tree, inline content, sha null for present paths) -> commit -> PATCH."""
    register_commit_flow(
        api, tree=[{"path": "otterdog/old.jsonnet", "type": "blob"}, {"path": "otterdog", "type": "tree"}]
    )
    files = {"otterdog/org.jsonnet": "{}\n", "otterdog/old.jsonnet": None, "otterdog/never-existed.jsonnet": None}
    assert mutator.commit_files("r", "main", files, "e2e: update") == COMMIT
    methods = [(c.request.method, str(c.request.url).split(f"/repos/{FAKE_ORG}/r")[1]) for c in api.calls]
    assert methods == [
        ("GET", "/git/ref/heads/main"),
        ("GET", f"/git/commits/{HEAD}"),
        ("GET", f"/git/trees/{TREE}?recursive=1"),
        ("POST", "/git/trees"),
        ("POST", "/git/commits"),
        ("PATCH", "/git/refs/heads/main"),
    ]
    assert body(api.calls[3]) == {
        "base_tree": TREE,
        "tree": [
            {"path": "otterdog/org.jsonnet", "mode": "100644", "type": "blob", "content": "{}\n"},
            {"path": "otterdog/old.jsonnet", "mode": "100644", "type": "blob", "sha": None},
        ],
    }
    assert body(api.calls[4]) == {"message": "e2e: update", "tree": NEW_TREE, "parents": [HEAD]}
    assert body(api.calls[5]) == {"sha": COMMIT, "force": False}


def test_commit_files_without_deletions_skips_tree_listing(api: responses.RequestsMock, mutator: Mutator) -> None:
    """No deletion => no recursive tree read."""
    register_commit_flow(api, tree=[])
    mutator.commit_files("r", "main", {"a.txt": "a"}, "m")
    assert not any("/git/trees/" in str(call.request.url) for call in api.calls)


def test_commit_files_truncated_tree_checks_paths(api: responses.RequestsMock, mutator: Mutator) -> None:
    """A truncated tree listing falls back to per-path contents lookups."""
    register_commit_flow(api, tree=[], truncated=True)
    api.add(responses.GET, f"{REPO}/contents/deep/file.txt", json={"type": "file", "sha": "f" * 40})
    api.add(responses.GET, f"{REPO}/contents/deep/gone.txt", status=404, json={"message": "Not Found"})
    mutator.commit_files("r", "main", {"deep/file.txt": None, "deep/gone.txt": None}, "m")
    tree_call = next(c for c in api.calls if c.request.method == "POST" and str(c.request.url).endswith("/git/trees"))
    assert body(tree_call)["tree"] == [{"path": "deep/file.txt", "mode": "100644", "type": "blob", "sha": None}]


def test_commit_files_retries_empty_repo_and_moved_branch(
    api: responses.RequestsMock, mutator: Mutator, sleeps: list[float]
) -> None:
    """409 (empty repo) is retried after 3 s; a non-fast-forward 422 restarts the flow."""
    api.add(responses.GET, f"{REPO}/git/ref/heads/main", status=409, json={"message": "Git Repository is empty."})
    register_commit_flow(api, tree=[])
    api.replace(
        responses.PATCH, f"{REPO}/git/refs/heads/main", status=422, json={"message": "Update is not a fast forward"}
    )
    api.add(responses.PATCH, f"{REPO}/git/refs/heads/main", json={"object": {"sha": COMMIT}})
    assert mutator.commit_files("r", "main", {"a": "1"}, "m") == COMMIT
    assert sleeps == [3.0]
    assert [c.request.method for c in api.calls].count("PATCH") == 2


def test_create_branch_retries_409(api: responses.RequestsMock, mutator: Mutator, sleeps: list[float]) -> None:
    """create_branch retries 409 (empty repository) and posts refs/heads/<branch>."""
    api.add(responses.POST, f"{REPO}/git/refs", status=409, json={"message": "Git Repository is empty."})
    api.add(responses.POST, f"{REPO}/git/refs", status=201, json={"ref": f"refs/heads/e2e/{FAKE_RUN_ID}/b"})
    mutator.create_branch("r", f"e2e/{FAKE_RUN_ID}/b", HEAD)
    assert body(api.calls[-1]) == {"ref": f"refs/heads/e2e/{FAKE_RUN_ID}/b", "sha": HEAD}
    assert sleeps == [3.0]


def test_create_branch_gives_up_after_30_s(api: responses.RequestsMock, mutator: Mutator, sleeps: list[float]) -> None:
    """The 409 retry budget is about 30 s."""
    api.add(responses.POST, f"{REPO}/git/refs", status=409, json={"message": "Git Repository is empty."})
    with pytest.raises(GitHubError):
        mutator.create_branch("r", "x", HEAD)
    assert sum(sleeps) == 30.0


def test_refs_and_commits(api: responses.RequestsMock, mutator: Mutator) -> None:
    """create_ref qualifies refs; 422 raises; update_ref PATCHes git/refs; force only for e2e refs."""
    api.add(responses.POST, f"{REPO}/git/refs", status=201, json={"ref": "refs/tags/sut-x", "object": {"sha": HEAD}})
    api.add(responses.POST, f"{REPO}/git/refs", status=422, json={"message": "Reference already exists"})
    api.add(responses.POST, f"{REPO}/git/commits", status=201, json={"sha": COMMIT})
    api.add(responses.PATCH, f"{REPO}/git/refs/heads/e2e-lease", json={})
    assert mutator.create_ref("r", "tags/sut-x", HEAD)["ref"] == "refs/tags/sut-x"
    assert body(api.calls[0]) == {"ref": "refs/tags/sut-x", "sha": HEAD}
    with pytest.raises(GitHubError) as info:
        mutator.create_ref("r", "refs/heads/e2e-lease", HEAD)
    assert info.value.status == 422
    assert mutator.create_commit("r", tree_sha=TREE, parents=[HEAD], message="m") == COMMIT
    mutator.update_ref("r", "heads/e2e-lease", COMMIT, force=True)
    assert body(api.calls[-1]) == {"sha": COMMIT, "force": True}
    with pytest.raises(SafetyError):
        mutator.update_ref("r", "heads/main", COMMIT, force=True)


def test_put_file_encodes_content(api: responses.RequestsMock, mutator: Mutator) -> None:
    """PUT contents with base64 content, branch and the replaced file's sha; returns the commit sha."""
    api.add(responses.PUT, f"{REPO}/contents/otterdog.json", status=200, json={"commit": {"sha": COMMIT}})
    assert mutator.put_file("r", "otterdog.json", '{"a": 1}', "e2e: config", branch="main", sha="f" * 40) == COMMIT
    sent = body(api.calls[0])
    assert base64.b64decode(sent["content"]).decode() == '{"a": 1}'
    assert sent["branch"] == "main" and sent["sha"] == "f" * 40 and sent["message"] == "e2e: config"


# --- pull requests -------------------------------------------------------------------------------------------------
def test_pull_request_calls(api: responses.RequestsMock, mutator: Mutator) -> None:
    """create_pull, comment, review (body only when given) and close_pull payloads."""
    api.add(responses.POST, f"{REPO}/pulls", status=201, json={"number": 5})
    api.add(responses.POST, f"{REPO}/issues/5/comments", status=201, json={"id": 1})
    api.add(responses.POST, f"{REPO}/pulls/5/reviews", json={"id": 2, "state": "APPROVED"})
    api.add(responses.PATCH, f"{REPO}/pulls/5", json={"number": 5, "state": "closed"})
    assert mutator.create_pull("r", head="e2e/x/y", base="main", title="t", body="b", draft=True)["number"] == 5
    assert body(api.calls[0]) == {"head": "e2e/x/y", "base": "main", "title": "t", "body": "b", "draft": True}
    mutator.comment("r", 5, "/otterdog help")
    assert body(api.calls[1]) == {"body": "/otterdog help"}
    mutator.review("r", 5)
    assert body(api.calls[2]) == {"event": "APPROVE"}
    mutator.close_pull("r", 5)
    assert body(api.calls[3]) == {"state": "closed"}


def test_merge_pull_retries_405_never_409_with_sha(
    api: responses.RequestsMock, mutator: Mutator, sleeps: list[float]
) -> None:
    """405 is retried 3 times 5 s apart; 409 with a sha fails at once."""
    url = f"{REPO}/pulls/5/merge"
    api.add(responses.PUT, url, status=405, json={"message": "Pull Request is not mergeable"})
    api.add(responses.PUT, url, status=405, json={"message": "Pull Request is not mergeable"})
    api.add(responses.PUT, url, json={"merged": True, "sha": COMMIT, "message": "Pull Request successfully merged"})
    assert mutator.merge_pull("r", 5)["merged"] is True
    assert body(api.calls[0]) == {"merge_method": "squash"}
    assert sleeps == [5.0, 5.0]
    api.add(responses.PUT, f"{REPO}/pulls/6/merge", status=409, json={"message": "Head branch was modified"})
    with pytest.raises(GitHubError) as info:
        mutator.merge_pull("r", 6, sha=HEAD)
    assert info.value.status == 409 and sleeps == [5.0, 5.0]
    assert body(api.calls[-1]) == {"merge_method": "squash", "sha": HEAD}


def test_merge_pull_gives_up_after_3_retries(
    api: responses.RequestsMock, mutator: Mutator, sleeps: list[float]
) -> None:
    """After 3 retries the 405 surfaces."""
    api.add(responses.PUT, f"{REPO}/pulls/5/merge", status=405, json={"message": "Pull Request is not mergeable"})
    with pytest.raises(GitHubError):
        mutator.merge_pull("r", 5, method="merge")
    assert sleeps == [5.0, 5.0, 5.0] and len(api.calls) == 4


# --- repositories, org ---------------------------------------------------------------------------------------------
def test_patch_repo_guards_protected_repos(api: responses.RequestsMock, mutator: Mutator) -> None:
    """Renaming/archiving/visibility changes are refused on non-e2e repos; descriptions are fine."""
    api.add(
        responses.PATCH, f"{GITHUB_API}/repos/{FAKE_ORG}/.otterdog", json={"name": ".otterdog", "description": "drift"}
    )
    api.add(responses.PATCH, f"{GITHUB_API}/repos/{FAKE_ORG}/{P}-x", json={"name": f"{P}-x", "archived": True})
    with pytest.raises(SafetyError):
        mutator.patch_repo(".otterdog", archived=True)
    with pytest.raises(SafetyError):
        mutator.patch_repo(".otterdog", visibility="private")
    assert mutator.patch_repo(".otterdog", description="drift")["description"] == "drift"
    assert mutator.patch_repo(f"{P}-x", archived=True)["archived"] is True


def test_create_repo_and_org_calls(api: responses.RequestsMock, mutator: Mutator) -> None:
    """create_repo, pings, set_org_description payloads."""
    api.add(responses.POST, f"{ORG}/repos", status=201, json={"name": f"{P}-r", "default_branch": "main"})
    api.add(responses.POST, f"{REPO}/hooks/3/pings", status=204, headers={"Date": "Sat, 03 Oct 2026 10:00:00 GMT"})
    api.add(responses.POST, f"{ORG}/hooks/4/pings", status=204, headers={"Date": "Sat, 03 Oct 2026 10:00:07 GMT"})
    api.add(responses.PATCH, ORG, json={"description": "[otterdog-e2e] x"})
    assert mutator.create_repo(f"{P}-r", description="d")["name"] == f"{P}-r"
    assert body(api.calls[0]) == {"name": f"{P}-r", "private": False, "description": "d", "auto_init": True}
    # BAT-10: a ping returns GitHub's time of the request (its Date header), not the local clock
    assert mutator.ping_repo_hook("r", 3) == datetime(2026, 10, 3, 10, 0, 0, tzinfo=UTC)
    assert mutator.ping_org_hook(4) == datetime(2026, 10, 3, 10, 0, 7, tzinfo=UTC)
    mutator.set_org_description("[otterdog-e2e] x")
    assert body(api.calls[-1]) == {"description": "[otterdog-e2e] x"}


def test_ensure_membership_never_demotes(api: responses.RequestsMock, mutator: Mutator) -> None:
    """An existing membership is returned unchanged; otherwise PUT role member."""
    api.add(responses.GET, f"{ORG}/memberships/owner", json={"state": "active", "role": "admin"})
    api.add(responses.GET, f"{ORG}/memberships/newbie", status=404, json={"message": "Not Found"})
    api.add(responses.PUT, f"{ORG}/memberships/newbie", json={"state": "pending", "role": "member"})
    assert mutator.ensure_membership("owner")["role"] == "admin"
    assert mutator.ensure_membership("newbie")["state"] == "pending"
    assert [c.request.method for c in api.calls] == ["GET", "GET", "PUT"]
    assert body(api.calls[-1]) == {"role": "member"}


def test_identity_side_helpers(api: responses.RequestsMock) -> None:
    """Accepting an invitation and publicizing a membership use the identity's own write-scoped client."""
    verified = make_verified_org()
    http = GitHubHttp(TOKEN, write_scope=verified, min_write_interval=0.0)
    api.add(responses.PATCH, f"{GITHUB_API}/user/memberships/orgs/{FAKE_ORG}", json={"state": "active"})
    api.add(responses.PUT, f"{ORG}/public_members/bot", status=204)
    assert accept_org_invitation(http, verified)["state"] == "active"
    assert body(api.calls[0]) == {"state": "active"}
    publicize_membership(http, verified, "bot")
    assert api.calls[1].request.method == "PUT"


def test_dry_run_never_writes(api: responses.RequestsMock) -> None:
    """dry_run: guards still apply, writes are only logged and return placeholders."""
    verified = make_verified_org()
    mutator = Mutator(GitHubHttp(TOKEN, read_only=True), verified, dry_run=True)
    assert mutator.commit_files("r", "main", {"a": "1"}, "m") == DRY_RUN_SHA
    assert mutator.create_commit("r", tree_sha=TREE, parents=[HEAD], message="m") == DRY_RUN_SHA
    assert mutator.create_ref("r", "heads/e2e-lease", HEAD)["dry_run"] is True
    assert mutator.create_pull("r", head="h", base="main", title="t")["dry_run"] is True
    mutator.delete_repo(f"{P}-x")
    mutator.delete_ref("r", f"heads/e2e/{FAKE_RUN_ID}/x")
    mutator.close_pull("r", 1)
    with pytest.raises(SafetyError):
        mutator.delete_repo(".otterdog")
    assert len(api.calls) == 0
