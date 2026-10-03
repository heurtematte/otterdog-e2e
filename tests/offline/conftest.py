"""Fixtures of the offline tier (SPEC 2, 12.3): the SUT CLI against a vendored template, never GitHub.

Every test gets a fresh workspace of the offline organization ``e2e-offline`` (plugin fixture ``fresh_workspace``)
and an OtterdogCli built with ``offline=True``: dummy token, ``unshare -rn`` network sandbox for host installs
(fail closed in CI without it) and ``--network none`` for the docker runtime of untrusted SUTs. CLI artifacts go to
``<artifacts>/<run>/offline/<workspace>/cli/`` and the rendered configuration (redacted) to
``.../offline/<workspace>/workspace/`` when the test ends.

The SUT is the session's ``--e2e-sut`` (plugin fixture ``sut``: host venv for trusted SUTs, the CLI of the SUT image
for untrusted ones); the base template is the SUT's own ``examples/template``, vendored with ``--local`` so nothing is
cloned. Offline renders use the deterministic offline run context (run id ``spduo000``): identical names on every
run and on both sides of a differential run.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

from otterdog_e2e import procs
from otterdog_e2e.context import E2EContext, get_context
from otterdog_e2e.otterdog.runner import OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.scenarios.offline import OfflineEngine, offline_run_context
from otterdog_e2e.sut.cli_install import InstalledCli
from otterdog_e2e.sut.source import UpstreamMirror
from otterdog_e2e.sut.template import PUBLISHED_TEMPLATE_FILE, TEMPLATE_SOURCE_DIR, vendor_template


@dataclass(frozen=True)
class SutHistory:
    """Whether the SUT under test contains an upstream commit (ancestry in the harness' upstream mirror).

    Release, tag, branch and sha SUTs live in the mirror; pr: SUTs are fetched into it (refs/e2e/pull/N) and path:/
    dirty: SUTs (their HEAD commit) by fetch_from_local, so every resolved SUT sha is known there. Uncommitted changes
    of a dirty: SUT are not part of the history: a fix applied only to the working tree is reported as missing.
    """

    mirror: UpstreamMirror
    sha: str
    label: str

    def contains(self, commit: str) -> bool | None:
        """True when ``commit`` is an ancestor of (or equal to) the SUT, False when not, None when undecidable."""
        try:
            if not (self.mirror.has_commit(commit) and self.mirror.has_commit(self.sha)):
                return None
            return self.mirror.is_ancestor(commit, self.sha)
        except (ValueError, OSError, procs.CalledProcessError):
            return None


@pytest.fixture(scope="session")
def offline_context(request: pytest.FixtureRequest) -> E2EContext:
    """The session E2EContext (no live part: offline tests never build it)."""
    return get_context(request.config)


@pytest.fixture(scope="session")
def template_src(sut: InstalledCli) -> Path:
    """examples/template of the SUT source: the template every offline workspace vendors."""
    path = sut.sut.source_dir / TEMPLATE_SOURCE_DIR
    if not (path / PUBLISHED_TEMPLATE_FILE).is_file():
        pytest.fail(f"SUT {sut.sut.label} has no {TEMPLATE_SOURCE_DIR}/{PUBLISHED_TEMPLATE_FILE}", pytrace=False)
    return path


@pytest.fixture(scope="session")
def sut_history(offline_context: E2EContext, sut: InstalledCli) -> SutHistory:
    """SutHistory of the SUT under test."""
    settings = offline_context.settings
    return SutHistory(UpstreamMirror(settings.cache_dir, settings.upstream_repo), sut.sut.sha, sut.sut.label)


@pytest.fixture
def offline_cli(
    offline_context: E2EContext, sut: InstalledCli, fresh_workspace: ConfigWorkspace
) -> Iterator[OtterdogCli]:
    """Offline OtterdogCli of the SUT on a fresh e2e-offline workspace; the workspace is exported at teardown."""
    name = fresh_workspace.root.name
    cli = offline_context.cli(sut, fresh_workspace, name=f"offline-{name}", artifacts=f"offline/{name}", offline=True)
    yield cli
    fresh_workspace.export_to(offline_context.artifacts_dir / "offline" / name / "workspace")


@pytest.fixture
def vendored_cli(offline_cli: OtterdogCli, template_src: Path) -> OtterdogCli:
    """offline_cli whose workspace has the vendored SUT template (commands that load it; otterdog.json is written by
    the plugin's fresh_workspace)."""
    workspace = offline_cli.workspace
    vendor_template(template_src, workspace.org_dir, workspace.template)
    return offline_cli


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
