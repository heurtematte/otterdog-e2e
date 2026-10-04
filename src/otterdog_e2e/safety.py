"""Safety model (SPEC 5): the org pin, the verified-org capability and identity isolation.

A ``VerifiedOrg`` can only be created by ``verify_target`` (its constructor requires a module-private sentinel). Every
component able to mutate GitHub (Mutator, TemplatePublisher, Janitor, OrgLease, WebappStack, live OtterdogCli,
GitHubHttp with write_scope) requires one, so no mutation path can be built without the checks having passed.

verify_target raises SafetyError for every failed check (GitHub errors included, chained as ``__cause__``).

Identity isolation depends on the kind of token (docs/security.md, "Fine-grained personal access tokens"):

- classic PAT (GET /rate_limit answers X-OAuth-Scopes): its scopes must be allowed for the role and the ACCOUNT may
  only belong to test organizations (GET /user/orgs, GET /user/memberships/orgs?state=pending);
- fine-grained PAT (``github_pat_``, no X-OAuth-Scopes): bound to ONE resource owner, so isolation is proven on the
  TOKEN: owner roles must read org-owner-only data of the test org (FINE_GRAINED_OWNER_PROBES), author/approver their
  own active membership of the test org through an organization permission (FINE_GRAINED_MEMBER_PROBE). GitHub
  answers GET /user/orgs with an empty list for fine-grained tokens, so the account check proves nothing for them.
  The outsider cannot use one (it must write to repos of an org it does not belong to), the read-only roles keep their
  former rules.
"""

from __future__ import annotations

import copy
import logging
import re
from collections.abc import Collection, Mapping
from dataclasses import InitVar, dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.settings import Identity, Target

_logger = logging.getLogger(__name__)


class SafetyError(RuntimeError):
    """A safety precondition does not hold; the operation must not proceed."""


FORBIDDEN_ORG_PATTERNS: tuple[str, ...] = (
    r"^eclipse($|-)",
    r"^eclipsefdn",
    r"^eclipse-csi$",
    r"^adoptium$",
    r"^jakartaee",
    r"^openhwgroup",
    r"^osgi$",
    r"^jetty",
    r"^microprofile",
    r"^locationtech",
    r"^deeplearning4j$",
    r"^eclipsenebula$",
    r"^orcwg$",
    r"^rust-sig$",
    r"^winery$",
    r"^cra-attestations$",
)  # matched case-insensitively against org logins
_FORBIDDEN_RES = tuple(re.compile(pattern, re.IGNORECASE) for pattern in FORBIDDEN_ORG_PATTERNS)

ALLOWED_SCOPES: Mapping[str, frozenset[str]] = {
    "admin": frozenset(
        {"repo", "workflow", "admin:org", "admin:org_hook", "delete_repo", "read:org", "read:user", "user:email"}
    ),
    "other": frozenset({"public_repo", "repo", "read:org", "read:user", "user:email", "workflow"}),
}
# roles checked against ALLOWED_SCOPES["admin"]: the oracle falls back to the admin token and, when separate, needs
# owner reads (admin:org, admin:org_hook) for org-level ground truth (GH-10)
OWNER_ROLES = frozenset({"admin", "oracle"})
MEMBER_ROLES = frozenset({"author", "approver"})  # active members of the test org (no owner rights)
READ_ONLY_ROLES = frozenset({"config_reader", "readonly"})  # read public data only: any non-classic token accepted
OUTSIDER_ROLE = "outsider"  # must NOT belong to (or be invited by) the test org
# roles allowed to use fine-grained PATs: every role but the outsider (see CLASSIC_ONLY_ROLES of settings)
FINE_GRAINED_ROLES = OWNER_ROLES | MEMBER_ROLES | READ_ONLY_ROLES

# token kinds (TokenInfo.kind); the declared identities.<role>.token_type uses the first two
CLASSIC, FINE_GRAINED, OTHER_TOKEN = "classic", "fine-grained", "other"
FINE_GRAINED_PREFIX = "github_pat_"  # classic PATs start with ghp_, App/OAuth tokens with ghs_/ghu_/gho_
TOKEN_EXPIRATION_HEADER = "github-authentication-token-expiration"  # noqa: S105 - a header name, sent for expiring tokens
_EXPIRATION_FORMATS = ("%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S %z", "%Y-%m-%dT%H:%M:%S%z")


