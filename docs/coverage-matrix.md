# Coverage matrix

<!-- Generated from scenarios/coverage.yaml by tests/unit/test_coverage_matrix.py: do not edit by hand. -->

> Generated from [`scenarios/coverage.yaml`](../scenarios/coverage.yaml) (`.venv/bin/python tests/unit/test_coverage_matrix.py --write`).
> Edit the YAML, then regenerate: `tests/unit/test_coverage_matrix.py` fails when this file is stale.

otterdog feature coverage of the e2e battery

Inventory of otterdog main @fa01483 (v1.8.0 and 32 commits; release:latest is v1.8.0), first built at main 9bdeb75 (after v1.6.1), then moved to main d9dac78 (after v1.7.1): every CLI command and its flags, every property of the configuration model grouped by feature, validation rules, diff semantics, the webapp (webhook events, comment commands, tasks, auto-merge, apply, blueprints, policies, /api and /internal), the webhook receiver contract and notable CHANGELOG fixes, mapped to the existing scenarios and tests of this repository. Gaps and partial coverage carry the outline of the missing test.

**396 features** in 27 areas: 319 covered, 58 partial, 19 gaps; covered 81%, weighted 88% (a partial feature counts half). *Offline-verified* counts the covered or partial features with at least one covering item in the offline tier; *live-verified* those with a recorded green live run of their covering items (`verified_on`: target, SUT, run id, date); *unverified* the others: their coverage is implemented but has never run, so it is a claim, not evidence. A covered feature needs at least one covering item that runs strictly on the default SUT (not only known-bug xfails or scenarios skipped by `fixed_in`).

## Summary by area

| Area | Features | Covered | Partial | Gap | Covered % | Weighted % | Offline-verified | Live-verified | Unverified |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| [CLI commands and global options](#cli) | 63 | 56 | 7 | 0 | 89% | 94% | 36 | 39 | 3 |
| [otterdog.json, base template and credentials](#config) | 27 | 15 | 6 | 6 | 56% | 67% | 17 | 9 | 0 |
| [Validation rules](#validation) | 38 | 37 | 1 | 0 | 97% | 99% | 37 | 6 | 0 |
| [Diff engine and plan semantics](#plan-semantics) | 18 | 17 | 1 | 0 | 94% | 97% | 16 | 9 | 0 |
| [Organization settings](#org-settings) | 14 | 9 | 5 | 0 | 64% | 82% | 3 | 10 | 3 |
| [Organization Actions settings](#org-workflows) | 7 | 4 | 3 | 0 | 57% | 79% | 2 | 4 | 1 |
| [Organization custom properties](#custom-properties) | 6 | 6 | 0 | 0 | 100% | 100% | 2 | 4 | 1 |
| [Custom organization roles](#org-roles) | 2 | 2 | 0 | 0 | 100% | 100% | 1 | 1 | 0 |
| [Code security configurations (organization) and their repositories](#code-security) | 3 | 0 | 3 | 0 | 0% | 50% | 3 | 0 | 0 |
| [Teams](#teams) | 7 | 5 | 0 | 2 | 71% | 71% | 0 | 5 | 0 |
| [Managed organization and repository webhooks](#webhooks) | 8 | 6 | 2 | 0 | 75% | 88% | 4 | 6 | 2 |
| [Secrets and variables (organization, repository, environment)](#secrets-variables) | 12 | 10 | 2 | 0 | 83% | 92% | 6 | 12 | 0 |
| [Repositories](#repositories) | 18 | 16 | 2 | 0 | 89% | 94% | 6 | 15 | 1 |
| [Repository Actions settings](#repo-workflows) | 7 | 5 | 2 | 0 | 71% | 86% | 2 | 6 | 1 |
| [Branch protection rules](#branch-protection) | 10 | 10 | 0 | 0 | 100% | 100% | 2 | 10 | 0 |
| [Repository and organization rulesets](#rulesets) | 19 | 11 | 8 | 0 | 58% | 79% | 11 | 12 | 0 |
| [Deployment environments](#environments) | 4 | 4 | 0 | 0 | 100% | 100% | 3 | 4 | 0 |
| [Webhook receiver contract](#receiver) | 8 | 8 | 0 | 0 | 100% | 100% | 8 | 2 | 0 |
| [Webapp webhook event routing](#webapp-events) | 10 | 9 | 1 | 0 | 90% | 95% | 1 | 10 | 0 |
| [Pull request comment commands](#webapp-commands) | 9 | 8 | 1 | 0 | 89% | 94% | 0 | 9 | 0 |
| [Pull request validation, sync check and apply](#webapp-pr) | 16 | 14 | 2 | 0 | 88% | 94% | 0 | 14 | 2 |
| [Auto-merge eligibility and merge](#webapp-automerge) | 4 | 4 | 0 | 0 | 100% | 100% | 0 | 4 | 0 |
| [Webapp boot, init, API and pages](#webapp-runtime) | 22 | 16 | 3 | 3 | 73% | 80% | 11 | 11 | 0 |
| [Blueprints](#blueprints) | 8 | 6 | 2 | 0 | 75% | 88% | 0 | 7 | 1 |
| [Policies](#policies) | 3 | 3 | 0 | 0 | 100% | 100% | 0 | 2 | 1 |
| [CHANGELOG fixes (regression guards)](#regressions) | 48 | 34 | 6 | 8 | 71% | 77% | 10 | 33 | 0 |
| [Unmerged otterdog changes (pull requests and local branches)](#pending) | 5 | 4 | 1 | 0 | 80% | 90% | 0 | 1 | 4 |
| **Total** | 396 | 319 | 58 | 19 | 81% | 88% | 181 | 245 | 20 |

## Summary by tier

| Tier | Features | Covered | Partial | Gap | Covered % | Weighted % | Offline-verified | Live-verified | Unverified |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `offline` | 123 | 111 | 11 | 1 | 90% | 95% | 122 | 25 | 0 |
| `cli` | 162 | 127 | 27 | 8 | 78% | 87% | 52 | 133 | 8 |
| `webhooks` | 4 | 3 | 1 | 0 | 75% | 88% | 2 | 3 | 1 |
| `webapp` | 88 | 69 | 13 | 6 | 78% | 86% | 3 | 73 | 8 |
| `web_ui` | 14 | 7 | 5 | 2 | 50% | 68% | 1 | 9 | 3 |
| `enterprise` | 5 | 2 | 1 | 2 | 40% | 50% | 1 | 2 | 0 |

## Summary by priority

| Priority | Features | Covered | Partial | Gap | Covered % | Weighted % | Offline-verified | Live-verified | Unverified |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| P0 | 62 | 61 | 1 | 0 | 98% | 99% | 32 | 52 | 1 |
| P1 | 152 | 125 | 24 | 3 | 82% | 90% | 70 | 105 | 3 |
| P2 | 182 | 133 | 33 | 16 | 73% | 82% | 79 | 88 | 16 |

Tiers:

- `offline`: no GitHub: validate, local-plan, show --local with the vendored template (tests/offline, scenarios/offline); the webapp container with dummy credentials
- `cli`: live CLI against the test organization: plan -n, apply -f -n, oracle checks, converge (tests/cli, scenarios/cli, regressions included)
- `webhooks`: otterdog-managed hooks and real App deliveries through the relay (tests/webhooks)
- `webapp`: the webapp under test in docker compose, GitHub App, config-repository pull requests (tests/webapp)
- `web_ui`: otterdog's own web-UI login (bot username, password, TOTP, Playwright Firefox): tests/web_ui, gated by --e2e-allow-web-ui and the admin web credentials (trusted SUTs only)
- `enterprise`: a GitHub Enterprise Cloud target (tests/enterprise, scenarios/enterprise)

Operations:

- `add`: create the object or setting (plan '+ add', apply ADD)
- `modify`: change an existing object (plan '\~', apply CHANGE)
- `remove`: delete it (plan '- remove', apply -d)
- `rename`: rename or re-key through aliases
- `archive`: behaviour with archived repositories
- `converge`: a plan after the apply is a no-op (the live read-back maps to the configuration)
- `import`: import round trip (live -&gt; jsonnet -&gt; no-op plan)
- `validate`: validation errors, warnings or infos
- `plan`: plan / local-plan rendering and counters
- `coerce`: values ignored or rewritten because of other settings (UNSET semantics)
- `forced-update`: '!' updates forced by --update-secrets / --update-webhooks
- `filter`: repository filter (-r) or update filter (--update-filter)
- `run`: command execution and its output
- `exit-code`: process exit status semantics
- `prompt`: interactive approval on stdin
- `error`: error handling and error messages
- `config`: configuration loading
- `event`: webhook event routing
- `task`: background task behaviour
- `comment`: bot comment content and minimization
- `status`: commit status contexts and descriptions
- `permission`: authorization and eligibility checks
- `api`: HTTP endpoint contract
- `state`: webapp database state
- `security`: signatures, import confinement, secret handling

## Gaps

19 features have no test yet, by priority; the outline of the missing test is in the details of their area.

| Id | Feature | Area | Tier | Plan | Prio |
|---|---|---|---|---|---|
| `config.hook.validate-team` | template hook validate-team.py (per team at validation) | [otterdog.json, base template and credentials](#config) | cli | free | P1 |
| `config.hook.post-add-objects` | template hook post-add-objects-hook.py: runs once after an apply that added objects (CLI apply/local-apply and the webapp apply comment) | [otterdog.json, base template and credentials](#config) | cli | free | P1 |
| `regression.905-excluded-teams-local-operations` | #905 (62ac2a4, in v1.8.0): local-plan and local-apply (the webapp's validation and apply) drop from the base configuration the teams whose slug matches defaults.github.exclude_teams and that the configuration no longer declares, so removing such a team plans no deletion; a local apply finds the slug of a removed team from its name; updating or deleting a team missing on GitHub fails with 'failed to find team with name ...' | [CHANGELOG fixes (regression guards)](#regressions) | cli | free | P1 |
| `config.hook.subdirectory-template` | templates in a subdirectory are copied without the repo-root hook scripts, so hooks never run (examples/template is such a case) | [otterdog.json, base template and credentials](#config) | cli | free | P2 |
| `config.exclude-environments` | defaults.github.exclude_environments (regexes, re.match, case-sensitive): matching live environments that the configuration does not declare are ignored by plan, apply -d, import and show-live (#887) | [otterdog.json, base template and credentials](#config) | cli | free | P2 |
| `config.exclude-teams.repository-permissions` | repository permissions of excluded teams (exclude_teams) are ignored unless the repository declares the team (#879) | [otterdog.json, base template and credentials](#config) | cli | free | P2 |
| `config.web-timeout` | OTTERDOG_WEB_TIMEOUT (milliseconds, default 10000): timeout of otterdog's web-UI pages (#880) (UI only) | [otterdog.json, base template and credentials](#config) | web_ui | free | P2 |
| `teams.team-sync` | team_sync (orgs.newTeamSync: id, name, description): identity provider groups connected to a team through team synchronization, identified by their id; at most 5 groups, no duplicate id, exclusive with external_group_id, and no members for a team managed by an identity provider (#911, eb8dca5, in v1.8.0) | [Teams](#teams) | enterprise | enterprise | P2 |
| `teams.external-group` | external_group_id: the external group of Enterprise Managed Users a team is connected to (GET/PATCH /orgs/{org}/teams/{team_slug}/external-groups), sent as an integer and kept out of the team payload (#911, eb8dca5, in v1.8.0) | [Teams](#teams) | enterprise | enterprise | P2 |
| `webapp-runtime.oauth-login` | GitHub OAuth login: /login -&gt; /github (authorize) -&gt; /github/authorized (user and project memberships stored in the session) -&gt; /logout | [Webapp boot, init, API and pages](#webapp-runtime) | web_ui | free | P2 |
| `webapp-runtime.playground-pages` | GET /playground (instance or ?template=example template), /admin/template-impact and its /configurations JSON (projects using the default base template); the project playground is a CodeMirror page fed by a JSON script (#878) | [Webapp boot, init, API and pages](#webapp-runtime) | webapp | free | P2 |
| `webapp-runtime.installation-refresh-bound` | installation refresh tasks run behind MAX_CONCURRENT_INSTALLATION_TASKS per worker (default 10, checked at boot like the playground limits); /internal/init refreshes every installation once; HYPERCORN_WORKERS sets the workers (#843) | [Webapp boot, init, API and pages](#webapp-runtime) | webapp | free | P2 |
| `regression.685-pin-invalid-workflow` | #685 (v1.4.0): PinWorkflowTask skips workflow files with invalid YAML | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P2 |
| `regression.854-885-cost-related` | #854 (0229baa) private repository creation and conversion are cost-related; #885 (529ca89) only a max_cache_size_gb change of the workflow settings is cost-related (the webapp's cost warning and auto-merge exclusion) | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P2 |
| `regression.960-retry-idempotent-requests` | #960 (e35360d, after v1.8.0): the REST requester sends a request again on a 5xx or a lost response only for GET, HEAD, OPTIONS, PUT and DELETE; POST and PATCH only when no connection could be established | [CHANGELOG fixes (regression guards)](#regressions) | cli | free | P2 |
| `regression.962-immutable-releases-rate-limit` | #962 (c853f83, after v1.8.0): a rate-limited 403 while reading the immutable release settings of an organization or a repository fails the read instead of leaving the settings unset (plan and apply skipped them silently) | [CHANGELOG fixes (regression guards)](#regressions) | cli | free | P2 |
| `regression.964-delete-branch-refused` | #964 (6566348, after v1.8.0): the webapp's DeleteBranchTask takes only a 404 or the 422 of an already deleted reference for a missing branch; another 422 (a deletion GitHub refuses) fails the task instead of completing it | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P2 |
| `regression.967-playground-find` | #967 (6f3ab92, after v1.8.0): Ctrl+F (Cmd+F) in the editors of the dashboard playground opens CodeMirror's search panel, which finds text outside the rendered lines | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P2 |
| `regression.907-custom-property-editable-default` | #907 (c7a5818, in v1.8.0): the standard template defaults values_editable_by of newCustomProperty to 'org_actors' (null before), the value GitHub reports when none was specified | [CHANGELOG fixes (regression guards)](#regressions) | offline | free | P2 |

## Partially covered features

58 features are only partly asserted, by priority; the outline of the missing test is in the details of their area.

| Id | Feature | Area | Tier | Plan | Prio | Covered by |
|---|---|---|---|---|---|---|
| `org-settings.profile` | organization profile: name, description (&lt;= 160), email, billing_email, company, location, twitter_username, blog (REST PATCH /orgs/{org}) | [Organization settings](#org-settings) | cli | free | P0 | `tests/cli/test_import.py::test_import_plans_no_change`, `cli.org.profile` |
| `cli.apply.validation-errors` | apply with validation errors prints 'Planning aborted due to validation errors.' and exits with the error count (#923, 1.8.0; before: 'No changes required.' and exit 0, KB-001) | [CLI commands and global options](#cli) | cli | free | P1 | `tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors`, `tests/offline/test_cli_local_apply.py::test_validation_errors_fail_the_local_apply` |
| `config.secret-references` | secret values: 'pass:', 'bitwarden:', 'vault:' references resolved at apply; other values used literally with a validation warning; '\*\*\*\*\*\*\*\*' = dummy | [otterdog.json, base template and credentials](#config) | cli | free | P1 | `cli.secrets`, `O-VAL-OK`, `O-VAL-SECRETS`, `cli.org.secret` |
| `config.secret-access-policy` | secret access policy of otterdog.json (#923): defaults.secrets {mode, allowed_references} and organizations[].secrets restrict the provider references of an organization | [otterdog.json, base template and credentials](#config) | offline | free | P1 | `O-VAL-SECRET-ACCESS-POLICY` |
| `validation.code-security` | code security configuration validation: products required by a feature, free plan products of the same status, labeled runner without label, bypass reviewers (team, role, mode), settings without effect, defaults while default_code_security_configurations_disabled, two defaults for one visibility (#892) | [Validation rules](#validation) | offline | free | P1 | `O-VAL-CODE-SECURITY` |
| `plan-semantics.wildcard-keys` | a key ending with '\*' (e.g. a webhook url hiding a token, #84) matches the live object whose key starts with the prefix: no remove + add, the live key is kept | [Diff engine and plan semantics](#plan-semantics) | offline | free | P1 | `O-LPLAN-WILDCARD`, `tests/webapp/test_merge_apply.py::test_team_and_wildcard_webhook_are_applied` |
| `org-settings.web-ui.packages` | web-UI package creation: packages_containers_public, packages_containers_internal (internal: Enterprise Cloud only) (UI only) | [Organization settings](#org-settings) | web_ui | free | P1 | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip` |
| `org-settings.web-ui.discussions` | web-UI org discussions: has_discussions with discussion_source_repository '&lt;org&gt;/&lt;repo&gt;' (17 Eclipse orgs) (UI only) | [Organization settings](#org-settings) | web_ui | free | P1 | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip` |
| `org-workflows.actions-policies` | organization actions_policies (orgs.newOrgActionsPolicy, GitHub's workflow execution protections): rules allowed_actors and allowed_events (null = not required), workflow and repository-name targeting, enforcement; add, change (PUT of the whole policy), delete with -d, by name (#947) | [Organization Actions settings](#org-workflows) | cli | free | P1 | `O-VAL-ACTIONS-POLICIES`, `O-LPLAN-ACTIONS-POLICIES`, `cli.workflows.org-actions-policies` |
| `code-security.configuration.lifecycle` | organization code_security_configurations (orgs.newOrgCodeSecurityConfiguration): add, change (one PATCH, default_for_new_repos through PUT .../defaults), delete with -d, by name; foreign organization configurations are deletions (#892) | [Code security configurations (organization) and their repositories](#code-security) | cli | free | P1 | `O-LPLAN-CODE-SECURITY`, `O-VAL-CODE-SECURITY`, `cli.code-security.configuration` |
| `code-security.repository-attachment` | repository code_security_configuration: the configuration attached to the repository (after creation; null keeps the attached one); the security settings it controls are not managed on the repository | [Code security configurations (organization) and their repositories](#code-security) | cli | free | P1 | `O-LPLAN-CODE-SECURITY`, `O-VAL-CODE-SECURITY`, `cli.code-security.configuration` |
| `secrets-variables.org-dependabot-codespaces-secrets` | organization dependabot_secrets and codespaces_secrets (orgs.newOrgDependabotSecret, newOrgCodespacesSecret): like Actions secrets (visibility public == 'all' \| private \| selected, names, values), private allowed on every plan (#890) | [Secrets and variables (organization, repository, environment)](#secrets-variables) | cli | free | P1 | `O-VAL-DEPENDABOT-CODESPACES-SECRETS`, `O-LPLAN-DEPENDABOT-CODESPACES-SECRETS`, `cli.secrets.dependabot-codespaces` |
| `secrets-variables.repo-dependabot-codespaces-secrets` | repository dependabot_secrets and codespaces_secrets (orgs.newRepoDependabotSecret, newRepoCodespacesSecret): name and value like repository Actions secrets (#890) | [Secrets and variables (organization, repository, environment)](#secrets-variables) | cli | free | P1 | `O-VAL-DEPENDABOT-CODESPACES-SECRETS`, `O-LPLAN-DEPENDABOT-CODESPACES-SECRETS`, `cli.secrets.dependabot-codespaces` |
| `repositories.pages` | GitHub Pages: gh_pages_build_type disabled \| legacy (source branch/path) \| workflow, gh_pages_visibility (enterprise) | [Repositories](#repositories) | cli | free | P1 | `cli.repo.pages` |
| `repo-workflows.actions-policies` | repository actions_policies (orgs.newRepoActionsPolicy): add (also with a new repository), change, delete with -d, by name; left as they are on an archived repository, applied before the archiving patch of the same apply (#947) | [Repository Actions settings](#repo-workflows) | cli | free | P1 | `O-VAL-ACTIONS-POLICIES`, `O-LPLAN-ACTIONS-POLICIES`, `cli.workflows.repo-actions-policies` |
| `rulesets.targets` | ruleset target branch \| tag \| push (tag protection rulesets with include_refs ['\~ALL'] are used by eclipse-csi) | [Repository and organization rulesets](#rulesets) | cli | free | P1 | `cli.ruleset.public`, `cli.ruleset.rules` |
| `webapp-events.review` | pull_request_review submitted / edited / dismissed: UpdatePullRequestTask with the review (approvals recomputed, auto-merge offered when eligible) | [Webapp webhook event routing](#webapp-events) | webapp | free | P1 | `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_merge_apply.py::test_dismissed_approval_blocks_the_merge` |
| `webapp-commands.team-info` | /otterdog team-info (and on PR open): the author's org membership and teams; sets author_can_auto_merge (bot authors skipped) | [Pull request comment commands](#webapp-commands) | webapp | free | P1 | `tests/webapp/test_commands.py::test_team_info_command`, `tests/webapp/test_pr_validation.py::test_draft_pr_lifecycle` |
| `webapp-pr.validation-failure` | a crashing validation task: status failure 'otterdog validation failed, please contact an admin'; evaluation exceptions give the friendly comment 'Validation failed while evaluating the configuration. ...' | [Pull request validation, sync check and apply](#webapp-pr) | webapp | free | P1 | `tests/webapp/test_pr_validation.py::test_evaluation_error_gets_a_friendly_comment` |
| `webapp-pr.import-confinement` | jsonnet imports are confined to the org directory during validation, sync check and apply (an import of '../../x' fails) | [Pull request validation, sync check and apply](#webapp-pr) | webapp | free | P1 | `tests/webapp/test_pr_validation.py::test_imports_are_confined_to_the_org_directory` |
| `regression.712-fail-fast-configuration` | #712 (v1.5.0) and v1.3.2: the webapp refuses to start when required settings are missing or empty (GITHUB_WEBHOOK_SECRET); values are stripped (#677) | [CHANGELOG fixes (regression guards)](#regressions) | offline | free | P1 | `tests/offline/test_webapp_runtime.py::test_required_setting_is_refused_at_boot`, `tests/offline/test_webapp_runtime.py::test_refused_boot_exits_non_zero` |
| `regression.895-merge-rechecks-approvals` | #895 (2591db4, in v1.8.0): /otterdog merge checks the reviews of the pull request again when neither its author nor the stored approvals allow the merge, and stores the result, so an approval whose review event was missed or failed no longer blocks the merge; reviews of deleted accounts and unresolved teams of a partial GraphQL answer are ignored | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P1 | `tests/webapp/test_merge_apply.py::test_dismissed_approval_blocks_the_merge` |
| `regression.904-merge-base-from-branch-activity` | #904 (e4515eb, in v1.8.0): the base of a squash- or rebase-merged pull request is the head of its base branch before the merge, read from the branch's pr_merge activity (looked up again for about 31 s), not from the commits GitHub associates with the pull request some time after the merge; a merge not recorded as a pr_merge activity (merge queue) fails the apply | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P1 | `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_merge_applies_config` |
| `regression.906-installation-before-config` | #906 (b79c7b9, in v1.8.0): a push to the default branch of the otterdog config repository is handled first, also when delivered through an App installation (otterdog.json, global policies and blueprints, then the installations are reloaded: KB-015); the App installed for an org not known yet reloads otterdog.json and creates, installs and fetches that org's installation when it is defined there, else logs a warning | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P1 | `tests/webapp/test_blueprints.py::test_global_definitions_reload_on_configs_push`, `tests/webapp/test_installation_events.py::test_installation_events_update_the_record` |
| `regression.914-codespaces-secrets-unavailable` | #914 (65175c3, in v1.8.0): a 404 of the organization or repository Codespaces secrets endpoints (Codespaces not available, e.g. Free organizations) skips these secrets with one warning per organization and scope instead of failing every operation; a configuration declaring such secrets fails with '... declares &lt;scope&gt; secrets which cannot be managed' | [CHANGELOG fixes (regression guards)](#regressions) | cli | free | P1 | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset` |
| `cli.no-web-ui-default` | defaults.github.no_web_ui of otterdog.json is the default of -n/--no-web-ui (show-live, import, plan, check-status, apply, local-apply); --web-ui overrides it (#913) | [CLI commands and global options](#cli) | offline | free | P2 | `tests/offline/test_cli_no_web_ui.py::test_no_web_ui_defaults_to_the_configuration`, `tests/offline/test_cli_no_web_ui.py::test_every_command_offers_both_flags` |
| `cli.install-app` | install-app -a SLUG: installs an App through the web UI ('app already installed, skipping.' / 'app installed.') (UI only) | [CLI commands and global options](#cli) | web_ui | free | P2 | `tests/web_ui/test_web_commands.py::test_install_and_uninstall_app` |
| `cli.uninstall-app` | uninstall-app -a SLUG: uninstalls an App through the web UI ('uninstalled app.') (UI only) | [CLI commands and global options](#cli) | web_ui | free | P2 | `tests/web_ui/test_web_commands.py::test_install_and_uninstall_app` |
| `cli.review-permissions` | review-permissions [-a SLUG] [-g] [-f]: lists requested App permission updates and grants them through the web UI (UI only) | [CLI commands and global options](#cli) | web_ui | free | P2 | `tests/web_ui/test_web_commands.py::test_review_permissions_lists_requests` |
| `cli.local-apply.code-security-metadata` | local-apply reads the code security configurations of the organization and the configuration of each repository from GitHub before its plan whenever the template defines them (#892): no offline local-apply any more | [CLI commands and global options](#cli) | offline | free | P2 | `tests/offline/test_cli_local_apply.py::test_local_apply_reads_code_security_configurations_from_github` |
| `cli.global.stats` | --stats / OTTERDOG_STATS (GitHub API usage report on stderr) and --stats-file / OTTERDOG_STATS_FILE (JSON) of every StdCommand; -v logs one 'github api usage for organization' INFO line per organization (#881) | [CLI commands and global options](#cli) | offline | free | P2 | `tests/offline/test_cli_exit_codes.py::test_verbosity_levels` |
| `config.organization-entries` | organizations[]: name and github_id required, per-org config_repo/base_template/credentials, approval_teams/admin_teams as string or list | [otterdog.json, base template and credentials](#config) | offline | free | P2 | `tests/offline/test_cli_basics.py::test_list_projects_lists_the_offline_organization`, `tests/offline/test_config_loading.py::test_invalid_organization_entry`, `tests/offline/test_config_loading.py::test_organization_entry_variants` |
| `config.local-base-template` | base_template as a local path (#917): relative to otterdog.json, linked as vendor/&lt;directory name&gt; on every run (--local included); missing file and a template directory holding the organization are load errors | [otterdog.json, base template and credentials](#config) | offline | free | P2 | `O-VAL-LOCAL-BASE-TEMPLATE` |
| `config.template-feature-gating` | the template drives what is managed: missing constructors skip a resource type, only template org-settings keys are fetched, hidden '::' fields are unmanaged | [otterdog.json, base template and credentials](#config) | cli | free | P2 | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `tests/cli/test_org_config.py::test_hidden_fields_are_unmanaged` |
| `config.credentials.other-providers` | plain, pass, bitwarden and vault providers; 'no credential provider configured' / "unsupported credential provider '&lt;x&gt;'" | [otterdog.json, base template and credentials](#config) | offline | free | P2 | `tests/offline/test_config_credentials.py::test_plain_and_default_providers`, `tests/offline/test_config_credentials.py::test_pass_provider_with_a_stub_store`, `tests/offline/test_config_credentials.py::test_pass_store_dir_from_the_defaults_override`, `tests/offline/test_config_credentials.py::test_bitwarden_provider_with_a_stub_vault`, `tests/offline/test_config_credentials.py::test_credential_lookups_never_reach_a_shell` |
| `org-settings.pages-creation` | members_can_create_public_pages / members_can_create_private_pages (private: enterprise plan only) | [Organization settings](#org-settings) | cli | free | P2 | `cli.org.member-privileges` |
| `org-settings.immutable-releases` | immutable_releases_enforced_repositories (all \| none \| selected) and immutable_releases_selected_repositories (compared without case, aliases resolved, duplicates dropped; only with 'selected') (#665) | [Organization settings](#org-settings) | cli | free | P2 | `O-VAL-IMMUTABLE-RELEASES` |
| `org-workflows.sha-pinning` | org sha_pinning_required (actions must be pinned to a full-length commit SHA; #946, 1.9.0) | [Organization Actions settings](#org-workflows) | cli | free | P2 | `O-VAL-ORG-WORKFLOWS`, `O-LPLAN-IGNORED-FIELDS` |
| `org-workflows.cache-size` | org max_cache_size_gb (Actions cache storage limit; changes are cost-related in the webapp) | [Organization Actions settings](#org-workflows) | cli | free | P2 | `cli.org.cache-size` |
| `code-security.configuration.settings` | the settings of a code security configuration: GitHub Advanced Security products, dependency graph, Dependabot, code scanning default setup (runner), secret scanning (delegated bypass reviewers), private vulnerability reporting; null = not managed | [Code security configurations (organization) and their repositories](#code-security) | cli | free | P2 | `O-VAL-CODE-SECURITY`, `O-LPLAN-CODE-SECURITY`, `cli.code-security.configuration` |
| `webhooks.org.aliases` | organization webhook aliases (matching by a previous url): the url change itself is never applied (url excluded from diffs) | [Managed organization and repository webhooks](#webhooks) | webhooks | free | P2 | `tests/webhooks/test_managed_org_hook.py::test_org_webhook_url_change_through_aliases` |
| `webhooks.repo.aliases` | repository webhook url change through aliases (documented in docs/userguide/renaming.md) | [Managed organization and repository webhooks](#webhooks) | cli | free | P2 | `cli.kb.webhook-url-alias` |
| `repositories.pages-custom-domain` | gh_pages_cname (custom domain, null = github.io) and gh_pages_https_enforced (only with a custom domain) (#858) | [Repositories](#repositories) | cli | free | P2 | `O-VAL-PAGES-CNAME` |
| `repo-workflows.cache-size` | repository max_cache_size_gb (cache storage limit; cost-related above defaults.cost_policy.free_max_cache_size_gb) | [Repository Actions settings](#repo-workflows) | cli | free | P2 | `cli.repo.cache-limit` |
| `rulesets.code-quality` | required_code_quality (orgs.newCodeQuality: severity errors \| warnings \| notes \| all): the code_quality rule; an unknown severity is a load error of the JSON schema (#900, daf9237, in v1.8.0) | [Repository and organization rulesets](#rulesets) | cli | enterprise | P2 | `O-VAL-RULESET-CODE-ANALYSIS` |
| `rulesets.code-coverage` | required_code_coverage (orgs.newCodeCoverage: minimum_coverage, max_coverage_drop in [0, 100]): the code_coverage rule; out-of-range values are refused and a coverage without threshold is a warning (#900, daf9237, in v1.8.0) | [Repository and organization rulesets](#rulesets) | cli | enterprise | P2 | `O-VAL-RULESET-CODE-ANALYSIS` |
| `rulesets.license-compliance` | requires_license_compliance_scanning: the license_compliance rule, results of license compliance scanning required before merging (#900, daf9237, in v1.8.0) | [Repository and organization rulesets](#rulesets) | cli | enterprise | P2 | `O-VAL-RULESET-CODE-ANALYSIS` |
| `rulesets.patterns` | pattern rules (orgs.newPattern: name, negate, operator starts_with \| ends_with \| contains \| regex, pattern) of commit_message_pattern, commit_author_email_pattern, committer_email_pattern, branch_name_pattern and tag_name_pattern; a missing or empty pattern is refused, the branch and tag name patterns only on a ruleset of their target (#900, daf9237, in v1.8.0) | [Repository and organization rulesets](#rulesets) | cli | enterprise | P2 | `O-VAL-RULESET-PATTERNS` |
| `rulesets.push-rules` | push rules of a ruleset with target 'push': restricted_file_paths (with restricted_file_paths_exceptions), max_file_path_length, restricted_file_extensions, max_file_size (with max_file_size_exceptions); limits of GitHub (size in [0, 100] MB, path length in [0, 32767], at most 200 entries of 200 characters), refused on a branch or tag ruleset (#900, daf9237, in v1.8.0) | [Repository and organization rulesets](#rulesets) | cli | team | P2 | `O-VAL-RULESET-PUSH-RULES` |
| `rulesets.required-workflows` | required_workflows (orgs.newWorkflows: do_not_enforce_on_create, workflows written 'owner/repository:path[@ref][#sha]'): the workflows rule of an organization ruleset, the repository resolved to its id when otterdog talks to GitHub; refused in a repository ruleset (#900, daf9237, in v1.8.0) | [Repository and organization rulesets](#rulesets) | enterprise | enterprise | P2 | `O-VAL-RULESET-REQUIRED-WORKFLOWS` |
| `rulesets.pull-request.allowed-merge-methods` | required_pull_request allowed_merge_methods (merge \| squash \| rebase, at least one, unique; template default all three) (#777) | [Repository and organization rulesets](#rulesets) | cli | free | P2 | `O-VAL-RULESETS`, `O-VAL-ORG-RULESETS`, `O-VAL-RULESET-NESTED` |
| `webapp-runtime.api-statistics` | GET /api/pullrequests/statistics/progress?interval=day\|week\|month&range=7d\|14d\|30d\|90d\|6m\|12m\|all[&org=]: polled background job; 400 {'error': "unsupported interval '&lt;x&gt;'"} | [Webapp boot, init, API and pages](#webapp-runtime) | offline | free | P2 | `tests/offline/test_webapp_contract.py::test_statistics_parameters` |
| `webapp-runtime.playground-validation` | POST /playground/validate[?template=example] and /projects/&lt;project&gt;/playground/validate: the evaluated organization configuration is validated with otterdog; JSON rejections 400 (no JSON object), 413 (PLAYGROUND_VALIDATION_MAX_SIZE), 404 (unknown project), 503 (PLAYGROUND_MAX_CONCURRENT_VALIDATIONS) (#891) | [Webapp boot, init, API and pages](#webapp-runtime) | webapp | free | P2 | `tests/offline/test_webapp_contract.py::test_playground_validation_refuses_malformed_requests` |
| `webapp-runtime.dashboard-theme` | #912 (941d284, in v1.8.0): the dashboard takes the documentation's theme (Eclipse colors, Inter bundled with the assets instead of Google Fonts, a dark mode following the system until the header toggle picks one); the projects pages show a card per organization (facts, protections, activity, filters and orders kept in the address); FetchConfigTask reads the configuration at the latest commit changing otterdog/&lt;org&gt;.jsonnet and stores it, shown as 'Configuration changed &lt;age&gt;' linked to that commit | [Webapp boot, init, API and pages](#webapp-runtime) | webapp | free | P2 | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_runtime.py::test_project_and_admin_pages` |
| `blueprints.loading` | blueprint definitions: id, type, name, description, config; global ones de-duplicated by type (KB-076), a global id wins over an org definition with the same id; reloaded on push and init | [Blueprints](#blueprints) | webapp | free | P2 | `tests/webapp/test_blueprints.py::test_blueprint_definitions_are_loaded`, `tests/webapp/test_blueprints.py::test_invalid_yaml_definition_does_not_block_the_others`, `tests/webapp/test_blueprints.py::test_global_definitions_reload_on_configs_push`, `tests/webapp/test_blueprints.py::test_changed_definition_is_stored_by_one_fetch`, `tests/webapp/test_blueprints.py::test_changed_type_keeps_the_check_working`, `tests/webapp/test_blueprints.py::test_changed_definition_is_rechecked_after_another_fetch` |
| `blueprints.scorecard-integration` | scorecard_integration: matching repositories need the OSSF scorecard workflow (PR with workflow_content); results are synced and served by /api/scorecard/results and /scorecard/checks | [Blueprints](#blueprints) | webapp | free | P2 | `tests/webapp/test_blueprints.py::test_scorecard_integration_remediation` |
| `regression.893-playground-custom-templates` | #893 (cb51e70, in v1.8.0): the playground gets every library of the base template's repository, subdirectories included, named by its path from the repository root (vendor/&lt;repo&gt;/&lt;path&gt;, source link &lt;repo&gt;/blob/&lt;ref&gt;/&lt;path&gt;), and the vendored copy keeps the whole subtree of the base template's directory (nested helpers) | [CHANGELOG fixes (regression guards)](#regressions) | webapp | free | P2 | `tests/webapp/test_runtime.py::test_project_and_admin_pages` |
| `pending.automerge-state-refresh` | local feature: auto-merge state recomputed from live teams and approvals (automerge_state.py) for merge, help and update-pull-request | [Unmerged otterdog changes (pull requests and local branches)](#pending) | webapp | free | P2 | `tests/webapp/test_check_merge.py::test_check_merge_refreshes_the_team_membership` |

## New findings

Defects found while building the inventory (not yet in `scenarios/known_bugs.yaml`):

| Id | Finding | Source | Verified | Suggestion |
|---|---|---|---|---|
| `F-01` | Organization variables are never validated: lowercase or GITHUB_ names, invalid visibility and 'private' on a free plan all pass | `otterdog/models/github_organization.py:543-625`, `otterdog/models/organization_variable.py:40-63`, `otterdog/models/variable.py:29-42` | offline: validate --local of newOrgVariable('lower_case') {visibility: 'private'} and newOrgVariable('GITHUB_X') {visibility: 'nonsense', selected_repositories: ['a']} with plan free prints 'Validation succeeded' (exit 0); the same org secret errors | registered as KB-028 (confirmed); offline scenario expecting the 4 errors (non-strict xfail of KB-028 until fixed); docs/capability-matrix.md now states that the variable check is never called |
| `F-02` | An invalid workflows.allowed_actions crashes validation with a KeyError as soon as a repository exists (org 'some' -&gt; "Error: 'some'", repo 'x' -&gt; "Error: 'x'", exit 2) | `otterdog/models/workflow_settings.py:102-121`, `otterdog/models/repo_workflow_settings.py:56-57`, `otterdog/models/repo_workflow_settings.py:102-108` | offline: settings workflows+ {allowed_actions: 'some'} with orgs.newRepo('r1') exits 2 printing "Error: 'some'"; without repositories the documented ERROR "settings has 'workflows.allowed_actions' of value 'some', ..." is printed (exit 1) | registered as KB-029 (confirmed); offline scenario expecting the documented error with a repository present (xfail KB-029) |
| `F-03` | A required custom property without default_value crashes loading ('unexpected None value', exit 2) when any repository exists, before the validation error can be reported | `otterdog/models/repository.py:387-394`, `otterdog/models/github_organization.py:784-786`, `otterdog/models/custom_property.py:84-91` | offline: newCustomProperty('p') {required: true, default_value: null} plus orgs.newRepo('r1') -&gt; 'Error: unexpected None value' exit 2; without a repository: custom_property[name="p"] has 'required' set to 'true', but no property 'default_value' is specified. | registered as KB-030 (confirmed); offline scenario with a repository expecting the validation error (xfail KB-030) |
| `F-04` | Missing required keys of required_pull_request and required_merge_queue are never reported (keys() skips UNSET), unlike required_status_checks since #790 | `otterdog/models/ruleset.py:68-75`, `otterdog/models/ruleset.py:268-275`, `otterdog/models/__init__.py:872-879`, `otterdog/models/ruleset.py:156-164` | offline: a repo ruleset with required_pull_request: {requires_code_owner_review: true} (no required_approving_review_count) and one with required_merge_queue: {merge_method: 'MERGE'} validate ('Validation succeeded'); the apply payload built by RepositoryRuleset.to_provider_data carries UNSET in the pull request rule (json.dumps: TypeError) and raises BendingException for the merge queue, and the apply loop only catches RuntimeError | registered as KB-031 (confirmed); offline scenario expecting "has not set required parameter 'required_pull_request.required_approving_review_count'" (xfail KB-031); a live apply crashes before its request |
| `F-05` | The team_permissions validation error is unreachable: the schema rejects other values first (uncaught jsonschema error, exit 2), including the uppercase READ/WRITE the model accepts | `otterdog/models/repository.py:612-620`, `otterdog/models/repository.py:232-243`, `otterdog/resources/schemas/team-permission.json:1-11` | offline: team_permissions {t: 'super'} -&gt; "Error: 'super' is not one of ['pull', 'triage', 'push', 'maintain', 'admin']" with the schema dump, exit 2; the model message "invalid permission ... allowed values are ('read/pull' \| ...)" never prints | registered as KB-032 (confirmed, low): report the schema error as a validation error or drop the dead check |
| `F-06` | Documented repository warnings and errors never fire because repositories are coerced at load (has_projects, web_commit_signoff_required, has_discussions source, gh_pages_visibility below enterprise) | `otterdog/models/github_organization.py:784-786`, `otterdog/models/repository.py:372-407`, `otterdog/models/repository.py:550-579`, `otterdog/models/repository.py:714-731` | offline: has_projects true with org has_organization_projects false, web_commit_signoff_required false with the template's org default true, has_discussions false on the org discussion source repo and gh_pages_visibility 'private' on free all print 'Validation succeeded' | registered as KB-033 (confirmed, low, docs): validate before coercion or remove the messages; regression scenario documenting the current behaviour |
| `F-07` | validate/plan exit with the number of validation errors, so two errors exit 2 like an uncaught exception | `otterdog/operations/validate.py:61-104`, `otterdog/operations/plan.py:121-137`, `otterdog/cli.py:1097-1099` | offline: a repository with an invalid squash_merge_commit_title gets 2 errors and validate exits 2; 256 repositories with an invalid topic exit 0 (validate and local-plan: the exit status is the error count modulo 256) | registered as KB-034 (confirmed, design): exit 1 on validation errors, keep 2 for crashes; harness checks must never read exit 2 as a crash without the output |
| `F-08` | Docs show orgs.newEnvironmentSecret/newEnvironmentVariable, the template functions are newEnvSecret/newEnvVariable | `docs/reference/organization/repository/environment/index.md:45-52`, `otterdog/resources/defaults/otterdog-defaults.libsonnet:457-461` | offline: orgs.newEnvironmentSecret('X') -&gt; 'failed to load configuration: failed to evaluate jsonnet file: no such field: newEnvironmentSecret' (exit 1) | registered as KB-035 (confirmed): docs fix upstream; nothing to test beyond the load error |
| `F-09` | The template comment of deployment_branch_policy lists 'all, protected_branches, branch_policies' while validation accepts 'all' \| 'protected' \| 'selected' | `otterdog/resources/defaults/otterdog-defaults.libsonnet:450-451`, `otterdog/models/environment.py:128-135` | offline: deployment_branch_policy 'protected_branches' -&gt; "... has 'deployment_branch_policy' of value 'protected_branches', while only values ('all' \| 'protected' \| 'selected') are allowed." | registered as KB-036 (confirmed): template comment fix upstream |
| `F-10` | The team privacy error says ('secret' \| 'closed') although the accepted values are 'secret' \| 'visible' | `otterdog/models/team.py:110-116` | offline, with the member listing of the team validation (its only GitHub read) replaced by a constant: privacy 'closed' -&gt; "... has 'privacy' of value 'closed', while only values ('secret' \| 'closed') are allowed." | registered as KB-037 (confirmed): message fix upstream; the live validation scenario must match the current wording |
| `F-11` | Two validation messages print Python sets, their value order changes from run to run (fork_pr_approval_policy values, code scanning languages) | `otterdog/models/workflow_settings.py:151-158`, `otterdog/models/repository.py:756-763`, `otterdog/models/repository.py:906-907` | offline: "... while only values {'first_time_contributors', 'first_time_contributors_new_to_github', 'all_external_contributors'} are allowed." and the language list in arbitrary order | registered as KB-038 (confirmed, reproduced with PYTHONHASHSEED=1 and 2): scenarios assert only the stable prefix of these messages; upstream could sort the values |
| `F-12` | An unknown role in ruleset bypass_actors ('#Admin') passes validation; the apply then crashes with an uncaught KeyError | `otterdog/models/ruleset.py:1434-1440`, `otterdog/models/ruleset.py:883-884` | offline: validate of a repo ruleset with bypass_actors ['#Admin'] succeeds; the apply payload (RepositoryRuleset.to_provider_data) raises KeyError 'Admin', which the apply loop does not catch (RuntimeError only) | registered as KB-039 (confirmed): validate bypass actors; offline validate scenario plus a live apply check (xfail KB-039) |
| `F-13` | A crashing sync check sets the sync status to 'failure' with the description 'otterdog detected out of sync changes, but they will not prevent a successful merge': misleading for an error, and a required sync context then blocks the merge | `otterdog/webapp/tasks/check_sync.py:133-137`, `otterdog/webapp/tasks/check_sync.py:221-230` | offline, in the webapp image of 9bdeb75 (network none, GitHub REST and MongoDB replaced by recorders): an exception of the sync plan posts 'failure' with that description; the out-of-sync result posts 'success' | registered as KB-040 (confirmed): describe the error ('sync check failed, contact an admin') or keep the state success like the out-of-sync case; webapp-pr.sync-failure records the current behaviour |

<a id="cli"></a>

## CLI commands and global options

`cli`: 63 features, 56 covered, 7 partial, 0 gaps (weighted 94%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `cli.version` | --version prints 'otterdog.sh, version &lt;version&gt;' (dynamic version of the build) | offline | free | P0 | covered | offline, live | `tests/offline/test_cli_basics.py::test_version_is_the_resolved_sut_version`, `tests/cli/test_smoke.py::test_version` |
| `cli.help` | --help lists the 29 subcommands; no subcommand or an unknown option is a click usage error (exit 2) | offline | free | P2 | covered | offline | `tests/offline/test_cli_basics.py::test_help_lists_every_command`, `tests/offline/test_cli_basics.py::test_command_help_lists_the_shared_options`, `tests/offline/test_cli_basics.py::test_usage_errors_exit_2` |
| `cli.global.organizations` | ORGANIZATIONS positional: project name or github_id (case-insensitive), none = every non-archived org, exit code = max over orgs | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_organizations_positional` |
| `cli.global.local-mode` | --local uses the vendored template without cloning; a missing vendor file fails with "template file '&lt;f&gt;' does not exist" (exit 2) | offline | free | P1 | covered | offline | `O-VAL-OK`, `O-LPLAN-ADD`, `tests/offline/test_config_loading.py::test_local_mode_needs_the_vendored_template` |
| `cli.global.verbosity` | -v shows Info messages (otherwise 'in order to print validation infos, enable printing info messages by adding '-v' flag.'); -vv adds tracebacks | offline | free | P2 | covered | offline | `O-VAL-INFOS`, `tests/offline/test_cli_exit_codes.py::test_verbosity_levels`, `tests/offline/test_cli_exit_codes.py::test_debug_verbosity_prints_the_traceback` |
| `cli.global.exit-codes` | Uncaught exceptions and config load errors exit 2 ('Error: &lt;message&gt;', traceback on stderr only with -vv) | offline | free | P1 | covered | offline | `O-VAL-SYNTAX`, `tests/offline/test_cli_exit_codes.py::test_validation_outcomes_set_the_exit_status`, `tests/offline/test_cli_exit_codes.py::test_load_errors_and_crashes`, `tests/offline/test_cli_exit_codes.py::test_debug_verbosity_prints_the_traceback`, `tests/offline/test_cli_exit_codes.py::test_local_plan_exit_status`, `tests/offline/test_cli_exit_codes.py::test_validation_errors_never_exit_like_a_crash`, `tests/offline/test_cli_exit_codes.py::test_secret_reference_with_colons_validates` |
| `cli.global.interrupt-at-startup` | Ctrl+C while the otterdog command loads its modules: 'Aborted!' on stderr and exit 130, no traceback (#937, after v1.8.0; before: a KeyboardInterrupt traceback) | offline | free | P2 | covered | offline | `tests/offline/test_cli_exit_codes.py::test_an_interrupt_while_loading_the_cli_aborts_without_traceback`, `tests/offline/test_cli_exit_codes.py::test_the_entry_point_keeps_the_cli_behaviour` |
| `cli.validate` | validate: 'Validating organization configurations:', per-org header, 'Validation succeeded' / "Validation succeeded': i info(s), w warning(s), 0 error(s)" / 'Validation failed: ...' | offline | free | P0 | covered | offline, live | `O-VAL-OK`, `O-VAL-SYNTAX`, `O-VAL-PLAN-GATE`, `O-VAL-ORGSECRET-PRIVATE-FREE`, `O-VAL-RULESET-STRICT`, `cli.secrets` |
| `cli.validate.missing-config` | validate/plan of a missing org file: "configuration file '&lt;f&gt;' does not exist, run 'fetch-config' or 'import' first." (exit 1) | offline | free | P2 | covered | offline, live | `tests/offline/test_config_loading.py::test_missing_organization_configuration`, `tests/cli/test_commands_errors.py::test_commands_need_the_org_config` |
| `cli.show` | show: prints every model object as key = value blocks (no credentials) | offline | free | P2 | covered | offline | `O-VAL-OK`, `O-LPLAN-ADD`, `O-SHOW`, `tests/offline/test_cli_basics.py::test_show_needs_no_credentials` |
| `cli.show.markdown` | show --markdown [--output-dir DIR]: writes configuration.md and repo-&lt;name&gt;.md (mkdocs tabs) instead of printing | offline | free | P2 | covered | offline | `tests/offline/test_cli_basics.py::test_show_markdown_writes_the_pages`, `tests/offline/test_cli_basics.py::test_show_markdown_keeps_the_repository_links` |
| `cli.show-live` | show-live [-n]: prints the live configuration read from GitHub (web UI unless -n) | cli | free | P2 | covered | live | `tests/cli/test_commands_read.py::test_show_live_prints_the_live_org` |
| `cli.show-default` | show-default: prints the template default of every object type (orgs.newOrg(...) = {, newRepo, newBranchProtectionRule, ...) | offline | free | P1 | covered | offline | `O-SHOW-DEFAULT`, `tests/offline/test_cli_basics.py::test_show_default_prints_every_object_type` |
| `cli.show-default.markdown` | show-default --markdown: mkdocs tab blocks with jsonnet code fences | offline | free | P2 | covered | offline | `tests/offline/test_cli_basics.py::test_show_default_markdown_prints_one_tab_per_object` |
| `cli.canonical-diff` | canonical-diff: unified diff of the file versus its canonical re-serialization (labels inverted, always exit 0) | offline | free | P2 | covered | offline | `O-CANON` |
| `cli.list-projects` | list-projects: rich table 'Projects' (Project name, GitHub ID, Index), no organization positional | offline | free | P2 | covered | offline, live | `tests/offline/test_cli_basics.py::test_list_projects_lists_the_offline_organization`, `tests/cli/test_smoke.py::test_list_projects` |
| `cli.check-token-permissions` | check-token-permissions [-l]: X-OAuth-Scopes must include admin:org, admin:org_hook, delete_repo, repo, workflow ('Missing scopes: ...', exit 1) | cli | free | P1 | covered | live | `tests/cli/test_smoke.py::test_check_token_permissions`, `tests/cli/test_commands_read.py::test_check_token_permissions_lists_the_granted_scopes`, `tests/cli/test_commands_read.py::test_check_token_permissions_reports_missing_scopes`, `tests/cli/test_commands_read.py::test_check_token_permissions_accepts_a_fine_grained_admin` |
| `cli.list-members` | list-members [--two-factor-disabled]: 'Found &lt;n&gt; members.' / 'Found &lt;x&gt; / &lt;total&gt; members with 2FA disabled. Organization has 2FA ...' | cli | free | P2 | covered | live | `tests/cli/test_commands_read.py::test_list_members_counts_the_members` |
| `cli.list-apps` | list-apps [--json]: installations of the org with app_id, slug and permissions (JSON array sorted by slug) | cli | free | P2 | covered | offline, live | `tests/cli/test_commands_read.py::test_list_apps_matches_the_installations`, `tests/offline/test_cli_json_output.py::test_list_apps_json_keeps_stdout_for_the_json` |
| `cli.list-advisories` | list-advisories [-s state ...] [-d] [-w]: CSV of repository security advisories (header line first; -w scrapes the web UI) | cli | free | P2 | covered | live | `tests/web_ui/test_web_commands.py::test_list_advisories_with_web`, `tests/cli/test_commands_read.py::test_list_advisories_prints_the_csv`, `tests/cli/test_commands_read.py::test_list_advisories_keeps_brackets_of_summaries` |
| `cli.dispatch-workflow` | dispatch-workflow [-r repo] --workflow WF: POST workflow dispatch on the default branch ("workflow '&lt;wf&gt;' dispatched for repo '&lt;repo&gt;'") | cli | free | P2 | covered | live | `tests/cli/test_commands_content.py::test_dispatch_workflow_starts_a_run`, `tests/cli/test_commands_content.py::test_failed_dispatch_exits_non_zero` |
| `cli.delete-file` | delete-file -r REPO --path P [-m MSG]: deletes a file of a configured repository ("Deleting file '&lt;p&gt;' in repository '&lt;org&gt;/&lt;repo&gt;': succeeded") | cli | free | P2 | covered | offline, live | `tests/cli/test_commands_content.py::test_delete_file_removes_a_configured_file`, `tests/cli/test_commands_content.py::test_delete_file_reports_a_missing_file`, `tests/cli/test_commands_content.py::test_delete_file_reports_a_refused_deletion`, `tests/offline/test_cli_delete_file.py::test_delete_file_warns_about_a_skipped_repository` |
| `cli.sync-template` | sync-template -r REPO: re-copies the template repository's files into a repo created from it (post_process_template_content rendered) | cli | free | P2 | covered | live | `tests/cli/test_commands_content.py::test_sync_template_recopies_the_template` |
| `cli.list-blueprints` | list-blueprints [-b ID]: table of remediation PRs read anonymously from &lt;defaults.base_url&gt;/api/blueprints/remediations | webapp | free | P1 | covered | live | `tests/cli/test_commands_blueprints.py::test_blueprint_commands_need_a_base_url`, `tests/webapp/test_cli_blueprints.py::test_list_and_approve_blueprints` |
| `cli.approve-blueprints` | approve-blueprints [-b ID]: merges every remediation PR (rebase, else squash, else merge) ('Merging PR #&lt;n&gt;: merged.') | webapp | free | P1 | covered | live | `tests/cli/test_commands_blueprints.py::test_blueprint_commands_need_a_base_url`, `tests/webapp/test_cli_blueprints.py::test_list_and_approve_blueprints` |
| `cli.import` | import -f -n: writes orgs/&lt;org&gt;/&lt;org&gt;.jsonnet from the live org (patches against the template defaults, sorted teams and repos) | cli | free | P0 | covered | live | `tests/cli/test_import.py::test_import_writes_config`, `tests/cli/test_import.py::test_import_validates`, `tests/cli/test_import.py::test_import_plans_no_change` |
| `cli.import.overwrite-backup-secrets` | import over an existing file: prompt without -f, '&lt;file&gt;.bak' backup, 'Copying secrets from previous configuration.', webhook URL masking ('&lt;n&gt; URLs have been masked.') | cli | free | P1 | covered | live | `tests/cli/test_commands_import.py::test_reimport_backs_up_copies_secrets_and_masks_urls`, `tests/cli/test_commands_import.py::test_import_without_force_asks_before_overwriting`, `tests/cli/test_commands_import.py::test_reimport_keeps_the_secret_of_a_masked_webhook` |
| `cli.import.web-ui` | import without -n reads the web-UI settings (full credentials); with -n the warning 'the Web UI will not be queried ...' is printed (UI only) | web_ui | free | P2 | covered | live | `tests/web_ui/test_web_settings.py::test_import_reads_web_settings`, `tests/cli/test_commands_import.py::test_import_without_web_ui_warns_and_skips_web_settings` |
| `cli.import.workflow-keys` | import reads only the workflow settings the default configuration defines (absent or null keys are never requested; #919, 1.8.0) | cli | free | P2 | covered | live | `tests/cli/test_import.py::test_import_reads_only_the_workflow_settings_of_the_template` |
| `cli.fetch-config` | fetch-config [-f] [-p PR] [-r REF] [-s SUFFIX]: reads otterdog/&lt;org&gt;.jsonnet from the config repo default branch, a ref or a PR head | cli | free | P0 | covered | live | `tests/cli/test_config_repo_cli.py::test_push_fetch_round_trip`, `tests/cli/test_commands_config_repo.py::test_fetch_config_from_a_pull_request_and_a_ref`, `tests/cli/test_commands_config_repo.py::test_fetch_config_asks_before_overwriting`, `tests/cli/test_commands_config_repo.py::test_fetch_config_names_the_ref`, `tests/cli/test_commands_config_repo.py::test_config_repo_commands_report_a_missing_repository` |
| `cli.push-config` | push-config [-m MSG] [-n] [-f]: PUTs otterdog/&lt;org&gt;.jsonnet on the default branch after a local-plan diff and a prompt | cli | free | P0 | covered | live | `tests/cli/test_config_repo_cli.py::test_push_fetch_round_trip`, `tests/cli/test_commands_config_repo.py::test_push_config_shows_the_diff_and_asks`, `tests/cli/test_commands_config_repo.py::test_push_config_without_diff_uses_the_default_message`, `tests/cli/test_commands_config_repo.py::test_push_config_refuses_an_invalid_configuration`, `tests/cli/test_commands_config_repo.py::test_push_config_of_an_invalid_configuration_fails`, `tests/cli/test_commands_config_repo.py::test_push_config_to_a_repository_without_definition`, `tests/cli/test_commands_config_repo.py::test_config_repo_commands_report_a_missing_repository` |
| `cli.open-pr` | open-pr -b BRANCH -t TITLE -a AUTHOR: branch otterdog/&lt;branch&gt;, the local file, a PR with the fixed body (always prompts) | cli | free | P1 | covered | live | `tests/cli/test_config_repo_cli.py::test_open_pr`, `tests/cli/test_commands_config_repo.py::test_open_pr_opens_nothing_when_it_must_not`, `tests/cli/test_commands_config_repo.py::test_open_pr_title_and_body`, `tests/cli/test_commands_config_repo.py::test_config_repo_commands_report_a_missing_repository` |
| `cli.plan` | plan -n: 'Planning execution:', legend, '+ add' / '\~' / '!' / '- remove' blocks, 'Plan: A to add, C to change, D to delete.' against the live org | cli | free | P0 | covered | live | `cli.repo.lifecycle`, `cli.team`, `cli.bpr.public`, `cli.ruleset.public`, `cli.environment`, `cli.plan-mismatch` |
| `cli.plan.no-web-ui` | -n/--no-web-ui: token-only credentials, web-UI org settings neither read, diffed nor applied | cli | free | P0 | covered | live | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `cli.repo.lifecycle` |
| `cli.no-web-ui-default` | defaults.github.no_web_ui of otterdog.json is the default of -n/--no-web-ui (show-live, import, plan, check-status, apply, local-apply); --web-ui overrides it (#913) | offline | free | P2 | **partial** | offline | `tests/offline/test_cli_no_web_ui.py::test_no_web_ui_defaults_to_the_configuration`, `tests/offline/test_cli_no_web_ui.py::test_every_command_offers_both_flags` |
| `cli.plan.web-ui` | plan/apply without -n: full credentials (username, password, TOTP), web-UI settings read through Playwright; 'invalid credentials' when they are missing (UI only) | web_ui | free | P2 | covered | live | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip`, `tests/cli/test_commands_errors.py::test_web_commands_need_the_web_credentials` |
| `cli.plan.repo-filter` | -r/--repo-filter PATTERN: only matching repositories are loaded and planned; organization-level objects are always diffed | cli | free | P0 | covered | offline, live | `cli.repo.lifecycle`, `cli.team`, `O-LPLAN-FILTER` |
| `cli.plan.update-secrets` | --update-secrets [--update-filter PATTERN]: forced '!' update of secrets whose name matches (values are never compared) | cli | free | P1 | covered | offline, live | `cli.secrets`, `O-LPLAN-FORCED-SECRETS`, `cli.org.secret`, `cli.environment.secrets` |
| `cli.plan.update-webhooks` | --update-webhooks [--update-filter URL-PATTERN]: forced '!' update of webhooks with a non-dummy secret and a matching url | cli | free | P1 | covered | offline, live | `O-LPLAN-FORCED-WEBHOOKS`, `cli.repo.webhook-secret`, `tests/webhooks/test_managed_org_hook.py::test_org_webhook_secret` |
| `cli.plan.only-secrets` | --only-secrets: only secret patches (org, repo, environment) are planned/applied | offline | free | P2 | covered | offline | `O-LPLAN-FORCED-SECRETS`, `O-LPLAN-ONLY-SECRETS` |
| `cli.plan.read-only-note` | read-only keys (plan, two_factor_requirement, template_repository): "Note: setting '&lt;k&gt;' is read-only, will be skipped." and not counted | cli | free | P1 | covered | offline, live | `cli.plan-mismatch`, `O-LPLAN-READ-ONLY-KEYS` |
| `cli.plan.webhook-secret-removal` | removing a webhook secret prints "Warning: removing secret for webhook with url '&lt;url&gt;'" | offline | free | P2 | covered | offline | `O-LPLAN-FORCED-WEBHOOKS`, `O-LPLAN-WEBHOOK-SECRET-REMOVED` |
| `cli.plan.validation-abort` | validation errors abort the plan: 'Planning aborted due to validation errors.' and no Plan: line | offline | free | P0 | covered | offline, live | `O-VAL-RULESET-STRICT`, `regression.code-scanning-new-repo`, `regression.repo-ruleset-without-strict` |
| `cli.plan.errors` | plan error paths: 'planning aborted: &lt;e&gt;' (exit 1, e.g. value_type change), 'failed to load configuration' (1), network/GitHub errors (2) | offline | free | P1 | covered | offline | `O-LPLAN-ERRORS`, `tests/offline/test_cli_exit_codes.py::test_plan_without_github_exits_2` |
| `cli.check-status` | check-status [-n] [-r] [-j FILE]: 'Archived/Validation status/Synchronization status' lines and a JSON list {org_id, is_archived, validation_status, sync_status} | cli | free | P0 | covered | offline, live | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `tests/cli/test_commands_check_status.py::test_check_status_reports_validity_and_sync`, `tests/cli/test_commands_check_status.py::test_check_status_of_an_invalid_configuration`, `tests/cli/test_commands_check_status.py::test_check_status_fails_for_an_invalid_configuration`, `tests/offline/test_cli_json_output.py::test_check_status_json_dash_writes_the_json_to_stdout` |
| `cli.local-plan` | local-plan [-s SUFFIX]: 'Printing local diff:' of &lt;org&gt;.jsonnet against &lt;org&gt;.jsonnet-BASE without GitHub (same engine as the webapp validation) | offline | free | P0 | covered | offline | `O-LPLAN-ADD`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE` |
| `cli.local-plan.suffix-and-missing-base` | local-plan -s other suffix; a missing BASE file: 'failed to load current configuration' / "configuration file '...-BASE' does not exist" (exit 1) | offline | free | P2 | covered | offline | `tests/offline/test_cli_local_plan_flags.py::test_local_plan_compares_with_another_suffix`, `tests/offline/test_cli_local_plan_flags.py::test_missing_other_side_fails_the_plan` |
| `cli.local-plan.dummy-secrets` | local-plan replaces dummy secrets by '&lt;DUMMY&gt;' and diffs secret references ('pass:a' -&gt; 'pass:b'), resolve_secrets off | offline | free | P1 | covered | offline | `O-LPLAN-ADD`, `O-LPLAN-FORCED-SECRETS`, `O-LPLAN-FORCED-WEBHOOKS`, `O-LPLAN-SECRET-REFS`, `tests/offline/test_cli_local_plan_flags.py::test_local_apply_forces_no_dummy_secret`, `tests/offline/test_cli_local_plan_flags.py::test_local_plan_forces_no_dummy_secret` |
| `cli.apply` | apply -f -n: applies the plan ('Applying changes:', progress, 'Executed plan: A added, C changed, D deleted.' / 'D live resources ignored.') | cli | free | P0 | covered | live | `cli.repo.lifecycle`, `cli.team`, `cli.secrets`, `cli.bpr.public`, `cli.ruleset.public`, `cli.environment` |
| `cli.apply.delete-resources` | -d/--delete-resources: REMOVE patches are applied only with -d (else skipped) | cli | free | P0 | covered | live | `cli.repo.lifecycle`, `cli.team`, `cli.bpr.public`, `cli.ruleset.public`, `cli.repo.webhook` |
| `cli.apply.delete-filter` | apply/local-apply -d --delete-filter SELECTOR (repeatable): only the selected deletions are applied, every other change is skipped and counted (#939, after v1.8.0) | cli | free | P1 | covered | offline, live | `cli.apply.delete-filter`, `tests/offline/test_cli_local_apply.py::test_a_delete_filter_applies_only_the_selected_deletions`, `tests/offline/test_cli_local_apply.py::test_a_delete_filter_selecting_nothing_changes_nothing`, `tests/offline/test_cli_local_apply.py::test_delete_filter_usage_errors`, `tests/offline/test_cli_local_apply.py::test_deletions_in_a_renamed_repository` |
| `cli.apply.deletion-hints` | without -d: 'No changes required.' + '&lt;n&gt; resource(s) would be deleted with flag '--delete-resources'.' or 'No resource will be removed, use flag ...' | offline | free | P1 | covered | offline | `tests/offline/test_cli_local_apply.py::test_removals_without_delete_flag_are_only_hinted`, `tests/offline/test_cli_local_apply.py::test_declined_approval_cancels_the_apply` |
| `cli.apply.prompt` | apply/local-apply without -f: "Do you want to perform these actions? (Only 'yes' or 'y' ...)"; 'n' -&gt; 'Apply cancelled.' (exit 0); EOF -&gt; exit 2 | offline | free | P2 | covered | offline, live | `tests/offline/test_cli_local_apply.py::test_declined_approval_cancels_the_apply`, `tests/offline/test_cli_local_apply.py::test_end_of_input_at_the_prompt_exits_2`, `tests/cli/test_commands_local_apply.py::test_local_apply_applies_the_local_diff` |
| `cli.apply.validation-errors` | apply with validation errors prints 'Planning aborted due to validation errors.' and exits with the error count (#923, 1.8.0; before: 'No changes required.' and exit 0, KB-001) | cli | free | P1 | **partial** | offline, live | `tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors`, `tests/offline/test_cli_local_apply.py::test_validation_errors_fail_the_local_apply` |
| `cli.apply.failed-patches` | a failing patch prints 'failed to apply patch: &lt;TYPE&gt; - &lt;header&gt;' and the exit code is the number of failed patches | cli | free | P1 | covered | live | `tests/cli/test_commands_errors.py::test_failed_patches_set_the_exit_code` |
| `cli.local-apply` | local-apply [-s SUFFIX] [-f] [-n] [-d]: applies the BASE -&gt; config diff to live GitHub (what the webapp does after a merge) | cli | free | P1 | covered | live | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/cli/test_commands_local_apply.py::test_local_apply_applies_the_local_diff` |
| `cli.web-login` | web-login: opens a headful browser logged in as the bot, waits for input, logs out (UI only) | web_ui | free | P2 | covered | **unverified** | `tests/web_ui/test_web_commands.py::test_web_login_opens_a_session` |
| `cli.install-app` | install-app -a SLUG: installs an App through the web UI ('app already installed, skipping.' / 'app installed.') (UI only) | web_ui | free | P2 | **partial** | **unverified** | `tests/web_ui/test_web_commands.py::test_install_and_uninstall_app` |
| `cli.uninstall-app` | uninstall-app -a SLUG: uninstalls an App through the web UI ('uninstalled app.') (UI only) | web_ui | free | P2 | **partial** | **unverified** | `tests/web_ui/test_web_commands.py::test_install_and_uninstall_app` |
| `cli.review-permissions` | review-permissions [-a SLUG] [-g] [-f]: lists requested App permission updates and grants them through the web UI (UI only) | web_ui | free | P2 | **partial** | live | `tests/web_ui/test_web_commands.py::test_review_permissions_lists_requests` |
| `cli.install-deps` | install-deps: runs 'python -m playwright install firefox' (exits 0 even when it fails) (UI only) | web_ui | free | P2 | covered | live | `tests/web_ui/test_web_commands.py::test_install_deps_keeps_the_installed_firefox`, `tests/web_ui/test_web_commands.py::test_install_deps_reports_a_failed_download`, `tests/web_ui/test_web_commands.py::test_failed_install_deps_exits_non_zero` |
| `cli.local-apply.code-security-metadata` | local-apply reads the code security configurations of the organization and the configuration of each repository from GitHub before its plan whenever the template defines them (#892): no offline local-apply any more | offline | free | P2 | **partial** | offline | `tests/offline/test_cli_local_apply.py::test_local_apply_reads_code_security_configurations_from_github` |
| `cli.global.stats` | --stats / OTTERDOG_STATS (GitHub API usage report on stderr) and --stats-file / OTTERDOG_STATS_FILE (JSON) of every StdCommand; -v logs one 'github api usage for organization' INFO line per organization (#881) | offline | free | P2 | **partial** | offline | `tests/offline/test_cli_exit_codes.py::test_verbosity_levels` |

Details:

- **`cli.version`** (covered, P0, `offline`): --version prints 'otterdog.sh, version &lt;version&gt;' (dynamic version of the build)
    - Source: `otterdog/cli.py:233-238`, `otterdog/__init__.py:9-11`
    - Operations: run
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.help`** (covered, P2, `offline`): --help lists the 29 subcommands; no subcommand or an unknown option is a click usage error (exit 2)
    - Source: `otterdog/cli.py:41`, `otterdog/cli.py:233-238`, `otterdog/cli.py:241-1046`
    - Operations: run, exit-code
    - Notes: --help/-h list the 29 inventoried commands (an unknown extra command only warns), validate --help the shared options; otterdog alone, an unknown option, an unknown command and open-pr without -a exit 2 with the click usage on stderr before any config load (v1.6.1 and 9bdeb75)
- **`cli.global.organizations`** (covered, P2, `offline`): ORGANIZATIONS positional: project name or github_id (case-insensitive), none = every non-archived org, exit code = max over orgs
    - Source: `otterdog/cli.py:158`, `otterdog/cli.py:1054-1099`, `otterdog/config.py:481-503`
    - Operations: run, exit-code, config
    - Notes: First org 1 error, second valid: no positional processes both in config order and exits 1 (largest, not the last org's 0); github_id and project name match case-insensitively; positionals keep their order; 'nope' exits 2 before any header
- **`cli.global.local-mode`** (covered, P1, `offline`): --local uses the vendored template without cloning; a missing vendor file fails with "template file '&lt;f&gt;' does not exist" (exit 2)
    - Source: `otterdog/cli.py:124-133`, `otterdog/jsonnet.py:165-180`
    - Operations: config, error
    - Notes: Missing vendor file: validate and show exit 2 ("template file '...' does not exist", before the project header), local-plan exits 1 ('planning aborted: template file ...'); vendoring fixes it
- **`cli.global.verbosity`** (covered, P2, `offline`): -v shows Info messages (otherwise 'in order to print validation infos, enable printing info messages by adding '-v' flag.'); -vv adds tracebacks
    - Source: `otterdog/cli.py:108-113`, `otterdog/logging.py:94-134`, `otterdog/operations/validate.py:97-102`, `otterdog/operations/diff_operation.py:292-297`
    - Operations: run
    - Notes: level 0: Info messages only counted (validate hint, local-plan 'there have been 1 validation infos'); -v: the Info boxes (validate and local-plan, O-VAL-INFOS); -vv: DEBUG lines and the rich traceback of an escaped exception on stderr instead of the Error box; -vvv: TRACE lines.
- **`cli.global.exit-codes`** (covered, P1, `offline`): Uncaught exceptions and config load errors exit 2 ('Error: &lt;message&gt;', traceback on stderr only with -vv)
    - Source: `otterdog/cli.py:160-179`, `otterdog/cli.py:1097-1099`, `otterdog/logging.py:153-180`
    - Operations: exit-code, error
    - Known bugs: KB-025, KB-034
    - New findings: F-07
    - Notes: 0 valid, 1 one error, 1 jsonnet evaluation error (caught 'failed to load configuration'), 2 schema type error / unknown org (escaped exception, boxed Error, no summary, empty stderr). KB-034 (2 errors exit 2, 256 errors exit 0 for validate and local-plan) and KB-025 are asserted as the correct behaviour in known_bug-marked non-strict xfails (O-KB-EXIT-STATUS-ERROR-COUNT, O-KB-SECRET-WITH-COLONS)
- **`cli.global.interrupt-at-startup`** (covered, P2, `offline`): Ctrl+C while the otterdog command loads its modules: 'Aborted!' on stderr and exit 130, no traceback (#937, after v1.8.0; before: a KeyboardInterrupt traceback)
    - Source: `otterdog/__main__.py:15-29`, `pyproject.toml:45`, `otterdog.sh:30`
    - Operations: exit-code, error
    - Notes: the interrupt is raised by a stand-in for click (the first third-party import of otterdog.cli) on PYTHONPATH, so it lands while the cli loads on every run; a real SIGINT is timing-dependent. Not covered: otterdog.sh (the harness runs the console script) and python -m otterdog; an interrupt during an operation ('operation interrupted', exit 130) is unchanged by #937 and untested.
- **`cli.validate`** (covered, P0, `offline`): validate: 'Validating organization configurations:', per-org header, 'Validation succeeded' / "Validation succeeded': i info(s), w warning(s), 0 error(s)" / 'Validation failed: ...'
    - Source: `otterdog/cli.py:241-248`, `otterdog/operations/validate.py:45-106`
    - Operations: run, validate, exit-code
    - Notes: the stray quote of the warning-only summary ("Validation succeeded': 0 info(s), 1 warning(s), 0 error(s)") is verified offline; validate needs GitHub only for teams (org members) and code scanning languages
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.validate.missing-config`** (covered, P2, `offline`): validate/plan of a missing org file: "configuration file '&lt;f&gt;' does not exist, run 'fetch-config' or 'import' first." (exit 1)
    - Source: `otterdog/operations/validate.py:62-64`, `otterdog/operations/diff_operation.py:183-187`
    - Operations: error, exit-code
    - Notes: validate and show exit 1 ("does not exist, run 'fetch-config' or 'import' first."), local-plan exit 1 ('does not yet exist, run fetch-config or import first.') Live: validate and list-members/delete-file/sync-template/push-config/open-pr "configuration file '&lt;f&gt;' does not exist, run 'fetch-config' or 'import' first.", local-plan/plan/apply/check-status '... does not yet exist, run fetch-config or import first.', all exit 1 (verified offline too).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.show`** (covered, P2, `offline`): show: prints every model object as key = value blocks (no credentials)
    - Source: `otterdog/cli.py:251-271`, `otterdog/operations/show.py:48-97`
    - Operations: run
    - Notes: show prints settings, org webhook, repository, repo variable, BPR and environment blocks with values, no diff lines; it resolves no credentials (works with a provider-less entry where validate exits 1). File scenarios/offline/cli/show.yaml
- **`cli.show.markdown`** (covered, P2, `offline`): show --markdown [--output-dir DIR]: writes configuration.md and repo-&lt;name&gt;.md (mkdocs tabs) instead of printing
    - Source: `otterdog/cli.py:251-271`, `otterdog/operations/show.py:97-298`
    - Operations: run
    - Known bugs: KB-050
    - Notes: configuration.md (front matter, 5 tabs, webhook/secret/variable/repository rows) and repo-&lt;name&gt;.md (6 tabs) in a new --output-dir; the '[&lt;name&gt;]' link texts are swallowed by rich markup
- **`cli.show-live`** (covered, P2, `cli`): show-live [-n]: prints the live configuration read from GitHub (web UI unless -n)
    - Source: `otterdog/cli.py:274-289`, `otterdog/operations/show_live.py:35-83`
    - Operations: run, converge
    - Notes: show-live -n: header, the --no-web-ui warning, REST-backed settings equal GET /orgs/{org} (plan from plan.name), no web-only key in the settings block, every repository/team the oracle lists has its block (advisory forks excluded like otterdog). Without -n it runs as the trusted reader of the web_ui round trip (reset SUT only).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.show-default.markdown`** (covered, P2, `offline`): show-default --markdown: mkdocs tab blocks with jsonnet code fences
    - Source: `otterdog/operations/show_default.py:326-343`
    - Operations: run
    - Notes: 12 tabs up to v1.7.1, 17 with the template of main d9dac78 (Dependabot and Codespaces secrets, code security configurations: show-default skips the types the template does not define), each with a jsonnet fence holding its orgs.new... = { block, no plain-text header
- **`cli.canonical-diff`** (covered, P2, `offline`): canonical-diff: unified diff of the file versus its canonical re-serialization (labels inverted, always exit 0)
    - Source: `otterdog/cli.py:897-904`, `otterdog/operations/canonical_diff.py:36-113`
    - Operations: run
    - Known bugs: KB-010, KB-050
    - Notes: a list whose template default is null is written as a replacement (':') since #916 (1.8.0; '+:' before, null + array fails to evaluate): steps custom-property-list-default (default_value of a multi_select custom property, 'allowed_values+:' unchanged) and code-security-bypass-reviewers (secret_scanning_delegated_bypass_reviewers, SUTs with #892) of O-CANON, asserted per SUT by expect_canonical_list_replacement; import writes the same form (live, not asserted)
- **`cli.list-projects`** (covered, P2, `offline`): list-projects: rich table 'Projects' (Project name, GitHub ID, Index), no organization positional
    - Source: `otterdog/cli.py:465-472`, `otterdog/operations/list_projects.py:22-50`
    - Operations: run
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.check-token-permissions`** (covered, P1, `cli`): check-token-permissions [-l]: X-OAuth-Scopes must include admin:org, admin:org_hook, delete_repo, repo, workflow ('Missing scopes: ...', exit 1)
    - Source: `otterdog/cli.py:1012-1027`, `otterdog/operations/check_token_permissions.py:26-78`
    - Operations: run, exit-code, permission
    - Known bugs: KB-078
    - Notes: -l: 'Granted scopes:' == the token's X-OAuth-Scopes; config_reader (no scope): 'Missing scopes:' == the five required minus granted (order-insensitive: printed from a frozenset), exit 1. A fine-grained ADMIN token is reported the same way (KB-078: the command only knows classic scopes); its test is skipped with a classic admin token.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.list-members`** (covered, P2, `cli`): list-members [--two-factor-disabled]: 'Found &lt;n&gt; members.' / 'Found &lt;x&gt; / &lt;total&gt; members with 2FA disabled. Organization has 2FA ...'
    - Source: `otterdog/cli.py:454-462`, `otterdog/operations/list_members.py:42-101`
    - Operations: run
    - Notes: 'Found &lt;n&gt; members.' n = GET /orgs/{org}/members; --two-factor-disabled: '&lt;x&gt; / &lt;n&gt; members with 2FA disabled' (x = filter=2fa_disabled) and the 2FA status from the LOCAL config (two_factor_requirement::: true -&gt; enabled, false -&gt; disabled on the same org).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.list-apps`** (covered, P2, `cli`): list-apps [--json]: installations of the org with app_id, slug and permissions (JSON array sorted by slug)
    - Source: `otterdog/cli.py:437-451`, `otterdog/operations/list_apps.py:32-86`
    - Operations: run
    - Known bugs: KB-051
    - Notes: --json array == GET /orgs/{org}/installations reduced to app_id/app_slug/permissions, sorted by slug, e2e App listed with its id when ready; text mode: one app['&lt;slug&gt;'] block with app_id per installation. Since #963 (02e0e72, after v1.8.0) stdout holds only the JSON (click.echo) and the messages, errors and -v log records go to stderr; O-JSON-STDOUT checks it offline with refused credentials ('[]' on stdout, exit 1), and the error on stdout before #963.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.list-advisories`** (covered, P2, `cli`): list-advisories [-s state ...] [-d] [-w]: CSV of repository security advisories (header line first; -w scrapes the web UI)
    - Source: `otterdog/cli.py:982-1009`, `otterdog/operations/list_advisories.py:23-153`
    - Operations: run
    - Known bugs: KB-050
    - Notes: draft advisory of a run repo: exact CSV header, full row (org, draft, low, NO_CVE, summary, html_url, dates, empty comment fields without -w) for default states and -s all, absent from -s published; -d blocks without header; listings == the oracle per state.
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.dispatch-workflow`** (covered, P2, `cli`): dispatch-workflow [-r repo] --workflow WF: POST workflow dispatch on the default branch ("workflow '&lt;wf&gt;' dispatched for repo '&lt;repo&gt;'")
    - Source: `otterdog/cli.py:336-355`, `otterdog/operations/dispatch_workflow.py:41-79`
    - Operations: run
    - Known bugs: KB-045
    - Notes: dispatch on the default branch -&gt; a workflow_dispatch run with head_branch main; unknown workflow 'failed to dispatch ...'; unknown repo exits non-zero.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.delete-file`** (covered, P2, `cli`): delete-file -r REPO --path P [-m MSG]: deletes a file of a configured repository ("Deleting file '&lt;p&gt;' in repository '&lt;org&gt;/&lt;repo&gt;': succeeded")
    - Source: `otterdog/cli.py:875-894`, `otterdog/operations/delete_file.py:48-117`
    - Operations: run, error
    - Known bugs: KB-043, KB-044
    - Notes: -m message and default message "Deleting file '&lt;p&gt;' with otterdog." as head commit messages, file gone; missing file creates no commit; unconfigured repo untouched. Since #961 (97bce29, after v1.8.0, fixes KB-043 and KB-044): a missing file 'not found, nothing to delete', a refused deletion 'failed' + 'failure deleting file' and exit 1 (live), a repository missing from the configuration or archived a warning ('not found in the configuration, skipped', 'is archived, skipped') and exit 0 (O-DELETE-FILE-SKIP, offline). Not covered: a path naming a directory ('is not a file', exit 1) and a read of the file that fails (403, 5xx: error, no DELETE sent).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.sync-template`** (covered, P2, `cli`): sync-template -r REPO: re-copies the template repository's files into a repo created from it (post_process_template_content rendered)
    - Source: `otterdog/cli.py:859-872`, `otterdog/operations/sync_template.py:38-94`, `otterdog/providers/github/rest/repo_client.py:1494-1548`
    - Operations: run
    - Notes: Python test instead of the suggested YAML cli.repo.template: template change -&gt; 'updated file' for README.md (re-rendered {{org}}/{{repo}}), TEMPLATE.txt (verbatim), NEW.txt; second run updates nothing; a repo without template_repository is skipped.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.list-blueprints`** (covered, P1, `webapp`): list-blueprints [-b ID]: table of remediation PRs read anonymously from &lt;defaults.base_url&gt;/api/blueprints/remediations
    - Source: `otterdog/cli.py:475-483`, `otterdog/operations/list_blueprints.py:44-110`
    - Operations: run, error
    - Known bugs: KB-042
    - Notes: W-CLI-BLUEPRINTS (tests/webapp): with a required_file remediation PR and the SUT CLI installed with the app group (install_cli with_app=True, host runtime only) and base_url = the webapp, the 'Projects' table is exactly [&lt;id&gt;, &lt;org&gt;, &lt;repo&gt;, &lt;PR url&gt;]; without defaults.base_url: exit 2 and "no base_url set which is required when using operation 'list-blueprints'". A CLI-only install crashes with ModuleNotFoundError (KB-042, cli.kb.blueprint-commands-without-webapp).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`cli.approve-blueprints`** (covered, P1, `webapp`): approve-blueprints [-b ID]: merges every remediation PR (rebase, else squash, else merge) ('Merging PR #&lt;n&gt;: merged.')
    - Source: `otterdog/cli.py:486-494`, `otterdog/operations/approve_blueprints.py:40-140`
    - Operations: run
    - Known bugs: KB-042
    - Notes: W-CLI-BLUEPRINTS (tests/webapp): approve-blueprints -b &lt;id&gt; prints 'Merging PR #&lt;n&gt;: merged.', the PR is merged on GitHub, UpdateBlueprintStatusTask and DeleteBranchTask finish, the remediation branch is gone and the status goes recheck/success. A CLI-only install crashes with ModuleNotFoundError (KB-042).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`cli.import`** (covered, P0, `cli`): import -f -n: writes orgs/&lt;org&gt;/&lt;org&gt;.jsonnet from the live org (patches against the template defaults, sorted teams and repos)
    - Source: `otterdog/cli.py:497-513`, `otterdog/operations/import_configuration.py:47-146`, `otterdog/models/github_organization.py:840-1031`
    - Operations: import, converge
    - Known bugs: KB-024
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.import.overwrite-backup-secrets`** (covered, P1, `cli`): import over an existing file: prompt without -f, '&lt;file&gt;.bak' backup, 'Copying secrets from previous configuration.', webhook URL masking ('&lt;n&gt; URLs have been masked.')
    - Source: `otterdog/operations/import_configuration.py:56-132`, `otterdog/operations/__init__.py:82-98`
    - Operations: import, prompt, security
    - Known bugs: KB-048
    - Notes: Second import: &lt;file&gt;.bak == previous file, 'Copying secrets ...', 'Masking webhooks ... 1 URLs have been masked.', repo secret and unmasked hook keep the literal value, live URL replaced by the masked one; without -f 'n' -&gt; 'Operation cancelled.' exit 1, file and backup unchanged.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.import.web-ui`** (covered, P2, `web_ui`): import without -n reads the web-UI settings (full credentials); with -n the warning 'the Web UI will not be queried ...' is printed
    - Source: `otterdog/operations/import_configuration.py:76-91`, `otterdog/providers/github/web.py:73-179`
    - Operations: import
    - Notes: import -n: the warning, no web-only key written (template defaults), secrets read as \*\*\*\*\*\*\*\*; web import: no warning (assertion added inside the existing login).
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.import.workflow-keys`** (covered, P2, `cli`): import reads only the workflow settings the default configuration defines (absent or null keys are never requested; #919, 1.8.0)
    - Source: `otterdog/models/github_organization.py:1268-1277`, `otterdog/models/github_organization.py:1785-1794`
    - Operations: import
    - Notes: request statistics of import -f -n: the standard template reads the org and repository cache sizes; a local copy of it (#917) with max_cache_size_gb null at both levels reads neither and writes no max_cache_size_gb, repository Actions settings still read. Skipped on SUTs before 1.8.0.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.fetch-config`** (covered, P0, `cli`): fetch-config [-f] [-p PR] [-r REF] [-s SUFFIX]: reads otterdog/&lt;org&gt;.jsonnet from the config repo default branch, a ref or a PR head
    - Source: `otterdog/cli.py:358-392`, `otterdog/operations/fetch_config.py:54-113`
    - Operations: run, prompt, config
    - Known bugs: KB-049
    - Notes: -p head, -r branch, -s suffix files, overwrite prompt n/y, unknown PR and missing config repo 'failed to fetch definition from repo' exit 1.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.push-config`** (covered, P0, `cli`): push-config [-m MSG] [-n] [-f]: PUTs otterdog/&lt;org&gt;.jsonnet on the default branch after a local-plan diff and a prompt
    - Source: `otterdog/cli.py:395-421`, `otterdog/operations/push_config.py:54-205`
    - Operations: run, prompt, plan
    - Known bugs: KB-046
    - Notes: diff + prompt n ('push cancelled.', no commit) / y (pushed, -m commit message), identical file pushes nothing, -n pushes without diff/prompt with the default message, invalid config not pushed, 'No configuration yet available.' for a repo without definition, missing repo exit 1.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.open-pr`** (covered, P1, `cli`): open-pr -b BRANCH -t TITLE -a AUTHOR: branch otterdog/&lt;branch&gt;, the local file, a PR with the fixed body (always prompts)
    - Source: `otterdog/cli.py:424-434`, `otterdog/operations/open_pull_request.py:50-195`
    - Operations: run, prompt, error
    - Notes: identical (exit 0), validation error (exit 1), unknown author (exit 2), 'n' (exit 1) open nothing and leave no otterdog/&lt;branch&gt;; opened PR: title, fixed body naming the author, head, printed URL; missing repo exit 1.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.plan`** (covered, P0, `cli`): plan -n: 'Planning execution:', legend, '+ add' / '\~' / '!' / '- remove' blocks, 'Plan: A to add, C to change, D to delete.' against the live org
    - Source: `otterdog/cli.py:516-571`, `otterdog/operations/plan.py:46-137`, `otterdog/operations/diff_operation.py:131-262`
    - Operations: plan, converge
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.plan.no-web-ui`** (covered, P0, `cli`): -n/--no-web-ui: token-only credentials, web-UI org settings neither read, diffed nor applied
    - Source: `otterdog/cli.py:517-517`, `otterdog/operations/diff_operation.py:156-157`, `otterdog/providers/github/__init__.py:126-146`
    - Operations: coerce, config
    - Notes: every live command of the harness passes -n; the baseline renders the template defaults of the web keys and still converges, which proves they are ignored
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.no-web-ui-default`** (partial, P2, `offline`): defaults.github.no_web_ui of otterdog.json is the default of -n/--no-web-ui (show-live, import, plan, check-status, apply, local-apply); --web-ui overrides it (#913)
    - Source: `otterdog/cli.py:274-281`, `otterdog/cli.py:1049-1051`, `otterdog/config.py:421-423`, `otterdog/operations/local_apply.py:97-98`
    - Operations: config, run
    - Notes: sources at main a196494 (1.8.0.dev). Offline (O-CONFIG-NO-WEB-UI): local-apply skips the change of a web UI setting when no_web_ui is in effect, from -n/--no-web-ui or from the configured default, and plans it with --web-ui or without either; the six commands document the flag pair; SUTs without #913 ignore the setting and refuse --web-ui (both asserted per SUT history). The other five commands resolve the option with the same _resolve_no_web_ui but need GitHub.
    - Suggested: `cli.config.no-web-ui-default` in `tests/cli/test_org_config.py`
    - Steps:
        - live workspace whose .otterdog-defaults.json sets github.no_web_ui: true; plan and apply without -n (the runner always passes -n: a raw invoke)
    - Assert:
        - the commands run with token-only credentials (no web login) and plan no web UI setting; with --web-ui they ask for the web credentials
    - Needs:
        - target
        - available: WorkspaceLayout(defaults_override=...) on a live workspace, OtterdogCli.invoke
- **`cli.plan.web-ui`** (covered, P2, `web_ui`): plan/apply without -n: full credentials (username, password, TOTP), web-UI settings read through Playwright; 'invalid credentials' when they are missing
    - Source: `otterdog/operations/diff_operation.py:156-157`, `otterdog/providers/github/web.py:73-265`, `otterdog/credentials/__init__.py:55-77`
    - Operations: plan, config
    - Notes: plan/apply/check-status/import/show-live/local-apply without -n and with unset web-login variables: 'invalid credentials' + "environment variable 'E2E_OTTERDOG_NO_WEB_USERNAME' for key 'username' not found", exit 1, before any web access (no login possible).
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.plan.repo-filter`** (covered, P0, `cli`): -r/--repo-filter PATTERN: only matching repositories are loaded and planned; organization-level objects are always diffed
    - Source: `otterdog/cli.py:518-524`, `otterdog/models/github_organization.py:2117-2120`, `otterdog/models/repository.py:1029-1032`
    - Operations: filter, plan
    - Known bugs: KB-077
    - Notes: O-LPLAN-FILTER (offline): -r '&lt;p&gt;-a' plans the matching repository and the organization variable and leaves the other repository and its branch protection rule out (0/2/0); a pattern '&lt;p&gt;-\*' plans both (0/4/0); an added repository outside the filter is not planned, one matching it is. A repository that exists only in the other configuration is planned for removal whatever the filter (KB-077, step-level). Every live scenario plans with -r e2e-&lt;run&gt;-\* (cli.repo.lifecycle, cli.team).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.plan.update-secrets`** (covered, P1, `cli`): --update-secrets [--update-filter PATTERN]: forced '!' update of secrets whose name matches (values are never compared)
    - Source: `otterdog/cli.py:532-551`, `otterdog/models/secret.py:144-159`
    - Operations: forced-update, filter
    - Known bugs: KB-056
    - Notes: offline (O-LPLAN-FORCED-SECRETS): forced '!' updates of organization, repository and environment secrets (every key 'v -&gt; v', 0/10/0) and --update-filter selecting one secret (0/2/0). Live: cli.secrets and cli.environment.secrets apply with --update-secrets, cli.org.secret applies with --update-secrets and --update-filter and asserts '! org_secret[name=&lt;P&gt;_ORG_SECRET]' while the other secret is not forced. local-plan also forces dummy secrets that every apply skips (KB-056).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`cli.plan.update-webhooks`** (covered, P1, `cli`): --update-webhooks [--update-filter URL-PATTERN]: forced '!' update of webhooks with a non-dummy secret and a matching url
    - Source: `otterdog/cli.py:525-531`, `otterdog/models/webhook.py:182-201`
    - Operations: forced-update, filter
    - Known bugs: KB-056
    - Notes: offline (O-LPLAN-FORCED-WEBHOOKS): forced '!' updates of org and repo hooks with a secret, never of a hook without secret (0/14/0), --update-filter on urls (0/7/0). Live: cli.repo.webhook-secret applies with --update-webhooks and an url filter (only the secured hook is forced) and H-ORG-HOOK-SECRET forces an organization hook. local-plan also forces hooks with a dummy secret that every apply skips (KB-056).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `webapp` with `v1.8.0`: run `tp239l54` (2026-11-25)
- **`cli.plan.only-secrets`** (covered, P2, `offline`): --only-secrets: only secret patches (org, repo, environment) are planned/applied
    - Source: `otterdog/cli.py:539-545`, `otterdog/operations/diff_operation.py:212-213`
    - Operations: filter, forced-update
    - Notes: verified offline: local-plan --only-secrets --update-secrets shows the forced org secret and hides a repository description change. only-secrets-forced and only-secrets-changes steps; O-LPLAN-ONLY-SECRETS covers it too. scenarios/offline/secrets/lplan-only-secrets.yaml: with --update-secrets org, repo and env secrets forced (8 changed keys) and the repository change hidden; without --update-secrets a noop; control without the flag shows only the repository change
- **`cli.plan.read-only-note`** (covered, P1, `cli`): read-only keys (plan, two_factor_requirement, template_repository): "Note: setting '&lt;k&gt;' is read-only, will be skipped." and not counted
    - Source: `otterdog/operations/plan.py:112-117`, `otterdog/models/organization_settings.py:55-68`, `otterdog/models/repository.py:81`
    - Operations: plan, coerce
    - Notes: verified offline too (local-plan of plan free -&gt; team and template_repository 'o/a' -&gt; 'o/b': the Note, 'Plan: 0 to add, 0 to change, 0 to delete.'). plan (base_config on team), two_factor_requirement, template_repository notes not counted; mixed with writable keys (0/2/0).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.plan.webhook-secret-removal`** (covered, P2, `offline`): removing a webhook secret prints "Warning: removing secret for webhook with url '&lt;url&gt;'"
    - Source: `otterdog/operations/plan.py:103-110`, `otterdog/models/webhook.py:205-227`
    - Operations: plan, security
    - Notes: verified offline with local-plan. org and repo hook secret removal warnings; also O-LPLAN-WEBHOOK-SECRET-REMOVED. scenarios/offline/webhooks/lplan-webhook-secret.yaml: org and repo webhooks ('- secret = ...' + the Warning), a changed reference without warning, an unchanged one noop
- **`cli.plan.validation-abort`** (covered, P0, `offline`): validation errors abort the plan: 'Planning aborted due to validation errors.' and no Plan: line
    - Source: `otterdog/operations/plan.py:121-126`
    - Operations: plan, validate
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`cli.plan.errors`** (covered, P1, `offline`): plan error paths: 'planning aborted: &lt;e&gt;' (exit 1, e.g. value_type change), 'failed to load configuration' (1), network/GitHub errors (2)
    - Source: `otterdog/operations/diff_operation.py:131-204`, `otterdog/operations/plan.py:128-139`
    - Operations: error, exit-code
    - Notes: verified offline: changing a custom property value_type prints "planning aborted: trying to change 'value_type' to 'true_false' for custom_property[name="p1"] which is not supported." exit 1. value_type change 'planning aborted: ...' exit 1, head not evaluating 'failed to load configuration' exit 1, other side not evaluating 'failed to load current configuration' exit 1, plan in the network sandbox 'Cannot connect to host api.github.com' exit 2
- **`cli.check-status`** (covered, P0, `cli`): check-status [-n] [-r] [-j FILE]: 'Archived/Validation status/Synchronization status' lines and a JSON list {org_id, is_archived, validation_status, sync_status}
    - Source: `otterdog/cli.py:574-607`, `otterdog/operations/check_status.py:28-113`
    - Operations: run, plan, exit-code
    - Known bugs: KB-011
    - Notes: warning-only config: is_valid false (warnings 1), in_sync false, counts 0; -r counts per filtered repo (== plan change count); additions/deletions; read-only plan mismatch in_sync false with 0 counts; invalid config: no comparison. Since #963 (02e0e72, after v1.8.0) '--json -' writes the status list to stdout, '[]' when no organization was checked, with the messages on stderr (O-JSON-STDOUT, offline with refused credentials); before, nothing was written for an empty list and a file named '-' otherwise.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`cli.local-plan.dummy-secrets`** (covered, P1, `offline`): local-plan replaces dummy secrets by '&lt;DUMMY&gt;' and diffs secret references ('pass:a' -&gt; 'pass:b'), resolve_secrets off
    - Source: `otterdog/operations/local_plan.py:93-98`, `otterdog/operations/local_plan.py:62-63`
    - Operations: plan, security
    - Known bugs: KB-056
    - Notes: '&lt;DUMMY&gt;' adds (org/repo/env secrets, webhook), dummies unchanged noop, reference change, dummy -&gt; reference; also O-LPLAN-SECRET-REFS. '&lt;DUMMY&gt;' additions, unchanged dummies noop, org/repo/env references diffed ('\~ value = "pass:e2e/a" -&gt; "pass:e2e/b"'); local-plan --update-secrets forces dummies that local-apply skips
- **`cli.apply`** (covered, P0, `cli`): apply -f -n: applies the plan ('Applying changes:', progress, 'Executed plan: A added, C changed, D deleted.' / 'D live resources ignored.')
    - Source: `otterdog/cli.py:674-759`, `otterdog/operations/apply.py:56-237`
    - Operations: add, modify, run
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.apply.delete-resources`** (covered, P0, `cli`): -d/--delete-resources: REMOVE patches are applied only with -d (else skipped)
    - Source: `otterdog/cli.py:718-725`, `otterdog/operations/apply.py:185-193`
    - Operations: remove
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.apply.delete-filter`** (covered, P1, `cli`): apply/local-apply -d --delete-filter SELECTOR (repeatable): only the selected deletions are applied, every other change is skipped and counted (#939, after v1.8.0)
    - Source: `otterdog/cli.py:282-307`, `otterdog/models/__init__.py:237-372`, `otterdog/operations/apply.py:69-86`, `otterdog/operations/apply.py:131-160`, `otterdog/operations/diff_operation.py:215-218`
    - Operations: remove, run, exit-code
    - Notes: offline (local-apply): selectors by key, by repeated types, by a value pattern, by the parent's type and by a type pattern show only the selected removals and 'N other change(s) are skipped, ...' before the prompt; selectors matching nothing warn ('no resource to delete matches the delete filter ...') and end with 'No changes required.'; without -d or with a malformed selector: usage error, exit 2; a renamed repository's variable is deleted under its old name (the rename is skipped). Live (cli.apply.delete-filter, fixed_in 1.9.0): only the DELETE of the selected object is sent, never the repository PATCH of the skipped change nor another DELETE, a renamed repository's variable is deleted under its current name. Not covered: team_sync and org_code_security_configuration selectors (identity provider, code security reads), organization-level deletions live (org_level).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
- **`cli.apply.deletion-hints`** (covered, P1, `offline`): without -d: 'No changes required.' + '&lt;n&gt; resource(s) would be deleted with flag '--delete-resources'.' or 'No resource will be removed, use flag ...'
    - Source: `otterdog/operations/apply.py:125-159`, `otterdog/operations/apply.py:201-210`
    - Operations: remove, run
    - Notes: local-apply with only removals and no -d prints the hint without touching GitHub (sample tests/unit/data/local-apply-no-changes.txt, captured offline). Removal-only: 'No changes required.' + '1 resource(s) would be deleted ...', no prompt, with and without -f; with an addition: 'No resource will be removed, use flag ...' before the prompt
- **`cli.apply.prompt`** (covered, P2, `offline`): apply/local-apply without -f: "Do you want to perform these actions? (Only 'yes' or 'y' ...)"; 'n' -&gt; 'Apply cancelled.' (exit 0); EOF -&gt; exit 2
    - Source: `otterdog/operations/apply.py:154-167`, `otterdog/utils.py:645-650`
    - Operations: prompt, exit-code
    - Notes: offline (local-apply): 'n', 'no' and 'YES' cancel ('Apply cancelled.', exit 0, nothing executed), end of input fails with 'EOF when reading a line' (exit 2); live: local-apply answering 'n' creates nothing (cli.local-apply).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.apply.validation-errors`** (partial, P1, `cli`): apply with validation errors prints 'Planning aborted due to validation errors.' and exits with the error count (#923, 1.8.0; before: 'No changes required.' and exit 0, KB-001)
    - Source: `otterdog/operations/plan.py:121-126`, `otterdog/operations/apply.py:124-135`
    - Operations: validate, exit-code
    - Known bugs: KB-001
    - Notes: KB-001 fixed by #923 (main a196494, 1.8.0): ApplyOperation.handle_finish returns the validation error count (otterdog/operations/apply.py:102-104 at a196494). Both tests run strict from 1.8.0 and xfail before; the offline one runs local-apply, which shares handle_finish (exit 1, no 'No changes required.'); the live one has not run yet.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Suggested: `cli.kb.apply-exit-code`
    - Steps:
        - no new test: both tests assert the fixed behaviour strictly on SUTs from 1.8.0 (branch:main, PR builds) and stay known-bug xfails on release:latest (v1.7.1)
    - Assert:
        - covered once release:latest contains #923 (otterdog 1.8.0): then the default SUT runs them strictly
    - Needs:
        - the otterdog 1.8.0 release
- **`cli.apply.failed-patches`** (covered, P1, `cli`): a failing patch prints 'failed to apply patch: &lt;TYPE&gt; - &lt;header&gt;' and the exit code is the number of failed patches
    - Source: `otterdog/operations/apply.py:185-199`
    - Operations: error, exit-code
    - Notes: Python test (id cli.cmd.apply-failed-patches) instead of the suggested YAML: team_permissions of a missing team make PUT .../teams/&lt;t&gt;/repos 404 after the repo is created (the outline's unknown bypass team is only skipped with a warning by otterdog, get_actor_ids_with_type): exactly 2 'failed to apply patch: ADD - repository[...]', a non-zero exit (otterdog exits with the count, 2; the test does not pin it: KB-034 calls count-as-exit-status a bug), no team access on the failing repos, the other repo applied, plan still pending.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.local-apply`** (covered, P1, `cli`): local-apply [-s SUFFIX] [-f] [-n] [-d]: applies the BASE -&gt; config diff to live GitHub (what the webapp does after a merge)
    - Source: `otterdog/cli.py:762-856`, `otterdog/operations/local_apply.py:27-104`
    - Operations: add, modify, remove, run
    - Known bugs: KB-077
    - Notes: prompt 'n' -&gt; 'Apply cancelled.' nothing created; -f '1 added'; live drift ignored ('No changes required.'); removal only with -d ('1 resource(s) would be deleted ...' then '1 deleted'), guarded by guard_config_change.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`cli.web-login`** (covered, P2, `web_ui`): web-login: opens a headful browser logged in as the bot, waits for input, logs out
    - Source: `otterdog/cli.py:907-914`, `otterdog/operations/web_login.py:32-55`, `otterdog/providers/github/web.py:267-296`
    - Operations: run
    - Notes: Since #938 (main 0f00daa, after v1.8.0) every web login performs the 2FA checkup GitHub may request ('Verify two-factor authentication': another TOTP on /settings/two_factor_checkup) and fails with '2FA checkup failed, TOTP has not been accepted' (LoginGate kind totp, blocking). GitHub requests it once per account and it cannot be forced: only a bot with a pending checkup exercises it.
- **`cli.install-app`** (partial, P2, `web_ui`): install-app -a SLUG: installs an App through the web UI ('app already installed, skipping.' / 'app installed.')
    - Source: `otterdog/cli.py:917-930`, `otterdog/operations/install_app.py:39-74`, `otterdog/providers/github/web.py:298-328`
    - Operations: run
    - Known bugs: KB-002
    - Suggested: `webui.cmd.install-app`
    - Steps:
        - tests/web_ui/test_web_commands.py::test_install_and_uninstall_app runs install-app/uninstall-app: a non-strict XFAIL while KB-002 exists (token-only credentials, no web login)
    - Assert:
        - covered once KB-002 is fixed: the App is installed, then uninstalled, checked through GET /orgs/{org}/installations
    - Needs:
        - a fix of KB-002
        - the web-UI tier (admin web credentials)
- **`cli.uninstall-app`** (partial, P2, `web_ui`): uninstall-app -a SLUG: uninstalls an App through the web UI ('uninstalled app.')
    - Source: `otterdog/cli.py:933-946`, `otterdog/operations/uninstall_app.py:39-72`, `otterdog/providers/github/web.py:330-360`
    - Operations: run
    - Known bugs: KB-002
    - Suggested: `webui.cmd.install-app`
    - Steps:
        - tests/web_ui/test_web_commands.py::test_install_and_uninstall_app runs install-app/uninstall-app: a non-strict XFAIL while KB-002 exists (token-only credentials, no web login)
    - Assert:
        - covered once KB-002 is fixed: the App is installed, then uninstalled, checked through GET /orgs/{org}/installations
    - Needs:
        - a fix of KB-002
        - the web-UI tier (admin web credentials)
- **`cli.review-permissions`** (partial, P2, `web_ui`): review-permissions [-a SLUG] [-g] [-f]: lists requested App permission updates and grants them through the web UI
    - Source: `otterdog/cli.py:949-979`, `otterdog/operations/review_app_permissions.py:47-118`, `otterdog/providers/github/web.py:425-525`
    - Operations: run, prompt
    - Notes: Listing inside the existing web_ui login: every app['&lt;slug&gt;'] request belongs to an installed App, no 'failed to process app installation', nothing approved. Granting (-g / -f) needs a pending permission request.
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
    - Suggested: `UI-REVIEW-PERMISSIONS`
    - Steps:
        - request a new permission for a helper App, run review-permissions -a &lt;slug&gt;, then with -g -f
    - Assert:
        - "app['&lt;slug&gt;'] {" with the requested permission; -g prints 'requested permissions approved.'
    - Needs:
        - web_ui tier
        - available: the probe App of `web_ui.probe_app_slug` (docs/web-ui-testing.md)
- **`cli.install-deps`** (covered, P2, `web_ui`): install-deps: runs 'python -m playwright install firefox' (exits 0 even when it fails)
    - Source: `otterdog/cli.py:1030-1046`
    - Operations: run
    - Known bugs: KB-047
    - Notes: 0 logins: offline sandbox with PLAYWRIGHT_BROWSERS_PATH=tier dir (success, nothing downloaded) / empty dir (failure message, nothing installed).
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
- **`cli.local-apply.code-security-metadata`** (partial, P2, `offline`): local-apply reads the code security configurations of the organization and the configuration of each repository from GitHub before its plan whenever the template defines them (#892): no offline local-apply any more
    - Source: `otterdog/operations/local_apply.py:100-102`, `otterdog/models/github_organization.py:308-319`
    - Operations: run, error
    - Notes: verified offline with main d9dac78: 'Cannot connect to host api.github.com:443' (exit 2) before any plan line; the offline local-apply tests hide newOrgCodeSecurityConfiguration from the vendored template (fixture local_apply_cli) to keep their prompt, credentials and hook checks on every SUT.
    - Suggested: `tests/offline/test_cli_local_apply.py::test_local_apply_reads_code_security_configurations_from_github`
    - Steps:
        - the test skips on SUTs without #892 (release:latest v1.7.1)
    - Assert:
        - covered on the default SUT once a release contains #892
    - Needs:
        - an otterdog release &gt;= 1.8.0
- **`cli.global.stats`** (partial, P2, `offline`): --stats / OTTERDOG_STATS (GitHub API usage report on stderr) and --stats-file / OTTERDOG_STATS_FILE (JSON) of every StdCommand; -v logs one 'github api usage for organization' INFO line per organization (#881)
    - Source: `otterdog/cli.py:135-157`, `otterdog/cli.py:1085`, `otterdog/providers/github/stats/report.py:83-120`
    - Operations: run, config
    - Notes: verified offline with main d9dac78 and v1.7.1: 'INFO github api usage for organization '&lt;id&gt;': no requests' with -v, nothing without; observations replace the summary by &lt;API-USAGE&gt; (request counts vary between live runs; otterdog.output.API_USAGE_RE).
    - Suggested: `tests/offline/test_cli_stats.py::test_stats_report_and_file` in `tests/offline/test_cli_stats.py`
    - Steps:
        - validate --local --stats; validate --local --stats-file &lt;scratch&gt;/stats.json (OTTERDOG_STATS_FILE through extra_env); an unwritable --stats-file
    - Assert:
        - stderr 'GitHub API usage · validate · 1 organization(s)' with REST/GraphQL/Total rows; the JSON has command, outcome 'completed', duration_seconds, total, apis, rate_limits, organizations; 'failed to write github api usage statistics' and an unchanged exit code
    - Needs:
        - available: OtterdogCli.invoke(env=...)

<a id="config"></a>

## otterdog.json, base template and credentials

`config`: 27 features, 15 covered, 6 partial, 6 gaps (weighted 67%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `config.org-identity` | orgs.newOrg('&lt;project_name&gt;', '&lt;github_id&gt;'): project and GitHub id of the organization configuration | offline | free | P0 | covered | offline, live | `O-VAL-OK`, `cli.repo.lifecycle` |
| `config.discovery` | config discovery: -c FILE, else $OTTERDOG_CONFIG_ROOT or the cwd; otterdog.jsonnet wins over otterdog.json; none -&gt; exit 2 | offline | free | P1 | covered | offline | `tests/offline/test_config_loading.py::test_configuration_is_discovered_in_the_config_root`, `tests/offline/test_config_loading.py::test_no_configuration_file_found` |
| `config.jsonnet-config-file` | otterdog.jsonnet configuration files are evaluated (#542); malformed JSON fails with "failed to parse json file '&lt;f&gt;'" | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_jsonnet_configuration_file`, `tests/offline/test_config_loading.py::test_unreadable_configuration_file` |
| `config.local-defaults-override` | .otterdog-defaults.json next to the config file is deep-merged over `defaults` (its values win, #725) | offline | free | P1 | covered | offline | `tests/offline/test_config_loading.py::test_defaults_override_wins_over_the_configuration_file`, `tests/offline/test_config_credentials.py::test_pass_store_dir_from_the_defaults_override` |
| `config.base-template-required` | defaults.jsonnet.base_template is always required (even when every org has its own): "need to define a base template ..." exit 2 | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_default_base_template_is_required` |
| `config.organization-entries` | organizations[]: name and github_id required, per-org config_repo/base_template/credentials, approval_teams/admin_teams as string or list | offline | free | P2 | **partial** | offline | `tests/offline/test_cli_basics.py::test_list_projects_lists_the_offline_organization`, `tests/offline/test_config_loading.py::test_invalid_organization_entry`, `tests/offline/test_config_loading.py::test_organization_entry_variants` |
| `config.archived-organizations` | organizations with archived: true are ignored (not listed, not processed, unknown when named; #463) | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_archived_organizations_are_ignored` |
| `config.config-dir-layout` | working layout: &lt;config_dir\|orgs&gt;/&lt;github_id&gt;/&lt;github_id&gt;.jsonnet, vendor/&lt;template repo&gt;/, import 'vendor/&lt;repo&gt;/&lt;file&gt;' | offline | free | P1 | covered | offline, live | `O-VAL-OK`, `cli.repo.lifecycle` |
| `config.exclude-teams` | defaults.github.exclude_teams (regexes): matching teams are not loaded (import, plan) and configuring one is a validation error | cli | free | P2 | covered | live | `tests/cli/test_org_config.py::test_excluded_teams_are_neither_loaded_nor_configurable` |
| `config.template-url` | base_template URL `https://github.com/<owner>/<repo>#<file>@<ref>`: only github.com, ref mandatory (exit 2 at load) | offline | free | P1 | covered | offline | `tests/offline/test_config_loading.py::test_invalid_template_url`, `tests/offline/test_config_loading.py::test_organization_entry_variants` |
| `config.local-base-template` | base_template as a local path (#917): relative to otterdog.json, linked as vendor/&lt;directory name&gt; on every run (--local included); missing file and a template directory holding the organization are load errors | offline | free | P2 | **partial** | offline | `O-VAL-LOCAL-BASE-TEMPLATE` |
| `config.template-clone` | non-local runs clone the template (unauthenticated) into &lt;config_dir&gt;/templates/&lt;owner&gt;/&lt;repo&gt;/&lt;ref&gt;, pull branch refs, never refresh tags/SHAs, copy into vendor/; a branch ref is reported (#921) and the update holds &lt;template dir&gt;.lock (#927) | cli | free | P1 | covered | offline, live | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `cli.repo.lifecycle`, `tests/offline/test_config_template_cache.py::test_a_branch_ref_is_pulled_and_reported_once`, `tests/offline/test_config_template_cache.py::test_a_tag_or_commit_ref_is_never_refreshed_nor_reported`, `tests/offline/test_config_template_cache.py::test_a_process_waits_for_the_lock_of_the_cached_clone` |
| `config.template-feature-gating` | the template drives what is managed: missing constructors skip a resource type, only template org-settings keys are fetched, hidden '::' fields are unmanaged | cli | free | P2 | **partial** | live | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `tests/cli/test_org_config.py::test_hidden_fields_are_unmanaged` |
| `config.hook.validate-org-settings` | template hook validate-org-settings.py (exec'ed at validation, context.property_equals -&gt; "&lt;h&gt; has '&lt;k&gt;' set to '&lt;v&gt;' but '&lt;r&gt;' is required.") | offline | free | P0 | covered | offline | `tests/offline/test_config_template_hooks.py::test_validate_org_settings_hook`, `tests/offline/test_config_template_hooks.py::test_without_the_hook_the_template_default_validates` |
| `config.hook.validate-team` | template hook validate-team.py (per team at validation) | cli | free | P1 | **gap** | - | - |
| `config.hook.pre-add-object` | template hook pre-add-object-hook.py: runs for every ADD while the apply plan is printed (before the prompt) | offline | free | P1 | covered | offline | `tests/offline/test_config_template_hooks.py::test_pre_add_object_hook_runs_for_every_addition` |
| `config.hook.post-add-objects` | template hook post-add-objects-hook.py: runs once after an apply that added objects (CLI apply/local-apply and the webapp apply comment) | cli | free | P1 | **gap** | - | - |
| `config.hook.subdirectory-template` | templates in a subdirectory are copied without the repo-root hook scripts, so hooks never run (examples/template is such a case) | cli | free | P2 | **gap** | - | - |
| `config.credentials.env` | env credential provider: api_token/username/password/twofa_seed name environment variables (org-level literal names, defaults.env templates) | offline | free | P1 | covered | offline, live | `O-VAL-OK`, `tests/cli/test_smoke.py::test_check_token_permissions`, `tests/offline/test_config_credentials.py::test_env_defaults_templates_resolve_placeholders`, `tests/offline/test_config_credentials.py::test_env_organization_keys_are_literal`, `tests/offline/test_config_credentials.py::test_env_resolves_the_four_keys_without_no_web_ui` |
| `config.credentials.other-providers` | plain, pass, bitwarden and vault providers; 'no credential provider configured' / "unsupported credential provider '&lt;x&gt;'" | offline | free | P2 | **partial** | offline | `tests/offline/test_config_credentials.py::test_plain_and_default_providers`, `tests/offline/test_config_credentials.py::test_pass_provider_with_a_stub_store`, `tests/offline/test_config_credentials.py::test_pass_store_dir_from_the_defaults_override`, `tests/offline/test_config_credentials.py::test_bitwarden_provider_with_a_stub_vault`, `tests/offline/test_config_credentials.py::test_credential_lookups_never_reach_a_shell` |
| `config.credentials.inmemory` | inmemory provider: the webapp runs every operation with the installation token (only_token) | webapp | free | P2 | covered | live | `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_pr_validation.py::test_valid_config_pr` |
| `config.secret-references` | secret values: 'pass:', 'bitwarden:', 'vault:' references resolved at apply; other values used literally with a validation warning; '\*\*\*\*\*\*\*\*' = dummy | cli | free | P1 | **partial** | offline, live | `cli.secrets`, `O-VAL-OK`, `O-VAL-SECRETS`, `cli.org.secret` |
| `config.secret-access-policy` | secret access policy of otterdog.json (#923): defaults.secrets {mode, allowed_references} and organizations[].secrets restrict the provider references of an organization | offline | free | P1 | **partial** | offline | `O-VAL-SECRET-ACCESS-POLICY` |
| `config.http-cache` | otterdog's HTTP cache (.cache/async_http relative to the cwd, always revalidated) must not hide out-of-band changes | cli | free | P1 | covered | live | `tests/cli/test_org_config.py::test_http_cache_does_not_hide_out_of_band_changes` |
| `config.exclude-environments` | defaults.github.exclude_environments (regexes, re.match, case-sensitive): matching live environments that the configuration does not declare are ignored by plan, apply -d, import and show-live (#887) | cli | free | P2 | **gap** | - | - |
| `config.exclude-teams.repository-permissions` | repository permissions of excluded teams (exclude_teams) are ignored unless the repository declares the team (#879) | cli | free | P2 | **gap** | - | - |
| `config.web-timeout` | OTTERDOG_WEB_TIMEOUT (milliseconds, default 10000): timeout of otterdog's web-UI pages (#880) (UI only) | web_ui | free | P2 | **gap** | - | - |

Details:

- **`config.org-identity`** (covered, P0, `offline`): orgs.newOrg('&lt;project_name&gt;', '&lt;github_id&gt;'): project and GitHub id of the organization configuration
    - Source: `otterdog/resources/defaults/otterdog-defaults.libsonnet:475-477`, `otterdog/models/github_organization.py:746-786`
    - Properties (`org`): `project_name`, `github_id`
    - Operations: config
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`config.discovery`** (covered, P1, `offline`): config discovery: -c FILE, else $OTTERDOG_CONFIG_ROOT or the cwd; otterdog.jsonnet wins over otterdog.json; none -&gt; exit 2
    - Source: `otterdog/cli.py:40-74`, `otterdog/config.py:505-523`
    - Operations: config, error
    - Notes: OTTERDOG_CONFIG_ROOT: otterdog.json used, otterdog.jsonnet wins when both exist (project header and list-projects); empty cwd: exit 2 'No configuration file specified ...'; -c of a missing file: click usage error
- **`config.jsonnet-config-file`** (covered, P2, `offline`): otterdog.jsonnet configuration files are evaluated (#542); malformed JSON fails with "failed to parse json file '&lt;f&gt;'"
    - Source: `otterdog/config.py:37-49`, `CHANGELOG.md:356`
    - Operations: config, error
    - Notes: Also 'expected JSON object in file' and a jsonnet evaluation error of otterdog.jsonnet (exit 2)
- **`config.local-defaults-override`** (covered, P1, `offline`): .otterdog-defaults.json next to the config file is deep-merged over `defaults` (its values win, #725)
    - Source: `otterdog/config.py:515-523`, `otterdog/utils.py:728-737`, `CHANGELOG.md:265`
    - Operations: config
    - Notes: config_dir override wins over otterdog.json; #725 pass.password_store_dir from the override reaches the pass provider
- **`config.organization-entries`** (partial, P2, `offline`): organizations[]: name and github_id required, per-org config_repo/base_template/credentials, approval_teams/admin_teams as string or list
    - Source: `otterdog/config.py:123-194`, `otterdog/config.py:349-354`, `otterdog/config.py:418-419`
    - Operations: config, error
    - Notes: error messages (no name, no github_id, null credentials, approval_teams int, admin_teams mapping) and variants (list/string teams, per-org base_template path) covered.
    - Suggested: `cli.config.default-config-repo` in `tests/cli/test_config_repo_cli.py`
    - Steps:
        - live workspace whose organization entry and defaults.github have no config_repo; run fetch-config -f
    - Assert:
        - otterdog reads &lt;org&gt;/.otterdog (the default config_repo); a list approval_teams behaves like the comma-joined string in the webapp approval check (tests/webapp)
    - Needs:
        - target
        - available: WorkspaceLayout(document=...) on a live workspace
- **`config.archived-organizations`** (covered, P2, `offline`): organizations with archived: true are ignored (not listed, not processed, unknown when named; #463)
    - Source: `otterdog/config.py:350`, `CHANGELOG.md:385`
    - Operations: config
    - Notes: Archived entries are not even parsed (one without github_id loads)
- **`config.config-dir-layout`** (covered, P1, `offline`): working layout: &lt;config_dir|orgs&gt;/&lt;github_id&gt;/&lt;github_id&gt;.jsonnet, vendor/&lt;template repo&gt;/, import 'vendor/&lt;repo&gt;/&lt;file&gt;'
    - Source: `otterdog/config.py:341-347`, `otterdog/jsonnet.py:525-574`
    - Operations: config
    - Notes: the harness renders exactly this layout (offline: vendor/template/otterdog-defaults.libsonnet; live: the upstream template path)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`config.exclude-teams`** (covered, P2, `cli`): defaults.github.exclude_teams (regexes): matching teams are not loaded (import, plan) and configuring one is a validation error
    - Source: `otterdog/config.py:426-435`, `otterdog/models/github_organization.py:1318-1324`, `otterdog/models/team.py:99-108`
    - Operations: config, import, validate
    - Notes: exclude_teams from .otterdog-defaults.json of a test workspace: an out-of-band run team is not planned for removal (control plan without the pattern removes it), not imported, and declaring a matching team is a validation error with the exact message.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`config.template-url`** (covered, P1, `offline`): base_template URL `https://github.com/<owner>/<repo>#<file>@<ref>`: only github.com, ref mandatory (exit 2 at load)
    - Source: `otterdog/utils.py:555-582`, `otterdog/jsonnet.py:91-109`
    - Operations: config, error
    - Notes: Also 'failed to parse file from template url' (no fragment)
- **`config.local-base-template`** (partial, P2, `offline`): base_template as a local path (#917): relative to otterdog.json, linked as vendor/&lt;directory name&gt; on every run (--local included); missing file and a template directory holding the organization are load errors
    - Source: `otterdog/config.py:133-136`, `otterdog/jsonnet.py:103-123`, `otterdog/jsonnet.py:169-173`, `otterdog/jsonnet.py:576-599`, `otterdog/utils.py:550-552`
    - Operations: config, error
    - Known bugs: KB-084
    - Notes: sources at main a196494 (1.8.0.dev). Offline (O-VAL-LOCAL-BASE-TEMPLATE, fixed_in 1.8.0): a relative default and a relative organization base_template validate, plan and show without a vendored copy; a missing local file (a vendored copy present) and a template directory holding the organization stop the loading (exit 2); a null organization base_template escapes as a TypeError (KB-084). Not covered: absolute and '\~' paths (the workspace root differs between the host and a container), the template's own imports and validation scripts through the link, the webapp (unchanged, URL templates only).
    - Suggested: `O-LOCAL-BASE-TEMPLATE-PATHS` in `tests/offline/test_config_loading.py`
    - Steps:
        - Python test on a host runtime: base_template set to the absolute path of a copy of the template, then to '\~/&lt;dir&gt;/&lt;file&gt;' with HOME inside the workspace
        - the copy imports a sibling libsonnet and carries a validate-org-settings.py script
    - Assert:
        - validate --local succeeds for both paths and the script runs (its validation error is reported)
    - Needs:
        - offline
        - available: WorkspaceLayout(local_template=...), OtterdogCli.invoke(..., env={'HOME': ...})
- **`config.template-clone`** (covered, P1, `cli`): non-local runs clone the template (unauthenticated) into &lt;config_dir&gt;/templates/&lt;owner&gt;/&lt;repo&gt;/&lt;ref&gt;, pull branch refs, never refresh tags/SHAs, copy into vendor/; a branch ref is reported (#921) and the update holds &lt;template dir&gt;.lock (#927)
    - Source: `otterdog/jsonnet.py:600-644`
    - Operations: config
    - Notes: live commands clone the template pinned to a commit sha (sut/template.py). Offline, O-TEMPLATE-CACHE seeds the cached clone with a bare repository of the workspace as its origin: validate (without --local) pulls a branch ref before the copy to vendor/&lt;repo&gt; (without .git), never refreshes a tag (even one moved in the origin) or a commit sha. Since 1.8.0 a branch ref logs once per process (#921, two organizations: one warning) 'base template '&lt;url&gt;' references the branch '&lt;ref&gt;': every push to it changes the default configuration and the python scripts that otterdog executes from it, reference a tag or a commit SHA instead', and the clone or pull holds an exclusive flock on &lt;template dir&gt;.lock (#927: v1.8.0 validated after 10.4 s while the test held the lock for 10 s, 2.2 s otherwise). The subdirectory copy rule is config.hook.subdirectory-template.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`config.template-feature-gating`** (partial, P2, `cli`): the template drives what is managed: missing constructors skip a resource type, only template org-settings keys are fetched, hidden '::' fields are unmanaged
    - Source: `otterdog/jsonnet.py:190-462`, `otterdog/models/github_organization.py:1262-1290`, `otterdog/models/github_organization.py:1295-1551`
    - Operations: coerce, config
    - Notes: the harness hides max_cache_size_gb with '::' when the cache limit is unavailable and the baseline still converges; a template without constructors is never used. hidden-field part covered: has_wiki:: false is never sent nor diffed, a later plain ':' keeps it hidden, ':::' manages it again.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Suggested: `cli.template.gating` in `tests/cli/test_template.py`
    - Steps:
        - publish a template variant without newEnvSecret/newEnvVariable and without team_permissions in newRepo; create an environment secret and a team permission with the mutator on a run repo
        - plan -n with that template
    - Assert:
        - no env_secret object and no team_permissions diff appear (the types are unmanaged)
    - Needs:
        - target
        - TemplatePublisher with a modified template
- **`config.hook.validate-org-settings`** (covered, P0, `offline`): template hook validate-org-settings.py (exec'ed at validation, context.property_equals -&gt; "&lt;h&gt; has '&lt;k&gt;' set to '&lt;v&gt;' but '&lt;r&gt;' is required.")
    - Source: `otterdog/models/__init__.py:99-105`, `otterdog/models/__init__.py:603-608`, `otterdog/models/organization_settings.py:109-111`
    - Operations: validate
    - Notes: O-TEMPLATE-HOOK-VALIDATE: the SUT template vendored with a validate-org-settings.py requiring default_repository_permission 'none' (sut.template.vendor_template(hooks=...)): the template default 'read' is the error "settings has 'default_repository_permission' set to 'read' but 'none' is required." (validate exit 1, local-plan 'Planning aborted due to validation errors.'), 'none' validates; without the hook file the same configuration validates. Eclipse's otterdog-defaults depends on it; the webapp validation runs it too.
- **`config.hook.validate-team`** (gap, P1, `cli`): template hook validate-team.py (per team at validation)
    - Source: `otterdog/models/team.py:95-97`, `otterdog/models/__init__.py:99-105`
    - Operations: validate
    - Suggested: `cli.template.hook-validate-team` in `tests/cli/test_template.py`
    - Steps:
        - template variant with validate-team.py requiring skip_non_organization_members True; validate a config with orgs.newTeam('&lt;p&gt;-t')
    - Assert:
        - "team[name="&lt;p&gt;-t"] has 'skip_non_organization_members' set to 'False' but 'True' is required."
    - Needs:
        - target
        - teams need the org member list (no offline run)
        - TemplatePublisher with extra hook files at the repo root
- **`config.hook.pre-add-object`** (covered, P1, `offline`): template hook pre-add-object-hook.py: runs for every ADD while the apply plan is printed (before the prompt)
    - Source: `otterdog/operations/apply.py:88-95`
    - Operations: add, run
    - Notes: O-TEMPLATE-HOOK-PRE-ADD: a pre-add-object-hook.py printing the added object runs once per addition (an org variable and a repository, not the changed repository) while local-apply prints its plan, before the prompt (answered 'n'); local-plan never runs it.
- **`config.hook.post-add-objects`** (gap, P1, `cli`): template hook post-add-objects-hook.py: runs once after an apply that added objects (CLI apply/local-apply and the webapp apply comment)
    - Source: `otterdog/operations/apply.py:213-237`
    - Operations: add, run
    - Suggested: `cli.template.hook-post-add` in `tests/cli/test_template.py`
    - Steps:
        - template variant with post-add-objects-hook.py printing the added repository names; apply a config adding a run repository
    - Assert:
        - the apply output contains the hook line after 'Executed plan:'; nothing is printed for an apply without additions
    - Needs:
        - target
        - TemplatePublisher with extra hook files
- **`config.hook.subdirectory-template`** (gap, P2, `cli`): templates in a subdirectory are copied without the repo-root hook scripts, so hooks never run (examples/template is such a case)
    - Source: `otterdog/jsonnet.py:625-644`, `otterdog/models/__init__.py:603-608`
    - Operations: config
    - Suggested: `cli.template.hook-subdir` in `tests/cli/test_template.py`
    - Steps:
        - publish the template under sub/otterdog-defaults.libsonnet with a failing validate-org-settings.py at the repo root; validate
    - Assert:
        - 'Validation succeeded' (the hook is not copied into vendor/&lt;repo&gt;/)
    - Needs:
        - target
        - TemplatePublisher with a subdirectory layout
- **`config.credentials.env`** (covered, P1, `offline`): env credential provider: api_token/username/password/twofa_seed name environment variables (org-level literal names, defaults.env templates)
    - Source: `otterdog/credentials/env_provider.py:29-124`, `otterdog/config.py:255-271`
    - Operations: config, error
    - Notes: defaults.env templates ({github_id}, {org_name} with ' '/'-' -&gt; '_'), org-level literal names win, braces refused, unset variable named; local-apply without -n resolves all four keys
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`config.credentials.other-providers`** (partial, P2, `offline`): plain, pass, bitwarden and vault providers; 'no credential provider configured' / "unsupported credential provider '&lt;x&gt;'"
    - Source: `otterdog/credentials/__init__.py:104-158`, `otterdog/credentials/plain_provider.py:24-58`, `otterdog/credentials/pass_provider.py:28-140`, `otterdog/credentials/bitwarden_provider.py:26-124`, `otterdog/credentials/vault_provider.py:38-308`
    - Operations: config, error
    - Known bugs: KB-086
    - Notes: plain, default provider, unexpected defaults keys, 'unsupported credential provider', 'no credential provider configured', pass (stub CLI) and bitwarden (stub CLI) covered in the SUT image and on host runtimes (the stubs first on the PATH of the otterdog process); since 1.8.0 (GHSA-886p-g538-rcmp, KB-086) their lookups never reach a shell ('pass show &lt;key&gt;', ';' and '$(...)' run nothing) and a key or item id starting with '-' is refused.
    - Suggested: `O-CREDENTIALS-PROVIDERS` in `tests/offline/test_config_credentials.py`
    - Steps:
        - provider vault with defaults.vault {vault_addr: &lt;mock&gt;, vault_token: e2e-dummy, mount_point: e2e} and a Vault KV mock answering &lt;github_id&gt;/github.com/api-token
    - Assert:
        - the token is read from the mock (Validation succeeded); an unauthenticated mock gives 'Failed to authenticate with Vault. Please check your credentials and address' (exit 1)
    - Needs:
        - offline
        - harness: a Vault KV mock reachable from the offline sandbox (unshare -rn has no loopback, --network none containers neither)
- **`config.credentials.inmemory`** (covered, P2, `webapp`): inmemory provider: the webapp runs every operation with the installation token (only_token)
    - Source: `otterdog/credentials/inmemory_provider.py:21-34`, `otterdog/webapp/tasks/__init__.py:314-325`
    - Operations: config
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`config.secret-references`** (partial, P1, `cli`): secret values: 'pass:', 'bitwarden:', 'vault:' references resolved at apply; other values used literally with a validation warning; '\*\*\*\*\*\*\*\*' = dummy
    - Source: `otterdog/config.py:273-293`, `otterdog/models/secret.py:45-64`, `otterdog/models/webhook.py:84-96`
    - Operations: validate, security
    - Known bugs: KB-025, KB-026, KB-057
    - Notes: offline (O-VAL-SECRETS): a 'pass:' reference validates silently, an unknown provider prefix 'foo:e2e/b' warns, several ':' crashed before #923 (KB-025, fixed in 1.8.0); live (cli.org.secret): 'pass:' validates silently (validate-only step), 'foo:e2e/...' warns and is applied literally, '\*\*\*\*\*\*\*\*' is skipped; webhook secrets with an unknown prefix do not warn (KB-057). Not covered: the resolution of references at apply time (pass, bitwarden, vault).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Suggested: `O-SECRET-RESOLUTION` in `tests/offline/test_config_credentials.py`
    - Steps:
        - BASE with org secret &lt;P&gt;_A 'pass:e2e/a', head with 'pass:e2e/b'; a stub 'pass' CLI on PATH logging the requested path (as test_pass_provider_with_a_stub_store)
        - local-apply --local -n answering 'n' (secrets are resolved before the prompt), then the same with 'bitwarden:' and an unknown 'foo:' prefix
    - Assert:
        - the stub was asked for e2e/b exactly once and the value never appears in the output; 'foo:' is not resolved (literal) and warns at validation
    - Needs:
        - offline
        - available: OtterdogCli.invoke(..., env={'PATH': '&lt;stub dir&gt;:&lt;system PATH&gt;'})
- **`config.secret-access-policy`** (partial, P1, `offline`): secret access policy of otterdog.json (#923): defaults.secrets {mode, allowed_references} and organizations[].secrets restrict the provider references of an organization
    - Source: `otterdog/credentials/secret_access_policy.py:1-251`, `otterdog/config.py:167-181`, `otterdog/config.py:233-308`, `otterdog/config.py:357-404`, `otterdog/models/__init__.py:86-97`, `otterdog/models/secret.py:66`, `otterdog/models/webhook.py:99`, `otterdog/operations/diff_operation.py:257`
    - Operations: config, validate, security, error
    - Known bugs: KB-050
    - Notes: sources at main a196494 (1.8.0.dev). Offline (O-VAL-SECRET-ACCESS-POLICY, fixed_in 1.8.0): organization, repository, archived repository and environment secrets and organization and repository webhook secrets outside the patterns are errors (warnings in warn mode); '\*', '\*\*' (at least one segment at the end, zero in the middle), {org_name}/{github_id} from otterdog.json (not the jsonnet newOrg names), bitwarden item ids, '..' segments, a provider without patterns, organization patterns added to the defaults or alone; plain values, dummies and unknown providers unchecked; malformed policies stop the loading (exit 2; the organization name of 'organizations[&lt;name&gt;].secrets' is lost to rich markup, KB-050). Not covered: the apply-time check before a secret is resolved (needs a provider) and the webapp playground validation.
    - Suggested: `O-SECRET-ACCESS-POLICY-APPLY` in `tests/offline/test_config_credentials.py`
    - Steps:
        - defaults.secrets in warn mode and a stub 'pass' CLI on PATH (as test_pass_provider_with_a_stub_store); BASE without the org secret, head with 'pass:bots/e2e-other/token'
        - local-apply --local -n answering 'n' (secrets are resolved before the prompt); in enforce mode validation refuses the same reference first (validation and resolution share SecretAccessPolicy.check)
    - Assert:
        - warn mode prints "organization '&lt;name&gt;' is not allowed to reference secret 'pass:...'" as a warning and the stub is still asked for the path
    - Needs:
        - offline
        - available: OtterdogCli.invoke(..., env={'PATH': '&lt;stub dir&gt;:&lt;system PATH&gt;'})
- **`config.http-cache`** (covered, P1, `cli`): otterdog's HTTP cache (.cache/async_http relative to the cwd, always revalidated) must not hide out-of-band changes
    - Source: `otterdog/cli.py:1064`, `otterdog/providers/github/cache/file.py:20-46`
    - Operations: converge
    - Notes: warm shared cache (cache dir non-empty), out-of-band description change, the next plans (within GitHub's max-age of 60 s) show the change.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`config.exclude-environments`** (gap, P2, `cli`): defaults.github.exclude_environments (regexes, re.match, case-sensitive): matching live environments that the configuration does not declare are ignored by plan, apply -d, import and show-live (#887)
    - Source: `otterdog/config.py:437-447`, `otterdog/utils.py:101-116`, `otterdog/models/github_organization.py:2021-2040`
    - Operations: config, import, plan
    - Notes: not observable offline: local-plan loads both sides from files. Since #887 exclude_teams uses the same per-pattern matching (ExclusionPatterns).
    - Suggested: `tests/cli/test_org_config.py::test_excluded_environments_are_ignored` in `tests/cli/test_org_config.py`
    - Steps:
        - a run repository with an environment '&lt;p&gt;-excluded' created out of band (Mutator), the workspace's .otterdog-defaults.json setting exclude_environments ['^&lt;p&gt;-excluded$']
        - plan and apply -d of the configuration without the environment; then import
    - Assert:
        - no '- remove environment' for it, the environment still exists (oracle environment), the import does not write it; a control plan without the pattern removes it
    - Needs:
        - target
        - available: workspace defaults override (like test_excluded_teams_are_neither_loaded_nor_configurable)
        - an otterdog release &gt;= 1.8.0
- **`config.exclude-teams.repository-permissions`** (gap, P2, `cli`): repository permissions of excluded teams (exclude_teams) are ignored unless the repository declares the team (#879)
    - Source: `otterdog/models/github_organization.py:1921-1937`, `otterdog/models/github_organization.py:2123-2128`
    - Operations: config, plan, import
    - Notes: live only (team permissions are read from GitHub); since #842 an undeclared team with access would otherwise be planned for removal.
    - Suggested: `tests/cli/test_org_config.py::test_excluded_teams_keep_their_repository_access`
    - Steps:
        - an out-of-band run team with push access to a run repository, exclude_teams matching it in the workspace defaults override
    - Assert:
        - the plan of the repository without the team plans nothing; declaring it in team_permissions manages it (change to 'pull' planned and applied)
    - Needs:
        - target
        - identity admin (team access)
        - an otterdog release &gt;= 1.7.0
- **`config.web-timeout`** (gap, P2, `web_ui`): OTTERDOG_WEB_TIMEOUT (milliseconds, default 10000): timeout of otterdog's web-UI pages (#880)
    - Source: `otterdog/providers/github/web.py:41`, `otterdog/providers/github/web.py:558`
    - Operations: config
    - Notes: read when web.py is imported, i.e. by every command that builds a provider (validate --local included): a non-integer value fails them with a bare "invalid literal for int() with base 10" (exit 2, by reading, not run).
    - Suggested: `tests/offline/test_config_credentials.py::test_web_timeout_must_be_an_integer`
    - Steps:
        - validate --local with OTTERDOG_WEB_TIMEOUT=abc (extra_env), then 20000
    - Assert:
        - the observed outcome of the invalid value (today an int() error, exit 2), the valid one validates; the web-UI tier passes the variable to its login
    - Needs:
        - available: OtterdogCli.invoke(env=...)

<a id="validation"></a>

## Validation rules

`validation`: 38 features, 37 covered, 1 partial, 0 gaps (weighted 99%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `validation.plan-gate.org-rulesets` | organization rulesets need settings.plan 'enterprise' ("use of organization rulesets requires an 'enterprise' plan, ...") | offline | free | P0 | covered | offline | `O-VAL-PLAN-GATE`, `O-VAL-PLAN-GATES`, `O-VAL-PLAN-GATES-TEAM`, `O-VAL-PLAN-GATES-ENTERPRISE` |
| `validation.plan-gate.org-secret-private` | org secret visibility 'private' on a free plan is an error ("... which is not available for an organization with free plan.") | offline | free | P0 | covered | offline | `O-VAL-ORGSECRET-PRIVATE-FREE`, `O-VAL-PLAN-GATES`, `O-VAL-PLAN-GATES-TEAM`, `O-VAL-PLAN-GATES-ENTERPRISE` |
| `validation.plan-gate.org-variable-private` | org variable visibility 'private' on a free plan should be an error like org secrets (it is never checked) | offline | free | P1 | covered | offline | `O-VAL-ORGVAR` |
| `validation.plan-gate.org-roles` | organization roles need settings.plan 'enterprise' ("use of organization roles requires an 'enterprise' plan, while this organization is currently on a '&lt;plan&gt;' plan.") | offline | free | P0 | covered | offline | `O-VAL-PLAN-GATES`, `O-VAL-PLAN-GATES-TEAM`, `O-VAL-PLAN-GATES-ENTERPRISE` |
| `validation.plan-gate.ruleset-evaluate` | ruleset enforcement 'evaluate' needs an enterprise plan ("... has 'enforcement' of value 'evaluate' which is only available for an 'enterprise' plan.") | offline | free | P1 | covered | offline | `O-VAL-PLAN-GATES`, `O-VAL-PLAN-GATES-TEAM`, `O-VAL-PLAN-GATES-ENTERPRISE` |
| `validation.plan-gate.private-pages` | members_can_create_private_pages true needs an enterprise plan ("enabling 'members_can_create_private_pages' requires an 'enterprise' plan.") | offline | free | P1 | covered | offline | `O-VAL-PLAN-GATES`, `O-VAL-PLAN-GATES-TEAM`, `O-VAL-PLAN-GATES-ENTERPRISE` |
| `validation.plan-gate.private-repo-wiki` | a private repository with has_wiki on a free plan is a warning ("... requires at least GitHub Team billing, currently using 'free' plan.") | offline | free | P1 | covered | offline | `O-VAL-PLAN-GATES`, `O-VAL-PLAN-GATES-TEAM`, `O-VAL-PLAN-GATES-ENTERPRISE` |
| `validation.org-settings` | organization settings rules: description &lt;= 160 chars, has_discussions needs a source repository '&lt;owner&gt;/&lt;repo&gt;', default_repository_permission none\|read\|write\|admin | offline | free | P1 | covered | offline | `O-VAL-ORG-SETTINGS` |
| `validation.org-workflows` | organization Actions rules: allowed_actions, default_workflow_permissions, fork_pr_approval_policy, enabled_repositories enums; ignored patterns/selection warnings | offline | free | P1 | covered | offline | `O-VAL-ORG-WORKFLOWS` |
| `validation.custom-properties` | custom property rules: value_type enum, select types need 1..200 allowed_values, required needs a default, default within allowed_values, single_select default not a list, values_editable_by | offline | free | P1 | covered | offline | `O-VAL-CUSTOM-PROPERTIES` |
| `validation.org-roles` | org role rules: base_role none\|read\|triage\|write\|maintain\|admin; base_role 'none' with permissions is an error | offline | free | P2 | covered | offline | `O-VAL-ORG-ROLES` |
| `validation.org-rulesets` | org ruleset rules: include/exclude_repo_names patterns must match a repository (warning), protect_repo_names needs names (warning), nested validators | offline | enterprise | P2 | covered | offline, live | `enterprise.kb.org-ruleset-repo-patterns`, `O-VAL-ORG-RULESET-STRICT`, `enterprise.org-ruleset.missing-strict`, `O-VAL-ORG-RULESETS` |
| `validation.teams` | team rules: privacy secret\|visible (message says 'closed'), skip_members with members, skip_non_organization_members with a non-member, exclusion pattern | cli | free | P1 | covered | live | `cli.validate.teams`, `cli.validate.team-non-member`, `cli.kb.team-privacy-message`, `tests/cli/test_org_config.py::test_excluded_teams_are_neither_loaded_nor_configurable` |
| `validation.webhooks` | webhook rules: content_type json\|form, insecure_ssl '0'\|'1', dummy secret info, secret without provider warning (value echoed) | offline | free | P1 | covered | offline | `O-VAL-WEBHOOKS` |
| `validation.secrets` | secret rules (org, repo, env): GITHUB_ prefix error, dummy '\*\*\*\*\*\*\*\*' info, value without provider warning; two ':' crash | offline | free | P1 | covered | offline, live | `cli.secrets`, `O-VAL-OK`, `O-VAL-SECRETS` |
| `validation.org-secrets` | org secret rules: visibility public\|private\|selected; selected_repositories ignored unless 'selected' (warning) | offline | free | P2 | covered | offline | `O-VAL-ORG-SECRETS`, `O-VAL-ORGSECRET-PRIVATE-FREE` |
| `validation.variables` | repository and environment variable rules: names upper case, no GITHUB_ prefix | offline | free | P1 | covered | offline | `O-VAL-VARIABLES` |
| `validation.repo.description-topics` | repository description &lt;= 350 chars, at most 20 topics, topics only [a-z0-9-] | offline | free | P1 | covered | offline, live | `tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors`, `O-VAL-REPO` |
| `validation.repo.forking` | public repo with allow_forking false: warning; private repo with allow_forking while the org disables private forks: error | offline | free | P1 | covered | offline | `O-VAL-REPO` |
| `validation.repo.secret-scanning` | secret_scanning 'disabled' with push protection 'enabled' on a non-archived repository is an error | offline | free | P2 | covered | offline | `O-VAL-REPO` |
| `validation.repo.template-fork` | template_repository and forked_repository are exclusive; forked_repository must be '&lt;owner&gt;/&lt;repo&gt;' ('the the' typo) | offline | free | P2 | covered | offline | `O-VAL-REPO` |
| `validation.repo.custom-properties` | a repository value for an undefined custom property is an error ("defines an unknown custom property with key '&lt;k&gt;'.") | offline | free | P2 | covered | offline | `O-VAL-REPO` |
| `validation.repo.team-permissions` | invalid team_permissions values (model check unreachable: the schema enum fails first, exit 2) | offline | free | P2 | covered | offline | `O-VAL-SCHEMA` |
| `validation.repo.merge-commit-settings` | squash/merge commit title and message enums and allowed combinations | offline | free | P1 | covered | offline | `O-VAL-MERGE-SETTINGS` |
| `validation.repo.pages` | GitHub Pages rules: build type disabled\|legacy\|workflow, legacy source path '/'\|'/docs', github-pages environment info, org site must not be disabled, visibility public\|private rules | offline | free | P1 | covered | offline | `O-VAL-PAGES`, `O-VAL-PAGES-ENTERPRISE`, `O-VAL-COERCED` |
| `validation.repo.code-scanning` | code scanning rules: query suite default\|extended, languages enum, languages need an existing repository (#767) that contains them | cli | free | P2 | covered | offline, live | `regression.code-scanning-new-repo`, `O-VAL-REPO`, `tests/cli/test_org_validation.py::test_code_scanning_languages_must_be_detected` |
| `validation.repo.archived-bpr` | an archived repository with branch protection rules: Info 'is archived but has branch_protection_rules which will be ignored.' | offline | free | P2 | covered | offline | `O-VAL-INFOS` |
| `validation.repo.coerced-rules` | documented repository checks made unreachable by load-time coercion (has_projects, web_commit_signoff_required, has_discussions source, private gh_pages below enterprise) | offline | free | P2 | covered | offline | `O-VAL-COERCED` |
| `validation.repo-workflows` | repository Actions infos (ignored because the org restricts: none, selected, more restricted actions, read permissions, no approvals) and code scanning with Actions disabled | offline | free | P2 | covered | offline | `O-VAL-REPO-WORKFLOWS` |
| `validation.bpr` | branch protection rules: review count required with PRs, dependent settings ignored when their toggle is off (infos/warnings), deployment environments must exist | offline | free | P1 | covered | offline | `O-VAL-BPR` |
| `validation.rulesets` | ruleset rules: target branch\|tag\|push, enforcement active\|disabled\|evaluate, ref patterns per target, deployment environments, nested settings | offline | free | P1 | covered | offline | `O-VAL-RULESETS` |
| `validation.ruleset-nested` | ruleset nested settings: status checks need strict and status_checks (#790), PR review count 0..10, merge queue method MERGE\|SQUASH\|REBASE and non-negative numbers | offline | free | P1 | covered | offline, live | `O-VAL-RULESET-STRICT`, `regression.repo-ruleset-without-strict`, `O-VAL-RULESET-NESTED` |
| `validation.environments` | environment rules: wait_timer 0..43200, deployment_branch_policy all\|protected\|selected, branch_policies ignored unless 'selected', prevent_self_review without reviewers | offline | free | P1 | covered | offline | `O-VAL-ENVIRONMENTS` |
| `validation.schema.unknown-properties` | unknown keys: additionalProperties objects (org, settings, repository, team, webhook, environment, BPR, custom property) only log 'ignoring unknown properties found while validating organization config: ...'; unevaluatedProperties objects (secrets, variables, rulesets, roles, workflows) are blocking (exit 2) | offline | free | P1 | covered | offline | `O-VAL-SCHEMA` |
| `validation.schema.type-errors` | schema type/enum/required violations raise an uncaught jsonschema error (exit 2): wrong types, secrets without value, values_editable_by, multi_select under a '_' property name | offline | free | P2 | covered | offline | `cli.kb.custom-property-underscore`, `O-VAL-SCHEMA` |
| `validation.jsonnet-load` | jsonnet evaluation errors: 'Validation failed' / 'failed to load configuration: failed to evaluate jsonnet file: ...' (exit 1) | offline | free | P0 | covered | offline | `O-VAL-SYNTAX` |
| `validation.code-security` | code security configuration validation: products required by a feature, free plan products of the same status, labeled runner without label, bypass reviewers (team, role, mode), settings without effect, defaults while default_code_security_configurations_disabled, two defaults for one visibility (#892) | offline | free | P1 | **partial** | offline | `O-VAL-CODE-SECURITY` |
| `validation.secret-names-uppercase` | every kind of secret (Actions, Dependabot, Codespaces, environment) needs an uppercase name: a lowercase name is an error since #890 (accepted before, GitHub upper-cases it) | offline | free | P2 | covered | offline | `O-VAL-SECRETS`, `O-VAL-DEPENDABOT-CODESPACES-SECRETS` |

Details:

- **`validation.plan-gate.org-rulesets`** (covered, P0, `offline`): organization rulesets need settings.plan 'enterprise' ("use of organization rulesets requires an 'enterprise' plan, ...")
    - Source: `otterdog/models/github_organization.py:572-580`
    - Operations: validate
    - Known bugs: KB-009
    - Notes: O-VAL-PLAN-GATES-TEAM step org-rulesets-on-team reproduces KB-009 offline (team plan refused, expected to validate).
- **`validation.plan-gate.org-secret-private`** (covered, P0, `offline`): org secret visibility 'private' on a free plan is an error ("... which is not available for an organization with free plan.")
    - Source: `otterdog/models/organization_secret.py:39-40`
    - Operations: validate
    - Notes: verified offline: plan 'team' accepts 'private'. private org secret accepted and planned on team and enterprise.
- **`validation.plan-gate.org-variable-private`** (covered, P1, `offline`): org variable visibility 'private' on a free plan should be an error like org secrets (it is never checked)
    - Source: `otterdog/models/organization_variable.py:43-50`, `otterdog/models/github_organization.py:543-625`
    - Operations: validate
    - Known bugs: KB-028
    - New findings: F-01
    - Notes: step invalid-variables expects the 4 errors (private on free, lowercase, GITHUB_, unknown visibility) + the selected_repositories warning (KB-028 step-level expected failure); valid-variables strict (validate + local-plan 3 adds).
- **`validation.plan-gate.org-roles`** (covered, P0, `offline`): organization roles need settings.plan 'enterprise' ("use of organization roles requires an 'enterprise' plan, while this organization is currently on a '&lt;plan&gt;' plan.")
    - Source: `otterdog/models/github_organization.py:545-555`
    - Operations: validate
    - Notes: free: exact error, exit 1, local-plan 'Planning aborted due to validation errors.'; team: message names 'team'; enterprise: validates and plans '+ add org_role'.
- **`validation.plan-gate.ruleset-evaluate`** (covered, P1, `offline`): ruleset enforcement 'evaluate' needs an enterprise plan ("... has 'enforcement' of value 'evaluate' which is only available for an 'enterprise' plan.")
    - Source: `otterdog/models/ruleset.py:1019-1033`
    - Operations: validate
    - Notes: refused on free and team (exact repo_ruleset header), planned with enforcement 'evaluate' on enterprise.
- **`validation.plan-gate.private-pages`** (covered, P1, `offline`): members_can_create_private_pages true needs an enterprise plan ("enabling 'members_can_create_private_pages' requires an 'enterprise' plan.")
    - Source: `otterdog/models/organization_settings.py:131-135`
    - Operations: validate
    - Known bugs: KB-024
    - Notes: refused on free and team, '\~ members_can_create_private_pages = false -&gt; true' planned on enterprise.
- **`validation.plan-gate.private-repo-wiki`** (covered, P1, `offline`): a private repository with has_wiki on a free plan is a warning ("... requires at least GitHub Team billing, currently using 'free' plan.")
    - Source: `otterdog/models/repository.py:542-548`
    - Operations: validate
    - Notes: every private-repository scenario sets has_wiki: false to avoid it. warning on free (exact), control without warning (public wiki, private has_wiki false); no warning on team/enterprise.
- **`validation.org-settings`** (covered, P1, `offline`): organization settings rules: description &lt;= 160 chars, has_discussions needs a source repository '&lt;owner&gt;/&lt;repo&gt;', default_repository_permission none|read|write|admin
    - Source: `otterdog/models/organization_settings.py:109-157`
    - Operations: validate
    - Notes: description 161 (validate + local-plan abort), discussions without source, source format (with and without discussions), default_repository_permission 'maintain', limits control.
- **`validation.org-workflows`** (covered, P1, `offline`): organization Actions rules: allowed_actions, default_workflow_permissions, fork_pr_approval_policy, enabled_repositories enums; ignored patterns/selection warnings
    - Source: `otterdog/models/workflow_settings.py:123-158`, `otterdog/models/organization_workflow_settings.py:51-69`
    - Operations: validate
    - Known bugs: KB-029, KB-038
    - New findings: F-02, F-11
    - Notes: every enum and both ignored-setting warnings; fork policy asserted order-free (KB-038); KB-029 step-level with a repository.
- **`validation.custom-properties`** (covered, P1, `offline`): custom property rules: value_type enum, select types need 1..200 allowed_values, required needs a default, default within allowed_values, single_select default not a list, values_editable_by
    - Source: `otterdog/models/custom_property.py:53-144`
    - Operations: validate
    - Known bugs: KB-030
    - New findings: F-03
    - Notes: 9 rules incl. non-empty list default and multi_select elements not allowed; limits control (200 values, every value type, both values_editable_by) planned; KB-030 step-level.
- **`validation.org-roles`** (covered, P2, `offline`): org role rules: base_role none|read|triage|write|maintain|admin; base_role 'none' with permissions is an error
    - Source: `otterdog/models/role.py:40-57`
    - Operations: validate
    - Notes: base_role enum, none+permissions, the 6 valid base roles validated and planned (6 adds).
- **`validation.org-rulesets`** (covered, P2, `offline`): org ruleset rules: include/exclude_repo_names patterns must match a repository (warning), protect_repo_names needs names (warning), nested validators
    - Source: `otterdog/models/organization_ruleset.py:51-97`
    - Operations: validate
    - Known bugs: KB-008, KB-023, KB-081
    - Notes: verified offline with variables.plan enterprise: 'nomatch-\*' -&gt; "org_ruleset[name="ors"] has an 'include_repo_names' pattern 'nomatch-\*' that does not match any existing repository"; protect without names -&gt; "... has 'protect_repo_names' set to 'True' but 'include_repo_names' and 'exclude_repo_names' are empty."; required_pull_request count 11 or requires_deployments crash with AttributeError (get_model_header / environments), exit 2. include/exclude no-match and protect warnings, target/enforcement/ref-pattern errors with the org_ruleset header, valid control planned; KB-023 (second pattern), KB-008 (review count 11, fixed by #891 in 1.8.0) and KB-081 (deployment rule: AttributeError 'environments', still on main d9dac78) as step-level expected failures.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`validation.teams`** (covered, P1, `cli`): team rules: privacy secret|visible (message says 'closed'), skip_members with members, skip_non_organization_members with a non-member, exclusion pattern
    - Source: `otterdog/models/team.py:95-136`, `otterdog/models/github_organization.py:520-527`
    - Operations: validate
    - Known bugs: KB-037
    - New findings: F-10
    - Notes: validation lists the org members as soon as teams exist: no offline run (verified: 'Cannot connect to host api.github.com' exit 2). privacy 'closed' refused (stable prefix; the correct value list is the KB-037 step of cli.kb.team-privacy-message), skip_members with members, skip_non_organization_members with the outsider identity, exclusion pattern message.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`validation.webhooks`** (covered, P1, `offline`): webhook rules: content_type json|form, insecure_ssl '0'|'1', dummy secret info, secret without provider warning (value echoed)
    - Source: `otterdog/models/webhook.py:84-115`
    - Operations: validate
    - Known bugs: KB-026, KB-057
    - Notes: content_type/insecure_ssl errors (org+repo headers), provider warning asserted without the value, dummy Info with -v, pass: silent; KB-026 step-level (value must not be echoed).
- **`validation.secrets`** (covered, P1, `offline`): secret rules (org, repo, env): GITHUB_ prefix error, dummy '\*\*\*\*\*\*\*\*' info, value without provider warning; two ':' crash
    - Source: `otterdog/models/secret.py:45-72`, `otterdog/models/environment.py:145-146`, `otterdog/models/repository.py:853-854`
    - Operations: validate, security
    - Known bugs: KB-025, KB-026
    - Notes: verified offline: "repo_secret[name="GITHUB_R"] starts with prefix 'GITHUB_' which is not allowed for secrets."; "env_secret[name="E2E_ES"] has a value 'lit' that does not use a credential provider."; 'pass:a:b' -&gt; 'too many values to unpack (expected 2)' exit 2; lowercase secret names are accepted (GitHub upper-cases them). GITHUB_ prefix (org/repo/env), provider warnings (plain, foo:), pass: silent, dummy infos (-v, 3 levels), lowercase accepted; KB-025 and KB-026 step-level.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`validation.org-secrets`** (covered, P2, `offline`): org secret rules: visibility public|private|selected; selected_repositories ignored unless 'selected' (warning)
    - Source: `otterdog/models/organization_secret.py:36-57`
    - Operations: validate
    - Notes: visibility enum, selected_repositories ignored warning, 'selected' control planned.
- **`validation.variables`** (covered, P1, `offline`): repository and environment variable rules: names upper case, no GITHUB_ prefix
    - Source: `otterdog/models/variable.py:29-42`, `otterdog/models/repository.py:862-863`, `otterdog/models/environment.py:148-149`
    - Operations: validate
    - Notes: 4 errors (repo/env lowercase and GITHUB_) with exact headers; valid names planned (4 adds).
- **`validation.repo.description-topics`** (covered, P1, `offline`): repository description &lt;= 350 chars, at most 20 topics, topics only [a-z0-9-]
    - Source: `otterdog/models/repository.py:515-534`, `otterdog/models/repository.py:877-879`
    - Operations: validate
    - Notes: 351 chars, 21 topics, invalid topics; limits control (350 chars, 20 topics).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`validation.repo.forking`** (covered, P1, `offline`): public repo with allow_forking false: warning; private repo with allow_forking while the org disables private forks: error
    - Source: `otterdog/models/repository.py:536-540`, `otterdog/models/repository.py:567-572`
    - Operations: validate
    - Notes: the template defaults (allow_forking true, org members_can_fork_private_repositories false) make every private repo invalid unless allow_forking: false. public allow_forking false warning, private allow_forking error; control with members_can_fork_private_repositories true.
- **`validation.repo.secret-scanning`** (covered, P2, `offline`): secret_scanning 'disabled' with push protection 'enabled' on a non-archived repository is an error
    - Source: `otterdog/models/repository.py:588-595`
    - Operations: validate
    - Notes: error, archived and both-disabled controls.
- **`validation.repo.template-fork`** (covered, P2, `offline`): template_repository and forked_repository are exclusive; forked_repository must be '&lt;owner&gt;/&lt;repo&gt;' ('the the' typo)
    - Source: `otterdog/models/repository.py:597-601`, `otterdog/models/repository.py:765-774`
    - Operations: validate
    - Notes: exclusive error and 'the the' format error; valid forked_repository control.
- **`validation.repo.custom-properties`** (covered, P2, `offline`): a repository value for an undefined custom property is an error ("defines an unknown custom property with key '&lt;k&gt;'.")
    - Source: `otterdog/models/repository.py:603-610`
    - Operations: validate
    - Notes: unknown key error; defined property value control.
- **`validation.repo.team-permissions`** (covered, P2, `offline`): invalid team_permissions values (model check unreachable: the schema enum fails first, exit 2)
    - Source: `otterdog/models/repository.py:612-620`, `otterdog/resources/schemas/team-permission.json:1-11`
    - Operations: validate
    - Known bugs: KB-032
    - New findings: F-05
    - Notes: KB-032 step-level: 'super' expects the model error (exit 1), 'WRITE' expects success; every lowercase value validates and is planned (strict).
- **`validation.repo.merge-commit-settings`** (covered, P1, `offline`): squash/merge commit title and message enums and allowed combinations
    - Source: `otterdog/models/repository.py:776-848`
    - Operations: validate
    - Known bugs: KB-034
    - New findings: F-07
    - Notes: both pair errors (exit 1), 4 single-value cases (2 errors each), all 7 valid combinations planned; KB-034 step-level (2 errors expected to exit 1).
- **`validation.repo.pages`** (covered, P1, `offline`): GitHub Pages rules: build type disabled|legacy|workflow, legacy source path '/'|'/docs', github-pages environment info, org site must not be disabled, visibility public|private rules
    - Source: `otterdog/models/repository.py:642-731`
    - Operations: validate
    - Notes: build type, legacy path, org site error, github-pages infos (-v, 3), valid sites planned; enterprise: visibility enum, private on public repo, org private pages disabled, valid + visibility change; below enterprise the visibility rules never fire (KB-033 step in O-VAL-COERCED).
- **`validation.repo.code-scanning`** (covered, P2, `cli`): code scanning rules: query suite default|extended, languages enum, languages need an existing repository (#767) that contains them
    - Source: `otterdog/models/repository.py:747-763`, `otterdog/models/repository.py:422-492`, `otterdog/models/github_organization.py:590-623`
    - Operations: validate
    - Known bugs: KB-034, KB-038
    - New findings: F-11
    - Notes: offline (O-VAL-REPO): the query suite enum ('full' refused) and the language enum ('cobol' refused, stable prefix only: set order, KB-038; every supported language validates), with the default setup disabled so that no language detection reads GitHub. Live (cli.validate.code-scanning-languages): once GitHub detected Python, 'go' is refused naming 'Detected languages: Python', python and actions validate, 'cobol' is refused by the enum (stable prefix only: set order, KB-038) and by the detection (2 errors, exit 2: KB-034); new repositories in regression.code-scanning-new-repo.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`validation.repo.archived-bpr`** (covered, P2, `offline`): an archived repository with branch protection rules: Info 'is archived but has branch_protection_rules which will be ignored.'
    - Source: `otterdog/models/repository.py:635-640`
    - Operations: validate, archive
    - Notes: Info hidden without -v (hint), printed with -v (validate and local-plan -v), the archived repository's rule is not planned.
- **`validation.repo.coerced-rules`** (covered, P2, `offline`): documented repository checks made unreachable by load-time coercion (has_projects, web_commit_signoff_required, has_discussions source, private gh_pages below enterprise)
    - Source: `otterdog/models/repository.py:550-579`, `otterdog/models/repository.py:372-407`, `otterdog/models/github_organization.py:784-786`
    - Operations: validate, coerce
    - Known bugs: KB-033
    - New findings: F-06
    - Notes: strict control: show --local prints the coerced repository without has_projects/gh_pages_visibility; the 4 documented messages (has_projects, signoff, discussion source, pages visibility below enterprise) as KB-033 step-level expected failures (flip automatically when fixed).
- **`validation.repo-workflows`** (covered, P2, `offline`): repository Actions infos (ignored because the org restricts: none, selected, more restricted actions, read permissions, no approvals) and code scanning with Actions disabled
    - Source: `otterdog/models/repo_workflow_settings.py:72-146`
    - Operations: validate, coerce
    - Notes: code scanning error (repo and org disabled), all 5 infos with -v, disabled-repo control (0 infos), enums with repo header (KB-038 order-free), patterns warning; KB-029 step-level for an invalid repo allowed_actions.
- **`validation.bpr`** (covered, P1, `offline`): branch protection rules: review count required with PRs, dependent settings ignored when their toggle is off (infos/warnings), deployment environments must exist
    - Source: `otterdog/models/branch_protection_rule.py:88-229`
    - Operations: validate
    - Notes: review count null/-1, 6 PR-dependent warnings + count info, deployment env error + ignored warning, push/lock warnings, 3 ignored-allowance infos, every-toggle-on control planned (3 adds).
- **`validation.rulesets`** (covered, P1, `offline`): ruleset rules: target branch|tag|push, enforcement active|disabled|evaluate, ref patterns per target, deployment environments, nested settings
    - Source: `otterdog/models/ruleset.py:1008-1103`
    - Operations: validate
    - Known bugs: KB-039
    - New findings: F-12
    - Notes: target/enforcement, branch/push/tag ref patterns, deployments error+warning, valid rulesets of every target with bypass actors planned; KB-039 step-level ('#Admin' expected to be refused).
- **`validation.ruleset-nested`** (covered, P1, `offline`): ruleset nested settings: status checks need strict and status_checks (#790), PR review count 0..10, merge queue method MERGE|SQUASH|REBASE and non-negative numbers
    - Source: `otterdog/models/ruleset.py:68-84`, `otterdog/models/ruleset.py:156-164`, `otterdog/models/ruleset.py:268-298`
    - Operations: validate
    - Known bugs: KB-031, KB-055
    - New findings: F-04
    - Notes: review count 11/-1, merge queue FAST/-1/-5, valid limits planned; messages asserted after the header (they name the repository twice: KB-055); KB-031 step-level for missing PR and merge-queue keys.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`validation.environments`** (covered, P1, `offline`): environment rules: wait_timer 0..43200, deployment_branch_policy all|protected|selected, branch_policies ignored unless 'selected', prevent_self_review without reviewers
    - Source: `otterdog/models/environment.py:111-149`
    - Operations: validate
    - Known bugs: KB-036
    - New findings: F-09
    - Notes: wait_timer 43201/-1, 'protected_branches' (KB-036 template comment value) refused, 3 ignored-setting warnings, limits planned.
- **`validation.schema.unknown-properties`** (covered, P1, `offline`): unknown keys: additionalProperties objects (org, settings, repository, team, webhook, environment, BPR, custom property) only log 'ignoring unknown properties found while validating organization config: ...'; unevaluatedProperties objects (secrets, variables, rulesets, roles, workflows) are blocking (exit 2)
    - Source: `otterdog/models/github_organization.py:627-666`, `otterdog/resources/schemas/repository.json:118`, `otterdog/resources/schemas/repo-secret.json:7`, `otterdog/resources/schemas/org-workflow-settings.json:15`
    - Operations: validate, error
    - Notes: 6 additionalProperties objects only warn (validate + local-plan, unknown keys not planned); unevaluatedProperties blocking for repo secret, org variable, ruleset, role, org and repo workflows (exit 2, no summary).
- **`validation.schema.type-errors`** (covered, P2, `offline`): schema type/enum/required violations raise an uncaught jsonschema error (exit 2): wrong types, secrets without value, values_editable_by, multi_select under a '_' property name
    - Source: `otterdog/models/github_organization.py:652-666`, `otterdog/resources/schemas/types.json:32-41`, `otterdog/resources/schemas/custom-property.json:15-20`
    - Operations: validate, error
    - Known bugs: KB-016
    - Notes: verified offline: has_wiki 123 -&gt; "123 is not of type 'boolean'"; a secret without value -&gt; "None is not of type 'string'"; values_editable_by 'anyone' -&gt; 'is not valid under any of the given schemas'; {'e2e_multi': ['a', 'b']} fails while 'e2emulti' passes (KB-016). has_wiki 123 (validate + local-plan), secret without value, values_editable_by 'anyone' (the model message is unreachable like KB-032), KB-016 offline counterpart step-level + control without '_'.
- **`validation.jsonnet-load`** (covered, P0, `offline`): jsonnet evaluation errors: 'Validation failed' / 'failed to load configuration: failed to evaluate jsonnet file: ...' (exit 1)
    - Source: `otterdog/operations/validate.py:66-70`, `otterdog/utils.py:504-512`
    - Operations: validate, error
    - Known bugs: KB-035
    - New findings: F-08
    - Notes: an unknown template function (orgs.newEnvironmentSecret of the docs) fails the same way ('no such field: newEnvironmentSecret')
- **`validation.code-security`** (partial, P1, `offline`): code security configuration validation: products required by a feature, free plan products of the same status, labeled runner without label, bypass reviewers (team, role, mode), settings without effect, defaults while default_code_security_configurations_disabled, two defaults for one visibility (#892)
    - Source: `otterdog/models/organization_code_security_configuration.py:378-445`, `otterdog/models/github_organization.py:484-502`, `otterdog/models/repository.py:622-630`
    - Operations: validate
    - Notes: exact messages from main d9dac78, e.g. "org_code_security_configuration[name=\"&lt;n&gt;\"] has 'code_scanning_default_setup' enabled while 'code_security' is disabled, GitHub requires 'code_security' to be enabled for it." and "... is set as default for new 'public' repositories, while code security configuration '&lt;other&gt;' is already the default for them."; the model's enum and description length checks are unreachable (schema errors at load).
    - Suggested: `O-VAL-CODE-SECURITY`
    - Steps:
        - O-VAL-CODE-SECURITY declares fixed_in 1.8.0: it runs on the 1.8.0 dev builds (branch:main, PR builds) and is skipped on release:latest
    - Assert:
        - covered on the default SUT once a release contains #892
    - Needs:
        - an otterdog release &gt;= 1.8.0
- **`validation.secret-names-uppercase`** (covered, P2, `offline`): every kind of secret (Actions, Dependabot, Codespaces, environment) needs an uppercase name: a lowercase name is an error since #890 (accepted before, GitHub upper-cases it)
    - Source: `otterdog/models/secret.py:74-79`
    - Operations: validate
    - Notes: O-VAL-SECRETS step lowercase-name records only; tests/offline/test_scenarios.py expect_secret_name_case asserts 'Validation succeeded' before #890 and "Error: repo_secret[name=\"&lt;lower&gt;\"] has 'name' of value '&lt;lower&gt;' which is not uppercase, while only uppercase names are allowed for secrets." (1 error, exit 1) since.

<a id="plan-semantics"></a>

## Diff engine and plan semantics

`plan-semantics`: 18 features, 17 covered, 1 partial, 0 gaps (weighted 97%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `plan-semantics.add-block` | a new object is one '+ add &lt;header&gt; {' block of its non-null diff fields; each object nested in a new repository is its own block and counts as an addition | offline | free | P0 | covered | offline, live | `O-LPLAN-ADD`, `cli.repo.lifecycle`, `cli.bpr.public`, `cli.repo.webhook`, `O-LPLAN-RESOURCE-TYPES` |
| `plan-semantics.change-block` | a changed object is one '\~ &lt;header&gt; {' block of 'key = old -&gt; new' lines; 'Plan: ... C to change' counts changed attributes, not objects; unchanged objects are not printed | offline | free | P0 | covered | offline, live | `O-LPLAN-CHANGE`, `cli.repo.lifecycle`, `cli.team`, `O-LPLAN-RESOURCE-TYPES` |
| `plan-semantics.remove-block` | a removed object is one '- remove &lt;header&gt; {' block; a removed repository (or environment) is ONE block, its nested objects are neither listed nor counted | offline | free | P0 | covered | offline, live | `O-LPLAN-REMOVE`, `cli.repo.lifecycle`, `cli.bpr.public`, `O-LPLAN-RESOURCE-TYPES` |
| `plan-semantics.converge` | convergence: a plan right after an apply is a no-op (the live read-back maps onto the configuration for every managed field) | cli | free | P0 | covered | live | `cli.repo.lifecycle`, `cli.team`, `cli.bpr.public`, `cli.ruleset.public`, `cli.environment`, `cli.custom-property`, `cli.repo.webhook`, `cli.secrets`, `tests/cli/test_import.py::test_import_plans_no_change` |
| `plan-semantics.rename-aliases` | repository rename through aliases: one change including '\~ name = "old" -&gt; "new"' instead of remove + add (data kept) | offline | free | P1 | covered | offline, live | `regression.rename-and-modify`, `O-LPLAN-RENAME` |
| `plan-semantics.dict-one-way` | dict fields (team_permissions, repository custom_properties): removing an entry is planned ('- b = "pull"') and sent (custom properties as null); before #842 (1.7.0) a removal alone was invisible (KB-005) | offline | free | P1 | covered | offline, live | `cli.kb.team-permissions-removal`, `O-LPLAN-DICT-ONE-WAY` |
| `plan-semantics.wildcard-keys` | a key ending with '\*' (e.g. a webhook url hiding a token, #84) matches the live object whose key starts with the prefix: no remove + add, the live key is kept | offline | free | P1 | **partial** | offline | `O-LPLAN-WILDCARD`, `tests/webapp/test_merge_apply.py::test_team_and_wildcard_webhook_are_applied` |
| `plan-semantics.coerce.org-signoff` | org web_commit_signoff_required true makes the repository field unmanaged; turning the org setting off re-applies the repository value on every non-archived repository ('\~ web_commit_signoff_required = true -&gt; true') | offline | free | P0 | covered | offline, live | `O-LPLAN-COERCE-SIGNOFF`, `cli.org.signoff` |
| `plan-semantics.coerce.org-projects-pages` | org has_organization_projects false makes repository has_projects unmanaged; gh_pages_visibility is unmanaged below an enterprise plan | offline | free | P1 | covered | offline | `O-LPLAN-COERCE-SIGNOFF`, `O-VAL-PAGES-ENTERPRISE`, `O-VAL-COERCED` |
| `plan-semantics.coerce.discussion-source` | the repository named by the org discussion_source_repository always gets has_discussions true; the org field is ignored while has_discussions is false | offline | free | P2 | covered | offline | `O-LPLAN-COERCE-SIGNOFF` |
| `plan-semantics.coerce.required-custom-properties` | repositories without a value for a required custom property get its default_value; a value equal to the default is dropped from patches | offline | free | P2 | covered | offline | `O-LPLAN-CUSTOM-PROPERTY-DEFAULTS`, `cli.custom-property.required` |
| `plan-semantics.ignored-fields` | fields excluded from diffs by other settings: private repos (secret scanning, push protection, dependabot security updates, PVR), pages disabled (source branch/path, visibility) or 'workflow' (source branch/path), code scanning setup disabled (suite, languages), fork_default_branch_only without forked_repository | offline | free | P1 | covered | offline, live | `regression.private-repo-template-defaults`, `O-LPLAN-IGNORED-FIELDS` |
| `plan-semantics.ignored-org-actions` | Actions fields ignored by diffs: allow_github_owned/verified_creator/action_patterns unless allowed_actions 'selected'; org selected_repositories unless enabled_repositories 'selected'; every org Actions field but enabled_repositories when it is 'none' | offline | free | P1 | covered | offline | `O-LPLAN-IGNORED-FIELDS` |
| `plan-semantics.ignored-archived` | archived repositories: fields GitHub cannot change on archived repos are not diffed while archived stays true; archiving with other changes shows both, applies the other changes first and archives last; BPRs and rulesets of archived repos are skipped | offline | free | P0 | covered | offline | `O-LPLAN-ARCHIVED` |
| `plan-semantics.bpr-dependents-ignored` | branch protection settings depending on a disabled toggle (review settings without requires_pull_request, status checks without requires_status_checks, ...) are ignored by diffs (validation reports them) | offline | free | P1 | covered | offline | `O-LPLAN-BPR-DEPENDENTS` |
| `plan-semantics.env-branch-policies-ignored` | environment branch_policies are ignored unless deployment_branch_policy is 'selected' (warning, no diff) | offline | free | P1 | covered | offline | `O-LPLAN-ENV-POLICIES` |
| `plan-semantics.code-security-disable-only` | default_code_security_configurations_disabled can only disable: true -&gt; false is dropped from the plan | offline | free | P2 | covered | offline | `O-LPLAN-COERCE-SIGNOFF` |
| `plan-semantics.patch-order` | patches are generated and applied in a fixed order: roles, teams, settings (and custom properties), org webhooks, org secrets, org variables, org rulesets, repositories with their nested objects | cli | free | P1 | covered | live | `cli.kb.org-variable-same-apply`, `cli.team`, `cli.kb.org-secret-same-apply`, `cli.org.security-managers` |

Details:

- **`plan-semantics.add-block`** (covered, P0, `offline`): a new object is one '+ add &lt;header&gt; {' block of its non-null diff fields; each object nested in a new repository is its own block and counts as an addition
    - Source: `otterdog/operations/plan.py:60-73`, `otterdog/operations/diff_operation.py:208-232`, `otterdog/models/repository.py:1577-1578`
    - Operations: add, plan
    - Notes: adds org roles, org rulesets, env secrets/variables.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`plan-semantics.change-block`** (covered, P0, `offline`): a changed object is one '\~ &lt;header&gt; {' block of 'key = old -&gt; new' lines; 'Plan: ... C to change' counts changed attributes, not objects; unchanged objects are not printed
    - Source: `otterdog/operations/plan.py:90-119`, `otterdog/models/__init__.py:610-648`
    - Operations: modify, plan
    - Known bugs: KB-063
    - Notes: changes settings, Actions, custom property, role, org ruleset, org secret, org webhook, repo ruleset, env secret/variable (counts per changed key).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`plan-semantics.remove-block`** (covered, P0, `offline`): a removed object is one '- remove &lt;header&gt; {' block; a removed repository (or environment) is ONE block, its nested objects are neither listed nor counted
    - Source: `otterdog/operations/plan.py:75-88`, `otterdog/models/repository.py:1555-1558`, `otterdog/models/__init__.py:1022-1038`
    - Operations: remove, plan
    - Notes: verified offline: removing a repository's only environment (with an env variable) prints one '- remove environment[name="e", repository=r1]' block, 'Plan: 0 to add, 0 to change, 1 to delete.'. removes custom property, role, org ruleset, org secret, repo secret, repo ruleset, BPR, env secret/variable; a removed environment is ONE block.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`plan-semantics.converge`** (covered, P0, `cli`): convergence: a plan right after an apply is a no-op (the live read-back maps onto the configuration for every managed field)
    - Source: `otterdog/models/__init__.py:610-648`, `otterdog/models/github_organization.py:1243-1639`
    - Operations: converge, plan
    - Known bugs: KB-003, KB-020, KB-021
    - Notes: the scenario engine re-plans after every applied step (converge loop); KB-003/KB-020/KB-021 are the known non-converging cases (xfail scenarios)
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`plan-semantics.rename-aliases`** (covered, P1, `offline`): repository rename through aliases: one change including '\~ name = "old" -&gt; "new"' instead of remove + add (data kept)
    - Source: `otterdog/models/repository.py:284-288`, `otterdog/models/__init__.py:1018-1046`, `otterdog/models/repository.py:1982-2069`
    - Operations: rename, plan, modify
    - Known bugs: KB-004
    - Notes: verified offline: base newRepo('old') {description: 'a'}, config newRepo('new') {aliases: ['old'], description: 'b'} -&gt; '\~ repository[name="new"]' with '\~ description = "a" -&gt; "b"' and '\~ name = "old" -&gt; "new"', 'Plan: 0 to add, 2 to change, 0 to delete.'; without the alias: '- remove repository[name="old"]' + '+ add repository[name="new"]' (1 to add, 1 to delete). alias with changes (name line + nested object under the new name, 0/3/0), alias only (0/1/0), no alias (1/0/1), dangling alias (plain add), webhook alias association; KB-004 step-level (url change expected).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`plan-semantics.dict-one-way`** (covered, P1, `offline`): dict fields (team_permissions, repository custom_properties): removing an entry is planned ('- b = "pull"') and sent (custom properties as null); before #842 (1.7.0) a removal alone was invisible (KB-005)
    - Source: `otterdog/utils.py:124-147`, `otterdog/models/__init__.py:610-648`, `otterdog/models/repository.py:1599-1609`
    - Operations: remove, modify, plan
    - Known bugs: KB-005
    - Notes: KB-005 fixed by #842 (1.7.0): the removal-only steps of O-LPLAN-DICT-ONE-WAY and cli.kb.team-permissions-removal are strict from that version on (release:latest included), expected failures before. Verified offline before the fix: team_permissions {a: 'push', b: 'pull'} -&gt; {a: 'push'}: 'Plan: 0 to add, 0 to change, 0 to delete.'; -&gt; {a: 'maintain'}: '\~ team_permissions = {', '\~ a = "push" -&gt; "maintain"', '- b = "pull"', 1 to change; custom_properties {p1: 'x', p2: 'y'} -&gt; {p1: 'x'}: no change. offline complete: removal-only (KB-005 step-level, team_permissions and custom_properties), removal with change, addition.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`plan-semantics.wildcard-keys`** (partial, P1, `offline`): a key ending with '\*' (e.g. a webhook url hiding a token, #84) matches the live object whose key starts with the prefix: no remove + add, the live key is kept
    - Source: `otterdog/models/__init__.py:1018-1033`, `CHANGELOG.md:614`, `CHANGELOG.md:509`
    - Operations: modify, plan, converge
    - Known bugs: KB-068
    - Notes: verified offline: base org webhook 'https://example.org/w?x=1', config 'https://example.org/w\*' -&gt; 'Plan: 0 to add, 0 to change, 0 to delete.' (import masks webhook URLs the same way, cli.import.overwrite-backup-secrets). offline: same hook noop, changed hook under the configured header, repository hook, non-matching prefix remove+add.
    - Suggested: `cli.webhook.wildcard` in `scenarios/cli/webhooks/repo-webhook-wildcard.yaml`
    - Steps:
        - create a repository hook '{{ hook_base }}w?token=x' (apply)
        - plan the same hook declared as '{{ hook_base }}w\*' with the same settings
    - Assert:
        - the second plan is a noop (no add/remove, counts 0/0/0) and the oracle repo_webhook keeps the url with its token; a changed wildcard hook is KB-068 (W-MERGE-TEAM-HOOK)
    - Needs:
        - target
        - available: hook URLs with '\*' and '?' below {{ hook_base }} load (verified with the strict model)
- **`plan-semantics.coerce.org-signoff`** (covered, P0, `offline`): org web_commit_signoff_required true makes the repository field unmanaged; turning the org setting off re-applies the repository value on every non-archived repository ('\~ web_commit_signoff_required = true -&gt; true')
    - Source: `otterdog/models/repository.py:378-379`, `otterdog/models/repository.py:1590-1597`
    - Operations: coerce, modify, plan
    - Notes: offline (O-LPLAN-COERCE-SIGNOFF): turning the org requirement off forces 'true -&gt; true' / 'false -&gt; false' on every non-archived repository (archived ones are not forced), a repository-only change is unmanaged while the org requires signoff, managed control. Live (cli.org.signoff, org_level): the org going false re-applies the run repository's own value ('false -&gt; false') and GitHub reports org false / repo false; back to true the repository is unmanaged again and both steps converge. 2019 of 2578 Eclipse repositories set it to false.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`plan-semantics.coerce.org-projects-pages`** (covered, P1, `offline`): org has_organization_projects false makes repository has_projects unmanaged; gh_pages_visibility is unmanaged below an enterprise plan
    - Source: `otterdog/models/repository.py:375-382`
    - Operations: coerce, plan
    - Known bugs: KB-033
    - New findings: F-06
    - Notes: has_projects unmanaged/managed, gh_pages_visibility unmanaged on free, managed on enterprise (O-VAL-PAGES-ENTERPRISE visibility-managed); the missing warnings are KB-033 (O-VAL-COERCED).
- **`plan-semantics.coerce.discussion-source`** (covered, P2, `offline`): the repository named by the org discussion_source_repository always gets has_discussions true; the org field is ignored while has_discussions is false
    - Source: `otterdog/models/repository.py:399-405`, `otterdog/models/organization_settings.py:97-104`
    - Operations: coerce, plan
    - Notes: verified offline: discussion_source_repository 'o/a' -&gt; 'o/b' with has_discussions false: Plan 0/0/0. source ignored while discussions are off, source repo forced true (noop), enabling (0/3/0), moving the source (1/2/0).
- **`plan-semantics.coerce.required-custom-properties`** (covered, P2, `offline`): repositories without a value for a required custom property get its default_value; a value equal to the default is dropped from patches
    - Source: `otterdog/models/repository.py:387-397`
    - Operations: coerce, plan, converge
    - Known bugs: KB-030
    - New findings: F-03
    - Notes: offline (O-LPLAN-CUSTOM-PROPERTY-DEFAULTS): the default of a required property is added to a new repository, an explicit default is a noop, a new default changes the definition and the repository (0/2/0), a required property without default crashes loading (KB-030, step-level). Live (cli.custom-property.required, org_level): a run repository created without a value converges and reads the default (GitHub fills it), then the next default.
- **`plan-semantics.ignored-fields`** (covered, P1, `offline`): fields excluded from diffs by other settings: private repos (secret scanning, push protection, dependabot security updates, PVR), pages disabled (source branch/path, visibility) or 'workflow' (source branch/path), code scanning setup disabled (suite, languages), fork_default_branch_only without forked_repository
    - Source: `otterdog/models/repository.py:909-942`, `otterdog/models/repository.py:944-967`
    - Operations: coerce, plan, converge
    - Notes: verified offline: a private repository changing secret_scanning 'enabled' -&gt; 'disabled' and push protection: Plan 0/0/0. The private-repository regression converges with the template's security defaults, which only works because they are excluded. private security, pages disabled/workflow, code scanning suite, model-only creation fields (forked_repository, fork_default_branch_only, auto_init) with controls.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`plan-semantics.ignored-org-actions`** (covered, P1, `offline`): Actions fields ignored by diffs: allow_github_owned/verified_creator/action_patterns unless allowed_actions 'selected'; org selected_repositories unless enabled_repositories 'selected'; every org Actions field but enabled_repositories when it is 'none'
    - Source: `otterdog/models/workflow_settings.py:160-165`, `otterdog/models/organization_workflow_settings.py:36-49`
    - Operations: coerce, plan
    - Notes: org patterns/owned/verified/selected repos ignored, everything ignored with enabled 'none', repo patterns ignored (local_only, enabled false, org none); controls with 'selected'.
- **`plan-semantics.ignored-archived`** (covered, P0, `offline`): archived repositories: fields GitHub cannot change on archived repos are not diffed while archived stays true; archiving with other changes shows both, applies the other changes first and archives last; BPRs and rulesets of archived repos are skipped
    - Source: `otterdog/models/repository.py:160-186`, `otterdog/models/repository.py:969-977`, `otterdog/models/repository.py:1625-1642`, `otterdog/models/repository.py:1696-1723`, `otterdog/operations/apply.py:176-183`
    - Operations: archive, plan, modify
    - Known bugs: KB-058
    - Notes: verified offline: archived repo description 'a' -&gt; 'b': Plan 0/0/0; unarchived -&gt; archived with description change: '\~ archived = false -&gt; true', '\~ description = "a" -&gt; "b"', 2 to change. 304 archived repositories in 47 Eclipse orgs. stays archived (read-only fields, BPRs, rulesets: noop), archive with changes (1/2/0 incl. the new BPR), unarchive, new archived repo without its BPR. Topics deliberately not asserted (KB-058, suspected).
- **`plan-semantics.bpr-dependents-ignored`** (covered, P1, `offline`): branch protection settings depending on a disabled toggle (review settings without requires_pull_request, status checks without requires_status_checks, ...) are ignored by diffs (validation reports them)
    - Source: `otterdog/models/branch_protection_rule.py:231-262`
    - Operations: coerce, plan
    - Notes: verified offline: requires_pull_request false, required_approving_review_count 1 -&gt; 3: Info "... has 'requires_pull_request' disabled, but 'required_approving_review_count' is set to '3', setting will be ignored." and Plan 0/0/0. every dependent of the 6 toggles ignored (noop), managed control counted (0/7/0).
- **`plan-semantics.env-branch-policies-ignored`** (covered, P1, `offline`): environment branch_policies are ignored unless deployment_branch_policy is 'selected' (warning, no diff)
    - Source: `otterdog/models/environment.py:151-160`, `otterdog/models/environment.py:137-142`
    - Operations: coerce, plan
    - Notes: verified offline: deployment_branch_policy 'all' (template default) with branch_policies ['a'] -&gt; ['b']: warning "environment[name="e", repository=r1] has 'deployment_branch_policy' set to 'all', but 'branch_policies' is set to '['b']', setting will be ignored." and Plan 0/0/0. 'all' (warning) and 'protected' ignored, 'selected' managed, switch to selected (0/2/0).
- **`plan-semantics.code-security-disable-only`** (covered, P2, `offline`): default_code_security_configurations_disabled can only disable: true -&gt; false is dropped from the plan
    - Source: `otterdog/models/organization_settings.py:305-313`, `otterdog/providers/github/rest/org_client.py:62-66`
    - Operations: coerce, plan
    - Notes: verified offline: true -&gt; false: Plan 0/0/0. true -&gt; false dropped (noop), false -&gt; true planned (0/1/0).
- **`plan-semantics.patch-order`** (covered, P1, `cli`): patches are generated and applied in a fixed order: roles, teams, settings (and custom properties), org webhooks, org secrets, org variables, org rulesets, repositories with their nested objects
    - Source: `otterdog/models/github_organization.py:1033-1053`, `otterdog/operations/apply.py:181-199`
    - Operations: add, plan
    - Known bugs: KB-022
    - Notes: a team granted on a new repository works (teams before repositories, cli.team); an org variable/secret selecting a new repository fails (KB-022). org secret selecting a repo of the same apply (step-level known_bug KB-022, then a strict retry step), teams before settings (security manager team created and assigned in one apply), teams before repositories (cli.team). Roles/org rulesets ordering needs Enterprise.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)

<a id="org-settings"></a>

## Organization settings

`org-settings`: 14 features, 9 covered, 5 partial, 0 gaps (weighted 82%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `org-settings.profile` | organization profile: name, description (&lt;= 160), email, billing_email, company, location, twitter_username, blog (REST PATCH /orgs/{org}) | cli | free | P0 | **partial** | **unverified** | `tests/cli/test_import.py::test_import_plans_no_change`, `cli.org.profile` |
| `org-settings.plan` | settings.plan: read-only, never applied, drives every plan gate (validation reads the configured plan, not GitHub) | cli | free | P0 | covered | offline, live | `cli.plan-mismatch`, `O-VAL-PLAN-GATE`, `O-VAL-ORGSECRET-PRIVATE-FREE` |
| `org-settings.member-privileges` | REST member privileges: default_repository_permission, members_can_create_private/public_repositories, members_can_fork_private_repositories, deploy_keys_enabled_for_repositories, has_organization_projects | cli | free | P1 | covered | **unverified** | `cli.org.member-privileges` |
| `org-settings.pages-creation` | members_can_create_public_pages / members_can_create_private_pages (private: enterprise plan only) | cli | free | P2 | **partial** | **unverified** | `cli.org.member-privileges` |
| `org-settings.web-commit-signoff` | web_commit_signoff_required at org level (257 Eclipse orgs set false; repositories inherit it, see plan-semantics.coerce.org-signoff) | cli | free | P0 | covered | live | `cli.org.signoff` |
| `org-settings.code-security-defaults` | default_code_security_configurations_disabled true removes the org's default code security configurations (disable only) | cli | free | P2 | covered | live | `tests/cli/test_org_code_security.py::test_default_code_security_configurations_are_disabled` |
| `org-settings.security-managers` | security_managers: team slugs assigned the security_manager organization role (added and removed to match) | cli | free | P2 | covered | live | `cli.org.security-managers` |
| `org-settings.web-ui.member-privileges` | web-UI member privileges: members_can_change_repo_visibility, members_can_delete_repositories, members_can_delete_issues, members_can_create_teams, members_can_change_project_visibility, readers_can_create_discussions (UI only) | web_ui | free | P1 | covered | live | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip`, `tests/web_ui/test_web_settings.py::test_web_settings_table_matches_the_sut`, `tests/web_ui/test_web_settings.py::test_import_reads_web_settings` |
| `org-settings.web-ui.default-branch` | web-UI default_branch_name (repository defaults page) (UI only) | web_ui | free | P2 | covered | live | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip`, `tests/web_ui/test_web_settings.py::test_round_trip_changes_the_default_branch_name` |
| `org-settings.web-ui.packages` | web-UI package creation: packages_containers_public, packages_containers_internal (internal: Enterprise Cloud only) (UI only) | web_ui | free | P1 | **partial** | live | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip` |
| `org-settings.web-ui.discussions` | web-UI org discussions: has_discussions with discussion_source_repository '&lt;org&gt;/&lt;repo&gt;' (17 Eclipse orgs) (UI only) | web_ui | free | P1 | **partial** | live | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip` |
| `org-settings.web-ui.two-factor` | two_factor_requirement: read-only web setting (never written; a difference prints the read-only note) (UI only) | web_ui | free | P2 | covered | offline, live | `tests/web_ui/test_web_settings.py::test_web_settings_table_matches_the_sut`, `O-LPLAN-READ-ONLY-KEYS`, `tests/web_ui/test_web_settings.py::test_import_reads_the_two_factor_requirement` |
| `org-settings.web-ui.no-web-ui-skip` | without web credentials (-n, the webapp): web-UI keys are unset before diffing (no plan entry), so web-only changes never apply | webapp | free | P1 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |
| `org-settings.immutable-releases` | immutable_releases_enforced_repositories (all \| none \| selected) and immutable_releases_selected_repositories (compared without case, aliases resolved, duplicates dropped; only with 'selected') (#665) | cli | free | P2 | **partial** | offline | `O-VAL-IMMUTABLE-RELEASES` |

Details:

- **`org-settings.profile`** (partial, P0, `cli`): organization profile: name, description (&lt;= 160), email, billing_email, company, location, twitter_username, blog (REST PATCH /orgs/{org})
    - Source: `otterdog/models/organization_settings.py:54-62`, `otterdog/resources/schemas/settings.json:6-41`, `otterdog/providers/github/__init__.py:149-169`
    - Properties (`org-settings`): `name`, `description`, `email`, `billing_email`, `company`, `location`, `twitter_username`, `blog`
    - Operations: modify, converge, import
    - Known bugs: KB-064, KB-092
    - Notes: name is only planned (step display-name): on an org without a display name GitHub leaves name out of GET /orgs/{org} and otterdog never plans nor applies it (KB-092, the 4 test orgs have none). blog, location, company, email and twitter_username are changed live (':::'), read back by the oracle, converged and restored by a step without fragments (a key going back to null is a '- key = ...' removal line; whether GitHub accepts the JSON null is KB-064). description and billing_email are never changed live by design: the description holds the safety marker (the engine refuses such a plan) and billing_email is owner-only; both are read by the import round trip and the 160-char description rule is the offline validation.org-settings case. description (268 orgs) and name (265) are the most overridden Eclipse org settings.
    - Suggested: `cli.org.profile` in `scenarios/cli/org-settings/profile.yaml`
    - Steps:
        - a test org given a display name once (GitHub settings page, outside otterdog), then the step display-name applies name live like the other profile keys, or otterdog fixed (KB-092)
    - Assert:
        - name changed live, read back by the oracle (GET /orgs/{org} returns name once set), converged and restored
    - Needs:
        - target
        - a test org with a display name, or a SUT with KB-092 fixed
- **`org-settings.plan`** (covered, P0, `cli`): settings.plan: read-only, never applied, drives every plan gate (validation reads the configured plan, not GitHub)
    - Source: `otterdog/models/organization_settings.py:55`, `otterdog/models/organization_settings.py:211-213`, `otterdog/operations/plan.py:112-117`
    - Properties (`org-settings`): `plan`
    - Operations: plan, validate
    - Known bugs: KB-009
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`org-settings.member-privileges`** (covered, P1, `cli`): REST member privileges: default_repository_permission, members_can_create_private/public_repositories, members_can_fork_private_repositories, deploy_keys_enabled_for_repositories, has_organization_projects
    - Source: `otterdog/models/organization_settings.py:65-76`, `otterdog/resources/schemas/settings.json:42-66`
    - Properties (`org-settings`): `default_repository_permission`, `members_can_create_private_repositories`, `members_can_create_public_repositories`, `members_can_fork_private_repositories`, `deploy_keys_enabled_for_repositories`, `has_organization_projects`
    - Operations: modify, converge, coerce
    - Notes: members_can_fork_private_repositories false (template) is what forces allow_forking false on private repositories (validation.repo.forking); has_organization_projects false makes repository has_projects unmanaged. default_repository_permission none, members_can_create_public/private_repositories, deploy_keys_enabled_for_repositories, has_organization_projects toggled and back (oracle GET /orgs on every key, converge); members_can_fork_private_repositories true + a private run repo created with allow_forking false whose allow_forking is turned on in the same apply (settings before repositories).
- **`org-settings.pages-creation`** (partial, P2, `cli`): members_can_create_public_pages / members_can_create_private_pages (private: enterprise plan only)
    - Source: `otterdog/models/organization_settings.py:77-78`, `otterdog/models/organization_settings.py:131-135`
    - Properties (`org-settings`): `members_can_create_public_pages`, `members_can_create_private_pages`
    - Operations: modify, validate, converge
    - Known bugs: KB-024
    - Notes: members_can_create_public_pages false then back to the template's true (oracle, converge). Since #925 (1.8.0) the members_can_create_private_pages value GitHub reports for a plan other than enterprise is left unset: never compared, never imported (KB-024 fixed, cli.import.validate strict from 1.8.0).
    - Suggested: `enterprise.org.private-pages` in `scenarios/enterprise/org-settings/org-private-pages.yaml`
    - Steps:
        - org_level on an Enterprise Cloud target: settings members_can_create_private_pages true, then false
    - Assert:
        - oracle org members_can_create_private_pages per step; converge; on Free the offline plan gate refuses it (validation.plan-gate.private-pages, KB-024)
    - Needs:
        - enterprise target
        - org_level (full baseline reset)
- **`org-settings.web-commit-signoff`** (covered, P0, `cli`): web_commit_signoff_required at org level (257 Eclipse orgs set false; repositories inherit it, see plan-semantics.coerce.org-signoff)
    - Source: `otterdog/models/organization_settings.py:69`, `otterdog/models/repository.py:1590-1597`
    - Properties (`org-settings`): `web_commit_signoff_required`
    - Operations: modify, coerce, converge
    - Notes: org true (template) with a run repo declaring false (coerced, no change); org false re-applies the repo value ('false -&gt; false' line) and GitHub reports org false/repo false; org back to true: no repo change, oracle org true and repo true (GitHub enforcement, unverified live); converge each step.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`org-settings.code-security-defaults`** (covered, P2, `cli`): default_code_security_configurations_disabled true removes the org's default code security configurations (disable only)
    - Source: `otterdog/models/organization_settings.py:70`, `otterdog/providers/github/rest/org_client.py:62-64`, `otterdog/providers/github/rest/org_client.py:912-936`
    - Properties (`org-settings`): `default_code_security_configurations_disabled`
    - Operations: modify, coerce, converge
    - Notes: org_level Python test: an e2e code security configuration made the default for new public repos (Mutator), the baseline plans 'false -&gt; true', the apply leaves GET .../defaults empty (oracle), the plan converges; configuring false while no default exists plans nothing (disable only). Skips when a foreign default exists or the configurations API answers 403/404.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`org-settings.security-managers`** (covered, P2, `cli`): security_managers: team slugs assigned the security_manager organization role (added and removed to match)
    - Source: `otterdog/models/organization_settings.py:87`, `otterdog/providers/github/rest/org_client.py:53-60`, `otterdog/providers/github/rest/org_client.py:214-238`
    - Properties (`org-settings`): `security_managers`
    - Operations: add, remove, converge
    - Notes: run team created and assigned the security_manager role in one apply (teams patched before settings), oracle security_managers contains it; back to the template's [] (the baseline): team kept, role removed (equals [] assumes the baseline has no security manager team).
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`org-settings.web-ui.member-privileges`** (covered, P1, `web_ui`): web-UI member privileges: members_can_change_repo_visibility, members_can_delete_repositories, members_can_delete_issues, members_can_create_teams, members_can_change_project_visibility, readers_can_create_discussions
    - Source: `otterdog/resources/schemas/settings.json:93-112`, `otterdog/resources/schemas/settings.json:129-132`, `otterdog/resources/github-web-settings.jsonnet:1`, `otterdog/providers/github/__init__.py:126-146`
    - Properties (`org-settings`): `members_can_change_repo_visibility`, `members_can_delete_repositories`, `members_can_delete_issues`, `members_can_create_teams`, `members_can_change_project_visibility`, `readers_can_create_discussions`
    - Operations: modify, converge, import
    - Notes: 29 Eclipse orgs set members_can_change_project_visibility, 20 the three repository/teams privileges. readers_can_create_discussions is optional on the page (skipped silently when missing). members_can_change_project_visibility is not REST-readable: with the default reset SUT (the SUT itself) the round trip checks it with the code under test only (report self_checked, BAT-17); the other keys are verified through REST.
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
- **`org-settings.web-ui.default-branch`** (covered, P2, `web_ui`): web-UI default_branch_name (repository defaults page)
    - Source: `otterdog/resources/schemas/settings.json:117-120`
    - Properties (`org-settings`): `default_branch_name`
    - Operations: modify, converge
    - Known bugs: KB-094
    - Notes: the round trip toggles it to e2e-&lt;run&gt;; KB-094: otterdog 1.8.0 reports the web change done while GitHub keeps main (REST default_repository_branch), so its differences go to the round trip's known_bug_failures and webui.kb.default-branch-name asserts them
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
- **`org-settings.web-ui.packages`** (partial, P1, `web_ui`): web-UI package creation: packages_containers_public, packages_containers_internal (internal: Enterprise Cloud only)
    - Source: `otterdog/resources/schemas/settings.json:121-128`
    - Properties (`org-settings`): `packages_containers_public`, `packages_containers_internal`
    - Operations: modify, converge
    - Notes: 44 orgs set packages_containers_internal (42 false), 34 packages_containers_public; the round trip toggles internal only on an enterprise target
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
    - Suggested: `webui.settings.round-trip` in `tests/web_ui/test_web_settings.py`
    - Steps:
        - the round trip toggles these keys with the SUT and reads them back with the trusted reader; REST cannot read them, and with the default reset SUT (auto: the SUT under test, trusted for this tier) the reader runs the SUT's own web code, so a symmetric bug of otterdog's web reader and writer passes (the report lists them as self_checked)
    - Assert:
        - an independent read of the organization settings pages (a Playwright DOM read of the checkbox and select states, harness-side) agrees with the toggled and the restored values
    - Needs:
        - a harness-side Playwright reader of the settings pages, or a reset SUT that differs from the SUT under test
- **`org-settings.web-ui.discussions`** (partial, P1, `web_ui`): web-UI org discussions: has_discussions with discussion_source_repository '&lt;org&gt;/&lt;repo&gt;' (17 Eclipse orgs)
    - Source: `otterdog/resources/schemas/settings.json:133-140`, `otterdog/providers/github/__init__.py:37-38`, `otterdog/models/organization_settings.py:97-104`
    - Properties (`org-settings`): `has_discussions`, `discussion_source_repository`
    - Operations: modify, coerce, converge
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
    - Suggested: `webui.settings.round-trip` in `tests/web_ui/test_web_settings.py`
    - Steps:
        - the round trip toggles these keys with the SUT and reads them back with the trusted reader; REST cannot read them, and with the default reset SUT (auto: the SUT under test, trusted for this tier) the reader runs the SUT's own web code, so a symmetric bug of otterdog's web reader and writer passes (the report lists them as self_checked)
    - Assert:
        - an independent read of the organization settings pages (a Playwright DOM read of the checkbox and select states, harness-side) agrees with the toggled and the restored values
    - Needs:
        - a harness-side Playwright reader of the settings pages, or a reset SUT that differs from the SUT under test
- **`org-settings.web-ui.two-factor`** (covered, P2, `web_ui`): two_factor_requirement: read-only web setting (never written; a difference prints the read-only note)
    - Source: `otterdog/models/organization_settings.py:68`, `otterdog/resources/schemas/settings.json:113-116`
    - Properties (`org-settings`): `two_factor_requirement`
    - Operations: plan, import
    - Known bugs: KB-041
    - Notes: plan side offline: O-LPLAN-READ-ONLY-KEYS step two-factor-requirement prints the read-only Note and plans nothing. Import side in the existing web_ui login: the imported two_factor_requirement must equal REST two_factor_requirement_enabled (KB-041 test, skipped when the live value equals the template default); the web settings table is checked against the SUT. Never toggled (KB-041, the web UI never reads it).
    - Verified on `org-level` with `v1.8.0`: run `tp2p707c` (2026-11-25)
- **`org-settings.web-ui.no-web-ui-skip`** (covered, P1, `webapp`): without web credentials (-n, the webapp): web-UI keys are unset before diffing (no plan entry), so web-only changes never apply
    - Source: `otterdog/models/organization_settings.py:232-240`, `otterdog/providers/github/__init__.py:126-146`, `otterdog/webapp/tasks/apply_changes.py:188-200`
    - Operations: plan, coerce
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`org-settings.immutable-releases`** (partial, P2, `cli`): immutable_releases_enforced_repositories (all | none | selected) and immutable_releases_selected_repositories (compared without case, aliases resolved, duplicates dropped; only with 'selected') (#665)
    - Source: `otterdog/models/organization_settings.py:71-72`, `otterdog/models/organization_settings.py:98-99`, `otterdog/models/organization_settings.py:159-181`, `otterdog/models/github_organization.py:1205-1229`
    - Properties (`org-settings`): `immutable_releases_enforced_repositories`, `immutable_releases_selected_repositories`
    - Operations: modify, validate, plan, converge
    - Known bugs: KB-033
    - Notes: verified offline (main d9dac78 and v1.7.1): the policy enum at load, the warning "'immutable_releases_enforced_repositories' is set to 'all', but 'immutable_releases_selected_repositories' is set to '[...]', setting will be ignored.", '\~ immutable_releases_enforced_repositories = "none" -&gt; "selected"' (2 changes with the list), ['&lt;P&gt;-APP', '&lt;p&gt;-app'] vs ['&lt;p&gt;-app'] plans nothing.
    - Suggested: `cli.org.immutable-releases` in `scenarios/cli/org-settings/immutable-releases.yaml`
    - Steps:
        - org_level: policy 'selected' with a run repository, then 'none' (the baseline)
    - Assert:
        - GET /orgs/{org}/settings/immutable-releases (+ /repositories) as written; converge
    - Needs:
        - target
        - org_level
        - available: check kinds org_immutable_releases, org_immutable_releases_repos (scenario cli.org.immutable-releases, not run live yet)
        - a plan offering immutable releases (402/403 leave it unset)

<a id="org-workflows"></a>

## Organization Actions settings

`org-workflows`: 7 features, 4 covered, 3 partial, 0 gaps (weighted 79%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `org-workflows.enabled-repositories` | org Actions availability: enabled_repositories all \| none \| selected with selected_repositories (repository names -&gt; ids) | cli | free | P1 | covered | live | `cli.org.actions-enabled-repositories` |
| `org-workflows.allowed-actions` | org allowed actions: allowed_actions all \| local_only \| selected with allow_github_owned_actions, allow_verified_creator_actions, allow_action_patterns (selected-actions endpoint) | cli | free | P1 | covered | live | `cli.org.actions-allowed` |
| `org-workflows.default-permissions` | org workflow permissions: default_workflow_permissions read \| write, actions_can_approve_pull_request_reviews (243 Eclipse orgs set it false) | cli | free | P0 | covered | live | `cli.org.workflow-permissions` |
| `org-workflows.fork-pr-approval` | org fork_pr_approval_policy (fork-pr-contributor-approval endpoint; not in the example template's org defaults: unmanaged unless set) | cli | free | P2 | covered | live | `cli.org.actions-allowed` |
| `org-workflows.sha-pinning` | org sha_pinning_required (actions must be pinned to a full-length commit SHA; #946, 1.9.0) | cli | free | P2 | **partial** | offline | `O-VAL-ORG-WORKFLOWS`, `O-LPLAN-IGNORED-FIELDS` |
| `org-workflows.cache-size` | org max_cache_size_gb (Actions cache storage limit; changes are cost-related in the webapp) | cli | free | P2 | **partial** | **unverified** | `cli.org.cache-size` |
| `org-workflows.actions-policies` | organization actions_policies (orgs.newOrgActionsPolicy, GitHub's workflow execution protections): rules allowed_actors and allowed_events (null = not required), workflow and repository-name targeting, enforcement; add, change (PUT of the whole policy), delete with -d, by name (#947) | cli | free | P1 | **partial** | offline | `O-VAL-ACTIONS-POLICIES`, `O-LPLAN-ACTIONS-POLICIES`, `cli.workflows.org-actions-policies` |

Details:

- **`org-workflows.enabled-repositories`** (covered, P1, `cli`): org Actions availability: enabled_repositories all | none | selected with selected_repositories (repository names -&gt; ids)
    - Source: `otterdog/models/organization_workflow_settings.py:33-49`, `otterdog/models/organization_workflow_settings.py:87-97`, `otterdog/providers/github/rest/org_client.py:824-848`
    - Properties (`org-workflows`): `enabled_repositories`, `selected_repositories`
    - Operations: modify, converge, coerce
    - Notes: selected with every configured repository except a run repo (overlay over $._repositories, so baseline repos keep Actions), oracle org_actions selected + selected repositories contain the run repo, validate -v Info for the left-out repo, plan not listing it; back to 'all' (selected list no longer diffed, oracle []); 'none' never applied by design.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`org-workflows.allowed-actions`** (covered, P1, `cli`): org allowed actions: allowed_actions all | local_only | selected with allow_github_owned_actions, allow_verified_creator_actions, allow_action_patterns (selected-actions endpoint)
    - Source: `otterdog/models/workflow_settings.py:43-46`, `otterdog/models/workflow_settings.py:160-171`, `otterdog/providers/github/rest/org_client.py:850-868`
    - Properties (`org-workflows`): `allowed_actions`, `allow_github_owned_actions`, `allow_verified_creator_actions`, `allow_action_patterns`
    - Operations: modify, converge, coerce
    - Known bugs: KB-029
    - New findings: F-02
    - Notes: selected with github-owned true, verified false, patterns ['actions/\*'] (oracle org_actions + org_selected_actions), repo 'all' ignored (Info); back to 'all': selected-action keys not diffed, selected-actions 409 (absent); 'local_only' never applied (would block GitHub-owned actions org-wide). KB-029 (invalid value crash) stays an offline validation case.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`org-workflows.default-permissions`** (covered, P0, `cli`): org workflow permissions: default_workflow_permissions read | write, actions_can_approve_pull_request_reviews (243 Eclipse orgs set it false)
    - Source: `otterdog/models/workflow_settings.py:47-48`, `otterdog/providers/github/rest/org_client.py:870-888`, `otterdog/models/repo_workflow_settings.py:40-70`
    - Properties (`org-workflows`): `default_workflow_permissions`, `actions_can_approve_pull_request_reviews`
    - Operations: modify, converge, coerce
    - Notes: org write + can_approve false (oracle org_workflow_permissions, repo_workflow_permissions write for a run repo), Infos for the coerced repo values; back to read: plan converges although the repo still declares write (no '"read" -&gt; "write"' line), oracle read/true.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`org-workflows.fork-pr-approval`** (covered, P2, `cli`): org fork_pr_approval_policy (fork-pr-contributor-approval endpoint; not in the example template's org defaults: unmanaged unless set)
    - Source: `otterdog/models/workflow_settings.py:49-58`, `otterdog/providers/github/rest/org_client.py:890-910`
    - Properties (`org-workflows`): `fork_pr_approval_policy`
    - Operations: modify, validate, converge
    - Known bugs: KB-038
    - New findings: F-11
    - Notes: all_external_contributors then first_time_contributors (oracle org_fork_pr_approval, converge); invalid value refused at validation (stable prefix only, KB-038). The template has no org-level key, so the baseline never restores it: the scenario ends on GitHub's default first_time_contributors.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`org-workflows.sha-pinning`** (partial, P2, `cli`): org sha_pinning_required (actions must be pinned to a full-length commit SHA; #946, 1.9.0)
    - Source: `otterdog/models/workflow_settings.py:69-75`, `otterdog/providers/github/rest/org_client.py:752-766`
    - Properties (`org-workflows`): `sha_pinning_required`
    - Operations: validate, modify
    - Notes: offline only: the boolean is validated (a string is a load error) and local-plan diffs false -&gt; true; older SUTs refuse the key at load (steps record, SUT_EXPECTATIONS asserts per SUT). No live apply: PUT /orgs/{org}/actions/permissions with the key is unasserted.
    - Suggested: `cli.org.actions.sha-pinning` in `scenarios/cli/workflows/org-actions-sha-pinning.yaml`
    - Steps:
        - org_level: settings.workflows.sha_pinning_required true, a run repository keeping false (validate -v Info: the repository setting is ignored)
        - back to the template's false
    - Assert:
        - apply.api sent PUT /orgs/{org}/actions/permissions, not_sent PUT /repos/{owner}/{repo}/actions/permissions for the coerced repository; oracle org_actions sha_pinning_required true then false; converge
    - Needs:
        - target
        - org_level
        - a reset SUT &gt;= 1.9.0 (the default auto reset SUT of a trusted SUT &gt;= 1.9.0, or --reset-sut): a 1.8.0 reset cannot restore an organization left requiring SHA-pinned actions, which stops its unpinned workflows
- **`org-workflows.cache-size`** (partial, P2, `cli`): org max_cache_size_gb (Actions cache storage limit; changes are cost-related in the webapp)
    - Source: `otterdog/models/workflow_settings.py:60-100`, `otterdog/providers/github/rest/org_client.py:791-822`
    - Properties (`org-workflows`): `max_cache_size_gb`
    - Operations: modify, converge
    - Known bugs: KB-006, KB-007
    - Notes: requires actions_cache_limit: 10 -&gt; 5 -&gt; 10 with the oracle on both the documented /organizations path and otterdog's /orgs path, converge. Skipped where otterdog cannot manage the limit (KB-006 suspected).
    - Suggested: `cli.org.cache-size.documented-path` in `scenarios/cli/workflows/org-cache-size-documented-path.yaml`
    - Steps:
        - on a target where only the documented /organizations/{org}/actions/cache/storage-limit path answers (probe org_cache_storage_limit_documented == 200): set requires actions_cache_limit 5
    - Assert:
        - expected: applied and read back 5 GB; today otterdog calls /orgs/... (KB-006): step-level known_bug
    - Needs:
        - target
        - org_level
        - harness: a capability derived from probes['org_cache_storage_limit_documented']
- **`org-workflows.actions-policies`** (partial, P1, `cli`): organization actions_policies (orgs.newOrgActionsPolicy, GitHub's workflow execution protections): rules allowed_actors and allowed_events (null = not required), workflow and repository-name targeting, enforcement; add, change (PUT of the whole policy), delete with -d, by name (#947)
    - Source: `otterdog/models/actions_policy.py:210-495`, `otterdog/models/organization_actions_policy.py:34-216`, `otterdog/providers/github/rest/org_client.py:1024-1094`, `otterdog/models/github_organization.py:1414-1421`
    - Properties (`org-actions-policy`): `name`, `enforcement`, `include_workflows`, `exclude_workflows`, `allowed_actors`, `allowed_events`, `include_repo_names`, `exclude_repo_names`, `protect_repo_names`
    - Operations: add, modify, remove, validate, plan, converge
    - Notes: sources at main 639eaea (#947, = the PR head c67a7f0). Verified offline with the PR head c67a7f0 (pr:947 in docker): validation errors (exit code = number of errors) for 'evaluate' below enterprise, empty or mixed '\~ALL' workflow targeting, invalid actors (pattern, unknown role, unknown type), warnings for an unknown event, an empty rule, no rule, an empty include_repo_names (the template default), patterns matching no repository, protect_repo_names without patterns; schema errors for an unknown key, an enforcement outside the enum, a rule that is neither a list nor null. local-plan: '+ add org_actions_policy[name="&lt;n&gt;"]', one change per changed attribute, '- remove ...' (1 to delete), roles compared by name ('#2' == '#Maintain'). canonical-diff prints '@dependabot[bot]' as '@dependabot' (the [bot] markup is eaten). The template keys of newOrgActionsPolicy are inventoried since the matrix moved to main fa01483 (2026-11-26).
    - Suggested: `cli.workflows.org-actions-policies` in `scenarios/cli/workflows/org-actions-policies.yaml`
    - Steps:
        - run the scenario on a test organization with branch:main (org_level), the enterprise instance first, then on the first release containing #947
    - Assert:
        - oracle org_actions_policy as written (conditions, rules with the resolved actor ids); covered on the default SUT once a release contains #947 (otterdog &gt;= 1.9.0)
    - Needs:
        - target
        - org_level
        - an otterdog release &gt;= 1.9.0
        - the plans offering Actions policies (unknown: the listing answers 403/404 where unavailable)
        - no foreign organization Actions policy in the test org (the -d step would refuse to delete it)
        - available: kind `org_actions_policy`, janitor kind org_actions_policy

<a id="custom-properties"></a>

## Organization custom properties

`custom-properties`: 6 features, 6 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `custom-properties.definitions` | property definitions: single_select / multi_select / string with allowed_values, description, values_editable_by (add, change allowed values) | cli | free | P2 | covered | offline, live | `cli.custom-property`, `O-LPLAN-ADD` |
| `custom-properties.required-default` | required properties with default_value (repositories without a value get the default; default_value only diffed when required) | cli | free | P2 | covered | **unverified** | `cli.custom-property.required` |
| `custom-properties.true-false` | value_type true_false properties and their repository values | cli | free | P2 | covered | live | `cli.custom-property.flag` |
| `custom-properties.value-type-immutable` | changing value_type aborts planning: "planning aborted: trying to change 'value_type' to '&lt;t&gt;' for custom_property[name="&lt;p&gt;"] which is not supported." (exit 1) | offline | free | P2 | covered | offline | `O-LPLAN-CUSTOM-PROPERTY-DEFAULTS` |
| `custom-properties.remove` | removing a property definition (apply -d) and the values of repositories | cli | free | P2 | covered | live | `cli.custom-property.flag`, `cli.kb.custom-property-definition-with-value` |
| `custom-properties.repository-values` | repository custom_properties values (single_select, multi_select lists, string); removals need another change (KB-005) | cli | free | P2 | covered | live | `cli.custom-property`, `cli.kb.custom-property-underscore`, `cli.custom-property.flag` |

Details:

- **`custom-properties.definitions`** (covered, P2, `cli`): property definitions: single_select / multi_select / string with allowed_values, description, values_editable_by (add, change allowed values)
    - Source: `otterdog/models/custom_property.py:40-47`, `otterdog/models/custom_property.py:169-182`, `otterdog/models/custom_property.py:225-245`
    - Properties (`custom-property`): `name`, `value_type`, `allowed_values`, `description`, `values_editable_by`
    - Operations: add, modify, converge
    - Known bugs: KB-062
    - Notes: 4 definitions in 2 Eclipse orgs. string properties never send allowed_values (#653, regression.653-string-property)
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`custom-properties.required-default`** (covered, P2, `cli`): required properties with default_value (repositories without a value get the default; default_value only diffed when required)
    - Source: `otterdog/models/custom_property.py:146-153`, `otterdog/models/repository.py:387-397`
    - Properties (`custom-property`): `required`, `default_value`
    - Operations: add, coerce, converge
    - Known bugs: KB-030
    - New findings: F-03
    - Notes: required single_select with default 'a': run repo created without a value converges and reads 'a' (oracle), then 'b'; org_level (GitHub sets the default on every repo). KB-030 (required without default) stays offline.
- **`custom-properties.true-false`** (covered, P2, `cli`): value_type true_false properties and their repository values
    - Source: `otterdog/models/custom_property.py:53-60`
    - Properties (`custom-property`): `value_type`
    - Operations: add, converge
    - Notes: value_type true_false definition, repo value 'true' then 'false' (oracle custom_property + repo_custom_properties, converge).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`custom-properties.value-type-immutable`** (covered, P2, `offline`): changing value_type aborts planning: "planning aborted: trying to change 'value_type' to '&lt;t&gt;' for custom_property[name="&lt;p&gt;"] which is not supported." (exit 1)
    - Source: `otterdog/models/custom_property.py:208-212`
    - Operations: modify, error
    - Notes: verified offline with local-plan (string -&gt; true_false). step value-type-change: expect error, exit 1, exact 'planning aborted: ...' message, no Plan line.
- **`custom-properties.remove`** (covered, P2, `cli`): removing a property definition (apply -d) and the values of repositories
    - Source: `otterdog/models/custom_property.py:201-203`, `otterdog/models/custom_property.py:236-238`
    - Operations: remove
    - Known bugs: KB-087
    - Notes: a string property retired in two applies: its repo value first (step remove-value, PATCH .../properties/values with null, no DELETE), then its definition with -d (step remove-definition: '- remove custom_property[...]', counts delete 1, DELETE of the schema, no repository PATCH, oracle definition absent, the other property kept). Both in one apply fail on 1.8.0 (KB-087: the definition is deleted first, the repository PATCH then gets 422 'Unexpected property'), step remove-both of cli.kb.custom-property-definition-with-value.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`custom-properties.repository-values`** (covered, P2, `cli`): repository custom_properties values (single_select, multi_select lists, string); removals need another change (KB-005)
    - Source: `otterdog/models/repository.py:115`, `otterdog/models/repository.py:1599-1609`, `otterdog/providers/github/rest/repo_client.py:957-978`
    - Properties (`repository`): `custom_properties`
    - Operations: add, modify, converge
    - Known bugs: KB-005, KB-016
    - Notes: a removal alone (KB-005 fixed in 1.7.0): step remove-value of cli.custom-property.flag drops one value of a repository, PATCH .../properties/values with null, oracle value gone.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)

<a id="org-roles"></a>

## Custom organization roles

`org-roles`: 2 features, 2 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `org-roles.lifecycle` | custom organization roles: name, description, base_role, permissions (add, change, remove) | enterprise | enterprise | P2 | covered | live | `enterprise.org-role` |
| `org-roles.unused-model-fields` | OrganizationRole.visibility and selected_repositories: model fields without template defaults (unmanaged unless set; GitHub documents neither for organization roles) | offline | enterprise | P2 | covered | offline | `O-SHOW-ROLE-FIELDS` |

Details:

- **`org-roles.lifecycle`** (covered, P2, `enterprise`): custom organization roles: name, description, base_role, permissions (add, change, remove)
    - Source: `otterdog/models/role.py:33-57`, `otterdog/models/organization_role.py:39-67`, `otterdog/providers/github/rest/org_client.py:288-323`
    - Properties (`org-role`): `name`, `description`, `base_role`, `permissions`
    - Operations: add, modify, remove, converge
    - Notes: 0 Eclipse orgs use roles; removal is the guarded cleanup (-d) of the scenario
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`org-roles.unused-model-fields`** (covered, P2, `offline`): OrganizationRole.visibility and selected_repositories: model fields without template defaults (unmanaged unless set; GitHub documents neither for organization roles)
    - Source: `otterdog/models/organization_role.py:29-30`
    - Properties (`org-role`): `visibility`, `selected_repositories`
    - Operations: validate
    - Notes: the role schema refuses visibility and selected_repositories (exit 2); the add block and show list name/description/base_role/permissions only.

<a id="code-security"></a>

## Code security configurations (organization) and their repositories

`code-security`: 3 features, 0 covered, 3 partial, 0 gaps (weighted 50%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `code-security.configuration.lifecycle` | organization code_security_configurations (orgs.newOrgCodeSecurityConfiguration): add, change (one PATCH, default_for_new_repos through PUT .../defaults), delete with -d, by name; foreign organization configurations are deletions (#892) | cli | free | P1 | **partial** | offline | `O-LPLAN-CODE-SECURITY`, `O-VAL-CODE-SECURITY`, `cli.code-security.configuration` |
| `code-security.configuration.settings` | the settings of a code security configuration: GitHub Advanced Security products, dependency graph, Dependabot, code scanning default setup (runner), secret scanning (delegated bypass reviewers), private vulnerability reporting; null = not managed | cli | free | P2 | **partial** | offline | `O-VAL-CODE-SECURITY`, `O-LPLAN-CODE-SECURITY`, `cli.code-security.configuration` |
| `code-security.repository-attachment` | repository code_security_configuration: the configuration attached to the repository (after creation; null keeps the attached one); the security settings it controls are not managed on the repository | cli | free | P1 | **partial** | offline | `O-LPLAN-CODE-SECURITY`, `O-VAL-CODE-SECURITY`, `cli.code-security.configuration` |

Details:

- **`code-security.configuration.lifecycle`** (partial, P1, `cli`): organization code_security_configurations (orgs.newOrgCodeSecurityConfiguration): add, change (one PATCH, default_for_new_repos through PUT .../defaults), delete with -d, by name; foreign organization configurations are deletions (#892)
    - Source: `otterdog/models/organization_code_security_configuration.py:122-199`, `otterdog/models/organization_code_security_configuration.py:613-672`, `otterdog/providers/github/rest/org_client.py:325-519`, `otterdog/models/github_organization.py:1092-1107`
    - Properties (`org-code-security-configuration`): `name`, `description`, `enforcement`, `default_for_new_repos`
    - Operations: add, modify, remove, plan, converge
    - Notes: verified offline with main d9dac78: '+ add org_code_security_configuration[name="&lt;n&gt;"]', '\~ description = "before" -&gt; "after"', '\~ default_for_new_repos = "none" -&gt; "public"', '- remove org_code_security_configuration[name="&lt;n&gt;"]' (1 to delete; applied only with -d). cli.code-security.configuration (fixed_in 1.8.0) creates, changes and deletes one live configuration; it has not run live yet and skips on release:latest.
    - Suggested: `cli.code-security.configuration` in `scenarios/cli/code-security/configuration.yaml`
    - Steps:
        - run the scenario on a test organization with branch:main (org_level), then on the first release containing #892
    - Assert:
        - oracle code_security_configuration and repo_code_security_configuration as written; covered on the default SUT once a release contains #892 (otterdog &gt;= 1.8.0)
    - Needs:
        - target
        - org_level
        - an otterdog release &gt;= 1.8.0
        - no foreign organization code security configuration in the test org (the -d step would refuse to delete it)
- **`code-security.configuration.settings`** (partial, P2, `cli`): the settings of a code security configuration: GitHub Advanced Security products, dependency graph, Dependabot, code scanning default setup (runner), secret scanning (delegated bypass reviewers), private vulnerability reporting; null = not managed
    - Source: `otterdog/models/organization_code_security_configuration.py:122-199`, `otterdog/models/organization_code_security_configuration.py:348-445`
    - Properties (`org-code-security-configuration`): `code_security`, `secret_protection`, `dependency_graph`, `dependency_graph_autosubmit_action`, `dependency_graph_autosubmit_action_labeled_runners`, `dependabot_alerts`, `dependabot_security_updates`, `dependabot_reachability`, `dependabot_delegated_alert_dismissal`, `code_scanning_default_setup`, `code_scanning_default_setup_runner_type`, `code_scanning_default_setup_runner_label`, `code_scanning_allow_advanced`, `code_scanning_delegated_alert_dismissal`, `secret_scanning`, `secret_scanning_push_protection`, `secret_scanning_delegated_bypass`, `secret_scanning_delegated_bypass_reviewers`, `secret_scanning_validity_checks`, `secret_scanning_non_provider_patterns`, `secret_scanning_generic_secrets`, `secret_scanning_generic_secrets_push_protection`, `secret_scanning_delegated_alert_dismissal`, `secret_scanning_extended_metadata`, `private_vulnerability_reporting`
    - Operations: add, modify, validate, plan, converge
    - Notes: offline: the product/feature rules, the free-plan product rule, labeled runner, bypass reviewers (team, role, mode), settings without effect and the schema enum (enabled | disabled | not_set) with exact messages; live: dependabot_alerts and dependabot_security_updates only (both products disabled, valid on every plan).
    - Suggested: `enterprise.code-security.products` in `scenarios/enterprise/code-security/products.yaml`
    - Steps:
        - org_level on a plan with GitHub Advanced Security: a configuration with code_security and secret_protection enabled, code scanning default setup on a labeled runner, secret scanning with delegated bypass reviewers '#RepositoryAdmin'
    - Assert:
        - oracle code_security_configuration matches every managed key (bypass reviewers as ids), converge
    - Needs:
        - target
        - a plan with GitHub Advanced Security (Code Security, Secret Protection)
        - org_level
        - an otterdog release &gt;= 1.8.0
- **`code-security.repository-attachment`** (partial, P1, `cli`): repository code_security_configuration: the configuration attached to the repository (after creation; null keeps the attached one); the security settings it controls are not managed on the repository
    - Source: `otterdog/models/repository.py:122`, `otterdog/models/repository.py:622-630`, `otterdog/models/repository.py:1570`, `otterdog/models/repository.py:1726-1744`, `otterdog/providers/github/rest/repo_client.py:357`
    - Properties (`repository`): `code_security_configuration`
    - Operations: add, modify, coerce, plan, converge
    - Notes: verified offline: '\~ code_security_configuration = null -&gt; "&lt;cfg&gt;"' (1 change); a null reference plans nothing; dependabot_alerts_enabled of an attached repository plans nothing (released setting) while an unattached repository plans '\~ dependabot_alerts_enabled = true -&gt; false'; an added repository with a configuration has no dependabot_alerts_enabled; an undefined (or differently cased) name is an error.
    - Suggested: `cli.code-security.configuration`
    - Steps:
        - attach an EXISTING repository (unarchived first by otterdog when archived) to the configuration in a later step
    - Assert:
        - oracle repo_code_security_configuration names the configuration; the repository security settings controlled by the configuration are not planned
    - Needs:
        - target
        - org_level
        - an otterdog release &gt;= 1.8.0

## Teams

`teams`: 7 features, 5 covered, 0 partial, 2 gaps (weighted 71%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `teams.lifecycle` | teams: add, change description, remove (name == slug for run teams; GitHub's auto-added creator is removed) | cli | free | P1 | covered | live | `cli.team`, `cli.kb.team-permissions-removal` |
| `teams.privacy` | privacy 'visible' (GitHub 'closed') and 'secret' | cli | free | P1 | covered | live | `cli.team`, `cli.team.settings` |
| `teams.members` | team members: exact member list (added and removed), skip_members (members unmanaged), skip_non_organization_members | cli | free | P1 | covered | live | `cli.team`, `cli.team.members`, `cli.validate.team-non-member` |
| `teams.notifications` | team notifications on/off (notification_setting) | cli | free | P2 | covered | live | `cli.team.settings` |
| `teams.repository-permissions` | repository team_permissions {team slug: pull \| triage \| push \| maintain \| admin} (uppercase READ/WRITE accepted by the model) | cli | free | P1 | covered | live | `cli.team`, `cli.kb.team-permissions-removal` |
| `teams.team-sync` | team_sync (orgs.newTeamSync: id, name, description): identity provider groups connected to a team through team synchronization, identified by their id; at most 5 groups, no duplicate id, exclusive with external_group_id, and no members for a team managed by an identity provider (#911, eb8dca5, in v1.8.0) | enterprise | enterprise | P2 | **gap** | - | - |
| `teams.external-group` | external_group_id: the external group of Enterprise Managed Users a team is connected to (GET/PATCH /orgs/{org}/teams/{team_slug}/external-groups), sent as an integer and kept out of the team payload (#911, eb8dca5, in v1.8.0) | enterprise | enterprise | P2 | **gap** | - | - |

Details:

- **`teams.lifecycle`** (covered, P1, `cli`): teams: add, change description, remove (name == slug for run teams; GitHub's auto-added creator is removed)
    - Source: `otterdog/models/team.py:57-69`, `otterdog/models/team.py:351-377`, `otterdog/providers/github/__init__.py:264-280`
    - Properties (`team`): `name`, `description`
    - Operations: add, modify, remove, converge
    - Notes: 81 teams in 18 Eclipse orgs
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`teams.privacy`** (covered, P1, `cli`): privacy 'visible' (GitHub 'closed') and 'secret'
    - Source: `otterdog/models/team.py:209`, `otterdog/models/team.py:228-229`
    - Properties (`team`): `privacy`
    - Operations: add, modify, converge
    - Known bugs: KB-037
    - New findings: F-10
    - Notes: visible -&gt; secret -&gt; visible ('\~ team[...]', oracle privacy closed/secret/closed, converge).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`teams.members`** (covered, P1, `cli`): team members: exact member list (added and removed), skip_members (members unmanaged), skip_non_organization_members
    - Source: `otterdog/models/team.py:63-69`, `otterdog/models/team.py:88-93`, `otterdog/models/team.py:118-136`, `otterdog/models/team.py:193-211`
    - Properties (`team`): `members`, `skip_members`, `skip_non_organization_members`
    - Operations: add, modify, remove, converge
    - Notes: members [author] then [approver] (oracle team_members exact list, team_membership role member / absent), skip_members true with [] keeps the live member (plan noop); skip_non_organization_members validated live with the outsider identity. Needs identities author+approver (outsider for the validation).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`teams.notifications`** (covered, P2, `cli`): team notifications on/off (notification_setting)
    - Source: `otterdog/models/team.py:62`, `otterdog/models/team.py:185-191`, `otterdog/models/team.py:231-235`
    - Properties (`team`): `notifications`
    - Operations: modify, converge
    - Notes: notifications false then true (oracle notification_setting notifications_disabled/enabled, converge).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`teams.repository-permissions`** (covered, P1, `cli`): repository team_permissions {team slug: pull | triage | push | maintain | admin} (uppercase READ/WRITE accepted by the model)
    - Source: `otterdog/models/repository.py:121`, `otterdog/models/repository.py:232-243`, `otterdog/models/repository.py:362-370`, `otterdog/models/github_organization.py:1798-1802`
    - Properties (`repository`): `team_permissions`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-005, KB-032
    - New findings: F-05
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`teams.team-sync`** (gap, P2, `enterprise`): team_sync (orgs.newTeamSync: id, name, description): identity provider groups connected to a team through team synchronization, identified by their id; at most 5 groups, no duplicate id, exclusive with external_group_id, and no members for a team managed by an identity provider (#911, eb8dca5, in v1.8.0)
    - Source: `otterdog/models/team_sync.py:25-36`, `otterdog/models/team.py:95-190`, `otterdog/providers/github/rest/team_client.py:209-238`
    - Properties (`team-sync`): `id`, `name`, `description`
    - Operations: add, modify, remove, validate, converge
    - Notes: GET/PATCH /orgs/{org}/teams/{team_slug}/team-sync/group-mappings need an organization whose enterprise synchronizes teams with an identity provider (Microsoft Entra ID or Okta through SAML SSO); the enterprise instance has no SAML SSO (the web-UI tier needs a login without it). The validation lists the team's members from GitHub (Team.validate), so it does not run offline either.
    - Suggested: `cli.team.identity-provider-validation` in `scenarios/cli/teams/team-identity-provider.yaml`
    - Steps:
        - validate a run team with team_sync and external_group_id both set, with 6 team_sync groups, with two groups of the same id, and with team_sync and members
        - on an organization with team synchronization: add a group, change its name, drop it
    - Assert:
        - validate errors: "has 'team_sync' and 'external_group_id' defined, while only one of them is allowed.", "... while at most 5 groups can be connected to a team.", "has 'team_sync' with duplicate group id '&lt;id&gt;'.", "... its members are managed by the identity provider, but 'members' is set to ..."
        - live: the group mappings of the team as written (GET .../team-sync/group-mappings), a no-op plan after each apply
    - Needs:
        - target
        - an Enterprise Cloud organization with SAML SSO and team synchronization (identity provider groups) for the live steps; the validation steps need only a target (it reads the members)
- **`teams.external-group`** (gap, P2, `enterprise`): external_group_id: the external group of Enterprise Managed Users a team is connected to (GET/PATCH /orgs/{org}/teams/{team_slug}/external-groups), sent as an integer and kept out of the team payload (#911, eb8dca5, in v1.8.0)
    - Source: `otterdog/models/team.py:63-66`, `otterdog/models/team.py:140-150`, `otterdog/providers/github/rest/team_client.py:239-303`
    - Properties (`team`): `external_group_id`
    - Operations: add, modify, remove, validate, converge
    - Notes: external groups exist only in an enterprise with Enterprise Managed Users, out of scope of the harness (README: GitHub Enterprise Server, ghe.com and Enterprise Managed Users are not covered).
    - Suggested: `enterprise.team-external-group` in `scenarios/enterprise/teams/team-external-group.yaml`
    - Steps:
        - a run team connected to an external group of the enterprise, then disconnected (external_group_id null)
    - Assert:
        - GET .../external-groups lists the group, then none; a no-op plan after each apply; validation refuses external_group_id with team_sync (teams.team-sync)
    - Needs:
        - target
        - an Enterprise Managed Users enterprise and one of its external groups (not available)

<a id="webhooks"></a>

## Managed organization and repository webhooks

`webhooks`: 8 features, 6 covered, 2 partial, 0 gaps (weighted 88%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webhooks.org.lifecycle` | organization webhooks keyed by url: add, remove (apply -d), converge; GitHub records a ping delivery | webhooks | free | P0 | covered | offline, live | `tests/webhooks/test_org_hook.py::test_org_webhook_lifecycle`, `O-LPLAN-ADD`, `O-LPLAN-REMOVE` |
| `webhooks.org.settings` | organization webhook settings: events, content_type json \| form, active, insecure_ssl '0' \| '1' (sent as the hook config) | webhooks | free | P1 | covered | live | `tests/webhooks/test_org_hook.py::test_org_webhook_lifecycle`, `tests/webhooks/test_managed_org_hook.py::test_org_webhook_settings_are_updated` |
| `webhooks.org.secret` | organization webhook secret: credential reference resolved at apply; presence changes and differing references are planned; '\*\*\*\*\*\*\*\*' skips the whole webhook; removal warns | webhooks | free | P1 | covered | offline, live | `O-LPLAN-FORCED-WEBHOOKS`, `tests/webhooks/test_managed_org_hook.py::test_org_webhook_secret` |
| `webhooks.org.aliases` | organization webhook aliases (matching by a previous url): the url change itself is never applied (url excluded from diffs) | webhooks | free | P2 | **partial** | **unverified** | `tests/webhooks/test_managed_org_hook.py::test_org_webhook_url_change_through_aliases` |
| `webhooks.repo.lifecycle` | repository webhooks keyed by url: add, remove (nested, apply -d), converge; GitHub records ping deliveries (probe) | cli | free | P0 | covered | offline, live | `cli.repo.webhook`, `O-LPLAN-ADD`, `O-LPLAN-REMOVE` |
| `webhooks.repo.settings` | repository webhook settings: events, content_type, active, insecure_ssl | cli | free | P1 | covered | live | `cli.repo.webhook`, `cli.repo.webhook-settings` |
| `webhooks.repo.secret` | repository webhook secret (same semantics as organization webhooks; forced by --update-webhooks with --update-filter on the url) | cli | free | P1 | covered | offline, live | `O-LPLAN-FORCED-WEBHOOKS`, `cli.repo.webhook-secret` |
| `webhooks.repo.aliases` | repository webhook url change through aliases (documented in docs/userguide/renaming.md) | cli | free | P2 | **partial** | **unverified** | `cli.kb.webhook-url-alias` |

Details:

- **`webhooks.org.lifecycle`** (covered, P0, `webhooks`): organization webhooks keyed by url: add, remove (apply -d), converge; GitHub records a ping delivery
    - Source: `otterdog/models/webhook.py:43-58`, `otterdog/models/organization_webhook.py:24-65`, `otterdog/providers/github/rest/org_client.py:557-610`
    - Properties (`org-webhook`): `url`
    - Operations: add, remove, converge
    - Notes: 94 org webhooks in 87 Eclipse orgs (ci.eclipse.org)
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Verified on `webapp` with `v1.8.0`: run `tp239l54` (2026-11-25)
- **`webhooks.org.settings`** (covered, P1, `webhooks`): organization webhook settings: events, content_type json | form, active, insecure_ssl '0' | '1' (sent as the hook config)
    - Source: `otterdog/models/webhook.py:44-48`, `otterdog/models/webhook.py:117-145`
    - Properties (`org-webhook`): `events`, `content_type`, `active`, `insecure_ssl`
    - Operations: add, modify, converge
    - Notes: H-ORG-HOOK-UPDATE: one '\~ org_webhook' change with exactly {active, content_type, events, insecure_ssl}, oracle after each apply, converge, changed back, guarded -d removal.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Verified on `webapp` with `v1.8.0`: run `tp239l54` (2026-11-25)
- **`webhooks.org.secret`** (covered, P1, `webhooks`): organization webhook secret: credential reference resolved at apply; presence changes and differing references are planned; '\*\*\*\*\*\*\*\*' skips the whole webhook; removal warns
    - Source: `otterdog/models/webhook.py:60-96`, `otterdog/models/webhook.py:147-161`, `otterdog/models/webhook.py:203-227`, `otterdog/operations/plan.py:103-110`
    - Properties (`org-webhook`): `secret`
    - Operations: add, modify, forced-update, security
    - Known bugs: KB-026, KB-064
    - Notes: 114 Eclipse webhooks have a secret, 93 of them the dummy '\*\*\*\*\*\*\*\*' (hooks created out of band: never added nor updated by otterdog). Offline (O-LPLAN-FORCED-WEBHOOKS): presence change, reference diff, removal warning, '&lt;DUMMY&gt;', forced update. Live (H-ORG-HOOK-SECRET): a plain dummy secret (Warning) is reported as '\*\*\*\*\*\*\*\*' and converges (never compared), the ping delivery is signed (X-Hub-Signature-256 sha256=...), --update-webhooks --update-filter &lt;url&gt; forces '!', secret null is planned with 'Warning: removing secret for webhook with url ...' and the next ping is unsigned (whether GitHub accepts the JSON null is KB-064); a '\*\*\*\*\*\*\*\*' hook is skipped (Info, never created).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Verified on `webapp` with `v1.8.0`: run `tp239l54` (2026-11-25)
- **`webhooks.org.aliases`** (partial, P2, `webhooks`): organization webhook aliases (matching by a previous url): the url change itself is never applied (url excluded from diffs)
    - Source: `otterdog/models/webhook.py:51-58`, `otterdog/models/webhook.py:66-71`
    - Properties (`org-webhook`): `aliases`
    - Operations: rename, modify
    - Known bugs: KB-004
    - Notes: verified offline: base org webhook 'https://example.org/a', config 'https://example.org/b' with aliases ['https://example.org/a']: Plan 0/0/0. H-ORG-HOOK-ALIAS asserts the documented in-place url change live: an expected failure while KB-004 exists (known_bug marker).
    - Suggested: `H-ORG-HOOK-ALIAS`
    - Steps:
        - H-ORG-HOOK-ALIAS asserts the documented in-place url change: the url change itself is the expected failure of KB-004 (scoped: only that assertion is tolerated, the hook creation and the cleanup are strict)
    - Assert:
        - covered once KB-004 is fixed: the hook keeps its id, the url changes, the old url disappears and the plan converges
    - Needs:
        - a fix of KB-004
- **`webhooks.repo.lifecycle`** (covered, P0, `cli`): repository webhooks keyed by url: add, remove (nested, apply -d), converge; GitHub records ping deliveries (probe)
    - Source: `otterdog/models/repo_webhook.py:24-31`, `otterdog/providers/github/rest/repo_client.py:385-438`, `otterdog/models/repository.py:1648-1654`
    - Properties (`repo-webhook`): `url`
    - Operations: add, remove, converge
    - Notes: 447 repository webhooks in 85 Eclipse orgs
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`webhooks.repo.settings`** (covered, P1, `cli`): repository webhook settings: events, content_type, active, insecure_ssl
    - Source: `otterdog/models/webhook.py:44-48`, `otterdog/models/webhook.py:117-145`
    - Properties (`repo-webhook`): `events`, `content_type`, `active`, `insecure_ssl`
    - Operations: add, modify, converge
    - Notes: active false, insecure_ssl '1', form, two events and back (oracle each step, converge), nested removal -d.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`webhooks.repo.secret`** (covered, P1, `cli`): repository webhook secret (same semantics as organization webhooks; forced by --update-webhooks with --update-filter on the url)
    - Source: `otterdog/models/webhook.py:60-96`, `otterdog/models/webhook.py:182-201`
    - Properties (`repo-webhook`): `secret`
    - Operations: add, modify, forced-update, security
    - Known bugs: KB-026, KB-057, KB-064
    - Notes: Offline (O-LPLAN-FORCED-WEBHOOKS): forced update with an url filter, removal warning. Live (cli.repo.webhook-secret): a plain secret (Warning) is reported as config.secret '\*\*\*\*\*\*\*\*', a hook without secret has none, a '\*\*\*\*\*\*\*\*' hook is skipped (Info, absent); --update-webhooks with --update-filter forces only the secured hook; secret null is planned with the removal warning and the oracle shows no secret (KB-064); removal with -d. An unknown provider prefix validates silently (KB-057). Delivery signatures are asserted by the organization variant (H-ORG-HOOK-SECRET).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`webhooks.repo.aliases`** (partial, P2, `cli`): repository webhook url change through aliases (documented in docs/userguide/renaming.md)
    - Source: `otterdog/models/webhook.py:51-58`, `otterdog/models/webhook.py:66-71`
    - Properties (`repo-webhook`): `aliases`
    - Operations: rename, modify
    - Known bugs: KB-004
    - Suggested: `cli.kb.webhook-url-alias`
    - Steps:
        - cli.kb.webhook-url-alias asserts the documented in-place url change: the url change itself is the expected failure of KB-004 (scoped: only that assertion is tolerated, the hook creation and the cleanup are strict)
    - Assert:
        - covered once KB-004 is fixed: the hook keeps its id, the url changes, the old url disappears and the plan converges
    - Needs:
        - a fix of KB-004

<a id="secrets-variables"></a>

## Secrets and variables (organization, repository, environment)

`secrets-variables`: 12 features, 10 covered, 2 partial, 0 gaps (weighted 92%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `secrets-variables.org-secret.lifecycle` | organization secrets: add (value encrypted with the org public key), visibility public \| private \| selected (public == GitHub 'all'), remove | cli | free | P0 | covered | offline, live | `O-LPLAN-ADD`, `O-VAL-ORGSECRET-PRIVATE-FREE`, `cli.org.secret`, `cli.org.secret-private` |
| `secrets-variables.org-secret.selected-repositories` | organization secret visibility 'selected' with selected_repositories (names resolved to ids at apply) | cli | free | P1 | covered | live | `cli.org.secret`, `cli.kb.org-secret-same-apply` |
| `secrets-variables.org-variable.lifecycle` | organization variables: add, change value and visibility (public == GitHub 'all'), remove | cli | free | P2 | covered | offline, live | `cli.org.variable`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE` |
| `secrets-variables.org-variable.selected-repositories` | organization variable visibility 'selected' with selected_repositories | cli | free | P2 | covered | live | `cli.org.variable`, `cli.kb.org-variable-same-apply` |
| `secrets-variables.repo-secret.lifecycle` | repository secrets: add (repo public key), forced update with --update-secrets, values never read back | cli | free | P0 | covered | offline, live | `cli.secrets`, `O-LPLAN-ADD`, `O-VAL-OK` |
| `secrets-variables.repo-variable.lifecycle` | repository variables: add, change value, remove; more than 10 variables (pagination) | cli | free | P1 | covered | offline, live | `cli.secrets`, `cli.kb.variables-pagination`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE` |
| `secrets-variables.env-secret.lifecycle` | environment secrets (orgs.newEnvSecret, since 1.4.0): add with the environment public key, forced update, remove | cli | free | P2 | covered | live | `cli.environment.secrets` |
| `secrets-variables.env-variable.lifecycle` | environment variables (orgs.newEnvVariable): add, change, remove; upper-case names | cli | free | P2 | covered | live | `cli.environment.secrets` |
| `secrets-variables.remove` | removing secrets (organization, repository) with apply -d | cli | free | P1 | covered | live | `cli.environment.secrets`, `cli.org.secret` |
| `secrets-variables.plain-value-warning` | secret values that are not credential references validate with the warning "has a value '&lt;v&gt;' that does not use a credential provider." (the value is echoed) | cli | free | P1 | covered | live | `cli.secrets` |
| `secrets-variables.org-dependabot-codespaces-secrets` | organization dependabot_secrets and codespaces_secrets (orgs.newOrgDependabotSecret, newOrgCodespacesSecret): like Actions secrets (visibility public == 'all' \| private \| selected, names, values), private allowed on every plan (#890) | cli | free | P1 | **partial** | offline, live | `O-VAL-DEPENDABOT-CODESPACES-SECRETS`, `O-LPLAN-DEPENDABOT-CODESPACES-SECRETS`, `cli.secrets.dependabot-codespaces` |
| `secrets-variables.repo-dependabot-codespaces-secrets` | repository dependabot_secrets and codespaces_secrets (orgs.newRepoDependabotSecret, newRepoCodespacesSecret): name and value like repository Actions secrets (#890) | cli | free | P1 | **partial** | offline, live | `O-VAL-DEPENDABOT-CODESPACES-SECRETS`, `O-LPLAN-DEPENDABOT-CODESPACES-SECRETS`, `cli.secrets.dependabot-codespaces` |

Details:

- **`secrets-variables.org-secret.lifecycle`** (covered, P0, `cli`): organization secrets: add (value encrypted with the org public key), visibility public | private | selected (public == GitHub 'all'), remove
    - Source: `otterdog/models/organization_secret.py:27-137`, `otterdog/providers/github/rest/secret_client.py:111-218`
    - Properties (`org-secret`): `name`, `value`, `visibility`
    - Operations: add, modify, remove, converge, security
    - Known bugs: KB-025
    - Notes: public (GitHub 'all') add, selected, forced update (--update-secrets with filter), removal -d, dummy '\*\*\*\*\*\*\*\*' skipped; 'private' on Team/Enterprise (cli.org.secret-private, min_plan team; Free: offline gate).
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`secrets-variables.org-secret.selected-repositories`** (covered, P1, `cli`): organization secret visibility 'selected' with selected_repositories (names resolved to ids at apply)
    - Source: `otterdog/models/organization_secret.py:59-124`, `otterdog/providers/github/rest/secret_client.py:140-152`
    - Properties (`org-secret`): `selected_repositories`
    - Operations: add, modify, converge
    - Known bugs: KB-022
    - Notes: selected [sel] then [sel, sel2] (oracle org_secret_repos exact / $unordered, converge); the same-apply case is the KB-022 step of cli.kb.org-secret-same-apply.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`secrets-variables.org-variable.lifecycle`** (covered, P2, `cli`): organization variables: add, change value and visibility (public == GitHub 'all'), remove
    - Source: `otterdog/models/organization_variable.py:27-122`, `otterdog/providers/github/rest/org_client.py:622-709`
    - Properties (`org-variable`): `name`, `value`, `visibility`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-003, KB-028
    - New findings: F-01
    - Notes: 3 organization variables in 2 Eclipse orgs
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`secrets-variables.org-variable.selected-repositories`** (covered, P2, `cli`): organization variable visibility 'selected' with selected_repositories
    - Source: `otterdog/models/organization_variable.py:91-93`, `otterdog/providers/github/rest/org_client.py:638-664`
    - Properties (`org-variable`): `selected_repositories`
    - Operations: add, modify, converge
    - Known bugs: KB-022
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`secrets-variables.repo-secret.lifecycle`** (covered, P0, `cli`): repository secrets: add (repo public key), forced update with --update-secrets, values never read back
    - Source: `otterdog/models/repo_secret.py:24-31`, `otterdog/models/secret.py:125-188`, `otterdog/providers/github/rest/secret_client.py:111-218`
    - Properties (`repo-secret`): `name`, `value`
    - Operations: add, forced-update, converge, security
    - Known bugs: KB-026
    - Notes: 573 repository secrets in 82 Eclipse orgs
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`secrets-variables.repo-variable.lifecycle`** (covered, P1, `cli`): repository variables: add, change value, remove; more than 10 variables (pagination)
    - Source: `otterdog/models/repo_variable.py:24-31`, `otterdog/providers/github/rest/repo_client.py:1230-1283`
    - Properties (`repo-variable`): `name`, `value`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-003
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`secrets-variables.env-secret.lifecycle`** (covered, P2, `cli`): environment secrets (orgs.newEnvSecret, since 1.4.0): add with the environment public key, forced update, remove
    - Source: `otterdog/models/environment_secret.py:24-31`, `otterdog/providers/github/__init__.py:706-797`, `CHANGELOG.md:273-275`
    - Properties (`env-secret`): `name`, `value`
    - Operations: add, forced-update, remove, converge
    - Known bugs: KB-035
    - New findings: F-08
    - Notes: env secret add ('+ add env_secret[name=..., environment=...]'), forced by --update-secrets ('!'), removal -d with the environment kept.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`secrets-variables.env-variable.lifecycle`** (covered, P2, `cli`): environment variables (orgs.newEnvVariable): add, change, remove; upper-case names
    - Source: `otterdog/models/environment_variable.py:24-31`, `otterdog/providers/github/rest/repo_client.py:1055-1120`
    - Properties (`env-variable`): `name`, `value`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-003
    - Notes: env variable add/change/remove with oracle values per step, converge.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`secrets-variables.remove`** (covered, P1, `cli`): removing secrets (organization, repository) with apply -d
    - Source: `otterdog/models/secret.py:139-142`, `otterdog/providers/github/rest/secret_client.py:205-218`, `otterdog/providers/github/rest/secret_client.py:205-218`
    - Operations: remove
    - Notes: repo secret + repo variable (+ env secret/variable) removed with -d, counts delete 4, oracle absent; org secrets removed with -d in cli.org.secret.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`secrets-variables.plain-value-warning`** (covered, P1, `cli`): secret values that are not credential references validate with the warning "has a value '&lt;v&gt;' that does not use a credential provider." (the value is echoed)
    - Source: `otterdog/models/secret.py:50-64`, `otterdog/config.py:276-280`
    - Operations: validate, security
    - Known bugs: KB-025, KB-026
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`secrets-variables.org-dependabot-codespaces-secrets`** (partial, P1, `cli`): organization dependabot_secrets and codespaces_secrets (orgs.newOrgDependabotSecret, newOrgCodespacesSecret): like Actions secrets (visibility public == 'all' | private | selected, names, values), private allowed on every plan (#890)
    - Source: `otterdog/models/organization_dependabot_secret.py:22-52`, `otterdog/models/organization_codespaces_secret.py:22-52`, `otterdog/models/organization_secret.py:27-110`, `otterdog/providers/github/rest/secret_client.py:111-237`
    - Operations: add, modify, remove, validate, plan, forced-update, converge, security
    - Known bugs: KB-025, KB-026
    - Notes: verified offline with main d9dac78: headers org_dependabot_secret[name=...] / org_codespaces_secret[name=...], the GITHUB_ prefix and uppercase errors, the visibility enum at load, 'private' validates on free (only org_secret is gated), the selected_repositories warning, '&lt;DUMMY&gt;', reference diffs, forced updates (4 changes per secret) and --only-secrets. A refused read now aborts plan, apply and import for every secret kind (KB-080's secrets part is fixed). cli.secrets.dependabot-codespaces has not run live yet.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
    - Suggested: `cli.secrets.dependabot-codespaces` in `scenarios/cli/secrets/dependabot-codespaces-secrets.yaml`
    - Steps:
        - run it on a test organization with branch:main (org_level), the admin token holding the Dependabot and Codespaces secrets permissions
    - Assert:
        - oracle org_dependabot_secret, org_codespaces_secret, org_dependabot_secret_repos as written, absent after -d
    - Needs:
        - target
        - org_level
        - an otterdog release &gt;= 1.8.0
        - Dependabot and Codespaces secrets permissions of the admin token (docs/setup-free-org.md)
- **`secrets-variables.repo-dependabot-codespaces-secrets`** (partial, P1, `cli`): repository dependabot_secrets and codespaces_secrets (orgs.newRepoDependabotSecret, newRepoCodespacesSecret): name and value like repository Actions secrets (#890)
    - Source: `otterdog/models/repo_dependabot_secret.py:22-55`, `otterdog/models/repo_codespaces_secret.py:22-55`, `otterdog/models/repository.py:134-139`
    - Operations: add, modify, remove, validate, plan, converge, security
    - Notes: verified offline: repo_dependabot_secret[name=..., repository=&lt;repo&gt;] headers in local-plan; the validation headers name no repository (repo_codespaces_secret[name="..."]), like repository Actions secrets.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
    - Suggested: `cli.secrets.dependabot-codespaces`
    - Steps:
        - the repository secrets of the live scenario (create, remove with -d)
    - Assert:
        - oracle repo_dependabot_secret and repo_codespaces_secret present, then absent
    - Needs:
        - target
        - an otterdog release &gt;= 1.8.0

## Repositories

`repositories`: 18 features, 16 covered, 2 partial, 0 gaps (weighted 94%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `repositories.lifecycle` | repositories: create (POST /orgs/{org}/repos, settings patched after creation), change description, homepage, topics, delete (apply -d) | cli | free | P0 | covered | offline, live | `cli.repo.lifecycle`, `O-LPLAN-ADD`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE`, `tests/cli/test_import.py::test_import_plans_no_change` |
| `repositories.features` | repository features: has_issues, has_wiki, has_projects (unmanaged when org projects are off), has_discussions (forced on the org discussion source) | cli | free | P0 | covered | offline, live | `cli.repo.lifecycle`, `cli.repo.features`, `O-LPLAN-COERCE-SIGNOFF` |
| `repositories.merge-methods` | merge settings: allow_merge_commit, allow_rebase_merge, allow_squash_merge, allow_auto_merge, allow_update_branch, delete_branch_on_merge | cli | free | P0 | covered | live | `cli.repo.lifecycle`, `cli.repo.features` |
| `repositories.merge-commit-messages` | squash_merge_commit_title/message and merge_commit_title/message (squash pair always sent together) | cli | free | P1 | covered | **unverified** | `cli.repo.merge-messages` |
| `repositories.signoff` | repository web_commit_signoff_required (2022 Eclipse repos, 2019 false; unmanaged while the org requires signoff) | cli | free | P0 | covered | live | `cli.repo.org-coerced`, `cli.org.signoff` |
| `repositories.visibility-forking` | private (create private repositories, change visibility) and allow_forking (private repositories need allow_forking false with the template) | cli | free | P1 | covered | live | `regression.private-repo-template-defaults`, `enterprise.private-bpr`, `cli.neg.private-bpr`, `cli.repo.visibility` |
| `repositories.default-branch` | default_branch: switch to an existing branch, otherwise rename the current default branch; skipped for empty repositories (1007 Eclipse overrides, 817 'master') | cli | free | P0 | covered | live | `cli.repo.default-branch` |
| `repositories.archive` | archived: archive (last, after the other changes), changes to archived repositories are ignored, unarchive (304 archived Eclipse repositories) | cli | free | P0 | covered | live | `cli.repo.archive` |
| `repositories.security` | security analysis: secret_scanning, secret_scanning_push_protection, dependabot_alerts_enabled (vulnerability alerts), dependabot_security_updates_enabled, private_vulnerability_reporting_enabled (ignored on private repositories) | cli | free | P1 | covered | live | `cli.repo.security` |
| `repositories.code-scanning` | code scanning default setup: code_scanning_default_setup_enabled, query suite, languages (only disabled on new repositories when configured, #791) | cli | free | P1 | covered | offline, live | `regression.code-scanning-new-repo`, `regression.private-repo-template-defaults`, `cli.repo.code-scanning`, `cli.repo.code-scanning-languages`, `O-LPLAN-CODE-SCANNING-LANGUAGES` |
| `repositories.pages` | GitHub Pages: gh_pages_build_type disabled \| legacy (source branch/path) \| workflow, gh_pages_visibility (enterprise) | cli | free | P1 | **partial** | live | `cli.repo.pages` |
| `repositories.template-repositories` | is_template, template_repository (create from a template, read-only afterwards), post_process_template_content (mustache-rendered files), auto_init | cli | free | P2 | covered | live | `tests/cli/test_repo_template.py::test_repository_from_template` |
| `repositories.fork` | forked_repository '&lt;owner&gt;/&lt;repo&gt;' and fork_default_branch_only: create the repository as a fork (13 repos in 7 orgs) | cli | free | P2 | covered | live | `cli.repo.fork` |
| `repositories.rename` | rename through aliases: ['&lt;old name&gt;'] (one PATCH, nested objects addressed by the new name, #472) | cli | free | P1 | covered | live | `regression.rename-and-modify` |
| `repositories.extend` | extendRepo(name): extends a repository the template already defines in _repositories (Eclipse: '.eclipsefdn'), merged by name | offline | free | P2 | covered | offline | `O-EXTEND-REPO` |
| `repositories.ghsa-forks-ignored` | temporary private forks of security advisories (GHSA repositories) are never loaded, planned or removed | cli | free | P2 | covered | live | `tests/cli/test_repo_ghsa.py::test_advisory_fork_is_ignored` |
| `repositories.immutable-releases` | repository immutable_releases_enabled (PUT/DELETE /repos/{o}/{r}/immutable-releases); not managed while the organization enforces it (#665) | cli | free | P2 | covered | offline, live | `O-VAL-IMMUTABLE-RELEASES`, `cli.repo.immutable-releases` |
| `repositories.pages-custom-domain` | gh_pages_cname (custom domain, null = github.io) and gh_pages_https_enforced (only with a custom domain) (#858) | cli | free | P2 | **partial** | offline | `O-VAL-PAGES-CNAME` |

Details:

- **`repositories.lifecycle`** (covered, P0, `cli`): repositories: create (POST /orgs/{org}/repos, settings patched after creation), change description, homepage, topics, delete (apply -d)
    - Source: `otterdog/models/repository.py:72-82`, `otterdog/providers/github/rest/repo_client.py:140-196`, `otterdog/providers/github/rest/repo_client.py:298-345`, `otterdog/providers/github/rest/repo_client.py:607-627`
    - Properties (`repository`): `name`, `description`, `homepage`, `topics`
    - Operations: add, modify, remove, converge, import
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.features`** (covered, P0, `cli`): repository features: has_issues, has_wiki, has_projects (unmanaged when org projects are off), has_discussions (forced on the org discussion source)
    - Source: `otterdog/models/repository.py:76-79`, `otterdog/models/repository.py:375-376`, `otterdog/models/repository.py:399-405`
    - Properties (`repository`): `has_issues`, `has_wiki`, `has_projects`, `has_discussions`
    - Operations: add, modify, converge, coerce
    - Known bugs: KB-065
    - Notes: has_issues, has_wiki, has_projects and has_discussions are created with non-default values, flipped (exactly 9 changed attributes, checked offline with local-plan), read back from GET /repos and converged (cli.repo.features). The coercions are diff semantics exercised offline by O-LPLAN-COERCE-SIGNOFF: has_projects is unmanaged while has_organization_projects is false, has_discussions is forced on the org discussion source; their validation messages never fire (KB-033). has_discussions is not documented by the create endpoint and not re-applied after the creation (KB-065, suspected: the create step converges live or shows it). has_wiki (423 Eclipse repos, 407 false), has_discussions (387, 353 true), has_projects (239, 223 false).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.merge-methods`** (covered, P0, `cli`): merge settings: allow_merge_commit, allow_rebase_merge, allow_squash_merge, allow_auto_merge, allow_update_branch, delete_branch_on_merge
    - Source: `otterdog/models/repository.py:84-89`
    - Properties (`repository`): `allow_merge_commit`, `allow_rebase_merge`, `allow_squash_merge`, `allow_auto_merge`, `allow_update_branch`, `delete_branch_on_merge`
    - Operations: add, modify, converge
    - Known bugs: KB-065
    - Notes: allow_auto_merge and allow_update_branch are asserted at creation and after the flip, together with allow_merge_commit, allow_rebase_merge, allow_squash_merge and delete_branch_on_merge.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.merge-commit-messages`** (covered, P1, `cli`): squash_merge_commit_title/message and merge_commit_title/message (squash pair always sent together)
    - Source: `otterdog/models/repository.py:90-93`, `otterdog/models/repository.py:1826-1856`, `otterdog/models/repository.py:776-848`
    - Properties (`repository`): `squash_merge_commit_title`, `squash_merge_commit_message`, `merge_commit_title`, `merge_commit_message`
    - Operations: add, modify, converge, validate
    - Known bugs: KB-053
    - Notes: Both pairs set at creation; a change of only the squash message (the title is resent) is asserted strictly. A change of only merge_commit_message is the last step, declared known_bug KB-053 (suspected): otterdog does not complete the merge pair.
- **`repositories.signoff`** (covered, P0, `cli`): repository web_commit_signoff_required (2022 Eclipse repos, 2019 false; unmanaged while the org requires signoff)
    - Source: `otterdog/models/repository.py:96`, `otterdog/models/repository.py:378-379`
    - Properties (`repository`): `web_commit_signoff_required`
    - Operations: add, modify, coerce, converge
    - Notes: with the example template the org requires signoff, so the repository field is only managed under an org setting off (org_level). cli.repo.org-coerced relaxes the org, then turns the repository from false to true (oracle); cli.org.signoff covers the coercion while the org requires signoff and the 'false -&gt; false' re-send when it stops requiring it. The signoff warning never fires (KB-033) and is not asserted.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`repositories.visibility-forking`** (covered, P1, `cli`): private (create private repositories, change visibility) and allow_forking (private repositories need allow_forking false with the template)
    - Source: `otterdog/models/repository.py:75`, `otterdog/models/repository.py:95`, `otterdog/models/repository.py:536-540`, `otterdog/models/repository.py:567-572`
    - Properties (`repository`): `private`, `allow_forking`
    - Operations: add, modify, converge
    - Known bugs: KB-065
    - Notes: An existing repository goes public -&gt; private (allow_forking false, exactly 2 changes) -&gt; public. Each switch must plan a change, never a remove+add. Creating a private repository directly is covered by regression.private-repo-template-defaults only (otterdog 1.7.0+): older SUTs, release:latest included, fail it without Code Security (#791), so the other private-repository scenarios create their repository public and make it private in the next step.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.default-branch`** (covered, P0, `cli`): default_branch: switch to an existing branch, otherwise rename the current default branch; skipped for empty repositories (1007 Eclipse overrides, 817 'master')
    - Source: `otterdog/models/repository.py:83`, `otterdog/providers/github/rest/repo_client.py:833-852`, `otterdog/providers/github/rest/repo_client.py:314-315`
    - Properties (`repository`): `default_branch`
    - Operations: add, modify, converge
    - Notes: Covers the rename at creation (main-&gt;master), a rename of an existing repo (master-&gt;trunk), and a switch to the existing branch e2e/&lt;run&gt;/develop (created by a probe with Mutator.create_branch; trunk stays). The empty-repository skip is exercised by the auto_init false repository of tests/cli/test_repo_template.py.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.archive`** (covered, P0, `cli`): archived: archive (last, after the other changes), changes to archived repositories are ignored, unarchive (304 archived Eclipse repositories)
    - Source: `otterdog/models/repository.py:94`, `otterdog/models/repository.py:1625-1642`, `otterdog/operations/apply.py:176-183`, `otterdog/models/repository.py:635-640`
    - Properties (`repository`): `archived`
    - Operations: archive, modify, converge
    - Known bugs: KB-058
    - Notes: Archive together with a description change (2 changes); while archived, a description change plus a new BPR plan noop (validate -v Info asserted, oracle shows no BPR); unarchive (1 change).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.security`** (covered, P1, `cli`): security analysis: secret_scanning, secret_scanning_push_protection, dependabot_alerts_enabled (vulnerability alerts), dependabot_security_updates_enabled, private_vulnerability_reporting_enabled (ignored on private repositories)
    - Source: `otterdog/models/repository.py:98-102`, `otterdog/models/repository.py:150-158`, `otterdog/providers/github/rest/repo_client.py:854-940`, `otterdog/models/repository.py:588-595`
    - Properties (`repository`): `secret_scanning`, `secret_scanning_push_protection`, `dependabot_alerts_enabled`, `dependabot_security_updates_enabled`, `private_vulnerability_reporting_enabled`
    - Operations: add, modify, converge, coerce
    - Notes: 748 repos enable dependabot security updates, 215 set PVR, 207 push protection (198 disabled), 187 alerts (168 false). Each setting is checked through its own oracle kind (security_and_analysis, vulnerability-alerts, automated-security-fixes, private-vulnerability-reporting) with exact change counts (2, then 4). The last step also creates a repository with security updates enabled from the start.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.code-scanning`** (covered, P1, `cli`): code scanning default setup: code_scanning_default_setup_enabled, query suite, languages (only disabled on new repositories when configured, #791)
    - Source: `otterdog/models/repository.py:104-106`, `otterdog/providers/github/rest/repo_client.py:629-651`, `otterdog/providers/github/rest/repo_client.py:771-793`, `otterdog/models/repository.py:422-492`
    - Properties (`repository`): `code_scanning_default_setup_enabled`, `code_scanning_default_query_suite`, `code_scanning_default_languages`
    - Operations: add, modify, converge, validate
    - Notes: An existing repository; a probe commits a Python file and a dispatch-only workflow and waits until Python is detected. The setup is then configured with the extended suite for languages [actions, python] (state check timeout 600 s before converge) and disabled. cli.repo.code-scanning-languages (fixed_in 1.9.0): a TypeScript repository enabled for 'javascript-typescript' (#922: sent as the combined value), 'actions' added (#941: the change shows the missing language only, analyzed ones kept), [] and a dropped analyzed language plan nothing (#941: minimum set), disabled, enabled again without languages (none sent). O-LPLAN-CODE-SCANNING-LANGUAGES: offline, [] is never compared (#941), enable/disable and a disabled setup's languages plan the same on every SUT.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.pages`** (partial, P1, `cli`): GitHub Pages: gh_pages_build_type disabled | legacy (source branch/path) | workflow, gh_pages_visibility (enterprise)
    - Source: `otterdog/models/repository.py:108-111`, `otterdog/providers/github/rest/repo_client.py:652-735`, `otterdog/models/environment.py:161-173`
    - Properties (`repository`): `gh_pages_build_type`, `gh_pages_source_branch`, `gh_pages_source_path`, `gh_pages_visibility`
    - Operations: add, modify, remove, converge
    - Notes: 309 repos set gh_pages_build_type (legacy 223, workflow 79); 336 of the 408 environments are github-pages, which otterdog never removes while pages are enabled. Covers legacy pages from main /, a change of the source path alone (regression #450), workflow pages with the github-pages environment, then disabled with apply -d removing the environment.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
    - Suggested: `enterprise.repo.pages-visibility` in `scenarios/enterprise/repo/repo-pages-visibility.yaml`
    - Steps:
        - org_level on Enterprise Cloud: members_can_create_private_pages true, a private run repository with legacy pages and gh_pages_visibility 'private', then 'public'
    - Assert:
        - oracle pages {public: false}, then {public: true}; converge
    - Needs:
        - enterprise target
        - capability private_pages
        - org_level
- **`repositories.template-repositories`** (covered, P2, `cli`): is_template, template_repository (create from a template, read-only afterwards), post_process_template_content (mustache-rendered files), auto_init
    - Source: `otterdog/models/repository.py:80-81`, `otterdog/models/repository.py:126-127`, `otterdog/providers/github/rest/repo_client.py:240-296`, `otterdog/providers/github/rest/repo_client.py:323-324`
    - Properties (`repository`): `is_template`, `template_repository`, `post_process_template_content`, `auto_init`
    - Operations: add, converge
    - Notes: template_repository is read-only: changing it later prints the read-only note (verified offline). 12 repos in 3 orgs use templates, 6 orgs mark templates. Covers is_template, template_repository (oracle template_repository.full_name), post_process_template_content (README.md rendered with org/repo, NOTICE.md not listed stays raw), and auto_init false (no branches).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
- **`repositories.fork`** (covered, P2, `cli`): forked_repository '&lt;owner&gt;/&lt;repo&gt;' and fork_default_branch_only: create the repository as a fork (13 repos in 7 orgs)
    - Source: `otterdog/models/repository.py:117-118`, `otterdog/providers/github/rest/repo_client.py:210-238`, `otterdog/models/repository.py:931-932`
    - Properties (`repository`): `forked_repository`, `fork_default_branch_only`
    - Operations: add, converge
    - Notes: Forks octocat/Hello-World with default_branch master and fork_default_branch_only; the oracle checks fork and parent.full_name, and the branches equal [master].
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.rename`** (covered, P1, `cli`): rename through aliases: ['&lt;old name&gt;'] (one PATCH, nested objects addressed by the new name, #472)
    - Source: `otterdog/models/repository.py:125`, `otterdog/models/repository.py:284-288`, `otterdog/providers/github/rest/repo_client.py:169-172`
    - Properties (`repository`): `aliases`
    - Operations: rename, modify, converge
    - Notes: 34 aliases in 20 Eclipse orgs; offline counterpart: plan-semantics.rename-aliases
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.extend`** (covered, P2, `offline`): extendRepo(name): extends a repository the template already defines in _repositories (Eclipse: '.eclipsefdn'), merged by name
    - Source: `otterdog/resources/defaults/otterdog-defaults.libsonnet:138-141`, `otterdog/resources/defaults/otterdog-functions.libsonnet:1`
    - Properties (`repository-extend`): `name`
    - Operations: config, modify
    - Notes: extension after (wins) and before (overridden) the definition, appended nested objects, extension alone refused by the schema ('private' is a required property).
- **`repositories.ghsa-forks-ignored`** (covered, P2, `cli`): temporary private forks of security advisories (GHSA repositories) are never loaded, planned or removed
    - Source: `otterdog/providers/github/__init__.py:417-420`, `otterdog/utils.py:585-591`
    - Operations: filter, remove
    - Notes: Draft advisory plus temporary private fork (probe). The plan is noop and the fork never appears; a guarded apply -d leaves it in place. The test closes the advisory and deletes the fork itself.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.immutable-releases`** (covered, P2, `cli`): repository immutable_releases_enabled (PUT/DELETE /repos/{o}/{r}/immutable-releases); not managed while the organization enforces it (#665)
    - Source: `otterdog/models/repository.py:97`, `otterdog/models/repository.py:384-385`, `otterdog/models/repository.py:409-420`, `otterdog/providers/github/rest/repo_client.py:122-156`
    - Properties (`repository`): `immutable_releases_enabled`
    - Operations: add, modify, coerce, plan, converge
    - Known bugs: KB-033
    - Notes: offline: '\~ immutable_releases_enabled = false -&gt; true'; with the policy 'all' the repository setting plans nothing (coerced at load, so the documented Info never prints: KB-033 step); live: cli.repo.immutable-releases (fixed_in 1.7.0, runs on release:latest) enables then disables it through the oracle kind repo_immutable_releases (not run live yet).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repositories.pages-custom-domain`** (partial, P2, `cli`): gh_pages_cname (custom domain, null = github.io) and gh_pages_https_enforced (only with a custom domain) (#858)
    - Source: `otterdog/models/repository.py:112-113`, `otterdog/models/repository.py:733-745`, `otterdog/models/repository.py:1875-1883`
    - Properties (`repository`): `gh_pages_cname`, `gh_pages_https_enforced`
    - Operations: modify, validate, plan, converge
    - Notes: verified offline (main d9dac78 and v1.7.1): "... has 'gh_pages_cname' set to value 'not a domain', which is not a valid domain name.", "... but a custom domain can not be a 'github.io' domain.", '\~ gh_pages_cname = null -&gt; "docs.&lt;p&gt;.invalid"', https_enforced excluded from the diff without a domain and planned with one.
    - Suggested: `cli.repo.pages-custom-domain` in `scenarios/cli/repo/repo-pages-custom-domain.yaml`
    - Steps:
        - a run repository with workflow pages and gh_pages_cname '&lt;p&gt;.&lt;a domain the org controls&gt;', then null
    - Assert:
        - oracle pages {cname: ...}, then cname null; converge (https enforcement needs a valid certificate: not asserted)
    - Needs:
        - target
        - a DNS name the test organization may point at GitHub Pages

<a id="repo-workflows"></a>

## Repository Actions settings

`repo-workflows`: 7 features, 5 covered, 2 partial, 0 gaps (weighted 86%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `repo-workflows.enabled` | repository Actions enabled true/false (false sends only 'enabled'; ignored when the org disables or does not select the repository) | cli | free | P1 | covered | live | `cli.repo.actions`, `cli.org.actions-enabled-repositories` |
| `repo-workflows.allowed-actions` | repository allowed_actions local_only \| selected with the selected-actions properties (managed only when stricter than the org) | cli | free | P2 | covered | live | `cli.repo.actions`, `cli.org.actions-allowed` |
| `repo-workflows.default-permissions` | repository default_workflow_permissions and actions_can_approve_pull_request_reviews (1354 Eclipse repos set write; unmanaged while the org is 'read' / approvals false) | cli | free | P0 | covered | live | `cli.repo.org-coerced`, `cli.repo.actions`, `cli.org.workflow-permissions` |
| `repo-workflows.fork-pr-approval` | repository fork_pr_approval_policy (skipped for private repositories: GitHub answers 422, #635) | cli | free | P2 | covered | live | `regression.private-repo-template-defaults`, `cli.repo.actions` |
| `repo-workflows.sha-pinning` | repository sha_pinning_required (actions pinned to a full-length commit SHA; ignored while the org requires it; #946, 1.9.0) | cli | free | P2 | covered | offline, live | `cli.repo.actions.sha-pinning`, `O-VAL-REPO-WORKFLOWS`, `O-LPLAN-IGNORED-FIELDS` |
| `repo-workflows.cache-size` | repository max_cache_size_gb (cache storage limit; cost-related above defaults.cost_policy.free_max_cache_size_gb) | cli | free | P2 | **partial** | **unverified** | `cli.repo.cache-limit` |
| `repo-workflows.actions-policies` | repository actions_policies (orgs.newRepoActionsPolicy): add (also with a new repository), change, delete with -d, by name; left as they are on an archived repository, applied before the archiving patch of the same apply (#947) | cli | free | P1 | **partial** | offline, live | `O-VAL-ACTIONS-POLICIES`, `O-LPLAN-ACTIONS-POLICIES`, `cli.workflows.repo-actions-policies` |

Details:

- **`repo-workflows.enabled`** (covered, P1, `cli`): repository Actions enabled true/false (false sends only 'enabled'; ignored when the org disables or does not select the repository)
    - Source: `otterdog/models/repo_workflow_settings.py:38`, `otterdog/models/repo_workflow_settings.py:45-54`, `otterdog/models/repo_workflow_settings.py:148-167`
    - Properties (`repo-workflows`): `enabled`
    - Operations: modify, coerce, converge
    - Notes: 176 Eclipse repos set enabled, 167 false. Created with Actions disabled (only 'enabled' sent), then enabled. The coercion (org selected/none) is covered by cli.org.actions-enabled-repositories
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`repo-workflows.allowed-actions`** (covered, P2, `cli`): repository allowed_actions local_only | selected with the selected-actions properties (managed only when stricter than the org)
    - Source: `otterdog/models/workflow_settings.py:43-46`, `otterdog/models/repo_workflow_settings.py:56-59`, `otterdog/providers/github/rest/repo_client.py:1394-1416`
    - Properties (`repo-workflows`): `allowed_actions`, `allow_github_owned_actions`, `allow_verified_creator_actions`, `allow_action_patterns`
    - Operations: modify, coerce, converge
    - Known bugs: KB-029
    - New findings: F-02
    - Notes: Covers 'selected' with github_owned true, verified false and patterns [actions/\*] (oracle repo_selected_actions), then 'local_only' (selected-actions absent). The coercion (org more restrictive) is covered by cli.org.actions-allowed.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`repo-workflows.default-permissions`** (covered, P0, `cli`): repository default_workflow_permissions and actions_can_approve_pull_request_reviews (1354 Eclipse repos set write; unmanaged while the org is 'read' / approvals false)
    - Source: `otterdog/models/workflow_settings.py:47-48`, `otterdog/models/repo_workflow_settings.py:61-65`, `otterdog/providers/github/rest/repo_client.py:1418-1440`
    - Properties (`repo-workflows`): `default_workflow_permissions`, `actions_can_approve_pull_request_reviews`
    - Operations: modify, coerce, converge
    - Notes: the example template's org default_workflow_permissions 'read' makes the repository value unmanaged: a scenario must set the org to 'write' (org_level) first. With the org at 'write', the repository goes 'read' -&gt; 'write'. actions_can_approve_pull_request_reviews false/true is set at repository level in both scenarios. The coercion with the org at 'read' is covered by cli.org.workflow-permissions.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
- **`repo-workflows.fork-pr-approval`** (covered, P2, `cli`): repository fork_pr_approval_policy (skipped for private repositories: GitHub answers 422, #635)
    - Source: `otterdog/models/workflow_settings.py:49-58`, `otterdog/providers/github/rest/repo_client.py:1442-1466`
    - Properties (`repo-workflows`): `fork_pr_approval_policy`
    - Operations: modify, converge
    - Notes: all_external_contributors on a public repository, read through repo_fork_pr_approval.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`repo-workflows.sha-pinning`** (covered, P2, `cli`): repository sha_pinning_required (actions pinned to a full-length commit SHA; ignored while the org requires it; #946, 1.9.0)
    - Source: `otterdog/models/repo_workflow_settings.py:67-68`, `otterdog/models/repo_workflow_settings.py:132-137`, `otterdog/providers/github/rest/repo_client.py:1320-1336`
    - Properties (`repo-workflows`): `sha_pinning_required`
    - Operations: add, modify, validate, coerce, converge
    - Notes: live (fixed_in 1.9.0): created requiring it, then false, then removed, PUT .../actions/permissions and repo_actions read back. Offline: the Info of a repository not requiring it under an org that does, the coerced (noop) and managed plans; older SUTs refuse the key at load (SUT_EXPECTATIONS asserts per SUT).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
- **`repo-workflows.cache-size`** (partial, P2, `cli`): repository max_cache_size_gb (cache storage limit; cost-related above defaults.cost_policy.free_max_cache_size_gb)
    - Source: `otterdog/models/workflow_settings.py:60-100`, `otterdog/providers/github/rest/repo_client.py:1360-1392`
    - Properties (`repo-workflows`): `max_cache_size_gb`
    - Operations: modify, converge
    - Known bugs: KB-007
    - Notes: Requires actions_cache_limit (5 then 8 GB, oracle repo_cache_storage_limit). Because of KB-006 the capability is usually absent, so the scenario skips.
    - Suggested: `cli.repo.actions` in `scenarios/cli/workflows/repo-actions.yaml`
    - Steps:
        - step 6: workflows+ {max_cache_size_gb: 5}
    - Assert:
        - oracle GET /repos/{o}/{r}/actions/cache/storage-limit (or the documented endpoint) reports 5; converge; KB-007 evidence when the GET reports it unavailable
    - Needs:
        - target
        - available: kind `repo_cache_storage_limit`
- **`repo-workflows.actions-policies`** (partial, P1, `cli`): repository actions_policies (orgs.newRepoActionsPolicy): add (also with a new repository), change, delete with -d, by name; left as they are on an archived repository, applied before the archiving patch of the same apply (#947)
    - Source: `otterdog/models/repo_actions_policy.py:27-98`, `otterdog/providers/github/rest/repo_client.py:515-591`, `otterdog/models/repository.py:1716-1723`
    - Properties (`repo-actions-policy`): `name`, `enforcement`, `include_workflows`, `exclude_workflows`, `allowed_actors`, `allowed_events`
    - Operations: add, modify, remove, archive, validate, plan, converge
    - Notes: sources at main 639eaea (#947). Verified offline with the PR head c67a7f0: '+ add repo_actions_policy[name="&lt;n&gt;", repository=&lt;r&gt;]' (2 to add with a new repository), one change per changed attribute, '- remove ...'; a repository that stays archived plans nothing for its policies (noop), a repository archived by the same plan plans both changes. A repository policy refuses the organization's repository keys (schema).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Suggested: `cli.workflows.repo-actions-policies` in `scenarios/cli/workflows/repo-actions-policies.yaml`
    - Steps:
        - run the scenario on a test organization with branch:main, the enterprise instance first, then on the first release containing #947
    - Assert:
        - POST/PUT/DELETE of .../actions/policies per step; archive in the same apply sends the policy PUT and the archiving PATCH; covered on the default SUT once a release contains #947
    - Needs:
        - target
        - an otterdog release &gt;= 1.9.0
        - the plans offering Actions policies (unknown)
        - available: kind `repo_actions_policy`

<a id="branch-protection"></a>

## Branch protection rules

`branch-protection`: 10 features, 10 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `branch-protection.lifecycle` | branch protection rules keyed by pattern: add, change, remove from an existing repository (apply -d); private repositories need Team or Enterprise | cli | free | P0 | covered | offline, live | `cli.bpr.public`, `enterprise.private-bpr`, `cli.neg.private-bpr`, `O-LPLAN-ADD`, `O-LPLAN-CHANGE` |
| `branch-protection.pull-request-reviews` | pull request reviews: requires_pull_request, required_approving_review_count, dismisses_stale_reviews, requires_code_owner_reviews, require_last_push_approval | cli | free | P0 | covered | live | `cli.bpr.public`, `enterprise.private-bpr`, `cli.bpr.settings` |
| `branch-protection.review-dismissal` | restricts_review_dismissals with review_dismissal_allowances (users '@login', teams '@org/team', apps) | cli | free | P2 | covered | live | `cli.bpr.allowances`, `cli.protection.app-checks` |
| `branch-protection.bypass-allowances` | bypass_pull_request_allowances and bypass_force_push_allowances (actor node ids) | cli | free | P1 | covered | live | `cli.bpr.allowances`, `cli.protection.app-checks` |
| `branch-protection.status-checks` | required status checks: requires_status_checks, requires_strict_status_checks, required_status_checks ('any:&lt;ctx&gt;', '&lt;app-slug&gt;:&lt;ctx&gt;', plain contexts bound to github-actions) | cli | free | P0 | covered | live | `cli.bpr.public`, `cli.bpr.settings`, `cli.protection.app-checks` |
| `branch-protection.history-and-signatures` | requires_linear_history, requires_conversation_resolution, requires_commit_signatures | cli | free | P1 | covered | offline, live | `cli.bpr.public`, `enterprise.private-bpr`, `O-LPLAN-CHANGE`, `cli.bpr.settings` |
| `branch-protection.force-push-deletion-admin` | allows_force_pushes, allows_deletions, is_admin_enforced | cli | free | P1 | covered | live | `cli.bpr.public`, `cli.bpr.settings` |
| `branch-protection.push-restrictions` | restricts_pushes with push_restrictions (actors) and blocks_creations | cli | free | P2 | covered | live | `cli.bpr.allowances`, `cli.protection.app-checks` |
| `branch-protection.lock-branch` | lock_branch with lock_allows_fetch_and_merge (warning when the lock is off) | cli | free | P2 | covered | live | `cli.bpr.lock` |
| `branch-protection.deployments` | requires_deployments with required_deployment_environments (must be environments of the repository) | cli | free | P2 | covered | live | `cli.bpr.deployments` |

Details:

- **`branch-protection.lifecycle`** (covered, P0, `cli`): branch protection rules keyed by pattern: add, change, remove from an existing repository (apply -d); private repositories need Team or Enterprise
    - Source: `otterdog/models/branch_protection_rule.py:47-48`, `otterdog/models/branch_protection_rule.py:371-408`, `otterdog/models/repository.py:1696-1706`
    - Properties (`bpr`): `pattern`
    - Operations: add, modify, remove, converge
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.pull-request-reviews`** (covered, P0, `cli`): pull request reviews: requires_pull_request, required_approving_review_count, dismisses_stale_reviews, requires_code_owner_reviews, require_last_push_approval
    - Source: `otterdog/models/branch_protection_rule.py:55-62`, `otterdog/models/branch_protection_rule.py:88-99`, `otterdog/models/branch_protection_rule.py:301-303`
    - Properties (`bpr`): `requires_pull_request`, `required_approving_review_count`, `dismisses_stale_reviews`, `requires_code_owner_reviews`, `require_last_push_approval`
    - Operations: add, modify, converge, validate
    - Notes: require_last_push_approval true, then requires_pull_request false with required_approving_review_count null (the dependent fields leave the diff: exactly 7 changes).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.review-dismissal`** (covered, P2, `cli`): restricts_review_dismissals with review_dismissal_allowances (users '@login', teams '@org/team', apps)
    - Source: `otterdog/models/branch_protection_rule.py:64-65`, `otterdog/models/branch_protection_rule.py:312-317`
    - Properties (`bpr`): `restricts_review_dismissals`, `review_dismissal_allowances`
    - Operations: add, modify, converge
    - Notes: restricts_review_dismissals with a team and a user (cli.bpr.allowances) and with the e2e App (cli.protection.app-checks, requires app); the oracle uses otterdog's notation.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.bypass-allowances`** (covered, P1, `cli`): bypass_pull_request_allowances and bypass_force_push_allowances (actor node ids)
    - Source: `otterdog/models/branch_protection_rule.py:63`, `otterdog/models/branch_protection_rule.py:67`, `otterdog/models/branch_protection_rule.py:319-331`
    - Properties (`bpr`): `bypass_pull_request_allowances`, `bypass_force_push_allowances`
    - Operations: add, modify, converge
    - Notes: 34 Eclipse rules use bypass_pull_request_allowances+. bypass_pull_request_allowances and bypass_force_push_allowances with a team and a user, swapped in the update step (exactly 5 changes), and with the App.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.status-checks`** (covered, P0, `cli`): required status checks: requires_status_checks, requires_strict_status_checks, required_status_checks ('any:&lt;ctx&gt;', '&lt;app-slug&gt;:&lt;ctx&gt;', plain contexts bound to github-actions)
    - Source: `otterdog/models/branch_protection_rule.py:77-79`, `otterdog/models/branch_protection_rule.py:333-363`, `otterdog/models/branch_protection_rule.py:270-290`
    - Properties (`bpr`): `requires_status_checks`, `requires_strict_status_checks`, `required_status_checks`
    - Operations: add, modify, converge
    - Notes: A plain context is bound to github-actions (oracle app.slug github-actions); a '&lt;app-slug&gt;:&lt;ctx&gt;' check uses the e2e App (requires app); 'any:' is in cli.bpr.public.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.history-and-signatures`** (covered, P1, `cli`): requires_linear_history, requires_conversation_resolution, requires_commit_signatures
    - Source: `otterdog/models/branch_protection_rule.py:73-75`
    - Properties (`bpr`): `requires_linear_history`, `requires_conversation_resolution`, `requires_commit_signatures`
    - Operations: add, modify, converge
    - Notes: requires_commit_signatures true, then false.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.force-push-deletion-admin`** (covered, P1, `cli`): allows_force_pushes, allows_deletions, is_admin_enforced
    - Source: `otterdog/models/branch_protection_rule.py:50-52`
    - Properties (`bpr`): `allows_force_pushes`, `allows_deletions`, `is_admin_enforced`
    - Operations: add, modify, converge
    - Notes: allows_force_pushes and allows_deletions true, then false; is_admin_enforced true.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.push-restrictions`** (covered, P2, `cli`): restricts_pushes with push_restrictions (actors) and blocks_creations
    - Source: `otterdog/models/branch_protection_rule.py:69-71`, `otterdog/models/branch_protection_rule.py:305-310`, `otterdog/models/branch_protection_rule.py:203-220`
    - Properties (`bpr`): `restricts_pushes`, `push_restrictions`, `blocks_creations`
    - Operations: add, modify, converge
    - Notes: restricts_pushes with a team, then user+team, and blocks_creations true-&gt;false, on 'release/\*' of a public repository. GitHub documents branch restrictions on public repositories of Free organizations. The App is the push actor in cli.protection.app-checks.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.lock-branch`** (covered, P2, `cli`): lock_branch with lock_allows_fetch_and_merge (warning when the lock is off)
    - Source: `otterdog/models/branch_protection_rule.py:53-54`, `otterdog/models/branch_protection_rule.py:222-229`
    - Properties (`bpr`): `lock_branch`, `lock_allows_fetch_and_merge`
    - Operations: add, modify, converge
    - Notes: lock_branch and lock_allows_fetch_and_merge true, then false (2 changes).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`branch-protection.deployments`** (covered, P2, `cli`): requires_deployments with required_deployment_environments (must be environments of the repository)
    - Source: `otterdog/models/branch_protection_rule.py:81-82`, `otterdog/models/branch_protection_rule.py:180-201`
    - Properties (`bpr`): `requires_deployments`, `required_deployment_environments`
    - Operations: add, modify, converge, validate
    - Notes: requires_deployments with the repository's own environment in the same apply; drop (1 change); validation error for an undefined environment.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)

<a id="rulesets"></a>

## Repository and organization rulesets

`rulesets`: 19 features, 11 covered, 8 partial, 0 gaps (weighted 79%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `rulesets.repo.lifecycle` | repository rulesets keyed by name with ref conditions include_refs / exclude_refs (\~DEFAULT_BRANCH, \~ALL, refs/heads/\*): add, change, remove | cli | free | P1 | covered | offline, live | `cli.ruleset.public`, `regression.disabled-ruleset-without-refs`, `O-VAL-OK`, `O-VAL-RULESET-STRICT` |
| `rulesets.targets` | ruleset target branch \| tag \| push (tag protection rulesets with include_refs ['\~ALL'] are used by eclipse-csi) | cli | free | P1 | **partial** | live | `cli.ruleset.public`, `cli.ruleset.rules` |
| `rulesets.enforcement` | enforcement active \| disabled \| evaluate (evaluate: enterprise plan) | cli | free | P1 | covered | live | `cli.ruleset.public`, `regression.disabled-ruleset-without-refs`, `enterprise.org-ruleset` |
| `rulesets.rules` | simple rules: allows_creations, allows_deletions, allows_updates, allows_force_pushes (inverted rules), requires_linear_history, requires_commit_signatures | cli | free | P1 | covered | live | `cli.ruleset.public`, `cli.kb.ruleset-default-status-checks`, `cli.ruleset.rules` |
| `rulesets.bypass-actors` | bypass_actors: '#RepositoryAdmin' \| '#Maintain' \| '#Write' \| '#OrganizationAdmin', '@user', '@org/team', '&lt;app-slug&gt;', each with an optional ':&lt;bypass_mode&gt;' (always \| pull_request) | cli | free | P1 | covered | live | `cli.ruleset.bypass`, `cli.protection.app-checks`, `regression.user-bypass-actors` |
| `rulesets.deployments` | requires_deployments with required_deployment_environments | cli | free | P2 | covered | live | `cli.ruleset.deployments` |
| `rulesets.pull-request` | required_pull_request (orgs.newPullRequest): required_approving_review_count 0..10, dismisses_stale_reviews, requires_code_owner_review, requires_last_push_approval, requires_review_thread_resolution | cli | free | P1 | covered | live | `cli.ruleset.public`, `regression.ruleset-empty-status-checks`, `cli.neg.private-ruleset`, `cli.ruleset.pull-request` |
| `rulesets.status-checks` | required_status_checks (orgs.newStatusChecks): strict, status_checks ('&lt;app&gt;:&lt;ctx&gt;', 'any:' dropped on read), do_not_enforce_on_create; an empty list sends no rule (#562) | cli | free | P1 | covered | offline, live | `cli.ruleset.public`, `regression.ruleset-empty-status-checks`, `cli.kb.ruleset-any-status-check`, `cli.kb.ruleset-default-status-checks`, `O-VAL-RULESET-STRICT`, `regression.repo-ruleset-without-strict`, `cli.ruleset.status-checks`, `cli.protection.app-checks` |
| `rulesets.merge-queue` | required_merge_queue (orgs.newMergeQueue): merge_method MERGE \| SQUASH \| REBASE, build_concurrency, min/max_group_size, wait_time_for_minimum_group_size, status_check_timeout, requires_all_group_entries_to_pass_required_checks | cli | free | P2 | covered | live | `cli.ruleset.merge-queue`, `enterprise.ruleset-merge-queue-private` |
| `rulesets.org.repository-conditions` | organization rulesets: include_repo_names / exclude_repo_names (fnmatch, '\~ALL'), protect_repo_names; enterprise plan in otterdog | enterprise | enterprise | P2 | covered | live | `enterprise.org-ruleset`, `enterprise.kb.org-ruleset-repo-patterns` |
| `rulesets.copilot-code-review` | copilot_code_review (orgs.newCopilotCodeReview: review_on_push, review_draft_pull_requests): the copilot_code_review rule, an automatic Copilot review of pull requests; refused on a push ruleset (#900, daf9237, in v1.8.0) | cli | free | P2 | covered | offline, live | `cli.ruleset.copilot-code-scanning`, `O-VAL-RULESET-CODE-ANALYSIS`, `O-VAL-RULESET-PUSH-RULES` |
| `rulesets.code-scanning` | required_code_scanning (orgs.newCodeScanning: code_scanning_tools written 'tool:security_alerts_threshold:alerts_threshold'): the code_scanning rule, one {tool, security_alerts_threshold, alerts_threshold} per tool; a missing, empty or malformed tool list and unknown thresholds are refused (#900, daf9237, in v1.8.0) | cli | free | P2 | covered | offline, live | `cli.ruleset.copilot-code-scanning`, `O-VAL-RULESET-CODE-ANALYSIS` |
| `rulesets.code-quality` | required_code_quality (orgs.newCodeQuality: severity errors \| warnings \| notes \| all): the code_quality rule; an unknown severity is a load error of the JSON schema (#900, daf9237, in v1.8.0) | cli | enterprise | P2 | **partial** | offline | `O-VAL-RULESET-CODE-ANALYSIS` |
| `rulesets.code-coverage` | required_code_coverage (orgs.newCodeCoverage: minimum_coverage, max_coverage_drop in [0, 100]): the code_coverage rule; out-of-range values are refused and a coverage without threshold is a warning (#900, daf9237, in v1.8.0) | cli | enterprise | P2 | **partial** | offline | `O-VAL-RULESET-CODE-ANALYSIS` |
| `rulesets.license-compliance` | requires_license_compliance_scanning: the license_compliance rule, results of license compliance scanning required before merging (#900, daf9237, in v1.8.0) | cli | enterprise | P2 | **partial** | offline | `O-VAL-RULESET-CODE-ANALYSIS` |
| `rulesets.patterns` | pattern rules (orgs.newPattern: name, negate, operator starts_with \| ends_with \| contains \| regex, pattern) of commit_message_pattern, commit_author_email_pattern, committer_email_pattern, branch_name_pattern and tag_name_pattern; a missing or empty pattern is refused, the branch and tag name patterns only on a ruleset of their target (#900, daf9237, in v1.8.0) | cli | enterprise | P2 | **partial** | offline | `O-VAL-RULESET-PATTERNS` |
| `rulesets.push-rules` | push rules of a ruleset with target 'push': restricted_file_paths (with restricted_file_paths_exceptions), max_file_path_length, restricted_file_extensions, max_file_size (with max_file_size_exceptions); limits of GitHub (size in [0, 100] MB, path length in [0, 32767], at most 200 entries of 200 characters), refused on a branch or tag ruleset (#900, daf9237, in v1.8.0) | cli | team | P2 | **partial** | offline | `O-VAL-RULESET-PUSH-RULES` |
| `rulesets.required-workflows` | required_workflows (orgs.newWorkflows: do_not_enforce_on_create, workflows written 'owner/repository:path[@ref][#sha]'): the workflows rule of an organization ruleset, the repository resolved to its id when otterdog talks to GitHub; refused in a repository ruleset (#900, daf9237, in v1.8.0) | enterprise | enterprise | P2 | **partial** | offline | `O-VAL-RULESET-REQUIRED-WORKFLOWS` |
| `rulesets.pull-request.allowed-merge-methods` | required_pull_request allowed_merge_methods (merge \| squash \| rebase, at least one, unique; template default all three) (#777) | cli | free | P2 | **partial** | offline | `O-VAL-RULESETS`, `O-VAL-ORG-RULESETS`, `O-VAL-RULESET-NESTED` |

Details:

- **`rulesets.repo.lifecycle`** (covered, P1, `cli`): repository rulesets keyed by name with ref conditions include_refs / exclude_refs (\~DEFAULT_BRANCH, \~ALL, refs/heads/\*): add, change, remove
    - Source: `otterdog/models/ruleset.py:836-844`, `otterdog/models/repo_ruleset.py:24-97`, `otterdog/providers/github/rest/repo_client.py:440-597`
    - Properties (`repo-ruleset`): `name`, `include_refs`, `exclude_refs`
    - Operations: add, modify, remove, converge
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.targets`** (partial, P1, `cli`): ruleset target branch | tag | push (tag protection rulesets with include_refs ['\~ALL'] are used by eclipse-csi)
    - Source: `otterdog/models/ruleset.py:838`, `otterdog/models/ruleset.py:1008-1060`
    - Properties (`repo-ruleset`): `target`
    - Operations: add, converge, validate
    - Notes: A tag ruleset with include_refs ['\~ALL'] and creation/update/deletion rules, plus an exclude pattern, is applied and converged.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
    - Suggested: `cli.ruleset.push-target` in `scenarios/cli/rulesets/ruleset-push-target.yaml`
    - Steps:
        - private run repository on a Team/Enterprise target: a ruleset with target 'push' and a file path rule
    - Assert:
        - discovery: what GitHub accepts from otterdog's model (otterdog always sends ref_name conditions and its simple rules are not push rules); record it, then assert it
    - Needs:
        - target
        - min_plan: team
        - requires: [push_rulesets]
- **`rulesets.enforcement`** (covered, P1, `cli`): enforcement active | disabled | evaluate (evaluate: enterprise plan)
    - Source: `otterdog/models/ruleset.py:839`, `otterdog/models/ruleset.py:1019-1033`
    - Properties (`repo-ruleset`): `enforcement`
    - Operations: add, modify, converge, validate
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.rules`** (covered, P1, `cli`): simple rules: allows_creations, allows_deletions, allows_updates, allows_force_pushes (inverted rules), requires_linear_history, requires_commit_signatures
    - Source: `otterdog/models/ruleset.py:846-852`, `otterdog/models/ruleset.py:1300-1312`, `otterdog/models/ruleset.py:1463-1477`
    - Properties (`repo-ruleset`): `allows_creations`, `allows_deletions`, `allows_updates`, `allows_force_pushes`, `requires_linear_history`, `requires_commit_signatures`
    - Operations: add, modify, converge
    - Notes: Exact rule sets: update, required_signatures, no non_fast_forward/creation, then the inverse (8 changes).
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.bypass-actors`** (covered, P1, `cli`): bypass_actors: '#RepositoryAdmin' | '#Maintain' | '#Write' | '#OrganizationAdmin', '@user', '@org/team', '&lt;app-slug&gt;', each with an optional ':&lt;bypass_mode&gt;' (always | pull_request)
    - Source: `otterdog/models/ruleset.py:841`, `otterdog/models/ruleset.py:883-884`, `otterdog/models/ruleset.py:1315-1358`, `otterdog/models/ruleset.py:1420-1456`
    - Properties (`repo-ruleset`): `bypass_actors`
    - Operations: add, modify, converge
    - Known bugs: KB-039, KB-052
    - New findings: F-12
    - Notes: 22 Eclipse rulesets use bypass_actors+ ('#OrganizationAdmin', '@&lt;org&gt;/eclipsefdn-releng'); the webapp's own config-repo ruleset needs '#OrganizationAdmin'. Covers #OrganizationAdmin, #RepositoryAdmin, #Maintain:pull_request, #Write, a team, then mode changes; the App actor (app-checks); the user actor (779, fixed_in 1.7.0). Known-bug steps: '#Admin' (KB-039) and explicit ':always' (KB-052).
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.deployments`** (covered, P2, `cli`): requires_deployments with required_deployment_environments
    - Source: `otterdog/models/ruleset.py:854-855`, `otterdog/models/ruleset.py:1063-1082`
    - Properties (`repo-ruleset`): `requires_deployments`, `required_deployment_environments`
    - Operations: add, modify, converge, validate
    - Notes: required_deployments rule with the repository's environment; drop (1 change); validation error for an undefined environment.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.pull-request`** (covered, P1, `cli`): required_pull_request (orgs.newPullRequest): required_approving_review_count 0..10, dismisses_stale_reviews, requires_code_owner_review, requires_last_push_approval, requires_review_thread_resolution
    - Source: `otterdog/models/ruleset.py:53-147`
    - Properties (`ruleset-pull-request`): `required_approving_review_count`, `dismisses_stale_reviews`, `requires_code_owner_review`, `requires_last_push_approval`, `requires_review_thread_resolution`
    - Operations: add, modify, remove, converge, validate
    - Known bugs: KB-031
    - New findings: F-04
    - Notes: Count 0 with every flag on, then count 3 with every flag off, then required_pull_request null removes the rule.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.status-checks`** (covered, P1, `cli`): required_status_checks (orgs.newStatusChecks): strict, status_checks ('&lt;app&gt;:&lt;ctx&gt;', 'any:' dropped on read), do_not_enforce_on_create; an empty list sends no rule (#562)
    - Source: `otterdog/models/ruleset.py:150-255`
    - Properties (`ruleset-status-checks`): `strict`, `status_checks`, `do_not_enforce_on_create`
    - Operations: add, modify, converge, validate
    - Known bugs: KB-020, KB-021, KB-054
    - Notes: do_not_enforce_on_create, the plain context and '15368:&lt;ctx&gt;' (GitHub Actions integration id) are strict; the installed App slug is in app-checks. Known-bug steps for 'github-actions:&lt;ctx&gt;' and '&lt;installed app id&gt;:&lt;ctx&gt;' never converge (KB-054).
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.merge-queue`** (covered, P2, `cli`): required_merge_queue (orgs.newMergeQueue): merge_method MERGE | SQUASH | REBASE, build_concurrency, min/max_group_size, wait_time_for_minimum_group_size, status_check_timeout, requires_all_group_entries_to_pass_required_checks
    - Source: `otterdog/models/ruleset.py:258-352`
    - Properties (`ruleset-merge-queue`): `merge_method`, `build_concurrency`, `min_group_size`, `max_group_size`, `wait_time_for_minimum_group_size`, `status_check_timeout`, `requires_all_group_entries_to_pass_required_checks`
    - Operations: add, modify, converge, validate
    - Known bugs: KB-031
    - New findings: F-04
    - Notes: 12 merge queues in 3 Eclipse orgs (eclipse-score: MERGE 6, SQUASH 5, REBASE 1). Public repository: SQUASH with non-default sizes, then MERGE/HEADGREEN. Private repository on Enterprise: requires merge_queue_private.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.org.repository-conditions`** (covered, P2, `enterprise`): organization rulesets: include_repo_names / exclude_repo_names (fnmatch, '\~ALL'), protect_repo_names; enterprise plan in otterdog
    - Source: `otterdog/models/organization_ruleset.py:27-35`, `otterdog/models/organization_ruleset.py:51-97`, `otterdog/providers/github/rest/org_client.py:956-1022`
    - Properties (`org-ruleset`): `include_repo_names`, `exclude_repo_names`, `protect_repo_names`
    - Operations: add, modify, remove, converge, validate
    - Known bugs: KB-009, KB-023
    - Notes: New repo-conditions step in enterprise.org-ruleset: exclude_repo_names for a second run repository and protect_repo_names true; oracle repository_name {include, exclude, protected}; 1 add + 2 changes, checked offline with the enterprise plan.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.copilot-code-review`** (covered, P2, `cli`): copilot_code_review (orgs.newCopilotCodeReview: review_on_push, review_draft_pull_requests): the copilot_code_review rule, an automatic Copilot review of pull requests; refused on a push ruleset (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:372-384`, `otterdog/models/ruleset.py:808-826`, `otterdog/models/ruleset.py:1171-1223`
    - Properties (`ruleset-copilot-code-review`): `review_on_push`, `review_draft_pull_requests`
    - Operations: add, modify, remove, converge, validate
    - Notes: cli.ruleset.copilot-code-scanning: a default-branch ruleset of a public run repository with the rule, read back with its exact parameters, both flags flipped, then the rule removed (copilot_code_review null), a no-op plan after each apply. #900 also fixed the rule type of #639 ('copilot_review' with 'review_new_pushes', refused by GitHub). Offline: the rule plans a change, a push ruleset refuses it (O-VAL-RULESET-PUSH-RULES pull-request-rules-on-push). Not verified: GitHub's answer on an organization without Copilot.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.code-scanning`** (covered, P2, `cli`): required_code_scanning (orgs.newCodeScanning: code_scanning_tools written 'tool:security_alerts_threshold:alerts_threshold'): the code_scanning rule, one {tool, security_alerts_threshold, alerts_threshold} per tool; a missing, empty or malformed tool list and unknown thresholds are refused (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:435-538`, `otterdog/models/ruleset.py:808-826`
    - Properties (`ruleset-code-scanning`): `code_scanning_tools`
    - Operations: add, modify, remove, converge, validate
    - Notes: Live: the rule with its tools as written, narrowed to another threshold, removed. Offline (O-VAL-RULESET-CODE-ANALYSIS code-scanning-tools): the validation errors of an empty list, a value without thresholds and an unknown threshold.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`rulesets.code-quality`** (partial, P2, `cli`): required_code_quality (orgs.newCodeQuality: severity errors | warnings | notes | all): the code_quality rule; an unknown severity is a load error of the JSON schema (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:539-561`, `otterdog/models/ruleset.py:808-826`, `otterdog/resources/schemas/ruleset.json:1-40`
    - Properties (`ruleset-code-quality`): `severity`
    - Operations: add, modify, validate, plan
    - Notes: Offline only (plan enterprise): the schema error of an unknown severity, the rule planned and a severity change planned as a change of the ruleset; the rule's plan gating is in O-VAL-PLAN-GATES / -TEAM / -ENTERPRISE.
    - Suggested: `enterprise.ruleset-code-analysis` in `scenarios/enterprise/rulesets/ruleset-code-analysis.yaml`
    - Steps:
        - a ruleset of a run repository with required_code_quality (severity warnings), required_code_coverage (minimum_coverage 80) and requires_license_compliance_scanning, then other values, then the three rules removed
    - Assert:
        - oracle repo_rulesets: the code_quality, code_coverage and license_compliance rules with their parameters; a no-op plan after each apply
    - Needs:
        - target
        - min_plan: enterprise (the plan gating of #900 warns below)
        - available: kind repo_rulesets
- **`rulesets.code-coverage`** (partial, P2, `cli`): required_code_coverage (orgs.newCodeCoverage: minimum_coverage, max_coverage_drop in [0, 100]): the code_coverage rule; out-of-range values are refused and a coverage without threshold is a warning (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:562-594`, `otterdog/models/ruleset.py:808-826`
    - Properties (`ruleset-code-coverage`): `minimum_coverage`, `max_coverage_drop`
    - Operations: add, modify, validate, plan
    - Notes: Offline only: the errors of values outside [0, 100], the warning "has neither 'required_code_coverage.minimum_coverage' nor 'required_code_coverage.max_coverage_drop' set, the rule has no effect.", a planned change.
    - Suggested: `enterprise.ruleset-code-analysis` in `scenarios/enterprise/rulesets/ruleset-code-analysis.yaml`
    - Steps:
        - see rulesets.code-quality: the same live scenario sets and changes the coverage thresholds
    - Assert:
        - oracle repo_rulesets: the code_coverage rule with minimum_coverage and max_coverage_drop as written
    - Needs:
        - target
        - min_plan: enterprise
- **`rulesets.license-compliance`** (partial, P2, `cli`): requires_license_compliance_scanning: the license_compliance rule, results of license compliance scanning required before merging (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:880`, `otterdog/models/ruleset.py:927-945`
    - Properties (`repo-ruleset`): `requires_license_compliance_scanning`
    - Operations: add, modify, plan
    - Notes: Offline only: the rule planned with the other code analysis rules.
    - Suggested: `enterprise.ruleset-code-analysis` in `scenarios/enterprise/rulesets/ruleset-code-analysis.yaml`
    - Steps:
        - see rulesets.code-quality: the same live scenario turns the rule on, then off
    - Assert:
        - oracle repo_rulesets: a license_compliance rule, then none
    - Needs:
        - target
        - min_plan: enterprise
- **`rulesets.patterns`** (partial, P2, `cli`): pattern rules (orgs.newPattern: name, negate, operator starts_with | ends_with | contains | regex, pattern) of commit_message_pattern, commit_author_email_pattern, committer_email_pattern, branch_name_pattern and tag_name_pattern; a missing or empty pattern is refused, the branch and tag name patterns only on a ruleset of their target (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:385-434`, `otterdog/models/ruleset.py:800-807`, `otterdog/models/ruleset.py:1171-1223`
    - Properties (`ruleset-pattern`): `name`, `negate`, `operator`, `pattern`
    - Operations: add, validate, plan
    - Notes: Offline only (plan enterprise, a warning below): the errors of a missing or empty pattern and of a branch or tag name pattern outside its target, the schema error of an unknown operator, the five rules planned.
    - Suggested: `enterprise.ruleset-patterns` in `scenarios/enterprise/rulesets/ruleset-patterns.yaml`
    - Steps:
        - a branch ruleset of a run repository with commit_message_pattern (starts_with), committer_email_pattern (negated ends_with) and branch_name_pattern (regex), then a changed operator, then the rules removed; a tag ruleset with tag_name_pattern
    - Assert:
        - oracle repo_rulesets: the commit_message_pattern, committer_email_pattern, branch_name_pattern and tag_name_pattern rules with {name, negate, operator, pattern}; a no-op plan after each apply
    - Needs:
        - target
        - min_plan: enterprise
- **`rulesets.push-rules`** (partial, P2, `cli`): push rules of a ruleset with target 'push': restricted_file_paths (with restricted_file_paths_exceptions), max_file_path_length, restricted_file_extensions, max_file_size (with max_file_size_exceptions); limits of GitHub (size in [0, 100] MB, path length in [0, 32767], at most 200 entries of 200 characters), refused on a branch or tag ruleset (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:869-875`, `otterdog/models/ruleset.py:950-963`, `otterdog/models/ruleset.py:1125-1170`
    - Properties (`repo-ruleset`): `restricted_file_paths`, `restricted_file_paths_exceptions`, `max_file_path_length`, `restricted_file_extensions`, `max_file_size`, `max_file_size_exceptions`
    - Operations: add, validate, plan
    - Notes: Offline only (plan team): the limits, the entry checks, the push rules refused outside a push ruleset and the pull request rules refused on one, the warnings of an exception without its rule and of ref conditions (ignored by push rulesets), a valid push ruleset planned. The live part is the gap of rulesets.targets (cli.ruleset.push-target).
    - Suggested: `cli.ruleset.push-target` in `scenarios/cli/rulesets/ruleset-push-target.yaml`
    - Steps:
        - a private run repository on a Team or Enterprise target: a push ruleset with restricted_file_paths and an exception, max_file_size 10, restricted_file_extensions ['.exe'], then changed limits, then removed
    - Assert:
        - oracle repo_rulesets: target push, the file_path_restriction, max_file_size and file_extension_restriction rules with their parameters, no ref condition; a no-op plan after each apply
    - Needs:
        - target
        - min_plan: team
        - requires: [push_rulesets]
- **`rulesets.required-workflows`** (partial, P2, `enterprise`): required_workflows (orgs.newWorkflows: do_not_enforce_on_create, workflows written 'owner/repository:path[@ref][#sha]'): the workflows rule of an organization ruleset, the repository resolved to its id when otterdog talks to GitHub; refused in a repository ruleset (#900, daf9237, in v1.8.0)
    - Source: `otterdog/models/ruleset.py:595-799`, `otterdog/models/ruleset.py:808-826`
    - Properties (`ruleset-workflows`): `do_not_enforce_on_create`, `workflows`
    - Operations: add, modify, validate, plan
    - Notes: Offline only (plan enterprise): the errors of an empty list, a value without owner, a numeric repository id, a sha that is not 40 hexadecimal digits and an unescaped '%', the warning of a path that is not a .yml/.yaml file, the rule refused in a repository ruleset, repository names compared case-insensitively in the plan.
    - Suggested: `enterprise.org-ruleset-required-workflows` in `scenarios/enterprise/rulesets/org-ruleset-required-workflows.yaml`
    - Steps:
        - an organization ruleset targeting the run repositories with required_workflows on a workflow of a run repository (pinned to a sha), then do_not_enforce_on_create true, then removed
    - Assert:
        - oracle org_rulesets: a workflows rule with {repository_id, path, ref, sha} of the run repository; a no-op plan after each apply
    - Needs:
        - target
        - min_plan: enterprise
        - org_level
        - a run repository holding the workflow file (available: repository files of the scenario fixtures)
- **`rulesets.pull-request.allowed-merge-methods`** (partial, P2, `cli`): required_pull_request allowed_merge_methods (merge | squash | rebase, at least one, unique; template default all three) (#777)
    - Source: `otterdog/models/ruleset.py:53-61`, `otterdog/resources/schemas/ruleset.json:88-98`
    - Properties (`ruleset-pull-request`): `allowed_merge_methods`
    - Operations: add, modify, plan, converge
    - Notes: the references to #777 of the ruleset scenarios declare the show and local-plan deltas that print allowed_merge_methods; no step asserts a changed list yet.
    - Suggested: `cli.ruleset.pull-request`
    - Steps:
        - a step restricting allowed_merge_methods to ['squash'] on the run ruleset
    - Assert:
        - plan '\~ allowed_merge_methods', oracle repo_ruleset rules[pull_request].parameters.allowed_merge_methods == ['squash'], converge
    - Needs:
        - target

<a id="environments"></a>

## Deployment environments

`environments`: 4 features, 4 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `environments.lifecycle` | deployment environments keyed by name: add, change, remove (github-pages is never removed while pages are enabled) | cli | free | P0 | covered | offline, live | `cli.environment`, `enterprise.env-reviewers-private`, `O-LPLAN-ADD`, `O-LPLAN-CHANGE`, `cli.environment.policies`, `cli.environment.private` |
| `environments.wait-timer` | wait_timer protection rule (minutes, 0..43200) | cli | free | P1 | covered | offline, live | `cli.environment`, `enterprise.env-reviewers-private`, `O-LPLAN-CHANGE` |
| `environments.reviewers` | required reviewers ('@user', '@org/team') and prevent_self_review (private repositories: Enterprise only) | cli | free | P1 | covered | live | `enterprise.env-reviewers-private`, `cli.environment.reviewers` |
| `environments.branch-policies` | deployment_branch_policy all \| protected \| selected with branch_policies (branch patterns, 'tag:&lt;pattern&gt;' for tags) | cli | free | P0 | covered | offline, live | `cli.environment`, `O-LPLAN-ADD`, `O-VAL-OK`, `cli.environment.policies`, `cli.environment.private` |

Details:

- **`environments.lifecycle`** (covered, P0, `cli`): deployment environments keyed by name: add, change, remove (github-pages is never removed while pages are enabled)
    - Source: `otterdog/models/environment.py:58`, `otterdog/models/environment.py:161-173`, `otterdog/models/environment.py:347-424`, `otterdog/providers/github/rest/repo_client.py:1004-1053`
    - Properties (`environment`): `name`
    - Operations: add, modify, remove, converge
    - Notes: Live removal from an existing repository: '- remove environment' with apply -d, environment absent, repository kept. Private repositories (min_plan team, requires private_repo_environments) in cli.environment.private.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`environments.wait-timer`** (covered, P1, `cli`): wait_timer protection rule (minutes, 0..43200)
    - Source: `otterdog/models/environment.py:59`, `otterdog/models/environment.py:213-216`
    - Properties (`environment`): `wait_timer`
    - Operations: add, modify, converge, validate
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`environments.reviewers`** (covered, P1, `cli`): required reviewers ('@user', '@org/team') and prevent_self_review (private repositories: Enterprise only)
    - Source: `otterdog/models/environment.py:60-61`, `otterdog/models/environment.py:179-188`, `otterdog/models/environment.py:238-246`
    - Properties (`environment`): `reviewers`, `prevent_self_review`
    - Operations: add, modify, converge, validate
    - Notes: Public repository: a team (pull access) plus the admin user with prevent_self_review, then the team only (2 changes). A one-minute wait timer makes the protection_rules list deterministic.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`environments.branch-policies`** (covered, P0, `cli`): deployment_branch_policy all | protected | selected with branch_policies (branch patterns, 'tag:&lt;pattern&gt;' for tags)
    - Source: `otterdog/models/environment.py:62-63`, `otterdog/models/environment.py:190-209`, `otterdog/models/environment.py:248-270`, `otterdog/providers/github/rest/repo_client.py:1158-1228`
    - Properties (`environment`): `deployment_branch_policy`, `branch_policies`
    - Operations: add, modify, remove, converge, validate
    - Known bugs: KB-036
    - New findings: F-09
    - Notes: selected with ['main', 'tag:v\*'] (oracle types branch/tag), then 'protected' (1 change).
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)

<a id="receiver"></a>

## Webhook receiver contract

`receiver`: 8 features, 8 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `receiver.endpoint` | POST GITHUB_WEBHOOK_ENDPOINT (default /github-webhook/receive); the webapp refuses to start without GITHUB_WEBHOOK_SECRET | offline | free | P0 | covered | offline, live | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/offline/test_webapp_runtime.py::test_webhook_endpoint_is_configurable` |
| `receiver.signature` | only 'X-Hub-Signature: sha1=&lt;hmac&gt;' is checked: missing ("Missing header: X-Hub-Signature"), wrong or sha256-only deliveries answer 400 | offline | free | P0 | covered | offline | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong` |
| `receiver.required-headers` | a signed delivery without X-Github-Event or content-type answers 400 'Missing header: &lt;name&gt;' | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong`, `tests/offline/test_webapp_contract.py::test_optional_headers` |
| `receiver.content-types` | content types: exactly application/json, or application/x-www-form-urlencoded with a 'payload' field; anything else (also a charset parameter) answers 415 | offline | free | P1 | covered | offline | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong`, `tests/offline/test_webapp_contract.py::test_form_encoded_delivery_is_processed`, `tests/offline/test_webapp_contract.py::test_form_delivery_without_payload_is_rejected` |
| `receiver.empty-body` | a JSON body 'null' answers 400 'Request body must contain data' | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong` |
| `receiver.accepted` | valid deliveries answer 204 whatever the hooks do: ping, events nobody handles, unknown installations ("received event for unknown installation '&lt;id&gt;'") | offline | free | P0 | covered | offline, live | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/offline/test_webapp_contract.py::test_replayed_delivery_is_processed_again` |
| `receiver.hook-exception` | an exception in a hook is logged with the delivery context ('failed to process webhook delivery &lt;id&gt; for event ...') and propagates (500) | offline | free | P2 | covered | offline | `tests/offline/test_webapp_runtime.py::test_database_outage` |
| `receiver.event-logging` | event descriptions are logged per delivery; formatting errors never block processing; workflow_job/workflow_run are only logged for queued/completed | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_workflow_events_are_described_selectively`, `tests/offline/test_webapp_contract.py::test_unformattable_events_are_still_processed`, `tests/offline/test_webapp_contract.py::test_form_encoded_delivery_is_processed`, `tests/offline/test_webapp_contract.py::test_replayed_delivery_is_processed_again` |

Details:

- **`receiver.endpoint`** (covered, P0, `offline`): POST GITHUB_WEBHOOK_ENDPOINT (default /github-webhook/receive); the webapp refuses to start without GITHUB_WEBHOOK_SECRET
    - Source: `otterdog/webapp/webhook/github_webhook.py:28-47`, `otterdog/webapp/config.py:105`
    - Operations: api, config, security
    - Known bugs: KB-012
    - Notes: GITHUB_WEBHOOK_ENDPOINT moves the receiver, the default path then answers 404
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`receiver.signature`** (covered, P0, `offline`): only 'X-Hub-Signature: sha1=&lt;hmac&gt;' is checked: missing ("Missing header: X-Hub-Signature"), wrong or sha256-only deliveries answer 400
    - Source: `otterdog/webapp/webhook/github_webhook.py:63-81`, `otterdog/webapp/webhook/github_webhook.py:150-156`
    - Operations: api, security
    - Notes: bodies 'Missing header: X-Hub-Signature' / 'Invalid signature' and the #775 rejection log
- **`receiver.required-headers`** (covered, P2, `offline`): a signed delivery without X-Github-Event or content-type answers 400 'Missing header: &lt;name&gt;'
    - Source: `otterdog/webapp/webhook/github_webhook.py:83-84`, `otterdog/webapp/webhook/github_webhook.py:150-156`
    - Operations: api, error
    - Notes: Bodies 'Missing header: X-Github-Event' / 'content-type'; User-Agent optional; X-GitHub-Delivery optional since 5466db5 (v1.6.1: 400 'Missing header: X-Github-Delivery')
- **`receiver.content-types`** (covered, P1, `offline`): content types: exactly application/json, or application/x-www-form-urlencoded with a 'payload' field; anything else (also a charset parameter) answers 415
    - Source: `otterdog/webapp/webhook/github_webhook.py:84-97`
    - Operations: api, error
    - Known bugs: KB-060
    - Notes: Form ping 204 + described; charset and text/plain 415 with 'Unknown content type ...'
- **`receiver.empty-body`** (covered, P2, `offline`): a JSON body 'null' answers 400 'Request body must contain data'
    - Source: `otterdog/webapp/webhook/github_webhook.py:99-101`
    - Operations: api, error
    - Notes: null body 400 'Request body must contain data' (+ 'rejecting webhook delivery &lt;id&gt; for event 'ping': empty body' with #775); undecodable JSON 400 'Failed to decode JSON'
- **`receiver.accepted`** (covered, P0, `offline`): valid deliveries answer 204 whatever the hooks do: ping, events nobody handles, unknown installations ("received event for unknown installation '&lt;id&gt;'")
    - Source: `otterdog/webapp/webhook/github_webhook.py:103-121`, `otterdog/webapp/webhook/__init__.py:423-429`
    - Operations: api, event
    - Known bugs: KB-017
    - Notes: a redelivery (same bytes and X-GitHub-Delivery) is accepted and processed again (no deduplication)
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`receiver.hook-exception`** (covered, P2, `offline`): an exception in a hook is logged with the delivery context ('failed to process webhook delivery &lt;id&gt; for event ...') and propagates (500)
    - Source: `otterdog/webapp/webhook/github_webhook.py:106-119`, `otterdog/webapp/webhook/github_webhook.py:209-226`
    - Operations: api, error
    - Notes: MongoDB stopped: pull_request 500 and (with #775) 'failed to process webhook delivery &lt;id&gt; for event 'pull_request' in hook 'on_pull_request_received': action='opened', ...'; recovered after start_service
- **`receiver.event-logging`** (covered, P2, `offline`): event descriptions are logged per delivery; formatting errors never block processing; workflow_job/workflow_run are only logged for queued/completed
    - Source: `otterdog/webapp/webhook/github_webhook.py:123-147`, `otterdog/webapp/webhook/github_webhook.py:196-206`
    - Operations: event
    - Notes: The outline's sender-null pull_request fails the pydantic model; the tests use a push with pusher null (TypeError path, processed by the push hook) and a push without pusher (KeyError path, debug only)

<a id="webapp-events"></a>

## Webapp webhook event routing

`webapp-events`: 10 features, 9 covered, 1 partial, 0 gaps (weighted 95%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-events.pr-opened` | pull_request opened on the config repo: UpdatePullRequestTask; non-draft: help comment, team membership, validation and sync check | webapp | free | P0 | covered | live | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_pr_validation.py::test_invalid_config_pr`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed` |
| `webapp-events.pr-synchronize` | pull_request synchronize (new commits): re-validation and sync check of the new head (sync status propagated from the previous commit within an hour) | webapp | free | P0 | covered | live | `tests/webapp/test_pr_validation.py::test_new_commits_are_validated_again` |
| `webapp-events.pr-draft` | draft pull requests: converted_to_draft only updates the record; ready_for_review triggers help, team membership, validation and sync check; drafts are never validated on open | webapp | free | P1 | covered | live | `tests/webapp/test_stale_status.py::test_stale_snapshot_keeps_merged_status`, `tests/webapp/test_pr_validation.py::test_draft_pr_lifecycle` |
| `webapp-events.pr-reopened` | pull_request reopened: re-validation and sync check; otterdog/\* branches also refresh their blueprint status | webapp | free | P2 | covered | live | `tests/webapp/test_pr_validation.py::test_closed_pr_is_validated_again_when_reopened`, `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint` |
| `webapp-events.pr-closed` | pull_request closed: merged into the default branch -&gt; ApplyChangesTask; closed unmerged -&gt; record closed; otterdog/\* head branches are deleted and their blueprint status updated | webapp | free | P0 | covered | live | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_closed_prs_are_never_applied`, `tests/webapp/test_otterdog_branches.py::test_otterdog_branches_are_deleted` |
| `webapp-events.review` | pull_request_review submitted / edited / dismissed: UpdatePullRequestTask with the review (approvals recomputed, auto-merge offered when eligible) | webapp | free | P1 | **partial** | live | `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_merge_apply.py::test_dismissed_approval_blocks_the_merge` |
| `webapp-events.issue-comment` | issue_comment created / edited on a config-repo pull request: the first matching /otterdog command runs (issues and other repositories are ignored) | webapp | free | P1 | covered | live | `tests/webapp/test_commands.py::test_help_command`, `tests/webapp/test_commands.py::test_validate_command`, `tests/webapp/test_commands.py::test_comment_matching_and_edits` |
| `webapp-events.push` | push to the default branch: config repo -&gt; FetchConfigTask (+ policies/blueprints reload when otterdog/policies or otterdog/blueprints change); any repo -&gt; re-evaluate matching blueprints; the configs repo -&gt; reload otterdog.json and every installation | webapp | free | P0 | covered | live | `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_blueprints.py::test_global_definitions_reload_on_configs_push`, `tests/webapp/test_blueprints.py::test_required_file_remediation` |
| `webapp-events.installation` | installation created / deleted / suspend / unsuspend: installation status NOT_INSTALLED, SUSPENDED, INSTALLED (+ data refresh) | webapp | free | P2 | covered | live | `tests/webapp/test_installation_events.py::test_installation_events_update_the_record` |
| `webapp-events.workflow-events` | workflow_job queued -&gt; macos_large_runners policy; workflow_run completed -&gt; dependency_track_upload policy | webapp | free | P2 | covered | offline, live | `tests/webapp/test_policies.py::test_macos_large_runner_jobs_are_cancelled_unless_allowed`, `tests/webapp/test_policies.py::test_sbom_upload_to_dependency_track`, `tests/offline/test_webapp_contract.py::test_workflow_events_are_described_selectively` |

Details:

- **`webapp-events.pr-opened`** (covered, P0, `webapp`): pull_request opened on the config repo: UpdatePullRequestTask; non-draft: help comment, team membership, validation and sync check
    - Source: `otterdog/webapp/webhook/__init__.py:112-174`
    - Operations: event, task
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.pr-synchronize`** (covered, P0, `webapp`): pull_request synchronize (new commits): re-validation and sync check of the new head (sync status propagated from the previous commit within an hour)
    - Source: `otterdog/webapp/webhook/__init__.py:151-174`, `otterdog/webapp/tasks/check_sync.py:89-122`
    - Operations: event, task, status
    - Notes: W-PR-SYNCHRONIZE (P0): three commits, a validate comment per head sha (previous minimized), success/success/error, /api valid false after the broken commit; the sync status of commits 2 and 3 is copied (one non-pending status, no pending one).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.pr-draft`** (covered, P1, `webapp`): draft pull requests: converted_to_draft only updates the record; ready_for_review triggers help, team membership, validation and sync check; drafts are never validated on open
    - Source: `otterdog/webapp/webhook/__init__.py:112-174`
    - Operations: event, task
    - Notes: W-PR-DRAFT (P1): draft opened -&gt; record only (draft true, no comment, no status, delivery+quiesce); mark_ready -&gt; help, team-info, validate comments, success, sync, draft false; convert_to_draft -&gt; draft true, no new comment/status.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.pr-reopened`** (covered, P2, `webapp`): pull_request reopened: re-validation and sync check; otterdog/\* branches also refresh their blueprint status
    - Source: `otterdog/webapp/webhook/__init__.py:99-107`, `otterdog/webapp/webhook/__init__.py:151-174`
    - Operations: event, task
    - Notes: W-PR-REOPEN (P2): unmerged close drops the /api record, no ApplyChangesTask/apply comment; reopen -&gt; open record (not_applied), new validate comment for the same sha, a second pending validation status. The otterdog/\* blueprint-status part is exercised by W-BP-DISMISS (reopen of a remediation PR).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.pr-closed`** (covered, P0, `webapp`): pull_request closed: merged into the default branch -&gt; ApplyChangesTask; closed unmerged -&gt; record closed; otterdog/\* head branches are deleted and their blueprint status updated
    - Source: `otterdog/webapp/webhook/__init__.py:89-107`, `otterdog/webapp/webhook/__init__.py:176-187`
    - Operations: event, task
    - Notes: W-PR-CLOSED (P0): an unmerged close (record gone, no ApplyChangesTask, no apply comment, repo not created) and a PR merged into a side base branch (recorded merged/not_applied, no ApplyChangesTask, no comment, repo not created). W-OPEN-PR-BRANCH covers the otterdog/\* branch deletion.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.review`** (partial, P1, `webapp`): pull_request_review submitted / edited / dismissed: UpdatePullRequestTask with the review (approvals recomputed, auto-merge offered when eligible)
    - Source: `otterdog/webapp/webhook/__init__.py:192-221`, `otterdog/webapp/tasks/update_pull_request.py:45-55`
    - Operations: event, task, permission
    - Notes: W-AUTOMERGE-DISMISS (P1): REQUEST_CHANGES -&gt; has_required_approvals false (no offer), approval -&gt; true + automerge comment, admin dismissal -&gt; false, /otterdog merge refused ('No approval from a member of'), PR open.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-REVIEW-EDITED` in `tests/webapp/test_merge_apply.py`
    - Steps:
        - approved contributor PR; the approver edits the review body
    - Assert:
        - a pull_request_review 'edited' delivery is handled (UpdatePullRequestTask, has_required_approvals unchanged)
    - Needs:
        - webapp
        - identities approver, author
        - harness: Mutator.edit_review (PUT /repos/{o}/{r}/pulls/{n}/reviews/{id}) and ConfigRepoFlow.edit_review
- **`webapp-events.issue-comment`** (covered, P1, `webapp`): issue_comment created / edited on a config-repo pull request: the first matching /otterdog command runs (issues and other repositories are ignored)
    - Source: `otterdog/webapp/webhook/__init__.py:224-249`, `otterdog/webapp/webhook/comment_handlers.py:36-37`
    - Operations: event, comment
    - Notes: W-CMD-NEG (P1): edited comment re-runs its command (new help comment, previous minimized), deleted comment ignored (delivery observed + quiesce), synthetic issue_comment on an issue of the config repo and on a PR of another repository schedule no task.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.push`** (covered, P0, `webapp`): push to the default branch: config repo -&gt; FetchConfigTask (+ policies/blueprints reload when otterdog/policies or otterdog/blueprints change); any repo -&gt; re-evaluate matching blueprints; the configs repo -&gt; reload otterdog.json and every installation
    - Source: `otterdog/webapp/webhook/__init__.py:252-336`, `otterdog/webapp/tasks/fetch_config.py:66-114`
    - Operations: event, task, state
    - Known bugs: KB-015
    - Notes: W-MERGE-APPLY waits for the relayed push of the merge commit, a finished FetchConfigTask created after the merge and /api/organizations/&lt;org&gt; listing the new repository with its description (the stored sha is the blob sha and is not exposed by the API). A push to the configs repository reloading the global definitions is W-BP-GLOBAL-PUSH (KB-015, scoped xfail), a push to a project repository re-evaluating blueprints is W-BP-REQUIRED-FILE (a deleted strict file is re-added at once); the boot checks the FetchConfigTask of /internal/init.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.installation`** (covered, P2, `webapp`): installation created / deleted / suspend / unsuspend: installation status NOT_INSTALLED, SUSPENDED, INSTALLED (+ data refresh)
    - Source: `otterdog/webapp/webhook/__init__.py:339-348`, `otterdog/webapp/db/service.py:71-117`
    - Operations: event, state
    - Notes: W-INSTALLATION-EVENTS (P2): signed synthetic installation deliveries for the real id: suspend -&gt; suspended, unsuspend -&gt; installed + finished FetchConfigTask and FetchAllPullRequestsTask, deleted -&gt; not_installed with id 0, created -&gt; installed with the real id + refresh; /internal/init restores on failure. Routing verified against the 9bdeb75 image locally.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-events.workflow-events`** (covered, P2, `webapp`): workflow_job queued -&gt; macos_large_runners policy; workflow_run completed -&gt; dependency_track_upload policy
    - Source: `otterdog/webapp/webhook/__init__.py:351-420`
    - Operations: event, task
    - Notes: workflow_job queued: W-POL-MACOS (the run on a macOS larger runner is cancelled unless allowed, the /admin/policies counters change); workflow_run completed: W-POL-SBOM (UploadSBOMTask, PUT /api/v1/bom of the Dependency-Track mock); offline, the receiver describes workflow_job only when queued and workflow_run only when completed.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)

<a id="webapp-commands"></a>

## Pull request comment commands

`webapp-commands`: 9 features, 8 covered, 1 partial, 0 gaps (weighted 94%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-commands.help` | /otterdog help (and on every non-draft PR opened by a user, never a bot): help comment listing the commands, previous one minimized | webapp | free | P1 | covered | live | `tests/webapp/test_commands.py::test_help_command`, `tests/webapp/test_pr_validation.py::test_valid_config_pr` |
| `webapp-commands.team-info` | /otterdog team-info (and on PR open): the author's org membership and teams; sets author_can_auto_merge (bot authors skipped) | webapp | free | P1 | **partial** | live | `tests/webapp/test_commands.py::test_team_info_command`, `tests/webapp/test_pr_validation.py::test_draft_pr_lifecycle` |
| `webapp-commands.check-sync` | /otterdog check-sync: re-runs the sync check now (no 1-hour propagation for comments) | webapp | free | P1 | covered | live | `tests/webapp/test_commands.py::test_drift_check_sync` |
| `webapp-commands.done` | /otterdog done by an admin team member marks a merged, not completed PR as completed (done comment); other users get the wrong-team comment | webapp | free | P1 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_secret_needs_a_manual_apply` |
| `webapp-commands.apply` | /otterdog apply by an admin team member re-applies a merged, valid, not completed PR (e.g. after a failed apply); others get the wrong-team comment | webapp | free | P1 | covered | live | `tests/webapp/test_merge_apply.py::test_failed_apply_is_retried_by_an_admin`, `tests/webapp/test_merge_apply.py::test_secret_needs_a_manual_apply` |
| `webapp-commands.merge` | /otterdog merge: merges an eligible PR on behalf of its author (or a member of the approval/admin teams); otherwise the automerge problems comment | webapp | free | P0 | covered | live | `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |
| `webapp-commands.validate` | /otterdog validate: re-validates the head (WARN level), new validate comment, previous minimized | webapp | free | P1 | covered | live | `tests/webapp/test_commands.py::test_validate_command` |
| `webapp-commands.validate-info` | /otterdog validate info: validation at INFO level (Info notices included in the validate comment) | webapp | free | P2 | covered | live | `tests/webapp/test_commands.py::test_validate_info_command` |
| `webapp-commands.matching` | command matching: re.match at the start of the comment, no word boundary ('/otterdog helpme' runs help), first handler wins, text after the command ignored | webapp | free | P2 | covered | live | `tests/webapp/test_commands.py::test_comment_matching_and_edits` |

Details:

- **`webapp-commands.help`** (covered, P1, `webapp`): /otterdog help (and on every non-draft PR opened by a user, never a bot): help comment listing the commands, previous one minimized
    - Source: `otterdog/webapp/webhook/comment_handlers.py:48-62`, `otterdog/webapp/tasks/help_comment.py:46-85`
    - Operations: comment, task
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-commands.team-info`** (partial, P1, `webapp`): /otterdog team-info (and on PR open): the author's org membership and teams; sets author_can_auto_merge (bot authors skipped)
    - Source: `otterdog/webapp/webhook/comment_handlers.py:65-81`, `otterdog/webapp/tasks/retrieve_team_membership.py:46-110`
    - Operations: comment, task, permission
    - Known bugs: KB-017, KB-027
    - Notes: W-CMD-TEAM-INFO (P1): contributor PR -&gt; team-info comment (author link, role == GitHub author_association, contributors team link, no admin/approval team), /api author_can_auto_merge false; /otterdog team-info -&gt; new comment, first minimized.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-CMD-TEAM-INFO-BOT` in `tests/webapp/test_commands.py`
    - Steps:
        - a PR opened by the e2e App (a blueprint remediation PR of the config repository)
    - Assert:
        - no help and no team-info comment for the bot-authored PR
    - Needs:
        - webapp
        - app
- **`webapp-commands.check-sync`** (covered, P1, `webapp`): /otterdog check-sync: re-runs the sync check now (no 1-hour propagation for comments)
    - Source: `otterdog/webapp/webhook/comment_handlers.py:84-98`, `otterdog/webapp/tasks/check_sync.py:58-61`
    - Operations: comment, task
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-commands.done`** (covered, P1, `webapp`): /otterdog done by an admin team member marks a merged, not completed PR as completed (done comment); other users get the wrong-team comment
    - Source: `otterdog/webapp/webhook/comment_handlers.py:101-116`, `otterdog/webapp/tasks/complete_pull_request.py:35-94`
    - Operations: comment, task, permission, state
    - Known bugs: KB-013
    - Notes: Wrong-team /otterdog done of a contributor (comment naming &lt;org&gt;/&lt;admin team&gt;, apply_status stays partially_applied) is in W-MERGE-SECRET instead of the suggested W-CMD-DONE-WRONG-TEAM (same partial-apply flow, keeps the catalogue test W-PR-WEBUI identity-free).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-commands.apply`** (covered, P1, `webapp`): /otterdog apply by an admin team member re-applies a merged, valid, not completed PR (e.g. after a failed apply); others get the wrong-team comment
    - Source: `otterdog/webapp/webhook/comment_handlers.py:119-134`, `otterdog/webapp/tasks/apply_changes.py:88-132`
    - Operations: comment, task, permission
    - Known bugs: KB-001, KB-013
    - Notes: W-CMD-APPLY (P1): repo created out of band -&gt; merged PR's apply fails ([!CAUTION], 'failed to apply patch', partially_applied); contributor /otterdog apply -&gt; wrong_team_apply_comment, record unchanged; repo removed -&gt; admin /otterdog apply -&gt; success, repo created with the declared description, completed; /otterdog apply of a completed PR -&gt; ApplyChangesTask finished, no comment. Note: a failed apply is recorded partially_applied (ApplyStatus.FAILED only for exceptions outside the local-apply).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-commands.merge`** (covered, P0, `webapp`): /otterdog merge: merges an eligible PR on behalf of its author (or a member of the approval/admin teams); otherwise the automerge problems comment
    - Source: `otterdog/webapp/webhook/comment_handlers.py:137-152`, `otterdog/webapp/tasks/merge_pull_request.py:44-144`
    - Operations: comment, task, permission
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-commands.validate`** (covered, P1, `webapp`): /otterdog validate: re-validates the head (WARN level), new validate comment, previous minimized
    - Source: `otterdog/webapp/webhook/comment_handlers.py:155-176`
    - Operations: comment, task, status
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-commands.validate-info`** (covered, P2, `webapp`): /otterdog validate info: validation at INFO level (Info notices included in the validate comment)
    - Source: `otterdog/webapp/webhook/comment_handlers.py:157-175`
    - Operations: comment, task
    - Notes: W-CMD-VALIDATE-INFO (P2): dummy repo secret: default comment has 'there have been N validation infos' and no Info line; /otterdog validate info prints 'repo_secret[name=...] only has a dummy value, resource will be skipped.' and no hint; first comment minimized.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-commands.matching`** (covered, P2, `webapp`): command matching: re.match at the start of the comment, no word boundary ('/otterdog helpme' runs help), first handler wins, text after the command ignored
    - Source: `otterdog/webapp/webhook/comment_handlers.py:36-37`, `otterdog/webapp/webhook/__init__.py:61-69`, `otterdog/webapp/webhook/__init__.py:242-247`
    - Operations: comment, event
    - Notes: W-CMD-NEG (P1) instead of the separate W-CMD-MATCHING/W-CMD-EDITED (one PR, the docs/scenario-catalog.md planned id): 'please /otterdog help' ignored, '/otterdog validate' validates, '/otterdog helpme, ...' helps (prefix match), '/otterdog validate\n/otterdog help' runs validate only. All cases also verified against the 9bdeb75 webapp image locally.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)

<a id="webapp-pr"></a>

## Pull request validation, sync check and apply

`webapp-pr`: 16 features, 14 covered, 2 partial, 0 gaps (weighted 94%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-pr.validation` | validation: local-plan of the PR head against the default branch HEAD, validate comment (plan output escaped), status success / error on the head sha | webapp | free | P0 | covered | live | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_pr_validation.py::test_invalid_config_pr`, `tests/webapp/test_commands.py::test_validate_command` |
| `webapp-pr.outdated-branch` | a PR whose branch predates a change of main: validated on the merge commit GitHub creates (diff against its first parent, 'Diff for &lt;head&gt; merged into &lt;main&gt;'), so the change of main is not shown reverted; without merge commit (conflict, GitHub too slow) the head is validated against main with the warning 'The branch of this pull request is not up-to-date' (#950, main 7f4235b after v1.8.0) | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_outdated_branch_is_validated_as_merged` |
| `webapp-pr.pending-statuses` | pending statuses are set first: 'validating configuration change using otterdog' and 'checking if configuration is in-sync using otterdog' | webapp | free | P2 | covered | live | `tests/webapp/test_pr_validation.py::test_valid_config_pr` |
| `webapp-pr.validation-failure` | a crashing validation task: status failure 'otterdog validation failed, please contact an admin'; evaluation exceptions give the friendly comment 'Validation failed while evaluating the configuration. ...' | webapp | free | P1 | **partial** | live | `tests/webapp/test_pr_validation.py::test_evaluation_error_gets_a_friendly_comment` |
| `webapp-pr.validation-warnings` | validation warnings: changes requiring secrets, the web UI or that may incur costs (max_cache_size_gb) are listed and block auto-merge | webapp | free | P1 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_pr_validation.py::test_validation_warnings` |
| `webapp-pr.no-changes` | a PR whose org file equals the base: 'No changes.' and success without running local-plan; PRs touching other files never auto-merge | webapp | free | P2 | covered | live | `tests/webapp/test_pr_validation.py::test_non_configuration_change` |
| `webapp-pr.import-confinement` | jsonnet imports are confined to the org directory during validation, sync check and apply (an import of '../../x' fails) | webapp | free | P1 | **partial** | live | `tests/webapp/test_pr_validation.py::test_imports_are_confined_to_the_org_directory` |
| `webapp-pr.sync-check` | sync check: plan of the default branch HEAD against GitHub; out of sync -&gt; check-sync comment and description 'otterdog sync check failed, check comment history' with state success (informational) | webapp | free | P0 | covered | live | `tests/webapp/test_commands.py::test_drift_check_sync`, `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_commands.py::test_sync_check_of_an_invalid_main` |
| `webapp-pr.sync-failure` | a crashing sync check sets state failure with the description 'otterdog detected out of sync changes, but they will not prevent a successful merge' | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_commands.py::test_sync_check_crash` |
| `webapp-pr.sync-propagation` | sync check throttling: on synchronize within an hour of the previous commit the previous final sync status is copied; sync tasks back off at least one minute | webapp | free | P2 | covered | live | `tests/webapp/test_pr_validation.py::test_new_commits_are_validated_again`, `tests/webapp/test_pr_validation.py::test_out_of_sync_status_survives_a_new_commit` |
| `webapp-pr.apply` | apply after merge: local-apply of the merge commit against its base commit (squash, rebase with several commits #773, merge commits), apply comment, apply_status completed | webapp | free | P0 | covered | live | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_merge_apply.py::test_merge_commit_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_drifted_org_still_auto_merges` |
| `webapp-pr.apply-deletions` | the webapp applies deletions (delete_resources=True): a merged PR removing an object deletes it on GitHub | webapp | free | P0 | covered | live | `tests/webapp/test_merge_apply.py::test_merged_removal_is_applied` |
| `webapp-pr.apply-partial` | patches needing secrets or the web UI are skipped by the webapp (no web UI, include_resources_with_secrets false): apply_status partially_applied, comment 'only partially applied ...', completed by /otterdog done | webapp | free | P1 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_secret_needs_a_manual_apply` |
| `webapp-pr.apply-guards` | apply is skipped for unmerged, already completed or invalid PRs; a failed or crashed apply is recorded partially_applied with 'Applying the configuration failed. ...' | webapp | free | P1 | covered | live | `tests/webapp/test_merge_apply.py::test_invalid_merged_pr_is_not_applied`, `tests/webapp/test_merge_apply.py::test_failed_apply_is_retried_by_an_admin`, `tests/webapp/test_merge_apply.py::test_crashing_apply_gets_a_friendly_comment`, `tests/webapp/test_merge_apply.py::test_closed_prs_are_never_applied` |
| `webapp-pr.records` | pull request records (/api/pullrequests): status open/closed/merged, draft, valid, in_sync, requires_manual_apply, supports_auto_merge, author_can_auto_merge, has_required_approvals, apply_status | webapp | free | P1 | covered | live | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |
| `webapp-pr.delete-otterdog-branch` | closing a PR whose head branch starts with 'otterdog/' deletes the branch (open-pr and blueprint remediation branches) | webapp | free | P2 | covered | live | `tests/webapp/test_otterdog_branches.py::test_otterdog_branches_are_deleted` |

Details:

- **`webapp-pr.validation`** (covered, P0, `webapp`): validation: local-plan of the PR head against the default branch HEAD, validate comment (plan output escaped), status success / error on the head sha
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:143-298`, `otterdog/webapp/tasks/validate_pull_request.py:322-338`
    - Operations: task, status, comment, validate
    - Known bugs: KB-026
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.outdated-branch`** (covered, P1, `webapp`): a PR whose branch predates a change of main: validated on the merge commit GitHub creates (diff against its first parent, 'Diff for &lt;head&gt; merged into &lt;main&gt;'), so the change of main is not shown reverted; without merge commit (conflict, GitHub too slow) the head is validated against main with the warning 'The branch of this pull request is not up-to-date' (#950, main 7f4235b after v1.8.0)
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:143-298`
    - Operations: task, comment, validate
    - Notes: W-PR-OUTDATED-BRANCH: main changes the description of a declared run repository after the PR branch was created; a second commit on the stale branch must be validated as merged into the new main (no phantom revert of that description), a third commit conflicting with main gets the not up-to-date warning. The run repository spans three lines, so the change of main and the PR's change right after it are not adjacent: on one line they conflicted, GitHub created no merge commit and #950 fell back to the head (nightly 45451116543, branch:main, reported as an xfail). Webapps without #950 (release:latest) show the phantom revert: non-strict xfail scoped to OutdatedBranchRevertError (eclipse-score/.eclipsefdn#257); webapps with it (its squash commit or the last head of its pull request) run strict. Not run here: needs the webapp tier.
- **`webapp-pr.pending-statuses`** (covered, P2, `webapp`): pending statuses are set first: 'validating configuration change using otterdog' and 'checking if configuration is in-sync using otterdog'
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:300-309`, `otterdog/webapp/tasks/check_sync.py:210-219`
    - Operations: status
    - Notes: W-PR-VALID lists every commit status (GET .../commits/{sha}/statuses): first validation status pending 'validating configuration change using otterdog', last success; first sync status pending 'checking if configuration is in-sync using otterdog', last success.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.validation-failure`** (partial, P1, `webapp`): a crashing validation task: status failure 'otterdog validation failed, please contact an admin'; evaluation exceptions give the friendly comment 'Validation failed while evaluating the configuration. ...'
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:245-254`, `otterdog/webapp/tasks/validate_pull_request.py:311-320`
    - Operations: status, error, comment
    - Known bugs: KB-008, KB-025, KB-032
    - Notes: W-PR-EVAL-ERROR (P1) uses a team_permissions value outside the schema enum (uncaught jsonschema error, KB-032) instead of 'pass:a:b': the config guard refuses the KB-025 crash (no load error in its output). Asserts the friendly 'Validation failed while evaluating the configuration.' + 'Please contact an admin...', no 'Traceback'/'Failed validating'/value, status error, /api valid false.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-PR-VALIDATION-CRASH` in `tests/webapp/test_pr_validation.py`
    - Steps:
        - a never-merged PR whose head deletes otterdog/&lt;org&gt;.jsonnet (the validation task crashes)
    - Assert:
        - commit status 'failure' with 'otterdog validation failed, please contact an admin'
    - Needs:
        - webapp
        - harness: ConfigRepoFlow opt-in to open a PR deleting the org configuration (refused today)
- **`webapp-pr.validation-warnings`** (covered, P1, `webapp`): validation warnings: changes requiring secrets, the web UI or that may incur costs (max_cache_size_gb) are listed and block auto-merge
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:227-268`, `otterdog/models/__init__.py:170-208`, `otterdog/config.py:453-471`
    - Operations: validate, comment, permission
    - Notes: W-PR-WARNINGS (P1): secret -&gt; secrets warning, requires_manual_apply true, supports_auto_merge false; max_cache_size_gb 10 -&gt; 5 on a declared repo (main pins 10 with ':::' so the diff exists also when the renderer hides the cache limit) -&gt; cost warning, supports_auto_merge false, no manual apply; both refused by /otterdog merge; new repo with 10 GB -&gt; no warning, auto-merge offered.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.no-changes`** (covered, P2, `webapp`): a PR whose org file equals the base: 'No changes.' and success without running local-plan; PRs touching other files never auto-merge
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:203-212`, `otterdog/webapp/tasks/validate_pull_request.py:346-350`
    - Operations: validate, permission
    - Notes: W-PR-NO-CHANGES (P2): README.md-only PR -&gt; 'No changes.' + success; multi-file PR (org config + README.md) -&gt; validated on its config change; both valid, supports_auto_merge false, no automerge comment, /otterdog merge refused naming 'touches non-configuration files'.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.import-confinement`** (partial, P1, `webapp`): jsonnet imports are confined to the org directory during validation, sync check and apply (an import of '../../x' fails)
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:238-242`, `otterdog/webapp/tasks/apply_changes.py:205-209`, `otterdog/webapp/tasks/check_sync.py:171-174`, `CHANGELOG.md:316`
    - Operations: validate, security
    - Notes: W-PR-IMPORT-CONFINEMENT (P1): importstr '../e2e-&lt;run&gt;-...-outside.libsonnet' (exists nowhere): comment shows 'failed to load configuration' + "import of '../...' is not allowed" (an unconfined evaluation says "can't resolve": strict xfail on SUTs before 326d62d), status error, /api valid false. Message verified with the 1.7.0.dev19 code.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-SYNC-IMPORT-CONFINEMENT` in `tests/webapp/test_commands.py`
    - Steps:
        - main importing a file outside the org directory; /otterdog check-sync and a merged PR
    - Assert:
        - the sync check and the apply refuse the import ("import of '../...' is not allowed")
    - Needs:
        - webapp
        - harness: an audited 'restore main to the baseline' path for tests that break main on purpose
- **`webapp-pr.sync-check`** (covered, P0, `webapp`): sync check: plan of the default branch HEAD against GitHub; out of sync -&gt; check-sync comment and description 'otterdog sync check failed, check comment history' with state success (informational)
    - Source: `otterdog/webapp/tasks/check_sync.py:139-208`, `otterdog/webapp/tasks/check_sync.py:232-269`
    - Operations: task, status, comment
    - Known bugs: KB-019, KB-067
    - Notes: W-PR-VALID asserts the in-sync outcome ('otterdog sync check completed successfully', state success, no check-sync comment); W-DRIFT-CHECKSYNC the out-of-sync one.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.sync-failure`** (covered, P2, `webapp`): a crashing sync check sets state failure with the description 'otterdog detected out of sync changes, but they will not prevent a successful merge'
    - Source: `otterdog/webapp/tasks/check_sync.py:133-137`, `otterdog/webapp/tasks/check_sync.py:221-230`
    - Operations: status, error
    - Known bugs: KB-040
    - New findings: F-13
    - Notes: W-SYNC-FAILURE (P2): main without its org config file makes the sync check raise (404 when it reads main's config; a main that fails to load is reported in sync since 1.7.0, KB-067): state failure, failed CheckConfigurationInSyncTask (on open and after /otterdog check-sync), no check-sync comment, in_sync never set; the misleading 'detected out of sync changes' description is a scoped xfail (MisleadingSyncFailureError, known_bug KB-040).
- **`webapp-pr.sync-propagation`** (covered, P2, `webapp`): sync check throttling: on synchronize within an hour of the previous commit the previous final sync status is copied; sync tasks back off at least one minute
    - Source: `otterdog/webapp/tasks/check_sync.py:89-127`
    - Operations: status, task
    - Known bugs: KB-066
    - Notes: Propagation observed as one non-pending sync status on the new head (no pending, same state/description). Note: the CheckConfigurationInSyncTask is still recorded (finished) when it copies, so the outline's 'task count unchanged' is wrong. W-SYNC-PROPAGATION-DRIFT is a scoped xfail of KB-066 (copied out-of-sync status becomes 'completed successfully').
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.apply`** (covered, P0, `webapp`): apply after merge: local-apply of the merge commit against its base commit (squash, rebase with several commits #773, merge commits), apply comment, apply_status completed
    - Source: `otterdog/webapp/tasks/apply_changes.py:147-237`, `otterdog/webapp/utils.py:432-513`
    - Operations: task, comment, state, add
    - Notes: W-MERGE-COMMIT-APPLY (P0): merge method 'merge' (2-parent commit) applies both commits, both repos with their descriptions, completed. W-AUTOMERGE-DRIFT shows the apply replays only the PR diff (drift left untouched).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.apply-deletions`** (covered, P0, `webapp`): the webapp applies deletions (delete_resources=True): a merged PR removing an object deletes it on GitHub
    - Source: `otterdog/webapp/tasks/apply_changes.py:186-200`
    - Operations: task, remove
    - Notes: W-MERGE-DELETE (P0): declared run repo removed by a PR: validate comment 'remove repository[name=...]', supports_auto_merge false, no automerge comment, /otterdog merge refused; admin merge -&gt; apply comment names the removal, repo deleted (oracle), completed.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.apply-partial`** (covered, P1, `webapp`): patches needing secrets or the web UI are skipped by the webapp (no web UI, include_resources_with_secrets false): apply_status partially_applied, comment 'only partially applied ...', completed by /otterdog done
    - Source: `otterdog/webapp/tasks/apply_changes.py:134-145`, `otterdog/webapp/tasks/apply_changes.py:186-212`
    - Operations: task, state, comment
    - Notes: W-MERGE-SECRET (P1): new run repo with a secret: apply creates the repo, never the secret (oracle repo_secret None), 'only partially applied', partially_applied, completed by the admin's /otterdog done.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.apply-guards`** (covered, P1, `webapp`): apply is skipped for unmerged, already completed or invalid PRs; a failed or crashed apply is recorded partially_applied with 'Applying the configuration failed. ...'
    - Source: `otterdog/webapp/tasks/apply_changes.py:88-107`, `otterdog/webapp/tasks/apply_changes.py:213-221`
    - Operations: task, state, error
    - Known bugs: KB-001, KB-039
    - Notes: W-MERGE-INVALID (invalid topic: ApplyChangesTask finished without comment, nothing created, merged/not_applied), W-CMD-APPLY (already completed -&gt; skipped; patch failure), W-PR-CLOSED (unmerged). W-MERGE-APPLY-CRASH (P1): KB-039 '#Admin' bypass actor as trigger -&gt; [!CAUTION] with 'Applying the configuration failed.'/'Please contact an admin', no KeyError/Traceback, partially_applied, repo created, ruleset not (skips if KB-039 is fixed). Title correction: a failed or crashed apply is recorded partially_applied, not failed.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.records`** (covered, P1, `webapp`): pull request records (/api/pullrequests): status open/closed/merged, draft, valid, in_sync, requires_manual_apply, supports_auto_merge, author_can_auto_merge, has_required_approvals, apply_status
    - Source: `otterdog/webapp/db/models.py:81-127`, `otterdog/webapp/db/service.py:670-766`, `otterdog/webapp/tasks/update_pull_request.py:37-67`
    - Operations: state, api
    - Known bugs: KB-018
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-pr.delete-otterdog-branch`** (covered, P2, `webapp`): closing a PR whose head branch starts with 'otterdog/' deletes the branch (open-pr and blueprint remediation branches)
    - Source: `otterdog/webapp/webhook/__init__.py:89-97`, `otterdog/webapp/tasks/delete_branch.py:29-42`
    - Operations: task, event
    - Notes: W-OPEN-PR-BRANCH in tests/webapp (not tests/cli): PR opened with 'otterdog open-pr' (trusted reset CLI, fresh workspace, adopted by the flow) closed -&gt; finished DeleteBranchTask (no pull_request recorded) and the otterdog/e2e-&lt;run&gt;-\* branch gone.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)

<a id="webapp-automerge"></a>

## Auto-merge eligibility and merge

`webapp-automerge`: 4 features, 4 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-automerge.eligibility` | eligibility: open, validated and valid, supports_auto_merge, and (author in an approval/admin team OR an approval by such a member) | webapp | free | P0 | covered | live | `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_approval_team_author_merges_without_review` |
| `webapp-automerge.blockers` | auto-merge is refused when the PR contains secrets, needs the web UI, may incur costs, includes deletions or touches non-configuration files | webapp | free | P1 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_pr_validation.py::test_validation_warnings`, `tests/webapp/test_pr_validation.py::test_non_configuration_change`, `tests/webapp/test_merge_apply.py::test_merged_removal_is_applied` |
| `webapp-automerge.comment` | the auto-merge status: as soon as validation, sync check or a review make the PR eligible, the webapp posts the automerge comment once (when no unminimized one exists); since #965 (main 144eae5, after v1.8.0) it rewrites in place a 'Ready to merge' section of the last validate comment (empty while not eligible), and a legacy automerge comment is hidden by the next validation | webapp | free | P1 | covered | live | `tests/webapp/test_merge_apply.py::test_automerge_after_approval` |
| `webapp-automerge.third-party` | /otterdog merge by someone else than the author requires approval/admin team membership ('Only the author of the pull request, a member of ..., or a member of ... is allowed to auto-merge.') | webapp | free | P1 | covered | live | `tests/webapp/test_merge_apply.py::test_merge_command_of_a_third_party` |

Details:

- **`webapp-automerge.eligibility`** (covered, P0, `webapp`): eligibility: open, validated and valid, supports_auto_merge, and (author in an approval/admin team OR an approval by such a member)
    - Source: `otterdog/webapp/db/models.py:129-229`, `otterdog/webapp/tasks/__init__.py:328-346`
    - Operations: permission, state
    - Known bugs: KB-013, KB-027
    - Notes: W-AUTOMERGE-AUTHOR-TEAM (P0): approver-authored PR: author_can_auto_merge true, has_required_approvals None, automerge comment without review, /otterdog merge merges and applies; an invalid PR of the same author is refused ('pull request is not valid').
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-automerge.blockers`** (covered, P1, `webapp`): auto-merge is refused when the PR contains secrets, needs the web UI, may incur costs, includes deletions or touches non-configuration files
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:340-386`, `otterdog/webapp/db/models.py:182-189`
    - Operations: permission
    - Notes: Each blocker is asserted in the test of its change type (secret, cost, README/multi-file, deletion, web UI) with admin-authored (eligible) PRs: no automerge comment after quiesce, /otterdog merge refused with the supports_auto_merge sentence, PR open. No separate W-AUTOMERGE-BLOCKERS (would duplicate those PRs). Since #943 (main 127c063, after v1.8.0) the validate comment lists the blockers ('&gt; [!NOTE]' 'This pull request cannot be auto-merged via `/otterdog merge`:', one reason per line) and mentions the admin team: WebappScenario.assert_merge_blockers in the same tests, and W-PR-VALID / the new repository of W-PR-WARNINGS get no note and no cc.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-automerge.comment`** (covered, P1, `webapp`): the auto-merge status: as soon as validation, sync check or a review make the PR eligible, the webapp posts the automerge comment once (when no unminimized one exists); since #965 (main 144eae5, after v1.8.0) it rewrites in place a 'Ready to merge' section of the last validate comment (empty while not eligible), and a legacy automerge comment is hidden by the next validation
    - Source: `otterdog/webapp/tasks/auto_merge_comment.py:35-60`, `otterdog/webapp/tasks/auto_merge_comment.py:86-145`, `otterdog/webapp/templates/comment/validation_comment.txt:1-3`, `otterdog/webapp/templates/comment/auto_merge_status.txt:1-6`
    - Operations: comment, task
    - Notes: W-AUTOMERGE: the eligibility signal is the automerge comment on webapps before #965 and the 'Ready to merge' auto-merge status section of the validate comment since (tests/webapp/conftest.py FEATURE_965, auto_merge_status); before #965 the task posted a separate comment headed '&lt;!-- Otterdog Comment: automerge --&gt;' from templates/comment/auto_merge_comment.txt, which #965 removed.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-automerge.third-party`** (covered, P1, `webapp`): /otterdog merge by someone else than the author requires approval/admin team membership ('Only the author of the pull request, a member of ..., or a member of ... is allowed to auto-merge.')
    - Source: `otterdog/webapp/tasks/merge_pull_request.py:79-97`
    - Operations: permission, comment
    - Known bugs: KB-027
    - Notes: W-AUTOMERGE-THIRD-PARTY (P1): approved contributor PR: the outsider's /otterdog merge -&gt; 'Only the author of the pull request, a member of ..., or a member of ... is allowed to auto-merge.', open; the approver's /otterdog merge -&gt; merged and applied.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)

<a id="webapp-runtime"></a>

## Webapp boot, init, API and pages

`webapp-runtime`: 22 features, 16 covered, 3 partial, 3 gaps (weighted 80%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-runtime.boot` | the webapp container boots with MongoDB and Valkey/Redis (dummy App credentials suffice), GET /internal/health answers 200, the /index footer shows 'OtterDog - v&lt;version&gt;' | offline | free | P0 | covered | offline, live | `tests/offline/test_webapp_contract.py::test_webapp_boots_with_dummy_credentials`, `tests/webapp/test_boot.py::test_webapp_boot` |
| `webapp-runtime.ready` | GET /internal/ready (#949, main after v1.8.0): MongoDB, Redis and ghproxy (TCP connect) checked within 2 s each, the result reused 5 s; 200 {status: ok, checks} when all are reachable, 503 {status: error} with {status: error, error: &lt;exception type&gt;} for the others; /internal/health stays the liveness probe | offline | free | P2 | covered | offline | `tests/offline/test_webapp_runtime.py::test_readiness_reports_each_dependency` |
| `webapp-runtime.internal-once` | /internal/init and /internal/check run once at a time across the workers (#949): a Redis lease (internal-init, internal-check; 300 s, renewed; the init keeps it until its installation tasks completed, 1 h at most) and 429 {status: '&lt;what&gt; is already running'} with Retry-After 60 while it is held | offline | free | P2 | covered | offline | `tests/offline/test_webapp_runtime.py::test_init_and_check_run_once_at_a_time`, `tests/offline/test_webapp_runtime.py::test_database_outage` |
| `webapp-runtime.config` | environment configuration: GITHUB_APP_ID/PRIVATE_KEY, GITHUB_WEBHOOK_SECRET/ENDPOINT, validation and sync status contexts, GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS (regex patterns), OTTERDOG_CONFIG_OWNER/REPO/PATH/TOKEN, MONGO_URI, REDIS_URI, GHPROXY_URI, BLUEPRINT_CHECK_INTERVAL, DEPENDENCY_TRACK_URL/TOKEN, CACHE_CONTROL | webapp | free | P1 | covered | offline, live | `tests/offline/test_webapp_contract.py::test_webapp_boots_with_dummy_credentials`, `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_runtime.py::test_organization_teams_override_the_environment`, `tests/webapp/test_runtime.py::test_admin_teams_list_with_spaces`, `tests/webapp/test_blueprints.py::test_check_interval_and_limit`, `tests/webapp/test_policies.py::test_sbom_upload_to_dependency_track` |
| `webapp-runtime.init` | GET /internal/init: reload otterdog.json, global policies and blueprints from the configs repo, sync the installation list (orgs not installed are NOT_INSTALLED), refresh data of active installations | webapp | free | P0 | covered | live | `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_runtime.py::test_init_imports_existing_pull_requests`, `tests/webapp/test_policies.py::test_policy_definitions_are_loaded_and_merged`, `tests/webapp/test_blueprints.py::test_blueprint_definitions_are_loaded` |
| `webapp-runtime.fetch-all-pull-requests` | FetchAllPullRequestsTask (on init/installation refresh) imports the config repo's existing pull requests (only those targeting 'main') | webapp | free | P2 | covered | live | `tests/webapp/test_runtime.py::test_init_imports_existing_pull_requests`, `tests/webapp/test_runtime.py::test_init_keeps_the_apply_status` |
| `webapp-runtime.internal-unknown` | GET /internal/&lt;anything else&gt; answers 404 {}; exceptions under /internal answer 500 {} | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_json_endpoints`, `tests/offline/test_webapp_runtime.py::test_database_outage` |
| `webapp-runtime.api-organizations` | GET /api/organizations ([{github_id, project_name}] of every installation row) and GET /api/organizations/&lt;github_id&gt; (stored configuration JSON, 404 until fetched) | webapp | free | P1 | covered | live | `tests/webapp/test_boot.py::test_webapp_boot` |
| `webapp-runtime.api-projects` | GET /api/projects/&lt;project_name&gt;: the stored configuration by project name (404 for unknown projects) | webapp | free | P2 | covered | live | `tests/webapp/test_runtime.py::test_project_api` |
| `webapp-runtime.api-tasks` | GET /api/tasks: paged task records (type, org_id, repo_name, pull_request, status, cache_stats, rate_limit_remaining) with regex filters, pageIndex/pageSize/sortField/sortOrder | webapp | free | P1 | covered | live | `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/webapp/test_boot.py::test_webapp_boot` |
| `webapp-runtime.api-pullrequests` | GET /api/pullrequests/open (open + merged-not-completed) and /api/pullrequests/merged (merged and completed), paged with id[...] filters | webapp | free | P1 | covered | live | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_stale_status.py::test_stale_snapshot_keeps_merged_status` |
| `webapp-runtime.api-statistics` | GET /api/pullrequests/statistics/progress?interval=day\|week\|month&range=7d\|14d\|30d\|90d\|6m\|12m\|all[&org=]: polled background job; 400 {'error': "unsupported interval '&lt;x&gt;'"} | offline | free | P2 | **partial** | offline | `tests/offline/test_webapp_contract.py::test_statistics_parameters` |
| `webapp-runtime.api-graphql` | GraphQL API: GET /api/graphql (explorer page), POST /api/graphql (queries over the stored data; invalid queries 400); /query page with the schema | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_graphql_api`, `tests/offline/test_webapp_contract.py::test_pages_need_no_login` |
| `webapp-runtime.pages-public` | public pages: / (redirect to /index), /robots.txt and /favicon.ico (static), /allprojects, /scorecard/checks, /&lt;name&gt;[.html] redirects to a known page or 404 page | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_redirects`, `tests/offline/test_webapp_contract.py::test_pages_need_no_login`, `tests/offline/test_webapp_contract.py::test_static_files`, `tests/offline/test_webapp_contract.py::test_not_found_page` |
| `webapp-runtime.pages-projects` | project pages: /organizations/&lt;org&gt;[/&lt;subpath&gt;] redirect to /projects/&lt;project&gt;[/&lt;subpath&gt;], /projects/&lt;project&gt; (+ /defaults, /playground, /repos/&lt;repo&gt;) render the stored configuration | webapp | free | P2 | covered | live | `tests/webapp/test_runtime.py::test_project_and_admin_pages` |
| `webapp-runtime.pages-admin` | admin pages without login: /admin/organizations (installation status), /admin/pullrequests, /admin/blueprints, /admin/policies (aggregated policy status), /admin/tasks | offline | free | P2 | covered | offline, live | `tests/offline/test_webapp_contract.py::test_pages_need_no_login`, `tests/offline/test_webapp_contract.py::test_admin_pages_of_an_empty_database`, `tests/webapp/test_runtime.py::test_project_and_admin_pages`, `tests/webapp/test_policies.py::test_macos_large_runner_jobs_are_cancelled_unless_allowed` |
| `webapp-runtime.login-required` | /myprojects needs a GitHub OAuth session: unauthenticated requests get the 401 page | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_login_required_page_without_session`, `tests/offline/test_webapp_runtime.py::test_login_required_page_with_oauth_configured` |
| `webapp-runtime.oauth-login` | GitHub OAuth login: /login -&gt; /github (authorize) -&gt; /github/authorized (user and project memberships stored in the session) -&gt; /logout | web_ui | free | P2 | **gap** | - | - |
| `webapp-runtime.playground-validation` | POST /playground/validate[?template=example] and /projects/&lt;project&gt;/playground/validate: the evaluated organization configuration is validated with otterdog; JSON rejections 400 (no JSON object), 413 (PLAYGROUND_VALIDATION_MAX_SIZE), 404 (unknown project), 503 (PLAYGROUND_MAX_CONCURRENT_VALIDATIONS) (#891) | webapp | free | P2 | **partial** | offline | `tests/offline/test_webapp_contract.py::test_playground_validation_refuses_malformed_requests` |
| `webapp-runtime.playground-pages` | GET /playground (instance or ?template=example template), /admin/template-impact and its /configurations JSON (projects using the default base template); the project playground is a CodeMirror page fed by a JSON script (#878) | webapp | free | P2 | **gap** | - | - |
| `webapp-runtime.installation-refresh-bound` | installation refresh tasks run behind MAX_CONCURRENT_INSTALLATION_TASKS per worker (default 10, checked at boot like the playground limits); /internal/init refreshes every installation once; HYPERCORN_WORKERS sets the workers (#843) | webapp | free | P2 | **gap** | - | - |
| `webapp-runtime.dashboard-theme` | #912 (941d284, in v1.8.0): the dashboard takes the documentation's theme (Eclipse colors, Inter bundled with the assets instead of Google Fonts, a dark mode following the system until the header toggle picks one); the projects pages show a card per organization (facts, protections, activity, filters and orders kept in the address); FetchConfigTask reads the configuration at the latest commit changing otterdog/&lt;org&gt;.jsonnet and stores it, shown as 'Configuration changed &lt;age&gt;' linked to that commit | webapp | free | P2 | **partial** | live | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_runtime.py::test_project_and_admin_pages` |

Details:

- **`webapp-runtime.boot`** (covered, P0, `offline`): the webapp container boots with MongoDB and Valkey/Redis (dummy App credentials suffice), GET /internal/health answers 200, the /index footer shows 'OtterDog - v&lt;version&gt;'
    - Source: `otterdog/app.py:21-68`, `otterdog/webapp/__init__.py:101-161`, `otterdog/webapp/internal/routes.py:68-76`, `otterdog/webapp/home/routes.py:91-203`
    - Operations: run, api
    - Known bugs: KB-061
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.ready`** (covered, P2, `offline`): GET /internal/ready (#949, main after v1.8.0): MongoDB, Redis and ghproxy (TCP connect) checked within 2 s each, the result reused 5 s; 200 {status: ok, checks} when all are reachable, 503 {status: error} with {status: error, error: &lt;exception type&gt;} for the others; /internal/health stays the liveness probe
    - Source: `otterdog/webapp/internal/routes.py:41-160`
    - Operations: api, error
    - Notes: O-WEB-READINESS: Redis then MongoDB stopped and started again on the runtime stack: 503 with the failed check naming only the exception type, /internal/health 200 meanwhile, ok again after the restart. ghproxy is https://api.github.com in the offline stack (not overridable): only the form of its check is asserted. SUTs without #949: 404 {}.
- **`webapp-runtime.internal-once`** (covered, P2, `offline`): /internal/init and /internal/check run once at a time across the workers (#949): a Redis lease (internal-init, internal-check; 300 s, renewed; the init keeps it until its installation tasks completed, 1 h at most) and 429 {status: '&lt;what&gt; is already running'} with Retry-After 60 while it is held
    - Source: `otterdog/webapp/internal/routes.py:162-236`, `otterdog/webapp/lease.py:1-69`, `otterdog/webapp/db/service.py:368-431`
    - Operations: api, state
    - Notes: O-WEB-INTERNAL-LEASE: the harness holds the Redis keys as another worker would (WebappStack.hold_lease, dummy stacks only): /internal/check and /internal/init answer 429 with Retry-After 60 and the lease stays the holder's; once it is dropped, a check answers 200 and releases its own lease. O-WEB-HOOK-ERROR: a check failing with 500 releases it too (the check after the outage answers 200). The harness waits out a 429 of /internal/init and /internal/check (WebappApi.get_once_at_a_time). Not covered: two real concurrent inits (the init needs GitHub).
- **`webapp-runtime.config`** (covered, P1, `webapp`): environment configuration: GITHUB_APP_ID/PRIVATE_KEY, GITHUB_WEBHOOK_SECRET/ENDPOINT, validation and sync status contexts, GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS (regex patterns), OTTERDOG_CONFIG_OWNER/REPO/PATH/TOKEN, MONGO_URI, REDIS_URI, GHPROXY_URI, BLUEPRINT_CHECK_INTERVAL, DEPENDENCY_TRACK_URL/TOKEN, CACHE_CONTROL
    - Source: `otterdog/webapp/config.py:15-150`, `otterdog/webapp/utils.py:316-424`
    - Operations: config
    - Known bugs: KB-012, KB-013
    - Notes: W-RT-CONFIG-TEAMS (P1): GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS point at a team that does not exist. The help comment names the otterdog.json org-entry teams ("approved by a member of team '&lt;approval&gt;'", `<org>/<admin>`). Once the entry drops them, it names the environment's (pattern '^x$' with the 'no team ... matches' note, `<org>/x`). Requires otterdog#715 (v1.5.0). W-RT-ADMIN-TEAMS-SPACES covers KB-013 (scoped xfail; approval patterns with spaces as the strict control). BLUEPRINT_CHECK_INTERVAL and DEPENDENCY_TRACK_URL/TOKEN are asserted by W-BP-CHECK and W-POL-SBOM. The GITHUB_WEBHOOK_ENDPOINT override is covered offline by tests/offline/test_webapp_runtime.py::test_webhook_endpoint_is_configurable.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.init`** (covered, P0, `webapp`): GET /internal/init: reload otterdog.json, global policies and blueprints from the configs repo, sync the installation list (orgs not installed are NOT_INSTALLED), refresh data of active installations
    - Source: `otterdog/webapp/internal/routes.py:167-192`, `otterdog/webapp/utils.py:137-313`, `otterdog/webapp/db/service.py:71-472`
    - Operations: api, state, config
    - Known bugs: KB-015, KB-074
    - Notes: Reloading global policies and blueprints on /internal/init is now asserted on the project page; init after a webapp restart refreshes PRs. The KB-015 push path is covered by W-BP-GLOBAL-PUSH.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.fetch-all-pull-requests`** (covered, P2, `webapp`): FetchAllPullRequestsTask (on init/installation refresh) imports the config repo's existing pull requests (only those targeting 'main')
    - Source: `otterdog/webapp/tasks/fetch_all_pull_requests.py:30-62`
    - Operations: task, state
    - Known bugs: KB-014, KB-074
    - Notes: W-RT-INIT-IMPORTS-PRS: the webapp service is stopped and the relay is shown to have failed (and dropped) the opened/closed deliveries. PRs opened or merged meanwhile are handled by the next /internal/init (FetchAllPullRequestsTask finished): the open PR is imported (open, draft false, not_applied, valid null, no bot comment; /otterdog validate then validates it), the merged PR is imported as merged and completed and never applied, and a PR against another base is not imported. KB-014: 'main' is hardcoded, which is consistent here because main is the config repo's default branch. KB-074 (W-RT-INIT-APPLY-STATUS): the re-import overwrites partially_applied with completed (non-strict xfail, scoped).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.internal-unknown`** (covered, P2, `offline`): GET /internal/&lt;anything else&gt; answers 404 {}; exceptions under /internal answer 500 {}
    - Source: `otterdog/webapp/internal/routes.py:258-268`
    - Operations: api, error
    - Notes: 404 {} for /internal/&lt;other&gt;; 500 {} for /internal/check during a MongoDB outage
- **`webapp-runtime.api-organizations`** (covered, P1, `webapp`): GET /api/organizations ([{github_id, project_name}] of every installation row) and GET /api/organizations/&lt;github_id&gt; (stored configuration JSON, 404 until fetched)
    - Source: `otterdog/webapp/api/routes.py:37-50`
    - Operations: api, state
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.api-projects`** (covered, P2, `webapp`): GET /api/projects/&lt;project_name&gt;: the stored configuration by project name (404 for unknown projects)
    - Source: `otterdog/webapp/api/routes.py:53-59`
    - Operations: api
    - Notes: W-RT-API-PROJECTS: /api/projects/&lt;project&gt; == /api/organizations/&lt;org&gt; (read after quiesce); an unknown project or org answers 404 with body {}. Also verified offline against the 9bdeb75 image.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.api-tasks`** (covered, P1, `webapp`): GET /api/tasks: paged task records (type, org_id, repo_name, pull_request, status, cache_stats, rate_limit_remaining) with regex filters, pageIndex/pageSize/sortField/sortOrder
    - Source: `otterdog/webapp/api/routes.py:62-66`, `otterdog/webapp/db/service.py:558-596`, `otterdog/webapp/tasks/__init__.py:59-90`
    - Operations: api, state, task
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.api-pullrequests`** (covered, P1, `webapp`): GET /api/pullrequests/open (open + merged-not-completed) and /api/pullrequests/merged (merged and completed), paged with id[...] filters
    - Source: `otterdog/webapp/api/routes.py:69-80`, `otterdog/webapp/db/service.py:857-979`
    - Operations: api, state
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.api-statistics`** (partial, P2, `offline`): GET /api/pullrequests/statistics/progress?interval=day|week|month&range=7d|14d|30d|90d|6m|12m|all[&org=]: polled background job; 400 {'error': "unsupported interval '&lt;x&gt;'"}
    - Source: `otterdog/webapp/api/routes.py:83-139`
    - Operations: api, error
    - Notes: 400 {'error': unsupported interval/range} covered (interval checked first).
    - Suggested: `W-API-STATISTICS` in `tests/webapp/test_api_statistics.py`
    - Steps:
        - webapp tier: GET /api/pullrequests/statistics/progress (defaults, then interval=week&range=30d&org=&lt;org&gt;) polled until status done
    - Assert:
        - the first answer is running (or done), the last one done with result.interval/range echoed, one bucket per period and the test org in result.organizations
    - Needs:
        - webapp
        - app
        - the job asks GitHub for the App identity first (get_app_bot_login): not runnable with dummy credentials
- **`webapp-runtime.api-graphql`** (covered, P2, `offline`): GraphQL API: GET /api/graphql (explorer page), POST /api/graphql (queries over the stored data; invalid queries 400); /query page with the schema
    - Source: `otterdog/webapp/api/routes.py:170-183`, `otterdog/webapp/home/routes.py:245-252`
    - Operations: api
    - Notes: Field names are snake_case (github_id), the outline's camelCase query answers 400
- **`webapp-runtime.pages-projects`** (covered, P2, `webapp`): project pages: /organizations/&lt;org&gt;[/&lt;subpath&gt;] redirect to /projects/&lt;project&gt;[/&lt;subpath&gt;], /projects/&lt;project&gt; (+ /defaults, /playground, /repos/&lt;repo&gt;) render the stored configuration
    - Source: `otterdog/webapp/home/routes.py:255-522`
    - Operations: api, state
    - Notes: W-RT-PAGES: /organizations/&lt;org&gt; -&gt; 302 /projects/&lt;project&gt;; /organizations/&lt;org&gt;/repos/&lt;repo&gt; -&gt; 302 /projects/&lt;project&gt;/repos/&lt;repo&gt;. The project page has the policies and blueprints tabs and the repo link; the repository page shows 'Repository &lt;repo&gt;'; /defaults shows the snippets orgs.newOrg('&lt;project-name&gt;', '&lt;github-id&gt;') = and orgs.newRepo('&lt;name&gt;') =; /playground shows the template (in a textarea up to v1.6.1, in the templateFiles of its playground-data JSON script since #878, v1.7.0); unknown org, project and repo get the 404 HTML page; /allprojects lists the project. The redirect and 404 shapes were checked offline.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.pages-admin`** (covered, P2, `offline`): admin pages without login: /admin/organizations (installation status), /admin/pullrequests, /admin/blueprints, /admin/policies (aggregated policy status), /admin/tasks
    - Source: `otterdog/webapp/home/routes.py:1053-1147`
    - Operations: api, security
    - Notes: offline: the five admin pages render without a session on an empty database (O-WEB-ROUTES); live: the /admin/organizations row of the test org {installation id of the App, installed, project} (W-RT-PAGES) and the /admin/policies counters (W-POL-MACOS).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`webapp-runtime.login-required`** (covered, P2, `offline`): /myprojects needs a GitHub OAuth session: unauthenticated requests get the 401 page
    - Source: `otterdog/webapp/home/routes.py:210-216`, `otterdog/webapp/home/routes.py:1160-1162`
    - Operations: permission, api
    - Known bugs: KB-059
    - Notes: without OAuth configuration (the offline stack) /myprojects answers the 500 page instead of 401 (KB-059, O-KB-WEB-LOGIN-REQUIRED asserts the 401); the 401 page itself needs a stack with OAuth variables.
- **`webapp-runtime.oauth-login`** (gap, P2, `web_ui`): GitHub OAuth login: /login -&gt; /github (authorize) -&gt; /github/authorized (user and project memberships stored in the session) -&gt; /logout
    - Source: `otterdog/webapp/auth/routes.py:34-173`
    - Operations: permission
    - Notes: Not implemented: needs an OAuth App for the webapp under test and harness-side browser automation. Related offline finding (KB-059): /myprojects answers 500 without OAuth configuration.
    - Suggested: `webui.webapp-login` in `tests/web_ui/test_webapp_login.py`
    - Steps:
        - Playwright: the bot logs in to github.com (LoginGate), opens &lt;webapp&gt;/login, authorizes the OAuth app, opens /myprojects, then /logout
    - Assert:
        - /myprojects 200 listing the projects of the bot's teams; after /logout /myprojects is 401 again
    - Needs:
        - web_ui
        - an OAuth App (GITHUB_OAUTH_CLIENT_ID/SECRET) for the webapp under test
- **`webapp-runtime.playground-validation`** (partial, P2, `webapp`): POST /playground/validate[?template=example] and /projects/&lt;project&gt;/playground/validate: the evaluated organization configuration is validated with otterdog; JSON rejections 400 (no JSON object), 413 (PLAYGROUND_VALIDATION_MAX_SIZE), 404 (unknown project), 503 (PLAYGROUND_MAX_CONCURRENT_VALIDATIONS) (#891)
    - Source: `otterdog/webapp/home/routes.py:583-785`, `otterdog/webapp/config.py:57-70`, `otterdog/webapp/config.py:141-144`
    - Operations: api, validate, security
    - Notes: verified offline against the main d9dac78 image: 400 {"error": "an evaluated configuration of an organization is expected"} (text/plain, invalid JSON, a list), 413 {"error": "the configuration must not exceed 5242880 bytes"}, 404 {"error": "unknown project"}, each logged 'rejecting a validation for ... by an anonymous user'. The test skips on images without #891.
    - Suggested: `tests/webapp/test_runtime.py::test_playground_validates_the_configuration`
    - Steps:
        - POST the evaluated configuration of the test organization (otterdog show --json-like evaluation of the config repo) to /projects/&lt;project&gt;/playground/validate
    - Assert:
        - 200 {"problems": [...]} without error problems, like otterdog validate; a nested ruleset problem names the ruleset (repo_ruleset[name=...])
    - Needs:
        - webapp
        - an otterdog release &gt;= 1.8.0
- **`webapp-runtime.playground-pages`** (gap, P2, `webapp`): GET /playground (instance or ?template=example template), /admin/template-impact and its /configurations JSON (projects using the default base template); the project playground is a CodeMirror page fed by a JSON script (#878)
    - Source: `otterdog/webapp/home/routes.py:521-582`, `otterdog/webapp/home/routes.py:1098-1144`, `otterdog/webapp/tasks/fetch_config.py:95-104`
    - Operations: api, state
    - Notes: each page reads the otterdog.json of the instance from GitHub (no offline answer without seeding Valkey). tests/webapp/test_runtime.py reads the template of the project playground from its playground-data script since #878.
    - Suggested: `tests/webapp/test_runtime.py::test_playground_and_template_impact_pages`
    - Steps:
        - GET /playground, /playground?template=example, /admin/template-impact, /admin/template-impact/configurations
    - Assert:
        - playground-data names the instance template (templateFiles), the example template under otterdog/resources/defaults, the configurations JSON lists the test project with its jsonnet
    - Needs:
        - webapp
        - an otterdog release &gt;= 1.7.0
- **`webapp-runtime.installation-refresh-bound`** (gap, P2, `webapp`): installation refresh tasks run behind MAX_CONCURRENT_INSTALLATION_TASKS per worker (default 10, checked at boot like the playground limits); /internal/init refreshes every installation once; HYPERCORN_WORKERS sets the workers (#843)
    - Source: `otterdog/webapp/config.py:57-70`, `otterdog/webapp/config.py:132`, `otterdog/webapp/db/service.py:415-442`, `otterdog/webapp/internal/routes.py:167-193`, `docker/start-webapp:1-10`
    - Operations: task, config
    - Notes: the harness passes HYPERCORN_WORKERS (E2E_HYPERCORN_WORKERS) since the image's --workers wins over hypercorn-cfg.toml; MAX_CONCURRENT_INSTALLATION_TASKS and the PLAYGROUND_\* limits are restart_webapp overrides.
    - Suggested: `tests/offline/test_webapp_runtime.py::test_positive_limits_are_checked_at_boot`
    - Steps:
        - restart_webapp with MAX_CONCURRENT_INSTALLATION_TASKS=0, then PLAYGROUND_VALIDATION_MAX_SIZE=0
    - Assert:
        - the webapp refuses to start with 'MAX_CONCURRENT_INSTALLATION_TASKS must be at least 1, got 0' (the exit status is KB-061); one FetchConfigTask per organization after /internal/init (live tier)
    - Needs:
        - available: WebappStack.restart_webapp(env)
        - an otterdog release &gt;= 1.7.0
- **`webapp-runtime.dashboard-theme`** (partial, P2, `webapp`): #912 (941d284, in v1.8.0): the dashboard takes the documentation's theme (Eclipse colors, Inter bundled with the assets instead of Google Fonts, a dark mode following the system until the header toggle picks one); the projects pages show a card per organization (facts, protections, activity, filters and orders kept in the address); FetchConfigTask reads the configuration at the latest commit changing otterdog/&lt;org&gt;.jsonnet and stores it, shown as 'Configuration changed &lt;age&gt;' linked to that commit
    - Source: `otterdog/webapp/tasks/fetch_config.py:31-50`, `otterdog/webapp/tasks/fetch_config.py:76-109`, `otterdog/webapp/home/projects.py:227-233`, `otterdog/webapp/templates/includes/project-card.html:152-185`, `otterdog/webapp/templates/includes/navigation.html:16-22`, `otterdog/webapp/templates/includes/color-scheme.html:1-14`
    - Operations: api, state
    - Notes: W-MERGE-APPLY waits for the FetchConfigTask after a squash merge and asserts /api/organizations/&lt;org&gt; holds the new repository: on webapps with #912 that fetch reads the configuration at the commit of GET /repos/{org}/{config repo}/commits?path=otterdog/&lt;org&gt;.jsonnet&per_page=1 (the merge), at the default branch before. W-RT-PAGES asserts the redesigned project page still has its policies and blueprints tabs and lists the repository, and /allprojects names the project. Neither asserts the new content: the 'Configuration changed' link (stored commit_sha, committed_at), the facts, filters and orders of the cards. v1.7.1 pages loaded fonts.googleapis.com (layouts/base.html), v1.8.0 pages do not. The dark mode (localStorage 'otterdog-color-scheme', prefers-color-scheme) is browser-only, unit-tested upstream with vitest (color-scheme.test.js, code-theme.test.js, fonts.test.js, projects.test.js).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-MERGE-APPLY` in `tests/webapp/test_merge_apply.py`
    - Steps:
        - after the squash merge and its finished FetchConfigTask: GET /allprojects and /projects/&lt;project&gt;
        - GET /index (the offline stack serves it too)
    - Assert:
        - the organization's card on /allprojects and the activity of /projects/&lt;project&gt; link 'Configuration changed ...' to https://github.com/&lt;org&gt;/&lt;config repo&gt;/commit/&lt;merge commit sha&gt; (webapps with #912)
        - the page has the color mode toggle (button[data-otterdog-color-scheme-toggle]) and no fonts.googleapis.com stylesheet (v1.7.1 has one)
    - Needs:
        - webapp
        - an otterdog release &gt;= 1.8.0
        - harness: Playwright pages of the webapp dashboard for the dark mode itself

## Blueprints

`blueprints`: 8 features, 6 covered, 2 partial, 0 gaps (weighted 88%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `blueprints.loading` | blueprint definitions: id, type, name, description, config; global ones de-duplicated by type (KB-076), a global id wins over an org definition with the same id; reloaded on push and init | webapp | free | P2 | **partial** | live | `tests/webapp/test_blueprints.py::test_blueprint_definitions_are_loaded`, `tests/webapp/test_blueprints.py::test_invalid_yaml_definition_does_not_block_the_others`, `tests/webapp/test_blueprints.py::test_global_definitions_reload_on_configs_push`, `tests/webapp/test_blueprints.py::test_changed_definition_is_stored_by_one_fetch`, `tests/webapp/test_blueprints.py::test_changed_type_keeps_the_check_working`, `tests/webapp/test_blueprints.py::test_changed_definition_is_rechecked_after_another_fetch` |
| `blueprints.required-file` | required_file: repositories matching repo_selector.name_pattern must contain files (mustache content; strict files are rewritten in an existing remediation branch) | webapp | free | P2 | covered | live | `tests/webapp/test_blueprints.py::test_required_file_remediation` |
| `blueprints.pin-workflow` | pin_workflow: workflow 'uses:' references are pinned to commit SHAs (comment keeps the tag) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_pin_workflow_remediation` |
| `blueprints.append-configuration` | append_configuration: when the JSONata condition holds on the org configuration, a PR on the config repo appends the rendered snippet (reviewers requested) | webapp | free | P2 | covered | live | `tests/webapp/test_blueprints.py::test_append_configuration_remediation` |
| `blueprints.scorecard-integration` | scorecard_integration: matching repositories need the OSSF scorecard workflow (PR with workflow_content); results are synced and served by /api/scorecard/results and /scorecard/checks | webapp | free | P2 | **partial** | live | `tests/webapp/test_blueprints.py::test_scorecard_integration_remediation` |
| `blueprints.status-and-dismissal` | remediation PR lifecycle: open -&gt; REMEDIATION_PREPARED, merged -&gt; RECHECK, closed unmerged -&gt; DISMISSED with a blueprint-dismissal comment (reopen reinstates); /api/blueprints/dismissed | webapp | free | P2 | covered | live | `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint`, `tests/webapp/test_blueprints.py::test_required_file_remediation` |
| `blueprints.remediations-api` | GET /api/blueprints/remediations: blueprint statuses with an open remediation PR (read by the CLI list-blueprints / approve-blueprints) | webapp | free | P2 | covered | live | `tests/webapp/test_blueprints.py::test_required_file_remediation`, `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint` |
| `blueprints.check-endpoint` | GET /internal/check[/&lt;limit&gt;] evaluates up to &lt;limit&gt; (default 50) blueprints whose last check is older than BLUEPRINT_CHECK_INTERVAL (forced rechecks reset) | webapp | free | P2 | covered | live | `tests/webapp/test_blueprints.py::test_check_interval_and_limit`, `tests/webapp/test_blueprints.py::test_changed_type_keeps_the_check_working` |

Details:

- **`blueprints.loading`** (partial, P2, `webapp`): blueprint definitions: id, type, name, description, config; global ones de-duplicated by type (KB-076), a global id wins over an org definition with the same id; reloaded on push and init
    - Source: `otterdog/webapp/blueprints/__init__.py:116-170`, `otterdog/webapp/tasks/fetch_blueprints.py:39-94`, `otterdog/webapp/webhook/__init__.py:322-332`
    - Operations: config, task, state
    - Known bugs: KB-015, KB-069, KB-070, KB-071, KB-072, KB-076
    - Notes: W-BP-LOAD (strict): org definitions load with a push to config repo main (push delivery -&gt; FetchBlueprintsTask -&gt; project page card: name, Reference URL .../blob/main/otterdog/blueprints/&lt;id&gt;.yml, config); a definition without 'type' is logged ('failed reading blueprint from path ...') and skipped; /internal/init loads a global definition; the global definition beats a later org definition with the same id ('duplicate blueprint with id ... skipping'); removing an org file unloads it. Known bugs: KB-015 (W-BP-GLOBAL-PUSH), KB-069 (W-BP-LOAD-YAML), KB-070 (W-BP-UPDATE), KB-071 (W-BP-RECHECK-LOST), KB-072 (W-BP-TYPE-CHANGE), KB-076 (two global definitions of one type, untested).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-BP-LOAD-GLOBAL-TYPES` in `tests/webapp/test_blueprints.py`
    - Steps:
        - two global blueprints of one type with different ids in the configs repository; /internal/init
    - Assert:
        - documented: both load (additive); today the second is skipped with 'duplicate global blueprint with type ...' (KB-076)
    - Needs:
        - webapp
        - harness: BlueprintHelper option bypassing the per-type rule for global definitions
- **`blueprints.required-file`** (covered, P2, `webapp`): required_file: repositories matching repo_selector.name_pattern must contain files (mustache content; strict files are rewritten in an existing remediation branch)
    - Source: `otterdog/webapp/blueprints/required_file.py:26-80`, `otterdog/webapp/tasks/blueprints/check_files.py:20-122`
    - Operations: task, add
    - Notes: W-BP-REQUIRED-FILE: the remediation PR (title, base main, body naming the blueprint name and definition, the dismissal note and /organizations/&lt;org&gt;#blueprint-&lt;id&gt;) adds a strict file and a non-strict file rendered with mustache (repo_name, github_id, project_name, blueprint_id, repo.description, repo_url). A list name_pattern is used and only the matching repo gets a status. A recheck (changed definition, exactly one fetch) rewrites the strict file in the existing branch, keeps the maintainer's edit of the non-strict file, and reuses the same PR. Merge -&gt; recheck/success. A push to main deleting the strict file re-evaluates at once (CheckFilesTask without /internal/check) and opens a new PR with only that file. Skips on webapps older than otterdog#766 (v1.6.0).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`blueprints.pin-workflow`** (covered, P2, `webapp`): pin_workflow: workflow 'uses:' references are pinned to commit SHAs (comment keeps the tag)
    - Source: `otterdog/webapp/blueprints/pin_workflow.py:23-60`, `otterdog/webapp/tasks/blueprints/pin_workflow.py:25-147`
    - Operations: task, modify
    - Known bugs: KB-073
    - Notes: W-BP-PIN: the PR changes exactly one line: 'actions/checkout@v4' -&gt; '@&lt;40-hex&gt; # v4.x.y'. The sha is checked against GET /repos/actions/checkout/commits/&lt;tag&gt;. '# ignore', '@main' and local actions are kept. Merge -&gt; success. The last step is KB-073 (a docker:// step makes otterdog skip the whole workflow), a non-strict xfail limited to DockerActionPinningError.
- **`blueprints.append-configuration`** (covered, P2, `webapp`): append_configuration: when the JSONata condition holds on the org configuration, a PR on the config repo appends the rendered snippet (reviewers requested)
    - Source: `otterdog/webapp/blueprints/append_configuration.py:26-80`, `otterdog/webapp/tasks/blueprints/append_configuration.py:23-145`
    - Operations: task, modify, validate
    - Notes: the Eclipse '.github' snippet blueprint appears in 199 org files as an appended '} + {' block. W-BP-APPEND: config-repo PR from otterdog/blueprint/&lt;id&gt;. Its otterdog/&lt;org&gt;.jsonnet is main.rstrip() + ' + ' + the rendered snippet ({{blueprint_id}}, {{github_id}}); the snippet was checked offline with rjsonnet. Review is requested from the approval team (requested_reviewers). The webapp validates it (status + validate comment naming the new repo). It is merged through the guarded ConfigRepoFlow and applied (repository created with the rendered description), then the stored config declares it and the blueprint reports success.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`blueprints.scorecard-integration`** (partial, P2, `webapp`): scorecard_integration: matching repositories need the OSSF scorecard workflow (PR with workflow_content); results are synced and served by /api/scorecard/results and /scorecard/checks
    - Source: `otterdog/webapp/blueprints/scorecard_integration.py:24-83`, `otterdog/webapp/tasks/blueprints/check_scorecard_integration.py:27-125`, `otterdog/webapp/tasks/blueprints/sync_scorecard_result.py:25-62`, `otterdog/webapp/api/routes.py:156-167`
    - Operations: task, add, api
    - Notes: W-BP-SCORECARD: the PR adds .github/workflows/scorecard-analysis.yml (default workflow_name) rendered from workflow_content. Merge -&gt; success (a workflow using ossf/scorecard-action is found). The next check runs SyncScorecardResultTask (finished). /api/scorecard/results stays empty and the repo page has no scorecard.dev link for a repo without published results.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-BP-SCORECARD-RESULT` in `tests/webapp/test_blueprints.py`
    - Steps:
        - a repository with published scorecard results (or a scorecard API mock); /internal/check
    - Assert:
        - a stored result: score per check in /api/scorecard/results and /scorecard/checks
    - Needs:
        - webapp
        - harness: a repository with published results or a redirect of api.securityscorecards.dev (hardcoded, sync_scorecard_result.py)
- **`blueprints.status-and-dismissal`** (covered, P2, `webapp`): remediation PR lifecycle: open -&gt; REMEDIATION_PREPARED, merged -&gt; RECHECK, closed unmerged -&gt; DISMISSED with a blueprint-dismissal comment (reopen reinstates); /api/blueprints/dismissed
    - Source: `otterdog/webapp/tasks/blueprints/update_blueprint_status.py:45-80`, `otterdog/webapp/tasks/blueprints/__init__.py:31-118`, `otterdog/webapp/api/routes.py:149-153`, `otterdog/webapp/db/service.py:1325`
    - Operations: task, state, comment, api
    - Known bugs: KB-075
    - Notes: W-BP-DISMISS: closing the PR -&gt; UpdateBlueprintStatusTask -&gt; dismissed (row keeps the PR number), bot comment with the blueprint-dismissal marker 'The blueprint `<id>` has been dismissed for this repo.', branch deleted by the webapp, listed by /api/blueprints/dismissed and no longer by remediations. A check evaluates nothing and opens no new PR. Reopen (branch recreated first) -&gt; remediation_prepared. A second close minimizes the first dismissal comment. A lost status (definition removed and re-added) is restored to dismissed from the closed PR on GitHub, with no new PR: the regression of otterdog#766 (16f7f32, v1.6.0), a strict xfail limited to DismissalLostError on older webapps. Merge -&gt; recheck/success is covered in W-BP-REQUIRED-FILE.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`blueprints.remediations-api`** (covered, P2, `webapp`): GET /api/blueprints/remediations: blueprint statuses with an open remediation PR (read by the CLI list-blueprints / approve-blueprints)
    - Source: `otterdog/webapp/api/routes.py:142-146`, `otterdog/webapp/db/service.py:1321`
    - Operations: api
    - Known bugs: KB-075
    - Notes: Rows {id.org_id, id.repo_name, id.blueprint_id, remediation_pr} with the id[blueprint_id] filter while the PR is open; gone after the merge or the dismissal (W-BP-REQUIRED-FILE, W-BP-DISMISS). The CLI consumers are cli.list-blueprints / cli.approve-blueprints (W-CLI-BLUEPRINTS). updated_at is never refreshed (KB-075).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`blueprints.check-endpoint`** (covered, P2, `webapp`): GET /internal/check[/&lt;limit&gt;] evaluates up to &lt;limit&gt; (default 50) blueprints whose last check is older than BLUEPRINT_CHECK_INTERVAL (forced rechecks reset)
    - Source: `otterdog/webapp/internal/routes.py:206-256`
    - Operations: api, task
    - Known bugs: KB-072
    - Notes: W-BP-CHECK uses append_configuration blueprints whose condition is not a boolean (status failure, no GitHub writes, one AppendConfigurationTask per evaluation of the config repo). With BLUEPRINT_CHECK_INTERVAL=3600 (webapp_env) /internal/check evaluates nothing and logs "skipping blueprint with id '&lt;id&gt;' for org '&lt;org&gt;', last checked at ..." (compose). Back at 0: /internal/check/1 evaluates only the never-checked blueprint, /internal/check all three. Requires otterdog#766. Validated offline against the 9bdeb75 image with a seeded database. W-BP-TYPE-CHANGE shows the failure mode where /internal/check answers 500.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)

## Policies

`policies`: 3 features, 3 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `policies.loading` | policy definitions (type, name, description, config) from the configs repo (policies/\*.yml) and the config repo (otterdog/policies/\*.yml, merged over the global one) | webapp | free | P2 | covered | live | `tests/webapp/test_policies.py::test_policy_definitions_are_loaded_and_merged`, `tests/webapp/test_policies.py::test_malformed_policy_does_not_block_the_others` |
| `policies.macos-large-runners` | macos_large_runners: queued jobs on 'macos\*large' runners are cancelled unless allowed; counters total_workflow_jobs, permitted/cancelled_on_restricted_runners | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_policies.py::test_macos_large_runner_jobs_are_cancelled_unless_allowed` |
| `policies.dependency-track-upload` | dependency_track_upload: a successful workflow run referencing workflow_filter uploads the SBOM artifact (bom.json + metadata.json) to DEPENDENCY_TRACK_URL /api/v1/bom | webapp | free | P2 | covered | live | `tests/webapp/test_policies.py::test_sbom_upload_to_dependency_track` |

Details:

- **`policies.loading`** (covered, P2, `webapp`): policy definitions (type, name, description, config) from the configs repo (policies/\*.yml) and the config repo (otterdog/policies/\*.yml, merged over the global one)
    - Source: `otterdog/webapp/policies/__init__.py:21-118`, `otterdog/webapp/tasks/fetch_policies.py:39-87`, `otterdog/webapp/webhook/__init__.py:310-320`
    - Operations: config, task, state
    - Known bugs: KB-069
    - Notes: W-POL-LOAD: global macos_large_runners and dependency_track_upload policies load on /internal/init (project page cards: name or 'Overview', Reference URL, config parsed from PrettyFormatter). Org policies pushed to config repo main merge over them: path and name from the org file, the global description kept when the org sets none, allowed and workflow_filter from the org, artifact_name always from the global one (Policy.merge). Removing the org macos file restores the global values. KB-069 (W-POL-LOAD-MALFORMED): a file without 'type' fails FetchPoliciesTask (non-strict xfail, scoped). #944 (open) removes the dependency_track_upload type: on a webapp built without it W-POL-LOAD asserts that its files never show up and the macos policy still loads and merges.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`policies.macos-large-runners`** (covered, P2, `webapp`): macos_large_runners: queued jobs on 'macos\*large' runners are cancelled unless allowed; counters total_workflow_jobs, permitted/cancelled_on_restricted_runners
    - Source: `otterdog/webapp/policies/macos_large_runners.py:21-79`, `otterdog/webapp/webhook/__init__.py:351-385`
    - Operations: event, task, state
    - Notes: W-POL-MACOS: allowed false -&gt; the workflow_job queued delivery is forwarded, the App cancels the run (conclusion cancelled), cancelled_on_restricted_runners +1, total_workflow_jobs +1, permitted unchanged (/admin/policies). allowed true -&gt; permitted_on_restricted_runners +1, cancelled unchanged, the run is still queued, and the harness cancels it. Skips where the org has larger runners (billing guard).
- **`policies.dependency-track-upload`** (covered, P2, `webapp`): dependency_track_upload: a successful workflow run referencing workflow_filter uploads the SBOM artifact (bom.json + metadata.json) to DEPENDENCY_TRACK_URL /api/v1/bom
    - Source: `otterdog/webapp/policies/dependency_track_upload.py:23-81`, `otterdog/webapp/tasks/policies/upload_sbom.py:1-119`, `otterdog/webapp/webhook/__init__.py:388-420`
    - Operations: event, task
    - Notes: W-POL-SBOM (dtrack_mock): a successful run of the caller of the reusable store workflow -&gt; workflow_run completed -&gt; UploadSBOMTask finished -&gt; PUT /api/v1/bom with X-Api-Key e2e-dummy\*, application/json, {projectName, projectVersion 1.0.0, parentUUID default, autoCreate true, bom == the CycloneDX document}. A non-matching workflow_filter -&gt; no UploadSBOMTask and no upload. The mock answering 500 -&gt; UploadSBOMTask failed ('failed to upload SBOM'). #944 (open) removes the policy, UploadSBOMTask and the workflow_run hook: W-POL-SBOM is skipped on a webapp built without them; offline, O-WEB-SIG then expects every workflow_run delivery logged as 'workflow_run (&lt;delivery id&gt;)'.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)

<a id="regressions"></a>

## CHANGELOG fixes (regression guards)

`regressions`: 48 features, 34 covered, 6 partial, 8 gaps (weighted 77%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `regression.790-ruleset-status-checks-strict` | #790 (9bdeb75, after v1.6.1): ruleset status checks without 'strict' are a validation error instead of an apply failure | offline | free | P1 | covered | offline, live | `O-VAL-RULESET-STRICT`, `regression.repo-ruleset-without-strict`, `O-VAL-ORG-RULESET-STRICT`, `enterprise.org-ruleset.missing-strict`, `tests/differential/test_offline_diff.py::test_change_expected_deltas_observed` |
| `regression.791-code-scanning-new-repos` | #791 (b5f7bb1): code scanning of new repositories is only disabled when it is configured (private repositories without Code Security) | cli | free | P1 | covered | live | `regression.private-repo-template-defaults` |
| `regression.779-user-bypass-actors` | #779 (f055d51): individual users ('@login') as ruleset bypass actors | cli | free | P2 | covered | live | `regression.user-bypass-actors` |
| `regression.775-unformattable-webhook-events` | #775 (5466db5): webhook events whose payload cannot be formatted for the log are still processed | offline | free | P1 | covered | offline | `tests/offline/test_webapp_contract.py::test_unformattable_events_are_still_processed`, `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong`, `tests/offline/test_webapp_contract.py::test_optional_headers` |
| `regression.773-rebase-merge-commits` | #773 (ba3d1f9): every commit of a rebase-merged pull request is applied (base = parent of the first rebased commit) | webapp | free | P1 | covered | live | `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit` |
| `regression.771-warning-wording` | #771 (476bf5e): validation comment warnings read 'some of the requested changes ...' (secrets, Web UI, costs) | webapp | free | P2 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_pr_validation.py::test_validation_warnings` |
| `regression.767-code-scanning-languages-new-repo` | #767 (8e3a359): code_scanning_default_languages on a repository that does not exist yet is a validation error | cli | free | P1 | covered | live | `regression.code-scanning-new-repo` |
| `regression.770-cost-automerge` | #770 (v1.6.1): cost-related changes (max_cache_size_gb) are excluded from auto-merge | webapp | free | P1 | covered | live | `tests/webapp/test_pr_validation.py::test_validation_warnings` |
| `regression.766-blueprint-dismissed` | #766 (v1.6.0): a dismissed blueprint stays dismissed (stored status or a closed remediation PR found on GitHub) | webapp | free | P2 | covered | live | `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint` |
| `regression.765-out-of-sync-warning` | #765 (v1.6.0): the out-of-sync comment is a '&gt; [!WARNING]' alert (was [!NOTE]) | webapp | free | P2 | covered | live | `tests/webapp/test_commands.py::test_drift_check_sync` |
| `regression.751-disabled-ruleset-conditions` | #751 (v1.6.0): disabled rulesets whose conditions are null converge | cli | free | P2 | covered | live | `regression.disabled-ruleset-without-refs` |
| `regression.731-private-repo-rulesets` | #731 (v1.5.0): rulesets of private repositories on plans without them (403/404) are tolerated | cli | free | P1 | covered | live | `regression.private-repo-template-defaults`, `cli.neg.private-ruleset` |
| `regression.718-unknown-properties` | #718 (v1.5.0): unknown properties only warn ('ignoring unknown properties found while validating organization config: ...') | offline | free | P1 | covered | offline | `O-VAL-SCHEMA` |
| `regression.713-already-deleted-branch` | #713 (v1.5.0): deleting an otterdog/\* branch GitHub already deleted (delete_branch_on_merge) is not an error | webapp | free | P2 | covered | live | `tests/webapp/test_otterdog_branches.py::test_otterdog_branches_are_deleted` |
| `regression.712-fail-fast-configuration` | #712 (v1.5.0) and v1.3.2: the webapp refuses to start when required settings are missing or empty (GITHUB_WEBHOOK_SECRET); values are stripped (#677) | offline | free | P1 | **partial** | offline | `tests/offline/test_webapp_runtime.py::test_required_setting_is_refused_at_boot`, `tests/offline/test_webapp_runtime.py::test_refused_boot_exits_non_zero` |
| `regression.699-token-only-operations` | #693 / #699 (v1.4.0): operations that do not need the web UI never read web credentials (token-only env credentials work) | cli | free | P0 | covered | live | `cli.repo.lifecycle`, `tests/cli/test_smoke.py::test_check_token_permissions` |
| `regression.695-700-491-status-check-mapping` | #491 (v1.1.1), #695, #700 (v1.4.0): ruleset status checks map app slugs and integration ids both ways (org rulesets return only integration_id) | cli | free | P1 | covered | live | `cli.ruleset.public`, `cli.ruleset.status-checks`, `cli.protection.app-checks` |
| `regression.691-open-pr-author` | #691 (v1.4.0): open-pr requires --author | cli | free | P2 | covered | offline, live | `tests/cli/test_config_repo_cli.py::test_open_pr`, `tests/offline/test_cli_basics.py::test_usage_errors_exit_2`, `tests/cli/test_commands_config_repo.py::test_open_pr_opens_nothing_when_it_must_not` |
| `regression.685-pin-invalid-workflow` | #685 (v1.4.0): PinWorkflowTask skips workflow files with invalid YAML | webapp | free | P2 | **gap** | - | - |
| `regression.675-ruleset-unset-defaults` | #675 (v1.3.4): ruleset values left UNSET by the template default are rendered and compared correctly (import round trip) | cli | free | P2 | covered | live | `tests/cli/test_import.py::test_import_plans_no_change`, `tests/cli/test_protection_import.py::test_imported_protections_plan_no_change` |
| `regression.653-string-property` | #653 (v1.3.4): no allowed_values are sent for string / true_false custom properties | cli | free | P2 | covered | live | `cli.custom-property`, `cli.custom-property.flag` |
| `regression.635-fork-pr-private` | #635 (v1.3.1): fork PR approval calls are skipped for private repositories (GitHub 422) | cli | free | P1 | covered | live | `regression.private-repo-template-defaults`, `cli.repo.visibility`, `cli.org.member-privileges` |
| `regression.603-automerge-problems-comment` | #603 (v1.3.0): a refused /otterdog merge answers with the automerge problems comment | webapp | free | P1 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |
| `regression.nested-dict-printing` | v1.3.0: changes of nested dicts (workflows, team_permissions) print as nested '\~ key = {' blocks | offline | free | P2 | covered | offline | `O-LPLAN-NESTED` |
| `regression.in-sync-not-required` | v1.2.0 / v1.1.0: an out-of-sync organization neither blocks auto-merge nor fails the sync status | webapp | free | P1 | covered | live | `tests/webapp/test_commands.py::test_drift_check_sync`, `tests/webapp/test_merge_apply.py::test_drifted_org_still_auto_merges` |
| `regression.562-empty-status-checks` | #562 (v1.2.0): rulesets with empty status_checks are created without a required_status_checks rule | cli | free | P1 | covered | live | `regression.ruleset-empty-status-checks` |
| `regression.472-rename-and-modify` | #472 (v1.1.1): renaming a repository and modifying it in one apply | cli | free | P1 | covered | live | `regression.rename-and-modify` |
| `regression.450-pages-required-fields` | #450 (v1.1.0): GitHub Pages updates send the required fields together | cli | free | P2 | covered | live | `cli.repo.pages` |
| `regression.440-rich-escaping` | #440 (v1.1.0): values containing rich markup ('[bold]', '[/]') are printed literally | offline | free | P2 | covered | offline | `O-LPLAN-ESCAPING`, `tests/offline/test_cli_markup.py::test_validation_messages_quote_values_literally` |
| `regression.458-411-435-code-scanning-live` | #411, #435, #458: 'actions' is a valid code scanning language, invalid CodeQL languages from the API are filtered, live code scanning settings compare with the expected default setup | cli | free | P2 | covered | live | `cli.repo.code-scanning` |
| `regression.import-multiple-custom-properties` | v1.0.1: importing an organization with several custom properties | cli | free | P2 | covered | live | `tests/cli/test_repo_import.py::test_imported_custom_properties_plan_no_change` |
| `regression.local-apply-teams-webhooks` | v1.0.1 / #325 / #330: local-apply (the webapp's apply) updates teams, handles wildcard webhooks and skips web-UI settings | webapp | free | P2 | covered | live | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_team_and_wildcard_webhook_are_applied` |
| `regression.842-team-permission-removal` | #842 (c1cdc54): removing an entry of a dict setting (team_permissions, repository custom_properties) is planned and applied (KB-005) | cli | free | P1 | covered | offline, live | `O-LPLAN-DICT-ONE-WAY`, `cli.kb.team-permissions-removal` |
| `regression.878-schema-enums` | #878 (a26b543): the JSON schemas enumerate the allowed values (custom property value_type, environment deployment_branch_policy, role base_role, default_repository_permission, merge commit settings, Pages, code scanning, ruleset target/enforcement/merge method, secret and variable visibility, webhook content_type/insecure_ssl, workflow settings): an invalid value is a load error | offline | free | P1 | covered | offline | `O-VAL-CUSTOM-PROPERTIES`, `O-VAL-ENVIRONMENTS`, `O-VAL-ORG-ROLES`, `O-VAL-ORG-SETTINGS`, `O-VAL-MERGE-SETTINGS`, `O-VAL-PAGES`, `O-VAL-REPO`, `O-VAL-RULESETS`, `O-VAL-ORG-SECRETS`, `O-VAL-WEBHOOKS`, `O-VAL-ORG-WORKFLOWS`, `O-VAL-REPO-WORKFLOWS` |
| `regression.854-885-cost-related` | #854 (0229baa) private repository creation and conversion are cost-related; #885 (529ca89) only a max_cache_size_gb change of the workflow settings is cost-related (the webapp's cost warning and auto-merge exclusion) | webapp | free | P2 | **gap** | - | - |
| `regression.889-packaged-defaults` | #889 (3bfd24d): the standard template moved from examples/template to otterdog/resources/defaults (base_template URL and vendor import path change for configurations on main) | offline | free | P0 | covered | offline | `tests/offline/test_scenarios.py::test_sut_template_can_be_vendored` |
| `regression.960-retry-idempotent-requests` | #960 (e35360d, after v1.8.0): the REST requester sends a request again on a 5xx or a lost response only for GET, HEAD, OPTIONS, PUT and DELETE; POST and PATCH only when no connection could be established | cli | free | P2 | **gap** | - | - |
| `regression.962-immutable-releases-rate-limit` | #962 (c853f83, after v1.8.0): a rate-limited 403 while reading the immutable release settings of an organization or a repository fails the read instead of leaving the settings unset (plan and apply skipped them silently) | cli | free | P2 | **gap** | - | - |
| `regression.964-delete-branch-refused` | #964 (6566348, after v1.8.0): the webapp's DeleteBranchTask takes only a 404 or the 422 of an already deleted reference for a missing branch; another 422 (a deletion GitHub refuses) fails the task instead of completing it | webapp | free | P2 | **gap** | - | - |
| `regression.967-playground-find` | #967 (6f3ab92, after v1.8.0): Ctrl+F (Cmd+F) in the editors of the dashboard playground opens CodeMirror's search panel, which finds text outside the rendered lines | webapp | free | P2 | **gap** | - | - |
| `regression.893-playground-custom-templates` | #893 (cb51e70, in v1.8.0): the playground gets every library of the base template's repository, subdirectories included, named by its path from the repository root (vendor/&lt;repo&gt;/&lt;path&gt;, source link &lt;repo&gt;/blob/&lt;ref&gt;/&lt;path&gt;), and the vendored copy keeps the whole subtree of the base template's directory (nested helpers) | webapp | free | P2 | **partial** | live | `tests/webapp/test_runtime.py::test_project_and_admin_pages` |
| `regression.895-merge-rechecks-approvals` | #895 (2591db4, in v1.8.0): /otterdog merge checks the reviews of the pull request again when neither its author nor the stored approvals allow the merge, and stores the result, so an approval whose review event was missed or failed no longer blocks the merge; reviews of deleted accounts and unresolved teams of a partial GraphQL answer are ignored | webapp | free | P1 | **partial** | live | `tests/webapp/test_merge_apply.py::test_dismissed_approval_blocks_the_merge` |
| `regression.904-merge-base-from-branch-activity` | #904 (e4515eb, in v1.8.0): the base of a squash- or rebase-merged pull request is the head of its base branch before the merge, read from the branch's pr_merge activity (looked up again for about 31 s), not from the commits GitHub associates with the pull request some time after the merge; a merge not recorded as a pr_merge activity (merge queue) fails the apply | webapp | free | P1 | **partial** | live | `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_merge_applies_config` |
| `regression.905-excluded-teams-local-operations` | #905 (62ac2a4, in v1.8.0): local-plan and local-apply (the webapp's validation and apply) drop from the base configuration the teams whose slug matches defaults.github.exclude_teams and that the configuration no longer declares, so removing such a team plans no deletion; a local apply finds the slug of a removed team from its name; updating or deleting a team missing on GitHub fails with 'failed to find team with name ...' | cli | free | P1 | **gap** | - | - |
| `regression.906-installation-before-config` | #906 (b79c7b9, in v1.8.0): a push to the default branch of the otterdog config repository is handled first, also when delivered through an App installation (otterdog.json, global policies and blueprints, then the installations are reloaded: KB-015); the App installed for an org not known yet reloads otterdog.json and creates, installs and fetches that org's installation when it is defined there, else logs a warning | webapp | free | P1 | **partial** | live | `tests/webapp/test_blueprints.py::test_global_definitions_reload_on_configs_push`, `tests/webapp/test_installation_events.py::test_installation_events_update_the_record` |
| `regression.907-custom-property-editable-default` | #907 (c7a5818, in v1.8.0): the standard template defaults values_editable_by of newCustomProperty to 'org_actors' (null before), the value GitHub reports when none was specified | offline | free | P2 | **gap** | - | - |
| `regression.914-codespaces-secrets-unavailable` | #914 (65175c3, in v1.8.0): a 404 of the organization or repository Codespaces secrets endpoints (Codespaces not available, e.g. Free organizations) skips these secrets with one warning per organization and scope instead of failing every operation; a configuration declaring such secrets fails with '... declares &lt;scope&gt; secrets which cannot be managed' | cli | free | P1 | **partial** | live | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset` |
| `regression.924-team-permissions-not-patched` | #924 (e6ab19e, in v1.8.0): team_permissions is no longer sent with the repository settings (PATCH /repos/{owner}/{repo}, POST /orgs/{org}/repos): a team-permission change goes through the teams API only and also applies to an archived repository, where GitHub refused the PATCH (403) before the teams API was called | cli | free | P1 | covered | live | `regression.archived-repo-team-permissions` |

Details:

- **`regression.790-ruleset-status-checks-strict`** (covered, P1, `offline`): #790 (9bdeb75, after v1.6.1): ruleset status checks without 'strict' are a validation error instead of an apply failure
    - Source: `otterdog/models/ruleset.py:156-164`, `otterdog/models/ruleset.py:1096-1103`
    - Operations: validate
    - Known bugs: KB-008
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`regression.791-code-scanning-new-repos`** (covered, P1, `cli`): #791 (b5f7bb1): code scanning of new repositories is only disabled when it is configured (private repositories without Code Security)
    - Source: `otterdog/providers/github/rest/repo_client.py:629-651`
    - Operations: add, converge
    - Notes: fixed_in 1.7.0, released in v1.7.0: regression.private-repo-template-defaults runs on release:latest (v1.7.1) and later, older SUTs skip it.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.779-user-bypass-actors`** (covered, P2, `cli`): #779 (f055d51): individual users ('@login') as ruleset bypass actors
    - Source: `otterdog/models/ruleset.py:1441-1448`, `otterdog/models/ruleset.py:1330-1341`
    - Operations: add, converge
    - Notes: fixed_in 1.7.0, released in v1.7.0: regression.user-bypass-actors runs on release:latest (v1.7.1) and later, older SUTs skip it (f055d51 = v1.6.1 + 7). The user actor in the default mode, then pull_request mode, converging.
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`regression.775-unformattable-webhook-events`** (covered, P1, `offline`): #775 (5466db5): webhook events whose payload cannot be formatted for the log are still processed
    - Source: `otterdog/webapp/webhook/github_webhook.py:123-147`
    - Operations: event
    - Notes: Decided by ancestry of 5466db5 in the webapp image revision: with the fix 204 + warning + processed; v1.6.1 500 and the event dropped (both verified)
- **`regression.773-rebase-merge-commits`** (covered, P1, `webapp`): #773 (ba3d1f9): every commit of a rebase-merged pull request is applied (base = parent of the first rebased commit)
    - Source: `otterdog/webapp/utils.py:432-471`, `otterdog/webapp/tasks/apply_changes.py:165-181`
    - Operations: task, add
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.771-warning-wording`** (covered, P2, `webapp`): #771 (476bf5e): validation comment warnings read 'some of the requested changes ...' (secrets, Web UI, costs)
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:258-267`
    - Operations: comment
    - Notes: Exact secrets and cost wordings: 'some of the requested changes ...' when the webapp includes 476bf5e, 'some of requested changes ...' when it predates it, either when unknown.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.767-code-scanning-languages-new-repo`** (covered, P1, `cli`): #767 (8e3a359): code_scanning_default_languages on a repository that does not exist yet is a validation error
    - Source: `otterdog/models/github_organization.py:590-623`, `otterdog/models/repository.py:422-427`
    - Operations: validate
    - Notes: fixed_in 1.7.0, released in v1.7.0: regression.code-scanning-new-repo runs on release:latest (v1.7.1) and later, older SUTs skip it.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.770-cost-automerge`** (covered, P1, `webapp`): #770 (v1.6.1): cost-related changes (max_cache_size_gb) are excluded from auto-merge
    - Source: `CHANGELOG.md:196`, `otterdog/webapp/tasks/validate_pull_request.py:346-350`
    - Operations: permission
    - Notes: Cost change: warning, supports_auto_merge false, no automerge comment, refusal naming 'may incur costs'; new repo with the default 10 GB stays auto-mergeable (automerge comment). Strict xfail (CostAutoMergeRegressionError) on webapps without c4f75eb.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.766-blueprint-dismissed`** (covered, P2, `webapp`): #766 (v1.6.0): a dismissed blueprint stays dismissed (stored status or a closed remediation PR found on GitHub)
    - Source: `CHANGELOG.md:226`, `otterdog/webapp/tasks/blueprints/__init__.py:31-86`
    - Operations: task, state
    - Notes: W-BP-DISMISS: a dismissed blueprint whose status is lost (definition removed and re-added) is restored to dismissed from the closed remediation PR on GitHub and no new PR is opened (strict xfail limited to DismissalLostError on webapps without 16f7f32).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.765-out-of-sync-warning`** (covered, P2, `webapp`): #765 (v1.6.0): the out-of-sync comment is a '&gt; [!WARNING]' alert (was [!NOTE])
    - Source: `CHANGELOG.md:225`, `otterdog/webapp/templates/comment/out_of_sync_comment.txt:1-3`
    - Operations: comment
    - Notes: The check-sync comment starts with its marker line followed by '&gt; [!WARNING]' when the webapp includes 975cf1b ('&gt; [!NOTE]' before, either when unknown).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.751-disabled-ruleset-conditions`** (covered, P2, `cli`): #751 (v1.6.0): disabled rulesets whose conditions are null converge
    - Source: `CHANGELOG.md:224`, `otterdog/models/ruleset.py:1277-1291`
    - Operations: converge
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`regression.731-private-repo-rulesets`** (covered, P1, `cli`): #731 (v1.5.0): rulesets of private repositories on plans without them (403/404) are tolerated
    - Source: `CHANGELOG.md:267`, `otterdog/providers/github/rest/repo_client.py:451-472`
    - Operations: plan, converge
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.718-unknown-properties`** (covered, P1, `offline`): #718 (v1.5.0): unknown properties only warn ('ignoring unknown properties found while validating organization config: ...')
    - Source: `CHANGELOG.md:264`, `otterdog/models/github_organization.py:627-666`
    - Operations: validate
    - Notes: step unknown-properties-ignored of O-VAL-SCHEMA: 'ignoring unknown properties found while validating organization config: Additional properties are not allowed (...)' and 'Validation succeeded' on v1.6.1 and 9bdeb75.
- **`regression.713-already-deleted-branch`** (covered, P2, `webapp`): #713 (v1.5.0): deleting an otterdog/\* branch GitHub already deleted (delete_branch_on_merge) is not an error
    - Source: `CHANGELOG.md:260`, `otterdog/webapp/tasks/delete_branch.py:29-42`
    - Operations: task
    - Notes: Second open-pr PR: the harness deletes otterdog/e2e-&lt;run&gt;-\* first (GitHub closes the PR, flow.close is a no-op then), the closed delivery arrives with the branch gone, the DeleteBranchTask must finish (strict xfail DeletedBranchRegressionError before 2bbd1a4). No delete_branch_on_merge drift needed.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.712-fail-fast-configuration`** (partial, P1, `offline`): #712 (v1.5.0) and v1.3.2: the webapp refuses to start when required settings are missing or empty (GITHUB_WEBHOOK_SECRET); values are stripped (#677)
    - Source: `CHANGELOG.md:258`, `CHANGELOG.md:320`, `CHANGELOG.md:304`, `otterdog/webapp/config.py:15-24`, `otterdog/webapp/webhook/github_webhook.py:35-37`
    - Operations: config, security
    - Known bugs: KB-061
    - Notes: empty GITHUB_WEBHOOK_VALIDATION_CONTEXT / GITHUB_WEBHOOK_SYNC_CONTEXT and a blank-after-strip GITHUB_ADMIN_TEAMS refuse to boot ('&lt;NAME&gt; must not be empty', the container exits); the refused container exits with status 0 (KB-061, O-KB-WEB-BOOT-EXIT-STATUS). Not covered: the empty webhook secret and the stripped config token (secrets are not overridable).
    - Suggested: `O-WEB-BOOT-CONFIG` in `tests/offline/test_webapp_runtime.py`
    - Steps:
        - offline stack with an empty GITHUB_WEBHOOK_SECRET; another with OTTERDOG_CONFIG_TOKEN padded with spaces
    - Assert:
        - the first refuses to start with 'GITHUB_WEBHOOK_SECRET is not configured.' (and should exit non-zero, KB-061); the second boots with the stripped token (#677)
    - Needs:
        - offline
        - docker
        - harness: dummy WebappSettings variants for the webhook secret and the config token (secrets are never overridable by restart_webapp)
        - available: WebappStack.service_states() (state and exit code of every compose service)
- **`regression.699-token-only-operations`** (covered, P0, `cli`): #693 / #699 (v1.4.0): operations that do not need the web UI never read web credentials (token-only env credentials work)
    - Source: `CHANGELOG.md:290`, `CHANGELOG.md:293`, `otterdog/operations/diff_operation.py:156-157`
    - Operations: config, security
    - Known bugs: KB-002
    - Notes: every live CLI run provides only api_token (no username, password or TOTP)
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.695-700-491-status-check-mapping`** (covered, P1, `cli`): #491 (v1.1.1), #695, #700 (v1.4.0): ruleset status checks map app slugs and integration ids both ways (org rulesets return only integration_id)
    - Source: `CHANGELOG.md:376`, `CHANGELOG.md:291`, `CHANGELOG.md:294`, `otterdog/models/ruleset.py:169-255`
    - Operations: add, converge
    - Known bugs: KB-051, KB-054
    - Notes: #700 (integration id of an app that is not installed: 15368) and #491/#695 (installed App slug sent as integration_id and read back as the slug) are strict. The outline's expectation that '&lt;installed app id&gt;:&lt;ctx&gt;' converges is wrong: it never converges (KB-054 known-bug step).
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`regression.691-open-pr-author`** (covered, P2, `cli`): #691 (v1.4.0): open-pr requires --author
    - Source: `CHANGELOG.md:279`, `otterdog/cli.py:424-435`
    - Operations: run, exit-code
    - Notes: offline: open-pr without -a is a click usage error (exit 2, "Missing option '-a'") before any configuration is loaded; live: an author that is no GitHub user exits 2 ('author ... is not a valid GitHub user') and opens nothing.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`regression.685-pin-invalid-workflow`** (gap, P2, `webapp`): #685 (v1.4.0): PinWorkflowTask skips workflow files with invalid YAML
    - Source: `CHANGELOG.md:288`, `otterdog/webapp/tasks/blueprints/pin_workflow.py:31-66`
    - Operations: task, error
    - Suggested: `W-BLUEPRINT-PIN` in `tests/webapp/test_blueprints.py`
    - Steps:
        - add .github/workflows/broken.yml with invalid YAML next to a valid workflow
    - Assert:
        - the pin PR only touches the valid workflow; the task finishes
    - Needs:
        - target
        - webapp
- **`regression.675-ruleset-unset-defaults`** (covered, P2, `cli`): #675 (v1.3.4): ruleset values left UNSET by the template default are rendered and compared correctly (import round trip)
    - Source: `CHANGELOG.md:302`, `otterdog/models/ruleset.py:1248-1275`
    - Operations: import, converge
    - Notes: Imports a repository with a BPR, a branch ruleset (partial pull_request, status checks, merge queue, bypass actors) and a tag ruleset (pull_request/status checks null). Checks the imported spelling, then plans the cut-out repository block with the baseline: noop (round trip checked offline with otterdog's writer).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.653-string-property`** (covered, P2, `cli`): #653 (v1.3.4): no allowed_values are sent for string / true_false custom properties
    - Source: `CHANGELOG.md:303`, `otterdog/models/custom_property.py:178-180`
    - Operations: add
    - Notes: string properties (cli.custom-property) and true_false properties (cli.custom-property.flag) are created without allowed_values and converge.
    - Verified on `automation` with `main-fa01483`: run `tp2fgp07` (2026-11-25)
    - Verified on `automation` with `v1.8.0`: run `tp24ye15` (2026-11-25)
- **`regression.635-fork-pr-private`** (covered, P1, `cli`): #635 (v1.3.1): fork PR approval calls are skipped for private repositories (GitHub 422)
    - Source: `CHANGELOG.md:332`, `otterdog/providers/github/rest/repo_client.py:1442-1466`
    - Operations: add, converge
    - Notes: Released in v1.3.1: cli.repo.visibility and cli.org.member-privileges plan, apply and converge private repositories (created public, then made private: #791) on release:latest, so the fork PR approval reads and patches of private repositories run there; regression.private-repo-template-defaults (fixed_in 1.7.0) also creates one directly.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.603-automerge-problems-comment`** (covered, P1, `webapp`): #603 (v1.3.0): a refused /otterdog merge answers with the automerge problems comment
    - Source: `CHANGELOG.md:339`, `otterdog/webapp/tasks/merge_pull_request.py:110-124`
    - Operations: comment, permission
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.nested-dict-printing`** (covered, P2, `offline`): v1.3.0: changes of nested dicts (workflows, team_permissions) print as nested '\~ key = {' blocks
    - Source: `CHANGELOG.md:350`, `otterdog/operations/plan.py:90-101`
    - Operations: plan
    - Notes: verified offline: repository workflows+ {allowed_actions: 'local_only'} prints '\~ workflows = {', '\~ allowed_actions = "all" -&gt; "local_only"', '\~ }'. scenarios/offline/plan/lplan-nested.yaml: repo workflows, org workflows, team_permissions value change and added entry
- **`regression.in-sync-not-required`** (covered, P1, `webapp`): v1.2.0 / v1.1.0: an out-of-sync organization neither blocks auto-merge nor fails the sync status
    - Source: `CHANGELOG.md:360`, `CHANGELOG.md:392`, `otterdog/webapp/db/models.py:129-228`
    - Operations: permission, status
    - Known bugs: KB-019
    - Notes: W-AUTOMERGE-DRIFT (P1): drifted run repo: check-sync comment, 'sync check failed' with state success, /api in_sync false, automerge comment, /otterdog merge merges, the apply names only the added repo and the drifted description stays on GitHub.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.562-empty-status-checks`** (covered, P1, `cli`): #562 (v1.2.0): rulesets with empty status_checks are created without a required_status_checks rule
    - Source: `CHANGELOG.md:364`, `otterdog/models/ruleset.py:199-201`
    - Operations: add
    - Known bugs: KB-021
    - Verified on `enterprise` with `main-fa01483`: run `tp28q9d7` (2026-11-25)
    - Verified on `enterprise` with `v1.8.0`: run `tp20305a` (2026-11-25)
- **`regression.472-rename-and-modify`** (covered, P1, `cli`): #472 (v1.1.1): renaming a repository and modifying it in one apply
    - Source: `CHANGELOG.md:377`, `otterdog/providers/github/rest/repo_client.py:169-172`
    - Operations: rename, modify
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.450-pages-required-fields`** (covered, P2, `cli`): #450 (v1.1.0): GitHub Pages updates send the required fields together
    - Source: `CHANGELOG.md:397`, `otterdog/providers/github/rest/repo_client.py:666-735`
    - Operations: modify
    - Notes: source-path step: only gh_pages_source_path changes (1 change); apply ok and oracle source {branch main, path /docs}.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.440-rich-escaping`** (covered, P2, `offline`): #440 (v1.1.0): values containing rich markup ('[bold]', '[/]') are printed literally
    - Source: `CHANGELOG.md:398`, `otterdog/models/__init__.py:754-776`
    - Operations: plan
    - Known bugs: KB-050
    - Notes: scenarios/offline/cli/lplan-escaping.yaml: additions, changes and show print markup literally; validation messages do not
- **`regression.458-411-435-code-scanning-live`** (covered, P2, `cli`): #411, #435, #458: 'actions' is a valid code scanning language, invalid CodeQL languages from the API are filtered, live code scanning settings compare with the expected default setup
    - Source: `CHANGELOG.md:424`, `CHANGELOG.md:403`, `CHANGELOG.md:399`, `otterdog/providers/github/rest/repo_client.py:771-793`
    - Operations: converge, validate
    - Notes: languages ['actions','python'] validate (no 'not detected' message), apply, and converge.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.import-multiple-custom-properties`** (covered, P2, `cli`): v1.0.1: importing an organization with several custom properties
    - Source: `CHANGELOG.md:426`, `otterdog/models/organization_settings.py:261-278`
    - Operations: import
    - Notes: Three definitions (single_select, string, true_false) plus repository values; checks the imported spelling, then the blocks plan noop with the baseline (requires custom_properties).
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.local-apply-teams-webhooks`** (covered, P2, `webapp`): v1.0.1 / #325 / #330: local-apply (the webapp's apply) updates teams, handles wildcard webhooks and skips web-UI settings
    - Source: `CHANGELOG.md:427`, `CHANGELOG.md:509`, `CHANGELOG.md:508`, `otterdog/operations/local_apply.py:27-104`
    - Operations: modify, task
    - Known bugs: KB-068
    - Notes: W-MERGE-TEAM-HOOK (P2): run team + run repo whose hook url carries a token, declared on main with '&lt;prefix&gt;\*' (trusted CLI then reset_main): the merged PR's team description is applied (strict); the wildcard webhook update loses the live url (scoped xfail WildcardWebhookUpdateError: KB-068, otterdog PATCHes config.url = the pattern).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`regression.842-team-permission-removal`** (covered, P1, `cli`): #842 (c1cdc54): removing an entry of a dict setting (team_permissions, repository custom_properties) is planned and applied (KB-005)
    - Source: `otterdog/utils.py:133-135`, `otterdog/models/repository.py:1887-1977`
    - Operations: remove, modify, plan
    - Known bugs: KB-005
    - Notes: KB-005 fixed in 1.7.0: the steps that declared it are strict from that version on (release:latest included) and expected failures before.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)
- **`regression.878-schema-enums`** (covered, P1, `offline`): #878 (a26b543): the JSON schemas enumerate the allowed values (custom property value_type, environment deployment_branch_policy, role base_role, default_repository_permission, merge commit settings, Pages, code scanning, ruleset target/enforcement/merge method, secret and variable visibility, webhook content_type/insecure_ssl, workflow settings): an invalid value is a load error
    - Source: `otterdog/resources/schemas/repository.json:38-41`, `otterdog/resources/schemas/ruleset.json:4-8`, `otterdog/resources/schemas/settings.json:45-50`
    - Operations: validate, error
    - Known bugs: KB-028, KB-029, KB-033, KB-038
    - Notes: ENUM_SCHEMA_STEPS of tests/offline/test_scenarios.py: model errors before #878, "failed to load configuration: invalid value at '&lt;path&gt;': '&lt;value&gt;' is not one of [...]" (exit 1) since; the KB-029 crash and the KB-038 set ordering are unreachable since (fixed in 1.7.0), the KB-028 and KB-033 parts on enum values too.
- **`regression.854-885-cost-related`** (gap, P2, `webapp`): #854 (0229baa) private repository creation and conversion are cost-related; #885 (529ca89) only a max_cache_size_gb change of the workflow settings is cost-related (the webapp's cost warning and auto-merge exclusion)
    - Source: `otterdog/models/repository.py:249-270`, `otterdog/models/__init__.py:838-853`, `otterdog/webapp/tasks/validate_pull_request.py:227-268`
    - Operations: comment, permission
    - Notes: only the webapp consumes the flag ('some of the requested changes may incur costs, need review by the designated team', supports_auto_merge false); the CLI never prints it. W-PR-WARNINGS covers the cache-size case.
    - Suggested: `tests/webapp/test_pr_validation.py::test_cost_related_changes`
    - Steps:
        - a PR creating a private run repository (team plan), a PR changing the run repository's allowed_actions only
    - Assert:
        - the first validation comment has the cost warning and /otterdog merge refuses ('may incur costs'); the second has no cost warning and is auto-mergeable
    - Needs:
        - webapp
        - team plan (private repositories)
        - an otterdog release &gt;= 1.8.0
- **`regression.889-packaged-defaults`** (covered, P0, `offline`): #889 (3bfd24d): the standard template moved from examples/template to otterdog/resources/defaults (base_template URL and vendor import path change for configurations on main)
    - Source: `otterdog/resources/defaults/otterdog-defaults.libsonnet:1-666`, `examples/otterdog.json:1-32`
    - Operations: config
    - Notes: the harness takes the template of a SUT from otterdog/resources/defaults when it exists, else examples/template (sut.template.template_source_dir), and points the upstream base template URL there; every offline item of branch:main depends on it.
- **`regression.960-retry-idempotent-requests`** (gap, P2, `cli`): #960 (e35360d, after v1.8.0): the REST requester sends a request again on a 5xx or a lost response only for GET, HEAD, OPTIONS, PUT and DELETE; POST and PATCH only when no connection could be established
    - Source: `otterdog/providers/github/rest/requester.py:60-75`, `otterdog/providers/github/rest/requester.py:331-360`
    - Operations: error, api
    - Notes: unit-tested upstream (tests/providers/github/rest/test_requester.py). The e2e battery cannot make GitHub answer 5xx or drop a response: the apply.api of the live scenarios (OTTERDOG_STATS_FILE) counts the requests sent, so a POST repeated after a 502 would show as two requests, but no run can provoke the 502.
    - Suggested: `cli.apply.retries`
    - Steps:
        - apply a repository webhook (POST) and a description change (PATCH) through a proxy that answers the first attempt of each with 502 after forwarding it, and a PUT of the topics the same way
    - Assert:
        - apply.api: one POST and one PATCH sent (no retry, the apply reports the failure), two PUT (retried); the next plan converges
    - Needs:
        - target
        - harness: a fault-injecting proxy between the CLI and api.github.com (otterdog's base URL is fixed: it needs an HTTPS interception the CLI trusts)
- **`regression.962-immutable-releases-rate-limit`** (gap, P2, `cli`): #962 (c853f83, after v1.8.0): a rate-limited 403 while reading the immutable release settings of an organization or a repository fails the read instead of leaving the settings unset (plan and apply skipped them silently)
    - Source: `otterdog/providers/github/rest/org_client.py:139-160`, `otterdog/providers/github/rest/repo_client.py:875-895`, `otterdog/providers/github/rest/requester.py:78-83`
    - Operations: error, plan
    - Notes: unit-tested upstream. A real rate limit cannot be provoked on purpose without exhausting the token's quota for the other sessions of the instance; the 403 without a rate limit (feature unavailable) is unchanged and stays the warning 'immutable release settings ... not available' covered by cli.org.immutable-releases and cli.repo.immutable-releases.
    - Suggested: `cli.org.immutable-releases-rate-limited`
    - Steps:
        - plan with GET /orgs/{org}/settings/immutable-releases answered 403 'API rate limit exceeded' by a proxy
    - Assert:
        - the plan fails ('failed retrieving immutable release settings for org ... 403: ...') instead of planning without the settings
    - Needs:
        - target
        - harness: a fault-injecting proxy (see regression.960-retry-idempotent-requests)
- **`regression.964-delete-branch-refused`** (gap, P2, `webapp`): #964 (6566348, after v1.8.0): the webapp's DeleteBranchTask takes only a 404 or the 422 of an already deleted reference for a missing branch; another 422 (a deletion GitHub refuses) fails the task instead of completing it
    - Source: `otterdog/providers/github/rest/reference_client.py:57-79`, `otterdog/webapp/tasks/delete_branch.py:29-39`
    - Operations: task, error
    - Notes: the branch stays on GitHub before and after #964: only the outcome of the task changes (failed instead of completed, the error logged), and the battery reads neither the task records nor the webapp logs. The already deleted case (branch removed on merge) is unchanged and runs in every merged W-AUTOMERGE scenario.
    - Suggested: `W-DELETE-BRANCH-REFUSED` in `tests/webapp/test_otterdog_branches.py`
    - Steps:
        - a repository ruleset of the config repository forbidding the deletion of refs/heads/otterdog/\*\* (rule deletion), then an otterdog/\* pull request closed without merge
    - Assert:
        - the branch stays; the DeleteBranchTask record is failed with the 422 of GitHub (webapps with #964), completed before
    - Needs:
        - target
        - webapp
        - harness: a read of the webapp's task records (MongoDB of the compose stack or a dashboard page listing tasks)
- **`regression.967-playground-find`** (gap, P2, `webapp`): #967 (6f3ab92, after v1.8.0): Ctrl+F (Cmd+F) in the editors of the dashboard playground opens CodeMirror's search panel, which finds text outside the rendered lines
    - Source: `otterdog/webapp/static/src/js/playground/editors.js:160-175`
    - Operations: state
    - Notes: browser-only behaviour of the webapp's JavaScript; upstream tests it with Playwright (tests/webapp/playground/test_documents.py) and a vitest unit test. The battery reads the webapp pages over HTTP only (W-RT-PAGES, O-WEB-PLAYGROUND-VALIDATE): no browser drives the dashboard.
    - Suggested: `O-WEB-PLAYGROUND-FIND` in `tests/offline/test_webapp_contract.py`
    - Steps:
        - open /projects/&lt;project&gt;/playground of the offline stack in Firefox, focus the organization editor, press Ctrl+F and search a line far below the visible ones
    - Assert:
        - the search panel shows at the top of the editor and the match is selected (webapps with #967); before, the browser's find misses it
    - Needs:
        - harness: Playwright pages of the offline webapp stack (only otterdog's web-UI login drives a browser today)
- **`regression.893-playground-custom-templates`** (partial, P2, `webapp`): #893 (cb51e70, in v1.8.0): the playground gets every library of the base template's repository, subdirectories included, named by its path from the repository root (vendor/&lt;repo&gt;/&lt;path&gt;, source link &lt;repo&gt;/blob/&lt;ref&gt;/&lt;path&gt;), and the vendored copy keeps the whole subtree of the base template's directory (nested helpers)
    - Source: `otterdog/jsonnet.py:547-554`, `otterdog/jsonnet.py:624-643`, `otterdog/webapp/home/routes.py:913-945`, `otterdog/webapp/static/src/js/playground/snippets.js:74-104`, `otterdog/webapp/static/src/js/playground/completion.js:112-150`
    - Operations: api, config
    - Notes: W-RT-PAGES asserts that the templateFiles of the project playground hold the standard template (a source with newRepo). With the default template mode (auto: the upstream template of a release SUT, otterdog/resources/defaults/otterdog-defaults.libsonnet) only #893's recursive listing provides it: before, jsonnet_template_files listed the top level of vendor/&lt;repo&gt; only, empty for a template in a subdirectory, and the copy kept one level below the template's directory ('&lt;dir&gt;/\*\*' with PurePath.match), dropping &lt;dir&gt;/nested/\*.libsonnet (both read in the code at cb51e70^ and simulated with Python 3.12 and 3.13, not observed in a run). With a published template (repository root) the assertion held before #893 too. Not asserted: the filenames and source links by path from the repository root, a nested library vendored for the CLI, and the browser side (completion from the evaluated functions with std.length, shared snippets keeping their available imports, error locations linked only when unambiguous), tested upstream with vitest and Playwright (tests/webapp/playground).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `O-TEMPLATE-NESTED-LIBRARY` in `tests/offline/test_config_template_cache.py`
    - Steps:
        - seed the cached clone with a template tree whose base template is sub/otterdog-defaults.libsonnet and that holds sub/nested/helper.libsonnet, imported by the organization configuration (or the template); validate without --local
        - webapp tier (W-RT-PAGES): read each templateFiles entry {filename, url} and defaultConfig of the project playground's playground-data
    - Assert:
        - offline: vendor/&lt;repo&gt;/sub/nested/helper.libsonnet exists and validate passes (otterdog &gt;= 1.8.0); before #893 the helper is not vendored and the import fails
        - webapp: defaultConfig vendor/otterdog/otterdog/resources/defaults/otterdog-defaults.libsonnet is one of the filenames, with url &lt;upstream repo&gt;/blob/&lt;sut sha&gt;/otterdog/resources/defaults/otterdog-defaults.libsonnet, otterdog-functions.libsonnet beside it
    - Needs:
        - offline
        - webapp
        - available: publish_origin and seed_clone of tests/offline/test_config_template_cache.py (O-TEMPLATE-CACHE)
        - an otterdog release &gt;= 1.8.0
        - harness: Playwright pages of the webapp dashboard for the completion and snippet behaviour
- **`regression.895-merge-rechecks-approvals`** (partial, P1, `webapp`): #895 (2591db4, in v1.8.0): /otterdog merge checks the reviews of the pull request again when neither its author nor the stored approvals allow the merge, and stores the result, so an approval whose review event was missed or failed no longer blocks the merge; reviews of deleted accounts and unresolved teams of a partial GraphQL answer are ignored
    - Source: `otterdog/webapp/tasks/merge_pull_request.py:44-77`, `otterdog/webapp/tasks/__init__.py:246-267`, `otterdog/providers/github/graphql.py:326-336`
    - Operations: permission, state, comment
    - Notes: W-AUTOMERGE-DISMISS goes through the recheck on webapps with #895 (contributor author, has_required_approvals false after the dismissal) and asserts its negative outcome: the reviews hold no current approval, /otterdog merge is refused naming the approval ('No approval from a member of') and the PR stays open, as before #895. The fix itself, a stored false while GitHub holds an approval by an approval team, is not exercised: no test drops a pull_request_review delivery or changes the approval teams after an approval (only UpdatePullRequestTask on a review and MergePullRequestTask set has_required_approvals; /internal/init and FetchAllPullRequestsTask keep the stored value). The null review author and the null team node are unit-tested upstream (tests/webapp/tasks/test_pull_request_approvals.py, tests/providers/github/test_graphql.py).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-AUTOMERGE-RECHECK` in `tests/webapp/test_merge_apply.py`
    - Steps:
        - webapp_otterdog_json({'approval_teams': ['^&lt;run name of no team&gt;$']}), then a contributor PR (identity author) approved by the approver: /api has_required_approvals false, no auto-merge offer
        - webapp_otterdog_json({}) (the run's approval teams again; the reload recomputes no approval, the stored false stays), then '/otterdog merge' by the author
    - Assert:
        - webapps with #895: the PR is merged and applied and /api has_required_approvals is true; before #895 (v1.7.1) the refusal names the missing approval ('No approval from a member of') and the PR stays open
    - Needs:
        - webapp
        - identity author
        - identity approver
        - available: webapp_otterdog_json fixture (otterdog.json organization overrides, then /internal/init)
        - an otterdog release &gt;= 1.8.0
- **`regression.904-merge-base-from-branch-activity`** (partial, P1, `webapp`): #904 (e4515eb, in v1.8.0): the base of a squash- or rebase-merged pull request is the head of its base branch before the merge, read from the branch's pr_merge activity (looked up again for about 31 s), not from the commits GitHub associates with the pull request some time after the merge; a merge not recorded as a pr_merge activity (merge queue) fails the apply
    - Source: `otterdog/webapp/utils.py:427-470`, `otterdog/webapp/tasks/apply_changes.py:165-171`, `otterdog/providers/github/rest/repo_client.py:72-93`
    - Operations: task, add, error
    - Notes: W-REBASE-MULTI rebase-merges a two-commit PR right after its validation and asserts that both run repositories exist and are named by the apply comment (strict on release:latest, which includes #773); with #904 the base comes from GET /repos/{org}/{repo}/activity?ref=refs/heads/main&activity_type=pr_merge (Contents: read of the App). Upstream: before #904 the walk stopped at the parent of the merge commit while GitHub had not associated the rebased commits yet, and only the last commit was applied. W-MERGE-APPLY squash-merges through the same activity read (same outcome as before); the merge-commit case (first parent, unchanged) is W-MERGE-COMMIT-APPLY. Not exercised: the lookups again while GitHub has not recorded the merge, and the failure of a merge that is no pr_merge activity. Unit-tested upstream (tests/webapp/test_find_base_commit_sha.py).
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-MERGE-QUEUE-APPLY` in `tests/webapp/test_merge_apply.py`
    - Steps:
        - a merge_queue rule on main of the config repository, a validated PR adding a run repository enqueued by the admin and merged by the queue
    - Assert:
        - webapps with #904: the ApplyChangesTask of the PR fails, its log naming 'unable to determine base of merged pull request, no merge of a pull request into branch 'main' up to commit '&lt;merge sha&gt;' found in the activity of repo '&lt;org&gt;/&lt;config repo&gt;'', no apply comment, the run repository is not created
    - Needs:
        - target
        - webapp
        - target: merge queues on the config repository (a public repository, or the enterprise plan for a private one)
        - harness: enqueue a pull request (GraphQL enqueuePullRequest) and wait for the merge of the queue
        - an otterdog release &gt;= 1.8.0
- **`regression.905-excluded-teams-local-operations`** (gap, P1, `cli`): #905 (62ac2a4, in v1.8.0): local-plan and local-apply (the webapp's validation and apply) drop from the base configuration the teams whose slug matches defaults.github.exclude_teams and that the configuration no longer declares, so removing such a team plans no deletion; a local apply finds the slug of a removed team from its name; updating or deleting a team missing on GitHub fails with 'failed to find team with name ...'
    - Source: `otterdog/models/github_organization.py:176-218`, `otterdog/operations/local_plan.py:86-91`, `otterdog/operations/local_apply.py:91-95`, `otterdog/providers/github/__init__.py:326-343`, `otterdog/models/team.py:367-369`
    - Operations: plan, remove, error
    - Notes: cli.team.exclude-pattern (tests/cli/test_org_config.py::test_excluded_teams_are_neither_loaded_nor_configurable) covers the live plan, import and validation, which #905 does not change (an excluded team is never loaded from GitHub; declaring one is the error "... which is not allowed due to exclusion pattern '&lt;pattern&gt;'."). No item runs local-plan or local-apply with exclude_teams, nor removes a team with local-apply (cli.local-apply removes a repository only). Upstream: before #905 the base configuration kept an excluded team, so a configuration dropping it (as its validation requires) planned '- remove team[...]', and every team removal of a local apply failed, a team of a configuration having no slug. Unit-tested upstream (tests/models/test_team.py, tests/operations/test_diff_operations.py).
    - Suggested: `cli.team.exclude-pattern-local` in `tests/cli/test_org_config.py`
    - Steps:
        - a workspace with defaults.github.exclude_teams ['^&lt;prefix&gt;-excluded-.\*']; the Mutator creates a team whose slug matches the pattern and whose name does not (e.g. '&lt;prefix&gt;-excluded Leads'), and a plain run team
        - -BASE = baseline + both teams, configuration = baseline: local-plan -s -BASE, then (after BaselineManager.guard_config_change) local-apply -f -d -n -s -BASE
        - -BASE declares a run team that does not exist on GitHub, the configuration changes its description: local-apply -f -n -s -BASE
    - Assert:
        - the plan has '- remove team[name="&lt;plain team&gt;"]' and no removal of the excluded team; the apply reports 'Executed plan: 0 added, 0 changed, 1 deleted.', the plain team is gone and the excluded team still exists (oracle.team)
        - the last apply fails naming "failed to find team with name '&lt;name&gt;' in org '&lt;org&gt;'" and sends no request for a team 'None'
    - Needs:
        - target
        - available: WorkspaceLayout(defaults_override={'github': {'exclude_teams': [...]}}), Mutator.create_team and oracle.team (cli.team.exclude-pattern)
        - available: LiveConfig.write(suffix='-BASE') and the local-apply calls of tests/cli/test_commands_local_apply.py
        - an otterdog release &gt;= 1.8.0
- **`regression.906-installation-before-config`** (partial, P1, `webapp`): #906 (b79c7b9, in v1.8.0): a push to the default branch of the otterdog config repository is handled first, also when delivered through an App installation (otterdog.json, global policies and blueprints, then the installations are reloaded: KB-015); the App installed for an org not known yet reloads otterdog.json and creates, installs and fetches that org's installation when it is defined there, else logs a warning
    - Source: `otterdog/webapp/webhook/__init__.py:260-275`, `otterdog/webapp/db/service.py:199-218`, `otterdog/webapp/db/service.py:318-365`
    - Operations: event, task, state
    - Known bugs: KB-015
    - Notes: W-BP-GLOBAL-PUSH (KB-015, fixed_in 1.8.0: strict on release:latest) commits a global blueprint definition to the configs repository, waits for the relayed App push and asserts the card of the definition on the project page within 180 s, without /internal/init; before #906 that push returned in the installation branch and reloaded nothing. The otterdog.json side of the same reload is not asserted: the harness calls /internal/init after every otterdog.json write. W-INSTALLATION-EVENTS sends 'created' for the org whose record exists (installed with the real id, FetchConfigTask and FetchAllPullRequestsTask finished): add_app_installation as restructured by #906, outcome unchanged. The fix for an org without a record is not exercised. docs/known-issues.md (KB-015) says W-BP-GLOBAL-PUSH has not run live against the fix yet.
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
    - Suggested: `W-INSTALLATION-UNKNOWN-ORG` in `tests/webapp/test_installation_events.py`
    - Steps:
        - publish otterdog.json without the test organization's entry and reload the webapp: its /admin/organizations row is removed
        - publish otterdog.json with the entry again while the relay holds back the push of the configs repository, then inject a signed installation 'created' delivery with the real installation id
    - Assert:
        - webapps with #906: the row is back {installation_id: the real id, status installed, project_name} and a FetchConfigTask of the config repository finishes, without /internal/init; before #906 (v1.7.1) there is no row until the next reload
    - Needs:
        - webapp
        - app
        - available: WebhookInjector and installation_payload (W-INSTALLATION-EVENTS), E2EContext.publish_otterdog_json and reload_webapp
        - harness: hold back the relayed push of the configs repository for one test (DeliveryRelay.accept is only set when the relay is built)
        - an otterdog release &gt;= 1.8.0
- **`regression.907-custom-property-editable-default`** (gap, P2, `offline`): #907 (c7a5818, in v1.8.0): the standard template defaults values_editable_by of newCustomProperty to 'org_actors' (null before), the value GitHub reports when none was specified
    - Source: `otterdog/resources/defaults/otterdog-defaults.libsonnet:464-472`, `otterdog/models/custom_property.py:38-47`, `otterdog/models/__init__.py:610-646`
    - Operations: add, plan
    - Notes: Every live custom property definition of the battery (cli.custom-property, cli.custom-property.flag, cli.custom-property.required, cli.kb.custom-property-definition-with-value, tests/cli/test_repo_import.py) sets values_editable_by 'org_actors' explicitly; the only one relying on the template default, in cli.kb.custom-property-underscore, is a KB-016 xfail that fails at validation before any request. No offline step asserts the default. Upstream states GitHub refuses values_editable_by null on a create or update ('Values editable by can't be blank') and reports org_actors when it was not specified; cli.custom-property's description, written before #907, calls the field nullable: unverified by the battery. Per the diff code a null default against the org_actors GitHub reports plans a change of every definition.
    - Suggested: `O-LPLAN-CUSTOM-PROPERTY-DEFAULTS` in `scenarios/offline/custom-properties/lplan-custom-property-defaults.yaml`
    - Steps:
        - step editable-by-default: BASE orgs.newCustomProperty('{{ p }}-edit') { values_editable_by: 'org_actors' }, configuration orgs.newCustomProperty('{{ p }}-edit') without the key
        - step editable-by-added: no BASE definition, configuration orgs.newCustomProperty('{{ p }}-edit')
        - live (cli.custom-property): one more definition without values_editable_by
    - Assert:
        - local-plan noop on SUTs &gt;= 1.8.0; before #907 a change of values_editable_by from "org_actors" to null
        - '+ add custom_property[name="{{ p }}-edit"]' shows values_editable_by "org_actors"
        - live: apply.api sends PUT /orgs/{org}/properties/schema/{name}, the oracle reports values_editable_by org_actors, the plan converges
    - Needs:
        - offline
        - target
        - an otterdog release &gt;= 1.8.0 (the SUT's own template, otterdog/resources/defaults)
        - a per-SUT expectation for SUTs before #907 (fixed_in, or a reference with expected_deltas)
- **`regression.914-codespaces-secrets-unavailable`** (partial, P1, `cli`): #914 (65175c3, in v1.8.0): a 404 of the organization or repository Codespaces secrets endpoints (Codespaces not available, e.g. Free organizations) skips these secrets with one warning per organization and scope instead of failing every operation; a configuration declaring such secrets fails with '... declares &lt;scope&gt; secrets which cannot be managed'
    - Source: `otterdog/providers/github/rest/secret_client.py:36-50`, `otterdog/providers/github/rest/secret_client.py:130-135`, `otterdog/models/github_organization.py:1365-1377`, `otterdog/models/github_organization.py:1736-1762`, `otterdog/models/github_organization.py:1994-2006`
    - Operations: plan, error
    - Notes: Since #890 (v1.8.0) the standard template makes every live read list the Codespaces secrets, and GitHub answers 404 for GET /orgs/{org}/codespaces/secrets on the three Free test organizations (cli.secrets.dependabot-codespaces): on those targets every live plan or check-status of a v1.8.0 SUT goes through the skip, and cli.baseline (check-status of the baseline: valid, in sync) would fail without it. On the enterprise shard the endpoint answers and nothing is skipped. Nothing asserts the warning, nor the error of a configuration declaring such secrets ('declares organization_codespaces secrets which cannot be managed', seen in the nightly of 2026-11-18 on the Free org-level organization, which made cli.secrets.dependabot-codespaces min_plan team). Other scopes and statuses still fail the read (#890). Whether the repository endpoint answers 404 on the Free organizations has not been checked.
    - Verified on `org-level` with `v1.8.0`: run `tp23ue25` (2026-11-25)
    - Suggested: `cli.secrets.codespaces-unavailable` in `scenarios/cli/secrets/codespaces-unavailable.yaml`
    - Steps:
        - on a target whose GET /orgs/{org}/codespaces/secrets answers 404: plan the baseline
        - a step adding orgs.newOrgCodespacesSecret('{{ P }}_CS') { value: 'e2e-dummy-{{ run }}' } to codespaces_secrets
    - Assert:
        - the baseline plan is a no-op and prints "organization_codespaces secrets of '&lt;org&gt;' are not available (GitHub answers 404 for '/orgs/&lt;org&gt;/codespaces/secrets'), they are skipped" once
        - the declaring plan fails with "The configuration of '&lt;org&gt;' declares organization_codespaces secrets which cannot be managed, remove them or make the secrets available." and no Plan line
    - Needs:
        - target
        - harness: a capability for unavailable organization Codespaces secrets (GET /orgs/{org}/codespaces/secrets answers 404), to skip on the enterprise shard (min_plan cannot say Free only)
        - an otterdog release &gt;= 1.8.0
- **`regression.924-team-permissions-not-patched`** (covered, P1, `cli`): #924 (e6ab19e, in v1.8.0): team_permissions is no longer sent with the repository settings (PATCH /repos/{owner}/{repo}, POST /orgs/{org}/repos): a team-permission change goes through the teams API only and also applies to an archived repository, where GitHub refused the PATCH (403) before the teams API was called
    - Source: `otterdog/models/repository.py:1305-1313`, `otterdog/models/repository.py:1958-1980`
    - Operations: add, modify, remove, archive, converge
    - Notes: fixed_in 1.8.0, released in v1.8.0: regression.archived-repo-team-permissions runs on release:latest (v1.8.0) and later, older SUTs skip it. apply.api of each step: a permission-only change of a regular repository sends PUT /orgs/{org}/teams/{name}/repos/{owner}/{repo} and no PATCH /repos/{owner}/{repo}; archiving sends the PATCH and no teams request; on the archived repository a changed and an added team send PUT, a removed team DELETE, never the PATCH, the output has no 'Repository was archived so is read-only' and the oracle shows the new permissions; every step converges. The body of POST /orgs/{org}/repos (without team_permissions since #924) is not asserted: GitHub ignores the field there.
    - Verified on `free` with `main-fa01483`: run `tp28qbd9` (2026-11-25)
    - Verified on `free` with `v1.8.0`: run `tp202z74` (2026-11-25)

<a id="pending"></a>

## Unmerged otterdog changes (pull requests and local branches)

`pending`: 5 features, 4 covered, 1 partial, 0 gaps (weighted 90%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `pending.792-stale-status` | #792 (open): a stale webhook snapshot must not revert a merged pull request to open | webapp | free | P1 | covered | live | `tests/webapp/test_stale_status.py::test_stale_snapshot_keeps_merged_status` |
| `pending.check-merge-command` | local feature: /otterdog check-merge reports auto-merge eligibility (check-merge comment, previous minimized) and never merges | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_check_merge.py::test_check_merge_command` |
| `pending.update-branch-command` | local feature: /otterdog update-branch [rebase\|merge] updates the PR branch with its base (a rebase only by the author or an admin) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_update_branch.py::test_update_branch_command` |
| `pending.outdated-branch-note` | local feature: validation and check-merge comments note when the PR branch is behind its base ('... is &lt;n&gt; commit(s) behind ...') | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_update_branch.py::test_update_branch_command` |
| `pending.automerge-state-refresh` | local feature: auto-merge state recomputed from live teams and approvals (automerge_state.py) for merge, help and update-pull-request | webapp | free | P2 | **partial** | **unverified** | `tests/webapp/test_check_merge.py::test_check_merge_refreshes_the_team_membership` |

Details:

- **`pending.792-stale-status`** (covered, P1, `webapp`): #792 (open): a stale webhook snapshot must not revert a merged pull request to open
    - Source: `ws:otterdog-pr/otterdog/webapp/db/service.py:506-579`, `otterdog/webapp/db/service.py:670-751`
    - Operations: state, event
    - Known bugs: KB-018
    - Notes: W-PR-STALE-SNAPSHOT references #792 with its expected delta (--change 792)
    - Verified on `webapp` with `main-fa01483`: run `tp2fya79` (2026-11-25)
- **`pending.check-merge-command`** (covered, P2, `webapp`): local feature: /otterdog check-merge reports auto-merge eligibility (check-merge comment, previous minimized) and never merges
    - Source: `ws:otterdog/otterdog/webapp/tasks/check_merge.py:1-87`, `ws:otterdog/otterdog/webapp/webhook/comment_handlers.py:101-116`
    - Operations: comment, permission
    - Notes: W-CMD-CHECK-MERGE references the named change check-merge (base v1.6.0, --change check-merge)
- **`pending.update-branch-command`** (covered, P2, `webapp`): local feature: /otterdog update-branch [rebase|merge] updates the PR branch with its base (a rebase only by the author or an admin)
    - Source: `ws:otterdog/otterdog/webapp/tasks/update_branch.py:1-123`, `ws:otterdog/otterdog/webapp/webhook/comment_handlers.py:118-137`
    - Operations: comment, permission
    - Notes: W-CMD-UPDATE-BRANCH (P2, dirty SUT of feat/check-merge-command only, skips elsewhere like W-CMD-CHECK-MERGE): approver refused ('Only the author of the pull request (@&lt;author&gt;) ... is allowed to update its branch'), author 'update-branch merge' -&gt; 2-parent head + updated comment, admin default rebase -&gt; single-parent head, 'history ... rewritten' note, re-validations.
- **`pending.outdated-branch-note`** (covered, P2, `webapp`): local feature: validation and check-merge comments note when the PR branch is behind its base ('... is &lt;n&gt; commit(s) behind ...')
    - Source: `ws:otterdog/otterdog/webapp/templates/comment/outdated_branch_note.txt:1-7`, `ws:otterdog/otterdog/webapp/tasks/automerge_state.py:70-88`
    - Operations: comment
    - Notes: Validate comment after main advanced by one commit contains 'is 1 commit(s) behind `main`'; the re-validations after the merge update and after the rebase have no '&gt; [!IMPORTANT]' note.
- **`pending.automerge-state-refresh`** (partial, P2, `webapp`): local feature: auto-merge state recomputed from live teams and approvals (automerge_state.py) for merge, help and update-pull-request
    - Source: `ws:otterdog/otterdog/webapp/tasks/automerge_state.py:40-156`
    - Operations: permission, state
    - Known bugs: KB-027
    - Notes: W-CMD-CHECK-MERGE-REFRESH (P2, dirty SUT): approval_teams overridden to a run team (webapp_otterdog_json); contributor PR not eligible; after the contributor joins the team /otterdog check-merge says eligible and /api author_can_auto_merge true. Per automerge_state.py the refresh only upgrades (a known-sufficient state is never re-read), so a removal from the team is not refreshed by design; approvals refresh not tested.
    - Suggested: `W-CMD-CHECK-MERGE-REFRESH` in `tests/webapp/test_check_merge.py`
    - Steps:
        - contributor PR without approval; the approver approves it; /otterdog check-merge
    - Assert:
        - the refreshed state reports has_required_approvals true (approvals refresh); a removal from the approval team is not re-read by design
    - Needs:
        - webapp
        - dirty SUT of feat/check-merge-command
        - identities author, approver
