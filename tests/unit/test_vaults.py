"""otterdog_e2e.vaults: vault references (HashiCorp Vault KV v2 with token, ~/.vault-token and GitHub OIDC logins; pass
and gopass; Bitwarden) resolved once and redacted, and their use by settings, the scrubber and ci-sync's callers.

Vault runs as a loopback HTTP server (KV v2 reads, the JWT login, GitHub's OIDC token endpoint); pass and bw are stub
scripts selected with E2E_PASS_BIN / E2E_BITWARDEN_BIN, so the real procs.run path (sanitized environment plus the
provider variables) is exercised.
"""

from __future__ import annotations

import json
import stat
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any

import click
import pytest

from otterdog_e2e import vaults
from otterdog_e2e.cli.maintenance import register_environment_secrets
from otterdog_e2e.redact import REDACTOR, Redactor
from otterdog_e2e.settings import TargetError, _env_value, load_env_files
from otterdog_e2e.vaults import Reference, Resolver, VaultError, is_reference, parse

ADMIN_TOKEN = "ghp_vaultAdminToken0123456789abcdef0123"
SEED = "JBSWY3DPEHPK3PXP"
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEvaultkeymaterial0123456789\n-----END RSA PRIVATE KEY-----"
VAULT_TOKEN = "hvs.local-token-0123456789"
OIDC_VAULT_TOKEN = "hvs.oidc-token-0123456789"
REQUEST_TOKEN = "oidc-request-token-0123456789"
JWT = "eyJhbGciOiJSUzI1NiJ9.e2e-jwt.signature"
SECRETS: dict[str, dict[str, Any]] = {
    "/v1/secret/data/e2e/free/admin": {"token": ADMIN_TOKEN},
    "/v1/kv/data/e2e/free/app": {"private_key": PEM},
    "/v1/kv/data/app-key": {"value": "default-field-value"},
}


@pytest.fixture(autouse=True)
def resolver(monkeypatch: pytest.MonkeyPatch) -> Resolver:
    """A fresh process resolver per test (no cached value leaks between tests)."""
    fresh = Resolver()
    monkeypatch.setattr(vaults, "RESOLVER", fresh)
    return fresh


# --- references ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("vault:e2e/free/admin/token", Reference("vault", "e2e/free/admin", "token")),
        ("vault:/e2e/free/admin/token", Reference("vault", "e2e/free/admin", "token")),
        ("vault:admin", Reference("vault", "admin", "value")),  # otterdog's default field
        ("pass:bots/e2e/admin-token", Reference("pass", "bots/e2e/admin-token")),
        ("bitwarden:0f4c-item@api_token", Reference("bitwarden", "0f4c-item", "api_token")),
        ("bitwarden:0f4c-item@login.totp", Reference("bitwarden", "0f4c-item", "login.totp")),
    ],
)
def test_parse(value: str, expected: Reference) -> None:
    """The syntax of otterdog's own secret references; str() gives the reference back."""
    assert parse(value) == expected
    assert is_reference(value)


@pytest.mark.parametrize(
    "value",
    ["", "ghp_plainToken", "https://vault.example.org", "vault:", "pass: ", "lastpass:x", "pass:a\nb", "otpauth://x"],
)
def test_values_that_are_not_references(value: str) -> None:
    """Plain values, other schemes, empty data and multi-line values are not references."""
    assert not is_reference(value)


@pytest.mark.parametrize("value", ["bitwarden:item-without-field", "bitwarden:@field", "vault:/field", "pass:"])
def test_malformed_references(value: str) -> None:
    """A reference without its required parts is refused with the expected syntax."""
    with pytest.raises(VaultError):
        parse(value)


