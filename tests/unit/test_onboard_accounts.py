"""onboard.accounts: machine accounts set up in the browser (sign-in, 2FA enrollment, classic token) with their secrets
in pass (ci-admin layout); the browser and pass are fakes, the order of the writes is checked against the browser
steps (nothing may lock an account out)."""

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
    AccountError,
    AccountSetup,
    AccountsIO,
    MachineAccount,
    cbi_password_store_dir,
    check_pass_dir,
    pass_dir_env,
    pass_environ,
    token_entry,
    totp_code,
)
from otterdog_e2e.testing.fakes import FakeGitHubHttp
from otterdog_e2e.vaults import VaultError

DIR = "bots/technology.otterdog-e2e-admin/github.com"
ACCOUNT = MachineAccount("admin", DIR)
LOGIN, PASSWORD = "e2e-admin", "correct horse battery staple"
SHOWN_SEED, SEED = "JBSW Y3DP EHPK 3PXP", "JBSWY3DPEHPK3PXP"
CODES = ["aaaa-1111", "bbbb-2222"]
NEW_TOKEN, OLD_TOKEN = "ghp_" + "N" * 36, "ghp_" + "O" * 36
ADMIN_SCOPES = {"repo", "workflow", "admin:org", "admin:org_hook", "delete_repo"}
TOKEN_REF = f"pass:{DIR}/otterdog-e2e-org2-token"


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


def test_pass_names() -> None:
    """E2E_<ROLE>_PASS_DIR and the per-instance token entry."""
    assert pass_dir_env("admin") == "E2E_ADMIN_PASS_DIR"
    assert pass_dir_env("config_reader") == "E2E_CONFIG_READER_PASS_DIR"
    assert token_entry("org2") == "otterdog-e2e-org2-token"
    assert ACCOUNT.ref("password") == f"pass:{DIR}/password"


@pytest.mark.parametrize("value", ["", "/", "bots/../x", "bots/a b", "bots//x"])
def test_invalid_pass_dirs(value: str) -> None:
    """Empty, '..', blanks and empty parts are refused."""
    with pytest.raises(AccountError):
        check_pass_dir(value)


def test_pass_dir_slashes_are_stripped() -> None:
    """Leading and trailing slashes are ignored."""
    assert check_pass_dir(f"/{DIR}/") == DIR


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
    """pass entries, events, echoed lines and the GitHub accounts behind tokens."""

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
        """AccountSetup of instance org2 with the fakes."""
        browser = FakeBrowser(session)
        io = AccountsIO(echo=self.echoed.append, secret_prompt=self.secret_prompt, prompt=lambda text: "")
        setup = AccountSetup(
            "org2",
            org="e2e-test-org",
            environ={"HOME": str(self.tmp_path)},
            browser=browser,
            io=io,
            http=self.http,
            **options,
        )
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
    """An account with username and password in pass; reads and writes go to ``entries`` (writes are events)."""
    state = World(tmp_path)
    state.entries.update({f"pass:{DIR}/username": LOGIN, f"pass:{DIR}/password": PASSWORD})

    def resolve(value: str, environ: object) -> str:
        """entries[value]."""
        if value not in state.entries:
            raise VaultError(f"{value}: is not in the password store")
        return state.entries[value]

    def store(value: str, secret: str, environ: object) -> None:
        """entries[value] = secret, recorded."""
        state.entries[value] = secret
        state.events.append(("write", value.rsplit("/", 1)[1]))

    monkeypatch.setattr(accounts_module, "resolve", resolve)
    monkeypatch.setattr(accounts_module, "store", store)
    return state


def assert_no_secret(text: str) -> None:
    """No password, key, code or token is echoed."""
    for secret in (PASSWORD, SEED, *CODES, NEW_TOKEN, OLD_TOKEN):
        assert secret not in text


# --- one account ----------------------------------------------------------------------------------------------------
def test_fresh_account_gets_2fa_and_its_token(world: World) -> None:
    """No 2FA, no token: the key is stored before its code is submitted, the recovery codes before they are
    acknowledged, the token as soon as it is shown; its note is the description of the prefilled URLs."""
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
        "write otterdog-e2e-org2-token",
    ]
    assert world.entries[f"pass:{DIR}/2FA-seed"] == SEED
    assert world.entries[f"pass:{DIR}/2FA-recovery-codes"] == "\n".join(CODES)
    assert world.entries[TOKEN_REF] == NEW_TOKEN
    code = next(event for event in world.events if event[0] == "submit code")[1]
    assert code.isdigit() and len(code) == 6
    _, note, url, days = next(event for event in world.events if event[0] == "token")
    assert note.startswith("otterdog-e2e admin of the test organization e2e-test-org (instance org2)")
    assert url.startswith("https://github.com/settings/tokens/new?scopes=repo,workflow,admin:org,admin:org_hook,")
    assert days == 90 and browser.opened == 1
    assert_no_secret(world.output)
    assert f"stored {TOKEN_REF}" in world.output  # the login is no secret: paths and messages keep it


