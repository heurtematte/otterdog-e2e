"""Run-data facet of the session context: what scenarios and reports read about the run.

RunDataFacet provides the Jinja variables of live scenarios (SPEC 12.1 (8); logins are the DECLARED ones, F8; ``app_id``
is the e2e App id, "" without an App, next to ``app_slug``) and of offline ones, the lowest GitHub rate budget seen per
identity, scenarios/known_bugs.yaml and the change under test (--e2e-change) with the references of the scenarios.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from otterdog_e2e.context.helpers import describe_error
from otterdog_e2e.context.live import LiveFacet

if TYPE_CHECKING:
    from otterdog_e2e.changes import ChangeId, ChangeSpec
    from otterdog_e2e.known_bugs import KnownBug

logger = logging.getLogger(__name__)

MIN_RATE_REMAINING = 800  # E2E_MIN_RATE_REMAINING: live items are skipped below this core budget
MIN_RATE_ENV = "E2E_MIN_RATE_REMAINING"
KNOWN_BUGS_FILE = "known_bugs.yaml"
DEFAULT_TEAMS: Mapping[str, str] = {
    "admin": "otterdog-admins",
    "approval": "project-leads",
    "contributors": "e2e-contributors",
}


class RunDataFacet(LiveFacet):
    """Scenario variables, rate budget, known bugs and change under test of a session."""

    # --- scenario variables ---------------------------------------------------------------------------------------
    def scenario_variables(self) -> dict[str, Any]:
        """Jinja variables of live scenarios (SPEC 12.1 (8)); logins are the DECLARED ones (F8)."""
        target, verified = self.require_target(), self.require_verified()
        return {
            **self.run_ctx.template_vars(),
            "org": target.org,
            "plan": verified.plan,
            "logins": {name: spec.login for name, spec in target.identities.items() if spec.login},
            "app_slug": self._app_slug(),
            "app_id": self._app_id(),
            "teams": {
                "admin": target.admin_team,
                "approval": target.approval_team,
                "contributors": target.contributors_team,
            },
        }

    def _app_slug(self) -> str:
        """Declared App slug (target or credentials), empty when unknown."""
        target = self.require_target()
        if target.app is not None and target.app.slug:
            return target.app.slug
        try:
            credentials = self.app_credentials()
        except Exception as exc:  # noqa: BLE001 - a broken App config must not break CLI scenarios
            logger.info("App credentials unavailable: %s", describe_error(exc))
            return ""
        return (credentials.slug or "") if credentials is not None else ""

    def _app_id(self) -> str:
        """Id of the e2e App (app-bound status checks ``<id>:<context>``, Integration bypass actors), "" when no App
        is configured."""
        try:
            credentials = self.app_credentials()
        except Exception as exc:  # noqa: BLE001 - a broken App config must not break CLI scenarios
            logger.info("App credentials unavailable: %s", describe_error(exc))
            return ""
        return str(credentials.app_id or "") if credentials is not None else ""

    def offline_variables(self) -> dict[str, Any]:
        """Jinja variables of offline scenarios: the offline org, plan free, default team names, no logins."""
        from otterdog_e2e.scenarios.offline import OFFLINE_DEFAULT_PLAN, OFFLINE_ORG

        return {
            **self.run_ctx.template_vars(),
            "org": OFFLINE_ORG,
            "plan": OFFLINE_DEFAULT_PLAN,
            "logins": {},
            "app_slug": "",
            "app_id": "",
            "teams": dict(DEFAULT_TEAMS),
        }

    # --- reporting --------------------------------------------------------------------------------------------------
    def rate_remaining(self) -> dict[str, int]:
        """Lowest core x-ratelimit-remaining seen per identity (from the clients' last responses)."""
        rates: dict[str, int] = {}
        for (name, _mode), http in self._http.items():
            core = (http.rate_snapshot() or {}).get("core") or {}
            remaining = core.get("remaining") if isinstance(core, Mapping) else None
            if remaining is None:
                continue
            rates[name] = min(int(remaining), rates.get(name, int(remaining)))
        return rates

    def min_rate_threshold(self) -> int:
        """E2E_MIN_RATE_REMAINING (default MIN_RATE_REMAINING)."""
        return int(self.environ.get(MIN_RATE_ENV) or MIN_RATE_REMAINING)

    def known_bugs(self) -> dict[str, KnownBug]:
        """scenarios/known_bugs.yaml keyed by id (empty when the file does not exist)."""

        def build() -> dict[str, KnownBug]:
            """Load the file."""
            path = self.settings.scenarios_dir / KNOWN_BUGS_FILE
            if not path.is_file():
                return {}
            from otterdog_e2e import known_bugs

            return dict(known_bugs.load(path))

        return self._memo("known_bugs", build)

    def change(self) -> ChangeId | None:
        """The change under test: --e2e-change (E2E_CHANGE), else N of a ``pr:N@<sha>`` --e2e-sut, else None
        (changes.ChangeError when --e2e-change is malformed)."""
        from otterdog_e2e.changes import default_change

        return default_change(self.options.change, self.options.sut)

    def change_spec(self) -> ChangeSpec | None:
        """The ChangeSpec of the change under test: the scenarios referencing it, their expected deltas, base and
        template (None without a change; changes.ChangeError for invalid or conflicting references)."""

        def build() -> ChangeSpec | None:
            """Gather the references of the repository."""
            change = self.change()
            if change is None:
                return None
            from otterdog_e2e.changes import load_change

            return load_change(self.settings.scenarios_dir, self.settings.project_root / "tests", change)

        return self._memo("change_spec", build)
