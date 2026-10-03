"""C-SMOKE (SPEC 19, P0): the SUT CLI runs against the test org (--version, check-token-permissions, list-projects).

No baseline reset is needed: these commands only read (the token's scopes, otterdog.json). They run first in any
lane selection because they carry the 'smoke' tag (selection.ALWAYS_TAGS).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.sut.version import public_version

if TYPE_CHECKING:
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


def test_check_token_permissions(otterdog: OtterdogCli) -> None:
    """The admin token has every scope otterdog requires (admin:org, admin:org_hook, delete_repo, repo, workflow)."""
    result = otterdog.check_token_permissions().assert_ok("check-token-permissions")
    assert MISSING_SCOPES_TEXT not in result.output, result.output[-2000:]


def test_list_projects(otterdog: OtterdogCli, target: Target) -> None:
    """``list-projects`` (no org positional) lists the test org from the workspace's otterdog.json."""
    result = otterdog.list_projects().assert_ok("list-projects")
    assert target.org in result.output, result.output[-2000:]
