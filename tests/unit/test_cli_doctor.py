"""Harness CLI doctor (SPEC 16): every check reported as OK/WARN/FAIL with a remediation, exit 1 on FAIL."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_e2e import cli
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import AppCredentials, Target, TargetError
from otterdog_e2e.testing.fakes import (
    FAKE_LOGINS,
    FAKE_MARKER,
    FAKE_ORG,
    FakeAppAuth,
    FakeGitHubHttp,
    FakeOracle,
    default_org_json,
    make_identities,
    make_settings,
    make_target,
    make_verified_org,
)

ROLES = ("admin", "author", "approver", "outsider", "config_reader")


@dataclass
class World:
    """Everything the doctor can see."""

    target: Target = field(default_factory=make_target)
    identities: dict[str, Any] = field(default_factory=lambda: make_identities(*ROLES))
    oracle: FakeOracle = field(default_factory=FakeOracle)
    app: FakeAppAuth = field(default_factory=FakeAppAuth)
    https: dict[str, FakeGitHubHttp] = field(default_factory=dict)
    description: str = f"{FAKE_MARKER} test org"
    isolation_errors: dict[str, str] = field(default_factory=dict)
    target_error: str | None = None
    docker: bool = True
    unshare: bool = True

    def http(self, name: str, *, login: str | None = None, scopes: set[str] | None = None) -> FakeGitHubHttp:
        """(Re)create the client of an identity: GET /user and public memberships answer."""
        client = FakeGitHubHttp(identity=name, scopes=scopes, read_only=True)
        client.add("GET", "/user", json={"login": login or FAKE_LOGINS[name]}, repeat=True)
        client.add("GET", f"/orgs/{FAKE_ORG}/public_members/*", status=204, repeat=True)
        self.https[name] = client
        return client


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A healthy test org, App and environment."""
    world = World()
    world.http("admin", scopes=set(cli.REQUIRED_ADMIN_SCOPES) | {"read:org"})
    for name in ("author", "approver", "outsider"):
        world.http(name, scopes={"public_repo"})
    world.http("config_reader", scopes=None)
    for name in ("author", "approver"):
        world.oracle.set("membership", FAKE_LOGINS[name], value={"state": "active", "role": "member"})
    world.oracle.add_team("otterdog-admins", members=["e2e-admin"])
    world.oracle.add_team("project-leads", members=["e2e-approver"])
    world.oracle.add_team("e2e-contributors", members=["e2e-author"])
    for repo in ("otterdog-e2e-configs", "otterdog-e2e-defaults", "otterdog-e2e-fixture-a"):
        world.oracle.add_repo(repo)
    world.app.add_delivery("push", {"organization": {"login": FAKE_ORG}}, delivered_at=datetime.now(UTC))

    def load_target(*args: Any, **kwargs: Any) -> Target:
        """The world's target (or a TargetError)."""
        if world.target_error:
            raise TargetError(world.target_error)
        return world.target

    def isolation(http: Any, *, role: str, allowed_org_ids: Any, test_org_id: int) -> None:
        """SafetyError for configured roles."""
        if role in world.isolation_errors:
            raise SafetyError(world.isolation_errors[role])

    def verify(admin_http: Any, target: Any, identities: Any, **kwargs: Any) -> Any:
        """VerifiedOrg whose description is the world's."""
        return make_verified_org(org_json={**default_org_json(), "description": world.description})

    credentials = AppCredentials("1", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----", "hook-secret", None)
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path))
    monkeypatch.setattr("otterdog_e2e.settings.load_env_files", lambda *a, **k: [])
    monkeypatch.setattr("otterdog_e2e.settings.load_target", load_target)
    monkeypatch.setattr("otterdog_e2e.settings.resolve_identities", lambda *a, **k: dict(world.identities))
    monkeypatch.setattr("otterdog_e2e.settings.resolve_app_credentials", lambda *a, **k: credentials)
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", lambda token, **kw: world.https[kw["identity"]])
    monkeypatch.setattr("otterdog_e2e.safety.check_identity_isolation", isolation)
    monkeypatch.setattr("otterdog_e2e.safety.verify_target", verify)
    monkeypatch.setattr("otterdog_e2e.github.oracle.Oracle", lambda http, org: world.oracle)
    monkeypatch.setattr("otterdog_e2e.github.app.AppAuth", lambda creds, **kw: world.app)
    monkeypatch.setattr("otterdog_e2e.sut.image.docker_available", lambda: world.docker)
    monkeypatch.setattr("otterdog_e2e.procs.unshare_available", lambda: world.unshare)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    return world


