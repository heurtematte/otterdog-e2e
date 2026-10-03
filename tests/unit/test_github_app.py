"""AppAuth: JWT claims and reuse, installation tokens, App endpoints and the delivery cursor (SPEC 9.2)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime

import jwt as pyjwt
import pytest
import responses
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from responses import matchers

from otterdog_e2e.github.app import AppAuth, cursor_from_link, parse_github_time
from otterdog_e2e.github.http import GITHUB_API
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import AppCredentials
from otterdog_e2e.testing.fakes import FAKE_ORG, make_verified_org

NOW = 1_900_000_000.0
INSTALLATION_TOKEN = "ghs_" + "InstallationTokenForTests0123456789abc"


@pytest.fixture(scope="module")
def key_pair() -> tuple[str, str]:
    """A throwaway RSA key pair (private PEM, public PEM)."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public = (
        key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    return private, public


class Clock:
    """Settable clock."""

    def __init__(self, now: float = NOW) -> None:
        """Start at ``now``."""
        self.now = now

    def __call__(self) -> float:
        """Current fake time."""
        return self.now


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked api.github.com."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def make_app(key_pair: tuple[str, str], clock: Clock, *, slug: str | None = "otterdog-e2e-test") -> AppAuth:
    """AppAuth with the test key."""
    creds = AppCredentials(app_id="12345", private_key_pem=key_pair[0], webhook_secret="e2e-dummy-secret0", slug=slug)
    return AppAuth(creds, clock=clock)


def test_jwt_claims_reuse_and_redaction(key_pair: tuple[str, str]) -> None:
    """RS256, iat=now-60, exp=now+540, iss=app id; reused until 60 s before exp; registered with REDACTOR."""
    clock = Clock()
    app = make_app(key_pair, clock)
    token = app.jwt()
    claims = pyjwt.decode(token, key_pair[1], algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False})
    assert claims == {"iat": int(NOW) - 60, "exp": int(NOW) + 540, "iss": "12345"}
    assert pyjwt.get_unverified_header(token)["alg"] == "RS256"
    assert token in REDACTOR.literals
    clock.now = NOW + 479
    assert app.jwt() == token
    clock.now = NOW + 480
    renewed = app.jwt()
    assert renewed != token
    assert (
        pyjwt.decode(renewed, key_pair[1], algorithms=["RS256"], options={"verify_exp": False, "verify_iat": False})[
            "iat"
        ]
        == int(NOW) + 420
    )


def test_installation_token_cache_and_jwt_auth(api: responses.RequestsMock, key_pair: tuple[str, str]) -> None:
    """Tokens are minted with the JWT, cached until expires_at - 60 s and registered with REDACTOR."""
    clock = Clock()
    url = f"{GITHUB_API}/app/installations/42/access_tokens"
    expires = "2030-03-17T18:46:40Z"  # NOW + 3600
    api.add(responses.POST, url, status=201, json={"token": INSTALLATION_TOKEN, "expires_at": expires})
    api.add(
        responses.POST, url, status=201, json={"token": INSTALLATION_TOKEN + "2", "expires_at": "2030-03-17T19:46:40Z"}
    )
    app = make_app(key_pair, clock)
    assert parse_github_time(expires).timestamp() == NOW + 3600
    assert app.installation_token(42) == INSTALLATION_TOKEN
    assert api.calls[0].request.headers["Authorization"] == f"Bearer {app.jwt()}"
    assert INSTALLATION_TOKEN in REDACTOR.literals
    clock.now = NOW + 3539
    assert app.installation_token(42) == INSTALLATION_TOKEN
    assert len(api.calls) == 1
    clock.now = NOW + 3540
    assert app.installation_token(42) == INSTALLATION_TOKEN + "2"
    assert len(api.calls) == 2


def test_installation_http_is_write_scoped(api: responses.RequestsMock, key_pair: tuple[str, str]) -> None:
    """The installation client authenticates with the installation token and is write-scoped to the org."""
    clock = Clock()
    api.add(
        responses.POST,
        f"{GITHUB_API}/app/installations/42/access_tokens",
        status=201,
        json={"token": INSTALLATION_TOKEN, "expires_at": "2030-03-17T18:46:40Z"},
    )
    api.add(responses.GET, f"{GITHUB_API}/repos/{FAKE_ORG}/r", json={"name": "r"})
    app = make_app(key_pair, clock)
    http = app.installation_http(42, make_verified_org())
    assert http.get(f"/repos/{FAKE_ORG}/r") == {"name": "r"}
    assert api.calls[-1].request.headers["Authorization"] == f"Bearer {INSTALLATION_TOKEN}"
    assert http.write_scope is not None and http.write_scope.login == FAKE_ORG
    with pytest.raises(SafetyError):
        http.delete("/repos/eclipse-csi/otterdog")