@dataclass(frozen=True)
class TokenInfo:
    """What GET /rate_limit reveals about a token: kind, classic scopes and expiration."""

    kind: str  # CLASSIC, FINE_GRAINED or OTHER_TOKEN (App installation / user-to-server tokens, unknown prefixes)
    scopes: frozenset[str] | None = None  # classic scopes (None for other kinds)
    expires_at: datetime | None = None  # None: no expiration header (classic tokens may never expire)
    expiration_header: str | None = None  # raw header value (kept when it cannot be parsed)


def token_kind(scopes_header: str | None, token: str | None) -> str:
    """CLASSIC when X-OAuth-Scopes is present, FINE_GRAINED for a ``github_pat_`` token without it, else OTHER_TOKEN."""
    if scopes_header is not None:
        return CLASSIC
    return FINE_GRAINED if (token or "").startswith(FINE_GRAINED_PREFIX) else OTHER_TOKEN


def parse_token_expiration(value: str | None) -> datetime | None:
    """Aware datetime of a github-authentication-token-expiration value (``2026-11-03 12:00:00 UTC``), else None."""
    text = (value or "").strip()
    for fmt in _EXPIRATION_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)  # noqa: DTZ007 - naive values are UTC (below)
        except ValueError:
            continue
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


@dataclass(frozen=True)
class PermissionProbe:
    """A read that needs a fine-grained permission (path template with {org}; the permission as shown on GitHub)."""

    path: str
    permission: str


# org-owner-only reads: a fine-grained token answers 200 only when its resource owner is the org AND its user is an
# owner; classic tokens need admin:org / admin:org_hook (openapi: actions/get-github-actions-permissions-organization,
# orgs/list-webhooks; ghdocs fine-grained permission tables "Administration" and "Webhooks", organization permissions)
FINE_GRAINED_OWNER_PROBES = (
    PermissionProbe("/orgs/{org}/actions/permissions", "Organization > Administration: Read-only"),
    PermissionProbe("/orgs/{org}/hooks", "Organization > Webhooks: Read-only"),
)
# the token user's own membership, through an ORGANIZATION permission (only granted on the token's resource owner)
FINE_GRAINED_MEMBER_PROBE = PermissionProbe("/user/memberships/orgs/{org}", "Organization > Members: Read-only")

_SENTINEL = object()


@dataclass(frozen=True)
class VerifiedOrg:
    """Proof that the target org passed verify_target (only verify_target can construct it)."""

    login: str
    org_id: int
    plan: str
    target: str
    verified_at: datetime
    org_json: Mapping[str, Any] = field(repr=False, compare=False)
    _token: InitVar[object] = None

    def __post_init__(self, _token: object) -> None:
        """Refuse construction without the module-private sentinel."""
        if _token is not _SENTINEL:
            raise SafetyError("VerifiedOrg can only be created by safety.verify_target()")


def _mint_verified_org(
    *,
    login: str,
    org_id: int,
    plan: str,
    target: str,
    org_json: Mapping[str, Any],
    verified_at: datetime | None = None,
) -> VerifiedOrg:
    """Create a VerifiedOrg (for verify_target and otterdog_e2e.testing.fakes only)."""
    return VerifiedOrg(
        login=login,
        org_id=org_id,
        plan=plan,
        target=target,
        verified_at=verified_at or datetime.now(UTC),
        org_json=org_json,
        _token=_SENTINEL,
    )


def check_org_allowed(login: str) -> None:
    """Raise SafetyError when ``login`` is empty or matches FORBIDDEN_ORG_PATTERNS (case-insensitive)."""
    name = (login or "").strip()
    if not name:
        raise SafetyError("empty organization login")
    for pattern in _FORBIDDEN_RES:
        if pattern.search(name):
            raise SafetyError(
                f"organization {name!r} matches the production denylist ({pattern.pattern}): never target it"
            )


def _describe(exc: BaseException) -> str:
    """Short redacted description of a failed GitHub call (with a hint when GitHub asks for SAML SSO)."""
    text = REDACTOR(f"{type(exc).__name__}: {exc}")[:300]
    headers = getattr(exc, "headers", None) or {}
    if any(str(key).lower() == "x-github-sso" for key in headers):
        text += " (SAML SSO: authorize the token for this organization)"
    return text


