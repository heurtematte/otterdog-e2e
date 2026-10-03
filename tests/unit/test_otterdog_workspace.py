"""ConfigWorkspace, credentials_env and webapp_otterdog_json (SPEC 11.1; keys verified against otterdog/config.py)."""

from __future__ import annotations

import json
import stat
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.otterdog.workspace import (
    CREDENTIAL_ENV,
    ConfigWorkspace,
    credentials_env,
    webapp_otterdog_json,
)
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.settings import Identity, Target, WebappSpec
from otterdog_e2e.sut.template import TemplateRef, offline_template

TEMPLATE = TemplateRef(
    url="https://github.com/eclipse-csi/otterdog#examples/template/otterdog-defaults.libsonnet@" + "a" * 40,
    repo_name="otterdog",
    file="examples/template/otterdog-defaults.libsonnet",
    ref="a" * 40,
)


def make_target() -> Target:
    """Minimal Target for webapp_otterdog_json."""
    values: dict[str, Any] = dict.fromkeys(Target.__dataclass_fields__)
    values.update(
        name="free",
        org="e2e-test-org",
        admin_team="otterdog-admins",
        approval_team="project-leads",
        contributors_team="e2e-contributors",
        webapp=WebappSpec("relay", None, None, "v", "s", 1, 5000),
        source_path=Path("t.yaml"),
    )
    return Target(**values)


def test_credentials_env() -> None:
    """The env provider maps api_token/username/password/twofa_seed to E2E_OTTERDOG_* names."""
    assert CREDENTIAL_ENV == {
        "api_token": "E2E_OTTERDOG_API_TOKEN",
        "username": "E2E_OTTERDOG_USERNAME",
        "password": "E2E_OTTERDOG_PASSWORD",
        "twofa_seed": "E2E_OTTERDOG_TOTP_SEED",
    }
    assert credentials_env(Identity("admin", "bot", "tok-123456"))["E2E_OTTERDOG_API_TOKEN"] == "tok-123456"
    assert credentials_env(None)["E2E_OTTERDOG_API_TOKEN"] == "offline-dummy-token"
    assert credentials_env(None)["E2E_OTTERDOG_TOTP_SEED"] == "unset"


def test_write_otterdog_json(tmp_path: Path) -> None:
    """otterdog.json shape of SPEC 11.1 (defaults.base_url/jsonnet/github, one org with the env provider), 0600."""
    workspace = ConfigWorkspace(
        tmp_path / "ws", org="e2e-test-org", template=TEMPLATE, config_repo="e2e-t3c7z8a5-config"
    )
    path = workspace.write_otterdog_json()
    assert path == tmp_path / "ws" / "otterdog.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert json.loads(path.read_text()) == {
        "defaults": {
            "base_url": "https://otterdog.invalid",
            "jsonnet": {"base_template": TEMPLATE.url, "config_dir": "orgs"},
            "github": {"config_repo": "e2e-t3c7z8a5-config"},
        },
        "organizations": [
            {
                "name": "e2e-test-org",
                "github_id": "e2e-test-org",
                "config_repo": "e2e-t3c7z8a5-config",
                "credentials": {"provider": "env", **CREDENTIAL_ENV},
            }
        ],
    }
    custom = ConfigWorkspace(
        tmp_path / "ws2", org="o", template=TEMPLATE, config_repo=".otterdog", project="proj", base_url="http://x"
    )
    data = json.loads(custom.write_otterdog_json().read_text())
    assert data["defaults"]["base_url"] == "http://x" and data["organizations"][0]["name"] == "proj"


def test_org_config_files(tmp_path: Path) -> None:
    """Org config and -BASE files live in orgs/<org>/ (0600); read back verbatim."""
    workspace = ConfigWorkspace(tmp_path, org="e2e-test-org", template=offline_template(), config_repo=".otterdog")
    workspace.write_org_config("local x = 1;\n{}\n")
    workspace.write_base_config("{}\n")
    assert workspace.read_org_config() == "local x = 1;\n{}\n"
    assert workspace.org_config_file == tmp_path / "orgs" / "e2e-test-org" / "e2e-test-org.jsonnet"
    assert workspace.base_config_file.read_text() == "{}\n"
    assert stat.S_IMODE(workspace.org_config_file.stat().st_mode) == 0o600


def test_clean_template_cache(tmp_path: Path) -> None:
    """Removes orgs/templates (clones) and orgs/<org>/vendor, keeps the configs."""
    workspace = ConfigWorkspace(tmp_path, org="o", template=offline_template(), config_repo=".otterdog")
    workspace.write_org_config("{}")
    clone = tmp_path / "orgs" / "templates" / "eclipse-csi" / "otterdog" / "main"
    clone.mkdir(parents=True)
    (clone / "f").write_text("x")
    vendored = workspace.org_dir / "vendor" / "template"
    vendored.mkdir(parents=True)
    workspace.clean_template_cache()
    workspace.clean_template_cache()  # idempotent
    assert not (tmp_path / "orgs" / "templates").exists() and not (workspace.org_dir / "vendor").exists()
    assert workspace.org_config_file.is_file()


