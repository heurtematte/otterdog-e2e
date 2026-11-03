"""onboard.accounts: machine accounts set up in the browser (sign-in, 2FA enrollment, classic token), their secrets in
the accounts store of the setup configuration file (pass or Vault, one naming convention); the browser and the store
are fakes, the order of the writes is checked against the browser steps (nothing may lock an account out)."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.onboard import accounts as accounts_module
from otterdog_e2e.onboard.accounts import (
    DEFAULT_ITEMS,
    AccountError,
    AccountsConfig,
    AccountSetup,
    AccountsIO,
    cbi_password_store_dir,
    load_accounts_config,
    parse_accounts_config,
    pass_environ,
    setup_config_path,
    totp_code,
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


def test_cbi_config_gives_the_password_store(tmp_path: Path) -> None:
    """ci-admin's ~/.cbi/config of the environment's HOME, unless PASSWORD_STORE_DIR is set; no file: unchanged."""
    assert cbi_password_store_dir(tmp_path) is None
    (tmp_path / ".cbi").mkdir()
    (tmp_path / ".cbi" / "config").write_text(json.dumps({"password-store": {"cbi-dir": "/srv/cbi-pass"}}))
    assert cbi_password_store_dir(tmp_path) == "/srv/cbi-pass"
    assert pass_environ({"HOME": str(tmp_path)})["PASSWORD_STORE_DIR"] == "/srv/cbi-pass"
    assert pass_environ({"HOME": str(tmp_path), "PASSWORD_STORE_DIR": "/mine"})["PASSWORD_STORE_DIR"] == "/mine"


# --- fakes ----------------------------------------------------------------------------------------------------------
@dataclass
class FakeSession:
    """A browser session: records each step in the shared ``events``."""

    events: list[tuple[Any, ...]]
    login_as: str = LOGIN
    enabled: bool = False
    codes: list[str] = field(default_factory=lambda: list(CODES))
    asked_login_code: bool = False

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
    ) -> None:
        """Setup key, code, recovery codes, acknowledgement."""
        keep_seed(SHOWN_SEED)
        self.events.append(("submit code", code(SHOWN_SEED)))
        keep_recovery_codes(self.codes)
        self.events.append(("acknowledge",))
        self.enabled = True

    def classic_token(self, *, note: str, url: str, days: int) -> str:
        """A new token value."""
        self.events.append(("token", note, url, days))
        return NEW_TOKEN


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

    def resolve(value: str, environ: object) -> str:
        """entries[value]."""
        if value not in state.entries:
            raise VaultError(f"{value}: is not in the password store")
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
    assert days == 90 and browser.opened == 1
    assert_no_secret(world.output)
    assert f"stored {TOKEN_REF}" in world.output  # logins and e-mails are no secrets: references keep them


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
    """The classic form offers 7, 30, 60 and 90 days."""
    with pytest.raises(AccountError, match="7, 30, 60, 90 days"):
        world.setup(FakeSession(world.events), days=366)


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


# --- onboard.browser without Playwright -----------------------------------------------------------------------------
def test_browser_without_playwright_names_the_install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The browser module imports without Playwright (an optional extra); opening the browser then fails with the
    install commands, Firefox going to the web-UI tier's browsers path."""
    import sys

    from otterdog_e2e.onboard.browser import CLASSIC_TOKEN_RE, PlaywrightBrowser

    monkeypatch.setitem(sys.modules, "playwright", None)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", None)
    browser = PlaywrightBrowser(browsers_path=tmp_path / "ms-playwright", pause=lambda message: None)
    with pytest.raises(AccountError, match="Playwright is not installed: install the browser extra") as caught:
        browser.__enter__()
    assert f"PLAYWRIGHT_BROWSERS_PATH={tmp_path / 'ms-playwright'}" in str(caught.value)
    assert CLASSIC_TOKEN_RE.fullmatch(NEW_TOKEN) and not CLASSIC_TOKEN_RE.fullmatch("github_pat_" + "x" * 30)
