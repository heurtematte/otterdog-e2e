"""OrgConfigRenderer with libraries and overlays (render.py, resources/org.jsonnet.j2).

Libraries are inlined as ``local <name> = (<expression>);`` right after the template import, overlays are object
mixins after layer 2 (``<org> + (<overlay>)``), both verbatim. The renders are evaluated with the jsonnet binary on
the vendored template copy (tests/unit/data/template, examples/template of otterdog main @9bdeb75), like the other
render tests, and, when E2E_TEST_OTTERDOG names an otterdog executable, validated with ``otterdog validate --local``
through the offline OtterdogCli (dummy token, unshare -rn sandbox when available).
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import procs
from otterdog_e2e.otterdog.render import (
    BaselineSpec,
    ConfigFragments,
    OrgConfigRenderer,
    RenderError,
    library_name_problem,
)
from otterdog_e2e.sut.template import offline_template

TEMPLATE_DIR = Path(__file__).parent / "data" / "template"
ORG = "e2e-offline"
MARKER = "[otterdog-e2e]"
JSONNET = shutil.which("jsonnet")
OTTERDOG = os.environ.get("E2E_TEST_OTTERDOG")  # optional otterdog executable for the validate test

LIBRARY = """// helpers (a trailing line comment is fine: the closing parenthesis is on its own line)
{
  publicRepo(name, description='otterdog e2e'):: orgs.newRepo(name) { description: description },
} // end
"""
SECOND_LIBRARY = "{ privateRepo(name):: e2e.publicRepo(name) { private: true, allow_forking: false, has_wiki: false } }"


def renderer(*, baseline: BaselineSpec | None = None) -> OrgConfigRenderer:
    """Renderer of the offline organization with the offline template."""
    return OrgConfigRenderer(
        template=offline_template(),
        org=ORG,
        plan="free",
        org_profile={"description": f"{MARKER} offline organization"},
        baseline=baseline or BaselineSpec(),
        marker=MARKER,
        hide_cache_limit=False,
    )


def fragments(**values: Any) -> ConfigFragments:
    """ConfigFragments with the given fields."""
    return ConfigFragments(**values)


def test_without_libraries_and_overlays_nothing_changes() -> None:
    """No local and no mixin are added: the import is followed by the org, layer 2 ends the file."""
    text = renderer().render(fragments(repositories=["orgs.newRepo('e2e-spduo000-a')"]))
    body = text.split("*/", 1)[1]  # after the header comment, which documents the forms
    assert "local orgs = orgs0;\n\norgs.newOrg('e2e-offline', 'e2e-offline') {" in body
    assert body.endswith("    orgs.newRepo('e2e-spduo000-a'),\n  ],\n}\n") and " + (" not in body
    assert body.count("local ") == 2


def test_libraries_follow_the_template_import_in_order() -> None:
    """One ``local`` per library, in order, between the template locals and the org; the text is stripped only."""
    text = renderer().render(fragments(libraries={"e2e": f"\n{LIBRARY}\n", "more": SECOND_LIBRARY}))
    expected = (
        "local orgs = orgs0;\n"
        f"local e2e = (\n{LIBRARY.strip()}\n);\n"
        f"local more = (\n{SECOND_LIBRARY}\n);\n"
        "\norgs.newOrg('e2e-offline', 'e2e-offline') {"
    )
    assert expected in text


def test_overlays_follow_layer_two_in_order() -> None:
    """Each overlay is a ``+ (...)`` mixin after the second layer, on its own lines."""
    text = renderer().render(fragments(overlays=["{ a:: 1 }", "{ b:: 2 } // last\n"]))
    assert text.endswith("} {\n} + (\n{ a:: 1 }\n) + (\n{ b:: 2 } // last\n)\n")


@pytest.mark.parametrize("name", ["orgs", "orgs0", "std", "self", "super", "$", "local", "import", "1st", "a-b", ""])
def test_library_names_are_checked(name: str) -> None:
    """A library name is a jsonnet identifier that is no keyword and shadows no template local."""
    assert library_name_problem(name)
    with pytest.raises(RenderError, match="library name"):
        renderer().render(fragments(libraries={name: "{}"}))


def test_valid_library_names_and_empty_content() -> None:
    """Identifiers are accepted; empty libraries and overlays would not parse and are refused."""
    assert library_name_problem("e2e") is None and library_name_problem("_helpers2") is None
    with pytest.raises(RenderError, match="library 'e2e' is empty"):
        renderer().render(fragments(libraries={"e2e": " \n"}))
    with pytest.raises(RenderError, match="overlay is empty"):
        renderer().render(fragments(overlays=["\n"]))


def test_config_fragments_carry_libraries_and_overlays() -> None:
    """merged concatenates overlays and unions libraries (the other's definition wins); to_mapping keeps the
    fragment keys only; overlays make fragments non-empty, libraries alone do not."""
    first = fragments(libraries={"a": "1", "b": "2"}, overlays=["{ x:: 1 }"])
    second = fragments(libraries={"b": "3"}, overlays=["{ y:: 2 }"], repositories=["orgs.newRepo('r')"])
    merged = first.merged(second)
    assert merged.libraries == {"a": "1", "b": "3"} and merged.overlays == ["{ x:: 1 }", "{ y:: 2 }"]
    assert "libraries" not in merged.to_mapping() and "overlays" not in merged.to_mapping()
    assert not fragments(overlays=["{}"]).is_empty() and fragments(libraries={"a": "{}"}).is_empty()


# --- evaluation with the jsonnet binary --------------------------------------------------------------------------
def manifest(text: str, root: Path) -> dict[str, Any]:
    """Manifest a rendered config with jsonnet against the vendored template copy."""
    org_dir = root / "orgs" / ORG
    if not (org_dir / "vendor" / "template").is_dir():
        shutil.copytree(TEMPLATE_DIR, org_dir / "vendor" / "template")
    config = org_dir / f"{ORG}.jsonnet"
    config.write_text(text, encoding="utf-8")
    completed = procs.run([str(JSONNET), config.name], cwd=org_dir, timeout=60, home=root / "home")
    assert completed.returncode == 0, completed.stderr[-2000:]
    data: dict[str, Any] = json.loads(completed.stdout)
    return data


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
def test_libraries_and_overlays_manifest(tmp_path: Path) -> None:
    """Libraries see orgs and the libraries before them; overlays apply after both layers, in order, and win."""
    rendered = fragments(
        libraries={"e2e": LIBRARY, "more": SECOND_LIBRARY},
        repositories=["e2e.publicRepo('e2e-spduo000-a')", "more.privateRepo('e2e-spduo000-b')"],
        overlays=[
            "{ _repositories+: [e2e.publicRepo('e2e-spduo000-c', 'from an overlay')] }",
            "{ _repositories: [r { description: 'last overlay wins' } for r in super._repositories] } # mixin\n",
        ],
    )
    org = manifest(renderer().render(rendered), tmp_path)
    repos = {repo["name"]: repo for repo in org["repositories"]}
    assert sorted(repos) == ["e2e-spduo000-a", "e2e-spduo000-b", "e2e-spduo000-c"]
    assert {repo["description"] for repo in repos.values()} == {"last overlay wins"}
    assert repos["e2e-spduo000-b"]["private"] is True and repos["e2e-spduo000-b"]["allow_forking"] is False
    assert org["settings"]["description"] == f"{MARKER} offline organization"


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
def test_overlays_see_the_baseline_layer(tmp_path: Path) -> None:
    """An overlay rewrites what layer 1 declared too (that is why live overlays touching settings need org_level and
    removals stay guarded)."""
    baseline = BaselineSpec(repositories=["orgs.newRepo('otterdog-e2e-configs') { description: 'configs' }"])
    overlay = "{ _repositories: [r { topics+: ['overlay'] } for r in super._repositories] }"
    org = manifest(renderer(baseline=baseline).render(fragments(overlays=[overlay])), tmp_path)
    assert [(repo["name"], repo["topics"]) for repo in org["repositories"]] == [("otterdog-e2e-configs", ["overlay"])]


# --- validation with a real otterdog CLI (optional) ----------------------------------------------------------------
@pytest.mark.skipif(not OTTERDOG, reason="set E2E_TEST_OTTERDOG to an otterdog executable to validate with otterdog")
def test_otterdog_validates_libraries_and_overlays(tmp_path: Path) -> None:
    """``otterdog validate --local`` accepts a render with a library and an overlay (offline CLI, dummy token)."""
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import HarnessSettings
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.spec import ResolvedSut, SutSpec
    from otterdog_e2e.sut.template import vendor_template

    workspace = ConfigWorkspace(tmp_path / "ws", org=ORG, template=offline_template(), config_repo=".otterdog")
    workspace.write_otterdog_json()
    vendor_template(TEMPLATE_DIR, workspace.org_dir, workspace.template)
    rendered = fragments(
        libraries={"e2e": LIBRARY},
        repositories=["e2e.publicRepo('e2e-spduo000-a') { has_wiki: false }"],
        overlays=["{ _repositories+: [e2e.publicRepo('e2e-spduo000-b')] }"],
    )
    workspace.write_org_config(renderer().render(rendered))
    sut = ResolvedSut(SutSpec("path:.", "path", "."), "local", "0" * 40, "0.0.0", "0.0.0", tmp_path, "local", True)
    settings = HarnessSettings(
        tmp_path, tmp_path / "cache", tmp_path / "artifacts", "eclipse-csi/otterdog", tmp_path, tmp_path
    )
    cli = OtterdogCli(
        InstalledCli(sut, "host", None, Path(str(OTTERDOG)), None, ""),
        workspace,
        verified=None,
        identity=None,
        scratch=tmp_path / "scratch",
        artifacts_dir=tmp_path / "artifacts",
        settings=settings,
        offline=True,
    )
    result = cli.validate(local=True)
    validation = result.validation()
    assert result.exit_code == 0 and validation.ok and not validation.errors, result.output[-2000:]
