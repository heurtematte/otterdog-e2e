"""The only GitHub HTTP client of the harness (SPEC 9.1).

Error semantics shared by every GitHub read helper (SPEC 4): single-object lookups return ``None`` on 404, list lookups
return ``[]`` on 403/404 and record the status in ``unavailable``; every other non-2xx raises ``GitHubError``.

Write guards (SPEC 5.2): absolute URLs must start with https://api.github.com/; ``read_only`` clients may only GET (and
POST /graphql queries); with ``write_scope`` non-GET requests are limited to the WRITE_PATH_PREFIXES of the verified org
(``/orgs/{login}`` itself included, for PATCH /orgs/{org}). Without ``write_scope`` a client may only mint App tokens
(``/app/installations/<id>/access_tokens``), convert App manifests (``/app-manifests/<code>/conversions``) and run
GraphQL queries: every other write needs a VerifiedOrg (SPEC 5.1).

Resilience: GET responses carrying an ETag are cached in memory and revalidated with ``If-None-Match`` (a 304 does not
count against the primary rate limit); rate-limited requests (403/429) are retried for every method; connection errors
and 502/503/504 only for GET/HEAD/PUT/DELETE and GraphQL queries; mutating calls are paced ``min_write_interval`` apart.

Mutating calls never follow redirects: GitHub redirects requests for a renamed or transferred repository (301/307) to
``/repositories/<id>``, which could be outside the write scope; the 3xx answer surfaces as a GitHubError (with its
Location) instead. Reads (GraphQL queries included) follow redirects, e.g. to a renamed branch.
"""

from __future__ import annotations

import email.utils
import json as jsonlib
import logging
import re
import threading
import time
import urllib.parse
from collections import OrderedDict
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import requests
from requests.structures import CaseInsensitiveDict

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.safety import VerifiedOrg

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
API_VERSION = "2022-11-28"
DEFAULT_HEADERS: Mapping[str, str] = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": API_VERSION,
    "X-Github-Next-Global-ID": "1",
}
# response headers kept on GitHubError for diagnostics (SSO authorization URL, required permissions / scopes, the
# target of a redirect that a write did not follow)
DIAGNOSTIC_HEADERS = (
    "X-GitHub-SSO",
    "X-Accepted-GitHub-Permissions",
    "X-Accepted-OAuth-Scopes",
    "X-GitHub-Request-Id",
    "Location",
)
RATE_HEADERS = (
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
    "X-RateLimit-Resource",
    "Retry-After",
)
# non-GET path prefixes allowed with write_scope; "{login}" is the verified org login, "{id}" an installation id
WRITE_PATH_PREFIXES = (
    "/repos/{login}/",
    "/orgs/{login}/",
    "/app/installations/{id}/access_tokens",
    "/app-manifests/",
    "/user/memberships/orgs/{login}",
    "/graphql",
)
# org-agnostic writes allowed without write_scope (App authentication flows only)
UNSCOPED_WRITE_PATTERNS = (
    re.compile(r"^/app/installations/\d+/access_tokens$"),
    re.compile(r"^/app-manifests/[^/]+/conversions$"),
)
RETRYABLE_STATUSES = frozenset({502, 503, 504})
IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "PUT", "DELETE"})
READ_METHODS = frozenset({"GET", "HEAD"})
NO_CACHE_PATHS = frozenset({"/rate_limit"})  # always fetched fresh (and never counted)
RATE_LIMIT_MAX_WAIT = 300.0  # cap of any rate-limit sleep (retry-after or reset)
SECONDARY_BACKOFF = (60.0, 120.0, 240.0)  # waits for rate limits without retry-after / reset information
CONNECTION_BACKOFF = (1.0, 2.0, 4.0, 8.0)
RATE_LIMIT_MARKERS = ("rate limit", "abuse detection")
ETAG_CACHE_ENTRIES = 2048
ETAG_CACHE_MAX_BYTES = 5 * 1024 * 1024
ERROR_BODY_MAX = 64 * 1024

