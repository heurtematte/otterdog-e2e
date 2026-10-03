"""Independent, read-only ground truth about the test org (SPEC 9.3).

The Oracle uses its own ``GitHubHttp(read_only=True)`` (an owner token for org-level reads) and never otterdog code.
Error semantics: single-object lookups return None on 404; list lookups return [] on 403/404 and record
``unavailable[(kind, scope)] = status`` (kind = the listing method, scope = ``"/".join(args)`` or the org login, e.g.
("org_rulesets", "<org>"), ("repo_rulesets", "<repo>"), ("environment_branch_policies", "<repo>/<env>")); a later
successful listing clears its entry; other errors raise GitHubError. Logins are returned without the ``[bot]`` suffix
where noted. Besides the SPEC lookups, ``matching_refs`` and ``git_commit`` serve the org lease and the janitor.

Feature lookups (settings that depend on the plan, an add-on or another setting: cache storage limits, fork PR
approval, selected actions, code scanning default setup, private vulnerability reporting, ...) answer None and record
``unavailable[(method, scope)]`` when GitHub reports the feature unavailable (403/404 by default, see each method),
answer None without a record when the setting does not apply (409, e.g. selected actions while ``allowed_actions`` is
not ``selected``) and raise GitHubError otherwise. Boolean endpoints answering 204/404 (vulnerability alerts, Dependabot
security updates) answer ``{"enabled": bool}`` and None only when the repository itself does not exist.
"""

from __future__ import annotations

import base64
import json
import logging
import urllib.parse
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from otterdog_e2e.github.http import GitHubError

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp

logger = logging.getLogger(__name__)

VOLATILE_KEYS = frozenset({"node_id", "url", "html_url", "created_at", "updated_at", "pushed_at", "etag", "_links"})
BPR_FIELDS = (
    "pattern",
    "requiresApprovingReviews",
    "requiredApprovingReviewCount",
    "requiresStatusChecks",
    "requiresStrictStatusChecks",
    "requiredStatusCheckContexts",
    "isAdminEnforced",
    "allowsForcePushes",
    "allowsDeletions",
    "requiresLinearHistory",
    "requiresConversationResolution",
    "requiresCommitSignatures",
    "dismissesStaleReviews",
    "requiresCodeOwnerReviews",
    "lockBranch",
    "restrictsPushes",
    "blocksCreations",
    "lockAllowsFetchAndMerge",
    "requireLastPushApproval",
    "restrictsReviewDismissals",
    "requiresDeployments",
    "requiredDeploymentEnvironments",
)
# list of {context, app: {slug} | null} (app null: any source; github-actions: a plain context in otterdog)
BPR_STATUS_CHECKS = "requiredStatusChecks { context app { slug } }"
# actor connections of a rule; branch_protection_rule() flattens them to otterdog's notation ("@login", "@org/team",
# "<app slug>"), the summary listing branch_protection_rules() leaves them out (4 nested connections per rule)
BPR_ALLOWANCES = (
    "bypassForcePushAllowances",
    "bypassPullRequestAllowances",
    "pushAllowances",
    "reviewDismissalAllowances",
)
BPR_ACTOR = "actor { __typename ... on App { slug } ... on Team { combinedSlug } ... on User { login } }"
BPR_ALLOWANCE_PAGE = 100  # actors per allowance list (not paginated further: a warning is logged when there are more)
BPR_DETAIL_PAGE = 25  # rules per page of the detailed query (GraphQL cost: 1 + 4 x 25 nested connections ~ 1 point)
VARIABLES_PER_PAGE = 30  # GitHub caps per_page at 30 for every variables listing
DELIVERY_PAGES = 5  # hook delivery logs are read newest first, at most 5 pages of 100
WORKFLOW_RUN_PAGES = 2  # workflow runs are read newest first, at most 2 pages of 100
GRAPHQL_PAGES = 20
TEAM_REPO_MEDIA_TYPE = "application/vnd.github.v3.repository+json"
RAW_MEDIA_TYPE = "application/vnd.github.raw+json"
# role_name of GET /orgs/{org}/teams/{team}/repos/{owner}/{repo} -> otterdog's team_permissions vocabulary
ROLE_TO_PERMISSION = {"read": "pull", "triage": "triage", "write": "push", "maintain": "maintain", "admin": "admin"}
_PERMISSION_ORDER = ("admin", "maintain", "push", "triage", "pull")
_GRAPHQL_STATUS = {"NOT_FOUND": 404, "FORBIDDEN": 403}
# statuses meaning "feature not available" for feature lookups (the documented 403/404; for the cache storage limits
# also 402, like otterdog's _get_optional_json in otterdog/providers/github/rest/__init__.py)
FEATURE_UNAVAILABLE = (403, 404)
CACHE_LIMIT_UNAVAILABLE = (402, 403, 404)
# the predefined organization role holding the security managers (the legacy GET /orgs/{org}/security-managers is
# closing down since 2026-01-01; otterdog itself reads GET /orgs/{org}/organization-roles/{id}/teams)
SECURITY_MANAGER_ROLE = "security_manager"
MEMBER_ROLES = ("admin", "member")  # role filter of GET /orgs/{org}/members

