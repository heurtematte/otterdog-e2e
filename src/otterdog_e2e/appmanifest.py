"""GitHub App manifest flow for the e2e App (SPEC 14, GH-01, GH-12).

Permission keys are the parameterized permission names of the GitHub docs; components.schemas.app-permissions of the
OpenAPI description is incomplete (it lacks actions_variables and organization_actions_variables). The App is private
(``public: false``) and its hook URL must not be a loopback URL (deliveries reach the webapp through the relay).

Flow: build_manifest() -> manifest_form_html() (served on 127.0.0.1, auto-posts to GitHub) -> GitHub redirects to
``redirect_url?code=...&state=...`` -> code_from_callback() -> exchange_code() within one hour. The conversion answer
carries the private key, the webhook secret and the OAuth client secret: the first two are written to 0600 files in a
0700 directory, the client id/secret are discarded, and nothing secret is returned, logged or printed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import html
import ipaddress
import json
import logging
import os
import re
import secrets
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e.github.http import GitHubHttp
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.settings import Target

DEFAULT_PERMISSIONS: dict[str, str] = {
    "actions": "write",
    "administration": "write",
    "statuses": "write",
    "contents": "write",
    "repository_custom_properties": "write",
    "environments": "write",
    "issues": "read",
    "metadata": "read",
    "pages": "write",
    "pull_requests": "write",
    "secrets": "write",
    "actions_variables": "write",
    "repository_hooks": "write",
    "workflows": "write",
    "organization_administration": "write",
    "organization_custom_org_roles": "write",
    "organization_custom_properties": "admin",
    "members": "write",
    "organization_plan": "read",
    "organization_secrets": "write",
    "organization_actions_variables": "write",
    "organization_hooks": "write",
}
DEFAULT_EVENTS: list[str] = [
    "issue_comment",
    "pull_request",
    "pull_request_review",
    "push",
    "workflow_job",
    "workflow_run",
]
APP_NAME_MAX_LENGTH = 34
DEFAULT_CALLBACK_PORT = 8765
GITHUB_WEB = "https://github.com"
FORM_ID = "otterdog-e2e-manifest"
AUTO_SUBMIT_SCRIPT = f'document.getElementById("{FORM_ID}").submit();'
# env names of the App credentials in targets/*.yaml (app.id_env, app.private_key_file_env, ...)
APP_ENV_NAMES = {
    "id": "E2E_APP_ID",
    "slug": "E2E_APP_SLUG",
    "private_key_file": "E2E_APP_PRIVATE_KEY_FILE",
    "webhook_secret": "E2E_APP_WEBHOOK_SECRET",
}
LOGIN_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})$")
CODE_RE = re.compile(r"^[A-Za-z0-9_-]{8,256}$")
_LOOPBACK_NAMES = ("localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback")

log = logging.getLogger(__name__)


def check_login(org: str) -> str:
    """``org`` when it is a valid GitHub organization login (ValueError otherwise)."""
    if not LOGIN_RE.match(org):
        raise ValueError(f"not a GitHub organization login: {org!r}")
    return org


def app_name(org: str) -> str:
    """Manifest App name: ``otterdog-e2e-<org>`` cut to GitHub's 34-character limit."""
    return f"otterdog-e2e-{check_login(org)}"[:APP_NAME_MAX_LENGTH]


def is_loopback_host(host: str) -> bool:
    """True for localhost names, loopback and unspecified IP addresses (GitHub rejects them as hook hosts)."""
    name = host.strip("[]").rstrip(".").lower()
    if name in _LOOPBACK_NAMES or name.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(name)
    except ValueError:
        return False
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return address.is_loopback or address.is_unspecified


def check_webhook_url(url: str) -> str:
    """The App hook URL: absolute https URL with a non-loopback host (ValueError otherwise)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError(f"the App webhook URL must be an absolute https URL, got {url!r}")
    if parts.username or parts.password:
        raise ValueError("the App webhook URL must not embed credentials")
    if is_loopback_host(parts.hostname):
        raise ValueError(
            f"the App webhook URL must not be a loopback URL ({parts.hostname}): GitHub rejects it; use a sink you "
            "control (deliveries reach the webapp through the relay)"
        )
    return url


def check_redirect_url(url: str) -> str:
    """The manifest redirect URL: absolute http(s) URL (normally the local callback listener)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"the manifest redirect URL must be an absolute http(s) URL, got {url!r}")
    return url