def _fetch_org(http: GitHubHttp, org: str) -> Mapping[str, Any]:
    """GET /orgs/{org} (SafetyError when missing, invisible or failing)."""
    try:
        data = http.get(f"/orgs/{org}", allow_404=True)
    except SafetyError:
        raise
    except Exception as exc:
        raise SafetyError(f"cannot read organization {org!r} with the admin token: {_describe(exc)}") from exc
    if data is None:
        raise SafetyError(f"organization {org!r} not found (or not visible to the admin token)")
    if not isinstance(data, Mapping):
        raise SafetyError(f"unexpected GET /orgs/{org} answer ({type(data).__name__})")
    return data


def _check_org_pin(org_json: Mapping[str, Any], target: Target) -> None:
    """Exact-case login, pinned numeric id and denylist of the live org."""
    login, org_id = org_json.get("login"), org_json.get("id")
    if login != target.org:
        raise SafetyError(f"GitHub reports login {login!r} for target org {target.org!r}: use the exact-case login")
    if isinstance(org_id, bool) or not isinstance(org_id, int) or org_id != target.org_id:
        raise SafetyError(
            f"organization {target.org!r} has id {org_id!r}, not the pinned github.org_id {target.org_id} "
            "(renamed, recreated or wrong organization)"
        )
    check_org_allowed(login)


def _check_plan(org_json: Mapping[str, Any], target: Target) -> str:
    """Live plan name (visible to owners with admin:org only) must equal target.expected_plan."""
    plan_info = org_json.get("plan")
    plan = plan_info.get("name") if isinstance(plan_info, Mapping) else None
    if not isinstance(plan, str) or not plan:
        raise SafetyError(
            f"the plan of {target.org!r} is not visible: the admin token must belong to an organization owner and "
            "carry the admin:org scope (classic PAT), or the Organization > Plan and Administration read permissions "
            "with the test org as resource owner (fine-grained PAT)"
        )
    if plan.lower() != target.expected_plan:
        raise SafetyError(f"organization {target.org!r} is on plan {plan!r}, target expects {target.expected_plan!r}")
    return plan.lower()


def _check_marker(org_json: Mapping[str, Any], target: Target) -> None:
    """The org description must contain the safety marker."""
    description = org_json.get("description") or ""
    if not isinstance(description, str) or target.marker not in description:
        raise SafetyError(
            f"the description of {target.org!r} lacks the safety marker {target.marker!r} "
            "(dedicated test orgs only: run `otterdog-e2e bootstrap` to set it)"
        )


def identity_http(identity: Identity, *, like: GitHubHttp) -> GitHubHttp:
    """Read-only client of ``identity`` (``like`` itself when it holds the same token); tests monkeypatch this."""
    if identity.token == getattr(like, "token", None):
        return like
    from otterdog_e2e.github.http import GITHUB_API, GitHubHttp

    return GitHubHttp(
        identity.token,
        base_url=getattr(like, "base_url", GITHUB_API),
        timeout=getattr(like, "timeout", 30.0),
        read_only=True,
        identity=identity.name,
    )


def _rules(role: str) -> tuple[frozenset[str], bool, bool]:
    """(allowed classic scopes, fine-grained token accepted, outsider membership rule) of a role."""
    scopes = ALLOWED_SCOPES["admin"] if role in OWNER_ROLES else ALLOWED_SCOPES["other"]
    return scopes, role in FINE_GRAINED_ROLES, role == OUTSIDER_ROLE


def _check_all_identities(admin_http: GitHubHttp, target: Target, identities: Mapping[str, Identity]) -> None:
    """Isolation of the admin client and of every identity (each distinct token/rule pair checked once)."""
    allowed, test_org_id = target.allowed_org_ids, target.org_id
    admin = identities.get("admin")
    admin_type = admin.token_type if admin is not None else "auto"
    check_identity_isolation(
        admin_http,
        role="admin",
        allowed_org_ids=allowed,
        test_org_id=test_org_id,
        org=target.org,
        token_type=admin_type,
    )
    admin_token = getattr(admin_http, "token", None)
    if admin_token is None and admin is not None:
        admin_token = admin.token  # clients without a token attribute (fakes) stand for the admin
    checked = {(admin_token, _rules("admin"), "admin" in OWNER_ROLES, admin_type)}
    clients: dict[str | None, GitHubHttp] = {admin_token: admin_http}  # one client per distinct token
    for name, identity in identities.items():
        key = (identity.token, _rules(name), name in OWNER_ROLES, identity.token_type)
        if key in checked:
            continue
        checked.add(key)
        if identity.token not in clients:
            clients[identity.token] = identity_http(identity, like=admin_http)
        check_identity_isolation(
            clients[identity.token],
            role=name,
            allowed_org_ids=allowed,
            test_org_id=test_org_id,
            org=target.org,
            token_type=identity.token_type,
        )


