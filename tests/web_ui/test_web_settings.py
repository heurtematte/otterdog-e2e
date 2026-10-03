"""Web-only organization settings driven by otterdog through the GitHub web UI (docs/web-ui-testing.md).

webui.settings.table: the harness table of the 12 web settings (oracles, pages, inputs) still matches the source of
    the SUT under test (no login).
webui.settings.round-trip: ONE scenario for every settings change of the run (8 logins): snapshot (REST + trusted
    reader), the SUT applies the toggled values without ``-n``, REST and the trusted reader verify them, the SUT's own
    plan converges, the SUT restores the originals (the trusted CLI as fallback) and both oracles verify the restore.
    Values an earlier session left changed (persisted snapshot of a killed run) are restored first.
webui.import.web-settings: ``import`` without ``-n`` writes the REST-readable web settings as GitHub reports them
    (1 login; ``show --local`` of the imported configuration evaluates it offline) and, unlike ``import -n``, does not
    warn that the Web UI was skipped.
webui.kb.import-two-factor (known bug KB-041): the same import (no further login) must carry the live
    two_factor_requirement (REST two_factor_requirement_enabled); otterdog never reads it, so the imported
    configuration shows the template default. Skipped when the live value equals that default (the bug is invisible).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.webui import mapping
from otterdog_e2e.webui.oracle import parse_settings_block, rest_web_values, web_values

if TYPE_CHECKING:
    from conftest import WebUiTier
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.otterdog.runner import CliResult, WebOtterdogCli

pytestmark = [pytest.mark.web_ui, pytest.mark.tags("org-settings", "cli")]

# printed by import, show-live and plan with -n (otterdog/operations/import_configuration.py, show_live.py)
NO_WEB_UI_WARNING = "the Web UI will not be queried as '--no-web-ui' has been specified"
# show-default prints the template's settings as ``key : value,`` (otterdog/operations/show_default.py)
TWO_FACTOR_DEFAULT_RE = re.compile(r"^\s*two_factor_requirement\s*:\s*(?P<value>true|false),?\s*$", re.MULTILINE)


@dataclass
class WebImport:
    """The single ``import`` without ``-n`` of the module (1 login) and its offline evaluation."""

    cli: WebOtterdogCli
    imported: CliResult
    shown: CliResult | None
    settings: dict[str, Any] | None
    rest: dict[str, Any]


@pytest.fixture(scope="module")
def web_import(e2e: E2EContext, web_sut: WebOtterdogCli, oracle: Oracle) -> WebImport:
    """``import -f`` without ``-n`` into the web workspace ``import``, then ``show --local`` (offline) and the REST
    values; shared by the tests of the import so that it costs one login."""
    cli = e2e.web_cli("head", name="import")
    imported = cli.import_config()
    shown = cli.show(local=True) if imported.exit_code == 0 and not imported.timed_out else None
    settings = parse_settings_block(shown.output) if shown is not None else None
    return WebImport(cli, imported, shown, settings, rest_web_values(oracle))


@pytest.mark.scenario("webui.settings.table")
@pytest.mark.timeout(600)
def test_web_settings_table_matches_the_sut(web_tier: WebUiTier) -> None:
    """mapping.WEB_SETTINGS agrees with the SUT's settings schema and web definitions (else update the table)."""
    source = web_tier.sut.installed.sut.source_dir
    problems = mapping.source_problems(source)
    assert not problems, f"the web settings of {web_tier.sut.installed.sut.label} changed: {problems}"


@pytest.mark.scenario("webui.settings.round-trip")
@pytest.mark.org_level
@pytest.mark.timeout(3600)
def test_web_settings_round_trip(web_tier: WebUiTier) -> None:
    """Toggle every writable web setting with the SUT, verify with REST and the trusted reader, converge, restore."""
    leftover = web_tier.recover_pending()
    assert not leftover, f"web values left changed by an earlier session could not be restored: {leftover}"
    report = web_tier.round_trip().run()
    web_tier.write_evidence("settings-round-trip", report.to_json())
    assert report.ok, report.summary()


@pytest.mark.scenario("webui.import.web-settings")
@pytest.mark.timeout(1200)
def test_import_reads_web_settings(web_tier: WebUiTier, web_import: WebImport) -> None:
    """``import -f`` without ``-n``: the imported configuration holds the live REST-readable web settings."""
    imported = web_import.imported
    assert imported.exit_code == 0 and not imported.timed_out, f"import failed:\n{imported.output[-2000:]}"
    assert NO_WEB_UI_WARNING not in imported.output, f"import without -n says it skipped the Web UI:\n{imported.output}"
    shown, settings = web_import.shown, web_import.settings
    assert shown is not None and settings is not None, f"show --local printed no settings block:\n{shown}"
    rest = web_import.rest
    keys = [key for key in mapping.REST_READABLE if key in mapping.WRITABLE and key in rest]
    differences = mapping.differences({key: rest[key] for key in keys}, settings, keys)
    web_tier.write_evidence("import", {"rest": rest, "imported": web_values(settings)})
    assert not differences, f"import wrote web settings that GitHub does not report: {differences}"


@pytest.mark.scenario("webui.kb.import-two-factor")
@pytest.mark.known_bug("KB-041")
@pytest.mark.tags("known-bug")
@pytest.mark.timeout(1200)
def test_import_reads_the_two_factor_requirement(web_import: WebImport) -> None:
    """The import without ``-n`` (the module's single login) carries the live two_factor_requirement (KB-041: the web
    reader never loads the security page, the imported configuration shows the template default)."""
    imported, settings = web_import.imported, web_import.settings
    assert imported.exit_code == 0 and settings is not None, f"import failed:\n{imported.output[-2000:]}"
    live = web_import.rest.get("two_factor_requirement")
    if live is None:
        pytest.skip("GET /orgs/{org} returned no two_factor_requirement_enabled (owner token needed)")
    default = TWO_FACTOR_DEFAULT_RE.search(normalize_text(web_import.cli.show_default(local=True).output))
    if default is not None and (default.group("value") == "true") is live:
        pytest.skip(
            f"the live two_factor_requirement ({live}) equals the template default: an unread value is invisible"
        )
    assert settings.get("two_factor_requirement") == live, (settings.get("two_factor_requirement"), live)