def test_a_complete_account_needs_no_browser(world: World) -> None:
    """A stored key and a valid classic token of the account with the role's scopes: nothing to do."""
    world.entries.update({f"pass:{DIR}/2FA-seed": SEED, TOKEN_REF: OLD_TOKEN})
    world.tokens[OLD_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    setup, browser = world.setup(FakeSession(world.events))
    result = setup.setup(ACCOUNT)
    assert (result.token_ref, result.token_created, result.enrolled) == (TOKEN_REF, False, False)
    assert browser.opened == 0 and not world.events
    assert "nothing to do" in world.output


@pytest.mark.parametrize(
    ("owner", "scopes", "problem"),
    [
        ("someone-else", ADMIN_SCOPES, "it belongs to someone-else, not e2e-admin"),
        (LOGIN, {"repo"}, "it lacks workflow, admin:org, admin:org_hook, delete_repo"),
        (LOGIN, None, "it is not a classic token"),
        ("", None, "is not usable (GET "),
    ],
)
def test_an_unusable_stored_token_is_replaced(world: World, owner: str, scopes: set[str] | None, problem: str) -> None:
    """A token of another account, without the role's scopes, fine-grained or revoked is replaced (2FA kept)."""
    world.entries.update({f"pass:{DIR}/2FA-seed": SEED, TOKEN_REF: OLD_TOKEN})
    if owner:
        world.tokens[OLD_TOKEN] = (owner, scopes)
    setup, _ = world.setup(FakeSession(world.events, enabled=True))
    result = setup.setup(ACCOUNT)
    assert result.token_created and not result.enrolled and world.entries[TOKEN_REF] == NEW_TOKEN
    assert problem in world.output and "a new one is created" in world.output


def test_rotate_replaces_a_valid_token(world: World) -> None:
    """--rotate: a new token although the stored one is valid."""
    world.entries.update({f"pass:{DIR}/2FA-seed": SEED, TOKEN_REF: OLD_TOKEN})
    world.tokens[OLD_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    setup, _ = world.setup(FakeSession(world.events, enabled=True), rotate=True)
    assert setup.setup(ACCOUNT).token_created and world.entries[TOKEN_REF] == NEW_TOKEN


def test_a_valid_token_without_the_key_checks_2fa_only(world: World) -> None:
    """A valid token but no key in pass: the browser checks 2FA (enrolled here) and keeps the token."""
    world.entries[TOKEN_REF] = OLD_TOKEN
    world.tokens[OLD_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    setup, _ = world.setup(FakeSession(world.events))
    result = setup.setup(ACCOUNT)
    assert result.enrolled and not result.token_created and world.entries[TOKEN_REF] == OLD_TOKEN
    assert not [event for event in world.events if event[0] == "token"]


def test_2fa_enabled_without_its_key_is_refused(world: World) -> None:
    """2FA enabled on GitHub but no key in pass: the account cannot be completed (nothing guessed)."""
    setup, _ = world.setup(FakeSession(world.events, enabled=True))
    with pytest.raises(AccountError, match=r"2FA is enabled but pass:.*/2FA-seed does not exist"):
        setup.setup(ACCOUNT)


def test_a_login_code_needs_the_key(world: World) -> None:
    """GitHub asks a 2FA code at sign-in and pass has no key: AccountError naming the entry."""
    setup, _ = world.setup(FakeSession(world.events, enabled=True, asked_login_code=True))
    with pytest.raises(AccountError, match=r"asks a 2FA code but pass:.*/2FA-seed does not exist"):
        setup.setup(ACCOUNT)


def test_the_login_code_comes_from_the_stored_key(world: World) -> None:
    """With the key in pass the sign-in code is its current TOTP code."""
    world.entries[f"pass:{DIR}/2FA-seed"] = SHOWN_SEED  # normalized when read
    setup, _ = world.setup(FakeSession(world.events, enabled=True, asked_login_code=True))
    setup.setup(ACCOUNT)
    code = next(event for event in world.events if event[0] == "login code")[1]
    assert code.isdigit() and len(code) == 6


def test_another_signed_in_account_is_refused(world: World) -> None:
    """The browser shows another login than pass names: nothing is enrolled or created."""
    setup, _ = world.setup(FakeSession(world.events, login_as="someone-else"))
    with pytest.raises(AccountError, match="signed in as someone-else"):
        setup.setup(ACCOUNT)
    assert [event[0] for event in world.events] == ["login"]


def test_a_missing_password_is_asked_once_and_stored(world: World) -> None:
    """No password entry: a hidden prompt, stored before the sign-in."""
    del world.entries[f"pass:{DIR}/password"]
    world.secrets.append(PASSWORD)
    setup, _ = world.setup(FakeSession(world.events))
    setup.setup(ACCOUNT)
    assert world.events[0] == ("write", "password") and world.events[1][0] == "login"
    assert_no_secret(world.output)


def test_no_login_is_refused(world: World) -> None:
    """Neither a username entry nor E2E_<ROLE>_LOGIN."""
    del world.entries[f"pass:{DIR}/username"]
    setup, _ = world.setup(FakeSession(world.events))
    with pytest.raises(AccountError, match="no login in"):
        setup.setup(ACCOUNT)


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
    """A tmp HOME, no CI, and the fake browser instead of Firefox."""
    from otterdog_e2e.cli import onboarding as cli_onboarding

    monkeypatch.setattr(cli_onboarding, "_open_browser", lambda stack: FakeBrowser(FakeSession(world.events)))
    monkeypatch.setattr(accounts_module, "_default_http", world.http)
    return {"HOME": str(tmp_path / "home"), "CI": None, "GITHUB_ACTIONS": None, "PASSWORD_STORE_DIR": None}


def invoke(env: dict[str, str | None], *args: str) -> Any:
    """Run ``otterdog-e2e accounts``."""
    from click.testing import CliRunner

    from otterdog_e2e import cli

    return CliRunner().invoke(cli.main, ["accounts", *args], env=env)


def test_accounts_command_sets_up_the_role_and_writes_its_pass_dir(
    world: World, cli_env: dict[str, str | None]
) -> None:
    """--pass-dir is written as E2E_ADMIN_PASS_DIR; the token goes to pass only; setup is the next step."""
    result = invoke(cli_env, "--target", "org2", "--pass-dir", f"admin={DIR}")
    assert result.exit_code == 0, result.output
    env_file = Path(str(cli_env["HOME"])) / ".config" / "otterdog-e2e" / "org2.env"
    text = env_file.read_text()
    assert f"E2E_ADMIN_PASS_DIR={DIR}" in text and "TOKEN" not in text
    assert world.entries[TOKEN_REF] == NEW_TOKEN
    assert f"admin: {LOGIN}: token created at {TOKEN_REF}, 2FA enrolled" in result.output
    assert "next: otterdog-e2e setup --target org2" in result.output
    assert_no_secret(result.output)
    world.tokens[NEW_TOKEN] = (LOGIN, set(ADMIN_SCOPES))
    again = invoke(cli_env, "--target", "org2")  # the stored pass directory selects the role
    assert again.exit_code == 0, again.output
    assert f"admin: {LOGIN} has its 2FA key and a valid token in {TOKEN_REF}: nothing to do" in again.output


@pytest.mark.parametrize(
    ("args", "message"),
    [
        ((), "no pass directory for any role"),
        (("--role", "author"), "no pass directory for author"),
        (("--pass-dir", "nobody=bots/x/github.com"), "expected ROLE=DIR with a role of setup"),
        (("--pass-dir", "admin=bots/../x"), "not a pass directory"),
    ],
)
def test_accounts_command_usage(cli_env: dict[str, str | None], args: tuple[str, ...], message: str) -> None:
    """A role needs a pass directory; --pass-dir takes ROLE=DIR with a valid directory."""
    result = invoke(cli_env, "--target", "org2", *args)
    assert result.exit_code == 2 and message in result.output


def test_accounts_command_is_refused_in_ci(cli_env: dict[str, str | None]) -> None:
    """A visible browser has no place in CI."""
    result = invoke({**cli_env, "CI": "true"}, "--target", "org2", "--pass-dir", f"admin={DIR}")
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