def test_export_to_copies_only_redacted_configs(tmp_path: Path) -> None:
    """otterdog.json and orgs/<org>/<org>.jsonnet* only, as text files, redacted (SPEC 5.7)."""
    secret = "e2e-export-secret-0123456789"
    REDACTOR.add(secret)
    workspace = ConfigWorkspace(tmp_path / "ws", org="o", template=offline_template(), config_repo=".otterdog")
    workspace.write_otterdog_json()
    workspace.write_org_config(f"{{ value: '{secret}' }}")
    workspace.write_base_config("{}")
    (workspace.org_dir / "vendor").mkdir()
    (workspace.org_dir / "vendor" / "x.libsonnet").write_text("{}")
    (workspace.root / ".cache").mkdir()
    out = tmp_path / "artifacts"
    workspace.export_to(out)
    assert sorted(path.name for path in out.iterdir()) == ["o.jsonnet-BASE.txt", "o.jsonnet.txt", "otterdog.json"]
    assert secret not in (out / "o.jsonnet.txt").read_text() and "***" in (out / "o.jsonnet.txt").read_text()


def test_webapp_otterdog_json() -> None:
    """Same defaults, no credentials; admin teams and an anchored approval pattern for the org entry."""
    data = webapp_otterdog_json(make_target(), TEMPLATE, config_repo="e2e-t3c7z8a5-config")
    assert data == {
        "defaults": {
            "base_url": "https://otterdog.invalid",
            "jsonnet": {"base_template": TEMPLATE.url, "config_dir": "orgs"},
            "github": {"config_repo": "e2e-t3c7z8a5-config"},
        },
        "organizations": [
            {
                "name": "e2e-test-org",
                "github_id": "e2e-test-org",
                "config_repo": "e2e-t3c7z8a5-config",
                "admin_teams": ["otterdog-admins"],
                "approval_teams": ["^project-leads$"],
            }
        ],
    }
    assert (
        webapp_otterdog_json(make_target(), TEMPLATE, config_repo="r", project="p")["organizations"][0]["name"] == "p"
    )


# --- files left by untrusted containers (ISO-01) -------------------------------------------------------------------
def test_read_untrusted_text_refuses_links_special_files_and_escapes(tmp_path: Path) -> None:
    """Regular files inside the root are read; links (never followed), FIFOs (without blocking), files below a
    directory that resolves outside the root and oversized files are refused; a missing file is None."""
    import os

    import pytest

    from otterdog_e2e.otterdog.workspace import read_untrusted_text
    from otterdog_e2e.safety import SafetyError

    root, outside = tmp_path / "ws", tmp_path / "host"
    root.mkdir()
    outside.mkdir()
    (outside / "secret").write_text("host secret")
    (root / "ok.json").write_text("[]")
    assert read_untrusted_text(root / "ok.json", within=root) == "[]"
    assert read_untrusted_text(root / "missing.json", within=root) is None
    (root / "link.json").symlink_to(outside / "secret")
    (root / "inner-link.json").symlink_to(root / "ok.json")
    os.mkfifo(root / "fifo.json")
    (root / "escape").symlink_to(outside)
    for name, message in [
        ("link.json", "symbolic link"),
        ("inner-link.json", "symbolic link"),
        ("fifo.json", "not a regular file"),
        ("escape/secret", "outside"),
    ]:
        with pytest.raises(SafetyError, match=message):
            read_untrusted_text(root / name, within=root)
    with pytest.raises(SafetyError, match="larger than 1 bytes"):
        read_untrusted_text(root / "ok.json", within=root, limit=1)


def test_write_private_text_replaces_planted_links(tmp_path: Path) -> None:
    """A link (or FIFO) at the destination is replaced by a regular 0600 file; the link target is untouched; with
    ``within`` a directory resolving outside the root is refused."""
    import os

    import pytest

    from otterdog_e2e.otterdog.workspace import write_private_text
    from otterdog_e2e.safety import SafetyError

    root, outside = tmp_path / "ws", tmp_path / "host"
    root.mkdir()
    outside.mkdir()
    (outside / "victim").write_text("keep me")
    (root / "out.json").symlink_to(outside / "victim")
    os.mkfifo(root / "fifo.json")
    for name in ("out.json", "fifo.json"):
        path = write_private_text(root / name, "new", within=root)
        assert not path.is_symlink() and path.read_text() == "new" and stat.S_IMODE(path.stat().st_mode) == 0o600
    assert (outside / "victim").read_text() == "keep me"
    (root / "escape").symlink_to(outside)
    with pytest.raises(SafetyError, match="outside"):
        write_private_text(root / "escape" / "victim", "x", within=root)
    assert (outside / "victim").read_text() == "keep me"


