"""Web-enabled restore of the web-only settings (BaselineManager) and the Playwright Firefox install (cli_install)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import procs
from otterdog_e2e.otterdog.baseline import BaselineManager
from otterdog_e2e.otterdog.render import OrgConfigRenderer, build_baseline, org_profile
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.sut.cli_install import (
    InstalledCli,
    ensure_playwright_firefox,
    firefox_installed,
    playwright_browsers_path,
)
from otterdog_e2e.sut.spec import ResolvedSut, SutSpec
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import (
    FakeCli,
    FakeOracle,
    default_org_json,
    make_run_context,
    make_settings,
    make_target,
)

NOOP = "Plan: 0 to add, 0 to change, 0 to delete.\n"
CHANGE = "  ~ settings {\n    ~ members_can_create_teams = false -> true\n  ~ }\n  Plan: 0 to add, 1 to change, 0 to delete.\n"
EXECUTED = "Executed plan: 0 added, 1 changed, 0 live resources ignored.\n"
# otterdog's error box (print_error) of a failed patch, as in tests/unit/data/apply-failed-patch.txt
FAILED_PATCH = (
    "╷\n"
    "│ Error:   failed to apply patch: CHANGE - settings\n"
    "│          RuntimeError: failed to update settings via web interface\n"
    "╵\n"
)


@dataclass
class Workspace:
    """Records the org configs written."""

    texts: list[str] = field(default_factory=list)

    def write_org_config(self, text: str) -> None:
        """Record ``text``."""
        self.texts.append(text)


class WebCli(FakeCli):
    """FakeCli with a web mode and a (trusted) installation."""

    def __init__(self, *, web: bool = True, trusted: bool = True) -> None:
        """A fake web-mode CLI."""
        super().__init__(workspace=Workspace())
        self.web = object() if web else None
        self.installed = type("Installed", (), {"sut": type("Sut", (), {"trusted": trusted, "label": "v1.6.1"})()})()


def manager() -> BaselineManager:
    """A BaselineManager of the fake target (renderer over the offline template)."""
    target, run = make_target(), make_run_context()
    renderer = OrgConfigRenderer(
        template=offline_template(),
        org=target.org,
        plan="free",
        org_profile=org_profile(default_org_json()),
        baseline=build_baseline(target, run),
        marker=target.marker,
        hide_cache_limit=False,
    )
    return BaselineManager(
        reset_cli=FakeCli(),  # type: ignore[arg-type]
        renderer=renderer,
        target=target,
        run_ctx=run,
        oracle=FakeOracle(),  # type: ignore[arg-type]
        purgeable=lambda run_id: True,
        protected_repos=target.protected_repos(run),
    )


def test_record_web_settings_first_snapshot_wins() -> None:
    """The ORIGINAL values are kept (later records only re-arm the pending restore); read-only keys dropped."""
    baseline = manager()
    assert baseline.web_snapshot is None and not baseline.web_restore_pending
    baseline.record_web_settings({"members_can_create_teams": False, "two_factor_requirement": True})
    baseline.record_web_settings({"members_can_create_teams": True})
    assert baseline.web_snapshot == {"members_can_create_teams": False} and baseline.web_restore_pending
    baseline.mark_web_restored()
    assert not baseline.web_restore_pending


def test_web_settings_text_pins_values_in_the_scenario_layer() -> None:
    """The baseline plus ``key::: value`` fields."""
    text = manager().web_settings_text({"members_can_create_teams": True, "default_branch_name": "main"})
    assert "members_can_create_teams::: true," in text and 'default_branch_name::: "main",' in text
    assert text.index("members_can_create_teams:::") > text.index("_repositories+:")


def test_restore_web_settings_with_a_trusted_web_cli() -> None:
    """Guarded plan then apply of the pinned snapshot; the pending flag clears on success."""
    baseline = manager()
    baseline.record_web_settings({"members_can_create_teams": False})
    cli = WebCli()
    cli.queue("plan", stdout=CHANGE)
    cli.queue("apply", stdout=CHANGE + EXECUTED)
    applied = baseline.restore_web_settings(cli)  # type: ignore[arg-type]
    assert [call.command for call in cli.calls] == ["plan", "apply"]
    assert applied.changed == 1 and not applied.failed_patches
    assert "members_can_create_teams::: false" in cli.workspace.texts[-1]
    assert not baseline.web_restore_pending


def test_restore_failure_keeps_the_restore_pending() -> None:
    """A failed patch: still pending (the session-end safety net retries and reports it)."""
    baseline = manager()
    baseline.record_web_settings({"members_can_create_teams": False})
    cli = WebCli()
    cli.queue("plan", stdout=CHANGE)
    cli.queue("apply", stdout=CHANGE + "planning aborted: could not log in to web UI: Timeout\n", exit_code=1)
    baseline.restore_web_settings(cli)  # type: ignore[arg-type]
    assert baseline.web_restore_pending, "a failed exit code keeps the restore pending"
    cli.queue("plan", stdout=CHANGE)
    cli.queue("apply", stdout=CHANGE + FAILED_PATCH + EXECUTED, exit_code=1)
    assert baseline.restore_web_settings(cli).failed_patches  # type: ignore[arg-type]
    assert baseline.web_restore_pending


def test_restore_refuses_an_incomplete_plan() -> None:
    """A web plan that did not complete (login failure) cannot be verified: SafetyError, nothing applied."""
    baseline = manager()
    baseline.record_web_settings({"members_can_create_teams": False})
    cli = WebCli()
    cli.queue("plan", stdout="planning aborted: incorrect 2FA TOTP\n", exit_code=1)
    with pytest.raises(SafetyError, match="did not complete"):
        baseline.restore_web_settings(cli)  # type: ignore[arg-type]
    assert [call.command for call in cli.calls] == ["plan"] and baseline.web_restore_pending


def test_restore_refusals_and_noop() -> None:
    """No snapshot: nothing runs; a CLI without web mode or an untrusted one is refused."""
    baseline = manager()
    cli = WebCli()
    assert baseline.restore_web_settings(cli).no_changes and cli.calls == []  # type: ignore[arg-type]
    baseline.record_web_settings({"members_can_create_teams": False})
    with pytest.raises(SafetyError, match="web-mode"):
        baseline.restore_web_settings(WebCli(web=False))  # type: ignore[arg-type]
    with pytest.raises(SafetyError, match="trusted otterdog"):
        baseline.restore_web_settings(WebCli(trusted=False))  # type: ignore[arg-type]


def test_explicit_values_do_not_clear_the_pending_snapshot() -> None:
    """Restoring other values (e.g. a scenario's own) leaves the snapshot restore pending."""
    baseline = manager()
    baseline.record_web_settings({"members_can_create_teams": False})
    cli = WebCli()
    cli.queue("plan", stdout=NOOP)
    baseline.restore_web_settings(cli, {"members_can_create_teams": True})  # type: ignore[arg-type]
    assert baseline.web_restore_pending and [call.command for call in cli.calls] == ["plan"]


# --- Playwright Firefox ----------------------------------------------------------------------------------------------
def installed(tmp_path: Path, *, trusted: bool = True, runtime: str = "host") -> InstalledCli:
    """A host install whose venv python exists."""
    venv = tmp_path / "build" / ".venv"
    (venv / "bin").mkdir(parents=True, exist_ok=True)
    (venv / "bin" / "python").write_text("")
    sut = ResolvedSut(
        spec=SutSpec("release:latest", "release", "latest"),
        label="v1.6.1",
        sha="d" * 40,
        version="1.6.1",
        image_version="1.6.1",
        source_dir=tmp_path / "src",
        repo_url="https://github.com/eclipse-csi/otterdog",
        trusted=trusted,
    )
    return InstalledCli(sut, runtime, venv if runtime == "host" else None, venv / "bin" / "otterdog", None, "x")


def test_ensure_playwright_firefox(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``<venv>/bin/python -m playwright install firefox`` with PLAYWRIGHT_BROWSERS_PATH in the private cache."""
    settings = make_settings(tmp_path)
    calls: list[dict[str, Any]] = []

    def run(argv: list[str], **kwargs: Any) -> procs.CompletedProcess[str]:
        """Record the call; pretend the browser was downloaded."""
        calls.append({"argv": argv, **kwargs})
        (Path(kwargs["extra_env"]["PLAYWRIGHT_BROWSERS_PATH"]) / "firefox-1538").mkdir(parents=True, exist_ok=True)
        return procs.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(procs, "run", run)
    path = ensure_playwright_firefox(installed(tmp_path), settings)
    assert path == playwright_browsers_path(settings) == settings.cache_dir / "ms-playwright"
    (call,) = calls
    assert call["argv"][1:] == ["-m", "playwright", "install", "firefox"]
    assert call["argv"][0].endswith("/.venv/bin/python")
    assert call["extra_env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(path)
    assert (path.stat().st_mode & 0o777) == 0o700
    assert firefox_installed(settings) == ["firefox-1538"]


def test_ensure_playwright_firefox_refusals(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Never for container CLIs or untrusted SUTs; a failed install raises with the output tail."""
    settings = make_settings(tmp_path)
    with pytest.raises(SafetyError, match="host CLIs only"):
        ensure_playwright_firefox(installed(tmp_path, runtime="docker"), settings)
    with pytest.raises(SafetyError, match="untrusted"):
        ensure_playwright_firefox(installed(tmp_path, trusted=False), settings)
    monkeypatch.setattr(procs, "run", lambda argv, **kw: procs.CompletedProcess(argv, 1, "", "download failed"))
    with pytest.raises(RuntimeError, match="download failed"):
        ensure_playwright_firefox(installed(tmp_path), settings)
    assert firefox_installed(make_settings(tmp_path / "empty")) == []
