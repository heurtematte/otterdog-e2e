"""WP-A: org pin, verified-org capability and identity isolation (SPEC 5.1)."""

from __future__ import annotations

import dataclasses
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import responses
from responses import matchers

from otterdog_e2e import safety
from otterdog_e2e.github.http import GitHubError, GitHubHttp
from otterdog_e2e.safety import (
    ALLOWED_SCOPES,
    SafetyError,
    VerifiedOrg,
    check_identity_isolation,
    check_org_allowed,
    verify_target,
)
from otterdog_e2e.settings import Identity, IdentitySpec, Target, WebappSpec
from otterdog_e2e.testing.fakes import FAKE_ORG, FAKE_ORG_ID, FakeGitHubHttp, default_org_json

API = "https://api.github.com"
ADMIN_SCOPES = {"repo", "workflow", "admin:org", "admin:org_hook", "delete_repo", "read:org"}
MEMBER_SCOPES = {"public_repo", "read:org"}
TEST_ORG = {"login": FAKE_ORG, "id": FAKE_ORG_ID}
SECOND_TEST_ORG = {"login": "e2e-second-org", "id": 777}
FOREIGN_ORG = {"login": "acme-production", "id": 99}  # a real org that is not on the denylist
DENYLISTED_ORG = {"login": "eclipse-jdt", "id": 98}
ADMIN = Identity("admin", "e2e-admin-bot", "wpa-admin-token-01")


def make_target(**overrides: Any) -> Target:
    """A free-plan Target for the fake org."""
    values: dict[str, Any] = {
        "name": "free",
        "description": "test",
        "org": FAKE_ORG,
        "org_id": FAKE_ORG_ID,
        "allowed_org_ids": (FAKE_ORG_ID,),
        "expected_plan": "free",
        "marker": "[otterdog-e2e]",
        "capability_overrides": {"add": (), "remove": ()},
        "configs_repo": "otterdog-e2e-configs",
        "org_config_repo": "auto",
        "defaults_repo": "otterdog-e2e-defaults",
        "template_mode": "auto",
        "template_url": None,
        "identities": {"admin": IdentitySpec("admin", "e2e-admin-bot", "E2E_ADMIN_TOKEN")},
        "app": None,
        "admin_team": "otterdog-admins",
        "approval_team": "project-leads",
        "contributors_team": "e2e-contributors",
        "webapp": WebappSpec("relay", None, None, "e2e/otterdog-validate", "e2e/otterdog-sync", 1, 5000),
        "fixture_repos": ("otterdog-e2e-fixture-a",),
        "extra_protected_repos": (),
        "baseline_settings": {},
        "source_path": Path("targets/free.yaml"),
    }
    values.update(overrides)
    return Target(**values)


def member_http(
    *,
    scopes: Iterable[str] | None = ADMIN_SCOPES,
    orgs: Iterable[Mapping[str, Any]] = (TEST_ORG,),
    pending: Iterable[Mapping[str, Any]] = (),
    identity: str = "admin",
) -> FakeGitHubHttp:
    """A fake client of an identity: its scopes, org memberships and pending invitations."""
    http = FakeGitHubHttp(identity=identity, scopes=None if scopes is None else set(scopes))
    http.add("GET", "/user/orgs", json=list(orgs), repeat=True)
    invitations = [{"state": "pending", "role": "member", "organization": dict(org)} for org in pending]
    http.add("GET", "/user/memberships/orgs", json=invitations, repeat=True)
    return http


def admin_http(org_json: Mapping[str, Any] | None = None, **kw: Any) -> FakeGitHubHttp:
    """The admin's fake client answering GET /orgs/{org}."""
    http = member_http(**kw)
    http.add("GET", f"/orgs/{FAKE_ORG}", json=dict(org_json or default_org_json()), repeat=True)
    return http


def org_json(**changes: Any) -> dict[str, Any]:
    """GET /orgs/{org} answer with changes (None removes a key)."""
    data = default_org_json()
    for key, value in changes.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    return data


# --- denylist -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "login",
    [
        "eclipse",
        "Eclipse",
        "eclipse-jdt",
        "ECLIPSE-ee4j",
        "eclipsefdn",
        "EclipseFdn-Infra",
        "eclipse-csi",
        "adoptium",
        "jakartaee",
        "jakartaee-specs",
        "openhwgroup",
        "osgi",
        "jetty",
        "jetty-project",
        "microprofile",
        "microprofile-wg",
        "locationtech",
        "deeplearning4j",
        "EclipseNebula",
        "orcwg",
        "rust-sig",
        "winery",
        "cra-attestations",
        " eclipse ",
    ],
)
def test_check_org_allowed_refuses_production_orgs(login: str) -> None:
    """Every FORBIDDEN_ORG_PATTERNS entry, case-insensitively."""
    with pytest.raises(SafetyError, match="denylist"):
        check_org_allowed(login)


