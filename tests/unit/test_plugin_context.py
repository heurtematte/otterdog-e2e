"""E2EContext (the otterdog_e2e.context package): options, lazy live session, lease, SUT roles, webapp wiring and
isolation, reporting."""

from __future__ import annotations

import json
import stat
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e import context as context_module
from otterdog_e2e.capabilities import Cap, from_plan
from otterdog_e2e.changes import ChangeError, ChangeId
from otterdog_e2e.context import (
    ContextError,
    E2EContext,
    E2EOptions,
    in_ci,
    installation_problems,
    lease_holder,
    parse_duration,
    parse_time,
    printed_version,
    split_csv,
    target_env_name,
    text_or_none,
)
from otterdog_e2e.context import core as context_core
from otterdog_e2e.context import helpers as context_helpers
from otterdog_e2e.context import sut as context_sut
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.otterdog import runtime as runtime_module
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import AppCredentials
from otterdog_e2e.sut.template import TemplateRef, offline_template
from otterdog_e2e.testing.fakes import (
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


def new_context(tmp_path: Path, **options: Any) -> E2EContext:
    """A context on tmp settings with an empty environment."""
    options.setdefault("run_id", FAKE_RUN_ID)
    return E2EContext.create(E2EOptions(**options), environ={}, settings=make_settings(tmp_path))


@dataclass
class LiveFakes:
    """Collaborators installed by the ``live`` fixture."""

    calls: list[str] = field(default_factory=list)
    lease: FakeLease = field(default_factory=FakeLease)
    oracle: FakeOracle = field(default_factory=FakeOracle)
    verify_error: Exception | None = None
    https: list[FakeGitHubHttp] = field(default_factory=list)


@pytest.fixture
def live(monkeypatch: pytest.MonkeyPatch) -> LiveFakes:
    """Fake target loading, verification, probes, clients and the lease (no network)."""
    fakes = LiveFakes()

    def http(token: str | None, **kwargs: Any) -> FakeGitHubHttp:
        """FakeGitHubHttp recording its construction."""
        client = FakeGitHubHttp(identity=kwargs.get("identity", "?"), read_only=kwargs.get("read_only", False))
        client.write_scope = kwargs.get("write_scope")
        fakes.https.append(client)
        return client

    def verify(admin_http: Any, target: Any, identities: Any, **kwargs: Any) -> Any:
        """Record and return a VerifiedOrg (or raise the configured error)."""
        fakes.calls.append(f"verify(marker={kwargs.get('require_marker')})")
        if fakes.verify_error is not None:
            raise fakes.verify_error
        return make_verified_org()

    def probe(admin_http: Any, verified: Any, **kwargs: Any) -> Any:
        """Record and return the free plan capabilities."""
        fakes.calls.append("probe")
        return from_plan("free")

    def lease(mutator: Any, oracle: Any, **kwargs: Any) -> FakeLease:
        """Record and return the shared FakeLease."""
        fakes.calls.append(f"lease(repo={kwargs['repo']})")
        return fakes.lease

    monkeypatch.setattr("otterdog_e2e.settings.load_env_files", lambda *a, **k: fakes.calls.append("env") or [])
    monkeypatch.setattr(
        "otterdog_e2e.settings.load_target", lambda *a, **k: fakes.calls.append("target") or make_target()
    )
    monkeypatch.setattr("otterdog_e2e.settings.resolve_identities", lambda *a, **k: make_identities("admin", "author"))
    monkeypatch.setattr("otterdog_e2e.settings.resolve_app_credentials", lambda *a, **k: None)
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", http)
    monkeypatch.setattr("otterdog_e2e.safety.verify_target", verify)
    monkeypatch.setattr("otterdog_e2e.capabilities.probe_capabilities", probe)
    monkeypatch.setattr("otterdog_e2e.sut.image.docker_available", lambda: False)
    monkeypatch.setattr("otterdog_e2e.github.lease.OrgLease", lease)
    monkeypatch.setattr("otterdog_e2e.github.oracle.Oracle", lambda http, org: fakes.oracle)
    monkeypatch.setattr("otterdog_e2e.github.mutate.Mutator", lambda http, verified, **k: RecordingMutator(verified))
    return fakes


# --- helpers --------------------------------------------------------------------------------------------------------
def test_small_helpers() -> None:
    """CSV splitting, blank handling, CI detection, env names, durations, timestamps, versions."""
    assert split_csv(" a, b,,c ") == ("a", "b", "c")
    assert split_csv(["x,y", "z"]) == ("x", "y", "z")
    assert split_csv(None) == ()
    assert text_or_none("  ") is None and text_or_none(" v ") == "v" and text_or_none(None) is None
    assert in_ci({"CI": "true"}) and in_ci({"GITHUB_ACTIONS": "true"})
    assert not in_ci({}) and not in_ci({"CI": "false"}) and not in_ci({"CI": "0"})
    assert target_env_name("free") == "free"
    assert target_env_name("targets/enterprise.yaml") == "enterprise"
    assert parse_duration("90") == timedelta(seconds=90)
    assert parse_duration("10m") == timedelta(minutes=10)
    assert parse_duration("6h") == timedelta(hours=6)
    assert parse_duration("2d") == timedelta(days=2)
    with pytest.raises(ValueError, match="invalid duration"):
        parse_duration("soon")
    assert parse_time("2026-10-02T10:00:00Z") == datetime(2026, 10, 2, 10, tzinfo=UTC)
    assert parse_time("2026-10-02T10:00:00") == datetime(2026, 10, 2, 10, tzinfo=UTC)
    assert parse_time("nope") is None and parse_time(None) is None
    assert printed_version("otterdog.sh, version 1.6.1\n") == "1.6.1"
    assert printed_version("garbage") is None


def test_lease_holder_text() -> None:
    """CI runs are identified by their workflow run, local runs by the user; an override wins."""
    ci = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "eclipse-csi/otterdog-e2e", "GITHUB_RUN_ID": "42"}
    assert lease_holder(ci) == "ci:eclipse-csi/otterdog-e2e/actions/runs/42"
    assert lease_holder({"E2E_LEASE_HOLDER": "me"}) == "me"
    assert lease_holder({}).startswith("local")


def test_installation_problems() -> None:
    """Selection, suspension, permission levels and events are all checked."""
    from otterdog_e2e.appmanifest import DEFAULT_EVENTS, DEFAULT_PERMISSIONS

    good = {"repository_selection": "all", "suspended_at": None, "permissions": dict(DEFAULT_PERMISSIONS)}
    good["events"] = list(DEFAULT_EVENTS)
    assert installation_problems(good) == []
    bad = {**good, "repository_selection": "selected", "suspended_at": "2026-01-01T00:00:00Z"}
    bad["permissions"] = {**DEFAULT_PERMISSIONS, "contents": "read"}
    bad["events"] = ["push"]
    problems = installation_problems(bad)
    assert any("repository_selection" in p for p in problems)
    assert any("suspended" in p for p in problems)
    assert any("contents (read < write)" in p for p in problems)
    assert any("events not subscribed" in p and "pull_request" in p for p in problems)
    assert len(installation_problems(bad, permissions=False)) == 2


def test_options_from_config(tmp_path: Path) -> None:
    """Options are read from the pytest config (blank values are None, CSV options are split)."""
    values = {
        "e2e_target": "free",
        "e2e_sut": "",
        "e2e_base_sut": " auto ",
        "e2e_reset_sut": None,
        "e2e_tags": "smoke, repo",
        "e2e_scenario": "cli.*",
        "e2e_artifacts": str(tmp_path / "art"),
        "e2e_run_id": None,
        "e2e_keep": True,
        "e2e_change": " #790 ",
        "e2e_trust_code": None,
    }
    config = SimpleNamespace(getoption=lambda dest, default=None: values.get(dest, default))
    options = E2EOptions.from_config(config)  # type: ignore[arg-type]
    assert options.target == "free"
    assert options.sut == "release:latest" and options.reset_sut == "release:latest"
    assert options.base_sut == "auto"
    assert options.tags == ("smoke", "repo") and options.scenario == ("cli.*",)
    assert options.artifacts == tmp_path / "art"
    assert options.keep and not options.no_reset
    assert options.change == "#790"


