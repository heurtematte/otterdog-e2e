"""Target instances bound to profiles: resolve_target_ref rules and messages, instance names, the team profile and the
env-driven literals of the profiles (saml_sso, capabilities, web_ui.probe_app_slug)."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

from otterdog_e2e import context, settings
from otterdog_e2e.context import E2EContext, E2EOptions
from otterdog_e2e.redact import Redactor
from otterdog_e2e.settings import (
    INSTANCE_NAME_RE,
    PROFILE_ENV,
    RESERVED_INSTANCE_NAMES,
    RESERVED_INSTANCE_SUFFIXES,
    HarnessSettings,
    TargetError,
    TargetRef,
    instance_name_problem,
    load_target,
    profile_names,
    resolve_target_ref,
    target_env_name,
)

PROJECT = Path(__file__).resolve().parents[2]
REPO_TARGETS = PROJECT / "targets"
PROFILES = ("free", "team", "enterprise")
ENV = {"E2E_ORG": "e2e-test-org", "E2E_ORG_ID": "424242", "E2E_ADMIN_LOGIN": "e2e-admin-bot"}


@pytest.fixture(autouse=True)
def redactor(monkeypatch: pytest.MonkeyPatch) -> Redactor:
    """A fresh Redactor used by settings (keeps the process-wide REDACTOR clean)."""
    fresh = Redactor()
    monkeypatch.setattr(settings, "REDACTOR", fresh)
    return fresh


@pytest.fixture
def harness(tmp_path: Path) -> HarnessSettings:
    """Settings whose targets dir holds copies of the repository's profiles."""
    targets = tmp_path / "project" / "targets"
    targets.mkdir(parents=True)
    for profile in PROFILES:
        shutil.copy(REPO_TARGETS / f"{profile}.yaml", targets / f"{profile}.yaml")
    root = tmp_path / "project"
    return HarnessSettings(root, tmp_path / "cache", root / "artifacts", "o/r", targets, root / "scenarios")


# --- resolve_target_ref ----------------------------------------------------------------------------------------------
def test_a_profile_name_is_the_instance_of_the_same_name(harness: HarnessSettings) -> None:
    """--target free: instance = profile = free (backward compatible); E2E_PROFILE naming the same profile is fine."""
    expected = TargetRef("free", "free", harness.targets_dir / "free.yaml")
    assert resolve_target_ref("free", harness, {}) == expected
    assert resolve_target_ref("free", harness, {PROFILE_ENV: "free"}) == expected
    target = load_target("team", harness, ENV)
    assert (target.name, target.profile, target.expected_plan) == ("team", "team", "team")


def test_a_path_is_its_own_profile(harness: HarnessSettings, tmp_path: Path) -> None:
    """A target file path: instance = profile = file stem, E2E_PROFILE is ignored; the instance is the stem even when
    the file's own ``name`` says otherwise."""
    data = yaml.safe_load((REPO_TARGETS / "free.yaml").read_text(encoding="utf-8"))
    data["name"] = "documented-name"
    custom = tmp_path / "elsewhere" / "acme-custom.yml"
    custom.parent.mkdir()
    custom.write_text(yaml.safe_dump(data), encoding="utf-8")
    ref = resolve_target_ref(str(custom), harness, {PROFILE_ENV: "team"})
    assert ref == TargetRef("acme-custom", "acme-custom", custom)
    target = load_target(str(custom), harness, ENV)
    assert (target.name, target.profile, target.source_path) == ("acme-custom", "acme-custom", custom)


def test_an_instance_uses_the_profile_of_e2e_profile(harness: HarnessSettings) -> None:
    """--target acme with E2E_PROFILE=team: Target.name is the instance, profile and file are the team profile's."""
    assert resolve_target_ref("acme", harness, {PROFILE_ENV: " team "}) == TargetRef(
        "acme", "team", harness.targets_dir / "team.yaml"
    )
    target = load_target("acme", harness, {**ENV, PROFILE_ENV: "team"})
    assert (target.name, target.profile, target.expected_plan) == ("acme", "team", "team")
    assert target.source_path == harness.targets_dir / "team.yaml"
    assert target.org == "e2e-test-org" and target.org_id == 424242


def test_an_instance_without_profile_explains_how_to_bind_it(harness: HarnessSettings) -> None:
    """No targets/<name>.yaml and no E2E_PROFILE: the message names setup, the env file and the profiles."""
    with pytest.raises(TargetError) as info:
        load_target("acme", harness, ENV)
    message = str(info.value)
    assert "otterdog-e2e setup --target acme" in message
    assert f"{PROFILE_ENV}=<profile> to ~/.config/otterdog-e2e/acme.env" in message
    assert "available: ['enterprise', 'free', 'team']" in message


