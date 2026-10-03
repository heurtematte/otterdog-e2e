"""WP-A: target files, identities and App credentials (SPEC 6.2)."""

from __future__ import annotations

import dataclasses
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from otterdog_e2e import settings
from otterdog_e2e.redact import Redactor
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import (
    HarnessSettings,
    Identity,
    Target,
    TargetError,
    load_target,
    resolve_app_credentials,
    resolve_identities,
)

PROJECT = Path(__file__).resolve().parents[2]
REPO_TARGETS = PROJECT / "targets"
ORG, ORG_ID, ADMIN = "e2e-test-org", 424242, "e2e-admin-bot"
ENV = {"E2E_ORG": ORG, "E2E_ORG_ID": str(ORG_ID), "E2E_ADMIN_LOGIN": ADMIN}
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAwpaFakeKeyLine0123456789\nabcdefghijklmnopqrstuvwxyz012345\n-----END RSA PRIVATE KEY-----"


@pytest.fixture
def redactor(monkeypatch: pytest.MonkeyPatch) -> Redactor:
    """A fresh Redactor used by settings (keeps the process-wide REDACTOR clean)."""
    fresh = Redactor()
    monkeypatch.setattr(settings, "REDACTOR", fresh)
    return fresh


@pytest.fixture
def harness(tmp_path: Path) -> HarnessSettings:
    """Settings whose targets dir holds a copy of the repository's free.yaml."""
    targets = tmp_path / "targets"
    targets.mkdir()
    shutil.copy(REPO_TARGETS / "free.yaml", targets / "free.yaml")
    return HarnessSettings(tmp_path, tmp_path / "cache", tmp_path / "artifacts", "o/r", targets, tmp_path / "scenarios")


def setter(dotted: str, value: Any) -> Callable[[dict[str, Any]], None]:
    """Mutation setting ``dotted`` (a.b.c) of a parsed target to ``value``."""

    def mutate(data: dict[str, Any]) -> None:
        """Apply the change."""
        node = data
        *parents, last = dotted.split(".")
        for key in parents:
            node = node.setdefault(key, {})
        node[last] = value

    return mutate


