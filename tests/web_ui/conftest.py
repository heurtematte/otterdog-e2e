"""Fixtures of the web-UI tier (docs/web-ui-testing.md): otterdog driving the GitHub web UI as the admin bot.

Every item of this directory is live (plugin tier ``web_ui``) and must carry the ``web_ui`` marker: the plugin then
skips it, before any fixture, unless the WEB_UI conditions hold (admin web credentials, ``--e2e-allow-web-ui``, a
trusted SUT, no ``github.saml_sso``, web logins not blocked). Fixtures:

* ``web_sut``: the SUT under test in web mode (plan/apply/import without ``-n``), host install of a trusted SUT;
* ``web_reader``: the TRUSTED reader, the reset SUT in web mode reading the settings with ``show-live`` (or with
  ``import`` + ``show --local`` when ``E2E_WEB_READER=import``);
* ``web_tier``: a WebUiTier bundling them with the REST oracle, the baseline and the evidence writer.

Every web command goes through the session's LoginGate (one login at a time, a TOTP window apart), so the tests
never sleep themselves and never start otterdog outside the web-mode CLIs.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.webui import mapping
from otterdog_e2e.webui.oracle import TrustedWebReader, rest_web_values, wait_rest_values
from otterdog_e2e.webui.roundtrip import WebSettingsRoundTrip

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import WebOtterdogCli
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.cli_install import InstalledCli

TIER_DIR = Path(__file__).resolve().parent


@dataclass
class WebUiTier:
    """Everything a web-UI test needs (built by the ``web_tier`` fixture)."""

    e2e: E2EContext
    sut: WebOtterdogCli
    reader: TrustedWebReader
    oracle: Oracle
    baseline: BaselineManager
    run_ctx: RunContext
    target: Target

    @property
    def org(self) -> str:
        """Exact-case login of the test org."""
        return self.target.org

    @property
    def discussion_repo(self) -> str | None:
        """``<org>/<first fixture repo>``: the public repository hosting org discussions while they are on."""
        fixture = next(iter(self.target.fixture_repos), None)
        return f"{self.org}/{fixture}" if fixture else None

    def rest(self) -> dict[str, Any]:
        """The REST-readable web settings (GET /orgs/{org}, owner token)."""
        return rest_web_values(self.oracle)

    def record(self, values: Mapping[str, Any]) -> None:
        """Remember the original web values: in the BaselineManager (session-end restore) and on disk (a hard kill
        of the session: the next web session restores them first)."""
        self.baseline.record_web_settings(values)
        self.e2e.save_web_snapshot(values)

    def restored(self) -> None:
        """The original values are verified back."""
        self.baseline.mark_web_restored()
        self.e2e.drop_web_snapshot()

    def recover_pending(self) -> list[str]:
        """Restore the web values a previous session of this machine left changed (persisted snapshot) with the
        TRUSTED web CLI before anything else; returns what is still different (REST), empty when recovered."""
        pending = self.e2e.load_web_snapshot()
        if pending is None:
            return []
        values = dict(pending["values"])
        self.baseline.record_web_settings(values)  # first record wins: the session-end restore uses these
        self.baseline.restore_web_settings(self.reader.cli, values)
        _rest, differences = wait_rest_values(self.rest, values)
        read = self.reader.read()
        if read.ok:
            readable = [key for key in values if key in read.values]
            differences += [f"trusted {line}" for line in mapping.differences(values, read.values, readable)]
        if not differences and read.ok:
            self.restored()
        return differences if read.ok else [*differences, read.problem() or "trusted read failed"]

    def round_trip(self) -> WebSettingsRoundTrip:
        """The settings round trip wired to the SUT, the trusted reader, REST and the baseline bookkeeping."""
        return WebSettingsRoundTrip(
            sut=self.sut,
            reader=self.reader,
            rest=self.rest,
            render=self.baseline.web_settings_text,
            plan=self.e2e.require_verified().plan,
            run_id=self.run_ctx.run_id,
            discussion_repo=self.discussion_repo,
            record=self.record,
            restored=self.restored,
            trusted_restore=lambda values: self.baseline.restore_web_settings(self.reader.cli, values),
            reader_is_sut=self.reader.cli.installed.sut.sha == self.sut.installed.sut.sha,
        )

    def web_cli(self, name: str) -> WebOtterdogCli:
        """Another web-mode CLI of the SUT with its own workspace (``webui-<name>``)."""
        return self.e2e.web_cli("head", name=name)

    def installations(self) -> list[dict[str, Any]]:
        """App installations of the org (GET /orgs/{org}/installations, admin token, read-only client)."""
        return list(
            self.e2e.http("admin").paginate(f"/orgs/{self.org}/installations", item_key="installations", per_page=100)
        )

    def installed_slugs(self) -> set[str]:
        """Slugs of the Apps installed on the org."""
        return {str(item.get("app_slug")) for item in self.installations()}

    def write_evidence(self, name: str, data: dict[str, Any]) -> Path:
        """Redacted ``<artifacts>/webui/<name>.json`` (with the login gate summary of the session)."""
        path = self.e2e.artifacts_dir / "webui" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"run": self.run_ctx.run_id, "gate": self.e2e.web_gate().summary(), **data}
        path.write_text(REDACTOR(json.dumps(payload, indent=2, sort_keys=True, default=str)) + "\n", encoding="utf-8")
        return path


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Every item of the tier carries the web_ui marker (the plugin gates on it before any fixture)."""
    for item in items:
        if Path(item.path).resolve().is_relative_to(TIER_DIR) and item.get_closest_marker("web_ui") is None:
            item.add_marker(pytest.mark.web_ui)


@pytest.fixture(scope="session")
def web_sut(e2e: E2EContext, sut: InstalledCli, baseline: BaselineManager) -> WebOtterdogCli:
    """The SUT under test in web mode (trusted host install; the baseline is reset first)."""
    return e2e.web_cli("head", name="sut")


@pytest.fixture(scope="session")
def web_reader(e2e: E2EContext, reset_sut: InstalledCli, baseline: BaselineManager) -> TrustedWebReader:
    """The trusted reader: the reset SUT in web mode (never the SUT under test); E2E_WEB_READER=import reads through
    ``import`` + ``show --local`` instead of ``show-live``."""
    mode = os.environ.get("E2E_WEB_READER") or "show-live"
    return TrustedWebReader(e2e.web_cli("reset", name="reader"), mode=mode)


@pytest.fixture
def web_tier(
    e2e: E2EContext,
    web_sut: WebOtterdogCli,
    web_reader: TrustedWebReader,
    oracle: Oracle,
    baseline: BaselineManager,
    run_ctx: RunContext,
    target: Target,
) -> WebUiTier:
    """WebUiTier of the current test."""
    return WebUiTier(e2e, web_sut, web_reader, oracle, baseline, run_ctx, target)
