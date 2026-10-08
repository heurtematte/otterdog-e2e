"""``otterdog-e2e bootstrap`` (SPEC 16): prepares a test org idempotently.

Bootstrap runs, in order: verify -> safety marker (after typing the org login) -> identities (invitations, a separate
oracle made an owner) -> configs and defaults repos -> org lease -> template -> baseline reset -> baseline push -> App
checks and delivery probe. Without --apply it only reports. The web-UI steps GitHub does not let a program do
(accepting an invitation, making a membership public, installing the App, approving a member's fine-grained token)
are printed with their URLs; --wait polls until they are done.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import click

from otterdog_e2e.cli.common import _declared_login, _echo, _handled, _public_member, _session, main
from otterdog_e2e.context import ContextError, E2EContext, describe_error, in_ci, parse_duration, parse_time

if TYPE_CHECKING:
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.template import TemplateRef

# --- bootstrap ------------------------------------------------------------------------------------------------------
DELIVERY_PROBE_TIMEOUT = 300.0  # like every delivery wait of the harness: GitHub lists deliveries minutes late (F6)
BOOTSTRAP_WAIT_TIMEOUT = 1800.0  # --wait: 30 min for the invitations to be accepted / the App to be installed
BOOTSTRAP_WAIT_INTERVAL = 10.0
BOOTSTRAP_MEMBERS = ("author", "approver")  # active and public members of the org (no owner rights)


def org_invitation_url(org: str) -> str:
    """Page where an invited account accepts the invitation of the org."""
    return f"https://github.com/orgs/{org}/invitation"


def org_people_url(org: str) -> str:
    """People page of the org, where a member makes its own membership public."""
    return f"https://github.com/orgs/{org}/people"


def token_requests_url(org: str) -> str:
    """Org settings page where an owner approves the fine-grained PAT requests of members (never automated: it would
    need the App permission organization_personal_access_token_requests, and the App key reaches untrusted lanes)."""
    return f"https://github.com/organizations/{org}/settings/personal-access-token-requests"


class Bootstrap:
    """SPEC 16 bootstrap, ordered and idempotent: verify -> marker -> identities -> repos -> lease -> template ->
    baseline reset -> push baseline -> App checks and delivery probe. Without ``apply`` it only reports. With ``wait``
    (and apply) it waits for the invitations to be accepted and for the App installation instead of stopping or
    reporting them as manual steps; a timeout or Ctrl-C stops it, and running it again resumes."""

    def __init__(
        self,
        context: E2EContext,
        *,
        apply: bool,
        confirm: Callable[[str], str],
        sleep: Callable[[float], None] = time.sleep,
        probe_timeout: float = DELIVERY_PROBE_TIMEOUT,
        wait: bool = False,
        wait_timeout: float = BOOTSTRAP_WAIT_TIMEOUT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind the steps to a context; ``confirm(prompt)`` returns what the operator typed; ``sleep`` and ``clock``
        drive the waits."""
        self.ctx = context
        self.apply = apply
        self.confirm = confirm
        self.sleep = sleep
        self.probe_timeout = probe_timeout
        self.wait = wait
        self.wait_timeout = wait_timeout
        self.clock = clock
        self._reader: Oracle | None = None

    def step(self, text: str) -> None:
        """Report one step."""
        _echo(f"[bootstrap] {text}")

    def reader(self) -> Oracle:
        """Oracle on the ADMIN client for bootstrap's own reads: a separate oracle account may not be an owner (not
        even a member) of the org yet, the admin is one (identities step)."""
        if self._reader is None:
            from otterdog_e2e.github.oracle import Oracle

            self._reader = Oracle(self.ctx.http("admin"), self.ctx.require_target().org)
        return self._reader

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
        """verify_target without the marker (identities isolated); a fine-grained token of author, approver or the
        oracle that cannot prove its isolation yet gets the steps GitHub requires first."""
        from otterdog_e2e.safety import SafetyError

        target = self.ctx.load_target()
        try:
            verified = self.ctx.verify(require_marker=False, check_identities=True)
        except SafetyError as exc:
            hint = self._fine_grained_hint(target, str(exc))
            if not hint:
                raise
            raise click.ClickException(f"{describe_error(exc)}\n{hint}") from exc
        self.step(f"verified {verified.login} (id {verified.org_id}, plan {verified.plan})")
        return verified

    def _fine_grained_hint(self, target: Target, message: str) -> str:
        """Why a fine-grained token of author/approver/oracle fails its isolation proof (verify_target names the role
        first) and what to do: such a token only works once its account is an active member (owner for the oracle)
        and, for members, once an org owner approved its request; "" for any other error."""
        refused = ("fine-grained token cannot read", "expected an active membership")
        for name in (*BOOTSTRAP_MEMBERS, "oracle"):
            if not message.startswith(f"{name}: ") or not any(text in message for text in refused):
                continue
            if not self._fine_grained(name):
                return ""
            login = _declared_login(target, name) or name
            spec = target.identities.get(name)
            token_env = (spec.token_env if spec is not None else None) or "its token"
            if name == "oracle":  # bootstrap never invites an oracle whose own token does not prove its login
                return (
                    f"a fine-grained token of oracle {login} only works once {login} is an active org owner; if it is "
                    f"not a member yet, invite {login} as an Owner at {org_people_url(target.org)} (Invite member) or "
                    f"with `otterdog-e2e setup --target {target.name}`, accept the invitation at "
                    f"{org_invitation_url(target.org)} logged in as {login}, then run bootstrap again"
                )
            needs = (
                f"an active member of {target.org} and an org owner approved its request (when the org requires "
                f"it) at {token_requests_url(target.org)}"
            )
            return (
                f"a fine-grained token of {name} {login} only works once {login} is {needs}; if it is not a member "
                f"yet, unset {token_env}, run bootstrap --apply (it invites {login}), accept the invitation at "
                f"{org_invitation_url(target.org)}, then set the token again"
            )
        return ""

    def _fine_grained(self, name: str) -> bool:
        """True when the identity's token is declared or shaped (github_pat_) as a fine-grained PAT."""
        from otterdog_e2e.safety import FINE_GRAINED, FINE_GRAINED_PREFIX

        identity = self.ctx.identities.get(name)
        return identity is not None and (
            identity.token_type == FINE_GRAINED or identity.token.startswith(FINE_GRAINED_PREFIX)
        )

    def _own_token(self, name: str) -> bool:
        """True when the identity has a token of its own (the oracle falls back to the admin token)."""
        identity, admin = self.ctx.identities.get(name), self.ctx.identities.get("admin")
        return identity is not None and (admin is None or identity.token != admin.token)

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
            r["name"] for r in self.reader().repos() if r.get("name") not in protected and not is_e2e_name(r["name"])
        )
        if foreign:
            raise click.ClickException(
                f"the org has repositories the harness does not manage: {', '.join(foreign[:10])}"
            )

    def _foreign_members(self, target: Target) -> list[str]:
        """Org members that are not declared identities."""
        declared = {spec.login.lower() for spec in target.identities.values() if spec.login}
        return sorted(login for login in self.reader().members() if login.lower() not in declared)

    def identities(self) -> None:
        """The admin is an active owner; author/approver: invite (admin), then accept and publicize with the identity's
        own token when it may (the allowed scopes, public_repo + read:org, usually cannot: the step is then reported as
        manual with the URLs and bootstrap goes on, F4); a separate oracle account whose own token proves its login
        (_oracle_login): invited as an OWNER, an active member promoted, never demoted (GH-10); outsider not a member.
        With ``wait`` (and apply) the pending invitations are awaited."""
        target = self.ctx.require_target()
        self._admin_owner(target)
        members = {name: login for name in BOOTSTRAP_MEMBERS if (login := _declared_login(target, name))}
        oracle = self._oracle_login(target)
        invited = {name: self._invite(login) for name, login in members.items()}  # every invitation first
        if oracle:
            invited["oracle"] = self._invite(oracle, role="admin")
        pending = {
            name: login
            for name, login in members.items()
            if not self._accept_and_publicize(target, name, login, (invited[name] or {}).get("state"))
        }
        if oracle and not self._accept_oracle(target, oracle, invited["oracle"]):
            pending["oracle"] = oracle
        self._check_outsider(target)
        if pending and self.wait and self.apply:
            self.wait_for_memberships(target, pending)
        elif pending and self.apply:
            names = ", ".join(f"{name} {login}" for name, login in pending.items())
            self.step(f"memberships left to the web UI: {names} (--wait waits for them)")
        if oracle:
            self._oracle_owner(target, oracle)

    def _admin_owner(self, target: Target) -> None:
        """The admin is an active org owner (GET /user/memberships/orgs/{org}): it invites, marks and resets."""
        login = _declared_login(target, "admin") or "admin"
        response = self.ctx.http("admin").request("GET", f"/user/memberships/orgs/{target.org}", allow=(403, 404))
        if response.status_code == 403:
            self.step(f"admin {login}: its membership is not readable (403); it must be an org owner")
            return
        body = response.json() if response.status_code == 200 and response.content else {}
        state, role = (body.get("state"), body.get("role")) if isinstance(body, dict) else (None, None)
        if state != "active" or role != "admin":
            raise click.ClickException(
                f"the admin {login} is not an active owner of {target.org} (state {state or 'none'}, role "
                f"{role or 'none'}): make it an org owner ({org_people_url(target.org)}), then run bootstrap again"
            )
        self.step(f"admin {login}: active, owner")

    def _oracle_login(self, target: Target) -> str | None:
        """Login of a separate oracle account that bootstrap may make an org OWNER: declared, distinct from the admin's,
        with a token of its own whose GET /user login is the declared one; None otherwise (reported: a declared login
        alone proves nothing, it could name any account, the author's included)."""
        from otterdog_e2e.github.http import GitHubError

        login, admin = _declared_login(target, "oracle"), _declared_login(target, "admin")
        if not login or (admin is not None and login.lower() == admin.lower()):
            return None
        spec = target.identities.get("oracle")
        token_env = (spec.token_env if spec is not None else None) or "its token"
        skipped = "not invited nor promoted to org owner"
        if not self._own_token("oracle"):
            self.step(
                f"oracle {login}: no token of its own ({token_env}), the admin serves as oracle: {skipped}; set"
                f" {token_env} to the token of {login} to make it an owner"
            )
            return None
        try:
            actual = str((self.ctx.http("oracle").get("/user") or {}).get("login") or "")
        except GitHubError as exc:
            self.step(f"oracle {login}: GET /user with its token failed ({exc.status}): {skipped}")
            return None
        if actual.lower() != login.lower():
            self.step(
                f"oracle {login}: {token_env} is the token of {actual or 'an unknown account'!r}, not of {login}:"
                f" {skipped}; use the token of the declared machine account"
            )
            return None
        return login

    def _invite(self, login: str, *, role: str = "member") -> dict[str, Any] | None:
        """Invite one identity with ``role`` when it is not a member (with apply); returns its membership (None:
        none). An existing membership is never changed here."""
        membership = self.reader().membership(login)
        if membership is None and self.apply:
            self.ctx.mutator().ensure_membership(login, role=role)
            return {"state": "pending", "role": role}
        return membership

    def _manual(self, target: Target, login: str, state: str | None, *, publicize: bool = True) -> str:
        """The web-UI steps left to ``login``: accept the invitation (unless active), make the membership public."""
        steps = [] if state == "active" else [f"accept the invitation at {org_invitation_url(target.org)}"]
        if publicize:
            steps.append(f"make the membership public at {org_people_url(target.org)}")
        return f"{' and '.join(steps)} in the web UI, logged in as {login}"

    def _accept_and_publicize(self, target: Target, name: str, login: str, state: str | None) -> bool:
        """One identity active and public in the org (True when it is); a refusal of the identity's own token (403/404:
        read:org cannot write memberships, a fine-grained token may await an owner's approval) becomes a manual step
        with the URLs instead of stopping bootstrap."""
        from otterdog_e2e.github.http import GitHubError

        public = state == "active" and _public_member(self.ctx, target.org, login)
        if public:
            self.step(f"{name} {login}: active, public")
            return True
        if not self.apply:
            self.step(f"{name} {login}: would invite, accept and publicize the membership (state {state or 'none'})")
            return False
        if not self._own_token(name):
            done = "invited" if state == "pending" else f"state {state}"
            self.step(f"{name} {login}: {done}; {self._manual(target, login, state)} (no token)")
            return False
        own = self.ctx.http(name, write=True)
        try:
            if state == "pending":
                own.patch(f"/user/memberships/orgs/{target.org}", json={"state": "active"})
                state = "active"
            own.put(f"/orgs/{target.org}/public_members/{login}")
        except GitHubError as exc:
            if exc.status not in (403, 404):
                raise
            manual = self._manual(target, login, state)
            self.step(f"{name} {login}: the token may not change its membership ({exc.status}): {manual}")
            if self._fine_grained(name):
                self.step(
                    f"{name} {login}: a fine-grained token of a member needs an org owner's approval when the org "
                    f"requires it: approve its request at {token_requests_url(target.org)}"
                )
            return False
        self.step(f"{name} {login}: active, public")
        return True

    def _accept_oracle(self, target: Target, login: str, membership: Mapping[str, Any] | None) -> bool:
        """The separate oracle account active in the org (True when it is): its own token accepts the invitation when
        it may, else a manual step with the URL. The owner role is settled by _oracle_owner."""
        from otterdog_e2e.github.http import GitHubError

        state, role = (membership or {}).get("state"), (membership or {}).get("role")
        if state == "active":
            return True
        if not self.apply:
            action = "invite it as an org owner" if state is None else "accept its invitation"
            self.step(f"oracle {login}: would {action} (state {state or 'none'}, role {role or 'none'})")
            return False
        manual = self._manual(target, login, state, publicize=False)
        if not self._own_token("oracle"):
            self.step(f"oracle {login}: invited (role {role}); {manual} (no token)")
            return False
        try:
            self.ctx.http("oracle", write=True).patch(f"/user/memberships/orgs/{target.org}", json={"state": "active"})
        except GitHubError as exc:
            if exc.status not in (403, 404):
                raise
            self.step(f"oracle {login}: invited (role {role}); the token may not accept it ({exc.status}): {manual}")
            return False
        self.step(f"oracle {login}: invitation accepted")
        return True

    def _oracle_owner(self, target: Target, login: str) -> None:
        """A separate oracle must be an org owner (GH-10): an active member is promoted with apply (never demoted).
        With apply and the oracle's own token in use, bootstrap stops while it is not an active owner: the next
        steps read the org through it."""
        membership = self.reader().membership(login) or {}
        state, role = membership.get("state"), membership.get("role")
        if state == "active" and role == "admin":
            self.step(f"oracle {login}: active, owner")
        elif state == "active" and not self.apply:
            self.step(f"oracle {login}: active member, not an owner: would promote it to org owner")
        elif state == "active":
            self.ctx.mutator().ensure_membership(login, role="admin")
            self.step(f"oracle {login}: promoted to org owner")
        elif self.apply and self._own_token("oracle"):
            raise click.ClickException(
                f"the oracle {login} is not an active owner of {target.org} yet (state {state or 'none'}): "
                f"{self._manual(target, login, state, publicize=False)}, then run bootstrap again (--wait waits for "
                "it); the next steps read the org through the oracle"
            )

    def _check_outsider(self, target: Target) -> None:
        """The outsider is not a member of the org (nor invited)."""
        outsider = _declared_login(target, "outsider")
        if outsider and self.reader().membership(outsider) is not None:
            raise click.ClickException(f"the outsider {outsider} is a member of the org: remove it first")

    def wait_for_memberships(self, target: Target, pending: Mapping[str, str]) -> None:
        """--wait: poll until every pending identity is active (author and approver also public) and the outsider is
        still not a member; a change of state is printed once."""
        seen: dict[str, str] = {}

        def ready() -> bool:
            """One poll of the pending identities (changes printed); True when every one is ready."""
            done = True
            for name, login in pending.items():
                status, ok = self._membership_status(target, name, login)
                if name in seen and seen[name] != status:
                    self.step(f"{name} {login}: {status}")
                seen[name] = status
                done = done and ok
            self._check_outsider(target)
            return done

        names = ", ".join(f"{name} {login}" for name, login in pending.items())
        self._wait(f"the memberships of {names}", ready)
        self.step(f"memberships ready: {names}")

    def _membership_status(self, target: Target, name: str, login: str) -> tuple[str, bool]:
        """(state shown, ready) of one identity: active and public for author/approver, active for the oracle."""
        state = (self.reader().membership(login) or {}).get("state")
        if state != "active":
            return ("invitation pending" if state == "pending" else "not a member"), False
        if name == "oracle":
            return "active", True
        public = _public_member(self.ctx, target.org, login)
        return ("active, public" if public else "active, private"), public

    def _wait(self, what: str, condition: Callable[[], Any]) -> Any:
        """wait_until(condition) every BOOTSTRAP_WAIT_INTERVAL s for at most ``wait_timeout`` s; a timeout or Ctrl-C
        stops bootstrap with how to resume (run it again: every step is idempotent)."""
        from otterdog_e2e.waiting import WaitTimeoutError, wait_until

        name = self.ctx.require_target().name
        again = f"run `otterdog-e2e bootstrap --target {name} --apply --wait` again (every step is idempotent)"
        self.step(
            f"waiting up to {self.wait_timeout:g} s for {what} (every {BOOTSTRAP_WAIT_INTERVAL:g} s; Ctrl-C stops)"
        )
        try:
            return wait_until(
                condition,
                timeout=self.wait_timeout,
                interval=BOOTSTRAP_WAIT_INTERVAL,
                what=what,
                sleep=self.sleep,
                clock=self.clock,
            )
        except WaitTimeoutError as exc:
            raise click.ClickException(f"{what}: not done within {self.wait_timeout:g} s: {again}") from exc
        except KeyboardInterrupt:
            raise click.ClickException(f"interrupted while waiting for {what}: {again}") from None

    def repos(self) -> None:
        """The configs and defaults repositories exist (public, auto-initialized)."""
        target = self.ctx.require_target()
        purposes = {
            target.configs_repo: "webapp otterdog.json, org lease and run ledger",
            target.defaults_repo: "published templates",
        }
        for name, purpose in purposes.items():
            if self.reader().repo(name) is not None:
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
        self.step(f"App installation {self.installation()} ready")
        self.delivery_probe()

    def installation(self) -> int:
        """Installation id of the App on the org (installation_id: verify_app and the GH-09 preflight). An App not
        installed yet (verified first: no installation link for an App that could reach other orgs): its installation
        URL is printed and, with ``wait``, GET /orgs/{org}/installation is polled until it is installed; without
        ``wait`` bootstrap stops (run it again once installed)."""
        from otterdog_e2e.appmanifest import installation_url

        target = self.ctx.require_target()
        isolation = self.ctx.verify_app()
        app = self.ctx.app_auth()
        if app.installation_for_org(target.org) is None:
            declared = target.app.slug if target.app is not None else None
            slug = declared or self.ctx.require_app_credentials().slug or isolation.slug  # isolation: GET /app
            install = (
                f"install the GitHub App {slug} on {target.org} for All repositories: "
                f"{installation_url(slug, target.org_id)}"
            )
            if not self.wait:
                raise click.ClickException(
                    f"the GitHub App is not installed on the org: {install}, then run bootstrap again (--wait waits)"
                )
            self.step(f"App not installed: {install}")
            self._wait(f"the installation of the GitHub App {slug}", lambda: app.installation_for_org(target.org))
            self.step(f"App {slug} installed on {target.org}")
        try:
            return self.ctx.installation_id()
        except ContextError as exc:
            raise click.ClickException(str(exc)) from exc

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
@click.option(
    "--wait",
    is_flag=True,
    help="with --apply: wait until the invited accounts are active and public members and the App is installed",
)
@click.option("--wait-timeout", default="30m", show_default=True, help="how long --wait waits (90s, 10m, 1h)")
@_handled
def bootstrap(target: str, apply_: bool, wait: bool, wait_timeout: str) -> None:
    """Prepare a test org idempotently: marker, identities, repos, lease, template, baseline, App checks.

    The web-UI steps GitHub does not allow to automate (accepting an invitation, making a membership public,
    installing the App, approving a member's fine-grained token) are printed with their URLs; --wait polls until the
    memberships are active and public and the App is installed.
    """
    try:
        timeout = parse_duration(wait_timeout).total_seconds()
    except ValueError as exc:
        raise click.UsageError(f"--wait-timeout: {exc}") from None
    if wait and not apply_:
        raise click.UsageError("--wait needs --apply (a dry run invites nobody and waits for nothing)")
    with _session(target) as context:
        Bootstrap(
            context,
            apply=apply_,
            confirm=lambda prompt: str(click.prompt(prompt)),
            wait=wait,
            wait_timeout=timeout,
        ).run()