def test_app_endpoints(api: responses.RequestsMock, key_pair: tuple[str, str]) -> None:
    """get_app is cached; slug falls back to GET /app; installation_for_org 404 -> None; hook config and rate."""
    api.add(
        responses.GET,
        f"{GITHUB_API}/app",
        json={"id": 12345, "slug": "from-api", "owner": {"login": FAKE_ORG}},
        headers={"X-RateLimit-Remaining": "4321"},
    )
    api.add(responses.GET, f"{GITHUB_API}/orgs/{FAKE_ORG}/installation", json={"id": 42, "repository_selection": "all"})
    api.add(responses.GET, f"{GITHUB_API}/orgs/other/installation", status=404, json={"message": "Not Found"})
    api.add(
        responses.GET,
        f"{GITHUB_API}/app/hook/config",
        json={"url": "https://sink.example.org/x", "content_type": "json"},
    )
    app = make_app(key_pair, Clock(), slug=None)
    assert app.rate_remaining is None
    assert app.slug == "from-api" and app.bot_login == "from-api[bot]"
    assert app.get_app()["id"] == 12345
    assert len([c for c in api.calls if str(c.request.url).endswith("/app")]) == 1
    assert app.rate_remaining == 4321
    assert (app.installation_for_org(FAKE_ORG) or {})["id"] == 42
    assert app.installation_for_org("other") is None
    assert app.hook_config()["content_type"] == "json"
    assert make_app(key_pair, Clock()).slug == "otterdog-e2e-test"


def test_rate_reset_comes_from_the_last_jwt_response(api: responses.RequestsMock, key_pair: tuple[str, str]) -> None:
    """rate_reset: X-RateLimit-Reset of the last JWT response as an aware UTC datetime; None without one."""
    reset = 1_900_000_600
    api.add(
        responses.GET,
        f"{GITHUB_API}/app",
        json={"id": 12345, "slug": "otterdog-e2e-test"},
        headers={"X-RateLimit-Remaining": "12", "X-RateLimit-Reset": str(reset)},
    )
    api.add(responses.GET, f"{GITHUB_API}/app/hook/config", json={}, headers={"X-RateLimit-Remaining": "11"})
    app = make_app(key_pair, Clock())
    assert app.rate_reset is None
    app.get_app()
    assert (app.rate_remaining, app.rate_reset) == (12, datetime.fromtimestamp(reset, UTC))
    assert app.rate_reset is not None and app.rate_reset.tzinfo is UTC
    app.hook_config()
    assert (app.rate_remaining, app.rate_reset) == (11, None)


def test_list_deliveries_cursor(api: responses.RequestsMock, key_pair: tuple[str, str]) -> None:
    """One page per call; the next cursor comes from the Link rel=next URL; per_page is capped at 100."""
    url = f"{GITHUB_API}/app/hook/deliveries"
    next_url = f"{url}?per_page=100&cursor=v1_7890123"
    page1 = [{"id": 3, "guid": "g3", "event": "push"}, {"id": 2, "guid": "g2", "event": "ping"}]
    api.add(
        responses.GET,
        url,
        json=page1,
        headers={"Link": f'<{next_url}>; rel="next", <{url}?per_page=100&cursor=v1_first>; rel="first"'},
        match=[matchers.query_param_matcher({"per_page": "100"})],
    )
    api.add(
        responses.GET,
        url,
        json=[{"id": 1, "guid": "g1", "event": "pull_request"}],
        match=[matchers.query_param_matcher({"per_page": "100", "cursor": "v1_7890123"})],
    )
    app = make_app(key_pair, Clock())
    items, cursor = app.list_deliveries(per_page=500)
    assert [item["id"] for item in items] == [3, 2] and cursor == "v1_7890123"
    items, cursor = app.list_deliveries(cursor=cursor)
    assert [item["id"] for item in items] == [1] and cursor is None