_GRAPHQL_STRINGS_RE = re.compile(r'"""[\s\S]*?"""|"(?:\\.|[^"\\])*"')
_GRAPHQL_COMMENT_RE = re.compile(r"#[^\n]*")
_GRAPHQL_TOKEN_RE = re.compile(r"[{}]|[_A-Za-z][_0-9A-Za-z]*")


class GitHubError(RuntimeError):
    """A GitHub API call answered with an unexpected status (body, url and headers are redacted)."""

    def __init__(
        self, status: int, method: str, url: str, body: str = "", headers: Mapping[str, str] | None = None
    ) -> None:
        """Store redacted request/response details and build a short message (with SSO/permission hints)."""
        self.status = status
        self.method = method
        self.url = REDACTOR(url)
        self.body = REDACTOR(body)
        self.headers: dict[str, str] = {key: REDACTOR(value) for key, value in (headers or {}).items()}
        super().__init__(f"{method} {self.url} -> {status}: {self.body[:500]}{self._hints()}")

    def _hints(self) -> str:
        """Remediation hints derived from the diagnostic headers."""
        lowered = {key.lower(): value for key, value in self.headers.items()}
        hints = []
        if "x-github-sso" in lowered:
            hints.append("SAML SSO: the token is not authorized for this organization")
        if lowered.get("x-accepted-github-permissions"):
            hints.append(f"required permissions: {lowered['x-accepted-github-permissions']}")
        if "x-accepted-oauth-scopes" in lowered:
            hints.append(f"accepted scopes: {lowered['x-accepted-oauth-scopes'] or '(none)'}")
        if 300 <= self.status < 400:
            hints.append(f"redirect to {lowered.get('location') or '?'} not followed (writes never follow redirects)")
        return f" [{'; '.join(hints)}]" if hints else ""


@dataclass
class _CachedResponse:
    """A 200 GET response kept for ETag revalidation."""

    etag: str
    status: int
    content: bytes
    headers: dict[str, str]
    encoding: str | None


def is_graphql_query(document: str) -> bool:
    """True for a read-only GraphQL document: starts with ``query`` or ``{`` and defines no mutation/subscription."""
    text = _GRAPHQL_COMMENT_RE.sub("", _GRAPHQL_STRINGS_RE.sub('""', document))
    if not text.lstrip().startswith(("query", "{")):
        return False
    depth = 0
    for match in _GRAPHQL_TOKEN_RE.finditer(text):
        word = match.group(0)
        if word == "{":
            depth += 1
        elif word == "}":
            depth -= 1
        elif depth == 0 and word in ("mutation", "subscription"):
            return False
    return True


def _graphql_document(body: Any) -> str | None:
    """The ``query`` of a GraphQL request body, if any."""
    if isinstance(body, Mapping) and isinstance(body.get("query"), str):
        return str(body["query"])
    return None


def _int(value: str | None) -> int | None:
    """Parse an integer header value (None when absent or malformed)."""
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


