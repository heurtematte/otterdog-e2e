"""Unit tests of otterdog_e2e.appmanifest: permissions, manifest, auto-posting form and the code exchange."""

from __future__ import annotations

import html.parser
import json
import logging
import stat
import urllib.parse
from pathlib import Path
from typing import Any

import pytest
import responses

from otterdog_e2e import appmanifest
from otterdog_e2e.appmanifest import (
    AUTO_SUBMIT_SCRIPT,
    DEFAULT_EVENTS,
    DEFAULT_PERMISSIONS,
    ManifestExchangeError,
    build_manifest,
    code_from_callback,
    default_redirect_url,
    exchange_code,
    is_loopback_host,
    manifest_form_html,
    script_hash,
)
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import Target, WebappSpec
from otterdog_e2e.testing.fakes import FakeGitHubHttp, HttpCall

DATA = Path(__file__).parent / "data"
ORG = "e2e-test-org"
# unique values: they are registered with the process-wide REDACTOR and must not collide with other tests' data
CODE = "e2eManifestCode0123456789abcdefABCDEF0123"
HOOK = "https://sink.example.org/otterdog-e2e"
REDIRECT = "http://127.0.0.1:8765/callback"
PEM = "".join(
    [
        "-----BEGIN RSA PRIVATE KEY-----\n",
        *(f"E2EAPPMANIFESTFAKEPRIVATEKEYLINE{index:02d}xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx\n" for index in range(3)),
        "-----END RSA PRIVATE KEY-----\n",
    ]
)
CLIENT_SECRET = "e2e-appmanifest-client-secret-0123456789abcdef"
CLIENT_ID = "Iv23liE2eAppManifestClient"
WEBHOOK_SECRET = "e2e-appmanifest-webhook-secret-0123456789abcdef"
# documented in the GitHub docs permission tables, missing from components.schemas.app-permissions (GH-01)
UNDOCUMENTED_IN_OPENAPI = {"actions_variables": ["read", "write"], "organization_actions_variables": ["read", "write"]}


def make_target(org: str = ORG) -> Target:
    """A Target as settings.load_target would build it."""
    return Target(
        name="free",
        description="Dedicated GitHub Free test organization",
        org=org,
        org_id=424242,
        allowed_org_ids=(424242,),
        expected_plan="free",
        marker="[otterdog-e2e]",
        capability_overrides={"add": (), "remove": ()},
        configs_repo="otterdog-e2e-configs",
        org_config_repo="auto",
        defaults_repo="otterdog-e2e-defaults",
        template_mode="auto",
        template_url=None,
        identities={},
        app=None,
        admin_team="otterdog-admins",
        approval_team="project-leads",
        contributors_team="e2e-contributors",
        webapp=WebappSpec("relay", None, None, "e2e/otterdog-validate", "e2e/otterdog-sync", 1, 5000),
        fixture_repos=("otterdog-e2e-fixture-a",),
        extra_protected_repos=(),
        baseline_settings={},
        source_path=Path("targets/free.yaml"),
    )


# --- permissions and events ---------------------------------------------------------------------------------------
def test_default_permissions_are_github_app_permission_names() -> None:
    """GH-01: keys are a subset of OpenAPI app-permissions plus the two variables permissions; levels are valid."""
    fixture = json.loads((DATA / "app_permissions_keys.json").read_text())
    openapi = fixture["permissions"]
    assert set(UNDOCUMENTED_IN_OPENAPI).isdisjoint(openapi), "OpenAPI gained the variables keys: update the fixture"
    levels = {**openapi, **UNDOCUMENTED_IN_OPENAPI}
    assert set(DEFAULT_PERMISSIONS) <= set(levels), sorted(set(DEFAULT_PERMISSIONS) - set(levels))
    assert {key: level for key, level in DEFAULT_PERMISSIONS.items() if level not in levels[key]} == {}


def test_default_permissions_cover_what_otterdog_manages() -> None:
    """Custom org roles (not repository roles), variables and custom properties use their real names."""
    assert DEFAULT_PERMISSIONS["organization_custom_org_roles"] == "write"
    assert "organization_custom_roles" not in DEFAULT_PERMISSIONS
    assert DEFAULT_PERMISSIONS["organization_custom_properties"] == "admin"
    assert DEFAULT_PERMISSIONS["repository_custom_properties"] == "write"
    assert DEFAULT_PERMISSIONS["actions_variables"] == DEFAULT_PERMISSIONS["organization_actions_variables"] == "write"
    assert len(DEFAULT_PERMISSIONS) == 22


