"""onboard.accounts: machine accounts set up in the browser (sign-in, 2FA enrollment, classic token), their secrets in
the accounts store of the setup configuration file (pass or Vault, one naming convention); the browser and the store
are fakes, the order of the writes is checked against the browser steps (nothing may lock an account out)."""

from __future__ import annotations

import contextlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import pytest

from otterdog_e2e.onboard import accounts as accounts_module
from otterdog_e2e.onboard.accounts import (
    DEFAULT_ITEMS,
    AccountError,
    AccountsConfig,
    AccountSetup,
    AccountsIO,
    SignIn,
    load_accounts_config,
    parse_accounts_config,
    setup_config_path,
    totp_code,
    web_login,
)
from otterdog_e2e.testing.fakes import FakeGitHubHttp
from otterdog_e2e.vaults import VaultError, parse

STORE = "pass:bots/technology.csi/github.com"
CONFIG = parse_accounts_config({"store": STORE}, "setup.yaml")
ACCOUNT = CONFIG.account("free", "admin")
BASE = f"{STORE}/otterdog-e2e-free-admin"
EMAIL, LOGIN, PASSWORD = "e2e-free-admin@example.org", "e2e-free-admin", "correct horse battery staple"
SHOWN_SEED, SEED = "JBSW Y3DP EHPK 3PXP", "JBSWY3DPEHPK3PXP"
CODES = ["aaaa-1111", "bbbb-2222"]
NEW_TOKEN, OLD_TOKEN = "ghp_" + "N" * 36, "ghp_" + "O" * 36
ADMIN_SCOPES = {"repo", "workflow", "admin:org", "admin:org_hook", "delete_repo"}
TOKEN_REF = f"{BASE}-api-token"


# --- configuration --------------------------------------------------------------------------------------------------
def test_the_default_layout_is_one_directory_of_named_entries() -> None:
    """otterdog-e2e-<instance>-<role>-<item> under the store, roles with dashes, ci-admin's item names."""
    reader = CONFIG.account("enterprise", "config_reader")
    assert ACCOUNT.ref("password") == f"{STORE}/otterdog-e2e-free-admin-password"
    assert ACCOUNT.ref("totp_seed") == f"{STORE}/otterdog-e2e-free-admin-2FA-seed"
    assert ACCOUNT.ref("recovery_codes") == f"{STORE}/otterdog-e2e-free-admin-2FA-recovery-codes"
    assert ACCOUNT.ref("token") == f"{STORE}/otterdog-e2e-free-admin-api-token"
    assert reader.ref("email") == f"{STORE}/otterdog-e2e-enterprise-config-reader-email"


def test_vault_uses_the_same_names_as_fields_of_one_secret() -> None:
    """vault:<secret path>: each name is a field of that KV v2 secret (the reference splits at the last '/')."""
    config = parse_accounts_config({"store": "vault:otterdog-e2e/technology.csi/github"}, "setup.yaml")
    reference = parse(config.account("free", "admin").ref("password"))
    assert (reference.path, reference.field) == (
        "otterdog-e2e/technology.csi/github",
        "otterdog-e2e-free-admin-password",
    )
    assert config.provider == "vault" and CONFIG.provider == "pass"


def test_entry_and_items_are_configurable() -> None:
    """The ci-admin directory layout as a template; one item renamed, the others keep their default names."""
    config = parse_accounts_config(
        {"store": "pass:/bots/", "entry": "{instance}-{role}/github.com/{item}", "items": {"token": "otterdog-token"}},
        "setup.yaml",
    )
    account = config.account("free", "config_reader")
    assert account.ref("token") == "pass:bots/free-config-reader/github.com/otterdog-token"
    assert account.ref("totp_seed") == "pass:bots/free-config-reader/github.com/2FA-seed"
    assert dict(config.items) == {**DEFAULT_ITEMS, "token": "otterdog-token"}


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "accounts.store must be pass:<directory> or vault:<secret path>"),
        ({"store": "bitwarden:x"}, "accounts.store must be pass:"),
        ({"store": "pass:bots/../x"}, "accounts.store: not a path of names"),
        ({"store": STORE, "entry": "{instance}-{role}"}, "takes {instance}, {role} and {item}"),
        ({"store": STORE, "entry": "{project}-{item}"}, "takes {instance}, {role} and {item}"),
        ({"store": STORE, "entry": "{item"}, "accounts.entry"),
        ({"store": STORE, "entry": "a b-{item}"}, "accounts.entry: not a path of names"),
        ({"store": STORE, "items": {"ssh_key": "id_rsa"}}, "accounts.items maps some of"),
        ({"store": STORE, "items": {"token": "password"}}, "gives two items the same name"),
        ({"store": STORE, "color": "blue"}, "unknown key(s) in accounts: color"),
        ("pass:x", "accounts must be a mapping"),
    ],
)
def test_invalid_accounts_sections(data: Any, message: str) -> None:
    """Every invalid value names the file and the key."""
    with pytest.raises(AccountError, match=r"^setup\.yaml: ") as caught:
        parse_accounts_config(data, "setup.yaml")
    assert message in str(caught.value)


def test_one_set_of_accounts_for_every_instance() -> None:
    """accounts.set: every instance uses the accounts of that set (the organizations of the shards share them)."""
    config = parse_accounts_config({"store": STORE, "set": "free"}, "setup.yaml")
    for instance in ("repos", "webapp", "enterprise"):
        assert config.account(instance, "admin").ref("password") == f"{BASE}-password"
        assert config.account(instance, "admin").label == "otterdog-e2e-free-admin"
    for bad in ("", 3, "a/../b", {}, {"enterprise": ""}, {"enterprise": 3}, {"a/../b": "free"}):
        with pytest.raises(AccountError, match=r"accounts\.set"):
            parse_accounts_config({"store": STORE, "set": bad}, "setup.yaml")


def test_an_instance_can_keep_its_own_accounts() -> None:
    """accounts.set as a mapping: the set of each instance named, ``default`` for the others; without ``default``,
    the others use their own accounts."""
    config = parse_accounts_config({"store": STORE, "set": {"default": "free", "enterprise": "enterprise"}}, "x")
    assert config.account("repos", "admin").label == "otterdog-e2e-free-admin"
    assert config.account("enterprise", "admin").label == "otterdog-e2e-enterprise-admin"
    assert config.account("enterprise", "config_reader").ref("token") == (
        f"{STORE}/otterdog-e2e-enterprise-config-reader-api-token"
    )
    config = parse_accounts_config({"store": STORE, "set": {"repos": "free"}}, "x")
    assert config.account("repos", "admin").label == "otterdog-e2e-free-admin"
    assert config.account("webapp", "admin").label == "otterdog-e2e-webapp-admin"


