"""Machine accounts in the browser (``otterdog-e2e accounts``, ``setup --browser``; docs/onboarding.md, "Machine accounts
in the browser").

For each role it logs in to github.com as the role's machine account, enrolls two-factor authentication (TOTP) when
the account has none and creates the role's classic token (the scopes of onboard.tokens, the note of the prefilled
URLs, an expiration), driving Firefox through Playwright (onboard.browser). The secrets of an account live in
``pass`` in the layout of eclipse-cbi/ci-admin (github/playwright), the account's directory ``<dir>`` (e.g.
``bots/<project>/github.com``) being E2E_<ROLE>_PASS_DIR of the instance env file:

* ``<dir>/username``, ``<dir>/password``: read (a missing password is asked once, hidden, and stored);
* ``<dir>/2FA-seed``: read for the login codes, written by the enrollment (the normalized base32 key);
* ``<dir>/2FA-recovery-codes``: written by the enrollment (one code per line);
* ``<dir>/otterdog-e2e-<instance>-token``: the classic token of the instance (an account may serve several).

``pass`` runs with PASSWORD_STORE_DIR, else the ``password-store.cbi-dir`` of ``~/.cbi/config`` as ci-admin does
(cbi_password_store_dir). Writes go through vaults.store (stdin, read back), never a shell.

The token is written to pass only: the env file gets it through setup, whose checks (token kind and scopes,
isolation, owner membership) decide; setup finds it at its place without a prompt (SetupWizard.from_account).
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
import struct
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from otterdog_e2e.onboard.tokens import (
    DEFAULT_EXPIRES_IN,
    ROLE_TOKENS,
    classic_token_url,
    missing_scopes,
    token_description,
    token_name,
)
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.settings import WebCredentialsError, normalize_totp_seed
from otterdog_e2e.vaults import VaultError, resolve, store

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp

USERNAME, PASSWORD, SEED, RECOVERY_CODES = "username", "password", "2FA-seed", "2FA-recovery-codes"
CBI_CONFIG = "~/.cbi/config"  # ci-admin's configuration: {"password-store": {"cbi-dir": ...}}
CLASSIC_EXPIRATIONS = (7, 30, 60, 90)  # days the classic token form offers besides a custom date and none
TOTP_PERIOD, TOTP_DIGITS = 30, 6
_DIR_RE = re.compile(r"^[A-Za-z0-9_.@-]+(/[A-Za-z0-9_.@-]+)*$")


class AccountError(RuntimeError):
    """A machine account cannot be set up (the message never contains a secret)."""


def pass_dir_env(role: str) -> str:
    """E2E_<ROLE>_PASS_DIR: the pass directory of the role's account (ci-admin layout)."""
    return ROLE_TOKENS[role].login_env.removesuffix("_LOGIN") + "_PASS_DIR"


def token_entry(instance: str) -> str:
    """The pass entry of the instance's token in an account directory."""
    return f"otterdog-e2e-{instance}-token"


def check_pass_dir(value: str) -> str:
    """A pass directory without leading or trailing slash (AccountError for '..', spaces or an empty path)."""
    directory = value.strip().strip("/")
    if not _DIR_RE.match(directory) or any(part in (".", "..") for part in directory.split("/")):
        raise AccountError(f"not a pass directory (such as bots/<project>/github.com): {value!r}")
    return directory


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
    """The pass directory of a role's account; ``ref(item)`` the reference of one of its entries."""

    role: str
    directory: str

    def ref(self, item: str) -> str:
        """``pass:<dir>/<item>``."""
        return f"pass:{self.directory}/{item}"


@dataclass(frozen=True)
class AccountResult:
    """What the setup of one account did: the login, the reference of its token in pass, whether that token was
    created now (else the stored valid one was kept) and whether 2FA was enrolled now."""

    role: str
    login: str
    token_ref: str
    token_created: bool
    enrolled: bool


