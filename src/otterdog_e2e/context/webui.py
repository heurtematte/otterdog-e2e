"""Web-UI facet of the session context (docs/web-ui-testing.md).

probe() adds Cap.WEB_UI only when web_ui_problems() is empty (admin web credentials, --e2e-allow-web-ui, a trusted SUT,
no github.saml_sso, web logins not blocked); web_cli() builds the web-mode CLIs (SUT under test or the trusted reset
SUT, host installs only) sharing one LoginGate per bot account. The original values of the web-only org settings are
persisted (web snapshot) until the trusted web CLI has restored them, so a later session can restore them first.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e.context.helpers import describe_error
from otterdog_e2e.context.state import HTTP_CACHE_DIR, ContextError
from otterdog_e2e.context.sut import SutFacet

if TYPE_CHECKING:
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import WebOtterdogCli
    from otterdog_e2e.settings import WebCredentials
    from otterdog_e2e.webui.gate import LoginGate

logger = logging.getLogger(__name__)

WEB_ROLES = ("head", "reset")  # SUT roles that may get a web-mode CLI (trusted host installs only)


class WebUiFacet(SutFacet):
    """Web credentials, login gate, web-mode CLIs and web snapshot of a session."""

    # --- web UI (docs/web-ui-testing.md) ----------------------------------------------------------------------------
    def web_credentials(self) -> WebCredentials | None:
        """Web-UI credentials of the admin bot (None when not configured); invalid ones raise WebCredentialsError."""

        def build() -> WebCredentials | None:
            """Resolve them from the environment."""
            from otterdog_e2e.settings import resolve_web_credentials

            return resolve_web_credentials(self.require_target(), self.environ)

        return self._memo("web_credentials", build)

    def web_gate(self) -> LoginGate:
        """The LoginGate of the bot account (one per context; its files are shared by every harness process)."""

        def build() -> LoginGate:
            """Create the gate in <E2E_CACHE_DIR>/webui."""
            from otterdog_e2e.webui.gate import GATE_DIR, LoginGate, spacing_from_env

            credentials = self.web_credentials()
            if credentials is None:
                raise ContextError("no web-UI credentials (E2E_ADMIN_PASSWORD, E2E_ADMIN_TOTP_SEED)")
            return LoginGate(
                self.settings.cache_dir / GATE_DIR,
                account=credentials.login,
                spacing=spacing_from_env(self.environ),
            )

        return self._memo("web_gate", build)

    def web_ui_problems(self) -> list[str]:
        """Why the WEB_UI capability is missing (empty: web-UI tests may run); see webui.gate.web_ui_problems."""
        from otterdog_e2e.settings import TargetError
        from otterdog_e2e.webui.gate import web_ui_problems

        target = self.require_target()
        credentials, error = None, None
        try:
            credentials = self.web_credentials()
        except TargetError as exc:
            error = describe_error(exc)
        blocked = self.web_gate().blocked() if credentials is not None else None
        return web_ui_problems(
            credentials=credentials is not None,
            allowed=self.options.allow_web_ui,
            sut_trusted=self.sut_trusted("head"),
            saml_sso=target.saml_sso,
            blocked=blocked,
            credentials_error=error,
        )

    def web_browsers(self, role: str) -> Path:
        """PLAYWRIGHT_BROWSERS_PATH with the Firefox of a role's SUT installed (once per role and session)."""

        def build() -> Path:
            """Install the browser with the role's own Playwright (trusted host installs only)."""
            from otterdog_e2e.sut.cli_install import ensure_playwright_firefox

            return ensure_playwright_firefox(self.installed(role), self.settings)

        return self._memo(f"web_browsers:{role}", build)

    def web_cli(self, role: str, *, name: str) -> WebOtterdogCli:
        """A web-mode CLI of ``role`` ("head": the SUT under test, "reset": the trusted reader) with its own workspace
        (``webui-<name>``, the head template like reset_cli), cached per (role, name).

        ContextError when web_ui_problems() is not empty; SafetyError for an untrusted SUT, even one granted host
        trust with --e2e-trust-code (the decision uses the spec's own trust).
        """
        if role not in WEB_ROLES:
            raise ValueError(f"web CLIs exist for the roles {WEB_ROLES}, not {role!r}")

        def build() -> WebOtterdogCli:
            """Check, install the browser, create the workspace and the CLI."""
            from otterdog_e2e.otterdog.runner import WebMode, WebOtterdogCli
            from otterdog_e2e.safety import SafetyError

            problems = self.web_ui_problems()
            if problems:
                raise ContextError("web-UI tier unavailable: " + "; ".join(problems))
            resolved = self.resolve(self.spec_for(role))
            if not resolved.trusted:
                raise SafetyError(f"web-UI credentials never reach the untrusted SUT {resolved.label}")
            credentials = self.web_credentials()
            assert credentials is not None  # web_ui_problems() checked it
            mode = WebMode(credentials=credentials, gate=self.web_gate(), browsers_path=self.web_browsers(role))
            workspace = self.workspace(f"webui-{name}", self.template_for("head"))
            cli = WebOtterdogCli(
                self.installed(role),
                workspace,
                verified=self.require_verified(),
                identity=self.require_identity("admin"),
                web=mode,
                scratch=self.scratch / "cli" / f"webui-{name}",
                artifacts_dir=self.artifacts_dir / "reset" if role == "reset" else self.artifacts_dir,
                settings=self.settings,
                http_cache=not self.options.no_http_cache,
                http_cache_root=self.scratch / HTTP_CACHE_DIR,
            )
            cli.live_check = self.check_lease_not_lost
            return cli

        return self._memo(f"web_cli:{role}:{name}", build)

    def restore_web_settings(self, baseline: BaselineManager) -> bool:
        """Session-end safety net: restore the web-only settings recorded by the web-UI tier with the trusted web CLI
        when a restore is pending; True when nothing is pending afterwards (errors are logged, never raised)."""
        if not getattr(baseline, "web_restore_pending", False):  # stand-in managers of unit tests have no web state
            return True
        try:
            cli = self.web_cli("reset", name="restore")
            baseline.restore_web_settings(cli)
        except Exception as exc:  # noqa: BLE001 - teardown: reported, the rest of the cleanup still runs
            logger.error("could not restore the web-only org settings: %s", describe_error(exc))
        if baseline.web_restore_pending:
            logger.error(
                "the web-only org settings of %s may still differ from %s: the next web-UI session on this machine "
                "restores them first (%s), or restore them in the GitHub UI (docs/web-ui-testing.md#recovery)",
                self.require_target().org,
                baseline.web_snapshot,
                self.web_snapshot_path(),
            )
            return False
        self.drop_web_snapshot()
        return True

    def web_snapshot_path(self) -> Path:
        """``<E2E_CACHE_DIR>/webui/pending-restore-<org id>.json``: original web values not restored yet (no secret)."""
        from otterdog_e2e.webui.gate import GATE_DIR

        return self.settings.cache_dir / GATE_DIR / f"pending-restore-{self.require_target().org_id}.json"

    def save_web_snapshot(self, values: Mapping[str, Any]) -> None:
        """Persist the ORIGINAL web values before the web-UI tier changes them (first record wins, survives a hard
        kill of the session: the next web session restores them first)."""
        path = self.web_snapshot_path()
        if path.exists():
            return
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        record = {
            "org": self.require_target().org,
            "org_id": self.require_target().org_id,
            "run_id": self.run_ctx.run_id,
            "recorded_at": datetime.now(UTC).isoformat(),
            "values": dict(values),
        }
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(record, handle, indent=2, sort_keys=True)

    def load_web_snapshot(self) -> dict[str, Any] | None:
        """The persisted pending restore of the target org ({org, org_id, run_id, recorded_at, values}), else None."""
        try:
            record = json.loads(self.web_snapshot_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        target = self.require_target()
        if not isinstance(record, dict) or record.get("org_id") != target.org_id:
            return None
        return record if isinstance(record.get("values"), dict) else None

    def drop_web_snapshot(self) -> None:
        """Forget the persisted pending restore (the original values are verified back)."""
        self.web_snapshot_path().unlink(missing_ok=True)

    def _record_web_logins(self) -> None:
        """run.json web_ui: the login gate summary of this session (when a web CLI was used)."""
        gate = self._memos.get("web_gate")
        if gate is not None:
            self.write_run_info(web_ui={**(self.run_info.get("web_ui") or {}), **gate.summary()})
