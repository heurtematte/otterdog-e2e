"""Secrets kept in an external vault: references instead of values (docs/security.md, "Secrets in an external vault").

The value of a secret variable (a name matching redact.SECRET_KEY_RE: ``*_TOKEN``, ``*_SECRET``, ``*_PASSWORD``,
``*_TOTP_SEED``, ``*_PRIVATE_KEY``), in an instance env file or in the environment, may be a reference to a vault
entry. settings resolves it when the harness reads the variable (settings._env_value), so a run only reaches the
vaults of the secrets it uses. The syntax is the one of otterdog's own secret references:

* ``vault:<path>/<field>``: HashiCorp Vault, KV v2, field ``<field>`` of the secret ``<path>`` (``value`` without a
  ``/``) of the mount E2E_VAULT_MOUNT (default ``secret``), at E2E_VAULT_ADDR (else VAULT_ADDR), namespace
  E2E_VAULT_NAMESPACE (else VAULT_NAMESPACE), CA bundle VAULT_CACERT. Login: in a GitHub Actions job with
  E2E_VAULT_ROLE set and an OIDC token (``permissions: id-token: write``), the JWT auth method E2E_VAULT_AUTH_MOUNT
  (default ``jwt``) with that token (audience E2E_VAULT_AUDIENCE, else GitHub's default); else VAULT_TOKEN, else
  ~/.vault-token (``vault login``);
* ``pass:<path>``: the whole entry of ``pass show <path>`` (E2E_PASS_BIN, e.g. ``gopass``), so a multi-line entry such
  as a PEM key keeps its lines;
* ``bitwarden:<item id>@<field>``: a custom field of ``bw get item <item id>`` (an unlocked session: BW_SESSION;
  E2E_BITWARDEN_BIN), or ``login.username``, ``login.password``, ``login.totp`` (the TOTP seed) or ``notes``.

Each reference is resolved once per process (RESOLVER caches values, Vault logins and Bitwarden items) and its value
registered with REDACTOR, as is every token of a Vault login; errors (VaultError) name the reference, never a value.
The provider CLIs run through procs.run with the operator's HOME and the provider's own variables (password store,
GnuPG, Bitwarden session), which procs strips from every other child.
"""

from __future__ import annotations

import json
import os
import threading
import urllib.parse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from otterdog_e2e.redact import REDACTOR

PROVIDERS = ("vault", "pass", "bitwarden")
DEFAULT_VAULT_MOUNT = "secret"
DEFAULT_VAULT_AUTH_MOUNT = "jwt"
DEFAULT_VAULT_FIELD = "value"  # otterdog's field of a vault reference without '/'
VAULT_TIMEOUT = 30.0
PROVIDER_TIMEOUT = 60.0
BITWARDEN_FIELDS = ("login.username", "login.password", "login.totp", "notes")
# provider variables a CLI needs although procs strips them (BW_*, PASSWORD_STORE_*) or the scratch HOME hides them
PASS_ENV_PREFIXES = ("PASSWORD_STORE_", "GNUPGHOME", "GPG_TTY")
BITWARDEN_ENV_PREFIXES = ("BW_", "BITWARDENCLI_", "NODE_EXTRA_CA_CERTS")
OIDC_URL_ENV, OIDC_TOKEN_ENV = "ACTIONS_ID_TOKEN_REQUEST_URL", "ACTIONS_ID_TOKEN_REQUEST_TOKEN"


class VaultError(RuntimeError):
    """A reference that cannot be resolved (the message names the reference, never a value)."""


@dataclass(frozen=True)
class Reference:
    """A parsed reference: provider, then (vault) path and field, (pass) path, (bitwarden) item id and field."""

    provider: str
    path: str
    field: str | None = None

    def __str__(self) -> str:
        """The reference as written."""
        if self.provider == "vault":
            return f"vault:{self.path}/{self.field}"
        if self.provider == "bitwarden":
            return f"bitwarden:{self.path}@{self.field}"
        return f"{self.provider}:{self.path}"


def is_reference(value: str | None) -> bool:
    """True for a one-line ``<provider>:<data>`` value of a PROVIDERS provider."""
    if not value or "\n" in value:
        return False
    provider, sep, data = value.strip().partition(":")
    return bool(sep) and provider in PROVIDERS and bool(data.strip())


