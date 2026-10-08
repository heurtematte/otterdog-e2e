"""``otterdog-e2e app-manifest`` (SPEC 16): creates the e2e GitHub App from a manifest, or exchanges the returned
code.

ManifestFlow serves the auto-posting manifest form on 127.0.0.1 and waits for GitHub's redirect (``state`` verified,
the temporary code registered with the redactor); the code is exchanged for the App credentials, written 0600 to the
user config dir, and the next steps are printed (paths only, never a secret). The setup wizard reuses the flow.
"""

from __future__ import annotations

import hmac
import http.server
import logging
import re
import secrets
import time
import urllib.parse
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from otterdog_e2e.cli.common import _context, _echo, _handled, _is_loopback_url, main
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.settings import Target

logger = logging.getLogger(__name__)

MANIFEST_TIMEOUT = 600.0


# --- app-manifest ---------------------------------------------------------------------------------------------------
class ManifestFlow:
    """One-shot callback listener of the GitHub App manifest flow (127.0.0.1 only, ``state`` verified)."""

    def __init__(
        self,
        target: Target,
        *,
        webhook_url: str,
        port: int,
        state: str | None = None,
        timeout: float = MANIFEST_TIMEOUT,
    ) -> None:
        """Prepare the flow; nothing listens before run()."""
        self.target = target
        self.webhook_url = webhook_url
        self.port = port
        self.state = state or secrets.token_urlsafe(24)
        self.timeout = timeout
        self.page = ""
        self.code: str | None = None

    def run(self, *, on_ready: Callable[[str], None] | None = None) -> str:
        """Serve the auto-posting form and wait for GitHub's redirect; returns the temporary code."""
        from otterdog_e2e.appmanifest import build_manifest, manifest_form_html

        server = _ManifestServer(("127.0.0.1", self.port), self)
        try:
            base = f"http://127.0.0.1:{server.server_address[1]}/"
            manifest = build_manifest(self.target, webhook_url=self.webhook_url, redirect_url=f"{base}callback")
            self.page = manifest_form_html(self.target.org, manifest, self.state)
            (on_ready or (lambda url: _echo(f"open {url} in a browser logged in as an owner of {self.target.org}")))(
                base
            )
            deadline = time.monotonic() + self.timeout
            while self.code is None:
                if time.monotonic() > deadline:
                    raise click.ClickException(f"no callback from GitHub within {self.timeout:g} s")
                server.handle_request()
        finally:
            server.server_close()
        return self.code

    def callback(self, query: Mapping[str, list[str]]) -> tuple[int, str]:
        """Accept GitHub's redirect only with our state; keeps the code (registered with REDACTOR)."""
        state = (query.get("state") or [""])[0]
        if not hmac.compare_digest(state.encode(), self.state.encode()):
            return 400, "state mismatch: ignored"
        code = (query.get("code") or [""])[0]
        if not re.fullmatch(r"[0-9A-Za-z_-]{8,256}", code):
            return 400, "missing or malformed code"
        REDACTOR.add(code)
        self.code = code
        return 200, "GitHub App created: return to the terminal."


class _ManifestHandler(http.server.BaseHTTPRequestHandler):
    """GET / (manifest form) and GET /callback?code=&state= (GitHub redirect)."""

    server: _ManifestServer

    def do_GET(self) -> None:
        """Serve the form or handle the callback."""
        url = urllib.parse.urlsplit(self.path)
        flow = self.server.flow
        if url.path == "/":
            self._send(200, flow.page, "text/html; charset=utf-8")
        elif url.path == "/callback":
            self._send(*flow.callback(urllib.parse.parse_qs(url.query)))
        else:
            self._send(404, "not found")

    def _send(self, status: int, body: str, content_type: str = "text/plain; charset=utf-8") -> None:
        """Write one response."""
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        """Never log request lines (they carry the temporary code)."""
        logger.debug("manifest listener: request handled")


class _ManifestServer(http.server.HTTPServer):
    """HTTPServer bound to loopback carrying the flow; handle_request() returns every second."""

    def __init__(self, address: tuple[str, int], flow: ManifestFlow) -> None:
        """Bind the listener."""
        super().__init__(address, _ManifestHandler)
        self.flow = flow
        self.timeout = 1.0


def app_credentials_dir(target: Target, environ: Mapping[str, str] | None = None) -> Path:
    """<user config dir>/<target>/, below HOME of ``environ`` (settings.user_config_dir; default os.environ):
    exchange_code writes the key and secret there (0600)."""
    from otterdog_e2e.settings import user_config_dir

    return user_config_dir(environ) / target.name


def app_instructions(target: Target, result: Mapping[str, Any], environ: Mapping[str, str] | None = None) -> str:
    """Next steps after the exchange (paths only: secrets are never printed); the env file is the target's in the
    user config dir below HOME of ``environ``."""
    from otterdog_e2e.appmanifest import installation_url
    from otterdog_e2e.settings import user_config_dir

    app = target.app
    id_env = app.id_env if app else "E2E_APP_ID"
    key_env = (app.private_key_file_env if app else None) or "E2E_APP_PRIVATE_KEY_FILE"
    secret_env = app.webhook_secret_env if app else "E2E_APP_WEBHOOK_SECRET"
    env_file = user_config_dir(environ) / f"{target.name}.env"
    lines = [
        f"GitHub App created: id {result.get('id')}, slug {result.get('slug')}",
        f"private key (0600):    {result.get('pem_path')}",
        f"webhook secret (0600): {result.get('secret_path')}",
        f"add to {env_file}:",
        f"  {id_env}={result.get('id')}",
        f"  E2E_APP_SLUG={result.get('slug')}",
        f"  {key_env}={result.get('pem_path')}",
        f"  {secret_env}=<the content of {result.get('secret_path')}>",
    ]
    if result.get("env_path"):
        lines.append(f"  (or append {result.get('env_path')}: the same lines, secret included)")
    install = installation_url(str(result.get("slug")), target.org_id)
    return "\n".join([*lines, f"then install it on {target.org} for All repositories: {install}"])


@main.command("app-manifest")
@click.option("--target", "target", required=True, help="target name or path")
@click.option("--webhook-url", required=True, help="App webhook sink URL (non-loopback)")
@click.option("--port", default=8765, show_default=True, help="local callback port")
@click.option("--exchange", "code", default=None, help="exchange a manifest code for the App credentials")
@_handled
def app_manifest(target: str, webhook_url: str, port: int, code: str | None) -> None:
    """Create the e2e GitHub App from a manifest, or exchange the returned code."""
    from otterdog_e2e.appmanifest import exchange_code

    context = _context(target, make_dirs=False)
    loaded = context.load_target()
    if _is_loopback_url(webhook_url):
        raise click.UsageError("--webhook-url must not be a loopback URL (deliveries reach the webapp via the relay)")
    if code is None:
        context.verify(require_marker=True, check_identities=False)
        code = ManifestFlow(loaded, webhook_url=webhook_url, port=port).run()
    else:
        REDACTOR.add(code)
    result = exchange_code(code, out_dir=app_credentials_dir(loaded, context.environ))
    _echo(app_instructions(loaded, result, context.environ))
