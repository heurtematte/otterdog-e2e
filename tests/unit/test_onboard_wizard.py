"""``otterdog-e2e setup`` (onboard.wizard.SetupWizard): every flow with injected I/O and fake GitHub clients; the
instance env file is real (tmp HOME) and checked with settings.parse_env_text."""

from __future__ import annotations

import functools
import os
import shutil
import stat
import types
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_e2e import appmanifest, cli
from otterdog_e2e.appmanifest import DEFAULT_EVENTS, DEFAULT_PERMISSIONS
from otterdog_e2e.onboard.wizard import SetupError, SetupOptions, SetupWizard, WizardIO
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import HarnessSettings, Target, parse_env_text
from otterdog_e2e.testing.fakes import FakeGitHubHttp, make_settings

ROOT = Path(__file__).resolve().parents[2]
ORG, ORG_ID = "e2e-test-org", 424242
OTHER_ORG_ID = 515151
ADMIN_SCOPES = {"repo", "workflow", "admin:org", "admin:org_hook", "delete_repo"}
MEMBER_SCOPES = {"public_repo", "read:org"}
# token-shaped but no pattern of the Redactor matches them: only their registration keeps them out of the output
TOKENS = {
    "admin": "tokadmin_1111111111111111",
    "oracle": "tokoracle_2222222222222222",
    "author": "tokauthor_3333333333333333",
    "approver": "tokapprover_44444444444444",
    "outsider": "tokoutsider_55555555555555",
    "config_reader": "tokreader_6666666666666666",
}
PASSWORD = "correct horse battery staple"
SEED = "JBSW Y3DP EHPK 3PXP"  # base32 with blanks: normalized to JBSWY3DPEHPK3PXP
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEfakekeymaterial0123456789\n-----END RSA PRIVATE KEY-----\n"
WEBHOOK_SECRET = "whsec-0123456789abcdef"
INSTALLATION = {
    "id": 777,
    "repository_selection": "all",
    "permissions": dict(DEFAULT_PERMISSIONS),
    "events": list(DEFAULT_EVENTS),
}


@dataclass
class Account:
    """A machine account behind a token: what GET /user, the token info and its memberships answer."""

    login: str
    scopes: set[str] | None  # None: fine-grained
    orgs: list[int] = field(default_factory=list)  # GET /user/orgs (classic tokens)
    membership: dict[str, Any] | None = None  # GET /user/memberships/orgs/{org}
    owner_probes: bool = False  # fine-grained owner reads answer 200
    valid: bool = True


def owner() -> dict[str, Any]:
    """An active owner membership of the test org."""
    return {"state": "active", "role": "admin", "organization": {"id": ORG_ID, "login": ORG}}


def member() -> dict[str, Any]:
    """An active plain membership of the test org."""
    return {"state": "active", "role": "member", "organization": {"id": ORG_ID, "login": ORG}}


def default_accounts() -> dict[str, Account]:
    """Valid accounts of every role, keyed by token."""
    return {
        TOKENS["admin"]: Account("e2e-admin", set(ADMIN_SCOPES), [ORG_ID], owner()),
        TOKENS["oracle"]: Account("e2e-oracle", None, [], owner(), owner_probes=True),
        TOKENS["author"]: Account("e2e-author", set(MEMBER_SCOPES)),
        TOKENS["approver"]: Account("e2e-approver", set(MEMBER_SCOPES)),
        TOKENS["outsider"]: Account("e2e-outsider", set(MEMBER_SCOPES)),
        TOKENS["config_reader"]: Account("e2e-reader", None),
    }


def app_owner_of_the_test_org() -> dict[str, Any]:
    """GET /app owner of an App created in the test org."""
    return {"type": "Organization", "id": ORG_ID, "login": ORG}


class FakeApp:
    """AppAuth stand-in: installation_for_org answers from a queue (the last answer repeats); GET /app names
    ``owner``, GET /app/installations lists nothing."""

    def __init__(self, answers: list[dict[str, Any] | None], owner: dict[str, Any]) -> None:
        """Queue of GET /orgs/{org}/installation answers and the App's owner."""
        self.answers = answers
        self.owner = owner
        self.calls = 0
        self.verified = 0
        self.slug = "otterdog-e2e-e2e-test-org"

    def get_app(self, refresh: bool = False) -> dict[str, Any]:
        """GET /app."""
        self.verified += 1
        return {"id": 4242, "slug": self.slug, "owner": dict(self.owner), "installations_count": 0}

    def installations(self) -> list[dict[str, Any]]:
        """GET /app/installations."""
        return []

    def installation_for_org(self, org: str) -> dict[str, Any] | None:
        """Next queued answer."""
        self.calls += 1
        return self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]