# --- HashiCorp Vault -------------------------------------------------------------------------------------------------
class FakeVault(BaseHTTPRequestHandler):
    """KV v2 reads with X-Vault-Token, the JWT login of role e2e, GitHub's OIDC token endpoint; every request logged."""

    requests: list[tuple[str, str, dict[str, str]]] = []

    def log_message(self, format: str, *args: Any) -> None:
        """Silent."""

    def answer(self, status: int, body: Any) -> None:
        """A JSON answer."""
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        """The OIDC token endpoint and the KV v2 reads."""
        FakeVault.requests.append(("GET", self.path, dict(self.headers)))
        if self.path.startswith("/oidc"):
            if self.headers.get("Authorization") != f"bearer {REQUEST_TOKEN}":
                return self.answer(401, {"message": "bad request token"})
            return self.answer(200, {"value": JWT})
        if self.headers.get("X-Vault-Token") not in (VAULT_TOKEN, OIDC_VAULT_TOKEN):
            return self.answer(403, {"errors": ["permission denied"]})
        data = SECRETS.get(self.path)
        if data is None:
            return self.answer(404, {"errors": []})
        return self.answer(200, {"data": {"data": data, "metadata": {"version": 1}}})

    def do_POST(self) -> None:
        """The JWT login."""
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))) or b"{}")
        FakeVault.requests.append(("POST", self.path, {**dict(self.headers), "body": json.dumps(body)}))
        if self.path == "/v1/auth/jwt/login" and body == {"role": "e2e", "jwt": JWT}:
            return self.answer(200, {"auth": {"client_token": OIDC_VAULT_TOKEN}})
        return self.answer(400, {"errors": ["invalid role or jwt"]})


@pytest.fixture
def vault_addr() -> Iterator[str]:
    """The loopback Vault's address (its request log reset)."""
    FakeVault.requests = []
    server = HTTPServer(("127.0.0.1", 0), FakeVault)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()


def test_vault_token_from_the_environment(vault_addr: str, tmp_path: Path) -> None:
    """VAULT_TOKEN reads the field of the mount E2E_VAULT_MOUNT (default secret); the value and the token are
    redacted, the namespace header sent; a second read comes from the cache."""
    env = {"HOME": str(tmp_path), "E2E_VAULT_ADDR": vault_addr, "VAULT_TOKEN": VAULT_TOKEN, "VAULT_NAMESPACE": "e2e"}
    assert vaults.resolve("vault:e2e/free/admin/token", env) == ADMIN_TOKEN
    assert vaults.resolve("vault:e2e/free/admin/token", env) == ADMIN_TOKEN
    assert len(FakeVault.requests) == 1 and FakeVault.requests[0][2]["X-Vault-Namespace"] == "e2e"
    assert REDACTOR(f"{ADMIN_TOKEN} {VAULT_TOKEN}") == "*** ***"


def test_vault_token_file_and_other_mount(vault_addr: str, tmp_path: Path) -> None:
    """~/.vault-token of the operator's HOME (``vault login``); a multi-line field keeps its lines; a reference
    without '/' reads the field ``value`` of that path."""
    (tmp_path / ".vault-token").write_text(VAULT_TOKEN + "\n")
    env = {"HOME": str(tmp_path), "VAULT_ADDR": vault_addr, "E2E_VAULT_MOUNT": "kv"}
    assert vaults.resolve("vault:e2e/free/app/private_key", env) == PEM
    assert vaults.resolve("vault:app-key", env) == "default-field-value"


def test_vault_github_oidc_login(vault_addr: str, tmp_path: Path) -> None:
    """In a job with E2E_VAULT_ROLE and an OIDC token: the token of the audience is exchanged on the JWT auth method
    for a Vault token, which reads the secret; VAULT_TOKEN is not needed and every token is redacted."""
    env = {
        "HOME": str(tmp_path),
        "E2E_VAULT_ADDR": vault_addr,
        "E2E_VAULT_ROLE": "e2e",
        "E2E_VAULT_AUDIENCE": "https://vault.example.org",
        vaults.OIDC_URL_ENV: f"{vault_addr}/oidc?api-version=2.0",
        vaults.OIDC_TOKEN_ENV: REQUEST_TOKEN,
    }
    assert vaults.resolve("vault:e2e/free/admin/token", env) == ADMIN_TOKEN
    oidc, login, read = FakeVault.requests
    assert oidc[1] == "/oidc?api-version=2.0&audience=https%3A%2F%2Fvault.example.org"
    assert login[1] == "/v1/auth/jwt/login" and read[2]["X-Vault-Token"] == OIDC_VAULT_TOKEN
    assert REDACTOR(f"{REQUEST_TOKEN} {JWT} {OIDC_VAULT_TOKEN}") == "*** *** ***"


