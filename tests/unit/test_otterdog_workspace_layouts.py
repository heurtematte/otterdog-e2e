"""WorkspaceLayout: otterdog.jsonnet, extra organizations, .otterdog-defaults.json, base_url, config_dir, a complete
document and vendor=False (config-discovery tests; keys verified against otterdog/config.py and otterdog/cli.py)."""

from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from otterdog_e2e.otterdog.workspace import (
    CREDENTIAL_ENV,
    DEFAULTS_OVERRIDE_FILE,
    ConfigWorkspace,
    WorkspaceLayout,
    jsonnet_config_text,
)
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FAKE_ORG, FakeWorkspace

ENV_PROVIDER = {"provider": "env", **CREDENTIAL_ENV}


def workspace(tmp_path: Path, **kwargs: object) -> ConfigWorkspace:
    """A ConfigWorkspace of org ``o`` below tmp_path/ws."""
    return ConfigWorkspace(tmp_path / "ws", org="o", template=offline_template(), config_repo=".otterdog", **kwargs)  # type: ignore[arg-type]


def test_the_default_layout_is_the_harness_layout(tmp_path: Path) -> None:
    """Nothing changes without a layout: otterdog.json, orgs/<org>, one organization, no override file."""
    ws = workspace(tmp_path)
    assert ws.layout == WorkspaceLayout() and ws.layout.is_default
    assert ws.config_file == tmp_path / "ws" / "otterdog.json" and ws.org_dir == tmp_path / "ws" / "orgs" / "o"
    path = ws.write_otterdog_json()
    assert path == ws.config_file and sorted(p.name for p in ws.root.iterdir()) == ["otterdog.json"]
    data = json.loads(path.read_text())
    assert data["defaults"]["jsonnet"]["config_dir"] == "orgs" and len(data["organizations"]) == 1


def test_jsonnet_format_writes_otterdog_jsonnet_and_drops_the_json(tmp_path: Path) -> None:
    """The ``jsonnet`` format writes otterdog.jsonnet (a jsonnet local, so a JSON parser refuses it), the -c file
    follows the format and a stale otterdog.json of an earlier layout is removed."""
    ws = workspace(tmp_path)
    ws.write_otterdog_json()
    path = ws.use_layout(WorkspaceLayout(format="jsonnet"))
    assert path == tmp_path / "ws" / "otterdog.jsonnet" == ws.config_file
    assert not (tmp_path / "ws" / "otterdog.json").exists()
    text = path.read_text()
    assert text.startswith("// otterdog.jsonnet written by otterdog-e2e") and "local config = {" in text
    assert text.rstrip().endswith("config")
    with pytest.raises(json.JSONDecodeError):
        json.loads(text)
    body = text.split("local config = ", 1)[1].rsplit(";", 1)[0]
    assert json.loads(body) == ws.otterdog_json()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert jsonnet_config_text({"a": 1}).endswith('local config = {\n  "a": 1\n};\n\nconfig\n')


def test_extra_organizations(tmp_path: Path) -> None:
    """A string entry is an ordinary organization; a mapping is merged over {name: github_id, config_repo, env
    credentials}; null values stay null (otterdog then reports the missing key)."""
    layout = WorkspaceLayout(
        orgs=(
            "o2",
            {"github_id": "o3", "archived": True},
            {"name": None, "github_id": "o4"},
            {"name": "only-name", "credentials": None, "approval_teams": 42},
        )
    )
    ws = workspace(tmp_path)
    ws.use_layout(layout)
    entries = json.loads(ws.config_file.read_text())["organizations"]
    assert entries[0]["github_id"] == "o" and entries[0]["credentials"] == ENV_PROVIDER
    assert entries[1] == {"name": "o2", "github_id": "o2", "config_repo": ".otterdog", "credentials": ENV_PROVIDER}
    assert entries[2] == {
        "name": "o3",
        "github_id": "o3",
        "config_repo": ".otterdog",
        "credentials": ENV_PROVIDER,
        "archived": True,
    }
    assert entries[3]["name"] is None and entries[3]["github_id"] == "o4"
    assert "github_id" not in entries[4] and entries[4]["credentials"] is None and entries[4]["approval_teams"] == 42
    assert ws.org_ids == ["o", "o2", "o3", "o4"]
    assert ws.org_config_file_for("o2") == tmp_path / "ws" / "orgs" / "o2" / "o2.jsonnet"


def test_defaults_override_base_url_and_config_dir(tmp_path: Path) -> None:
    """.otterdog-defaults.json is written next to the config file (removed again without an override); its
    jsonnet.config_dir wins over the layout's, like otterdog's deep merge; base_url overrides the workspace's."""
    ws = workspace(tmp_path, base_url="https://configured.invalid")
    layout = WorkspaceLayout(
        defaults_override={"jsonnet": {"config_dir": "orgs-override", "base_template": None}},
        base_url="https://override.invalid",
        config_dir="orgs-alt",
    )
    ws.use_layout(layout)
    override = tmp_path / "ws" / DEFAULTS_OVERRIDE_FILE
    assert json.loads(override.read_text()) == {"jsonnet": {"config_dir": "orgs-override", "base_template": None}}
    data = json.loads(ws.config_file.read_text())
    assert data["defaults"]["base_url"] == "https://override.invalid"
    assert data["defaults"]["jsonnet"]["config_dir"] == "orgs-alt"
    assert ws.config_dir == "orgs-override" and ws.org_dir == tmp_path / "ws" / "orgs-override" / "o"
    assert ws.templates_dir == tmp_path / "ws" / "orgs-override" / "templates"
    assert ws.base_config_file == tmp_path / "ws" / "orgs-override" / "o" / "o.jsonnet-BASE"
    ws.use_layout(WorkspaceLayout(config_dir="orgs-alt"))
    assert not override.exists() and ws.org_dir == tmp_path / "ws" / "orgs-alt" / "o"
    ws.use_layout(WorkspaceLayout())
    assert json.loads(ws.config_file.read_text())["defaults"]["base_url"] == "https://configured.invalid"


