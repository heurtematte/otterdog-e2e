"""Token requirements per role and PREFILLED token creation URLs (docs/setup-free-org.md, "3. Tokens" and
"Permissions per role"; this module is the single source of those tables: a unit test parses the docs against it).

GitHub has no API to create a personal access token: the wizard prints a creation URL that preselects everything URL
parameters can carry, and the operator clicks "Generate token".

* classic: ``https://github.com/settings/tokens/new?scopes=<a,b>&description=<note>``; there is no expiration
  parameter (the operator picks one);
* fine-grained: ``https://github.com/settings/personal-access-tokens/new?name=&description=&target_name=<owner>&
  expires_in=<1..366>&<permission>=<read|write|admin>...`` (GitHub docs, managing-your-personal-access-tokens,
  "Pre-filling fine-grained personal access token details using URL parameters"); ``name`` is at most 40 characters,
  ``description`` at most 1024, ``workflows`` only exists as write; repository access ("All repositories", "Public
  repositories") has NO parameter: the operator selects it.

The outsider has no fine-grained form (a fine-grained token cannot write to an org its account does not belong to),
the config_reader no classic form (the webapp's OTTERDOG_CONFIG_TOKEN must be a fine-grained public read-only token).
"""

from __future__ import annotations

import hashlib
import urllib.parse
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field

from otterdog_e2e.safety import CLASSIC, FINE_GRAINED

CLASSIC_TOKEN_URL = "https://github.com/settings/tokens/new"  # noqa: S105 - a page URL, not a secret
FINE_GRAINED_TOKEN_URL = "https://github.com/settings/personal-access-tokens/new"  # noqa: S105 - a page URL
TOKEN_NAME_MAX_LENGTH = 40
TOKEN_DESCRIPTION_MAX_LENGTH = 1024
DEFAULT_EXPIRES_IN = 90  # days; organizations cap fine-grained tokens at 366 days by default
MIN_EXPIRES_IN, MAX_EXPIRES_IN = 1, 366
TOKEN_KINDS = (CLASSIC, FINE_GRAINED)
ACCESS_LEVELS = ("read", "write", "admin")
# URL parameter names of the fine-grained permissions (organization, then repository permissions)
ORG_PERMISSIONS = (
    "organization_administration",
    "organization_custom_org_roles",
    "organization_custom_properties",
    "members",
    "organization_plan",
    "organization_secrets",
    "organization_actions_variables",
    "organization_hooks",
)
REPO_PERMISSIONS = (
    "actions",
    "administration",
    "statuses",
    "contents",
    "repository_custom_properties",
    "environments",
    "metadata",
    "pages",
    "pull_requests",
    "repository_advisories",
    "secrets",
    "actions_variables",
    "repository_hooks",
    "workflows",
)
WRITE_ONLY_PERMISSIONS = frozenset({"workflows"})  # GitHub offers "Read and write" only
# labels of the permission tables of docs/setup-free-org.md -> URL parameter names
ORG_PERMISSION_LABELS: Mapping[str, str] = {
    "Administration": "organization_administration",
    "Custom organization roles": "organization_custom_org_roles",
    "Custom properties": "organization_custom_properties",
    "Members": "members",
    "Plan": "organization_plan",
    "Secrets": "organization_secrets",
    "Variables": "organization_actions_variables",
    "Webhooks": "organization_hooks",
}
REPO_PERMISSION_LABELS: Mapping[str, str] = {
    "Actions": "actions",
    "Administration": "administration",
    "Commit statuses": "statuses",
    "Contents": "contents",
    "Custom properties": "repository_custom_properties",
    "Environments": "environments",
    "Metadata": "metadata",
    "Pages": "pages",
    "Pull requests": "pull_requests",
    "Repository security advisories": "repository_advisories",
    "Secrets": "secrets",
    "Variables": "actions_variables",
    "Webhooks": "repository_hooks",
    "Workflows": "workflows",
}
ACCESS_LABELS: Mapping[str, str] = {"Read": "read", "Read and write": "write", "Admin": "admin"}
# classic scopes that grant another one (repo covers public_repo, admin:org covers read:org)
IMPLIED_SCOPES: Mapping[str, frozenset[str]] = {
    "public_repo": frozenset({"repo"}),
    "read:org": frozenset({"admin:org", "write:org"}),
}

