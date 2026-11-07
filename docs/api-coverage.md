# HTTP request coverage

<!-- generated from scenarios/api_endpoints.yaml and the live scenarios: .venv/bin/python tests/unit/test_api_endpoints.py --write -->

Every write request otterdog sends to GitHub (REST `POST`, `PUT`, `PATCH`, `DELETE` and GraphQL mutations), listed in [scenarios/api_endpoints.yaml](../scenarios/api_endpoints.yaml) at otterdog `a196494`, and the live scenario steps whose `apply.api` asserts it. A step asserts the requests of its apply from otterdog's request statistics (otterdog 1.7.0 and later, [writing scenarios](writing-scenarios.md#http-requests-of-an-apply)): `sent` means the apply sent at least one such request, `not sent` that it sent none (for instance no `PATCH /repos/{owner}/{repo}` when only `team_permissions` change, otterdog#924).

**84 of 97** endpoints the CLI sends are asserted as sent by at least one step.

| Method | Asserted sent | Endpoints |
|---|---:|---:|
| POST | 14 | 17 |
| PUT | 30 | 34 |
| PATCH | 10 | 14 |
| DELETE | 27 | 29 |
| mutation | 3 | 3 |

Endpoints nobody asserts yet are the gaps of this page: a scenario that adds, changes or removes the object should name them in the `apply.api.sent` of the step (the `fill-coverage-gap` skill).

## Endpoints

