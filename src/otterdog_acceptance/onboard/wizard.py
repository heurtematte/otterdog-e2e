"""``otterdog-acceptance setup``: the interactive onboarding of one test organization instance (docs/onboarding.md).

Every validated answer is written to the instance env file at once (``envfile.update_env_file``), so an interrupted
run keeps its progress and the next run continues where it stopped:

1. org: the login (--org, E2E_ORG, otterdog-e2e-<instance> for the instance of a shard, else asked) ->``GET /orgs/{org}`` (exact-case login, id pinned in E2E_ORG_ID); a
   missing org gets its creation URL (the profile's plan; both the Free URL and the Enterprise Cloud note while the
   profile is not known) and is checked again on demand (no API creates Free/Team orgs);
2. tokens, one role after the other (admin required, the others skippable): the PREFILLED creation URL (classic or
   fine-grained: --token-type, else the stored E2E_<ROLE>_TOKEN_TYPE, else classic), a hidden prompt, then the checks
   of the harness (GET /user login, token kind, the role's classic scopes, the owner membership of the admin,
   ``safety.check_identity_isolation``); a token or login already used by another role is refused (the oracle may be
   the admin); E2E_<ROLE>_LOGIN / _TOKEN / _TOKEN_TYPE are written only for a token that passed. Stored valid tokens
   are kept unless ``--rotate <role>``. Right after the admin token: E2E_PROFILE (--profile, the stored one, else the
   org plan), checked against the profile's expected plan. A FINE-GRAINED token of the author, approver or oracle can
   neither be created (its resource owner is the org) nor proven isolated before the account is an active member: the
   wizard first asks only the login, invites it with the admin token (author/approver as members, the oracle as an
   owner; an existing membership is never changed), prints the invitation URL and polls until it is active (timeout:
   run setup again), and only then shows the token URL. When the role then ends without a token after a token of
   ANOTHER account was refused, the invitation this run created is cancelled while still pending (``DELETE
   /orgs/{org}/memberships/{login}``, admin token) and an accepted one is reported (never removed). Classic tokens are
   checked before any membership (bootstrap invites and publicizes later). A role whose token is in the accounts
   store (the accounts section of ~/.config/otterdog-acceptance/setup.yaml, written by ``otterdog-acceptance accounts``) takes it
   without a prompt, through the same checks (the env file gets its pass reference, or for a Vault store its value:
   keeps_account_references); with the accounts store (or --browser; --no-browser: the prefilled URL and its
   steps instead), a role without a valid token is set up in the browser first, its classic token created there
   (onboard/accounts.py, ``run_account``), the prompt following when that fails;
3. web-UI login of the admin account (optional): password and TOTP setup key (hidden, settings.normalize_totp_seed),
   or the admin account's pass entries (opt-in);
4. GitHub App (optional; the org description must carry the safety marker, as for ``app-manifest``): the manifest flow
   (browser click), E2E_APP_* written into the instance env file itself; a new or stored App is verified first
   (``safety.verify_app``: owned by the test org, installed on test orgs only; refused otherwise, ``--rotate app``),
   then the installation URL printed and ``GET /orgs/{org}/installation`` (App JWT) polled until installed (timeout:
   run setup again);
5. ``bootstrap --apply`` and ``doctor`` offered (callables of the CLI).

Machine accounts serving several test orgs: a classic PAT lists every membership of its account. An org id N it
belongs to beyond this instance's allowlist is OFFERED (question defaulting to no, "org id N (instance x)") only when
it is the validated test org of another instance x: (1) x's env file pins E2E_ORG and E2E_ORG_ID=N and holds
E2E_ADMIN_LOGIN and E2E_ADMIN_TOKEN, which setup writes only for an admin token that passed the owner check of that
org (an aborted setup pins the org id without them), (2) x's target loads with those values (production denylist
included), and (3) read LIVE through the token being checked, ``GET /orgs/{x's org}`` answers id N and a description
carrying x's safety marker (set by x's bootstrap once the operator typed the org login). Every foreign org must be
offered, or none is (the isolation check refuses it anyway); the reason an org of a known instance is not offered is
printed. An accepted offer only widens the allowlist the checks of THIS token use, in memory: E2E_ALLOWED_ORG_IDS is
written (the other instances' files first, then this one) once the token passed every check (scopes, isolation,
owner, the invited login); a refused token changes no file. Other cases: set E2E_ALLOWED_ORG_IDS by hand.

Refused in CI (context.in_ci). Secrets are read with hidden prompts only, registered with REDACTOR at once and never
echoed; every echoed text is redacted. Every secret prompt (tokens, web password, TOTP setup key) also accepts a vault
reference (``vault:<path>/<field>``, ``pass:<path>``, ``bitwarden:<item>@<field>``, vaults.py): it is resolved with
the operator's own vault access, the value checked like a typed one, and the REFERENCE written; a stored reference is
resolved before its checks (secret). With a secret store (``--store vault:<prefix>`` or ``pass:<prefix>``, kept as
E2E_SECRET_STORE; store_step asks E2E_VAULT_ADDR for Vault), every secret has its place in the reference layout
(onboard/store.py): a secret already there is used without a prompt, a typed or stored plain value that passes its
checks is written there (into_store) and only its reference goes to the env file, the App's key and webhook secret
included (the key file may then be deleted); the end lists the Vault policies of the instance's environments.
"""

from __future__ import annotations

import functools
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

import yaml

from otterdog_acceptance.batch import add_to_list
from otterdog_acceptance.context import in_ci, installation_problems
from otterdog_acceptance.github.http import GitHubError
from otterdog_acceptance.onboard.accounts import (
    FLAGGED_JOIN_LOSS,
    FLAGGED_LOSS,
    AccountError,
    AccountResult,
    AccountsConfig,
    load_accounts_config,
    setup_config_path,
)
from otterdog_acceptance.onboard.envfile import (
    check_instance_name,
    instance_app_dir,
    instance_env_path,
    known_instances,
    read_env_file,
    update_env_file,
)
from otterdog_acceptance.onboard.store import STORE_ENV, StoreError, parse_store, store_reference, vault_policies
from otterdog_acceptance.onboard.tokens import (
    DEFAULT_EXPIRES_IN,
    ROLE_TOKENS,
    ROLES,
    missing_scopes,
    token_steps,
    token_url,
)
from otterdog_acceptance.redact import REDACTOR, SECRET_KEY_RE
from otterdog_acceptance.safety import CLASSIC, FINE_GRAINED, MEMBER_ROLES, SafetyError, check_org_allowed
from otterdog_acceptance.settings import (
    DEFAULT_WEB_ENV,
    LOGIN_RE,
    TargetError,
    WebCredentialsError,
    normalize_totp_seed,
)
from otterdog_acceptance.shards import (
    SHARD_ENV,
    SHARDS_FILE,
    SHARDS_LIST,
    ItemFacts,
    Shard,
    ShardError,
    ShardMap,
    load_shards,
)
from otterdog_acceptance.vaults import VaultError, is_reference, resolve, store
from otterdog_acceptance.waiting import WaitTimeoutError, wait_until

if TYPE_CHECKING:
    from otterdog_acceptance.github.app import AppAuth
    from otterdog_acceptance.github.http import GitHubHttp
    from otterdog_acceptance.safety import VerifiedOrg
    from otterdog_acceptance.settings import AppCredentials, HarnessSettings, Target

ORG_CREATION_URLS: Mapping[str, str] = {
    "free": "https://github.com/account/organizations/new?plan=free",
    "team": "https://github.com/account/organizations/new",
}
ENTERPRISE_ORG_NOTE = (
    "Enterprise Cloud: an enterprise owner creates the organization in the enterprise (Organizations, New "
    "organization), or with the GraphQL mutation createEnterpriseOrganization; a trial enterprise can hold three"
)
APP_INSTALL_URL = "https://github.com/apps/{slug}/installations/new/permissions?target_id={org_id}"
APP_WEBHOOK_URL_ENV = "E2E_APP_WEBHOOK_URL"  # the App's webhook sink (non-secret), reused by --from and re-runs
APP_ENV = ("E2E_APP_ID", "E2E_APP_SLUG", "E2E_APP_PRIVATE_KEY_FILE", "E2E_APP_WEBHOOK_SECRET")
WEB_ROTATION, APP_ROTATION = "web", "app"
NO_SHARD = "none"  # setup --shard none: the instance runs every live item
PUBLIC_MEMBERS = ("author", "approver")  # active and PUBLIC members (bootstrap.BOOTSTRAP_MEMBERS); the oracle owns
ROTATABLE = (*ROLES, WEB_ROTATION, APP_ROTATION)
TOKEN_KIND_LABELS: Mapping[str, str] = {CLASSIC: "classic PAT", FINE_GRAINED: "fine-grained PAT"}
# --from: settings of another instance that are neither secret nor specific to its org
COPYABLE_KEYS = (
    "E2E_PROFILE",
    *(spec.type_env for spec in ROLE_TOKENS.values()),
    "E2E_ADMIN_TEAM",
    "E2E_APPROVAL_TEAM",
    "E2E_CONTRIBUTORS_TEAM",
    "E2E_CONFIGS_REPO",
    "E2E_ORG_CONFIG_REPO",
    "E2E_DEFAULTS_REPO",
    "E2E_TEMPLATE_MODE",
    "E2E_TEMPLATE_URL",
    "E2E_TRANSPORT",
    "E2E_VALIDATION_CONTEXT",
    "E2E_SYNC_CONTEXT",
    "E2E_WEBAPP_WORKERS",
    APP_WEBHOOK_URL_ENV,
    "E2E_MIN_RATE_REMAINING",
    "E2E_LEASE_WAIT",
    "E2E_WEB_LOGIN_SPACING",
)
MAX_ATTEMPTS = 5  # per prompt: invalid tokens, seeds or URLs before the wizard gives up (nothing written)
TOKEN_SHAPE_RE = re.compile(r"^[A-Za-z0-9_]{20,255}$")  # ghp_..., github_pat_... (nothing else is sent to GitHub)
DEFAULT_WAIT_TIMEOUT = 1800.0  # seconds: invitation acceptance and App installation waits (like bootstrap --wait)
POLL_INTERVAL = 10.0
# roles whose fine-grained token needs an active membership first, and the role they are invited with
FINE_GRAINED_INVITES: Mapping[str, str] = {"author": "member", "approver": "member", "oracle": "admin"}
INVITATION_URL = "https://github.com/orgs/{org}/invitation"
PEOPLE_URL = "https://github.com/orgs/{org}/people"
APP_READY, APP_SKIPPED, APP_NEEDS_MARKER = "ready", "skipped", "needs-marker"
RULE_WIDTH = 100  # the title line of an instance's setup (banner)
# the marks of the status lines (the CLI colours them): done, needs attention, skipped
DONE, WARN, SKIPPED = "\u2713", "!", "\u2013"
ENV_FILE_HEADER = (
    "otterdog-acceptance instance {instance}: written by `otterdog-acceptance setup` (re-run it to change or rotate a value).\n"
    "Holds tokens and passwords: keep it private (mode 0600), never commit or share it."
)


