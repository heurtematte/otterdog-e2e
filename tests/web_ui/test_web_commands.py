"""UI-driven otterdog commands (docs/web-ui-testing.md): each one logs the admin bot in through the LoginGate.

webui.cmd.review-permissions: ``review-permissions`` (never ``-g``: nothing is approved) logs in and reads the
    installations page of the org (1 login); every ``app['<slug>']`` block it prints is an installed App and nothing
    is approved.
webui.cmd.list-advisories: ``list-advisories -w -s all`` prints its CSV, one row per repository advisory GitHub
    reports in the four states; it only logs in when the org has advisories (0 or 1 login).
webui.cmd.install-app (known bug KB-002): ``install-app`` then ``uninstall-app`` of the probe App
    (``web_ui.probe_app_slug``, a harmless App of the test org without permissions); since #699 both commands resolve
    token-only credentials, so their web login fails with "username not available" (non-strict xfail: an XPASS
    reveals the fix). Never the e2e App: uninstalling it would break the webapp tier.
webui.cmd.web-login: ``web-login`` opens a VISIBLE browser logged in as the bot and logs out at the first input line
    (the harness sends it at once): local runs with a display and ``E2E_WEB_LOGIN=1`` only, never in CI.
webui.cmd.install-deps: ``install-deps`` runs ``<python> -m playwright install firefox`` (otterdog/cli.py
    install_deps), no login: with the tier's browsers dir (the SUT's Firefox installed before the first item) it
    succeeds without downloading anything (run in the offline sandbox: no network at all); with an empty dir the
    download fails and 'could not install required dependencies: <status>' is printed, nothing is installed.
webui.kb.install-deps-exit-code (known bug KB-047): that failed installation still exits 0.
"""

from __future__ import annotations

import csv
import os
import re
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.context import env_flag, in_ci
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.sut.cli_install import PLAYWRIGHT_BROWSERS_ENV
from otterdog_e2e.webui.gate import classify_web_failure

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import WebUiTier
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli

pytestmark = [pytest.mark.web_ui, pytest.mark.tags("cli")]

# otterdog/operations/list_advisories.py CSV_FIELDS (unchanged since v1.4.0)
ADVISORY_FIELDS = (
    "organization",
    "created_at",
    "days_since_created",
    "updated_at",
    "days_since_updated",
    "published_at",
    "last_commented_at",
    "days_since_last_commented",
    "state",
    "severity",
    "ghsa_id",
    "cve_id",
    "html_url",
    "summary",
)
REVIEW_HEADER = "Reviewing permission updates for app installations:"
REVIEW_FAILURE = "failed to process app installation with id"  # review_app_permissions.py: an unknown installation
APPROVED_TEXT = "requested permissions approved."
APP_BLOCK_RE = re.compile(r"^\s*app\['(?P<slug>[^']+)'\] \{", re.MULTILINE)
INSTALLED_TEXTS = ("app installed.", "app already installed, skipping.")
UNINSTALLED_TEXT = "uninstalled app."
ADVISORY_STATES = ("triage", "draft", "published", "closed")  # what "-s all" expands to
INSTALL_FAILURE_RE = re.compile(r"Error: could not install required dependencies: (?P<status>-?\d+)")
WEB_LOGIN_POSSIBLE = (
    not in_ci(os.environ)
    and bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    and env_flag(os.environ, "E2E_WEB_LOGIN")
)


def _failure_hint(output: str) -> str:
    """The recognized web-client failure of an output (for assertion messages)."""
    failure = classify_web_failure(output)
    return f" [{failure.kind}: {failure.hint}]" if failure is not None else ""


