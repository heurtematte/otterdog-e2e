"""Harness CLI operations: bootstrap, janitor, relay, report, scrub-artifacts, cache prune, app-manifest, sut."""

from __future__ import annotations

import json
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import click
import pytest
import requests
from click.testing import CliRunner

from otterdog_e2e import cli
from otterdog_e2e.context import E2EContext, E2EOptions
from otterdog_e2e.github.janitor import JanitorItem
from otterdog_e2e.redact import Redactor
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import AppCredentials, Identity, IdentitySpec, Target
from otterdog_e2e.testing.fakes import (
    FAKE_MARKER,
    FAKE_ORG,
    FAKE_ORG_ID,
    FAKE_RUN_ID,
    FakeAppAuth,
    FakeBaselineManager,
    FakeCli,
    FakeGitHubHttp,
    FakeLease,
    FakeOracle,
    HttpCall,
    RecordingMutator,
    fake_sha,
    fake_token,
    make_identities,
    make_settings,
    make_target,
    make_verified_org,
)

OTHER_RUN = "t3c7z8b6"
ADMIN_MEMBERSHIP = {"state": "active", "role": "admin", "user": {"login": "e2e-admin"}}
INVITATION_URL = f"https://github.com/orgs/{FAKE_ORG}/invitation"
PEOPLE_URL = f"https://github.com/orgs/{FAKE_ORG}/people"
TOKEN_REQUESTS_URL = f"https://github.com/organizations/{FAKE_ORG}/settings/personal-access-token-requests"
INSTALL_URL = f"https://github.com/apps/otterdog-e2e-test/installations/new/permissions?target_id={FAKE_ORG_ID}"


@dataclass
class Org:
    """The fake org seen by a command."""

    target: Target = field(default_factory=make_target)
    identities: dict[str, Any] = field(default_factory=lambda: make_identities("admin", "author", "approver"))
    oracle: FakeOracle = field(default_factory=FakeOracle)
    app: FakeAppAuth = field(default_factory=FakeAppAuth)
    lease: FakeLease = field(default_factory=FakeLease)
    mutators: dict[str, RecordingMutator] = field(default_factory=dict)
    https: dict[str, FakeGitHubHttp] = field(default_factory=dict)
    app_credentials: AppCredentials | None = None


@pytest.fixture
def org(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Org:
    """A fake org (description without marker), identities, App and lease; every collaborator patched."""
    state = Org()
    state.oracle.set("org", value={**state.oracle.org(), "description": "e2e scratch org"})
    state.app_credentials = AppCredentials(
        "1", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----", "hook-s3cret", None
    )

    def http(token: str | None, **kwargs: Any) -> FakeGitHubHttp:
        """One shared fake client per identity."""
        name = kwargs.get("identity", "anonymous")
        if name not in state.https:
            client = FakeGitHubHttp(identity=name, strict=False)
            client.add("GET", f"/orgs/{FAKE_ORG}/public_members/*", status=404, repeat=True)
            client.add("PATCH", f"/user/memberships/orgs/{FAKE_ORG}", json={"state": "active"}, repeat=True)
            client.add("PUT", f"/orgs/{FAKE_ORG}/public_members/*", status=204, repeat=True)
            if name == "admin":
                client.add("GET", f"/user/memberships/orgs/{FAKE_ORG}", json=ADMIN_MEMBERSHIP, repeat=True)
            identity = state.identities.get(name)
            if identity is not None and identity.login:  # GET /user: the account of the token
                client.add("GET", "/user", json={"login": identity.login}, repeat=True)
            state.https[name] = client
        return state.https[name]

    def verify(admin_http: Any, target: Any, identities: Any, *, require_marker: bool = True, **kwargs: Any) -> Any:
        """VerifiedOrg of the oracle's org; SafetyError when the marker is required and missing."""
        org_json = state.oracle.org()
        if require_marker and FAKE_MARKER not in (org_json.get("description") or ""):
            raise SafetyError("marker missing")
        return make_verified_org(org_json=org_json)

    def mutator(client: Any, verified: Any, **kwargs: Any) -> RecordingMutator:
        """RecordingMutator per identity, updating the oracle."""
        return state.mutators.setdefault(client.identity, RecordingMutator(verified, oracle=state.oracle))

    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path))
    monkeypatch.setattr("otterdog_e2e.settings.load_env_files", lambda *a, **k: [])
    monkeypatch.setattr("otterdog_e2e.settings.load_target", lambda *a, **k: state.target)
    monkeypatch.setattr("otterdog_e2e.settings.resolve_identities", lambda *a, **k: dict(state.identities))
    monkeypatch.setattr("otterdog_e2e.settings.resolve_app_credentials", lambda *a, **k: state.app_credentials)
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", http)
    monkeypatch.setattr("otterdog_e2e.safety.verify_target", verify)
    monkeypatch.setattr("otterdog_e2e.github.oracle.Oracle", lambda client, login: state.oracle)
    monkeypatch.setattr("otterdog_e2e.github.mutate.Mutator", mutator)
    monkeypatch.setattr("otterdog_e2e.github.lease.OrgLease", lambda *a, **k: state.lease)
    monkeypatch.setattr("otterdog_e2e.github.app.AppAuth", lambda creds, **kw: state.app)
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *a: None)
    monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor=None: [])
    for name in ("CI", "GITHUB_ACTIONS", "E2E_LEASE_WAIT"):
        monkeypatch.delenv(name, raising=False)
    return state


def admin_calls(org: Org, method: str) -> list[Any]:
    """Recorded calls of the admin mutator."""
    mutator = org.mutators.get("admin")
    return mutator.calls_to(method) if mutator else []


# --- bootstrap ------------------------------------------------------------------------------------------------------
def test_bootstrap_dry_run_changes_nothing(org: Org) -> None:
    """Without --apply: only reports (marker, memberships, repos), never mutates nor takes the lease."""
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake"])
    assert result.exit_code == 0, result.output
    assert "would add the safety marker" in result.output
    assert "author e2e-author: would invite" in result.output
    assert "would create the public repo otterdog-e2e-configs" in result.output
    assert "dry run" in result.output
    assert all(not mutator.calls for mutator in org.mutators.values()) and "acquire" not in org.lease.calls


def test_bootstrap_marker_refused_in_ci(org: Org, monkeypatch: pytest.MonkeyPatch) -> None:
    """The marker is never written when CI is set."""
    monkeypatch.setenv("CI", "true")
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", "--apply"])
    assert result.exit_code == 1 and "refusing to write the safety marker" in result.output
    assert not admin_calls(org, "set_org_description")


def test_bootstrap_marker_needs_the_typed_login(org: Org) -> None:
    """A wrong confirmation changes nothing."""
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", "--apply"], input="eclipse\n")
    assert result.exit_code == 1 and "does not match" in result.output
    assert not admin_calls(org, "set_org_description")


def test_bootstrap_refuses_orgs_with_foreign_repos(org: Org) -> None:
    """An org holding unmanaged repositories is never marked (protects real orgs)."""
    org.oracle.add_repo("production-service")
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", "--apply"], input=f"{FAKE_ORG}\n")
    assert result.exit_code == 1 and "production-service" in result.output