@pytest.mark.parametrize("profile", ["gold", "free.yaml", "../targets/free", "targets/free.yaml", "Free"])
def test_e2e_profile_must_name_an_existing_profile(harness: HarnessSettings, profile: str) -> None:
    """E2E_PROFILE is a profile name of targets/ (never a path); anything else is refused with the list."""
    with pytest.raises(
        TargetError, match=re.escape(f"{PROFILE_ENV}={profile!r} of the instance acme names no profile")
    ):
        resolve_target_ref("acme", harness, {PROFILE_ENV: profile})


def test_a_profile_bound_to_another_profile_is_ambiguous(harness: HarnessSettings) -> None:
    """--target free with E2E_PROFILE=team: is it the profile free or an instance free of the team profile?"""
    with pytest.raises(TargetError, match="ambiguous") as info:
        resolve_target_ref("free", harness, {PROFILE_ENV: "team"})
    assert "~/.config/otterdog-e2e/free.env" in str(info.value) and "'team'" in str(info.value)


@pytest.mark.parametrize(
    ("name", "message"),
    [
        ("Acme", "invalid target name"),
        ("acme_org", "invalid instance name"),
        ("acme.org", "invalid instance name"),
        ("-acme", "invalid target name"),
        ("a" * 40, "invalid instance name"),
        ("acme-untrusted", "the suffix -untrusted is reserved"),
        ("acme-webui", "the suffix -webui is reserved"),
        ("lists", "'lists': the name is reserved"),
        ("acme org", "invalid target name"),
        ("a,b", "only accepted by otterdog-e2e run, pr, doctor and janitor"),
        ("@all", "only accepted by otterdog-e2e run, pr, doctor and janitor"),
    ],
)
def test_instance_names_are_ci_safe(harness: HarnessSettings, name: str, message: str) -> None:
    """Instances (no profile of that name) match INSTANCE_NAME_RE and end with no reserved suffix; a list of targets
    is refused with a hint (one session per target)."""
    with pytest.raises(TargetError, match=re.escape(message)):
        load_target(name, harness, {**ENV, PROFILE_ENV: "free"})


def test_instance_name_problem() -> None:
    """None for valid names; the reason otherwise (39 characters at most, reserved suffixes)."""
    assert INSTANCE_NAME_RE.pattern == "^[a-z0-9][a-z0-9-]{0,38}$"
    assert RESERVED_INSTANCE_SUFFIXES == ("-untrusted", "-webui")
    for valid in ("free", "acme", "a", "acme-2", "x" * 39, "webui", "untrusted-acme", "lists-2", "my-lists"):
        assert instance_name_problem(valid) is None, valid
    assert "e2e-acme-webui is the CI environment of the instance 'acme'" in str(instance_name_problem("acme-webui"))
    # ~/.config/otterdog-e2e/lists/ holds the target lists: an instance "lists" would write its App credentials there
    assert RESERVED_INSTANCE_NAMES == ("lists",)
    assert "~/.config/otterdog-e2e/lists/ holds the target lists" in str(instance_name_problem("lists"))
    for invalid in ("", "x" * 40, "Acme", "a.b", "a_b", "-a"):
        assert instance_name_problem(invalid), invalid


def test_a_profile_may_keep_a_name_that_is_no_instance_name(harness: HarnessSettings) -> None:
    """Profiles keep the wider target-name rule (dots, underscores): --target my_org loads targets/my_org.yaml."""
    shutil.copy(REPO_TARGETS / "free.yaml", harness.targets_dir / "my_org.yaml")
    assert resolve_target_ref("my_org", harness, {}).profile == "my_org"
    assert load_target("my_org", harness, ENV).name == "my_org"


def test_profile_names(harness: HarnessSettings) -> None:
    """Stems of targets/*.yaml and *.yml, sorted; other files and odd names are ignored; no targets dir: none."""
    (harness.targets_dir / "other.yml").write_text("x: 1\n", encoding="utf-8")
    (harness.targets_dir / "README.md").write_text("# not a profile\n", encoding="utf-8")
    (harness.targets_dir / "Bad Name.yaml").write_text("x: 1\n", encoding="utf-8")
    assert profile_names(harness) == ["enterprise", "free", "other", "team"]
    assert resolve_target_ref("other", harness, {}).path == harness.targets_dir / "other.yml"
    missing = HarnessSettings(
        harness.project_root, harness.cache_dir, harness.artifacts_root, "o/r", Path("/nope"), Path("/")
    )
    assert profile_names(missing) == []


def test_target_env_name_refuses_lists() -> None:
    """settings.target_env_name refuses lists with the hint; context.target_env_name delegates to it."""
    with pytest.raises(TargetError, match="only accepted by otterdog-e2e run, pr, doctor and janitor"):
        target_env_name("free,team")
    assert context.target_env_name("targets/team.yaml") == "team"
    assert context.target_env_name("acme") == "acme"
    with pytest.raises(TargetError, match="invalid target name"):
        context.target_env_name("Free Org")
    with pytest.raises(ValueError):  # TargetError is a ValueError: callers catching ValueError keep working
        context.target_env_name("@all")


