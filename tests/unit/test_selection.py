"""Changed-path -> scenario tag selection (SPEC 14 selection.py)."""

from __future__ import annotations

import pytest

from otterdog_e2e.selection import (
    ALL_TAGS,
    ALWAYS_TAGS,
    PATH_RULES,
    SCENARIO_TAGS,
    explain,
    glob_regex,
    normalize_path,
    rules_by_tag,
    select_tags,
    tags_for_path,
    unmapped,
)

# a sample of real upstream paths (eclipse-csi/otterdog main); every rule must match one of them
UPSTREAM_PATHS = (
    "otterdog/models/__init__.py",
    "otterdog/models/github_organization.py",
    "otterdog/models/repository.py",
    "otterdog/models/branch_protection_rule.py",
    "otterdog/models/ruleset.py",
    "otterdog/models/repo_ruleset.py",
    "otterdog/models/organization_ruleset.py",
    "otterdog/models/environment.py",
    "otterdog/models/environment_secret.py",
    "otterdog/models/environment_variable.py",
    "otterdog/models/secret.py",
    "otterdog/models/repo_secret.py",
    "otterdog/models/organization_secret.py",
    "otterdog/models/variable.py",
    "otterdog/models/repo_variable.py",
    "otterdog/models/organization_variable.py",
    "otterdog/models/webhook.py",
    "otterdog/models/repo_webhook.py",
    "otterdog/models/organization_webhook.py",
    "otterdog/models/team.py",
    "otterdog/models/custom_property.py",
    "otterdog/models/organization_settings.py",
    "otterdog/models/workflow_settings.py",
    "otterdog/models/organization_workflow_settings.py",
    "otterdog/models/repo_workflow_settings.py",
    "otterdog/models/role.py",
    "otterdog/models/organization_role.py",
    "otterdog/resources/schemas/types.json",
    "otterdog/resources/schemas/organization.json",
    "otterdog/resources/schemas/settings.json",
    "otterdog/resources/schemas/repository.json",
    "otterdog/resources/schemas/branch-protection-rule.json",
    "otterdog/resources/schemas/org-ruleset.json",
    "otterdog/resources/schemas/environment-secret.json",
    "otterdog/resources/schemas/repo-secret.json",
    "otterdog/resources/schemas/org-variable.json",
    "otterdog/resources/schemas/webhook.json",
    "otterdog/resources/schemas/team-permission.json",
    "otterdog/resources/schemas/custom-property.json",
    "otterdog/resources/schemas/repo-workflow-settings.json",
    "otterdog/resources/schemas/org-role.json",
    "otterdog/resources/graphql/get-branch-protection-rules.gql",
    "otterdog/resources/graphql/get-bypass-pull-request-allowances.gql",
    "otterdog/resources/graphql/get-push-allowances.gql",
    "otterdog/resources/graphql/get-review-dismissal-allowances.gql",
    "otterdog/resources/graphql/get-team-membership.gql",
    "otterdog/resources/graphql/get-repository-permissions-of-team.gql",
    "otterdog/resources/graphql/get-issue-comments.gql",
    "otterdog/resources/graphql/get-pull-requests.gql",
    "otterdog/resources/github-web-settings.jsonnet",
    "otterdog/resources/__init__.py",
    "otterdog/providers/github/__init__.py",
    "otterdog/providers/github/rest/__init__.py",
    "otterdog/providers/github/rest/requester.py",
    "otterdog/providers/github/exception.py",
    "otterdog/providers/github/rest/repo_client.py",
    "otterdog/providers/github/rest/org_client.py",
    "otterdog/providers/github/rest/team_client.py",
    "otterdog/providers/github/rest/user_client.py",
    "otterdog/providers/github/rest/action_client.py",
    "otterdog/providers/github/rest/app_client.py",
    "otterdog/providers/github/rest/content_client.py",
    "otterdog/providers/github/rest/reference_client.py",
    "otterdog/providers/github/rest/pull_request_client.py",
    "otterdog/providers/github/rest/commit_client.py",
    "otterdog/providers/github/rest/issue_client.py",
    "otterdog/providers/github/rest/meta_client.py",
    "otterdog/providers/github/graphql.py",
    "otterdog/providers/github/web.py",
    "otterdog/providers/github/auth/app.py",
    "otterdog/providers/github/cache/file.py",
    "otterdog/providers/github/cache/redis.py",
    "otterdog/providers/github/cache/__init__.py",
    "otterdog/providers/github/stats/__init__.py",
    "otterdog/operations/__init__.py",
    "otterdog/operations/diff_operation.py",
    "otterdog/operations/plan.py",
    "otterdog/operations/apply.py",
    "otterdog/operations/local_plan.py",
    "otterdog/operations/local_apply.py",
    "otterdog/operations/validate.py",
    "otterdog/operations/show.py",
    "otterdog/operations/show_default.py",
    "otterdog/operations/canonical_diff.py",
    "otterdog/operations/list_projects.py",
    "otterdog/operations/show_live.py",
    "otterdog/operations/check_status.py",
    "otterdog/operations/check_token_permissions.py",
    "otterdog/operations/push_config.py",
    "otterdog/operations/fetch_config.py",
    "otterdog/operations/open_pull_request.py",
    "otterdog/operations/import_configuration.py",
    "otterdog/operations/list_members.py",
    "otterdog/operations/approve_blueprints.py",
    "otterdog/cli.py",
    "otterdog/config.py",
    "otterdog/jsonnet.py",
    "otterdog/utils.py",
    "otterdog/logging.py",
    "otterdog/cache.py",
    "otterdog/credentials/env_provider.py",
    "otterdog/__init__.py",
    "otterdog/app.py",
    "otterdog/webapp/db/service.py",
    "otterdog/webapp/webhook/__init__.py",
    "otterdog/webapp/webhook/github_webhook.py",
    "otterdog/webapp/webhook/github_models.py",
    "otterdog/webapp/utils.py",
    "otterdog/webapp/__init__.py",
    "otterdog/webapp/config.py",
    "examples/template/otterdog-defaults.libsonnet",
    "docker/Dockerfile",
    "pyproject.toml",
    "poetry.lock",
    "otterdog.sh",
)