def test_the_setup_configuration_file(tmp_path: Path) -> None:
    """~/.config/otterdog-e2e/setup.yaml of the environment's HOME, or E2E_SETUP_CONFIG; no file or no section:
    None; a named file that does not exist and an invalid file are errors."""
    environ = {"HOME": str(tmp_path)}
    path = tmp_path / ".config" / "otterdog-e2e" / "setup.yaml"
    assert setup_config_path(environ) == path and load_accounts_config(environ) is None
    path.parent.mkdir(parents=True)
    path.write_text("# nothing yet\n")
    assert load_accounts_config(environ) is None
    path.write_text(f"accounts:\n  store: {STORE}\n")
    assert load_accounts_config(environ) == AccountsConfig(STORE, source=str(path))
    other = tmp_path / "other.yaml"
    with pytest.raises(AccountError, match=r"E2E_SETUP_CONFIG: .* does not exist"):
        load_accounts_config({**environ, "E2E_SETUP_CONFIG": str(other)})
    other.write_text("accounts: [1, 2]\n")
    with pytest.raises(AccountError, match="accounts must be a mapping"):
        load_accounts_config({**environ, "E2E_SETUP_CONFIG": str(other)})
    other.write_text("accounts: {store: [\n")
    with pytest.raises(AccountError, match="cannot be read"):
        load_accounts_config({**environ, "E2E_SETUP_CONFIG": str(other)})


# --- helpers --------------------------------------------------------------------------------------------------------
def test_totp_code_matches_rfc_6238() -> None:
    """The SHA1 test vectors of RFC 6238 (seed '12345678901234567890'), last 6 digits."""
    seed = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
    assert [totp_code(seed, at) for at in (59, 1111111109, 1234567890, 2000000000)] == [
        "287082",
        "081804",
        "005924",
        "279037",
    ]


# --- fakes ----------------------------------------------------------------------------------------------------------
@dataclass
class FakeSession:
    """A browser session: records each step in the shared ``events``."""

    events: list[tuple[Any, ...]]
    login_as: str = LOGIN
    enabled: bool = False
    codes: list[str] = field(default_factory=lambda: list(CODES))
    asked_login_code: bool = False
    unreadable_key: bool = False  # the page hides the setup key: asked

    def login(self, username: str, password: str, *, code: Callable[[], str], device_code: Callable[[], str]) -> str:
        """Sign in (asks a 2FA code when enabled)."""
        self.events.append(("login", username, password))
        if self.enabled and self.asked_login_code:
            self.events.append(("login code", code()))
        return self.login_as

    def two_factor_enabled(self) -> bool:
        """The account's 2FA state."""
        return self.enabled

    def enroll_two_factor(
        self,
        *,
        keep_seed: Callable[[str], None],
        code: Callable[[str], str],
        keep_recovery_codes: Callable[[list[str]], None],
        ask_key: Callable[[str], str],
    ) -> None:
        """Setup key (asked when unreadable), code, recovery codes, acknowledgement."""
        shown = ask_key("GitHub's setup key could not be read (0 characters)") if self.unreadable_key else SHOWN_SEED
        keep_seed(shown)
        self.events.append(("submit code", code(shown)))
        keep_recovery_codes(self.codes)
        self.events.append(("acknowledge",))
        self.enabled = True

    def classic_token(self, *, note: str, url: str, days: int | None) -> str:
        """A new token value."""
        self.events.append(("token", note, url, days))
        return NEW_TOKEN

    def open(self, url: str) -> None:
        """Show a page."""
        self.events.append(("open", url))

    def join_org(self, org: str, login: str, *, public: bool) -> None:
        """Accept an invitation (fails for the org named "broken")."""
        if org == "broken":
            raise AccountError("invitation: no Join button")
        self.events.append(("join", org, login, public))

    def install_app(self, url: str) -> None:
        """Install the App."""
        self.events.append(("install", url))

    def confirm_app(self, url: str) -> None:
        """Create the App."""
        self.events.append(("confirm", url))


class FakeBrowser:
    """Counts the sessions it opened."""

    def __init__(self, session: FakeSession) -> None:
        """One session object for every account."""
        self.fake = session
        self.opened = 0

    @contextlib.contextmanager
    def session(self) -> Iterator[FakeSession]:
        """The fake session."""
        self.opened += 1
        yield self.fake


@dataclass
class World:
    """Store entries, events, echoed lines and the GitHub accounts behind tokens."""

    tmp_path: Path
    entries: dict[str, str] = field(default_factory=dict)
    events: list[tuple[Any, ...]] = field(default_factory=list)
    echoed: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    asked: list[str] = field(default_factory=list)  # the hidden prompts
    plain: list[str] = field(default_factory=list)  # the references read as no secret
    tokens: dict[str, tuple[str, set[str] | None]] = field(default_factory=dict)  # token -> (login, scopes)

    def http(self, token: str, role: str) -> FakeGitHubHttp:
        """GET /user and the token info of a known token (401 otherwise)."""
        login, scopes = self.tokens.get(token, ("", None))
        http = FakeGitHubHttp(identity=role, scopes=scopes, read_only=True)
        http.add("GET", "/user", json={"login": login}, status=200 if login else 401, repeat=True)
        return http

    def setup(self, session: FakeSession, **options: Any) -> tuple[AccountSetup, FakeBrowser]:
        """AccountSetup of the test org with the fakes (``environ``: extra variables)."""
        browser = FakeBrowser(session)
        io = AccountsIO(echo=self.echoed.append, secret_prompt=self.secret_prompt, prompt=lambda text: "")
        environ = {"HOME": str(self.tmp_path), **options.pop("environ", {})}
        setup = AccountSetup(org="e2e-test-org", environ=environ, browser=browser, io=io, http=self.http, **options)
        return setup, browser

    def secret_prompt(self, text: str) -> str:
        """Next scripted hidden answer."""
        self.asked.append(text)
        assert self.secrets, f"unexpected prompt: {text}"
        return self.secrets.pop(0)

    @property
    def output(self) -> str:
        """Everything echoed."""
        return "\n".join(self.echoed)


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """An account with e-mail and password in the store (no username, like the CSI bots); reads and writes go to
    ``entries`` (writes are events named after the item)."""
    state = World(tmp_path)
    state.entries.update({f"{BASE}-email": EMAIL, f"{BASE}-password": PASSWORD})

    def resolve(value: str, environ: object, *, secret: bool = True) -> str:
        """entries[value]; the values read as no secret are recorded in ``plain``."""
        if value not in state.entries:
            raise VaultError(f"{value}: is not in the password store")
        if not secret:
            state.plain.append(value)
        return state.entries[value]

    def store(value: str, secret: str, environ: object) -> None:
        """entries[value] = secret, recorded."""
        state.entries[value] = secret
        state.events.append(("write", value.removeprefix(f"{BASE}-")))

    monkeypatch.setattr(accounts_module, "resolve", resolve)
    monkeypatch.setattr(accounts_module, "store", store)
    return state