@pytest.mark.parametrize(
    "login",
    ["e2e-test-org", "eclipsed", "my-eclipse", "osgi-e2e", "adoptium-e2e", "winery-test", "rust-sig2", "orcwg-sandbox"],
)
def test_check_org_allowed_accepts_other_orgs(login: str) -> None:
    """Anchored patterns: look-alike test orgs are fine."""
    check_org_allowed(login)


def test_check_org_allowed_refuses_empty_logins() -> None:
    """An empty login is never a valid target."""
    for login in ("", "   "):
        with pytest.raises(SafetyError, match="empty"):
            check_org_allowed(login)


# --- VerifiedOrg ----------------------------------------------------------------------------------------------------
def test_verified_org_cannot_be_forged() -> None:
    """Only the module-private sentinel builds a VerifiedOrg; replace() and foreign tokens fail."""
    now = datetime.now(UTC)
    with pytest.raises(SafetyError):
        VerifiedOrg("e2e-test-org", 1, "free", "t", now, {})
    with pytest.raises(SafetyError):
        VerifiedOrg("e2e-test-org", 1, "free", "t", now, {}, object())
    verified = verify_target(admin_http(), make_target(), {"admin": ADMIN})
    with pytest.raises(SafetyError):
        dataclasses.replace(verified, login="eclipse")


# --- verify_target --------------------------------------------------------------------------------------------------
def test_verify_target_success() -> None:
    """A pinned, marked, free org with an isolated admin yields a VerifiedOrg (org_json is a private copy)."""
    http = admin_http()
    oracle = Identity("oracle", "e2e-admin-bot", ADMIN.token)
    verified = verify_target(http, make_target(), {"admin": ADMIN, "oracle": oracle})
    assert (verified.login, verified.org_id, verified.plan, verified.target) == (FAKE_ORG, FAKE_ORG_ID, "free", "free")
    assert verified.verified_at.tzinfo is not None
    assert verified.org_json["description"].startswith("[otterdog-e2e]")
    assert len(http.calls_to("GET", f"/orgs/{FAKE_ORG}")) == 1
    assert len(http.calls_to("GET", "/user/orgs")) == 1  # oracle == admin token: checked once
    [pending] = http.calls_to("GET", "/user/memberships/orgs")
    assert pending.params is not None and pending.params["state"] == "pending"


def test_verify_target_checks_the_denylist_before_any_request() -> None:
    """A forbidden target org never reaches GitHub."""
    http = admin_http()
    with pytest.raises(SafetyError, match="denylist"):
        verify_target(http, make_target(org="eclipse-jdt"), {"admin": ADMIN})
    assert http.calls == []


def test_verify_target_org_not_found() -> None:
    """404 (missing org or invisible to the token) is a SafetyError."""
    http = member_http()
    http.add("GET", f"/orgs/{FAKE_ORG}", status=404, json={"message": "Not Found"})
    with pytest.raises(SafetyError, match="not found"):
        verify_target(http, make_target(), {"admin": ADMIN})


def test_verify_target_wraps_github_errors_with_sso_hint() -> None:
    """GitHub failures become SafetyErrors (cause kept); SAML SSO is pointed out without echoing the link."""
    http = member_http()
    http.add(
        "GET",
        f"/orgs/{FAKE_ORG}",
        status=403,
        json={"message": "Resource protected by organization SAML enforcement."},
        headers={"X-GitHub-SSO": "required; url=https://github.com/orgs/x/sso?authorization_request=SSO-LINK"},
    )
    with pytest.raises(SafetyError, match="SAML SSO") as info:
        verify_target(http, make_target(), {"admin": ADMIN})
    assert isinstance(info.value.__cause__, GitHubError)
    assert "SSO-LINK" not in str(info.value)


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"id": 1}, "not the pinned github.org_id 424242"),
        ({"id": str(FAKE_ORG_ID)}, "not the pinned github.org_id"),
        ({"login": "E2E-Test-Org"}, "exact-case login"),
        ({"plan": None}, "must belong to an organization owner and carry the admin:org scope"),
        ({"plan": {"space": 1}}, "admin:org scope"),
        ({"plan": {"name": "team"}}, "is on plan 'team', target expects 'free'"),
        ({"description": "production org"}, "lacks the safety marker '[otterdog-e2e]'"),
        ({"description": None}, "lacks the safety marker"),
    ],
)
def test_verify_target_failures(changes: dict[str, Any], message: str) -> None:
    """Wrong id, wrong case, invisible or wrong plan, missing marker."""
    with pytest.raises(SafetyError, match=message.replace("[", r"\[").replace("]", r"\]")):
        verify_target(admin_http(org_json(**changes)), make_target(), {"admin": ADMIN})


def test_verify_target_plan_is_case_insensitive_and_marker_optional() -> None:
    """Plan names compare case-insensitively; require_marker=False (bootstrap) skips the marker."""
    http = admin_http(org_json(plan={"name": "Free"}, description=""))
    verified = verify_target(http, make_target(), {"admin": ADMIN}, require_marker=False)
    assert verified.plan == "free"


def test_verify_target_without_identity_checks() -> None:
    """check_identities=False only verifies the org."""
    http = admin_http(orgs=[FOREIGN_ORG])
    verify_target(http, make_target(), {"admin": ADMIN}, check_identities=False)
    assert http.calls_to("GET", "/user/orgs") == []