def verify_target(
    admin_http: GitHubHttp,
    target: Target,
    identities: Mapping[str, Identity],
    *,
    require_marker: bool = True,
    check_identities: bool = True,
) -> VerifiedOrg:
    """GET /orgs/{org} with the ADMIN token and check login (exact case), id, denylist, plan and marker, then isolation.

    login == target.org; id == target.org_id; check_org_allowed; plan.name present (owner + admin:org) and equal to
    target.expected_plan; description contains target.marker (unless require_marker is False); then
    check_identity_isolation for every identity (unless check_identities is False).
    """
    check_org_allowed(target.org)  # before any request
    org_json = _fetch_org(admin_http, target.org)
    _check_org_pin(org_json, target)
    plan = _check_plan(org_json, target)
    if require_marker:
        _check_marker(org_json, target)
    if check_identities:
        _check_all_identities(admin_http, target, identities)
    verified = _mint_verified_org(
        login=target.org,
        org_id=target.org_id,
        plan=plan,
        target=target.name,
        org_json=copy.deepcopy(dict(org_json)),
    )
    _logger.info(
        "verified organization %s (id %d, plan %s) for target %s", target.org, target.org_id, plan, target.name
    )
    return verified


def read_token_info(http: GitHubHttp, role: str) -> TokenInfo:
    """Kind, scopes and expiration of the client's token (GET /rate_limit); SafetyError when unreadable."""
    try:
        info = http.token_info()
    except SafetyError:
        raise
    except Exception as exc:
        raise SafetyError(f"{role}: cannot read the token scopes: {_describe(exc)}") from exc
    if not isinstance(info, TokenInfo):
        raise SafetyError(f"{role}: unexpected token information ({type(info).__name__})")
    return info


def _check_token_type(role: str, info: TokenInfo, declared: str) -> None:
    """The declared identities.<role>.token_type (auto, classic, fine-grained) must match the detected kind."""
    if declared in ("auto", "", None) or declared == info.kind:
        return
    found = {CLASSIC: "a classic PAT", FINE_GRAINED: "a fine-grained PAT"}.get(
        info.kind, "neither a classic nor a fine-grained PAT"
    )
    raise SafetyError(
        f"{role}: the target declares token_type {declared!r} but the token is {found} (X-OAuth-Scopes "
        f"{'present' if info.kind == CLASSIC else 'absent'} on GET /rate_limit): fix identities.{role}.token_type or "
        "the token"
    )


def _check_scopes(role: str, scopes: set[str] | None) -> None:
    """Classic scopes must be allowed for the role (non-classic tokens are checked by _check_fine_grained)."""
    allowed, _, _ = _rules(role)
    if scopes is None:
        return
    extra = scopes - allowed
    if extra:
        raise SafetyError(
            f"{role}: token scopes {', '.join(sorted(extra))} are not allowed (allowed: {', '.join(sorted(allowed))})"
        )


def _org_of(item: Any, path: str, role: str) -> tuple[int, str]:
    """(id, login) of a /user/orgs item or the organization of a /user/memberships/orgs item."""
    org = item.get("organization") if isinstance(item, Mapping) and "organization" in item else item
    if not isinstance(org, Mapping):
        raise SafetyError(f"{role}: unexpected {path} entry (not an organization)")
    org_id = org.get("id")
    if isinstance(org_id, bool) or not isinstance(org_id, int):
        raise SafetyError(f"{role}: unexpected {path} entry without an organization id")
    return org_id, str(org.get("login") or "?")