# --- permission sets (docs/setup-free-org.md "Permissions per role") -----------------------------------------------
ADMIN_PERMISSIONS: Mapping[str, str] = {
    "organization_administration": "write",
    "organization_custom_org_roles": "read",
    "organization_custom_properties": "admin",
    "members": "write",
    "organization_plan": "read",
    "organization_secrets": "write",
    "organization_actions_variables": "write",
    "organization_hooks": "write",
    "actions": "write",
    "administration": "write",
    "statuses": "read",
    "contents": "write",
    "repository_custom_properties": "write",
    "environments": "write",
    "metadata": "read",
    "pages": "read",
    "pull_requests": "write",
    "repository_advisories": "write",
    "secrets": "write",
    "actions_variables": "write",
    "repository_hooks": "write",
    "workflows": "write",
}
# reads GitHub lists under write access: the read-only oracle keeps write there (organization rulesets, the
# organization advisory listing)
ORACLE_WRITE_READS = frozenset({"organization_administration", "repository_advisories"})
ORACLE_PERMISSIONS: Mapping[str, str] = {
    name: "write" if name in ORACLE_WRITE_READS else "read"
    for name in ADMIN_PERMISSIONS
    if name not in WRITE_ONLY_PERMISSIONS
}
MEMBER_PERMISSIONS: Mapping[str, str] = {
    "members": "read",
    "contents": "write",
    "metadata": "read",
    "pull_requests": "write",
}
ALL_REPOSITORIES = "All repositories"
PUBLIC_REPOSITORIES = "Public repositories"


@dataclass(frozen=True)
class RoleTokens:
    """What one role's token must be: env names, classic scopes, fine-grained permissions and repository access.

    ``classic_scopes`` empty: no classic PAT accepted; ``fine_grained`` None: no fine-grained PAT accepted;
    ``own_owner``: the token's resource owner is its own account (config_reader), else the test org.
    """

    role: str
    login_env: str
    token_env: str
    type_env: str
    required: bool
    purpose: str
    classic_scopes: tuple[str, ...] = ()
    fine_grained: Mapping[str, str] | None = field(default=None, repr=False)
    own_owner: bool = False
    repository_access: str = ALL_REPOSITORIES

    @property
    def kinds(self) -> tuple[str, ...]:
        """Token kinds accepted for the role (CLASSIC, FINE_GRAINED)."""
        return tuple(
            kind
            for kind, accepted in ((CLASSIC, bool(self.classic_scopes)), (FINE_GRAINED, self.fine_grained is not None))
            if accepted
        )


def _role(
    role: str,
    prefix: str,
    *,
    required: bool,
    purpose: str,
    classic_scopes: tuple[str, ...] = (),
    fine_grained: Mapping[str, str] | None = None,
    own_owner: bool = False,
    repository_access: str = ALL_REPOSITORIES,
) -> RoleTokens:
    """RoleTokens with the env names E2E_<PREFIX>_LOGIN, E2E_<PREFIX>_TOKEN and E2E_<PREFIX>_TOKEN_TYPE."""
    return RoleTokens(
        role,
        login_env=f"E2E_{prefix}_LOGIN",
        token_env=f"E2E_{prefix}_TOKEN",
        type_env=f"E2E_{prefix}_TOKEN_TYPE",
        required=required,
        purpose=purpose,
        classic_scopes=classic_scopes,
        fine_grained=fine_grained,
        own_owner=own_owner,
        repository_access=repository_access,
    )


