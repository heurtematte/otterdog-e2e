"""Harness CLI operations: bootstrap, janitor, relay, report, scrub-artifacts, cache prune, app-manifest, sut."""

from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
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
from otterdog_e2e.settings import AppCredentials, Target
from otterdog_e2e.testing.fakes import (
    FAKE_MARKER,
    FAKE_ORG,
    FAKE_RUN_ID,
    FakeAppAuth,
    FakeBaselineManager,
    FakeCli,
    FakeGitHubHttp,
    FakeLease,
    FakeOracle,
    RecordingMutator,
    fake_sha,
    make_identities,
    make_settings,
    make_target,
    make_verified_org,
)

OTHER_RUN = "t3c7z8b6"


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


def bootstrap(org: Org, *, confirm: str = FAKE_ORG) -> list[str]:
    """Run Bootstrap(apply) on a fresh context; returns the prompts shown."""
    prompts: list[str] = []
    context = E2EContext.create(E2EOptions(target="fake", run_id=FAKE_RUN_ID), environ={})
    cli.Bootstrap(context, apply=True, confirm=lambda text: prompts.append(text) or confirm, sleep=lambda s: None).run()
    return prompts


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
    bootstrap(org)
    output = capsys.readouterr().out
    assert "author e2e-author: the token may not change its membership (403)" in output
    assert "in the web UI, logged in as e2e-author" in output
    invited = [call.args for call in admin_calls(org, "ensure_membership")]
    assert invited == [("e2e-author",), ("e2e-approver",)]  # both invited before any acceptance
    assert org.lease.held and heavy["baseline"].calls_to("reset") and heavy["published"]


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
    )
    assert result.exit_code == 0, result.output
    assert exchanged["code"] == "code-12345678" and exchanged["out_dir"].name == "fake"
    assert "E2E_APP_ID=77" in result.output and "E2E_APP_PRIVATE_KEY_FILE=" in result.output
    assert "E2E_APP_WEBHOOK_SECRET=<the content of" in result.output and "code-12345678" not in result.output


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