@dataclass
class World:
    """The fake GitHub, the tmp HOME and the project profiles the wizard sees."""

    tmp: Path
    accounts: dict[str, Account] = field(default_factory=default_accounts)
    org: dict[str, Any] = field(
        default_factory=lambda: {"login": ORG, "id": ORG_ID, "plan": {"name": "free"}, "description": "scratch"}
    )
    missing_org_checks: int = 0  # anonymous GET /orgs/{org} answers 404 this many times first
    environ: dict[str, str] = field(default_factory=dict)
    settings: HarnessSettings | None = None
    clients: list[FakeGitHubHttp] = field(default_factory=list)
    manifest_calls: list[tuple[str, str]] = field(default_factory=list)
    installations: list[dict[str, Any] | None] = field(default_factory=lambda: [dict(INSTALLATION)])
    app_owner: dict[str, Any] = field(default_factory=app_owner_of_the_test_org)
    app: FakeApp | None = None
    bootstraps: list[str] = field(default_factory=list)
    doctors: list[str] = field(default_factory=list)
    bootstrap_sets_marker: bool = True
    memberships: dict[str, dict[str, Any]] = field(default_factory=dict)  # GET /orgs/{org}/memberships/{login}
    invites: list[tuple[str, Any]] = field(default_factory=list)  # PUT /orgs/{org}/memberships/{login} bodies
    cancelled: list[str] = field(default_factory=list)  # DELETE /orgs/{org}/memberships/{login}
    accepts_invitations: bool = True  # a pending invitation is active at the next poll
    other_orgs: dict[str, dict[str, Any]] = field(default_factory=dict)  # GET /orgs/{login} of other test orgs

    def http(self, token: str | None, identity: str) -> FakeGitHubHttp:
        """A fake client per call: anonymous org reads, or the account behind ``token``."""
        if token is None:
            client = FakeGitHubHttp(identity=identity, read_only=True)

            def org_answer(call: Any) -> tuple[int, Any]:
                """404 while the org is "not created yet", then the public org."""
                if self.missing_org_checks > 0:
                    self.missing_org_checks -= 1
                    return 404, {"message": "Not Found"}
                return 200, {key: self.org[key] for key in ("login", "id", "description")}

            client.add("GET", "/orgs/*", responder=org_answer, repeat=True)
            self.clients.append(client)
            return client
        account = self.accounts.get(token)
        client = FakeGitHubHttp(identity=identity, scopes=account.scopes if account else None, read_only=True)
        if account is None or not account.valid:
            client.add("GET", "/user", status=401, json={"message": "Bad credentials"}, repeat=True)
            return client
        client.add("GET", "/user", json={"login": account.login, "id": 1}, repeat=True)
        client.add("GET", "/user/orgs", json=[{"id": oid, "login": f"org-{oid}"} for oid in account.orgs], repeat=True)
        client.add("GET", "/user/memberships/orgs", json=[], repeat=True)
        if account.membership is not None:
            client.add("GET", f"/user/memberships/orgs/{ORG}", json=account.membership, repeat=True)
        else:
            client.add("GET", f"/user/memberships/orgs/{ORG}", status=404, json={"message": "Not Found"}, repeat=True)
        client.add("GET", f"/orgs/{ORG}", responder=lambda call: (200, dict(self.org)), repeat=True)
        for login, data in self.other_orgs.items():
            client.add("GET", f"/orgs/{login}", responder=lambda call, data=data: (200, dict(data)), repeat=True)
        client.add("GET", f"/orgs/{ORG}/memberships/*", responder=self.membership_answer, repeat=True)
        client.add("GET", "/users/*", responder=self.user_answer, repeat=True)
        status = 200 if account.owner_probes else 403
        for path in (f"/orgs/{ORG}/actions/permissions", f"/orgs/{ORG}/hooks"):
            client.add("GET", path, status=status, json={}, repeat=True)
        self.clients.append(client)
        return client

    def membership_answer(self, call: Any) -> tuple[int, Any]:
        """The admin's view of a membership; a pending one turns active once it was seen (the account accepts)."""
        login = call.path.rsplit("/", 1)[1]
        membership = self.memberships.get(login)
        if membership is None:
            return 404, {"message": "Not Found"}
        answer = dict(membership)
        if membership["state"] == "pending" and self.accepts_invitations:
            membership["state"] = "active"
        return 200, answer

    def user_answer(self, call: Any) -> tuple[int, Any]:
        """GET /users/{login}: the accounts of the world are users, ``some-org`` an organization."""
        login = call.path.rsplit("/", 1)[1]
        if login == "some-org":
            return 200, {"login": login, "type": "Organization"}
        logins = {account.login.lower(): account.login for account in self.accounts.values()}
        if login.lower() not in logins:
            return 404, {"message": "Not Found"}
        return 200, {"login": logins[login.lower()], "type": "User"}

    def write_http(self, token: str, verified: Any) -> FakeGitHubHttp:
        """The admin's write-scoped client: invitations become pending memberships."""
        assert token == TOKENS["admin"] and verified.login == ORG and verified.org_id == ORG_ID
        client = FakeGitHubHttp(identity="admin", write_scope=verified)

        def invite(call: Any) -> tuple[int, Any]:
            """PUT /orgs/{org}/memberships/{login}."""
            login = call.path.rsplit("/", 1)[1]
            self.invites.append((login, call.json))
            self.memberships[login] = {"state": "pending", "role": call.json["role"]}
            return 200, dict(self.memberships[login])

        def cancel(call: Any) -> tuple[int, Any]:
            """DELETE /orgs/{org}/memberships/{login}."""
            login = call.path.rsplit("/", 1)[1]
            self.cancelled.append(login)
            self.memberships.pop(login, None)
            return 204, None

        client.add("PUT", f"/orgs/{ORG}/memberships/*", responder=invite, repeat=True)
        client.add("DELETE", f"/orgs/{ORG}/memberships/*", responder=cancel, repeat=True)
        return client

    def run_manifest(self, target: Target, webhook_url: str) -> str:
        """The browser click: the manifest code."""
        self.manifest_calls.append((target.org, webhook_url))
        return "manifestcode1234"

    def app_auth(self, credentials: Any) -> FakeApp:
        """The App's JWT client."""
        assert credentials.private_key_pem.startswith("-----BEGIN") and credentials.webhook_secret
        self.app = FakeApp(self.installations, self.app_owner)
        return self.app

    def bootstrap(self, instance: str) -> None:
        """bootstrap --apply: adds the marker."""
        self.bootstraps.append(instance)
        if self.bootstrap_sets_marker:
            self.org["description"] = "[otterdog-e2e] scratch"

    def doctor(self, instance: str) -> None:
        """doctor."""
        self.doctors.append(instance)

    @property
    def config_dir(self) -> Path:
        """~/.config/otterdog-e2e of the tmp HOME."""
        return Path(self.environ["HOME"]) / ".config" / "otterdog-e2e"

    def env(self, instance: str = "org2") -> dict[str, str]:
        """Values of an instance env file."""
        path = self.config_dir / f"{instance}.env"
        return parse_env_text(path.read_text()) if path.is_file() else {}

    def write_env(self, instance: str, text: str) -> Path:
        """Create an instance env file (0600)."""
        path = self.config_dir / f"{instance}.env"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        path.chmod(0o600)
        return path


@dataclass
class Script:
    """Scripted answers: hidden prompts and prompts in order, confirmations by substring (else their default)."""

    secrets: list[str] = field(default_factory=list)
    answers: list[str] = field(default_factory=list)
    confirms: dict[str, bool] = field(default_factory=dict)
    echoed: list[str] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    now: float = 0.0

    DEFAULTS = {"Set up the": False, "Create the GitHub App": False, "bootstrap": False, "doctor": False}

    def secret_prompt(self, text: str) -> str:
        """Next hidden answer (an exhausted script is a test failure)."""
        self.asked.append(text)
        assert self.secrets, f"unexpected hidden prompt: {text}"
        return self.secrets.pop(0)

    def prompt(self, text: str, default: str | None) -> str:
        """Next visible answer."""
        self.asked.append(text)
        assert self.answers, f"unexpected prompt: {text}"
        return self.answers.pop(0)

    def confirm(self, text: str, default: bool) -> bool:
        """The first matching rule (test rules first, then DEFAULTS), else the question's default."""
        self.asked.append(text)
        for rules in (self.confirms, self.DEFAULTS):
            for needle, answer in rules.items():
                if needle in text:
                    return answer
        return default

    def sleep(self, seconds: float) -> None:
        """Advance the fake clock."""
        self.now += seconds

    def io(self) -> WizardIO:
        """The WizardIO of this script."""
        return WizardIO(
            prompt=self.prompt,
            secret_prompt=self.secret_prompt,
            confirm=self.confirm,
            echo=self.echoed.append,
            open_url=self.opened.append,
            sleep=self.sleep,
            clock=lambda: self.now,
        )

    @property
    def output(self) -> str:
        """Everything echoed."""
        return "\n".join(self.echoed)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """A fresh Free org (no marker) with valid accounts, a tmp HOME and the project's profiles (+ team)."""
    project = tmp_path / "project"
    (project / "targets").mkdir(parents=True)
    for name in ("free", "enterprise"):
        shutil.copy(ROOT / "targets" / f"{name}.yaml", project / "targets" / f"{name}.yaml")
    free = (ROOT / "targets" / "free.yaml").read_text()
    team = free.replace("name: free", "name: team").replace("expected_plan: free ", "expected_plan: team ")
    assert "expected_plan: team" in team
    (project / "targets" / "team.yaml").write_text(team)
    for name in ("CI", "GITHUB_ACTIONS"):
        monkeypatch.delenv(name, raising=False)
    conversion = FakeGitHubHttp(identity="app-manifest")
    conversion.add(
        "POST",
        "/app-manifests/manifestcode1234/conversions",
        status=201,
        json={"id": 4242, "slug": "otterdog-e2e-e2e-test-org", "pem": PEM, "webhook_secret": WEBHOOK_SECRET},
        repeat=True,
    )
    monkeypatch.setattr(appmanifest, "_manifest_http", lambda: conversion)
    return World(tmp_path, environ={"HOME": str(tmp_path / "home")}, settings=make_settings(project))


def run_wizard(world: World, script: Script, **options: Any) -> SetupWizard:
    """Run the wizard of instance ``org2`` (unless given) against the world."""
    assert world.settings is not None
    wizard = SetupWizard(
        SetupOptions(**{"instance": "org2", "org": ORG, **options}),
        script.io(),
        environ=world.environ,
        settings=world.settings,
        http=world.http,
        run_manifest=world.run_manifest,
        app_auth=world.app_auth,
        write_http=world.write_http,
        bootstrap=world.bootstrap,
        doctor=world.doctor,
    )
    wizard.run()
    return wizard