# the roles of setup, in prompt order (env names of targets/*.yaml: identities.<role>.login / token_env / token_type)
ROLE_TOKENS: Mapping[str, RoleTokens] = {
    "admin": _role(
        "admin",
        "ADMIN",
        required=True,
        purpose="owner of the test org: runs otterdog, resets the org, creates the App",
        classic_scopes=("repo", "workflow", "admin:org", "admin:org_hook", "delete_repo"),
        fine_grained=ADMIN_PERMISSIONS,
    ),
    "oracle": _role(
        "oracle",
        "ORACLE",
        required=False,
        purpose="separate read-only ground truth, an org owner (skip it: the admin token serves as oracle)",
        classic_scopes=("repo", "admin:org", "admin:org_hook"),
        fine_grained=ORACLE_PERMISSIONS,
    ),
    "author": _role(
        "author",
        "AUTHOR",
        required=False,
        purpose="opens config PRs as a plain member (webapp flows)",
        classic_scopes=("public_repo", "read:org"),
        fine_grained=MEMBER_PERMISSIONS,
    ),
    "approver": _role(
        "approver",
        "APPROVER",
        required=False,
        purpose="approves config PRs (approval and auto-merge flows)",
        classic_scopes=("public_repo", "read:org"),
        fine_grained=MEMBER_PERMISSIONS,
    ),
    "outsider": _role(
        "outsider",
        "OUTSIDER",
        required=False,
        purpose="comments as a NON-member (negative tests); classic PAT only",
        classic_scopes=("public_repo", "read:org"),
    ),
    "config_reader": _role(
        "config_reader",
        "CONFIG_READER",
        required=False,
        purpose="powerless token given to the webapp under test (OTTERDOG_CONFIG_TOKEN), needed for untrusted SUTs",
        fine_grained={},
        own_owner=True,
        repository_access=PUBLIC_REPOSITORIES,
    ),
}
ROLES = tuple(ROLE_TOKENS)


def missing_scopes(role: str, scopes: Collection[str]) -> list[str]:
    """Classic scopes the role needs that ``scopes`` neither has nor implies (IMPLIED_SCOPES)."""
    granted = set(scopes)
    return [
        scope
        for scope in ROLE_TOKENS[role].classic_scopes
        if scope not in granted and not (IMPLIED_SCOPES.get(scope, frozenset()) & granted)
    ]


def token_name(instance: str, role: str) -> str:
    """Name of a fine-grained token, unique per account and instance: ``otterdog-e2e-<instance>-<role>``, or a cut
    prefix plus a hash of both when that exceeds TOKEN_NAME_MAX_LENGTH."""
    name = f"otterdog-e2e-{instance}-{role}"
    if len(name) <= TOKEN_NAME_MAX_LENGTH:
        return name
    digest = hashlib.sha256(f"{instance}\0{role}".encode()).hexdigest()[:8]
    return f"{name[: TOKEN_NAME_MAX_LENGTH - len(digest) - 1].rstrip('-')}-{digest}"


def token_description(instance: str, role: str, org: str) -> str:
    """Description (classic: the note) of a token: role, test org and instance."""
    text = f"otterdog-e2e {role} of the test organization {org} (instance {instance}): {ROLE_TOKENS[role].purpose}"
    return text[:TOKEN_DESCRIPTION_MAX_LENGTH]


def _query(params: Mapping[str, str]) -> str:
    """URL query string (commas and colons of scope lists kept readable)."""
    return urllib.parse.urlencode(params, quote_via=urllib.parse.quote, safe=",:")


def classic_token_url(role: str, *, description: str) -> str:
    """Prefilled creation URL of a classic PAT with the role's scopes (no expiration parameter exists)."""
    spec = ROLE_TOKENS[role]
    if not spec.classic_scopes:
        raise ValueError(f"{role}: no classic PAT is accepted for this role")
    return f"{CLASSIC_TOKEN_URL}?{_query({'scopes': ','.join(spec.classic_scopes), 'description': description})}"


