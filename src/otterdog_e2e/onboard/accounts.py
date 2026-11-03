"""Machine accounts in the browser (``otterdog-e2e accounts``, ``setup --browser``; docs/onboarding.md, "Machine accounts
in the browser").

For each role it logs in to github.com as the role's machine account, enrolls two-factor authentication (TOTP) when
the account has none and creates the role's classic token (the scopes of onboard.tokens, the note of the prefilled
URLs, an expiration), driving Firefox through Playwright (onboard.browser).

Where the secrets of the accounts live is the ``accounts`` section of the setup configuration file
(``~/.config/otterdog-e2e/setup.yaml``, or E2E_SETUP_CONFIG; AccountsConfig): a ``store`` (``pass:<directory>`` or
``vault:<secret path>``), the name of an entry (``entry``, default ``otterdog-e2e-{instance}-{role}-{item}``, the role
spelled with dashes: ``config-reader``) and the names of the items (``items``, default the names of
eclipse-cbi/ci-admin: ``username``, ``email``, ``password``, ``2FA-seed``, ``2FA-recovery-codes``, ``api-token``). The
reference of an item is ``<store>/<entry>``, one convention for both: a pass entry under the directory, or the field
``<entry>`` of the Vault KV v2 secret ``<secret path>`` (vaults.parse splits at the last ``/``), e.g.
``pass:bots/technology.csi/github.com/otterdog-e2e-free-admin-password`` and
``vault:otterdog-e2e/technology.csi/github/otterdog-e2e-free-admin-password``. ``set`` gives every instance the
accounts of one set: ``set: free`` makes ``{instance}`` free for all of them, so the test organizations of the shards
share one set of machine accounts (otterdog-e2e-free-admin...).

* the login: the username item, else E2E_<ROLE>_LOGIN, else the account is signed in with its e-mail item (GitHub
  accepts both) and the login GitHub shows is used;
* the password: read (a missing one is asked once, hidden, and stored);
* the 2FA key: read for the sign-in codes, written by the enrollment (normalized base32, as ``oathtool -b`` reads it);
* the recovery codes: written by the enrollment (one code per line);
* the token: the role's classic token, written as soon as GitHub shows it.

``pass`` runs with PASSWORD_STORE_DIR, else the ``password-store.cbi-dir`` of ``~/.cbi/config`` as ci-admin does
(cbi_password_store_dir). Writes go through vaults.store (stdin or the Vault API, read back), never a shell.

The token is written to the accounts store only: the env file gets it through setup, whose checks (token kind and
scopes, isolation, owner membership) decide; setup finds it there without a prompt (SetupWizard.from_account).
Writes are ordered so that an interruption never locks an account out: the 2FA key is stored before the code that
enables it is submitted, the recovery codes before they are acknowledged, the token as soon as GitHub shows it
(once). What stays a person's: creating the account (GitHub's terms), a captcha, and the code GitHub e-mails to a new
device (asked in the terminal), hence a visible window. Refused in CI.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import string
import struct
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from otterdog_e2e.onboard.tokens import (
    DEFAULT_EXPIRES_IN,
    ROLE_TOKENS,
    classic_token_url,
    missing_scopes,
    token_description,
    token_name,
)
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.settings import WebCredentialsError, normalize_totp_seed, user_config_dir
from otterdog_e2e.vaults import VaultError, resolve, store

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp

SETUP_CONFIG_FILE = "setup.yaml"  # in ~/.config/otterdog-e2e (user_config_dir)
SETUP_CONFIG_ENV = "E2E_SETUP_CONFIG"  # another path of the setup configuration file
STORE_PROVIDERS = ("pass", "vault")
# item -> its name in the store (ci-admin's names); the items of an account
DEFAULT_ITEMS: Mapping[str, str] = {
    "username": "username",
    "email": "email",
    "password": "password",
    "totp_seed": "2FA-seed",
    "recovery_codes": "2FA-recovery-codes",
    "token": "api-token",
}
DEFAULT_ENTRY = "otterdog-e2e-{instance}-{role}-{item}"
ENTRY_FIELDS = frozenset({"instance", "role", "item"})
CBI_CONFIG = "~/.cbi/config"  # ci-admin's configuration: {"password-store": {"cbi-dir": ...}}
CLASSIC_EXPIRATIONS = (7, 30, 60, 90)  # days the classic token form offers besides a custom date and none
TOTP_PERIOD, TOTP_DIGITS = 30, 6
_PATH_RE = re.compile(r"^[A-Za-z0-9_.@-]+(/[A-Za-z0-9_.@-]+)*$")


class AccountError(RuntimeError):
    """A machine account cannot be set up, or the setup configuration is invalid (never a secret in the message)."""


def _check_path(value: str, what: str) -> str:
    """``value`` when it is a relative path of safe names (AccountError for '..', blanks or empty parts)."""
    if not _PATH_RE.match(value) or any(part in (".", "..") for part in value.split("/")):
        raise AccountError(f"{what}: not a path of names ([A-Za-z0-9_.@-], separated by '/'): {value!r}")
    return value


@dataclass(frozen=True)
class AccountsConfig:
    """The ``accounts`` section of the setup configuration file (module docstring)."""

    store: str
    entry: str = DEFAULT_ENTRY
    items: Mapping[str, str] = field(default_factory=lambda: dict(DEFAULT_ITEMS))
    source: str = "setup configuration"
    set: str | None = None  # the {instance} of every instance: one set of accounts for all the organizations

    @property
    def provider(self) -> str:
        """``pass`` or ``vault``."""
        return self.store.partition(":")[0]

    def account(self, instance: str, role: str) -> MachineAccount:
        """The account of ``role`` in ``instance`` (in the shared ``set`` when there is one)."""
        return MachineAccount(role, self.set or instance, self)

    def named(self, name: str) -> MachineAccount:
        """The account whose entries start with ``name``, what the entry template gives before the item (e.g.
        otterdog-e2e-free-admin: web-login without an instance)."""
        return MachineAccount("account", "", self, _check_path(name, "the account name"))


def parse_accounts_config(data: Any, source: str) -> AccountsConfig:
    """AccountsConfig of the ``accounts`` mapping (AccountError naming ``source`` for anything unexpected)."""
    if not isinstance(data, Mapping):
        raise AccountError(f"{source}: accounts must be a mapping with a store")
    unknown = sorted(set(data) - {"store", "entry", "items", "set"})
    if unknown:
        raise AccountError(f"{source}: unknown key(s) in accounts: {', '.join(map(str, unknown))}")
    raw_store = str(data.get("store") or "").strip()
    provider, sep, path = raw_store.partition(":")
    if not sep or provider not in STORE_PROVIDERS:
        raise AccountError(f"{source}: accounts.store must be pass:<directory> or vault:<secret path>")
    store_value = f"{provider}:{_check_path(path.strip('/'), f'{source}: accounts.store')}"
    entry = str(data.get("entry") or DEFAULT_ENTRY)
    try:
        names = {name for _, name, _, _ in string.Formatter().parse(entry) if name is not None}
    except ValueError as exc:
        raise AccountError(f"{source}: accounts.entry: {exc}") from None
    if not names <= ENTRY_FIELDS or "item" not in names:
        raise AccountError(
            f"{source}: accounts.entry takes {{instance}}, {{role}} and {{item}} (which it needs), got {entry!r}"
        )
    items = dict(DEFAULT_ITEMS)
    given = data.get("items") or {}
    if not isinstance(given, Mapping) or not set(given) <= set(DEFAULT_ITEMS):
        raise AccountError(f"{source}: accounts.items maps some of {', '.join(DEFAULT_ITEMS)} to their names")
    items.update({str(key): str(value) for key, value in given.items()})
    for key, value in items.items():
        _check_path(value, f"{source}: accounts.items.{key}")
    if len(set(items.values())) != len(items):
        raise AccountError(f"{source}: accounts.items gives two items the same name")
    shared = data.get("set")
    if shared is not None and (not isinstance(shared, str) or not shared.strip()):
        raise AccountError(f"{source}: accounts.set names the set of accounts every instance uses (e.g. free)")
    config = AccountsConfig(
        store_value, entry, items, source, _check_path(shared.strip(), f"{source}: accounts.set") if shared else None
    )
    config.account("i", "config_reader").ref("token")  # the template renders a valid path
    return config


def setup_config_path(environ: Mapping[str, str]) -> Path:
    """E2E_SETUP_CONFIG, else ``~/.config/otterdog-e2e/setup.yaml`` of the environment's HOME."""
    value = environ.get(SETUP_CONFIG_ENV)
    return Path(value).expanduser() if value else user_config_dir(environ) / SETUP_CONFIG_FILE


