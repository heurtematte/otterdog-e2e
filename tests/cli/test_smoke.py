"""C-SMOKE (SPEC 19, P0): the SUT CLI runs against the test org (--version, check-token-permissions, list-projects).

No baseline reset is needed: these commands only read (the token's scopes, otterdog.json). They run first in any
lane selection because they carry the 'smoke' tag (selection.ALWAYS_TAGS).

check-token-permissions only knows classic scopes: with a fine-grained admin token it reports all five as missing
(KB-078), which this smoke test reports as an expected failure (cli.kb.check-token-permissions-fine-grained asserts
the correct behaviour).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.sut.version import public_version

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.cli_install import InstalledCli

pytestmark = [pytest.mark.scenario("cli.smoke"), pytest.mark.tags("smoke", "cli")]

# printed by CheckTokenPermissionsOperation when a scope of EXPECTED_SCOPES is missing (check_token_permissions.py:64)
MISSING_SCOPES_TEXT = "Missing scopes"


def test_version(otterdog: OtterdogCli, sut: InstalledCli) -> None:
    """``otterdog --version`` prints the version the harness installed (public part, local label ignored)."""
    printed = otterdog.version()
    expected = public_version(sut.sut.version)
    assert expected in printed, f"otterdog --version printed {printed!r}, expected version {expected}"


def test_check_token_permissions(otterdog: OtterdogCli, e2e: E2EContext) -> None:
    """The admin token has every scope otterdog requires (admin:org, admin:org_hook, delete_repo, repo, workflow).

    A fine-grained admin token has no classic scopes: otterdog reporting them missing is KB-078 (expected failure).
    """
    kind = e2e.http("admin").token_info().kind
    result = otterdog.check_token_permissions()
    if kind != "classic" and (result.exit_code != 0 or MISSING_SCOPES_TEXT in result.output):
        pytest.xfail(f"KB-078: check-token-permissions only knows classic scopes ({kind} admin token)")
    result.assert_ok("check-token-permissions")
    assert MISSING_SCOPES_TEXT not in result.output, result.output[-2000:]


def test_list_projects(otterdog: OtterdogCli, target: Target) -> None:
    """``list-projects`` (no org positional) lists the test org from the workspace's otterdog.json."""
    result = otterdog.list_projects().assert_ok("list-projects")
    assert target.org in result.output, result.output[-2000:]