@pytest.fixture
def heavy(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake template, probes, reset CLI, renderer, baseline and otterdog.json publishing."""
    state: dict[str, Any] = {"baseline": FakeBaselineManager(), "published": []}
    monkeypatch.setattr(E2EContext, "template_for", lambda self, role: SimpleNamespace(url=f"template-of-{role}"))
    monkeypatch.setattr(E2EContext, "probe", lambda self: None)
    monkeypatch.setattr(E2EContext, "installed", lambda self, role: SimpleNamespace(role=role))
    monkeypatch.setattr(E2EContext, "workspace", lambda self, name, template: SimpleNamespace(name=name))
    monkeypatch.setattr(E2EContext, "cli", lambda self, installed, workspace, **kw: FakeCli())
    monkeypatch.setattr(E2EContext, "renderer", lambda self, template: SimpleNamespace(template=template))
    monkeypatch.setattr(E2EContext, "baseline_manager", lambda self, reset_cli, renderer: state["baseline"])
    monkeypatch.setattr(E2EContext, "publish_otterdog_json", lambda self, template: state["published"].append(template))
    return state


class Clock:
    """Monotonic clock of the bootstrap waits, advanced by its own sleep; ``on_sleep(count)`` runs after each sleep."""

    def __init__(self, on_sleep: Callable[[int], None] | None = None) -> None:
        """Start at 0 s."""
        self.now = 0.0
        self.sleeps: list[float] = []
        self.on_sleep = on_sleep

    def __call__(self) -> float:
        """The current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the clock, then run the hook."""
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep is not None:
            self.on_sleep(len(self.sleeps))


def bootstrap(org: Org, *, confirm: str = FAKE_ORG, clock: Clock | None = None, **options: Any) -> list[str]:
    """Run Bootstrap(apply) on a fresh context; returns the prompts shown."""
    prompts: list[str] = []
    clock = clock or Clock()
    context = E2EContext.create(E2EOptions(target="fake", run_id=FAKE_RUN_ID), environ={})
    cli.Bootstrap(
        context,
        apply=True,
        confirm=lambda text: prompts.append(text) or confirm,
        sleep=clock.sleep,
        clock=clock,
        **options,
    ).run()
    return prompts


def verified_steps(org: Org, *, apply: bool = True, clock: Clock | None = None, **options: Any) -> cli.Bootstrap:
    """A Bootstrap on a fresh context after its verify step (its waits driven by ``clock``)."""
    clock = clock or Clock()
    context = E2EContext.create(E2EOptions(target="fake", run_id=FAKE_RUN_ID), environ={})
    runner = cli.Bootstrap(
        context, apply=apply, confirm=lambda text: FAKE_ORG, sleep=clock.sleep, clock=clock, **options
    )
    runner.verify()
    return runner


def admin_http(public: set[str], membership: dict[str, Any] | None = None) -> FakeGitHubHttp:
    """Admin client: its own membership (an active owner by default); GET public_members answers 204 for the logins
    in ``public`` (read on every request), 404 otherwise."""
    client = FakeGitHubHttp(identity="admin", strict=False)
    client.add("GET", f"/user/memberships/orgs/{FAKE_ORG}", json=membership or ADMIN_MEMBERSHIP, repeat=True)
    client.add(
        "GET",
        f"/orgs/{FAKE_ORG}/public_members/*",
        repeat=True,
        responder=lambda call: (204 if call.path.rsplit("/", 1)[1] in public else 404, None),
    )
    return client


def refusing(identity: str, status: int = 403) -> FakeGitHubHttp:
    """Client of an identity (account e2e-<identity>) whose token may neither accept an invitation nor publicize its
    membership."""
    client = FakeGitHubHttp(identity=identity, strict=False)
    client.add("GET", "/user", json={"login": f"e2e-{identity}"}, repeat=True)
    for method, path in (
        ("PATCH", f"/user/memberships/orgs/{FAKE_ORG}"),
        ("PUT", f"/orgs/{FAKE_ORG}/public_members/*"),
    ):
        client.add(method, path, status=status, json={"message": "Resource not accessible"}, repeat=True)
    return client


def with_oracle(org: Org, login: str = "e2e-oracle", *, token: bool = True) -> None:
    """Declare a separate oracle account (E2E_ORACLE_LOGIN), with a token of its own unless ``token`` is False."""
    oracle = IdentitySpec("oracle", login, "E2E_ORACLE_TOKEN")
    org.target = make_target(identities={**org.target.identities, "oracle": oracle})
    if token:
        org.identities["oracle"] = Identity("oracle", login, fake_token("oracle"))


def ready_org(org: Org) -> None:
    """Marker present, author/approver active members, configs and defaults repos: bootstrap reaches the App steps."""
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    for name in ("author", "approver"):
        org.oracle.set("membership", f"e2e-{name}", value={"state": "active"})
    for repo in ("otterdog-e2e-configs", "otterdog-e2e-defaults"):
        org.oracle.add_repo(repo)
    org.oracle.set("branch_sha", "otterdog-e2e-configs", "main", value=fake_sha("main"))


def test_bootstrap_apply_runs_every_step(org: Org, heavy: dict[str, Any]) -> None:
    """marker -> identities -> repos -> lease -> template -> reset -> App otterdog.json, preflight, delivery probe."""
    org.oracle.set("members", value=["e2e-admin", "human-owner"])
    org.oracle.add_repo("otterdog-e2e-configs")
    org.oracle.set("branch_sha", "otterdog-e2e-configs", "main", value=fake_sha("main"))
    org.oracle.set("membership", "e2e-approver", value={"state": "active"})
    org.https.clear()
    branch = f"e2e/{FAKE_RUN_ID}/bootstrap"
    org.app.add_delivery("push", {"ref": f"refs/heads/{branch}", "organization": {"login": FAKE_ORG}})
    prompts = bootstrap(org)
    assert "human-owner" in prompts[0] and FAKE_ORG in prompts[0]
    [(description,)] = [call.args for call in admin_calls(org, "set_org_description")]
    assert description == f"{FAKE_MARKER} e2e scratch org"
    assert [call.args for call in admin_calls(org, "ensure_membership")] == [("e2e-author",)]
    author_http, approver_http = org.https["author"], org.https["approver"]
    assert author_http.calls_to("PATCH", f"/user/memberships/orgs/{FAKE_ORG}")
    assert author_http.calls_to("PUT", f"/orgs/{FAKE_ORG}/public_members/e2e-author")
    assert not approver_http.calls_to("PATCH")  # already active: only publicized
    assert approver_http.calls_to("PUT", f"/orgs/{FAKE_ORG}/public_members/e2e-approver")
    assert [call.args for call in admin_calls(org, "create_repo")] == [("otterdog-e2e-defaults",)]
    assert org.lease.held and org.lease.heartbeat
    assert heavy["baseline"].calls_to("reset") and heavy["published"]
    assert [call.args[1] for call in admin_calls(org, "create_branch")] == [branch]
    assert [call.args for call in admin_calls(org, "delete_ref")] == [("otterdog-e2e-configs", f"heads/{branch}")]


def test_bootstrap_reports_refused_membership_writes_as_manual_steps(
    org: Org, heavy: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """F4: the identities' tokens (public_repo + read:org) may not accept or publicize a membership: a 403/404 of
    their own PATCH/PUT is reported as a manual step, every identity is invited first and bootstrap goes on (repos,
    lease, baseline reset, App)."""
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    org.oracle.add_repo("otterdog-e2e-configs")
    org.oracle.set("branch_sha", "otterdog-e2e-configs", "main", value=fake_sha("main"))
    refused = FakeGitHubHttp(identity="author", strict=False)
    refused.add("GET", f"/orgs/{FAKE_ORG}/public_members/*", status=404, repeat=True)
    refused.add("PATCH", f"/user/memberships/orgs/{FAKE_ORG}", status=403, json={"message": "no"}, repeat=True)
    refused.add("PUT", f"/orgs/{FAKE_ORG}/public_members/*", status=404, json={"message": "no"}, repeat=True)
    org.https["author"] = refused
    branch = f"e2e/{FAKE_RUN_ID}/bootstrap"
    org.app.add_delivery("push", {"ref": f"refs/heads/{branch}", "organization": {"login": FAKE_ORG}})
    clock = Clock()
    bootstrap(org, clock=clock)
    output = capsys.readouterr().out
    assert (
        "author e2e-author: the token may not change its membership (403): accept the invitation at "
        f"{INVITATION_URL} and make the membership public at {PEOPLE_URL} in the web UI, logged in as e2e-author"
    ) in output
    invited = [call.args for call in admin_calls(org, "ensure_membership")]
    assert invited == [("e2e-author",), ("e2e-approver",)]  # both invited before any acceptance
    assert org.lease.held and heavy["baseline"].calls_to("reset") and heavy["published"]
    # without --wait nothing is awaited; a classic token gets no approval hint
    assert "memberships left to the web UI: author e2e-author (--wait waits for them)" in output
    assert "waiting up to" not in output and not clock.sleeps and TOKEN_REQUESTS_URL not in output


def test_the_delivery_probe_waits_as_long_as_every_delivery_wait() -> None:
    """F6: GitHub lists deliveries minutes late: bootstrap's probe gets the 300 s of the other delivery waits."""
    import inspect

    from otterdog_e2e.config_repo import ConfigRepoFlow

    flow_default = inspect.signature(ConfigRepoFlow).parameters["delivery_timeout"].default
    assert cli.DELIVERY_PROBE_TIMEOUT == flow_default == 300


def test_bootstrap_delivery_probe_timeout(org: Org, heavy: dict[str, Any]) -> None:
    """No push delivery: the probe fails with the webhook hint and still deletes its branch."""
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    for name in ("author", "approver"):
        org.oracle.set("membership", f"e2e-{name}", value={"state": "active"})
    for repo in ("otterdog-e2e-configs", "otterdog-e2e-defaults"):
        org.oracle.add_repo(repo)
    org.oracle.set("branch_sha", "otterdog-e2e-configs", "main", value=fake_sha("main"))
    context = E2EContext.create(E2EOptions(target="fake", run_id=FAKE_RUN_ID), environ={})
    runner = cli.Bootstrap(context, apply=True, confirm=lambda text: "", sleep=lambda s: None, probe_timeout=0)
    with pytest.raises(click.ClickException, match=r"no push delivery.*minutes late"):
        runner.run()
    assert admin_calls(org, "delete_ref")


def test_bootstrap_pushes_a_fixed_org_config_repo(
    org: Org, heavy: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """With a fixed org_config_repo the baseline is pushed through a ConfigRepoFlow."""
    org.target = make_target(org_config_repo=".otterdog")
    org.app_credentials = None
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    for repo in ("otterdog-e2e-configs", "otterdog-e2e-defaults"):
        org.oracle.add_repo(repo)
    for name in ("author", "approver"):
        org.oracle.set("membership", f"e2e-{name}", value={"state": "active"})
    flows: list[Any] = []
    monkeypatch.setattr(
        E2EContext,
        "config_flow",
        lambda self, baseline, **kw: (
            flows.append(baseline) or SimpleNamespace(reset_main=lambda text, message: fake_sha(text))
        ),
    )
    bootstrap(org)
    assert heavy["baseline"].calls_to("push") and flows == [heavy["baseline"]] and not heavy["published"]


def test_bootstrap_requires_the_admin_to_be_an_owner(org: Org, capsys: pytest.CaptureFixture[str]) -> None:
    """The admin invites, marks and resets: a non-owner or pending admin stops bootstrap (People page in the message),
    even in a dry run; an unreadable own membership (403) is only reported."""
    for membership in ({"state": "active", "role": "member"}, {"state": "pending", "role": "admin"}):
        org.https["admin"] = admin_http(set(), membership)
        with pytest.raises(
            click.ClickException, match=r"admin e2e-admin is not an active owner of e2e-test-org"
        ) as exc:
            verified_steps(org).identities()
        assert PEOPLE_URL in str(exc.value) and f"state {membership['state']}, role {membership['role']}" in str(
            exc.value
        )
        result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake"])
        assert result.exit_code == 1 and "is not an active owner" in result.output
    assert not admin_calls(org, "ensure_membership")
    forbidden = FakeGitHubHttp(identity="admin", strict=False)
    forbidden.add("GET", f"/user/memberships/orgs/{FAKE_ORG}", status=403, json={"message": "no"})
    org.https["admin"] = forbidden
    verified_steps(org, apply=False).identities()
    assert "admin e2e-admin: its membership is not readable (403); it must be an org owner" in capsys.readouterr().out


def test_bootstrap_invites_a_separate_oracle_as_owner(org: Org, capsys: pytest.CaptureFixture[str]) -> None:
    """A declared oracle account distinct from the admin is invited as an OWNER (role admin), the members as members,
    every invitation first; the oracle's own token accepts its invitation (its membership is never publicized)."""
    with_oracle(org)
    verified_steps(org, apply=False).identities()
    assert "oracle e2e-oracle: would invite it as an org owner (state none" in capsys.readouterr().out
    assert not org.mutators
    oracle_http = FakeGitHubHttp(identity="oracle", strict=False)
    oracle_http.add("GET", "/user", json={"login": "e2e-oracle"}, repeat=True)

    def accept(call: HttpCall) -> tuple[int, Any]:
        """GitHub accepts the invitation: the oracle is now an active owner."""
        org.oracle.set("membership", "e2e-oracle", value={"state": "active", "role": "admin"})
        return 200, {"state": "active"}

    oracle_http.add("PATCH", f"/user/memberships/orgs/{FAKE_ORG}", responder=accept)
    org.https["oracle"] = oracle_http
    verified_steps(org).identities()
    output = capsys.readouterr().out
    invited = [(call.args, call.kwargs) for call in admin_calls(org, "ensure_membership")]
    assert invited == [
        (("e2e-author",), {"role": "member"}),
        (("e2e-approver",), {"role": "member"}),
        (("e2e-oracle",), {"role": "admin"}),
    ]
    assert "oracle e2e-oracle: invitation accepted" in output and "oracle e2e-oracle: active, owner" in output
    assert [call.json for call in oracle_http.calls_to("PATCH")] == [{"state": "active"}]
    assert not oracle_http.calls_to("PUT")


def test_bootstrap_never_demotes_the_oracle_and_promotes_an_active_member_with_apply(
    org: Org, capsys: pytest.CaptureFixture[str]
) -> None:
    """An owner oracle is left alone; an active member oracle is reported in a dry run and promoted (PUT role admin
    through ensure_membership) with apply; author/approver memberships are never touched by the promotion."""
    with_oracle(org)
    for name in ("author", "approver"):
        org.oracle.set("membership", f"e2e-{name}", value={"state": "active", "role": "member"})
    org.oracle.set("membership", "e2e-oracle", value={"state": "active", "role": "admin"})
    verified_steps(org).identities()
    assert "oracle e2e-oracle: active, owner" in capsys.readouterr().out
    assert not admin_calls(org, "ensure_membership")
    org.oracle.set("membership", "e2e-oracle", value={"state": "active", "role": "member"})
    verified_steps(org, apply=False).identities()
    assert "oracle e2e-oracle: active member, not an owner: would promote it to org owner" in capsys.readouterr().out
    assert not admin_calls(org, "ensure_membership")
    verified_steps(org).identities()
    assert "oracle e2e-oracle: promoted to org owner" in capsys.readouterr().out
    promoted = [(call.args, call.kwargs) for call in admin_calls(org, "ensure_membership")]
    assert promoted == [(("e2e-oracle",), {"role": "admin"})]


def test_bootstrap_stops_while_a_separate_oracle_is_not_an_active_owner(
    org: Org, capsys: pytest.CaptureFixture[str]
) -> None:
    """A pending oracle is never promoted; when its token may not accept the invitation and the oracle's token is in
    use (the next steps read the org through it), bootstrap stops before the repos and the lease with the invitation
    URL. Without a token of its own the oracle is not used: bootstrap neither invites nor promotes it (reported)."""
    with_oracle(org)
    org.oracle.set("membership", "e2e-oracle", value={"state": "pending", "role": "member"})
    org.https["oracle"] = refusing("oracle")
    with pytest.raises(
        click.ClickException, match=r"oracle e2e-oracle is not an active owner of e2e-test-org yet"
    ) as exc:
        verified_steps(org).identities()
    assert INVITATION_URL in str(exc.value) and "--wait" in str(exc.value)
    assert "oracle e2e-oracle: invited (role member); the token may not accept it (403)" in capsys.readouterr().out
    assert not [call for call in admin_calls(org, "ensure_membership") if call.args == ("e2e-oracle",)]
    org.identities = make_identities("admin", "author", "approver")  # the oracle falls back to the admin token
    verified_steps(org).identities()
    output = capsys.readouterr().out
    assert (
        "oracle e2e-oracle: no token of its own (E2E_ORACLE_TOKEN), the admin serves as oracle: not invited nor "
        "promoted to org owner"
    ) in output
    assert "oracle e2e-oracle: invited" not in output


def test_bootstrap_never_makes_an_unproven_oracle_login_an_owner(org: Org, capsys: pytest.CaptureFixture[str]) -> None:
    """E2E_ORACLE_LOGIN alone proves nothing (it could name the author, a human): without a token of its own, or with
    a token of another account (GET /user), the declared oracle is neither invited as an owner nor promoted, with
    apply or not; the members are still handled."""
    for name in ("author", "approver"):
        org.oracle.set("membership", f"e2e-{name}", value={"state": "active", "role": "member"})
    with_oracle(org, "e2e-author", token=False)  # the author's login declared as oracle, no E2E_ORACLE_TOKEN
    for apply in (False, True):
        verified_steps(org, apply=apply).identities()
        output = capsys.readouterr().out
        assert "oracle e2e-author: no token of its own (E2E_ORACLE_TOKEN)" in output
        assert "oracle e2e-author: promoted" not in output and "oracle e2e-author: active member" not in output
    assert not [call for call in admin_calls(org, "ensure_membership") if call.kwargs.get("role") == "admin"]
    with_oracle(org, "e2e-oracle")
    impostor = FakeGitHubHttp(identity="oracle", strict=False)
    impostor.add("GET", "/user", json={"login": "e2e-author"}, repeat=True)  # the token of another account
    org.https["oracle"] = impostor
    org.oracle.set("membership", "e2e-oracle", value={"state": "active", "role": "member"})
    verified_steps(org).identities()
    output = capsys.readouterr().out
    assert "oracle e2e-oracle: E2E_ORACLE_TOKEN is the token of 'e2e-author', not of e2e-oracle" in output
    assert "oracle e2e-oracle: promoted" not in output
    assert not [call for call in admin_calls(org, "ensure_membership") if call.kwargs.get("role") == "admin"]
    assert not impostor.calls_to("PATCH")


def test_bootstrap_wait_polls_until_the_members_are_active_and_public(
    org: Org, capsys: pytest.CaptureFixture[str]
) -> None:
    """--wait: after the invitations the manual steps are printed once (URLs and login), then the memberships are
    polled every 10 s through the injected sleep; only the changes are printed."""
    public: set[str] = set()
    org.https["admin"] = admin_http(public)
    for name in ("author", "approver"):
        org.https[name] = refusing(name)
    timeline: dict[int, Callable[[], Any]] = {
        1: lambda: org.oracle.set("membership", "e2e-author", value={"state": "active"}),
        2: lambda: public.add("e2e-author"),
        3: lambda: (
            org.oracle.set("membership", "e2e-approver", value={"state": "active"}),
            public.add("e2e-approver"),
        ),
    }
    clock = Clock(lambda count: timeline[count]())
    verified_steps(org, clock=clock, wait=True).identities()
    output = capsys.readouterr().out
    assert clock.sleeps == [10.0, 10.0, 10.0]
    for name in ("author", "approver"):
        assert (
            f"{name} e2e-{name}: the token may not change its membership (403): accept the invitation at "
            f"{INVITATION_URL} and make the membership public at {PEOPLE_URL} in the web UI, logged in as e2e-{name}"
        ) in output
    assert output.count(INVITATION_URL) == 2  # once per identity, never repeated by the polls
    assert "waiting up to 1800 s for the memberships of author e2e-author, approver e2e-approver (every 10 s" in output
    progress = [line for line in output.splitlines() if line.endswith(("active, private", "active, public"))]
    assert progress == [
        "[bootstrap] author e2e-author: active, private",
        "[bootstrap] author e2e-author: active, public",
        "[bootstrap] approver e2e-approver: active, public",
    ]
    assert output.rstrip().endswith("memberships ready: author e2e-author, approver e2e-approver")


def test_bootstrap_wait_also_waits_for_the_oracle_then_promotes_it(
    org: Org, capsys: pytest.CaptureFixture[str]
) -> None:
    """An oracle invited as a member earlier: --wait waits until it is active (never public), then promotes it."""
    with_oracle(org)
    for name in ("author", "approver"):
        org.oracle.set("membership", f"e2e-{name}", value={"state": "active"})
    org.oracle.set("membership", "e2e-oracle", value={"state": "pending", "role": "member"})
    org.https["oracle"] = refusing("oracle")
    clock = Clock(lambda count: org.oracle.set("membership", "e2e-oracle", value={"state": "active", "role": "member"}))
    verified_steps(org, clock=clock, wait=True).identities()
    output = capsys.readouterr().out
    assert clock.sleeps == [10.0] and "[bootstrap] oracle e2e-oracle: active\n" in output
    assert "oracle e2e-oracle: promoted to org owner" in output
    assert [(call.args, call.kwargs) for call in admin_calls(org, "ensure_membership")] == [
        (("e2e-oracle",), {"role": "admin"})
    ]


def test_bootstrap_wait_timeout_and_ctrl_c_tell_to_run_it_again(org: Org, heavy: dict[str, Any]) -> None:
    """A timeout (--wait-timeout) or Ctrl-C during the wait stops bootstrap before the lease with how to resume."""
    org.https["author"] = refusing("author")
    clock = Clock()
    again = re.escape("run `otterdog-e2e bootstrap --target fake --apply --wait` again")
    with pytest.raises(click.ClickException, match=rf"author e2e-author: not done within 30 s: {again}"):
        verified_steps(org, clock=clock, wait=True, wait_timeout=30).identities()
    assert clock.sleeps == [10.0, 10.0, 10.0]

    def interrupt(count: int) -> None:
        """Ctrl-C during the first sleep."""
        raise KeyboardInterrupt

    with pytest.raises(click.ClickException, match=rf"interrupted while waiting for the memberships of .*{again}"):
        bootstrap(org, wait=True, clock=Clock(interrupt))
    assert "acquire" not in org.lease.calls and not heavy["baseline"].calls


def test_bootstrap_wait_stops_when_the_outsider_becomes_a_member(org: Org) -> None:
    """The outsider must stay outside the org while bootstrap waits for the other identities."""
    org.https["author"] = refusing("author")
    clock = Clock(lambda count: org.oracle.set("membership", "e2e-outsider", value={"state": "pending"}))
    with pytest.raises(click.ClickException, match="the outsider e2e-outsider is a member of the org"):
        verified_steps(org, clock=clock, wait=True).identities()
    assert clock.sleeps == [10.0]


def test_bootstrap_points_refused_fine_grained_member_tokens_to_the_approval_page(
    org: Org, capsys: pytest.CaptureFixture[str]
) -> None:
    """A refused member token that is fine-grained (declared, or github_pat_ shaped) may await an owner's approval:
    the token requests page is printed (bootstrap never approves it)."""
    org.identities["author"] = Identity("author", "e2e-author", fake_token("author"), "fine-grained")
    org.identities["approver"] = Identity("approver", "e2e-approver", "github_pat_" + "A1b2" * 20)
    for name in ("author", "approver"):
        org.https[name] = refusing(name)
    verified_steps(org).identities()
    output = capsys.readouterr().out
    for name in ("author", "approver"):
        assert (
            f"{name} e2e-{name}: a fine-grained token of a member needs an org owner's approval when the org requires "
            f"it: approve its request at {TOKEN_REQUESTS_URL}"
        ) in output


@pytest.mark.parametrize(
    ("role", "message", "expected"),
    [
        (
            "author",
            "author: fine-grained token cannot read GET /user/memberships/orgs/e2e-test-org (403): ...",
            ["an active member of e2e-test-org", TOKEN_REQUESTS_URL, "unset E2E_AUTHOR_TOKEN", INVITATION_URL],
        ),
        (
            "approver",
            (
                "approver: GET /user/memberships/orgs/e2e-test-org answered organization id 424242, state 'pending': "
                "expected an active membership of the test org (id 424242)"
            ),
            ["an active member of e2e-test-org", TOKEN_REQUESTS_URL, "unset E2E_APPROVER_TOKEN"],
        ),
        (
            "oracle",
            "oracle: fine-grained token cannot read GET /orgs/e2e-test-org/actions/permissions (403): ...",
            # bootstrap never invites an oracle without its own proven token: invited in the web UI or by setup
            ["is an active org owner", f"as an Owner at {PEOPLE_URL}", "setup --target fake", INVITATION_URL],
        ),
    ],
)
def test_bootstrap_explains_fine_grained_tokens_that_cannot_prove_their_isolation(
    org: Org, monkeypatch: pytest.MonkeyPatch, role: str, message: str, expected: list[str]
) -> None:
    """verify_target refuses a fine-grained author/approver/oracle token until its account is an active member
    (owner) and, for members, the request is approved: bootstrap adds those steps; other errors pass unchanged."""
    from otterdog_e2e.safety import SafetyError as RealSafetyError

    if role == "oracle":
        with_oracle(org)
    org.identities[role] = Identity(role, f"e2e-{role}", fake_token(role), "fine-grained")

    def refuse(admin_http: Any, target: Any, identities: Any, **kwargs: Any) -> Any:
        """The isolation proof of the fine-grained token fails."""
        raise RealSafetyError(message)

    monkeypatch.setattr("otterdog_e2e.safety.verify_target", refuse)
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", "--apply"])
    assert result.exit_code == 1 and f"SafetyError: {message}" in result.output
    for text in expected:
        assert text in result.output
    assert (TOKEN_REQUESTS_URL in result.output) == (role != "oracle")
    org.identities[role] = Identity(role, f"e2e-{role}", fake_token(role))  # classic: no hint
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", "--apply"])
    assert result.exit_code == 1 and "SafetyError" in result.output and "unset E2E_" not in result.output


def test_bootstrap_stops_with_the_installation_url_of_an_app_not_installed(org: Org, heavy: dict[str, Any]) -> None:
    """App configured but not installed (without --wait): the installation URL (slug of GET /app when neither the
    target nor the credentials declare it, target_id = the org id) and a re-run hint; no delivery probe."""
    ready_org(org)
    org.app.installed = False
    with pytest.raises(click.ClickException, match=r"not installed on the org: install the GitHub App") as exc:
        bootstrap(org)
    assert INSTALL_URL in str(exc.value) and "--wait" in str(exc.value)
    assert ("get_app", (True,)) in org.app.calls and not admin_calls(org, "create_branch")
    assert org.target.app is not None
    org.target = make_target(app=replace(org.target.app, slug="e2e-declared-app"))
    with pytest.raises(click.ClickException, match="e2e-declared-app/installations/new/permissions") as exc:
        bootstrap(org)
    assert f"?target_id={FAKE_ORG_ID}" in str(exc.value)


def test_bootstrap_wait_polls_the_app_installation(
    org: Org, heavy: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """--wait: the installation URL is printed and GET /orgs/{org}/installation polled every 10 s until the App is
    installed; then the preflight and the delivery probe run."""
    ready_org(org)
    org.app.installed = False
    branch = f"e2e/{FAKE_RUN_ID}/bootstrap"
    org.app.add_delivery("push", {"ref": f"refs/heads/{branch}", "organization": {"login": FAKE_ORG}})
    clock = Clock(lambda count: setattr(org.app, "installed", count >= 2))
    bootstrap(org, wait=True, clock=clock)
    output = capsys.readouterr().out
    assert f"App not installed: install the GitHub App otterdog-e2e-test on {FAKE_ORG} for All repositories: " in output
    assert INSTALL_URL in output and "waiting up to 1800 s for the installation of the GitHub App" in output
    assert clock.sleeps == [10.0, 10.0] and "App installation 4242 ready" in output
    assert [call.args[1] for call in admin_calls(org, "create_branch")] == [branch]
    org.app.installed = False
    with pytest.raises(
        click.ClickException, match=r"installation of the GitHub App otterdog-e2e-test: not done within"
    ):
        bootstrap(org, wait=True, wait_timeout=10, clock=Clock())


def test_bootstrap_command_wait_options(org: Org, monkeypatch: pytest.MonkeyPatch) -> None:
    """--wait / --wait-timeout (durations like the other options: 90s, 10m, plain seconds; default 30 min) reach
    Bootstrap; a malformed duration is a usage error."""
    created: dict[str, Any] = {}

    class Recorder:
        """Bootstrap stand-in recording its options."""

        def __init__(self, context: Any, **options: Any) -> None:
            """Record the options."""
            created.update(options)

        def run(self) -> None:
            """Record the run."""
            created["ran"] = True

    monkeypatch.setattr(cli, "Bootstrap", Recorder)
    for argv, wait, timeout in (
        (["--apply", "--wait", "--wait-timeout", "90s"], True, 90),
        (["--apply", "--wait", "--wait-timeout", "1800"], True, 1800),
        ([], False, 1800),
    ):
        created.clear()
        result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", *argv])
        assert result.exit_code == 0, result.output
        assert (created["wait"], created["wait_timeout"], created["ran"]) == (wait, timeout, True)
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", "--wait", "--wait-timeout", "soon"])
    assert result.exit_code == 2 and "--wait-timeout" in result.output
    created.clear()
    result = CliRunner().invoke(cli.main, ["bootstrap", "--target", "fake", "--wait"])  # a dry run waits for nothing
    assert result.exit_code == 2 and "--wait needs --apply" in result.output and not created


# --- janitor --------------------------------------------------------------------------------------------------------
def test_janitor_filter_rules() -> None:
    """Exact --run-id, else runs older than the cutoff; never the janitor's own run; only purgeable runs."""
    now = datetime(2026, 10, 2, tzinfo=UTC)
    context = SimpleNamespace(run_ctx=SimpleNamespace(run_id="zzzzzz00"), purgeable=lambda run_id: run_id != "t3c7z8c7")
    by_age = cli.janitor_filter(context, older_than=timedelta(hours=6), run_id=None, now=now)  # type: ignore[arg-type]
    assert by_age(FAKE_RUN_ID)  # 2025: old enough
    assert not by_age("t3c7z8c7")  # not purgeable
    assert not by_age("zzzzzz00")  # the janitor's own run
    assert not by_age("garbage")
    exact = cli.janitor_filter(context, older_than=timedelta(hours=6), run_id=OTHER_RUN, now=now)  # type: ignore[arg-type]
    assert exact(OTHER_RUN) and not exact(FAKE_RUN_ID)


@pytest.fixture
def fake_janitor(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """github.janitor.Janitor stand-in returning two items."""
    state: dict[str, Any] = {"swept": None}
    items = [
        JanitorItem("repo", f"e2e-{OTHER_RUN}-x", OTHER_RUN),
        JanitorItem("team", f"e2e-{OTHER_RUN}-t", OTHER_RUN, detail="id 7"),
    ]

    class Janitor:
        """Records its purgeable callback and sweeps."""

        def __init__(self, oracle: Any, mutator: Any, **kwargs: Any) -> None:
            """Record the arguments."""
            state["kwargs"] = kwargs

        def scan(self) -> list[JanitorItem]:
            """The fixed items."""
            return list(items)

        def sweep(self, swept: Any = None) -> list[JanitorItem]:
            """Record the sweep."""
            state["swept"] = list(swept)
            return list(swept)

    monkeypatch.setattr("otterdog_e2e.github.janitor.Janitor", Janitor)
    return state


def test_janitor_dry_run(org: Org, fake_janitor: dict[str, Any]) -> None:
    """Dry run lists the items without the lease or deletions."""
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    result = CliRunner().invoke(cli.main, ["janitor", "--target", "fake"])
    assert result.exit_code == 0, result.output
    assert f"e2e-{OTHER_RUN}-x" in result.output and "--apply" in result.output
    assert fake_janitor["swept"] is None and "acquire" not in org.lease.calls
    assert fake_janitor["kwargs"]["configs_repo"] == "otterdog-e2e-configs"
    assert "otterdog-e2e-fixture-a" in fake_janitor["kwargs"]["protected_repos"]


def test_janitor_apply_with_run_id_takes_over_the_lease(org: Org, fake_janitor: dict[str, Any]) -> None:
    """--run-id --apply takes over a lease left by that run (compare-and-swap in OrgLease.acquire, never a DELETE),
    then sweeps; --force-takeover is passed through."""
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    org.lease.holder = {"run_id": OTHER_RUN, "expires_at": "2099-01-01T00:00:00Z"}
    org.lease.busy = True
    result = CliRunner().invoke(cli.main, ["janitor", "--target", "fake", "--run-id", OTHER_RUN, "--apply"])
    assert result.exit_code == 0, result.output
    assert not admin_calls(org, "delete_ref")
    assert org.lease.takeovers == [(OTHER_RUN, False, None)]
    assert org.lease.calls.count("acquire") == 1 and "release" in org.lease.calls
    assert len(fake_janitor["swept"]) == 2 and "deleted 2 of 2" in result.output


def test_janitor_refuses_to_take_over_a_live_runs_lease(org: Org, fake_janitor: dict[str, Any]) -> None:
    """DESTR-05: a lease renewed recently (the run may still be running) is not taken over: nothing is swept; the
    operator can force it."""
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    org.lease.holder = {"run_id": OTHER_RUN, "expires_at": "2099-01-01T00:00:00Z"}
    org.lease.busy = org.lease.takeover_refused = True
    result = CliRunner().invoke(cli.main, ["janitor", "--target", "fake", "--run-id", OTHER_RUN, "--apply"])
    assert result.exit_code == 1 and "renewed the org lease recently" in result.output
    assert fake_janitor["swept"] is None
    forced = ["janitor", "--target", "fake", "--run-id", OTHER_RUN, "--apply", "--force-takeover"]
    result = CliRunner().invoke(cli.main, forced)
    assert result.exit_code == 0, result.output
    assert org.lease.takeovers[-1] == (OTHER_RUN, True, None) and len(fake_janitor["swept"]) == 2
    assert CliRunner().invoke(cli.main, ["janitor", "--target", "fake", "--force-takeover"]).exit_code == 2


def test_janitor_rejects_bad_run_ids(org: Org) -> None:
    """--run-id must look like a run id."""
    result = CliRunner().invoke(cli.main, ["janitor", "--target", "fake", "--run-id", "../../x"])
    assert result.exit_code == 2


# --- relay ----------------------------------------------------------------------------------------------------------
class FakeRelay:
    """DeliveryRelay stand-in: scripted poll results (an exception is raised)."""

    poll_interval = 5.0

    def __init__(self, *script: Any) -> None:
        """Script the polls."""
        self.script = list(script)
        self.stopped = False

    def poll_once(self) -> list[Any]:
        """Next scripted result."""
        item = self.script.pop(0) if self.script else []
        if isinstance(item, Exception):
            raise item
        return item

    def stop(self, timeout: float = 10) -> None:
        """Record."""
        self.stopped = True


def delivery(**overrides: Any) -> Any:
    """A RelayedDelivery-like record."""
    values = {"event": "pull_request", "action": "opened", "pull_number": 3, "relay_status": 204, "error": None}
    values["delivered_at"] = datetime(2026, 10, 2, 12, 30, 5, tzinfo=UTC)
    return SimpleNamespace(**(values | overrides))


def test_relay_loop_prints_and_survives_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """Forwarded deliveries are printed; a failing poll is logged and retried; the relay is stopped."""
    relay = FakeRelay(
        [delivery()], RuntimeError("github hiccup"), [delivery(event="push", action=None, pull_number=None)]
    )
    sleeps: list[float] = []
    cli.relay_loop(relay, sleep=sleeps.append, max_polls=3)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert "12:30:05 pull_request/opened #3 -> 204" in out and "12:30:05 push -> 204" in out
    assert sleeps == [5.0, 5.0, 5.0] and relay.stopped


def test_relay_loop_stops_on_ctrl_c() -> None:
    """Ctrl-C stops the relay cleanly."""
    relay = FakeRelay()

    def interrupt(seconds: float) -> None:
        """Simulate Ctrl-C."""
        raise KeyboardInterrupt

    cli.relay_loop(relay, sleep=interrupt)  # type: ignore[arg-type]
    assert relay.stopped


def test_relay_command_holds_the_lease(org: Org, monkeypatch: pytest.MonkeyPatch) -> None:
    """relay: verified org, lease held, relay configured from the App and --since."""
    org.oracle.set("org", value={**org.oracle.org(), "description": f"{FAKE_MARKER} ok"})
    created: dict[str, Any] = {}
    monkeypatch.setattr(
        "otterdog_e2e.webhooks.relay.DeliveryRelay", lambda app, **kw: created.update(kw) or FakeRelay()
    )
    monkeypatch.setattr(cli, "relay_loop", lambda relay, **kw: created.setdefault("lease", list(org.lease.calls)))
    before = datetime.now(UTC)
    result = CliRunner().invoke(
        cli.main,
        ["relay", "--target", "fake", "--forward-to", "http://127.0.0.1:5000/github-webhook/receive", "--since", "30m"],
    )
    assert result.exit_code == 0, result.output
    assert "acquire" in created["lease"] and "release" in org.lease.calls
    assert created["installation_id"] == 4242 and created["secret"] == "hook-s3cret" and created["org"] == FAKE_ORG
    assert before - timedelta(minutes=31) < created["since"] < before - timedelta(minutes=29)


# --- report, scrub, cache -------------------------------------------------------------------------------------------
def test_report_and_scrub_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """report prints the summary; scrub-artifacts exits 1 when it removed leaking files."""
    monkeypatch.setattr("otterdog_e2e.report.build_summary", lambda directory, **kw: f"# summary {directory.name}")
    result = CliRunner().invoke(cli.main, ["report", str(tmp_path)])
    assert result.exit_code == 0 and f"# summary {tmp_path.name}" in result.output
    monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor=None: [root / "cli" / "x.txt"])
    result = CliRunner().invoke(cli.main, ["scrub-artifacts", str(tmp_path)])
    assert result.exit_code == 1 and "x.txt" in result.output
    monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor=None: [])
    result = CliRunner().invoke(cli.main, ["scrub-artifacts", str(tmp_path)])
    assert result.exit_code == 0 and "no leak" in result.output


# unique values: registered with the redactor of the test only (cli.REDACTOR is replaced by a fresh one)
WEB_PASSWORD = "e2e-web-password-not-token-shaped-7f3a"
TOTP_SEED = "JBSWY3DPEHPK3PXPJBSWY3DPEHPK3PXP"


def test_scrub_registers_the_secrets_of_the_environment(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """scrub-artifacts registers the SECRET_KEY_RE values of its environment before the scan: a leaked password or TOTP
    seed (no token shape, unknown to a fresh CI process) is found, the file deleted and the exit code 1; other
    variables are no secrets."""
    fresh = Redactor()
    monkeypatch.setattr(cli, "REDACTOR", fresh)
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)  # no ::add-mask:: lines (they would print the values)
    run_dir = tmp_path / "artifacts" / "t3c7z8a5"
    (run_dir / "cli" / "0001-plan").mkdir(parents=True)
    (run_dir / "cli" / "0001-plan" / "stdout.txt").write_text(f"login {WEB_PASSWORD}\n")
    (run_dir / "cli" / "0001-plan" / "stderr.txt").write_text(f"seed {TOTP_SEED}\n")
    (run_dir / "summary.md").write_text("# org e2e-test-org-public-name\n")
    environ = {
        "E2E_ADMIN_PASSWORD": WEB_PASSWORD,
        "E2E_ADMIN_TOTP_SEED": TOTP_SEED,
        "E2E_ORG": "e2e-test-org-public-name",
    }
    result = CliRunner().invoke(cli.main, ["scrub-artifacts", str(run_dir)], env=environ)
    assert result.exit_code == 1, result.output
    assert "cli/0001-plan/stdout.txt" in result.output and "cli/0001-plan/stderr.txt" in result.output
    assert not (run_dir / "cli" / "0001-plan" / "stdout.txt").exists() and (run_dir / "summary.md").exists()
    leaks = (run_dir / "leaks.json").read_text()
    assert WEB_PASSWORD not in leaks and TOTP_SEED not in leaks and WEB_PASSWORD not in result.output
    assert fresh(f"{WEB_PASSWORD} {TOTP_SEED} e2e-test-org-public-name") == "*** *** e2e-test-org-public-name"


def test_register_environment_secrets_counts_registered_values() -> None:
    """Only names ending in _TOKEN, _SECRET, _PASSWORD, _TOTP_SEED or _PRIVATE_KEY with a value long enough to redact."""
    fresh = Redactor()
    environ = {
        "E2E_ADMIN_TOKEN": "e2e-admin-token-value-1",
        "E2E_APP_WEBHOOK_SECRET": "e2e-hook-secret-value-2",
        "E2E_ADMIN_PASSWORD": "short",
        "E2E_ADMIN_USERNAME": "e2e-admin-login-name",
        "PATH": "/usr/bin:/bin",
    }
    assert cli.register_environment_secrets(environ, fresh) == 2
    assert (
        fresh("e2e-admin-token-value-1 e2e-hook-secret-value-2 e2e-admin-login-name") == "*** *** e2e-admin-login-name"
    )
    assert cli.register_environment_secrets({}, fresh) == 0


def test_cache_prune_keeps_the_newest_entries(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Older run/build/src/http-cache entries go (with their sidecar markers); docker images are skipped without docker."""
    cache = tmp_path / "cache"
    for sub, names in (("run", ["r1", "r2", "r3"]), ("src", ["v1.6.0", "v1.6.1"]), ("build", ["v1.6.1-cli"])):
        for age, name in enumerate(reversed(names)):
            entry = cache / sub / name
            entry.mkdir(parents=True)
            os.utime(entry, (1_700_000_000 - age * 100, 1_700_000_000 - age * 100))
    (cache / "src" / "v1.6.0.e2e-export.json").write_text("{}")
    (cache / "mirror").mkdir()
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path))
    monkeypatch.setattr("otterdog_e2e.sut.image.docker_available", lambda: False)
    result = CliRunner().invoke(cli.main, ["cache", "prune", "--keep", "1"])
    assert result.exit_code == 0, result.output
    assert sorted(p.name for p in (cache / "run").iterdir()) == ["r3"]
    assert sorted(p.name for p in (cache / "src").iterdir()) == ["v1.6.1"]
    assert (cache / "build" / "v1.6.1-cli").is_dir() and (cache / "mirror").is_dir()
    assert "pruned 3 cache entries and 0 image(s)" in result.output


def test_prune_images_keeps_the_newest_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """docker lists newest first: every tag after the first ``keep`` is removed."""
    calls: list[list[str]] = []

    def run(argv: list[str], **kwargs: Any) -> Any:
        """Fake docker CLI."""
        calls.append(list(argv))
        if argv[:3] == ["docker", "image", "ls"]:
            repository = argv[-1]
            return SimpleNamespace(returncode=0, stdout=f"{repository}:new\n{repository}:old\n{repository}:<none>\n")
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr("otterdog_e2e.sut.image.docker_available", lambda: True)
    monkeypatch.setattr("otterdog_e2e.procs.run", run)
    removed = cli.prune_images(keep=1)
    assert removed == ["otterdog-e2e/otterdog:old", "otterdog-e2e/untrusted:old"]
    assert ["docker", "image", "rm", "otterdog-e2e/otterdog:old"] in calls


# --- app-manifest ---------------------------------------------------------------------------------------------------
def test_manifest_flow_verifies_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The loopback listener serves the form, ignores a wrong state and returns the code of the right one."""
    monkeypatch.setattr(
        "otterdog_e2e.appmanifest.build_manifest", lambda target, **kw: {"redirect_url": kw["redirect_url"]}
    )
    monkeypatch.setattr(
        "otterdog_e2e.appmanifest.manifest_form_html", lambda org, manifest, state: f"<form {org} {state}>"
    )
    flow = cli.ManifestFlow(
        make_target(), webhook_url="https://sink.example.org/x", port=0, state="the-state", timeout=30
    )
    responses: list[tuple[int, str]] = []

    def browser(base: str) -> None:
        """Play GitHub and the browser from another thread."""

        def visit() -> None:
            """Requests of the flow."""
            session = requests.Session()
            session.trust_env = False
            for path in (
                "",
                "callback?code=abcdefgh1234&state=forged",
                "nope",
                "callback?code=abcdefgh1234&state=the-state",
            ):
                answer = session.get(base + path, timeout=10)
                responses.append((answer.status_code, answer.text))

        threading.Thread(target=visit, daemon=True).start()

    code = flow.run(on_ready=browser)
    assert code == "abcdefgh1234"
    assert responses[0] == (200, f"<form {FAKE_ORG} the-state>")
    assert responses[1][0] == 400 and "state mismatch" in responses[1][1]
    assert responses[2][0] == 404


def test_manifest_flow_rejects_malformed_codes() -> None:
    """Callbacks without a plausible code are refused."""
    flow = cli.ManifestFlow(make_target(), webhook_url="https://sink.example.org/x", port=0, state="s")
    assert flow.callback({"state": ["s"], "code": ["x"]})[0] == 400
    assert flow.callback({"state": ["s"]})[0] == 400 and flow.code is None


def test_app_manifest_exchange_prints_paths_not_secrets(
    org: Org, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """--exchange: credentials land in 0600 files; only their paths and env var names are printed."""
    exchanged: dict[str, Any] = {}

    def exchange(code: str, *, out_dir: Path) -> dict[str, Any]:
        """Record the exchange."""
        exchanged.update(code=code, out_dir=out_dir)
        return {
            "id": 77,
            "slug": "otterdog-e2e-org",
            "pem_path": out_dir / "app.pem",
            "secret_path": out_dir / "webhook-secret",
        }

    monkeypatch.setattr("otterdog_e2e.appmanifest.exchange_code", exchange)
    home = tmp_path / "home"
    result = CliRunner().invoke(
        cli.main,
        [
            "app-manifest",
            "--target",
            "fake",
            "--webhook-url",
            "https://sink.example.org/x",
            "--exchange",
            "code-12345678",
        ],
        env={"HOME": str(home)},
    )
    assert result.exit_code == 0, result.output
    assert exchanged["code"] == "code-12345678" and exchanged["out_dir"] == home / ".config" / "otterdog-e2e" / "fake"
    assert "E2E_APP_ID=77" in result.output and "E2E_APP_PRIVATE_KEY_FILE=" in result.output
    assert "E2E_APP_WEBHOOK_SECRET=<the content of" in result.output and "code-12345678" not in result.output
    assert f"add to {home / '.config' / 'otterdog-e2e' / 'fake.env'}:" in result.output


def test_app_credentials_dir_and_instructions_use_home_of_the_environ(tmp_path: Path) -> None:
    """The App credentials go to settings.user_config_dir(environ) / <target name> (HOME of the context's environ, not
    of the process); the instructions name that env file and the installation URL preselecting the org."""
    target = make_target("my-instance")
    environ = {"HOME": str(tmp_path)}
    config = tmp_path / ".config" / "otterdog-e2e"
    assert cli.app_credentials_dir(target, environ) == config / "my-instance"
    result = {"id": 7, "slug": "otterdog-e2e-x", "pem_path": "k.pem", "secret_path": "s", "env_path": "app-7.env"}
    text = cli.app_instructions(target, result, environ)
    assert f"add to {config / 'my-instance.env'}:" in text and "(or append app-7.env:" in text
    assert text.endswith(
        f"for All repositories: https://github.com/apps/otterdog-e2e-x/installations/new/permissions"
        f"?target_id={FAKE_ORG_ID}"
    )


def test_app_manifest_listener_requires_a_verified_org(org: Org, monkeypatch: pytest.MonkeyPatch) -> None:
    """The listener path verifies the marked org first and refuses loopback webhook URLs."""
    result = CliRunner().invoke(
        cli.main, ["app-manifest", "--target", "fake", "--webhook-url", "https://sink.example.org/x"]
    )
    assert result.exit_code == 1 and "marker missing" in result.output
    result = CliRunner().invoke(cli.main, ["app-manifest", "--target", "fake", "--webhook-url", "http://localhost:9/x"])
    assert result.exit_code == 2 and "loopback" in result.output


# --- sut ------------------------------------------------------------------------------------------------------------
@dataclass
class Resolved:
    """Minimal ResolvedSut."""

    label: str
    trusted: bool
    version: str = "1.6.1"
    sha: str = fake_sha("sut")

    def to_json(self) -> dict[str, Any]:
        """JSON form."""
        return {"label": self.label, "trusted": self.trusted}


def test_sut_commands(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve prints the ResolvedSut; install refuses untrusted SUTs; image builds the webapp image."""
    resolved = {"release:latest": Resolved("v1.6.1", True), "pr:1@" + fake_sha("p"): Resolved("pr1-abc", False)}
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path))
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *a: None)
    monkeypatch.setattr("otterdog_e2e.sut.spec.parse_sut_spec", lambda raw: raw)
    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", lambda spec, settings, http=None: resolved[spec])
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", lambda token, **kw: FakeGitHubHttp())
    installed = SimpleNamespace(
        runtime="host", otterdog_bin=tmp_path / "otterdog", version_output="otterdog.sh, version 1.6.1\n"
    )
    monkeypatch.setattr(
        "otterdog_e2e.sut.cli_install.install_cli",
        lambda sut, settings, **kw: SimpleNamespace(sut=sut, **vars(installed)),
    )
    monkeypatch.setattr(
        "otterdog_e2e.sut.image.build_webapp_image",
        lambda sut, **kw: cli.dataclasses.make_dataclass("Image", ["tag"])(tag=f"otterdog-e2e/otterdog:{sut.label}"),
    )
    result = CliRunner().invoke(cli.main, ["sut", "resolve", "release:latest"])
    assert result.exit_code == 0 and json.loads(result.output) == {"label": "v1.6.1", "trusted": True}
    result = CliRunner().invoke(cli.main, ["sut", "install", "release:latest"])
    assert result.exit_code == 0 and json.loads(result.output)["version_output"] == "otterdog.sh, version 1.6.1"
    result = CliRunner().invoke(cli.main, ["sut", "install", "pr:1@" + fake_sha("p")])
    assert result.exit_code == 1 and "untrusted" in result.output
    result = CliRunner().invoke(cli.main, ["sut", "image", "release:latest"])
    assert result.exit_code == 0 and json.loads(result.output) == {"tag": "otterdog-e2e/otterdog:v1.6.1"}
    assert not (make_settings(tmp_path).artifacts_root).exists()