def parse(value: str) -> Reference:
    """The Reference of ``value`` (VaultError when it is not one, or malformed)."""
    if not is_reference(value):
        raise VaultError(f"not a secret reference (expected one of {', '.join(f'{p}:' for p in PROVIDERS)})")
    provider, _, data = value.strip().partition(":")
    data = data.strip()
    if provider == "vault":
        path, sep, field = data.rpartition("/")
        path, field = (path, field) if sep else (data, DEFAULT_VAULT_FIELD)
        if not path.strip("/") or not field:
            raise VaultError(f"{value!r}: expected vault:<path>/<field>")
        return Reference(provider, path.strip("/"), field)
    if provider == "bitwarden":
        item, sep, field = data.partition("@")
        if not sep or not item or not field:
            raise VaultError(f"{value!r}: expected bitwarden:<item id>@<field>")
        return Reference(provider, item, field)
    return Reference(provider, data)


@dataclass(frozen=True)
class VaultSettings:
    """Where and how to reach HashiCorp Vault (module docstring)."""

    addr: str
    namespace: str | None
    mount: str
    role: str | None
    auth_mount: str
    audience: str | None
    ca_cert: str | None

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> VaultSettings:
        """The settings of ``env`` (VaultError without an address)."""
        addr = (env.get("E2E_VAULT_ADDR") or env.get("VAULT_ADDR") or "").strip().rstrip("/")
        if not addr:
            raise VaultError("vault: no address (set E2E_VAULT_ADDR, or VAULT_ADDR)")
        if not addr.startswith("https://") and not addr.startswith(("http://127.0.0.1", "http://localhost")):
            raise VaultError(f"vault: {addr} is not an https:// address")
        return cls(
            addr=addr,
            namespace=(env.get("E2E_VAULT_NAMESPACE") or env.get("VAULT_NAMESPACE") or "").strip() or None,
            mount=(env.get("E2E_VAULT_MOUNT") or DEFAULT_VAULT_MOUNT).strip("/ "),
            role=(env.get("E2E_VAULT_ROLE") or "").strip() or None,
            auth_mount=(env.get("E2E_VAULT_AUTH_MOUNT") or DEFAULT_VAULT_AUTH_MOUNT).strip("/ "),
            audience=(env.get("E2E_VAULT_AUDIENCE") or "").strip() or None,
            ca_cert=(env.get("VAULT_CACERT") or "").strip() or None,
        )