class SetupError(RuntimeError):
    """The setup cannot go on (the message never contains a secret); what was validated so far stays written."""


class SetupStoppedError(SetupError):
    """The operator stopped the setup at a question: never taken for a refused token."""


class TokenRejectedError(ValueError):
    """A token failed a check (redacted reason); it is never written."""


# the roles whose account joins the test org (bootstrap invites them): a flagged account cannot
JOINING_ROLES = (*MEMBER_ROLES, "oracle")
FLAGGED_HELP = (
    "GitHub hides the profile of {login} from anonymous visitors, as it does for a flagged account ({loss}); only "
    "GitHub Support lifts the flag: https://support.github.com/contact (signed in as {login}, a flagged account "
    "sees a banner)"
)


@dataclass(frozen=True)
class SetupOptions:
    """Command line options of ``setup``."""

    instance: str
    profile: str | None = None
    org: str | None = None
    token_type: str | None = None  # kind of the prefilled creation URLs (classic, fine-grained)
    rotate: tuple[str, ...] = ()
    from_instance: str | None = None
    expires_in: int = DEFAULT_EXPIRES_IN
    webhook_url: str | None = None
    open_urls: bool = False
    wait_timeout: float = DEFAULT_WAIT_TIMEOUT
    poll_interval: float = POLL_INTERVAL
    store: str | None = None  # secret store vault:<prefix> / pass:<prefix> (onboard/store.py)
    # create the classic tokens of the machine accounts in the browser (onboard/accounts.py); None: when the accounts
    # store is configured (--browser / --no-browser decide)
    browser: bool | None = None
    shard: str | None = None  # the shard of the instance (scenarios/shards.yaml); NO_SHARD: every live item
    banner: bool = True  # the title line (setup --shards prints its own, with the position of the instance)


class WebSteps(Protocol):
    """GitHub's web steps done in a browser as the machine accounts (the CLI's: the accounts store and Firefox); each
    returns whether it was done, the operator does it otherwise. The wait that follows sees the result either way."""

    def join(self, role: str, org: str, login: str, *, public: bool) -> bool:
        """``login`` accepts its invitation of ``org`` and, with ``public``, makes its membership public."""

    def install_app(self, url: str) -> bool:
        """The admin installs the App from its installation page ``url``."""


@dataclass(frozen=True)
class WizardIO:
    """Every interaction of the wizard: ``prompt(text, default)``, hidden ``secret_prompt(text)``,
    ``confirm(text, default)``, ``echo(text)``, ``open_url(url)`` (None: URLs are only printed), sleep and clock."""

    prompt: Callable[[str, str | None], str]
    secret_prompt: Callable[[str], str]
    confirm: Callable[[str, bool], bool]
    echo: Callable[[str], None]
    open_url: Callable[[str], Any] | None = None
    sleep: Callable[[float], None] = time.sleep
    clock: Callable[[], float] = time.monotonic


@dataclass(frozen=True)
class OrgInfo:
    """The live test org: exact-case login and numeric id."""

    login: str
    org_id: int


@dataclass(frozen=True)
class CheckedToken:
    """A token that passed every check of its role; ``shared``: the accepted org ids of other instances (with their
    instance names) its isolation check allowed, to be written to E2E_ALLOWED_ORG_IDS with the token."""

    login: str
    kind: str
    expires_at: datetime | None = None
    shared: tuple[tuple[int, tuple[str, ...]], ...] = ()


def _default_http(token: str | None, identity: str) -> GitHubHttp:
    """Read-only GitHubHttp of one identity (imported here: tests patch otterdog_acceptance.github.http.GitHubHttp)."""
    from otterdog_acceptance.github.http import GitHubHttp

    return GitHubHttp(token, read_only=True, identity=identity)


def _default_write_http(token: str, verified: VerifiedOrg) -> GitHubHttp:
    """GitHubHttp of the admin token, write-scoped to the verified org (the invitations of fine-grained roles)."""
    from otterdog_acceptance.github.http import GitHubHttp

    return GitHubHttp(token, write_scope=verified, identity="admin")


def _default_app_auth(credentials: AppCredentials) -> AppAuth:
    """AppAuth of the App credentials (JWT reads only)."""
    from otterdog_acceptance.github.app import AppAuth

    return AppAuth(credentials)


def _default_exchange(code: str, *, out_dir: Path) -> Mapping[str, Any]:
    """appmanifest.exchange_code: the App key and webhook secret written to 0600 files of ``out_dir``."""
    from otterdog_acceptance.appmanifest import exchange_code

    return exchange_code(code, out_dir=out_dir)


def _org_id_of(item: Any) -> int | None:
    """Organization id of a /user/orgs item or of a /user/memberships/orgs item."""
    org = item.get("organization") if isinstance(item, Mapping) and "organization" in item else item
    value = org.get("id") if isinstance(org, Mapping) else None
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def parse_org_ids(text: str | None) -> list[int]:
    """Positive ids of a comma separated E2E_ALLOWED_ORG_IDS value (SetupError for anything else)."""
    ids = []
    for item in (text or "").split(","):
        item = item.strip()
        if not item:
            continue
        if not item.isdigit() or int(item) <= 0:
            raise SetupError(f"E2E_ALLOWED_ORG_IDS: {item!r} is not a positive organization id")
        ids.append(int(item))
    return ids


def banner(title: str) -> str:
    """The ruled title line that starts the setup of an instance."""
    head = f"\u2501\u2501 {title} "
    return head + "\u2501" * max(3, RULE_WIDTH - len(head))


def _expiry(checked: CheckedToken) -> str:
    """``expires <date>`` or ``no expiration``."""
    return f"expires {checked.expires_at:%Y-%m-%d}" if checked.expires_at else "no expiration"