def test_every_rule_matches_an_upstream_path_and_uses_known_tags() -> None:
    """No dead globs; only the documented tag vocabulary."""
    dead = [pattern for pattern, _ in PATH_RULES if not any(glob_regex(pattern).match(p) for p in UPSTREAM_PATHS)]
    assert dead == []
    assert {tag for _, tags in PATH_RULES for tag in tags} <= set(SCENARIO_TAGS)
    assert set(rules_by_tag()) == set(ALL_TAGS)  # every tag but smoke is selectable from some path


def test_always_tags() -> None:
    """Documentation-only changes still select the smoke set."""
    assert select_tags([]) == {"smoke"} == set(ALWAYS_TAGS)
    assert select_tags(["docs/index.md", "README.md", "tests/models/test_repo.py", ".github/workflows/x.yml"]) == {
        "smoke"
    }


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("otterdog/models/repo_ruleset.py", {"rulesets", "offline"}),
        ("otterdog/models/environment_secret.py", {"environments", "secrets", "offline"}),
        ("otterdog/resources/schemas/org-ruleset.json", {"rulesets", "offline"}),
        ("otterdog/resources/graphql/get-team-membership.gql", {"teams", "webapp"}),
        ("otterdog/webapp/db/service.py", {"webapp"}),
        ("otterdog/webapp/tasks/apply_changes.py", {"webapp"}),
        ("otterdog/webapp/templates/comment/validation_comment.txt", {"webapp"}),
        ("otterdog/webapp/webhook/comment_handlers.py", {"webapp"}),
        ("otterdog/webapp/webhook/github_webhook.py", {"webapp", "webhooks-app"}),
        ("otterdog/operations/push_config.py", {"cli"}),
        ("otterdog/operations/local_plan.py", {"offline", "webapp", "cli"}),
        ("otterdog/providers/github/auth/token.py", {"cli", "webapp", "webhooks-app"}),
        ("otterdog/jsonnet.py", {"template", "offline", "cli"}),
        ("examples/template/otterdog-defaults.libsonnet", {"template", "offline", "repo"}),
    ],
)
def test_tags_for_path(path: str, expected: set[str]) -> None:
    """Representative mappings of the PR impact map."""
    assert tags_for_path(path) == expected


def test_core_changes_select_everything() -> None:
    """The base model, shared utilities and dependencies may affect every scenario."""
    for path in ("otterdog/models/__init__.py", "otterdog/utils.py", "poetry.lock", "pyproject.toml"):
        assert select_tags([path]) == {*ALL_TAGS, "smoke"}


def test_repo_client_impact() -> None:
    """rest/repo_client.py maps to repo/env/secret/ruleset scenarios (providers.json PR impact map)."""
    assert {"repo", "environments", "secrets", "rulesets"} <= select_tags(
        ["otterdog/providers/github/rest/repo_client.py"]
    )


def test_globs_are_path_aware() -> None:
    """``*`` stays within a segment, ``**`` spans segments (and matches directly below)."""
    assert glob_regex("otterdog/models/*.py").match("otterdog/models/team.py")
    assert not glob_regex("otterdog/models/*.py").match("otterdog/models/sub/team.py")
    assert glob_regex("otterdog/webapp/**").match("otterdog/webapp/tasks/x.py")
    assert glob_regex("a/**/b.py").match("a/b.py") and glob_regex("a/**/b.py").match("a/x/y/b.py")
    assert not glob_regex("a?c").match("a/c")


def test_paths_are_normalized_and_explained() -> None:
    """Leading ./ or /, Windows separators; explain and unmapped for reports."""
    assert normalize_path("./otterdog\\cli.py") == "otterdog/cli.py" == normalize_path("/otterdog/cli.py")
    assert select_tags(["./otterdog/models/team.py"]) == {"teams", "smoke"}
    report = explain(["otterdog/models/team.py", "docs/x.md"])
    assert report == {"otterdog/models/team.py": ["teams"], "docs/x.md": []}
    assert unmapped(["otterdog/models/team.py", "docs/x.md"]) == ["docs/x.md"]