def assert_no_secret(text: str) -> None:
    """No password, key, code or token is echoed."""
    for secret in (PASSWORD, SEED, *CODES, NEW_TOKEN, OLD_TOKEN):
        assert secret not in text


# --- one account ----------------------------------------------------------------------------------------------------
def test_fresh_account_gets_2fa_and_its_token(world: World) -> None:
    """No 2FA, no token, no login known: signed in with the e-mail, the login GitHub shows is used; the key is stored
    before its code is submitted, the recovery codes before they are acknowledged, the token as soon as it is shown;
    its note is the description of the prefilled URLs."""
    session = FakeSession(world.events)
    setup, browser = world.setup(session)
    result = setup.setup(ACCOUNT)
    assert (result.login, result.token_ref, result.token_created, result.enrolled) == (LOGIN, TOKEN_REF, True, True)
    steps = [event[0] if event[0] != "write" else f"write {event[1]}" for event in world.events]
    assert steps == [
        "login",
        "write 2FA-seed",
        "submit code",
        "write 2FA-recovery-codes",
        "acknowledge",
        "token",
        "write api-token",
    ]
    assert world.events[0] == ("login", EMAIL, PASSWORD)
    assert world.entries[f"{BASE}-2FA-seed"] == SEED
    assert world.entries[f"{BASE}-2FA-recovery-codes"] == "\n".join(CODES)
    assert world.entries[TOKEN_REF] == NEW_TOKEN
    code = next(event for event in world.events if event[0] == "submit code")[1]
    assert code.isdigit() and len(code) == 6
    _, note, url, days = next(event for event in world.events if event[0] == "token")
    assert note.startswith("otterdog-e2e admin of the test organization e2e-test-org (instance free)")
    assert url.startswith("https://github.com/settings/tokens/new?scopes=repo,workflow,admin:org,admin:org_hook,")
    assert days is None and browser.opened == 1  # no expiration
    assert "classic token created (no expiration)" in world.output
    assert_no_secret(world.output)
    assert f"stored {TOKEN_REF}" in world.output  # logins and e-mails are no secrets: references keep them


def test_a_setup_key_the_page_hides_is_asked(world: World) -> None:
    """A setup key the page does not give is asked (hidden) from the dialog left open, then stored and used."""
    world.secrets.append(SHOWN_SEED)
    setup, _ = world.setup(FakeSession(world.events, unreadable_key=True))
    assert setup.setup(ACCOUNT).enrolled and world.entries[f"{BASE}-2FA-seed"] == SEED
    (asked,) = world.asked
    assert asked == (
        "  admin: GitHub's setup key could not be read (0 characters): copy it from the dialog in the browser window "
        "and paste it here (input hidden)"
    )


def test_the_known_login_signs_in_and_must_match(world: World) -> None:
    """E2E_<ROLE>_LOGIN (or a username item) is the sign-in name and the login GitHub must show."""
    setup, _ = world.setup(FakeSession(world.events, login_as="someone-else"), environ={"E2E_ADMIN_LOGIN": LOGIN})
    with pytest.raises(AccountError, match="signed in as someone-else, but the account is e2e-free-admin"):
        setup.setup(ACCOUNT)
    assert world.events == [("login", LOGIN, PASSWORD)]