class SetupWizard:
    """The ``setup`` flow of one instance; every external effect is injected (I/O, GitHub clients, App flow, bootstrap,
    doctor) so the flow runs against fakes."""

    def __init__(
        self,
        options: SetupOptions,
        io: WizardIO,
        *,
        environ: Mapping[str, str],
        settings: HarnessSettings,
        http: Callable[[str | None, str], GitHubHttp] = _default_http,
        write_http: Callable[[str, VerifiedOrg], GitHubHttp] = _default_write_http,
        run_manifest: Callable[[Target, str], str] | None = None,
        exchange: Callable[..., Mapping[str, Any]] = _default_exchange,
        app_auth: Callable[[AppCredentials], Any] = _default_app_auth,
        bootstrap: Callable[[str], None] | None = None,
        doctor: Callable[[str], None] | None = None,
        run_account: Callable[..., AccountResult] | None = None,
        sign_in_at: Callable[[str, str], None] | None = None,
        web: WebSteps | None = None,
    ) -> None:
        """Bind the flow; nothing is read or asked before run(). ``run_manifest(target, webhook_url)`` returns the
        manifest code (None: no App step), ``bootstrap`` / ``doctor`` take the instance name (None: not offered),
        ``write_http(admin_token, verified)`` is the only writing client (invitations), ``run_account(account, *,
        org, rotate, environ)`` sets up a machine account in the browser for --browser (AccountSetup.setup),
        ``sign_in_at(account, url)`` shows a page in a browser signed in as an account of the accounts store until the
        operator is done (web-login ACCOUNT --url: the creation of the organization by its admin), ``web`` does the
        web steps of the members and the App (accepting invitations, public memberships, installing the App)."""
        unknown = sorted(set(options.rotate) - set(ROTATABLE))
        if unknown:
            raise SetupError(f"--rotate: unknown value(s) {', '.join(unknown)} (expected {', '.join(ROTATABLE)})")
        self.options = options
        self.section_title: str | None = None  # the title of the current step, printed before its first output
        self.in_section = False
        self.io = replace(  # the questions of a step come under its title, indented like its lines
            io,
            prompt=lambda text, default: io.prompt(self.indented(text), default),
            secret_prompt=lambda text: io.secret_prompt(self.indented(text)),
            confirm=lambda text, default: io.confirm(self.indented(text), default),
        )
        self.environ = environ
        self.settings = settings
        self.http = http
        self.write_http = write_http
        self.run_manifest = run_manifest
        self.exchange = exchange
        self.app_auth = app_auth
        self.bootstrap = bootstrap
        self.doctor = doctor
        self.run_account = run_account
        self.sign_in_at = sign_in_at
        self.web = web
        self.instance = check_instance_name(options.instance)
        self.env_path = instance_env_path(self.instance, environ)
        self.values: dict[str, str] = {}
        self.clients: dict[str, GitHubHttp] = {}
        self.flagged: dict[str, str] = {}  # role -> login of a flagged account left out (check_flagged)
        self.flag_answers: dict[str, bool] = {}  # login -> continue? (asked once per flagged account)
        self.visible_accounts: set[str] = set()  # logins whose profile is public
        self.profile: str | None = None
        self.shard_map: ShardMap | None = None
        self.shard: Shard | None = None
        self.invited: dict[str, str] = {}  # role -> login invited by THIS run (PUT /orgs/{org}/memberships/{login})

    # --- plumbing -----------------------------------------------------------------------------------------------
    def echo(self, text: str = "") -> None:
        """Print redacted text (under the title of the current step)."""
        self.io.echo(REDACTOR(self.indented(text)))

    def done(self, text: str) -> None:
        """A status line: done."""
        self.echo(f"{DONE} {text}")

    def warn(self, text: str) -> None:
        """A status line: something the operator should look at."""
        self.echo(f"{WARN} {text}")

    def skipped(self, text: str = "skipped") -> None:
        """A status line: left out."""
        self.echo(f"{SKIPPED} {text}")

    def section(self, title: str) -> None:
        """Start a step: its title comes before its first output, so a step with nothing to say shows none."""
        self.section_title = title
        self.in_section = True

    def indented(self, text: str) -> str:
        """``text`` under the current step: its pending title printed first, then the text indented."""
        if self.section_title is not None:
            self.io.echo("")
            self.io.echo(f"\u25b8 {self.section_title}")
            self.section_title = None
        return f"  {text}" if self.in_section and text else text

    def open(self, url: str) -> None:
        """Open ``url`` in a browser when --open was given (it is always printed as well)."""
        if self.options.open_urls and self.io.open_url is not None:
            self.io.open_url(url)

    def write(self, updates: Mapping[str, str | None], *, path: Path | None = None) -> list[str]:
        """Write keys to the instance env file (or ``path``); the names written are reported, never the values."""
        target = path or self.env_path
        header = ENV_FILE_HEADER.format(instance=self.instance) if target == self.env_path else None
        changed = update_env_file(target, updates, header=header)
        if target == self.env_path:
            for key, value in updates.items():
                if value is None:
                    self.values.pop(key, None)
                else:
                    self.values[key] = value
        if changed:
            self.echo(f"  saved {', '.join(changed)}" + ("" if target == self.env_path else f" in {target}"))
        return changed

    def profiles(self) -> list[str]:
        """Profiles of the project (targets/<profile>.yaml)."""
        directory = self.settings.targets_dir
        if not directory.is_dir():
            return []
        return sorted({path.stem for pattern in ("*.yaml", "*.yml") for path in directory.glob(pattern)})

    def expected_plan(self, profile: str) -> str | None:
        """github.expected_plan of a profile when it is a literal (None when env-driven or unreadable)."""
        for suffix in (".yaml", ".yml"):
            path = self.settings.targets_dir / f"{profile}{suffix}"
            if not path.is_file():
                continue
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError, yaml.YAMLError):
                return None
            github = data.get("github") if isinstance(data, Mapping) else None
            plan = github.get("expected_plan") if isinstance(github, Mapping) else None
            return plan.strip().lower() if isinstance(plan, str) and "${" not in plan else None
        return None

    def target(self) -> Target:
        """The profile's target expanded with the instance values only (never the process environment)."""
        from otterdog_acceptance.settings import load_target

        if self.profile is None:
            raise SetupError("the profile is not known yet")
        try:
            return load_target(self.profile, self.settings, environ=self.values)
        except (TargetError, SafetyError) as exc:
            raise SetupError(f"profile {self.profile} with the values of {self.env_path}: {exc}") from None

    # --- the flow -----------------------------------------------------------------------------------------------
    def run(self) -> None:
        """Every step in order (see the module docstring)."""
        if in_ci(self.environ):
            raise SetupError(
                "setup is interactive and refused when CI is set: run it on your machine, then `otterdog-acceptance ci-sync`"
            )
        self.values = read_env_file(self.env_path)
        REDACTOR.add(
            *(value for key, value in self.values.items() if SECRET_KEY_RE.search(key) and not is_reference(value))
        )
        if self.options.banner:
            self.echo(banner(f"setup of {self.instance}"))
        self.echo(f"settings file: {self.env_path}")
        self.copy_from()
        self.section("Secret store")
        self.store_step()
        self.section("Shard")
        self.shard_step()
        self.section("Organization")
        org = self.org_step()
        self.role_section("admin")
        self.role_step("admin", org)
        self.section("Profile")
        self.profile_step(org)
        for role in ROLES:
            if role != "admin":
                self.role_section(role)
                self.role_step(role, org)
        self.section("Web-UI login of the admin account")
        self.web_step()
        self.section("GitHub App")
        app = self.app_step(org)
        self.section("Bootstrap and doctor")
        self.finish(org, app)

    def role_section(self, role: str) -> None:
        """The step of a role's token, titled with what the role does."""
        self.section(f"{role} token: {ROLE_TOKENS[role].purpose}")

    def list_shard_instance(self) -> None:
        """An instance of a shard joins ~/.config/otterdog-acceptance/lists/shards, the target of ``run --target @shards``."""
        if self.shard is None:
            return
        path = add_to_list(SHARDS_LIST, self.instance, self.environ)
        if path is not None:
            self.done(f"{self.instance} listed in {path}: otterdog-acceptance run --target @{SHARDS_LIST} --parallel 5")

    def copy_from(self) -> None:
        """--from: copy COPYABLE_KEYS of another instance that this one does not set yet."""
        source = self.options.from_instance
        if not source:
            return
        if check_instance_name(source) == self.instance:
            raise SetupError("--from names the instance being set up")
        path = instance_env_path(source, self.environ)
        if not path.is_file():
            raise SetupError(f"--from {source}: {path} does not exist")
        values = read_env_file(path)
        keys = [key for key in COPYABLE_KEYS if not (key == "E2E_PROFILE" and self.instance in self.profiles())]
        copied = {key: values[key] for key in keys if values.get(key) and not self.values.get(key)}
        if copied:
            self.echo(f"copied from instance {source}: {', '.join(copied)}")
            self.write(copied)

    def org_step(self) -> OrgInfo:
        """The live org (created by the operator when missing); E2E_ORG and E2E_ORG_ID written. Its login: --org, the
        stored one, otterdog-e2e-<instance> for the instance of a shard (not asked), else asked."""
        pinned = self.values.get("E2E_ORG")
        proposed = f"otterdog-e2e-{self.instance}"
        login = self.options.org or pinned or (proposed if self.shard is not None else None)
        login = (login or self.answer("Login of the dedicated test organization", proposed)).strip()
        if pinned and login.lower() != pinned.lower():
            raise SetupError(
                f"{self.env_path} pins the organization {pinned}: set up {login} as another instance (--target)"
            )
        if not LOGIN_RE.fullmatch(login):
            raise SetupError(f"{login!r} is not a GitHub organization login")
        check_org_allowed(login)
        anonymous = self.http(None, "anonymous")
        windows = 0
        while (data := anonymous.get(f"/orgs/{login}", allow_404=True)) is None:
            if self.automatic and windows:  # automatic: one window, then setup stops (never a loop of windows)
                raise SetupError(
                    f"organization {login} was not created in the window: create it (GitHub has no API for it, and "
                    "its terms forbid accounts made by automated means), then run setup again"
                )
            for line in self.org_creation_help(login):
                self.echo(line)
            shown = self.create_org_in_browser(login)
            windows += shown
            if not self.ask(f"Check {login} again?", True, automatic=shown):
                raise SetupError(f"organization {login} not found: create it, then run setup again")
        live, org_id = str(data.get("login") or ""), data.get("id")
        if isinstance(org_id, bool) or not isinstance(org_id, int) or org_id <= 0 or not LOGIN_RE.fullmatch(live):
            raise SetupError(f"unexpected GET /orgs/{login} answer (no login or numeric id)")
        check_org_allowed(live)
        pinned_id = self.values.get("E2E_ORG_ID")
        if pinned_id and pinned_id != str(org_id):
            raise SetupError(
                f"E2E_ORG_ID of {self.env_path} is {pinned_id} but {live} has id {org_id} (renamed, recreated or "
                "another organization): nothing changed; remove E2E_ORG_ID from the file only if the org was "
                "recreated on purpose"
            )
        if live != login:
            self.echo(f"using the exact-case login {live}")
        others = self.known_org_ids().get(org_id)
        if others:
            self.echo(
                f"note: instance {', '.join(others)} pins the same organization (runs of both share its org lease)"
            )
        self.done(f"{live} (id {org_id})")
        self.write({"E2E_ORG": live, "E2E_ORG_ID": str(org_id)})
        return OrgInfo(live, org_id)

    def org_creation_help(self, login: str) -> list[str]:
        """How to create the missing org (GitHub has no API for Free/Team orgs), after the plan of the profile
        (--profile, E2E_PROFILE, else the profile named like the instance; a profile's literal expected_plan); while
        no plan is known: the Free URL and the Enterprise Cloud note, and the hint to pass --profile."""
        plan = self.org_plan()
        if plan == "enterprise":
            return [f"organization {login} not found.", ENTERPRISE_ORG_NOTE]
        create = f"organization {login} not found: create it signed in as the admin machine account (no API can):"
        empty = f"  name it {login}, keep it empty (no repositories, teams, secrets), no SAML SSO, no IP allow list"
        url = ORG_CREATION_URLS.get(plan or "")
        if url:
            return [create, f"  {url}", empty]
        choices = "|".join(self.profiles()) or "<profile>"
        return [
            create,
            f"  Free: {ORG_CREATION_URLS['free']} (Team: {ORG_CREATION_URLS['team']})",
            empty,
            f"  {ENTERPRISE_ORG_NOTE} (not automated by setup)",
            f"  the plan of instance {self.instance} is not known yet: pass --profile {choices} for its hint only",
        ]

    def org_plan(self) -> str | None:
        """The plan of the org to create: the one of the profile (--profile, E2E_PROFILE, else the profile named like
        the instance; a profile's literal expected_plan), None while it is not known."""
        shard_profile = self.shard.profile if self.shard is not None else None
        profile = self.options.profile or self.values.get("E2E_PROFILE") or shard_profile or self.instance
        return profile if profile in (*ORG_CREATION_URLS, "enterprise") else self.expected_plan(profile)

    # --- shard --------------------------------------------------------------------------------------------------
    def shard_step(self) -> None:
        """E2E_SHARD: the live items the instance runs (scenarios/shards.yaml): --shard, the stored one, else the shard
        named like the instance (proposed, the operator confirms); none (NO_SHARD) or no shard map: every live item."""
        try:
            self.shard_map = load_shards(self.settings.project_root)
        except ShardError as exc:
            raise SetupError(str(exc)) from None
        stored = self.values.get(SHARD_ENV)
        name = self.options.shard or stored
        if name is None and self.shard_map is not None and self.instance in self.shard_map.names:
            shard = self.shard_map.get(self.instance)
            question = f"Run only the live items of the shard {shard.name} on {self.instance} ({shard.description})?"
            name = shard.name if self.ask(question, True) else NO_SHARD
        if name is None or name == NO_SHARD:
            if stored and name == NO_SHARD:
                self.write({SHARD_ENV: ""})
            self.skipped(f"none: {self.instance} runs every live item")
            return
        if self.shard_map is None:
            raise SetupError(f"shard {name}: no {SHARDS_FILE} in {self.settings.project_root}")
        try:
            self.shard = self.shard_map.get(name)
        except ShardError as exc:
            raise SetupError(str(exc)) from None
        self.done(f"{self.shard.name}: {self.shard.description} (profile {self.shard.profile})")
        self.write({SHARD_ENV: self.shard.name})

    def shard_runs(self, tier: str) -> bool | None:
        """Whether the shard of the instance runs the items of ``tier`` (None without a shard: every tier)."""
        if self.shard is None or self.shard_map is None:
            return None
        return self.shard_map.assign(ItemFacts(tier)) is self.shard

    def create_org_in_browser(self, login: str) -> bool:
        """Offer the creation page of the org in a browser signed in as the admin account of the accounts store: its
        name is proposed, the operator confirms it or names another account (the org's owner); the window stays until
        the operator is done (True). Not offered without sign_in_at, an accounts store or a creation URL (plan)."""
        url = ORG_CREATION_URLS.get(self.org_plan() or "")
        if self.sign_in_at is None or url is None or self.accounts_config is None:
            return False
        if not self.ask(f"Create {login} in a browser signed in as the admin account?", True):
            return False
        default = self.accounts_config.account(self.instance, "admin").label
        account = self.answer("Account that creates the organization (its owner: the admin)", default).strip()
        self.echo(
            f"in the window, create the organization {login} yourself (the one step left to you: no API creates it): "
            "its name, a contact e-mail, owned by the account, then keep it empty; press Enter below once it exists"
        )
        try:
            self.sign_in_at(account or default, url)
        except AccountError as exc:
            self.warn(f"browser: {exc}: create {login} by hand")
            return False
        return True

    # --- tokens -------------------------------------------------------------------------------------------------
    def role_step(self, role: str, org: OrgInfo) -> None:
        """One role: keep the stored valid token (unless rotated), else prompt for a new one (optional roles may be
        skipped); an unusable stored token may be removed."""
        spec = ROLE_TOKENS[role]
        stored = self.values.get(spec.token_env)
        rotate = role in self.options.rotate
        if stored and not rotate and self.keep_stored(role, stored, org):
            return
        found = None if stored or rotate else self.from_store(spec.token_env)
        if found is not None:
            self.echo(f"found in the store at {found}")
            if self.keep_stored(role, found, org):
                return
        found = None if stored or rotate else self.from_account(role)
        if found is not None:
            self.echo(f"found in the accounts store at {found}")
            if self.keep_stored(role, found, org, keep_reference=self.keeps_account_references):
                return
        if self.drop_flagged(role, stored):
            return
        config = self.accounts_config
        if not stored and not spec.required and self.automatic and config is not None:
            # the accounts store decides, nothing asked: the role is set up when its account is in it
            if not self.account_exists(role):
                account = config.account(self.instance, role)
                self.skipped(f"skipped: {account.label} is not in {config.store} (run setup again once it is)")
                return
        # the oracle is usually left out (the admin token serves as oracle): only that question defaults to no
        elif not stored and not spec.required and not self.io.confirm(self.optional_question(role), role != "oracle"):
            self.skipped("skipped (run setup again to add it)")
            return
        by_browser = self.browser_tokens
        if (by_browser and self.browser_token(role, org)) or self.drop_flagged(role, stored):
            return
        if self.prompt_token(role, org, stored=stored if rotate else None, brief=by_browser):
            return
        if stored and rotate and self.keep_stored(role, stored, org):
            return
        if spec.required:
            raise SetupError(f"{role}: a valid token is required")
        if stored and self.ask(f"Remove the unusable {spec.token_env} from {self.env_path}?", True):
            self.write({spec.token_env: None, spec.login_env: None, spec.type_env: None})

    def drop_flagged(self, role: str, stored: str | None) -> bool:
        """An optional role whose account GitHub flagged (check_flagged) is left out without asking, its stored token
        removed (True); False for any other role."""
        spec = ROLE_TOKENS[role]
        if role not in self.flagged or spec.required:
            return False
        if stored:
            self.write({spec.token_env: None, spec.login_env: None, spec.type_env: None})
        removed = f" (its {spec.token_env} removed)" if stored else ""
        self.skipped(f"skipped: GitHub flagged {self.flagged[role]}{removed}")
        return True

    def keep_stored(self, role: str, stored: str, org: OrgInfo, *, keep_reference: bool = True) -> bool:
        """Validate the stored token (a vault reference resolved first); True (and its login/type refreshed) when it
        passes. ``keep_reference`` False: the value is recorded, not the reference (a Vault accounts store)."""
        spec = ROLE_TOKENS[role]
        try:
            token = self.reveal(stored, spec.token_env)
            checked = self.check_token(role, token, org)
        except SetupStoppedError:
            raise
        except (TokenRejectedError, SetupError) as exc:
            self.warn(f"the stored {spec.token_env} is not usable: {exc}")
            return False
        self.done(f"keeping the token of {checked.login} ({TOKEN_KIND_LABELS[checked.kind]}, {_expiry(checked)})")
        written = stored if keep_reference and is_reference(stored) else None
        self.record(role, token, checked, org, written=written)
        return True

    def provider_env(self) -> dict[str, str]:
        """The environment of the vaults: the operator's, overlaid with the env file (E2E_VAULT_ADDR, ...)."""
        return {**self.environ, **self.values}

    def reveal(self, value: str, name: str) -> str:
        """``value``, a vault reference resolved (SetupError naming ``name`` when it cannot be read)."""
        if not is_reference(value):
            return value
        try:
            return resolve(value, self.provider_env()).strip()
        except VaultError as exc:
            raise SetupError(f"{name}: {exc}") from None

    def secret(self, name: str) -> str | None:
        """The stored value of a secret variable, a vault reference resolved (SetupError when it cannot be read)."""
        value = self.values.get(name)
        return self.reveal(value, name) if value else value

    # --- secret store -------------------------------------------------------------------------------------------
    @property
    def store(self) -> str | None:
        """The instance's secret store (E2E_SECRET_STORE, set by store_step), None without one."""
        return self.values.get(STORE_ENV) or None

    def store_step(self) -> None:
        """--store (else the stored E2E_SECRET_STORE): validated and written; Vault needs E2E_VAULT_ADDR (asked,
        default VAULT_ADDR), so that ci-sync gives the jobs the same Vault."""
        value = self.options.store or self.values.get(STORE_ENV)
        if not value:
            return
        try:
            provider, prefix = parse_store(value)
        except StoreError as exc:
            raise SetupError(str(exc)) from None
        self.write({STORE_ENV: f"{provider}:{prefix}"})
        if provider == "vault" and not self.values.get("E2E_VAULT_ADDR"):
            default = self.environ.get("VAULT_ADDR") or None
            address = self.answer("Vault address (E2E_VAULT_ADDR, https://...)", default).strip().rstrip("/")
            if not address:
                raise SetupError("a vault: store needs the Vault address (E2E_VAULT_ADDR)")
            self.write({"E2E_VAULT_ADDR": address})
        self.done(f"{provider}:{prefix}: the secrets of {self.instance} go to {prefix}/{self.instance}/")

    def from_store(self, name: str) -> str | None:
        """The reference of secret ``name`` at its place in the store when it can be read there, else None."""
        if not self.store:
            return None
        reference = store_reference(self.store, self.instance, name)
        try:
            resolve(reference, self.provider_env())
        except VaultError:
            return None
        return reference

    def into_store(self, name: str, value: str) -> str:
        """Write a checked secret at its place in the store; the reference the env file gets instead of the value."""
        assert self.store is not None
        reference = store_reference(self.store, self.instance, name)
        try:
            store(reference, value, self.provider_env())
        except VaultError as exc:
            raise SetupError(f"{name}: {exc}") from None
        self.echo(f"  {name}: stored in {reference}")
        return reference

    def stored_or_plain(self, name: str, value: str) -> str:
        """What the env file gets for a plain secret: its store reference (written there) with a store, else it."""
        return self.into_store(name, value) if self.store and not is_reference(value) else value

    # --- machine accounts (onboard/accounts.py: the accounts section of the setup configuration file) -------------
    @functools.cached_property
    def accounts_config(self) -> AccountsConfig | None:
        """The accounts section of ~/.config/otterdog-acceptance/setup.yaml (E2E_SETUP_CONFIG), None without it."""
        try:
            return load_accounts_config(self.environ)
        except AccountError as exc:
            raise SetupError(str(exc)) from None

    @property
    def keeps_account_references(self) -> bool:
        """Whether the env file may refer to the accounts store: pass yes; Vault no, since a Vault policy grants a
        whole secret, and the one of the accounts holds every password and 2FA key: a CI environment reading a token
        there would read them all. Values from a Vault accounts store go to the instance store, else as values."""
        return self.accounts_config is not None and self.accounts_config.provider == "pass"

    def account_ref(self, role: str, item: str) -> str | None:
        """The reference of an item of the role's account in the accounts store when it can be read, else None."""
        if self.accounts_config is None:
            return None
        reference = self.accounts_config.account(self.instance, role).ref(item)
        try:
            resolve(reference, self.provider_env())
        except VaultError:
            return None
        return reference

    def account_exists(self, role: str) -> bool:
        """Whether the accounts store knows the role's account: its username or e-mail (read as no secret), else its
        password."""
        if self.accounts_config is None:
            return False
        account = self.accounts_config.account(self.instance, role)
        for item in ("username", "email", "password"):
            try:
                if resolve(account.ref(item), self.provider_env(), secret=item == "password").strip():
                    return True
            except VaultError:
                continue
        return False

    def from_account(self, role: str) -> str | None:
        """The reference of the role's token in the accounts store (written by ``accounts``)."""
        return self.account_ref(role, "token")

    def browser_token(self, role: str, org: OrgInfo) -> bool:
        """--browser: set up the role's machine account in the browser, then check its token like a typed one; False
        (the prompt follows) without an accounts store or when the browser fails."""
        if self.run_account is None or ROLE_TOKENS[role].classic_scopes is None:
            return False
        if self.accounts_config is None:
            self.warn(f"--browser needs the accounts section of {setup_config_path(self.environ)}")
            return False
        try:
            result = self.run_account(
                self.accounts_config.account(self.instance, role),
                org=org.login,
                rotate=role in self.options.rotate,
                environ=self.provider_env(),
            )
        except AccountError as exc:
            self.warn(f"browser: {exc}")
            return False
        return self.keep_stored(role, result.token_ref, org, keep_reference=self.keeps_account_references)

    def typed_secret(self, label: str, answer: str) -> tuple[str, str | None]:
        """(value, reference) of a typed secret: a vault reference resolved (SetupError when it cannot be read)."""
        if not is_reference(answer):
            return answer, None
        try:
            return resolve(answer, {**self.environ, **self.values}).strip(), answer
        except VaultError as exc:
            raise SetupError(f"{label}: {exc}") from None

    def optional_question(self, role: str) -> str:
        """The question of an optional role: what no and yes mean (its purpose is the title of its section)."""
        config = self.accounts_config
        name = self.values.get(ROLE_TOKENS[role].login_env) or (
            config.account(self.instance, role).label if config is not None else None
        )
        of = f" of {name}" if name else ""
        if role == "oracle":
            return (
                f"Set up the oracle token{of}? (no, the default: the admin token checks what otterdog did; yes: a "
                "second owner of the organization checks it with its own token)"
            )
        return f"Set up the {role} token{of}? (no: the tests that need it are skipped)"

    def account_name(self, role: str) -> str:
        """The account a role's token is created as: its stored login, else its account in the accounts store."""
        stored = self.values.get(ROLE_TOKENS[role].login_env)
        if stored:
            return stored
        config = self.accounts_config
        return config.account(self.instance, role).label if config is not None else f"the {role} machine account"

    def url_kind(self, role: str) -> str:
        """Kind of the prefilled URL: the only kind of the role, else --token-type, the stored type, classic."""
        kinds = ROLE_TOKENS[role].kinds
        if len(kinds) == 1:
            return kinds[0]
        wanted = self.options.token_type or self.values.get(ROLE_TOKENS[role].type_env)
        return wanted if wanted in kinds else CLASSIC

    def active_membership(self, role: str, org: OrgInfo) -> str | None:
        """The login of an author/approver/oracle account that is an ACTIVE member of the org (fine-grained tokens
        need it): asked, invited with the admin token when it is no member (never changing an existing membership)
        and polled until the invitation is accepted; None when it is skipped or not accepted in time."""
        spec = ROLE_TOKENS[role]
        login = self.member_login(role, org)
        if login is None:
            self.skipped()
            return None
        admin = self.clients["admin"]
        path = f"/orgs/{org.login}/memberships/{login}"
        membership = admin.get(path, allow_404=True)
        if membership is None:
            self.invite(role, login, org)
        elif membership.get("role") != FINE_GRAINED_INVITES[role]:
            note = "; doctor requires the oracle to be an owner" if role == "oracle" else ""
            self.echo(f"{login} is a member with role {membership.get('role')!r} already (left unchanged{note})")
        self.write({spec.login_env: login, spec.type_env: FINE_GRAINED})
        if (membership or {}).get("state") == "active":
            return login
        invitation = INVITATION_URL.format(org=org.login)
        self.echo(
            f"signed in as {login}, accept the invitation: {invitation} (waiting up to "
            f"{self.options.wait_timeout:g} s; Ctrl-C stops, setup can be run again)"
        )
        self.open(invitation)
        if self.web is not None:
            self.web.join(role, org.login, login, public=role in PUBLIC_MEMBERS)
        try:
            wait_until(
                lambda: (admin.get(path, allow_404=True) or {}).get("state") == "active",
                timeout=self.options.wait_timeout,
                interval=self.options.poll_interval,
                what=f"active membership of {login} in {org.login}",
                sleep=self.io.sleep,
                clock=self.io.clock,
            )
        except WaitTimeoutError:
            self.warn(
                f"{login} has not accepted the invitation yet: run setup again once it did (a mistyped "
                f"login: cancel its invitation at {PEOPLE_URL.format(org=org.login)})"
            )
            return None
        self.done(f"{login} is an active member of {org.login}")
        return login

    def member_login(self, role: str, org: OrgInfo) -> str | None:
        """The login of the role's account (stored or asked; empty: None): a GitHub user no other role uses."""
        stored = self.values.get(ROLE_TOKENS[role].login_env)
        for _ in range(MAX_ATTEMPTS):
            login = self.io.prompt(
                f"Login of the {role} machine account (its fine-grained token needs an active membership of "
                f"{org.login} first; empty: skip)",
                stored or "",
            ).strip()
            if not login:
                return None
            try:
                if not LOGIN_RE.fullmatch(login):
                    raise TokenRejectedError(f"{login!r} is not a GitHub login")
                self.refuse_shared(role, login, what="account")
                user = self.clients["admin"].get(f"/users/{login}", allow_404=True)
                if not isinstance(user, Mapping) or user.get("type") != "User":
                    raise TokenRejectedError(f"{login} is not a GitHub user account")
            except TokenRejectedError as exc:
                self.warn(str(exc))
                continue
            return str(user.get("login") or login)
        raise SetupError(f"{role}: no valid login after {MAX_ATTEMPTS} attempts")

    def admin_writer(self) -> GitHubHttp:
        """The admin token's client, write-scoped to the org verified first (pin and plan; the marker is
        bootstrap's): the only writing client of setup (invitations and their cancellation)."""
        from otterdog_acceptance import safety

        admin_token = self.secret(ROLE_TOKENS["admin"].token_env)
        if not admin_token:
            raise SetupError("the admin token is needed for the invitations")
        verified = safety.verify_target(
            self.clients["admin"], self.target(), {}, require_marker=False, check_identities=False
        )
        return self.write_http(admin_token, verified)

    def invite(self, role: str, login: str, org: OrgInfo) -> None:
        """PUT /orgs/{org}/memberships/{login} with the admin token (admin_writer): author/approver as members, the
        oracle as an owner; remembered as an invitation of this run (withdraw_invitation)."""
        org_role = FINE_GRAINED_INVITES[role]
        self.admin_writer().put(f"/orgs/{org.login}/memberships/{login}", json={"role": org_role})
        self.invited[role] = login
        self.done(f"invited {login} to {org.login} as {'an owner' if org_role == 'admin' else 'a member'}")

    def withdraw_invitation(self, role: str, login: str, org: OrgInfo) -> None:
        """The role ends without a token after a token of ANOTHER account than the invited ``login`` was refused: the
        invitation THIS run created is cancelled while it is still pending (DELETE /orgs/{org}/memberships/{login}
        with the admin token cancels a pending invitation; the stored login goes too unless the role keeps a token);
        an invitation that was accepted already is only reported (removing a member stays the operator's call), and
        an older invitation or membership is never touched."""
        if self.invited.get(role, "").lower() != login.lower():
            return
        spec = ROLE_TOKENS[role]
        path = f"/orgs/{org.login}/memberships/{login}"
        people = PEOPLE_URL.format(org=org.login)
        what = "an owner" if FINE_GRAINED_INVITES[role] == "admin" else "a member"
        try:
            state = (self.clients["admin"].get(path, allow_404=True) or {}).get("state")
            if state == "pending":
                self.admin_writer().delete(path)
        except GitHubError as exc:
            self.warn(f"cannot cancel the invitation of {login} ({exc.status}): cancel it at {people}")
            return
        if state == "pending":
            self.invited.pop(role, None)
            self.echo(f"cancelled the pending invitation of {login} to {org.login} (created by this run)")
            if not self.values.get(spec.token_env):
                self.write({spec.login_env: None})
        elif state == "active":
            self.warn(
                f"{login} accepted the invitation of this run and stays {what} of {org.login}: if it "
                f"is not the {role} machine account, remove it: {people}"
            )

    @property
    def automatic(self) -> bool:
        """Whether setup decides instead of asking: with the accounts store (and the browser), every question takes
        its answer (``ask``, ``answer``); what only the operator has (a webhook URL, a profile nobody can tell) is still
        asked."""
        return self.browser_tokens and self.accounts_config is not None

    @property
    def shares_accounts(self) -> bool:
        """Whether the instance uses the accounts of another set (accounts.set): they serve several test orgs."""
        config = self.accounts_config
        return config is not None and config.account(self.instance, "admin").instance != self.instance

    def ask(self, question: str, default: bool, *, automatic: bool | None = None) -> bool:
        """A yes/no question; in automatic mode not asked: ``automatic``, else ``default``."""
        if self.automatic:
            return default if automatic is None else automatic
        return self.io.confirm(question, default)

    def answer(self, question: str, default: str | None) -> str:
        """A question with a text answer; in automatic mode its default, when it has one, is taken without asking."""
        if self.automatic and default:
            return default
        return self.io.prompt(question, default)

    @property
    def browser_tokens(self) -> bool:
        """Whether the tokens are created in the browser: --browser / --no-browser, else when the accounts store is
        configured (and the CLI can open the browser)."""
        if self.options.browser is not None:
            return self.options.browser
        return self.run_account is not None and self.accounts_config is not None

    def prompt_token(self, role: str, org: OrgInfo, *, stored: str | None, brief: bool = False) -> bool:
        """Print the prefilled URL (``brief``: after the browser, that URL only, without the steps) and read tokens
        until one passes (True, written) or the operator enters nothing (False); SetupError after MAX_ATTEMPTS
        refused tokens."""
        spec = ROLE_TOKENS[role]
        kind = self.url_kind(role)
        invited = None
        if kind == FINE_GRAINED and role in FINE_GRAINED_INVITES:
            invited = self.active_membership(role, org)
            if invited is None:
                return False
        url = token_url(
            role,
            kind,
            instance=self.instance,
            org=org.login,
            login=self.values.get(spec.login_env),
            expires_in=self.options.expires_in,
        )
        if brief:
            self.echo(f"create it by hand, signed in as {self.account_name(role)}: {url}")
        else:
            self.echo(f"Create a {TOKEN_KIND_LABELS[kind]}, signed in as {self.account_name(role)}:")
            steps = [f"open {url}", *token_steps(role, kind, org.login), "Generate token, copy it and paste it below"]
            for number, step in enumerate(steps, start=1):
                self.echo(f"  {number}. {step[:1].upper()}{step[1:]}")
            other = [item for item in spec.kinds if item != kind]
            if other:
                self.echo(f"(a {TOKEN_KIND_LABELS[other[0]]} works too: --token-type {other[0]})")
        if stored and not brief:
            self.echo("(rotating: regenerating the existing token in the account's settings works too)")
        self.open(url)
        empty = "keep the stored one" if stored else ("try again" if spec.required else "skip")
        other_account = False  # a token of another account than the invited one was refused
        for _ in range(MAX_ATTEMPTS):
            token = self.io.secret_prompt(
                f"Paste the {role} token or a vault reference (input hidden; empty: {empty})"
            ).strip()
            if not token:
                if spec.required and not stored:
                    self.warn("the token is required")
                    continue
                self.skipped("unchanged" if stored else "skipped")
                if invited and other_account:
                    self.withdraw_invitation(role, invited, org)
                return False
            try:
                token, reference = self.typed_secret(f"{role} token", token)
                REDACTOR.add(token)
                checked = self.check_token(role, token, org)
                if invited and checked.login.lower() != invited.lower():
                    other_account = True
                    raise TokenRejectedError(f"token of {checked.login}, but {invited} is the invited {role} account")
            except SetupStoppedError:
                raise
            except (TokenRejectedError, SetupError) as exc:
                self.warn(f"token refused, nothing written: {exc}")
                continue
            self.record(role, token, checked, org, written=reference)
            return True
        if invited and other_account:
            self.withdraw_invitation(role, invited, org)
        raise SetupError(f"{role}: no valid token after {MAX_ATTEMPTS} attempts (nothing written for this role)")

    def record(self, role: str, token: str, checked: CheckedToken, org: OrgInfo, *, written: str | None = None) -> None:
        """Write login, token (``written``: the vault reference it came from) and kind of a checked token (the admin's
        token as oracle is the fallback: not stored), after the shared org ids its checks allowed (write_shared)."""
        spec = ROLE_TOKENS[role]
        self.write_shared(checked, org)
        if role == "oracle" and token == self.secret(ROLE_TOKENS["admin"].token_env):
            self.done("same token as the admin, which is the oracle's fallback anyway: nothing stored")
            self.write({spec.token_env: None, spec.login_env: None, spec.type_env: None})
            return
        if written is None and self.store:
            written = self.into_store(spec.token_env, token)
        previous = self.values.get(spec.login_env)
        if previous and previous.lower() != checked.login.lower():
            self.echo(f"the login changes from {previous} to {checked.login}")
        if (written or token) != self.values.get(spec.token_env):
            self.done(f"token of {checked.login} accepted ({TOKEN_KIND_LABELS[checked.kind]}, {_expiry(checked)})")
        self.write({spec.login_env: checked.login, spec.token_env: written or token, spec.type_env: checked.kind})

    def check_flagged(self, role: str, login: str) -> None:
        """A flagged account (its profile hidden from an anonymous GET /users/{login}): a warning, then a question even
        in automatic mode (the operator may be lifting the flag): continue (default) or stop (SetupError). Continuing
        leaves a role that joins the org out (TokenRejectedError, remembered in ``flagged``: drop_flagged) and keeps
        the others' account as it is. Asked once per account."""
        if login.lower() in self.visible_accounts:
            return
        if self.http(None, "anonymous").get(f"/users/{login}", allow_404=True) is not None:
            self.visible_accounts.add(login.lower())
            return
        joins = role in JOINING_ROLES and not ROLE_TOKENS[role].required
        if login.lower() not in self.flag_answers:
            self.warn(FLAGGED_HELP.format(login=login, loss=FLAGGED_LOSS.get(role, FLAGGED_JOIN_LOSS)))
            question = (
                f"Continue the setup without the {role} {login}? (no: setup stops; run it again once the flag is lifted)"
                if joins
                else f"Continue the setup with {login} as it is? (no: setup stops; run it again once the flag is lifted)"
            )
            self.flag_answers[login.lower()] = self.io.confirm(question, True)
        if not self.flag_answers[login.lower()]:
            raise SetupStoppedError(f"stopped: GitHub flagged {login}; run setup again once the flag is lifted")
        if joins:
            self.flagged[role] = login
            raise TokenRejectedError(f"GitHub flagged {login}")

    def check_token(self, role: str, token: str, org: OrgInfo) -> CheckedToken:
        """Every check of a role's token (TokenRejectedError with the reason): shape, not another role's token, GET /user,
        kind, classic scopes, isolation (safety.check_identity_isolation, with the shared org ids accepted for this
        token in memory only: shared_org_offer), owner membership. Nothing is written here (record does)."""
        from otterdog_acceptance import safety

        spec = ROLE_TOKENS[role]
        shared: dict[int, tuple[str, ...]] = {}
        if not TOKEN_SHAPE_RE.fullmatch(token):
            raise TokenRejectedError("this does not look like a GitHub token (ghp_... or github_pat_...)")
        self.refuse_shared(role, token, what="token")
        http = self.http(token, role)
        try:
            user = http.get("/user") or {}
        except GitHubError as exc:
            raise TokenRejectedError(f"GET /user answered {exc.status}: not a valid token") from None
        login = str(user.get("login") or "") if isinstance(user, Mapping) else ""
        if not LOGIN_RE.fullmatch(login):
            raise TokenRejectedError("GET /user returned no login")
        self.refuse_shared(role, login, what="account")
        self.check_flagged(role, login)
        try:
            info = safety.read_token_info(http, role)
        except SafetyError as exc:
            raise TokenRejectedError(str(exc)) from None
        if info.kind not in spec.kinds:
            accepted = " or ".join(TOKEN_KIND_LABELS[kind] for kind in spec.kinds)
            found = TOKEN_KIND_LABELS.get(info.kind, "App or OAuth token")
            raise TokenRejectedError(f"the {role} needs a {accepted}, got a {found}")
        if info.kind == CLASSIC:
            missing = missing_scopes(role, info.scopes or ())
            if missing:
                raise TokenRejectedError(f"the classic PAT lacks {', '.join(missing)} (use the prefilled URL)")
            shared = self.shared_org_offer(http, login, org)
        try:
            safety.check_identity_isolation(
                http,
                role=role,
                allowed_org_ids=list(dict.fromkeys([*self.allowed_org_ids(org), *shared])),
                test_org_id=org.org_id,
                org=org.login,
                token_type=info.kind,
            )
        except SafetyError as exc:
            hint = ""
            if info.kind == FINE_GRAINED and role in MEMBER_ROLES:
                hint = (
                    f" (a member's fine-grained token needs an active membership of {org.login}: accept the "
                    f"invitation of bootstrap first, then run setup again with --rotate {role})"
                )
            raise TokenRejectedError(f"{exc}{hint}") from None
        if role in safety.OWNER_ROLES:
            self.check_owner(role, http, login, org)
        self.clients[role] = http
        return CheckedToken(login, info.kind, info.expires_at, tuple(sorted(shared.items())))

    def refuse_shared(self, role: str, value: str, *, what: str) -> None:
        """TokenRejectedError when another role with a stored token already holds this ``token`` or ``account`` (login,
        case-insensitive); the oracle may share the admin's."""
        for other, spec in ROLE_TOKENS.items():
            if other == role or {role, other} == {"admin", "oracle"}:
                continue
            try:
                token = self.secret(spec.token_env)
            except SetupError:
                continue  # an unreadable reference is reported at the step of its own role
            if not token:
                continue
            stored = token if what == "token" else (self.values.get(spec.login_env) or "").lower()
            if stored and stored == (value if what == "token" else value.lower()):
                raise TokenRejectedError(
                    f"the same {what} is already stored for the {other}: every role needs its own machine account "
                    "and token"
                )

    def check_owner(self, role: str, http: GitHubHttp, login: str, org: OrgInfo) -> None:
        """The admin must be an active owner of the org; a separate oracle is reported when it is not (yet) one."""
        try:
            membership = http.get(f"/user/memberships/orgs/{org.login}", allow_404=True)
        except GitHubError as exc:
            raise TokenRejectedError(f"cannot read the membership of {login} in {org.login} ({exc.status})") from None
        membership = membership if isinstance(membership, Mapping) else {}
        state, org_role = membership.get("state"), membership.get("role")
        if state == "active" and org_role == "admin":
            return
        if role == "admin":
            raise TokenRejectedError(
                f"{login} is not an owner of {org.login} (membership {state or 'none'}, role {org_role or 'none'}): "
                "the admin account must own the organization"
            )
        self.echo(
            f"{login} is not an owner of {org.login} yet (membership {state or 'none'}): bootstrap invites "
            "it as an owner, doctor checks it"
        )

    def allowed_org_ids(self, org: OrgInfo) -> list[int]:
        """The pinned org id plus E2E_ALLOWED_ORG_IDS."""
        return list(dict.fromkeys([org.org_id, *parse_org_ids(self.values.get("E2E_ALLOWED_ORG_IDS"))]))

    def known_org_ids(self) -> dict[int, list[str]]:
        """Org id -> names of the OTHER instances whose env files pin it (E2E_ORG_ID; not validated: see
        validation_problem)."""
        found: dict[int, list[str]] = {}
        for name, path in known_instances(self.environ).items():
            if name == self.instance:
                continue
            value = read_env_file(path).get("E2E_ORG_ID", "")
            if value.isdigit():
                found.setdefault(int(value), []).append(name)
        return found

    def validation_problem(self, http: GitHubHttp, name: str, org_id: int) -> str | None:
        """Why ``org_id``, pinned by instance ``name``, is NOT a validated test org (None: it is): the module docstring's
        rule (env file with the admin login and token setup writes only after the owner check, the instance's target,
        and live through ``http``: the org's id and the safety marker in its description)."""
        from otterdog_acceptance.settings import load_target

        path = instance_env_path(name, self.environ)
        values = read_env_file(path)
        admin = ROLE_TOKENS["admin"]
        if not (values.get(admin.login_env) and values.get(admin.token_env)):
            return f"{path} holds no validated admin token (complete `otterdog-acceptance setup --target {name}` first)"
        try:
            target = load_target(name, self.settings, environ=values)
        except (TargetError, SafetyError) as exc:
            return f"the target of instance {name} does not load: {exc}"
        if target.org_id != org_id:
            return f"the target of instance {name} pins org id {target.org_id}"
        try:
            data = http.get(f"/orgs/{target.org}", allow_404=True)
        except GitHubError as exc:
            return f"GET /orgs/{target.org} answered {exc.status}"
        data = data if isinstance(data, Mapping) else {}
        if data.get("id") != org_id:
            return f"{target.org} does not have the id {org_id} (renamed or recreated)"
        if target.marker not in str(data.get("description") or ""):
            return (
                f"the description of {target.org} lacks the safety marker {target.marker!r} that proves a dedicated "
                f"test org (run `otterdog-acceptance bootstrap --target {name} --apply` first)"
            )
        return None

    def shared_org_offer(self, http: GitHubHttp, login: str, org: OrgInfo) -> dict[int, tuple[str, ...]]:
        """Classic PAT of an account that also belongs to orgs beyond this instance's allowlist: when every such org is
        the validated test org of other instances (validation_problem), offer them (default: no); the accepted org
        ids -> their instances. In memory only: record writes them once the token passed every check."""
        try:
            items = [
                *http.paginate("/user/orgs"),
                *http.paginate("/user/memberships/orgs", params={"state": "pending"}),
            ]
        except Exception:  # noqa: BLE001 - the isolation check reports the listing failure itself
            return {}
        ids = {org_id for org_id in map(_org_id_of, items) if org_id is not None}
        foreign = sorted(ids - set(self.allowed_org_ids(org)))
        known = self.known_org_ids()
        if not foreign or not set(foreign) <= set(known):
            return {}  # an org no other instance pins: the isolation check refuses it
        validated: dict[int, tuple[str, ...]] = {}
        for org_id in foreign:
            names = []
            for name in known[org_id]:
                problem = self.validation_problem(http, name, org_id)
                if problem:
                    self.echo(
                        f"note: org id {org_id} (instance {name}) is not offered for E2E_ALLOWED_ORG_IDS: {problem}"
                    )
                else:
                    names.append(name)
            if names:
                validated[org_id] = tuple(names)
        if set(validated) != set(foreign):
            return {}
        offered = ", ".join(f"org id {org_id} (instance {', '.join(names)})" for org_id, names in validated.items())
        question = (
            f"{login} also belongs to the test org of another instance: {offered}. Allow it in E2E_ALLOWED_ORG_IDS "
            f"of {self.instance}, and {org.org_id} in theirs (written only once this token passed every check; "
            "needed when machine accounts serve several test orgs)?"
        )
        return validated if self.ask(question, False, automatic=self.shares_accounts) else {}

    def write_shared(self, checked: CheckedToken, org: OrgInfo) -> None:
        """E2E_ALLOWED_ORG_IDS of a token that passed every check with shared org ids: this org id in the files of
        their instances first, then their ids in this instance's file (an interrupted write is offered again)."""
        if not checked.shared:
            return
        for _org_id, names in checked.shared:
            for name in names:
                path = instance_env_path(name, self.environ)
                theirs = parse_org_ids(read_env_file(path).get("E2E_ALLOWED_ORG_IDS"))
                if org.org_id not in theirs:
                    self.write({"E2E_ALLOWED_ORG_IDS": ",".join(str(i) for i in [*theirs, org.org_id])}, path=path)
        allowed = parse_org_ids(self.values.get("E2E_ALLOWED_ORG_IDS"))
        ids = dict.fromkeys([*allowed, *(org_id for org_id, _names in checked.shared)])
        self.write({"E2E_ALLOWED_ORG_IDS": ",".join(str(i) for i in ids)})

    # --- profile ------------------------------------------------------------------------------------------------
    def profile_step(self, org: OrgInfo) -> None:
        """E2E_PROFILE: an instance named after a profile uses it; else --profile, the stored one or the org plan; the
        profile's literal expected_plan must be the live plan (read with the admin token)."""
        data = self.clients["admin"].get(f"/orgs/{org.login}") or {}
        plan_info = data.get("plan") if isinstance(data, Mapping) else None
        plan = str((plan_info or {}).get("name") or "").lower() if isinstance(plan_info, Mapping) else ""
        if not plan:
            raise SetupError(
                f"the plan of {org.login} is not visible to the admin token (owner, admin:org / Plan read)"
            )
        available = self.profiles()
        stored = self.values.get("E2E_PROFILE")
        if self.instance in available:
            for source, value in (("--profile", self.options.profile), ("E2E_PROFILE", stored)):
                if value and value != self.instance:
                    raise SetupError(
                        f"the instance {self.instance} is the profile of the same name: {source} {value} is ambiguous "
                        "(pick another instance name)"
                    )
            profile = self.instance
        else:
            shard_profile = self.shard.profile if self.shard is not None else None
            profile = self.options.profile or stored or shard_profile or (plan if plan in available else "")
        while profile not in available:
            if profile:
                self.warn(f"no profile {profile!r} (targets/<profile>.yaml): one of {', '.join(available)}")
            profile = self.io.prompt(f"Profile of {org.login} (plan {plan})", None).strip()
        expected = self.expected_plan(profile)
        if expected and expected != plan:
            raise SetupError(
                f"profile {profile} expects plan {expected}, {org.login} is on plan {plan}: choose another --profile"
            )
        self.profile = profile
        self.done(f"{profile} (targets/{profile}.yaml), plan {plan}")
        self.write({"E2E_PROFILE": profile})

    # --- web-UI login -------------------------------------------------------------------------------------------
    def web_step(self) -> None:
        """Optional web-UI login of the admin account: password and normalized TOTP seed (hidden prompts)."""
        password_env, seed_env = DEFAULT_WEB_ENV["password_env"], DEFAULT_WEB_ENV["totp_seed_env"]
        rotate = WEB_ROTATION in self.options.rotate
        if not rotate and not (self.values.get(password_env) or self.values.get(seed_env)):
            found = {name: self.from_store(name) for name in (password_env, seed_env)}
            if all(found.values()):
                self.echo(f"found in the store at {found[password_env]} and {found[seed_env]}")
                self.write({name: str(reference) for name, reference in found.items()})
            elif self.account_web_login(password_env, seed_env):
                return
        stored_seed = self.values.get(seed_env)
        if self.values.get(password_env) and stored_seed and not rotate:
            try:
                kept_password = self.secret(password_env) or ""
                kept_seed = normalize_totp_seed(self.secret(seed_env) or "", where=seed_env)
            except (WebCredentialsError, SetupError) as exc:
                self.warn(str(exc))
            else:
                self.done(f"keeping {password_env} and {seed_env}")
                if self.store:  # plain values move into the store, references stay as they are
                    values = ((password_env, kept_password), (seed_env, kept_seed))
                    moved = {
                        name: self.into_store(name, value)
                        for name, value in values
                        if not is_reference(self.values[name])
                    }
                    if moved:
                        self.write(moved)
                return
        elif not rotate and not self.ask(
            "Set up the web-UI login of the admin account? (optional: the web-UI tier logs in to github.com as the "
            "admin, trusted SUTs only)"
            + (
                f"; the shard {self.shard.name} runs it" if self.shard is not None and self.shard_runs("web_ui") else ""
            ),
            bool(self.shard_runs("web_ui")),
        ):
            self.skipped(self.web_skip_reason() if self.automatic else "skipped")
            return
        admin = self.values.get(ROLE_TOKENS["admin"].login_env, "the admin account")
        self.echo(
            f"{admin}: two-factor authentication with an authenticator app (TOTP) only; its setup key "
            "is shown once while enrolling it (https://github.com/settings/security) and cannot be read back"
        )
        password = ""
        for _ in range(MAX_ATTEMPTS):
            answer = self.io.secret_prompt(
                f"password of {admin} on github.com, or its vault reference (input hidden; empty: skip)"
            )
            if not answer:
                break
            try:
                value, reference = self.typed_secret(password_env, answer)
            except SetupError as exc:
                self.echo(str(exc))
                continue
            REDACTOR.add(value)
            password = reference or value
            break
        else:
            raise SetupError(f"{password_env}: no readable password after {MAX_ATTEMPTS} attempts (nothing written)")
        if not password:
            self.skipped()
            return
        seed = self.read_seed(seed_env)
        if seed is None:
            self.skipped()
            return
        self.write(
            {
                password_env: self.stored_or_plain(password_env, password),
                seed_env: self.stored_or_plain(seed_env, seed),
            }
        )

    def web_skip_reason(self) -> str:
        """Why automatic setup leaves the web-UI login out: the shard that runs the web-UI tier is another one, or the
        instance has no shard (the login is then added on request)."""
        if self.shard is None or self.shard_map is None:
            return f"skipped: no shard says {self.instance} runs the web-UI tier (setup --rotate web adds the login)"
        return self.elsewhere("web_ui", "the web-UI tier runs")

    def elsewhere(self, tier: str, what: str) -> str:
        """ "skipped: <what> on the shard X, not Y": automatic setup leaving out the step of another shard's tier."""
        assert self.shard is not None and self.shard_map is not None
        return f"skipped: {what} on the shard {self.shard_map.assign(ItemFacts(tier)).name}, not {self.shard.name}"

    def account_web_login(self, password_env: str, seed_env: str) -> bool:
        """Offer the admin account's password and 2FA key of the accounts store as the web-UI login (opt-in, default
        no, like the web step itself); True when written: their references (pass), else their values, into the instance
        store when there is one (keeps_account_references)."""
        refs = {password_env: self.account_ref("admin", "password"), seed_env: self.account_ref("admin", "totp_seed")}
        if not all(refs.values()) or not self.ask(
            f"Use the admin account's {refs[password_env]} and {refs[seed_env]} as the web-UI login? (optional: the "
            "web-UI tier logs in to github.com as the admin, trusted SUTs only)",
            False,
            automatic=bool(self.shard_runs("web_ui")),
        ):
            return False
        try:
            values = {name: resolve(str(reference), self.provider_env()).strip() for name, reference in refs.items()}
            REDACTOR.add(*values.values())
            values[seed_env] = normalize_totp_seed(values[seed_env], where=seed_env)
        except (VaultError, WebCredentialsError) as exc:
            self.warn(str(exc))
            return False
        if self.keeps_account_references:
            self.write({name: str(reference) for name, reference in refs.items()})
            self.done(f"{password_env} and {seed_env} refer to the admin account in the accounts store")
        else:
            self.write({name: self.stored_or_plain(name, value) for name, value in values.items()})
            self.done(f"{password_env} and {seed_env} copied from the admin account in the accounts store")
        return True

    def read_seed(self, seed_env: str) -> str | None:
        """A TOTP setup key normalized by settings.normalize_totp_seed, or the vault reference of a valid one (None:
        skipped)."""
        for _ in range(MAX_ATTEMPTS):
            raw = self.io.secret_prompt(
                "TOTP setup key: base32, otpauth:// URI or a vault reference (input hidden; empty: skip)"
            ).strip()
            if not raw:
                return None
            try:
                raw, reference = self.typed_secret(seed_env, raw)
                REDACTOR.add(raw)
                seed = normalize_totp_seed(raw, where=seed_env)
            except (WebCredentialsError, SetupError) as exc:
                self.echo(str(exc))
                continue
            REDACTOR.add(seed, seed.lower())
            return reference or seed
        raise SetupError(f"{seed_env}: no valid TOTP setup key after {MAX_ATTEMPTS} attempts (nothing written)")

    # --- GitHub App ---------------------------------------------------------------------------------------------
    def app_step(self, org: OrgInfo, *, confirmed: bool = False) -> str:
        """The App of the webapp tiers: kept, created through the manifest flow, or skipped; APP_READY, APP_SKIPPED or
        APP_NEEDS_MARKER (the org description lacks the safety marker that bootstrap adds)."""
        app_id = self.values.get("E2E_APP_ID")
        rotate = APP_ROTATION in self.options.rotate
        if app_id and not rotate:
            self.done(f"keeping {self.values.get('E2E_APP_SLUG') or '?'} (id {app_id})")
            self.app_into_store()
            self.wait_installation(org)
            return APP_READY
        if self.run_manifest is None:
            self.skipped("the manifest flow is not available here (otterdog-acceptance app-manifest)")
            return APP_SKIPPED
        needed = self.shard_runs("webapp")
        why = (
            ""
            if needed is None or self.shard is None
            else f"; the shard {self.shard.name} " + ("runs them" if needed else "does not run them")
        )
        # automatic: for the shard that runs the tiers; without a shard, only when the webhook sink is known already
        sink = bool(self.options.webhook_url or self.values.get(APP_WEBHOOK_URL_ENV))
        if not confirmed and not self.ask(
            f"Create the GitHub App of the webapp and webhooks tiers? (optional: one browser click){why}",
            needed is None or needed,
            automatic=bool(needed) or (needed is None and sink),
        ):
            if self.automatic and needed is False:
                self.skipped(self.elsewhere("webapp", "the webapp and webhooks tiers run"))
            elif self.automatic:
                self.skipped("skipped (setup --webhook-url <https sink> adds it)")
            else:
                self.skipped("skipped (run setup again to add it)")
            return APP_SKIPPED
        target = self.target()
        description = str((self.clients["admin"].get(f"/orgs/{org.login}") or {}).get("description") or "")
        if target.marker not in description:
            self.warn(
                f"the description of {org.login} lacks the safety marker {target.marker!r} that proves a "
                "dedicated test org: bootstrap adds it (the App is offered again right after it)"
            )
            return APP_NEEDS_MARKER
        if app_id:
            self.echo(
                f"rotating the App: a NEW App is registered; delete the old one (id {app_id}) afterwards: "
                f"https://github.com/organizations/{org.login}/settings/apps"
            )
        webhook_url = self.webhook_url()
        code = self.run_manifest(target, webhook_url)
        REDACTOR.add(code)
        result = self.exchange(code, out_dir=instance_app_dir(self.instance, self.environ))
        secret = Path(result["secret_path"]).read_text(encoding="utf-8").strip()
        REDACTOR.add(secret)
        slug = str(result["slug"])
        self.done(f"{slug} (id {result['id']}) created; private key {result['pem_path']} (0600)")
        self.write(
            {
                "E2E_APP_ID": str(result["id"]),
                "E2E_APP_SLUG": slug,
                "E2E_APP_PRIVATE_KEY_FILE": str(result["pem_path"]),
                "E2E_APP_WEBHOOK_SECRET": secret,
                "E2E_APP_PRIVATE_KEY": None,  # an inline key of a former App would win over the new key file
            }
        )
        self.app_into_store()
        if result.get("secret_generated"):
            self.warn(
                "GitHub returned no webhook secret: a random one was generated; set it as the App's webhook secret: "
                f"https://github.com/organizations/{org.login}/settings/apps/{slug}"
            )
        self.wait_installation(org)
        return APP_READY

    def app_into_store(self) -> None:
        """With a store: the App's private key (inline, else the content of its key file) and webhook secret move
        into the store; the key file is no longer referenced and may be deleted."""
        if not self.store:
            return
        updates: dict[str, str | None] = {}
        key, key_file = self.values.get("E2E_APP_PRIVATE_KEY"), self.values.get("E2E_APP_PRIVATE_KEY_FILE")
        if key and not is_reference(key):
            updates["E2E_APP_PRIVATE_KEY"] = self.into_store("E2E_APP_PRIVATE_KEY", key)
        elif not key and key_file:
            path = Path(key_file).expanduser()
            try:
                pem = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise SetupError(f"E2E_APP_PRIVATE_KEY_FILE: cannot read {path} ({type(exc).__name__})") from None
            REDACTOR.add(pem, pem.strip())
            updates["E2E_APP_PRIVATE_KEY"] = self.into_store("E2E_APP_PRIVATE_KEY", pem.strip() + "\n")
        if updates and key_file:
            updates["E2E_APP_PRIVATE_KEY_FILE"] = None
            self.echo(f"  the files of {Path(key_file).expanduser().parent} are no longer used: delete them")
        secret = self.values.get("E2E_APP_WEBHOOK_SECRET")
        if secret and not is_reference(secret):
            updates["E2E_APP_WEBHOOK_SECRET"] = self.into_store("E2E_APP_WEBHOOK_SECRET", secret)
        if updates:
            self.write(updates)

    def webhook_url(self) -> str:
        """The App's webhook sink (--webhook-url, the stored one, else asked): https, not loopback; written."""
        from otterdog_acceptance.appmanifest import check_webhook_url

        url = self.options.webhook_url or self.values.get(APP_WEBHOOK_URL_ENV) or ""
        for _ in range(MAX_ATTEMPTS):
            if not url:
                url = self.io.prompt(
                    "App webhook sink URL (any https endpoint you control that answers 2xx; deliveries are pulled "
                    "from GitHub, nothing reaches this machine)",
                    None,
                ).strip()
            try:
                check_webhook_url(url)
            except ValueError as exc:
                self.echo(str(exc))
                url = ""
                continue
            self.write({APP_WEBHOOK_URL_ENV: url})
            return url
        raise SetupError(f"no valid App webhook URL after {MAX_ATTEMPTS} attempts")

    def wait_installation(self, org: OrgInfo) -> None:
        """Verify the App (safety.verify_app: GET /app names the test org as owner, every installation is on a test
        org; SetupError otherwise, before any installation link), then print the installation URL and poll
        GET /orgs/{org}/installation (App JWT) until the App is installed; a timeout only reports (run setup again)."""
        from otterdog_acceptance.safety import verify_app
        from otterdog_acceptance.settings import resolve_app_credentials

        target = self.target()
        try:
            credentials = resolve_app_credentials(target, self.values)
        except TargetError as exc:
            self.warn(str(exc))
            return
        if credentials is None:
            return
        app = self.app_auth(credentials)
        try:
            isolation = verify_app(app, target)
        except SafetyError as exc:
            name = credentials.slug or self.values.get("E2E_APP_SLUG") or self.values.get("E2E_APP_ID") or "?"
            raise SetupError(
                f"GitHub App {name}: {exc}; no installation link for it: register a new App in {org.login} with "
                f"`otterdog-acceptance setup --target {self.instance} --rotate app`"
            ) from None
        installation = app.installation_for_org(org.login)
        if installation is None:
            slug = credentials.slug or self.values.get("E2E_APP_SLUG") or isolation.slug
            url = APP_INSTALL_URL.format(slug=slug, org_id=org.org_id)
            self.echo(f"install the App on {org.login} for All repositories: {url}")
            self.open(url)
            if self.web is not None:
                self.web.install_app(url)
            self.echo(
                f"waiting for the installation (up to {self.options.wait_timeout:g} s; Ctrl-C stops, setup can "
                "be run again)"
            )
            try:
                installation = wait_until(
                    lambda: app.installation_for_org(org.login),
                    timeout=self.options.wait_timeout,
                    interval=self.options.poll_interval,
                    what=f"installation of the App on {org.login}",
                    sleep=self.io.sleep,
                    clock=self.io.clock,
                )
            except WaitTimeoutError:
                self.warn("not installed yet: install it, then run setup (or bootstrap) again")
                return
        problems = installation_problems(installation)
        if problems:
            self.warn(
                f"installation {installation.get('id')}: {'; '.join(problems)} (accept the requested "
                "permissions and select All repositories)"
            )
        else:
            self.done(f"installation {installation.get('id')} ready")

    # --- end ------------------------------------------------------------------------------------------------------
    def finish(self, org: OrgInfo, app: str) -> None:
        """Offer bootstrap (then the App again when it waited for the marker) and doctor, then the manual steps."""
        self.warn_shadowed()
        command = f"otterdog-acceptance bootstrap --target {self.instance} --apply"
        if self.bootstrap is not None and self.ask(
            f"Run `{command}` now? (safety marker after you type the org login, invitations, repositories, baseline)",
            True,
        ):
            self.bootstrap(self.instance)
            if app == APP_NEEDS_MARKER and self.ask("The marker is set now: create the GitHub App?", True):
                self.section("GitHub App")
                app = self.app_step(org, confirmed=True)
                if app == APP_READY and self.ask(
                    "Run bootstrap again for the App checks (otterdog.json, delivery probe)?", True
                ):
                    self.bootstrap(self.instance)
        if self.doctor is not None and self.ask(
            f"Run `otterdog-acceptance doctor --target {self.instance}` now?", True
        ):
            self.doctor(self.instance)
        self.list_shard_instance()
        self.section(f"What stays manual for {self.instance}")
        for line in self.next_steps(org, app):
            self.echo(line)

    def warn_shadowed(self) -> None:
        """Exported E2E_* variables override env files in every session: name those that differ from this file."""
        shadowed = sorted(
            key for key, value in self.values.items() if key in self.environ and self.environ[key] != value
        )
        if shadowed:
            self.warn(f"exported in this shell, these override {self.env_path}: {', '.join(shadowed)}")

    def next_steps(self, org: OrgInfo, app: str) -> Iterable[str]:
        """What stays manual (docs/onboarding.md)."""
        lines = []
        if app == APP_NEEDS_MARKER:
            lines.append(f"- the GitHub App: run setup again once bootstrap added the safety marker to {org.login}")
        members = [
            self.values[ROLE_TOKENS[role].login_env]
            for role in ("author", "approver")
            if self.values.get(ROLE_TOKENS[role].login_env)
        ]
        if members:
            lines.append(
                f"- logged in as {', '.join(members)}: accept the invitation (https://github.com/orgs/{org.login}/"
                f"invitation) and make the membership public (https://github.com/orgs/{org.login}/people)"
            )
        if any(self.values.get(ROLE_TOKENS[role].type_env) == FINE_GRAINED for role in MEMBER_ROLES):
            lines.append(
                "- approve the members' fine-grained token requests: "
                f"https://github.com/organizations/{org.login}/settings/personal-access-token-requests"
            )
        if self.store and self.store.startswith("vault:"):
            mount = self.values.get("E2E_VAULT_MOUNT") or self.environ.get("E2E_VAULT_MOUNT") or "secret"
            lines.append(
                "- Vault: one JWT role per GitHub environment, bound to it, with its read-only policy; then set "
                "E2E_VAULT_ROLE (E2E_VAULT_ROLE_UNTRUSTED, E2E_VAULT_ROLE_WEBUI) in the env file (docs/security.md):"
            )
            for name, policy in vault_policies(self.store, self.instance, mount).items():
                lines.append(f"  policy {name}:")
                lines.extend(f"    {line}" for line in policy.splitlines())
        lines.append(f"- CI environments, variables and secrets: otterdog-acceptance ci-sync --target {self.instance}")
        return lines