def assert_no_secret(text: str) -> None:
    """None of the secrets of the scenario appear."""
    for secret in (*TOKENS.values(), PASSWORD, "JBSWY3DPEHPK3PXP", WEBHOOK_SECRET, "MIIEfakekeymaterial"):
        assert secret not in text


# --- fresh instance -------------------------------------------------------------------------------------------------
def test_fresh_instance_with_the_admin_only(world: World) -> None:
    """Org pinned, admin token validated and written, profile from the plan; optional steps skipped; 0600 file."""
    script = Script(secrets=[TOKENS["admin"]])
    run_wizard(world, script)
    assert world.env() == {
        "E2E_ORG": ORG,
        "E2E_ORG_ID": str(ORG_ID),
        "E2E_ADMIN_LOGIN": "e2e-admin",
        "E2E_ADMIN_TOKEN": TOKENS["admin"],
        "E2E_ADMIN_TOKEN_TYPE": "classic",
        "E2E_PROFILE": "free",
    }
    path = world.config_dir / "org2.env"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and stat.S_IMODE(world.config_dir.stat().st_mode) == 0o700
    assert path.read_text().startswith("# otterdog-e2e instance org2: written by `otterdog-e2e setup`")
    assert "https://github.com/settings/tokens/new?scopes=repo,workflow,admin:org,admin:org_hook,delete_repo&" in (
        script.output
    )
    assert "profile free (targets/free.yaml), plan free" in script.output
    assert "otterdog-e2e ci-sync --target org2" in script.output
    assert not script.opened and not world.bootstraps and not world.doctors
    assert_no_secret(script.output)


def test_every_role_web_login_and_bootstrap(world: World) -> None:
    """All roles (classic and fine-grained), the web login, bootstrap and doctor; nothing secret echoed."""
    script = Script(
        secrets=[
            TOKENS["admin"],
            TOKENS["oracle"],
            TOKENS["author"],
            TOKENS["approver"],
            TOKENS["outsider"],
            TOKENS["config_reader"],
            PASSWORD,
            SEED,
        ],
        answers=["e2e-oracle", "e2e-author", "e2e-approver"],
        confirms={"Set up the": True, "bootstrap": True, "doctor": True},
    )
    world.memberships = {"e2e-oracle": {"state": "active", "role": "admin"}}
    run_wizard(world, script, token_type="fine-grained", open_urls=True)
    env = world.env()
    for role, login, kind in (
        ("ADMIN", "e2e-admin", "classic"),
        ("ORACLE", "e2e-oracle", "fine-grained"),
        ("AUTHOR", "e2e-author", "classic"),
        ("APPROVER", "e2e-approver", "classic"),
        ("OUTSIDER", "e2e-outsider", "classic"),
        ("CONFIG_READER", "e2e-reader", None),
    ):
        assert env[f"E2E_{role}_LOGIN"] == login
        if kind:
            assert env[f"E2E_{role}_TOKEN_TYPE"] == kind
    assert (
        env["E2E_CONFIG_READ_TOKEN"] == TOKENS["config_reader"] and env["E2E_CONFIG_READ_TOKEN_TYPE"] == "fine-grained"
    )
    assert env["E2E_ORACLE_TOKEN_TYPE"] == "fine-grained" and env["E2E_ORACLE_TOKEN"] == TOKENS["oracle"]
    assert env["E2E_ADMIN_PASSWORD"] == PASSWORD and env["E2E_ADMIN_TOTP_SEED"] == "JBSWY3DPEHPK3PXP"
    # --token-type fine-grained: prefilled fine-grained URLs, except the outsider (classic only); --open opens them
    assert "personal-access-tokens/new?name=otterdog-e2e-org2-admin&" in script.output
    assert any("settings/tokens/new?scopes=public_repo,read:org" in url for url in script.opened)
    assert any("target_name=e2e-test-org" in url for url in script.opened)
    assert world.bootstraps == ["org2"] and world.doctors == ["org2"]
    assert "accept the invitation" in script.output
    assert_no_secret(script.output)


# --- token validation -----------------------------------------------------------------------------------------------
def test_an_invalid_token_is_refused_and_asked_again(world: World) -> None:
    """GET /user 401: refused, nothing written for it, the next token is checked."""
    bad = "tokbadbadbad_000000000000"
    script = Script(secrets=["not a token!", bad, TOKENS["admin"]])
    run_wizard(world, script)
    assert world.env()["E2E_ADMIN_TOKEN"] == TOKENS["admin"]
    assert "does not look like a GitHub token" in script.output and "GET /user answered 401" in script.output
    assert bad not in (world.config_dir / "org2.env").read_text()


def test_the_admin_token_is_required(world: World) -> None:
    """Empty answers do not skip the admin; after the attempts nothing is written for it."""
    script = Script(secrets=[""] * 5)
    with pytest.raises(SetupError, match="admin: no valid token after 5 attempts"):
        run_wizard(world, script)
    assert "E2E_ADMIN_TOKEN" not in world.env() and world.env()["E2E_ORG"] == ORG


def test_missing_classic_scopes_are_refused(world: World) -> None:
    """A classic admin PAT without delete_repo is refused with the missing scope."""
    world.accounts["tokadmin_short_scopes_xxxx"] = Account(
        "e2e-admin", ADMIN_SCOPES - {"delete_repo"}, [ORG_ID], owner()
    )
    script = Script(secrets=["tokadmin_short_scopes_xxxx", TOKENS["admin"]])
    run_wizard(world, script)
    assert "the classic PAT lacks delete_repo" in script.output


def test_extra_scopes_fail_the_isolation_check(world: World) -> None:
    """A scope outside the role's allowlist: safety.check_identity_isolation refuses it."""
    world.accounts["tokauthor_wide_scopes_xxx"] = Account("e2e-author", MEMBER_SCOPES | {"delete_repo"})
    script = Script(secrets=[TOKENS["admin"], "tokauthor_wide_scopes_xxx", ""], confirms={"author token": True})
    run_wizard(world, script)
    assert "token scopes delete_repo are not allowed" in script.output
    assert "E2E_AUTHOR_TOKEN" not in world.env()


def test_the_admin_must_own_the_org(world: World) -> None:
    """An admin token of a plain member is refused."""
    world.accounts["tokadmin_member_only_xxxx"] = Account("e2e-admin", set(ADMIN_SCOPES), [ORG_ID], member())
    script = Script(secrets=["tokadmin_member_only_xxxx", TOKENS["admin"]])
    run_wizard(world, script)
    assert "e2e-admin is not an owner of e2e-test-org" in script.output


def test_a_foreign_membership_fails_the_isolation_check(world: World) -> None:
    """A classic PAT of an account in an unknown org is refused (isolation)."""
    world.accounts["tokadmin_foreign_org_xxxx"] = Account("e2e-admin", set(ADMIN_SCOPES), [ORG_ID, 999], owner())
    script = Script(secrets=["tokadmin_foreign_org_xxxx", TOKENS["admin"]])
    run_wizard(world, script)
    assert "outside github.allowed_org_ids" in script.output


@pytest.mark.parametrize(
    ("role", "account", "message"),
    [
        ("outsider", Account("e2e-outsider", None), "the outsider needs a classic PAT, got a fine-grained PAT"),
        ("config_reader", Account("e2e-reader", set(MEMBER_SCOPES)), "needs a fine-grained PAT, got a classic PAT"),
    ],
)
def test_token_kinds_per_role(world: World, role: str, account: Account, message: str) -> None:
    """The outsider is classic only, the config_reader fine-grained only."""
    world.accounts["tokwrongkind_000000000000"] = account
    script = Script(
        secrets=[TOKENS["admin"], "tokwrongkind_000000000000", ""], confirms={f"Set up the {role} token": True}
    )
    run_wizard(world, script)
    assert message in script.output