def load_accounts_config(environ: Mapping[str, str]) -> AccountsConfig | None:
    """The ``accounts`` section of the setup configuration file; None without the file or the section (AccountError
    for an unreadable file or an invalid section)."""
    path = setup_config_path(environ)
    if not path.is_file():
        if environ.get(SETUP_CONFIG_ENV):
            raise AccountError(f"{SETUP_CONFIG_ENV}: {path} does not exist")
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise AccountError(f"{path}: cannot be read: {exc}") from None
    if not isinstance(data, Mapping):
        raise AccountError(f"{path}: expected a mapping (accounts: ...)")
    if data.get("accounts") is None:
        return None
    return parse_accounts_config(data["accounts"], str(path))


def cbi_password_store_dir(home: Path | None = None) -> str | None:
    """``password-store.cbi-dir`` of ci-admin's ``~/.cbi/config`` (None without the file or the key)."""
    path = (home / ".cbi" / "config") if home is not None else Path(CBI_CONFIG).expanduser()
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    value = (config.get("password-store") or {}).get("cbi-dir") if isinstance(config, dict) else None
    return str(Path(value).expanduser()) if isinstance(value, str) and value else None


def pass_environ(environ: Mapping[str, str]) -> dict[str, str]:
    """``environ`` with PASSWORD_STORE_DIR from the ~/.cbi/config of its HOME when it does not set one."""
    env = dict(environ)
    if not env.get("PASSWORD_STORE_DIR"):
        directory = cbi_password_store_dir(Path(env["HOME"]) if env.get("HOME") else None)
        if directory:
            env["PASSWORD_STORE_DIR"] = directory
    return env