@pytest.mark.scenario("webui.cmd.review-permissions")
@pytest.mark.timeout(1200)
def test_review_permissions_lists_requests(web_tier: WebUiTier) -> None:
    """``review-permissions``: logs in, reads the installations page, exits 0 without approving anything; every
    pending request it lists (``app['<slug>']``) belongs to an App installed on the org."""
    result = web_tier.sut.review_permissions()
    listed = APP_BLOCK_RE.findall(normalize_text(result.output))
    web_tier.write_evidence(
        "review-permissions", {"exit_code": result.exit_code, "notes": result.notes, "requests": listed}
    )
    assert result.exit_code == 0 and not result.timed_out, (
        f"review-permissions failed{_failure_hint(result.output)}:\n{result.output[-2000:]}"
    )
    assert REVIEW_HEADER in result.output, f"unexpected output:\n{result.output[-2000:]}"
    assert classify_web_failure(result.output) is None, f"web login problem:{_failure_hint(result.output)}"
    assert REVIEW_FAILURE not in result.output, f"a request of an unknown installation:\n{result.output[-2000:]}"
    assert APPROVED_TEXT not in result.output, "review-permissions without -g approved a request"
    unknown = sorted(set(listed) - web_tier.installed_slugs())
    assert not unknown, f"requests listed for Apps that are not installed: {unknown}"


@pytest.mark.scenario("webui.cmd.list-advisories")
@pytest.mark.timeout(1200)
def test_list_advisories_with_web(web_tier: WebUiTier) -> None:
    """``list-advisories -w -s all``: the CSV header, then one complete row per advisory GitHub reports in the four
    states."""
    result = web_tier.sut.list_advisories(states=("all",))
    assert result.exit_code == 0 and not result.timed_out, (
        f"list-advisories -w failed{_failure_hint(result.output)}:\n{result.output[-2000:]}"
    )
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    header = ",".join(ADVISORY_FIELDS)
    assert header in lines, f"no CSV header in:\n{result.stdout[-2000:]}"
    rows = list(csv.reader(lines[lines.index(header) + 1 :]))
    web_tier.write_evidence("list-advisories", {"advisories": len(rows), "notes": result.notes})
    incomplete = [row for row in rows if len(row) != len(ADVISORY_FIELDS)]
    assert not incomplete, f"{len(incomplete)} CSV row(s) without the {len(ADVISORY_FIELDS)} fields"
    listed = {row[ADVISORY_FIELDS.index("ghsa_id")] for row in rows}
    live = {
        str(item["ghsa_id"])
        for item in web_tier.oracle.org_security_advisories()
        if item.get("state") in ADVISORY_STATES
    }
    assert listed == live, f"CSV advisories {sorted(listed)}, GitHub reports {sorted(live)}"


@pytest.mark.scenario("webui.cmd.install-app")
@pytest.mark.known_bug("KB-002")
@pytest.mark.timeout(1800)
def test_install_and_uninstall_app(web_tier: WebUiTier) -> None:
    """``install-app`` then ``uninstall-app`` of the probe App, each verified through REST (installations)."""
    slug = web_tier.target.web_probe_app_slug
    if not slug:
        pytest.skip("web_ui.probe_app_slug is not configured (a harmless App of the test org, docs/web-ui-testing.md)")
    installed_before = slug in web_tier.installed_slugs()
    try:
        if not installed_before:
            install = web_tier.sut.install_app(slug)
            assert install.exit_code == 0 and any(text in install.output for text in INSTALLED_TEXTS), (
                f"install-app -a {slug} failed{_failure_hint(install.output)}:\n{install.output[-2000:]}"
            )
            assert slug in web_tier.installed_slugs(), f"install-app reported success but {slug} is not installed"
        uninstall = web_tier.sut.uninstall_app(slug)
        assert uninstall.exit_code == 0 and UNINSTALLED_TEXT in uninstall.output, (
            f"uninstall-app -a {slug} failed{_failure_hint(uninstall.output)}:\n{uninstall.output[-2000:]}"
        )
        assert slug not in web_tier.installed_slugs(), f"uninstall-app reported success but {slug} is still installed"
    finally:
        web_tier.write_evidence(
            "install-app", {"slug": slug, "installed_before": installed_before, "installed": web_tier.installed_slugs()}
        )


@pytest.mark.scenario("webui.cmd.web-login")
@pytest.mark.skipif(
    not WEB_LOGIN_POSSIBLE,
    reason="web-login opens a visible browser: local runs with a display and E2E_WEB_LOGIN=1 only, never in CI",
)
@pytest.mark.timeout(600)
def test_web_login_opens_a_session(web_tier: WebUiTier) -> None:
    """``web-login``: the bot's browser session opens and closes (the harness answers the prompt at once)."""
    result = web_tier.sut.web_login(timeout=300)
    assert result.exit_code == 0 and not result.timed_out, (
        f"web-login failed{_failure_hint(result.output)}:\n{result.output[-2000:]}"
    )