def operator_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment providers read: the process environment overlaid with ``environ`` (env file values)."""
    return {**os.environ, **environ}


class Resolver:
    """Resolves references with a per-process cache (module docstring); one instance serves the process (RESOLVER)."""

    def __init__(self, run: Callable[..., Any] | None = None, session: Any = None) -> None:
        """``run`` (procs.run) and ``session`` (a requests session) may be replaced by tests."""
        self._run = run
        self._session = session
        self._lock = threading.RLock()
        self._values: dict[tuple[str, ...], str] = {}
        self._vault_tokens: dict[tuple[str, ...], str] = {}
        self._items: dict[tuple[str, str], dict[str, Any]] = {}

    def clear(self) -> None:
        """Forget every cached value, login and item."""
        with self._lock:
            self._values.clear()
            self._vault_tokens.clear()
            self._items.clear()

    def resolve(self, value: str, environ: Mapping[str, str]) -> str:
        """The secret ``value`` refers to, registered with REDACTOR (VaultError when it cannot be read)."""
        reference = parse(value)
        env = operator_env(environ)
        with self._lock:
            key = self._cache_key(reference, env)
            if key not in self._values:
                secret = self._read(reference, env)
                if not secret:
                    raise VaultError(f"{reference}: empty value")
                REDACTOR.add(secret, secret.strip())
                self._values[key] = secret
            return self._values[key]

    def _cache_key(self, reference: Reference, env: Mapping[str, str]) -> tuple[str, ...]:
        """The reference plus what decides where it is read."""
        if reference.provider == "vault":
            settings = VaultSettings.from_env(env)
            return (str(reference), settings.addr, settings.namespace or "", settings.mount)
        if reference.provider == "pass":
            return (str(reference), env.get("E2E_PASS_BIN") or "pass", env.get("PASSWORD_STORE_DIR") or "")
        return (str(reference), env.get("E2E_BITWARDEN_BIN") or "bw")

    def _read(self, reference: Reference, env: Mapping[str, str]) -> str:
        """Dispatch to the provider."""
        if reference.provider == "vault":
            return self._read_vault(reference, VaultSettings.from_env(env), env)
        if reference.provider == "pass":
            return self._read_pass(reference, env)
        return self._read_bitwarden(reference, env)

    # --- HashiCorp Vault -----------------------------------------------------------------------------------------
    def _http(self) -> Any:
        """The requests session (created on first use)."""
        if self._session is None:
            import requests

            self._session = requests.Session()
        return self._session

    def _request(self, method: str, url: str, what: str, settings: VaultSettings, **kwargs: Any) -> Any:
        """One HTTP call; VaultError on a network error, a non-2xx answer or a body that is not JSON."""
        import requests

        verify: bool | str = settings.ca_cert or True
        try:
            response = self._http().request(method, url, timeout=VAULT_TIMEOUT, verify=verify, **kwargs)
        except requests.RequestException as exc:
            raise VaultError(f"{what}: {type(exc).__name__} reaching {urllib.parse.urlsplit(url).netloc}") from None
        if not 200 <= response.status_code < 300:
            raise VaultError(f"{what}: HTTP {response.status_code}{_vault_errors(response)}")
        try:
            return response.json()
        except ValueError:
            raise VaultError(f"{what}: the answer is not JSON") from None

    def _headers(self, settings: VaultSettings, token: str | None = None) -> dict[str, str]:
        """X-Vault-Token and X-Vault-Namespace."""
        headers = {"X-Vault-Namespace": settings.namespace} if settings.namespace else {}
        if token:
            headers["X-Vault-Token"] = token
        return headers

    def _read_vault(self, reference: Reference, settings: VaultSettings, env: Mapping[str, str]) -> str:
        """Field ``reference.field`` of KV v2 secret ``reference.path``."""
        token = self._vault_token(settings, env)
        path = urllib.parse.quote(reference.path)
        url = f"{settings.addr}/v1/{urllib.parse.quote(settings.mount)}/data/{path}"
        body = self._request(
            "GET", url, f"{reference} (mount {settings.mount})", settings, headers=self._headers(settings, token)
        )
        data = (body.get("data") or {}).get("data") if isinstance(body, dict) else None
        if not isinstance(data, dict):
            raise VaultError(f"{reference}: not a KV v2 secret of the mount {settings.mount}")
        value = data.get(reference.field)
        if not isinstance(value, str) or not value:
            raise VaultError(f"{reference}: no field {reference.field!r} (fields: {', '.join(sorted(data)) or 'none'})")
        return value

    def _vault_token(self, settings: VaultSettings, env: Mapping[str, str]) -> str:
        """The Vault token: a GitHub Actions OIDC login with E2E_VAULT_ROLE, else VAULT_TOKEN, else ~/.vault-token."""
        oidc = bool(settings.role and env.get(OIDC_URL_ENV) and env.get(OIDC_TOKEN_ENV))
        key = (settings.addr, settings.namespace or "", (settings.role or "") if oidc else "")
        if key in self._vault_tokens:
            return self._vault_tokens[key]
        token = self._oidc_login(settings, env) if oidc else (env.get("VAULT_TOKEN") or "").strip() or _token_file(env)
        if not token:
            hint = " (E2E_VAULT_ROLE is set: grant the job `permissions: id-token: write`)" if settings.role else ""
            raise VaultError(f"vault: no token: run `vault login`, or set VAULT_TOKEN{hint}")
        REDACTOR.add(token)
        self._vault_tokens[key] = token
        return token

    def _oidc_login(self, settings: VaultSettings, env: Mapping[str, str]) -> str:
        """The job's GitHub OIDC token exchanged for a Vault token on the JWT auth method (role E2E_VAULT_ROLE)."""
        url = env[OIDC_URL_ENV]
        if settings.audience:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode({"audience": settings.audience})
        request_token = env[OIDC_TOKEN_ENV]
        REDACTOR.add(request_token)
        body = self._request(
            "GET", url, "GitHub OIDC token", settings, headers={"Authorization": f"bearer {request_token}"}
        )
        jwt = body.get("value") if isinstance(body, dict) else None
        if not isinstance(jwt, str) or not jwt:
            raise VaultError("GitHub OIDC token: no value in the answer")
        REDACTOR.add(jwt)
        login = self._request(
            "POST",
            f"{settings.addr}/v1/auth/{urllib.parse.quote(settings.auth_mount)}/login",
            f"vault login (auth {settings.auth_mount}, role {settings.role})",
            settings,
            headers=self._headers(settings),
            json={"role": settings.role, "jwt": jwt},
        )
        token = (login.get("auth") or {}).get("client_token") if isinstance(login, dict) else None
        if not isinstance(token, str) or not token:
            raise VaultError(f"vault login (role {settings.role}): no client token in the answer")
        return token

    # --- pass / gopass and Bitwarden -----------------------------------------------------------------------------
    def _cli(self, argv: list[str], env: Mapping[str, str], prefixes: tuple[str, ...], what: str) -> str:
        """Run a provider CLI with the operator's HOME and the provider variables; its stdout (VaultError otherwise)."""
        from otterdog_e2e import procs

        run = self._run or procs.run
        extra = {key: value for key, value in env.items() if key.startswith(prefixes)}
        if env.get("PATH"):
            extra["PATH"] = env["PATH"]
        try:
            result = run(argv, extra_env=extra, keep_home=True, timeout=PROVIDER_TIMEOUT)
        except FileNotFoundError:
            raise VaultError(f"{what}: {argv[0]} is not installed (or not on PATH)") from None
        except procs.TimeoutExpired:
            raise VaultError(f"{what}: {argv[0]} did not answer within {PROVIDER_TIMEOUT:.0f} s") from None
        if result.returncode != 0:
            detail = (result.stderr or "").strip().splitlines()
            raise VaultError(f"{what}: {argv[0]} exited {result.returncode}{': ' + detail[-1] if detail else ''}")
        return str(result.stdout)

    def _read_pass(self, reference: Reference, env: Mapping[str, str]) -> str:
        """The whole entry, without its trailing newline."""
        command = (env.get("E2E_PASS_BIN") or "pass").strip()
        output = self._cli([command, "show", reference.path], env, PASS_ENV_PREFIXES, str(reference))
        return output.rstrip("\r\n")

    def _read_bitwarden(self, reference: Reference, env: Mapping[str, str]) -> str:
        """A custom field of the item, or one of BITWARDEN_FIELDS."""
        command = (env.get("E2E_BITWARDEN_BIN") or "bw").strip()
        key = (command, reference.path)
        if key not in self._items:
            output = self._cli(
                [command, "get", "item", reference.path, "--nointeraction"], env, BITWARDEN_ENV_PREFIXES, str(reference)
            )
            try:
                item = json.loads(output)
            except ValueError:
                raise VaultError(
                    f"{reference}: bw did not answer an item (is the vault unlocked? BW_SESSION)"
                ) from None
            if not isinstance(item, dict):
                raise VaultError(f"{reference}: bw did not answer an item")
            self._items[key] = item
        return _bitwarden_field(self._items[key], reference)


