"""``otterdog-e2e doctor`` (SPEC 16): the read-only checks of a target, never mutating and never taking the org lease.

Doctor checks, in dependency order: the target and its environment, every identity (declared login, token kind and
expiration, isolation, the scopes or fine-grained permissions of the owner tokens), the org and its safety marker, the
memberships, teams, repositories and unmanaged objects, the GitHub App, the web-UI tier, the template pin and the
tools; render_rows prints the OK/WARN/FAIL table with remediation hints. Several targets are checked in turn, each with
its own copy of the environment.
"""

from __future__ import annotations

import dataclasses
import functools
import os
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import click

from otterdog_e2e.cli.common import (
    CONFIG_HOME,
    FULL_SHA_RE,
    TARGETS_HELP,
    _context,
    _declared_login,
    _echo,
    _echo_json,
    _handled,
    _is_loopback_url,
    _public_member,
    main,
    target_names,
)
from otterdog_e2e.context import (
    E2EContext,
    E2EOptions,
    describe_error,
    in_ci,
    installation_problems,
    parse_time,
)
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.github.app import AppAuth
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import Target

# otterdog's own check-token-permissions requirement for the admin PAT
REQUIRED_ADMIN_SCOPES = frozenset({"admin:org", "admin:org_hook", "delete_repo", "repo", "workflow"})
TOKEN_EXPIRY_WARNING = timedelta(days=14)  # doctor WARNs when a token expires sooner
# read probes of a fine-grained admin/oracle token: (path, permission); {org} = the test org, {repo} = the configs repo.
# Each answers 200 only with the permission (docs/setup-free-org.md#fine-grained-personal-access-tokens); write
# access cannot be probed without mutating, the first live run verifies it
FINE_GRAINED_OWNER_READS: tuple[tuple[str, str], ...] = (
    ("/orgs/{org}/actions/permissions", "Organization > Administration"),
    ("/orgs/{org}/hooks", "Organization > Webhooks"),
    ("/orgs/{org}/teams", "Organization > Members"),
    ("/orgs/{org}/actions/secrets", "Organization > Secrets"),
    ("/orgs/{org}/actions/variables", "Organization > Variables"),
    ("/orgs/{org}/properties/schema", "Organization > Custom properties"),
    ("/orgs/{org}/organization-roles", "Organization > Custom organization roles"),
    ("/repos/{org}/{repo}/actions/permissions", "Repository > Administration"),
    ("/repos/{org}/{repo}/hooks", "Repository > Webhooks"),
    ("/repos/{org}/{repo}/actions/secrets", "Repository > Secrets"),
    ("/repos/{org}/{repo}/actions/variables", "Repository > Variables"),
    ("/repos/{org}/{repo}/environments", "Repository > Actions"),
)
# reads GitHub lists under WRITE access (fine-grained permission tables): a GET that proves write access; org rulesets
# need a paid plan, so only probed on team/enterprise targets
FINE_GRAINED_OWNER_WRITE_READS: tuple[tuple[str, str], ...] = (
    ("/orgs/{org}/rulesets", "Organization > Administration: Read and write"),
)
DELIVERY_FRESHNESS = timedelta(hours=72)
OK, WARN, FAIL = "OK", "WARN", "FAIL"


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
        """The target loads (env files applied): ``instance (profile p, file)`` with its org."""
        try:
            target = self.ctx.load_target()
        except Exception as exc:  # noqa: BLE001 - reported as the first FAIL
            hint = (
                f"check targets/<profile>.yaml and the env vars of the instance (export them or write"
                f" {CONFIG_HOME}/<instance>.env with E2E_PROFILE=<profile>, .env.e2e.<instance> or .env.e2e;"
                " otterdog-e2e targets lists the instances)"
            )
            self.add("target", FAIL, describe_error(exc), hint)
            return None
        profile = target.profile or target.source_path.stem
        self.add(
            "target",
            OK,
            f"{target.name} (profile {profile}, {target.source_path.name}): org {target.org} (id {target.org_id}),"
            f" {target.expected_plan}",
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
        from otterdog_e2e.safety import SafetyError, check_identity_isolation, read_token_info

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
        info = read_token_info(http, name)
        token_type = self.ctx.identities[name].token_type
        if not self._token(name, info, token_type):
            return False
        try:
            check_identity_isolation(
                http,
                role=name,
                allowed_org_ids=target.allowed_org_ids,
                test_org_id=target.org_id,
                org=target.org,
                token_type=token_type,
            )
        except SafetyError as exc:
            remediation = (
                "use a dedicated machine account that belongs only to test orgs"
                if info.kind == "classic"
                else "create the fine-grained token with the test org as resource owner (docs/security.md)"
            )
            self.add(f"isolation:{name}", FAIL, str(exc), remediation)
            return False
        detail = (
            "member of test orgs only, token scopes allowed"
            if info.kind == "classic"
            else f"{info.kind} token bound to {target.org}"
            if name != "config_reader"
            else f"{info.kind} token (read-only role)"
        )
        self.add(f"isolation:{name}", OK, detail)
        if name in ("admin", "oracle"):
            self._owner_token(target, name, http, info)
        if name == "config_reader":
            self._config_reader(http)
        return True

    def _token(self, name: str, info: Any, declared: str) -> bool:
        """token:<name>: kind, declared token_type and expiration (WARN under TOKEN_EXPIRY_WARNING)."""
        kind = {"classic": "classic PAT", "fine-grained": "fine-grained PAT"}.get(info.kind, "App/OAuth token")
        if declared not in ("auto", info.kind):
            self.add(
                f"token:{name}",
                FAIL,
                f"{kind}, but the target declares token_type {declared!r}",
                f"fix identities.{name}.token_type or use a {declared} token",
            )
            return False
        if info.expires_at is None:
            note = "expiration unknown: " + info.expiration_header if info.expiration_header else "no expiration"
            self.add(f"token:{name}", OK, f"{kind}, {note}")
            return True
        left = info.expires_at - datetime.now(UTC)
        detail = f"{kind}, expires {info.expires_at:%Y-%m-%d %H:%M} UTC"
        if left < TOKEN_EXPIRY_WARNING:
            self.add(f"token:{name}", WARN, f"{detail} (in {max(left.days, 0)} day(s))", "regenerate the token soon")
        else:
            self.add(f"token:{name}", OK, detail)
        return True

    def _owner_token(self, target: Target, name: str, http: GitHubHttp, info: Any) -> None:
        """scopes:<name> of a classic admin PAT, permissions:<name> of a fine-grained admin/oracle token."""
        if info.kind == "classic":
            if name == "admin":
                self._admin_scopes(set(info.scopes or ()))
            return
        self._owner_permissions(target, name, http)

    def _admin_scopes(self, scopes: set[str]) -> None:
        """The classic admin PAT has otterdog's required scopes."""
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

    def _owner_permissions(self, target: Target, name: str, http: GitHubHttp) -> None:
        """Read probes of the permissions otterdog (admin) / the oracle need; missing ones named with what GitHub asks."""
        from otterdog_e2e.safety import PermissionProbe, run_probe

        missing = []
        probes = FINE_GRAINED_OWNER_READS
        if target.expected_plan != "free":
            probes += FINE_GRAINED_OWNER_WRITE_READS
        for path, permission in probes:
            probe = PermissionProbe(path.replace("{repo}", target.configs_repo), permission)
            _, error = run_probe(http, probe, target.org)
            if error is None:
                continue
            headers = {str(key).lower(): value for key, value in (getattr(error, "headers", None) or {}).items()}
            accepted = headers.get("x-accepted-github-permissions")
            status = getattr(error, "status", "error")
            missing.append(
                f"{permission} (GET {probe.path.format(org=target.org)}: {status}"
                + (f", GitHub accepts {accepted})" if accepted else ")")
            )
        if missing:
            self.add(
                f"permissions:{name}",
                FAIL,
                "missing read access: " + "; ".join(missing),
                "edit the fine-grained token (docs/setup-free-org.md#fine-grained-personal-access-tokens)",
            )
        else:
            self.add(
                f"permissions:{name}",
                OK,
                f"{len(probes)} read probes passed (write access is verified by the first live run)",
            )

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


def _doctor_report(target: str, checks: Doctor, rows: Sequence[CheckRow]) -> dict[str, Any]:
    """The --json document of one target's checks."""
    return {"target": target, "ok": not checks.failed, "checks": [dataclasses.asdict(row) for row in rows]}


@main.command()
@click.option("--target", "targets", multiple=True, required=True, help=TARGETS_HELP)
@click.option("--json", "as_json", is_flag=True, help="print the checks as JSON (a list with several targets)")
@_handled
def doctor(targets: tuple[str, ...], as_json: bool) -> None:
    """Check environment, identities, isolation, org, repos, teams, App and tools of a target (exit 1 on FAIL).

    Several targets: one table per target, each checked with its own copy of the environment (the env files of one
    target never reach the checks of another); exit 1 when any target has a FAIL.
    """
    names = target_names(targets, required=True)
    if len(names) == 1:
        checks = Doctor(_context(names[0], make_dirs=False))
        rows = checks.run()
        if as_json:
            _echo_json(_doctor_report(names[0], checks, rows))
        else:
            _echo(render_rows(rows))
        if checks.failed:
            sys.exit(1)
        return
    reports = []
    for name in names:
        checks = Doctor(E2EContext.create(E2EOptions(target=name), environ=dict(os.environ), make_dirs=False))
        reports.append((name, checks, checks.run()))
    failed = [name for name, checks, _rows in reports if checks.failed]
    if as_json:
        _echo_json([_doctor_report(name, checks, rows) for name, checks, rows in reports])
    else:
        for name, _checks, rows in reports:
            _echo(f"=== target {name} ===\n{render_rows(rows)}\n")
        _echo(
            f"doctor: {len(reports)} targets, {len(failed)} with failures"
            + (f": {', '.join(failed)}" if failed else "")
        )
    if failed:
        sys.exit(1)