def fine_grained_token_url(
    role: str, *, name: str, description: str, target_name: str | None, expires_in: int = DEFAULT_EXPIRES_IN
) -> str:
    """Prefilled creation URL of a fine-grained PAT with the role's permissions (ValueError for invalid parameters);
    ``target_name`` None leaves the resource owner at GitHub's default, the signed-in account."""
    spec = ROLE_TOKENS[role]
    if spec.fine_grained is None:
        raise ValueError(f"{role}: no fine-grained PAT is accepted for this role")
    if not name or len(name) > TOKEN_NAME_MAX_LENGTH:
        raise ValueError(f"fine-grained token names have 1 to {TOKEN_NAME_MAX_LENGTH} characters, got {len(name)}")
    if len(description) > TOKEN_DESCRIPTION_MAX_LENGTH:
        raise ValueError(f"fine-grained token descriptions have at most {TOKEN_DESCRIPTION_MAX_LENGTH} characters")
    if isinstance(expires_in, bool) or not MIN_EXPIRES_IN <= expires_in <= MAX_EXPIRES_IN:
        raise ValueError(f"expires_in must be {MIN_EXPIRES_IN}..{MAX_EXPIRES_IN} days, got {expires_in!r}")
    params = {"name": name, "description": description}
    if target_name:
        params["target_name"] = target_name
    params["expires_in"] = str(expires_in)
    for permission, access in spec.fine_grained.items():
        if permission not in ORG_PERMISSIONS and permission not in REPO_PERMISSIONS:
            raise ValueError(f"{role}: unknown fine-grained permission {permission!r}")
        if access not in ACCESS_LEVELS or (permission in WRITE_ONLY_PERMISSIONS and access != "write"):
            raise ValueError(f"{role}: invalid access {access!r} for {permission}")
        params[permission] = access
    return f"{FINE_GRAINED_TOKEN_URL}?{_query(params)}"


def token_url(
    role: str, kind: str, *, instance: str, org: str, login: str | None = None, expires_in: int = DEFAULT_EXPIRES_IN
) -> str:
    """Prefilled creation URL of the role's token of ``kind`` (the config_reader's resource owner is its own account:
    ``login`` when known)."""
    description = token_description(instance, role, org)
    if kind == CLASSIC:
        return classic_token_url(role, description=description)
    if kind != FINE_GRAINED:
        raise ValueError(f"unknown token kind {kind!r}, expected one of {', '.join(TOKEN_KINDS)}")
    owner = login if ROLE_TOKENS[role].own_owner else org
    return fine_grained_token_url(
        role,
        name=token_name(instance, role),
        description=description,
        target_name=owner,
        expires_in=expires_in,
    )


def token_steps(role: str, kind: str, org: str) -> list[str]:
    """What the operator still selects by hand on the creation page (URL parameters cannot carry it)."""
    spec = ROLE_TOKENS[role]
    if kind == CLASSIC:
        return [
            f"scopes preselected: {', '.join(spec.classic_scopes)} (select nothing else)",
            "Expiration: choose one (no URL parameter), e.g. 90 days, and plan the rotation",
        ]
    owner = "the account itself (signed in as the config_reader)" if spec.own_owner else f"{org}"
    steps = [
        f"Resource owner: {owner} (preselected)",
        f"Repository access: select '{spec.repository_access}' (no URL parameter)",
        (
            f"Permissions: {len(spec.fine_grained or {})} preselected (add none; Metadata read is always added)"
            if spec.fine_grained
            else "Permissions: none (leave every permission at No access)"
        ),
    ]
    if role in ("author", "approver"):
        steps.append(
            f"the account must already be an active member of {org} (accept the invitation first), and an owner "
            f"may have to approve the request: https://github.com/organizations/{org}/settings/personal-access-token-requests"
        )
    return steps