def test_default_events() -> None:
    """Events the webapp handles."""
    assert DEFAULT_EVENTS == [
        "issue_comment",
        "pull_request",
        "pull_request_review",
        "push",
        "workflow_job",
        "workflow_run",
    ]


# --- manifest -----------------------------------------------------------------------------------------------------
def test_build_manifest() -> None:
    """Private App, homepage on the configs repo, active non-loopback hook, redirect to the local listener."""
    manifest = build_manifest(make_target(), webhook_url=HOOK, redirect_url=REDIRECT)
    assert manifest["name"] == f"otterdog-e2e-{ORG}"
    assert manifest["url"] == f"https://github.com/{ORG}/otterdog-e2e-configs"
    assert manifest["hook_attributes"] == {"url": HOOK, "active": True}
    assert manifest["redirect_url"] == REDIRECT and manifest["public"] is False
    assert manifest["default_permissions"] == DEFAULT_PERMISSIONS and manifest["default_events"] == DEFAULT_EVENTS
    manifest["default_permissions"]["issues"] = "write"
    manifest["default_events"].append("ping")
    assert DEFAULT_PERMISSIONS["issues"] == "read" and "ping" not in DEFAULT_EVENTS
    json.dumps(manifest)


def test_app_name_is_cut_to_34_characters() -> None:
    """GitHub App names are limited to 34 characters."""
    org = "a-rather-long-organization-name-for-e2e"  # 39 characters: the longest GitHub login
    name = build_manifest(make_target(org), webhook_url=HOOK, redirect_url=REDIRECT)["name"]
    assert name == f"otterdog-e2e-{org}"[:34] and len(name) == 34


@pytest.mark.parametrize(
    "url",
    [
        "https://localhost/hook",
        "https://LOCALHOST./hook",
        "https://app.localhost:8443/hook",
        "https://127.0.0.1/hook",
        "https://127.10.20.30/hook",
        "https://[::1]:5000/hook",
        "https://[::ffff:127.0.0.1]/hook",
        "https://0.0.0.0/hook",
    ],
)
def test_loopback_hook_urls_are_rejected(url: str) -> None:
    """GitHub refuses loopback hook hosts; deliveries reach the webapp through the relay instead."""
    with pytest.raises(ValueError, match="loopback"):
        build_manifest(make_target(), webhook_url=url, redirect_url=REDIRECT)


@pytest.mark.parametrize(
    "url", ["http://sink.example.org/hook", "sink.example.org/hook", "https:///hook", "https://u:p@sink.example.org/"]
)
def test_hook_urls_must_be_plain_https(url: str) -> None:
    """Absolute https URLs only, without embedded credentials."""
    with pytest.raises(ValueError, match=r"https URL|credentials"):
        build_manifest(make_target(), webhook_url=url, redirect_url=REDIRECT)


def test_redirect_url_and_org_are_validated() -> None:
    """The redirect URL must be absolute http(s); the org must be a GitHub login."""
    with pytest.raises(ValueError, match="redirect URL"):
        build_manifest(make_target(), webhook_url=HOOK, redirect_url="/callback")
    with pytest.raises(ValueError, match="organization login"):
        build_manifest(make_target("bad/org"), webhook_url=HOOK, redirect_url=REDIRECT)
    assert default_redirect_url() == REDIRECT and default_redirect_url(9000) == "http://127.0.0.1:9000/callback"


def test_is_loopback_host() -> None:
    """Public names and addresses are not loopback."""
    assert is_loopback_host("localhost") and is_loopback_host("[::1]") and is_loopback_host("127.0.0.53")
    assert not is_loopback_host("smee.io") and not is_loopback_host("140.82.112.3") and not is_loopback_host("::2")


