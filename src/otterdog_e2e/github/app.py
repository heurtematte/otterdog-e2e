"""GitHub App authentication: JWTs, installation tokens and the App webhook delivery log (SPEC 9.2).

Every JWT and installation token minted here is registered with REDACTOR. No update_hook_config / redeliver in v1.
The JWT-authenticated client is created once and reused (one requests.Session, ETag cache, rate-limit headers); its
token is fetched per request, so a rotated JWT or installation token is picked up transparently.
"""

from __future__ import annotations

import logging
import threading
import time
import urllib.parse
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import jwt as pyjwt
import requests

from otterdog_e2e.github.http import GITHUB_API, GitHubHttp
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import AppCredentials

logger = logging.getLogger(__name__)

JWT_BACKDATE = 60  # iat = now - 60 s
JWT_LIFETIME = 540  # exp = now + 540 s
TOKEN_REFRESH_MARGIN = 60  # JWTs and installation tokens are renewed 60 s before they expire
DELIVERIES_MAX_PER_PAGE = 100


def parse_github_time(value: str) -> datetime:
    """Parse a GitHub ISO-8601 timestamp (``Z`` suffix) as an aware UTC datetime."""
    return datetime.fromisoformat(value)


def cursor_from_link(url: str | None) -> str | None:
    """The ``cursor`` query parameter of a Link rel=next URL (None at the last page)."""
    if not url:
        return None
    values = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query).get("cursor")
    return values[0] if values else None


class AppAuth:
    """Authenticates as the e2e GitHub App (RS256 JWT) and as its installations."""

    def __init__(
        self,
        creds: AppCredentials,
        *,
        base_url: str = GITHUB_API,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        """Bind the App credentials; nothing is requested yet."""
        self.creds = creds
        self.base_url = base_url
        self.session = session if session is not None else requests.Session()
        self.session.trust_env = False
        self.clock = clock
        self._jwt: str | None = None
        self._jwt_expires = 0.0
        self._tokens: dict[int, tuple[str, float]] = {}
        self._app: dict[str, Any] | None = None
        self._app_http: GitHubHttp | None = None
        self._jwt_lock = threading.Lock()
        self._token_lock = threading.Lock()
        REDACTOR.add(creds.private_key_pem, creds.webhook_secret)

    def jwt(self) -> str:
        """RS256 JWT (iat=now-60, exp=now+540, iss=app_id), reused until 60 s before exp; registered with REDACTOR."""
        with self._jwt_lock:
            now = self.clock()
            if self._jwt is None or now >= self._jwt_expires - TOKEN_REFRESH_MARGIN:
                issued, expires = int(now) - JWT_BACKDATE, int(now) + JWT_LIFETIME
                claims = {"iat": issued, "exp": expires, "iss": self.creds.app_id}
                token = pyjwt.encode(claims, self.creds.private_key_pem, algorithm="RS256")
                REDACTOR.add(token, variants=False)
                self._jwt, self._jwt_expires = token, float(expires)
                logger.debug("minted a JWT for app %s (expires in %d s)", self.creds.app_id, JWT_LIFETIME)
            return self._jwt

    def app_http(self) -> GitHubHttp:
        """GitHubHttp authenticated with the current JWT (read endpoints of /app)."""
        if self._app_http is None:
            http = GitHubHttp(
                None, base_url=self.base_url, session=self.session, min_write_interval=0.0, identity="app-jwt"
            )
            http.token_provider = self.jwt
            self._app_http = http
        return self._app_http

    def get_app(self, *, refresh: bool = False) -> dict[str, Any]:
        """GET /app (cached; ``refresh`` reads it again, e.g. for safety.verify_app before each webapp start)."""
        if self._app is None or refresh:
            self._app = dict(self.app_http().get("/app") or {})
        return self._app

    def installations(self) -> list[dict[str, Any]]:
        """Every installation of the App (GET /app/installations with the JWT, all pages)."""
        return [dict(item) for item in self.app_http().paginate("/app/installations") if isinstance(item, dict)]

    @property
    def slug(self) -> str:
        """App slug (from the credentials, else GET /app)."""
        return self.creds.slug or str(self.get_app()["slug"])

    @property
    def bot_login(self) -> str:
        """Login of the App's bot user: ``<slug>[bot]``."""
        return f"{self.slug}[bot]"

    def installation_for_org(self, org: str) -> dict[str, Any] | None:
        """GET /orgs/{org}/installation with the JWT (None when not installed)."""
        org_path = urllib.parse.quote(org, safe="")
        return self.app_http().get(f"/orgs/{org_path}/installation", allow_404=True)

    def installation_token(self, installation_id: int) -> str:
        """POST /app/installations/{id}/access_tokens, cached until expires_at - 60 s; registered with REDACTOR."""
        with self._token_lock:
            cached = self._tokens.get(installation_id)
            if cached is not None and self.clock() < cached[1] - TOKEN_REFRESH_MARGIN:
                return cached[0]
            body = self.app_http().post(f"/app/installations/{int(installation_id)}/access_tokens")
            token = str(body["token"])
            expires = parse_github_time(str(body["expires_at"])).timestamp()
            REDACTOR.add(token)
            self._tokens[installation_id] = (token, expires)
            logger.debug("minted an installation token for installation %s", installation_id)
            return token

    def installation_http(self, installation_id: int, verified: VerifiedOrg) -> GitHubHttp:
        """GitHubHttp authenticated as the installation, write-scoped to the verified org."""
        http = GitHubHttp(
            None,
            base_url=self.base_url,
            session=self.session,
            write_scope=verified,
            identity=f"app-installation-{installation_id}",
        )
        http.token_provider = lambda: self.installation_token(installation_id)
        return http

    def hook_config(self) -> dict[str, Any]:
        """GET /app/hook/config: url, content_type, secret (masked), insecure_ssl (there is no 'active' field)."""
        return dict(self.app_http().get("/app/hook/config") or {})

    def list_deliveries(
        self, *, per_page: int = 100, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page of GET /app/hook/deliveries (newest first) and the cursor of the next page."""
        params: dict[str, Any] = {"per_page": max(1, min(int(per_page), DELIVERIES_MAX_PER_PAGE))}
        if cursor:
            params["cursor"] = cursor
        response = self.app_http().request("GET", "/app/hook/deliveries", params=params)
        body = response.json() if response.content else []
        items = [item for item in body if isinstance(item, dict)] if isinstance(body, list) else []
        return items, cursor_from_link(response.links.get("next", {}).get("url"))

    def get_delivery(self, delivery_id: int) -> dict[str, Any]:
        """GET /app/hook/deliveries/{id}: includes request.headers and request.payload (both nullable)."""
        return dict(self.app_http().get(f"/app/hook/deliveries/{int(delivery_id)}") or {})

    @property
    def rate_remaining(self) -> int | None:
        """x-ratelimit-remaining of the last JWT-authenticated response (None before the first call)."""
        if self._app_http is None or self._app_http.last_rate is None:
            return None
        remaining = self._app_http.last_rate.get("remaining")
        return remaining if isinstance(remaining, int) else None

    @property
    def rate_reset(self) -> datetime | None:
        """X-RateLimit-Reset of the last JWT-authenticated response as an aware UTC datetime (None before the first
        call or without the header): when the App budget seen by rate_remaining is refilled."""
        if self._app_http is None or self._app_http.last_rate is None:
            return None
        reset = self._app_http.last_rate.get("reset")
        if not isinstance(reset, int) or isinstance(reset, bool):
            return None
        return datetime.fromtimestamp(reset, UTC)