def doctor_json(*extra: str) -> tuple[int, dict[str, Any]]:
    """Run ``doctor --json`` and return (exit code, rows by name)."""
    result = CliRunner().invoke(cli.main, ["doctor", "--target", "fake", "--json", *extra])
    data = json.loads(result.stdout)
    return result.exit_code, {row["name"]: row for row in data["checks"]} | {"_ok": data["ok"]}


def statuses(rows: dict[str, Any]) -> dict[str, str]:
    """Status per check name."""
    return {name: row["status"] for name, row in rows.items() if not name.startswith("_")}


def test_healthy_org_passes(world: World) -> None:
    """Every check OK: exit 0, the table lists them."""
    code, rows = doctor_json()
    assert code == 0 and rows["_ok"] is True, [
        row for row in rows.values() if isinstance(row, dict) and row["status"] != "OK"
    ]
    status = statuses(rows)
    assert not [name for name, value in status.items() if value == "FAIL"], status
    for name in (
        "target",
        "env:admin",
        "identity:admin",
        "isolation:admin",
        "scopes:admin",
        "scopes:config_reader",
        "org",
        "org:marker",
        "membership:author",
        "membership:approver",
        "membership:outsider",
        "team:project-leads",
        "repo:otterdog-e2e-configs",
        "app:owner",
        "app:installation",
        "app:webhook",
        "app:deliveries",
        "docker",
        "unshare",
    ):
        assert status[name] == "OK", (name, rows[name])
    table = CliRunner().invoke(cli.main, ["doctor", "--target", "fake"])
    assert table.exit_code == 0 and "STATUS" in table.output and "0 failure(s)" in table.output


def test_missing_marker_fails_with_bootstrap_hint(world: World) -> None:
    """No safety marker: FAIL with the bootstrap remediation, exit 1."""
    world.description = "a real org?"
    code, rows = doctor_json()
    assert code == 1 and rows["org:marker"]["status"] == "FAIL"
    assert "bootstrap --target fake --apply" in rows["org:marker"]["remediation"]
    table = CliRunner().invoke(cli.main, ["doctor", "--target", "fake"])
    assert table.exit_code == 1 and "fix: run `otterdog-e2e bootstrap" in table.output


def test_identity_problems(world: World) -> None:
    """Wrong account behind a token, isolation violations and bad token kinds fail."""
    world.http("author", login="someone-else", scopes={"public_repo"})
    world.isolation_errors["approver"] = "approver belongs to org 99 (eclipse)"
    world.http("config_reader", scopes={"repo"})
    world.https["admin"].scopes = {"repo"}
    _code, rows = doctor_json()
    assert rows["identity:author"]["status"] == "FAIL" and "someone-else" in rows["identity:author"]["detail"]
    assert rows["isolation:approver"]["status"] == "FAIL"
    assert rows["scopes:config_reader"]["status"] == "FAIL" and "classic" in rows["scopes:config_reader"]["detail"]
    assert rows["scopes:admin"]["status"] == "FAIL" and "admin:org" in rows["scopes:admin"]["detail"]


def test_admin_isolation_failure_stops_org_checks(world: World) -> None:
    """When the admin identity is unusable nothing org-related is queried."""
    world.isolation_errors["admin"] = "admin owns eclipse-csi"
    code, rows = doctor_json()
    assert code == 1 and rows["isolation:admin"]["status"] == "FAIL"
    assert "org" not in rows and "team:project-leads" not in rows


def test_org_state_problems(world: World) -> None:
    """Pending/private memberships, members outsider, missing teams/repos, private repos, wrong branch."""
    world.oracle.set("membership", "e2e-author", value={"state": "pending"})
    world.https["admin"].routes.pop(("GET", f"/orgs/{FAKE_ORG}/public_members/*"))
    world.https["admin"].add("GET", f"/orgs/{FAKE_ORG}/public_members/*", status=404, repeat=True)
    world.oracle.set("membership", "e2e-outsider", value={"state": "active", "role": "member"})
    world.oracle.remove_team("project-leads")
    world.oracle.set("team_members", "e2e-contributors", value=[])
    world.oracle.remove_repo("otterdog-e2e-defaults")
    world.oracle.remove_repo("otterdog-e2e-fixture-a")
    world.oracle.add_repo("otterdog-e2e-fixture-a", private=True, default_branch="master")
    world.oracle.add_repo("real-project")
    world.oracle.add_team("maintainers")
    code, rows = doctor_json()
    assert code == 1
    status = statuses(rows)
    assert status["membership:author"] == "FAIL" and "pending" in rows["membership:author"]["detail"]
    assert status["membership:approver"] == "FAIL" and "private" in rows["membership:approver"]["detail"]
    assert status["membership:outsider"] == "FAIL"
    assert status["team:project-leads"] == "FAIL" and status["team:e2e-contributors"] == "WARN"
    assert status["repo:otterdog-e2e-defaults"] == "FAIL"
    assert status["repo:otterdog-e2e-fixture-a"] == "FAIL"
    assert (
        "not public" in rows["repo:otterdog-e2e-fixture-a"]["detail"]
        and "master" in rows["repo:otterdog-e2e-fixture-a"]["detail"]
    )
    assert status["unmanaged:repos"] == "WARN" and "real-project" in rows["unmanaged:repos"]["detail"]
    assert status["unmanaged:teams"] == "WARN" and "maintainers" in rows["unmanaged:teams"]["detail"]