# --- creation and teardown --------------------------------------------------------------------------------------------
def test_create_makes_private_dirs(tmp_path: Path) -> None:
    """Scratch is 0700 under cache_dir/run/<id>; artifacts under the (overridable) artifacts root."""
    context = new_context(tmp_path, artifacts=tmp_path / "elsewhere")
    assert context.run_ctx.run_id == FAKE_RUN_ID
    assert context.scratch == tmp_path / "cache" / "run" / FAKE_RUN_ID
    assert stat.S_IMODE(context.scratch.stat().st_mode) == 0o700
    assert context.artifacts_dir == (tmp_path / "elsewhere").resolve() / FAKE_RUN_ID
    assert context.artifacts_dir.is_dir()
    assert not context.is_live


def test_create_without_dirs(tmp_path: Path) -> None:
    """make_dirs=False (doctor) creates nothing; artifacts=False skips the artifacts dir."""
    context = E2EContext.create(
        E2EOptions(run_id=FAKE_RUN_ID), environ={}, settings=make_settings(tmp_path), make_dirs=False
    )
    assert not context.scratch.exists() and not context.artifacts_dir.exists()
    context.write_run_info(x=1)
    assert not context.artifacts_dir.exists()
    other = E2EContext.create(E2EOptions(), environ={}, settings=make_settings(tmp_path), artifacts=False)
    assert other.scratch.is_dir() and not other.artifacts_dir.exists()


def test_start_session_writes_run_json_and_sets_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """start_session: log redaction installed, subprocess HOME in scratch, container names scoped to the run,
    run.json with the options."""
    installed: list[Any] = []
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *a: installed.append(a))
    homes: list[Any] = []
    monkeypatch.setattr("otterdog_e2e.procs.set_default_home", homes.append)
    scopes: list[Any] = []
    monkeypatch.setattr("otterdog_e2e.otterdog.runtime.set_container_scope", scopes.append)
    context = new_context(tmp_path, target="free", sut="tag:v1.6.1")
    context.start_session(argv=["-q", "tests/cli"])
    assert installed and homes == [context.scratch / "home"] and scopes == [FAKE_RUN_ID]
    run = json.loads((context.artifacts_dir / "run.json").read_text())
    assert run["run_id"] == FAKE_RUN_ID and run["target"] == "free" and run["sut"] == "tag:v1.6.1"
    assert run["reset_sut"] == "release:latest" and run["argv"] == ["-q", "tests/cli"]
    assert run["command"] is None  # set only by otterdog-e2e run|pr (E2E_INVOCATION)
    started = new_context(tmp_path / "cmd", run_id=OTHER_RUN)
    started.environ = {"E2E_INVOCATION": "otterdog-e2e run --suite offline --sut release:latest"}
    started.start_session()
    command = json.loads((started.artifacts_dir / "run.json").read_text())["command"]
    assert command == "otterdog-e2e run --suite offline --sut release:latest"


def test_session_close_is_registered_at_exit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """start_session registers close() with atexit (sessions dying before teardown); close() unregisters it."""
    registered: list[Any] = []
    monkeypatch.setattr(context_core.atexit, "register", registered.append)
    monkeypatch.setattr(context_core.atexit, "unregister", registered.remove)
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *a: None)
    monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor: [])
    context = new_context(tmp_path)
    context.start_session()
    assert registered == [context.close] and runtime_module.container_name(1) == f"otterdog-e2e-{FAKE_RUN_ID}-0001"
    context.close()
    assert registered == [] and runtime_module.container_scope() != FAKE_RUN_ID  # process default restored


def test_close_runs_finalizers_releases_lease_scrubs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Finalizers in reverse order (failures do not stop the others), lease released, scrub, scratch removed."""
    leak = tmp_path / "leak.txt"
    scrubbed: list[Path] = []
    monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor: scrubbed.append(root) or [leak])
    context = new_context(tmp_path)
    order: list[str] = []
    context.add_finalizer(lambda: order.append("first"))
    context.add_finalizer(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    context.add_finalizer(lambda: order.append("last"))
    lease = FakeLease()
    lease.acquire()
    lease.start_heartbeat()
    context.lease = lease  # type: ignore[assignment]
    context.close()
    assert order == ["last", "first"]
    assert lease.calls[-2:] == ["stop_heartbeat", "release"] and context.lease is None
    assert scrubbed == [context.artifacts_dir] and context.leaks == [leak]
    assert not context.scratch.exists() and context.closed
    context.close()  # idempotent
    assert lease.calls.count("release") == 1


def test_close_purges_live_http_caches_kept_across_runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ISO-04: live HTTP caches (pickled Authorization headers) never outlive a session: those older versions left in
    <E2E_CACHE_DIR>/http-cache are deleted at close; offline caches (dummy token) stay shared; the CLIs of the
    session keep their live caches in the run's scratch."""
    monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor: [])
    context = new_context(tmp_path)
    shared = context.settings.cache_dir / "http-cache"
    for name in ("v1.6.1-admin", "v1.6.1-oracle", "v1.6.1-offline"):
        (shared / name).mkdir(parents=True)
        (shared / name / "responses.sqlite").write_text("pickled Authorization: Bearer ghp_x")
    built: list[dict[str, Any]] = []
    monkeypatch.setattr(
        "otterdog_e2e.otterdog.runner.OtterdogCli", lambda *a, **k: built.append(k) or SimpleNamespace()
    )
    context.cli(SimpleNamespace(), SimpleNamespace(), name="x", offline=True)  # type: ignore[arg-type]
    assert built[0]["http_cache_root"] == context.scratch / "http-cache"
    context.close()
    assert sorted(entry.name for entry in shared.iterdir()) == ["v1.6.1-offline"]


def test_close_keeps_scratch_with_keep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """--e2e-keep keeps the scratch dir; a failing scrub is recorded."""
    monkeypatch.setattr(
        "otterdog_e2e.report.scrub_artifacts", lambda root, redactor: (_ for _ in ()).throw(OSError("x"))
    )
    context = new_context(tmp_path, keep=True)
    context.close()
    assert context.scratch.is_dir()
    assert context.scrub_error is not None and "OSError" in context.scrub_error


# --- live session -----------------------------------------------------------------------------------------------------
def test_ensure_live_builds_everything_in_order(tmp_path: Path, live: LiveFakes) -> None:
    """target -> verify (marker required) -> probe -> lease (configs repo) + heartbeat; run.json updated."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    assert context.live_error is None and context.is_live
    assert live.calls == ["env", "target", "verify(marker=True)", "probe", "lease(repo=otterdog-e2e-configs)"]
    assert live.lease.held and live.lease.heartbeat and context.lease is live.lease
    assert context.capabilities is not None and context.capabilities.has(Cap.PUBLIC_REPOS)
    assert context.docker_ok is False and context.app_ok is False
    assert context.extras["app_reason"] == "no GitHub App configured"
    run = json.loads((context.artifacts_dir / "run.json").read_text())
    assert run["target"] == {"name": "fake", "profile": "free", "org": FAKE_ORG, "plan": "free"}
    assert run["plan"] == "free"
    assert "public_repos" in run["capabilities"]["caps"]
    context.ensure_live()
    assert live.calls.count("probe") == 1


def test_ensure_live_failure_is_stored_once(tmp_path: Path, live: LiveFakes) -> None:
    """A failing verification is stored (redacted) and never retried; nothing is leased."""
    live.verify_error = SafetyError("org id mismatch")
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    context.ensure_live()
    assert context.live_error == "SafetyError: org id mismatch"
    assert live.calls.count("verify(marker=True)") == 1
    assert not context.is_live and context.verified is None and context.lease is None
    assert "acquire" not in live.lease.calls


def test_ensure_live_lease_busy(tmp_path: Path, live: LiveFakes) -> None:
    """A busy lease makes the live session fail with the holder."""
    live.lease.busy = True
    live.lease.holder = {"run_id": OTHER_RUN, "holder": "ci:x/actions/runs/1"}
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    assert context.live_error is not None and "LeaseBusy" in context.live_error and OTHER_RUN in context.live_error
    assert not context.is_live


def test_ensure_live_interrupted_never_leaves_a_live_session_without_the_lease(
    tmp_path: Path, live: LiveFakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """F1: an interruption while waiting for the lease (pytest-timeout's Failed is a BaseException) is stored, the
    partial live state is dropped and the interruption propagates: later live items fail instead of writing without
    the lease."""

    class Interrupted(BaseException):
        """Stand-in for pytest-timeout's Failed (an OutcomeException, not an Exception)."""

    def acquire(**kwargs: Any) -> None:
        """Interrupted while waiting for a busy lease."""
        raise Interrupted("Timeout (>600.0s) from pytest-timeout.")

    monkeypatch.setattr(live.lease, "acquire", acquire)
    context = new_context(tmp_path, target="free")
    with pytest.raises(Interrupted):
        context.ensure_live()
    assert context.live_error is not None and "Timeout" in context.live_error
    assert not context.is_live and context.verified is None and context.lease is None
    context.ensure_live()  # never retried: the stored error is reported by every live item
    assert not context.is_live


def test_a_lost_lease_ends_the_live_session(tmp_path: Path, live: LiveFakes) -> None:
    """is_live requires the lease to be held: once it is lost, live items and fixtures fail with the reason."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    assert context.is_live and context.live_problem() is None
    live.lease.held = False  # a failed renewal (taken over or deleted)
    assert not context.is_live and "was lost" in (context.live_problem() or "")


def test_one_session_per_run_id_and_scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """DESTR-03: a second session reusing a running session's run id on the same machine is refused at start (it would
    share, and at its end delete, the first session's scratch); a context that never started does not delete a
    scratch another session holds; the first session's close still drops it."""
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *a: None)
    monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor: [])
    first = new_context(tmp_path)
    first.start_session()
    (first.scratch / "http-cache").mkdir()
    second = new_context(tmp_path)  # same run id, same cache dir
    with pytest.raises(ContextError, match="in use by another session"):
        second.start_session()
    second.close()
    assert (first.scratch / "http-cache").is_dir()
    first.close()
    assert not first.scratch.exists()
    third = new_context(tmp_path)  # the run id is free again on this machine
    third.start_session()
    third.close()