def test_a_fine_grained_member_token_needs_the_membership(world: World) -> None:
    """A member's fine-grained token before the invitation is accepted: refused with the hint."""
    world.accounts["tokauthor_finegrained_xxx"] = Account("e2e-author", None)
    script = Script(secrets=[TOKENS["admin"], "tokauthor_finegrained_xxx", ""], confirms={"author token": True})
    run_wizard(world, script)
    assert "needs an active membership of e2e-test-org" in script.output and "--rotate author" in script.output
    world.accounts["tokauthor_finegrained_xxx"].membership = member()
    run_wizard(world, Script(secrets=["tokauthor_finegrained_xxx"], confirms={"author token": True}))
    assert world.env()["E2E_AUTHOR_TOKEN_TYPE"] == "fine-grained"


# --- fine-grained tokens of members and the oracle: the membership first --------------------------------------------
def test_a_fine_grained_member_is_invited_and_awaited_before_its_token(world: World) -> None:
    """Fine-grained author: login asked, invited as a member, invitation URL printed and polled, then the token URL
    (with the approval hint) and the token, which must belong to the invited account."""
    world.accounts["tokauthor_finegrained_xxx"] = Account("e2e-author", None, membership=member())
    script = Script(
        secrets=[TOKENS["admin"], TOKENS["outsider"], "tokauthor_finegrained_xxx"],
        answers=["e2e-author"],
        confirms={"author token": True},
    )
    run_wizard(world, script, token_type="fine-grained", open_urls=True)
    assert world.invites == [("e2e-author", {"role": "member"})]
    output = script.output
    invitation = output.index("accept the invitation: https://github.com/orgs/e2e-test-org/invitation")
    assert invitation < output.index("personal-access-tokens/new?name=otterdog-e2e-org2-author&")
    assert "/organizations/e2e-test-org/settings/personal-access-token-requests" in output
    assert "https://github.com/orgs/e2e-test-org/invitation" in script.opened
    assert "token of e2e-outsider, but e2e-author is the invited author account" in output
    env = world.env()
    assert env["E2E_AUTHOR_TOKEN"] == "tokauthor_finegrained_xxx" and env["E2E_AUTHOR_TOKEN_TYPE"] == "fine-grained"
    assert script.now == 10.0  # one poll interval until the invitation was accepted


def test_a_fine_grained_oracle_is_invited_as_an_owner(world: World) -> None:
    """The oracle's invitation asks for the owner role."""
    script = Script(
        secrets=[TOKENS["admin"], TOKENS["oracle"]], answers=["e2e-oracle"], confirms={"oracle token": True}
    )
    run_wizard(world, script, token_type="fine-grained")
    assert world.invites == [("e2e-oracle", {"role": "admin"})]
    assert "invited e2e-oracle to e2e-test-org as an owner" in script.output
    assert world.env()["E2E_ORACLE_TOKEN"] == TOKENS["oracle"]


def test_an_existing_membership_is_never_changed(world: World) -> None:
    """A member already in the org (even an owner as approver) is not invited again, nor demoted."""
    world.accounts["tokapprover_finegrained_x"] = Account("e2e-approver", None, membership=owner())
    world.memberships = {"e2e-approver": {"state": "active", "role": "admin"}}
    script = Script(
        secrets=[TOKENS["admin"], "tokapprover_finegrained_x"],
        answers=["e2e-approver"],
        confirms={"approver token": True},
    )
    run_wizard(world, script, token_type="fine-grained")
    assert not world.invites and world.memberships["e2e-approver"] == {"state": "active", "role": "admin"}
    assert "is a member with role 'admin' already (left unchanged)" in script.output
    assert script.now == 0.0 and world.env()["E2E_APPROVER_TOKEN_TYPE"] == "fine-grained"


def test_an_invitation_not_accepted_in_time_is_resumed_by_the_next_run(world: World) -> None:
    """Timeout: the token is not asked, login and kind are kept; the next run polls the same invitation."""
    world.accepts_invitations = False
    script = Script(secrets=[TOKENS["admin"]], answers=["e2e-author"], confirms={"author token": True})
    run_wizard(world, script, token_type="fine-grained", wait_timeout=30)
    assert "e2e-author has not accepted the invitation yet: run setup again" in script.output
    assert script.now == 30.0 and not [text for text in script.asked if text.startswith("author token")]
    env = world.env()
    assert env["E2E_AUTHOR_LOGIN"] == "e2e-author" and env["E2E_AUTHOR_TOKEN_TYPE"] == "fine-grained"
    assert "E2E_AUTHOR_TOKEN" not in env
    world.accepts_invitations = True
    world.accounts["tokauthor_finegrained_xxx"] = Account("e2e-author", None, membership=member())
    script = Script(secrets=["tokauthor_finegrained_xxx"], answers=["e2e-author"], confirms={"author token": True})
    run_wizard(world, script)  # the stored kind keeps the fine-grained path
    assert len(world.invites) == 1 and world.env()["E2E_AUTHOR_TOKEN"] == "tokauthor_finegrained_xxx"


def test_member_logins_are_checked_before_any_invitation(world: World) -> None:
    """Not a login, an organization, another role's account: asked again; empty skips the role."""
    run_wizard(world, Script(secrets=[TOKENS["admin"], TOKENS["author"]], confirms={"author token": True}))
    script = Script(answers=["not a login", "some-org", "e2e-author", ""], confirms={"approver token": True})
    run_wizard(world, script, token_type="fine-grained")
    output = script.output
    assert "'not a login' is not a GitHub login" in output and "some-org is not a GitHub user account" in output
    assert "the same account is already stored for the author" in output and "approver: skipped" in output
    assert not world.invites and "E2E_APPROVER_LOGIN" not in world.env()


@dataclass
class MembershipAtTokenPrompt(Script):
    """Script whose first prompt for the ``role`` token finds the invited membership in ``state``."""

    world: World | None = None
    role: str = "oracle"
    login: str = "e2e-oracle"
    state: str = "pending"

    def secret_prompt(self, text: str) -> str:
        """Set the membership state of the invited account first."""
        if text.startswith(f"{self.role} token") and self.world is not None:
            self.world.accepts_invitations = False
            self.world.memberships[self.login]["state"] = self.state
        return super().secret_prompt(text)


@pytest.mark.parametrize("state", ["pending", "active"])
def test_an_invitation_of_this_run_is_withdrawn_after_a_token_of_another_account(world: World, state: str) -> None:
    """Fine-grained oracle invited as an owner by this run, then only a token of ANOTHER account: a still pending
    invitation is cancelled (DELETE with the admin token, the stored login removed); an accepted one is reported."""
    world.accounts["tokoracle_other_account_x"] = Account("e2e-oracle2", None, [], owner(), owner_probes=True)
    script = MembershipAtTokenPrompt(
        secrets=[TOKENS["admin"], "tokoracle_other_account_x", ""],
        answers=["e2e-oracle"],
        confirms={"oracle token": True},
        world=world,
        state=state,
    )
    run_wizard(world, script, token_type="fine-grained")
    assert world.invites == [("e2e-oracle", {"role": "admin"})]
    assert "token of e2e-oracle2, but e2e-oracle is the invited oracle account" in script.output
    if state == "pending":
        assert world.cancelled == ["e2e-oracle"]
        assert "oracle: cancelled the pending invitation of e2e-oracle to e2e-test-org" in script.output
        assert "E2E_ORACLE_LOGIN" not in world.env()
    else:
        assert not world.cancelled
        assert "e2e-oracle accepted the invitation of this run and stays an owner of e2e-test-org" in script.output
    assert "E2E_ORACLE_TOKEN" not in world.env()