class GitHubHttp:
    """requests-based client: retries, conditional GET cache, pagination, GraphQL and the SPEC 5.2 write guards.

    ``token_provider`` (attribute, default None) may be set to a callable returning the current token; it is called
    for every request (used by AppAuth for JWTs and installation tokens that rotate).
    """

    token_provider: Callable[[], str] | None = None

    def __init__(
        self,
        token: str | None,
        *,
        base_url: str = GITHUB_API,
        auth_scheme: str = "Bearer",
        user_agent: str = "otterdog-e2e",
        timeout: float = 30.0,
        session: requests.Session | None = None,
        max_retries: int = 4,
        sleep: Callable[[float], None] = time.sleep,
        write_scope: VerifiedOrg | None = None,
        read_only: bool = False,
        min_write_interval: float = 1.0,
        identity: str = "anonymous",
    ) -> None:
        """Configure the client (session.trust_env is forced to False); the token is registered with REDACTOR."""
        self.token = token
        self.base_url = base_url.rstrip("/")
        self.auth_scheme = auth_scheme
        self.user_agent = user_agent
        self.timeout = timeout
        self.session = session if session is not None else requests.Session()
        self.session.trust_env = False
        self.max_retries = max_retries
        self.sleep = sleep
        self.write_scope = write_scope
        self.read_only = read_only
        self.min_write_interval = min_write_interval
        self.identity = identity
        # extra precondition of every write (E2EContext: refuses once this session's org lease was lost, DESTR-03)
        self.write_guard: Callable[[], None] | None = None
        self.unavailable: dict[str, int] = {}
        self.last_rate: dict[str, Any] | None = None
        self.last_date: datetime | None = None  # GitHub's Date header of the last response
        self.last_graphql_errors: list[Any] = []
        self._rate: dict[str, dict[str, Any]] = {}
        self._etags: OrderedDict[str, _CachedResponse] = OrderedDict()
        self._lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._last_write: float | None = None
        if write_scope is not None and self.base_url != GITHUB_API:
            raise SafetyError(f"write-scoped GitHub clients must use {GITHUB_API} (got {self.base_url})")
        REDACTOR.add(token)

    # --- request plumbing ---------------------------------------------------------------------------------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        expected: Sequence[int] = (200, 201, 202, 204),
        allow: Sequence[int] = (),
    ) -> requests.Response:
        """Send one request with retries/guards; return the response if its status is in expected or allow."""
        method = method.upper()
        url = self._prepare_url(self._absolute_url(path), params)
        api_path = self._api_path(url)
        self._guard(method, api_path, json)
        request_headers = self._headers(headers)
        cache_key = self._cache_key(method, api_path, url, request_headers)
        cached = self._cache_lookup(cache_key)
        if cached is not None:
            request_headers["If-None-Match"] = cached.etag
        response = self._send(method, url, api_path, json, data, request_headers, cached)
        if cache_key is not None:
            self._cache_store(cache_key, response)
        rate_limited = self._rate_limit_delay(response, 0) is not None  # never "allowed" (e.g. as unavailable)
        if not rate_limited and (response.status_code in expected or response.status_code in allow):
            return response
        raise self._error(method, url, response)

    def _absolute_url(self, path: str) -> str:
        """Join ``path`` to base_url; absolute URLs must point at the GitHub REST API."""
        if path.startswith(("http://", "https://")):
            if not path.startswith(GITHUB_API + "/"):
                raise SafetyError(f"refusing a request outside {GITHUB_API}: {REDACTOR(path)}")
            return path
        return self.base_url + (path if path.startswith("/") else "/" + path)

    @staticmethod
    def _prepare_url(url: str, params: Mapping[str, Any] | None) -> str:
        """URL with the query parameters encoded (stable for the ETag cache key)."""
        if not params:
            return url
        prepared = requests.Request("GET", url, params=dict(params)).prepare().url
        return prepared or url

    @staticmethod
    def _api_path(url: str) -> str:
        """Decoded path of an API URL; dot segments and backslashes are refused (they could escape the write scope)."""
        path = urllib.parse.unquote(urllib.parse.urlsplit(url).path)
        segments = path.split("/")
        if "\\" in path or any(segment in (".", "..") for segment in segments):
            raise SafetyError(f"refusing a GitHub API path with dot segments: {REDACTOR(path)}")
        return path

    def _guard(self, method: str, api_path: str, body: Any) -> None:
        """SPEC 5.2: read-only clients only read; writes need a write scope covering ``api_path``."""
        if method in READ_METHODS:
            return
        document = _graphql_document(body) if api_path == "/graphql" else None
        if method == "POST" and document is not None and is_graphql_query(document):
            return
        if self.read_only:
            raise SafetyError(f"read-only GitHub client ({self.identity}) refuses {method} {api_path}")
        if self.write_scope is None:
            if any(pattern.match(api_path) for pattern in UNSCOPED_WRITE_PATTERNS):
                return
            raise SafetyError(f"GitHub client ({self.identity}) without write_scope refuses {method} {api_path}")
        if not self._in_write_scope(api_path):
            raise SafetyError(
                f"{method} {api_path} is outside the write scope of org {self.write_scope.login!r} ({self.identity})"
            )
        if self.write_guard is not None:
            self.write_guard()

    def _in_write_scope(self, api_path: str) -> bool:
        """True when ``api_path`` is one of WRITE_PATH_PREFIXES for the verified org (logins compare case-insensitively)."""
        if self.write_scope is None:
            return False
        login = re.escape(self.write_scope.login.lower())
        patterns = (
            rf"^/repos/{login}/[^/]+(/.*)?$",
            rf"^/orgs/{login}(/.*)?$",
            r"^/app/installations/\d+/access_tokens$",
            r"^/app-manifests/[^/]+/conversions$",
            rf"^/user/memberships/orgs/{login}$",
            r"^/graphql$",
        )
        lowered = api_path.lower()
        return any(re.match(pattern, lowered) for pattern in patterns)

    def _headers(self, extra: Mapping[str, str] | None) -> dict[str, str]:
        """Default API headers, User-Agent, Authorization (static tokens; provider tokens are set per attempt)."""
        headers = {**DEFAULT_HEADERS, "User-Agent": self.user_agent}
        if self.token and self.token_provider is None:
            headers["Authorization"] = f"{self.auth_scheme} {self.token}"
        headers.update(extra or {})
        return headers

    def _refresh_auth(self, headers: dict[str, str]) -> None:
        """Set the current provider token (a JWT may rotate during a long rate-limit wait)."""
        if self.token_provider is None or any(name.lower() == "authorization" for name in headers):
            return
        token = self.token_provider()
        if token:
            headers["Authorization"] = f"{self.auth_scheme} {token}"

    def _is_write(self, method: str, api_path: str, body: Any) -> bool:
        """True for mutating calls (GraphQL queries are reads)."""
        if method in READ_METHODS:
            return False
        document = _graphql_document(body) if api_path == "/graphql" else None
        return not (method == "POST" and document is not None and is_graphql_query(document))

    def _pace(self) -> None:
        """Keep at least min_write_interval seconds between mutating calls of this client (all threads)."""
        if self.min_write_interval <= 0:
            return
        with self._write_lock:
            if self._last_write is not None:
                wait = self.min_write_interval - (time.monotonic() - self._last_write)
                if wait > 0:
                    self.sleep(wait)
            self._last_write = time.monotonic()

    def _send(
        self,
        method: str,
        url: str,
        api_path: str,
        json: Any,
        data: Any,
        headers: dict[str, str],
        cached: _CachedResponse | None,
    ) -> requests.Response:
        """Perform the call, retrying rate limits (all methods) and transient failures (idempotent calls only); writes
        never follow redirects (a redirect could leave the write scope)."""
        write = self._is_write(method, api_path, json)
        retry_transient = not write or method in IDEMPOTENT_METHODS
        attempt = 0
        while True:
            if write:
                self._pace()
            attempt_headers = dict(headers)
            self._refresh_auth(attempt_headers)
            try:
                response = self.session.request(
                    method,
                    url,
                    json=json,
                    data=data,
                    headers=attempt_headers,
                    timeout=self.timeout,
                    allow_redirects=not write,
                )
            except (requests.ConnectionError, requests.Timeout, requests.exceptions.ChunkedEncodingError) as exc:
                if not retry_transient or attempt >= self.max_retries:
                    raise
                delay = CONNECTION_BACKOFF[min(attempt, len(CONNECTION_BACKOFF) - 1)]
                logger.warning("%s %s failed (%s); retrying in %.0f s", method, api_path, type(exc).__name__, delay)
                self.sleep(delay)
                attempt += 1
                continue
            self._record_rate(response)
            self._record_date(response)
            if response.status_code == 304 and cached is not None:
                response = self._from_cache(cached, response)
            self._log(method, api_path, response)
            retry_in = self._retry_delay(response, attempt, retry_transient)
            if retry_in is None or attempt >= self.max_retries:
                return response
            logger.warning(
                "%s %s -> %s (%s): retrying in %.0f s", method, api_path, response.status_code, self.identity, retry_in
            )
            self.sleep(retry_in)
            attempt += 1

    def _retry_delay(self, response: requests.Response, attempt: int, retry_transient: bool) -> float | None:
        """Seconds to wait before retrying ``response`` (None = do not retry)."""
        rate_delay = self._rate_limit_delay(response, attempt)
        if rate_delay is not None:
            return rate_delay
        if retry_transient and response.status_code in RETRYABLE_STATUSES:
            return CONNECTION_BACKOFF[min(attempt, len(CONNECTION_BACKOFF) - 1)]
        return None

    @staticmethod
    def _rate_limit_delay(response: requests.Response, attempt: int) -> float | None:
        """Wait for a rate-limited 403/429: retry-after, else until reset (cap 300 s), else 60/120/240 s."""
        if response.status_code not in (403, 429):
            return None
        headers = response.headers
        retry_after = headers.get("Retry-After")
        if retry_after is not None and retry_after.strip().isdigit():
            return min(float(retry_after), RATE_LIMIT_MAX_WAIT)
        if headers.get("X-RateLimit-Remaining") == "0":
            reset = _int(headers.get("X-RateLimit-Reset"))
            if reset is not None:
                return min(max(reset - time.time(), 0.0) + 1.0, RATE_LIMIT_MAX_WAIT)
        text = response.text.lower() if response.content else ""
        if response.status_code == 429 or any(marker in text for marker in RATE_LIMIT_MARKERS):
            return SECONDARY_BACKOFF[min(attempt, len(SECONDARY_BACKOFF) - 1)]
        return None

    def _log(self, method: str, api_path: str, response: requests.Response) -> None:
        """DEBUG log of one exchange (redacted)."""
        if logger.isEnabledFor(logging.DEBUG):
            remaining = response.headers.get("X-RateLimit-Remaining", "?")
            cached = " (cached)" if getattr(response, "from_cache", False) else ""
            logger.debug(
                "%s %s -> %s%s [%s, %s remaining]",
                method,
                REDACTOR(api_path),
                response.status_code,
                cached,
                self.identity,
                remaining,
            )

    def _error(self, method: str, url: str, response: requests.Response) -> GitHubError:
        """GitHubError for an unexpected response (diagnostic and rate-limit headers only)."""
        wanted = DIAGNOSTIC_HEADERS + RATE_HEADERS
        headers = {name: response.headers[name] for name in wanted if name in response.headers}
        body = response.text[:ERROR_BODY_MAX] if response.content else ""
        return GitHubError(response.status_code, method, response.url or url, body, headers)

    def _record_date(self, response: requests.Response) -> None:
        """Remember GitHub's clock (the ``Date`` header) of the last response (``last_date``: compare with GitHub
        timestamps such as a delivery's delivered_at without trusting the local clock)."""
        value = response.headers.get("Date")
        if not value:
            return
        try:
            parsed = email.utils.parsedate_to_datetime(value)
        except (TypeError, ValueError):
            return
        self.last_date = parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)

    # --- rate limits --------------------------------------------------------------------------------------------
    def _record_rate(self, response: requests.Response) -> None:
        """Remember the x-ratelimit-* headers of a response per resource."""
        headers = response.headers
        if "X-RateLimit-Remaining" not in headers:
            return
        resource = headers.get("X-RateLimit-Resource", "core")
        snapshot = {
            "resource": resource,
            "limit": _int(headers.get("X-RateLimit-Limit")),
            "remaining": _int(headers.get("X-RateLimit-Remaining")),
            "used": _int(headers.get("X-RateLimit-Used")),
            "reset": _int(headers.get("X-RateLimit-Reset")),
            "identity": self.identity,
        }
        with self._lock:
            self._rate[resource] = snapshot
            self.last_rate = snapshot

    # --- conditional GET cache ----------------------------------------------------------------------------------
    @staticmethod
    def _cache_key(method: str, api_path: str, url: str, headers: Mapping[str, str]) -> str | None:
        """Key of a cacheable GET (None for other requests, /rate_limit and caller-conditional requests)."""
        if method != "GET" or api_path in NO_CACHE_PATHS:
            return None
        if any(name.lower() in ("if-none-match", "if-modified-since") for name in headers):
            return None
        return f"{headers.get('Accept', '')}|{url}"

    def _cache_lookup(self, key: str | None) -> _CachedResponse | None:
        """Cached response for ``key`` (refreshing its LRU position)."""
        if key is None:
            return None
        with self._lock:
            cached = self._etags.get(key)
            if cached is not None:
                self._etags.move_to_end(key)
            return cached

    def _cache_store(self, key: str, response: requests.Response) -> None:
        """Keep a 200 response with an ETag (bounded LRU); drop the entry on 404."""
        if getattr(response, "from_cache", False):
            return
        etag = response.headers.get("ETag")
        with self._lock:
            if response.status_code == 404:
                self._etags.pop(key, None)
                return
            if response.status_code != 200 or not etag or len(response.content) > ETAG_CACHE_MAX_BYTES:
                return
            self._etags[key] = _CachedResponse(
                etag, response.status_code, response.content, dict(response.headers), response.encoding
            )
            self._etags.move_to_end(key)
            while len(self._etags) > ETAG_CACHE_ENTRIES:
                self._etags.popitem(last=False)

    @staticmethod
    def _from_cache(cached: _CachedResponse, fresh: requests.Response) -> requests.Response:
        """A 200 response rebuilt from the cache, with the fresh rate-limit/date headers of the 304."""
        response = requests.Response()
        response.status_code = cached.status
        response._content = cached.content
        response.encoding = cached.encoding
        headers = CaseInsensitiveDict(cached.headers)
        for name, value in fresh.headers.items():
            if name.lower().startswith("x-ratelimit") or name.lower() in ("date", "etag"):
                headers[name] = value
        response.headers = headers
        response.url = fresh.url
        response.request = fresh.request
        response.reason = "OK (cached)"
        response.from_cache = True  # type: ignore[attr-defined]
        return response

    # --- convenience methods ------------------------------------------------------------------------------------
    @staticmethod
    def _decode(response: requests.Response) -> Any:
        """JSON body, raw text for non-JSON bodies, None for empty bodies."""
        if response.status_code == 204 or not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return response.text

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        allow_404: bool = False,
    ) -> Any:
        """GET and decode JSON (None on 404 when allow_404)."""
        response = self.request("GET", path, params=params, headers=headers, allow=(404,) if allow_404 else ())
        return None if response.status_code == 404 else self._decode(response)

    def paginate(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        per_page: int = 100,
        item_key: str | None = None,
        max_pages: int = 50,
        allow_unavailable: bool = False,
    ) -> list[Any]:
        """Follow Link rel=next; item_key selects the list in wrapped responses; 403/404 -> [] when allow_unavailable."""
        allow = (403, 404) if allow_unavailable else ()
        url: str = path
        query: Mapping[str, Any] | None = {**(params or {}), "per_page": per_page}
        items: list[Any] = []
        for _ in range(max_pages):
            response = self.request("GET", url, params=query, allow=allow)
            if response.status_code in (403, 404):
                self.unavailable[path] = response.status_code
                return []
            items.extend(self._page_items(self._decode(response), item_key, path))
            next_url = response.links.get("next", {}).get("url")
            if not next_url:
                return items
            url, query = next_url, None
        logger.warning("%s: stopped after %d pages (%d items)", REDACTOR(path), max_pages, len(items))
        return items

    @staticmethod
    def _page_items(body: Any, item_key: str | None, path: str) -> list[Any]:
        """Items of one page: the list itself, body[item_key], or the only list of a ``{total_count, <list>}`` body."""
        if body is None:
            return []
        if isinstance(body, list):
            return body
        if isinstance(body, dict):
            if item_key is not None:
                return list(body.get(item_key) or [])
            lists = [value for key, value in body.items() if isinstance(value, list) and key != "total_count"]
            if len(lists) == 1:
                return list(lists[0])
        raise TypeError(f"{path}: cannot find the items of a {type(body).__name__} page (item_key={item_key!r})")

    def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        """POST and decode JSON (None for empty bodies)."""
        return self._decode(self.request("POST", path, json=json, **kw))

    def put(self, path: str, json: Any = None, **kw: Any) -> Any:
        """PUT and decode JSON (None for empty bodies)."""
        return self._decode(self.request("PUT", path, json=json, **kw))

    def patch(self, path: str, json: Any = None, **kw: Any) -> Any:
        """PATCH and decode JSON (None for empty bodies)."""
        return self._decode(self.request("PATCH", path, json=json, **kw))

    def delete(self, path: str, *, allow_404: bool = True, **kw: Any) -> None:
        """DELETE (404 ignored when allow_404)."""
        allow = tuple(kw.pop("allow", ())) + ((404,) if allow_404 else ())
        self.request("DELETE", path, allow=allow, **kw)

    def graphql(self, query: str, variables: Mapping[str, Any] | None = None, *, allow_errors: bool = False) -> dict:
        """POST /graphql and return ``data``; GitHubError on ``errors`` unless allow_errors (RATE_LIMITED is retried)."""
        payload = {"query": query, "variables": dict(variables or {})}
        attempt = 0
        while True:
            response = self.request("POST", "/graphql", json=payload)
            body = self._decode(response)
            body = body if isinstance(body, dict) else {}
            errors = list(body.get("errors") or [])
            if not errors or not self._graphql_rate_limited(errors) or attempt >= self.max_retries:
                break
            delay = self._graphql_rate_delay(attempt)
            logger.warning("GraphQL rate limited (%s): retrying in %.0f s", self.identity, delay)
            self.sleep(delay)
            attempt += 1
        self.last_graphql_errors = errors
        if errors and not allow_errors:
            raise GitHubError(response.status_code, "POST", response.url, jsonlib.dumps(errors))
        if errors:
            logger.debug("GraphQL errors ignored (%s): %s", self.identity, REDACTOR(jsonlib.dumps(errors))[:500])
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _graphql_rate_limited(errors: Sequence[Any]) -> bool:
        """True when a GraphQL error list reports a rate limit."""
        return any(isinstance(error, dict) and error.get("type") == "RATE_LIMITED" for error in errors)

    def _graphql_rate_delay(self, attempt: int) -> float:
        """Wait until the graphql budget resets (cap 300 s), else the secondary backoff."""
        snapshot = self._rate.get("graphql") or {}
        reset = snapshot.get("reset")
        if snapshot.get("remaining") == 0 and reset is not None:
            return min(max(reset - time.time(), 0.0) + 1.0, RATE_LIMIT_MAX_WAIT)
        return SECONDARY_BACKOFF[min(attempt, len(SECONDARY_BACKOFF) - 1)]

    def oauth_scopes(self) -> set[str] | None:
        """Classic token scopes (X-OAuth-Scopes of GET /rate_limit); None for fine-grained or App tokens."""
        response = self.request("GET", "/rate_limit")
        header = response.headers.get("X-OAuth-Scopes")
        if header is None:
            return None
        return {scope.strip() for scope in header.split(",") if scope.strip()}

    def rate_snapshot(self) -> dict[str, Any]:
        """Last x-ratelimit-* headers seen, per resource."""
        with self._lock:
            return {resource: dict(snapshot) for resource, snapshot in self._rate.items()}

    def rate_limit(self) -> dict:
        """GET /rate_limit (does not count against the primary limit)."""
        body = self.get("/rate_limit")
        return body if isinstance(body, dict) else {}