# --- form ---------------------------------------------------------------------------------------------------------
class _FormParser(html.parser.HTMLParser):
    """Collects the form, its inputs, scripts and meta tags of the manifest page."""

    def __init__(self) -> None:
        """Start empty."""
        super().__init__()
        self.forms: list[dict[str, str | None]] = []
        self.inputs: dict[str, str | None] = {}
        self.metas: list[dict[str, str | None]] = []
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Record forms, inputs and metas."""
        values = dict(attrs)
        if tag == "form":
            self.forms.append(values)
        elif tag == "input":
            self.inputs[values["name"] or ""] = values.get("value")
        elif tag == "meta":
            self.metas.append(values)
        self._in_script = tag == "script"

    def handle_endtag(self, tag: str) -> None:
        """Leave a script."""
        self._in_script = False

    def handle_data(self, data: str) -> None:
        """Collect script bodies."""
        if self._in_script:
            self.scripts.append(data)


def _parse(page: str) -> _FormParser:
    """Parsed manifest page."""
    parser = _FormParser()
    parser.feed(page)
    return parser


def test_manifest_form_posts_manifest_and_state_to_github() -> None:
    """The page auto-posts ``manifest`` (JSON) and ``state`` to the org's new-App page (state also in the URL)."""
    manifest = build_manifest(make_target(), webhook_url=HOOK, redirect_url=REDIRECT)
    state = "s/t&a=te+1"
    parser = _parse(manifest_form_html(ORG, manifest, state))
    (form,) = parser.forms
    assert form["method"] == "post"
    action = urllib.parse.urlsplit(form["action"] or "")
    assert (action.scheme, action.netloc, action.path) == (
        "https",
        "github.com",
        f"/organizations/{ORG}/settings/apps/new",
    )
    assert urllib.parse.parse_qs(action.query) == {"state": [state]}
    assert json.loads(parser.inputs["manifest"] or "") == manifest
    assert parser.inputs["state"] == state
    assert parser.scripts == [AUTO_SUBMIT_SCRIPT] and f'getElementById("{form["id"]}")' in AUTO_SUBMIT_SCRIPT


def test_manifest_form_csp_allows_only_the_submit_script_and_github() -> None:
    """CSP: no other script, forms may only post to github.com."""
    page = manifest_form_html(ORG, {"name": "x"}, "state")
    csp = next(meta["content"] for meta in _parse(page).metas if meta.get("http-equiv") == "Content-Security-Policy")
    assert csp is not None
    assert "default-src 'none'" in csp and "form-action https://github.com" in csp
    assert f"script-src {script_hash(AUTO_SUBMIT_SCRIPT)}" in csp
    assert script_hash("alert(1)") != script_hash(AUTO_SUBMIT_SCRIPT)


def test_manifest_form_escapes_manifest_values() -> None:
    """Manifest strings cannot inject markup (JSON is HTML-escaped inside the attribute)."""
    manifest = {"name": '"><script>alert(1)</script>', "description": "a & b <i>"}
    page = manifest_form_html(ORG, manifest, "st")
    assert "<script>alert(1)</script>" not in page and "<i>" not in page
    parser = _parse(page)
    assert json.loads(parser.inputs["manifest"] or "") == manifest
    assert parser.scripts == [AUTO_SUBMIT_SCRIPT]


def test_manifest_form_rejects_bad_org_and_empty_state() -> None:
    """The org is a login and the state is required."""
    with pytest.raises(ValueError, match="organization login"):
        manifest_form_html("evil.com/x", {}, "state")
    with pytest.raises(ValueError, match="state"):
        manifest_form_html(ORG, {}, "")


# --- callback -----------------------------------------------------------------------------------------------------
def test_code_from_callback() -> None:
    """The code is returned only with the expected state; it is registered as a secret."""
    assert code_from_callback(f"code={CODE}&state=abc123", state="abc123") == CODE
    assert code_from_callback(f"{REDIRECT}?code={CODE}&state=abc123", state="abc123") == CODE
    assert REDACTOR(f"x {CODE}") == "x ***"
    with pytest.raises(ValueError, match="state mismatch"):
        code_from_callback(f"code={CODE}&state=other", state="abc123")
    with pytest.raises(ValueError, match="state mismatch"):
        code_from_callback(f"code={CODE}", state="abc123")
    with pytest.raises(ValueError, match="valid code"):
        code_from_callback("state=abc123", state="abc123")
    with pytest.raises(ValueError, match="valid code"):
        code_from_callback("code=../../x&state=abc123", state="abc123")