| Endpoint | Trigger | Asserted sent by | Asserted not sent by |
|---|---|---|---|
| `PATCH /orgs/{org}` | an organization setting changes (update_settings) | `cli.org.member-privileges/fork`, `cli.org.member-privileges/privileges` |  |
| `PUT /orgs/{org}/settings/immutable-releases` | settings.immutable_releases_enforced_repositories changes | **none** |  |
| `PUT /orgs/{org}/settings/immutable-releases/repositories` | settings.immutable_releases_selected_repositories changes (enforced_repositories 'selected') | **none** |  |
| `PUT /orgs/{org}/organization-roles/teams/{name}/{id}` | a team is added to settings.security_managers (security manager role) | `cli.org.security-managers/assign` |  |
| `DELETE /orgs/{org}/organization-roles/teams/{name}/{id}` | a team is removed from settings.security_managers | `cli.org.security-managers/unassign` |  |
| `PUT /orgs/{org}/actions/permissions` | workflows.enabled_repositories or workflows.allowed_actions changes | `cli.org.actions-allowed/all`, `cli.org.actions-allowed/selected`, `cli.org.actions-enabled-repositories/all`, `cli.org.actions-enabled-repositories/selected` |  |
| `PUT /orgs/{org}/actions/permissions/repositories` | workflows.selected_repositories changes (enabled_repositories 'selected') | `cli.org.actions-enabled-repositories/selected` |  |
| `PUT /orgs/{org}/actions/permissions/selected-actions` | workflows.github_owned_allowed, verified_allowed or patterns_allowed changes | `cli.org.actions-allowed/selected` |  |
| `PUT /orgs/{org}/actions/permissions/workflow` | workflows.default_workflow_permissions or actions_can_approve_pull_request_reviews changes | `cli.org.workflow-permissions/read`, `cli.org.workflow-permissions/write` |  |
| `PUT /orgs/{org}/actions/permissions/fork-pr-contributor-approval` | workflows.approval_policy changes | `cli.org.actions-allowed/all`, `cli.org.actions-allowed/selected` |  |
| `PUT /orgs/{org}/actions/cache/storage-limit` | workflows.max_cache_size_gb changes | `cli.org.cache-size/limit`, `cli.org.cache-size/template` |  |
| `POST /orgs/{org}/organization-roles` | a custom organization role is added (enterprise) | `enterprise.org-role/create` |  |
| `PATCH /orgs/{org}/organization-roles/{id}` | a custom organization role changes (enterprise) | `enterprise.org-role/update` |  |
| `DELETE /orgs/{org}/organization-roles/{id}` | a custom organization role is removed (apply -d, enterprise) | `enterprise.org-role/remove` |  |
| `POST /orgs/{org}/code-security/configurations` | a code security configuration is added | `cli.code-security.configuration/create` |  |
| `PATCH /orgs/{org}/code-security/configurations/{id}` | a setting of a code security configuration changes | `cli.code-security.configuration/change` |  |
| `PUT /orgs/{org}/code-security/configurations/{id}/defaults` | default_for_new_repos of a configuration changes; also settings.default_code_security_configurations_disabled (org_client.py:926) | **none** |  |
| `DELETE /orgs/{org}/code-security/configurations/{id}` | a code security configuration is removed (apply -d) | `cli.code-security.configuration/delete` |  |
| `POST /orgs/{org}/code-security/configurations/{id}/attach` | a repository's code_security_configuration changes, or a repository is created with one | `cli.code-security.configuration/attach-new-repository` |  |
| `PUT /orgs/{org}/properties/schema/{name}` | a custom property definition is added or changes (add_custom_property, update_custom_property:538) | `cli.custom-property/create`, `cli.custom-property/update` |  |
| `DELETE /orgs/{org}/properties/schema/{name}` | a custom property definition is removed (apply -d) | `cli.custom-property.flag/remove-definition` |  |
| `PATCH /repos/{owner}/{repo}/properties/values` | a repository's custom_properties change | `cli.custom-property.flag/flag-false`, `cli.custom-property/create`, `cli.custom-property/update` |  |
| `POST /orgs/{org}/teams` | a team is added | `cli.team.members/author`, `cli.team/create` |  |
| `PATCH /orgs/{org}/teams/{name}` | a team's description, privacy, notifications or parent changes | `cli.team/update` |  |
| `DELETE /orgs/{org}/teams/{name}` | a team is removed (apply -d) | `cli.team/remove` |  |
| `PUT /orgs/{org}/teams/{name}/memberships/{name}` | a member is added to a team (or a maintainer's role changes) | `cli.team.members/approver`, `cli.team.members/author` |  |
| `DELETE /orgs/{org}/teams/{name}/memberships/{name}` | a member is removed from a team | `cli.team.members/approver` |  |
| `PATCH /orgs/{org}/teams/{name}/team-sync/group-mappings` | a team's identity provider groups change (team sync, enterprise, | **none** |  |
| `PATCH /orgs/{org}/teams/{name}/external-groups` | a team's external group is set (enterprise managed users, | **none** |  |
| `DELETE /orgs/{org}/teams/{name}/external-groups` | a team's external group is removed (enterprise managed users, | **none** |  |
| `PUT /orgs/{org}/teams/{name}/repos/{owner}/{repo}` | a team is added to a repository's team_permissions or its permission changes | `cli.team/create`, `cli.team/update` |  |
| `DELETE /orgs/{org}/teams/{name}/repos/{owner}/{repo}` | a team is removed from a repository's team_permissions (KB-005 fixed in 1.7.0, | `cli.kb.team-permissions-removal/remove-permission` |  |
| `POST /orgs/{org}/hooks` | an organization webhook is added | **none** |  |
| `PATCH /orgs/{org}/hooks/{id}` | an organization webhook changes, or --update-webhooks forces it | **none** |  |
| `DELETE /orgs/{org}/hooks/{id}` | an organization webhook is removed (apply -d) | **none** |  |
| `PUT /orgs/{org}/actions/secrets/{name}` | an organization secret is added or changes (visibility, selected repositories), or --update-secrets | `cli.org.secret/create`, `cli.org.secret/selected` |  |
| `DELETE /orgs/{org}/actions/secrets/{name}` | an organization secret is removed (apply -d) | `cli.org.secret/remove` |  |
| `PUT /orgs/{org}/dependabot/secrets/{name}` | an organization Dependabot secret is added or changes (#890) | `cli.secrets.dependabot-codespaces/create`, `cli.secrets.dependabot-codespaces/selected` |  |
| `DELETE /orgs/{org}/dependabot/secrets/{name}` | an organization Dependabot secret is removed (apply -d) | `cli.secrets.dependabot-codespaces/remove` |  |
| `PUT /orgs/{org}/codespaces/secrets/{name}` | an organization Codespaces secret is added or changes (#890) | `cli.secrets.dependabot-codespaces/create` |  |
| `DELETE /orgs/{org}/codespaces/secrets/{name}` | an organization Codespaces secret is removed (apply -d) | `cli.secrets.dependabot-codespaces/remove` |  |
| `POST /orgs/{org}/actions/variables` | an organization variable is added | `cli.org.variable/variable` |  |
| `PATCH /orgs/{org}/actions/variables/{name}` | an organization variable's value or visibility changes | `cli.org.variable/update` |  |
| `PUT /orgs/{org}/actions/variables/{name}/repositories` | the selected repositories of an organization variable change (visibility 'selected') | `cli.org.variable/selected-two` |  |
| `DELETE /orgs/{org}/actions/variables/{name}` | an organization variable is removed (apply -d) | `cli.org.variable/remove` |  |
| `POST /orgs/{org}/rulesets` | an organization ruleset is added | `enterprise.org-ruleset/create` |  |
| `PUT /orgs/{org}/rulesets/{id}` | an organization ruleset changes | `enterprise.org-ruleset/evaluate`, `enterprise.org-ruleset/repo-conditions` |  |
| `DELETE /orgs/{org}/rulesets/{id}` | an organization ruleset is removed (apply -d) | `enterprise.org-ruleset/remove-ruleset` |  |
| `POST /orgs/{org}/repos` | a repository is added (neither a fork nor from a template) | `cli.bpr.public/create`, `cli.code-security.configuration/attach-new-repository`, `cli.repo.lifecycle/create`, `cli.team/create` | `cli.repo.fork/fork` |
| `POST /repos/{owner}/{repo}/generate` | a repository is added with template_repository | **none** |  |
| `POST /repos/{owner}/{repo}/forks` | a repository is added with forked_repository | `cli.repo.fork/fork` |  |
| `PATCH /repos/{owner}/{repo}` | a repository setting changes (update_repo), archived included; also the settings of a new repository after its creation, and default_branch when the branch exists (repo_client.py:739) | `cli.org.member-privileges/privileges`, `cli.repo.lifecycle/update`, `cli.repo.security/disable`, `cli.repo.security/enable` |  |
| `DELETE /repos/{owner}/{repo}` | a repository is removed (apply -d) | `cli.repo.lifecycle/delete`, `cli.team/remove` |  |
| `POST /repos/{owner}/{repo}/branches/{name}/rename` | default_branch names a branch that does not exist (the current default branch is renamed) | **none** |  |
| `PUT /repos/{owner}/{repo}/topics` | a repository's topics change | `cli.repo.lifecycle/create`, `cli.repo.lifecycle/update` |  |
| `POST /repos/{owner}/{repo}/pages` | gh_pages_build_type is enabled on a repository without a pages site | `cli.repo.pages/legacy` |  |
| `PUT /repos/{owner}/{repo}/pages` | a pages setting changes (source, build type; cname and https_enforced at repo_client.py:660-670) | `cli.repo.pages/source-path` |  |
| `DELETE /repos/{owner}/{repo}/pages` | gh_pages_build_type becomes 'disabled' | `cli.repo.pages/disabled` |  |
| `PATCH /repos/{owner}/{repo}/code-scanning/default-setup` | code_scanning_default_setup_enabled, _query_suite or _languages change | **none** |  |
| `PUT /repos/{owner}/{repo}/vulnerability-alerts` | dependabot_alerts_enabled becomes true | **none** |  |
| `DELETE /repos/{owner}/{repo}/vulnerability-alerts` | dependabot_alerts_enabled becomes false | `cli.repo.security/disable` |  |
| `PUT /repos/{owner}/{repo}/private-vulnerability-reporting` | private_vulnerability_reporting_enabled becomes true | `cli.repo.security/enable` |  |
| `DELETE /repos/{owner}/{repo}/private-vulnerability-reporting` | private_vulnerability_reporting_enabled becomes false | `cli.repo.security/disable` |  |
| `PUT /repos/{owner}/{repo}/immutable-releases` | immutable_releases_enabled becomes true | `cli.repo.immutable-releases/create-enabled` |  |
| `DELETE /repos/{owner}/{repo}/immutable-releases` | immutable_releases_enabled becomes false | `cli.repo.immutable-releases/disable` |  |
| `PUT /repos/{owner}/{repo}/actions/permissions` | workflows.enabled or workflows.allowed_actions of a repository changes | `cli.repo.actions/disabled`, `cli.repo.actions/local-only`, `cli.repo.actions/selected` |  |
| `PUT /repos/{owner}/{repo}/actions/permissions/selected-actions` | workflows.github_owned_allowed, verified_allowed or patterns_allowed of a repository changes | `cli.repo.actions/selected` |  |
| `PUT /repos/{owner}/{repo}/actions/permissions/workflow` | workflows.default_workflow_permissions or actions_can_approve_pull_request_reviews of a repository changes | `cli.repo.org-coerced/managed` |  |
| `PUT /repos/{owner}/{repo}/actions/permissions/fork-pr-contributor-approval` | workflows.approval_policy of a repository changes | `cli.repo.actions/local-only` |  |
| `PUT /repos/{owner}/{repo}/actions/cache/storage-limit` | workflows.max_cache_size_gb of a repository changes | `cli.repo.cache-limit/update` |  |
| `POST /repos/{owner}/{repo}/hooks` | a repository webhook is added | `cli.repo.webhook/create` |  |
| `PATCH /repos/{owner}/{repo}/hooks/{id}` | a repository webhook changes, or --update-webhooks forces it | `cli.repo.webhook/update` |  |
| `DELETE /repos/{owner}/{repo}/hooks/{id}` | a repository webhook is removed (apply -d) | `cli.repo.webhook/remove-hook` |  |
| `PUT /repos/{owner}/{repo}/actions/secrets/{name}` | a repository secret is added, or --update-secrets forces it | `cli.environment.secrets/update`, `cli.secrets/create`, `cli.secrets/update` |  |
| `DELETE /repos/{owner}/{repo}/actions/secrets/{name}` | a repository secret is removed (apply -d) | `cli.environment.secrets/remove` |  |
| `PUT /repos/{owner}/{repo}/dependabot/secrets/{name}` | a repository Dependabot secret is added or forced (#890) | `cli.secrets.dependabot-codespaces/create` |  |
| `DELETE /repos/{owner}/{repo}/dependabot/secrets/{name}` | a repository Dependabot secret is removed (apply -d) | `cli.secrets.dependabot-codespaces/remove` |  |
| `PUT /repos/{owner}/{repo}/codespaces/secrets/{name}` | a repository Codespaces secret is added or forced (#890) | `cli.secrets.dependabot-codespaces/create` |  |
| `DELETE /repos/{owner}/{repo}/codespaces/secrets/{name}` | a repository Codespaces secret is removed (apply -d) | `cli.secrets.dependabot-codespaces/remove` |  |
| `POST /repos/{owner}/{repo}/actions/variables` | a repository variable is added | `cli.secrets/create` |  |
| `PATCH /repos/{owner}/{repo}/actions/variables/{name}` | a repository variable's value changes | `cli.environment.secrets/update`, `cli.secrets/update` |  |
| `DELETE /repos/{owner}/{repo}/actions/variables/{name}` | a repository variable is removed (apply -d) | `cli.environment.secrets/remove` |  |
| `PUT /repos/{owner}/{repo}/environments/{name}` | an environment is added or changes (wait timer, reviewers, deployment branch policy type) | `cli.environment.secrets/create`, `cli.environment/create`, `cli.environment/update` |  |
| `DELETE /repos/{owner}/{repo}/environments/{name}` | an environment is removed (apply -d) | `cli.repo.pages/disabled` |  |
| `POST /repos/{owner}/{repo}/environments/{name}/deployment-branch-policies` | a branch policy is added to an environment (deployment_branch_policy 'selected') | `cli.environment/create` |  |
| `DELETE /repos/{owner}/{repo}/environments/{name}/deployment-branch-policies/{id}` | a branch policy is removed from an environment | `cli.environment/update` |  |
| `PUT /repos/{owner}/{repo}/environments/{name}/secrets/{name}` | an environment secret is added, or --update-secrets forces it | `cli.environment.secrets/create`, `cli.environment.secrets/update` |  |
| `DELETE /repos/{owner}/{repo}/environments/{name}/secrets/{name}` | an environment secret is removed (apply -d) | `cli.environment.secrets/remove` |  |
| `POST /repos/{owner}/{repo}/environments/{name}/variables` | an environment variable is added | `cli.environment.secrets/create` |  |
| `PATCH /repos/{owner}/{repo}/environments/{name}/variables/{name}` | an environment variable's value changes | `cli.environment.secrets/update` |  |
| `DELETE /repos/{owner}/{repo}/environments/{name}/variables/{name}` | an environment variable is removed (apply -d) | `cli.environment.secrets/remove` |  |
| `POST /repos/{owner}/{repo}/rulesets` | a repository ruleset is added | `cli.ruleset.public/create` |  |
| `PUT /repos/{owner}/{repo}/rulesets/{id}` | a repository ruleset changes | `cli.ruleset.public/update` |  |
| `DELETE /repos/{owner}/{repo}/rulesets/{id}` | a repository ruleset is removed (apply -d) | `cli.ruleset.public/remove-ruleset` |  |
| `mutation createBranchProtectionRule` | a branch protection rule is added | `cli.bpr.public/create` |  |
| `mutation updateBranchProtectionRule` | a branch protection rule changes | `cli.bpr.public/update` |  |
| `mutation deleteBranchProtectionRule` | a branch protection rule is removed (apply -d) | `cli.bpr.public/remove-rule` |  |
| `POST /repos/{owner}/{repo}/actions/workflows/{name}/dispatches` | the webapp dispatches a workflow (blueprints, policies) | _webapp only_ |  |
| `mutation minimizeComment` | the webapp minimizes its outdated pull request comments | _webapp only_ |  |
