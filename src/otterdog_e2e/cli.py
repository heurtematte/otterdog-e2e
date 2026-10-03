"""``otterdog-e2e`` command line (SPEC 16): doctor, bootstrap, sut, run, pr, relay, janitor, report, scrub-artifacts,
cache prune and app-manifest. Exit codes: pytest's for run/pr; budget overruns never fail.

Every command builds an E2EContext (the composition root shared with the pytest plugin); collaborators are imported
lazily so that ``--help`` stays fast. Errors are reported as redacted one-line messages (exit 1). ``run`` and ``pr``
call ``pytest.main`` in-process: the plugin's safety model (verify_target, lease, gating, redaction) applies unchanged.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import hmac
import http.server
import ipaddress
import json
import logging
import os
import re
import secrets
import shlex
import shutil
import sys
import time
import urllib.parse
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import click

from otterdog_e2e.context import (
    AUTO_BASE,
    INVOCATION_ENV,
    ContextError,
    E2EContext,
    E2EOptions,
    describe_error,
    in_ci,
    installation_problems,
    parse_duration,
    parse_time,
    split_csv,
)
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.differential import PrManifest
    from otterdog_e2e.github.app import AppAuth
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.github.janitor import JanitorItem
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.redact import Redactor
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import HarnessSettings, Target
    from otterdog_e2e.sut.spec import SutSpec
    from otterdog_e2e.sut.template import TemplateRef
    from otterdog_e2e.webhooks.relay import DeliveryRelay, RelayedDelivery

logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable[..., Any])

# pass-through pytest args starting with these are rejected by `run` and `pr` (they could override the SUT or plugins,
# or print secrets); "@" is pytest's argument-file prefix
REJECTED_PASSTHROUGH = (
    "--e2e-",
    "-p",
    "-c",
    "-o",
    "--rootdir",
    "--confcutdir",
    "--basetemp",
    "--pyargs",
    "--showlocals",
    "--override-ini",
    "--config-file",
    "-l",
    "@",
)
_LONG_REJECTED = tuple(prefix for prefix in REJECTED_PASSTHROUGH if prefix.startswith("--"))
_SHORT_REJECTED = frozenset(prefix[1] for prefix in REJECTED_PASSTHROUGH if len(prefix) == 2 and prefix[0] == "-")
_SHORT_WITH_VALUE = frozenset("kmrcopW")  # pytest short options taking a value: the rest of the cluster is that value
SUITES = ("unit", "offline", "cli", "webhooks", "webapp", "enterprise", "differential", "web_ui")
DEFAULT_SUITES = ("offline", "cli", "webhooks", "webapp", "enterprise")
PR_LIVE_SUITES = ("cli", "webhooks", "webapp", "enterprise")
WEB_UI_SUITE = "web_ui"  # tests/web_ui: a default suite only with --allow-web-ui (docs/web-ui-testing.md)
# otterdog's own check-token-permissions requirement for the admin PAT
REQUIRED_ADMIN_SCOPES = frozenset({"admin:org", "admin:org_hook", "delete_repo", "repo", "workflow"})
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RUN_ID_ARG_RE = re.compile(r"^[0-9a-z]{6}[0-9a-f]{2}$")
DELIVERY_PROBE_TIMEOUT = 300.0  # like every delivery wait of the harness: GitHub lists deliveries minutes late (F6)
DELIVERY_FRESHNESS = timedelta(hours=72)
# files of a PR that run code at build time or change templates: flagged in the classify step summary
RISKY_PATHS = ("pyproject.toml", "poetry.lock", "docker/*", "*Dockerfile*", "examples/template/*")
PRUNABLE_CACHE_DIRS = ("run", "build", "src", "http-cache")
CONFIG_HOME = Path("~/.config/otterdog-e2e")
MANIFEST_TIMEOUT = 600.0
OK, WARN, FAIL = "OK", "WARN", "FAIL"


# --- shared helpers -------------------------------------------------------------------------------------------------
def check_passthrough(args: Sequence[str]) -> None:
    """click.UsageError when a pass-through argument starts with one of REJECTED_PASSTHROUGH."""
    for arg in args:
        if _rejected(arg):
            raise click.UsageError(
                f"pass-through argument {arg!r} is not allowed (it could change the SUT, load plugins or print secrets)"
            )


def _rejected(arg: str) -> bool:
    """True for @files, rejected long options and short-option clusters containing -p/-c/-o/-l."""
    if arg.startswith("@"):
        return True
    if arg.startswith("--"):
        name = arg.split("=", 1)[0]
        return any(name.startswith(prefix) if prefix.endswith("-") else name == prefix for prefix in _LONG_REJECTED)
    if not arg.startswith("-") or len(arg) < 2:
        return False
    for char in arg[1:]:
        if char in _SHORT_REJECTED:
            return True
        if char in _SHORT_WITH_VALUE:
            return False
    return False


def _handled(func: F) -> F:
    """Report harness errors as a redacted one-line click error (exit 1) instead of a traceback."""

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Call the command, converting unexpected exceptions."""
        try:
            return func(*args, **kwargs)
        except (click.ClickException, click.exceptions.Exit, click.Abort):
            raise
        except Exception as exc:
            logger.debug("command failed", exc_info=True)
            raise click.ClickException(describe_error(exc)) from exc

    return wrapper  # type: ignore[return-value]


def _context(
    target: str | None = None, *, make_dirs: bool = True, artifacts: bool = True, **options: Any
) -> E2EContext:
    """A fresh E2EContext for one command."""
    return E2EContext.create(E2EOptions(target=target, **options), make_dirs=make_dirs, artifacts=artifacts)


@contextlib.contextmanager
def _session(target: str | None = None, *, artifacts: bool = True, **options: Any) -> Iterator[E2EContext]:
    """E2EContext with process setup (scratch HOME, log redaction); always closed (lease release, scrub)."""
    context = _context(target, artifacts=artifacts, **options)
    context.start_session(argv=[REDACTOR(arg) for arg in sys.argv])
    try:
        yield context
    finally:
        context.close()


def _echo(text: str = "", *, err: bool = False) -> None:
    """click.echo of redacted text."""
    click.echo(REDACTOR(text), err=err)


def _echo_json(data: Any) -> None:
    """Pretty JSON on stdout (redacted)."""
    _echo(json.dumps(data, indent=2, sort_keys=True, default=str))


def _settings() -> HarnessSettings:
    """HarnessSettings from the environment."""
    from otterdog_e2e.settings import harness_settings

    return harness_settings(os.environ)


def _declared_login(target: Target, name: str) -> str | None:
    """Login declared for an identity in the target (F8), None when absent."""
    spec = target.identities.get(name)
    return spec.login if spec is not None and spec.login else None