@pytest.mark.parametrize(
    ("reference", "env", "message"),
    [
        ("vault:e2e/free/admin/nope", {"VAULT_TOKEN": VAULT_TOKEN}, "no field 'nope' (fields: token)"),
        ("vault:e2e/free/admin/token", {"VAULT_TOKEN": "hvs.wrong"}, "HTTP 403: permission denied"),
        ("vault:e2e/free/missing/token", {"VAULT_TOKEN": VAULT_TOKEN}, "HTTP 404"),
        ("vault:e2e/free/admin/token", {}, "vault: no token: run `vault login`, or set VAULT_TOKEN"),
        (
            "vault:e2e/free/admin/token",
            {"E2E_VAULT_ROLE": "e2e"},
            "set VAULT_TOKEN (E2E_VAULT_ROLE is set: grant the job `permissions: id-token: write`)",
        ),
    ],
)
def test_vault_errors(vault_addr: str, tmp_path: Path, reference: str, env: dict[str, str], message: str) -> None:
    """Errors name the reference and the cause (field names, Vault's errors), never a value."""
    with pytest.raises(VaultError, match=None) as info:
        vaults.resolve(reference, {"HOME": str(tmp_path), "E2E_VAULT_ADDR": vault_addr, **env})
    assert message in str(info.value) and ADMIN_TOKEN not in str(info.value)


@pytest.mark.parametrize(
    ("addr", "message"),
    [("", "vault: no address (set E2E_VAULT_ADDR, or VAULT_ADDR)"), ("http://vault.example.org", "not an https://")],
)
def test_vault_address(addr: str, message: str, tmp_path: Path) -> None:
    """An address is required, and must be https:// unless loopback."""
    with pytest.raises(VaultError, match=None) as info:
        vaults.resolve("vault:e2e/x/y", {"HOME": str(tmp_path), "VAULT_ADDR": addr, "VAULT_TOKEN": VAULT_TOKEN})
    assert message in str(info.value)


# --- pass and Bitwarden ----------------------------------------------------------------------------------------------
def stub(path: Path, script: str) -> Path:
    """An executable shell script."""
    path.write_text("#!/bin/sh\n" + script)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


@pytest.fixture
def pass_bin(tmp_path: Path) -> Path:
    """pass: ``show e2e/admin`` prints the token, ``show e2e/app-key`` the PEM (several lines) and the password store
    it was given; anything else fails like pass."""
    return stub(
        tmp_path / "pass",
        f"""[ "$1" = show ] || exit 2
case "$2" in
  e2e/admin) echo '{ADMIN_TOKEN}' ;;
  e2e/app-key) printf '%s\\n' '{PEM}' ;;
  e2e/store) echo "store=$PASSWORD_STORE_DIR" ;;
  *) echo "Error: $2 is not in the password store." >&2; exit 1 ;;
esac
""",
    )


def test_pass_reads_the_whole_entry(pass_bin: Path, tmp_path: Path) -> None:
    """``pass show <path>``: the whole entry without its trailing newline (a PEM keeps its lines); the password store
    variables reach the CLI although procs strips them from every other child."""
    env = {"HOME": str(tmp_path), "E2E_PASS_BIN": str(pass_bin), "PASSWORD_STORE_DIR": "/srv/e2e-store"}
    assert vaults.resolve("pass:e2e/admin", env) == ADMIN_TOKEN
    assert vaults.resolve("pass:e2e/app-key", env) == PEM
    assert vaults.resolve("pass:e2e/store", env) == "store=/srv/e2e-store"


def test_pass_errors(pass_bin: Path, tmp_path: Path) -> None:
    """A missing entry reports pass's own last error line; a missing CLI says so."""
    env = {"HOME": str(tmp_path), "E2E_PASS_BIN": str(pass_bin)}
    with pytest.raises(VaultError, match=r"pass:e2e/nope: .*exited 1: Error: e2e/nope is not in the password store"):
        vaults.resolve("pass:e2e/nope", env)
    with pytest.raises(VaultError, match="is not installed"):
        vaults.resolve("pass:e2e/admin", {**env, "E2E_PASS_BIN": str(tmp_path / "nowhere")})


@pytest.fixture
def bw_bin(tmp_path: Path) -> Path:
    """bw: ``get item item-1 --nointeraction`` prints the item when BW_SESSION is set (each call counted)."""
    item = {
        "id": "item-1",
        "login": {"username": "e2e-admin", "password": "web-password-0123", "totp": SEED},
        "notes": PEM,
        "fields": [{"name": "api_token", "value": ADMIN_TOKEN, "type": 1}],
    }
    calls = tmp_path / "bw-calls"
    return stub(
        tmp_path / "bw",
        f"""echo call >> '{calls}'
[ "$*" = "get item item-1 --nointeraction" ] || {{ echo "Not found." >&2; exit 1; }}
[ -n "$BW_SESSION" ] || {{ echo "Vault is locked." >&2; exit 1; }}
cat <<'EOF'
{json.dumps(item)}
EOF
""",
    )