def test_an_invitation_of_a_former_run_is_never_withdrawn(world: World) -> None:
    """An author invitation a former run created (pending when this run starts) stays pending after a token of
    another account: only the invitations of the current run are cancelled."""
    world.accounts["tokauthor_other_account_x"] = Account("e2e-author2", None, membership=member())
    world.memberships = {"e2e-author": {"state": "pending", "role": "member"}}
    script = MembershipAtTokenPrompt(
        secrets=[TOKENS["admin"], "tokauthor_other_account_x", ""],
        answers=["e2e-author"],
        confirms={"author token": True},
        world=world,
        role="author",
        login="e2e-author",
    )
    run_wizard(world, script, token_type="fine-grained")
    assert "token of e2e-author2, but e2e-author is the invited author account" in script.output
    assert not world.invites and not world.cancelled and world.memberships["e2e-author"]["state"] == "pending"
    assert world.env()["E2E_AUTHOR_LOGIN"] == "e2e-author"


def test_a_token_of_another_role_is_refused(world: World) -> None:
    """Two roles never share a token: the admin token as author is refused."""
    script = Script(secrets=[TOKENS["admin"], TOKENS["admin"], TOKENS["author"]], confirms={"author token": True})
    run_wizard(world, script)
    assert "the same token is already stored for the admin" in script.output
    assert world.env()["E2E_AUTHOR_TOKEN"] == TOKENS["author"]


def test_an_account_of_another_role_is_refused(world: World) -> None:
    """Another token of the author's account as approver is refused (one machine account per role)."""
    world.accounts["tokauthor_second_token_xx"] = Account("E2E-Author", set(MEMBER_SCOPES))
    script = Script(
        secrets=[TOKENS["admin"], TOKENS["author"], "tokauthor_second_token_xx", TOKENS["approver"]],
        confirms={"author token": True, "approver token": True},
    )
    run_wizard(world, script)
    assert "the same account is already stored for the author" in script.output
    assert world.env()["E2E_APPROVER_LOGIN"] == "e2e-approver"


def test_the_admin_token_as_oracle_is_the_fallback(world: World) -> None:
    """oracle = admin is allowed but nothing is stored (the admin token is the oracle's fallback)."""
    script = Script(secrets=[TOKENS["admin"], TOKENS["admin"]], confirms={"oracle token": True})
    run_wizard(world, script)
    assert "same token as the admin" in script.output
    assert "E2E_ORACLE_TOKEN" not in world.env()


# --- re-runs ----------------------------------------------------------------------------------------------------------
def test_stored_valid_tokens_are_kept(world: World) -> None:
    """A re-run validates the stored tokens and asks nothing for them."""
    run_wizard(world, Script(secrets=[TOKENS["admin"], TOKENS["author"]], confirms={"author token": True}))
    script = Script(secrets=[])
    run_wizard(world, script)
    assert "admin: keeping the token of e2e-admin (classic PAT, no expiration)" in script.output
    assert "author: keeping the token of e2e-author" in script.output
    assert not [text for text in script.asked if "token (input hidden" in text]


def test_rotate_asks_again_and_empty_keeps_the_stored_token(world: World) -> None:
    """--rotate admin: a new token replaces the stored one; an empty answer keeps it."""
    run_wizard(world, Script(secrets=[TOKENS["admin"]]))
    world.accounts["tokadmin_rotated_00000000"] = Account("e2e-admin", set(ADMIN_SCOPES), [ORG_ID], owner())
    script = Script(secrets=["tokadmin_rotated_00000000"])
    run_wizard(world, script, rotate=("admin",))
    assert world.env()["E2E_ADMIN_TOKEN"] == "tokadmin_rotated_00000000"
    assert "regenerating the existing token" in script.output
    script = Script(secrets=[""])
    run_wizard(world, script, rotate=("admin",))
    assert world.env()["E2E_ADMIN_TOKEN"] == "tokadmin_rotated_00000000" and "admin: unchanged" in script.output


def test_an_unusable_stored_token_can_be_removed(world: World) -> None:
    """A stored author token that no longer works: asked again; skipped, the operator may remove it."""
    run_wizard(world, Script(secrets=[TOKENS["admin"], TOKENS["author"]], confirms={"author token": True}))
    world.accounts[TOKENS["author"]].valid = False
    script = Script(secrets=[""], confirms={"Remove the unusable": True})
    run_wizard(world, script)
    assert "the stored E2E_AUTHOR_TOKEN is not usable" in script.output
    assert not {"E2E_AUTHOR_TOKEN", "E2E_AUTHOR_LOGIN", "E2E_AUTHOR_TOKEN_TYPE"} & set(world.env())


def test_an_interrupted_run_keeps_its_progress(world: World) -> None:
    """Every validated value is written at once: an exception later leaves the admin token in the file."""

    def interrupted(text: str) -> str:
        """Ctrl-C at the author prompt."""
        if "author" in text:
            raise KeyboardInterrupt
        return TOKENS["admin"]

    script = Script(confirms={"author token": True})
    script.secret_prompt = interrupted  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        run_wizard(world, script)
    assert world.env()["E2E_ADMIN_TOKEN"] == TOKENS["admin"] and world.env()["E2E_PROFILE"] == "free"


# --- org and profile --------------------------------------------------------------------------------------------------
def test_a_missing_org_gets_its_creation_url_and_is_checked_again(world: World) -> None:
    """404: the creation URL is printed, the operator creates the org and the wizard checks again."""
    world.missing_org_checks = 1
    script = Script(secrets=[TOKENS["admin"]], confirms={"Check e2e-test-org again": True})
    run_wizard(world, script, profile="free")
    assert "https://github.com/account/organizations/new?plan=free" in script.output
    assert world.env()["E2E_ORG_ID"] == str(ORG_ID)


def test_a_missing_org_stops_when_the_operator_gives_up(world: World) -> None:
    """Not created: SetupError, nothing about the org written; enterprise profiles get the GHEC hint."""
    world.missing_org_checks = 5
    script = Script(confirms={"again": False})
    with pytest.raises(SetupError, match="organization e2e-test-org not found"):
        run_wizard(world, script, profile="enterprise")
    assert "createEnterpriseOrganization" in script.output and world.env() == {}


def test_a_missing_org_of_an_instance_without_a_known_plan_gets_every_hint(world: World) -> None:
    """Instance acme-a, no --profile, no E2E_PROFILE: the Free URL, the Enterprise Cloud note and the --profile hint."""
    world.missing_org_checks = 5
    script = Script(confirms={"again": False})
    with pytest.raises(SetupError, match="organization e2e-test-org not found"):
        run_wizard(world, script, instance="acme-a")
    assert "https://github.com/account/organizations/new?plan=free" in script.output
    assert "createEnterpriseOrganization" in script.output and "not automated by setup" in script.output
    assert "pass --profile enterprise|free|team" in script.output
    script = Script(confirms={"again": False})
    world.missing_org_checks = 5
    with pytest.raises(SetupError, match="not found"):
        run_wizard(world, script, instance="acme-b", profile="team")
    assert "https://github.com/account/organizations/new\n" in script.output + "\n"
    assert "createEnterpriseOrganization" not in script.output and "--profile" not in script.output


def test_the_org_login_is_asked_and_its_exact_case_used(world: World) -> None:
    """No --org: asked; GitHub's exact-case login is the one written."""
    script = Script(secrets=[TOKENS["admin"]], answers=["E2E-Test-Org"])
    run_wizard(world, script, org=None)
    assert world.env()["E2E_ORG"] == ORG and "using the exact-case login e2e-test-org" in script.output


def test_a_pinned_org_id_that_changed_is_refused(world: World) -> None:
    """The env file pins another id (org renamed or recreated): refused, nothing changed."""
    world.write_env("org2", f"E2E_ORG={ORG}\nE2E_ORG_ID=1\n")
    with pytest.raises(SetupError, match=r"E2E_ORG_ID of .* is 1 but e2e-test-org has id 424242"):
        run_wizard(world, Script())
    assert world.env() == {"E2E_ORG": ORG, "E2E_ORG_ID": "1"}