def _bitwarden_field(item: Mapping[str, Any], reference: Reference) -> str:
    """The field of a Bitwarden item a reference names."""
    field = reference.field or ""
    if field in BITWARDEN_FIELDS:
        container: Any = item.get("login") if field.startswith("login.") else item
        value = (container or {}).get(field.removeprefix("login."))
    else:
        found = [entry for entry in item.get("fields") or [] if isinstance(entry, dict) and entry.get("name") == field]
        if not found:
            names = sorted(str(entry.get("name")) for entry in item.get("fields") or [] if isinstance(entry, dict))
            raise VaultError(
                f"{reference}: no field {field!r} (custom fields: {', '.join(names) or 'none'}; "
                f"or one of {', '.join(BITWARDEN_FIELDS)})"
            )
        value = found[0].get("value")
    if not isinstance(value, str) or not value:
        raise VaultError(f"{reference}: the field {field!r} is empty")
    return value


def _token_file(env: Mapping[str, str]) -> str | None:
    """The token ``vault login`` stored in ~/.vault-token (the operator's HOME)."""
    home = env.get("HOME")
    path = (Path(home) if home else Path.home()) / ".vault-token"
    try:
        return path.read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def _vault_errors(response: Any) -> str:
    """``: <errors>`` of a Vault error answer (Vault's ``errors`` list), else nothing."""
    try:
        errors = response.json().get("errors")
    except (ValueError, AttributeError):
        return ""
    return f": {'; '.join(str(error) for error in errors)}" if isinstance(errors, list) and errors else ""


RESOLVER = Resolver()


def resolve(value: str, environ: Mapping[str, str]) -> str:
    """RESOLVER.resolve: the secret a reference names (VaultError when it cannot be read)."""
    return RESOLVER.resolve(value, environ)
