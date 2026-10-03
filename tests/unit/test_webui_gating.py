"""Gating of the web-UI tier (pytest_plugin + context): the web_ui marker skips before any fixture unless WEB_UI holds
(admin web credentials, --e2e-allow-web-ui / E2E_ALLOW_WEB_UI, a trusted SUT, no github.saml_sso, no blocked gate);
probe() derives Cap.WEB_UI; web_cli() refuses untrusted SUTs; the baseline teardown restores pending web settings."""

from __future__ import annotations

import dataclasses
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.capabilities import Cap, from_plan
from otterdog_e2e.context import ContextError, E2EContext, E2EOptions
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import (
    FAKE_RUN_ID,
    FakeLease,
    make_identities,
    make_settings,
    make_target,
    make_verified_org,
)

pytest_plugins = ["pytester"]

SEED = "JBSWY3DPEHPK3PXP"
WEB_ENV = {"E2E_ADMIN_PASSWORD": "bot-pw-0123456789", "E2E_ADMIN_TOTP_SEED": SEED}
CLEARED = ("E2E_TARGET", "E2E_SUT", "E2E_RESET_SUT", "E2E_ALLOW_WEB_UI", "E2E_ARTIFACTS", "E2E_RUN_ID", "CI")
CLEARED += ("GITHUB_ACTIONS", "GITHUB_STEP_SUMMARY", "E2E_ADMIN_PASSWORD", "E2E_ADMIN_TOTP_SEED", "E2E_SCENARIO")
WEB_TEST = """
import pytest

pytestmark = [pytest.mark.live, pytest.mark.web_ui]


@pytest.fixture
def boom():
    raise AssertionError("fixtures must not run for skipped web_ui items")


def test_web(boom):
    pass
"""


def context(tmp_path: Path, *, allow: bool = True, environ: dict[str, str] | None = None, **target: Any) -> E2EContext:
    """A live-looking context of the fake target (no GitHub access)."""
    ctx = E2EContext.create(
        E2EOptions(target="fake", allow_web_ui=allow), environ=dict(environ or {}), settings=make_settings(tmp_path)
    )
    ctx.target = make_target(**target)
    ctx.identities = make_identities("admin")
    ctx.verified = make_verified_org()
    ctx._memos["trusted:head"] = True
    return ctx


def test_web_ui_problems_of_the_context(tmp_path: Path) -> None:
    """Every WEB_UI condition, from the context's own state."""
    assert context(tmp_path, environ=WEB_ENV).web_ui_problems() == []
    assert "no web-UI credentials" in context(tmp_path).web_ui_problems()[0]
    assert "--e2e-allow-web-ui" in context(tmp_path, allow=False, environ=WEB_ENV).web_ui_problems()[0]
    assert "SAML SSO" in context(tmp_path, environ=WEB_ENV, saml_sso=True).web_ui_problems()[0]
    untrusted = context(tmp_path, environ=WEB_ENV)
    untrusted._memos["trusted:head"] = False
    assert "untrusted" in untrusted.web_ui_problems()[0]
    invalid = context(tmp_path, environ={**WEB_ENV, "E2E_ADMIN_TOTP_SEED": "12"})
    assert "web-UI credentials invalid" in invalid.web_ui_problems()[0]
    blocked = context(tmp_path, environ=WEB_ENV)
    blocked.web_gate().block("lockout: GitHub throttles the bot's logins")
    assert "blocked until" in blocked.web_ui_problems()[0]