class GitHubSession(Protocol):
    """One logged-in browser session of an account (onboard.browser.PlaywrightSession)."""

    def login(self, username: str, password: str, *, code: Callable[[], str], device_code: Callable[[], str]) -> str:
        """Sign in (``code``: a TOTP code when GitHub asks one, ``device_code``: the e-mailed verification code);
        returns the login GitHub shows."""
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


def _default_http(token: str, identity: str) -> GitHubHttp:
    """Read-only GitHubHttp of the token being checked."""
    from otterdog_e2e.github.http import GitHubHttp

    return GitHubHttp(token, read_only=True, identity=identity)


class AccountSetup:
    """Log in, enroll 2FA and create the classic token of each role's account (module docstring); every effect
    injected: the browser, the GitHub client of the token check, the pass environment, the terminal."""

    def __init__(
        self,
        instance: str,
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
        self.instance = instance
        self.org = org
        self.environ = pass_environ(environ)
        self.browser = browser
        self.io = io
        self.http = http
        self.days = days
        self.rotate = rotate

    # --- pass ---------------------------------------------------------------------------------------------------
    def read(self, account: MachineAccount, item: str, *, secret: bool = True) -> str | None:
        """The entry ``item`` of the account (stripped), None when it does not exist or cannot be read; a secret entry
        is registered with REDACTOR (the username is not one)."""
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

    # --- one account --------------------------------------------------------------------------------------------
    def password(self, account: MachineAccount) -> str:
        """The account's password from pass, else typed once (hidden) and stored."""
        value = self.read(account, PASSWORD)
        if value:
            return value
        typed = self.io.secret_prompt(f"password of the {account.role} account (input hidden; stored in pass)").strip()
        if not typed:
            raise AccountError(f"{account.role}: no password in {account.ref(PASSWORD)} and none typed")
        REDACTOR.add(typed)
        self.write(account, PASSWORD, typed)
        return typed

    def seed(self, account: MachineAccount) -> str | None:
        """The normalized 2FA key from pass (AccountError when the entry is not a TOTP key)."""
        value = self.read(account, SEED)
        if value is None:
            return None
        try:
            seed = normalize_totp_seed(value, where=account.ref(SEED))
        except WebCredentialsError as exc:
            raise AccountError(str(exc)) from None
        REDACTOR.add(seed, seed.lower())
        return seed

    def stored_token(self, account: MachineAccount, login: str) -> str | None:
        """The reference of the instance's token in pass when it is a classic token of ``login`` with the role's
        scopes (setup applies every other check), else None."""
        from otterdog_e2e import safety
        from otterdog_e2e.github.http import GitHubError

        reference = account.ref(token_entry(self.instance))
        token = self.read(account, token_entry(self.instance))
        if token is None:
            return None
        http = (self.http or _default_http)(token, account.role)
        try:
            user = http.get("/user") or {}
            info = safety.read_token_info(http, account.role)
        except (GitHubError, safety.SafetyError) as exc:
            self.io.echo(f"  {account.role}: the token in {reference} is not usable ({exc}): a new one is created")
            return None
        found = str(user.get("login") or "") if isinstance(user, Mapping) else ""
        problem = None
        if found.lower() != login.lower():
            problem = f"it belongs to {found or 'nobody'}, not {login}"
        elif info.kind != safety.CLASSIC:
            problem = "it is not a classic token"
        elif missing := missing_scopes(account.role, info.scopes or ()):
            problem = f"it lacks {', '.join(missing)}"
        if problem:
            self.io.echo(f"  {account.role}: the token in {reference} is not usable ({problem}): a new one is created")
            return None
        return reference

    def setup(self, account: MachineAccount) -> AccountResult:
        """Everything of one account (module docstring); the browser only opens when something is missing."""
        role = account.role
        spec = ROLE_TOKENS[role]
        if spec.classic_scopes is None:
            raise AccountError(f"{role}: no classic token is accepted for this role")
        login = self.read(account, USERNAME, secret=False) or self.environ.get(spec.login_env)
        if not login:
            raise AccountError(f"{role}: no login in {account.ref(USERNAME)} (nor {spec.login_env})")
        seed = self.seed(account)
        kept = None if self.rotate else self.stored_token(account, login)
        if kept and seed:
            self.io.echo(f"{role}: {login} has its 2FA key and a valid token in {kept}: nothing to do")
            return AccountResult(role, login, kept, token_created=False, enrolled=False)
        password = self.password(account)
        self.io.echo(f"{role}: signing in as {login} in the browser window")
        with self.browser.session() as session:
            shown = session.login(
                login,
                password,
                code=lambda: self.login_code(account),
                device_code=lambda: self.device_code(role, login),
            )
            if shown.lower() != login.lower():
                raise AccountError(f"{role}: signed in as {shown}, but {account.ref(USERNAME)} names {login}")
            enrolled = self.ensure_two_factor(session, account, seed)
            if kept:
                return AccountResult(role, login, kept, token_created=False, enrolled=enrolled)
            reference = self.new_token(session, account)
        return AccountResult(role, login, reference, token_created=True, enrolled=enrolled)

    def login_code(self, account: MachineAccount) -> str:
        """A TOTP code of the stored key (AccountError without one: the account has 2FA that pass does not know)."""
        seed = self.seed(account)
        if seed is None:
            raise AccountError(
                f"{account.role}: GitHub asks a 2FA code but {account.ref(SEED)} does not exist: store the account's "
                "setup key there (or reset its 2FA with a recovery code), then run again"
            )
        return totp_code(seed)

    def device_code(self, role: str, login: str) -> str:
        """The verification code GitHub e-mailed for a new device, typed in the terminal (empty: typed in the
        browser)."""
        return self.io.prompt(
            f"{role}: GitHub sent a verification code to the e-mail address of {login}: type it here, or in the browser "
            "window and press Enter"
        ).strip()

    def ensure_two_factor(self, session: GitHubSession, account: MachineAccount, seed: str | None) -> bool:
        """Enroll an authenticator app when the account has no 2FA (True); a known key with 2FA enabled is kept."""
        if session.two_factor_enabled():
            if seed is None:
                raise AccountError(
                    f"{account.role}: 2FA is enabled but {account.ref(SEED)} does not exist: store its setup key there"
                )
            self.io.echo(f"  {account.role}: 2FA already enabled")
            return False
        if seed is not None:
            self.io.echo(f"  {account.role}: 2FA is not enabled: the unused key in {account.ref(SEED)} is replaced")

        def keep_seed(raw: str) -> None:
            """Store the setup key before the code that enables it is submitted."""
            try:
                value = normalize_totp_seed(raw, where="the setup key GitHub showed")
            except WebCredentialsError as exc:
                raise AccountError(f"{account.role}: {exc}") from None
            REDACTOR.add(raw, value, value.lower())
            self.write(account, SEED, value)

        def keep_codes(codes: list[str]) -> None:
            """Store the recovery codes before they are acknowledged."""
            codes = [code.strip() for code in codes if code.strip()]
            if not codes:
                raise AccountError(f"{account.role}: GitHub showed no recovery codes: finish the enrollment by hand")
            REDACTOR.add(*codes)
            self.write(account, RECOVERY_CODES, "\n".join(codes))

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
        role = account.role
        note = token_description(self.instance, role, self.org) if self.org else token_name(self.instance, role)
        token = session.classic_token(note=note, url=classic_token_url(role, description=note), days=self.days).strip()
        if not token:
            raise AccountError(f"{role}: GitHub showed no token")
        REDACTOR.add(token)
        reference = self.write(account, token_entry(self.instance), token)
        self.io.echo(f"  {role}: classic token created ({self.days} days)")
        return reference

    def run(self, accounts: Sequence[MachineAccount]) -> Iterator[AccountResult]:
        """Set up the accounts in order (stops at the first AccountError)."""
        for account in accounts:
            yield self.setup(account)
