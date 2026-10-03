"""Capabilities of a target: what the org's plan, probes and environment allow (SPEC 8).

Plan-derived capabilities come from PLAN_MATRIX; CUSTOM_PROPERTIES and ACTIONS_CACHE_LIMIT come from read-only probes;
GHAS_PRIVATE only from target overrides; APP/DOCKER/IDENTITY_*/SEPARATE_ORACLE from the environment. Target overrides
(``github.capabilities: {add, remove}``) are applied last.

ACTIONS_CACHE_LIMIT means "otterdog can manage the Actions cache limit on this target": it needs the repository
endpoint and the org path otterdog itself calls (``/orgs/{org}/actions/cache/storage-limit``, not in GitHub's REST
description: KB-006) to answer 200, because the renderer only shows ``max_cache_size_gb`` when the capability is
there. The documented ``/organizations/{org}/actions/cache/storage-limit`` is probed too and only recorded
(``probes['org_cache_storage_limit_documented']``): it tells "GitHub offers the limit, otterdog misses it" (KB-006
evidence) from "the plan has no cache limit".

WEB_UI (docs/web-ui-testing.md) is DERIVED by the session (E2EContext.probe): admin web credentials present AND
``--e2e-allow-web-ui`` AND a trusted SUT AND no ``github.saml_sso`` AND web logins not blocked. Target overrides can
remove it but never add it (DERIVED_CAPS).
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import Identity

_logger = logging.getLogger(__name__)


class Cap(StrEnum):
    """A capability a scenario may require (values are lower snake case)."""

    PUBLIC_REPOS = "public_repos"
    PRIVATE_REPO_BRANCH_PROTECTION = "private_repo_branch_protection"
    PRIVATE_REPO_RULESETS = "private_repo_rulesets"
    PRIVATE_REPO_ENVIRONMENTS = "private_repo_environments"
    PRIVATE_REPO_ENV_PROTECTION_RULES = "private_repo_env_protection_rules"
    PRIVATE_PAGES = "private_pages"
    ORG_RULESETS = "org_rulesets"
    OTTERDOG_ORG_RULESETS = "otterdog_org_rulesets"
    PUSH_RULESETS = "push_rulesets"
    RULESET_EVALUATE = "ruleset_evaluate"
    CUSTOM_ORG_ROLES = "custom_org_roles"
    CUSTOM_PROPERTIES = "custom_properties"
    INTERNAL_REPOS = "internal_repos"
    ORG_SECRETS_PRIVATE_REPOS = "org_secrets_private_repos"
    SECRET_SCANNING_PUBLIC = "secret_scanning_public"  # noqa: S105 - a capability name, not a secret
    GHAS_PRIVATE = "ghas_private"
    LARGER_RUNNERS = "larger_runners"
    MERGE_QUEUE_PRIVATE = "merge_queue_private"
    ACTIONS_CACHE_LIMIT = "actions_cache_limit"
    APP = "app"
    DOCKER = "docker"
    IDENTITY_AUTHOR = "identity_author"
    IDENTITY_APPROVER = "identity_approver"
    IDENTITY_OUTSIDER = "identity_outsider"
    IDENTITY_CONFIG_READER = "identity_config_reader"
    SEPARATE_ORACLE = "separate_oracle"
    WEB_UI = "web_ui"


PLANS: tuple[str, ...] = ("free", "team", "enterprise")

_FREE = frozenset({Cap.PUBLIC_REPOS, Cap.SECRET_SCANNING_PUBLIC})
_TEAM = _FREE | {
    Cap.PRIVATE_REPO_BRANCH_PROTECTION,
    Cap.PRIVATE_REPO_RULESETS,
    Cap.PRIVATE_REPO_ENVIRONMENTS,
    Cap.ORG_RULESETS,
    Cap.PUSH_RULESETS,
    Cap.ORG_SECRETS_PRIVATE_REPOS,
    Cap.LARGER_RUNNERS,
}
_ENTERPRISE = _TEAM | {
    Cap.PRIVATE_REPO_ENV_PROTECTION_RULES,
    Cap.PRIVATE_PAGES,
    Cap.RULESET_EVALUATE,
    Cap.CUSTOM_ORG_ROLES,
    Cap.INTERNAL_REPOS,
    Cap.OTTERDOG_ORG_RULESETS,
    Cap.MERGE_QUEUE_PRIVATE,
}
PLAN_MATRIX: Mapping[str, frozenset[Cap]] = {"free": _FREE, "team": _TEAM, "enterprise": _ENTERPRISE}

# capabilities only the session derives (never added through github.capabilities.add)
DERIVED_CAPS: frozenset[Cap] = frozenset({Cap.WEB_UI})

# identity name -> capability granted when that identity is configured
IDENTITY_CAPS: Mapping[str, Cap] = {
    "author": Cap.IDENTITY_AUTHOR,
    "approver": Cap.IDENTITY_APPROVER,
    "outsider": Cap.IDENTITY_OUTSIDER,
    "config_reader": Cap.IDENTITY_CONFIG_READER,
}


def plans_at_least(min_plan: str) -> tuple[str, ...]:
    """Plans that include ``min_plan`` (e.g. "team" -> ("team", "enterprise"))."""
    if min_plan not in PLANS:
        raise ValueError(f"unknown plan {min_plan!r}, expected one of {PLANS}")
    return PLANS[PLANS.index(min_plan) :]


@dataclass
class Capabilities:
    """The capabilities of one target for this session, with the raw probe results."""

    plan: str
    caps: frozenset[Cap]
    probes: dict[str, Any] = field(default_factory=dict)

    def has(self, cap: Cap | str) -> bool:
        """True when the capability is present (ValueError for unknown names)."""
        return Cap(cap) in self.caps

    def missing(self, caps: Iterable[Cap | str]) -> list[str]:
        """Names of the given capabilities that are not present, in order (ValueError for unknown names)."""
        return [Cap(cap).value for cap in caps if not self.has(cap)]

    def to_json(self) -> dict[str, Any]:
        """JSON-serializable form (run.json)."""
        return {"plan": self.plan, "caps": sorted(cap.value for cap in self.caps), "probes": dict(self.probes)}


def from_plan(plan: str, extra: Iterable[Cap | str] = (), remove: Iterable[Cap | str] = ()) -> Capabilities:
    """Capabilities of ``plan`` per PLAN_MATRIX, plus ``extra``, minus ``remove`` (ValueError for unknown plan/names)."""
    if plan not in PLAN_MATRIX:
        raise ValueError(f"unknown plan {plan!r}, expected one of {PLANS}")
    caps = (PLAN_MATRIX[plan] | {Cap(c) for c in extra}) - {Cap(c) for c in remove}
    return Capabilities(plan=plan, caps=frozenset(caps), probes={})


# non-2xx answers a probe records instead of failing (anything else, 5xx after retries included, becomes "error: ...")
PROBE_RECORDED_STATUSES: tuple[int, ...] = (400, 401, 402, 403, 404, 405, 409, 410, 422, 451)


def probe_status(http: GitHubHttp, path: str) -> int | str:
    """HTTP status of a read-only GET probe (304 counts as 200); never raises: errors become ``"error: <reason>"``."""
    try:
        response = http.request("GET", path, expected=(200, 304), allow=PROBE_RECORDED_STATUSES)
    except Exception as exc:  # noqa: BLE001 - probes never raise (SPEC 8): the failure is recorded instead
        status = getattr(exc, "status", None)
        if isinstance(status, int) and not isinstance(status, bool):
            return status
        return "error: " + REDACTOR(f"{type(exc).__name__}: {exc}")[:200]
    return 200 if response.status_code == 304 else response.status_code


def environment_caps(identities: Mapping[str, Identity], *, app_ok: bool, docker_ok: bool) -> set[Cap]:
    """APP, DOCKER, IDENTITY_* for configured identities and SEPARATE_ORACLE when the oracle token is not the admin's."""
    caps = {cap for name, cap in IDENTITY_CAPS.items() if name in identities}
    if app_ok:
        caps.add(Cap.APP)
    if docker_ok:
        caps.add(Cap.DOCKER)
    oracle, admin = identities.get("oracle"), identities.get("admin")
    if oracle is not None and admin is not None and oracle.token != admin.token:
        caps.add(Cap.SEPARATE_ORACLE)
    return caps


