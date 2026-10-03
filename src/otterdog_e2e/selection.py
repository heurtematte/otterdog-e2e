"""Scenario tag selection from the files an otterdog PR changes (SPEC 14).

PATH_RULES maps globs on upstream otterdog paths to scenario tags; ALWAYS_TAGS are always selected. Globs are
path-aware: ``*`` and ``?`` stay inside one path segment, ``**`` spans segments (``a/**`` matches everything below
``a``). Every matching rule contributes its tags (rules are additive, order does not matter).

Scenario tag vocabulary (SCENARIO_TAGS): repo, bpr, rulesets, environments, secrets, variables, webhooks, teams,
custom-properties, org-settings, workflows, org-roles (model areas, CLI and webapp scenarios alike); template (the
base template / jsonnet layer); cli (CLI commands beyond plan/apply: version, list-projects, check-token-permissions,
push/fetch-config, import, open-pr, check-status); webapp (config-repo PR workflow); webhooks-app (App webhook
receiver and deliveries); offline (offline tier: validate/local-plan/show) and smoke (always).

Sources: FACTS tests.json harness_requirements ("Changed-path to suite selector") and providers.json ("PR impact map":
rest/repo_client.py -> repo/env/secret/ruleset; graphql.py and resources/graphql/* -> BPR, team permissions and PR
comments; web.py and github-web-settings.jsonnet -> web settings; cache/* and requester.py -> every API caller;
auth/* and webapp/utils.py -> App and webhook-app), checked against the upstream tree.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from functools import lru_cache

MODEL_TAGS = (
    "repo",
    "bpr",
    "rulesets",
    "environments",
    "secrets",
    "variables",
    "webhooks",
    "teams",
    "custom-properties",
    "org-settings",
    "workflows",
    "org-roles",
)
SCENARIO_TAGS = (*MODEL_TAGS, "template", "cli", "webapp", "webhooks-app", "offline", "smoke")
# changes that can affect every scenario (core model/diff machinery, shared utilities, dependencies)
ALL_TAGS = tuple(tag for tag in SCENARIO_TAGS if tag != "smoke")
# changes affecting every live API caller (CLI and webapp) but not the offline tier
LIVE_TAGS = (*MODEL_TAGS, "cli", "webapp", "webhooks-app")

PATH_RULES: list[tuple[str, tuple[str, ...]]] = [
    # --- models: one area per model file; the base model and the org root affect everything ---------------------
    ("otterdog/models/__init__.py", ALL_TAGS),
    ("otterdog/models/github_organization.py", (*MODEL_TAGS, "offline", "webapp")),
    ("otterdog/models/repository.py", ("repo", "offline")),
    ("otterdog/models/branch_protection_rule.py", ("bpr", "offline")),
    ("otterdog/models/ruleset.py", ("rulesets", "offline")),
    ("otterdog/models/repo_ruleset.py", ("rulesets", "offline")),
    ("otterdog/models/organization_ruleset.py", ("rulesets", "offline")),
    ("otterdog/models/environment.py", ("environments", "offline")),
    ("otterdog/models/environment_secret.py", ("environments", "secrets", "offline")),
    ("otterdog/models/environment_variable.py", ("environments", "variables", "offline")),
    ("otterdog/models/secret.py", ("secrets", "offline")),
    ("otterdog/models/repo_secret.py", ("secrets", "repo", "offline")),
    ("otterdog/models/organization_secret.py", ("secrets", "offline")),
    ("otterdog/models/variable.py", ("variables", "offline")),
    ("otterdog/models/repo_variable.py", ("variables", "repo", "offline")),
    ("otterdog/models/organization_variable.py", ("variables", "offline")),
    ("otterdog/models/webhook.py", ("webhooks", "offline")),
    ("otterdog/models/repo_webhook.py", ("webhooks", "repo", "offline")),
    ("otterdog/models/organization_webhook.py", ("webhooks", "offline")),
    ("otterdog/models/team.py", ("teams",)),
    ("otterdog/models/custom_property.py", ("custom-properties", "offline")),
    ("otterdog/models/organization_settings.py", ("org-settings", "offline")),
    ("otterdog/models/workflow_settings.py", ("workflows", "offline")),
    ("otterdog/models/organization_workflow_settings.py", ("workflows", "org-settings", "offline")),
    ("otterdog/models/repo_workflow_settings.py", ("workflows", "repo", "offline")),
    ("otterdog/models/role.py", ("org-roles", "offline")),
    ("otterdog/models/organization_role.py", ("org-roles", "offline")),
    # --- JSON schemas (validation, offline tier) ------------------------------------------------------------------
    ("otterdog/resources/schemas/**", ("offline",)),
    ("otterdog/resources/schemas/types.json", MODEL_TAGS),
    ("otterdog/resources/schemas/organization.json", ("org-settings",)),
    ("otterdog/resources/schemas/settings.json", ("org-settings",)),
    ("otterdog/resources/schemas/repository.json", ("repo",)),
    ("otterdog/resources/schemas/branch-protection-rule.json", ("bpr",)),
    ("otterdog/resources/schemas/*ruleset*.json", ("rulesets",)),
    ("otterdog/resources/schemas/environment*.json", ("environments",)),
    ("otterdog/resources/schemas/*secret*.json", ("secrets",)),
    ("otterdog/resources/schemas/*variable*.json", ("variables",)),
    ("otterdog/resources/schemas/webhook.json", ("webhooks",)),
    ("otterdog/resources/schemas/team*.json", ("teams",)),
    ("otterdog/resources/schemas/custom-property.json", ("custom-properties",)),
    ("otterdog/resources/schemas/*workflow-settings.json", ("workflows",)),
    ("otterdog/resources/schemas/*role.json", ("org-roles",)),
    # --- GraphQL queries and web settings ---------------------------------------------------------------------------
    ("otterdog/resources/graphql/get-branch-protection-rule*.gql", ("bpr",)),
    ("otterdog/resources/graphql/get-bypass-*.gql", ("bpr",)),
    ("otterdog/resources/graphql/get-push-allowances.gql", ("bpr",)),
    ("otterdog/resources/graphql/get-review-dismissal-allowances.gql", ("bpr",)),
    ("otterdog/resources/graphql/get-team-*.gql", ("teams", "webapp")),
    ("otterdog/resources/graphql/get-repository-permissions-of-team.gql", ("teams",)),
    ("otterdog/resources/graphql/get-issue-comments.gql", ("webapp",)),
    ("otterdog/resources/graphql/get-pull-requests.gql", ("webapp",)),
    ("otterdog/resources/github-web-settings.jsonnet", ("org-settings",)),
    ("otterdog/resources/__init__.py", ("offline", "cli")),
    # --- GitHub provider ------------------------------------------------------------------------------------------
    ("otterdog/providers/github/__init__.py", LIVE_TAGS),
    ("otterdog/providers/github/rest/__init__.py", LIVE_TAGS),
    ("otterdog/providers/github/rest/requester.py", LIVE_TAGS),
    ("otterdog/providers/github/exception.py", ("cli", "webapp")),
    (
        "otterdog/providers/github/rest/repo_client.py",
        ("repo", "environments", "secrets", "variables", "rulesets", "webhooks", "workflows", "custom-properties"),
    ),
    (
        "otterdog/providers/github/rest/org_client.py",
        ("org-settings", "secrets", "variables", "webhooks", "rulesets", "custom-properties", "org-roles", "workflows"),
    ),
    ("otterdog/providers/github/rest/team_client.py", ("teams", "webapp")),
    ("otterdog/providers/github/rest/user_client.py", ("teams", "cli")),
    ("otterdog/providers/github/rest/action_client.py", ("workflows",)),
    ("otterdog/providers/github/rest/app_client.py", ("webapp", "webhooks-app")),
    ("otterdog/providers/github/rest/content_client.py", ("cli", "webapp")),
    ("otterdog/providers/github/rest/reference_client.py", ("cli", "webapp")),
    ("otterdog/providers/github/rest/pull_request_client.py", ("cli", "webapp")),
    ("otterdog/providers/github/rest/commit_client.py", ("webapp",)),
    ("otterdog/providers/github/rest/issue_client.py", ("webapp",)),
    ("otterdog/providers/github/rest/meta_client.py", ("cli",)),
    ("otterdog/providers/github/graphql.py", ("bpr", "teams", "webapp")),
    ("otterdog/providers/github/web.py", ("org-settings", "cli")),
    ("otterdog/providers/github/auth/**", ("cli", "webapp", "webhooks-app")),
    ("otterdog/providers/github/cache/file.py", ("cli",)),
    ("otterdog/providers/github/cache/**", ("webapp",)),
    ("otterdog/providers/github/cache/__init__.py", ("cli",)),
    ("otterdog/providers/github/stats/**", ("webapp",)),
    # --- operations (CLI commands) ----------------------------------------------------------------------------------
    ("otterdog/operations/__init__.py", ALL_TAGS),
    ("otterdog/operations/diff_operation.py", ("repo", "cli", "offline", "webapp")),
    ("otterdog/operations/plan.py", ("repo", "cli", "webapp")),
    ("otterdog/operations/apply.py", ("repo", "cli")),
    ("otterdog/operations/local_plan.py", ("offline", "webapp")),
    ("otterdog/operations/local_apply.py", ("webapp", "cli")),
    ("otterdog/operations/validate.py", ("offline", "cli")),
    ("otterdog/operations/show.py", ("offline",)),
    ("otterdog/operations/show_default.py", ("offline", "template")),
    ("otterdog/operations/canonical_diff.py", ("offline",)),
    ("otterdog/operations/list_projects.py", ("offline", "cli")),
    ("otterdog/operations/show_live.py", ("cli",)),
    ("otterdog/operations/check_status.py", ("cli",)),
    ("otterdog/operations/check_token_permissions.py", ("cli",)),
    ("otterdog/operations/push_config.py", ("cli",)),
    ("otterdog/operations/fetch_config.py", ("cli",)),
    ("otterdog/operations/open_pull_request.py", ("cli",)),
    ("otterdog/operations/import_configuration.py", ("cli",)),
    ("otterdog/operations/list_members.py", ("cli", "teams")),
    ("otterdog/operations/*.py", ("cli",)),
    ("otterdog/operations/*blueprint*.py", ("webapp",)),
    # --- core modules -----------------------------------------------------------------------------------------------
    ("otterdog/cli.py", ("cli", "offline", "repo")),
    ("otterdog/config.py", ("cli", "offline", "webapp")),
    ("otterdog/jsonnet.py", ("template", "offline", "cli")),
    ("otterdog/utils.py", ALL_TAGS),
    ("otterdog/logging.py", ("cli", "offline")),
    ("otterdog/cache.py", ("cli", "webapp")),
    ("otterdog/credentials/**", ("cli", "offline")),
    ("otterdog/__init__.py", ("cli", "offline")),
    ("otterdog/app.py", ("webapp", "webhooks-app")),
    # --- webapp ---------------------------------------------------------------------------------------------------
    ("otterdog/webapp/**", ("webapp",)),
    ("otterdog/webapp/webhook/__init__.py", ("webhooks-app",)),
    ("otterdog/webapp/webhook/github_webhook.py", ("webhooks-app",)),
    ("otterdog/webapp/webhook/github_models.py", ("webhooks-app",)),
    ("otterdog/webapp/utils.py", ("webhooks-app",)),
    ("otterdog/webapp/__init__.py", ("webhooks-app",)),
    ("otterdog/webapp/config.py", ("webhooks-app",)),
    # --- template, packaging and image ------------------------------------------------------------------------------
    ("examples/template/**", ("template", "offline", "repo")),
    ("docker/**", ("webapp", "webhooks-app", "cli")),
    ("pyproject.toml", ALL_TAGS),
    ("poetry.lock", ALL_TAGS),
    ("otterdog.sh", ("cli",)),
]
ALWAYS_TAGS = ("smoke",)


def select_tags(changed_files: Iterable[str]) -> set[str]:
    """ALWAYS_TAGS plus the tags of every PATH_RULES glob matching a changed file."""
    tags = set(ALWAYS_TAGS)
    for path in changed_files:
        tags.update(tags_for_path(path))
    return tags


def tags_for_path(path: str) -> set[str]:
    """Tags of every rule matching one path (empty for docs, tests and other unmapped files)."""
    normalized = normalize_path(path)
    return {tag for pattern, tags in PATH_RULES if glob_regex(pattern).match(normalized) for tag in tags}


def explain(changed_files: Iterable[str]) -> dict[str, list[str]]:
    """Changed file -> sorted tags (unmapped files map to []), for reports."""
    return {path: sorted(tags_for_path(path)) for path in changed_files}


def unmapped(changed_files: Iterable[str]) -> list[str]:
    """Changed files no rule covers (documentation, upstream tests, CI files, ...)."""
    return [path for path in changed_files if not tags_for_path(path)]


def normalize_path(path: str) -> str:
    """Repository-relative POSIX form of a changed path (backslashes, ``./`` and leading ``/`` removed)."""
    normalized = path.strip().replace("\\", "/")
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized.lstrip("/")


@lru_cache(maxsize=512)
def glob_regex(pattern: str) -> re.Pattern[str]:
    """Path-aware glob: ``**`` spans segments (``a/**`` also matches files directly in ``a``), ``*``/``?`` do not."""
    parts: list[str] = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("**/", index):
            parts.append("(?:.*/)?")
            index += 3
        elif pattern.startswith("**", index):
            parts.append(".*")
            index += 2
        elif pattern[index] == "*":
            parts.append("[^/]*")
            index += 1
        elif pattern[index] == "?":
            parts.append("[^/]")
            index += 1
        else:
            parts.append(re.escape(pattern[index]))
            index += 1
    return re.compile("^" + "".join(parts) + "$")


def rules_by_tag() -> Mapping[str, list[str]]:
    """Tag -> globs selecting it (documentation and self-checks)."""
    result: dict[str, list[str]] = {}
    for pattern, tags in PATH_RULES:
        for tag in tags:
            result.setdefault(tag, []).append(pattern)
    return result