def _list_orgs(
    http: GitHubHttp, path: str, params: Mapping[str, str] | None, role: str, *, tolerate: bool
) -> dict[int, str]:
    """Org ids -> logins listed at ``path``; listing errors are SafetyErrors (403/404 tolerated when ``tolerate``)."""
    try:
        items = http.paginate(path, params=params)
    except SafetyError:
        raise
    except Exception as exc:
        status = getattr(exc, "status", None)
        if tolerate and status in (403, 404):
            _logger.info("%s: %s not available for this fine-grained token (%s)", role, path, status)
            return {}
        raise SafetyError(
            f"{role}: cannot list {path} ({_describe(exc)}); classic tokens need the read:org scope"
        ) from exc
    return dict(_org_of(item, path, role) for item in items)


def _refuse_production_orgs(role: str, memberships: Mapping[int, tuple[str, str]]) -> None:
    """Denylisted orgs are refused even when their id was put into allowed_org_ids by mistake."""
    for login, state in memberships.values():
        try:
            check_org_allowed(login)
        except SafetyError:
            raise SafetyError(
                f"{role}: the account belongs to the production organization {login!r} ({state})"
            ) from None


def _check_memberships(
    role: str, active: Mapping[int, str], pending: Mapping[int, str], allowed: set[int], test_org_id: int
) -> None:
    """Every (pending) membership must be a test org; the outsider must not belong to the test org."""
    _, _, outsider = _rules(role)
    memberships = {oid: (login, "member") for oid, login in active.items()}
    memberships.update({oid: (login, "invited") for oid, login in pending.items() if oid not in memberships})
    _refuse_production_orgs(role, memberships)
    if outsider:
        if test_org_id in memberships:
            login, state = memberships[test_org_id]
            raise SafetyError(f"{role}: must not belong to the test organization {login!r} ({state})")
        allowed = allowed - {test_org_id}
    else:
        allowed = allowed | {test_org_id}
    foreign = sorted((login, oid, state) for oid, (login, state) in memberships.items() if oid not in allowed)
    if foreign:
        listed = ", ".join(f"{login} (id {oid}, {state})" for login, oid, state in foreign)
        raise SafetyError(
            f"{role}: the account belongs to organizations outside github.allowed_org_ids: {listed}; identities must "
            "be dedicated machine accounts that only belong to test organizations"
        )


APP_OWNER_TYPE = "Organization"  # owner.type of an App created in an organization (GET /app)


@dataclass(frozen=True)
class AppIsolation:
    """What verify_app established: the App's owner and the accounts it is installed on."""

    slug: str
    owner: str
    installations: tuple[str, ...]


def _int_or_none(value: Any) -> int | None:
    """An int that is not a bool, else None."""
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _installation_account(installation: Mapping[str, Any]) -> tuple[int | None, str, str]:
    """(id, login, type) of the account an installation belongs to (account, else target_id/target_type)."""
    account = installation.get("account")
    account = account if isinstance(account, Mapping) else {}
    account_id = _int_or_none(account.get("id"))
    if account_id is None:
        account_id = _int_or_none(installation.get("target_id"))
    kind = str(installation.get("target_type") or account.get("type") or "?")
    login = str(account.get("login") or account.get("slug") or "?")
    return account_id, login, kind