# --- install-deps (no login) -------------------------------------------------------------------------------------------
def _offline_cli(web_tier: WebUiTier, name: str) -> OtterdogCli:
    """The SUT's host CLI in the offline sandbox (``unshare -rn``: no network at all, dummy token, no web login)."""
    e2e = web_tier.e2e
    workspace = e2e.offline_workspace(e2e.unique_name(f"webui-{name}"))
    return e2e.cli(web_tier.sut.installed, workspace, name=f"webui-{name}", offline=True)


def _install_deps(web_tier: WebUiTier, browsers: Path, name: str) -> tuple[CliResult, str]:
    """``otterdog install-deps`` with PLAYWRIGHT_BROWSERS_PATH=<browsers>, offline; the result and its normalized
    output."""
    result = _offline_cli(web_tier, name).invoke("install-deps", env={PLAYWRIGHT_BROWSERS_ENV: str(browsers)})
    return result, normalize_text(result.output)


def _firefox_builds(browsers: Path) -> list[str]:
    """``firefox-<revision>`` directories of a Playwright browsers dir."""
    if not browsers.is_dir():
        return []
    return sorted(entry.name for entry in browsers.iterdir() if entry.is_dir() and entry.name.startswith("firefox-"))


def _empty_browsers_dir(web_tier: WebUiTier, name: str) -> Path:
    """A new, empty browsers dir in the private scratch."""
    path = web_tier.e2e.scratch / "webui-install-deps" / web_tier.e2e.unique_name(name)
    path.mkdir(mode=0o700, parents=True)
    return path


@pytest.mark.scenario("webui.cmd.install-deps")
@pytest.mark.timeout(600)
def test_install_deps_keeps_the_installed_firefox(web_tier: WebUiTier) -> None:
    """With the tier's browsers dir (the SUT's Firefox installed) install-deps succeeds offline: no error (a download
    attempt would fail without network) and no new Firefox build (Playwright may only drop builds no installation
    links any more)."""
    browsers = web_tier.sut.web.browsers_path if web_tier.sut.web is not None else None
    assert browsers is not None, "the web-mode SUT has no browsers dir"
    before = _firefox_builds(browsers)
    assert before, f"no Firefox build in {browsers} (the tier installs it before its first item)"
    result, text = _install_deps(web_tier, browsers, "install-deps")
    assert result.exit_code == 0 and not result.timed_out, f"exit {result.exit_code}:\n{text[-2000:]}"
    assert INSTALL_FAILURE_RE.search(text) is None, f"install-deps reported a failure:\n{text[-2000:]}"
    after = _firefox_builds(browsers)
    assert after and set(after) <= set(before), (before, after)


@pytest.mark.scenario("webui.cmd.install-deps")
@pytest.mark.timeout(600)
def test_install_deps_reports_a_failed_download(web_tier: WebUiTier) -> None:
    """With an empty browsers dir and no network the download fails: install-deps prints 'could not install required
    dependencies: <non-zero status>' and installs nothing."""
    browsers = _empty_browsers_dir(web_tier, "failed-download")
    result, text = _install_deps(web_tier, browsers, "install-deps-failure")
    failure = INSTALL_FAILURE_RE.search(text)
    assert failure is not None and int(failure.group("status")) != 0, (
        f"no installation failure reported:\n{text[-2000:]}"
    )
    assert not result.timed_out, text[-2000:]
    assert not _firefox_builds(browsers), f"a failed download installed {_firefox_builds(browsers)}"


@pytest.mark.scenario("webui.kb.install-deps-exit-code")
@pytest.mark.known_bug("KB-047")
@pytest.mark.tags("known-bug")
@pytest.mark.timeout(600)
def test_failed_install_deps_exits_non_zero(web_tier: WebUiTier) -> None:
    """A failed browser installation is a failure of install-deps: non-zero exit (KB-047: it exits 0)."""
    result, text = _install_deps(web_tier, _empty_browsers_dir(web_tier, "exit-code"), "install-deps-exit")
    assert INSTALL_FAILURE_RE.search(text) is not None, text[-2000:]
    assert result.exit_code != 0, f"install-deps exited {result.exit_code} although the installation failed"