def test_verify_target_checks_every_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each identity is checked with its own client and role rules."""
    clients = {
        "oracle": member_http(identity="oracle", scopes=ADMIN_SCOPES),
        "author": member_http(identity="author", scopes=MEMBER_SCOPES),
        "outsider": member_http(identity="outsider", scopes={"public_repo", "read:org"}, orgs=[]),
        "config_reader": member_http(identity="config_reader", scopes=None, orgs=[]),
    }
    monkeypatch.setattr(safety, "identity_http", lambda identity, *, like: clients[identity.name])
    identities = {"admin": ADMIN} | {name: Identity(name, None, f"wpa-{name}-token-1") for name in clients}
    http = admin_http()
    verify_target(http, make_target(), identities)
    assert len(http.calls_to("GET", "/user/orgs")) == 1
    for client in clients.values():
        assert len(client.calls_to("GET", "/user/orgs")) == 1


def test_verify_target_names_the_failing_identity(monkeypatch: pytest.MonkeyPatch) -> None:
    """A machine account that belongs to a production org stops the session."""
    author = member_http(identity="author", scopes=MEMBER_SCOPES, orgs=[TEST_ORG, FOREIGN_ORG])
    monkeypatch.setattr(safety, "identity_http", lambda identity, *, like: author)
    identities = {"admin": ADMIN, "author": Identity("author", None, "wpa-author-token-1")}
    with pytest.raises(SafetyError, match=r"author: .*acme-production \(id 99, member\)"):
        verify_target(admin_http(), make_target(), identities)


def test_verify_target_detects_an_outsider_sharing_the_admin_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same token, stricter rules: the outsider check still runs (on the admin client) and fails."""

    def no_new_client(identity: Identity, *, like: Any) -> Any:
        """Shared tokens reuse the admin client."""
        raise AssertionError("unexpected client")

    monkeypatch.setattr(safety, "identity_http", no_new_client)
    identities = {"admin": ADMIN, "outsider": Identity("outsider", None, ADMIN.token)}
    with pytest.raises(SafetyError, match="outsider: token scopes admin:org"):
        verify_target(admin_http(), make_target(), identities)
    member_scoped = admin_http(scopes=MEMBER_SCOPES)  # even with member scopes the membership rule refuses it
    with pytest.raises(SafetyError, match="admin: token scopes public_repo"):
        verify_target(member_scoped, make_target(), identities)
    with pytest.raises(SafetyError, match="outsider: must not belong to the test organization"):
        check_identity_isolation(member_scoped, role="outsider", allowed_org_ids=(), test_org_id=FAKE_ORG_ID)


def test_verify_target_checks_the_admin_client_even_without_identities() -> None:
    """The admin client itself is always isolation-checked."""
    with pytest.raises(SafetyError, match="admin: the account belongs to organizations outside"):
        verify_target(admin_http(orgs=[TEST_ORG, FOREIGN_ORG]), make_target(), {})


# --- check_identity_isolation ---------------------------------------------------------------------------------------
def isolate(http: Any, role: str, allowed: Iterable[int] = (FAKE_ORG_ID,)) -> None:
    """check_identity_isolation against the fake test org."""
    check_identity_isolation(http, role=role, allowed_org_ids=tuple(allowed), test_org_id=FAKE_ORG_ID)


def test_isolation_accepts_dedicated_accounts() -> None:
    """Admin, member roles, a separate oracle with owner scopes and an outsider without orgs."""
    isolate(member_http(scopes=ALLOWED_SCOPES["admin"]), "admin")
    isolate(member_http(scopes=MEMBER_SCOPES), "author")
    isolate(member_http(scopes={"repo", "workflow", "read:org"}), "approver")
    isolate(member_http(scopes=ADMIN_SCOPES), "oracle")
    isolate(member_http(scopes=set()), "approver")
    isolate(member_http(scopes=MEMBER_SCOPES, orgs=[]), "outsider")
    isolate(member_http(scopes=MEMBER_SCOPES, orgs=[TEST_ORG, SECOND_TEST_ORG]), "author", (FAKE_ORG_ID, 777))
    isolate(member_http(scopes=MEMBER_SCOPES, orgs=[SECOND_TEST_ORG]), "outsider", (FAKE_ORG_ID, 777))


def test_isolation_allows_the_test_org_implicitly() -> None:
    """The pinned test org is always allowed for member roles."""
    isolate(member_http(scopes=MEMBER_SCOPES), "author", allowed=())


@pytest.mark.parametrize(
    ("role", "scopes", "message"),
    [
        ("admin", ADMIN_SCOPES | {"admin:enterprise"}, "admin:enterprise are not allowed"),
        ("admin", ADMIN_SCOPES | {"user"}, "user are not allowed"),
        ("author", MEMBER_SCOPES | {"admin:org"}, "admin:org are not allowed"),
        ("approver", {"delete_repo", "repo"}, "delete_repo are not allowed"),
        ("outsider", {"gist", "public_repo"}, "gist are not allowed"),
    ],
)
def test_isolation_refuses_excess_scopes(role: str, scopes: set[str], message: str) -> None:
    """Classic scopes must be a subset of the role's allowed scopes."""
    with pytest.raises(SafetyError, match=f"{role}: token scopes {message}"):
        isolate(member_http(scopes=scopes, orgs=[]), role)