def verify_app(app: Any, target: Target) -> AppIsolation:
    """Raise SafetyError unless the GitHub App can only reach test organizations (DESTR-01).

    The App private key reaches the webapp under test, untrusted PR images included, and with it every installation of
    the App (``GET /app/installations`` + ``POST /app/installations/<id>/access_tokens``). Token isolation does not
    cover it, so before the key is handed out: ``GET /app`` (fresh) must name the test organization as owner
    (``owner.type`` Organization, ``owner.id`` == the pinned org id), and every installation listed by
    ``GET /app/installations`` must be an organization installation on the test org, or on another id of
    ``github.allowed_org_ids`` that passes check_org_allowed; ``installations_count`` must not exceed the listing (a
    truncated listing cannot prove anything). ``app`` is an AppAuth (``get_app(refresh=True)``, ``installations()``).
    """
    check_org_allowed(target.org)
    try:
        info = app.get_app(refresh=True)
        installations = list(app.installations())
    except SafetyError:
        raise
    except Exception as exc:
        raise SafetyError(f"cannot verify the GitHub App (GET /app, /app/installations): {_describe(exc)}") from exc
    slug = str(info.get("slug") or info.get("id") or "?")
    owner = info.get("owner")
    owner = owner if isinstance(owner, Mapping) else {}
    owner_id, owner_login = _int_or_none(owner.get("id")), str(owner.get("login") or owner.get("slug") or "?")
    if owner.get("type") != APP_OWNER_TYPE or owner_id != target.org_id or owner_login.lower() != target.org.lower():
        raise SafetyError(
            f"the GitHub App {slug!r} is owned by {owner_login!r} (type {owner.get('type')!r}, id {owner_id}), not by "
            f"the test organization {target.org!r} (id {target.org_id}): its private key reaches the webapp under test "
            "(untrusted PR images included), so only an App created in the test org is accepted "
            "(otterdog-e2e app-manifest, docs/github-app.md)"
        )
    allowed = {int(oid) for oid in target.allowed_org_ids} | {target.org_id}
    accounts, foreign = [], []
    for installation in installations:
        account_id, login, kind = _installation_account(installation)
        accounts.append(login)
        safe = kind == APP_OWNER_TYPE and account_id in allowed
        if safe and account_id != target.org_id:
            try:
                check_org_allowed(login)
            except SafetyError:
                safe = False
        if not safe:
            foreign.append(f"{login} ({kind}, id {account_id})")
    if foreign:
        raise SafetyError(
            f"the GitHub App {slug!r} is installed outside the test organizations (github.allowed_org_ids): "
            f"{', '.join(sorted(foreign))}; its private key would reach them through the webapp under test: uninstall "
            "it there (or make the App private to the test org)"
        )
    count = _int_or_none(info.get("installations_count"))
    if count is not None and count > len(installations):
        raise SafetyError(
            f"GET /app reports {count} installation(s) of the GitHub App {slug!r} but GET /app/installations lists "
            f"{len(installations)}: cannot verify that the App reaches test organizations only"
        )
    _logger.info("GitHub App %s owned by %s, installed on: %s", slug, owner_login, ", ".join(accounts) or "nothing")
    return AppIsolation(slug=slug, owner=owner_login, installations=tuple(accounts))


def _probe_hint(exc: BaseException) -> str:
    """The permissions GitHub asked for (X-Accepted-GitHub-Permissions), if any."""
    headers = {str(key).lower(): value for key, value in (getattr(exc, "headers", None) or {}).items()}
    accepted = headers.get("x-accepted-github-permissions")
    return f"; GitHub accepts: {accepted}" if accepted else ""


def run_probe(http: GitHubHttp, probe: PermissionProbe, org: str) -> tuple[Any, BaseException | None]:
    """GET the probe path: (body, None) on 200, (None, error) otherwise (SafetyErrors of the client propagate)."""
    try:
        return http.get(probe.path.format(org=org)), None
    except SafetyError:
        raise
    except Exception as exc:  # noqa: BLE001 - the caller turns it into a failed proof
        return None, exc


def _refuse_probe(role: str, probe: PermissionProbe, org: str, exc: BaseException, why: str) -> SafetyError:
    """SafetyError of a failed fine-grained proof (with the permission GitHub asks for)."""
    status = getattr(exc, "status", None)
    return SafetyError(
        f"{role}: fine-grained token cannot read GET {probe.path.format(org=org)} ({status or _describe(exc)}"
        f"{_probe_hint(exc)}): {why}. Create the token with resource owner {org!r}, Repository access 'All "
        f"repositories' and {probe.permission} (docs/setup-free-org.md#fine-grained-personal-access-tokens), and have "
        "an org owner approve it if the org requires approval"
    )


def _check_owner_token(http: GitHubHttp, role: str, org: str) -> None:
    """Owner roles: org-owner-only reads of the test org must answer 200 (the token's resource owner is the org)."""
    for probe in FINE_GRAINED_OWNER_PROBES:
        _, error = run_probe(http, probe, org)
        if error is not None:
            raise _refuse_probe(
                role,
                probe,
                org,
                error,
                "only a token whose resource owner is the test org and whose account is an "
                "owner can, so its isolation is not proven",
            ) from error