def test_probe_derives_web_ui(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """probe(): WEB_UI only without problems (and not when the target overrides remove it); run.json records it."""
    monkeypatch.setattr("otterdog_e2e.capabilities.probe_capabilities", lambda *a, **k: from_plan("free"))
    monkeypatch.setattr(E2EContext, "check_app", lambda self: (False, "no App"))
    monkeypatch.setattr(E2EContext, "docker_available", lambda self: False)
    monkeypatch.setattr(E2EContext, "http", lambda self, name, write=False: object())
    ctx = context(tmp_path, environ=WEB_ENV)
    assert ctx.probe().has(Cap.WEB_UI) and ctx.run_info["web_ui"] == {"enabled": True, "reason": None}
    off = context(tmp_path, allow=False, environ=WEB_ENV)
    assert not off.probe().has(Cap.WEB_UI) and "--e2e-allow-web-ui" in off.extras["web_ui_reason"]
    removed = context(tmp_path, environ=WEB_ENV, capability_overrides={"add": (), "remove": ("web_ui",)})
    assert not removed.probe().has(Cap.WEB_UI)


def test_web_cli_refusals(tmp_path: Path) -> None:
    """web_cli(): unknown roles, a missing WEB_UI condition, and untrusted SUTs (even granted host trust)."""
    ctx = context(tmp_path, allow=False, environ=WEB_ENV)
    with pytest.raises(ValueError, match="roles"):
        ctx.web_cli("base", name="x")
    with pytest.raises(ContextError, match="web-UI tier unavailable"):
        ctx.web_cli("head", name="x")
    ok = context(tmp_path, environ=WEB_ENV)
    ok._memos[f"resolved:{ok.options.reset_sut}"] = type("Resolved", (), {"trusted": False, "label": "pr1-abc"})()
    with pytest.raises(SafetyError, match="untrusted SUT pr1-abc"):
        ok.web_cli("reset", name="reader")


def test_restore_web_settings_only_when_pending(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The session-end safety net runs the trusted restore only while a restore is pending; errors are logged."""
    ctx = context(tmp_path, environ=WEB_ENV)
    calls: list[Any] = []

    class Baseline:
        """BaselineManager stand-in with web bookkeeping."""

        web_restore_pending = True
        web_snapshot = {"members_can_create_teams": True}

        def restore_web_settings(self, cli: Any) -> None:
            """Record and clear."""
            calls.append(cli)
            self.web_restore_pending = False

    monkeypatch.setattr(E2EContext, "web_cli", lambda self, role, name: f"web-cli:{role}:{name}")
    assert ctx.restore_web_settings(Baseline()) is True and calls == ["web-cli:reset:restore"]
    idle = Baseline()
    idle.web_restore_pending = False
    calls.clear()
    assert ctx.restore_web_settings(idle) is True and calls == []

    class Broken(Baseline):
        """The restore fails."""

        def restore_web_settings(self, cli: Any) -> None:
            """Raise."""
            raise RuntimeError("blocked")

    assert ctx.restore_web_settings(Broken()) is False
    assert ctx.restore_web_settings(object()) is True  # managers without web state (other unit tests' fakes)


# --- pytester: the plugin gate ---------------------------------------------------------------------------------------
class Inner:
    """Inner pytest sessions with a fake live session."""

    def __init__(self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
        """Isolated settings, no e2e environment, fake summary and scrub."""
        self.pytester = pytester
        self.monkeypatch = monkeypatch
        self.settings = make_settings(pytester.path / "harness")
        monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: self.settings)
        monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *a: None)
        monkeypatch.setattr("otterdog_e2e.report.build_summary", lambda directory, **kw: "# summary\n")
        monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor=None: [])
        for name in CLEARED:
            monkeypatch.delenv(name, raising=False)

    def live(self, problems: list[str]) -> None:
        """Fake ensure_live and web_ui_problems."""

        def ensure_live(ctx: E2EContext) -> None:
            """A verified free org."""
            if ctx._live_attempted:
                return
            ctx._live_attempted = True
            ctx.target = make_target()
            ctx.identities = make_identities("admin")
            ctx.verified = make_verified_org()
            ctx.capabilities = from_plan("free")
            ctx.docker_ok, ctx.app_ok = True, False
            ctx.lease = FakeLease()
            ctx.lease.acquire()

        self.monkeypatch.setattr(E2EContext, "ensure_live", ensure_live)
        self.monkeypatch.setattr(E2EContext, "web_ui_problems", lambda self: list(problems))
        self.monkeypatch.setenv("E2E_TARGET", "fake")

    def run(self, *args: str) -> pytest.RunResult:
        """runpytest with a fixed run id."""
        return self.pytester.runpytest("-p", "no:cacheprovider", f"--e2e-run-id={FAKE_RUN_ID}", "-rs", *args)


@pytest.fixture
def inner(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> Inner:
    """Inner session factory."""
    return Inner(pytester, monkeypatch)


def test_marker_and_option_are_registered(inner: Inner) -> None:
    """--markers lists web_ui; --help lists --e2e-allow-web-ui."""
    inner.pytester.runpytest("--markers").stdout.fnmatch_lines(["@pytest.mark.web_ui:*"])
    assert "--e2e-allow-web-ui" in inner.pytester.runpytest("--help").stdout.str()


def test_web_ui_items_skip_before_fixtures(inner: Inner) -> None:
    """A WEB_UI problem skips the item with the reason; its fixtures never run."""
    inner.live(["no web-UI credentials for the admin bot (E2E_ADMIN_PASSWORD, E2E_ADMIN_TOTP_SEED)"])
    inner.pytester.makepyfile(test_web=WEB_TEST)
    result = inner.run()
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*web-UI tier: no web-UI credentials for the admin bot*"])


def test_web_ui_items_run_when_every_condition_holds(inner: Inner) -> None:
    """No problem: the item runs (here its failing fixture proves the gate let it through)."""
    inner.live([])
    inner.pytester.makepyfile(test_web=WEB_TEST)
    inner.run().assert_outcomes(errors=1)


def test_non_live_web_ui_items_are_skipped(inner: Inner) -> None:
    """web_ui without live: skipped (web-UI tests always drive github.com)."""
    inner.pytester.makepyfile(
        test_local="import pytest\n\n@pytest.mark.web_ui\ndef test_local():\n    pass\n",
    )
    result = inner.run()
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*mark the test live*"])


def test_allow_flag_and_its_environment_fallback(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """--e2e-allow-web-ui, or E2E_ALLOW_WEB_UI=1/true, sets E2EOptions.allow_web_ui."""
    inner.pytester.makepyfile(
        test_flag=(
            "from otterdog_e2e.context import E2EOptions\n\n"
            "def test_flag(pytestconfig):\n"
            "    print('ALLOW', E2EOptions.from_config(pytestconfig).allow_web_ui)\n"
        )
    )
    assert "ALLOW False" in inner.run("-s").stdout.str()
    assert "ALLOW True" in inner.run("-s", "--e2e-allow-web-ui").stdout.str()
    monkeypatch.setenv("E2E_ALLOW_WEB_UI", "true")
    assert "ALLOW True" in inner.run("-s").stdout.str()
    monkeypatch.setenv("E2E_ALLOW_WEB_UI", "no")
    assert "ALLOW False" in inner.run("-s").stdout.str()


def test_tier_directory_marks_items_live(inner: Inner) -> None:
    """tests/web_ui is a live tier: its items get the live marker (and skip without a target)."""
    directory = inner.pytester.mkpydir("tests") / "web_ui"
    directory.mkdir()
    (directory / "test_tier.py").write_text("def test_tier():\n    pass\n")
    result = inner.run(str(directory))
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*live test without a target*"])


def test_options_dataclass_default() -> None:
    """E2EOptions.allow_web_ui defaults to False (the web-UI tier is opt-in)."""
    assert E2EOptions().allow_web_ui is False
    assert {field.name for field in dataclasses.fields(E2EOptions)} >= {"allow_web_ui"}


def test_persisted_snapshot_survives_the_session(tmp_path: Path) -> None:
    """save (first wins, 0600, no secret) -> load (same org only) -> drop; a verified restore drops it."""
    ctx = context(tmp_path, environ=WEB_ENV)
    assert ctx.load_web_snapshot() is None
    ctx.save_web_snapshot({"members_can_create_teams": False})
    ctx.save_web_snapshot({"members_can_create_teams": True})
    record = ctx.load_web_snapshot()
    assert record is not None and record["values"] == {"members_can_create_teams": False}
    assert record["run_id"] == ctx.run_ctx.run_id and record["org"] == ctx.require_target().org
    path = ctx.web_snapshot_path()
    assert (path.stat().st_mode & 0o777) == 0o600 and "bot-pw" not in path.read_text()
    other_org = context(tmp_path, environ=WEB_ENV, org_id=7)
    assert other_org.load_web_snapshot() is None
    later = context(tmp_path, environ=WEB_ENV)  # another session on the same machine sees it
    assert later.load_web_snapshot() == record

    class Baseline:
        """A pending restore that succeeds."""

        web_restore_pending = True
        web_snapshot = {"members_can_create_teams": False}

        def restore_web_settings(self, cli: Any) -> None:
            """Clear the pending flag."""
            self.web_restore_pending = False

    later.web_cli = lambda role, name: "trusted-cli"  # type: ignore[method-assign]
    assert later.restore_web_settings(Baseline()) is True and later.load_web_snapshot() is None
    path.write_text("{broken")
    assert ctx.load_web_snapshot() is None