def test_isolation_refuses_a_classic_config_reader_token() -> None:
    """The config_reader only reads public repositories: a classic PAT, whatever its scopes, is refused."""
    for scopes in (set(), {"public_repo"}):
        with pytest.raises(SafetyError, match="config_reader: needs a fine-grained PAT"):
            isolate(member_http(scopes=scopes, orgs=[]), "config_reader")


# --- fine-grained tokens: isolation proven on the token ---------------------------------------------------------------
OWNER_PROBES = (f"/orgs/{FAKE_ORG}/actions/permissions", f"/orgs/{FAKE_ORG}/hooks")
MEMBERSHIP = f"/user/memberships/orgs/{FAKE_ORG}"
ACCEPTED = {"X-Accepted-GitHub-Permissions": "administration=read"}


def fine_grained_http(role: str, *, owner: bool = True, membership: Mapping[str, Any] | None = None) -> FakeGitHubHttp:
    """A fine-grained token bound to the test org: owner probes (owner roles) or its own membership answer 200."""
    http = FakeGitHubHttp(identity=role, scopes=None)
    if owner:
        http.add("GET", OWNER_PROBES[0], json={"enabled_repositories": "all"}, repeat=True)
        http.add("GET", OWNER_PROBES[1], json=[], repeat=True)
    state = {"state": "active", "role": "member", "organization": dict(TEST_ORG)}
    http.add("GET", MEMBERSHIP, json=dict(membership or state), repeat=True)
    return http


def isolate_fg(http: Any, role: str, *, org: str | None = FAKE_ORG, token_type: str = "auto") -> None:  # noqa: S107
    """check_identity_isolation with the test org login (needed by fine-grained proofs)."""
    check_identity_isolation(
        http, role=role, allowed_org_ids=(FAKE_ORG_ID,), test_org_id=FAKE_ORG_ID, org=org, token_type=token_type
    )


@pytest.mark.parametrize("role", ["admin", "oracle"])
def test_fine_grained_owner_proven_by_owner_only_reads(role: str) -> None:
    """Owner roles: both org-owner-only reads answer 200; the account's org listings are not used."""
    http = fine_grained_http(role)
    isolate_fg(http, role, token_type="fine-grained")
    assert [call.path for call in http.calls] == list(OWNER_PROBES)


@pytest.mark.parametrize(("status", "probe"), [(403, 0), (404, 0), (403, 1), (401, 1)])
def test_fine_grained_owner_refused_when_a_probe_fails(status: int, probe: int) -> None:
    """A token bound to another owner (or without the permission) cannot read them: fail closed, with GitHub's hint."""
    http = FakeGitHubHttp(identity="admin", scopes=None)
    for index, path in enumerate(OWNER_PROBES):
        answer = status if index == probe else 200
        http.add("GET", path, status=answer, json={"message": "Resource not accessible"}, headers=ACCEPTED)
    with pytest.raises(SafetyError, match=f"admin: fine-grained token cannot read GET {OWNER_PROBES[probe]}") as info:
        isolate_fg(http, "admin")
    assert f"({status}; GitHub accepts: administration=read)" in str(info.value)
    assert "resource owner 'e2e-test-org'" in str(info.value) and isinstance(info.value.__cause__, GitHubError)


@pytest.mark.parametrize("role", ["admin", "oracle", "author", "approver"])
def test_fine_grained_needs_the_org_login(role: str) -> None:
    """Without the test org login nothing can be proven: fail closed."""
    with pytest.raises(SafetyError, match=f"{role}: the test org login is needed"):
        isolate_fg(fine_grained_http(role), role, org=None)


@pytest.mark.parametrize("role", ["author", "approver"])
def test_fine_grained_members_proven_by_their_membership(role: str) -> None:
    """author/approver: their active membership of the test org, read through an organization permission."""
    http = fine_grained_http(role, owner=False)
    isolate_fg(http, role)
    assert [call.path for call in http.calls] == [MEMBERSHIP]


@pytest.mark.parametrize(
    ("membership", "message"),
    [
        ({"state": "pending", "organization": dict(TEST_ORG)}, "state 'pending'"),
        ({"state": "active", "organization": dict(SECOND_TEST_ORG)}, "organization id 777"),
        ({"state": "active"}, "organization id None"),
    ],
)
def test_fine_grained_members_refused_without_an_active_membership(membership: dict[str, Any], message: str) -> None:
    """Pending or foreign memberships are no proof."""
    with pytest.raises(SafetyError, match=message):
        isolate_fg(fine_grained_http("author", owner=False, membership=membership), "author")