def default_redirect_url(port: int = DEFAULT_CALLBACK_PORT) -> str:
    """Callback URL of the local one-shot listener (``http://127.0.0.1:<port>/callback``)."""
    return f"http://127.0.0.1:{port}/callback"


def build_manifest(target: Target, *, webhook_url: str, redirect_url: str) -> dict[str, Any]:
    """Manifest: name f"otterdog-e2e-{org}"[:34], url, hook_attributes {url (non-loopback), active true},
    redirect_url, public false, default_permissions, default_events (ValueError for a loopback webhook_url)."""
    return {
        "name": app_name(target.org),
        "url": f"{GITHUB_WEB}/{target.org}/{target.configs_repo}",
        "description": f"otterdog end-to-end tests on the dedicated test organization {target.org} (otterdog-e2e)",
        "hook_attributes": {"url": check_webhook_url(webhook_url), "active": True},
        "redirect_url": check_redirect_url(redirect_url),
        "public": False,
        "default_permissions": dict(DEFAULT_PERMISSIONS),
        "default_events": list(DEFAULT_EVENTS),
    }


def new_state() -> str:
    """Random ``state`` value of one manifest flow."""
    return secrets.token_urlsafe(24)


def manifest_form_url(org: str, state: str) -> str:
    """https://github.com/organizations/<org>/settings/apps/new?state=<state>."""
    query = urllib.parse.urlencode({"state": state})
    return f"{GITHUB_WEB}/organizations/{check_login(org)}/settings/apps/new?{query}"


def script_hash(script: str) -> str:
    """CSP source expression (``'sha256-...'``) allowing exactly this inline script."""
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    return f"'sha256-{digest}'"


def manifest_form_html(org: str, manifest: dict[str, Any], state: str) -> str:
    """HTML page auto-posting the manifest (and ``state``) to github.com/organizations/<org>/settings/apps/new."""
    if not state:
        raise ValueError("the manifest flow needs a non-empty state")
    action = html.escape(manifest_form_url(org, state), quote=True)
    value = html.escape(json.dumps(manifest, sort_keys=True), quote=True)
    name = html.escape(str(manifest.get("name", "")), quote=True)
    csp = f"default-src 'none'; script-src {script_hash(AUTO_SUBMIT_SCRIPT)}; form-action {GITHUB_WEB}; base-uri 'none'"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="{html.escape(csp, quote=True)}">
<title>otterdog-e2e: register the GitHub App</title>
</head>
<body>
<form id="{FORM_ID}" method="post" action="{action}">
<input type="hidden" name="manifest" value="{value}">
<input type="hidden" name="state" value="{html.escape(state, quote=True)}">
<p>Registering the GitHub App <strong>{name}</strong> on <strong>{html.escape(org)}</strong>.</p>
<noscript><p>JavaScript is disabled: press the button to continue on GitHub.</p></noscript>
<button type="submit">Continue on GitHub</button>
</form>
<script>{AUTO_SUBMIT_SCRIPT}</script>
</body>
</html>
"""


def code_from_callback(query: str, *, state: str) -> str:
    """The manifest ``code`` of a redirect query string (or URL); ValueError when state or code is wrong."""
    if "?" in query:
        query = urllib.parse.urlsplit(query).query
    params = urllib.parse.parse_qs(query.lstrip("?"))
    received = (params.get("state") or [""])[0]
    if not state or not hmac.compare_digest(received.encode(), state.encode()):
        raise ValueError("manifest callback state mismatch (stale or forged redirect)")
    code = (params.get("code") or [""])[0]
    if not CODE_RE.match(code):
        raise ValueError("manifest callback without a valid code")
    REDACTOR.add(code)
    return code


def _manifest_http() -> GitHubHttp:
    """Unauthenticated client of the manifest conversion (the code is the credential)."""
    return GitHubHttp(None, identity="app-manifest")


def _private_dir(out_dir: Path) -> Path:
    """Create ``out_dir`` (``~`` expanded) with mode 0700 (an existing one is tightened; a symlink is refused)."""
    out_dir = out_dir.expanduser()
    if out_dir.is_symlink():
        raise SafetyError(f"refusing to write App credentials through a symlink: {out_dir}")
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(out_dir, 0o700)
    return out_dir


def _write_private(path: Path, text: str) -> Path:
    """Create a new 0600 file (never overwrites, never follows symlinks)."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)
    return path