def test_get_delivery(api: responses.RequestsMock, key_pair: tuple[str, str]) -> None:
    """GET /app/hook/deliveries/{id} returns request headers and payload."""
    detail = {"id": 7, "event": "ping", "request": {"headers": {"X-GitHub-Event": "ping"}, "payload": {"zen": "z"}}}
    api.add(responses.GET, f"{GITHUB_API}/app/hook/deliveries/7", json=detail)
    assert make_app(key_pair, Clock()).get_delivery(7)["request"]["payload"] == {"zen": "z"}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://api.github.com/app/hook/deliveries?per_page=100&cursor=v1_123", "v1_123"),
        ("https://api.github.com/app/hook/deliveries?cursor=v1%3D9&per_page=2", "v1=9"),
        ("https://api.github.com/app/hook/deliveries?per_page=100", None),
        (None, None),
    ],
)
def test_cursor_from_link(url: str | None, expected: str | None) -> None:
    """The cursor query parameter of a next link."""
    assert cursor_from_link(url) == expected


def test_app_credentials_registered(key_pair: tuple[str, str]) -> None:
    """The private key lines and the webhook secret are registered with REDACTOR."""
    app = make_app(key_pair, Clock())
    pem_line = next(line for line in key_pair[0].splitlines() if len(line) > 40)
    assert REDACTOR(pem_line) == "***"
    assert REDACTOR(json.dumps({"s": app.creds.webhook_secret})) == '{"s": "***"}'


def test_jwt_refreshed_between_retries(api: responses.RequestsMock, key_pair: tuple[str, str]) -> None:
    """A JWT expiring during a rate-limit wait is re-minted for the retry."""
    clock = Clock()
    app = make_app(key_pair, clock)

    def wait(seconds: float) -> None:
        """Time passes while waiting (past the JWT refresh point, now + 480 s)."""
        clock.now += seconds + 400

    app.app_http().sleep = wait
    url = f"{GITHUB_API}/app/hook/config"
    api.add(responses.GET, url, status=429, json={"message": "rate limited"}, headers={"Retry-After": "120"})
    api.add(responses.GET, url, json={"url": "https://sink.example.org/x"})
    assert app.hook_config()["url"] == "https://sink.example.org/x"
    first, second = (call.request.headers["Authorization"] for call in api.calls)
    assert first != second and second == f"Bearer {app.jwt()}"


def test_installations_and_refreshed_app_feed_verify_app(
    api: responses.RequestsMock, key_pair: tuple[str, str]
) -> None:
    """installations() follows every page of GET /app/installations; get_app(refresh=True) reads GET /app again;
    safety.verify_app refuses an installation on a foreign org found on page 2 (DESTR-01)."""
    from otterdog_e2e.safety import verify_app
    from otterdog_e2e.testing.fakes import FAKE_ORG_ID, make_target

    owner = {"login": FAKE_ORG, "id": FAKE_ORG_ID, "type": "Organization"}
    api.add(responses.GET, f"{GITHUB_API}/app", json={"id": 12345, "slug": "otterdog-e2e-test", "owner": owner})
    page2 = f"{GITHUB_API}/app/installations?per_page=100&page=2"
    own = {"id": 1, "account": owner, "target_id": FAKE_ORG_ID, "target_type": "Organization"}
    foreign = {
        "id": 2,
        "account": {"login": "acme-production", "id": 99, "type": "Organization"},
        "target_type": "Organization",
    }
    api.add(
        responses.GET,
        f"{GITHUB_API}/app/installations",
        json=[own],
        headers={"Link": f'<{page2}>; rel="next"'},
        match=[matchers.query_param_matcher({"per_page": "100"})],
    )
    api.add(
        responses.GET,
        f"{GITHUB_API}/app/installations",
        json=[foreign],
        match=[matchers.query_param_matcher({"per_page": "100", "page": "2"})],
    )
    app = make_app(key_pair, Clock())
    assert [item["id"] for item in app.installations()] == [1, 2]
    app.get_app()
    app.get_app()
    app.get_app(refresh=True)
    assert len([call for call in api.calls if call.request.url == f"{GITHUB_API}/app"]) == 2
    with pytest.raises(SafetyError, match="acme-production"):
        verify_app(app, make_target())