def test_context_loads_the_instance_env_file_then_its_profile(
    harness: HarnessSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """E2EContext.load_target: ~/.config/otterdog-e2e/<instance>.env (E2E_PROFILE included) is loaded first, so an
    instance needs nothing but its env file."""
    home = tmp_path / "home"
    env_file = home / ".config" / "otterdog-e2e" / "acme.env"
    env_file.parent.mkdir(parents=True)
    lines = [f"{PROFILE_ENV}=enterprise", "E2E_ORG=acme-e2e", "E2E_ORG_ID=77", "E2E_ADMIN_LOGIN=acme-admin"]
    env_file.write_text("\n".join([*lines, "E2E_ADMIN_TOKEN=ghp_" + "a" * 36, ""]), encoding="utf-8")
    env_file.chmod(0o600)
    environ: dict[str, str] = {"HOME": str(home)}
    ctx = E2EContext.create(E2EOptions(target="acme"), environ=environ, settings=harness, make_dirs=False)
    target = ctx.load_target()
    assert (target.name, target.profile, target.org, target.org_id) == ("acme", "enterprise", "acme-e2e", 77)
    assert target.expected_plan == "enterprise" and ctx.identities["admin"].login == "acme-admin"
    assert environ[PROFILE_ENV] == "enterprise"  # the session's own environment


# --- the profiles ------------------------------------------------------------------------------------------------------
def _profile_tree(profile: str) -> dict[str, Any]:
    """Parsed targets/<profile>.yaml without the keys that legitimately differ between profiles."""
    data = yaml.safe_load((REPO_TARGETS / f"{profile}.yaml").read_text(encoding="utf-8"))
    assert data["name"] == profile
    data.pop("name"), data.pop("description"), data["github"].pop("expected_plan")
    return dict(data)


def test_the_profiles_differ_only_in_name_description_and_plan() -> None:
    """free, team and enterprise hold no org-specific value: everything else is identical (and env-driven)."""
    assert _profile_tree("team") == _profile_tree("free") == _profile_tree("enterprise")
    for profile in PROFILES:
        github = yaml.safe_load((REPO_TARGETS / f"{profile}.yaml").read_text(encoding="utf-8"))["github"]
        assert github["expected_plan"] == profile
        assert github["saml_sso"] == "${E2E_SAML_SSO:-false}"
        assert github["capabilities"] == {"add": "${E2E_CAPABILITIES_ADD:-}", "remove": "${E2E_CAPABILITIES_REMOVE:-}"}


@pytest.mark.parametrize("profile", PROFILES)
def test_profile_literals_come_from_the_instance(harness: HarnessSettings, profile: str) -> None:
    """saml_sso, the capability overrides and the probe App are per instance (E2E_SAML_SSO, E2E_CAPABILITIES_ADD,
    E2E_CAPABILITIES_REMOVE, E2E_WEB_PROBE_APP_SLUG); unset: false, none, none."""
    default = load_target(profile, harness, ENV)
    assert (default.saml_sso, default.capability_overrides, default.web_probe_app_slug) == (
        False,
        {"add": (), "remove": ()},
        None,
    )
    env = {
        **ENV,
        "E2E_SAML_SSO": "yes",
        "E2E_CAPABILITIES_ADD": "ghas_private",
        "E2E_CAPABILITIES_REMOVE": " larger_runners, , GHAS_PRIVATE",
        "E2E_WEB_PROBE_APP_SLUG": "e2e-probe-app",
    }
    target = load_target(profile, harness, env)
    assert target.saml_sso is True
    assert target.capability_overrides == {"add": ("ghas_private",), "remove": ("larger_runners", "ghas_private")}
    assert target.web_probe_app_slug == "e2e-probe-app"
    assert load_target(profile, harness, {**ENV, "E2E_SAML_SSO": "0"}).saml_sso is False


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"E2E_SAML_SSO": "maybe"}, "github.saml_sso: expected a boolean"),
        ({"E2E_CAPABILITIES_ADD": "warp_drive"}, "unknown capability 'warp_drive'"),
        ({"E2E_CAPABILITIES_ADD": "web_ui"}, "web_ui cannot be added"),
        ({"E2E_CAPABILITIES_REMOVE": "nope"}, "github.capabilities.remove: unknown capability"),
        ({"E2E_WEB_PROBE_APP_SLUG": "Probe App"}, "web_ui.probe_app_slug"),
        ({"E2E_WEB_PROBE_APP_SLUG": "e2e-app", "E2E_APP_SLUG": "e2e-app"}, "must not be the e2e GitHub App"),
    ],
)
def test_profile_literals_are_validated(harness: HarnessSettings, env: dict[str, str], message: str) -> None:
    """The env-driven values go through the same checks as literals."""
    with pytest.raises(TargetError, match=re.escape(message)):
        load_target("team", harness, {**ENV, **env})
