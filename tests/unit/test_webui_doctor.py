"""doctor's web-UI checks (cli.doctor.Doctor.check_web): credentials, SAML SSO, Playwright browser, login gate, bot
2FA; the doctor never logs in and never fails a target without web credentials."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_e2e import cli
from otterdog_e2e.cli import doctor as cli_doctor
from otterdog_e2e.settings import AppCredentials, Target
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
from otterdog_e2e.webui.gate import GATE_DIR, LoginGate

SEED = "JBSWY3DPEHPK3PXP"


class World:
    """A healthy org whose admin bot answers GET /user with its 2FA state."""

    def __init__(self, tmp_path: Path) -> None:
        """Healthy defaults."""
        self.tmp_path = tmp_path
        self.target: Target = make_target()
        self.two_factor: bool | None = True
        self.oracle = FakeOracle()
        self.app = FakeAppAuth()
        self.app.add_delivery("push", {"organization": {"login": FAKE_ORG}}, delivered_at=datetime.now(UTC))
        for repo in ("otterdog-e2e-configs", "otterdog-e2e-defaults", "otterdog-e2e-fixture-a"):
            self.oracle.add_repo(repo)
        self.oracle.add_team("otterdog-admins", members=["e2e-admin"])
        self.oracle.add_team("project-leads", members=["e2e-approver"])
        self.oracle.add_team("e2e-contributors", members=["e2e-author"])
        for name in ("author", "approver"):
            self.oracle.set("membership", FAKE_LOGINS[name], value={"state": "active", "role": "member"})

    def http(self, token: str | None, **kwargs: Any) -> FakeGitHubHttp:
        """The admin client: GET /user (with two_factor_authentication) and public memberships."""
        client = FakeGitHubHttp(
            identity=kwargs["identity"], scopes=set(cli_doctor.REQUIRED_ADMIN_SCOPES), read_only=True
        )
        user: dict[str, Any] = {"login": FAKE_LOGINS["admin"]}
        if self.two_factor is not None:
            user["two_factor_authentication"] = self.two_factor
        client.add("GET", "/user", json=user, repeat=True)
        client.add("GET", f"/orgs/{FAKE_ORG}/public_members/*", status=204, repeat=True)
        return client


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """Doctor collaborators replaced by fakes (only the admin identity is configured)."""
    world = World(tmp_path)
    credentials = AppCredentials("1", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----", "hook-secret", None)
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path))
    monkeypatch.setattr("otterdog_e2e.settings.load_env_files", lambda *a, **k: [])
    monkeypatch.setattr("otterdog_e2e.settings.load_target", lambda *a, **k: world.target)
    monkeypatch.setattr("otterdog_e2e.settings.resolve_identities", lambda *a, **k: make_identities("admin"))
    monkeypatch.setattr("otterdog_e2e.settings.resolve_app_credentials", lambda *a, **k: credentials)
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", world.http)
    monkeypatch.setattr("otterdog_e2e.safety.check_identity_isolation", lambda *a, **k: None)
    org_json = {**default_org_json(), "description": f"{FAKE_MARKER} test org"}
    monkeypatch.setattr("otterdog_e2e.safety.verify_target", lambda *a, **k: make_verified_org(org_json=org_json))
    monkeypatch.setattr("otterdog_e2e.github.oracle.Oracle", lambda http, org: world.oracle)
    monkeypatch.setattr("otterdog_e2e.github.app.AppAuth", lambda creds, **kw: world.app)
    monkeypatch.setattr("otterdog_e2e.sut.image.docker_available", lambda: True)
    monkeypatch.setattr("otterdog_e2e.procs.unshare_available", lambda: True)
    for name in ("CI", "GITHUB_ACTIONS", "E2E_ADMIN_PASSWORD", "E2E_ADMIN_TOTP_SEED", "E2E_ADMIN_USERNAME"):
        monkeypatch.delenv(name, raising=False)
    return world


def rows() -> tuple[int, dict[str, dict[str, Any]]]:
    """Run ``doctor --json``: exit code and rows by name."""
    result = CliRunner().invoke(cli.main, ["doctor", "--target", "fake", "--json"])
    data = json.loads(result.stdout)
    return result.exit_code, {row["name"]: row for row in data["checks"]}


def configure(monkeypatch: pytest.MonkeyPatch, **values: str) -> None:
    """Set the admin bot's web credentials."""
    monkeypatch.setenv("E2E_ADMIN_PASSWORD", values.get("password", "bot-pw-0123456789"))
    monkeypatch.setenv("E2E_ADMIN_TOTP_SEED", values.get("seed", SEED))


def test_without_web_credentials_the_tier_is_simply_off(world: World) -> None:
    """One OK row, no web check fails, nothing about browsers or the gate."""
    code, found = rows()
    assert code == 0, [row for row in found.values() if row["status"] == "FAIL"]
    assert found["web"]["status"] == "OK" and "web-UI tier off" in found["web"]["detail"]
    assert not {"web:credentials", "web:browser", "web:gate", "web:2fa"} & set(found)


def test_configured_web_credentials(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Credentials OK, browser missing (WARN), gate OK, the bot's 2FA enabled."""
    configure(monkeypatch)
    code, found = rows()
    assert code == 0, [row for row in found.values() if row["status"] == "FAIL"]
    assert found["web:credentials"]["status"] == "OK" and "e2e-admin" in found["web:credentials"]["detail"]
    assert found["web:browser"]["status"] == "WARN" and "install-deps" in found["web:browser"]["remediation"]
    assert found["web:gate"]["status"] == "OK" and "no web login yet" in found["web:gate"]["detail"]
    assert found["web:2fa"]["status"] == "OK"
    assert "bot-pw-0123456789" not in json.dumps(found) and SEED not in json.dumps(found)


def test_web_problems(world: World, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """2FA disabled FAILs; SAML SSO WARNs; a blocked gate FAILs with the file to delete; an installed browser is OK."""
    configure(monkeypatch)
    world.two_factor = False
    world.target = make_target(saml_sso=True)
    settings = make_settings(tmp_path)
    (settings.cache_dir / "ms-playwright" / "firefox-1538").mkdir(parents=True)
    LoginGate(settings.cache_dir / GATE_DIR, account="e2e-admin").block("lockout: throttled")
    code, found = rows()
    assert code == 1
    assert found["web:2fa"]["status"] == "FAIL" and "authenticator app" in found["web:2fa"]["remediation"]
    assert found["web:sso"]["status"] == "WARN"
    assert found["web:gate"]["status"] == "FAIL" and "e2e-admin.json" in found["web:gate"]["remediation"]
    assert found["web:browser"]["status"] == "OK" and "firefox-1538" in found["web:browser"]["detail"]


def test_invalid_or_partial_web_credentials_fail(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A seed that is not base32, or a password without seed: FAIL naming the variable, never the value."""
    configure(monkeypatch, seed="not-a-seed")
    code, found = rows()
    assert code == 1 and found["web:credentials"]["status"] == "FAIL"
    assert "E2E_ADMIN_TOTP_SEED" in found["web:credentials"]["detail"]
    monkeypatch.delenv("E2E_ADMIN_TOTP_SEED")
    _code, found = rows()
    assert "E2E_ADMIN_TOTP_SEED is not set" in found["web:credentials"]["detail"]


def test_unknown_two_factor_state_warns(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /user without two_factor_authentication (token without user scope): WARN, not FAIL."""
    configure(monkeypatch)
    world.two_factor = None
    _code, found = rows()
    assert found["web:2fa"]["status"] == "WARN"