def test_fine_grained_member_refused_when_the_membership_is_not_readable() -> None:
    """A token bound to the user account (no organization permission) cannot read it."""
    http = FakeGitHubHttp(identity="approver", scopes=None)
    http.add("GET", MEMBERSHIP, status=403, json={"message": "Resource not accessible by personal access token"})
    with pytest.raises(SafetyError, match=f"approver: fine-grained token cannot read GET {MEMBERSHIP} .403"):
        isolate_fg(http, "approver")


def test_fine_grained_outsider_is_refused() -> None:
    """The outsider writes to repos of an org it does not belong to: impossible with a fine-grained token."""
    with pytest.raises(SafetyError, match="outsider: needs a classic PAT"):
        isolate_fg(fine_grained_http("outsider"), "outsider")


@pytest.mark.parametrize("role", ["admin", "oracle", "author", "approver", "outsider"])
def test_other_token_kinds_are_refused_for_writing_roles(role: str) -> None:
    """Tokens without X-OAuth-Scopes that are not github_pat_ (App/OAuth user tokens) are not bound to one owner."""
    http = FakeGitHubHttp(identity=role, scopes=None, token_kind=safety.OTHER_TOKEN)
    with pytest.raises(SafetyError, match=f"{role}: (needs a classic PAT|.*not a fine-grained PAT)"):
        isolate_fg(http, role)


def test_other_token_kinds_stay_accepted_for_read_only_roles() -> None:
    """The config_reader keeps its former rules (any non-classic token, visible memberships checked)."""
    for role in ("config_reader",):
        http = member_http(scopes=None, orgs=[], identity=role)
        http.token_kind = safety.OTHER_TOKEN
        isolate_fg(http, role)


@pytest.mark.parametrize(
    ("declared", "http", "found"),
    [
        ("classic", fine_grained_http("admin"), "a fine-grained PAT"),
        ("fine-grained", member_http(scopes=ADMIN_SCOPES), "a classic PAT"),
        ("fine-grained", FakeGitHubHttp(scopes=None, token_kind=safety.OTHER_TOKEN), "neither"),
    ],
)
def test_declared_token_type_must_match(declared: str, http: FakeGitHubHttp, found: str) -> None:
    """identities.<role>.token_type is checked against the detected kind before anything else."""
    with pytest.raises(
        SafetyError, match=f"admin: the target declares token_type '{declared}' but the token is {found}"
    ):
        isolate_fg(http, "admin", token_type=declared)
    assert http.calls == []


def test_declared_token_type_matching_passes() -> None:
    """Declared kinds equal to the detected ones (and auto) pass."""
    isolate_fg(member_http(scopes=ADMIN_SCOPES), "admin", token_type="classic")
    isolate_fg(fine_grained_http("admin"), "admin", token_type="fine-grained")
    isolate_fg(fine_grained_http("admin"), "admin", token_type="auto")


def test_verify_target_with_fine_grained_identities(monkeypatch: pytest.MonkeyPatch) -> None:
    """verify_target hands the org login and the declared token types to every check."""
    admin = admin_http(scopes=None)
    for path in OWNER_PROBES:
        admin.add("GET", path, json={}, repeat=True)
    author = fine_grained_http("author", owner=False)
    monkeypatch.setattr(safety, "identity_http", lambda identity, *, like: author)
    identities = {
        "admin": Identity("admin", "e2e-admin-bot", "github_pat_admin_1", "fine-grained"),
        "author": Identity("author", "e2e-author-bot", "github_pat_author_1", "fine-grained"),
    }
    verify_target(admin, make_target(), identities)
    assert admin.calls_to("GET", "/user/orgs") == [] and len(author.calls_to("GET", MEMBERSHIP)) == 1
    identities["author"] = dataclasses.replace(identities["author"], token_type="classic")
    with pytest.raises(SafetyError, match="author: the target declares token_type 'classic'"):
        verify_target(admin, make_target(), identities)


def test_isolation_accepts_fine_grained_readers_and_tolerates_hidden_listings() -> None:
    """Fine-grained readers: listings answering 403/404 are tolerated, visible memberships still checked."""
    reader = FakeGitHubHttp(identity="config_reader", scopes=None)
    reader.add("GET", "/user/orgs", json=[])
    reader.add("GET", "/user/memberships/orgs", status=403, json={"message": "Resource not accessible"})
    isolate(reader, "config_reader")
    isolate(member_http(scopes=None, orgs=[]), "config_reader")
    with pytest.raises(SafetyError, match="acme-production"):
        isolate(member_http(scopes=None, orgs=[FOREIGN_ORG]), "config_reader")


def test_isolation_refuses_classic_tokens_that_cannot_list_orgs() -> None:
    """Classic tokens without read:org cannot prove their isolation: fail closed."""
    http = FakeGitHubHttp(identity="author", scopes={"public_repo"})
    http.add("GET", "/user/orgs", status=403, json={"message": "Must have admin rights"})
    with pytest.raises(SafetyError, match="read:org") as info:
        isolate(http, "author")
    assert isinstance(info.value.__cause__, GitHubError)