# --- exchange -----------------------------------------------------------------------------------------------------
def conversion_answer(**overrides: Any) -> dict[str, Any]:
    """POST /app-manifests/{code}/conversions 201 answer (OpenAPI integration-from-manifest shape)."""
    answer = {
        "id": 4242,
        "slug": f"otterdog-e2e-{ORG}",
        "node_id": "MDxOkludGVncmF0aW9uMQ==",
        "owner": {"login": ORG, "id": 424242, "type": "Organization"},
        "name": f"otterdog-e2e-{ORG}",
        "description": "",
        "external_url": f"https://github.com/{ORG}/otterdog-e2e-configs",
        "html_url": f"https://github.com/apps/otterdog-e2e-{ORG}",
        "created_at": "2026-10-02T10:00:00Z",
        "updated_at": "2026-10-02T10:00:00Z",
        "permissions": dict(DEFAULT_PERMISSIONS),
        "events": list(DEFAULT_EVENTS),
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "webhook_secret": WEBHOOK_SECRET,
        "pem": PEM,
    }
    answer.update(overrides)
    return answer


@pytest.fixture
def github(monkeypatch: pytest.MonkeyPatch) -> FakeGitHubHttp:
    """FakeGitHubHttp behind appmanifest._manifest_http (no network)."""
    http = FakeGitHubHttp(identity="app-manifest")
    monkeypatch.setattr(appmanifest, "_manifest_http", lambda: http)
    return http


def _mode(path: Path) -> int:
    """Permission bits of a path."""
    return stat.S_IMODE(path.stat().st_mode)