def test_another_org_for_a_pinned_instance_is_refused(world: World) -> None:
    """--org other than the pinned org: another instance is needed."""
    world.write_env("org2", "E2E_ORG=some-other-org\n")
    with pytest.raises(SetupError, match="pins the organization some-other-org"):
        run_wizard(world, Script())


def test_production_orgs_are_refused(world: World) -> None:
    """The denylist applies before any request."""
    with pytest.raises(SafetyError, match="production denylist"):
        run_wizard(world, Script(), org="eclipse-foo")
    assert not world.clients


def test_the_profile_follows_the_plan(world: World) -> None:
    """A Team org gets the team profile."""
    world.org["plan"] = {"name": "team"}
    run_wizard(world, Script(secrets=[TOKENS["admin"]]))
    assert world.env()["E2E_PROFILE"] == "team"


def test_a_profile_of_another_plan_is_refused(world: World) -> None:
    """--profile enterprise on a Free org: the profile's expected plan differs."""
    with pytest.raises(SetupError, match="profile enterprise expects plan enterprise, e2e-test-org is on plan free"):
        run_wizard(world, Script(secrets=[TOKENS["admin"]]), profile="enterprise")


def test_an_instance_named_after_a_profile_uses_it(world: World) -> None:
    """Instance free: profile free (another --profile is ambiguous)."""
    run_wizard(world, Script(secrets=[TOKENS["admin"]]), instance="free")
    assert world.env("free")["E2E_PROFILE"] == "free"
    with pytest.raises(SetupError, match="the instance free is the profile of the same name"):
        run_wizard(world, Script(), instance="free", profile="team")


def test_an_unknown_profile_is_asked_again(world: World) -> None:
    """A plan without a profile file: the operator picks one of the profiles."""
    world.org["plan"] = {"name": "business_plus"}
    script = Script(secrets=[TOKENS["admin"]], answers=["nope", "team"])
    with pytest.raises(SetupError, match="profile team expects plan team"):
        run_wizard(world, script)
    assert "no profile 'nope'" in script.output


# --- --from and shared accounts ---------------------------------------------------------------------------------------
def test_from_copies_only_non_secret_non_org_settings(world: World) -> None:
    """--from: profile, token types, teams, repos, transport, webhook URL; never tokens, logins, org or App ids."""
    world.write_env(
        "first",
        "\n".join(
            [
                "E2E_ORG=first-org",
                "E2E_ORG_ID=1",
                f"E2E_ADMIN_TOKEN={TOKENS['admin']}",
                "E2E_ADMIN_LOGIN=e2e-admin",
                "E2E_ADMIN_TOKEN_TYPE=classic",
                "E2E_PROFILE=free",
                "E2E_ADMIN_TEAM=custom-admins",
                "E2E_TRANSPORT=external",
                "E2E_APP_ID=99",
                "E2E_APP_WEBHOOK_SECRET=hook-secret-xyz",
                "E2E_APP_WEBHOOK_URL=https://sink.example.org/hook",
                "E2E_ALLOWED_ORG_IDS=5",
                "",
            ]
        ),
    )
    world.write_env("org2", "E2E_TRANSPORT=relay\n")
    script = Script(secrets=[TOKENS["admin"]])
    run_wizard(world, script, from_instance="first")
    env = world.env()
    assert env["E2E_ADMIN_TEAM"] == "custom-admins" and env["E2E_APP_WEBHOOK_URL"] == "https://sink.example.org/hook"
    assert env["E2E_TRANSPORT"] == "relay"  # never overridden
    assert env["E2E_ORG"] == ORG and "E2E_APP_ID" not in env and "E2E_APP_WEBHOOK_SECRET" not in env
    assert "E2E_ALLOWED_ORG_IDS" not in env
    assert "copied from instance first: E2E_PROFILE, E2E_ADMIN_TOKEN_TYPE, E2E_ADMIN_TEAM" in script.output
    with pytest.raises(SetupError, match="--from missing"):
        run_wizard(world, Script(), from_instance="missing")


def write_other_instance(world: World, *, admin: bool = True, marker: bool = True) -> None:
    """Instance ``first`` of the org first-org (OTHER_ORG_ID): with ``admin`` the admin login and token setup writes
    after the owner check (else: an aborted setup that only pinned the org), with ``marker`` bootstrapped."""
    lines = [f"E2E_ORG=first-org\nE2E_ORG_ID={OTHER_ORG_ID}\nE2E_PROFILE=free\n"]
    if admin:
        lines.append("E2E_ADMIN_LOGIN=e2e-admin\nE2E_ADMIN_TOKEN=tokadmin_first_000000000000\n")
    world.write_env("first", "".join(lines))
    description = "[otterdog-e2e] first" if marker else "scratch"
    world.other_orgs["first-org"] = {"login": "first-org", "id": OTHER_ORG_ID, "description": description}


def test_accounts_shared_with_another_instance_are_allowed_in_both_files(world: World) -> None:
    """A classic PAT whose account also belongs to the validated test org of instance first: offered as "org id N
    (instance first)"; accepted, both allowlists gain the other id."""
    write_other_instance(world)
    world.accounts[TOKENS["admin"]].orgs = [ORG_ID, OTHER_ORG_ID]
    script = Script(secrets=[TOKENS["admin"]], confirms={"also belongs to the test org": True})
    run_wizard(world, script)
    assert world.env()["E2E_ALLOWED_ORG_IDS"] == str(OTHER_ORG_ID)
    assert world.env("first")["E2E_ALLOWED_ORG_IDS"] == str(ORG_ID)
    assert world.env()["E2E_ADMIN_TOKEN"] == TOKENS["admin"]
    assert any(f"org id {OTHER_ORG_ID} (instance first)" in text for text in script.asked)


def test_shared_accounts_declined_fail_the_isolation_check(world: World) -> None:
    """The offer defaults to no: unanswered, the isolation check refuses the foreign membership as usual."""
    write_other_instance(world)
    world.accounts[TOKENS["admin"]].orgs = [ORG_ID, OTHER_ORG_ID]
    script = Script(secrets=[TOKENS["admin"]] * 5)
    with pytest.raises(SetupError):
        run_wizard(world, script)
    assert any("also belongs to the test org" in text for text in script.asked)
    assert "outside github.allowed_org_ids" in script.output and "E2E_ALLOWED_ORG_IDS" not in world.env("first")


def test_shared_orgs_are_written_only_once_the_token_passed_every_check(world: World) -> None:
    """An accepted offer for a token refused afterwards (not an owner of the org being set up) changes no env file;
    the next token that passes every check writes both."""
    write_other_instance(world)
    world.accounts["tokadmin_member_only_xxxx"] = Account(
        "e2e-admin", set(ADMIN_SCOPES), [ORG_ID, OTHER_ORG_ID], member()
    )
    script = Script(secrets=["tokadmin_member_only_xxxx", "", "", "", ""], confirms={"also belongs to the test": True})
    with pytest.raises(SetupError, match="admin: no valid token"):
        run_wizard(world, script)
    assert "e2e-admin is not an owner of e2e-test-org" in script.output
    assert "E2E_ALLOWED_ORG_IDS" not in world.env() and "E2E_ALLOWED_ORG_IDS" not in world.env("first")
    world.accounts[TOKENS["admin"]].orgs = [ORG_ID, OTHER_ORG_ID]
    run_wizard(world, Script(secrets=[TOKENS["admin"]], confirms={"also belongs to the test org": True}))
    assert world.env()["E2E_ALLOWED_ORG_IDS"] == str(OTHER_ORG_ID)
    assert world.env("first")["E2E_ALLOWED_ORG_IDS"] == str(ORG_ID)