@pytest.mark.parametrize(
    ("role", "orgs", "pending", "message"),
    [
        ("admin", [TEST_ORG, FOREIGN_ORG], [], r"acme-production \(id 99, member\)"),
        ("author", [TEST_ORG], [FOREIGN_ORG], r"acme-production \(id 99, invited\)"),
        ("author", [TEST_ORG, SECOND_TEST_ORG], [], r"e2e-second-org \(id 777, member\)"),
        ("outsider", [TEST_ORG], [], "outsider: must not belong to the test organization 'e2e-test-org' .member."),
        ("outsider", [], [TEST_ORG], "outsider: must not belong to the test organization 'e2e-test-org' .invited."),
        ("outsider", [FOREIGN_ORG], [], "outside github.allowed_org_ids"),
    ],
)
def test_isolation_refuses_foreign_memberships(
    role: str, orgs: list[dict[str, Any]], pending: list[dict[str, Any]], message: str
) -> None:
    """Memberships and pending invitations outside the allowed test orgs; outsiders must not touch the test org."""
    scopes = ADMIN_SCOPES if role == "admin" else MEMBER_SCOPES
    with pytest.raises(SafetyError, match=message):
        isolate(member_http(scopes=scopes, orgs=orgs, pending=pending), role)


def test_isolation_refuses_denylisted_orgs_even_when_allowed() -> None:
    """A production org stays refused even if its id was added to allowed_org_ids by mistake."""
    for role, orgs, pending in (("admin", [TEST_ORG, DENYLISTED_ORG], []), ("author", [TEST_ORG], [DENYLISTED_ORG])):
        scopes = ADMIN_SCOPES if role == "admin" else MEMBER_SCOPES
        with pytest.raises(
            SafetyError, match=f"{role}: the account belongs to the production organization 'eclipse-jdt'"
        ):
            isolate(member_http(scopes=scopes, orgs=orgs, pending=pending), role, allowed=(FAKE_ORG_ID, 98))


def test_verify_target_reuses_one_client_per_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """One client per distinct token; same token + same rules is checked once, different rules again."""
    built: list[str] = []
    shared_client = member_http(identity="shared", scopes=MEMBER_SCOPES, orgs=[])

    def build(identity: Identity, *, like: Any) -> Any:
        """Record client creation."""
        built.append(identity.name)
        return shared_client

    monkeypatch.setattr(safety, "identity_http", build)
    shared = "wpa-shared-token-9"
    identities = {
        "admin": ADMIN,
        "author": Identity("author", None, shared),
        "approver": Identity("approver", None, shared),  # same rules as author: not re-checked
        "outsider": Identity("outsider", None, shared),  # stricter rules: re-checked with the same client
    }
    verify_target(admin_http(), make_target(), identities)
    assert built == ["author"]
    assert len(shared_client.calls_to("GET", "/user/orgs")) == 2


def test_isolation_refuses_malformed_entries() -> None:
    """Entries without an organization id fail closed."""
    http = FakeGitHubHttp(identity="author", scopes=MEMBER_SCOPES)
    http.add("GET", "/user/orgs", json=[{"login": "mystery"}])
    with pytest.raises(SafetyError, match="without an organization id"):
        isolate(http, "author")
    http = FakeGitHubHttp(identity="author", scopes=MEMBER_SCOPES)
    http.add("GET", "/user/orgs", json=["not-an-org"])
    with pytest.raises(SafetyError, match="not an organization"):
        isolate(http, "author")


def test_isolation_wraps_scope_read_errors() -> None:
    """A failing GET /rate_limit (e.g. bad credentials) is a SafetyError."""
    http = member_http(scopes=MEMBER_SCOPES)

    def broken() -> safety.TokenInfo:
        """Bad credentials."""
        raise GitHubError(401, "GET", f"{API}/rate_limit", '{"message": "Bad credentials"}')

    http.token_info = broken  # type: ignore[method-assign]
    with pytest.raises(SafetyError, match="cannot read the token scopes"):
        isolate(http, "author")


# --- the real GitHubHttp (WP-B) through `responses` -----------------------------------------------------------------
def _auth(token: str) -> list[Any]:
    """Matcher for requests sent with ``token``."""
    return [matchers.header_matcher({"Authorization": f"Bearer {token}"})]


def _register_identity(
    rsps: responses.RequestsMock, token: str, scopes: str | None, orgs: list[dict[str, Any]], pages: int = 1
) -> None:
    """GitHub answers for one identity: /rate_limit scopes, paginated /user/orgs and pending memberships."""
    headers = {} if scopes is None else {"X-OAuth-Scopes": scopes}
    rsps.get(f"{API}/rate_limit", json={"resources": {}}, headers=headers, match=_auth(token))
    if pages == 2:
        next_link = {"Link": f'<{API}/user/orgs?per_page=100&page=2>; rel="next"'}
        rsps.get(
            f"{API}/user/orgs", json=orgs[:1], headers=next_link, match=[*_auth(token), _query({"per_page": "100"})]
        )
        rsps.get(f"{API}/user/orgs", json=orgs[1:], match=[*_auth(token), _query({"per_page": "100", "page": "2"})])
    else:
        rsps.get(f"{API}/user/orgs", json=orgs, match=_auth(token))
    pending = _query({"state": "pending", "per_page": "100"})
    rsps.get(f"{API}/user/memberships/orgs", json=[], match=[*_auth(token), pending])