def test_a_lost_lease_stops_every_write(tmp_path: Path, live: LiveFakes, monkeypatch: pytest.MonkeyPatch) -> None:
    """DESTR-03: once the lease is lost, write clients, guarded applies and live otterdog commands are refused."""
    monkeypatch.setattr("otterdog_e2e.otterdog.runner.OtterdogCli", lambda *a, **k: SimpleNamespace(live_check=None))
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    client = context.http("admin", write=True)
    assert client.write_guard is not None
    client.write_guard()  # held: nothing refused
    manager = context.baseline_manager(FakeCli(), SimpleNamespace())  # type: ignore[arg-type]
    cli = context.cli(SimpleNamespace(), SimpleNamespace(), name="x")  # type: ignore[arg-type]
    offline = context.cli(SimpleNamespace(), SimpleNamespace(), name="y", offline=True)  # type: ignore[arg-type]
    assert offline.live_check is None
    live.lease.held = False
    for check in (client.write_guard, manager.write_check, cli.live_check):
        assert check is not None
        with pytest.raises(SafetyError, match=r"org lease of run .* was lost"):
            check()
    context.lease = None  # released (session end): nothing to refuse any more
    context.check_lease_not_lost()


def test_ensure_live_without_target(tmp_path: Path) -> None:
    """No target: live_error explains how to pass one."""
    context = new_context(tmp_path)
    context.ensure_live()
    assert context.live_error is not None and "--e2e-target" in context.live_error


def test_clients_are_scoped_and_cached(tmp_path: Path, live: LiveFakes) -> None:
    """Read clients are read-only; write clients carry the VerifiedOrg; clients are cached per identity and mode."""
    context = new_context(tmp_path, target="free")
    context.load_target()
    read = context.http("admin")
    assert read.read_only and read is context.http("admin")
    with pytest.raises(ContextError, match="not been verified"):
        context.http("admin", write=True)
    context.verify()
    write = context.http("admin", write=True)
    assert not write.read_only and write.write_scope is context.verified
    with pytest.raises(ContextError, match="E2E_APPROVER_TOKEN"):
        context.http("approver")
    assert set(context.mutators()) == {"admin", "author"}


def test_purgeable_runs(tmp_path: Path, live: LiveFakes) -> None:
    """Own run always; other runs only when in the ledger and not holding an unexpired lease."""
    context = new_context(tmp_path, target="free")
    context.load_target()
    context.verify()
    live.lease.ledger_ids = [OTHER_RUN, "t3c7z8c7"]
    future = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    live.lease.holder = {"run_id": "t3c7z8c7", "holder": "other", "expires_at": future}
    assert context.purgeable(FAKE_RUN_ID)
    assert context.purgeable(OTHER_RUN)
    assert not context.purgeable("t3c7z8c7")  # active lease holder
    assert not context.purgeable("t3c7z8d8")  # not in the ledger


def test_purgeable_expired_holder(tmp_path: Path, live: LiveFakes) -> None:
    """An expired lease holder is purgeable again."""
    context = new_context(tmp_path, target="free")
    context.load_target()
    context.verify()
    live.lease.ledger_ids = [OTHER_RUN]
    live.lease.holder = {"run_id": OTHER_RUN, "expires_at": "2025-01-01T00:00:00Z"}
    assert context.purgeable(OTHER_RUN)


def test_takeover_of_a_finished_runs_lease(tmp_path: Path, live: LiveFakes) -> None:
    """janitor --run-id: the lease of that run is taken over by OrgLease.acquire (compare-and-swap, DESTR-05), never
    deleted; outside CI no holder is trusted, in CI this job's holder is."""
    context = new_context(tmp_path, target="free")
    context.load_target()
    context.verify()
    live.lease.holder = {"run_id": OTHER_RUN, "expires_at": "2099-01-01T00:00:00Z"}
    live.lease.busy = True
    context.acquire_lease(takeover_run=OTHER_RUN, heartbeat=False)
    assert not context.mutator("admin").calls_to("delete_ref")
    assert live.lease.takeovers == [(OTHER_RUN, False, None)] and live.lease.held and not live.lease.heartbeat
    ci = new_context(tmp_path / "ci", target="free", run_id="t3c7z8c7")
    ci.environ = {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "o/r", "GITHUB_RUN_ID": "7"}
    ci.load_target()
    ci.verify()
    ci.acquire_lease(takeover_run=OTHER_RUN, force_takeover=True, heartbeat=False)
    assert live.lease.takeovers[-1] == (OTHER_RUN, True, "ci:o/r/actions/runs/7")


def test_takeover_of_a_live_runs_lease_is_refused(tmp_path: Path, live: LiveFakes) -> None:
    """A run that renewed its lease recently looks alive: the takeover raises LeaseBusy, nothing is held."""
    from otterdog_e2e.github.lease import LeaseBusy

    context = new_context(tmp_path, target="free")
    context.load_target()
    context.verify()
    live.lease.holder = {"run_id": OTHER_RUN, "expires_at": "2099-01-01T00:00:00Z"}
    live.lease.busy = live.lease.takeover_refused = True
    with pytest.raises(LeaseBusy, match="renewed the org lease recently"):
        context.acquire_lease(takeover_run=OTHER_RUN, heartbeat=False)
    assert context.lease is None and not live.lease.held


# --- SUT roles --------------------------------------------------------------------------------------------------------
@dataclass
class FakeResolved:
    """Minimal ResolvedSut."""

    label: str
    sha: str
    trusted: bool
    base_sha: str | None = None
    version: str = "1.6.1"
    changed_files: list[str] = field(default_factory=list)
    source_dir: Path = Path("/nonexistent/src")

    def to_json(self) -> dict[str, Any]:
        """JSON form."""
        return {"label": self.label, "sha": self.sha, "trusted": self.trusted}