def _known_caps(names: Iterable[str], what: str) -> set[Cap]:
    """Capabilities named in an override list; unknown names are logged and ignored."""
    caps = set()
    for name in names:
        try:
            caps.add(Cap(str(name).lower()))
        except ValueError:
            _logger.warning("ignoring unknown capability %r in the target capability overrides (%s)", name, what)
    return caps


def apply_overrides(caps: Iterable[Cap], overrides: Mapping[str, Sequence[str]]) -> set[Cap]:
    """``caps`` plus overrides["add"] minus overrides["remove"] (remove wins; DERIVED_CAPS are never added)."""
    added = _known_caps(overrides.get("add", ()), "add")
    for cap in sorted(added & DERIVED_CAPS):
        _logger.warning("ignoring capability %r in the target overrides (add): the session derives it", cap.value)
    removed = _known_caps(overrides.get("remove", ()), "remove")
    return (set(caps) | (added - DERIVED_CAPS)) - removed


def with_capabilities(
    capabilities: Capabilities, *caps: Cap, overrides: Mapping[str, Sequence[str]] | None = None
) -> Capabilities:
    """A copy of ``capabilities`` with ``caps`` added, unless the target overrides remove them."""
    removed = _known_caps((overrides or {}).get("remove", ()), "remove")
    added = {Cap(cap) for cap in caps} - removed
    return Capabilities(
        plan=capabilities.plan, caps=frozenset(capabilities.caps | added), probes=dict(capabilities.probes)
    )