def _query(params: dict[str, str]) -> Any:
    """Exact query string matcher."""
    return matchers.query_param_matcher(params)


def test_identity_http_builds_read_only_clients() -> None:
    """Other tokens get their own read-only client; the same token reuses the admin client."""
    admin = GitHubHttp(ADMIN.token, sleep=lambda _s: None, identity="admin")
    assert safety.identity_http(Identity("oracle", None, ADMIN.token), like=admin) is admin
    author = safety.identity_http(Identity("author", None, "wpa-author-token-2"), like=admin)
    assert author is not admin
    assert (author.token, author.read_only, author.identity) == ("wpa-author-token-2", True, "author")


def test_verify_target_with_real_http() -> None:
    """End to end with the real client: pinned org, paginated memberships, per-identity tokens."""
    target = make_target()
    author_token = "wpa-author-token-3"
    with responses.RequestsMock() as rsps:
        rsps.get(f"{API}/orgs/{FAKE_ORG}", json=default_org_json(), match=_auth(ADMIN.token))
        _register_identity(rsps, ADMIN.token, "repo, admin:org, read:org, workflow", [TEST_ORG, SECOND_TEST_ORG], 2)
        _register_identity(rsps, author_token, "public_repo, read:org", [TEST_ORG])
        verified = verify_target(
            GitHubHttp(ADMIN.token, sleep=lambda _s: None, identity="admin"),
            dataclasses.replace(target, allowed_org_ids=(FAKE_ORG_ID, 777)),
            {"admin": ADMIN, "author": Identity("author", "e2e-author-bot", author_token)},
        )
    assert (verified.login, verified.org_id, verified.plan) == (FAKE_ORG, FAKE_ORG_ID, "free")


def test_isolation_with_real_http_refuses_foreign_orgs_and_fine_grained() -> None:
    """The real client reports X-OAuth-Scopes (or none for fine-grained tokens) and paginates."""
    with responses.RequestsMock() as rsps:
        _register_identity(rsps, "wpa-author-token-4", "public_repo, read:org", [TEST_ORG, FOREIGN_ORG], 2)
        with pytest.raises(SafetyError, match="acme-production"):
            isolate(GitHubHttp("wpa-author-token-4", sleep=lambda _s: None), "author")
    with responses.RequestsMock(assert_all_requests_are_fired=False) as rsps:
        _register_identity(rsps, "wpa-fine-token-5", None, [])
        with pytest.raises(SafetyError, match="fine-grained"):
            isolate(GitHubHttp("wpa-fine-token-5", sleep=lambda _s: None), "approver")


# --- GitHub App isolation (DESTR-01) --------------------------------------------------------------------------------
def org_installation(org: Mapping[str, Any], *, kind: str = "Organization", **fields: Any) -> dict[str, Any]:
    """A GET /app/installations item on ``org``."""
    account = {"login": org["login"], "id": org["id"], "type": kind}
    return {"id": 1000 + int(org["id"]), "account": account, "target_id": org["id"], "target_type": kind, **fields}


def fake_app(**kw: Any) -> Any:
    """A FakeAppAuth owned by and installed on the fake test org (overridable)."""
    from otterdog_e2e.testing.fakes import FakeAppAuth

    return FakeAppAuth(**kw)


def test_verify_app_accepts_the_test_org_app() -> None:
    """An App owned by the test org and installed there only passes; GET /app is read again (refresh)."""
    app = fake_app()
    isolation = safety.verify_app(app, make_target())
    assert isolation.owner == FAKE_ORG and isolation.installations == (FAKE_ORG,)
    assert ("get_app", (True,)) in app.calls and ("installations", ()) in app.calls


@pytest.mark.parametrize(
    ("owner", "message"),
    [
        ({"login": "some-dev", "id": 5, "type": "User"}, "owned by 'some-dev'"),
        ({"login": "acme-production", "id": 99, "type": "Organization"}, "owned by 'acme-production'"),
        ({"login": FAKE_ORG, "id": 1, "type": "Organization"}, "id 1"),  # same login, other id (recreated org)
        ({"login": FAKE_ORG, "id": FAKE_ORG_ID, "type": "User"}, "type 'User'"),
        ({"slug": "acme-enterprise", "id": FAKE_ORG_ID}, "acme-enterprise"),  # enterprise-owned App
        ({}, "owned by '?'"),
    ],
)
def test_verify_app_refuses_apps_not_owned_by_the_test_org(owner: dict[str, Any], message: str) -> None:
    """The owner must be the pinned test organization (type Organization, id == org_id)."""
    with pytest.raises(SafetyError, match="not by the test organization") as raised:
        safety.verify_app(fake_app(owner=owner), make_target())
    assert message in str(raised.value)


