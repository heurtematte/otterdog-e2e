"""``otterdog-e2e setup``: the interactive onboarding of one test organization instance (docs/onboarding.md).

Every validated answer is written to the instance env file at once (``envfile.update_env_file``), so an interrupted
run keeps its progress and the next run continues where it stopped:

1. org: the login (--org, E2E_ORG, else asked) -> ``GET /orgs/{org}`` (exact-case login, id pinned in E2E_ORG_ID); a
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
   checked before any membership (bootstrap invites and publicizes later);
3. web-UI login of the admin account (optional): password and TOTP setup key (hidden, settings.normalize_totp_seed);
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
resolved before its checks (secret).
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from otterdog_e2e.context import in_ci, installation_problems
from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.onboard.envfile import (
    check_instance_name,
    instance_app_dir,
    instance_env_path,
    known_instances,
    read_env_file,
    update_env_file,
)
from otterdog_e2e.onboard.tokens import (
    DEFAULT_EXPIRES_IN,
    ROLE_TOKENS,
    ROLES,
    missing_scopes,
    token_steps,
    token_url,
)
from otterdog_e2e.redact import REDACTOR, SECRET_KEY_RE
from otterdog_e2e.safety import CLASSIC, FINE_GRAINED, MEMBER_ROLES, SafetyError, check_org_allowed
from otterdog_e2e.settings import (
    DEFAULT_WEB_ENV,
    LOGIN_RE,
    TargetError,
    WebCredentialsError,
    normalize_totp_seed,
)
from otterdog_e2e.vaults import VaultError, is_reference, resolve
from otterdog_e2e.waiting import WaitTimeoutError, wait_until

if TYPE_CHECKING:
    from otterdog_e2e.github.app import AppAuth
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import AppCredentials, HarnessSettings, Target

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
ENV_FILE_HEADER = (
    "otterdog-e2e instance {instance}: written by `otterdog-e2e setup` (re-run it to change or rotate a value).\n"
    "Holds tokens and passwords: keep it private (mode 0600), never commit or share it."
)


class SetupError(RuntimeError):
    """The setup cannot go on (the message never contains a secret); what was validated so far stays written."""


class TokenRejectedError(ValueError):
    """A token failed a check (redacted reason); it is never written."""


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
    """Read-only GitHubHttp of one identity (imported here: tests patch otterdog_e2e.github.http.GitHubHttp)."""
    from otterdog_e2e.github.http import GitHubHttp

    return GitHubHttp(token, read_only=True, identity=identity)


def _default_write_http(token: str, verified: VerifiedOrg) -> GitHubHttp:
    """GitHubHttp of the admin token, write-scoped to the verified org (the invitations of fine-grained roles)."""
    from otterdog_e2e.github.http import GitHubHttp

    return GitHubHttp(token, write_scope=verified, identity="admin")


def _default_app_auth(credentials: AppCredentials) -> AppAuth:
    """AppAuth of the App credentials (JWT reads only)."""
    from otterdog_e2e.github.app import AppAuth

    return AppAuth(credentials)


def _default_exchange(code: str, *, out_dir: Path) -> Mapping[str, Any]:
    """appmanifest.exchange_code: the App key and webhook secret written to 0600 files of ``out_dir``."""
    from otterdog_e2e.appmanifest import exchange_code

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
    ) -> None:
        """Bind the flow; nothing is read or asked before run(). ``run_manifest(target, webhook_url)`` returns the
        manifest code (None: no App step), ``bootstrap`` / ``doctor`` take the instance name (None: not offered),
        ``write_http(admin_token, verified)`` is the only writing client (invitations)."""
        unknown = sorted(set(options.rotate) - set(ROTATABLE))
        if unknown:
            raise SetupError(f"--rotate: unknown value(s) {', '.join(unknown)} (expected {', '.join(ROTATABLE)})")
        self.options = options
        self.io = io
        self.environ = environ
        self.settings = settings
        self.http = http
        self.write_http = write_http
        self.run_manifest = run_manifest
        self.exchange = exchange
        self.app_auth = app_auth
        self.bootstrap = bootstrap
        self.doctor = doctor
        self.instance = check_instance_name(options.instance)
        self.env_path = instance_env_path(self.instance, environ)
        self.values: dict[str, str] = {}
        self.clients: dict[str, GitHubHttp] = {}
        self.profile: str | None = None
        self.invited: dict[str, str] = {}  # role -> login invited by THIS run (PUT /orgs/{org}/memberships/{login})

    # --- plumbing -----------------------------------------------------------------------------------------------
    def echo(self, text: str = "") -> None:
        """Print redacted text."""
        self.io.echo(REDACTOR(text))

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
            self.echo(f"  saved {', '.join(changed)} in {target}")
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
        from otterdog_e2e.settings import load_target

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
                "setup is interactive and refused when CI is set: run it on your machine, then `otterdog-e2e ci-sync`"
            )
        self.values = read_env_file(self.env_path)
        REDACTOR.add(
            *(value for key, value in self.values.items() if SECRET_KEY_RE.search(key) and not is_reference(value))
        )
        self.echo(f"otterdog-e2e setup of instance {self.instance}: {self.env_path}")
        self.copy_from()
        org = self.org_step()
        self.role_step("admin", org)
        self.profile_step(org)
        for role in ROLES:
            if role != "admin":
                self.role_step(role, org)
        self.web_step()
        app = self.app_step(org)
        self.finish(org, app)

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
        """The live org (created by the operator when missing); E2E_ORG and E2E_ORG_ID written."""
        pinned = self.values.get("E2E_ORG")
        login = (self.options.org or pinned or self.io.prompt("Login of the dedicated test organization", None)).strip()
        if pinned and login.lower() != pinned.lower():
            raise SetupError(
                f"{self.env_path} pins the organization {pinned}: set up {login} as another instance (--target)"
            )
        if not LOGIN_RE.fullmatch(login):
            raise SetupError(f"{login!r} is not a GitHub organization login")
        check_org_allowed(login)
        anonymous = self.http(None, "anonymous")
        while (data := anonymous.get(f"/orgs/{login}", allow_404=True)) is None:
            for line in self.org_creation_help(login):
                self.echo(line)
            if not self.io.confirm(f"Check {login} again?", True):
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
        self.echo(f"organization {live} (id {org_id})")
        self.write({"E2E_ORG": live, "E2E_ORG_ID": str(org_id)})
        return OrgInfo(live, org_id)

    def org_creation_help(self, login: str) -> list[str]:
        """How to create the missing org (GitHub has no API for Free/Team orgs), after the plan of the profile
        (--profile, E2E_PROFILE, else the profile named like the instance; a profile's literal expected_plan); while
        no plan is known: the Free URL and the Enterprise Cloud note, and the hint to pass --profile."""
        profile = self.options.profile or self.values.get("E2E_PROFILE") or self.instance
        plan = profile if profile in (*ORG_CREATION_URLS, "enterprise") else self.expected_plan(profile)
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

    # --- tokens -------------------------------------------------------------------------------------------------
    def role_step(self, role: str, org: OrgInfo) -> None:
        """One role: keep the stored valid token (unless rotated), else prompt for a new one (optional roles may be
        skipped); an unusable stored token may be removed."""
        spec = ROLE_TOKENS[role]
        stored = self.values.get(spec.token_env)
        rotate = role in self.options.rotate
        if stored and not rotate and self.keep_stored(role, stored, org):
            return
        # the oracle is usually left out (the admin token serves as oracle): only that question defaults to no
        if (
            not stored
            and not spec.required
            and not self.io.confirm(f"Set up the {role} token? ({spec.purpose})", role != "oracle")
        ):
            self.echo(f"{role}: skipped (run setup again to add it)")
            return
        if self.prompt_token(role, org, stored=stored if rotate else None):
            return
        if stored and rotate and self.keep_stored(role, stored, org):
            return
        if spec.required:
            raise SetupError(f"{role}: a valid token is required")
        if stored and self.io.confirm(f"Remove the unusable {spec.token_env} from {self.env_path}?", True):
            self.write({spec.token_env: None, spec.login_env: None, spec.type_env: None})

    def keep_stored(self, role: str, stored: str, org: OrgInfo) -> bool:
        """Validate the stored token (a vault reference resolved first); True (and its login/type refreshed) when it
        passes."""
        spec = ROLE_TOKENS[role]
        try:
            token = self.secret(spec.token_env) or ""
            checked = self.check_token(role, token, org)
        except (TokenRejectedError, SetupError) as exc:
            self.echo(f"{role}: the stored {spec.token_env} is not usable: {exc}")
            return False
        self.echo(
            f"{role}: keeping the token of {checked.login} ({TOKEN_KIND_LABELS[checked.kind]}, {_expiry(checked)})"
        )
        self.record(role, token, checked, org, written=stored)
        return True

    def secret(self, name: str) -> str | None:
        """The stored value of a secret variable, a vault reference resolved (SetupError when it cannot be read)."""
        value = self.values.get(name)
        if not value or not is_reference(value):
            return value
        try:
            return resolve(value, {**self.environ, **self.values}).strip()
        except VaultError as exc:
            raise SetupError(f"{name}: {exc}") from None

    def typed_secret(self, label: str, answer: str) -> tuple[str, str | None]:
        """(value, reference) of a typed secret: a vault reference resolved (SetupError when it cannot be read)."""
        if not is_reference(answer):
            return answer, None
        try:
            return resolve(answer, {**self.environ, **self.values}).strip(), answer
        except VaultError as exc:
            raise SetupError(f"{label}: {exc}") from None

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
            self.echo(f"{role}: skipped")
            return None
        admin = self.clients["admin"]
        path = f"/orgs/{org.login}/memberships/{login}"
        membership = admin.get(path, allow_404=True)
        if membership is None:
            self.invite(role, login, org)
        elif membership.get("role") != FINE_GRAINED_INVITES[role]:
            note = "; doctor requires the oracle to be an owner" if role == "oracle" else ""
            self.echo(
                f"{role}: {login} is a member with role {membership.get('role')!r} already (left unchanged{note})"
            )
        self.write({spec.login_env: login, spec.type_env: FINE_GRAINED})
        if (membership or {}).get("state") == "active":
            return login
        invitation = INVITATION_URL.format(org=org.login)
        self.echo(
            f"{role}: signed in as {login}, accept the invitation: {invitation} (waiting up to "
            f"{self.options.wait_timeout:g} s; Ctrl-C stops, setup can be run again)"
        )
        self.open(invitation)
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
            self.echo(
                f"{role}: {login} has not accepted the invitation yet: run setup again once it did (a mistyped "
                f"login: cancel its invitation at {PEOPLE_URL.format(org=org.login)})"
            )
            return None
        self.echo(f"{role}: {login} is an active member of {org.login}")
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
                self.echo(f"{role}: {exc}")
                continue
            return str(user.get("login") or login)
        raise SetupError(f"{role}: no valid login after {MAX_ATTEMPTS} attempts")

    def admin_writer(self) -> GitHubHttp:
        """The admin token's client, write-scoped to the org verified first (pin and plan; the marker is
        bootstrap's): the only writing client of setup (invitations and their cancellation)."""
        from otterdog_e2e import safety

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
        self.echo(f"{role}: invited {login} to {org.login} as {'an owner' if org_role == 'admin' else 'a member'}")

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
            self.echo(f"{role}: cannot cancel the invitation of {login} ({exc.status}): cancel it at {people}")
            return
        if state == "pending":
            self.invited.pop(role, None)
            self.echo(f"{role}: cancelled the pending invitation of {login} to {org.login} (created by this run)")
            if not self.values.get(spec.token_env):
                self.write({spec.login_env: None})
        elif state == "active":
            self.echo(
                f"{role}: warning: {login} accepted the invitation of this run and stays {what} of {org.login}: if it "
                f"is not the {role} machine account, remove it: {people}"
            )

    def prompt_token(self, role: str, org: OrgInfo, *, stored: str | None) -> bool:
        """Print the prefilled URL and read tokens until one passes (True, written) or the operator enters nothing
        (False); SetupError after MAX_ATTEMPTS refused tokens."""
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
        self.echo(f"{role}: create a {TOKEN_KIND_LABELS[kind]} signed in as the {role} machine account:")
        self.echo(f"  {url}")
        for step in token_steps(role, kind, org.login):
            self.echo(f"  - {step}")
        other = [item for item in spec.kinds if item != kind]
        if other:
            self.echo(f"  (a {TOKEN_KIND_LABELS[other[0]]} works too: --token-type {other[0]})")
        if stored:
            self.echo("  rotating: regenerating the existing token in the account's settings works too")
        self.open(url)
        empty = "keep the stored one" if stored else ("try again" if spec.required else "skip")
        other_account = False  # a token of another account than the invited one was refused
        for _ in range(MAX_ATTEMPTS):
            token = self.io.secret_prompt(f"{role} token or vault reference (input hidden; empty: {empty})").strip()
            if not token:
                if spec.required and not stored:
                    self.echo(f"{role}: the token is required")
                    continue
                self.echo(f"{role}: {'unchanged' if stored else 'skipped'}")
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
            except (TokenRejectedError, SetupError) as exc:
                self.echo(f"{role}: token refused, nothing written: {exc}")
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
            self.echo("oracle: same token as the admin, which is the oracle's fallback anyway: nothing stored")
            self.write({spec.token_env: None, spec.login_env: None, spec.type_env: None})
            return
        previous = self.values.get(spec.login_env)
        if previous and previous.lower() != checked.login.lower():
            self.echo(f"{role}: the login changes from {previous} to {checked.login}")
        if (written or token) != self.values.get(spec.token_env):
            self.echo(
                f"{role}: token of {checked.login} accepted ({TOKEN_KIND_LABELS[checked.kind]}, {_expiry(checked)})"
            )
        self.write({spec.login_env: checked.login, spec.token_env: written or token, spec.type_env: checked.kind})

    def check_token(self, role: str, token: str, org: OrgInfo) -> CheckedToken:
        """Every check of a role's token (TokenRejectedError with the reason): shape, not another role's token, GET /user,
        kind, classic scopes, isolation (safety.check_identity_isolation, with the shared org ids accepted for this
        token in memory only: shared_org_offer), owner membership. Nothing is written here (record does)."""
        from otterdog_e2e import safety

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
            f"oracle: {login} is not an owner of {org.login} yet (membership {state or 'none'}): bootstrap invites "
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
        from otterdog_e2e.settings import load_target

        path = instance_env_path(name, self.environ)
        values = read_env_file(path)
        admin = ROLE_TOKENS["admin"]
        if not (values.get(admin.login_env) and values.get(admin.token_env)):
            return f"{path} holds no validated admin token (complete `otterdog-e2e setup --target {name}` first)"
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
                f"test org (run `otterdog-e2e bootstrap --target {name} --apply` first)"
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
        return validated if self.io.confirm(question, False) else {}

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
            profile = self.options.profile or stored or (plan if plan in available else "")
        while profile not in available:
            if profile:
                self.echo(f"no profile {profile!r} (targets/<profile>.yaml): one of {', '.join(available)}")
            profile = self.io.prompt(f"Profile of {org.login} (plan {plan})", None).strip()
        expected = self.expected_plan(profile)
        if expected and expected != plan:
            raise SetupError(
                f"profile {profile} expects plan {expected}, {org.login} is on plan {plan}: choose another --profile"
            )
        self.profile = profile
        self.echo(f"profile {profile} (targets/{profile}.yaml), plan {plan}")
        self.write({"E2E_PROFILE": profile})

    # --- web-UI login -------------------------------------------------------------------------------------------
    def web_step(self) -> None:
        """Optional web-UI login of the admin account: password and normalized TOTP seed (hidden prompts)."""
        password_env, seed_env = DEFAULT_WEB_ENV["password_env"], DEFAULT_WEB_ENV["totp_seed_env"]
        stored_seed = self.values.get(seed_env)
        if self.values.get(password_env) and stored_seed and WEB_ROTATION not in self.options.rotate:
            try:
                self.secret(password_env)
                normalize_totp_seed(self.secret(seed_env) or "", where=seed_env)
            except (WebCredentialsError, SetupError) as exc:
                self.echo(f"web-UI login: {exc}")
            else:
                self.echo(f"web-UI login: keeping {password_env} and {seed_env}")
                return
        elif WEB_ROTATION not in self.options.rotate and not self.io.confirm(
            "Set up the web-UI login of the admin account? (optional: the web-UI tier logs in to github.com as the "
            "admin, trusted SUTs only)",
            False,
        ):
            self.echo("web-UI login: skipped")
            return
        admin = self.values.get(ROLE_TOKENS["admin"].login_env, "the admin account")
        self.echo(
            f"web-UI login of {admin}: two-factor authentication with an authenticator app (TOTP) only; its setup key "
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
            self.echo("web-UI login: skipped")
            return
        seed = self.read_seed(seed_env)
        if seed is None:
            self.echo("web-UI login: skipped")
            return
        self.write({password_env: password, seed_env: seed})

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
            self.echo(f"GitHub App: keeping {self.values.get('E2E_APP_SLUG') or '?'} (id {app_id})")
            self.wait_installation(org)
            return APP_READY
        if self.run_manifest is None:
            self.echo("GitHub App: the manifest flow is not available here (otterdog-e2e app-manifest)")
            return APP_SKIPPED
        if not confirmed and not self.io.confirm(
            "Create the GitHub App of the webapp and webhooks tiers? (optional: one browser click)", True
        ):
            self.echo("GitHub App: skipped (run setup again to add it)")
            return APP_SKIPPED
        target = self.target()
        description = str((self.clients["admin"].get(f"/orgs/{org.login}") or {}).get("description") or "")
        if target.marker not in description:
            self.echo(
                f"GitHub App: the description of {org.login} lacks the safety marker {target.marker!r} that proves a "
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
        self.echo(f"GitHub App {slug} (id {result['id']}) created; private key {result['pem_path']} (0600)")
        self.write(
            {
                "E2E_APP_ID": str(result["id"]),
                "E2E_APP_SLUG": slug,
                "E2E_APP_PRIVATE_KEY_FILE": str(result["pem_path"]),
                "E2E_APP_WEBHOOK_SECRET": secret,
                "E2E_APP_PRIVATE_KEY": None,  # an inline key of a former App would win over the new key file
            }
        )
        if result.get("secret_generated"):
            self.echo(
                "GitHub returned no webhook secret: a random one was generated; set it as the App's webhook secret: "
                f"https://github.com/organizations/{org.login}/settings/apps/{slug}"
            )
        self.wait_installation(org)
        return APP_READY

    def webhook_url(self) -> str:
        """The App's webhook sink (--webhook-url, the stored one, else asked): https, not loopback; written."""
        from otterdog_e2e.appmanifest import check_webhook_url

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
        from otterdog_e2e.safety import verify_app
        from otterdog_e2e.settings import resolve_app_credentials

        target = self.target()
        try:
            credentials = resolve_app_credentials(target, self.values)
        except TargetError as exc:
            self.echo(f"GitHub App: {exc}")
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
                f"`otterdog-e2e setup --target {self.instance} --rotate app`"
            ) from None
        installation = app.installation_for_org(org.login)
        if installation is None:
            slug = credentials.slug or self.values.get("E2E_APP_SLUG") or isolation.slug
            url = APP_INSTALL_URL.format(slug=slug, org_id=org.org_id)
            self.echo(f"install the App on {org.login} for All repositories: {url}")
            self.open(url)
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
                self.echo("GitHub App: not installed yet: install it, then run setup (or bootstrap) again")
                return
        problems = installation_problems(installation)
        if problems:
            self.echo(
                f"GitHub App installation {installation.get('id')}: {'; '.join(problems)} (accept the requested "
                "permissions and select All repositories)"
            )
        else:
            self.echo(f"GitHub App installation {installation.get('id')} ready")

    # --- end ------------------------------------------------------------------------------------------------------
    def finish(self, org: OrgInfo, app: str) -> None:
        """Offer bootstrap (then the App again when it waited for the marker) and doctor, then the manual steps."""
        self.warn_shadowed()
        command = f"otterdog-e2e bootstrap --target {self.instance} --apply"
        if self.bootstrap is not None and self.io.confirm(
            f"Run `{command}` now? (safety marker after you type the org login, invitations, repositories, baseline)",
            True,
        ):
            self.bootstrap(self.instance)
            if app == APP_NEEDS_MARKER and self.io.confirm("The marker is set now: create the GitHub App?", True):
                app = self.app_step(org, confirmed=True)
                if app == APP_READY and self.io.confirm(
                    "Run bootstrap again for the App checks (otterdog.json, delivery probe)?", True
                ):
                    self.bootstrap(self.instance)
        if self.doctor is not None and self.io.confirm(
            f"Run `otterdog-e2e doctor --target {self.instance}` now?", True
        ):
            self.doctor(self.instance)
        for line in self.next_steps(org, app):
            self.echo(line)

    def warn_shadowed(self) -> None:
        """Exported E2E_* variables override env files in every session: name those that differ from this file."""
        shadowed = sorted(
            key for key, value in self.values.items() if key in self.environ and self.environ[key] != value
        )
        if shadowed:
            self.echo(f"warning: exported in this shell, these override {self.env_path}: {', '.join(shadowed)}")

    def next_steps(self, org: OrgInfo, app: str) -> Iterable[str]:
        """What stays manual (docs/onboarding.md)."""
        lines = [f"instance {self.instance} ({self.env_path}): what stays manual"]
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
        lines.append(f"- CI environments, variables and secrets: otterdog-e2e ci-sync --target {self.instance}")
        return lines