def _env_value(value: str) -> str:
    """Env-file value, double-quoted when it contains blanks or '#'."""
    return f'"{value}"' if re.search(r"[\s#'\"]", value) else value


def env_snippet(app_id: int, slug: str, pem_path: Path, webhook_secret: str) -> str:
    """Lines for the target env file (~/.config/otterdog-e2e/<target>.env), default env names of targets/*.yaml."""
    created = datetime.now(UTC).isoformat(timespec="seconds")
    lines = [
        f"# otterdog-e2e GitHub App {slug} (id {app_id}), created {created}",
        "# append to the target env file, e.g. ~/.config/otterdog-e2e/<target>.env",
        f"{APP_ENV_NAMES['id']}={app_id}",
        f"{APP_ENV_NAMES['slug']}={_env_value(slug)}",
        f"{APP_ENV_NAMES['private_key_file']}={_env_value(str(pem_path))}",
        f"{APP_ENV_NAMES['webhook_secret']}={_env_value(webhook_secret)}",
    ]
    return "\n".join(lines) + "\n"


class ManifestExchangeError(RuntimeError):
    """The manifest conversion answered something unusable (no key, no App id/slug)."""


def _conversion_problem(data: Any) -> str | None:
    """Why a conversion answer is unusable, None when it is fine."""
    if not isinstance(data, dict):
        return "not a JSON object"
    pem = data.get("pem")
    if not isinstance(pem, str) or "PRIVATE KEY-----" not in pem:
        return "no private key"
    app_id = data.get("id")
    if isinstance(app_id, bool) or not isinstance(app_id, int) or not isinstance(data.get("slug"), str):
        return "no App id/slug"
    return None


def _conversion(code: str) -> dict[str, Any]:
    """POST /app-manifests/{code}/conversions; registers every secret of the answer with REDACTOR."""
    data = _manifest_http().post(f"/app-manifests/{code}/conversions")
    if isinstance(data, dict):
        REDACTOR.add(data.get("pem"), data.get("client_secret"), data.get("webhook_secret"))
    problem = _conversion_problem(data)
    if problem:
        raise ManifestExchangeError(f"unusable answer of the manifest conversion: {problem}")
    return dict(data)


def exchange_code(code: str, *, out_dir: Path) -> dict[str, Any]:
    """POST /app-manifests/{code}/conversions; writes the pem and webhook secret to 0600 files in out_dir (0700),
    discards client_id/client_secret; returns {id, slug, pem_path, secret_path}."""
    if not CODE_RE.match(code or ""):
        raise ValueError("invalid manifest code (expected the 'code' parameter of the GitHub redirect)")
    REDACTOR.add(code)
    data = _conversion(code)
    app_id, slug = int(data["id"]), str(data["slug"])
    secret = data.get("webhook_secret")
    generated = not isinstance(secret, str) or not secret
    if generated:
        secret = secrets.token_hex(32)
        REDACTOR.add(secret)
        log.warning(
            "GitHub returned no webhook secret for App %s: generated one locally; the relay signs forwarded deliveries "
            "with it, set it as the App's webhook secret in its GitHub settings as well",
            slug,
        )
    directory = _private_dir(out_dir)
    pem_path = _write_private(directory / f"app-{app_id}.private-key.pem", str(data["pem"]))
    secret_path = _write_private(directory / f"app-{app_id}.webhook-secret", f"{secret}\n")
    env_path = _write_private(directory / f"app-{app_id}.env", env_snippet(app_id, slug, pem_path, str(secret)))
    owner: dict[str, Any] = data["owner"] if isinstance(data.get("owner"), dict) else {}
    log.info("GitHub App %s (id %s) created; credentials written to %s (mode 0600)", slug, app_id, directory)
    return {
        "id": app_id,
        "slug": slug,
        "name": data.get("name"),
        "owner": owner.get("login"),
        "html_url": data.get("html_url"),
        "pem_path": pem_path,
        "secret_path": secret_path,
        "env_path": env_path,
        "secret_generated": generated,
    }
