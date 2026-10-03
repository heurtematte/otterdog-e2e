"""``list-blueprints`` / ``approve-blueprints`` of the otterdog CLI installed without the webapp.

Both commands read the remediation PRs of the webapp anonymously from ``<defaults.base_url>/api/blueprints/
remediations`` (otterdog/operations/list_blueprints.py, approve_blueprints.py) and refuse to run without a base_url:
"no base_url set which is required when using operation '<command>'" (a RuntimeError of pre_execute, exit 2).

cli.kb.blueprint-commands-without-webapp (known bug KB-042): the two operation modules import
    ``otterdog.webapp.db.models`` at the top. The published distribution excludes ``otterdog/webapp`` (pyproject.toml
    ``exclude``) and the webapp's dependencies (odmantic, quart, ...) are the optional ``app`` group, so a CLI-only
    install (``pip install otterdog``: "No module named 'otterdog.webapp'"; ``poetry sync --only main``, the
    harness's host install: "No module named 'quart_flask_patch'") crashes with a ModuleNotFoundError traceback
    (exit 1) before the base_url check. The test asserts the documented refusal. It only runs where the bug can show:
    a host install of the SUT without the webapp dependencies (the SUT image of untrusted SUTs bundles them).

The commands against a running webapp (a remediation PR listed, then merged) need a CLI with the ``app`` group in a
build directory of its own and the webapp tier's ``blueprints`` fixture (W-BP-APPROVE, tests/webapp).
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.otterdog.workspace import WorkspaceLayout

if TYPE_CHECKING:
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.sut.cli_install import InstalledCli

pytestmark = [pytest.mark.tags("cli", "webapp")]

WEBAPP_DEPENDENCY = "quart_flask_patch"  # the first import of otterdog/webapp/__init__.py
CRASH_MARKERS = ("ModuleNotFoundError", "Traceback (most recent call last)")


def webapp_dependencies_installed(sut: InstalledCli) -> bool:
    """True when the SUT's venv holds the webapp's dependencies (an install with the ``app`` group)."""
    if sut.venv_dir is None:
        return True
    return any(sut.venv_dir.glob(f"lib/python*/site-packages/{WEBAPP_DEPENDENCY}*"))


@pytest.mark.scenario("cli.kb.blueprint-commands-without-webapp", priority="P1")
@pytest.mark.known_bug("KB-042")
@pytest.mark.tags("known-bug")
@pytest.mark.parametrize("command", ["list-blueprints", "approve-blueprints"])
def test_blueprint_commands_need_a_base_url(
    command: str,
    sut: InstalledCli,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """Without defaults.base_url the command refuses to run ('no base_url set ...', exit 2) instead of crashing on
    the webapp modules a CLI-only install lacks (KB-042)."""
    if sut.runtime != "host":
        pytest.skip(f"the SUT runs in its image ({sut.runtime}), which bundles the webapp dependencies")
    if webapp_dependencies_installed(sut):
        pytest.skip("the SUT install holds the webapp dependencies (app group): the CLI-only install is not tested")
    document = copy.deepcopy(fresh_workspace.otterdog_json())
    document["defaults"].pop("base_url", None)
    fresh_workspace.use_layout(WorkspaceLayout(document=document))
    result = make_cli(fresh_workspace).run(command)
    text = cli_lines(result)
    crash = [marker for marker in CRASH_MARKERS if marker in text]
    assert not crash, f"{command} crashed ({', '.join(crash)}):\n{text[-1500:]}"
    assert f"no base_url set which is required when using operation '{command}'" in text, text[-2000:]
    assert result.exit_code == 2, f"exit {result.exit_code}"