@pytest.mark.parametrize(
    ("admin", "marker", "reason"),
    [
        (False, True, "holds no validated admin token (complete `otterdog-e2e setup --target first` first)"),
        (True, False, "the description of first-org lacks the safety marker '[otterdog-e2e]'"),
    ],
)
def test_only_validated_test_orgs_of_other_instances_are_offered(
    world: World, admin: bool, marker: bool, reason: str
) -> None:
    """An org pinned by an aborted setup (no admin token) or not bootstrapped (no marker) is not offered: the reason
    is printed, the isolation check refuses the membership, no env file changes."""
    write_other_instance(world, admin=admin, marker=marker)
    world.accounts[TOKENS["admin"]].orgs = [ORG_ID, OTHER_ORG_ID]
    script = Script(secrets=[TOKENS["admin"]] * 5, confirms={"also belongs to the test org": True})
    with pytest.raises(SetupError):
        run_wizard(world, script)
    assert not [text for text in script.asked if "also belongs to the test org" in text]
    assert f"note: org id {OTHER_ORG_ID} (instance first) is not offered for E2E_ALLOWED_ORG_IDS: " in script.output
    assert reason in script.output
    assert "outside github.allowed_org_ids" in script.output
    assert "E2E_ALLOWED_ORG_IDS" not in world.env() and "E2E_ALLOWED_ORG_IDS" not in world.env("first")


# --- web-UI login -----------------------------------------------------------------------------------------------------
def test_an_invalid_totp_seed_is_asked_again(world: World) -> None:
    """A 6-digit code instead of the setup key is refused (message without the value), the key is normalized."""
    script = Script(secrets=[TOKENS["admin"], PASSWORD, "123456", SEED], confirms={"web-UI login": True})
    run_wizard(world, script)
    assert "not a base32 TOTP secret" in script.output
    assert world.env()["E2E_ADMIN_TOTP_SEED"] == "JBSWY3DPEHPK3PXP"
    assert_no_secret(script.output)


def test_stored_web_credentials_are_kept_unless_rotated(world: World) -> None:
    """A valid stored login is kept; --rotate web asks again without the opt-in question."""
    run_wizard(world, Script(secrets=[TOKENS["admin"], PASSWORD, SEED], confirms={"web-UI login": True}))
    script = Script()
    run_wizard(world, script)
    assert "web-UI login: keeping E2E_ADMIN_PASSWORD and E2E_ADMIN_TOTP_SEED" in script.output
    script = Script(secrets=["new password value", SEED])
    run_wizard(world, script, rotate=("web",))
    assert world.env()["E2E_ADMIN_PASSWORD"] == "new password value"


# --- GitHub App -------------------------------------------------------------------------------------------------------
def test_the_app_step_writes_its_keys_and_polls_the_installation(world: World) -> None:
    """Marker present: manifest flow, E2E_APP_* in the instance env file, install URL printed and polled."""
    world.org["description"] = "[otterdog-e2e] scratch"
    world.write_env("org2", "E2E_APP_PRIVATE_KEY=stale-inline-key\n")
    world.installations = [None, None, dict(INSTALLATION)]
    script = Script(secrets=[TOKENS["admin"]], answers=["https://sink.example.org/hook"], confirms={"GitHub App": True})
    run_wizard(world, script, open_urls=True)
    env = world.env()
    app_dir = world.config_dir / "org2"
    assert env["E2E_APP_ID"] == "4242" and env["E2E_APP_SLUG"] == "otterdog-e2e-e2e-test-org"
    assert env["E2E_APP_PRIVATE_KEY_FILE"] == str(app_dir / "app-4242.private-key.pem")
    assert (
        env["E2E_APP_WEBHOOK_SECRET"] == WEBHOOK_SECRET
        and env["E2E_APP_WEBHOOK_URL"] == "https://sink.example.org/hook"
    )
    assert "E2E_APP_PRIVATE_KEY" not in env  # the stale inline key would win over the new file
    assert stat.S_IMODE(app_dir.stat().st_mode) == 0o700
    assert world.manifest_calls == [(ORG, "https://sink.example.org/hook")]
    install = f"https://github.com/apps/otterdog-e2e-e2e-test-org/installations/new/permissions?target_id={ORG_ID}"
    assert install in script.output and install in script.opened
    assert world.app is not None and world.app.calls == 3 and script.now == 10.0  # checked, polled, slept, found
    assert "GitHub App installation 777 ready" in script.output
    assert_no_secret(script.output)


def test_the_installation_wait_times_out(world: World) -> None:
    """Never installed within the timeout: reported, setup goes on (re-runnable)."""
    world.org["description"] = "[otterdog-e2e] scratch"
    world.installations = [None]
    script = Script(secrets=[TOKENS["admin"]], confirms={"GitHub App": True})
    run_wizard(world, script, webhook_url="https://sink.example.org/hook", wait_timeout=30, poll_interval=10)
    assert "not installed yet: install it, then run setup (or bootstrap) again" in script.output
    assert world.env()["E2E_APP_ID"] == "4242"


def test_a_partial_installation_is_reported(world: World) -> None:
    """An installation on selected repositories only: the problem is named."""
    world.org["description"] = "[otterdog-e2e] scratch"
    world.installations = [{**INSTALLATION, "repository_selection": "selected"}]
    script = Script(secrets=[TOKENS["admin"]], confirms={"GitHub App": True})
    run_wizard(world, script, webhook_url="https://sink.example.org/hook")
    assert "repository_selection is 'selected'" in script.output


def test_a_loopback_webhook_url_is_asked_again(world: World) -> None:
    """GitHub rejects loopback hook URLs: asked again."""
    world.org["description"] = "[otterdog-e2e] scratch"
    script = Script(
        secrets=[TOKENS["admin"]],
        answers=["http://127.0.0.1:5000/hook", "https://sink.example.org/hook"],
        confirms={"GitHub App": True},
    )
    run_wizard(world, script)
    assert "must be an absolute https URL" in script.output
    assert world.env()["E2E_APP_WEBHOOK_URL"] == "https://sink.example.org/hook"


def test_the_app_waits_for_the_marker_of_bootstrap(world: World) -> None:
    """No marker yet: the App is offered again right after bootstrap added it, then bootstrap runs again."""
    script = Script(
        secrets=[TOKENS["admin"]],
        confirms={"GitHub App": True, "Run bootstrap again": True, "bootstrap": True},
    )
    run_wizard(world, script, webhook_url="https://sink.example.org/hook")
    assert "lacks the safety marker '[otterdog-e2e]'" in script.output
    assert world.bootstraps == ["org2", "org2"] and world.env()["E2E_APP_ID"] == "4242"


def test_without_bootstrap_the_app_stays_a_next_step(world: World) -> None:
    """No marker and bootstrap declined: the App is listed as what to do next."""
    script = Script(secrets=[TOKENS["admin"]], confirms={"GitHub App": True})
    run_wizard(world, script, webhook_url="https://sink.example.org/hook")
    assert "the GitHub App: run setup again once bootstrap added the safety marker" in script.output
    assert "E2E_APP_ID" not in world.env()


def test_a_stored_app_is_kept_and_its_installation_checked(world: World) -> None:
    """A configured App is not registered again; its installation is checked."""
    key = world.config_dir / "org2" / "app-1.private-key.pem"
    key.parent.mkdir(parents=True)
    key.write_text(PEM)
    world.write_env(
        "org2",
        f"E2E_APP_ID=1\nE2E_APP_SLUG=my-app\nE2E_APP_PRIVATE_KEY_FILE={key}\nE2E_APP_WEBHOOK_SECRET={WEBHOOK_SECRET}\n",
    )
    script = Script(secrets=[TOKENS["admin"]])
    run_wizard(world, script)
    assert "GitHub App: keeping my-app (id 1)" in script.output and "installation 777 ready" in script.output
    assert not world.manifest_calls