def test_app_problems(world: World) -> None:
    """Installation not on all repos, missing permissions, loopback hook and stale deliveries."""
    world.app = FakeAppAuth(
        repository_selection="selected", permissions={"contents": "read"}, hook_url="http://127.0.0.1:5000/hook"
    )
    world.app.add_delivery("push", {}, delivered_at=datetime.now(UTC) - timedelta(days=5))
    _code, rows = doctor_json()
    assert rows["app:installation"]["status"] == "FAIL"
    assert (
        "repository_selection" in rows["app:installation"]["detail"]
        and "permissions missing" in rows["app:installation"]["detail"]
    )
    assert rows["app:webhook"]["status"] == "FAIL" and "127.0.0.1" in rows["app:webhook"]["detail"]
    assert rows["app:deliveries"]["status"] == "WARN"


def test_app_owner_and_missing_installation(world: World) -> None:
    """An App owned elsewhere or not installed fails."""
    world.app = FakeAppAuth(org="other-org")
    _code, rows = doctor_json()
    assert rows["app:owner"]["status"] == "FAIL" and rows["app:installation"]["status"] == "FAIL"


def test_app_installed_on_a_foreign_org_fails_the_isolation_row(world: World) -> None:
    """DESTR-01: doctor's app:owner row is safety.verify_app (owner AND every installation)."""
    foreign = {"id": 9, "account": {"login": "acme-production", "id": 99, "type": "Organization"}}
    world.app = FakeAppAuth(extra_installations=[foreign])
    code, rows = doctor_json()
    assert code == 1 and rows["app:owner"]["status"] == "FAIL" and "acme-production" in rows["app:owner"]["detail"]
    world.app = FakeAppAuth()
    _code, rows = doctor_json()
    assert rows["app:owner"]["status"] == "OK" and "installed on: e2e-test-org" in rows["app:owner"]["detail"]


def test_missing_tokens_and_tools(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Declared identities without tokens WARN; docker WARN; unshare FAIL in CI."""
    world.identities = make_identities("admin")
    world.docker = False
    world.unshare = False
    monkeypatch.setenv("CI", "true")
    _code, rows = doctor_json()
    assert rows["env:author"]["status"] == "WARN" and "E2E_AUTHOR_TOKEN" in rows["env:author"]["detail"]
    assert rows["docker"]["status"] == "WARN" and rows["unshare"]["status"] == "FAIL"


def test_missing_admin_token(world: World) -> None:
    """Without the admin token only local checks run."""
    world.identities = {}
    code, rows = doctor_json()
    assert code == 1 and rows["env:admin"]["status"] == "FAIL" and "org" not in rows


def test_target_errors_stop_early(world: World) -> None:
    """An invalid target is the only (FAIL) row."""
    world.target_error = "E2E_ORG_ID is not set"
    code, rows = doctor_json()
    assert code == 1 and statuses(rows) == {"target": "FAIL"} and "E2E_ORG_ID" in rows["target"]["detail"]


def test_url_template_should_be_pinned(world: World) -> None:
    """url templates not pinned to a commit WARN (SEC-12)."""
    world.target = make_target(template_mode="url", template_url="https://github.com/o/r#t.libsonnet@main")
    _code, rows = doctor_json()
    assert rows["template"]["status"] == "WARN"


def test_render_rows_layout() -> None:
    """Fix lines only under WARN/FAIL rows; totals at the end."""
    rows = [cli.CheckRow("a", "OK", "fine", "unused"), cli.CheckRow("longer-name", "FAIL", "broken", "repair it")]
    text = cli.render_rows(rows)
    assert "unused" not in text and "fix: repair it" in text and text.endswith("1 ok, 0 warning(s), 1 failure(s)")