@pytest.fixture
def suts(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake resolution/installation: specs map to FakeResolved; calls are recorded."""
    resolved = {
        "release:latest": FakeResolved("v1.6.1", fake_sha("v1.6.1"), True),
        "pr:792@" + fake_sha("pr"): FakeResolved("pr792-abc1234", fake_sha("pr"), False, base_sha=fake_sha("base")),
        "sha:" + fake_sha("base"): FakeResolved("sha-base", fake_sha("base"), True),
    }
    state: dict[str, Any] = {"resolved": resolved, "installs": [], "images": []}

    def install(sut: Any, settings: Any, **kwargs: Any) -> Any:
        """Record a host install."""
        state["installs"].append(sut)
        return SimpleNamespace(sut=sut, runtime="host", version_output=f"otterdog.sh, version {sut.version}\n")

    def image_cli(sut: Any, image: Any) -> Any:
        """Record an image CLI."""
        return SimpleNamespace(
            sut=sut, runtime="docker", image=image.tag, version_output="otterdog.sh, version 1.7.0\n"
        )

    def build(sut: Any, **kwargs: Any) -> Any:
        """Record an image build."""
        state["images"].append(sut.label)
        return SimpleNamespace(tag=f"otterdog-e2e/untrusted:{sut.label}")

    monkeypatch.setattr("otterdog_e2e.sut.spec.parse_sut_spec", lambda raw: raw)
    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", lambda spec, settings, http=None: resolved[spec])
    monkeypatch.setattr("otterdog_e2e.sut.cli_install.install_cli", install)
    monkeypatch.setattr("otterdog_e2e.sut.cli_install.image_cli", image_cli)
    monkeypatch.setattr("otterdog_e2e.sut.image.build_webapp_image", build)
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", lambda token, **kw: FakeGitHubHttp(identity="anonymous"))
    return state


def test_trusted_sut_installs_on_host(tmp_path: Path, suts: dict[str, Any]) -> None:
    """A trusted SUT is installed on the host and recorded in run.json."""
    context = new_context(tmp_path)
    installed = context.installed("head")
    assert installed.runtime == "host" and installed is context.installed("head")
    assert len(suts["installs"]) == 1
    run = json.loads((context.artifacts_dir / "run.json").read_text())
    assert run["sut"]["label"] == "v1.6.1" and run["sut"]["runtime"] == "host"
    assert run["versions"]["head"] == "otterdog.sh, version 1.6.1"
    assert context.sut_label() == "v1.6.1"


def test_untrusted_sut_runs_in_its_image(tmp_path: Path, suts: dict[str, Any]) -> None:
    """A PR SUT never runs on the host: its CLI comes from the untrusted image."""
    context = new_context(tmp_path, sut="pr:792@" + fake_sha("pr"))
    installed = context.installed("head")
    assert installed.runtime == "docker" and suts["images"] == ["pr792-abc1234"] and not suts["installs"]


def test_trust_code_goes_through_grant_host_trust(
    tmp_path: Path, suts: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """--e2e-trust-code <exact sha>: cli_install.grant_host_trust installs the untrusted SUT on the host from an
    interactive terminal only; CI and non-interactive sessions are refused; a code naming another sha changes nothing."""
    spec = "pr:792@" + fake_sha("pr")
    monkeypatch.setattr(context_sut, "interactive_terminal", lambda: True)
    context = new_context(tmp_path, sut=spec, trust_code=fake_sha("pr").upper())
    assert context.installed("head").runtime == "host" and suts["installs"][0].trusted
    assert not context.resolve(spec).trusted  # the resolved SUT stays untrusted (webapp token, source cleanup)
    assert new_context(tmp_path, sut=spec, trust_code=fake_sha("other")).installed("head").runtime == "docker"
    assert len(suts["installs"]) == 1
    for environ in ({"CI": "true"}, {"GITHUB_ACTIONS": "true"}):
        ci = E2EContext.create(
            E2EOptions(sut=spec, trust_code=fake_sha("pr")), environ=environ, settings=make_settings(tmp_path)
        )
        with pytest.raises(SafetyError, match="refused when CI is set"):
            ci.installed("head")
    monkeypatch.setattr(context_sut, "interactive_terminal", lambda: False)
    with pytest.raises(SafetyError, match="interactive terminal"):
        new_context(tmp_path, sut=spec, trust_code=fake_sha("pr")).installed("head")
    assert len(suts["installs"]) == 1


def test_interactive_terminal_reads_the_original_stdin(monkeypatch: pytest.MonkeyPatch) -> None:
    """pytest replaces sys.stdin while capturing: the original stdin decides; closed or missing stdin is not a tty."""

    class Stream:
        """A stdin stand-in."""

        def __init__(self, tty: bool | None) -> None:
            """``tty`` None: a closed stream."""
            self.tty = tty

        def isatty(self) -> bool:
            """The configured answer (ValueError when closed)."""
            if self.tty is None:
                raise ValueError("I/O operation on closed file")
            return self.tty

    for stream, expected in ((Stream(True), True), (Stream(False), False), (Stream(None), False), (None, False)):
        monkeypatch.setattr(context_helpers.sys, "__stdin__", stream)
        assert context_helpers.interactive_terminal() is expected


def test_close_deletes_untrusted_sources(tmp_path: Path, suts: dict[str, Any]) -> None:
    """Session end: sut.spec.cleanup_source deletes untrusted exports; trusted caches stay."""
    pr_spec = "pr:792@" + fake_sha("pr")
    untrusted, trusted = tmp_path / "untrusted-export", tmp_path / "trusted-cache"
    for directory in (untrusted, trusted):
        directory.mkdir()
        (directory / "pyproject.toml").write_text("x")
    suts["resolved"][pr_spec].source_dir = untrusted
    suts["resolved"]["release:latest"].source_dir = trusted
    context = new_context(tmp_path, sut=pr_spec)
    context.resolve(pr_spec)
    context.resolve("release:latest")
    context.close()
    assert not untrusted.exists() and (trusted / "pyproject.toml").is_file()


def test_resolution_uses_one_anonymous_read_only_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """resolve_sut gets the anonymous read-only client for every spec (pr: base ref lookups): never a token."""
    built: list[tuple[str | None, dict[str, Any]]] = []
    seen: list[Any] = []

    def http(token: str | None, **kwargs: Any) -> FakeGitHubHttp:
        """Record the construction."""
        built.append((token, kwargs))
        return FakeGitHubHttp(identity=kwargs["identity"], read_only=kwargs["read_only"])

    def resolve_sut(spec: Any, settings: Any, *, http: Any = None) -> FakeResolved:
        """Record the client."""
        seen.append(http)
        return FakeResolved(spec.raw, fake_sha(spec.raw), spec.trusted)

    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", http)
    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", resolve_sut)
    context = new_context(tmp_path)
    context.resolve("pr:792@" + fake_sha("pr"))
    context.resolve("release:latest")
    assert built == [(None, {"read_only": True, "identity": "anonymous"})]
    assert len(seen) == 2 and seen[0] is seen[1] and seen[0].read_only and seen[0].identity == "anonymous"


def test_reset_sut_must_be_trusted(tmp_path: Path, suts: dict[str, Any]) -> None:
    """The reset SUT is never untrusted code."""
    context = new_context(tmp_path, reset_sut="pr:792@" + fake_sha("pr"))
    with pytest.raises(SafetyError, match="reset SUT"):
        context.installed("reset")


def test_base_spec_auto_is_the_merge_base(tmp_path: Path, suts: dict[str, Any]) -> None:
    """--e2e-base-sut auto resolves to the SUT's merge base; missing options raise ContextError."""
    context = new_context(tmp_path, sut="pr:792@" + fake_sha("pr"), base_sut="auto")
    assert context.spec_for("base") == "sha:" + fake_sha("base")
    assert context.installed("base").runtime == "host"
    with pytest.raises(ContextError, match="--e2e-base-sut"):
        new_context(tmp_path).spec_for("base")
    with pytest.raises(ContextError, match="no merge base"):
        new_context(tmp_path, base_sut="auto").spec_for("base")
    with pytest.raises(ValueError, match="unknown SUT role"):
        context.spec_for("other")


def test_config_token_rules(tmp_path: Path, suts: dict[str, Any]) -> None:
    """OTTERDOG_CONFIG_TOKEN: config_reader, else admin for trusted SUTs only (SEC-11)."""
    context = new_context(tmp_path)
    context.target = make_target()
    context.identities = make_identities("admin")
    assert context.config_token() == context.identities["admin"].token
    context.identities = make_identities("admin", "config_reader")
    assert context.config_token() == context.identities["config_reader"].token
    untrusted = new_context(tmp_path, sut="pr:792@" + fake_sha("pr"))
    untrusted.target = make_target()
    untrusted.identities = make_identities("admin")
    with pytest.raises(ContextError, match="config_reader"):
        untrusted.config_token()


# --- webapp -----------------------------------------------------------------------------------------------------------
class FakeStack:
    """WebappStack stand-in recording into a shared event list."""

    def __init__(self, events: list[str], *, fail_init: bool = False) -> None:
        """Bind the event list."""
        self.events = events
        self.fail_init = fail_init
        self.webhook_url = "http://127.0.0.1:5000/github-webhook/receive"
        self.base_url = "http://127.0.0.1:5000"

    def up(self, *, timeout: float = 300) -> None:
        """Record."""
        self.events.append("up")

    def init(self) -> None:
        """Record (or fail)."""
        self.events.append("init")
        if self.fail_init:
            raise RuntimeError("init failed")

    def wait_ready(self, *, timeout: float = 300) -> None:
        """Record."""
        self.events.append("wait_ready")

    def deployed_version(self) -> str:
        """A version."""
        return "1.6.1"

    def save_logs(self) -> None:
        """Record."""
        self.events.append("save_logs")

    def down(self) -> None:
        """Record."""
        self.events.append("down")


class FakeFlow:
    """ConfigRepoFlow stand-in."""

    def __init__(self, events: list[str], main: str | None = None, **kwargs: Any) -> None:
        """Record the constructor arguments."""
        self.events = events
        self.main = main
        self.kwargs = kwargs
        self.repo = kwargs.get("repo", "e2e-config")

    def main_config(self) -> str | None:
        """Current main text."""
        return self.main

    def reset_main(self, text: str, *, message: str, identity: str = "admin") -> str:
        """Record and store."""
        self.events.append("reset_main")
        self.main = text
        return fake_sha(text)

    def cleanup(self) -> None:
        """Record."""
        self.events.append("cleanup")


@pytest.fixture
def webapp_context(tmp_path: Path, live: LiveFakes, monkeypatch: pytest.MonkeyPatch) -> tuple[E2EContext, list[str]]:
    """A verified context whose stack, flow and otterdog.json writer record into one event list."""
    events: list[str] = []
    monkeypatch.setattr("otterdog_e2e.webapp.stack.WebappStack", lambda settings, **kw: FakeStack(events))
    monkeypatch.setattr("otterdog_e2e.webapp.stack.WebappSettings", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr("otterdog_e2e.config_repo.ConfigRepoFlow", lambda **kw: FakeFlow(events, **kw))
    monkeypatch.setattr("otterdog_e2e.otterdog.workspace.webapp_otterdog_json", lambda *a, **k: {"organizations": []})
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    credentials = AppCredentials("1", "-----BEGIN PRIVATE KEY-----\nx\n-----END PRIVATE KEY-----", "s3cret-hook", None)
    context._memos["app_credentials"] = credentials
    context._memos["app_auth"] = FakeAppAuth()  # owned by and installed on the fake org only (verify_app passes)
    context._memos["image:head"] = SimpleNamespace(tag="otterdog-e2e/otterdog:v1.6.1")
    context._memos["resolved:release:latest"] = FakeResolved("v1.6.1", fake_sha("v"), True)
    mutator = context.mutator("admin")
    original = mutator.commit_files

    def commit(repo: str, branch: str, files: Any, message: str) -> str:
        """Record the otterdog.json commit."""
        events.append(f"commit:{repo}:{','.join(files)}")
        return original(repo, branch, files, message)

    mutator.commit_files = commit  # type: ignore[method-assign]
    return context, events


def test_start_webapp_order(webapp_context: tuple[E2EContext, list[str]]) -> None:
    """stack up -> config repo main = baseline -> otterdog.json -> /internal/init -> wait_ready; ready time kept."""
    context, events = webapp_context
    baseline = FakeBaselineManager("// baseline of the run\n")
    before = datetime.now(UTC)
    deployment = context.start_webapp(baseline, SimpleNamespace(url="https://github.com/x/y#f@sha"))  # type: ignore[arg-type]
    assert events == ["up", "reset_main", "commit:otterdog-e2e-configs:otterdog.json", "init", "wait_ready"]
    assert context.extras["webapp_ready_at"] >= before
    assert context.run_info["versions"]["webapp"] == "1.6.1"
    context.stop_webapp(deployment)
    assert events[-2:] == ["save_logs", "down"]


def test_start_webapp_failure_stops_the_stack(
    webapp_context: tuple[E2EContext, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failing init brings the stack down and propagates."""
    context, events = webapp_context
    monkeypatch.setattr(
        "otterdog_e2e.webapp.stack.WebappStack", lambda settings, **kw: FakeStack(events, fail_init=True)
    )
    with pytest.raises(RuntimeError, match="init failed"):
        context.start_webapp(FakeBaselineManager(), SimpleNamespace(url="u"))  # type: ignore[arg-type]
    assert events[-2:] == ["save_logs", "down"]


def test_publish_otterdog_json_is_idempotent(webapp_context: tuple[E2EContext, list[str]], live: LiveFakes) -> None:
    """Same content on the configs repo: no commit."""
    context, events = webapp_context
    live.oracle.add_repo("otterdog-e2e-configs")
    live.oracle.add_file(
        "otterdog-e2e-configs", "otterdog.json", json.dumps({"organizations": []}, indent=2) + "\n", ref="main"
    )
    context.publish_otterdog_json(SimpleNamespace(url="u"))  # type: ignore[arg-type]
    assert not [e for e in events if e.startswith("commit")]


def test_webapp_deployment_external_and_none(webapp_context: tuple[E2EContext, list[str]]) -> None:
    """external needs a URL; none cannot serve webapp tests."""
    from otterdog_e2e.settings import WebappSpec

    context, _events = webapp_context
    context.target = make_target(webapp=WebappSpec("external", "http://127.0.0.1:5000", None, "v", "s", 1, 5000))
    deployment = context.webapp_deployment()
    assert type(deployment).__name__ == "ExternalWebapp" and deployment.base_url == "http://127.0.0.1:5000"
    context.target = make_target(webapp=WebappSpec("external", None, None, "v", "s", 1, 5000))
    with pytest.raises(ContextError, match="E2E_EXTERNAL_URL"):
        context.webapp_deployment()
    context.target = make_target(webapp=WebappSpec("none", None, None, "v", "s", 1, 5000))
    with pytest.raises(ContextError, match="'none'"):
        context.webapp_deployment()


def test_start_relay_since_ready_time(
    webapp_context: tuple[E2EContext, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relay forwards to the deployment's receiver, since the webapp ready time, for the checked installation."""
    context, _events = webapp_context
    created: dict[str, Any] = {}

    class Relay:
        """DeliveryRelay stand-in."""

        def __init__(self, app: Any, **kwargs: Any) -> None:
            """Record."""
            created.update(kwargs)

        def start(self) -> None:
            """Record."""
            created["started"] = True

    ready = datetime(2026, 10, 2, 12, tzinfo=UTC)
    context.extras["webapp_ready_at"] = ready
    context._memos["app_auth"] = object()
    context._memos["installation_id"] = 4242
    monkeypatch.setattr("otterdog_e2e.webhooks.relay.DeliveryRelay", Relay)
    context.start_relay(FakeStack([]))  # type: ignore[arg-type]
    assert created["since"] == ready and created["installation_id"] == 4242 and created["started"]
    assert created["forward_url"].endswith("/github-webhook/receive") and created["secret"] == "s3cret-hook"


def test_webapp_deployment_refuses_an_app_reaching_other_orgs(
    webapp_context: tuple[E2EContext, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """DESTR-01: the private key never reaches a WebappStack when the App is owned by another account or installed
    outside the test orgs; the check is repeated at every start (GET /app re-read)."""
    created: list[Any] = []
    monkeypatch.setattr("otterdog_e2e.webapp.stack.WebappStack", lambda settings, **kw: created.append(settings))
    context, _events = webapp_context
    context.webapp_deployment()
    context.webapp_deployment()
    app = context._memos["app_auth"]
    assert len(created) == 2 and app.calls.count(("get_app", (True,))) == 2
    foreign = {"id": 9, "account": {"login": "acme-production", "id": 99, "type": "Organization"}}
    context._memos["app_auth"] = FakeAppAuth(extra_installations=[foreign])
    with pytest.raises(SafetyError, match="installed outside the test organizations"):
        context.webapp_deployment()
    context._memos["app_auth"] = FakeAppAuth(owner={"login": "some-dev", "id": 5, "type": "User"})
    with pytest.raises(SafetyError, match="owned by 'some-dev'"):
        context.webapp_deployment()
    assert len(created) == 2


def test_check_app_and_installation_id_verify_the_app(tmp_path: Path, live: LiveFakes) -> None:
    """check_app marks an unsafe App (app_unsafe: the webapp gate fails its items); installation_id refuses it."""
    context = new_context(tmp_path, target="free")
    context.load_target()
    context._memos["app_credentials"] = AppCredentials("1", "pem", "s3cret-hook", None)
    context._memos["app_auth"] = FakeAppAuth()
    assert context.check_app() == (True, "") and "app_unsafe" not in context.extras
    assert context.run_info["app"] == {"slug": "otterdog-e2e-test", "owner": FAKE_ORG, "installations": 1}
    context._memos["app_auth"] = FakeAppAuth(owner={"login": "acme-production", "id": 99, "type": "Organization"})
    ok, reason = context.check_app()
    assert not ok and reason.startswith("unsafe GitHub App: SafetyError") and context.extras["app_unsafe"] is True
    with pytest.raises(SafetyError, match="not by the test organization"):
        context.installation_id()
    context._memos["app_auth"] = FakeAppAuth()
    assert context.check_app()[0] and "app_unsafe" not in context.extras
    assert context.installation_id() == 4242


def test_installation_id_preflight(tmp_path: Path, live: LiveFakes) -> None:
    """installation_id fails with the problems of an unusable installation."""
    from otterdog_e2e.testing.fakes import FakeAppAuth

    context = new_context(tmp_path, target="free")
    context.load_target()
    app = FakeAppAuth(permissions={})
    context._memos["app_auth"] = app
    with pytest.raises(ContextError, match="permissions missing"):
        context.installation_id()


# --- webapp case --------------------------------------------------------------------------------------------------------
class RecordingWorkspace:
    """ConfigWorkspace stand-in recording written texts."""

    def __init__(self) -> None:
        """Start empty."""
        self.base: str | None = None
        self.head: str | None = None

    def write_base_config(self, text: str) -> None:
        """Record the -BASE text."""
        self.base = text

    def write_org_config(self, text: str) -> None:
        """Record the head text."""
        self.head = text


class FakeApi:
    """WebappApi stand-in."""

    def __init__(self) -> None:
        """Start empty."""
        self.quiesced: list[str] = []

    def quiesce(self, *, org_id: str, quiet_for: float = 15, timeout: float = 180) -> None:
        """Record."""
        self.quiesced.append(org_id)


def test_config_flow_is_guarded_by_the_baseline(tmp_path: Path, live: LiveFakes) -> None:
    """The flow's guard is the one BaselineManager.guard_config_change (SEC-07); refusals propagate."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    baseline = FakeBaselineManager()
    flow = context.config_flow(baseline)  # type: ignore[arg-type]
    assert flow.guard == baseline.guard_config_change
    assert flow.repo == f"e2e-{FAKE_RUN_ID}-config" and flow.relay is None
    flow.guard_config("main text", "head text")
    assert baseline.calls_to("guard_config_change") == [(("main text", "head text"), {"allow_invalid_head": True})]
    refusing = FakeBaselineManager(refuse="would delete a protected repository")
    with pytest.raises(SafetyError, match="protected repository"):
        context.config_flow(refusing).guard_config("main", "head")  # type: ignore[arg-type]


def test_webapp_case_before_and_after(tmp_path: Path, live: LiveFakes) -> None:
    """Before: main reset to baseline, webapp quiet, comment ids; after: cleanup, main restored, run objects removed."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    events: list[str] = []
    flow = FakeFlow(events, main="// stale\n", repo="e2e-t3c7z8a5-config")
    live.oracle.add_pull("e2e-t3c7z8a5-config", {"number": 7})
    live.oracle.add_pr_comment("e2e-t3c7z8a5-config", 7, "old")
    baseline = FakeBaselineManager("// baseline\n")
    api = FakeApi()
    case = context.begin_webapp_case(flow, api, baseline)  # type: ignore[arg-type]
    assert events == ["reset_main"] and flow.main == "// baseline\n" and api.quiesced == [FAKE_ORG]
    assert len(case.seen_comment_ids) == 1
    flow.main = "// changed by the test\n"
    reset_cli = FakeCli(workspace=RecordingWorkspace())
    context.end_webapp_case(case, baseline=baseline, reset_cli=reset_cli, org_level=True)  # type: ignore[arg-type]
    assert events == ["reset_main", "cleanup", "reset_main"]
    assert reset_cli.workspace.head == "// baseline\n"
    [(_args, kwargs)] = baseline.calls_to("guarded_apply")
    assert kwargs == {"repo_filter": f"e2e-{FAKE_RUN_ID}-*", "delete": True}
    assert baseline.calls_to("reset")


def test_webapp_case_cleanup_errors_are_raised_together(tmp_path: Path, live: LiveFakes) -> None:
    """Every after-step runs; failures are reported at once."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    flow = FakeFlow([], main="// baseline\n")
    flow.cleanup = lambda: (_ for _ in ()).throw(RuntimeError("cannot close"))  # type: ignore[method-assign]
    baseline = FakeBaselineManager("// baseline\n", refuse="non purgeable removal")
    case = context.begin_webapp_case(flow, FakeApi(), baseline)  # type: ignore[arg-type]
    with pytest.raises(ContextError) as excinfo:
        context.end_webapp_case(
            case, baseline=baseline, reset_cli=FakeCli(workspace=RecordingWorkspace()), org_level=False
        )  # type: ignore[arg-type]
    assert "cannot close" in str(excinfo.value) and "non purgeable removal" in str(excinfo.value)


# --- renderer -------------------------------------------------------------------------------------------------------
def test_renderer_profile_hides_keys_github_did_not_return(tmp_path: Path) -> None:
    """render.org_profile: returned keys are managed with their live value (null included), missing ones hidden."""
    context = new_context(tmp_path)
    context.target = make_target()
    org_json = {
        "login": FAKE_ORG,
        "id": 1,
        "description": "[otterdog-e2e] profile test",
        "name": "E2E",
        "email": None,
        "plan": {"name": "free"},
    }  # no billing_email (a token without admin:org), blog, location, company or twitter_username
    context.verified = make_verified_org(org_json=org_json)
    context.capabilities = from_plan("free")
    renderer = context.renderer(offline_template())
    assert renderer.org_profile == {"description": "[otterdog-e2e] profile test", "name": "E2E", "email": None}
    text = renderer.render()
    assert "billing_email:: null" in text and "twitter_username:: null" in text
    assert 'name: "E2E"' in text and "email: null" in text and "billing_email: null" not in text


# --- templates and trust -------------------------------------------------------------------------------------------
class StubPublisher:
    """TemplatePublisher stand-in: publish() returns a pinned ref with its tag."""

    created: list[StubPublisher] = []

    def __init__(self, http: Any, verified: Any, repo: str) -> None:
        """Record the construction."""
        self.http, self.repo, self.published = http, repo, []
        StubPublisher.created.append(self)

    def publish(self, sut: Any) -> TemplateRef:
        """Record and return the published ref."""
        self.published.append(sut.label)
        commit = fake_sha("template")
        url = f"https://github.com/{FAKE_ORG}/{self.repo}#otterdog-defaults.libsonnet@{commit}"
        return TemplateRef(url, self.repo, "otterdog-defaults.libsonnet", commit, tag=f"sut-{sut.label}-0badc0de")


@pytest.fixture
def templates(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Fake resolution (pr: untrusted, release: trusted) and the stub publisher."""
    resolved = {
        "pr:792@" + fake_sha("pr"): SimpleNamespace(
            spec=SimpleNamespace(kind="pr"), label="pr792-abc1234", sha=fake_sha("pr"), trusted=False
        ),
        "release:latest": SimpleNamespace(
            spec=SimpleNamespace(kind="release"), label="v1.6.1", sha=fake_sha("v1.6.1"), trusted=True
        ),
    }
    StubPublisher.created = []
    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", lambda spec, settings, http=None: resolved[spec.raw])
    monkeypatch.setattr("otterdog_e2e.sut.template.TemplatePublisher", StubPublisher)
    return resolved


def test_template_publishing_needs_the_lease_and_references_its_tag(
    tmp_path: Path, live: LiveFakes, templates: dict[str, Any]
) -> None:
    """Publishing (auto mode, pr SUT) only while this session holds the lease; the tag is recorded in the lease."""
    context = new_context(tmp_path, target="free", sut="pr:792@" + fake_sha("pr"))
    context.load_target()
    context.verify()
    with pytest.raises(ContextError, match="publishing the template of pr792-abc1234 needs the org lease"):
        context.template_for("head")
    assert StubPublisher.created == []
    upstream = context.template_for("reset")  # release SUT: the upstream template, no lease, no publisher
    assert upstream.repo_name == "otterdog" and upstream.tag is None and StubPublisher.created == []
    context.acquire_lease(heartbeat=False)
    template = context.template_for("head")
    (publisher,) = StubPublisher.created
    assert publisher.published == ["pr792-abc1234"] and publisher.repo == "otterdog-e2e-defaults"
    assert publisher.http.write_scope is context.verified  # write-scoped admin client
    assert template.tag == "sut-pr792-abc1234-0badc0de" and live.lease.refs == [f"tags/{template.tag}"]
    assert context.template_for("head") is template and len(live.lease.refs) == 1  # memoized


def test_require_lease_refuses_a_lost_lease(tmp_path: Path, live: LiveFakes) -> None:
    """A lease taken over by another session (held False) no longer authorizes publishing."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    assert context.require_lease("x") is live.lease
    live.lease.held = False
    with pytest.raises(ContextError, match="x needs the org lease"):
        context.require_lease("x")


def test_sut_trust_decisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """pr: is untrusted and release: trusted without resolving; sha: resolves (once); errors leave it undecided."""
    calls: list[str] = []
    trust = {"sha:" + fake_sha("main"): True, "sha:" + fake_sha("fork"): False}

    def resolve_sut(spec: Any, settings: Any, *, http: Any = None) -> SimpleNamespace:
        """Record; fail for unknown shas."""
        calls.append(spec.raw)
        if spec.raw not in trust:
            raise RuntimeError("mirror fetch failed")
        return SimpleNamespace(trusted=trust[spec.raw])

    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", resolve_sut)
    assert new_context(tmp_path, sut="pr:792@" + fake_sha("pr")).sut_trusted() is False
    assert new_context(tmp_path, sut="release:latest").sut_trusted() is True
    assert calls == []
    fork = new_context(tmp_path, sut="sha:" + fake_sha("fork"))
    assert fork.sut_trusted() is False and fork.sut_trusted() is False and calls == ["sha:" + fake_sha("fork")]
    assert new_context(tmp_path, sut="sha:" + fake_sha("main")).sut_trusted() is True
    broken = new_context(tmp_path, sut="sha:" + fake_sha("gone"))
    assert broken.sut_trusted() is None and broken.sut_trusted() is None
    assert calls.count("sha:" + fake_sha("gone")) == 1


# --- variables, reporting ------------------------------------------------------------------------------------------------
def test_scenario_variables(tmp_path: Path, live: LiveFakes) -> None:
    """Live variables use the declared logins (F8), teams and the plan; offline ones the offline org."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    variables = context.scenario_variables()
    assert variables["p"] == f"e2e-{FAKE_RUN_ID}" and variables["org"] == FAKE_ORG and variables["plan"] == "free"
    assert variables["logins"]["approver"] == "e2e-approver"  # declared even without a token
    assert variables["teams"] == {
        "admin": "otterdog-admins",
        "approval": "project-leads",
        "contributors": "e2e-contributors",
    }
    assert variables["app_slug"] == ""
    offline = context.offline_variables()
    assert offline["org"] == "e2e-offline" and offline["plan"] == "free" and offline["logins"] == {}


def test_rate_remaining_lowest_per_identity(tmp_path: Path, live: LiveFakes) -> None:
    """The lowest core budget seen per identity."""
    context = new_context(tmp_path, target="free")
    context.load_target()
    context.http("admin").rate_remaining = 900  # type: ignore[attr-defined]
    context.verify()
    context.http("admin", write=True).rate_remaining = 700  # type: ignore[attr-defined]
    context.http("author").rate_remaining = 4000  # type: ignore[attr-defined]
    assert context.rate_remaining() == {"admin": 700, "author": 4000}
    assert context.min_rate_threshold() == 800


def test_run_info_and_results_are_redacted(tmp_path: Path) -> None:
    """run.json and results.jsonl never contain registered secrets."""
    secret = "e2e-unit-secret-" + fake_sha("ctx")[:12]
    REDACTOR.add(secret)
    context = new_context(tmp_path)
    context.write_run_info(note=f"token {secret}")
    context.append_result({"nodeid": "x", "failure": f"boom {secret}"})
    context.append_result({"nodeid": "y"})
    assert secret not in (context.artifacts_dir / "run.json").read_text()
    lines = (context.artifacts_dir / "results.jsonl").read_text().splitlines()
    assert len(lines) == 2 and json.loads(lines[0])["failure"] == "boom ***"


def test_known_bugs_and_change(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """known_bugs.yaml is optional; the change under test is --e2e-change, else N of a pr: SUT, and its references
    are gathered once."""
    context = new_context(tmp_path)
    assert context.known_bugs() == {} and context.change() is None and context.change_spec() is None
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "known_bugs.yaml").write_text("- {id: KB-001, title: t}\n")
    monkeypatch.setattr("otterdog_e2e.known_bugs.load", lambda path: {"KB-001": SimpleNamespace(id="KB-001")})
    assert set(new_context(tmp_path).known_bugs()) == {"KB-001"}
    loaded: list[tuple[Path, Path, ChangeId]] = []
    monkeypatch.setattr(
        "otterdog_e2e.changes.load_change",
        lambda *args: loaded.append(args) or "spec",  # type: ignore[func-returns-value]
    )
    context = new_context(tmp_path, change="check-merge")
    assert context.change() == ChangeId(slug="check-merge") and context.change_spec() == "spec"
    assert context.change_spec() == "spec" and loaded == [
        (tmp_path / "scenarios", tmp_path / "tests", context.change())
    ]
    assert new_context(tmp_path, sut=f"pr:792@{'a' * 40}").change() == ChangeId(pr=792)
    with pytest.raises(ChangeError):
        new_context(tmp_path, change="Not a change").change_spec()


def test_offline_sut_pair(tmp_path: Path, suts: dict[str, Any]) -> None:
    """Offline sides: offline CLIs on the offline org, recorders per role, artifacts under base/ and head/."""
    context = new_context(tmp_path, sut="tag:v1.6.1", base_sut="release:latest")
    head = FakeResolved("v1.6.1", fake_sha("h"), True, version="1.6.1")
    suts["resolved"]["tag:v1.6.1"] = head
    for role in ("base", "head"):
        sut = suts["resolved"]["release:latest"] if role == "base" else head
        context._memos[f"installed:{role}"] = SimpleNamespace(
            sut=SimpleNamespace(label=sut.label, trusted=True),
            runtime="host",
            version_output="otterdog.sh, version 1.6.1\n",
        )
    pair = context.sut_pair(live=False)
    base, head_side = pair
    assert base.role == "base" and head_side.role == "head" and pair.head is head_side
    assert base.cli.offline and base.cli.verified is None and base.cli.workspace.org == "e2e-offline"
    assert base.cli.artifacts_dir == context.artifacts_dir / "base" / "offline"
    assert base.recorder.out_file == context.artifacts_dir / "observations" / "base.jsonl"
    assert ("1.6.1", "<VERSION>") in base.recorder.normalize_ctx.literals
    for side in pair:  # each side's own workspace root is hidden: printed config paths compare equal
        root = side.cli.workspace.root
        assert root.name == f"diff-offline-{side.role}"
        assert (str(root), "<WORKSPACE>") in side.recorder.normalize_ctx.literals
        assert ("/ws/", "<WORKSPACE>/") not in side.recorder.normalize_ctx.literals  # host runtime
    from otterdog_e2e.otterdog.output import normalize_text

    for side in pair:
        printed = f"{side.cli.workspace.root}/orgs/e2e-offline/e2e-offline.jsonnet:43:3 syntax error\n"
        assert normalize_text(printed, side.recorder.normalize_ctx).startswith(
            "<WORKSPACE>/orgs/e2e-offline/e2e-offline.jsonnet:43:3"
        )
    assert context.sut_pair(live=False) is pair
    assert context_module.SutPair is type(pair)
    assert new_run_context(FAKE_RUN_ID).run_id == context.run_ctx.run_id


def test_workspace_literals_of_host_and_container_sides(tmp_path: Path) -> None:
    """A side's workspace root (given and resolved) becomes <WORKSPACE>; a container side also hides its mount."""
    real = tmp_path / "real" / "diff-offline-head"
    real.mkdir(parents=True)
    link = tmp_path / "link"
    link.symlink_to(tmp_path / "real")
    host = SimpleNamespace(workspace=SimpleNamespace(root=link / "diff-offline-head"), runtime=SimpleNamespace())
    assert context_module.workspace_literals(host) == [  # type: ignore[arg-type]
        (str(link / "diff-offline-head"), "<WORKSPACE>"),
        (str(real), "<WORKSPACE>"),
    ]
    docker = SimpleNamespace(workspace=SimpleNamespace(root=real), runtime=SimpleNamespace(in_container=True))
    assert context_module.workspace_literals(docker) == [  # type: ignore[arg-type]
        (str(real), "<WORKSPACE>"),
        ("/ws/", "<WORKSPACE>/"),
    ]


# --- webapp tier extras: app_id, the dtrack mock, the blueprint helper ------------------------------------------------
def test_scenario_variables_carry_the_app_id(tmp_path: Path, live: LiveFakes) -> None:
    """app_id: the e2e App id (app-bound status checks, Integration bypass actors), "" without an App or offline."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    assert context.scenario_variables()["app_id"] == ""
    context._memos["app_credentials"] = AppCredentials("424242", "-----BEGIN PRIVATE KEY-----\nx\n", "hook", "e2e-app")
    variables = context.scenario_variables()
    assert variables["app_id"] == "424242" and variables["app_slug"] == "e2e-app"
    assert context.offline_variables()["app_id"] == ""


def test_broken_app_credentials_do_not_break_scenario_variables(
    tmp_path: Path, live: LiveFakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A broken App configuration leaves app_id empty (CLI scenarios still run)."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()

    def broken(*args: Any, **kwargs: Any) -> None:
        """An unreadable App key."""
        raise ValueError("bad PEM")

    monkeypatch.setattr("otterdog_e2e.settings.resolve_app_credentials", broken)
    assert context.scenario_variables()["app_id"] == ""


def test_webapp_deployment_starts_the_dtrack_mock_when_requested(
    webapp_context: tuple[E2EContext, list[str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    """extras["dtrack_mock"] (set by the plugin for items using the dtrack_mock fixture) reaches WebappSettings."""
    context, _events = webapp_context
    seen: list[Any] = []
    monkeypatch.setattr("otterdog_e2e.webapp.stack.WebappStack", lambda settings, **kw: seen.append(settings))
    context.webapp_deployment()
    context.extras["dtrack_mock"] = True
    context.webapp_deployment()
    assert [settings.dtrack_mock for settings in seen] == [False, True]


class DtrackStack:
    """Compose stack stand-in for E2EContext.dtrack_mock."""

    def __init__(self, enabled: bool, error: Exception | None = None) -> None:
        """Mock enabled or not; enable_dtrack_mock may fail."""
        self.dtrack_enabled = enabled
        self.error = error
        self.calls: list[str] = []

    def down(self) -> None:
        """A compose stack can be stopped."""

    def dtrack(self) -> str:
        """The client."""
        self.calls.append("dtrack")
        return "client"

    def enable_dtrack_mock(self) -> str:
        """Start the mock (or fail)."""
        self.calls.append("enable")
        if self.error is not None:
            raise self.error
        return "client"


def test_dtrack_mock_of_the_deployment(tmp_path: Path) -> None:
    """The running mock's client, the mock started on a stack without it, refusals for external webapps and stack
    errors."""
    from otterdog_e2e.webapp.stack import WebappStackError

    context = new_context(tmp_path)
    running, started = DtrackStack(True), DtrackStack(False)
    assert context.dtrack_mock(running) == "client" and running.calls == ["dtrack"]  # type: ignore[arg-type]
    assert context.dtrack_mock(started) == "client" and started.calls == ["enable"]  # type: ignore[arg-type]
    with pytest.raises(ContextError, match="compose webapp stack"):
        context.dtrack_mock(SimpleNamespace(base_url="http://127.0.0.1:5000"))  # type: ignore[arg-type]
    with pytest.raises(ContextError, match="unavailable: WebappStackError: pull denied"):
        context.dtrack_mock(DtrackStack(False, WebappStackError("pull denied")))  # type: ignore[arg-type]


def test_blueprint_helper_wiring(tmp_path: Path, live: LiveFakes) -> None:
    """The helper of a webapp case: org config repo of the run, configs repo, admin Mutator, the case's flow and API,
    the relay, the larger-runner capability and the purgeable runs."""
    context = new_context(tmp_path, target="free")
    context.ensure_live()
    case = SimpleNamespace(flow="flow", api="api")
    relay = object()
    helper = context.blueprint_helper(case, relay=relay)  # type: ignore[arg-type]
    assert helper.org == FAKE_ORG and helper.configs_repo == "otterdog-e2e-configs"
    assert helper.config_repo == f"e2e-{FAKE_RUN_ID}-config" and helper.run_ctx is context.run_ctx
    assert helper.mutator is context.mutator("admin") and helper.oracle is context.oracle()
    assert (helper.flow, helper.api, helper.relay) == ("flow", "api", relay)
    assert helper.larger_runners is False and helper.purgeable == context.purgeable  # free plan
    context.capabilities = from_plan("team")
    assert context.blueprint_helper(case).larger_runners is True  # type: ignore[arg-type]


def test_publish_otterdog_json_with_organization_overrides(
    webapp_context: tuple[E2EContext, list[str]], live: LiveFakes, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admin_teams / approval_teams of the org entry are replaced (None drops a key); other keys are refused."""
    from otterdog_e2e.context import check_organization_overrides

    context, _events = webapp_context
    entry = {
        "name": "p",
        "github_id": FAKE_ORG,
        "admin_teams": ["otterdog-admins"],
        "approval_teams": ["^project-leads$"],
    }
    monkeypatch.setattr(
        "otterdog_e2e.otterdog.workspace.webapp_otterdog_json", lambda *a, **k: {"organizations": [dict(entry)]}
    )
    written: list[dict[str, Any]] = []
    mutator = context.mutator("admin")
    original = mutator.commit_files

    def commit(repo: str, branch: str, files: Any, message: str) -> str:
        """Keep the published document."""
        written.append(json.loads(files["otterdog.json"]))
        return original(repo, branch, files, message)

    mutator.commit_files = commit  # type: ignore[method-assign]
    context.publish_otterdog_json(
        SimpleNamespace(url="u"),  # type: ignore[arg-type]
        organization={"admin_teams": ["e2e-admins", "otterdog-admins"], "approval_teams": None},
    )
    (document,) = written
    assert document["organizations"][0] == {
        "name": "p",
        "github_id": FAKE_ORG,
        "admin_teams": ["e2e-admins", "otterdog-admins"],
    }
    for bad in ({"config_repo": ["x"]}, {"admin_teams": "otterdog-admins"}, {"approval_teams": [""]}):
        with pytest.raises(ValueError):
            check_organization_overrides(bad)
    assert check_organization_overrides({"approval_teams": ("e2e-.*",)}) == {"approval_teams": ["e2e-.*"]}


def test_reload_webapp_inits_and_waits(webapp_context: tuple[E2EContext, list[str]]) -> None:
    """reload_webapp: /internal/init, then the readiness wait of the deployment."""
    context, events = webapp_context
    context.reload_webapp(FakeStack(events))  # type: ignore[arg-type]
    assert events[-2:] == ["init", "wait_ready"]
