"""The reference layout of the secrets of an instance in a secret store (docs/security.md, "Reference layout").

``otterdog-e2e setup --store <provider>:<prefix>`` (provider ``vault`` or ``pass``, stored as E2E_SECRET_STORE in the
instance env file) keeps every secret of instance ``<i>`` at ``<prefix>/<i>/<item>/<field>`` (LAYOUT):

* one item per role, field ``token``: ``admin``, ``oracle``, ``author``, ``approver``, ``outsider``, ``config_reader``;
* ``web``: the admin's web login, fields ``password`` and ``totp_seed``;
* ``app``: the GitHub App, fields ``private_key`` and ``webhook_secret``.

A secret is never shared between instances (each test org has its own machine-account tokens and App), and the web
login has an item of its own, so the access of each GitHub environment is a list of items (ENVIRONMENT_ITEMS, the
secrets its jobs read: tests/unit/test_onboard_store.py checks them against the workflows) and vault_policies gives
one read-only Vault policy per environment.
"""

from __future__ import annotations

import re
from collections.abc import Mapping

from otterdog_e2e.onboard.tokens import ROLE_TOKENS, ROLES
from otterdog_e2e.settings import DEFAULT_WEB_ENV

STORE_ENV = "E2E_SECRET_STORE"
STORE_PROVIDERS = ("vault", "pass")  # Bitwarden addresses items by id: no path layout
WEB_ITEM, APP_ITEM = "web", "app"
# env var -> (item, field) of the secret in the store of an instance
LAYOUT: Mapping[str, tuple[str, str]] = {
    **{ROLE_TOKENS[role].token_env: (role, "token") for role in ROLES},
    DEFAULT_WEB_ENV["password_env"]: (WEB_ITEM, "password"),
    DEFAULT_WEB_ENV["totp_seed_env"]: (WEB_ITEM, "totp_seed"),
    "E2E_APP_PRIVATE_KEY": (APP_ITEM, "private_key"),
    "E2E_APP_WEBHOOK_SECRET": (APP_ITEM, "webhook_secret"),
}
# environment kind (onboard.cisync: trusted e2e-<i>, untrusted e2e-<i>-untrusted, webui e2e-<i>-webui) -> the items its
# jobs read: the e2e jobs every role and the App (never the web login), the web-UI job the admin, the oracle and web
ENVIRONMENT_ITEMS: Mapping[str, tuple[str, ...]] = {
    "trusted": (*ROLES, APP_ITEM),
    "untrusted": (*ROLES, APP_ITEM),
    "webui": ("admin", "oracle", WEB_ITEM),
}
ENVIRONMENT_SUFFIXES: Mapping[str, str] = {"trusted": "", "untrusted": "-untrusted", "webui": "-webui"}
_PREFIX_RE = re.compile(r"^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$")


class StoreError(ValueError):
    """An invalid E2E_SECRET_STORE / --store value."""


def parse_store(value: str) -> tuple[str, str]:
    """(provider, prefix) of ``<provider>:<prefix>`` (StoreError otherwise)."""
    provider, sep, prefix = value.strip().partition(":")
    prefix = prefix.strip("/")
    dots = any(part in (".", "..") for part in prefix.split("/"))
    if not sep or provider not in STORE_PROVIDERS or not _PREFIX_RE.match(prefix) or dots:
        raise StoreError(
            f"{STORE_ENV}: expected vault:<prefix> or pass:<prefix> (a path such as otterdog-e2e), got {value!r}"
        )
    return provider, prefix


def store_reference(store: str, instance: str, env_name: str) -> str:
    """The reference of secret ``env_name`` of ``instance`` in ``store`` (KeyError for a name outside LAYOUT)."""
    provider, prefix = parse_store(store)
    item, field = LAYOUT[env_name]
    return f"{provider}:{prefix}/{instance}/{item}/{field}"


def vault_policies(store: str, instance: str, mount: str = "secret") -> dict[str, str]:
    """Policy name -> HCL of the read-only Vault policy of each GitHub environment of ``instance`` (KV v2 ``mount``):
    ``otterdog-e2e-<i>``, ``otterdog-e2e-<i>-untrusted``, ``otterdog-e2e-<i>-webui``."""
    _, prefix = parse_store(store)
    policies = {}
    for kind, items in ENVIRONMENT_ITEMS.items():
        lines = [f'path "{mount}/data/{prefix}/{instance}/{item}" {{ capabilities = ["read"] }}' for item in items]
        policies[f"otterdog-e2e-{instance}{ENVIRONMENT_SUFFIXES[kind]}"] = "\n".join(lines) + "\n"
    return policies