def variant(harness: HarnessSettings, mutate: Callable[[dict[str, Any]], None] | None, name: str = "variant") -> str:
    """Write a modified copy of free.yaml as targets/<name>.yaml and return its name."""
    data = yaml.safe_load((REPO_TARGETS / "free.yaml").read_text(encoding="utf-8"))
    data["name"] = name
    if mutate is not None:
        mutate(data)
    (harness.targets_dir / f"{name}.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return name


def free_target(harness: HarnessSettings, **env: str) -> Target:
    """free.yaml loaded with ENV plus ``env``."""
    return load_target("free", harness, {**ENV, **env})


# --- load_target ----------------------------------------------------------------------------------------------------
def test_load_free_target_defaults(harness: HarnessSettings) -> None:
    """Every default of SPEC 6.2 with only the required variables set."""
    target = free_target(harness)
    assert (target.name, target.description) == ("free", "Dedicated GitHub Free test organization")
    assert (target.org, target.org_id, target.allowed_org_ids) == (ORG, ORG_ID, (ORG_ID,))
    assert (target.expected_plan, target.marker) == ("free", "[otterdog-e2e]")
    assert target.capability_overrides == {"add": (), "remove": ()}
    assert (target.configs_repo, target.org_config_repo, target.defaults_repo) == (
        "otterdog-e2e-configs",
        "auto",
        "otterdog-e2e-defaults",
    )
    assert (target.template_mode, target.template_url) == ("auto", None)
    assert list(target.identities) == ["admin", "oracle", "author", "approver", "outsider", "config_reader"]
    assert target.identities["admin"] == settings.IdentitySpec("admin", ADMIN, "E2E_ADMIN_TOKEN")
    assert target.identities["author"] == settings.IdentitySpec("author", None, "E2E_AUTHOR_TOKEN")
    assert target.identities["config_reader"].token_env == "E2E_CONFIG_READ_TOKEN"
    assert target.app == settings.AppSpec(
        "E2E_APP_ID", "E2E_APP_PRIVATE_KEY", "E2E_APP_PRIVATE_KEY_FILE", "E2E_APP_WEBHOOK_SECRET", None
    )
    assert (target.admin_team, target.approval_team, target.contributors_team) == (
        "otterdog-admins",
        "project-leads",
        "e2e-contributors",
    )
    assert target.webapp == settings.WebappSpec(
        "relay", None, None, "e2e/otterdog-validate", "e2e/otterdog-sync", 1, 5000
    )
    assert (target.fixture_repos, target.extra_protected_repos) == (("otterdog-e2e-fixture-a",), ())
    assert target.baseline_settings == {}
    assert target.source_path == harness.targets_dir / "free.yaml"


def test_load_target_environment_values(harness: HarnessSettings) -> None:
    """${VAR:-default} values come from the environment and are typed/validated."""
    target = free_target(
        harness,
        E2E_ALLOWED_ORG_IDS="77, 424242,88",
        E2E_ORG_CONFIG_REPO=".otterdog",
        E2E_TRANSPORT="external",
        E2E_EXTERNAL_URL="http://127.0.0.1:5000",
        E2E_EXTERNAL_INIT_URL="http://127.0.0.1:5000/internal/init",
        E2E_WEBAPP_WORKERS="2",
        E2E_WEBAPP_PORT="5050",
        E2E_TEMPLATE_MODE="url",
        E2E_TEMPLATE_URL="https://github.com/o/r#otterdog-defaults.libsonnet@" + "a" * 40,
        E2E_APP_SLUG="otterdog-e2e-app",
        E2E_AUTHOR_LOGIN="e2e-author-bot",
        E2E_ADMIN_TEAM="admins",
        E2E_VALIDATION_CONTEXT="ci/validate",
    )
    assert target.allowed_org_ids == (ORG_ID, 77, 88)
    assert target.org_config_repo == ".otterdog"
    assert target.webapp.transport == "external"
    assert target.webapp.external_url == "http://127.0.0.1:5000"
    assert target.webapp.external_init_url == "http://127.0.0.1:5000/internal/init"
    assert (target.webapp.workers, target.webapp.port, target.webapp.validation_context) == (2, 5050, "ci/validate")
    assert (target.template_mode, target.template_url) == (
        "url",
        "https://github.com/o/r#otterdog-defaults.libsonnet@" + "a" * 40,
    )
    assert target.app is not None and target.app.slug == "otterdog-e2e-app"
    assert target.identities["author"].login == "e2e-author-bot"
    assert target.admin_team == "admins"


def test_load_target_capability_overrides_and_id_forms(harness: HarnessSettings) -> None:
    """Overrides accept lists or comma strings (normalized lower case); ids accept YAML ints and lists."""

    def mutate(data: dict[str, Any]) -> None:
        """Set overrides and literal ids."""
        data["github"]["capabilities"] = {"add": ["GHAS_PRIVATE"], "remove": "larger_runners, private_pages"}
        data["github"]["org_id"] = ORG_ID
        data["github"]["allowed_org_ids"] = [1, "2", ORG_ID]

    target = load_target(variant(harness, mutate), harness, ENV)
    assert target.capability_overrides == {"add": ("ghas_private",), "remove": ("larger_runners", "private_pages")}
    assert target.allowed_org_ids == (ORG_ID, 1, 2)
    target = load_target(variant(harness, setter("github.allowed_org_ids", 9), "single"), harness, ENV)
    assert target.allowed_org_ids == (ORG_ID, 9)


def test_load_target_minimal_file(harness: HarnessSettings) -> None:
    """Only github.{org, org_id, expected_plan} and the admin identity are required."""
    minimal = {
        "github": {"org": "${E2E_ORG}", "org_id": "${E2E_ORG_ID}", "expected_plan": "team"},
        "identities": {"admin": {"login": "${E2E_ADMIN_LOGIN}", "token_env": "E2E_ADMIN_TOKEN"}},
    }
    (harness.targets_dir / "mini.yaml").write_text(yaml.safe_dump(minimal), encoding="utf-8")
    target = load_target("mini", harness, ENV)
    assert (target.name, target.description, target.expected_plan, target.marker) == (
        "mini",
        "",
        "team",
        "[otterdog-e2e]",
    )
    assert target.app is None
    assert list(target.identities) == ["admin"]
    assert target.fixture_repos == ()
    assert target.webapp.port == 5000


def test_load_target_by_path(harness: HarnessSettings, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Absolute paths and project-relative paths are accepted; the name comes from the file."""
    assert load_target(str(harness.targets_dir / "free.yaml"), harness, ENV).name == "free"
    monkeypatch.chdir(tmp_path.parent)
    assert load_target("targets/free.yaml", harness, ENV).source_path == harness.targets_dir / "free.yaml"


def test_load_target_defaults_to_os_environ(harness: HarnessSettings, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without environ, os.environ is used."""
    for key, value in ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("E2E_WEBAPP_PORT", "6000")
    assert load_target("free", harness).webapp.port == 6000


def test_load_target_refuses_production_orgs(harness: HarnessSettings) -> None:
    """A target naming a denylisted org is a SafetyError, not a mere TargetError."""
    with pytest.raises(SafetyError, match="denylist"):
        free_target(harness, E2E_ORG="Eclipse-JDT")


def test_load_target_missing_and_invalid_names(harness: HarnessSettings) -> None:
    """Missing targets list the available ones; odd names are refused."""
    with pytest.raises(TargetError, match=re.escape("available: ['free']")):
        load_target("team", harness, ENV)
    with pytest.raises(TargetError, match="invalid target name"):
        load_target("Free Org", harness, ENV)


def test_load_target_unreadable_yaml(harness: HarnessSettings) -> None:
    """YAML syntax errors and non-mapping documents are TargetErrors."""
    (harness.targets_dir / "broken.yaml").write_text("github: {org: ${E2E_ORG}}\n", encoding="utf-8")
    with pytest.raises(TargetError, match="cannot read target file"):
        load_target("broken", harness, ENV)
    (harness.targets_dir / "list.yaml").write_text("- a\n- b\n", encoding="utf-8")
    with pytest.raises(TargetError, match="expected a mapping at the top level"):
        load_target("list", harness, ENV)


INVALID_CASES: list[tuple[str, Callable[[dict[str, Any]], None] | None, dict[str, str], str]] = [
    ("missing org id", None, {"E2E_ORG_ID": ""}, "github.org_id is required"),
    ("non numeric org id", None, {"E2E_ORG_ID": "12a"}, "not a non-negative integer"),
    ("bad allowed id", None, {"E2E_ALLOWED_ORG_IDS": "1,x"}, "not a positive organization id"),
    ("zero allowed id", None, {"E2E_ALLOWED_ORG_IDS": "0"}, "not a positive organization id"),
    ("bad org login", None, {"E2E_ORG": "bad/org"}, "organization login"),
    ("missing org", None, {"E2E_ORG": ""}, "github.org is required"),
    ("unknown plan", setter("github.expected_plan", "pro"), {}, "is not one of free, team, enterprise"),
    ("short marker", setter("github.marker", "abc"), {}, "too short"),
    ("unknown capability", setter("github.capabilities", {"add": ["warp_drive"]}), {}, "unknown capability"),
    ("unknown capability key", setter("github.capabilities", {"enable": []}), {}, "unknown key(s) enable"),
    ("team not a slug", None, {"E2E_APPROVAL_TEAM": "Project Leads"}, "team name"),
    ("teams not distinct", None, {"E2E_APPROVAL_TEAM": "otterdog-admins"}, "must be distinct"),
    ("unknown top-level key", setter("extra", 1), {}, "unknown key(s) extra"),
    ("unknown github key", setter("github.orgg", "x"), {}, "unknown key(s) orgg"),
    ("unknown identity role", setter("identities.reviewer", {"login": "x"}), {}, "unknown key(s) reviewer"),
    ("missing admin login", None, {"E2E_ADMIN_LOGIN": ""}, "identities.admin needs a login"),
    ("bad identity login", None, {"E2E_AUTHOR_LOGIN": "bad login"}, "GitHub login"),
    (
        "token env not secret-like",
        setter("identities.author", {"login": "a", "token_env": "MY_AUTHOR_PAT"}),
        {},
        "must end with one of",
    ),
    ("baseline description", setter("baseline.settings", {"description": "x"}), {}, "come from the live organization"),
    ("baseline not mapping", setter("baseline.settings", ["x"]), {}, "expected a mapping of org settings"),
    ("run-like fixture", setter("fixtures.repos", ["e2e-t3c7z8a5-fixture"]), {}, "looks like a run-prefixed name"),
    ("run-like config repo", None, {"E2E_ORG_CONFIG_REPO": "e2e-t3c7z8a5-config"}, "looks like a run-prefixed name"),
    ("bad repo name", None, {"E2E_CONFIGS_REPO": "bad name"}, "repository name"),
    ("dot repo name", None, {"E2E_DEFAULTS_REPO": ".."}, "repository name"),
    ("external without url", None, {"E2E_TRANSPORT": "external"}, "external_url is required"),
    ("unknown transport", None, {"E2E_TRANSPORT": "pigeon"}, "is not one of relay, external, none"),
    ("non http external url", None, {"E2E_EXTERNAL_URL": "ftp://x"}, "is not an http(s) URL"),
    ("port range", None, {"E2E_WEBAPP_PORT": "99999"}, "must be in [1, 65535]"),
    ("workers not int", None, {"E2E_WEBAPP_WORKERS": "two"}, "not a non-negative integer"),
    ("same contexts", None, {"E2E_SYNC_CONTEXT": "e2e/otterdog-validate"}, "must differ"),
    ("url mode without url", None, {"E2E_TEMPLATE_MODE": "url"}, "required when the template mode is 'url'"),
    ("unknown template mode", None, {"E2E_TEMPLATE_MODE": "git"}, "is not one of auto, upstream, publish, url"),
    ("http template url", None, {"E2E_TEMPLATE_URL": "http://x/y"}, "must be an https://"),
    ("bad app slug", None, {"E2E_APP_SLUG": "My App"}, "GitHub App slug"),
    (
        "app without key",
        setter("app", {"id_env": "E2E_APP_ID", "webhook_secret_env": "E2E_APP_WEBHOOK_SECRET"}),
        {},
        "private_key_env or private_key_file_env is required",
    ),
    ("github not mapping", setter("github", ["x"]), {}, "github: expected a mapping"),
    ("string expected", setter("description", ["x"]), {}, "description: expected a string"),
    ("bad target name", setter("name", "Bad Name"), {}, "target name"),
    ("malformed reference", setter("description", "${E2E_ORG"), {}, "malformed variable reference"),
]


@pytest.mark.parametrize(
    ("mutate", "env", "message"), [case[1:] for case in INVALID_CASES], ids=[c[0] for c in INVALID_CASES]
)
def test_load_target_rejects_invalid_targets(
    harness: HarnessSettings, mutate: Callable[[dict[str, Any]], None] | None, env: dict[str, str], message: str
) -> None:
    """Strict schema: wrong types, unknown keys, unsafe names and inconsistent values are TargetErrors."""
    name = variant(harness, mutate)
    with pytest.raises(TargetError, match=re.escape(message)) as info:
        load_target(name, harness, {**ENV, **env})
    assert str(harness.targets_dir / f"{name}.yaml") in str(info.value)


@pytest.mark.parametrize(("name", "plan"), [("free", "free"), ("enterprise", "enterprise")])
def test_repository_target_files(name: str, plan: str) -> None:
    """targets/free.yaml and targets/enterprise.yaml are valid SPEC 6.2 targets."""
    harness = HarnessSettings(PROJECT, PROJECT / ".cache-unused", PROJECT / "artifacts", "o/r", REPO_TARGETS, PROJECT)
    target = load_target(name, harness, ENV)
    assert (target.name, target.expected_plan, target.marker) == (name, plan, "[otterdog-e2e]")
    assert target.capability_overrides == {"add": (), "remove": ()}
    assert set(target.identities) == {"admin", "oracle", "author", "approver", "outsider", "config_reader"}
    assert target.app is not None and target.app.private_key_file_env == "E2E_APP_PRIVATE_KEY_FILE"
    assert target.webapp.transport == "relay"
    assert target.fixture_repos == ("otterdog-e2e-fixture-a",)


def test_enterprise_target_documents_trial_overrides() -> None:
    """The enterprise target explains the GHEC trial overrides (GH-08)."""
    text = (REPO_TARGETS / "enterprise.yaml").read_text(encoding="utf-8")
    assert "remove: [larger_runners]" in text and "ghas_private" in text


# --- identities -----------------------------------------------------------------------------------------------------
def test_resolve_identities_oracle_falls_back_to_admin(harness: HarnessSettings, redactor: Redactor) -> None:
    """Only the admin token: oracle = admin, optional identities omitted, tokens registered."""
    target = free_target(harness)
    identities = resolve_identities(target, {"E2E_ADMIN_TOKEN": " wpa-admin-tok-1 \n"})
    assert list(identities) == ["admin", "oracle"]
    assert identities["admin"] == Identity("admin", ADMIN, "wpa-admin-tok-1")
    assert identities["oracle"] == Identity("oracle", ADMIN, "wpa-admin-tok-1")
    assert redactor("x wpa-admin-tok-1 y") == "x *** y"


def test_resolve_identities_all_roles(harness: HarnessSettings, redactor: Redactor) -> None:
    """Every identity whose token is set, in role order, with its declared login (or None)."""
    target = free_target(harness, E2E_AUTHOR_LOGIN="e2e-author-bot", E2E_OUTSIDER_LOGIN="e2e-outsider-bot")
    environ = {
        "E2E_ADMIN_TOKEN": "wpa-admin-tok-1",
        "E2E_ORACLE_TOKEN": "wpa-oracle-tok-2",
        "E2E_AUTHOR_TOKEN": "wpa-author-tok-3",
        "E2E_APPROVER_TOKEN": "wpa-approver-tok-4",
        "E2E_OUTSIDER_TOKEN": "wpa-outsider-tok-5",
        "E2E_CONFIG_READ_TOKEN": "wpa-reader-tok-6",
    }
    identities = resolve_identities(target, environ)
    assert list(identities) == ["admin", "oracle", "author", "approver", "outsider", "config_reader"]
    assert identities["oracle"] == Identity("oracle", None, "wpa-oracle-tok-2")
    assert identities["author"].login == "e2e-author-bot"
    assert identities["approver"].login is None
    assert redactor(" ".join(environ.values())) == " ".join(["***"] * 6)


def test_resolve_identities_requires_admin_token(harness: HarnessSettings, redactor: Redactor) -> None:
    """A live session cannot run without the admin token."""
    with pytest.raises(TargetError, match="E2E_ADMIN_TOKEN"):
        resolve_identities(free_target(harness), {"E2E_AUTHOR_TOKEN": "wpa-author-tok-3", "E2E_ADMIN_TOKEN": " "})


def test_resolve_identities_refuses_shared_tokens(harness: HarnessSettings, redactor: Redactor) -> None:
    """One machine account per role; only oracle == admin may share a token."""
    target = free_target(harness)
    shared = {
        "E2E_ADMIN_TOKEN": "wpa-admin-tok-1",
        "E2E_AUTHOR_TOKEN": "same-tok-77",
        "E2E_APPROVER_TOKEN": "same-tok-77",
    }
    with pytest.raises(TargetError, match="approver, author share one token"):
        resolve_identities(target, shared)
    with pytest.raises(TargetError, match="admin, author, oracle share one token"):
        resolve_identities(target, {"E2E_ADMIN_TOKEN": "wpa-admin-tok-1", "E2E_AUTHOR_TOKEN": "wpa-admin-tok-1"})
    explicit = resolve_identities(target, {"E2E_ADMIN_TOKEN": "wpa-admin-tok-1", "E2E_ORACLE_TOKEN": "wpa-admin-tok-1"})
    assert explicit["oracle"].token == explicit["admin"].token


# --- App credentials ------------------------------------------------------------------------------------------------
APP_ENV = {"E2E_APP_ID": "123456", "E2E_APP_WEBHOOK_SECRET": "wpa-hook-secret-1"}


def test_app_credentials_not_configured(harness: HarnessSettings, redactor: Redactor) -> None:
    """No app section or no App variable at all -> None."""
    target = free_target(harness)
    assert resolve_app_credentials(target, {}) is None
    assert resolve_app_credentials(dataclasses.replace(target, app=None), APP_ENV) is None


def test_app_credentials_partial_configuration(harness: HarnessSettings, redactor: Redactor) -> None:
    """A partially configured App names every missing variable."""
    with pytest.raises(TargetError, match="E2E_APP_PRIVATE_KEY or E2E_APP_PRIVATE_KEY_FILE, E2E_APP_WEBHOOK_SECRET"):
        resolve_app_credentials(free_target(harness), {"E2E_APP_ID": "1"})
    with pytest.raises(TargetError, match="missing E2E_APP_ID"):
        resolve_app_credentials(free_target(harness), {"E2E_APP_PRIVATE_KEY": PEM, "E2E_APP_WEBHOOK_SECRET": "s3cret"})


def test_app_credentials_inline_key_with_escaped_newlines(harness: HarnessSettings, redactor: Redactor) -> None:
    """CI secrets with literal \\n become a real PEM; key and secret are registered."""
    environ = {**APP_ENV, "E2E_APP_PRIVATE_KEY": PEM.replace("\n", "\\n")}
    creds = resolve_app_credentials(free_target(harness, E2E_APP_SLUG="my-app"), environ)
    assert creds is not None
    assert (creds.app_id, creds.slug, creds.webhook_secret) == ("123456", "my-app", "wpa-hook-secret-1")
    assert creds.private_key_pem == PEM + "\n"
    assert redactor("MIIEowIBAAKCAQEAwpaFakeKeyLine0123456789 wpa-hook-secret-1") == "*** ***"
    assert redactor(PEM.replace("\n", "\\n")) == "***"


def test_app_credentials_key_file(harness: HarnessSettings, redactor: Redactor, tmp_path: Path) -> None:
    """The key may come from a file ('~' expands to HOME of the environment)."""
    key_file = tmp_path / "home" / "app.pem"
    key_file.parent.mkdir()
    key_file.write_text(PEM + "\n", encoding="utf-8")
    key_file.chmod(0o600)
    environ = {**APP_ENV, "HOME": str(tmp_path / "home"), "E2E_APP_PRIVATE_KEY_FILE": "~/app.pem"}
    creds = resolve_app_credentials(free_target(harness), environ)
    assert creds is not None and creds.private_key_pem == PEM + "\n"


def test_app_credentials_bad_key_material(harness: HarnessSettings, redactor: Redactor, tmp_path: Path) -> None:
    """Unreadable or non-PEM keys fail without echoing the content; App ids are numeric."""
    target = free_target(harness)
    with pytest.raises(TargetError, match="cannot read the App private key file") as info:
        resolve_app_credentials(target, {**APP_ENV, "E2E_APP_PRIVATE_KEY_FILE": str(tmp_path / "missing.pem")})
    assert "E2E_APP_PRIVATE_KEY_FILE" in str(info.value)
    with pytest.raises(TargetError, match="not a PEM private key") as info:
        resolve_app_credentials(target, {**APP_ENV, "E2E_APP_PRIVATE_KEY": "not-a-key-wpa-secretish"})
    assert "not-a-key-wpa-secretish" not in str(info.value)
    with pytest.raises(TargetError, match="must be numeric"):
        resolve_app_credentials(target, {**APP_ENV, "E2E_APP_ID": "my-app", "E2E_APP_PRIVATE_KEY": PEM})
