"""onboard.store: the reference layout of an instance's secrets in a secret store, kept in step with the secrets the
jobs of each GitHub environment read (.github/workflows), and the Vault policies derived from it."""

from __future__ import annotations

from pathlib import Path

import pytest

from otterdog_e2e.onboard.cisync import workflow_names
from otterdog_e2e.onboard.store import (
    ENVIRONMENT_ITEMS,
    LAYOUT,
    StoreError,
    parse_store,
    store_reference,
    vault_policies,
)

ROOT = Path(__file__).resolve().parents[2]
AUTOMATIC = {"GITHUB_TOKEN"}


@pytest.mark.parametrize(
    ("value", "expected"),
    [("vault:otterdog-e2e", ("vault", "otterdog-e2e")), ("pass:/bots/e2e/", ("pass", "bots/e2e"))],
)
def test_parse_store(value: str, expected: tuple[str, str]) -> None:
    """vault:<prefix> and pass:<prefix>, slashes around the prefix ignored."""
    assert parse_store(value) == expected


@pytest.mark.parametrize("value", ["otterdog-e2e", "bitwarden:x", "vault:", "vault:a b", "pass:../x", "vault:a//b"])
def test_invalid_stores(value: str) -> None:
    """A provider without a path layout (Bitwarden), an empty or odd prefix are refused."""
    with pytest.raises(StoreError):
        parse_store(value)


@pytest.mark.parametrize(
    ("name", "reference"),
    [
        ("E2E_ADMIN_TOKEN", "vault:otterdog-e2e/acme-a/admin/token"),
        ("E2E_CONFIG_READER_TOKEN", "vault:otterdog-e2e/acme-a/config_reader/token"),
        ("E2E_ADMIN_PASSWORD", "vault:otterdog-e2e/acme-a/web/password"),
        ("E2E_ADMIN_TOTP_SEED", "vault:otterdog-e2e/acme-a/web/totp_seed"),
        ("E2E_APP_PRIVATE_KEY", "vault:otterdog-e2e/acme-a/app/private_key"),
        ("E2E_APP_WEBHOOK_SECRET", "vault:otterdog-e2e/acme-a/app/webhook_secret"),
    ],
)
def test_store_reference(name: str, reference: str) -> None:
    """<prefix>/<instance>/<item>/<field>."""
    assert store_reference("vault:otterdog-e2e", "acme-a", name) == reference


def test_the_layout_covers_every_secret_the_jobs_read() -> None:
    """Every secret a workflow job reads has its place in the store, and each environment's items are exactly those
    of the secrets its jobs read (the web login never reaches the e2e environments)."""
    names = workflow_names(ROOT / ".github" / "workflows")
    for kind, items in ENVIRONMENT_ITEMS.items():
        secrets = names[kind].secrets - AUTOMATIC
        assert secrets <= set(LAYOUT), sorted(secrets - set(LAYOUT))
        assert {LAYOUT[name][0] for name in secrets} == set(items), kind
    assert "web" not in ENVIRONMENT_ITEMS["trusted"] + ENVIRONMENT_ITEMS["untrusted"]


def test_vault_policies() -> None:
    """One read-only policy per environment of the instance, on the KV v2 data paths of its items."""
    policies = vault_policies("vault:otterdog-e2e", "acme-a", mount="kv")
    assert sorted(policies) == ["otterdog-e2e-acme-a", "otterdog-e2e-acme-a-untrusted", "otterdog-e2e-acme-a-webui"]
    webui = policies["otterdog-e2e-acme-a-webui"].splitlines()
    assert webui == [
        'path "kv/data/otterdog-e2e/acme-a/admin" { capabilities = ["read"] }',
        'path "kv/data/otterdog-e2e/acme-a/oracle" { capabilities = ["read"] }',
        'path "kv/data/otterdog-e2e/acme-a/web" { capabilities = ["read"] }',
    ]
    assert "/web" not in policies["otterdog-e2e-acme-a-untrusted"]
    assert '"kv/data/otterdog-e2e/acme-a/app"' in policies["otterdog-e2e-acme-a"]