def totp_code(seed: str, at: float | None = None) -> str:
    """RFC 6238 code (HMAC-SHA1, 30 s, 6 digits) of a base32 seed at ``at`` (default: now)."""
    key = base64.b32decode(seed + "=" * (-len(seed) % 8), casefold=True)
    counter = int((time.time() if at is None else at) // TOTP_PERIOD)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(value % 10**TOTP_DIGITS).zfill(TOTP_DIGITS)


@dataclass(frozen=True)
class MachineAccount:
    """The account of a role in an instance; ``ref(item)`` the reference of one of its items (AccountsConfig)."""

    role: str
    instance: str
    config: AccountsConfig
    name: str | None = None  # AccountsConfig.named: the entries are <name><separator><item>

    def _template_parts(self) -> tuple[str, str, str]:
        """The entry template before its item (head), between its role and its item (separator), after it (tail)."""
        head, _, tail = self.config.entry.rpartition("{item}")
        return head, head[head.rfind("}") + 1 :] if "}" in head else "-", tail

    @property
    def label(self) -> str:
        """The name the account's entries start with (otterdog-e2e-free-admin): ``web-login ACCOUNT`` takes it."""
        if self.name is not None:
            return self.name
        head, separator, _ = self._template_parts()
        prefix = head.format(instance=self.instance, role=self.role.replace("_", "-"))
        return prefix.removesuffix(separator) if separator else prefix

    def entry(self, item: str) -> str:
        """The name of ``item`` (a key of DEFAULT_ITEMS) in the store: the entry template filled in, or the account's
        name followed by what the template puts between its role and its item."""
        if self.name is not None:
            _, separator, tail = self._template_parts()
            return _check_path(f"{self.name}{separator}{self.config.items[item]}{tail}", "the account name")
        name = self.config.entry.format(
            instance=self.instance, role=self.role.replace("_", "-"), item=self.config.items[item]
        )
        return _check_path(name, f"{self.config.source}: accounts.entry")

    def ref(self, item: str) -> str:
        """``<store>/<entry>``: a pass entry, or a field of the Vault secret."""
        return f"{self.config.store}/{self.entry(item)}"


@dataclass(frozen=True)
class AccountResult:
    """What the setup of one account did: the login, the reference of its token in the accounts store, whether that
    token was created now (else the stored valid one was kept) and whether 2FA was enrolled now."""

    role: str
    login: str
    token_ref: str
    token_created: bool
    enrolled: bool


class GitHubSession(Protocol):
    """One logged-in browser session of an account (onboard.browser.PlaywrightSession)."""

    def login(self, username: str, password: str, *, code: Callable[[], str], device_code: Callable[[], str]) -> str:
        """Sign in with the login or e-mail ``username`` (``code``: a TOTP code when GitHub asks one,
        ``device_code``: the e-mailed verification code); returns the login GitHub shows."""
        ...

    def two_factor_enabled(self) -> bool:
        """Whether the account has two-factor authentication."""
        ...

    def enroll_two_factor(
        self,
        *,
        keep_seed: Callable[[str], None],
        code: Callable[[str], str],
        keep_recovery_codes: Callable[[list[str]], None],
    ) -> None:
        """Enroll an authenticator app: the setup key goes to ``keep_seed`` before ``code(seed)`` is submitted, the
        recovery codes to ``keep_recovery_codes`` before they are acknowledged."""
        ...

    def classic_token(self, *, note: str, url: str, days: int) -> str:
        """A new value of the classic token ``note``: regenerated when a token with that note exists, else created
        from the prefilled ``url`` (a sudo confirmation answered with the sign-in's password or code source)."""
        ...

    def open(self, url: str) -> None:
        """Show the page ``url`` (otterdog-e2e web-login)."""
        ...


class Browser(Protocol):
    """Opens one isolated session per account (onboard.browser.PlaywrightBrowser)."""

    def session(self) -> AbstractContextManager[GitHubSession]:
        """A fresh browser context, closed (and its cookies dropped) on exit."""
        ...


@dataclass
class AccountsIO:
    """The terminal side: echo, hidden prompt, plain prompt (the e-mailed device code)."""

    echo: Callable[[str], None]
    secret_prompt: Callable[[str], str]
    prompt: Callable[[str], str]


@dataclass(frozen=True)
class SignIn:
    """What signs an account in on github.com (web-login): ``name`` is typed (login or e-mail), ``login`` the account
    it must be when known, ``source`` where the password comes from (a variable or a reference, never a value)."""

    role: str
    name: str
    login: str | None
    password: str = field(repr=False)
    seed: str | None = field(repr=False)
    source: str


def web_login(browser: Browser, io: AccountsIO, account: SignIn, url: str, *, until: Callable[[str], object]) -> str:
    """Sign ``account`` in in a fresh browser session, show ``url`` and keep the window until ``until(message)``
    returns; leaving the session signs the account out and drops its cookies. A 2FA code comes from the account's key,
    else it is typed. The login GitHub shows."""

    def code() -> str:
        """The 2FA code: of the account's key, else typed."""
        if account.seed is not None:
            return totp_code(account.seed)
        return io.prompt(f"{account.role}: GitHub asks a 2FA code of {account.name}: type the code of its app").strip()

    def device_code() -> str:
        """The verification code GitHub e-mailed for a new device, typed (empty: typed in the browser)."""
        return io.prompt(
            f"{account.role}: GitHub sent a verification code to the e-mail address of {account.name}: type it here, "
            "or in the browser window and press Enter"
        ).strip()

    io.echo(f"{account.role}: signing in as {account.name} (password from {account.source})")
    with browser.session() as session:
        shown = session.login(account.name, account.password, code=code, device_code=device_code)
        if account.login and shown.lower() != account.login.lower():
            raise AccountError(f"{account.role}: signed in as {shown}, but the account is {account.login}")
        session.open(url)
        until(f"{account.role}: {shown} is signed in on {url}: press Enter to sign out and close the window")
    return shown


def _default_http(token: str, identity: str) -> GitHubHttp:
    """Read-only GitHubHttp of the token being checked."""
    from otterdog_e2e.github.http import GitHubHttp

    return GitHubHttp(token, read_only=True, identity=identity)


class AccountSetup:
    """Log in, enroll 2FA and create the classic token of each role's account (module docstring); every effect
    injected: the browser, the GitHub client of the token check, the store environment, the terminal."""

    def __init__(
        self,
        *,
        org: str | None,
        environ: Mapping[str, str],
        browser: Browser,
        io: AccountsIO,
        http: Callable[[str, str], GitHubHttp] | None = None,
        days: int = DEFAULT_EXPIRES_IN,
        rotate: bool = False,
    ) -> None:
        """Bind; ``days`` must be one of CLASSIC_EXPIRATIONS; ``rotate``: a new token even when the stored one is
        valid; ``http(token, role)``: the client of the token check (default: a read-only GitHubHttp)."""
        if days not in CLASSIC_EXPIRATIONS:
            raise AccountError(
                f"a classic token expires in {', '.join(map(str, CLASSIC_EXPIRATIONS))} days, not {days}"
            )
        self.org = org
        self.environ = pass_environ(environ)
        self.browser = browser
        self.io = io
        self.http = http
        self.days = days
        self.rotate = rotate

    # --- the store ----------------------------------------------------------------------------------------------
    def read(self, account: MachineAccount, item: str, *, secret: bool = True) -> str | None:
        """The ``item`` of the account (stripped), None when it does not exist or cannot be read; a secret item is
        registered with REDACTOR (the username and e-mail are not)."""
        try:
            value = resolve(account.ref(item), self.environ).strip()
        except VaultError:
            return None
        if value and secret:
            REDACTOR.add(value)
        return value or None

    def write(self, account: MachineAccount, item: str, value: str) -> str:
        """Write and read back ``value`` at the account's ``item``; its reference."""
        reference = account.ref(item)
        try:
            store(reference, value, self.environ)
        except VaultError as exc:
            raise AccountError(f"{account.role}: {exc}") from None
        self.io.echo(f"  {account.role}: stored {reference}")
        return reference

    def exists(self, account: MachineAccount) -> bool:
        """Whether the store knows the account (a username, e-mail or password item)."""
        return any(self.read(account, item, secret=False) for item in ("username", "email", "password"))

    # --- one account --------------------------------------------------------------------------------------------
    def password(self, account: MachineAccount) -> str:
        """The account's password from the store, else typed once (hidden) and stored."""
        value = self.read(account, "password")
        if value:
            return value
        typed = self.io.secret_prompt(
            f"password of the {account.role} account (input hidden; stored at {account.ref('password')})"
        ).strip()
        if not typed:
            raise AccountError(f"{account.role}: no password at {account.ref('password')} and none typed")
        REDACTOR.add(typed)
        self.write(account, "password", typed)
        return typed

    def seed(self, account: MachineAccount) -> str | None:
        """The normalized 2FA key from the store (AccountError when the item is not a TOTP key)."""
        value = self.read(account, "totp_seed")
        if value is None:
            return None
        try:
            seed = normalize_totp_seed(value, where=account.ref("totp_seed"))
        except WebCredentialsError as exc:
            raise AccountError(str(exc)) from None
        REDACTOR.add(seed, seed.lower())
        return seed

    def sign_in(self, account: MachineAccount) -> SignIn:
        """The web sign-in of the account from the store (AccountError without a name or a password); nothing is
        asked nor written."""
        role = account.role
        login_env = ROLE_TOKENS[role].login_env if role in ROLE_TOKENS else None
        login = self.read(account, "username", secret=False) or (self.environ.get(login_env) if login_env else None)
        name = login or self.read(account, "email", secret=False)
        if not name:
            names = ", ".join(filter(None, (account.ref("username"), login_env)))
            raise AccountError(f"{role}: neither {names} nor {account.ref('email')} names the account")
        password = self.read(account, "password")
        if not password:
            raise AccountError(f"{role}: no password at {account.ref('password')}")
        return SignIn(role, name, login, password, self.seed(account), account.ref("password"))

    def stored_token(self, account: MachineAccount, login: str | None) -> str | None:
        """The reference of the account's token when it is a classic token (of ``login`` when it is known) with the
        role's scopes (setup applies every other check), else None."""
        from otterdog_e2e import safety
        from otterdog_e2e.github.http import GitHubError

        reference = account.ref("token")
        token = self.read(account, "token")
        if token is None:
            return None
        http = (self.http or _default_http)(token, account.role)
        try:
            user = http.get("/user") or {}
            info = safety.read_token_info(http, account.role)
        except (GitHubError, safety.SafetyError) as exc:
            self.io.echo(f"  {account.role}: the token at {reference} is not usable ({exc}): a new one is created")
            return None
        found = str(user.get("login") or "") if isinstance(user, Mapping) else ""
        problem = None
        if not found or (login and found.lower() != login.lower()):
            problem = f"it belongs to {found or 'nobody'}" + (f", not {login}" if login else "")
        elif info.kind != safety.CLASSIC:
            problem = "it is not a classic token"
        elif missing := missing_scopes(account.role, info.scopes or ()):
            problem = f"it lacks {', '.join(missing)}"
        if problem:
            self.io.echo(f"  {account.role}: the token at {reference} is not usable ({problem}): a new one is created")
            return None
        return reference

    def setup(self, account: MachineAccount) -> AccountResult:
        """Everything of one account (module docstring); the browser only opens when something is missing."""
        role = account.role
        spec = ROLE_TOKENS[role]
        if spec.classic_scopes is None:
            raise AccountError(f"{role}: no classic token is accepted for this role")
        login = self.read(account, "username", secret=False) or self.environ.get(spec.login_env)
        sign_in = login or self.read(account, "email", secret=False)
        if not sign_in:
            raise AccountError(
                f"{role}: neither {account.ref('username')}, {spec.login_env} nor {account.ref('email')} names the "
                "account"
            )
        seed = self.seed(account)
        kept = None if self.rotate else self.stored_token(account, login)
        if kept and seed:
            self.io.echo(f"{role}: {login or sign_in} has its 2FA key and a valid token at {kept}: nothing to do")
            return AccountResult(role, login or sign_in, kept, token_created=False, enrolled=False)
        password = self.password(account)
        self.io.echo(f"{role}: signing in as {sign_in} in the browser window")
        with self.browser.session() as session:
            shown = session.login(
                sign_in,
                password,
                code=lambda: self.login_code(account),
                device_code=lambda: self.device_code(role, sign_in),
            )
            if login and shown.lower() != login.lower():
                raise AccountError(f"{role}: signed in as {shown}, but the account is {login}")
            enrolled = self.ensure_two_factor(session, account, seed)
            if kept:
                return AccountResult(role, shown, kept, token_created=False, enrolled=enrolled)
            reference = self.new_token(session, account)
        return AccountResult(role, shown, reference, token_created=True, enrolled=enrolled)

    def login_code(self, account: MachineAccount) -> str:
        """A TOTP code of the stored key (AccountError without one: the account has 2FA that the store does not
        know)."""
        seed = self.seed(account)
        if seed is None:
            raise AccountError(
                f"{account.role}: GitHub asks a 2FA code but {account.ref('totp_seed')} does not exist: store the "
                "account's setup key there (or reset its 2FA with a recovery code), then run again"
            )
        return totp_code(seed)

    def device_code(self, role: str, sign_in: str) -> str:
        """The verification code GitHub e-mailed for a new device, typed in the terminal (empty: typed in the
        browser)."""
        return self.io.prompt(
            f"{role}: GitHub sent a verification code to the e-mail address of {sign_in}: type it here, or in the "
            "browser window and press Enter"
        ).strip()

    def ensure_two_factor(self, session: GitHubSession, account: MachineAccount, seed: str | None) -> bool:
        """Enroll an authenticator app when the account has no 2FA (True); a known key with 2FA enabled is kept."""
        if session.two_factor_enabled():
            if seed is None:
                raise AccountError(
                    f"{account.role}: 2FA is enabled but {account.ref('totp_seed')} does not exist: store its setup "
                    "key there"
                )
            self.io.echo(f"  {account.role}: 2FA already enabled")
            return False
        if seed is not None:
            self.io.echo(
                f"  {account.role}: 2FA is not enabled: the unused key at {account.ref('totp_seed')} is replaced"
            )

        def keep_seed(raw: str) -> None:
            """Store the setup key before the code that enables it is submitted."""
            try:
                value = normalize_totp_seed(raw, where="the setup key GitHub showed")
            except WebCredentialsError as exc:
                raise AccountError(f"{account.role}: {exc}") from None
            REDACTOR.add(raw, value, value.lower())
            self.write(account, "totp_seed", value)

        def keep_codes(codes: list[str]) -> None:
            """Store the recovery codes before they are acknowledged."""
            codes = [code.strip() for code in codes if code.strip()]
            if not codes:
                raise AccountError(f"{account.role}: GitHub showed no recovery codes: finish the enrollment by hand")
            REDACTOR.add(*codes)
            self.write(account, "recovery_codes", "\n".join(codes))

        session.enroll_two_factor(
            keep_seed=keep_seed,
            code=lambda raw: totp_code(normalize_totp_seed(raw, where="the setup key GitHub showed")),
            keep_recovery_codes=keep_codes,
        )
        self.io.echo(f"  {account.role}: 2FA enabled (authenticator app)")
        return True

    def new_token(self, session: GitHubSession, account: MachineAccount) -> str:
        """Create (or regenerate) the role's classic token and store it at once; its note is the description of the
        prefilled URLs (the org known), else the token name."""
        role, instance = account.role, account.instance
        note = token_description(instance, role, self.org) if self.org else token_name(instance, role)
        token = session.classic_token(note=note, url=classic_token_url(role, description=note), days=self.days).strip()
        if not token:
            raise AccountError(f"{role}: GitHub showed no token")
        REDACTOR.add(token)
        reference = self.write(account, "token", token)
        self.io.echo(f"  {role}: classic token created ({self.days} days)")
        return reference

    def run(self, accounts: Sequence[MachineAccount]) -> Iterator[AccountResult]:
        """Set up the accounts in order (stops at the first AccountError)."""
        for account in accounts:
            yield self.setup(account)