@pytest.mark.parametrize(
    "installation",
    [
        org_installation(FOREIGN_ORG),
        org_installation({"login": "a-user", "id": 5}, kind="User"),
        org_installation({"login": "acme-enterprise", "id": FAKE_ORG_ID}, kind="Enterprise"),
        {"id": 7, "account": None},  # no account at all
    ],
)
def test_verify_app_refuses_installations_outside_the_test_orgs(installation: dict[str, Any]) -> None:
    """A public App owned by the test org but installed elsewhere would hand that account to the SUT."""
    with pytest.raises(SafetyError, match="installed outside the test organizations"):
        safety.verify_app(fake_app(extra_installations=[installation]), make_target())


def test_verify_app_allows_other_test_orgs_but_never_denylisted_ones() -> None:
    """Installations on allowed_org_ids pass; a denylisted org is refused even when its id was allowed."""
    target = make_target(allowed_org_ids=(FAKE_ORG_ID, SECOND_TEST_ORG["id"], DENYLISTED_ORG["id"]))
    isolation = safety.verify_app(fake_app(extra_installations=[org_installation(SECOND_TEST_ORG)]), target)
    assert isolation.installations == (FAKE_ORG, "e2e-second-org")
    with pytest.raises(SafetyError, match="eclipse-jdt"):
        safety.verify_app(fake_app(extra_installations=[org_installation(DENYLISTED_ORG)]), target)


def test_verify_app_refuses_a_listing_shorter_than_installations_count() -> None:
    """installations_count above the listed installations (truncated listing) proves nothing: refused."""
    with pytest.raises(SafetyError, match="reports 3 installation"):
        safety.verify_app(fake_app(installations_count=3), make_target())


def test_verify_app_wraps_github_errors() -> None:
    """A failing GET /app or /app/installations is a SafetyError (fail closed)."""

    class Broken:
        """AppAuth whose JWT is refused."""

        def get_app(self, *, refresh: bool = False) -> dict[str, Any]:
            """401."""
            raise GitHubError(401, "GET", "/app", "A JSON web token could not be decoded")

        def installations(self) -> list[dict[str, Any]]:
            """Never reached."""
            raise AssertionError

    with pytest.raises(SafetyError, match="cannot verify the GitHub App"):
        safety.verify_app(Broken(), make_target())


# --- token kinds and expiration (GET /rate_limit) -------------------------------------------------------------------
@pytest.mark.parametrize(
    ("token", "headers", "kind", "scopes"),
    [
        ("ghp_classic_1", {"X-OAuth-Scopes": "repo, admin:org"}, "classic", frozenset({"repo", "admin:org"})),
        ("ghp_classic_2", {"X-OAuth-Scopes": ""}, "classic", frozenset()),
        ("github_pat_fine_1", {}, "fine-grained", None),
        ("ghs_installation_1", {}, "other", None),
    ],
)
def test_token_info_with_real_http(token: str, headers: dict[str, str], kind: str, scopes: Any) -> None:
    """X-OAuth-Scopes present = classic; absent = fine-grained for github_pat_ tokens, other kinds otherwise."""
    with responses.RequestsMock() as rsps:
        rsps.get(f"{API}/rate_limit", json={"resources": {}}, headers=headers, match=_auth(token))
        info = GitHubHttp(token, sleep=lambda _s: None).token_info()
    assert (info.kind, info.scopes, info.expires_at) == (kind, scopes, None)


def test_token_info_reads_the_expiration_header() -> None:
    """github-authentication-token-expiration is parsed (kept raw when the format is unknown)."""
    with responses.RequestsMock() as rsps:
        expiring = {"github-authentication-token-expiration": "2026-11-03 12:30:00 UTC"}
        rsps.get(f"{API}/rate_limit", json={}, headers=expiring)
        rsps.get(f"{API}/rate_limit", json={}, headers={"github-authentication-token-expiration": "soon"})
        http = GitHubHttp("github_pat_fine_2", sleep=lambda _s: None)
        first, second = http.token_info(), http.token_info()
    assert first.expires_at == datetime(2026, 11, 3, 12, 30, tzinfo=UTC)
    assert (second.expires_at, second.expiration_header) == (None, "soon")


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-11-03 12:30:00 UTC", datetime(2026, 11, 3, 12, 30, tzinfo=UTC)),
        ("2026-11-03 14:30:00 +0200", datetime(2026, 11, 3, 12, 30, tzinfo=UTC)),
        ("2026-11-03T12:30:00+00:00", datetime(2026, 11, 3, 12, 30, tzinfo=UTC)),
        ("", None),
        (None, None),
        ("next week", None),
    ],
)
def test_parse_token_expiration(value: str | None, expected: datetime | None) -> None:
    """The header formats seen in the wild (to confirm on the first live run) and garbage."""
    assert safety.parse_token_expiration(value) == expected


def test_token_kind() -> None:
    """Classification of GET /rate_limit answers."""
    assert safety.token_kind("repo", "github_pat_x") == "classic"
    assert safety.token_kind(None, "github_pat_x") == "fine-grained"
    assert safety.token_kind(None, "ghu_x") == safety.token_kind(None, None) == "other"