def test_exchange_code_writes_private_files_and_returns_no_secret(
    github: FakeGitHubHttp, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """pem + webhook secret (+ env snippet) in 0600 files of a 0700 dir; client id/secret discarded."""
    github.add("POST", f"/app-manifests/{CODE}/conversions", status=201, json=conversion_answer())
    out_dir = tmp_path / "config" / "otterdog-e2e" / "free"
    with caplog.at_level(logging.DEBUG, logger="otterdog_e2e.appmanifest"):
        result = exchange_code(CODE, out_dir=out_dir)
    assert github.calls == [HttpCall("POST", f"/app-manifests/{CODE}/conversions", None, None)]
    assert (result["id"], result["slug"], result["owner"], result["secret_generated"]) == (
        4242,
        f"otterdog-e2e-{ORG}",
        ORG,
        False,
    )
    assert _mode(out_dir) == 0o700
    for key in ("pem_path", "secret_path", "env_path"):
        assert result[key].parent == out_dir and _mode(result[key]) == 0o600
    assert result["pem_path"].read_text() == PEM
    assert result["secret_path"].read_text() == WEBHOOK_SECRET + "\n"
    env = result["env_path"].read_text().splitlines()
    assert "E2E_APP_ID=4242" in env and f"E2E_APP_SLUG=otterdog-e2e-{ORG}" in env
    assert f"E2E_APP_PRIVATE_KEY_FILE={result['pem_path']}" in env and f"E2E_APP_WEBHOOK_SECRET={WEBHOOK_SECRET}" in env
    returned = json.dumps(result, default=str)
    files = "".join(path.read_text() for path in out_dir.iterdir())
    for secret in (CLIENT_SECRET, CLIENT_ID, WEBHOOK_SECRET, "BEGIN RSA PRIVATE KEY", CODE):
        assert secret not in returned and secret not in caplog.text
    assert CLIENT_SECRET not in files and CLIENT_ID not in files
    assert REDACTOR(f"{CLIENT_SECRET} {WEBHOOK_SECRET} {CODE}") == "*** *** ***"


def test_exchange_code_generates_a_missing_webhook_secret(
    github: FakeGitHubHttp, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A null webhook_secret is replaced by a random 64-hex secret (registered, flagged, warned about)."""
    github.add("POST", f"/app-manifests/{CODE}/conversions", status=201, json=conversion_answer(webhook_secret=None))
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.appmanifest"):
        result = exchange_code(CODE, out_dir=tmp_path / "out")
    secret = result["secret_path"].read_text().strip()
    assert result["secret_generated"] is True and len(secret) == 64 and int(secret, 16) >= 0
    assert REDACTOR(secret) == "***" and secret not in caplog.text
    assert "no webhook secret" in caplog.text


def test_exchange_code_expands_the_home_directory(
    github: FakeGitHubHttp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``~/.config/otterdog-e2e/<target>`` is expanded (never a literal ``~`` directory)."""
    github.add("POST", f"/app-manifests/{CODE}/conversions", status=201, json=conversion_answer())
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    result = exchange_code(CODE, out_dir=Path("~/.config/otterdog-e2e/free"))
    assert result["pem_path"].parent == tmp_path / "home" / ".config" / "otterdog-e2e" / "free"


def test_exchange_code_tightens_an_existing_directory(github: FakeGitHubHttp, tmp_path: Path) -> None:
    """An existing out_dir gets mode 0700."""
    github.add("POST", f"/app-manifests/{CODE}/conversions", status=201, json=conversion_answer())
    out_dir = tmp_path / "out"
    out_dir.mkdir(mode=0o755)
    out_dir.chmod(0o755)
    exchange_code(CODE, out_dir=out_dir)
    assert _mode(out_dir) == 0o700


@pytest.mark.parametrize("code", ["", "short", "../../app/hook/config", "a/b/c/d/e/f/g", "code with spaces", "x" * 300])
def test_exchange_code_refuses_invalid_codes(github: FakeGitHubHttp, tmp_path: Path, code: str) -> None:
    """Codes are validated before any request (no path injection into the API URL)."""
    with pytest.raises(ValueError, match="invalid manifest code"):
        exchange_code(code, out_dir=tmp_path / "out")
    assert github.calls == [] and not (tmp_path / "out").exists()


@pytest.mark.parametrize(
    ("overrides", "problem"),
    [({"pem": None}, "no private key"), ({"pem": "not a key"}, "no private key"), ({"id": "1"}, "no App id/slug")],
)
def test_exchange_code_rejects_unusable_answers(
    github: FakeGitHubHttp, tmp_path: Path, overrides: dict[str, Any], problem: str
) -> None:
    """Nothing is written when the answer lacks the key or the App identity."""
    github.add("POST", f"/app-manifests/{CODE}/conversions", status=201, json=conversion_answer(**overrides))
    with pytest.raises(ManifestExchangeError, match=problem):
        exchange_code(CODE, out_dir=tmp_path / "out")
    assert not (tmp_path / "out").exists()
    assert REDACTOR(CLIENT_SECRET) == "***"


def test_exchange_code_never_overwrites_credentials(github: FakeGitHubHttp, tmp_path: Path) -> None:
    """Credential files are created exclusively (an existing key file is kept)."""
    github.add("POST", f"/app-manifests/{CODE}/conversions", status=201, json=conversion_answer())
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    existing = out_dir / "app-4242.private-key.pem"
    existing.write_text("previous key")
    with pytest.raises(FileExistsError):
        exchange_code(CODE, out_dir=out_dir)
    assert existing.read_text() == "previous key"


def test_exchange_code_refuses_a_symlinked_directory(github: FakeGitHubHttp, tmp_path: Path) -> None:
    """Credentials are never written through a symlinked out_dir."""
    github.add("POST", f"/app-manifests/{CODE}/conversions", status=201, json=conversion_answer())
    target = tmp_path / "elsewhere"
    target.mkdir()
    link = tmp_path / "out"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(SafetyError, match="symlink"):
        exchange_code(CODE, out_dir=link)
    assert list(target.iterdir()) == []


def test_exchange_code_through_github_http(tmp_path: Path) -> None:
    """The real GitHubHttp sends an unauthenticated POST to api.github.com (mocked with responses)."""
    url = f"https://api.github.com/app-manifests/{CODE}/conversions"
    with responses.RequestsMock() as mock:
        mock.add(responses.POST, url, json=conversion_answer(), status=201)
        result = exchange_code(CODE, out_dir=tmp_path / "out")
        (call,) = mock.calls
    assert result["id"] == 4242 and result["pem_path"].read_text() == PEM
    assert call.request.method == "POST" and "Authorization" not in call.request.headers
    assert call.request.headers["Accept"] == "application/vnd.github+json"