def test_neutralize_untrusted_tree(tmp_path: Path) -> None:
    """Links resolving outside the root (absolute, relative, chained, dangling) and FIFOs are removed, links inside
    are kept, link targets are never entered, and a directory the container made unreadable is opened again."""
    import os

    from otterdog_e2e.otterdog.workspace import neutralize_untrusted_tree

    root, outside = tmp_path / "ws", tmp_path / "host"
    (root / "orgs" / "o").mkdir(parents=True)
    (outside / "templates").mkdir(parents=True)
    (root / "orgs" / "o" / "o.jsonnet").write_text("{}")
    (root / "abs").symlink_to(outside / "templates")
    (root / "orgs" / "rel").symlink_to(os.path.join("..", "..", "host"))
    (root / "chain").symlink_to("abs")
    (root / "dangling").symlink_to(outside / "nothing-yet")
    (root / "slash-ws").symlink_to("/ws/cwd/x")  # a container path: meaningless (or worse) on the host
    (root / "inner").symlink_to(os.path.join("orgs", "o", "o.jsonnet"))
    os.mkfifo(root / "orgs" / "o" / "pipe")
    locked = root / "locked"
    locked.mkdir()
    (locked / "deep").symlink_to(outside)
    locked.chmod(0)
    removed = neutralize_untrusted_tree(root)
    assert removed == sorted(["abs", "chain", "dangling", "slash-ws", "orgs/rel", "orgs/o/pipe", "locked/deep"])
    assert (root / "inner").is_symlink() and (root / "orgs" / "o" / "o.jsonnet").read_text() == "{}"
    assert (outside / "templates").is_dir()
    assert neutralize_untrusted_tree(root) == [] and neutralize_untrusted_tree(tmp_path / "missing") == []


@pytest.mark.parametrize("reverse", [False, True], ids=["scandir-order", "reversed-order"])
def test_neutralize_untrusted_tree_does_not_depend_on_the_listing_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reverse: bool
) -> None:
    """A link chained through another outside link is removed whatever the directory listing order (the order
    differs between filesystems: chain was kept on a GitHub runner when abs came first)."""
    import os

    from otterdog_e2e.otterdog import workspace as workspace_module

    root, outside = tmp_path / "ws", tmp_path / "host"
    root.mkdir()
    outside.mkdir()
    (root / "abs").symlink_to(outside)
    (root / "chain").symlink_to("abs")
    (root / "chain2").symlink_to("chain")
    real_scandir = os.scandir

    def ordered(path: str) -> list[os.DirEntry[str]]:
        """Entries sorted by name, optionally reversed."""
        return sorted(real_scandir(path), key=lambda entry: entry.name, reverse=reverse)

    monkeypatch.setattr(workspace_module.os, "scandir", ordered)
    assert workspace_module.neutralize_untrusted_tree(root) == ["abs", "chain", "chain2"]


def test_workspace_reads_and_cleanups_stay_inside_the_root(tmp_path: Path) -> None:
    """read_org_config refuses a planted link; clean_template_cache refuses to delete through a parent link."""
    import pytest

    from otterdog_e2e.safety import SafetyError

    workspace = ConfigWorkspace(tmp_path / "ws", org="o", template=offline_template(), config_repo=".otterdog")
    workspace.write_otterdog_json()
    outside = tmp_path / "host"
    (outside / "templates").mkdir(parents=True)
    (outside / "o").mkdir()
    (outside / "o" / "o.jsonnet").write_text("host file")
    (workspace.root / "orgs").symlink_to(outside)
    with pytest.raises(SafetyError, match="outside"):
        workspace.write_base_config("{}", org="new-org")
    assert not (outside / "new-org").exists()  # refused before any directory is created through the link
    with pytest.raises(SafetyError, match="outside"):
        workspace.read_org_config()
    with pytest.raises(SafetyError, match="outside"):
        workspace.clean_template_cache()
    with pytest.raises(SafetyError, match="outside"):
        workspace.write_org_config("{}")
    assert (outside / "templates").is_dir() and (outside / "o" / "o.jsonnet").read_text() == "host file"
    out = tmp_path / "out"
    workspace.export_to(out)
    assert not (out / "o.jsonnet.txt").exists()
    with pytest.raises(FileNotFoundError):
        ConfigWorkspace(tmp_path / "ws2", org="o", template=offline_template(), config_repo=".x").read_org_config()
