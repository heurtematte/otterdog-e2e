"""Web-UI settings of a target (settings.py): admin web credential names, github.saml_sso, web_ui.probe_app_slug,
the derived web_ui capability, and the resolution of the admin bot's web credentials (TOTP seed included)."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from otterdog_e2e import settings
from otterdog_e2e.capabilities import Cap, apply_overrides, from_plan, with_capabilities
from otterdog_e2e.redact import Redactor
from otterdog_e2e.settings import (
    DEFAULT_WEB_ENV,
    HarnessSettings,
    IdentitySpec,
    TargetError,
    WebCredentialsError,
    load_target,
    normalize_totp_seed,
    resolve_web_credentials,
    web_credential_env_names,
)

PROJECT = Path(__file__).resolve().parents[2]
ENV = {"E2E_ORG": "e2e-test-org", "E2E_ORG_ID": "424242", "E2E_ADMIN_LOGIN": "e2e-admin-bot"}
SEED = "JBSWY3DPEHPK3PXP"  # base32 of "Hello!\xde\xad\xbe\xef"


@pytest.fixture
def redactor(monkeypatch: pytest.MonkeyPatch) -> Redactor:
    """A fresh Redactor used by settings."""
    fresh = Redactor()
    monkeypatch.setattr(settings, "REDACTOR", fresh)
    return fresh


@pytest.fixture
def harness(tmp_path: Path) -> HarnessSettings:
    """Settings whose targets dir holds the repository's target files."""
    targets = tmp_path / "targets"
    targets.mkdir()
    for name in ("free", "enterprise"):
        shutil.copy(PROJECT / "targets" / f"{name}.yaml", targets / f"{name}.yaml")
    return HarnessSettings(tmp_path, tmp_path / "cache", tmp_path / "artifacts", "o/r", targets, tmp_path / "scenarios")


def variant(harness: HarnessSettings, mutate: Callable[[dict[str, Any]], None]) -> str:
    """A modified copy of free.yaml (targets/variant.yaml)."""
    data = yaml.safe_load((PROJECT / "targets" / "free.yaml").read_text(encoding="utf-8"))
    data["name"] = "variant"
    mutate(data)
    (harness.targets_dir / "variant.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return "variant"


def test_repository_targets_have_no_web_setup_by_default(harness: HarnessSettings) -> None:
    """free/enterprise: SAML SSO off, no probe App, default web credential variable names."""
    for name in ("free", "enterprise"):
        target = load_target(name, harness, ENV)
        assert target.saml_sso is False and target.web_probe_app_slug is None
        assert web_credential_env_names(target) == {
            "username_env": "E2E_ADMIN_USERNAME",
            "password_env": "E2E_ADMIN_PASSWORD",
            "totp_seed_env": "E2E_ADMIN_TOTP_SEED",
        }


def test_declared_web_credential_names(harness: HarnessSettings) -> None:
    """identities.admin may name its web variables (secret suffixes enforced)."""

    def declare(data: dict[str, Any]) -> None:
        """Declare custom names."""
        data["identities"]["admin"].update(
            {"username_env": "BOT_LOGIN_NAME", "password_env": "BOT_WEB_PASSWORD", "totp_seed_env": "BOT_TOTP_SEED"}
        )

    target = load_target(variant(harness, declare), harness, ENV)
    assert web_credential_env_names(target) == {
        "username_env": "BOT_LOGIN_NAME",
        "password_env": "BOT_WEB_PASSWORD",
        "totp_seed_env": "BOT_TOTP_SEED",
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda d: d["identities"]["author"].update({"password_env": "X_PASSWORD"}), "only supported for the admin"),
        (lambda d: d["identities"]["admin"].update({"password_env": "BOT_PASS"}), "must end with _PASSWORD"),
        (lambda d: d["identities"]["admin"].update({"totp_seed_env": "BOT_SEED"}), "must end with _TOTP_SEED"),
        (lambda d: d["identities"]["admin"].update({"username_env": "bad name"}), "environment variable name"),
        (lambda d: d["github"].update({"saml_sso": "maybe"}), "expected a boolean"),
        (lambda d: d["github"].update({"capabilities": {"add": ["web_ui"], "remove": []}}), "cannot be added"),
        (lambda d: d.update({"web_ui": {"probe_app_slug": "Not A Slug"}}), "GitHub App slug"),
        (lambda d: d.update({"web_ui": {"unknown": 1}}), "unknown key"),
    ],
)
def test_invalid_web_settings(harness: HarnessSettings, mutate: Callable[[dict[str, Any]], None], message: str) -> None:
    """Misplaced or unsafe web settings are refused with the offending key."""
    with pytest.raises(TargetError, match=message):
        load_target(variant(harness, mutate), harness, ENV)


def test_saml_sso_and_probe_app(harness: HarnessSettings) -> None:
    """github.saml_sso accepts YAML and text booleans; the probe App must not be the e2e App."""

    def enable(data: dict[str, Any]) -> None:
        """SSO on (text), a probe App."""
        data["github"]["saml_sso"] = "yes"
        data["web_ui"] = {"probe_app_slug": "e2e-probe-app"}

    target = load_target(variant(harness, enable), harness, ENV)
    assert target.saml_sso is True and target.web_probe_app_slug == "e2e-probe-app"
    with pytest.raises(TargetError, match="must not be the e2e GitHub App"):
        load_target(variant(harness, enable), harness, {**ENV, "E2E_APP_SLUG": "e2e-probe-app"})