def test_bitwarden_fields(bw_bin: Path, tmp_path: Path) -> None:
    """A custom field, the login fields and the notes of one item, fetched once (BW_SESSION reaches bw)."""
    env = {"HOME": str(tmp_path), "E2E_BITWARDEN_BIN": str(bw_bin), "BW_SESSION": "session-0123456789"}
    assert vaults.resolve("bitwarden:item-1@api_token", env) == ADMIN_TOKEN
    assert vaults.resolve("bitwarden:item-1@login.password", env) == "web-password-0123"
    assert vaults.resolve("bitwarden:item-1@login.totp", env) == SEED
    assert vaults.resolve("bitwarden:item-1@notes", env) == PEM
    assert (tmp_path / "bw-calls").read_text().count("call") == 1


def test_bitwarden_errors(bw_bin: Path, tmp_path: Path) -> None:
    """A locked vault, an unknown item and an unknown field (the custom field names listed)."""
    env = {"HOME": str(tmp_path), "E2E_BITWARDEN_BIN": str(bw_bin)}
    with pytest.raises(VaultError, match=r"exited 1: Vault is locked\."):
        vaults.resolve("bitwarden:item-1@api_token", env)
    env["BW_SESSION"] = "session-0123456789"
    with pytest.raises(VaultError, match=r"exited 1: Not found\."):
        vaults.resolve("bitwarden:item-2@api_token", env)
    with pytest.raises(VaultError, match=r"no field 'token' \(custom fields: api_token; or one of login.username"):
        vaults.resolve("bitwarden:item-1@token", env)


# --- callers ---------------------------------------------------------------------------------------------------------
def test_settings_resolve_secret_variables_only(pass_bin: Path, tmp_path: Path) -> None:
    """_env_value resolves the reference of a secret variable, leaves a reference-looking value of any other variable
    as it is, and names the variable when the reference cannot be read."""
    env = {
        "HOME": str(tmp_path),
        "E2E_PASS_BIN": str(pass_bin),
        "E2E_ADMIN_TOKEN": "pass:e2e/admin",
        "E2E_APP_ID": "pass:e2e/admin",
        "E2E_ORACLE_TOKEN": "pass:e2e/nope",
    }
    assert _env_value(env, "E2E_ADMIN_TOKEN") == ADMIN_TOKEN
    assert _env_value(env, "E2E_APP_ID") == "pass:e2e/admin"
    with pytest.raises(TargetError, match=r"^E2E_ORACLE_TOKEN: pass:e2e/nope: "):
        _env_value(env, "E2E_ORACLE_TOKEN")


def test_env_files_never_register_references(tmp_path: Path) -> None:
    """A reference in an env file is not a secret: it stays readable in messages; plain secrets are registered."""
    project = tmp_path / "project"
    project.mkdir()
    (project / ".env.e2e").write_text("E2E_ADMIN_TOKEN=pass:e2e/reference-is-not-secret\nE2E_X_SECRET=plain-secret-0\n")
    environ = {"HOME": str(tmp_path)}
    load_env_files(None, project, environ)
    assert environ["E2E_ADMIN_TOKEN"] == "pass:e2e/reference-is-not-secret"
    assert REDACTOR("pass:e2e/reference-is-not-secret plain-secret-0") == "pass:e2e/reference-is-not-secret ***"


def test_the_scrubber_resolves_references(pass_bin: Path, tmp_path: Path) -> None:
    """register_environment_secrets registers the value behind a reference, and fails closed when it cannot read it."""
    redactor = Redactor()
    env = {"HOME": str(tmp_path), "E2E_PASS_BIN": str(pass_bin), "E2E_ADMIN_TOKEN": "pass:e2e/admin"}
    assert register_environment_secrets(env, redactor) == 1
    assert redactor(ADMIN_TOKEN) == "***"
    with pytest.raises(click.ClickException, match=r"E2E_ADMIN_TOKEN: pass:e2e/nope: .*\(the scan needs the value"):
        register_environment_secrets({**env, "E2E_ADMIN_TOKEN": "pass:e2e/nope"}, redactor)
