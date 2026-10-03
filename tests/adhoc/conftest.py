"""Fixtures of the ad-hoc injection tests (``otterdog-e2e inject``, tests/adhoc/test_adhoc.py).

The offline fixtures mirror tests/offline/conftest.py (conftest fixtures are per directory): the SUT CLI with
``offline=True`` (dummy token, ``unshare -rn`` or ``--network none``) on a fresh ``e2e-offline`` workspace whose
template is the SUT's own examples/template, vendored with ``--local``. CLI outputs go to
``<artifacts>/<run>/adhoc/cli/``; the test itself exports the rendered configuration. Live injections use the plugin's
session fixtures (scenario_engine: lease, baseline, guards, trusted reset CLI) unchanged.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from otterdog_e2e.context import E2EContext, get_context
from otterdog_e2e.inject import ADHOC_DIR
from otterdog_e2e.otterdog.runner import OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.scenarios.offline import OfflineEngine, offline_run_context
from otterdog_e2e.sut.cli_install import InstalledCli
from otterdog_e2e.sut.template import PUBLISHED_TEMPLATE_FILE, TEMPLATE_SOURCE_DIR


@pytest.fixture(scope="session")
def offline_context(request: pytest.FixtureRequest) -> E2EContext:
    """The session E2EContext (no live part: offline injections never build it)."""
    return get_context(request.config)


@pytest.fixture(scope="session")
def template_src(sut: InstalledCli) -> Path:
    """examples/template of the SUT source: the template the offline workspace vendors."""
    path = sut.sut.source_dir / TEMPLATE_SOURCE_DIR
    if not (path / PUBLISHED_TEMPLATE_FILE).is_file():
        pytest.fail(f"SUT {sut.sut.label} has no {TEMPLATE_SOURCE_DIR}/{PUBLISHED_TEMPLATE_FILE}", pytrace=False)
    return path


@pytest.fixture
def offline_cli(offline_context: E2EContext, sut: InstalledCli, fresh_workspace: ConfigWorkspace) -> OtterdogCli:
    """Offline OtterdogCli of the SUT on a fresh e2e-offline workspace (outputs under adhoc/cli/)."""
    name = fresh_workspace.root.name
    return offline_context.cli(sut, fresh_workspace, name=f"adhoc-{name}", artifacts=ADHOC_DIR, offline=True)


@pytest.fixture
def offline_engine(offline_context: E2EContext, offline_cli: OtterdogCli, template_src: Path) -> OfflineEngine:
    """OfflineEngine of the SUT (deterministic offline run context, the SUT's own template, the session's known bugs
    for step-level known_bug)."""
    engine = OfflineEngine(
        cli=offline_cli,
        workspace=offline_cli.workspace,
        template_src=template_src,
        run_ctx=offline_run_context(),
    )
    engine.known_bugs = offline_context.known_bugs()
    return engine