def test_web_ui_capability_is_never_added_by_overrides() -> None:
    """apply_overrides ignores web_ui in add; with_capabilities adds it unless the overrides remove it."""
    assert Cap.WEB_UI not in apply_overrides({Cap.PUBLIC_REPOS}, {"add": ["web_ui"], "remove": []})
    caps = from_plan("free")
    assert with_capabilities(caps, Cap.WEB_UI, overrides={"add": [], "remove": []}).has(Cap.WEB_UI)
    assert not with_capabilities(caps, Cap.WEB_UI, overrides={"remove": ["web_ui"]}).has(Cap.WEB_UI)
    assert not caps.has(Cap.WEB_UI), "with_capabilities returns a copy"


def test_resolve_web_credentials(harness: HarnessSettings, redactor: Redactor) -> None:
    """None when unset; the admin login as username; password and seeds registered for redaction."""
    target = load_target("free", harness, ENV)
    assert resolve_web_credentials(target, {}) is None
    web = resolve_web_credentials(
        target, {"E2E_ADMIN_PASSWORD": "pw-0123456789", "E2E_ADMIN_TOTP_SEED": "jbsw y3dp ehpk 3pxp"}
    )
    assert web is not None and web.username == "e2e-admin-bot" and web.login == "e2e-admin-bot"
    assert web.totp_seed == SEED and web.identity == "admin"
    assert redactor("pw-0123456789 jbsw y3dp ehpk 3pxp " + SEED) == "*** *** ***"
    assert "pw-0123456789" not in repr(web) and SEED not in repr(web)
    email = resolve_web_credentials(
        target,
        {"E2E_ADMIN_PASSWORD": "pw-0123456789", "E2E_ADMIN_TOTP_SEED": SEED, "E2E_ADMIN_USERNAME": "bot@example.org"},
    )
    assert email is not None and email.username == "bot@example.org"
    same = resolve_web_credentials(
        target,
        {"E2E_ADMIN_PASSWORD": "pw-0123456789", "E2E_ADMIN_TOTP_SEED": SEED, "E2E_ADMIN_USERNAME": "E2E-Admin-Bot"},
    )
    assert same is not None and same.username == "E2E-Admin-Bot"


@pytest.mark.parametrize(
    ("environ", "message"),
    [
        ({"E2E_ADMIN_PASSWORD": "pw-0123456789"}, "E2E_ADMIN_TOTP_SEED is not set"),
        ({"E2E_ADMIN_TOTP_SEED": SEED}, "E2E_ADMIN_PASSWORD is not set"),
        ({"E2E_ADMIN_PASSWORD": "pw-0123456789", "E2E_ADMIN_TOTP_SEED": "123456"}, "not a base32 TOTP secret"),
        (
            {"E2E_ADMIN_PASSWORD": "pw-0123456789", "E2E_ADMIN_TOTP_SEED": SEED, "E2E_ADMIN_USERNAME": "someone-else"},
            "must belong to the admin machine account",
        ),
    ],
)
def test_invalid_web_credentials(harness: HarnessSettings, environ: dict[str, str], message: str) -> None:
    """Partial, invalid or foreign web credentials: WebCredentialsError that never quotes a secret."""
    target = load_target("free", harness, ENV)
    with pytest.raises(WebCredentialsError, match=message) as info:
        resolve_web_credentials(target, environ)
    assert "pw-0123456789" not in str(info.value) and "123456" not in str(info.value).replace("TOTP", "")


def test_normalize_totp_seed() -> None:
    """Spaces, dashes, case and padding are normalized; otpauth URIs give their secret; other algorithms refused."""
    assert normalize_totp_seed("jbsw-y3dp ehpk 3pxp====") == SEED
    assert normalize_totp_seed(f"otpauth://totp/GitHub:bot?secret={SEED}&issuer=GitHub") == SEED
    assert normalize_totp_seed(f"otpauth://totp/x?secret={SEED}&digits=6&period=30&algorithm=SHA1") == SEED
    with pytest.raises(WebCredentialsError, match="SHA1 6-digit"):
        normalize_totp_seed(f"otpauth://totp/x?secret={SEED}&digits=8")
    with pytest.raises(WebCredentialsError, match="no secret"):
        normalize_totp_seed("otpauth://totp/x?issuer=GitHub")
    with pytest.raises(WebCredentialsError, match="otpauth://totp"):
        normalize_totp_seed(f"otpauth://hotp/x?secret={SEED}")
    for bad in ("", "JBSWY3DP", "not-base32-!!", "0189" * 5):
        with pytest.raises(WebCredentialsError):
            normalize_totp_seed(bad)


def test_identity_spec_web_env() -> None:
    """Declared names win, DEFAULT_WEB_ENV otherwise; unknown keys refused."""
    spec = IdentitySpec("admin", "bot", "E2E_ADMIN_TOKEN", password_env="BOT_PASSWORD")
    assert spec.web_env("password_env") == "BOT_PASSWORD"
    assert spec.web_env("totp_seed_env") == DEFAULT_WEB_ENV["totp_seed_env"]
    with pytest.raises(ValueError):
        spec.web_env("token_env")