def _is_loopback_url(url: str) -> bool:
    """True when the URL's host is localhost or a loopback address."""
    host = urllib.parse.urlsplit(url).hostname or ""
    if host in ("localhost", "localhost.localdomain"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _public_member(context: E2EContext, org: str, login: str) -> bool:
    """GET /orgs/{org}/public_members/{login}: 204 public, 404 private or not a member."""
    response = context.http("admin").request(
        "GET", f"/orgs/{org}/public_members/{login}", expected=(204,), allow=(404,)
    )
    return response.status_code == 204


@click.group()
@click.version_option(package_name="otterdog-e2e", prog_name="otterdog-e2e")
@click.option("-v", "--verbose", count=True, help="log more (-v info, -vv debug)")
def main(verbose: int) -> None:
    """End-to-end test harness for otterdog."""
    from otterdog_e2e import redact

    redact.install_logging_filter()
    if verbose:
        logging.basicConfig(level=logging.DEBUG if verbose > 1 else logging.INFO, format="%(levelname)s %(message)s")


# --- doctor ---------------------------------------------------------------------------------------------------------
@dataclass
class CheckRow:
    """One doctor check: OK, WARN or FAIL with details and a remediation hint."""

    name: str
    status: str
    detail: str = ""
    remediation: str = ""


class Doctor:
    """Read-only checks of SPEC 16 for one target (never mutates, never takes the lease)."""

    def __init__(self, context: E2EContext) -> None:
        """Bind the checks to a context (not verified yet)."""
        self.ctx = context
        self.rows: list[CheckRow] = []

    def add(self, name: str, status: str, detail: str = "", remediation: str = "") -> None:
        """Record one check result (redacted)."""
        self.rows.append(CheckRow(name, status, REDACTOR(detail), REDACTOR(remediation)))

    def guarded(self, name: str, check: Callable[[], Any], remediation: str = "") -> Any:
        """Run a check; an unexpected error becomes a FAIL row (None returned)."""
        try:
            return check()
        except Exception as exc:  # noqa: BLE001 - every failing check is reported, the doctor goes on
            self.add(name, FAIL, describe_error(exc), remediation)
            return None

    def run(self) -> list[CheckRow]:
        """Every check, in dependency order (GitHub checks need the admin identity and a matching org)."""
        target = self.check_target()
        if target is None:
            return self.rows
        self.check_env(target)
        web = self.guarded("web:credentials", functools.partial(self.check_web, target))
        if "admin" in self.ctx.identities and self.check_identities(target):
            verified = self.check_org(target)
            if verified is not None:
                for name, check in (
                    ("memberships", self.check_memberships),
                    ("teams", self.check_teams),
                    ("repos", self.check_repos),
                    ("unmanaged", self.check_unmanaged),
                    ("app", self.check_app),
                ):
                    self.guarded(name, functools.partial(check, target))
                if web:
                    self.guarded("web:2fa", self.check_web_2fa)
        self.check_template(target)
        self.check_tools()
        return self.rows

    @property
    def failed(self) -> bool:
        """True when at least one check failed."""
        return any(row.status == FAIL for row in self.rows)

    def check_target(self) -> Target | None:
        """The target file loads (env files applied)."""
        try:
            target = self.ctx.load_target()
        except Exception as exc:  # noqa: BLE001 - reported as the first FAIL
            hint = (
                f"check targets/<name>.yaml and its env vars (export them or write {CONFIG_HOME}/<target>.env,"
                " .env.e2e.<target> or .env.e2e)"
            )
            self.add("target", FAIL, describe_error(exc), hint)
            return None
        self.add(
            "target", OK, f"{target.source_path.name}: org {target.org} (id {target.org_id}), {target.expected_plan}"
        )
        return target

    def check_env(self, target: Target) -> None:
        """Admin token present; declared optional identities have tokens; App env vars when the target has an App."""
        admin = target.identities.get("admin")
        if "admin" in self.ctx.identities:
            self.add("env:admin", OK, f"{admin.token_env if admin else 'admin token'} set")
        else:
            env = admin.token_env if admin else "E2E_ADMIN_TOKEN"
            self.add("env:admin", FAIL, f"{env} is not set", f"export it or add it to {CONFIG_HOME}/{target.name}.env")
        for name in ("author", "approver", "outsider", "config_reader"):
            spec = target.identities.get(name)
            if spec is not None and spec.login and name not in self.ctx.identities:
                self.add(f"env:{name}", WARN, f"{spec.token_env} is not set: tests needing {name} are skipped")
        if target.app is not None:
            credentials = self.guarded("env:app", self.ctx.app_credentials, "check the App key file / env vars")
            if credentials is None and not any(row.name == "env:app" for row in self.rows):
                self.add("env:app", WARN, f"{target.app.id_env} not set: webapp and webhooks tiers are skipped")

    def check_identities(self, target: Target) -> bool:
        """GET /user == declared login, isolation (SPEC 5.1) and scope rules; True when admin is usable."""
        admin_token = self.ctx.identities["admin"].token
        admin_ok = False
        for name, identity in sorted(self.ctx.identities.items()):
            if name == "oracle" and identity.token == admin_token:
                continue  # the oracle falls back to the admin identity
            ok = bool(self.guarded(f"identity:{name}", functools.partial(self._identity, target, name)))
            admin_ok = admin_ok or (name == "admin" and ok)
        return admin_ok

    def _identity(self, target: Target, name: str) -> bool:
        """Checks of one identity."""
        from otterdog_e2e.safety import SafetyError, check_identity_isolation

        http = self.ctx.http(name)
        login = str((http.get("/user") or {}).get("login") or "")
        declared = _declared_login(target, name)
        if declared and login.lower() != declared.lower():
            self.add(
                f"identity:{name}",
                FAIL,
                f"token of {login!r}, target declares {declared!r}",
                "use the token of the declared machine account",
            )
            return False
        hint = "" if declared else f"declare identities.{name}.login in the target (F8)"
        self.add(f"identity:{name}", OK if declared else WARN, f"GET /user = {login}", hint)
        try:
            check_identity_isolation(http, role=name, allowed_org_ids=target.allowed_org_ids, test_org_id=target.org_id)
        except SafetyError as exc:
            self.add(
                f"isolation:{name}", FAIL, str(exc), "use a dedicated machine account that belongs only to test orgs"
            )
            return False
        self.add(f"isolation:{name}", OK, "member of test orgs only, token scopes allowed")
        if name == "admin":
            self._admin_scopes(http)
        if name == "config_reader":
            self._config_reader(http)
        return True

    def _admin_scopes(self, http: GitHubHttp) -> None:
        """The admin PAT is classic and has otterdog's required scopes."""
        scopes = http.oauth_scopes()
        if scopes is None:
            self.add("scopes:admin", FAIL, "not a classic PAT", "create a classic PAT for the admin machine account")
            return
        missing = sorted(REQUIRED_ADMIN_SCOPES - scopes)
        if missing:
            self.add(
                "scopes:admin",
                FAIL,
                f"missing {', '.join(missing)}",
                "regenerate the PAT with " + ", ".join(sorted(REQUIRED_ADMIN_SCOPES)),
            )
        else:
            self.add("scopes:admin", OK, ", ".join(sorted(scopes)))

    def _config_reader(self, http: GitHubHttp) -> None:
        """config_reader is a fine-grained token distinct from the admin token (SEC-11)."""
        if self.ctx.identities["config_reader"].token == self.ctx.identities["admin"].token:
            self.add(
                "scopes:config_reader", FAIL, "same token as admin", "create a fine-grained public read-only token"
            )
        elif http.oauth_scopes() is not None:
            self.add(
                "scopes:config_reader", FAIL, "classic PAT", "use a fine-grained token: Public repositories (read-only)"
            )
        else:
            self.add("scopes:config_reader", OK, "fine-grained token")

    def check_org(self, target: Target) -> VerifiedOrg | None:
        """verify_target (id, login, denylist, plan) without the marker; the marker reported separately."""
        try:
            verified = self.ctx.verify(require_marker=False, check_identities=False)
        except Exception as exc:  # noqa: BLE001 - nothing org-related is checked further
            hint = "check github.org, org_id and expected_plan of the target; the admin must be an org owner"
            self.add("org", FAIL, describe_error(exc), hint)
            return None
        self.add("org", OK, f"{verified.login} (id {verified.org_id}), plan {verified.plan}")
        description = str(verified.org_json.get("description") or "")
        if target.marker in description:
            self.add("org:marker", OK, f"description contains {target.marker!r}")
        else:
            hint = f"run `otterdog-e2e bootstrap --target {target.name} --apply` (asks you to type the org login)"
            self.add("org:marker", FAIL, f"description lacks {target.marker!r}", hint)
        return verified

    def check_memberships(self, target: Target) -> None:
        """author/approver active and public members, outsider not a member, separate oracle an owner."""
        oracle = self.ctx.oracle()
        bootstrap = f"otterdog-e2e bootstrap --target {target.name} --apply"
        for name in ("author", "approver"):
            login = _declared_login(target, name)
            if not login:
                continue
            state = (oracle.membership(login) or {}).get("state")
            if state != "active":
                self.add(f"membership:{name}", FAIL, f"{login}: {state or 'not a member'}", bootstrap)
            elif not _public_member(self.ctx, target.org, login):
                self.add(f"membership:{name}", FAIL, f"{login}: membership is private", bootstrap)
            else:
                self.add(f"membership:{name}", OK, f"{login}: active, public")
        outsider = _declared_login(target, "outsider")
        if outsider:
            member = oracle.membership(outsider) is not None
            status, detail = (FAIL, "is a member of the test org") if member else (OK, "not a member")
            self.add(
                "membership:outsider",
                status,
                f"{outsider} {detail}",
                "remove the outsider from the org" if member else "",
            )
        self._check_oracle_role(target)

    def _check_oracle_role(self, target: Target) -> None:
        """A separate oracle identity must be an org owner (GH-10)."""
        oracle_identity = self.ctx.identities.get("oracle")
        login = _declared_login(target, "oracle")
        if oracle_identity is None or oracle_identity.token == self.ctx.identities["admin"].token or not login:
            return
        role = (self.ctx.oracle().membership(login) or {}).get("role")
        status = OK if role == "admin" else FAIL
        self.add(
            "membership:oracle",
            status,
            f"{login}: role {role or 'none'}",
            "" if role == "admin" else "make the oracle account an org owner",
        )

    def check_teams(self, target: Target) -> None:
        """Baseline teams exist with their declared members."""
        oracle = self.ctx.oracle()
        expected = {
            target.admin_team: _declared_login(target, "admin"),
            target.approval_team: _declared_login(target, "approver"),
            target.contributors_team: _declared_login(target, "author"),
        }
        bootstrap = f"otterdog-e2e bootstrap --target {target.name} --apply (the baseline reset creates and fills it)"
        for slug, login in expected.items():
            if oracle.team(slug) is None:
                self.add(f"team:{slug}", FAIL, "missing", bootstrap)
            elif login and login.lower() not in {member.lower() for member in oracle.team_members(slug)}:
                self.add(f"team:{slug}", WARN, f"{login} is not an active member", bootstrap)
            else:
                self.add(f"team:{slug}", OK, f"member {login}" if login else "exists")

    def check_repos(self, target: Target) -> None:
        """configs/defaults/fixture (and a fixed org config) repos exist, are public and use main."""
        from otterdog_e2e.naming import is_e2e_name

        oracle = self.ctx.oracle()
        names = [target.configs_repo, target.defaults_repo, *target.fixture_repos]
        if target.org_config_repo != "auto":
            names.append(target.org_config_repo)
        for name in dict.fromkeys(names):
            repo = oracle.repo(name)
            if repo is None:
                self.add(f"repo:{name}", FAIL, "missing", f"otterdog-e2e bootstrap --target {target.name} --apply")
                continue
            problems = []
            if repo.get("private") or repo.get("visibility", "public") != "public":
                problems.append("not public")
            if repo.get("default_branch") != "main":
                problems.append(f"default branch {repo.get('default_branch')!r} (the webapp expects main)")
            self.add(f"repo:{name}", FAIL if problems else OK, "; ".join(problems) or "public, main")
        for name in target.extra_protected_repos:
            if is_e2e_name(name) or name.startswith("e2e-"):
                self.add(
                    f"protected:{name}",
                    FAIL,
                    "looks like a run repo",
                    "rename it or drop it from extra_protected_repos",
                )

    def check_unmanaged(self, target: Target) -> None:
        """WARN for repos/teams neither protected, baseline nor run-prefixed."""
        from otterdog_e2e.naming import is_e2e_name

        oracle = self.ctx.oracle()
        protected = set(target.protected_repos(self.ctx.run_ctx))
        repos = sorted(
            r["name"] for r in oracle.repos() if r.get("name") not in protected and not is_e2e_name(r["name"])
        )
        if repos:
            self.add(
                "unmanaged:repos",
                WARN,
                ", ".join(repos[:20]),
                "never touched by the harness; list them in fixtures.extra_protected_repos",
            )
        else:
            self.add("unmanaged:repos", OK, "none")
        baseline_teams = {target.admin_team, target.approval_team, target.contributors_team}
        teams = sorted(
            t["slug"] for t in oracle.teams() if t.get("slug") not in baseline_teams and not is_e2e_name(t["slug"])
        )
        if teams:
            self.add(
                "unmanaged:teams",
                WARN,
                ", ".join(teams[:20]),
                "baseline resets refuse to delete them (SafetyError): remove them",
            )
        else:
            self.add("unmanaged:teams", OK, "none")

    def check_app(self, target: Target) -> None:
        """App isolation (safety.verify_app: owner and installations), installation preflight, hook config and recent
        deliveries."""
        from otterdog_e2e.safety import SafetyError, verify_app

        if target.app is None:
            self.add("app", WARN, "no app section in the target: webapp and webhooks tiers are skipped")
            return
        if self.ctx.app_credentials() is None:
            return
        app = self.ctx.app_auth()
        try:
            isolation = verify_app(app, target)
        except SafetyError as exc:
            self.add(
                "app:owner",
                FAIL,
                describe_error(exc),
                "create the App in the test org (otterdog-e2e app-manifest) and install it there only",
            )
        else:
            installs = ", ".join(isolation.installations) or "none"
            self.add("app:owner", OK, f"owned by {isolation.owner!r}, installed on: {installs}")
        installation = app.installation_for_org(target.org)
        if installation is None:
            self.add(
                "app:installation", FAIL, "not installed on the org", "install the App on the org for All repositories"
            )
        else:
            problems = installation_problems(installation)
            hint = "accept the requested permissions and select All repositories" if problems else ""
            self.add(
                "app:installation",
                FAIL if problems else OK,
                "; ".join(problems) or f"id {installation.get('id')}",
                hint,
            )
        self._check_hook(app)
        self._check_deliveries(app)

    def _check_hook(self, app: AppAuth) -> None:
        """Hook config: non-loopback URL, JSON content type (there is no 'active' field: GH-09)."""
        hook = app.hook_config() or {}
        url = str(hook.get("url") or "")
        if not url or _is_loopback_url(url):
            self.add(
                "app:webhook",
                FAIL,
                f"url {url!r}",
                "set a non-loopback sink URL (deliveries reach the webapp through the relay)",
            )
        elif hook.get("content_type") != "json":
            self.add(
                "app:webhook",
                FAIL,
                f"content type {hook.get('content_type')!r}",
                "set the App webhook content type to json",
            )
        else:
            self.add("app:webhook", OK, f"url {url}")

    def _check_deliveries(self, app: AppAuth) -> None:
        """WARN when the App delivered nothing in the last 72 h (inactive webhook heuristic)."""
        items, _cursor = app.list_deliveries(per_page=30)
        times = [when for when in (parse_time(item.get("delivered_at")) for item in items) if when is not None]
        newest = max(times, default=None)
        if newest is None or newest < datetime.now(UTC) - DELIVERY_FRESHNESS:
            self.add(
                "app:deliveries",
                WARN,
                "no delivery in the last 72 h",
                "check the App webhook is active and subscribed to the events",
            )
        else:
            self.add("app:deliveries", OK, f"last delivery {newest:%Y-%m-%d %H:%M} UTC")

    def check_web(self, target: Target) -> bool:
        """Web-UI tier (docs/web-ui-testing.md), never logging in: web credentials of the admin bot (complete, base32
        TOTP seed, username of the admin account), SAML SSO, the Playwright Firefox and the login gate state. True
        when web credentials are configured."""
        from otterdog_e2e.settings import TargetError, web_credential_env_names
        from otterdog_e2e.sut.cli_install import firefox_installed, playwright_browsers_path

        names = web_credential_env_names(target)
        guide = "see docs/web-ui-testing.md"
        try:
            credentials = self.ctx.web_credentials()
        except TargetError as exc:
            self.add(
                "web:credentials", FAIL, describe_error(exc), f"fix the web-UI variables of the admin bot ({guide})"
            )
            return False
        if credentials is None:
            self.add("web", OK, f"not configured ({names['password_env']}, {names['totp_seed_env']}): web-UI tier off")
            return False
        self.add(
            "web:credentials",
            OK,
            f"{names['password_env']} and {names['totp_seed_env']} set for {credentials.login}"
            + (f" (username {credentials.username})" if credentials.username != credentials.login else ""),
        )
        if target.saml_sso:
            self.add(
                "web:sso",
                WARN,
                "github.saml_sso is true: otterdog's web client cannot log in through SAML SSO",
                "the web-UI tier is skipped on this target",
            )
        builds = firefox_installed(self.ctx.settings)
        if builds:
            self.add(
                "web:browser", OK, f"Playwright {', '.join(builds)} in {playwright_browsers_path(self.ctx.settings)}"
            )
        else:
            self.add(
                "web:browser",
                WARN,
                f"no Playwright Firefox in {playwright_browsers_path(self.ctx.settings)}",
                "installed by the first web-UI session (trusted SUTs); system libraries: playwright install-deps firefox",
            )
        self._web_gate_state()
        return True

    def _web_gate_state(self) -> None:
        """The login gate of the bot: blocked (FAIL with the reason) or the time of the last web login."""
        gate = self.ctx.web_gate()
        blocked = gate.blocked()
        if blocked:
            self.add("web:gate", FAIL, blocked, f"check the bot account, then delete {gate.state_path} to unblock")
            return
        state = gate.state()
        last = state.last_end or state.last_start
        when = f"last web login {datetime.fromtimestamp(last, UTC):%Y-%m-%d %H:%M} UTC" if last else "no web login yet"
        self.add("web:gate", OK, f"{when} ({state.logins} in total, spacing {gate.spacing:g} s)")

    def check_web_2fa(self) -> None:
        """The admin bot has 2FA enabled (GET /user two_factor_authentication): otterdog types a TOTP code."""
        user = self.ctx.http("admin").get("/user") or {}
        enabled = user.get("two_factor_authentication")
        if enabled is True:
            self.add("web:2fa", OK, "two-factor authentication enabled on the admin bot")
        elif enabled is False:
            self.add(
                "web:2fa",
                FAIL,
                "two-factor authentication is disabled on the admin bot",
                "enable 2FA with an authenticator app (TOTP) and store its setup key in the TOTP seed variable",
            )
        else:
            self.add("web:2fa", WARN, "GET /user did not return two_factor_authentication (token scopes?)")

    def check_template(self, target: Target) -> None:
        """url templates should be pinned to a 40-hex commit (SEC-12)."""
        if target.template_mode != "url":
            return
        ref = (target.template_url or "").rsplit("@", 1)[-1]
        if FULL_SHA_RE.match(ref):
            self.add("template", OK, "url template pinned to a commit")
        else:
            self.add(
                "template",
                WARN,
                f"url template ref {ref!r} is not a 40-hex commit",
                "pin E2E_TEMPLATE_URL to a commit sha",
            )

    def check_tools(self) -> None:
        """docker (webapp tiers) and unshare (offline sandbox; required in CI)."""
        from otterdog_e2e import procs

        if self.ctx.docker_available():
            self.add("docker", OK, "daemon answers")
        else:
            self.add("docker", WARN, "not available: webapp tests are skipped")
        if procs.unshare_available():
            self.add("unshare", OK, "offline commands run without network")
        else:
            status = FAIL if in_ci(os.environ) else WARN
            self.add(
                "unshare",
                status,
                "user namespaces unavailable: offline commands run unsandboxed",
                "allow unprivileged user namespaces",
            )


def render_rows(rows: Sequence[CheckRow]) -> str:
    """Doctor table: STATUS, CHECK, DETAIL with a ``fix:`` line under WARN/FAIL rows."""
    width = max([len(row.name) for row in rows] + [5])
    lines = [f"{'STATUS':<6}  {'CHECK':<{width}}  DETAIL"]
    for row in rows:
        lines.append(f"{row.status:<6}  {row.name:<{width}}  {row.detail}".rstrip())
        if row.remediation and row.status != OK:
            lines.append(f"{'':<6}  {'':<{width}}  fix: {row.remediation}")
    counts = {status: sum(1 for row in rows if row.status == status) for status in (OK, WARN, FAIL)}
    lines.append(f"\n{counts[OK]} ok, {counts[WARN]} warning(s), {counts[FAIL]} failure(s)")
    return "\n".join(lines)


@main.command()
@click.option("--target", "target", required=True, help="target name or path")
@click.option("--json", "as_json", is_flag=True, help="print the checks as JSON")
@_handled
def doctor(target: str, as_json: bool) -> None:
    """Check environment, identities, isolation, org, repos, teams, App and tools of a target (exit 1 on FAIL)."""
    checks = Doctor(_context(target, make_dirs=False))
    rows = checks.run()
    if as_json:
        _echo_json({"target": target, "ok": not checks.failed, "checks": [dataclasses.asdict(row) for row in rows]})
    else:
        _echo(render_rows(rows))
    if checks.failed:
        sys.exit(1)


# --- bootstrap ------------------------------------------------------------------------------------------------------
class Bootstrap:
    """SPEC 16 bootstrap, ordered and idempotent: verify -> marker -> identities -> repos -> lease -> template ->
    baseline reset -> push baseline -> App checks and delivery probe. Without ``apply`` it only reports."""

    def __init__(
        self,
        context: E2EContext,
        *,
        apply: bool,
        confirm: Callable[[str], str],
        sleep: Callable[[float], None] = time.sleep,
        probe_timeout: float = DELIVERY_PROBE_TIMEOUT,
    ) -> None:
        """Bind the steps to a context; ``confirm(prompt)`` returns what the operator typed."""
        self.ctx = context
        self.apply = apply
        self.confirm = confirm
        self.sleep = sleep
        self.probe_timeout = probe_timeout

    def step(self, text: str) -> None:
        """Report one step."""
        _echo(f"[bootstrap] {text}")

    def run(self) -> None:
        """All steps in order (stops after the read-only ones without apply)."""
        verified = self.verify()
        self.marker(verified)
        self.identities()
        self.repos()
        if not self.apply:
            self.step("dry run: re-run with --apply to take the lease, reset the baseline, push it and probe the App")
            return
        self.ctx.acquire_lease()
        self.step("org lease acquired")
        template = self.ctx.template_for("reset")
        self.step(f"template {template.url}")
        baseline = self.baseline(template)
        self.push(baseline)
        self.app(template)
        self.step("done")

    def verify(self) -> VerifiedOrg:
        """verify_target without the marker (identities isolated)."""
        self.ctx.load_target()
        verified = self.ctx.verify(require_marker=False, check_identities=True)
        self.step(f"verified {verified.login} (id {verified.org_id}, plan {verified.plan})")
        return verified

    def marker(self, verified: VerifiedOrg) -> None:
        """Add the safety marker to the org description after typing the org login (refused in CI)."""
        target = self.ctx.require_target()
        description = str(verified.org_json.get("description") or "")
        if target.marker in description:
            self.step("safety marker present")
            return
        if not self.apply:
            self.step(f"would add the safety marker {target.marker!r} to the org description (asks for the org login)")
            return
        if in_ci(self.ctx.environ):
            raise click.ClickException(
                "refusing to write the safety marker when CI is set: run bootstrap interactively"
            )
        self._refuse_foreign_repos(target)
        prompt = f"Type the organization login ({target.org}) to add {target.marker!r} to its description"
        foreign = self._foreign_members(target)
        if foreign:
            prompt = f"members not declared as identities: {', '.join(foreign)}\n{prompt}"
        if self.confirm(prompt).strip() != target.org:
            raise click.ClickException("the typed login does not match the org: nothing changed")
        self.ctx.mutator().set_org_description(f"{target.marker} {description}".strip())
        self.ctx.verify(require_marker=True, check_identities=False)
        self.step("safety marker added")

    def _refuse_foreign_repos(self, target: Target) -> None:
        """A fresh test org has no repositories the harness does not manage (protects real orgs, SEC-02)."""
        from otterdog_e2e.naming import is_e2e_name

        protected = set(target.protected_repos(self.ctx.run_ctx))
        foreign = sorted(
            r["name"]
            for r in self.ctx.oracle().repos()
            if r.get("name") not in protected and not is_e2e_name(r["name"])
        )
        if foreign:
            raise click.ClickException(
                f"the org has repositories the harness does not manage: {', '.join(foreign[:10])}"
            )

    def _foreign_members(self, target: Target) -> list[str]:
        """Org members that are not declared identities."""
        declared = {spec.login.lower() for spec in target.identities.values() if spec.login}
        return sorted(login for login in self.ctx.oracle().members() if login.lower() not in declared)

    def identities(self) -> None:
        """author/approver: invite (admin), then accept and publicize with the identity's own token when it may (the
        allowed scopes, public_repo + read:org, usually cannot: the step is then reported as manual and bootstrap goes
        on, F4); outsider not a member."""
        target = self.ctx.require_target()
        members = [(name, login) for name in ("author", "approver") if (login := _declared_login(target, name))]
        states = {name: self._invite(target, name, login) for name, login in members}  # every invitation first
        for name, login in members:
            self._accept_and_publicize(target, name, login, states[name])
        outsider = _declared_login(target, "outsider")
        if outsider and self.ctx.oracle().membership(outsider) is not None:
            raise click.ClickException(f"the outsider {outsider} is a member of the org: remove it first")

    def _invite(self, target: Target, name: str, login: str) -> str | None:
        """Invite one identity when it is not a member (with apply); returns its membership state (None: none)."""
        state = (self.ctx.oracle().membership(login) or {}).get("state")
        if state is None and self.apply:
            self.ctx.mutator().ensure_membership(login)
            return "pending"
        return state

    def _accept_and_publicize(self, target: Target, name: str, login: str, state: str | None) -> None:
        """One identity active and public in the org; a refusal of the identity's own token (403/404: read:org cannot
        write memberships) becomes a manual step instead of stopping bootstrap."""
        from otterdog_e2e.github.http import GitHubError

        public = state == "active" and _public_member(self.ctx, target.org, login)
        if public:
            self.step(f"{name} {login}: active, public")
            return
        if not self.apply:
            self.step(f"{name} {login}: would invite, accept and publicize the membership (state {state or 'none'})")
            return
        manual = f"accept the invitation and make the membership public in the web UI, logged in as {login}"
        if name not in self.ctx.identities:
            self.step(f"{name} {login}: invited; {manual} (no token)")
            return
        own = self.ctx.http(name, write=True)
        try:
            if state == "pending":
                own.patch(f"/user/memberships/orgs/{target.org}", json={"state": "active"})
            own.put(f"/orgs/{target.org}/public_members/{login}")
        except GitHubError as exc:
            if exc.status not in (403, 404):
                raise
            self.step(f"{name} {login}: the token may not change its membership ({exc.status}): {manual}")
            return
        self.step(f"{name} {login}: active, public")

    def repos(self) -> None:
        """The configs and defaults repositories exist (public, auto-initialized)."""
        target = self.ctx.require_target()
        purposes = {
            target.configs_repo: "webapp otterdog.json, org lease and run ledger",
            target.defaults_repo: "published templates",
        }
        for name, purpose in purposes.items():
            if self.ctx.oracle().repo(name) is not None:
                self.step(f"repo {name} exists")
            elif not self.apply:
                self.step(f"would create the public repo {name} ({purpose})")
            else:
                self.ctx.mutator().create_repo(
                    name, private=False, description=f"otterdog e2e: {purpose}", auto_init=True
                )
                self.step(f"created repo {name}")

    def baseline(self, template: TemplateRef) -> BaselineManager:
        """Baseline reset with the trusted reset SUT (creates teams, fixture repos and the run config repo)."""
        self.ctx.probe()
        workspace = self.ctx.workspace("reset", template)
        reset_cli = self.ctx.cli(self.ctx.installed("reset"), workspace, name="reset", artifacts="reset")
        manager = self.ctx.baseline_manager(reset_cli, self.ctx.renderer(template))
        manager.reset()
        self.step("baseline reset done")
        return manager

    def push(self, baseline: BaselineManager) -> None:
        """Push the baseline to a fixed org config repo (auto: each session pushes its own)."""
        target = self.ctx.require_target()
        if target.org_config_repo == "auto":
            self.step("org_config_repo is auto: every session pushes the baseline to its own e2e-<run>-config repo")
            return
        sha = baseline.push(self.ctx.config_flow(baseline))
        self.step(f"baseline pushed to {target.org_config_repo} ({str(sha)[:12]})")

    def app(self, template: TemplateRef) -> None:
        """otherdog.json for the webapp, installation preflight and delivery probe (only with an App)."""
        if self.ctx.app_credentials() is None:
            self.step("no GitHub App configured: App steps skipped")
            return
        self.ctx.publish_otterdog_json(template)
        self.step("otterdog.json written to the configs repo")
        try:
            installation = self.ctx.installation_id()
        except ContextError as exc:
            raise click.ClickException(str(exc)) from exc
        self.step(f"App installation {installation} ready")
        self.delivery_probe()

    def delivery_probe(self) -> None:
        """Push a throwaway branch e2e/<run>/bootstrap to the configs repo and wait for its push delivery."""
        from otterdog_e2e.waiting import WaitTimeoutError, wait_until

        target, oracle, mutator = self.ctx.require_target(), self.ctx.oracle(), self.ctx.mutator()
        branch = self.ctx.run_ctx.branch("bootstrap")
        default = oracle.default_branch(target.configs_repo) or "main"
        head = oracle.branch_sha(target.configs_repo, default)
        if not head:
            raise click.ClickException(f"{target.configs_repo} has no {default} branch")
        started = datetime.now(UTC)
        mutator.create_branch(target.configs_repo, branch, head)
        try:
            wait_until(
                lambda: self._push_delivery(branch, started),
                timeout=self.probe_timeout,
                interval=10,
                what=f"push delivery of {branch}",
                sleep=self.sleep,
            )
        except WaitTimeoutError as exc:
            raise click.ClickException(
                f"no push delivery for {branch} within {self.probe_timeout:g} s: GitHub may list deliveries a few "
                "minutes late, so run bootstrap again; if it persists, check that the App webhook is active and "
                "subscribed to push events"
            ) from exc
        finally:
            mutator.delete_ref(target.configs_repo, f"heads/{branch}")
        self.step("delivery probe: push delivery received")

    def _push_delivery(self, branch: str, started: datetime) -> dict[str, Any] | None:
        """The App delivery of the push creating ``branch`` (None until it shows up)."""
        app = self.ctx.app_auth()
        items, _cursor = app.list_deliveries(per_page=50)
        for item in items:
            when = parse_time(item.get("delivered_at"))
            if item.get("event") != "push" or (when is not None and when < started - timedelta(minutes=1)):
                continue
            detail = app.get_delivery(int(item["id"]))
            payload = (detail.get("request") or {}).get("payload") or {}
            if payload.get("ref") == f"refs/heads/{branch}":
                return detail
        return None


@main.command()
@click.option("--target", "target", required=True, help="target name or path")
@click.option("--apply", "apply_", is_flag=True, help="perform the changes (default: dry run)")
@_handled
def bootstrap(target: str, apply_: bool) -> None:
    """Prepare a test org idempotently: marker, identities, repos, lease, template, baseline, App checks."""
    with _session(target) as context:
        Bootstrap(context, apply=apply_, confirm=lambda prompt: str(click.prompt(prompt))).run()


# --- sut ------------------------------------------------------------------------------------------------------------
@main.group()
def sut() -> None:
    """Resolve, install, build and classify systems under test."""


@sut.command("resolve")
@click.argument("spec")
@_handled
def sut_resolve(spec: str) -> None:
    """Resolve SPEC and print the ResolvedSut as JSON."""
    with _session(sut=spec, artifacts=False) as context:
        _echo_json(context.resolve(spec).to_json())


@sut.command("install")
@click.argument("spec")
@_handled
def sut_install(spec: str) -> None:
    """Install the CLI of a trusted SPEC on the host."""
    with _session(sut=spec, artifacts=False) as context:
        resolved = context.resolve(spec)
        if not resolved.trusted:
            raise click.ClickException(f"{resolved.label} is untrusted: it never runs on the host (use `sut image`)")
        installed = context.installed("head")
        _echo_json(
            {
                "label": resolved.label,
                "version": resolved.version,
                "runtime": installed.runtime,
                "otterdog": str(installed.otterdog_bin),
                "version_output": installed.version_output.strip(),
            }
        )


@sut.command("image")
@click.argument("spec")
@_handled
def sut_image(spec: str) -> None:
    """Build the webapp image of SPEC."""
    with _session(sut=spec, artifacts=False) as context:
        _echo_json(dataclasses.asdict(context.image_for("head")))


def normalize_spec(spec: SutSpec) -> str:
    """Canonical spec string (``v1.6.1`` -> ``tag:v1.6.1``, ``pr:792@<sha>``)."""
    return f"{spec.kind}:{spec.value}" + (f"@{spec.pin_sha}" if spec.pin_sha else "")


def pr_details(number: int, pin: str | None, upstream: str, http: GitHubHttp) -> dict[str, Any]:
    """Title, author, head repo/sha and risky changed files of an upstream PR (anonymous public reads)."""
    from fnmatch import fnmatch

    pull = http.get(f"/repos/{upstream}/pulls/{number}") or {}
    files = [str(item.get("filename")) for item in http.paginate(f"/repos/{upstream}/pulls/{number}/files")]
    head = pull.get("head") or {}
    return {
        "number": number,
        "title": pull.get("title"),
        "author": (pull.get("user") or {}).get("login"),
        "head_repo": (head.get("repo") or {}).get("full_name"),
        "head_sha": head.get("sha"),
        "pin_is_head": head.get("sha") == pin,
        "changed_files": len(files),
        "risky_files": sorted(f for f in files if any(fnmatch(f, pattern) for pattern in RISKY_PATHS)),
    }


def _code_span(text: Any) -> str:
    """Markdown code span of untrusted text (backticks and newlines neutralized)."""
    return "`" + str(text or "").replace("`", "'").replace("\n", " ") + "`"


def _write_github_files(info: Mapping[str, Any], environ: Mapping[str, str]) -> None:
    """GITHUB_OUTPUT trust/sut/base_sut lines; for untrusted SUTs a review block in GITHUB_STEP_SUMMARY."""
    output = environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={info.get(key) or ''}\n" for key in ("trust", "sut", "base_sut"))
    summary = environ.get("GITHUB_STEP_SUMMARY")
    if summary and info.get("trust") == "untrusted":
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(REDACTOR(_untrusted_summary(info)))


def _untrusted_summary(info: Mapping[str, Any]) -> str:
    """Markdown review block of an untrusted SUT (PR title as a code span, risky files flagged)."""
    lines = ["### Untrusted SUT: review before approving the environment", "", f"- spec: {_code_span(info.get('sut'))}"]
    pull = info.get("pr") or {}
    if pull:
        lines += [
            f"- PR #{pull.get('number')}: {_code_span(pull.get('title'))}",
            f"- author: {_code_span(pull.get('author'))}, head repo: {_code_span(pull.get('head_repo'))}",
            f"- head sha: {_code_span(pull.get('head_sha'))} (pin is head: {pull.get('pin_is_head')})",
            f"- changed files: {pull.get('changed_files')}",
        ]
        risky = pull.get("risky_files") or []
        lines.append("- build/template files changed: " + (", ".join(_code_span(f) for f in risky) or "none"))
    return "\n".join(lines) + "\n"


@sut.command("classify")
@click.argument("spec")
@click.option("--base-sut", default=None, help="base SUT spec to normalize as well")
@_handled
def sut_classify(spec: str, base_sut: str | None) -> None:
    """Print trust (trusted|untrusted) and normalized specs (CI classify job, no secrets)."""
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.sut.spec import parse_sut_spec

    parsed = parse_sut_spec(spec)
    base = AUTO_BASE if base_sut in (None, "", AUTO_BASE) else normalize_spec(parse_sut_spec(str(base_sut)))
    trusted = parsed.trusted
    if parsed.kind == "sha":
        with _session(sut=spec, artifacts=False) as context:
            trusted = context.resolve(spec).trusted
    info: dict[str, Any] = {
        "trust": "trusted" if trusted else "untrusted",
        "sut": normalize_spec(parsed),
        "base_sut": base,
        "kind": parsed.kind,
    }
    if parsed.kind == "pr":
        http = GitHubHttp(None, read_only=True, identity="anonymous")
        info["pr"] = pr_details(int(parsed.value), parsed.pin_sha, _settings().upstream_repo, http)
    _write_github_files(info, os.environ)
    _echo_json(info)


# --- run and pr -----------------------------------------------------------------------------------------------------
@dataclass
class RunRequest:
    """What ``run``/``pr`` pass to pytest (always as ``--e2e-x=value`` so values never look like options)."""

    suites: tuple[str, ...]
    target: str | None = None
    sut: str | None = None
    base_sut: str | None = None
    reset_sut: str | None = None
    tags: str | None = None
    scenario: str | None = None
    keyword: str | None = None
    run_id: str | None = None
    pr_manifest: Path | None = None
    webapp_image: str | None = None
    artifacts: str | None = None
    keep: bool = False
    no_reset: bool = False
    strict_diff: bool = False
    extra: tuple[str, ...] = ()
    extra_scenarios: tuple[str, ...] = ()  # PR manifest scenarios (informational: pytest reads --e2e-pr-manifest)
    allow_web_ui: bool = False  # --e2e-allow-web-ui: web-UI items may log in as the admin bot (web_ui gating)

    def pytest_args(self, project_root: Path) -> list[str]:
        """pytest.main arguments: suite directories, --e2e-* options, -k, pass-through arguments."""
        args = [str(_suite_dir(project_root, suite)) for suite in self.suites]
        values = {
            "--e2e-target": self.target,
            "--e2e-sut": self.sut,
            "--e2e-base-sut": self.base_sut,
            "--e2e-reset-sut": self.reset_sut,
            "--e2e-tags": self.tags,
            "--e2e-scenario": self.scenario,
            "--e2e-run-id": self.run_id,
            "--e2e-pr-manifest": str(self.pr_manifest) if self.pr_manifest else None,
            "--e2e-webapp-image": self.webapp_image,
            "--e2e-artifacts": self.artifacts,
        }
        args += [f"{flag}={value}" for flag, value in values.items() if value]
        flags = {
            "--e2e-keep": self.keep,
            "--e2e-no-reset": self.no_reset,
            "--e2e-strict-diff": self.strict_diff,
            "--e2e-allow-web-ui": self.allow_web_ui,
        }
        args += [flag for flag, enabled in flags.items() if enabled]
        if self.keyword:
            args.append(f"-k{self.keyword}")
        return [*args, *self.extra]

    def command_line(self, project_root: Path) -> str:
        """The equivalent ``otterdog-e2e run`` command (run.json ``command``: summary.md "How to reproduce"); the run
        id, artifacts root and keep flag are left out (a new run gets its own)."""
        manifest = self.pr_manifest
        if manifest is not None and manifest.is_absolute() and manifest.is_relative_to(project_root):
            manifest = manifest.relative_to(project_root)
        argv = ["otterdog-e2e", "run", "--suite", ",".join(self.suites)]
        options = {
            "--target": self.target,
            "--sut": self.sut,
            "--base-sut": self.base_sut,
            "--reset-sut": self.reset_sut,
            "--tags": self.tags,
            "--scenario": self.scenario,
            "-k": self.keyword,
            "--pr-manifest": str(manifest) if manifest is not None else None,
            "--webapp-image": self.webapp_image,
        }
        argv += [part for flag, value in options.items() if value for part in (flag, value)]
        flags = (
            ("--no-reset", self.no_reset),
            ("--strict-diff", self.strict_diff),
            ("--allow-web-ui", self.allow_web_ui),
        )
        argv += [flag for flag, enabled in flags if enabled]
        return shlex.join([*argv, *self.extra])


def _suite_dir(project_root: Path, suite: str) -> Path:
    """tests/<suite> of the project (UsageError for unknown suites or missing directories)."""
    if suite not in SUITES:
        raise click.UsageError(f"unknown suite {suite!r}, expected one of {', '.join(SUITES)}")
    path = project_root / "tests" / suite
    if not path.is_dir():
        raise click.UsageError(f"suite {suite!r}: {path} does not exist")
    return path


SUITE_HELP = f"test tier(s) to run, repeatable or comma separated: {', '.join(SUITES)}"
ALLOW_WEB_UI_HELP = (
    "allow the web-UI tier (--e2e-allow-web-ui): otterdog logs in to github.com as the admin bot (web credentials,"
    " trusted SUTs only; docs/web-ui-testing.md)"
)


def default_suites(*, base_sut: str | None, allow_web_ui: bool) -> tuple[str, ...]:
    """Suites of ``run`` without --suite: every e2e tier; differential with a base SUT, web_ui with --allow-web-ui."""
    return (
        *DEFAULT_SUITES,
        *(("differential",) if base_sut else ()),
        *((WEB_UI_SUITE,) if allow_web_ui else ()),
    )


def parse_suites(values: Sequence[str]) -> tuple[str, ...]:
    """--suite values (repeated and/or comma separated) validated against SUITES."""
    suites = split_csv(values)
    unknown = [suite for suite in suites if suite not in SUITES]
    if unknown:
        raise click.BadParameter(f"unknown suite(s) {', '.join(unknown)}; expected {', '.join(SUITES)}")
    return suites


def run_pytest(args: Sequence[str], *, command: str | None = None) -> int:
    """pytest.main in-process (keeps the credentials of this process; the plugin is loaded by its entry point).

    ``command``: the harness command line, recorded in run.json (summary.md "How to reproduce") via INVOCATION_ENV.
    """
    import pytest

    logger.info("pytest %s", shlex.join(args))
    previous = os.environ.get(INVOCATION_ENV)
    if command:
        os.environ[INVOCATION_ENV] = command
    try:
        return int(pytest.main(list(args)))
    finally:
        if previous is None:
            os.environ.pop(INVOCATION_ENV, None)
        else:
            os.environ[INVOCATION_ENV] = previous


def _check_addopts(environ: Mapping[str, str]) -> None:
    """PYTEST_ADDOPTS obeys the same pass-through rules."""
    check_passthrough(shlex.split(environ.get("PYTEST_ADDOPTS", "")))


def _artifacts_dir(settings: HarnessSettings, request: RunRequest) -> Path:
    """Artifacts directory of a run started by run/pr."""
    root = Path(request.artifacts).expanduser().resolve() if request.artifacts else settings.artifacts_root
    return root / str(request.run_id)


def _echo_run_report(settings: HarnessSettings, request: RunRequest, code: int) -> None:
    """Where the run's summary and differential report are (and the delta counts), after pytest's own output."""
    sys.stdout.flush()  # pytest's final summary line may still sit in the stdout buffer: keep it first
    directory = _artifacts_dir(settings, request)
    _echo(f"pytest exit code {code}; artifacts: {directory}", err=True)
    differential = directory / "differential.json"
    if differential.is_file():
        counts = json.loads(differential.read_text(encoding="utf-8")).get("counts") or {}
        _echo(
            f"differential: {counts.get('unexpected', 0)} unexpected, {counts.get('expected', 0)} expected delta(s)",
            err=True,
        )


@main.command(context_settings={"ignore_unknown_options": True})
@click.option("--target", default=None, help="target name or path")
@click.option("--sut", "sut_spec", default=None, help="SUT spec")
@click.option("--base-sut", default=None, help="base SUT spec (differential)")
@click.option("--reset-sut", default=None, help="trusted reset SUT spec")
@click.option(
    "--suite", "suites", multiple=True, callback=lambda ctx, param, value: parse_suites(value), help=SUITE_HELP
)
@click.option(
    "--tags",
    default=None,
    help="comma separated tags: keep items with any of them (offline/unit exempt; AND --scenario)",
)
@click.option("--scenario", default=None, help="comma separated scenario id globs: keep matching items (AND --tags)")
@click.option("-k", "keyword", default=None, help="pytest -k expression")
@click.option("--run-id", default=None, help="run id (default: a new one)")
@click.option("--artifacts", default=None, help="artifacts root directory")
@click.option("--webapp-image", default=None, help="prebuilt webapp image")
@click.option("--keep", is_flag=True, help="keep run resources after the session")
@click.option("--no-reset", is_flag=True, help="skip the baseline reset")
@click.option("--strict-diff", is_flag=True, help="fail on unexpected differential deltas")
@click.option("--allow-web-ui", is_flag=True, help=ALLOW_WEB_UI_HELP + "; adds web_ui to the default suites")
@click.option(
    "--pr-manifest",
    "pr_manifest",
    default=None,
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="PR manifest (scenarios/otterdog-prs/<N>.yaml): expected deltas, extra scenarios; its base is the default"
    " --base-sut",
)
@click.argument("pytest_args", nargs=-1, type=click.UNPROCESSED)
@_handled
def run(
    target: str | None,
    sut_spec: str | None,
    base_sut: str | None,
    reset_sut: str | None,
    suites: tuple[str, ...],
    tags: str | None,
    scenario: str | None,
    keyword: str | None,
    run_id: str | None,
    artifacts: str | None,
    webapp_image: str | None,
    keep: bool,
    no_reset: bool,
    strict_diff: bool,
    allow_web_ui: bool,
    pr_manifest: Path | None,
    pytest_args: tuple[str, ...],
) -> None:
    """Run test suites through pytest (pass-through args checked by check_passthrough)."""
    from otterdog_e2e.naming import new_run_context

    check_passthrough(pytest_args)
    _check_addopts(os.environ)
    settings = _settings()
    manifest = _run_manifest(pr_manifest)
    if not base_sut and manifest is not None and manifest.base:
        base_sut = manifest.base
    request = RunRequest(
        suites=suites or default_suites(base_sut=base_sut, allow_web_ui=allow_web_ui),
        target=target,
        sut=sut_spec,
        base_sut=base_sut,
        reset_sut=reset_sut,
        tags=tags,
        scenario=scenario,
        keyword=keyword,
        run_id=run_id or new_run_context().run_id,
        pr_manifest=pr_manifest.resolve() if pr_manifest is not None else None,
        webapp_image=webapp_image,
        artifacts=artifacts,
        keep=keep,
        no_reset=no_reset,
        strict_diff=strict_diff,
        extra=pytest_args,
        extra_scenarios=tuple(manifest.scenarios) if manifest is not None else (),
        allow_web_ui=allow_web_ui,
    )
    if manifest is not None:
        _echo(
            f"PR manifest #{manifest.pr} ({pr_manifest}): base {request.base_sut or '-'}, "
            f"manifest scenarios {','.join(request.extra_scenarios) or '-'}",
            err=True,
        )
    code = run_pytest(request.pytest_args(settings.project_root), command=request.command_line(settings.project_root))
    _echo_run_report(settings, request, code)
    sys.exit(code)


def _run_manifest(path: Path | None) -> PrManifest | None:
    """The --pr-manifest of ``run`` loaded (UsageError when invalid), None without one."""
    if path is None:
        return None
    from otterdog_e2e.differential import load_pr_manifest

    try:
        return load_pr_manifest(path)
    except (OSError, ValueError) as exc:
        raise click.UsageError(f"--pr-manifest: {exc}") from exc


def pr_suites(value: str, target: str | None) -> tuple[str, ...]:
    """``auto``: offline + differential (+ the live tiers with a target); else a validated comma list."""
    if value == "auto":
        return ("offline", "differential", *(PR_LIVE_SUITES if target else ()))
    suites = parse_suites([value])
    if not suites:
        raise click.UsageError(f"--suite: expected auto or a comma list of {', '.join(SUITES)}")
    return suites


def load_manifest(settings: HarnessSettings, number: int) -> tuple[Path | None, PrManifest | None]:
    """scenarios/otterdog-prs/<N>.yaml when it exists (its pr must be N)."""
    from otterdog_e2e.differential import load_pr_manifest

    path = settings.scenarios_dir / "otterdog-prs" / f"{number}.yaml"
    if not path.is_file():
        return None, None
    manifest = load_pr_manifest(path)
    if manifest.pr != number:
        raise click.UsageError(f"{path} describes PR {manifest.pr}, not {number}")
    return path, manifest


def plan_pr(number: int, sha: str, *, target: str | None, suites: str, settings: HarnessSettings) -> RunRequest:
    """Resolve the PR (pin checked), load its manifest, derive base and tags.

    tags = selection.select_tags(changed files) + manifest tags. The manifest's ``scenarios`` are EXTRA scenarios:
    pytest reads them from --e2e-pr-manifest and lets them pass the tags filter. They are never passed as
    --e2e-scenario, which restricts every tier (offline and unit included) and is ANDed with --e2e-tags.
    """
    from otterdog_e2e.naming import new_run_context
    from otterdog_e2e.selection import select_tags

    spec = f"pr:{number}@{sha}"
    with _session(sut=spec, artifacts=False) as context:
        changed = list(context.resolve(spec).changed_files)
    manifest_path, manifest = load_manifest(settings, number)
    tags = select_tags(changed) | set(manifest.tags if manifest else ())
    return RunRequest(
        suites=pr_suites(suites, target),
        target=target,
        sut=spec,
        base_sut=(manifest.base if manifest is not None and manifest.base else AUTO_BASE),
        tags=",".join(sorted(tags)),
        run_id=new_run_context().run_id,
        pr_manifest=manifest_path,
        extra_scenarios=tuple(manifest.scenarios) if manifest is not None else (),
    )


PR_WEB_UI_NOTE = (
    "--allow-web-ui: a pr: SUT is untrusted and the web-UI tier only runs trusted SUTs, so its web_ui items skip with"
    " the reason; test a trusted build of the PR instead (run --sut dirty:<checkout> --suite web_ui --allow-web-ui)"
)


@main.command()
@click.argument("number", type=int)
@click.option("--sha", required=True, help="40-hex head sha to test (pin)")
@click.option("--target", default=None, help="target name or path")
@click.option("--suite", "suites", default="auto", help="auto (from the PR's changed files) or a comma list")
@click.option("--strict-diff", is_flag=True, help="fail on unexpected differential deltas")
@click.option("--allow-web-ui", is_flag=True, help=ALLOW_WEB_UI_HELP)
@_handled
def pr(number: int, sha: str, target: str | None, suites: str, strict_diff: bool, allow_web_ui: bool) -> None:
    """Test otterdog PR NUMBER at SHA: regression suites, differential vs its base, manifest scenarios."""
    sha = sha.strip().lower()
    if number <= 0 or not FULL_SHA_RE.match(sha):
        raise click.UsageError("pr needs a positive PR number and --sha with the 40-hex head commit")
    _check_addopts(os.environ)
    settings = _settings()
    request = dataclasses.replace(
        plan_pr(number, sha, target=target, suites=suites, settings=settings),
        strict_diff=strict_diff,
        allow_web_ui=allow_web_ui,
    )
    _echo(
        f"PR #{number} @ {sha[:12]}: base {request.base_sut}, tags {request.tags}, "
        f"manifest scenarios {','.join(request.extra_scenarios) or '-'}",
        err=True,
    )
    if allow_web_ui:
        _echo(PR_WEB_UI_NOTE, err=True)
    command = ["otterdog-e2e", "pr", str(number), "--sha", sha, *(["--target", target] if target else [])]
    command += [*(["--suite", suites] if suites != "auto" else []), *(["--strict-diff"] if strict_diff else [])]
    command += ["--allow-web-ui"] if allow_web_ui else []
    code = run_pytest(request.pytest_args(settings.project_root), command=shlex.join(command))
    _echo_run_report(settings, request, code)
    sys.exit(code)


# --- relay ----------------------------------------------------------------------------------------------------------
def build_relay(context: E2EContext, *, forward_to: str, since: datetime, allow_remote: bool) -> DeliveryRelay:
    """DeliveryRelay of the target's App installation (preflight checked) to ``forward_to``."""
    from otterdog_e2e.webhooks.relay import DeliveryRelay

    return DeliveryRelay(
        context.app_auth(),
        forward_url=forward_to,
        secret=context.require_app_credentials().webhook_secret,
        since=since,
        installation_id=context.installation_id(),
        org=context.require_target().org,
        artifacts_dir=context.artifacts_dir,
        allow_remote=allow_remote,
    )


def delivery_line(delivery: RelayedDelivery) -> str:
    """One line per relayed delivery."""
    event = delivery.event + (f"/{delivery.action}" if delivery.action else "")
    pull = f" #{delivery.pull_number}" if delivery.pull_number else ""
    outcome = delivery.error or f"-> {delivery.relay_status}"
    return f"{delivery.delivered_at:%H:%M:%S} {event}{pull} {outcome}"


def relay_loop(
    relay: DeliveryRelay, *, sleep: Callable[[float], None] = time.sleep, max_polls: int | None = None
) -> None:
    """Poll and print until Ctrl-C (or ``max_polls``); poll errors are logged and retried; the relay is stopped."""
    polls = 0
    try:
        while max_polls is None or polls < max_polls:
            polls += 1
            try:
                for delivery in relay.poll_once():
                    _echo(delivery_line(delivery))
            except Exception as exc:  # noqa: BLE001 - a long-running relay survives transient poll failures
                logger.warning("relay poll failed: %s", describe_error(exc))
            sleep(relay.poll_interval)
    except KeyboardInterrupt:
        _echo("relay stopped", err=True)
    finally:
        relay.stop()


@main.command()
@click.option("--target", "target", required=True, help="target name or path")
@click.option("--forward-to", "forward_to", required=True, help="webhook receiver URL (loopback)")
@click.option("--since", default="10m", show_default=True, help="forward deliveries newer than this")
@click.option("--allow-remote", is_flag=True, help="allow a non-loopback --forward-to")
@_handled
def relay(target: str, forward_to: str, since: str, allow_remote: bool) -> None:
    """Forward the App's webhook deliveries to a local webapp (holds the org lease)."""
    window = parse_duration(since)
    with _session(target, allow_remote_webapp=allow_remote) as context:
        context.load_target()
        context.verify()
        context.acquire_lease()
        delivery_relay = build_relay(
            context, forward_to=forward_to, since=datetime.now(UTC) - window, allow_remote=allow_remote
        )
        _echo(f"relaying deliveries of {context.require_target().org} to {forward_to} (Ctrl-C to stop)", err=True)
        relay_loop(delivery_relay)


# --- janitor --------------------------------------------------------------------------------------------------------
def janitor_filter(
    context: E2EContext, *, older_than: timedelta, run_id: str | None, now: datetime | None = None
) -> Callable[[str], bool]:
    """purgeable for the janitor: ledger runs without active lease, exactly ``run_id`` or older than the cutoff."""
    from otterdog_e2e.naming import run_id_timestamp

    cutoff = (now or datetime.now(UTC)) - older_than

    def purgeable(candidate: str) -> bool:
        """True for the runs this janitor invocation may sweep."""
        if candidate == context.run_ctx.run_id:
            return False
        if run_id is not None:
            return candidate == run_id and context.purgeable(candidate)
        created = run_id_timestamp(candidate)
        return created is not None and created <= cutoff and context.purgeable(candidate)

    return purgeable


def render_items(items: Iterable[JanitorItem]) -> str:
    """Table of janitor items."""
    rows = [(item.kind, item.name, item.run_id or "-", item.scope, item.detail) for item in items]
    if not rows:
        return "nothing to sweep"
    widths = [max(len(str(row[index])) for row in rows) for index in range(4)]
    return "\n".join(
        "  ".join(str(value).ljust(width) for value, width in zip(row[:4], widths, strict=True))
        + f"  {row[4]}".rstrip()
        for row in rows
    )


@main.command()
@click.option("--target", "target", required=True, help="target name or path")
@click.option("--older-than", default="6h", show_default=True, help="minimum age of swept runs")
@click.option("--run-id", default=None, help="sweep exactly this run (no age threshold)")
@click.option("--apply", "apply_", is_flag=True, help="delete (default: dry run)")
@click.option(
    "--force-takeover",
    is_flag=True,
    help="with --run-id: take over that run's lease even if it was renewed recently (the run is known to be dead)",
)
@_handled
def janitor(target: str, older_than: str, run_id: str | None, apply_: bool, force_takeover: bool) -> None:
    """List (and with --apply delete) leftovers of finished or crashed runs.

    With --run-id and --apply, a lease still held by that run is taken over (compare-and-swap) only when the run looks
    dead: no renewal for 20 minutes, or the holder is this CI job; --force-takeover skips that check.
    """
    age = parse_duration(older_than)
    if run_id is not None and not RUN_ID_ARG_RE.match(run_id):
        raise click.UsageError(f"--run-id {run_id!r} is not a run id")
    if force_takeover and run_id is None:
        raise click.UsageError("--force-takeover needs --run-id")
    with _session(target) as context:
        context.load_target()
        context.verify()
        if apply_:
            context.acquire_lease(takeover_run=run_id, force_takeover=force_takeover)
        sweeper = context.janitor(janitor_filter(context, older_than=age, run_id=run_id))
        items = sweeper.scan()
        _echo(render_items(items))
        if not apply_:
            if items:
                _echo("dry run: re-run with --apply to delete", err=True)
            return
        deleted = sweeper.sweep(items)
        _echo(f"deleted {len(deleted)} of {len(items)} item(s)", err=True)


# --- reports and cache ----------------------------------------------------------------------------------------------
@main.command()
@click.argument("directory", type=click.Path(file_okay=False, exists=True))
@_handled
def report(directory: str) -> None:
    """Print the summary of a run artifacts directory."""
    from otterdog_e2e import report as report_module

    _echo(report_module.build_summary(Path(directory)))


def register_environment_secrets(environ: Mapping[str, str], redactor: Redactor | None = None) -> int:
    """Register with the redactor (default REDACTOR) the values of the variables whose name matches SECRET_KEY_RE
    (``*_TOKEN``, ``*_SECRET``, ``*_PASSWORD``, ``*_TOTP_SEED``, ``*_PRIVATE_KEY``); returns how many were long enough
    to register. A separate scrub process (the CI scrub step) knows no secret of the session: without this, a leaked
    value that has no token shape (the web-UI password, a TOTP seed, a webhook secret) would pass the scan."""
    from otterdog_e2e.redact import MIN_SECRET_LENGTH, SECRET_KEY_RE

    values = [value for key, value in environ.items() if SECRET_KEY_RE.search(key) and len(value) >= MIN_SECRET_LENGTH]
    (REDACTOR if redactor is None else redactor).add(*values)
    return len(values)


@main.command("scrub-artifacts")
@click.argument("directory", type=click.Path(file_okay=False))
@_handled
def scrub_artifacts(directory: str) -> None:
    """Scrub a run artifacts directory (exit 1 when leaks were found and removed).

    The secret values of the process environment (SECRET_KEY_RE names) are registered first, so the scan also finds
    leaked secrets that have no token shape.
    """
    from otterdog_e2e import report as report_module

    logger.info("scrub: %d secret value(s) of the environment registered", register_environment_secrets(os.environ))
    leaks = report_module.scrub_artifacts(Path(directory), REDACTOR)
    for leak in leaks:
        _echo(f"removed file leaking a secret: {leak}", err=True)
    if leaks:
        sys.exit(1)
    _echo("no leak found")


def prune_cache_dirs(cache_dir: Path, *, keep: int) -> list[Path]:
    """Keep the ``keep`` newest entries of run/, build/, src/ and http-cache/ (sidecar ``<name>.*`` files go too)."""
    removed: list[Path] = []
    for sub in PRUNABLE_CACHE_DIRS:
        base = cache_dir / sub
        if not base.is_dir() or base.is_symlink():
            continue
        entries = [entry for entry in base.iterdir() if entry.is_dir() and not entry.is_symlink()]
        entries.sort(key=lambda entry: entry.stat().st_mtime, reverse=True)
        for entry in entries[keep:]:
            shutil.rmtree(entry)
            for sidecar in base.glob(f"{entry.name}.*"):
                if sidecar.is_file() or sidecar.is_symlink():
                    sidecar.unlink()
            removed.append(entry)
    return removed


def prune_images(*, keep: int) -> list[str]:
    """Remove all but the ``keep`` newest images of the trusted and untrusted harness repositories."""
    from otterdog_e2e import procs
    from otterdog_e2e.sut.image import TRUSTED_IMAGE_REPO, UNTRUSTED_IMAGE_REPO, docker_available

    if not docker_available():
        return []
    removed = []
    for repository in (TRUSTED_IMAGE_REPO, UNTRUSTED_IMAGE_REPO):
        listing = procs.run(
            ["docker", "image", "ls", "--format", "{{.Repository}}:{{.Tag}}", repository], keep_home=True, timeout=60
        )
        tags = [line.strip() for line in listing.stdout.splitlines() if line.strip() and not line.endswith(":<none>")]
        for tag in tags[keep:]:  # docker lists the newest images first
            if procs.run(["docker", "image", "rm", tag], keep_home=True, timeout=120).returncode == 0:
                removed.append(tag)
    return removed


@main.group()
def cache() -> None:
    """Manage the harness cache."""


@cache.command("prune")
@click.option(
    "--keep", default=3, show_default=True, type=click.IntRange(min=0), help="number of recent builds/runs to keep"
)
@_handled
def cache_prune(keep: int) -> None:
    """Remove old builds, venvs, images and run scratch directories."""
    removed = prune_cache_dirs(_settings().cache_dir, keep=keep)
    images = prune_images(keep=keep)
    for path in removed:
        _echo(f"removed {path}")
    for image in images:
        _echo(f"removed image {image}")
    _echo(f"pruned {len(removed)} cache entr{'y' if len(removed) == 1 else 'ies'} and {len(images)} image(s)", err=True)


# --- app-manifest ---------------------------------------------------------------------------------------------------
class ManifestFlow:
    """One-shot callback listener of the GitHub App manifest flow (127.0.0.1 only, ``state`` verified)."""

    def __init__(
        self,
        target: Target,
        *,
        webhook_url: str,
        port: int,
        state: str | None = None,
        timeout: float = MANIFEST_TIMEOUT,
    ) -> None:
        """Prepare the flow; nothing listens before run()."""
        self.target = target
        self.webhook_url = webhook_url
        self.port = port
        self.state = state or secrets.token_urlsafe(24)
        self.timeout = timeout
        self.page = ""
        self.code: str | None = None

    def run(self, *, on_ready: Callable[[str], None] | None = None) -> str:
        """Serve the auto-posting form and wait for GitHub's redirect; returns the temporary code."""
        from otterdog_e2e.appmanifest import build_manifest, manifest_form_html

        server = _ManifestServer(("127.0.0.1", self.port), self)
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}/"
            manifest = build_manifest(self.target, webhook_url=self.webhook_url, redirect_url=f"{base}callback")
            self.page = manifest_form_html(self.target.org, manifest, self.state)
            (on_ready or (lambda url: _echo(f"open {url} in a browser logged in as an owner of {self.target.org}")))(
                base
            )
            deadline = time.monotonic() + self.timeout
            while self.code is None:
                if time.monotonic() > deadline:
                    raise click.ClickException(f"no callback from GitHub within {self.timeout:g} s")
                server.handle_request()
        finally:
            server.server_close()
        return self.code

    def callback(self, query: Mapping[str, list[str]]) -> tuple[int, str]:
        """Accept GitHub's redirect only with our state; keeps the code (registered with REDACTOR)."""
        state = (query.get("state") or [""])[0]
        if not hmac.compare_digest(state.encode(), self.state.encode()):
            return 400, "state mismatch: ignored"
        code = (query.get("code") or [""])[0]
        if not re.fullmatch(r"[0-9A-Za-z_-]{8,256}", code):
            return 400, "missing or malformed code"
        REDACTOR.add(code)
        self.code = code
        return 200, "GitHub App created: return to the terminal."