def test_a_complete_document_is_written_as_it_is(tmp_path: Path) -> None:
    """``document`` replaces the generated configuration (e.g. no defaults.jsonnet.base_template)."""
    document = {"defaults": {"jsonnet": {"config_dir": "orgs"}}, "organizations": [{"name": "o", "github_id": "o"}]}
    ws = workspace(tmp_path)
    ws.use_layout(WorkspaceLayout(document=document))
    assert json.loads(ws.config_file.read_text()) == document
    ws.use_layout(WorkspaceLayout(document=document, format="jsonnet"))
    assert "local config = " in ws.config_file.read_text()


def test_org_and_base_config_files_of_any_organization_and_suffix(tmp_path: Path) -> None:
    """write_org_config / write_base_config / read_org_config take another organization and another suffix."""
    ws = workspace(tmp_path)
    ws.use_layout(WorkspaceLayout(orgs=("o2",)))
    ws.write_org_config("{ a: 1 }", org="o2")
    ws.write_base_config("{ b: 1 }", suffix="-OTHER")
    assert ws.read_org_config(org="o2") == "{ a: 1 }"
    assert (ws.org_dir / "o.jsonnet-OTHER").read_text() == "{ b: 1 }"
    with pytest.raises(ValueError, match="invalid config file suffix"):
        ws.org_config_file_for("o", suffix="/../x")


def test_clean_template_cache_and_export_follow_the_layout(tmp_path: Path) -> None:
    """Vendored copies of every organization are removed; otterdog.jsonnet, the override and every org config are
    exported as text files."""
    ws = workspace(tmp_path)
    ws.use_layout(WorkspaceLayout(format="jsonnet", orgs=("o2",), defaults_override={"github": {"exclude_teams": []}}))
    for org in ("o", "o2"):
        (ws.org_dir_for(org) / "vendor" / "template").mkdir(parents=True)
        ws.write_org_config(f"// {org}\n{{}}\n", org=org)
    ws.clean_template_cache()
    assert not (ws.org_dir / "vendor").exists() and not (ws.org_dir_for("o2") / "vendor").exists()
    out = tmp_path / "artifacts"
    ws.export_to(out)
    assert sorted(path.name for path in out.iterdir()) == [
        DEFAULTS_OVERRIDE_FILE,
        "o.jsonnet.txt",
        "o2.jsonnet.txt",
        "otterdog.jsonnet.txt",
    ]


@pytest.mark.parametrize(
    ("kwargs", "match"),
    [
        ({"format": "yaml"}, "format 'yaml'"),
        ({"config_dir": "../escape"}, "is not a directory name"),
        ({"config_dir": "."}, "is not a directory name"),
        ({"defaults_override": {"jsonnet": {"config_dir": "/abs"}}}, "defaults_override.jsonnet.config_dir"),
        ({"orgs": "o2"}, "list of organization entries"),
        ({"orgs": (3,)}, "neither a github_id nor a mapping"),
        ({"orgs": ({"github_id": "x", "token": "t"},)}, r"unknown key\(s\) \['token'\]"),
        ({"defaults_override": ["x"]}, "must be a mapping"),
    ],
)
def test_invalid_layouts_are_refused(kwargs: dict[str, object], match: str) -> None:
    """Unknown formats, directories leaving the workspace and badly typed entries are ValueErrors."""
    with pytest.raises(ValueError, match=match):
        WorkspaceLayout(**kwargs)  # type: ignore[arg-type]


def test_layout_lists_become_tuples_and_compare_by_value() -> None:
    """orgs given as a list are stored as a tuple; equal layouts compare equal (the engine switches on change)."""
    layout = WorkspaceLayout(orgs=["o2"])  # type: ignore[arg-type]
    assert layout.orgs == ("o2",) and layout == WorkspaceLayout(orgs=("o2",)) and not layout.is_default


def test_fake_workspace_records_without_disk_io() -> None:
    """FakeWorkspace keeps the real paths and layout logic, records every write in memory."""
    ws = FakeWorkspace()
    assert ws.org == FAKE_ORG and not ws.config_file.exists()
    ws.write_otterdog_json()
    ws.use_layout(WorkspaceLayout(format="jsonnet", defaults_override={"base_url": "x"}))
    assert ws.otterdog_json_writes == 2 and len(ws.documents) == 2
    assert ws.config_file.name == "otterdog.jsonnet" and ws.config_file in ws.files
    assert ws.root / "otterdog.json" not in ws.files and ws.defaults_override_file in ws.files
    ws.write_org_config("A")
    ws.write_base_config("B")
    assert ws.writes == ["A"] and ws.base_writes == ["B"] and ws.read_org_config() == "A"
    with pytest.raises(FileNotFoundError):
        ws.read_org_config(org="other")
    ws.clean_template_cache()
    ws.export_to(Path("/nonexistent/out"))
    assert ws.cleaned == 1 and ws.exports == [Path("/nonexistent/out")] and not ws.root.exists()
