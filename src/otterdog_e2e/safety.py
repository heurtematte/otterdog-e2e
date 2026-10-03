"""Safety model (SPEC 5): the org pin, the verified-org capability and identity isolation.

A ``VerifiedOrg`` can only be created by ``verify_target`` (its constructor requires a module-private sentinel). Every
component able to mutate GitHub (Mutator, TemplatePublisher, Janitor, OrgLease, WebappStack, live OtterdogCli,
GitHubHttp with write_scope) requires one, so no mutation path can be built without the checks having passed.

verify_target raises SafetyError for every failed check (GitHub errors included, chained as ``__cause__``).
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
FINE_GRAINED_ROLES = frozenset({"config_reader", "readonly"})  # roles allowed to use fine-grained tokens
# roles checked against ALLOWED_SCOPES["admin"]: the oracle falls back to the admin token and, when separate, needs
# owner reads (admin:org, admin:org_hook) for org-level ground truth (GH-10)
OWNER_ROLES = frozenset({"admin", "oracle"})
OUTSIDER_ROLE = "outsider"  # must NOT belong to (or be invited by) the test org

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
            "carry the admin:org scope"
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
    check_identity_isolation(admin_http, role="admin", allowed_org_ids=allowed, test_org_id=test_org_id)
    admin_token = getattr(admin_http, "token", None)
    if admin_token is None and "admin" in identities:
        admin_token = identities["admin"].token  # clients without a token attribute (fakes) stand for the admin
    checked = {(admin_token, _rules("admin"))}
    clients: dict[str | None, GitHubHttp] = {admin_token: admin_http}  # one client per distinct token
    for name, identity in identities.items():
        key = (identity.token, _rules(name))
        if key in checked:
            continue
        checked.add(key)
        if identity.token not in clients:
            clients[identity.token] = identity_http(identity, like=admin_http)
        check_identity_isolation(clients[identity.token], role=name, allowed_org_ids=allowed, test_org_id=test_org_id)


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


def _token_scopes(http: GitHubHttp, role: str) -> set[str] | None:
    """Classic scopes of the client's token (None for fine-grained tokens); SafetyError when unreadable."""
    try:
        scopes = http.oauth_scopes()
    except SafetyError:
        raise
    except Exception as exc:
        raise SafetyError(f"{role}: cannot read the token scopes: {_describe(exc)}") from exc
    return None if scopes is None else {scope.strip() for scope in scopes if scope.strip()}


def _check_scopes(role: str, scopes: set[str] | None) -> None:
    """Classic scopes must be allowed for the role; fine-grained tokens only for FINE_GRAINED_ROLES."""
    allowed, fine_grained_ok, _ = _rules(role)
    if scopes is None:
        if not fine_grained_ok:
            raise SafetyError(
                f"{role}: fine-grained or App tokens are only accepted for {', '.join(sorted(FINE_GRAINED_ROLES))}; "
                "use a classic PAT so its scopes can be verified"
            )
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


def check_identity_isolation(
    http: GitHubHttp, *, role: str, allowed_org_ids: Collection[int], test_org_id: int
) -> None:
    """Raise SafetyError unless the identity only belongs to test orgs and its token scopes are allowed for ``role``.

    Paginates GET /user/orgs and GET /user/memberships/orgs?state=pending; any org id outside allowed_org_ids fails
    (role "outsider": test_org_id must not be present). Classic scopes (X-OAuth-Scopes) must be a subset of
    ALLOWED_SCOPES["admin"] (OWNER_ROLES) or ALLOWED_SCOPES["other"]; fine-grained tokens only for FINE_GRAINED_ROLES
    (their membership listings may answer 403/404, which is tolerated).
    """
    scopes = _token_scopes(http, role)
    _check_scopes(role, scopes)
    fine_grained = scopes is None
    active = _list_orgs(http, "/user/orgs", None, role, tolerate=fine_grained)
    pending = _list_orgs(http, "/user/memberships/orgs", {"state": "pending"}, role, tolerate=fine_grained)
    _check_memberships(role, active, pending, {int(oid) for oid in allowed_org_ids}, test_org_id)
    _logger.info(
        "identity %s isolated: %s; %d organization(s), %d pending invitation(s)",
        role,
        "fine-grained token" if fine_grained else f"scopes {', '.join(sorted(scopes or ())) or '(none)'}",
        len(active),
        len(pending),
    )