_BPR_SELECTION = f"id {' '.join(BPR_FIELDS)} {BPR_STATUS_CHECKS}"
_BPR_ALLOWANCE_SELECTION = " ".join(
    f"{name}(first: {BPR_ALLOWANCE_PAGE}) {{ totalCount nodes {{ {BPR_ACTOR} }} }}" for name in BPR_ALLOWANCES
)
BPR_QUERY = (
    "query($owner: String!, $name: String!, $after: String) { repository(owner: $owner, name: $name) {"
    " branchProtectionRules(first: 100, after: $after) { pageInfo { hasNextPage endCursor }"
    f" nodes {{ {_BPR_SELECTION} }} }} }} }}"
)
BPR_DETAIL_QUERY = (
    "query($owner: String!, $name: String!, $after: String) { repository(owner: $owner, name: $name) {"
    f" branchProtectionRules(first: {BPR_DETAIL_PAGE}, after: $after) {{ pageInfo {{ hasNextPage endCursor }}"
    f" nodes {{ {_BPR_SELECTION} {_BPR_ALLOWANCE_SELECTION} }} }} }} }}"
)
PR_COMMENTS_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!, $after: String) { repository(owner: $owner, name: $name) {"
    " pullRequest(number: $number) { comments(first: 100, after: $after) { pageInfo { hasNextPage endCursor }"
    " nodes { id databaseId author { login } body isMinimized minimizedReason createdAt } } } } }"
)


def is_volatile(key: str) -> bool:
    """True for keys that change without a configuration change (VOLATILE_KEYS and any ``*_url``)."""
    return key in VOLATILE_KEYS or key.endswith("_url")


def normalize(obj: Any) -> Any:
    """Recursively drop volatile keys from mappings (lists keep their order; other values are returned as is)."""
    if isinstance(obj, dict):
        return {key: normalize(value) for key, value in obj.items() if not is_volatile(key)}
    if isinstance(obj, list | tuple):
        return [normalize(item) for item in obj]
    return obj


def _q(value: str) -> str:
    """URL-encode one path segment (slashes included, as GitHub requires for environment names)."""
    return urllib.parse.quote(str(value), safe="")


def _graphql_error_status(error: GitHubError) -> int | None:
    """403/404 when a GraphQL error list only reports FORBIDDEN/NOT_FOUND, else None."""
    try:
        errors = json.loads(error.body)
    except ValueError:
        return None
    if not isinstance(errors, list) or not errors:
        return None
    statuses = {_GRAPHQL_STATUS.get(str(item.get("type"))) for item in errors if isinstance(item, dict)}
    if len(statuses) == 1 and None not in statuses:
        return statuses.pop()
    return None


def _team_permission(repository: dict[str, Any]) -> str | None:
    """otterdog permission name of a team-repository answer (role_name, else the highest permissions flag)."""
    role = repository.get("role_name")
    if isinstance(role, str) and role:
        return ROLE_TO_PERMISSION.get(role, role)
    permissions = repository.get("permissions") or {}
    return next((name for name in _PERMISSION_ORDER if permissions.get(name)), None)


def _actor_name(actor: Any) -> str | None:
    """otterdog's notation of a BranchActorAllowanceActor: ``@login`` (User), ``@org/team`` (Team), ``slug`` (App)."""
    if not isinstance(actor, dict):
        return None
    typename = actor.get("__typename")
    if typename == "User" and actor.get("login"):
        return f"@{actor['login']}"
    if typename == "Team" and actor.get("combinedSlug"):
        return f"@{actor['combinedSlug']}"
    if typename == "App" and actor.get("slug"):
        return str(actor["slug"])
    return None


def _actors(name: str, connection: Any) -> list[str]:
    """Actors of an allowance connection in otterdog's notation (hidden actors, e.g. deleted users, are skipped)."""
    if not isinstance(connection, dict):
        return []
    nodes = [node for node in connection.get("nodes") or [] if isinstance(node, dict)]
    actors = [actor for actor in (_actor_name(node.get("actor")) for node in nodes) if actor is not None]
    total = connection.get("totalCount")
    if isinstance(total, int) and total > len(nodes):
        logger.warning("%s: %d actors, only the first %d are read", name, total, len(nodes))
    return actors


def _flatten_allowances(rule: dict[str, Any]) -> dict[str, Any]:
    """A detailed rule with each BPR_ALLOWANCES connection replaced by its list of actor names."""
    flat = dict(rule)
    for name in BPR_ALLOWANCES:
        if name in flat:
            flat[name] = _actors(name, flat[name])
    return flat


DELIVERY_SKEW = timedelta(seconds=2)  # GitHub's Date header (second resolution) vs. a delivery's delivered_at


def deliveries_since(
    deliveries: Iterable[dict[str, Any]], since: datetime, *, event: str | None = None, skew: timedelta = DELIVERY_SKEW
) -> list[dict[str, Any]]:
    """The deliveries (of ``event``) delivered at or after ``since`` - ``skew``: ``since`` is GitHub's time of the
    request that triggered them (Mutator.ping_* return it), so deliveries logged late but triggered earlier (a hook's
    creation ping, a previous ping) never count as the new one (BAT-10). Deliveries without delivered_at are left out."""
    found = []
    for delivery in deliveries:
        if event is not None and delivery.get("event") != event:
            continue
        try:
            when = datetime.fromisoformat(str(delivery.get("delivered_at") or ""))
        except ValueError:
            continue
        when = when if when.tzinfo else when.replace(tzinfo=UTC)
        if when >= since - skew:
            found.append(delivery)
    return found


class Oracle:
    """Read-only lookups of org, repo, team, hook, ruleset, environment and PR state."""

    def __init__(self, http: GitHubHttp, org: str) -> None:
        """Bind the read-only client to the org login."""
        self.http = http
        self.org_login = org
        self.unavailable: dict[tuple[str, str], int] = {}

    # --- helpers ------------------------------------------------------------------------------------------------
    @property
    def _org(self) -> str:
        """URL-encoded org login."""
        return _q(self.org_login)

    def _repo(self, repo: str) -> str:
        """``/repos/{org}/{repo}`` path prefix."""
        return f"/repos/{self._org}/{_q(repo)}"

    def _scope(self, args: tuple[Any, ...]) -> str:
        """Scope of an unavailable record: the joined arguments, else the org login."""
        return "/".join(str(arg) for arg in args) or self.org_login

    def _get(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        """Single-object GET (None on 404)."""
        return self.http.get(path, params=params, allow_404=True)

    def _list(
        self,
        kind: str,
        args: tuple[Any, ...],
        path: str,
        *,
        item_key: str | None = None,
        per_page: int = 100,
        params: dict[str, Any] | None = None,
        max_pages: int = 50,
    ) -> list[Any]:
        """List GET with pagination ([] on 403/404, recorded in ``unavailable[(kind, scope)]``)."""
        self.http.unavailable.pop(path, None)
        items = self.http.paginate(
            path, params=params, per_page=per_page, item_key=item_key, max_pages=max_pages, allow_unavailable=True
        )
        return self._settle(kind, args, self.http.unavailable.pop(path, None), items)

    def _list_page(self, kind: str, args: tuple[Any, ...], path: str, *, item_key: str | None = None) -> list[Any]:
        """A listing GitHub answers in one response (no pagination parameters): [] on 403/404, recorded unavailable."""
        response = self.http.request("GET", path, allow=(403, 404))
        if response.status_code in (403, 404):
            return self._settle(kind, args, response.status_code, [])
        body = self._body(response)
        items = body.get(item_key) if item_key and isinstance(body, dict) else body
        return self._settle(kind, args, None, list(items) if isinstance(items, list) else [])

    def _settle(self, kind: str, args: tuple[Any, ...], status: int | None, items: list[Any]) -> list[Any]:
        """Record (or clear) the availability of a listing and return its items."""
        key = (kind, self._scope(args))
        if status is not None:
            logger.debug("%s(%s) unavailable: HTTP %s", kind, key[1], status)
            self.unavailable[key] = status
            return []
        self.unavailable.pop(key, None)
        return items

    def _graphql_pages(
        self, kind: str, args: tuple[Any, ...], query: str, variables: dict[str, Any], path: list[str]
    ) -> list[Any]:
        """Nodes of a paginated GraphQL connection at ``path``; NOT_FOUND/FORBIDDEN -> [] recorded unavailable."""
        nodes: list[dict[str, Any]] = []
        after: str | None = None
        for _ in range(GRAPHQL_PAGES):
            try:
                data = self.http.graphql(query, {**variables, "after": after})
            except GitHubError as exc:
                status = _graphql_error_status(exc)
                if status is None:
                    raise
                return self._settle(kind, args, status, [])
            connection: Any = data
            for key in path:
                connection = connection.get(key) if isinstance(connection, dict) else None
            if not isinstance(connection, dict):
                return self._settle(kind, args, 404, [])
            nodes.extend(node for node in connection.get("nodes") or [] if isinstance(node, dict))
            page = connection.get("pageInfo") or {}
            if not page.get("hasNextPage"):
                break
            after = page.get("endCursor")
        return self._settle(kind, args, None, nodes)

    @staticmethod
    def _find(items: list[dict[str, Any]], key: str, value: Any) -> dict[str, Any] | None:
        """First item whose ``key`` equals ``value``."""
        return next((item for item in items if item.get(key) == value), None)

    @staticmethod
    def _body(response: Any) -> Any:
        """Decoded JSON body of a response (None for empty bodies)."""
        return response.json() if response.content else None

    def _feature(
        self,
        kind: str,
        args: tuple[Any, ...],
        path: str,
        *,
        unavailable: tuple[int, ...] = FEATURE_UNAVAILABLE,
        absent: tuple[int, ...] = (),
    ) -> dict[str, Any] | None:
        """GET of a feature setting: the object; None recorded unavailable on ``unavailable`` statuses; None without
        a record on ``absent`` statuses (the setting does not apply); other errors raise GitHubError."""
        response = self.http.request("GET", path, allow=(*unavailable, *absent))
        status = response.status_code
        if status in unavailable:
            self._settle(kind, args, status, [])
            return None
        self._settle(kind, args, None, [])
        body = None if status in absent else self._body(response)
        return body if isinstance(body, dict) else None

    def _enabled_flag(self, repo: str, path: str) -> dict[str, Any] | None:
        """204/200 -> enabled, 404 -> disabled (``{"enabled": False}``) unless the repository itself is missing."""
        response = self.http.request("GET", path, allow=(404,))
        if response.status_code == 404:
            return None if self.repo(repo) is None else {"enabled": False}
        body = self._body(response)
        return dict(body) if isinstance(body, dict) else {"enabled": True}

    def _names(self, items: list[Any], key: str = "name") -> list[str]:
        """``key`` values of the mapping items of a listing."""
        return [str(item[key]) for item in items if isinstance(item, dict) and item.get(key) is not None]

    # --- organization -------------------------------------------------------------------------------------------
    def org(self) -> dict[str, Any] | None:
        """GET /orgs/{org}."""
        return self._get(f"/orgs/{self._org}")

    def plan_name(self) -> str | None:
        """plan.name of the org (owners only)."""
        plan = (self.org() or {}).get("plan") or {}
        name = plan.get("name") if isinstance(plan, dict) else None
        return str(name) if name else None

    def org_actions_permissions(self) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/permissions."""
        return self._get(f"/orgs/{self._org}/actions/permissions")

    def org_workflow_permissions(self) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/permissions/workflow."""
        return self._get(f"/orgs/{self._org}/actions/permissions/workflow")

    def org_selected_actions(self) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/permissions/selected-actions: github_owned_allowed, verified_allowed,
        patterns_allowed (feature lookup; None without a record on 409, i.e. allowed_actions is not 'selected')."""
        path = f"/orgs/{self._org}/actions/permissions/selected-actions"
        return self._feature("org_selected_actions", (), path, absent=(409,))

    def org_actions_selected_repositories(self) -> list[str]:
        """Names of GET /orgs/{org}/actions/permissions/repositories (``repositories``; [] on 409, i.e.
        enabled_repositories is not 'selected'; 403/404 recorded unavailable)."""
        path = f"/orgs/{self._org}/actions/permissions/repositories"
        return self._selected_repositories("org_actions_selected_repositories", (), path)

    def org_fork_pr_approval(self) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/permissions/fork-pr-contributor-approval: approval_policy (feature lookup)."""
        path = f"/orgs/{self._org}/actions/permissions/fork-pr-contributor-approval"
        return self._feature("org_fork_pr_approval", (), path)

    def org_fork_pr_workflows_private_repos(self) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/permissions/fork-pr-workflows-private-repos (feature lookup; otterdog does not
        manage these settings: use it to check that they stay unchanged)."""
        path = f"/orgs/{self._org}/actions/permissions/fork-pr-workflows-private-repos"
        return self._feature("org_fork_pr_workflows_private_repos", (), path)

    def org_cache_storage_limit(self) -> dict[str, Any] | None:
        """GET /organizations/{org}/actions/cache/storage-limit (the documented path): max_cache_size_gb (feature
        lookup, 402/403/404 unavailable)."""
        path = f"/organizations/{self._org}/actions/cache/storage-limit"
        return self._feature("org_cache_storage_limit", (), path, unavailable=CACHE_LIMIT_UNAVAILABLE)

    def org_cache_storage_limit_orgs_path(self) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/cache/storage-limit, the undocumented path otterdog calls (KB-006 evidence): the
        same answer as org_cache_storage_limit() means the path works, unavailable means it does not."""
        path = f"/orgs/{self._org}/actions/cache/storage-limit"
        return self._feature("org_cache_storage_limit_orgs_path", (), path, unavailable=CACHE_LIMIT_UNAVAILABLE)

    def org_secrets(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/actions/secrets (item_key secrets)."""
        return self._list("org_secrets", (), f"/orgs/{self._org}/actions/secrets", item_key="secrets")

    def org_secret(self, name: str) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/secrets/{name}."""
        return self._get(f"/orgs/{self._org}/actions/secrets/{_q(name)}")

    def org_secret_repositories(self, name: str) -> list[str]:
        """Names of the selected repositories of an org secret."""
        path = f"/orgs/{self._org}/actions/secrets/{_q(name)}/repositories"
        return self._selected_repositories("org_secret_repositories", (name,), path)

    def org_variables(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/actions/variables (per_page 30)."""
        path = f"/orgs/{self._org}/actions/variables"
        return self._list("org_variables", (), path, item_key="variables", per_page=VARIABLES_PER_PAGE)

    def org_variable(self, name: str) -> dict[str, Any] | None:
        """GET /orgs/{org}/actions/variables/{name}."""
        return self._get(f"/orgs/{self._org}/actions/variables/{_q(name)}")

    def org_variable_repositories(self, name: str) -> list[str]:
        """Names of the selected repositories of an org variable."""
        path = f"/orgs/{self._org}/actions/variables/{_q(name)}/repositories"
        return self._selected_repositories("org_variable_repositories", (name,), path)

    def _selected_repositories(self, kind: str, args: tuple[Any, ...], path: str) -> list[str]:
        """Repository names of a ``{total_count, repositories}`` listing; 409 (not a 'selected' policy) -> []."""
        try:
            repos = self._list(kind, args, path, item_key="repositories")
        except GitHubError as exc:
            if exc.status != 409:
                raise
            return []
        return self._names(repos)

    def org_hooks(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/hooks."""
        return self._list("org_hooks", (), f"/orgs/{self._org}/hooks")

    def org_hook_by_url(self, url: str) -> dict[str, Any] | None:
        """The org hook whose config.url equals ``url``."""
        return next((hook for hook in self.org_hooks() if (hook.get("config") or {}).get("url") == url), None)

    def org_hook_deliveries(self, hook_id: int) -> list[dict[str, Any]]:
        """GET /orgs/{org}/hooks/{id}/deliveries."""
        path = f"/orgs/{self._org}/hooks/{int(hook_id)}/deliveries"
        return self._list("org_hook_deliveries", (hook_id,), path, max_pages=DELIVERY_PAGES)

    def org_hook_deliveries_by_url(self, url: str) -> list[dict[str, Any]]:
        """Deliveries of the org hook whose config.url equals ``url`` ([] while no such hook exists)."""
        hook = self.org_hook_by_url(url)
        return [] if hook is None else self.org_hook_deliveries(int(hook["id"]))

    def org_hook_delivery(self, hook_id: int, delivery_id: int) -> dict[str, Any] | None:
        """GET /orgs/{org}/hooks/{id}/deliveries/{delivery_id}: one delivery with its request (headers, payload) and
        response."""
        return self._get(f"/orgs/{self._org}/hooks/{int(hook_id)}/deliveries/{int(delivery_id)}")

    def org_hook_latest_delivery_by_url(self, url: str, event: str) -> dict[str, Any] | None:
        """The newest delivery of ``event`` of the org hook with this URL, in full (request headers, e.g.
        X-Hub-Signature-256); None while there is no such hook or delivery."""
        hook = self.org_hook_by_url(url)
        if hook is None:
            return None
        hook_id = int(hook["id"])
        delivery = self._find(self.org_hook_deliveries(hook_id), "event", event)
        return None if delivery is None else self.org_hook_delivery(hook_id, int(delivery["id"]))

    def org_rulesets(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/rulesets ([] on 403/404, recorded unavailable)."""
        return self._list("org_rulesets", (), f"/orgs/{self._org}/rulesets")

    def org_ruleset(self, name: str) -> dict[str, Any] | None:
        """Full org ruleset by name."""
        summary = self._find(self.org_rulesets(), "name", name)
        if summary is None:
            return None
        return self._get(f"/orgs/{self._org}/rulesets/{int(summary['id'])}")

    def custom_properties(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/properties/schema ([] on 403/404, recorded unavailable)."""
        return self._list("custom_properties", (), f"/orgs/{self._org}/properties/schema")

    def custom_property(self, name: str) -> dict[str, Any] | None:
        """Custom property definition by property_name."""
        return self._find(self.custom_properties(), "property_name", name)

    def org_roles(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/organization-roles (one response, ``roles``; [] on 403/404, recorded unavailable)."""
        return self._list_page("org_roles", (), f"/orgs/{self._org}/organization-roles", item_key="roles")

    def org_role(self, name: str) -> dict[str, Any] | None:
        """The organization role named ``name`` (custom roles and GitHub's predefined ones)."""
        return self._find(self.org_roles(), "name", name)

    def org_role_teams(self, name: str) -> list[str]:
        """Slugs of the teams holding the organization role ``name`` (GET /orgs/{org}/organization-roles/{id}/teams);
        [] recorded unavailable when the role does not exist (404) or the roles feature is not enabled (422)."""
        role = self.org_role(name)
        if role is None:
            return self._settle("org_role_teams", (name,), 404, [])
        path = f"/orgs/{self._org}/organization-roles/{int(role['id'])}/teams"
        try:
            teams = self._list("org_role_teams", (name,), path)
        except GitHubError as exc:
            if exc.status != 422:
                raise
            teams = self._settle("org_role_teams", (name,), 422, [])
        return self._names(teams, "slug")

    def security_managers(self) -> list[str]:
        """Slugs of the security manager teams (the teams of the predefined ``security_manager`` organization role)."""
        return self.org_role_teams(SECURITY_MANAGER_ROLE)

    def code_security_configurations(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/code-security/configurations (org and global configurations; cursor pagination)."""
        return self._list("code_security_configurations", (), f"/orgs/{self._org}/code-security/configurations")

    def code_security_configuration(self, name: str) -> dict[str, Any] | None:
        """The code security configuration named ``name``."""
        return self._find(self.code_security_configurations(), "name", name)

    def code_security_default_configurations(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/code-security/configurations/defaults: [{default_for_new_repos, configuration}] (otterdog's
        default_code_security_configurations_disabled is true exactly when this list is empty)."""
        path = f"/orgs/{self._org}/code-security/configurations/defaults"
        return self._list_page("code_security_default_configurations", (), path)

    def members(self) -> list[str]:
        """Logins of the org members."""
        members = self._list("members", (), f"/orgs/{self._org}/members")
        return [str(member["login"]) for member in members if isinstance(member, dict) and "login" in member]

    def members_with_role(self) -> list[dict[str, Any]]:
        """[{login, role}] of the org members, role 'admin' (owners) or 'member' (GET /orgs/{org}/members?role=...)."""
        result: list[dict[str, Any]] = []
        for role in MEMBER_ROLES:
            members = self._list("members_with_role", (role,), f"/orgs/{self._org}/members", params={"role": role})
            result += [{"login": login, "role": role} for login in self._names(members, "login")]
        return result

    def members_2fa_disabled(self) -> list[str]:
        """Logins of the members without two-factor authentication (GET /orgs/{org}/members?filter=2fa_disabled)."""
        path = f"/orgs/{self._org}/members"
        return self._names(self._list("members_2fa_disabled", (), path, params={"filter": "2fa_disabled"}), "login")

    def membership(self, login: str) -> dict[str, Any] | None:
        """GET /orgs/{org}/memberships/{login} (state, role)."""
        return self._get(f"/orgs/{self._org}/memberships/{_q(login)}")

    def org_invitations(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/invitations: pending invitations (login, email, role, inviter, failed_at, ...)."""
        return self._list("org_invitations", (), f"/orgs/{self._org}/invitations")

    # --- teams --------------------------------------------------------------------------------------------------
    def teams(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/teams."""
        return self._list("teams", (), f"/orgs/{self._org}/teams")

    def team(self, slug: str) -> dict[str, Any] | None:
        """GET /orgs/{org}/teams/{slug}."""
        return self._get(f"/orgs/{self._org}/teams/{_q(slug)}")

    def team_members(self, slug: str) -> list[str]:
        """Logins of the (active) team members."""
        members = self._list("team_members", (slug,), f"/orgs/{self._org}/teams/{_q(slug)}/members")
        return [str(member["login"]) for member in members if isinstance(member, dict) and "login" in member]

    def team_membership(self, slug: str, login: str) -> dict[str, Any] | None:
        """GET /orgs/{org}/teams/{slug}/memberships/{login}: role (member | maintainer) and state (active | pending);
        None when the user is not a member (404)."""
        return self._get(f"/orgs/{self._org}/teams/{_q(slug)}/memberships/{_q(login)}")

    def team_invitations(self, slug: str) -> list[dict[str, Any]]:
        """GET /orgs/{org}/teams/{slug}/invitations: pending invitations to the team."""
        return self._list("team_invitations", (slug,), f"/orgs/{self._org}/teams/{_q(slug)}/invitations")

    def team_repo_permission(self, slug: str, repo: str) -> str | None:
        """Permission of the team on the repo in otterdog's vocabulary (pull|triage|push|maintain|admin).

        Derived from role_name of GET /orgs/{org}/teams/{slug}/repos/{org}/{repo} with the
        vnd.github.v3.repository+json media type (read -> pull, write -> push; custom roles are returned unchanged);
        None when the team has no access (404).
        """
        path = f"/orgs/{self._org}/teams/{_q(slug)}/repos/{self._org}/{_q(repo)}"
        body = self.http.get(path, headers={"Accept": TEAM_REPO_MEDIA_TYPE}, allow_404=True)
        return _team_permission(body) if isinstance(body, dict) else None

    # --- repositories -------------------------------------------------------------------------------------------
    def repos(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/repos (type all)."""
        return self._list("repos", (), f"/orgs/{self._org}/repos", params={"type": "all"})

    def repo(self, name: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{name}."""
        return self._get(self._repo(name))

    def repo_topics(self, name: str) -> list[str]:
        """GET /repos/{org}/{name}/topics (names)."""
        return [
            str(topic) for topic in self._list("repo_topics", (name,), f"{self._repo(name)}/topics", item_key="names")
        ]

    def repo_actions_permissions(self, name: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{name}/actions/permissions."""
        return self._get(f"{self._repo(name)}/actions/permissions")

    def repo_workflow_permissions(self, name: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{name}/actions/permissions/workflow."""
        return self._get(f"{self._repo(name)}/actions/permissions/workflow")

    def repo_selected_actions(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/permissions/selected-actions: github_owned_allowed, verified_allowed,
        patterns_allowed (feature lookup; None without a record on 409, i.e. allowed_actions is not 'selected')."""
        path = f"{self._repo(repo)}/actions/permissions/selected-actions"
        return self._feature("repo_selected_actions", (repo,), path, absent=(409,))

    def repo_fork_pr_approval(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/permissions/fork-pr-contributor-approval: approval_policy (feature lookup;
        otterdog only manages it on public repositories)."""
        path = f"{self._repo(repo)}/actions/permissions/fork-pr-contributor-approval"
        return self._feature("repo_fork_pr_approval", (repo,), path)

    def repo_fork_pr_workflows_private_repos(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/permissions/fork-pr-workflows-private-repos (feature lookup; not managed by
        otterdog)."""
        path = f"{self._repo(repo)}/actions/permissions/fork-pr-workflows-private-repos"
        return self._feature("repo_fork_pr_workflows_private_repos", (repo,), path)

    def repo_cache_storage_limit(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/cache/storage-limit: max_cache_size_gb (feature lookup, 402/403/404
        unavailable: KB-007 evidence)."""
        path = f"{self._repo(repo)}/actions/cache/storage-limit"
        return self._feature("repo_cache_storage_limit", (repo,), path, unavailable=CACHE_LIMIT_UNAVAILABLE)

    # --- repository security ------------------------------------------------------------------------------------
    def repo_security_and_analysis(self, repo: str) -> dict[str, Any] | None:
        """``security_and_analysis`` of GET /repos/{org}/{repo} (secret_scanning, secret_scanning_push_protection,
        dependabot_security_updates, ... each {status}); None when the repository or the block is missing."""
        block = (self.repo(repo) or {}).get("security_and_analysis")
        return block if isinstance(block, dict) else None

    def repo_vulnerability_alerts(self, repo: str) -> dict[str, Any] | None:
        """{enabled} of GET /repos/{org}/{repo}/vulnerability-alerts (204 enabled, 404 disabled; None: no repo)."""
        return self._enabled_flag(repo, f"{self._repo(repo)}/vulnerability-alerts")

    def repo_automated_security_fixes(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/automated-security-fixes: {enabled, paused}; 404 (not enabled) -> {enabled: False};
        None: no repository."""
        return self._enabled_flag(repo, f"{self._repo(repo)}/automated-security-fixes")

    def repo_private_vulnerability_reporting(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/private-vulnerability-reporting: {enabled} (feature lookup: 403/422 unavailable,
        404 -> None, the repository does not exist)."""
        path = f"{self._repo(repo)}/private-vulnerability-reporting"
        return self._feature(
            "repo_private_vulnerability_reporting", (repo,), path, unavailable=(403, 422), absent=(404,)
        )

    def repo_code_scanning_default_setup(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/code-scanning/default-setup: state (configured | not-configured), languages,
        query_suite, ... (feature lookup: 403, GitHub Advanced Security not enabled, and 404 unavailable)."""
        return self._feature(
            "repo_code_scanning_default_setup", (repo,), f"{self._repo(repo)}/code-scanning/default-setup"
        )

    def repo_security_advisories(self, repo: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/security-advisories (every state the owner token can see, newest first)."""
        return self._list("repo_security_advisories", (repo,), f"{self._repo(repo)}/security-advisories")

    def repo_security_advisory(self, repo: str, ghsa_id: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/security-advisories/{ghsa_id}."""
        return self._get(f"{self._repo(repo)}/security-advisories/{_q(ghsa_id)}")

    def org_security_advisories(self) -> list[dict[str, Any]]:
        """GET /orgs/{org}/security-advisories (the listing behind otterdog's list-advisories; owners only)."""
        return self._list("org_security_advisories", (), f"/orgs/{self._org}/security-advisories")

    # --- repository access, branches and workflows --------------------------------------------------------------
    def repo_languages(self, repo: str) -> dict[str, int] | None:
        """Languages GitHub detected in a repository, bytes per language: GET /repos/{org}/{repo}/languages ({} for an
        empty repository or while the detection has not run; None when the repository is absent)."""
        body = self._get(f"{self._repo(repo)}/languages")
        return {str(name): int(size) for name, size in body.items()} if isinstance(body, dict) else None

    def repo_branches(self, repo: str) -> list[str]:
        """Branch names of GET /repos/{org}/{repo}/branches ([] for an empty repository)."""
        return self._names(self._list("repo_branches", (repo,), f"{self._repo(repo)}/branches"))

    def repo_branch(self, repo: str, branch: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/branches/{branch} (name, commit, protected, protection); None when absent or renamed
        (GitHub redirects a renamed branch to its new name)."""
        body = self._get(f"{self._repo(repo)}/branches/{_q(branch)}")
        return body if isinstance(body, dict) and body.get("name") == branch else None

    def repo_teams(self, repo: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/teams: teams granted access (slug, permission, ...; on a public repository only the
        teams that added it explicitly)."""
        return self._list("repo_teams", (repo,), f"{self._repo(repo)}/teams")

    def repo_collaborators(self, repo: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/collaborators?affiliation=direct: direct collaborators (login, role_name,
        permissions), neither team members nor owners."""
        params = {"affiliation": "direct"}
        return self._list("repo_collaborators", (repo,), f"{self._repo(repo)}/collaborators", params=params)

    def repo_collaborator_permission(self, repo: str, login: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/collaborators/{login}/permission: permission (admin|write|read|none), role_name."""
        return self._get(f"{self._repo(repo)}/collaborators/{_q(login)}/permission")

    def repo_invitations(self, repo: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/invitations: open repository invitations (invitee, permissions, expired)."""
        return self._list("repo_invitations", (repo,), f"{self._repo(repo)}/invitations")

    def workflow(self, repo: str, workflow: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/workflows/{workflow} (id or file name): id, name, path, state."""
        return self._get(f"{self._repo(repo)}/actions/workflows/{_q(workflow)}")

    def workflow_runs(self, repo: str, workflow: str) -> list[dict[str, Any]]:
        """Runs of one workflow (id or file name), newest first, at most WORKFLOW_RUN_PAGES pages of 100."""
        path = f"{self._repo(repo)}/actions/workflows/{_q(workflow)}/runs"
        return self._list(
            "workflow_runs", (repo, workflow), path, item_key="workflow_runs", max_pages=WORKFLOW_RUN_PAGES
        )

    def repo_workflow_runs(self, repo: str) -> list[dict[str, Any]]:
        """Runs of every workflow of the repository, newest first, at most WORKFLOW_RUN_PAGES pages of 100."""
        path = f"{self._repo(repo)}/actions/runs"
        return self._list("repo_workflow_runs", (repo,), path, item_key="workflow_runs", max_pages=WORKFLOW_RUN_PAGES)

    def find_workflow_runs(
        self,
        repo: str,
        *,
        workflow: str | None = None,
        event: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        head_sha: str | None = None,
        created: str | None = None,
    ) -> list[dict[str, Any]]:
        """Workflow runs filtered server side (GET .../actions/[workflows/{workflow}/]runs with event, branch, status
        (a status or a conclusion), head_sha, created (search syntax, e.g. '>=2026-10-03T00:00:00Z'))."""
        filters = {"event": event, "branch": branch, "status": status, "head_sha": head_sha, "created": created}
        params = {key: value for key, value in filters.items() if value is not None}
        base = self._repo(repo)
        path = f"{base}/actions/workflows/{_q(workflow)}/runs" if workflow else f"{base}/actions/runs"
        args = (repo, workflow or "")
        return self._list(
            "find_workflow_runs", args, path, item_key="workflow_runs", params=params, max_pages=WORKFLOW_RUN_PAGES
        )

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/runs/{run_id}: status, conclusion, event, head_branch, ..."""
        return self._get(f"{self._repo(repo)}/actions/runs/{int(run_id)}")

    def workflow_run_jobs(self, repo: str, run_id: int) -> list[dict[str, Any]]:
        """Jobs of the latest attempt of a run (GET .../actions/runs/{run_id}/jobs?filter=latest; item_key jobs)."""
        path = f"{self._repo(repo)}/actions/runs/{int(run_id)}/jobs"
        return self._list("workflow_run_jobs", (repo, run_id), path, item_key="jobs", params={"filter": "latest"})

    # --- repository secrets, variables, hooks, protection, environments -----------------------------------------
    def repo_secrets(self, name: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{name}/actions/secrets."""
        return self._list("repo_secrets", (name,), f"{self._repo(name)}/actions/secrets", item_key="secrets")

    def repo_secret(self, repo: str, name: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/secrets/{name}."""
        return self._get(f"{self._repo(repo)}/actions/secrets/{_q(name)}")

    def repo_variables(self, name: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{name}/actions/variables (per_page 30)."""
        path = f"{self._repo(name)}/actions/variables"
        return self._list("repo_variables", (name,), path, item_key="variables", per_page=VARIABLES_PER_PAGE)

    def repo_variable(self, repo: str, name: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/actions/variables/{name}."""
        return self._get(f"{self._repo(repo)}/actions/variables/{_q(name)}")

    def repo_hooks(self, name: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{name}/hooks."""
        return self._list("repo_hooks", (name,), f"{self._repo(name)}/hooks")

    def repo_hook_by_url(self, repo: str, url: str) -> dict[str, Any] | None:
        """The repo hook whose config.url equals ``url``."""
        return next((hook for hook in self.repo_hooks(repo) if (hook.get("config") or {}).get("url") == url), None)

    def repo_hook_deliveries(self, repo: str, hook_id: int) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/hooks/{id}/deliveries."""
        path = f"{self._repo(repo)}/hooks/{int(hook_id)}/deliveries"
        return self._list("repo_hook_deliveries", (repo, hook_id), path, max_pages=DELIVERY_PAGES)

    def repo_hook_deliveries_by_url(self, repo: str, url: str) -> list[dict[str, Any]]:
        """Deliveries of the repo hook whose config.url equals ``url`` ([] while no such hook exists)."""
        hook = self.repo_hook_by_url(repo, url)
        return [] if hook is None else self.repo_hook_deliveries(repo, int(hook["id"]))

    def repo_hook_delivery(self, repo: str, hook_id: int, delivery_id: int) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/hooks/{id}/deliveries/{delivery_id}: one delivery with its request and response."""
        return self._get(f"{self._repo(repo)}/hooks/{int(hook_id)}/deliveries/{int(delivery_id)}")

    def repo_hook_latest_delivery_by_url(self, repo: str, url: str, event: str) -> dict[str, Any] | None:
        """The newest delivery of ``event`` of the repo hook with this URL, in full; None while there is none."""
        hook = self.repo_hook_by_url(repo, url)
        if hook is None:
            return None
        hook_id = int(hook["id"])
        delivery = self._find(self.repo_hook_deliveries(repo, hook_id), "event", event)
        return None if delivery is None else self.repo_hook_delivery(repo, hook_id, int(delivery["id"]))

    def branch_protection_rules(self, repo: str) -> list[dict[str, Any]]:
        """Branch protection rules via GraphQL (fields: BPR_FIELDS and requiredStatusChecks {context, app {slug}},
        plus the node ``id``; no allowance actors, see branch_protection_rule)."""
        variables = {"owner": self.org_login, "name": repo}
        path = ["repository", "branchProtectionRules"]
        return self._graphql_pages("branch_protection_rules", (repo,), BPR_QUERY, variables, path)

    def branch_protection_rule(self, repo: str, pattern: str) -> dict[str, Any] | None:
        """The branch protection rule with this pattern, in detail: the branch_protection_rules fields plus the actor
        lists BPR_ALLOWANCES in otterdog's notation (``@login``, ``@<org>/<team>``, ``<app slug>``)."""
        variables = {"owner": self.org_login, "name": repo}
        path = ["repository", "branchProtectionRules"]
        rules = self._graphql_pages("branch_protection_rules", (repo,), BPR_DETAIL_QUERY, variables, path)
        rule = self._find(rules, "pattern", pattern)
        return None if rule is None else _flatten_allowances(rule)

    def repo_rulesets(self, repo: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/rulesets (includes_parents false; [] on 403/404, recorded unavailable)."""
        params = {"includes_parents": "false"}
        return self._list("repo_rulesets", (repo,), f"{self._repo(repo)}/rulesets", params=params)

    def repo_ruleset(self, repo: str, name: str) -> dict[str, Any] | None:
        """Full repo ruleset by name."""
        summary = self._find(self.repo_rulesets(repo), "name", name)
        if summary is None:
            return None
        params = {"includes_parents": "false"}
        return self._get(f"{self._repo(repo)}/rulesets/{int(summary['id'])}", params=params)

    def environments(self, repo: str) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/environments (item_key environments)."""
        return self._list("environments", (repo,), f"{self._repo(repo)}/environments", item_key="environments")

    def _env(self, repo: str, env: str) -> str:
        """``/repos/{org}/{repo}/environments/{env}`` with the environment name URL-encoded."""
        return f"{self._repo(repo)}/environments/{_q(env)}"

    def environment(self, repo: str, name: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/environments/{name} (name URL-encoded)."""
        return self._get(self._env(repo, name))

    def environment_branch_policies(self, repo: str, env: str) -> list[dict[str, Any]]:
        """GET .../environments/{env}/deployment-branch-policies (item_key branch_policies)."""
        path = f"{self._env(repo, env)}/deployment-branch-policies"
        return self._list("environment_branch_policies", (repo, env), path, item_key="branch_policies")

    def environment_secrets(self, repo: str, env: str) -> list[dict[str, Any]]:
        """GET .../environments/{env}/secrets."""
        path = f"{self._env(repo, env)}/secrets"
        return self._list("environment_secrets", (repo, env), path, item_key="secrets")

    def environment_secret(self, repo: str, env: str, name: str) -> dict[str, Any] | None:
        """GET .../environments/{env}/secrets/{name}."""
        return self._get(f"{self._env(repo, env)}/secrets/{_q(name)}")

    def environment_variables(self, repo: str, env: str) -> list[dict[str, Any]]:
        """GET .../environments/{env}/variables (per_page 30)."""
        path = f"{self._env(repo, env)}/variables"
        return self._list("environment_variables", (repo, env), path, item_key="variables", per_page=VARIABLES_PER_PAGE)

    def environment_variable(self, repo: str, env: str, name: str) -> dict[str, Any] | None:
        """GET .../environments/{env}/variables/{name}."""
        return self._get(f"{self._env(repo, env)}/variables/{_q(name)}")

    def pages(self, repo: str) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/pages."""
        return self._get(f"{self._repo(repo)}/pages")

    def repo_custom_property_values(self, repo: str) -> dict[str, Any]:
        """{property_name: value} of GET /repos/{org}/{repo}/properties/values ({} on 403/404, recorded unavailable)."""
        values = self._list("repo_custom_property_values", (repo,), f"{self._repo(repo)}/properties/values")
        return {str(item["property_name"]): item.get("value") for item in values if isinstance(item, dict)}

    # --- git and pull requests ----------------------------------------------------------------------------------
    def default_branch(self, repo: str) -> str | None:
        """default_branch of the repo."""
        branch = (self.repo(repo) or {}).get("default_branch")
        return str(branch) if branch else None

    def branch_sha(self, repo: str, branch: str) -> str | None:
        """Head commit sha of a branch (GET git/ref/heads/{branch}); None when absent or the repo is empty."""
        return self._ref_sha(repo, f"heads/{branch}")

    def _ref_sha(self, repo: str, ref: str) -> str | None:
        """Object sha of a ref ``heads/<b>`` / ``tags/<t>`` (GET git/ref/{ref}); None on 404/409 (empty repo)."""
        path = f"{self._repo(repo)}/git/ref/{urllib.parse.quote(ref.removeprefix('refs/'), safe='/')}"
        response = self.http.request("GET", path, allow=(404, 409))
        if response.status_code in (404, 409):
            return None
        body = response.json()
        sha = (body.get("object") or {}).get("sha") if isinstance(body, dict) else None
        return str(sha) if sha else None

    def matching_refs(self, repo: str, prefix: str) -> list[dict[str, Any]]:
        """Refs whose name starts with ``refs/<prefix>`` (GET git/matching-refs; [] on 403/404/409, recorded)."""
        prefix = prefix.removeprefix("refs/")
        path = f"{self._repo(repo)}/git/matching-refs/{urllib.parse.quote(prefix.rstrip('/'), safe='/')}"
        try:
            refs = self._list("matching_refs", (repo, prefix), path)
        except GitHubError as exc:
            if exc.status != 409:
                raise
            refs = self._settle("matching_refs", (repo, prefix), 409, [])
        wanted = f"refs/{prefix}"
        return [ref for ref in refs if isinstance(ref, dict) and str(ref.get("ref", "")).startswith(wanted)]

    def git_commit(self, repo: str, sha: str) -> dict[str, Any] | None:
        """GET git/commits/{sha}: message, tree, parents, author/committer dates (None on 404/409)."""
        response = self.http.request("GET", f"{self._repo(repo)}/git/commits/{_q(sha)}", allow=(404, 409))
        if response.status_code in (404, 409):
            return None
        body = response.json()
        return body if isinstance(body, dict) else None

    def file_content(self, repo: str, path: str, ref: str | None = None) -> str | None:
        """Decoded content of a file (GET contents), None when absent."""
        url = f"{self._repo(repo)}/contents/{urllib.parse.quote(path.lstrip('/'), safe='/')}"
        params = {"ref": ref} if ref else None
        body = self._get(url, params=params)
        if not isinstance(body, dict) or body.get("type") != "file":
            return None
        if body.get("encoding") == "base64" and isinstance(body.get("content"), str):
            return base64.b64decode(body["content"]).decode("utf-8", errors="replace")
        raw = self.http.get(url, params=params, headers={"Accept": RAW_MEDIA_TYPE}, allow_404=True)
        return raw if isinstance(raw, str) else None

    def pull(self, repo: str, number: int) -> dict[str, Any] | None:
        """GET /repos/{org}/{repo}/pulls/{number}."""
        return self._get(f"{self._repo(repo)}/pulls/{int(number)}")

    def pulls(self, repo: str, state: str = "open") -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/pulls?state=..."""
        return self._list("pulls", (repo, state), f"{self._repo(repo)}/pulls", params={"state": state})

    def combined_status(self, repo: str, sha: str) -> dict[str, Any]:
        """GET /repos/{org}/{repo}/commits/{sha}/status (latest status per context; empty pending on 404)."""
        body = self._get(f"{self._repo(repo)}/commits/{_q(sha)}/status", params={"per_page": 100})
        if not isinstance(body, dict):
            return {"sha": sha, "state": "pending", "total_count": 0, "statuses": []}
        return body

    def latest_status(self, repo: str, sha: str, context: str) -> dict[str, Any] | None:
        """The latest commit status of ``context`` on ``sha``."""
        return self._find(list(self.combined_status(repo, sha).get("statuses") or []), "context", context)

    def commit_statuses(self, repo: str, ref: str) -> list[dict[str, Any]]:
        """Every commit status of ``ref`` (a sha, branch or tag), newest first: GET
        /repos/{org}/{repo}/commits/{ref}/statuses, paginated ([] on 404, recorded unavailable)."""
        return self._list("commit_statuses", (repo, ref), f"{self._repo(repo)}/commits/{_q(ref)}/statuses")

    def issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        """GET /repos/{org}/{repo}/issues/{number}/comments."""
        return self._list("issue_comments", (repo, number), f"{self._repo(repo)}/issues/{int(number)}/comments")

    def pr_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        """PR comments via GraphQL: id, author (login without "[bot]"), body, is_minimized, minimized_reason,
        created_at, database_id."""
        variables = {"owner": self.org_login, "name": repo, "number": int(number)}
        path = ["repository", "pullRequest", "comments"]
        nodes = self._graphql_pages("pr_comments", (repo, number), PR_COMMENTS_QUERY, variables, path)
        return [self._comment(node) for node in nodes]

    @staticmethod
    def _comment(node: dict[str, Any]) -> dict[str, Any]:
        """pr_comments shape of a GraphQL IssueComment node."""
        author = (node.get("author") or {}).get("login")
        return {
            "id": node.get("id"),
            "database_id": node.get("databaseId"),
            "author": str(author).removesuffix("[bot]") if author else None,
            "body": node.get("body") or "",
            "is_minimized": bool(node.get("isMinimized")),
            "minimized_reason": node.get("minimizedReason"),
            "created_at": node.get("createdAt"),
        }

    def lookup(self, kind: str, **params: Any) -> Any:
        """Dispatch a check kind to its Oracle method (scenarios.checks.CHECK_KINDS)."""
        from otterdog_e2e.scenarios.checks import CHECK_KINDS

        method, names = CHECK_KINDS[kind]
        missing = [name for name in names if name not in params]
        if missing:
            raise TypeError(f"check kind {kind!r} needs parameter(s) {missing}")
        return getattr(self, method)(*(params[name] for name in names))