class _ManifestHandler(http.server.BaseHTTPRequestHandler):
    """GET / (manifest form) and GET /callback?code=&state= (GitHub redirect)."""

    server: _ManifestServer

    def do_GET(self) -> None:
        """Serve the form or handle the callback."""
        url = urllib.parse.urlsplit(self.path)
        flow = self.server.flow
        if url.path == "/":
            self._send(200, flow.page, "text/html; charset=utf-8")
        elif url.path == "/callback":
            self._send(*flow.callback(urllib.parse.parse_qs(url.query)))
        else:
            self._send(404, "not found")

    def _send(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        """Write one response."""
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        """Never log request lines (they carry the temporary code)."""
        logger.debug("manifest listener: request handled")


class _ManifestServer(http.server.HTTPServer):
    """HTTPServer bound to loopback carrying the flow; handle_request() returns every second."""

    def __init__(self, address: tuple[str, int], flow: ManifestFlow) -> None:
        """Bind the listener."""
        super().__init__(address, _ManifestHandler)
        self.flow = flow
        self.timeout = 1.0


def app_credentials_dir(target: Target) -> Path:
    """~/.config/otterdog-e2e/<target>/ (exchange_code writes the key and secret there, 0600)."""
    return CONFIG_HOME.expanduser() / target.name


def app_instructions(target: Target, result: Mapping[str, Any]) -> str:
    """Next steps after the exchange (paths only: secrets are never printed)."""
    app = target.app
    id_env = app.id_env if app else "E2E_APP_ID"
    key_env = (app.private_key_file_env if app else None) or "E2E_APP_PRIVATE_KEY_FILE"
    secret_env = app.webhook_secret_env if app else "E2E_APP_WEBHOOK_SECRET"
    return "\n".join(
        [
            f"GitHub App created: id {result.get('id')}, slug {result.get('slug')}",
            f"private key (0600):    {result.get('pem_path')}",
            f"webhook secret (0600): {result.get('secret_path')}",
            f"add to {CONFIG_HOME}/{target.name}.env:",
            f"  {id_env}={result.get('id')}",
            f"  E2E_APP_SLUG={result.get('slug')}",
            f"  {key_env}={result.get('pem_path')}",
            f"  {secret_env}=<the content of {result.get('secret_path')}>",
            f"then install it on {target.org} for All repositories: https://github.com/apps/{result.get('slug')}/installations/new",
        ]
    )


@main.command("app-manifest")
@click.option("--target", "target", required=True, help="target name or path")
@click.option("--webhook-url", required=True, help="App webhook sink URL (non-loopback)")
@click.option("--port", default=8765, show_default=True, help="local callback port")
@click.option("--exchange", "code", default=None, help="exchange a manifest code for the App credentials")
@_handled
def app_manifest(target: str, webhook_url: str, port: int, code: str | None) -> None:
    """Create the e2e GitHub App from a manifest, or exchange the returned code."""
    from otterdog_e2e.appmanifest import exchange_code

    context = _context(target, make_dirs=False)
    loaded = context.load_target()
    if _is_loopback_url(webhook_url):
        raise click.UsageError("--webhook-url must not be a loopback URL (deliveries reach the webapp via the relay)")
    if code is None:
        context.verify(require_marker=True, check_identities=False)
        code = ManifestFlow(loaded, webhook_url=webhook_url, port=port).run()
    else:
        REDACTOR.add(code)
    _echo(app_instructions(loaded, exchange_code(code, out_dir=app_credentials_dir(loaded))))


# --- inject: jsonnet files injected into a rendered configuration, without a scenario ------------------------------
if TYPE_CHECKING:
    from otterdog_e2e.inject import InjectRequest

INJECT_FILE = click.Path(exists=True, dir_okay=False, path_type=Path)
INJECT_PLANS = ("free", "team", "enterprise")  # capabilities.PLANS (checked in inject_request)


def _existing_file(value: str, option: str) -> Path:
    """Resolved path of the existing file an option value names (UsageError otherwise)."""
    path = Path(value).expanduser()
    if not path.is_file():
        raise click.UsageError(f"{option}: {value!r} is not an existing file")
    return path.resolve()


def inject_request(
    *,
    live: bool,
    fragments: Sequence[str],
    libraries: Sequence[str],
    overlays: Sequence[Path],
    config: Path | None,
    base: Path | None,
    plan: str | None,
    variables: Sequence[str],
    apply_: bool,
    keep: bool,
) -> InjectRequest:
    """The InjectRequest of the inject options (UsageError for inconsistent options; files may lie anywhere)."""
    from otterdog_e2e.capabilities import PLANS
    from otterdog_e2e.inject import InjectError, InjectRequest, parse_assignment, parse_variables
    from otterdog_e2e.otterdog.render import FRAGMENT_KEYS, library_name_problem

    if not (fragments or overlays or config):
        raise click.UsageError("nothing to inject: give --fragment KIND=FILE, --overlay FILE or --config FILE")
    if live and (config or base):
        raise click.UsageError("--config and --base are offline only (live configs are rendered on the baseline)")
    if apply_ and not live:
        raise click.UsageError("--apply needs a live target (--target without --offline)")
    if config and (fragments or overlays):
        raise click.UsageError("--config replaces the rendered configuration: drop --fragment and --overlay")
    if plan is not None and plan not in PLANS:
        raise click.UsageError(f"--plan: {plan!r} is not one of {', '.join(PLANS)}")
    try:
        kinds = [parse_assignment(item, "--fragment") for item in fragments]
        names = [parse_assignment(item, "--library") for item in libraries]
        extra = parse_variables(variables)
    except InjectError as exc:
        raise click.UsageError(str(exc)) from None
    unknown = [kind for kind, _ in kinds if kind not in FRAGMENT_KEYS]
    if unknown:
        raise click.UsageError(f"--fragment: unknown kind(s) {', '.join(unknown)}; expected {', '.join(FRAGMENT_KEYS)}")
    for name, _ in names:
        problem = library_name_problem(name)
        if problem:
            raise click.UsageError(f"--library: {problem}")
    if len({name for name, _ in names}) != len(names):
        raise click.UsageError("--library: each NAME may be given once")
    if "plan" in extra:
        raise click.UsageError("--var plan=...: use --plan")
    if plan:
        extra["plan"] = plan
    return InjectRequest(
        fragments=[(kind, _existing_file(path, "--fragment")) for kind, path in kinds],
        libraries=[(name, _existing_file(path, "--library")) for name, path in names],
        overlays=[path.resolve() for path in overlays],
        config=config.resolve() if config is not None else None,
        base=base.resolve() if base is not None else None,
        live=live,
        apply=apply_,
        keep=keep,
        variables=extra,
    )


def inject_pytest_args(
    project_root: Path,
    *,
    run_id: str,
    target: str | None,
    sut: str | None,
    reset_sut: str | None,
    artifacts: str | None,
    keep: bool,
    no_reset: bool,
) -> list[str]:
    """pytest.main arguments of an injection: tests/adhoc, short tracebacks (the command prints its own summary) and
    the --e2e-* options; the target and the selection and differential options are always given (empty), so their
    E2E_* environment fallbacks never apply."""
    args = [
        str(project_root / "tests" / "adhoc"),
        "--tb=short",
        f"--e2e-run-id={run_id}",
        f"--e2e-target={target or ''}",
        "--e2e-tags=",
        "--e2e-scenario=",
        "--e2e-base-sut=",
        "--e2e-pr-manifest=",
    ]
    values = {"--e2e-sut": sut, "--e2e-reset-sut": reset_sut, "--e2e-artifacts": artifacts}
    args += [f"{flag}={value}" for flag, value in values.items() if value]
    return args + [flag for flag, enabled in (("--e2e-keep", keep), ("--e2e-no-reset", no_reset)) if enabled]


def inject_command_line(
    request: InjectRequest, *, target: str | None, sut: str | None, reset_sut: str | None, no_reset: bool
) -> str:
    """The ``otterdog-e2e inject`` command of a request (run.json ``command``: summary.md "How to reproduce")."""
    options = {"--target": target, "--sut": sut, "--reset-sut": reset_sut}
    argv = ["otterdog-e2e", "inject", *(part for flag, value in options.items() if value for part in (flag, value))]
    argv += [part for kind, path in request.fragments for part in ("--fragment", f"{kind}={path}")]
    argv += [part for name, path in request.libraries for part in ("--library", f"{name}={path}")]
    argv += [part for path in request.overlays for part in ("--overlay", str(path))]
    files = {"--config": request.config, "--base": request.base}
    argv += [part for flag, path in files.items() if path is not None for part in (flag, str(path))]
    variables = dict(request.variables)
    plan = variables.pop("plan", None)
    if plan:
        argv += ["--plan", str(plan)]
    for name, value in variables.items():
        argv += ["--var", f"{name}={value if isinstance(value, str) else json.dumps(value)}"]
    flags = (("--apply", request.apply), ("--keep", request.keep), ("--no-reset", no_reset))
    return shlex.join([*argv, *(flag for flag, enabled in flags if enabled)])


def adhoc_item(run_dir: Path) -> dict[str, Any] | None:
    """The results.jsonl line of the injection's test item, None when it did not run."""
    path = run_dir / "results.jsonl"
    found = None
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and "tests/adhoc/" in str(data.get("nodeid", "")):
                found = data
    return found


def echo_inject_report(run_dir: Path, *, mode: str, code: int, print_config: bool) -> None:
    """After the session: rendered config paths, validation and plan summaries, the result (and the configs)."""
    from otterdog_e2e.inject import ADHOC_DIR, read_adhoc_result, result_lines

    sys.stdout.flush()  # pytest's summary first
    result = read_adhoc_result(run_dir / ADHOC_DIR) or {}
    _echo(f"otterdog-e2e inject ({mode}): artifacts {run_dir}")
    for line in result_lines(result):
        _echo(line)
    item = adhoc_item(run_dir)
    if item is None:
        _echo(f"result: not run (pytest exit code {code}), see {run_dir / 'summary.md'}")
    elif result.get("failures"):
        _echo(f"result: {item.get('outcome')}")
        for failure in result["failures"]:
            _echo(f"  - {failure}")
    else:
        detail = item.get("failure") or item.get("reason") or result.get("error")
        _echo(f"result: {item.get('outcome')}" + (f": {detail}" if detail else ""))
    if print_config:
        for key in ("config", "base_config"):
            if result.get(key) and Path(result[key]).is_file():
                _echo(f"--- {result[key]}")
                _echo(Path(result[key]).read_text(encoding="utf-8").rstrip("\n"))


@main.command("inject")
@click.option("--target", default=None, help="target name or path: live injection (validate + plan; --apply applies)")
@click.option("--sut", "sut_spec", default=None, help="SUT spec (default: release:latest)")
@click.option("--reset-sut", default=None, help="trusted reset SUT spec (live)")
@click.option(
    "--fragment",
    "fragments",
    multiple=True,
    metavar="KIND=FILE",
    help="fragment file of KIND (repositories, settings, secrets, variables, webhooks, ...), repeatable",
)
@click.option(
    "--library",
    "libraries",
    multiple=True,
    metavar="NAME=FILE",
    help="library file inlined as 'local NAME = (...);' after the template import, repeatable",
)
@click.option("--overlay", "overlays", multiple=True, type=INJECT_FILE, help="object mixin applied last, repeatable")
@click.option("--config", default=None, type=INJECT_FILE, help="offline: complete org config replacing the rendering")
@click.option("--base", default=None, type=INJECT_FILE, help="offline: -BASE config of local-plan (default: bare org)")
@click.option("--plan", default=None, help=f"plan rendered into settings.plan: {', '.join(INJECT_PLANS)}")
@click.option("--var", "variables", multiple=True, metavar="NAME=VALUE", help="Jinja variable (YAML value), repeatable")
@click.option("--offline", is_flag=True, help="offline injection (the default without --target)")
@click.option("--apply", "apply_", is_flag=True, help="live: guarded apply, converge, cleanup (default: validate+plan)")
@click.option("--keep", is_flag=True, help="no cleanup: keep the run's objects (live) and scratch directory")
@click.option("--no-reset", is_flag=True, help="live: skip the baseline reset at session start")
@click.option("--print", "print_config", is_flag=True, help="print the rendered configuration after the run")
@click.option("--run-id", default=None, help="run id (default: a new one)")
@click.option("--artifacts", default=None, help="artifacts root directory")
@_handled
def inject_command(
    target: str | None,
    sut_spec: str | None,
    reset_sut: str | None,
    fragments: tuple[str, ...],
    libraries: tuple[str, ...],
    overlays: tuple[Path, ...],
    config: Path | None,
    base: Path | None,
    plan: str | None,
    variables: tuple[str, ...],
    offline: bool,
    apply_: bool,
    keep: bool,
    no_reset: bool,
    print_config: bool,
    run_id: str | None,
    artifacts: str | None,
) -> None:
    """Inject jsonnet files without writing a scenario: validate and plan them offline, or on a live target.

    The files (any path) go through the scenario model's rules; the generated scenario runs in tests/adhoc with the
    regular fixtures and safety (offline sandbox; live: org lease, baseline reset, guarded apply, cleanup).
    """
    from otterdog_e2e.inject import ADHOC_DIR, ADHOC_ENV, write_adhoc_scenario
    from otterdog_e2e.naming import new_run_context
    from otterdog_e2e.scenarios.model import ScenarioError, load_adhoc_scenario

    if offline and target:
        raise click.UsageError("--offline and --target exclude each other (an offline injection uses no target)")
    if run_id is not None and not RUN_ID_ARG_RE.match(run_id):
        raise click.UsageError(f"--run-id {run_id!r} is not a run id ({RUN_ID_ARG_RE.pattern})")
    _check_addopts(os.environ)
    live = bool(target)
    request = inject_request(
        live=live,
        fragments=fragments,
        libraries=libraries,
        overlays=overlays,
        config=config,
        base=base,
        plan=plan,
        variables=variables,
        apply_=apply_,
        keep=keep,
    )
    settings = _settings()
    run_id = run_id or new_run_context().run_id
    scratch = settings.scratch(run_id)
    path = write_adhoc_scenario(request, scratch / ADHOC_DIR)
    try:
        load_adhoc_scenario(path)  # every content rule, with <file>:<line> messages, before any session starts
    except ScenarioError as exc:
        if not keep:
            shutil.rmtree(scratch, ignore_errors=True)
        raise click.ClickException(str(exc).removeprefix(f"{path}: ")) from None
    args = inject_pytest_args(
        settings.project_root,
        run_id=run_id,
        target=target if live else None,
        sut=sut_spec,
        reset_sut=reset_sut,
        artifacts=artifacts,
        keep=keep,
        no_reset=no_reset,
    )
    command = inject_command_line(request, target=target, sut=sut_spec, reset_sut=reset_sut, no_reset=no_reset)
    previous = os.environ.get(ADHOC_ENV)
    os.environ[ADHOC_ENV] = str(path)
    try:
        code = run_pytest(args, command=command)
    finally:
        if previous is None:
            os.environ.pop(ADHOC_ENV, None)
        else:
            os.environ[ADHOC_ENV] = previous
    root = Path(artifacts).expanduser().resolve() if artifacts else settings.artifacts_root
    echo_inject_report(root / run_id, mode=request.mode, code=code, print_config=print_config)
    sys.exit(code)