def _org_probes(http: GitHubHttp, org: str, fixture_repo: str | None) -> dict[str, Any]:
    """Statuses of the read-only org/repo probes of SPEC 8."""
    repo_limit = f"/repos/{org}/{fixture_repo}/actions/cache/storage-limit"
    return {
        "properties_schema": probe_status(http, f"/orgs/{org}/properties/schema"),
        "repo_cache_storage_limit": probe_status(http, repo_limit) if fixture_repo else None,
        "org_cache_storage_limit": probe_status(http, f"/orgs/{org}/actions/cache/storage-limit"),
        "org_cache_storage_limit_documented": probe_status(http, f"/organizations/{org}/actions/cache/storage-limit"),
        "custom_repository_roles": probe_status(http, f"/orgs/{org}/custom-repository-roles"),
    }


def _probed_caps(probes: Mapping[str, Any]) -> set[Cap]:
    """CUSTOM_PROPERTIES and ACTIONS_CACHE_LIMIT from the probe statuses."""
    caps = set()
    if probes["properties_schema"] == 200:
        caps.add(Cap.CUSTOM_PROPERTIES)
    if probes["repo_cache_storage_limit"] == 200 and probes["org_cache_storage_limit"] == 200:
        caps.add(Cap.ACTIONS_CACHE_LIMIT)
    return caps


def probe_capabilities(
    admin_http: GitHubHttp,
    verified: VerifiedOrg,
    *,
    identities: Mapping[str, Identity],
    app_ok: bool,
    docker_ok: bool,
    overrides: Mapping[str, Sequence[str]],
    fixture_repo: str | None,
) -> Capabilities:
    """from_plan(verified.plan) + read-only probes (never raise) + environment caps, then overrides {add, remove}.

    GET /orgs/{org}/properties/schema (200 -> CUSTOM_PROPERTIES); GET /repos/{org}/{fixture}/actions/cache/storage-limit
    and GET /orgs/{org}/actions/cache/storage-limit (both 200 -> ACTIONS_CACHE_LIMIT, otterdog's own paths); GET
    /organizations/{org}/actions/cache/storage-limit (the documented path, recorded) and GET /orgs/{org}/custom-
    repository-roles (recorded); APP/DOCKER from app_ok/docker_ok; IDENTITY_* from identities; SEPARATE_ORACLE when the
    oracle identity differs from admin. Statuses are recorded in Capabilities.probes.
    """
    plan_caps = PLAN_MATRIX.get(verified.plan)
    if plan_caps is None:
        _logger.warning("unknown plan %r of %s: no plan capabilities", verified.plan, verified.login)
    probes = _org_probes(admin_http, verified.login, fixture_repo)
    if verified.plan == "enterprise" and probes["custom_repository_roles"] != 200:
        _logger.warning(
            "enterprise sanity: GET /orgs/%s/custom-repository-roles answered %s (expected 200 on Enterprise Cloud)",
            verified.login,
            probes["custom_repository_roles"],
        )
    caps = set(plan_caps or ()) | _probed_caps(probes)
    caps |= environment_caps(identities, app_ok=app_ok, docker_ok=docker_ok)
    caps = apply_overrides(caps, overrides)
    probes["overrides"] = {key: sorted(str(name) for name in overrides.get(key, ())) for key in ("add", "remove")}
    _logger.info("capabilities of %s (%s): %s", verified.login, verified.plan, ", ".join(sorted(caps)))
    return Capabilities(plan=verified.plan, caps=frozenset(caps), probes=probes)
