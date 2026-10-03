"""GitHubHttp: headers, pagination, ETag cache, retries, pacing, write guards and errors (SPEC 9.1, 5.2)."""

from __future__ import annotations

import json
import time
from collections.abc import Iterator

import pytest
import requests
import responses
from responses import matchers

from otterdog_e2e.github.http import GITHUB_API, GitHubError, GitHubHttp, is_graphql_query
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FAKE_ORG, make_verified_org

TOKEN = "ghp_" + "T0kenForHttpTests0123456789abcdefghij"
ORG_URL = f"{GITHUB_API}/orgs/{FAKE_ORG}"


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked api.github.com (unregistered requests fail)."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


@pytest.fixture
def sleeps() -> list[float]:
    """Recorded sleep durations."""
    return []


def make_http(sleeps: list[float], **kw: object) -> GitHubHttp:
    """A client with a recording sleep and no write pacing (unless overridden)."""
    options: dict = {"sleep": sleeps.append, "min_write_interval": 0.0, "identity": "test", **kw}
    return GitHubHttp(TOKEN, **options)


# --- headers, decoding, errors -------------------------------------------------------------------------------------
def test_default_headers_auth_and_trust_env(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """API version, global-id, Accept, User-Agent and Bearer headers; the session ignores proxy env vars."""
    api.add(responses.GET, ORG_URL, json={"login": FAKE_ORG})
    http = make_http(sleeps)
    assert http.get(f"/orgs/{FAKE_ORG}") == {"login": FAKE_ORG}
    headers = api.calls[0].request.headers
    assert headers["Accept"] == "application/vnd.github+json"
    assert headers["X-GitHub-Api-Version"] == "2022-11-28"
    assert headers["X-Github-Next-Global-ID"] == "1"
    assert headers["Authorization"] == f"Bearer {TOKEN}"
    assert headers["User-Agent"] == "otterdog-e2e"
    assert http.session.trust_env is False
    assert TOKEN in REDACTOR.literals


def test_anonymous_client_sends_no_authorization(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """token None => no Authorization header."""
    api.add(responses.GET, f"{GITHUB_API}/repos/eclipse-csi/otterdog", json={"name": "otterdog"})
    http = GitHubHttp(None, sleep=sleeps.append)
    assert http.get("/repos/eclipse-csi/otterdog")["name"] == "otterdog"
    assert "Authorization" not in api.calls[0].request.headers


def test_get_allow_404_and_error_details(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """404 -> None with allow_404, else a redacted GitHubError keeping SSO/permission headers."""
    url = f"{GITHUB_API}/repos/{FAKE_ORG}/missing"
    headers = {
        "X-GitHub-SSO": "required; url=https://github.com/orgs/x/sso?authorization_request=abc",
        "X-Accepted-GitHub-Permissions": "contents=read",
        "X-GitHub-Request-Id": "ABCD:1234",
        "X-Unrelated": "dropped",
    }
    api.add(responses.GET, url, status=404, json={"message": f"Not Found {TOKEN}"}, headers=headers)
    http = make_http(sleeps)
    assert http.get(f"/repos/{FAKE_ORG}/missing", allow_404=True) is None
    with pytest.raises(GitHubError) as info:
        http.get(f"/repos/{FAKE_ORG}/missing")
    error = info.value
    assert error.status == 404 and error.method == "GET" and error.url == url
    assert TOKEN not in str(error) and TOKEN not in error.body
    assert error.headers["X-GitHub-SSO"].startswith("required")
    assert error.headers["X-Accepted-GitHub-Permissions"] == "contents=read"
    assert "X-Unrelated" not in error.headers
    assert "SAML SSO" in str(error) and "contents=read" in str(error)


def test_expected_and_allow(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Statuses outside expected+allow raise; allowed ones are returned."""
    api.add(responses.GET, f"{GITHUB_API}/x", status=409, json={"message": "Git Repository is empty."})
    http = make_http(sleeps)
    assert http.request("GET", "/x", allow=(409,)).status_code == 409
    with pytest.raises(GitHubError):
        http.request("GET", "/x")


def test_post_put_patch_delete_decode(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Write helpers decode JSON, return None for empty bodies; delete ignores 404 by default."""
    verified = make_verified_org()
    base = f"{GITHUB_API}/repos/{FAKE_ORG}/r"
    api.add(responses.POST, f"{base}/issues/1/comments", status=201, json={"id": 1})
    api.add(responses.PUT, f"{base}/topics", json={"names": ["a"]})
    api.add(responses.PATCH, base, json={"name": "r"})
    api.add(responses.DELETE, f"{base}/hooks/1", status=404, json={"message": "Not Found"})
    api.add(responses.DELETE, f"{base}/hooks/2", status=204)
    http = make_http(sleeps, write_scope=verified)
    assert http.post(f"/repos/{FAKE_ORG}/r/issues/1/comments", json={"body": "x"}) == {"id": 1}
    assert json.loads(api.calls[0].request.body or "{}") == {"body": "x"}
    assert http.put(f"/repos/{FAKE_ORG}/r/topics", json={"names": ["a"]}) == {"names": ["a"]}
    assert http.patch(f"/repos/{FAKE_ORG}/r", json={"description": "d"}) == {"name": "r"}
    http.delete(f"/repos/{FAKE_ORG}/r/hooks/1")
    http.delete(f"/repos/{FAKE_ORG}/r/hooks/2")
    with pytest.raises(GitHubError):
        api.add(responses.DELETE, f"{base}/hooks/3", status=404, json={"message": "Not Found"})
        http.delete(f"/repos/{FAKE_ORG}/r/hooks/3", allow_404=False)


# --- pagination ----------------------------------------------------------------------------------------------------
def test_paginate_follows_link_next_with_item_key(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """per_page is sent on the first page; rel=next URLs are followed; item_key unwraps the pages."""
    url = f"{ORG_URL}/actions/secrets"
    next_url = f"{url}?per_page=2&page=2"
    api.add(
        responses.GET,
        url,
        json={"total_count": 3, "secrets": [{"name": "A"}, {"name": "B"}]},
        headers={"Link": f'<{next_url}>; rel="next", <{next_url}>; rel="last"'},
        match=[matchers.query_param_matcher({"per_page": "2"})],
    )
    api.add(
        responses.GET,
        url,
        json={"total_count": 3, "secrets": [{"name": "C"}]},
        match=[matchers.query_param_matcher({"per_page": "2", "page": "2"})],
    )
    http = make_http(sleeps)
    items = http.paginate(f"/orgs/{FAKE_ORG}/actions/secrets", per_page=2, item_key="secrets")
    assert [item["name"] for item in items] == ["A", "B", "C"]
    assert len(api.calls) == 2


def test_paginate_lists_and_wrapped_bodies_and_max_pages(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Plain lists, auto-detected ``{total_count, <list>}`` bodies and the max_pages bound."""
    api.add(
        responses.GET, f"{ORG_URL}/hooks", json=[{"id": 1}], headers={"Link": f'<{ORG_URL}/hooks?page=2>; rel="next"'}
    )
    api.add(
        responses.GET,
        f"{GITHUB_API}/repos/{FAKE_ORG}/r/environments",
        json={"total_count": 1, "environments": [{"name": "e"}]},
    )
    http = make_http(sleeps)
    assert http.paginate(f"/orgs/{FAKE_ORG}/hooks", max_pages=1) == [{"id": 1}]
    assert http.paginate(f"/repos/{FAKE_ORG}/r/environments") == [{"name": "e"}]


def test_paginate_unavailable(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """403/404 -> [] and unavailable[path] with allow_unavailable; GitHubError otherwise."""
    api.add(responses.GET, f"{ORG_URL}/rulesets", status=403, json={"message": "Upgrade to GitHub Team"})
    http = make_http(sleeps)
    assert http.paginate(f"/orgs/{FAKE_ORG}/rulesets", allow_unavailable=True) == []
    assert http.unavailable == {f"/orgs/{FAKE_ORG}/rulesets": 403}
    with pytest.raises(GitHubError) as info:
        http.paginate(f"/orgs/{FAKE_ORG}/rulesets")
    assert info.value.status == 403
    assert sleeps == []  # a permission 403 is not a rate limit


# --- conditional GET cache -----------------------------------------------------------------------------------------
def test_etag_304_reuses_cached_body(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """The ETag of a 200 is revalidated with If-None-Match; a 304 returns the cached body with fresh rate headers."""
    url = f"{GITHUB_API}/repos/{FAKE_ORG}/r/pulls/1"
    api.add(
        responses.GET,
        url,
        json={"number": 1, "state": "open"},
        headers={"ETag": '"v1"', "X-RateLimit-Remaining": "4999"},
    )
    api.add(
        responses.GET,
        url,
        status=304,
        headers={"ETag": '"v1"', "X-RateLimit-Remaining": "4999", "X-RateLimit-Resource": "core"},
        match=[matchers.header_matcher({"If-None-Match": '"v1"'})],
    )
    http = make_http(sleeps)
    assert http.get(f"/repos/{FAKE_ORG}/r/pulls/1") == {"number": 1, "state": "open"}
    assert "If-None-Match" not in api.calls[0].request.headers
    response = http.request("GET", f"/repos/{FAKE_ORG}/r/pulls/1")
    assert response.status_code == 200 and response.json() == {"number": 1, "state": "open"}
    assert getattr(response, "from_cache", False) is True
    assert api.calls[1].request.headers["If-None-Match"] == '"v1"'
    assert http.rate_snapshot()["core"]["remaining"] == 4999


def test_etag_cache_keeps_link_header_for_pagination(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """A 304 page still yields its cached Link header, so pagination continues."""
    url, page2 = f"{ORG_URL}/teams", f"{ORG_URL}/teams?per_page=100&page=2"
    first = matchers.query_param_matcher({"per_page": "100"})
    second = matchers.query_param_matcher({"per_page": "100", "page": "2"})
    link = {"Link": f'<{page2}>; rel="next"'}
    api.add(responses.GET, url, json=[{"slug": "a"}], headers={"ETag": '"p1"', **link}, match=[first])
    api.add(responses.GET, url, json=[{"slug": "b"}], headers={"ETag": '"p2"'}, match=[second])
    http = make_http(sleeps)
    assert [t["slug"] for t in http.paginate(f"/orgs/{FAKE_ORG}/teams")] == ["a", "b"]
    api.replace(responses.GET, url, status=304, headers={"ETag": '"p1"'}, match=[first])
    api.add(responses.GET, url, status=304, headers={"ETag": '"p2"'}, match=[second])
    assert [t["slug"] for t in http.paginate(f"/orgs/{FAKE_ORG}/teams")] == ["a", "b"]
    assert [getattr(call.response, "status_code", None) for call in api.calls] == [200, 200, 304, 304]
    assert [call.request.headers.get("If-None-Match") for call in api.calls[2:]] == ['"p1"', '"p2"']


def test_rate_limit_endpoint_is_never_conditional(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """GET /rate_limit bypasses the ETag cache; oauth_scopes parses X-OAuth-Scopes."""
    body = {"resources": {"core": {"remaining": 4000}}, "rate": {"remaining": 4000}}
    api.add(
        responses.GET,
        f"{GITHUB_API}/rate_limit",
        json=body,
        headers={"ETag": '"r"', "X-OAuth-Scopes": "repo, admin:org"},
    )
    http = make_http(sleeps)
    assert http.rate_limit()["resources"]["core"]["remaining"] == 4000
    assert http.oauth_scopes() == {"repo", "admin:org"}
    assert all("If-None-Match" not in call.request.headers for call in api.calls)


def test_oauth_scopes_absent_or_empty(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """No X-OAuth-Scopes header -> None (fine-grained/App); an empty header -> set()."""
    api.add(responses.GET, f"{GITHUB_API}/rate_limit", json={"resources": {}})
    api.add(responses.GET, f"{GITHUB_API}/rate_limit", json={"resources": {}}, headers={"X-OAuth-Scopes": ""})
    http = make_http(sleeps)
    assert http.oauth_scopes() is None
    assert http.oauth_scopes() == set()


def test_rate_snapshot_per_resource(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """x-ratelimit-* headers are kept per resource."""
    rate = {
        "X-RateLimit-Limit": "5000",
        "X-RateLimit-Remaining": "4321",
        "X-RateLimit-Used": "679",
        "X-RateLimit-Reset": "1900000000",
    }
    api.add(responses.GET, ORG_URL, json={}, headers={**rate, "X-RateLimit-Resource": "core"})
    api.add(
        responses.POST,
        f"{GITHUB_API}/graphql",
        json={"data": {}},
        headers={**rate, "X-RateLimit-Resource": "graphql", "X-RateLimit-Remaining": "4990"},
    )
    http = make_http(sleeps)
    http.get(f"/orgs/{FAKE_ORG}")
    http.graphql("query { viewer { login } }")
    snapshot = http.rate_snapshot()
    assert snapshot["core"] == {
        "resource": "core",
        "limit": 5000,
        "remaining": 4321,
        "used": 679,
        "reset": 1900000000,
        "identity": "test",
    }
    assert snapshot["graphql"]["remaining"] == 4990
    assert http.last_rate is not None and http.last_rate["resource"] == "graphql"


# --- retries -------------------------------------------------------------------------------------------------------
def test_rate_limit_retry_on_post_with_retry_after(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """A secondary rate limit on POST is retried after Retry-After seconds (the request was not processed)."""
    url = f"{GITHUB_API}/repos/{FAKE_ORG}/r/issues/1/comments"
    api.add(
        responses.POST,
        url,
        status=403,
        json={"message": "You have exceeded a secondary rate limit."},
        headers={"Retry-After": "7"},
    )
    api.add(responses.POST, url, status=201, json={"id": 9})
    http = make_http(sleeps, write_scope=make_verified_org())
    assert http.post(f"/repos/{FAKE_ORG}/r/issues/1/comments", json={"body": "hi"}) == {"id": 9}
    assert sleeps == [7.0]
    assert len(api.calls) == 2


def test_rate_limit_waits_until_reset_capped(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """x-ratelimit-remaining 0 -> wait until reset, capped at 300 s; applies to PATCH too."""
    url = f"{GITHUB_API}/repos/{FAKE_ORG}/r"
    reset = str(int(time.time()) + 3600)
    api.add(
        responses.PATCH,
        url,
        status=429,
        json={"message": "API rate limit exceeded"},
        headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": reset},
    )
    api.add(responses.PATCH, url, json={"name": "r"})
    http = make_http(sleeps, write_scope=make_verified_org())
    assert http.patch(f"/repos/{FAKE_ORG}/r", json={"description": "x"}) == {"name": "r"}
    assert sleeps == [300.0]


def test_rate_limit_backoff_without_headers_and_max_retries(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Rate-limit bodies without headers back off 60/120/240 s; after max_retries the error surfaces."""
    url = f"{ORG_URL}/repos"
    for _ in range(3):
        api.add(responses.GET, url, status=403, json={"message": "API rate limit exceeded for user ID 1."})
    http = make_http(sleeps, max_retries=2)
    with pytest.raises(GitHubError) as info:
        http.get(f"/orgs/{FAKE_ORG}/repos")
    assert info.value.status == 403
    assert sleeps == [60.0, 120.0]


def test_exhausted_rate_limit_is_never_unavailable(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """A listing still rate-limited after the retries raises instead of looking like an unavailable feature."""
    api.add(
        responses.GET, f"{ORG_URL}/rulesets", status=403, json={"message": "API rate limit exceeded for user ID 1."}
    )
    http = make_http(sleeps, max_retries=1)
    with pytest.raises(GitHubError) as info:
        http.paginate(f"/orgs/{FAKE_ORG}/rulesets", allow_unavailable=True)
    assert info.value.status == 403 and http.unavailable == {}
    assert sleeps == [60.0]


def test_server_errors_retried_only_for_idempotent_calls(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """502/503/504 are retried for GET/PUT/DELETE and GraphQL queries, never for POST/PATCH."""
    verified = make_verified_org()
    api.add(responses.GET, ORG_URL, status=502)
    api.add(responses.GET, ORG_URL, json={"login": FAKE_ORG})
    api.add(responses.POST, f"{GITHUB_API}/graphql", status=503)
    api.add(responses.POST, f"{GITHUB_API}/graphql", json={"data": {"viewer": {"login": "x"}}})
    api.add(responses.POST, f"{GITHUB_API}/repos/{FAKE_ORG}/r/pulls", status=502)
    http = make_http(sleeps, write_scope=verified)
    assert http.get(f"/orgs/{FAKE_ORG}") == {"login": FAKE_ORG}
    assert http.graphql("query { viewer { login } }") == {"viewer": {"login": "x"}}
    with pytest.raises(GitHubError) as info:
        http.post(f"/repos/{FAKE_ORG}/r/pulls", json={"head": "h", "base": "main"})
    assert info.value.status == 502
    assert sleeps == [1.0, 1.0]


def test_connection_errors_retried_for_get_not_post(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Connection errors: GET retried with backoff, POST raised at once."""
    api.add(responses.GET, ORG_URL, body=requests.ConnectionError("reset"))
    api.add(responses.GET, ORG_URL, json={"login": FAKE_ORG})
    api.add(responses.POST, f"{GITHUB_API}/repos/{FAKE_ORG}/r/pulls", body=requests.ConnectionError("reset"))
    http = make_http(sleeps, write_scope=make_verified_org())
    assert http.get(f"/orgs/{FAKE_ORG}")["login"] == FAKE_ORG
    with pytest.raises(requests.ConnectionError):
        http.post(f"/repos/{FAKE_ORG}/r/pulls", json={})
    assert sleeps == [1.0]


def test_min_write_interval_paces_writes_not_reads(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Mutating calls are at least min_write_interval apart; GETs and GraphQL queries are not paced."""
    url = f"{GITHUB_API}/repos/{FAKE_ORG}/r/issues/1/comments"
    api.add(responses.POST, url, status=201, json={"id": 1})
    api.add(responses.POST, url, status=201, json={"id": 2})
    api.add(responses.GET, ORG_URL, json={})
    api.add(responses.POST, f"{GITHUB_API}/graphql", json={"data": {}})
    http = make_http(sleeps, write_scope=make_verified_org(), min_write_interval=5.0)
    http.post(f"/repos/{FAKE_ORG}/r/issues/1/comments", json={"body": "a"})
    http.get(f"/orgs/{FAKE_ORG}")
    http.graphql("{ viewer { login } }")
    assert sleeps == []
    http.post(f"/repos/{FAKE_ORG}/r/issues/1/comments", json={"body": "b"})
    assert len(sleeps) == 1 and 4.0 < sleeps[0] <= 5.0


# --- GraphQL -------------------------------------------------------------------------------------------------------
def test_graphql_data_errors_and_rate_limited_retry(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """``data`` is returned; errors raise unless allow_errors; RATE_LIMITED errors are retried."""
    url = f"{GITHUB_API}/graphql"
    api.add(responses.POST, url, json={"errors": [{"type": "RATE_LIMITED", "message": "API rate limit exceeded"}]})
    api.add(responses.POST, url, json={"data": {"viewer": {"login": "bot"}}})
    api.add(responses.POST, url, json={"data": {"repository": None}, "errors": [{"type": "NOT_FOUND"}]})
    api.add(responses.POST, url, json={"data": {"repository": None}, "errors": [{"type": "NOT_FOUND"}]})
    http = make_http(sleeps)
    assert http.graphql("query($a: Int) { viewer { login } }", {"a": 1}) == {"viewer": {"login": "bot"}}
    assert json.loads(api.calls[0].request.body or "{}") == {
        "query": "query($a: Int) { viewer { login } }",
        "variables": {"a": 1},
    }
    assert sleeps == [60.0]
    with pytest.raises(GitHubError, match="NOT_FOUND"):
        http.graphql('query { repository(owner: "o", name: "r") { id } }')
    assert http.graphql('{ repository(owner: "o", name: "r") { id } }', allow_errors=True) == {"repository": None}
    assert http.last_graphql_errors == [{"type": "NOT_FOUND"}]


@pytest.mark.parametrize(
    ("document", "expected"),
    [
        ("query { viewer { login } }", True),
        ("  {\n viewer { login } }", True),
        ('query { repository(owner: "o", name: "mutation-test") { id } }', True),
        ('query($q: String = "mutation {x}") { search(query: $q) { codeCount } }', True),
        ('mutation { addStar(input: {starrableId: "x"}) { clientMutationId } }', False),
        ("# comment\nmutation { x }", False),
        ("query A { viewer { login } } mutation B { x }", False),
        ("subscription { x }", False),
        ("fragment F on User { login }", False),
    ],
)
def test_is_graphql_query(document: str, expected: bool) -> None:
    """Only documents starting with query/{ and defining no mutation/subscription are queries."""
    assert is_graphql_query(document) is expected


# --- write guards (SPEC 5.2) ---------------------------------------------------------------------------------------
def test_read_only_refuses_graphql_mutations_and_writes(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """read_only: GET and GraphQL queries pass; mutations and REST writes raise SafetyError before any request."""
    api.add(responses.POST, f"{GITHUB_API}/graphql", json={"data": {"viewer": {"login": "o"}}})
    http = make_http(sleeps, read_only=True)
    assert http.graphql("query { viewer { login } }") == {"viewer": {"login": "o"}}
    with pytest.raises(SafetyError):
        http.graphql(
            'mutation { deleteBranchProtectionRule(input: {branchProtectionRuleId: "x"}) { clientMutationId } }'
        )
    with pytest.raises(SafetyError):
        http.graphql("query A { viewer { login } } mutation B { x }")
    with pytest.raises(SafetyError):
        http.delete(f"/repos/{FAKE_ORG}/r")
    with pytest.raises(SafetyError):
        http.post(f"/repos/{FAKE_ORG}/r/issues/1/comments", json={"body": "x"})
    assert len(api.calls) == 1


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"/repos/{FAKE_ORG}/r/git/refs"),
        ("DELETE", f"/repos/{FAKE_ORG}/r"),
        ("PATCH", f"/orgs/{FAKE_ORG}"),
        ("PUT", f"/orgs/{FAKE_ORG}/public_members/bot"),
        ("PATCH", f"/user/memberships/orgs/{FAKE_ORG}"),
        ("POST", "/app/installations/42/access_tokens"),
        ("POST", "/app-manifests/abc123/conversions"),
        ("DELETE", f"/repos/{FAKE_ORG.upper()}/r"),
    ],
)
def test_write_scope_allows_org_paths(api: responses.RequestsMock, sleeps: list[float], method: str, path: str) -> None:
    """Writes under the verified org (case-insensitive login) and the App/manifest endpoints are allowed."""
    api.add(method, f"{GITHUB_API}{path}", status=200, json={})
    http = make_http(sleeps, write_scope=make_verified_org())
    assert http.request(method, path).status_code == 200


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("DELETE", "/repos/eclipse-csi/otterdog"),
        ("PATCH", "/orgs/eclipsefdn"),
        ("POST", "/user/repos"),
        ("PATCH", "/user/memberships/orgs/eclipse"),
        ("DELETE", f"/repos/{FAKE_ORG}x/r"),
        ("DELETE", f"/repos/{FAKE_ORG}/../eclipse-csi/otterdog"),
        ("DELETE", f"/repos/{FAKE_ORG}/%2e%2e/eclipse-csi/otterdog"),
        ("PUT", "/orgs/other/memberships/bot"),
    ],
)
def test_write_scope_refuses_other_paths(
    api: responses.RequestsMock, sleeps: list[float], method: str, path: str
) -> None:
    """Writes outside the verified org (or escaping it with dot segments) raise SafetyError without any request."""
    http = make_http(sleeps, write_scope=make_verified_org())
    with pytest.raises(SafetyError):
        http.request(method, path)
    assert len(api.calls) == 0


def test_write_guard_runs_before_every_write(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """DESTR-03: the write_guard (lost org lease) refuses writes before any request; reads are not affected."""
    api.add(responses.GET, ORG_URL, json={"login": FAKE_ORG})
    http = make_http(sleeps, write_scope=make_verified_org())
    calls: list[str] = []

    def guard() -> None:
        """Refuse like E2EContext.check_lease_not_lost after a lost renewal."""
        calls.append("guard")
        raise SafetyError("the org lease of run x was lost")

    http.write_guard = guard
    with pytest.raises(SafetyError, match="lease of run x was lost"):
        http.patch(f"/orgs/{FAKE_ORG}", json={"description": "x"})
    assert calls == ["guard"] and len(api.calls) == 0
    assert http.get(f"/orgs/{FAKE_ORG}") == {"login": FAKE_ORG} and calls == ["guard"]


def test_unscoped_client_only_mints_tokens(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Without write_scope only App token minting, manifest conversion and GraphQL queries may POST."""
    api.add(responses.POST, f"{GITHUB_API}/app/installations/42/access_tokens", status=201, json={"token": "x"})
    http = make_http(sleeps)
    assert http.post("/app/installations/42/access_tokens") == {"token": "x"}
    with pytest.raises(SafetyError):
        http.post(f"/repos/{FAKE_ORG}/r/issues/1/comments", json={"body": "x"})
    with pytest.raises(SafetyError):
        http.graphql("mutation { x }")


def test_absolute_urls_must_target_the_api(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """Absolute URLs outside https://api.github.com/ are refused, also for reads."""
    http = make_http(sleeps)
    for url in ("https://evil.example/x", "https://api.github.com.evil.example/x", "http://api.github.com/x"):
        with pytest.raises(SafetyError):
            http.get(url)
    api.add(responses.GET, ORG_URL, json={"login": FAKE_ORG})
    assert http.get(ORG_URL)["login"] == FAKE_ORG


def test_write_scope_requires_the_github_api(sleeps: list[float]) -> None:
    """A write-scoped client cannot be pointed at another API host."""
    with pytest.raises(SafetyError):
        GitHubHttp(TOKEN, base_url="https://ghes.example/api/v3", write_scope=make_verified_org())


# --- redirects -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("method", ["DELETE", "PATCH", "PUT", "POST"])
def test_writes_never_follow_redirects(api: responses.RequestsMock, sleeps: list[float], method: str) -> None:
    """A transferred repository redirects (307) to /repositories/<id>: the write stops there, with the Location hint."""
    url = f"{GITHUB_API}/repos/{FAKE_ORG}/e2e-t3c7z8a5-moved"
    target = f"{GITHUB_API}/repositories/123"
    api.add(method, url, status=307, headers={"Location": target}, json={"message": "Temporary Redirect"})
    api.add(method, target, status=204)
    http = make_http(sleeps, write_scope=make_verified_org())
    with pytest.raises(GitHubError) as info:
        http.request(method, f"/repos/{FAKE_ORG}/e2e-t3c7z8a5-moved", json={"x": 1})
    assert info.value.status == 307 and info.value.headers["Location"] == target
    assert "not followed" in str(info.value)
    assert [str(call.request.url) for call in api.calls] == [url]


def test_reads_and_graphql_queries_follow_redirects(api: responses.RequestsMock, sleeps: list[float]) -> None:
    """GET (a renamed branch) and POST /graphql queries follow redirects as before."""
    base = f"{GITHUB_API}/repos/{FAKE_ORG}/r/branches"
    api.add(responses.GET, f"{base}/main", status=301, headers={"Location": f"{base}/master"})
    api.add(responses.GET, f"{base}/master", json={"name": "master"})
    api.add(responses.POST, f"{GITHUB_API}/graphql", status=307, headers={"Location": f"{GITHUB_API}/graphql2"})
    api.add(responses.POST, f"{GITHUB_API}/graphql2", json={"data": {"viewer": {"login": "x"}}})
    http = make_http(sleeps)
    assert http.get(f"/repos/{FAKE_ORG}/r/branches/main") == {"name": "master"}
    assert http.graphql("query { viewer { login } }") == {"viewer": {"login": "x"}}