def test_a_stored_app_is_verified_before_its_installation_link(world: World) -> None:
    """A stored App that is not owned by the test org (safety.verify_app): refused before any installation link or
    poll, with the hint to register a new App (--rotate app)."""
    key = world.config_dir / "org2" / "app-1.private-key.pem"
    key.parent.mkdir(parents=True)
    key.write_text(PEM)
    world.write_env(
        "org2",
        f"E2E_APP_ID=1\nE2E_APP_SLUG=my-app\nE2E_APP_PRIVATE_KEY_FILE={key}\nE2E_APP_WEBHOOK_SECRET={WEBHOOK_SECRET}\n",
    )
    world.app_owner = {"type": "Organization", "id": 999, "login": "elsewhere"}
    world.installations = [None]
    script = Script(secrets=[TOKENS["admin"]])
    with pytest.raises(SetupError, match=r"GitHub App my-app: .*owned by 'elsewhere'.*--rotate app") as error:
        run_wizard(world, script)
    assert "no installation link for it" in str(error.value)
    assert world.app is not None and world.app.verified == 1 and world.app.calls == 0
    assert "installations/new" not in script.output and not script.opened


# --- environment ------------------------------------------------------------------------------------------------------
def test_refused_in_ci(world: World) -> None:
    """CI set: refused before anything is read or asked."""
    world.environ["CI"] = "true"
    script = Script()
    with pytest.raises(SetupError, match="refused when CI is set"):
        run_wizard(world, script)
    assert not script.asked and not world.clients


def test_exported_variables_that_override_the_file_are_named(world: World) -> None:
    """An exported E2E_ORG_ID would override the file in bootstrap/doctor/runs: warned (names only)."""
    world.environ["E2E_ORG_ID"] = "1"
    script = Script(secrets=[TOKENS["admin"]])
    run_wizard(world, script)
    assert "warning: exported in this shell, these override" in script.output and "E2E_ORG_ID" in script.output


def test_unknown_rotation_and_invalid_instances_are_refused(world: World) -> None:
    """--rotate values and instance names are checked when the wizard is built."""
    with pytest.raises(SetupError, match="--rotate: unknown"):
        run_wizard(world, Script(), rotate=("everything",))
    with pytest.raises(ValueError, match="invalid instance name"):
        run_wizard(world, Script(), instance="org2-untrusted")


# --- the CLI command --------------------------------------------------------------------------------------------------
def _cli_world(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch the collaborators of the setup command onto the world."""
    monkeypatch.setenv("HOME", world.environ["HOME"])
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: world.settings)
    patched: Callable[..., FakeGitHubHttp] = lambda token, **kwargs: world.http(token, kwargs["identity"])
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", patched)
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *args: None)


def test_cli_setup_end_to_end(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """``setup --target org2 --org ...``: hidden token prompt, every optional step declined; the token never shown."""
    _cli_world(world, monkeypatch)
    result = CliRunner().invoke(
        cli.main, ["setup", "--target", "org2", "--org", ORG], input=TOKENS["admin"] + "\n" + "n\n" * 9
    )
    assert result.exit_code == 0, result.output
    assert world.env()["E2E_ADMIN_TOKEN"] == TOKENS["admin"]
    assert TOKENS["admin"] not in result.output and "admin token (input hidden" in result.output


@pytest.mark.parametrize("target", ["a,b", "@all", "Org2", "org2-webui"])
def test_cli_setup_takes_one_valid_instance(world: World, monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """Lists and invalid names are usage errors (exit 2)."""
    _cli_world(world, monkeypatch)
    result = CliRunner().invoke(cli.main, ["setup", "--target", target])
    assert result.exit_code == 2 and "setup and ci-sync take one instance" in result.output


def test_cli_setup_errors_are_one_line(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """A SetupError is a click error (exit 1) without traceback."""
    _cli_world(world, monkeypatch)
    monkeypatch.setenv("CI", "1")
    result = CliRunner().invoke(cli.main, ["setup", "--target", "org2"])
    assert result.exit_code == 1 and "Error: setup is interactive and refused when CI is set" in result.output


def test_cli_rotation_choices_match_the_wizard() -> None:
    """The --rotate choices of the CLI are the wizard's."""
    from otterdog_e2e.onboard.wizard import ROTATABLE

    assert tuple(cli.SETUP_ROTATABLE) == ROTATABLE


def test_cli_setup_wait_timeout_takes_durations(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """--wait-timeout takes the durations of bootstrap --wait-timeout (90s, 10m, 1h; default 30m) for the wizard and
    the bootstrap it starts; the wizard reads a copy of the environment, never os.environ itself."""
    _cli_world(world, monkeypatch)
    seen: list[SetupWizard] = []
    monkeypatch.setattr(SetupWizard, "run", lambda self: seen.append(self) or None)
    for argument, seconds in (("90s", 90.0), ("10m", 600.0), (None, 1800.0)):
        extra = ["--wait-timeout", argument] if argument else []
        result = CliRunner().invoke(cli.main, ["setup", "--target", "org2", *extra])
        assert result.exit_code == 0, result.output
        wizard = seen.pop()
        assert wizard.options.wait_timeout == seconds
        assert isinstance(wizard.bootstrap, functools.partial) and wizard.bootstrap.keywords["wait_timeout"] == seconds
        assert wizard.environ is not os.environ and wizard.bootstrap.keywords["pristine"] is wizard.environ
        assert isinstance(wizard.doctor, functools.partial) and wizard.doctor.keywords["pristine"] is wizard.environ
    result = CliRunner().invoke(cli.main, ["setup", "--target", "org2", "--wait-timeout", "soon"])
    assert result.exit_code == 2 and "--wait-timeout: invalid duration 'soon'" in result.output


def test_setup_bootstrap_and_doctor_run_on_fresh_copies_of_the_pristine_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every bootstrap and doctor of setup gets a NEW copy of the environment captured before any env file was read:
    the values a former run loaded (an App replaced since) never reach the next one, os.environ is never changed."""
    monkeypatch.delenv("E2E_APP_ID", raising=False)
    created: list[tuple[str | None, dict[str, str], Any]] = []

    class Context:
        """E2EContext stand-in."""

        def __init__(self, environ: dict[str, str]) -> None:
            """Bind the environment."""
            self.environ = environ
            self.closed = False

        def start_session(self, *, argv: Any = ()) -> None:
            """No process setup."""

        def close(self) -> None:
            """Closed after bootstrap."""
            self.closed = True

    class Contexts:
        """E2EContext.create stand-in: load_env_files fills the context's environment."""

        @staticmethod
        def create(options: Any, *, environ: Any = None, **kwargs: Any) -> Context:
            """Record a copy of what the context starts with, then fill it like load_env_files."""
            assert environ is not None and environ is not os.environ
            created.append((options.target, dict(environ), None))
            environ["E2E_APP_ID"] = "1"
            context = Context(environ)
            created[-1] = (*created[-1][:2], context)
            return context

    monkeypatch.setattr(cli, "E2EContext", Contexts)
    monkeypatch.setattr(cli, "Bootstrap", lambda context, **kwargs: types.SimpleNamespace(run=lambda: None))
    monkeypatch.setattr(cli, "Doctor", lambda context: types.SimpleNamespace(run=list))
    monkeypatch.setattr(cli, "render_rows", lambda rows: "doctor table")
    pristine = {"HOME": "/nowhere", "E2E_ORG": "exported"}
    cli._setup_bootstrap("org2", pristine=pristine, wait_timeout=5.0)
    cli._setup_bootstrap("org2", pristine=pristine, wait_timeout=5.0)
    cli._setup_doctor("org2", pristine=pristine)
    assert [(target, environ) for target, environ, _ in created] == [("org2", pristine)] * 3
    assert pristine == {"HOME": "/nowhere", "E2E_ORG": "exported"} and "E2E_APP_ID" not in os.environ
    assert [context.closed for _, _, context in created] == [True, True, False]