def _check_member_token(http: GitHubHttp, role: str, org: str, test_org_id: int) -> None:
    """author/approver: the token reads its user's ACTIVE membership of the test org through an org permission."""
    probe = FINE_GRAINED_MEMBER_PROBE
    body, error = run_probe(http, probe, org)
    if error is not None:
        raise _refuse_probe(
            role,
            probe,
            org,
            error,
            "organization permissions only apply to the token's resource owner, so the "
            "token is not proven to target the test org",
        ) from error
    membership = body if isinstance(body, Mapping) else {}
    organization = membership.get("organization")
    org_id = organization.get("id") if isinstance(organization, Mapping) else None
    if org_id != test_org_id or membership.get("state") != "active":
        raise SafetyError(
            f"{role}: GET {probe.path.format(org=org)} answered organization id {org_id!r}, state "
            f"{membership.get('state')!r}: expected an active membership of the test org (id {test_org_id})"
        )


def _check_fine_grained(http: GitHubHttp, role: str, info: TokenInfo, org: str | None, test_org_id: int) -> None:
    """Rules of non-classic tokens: read-only roles accept them, the outsider never, the others need the token proof."""
    if role in READ_ONLY_ROLES:
        return
    if role == OUTSIDER_ROLE:
        raise SafetyError(
            f"{role}: needs a classic PAT: it comments on the test org's public repositories without being a member, "
            "and a fine-grained token can only write to the resources of its resource owner (docs/security.md)"
        )
    if info.kind != FINE_GRAINED:
        raise SafetyError(
            f"{role}: token without X-OAuth-Scopes that is not a fine-grained PAT ({FINE_GRAINED_PREFIX}...): App or "
            "OAuth tokens are only accepted for " + ", ".join(sorted(READ_ONLY_ROLES))
        )
    if role not in FINE_GRAINED_ROLES:
        raise SafetyError(f"{role}: fine-grained tokens are not accepted for this role; use a classic PAT")
    if not org:
        raise SafetyError(f"{role}: the test org login is needed to verify a fine-grained token (fail closed)")
    if role in OWNER_ROLES:
        _check_owner_token(http, role, org)
    else:
        _check_member_token(http, role, org, test_org_id)


def check_identity_isolation(
    http: GitHubHttp,
    *,
    role: str,
    allowed_org_ids: Collection[int],
    test_org_id: int,
    org: str | None = None,
    token_type: str = "auto",  # noqa: S107 - a token kind, not a secret
) -> None:
    """Raise SafetyError unless the token of ``role`` is isolated to test orgs (rules depend on the token kind).

    The declared ``token_type`` (auto, classic, fine-grained) must match the kind GET /rate_limit reveals.
    Classic PAT: its scopes (X-OAuth-Scopes) must be a subset of ALLOWED_SCOPES["admin"] (OWNER_ROLES) or
    ALLOWED_SCOPES["other"], and GET /user/orgs + GET /user/memberships/orgs?state=pending may only list
    allowed_org_ids (role "outsider": test_org_id must not be present).
    Fine-grained PAT (no X-OAuth-Scopes; GitHub lists no orgs for it): owner roles must read FINE_GRAINED_OWNER_PROBES
    of ``org`` (the test org login), author/approver their active membership of it (FINE_GRAINED_MEMBER_PROBE); the
    outsider is refused; config_reader/readonly accept any non-classic token (their membership listings may answer
    403/404, which is tolerated, and visible memberships are still checked).
    """
    info = read_token_info(http, role)
    _check_token_type(role, info, token_type)
    if info.kind == CLASSIC:
        scopes = set(info.scopes or ())
        _check_scopes(role, scopes)
        active = _list_orgs(http, "/user/orgs", None, role, tolerate=False)
        pending = _list_orgs(http, "/user/memberships/orgs", {"state": "pending"}, role, tolerate=False)
        _check_memberships(role, active, pending, {int(oid) for oid in allowed_org_ids}, test_org_id)
        _logger.info(
            "identity %s isolated: classic PAT, scopes %s; %d organization(s), %d pending invitation(s)",
            role,
            ", ".join(sorted(scopes)) or "(none)",
            len(active),
            len(pending),
        )
        return
    _check_fine_grained(http, role, info, org, test_org_id)
    if role in READ_ONLY_ROLES:
        active = _list_orgs(http, "/user/orgs", None, role, tolerate=True)
        pending = _list_orgs(http, "/user/memberships/orgs", {"state": "pending"}, role, tolerate=True)
        _check_memberships(role, active, pending, {int(oid) for oid in allowed_org_ids}, test_org_id)
    _logger.info("identity %s isolated: %s token bound to %s", role, info.kind, org or "its resource owner")