def test_a_complete_account_needs_no_browser(world: World) -> None:
    """A stored key and a valid classic token of the account with the role's scopes: nothing to do."""
    world.entries.update({f"{BASE}-2FA-seed": SEED, TOKEN_REF: OLD_TOKEN})
    world.tokens[OLD_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    setup, browser = world.setup(FakeSession(world.events), environ={"E2E_ADMIN_LOGIN": LOGIN})
    result = setup.setup(ACCOUNT)
    assert (result.token_ref, result.token_created, result.enrolled) == (TOKEN_REF, False, False)
    assert browser.opened == 0 and not world.events
    assert "nothing to do" in world.output


@pytest.mark.parametrize(
    ("owner", "scopes", "problem"),
    [
        ("someone-else", ADMIN_SCOPES, "it belongs to someone-else, not e2e-free-admin"),
        (LOGIN, {"repo"}, "it lacks workflow, admin:org, admin:org_hook, delete_repo"),
        (LOGIN, None, "it is not a classic token"),
        ("", None, "is not usable (GET "),
    ],
)
def test_an_unusable_stored_token_is_replaced(world: World, owner: str, scopes: set[str] | None, problem: str) -> None:
    """A token of another account, without the role's scopes, fine-grained or revoked is replaced (2FA kept)."""
    world.entries.update({f"{BASE}-2FA-seed": SEED, TOKEN_REF: OLD_TOKEN})
    if owner:
        world.tokens[OLD_TOKEN] = (owner, scopes)
    setup, _ = world.setup(FakeSession(world.events, enabled=True), environ={"E2E_ADMIN_LOGIN": LOGIN})
    result = setup.setup(ACCOUNT)
    assert result.token_created and not result.enrolled and world.entries[TOKEN_REF] == NEW_TOKEN
    assert problem in world.output and "a new one is created" in world.output


def test_rotate_replaces_a_valid_token(world: World) -> None:
    """--rotate: a new token although the stored one is valid."""
    world.entries.update({f"{BASE}-2FA-seed": SEED, TOKEN_REF: OLD_TOKEN})
    world.tokens[OLD_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    setup, _ = world.setup(FakeSession(world.events, enabled=True), rotate=True)
    assert setup.setup(ACCOUNT).token_created and world.entries[TOKEN_REF] == NEW_TOKEN


def test_a_valid_token_without_the_key_checks_2fa_only(world: World) -> None:
    """A valid token but no key in the store: the browser checks 2FA (enrolled here) and keeps the token."""
    world.entries[TOKEN_REF] = OLD_TOKEN
    world.tokens[OLD_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    setup, _ = world.setup(FakeSession(world.events))
    result = setup.setup(ACCOUNT)
    assert result.enrolled and not result.token_created and world.entries[TOKEN_REF] == OLD_TOKEN
    assert not [event for event in world.events if event[0] == "token"]


def test_2fa_enabled_without_its_key_is_refused(world: World) -> None:
    """2FA enabled on GitHub but no key in the store: the account cannot be completed (nothing guessed)."""
    setup, _ = world.setup(FakeSession(world.events, enabled=True))
    with pytest.raises(AccountError, match=r"2FA is enabled but pass:.*-2FA-seed does not exist"):
        setup.setup(ACCOUNT)


def test_a_login_code_needs_the_key(world: World) -> None:
    """GitHub asks a 2FA code at sign-in and the store has no key: AccountError naming the entry."""
    setup, _ = world.setup(FakeSession(world.events, enabled=True, asked_login_code=True))
    with pytest.raises(AccountError, match=r"asks a 2FA code but pass:.*-2FA-seed does not exist"):
        setup.setup(ACCOUNT)


def test_the_login_code_comes_from_the_stored_key(world: World) -> None:
    """With the key in the store the sign-in code is its current TOTP code."""
    world.entries[f"{BASE}-2FA-seed"] = SHOWN_SEED  # normalized when read
    setup, _ = world.setup(FakeSession(world.events, enabled=True, asked_login_code=True))
    setup.setup(ACCOUNT)
    code = next(event for event in world.events if event[0] == "login code")[1]
    assert code.isdigit() and len(code) == 6


def test_a_missing_password_is_asked_once_and_stored(world: World) -> None:
    """No password item: a hidden prompt, stored before the sign-in."""
    del world.entries[f"{BASE}-password"]
    world.secrets.append(PASSWORD)
    setup, _ = world.setup(FakeSession(world.events))
    setup.setup(ACCOUNT)
    assert world.events[0] == ("write", "password") and world.events[1][0] == "login"
    assert_no_secret(world.output)


def test_an_unnamed_account_is_refused(world: World) -> None:
    """Neither a username or e-mail item nor E2E_<ROLE>_LOGIN."""
    del world.entries[f"{BASE}-email"]
    setup, _ = world.setup(FakeSession(world.events))
    with pytest.raises(AccountError, match=r"nor .*-email names the account"):
        setup.setup(ACCOUNT)
    assert not setup.exists(CONFIG.account("free", "author"))


def test_recovery_codes_are_required(world: World) -> None:
    """An enrollment without recovery codes stops before the acknowledgement."""
    setup, _ = world.setup(FakeSession(world.events, codes=[]))
    with pytest.raises(AccountError, match="no recovery codes"):
        setup.setup(ACCOUNT)
    assert ("acknowledge",) not in world.events


def test_classic_expirations_only(world: World) -> None:
    """The classic form offers 7, 30, 60 and 90 days, or no expiration (None)."""
    with pytest.raises(AccountError, match="7, 30, 60, 90 days"):
        world.setup(FakeSession(world.events), days=366)
    setup, _ = world.setup(FakeSession(world.events), days=30)
    setup.setup(ACCOUNT)
    assert next(event for event in world.events if event[0] == "token")[3] == 30
    assert "classic token created (30 days)" in world.output


# --- otterdog-e2e accounts ------------------------------------------------------------------------------------------
@pytest.fixture
def cli_env(world: World, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str | None]:
    """A tmp HOME with the setup configuration file, no CI, and the fake browser instead of Firefox."""
    from otterdog_e2e.cli import onboarding as cli_onboarding

    monkeypatch.setattr(cli_onboarding, "_open_browser", lambda stack: FakeBrowser(FakeSession(world.events)))
    monkeypatch.setattr(accounts_module, "_default_http", world.http)
    config = tmp_path / "home" / ".config" / "otterdog-e2e" / "setup.yaml"
    config.parent.mkdir(parents=True)
    config.write_text(f"accounts:\n  store: {STORE}\n")
    logins = [f"E2E_{role}_LOGIN" for role in ("ADMIN", "ORACLE", "AUTHOR", "APPROVER", "OUTSIDER", "CONFIG_READER")]
    unset: dict[str, str | None] = dict.fromkeys(("CI", "GITHUB_ACTIONS", "E2E_SETUP_CONFIG", "E2E_ORG", *logins))
    return {**unset, "HOME": str(tmp_path / "home"), "PASSWORD_STORE_DIR": "/srv/pass"}


def invoke(env: dict[str, str | None], *args: str) -> Any:
    """Run ``otterdog-e2e accounts``."""
    from click.testing import CliRunner

    from otterdog_e2e import cli

    return CliRunner().invoke(cli.main, ["accounts", *args], env=env)


def test_accounts_command_sets_up_the_accounts_of_the_store(world: World, cli_env: dict[str, str | None]) -> None:
    """Without --role: the roles whose account is in the store (admin here); the token goes to the store only; a
    second run has nothing to do."""
    result = invoke(cli_env, "--target", "free")
    assert result.exit_code == 0, result.output
    assert world.entries[TOKEN_REF] == NEW_TOKEN
    assert f"admin: {LOGIN}: token created at {TOKEN_REF}, 2FA enrolled" in result.output
    assert "author" not in result.output.split("next:")[0]
    assert "next: otterdog-e2e setup --target free" in result.output
    assert not (Path(str(cli_env["HOME"])) / ".config" / "otterdog-e2e" / "free.env").exists()
    assert_no_secret(result.output)
    world.tokens[NEW_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    again = invoke(cli_env, "--target", "free")
    assert again.exit_code == 0, again.output
    assert f"admin: {EMAIL} has its 2FA key and a valid token at {TOKEN_REF}: nothing to do" in again.output


def test_accounts_command_usage(world: World, cli_env: dict[str, str | None], tmp_path: Path) -> None:
    """No account of the instance in the store; no accounts section; an invalid file."""
    result = invoke(cli_env, "--target", "org9")
    assert result.exit_code == 2 and "no account of instance org9 in pass:bots/technology.csi/github.com" in (
        result.output
    )
    empty = tmp_path / "empty.yaml"
    empty.write_text("{}\n")
    result = invoke(cli_env, "--target", "free", "--config", str(empty))
    assert result.exit_code == 2 and "no accounts section in" in result.output
    empty.write_text("accounts: {store: 'bitwarden:x'}\n")
    result = invoke(cli_env, "--target", "free", "--config", str(empty))
    assert result.exit_code == 1 and "accounts.store must be pass:<directory> or vault:<secret path>" in result.output


def test_accounts_command_is_refused_in_ci(cli_env: dict[str, str | None]) -> None:
    """A visible browser has no place in CI."""
    result = invoke({**cli_env, "CI": "true"}, "--target", "free")
    assert result.exit_code == 1 and "refused when CI is set" in result.output


# --- web-login ------------------------------------------------------------------------------------------------------
def test_sign_in_reads_the_store_and_asks_nothing(world: World) -> None:
    """The store names the account and holds its password and 2FA key; nothing is asked nor written."""
    world.entries[f"{BASE}-2FA-seed"] = SHOWN_SEED
    setup, browser = world.setup(FakeSession(world.events))
    account = setup.sign_in(ACCOUNT)
    assert (account.role, account.name, account.login, account.password, account.seed) == (
        "admin",
        EMAIL,
        None,
        PASSWORD,
        SEED,
    )
    assert account.source == f"{BASE}-password" and PASSWORD not in repr(account) and browser.opened == 0
    del world.entries[f"{BASE}-password"]
    with pytest.raises(AccountError, match="no password at"):
        setup.sign_in(ACCOUNT)
    assert not world.events


def test_web_login_signs_in_shows_the_page_and_waits(world: World) -> None:
    """The 2FA code comes from the key, else it is typed; the page is shown until the operator answers; the login
    GitHub shows must be the account's."""
    session = FakeSession(world.events, enabled=True, asked_login_code=True)
    io = AccountsIO(echo=world.echoed.append, secret_prompt=world.secret_prompt, prompt=lambda text: "123456")
    waited: list[str] = []
    account = SignIn("admin", EMAIL, LOGIN, PASSWORD, SEED, f"{BASE}-password")
    assert web_login(FakeBrowser(session), io, account, "https://github.com/e2e-test-org", until=waited.append) == LOGIN
    assert [event[0] for event in world.events] == ["login", "login code", "open"]
    assert world.events[1][1].isdigit() and world.events[2] == ("open", "https://github.com/e2e-test-org")
    assert len(waited) == 1 and "press Enter to sign out and close the window" in waited[0]
    assert_no_secret(world.output)
    world.events.clear()
    typed = SignIn("account", LOGIN, LOGIN, PASSWORD, None, "the terminal")
    web_login(FakeBrowser(session), io, typed, "https://github.com/", until=waited.append)
    assert world.events[1] == ("login code", "123456")
    with pytest.raises(AccountError, match=f"signed in as {LOGIN}, but the account is other"):
        web_login(FakeBrowser(session), io, SignIn("account", "other", "other", PASSWORD, None, "x"), "u", until=print)


def invoke_web_login(env: dict[str, str | None], *args: str, input: str = "\n") -> Any:
    """Run ``otterdog-e2e web-login`` (``input``: the terminal's answers)."""
    from click.testing import CliRunner

    from otterdog_e2e import cli

    return CliRunner().invoke(cli.main, ["web-login", *args], env=env, input=input)


def test_web_login_command_with_an_instance(world: World, cli_env: dict[str, str | None]) -> None:
    """--target: the account of the instance in the accounts store, on the page of --url, then signed out."""
    result = invoke_web_login(cli_env, "--target", "free", "--url", "/orgs/e2e-test-org/settings")
    assert result.exit_code == 0, result.output
    assert world.events == [("login", EMAIL, PASSWORD), ("open", "https://github.com/orgs/e2e-test-org/settings")]
    assert f"admin: signing in as {EMAIL} (password from {BASE}-password)" in result.output
    assert f"admin: {LOGIN} signed out, window closed" in result.output
    assert_no_secret(result.output)
    result = invoke_web_login(cli_env, "--target", "free", "--role", "author")
    assert result.exit_code == 1 and "author: neither" in result.output


def test_web_login_command_admin_from_the_env_file(
    world: World, cli_env: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The admin signs in with the web credentials of the env file (resolved as runs resolve them), on the page of the
    organization; the accounts store is not read."""
    from otterdog_e2e import settings as settings_module

    env_file = Path(str(cli_env["HOME"])) / ".config" / "otterdog-e2e" / "free.env"
    env_file.write_text("E2E_ORG=e2e-test-org\nE2E_ADMIN_PASSWORD=pass:web/password\n")
    web = settings_module.WebCredentials("admin", LOGIN, LOGIN, "web password", SEED)
    monkeypatch.setattr(settings_module, "load_target", lambda name, settings, environ: object())
    monkeypatch.setattr(settings_module, "resolve_web_credentials", lambda target, environ: web)
    monkeypatch.setattr(settings_module, "web_credential_env_names", lambda target: {"password_env": "E2E_X_PASSWORD"})
    world.entries.clear()
    result = invoke_web_login(cli_env, "--target", "free")
    assert result.exit_code == 0, result.output
    assert world.events == [("login", LOGIN, "web password"), ("open", "https://github.com/e2e-test-org")]
    assert f"admin: signing in as {LOGIN} (password from E2E_X_PASSWORD)" in result.output


def test_web_login_command_finds_the_account_in_the_store(world: World, cli_env: dict[str, str | None]) -> None:
    """ACCOUNT (or --login) names the entries of the accounts store: its e-mail and password sign it in, nothing is
    typed but the Enter that closes the window."""
    for args in (["otterdog-e2e-free-admin"], ["--login", "otterdog-e2e-free-admin"]):
        world.events.clear()
        result = invoke_web_login(cli_env, *args)
        assert result.exit_code == 0, result.output
        assert world.events == [("login", EMAIL, PASSWORD), ("open", "https://github.com/")]
        assert f"account: signing in as {EMAIL} (password from {BASE}-password)" in result.output
        assert_no_secret(result.output)


def test_web_login_command_without_an_instance(world: World, cli_env: dict[str, str | None]) -> None:
    """An account the store does not know is typed: its login (ACCOUNT or asked), its hidden password."""
    result = invoke_web_login(cli_env, LOGIN, input=f"{PASSWORD}\n\n")
    assert result.exit_code == 0, result.output
    assert world.events == [("login", LOGIN, PASSWORD), ("open", "https://github.com/")]
    assert f"no password of {LOGIN} at {STORE}/{LOGIN}-password: it is typed" in result.output
    assert PASSWORD not in result.output
    world.events.clear()
    result = invoke_web_login(cli_env, input=f"{LOGIN}\n{PASSWORD}\n\n")
    assert result.exit_code == 0, result.output
    assert world.events[0] == ("login", LOGIN, PASSWORD)


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--role", "author"], "--role names an account of an instance: pass --target"),
        (["--target", "free", "x"], "ACCOUNT 'x' or --target"),
        (["x", "--login", "y"], "ACCOUNT 'x' or --login 'y': one account"),
        (["--login", "x", "--url", "https://example.org/"], "a page of github.com"),
    ],
)
def test_web_login_command_usage(cli_env: dict[str, str | None], args: list[str], message: str) -> None:
    """The instance names its accounts, an account needs no --role, one account at a time, the page is on
    github.com."""
    result = invoke_web_login(cli_env, *args, input=f"{PASSWORD}\n\n")
    assert result.exit_code == 2 and message in result.output


def test_web_login_command_is_refused_in_ci(cli_env: dict[str, str | None]) -> None:
    """A visible browser has no place in CI."""
    result = invoke_web_login({**cli_env, "CI": "true"}, "--login", LOGIN)
    assert result.exit_code == 1 and "refused when CI is set" in result.output


# --- setup: the web steps in the browser, --shards ------------------------------------------------------------------
def web_steps(cli_env: dict[str, str | None], stack: contextlib.ExitStack) -> Any:
    """The web steps of setup for the instance free, with the fake browser and the accounts store of cli_env."""
    from otterdog_e2e.cli import onboarding

    return onboarding._WebSteps(stack, "free", {key: value for key, value in cli_env.items() if value is not None})


def test_setup_web_steps_sign_the_store_accounts_in(
    world: World, cli_env: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each step asks first, signs the role's account of the accounts store in and does the step; a declined one, a
    role the store does not know or a failing step is left to the operator."""
    answers: list[bool] = [True, True, True, False, True]
    monkeypatch.setattr("click.confirm", lambda text, default: answers.pop(0))
    with contextlib.ExitStack() as stack:
        web = web_steps(cli_env, stack)
        assert web.join("admin", "e2e-test-org", LOGIN, public=True)
        assert web.install_app("https://github.com/apps/a/installations/new")
        assert web.confirm_app("http://127.0.0.1:8765/")
        assert not web.join("admin", "e2e-test-org", LOGIN, public=False)  # declined
        assert not web.join("author", "e2e-test-org", "e2e-author", public=True)  # not in the store: not asked
        assert not web.join("admin", "broken", LOGIN, public=True)
    logins = [event for event in world.events if event[0] == "login"]
    steps = [event for event in world.events if event[0] != "login"]
    assert logins == [("login", EMAIL, PASSWORD)] * 4
    assert steps == [
        ("join", "e2e-test-org", LOGIN, True),
        ("install", "https://github.com/apps/a/installations/new"),
        ("confirm", "http://127.0.0.1:8765/"),
    ]
    assert answers == []


def test_automatic_web_steps_ask_nothing(
    world: World, cli_env: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """automatic (setup with the accounts store): each step is done without a confirmation."""
    from otterdog_e2e.cli import onboarding

    monkeypatch.setattr("click.confirm", lambda text, default: pytest.fail(f"asked: {text}"))
    environ = {key: value for key, value in cli_env.items() if value is not None}
    with contextlib.ExitStack() as stack:
        web = onboarding._WebSteps(stack, "free", environ, automatic=True)
        assert web.join("admin", "e2e-test-org", LOGIN, public=True)
    assert ("join", "e2e-test-org", LOGIN, True) in world.events


def test_bootstrap_alone_accepts_the_invitations_in_one_firefox(
    world: World, cli_env: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """`bootstrap` without setup: with the accounts store, the invitations are accepted in Firefox (one browser for
    all, nothing asked); without the store or in CI, no browser."""
    import types

    from otterdog_e2e.cli import bootstrap as cli_bootstrap
    from otterdog_e2e.cli import onboarding

    opened: list[int] = []
    monkeypatch.setattr(
        onboarding, "_open_browser", lambda stack: opened.append(1) or FakeBrowser(FakeSession(world.events))
    )
    monkeypatch.setattr("click.confirm", lambda text, default: pytest.fail(f"asked: {text}"))
    environ = {key: value for key, value in cli_env.items() if value is not None}

    def context(**extra: str) -> Any:
        """The bits of E2EContext the join uses."""
        target = types.SimpleNamespace(name="free")
        return types.SimpleNamespace(environ={**environ, **extra}, require_target=lambda: target)

    with contextlib.ExitStack() as stack:
        join = cli_bootstrap._browser_join(context(), stack)
        assert join is not None
        assert join("admin", "e2e-test-org", LOGIN, public=True) and join("admin", "e2e-test-org", LOGIN, public=False)
        assert cli_bootstrap._browser_join(context(CI="true"), stack) is None
        assert cli_bootstrap._browser_join(context(HOME=str(world.tmp_path / "nobody")), stack) is None
    assert [event for event in world.events if event[0] == "join"] == [
        ("join", "e2e-test-org", LOGIN, True),
        ("join", "e2e-test-org", LOGIN, False),
    ]
    assert opened == [1]


def invoke_setup(env: dict[str, str | None], *args: str, input: str = "") -> Any:
    """Run ``otterdog-e2e setup``."""
    from click.testing import CliRunner

    from otterdog_e2e import cli

    return CliRunner().invoke(cli.main, ["setup", *args], env=env, input=input)


def test_setup_shards_sets_up_every_shard_instance(
    cli_env: dict[str, str | None], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--shards: one setup per shard instance in the map's order; with the accounts store nothing is asked: an instance
    set up already runs again until its setup finished (it is then in @shards); without it (--no-browser), an
    instance set up already runs again only when confirmed; a stopped one names how to resume; --target and --shards
    exclude each other."""
    from otterdog_e2e.batch import list_file
    from otterdog_e2e.cli import onboarding

    done: list[tuple[str, str | None]] = []
    monkeypatch.setattr(
        onboarding, "_shard_instances", lambda environ: [("enterprise", "enterprise"), ("free", "repos")]
    )
    monkeypatch.setattr(onboarding, "_set_up_already", lambda instance, shard, environ: instance == "enterprise")
    monkeypatch.setattr(
        onboarding, "_setup_instance", lambda options, **kw: done.append((options.instance, options.shard))
    )
    result = invoke_setup(cli_env, "--shards")
    assert result.exit_code == 0, result.output
    assert done == [("enterprise", "enterprise"), ("free", "repos")]  # enterprise never finished its setup
    assert "\u2501\u2501 [1/2] enterprise \u2501" in result.output
    assert "\u2501\u2501 [2/2] free (shard repos) \u2501" in result.output
    assert "otterdog-e2e run --target @shards --parallel 2" in result.output
    shards = list_file("shards", {"HOME": str(cli_env["HOME"])})
    shards.parent.mkdir(parents=True)
    shards.write_text("# the instances of @shards\nenterprise\n")
    done.clear()
    result = invoke_setup(cli_env, "--shards")
    assert result.exit_code == 0 and done == [("free", "repos")], result.output
    assert "\u2013 kept as it is (setup --target enterprise runs it again)" in result.output
    assert "run its setup again?" not in result.output
    done.clear()
    result = invoke_setup(cli_env, "--shards", "--no-browser", input="\n")
    assert result.exit_code == 0 and done == [("free", "repos")], result.output
    assert "enterprise is set up already: run its setup again? [y/N]" in result.output

    def stopped(options: Any, **kw: Any) -> None:
        raise click.ClickException("no admin token")

    monkeypatch.setattr(onboarding, "_setup_instance", stopped)
    result = invoke_setup(cli_env, "--shards", "--no-browser", input="y\n")
    assert result.exit_code == 1 and "setup of enterprise stopped: no admin token" in result.output
    for args in ([], ["--target", "free", "--shards"], ["--shards", "--org", "x"]):
        assert invoke_setup(cli_env, *args).exit_code == 2


def test_setup_lines_get_their_marks_in_colour(monkeypatch: pytest.MonkeyPatch) -> None:
    """In a terminal: titles bold, the done mark green, the attention mark yellow, skipped and saved lines dim, the
    rest as it is (click drops the styles when the output is no terminal)."""
    from otterdog_e2e.cli import onboarding

    printed: list[str] = []
    monkeypatch.setattr(click, "echo", printed.append)
    lines = ["▸ Organization", "  ✓ e2e-test-org (id 1)", "  ! token refused", "    saved E2E_ORG", "plain"]
    for line in lines:
        onboarding._setup_echo(line)
    assert printed == [
        click.style("▸ Organization", bold=True),
        "  " + click.style("✓", fg="green", bold=True) + " e2e-test-org (id 1)",
        "  " + click.style("!", fg="yellow", bold=True) + " token refused",
        click.style("    saved E2E_ORG", dim=True),
        "plain",
    ]


def test_the_instance_of_a_shard_is_the_one_that_selects_it(cli_env: dict[str, str | None], tmp_path: Path) -> None:
    """An instance whose E2E_SHARD names a shard serves it (the existing free organization as repos), the others are
    named after their shard."""
    from otterdog_e2e.cli import onboarding

    config = Path(str(cli_env["HOME"])) / ".config" / "otterdog-e2e"
    (config / "free.env").write_text("E2E_PROFILE=free\nE2E_SHARD=repos\n")
    environ = {key: value for key, value in cli_env.items() if value is not None}
    instances = onboarding._shard_instances(environ)
    assert instances == [
        ("enterprise", "enterprise"),
        ("webapp", "webapp"),
        ("org-level", "org-level"),
        ("free", "repos"),
        ("automation", "automation"),
    ]
    assert not onboarding._set_up_already("free", "repos", environ)
    (config / "free.env").write_text("E2E_SHARD=repos\nE2E_ORG_ID=1\nE2E_ADMIN_TOKEN=pass:x\n")
    assert onboarding._set_up_already("free", "repos", environ)
    assert not onboarding._set_up_already("free", "webapp", environ)


# --- onboard.browser without Playwright -----------------------------------------------------------------------------
def test_browser_without_playwright_names_the_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser module imports without Playwright (an optional extra); opening the browser then fails with the
    install commands, Firefox going to PLAYWRIGHT_BROWSERS_PATH when it is set, else to Playwright's own cache."""
    import sys

    from otterdog_e2e.onboard.browser import CLASSIC_TOKEN_RE, PlaywrightBrowser

    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    monkeypatch.delenv("PLAYWRIGHT_BROWSERS_PATH", raising=False)
    with pytest.raises(AccountError, match="Playwright is not installed: install the browser extra") as caught:
        PlaywrightBrowser(pause=lambda message: None).__enter__()
    assert "make init" in str(caught.value) and "PLAYWRIGHT_BROWSERS_PATH" not in str(caught.value)
    browser = PlaywrightBrowser(browsers_path=tmp_path / "ms-playwright", pause=lambda message: None)
    with pytest.raises(AccountError, match="Playwright is not installed") as caught:
        browser.__enter__()
    assert f"PLAYWRIGHT_BROWSERS_PATH={tmp_path / 'ms-playwright'} .venv/bin/python" in str(caught.value)
    assert CLASSIC_TOKEN_RE.fullmatch(NEW_TOKEN) and not CLASSIC_TOKEN_RE.fullmatch("github_pat_" + "x" * 30)


GNOME_46_XSETTINGS = """<?xml version="1.0" encoding="UTF-8"?>
<schemalist>
  <schema gettext-domain="gnome-settings-daemon" id="org.gnome.settings-daemon.plugins.xsettings" path="/x/">
    <key name="overrides" type="a{sv}">
      <default>{}</default>
    </key>
  </schema>
  <schema id="org.gnome.settings-daemon.plugins.xsettings.deprecated">
    <key name="antialiasing" enum="org.gnome.settings-daemon.GsdFontAntialiasingMode">
      <default>'grayscale'</default>
    </key>
  </schema>
</schemalist>
"""


def test_firefox_gets_the_font_keys_gnome_46_moved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """GNOME 46 moved antialiasing to a deprecated schema, where Playwright's Firefox does not look (it aborts): the
    compat directory has the xsettings schema with the key back, compiled once; nothing when the system schema has it,
    or has no such schema, or glib-compile-schemas is missing."""
    from otterdog_e2e.onboard import browser as browser_module

    system, target = tmp_path / "system", tmp_path / "compat"
    system.mkdir()
    (system / browser_module.GSD_ENUMS).write_text("<schemalist/>\n")
    (system / f"{browser_module.XSETTINGS_SCHEMA}.gschema.xml").write_text(GNOME_46_XSETTINGS)
    compiles: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        """glib-compile-schemas: the compiled file."""
        compiles.append(argv)
        (Path(argv[1]) / "gschemas.compiled").write_text("compiled")
        return type("Done", (), {"returncode": 0})()

    monkeypatch.setattr(browser_module.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(browser_module.procs, "run", run)
    assert browser_module.gsettings_compat_dir(target, system) == target
    merged = (target / f"{browser_module.XSETTINGS_SCHEMA}.gschema.xml").read_text()
    main = merged.split("</schema>")[0]
    assert 'name="overrides"' in main and 'name="antialiasing"' in main and merged.count("</schema>") == 2
    assert browser_module.gsettings_compat_dir(target, system) == target and len(compiles) == 1  # built once
    monkeypatch.setattr(browser_module.shutil, "which", lambda name: None)
    assert browser_module.gsettings_compat_dir(tmp_path / "other", system) is None  # no compiler
    (system / f"{browser_module.XSETTINGS_SCHEMA}.gschema.xml").write_text(merged)
    assert browser_module.gsettings_compat_dir(target, system) is None  # the system schema has the keys
    assert browser_module.gsettings_compat_dir(target, tmp_path / "none") is None  # no GNOME schemas


def test_a_firefox_that_stops_names_what_it_printed() -> None:
    """A launch failure names Firefox's last error line; a missing Firefox is told apart (the install hint)."""
    from otterdog_e2e.onboard.browser import MISSING_FIREFOX_RE, _launch_error

    error = Exception(
        "BrowserType.launch: Failed to launch the browser process.\nBrowser logs:\n"
        "[pid=1][err] ###!!! ASSERTION: glib assertion\n[pid=1][err] \n"
        "[pid=1][err] GLib-GIO-ERROR **: Settings schema does not contain a key named 'antialiasing'\n"
        "[pid=1] <process did exit: exitCode=null, signal=SIGTRAP>"
    )
    assert _launch_error(error) == "GLib-GIO-ERROR **: Settings schema does not contain a key named 'antialiasing'"
    assert _launch_error(Exception("Timeout 180000ms exceeded.\nmore")) == "Timeout 180000ms exceeded."
    assert MISSING_FIREFOX_RE.search("BrowserType.launch: Executable doesn't exist at /x/firefox")
    assert not MISSING_FIREFOX_RE.search(str(error))


# --- onboard.browser: the setup key of the 2FA enrollment -----------------------------------------------------------
@pytest.mark.parametrize(
    "shown",
    [
        SHOWN_SEED,
        SEED,
        f"{SEED}\nCopied!",
        SHOWN_SEED.replace(" ", "\u200b"),
        f"Your two-factor secret\n{SEED[:8]}\u2013{SEED[8:]}\nClose",
        f"otpauth://totp/GitHub:{LOGIN}?secret={SEED}&amp;issuer=GitHub",
    ],
)
def test_the_setup_key_is_read_from_what_the_dialog_shows(shown: str) -> None:
    """The key in the texts of the setup key dialog: grouped or not, between invisible characters, dashes, words or
    in an otpauth:// URI."""
    from otterdog_e2e.onboard.browser import setup_key_in

    assert setup_key_in(["", "Loading", shown]) == SEED


def test_texts_without_a_setup_key_are_described_not_quoted() -> None:
    """No key in short, lower-case or non base32 texts; the description gives lengths and kinds, never the text."""
    from otterdog_e2e.onboard.browser import describe_key_texts, setup_key_in

    assert setup_key_in(["", "123456", "Your two-factor secret", SEED[:-1] + "0", SEED.lower()]) is None
    text = describe_key_texts([SEED[:4] + "\u200b" + SEED[4:8] + "!", ""])
    assert text == "10 characters (digits 2-7, exclamation mark, upper-case letters, zero width space); 0 characters"
    assert describe_key_texts([]) == "no setup key element"


class KeyPage:
    """GitHub's 2FA setup page as PlaywrightSession.setup_key reads it: the key element shows ``shown`` in turn (the
    last one stays), the dialog nothing, the page source ``source``."""

    def __init__(self, shown: list[str], source: str = "") -> None:
        """The successive texts of the key element."""
        self.shown, self.source, self.url, self.waits = list(shown), source, "about:blank", 0

    def goto(self, url: str) -> None:
        """Open ``url``."""
        self.url = url

    def wait_for_load_state(self) -> None:
        """Loaded at once."""

    def wait_for_timeout(self, timeout: float) -> None:
        """Count the waits instead."""
        self.waits += 1

    def content(self) -> str:
        """The page source."""
        return self.source

    def key_texts(self) -> list[str]:
        """The text of the key element now; the next read shows the next one."""
        return [self.shown.pop(0) if len(self.shown) > 1 else self.shown[0]]

    def get_by_role(self, role: str, name: Any) -> Any:
        """The setup key button (no "Confirm access" heading)."""
        return KeyLocator(lambda: [] if role == "heading" else ["setup key"])

    def locator(self, selector: str) -> Any:
        """The key element, else the dialog around it."""
        from otterdog_e2e.onboard.browser import SETUP_KEY_SELECTOR

        return KeyLocator(self.key_texts if selector == SETUP_KEY_SELECTOR else list)


class KeyLocator:
    """A locator whose elements show ``texts()``."""

    def __init__(self, texts: Callable[[], list[str]]) -> None:
        """The texts of its elements."""
        self.texts = texts
        self.first = self

    def count(self) -> int:
        """Its elements."""
        return len(self.texts())

    def is_visible(self) -> bool:
        """Visible when it matches."""
        return True

    def click(self) -> None:
        """Clicked."""

    def all_inner_texts(self) -> list[str]:
        """The texts as shown."""
        return self.texts()

    def all_text_contents(self) -> list[str]:
        """The texts as written (read in the same turn as the texts shown)."""
        return []

    def evaluate_all(self, script: str) -> list[str]:
        """The text nodes (none apart)."""
        return []


def test_the_setup_key_is_read_again_until_github_filled_it_in(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key element is read every half second until it holds a key, else the page's otpauth:// URI; without a key
    in time, the key is asked with a description of what the element showed (never its text)."""
    import sys
    import types

    from otterdog_e2e.onboard import browser as browser_module

    monkeypatch.setitem(sys.modules, "playwright.sync_api", types.SimpleNamespace(Error=RuntimeError))  # no extra
    asked: list[str] = []

    def ask_key(problem: str) -> str:
        """The operator pastes the key."""
        asked.append(problem)
        return SHOWN_SEED

    page = KeyPage(["", "Loading", SHOWN_SEED])
    assert browser_module.PlaywrightSession(page).setup_key(ask_key) == SEED
    assert page.url == browser_module.TWO_FACTOR_SETUP_URL and page.waits == 2
    uri = f'<a href="otpauth://totp/GitHub:{LOGIN}?secret={SEED}&amp;issuer=GitHub">'
    assert browser_module.PlaywrightSession(KeyPage([""], uri)).setup_key(ask_key) == SEED
    monkeypatch.setattr(browser_module, "SETUP_KEY_TIMEOUT", 0.0)
    assert browser_module.PlaywrightSession(KeyPage(["123890"])).setup_key(ask_key) == SHOWN_SEED
    assert asked == ["GitHub's setup key could not be read (6 characters (digits 0 1 8 9, digits 2-7))"]
