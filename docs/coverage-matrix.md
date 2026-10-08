# Coverage matrix

<!-- Generated from scenarios/coverage.yaml by tests/unit/test_coverage_matrix.py: do not edit by hand. -->

> Generated from [`scenarios/coverage.yaml`](../scenarios/coverage.yaml) (`.venv/bin/python tests/unit/test_coverage_matrix.py --write`).
> Edit the YAML, then regenerate: `tests/unit/test_coverage_matrix.py` fails when this file is stale.

otterdog feature coverage of the e2e battery

Inventory of otterdog main @9bdeb75 (after v1.6.1; release:latest is v1.6.1): every CLI command and its flags, every property of the configuration model grouped by feature, validation rules, diff semantics, the webapp (webhook events, comment commands, tasks, auto-merge, apply, blueprints, policies, /api and /internal), the webhook receiver contract and notable CHANGELOG fixes, mapped to the existing scenarios and tests of this repository. Gaps and partial coverage carry the outline of the missing test.

**337 features** in 26 areas: 300 covered, 32 partial, 5 gaps; covered 89%, weighted 94% (a partial feature counts half). *Offline-verified* counts the covered or partial features with at least one covering item in the offline tier; *live-verified* those with a recorded green live run of their covering items (`verified_on`: target, SUT, run id, date); *unverified* the others: their coverage is implemented but has never run, so it is a claim, not evidence. A covered feature needs at least one covering item that runs strictly on the default SUT (not only known-bug xfails or scenarios skipped by `fixed_in`).

## Summary by area

| Area | Features | Covered | Partial | Gap | Covered % | Weighted % | Offline-verified | Live-verified | Unverified |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| [CLI commands and global options](#cli) | 57 | 53 | 4 | 0 | 93% | 96% | 27 | 0 | 30 |
| [otterdog.json, base template and credentials](#config) | 22 | 14 | 5 | 3 | 64% | 75% | 14 | 0 | 5 |
| [Validation rules](#validation) | 36 | 36 | 0 | 0 | 100% | 100% | 35 | 0 | 1 |
| [Diff engine and plan semantics](#plan-semantics) | 18 | 16 | 2 | 0 | 89% | 94% | 16 | 0 | 2 |
| [Organization settings](#org-settings) | 13 | 10 | 3 | 0 | 77% | 88% | 2 | 0 | 11 |
| [Organization Actions settings](#org-workflows) | 5 | 4 | 1 | 0 | 80% | 90% | 0 | 0 | 5 |
| [Organization custom properties](#custom-properties) | 6 | 6 | 0 | 0 | 100% | 100% | 2 | 0 | 4 |
| [Custom organization roles](#org-roles) | 2 | 2 | 0 | 0 | 100% | 100% | 1 | 0 | 1 |
| [Teams](#teams) | 5 | 5 | 0 | 0 | 100% | 100% | 0 | 0 | 5 |
| [Managed organization and repository webhooks](#webhooks) | 8 | 6 | 2 | 0 | 75% | 88% | 4 | 0 | 4 |
| [Secrets and variables (organization, repository, environment)](#secrets-variables) | 10 | 10 | 0 | 0 | 100% | 100% | 4 | 0 | 6 |
| [Repositories](#repositories) | 16 | 15 | 1 | 0 | 94% | 97% | 3 | 0 | 13 |
| [Repository Actions settings](#repo-workflows) | 5 | 4 | 1 | 0 | 80% | 90% | 0 | 0 | 5 |
| [Branch protection rules](#branch-protection) | 10 | 10 | 0 | 0 | 100% | 100% | 2 | 0 | 8 |
| [Repository and organization rulesets](#rulesets) | 10 | 9 | 1 | 0 | 90% | 95% | 2 | 0 | 8 |
| [Deployment environments](#environments) | 4 | 4 | 0 | 0 | 100% | 100% | 3 | 0 | 1 |
| [Webhook receiver contract](#receiver) | 8 | 8 | 0 | 0 | 100% | 100% | 8 | 0 | 0 |
| [Webapp webhook event routing](#webapp-events) | 10 | 9 | 1 | 0 | 90% | 95% | 1 | 0 | 9 |
| [Pull request comment commands](#webapp-commands) | 9 | 8 | 1 | 0 | 89% | 94% | 0 | 0 | 9 |
| [Pull request validation, sync check and apply](#webapp-pr) | 15 | 13 | 2 | 0 | 87% | 93% | 0 | 0 | 15 |
| [Auto-merge eligibility and merge](#webapp-automerge) | 4 | 4 | 0 | 0 | 100% | 100% | 0 | 0 | 4 |
| [Webapp boot, init, API and pages](#webapp-runtime) | 16 | 14 | 1 | 1 | 88% | 91% | 8 | 0 | 7 |
| [Blueprints](#blueprints) | 8 | 6 | 2 | 0 | 75% | 88% | 0 | 0 | 8 |
| [Policies](#policies) | 3 | 3 | 0 | 0 | 100% | 100% | 0 | 0 | 3 |
| [CHANGELOG fixes (regression guards)](#regressions) | 32 | 27 | 4 | 1 | 84% | 91% | 7 | 0 | 24 |
| [Unmerged otterdog changes (pull requests and local branches)](#pending) | 5 | 4 | 1 | 0 | 80% | 90% | 0 | 0 | 5 |
| **Total** | 337 | 300 | 32 | 5 | 89% | 94% | 139 | 0 | 193 |

## Summary by tier

| Tier | Features | Covered | Partial | Gap | Covered % | Weighted % | Offline-verified | Live-verified | Unverified |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| `offline` | 110 | 104 | 6 | 0 | 95% | 97% | 110 | 0 | 0 |
| `cli` | 132 | 116 | 13 | 3 | 88% | 93% | 24 | 0 | 105 |
| `webhooks` | 4 | 3 | 1 | 0 | 75% | 88% | 2 | 0 | 2 |
| `webapp` | 76 | 68 | 7 | 1 | 89% | 94% | 2 | 0 | 73 |
| `web_ui` | 13 | 7 | 5 | 1 | 54% | 73% | 1 | 0 | 11 |
| `enterprise` | 2 | 2 | 0 | 0 | 100% | 100% | 0 | 0 | 2 |

## Summary by priority

| Priority | Features | Covered | Partial | Gap | Covered % | Weighted % | Offline-verified | Live-verified | Unverified |
|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|
| P0 | 61 | 61 | 0 | 0 | 100% | 100% | 30 | 0 | 31 |
| P1 | 134 | 116 | 16 | 2 | 87% | 93% | 56 | 0 | 76 |
| P2 | 142 | 123 | 16 | 3 | 87% | 92% | 53 | 0 | 86 |

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

## New findings

Defects found while building the inventory (not yet in `scenarios/known_bugs.yaml`):

| Id | Finding | Source | Verified | Suggestion |
|---|---|---|---|---|
| `F-01` | Organization variables are never validated: lowercase or GITHUB_ names, invalid visibility and 'private' on a free plan all pass | `otterdog/models/github_organization.py:196-264`, `otterdog/models/organization_variable.py:40-63`, `otterdog/models/variable.py:29-42` | offline: validate --local of newOrgVariable('lower_case') {visibility: 'private'} and newOrgVariable('GITHUB_X') {visibility: 'nonsense', selected_repositories: ['a']} with plan free prints 'Validation succeeded' (exit 0); the same org secret errors | registered as KB-028 (confirmed); offline scenario expecting the 4 errors (non-strict xfail of KB-028 until fixed); docs/capability-matrix.md now states that the variable check is never called |
| `F-02` | An invalid workflows.allowed_actions crashes validation with a KeyError as soon as a repository exists (org 'some' -&gt; "Error: 'some'", repo 'x' -&gt; "Error: 'x'", exit 2) | `otterdog/models/workflow_settings.py:94-113`, `otterdog/models/repo_workflow_settings.py:56-57`, `otterdog/models/repo_workflow_settings.py:99-105` | offline: settings workflows+ {allowed_actions: 'some'} with orgs.newRepo('r1') exits 2 printing "Error: 'some'"; without repositories the documented ERROR "settings has 'workflows.allowed_actions' of value 'some', ..." is printed (exit 1) | registered as KB-029 (confirmed); offline scenario expecting the documented error with a repository present (xfail KB-029) |
| `F-03` | A required custom property without default_value crashes loading ('unexpected None value', exit 2) when any repository exists, before the validation error can be reported | `otterdog/models/repository.py:296-303`, `otterdog/models/github_organization.py:349-351`, `otterdog/models/custom_property.py:83-90` | offline: newCustomProperty('p') {required: true, default_value: null} plus orgs.newRepo('r1') -&gt; 'Error: unexpected None value' exit 2; without a repository: custom_property[name="p"] has 'required' set to 'true', but no property 'default_value' is specified. | registered as KB-030 (confirmed); offline scenario with a repository expecting the validation error (xfail KB-030) |
| `F-04` | Missing required keys of required_pull_request and required_merge_queue are never reported (keys() skips UNSET), unlike required_status_checks since #790 | `otterdog/models/ruleset.py:57-65`, `otterdog/models/ruleset.py:240-248`, `otterdog/models/__init__.py:677-684`, `otterdog/models/ruleset.py:128-136` | offline: a repo ruleset with required_pull_request: {requires_code_owner_review: true} (no required_approving_review_count) and one with required_merge_queue: {merge_method: 'MERGE'} validate ('Validation succeeded'); the apply payload built by RepositoryRuleset.to_provider_data carries UNSET in the pull request rule (json.dumps: TypeError) and raises BendingException for the merge queue, and the apply loop only catches RuntimeError | registered as KB-031 (confirmed); offline scenario expecting "has not set required parameter 'required_pull_request.required_approving_review_count'" (xfail KB-031); a live apply crashes before its request |
| `F-05` | The team_permissions validation error is unreachable: the schema rejects other values first (uncaught jsonschema error, exit 2), including the uppercase READ/WRITE the model accepts | `otterdog/models/repository.py:491-499`, `otterdog/models/repository.py:194-205`, `otterdog/resources/schemas/team-permission.json:1-11` | offline: team_permissions {t: 'super'} -&gt; "Error: 'super' is not one of ['pull', 'triage', 'push', 'maintain', 'admin']" with the schema dump, exit 2; the model message "invalid permission ... allowed values are ('read/pull' \| ...)" never prints | registered as KB-032 (confirmed, low): report the schema error as a validation error or drop the dead check |
| `F-06` | Documented repository warnings and errors never fire because repositories are coerced at load (has_projects, web_commit_signoff_required, has_discussions source, gh_pages_visibility below enterprise) | `otterdog/models/github_organization.py:349-351`, `otterdog/models/repository.py:284-316`, `otterdog/models/repository.py:436-465`, `otterdog/models/repository.py:583-600` | offline: has_projects true with org has_organization_projects false, web_commit_signoff_required false with the template's org default true, has_discussions false on the org discussion source repo and gh_pages_visibility 'private' on free all print 'Validation succeeded' | registered as KB-033 (confirmed, low, docs): validate before coercion or remove the messages; regression scenario documenting the current behaviour |
| `F-07` | validate/plan exit with the number of validation errors, so two errors exit 2 like an uncaught exception | `otterdog/operations/validate.py:59-102`, `otterdog/operations/plan.py:121-139`, `otterdog/cli.py:999-1001` | offline: a repository with an invalid squash_merge_commit_title gets 2 errors and validate exits 2; 256 repositories with an invalid topic exit 0 (validate and local-plan: the exit status is the error count modulo 256) | registered as KB-034 (confirmed, design): exit 1 on validation errors, keep 2 for crashes; harness checks must never read exit 2 as a crash without the output |
| `F-08` | Docs show orgs.newEnvironmentSecret/newEnvironmentVariable, the template functions are newEnvSecret/newEnvVariable | `docs/reference/organization/repository/environment/index.md:45-52`, `examples/template/otterdog-defaults.libsonnet:288-292` | offline: orgs.newEnvironmentSecret('X') -&gt; 'failed to load configuration: failed to evaluate jsonnet file: no such field: newEnvironmentSecret' (exit 1) | registered as KB-035 (confirmed): docs fix upstream; nothing to test beyond the load error |
| `F-09` | The template comment of deployment_branch_policy lists 'all, protected_branches, branch_policies' while validation accepts 'all' \| 'protected' \| 'selected' | `examples/template/otterdog-defaults.libsonnet:281-282`, `otterdog/models/environment.py:128-135` | offline: deployment_branch_policy 'protected_branches' -&gt; "... has 'deployment_branch_policy' of value 'protected_branches', while only values ('all' \| 'protected' \| 'selected') are allowed." | registered as KB-036 (confirmed): template comment fix upstream |
| `F-10` | The team privacy error says ('secret' \| 'closed') although the accepted values are 'secret' \| 'visible' | `otterdog/models/team.py:77-83` | offline, with the member listing of the team validation (its only GitHub read) replaced by a constant: privacy 'closed' -&gt; "... has 'privacy' of value 'closed', while only values ('secret' \| 'closed') are allowed." | registered as KB-037 (confirmed): message fix upstream; the live validation scenario must match the current wording |
| `F-11` | Two validation messages print Python sets, their value order changes from run to run (fork_pr_approval_policy values, code scanning languages) | `otterdog/models/workflow_settings.py:143-150`, `otterdog/models/repository.py:611-618`, `otterdog/models/repository.py:731-732` | offline: "... while only values {'first_time_contributors', 'first_time_contributors_new_to_github', 'all_external_contributors'} are allowed." and the language list in arbitrary order | registered as KB-038 (confirmed, reproduced with PYTHONHASHSEED=1 and 2): scenarios assert only the stable prefix of these messages; upstream could sort the values |
| `F-12` | An unknown role in ruleset bypass_actors ('#Admin') passes validation; the apply then crashes with an uncaught KeyError | `otterdog/models/ruleset.py:648-654`, `otterdog/models/ruleset.py:360-361` | offline: validate of a repo ruleset with bypass_actors ['#Admin'] succeeds; the apply payload (RepositoryRuleset.to_provider_data) raises KeyError 'Admin', which the apply loop does not catch (RuntimeError only) | registered as KB-039 (confirmed): validate bypass actors; offline validate scenario plus a live apply check (xfail KB-039) |
| `F-13` | A crashing sync check sets the sync status to 'failure' with the description 'otterdog detected out of sync changes, but they will not prevent a successful merge': misleading for an error, and a required sync context then blocks the merge | `otterdog/webapp/tasks/check_sync.py:135-139`, `otterdog/webapp/tasks/check_sync.py:225-234` | offline, in the webapp image of 9bdeb75 (network none, GitHub REST and MongoDB replaced by recorders): an exception of the sync plan posts 'failure' with that description; the out-of-sync result posts 'success' | registered as KB-040 (confirmed): describe the error ('sync check failed, contact an admin') or keep the state success like the out-of-sync case; webapp-pr.sync-failure records the current behaviour |

<a id="cli"></a>

## CLI commands and global options

`cli`: 57 features, 53 covered, 4 partial, 0 gaps (weighted 96%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `cli.version` | --version prints 'otterdog.sh, version &lt;version&gt;' (dynamic version of the build) | offline | free | P0 | covered | offline | `tests/offline/test_cli_basics.py::test_version_is_the_resolved_sut_version`, `tests/cli/test_smoke.py::test_version` |
| `cli.help` | --help lists the 29 subcommands; no subcommand or an unknown option is a click usage error (exit 2) | offline | free | P2 | covered | offline | `tests/offline/test_cli_basics.py::test_help_lists_every_command`, `tests/offline/test_cli_basics.py::test_command_help_lists_the_shared_options`, `tests/offline/test_cli_basics.py::test_usage_errors_exit_2` |
| `cli.global.organizations` | ORGANIZATIONS positional: project name or github_id (case-insensitive), none = every non-archived org, exit code = max over orgs | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_organizations_positional` |
| `cli.global.local-mode` | --local uses the vendored template without cloning; a missing vendor file fails with "template file '&lt;f&gt;' does not exist" (exit 2) | offline | free | P1 | covered | offline | `O-VAL-OK`, `O-LPLAN-ADD`, `tests/offline/test_config_loading.py::test_local_mode_needs_the_vendored_template` |
| `cli.global.verbosity` | -v shows Info messages (otherwise 'in order to print validation infos, enable printing info messages by adding '-v' flag.'); -vv adds tracebacks | offline | free | P2 | covered | offline | `O-VAL-INFOS`, `tests/offline/test_cli_exit_codes.py::test_verbosity_levels`, `tests/offline/test_cli_exit_codes.py::test_debug_verbosity_prints_the_traceback` |
| `cli.global.exit-codes` | Uncaught exceptions and config load errors exit 2 ('Error: &lt;message&gt;', traceback on stderr only with -vv) | offline | free | P1 | covered | offline | `O-VAL-SYNTAX`, `tests/offline/test_cli_exit_codes.py::test_validation_outcomes_set_the_exit_status`, `tests/offline/test_cli_exit_codes.py::test_load_errors_and_crashes`, `tests/offline/test_cli_exit_codes.py::test_debug_verbosity_prints_the_traceback`, `tests/offline/test_cli_exit_codes.py::test_local_plan_exit_status`, `tests/offline/test_cli_exit_codes.py::test_validation_errors_never_exit_like_a_crash`, `tests/offline/test_cli_exit_codes.py::test_secret_reference_with_colons_validates` |
| `cli.validate` | validate: 'Validating organization configurations:', per-org header, 'Validation succeeded' / "Validation succeeded': i info(s), w warning(s), 0 error(s)" / 'Validation failed: ...' | offline | free | P0 | covered | offline | `O-VAL-OK`, `O-VAL-SYNTAX`, `O-VAL-PLAN-GATE`, `O-VAL-ORGSECRET-PRIVATE-FREE`, `O-VAL-RULESET-STRICT`, `cli.secrets` |
| `cli.validate.missing-config` | validate/plan of a missing org file: "configuration file '&lt;f&gt;' does not exist, run 'fetch-config' or 'import' first." (exit 1) | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_missing_organization_configuration`, `tests/cli/test_commands_errors.py::test_commands_need_the_org_config` |
| `cli.show` | show: prints every model object as key = value blocks (no credentials) | offline | free | P2 | covered | offline | `O-VAL-OK`, `O-LPLAN-ADD`, `O-SHOW`, `tests/offline/test_cli_basics.py::test_show_needs_no_credentials` |
| `cli.show.markdown` | show --markdown [--output-dir DIR]: writes configuration.md and repo-&lt;name&gt;.md (mkdocs tabs) instead of printing | offline | free | P2 | covered | offline | `tests/offline/test_cli_basics.py::test_show_markdown_writes_the_pages`, `tests/offline/test_cli_basics.py::test_show_markdown_keeps_the_repository_links` |
| `cli.show-live` | show-live [-n]: prints the live configuration read from GitHub (web UI unless -n) | cli | free | P2 | covered | **unverified** | `tests/cli/test_commands_read.py::test_show_live_prints_the_live_org` |
| `cli.show-default` | show-default: prints the template default of every object type (orgs.newOrg(...) = {, newRepo, newBranchProtectionRule, ...) | offline | free | P1 | covered | offline | `O-SHOW-DEFAULT`, `tests/offline/test_cli_basics.py::test_show_default_prints_every_object_type` |
| `cli.show-default.markdown` | show-default --markdown: mkdocs tab blocks with jsonnet code fences | offline | free | P2 | covered | offline | `tests/offline/test_cli_basics.py::test_show_default_markdown_prints_one_tab_per_object` |
| `cli.canonical-diff` | canonical-diff: unified diff of the file versus its canonical re-serialization (labels inverted, always exit 0) | offline | free | P2 | covered | offline | `O-CANON` |
| `cli.list-projects` | list-projects: rich table 'Projects' (Project name, GitHub ID, Index), no organization positional | offline | free | P2 | covered | offline | `tests/offline/test_cli_basics.py::test_list_projects_lists_the_offline_organization`, `tests/cli/test_smoke.py::test_list_projects` |
| `cli.check-token-permissions` | check-token-permissions [-l]: X-OAuth-Scopes must include admin:org, admin:org_hook, delete_repo, repo, workflow ('Missing scopes: ...', exit 1) | cli | free | P1 | covered | **unverified** | `tests/cli/test_smoke.py::test_check_token_permissions`, `tests/cli/test_commands_read.py::test_check_token_permissions_lists_the_granted_scopes`, `tests/cli/test_commands_read.py::test_check_token_permissions_reports_missing_scopes`, `tests/cli/test_commands_read.py::test_check_token_permissions_accepts_a_fine_grained_admin` |
| `cli.list-members` | list-members [--two-factor-disabled]: 'Found &lt;n&gt; members.' / 'Found &lt;x&gt; / &lt;total&gt; members with 2FA disabled. Organization has 2FA ...' | cli | free | P2 | covered | **unverified** | `tests/cli/test_commands_read.py::test_list_members_counts_the_members` |
| `cli.list-apps` | list-apps [--json]: installations of the org with app_id, slug and permissions (JSON array sorted by slug) | cli | free | P2 | covered | **unverified** | `tests/cli/test_commands_read.py::test_list_apps_matches_the_installations` |
| `cli.list-advisories` | list-advisories [-s state ...] [-d] [-w]: CSV of repository security advisories (header line first; -w scrapes the web UI) | cli | free | P2 | covered | **unverified** | `tests/web_ui/test_web_commands.py::test_list_advisories_with_web`, `tests/cli/test_commands_read.py::test_list_advisories_prints_the_csv`, `tests/cli/test_commands_read.py::test_list_advisories_keeps_brackets_of_summaries` |
| `cli.dispatch-workflow` | dispatch-workflow [-r repo] --workflow WF: POST workflow dispatch on the default branch ("workflow '&lt;wf&gt;' dispatched for repo '&lt;repo&gt;'") | cli | free | P2 | covered | **unverified** | `tests/cli/test_commands_content.py::test_dispatch_workflow_starts_a_run`, `tests/cli/test_commands_content.py::test_failed_dispatch_exits_non_zero` |
| `cli.delete-file` | delete-file -r REPO --path P [-m MSG]: deletes a file of a configured repository ("Deleting file '&lt;p&gt;' in repository '&lt;org&gt;/&lt;repo&gt;': succeeded") | cli | free | P2 | covered | **unverified** | `tests/cli/test_commands_content.py::test_delete_file_removes_a_configured_file`, `tests/cli/test_commands_content.py::test_delete_file_reports_a_missing_file`, `tests/cli/test_commands_content.py::test_delete_file_reports_a_refused_deletion` |
| `cli.sync-template` | sync-template -r REPO: re-copies the template repository's files into a repo created from it (post_process_template_content rendered) | cli | free | P2 | covered | **unverified** | `tests/cli/test_commands_content.py::test_sync_template_recopies_the_template` |
| `cli.list-blueprints` | list-blueprints [-b ID]: table of remediation PRs read anonymously from &lt;defaults.base_url&gt;/api/blueprints/remediations | webapp | free | P1 | covered | **unverified** | `tests/cli/test_commands_blueprints.py::test_blueprint_commands_need_a_base_url`, `tests/webapp/test_cli_blueprints.py::test_list_and_approve_blueprints` |
| `cli.approve-blueprints` | approve-blueprints [-b ID]: merges every remediation PR (rebase, else squash, else merge) ('Merging PR #&lt;n&gt;: merged.') | webapp | free | P1 | covered | **unverified** | `tests/cli/test_commands_blueprints.py::test_blueprint_commands_need_a_base_url`, `tests/webapp/test_cli_blueprints.py::test_list_and_approve_blueprints` |
| `cli.import` | import -f -n: writes orgs/&lt;org&gt;/&lt;org&gt;.jsonnet from the live org (patches against the template defaults, sorted teams and repos) | cli | free | P0 | covered | **unverified** | `tests/cli/test_import.py::test_import_writes_config`, `tests/cli/test_import.py::test_import_validates`, `tests/cli/test_import.py::test_import_plans_no_change` |
| `cli.import.overwrite-backup-secrets` | import over an existing file: prompt without -f, '&lt;file&gt;.bak' backup, 'Copying secrets from previous configuration.', webhook URL masking ('&lt;n&gt; URLs have been masked.') | cli | free | P1 | covered | **unverified** | `tests/cli/test_commands_import.py::test_reimport_backs_up_copies_secrets_and_masks_urls`, `tests/cli/test_commands_import.py::test_import_without_force_asks_before_overwriting`, `tests/cli/test_commands_import.py::test_reimport_keeps_the_secret_of_a_masked_webhook` |
| `cli.import.web-ui` | import without -n reads the web-UI settings (full credentials); with -n the warning 'the Web UI will not be queried ...' is printed (UI only) | web_ui | free | P2 | covered | **unverified** | `tests/web_ui/test_web_settings.py::test_import_reads_web_settings`, `tests/cli/test_commands_import.py::test_import_without_web_ui_warns_and_skips_web_settings` |
| `cli.fetch-config` | fetch-config [-f] [-p PR] [-r REF] [-s SUFFIX]: reads otterdog/&lt;org&gt;.jsonnet from the config repo default branch, a ref or a PR head | cli | free | P0 | covered | **unverified** | `tests/cli/test_config_repo_cli.py::test_push_fetch_round_trip`, `tests/cli/test_commands_config_repo.py::test_fetch_config_from_a_pull_request_and_a_ref`, `tests/cli/test_commands_config_repo.py::test_fetch_config_asks_before_overwriting`, `tests/cli/test_commands_config_repo.py::test_fetch_config_names_the_ref`, `tests/cli/test_commands_config_repo.py::test_config_repo_commands_report_a_missing_repository` |
| `cli.push-config` | push-config [-m MSG] [-n] [-f]: PUTs otterdog/&lt;org&gt;.jsonnet on the default branch after a local-plan diff and a prompt | cli | free | P0 | covered | **unverified** | `tests/cli/test_config_repo_cli.py::test_push_fetch_round_trip`, `tests/cli/test_commands_config_repo.py::test_push_config_shows_the_diff_and_asks`, `tests/cli/test_commands_config_repo.py::test_push_config_without_diff_uses_the_default_message`, `tests/cli/test_commands_config_repo.py::test_push_config_refuses_an_invalid_configuration`, `tests/cli/test_commands_config_repo.py::test_push_config_of_an_invalid_configuration_fails`, `tests/cli/test_commands_config_repo.py::test_push_config_to_a_repository_without_definition`, `tests/cli/test_commands_config_repo.py::test_config_repo_commands_report_a_missing_repository` |
| `cli.open-pr` | open-pr -b BRANCH -t TITLE -a AUTHOR: branch otterdog/&lt;branch&gt;, the local file, a PR with the fixed body (always prompts) | cli | free | P1 | covered | **unverified** | `tests/cli/test_config_repo_cli.py::test_open_pr`, `tests/cli/test_commands_config_repo.py::test_open_pr_opens_nothing_when_it_must_not`, `tests/cli/test_commands_config_repo.py::test_open_pr_title_and_body`, `tests/cli/test_commands_config_repo.py::test_config_repo_commands_report_a_missing_repository` |
| `cli.plan` | plan -n: 'Planning execution:', legend, '+ add' / '\~' / '!' / '- remove' blocks, 'Plan: A to add, C to change, D to delete.' against the live org | cli | free | P0 | covered | **unverified** | `cli.repo.lifecycle`, `cli.team`, `cli.bpr.public`, `cli.ruleset.public`, `cli.environment`, `cli.plan-mismatch` |
| `cli.plan.no-web-ui` | -n/--no-web-ui: token-only credentials, web-UI org settings neither read, diffed nor applied | cli | free | P0 | covered | **unverified** | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `cli.repo.lifecycle` |
| `cli.plan.web-ui` | plan/apply without -n: full credentials (username, password, TOTP), web-UI settings read through Playwright; 'invalid credentials' when they are missing (UI only) | web_ui | free | P2 | covered | **unverified** | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip`, `tests/cli/test_commands_errors.py::test_web_commands_need_the_web_credentials` |
| `cli.plan.repo-filter` | -r/--repo-filter PATTERN: only matching repositories are loaded and planned; organization-level objects are always diffed | cli | free | P0 | covered | offline | `cli.repo.lifecycle`, `cli.team`, `O-LPLAN-FILTER` |
| `cli.plan.update-secrets` | --update-secrets [--update-filter PATTERN]: forced '!' update of secrets whose name matches (values are never compared) | cli | free | P1 | covered | offline | `cli.secrets`, `O-LPLAN-FORCED-SECRETS`, `cli.org.secret`, `cli.environment.secrets` |
| `cli.plan.update-webhooks` | --update-webhooks [--update-filter URL-PATTERN]: forced '!' update of webhooks with a non-dummy secret and a matching url | cli | free | P1 | covered | offline | `O-LPLAN-FORCED-WEBHOOKS`, `cli.repo.webhook-secret`, `tests/webhooks/test_managed_org_hook.py::test_org_webhook_secret` |
| `cli.plan.only-secrets` | --only-secrets: only secret patches (org, repo, environment) are planned/applied | offline | free | P2 | covered | offline | `O-LPLAN-FORCED-SECRETS`, `O-LPLAN-ONLY-SECRETS` |
| `cli.plan.read-only-note` | read-only keys (plan, two_factor_requirement, template_repository): "Note: setting '&lt;k&gt;' is read-only, will be skipped." and not counted | cli | free | P1 | covered | offline | `cli.plan-mismatch`, `O-LPLAN-READ-ONLY-KEYS` |
| `cli.plan.webhook-secret-removal` | removing a webhook secret prints "Warning: removing secret for webhook with url '&lt;url&gt;'" | offline | free | P2 | covered | offline | `O-LPLAN-FORCED-WEBHOOKS`, `O-LPLAN-WEBHOOK-SECRET-REMOVED` |
| `cli.plan.validation-abort` | validation errors abort the plan: 'Planning aborted due to validation errors.' and no Plan: line | offline | free | P0 | covered | offline | `O-VAL-RULESET-STRICT`, `regression.code-scanning-new-repo`, `regression.repo-ruleset-without-strict` |
| `cli.plan.errors` | plan error paths: 'planning aborted: &lt;e&gt;' (exit 1, e.g. value_type change), 'failed to load configuration' (1), network/GitHub errors (2) | offline | free | P1 | covered | offline | `O-LPLAN-ERRORS`, `tests/offline/test_cli_exit_codes.py::test_plan_without_github_exits_2` |
| `cli.check-status` | check-status [-n] [-r] [-j FILE]: 'Archived/Validation status/Synchronization status' lines and a JSON list {org_id, is_archived, validation_status, sync_status} | cli | free | P0 | covered | **unverified** | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `tests/cli/test_commands_check_status.py::test_check_status_reports_validity_and_sync`, `tests/cli/test_commands_check_status.py::test_check_status_of_an_invalid_configuration`, `tests/cli/test_commands_check_status.py::test_check_status_fails_for_an_invalid_configuration` |
| `cli.local-plan` | local-plan [-s SUFFIX]: 'Printing local diff:' of &lt;org&gt;.jsonnet against &lt;org&gt;.jsonnet-BASE without GitHub (same engine as the webapp validation) | offline | free | P0 | covered | offline | `O-LPLAN-ADD`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE` |
| `cli.local-plan.suffix-and-missing-base` | local-plan -s other suffix; a missing BASE file: 'failed to load current configuration' / "configuration file '...-BASE' does not exist" (exit 1) | offline | free | P2 | covered | offline | `tests/offline/test_cli_local_plan_flags.py::test_local_plan_compares_with_another_suffix`, `tests/offline/test_cli_local_plan_flags.py::test_missing_other_side_fails_the_plan` |
| `cli.local-plan.dummy-secrets` | local-plan replaces dummy secrets by '&lt;DUMMY&gt;' and diffs secret references ('pass:a' -&gt; 'pass:b'), resolve_secrets off | offline | free | P1 | covered | offline | `O-LPLAN-ADD`, `O-LPLAN-FORCED-SECRETS`, `O-LPLAN-FORCED-WEBHOOKS`, `O-LPLAN-SECRET-REFS`, `tests/offline/test_cli_local_plan_flags.py::test_local_apply_forces_no_dummy_secret`, `tests/offline/test_cli_local_plan_flags.py::test_local_plan_forces_no_dummy_secret` |
| `cli.apply` | apply -f -n: applies the plan ('Applying changes:', progress, 'Executed plan: A added, C changed, D deleted.' / 'D live resources ignored.') | cli | free | P0 | covered | **unverified** | `cli.repo.lifecycle`, `cli.team`, `cli.secrets`, `cli.bpr.public`, `cli.ruleset.public`, `cli.environment` |
| `cli.apply.delete-resources` | -d/--delete-resources: REMOVE patches are applied only with -d (else skipped) | cli | free | P0 | covered | **unverified** | `cli.repo.lifecycle`, `cli.team`, `cli.bpr.public`, `cli.ruleset.public`, `cli.repo.webhook` |
| `cli.apply.deletion-hints` | without -d: 'No changes required.' + '&lt;n&gt; resource(s) would be deleted with flag '--delete-resources'.' or 'No resource will be removed, use flag ...' | offline | free | P1 | covered | offline | `tests/offline/test_cli_local_apply.py::test_removals_without_delete_flag_are_only_hinted`, `tests/offline/test_cli_local_apply.py::test_declined_approval_cancels_the_apply` |
| `cli.apply.prompt` | apply/local-apply without -f: "Do you want to perform these actions? (Only 'yes' or 'y' ...)"; 'n' -&gt; 'Apply cancelled.' (exit 0); EOF -&gt; exit 2 | offline | free | P2 | covered | offline | `tests/offline/test_cli_local_apply.py::test_declined_approval_cancels_the_apply`, `tests/offline/test_cli_local_apply.py::test_end_of_input_at_the_prompt_exits_2`, `tests/cli/test_commands_local_apply.py::test_local_apply_applies_the_local_diff` |
| `cli.apply.validation-errors` | apply with validation errors prints 'Planning aborted due to validation errors.' + 'No changes required.' and exits 0 | cli | free | P1 | **partial** | **unverified** | `tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors` |
| `cli.apply.failed-patches` | a failing patch prints 'failed to apply patch: &lt;TYPE&gt; - &lt;header&gt;' and the exit code is the number of failed patches | cli | free | P1 | covered | **unverified** | `tests/cli/test_commands_errors.py::test_failed_patches_set_the_exit_code` |
| `cli.local-apply` | local-apply [-s SUFFIX] [-f] [-n] [-d]: applies the BASE -&gt; config diff to live GitHub (what the webapp does after a merge) | cli | free | P1 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/cli/test_commands_local_apply.py::test_local_apply_applies_the_local_diff` |
| `cli.web-login` | web-login: opens a headful browser logged in as the bot, waits for input, logs out (UI only) | web_ui | free | P2 | covered | **unverified** | `tests/web_ui/test_web_commands.py::test_web_login_opens_a_session` |
| `cli.install-app` | install-app -a SLUG: installs an App through the web UI ('app already installed, skipping.' / 'app installed.') (UI only) | web_ui | free | P2 | **partial** | **unverified** | `tests/web_ui/test_web_commands.py::test_install_and_uninstall_app` |
| `cli.uninstall-app` | uninstall-app -a SLUG: uninstalls an App through the web UI ('uninstalled app.') (UI only) | web_ui | free | P2 | **partial** | **unverified** | `tests/web_ui/test_web_commands.py::test_install_and_uninstall_app` |
| `cli.review-permissions` | review-permissions [-a SLUG] [-g] [-f]: lists requested App permission updates and grants them through the web UI (UI only) | web_ui | free | P2 | **partial** | **unverified** | `tests/web_ui/test_web_commands.py::test_review_permissions_lists_requests` |
| `cli.install-deps` | install-deps: runs 'python -m playwright install firefox' (exits 0 even when it fails) (UI only) | web_ui | free | P2 | covered | **unverified** | `tests/web_ui/test_web_commands.py::test_install_deps_keeps_the_installed_firefox`, `tests/web_ui/test_web_commands.py::test_install_deps_reports_a_failed_download`, `tests/web_ui/test_web_commands.py::test_failed_install_deps_exits_non_zero` |

Details:

- **`cli.help`** (covered, P2, `offline`): --help lists the 29 subcommands; no subcommand or an unknown option is a click usage error (exit 2)
    - Source: `otterdog/cli.py:28`, `otterdog/cli.py:171-176`, `otterdog/cli.py:179-969`
    - Operations: run, exit-code
    - Notes: --help/-h list the 29 inventoried commands (an unknown extra command only warns), validate --help the shared options; otterdog alone, an unknown option, an unknown command and open-pr without -a exit 2 with the click usage on stderr before any config load (v1.6.1 and 9bdeb75)
- **`cli.global.organizations`** (covered, P2, `offline`): ORGANIZATIONS positional: project name or github_id (case-insensitive), none = every non-archived org, exit code = max over orgs
    - Source: `otterdog/cli.py:100`, `otterdog/cli.py:972-1001`, `otterdog/config.py:340-362`
    - Operations: run, exit-code, config
    - Notes: First org 1 error, second valid: no positional processes both in config order and exits 1 (largest, not the last org's 0); github_id and project name match case-insensitively; positionals keep their order; 'nope' exits 2 before any header
- **`cli.global.local-mode`** (covered, P1, `offline`): --local uses the vendored template without cloning; a missing vendor file fails with "template file '&lt;f&gt;' does not exist" (exit 2)
    - Source: `otterdog/cli.py:89-98`, `otterdog/jsonnet.py:98-110`
    - Operations: config, error
    - Notes: Missing vendor file: validate and show exit 2 ("template file '...' does not exist", before the project header), local-plan exits 1 ('planning aborted: template file ...'); vendoring fixes it
- **`cli.global.verbosity`** (covered, P2, `offline`): -v shows Info messages (otherwise 'in order to print validation infos, enable printing info messages by adding '-v' flag.'); -vv adds tracebacks
    - Source: `otterdog/cli.py:73-78`, `otterdog/logging.py:57-97`, `otterdog/operations/validate.py:95-100`, `otterdog/operations/diff_operation.py:241-246`
    - Operations: run
    - Notes: level 0: Info messages only counted (validate hint, local-plan 'there have been 1 validation infos'); -v: the Info boxes (validate and local-plan, O-VAL-INFOS); -vv: DEBUG lines and the rich traceback of an escaped exception on stderr instead of the Error box; -vvv: TRACE lines.
- **`cli.global.exit-codes`** (covered, P1, `offline`): Uncaught exceptions and config load errors exit 2 ('Error: &lt;message&gt;', traceback on stderr only with -vv)
    - Source: `otterdog/cli.py:102-117`, `otterdog/cli.py:999-1001`, `otterdog/logging.py:116-143`
    - Operations: exit-code, error
    - Known bugs: KB-025, KB-034
    - New findings: F-07
    - Notes: 0 valid, 1 one error, 1 jsonnet evaluation error (caught 'failed to load configuration'), 2 schema type error / unknown org (escaped exception, boxed Error, no summary, empty stderr). KB-034 (2 errors exit 2, 256 errors exit 0 for validate and local-plan) and KB-025 are asserted as the correct behaviour in known_bug-marked non-strict xfails (O-KB-EXIT-STATUS-ERROR-COUNT, O-KB-SECRET-WITH-COLONS)
- **`cli.validate`** (covered, P0, `offline`): validate: 'Validating organization configurations:', per-org header, 'Validation succeeded' / "Validation succeeded': i info(s), w warning(s), 0 error(s)" / 'Validation failed: ...'
    - Source: `otterdog/cli.py:179-186`, `otterdog/operations/validate.py:43-104`
    - Operations: run, validate, exit-code
    - Notes: the stray quote of the warning-only summary ("Validation succeeded': 0 info(s), 1 warning(s), 0 error(s)") is verified offline; validate needs GitHub only for teams (org members) and code scanning languages
- **`cli.validate.missing-config`** (covered, P2, `offline`): validate/plan of a missing org file: "configuration file '&lt;f&gt;' does not exist, run 'fetch-config' or 'import' first." (exit 1)
    - Source: `otterdog/operations/validate.py:60-62`, `otterdog/operations/diff_operation.py:155-159`
    - Operations: error, exit-code
    - Notes: validate and show exit 1 ("does not exist, run 'fetch-config' or 'import' first."), local-plan exit 1 ('does not yet exist, run fetch-config or import first.') Live: validate and list-members/delete-file/sync-template/push-config/open-pr "configuration file '&lt;f&gt;' does not exist, run 'fetch-config' or 'import' first.", local-plan/plan/apply/check-status '... does not yet exist, run fetch-config or import first.', all exit 1 (verified offline too).
- **`cli.show`** (covered, P2, `offline`): show: prints every model object as key = value blocks (no credentials)
    - Source: `otterdog/cli.py:189-209`, `otterdog/operations/show.py:47-96`
    - Operations: run
    - Notes: show prints settings, org webhook, repository, repo variable, BPR and environment blocks with values, no diff lines; it resolves no credentials (works with a provider-less entry where validate exits 1). File scenarios/offline/cli/show.yaml
- **`cli.show.markdown`** (covered, P2, `offline`): show --markdown [--output-dir DIR]: writes configuration.md and repo-&lt;name&gt;.md (mkdocs tabs) instead of printing
    - Source: `otterdog/cli.py:189-209`, `otterdog/operations/show.py:96-288`
    - Operations: run
    - Known bugs: KB-050
    - Notes: configuration.md (front matter, 5 tabs, webhook/secret/variable/repository rows) and repo-&lt;name&gt;.md (6 tabs) in a new --output-dir; the '[&lt;name&gt;]' link texts are swallowed by rich markup
- **`cli.show-live`** (covered, P2, `cli`): show-live [-n]: prints the live configuration read from GitHub (web UI unless -n)
    - Source: `otterdog/cli.py:212-227`, `otterdog/operations/show_live.py:35-82`
    - Operations: run, converge
    - Notes: show-live -n: header, the --no-web-ui warning, REST-backed settings equal GET /orgs/{org} (plan from plan.name), no web-only key in the settings block, every repository/team the oracle lists has its block (advisory forks excluded like otterdog). Without -n it runs as the trusted reader of the web_ui round trip (reset SUT only).
- **`cli.show-default.markdown`** (covered, P2, `offline`): show-default --markdown: mkdocs tab blocks with jsonnet code fences
    - Source: `otterdog/operations/show_default.py:207-224`
    - Operations: run
    - Notes: 12 tabs, each with a jsonnet fence holding its orgs.new... = { block, no plain-text header
- **`cli.canonical-diff`** (covered, P2, `offline`): canonical-diff: unified diff of the file versus its canonical re-serialization (labels inverted, always exit 0)
    - Source: `otterdog/cli.py:820-827`, `otterdog/operations/canonical_diff.py:35-105`
    - Operations: run
    - Known bugs: KB-010, KB-050
- **`cli.check-token-permissions`** (covered, P1, `cli`): check-token-permissions [-l]: X-OAuth-Scopes must include admin:org, admin:org_hook, delete_repo, repo, workflow ('Missing scopes: ...', exit 1)
    - Source: `otterdog/cli.py:935-950`, `otterdog/operations/check_token_permissions.py:26-78`
    - Operations: run, exit-code, permission
    - Known bugs: KB-078
    - Notes: -l: 'Granted scopes:' == the token's X-OAuth-Scopes; config_reader (fine-grained): 'Missing scopes:' == the five required minus granted (order-insensitive: printed from a frozenset), exit 1. A fine-grained ADMIN token is reported the same way (KB-078: the command only knows classic scopes); its test is skipped with a classic admin token.
- **`cli.list-members`** (covered, P2, `cli`): list-members [--two-factor-disabled]: 'Found &lt;n&gt; members.' / 'Found &lt;x&gt; / &lt;total&gt; members with 2FA disabled. Organization has 2FA ...'
    - Source: `otterdog/cli.py:357-365`, `otterdog/operations/list_members.py:40-99`
    - Operations: run
    - Notes: 'Found &lt;n&gt; members.' n = GET /orgs/{org}/members; --two-factor-disabled: '&lt;x&gt; / &lt;n&gt; members with 2FA disabled' (x = filter=2fa_disabled) and the 2FA status from the LOCAL config (two_factor_requirement::: true -&gt; enabled, false -&gt; disabled on the same org).
- **`cli.list-apps`** (covered, P2, `cli`): list-apps [--json]: installations of the org with app_id, slug and permissions (JSON array sorted by slug)
    - Source: `otterdog/cli.py:346-354`, `otterdog/operations/list_apps.py:30-85`
    - Operations: run
    - Known bugs: KB-051
    - Notes: --json array == GET /orgs/{org}/installations reduced to app_id/app_slug/permissions, sorted by slug, e2e App listed with its id when ready; text mode: one app['&lt;slug&gt;'] block with app_id per installation.
- **`cli.list-advisories`** (covered, P2, `cli`): list-advisories [-s state ...] [-d] [-w]: CSV of repository security advisories (header line first; -w scrapes the web UI)
    - Source: `otterdog/cli.py:905-932`, `otterdog/operations/list_advisories.py:23-153`
    - Operations: run
    - Known bugs: KB-050
    - Notes: draft advisory of a run repo: exact CSV header, full row (org, draft, low, NO_CVE, summary, html_url, dates, empty comment fields without -w) for default states and -s all, absent from -s published; -d blocks without header; listings == the oracle per state.
- **`cli.dispatch-workflow`** (covered, P2, `cli`): dispatch-workflow [-r repo] --workflow WF: POST workflow dispatch on the default branch ("workflow '&lt;wf&gt;' dispatched for repo '&lt;repo&gt;'")
    - Source: `otterdog/cli.py:246-264`, `otterdog/operations/dispatch_workflow.py:39-71`
    - Operations: run
    - Known bugs: KB-045
    - Notes: dispatch on the default branch -&gt; a workflow_dispatch run with head_branch main; unknown workflow 'failed to dispatch ...'; unknown repo exits non-zero.
- **`cli.delete-file`** (covered, P2, `cli`): delete-file -r REPO --path P [-m MSG]: deletes a file of a configured repository ("Deleting file '&lt;p&gt;' in repository '&lt;org&gt;/&lt;repo&gt;': succeeded")
    - Source: `otterdog/cli.py:799-817`, `otterdog/operations/delete_file.py:46-108`
    - Operations: run, error
    - Known bugs: KB-043, KB-044
    - Notes: -m message and default message "Deleting file '&lt;p&gt;' with otterdog." as head commit messages, file gone; missing file creates no commit; unconfigured repo untouched.
- **`cli.sync-template`** (covered, P2, `cli`): sync-template -r REPO: re-copies the template repository's files into a repo created from it (post_process_template_content rendered)
    - Source: `otterdog/cli.py:783-796`, `otterdog/operations/sync_template.py:36-92`, `otterdog/providers/github/rest/repo_client.py:1377-1431`
    - Operations: run
    - Notes: Python test instead of the suggested YAML cli.repo.template: template change -&gt; 'updated file' for README.md (re-rendered {{org}}/{{repo}}), TEMPLATE.txt (verbatim), NEW.txt; second run updates nothing; a repo without template_repository is skipped.
- **`cli.list-blueprints`** (covered, P1, `webapp`): list-blueprints [-b ID]: table of remediation PRs read anonymously from &lt;defaults.base_url&gt;/api/blueprints/remediations
    - Source: `otterdog/cli.py:378-386`, `otterdog/operations/list_blueprints.py:44-110`
    - Operations: run, error
    - Known bugs: KB-042
    - Notes: W-CLI-BLUEPRINTS (tests/webapp): with a required_file remediation PR and the SUT CLI installed with the app group (install_cli with_app=True, host runtime only) and base_url = the webapp, the 'Projects' table is exactly [&lt;id&gt;, &lt;org&gt;, &lt;repo&gt;, &lt;PR url&gt;]; without defaults.base_url: exit 2 and "no base_url set which is required when using operation 'list-blueprints'". A CLI-only install crashes with ModuleNotFoundError (KB-042, cli.kb.blueprint-commands-without-webapp).
- **`cli.approve-blueprints`** (covered, P1, `webapp`): approve-blueprints [-b ID]: merges every remediation PR (rebase, else squash, else merge) ('Merging PR #&lt;n&gt;: merged.')
    - Source: `otterdog/cli.py:389-397`, `otterdog/operations/approve_blueprints.py:38-138`
    - Operations: run
    - Known bugs: KB-042
    - Notes: W-CLI-BLUEPRINTS (tests/webapp): approve-blueprints -b &lt;id&gt; prints 'Merging PR #&lt;n&gt;: merged.', the PR is merged on GitHub, UpdateBlueprintStatusTask and DeleteBranchTask finish, the remediation branch is gone and the status goes recheck/success. A CLI-only install crashes with ModuleNotFoundError (KB-042).
- **`cli.import`** (covered, P0, `cli`): import -f -n: writes orgs/&lt;org&gt;/&lt;org&gt;.jsonnet from the live org (patches against the template defaults, sorted teams and repos)
    - Source: `otterdog/cli.py:400-423`, `otterdog/operations/import_configuration.py:47-145`, `otterdog/models/github_organization.py:389-524`
    - Operations: import, converge
    - Known bugs: KB-024
- **`cli.import.overwrite-backup-secrets`** (covered, P1, `cli`): import over an existing file: prompt without -f, '&lt;file&gt;.bak' backup, 'Copying secrets from previous configuration.', webhook URL masking ('&lt;n&gt; URLs have been masked.')
    - Source: `otterdog/operations/import_configuration.py:56-131`, `otterdog/operations/__init__.py:82-98`
    - Operations: import, prompt, security
    - Known bugs: KB-048
    - Notes: Second import: &lt;file&gt;.bak == previous file, 'Copying secrets ...', 'Masking webhooks ... 1 URLs have been masked.', repo secret and unmasked hook keep the literal value, live URL replaced by the masked one; without -f 'n' -&gt; 'Operation cancelled.' exit 1, file and backup unchanged.
- **`cli.import.web-ui`** (covered, P2, `web_ui`): import without -n reads the web-UI settings (full credentials); with -n the warning 'the Web UI will not be queried ...' is printed
    - Source: `otterdog/operations/import_configuration.py:76-91`, `otterdog/providers/github/web.py:57-165`
    - Operations: import
    - Notes: import -n: the warning, no web-only key written (template defaults), secrets read as \*\*\*\*\*\*\*\*; web import: no warning (assertion added inside the existing login).
- **`cli.fetch-config`** (covered, P0, `cli`): fetch-config [-f] [-p PR] [-r REF] [-s SUFFIX]: reads otterdog/&lt;org&gt;.jsonnet from the config repo default branch, a ref or a PR head
    - Source: `otterdog/cli.py:267-301`, `otterdog/operations/fetch_config.py:54-113`
    - Operations: run, prompt, config
    - Known bugs: KB-049
    - Notes: -p head, -r branch, -s suffix files, overwrite prompt n/y, unknown PR and missing config repo 'failed to fetch definition from repo' exit 1.
- **`cli.push-config`** (covered, P0, `cli`): push-config [-m MSG] [-n] [-f]: PUTs otterdog/&lt;org&gt;.jsonnet on the default branch after a local-plan diff and a prompt
    - Source: `otterdog/cli.py:304-330`, `otterdog/operations/push_config.py:54-205`
    - Operations: run, prompt, plan
    - Known bugs: KB-046
    - Notes: diff + prompt n ('push cancelled.', no commit) / y (pushed, -m commit message), identical file pushes nothing, -n pushes without diff/prompt with the default message, invalid config not pushed, 'No configuration yet available.' for a repo without definition, missing repo exit 1.
- **`cli.open-pr`** (covered, P1, `cli`): open-pr -b BRANCH -t TITLE -a AUTHOR: branch otterdog/&lt;branch&gt;, the local file, a PR with the fixed body (always prompts)
    - Source: `otterdog/cli.py:333-343`, `otterdog/operations/open_pull_request.py:50-195`
    - Operations: run, prompt, error
    - Notes: identical (exit 0), validation error (exit 1), unknown author (exit 2), 'n' (exit 1) open nothing and leave no otterdog/&lt;branch&gt;; opened PR: title, fixed body naming the author, head, printed URL; missing repo exit 1.
- **`cli.plan.no-web-ui`** (covered, P0, `cli`): -n/--no-web-ui: token-only credentials, web-UI org settings neither read, diffed nor applied
    - Source: `otterdog/cli.py:427-434`, `otterdog/operations/diff_operation.py:131-132`, `otterdog/providers/github/__init__.py:104-124`
    - Operations: coerce, config
    - Notes: every live command of the harness passes -n; the baseline renders the template defaults of the web keys and still converges, which proves they are ignored
- **`cli.plan.web-ui`** (covered, P2, `web_ui`): plan/apply without -n: full credentials (username, password, TOTP), web-UI settings read through Playwright; 'invalid credentials' when they are missing
    - Source: `otterdog/operations/diff_operation.py:131-132`, `otterdog/providers/github/web.py:57-252`, `otterdog/credentials/__init__.py:52-74`
    - Operations: plan, config
    - Notes: plan/apply/check-status/import/show-live/local-apply without -n and with unset web-login variables: 'invalid credentials' + "environment variable 'E2E_OTTERDOG_NO_WEB_USERNAME' for key 'username' not found", exit 1, before any web access (no login possible).
- **`cli.plan.repo-filter`** (covered, P0, `cli`): -r/--repo-filter PATTERN: only matching repositories are loaded and planned; organization-level objects are always diffed
    - Source: `otterdog/cli.py:435-441`, `otterdog/models/github_organization.py:913-916`, `otterdog/models/repository.py:793-796`
    - Operations: filter, plan
    - Known bugs: KB-077
    - Notes: O-LPLAN-FILTER (offline): -r '&lt;p&gt;-a' plans the matching repository and the organization variable and leaves the other repository and its branch protection rule out (0/2/0); a pattern '&lt;p&gt;-\*' plans both (0/4/0); an added repository outside the filter is not planned, one matching it is. A repository that exists only in the other configuration is planned for removal whatever the filter (KB-077, step-level). Every live scenario plans with -r e2e-&lt;run&gt;-\* (cli.repo.lifecycle, cli.team).
- **`cli.plan.update-secrets`** (covered, P1, `cli`): --update-secrets [--update-filter PATTERN]: forced '!' update of secrets whose name matches (values are never compared)
    - Source: `otterdog/cli.py:449-468`, `otterdog/models/secret.py:132-147`
    - Operations: forced-update, filter
    - Known bugs: KB-056
    - Notes: offline (O-LPLAN-FORCED-SECRETS): forced '!' updates of organization, repository and environment secrets (every key 'v -&gt; v', 0/10/0) and --update-filter selecting one secret (0/2/0). Live: cli.secrets and cli.environment.secrets apply with --update-secrets, cli.org.secret applies with --update-secrets and --update-filter and asserts '! org_secret[name=&lt;P&gt;_ORG_SECRET]' while the other secret is not forced. local-plan also forces dummy secrets that every apply skips (KB-056).
- **`cli.plan.update-webhooks`** (covered, P1, `cli`): --update-webhooks [--update-filter URL-PATTERN]: forced '!' update of webhooks with a non-dummy secret and a matching url
    - Source: `otterdog/cli.py:442-448`, `otterdog/models/webhook.py:178-197`
    - Operations: forced-update, filter
    - Known bugs: KB-056
    - Notes: offline (O-LPLAN-FORCED-WEBHOOKS): forced '!' updates of org and repo hooks with a secret, never of a hook without secret (0/14/0), --update-filter on urls (0/7/0). Live: cli.repo.webhook-secret applies with --update-webhooks and an url filter (only the secured hook is forced) and H-ORG-HOOK-SECRET forces an organization hook. local-plan also forces hooks with a dummy secret that every apply skips (KB-056).
- **`cli.plan.only-secrets`** (covered, P2, `offline`): --only-secrets: only secret patches (org, repo, environment) are planned/applied
    - Source: `otterdog/cli.py:456-462`, `otterdog/operations/diff_operation.py:184-185`
    - Operations: filter, forced-update
    - Notes: verified offline: local-plan --only-secrets --update-secrets shows the forced org secret and hides a repository description change. only-secrets-forced and only-secrets-changes steps; O-LPLAN-ONLY-SECRETS covers it too. scenarios/offline/secrets/lplan-only-secrets.yaml: with --update-secrets org, repo and env secrets forced (8 changed keys) and the repository change hidden; without --update-secrets a noop; control without the flag shows only the repository change
- **`cli.plan.read-only-note`** (covered, P1, `cli`): read-only keys (plan, two_factor_requirement, template_repository): "Note: setting '&lt;k&gt;' is read-only, will be skipped." and not counted
    - Source: `otterdog/operations/plan.py:112-117`, `otterdog/models/organization_settings.py:55-68`, `otterdog/models/repository.py:73`
    - Operations: plan, coerce
    - Notes: verified offline too (local-plan of plan free -&gt; team and template_repository 'o/a' -&gt; 'o/b': the Note, 'Plan: 0 to add, 0 to change, 0 to delete.'). plan (base_config on team), two_factor_requirement, template_repository notes not counted; mixed with writable keys (0/2/0).
- **`cli.plan.webhook-secret-removal`** (covered, P2, `offline`): removing a webhook secret prints "Warning: removing secret for webhook with url '&lt;url&gt;'"
    - Source: `otterdog/operations/plan.py:103-110`, `otterdog/models/webhook.py:201-223`
    - Operations: plan, security
    - Notes: verified offline with local-plan. org and repo hook secret removal warnings; also O-LPLAN-WEBHOOK-SECRET-REMOVED. scenarios/offline/webhooks/lplan-webhook-secret.yaml: org and repo webhooks ('- secret = ...' + the Warning), a changed reference without warning, an unchanged one noop
- **`cli.plan.errors`** (covered, P1, `offline`): plan error paths: 'planning aborted: &lt;e&gt;' (exit 1, e.g. value_type change), 'failed to load configuration' (1), network/GitHub errors (2)
    - Source: `otterdog/operations/diff_operation.py:115-176`, `otterdog/operations/plan.py:128-139`
    - Operations: error, exit-code
    - Notes: verified offline: changing a custom property value_type prints "planning aborted: trying to change 'value_type' to 'true_false' for custom_property[name="p1"] which is not supported." exit 1. value_type change 'planning aborted: ...' exit 1, head not evaluating 'failed to load configuration' exit 1, other side not evaluating 'failed to load current configuration' exit 1, plan in the network sandbox 'Cannot connect to host api.github.com' exit 2
- **`cli.check-status`** (covered, P0, `cli`): check-status [-n] [-r] [-j FILE]: 'Archived/Validation status/Synchronization status' lines and a JSON list {org_id, is_archived, validation_status, sync_status}
    - Source: `otterdog/cli.py:491-527`, `otterdog/operations/check_status.py:25-111`
    - Operations: run, plan, exit-code
    - Known bugs: KB-011
    - Notes: warning-only config: is_valid false (warnings 1), in_sync false, counts 0; -r counts per filtered repo (== plan change count); additions/deletions; read-only plan mismatch in_sync false with 0 counts; invalid config: no comparison.
- **`cli.local-plan.dummy-secrets`** (covered, P1, `offline`): local-plan replaces dummy secrets by '&lt;DUMMY&gt;' and diffs secret references ('pass:a' -&gt; 'pass:b'), resolve_secrets off
    - Source: `otterdog/operations/local_plan.py:82-87`, `otterdog/operations/local_plan.py:59-60`
    - Operations: plan, security
    - Known bugs: KB-056
    - Notes: '&lt;DUMMY&gt;' adds (org/repo/env secrets, webhook), dummies unchanged noop, reference change, dummy -&gt; reference; also O-LPLAN-SECRET-REFS. '&lt;DUMMY&gt;' additions, unchanged dummies noop, org/repo/env references diffed ('\~ value = "pass:e2e/a" -&gt; "pass:e2e/b"'); local-plan --update-secrets forces dummies that local-apply skips
- **`cli.apply.deletion-hints`** (covered, P1, `offline`): without -d: 'No changes required.' + '&lt;n&gt; resource(s) would be deleted with flag '--delete-resources'.' or 'No resource will be removed, use flag ...'
    - Source: `otterdog/operations/apply.py:100-113`, `otterdog/operations/apply.py:155-163`
    - Operations: remove, run
    - Notes: local-apply with only removals and no -d prints the hint without touching GitHub (sample tests/unit/data/local-apply-no-changes.txt, captured offline). Removal-only: 'No changes required.' + '1 resource(s) would be deleted ...', no prompt, with and without -f; with an addition: 'No resource will be removed, use flag ...' before the prompt
- **`cli.apply.prompt`** (covered, P2, `offline`): apply/local-apply without -f: "Do you want to perform these actions? (Only 'yes' or 'y' ...)"; 'n' -&gt; 'Apply cancelled.' (exit 0); EOF -&gt; exit 2
    - Source: `otterdog/operations/apply.py:110-121`, `otterdog/utils.py:580-585`
    - Operations: prompt, exit-code
    - Notes: offline (local-apply): 'n', 'no' and 'YES' cancel ('Apply cancelled.', exit 0, nothing executed), end of input fails with 'EOF when reading a line' (exit 2); live: local-apply answering 'n' creates nothing (cli.local-apply).
- **`cli.apply.validation-errors`** (partial, P1, `cli`): apply with validation errors prints 'Planning aborted due to validation errors.' + 'No changes required.' and exits 0
    - Source: `otterdog/operations/plan.py:121-126`, `otterdog/operations/apply.py:97-108`
    - Operations: validate, exit-code
    - Known bugs: KB-001
    - Notes: offline counterpart: `apply --local -f -n` with a validation error exits 0 without network (tests/unit/data/apply-validation-error.txt)
    - Suggested: `cli.kb.apply-exit-code`
    - Steps:
        - tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors asserts the correct exit status: an XFAIL while KB-001 exists, so the live behaviour is only observed through the expected failure
    - Assert:
        - covered once KB-001 is fixed (the test then passes strictly, XPASS first) or by a strict check of the printed texts
    - Needs:
        - a fix of KB-001, or a strict live assertion of the current output
- **`cli.apply.failed-patches`** (covered, P1, `cli`): a failing patch prints 'failed to apply patch: &lt;TYPE&gt; - &lt;header&gt;' and the exit code is the number of failed patches
    - Source: `otterdog/operations/apply.py:139-153`
    - Operations: error, exit-code
    - Notes: Python test (id cli.cmd.apply-failed-patches) instead of the suggested YAML: team_permissions of a missing team make PUT .../teams/&lt;t&gt;/repos 404 after the repo is created (the outline's unknown bypass team is only skipped with a warning by otterdog, get_actor_ids_with_type): exactly 2 'failed to apply patch: ADD - repository[...]', a non-zero exit (otterdog exits with the count, 2; the test does not pin it: KB-034 calls count-as-exit-status a bug), no team access on the failing repos, the other repo applied, plan still pending.
- **`cli.local-apply`** (covered, P1, `cli`): local-apply [-s SUFFIX] [-f] [-n] [-d]: applies the BASE -&gt; config diff to live GitHub (what the webapp does after a merge)
    - Source: `otterdog/cli.py:684-780`, `otterdog/operations/local_apply.py:24-90`
    - Operations: add, modify, remove, run
    - Known bugs: KB-077
    - Notes: prompt 'n' -&gt; 'Apply cancelled.' nothing created; -f '1 added'; live drift ignored ('No changes required.'); removal only with -d ('1 resource(s) would be deleted ...' then '1 deleted'), guarded by guard_config_change.
- **`cli.install-app`** (partial, P2, `web_ui`): install-app -a SLUG: installs an App through the web UI ('app already installed, skipping.' / 'app installed.')
    - Source: `otterdog/cli.py:840-853`, `otterdog/operations/install_app.py:39-74`, `otterdog/providers/github/web.py:286-317`
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
    - Source: `otterdog/cli.py:856-869`, `otterdog/operations/uninstall_app.py:39-72`, `otterdog/providers/github/web.py:319-350`
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
    - Source: `otterdog/cli.py:872-902`, `otterdog/operations/review_app_permissions.py:47-118`, `otterdog/providers/github/web.py:416-516`
    - Operations: run, prompt
    - Notes: Listing inside the existing web_ui login: every app['&lt;slug&gt;'] request belongs to an installed App, no 'failed to process app installation', nothing approved. Granting (-g / -f) needs a pending permission request.
    - Suggested: `UI-REVIEW-PERMISSIONS`
    - Steps:
        - request a new permission for a helper App, run review-permissions -a &lt;slug&gt;, then with -g -f
    - Assert:
        - "app['&lt;slug&gt;'] {" with the requested permission; -g prints 'requested permissions approved.'
    - Needs:
        - web_ui tier
        - available: the probe App of `web_ui.probe_app_slug` (docs/web-ui-testing.md)
- **`cli.install-deps`** (covered, P2, `web_ui`): install-deps: runs 'python -m playwright install firefox' (exits 0 even when it fails)
    - Source: `otterdog/cli.py:953-969`
    - Operations: run
    - Known bugs: KB-047
    - Notes: 0 logins: offline sandbox with PLAYWRIGHT_BROWSERS_PATH=tier dir (success, nothing downloaded) / empty dir (failure message, nothing installed).

<a id="config"></a>

## otterdog.json, base template and credentials

`config`: 22 features, 14 covered, 5 partial, 3 gaps (weighted 75%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `config.org-identity` | orgs.newOrg('&lt;project_name&gt;', '&lt;github_id&gt;'): project and GitHub id of the organization configuration | offline | free | P0 | covered | offline | `O-VAL-OK`, `cli.repo.lifecycle` |
| `config.discovery` | config discovery: -c FILE, else $OTTERDOG_CONFIG_ROOT or the cwd; otterdog.jsonnet wins over otterdog.json; none -&gt; exit 2 | offline | free | P1 | covered | offline | `tests/offline/test_config_loading.py::test_configuration_is_discovered_in_the_config_root`, `tests/offline/test_config_loading.py::test_no_configuration_file_found` |
| `config.jsonnet-config-file` | otterdog.jsonnet configuration files are evaluated (#542); malformed JSON fails with "failed to parse json file '&lt;f&gt;'" | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_jsonnet_configuration_file`, `tests/offline/test_config_loading.py::test_unreadable_configuration_file` |
| `config.local-defaults-override` | .otterdog-defaults.json next to the config file is deep-merged over `defaults` (its values win, #725) | offline | free | P1 | covered | offline | `tests/offline/test_config_loading.py::test_defaults_override_wins_over_the_configuration_file`, `tests/offline/test_config_credentials.py::test_pass_store_dir_from_the_defaults_override` |
| `config.base-template-required` | defaults.jsonnet.base_template is always required (even when every org has its own): "need to define a base template ..." exit 2 | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_default_base_template_is_required` |
| `config.organization-entries` | organizations[]: name and github_id required, per-org config_repo/base_template/credentials, approval_teams/admin_teams as string or list | offline | free | P2 | **partial** | offline | `tests/offline/test_cli_basics.py::test_list_projects_lists_the_offline_organization`, `tests/offline/test_config_loading.py::test_invalid_organization_entry`, `tests/offline/test_config_loading.py::test_organization_entry_variants` |
| `config.archived-organizations` | organizations with archived: true are ignored (not listed, not processed, unknown when named; #463) | offline | free | P2 | covered | offline | `tests/offline/test_config_loading.py::test_archived_organizations_are_ignored` |
| `config.config-dir-layout` | working layout: &lt;config_dir\|orgs&gt;/&lt;github_id&gt;/&lt;github_id&gt;.jsonnet, vendor/&lt;template repo&gt;/, import 'vendor/&lt;repo&gt;/&lt;file&gt;' | offline | free | P1 | covered | offline | `O-VAL-OK`, `cli.repo.lifecycle` |
| `config.exclude-teams` | defaults.github.exclude_teams (regexes): matching teams are not loaded (import, plan) and configuring one is a validation error | cli | free | P2 | covered | **unverified** | `tests/cli/test_org_config.py::test_excluded_teams_are_neither_loaded_nor_configurable` |
| `config.template-url` | base_template URL `https://github.com/<owner>/<repo>#<file>@<ref>`: only github.com, ref mandatory (exit 2 at load) | offline | free | P1 | covered | offline | `tests/offline/test_config_loading.py::test_invalid_template_url`, `tests/offline/test_config_loading.py::test_organization_entry_variants` |
| `config.template-clone` | non-local runs clone the template (unauthenticated) into &lt;config_dir&gt;/templates/&lt;owner&gt;/&lt;repo&gt;/&lt;ref&gt;, pull branch refs, never refresh tags/SHAs, copy into vendor/ | cli | free | P1 | **partial** | **unverified** | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `cli.repo.lifecycle` |
| `config.template-feature-gating` | the template drives what is managed: missing constructors skip a resource type, only template org-settings keys are fetched, hidden '::' fields are unmanaged | cli | free | P2 | **partial** | **unverified** | `tests/cli/test_baseline.py::test_baseline_in_sync_after_reset`, `tests/cli/test_org_config.py::test_hidden_fields_are_unmanaged` |
| `config.hook.validate-org-settings` | template hook validate-org-settings.py (exec'ed at validation, context.property_equals -&gt; "&lt;h&gt; has '&lt;k&gt;' set to '&lt;v&gt;' but '&lt;r&gt;' is required.") | offline | free | P0 | covered | offline | `tests/offline/test_config_template_hooks.py::test_validate_org_settings_hook`, `tests/offline/test_config_template_hooks.py::test_without_the_hook_the_template_default_validates` |
| `config.hook.validate-team` | template hook validate-team.py (per team at validation) | cli | free | P1 | **gap** | - | - |
| `config.hook.pre-add-object` | template hook pre-add-object-hook.py: runs for every ADD while the apply plan is printed (before the prompt) | offline | free | P1 | covered | offline | `tests/offline/test_config_template_hooks.py::test_pre_add_object_hook_runs_for_every_addition` |
| `config.hook.post-add-objects` | template hook post-add-objects-hook.py: runs once after an apply that added objects (CLI apply/local-apply and the webapp apply comment) | cli | free | P1 | **gap** | - | - |
| `config.hook.subdirectory-template` | templates in a subdirectory are copied without the repo-root hook scripts, so hooks never run (examples/template is such a case) | cli | free | P2 | **gap** | - | - |
| `config.credentials.env` | env credential provider: api_token/username/password/twofa_seed name environment variables (org-level literal names, defaults.env templates) | offline | free | P1 | covered | offline | `O-VAL-OK`, `tests/cli/test_smoke.py::test_check_token_permissions`, `tests/offline/test_config_credentials.py::test_env_defaults_templates_resolve_placeholders`, `tests/offline/test_config_credentials.py::test_env_organization_keys_are_literal`, `tests/offline/test_config_credentials.py::test_env_resolves_the_four_keys_without_no_web_ui` |
| `config.credentials.other-providers` | plain, pass, bitwarden and vault providers; 'no credential provider configured' / "unsupported credential provider '&lt;x&gt;'" | offline | free | P2 | **partial** | offline | `tests/offline/test_config_credentials.py::test_plain_and_default_providers`, `tests/offline/test_config_credentials.py::test_pass_provider_with_a_stub_store`, `tests/offline/test_config_credentials.py::test_pass_store_dir_from_the_defaults_override`, `tests/offline/test_config_credentials.py::test_bitwarden_provider_with_a_stub_vault` |
| `config.credentials.inmemory` | inmemory provider: the webapp runs every operation with the installation token (only_token) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_pr_validation.py::test_valid_config_pr` |
| `config.secret-references` | secret values: 'pass:', 'bitwarden:', 'vault:' references resolved at apply; other values used literally with a validation warning; '\*\*\*\*\*\*\*\*' = dummy | cli | free | P1 | **partial** | offline | `cli.secrets`, `O-VAL-OK`, `O-VAL-SECRETS`, `cli.org.secret` |
| `config.http-cache` | otterdog's HTTP cache (.cache/async_http relative to the cwd, always revalidated) must not hide out-of-band changes | cli | free | P1 | covered | **unverified** | `tests/cli/test_org_config.py::test_http_cache_does_not_hide_out_of_band_changes` |

Details:

- **`config.discovery`** (covered, P1, `offline`): config discovery: -c FILE, else $OTTERDOG_CONFIG_ROOT or the cwd; otterdog.jsonnet wins over otterdog.json; none -&gt; exit 2
    - Source: `otterdog/cli.py:27-50`, `otterdog/config.py:364-382`
    - Operations: config, error
    - Notes: OTTERDOG_CONFIG_ROOT: otterdog.json used, otterdog.jsonnet wins when both exist (project header and list-projects); empty cwd: exit 2 'No configuration file specified ...'; -c of a missing file: click usage error
- **`config.jsonnet-config-file`** (covered, P2, `offline`): otterdog.jsonnet configuration files are evaluated (#542); malformed JSON fails with "failed to parse json file '&lt;f&gt;'"
    - Source: `otterdog/config.py:35-47`, `CHANGELOG.md:167`
    - Operations: config, error
    - Notes: Also 'expected JSON object in file' and a jsonnet evaluation error of otterdog.jsonnet (exit 2)
- **`config.local-defaults-override`** (covered, P1, `offline`): .otterdog-defaults.json next to the config file is deep-merged over `defaults` (its values win, #725)
    - Source: `otterdog/config.py:374-382`, `otterdog/utils.py:663-672`, `CHANGELOG.md:76`
    - Operations: config
    - Notes: config_dir override wins over otterdog.json; #725 pass.password_store_dir from the override reaches the pass provider
- **`config.organization-entries`** (partial, P2, `offline`): organizations[]: name and github_id required, per-org config_repo/base_template/credentials, approval_teams/admin_teams as string or list
    - Source: `otterdog/config.py:114-164`, `otterdog/config.py:277-282`, `otterdog/config.py:293-294`
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
    - Source: `otterdog/config.py:278`, `CHANGELOG.md:196`
    - Operations: config
    - Notes: Archived entries are not even parsed (one without github_id loads)
- **`config.config-dir-layout`** (covered, P1, `offline`): working layout: &lt;config_dir|orgs&gt;/&lt;github_id&gt;/&lt;github_id&gt;.jsonnet, vendor/&lt;template repo&gt;/, import 'vendor/&lt;repo&gt;/&lt;file&gt;'
    - Source: `otterdog/config.py:269-275`, `otterdog/jsonnet.py:321-370`
    - Operations: config
    - Notes: the harness renders exactly this layout (offline: vendor/template/otterdog-defaults.libsonnet; live: the upstream template path)
- **`config.exclude-teams`** (covered, P2, `cli`): defaults.github.exclude_teams (regexes): matching teams are not loaded (import, plan) and configuring one is a validation error
    - Source: `otterdog/config.py:297-306`, `otterdog/models/github_organization.py:636-642`, `otterdog/models/team.py:66-75`
    - Operations: config, import, validate
    - Notes: exclude_teams from .otterdog-defaults.json of a test workspace: an out-of-band run team is not planned for removal (control plan without the pattern removes it), not imported, and declaring a matching team is a validation error with the exact message.
- **`config.template-url`** (covered, P1, `offline`): base_template URL `https://github.com/<owner>/<repo>#<file>@<ref>`: only github.com, ref mandatory (exit 2 at load)
    - Source: `otterdog/utils.py:490-517`, `otterdog/jsonnet.py:51-68`
    - Operations: config, error
    - Notes: Also 'failed to parse file from template url' (no fragment)
- **`config.template-clone`** (partial, P1, `cli`): non-local runs clone the template (unauthenticated) into &lt;config_dir&gt;/templates/&lt;owner&gt;/&lt;repo&gt;/&lt;ref&gt;, pull branch refs, never refresh tags/SHAs, copy into vendor/
    - Source: `otterdog/jsonnet.py:372-426`
    - Operations: config
    - Notes: live commands clone the template pinned to a commit sha (sut/template.py); the branch pull and the subdirectory copy rules are not asserted
    - Suggested: `cli.template.branch-ref` in `tests/cli/test_template.py`
    - Steps:
        - publish the template to the defaults repository on a branch e2e/&lt;run&gt;/tpl; validate with base_template ...@e2e/&lt;run&gt;/tpl
        - push a change to the branch template (a new default topic); validate/plan again
    - Assert:
        - the second run sees the change (git pull of branch refs); with a tag ref the cached clone is not refreshed
    - Needs:
        - target
        - TemplatePublisher on a branch (today only immutable tags)
- **`config.template-feature-gating`** (partial, P2, `cli`): the template drives what is managed: missing constructors skip a resource type, only template org-settings keys are fetched, hidden '::' fields are unmanaged
    - Source: `otterdog/jsonnet.py:120-318`, `otterdog/models/github_organization.py:579-610`, `otterdog/models/github_organization.py:615-871`
    - Operations: coerce, config
    - Notes: the harness hides max_cache_size_gb with '::' when the cache limit is unavailable and the baseline still converges; a template without constructors is never used. hidden-field part covered: has_wiki:: false is never sent nor diffed, a later plain ':' keeps it hidden, ':::' manages it again.
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
    - Source: `otterdog/models/__init__.py:79-85`, `otterdog/models/__init__.py:430-435`, `otterdog/models/organization_settings.py:104-106`
    - Operations: validate
    - Notes: O-TEMPLATE-HOOK-VALIDATE: the SUT template vendored with a validate-org-settings.py requiring default_repository_permission 'none' (sut.template.vendor_template(hooks=...)): the template default 'read' is the error "settings has 'default_repository_permission' set to 'read' but 'none' is required." (validate exit 1, local-plan 'Planning aborted due to validation errors.'), 'none' validates; without the hook file the same configuration validates. Eclipse's otterdog-defaults depends on it; the webapp validation runs it too.
- **`config.hook.validate-team`** (gap, P1, `cli`): template hook validate-team.py (per team at validation)
    - Source: `otterdog/models/team.py:62-64`, `otterdog/models/__init__.py:79-85`
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
    - Source: `otterdog/operations/apply.py:61-68`
    - Operations: add, run
    - Notes: O-TEMPLATE-HOOK-PRE-ADD: a pre-add-object-hook.py printing the added object runs once per addition (an org variable and a repository, not the changed repository) while local-apply prints its plan, before the prompt (answered 'n'); local-plan never runs it.
- **`config.hook.post-add-objects`** (gap, P1, `cli`): template hook post-add-objects-hook.py: runs once after an apply that added objects (CLI apply/local-apply and the webapp apply comment)
    - Source: `otterdog/operations/apply.py:166-190`
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
    - Source: `otterdog/jsonnet.py:407-426`, `otterdog/models/__init__.py:430-435`
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
    - Source: `otterdog/credentials/env_provider.py:29-124`, `otterdog/config.py:212-228`
    - Operations: config, error
    - Notes: defaults.env templates ({github_id}, {org_name} with ' '/'-' -&gt; '_'), org-level literal names win, braces refused, unset variable named; local-apply without -n resolves all four keys
- **`config.credentials.other-providers`** (partial, P2, `offline`): plain, pass, bitwarden and vault providers; 'no credential provider configured' / "unsupported credential provider '&lt;x&gt;'"
    - Source: `otterdog/credentials/__init__.py:101-155`, `otterdog/credentials/plain_provider.py:24-58`, `otterdog/credentials/pass_provider.py:29-136`, `otterdog/credentials/bitwarden_provider.py:25-120`, `otterdog/credentials/vault_provider.py:37-305`
    - Operations: config, error
    - Notes: plain, default provider, unexpected defaults keys, 'unsupported credential provider', 'no credential provider configured', pass (stub CLI) and bitwarden (stub CLI) covered on host runtimes.
    - Suggested: `O-CREDENTIALS-PROVIDERS` in `tests/offline/test_config_credentials.py`
    - Steps:
        - provider vault with defaults.vault {vault_addr: &lt;mock&gt;, vault_token: e2e-dummy, mount_point: e2e} and a Vault KV mock answering &lt;github_id&gt;/github.com/api-token
    - Assert:
        - the token is read from the mock (Validation succeeded); an unauthenticated mock gives 'Failed to authenticate with Vault. Please check your credentials and address' (exit 1)
    - Needs:
        - offline
        - harness: a Vault KV mock reachable from the offline sandbox (unshare -rn has no loopback, --network none containers neither)
- **`config.secret-references`** (partial, P1, `cli`): secret values: 'pass:', 'bitwarden:', 'vault:' references resolved at apply; other values used literally with a validation warning; '\*\*\*\*\*\*\*\*' = dummy
    - Source: `otterdog/config.py:230-244`, `otterdog/models/secret.py:45-61`, `otterdog/models/webhook.py:83-95`
    - Operations: validate, security
    - Known bugs: KB-025, KB-026, KB-057
    - Notes: offline (O-VAL-SECRETS): a 'pass:' reference validates silently, an unknown provider prefix 'foo:e2e/b' warns, several ':' crash (KB-025); live (cli.org.secret): 'pass:' validates silently (validate-only step), 'foo:e2e/...' warns and is applied literally, '\*\*\*\*\*\*\*\*' is skipped; webhook secrets with an unknown prefix do not warn (KB-057). Not covered: the resolution of references at apply time (pass, bitwarden, vault).
    - Suggested: `O-SECRET-RESOLUTION` in `tests/offline/test_config_credentials.py`
    - Steps:
        - BASE with org secret &lt;P&gt;_A 'pass:e2e/a', head with 'pass:e2e/b'; a stub 'pass' CLI on PATH logging the requested path (as test_pass_provider_with_a_stub_store)
        - local-apply --local -n answering 'n' (secrets are resolved before the prompt), then the same with 'bitwarden:' and an unknown 'foo:' prefix
    - Assert:
        - the stub was asked for e2e/b exactly once and the value never appears in the output; 'foo:' is not resolved (literal) and warns at validation
    - Needs:
        - offline
        - available: OtterdogCli.invoke(..., env={'PATH': '&lt;stub dir&gt;:&lt;system PATH&gt;'})
- **`config.http-cache`** (covered, P1, `cli`): otterdog's HTTP cache (.cache/async_http relative to the cwd, always revalidated) must not hide out-of-band changes
    - Source: `otterdog/cli.py:979`, `otterdog/providers/github/cache/file.py:20-46`
    - Operations: converge
    - Notes: warm shared cache (cache dir non-empty), out-of-band description change, the next plans (within GitHub's max-age of 60 s) show the change.

<a id="validation"></a>

## Validation rules

`validation`: 36 features, 36 covered, 0 partial, 0 gaps (weighted 100%).

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
| `validation.org-rulesets` | org ruleset rules: include/exclude_repo_names patterns must match a repository (warning), protect_repo_names needs names (warning), nested validators | offline | enterprise | P2 | covered | offline | `enterprise.kb.org-ruleset-repo-patterns`, `O-VAL-ORG-RULESET-STRICT`, `enterprise.org-ruleset.missing-strict`, `O-VAL-ORG-RULESETS` |
| `validation.teams` | team rules: privacy secret\|visible (message says 'closed'), skip_members with members, skip_non_organization_members with a non-member, exclusion pattern | cli | free | P1 | covered | **unverified** | `cli.validate.teams`, `cli.validate.team-non-member`, `cli.kb.team-privacy-message`, `tests/cli/test_org_config.py::test_excluded_teams_are_neither_loaded_nor_configurable` |
| `validation.webhooks` | webhook rules: content_type json\|form, insecure_ssl '0'\|'1', dummy secret info, secret without provider warning (value echoed) | offline | free | P1 | covered | offline | `O-VAL-WEBHOOKS` |
| `validation.secrets` | secret rules (org, repo, env): GITHUB_ prefix error, dummy '\*\*\*\*\*\*\*\*' info, value without provider warning; two ':' crash | offline | free | P1 | covered | offline | `cli.secrets`, `O-VAL-OK`, `O-VAL-SECRETS` |
| `validation.org-secrets` | org secret rules: visibility public\|private\|selected; selected_repositories ignored unless 'selected' (warning) | offline | free | P2 | covered | offline | `O-VAL-ORG-SECRETS`, `O-VAL-ORGSECRET-PRIVATE-FREE` |
| `validation.variables` | repository and environment variable rules: names upper case, no GITHUB_ prefix | offline | free | P1 | covered | offline | `O-VAL-VARIABLES` |
| `validation.repo.description-topics` | repository description &lt;= 350 chars, at most 20 topics, topics only [a-z0-9-] | offline | free | P1 | covered | offline | `tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors`, `O-VAL-REPO` |
| `validation.repo.forking` | public repo with allow_forking false: warning; private repo with allow_forking while the org disables private forks: error | offline | free | P1 | covered | offline | `O-VAL-REPO` |
| `validation.repo.secret-scanning` | secret_scanning 'disabled' with push protection 'enabled' on a non-archived repository is an error | offline | free | P2 | covered | offline | `O-VAL-REPO` |
| `validation.repo.template-fork` | template_repository and forked_repository are exclusive; forked_repository must be '&lt;owner&gt;/&lt;repo&gt;' ('the the' typo) | offline | free | P2 | covered | offline | `O-VAL-REPO` |
| `validation.repo.custom-properties` | a repository value for an undefined custom property is an error ("defines an unknown custom property with key '&lt;k&gt;'.") | offline | free | P2 | covered | offline | `O-VAL-REPO` |
| `validation.repo.team-permissions` | invalid team_permissions values (model check unreachable: the schema enum fails first, exit 2) | offline | free | P2 | covered | offline | `O-VAL-SCHEMA` |
| `validation.repo.merge-commit-settings` | squash/merge commit title and message enums and allowed combinations | offline | free | P1 | covered | offline | `O-VAL-MERGE-SETTINGS` |
| `validation.repo.pages` | GitHub Pages rules: build type disabled\|legacy\|workflow, legacy source path '/'\|'/docs', github-pages environment info, org site must not be disabled, visibility public\|private rules | offline | free | P1 | covered | offline | `O-VAL-PAGES`, `O-VAL-PAGES-ENTERPRISE`, `O-VAL-COERCED` |
| `validation.repo.code-scanning` | code scanning rules: query suite default\|extended, languages enum, languages need an existing repository (#767) that contains them | cli | free | P2 | covered | offline | `regression.code-scanning-new-repo`, `O-VAL-REPO`, `tests/cli/test_org_validation.py::test_code_scanning_languages_must_be_detected` |
| `validation.repo.archived-bpr` | an archived repository with branch protection rules: Info 'is archived but has branch_protection_rules which will be ignored.' | offline | free | P2 | covered | offline | `O-VAL-INFOS` |
| `validation.repo.coerced-rules` | documented repository checks made unreachable by load-time coercion (has_projects, web_commit_signoff_required, has_discussions source, private gh_pages below enterprise) | offline | free | P2 | covered | offline | `O-VAL-COERCED` |
| `validation.repo-workflows` | repository Actions infos (ignored because the org restricts: none, selected, more restricted actions, read permissions, no approvals) and code scanning with Actions disabled | offline | free | P2 | covered | offline | `O-VAL-REPO-WORKFLOWS` |
| `validation.bpr` | branch protection rules: review count required with PRs, dependent settings ignored when their toggle is off (infos/warnings), deployment environments must exist | offline | free | P1 | covered | offline | `O-VAL-BPR` |
| `validation.rulesets` | ruleset rules: target branch\|tag\|push, enforcement active\|disabled\|evaluate, ref patterns per target, deployment environments, nested settings | offline | free | P1 | covered | offline | `O-VAL-RULESETS` |
| `validation.ruleset-nested` | ruleset nested settings: status checks need strict and status_checks (#790), PR review count 0..10, merge queue method MERGE\|SQUASH\|REBASE and non-negative numbers | offline | free | P1 | covered | offline | `O-VAL-RULESET-STRICT`, `regression.repo-ruleset-without-strict`, `O-VAL-RULESET-NESTED` |
| `validation.environments` | environment rules: wait_timer 0..43200, deployment_branch_policy all\|protected\|selected, branch_policies ignored unless 'selected', prevent_self_review without reviewers | offline | free | P1 | covered | offline | `O-VAL-ENVIRONMENTS` |
| `validation.schema.unknown-properties` | unknown keys: additionalProperties objects (org, settings, repository, team, webhook, environment, BPR, custom property) only log 'ignoring unknown properties found while validating organization config: ...'; unevaluatedProperties objects (secrets, variables, rulesets, roles, workflows) are blocking (exit 2) | offline | free | P1 | covered | offline | `O-VAL-SCHEMA` |
| `validation.schema.type-errors` | schema type/enum/required violations raise an uncaught jsonschema error (exit 2): wrong types, secrets without value, values_editable_by, multi_select under a '_' property name | offline | free | P2 | covered | offline | `cli.kb.custom-property-underscore`, `O-VAL-SCHEMA` |
| `validation.jsonnet-load` | jsonnet evaluation errors: 'Validation failed' / 'failed to load configuration: failed to evaluate jsonnet file: ...' (exit 1) | offline | free | P0 | covered | offline | `O-VAL-SYNTAX` |

Details:

- **`validation.plan-gate.org-rulesets`** (covered, P0, `offline`): organization rulesets need settings.plan 'enterprise' ("use of organization rulesets requires an 'enterprise' plan, ...")
    - Source: `otterdog/models/github_organization.py:219-227`
    - Operations: validate
    - Known bugs: KB-009
    - Notes: O-VAL-PLAN-GATES-TEAM step org-rulesets-on-team reproduces KB-009 offline (team plan refused, expected to validate).
- **`validation.plan-gate.org-secret-private`** (covered, P0, `offline`): org secret visibility 'private' on a free plan is an error ("... which is not available for an organization with free plan.")
    - Source: `otterdog/models/organization_secret.py:43-50`
    - Operations: validate
    - Notes: verified offline: plan 'team' accepts 'private'. private org secret accepted and planned on team and enterprise.
- **`validation.plan-gate.org-variable-private`** (covered, P1, `offline`): org variable visibility 'private' on a free plan should be an error like org secrets (it is never checked)
    - Source: `otterdog/models/organization_variable.py:43-50`, `otterdog/models/github_organization.py:196-264`
    - Operations: validate
    - Known bugs: KB-028
    - New findings: F-01
    - Notes: step invalid-variables expects the 4 errors (private on free, lowercase, GITHUB_, unknown visibility) + the selected_repositories warning (KB-028 step-level expected failure); valid-variables strict (validate + local-plan 3 adds).
- **`validation.plan-gate.org-roles`** (covered, P0, `offline`): organization roles need settings.plan 'enterprise' ("use of organization roles requires an 'enterprise' plan, while this organization is currently on a '&lt;plan&gt;' plan.")
    - Source: `otterdog/models/github_organization.py:198-208`
    - Operations: validate
    - Notes: free: exact error, exit 1, local-plan 'Planning aborted due to validation errors.'; team: message names 'team'; enterprise: validates and plans '+ add org_role'.
- **`validation.plan-gate.ruleset-evaluate`** (covered, P1, `offline`): ruleset enforcement 'evaluate' needs an enterprise plan ("... has 'enforcement' of value 'evaluate' which is only available for an 'enterprise' plan.")
    - Source: `otterdog/models/ruleset.py:374-388`
    - Operations: validate
    - Notes: refused on free and team (exact repo_ruleset header), planned with enforcement 'evaluate' on enterprise.
- **`validation.plan-gate.private-pages`** (covered, P1, `offline`): members_can_create_private_pages true needs an enterprise plan ("enabling 'members_can_create_private_pages' requires an 'enterprise' plan.")
    - Source: `otterdog/models/organization_settings.py:126-130`
    - Operations: validate
    - Known bugs: KB-024
    - Notes: refused on free and team, '\~ members_can_create_private_pages = false -&gt; true' planned on enterprise.
- **`validation.plan-gate.private-repo-wiki`** (covered, P1, `offline`): a private repository with has_wiki on a free plan is a warning ("... requires at least GitHub Team billing, currently using 'free' plan.")
    - Source: `otterdog/models/repository.py:428-434`
    - Operations: validate
    - Notes: every private-repository scenario sets has_wiki: false to avoid it. warning on free (exact), control without warning (public wiki, private has_wiki false); no warning on team/enterprise.
- **`validation.org-settings`** (covered, P1, `offline`): organization settings rules: description &lt;= 160 chars, has_discussions needs a source repository '&lt;owner&gt;/&lt;repo&gt;', default_repository_permission none|read|write|admin
    - Source: `otterdog/models/organization_settings.py:104-150`
    - Operations: validate
    - Notes: description 161 (validate + local-plan abort), discussions without source, source format (with and without discussions), default_repository_permission 'maintain', limits control.
- **`validation.org-workflows`** (covered, P1, `offline`): organization Actions rules: allowed_actions, default_workflow_permissions, fork_pr_approval_policy, enabled_repositories enums; ignored patterns/selection warnings
    - Source: `otterdog/models/workflow_settings.py:115-150`, `otterdog/models/organization_workflow_settings.py:51-69`
    - Operations: validate
    - Known bugs: KB-029, KB-038
    - New findings: F-02, F-11
    - Notes: every enum and both ignored-setting warnings; fork policy asserted order-free (KB-038); KB-029 step-level with a repository.
- **`validation.custom-properties`** (covered, P1, `offline`): custom property rules: value_type enum, select types need 1..200 allowed_values, required needs a default, default within allowed_values, single_select default not a list, values_editable_by
    - Source: `otterdog/models/custom_property.py:52-143`
    - Operations: validate
    - Known bugs: KB-030
    - New findings: F-03
    - Notes: 9 rules incl. non-empty list default and multi_select elements not allowed; limits control (200 values, every value type, both values_editable_by) planned; KB-030 step-level.
- **`validation.org-roles`** (covered, P2, `offline`): org role rules: base_role none|read|triage|write|maintain|admin; base_role 'none' with permissions is an error
    - Source: `otterdog/models/role.py:40-57`
    - Operations: validate
    - Notes: base_role enum, none+permissions, the 6 valid base roles validated and planned (6 adds).
- **`validation.org-rulesets`** (covered, P2, `offline`): org ruleset rules: include/exclude_repo_names patterns must match a repository (warning), protect_repo_names needs names (warning), nested validators
    - Source: `otterdog/models/organization_ruleset.py:44-82`
    - Operations: validate
    - Known bugs: KB-008, KB-023
    - Notes: verified offline with variables.plan enterprise: 'nomatch-\*' -&gt; "org_ruleset[name="ors"] has an 'include_repo_names' pattern 'nomatch-\*' that does not match any existing repository"; protect without names -&gt; "... has 'protect_repo_names' set to 'True' but 'include_repo_names' and 'exclude_repo_names' are empty."; required_pull_request count 11 or requires_deployments crash with AttributeError (get_model_header / environments), exit 2. include/exclude no-match and protect warnings, target/enforcement/ref-pattern errors with the org_ruleset header, valid control planned; KB-023 (second pattern) and KB-008 (review count 11, deployment rule: AttributeError 'environments') as step-level expected failures.
- **`validation.teams`** (covered, P1, `cli`): team rules: privacy secret|visible (message says 'closed'), skip_members with members, skip_non_organization_members with a non-member, exclusion pattern
    - Source: `otterdog/models/team.py:62-99`, `otterdog/models/github_organization.py:177-181`
    - Operations: validate
    - Known bugs: KB-037
    - New findings: F-10
    - Notes: validation lists the org members as soon as teams exist: no offline run (verified: 'Cannot connect to host api.github.com' exit 2). privacy 'closed' refused (stable prefix; the correct value list is the KB-037 step of cli.kb.team-privacy-message), skip_members with members, skip_non_organization_members with the outsider identity, exclusion pattern message.
- **`validation.webhooks`** (covered, P1, `offline`): webhook rules: content_type json|form, insecure_ssl '0'|'1', dummy secret info, secret without provider warning (value echoed)
    - Source: `otterdog/models/webhook.py:83-111`
    - Operations: validate
    - Known bugs: KB-026, KB-057
    - Notes: content_type/insecure_ssl errors (org+repo headers), provider warning asserted without the value, dummy Info with -v, pass: silent; KB-026 step-level (value must not be echoed).
- **`validation.secrets`** (covered, P1, `offline`): secret rules (org, repo, env): GITHUB_ prefix error, dummy '\*\*\*\*\*\*\*\*' info, value without provider warning; two ':' crash
    - Source: `otterdog/models/secret.py:45-67`, `otterdog/models/environment.py:145-146`, `otterdog/models/repository.py:708-709`
    - Operations: validate, security
    - Known bugs: KB-025, KB-026
    - Notes: verified offline: "repo_secret[name="GITHUB_R"] starts with prefix 'GITHUB_' which is not allowed for secrets."; "env_secret[name="E2E_ES"] has a value 'lit' that does not use a credential provider."; 'pass:a:b' -&gt; 'too many values to unpack (expected 2)' exit 2; lowercase secret names are accepted (GitHub upper-cases them). GITHUB_ prefix (org/repo/env), provider warnings (plain, foo:), pass: silent, dummy infos (-v, 3 levels), lowercase accepted; KB-025 and KB-026 step-level.
- **`validation.org-secrets`** (covered, P2, `offline`): org secret rules: visibility public|private|selected; selected_repositories ignored unless 'selected' (warning)
    - Source: `otterdog/models/organization_secret.py:40-64`
    - Operations: validate
    - Notes: visibility enum, selected_repositories ignored warning, 'selected' control planned.
- **`validation.variables`** (covered, P1, `offline`): repository and environment variable rules: names upper case, no GITHUB_ prefix
    - Source: `otterdog/models/variable.py:29-42`, `otterdog/models/repository.py:711-712`, `otterdog/models/environment.py:148-149`
    - Operations: validate
    - Notes: 4 errors (repo/env lowercase and GITHUB_) with exact headers; valid names planned (4 adds).
- **`validation.repo.description-topics`** (covered, P1, `offline`): repository description &lt;= 350 chars, at most 20 topics, topics only [a-z0-9-]
    - Source: `otterdog/models/repository.py:401-420`, `otterdog/models/repository.py:723-725`
    - Operations: validate
    - Notes: 351 chars, 21 topics, invalid topics; limits control (350 chars, 20 topics).
- **`validation.repo.forking`** (covered, P1, `offline`): public repo with allow_forking false: warning; private repo with allow_forking while the org disables private forks: error
    - Source: `otterdog/models/repository.py:422-426`, `otterdog/models/repository.py:453-458`
    - Operations: validate
    - Notes: the template defaults (allow_forking true, org members_can_fork_private_repositories false) make every private repo invalid unless allow_forking: false. public allow_forking false warning, private allow_forking error; control with members_can_fork_private_repositories true.
- **`validation.repo.secret-scanning`** (covered, P2, `offline`): secret_scanning 'disabled' with push protection 'enabled' on a non-archived repository is an error
    - Source: `otterdog/models/repository.py:467-474`
    - Operations: validate
    - Notes: error, archived and both-disabled controls.
- **`validation.repo.template-fork`** (covered, P2, `offline`): template_repository and forked_repository are exclusive; forked_repository must be '&lt;owner&gt;/&lt;repo&gt;' ('the the' typo)
    - Source: `otterdog/models/repository.py:476-480`, `otterdog/models/repository.py:620-629`
    - Operations: validate
    - Notes: exclusive error and 'the the' format error; valid forked_repository control.
- **`validation.repo.custom-properties`** (covered, P2, `offline`): a repository value for an undefined custom property is an error ("defines an unknown custom property with key '&lt;k&gt;'.")
    - Source: `otterdog/models/repository.py:482-489`
    - Operations: validate
    - Notes: unknown key error; defined property value control.
- **`validation.repo.team-permissions`** (covered, P2, `offline`): invalid team_permissions values (model check unreachable: the schema enum fails first, exit 2)
    - Source: `otterdog/models/repository.py:491-499`, `otterdog/resources/schemas/team-permission.json:1-11`
    - Operations: validate
    - Known bugs: KB-032
    - New findings: F-05
    - Notes: KB-032 step-level: 'super' expects the model error (exit 1), 'WRITE' expects success; every lowercase value validates and is planned (strict).
- **`validation.repo.merge-commit-settings`** (covered, P1, `offline`): squash/merge commit title and message enums and allowed combinations
    - Source: `otterdog/models/repository.py:631-703`
    - Operations: validate
    - Known bugs: KB-034
    - New findings: F-07
    - Notes: both pair errors (exit 1), 4 single-value cases (2 errors each), all 7 valid combinations planned; KB-034 step-level (2 errors expected to exit 1).
- **`validation.repo.pages`** (covered, P1, `offline`): GitHub Pages rules: build type disabled|legacy|workflow, legacy source path '/'|'/docs', github-pages environment info, org site must not be disabled, visibility public|private rules
    - Source: `otterdog/models/repository.py:511-600`
    - Operations: validate
    - Notes: build type, legacy path, org site error, github-pages infos (-v, 3), valid sites planned; enterprise: visibility enum, private on public repo, org private pages disabled, valid + visibility change; below enterprise the visibility rules never fire (KB-033 step in O-VAL-COERCED).
- **`validation.repo.code-scanning`** (covered, P2, `cli`): code scanning rules: query suite default|extended, languages enum, languages need an existing repository (#767) that contains them
    - Source: `otterdog/models/repository.py:602-618`, `otterdog/models/repository.py:318-378`, `otterdog/models/github_organization.py:229-262`
    - Operations: validate
    - Known bugs: KB-034, KB-038
    - New findings: F-11
    - Notes: offline (O-VAL-REPO): the query suite enum ('full' refused) and the language enum ('cobol' refused, stable prefix only: set order, KB-038; every supported language validates), with the default setup disabled so that no language detection reads GitHub. Live (cli.validate.code-scanning-languages): once GitHub detected Python, 'go' is refused naming 'Detected languages: Python', python and actions validate, 'cobol' is refused by the enum (stable prefix only: set order, KB-038) and by the detection (2 errors, exit 2: KB-034); new repositories in regression.code-scanning-new-repo.
- **`validation.repo.archived-bpr`** (covered, P2, `offline`): an archived repository with branch protection rules: Info 'is archived but has branch_protection_rules which will be ignored.'
    - Source: `otterdog/models/repository.py:504-509`
    - Operations: validate, archive
    - Notes: Info hidden without -v (hint), printed with -v (validate and local-plan -v), the archived repository's rule is not planned.
- **`validation.repo.coerced-rules`** (covered, P2, `offline`): documented repository checks made unreachable by load-time coercion (has_projects, web_commit_signoff_required, has_discussions source, private gh_pages below enterprise)
    - Source: `otterdog/models/repository.py:436-465`, `otterdog/models/repository.py:284-316`, `otterdog/models/github_organization.py:349-351`
    - Operations: validate, coerce
    - Known bugs: KB-033
    - New findings: F-06
    - Notes: strict control: show --local prints the coerced repository without has_projects/gh_pages_visibility; the 4 documented messages (has_projects, signoff, discussion source, pages visibility below enterprise) as KB-033 step-level expected failures (flip automatically when fixed).
- **`validation.repo-workflows`** (covered, P2, `offline`): repository Actions infos (ignored because the org restricts: none, selected, more restricted actions, read permissions, no approvals) and code scanning with Actions disabled
    - Source: `otterdog/models/repo_workflow_settings.py:69-136`
    - Operations: validate, coerce
    - Notes: code scanning error (repo and org disabled), all 5 infos with -v, disabled-repo control (0 infos), enums with repo header (KB-038 order-free), patterns warning; KB-029 step-level for an invalid repo allowed_actions.
- **`validation.bpr`** (covered, P1, `offline`): branch protection rules: review count required with PRs, dependent settings ignored when their toggle is off (infos/warnings), deployment environments must exist
    - Source: `otterdog/models/branch_protection_rule.py:88-229`
    - Operations: validate
    - Notes: review count null/-1, 6 PR-dependent warnings + count info, deployment env error + ignored warning, push/lock warnings, 3 ignored-allowance infos, every-toggle-on control planned (3 adds).
- **`validation.rulesets`** (covered, P1, `offline`): ruleset rules: target branch|tag|push, enforcement active|disabled|evaluate, ref patterns per target, deployment environments, nested settings
    - Source: `otterdog/models/ruleset.py:363-458`
    - Operations: validate
    - Known bugs: KB-039
    - New findings: F-12
    - Notes: target/enforcement, branch/push/tag ref patterns, deployments error+warning, valid rulesets of every target with bypass actors planned; KB-039 step-level ('#Admin' expected to be refused).
- **`validation.ruleset-nested`** (covered, P1, `offline`): ruleset nested settings: status checks need strict and status_checks (#790), PR review count 0..10, merge queue method MERGE|SQUASH|REBASE and non-negative numbers
    - Source: `otterdog/models/ruleset.py:57-74`, `otterdog/models/ruleset.py:128-136`, `otterdog/models/ruleset.py:240-271`
    - Operations: validate
    - Known bugs: KB-031, KB-055
    - New findings: F-04
    - Notes: review count 11/-1, merge queue FAST/-1/-5, valid limits planned; messages asserted after the header (they name the repository twice: KB-055); KB-031 step-level for missing PR and merge-queue keys.
- **`validation.environments`** (covered, P1, `offline`): environment rules: wait_timer 0..43200, deployment_branch_policy all|protected|selected, branch_policies ignored unless 'selected', prevent_self_review without reviewers
    - Source: `otterdog/models/environment.py:111-149`
    - Operations: validate
    - Known bugs: KB-036
    - New findings: F-09
    - Notes: wait_timer 43201/-1, 'protected_branches' (KB-036 template comment value) refused, 3 ignored-setting warnings, limits planned.
- **`validation.schema.unknown-properties`** (covered, P1, `offline`): unknown keys: additionalProperties objects (org, settings, repository, team, webhook, environment, BPR, custom property) only log 'ignoring unknown properties found while validating organization config: ...'; unevaluatedProperties objects (secrets, variables, rulesets, roles, workflows) are blocking (exit 2)
    - Source: `otterdog/models/github_organization.py:266-296`, `otterdog/resources/schemas/repository.json:99`, `otterdog/resources/schemas/repo-secret.json:7`, `otterdog/resources/schemas/org-workflow-settings.json:15`
    - Operations: validate, error
    - Notes: 6 additionalProperties objects only warn (validate + local-plan, unknown keys not planned); unevaluatedProperties blocking for repo secret, org variable, ruleset, role, org and repo workflows (exit 2, no summary).
- **`validation.schema.type-errors`** (covered, P2, `offline`): schema type/enum/required violations raise an uncaught jsonschema error (exit 2): wrong types, secrets without value, values_editable_by, multi_select under a '_' property name
    - Source: `otterdog/models/github_organization.py:285-296`, `otterdog/resources/schemas/types.json:32-41`, `otterdog/resources/schemas/custom-property.json:15-20`
    - Operations: validate, error
    - Known bugs: KB-016
    - Notes: verified offline: has_wiki 123 -&gt; "123 is not of type 'boolean'"; a secret without value -&gt; "None is not of type 'string'"; values_editable_by 'anyone' -&gt; 'is not valid under any of the given schemas'; {'e2e_multi': ['a', 'b']} fails while 'e2emulti' passes (KB-016). has_wiki 123 (validate + local-plan), secret without value, values_editable_by 'anyone' (the model message is unreachable like KB-032), KB-016 offline counterpart step-level + control without '_'.
- **`validation.jsonnet-load`** (covered, P0, `offline`): jsonnet evaluation errors: 'Validation failed' / 'failed to load configuration: failed to evaluate jsonnet file: ...' (exit 1)
    - Source: `otterdog/operations/validate.py:64-68`, `otterdog/utils.py:444-452`
    - Operations: validate, error
    - Known bugs: KB-035
    - New findings: F-08
    - Notes: an unknown template function (orgs.newEnvironmentSecret of the docs) fails the same way ('no such field: newEnvironmentSecret')

<a id="plan-semantics"></a>

## Diff engine and plan semantics

`plan-semantics`: 18 features, 16 covered, 2 partial, 0 gaps (weighted 94%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `plan-semantics.add-block` | a new object is one '+ add &lt;header&gt; {' block of its non-null diff fields; each object nested in a new repository is its own block and counts as an addition | offline | free | P0 | covered | offline | `O-LPLAN-ADD`, `cli.repo.lifecycle`, `cli.bpr.public`, `cli.repo.webhook`, `O-LPLAN-RESOURCE-TYPES` |
| `plan-semantics.change-block` | a changed object is one '\~ &lt;header&gt; {' block of 'key = old -&gt; new' lines; 'Plan: ... C to change' counts changed attributes, not objects; unchanged objects are not printed | offline | free | P0 | covered | offline | `O-LPLAN-CHANGE`, `cli.repo.lifecycle`, `cli.team`, `O-LPLAN-RESOURCE-TYPES` |
| `plan-semantics.remove-block` | a removed object is one '- remove &lt;header&gt; {' block; a removed repository (or environment) is ONE block, its nested objects are neither listed nor counted | offline | free | P0 | covered | offline | `O-LPLAN-REMOVE`, `cli.repo.lifecycle`, `cli.bpr.public`, `O-LPLAN-RESOURCE-TYPES` |
| `plan-semantics.converge` | convergence: a plan right after an apply is a no-op (the live read-back maps onto the configuration for every managed field) | cli | free | P0 | covered | **unverified** | `cli.repo.lifecycle`, `cli.team`, `cli.bpr.public`, `cli.ruleset.public`, `cli.environment`, `cli.custom-property`, `cli.repo.webhook`, `cli.secrets`, `tests/cli/test_import.py::test_import_plans_no_change` |
| `plan-semantics.rename-aliases` | repository rename through aliases: one change including '\~ name = "old" -&gt; "new"' instead of remove + add (data kept) | offline | free | P1 | covered | offline | `regression.rename-and-modify`, `O-LPLAN-RENAME` |
| `plan-semantics.dict-one-way` | dict fields (team_permissions, repository custom_properties) diff one way: removing an entry alone is invisible; together with another change of the same dict the removed key is printed ('- b = "pull"') and sent (custom properties as null) | offline | free | P1 | **partial** | offline | `cli.kb.team-permissions-removal`, `O-LPLAN-DICT-ONE-WAY` |
| `plan-semantics.wildcard-keys` | a key ending with '\*' (e.g. a webhook url hiding a token, #84) matches the live object whose key starts with the prefix: no remove + add, the live key is kept | offline | free | P1 | **partial** | offline | `O-LPLAN-WILDCARD`, `tests/webapp/test_merge_apply.py::test_team_and_wildcard_webhook_are_applied` |
| `plan-semantics.coerce.org-signoff` | org web_commit_signoff_required true makes the repository field unmanaged; turning the org setting off re-applies the repository value on every non-archived repository ('\~ web_commit_signoff_required = true -&gt; true') | offline | free | P0 | covered | offline | `O-LPLAN-COERCE-SIGNOFF`, `cli.org.signoff` |
| `plan-semantics.coerce.org-projects-pages` | org has_organization_projects false makes repository has_projects unmanaged; gh_pages_visibility is unmanaged below an enterprise plan | offline | free | P1 | covered | offline | `O-LPLAN-COERCE-SIGNOFF`, `O-VAL-PAGES-ENTERPRISE`, `O-VAL-COERCED` |
| `plan-semantics.coerce.discussion-source` | the repository named by the org discussion_source_repository always gets has_discussions true; the org field is ignored while has_discussions is false | offline | free | P2 | covered | offline | `O-LPLAN-COERCE-SIGNOFF` |
| `plan-semantics.coerce.required-custom-properties` | repositories without a value for a required custom property get its default_value; a value equal to the default is dropped from patches | offline | free | P2 | covered | offline | `O-LPLAN-CUSTOM-PROPERTY-DEFAULTS`, `cli.custom-property.required` |
| `plan-semantics.ignored-fields` | fields excluded from diffs by other settings: private repos (secret scanning, push protection, dependabot security updates, PVR), pages disabled (source branch/path, visibility) or 'workflow' (source branch/path), code scanning setup disabled (suite, languages), fork_default_branch_only without forked_repository | offline | free | P1 | covered | offline | `regression.private-repo-template-defaults`, `O-LPLAN-IGNORED-FIELDS` |
| `plan-semantics.ignored-org-actions` | Actions fields ignored by diffs: allow_github_owned/verified_creator/action_patterns unless allowed_actions 'selected'; org selected_repositories unless enabled_repositories 'selected'; every org Actions field but enabled_repositories when it is 'none' | offline | free | P1 | covered | offline | `O-LPLAN-IGNORED-FIELDS` |
| `plan-semantics.ignored-archived` | archived repositories: fields GitHub cannot change on archived repos are not diffed while archived stays true; archiving with other changes shows both, applies the other changes first and archives last; BPRs and rulesets of archived repos are skipped | offline | free | P0 | covered | offline | `O-LPLAN-ARCHIVED` |
| `plan-semantics.bpr-dependents-ignored` | branch protection settings depending on a disabled toggle (review settings without requires_pull_request, status checks without requires_status_checks, ...) are ignored by diffs (validation reports them) | offline | free | P1 | covered | offline | `O-LPLAN-BPR-DEPENDENTS` |
| `plan-semantics.env-branch-policies-ignored` | environment branch_policies are ignored unless deployment_branch_policy is 'selected' (warning, no diff) | offline | free | P1 | covered | offline | `O-LPLAN-ENV-POLICIES` |
| `plan-semantics.code-security-disable-only` | default_code_security_configurations_disabled can only disable: true -&gt; false is dropped from the plan | offline | free | P2 | covered | offline | `O-LPLAN-COERCE-SIGNOFF` |
| `plan-semantics.patch-order` | patches are generated and applied in a fixed order: roles, teams, settings (and custom properties), org webhooks, org secrets, org variables, org rulesets, repositories with their nested objects | cli | free | P1 | covered | **unverified** | `cli.kb.org-variable-same-apply`, `cli.team`, `cli.kb.org-secret-same-apply`, `cli.org.security-managers` |

Details:

- **`plan-semantics.add-block`** (covered, P0, `offline`): a new object is one '+ add &lt;header&gt; {' block of its non-null diff fields; each object nested in a new repository is its own block and counts as an addition
    - Source: `otterdog/operations/plan.py:60-73`, `otterdog/operations/diff_operation.py:180-200`, `otterdog/models/repository.py:1229-1230`
    - Operations: add, plan
    - Notes: adds org roles, org rulesets, env secrets/variables.
- **`plan-semantics.change-block`** (covered, P0, `offline`): a changed object is one '\~ &lt;header&gt; {' block of 'key = old -&gt; new' lines; 'Plan: ... C to change' counts changed attributes, not objects; unchanged objects are not printed
    - Source: `otterdog/operations/plan.py:90-119`, `otterdog/models/__init__.py:437-475`
    - Operations: modify, plan
    - Known bugs: KB-063
    - Notes: changes settings, Actions, custom property, role, org ruleset, org secret, org webhook, repo ruleset, env secret/variable (counts per changed key).
- **`plan-semantics.remove-block`** (covered, P0, `offline`): a removed object is one '- remove &lt;header&gt; {' block; a removed repository (or environment) is ONE block, its nested objects are neither listed nor counted
    - Source: `otterdog/operations/plan.py:75-88`, `otterdog/models/repository.py:1212-1215`, `otterdog/models/__init__.py:826-842`
    - Operations: remove, plan
    - Notes: verified offline: removing a repository's only environment (with an env variable) prints one '- remove environment[name="e", repository=r1]' block, 'Plan: 0 to add, 0 to change, 1 to delete.'. removes custom property, role, org ruleset, org secret, repo secret, repo ruleset, BPR, env secret/variable; a removed environment is ONE block.
- **`plan-semantics.converge`** (covered, P0, `cli`): convergence: a plan right after an apply is a no-op (the live read-back maps onto the configuration for every managed field)
    - Source: `otterdog/models/__init__.py:437-475`, `otterdog/models/github_organization.py:560-956`
    - Operations: converge, plan
    - Known bugs: KB-003, KB-020, KB-021
    - Notes: the scenario engine re-plans after every applied step (converge loop); KB-003/KB-020/KB-021 are the known non-converging cases (xfail scenarios)
- **`plan-semantics.rename-aliases`** (covered, P1, `offline`): repository rename through aliases: one change including '\~ name = "old" -&gt; "new"' instead of remove + add (data kept)
    - Source: `otterdog/models/repository.py:220-224`, `otterdog/models/__init__.py:822-850`, `otterdog/models/repository.py:1473-1546`
    - Operations: rename, plan, modify
    - Known bugs: KB-004
    - Notes: verified offline: base newRepo('old') {description: 'a'}, config newRepo('new') {aliases: ['old'], description: 'b'} -&gt; '\~ repository[name="new"]' with '\~ description = "a" -&gt; "b"' and '\~ name = "old" -&gt; "new"', 'Plan: 0 to add, 2 to change, 0 to delete.'; without the alias: '- remove repository[name="old"]' + '+ add repository[name="new"]' (1 to add, 1 to delete). alias with changes (name line + nested object under the new name, 0/3/0), alias only (0/1/0), no alias (1/0/1), dangling alias (plain add), webhook alias association; KB-004 step-level (url change expected).
- **`plan-semantics.dict-one-way`** (partial, P1, `offline`): dict fields (team_permissions, repository custom_properties) diff one way: removing an entry alone is invisible; together with another change of the same dict the removed key is printed ('- b = "pull"') and sent (custom properties as null)
    - Source: `otterdog/utils.py:105-124`, `otterdog/models/__init__.py:437-475`, `otterdog/models/repository.py:1247-1257`
    - Operations: remove, modify, plan
    - Known bugs: KB-005
    - Notes: verified offline: team_permissions {a: 'push', b: 'pull'} -&gt; {a: 'push'}: 'Plan: 0 to add, 0 to change, 0 to delete.'; -&gt; {a: 'maintain'}: '\~ team_permissions = {', '\~ a = "push" -&gt; "maintain"', '- b = "pull"', 1 to change; custom_properties {p1: 'x', p2: 'y'} -&gt; {p1: 'x'}: no change. offline complete: removal-only (KB-005 step-level, team_permissions and custom_properties), removal with change, addition.
    - Suggested: `cli.kb.custom-property-value-removal` in `scenarios/cli/custom-properties/kb-custom-property-value-removal.yaml`
    - Steps:
        - org_level: a string custom property {{ p }}-p and a run repository with custom_properties {'{{ p }}-p': 'x'}; apply
        - the same configuration without the repository value (the definition stays)
    - Assert:
        - plan expects changes on '\~ repository[name="{{ p }}-r"]' (today: noop, KB-005 at scenario level) and the oracle repo_custom_properties loses the key after the apply
    - Needs:
        - target
        - org_level (custom property definitions)
        - requires: [custom_properties]
- **`plan-semantics.wildcard-keys`** (partial, P1, `offline`): a key ending with '\*' (e.g. a webhook url hiding a token, #84) matches the live object whose key starts with the prefix: no remove + add, the live key is kept
    - Source: `otterdog/models/__init__.py:822-837`, `CHANGELOG.md:425`, `CHANGELOG.md:320`
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
    - Source: `otterdog/models/repository.py:290-291`, `otterdog/models/repository.py:1238-1245`
    - Operations: coerce, modify, plan
    - Notes: offline (O-LPLAN-COERCE-SIGNOFF): turning the org requirement off forces 'true -&gt; true' / 'false -&gt; false' on every non-archived repository (archived ones are not forced), a repository-only change is unmanaged while the org requires signoff, managed control. Live (cli.org.signoff, org_level): the org going false re-applies the run repository's own value ('false -&gt; false') and GitHub reports org false / repo false; back to true the repository is unmanaged again and both steps converge. 2019 of 2578 Eclipse repositories set it to false.
- **`plan-semantics.coerce.org-projects-pages`** (covered, P1, `offline`): org has_organization_projects false makes repository has_projects unmanaged; gh_pages_visibility is unmanaged below an enterprise plan
    - Source: `otterdog/models/repository.py:287-294`
    - Operations: coerce, plan
    - Known bugs: KB-033
    - New findings: F-06
    - Notes: has_projects unmanaged/managed, gh_pages_visibility unmanaged on free, managed on enterprise (O-VAL-PAGES-ENTERPRISE visibility-managed); the missing warnings are KB-033 (O-VAL-COERCED).
- **`plan-semantics.coerce.discussion-source`** (covered, P2, `offline`): the repository named by the org discussion_source_repository always gets has_discussions true; the org field is ignored while has_discussions is false
    - Source: `otterdog/models/repository.py:308-314`, `otterdog/models/organization_settings.py:95-99`
    - Operations: coerce, plan
    - Notes: verified offline: discussion_source_repository 'o/a' -&gt; 'o/b' with has_discussions false: Plan 0/0/0. source ignored while discussions are off, source repo forced true (noop), enabling (0/3/0), moving the source (1/2/0).
- **`plan-semantics.coerce.required-custom-properties`** (covered, P2, `offline`): repositories without a value for a required custom property get its default_value; a value equal to the default is dropped from patches
    - Source: `otterdog/models/repository.py:296-306`
    - Operations: coerce, plan, converge
    - Known bugs: KB-030
    - New findings: F-03
    - Notes: offline (O-LPLAN-CUSTOM-PROPERTY-DEFAULTS): the default of a required property is added to a new repository, an explicit default is a noop, a new default changes the definition and the repository (0/2/0), a required property without default crashes loading (KB-030, step-level). Live (cli.custom-property.required, org_level): a run repository created without a value converges and reads the default (GitHub fills it), then the next default.
- **`plan-semantics.ignored-fields`** (covered, P1, `offline`): fields excluded from diffs by other settings: private repos (secret scanning, push protection, dependabot security updates, PVR), pages disabled (source branch/path, visibility) or 'workflow' (source branch/path), code scanning setup disabled (suite, languages), fork_default_branch_only without forked_repository
    - Source: `otterdog/models/repository.py:734-759`, `otterdog/models/repository.py:761-781`
    - Operations: coerce, plan, converge
    - Notes: verified offline: a private repository changing secret_scanning 'enabled' -&gt; 'disabled' and push protection: Plan 0/0/0. The private-repository regression converges with the template's security defaults, which only works because they are excluded. private security, pages disabled/workflow, code scanning suite, model-only creation fields (forked_repository, fork_default_branch_only, auto_init) with controls.
- **`plan-semantics.ignored-org-actions`** (covered, P1, `offline`): Actions fields ignored by diffs: allow_github_owned/verified_creator/action_patterns unless allowed_actions 'selected'; org selected_repositories unless enabled_repositories 'selected'; every org Actions field but enabled_repositories when it is 'none'
    - Source: `otterdog/models/workflow_settings.py:152-157`, `otterdog/models/organization_workflow_settings.py:36-49`
    - Operations: coerce, plan
    - Notes: org patterns/owned/verified/selected repos ignored, everything ignored with enabled 'none', repo patterns ignored (local_only, enabled false, org none); controls with 'selected'.
- **`plan-semantics.ignored-archived`** (covered, P0, `offline`): archived repositories: fields GitHub cannot change on archived repos are not diffed while archived stays true; archiving with other changes shows both, applies the other changes first and archives last; BPRs and rulesets of archived repos are skipped
    - Source: `otterdog/models/repository.py:137-163`, `otterdog/models/repository.py:783-791`, `otterdog/models/repository.py:1259-1276`, `otterdog/models/repository.py:1310-1328`, `otterdog/operations/apply.py:130-137`
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
    - Source: `otterdog/models/organization_settings.py:266-274`, `otterdog/providers/github/rest/org_client.py:82-86`
    - Operations: coerce, plan
    - Notes: verified offline: true -&gt; false: Plan 0/0/0. true -&gt; false dropped (noop), false -&gt; true planned (0/1/0).
- **`plan-semantics.patch-order`** (covered, P1, `cli`): patches are generated and applied in a fixed order: roles, teams, settings (and custom properties), org webhooks, org secrets, org variables, org rulesets, repositories with their nested objects
    - Source: `otterdog/models/github_organization.py:526-546`, `otterdog/operations/apply.py:135-153`
    - Operations: add, plan
    - Known bugs: KB-022
    - Notes: a team granted on a new repository works (teams before repositories, cli.team); an org variable/secret selecting a new repository fails (KB-022). org secret selecting a repo of the same apply (step-level known_bug KB-022, then a strict retry step), teams before settings (security manager team created and assigned in one apply), teams before repositories (cli.team). Roles/org rulesets ordering needs Enterprise.

<a id="org-settings"></a>

## Organization settings

`org-settings`: 13 features, 10 covered, 3 partial, 0 gaps (weighted 88%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `org-settings.profile` | organization profile: name, description (&lt;= 160), email, billing_email, company, location, twitter_username, blog (REST PATCH /orgs/{org}) | cli | free | P0 | covered | **unverified** | `tests/cli/test_import.py::test_import_plans_no_change`, `cli.org.profile` |
| `org-settings.plan` | settings.plan: read-only, never applied, drives every plan gate (validation reads the configured plan, not GitHub) | cli | free | P0 | covered | offline | `cli.plan-mismatch`, `O-VAL-PLAN-GATE`, `O-VAL-ORGSECRET-PRIVATE-FREE` |
| `org-settings.member-privileges` | REST member privileges: default_repository_permission, members_can_create_private/public_repositories, members_can_fork_private_repositories, deploy_keys_enabled_for_repositories, has_organization_projects | cli | free | P1 | covered | **unverified** | `cli.org.member-privileges` |
| `org-settings.pages-creation` | members_can_create_public_pages / members_can_create_private_pages (private: enterprise plan only) | cli | free | P2 | **partial** | **unverified** | `cli.org.member-privileges` |
| `org-settings.web-commit-signoff` | web_commit_signoff_required at org level (257 Eclipse orgs set false; repositories inherit it, see plan-semantics.coerce.org-signoff) | cli | free | P0 | covered | **unverified** | `cli.org.signoff` |
| `org-settings.code-security-defaults` | default_code_security_configurations_disabled true removes the org's default code security configurations (disable only) | cli | free | P2 | covered | **unverified** | `tests/cli/test_org_code_security.py::test_default_code_security_configurations_are_disabled` |
| `org-settings.security-managers` | security_managers: team slugs assigned the security_manager organization role (added and removed to match) | cli | free | P2 | covered | **unverified** | `cli.org.security-managers` |
| `org-settings.web-ui.member-privileges` | web-UI member privileges: members_can_change_repo_visibility, members_can_delete_repositories, members_can_delete_issues, members_can_create_teams, members_can_change_project_visibility, readers_can_create_discussions (UI only) | web_ui | free | P1 | covered | **unverified** | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip`, `tests/web_ui/test_web_settings.py::test_web_settings_table_matches_the_sut`, `tests/web_ui/test_web_settings.py::test_import_reads_web_settings` |
| `org-settings.web-ui.default-branch` | web-UI default_branch_name (repository defaults page) (UI only) | web_ui | free | P2 | covered | **unverified** | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip` |
| `org-settings.web-ui.packages` | web-UI package creation: packages_containers_public, packages_containers_internal (internal: Enterprise Cloud only) (UI only) | web_ui | free | P1 | **partial** | **unverified** | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip` |
| `org-settings.web-ui.discussions` | web-UI org discussions: has_discussions with discussion_source_repository '&lt;org&gt;/&lt;repo&gt;' (17 Eclipse orgs) (UI only) | web_ui | free | P1 | **partial** | **unverified** | `tests/web_ui/test_web_settings.py::test_web_settings_round_trip` |
| `org-settings.web-ui.two-factor` | two_factor_requirement: read-only web setting (never written; a difference prints the read-only note) (UI only) | web_ui | free | P2 | covered | offline | `tests/web_ui/test_web_settings.py::test_web_settings_table_matches_the_sut`, `O-LPLAN-READ-ONLY-KEYS`, `tests/web_ui/test_web_settings.py::test_import_reads_the_two_factor_requirement` |
| `org-settings.web-ui.no-web-ui-skip` | without web credentials (-n, the webapp): web-UI keys are unset before diffing (no plan entry), so web-only changes never apply | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |

Details:

- **`org-settings.profile`** (covered, P0, `cli`): organization profile: name, description (&lt;= 160), email, billing_email, company, location, twitter_username, blog (REST PATCH /orgs/{org})
    - Source: `otterdog/models/organization_settings.py:54-62`, `otterdog/resources/schemas/settings.json:6-41`, `otterdog/providers/github/__init__.py:127-147`
    - Properties (`org-settings`): `name`, `description`, `email`, `billing_email`, `company`, `location`, `twitter_username`, `blog`
    - Operations: modify, converge, import
    - Known bugs: KB-064
    - Notes: name, blog, location, company, email and twitter_username are changed live (':::'), read back by the oracle, converged and restored by a step without fragments (a key going back to null is a '- key = ...' removal line; whether GitHub accepts the JSON null is KB-064). description and billing_email are never changed live by design: the description holds the safety marker (the engine refuses such a plan) and billing_email is owner-only; both are read by the import round trip and the 160-char description rule is the offline validation.org-settings case. description (268 orgs) and name (265) are the most overridden Eclipse org settings.
- **`org-settings.plan`** (covered, P0, `cli`): settings.plan: read-only, never applied, drives every plan gate (validation reads the configured plan, not GitHub)
    - Source: `otterdog/models/organization_settings.py:55`, `otterdog/models/organization_settings.py:179-181`, `otterdog/operations/plan.py:112-117`
    - Properties (`org-settings`): `plan`
    - Operations: plan, validate
    - Known bugs: KB-009
- **`org-settings.member-privileges`** (covered, P1, `cli`): REST member privileges: default_repository_permission, members_can_create_private/public_repositories, members_can_fork_private_repositories, deploy_keys_enabled_for_repositories, has_organization_projects
    - Source: `otterdog/models/organization_settings.py:65-74`, `otterdog/resources/schemas/settings.json:42-65`
    - Properties (`org-settings`): `default_repository_permission`, `members_can_create_private_repositories`, `members_can_create_public_repositories`, `members_can_fork_private_repositories`, `deploy_keys_enabled_for_repositories`, `has_organization_projects`
    - Operations: modify, converge, coerce
    - Notes: members_can_fork_private_repositories false (template) is what forces allow_forking false on private repositories (validation.repo.forking); has_organization_projects false makes repository has_projects unmanaged. default_repository_permission none, members_can_create_public/private_repositories, deploy_keys_enabled_for_repositories, has_organization_projects toggled and back (oracle GET /orgs on every key, converge); members_can_fork_private_repositories true + a private run repo created with allow_forking false whose allow_forking is turned on in the same apply (settings before repositories).
- **`org-settings.pages-creation`** (partial, P2, `cli`): members_can_create_public_pages / members_can_create_private_pages (private: enterprise plan only)
    - Source: `otterdog/models/organization_settings.py:75-76`, `otterdog/models/organization_settings.py:126-130`
    - Properties (`org-settings`): `members_can_create_public_pages`, `members_can_create_private_pages`
    - Operations: modify, validate, converge
    - Known bugs: KB-024
    - Notes: members_can_create_public_pages false then back to the template's true (oracle, converge).
    - Suggested: `enterprise.org.private-pages` in `scenarios/enterprise/org-settings/org-private-pages.yaml`
    - Steps:
        - org_level on an Enterprise Cloud target: settings members_can_create_private_pages true, then false
    - Assert:
        - oracle org members_can_create_private_pages per step; converge; on Free the offline plan gate refuses it (validation.plan-gate.private-pages, KB-024)
    - Needs:
        - enterprise target
        - org_level (full baseline reset)
- **`org-settings.web-commit-signoff`** (covered, P0, `cli`): web_commit_signoff_required at org level (257 Eclipse orgs set false; repositories inherit it, see plan-semantics.coerce.org-signoff)
    - Source: `otterdog/models/organization_settings.py:69`, `otterdog/models/repository.py:1238-1245`
    - Properties (`org-settings`): `web_commit_signoff_required`
    - Operations: modify, coerce, converge
    - Notes: org true (template) with a run repo declaring false (coerced, no change); org false re-applies the repo value ('false -&gt; false' line) and GitHub reports org false/repo false; org back to true: no repo change, oracle org true and repo true (GitHub enforcement, unverified live); converge each step.
- **`org-settings.code-security-defaults`** (covered, P2, `cli`): default_code_security_configurations_disabled true removes the org's default code security configurations (disable only)
    - Source: `otterdog/models/organization_settings.py:70`, `otterdog/providers/github/rest/org_client.py:59-61`, `otterdog/providers/github/rest/org_client.py:683-707`
    - Properties (`org-settings`): `default_code_security_configurations_disabled`
    - Operations: modify, coerce, converge
    - Notes: org_level Python test: an e2e code security configuration made the default for new public repos (Mutator), the baseline plans 'false -&gt; true', the apply leaves GET .../defaults empty (oracle), the plan converges; configuring false while no default exists plans nothing (disable only). Skips when a foreign default exists or the configurations API answers 403/404.
- **`org-settings.security-managers`** (covered, P2, `cli`): security_managers: team slugs assigned the security_manager organization role (added and removed to match)
    - Source: `otterdog/models/organization_settings.py:85`, `otterdog/providers/github/rest/org_client.py:50-57`, `otterdog/providers/github/rest/org_client.py:100-124`
    - Properties (`org-settings`): `security_managers`
    - Operations: add, remove, converge
    - Notes: run team created and assigned the security_manager role in one apply (teams patched before settings), oracle security_managers contains it; back to the template's [] (the baseline): team kept, role removed (equals [] assumes the baseline has no security manager team).
- **`org-settings.web-ui.member-privileges`** (covered, P1, `web_ui`): web-UI member privileges: members_can_change_repo_visibility, members_can_delete_repositories, members_can_delete_issues, members_can_create_teams, members_can_change_project_visibility, readers_can_create_discussions
    - Source: `otterdog/resources/schemas/settings.json:82-101`, `otterdog/resources/schemas/settings.json:118-121`, `otterdog/resources/github-web-settings.jsonnet:1`, `otterdog/providers/github/__init__.py:104-124`
    - Properties (`org-settings`): `members_can_change_repo_visibility`, `members_can_delete_repositories`, `members_can_delete_issues`, `members_can_create_teams`, `members_can_change_project_visibility`, `readers_can_create_discussions`
    - Operations: modify, converge, import
    - Notes: 29 Eclipse orgs set members_can_change_project_visibility, 20 the three repository/teams privileges. readers_can_create_discussions is optional on the page (skipped silently when missing). members_can_change_project_visibility is not REST-readable: with the default reset SUT (the SUT itself) the round trip checks it with the code under test only (report self_checked, BAT-17); the other keys are verified through REST.
- **`org-settings.web-ui.packages`** (partial, P1, `web_ui`): web-UI package creation: packages_containers_public, packages_containers_internal (internal: Enterprise Cloud only)
    - Source: `otterdog/resources/schemas/settings.json:110-117`
    - Properties (`org-settings`): `packages_containers_public`, `packages_containers_internal`
    - Operations: modify, converge
    - Notes: 44 orgs set packages_containers_internal (42 false), 34 packages_containers_public; the round trip toggles internal only on an enterprise target
    - Suggested: `webui.settings.round-trip` in `tests/web_ui/test_web_settings.py`
    - Steps:
        - the round trip toggles these keys with the SUT and reads them back with the trusted reader; REST cannot read them, and with the default reset SUT (release:latest, also the default SUT) the reader runs the SUT's own web code, so a symmetric bug of otterdog's web reader and writer passes (the report lists them as self_checked)
    - Assert:
        - an independent read of the organization settings pages (a Playwright DOM read of the checkbox and select states, harness-side) agrees with the toggled and the restored values
    - Needs:
        - a harness-side Playwright reader of the settings pages, or a reset SUT that differs from the SUT under test
- **`org-settings.web-ui.discussions`** (partial, P1, `web_ui`): web-UI org discussions: has_discussions with discussion_source_repository '&lt;org&gt;/&lt;repo&gt;' (17 Eclipse orgs)
    - Source: `otterdog/resources/schemas/settings.json:122-129`, `otterdog/providers/github/__init__.py:34-35`, `otterdog/models/organization_settings.py:95-99`
    - Properties (`org-settings`): `has_discussions`, `discussion_source_repository`
    - Operations: modify, coerce, converge
    - Suggested: `webui.settings.round-trip` in `tests/web_ui/test_web_settings.py`
    - Steps:
        - the round trip toggles these keys with the SUT and reads them back with the trusted reader; REST cannot read them, and with the default reset SUT (release:latest, also the default SUT) the reader runs the SUT's own web code, so a symmetric bug of otterdog's web reader and writer passes (the report lists them as self_checked)
    - Assert:
        - an independent read of the organization settings pages (a Playwright DOM read of the checkbox and select states, harness-side) agrees with the toggled and the restored values
    - Needs:
        - a harness-side Playwright reader of the settings pages, or a reset SUT that differs from the SUT under test
- **`org-settings.web-ui.two-factor`** (covered, P2, `web_ui`): two_factor_requirement: read-only web setting (never written; a difference prints the read-only note)
    - Source: `otterdog/models/organization_settings.py:68`, `otterdog/resources/schemas/settings.json:102-105`
    - Properties (`org-settings`): `two_factor_requirement`
    - Operations: plan, import
    - Known bugs: KB-041
    - Notes: plan side offline: O-LPLAN-READ-ONLY-KEYS step two-factor-requirement prints the read-only Note and plans nothing. Import side in the existing web_ui login: the imported two_factor_requirement must equal REST two_factor_requirement_enabled (KB-041 test, skipped when the live value equals the template default); the web settings table is checked against the SUT. Never toggled (KB-041, the web UI never reads it).

<a id="org-workflows"></a>

## Organization Actions settings

`org-workflows`: 5 features, 4 covered, 1 partial, 0 gaps (weighted 90%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `org-workflows.enabled-repositories` | org Actions availability: enabled_repositories all \| none \| selected with selected_repositories (repository names -&gt; ids) | cli | free | P1 | covered | **unverified** | `cli.org.actions-enabled-repositories` |
| `org-workflows.allowed-actions` | org allowed actions: allowed_actions all \| local_only \| selected with allow_github_owned_actions, allow_verified_creator_actions, allow_action_patterns (selected-actions endpoint) | cli | free | P1 | covered | **unverified** | `cli.org.actions-allowed` |
| `org-workflows.default-permissions` | org workflow permissions: default_workflow_permissions read \| write, actions_can_approve_pull_request_reviews (243 Eclipse orgs set it false) | cli | free | P0 | covered | **unverified** | `cli.org.workflow-permissions` |
| `org-workflows.fork-pr-approval` | org fork_pr_approval_policy (fork-pr-contributor-approval endpoint; not in the example template's org defaults: unmanaged unless set) | cli | free | P2 | covered | **unverified** | `cli.org.actions-allowed` |
| `org-workflows.cache-size` | org max_cache_size_gb (Actions cache storage limit; changes are cost-related in the webapp) | cli | free | P2 | **partial** | **unverified** | `cli.org.cache-size` |

Details:

- **`org-workflows.enabled-repositories`** (covered, P1, `cli`): org Actions availability: enabled_repositories all | none | selected with selected_repositories (repository names -&gt; ids)
    - Source: `otterdog/models/organization_workflow_settings.py:33-49`, `otterdog/models/organization_workflow_settings.py:87-97`, `otterdog/providers/github/rest/org_client.py:595-619`
    - Properties (`org-workflows`): `enabled_repositories`, `selected_repositories`
    - Operations: modify, converge, coerce
    - Notes: selected with every configured repository except a run repo (overlay over $._repositories, so baseline repos keep Actions), oracle org_actions selected + selected repositories contain the run repo, validate -v Info for the left-out repo, plan not listing it; back to 'all' (selected list no longer diffed, oracle []); 'none' never applied by design.
- **`org-workflows.allowed-actions`** (covered, P1, `cli`): org allowed actions: allowed_actions all | local_only | selected with allow_github_owned_actions, allow_verified_creator_actions, allow_action_patterns (selected-actions endpoint)
    - Source: `otterdog/models/workflow_settings.py:43-46`, `otterdog/models/workflow_settings.py:152-163`, `otterdog/providers/github/rest/org_client.py:621-639`
    - Properties (`org-workflows`): `allowed_actions`, `allow_github_owned_actions`, `allow_verified_creator_actions`, `allow_action_patterns`
    - Operations: modify, converge, coerce
    - Known bugs: KB-029
    - New findings: F-02
    - Notes: selected with github-owned true, verified false, patterns ['actions/\*'] (oracle org_actions + org_selected_actions), repo 'all' ignored (Info); back to 'all': selected-action keys not diffed, selected-actions 409 (absent); 'local_only' never applied (would block GitHub-owned actions org-wide). KB-029 (invalid value crash) stays an offline validation case.
- **`org-workflows.default-permissions`** (covered, P0, `cli`): org workflow permissions: default_workflow_permissions read | write, actions_can_approve_pull_request_reviews (243 Eclipse orgs set it false)
    - Source: `otterdog/models/workflow_settings.py:47-48`, `otterdog/providers/github/rest/org_client.py:641-659`, `otterdog/models/repo_workflow_settings.py:40-67`
    - Properties (`org-workflows`): `default_workflow_permissions`, `actions_can_approve_pull_request_reviews`
    - Operations: modify, converge, coerce
    - Notes: org write + can_approve false (oracle org_workflow_permissions, repo_workflow_permissions write for a run repo), Infos for the coerced repo values; back to read: plan converges although the repo still declares write (no '"read" -&gt; "write"' line), oracle read/true.
- **`org-workflows.fork-pr-approval`** (covered, P2, `cli`): org fork_pr_approval_policy (fork-pr-contributor-approval endpoint; not in the example template's org defaults: unmanaged unless set)
    - Source: `otterdog/models/workflow_settings.py:49-58`, `otterdog/providers/github/rest/org_client.py:661-681`
    - Properties (`org-workflows`): `fork_pr_approval_policy`
    - Operations: modify, validate, converge
    - Known bugs: KB-038
    - New findings: F-11
    - Notes: all_external_contributors then first_time_contributors (oracle org_fork_pr_approval, converge); invalid value refused at validation (stable prefix only, KB-038). The template has no org-level key, so the baseline never restores it: the scenario ends on GitHub's default first_time_contributors.
- **`org-workflows.cache-size`** (partial, P2, `cli`): org max_cache_size_gb (Actions cache storage limit; changes are cost-related in the webapp)
    - Source: `otterdog/models/workflow_settings.py:60-92`, `otterdog/providers/github/rest/org_client.py:562-593`
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

<a id="custom-properties"></a>

## Organization custom properties

`custom-properties`: 6 features, 6 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `custom-properties.definitions` | property definitions: single_select / multi_select / string with allowed_values, description, values_editable_by (add, change allowed values) | cli | free | P2 | covered | offline | `cli.custom-property`, `O-LPLAN-ADD` |
| `custom-properties.required-default` | required properties with default_value (repositories without a value get the default; default_value only diffed when required) | cli | free | P2 | covered | **unverified** | `cli.custom-property.required` |
| `custom-properties.true-false` | value_type true_false properties and their repository values | cli | free | P2 | covered | **unverified** | `cli.custom-property.flag` |
| `custom-properties.value-type-immutable` | changing value_type aborts planning: "planning aborted: trying to change 'value_type' to '&lt;t&gt;' for custom_property[name="&lt;p&gt;"] which is not supported." (exit 1) | offline | free | P2 | covered | offline | `O-LPLAN-CUSTOM-PROPERTY-DEFAULTS` |
| `custom-properties.remove` | removing a property definition (apply -d) and the values of repositories | cli | free | P2 | covered | **unverified** | `cli.custom-property.flag` |
| `custom-properties.repository-values` | repository custom_properties values (single_select, multi_select lists, string); removals need another change (KB-005) | cli | free | P2 | covered | **unverified** | `cli.custom-property`, `cli.kb.custom-property-underscore` |

Details:

- **`custom-properties.definitions`** (covered, P2, `cli`): property definitions: single_select / multi_select / string with allowed_values, description, values_editable_by (add, change allowed values)
    - Source: `otterdog/models/custom_property.py:40-46`, `otterdog/models/custom_property.py:168-181`, `otterdog/models/custom_property.py:224-244`
    - Properties (`custom-property`): `name`, `value_type`, `allowed_values`, `description`, `values_editable_by`
    - Operations: add, modify, converge
    - Known bugs: KB-062
    - Notes: 4 definitions in 2 Eclipse orgs. string properties never send allowed_values (#653, regression.653-string-property)
- **`custom-properties.required-default`** (covered, P2, `cli`): required properties with default_value (repositories without a value get the default; default_value only diffed when required)
    - Source: `otterdog/models/custom_property.py:145-152`, `otterdog/models/repository.py:296-306`
    - Properties (`custom-property`): `required`, `default_value`
    - Operations: add, coerce, converge
    - Known bugs: KB-030
    - New findings: F-03
    - Notes: required single_select with default 'a': run repo created without a value converges and reads 'a' (oracle), then 'b'; org_level (GitHub sets the default on every repo). KB-030 (required without default) stays offline.
- **`custom-properties.true-false`** (covered, P2, `cli`): value_type true_false properties and their repository values
    - Source: `otterdog/models/custom_property.py:52-59`
    - Properties (`custom-property`): `value_type`
    - Operations: add, converge
    - Notes: value_type true_false definition, repo value 'true' then 'false' (oracle custom_property + repo_custom_properties, converge).
- **`custom-properties.value-type-immutable`** (covered, P2, `offline`): changing value_type aborts planning: "planning aborted: trying to change 'value_type' to '&lt;t&gt;' for custom_property[name="&lt;p&gt;"] which is not supported." (exit 1)
    - Source: `otterdog/models/custom_property.py:207-211`
    - Operations: modify, error
    - Notes: verified offline with local-plan (string -&gt; true_false). step value-type-change: expect error, exit 1, exact 'planning aborted: ...' message, no Plan line.
- **`custom-properties.remove`** (covered, P2, `cli`): removing a property definition (apply -d) and the values of repositories
    - Source: `otterdog/models/custom_property.py:200-202`, `otterdog/models/custom_property.py:235-237`
    - Operations: remove
    - Notes: a string property definition dropped with its repo value, apply -d: '- remove custom_property[...]', counts delete 1, oracle definition absent and the repo value gone, the other property kept.
- **`custom-properties.repository-values`** (covered, P2, `cli`): repository custom_properties values (single_select, multi_select lists, string); removals need another change (KB-005)
    - Source: `otterdog/models/repository.py:104`, `otterdog/models/repository.py:1247-1257`, `otterdog/providers/github/rest/repo_client.py:677-698`
    - Properties (`repository`): `custom_properties`
    - Operations: add, modify, converge
    - Known bugs: KB-005, KB-016

<a id="org-roles"></a>

## Custom organization roles

`org-roles`: 2 features, 2 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `org-roles.lifecycle` | custom organization roles: name, description, base_role, permissions (add, change, remove) | enterprise | enterprise | P2 | covered | **unverified** | `enterprise.org-role` |
| `org-roles.unused-model-fields` | OrganizationRole.visibility and selected_repositories: model fields without template defaults (unmanaged unless set; GitHub documents neither for organization roles) | offline | enterprise | P2 | covered | offline | `O-SHOW-ROLE-FIELDS` |

Details:

- **`org-roles.lifecycle`** (covered, P2, `enterprise`): custom organization roles: name, description, base_role, permissions (add, change, remove)
    - Source: `otterdog/models/role.py:33-57`, `otterdog/models/organization_role.py:39-67`, `otterdog/providers/github/rest/org_client.py:174-209`
    - Properties (`org-role`): `name`, `description`, `base_role`, `permissions`
    - Operations: add, modify, remove, converge
    - Notes: 0 Eclipse orgs use roles; removal is the guarded cleanup (-d) of the scenario
- **`org-roles.unused-model-fields`** (covered, P2, `offline`): OrganizationRole.visibility and selected_repositories: model fields without template defaults (unmanaged unless set; GitHub documents neither for organization roles)
    - Source: `otterdog/models/organization_role.py:29-30`
    - Properties (`org-role`): `visibility`, `selected_repositories`
    - Operations: validate
    - Notes: the role schema refuses visibility and selected_repositories (exit 2); the add block and show list name/description/base_role/permissions only.

## Teams

`teams`: 5 features, 5 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `teams.lifecycle` | teams: add, change description, remove (name == slug for run teams; GitHub's auto-added creator is removed) | cli | free | P1 | covered | **unverified** | `cli.team`, `cli.kb.team-permissions-removal` |
| `teams.privacy` | privacy 'visible' (GitHub 'closed') and 'secret' | cli | free | P1 | covered | **unverified** | `cli.team`, `cli.team.settings` |
| `teams.members` | team members: exact member list (added and removed), skip_members (members unmanaged), skip_non_organization_members | cli | free | P1 | covered | **unverified** | `cli.team`, `cli.team.members`, `cli.validate.team-non-member` |
| `teams.notifications` | team notifications on/off (notification_setting) | cli | free | P2 | covered | **unverified** | `cli.team.settings` |
| `teams.repository-permissions` | repository team_permissions {team slug: pull \| triage \| push \| maintain \| admin} (uppercase READ/WRITE accepted by the model) | cli | free | P1 | covered | **unverified** | `cli.team`, `cli.kb.team-permissions-removal` |

Details:

- **`teams.lifecycle`** (covered, P1, `cli`): teams: add, change description, remove (name == slug for run teams; GitHub's auto-added creator is removed)
    - Source: `otterdog/models/team.py:39-47`, `otterdog/models/team.py:142-167`, `otterdog/providers/github/__init__.py:166-182`
    - Properties (`team`): `name`, `description`
    - Operations: add, modify, remove, converge
    - Notes: 81 teams in 18 Eclipse orgs
- **`teams.privacy`** (covered, P1, `cli`): privacy 'visible' (GitHub 'closed') and 'secret'
    - Source: `otterdog/models/team.py:118`, `otterdog/models/team.py:131-132`
    - Properties (`team`): `privacy`
    - Operations: add, modify, converge
    - Known bugs: KB-037
    - New findings: F-10
    - Notes: visible -&gt; secret -&gt; visible ('\~ team[...]', oracle privacy closed/secret/closed, converge).
- **`teams.members`** (covered, P1, `cli`): team members: exact member list (added and removed), skip_members (members unmanaged), skip_non_organization_members
    - Source: `otterdog/models/team.py:45-47`, `otterdog/models/team.py:56-60`, `otterdog/models/team.py:85-99`, `otterdog/models/team.py:113-120`
    - Properties (`team`): `members`, `skip_members`, `skip_non_organization_members`
    - Operations: add, modify, remove, converge
    - Notes: members [author] then [approver] (oracle team_members exact list, team_membership role member / absent), skip_members true with [] keeps the live member (plan noop); skip_non_organization_members validated live with the outsider identity. Needs identities author+approver (outsider for the validation).
- **`teams.notifications`** (covered, P2, `cli`): team notifications on/off (notification_setting)
    - Source: `otterdog/models/team.py:44`, `otterdog/models/team.py:105-111`, `otterdog/models/team.py:134-138`
    - Properties (`team`): `notifications`
    - Operations: modify, converge
    - Notes: notifications false then true (oracle notification_setting notifications_disabled/enabled, converge).
- **`teams.repository-permissions`** (covered, P1, `cli`): repository team_permissions {team slug: pull | triage | push | maintain | admin} (uppercase READ/WRITE accepted by the model)
    - Source: `otterdog/models/repository.py:110`, `otterdog/models/repository.py:194-205`, `otterdog/models/repository.py:274-282`, `otterdog/models/github_organization.py:777-781`
    - Properties (`repository`): `team_permissions`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-005, KB-032
    - New findings: F-05

<a id="webhooks"></a>

## Managed organization and repository webhooks

`webhooks`: 8 features, 6 covered, 2 partial, 0 gaps (weighted 88%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webhooks.org.lifecycle` | organization webhooks keyed by url: add, remove (apply -d), converge; GitHub records a ping delivery | webhooks | free | P0 | covered | offline | `tests/webhooks/test_org_hook.py::test_org_webhook_lifecycle`, `O-LPLAN-ADD`, `O-LPLAN-REMOVE` |
| `webhooks.org.settings` | organization webhook settings: events, content_type json \| form, active, insecure_ssl '0' \| '1' (sent as the hook config) | webhooks | free | P1 | covered | **unverified** | `tests/webhooks/test_org_hook.py::test_org_webhook_lifecycle`, `tests/webhooks/test_managed_org_hook.py::test_org_webhook_settings_are_updated` |
| `webhooks.org.secret` | organization webhook secret: credential reference resolved at apply; presence changes and differing references are planned; '\*\*\*\*\*\*\*\*' skips the whole webhook; removal warns | webhooks | free | P1 | covered | offline | `O-LPLAN-FORCED-WEBHOOKS`, `tests/webhooks/test_managed_org_hook.py::test_org_webhook_secret` |
| `webhooks.org.aliases` | organization webhook aliases (matching by a previous url): the url change itself is never applied (url excluded from diffs) | webhooks | free | P2 | **partial** | **unverified** | `tests/webhooks/test_managed_org_hook.py::test_org_webhook_url_change_through_aliases` |
| `webhooks.repo.lifecycle` | repository webhooks keyed by url: add, remove (nested, apply -d), converge; GitHub records ping deliveries (probe) | cli | free | P0 | covered | offline | `cli.repo.webhook`, `O-LPLAN-ADD`, `O-LPLAN-REMOVE` |
| `webhooks.repo.settings` | repository webhook settings: events, content_type, active, insecure_ssl | cli | free | P1 | covered | **unverified** | `cli.repo.webhook`, `cli.repo.webhook-settings` |
| `webhooks.repo.secret` | repository webhook secret (same semantics as organization webhooks; forced by --update-webhooks with --update-filter on the url) | cli | free | P1 | covered | offline | `O-LPLAN-FORCED-WEBHOOKS`, `cli.repo.webhook-secret` |
| `webhooks.repo.aliases` | repository webhook url change through aliases (documented in docs/userguide/renaming.md) | cli | free | P2 | **partial** | **unverified** | `cli.kb.webhook-url-alias` |

Details:

- **`webhooks.org.lifecycle`** (covered, P0, `webhooks`): organization webhooks keyed by url: add, remove (apply -d), converge; GitHub records a ping delivery
    - Source: `otterdog/models/webhook.py:42-57`, `otterdog/models/organization_webhook.py:24-65`, `otterdog/providers/github/rest/org_client.py:247-300`
    - Properties (`org-webhook`): `url`
    - Operations: add, remove, converge
    - Notes: 94 org webhooks in 87 Eclipse orgs (ci.eclipse.org)
- **`webhooks.org.settings`** (covered, P1, `webhooks`): organization webhook settings: events, content_type json | form, active, insecure_ssl '0' | '1' (sent as the hook config)
    - Source: `otterdog/models/webhook.py:43-47`, `otterdog/models/webhook.py:113-141`
    - Properties (`org-webhook`): `events`, `content_type`, `active`, `insecure_ssl`
    - Operations: add, modify, converge
    - Notes: H-ORG-HOOK-UPDATE: one '\~ org_webhook' change with exactly {active, content_type, events, insecure_ssl}, oracle after each apply, converge, changed back, guarded -d removal.
- **`webhooks.org.secret`** (covered, P1, `webhooks`): organization webhook secret: credential reference resolved at apply; presence changes and differing references are planned; '\*\*\*\*\*\*\*\*' skips the whole webhook; removal warns
    - Source: `otterdog/models/webhook.py:59-95`, `otterdog/models/webhook.py:143-157`, `otterdog/models/webhook.py:199-223`, `otterdog/operations/plan.py:103-110`
    - Properties (`org-webhook`): `secret`
    - Operations: add, modify, forced-update, security
    - Known bugs: KB-026, KB-064
    - Notes: 114 Eclipse webhooks have a secret, 93 of them the dummy '\*\*\*\*\*\*\*\*' (hooks created out of band: never added nor updated by otterdog). Offline (O-LPLAN-FORCED-WEBHOOKS): presence change, reference diff, removal warning, '&lt;DUMMY&gt;', forced update. Live (H-ORG-HOOK-SECRET): a plain dummy secret (Warning) is reported as '\*\*\*\*\*\*\*\*' and converges (never compared), the ping delivery is signed (X-Hub-Signature-256 sha256=...), --update-webhooks --update-filter &lt;url&gt; forces '!', secret null is planned with 'Warning: removing secret for webhook with url ...' and the next ping is unsigned (whether GitHub accepts the JSON null is KB-064); a '\*\*\*\*\*\*\*\*' hook is skipped (Info, never created).
- **`webhooks.org.aliases`** (partial, P2, `webhooks`): organization webhook aliases (matching by a previous url): the url change itself is never applied (url excluded from diffs)
    - Source: `otterdog/models/webhook.py:50-57`, `otterdog/models/webhook.py:65-70`
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
    - Source: `otterdog/models/repo_webhook.py:24-31`, `otterdog/providers/github/rest/repo_client.py:299-352`, `otterdog/models/repository.py:1278-1284`
    - Properties (`repo-webhook`): `url`
    - Operations: add, remove, converge
    - Notes: 447 repository webhooks in 85 Eclipse orgs
- **`webhooks.repo.settings`** (covered, P1, `cli`): repository webhook settings: events, content_type, active, insecure_ssl
    - Source: `otterdog/models/webhook.py:43-47`, `otterdog/models/webhook.py:113-141`
    - Properties (`repo-webhook`): `events`, `content_type`, `active`, `insecure_ssl`
    - Operations: add, modify, converge
    - Notes: active false, insecure_ssl '1', form, two events and back (oracle each step, converge), nested removal -d.
- **`webhooks.repo.secret`** (covered, P1, `cli`): repository webhook secret (same semantics as organization webhooks; forced by --update-webhooks with --update-filter on the url)
    - Source: `otterdog/models/webhook.py:59-95`, `otterdog/models/webhook.py:178-197`
    - Properties (`repo-webhook`): `secret`
    - Operations: add, modify, forced-update, security
    - Known bugs: KB-026, KB-057, KB-064
    - Notes: Offline (O-LPLAN-FORCED-WEBHOOKS): forced update with an url filter, removal warning. Live (cli.repo.webhook-secret): a plain secret (Warning) is reported as config.secret '\*\*\*\*\*\*\*\*', a hook without secret has none, a '\*\*\*\*\*\*\*\*' hook is skipped (Info, absent); --update-webhooks with --update-filter forces only the secured hook; secret null is planned with the removal warning and the oracle shows no secret (KB-064); removal with -d. An unknown provider prefix validates silently (KB-057). Delivery signatures are asserted by the organization variant (H-ORG-HOOK-SECRET).
- **`webhooks.repo.aliases`** (partial, P2, `cli`): repository webhook url change through aliases (documented in docs/userguide/renaming.md)
    - Source: `otterdog/models/webhook.py:50-57`, `otterdog/models/webhook.py:65-70`
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

`secrets-variables`: 10 features, 10 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `secrets-variables.org-secret.lifecycle` | organization secrets: add (value encrypted with the org public key), visibility public \| private \| selected (public == GitHub 'all'), remove | cli | free | P0 | covered | offline | `O-LPLAN-ADD`, `O-VAL-ORGSECRET-PRIVATE-FREE`, `cli.org.secret`, `cli.org.secret-private` |
| `secrets-variables.org-secret.selected-repositories` | organization secret visibility 'selected' with selected_repositories (names resolved to ids at apply) | cli | free | P1 | covered | **unverified** | `cli.org.secret`, `cli.kb.org-secret-same-apply` |
| `secrets-variables.org-variable.lifecycle` | organization variables: add, change value and visibility (public == GitHub 'all'), remove | cli | free | P2 | covered | offline | `cli.org.variable`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE` |
| `secrets-variables.org-variable.selected-repositories` | organization variable visibility 'selected' with selected_repositories | cli | free | P2 | covered | **unverified** | `cli.org.variable`, `cli.kb.org-variable-same-apply` |
| `secrets-variables.repo-secret.lifecycle` | repository secrets: add (repo public key), forced update with --update-secrets, values never read back | cli | free | P0 | covered | offline | `cli.secrets`, `O-LPLAN-ADD`, `O-VAL-OK` |
| `secrets-variables.repo-variable.lifecycle` | repository variables: add, change value, remove; more than 10 variables (pagination) | cli | free | P1 | covered | offline | `cli.secrets`, `cli.kb.variables-pagination`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE` |
| `secrets-variables.env-secret.lifecycle` | environment secrets (orgs.newEnvSecret, since 1.4.0): add with the environment public key, forced update, remove | cli | free | P2 | covered | **unverified** | `cli.environment.secrets` |
| `secrets-variables.env-variable.lifecycle` | environment variables (orgs.newEnvVariable): add, change, remove; upper-case names | cli | free | P2 | covered | **unverified** | `cli.environment.secrets` |
| `secrets-variables.remove` | removing secrets (organization, repository) with apply -d | cli | free | P1 | covered | **unverified** | `cli.environment.secrets`, `cli.org.secret` |
| `secrets-variables.plain-value-warning` | secret values that are not credential references validate with the warning "has a value '&lt;v&gt;' that does not use a credential provider." (the value is echoed) | cli | free | P1 | covered | **unverified** | `cli.secrets` |

Details:

- **`secrets-variables.org-secret.lifecycle`** (covered, P0, `cli`): organization secrets: add (value encrypted with the org public key), visibility public | private | selected (public == GitHub 'all'), remove
    - Source: `otterdog/models/organization_secret.py:27-125`, `otterdog/providers/github/rest/org_client.py:312-384`
    - Properties (`org-secret`): `name`, `value`, `visibility`
    - Operations: add, modify, remove, converge, security
    - Known bugs: KB-025
    - Notes: public (GitHub 'all') add, selected, forced update (--update-secrets with filter), removal -d, dummy '\*\*\*\*\*\*\*\*' skipped; 'private' on Team/Enterprise (cli.org.secret-private, min_plan team; Free: offline gate).
- **`secrets-variables.org-secret.selected-repositories`** (covered, P1, `cli`): organization secret visibility 'selected' with selected_repositories (names resolved to ids at apply)
    - Source: `otterdog/models/organization_secret.py:66-112`, `otterdog/providers/github/rest/org_client.py:328-336`
    - Properties (`org-secret`): `selected_repositories`
    - Operations: add, modify, converge
    - Known bugs: KB-022
    - Notes: selected [sel] then [sel, sel2] (oracle org_secret_repos exact / $unordered, converge); the same-apply case is the KB-022 step of cli.kb.org-secret-same-apply.
- **`secrets-variables.org-variable.lifecycle`** (covered, P2, `cli`): organization variables: add, change value and visibility (public == GitHub 'all'), remove
    - Source: `otterdog/models/organization_variable.py:27-122`, `otterdog/providers/github/rest/org_client.py:386-473`
    - Properties (`org-variable`): `name`, `value`, `visibility`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-003, KB-028
    - New findings: F-01
    - Notes: 3 organization variables in 2 Eclipse orgs
- **`secrets-variables.org-variable.selected-repositories`** (covered, P2, `cli`): organization variable visibility 'selected' with selected_repositories
    - Source: `otterdog/models/organization_variable.py:91-93`, `otterdog/providers/github/rest/org_client.py:402-428`
    - Properties (`org-variable`): `selected_repositories`
    - Operations: add, modify, converge
    - Known bugs: KB-022
- **`secrets-variables.repo-secret.lifecycle`** (covered, P0, `cli`): repository secrets: add (repo public key), forced update with --update-secrets, values never read back
    - Source: `otterdog/models/repo_secret.py:24-31`, `otterdog/models/secret.py:113-176`, `otterdog/providers/github/rest/repo_client.py:1043-1107`
    - Properties (`repo-secret`): `name`, `value`
    - Operations: add, forced-update, converge, security
    - Known bugs: KB-026
    - Notes: 573 repository secrets in 82 Eclipse orgs
- **`secrets-variables.repo-variable.lifecycle`** (covered, P1, `cli`): repository variables: add, change value, remove; more than 10 variables (pagination)
    - Source: `otterdog/models/repo_variable.py:24-31`, `otterdog/providers/github/rest/repo_client.py:1109-1162`
    - Properties (`repo-variable`): `name`, `value`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-003
- **`secrets-variables.env-secret.lifecycle`** (covered, P2, `cli`): environment secrets (orgs.newEnvSecret, since 1.4.0): add with the environment public key, forced update, remove
    - Source: `otterdog/models/environment_secret.py:24-31`, `otterdog/providers/github/rest/repo_client.py:775-866`, `CHANGELOG.md:84-86`
    - Properties (`env-secret`): `name`, `value`
    - Operations: add, forced-update, remove, converge
    - Known bugs: KB-035
    - New findings: F-08
    - Notes: env secret add ('+ add env_secret[name=..., environment=...]'), forced by --update-secrets ('!'), removal -d with the environment kept.
- **`secrets-variables.env-variable.lifecycle`** (covered, P2, `cli`): environment variables (orgs.newEnvVariable): add, change, remove; upper-case names
    - Source: `otterdog/models/environment_variable.py:24-31`, `otterdog/providers/github/rest/repo_client.py:868-933`
    - Properties (`env-variable`): `name`, `value`
    - Operations: add, modify, remove, converge
    - Known bugs: KB-003
    - Notes: env variable add/change/remove with oracle values per step, converge.
- **`secrets-variables.remove`** (covered, P1, `cli`): removing secrets (organization, repository) with apply -d
    - Source: `otterdog/models/secret.py:127-130`, `otterdog/providers/github/rest/repo_client.py:1097-1107`, `otterdog/providers/github/rest/org_client.py:377-384`
    - Operations: remove
    - Notes: repo secret + repo variable (+ env secret/variable) removed with -d, counts delete 4, oracle absent; org secrets removed with -d in cli.org.secret.
- **`secrets-variables.plain-value-warning`** (covered, P1, `cli`): secret values that are not credential references validate with the warning "has a value '&lt;v&gt;' that does not use a credential provider." (the value is echoed)
    - Source: `otterdog/models/secret.py:50-61`, `otterdog/config.py:234-236`
    - Operations: validate, security
    - Known bugs: KB-025, KB-026

## Repositories

`repositories`: 16 features, 15 covered, 1 partial, 0 gaps (weighted 97%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `repositories.lifecycle` | repositories: create (POST /orgs/{org}/repos, settings patched after creation), change description, homepage, topics, delete (apply -d) | cli | free | P0 | covered | offline | `cli.repo.lifecycle`, `O-LPLAN-ADD`, `O-LPLAN-CHANGE`, `O-LPLAN-REMOVE`, `tests/cli/test_import.py::test_import_plans_no_change` |
| `repositories.features` | repository features: has_issues, has_wiki, has_projects (unmanaged when org projects are off), has_discussions (forced on the org discussion source) | cli | free | P0 | covered | offline | `cli.repo.lifecycle`, `cli.repo.features`, `O-LPLAN-COERCE-SIGNOFF` |
| `repositories.merge-methods` | merge settings: allow_merge_commit, allow_rebase_merge, allow_squash_merge, allow_auto_merge, allow_update_branch, delete_branch_on_merge | cli | free | P0 | covered | **unverified** | `cli.repo.lifecycle`, `cli.repo.features` |
| `repositories.merge-commit-messages` | squash_merge_commit_title/message and merge_commit_title/message (squash pair always sent together) | cli | free | P1 | covered | **unverified** | `cli.repo.merge-messages` |
| `repositories.signoff` | repository web_commit_signoff_required (2022 Eclipse repos, 2019 false; unmanaged while the org requires signoff) | cli | free | P0 | covered | **unverified** | `cli.repo.org-coerced`, `cli.org.signoff` |
| `repositories.visibility-forking` | private (create private repositories, change visibility) and allow_forking (private repositories need allow_forking false with the template) | cli | free | P1 | covered | **unverified** | `regression.private-repo-template-defaults`, `enterprise.private-bpr`, `cli.neg.private-bpr`, `cli.repo.visibility` |
| `repositories.default-branch` | default_branch: switch to an existing branch, otherwise rename the current default branch; skipped for empty repositories (1007 Eclipse overrides, 817 'master') | cli | free | P0 | covered | **unverified** | `tests/cli/test_repo_default_branch.py::test_default_branch_rename_and_switch` |
| `repositories.archive` | archived: archive (last, after the other changes), changes to archived repositories are ignored, unarchive (304 archived Eclipse repositories) | cli | free | P0 | covered | **unverified** | `cli.repo.archive` |
| `repositories.security` | security analysis: secret_scanning, secret_scanning_push_protection, dependabot_alerts_enabled (vulnerability alerts), dependabot_security_updates_enabled, private_vulnerability_reporting_enabled (ignored on private repositories) | cli | free | P1 | covered | **unverified** | `cli.repo.security` |
| `repositories.code-scanning` | code scanning default setup: code_scanning_default_setup_enabled, query suite, languages (only disabled on new repositories when configured, #791) | cli | free | P1 | covered | **unverified** | `regression.code-scanning-new-repo`, `regression.private-repo-template-defaults`, `tests/cli/test_repo_code_scanning.py::test_code_scanning_default_setup` |
| `repositories.pages` | GitHub Pages: gh_pages_build_type disabled \| legacy (source branch/path) \| workflow, gh_pages_visibility (enterprise) | cli | free | P1 | **partial** | **unverified** | `cli.repo.pages` |
| `repositories.template-repositories` | is_template, template_repository (create from a template, read-only afterwards), post_process_template_content (mustache-rendered files), auto_init | cli | free | P2 | covered | **unverified** | `tests/cli/test_repo_template.py::test_repository_from_template` |
| `repositories.fork` | forked_repository '&lt;owner&gt;/&lt;repo&gt;' and fork_default_branch_only: create the repository as a fork (13 repos in 7 orgs) | cli | free | P2 | covered | **unverified** | `cli.repo.fork` |
| `repositories.rename` | rename through aliases: ['&lt;old name&gt;'] (one PATCH, nested objects addressed by the new name, #472) | cli | free | P1 | covered | **unverified** | `regression.rename-and-modify` |
| `repositories.extend` | extendRepo(name): extends a repository the template already defines in _repositories (Eclipse: '.eclipsefdn'), merged by name | offline | free | P2 | covered | offline | `O-EXTEND-REPO` |
| `repositories.ghsa-forks-ignored` | temporary private forks of security advisories (GHSA repositories) are never loaded, planned or removed | cli | free | P2 | covered | **unverified** | `tests/cli/test_repo_ghsa.py::test_advisory_fork_is_ignored` |

Details:

- **`repositories.features`** (covered, P0, `cli`): repository features: has_issues, has_wiki, has_projects (unmanaged when org projects are off), has_discussions (forced on the org discussion source)
    - Source: `otterdog/models/repository.py:68-71`, `otterdog/models/repository.py:287-288`, `otterdog/models/repository.py:308-314`
    - Properties (`repository`): `has_issues`, `has_wiki`, `has_projects`, `has_discussions`
    - Operations: add, modify, converge, coerce
    - Known bugs: KB-065
    - Notes: has_issues, has_wiki, has_projects and has_discussions are created with non-default values, flipped (exactly 9 changed attributes, checked offline with local-plan), read back from GET /repos and converged (cli.repo.features). The coercions are diff semantics exercised offline by O-LPLAN-COERCE-SIGNOFF: has_projects is unmanaged while has_organization_projects is false, has_discussions is forced on the org discussion source; their validation messages never fire (KB-033). has_discussions is not documented by the create endpoint and not re-applied after the creation (KB-065, suspected: the create step converges live or shows it). has_wiki (423 Eclipse repos, 407 false), has_discussions (387, 353 true), has_projects (239, 223 false).
- **`repositories.merge-methods`** (covered, P0, `cli`): merge settings: allow_merge_commit, allow_rebase_merge, allow_squash_merge, allow_auto_merge, allow_update_branch, delete_branch_on_merge
    - Source: `otterdog/models/repository.py:76-81`
    - Properties (`repository`): `allow_merge_commit`, `allow_rebase_merge`, `allow_squash_merge`, `allow_auto_merge`, `allow_update_branch`, `delete_branch_on_merge`
    - Operations: add, modify, converge
    - Known bugs: KB-065
    - Notes: allow_auto_merge and allow_update_branch are asserted at creation and after the flip, together with allow_merge_commit, allow_rebase_merge, allow_squash_merge and delete_branch_on_merge.
- **`repositories.merge-commit-messages`** (covered, P1, `cli`): squash_merge_commit_title/message and merge_commit_title/message (squash pair always sent together)
    - Source: `otterdog/models/repository.py:82-85`, `otterdog/models/repository.py:1330-1360`, `otterdog/models/repository.py:631-703`
    - Properties (`repository`): `squash_merge_commit_title`, `squash_merge_commit_message`, `merge_commit_title`, `merge_commit_message`
    - Operations: add, modify, converge, validate
    - Known bugs: KB-053
    - Notes: Both pairs set at creation; a change of only the squash message (the title is resent) is asserted strictly. A change of only merge_commit_message is the last step, declared known_bug KB-053 (suspected): otterdog does not complete the merge pair.
- **`repositories.signoff`** (covered, P0, `cli`): repository web_commit_signoff_required (2022 Eclipse repos, 2019 false; unmanaged while the org requires signoff)
    - Source: `otterdog/models/repository.py:88`, `otterdog/models/repository.py:290-291`
    - Properties (`repository`): `web_commit_signoff_required`
    - Operations: add, modify, coerce, converge
    - Notes: with the example template the org requires signoff, so the repository field is only managed under an org setting off (org_level). cli.repo.org-coerced relaxes the org, then turns the repository from false to true (oracle); cli.org.signoff covers the coercion while the org requires signoff and the 'false -&gt; false' re-send when it stops requiring it. The signoff warning never fires (KB-033) and is not asserted.
- **`repositories.visibility-forking`** (covered, P1, `cli`): private (create private repositories, change visibility) and allow_forking (private repositories need allow_forking false with the template)
    - Source: `otterdog/models/repository.py:67`, `otterdog/models/repository.py:87`, `otterdog/models/repository.py:422-426`, `otterdog/models/repository.py:453-458`
    - Properties (`repository`): `private`, `allow_forking`
    - Operations: add, modify, converge
    - Known bugs: KB-065
    - Notes: An existing repository goes public -&gt; private (allow_forking false, exactly 2 changes) -&gt; public. Each switch must plan a change, never a remove+add. Creating a private repository directly is covered by regression.private-repo-template-defaults only (otterdog 1.7.0.dev14+): older SUTs, release:latest included, fail it without Code Security (#791), so the other private-repository scenarios create their repository public and make it private in the next step.
- **`repositories.default-branch`** (covered, P0, `cli`): default_branch: switch to an existing branch, otherwise rename the current default branch; skipped for empty repositories (1007 Eclipse overrides, 817 'master')
    - Source: `otterdog/models/repository.py:75`, `otterdog/providers/github/rest/repo_client.py:592-611`, `otterdog/providers/github/rest/repo_client.py:267-268`
    - Properties (`repository`): `default_branch`
    - Operations: add, modify, converge
    - Notes: Covers the rename at creation (main-&gt;master), a rename of an existing repo (master-&gt;trunk), and a switch to the existing branch e2e/&lt;run&gt;/develop (created by a probe with Mutator.create_branch; trunk stays). The empty-repository skip is exercised by the auto_init false repository of tests/cli/test_repo_template.py.
- **`repositories.archive`** (covered, P0, `cli`): archived: archive (last, after the other changes), changes to archived repositories are ignored, unarchive (304 archived Eclipse repositories)
    - Source: `otterdog/models/repository.py:86`, `otterdog/models/repository.py:1259-1276`, `otterdog/operations/apply.py:130-137`, `otterdog/models/repository.py:504-509`
    - Properties (`repository`): `archived`
    - Operations: archive, modify, converge
    - Known bugs: KB-058
    - Notes: Archive together with a description change (2 changes); while archived, a description change plus a new BPR plan noop (validate -v Info asserted, oracle shows no BPR); unarchive (1 change).
- **`repositories.security`** (covered, P1, `cli`): security analysis: secret_scanning, secret_scanning_push_protection, dependabot_alerts_enabled (vulnerability alerts), dependabot_security_updates_enabled, private_vulnerability_reporting_enabled (ignored on private repositories)
    - Source: `otterdog/models/repository.py:89-93`, `otterdog/models/repository.py:127-135`, `otterdog/providers/github/rest/repo_client.py:613-660`, `otterdog/models/repository.py:467-474`
    - Properties (`repository`): `secret_scanning`, `secret_scanning_push_protection`, `dependabot_alerts_enabled`, `dependabot_security_updates_enabled`, `private_vulnerability_reporting_enabled`
    - Operations: add, modify, converge, coerce
    - Notes: 748 repos enable dependabot security updates, 215 set PVR, 207 push protection (198 disabled), 187 alerts (168 false). Each setting is checked through its own oracle kind (security_and_analysis, vulnerability-alerts, automated-security-fixes, private-vulnerability-reporting) with exact change counts (2, then 4). The last step also creates a repository with security updates enabled from the start.
- **`repositories.code-scanning`** (covered, P1, `cli`): code scanning default setup: code_scanning_default_setup_enabled, query suite, languages (only disabled on new repositories when configured, #791)
    - Source: `otterdog/models/repository.py:95-97`, `otterdog/providers/github/rest/repo_client.py:464-486`, `otterdog/providers/github/rest/repo_client.py:568-590`, `otterdog/models/repository.py:318-378`
    - Properties (`repository`): `code_scanning_default_setup_enabled`, `code_scanning_default_query_suite`, `code_scanning_default_languages`
    - Operations: add, modify, converge, validate
    - Notes: An existing repository; a probe commits a Python file and a dispatch-only workflow and waits until Python is detected. The setup is then configured with the extended suite for languages [actions, python] (state check timeout 600 s before converge) and disabled.
- **`repositories.pages`** (partial, P1, `cli`): GitHub Pages: gh_pages_build_type disabled | legacy (source branch/path) | workflow, gh_pages_visibility (enterprise)
    - Source: `otterdog/models/repository.py:99-102`, `otterdog/providers/github/rest/repo_client.py:487-566`, `otterdog/models/environment.py:161-173`
    - Properties (`repository`): `gh_pages_build_type`, `gh_pages_source_branch`, `gh_pages_source_path`, `gh_pages_visibility`
    - Operations: add, modify, remove, converge
    - Notes: 309 repos set gh_pages_build_type (legacy 223, workflow 79); 336 of the 408 environments are github-pages, which otterdog never removes while pages are enabled. Covers legacy pages from main /, a change of the source path alone (regression #450), workflow pages with the github-pages environment, then disabled with apply -d removing the environment.
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
    - Source: `otterdog/models/repository.py:72-73`, `otterdog/models/repository.py:114-115`, `otterdog/providers/github/rest/repo_client.py:195-250`, `otterdog/providers/github/rest/repo_client.py:276-277`
    - Properties (`repository`): `is_template`, `template_repository`, `post_process_template_content`, `auto_init`
    - Operations: add, converge
    - Notes: template_repository is read-only: changing it later prints the read-only note (verified offline). 12 repos in 3 orgs use templates, 6 orgs mark templates. Covers is_template, template_repository (oracle template_repository.full_name), post_process_template_content (README.md rendered with org/repo, NOTICE.md not listed stays raw), and auto_init false (no branches).
- **`repositories.fork`** (covered, P2, `cli`): forked_repository '&lt;owner&gt;/&lt;repo&gt;' and fork_default_branch_only: create the repository as a fork (13 repos in 7 orgs)
    - Source: `otterdog/models/repository.py:106-107`, `otterdog/providers/github/rest/repo_client.py:166-193`, `otterdog/models/repository.py:752-753`
    - Properties (`repository`): `forked_repository`, `fork_default_branch_only`
    - Operations: add, converge
    - Notes: Forks octocat/Hello-World with default_branch master and fork_default_branch_only; the oracle checks fork and parent.full_name, and the branches equal [master].
- **`repositories.rename`** (covered, P1, `cli`): rename through aliases: ['&lt;old name&gt;'] (one PATCH, nested objects addressed by the new name, #472)
    - Source: `otterdog/models/repository.py:113`, `otterdog/models/repository.py:220-224`, `otterdog/providers/github/rest/repo_client.py:128-131`
    - Properties (`repository`): `aliases`
    - Operations: rename, modify, converge
    - Notes: 34 aliases in 20 Eclipse orgs; offline counterpart: plan-semantics.rename-aliases
- **`repositories.extend`** (covered, P2, `offline`): extendRepo(name): extends a repository the template already defines in _repositories (Eclipse: '.eclipsefdn'), merged by name
    - Source: `examples/template/otterdog-defaults.libsonnet:121-124`, `examples/template/otterdog-functions.libsonnet:1`
    - Properties (`repository-extend`): `name`
    - Operations: config, modify
    - Notes: extension after (wins) and before (overridden) the definition, appended nested objects, extension alone refused by the schema ('private' is a required property).
- **`repositories.ghsa-forks-ignored`** (covered, P2, `cli`): temporary private forks of security advisories (GHSA repositories) are never loaded, planned or removed
    - Source: `otterdog/providers/github/__init__.py:234-237`, `otterdog/utils.py:520-526`
    - Operations: filter, remove
    - Notes: Draft advisory plus temporary private fork (probe). The plan is noop and the fork never appears; a guarded apply -d leaves it in place. The test closes the advisory and deletes the fork itself.

<a id="repo-workflows"></a>

## Repository Actions settings

`repo-workflows`: 5 features, 4 covered, 1 partial, 0 gaps (weighted 90%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `repo-workflows.enabled` | repository Actions enabled true/false (false sends only 'enabled'; ignored when the org disables or does not select the repository) | cli | free | P1 | covered | **unverified** | `cli.repo.actions`, `cli.org.actions-enabled-repositories` |
| `repo-workflows.allowed-actions` | repository allowed_actions local_only \| selected with the selected-actions properties (managed only when stricter than the org) | cli | free | P2 | covered | **unverified** | `cli.repo.actions`, `cli.org.actions-allowed` |
| `repo-workflows.default-permissions` | repository default_workflow_permissions and actions_can_approve_pull_request_reviews (1354 Eclipse repos set write; unmanaged while the org is 'read' / approvals false) | cli | free | P0 | covered | **unverified** | `cli.repo.org-coerced`, `cli.repo.actions`, `cli.org.workflow-permissions` |
| `repo-workflows.fork-pr-approval` | repository fork_pr_approval_policy (skipped for private repositories: GitHub answers 422, #635) | cli | free | P2 | covered | **unverified** | `regression.private-repo-template-defaults`, `cli.repo.actions` |
| `repo-workflows.cache-size` | repository max_cache_size_gb (cache storage limit; cost-related above defaults.cost_policy.free_max_cache_size_gb) | cli | free | P2 | **partial** | **unverified** | `cli.repo.cache-limit` |

Details:

- **`repo-workflows.enabled`** (covered, P1, `cli`): repository Actions enabled true/false (false sends only 'enabled'; ignored when the org disables or does not select the repository)
    - Source: `otterdog/models/repo_workflow_settings.py:38`, `otterdog/models/repo_workflow_settings.py:45-54`, `otterdog/models/repo_workflow_settings.py:138-157`
    - Properties (`repo-workflows`): `enabled`
    - Operations: modify, coerce, converge
    - Notes: 176 Eclipse repos set enabled, 167 false. Created with Actions disabled (only 'enabled' sent), then enabled. The coercion (org selected/none) is covered by cli.org.actions-enabled-repositories
- **`repo-workflows.allowed-actions`** (covered, P2, `cli`): repository allowed_actions local_only | selected with the selected-actions properties (managed only when stricter than the org)
    - Source: `otterdog/models/workflow_settings.py:43-46`, `otterdog/models/repo_workflow_settings.py:56-59`, `otterdog/providers/github/rest/repo_client.py:1266-1288`
    - Properties (`repo-workflows`): `allowed_actions`, `allow_github_owned_actions`, `allow_verified_creator_actions`, `allow_action_patterns`
    - Operations: modify, coerce, converge
    - Known bugs: KB-029
    - New findings: F-02
    - Notes: Covers 'selected' with github_owned true, verified false and patterns [actions/\*] (oracle repo_selected_actions), then 'local_only' (selected-actions absent). The coercion (org more restrictive) is covered by cli.org.actions-allowed.
- **`repo-workflows.default-permissions`** (covered, P0, `cli`): repository default_workflow_permissions and actions_can_approve_pull_request_reviews (1354 Eclipse repos set write; unmanaged while the org is 'read' / approvals false)
    - Source: `otterdog/models/workflow_settings.py:47-48`, `otterdog/models/repo_workflow_settings.py:61-65`, `otterdog/providers/github/rest/repo_client.py:1290-1312`
    - Properties (`repo-workflows`): `default_workflow_permissions`, `actions_can_approve_pull_request_reviews`
    - Operations: modify, coerce, converge
    - Notes: the example template's org default_workflow_permissions 'read' makes the repository value unmanaged: a scenario must set the org to 'write' (org_level) first. With the org at 'write', the repository goes 'read' -&gt; 'write'. actions_can_approve_pull_request_reviews false/true is set at repository level in both scenarios. The coercion with the org at 'read' is covered by cli.org.workflow-permissions.
- **`repo-workflows.fork-pr-approval`** (covered, P2, `cli`): repository fork_pr_approval_policy (skipped for private repositories: GitHub answers 422, #635)
    - Source: `otterdog/models/workflow_settings.py:49-58`, `otterdog/providers/github/rest/repo_client.py:1314-1338`
    - Properties (`repo-workflows`): `fork_pr_approval_policy`
    - Operations: modify, converge
    - Notes: all_external_contributors on a public repository, read through repo_fork_pr_approval.
- **`repo-workflows.cache-size`** (partial, P2, `cli`): repository max_cache_size_gb (cache storage limit; cost-related above defaults.cost_policy.free_max_cache_size_gb)
    - Source: `otterdog/models/workflow_settings.py:60-92`, `otterdog/providers/github/rest/repo_client.py:1232-1264`
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

<a id="branch-protection"></a>

## Branch protection rules

`branch-protection`: 10 features, 10 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `branch-protection.lifecycle` | branch protection rules keyed by pattern: add, change, remove from an existing repository (apply -d); private repositories need Team or Enterprise | cli | free | P0 | covered | offline | `cli.bpr.public`, `enterprise.private-bpr`, `cli.neg.private-bpr`, `O-LPLAN-ADD`, `O-LPLAN-CHANGE` |
| `branch-protection.pull-request-reviews` | pull request reviews: requires_pull_request, required_approving_review_count, dismisses_stale_reviews, requires_code_owner_reviews, require_last_push_approval | cli | free | P0 | covered | **unverified** | `cli.bpr.public`, `enterprise.private-bpr`, `cli.bpr.settings` |
| `branch-protection.review-dismissal` | restricts_review_dismissals with review_dismissal_allowances (users '@login', teams '@org/team', apps) | cli | free | P2 | covered | **unverified** | `cli.bpr.allowances`, `cli.protection.app-checks` |
| `branch-protection.bypass-allowances` | bypass_pull_request_allowances and bypass_force_push_allowances (actor node ids) | cli | free | P1 | covered | **unverified** | `cli.bpr.allowances`, `cli.protection.app-checks` |
| `branch-protection.status-checks` | required status checks: requires_status_checks, requires_strict_status_checks, required_status_checks ('any:&lt;ctx&gt;', '&lt;app-slug&gt;:&lt;ctx&gt;', plain contexts bound to github-actions) | cli | free | P0 | covered | **unverified** | `cli.bpr.public`, `cli.bpr.settings`, `cli.protection.app-checks` |
| `branch-protection.history-and-signatures` | requires_linear_history, requires_conversation_resolution, requires_commit_signatures | cli | free | P1 | covered | offline | `cli.bpr.public`, `enterprise.private-bpr`, `O-LPLAN-CHANGE`, `cli.bpr.settings` |
| `branch-protection.force-push-deletion-admin` | allows_force_pushes, allows_deletions, is_admin_enforced | cli | free | P1 | covered | **unverified** | `cli.bpr.public`, `cli.bpr.settings` |
| `branch-protection.push-restrictions` | restricts_pushes with push_restrictions (actors) and blocks_creations | cli | free | P2 | covered | **unverified** | `cli.bpr.allowances`, `cli.protection.app-checks` |
| `branch-protection.lock-branch` | lock_branch with lock_allows_fetch_and_merge (warning when the lock is off) | cli | free | P2 | covered | **unverified** | `cli.bpr.lock` |
| `branch-protection.deployments` | requires_deployments with required_deployment_environments (must be environments of the repository) | cli | free | P2 | covered | **unverified** | `cli.bpr.deployments` |

Details:

- **`branch-protection.pull-request-reviews`** (covered, P0, `cli`): pull request reviews: requires_pull_request, required_approving_review_count, dismisses_stale_reviews, requires_code_owner_reviews, require_last_push_approval
    - Source: `otterdog/models/branch_protection_rule.py:55-62`, `otterdog/models/branch_protection_rule.py:88-99`, `otterdog/models/branch_protection_rule.py:301-303`
    - Properties (`bpr`): `requires_pull_request`, `required_approving_review_count`, `dismisses_stale_reviews`, `requires_code_owner_reviews`, `require_last_push_approval`
    - Operations: add, modify, converge, validate
    - Notes: require_last_push_approval true, then requires_pull_request false with required_approving_review_count null (the dependent fields leave the diff: exactly 7 changes).
- **`branch-protection.review-dismissal`** (covered, P2, `cli`): restricts_review_dismissals with review_dismissal_allowances (users '@login', teams '@org/team', apps)
    - Source: `otterdog/models/branch_protection_rule.py:64-65`, `otterdog/models/branch_protection_rule.py:312-317`
    - Properties (`bpr`): `restricts_review_dismissals`, `review_dismissal_allowances`
    - Operations: add, modify, converge
    - Notes: restricts_review_dismissals with a team and a user (cli.bpr.allowances) and with the e2e App (cli.protection.app-checks, requires app); the oracle uses otterdog's notation.
- **`branch-protection.bypass-allowances`** (covered, P1, `cli`): bypass_pull_request_allowances and bypass_force_push_allowances (actor node ids)
    - Source: `otterdog/models/branch_protection_rule.py:63`, `otterdog/models/branch_protection_rule.py:67`, `otterdog/models/branch_protection_rule.py:319-331`
    - Properties (`bpr`): `bypass_pull_request_allowances`, `bypass_force_push_allowances`
    - Operations: add, modify, converge
    - Notes: 34 Eclipse rules use bypass_pull_request_allowances+. bypass_pull_request_allowances and bypass_force_push_allowances with a team and a user, swapped in the update step (exactly 5 changes), and with the App.
- **`branch-protection.status-checks`** (covered, P0, `cli`): required status checks: requires_status_checks, requires_strict_status_checks, required_status_checks ('any:&lt;ctx&gt;', '&lt;app-slug&gt;:&lt;ctx&gt;', plain contexts bound to github-actions)
    - Source: `otterdog/models/branch_protection_rule.py:77-79`, `otterdog/models/branch_protection_rule.py:333-363`, `otterdog/models/branch_protection_rule.py:270-290`
    - Properties (`bpr`): `requires_status_checks`, `requires_strict_status_checks`, `required_status_checks`
    - Operations: add, modify, converge
    - Notes: A plain context is bound to github-actions (oracle app.slug github-actions); a '&lt;app-slug&gt;:&lt;ctx&gt;' check uses the e2e App (requires app); 'any:' is in cli.bpr.public.
- **`branch-protection.history-and-signatures`** (covered, P1, `cli`): requires_linear_history, requires_conversation_resolution, requires_commit_signatures
    - Source: `otterdog/models/branch_protection_rule.py:73-75`
    - Properties (`bpr`): `requires_linear_history`, `requires_conversation_resolution`, `requires_commit_signatures`
    - Operations: add, modify, converge
    - Notes: requires_commit_signatures true, then false.
- **`branch-protection.force-push-deletion-admin`** (covered, P1, `cli`): allows_force_pushes, allows_deletions, is_admin_enforced
    - Source: `otterdog/models/branch_protection_rule.py:50-52`
    - Properties (`bpr`): `allows_force_pushes`, `allows_deletions`, `is_admin_enforced`
    - Operations: add, modify, converge
    - Notes: allows_force_pushes and allows_deletions true, then false; is_admin_enforced true.
- **`branch-protection.push-restrictions`** (covered, P2, `cli`): restricts_pushes with push_restrictions (actors) and blocks_creations
    - Source: `otterdog/models/branch_protection_rule.py:69-71`, `otterdog/models/branch_protection_rule.py:305-310`, `otterdog/models/branch_protection_rule.py:203-220`
    - Properties (`bpr`): `restricts_pushes`, `push_restrictions`, `blocks_creations`
    - Operations: add, modify, converge
    - Notes: restricts_pushes with a team, then user+team, and blocks_creations true-&gt;false, on 'release/\*' of a public repository. GitHub documents branch restrictions on public repositories of Free organizations. The App is the push actor in cli.protection.app-checks.
- **`branch-protection.lock-branch`** (covered, P2, `cli`): lock_branch with lock_allows_fetch_and_merge (warning when the lock is off)
    - Source: `otterdog/models/branch_protection_rule.py:53-54`, `otterdog/models/branch_protection_rule.py:222-229`
    - Properties (`bpr`): `lock_branch`, `lock_allows_fetch_and_merge`
    - Operations: add, modify, converge
    - Notes: lock_branch and lock_allows_fetch_and_merge true, then false (2 changes).
- **`branch-protection.deployments`** (covered, P2, `cli`): requires_deployments with required_deployment_environments (must be environments of the repository)
    - Source: `otterdog/models/branch_protection_rule.py:81-82`, `otterdog/models/branch_protection_rule.py:180-201`
    - Properties (`bpr`): `requires_deployments`, `required_deployment_environments`
    - Operations: add, modify, converge, validate
    - Notes: requires_deployments with the repository's own environment in the same apply; drop (1 change); validation error for an undefined environment.

<a id="rulesets"></a>

## Repository and organization rulesets

`rulesets`: 10 features, 9 covered, 1 partial, 0 gaps (weighted 95%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `rulesets.repo.lifecycle` | repository rulesets keyed by name with ref conditions include_refs / exclude_refs (\~DEFAULT_BRANCH, \~ALL, refs/heads/\*): add, change, remove | cli | free | P1 | covered | offline | `cli.ruleset.public`, `regression.disabled-ruleset-without-refs`, `O-VAL-OK`, `O-VAL-RULESET-STRICT` |
| `rulesets.targets` | ruleset target branch \| tag \| push (tag protection rulesets with include_refs ['\~ALL'] are used by eclipse-csi) | cli | free | P1 | **partial** | **unverified** | `cli.ruleset.public`, `cli.ruleset.rules` |
| `rulesets.enforcement` | enforcement active \| disabled \| evaluate (evaluate: enterprise plan) | cli | free | P1 | covered | **unverified** | `cli.ruleset.public`, `regression.disabled-ruleset-without-refs`, `enterprise.org-ruleset` |
| `rulesets.rules` | simple rules: allows_creations, allows_deletions, allows_updates, allows_force_pushes (inverted rules), requires_linear_history, requires_commit_signatures | cli | free | P1 | covered | **unverified** | `cli.ruleset.public`, `cli.kb.ruleset-default-status-checks`, `cli.ruleset.rules` |
| `rulesets.bypass-actors` | bypass_actors: '#RepositoryAdmin' \| '#Maintain' \| '#Write' \| '#OrganizationAdmin', '@user', '@org/team', '&lt;app-slug&gt;', each with an optional ':&lt;bypass_mode&gt;' (always \| pull_request) | cli | free | P1 | covered | **unverified** | `cli.ruleset.bypass`, `cli.protection.app-checks`, `regression.user-bypass-actors` |
| `rulesets.deployments` | requires_deployments with required_deployment_environments | cli | free | P2 | covered | **unverified** | `cli.ruleset.deployments` |
| `rulesets.pull-request` | required_pull_request (orgs.newPullRequest): required_approving_review_count 0..10, dismisses_stale_reviews, requires_code_owner_review, requires_last_push_approval, requires_review_thread_resolution | cli | free | P1 | covered | **unverified** | `cli.ruleset.public`, `regression.ruleset-empty-status-checks`, `cli.neg.private-ruleset`, `cli.ruleset.pull-request` |
| `rulesets.status-checks` | required_status_checks (orgs.newStatusChecks): strict, status_checks ('&lt;app&gt;:&lt;ctx&gt;', 'any:' dropped on read), do_not_enforce_on_create; an empty list sends no rule (#562) | cli | free | P1 | covered | offline | `cli.ruleset.public`, `regression.ruleset-empty-status-checks`, `cli.kb.ruleset-any-status-check`, `cli.kb.ruleset-default-status-checks`, `O-VAL-RULESET-STRICT`, `regression.repo-ruleset-without-strict`, `cli.ruleset.status-checks`, `cli.protection.app-checks` |
| `rulesets.merge-queue` | required_merge_queue (orgs.newMergeQueue): merge_method MERGE \| SQUASH \| REBASE, build_concurrency, min/max_group_size, wait_time_for_minimum_group_size, status_check_timeout, requires_all_group_entries_to_pass_required_checks | cli | free | P2 | covered | **unverified** | `cli.ruleset.merge-queue`, `enterprise.ruleset-merge-queue-private` |
| `rulesets.org.repository-conditions` | organization rulesets: include_repo_names / exclude_repo_names (fnmatch, '\~ALL'), protect_repo_names; enterprise plan in otterdog | enterprise | enterprise | P2 | covered | **unverified** | `enterprise.org-ruleset`, `enterprise.kb.org-ruleset-repo-patterns` |

Details:

- **`rulesets.targets`** (partial, P1, `cli`): ruleset target branch | tag | push (tag protection rulesets with include_refs ['\~ALL'] are used by eclipse-csi)
    - Source: `otterdog/models/ruleset.py:337`, `otterdog/models/ruleset.py:363-415`
    - Properties (`repo-ruleset`): `target`
    - Operations: add, converge, validate
    - Notes: A tag ruleset with include_refs ['\~ALL'] and creation/update/deletion rules, plus an exclude pattern, is applied and converged.
    - Suggested: `cli.ruleset.push-target` in `scenarios/cli/rulesets/ruleset-push-target.yaml`
    - Steps:
        - private run repository on a Team/Enterprise target: a ruleset with target 'push' and a file path rule
    - Assert:
        - discovery: what GitHub accepts from otterdog's model (otterdog always sends ref_name conditions and its simple rules are not push rules); record it, then assert it
    - Needs:
        - target
        - min_plan: team
        - requires: [push_rulesets]
- **`rulesets.rules`** (covered, P1, `cli`): simple rules: allows_creations, allows_deletions, allows_updates, allows_force_pushes (inverted rules), requires_linear_history, requires_commit_signatures
    - Source: `otterdog/models/ruleset.py:345-351`, `otterdog/models/ruleset.py:513-525`, `otterdog/models/ruleset.py:677-691`
    - Properties (`repo-ruleset`): `allows_creations`, `allows_deletions`, `allows_updates`, `allows_force_pushes`, `requires_linear_history`, `requires_commit_signatures`
    - Operations: add, modify, converge
    - Notes: Exact rule sets: update, required_signatures, no non_fast_forward/creation, then the inverse (8 changes).
- **`rulesets.bypass-actors`** (covered, P1, `cli`): bypass_actors: '#RepositoryAdmin' | '#Maintain' | '#Write' | '#OrganizationAdmin', '@user', '@org/team', '&lt;app-slug&gt;', each with an optional ':&lt;bypass_mode&gt;' (always | pull_request)
    - Source: `otterdog/models/ruleset.py:340`, `otterdog/models/ruleset.py:360-361`, `otterdog/models/ruleset.py:527-570`, `otterdog/models/ruleset.py:634-670`
    - Properties (`repo-ruleset`): `bypass_actors`
    - Operations: add, modify, converge
    - Known bugs: KB-039, KB-052
    - New findings: F-12
    - Notes: 22 Eclipse rulesets use bypass_actors+ ('#OrganizationAdmin', '@&lt;org&gt;/eclipsefdn-releng'); the webapp's own config-repo ruleset needs '#OrganizationAdmin'. Covers #OrganizationAdmin, #RepositoryAdmin, #Maintain:pull_request, #Write, a team, then mode changes; the App actor (app-checks); the user actor (779, fixed_in 1.7.0.dev7). Known-bug steps: '#Admin' (KB-039) and explicit ':always' (KB-052).
- **`rulesets.deployments`** (covered, P2, `cli`): requires_deployments with required_deployment_environments
    - Source: `otterdog/models/ruleset.py:353-354`, `otterdog/models/ruleset.py:418-437`
    - Properties (`repo-ruleset`): `requires_deployments`, `required_deployment_environments`
    - Operations: add, modify, converge, validate
    - Notes: required_deployments rule with the repository's environment; drop (1 change); validation error for an undefined environment.
- **`rulesets.pull-request`** (covered, P1, `cli`): required_pull_request (orgs.newPullRequest): required_approving_review_count 0..10, dismisses_stale_reviews, requires_code_owner_review, requires_last_push_approval, requires_review_thread_resolution
    - Source: `otterdog/models/ruleset.py:49-119`
    - Properties (`ruleset-pull-request`): `required_approving_review_count`, `dismisses_stale_reviews`, `requires_code_owner_review`, `requires_last_push_approval`, `requires_review_thread_resolution`
    - Operations: add, modify, remove, converge, validate
    - Known bugs: KB-031
    - New findings: F-04
    - Notes: Count 0 with every flag on, then count 3 with every flag off, then required_pull_request null removes the rule.
- **`rulesets.status-checks`** (covered, P1, `cli`): required_status_checks (orgs.newStatusChecks): strict, status_checks ('&lt;app&gt;:&lt;ctx&gt;', 'any:' dropped on read), do_not_enforce_on_create; an empty list sends no rule (#562)
    - Source: `otterdog/models/ruleset.py:122-227`
    - Properties (`ruleset-status-checks`): `strict`, `status_checks`, `do_not_enforce_on_create`
    - Operations: add, modify, converge, validate
    - Known bugs: KB-020, KB-021, KB-054
    - Notes: do_not_enforce_on_create, the plain context and '15368:&lt;ctx&gt;' (GitHub Actions integration id) are strict; the installed App slug is in app-checks. Known-bug steps for 'github-actions:&lt;ctx&gt;' and '&lt;installed app id&gt;:&lt;ctx&gt;' never converge (KB-054).
- **`rulesets.merge-queue`** (covered, P2, `cli`): required_merge_queue (orgs.newMergeQueue): merge_method MERGE | SQUASH | REBASE, build_concurrency, min/max_group_size, wait_time_for_minimum_group_size, status_check_timeout, requires_all_group_entries_to_pass_required_checks
    - Source: `otterdog/models/ruleset.py:230-325`
    - Properties (`ruleset-merge-queue`): `merge_method`, `build_concurrency`, `min_group_size`, `max_group_size`, `wait_time_for_minimum_group_size`, `status_check_timeout`, `requires_all_group_entries_to_pass_required_checks`
    - Operations: add, modify, converge, validate
    - Known bugs: KB-031
    - New findings: F-04
    - Notes: 12 merge queues in 3 Eclipse orgs (eclipse-score: MERGE 6, SQUASH 5, REBASE 1). Public repository: SQUASH with non-default sizes, then MERGE/HEADGREEN. Private repository on Enterprise: requires merge_queue_private.
- **`rulesets.org.repository-conditions`** (covered, P2, `enterprise`): organization rulesets: include_repo_names / exclude_repo_names (fnmatch, '\~ALL'), protect_repo_names; enterprise plan in otterdog
    - Source: `otterdog/models/organization_ruleset.py:27-35`, `otterdog/models/organization_ruleset.py:44-82`, `otterdog/providers/github/rest/org_client.py:727-793`
    - Properties (`org-ruleset`): `include_repo_names`, `exclude_repo_names`, `protect_repo_names`
    - Operations: add, modify, remove, converge, validate
    - Known bugs: KB-009, KB-023
    - Notes: New repo-conditions step in enterprise.org-ruleset: exclude_repo_names for a second run repository and protect_repo_names true; oracle repository_name {include, exclude, protected}; 1 add + 2 changes, checked offline with the enterprise plan.

<a id="environments"></a>

## Deployment environments

`environments`: 4 features, 4 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `environments.lifecycle` | deployment environments keyed by name: add, change, remove (github-pages is never removed while pages are enabled) | cli | free | P0 | covered | offline | `cli.environment`, `enterprise.env-reviewers-private`, `O-LPLAN-ADD`, `O-LPLAN-CHANGE`, `cli.environment.policies`, `cli.environment.private` |
| `environments.wait-timer` | wait_timer protection rule (minutes, 0..43200) | cli | free | P1 | covered | offline | `cli.environment`, `enterprise.env-reviewers-private`, `O-LPLAN-CHANGE` |
| `environments.reviewers` | required reviewers ('@user', '@org/team') and prevent_self_review (private repositories: Enterprise only) | cli | free | P1 | covered | **unverified** | `enterprise.env-reviewers-private`, `cli.environment.reviewers` |
| `environments.branch-policies` | deployment_branch_policy all \| protected \| selected with branch_policies (branch patterns, 'tag:&lt;pattern&gt;' for tags) | cli | free | P0 | covered | offline | `cli.environment`, `O-LPLAN-ADD`, `O-VAL-OK`, `cli.environment.policies`, `cli.environment.private` |

Details:

- **`environments.lifecycle`** (covered, P0, `cli`): deployment environments keyed by name: add, change, remove (github-pages is never removed while pages are enabled)
    - Source: `otterdog/models/environment.py:58`, `otterdog/models/environment.py:161-173`, `otterdog/models/environment.py:347-420`, `otterdog/providers/github/rest/repo_client.py:724-773`
    - Properties (`environment`): `name`
    - Operations: add, modify, remove, converge
    - Notes: Live removal from an existing repository: '- remove environment' with apply -d, environment absent, repository kept. Private repositories (min_plan team, requires private_repo_environments) in cli.environment.private.
- **`environments.reviewers`** (covered, P1, `cli`): required reviewers ('@user', '@org/team') and prevent_self_review (private repositories: Enterprise only)
    - Source: `otterdog/models/environment.py:60-61`, `otterdog/models/environment.py:179-188`, `otterdog/models/environment.py:238-246`
    - Properties (`environment`): `reviewers`, `prevent_self_review`
    - Operations: add, modify, converge, validate
    - Notes: Public repository: a team (pull access) plus the admin user with prevent_self_review, then the team only (2 changes). A one-minute wait timer makes the protection_rules list deterministic.
- **`environments.branch-policies`** (covered, P0, `cli`): deployment_branch_policy all | protected | selected with branch_policies (branch patterns, 'tag:&lt;pattern&gt;' for tags)
    - Source: `otterdog/models/environment.py:62-63`, `otterdog/models/environment.py:190-209`, `otterdog/models/environment.py:248-270`, `otterdog/providers/github/rest/repo_client.py:971-1041`
    - Properties (`environment`): `deployment_branch_policy`, `branch_policies`
    - Operations: add, modify, remove, converge, validate
    - Known bugs: KB-036
    - New findings: F-09
    - Notes: selected with ['main', 'tag:v\*'] (oracle types branch/tag), then 'protected' (1 change).

<a id="receiver"></a>

## Webhook receiver contract

`receiver`: 8 features, 8 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `receiver.endpoint` | POST GITHUB_WEBHOOK_ENDPOINT (default /github-webhook/receive); the webapp refuses to start without GITHUB_WEBHOOK_SECRET | offline | free | P0 | covered | offline | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/offline/test_webapp_runtime.py::test_webhook_endpoint_is_configurable` |
| `receiver.signature` | only 'X-Hub-Signature: sha1=&lt;hmac&gt;' is checked: missing ("Missing header: X-Hub-Signature"), wrong or sha256-only deliveries answer 400 | offline | free | P0 | covered | offline | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong` |
| `receiver.required-headers` | a signed delivery without X-Github-Event or content-type answers 400 'Missing header: &lt;name&gt;' | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong`, `tests/offline/test_webapp_contract.py::test_optional_headers` |
| `receiver.content-types` | content types: exactly application/json, or application/x-www-form-urlencoded with a 'payload' field; anything else (also a charset parameter) answers 415 | offline | free | P1 | covered | offline | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong`, `tests/offline/test_webapp_contract.py::test_form_encoded_delivery_is_processed`, `tests/offline/test_webapp_contract.py::test_form_delivery_without_payload_is_rejected` |
| `receiver.empty-body` | a JSON body 'null' answers 400 'Request body must contain data' | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong` |
| `receiver.accepted` | valid deliveries answer 204 whatever the hooks do: ping, events nobody handles, unknown installations ("received event for unknown installation '&lt;id&gt;'") | offline | free | P0 | covered | offline | `tests/offline/test_webapp_contract.py::test_webhook_receiver_contract`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/offline/test_webapp_contract.py::test_replayed_delivery_is_processed_again` |
| `receiver.hook-exception` | an exception in a hook is logged with the delivery context ('failed to process webhook delivery &lt;id&gt; for event ...') and propagates (500) | offline | free | P2 | covered | offline | `tests/offline/test_webapp_runtime.py::test_database_outage` |
| `receiver.event-logging` | event descriptions are logged per delivery; formatting errors never block processing; workflow_job/workflow_run are only logged for queued/completed | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_workflow_events_are_described_selectively`, `tests/offline/test_webapp_contract.py::test_unformattable_events_are_still_processed`, `tests/offline/test_webapp_contract.py::test_form_encoded_delivery_is_processed`, `tests/offline/test_webapp_contract.py::test_replayed_delivery_is_processed_again` |

Details:

- **`receiver.endpoint`** (covered, P0, `offline`): POST GITHUB_WEBHOOK_ENDPOINT (default /github-webhook/receive); the webapp refuses to start without GITHUB_WEBHOOK_SECRET
    - Source: `otterdog/webapp/webhook/github_webhook.py:28-47`, `otterdog/webapp/config.py:87`
    - Operations: api, config, security
    - Known bugs: KB-012
    - Notes: GITHUB_WEBHOOK_ENDPOINT moves the receiver, the default path then answers 404
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
| `webapp-events.pr-opened` | pull_request opened on the config repo: UpdatePullRequestTask; non-draft: help comment, team membership, validation and sync check | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_pr_validation.py::test_invalid_config_pr`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed` |
| `webapp-events.pr-synchronize` | pull_request synchronize (new commits): re-validation and sync check of the new head (sync status propagated from the previous commit within an hour) | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_new_commits_are_validated_again` |
| `webapp-events.pr-draft` | draft pull requests: converted_to_draft only updates the record; ready_for_review triggers help, team membership, validation and sync check; drafts are never validated on open | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_stale_status.py::test_stale_snapshot_keeps_merged_status`, `tests/webapp/test_pr_validation.py::test_draft_pr_lifecycle` |
| `webapp-events.pr-reopened` | pull_request reopened: re-validation and sync check; otterdog/\* branches also refresh their blueprint status | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_closed_pr_is_validated_again_when_reopened`, `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint` |
| `webapp-events.pr-closed` | pull_request closed: merged into the default branch -&gt; ApplyChangesTask; closed unmerged -&gt; record closed; otterdog/\* head branches are deleted and their blueprint status updated | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_closed_prs_are_never_applied`, `tests/webapp/test_otterdog_branches.py::test_otterdog_branches_are_deleted` |
| `webapp-events.review` | pull_request_review submitted / edited / dismissed: UpdatePullRequestTask with the review (approvals recomputed, auto-merge offered when eligible) | webapp | free | P1 | **partial** | **unverified** | `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_merge_apply.py::test_dismissed_approval_blocks_the_merge` |
| `webapp-events.issue-comment` | issue_comment created / edited on a config-repo pull request: the first matching /otterdog command runs (issues and other repositories are ignored) | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_commands.py::test_help_command`, `tests/webapp/test_commands.py::test_validate_command`, `tests/webapp/test_commands.py::test_comment_matching_and_edits` |
| `webapp-events.push` | push to the default branch: config repo -&gt; FetchConfigTask (+ policies/blueprints reload when otterdog/policies or otterdog/blueprints change); any repo -&gt; re-evaluate matching blueprints; the configs repo -&gt; reload otterdog.json and every installation | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_blueprints.py::test_global_definitions_reload_on_configs_push`, `tests/webapp/test_blueprints.py::test_required_file_remediation` |
| `webapp-events.installation` | installation created / deleted / suspend / unsuspend: installation status NOT_INSTALLED, SUSPENDED, INSTALLED (+ data refresh) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_installation_events.py::test_installation_events_update_the_record` |
| `webapp-events.workflow-events` | workflow_job queued -&gt; macos_large_runners policy; workflow_run completed -&gt; dependency_track_upload policy | webapp | free | P2 | covered | offline | `tests/webapp/test_policies.py::test_macos_large_runner_jobs_are_cancelled_unless_allowed`, `tests/webapp/test_policies.py::test_sbom_upload_to_dependency_track`, `tests/offline/test_webapp_contract.py::test_workflow_events_are_described_selectively` |

Details:

- **`webapp-events.pr-synchronize`** (covered, P0, `webapp`): pull_request synchronize (new commits): re-validation and sync check of the new head (sync status propagated from the previous commit within an hour)
    - Source: `otterdog/webapp/webhook/__init__.py:151-174`, `otterdog/webapp/tasks/check_sync.py:91-124`
    - Operations: event, task, status
    - Notes: W-PR-SYNCHRONIZE (P0): three commits, a validate comment per head sha (previous minimized), success/success/error, /api valid false after the broken commit; the sync status of commits 2 and 3 is copied (one non-pending status, no pending one).
- **`webapp-events.pr-draft`** (covered, P1, `webapp`): draft pull requests: converted_to_draft only updates the record; ready_for_review triggers help, team membership, validation and sync check; drafts are never validated on open
    - Source: `otterdog/webapp/webhook/__init__.py:112-174`
    - Operations: event, task
    - Notes: W-PR-DRAFT (P1): draft opened -&gt; record only (draft true, no comment, no status, delivery+quiesce); mark_ready -&gt; help, team-info, validate comments, success, sync, draft false; convert_to_draft -&gt; draft true, no new comment/status.
- **`webapp-events.pr-reopened`** (covered, P2, `webapp`): pull_request reopened: re-validation and sync check; otterdog/\* branches also refresh their blueprint status
    - Source: `otterdog/webapp/webhook/__init__.py:99-107`, `otterdog/webapp/webhook/__init__.py:151-174`
    - Operations: event, task
    - Notes: W-PR-REOPEN (P2): unmerged close drops the /api record, no ApplyChangesTask/apply comment; reopen -&gt; open record (not_applied), new validate comment for the same sha, a second pending validation status. The otterdog/\* blueprint-status part is exercised by W-BP-DISMISS (reopen of a remediation PR).
- **`webapp-events.pr-closed`** (covered, P0, `webapp`): pull_request closed: merged into the default branch -&gt; ApplyChangesTask; closed unmerged -&gt; record closed; otterdog/\* head branches are deleted and their blueprint status updated
    - Source: `otterdog/webapp/webhook/__init__.py:89-107`, `otterdog/webapp/webhook/__init__.py:176-187`
    - Operations: event, task
    - Notes: W-PR-CLOSED (P0): an unmerged close (record gone, no ApplyChangesTask, no apply comment, repo not created) and a PR merged into a side base branch (recorded merged/not_applied, no ApplyChangesTask, no comment, repo not created). W-OPEN-PR-BRANCH covers the otterdog/\* branch deletion.
- **`webapp-events.review`** (partial, P1, `webapp`): pull_request_review submitted / edited / dismissed: UpdatePullRequestTask with the review (approvals recomputed, auto-merge offered when eligible)
    - Source: `otterdog/webapp/webhook/__init__.py:192-221`, `otterdog/webapp/tasks/update_pull_request.py:49-86`
    - Operations: event, task, permission
    - Notes: W-AUTOMERGE-DISMISS (P1): REQUEST_CHANGES -&gt; has_required_approvals false (no offer), approval -&gt; true + automerge comment, admin dismissal -&gt; false, /otterdog merge refused ('No approval from a member of'), PR open.
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
- **`webapp-events.push`** (covered, P0, `webapp`): push to the default branch: config repo -&gt; FetchConfigTask (+ policies/blueprints reload when otterdog/policies or otterdog/blueprints change); any repo -&gt; re-evaluate matching blueprints; the configs repo -&gt; reload otterdog.json and every installation
    - Source: `otterdog/webapp/webhook/__init__.py:252-336`, `otterdog/webapp/tasks/fetch_config.py:32-107`
    - Operations: event, task, state
    - Known bugs: KB-015
    - Notes: W-MERGE-APPLY waits for the relayed push of the merge commit, a finished FetchConfigTask created after the merge and /api/organizations/&lt;org&gt; listing the new repository with its description (the stored sha is the blob sha and is not exposed by the API). A push to the configs repository reloading the global definitions is W-BP-GLOBAL-PUSH (KB-015, scoped xfail), a push to a project repository re-evaluating blueprints is W-BP-REQUIRED-FILE (a deleted strict file is re-added at once); the boot checks the FetchConfigTask of /internal/init.
- **`webapp-events.installation`** (covered, P2, `webapp`): installation created / deleted / suspend / unsuspend: installation status NOT_INSTALLED, SUSPENDED, INSTALLED (+ data refresh)
    - Source: `otterdog/webapp/webhook/__init__.py:339-348`, `otterdog/webapp/db/service.py:64-110`
    - Operations: event, state
    - Notes: W-INSTALLATION-EVENTS (P2): signed synthetic installation deliveries for the real id: suspend -&gt; suspended, unsuspend -&gt; installed + finished FetchConfigTask and FetchAllPullRequestsTask, deleted -&gt; not_installed with id 0, created -&gt; installed with the real id + refresh; /internal/init restores on failure. Routing verified against the 9bdeb75 image locally.
- **`webapp-events.workflow-events`** (covered, P2, `webapp`): workflow_job queued -&gt; macos_large_runners policy; workflow_run completed -&gt; dependency_track_upload policy
    - Source: `otterdog/webapp/webhook/__init__.py:351-420`
    - Operations: event, task
    - Notes: workflow_job queued: W-POL-MACOS (the run on a macOS larger runner is cancelled unless allowed, the /admin/policies counters change); workflow_run completed: W-POL-SBOM (UploadSBOMTask, PUT /api/v1/bom of the Dependency-Track mock); offline, the receiver describes workflow_job only when queued and workflow_run only when completed.

<a id="webapp-commands"></a>

## Pull request comment commands

`webapp-commands`: 9 features, 8 covered, 1 partial, 0 gaps (weighted 94%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-commands.help` | /otterdog help (and on every non-draft PR opened by a user, never a bot): help comment listing the commands, previous one minimized | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_commands.py::test_help_command`, `tests/webapp/test_pr_validation.py::test_valid_config_pr` |
| `webapp-commands.team-info` | /otterdog team-info (and on PR open): the author's org membership and teams; sets author_can_auto_merge (bot authors skipped) | webapp | free | P1 | **partial** | **unverified** | `tests/webapp/test_commands.py::test_team_info_command`, `tests/webapp/test_pr_validation.py::test_draft_pr_lifecycle` |
| `webapp-commands.check-sync` | /otterdog check-sync: re-runs the sync check now (no 1-hour propagation for comments) | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_commands.py::test_drift_check_sync` |
| `webapp-commands.done` | /otterdog done by an admin team member marks a merged, not completed PR as completed (done comment); other users get the wrong-team comment | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_secret_needs_a_manual_apply` |
| `webapp-commands.apply` | /otterdog apply by an admin team member re-applies a merged, valid, not completed PR (e.g. after a failed apply); others get the wrong-team comment | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_failed_apply_is_retried_by_an_admin`, `tests/webapp/test_merge_apply.py::test_secret_needs_a_manual_apply` |
| `webapp-commands.merge` | /otterdog merge: merges an eligible PR on behalf of its author (or a member of the approval/admin teams); otherwise the automerge problems comment | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |
| `webapp-commands.validate` | /otterdog validate: re-validates the head (WARN level), new validate comment, previous minimized | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_commands.py::test_validate_command` |
| `webapp-commands.validate-info` | /otterdog validate info: validation at INFO level (Info notices included in the validate comment) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_commands.py::test_validate_info_command` |
| `webapp-commands.matching` | command matching: re.match at the start of the comment, no word boundary ('/otterdog helpme' runs help), first handler wins, text after the command ignored | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_commands.py::test_comment_matching_and_edits` |

Details:

- **`webapp-commands.team-info`** (partial, P1, `webapp`): /otterdog team-info (and on PR open): the author's org membership and teams; sets author_can_auto_merge (bot authors skipped)
    - Source: `otterdog/webapp/webhook/comment_handlers.py:65-81`, `otterdog/webapp/tasks/retrieve_team_membership.py:46-120`
    - Operations: comment, task, permission
    - Known bugs: KB-017, KB-027
    - Notes: W-CMD-TEAM-INFO (P1): contributor PR -&gt; team-info comment (author link, role == GitHub author_association, contributors team link, no admin/approval team), /api author_can_auto_merge false; /otterdog team-info -&gt; new comment, first minimized.
    - Suggested: `W-CMD-TEAM-INFO-BOT` in `tests/webapp/test_commands.py`
    - Steps:
        - a PR opened by the e2e App (a blueprint remediation PR of the config repository)
    - Assert:
        - no help and no team-info comment for the bot-authored PR
    - Needs:
        - webapp
        - app
- **`webapp-commands.done`** (covered, P1, `webapp`): /otterdog done by an admin team member marks a merged, not completed PR as completed (done comment); other users get the wrong-team comment
    - Source: `otterdog/webapp/webhook/comment_handlers.py:101-116`, `otterdog/webapp/tasks/complete_pull_request.py:35-94`
    - Operations: comment, task, permission, state
    - Known bugs: KB-013
    - Notes: Wrong-team /otterdog done of a contributor (comment naming &lt;org&gt;/&lt;admin team&gt;, apply_status stays partially_applied) is in W-MERGE-SECRET instead of the suggested W-CMD-DONE-WRONG-TEAM (same partial-apply flow, keeps the catalogue test W-PR-WEBUI identity-free).
- **`webapp-commands.apply`** (covered, P1, `webapp`): /otterdog apply by an admin team member re-applies a merged, valid, not completed PR (e.g. after a failed apply); others get the wrong-team comment
    - Source: `otterdog/webapp/webhook/comment_handlers.py:119-134`, `otterdog/webapp/tasks/apply_changes.py:88-132`
    - Operations: comment, task, permission
    - Known bugs: KB-001, KB-013
    - Notes: W-CMD-APPLY (P1): repo created out of band -&gt; merged PR's apply fails ([!CAUTION], 'failed to apply patch', partially_applied); contributor /otterdog apply -&gt; wrong_team_apply_comment, record unchanged; repo removed -&gt; admin /otterdog apply -&gt; success, repo created with the declared description, completed; /otterdog apply of a completed PR -&gt; ApplyChangesTask finished, no comment. Note: a failed apply is recorded partially_applied (ApplyStatus.FAILED only for exceptions outside the local-apply).
- **`webapp-commands.validate-info`** (covered, P2, `webapp`): /otterdog validate info: validation at INFO level (Info notices included in the validate comment)
    - Source: `otterdog/webapp/webhook/comment_handlers.py:157-175`
    - Operations: comment, task
    - Notes: W-CMD-VALIDATE-INFO (P2): dummy repo secret: default comment has 'there have been N validation infos' and no Info line; /otterdog validate info prints 'repo_secret[name=...] only has a dummy value, resource will be skipped.' and no hint; first comment minimized.
- **`webapp-commands.matching`** (covered, P2, `webapp`): command matching: re.match at the start of the comment, no word boundary ('/otterdog helpme' runs help), first handler wins, text after the command ignored
    - Source: `otterdog/webapp/webhook/comment_handlers.py:36-37`, `otterdog/webapp/webhook/__init__.py:61-69`, `otterdog/webapp/webhook/__init__.py:242-247`
    - Operations: comment, event
    - Notes: W-CMD-NEG (P1) instead of the separate W-CMD-MATCHING/W-CMD-EDITED (one PR, the docs/scenario-catalog.md planned id): 'please /otterdog help' ignored, '/otterdog validate' validates, '/otterdog helpme, ...' helps (prefix match), '/otterdog validate\n/otterdog help' runs validate only. All cases also verified against the 9bdeb75 webapp image locally.

<a id="webapp-pr"></a>

## Pull request validation, sync check and apply

`webapp-pr`: 15 features, 13 covered, 2 partial, 0 gaps (weighted 93%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-pr.validation` | validation: local-plan of the PR head against the default branch HEAD, validate comment (plan output escaped), status success / error on the head sha | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_pr_validation.py::test_invalid_config_pr`, `tests/webapp/test_commands.py::test_validate_command` |
| `webapp-pr.pending-statuses` | pending statuses are set first: 'validating configuration change using otterdog' and 'checking if configuration is in-sync using otterdog' | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_valid_config_pr` |
| `webapp-pr.validation-failure` | a crashing validation task: status failure 'otterdog validation failed, please contact an admin'; evaluation exceptions give the friendly comment 'Validation failed while evaluating the configuration. ...' | webapp | free | P1 | **partial** | **unverified** | `tests/webapp/test_pr_validation.py::test_evaluation_error_gets_a_friendly_comment` |
| `webapp-pr.validation-warnings` | validation warnings: changes requiring secrets, the web UI or that may incur costs (max_cache_size_gb) are listed and block auto-merge | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_pr_validation.py::test_validation_warnings` |
| `webapp-pr.no-changes` | a PR whose org file equals the base: 'No changes.' and success without running local-plan; PRs touching other files never auto-merge | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_non_configuration_change` |
| `webapp-pr.import-confinement` | jsonnet imports are confined to the org directory during validation, sync check and apply (an import of '../../x' fails) | webapp | free | P1 | **partial** | **unverified** | `tests/webapp/test_pr_validation.py::test_imports_are_confined_to_the_org_directory` |
| `webapp-pr.sync-check` | sync check: plan of the default branch HEAD against GitHub; out of sync -&gt; check-sync comment and description 'otterdog sync check failed, check comment history' with state success (informational) | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_commands.py::test_drift_check_sync`, `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_commands.py::test_sync_check_of_an_invalid_main` |
| `webapp-pr.sync-failure` | a crashing sync check sets state failure with the description 'otterdog detected out of sync changes, but they will not prevent a successful merge' | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_commands.py::test_sync_check_crash` |
| `webapp-pr.sync-propagation` | sync check throttling: on synchronize within an hour of the previous commit the previous final sync status is copied; sync tasks back off at least one minute | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_new_commits_are_validated_again`, `tests/webapp/test_pr_validation.py::test_out_of_sync_status_survives_a_new_commit` |
| `webapp-pr.apply` | apply after merge: local-apply of the merge commit against its base commit (squash, rebase with several commits #773, merge commits), apply comment, apply_status completed | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_merge_apply.py::test_merge_commit_applies_every_commit`, `tests/webapp/test_merge_apply.py::test_drifted_org_still_auto_merges` |
| `webapp-pr.apply-deletions` | the webapp applies deletions (delete_resources=True): a merged PR removing an object deletes it on GitHub | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_merged_removal_is_applied` |
| `webapp-pr.apply-partial` | patches needing secrets or the web UI are skipped by the webapp (no web UI, include_resources_with_secrets false): apply_status partially_applied, comment 'only partially applied ...', completed by /otterdog done | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_secret_needs_a_manual_apply` |
| `webapp-pr.apply-guards` | apply is skipped for unmerged, already completed or invalid PRs; a failed or crashed apply is recorded partially_applied with 'Applying the configuration failed. ...' | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_invalid_merged_pr_is_not_applied`, `tests/webapp/test_merge_apply.py::test_failed_apply_is_retried_by_an_admin`, `tests/webapp/test_merge_apply.py::test_crashing_apply_gets_a_friendly_comment`, `tests/webapp/test_merge_apply.py::test_closed_prs_are_never_applied` |
| `webapp-pr.records` | pull request records (/api/pullrequests): status open/closed/merged, draft, valid, in_sync, requires_manual_apply, supports_auto_merge, author_can_auto_merge, has_required_approvals, apply_status | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |
| `webapp-pr.delete-otterdog-branch` | closing a PR whose head branch starts with 'otterdog/' deletes the branch (open-pr and blueprint remediation branches) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_otterdog_branches.py::test_otterdog_branches_are_deleted` |

Details:

- **`webapp-pr.validation`** (covered, P0, `webapp`): validation: local-plan of the PR head against the default branch HEAD, validate comment (plan output escaped), status success / error on the head sha
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:105-231`, `otterdog/webapp/tasks/validate_pull_request.py:255-271`
    - Operations: task, status, comment, validate
    - Known bugs: KB-026
- **`webapp-pr.pending-statuses`** (covered, P2, `webapp`): pending statuses are set first: 'validating configuration change using otterdog' and 'checking if configuration is in-sync using otterdog'
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:233-242`, `otterdog/webapp/tasks/check_sync.py:214-223`
    - Operations: status
    - Notes: W-PR-VALID lists every commit status (GET .../commits/{sha}/statuses): first validation status pending 'validating configuration change using otterdog', last success; first sync status pending 'checking if configuration is in-sync using otterdog', last success.
- **`webapp-pr.validation-failure`** (partial, P1, `webapp`): a crashing validation task: status failure 'otterdog validation failed, please contact an admin'; evaluation exceptions give the friendly comment 'Validation failed while evaluating the configuration. ...'
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:183-192`, `otterdog/webapp/tasks/validate_pull_request.py:244-253`
    - Operations: status, error, comment
    - Known bugs: KB-008, KB-025, KB-032
    - Notes: W-PR-EVAL-ERROR (P1) uses a team_permissions value outside the schema enum (uncaught jsonschema error, KB-032) instead of 'pass:a:b': the config guard refuses the KB-025 crash (no load error in its output). Asserts the friendly 'Validation failed while evaluating the configuration.' + 'Please contact an admin...', no 'Traceback'/'Failed validating'/value, status error, /api valid false.
    - Suggested: `W-PR-VALIDATION-CRASH` in `tests/webapp/test_pr_validation.py`
    - Steps:
        - a never-merged PR whose head deletes otterdog/&lt;org&gt;.jsonnet (the validation task crashes)
    - Assert:
        - commit status 'failure' with 'otterdog validation failed, please contact an admin'
    - Needs:
        - webapp
        - harness: ConfigRepoFlow opt-in to open a PR deleting the org configuration (refused today)
- **`webapp-pr.validation-warnings`** (covered, P1, `webapp`): validation warnings: changes requiring secrets, the web UI or that may incur costs (max_cache_size_gb) are listed and block auto-merge
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:164-205`, `otterdog/models/__init__.py:150-188`, `otterdog/config.py:312-330`
    - Operations: validate, comment, permission
    - Notes: W-PR-WARNINGS (P1): secret -&gt; secrets warning, requires_manual_apply true, supports_auto_merge false; max_cache_size_gb 10 -&gt; 5 on a declared repo (main pins 10 with ':::' so the diff exists also when the renderer hides the cache limit) -&gt; cost warning, supports_auto_merge false, no manual apply; both refused by /otterdog merge; new repo with 10 GB -&gt; no warning, auto-merge offered.
- **`webapp-pr.no-changes`** (covered, P2, `webapp`): a PR whose org file equals the base: 'No changes.' and success without running local-plan; PRs touching other files never auto-merge
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:146-155`, `otterdog/webapp/tasks/validate_pull_request.py:279-286`
    - Operations: validate, permission
    - Notes: W-PR-NO-CHANGES (P2): README.md-only PR -&gt; 'No changes.' + success; multi-file PR (org config + README.md) -&gt; validated on its config change; both valid, supports_auto_merge false, no automerge comment, /otterdog merge refused naming 'touches non-configuration files'.
- **`webapp-pr.import-confinement`** (partial, P1, `webapp`): jsonnet imports are confined to the org directory during validation, sync check and apply (an import of '../../x' fails)
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:176-180`, `otterdog/webapp/tasks/apply_changes.py:205-209`, `otterdog/webapp/tasks/check_sync.py:175-178`, `CHANGELOG.md:127`
    - Operations: validate, security
    - Notes: W-PR-IMPORT-CONFINEMENT (P1): importstr '../e2e-&lt;run&gt;-...-outside.libsonnet' (exists nowhere): comment shows 'failed to load configuration' + "import of '../...' is not allowed" (an unconfined evaluation says "can't resolve": strict xfail on SUTs before 326d62d), status error, /api valid false. Message verified with the 1.7.0.dev19 code.
    - Suggested: `W-SYNC-IMPORT-CONFINEMENT` in `tests/webapp/test_commands.py`
    - Steps:
        - main importing a file outside the org directory; /otterdog check-sync and a merged PR
    - Assert:
        - the sync check and the apply refuse the import ("import of '../...' is not allowed")
    - Needs:
        - webapp
        - harness: an audited 'restore main to the baseline' path for tests that break main on purpose
- **`webapp-pr.sync-check`** (covered, P0, `webapp`): sync check: plan of the default branch HEAD against GitHub; out of sync -&gt; check-sync comment and description 'otterdog sync check failed, check comment history' with state success (informational)
    - Source: `otterdog/webapp/tasks/check_sync.py:141-212`, `otterdog/webapp/tasks/check_sync.py:236-273`
    - Operations: task, status, comment
    - Known bugs: KB-019, KB-067
    - Notes: W-PR-VALID asserts the in-sync outcome ('otterdog sync check completed successfully', state success, no check-sync comment); W-DRIFT-CHECKSYNC the out-of-sync one.
- **`webapp-pr.sync-failure`** (covered, P2, `webapp`): a crashing sync check sets state failure with the description 'otterdog detected out of sync changes, but they will not prevent a successful merge'
    - Source: `otterdog/webapp/tasks/check_sync.py:135-139`, `otterdog/webapp/tasks/check_sync.py:225-234`
    - Operations: status, error
    - Known bugs: KB-040
    - New findings: F-13
    - Notes: W-SYNC-FAILURE (P2): main with a team_permissions schema error makes the sync plan raise: state failure, failed CheckConfigurationInSyncTask (on open and after /otterdog check-sync), no check-sync comment, in_sync never set; the misleading 'detected out of sync changes' description is a scoped xfail (MisleadingSyncFailureError, known_bug KB-040).
- **`webapp-pr.sync-propagation`** (covered, P2, `webapp`): sync check throttling: on synchronize within an hour of the previous commit the previous final sync status is copied; sync tasks back off at least one minute
    - Source: `otterdog/webapp/tasks/check_sync.py:91-129`
    - Operations: status, task
    - Known bugs: KB-066
    - Notes: Propagation observed as one non-pending sync status on the new head (no pending, same state/description). Note: the CheckConfigurationInSyncTask is still recorded (finished) when it copies, so the outline's 'task count unchanged' is wrong. W-SYNC-PROPAGATION-DRIFT is a scoped xfail of KB-066 (copied out-of-sync status becomes 'completed successfully').
- **`webapp-pr.apply`** (covered, P0, `webapp`): apply after merge: local-apply of the merge commit against its base commit (squash, rebase with several commits #773, merge commits), apply comment, apply_status completed
    - Source: `otterdog/webapp/tasks/apply_changes.py:147-237`, `otterdog/webapp/utils.py:430-508`
    - Operations: task, comment, state, add
    - Notes: W-MERGE-COMMIT-APPLY (P0): merge method 'merge' (2-parent commit) applies both commits, both repos with their descriptions, completed. W-AUTOMERGE-DRIFT shows the apply replays only the PR diff (drift left untouched).
- **`webapp-pr.apply-deletions`** (covered, P0, `webapp`): the webapp applies deletions (delete_resources=True): a merged PR removing an object deletes it on GitHub
    - Source: `otterdog/webapp/tasks/apply_changes.py:186-200`
    - Operations: task, remove
    - Notes: W-MERGE-DELETE (P0): declared run repo removed by a PR: validate comment 'remove repository[name=...]', supports_auto_merge false, no automerge comment, /otterdog merge refused; admin merge -&gt; apply comment names the removal, repo deleted (oracle), completed.
- **`webapp-pr.apply-partial`** (covered, P1, `webapp`): patches needing secrets or the web UI are skipped by the webapp (no web UI, include_resources_with_secrets false): apply_status partially_applied, comment 'only partially applied ...', completed by /otterdog done
    - Source: `otterdog/webapp/tasks/apply_changes.py:134-145`, `otterdog/webapp/tasks/apply_changes.py:186-212`
    - Operations: task, state, comment
    - Notes: W-MERGE-SECRET (P1): new run repo with a secret: apply creates the repo, never the secret (oracle repo_secret None), 'only partially applied', partially_applied, completed by the admin's /otterdog done.
- **`webapp-pr.apply-guards`** (covered, P1, `webapp`): apply is skipped for unmerged, already completed or invalid PRs; a failed or crashed apply is recorded partially_applied with 'Applying the configuration failed. ...'
    - Source: `otterdog/webapp/tasks/apply_changes.py:88-107`, `otterdog/webapp/tasks/apply_changes.py:213-221`
    - Operations: task, state, error
    - Known bugs: KB-001, KB-039
    - Notes: W-MERGE-INVALID (invalid topic: ApplyChangesTask finished without comment, nothing created, merged/not_applied), W-CMD-APPLY (already completed -&gt; skipped; patch failure), W-PR-CLOSED (unmerged). W-MERGE-APPLY-CRASH (P1): KB-039 '#Admin' bypass actor as trigger -&gt; [!CAUTION] with 'Applying the configuration failed.'/'Please contact an admin', no KeyError/Traceback, partially_applied, repo created, ruleset not (skips if KB-039 is fixed). Title correction: a failed or crashed apply is recorded partially_applied, not failed.
- **`webapp-pr.records`** (covered, P1, `webapp`): pull request records (/api/pullrequests): status open/closed/merged, draft, valid, in_sync, requires_manual_apply, supports_auto_merge, author_can_auto_merge, has_required_approvals, apply_status
    - Source: `otterdog/webapp/db/models.py:73-115`, `otterdog/webapp/db/service.py:505-579`, `otterdog/webapp/tasks/update_pull_request.py:41-95`
    - Operations: state, api
    - Known bugs: KB-018
- **`webapp-pr.delete-otterdog-branch`** (covered, P2, `webapp`): closing a PR whose head branch starts with 'otterdog/' deletes the branch (open-pr and blueprint remediation branches)
    - Source: `otterdog/webapp/webhook/__init__.py:89-97`, `otterdog/webapp/tasks/delete_branch.py:29-42`
    - Operations: task, event
    - Notes: W-OPEN-PR-BRANCH in tests/webapp (not tests/cli): PR opened with 'otterdog open-pr' (trusted reset CLI, fresh workspace, adopted by the flow) closed -&gt; finished DeleteBranchTask (no pull_request recorded) and the otterdog/e2e-&lt;run&gt;-\* branch gone.

<a id="webapp-automerge"></a>

## Auto-merge eligibility and merge

`webapp-automerge`: 4 features, 4 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-automerge.eligibility` | eligibility: open, validated and valid, supports_auto_merge, and (author in an approval/admin team OR an approval by such a member) | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_approval_team_author_merges_without_review` |
| `webapp-automerge.blockers` | auto-merge is refused when the PR contains secrets, needs the web UI, may incur costs, includes deletions or touches non-configuration files | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_pr_validation.py::test_validation_warnings`, `tests/webapp/test_pr_validation.py::test_non_configuration_change`, `tests/webapp/test_merge_apply.py::test_merged_removal_is_applied` |
| `webapp-automerge.comment` | the automerge comment is posted once (when no unminimized one exists) as soon as validation, sync check or a review make the PR eligible | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_automerge_after_approval` |
| `webapp-automerge.third-party` | /otterdog merge by someone else than the author requires approval/admin team membership ('Only the author of the pull request, a member of ..., or a member of ... is allowed to auto-merge.') | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_merge_command_of_a_third_party` |

Details:

- **`webapp-automerge.eligibility`** (covered, P0, `webapp`): eligibility: open, validated and valid, supports_auto_merge, and (author in an approval/admin team OR an approval by such a member)
    - Source: `otterdog/webapp/db/models.py:117-203`, `otterdog/webapp/tasks/__init__.py:279-297`
    - Operations: permission, state
    - Known bugs: KB-013, KB-027
    - Notes: W-AUTOMERGE-AUTHOR-TEAM (P0): approver-authored PR: author_can_auto_merge true, has_required_approvals None, automerge comment without review, /otterdog merge merges and applies; an invalid PR of the same author is refused ('pull request is not valid').
- **`webapp-automerge.blockers`** (covered, P1, `webapp`): auto-merge is refused when the PR contains secrets, needs the web UI, may incur costs, includes deletions or touches non-configuration files
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:273-296`, `otterdog/webapp/db/models.py:151-158`
    - Operations: permission
    - Notes: Each blocker is asserted in the test of its change type (secret, cost, README/multi-file, deletion, web UI) with admin-authored (eligible) PRs: no automerge comment after quiesce, /otterdog merge refused with the supports_auto_merge sentence, PR open. No separate W-AUTOMERGE-BLOCKERS (would duplicate those PRs).
- **`webapp-automerge.third-party`** (covered, P1, `webapp`): /otterdog merge by someone else than the author requires approval/admin team membership ('Only the author of the pull request, a member of ..., or a member of ... is allowed to auto-merge.')
    - Source: `otterdog/webapp/tasks/merge_pull_request.py:66-83`
    - Operations: permission, comment
    - Known bugs: KB-027
    - Notes: W-AUTOMERGE-THIRD-PARTY (P1): approved contributor PR: the outsider's /otterdog merge -&gt; 'Only the author of the pull request, a member of ..., or a member of ... is allowed to auto-merge.', open; the approver's /otterdog merge -&gt; merged and applied.

<a id="webapp-runtime"></a>

## Webapp boot, init, API and pages

`webapp-runtime`: 16 features, 14 covered, 1 partial, 1 gaps (weighted 91%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `webapp-runtime.boot` | the webapp container boots with MongoDB and Valkey/Redis (dummy App credentials suffice), GET /internal/health answers 200, the /index footer shows 'OtterDog - v&lt;version&gt;' | offline | free | P0 | covered | offline | `tests/offline/test_webapp_contract.py::test_webapp_boots_with_dummy_credentials`, `tests/webapp/test_boot.py::test_webapp_boot` |
| `webapp-runtime.config` | environment configuration: GITHUB_APP_ID/PRIVATE_KEY, GITHUB_WEBHOOK_SECRET/ENDPOINT, validation and sync status contexts, GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS (regex patterns), OTTERDOG_CONFIG_OWNER/REPO/PATH/TOKEN, MONGO_URI, REDIS_URI, GHPROXY_URI, BLUEPRINT_CHECK_INTERVAL, DEPENDENCY_TRACK_URL/TOKEN, CACHE_CONTROL | webapp | free | P1 | covered | offline | `tests/offline/test_webapp_contract.py::test_webapp_boots_with_dummy_credentials`, `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_merge_apply.py::test_automerge_after_approval`, `tests/webapp/test_runtime.py::test_organization_teams_override_the_environment`, `tests/webapp/test_runtime.py::test_admin_teams_list_with_spaces`, `tests/webapp/test_blueprints.py::test_check_interval_and_limit`, `tests/webapp/test_policies.py::test_sbom_upload_to_dependency_track` |
| `webapp-runtime.init` | GET /internal/init: reload otterdog.json, global policies and blueprints from the configs repo, sync the installation list (orgs not installed are NOT_INSTALLED), refresh data of active installations | webapp | free | P0 | covered | **unverified** | `tests/webapp/test_boot.py::test_webapp_boot`, `tests/webapp/test_runtime.py::test_init_imports_existing_pull_requests`, `tests/webapp/test_policies.py::test_policy_definitions_are_loaded_and_merged`, `tests/webapp/test_blueprints.py::test_blueprint_definitions_are_loaded` |
| `webapp-runtime.fetch-all-pull-requests` | FetchAllPullRequestsTask (on init/installation refresh) imports the config repo's existing pull requests (only those targeting 'main') | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_runtime.py::test_init_imports_existing_pull_requests`, `tests/webapp/test_runtime.py::test_init_keeps_the_apply_status` |
| `webapp-runtime.internal-unknown` | GET /internal/&lt;anything else&gt; answers 404 {}; exceptions under /internal answer 500 {} | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_json_endpoints`, `tests/offline/test_webapp_runtime.py::test_database_outage` |
| `webapp-runtime.api-organizations` | GET /api/organizations ([{github_id, project_name}] of every installation row) and GET /api/organizations/&lt;github_id&gt; (stored configuration JSON, 404 until fetched) | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_boot.py::test_webapp_boot` |
| `webapp-runtime.api-projects` | GET /api/projects/&lt;project_name&gt;: the stored configuration by project name (404 for unknown projects) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_runtime.py::test_project_api` |
| `webapp-runtime.api-tasks` | GET /api/tasks: paged task records (type, org_id, repo_name, pull_request, status, cache_stats, rate_limit_remaining) with regex filters, pageIndex/pageSize/sortField/sortOrder | webapp | free | P1 | covered | **unverified** | `tests/webhooks/test_app_delivery.py::test_config_pr_delivery_is_relayed`, `tests/webapp/test_boot.py::test_webapp_boot` |
| `webapp-runtime.api-pullrequests` | GET /api/pullrequests/open (open + merged-not-completed) and /api/pullrequests/merged (merged and completed), paged with id[...] filters | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_valid_config_pr`, `tests/webapp/test_merge_apply.py::test_merge_applies_config`, `tests/webapp/test_stale_status.py::test_stale_snapshot_keeps_merged_status` |
| `webapp-runtime.api-statistics` | GET /api/pullrequests/statistics/progress?interval=day\|week\|month&range=7d\|14d\|30d\|90d\|6m\|12m\|all[&org=]: polled background job; 400 {'error': "unsupported interval '&lt;x&gt;'"} | offline | free | P2 | **partial** | offline | `tests/offline/test_webapp_contract.py::test_statistics_parameters` |
| `webapp-runtime.api-graphql` | GraphQL API: GET /api/graphql (explorer page), POST /api/graphql (queries over the stored data; invalid queries 400); /query page with the schema | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_graphql_api`, `tests/offline/test_webapp_contract.py::test_pages_need_no_login` |
| `webapp-runtime.pages-public` | public pages: / (redirect to /index), /robots.txt and /favicon.ico (static), /allprojects, /scorecard/checks, /&lt;name&gt;[.html] redirects to a known page or 404 page | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_redirects`, `tests/offline/test_webapp_contract.py::test_pages_need_no_login`, `tests/offline/test_webapp_contract.py::test_static_files`, `tests/offline/test_webapp_contract.py::test_not_found_page` |
| `webapp-runtime.pages-projects` | project pages: /organizations/&lt;org&gt;[/&lt;subpath&gt;] redirect to /projects/&lt;project&gt;[/&lt;subpath&gt;], /projects/&lt;project&gt; (+ /defaults, /playground, /repos/&lt;repo&gt;) render the stored configuration | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_runtime.py::test_project_and_admin_pages` |
| `webapp-runtime.pages-admin` | admin pages without login: /admin/organizations (installation status), /admin/pullrequests, /admin/blueprints, /admin/policies (aggregated policy status), /admin/tasks | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_pages_need_no_login`, `tests/offline/test_webapp_contract.py::test_admin_pages_of_an_empty_database`, `tests/webapp/test_runtime.py::test_project_and_admin_pages`, `tests/webapp/test_policies.py::test_macos_large_runner_jobs_are_cancelled_unless_allowed` |
| `webapp-runtime.login-required` | /myprojects needs a GitHub OAuth session: unauthenticated requests get the 401 page | offline | free | P2 | covered | offline | `tests/offline/test_webapp_contract.py::test_login_required_page_without_session`, `tests/offline/test_webapp_runtime.py::test_login_required_page_with_oauth_configured` |
| `webapp-runtime.oauth-login` | GitHub OAuth login: /login -&gt; /github (authorize) -&gt; /github/authorized (user and project memberships stored in the session) -&gt; /logout | web_ui | free | P2 | **gap** | - | - |

Details:

- **`webapp-runtime.boot`** (covered, P0, `offline`): the webapp container boots with MongoDB and Valkey/Redis (dummy App credentials suffice), GET /internal/health answers 200, the /index footer shows 'OtterDog - v&lt;version&gt;'
    - Source: `otterdog/app.py:21-68`, `otterdog/webapp/__init__.py:95-140`, `otterdog/webapp/internal/routes.py:33-35`, `otterdog/webapp/home/routes.py:61-150`
    - Operations: run, api
    - Known bugs: KB-061
- **`webapp-runtime.config`** (covered, P1, `webapp`): environment configuration: GITHUB_APP_ID/PRIVATE_KEY, GITHUB_WEBHOOK_SECRET/ENDPOINT, validation and sync status contexts, GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS (regex patterns), OTTERDOG_CONFIG_OWNER/REPO/PATH/TOKEN, MONGO_URI, REDIS_URI, GHPROXY_URI, BLUEPRINT_CHECK_INTERVAL, DEPENDENCY_TRACK_URL/TOKEN, CACHE_CONTROL
    - Source: `otterdog/webapp/config.py:15-112`, `otterdog/webapp/utils.py:315-423`
    - Operations: config
    - Known bugs: KB-012, KB-013
    - Notes: W-RT-CONFIG-TEAMS (P1): GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS point at a team that does not exist. The help comment names the otterdog.json org-entry teams ("approved by a member of team '&lt;approval&gt;'", `<org>/<admin>`). Once the entry drops them, it names the environment's (pattern '^x$' with the 'no team ... matches' note, `<org>/x`). Requires otterdog#715 (v1.5.0). W-RT-ADMIN-TEAMS-SPACES covers KB-013 (scoped xfail; approval patterns with spaces as the strict control). BLUEPRINT_CHECK_INTERVAL and DEPENDENCY_TRACK_URL/TOKEN are asserted by W-BP-CHECK and W-POL-SBOM. The GITHUB_WEBHOOK_ENDPOINT override is covered offline by tests/offline/test_webapp_runtime.py::test_webhook_endpoint_is_configurable.
- **`webapp-runtime.init`** (covered, P0, `webapp`): GET /internal/init: reload otterdog.json, global policies and blueprints from the configs repo, sync the installation list (orgs not installed are NOT_INSTALLED), refresh data of active installations
    - Source: `otterdog/webapp/internal/routes.py:38-51`, `otterdog/webapp/utils.py:136-312`, `otterdog/webapp/db/service.py:64-334`
    - Operations: api, state, config
    - Known bugs: KB-015, KB-074
    - Notes: Reloading global policies and blueprints on /internal/init is now asserted on the project page; init after a webapp restart refreshes PRs. The KB-015 push path is covered by W-BP-GLOBAL-PUSH.
- **`webapp-runtime.fetch-all-pull-requests`** (covered, P2, `webapp`): FetchAllPullRequestsTask (on init/installation refresh) imports the config repo's existing pull requests (only those targeting 'main')
    - Source: `otterdog/webapp/tasks/fetch_all_pull_requests.py:30-62`
    - Operations: task, state
    - Known bugs: KB-014, KB-074
    - Notes: W-RT-INIT-IMPORTS-PRS: the webapp service is stopped and the relay is shown to have failed (and dropped) the opened/closed deliveries. PRs opened or merged meanwhile are handled by the next /internal/init (FetchAllPullRequestsTask finished): the open PR is imported (open, draft false, not_applied, valid null, no bot comment; /otterdog validate then validates it), the merged PR is imported as merged and completed and never applied, and a PR against another base is not imported. KB-014: 'main' is hardcoded, which is consistent here because main is the config repo's default branch. KB-074 (W-RT-INIT-APPLY-STATUS): the re-import overwrites partially_applied with completed (non-strict xfail, scoped).
- **`webapp-runtime.internal-unknown`** (covered, P2, `offline`): GET /internal/&lt;anything else&gt; answers 404 {}; exceptions under /internal answer 500 {}
    - Source: `otterdog/webapp/internal/routes.py:96-106`
    - Operations: api, error
    - Notes: 404 {} for /internal/&lt;other&gt;; 500 {} for /internal/check during a MongoDB outage
- **`webapp-runtime.api-projects`** (covered, P2, `webapp`): GET /api/projects/&lt;project_name&gt;: the stored configuration by project name (404 for unknown projects)
    - Source: `otterdog/webapp/api/routes.py:53-59`
    - Operations: api
    - Notes: W-RT-API-PROJECTS: /api/projects/&lt;project&gt; == /api/organizations/&lt;org&gt; (read after quiesce); an unknown project or org answers 404 with body {}. Also verified offline against the 9bdeb75 image.
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
    - Source: `otterdog/webapp/api/routes.py:170-183`, `otterdog/webapp/home/routes.py:182-189`
    - Operations: api
    - Notes: Field names are snake_case (github_id), the outline's camelCase query answers 400
- **`webapp-runtime.pages-projects`** (covered, P2, `webapp`): project pages: /organizations/&lt;org&gt;[/&lt;subpath&gt;] redirect to /projects/&lt;project&gt;[/&lt;subpath&gt;], /projects/&lt;project&gt; (+ /defaults, /playground, /repos/&lt;repo&gt;) render the stored configuration
    - Source: `otterdog/webapp/home/routes.py:192-459`
    - Operations: api, state
    - Notes: W-RT-PAGES: /organizations/&lt;org&gt; -&gt; 302 /projects/&lt;project&gt;; /organizations/&lt;org&gt;/repos/&lt;repo&gt; -&gt; 302 /projects/&lt;project&gt;/repos/&lt;repo&gt;. The project page has the policies and blueprints tabs and the repo link; the repository page shows 'Repository &lt;repo&gt;'; /defaults shows the snippets orgs.newOrg('&lt;project-name&gt;', '&lt;github-id&gt;') = and orgs.newRepo('&lt;name&gt;') =; /playground shows the template in a textarea; unknown org, project and repo get the 404 HTML page; /allprojects lists the project. The redirect and 404 shapes were checked offline.
- **`webapp-runtime.pages-admin`** (covered, P2, `offline`): admin pages without login: /admin/organizations (installation status), /admin/pullrequests, /admin/blueprints, /admin/policies (aggregated policy status), /admin/tasks
    - Source: `otterdog/webapp/home/routes.py:462-509`
    - Operations: api, security
    - Notes: offline: the five admin pages render without a session on an empty database (O-WEB-ROUTES); live: the /admin/organizations row of the test org {installation id of the App, installed, project} (W-RT-PAGES) and the /admin/policies counters (W-POL-MACOS).
- **`webapp-runtime.login-required`** (covered, P2, `offline`): /myprojects needs a GitHub OAuth session: unauthenticated requests get the 401 page
    - Source: `otterdog/webapp/home/routes.py:153-166`, `otterdog/webapp/home/routes.py:522-524`
    - Operations: permission, api
    - Known bugs: KB-059
    - Notes: without OAuth configuration (the offline stack) /myprojects answers the 500 page instead of 401 (KB-059, O-KB-WEB-LOGIN-REQUIRED asserts the 401); the 401 page itself needs a stack with OAuth variables.
- **`webapp-runtime.oauth-login`** (gap, P2, `web_ui`): GitHub OAuth login: /login -&gt; /github (authorize) -&gt; /github/authorized (user and project memberships stored in the session) -&gt; /logout
    - Source: `otterdog/webapp/auth/routes.py:22-118`
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

## Blueprints

`blueprints`: 8 features, 6 covered, 2 partial, 0 gaps (weighted 88%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `blueprints.loading` | blueprint definitions: id, type, name, description, config; global ones de-duplicated by type (KB-076), a global id wins over an org definition with the same id; reloaded on push and init | webapp | free | P2 | **partial** | **unverified** | `tests/webapp/test_blueprints.py::test_blueprint_definitions_are_loaded`, `tests/webapp/test_blueprints.py::test_invalid_yaml_definition_does_not_block_the_others`, `tests/webapp/test_blueprints.py::test_global_definitions_reload_on_configs_push`, `tests/webapp/test_blueprints.py::test_changed_definition_is_stored_by_one_fetch`, `tests/webapp/test_blueprints.py::test_changed_type_keeps_the_check_working`, `tests/webapp/test_blueprints.py::test_changed_definition_is_rechecked_after_another_fetch` |
| `blueprints.required-file` | required_file: repositories matching repo_selector.name_pattern must contain files (mustache content; strict files are rewritten in an existing remediation branch) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_required_file_remediation` |
| `blueprints.pin-workflow` | pin_workflow: workflow 'uses:' references are pinned to commit SHAs (comment keeps the tag) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_pin_workflow_remediation` |
| `blueprints.append-configuration` | append_configuration: when the JSONata condition holds on the org configuration, a PR on the config repo appends the rendered snippet (reviewers requested) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_append_configuration_remediation` |
| `blueprints.scorecard-integration` | scorecard_integration: matching repositories need the OSSF scorecard workflow (PR with workflow_content); results are synced and served by /api/scorecard/results and /scorecard/checks | webapp | free | P2 | **partial** | **unverified** | `tests/webapp/test_blueprints.py::test_scorecard_integration_remediation` |
| `blueprints.status-and-dismissal` | remediation PR lifecycle: open -&gt; REMEDIATION_PREPARED, merged -&gt; RECHECK, closed unmerged -&gt; DISMISSED with a blueprint-dismissal comment (reopen reinstates); /api/blueprints/dismissed | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint`, `tests/webapp/test_blueprints.py::test_required_file_remediation` |
| `blueprints.remediations-api` | GET /api/blueprints/remediations: blueprint statuses with an open remediation PR (read by the CLI list-blueprints / approve-blueprints) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_required_file_remediation`, `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint` |
| `blueprints.check-endpoint` | GET /internal/check[/&lt;limit&gt;] evaluates up to &lt;limit&gt; (default 50) blueprints whose last check is older than BLUEPRINT_CHECK_INTERVAL (forced rechecks reset) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_check_interval_and_limit`, `tests/webapp/test_blueprints.py::test_changed_type_keeps_the_check_working` |

Details:

- **`blueprints.loading`** (partial, P2, `webapp`): blueprint definitions: id, type, name, description, config; global ones de-duplicated by type (KB-076), a global id wins over an org definition with the same id; reloaded on push and init
    - Source: `otterdog/webapp/blueprints/__init__.py:116-170`, `otterdog/webapp/tasks/fetch_blueprints.py:39-94`, `otterdog/webapp/webhook/__init__.py:305-315`
    - Operations: config, task, state
    - Known bugs: KB-015, KB-069, KB-070, KB-071, KB-072, KB-076
    - Notes: W-BP-LOAD (strict): org definitions load with a push to config repo main (push delivery -&gt; FetchBlueprintsTask -&gt; project page card: name, Reference URL .../blob/main/otterdog/blueprints/&lt;id&gt;.yml, config); a definition without 'type' is logged ('failed reading blueprint from path ...') and skipped; /internal/init loads a global definition; the global definition beats a later org definition with the same id ('duplicate blueprint with id ... skipping'); removing an org file unloads it. Known bugs: KB-015 (W-BP-GLOBAL-PUSH), KB-069 (W-BP-LOAD-YAML), KB-070 (W-BP-UPDATE), KB-071 (W-BP-RECHECK-LOST), KB-072 (W-BP-TYPE-CHANGE), KB-076 (two global definitions of one type, untested).
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
- **`blueprints.pin-workflow`** (covered, P2, `webapp`): pin_workflow: workflow 'uses:' references are pinned to commit SHAs (comment keeps the tag)
    - Source: `otterdog/webapp/blueprints/pin_workflow.py:23-60`, `otterdog/webapp/tasks/blueprints/pin_workflow.py:25-147`
    - Operations: task, modify
    - Known bugs: KB-073
    - Notes: W-BP-PIN: the PR changes exactly one line: 'actions/checkout@v4' -&gt; '@&lt;40-hex&gt; # v4.x.y'. The sha is checked against GET /repos/actions/checkout/commits/&lt;tag&gt;. '# ignore', '@main' and local actions are kept. Merge -&gt; success. The last step is KB-073 (a docker:// step makes otterdog skip the whole workflow), a non-strict xfail limited to DockerActionPinningError.
- **`blueprints.append-configuration`** (covered, P2, `webapp`): append_configuration: when the JSONata condition holds on the org configuration, a PR on the config repo appends the rendered snippet (reviewers requested)
    - Source: `otterdog/webapp/blueprints/append_configuration.py:26-80`, `otterdog/webapp/tasks/blueprints/append_configuration.py:23-145`
    - Operations: task, modify, validate
    - Notes: the Eclipse '.github' snippet blueprint appears in 199 org files as an appended '} + {' block. W-BP-APPEND: config-repo PR from otterdog/blueprint/&lt;id&gt;. Its otterdog/&lt;org&gt;.jsonnet is main.rstrip() + ' + ' + the rendered snippet ({{blueprint_id}}, {{github_id}}); the snippet was checked offline with rjsonnet. Review is requested from the approval team (requested_reviewers). The webapp validates it (status + validate comment naming the new repo). It is merged through the guarded ConfigRepoFlow and applied (repository created with the rendered description), then the stored config declares it and the blueprint reports success.
- **`blueprints.scorecard-integration`** (partial, P2, `webapp`): scorecard_integration: matching repositories need the OSSF scorecard workflow (PR with workflow_content); results are synced and served by /api/scorecard/results and /scorecard/checks
    - Source: `otterdog/webapp/blueprints/scorecard_integration.py:24-83`, `otterdog/webapp/tasks/blueprints/check_scorecard_integration.py:27-125`, `otterdog/webapp/tasks/blueprints/sync_scorecard_result.py:25-62`, `otterdog/webapp/api/routes.py:156-167`
    - Operations: task, add, api
    - Notes: W-BP-SCORECARD: the PR adds .github/workflows/scorecard-analysis.yml (default workflow_name) rendered from workflow_content. Merge -&gt; success (a workflow using ossf/scorecard-action is found). The next check runs SyncScorecardResultTask (finished). /api/scorecard/results stays empty and the repo page has no scorecard.dev link for a repo without published results.
    - Suggested: `W-BP-SCORECARD-RESULT` in `tests/webapp/test_blueprints.py`
    - Steps:
        - a repository with published scorecard results (or a scorecard API mock); /internal/check
    - Assert:
        - a stored result: score per check in /api/scorecard/results and /scorecard/checks
    - Needs:
        - webapp
        - harness: a repository with published results or a redirect of api.securityscorecards.dev (hardcoded, sync_scorecard_result.py)
- **`blueprints.status-and-dismissal`** (covered, P2, `webapp`): remediation PR lifecycle: open -&gt; REMEDIATION_PREPARED, merged -&gt; RECHECK, closed unmerged -&gt; DISMISSED with a blueprint-dismissal comment (reopen reinstates); /api/blueprints/dismissed
    - Source: `otterdog/webapp/tasks/blueprints/update_blueprint_status.py:45-80`, `otterdog/webapp/tasks/blueprints/__init__.py:31-118`, `otterdog/webapp/api/routes.py:149-153`, `otterdog/webapp/db/service.py:1106`
    - Operations: task, state, comment, api
    - Known bugs: KB-075
    - Notes: W-BP-DISMISS: closing the PR -&gt; UpdateBlueprintStatusTask -&gt; dismissed (row keeps the PR number), bot comment with the blueprint-dismissal marker 'The blueprint `<id>` has been dismissed for this repo.', branch deleted by the webapp, listed by /api/blueprints/dismissed and no longer by remediations. A check evaluates nothing and opens no new PR. Reopen (branch recreated first) -&gt; remediation_prepared. A second close minimizes the first dismissal comment. A lost status (definition removed and re-added) is restored to dismissed from the closed PR on GitHub, with no new PR: the regression of otterdog#766 (16f7f32, v1.6.0), a strict xfail limited to DismissalLostError on older webapps. Merge -&gt; recheck/success is covered in W-BP-REQUIRED-FILE.
- **`blueprints.remediations-api`** (covered, P2, `webapp`): GET /api/blueprints/remediations: blueprint statuses with an open remediation PR (read by the CLI list-blueprints / approve-blueprints)
    - Source: `otterdog/webapp/api/routes.py:142-146`, `otterdog/webapp/db/service.py:1046`
    - Operations: api
    - Known bugs: KB-075
    - Notes: Rows {id.org_id, id.repo_name, id.blueprint_id, remediation_pr} with the id[blueprint_id] filter while the PR is open; gone after the merge or the dismissal (W-BP-REQUIRED-FILE, W-BP-DISMISS). The CLI consumers are cli.list-blueprints / cli.approve-blueprints (W-CLI-BLUEPRINTS). updated_at is never refreshed (KB-075).
- **`blueprints.check-endpoint`** (covered, P2, `webapp`): GET /internal/check[/&lt;limit&gt;] evaluates up to &lt;limit&gt; (default 50) blueprints whose last check is older than BLUEPRINT_CHECK_INTERVAL (forced rechecks reset)
    - Source: `otterdog/webapp/internal/routes.py:54-93`
    - Operations: api, task
    - Known bugs: KB-072
    - Notes: W-BP-CHECK uses append_configuration blueprints whose condition is not a boolean (status failure, no GitHub writes, one AppendConfigurationTask per evaluation of the config repo). With BLUEPRINT_CHECK_INTERVAL=3600 (webapp_env) /internal/check evaluates nothing and logs "skipping blueprint with id '&lt;id&gt;' for org '&lt;org&gt;', last checked at ..." (compose). Back at 0: /internal/check/1 evaluates only the never-checked blueprint, /internal/check all three. Requires otterdog#766. Validated offline against the 9bdeb75 image with a seeded database. W-BP-TYPE-CHANGE shows the failure mode where /internal/check answers 500.

## Policies

`policies`: 3 features, 3 covered, 0 partial, 0 gaps (weighted 100%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `policies.loading` | policy definitions (type, name, description, config) from the configs repo (policies/\*.yml) and the config repo (otterdog/policies/\*.yml, merged over the global one) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_policies.py::test_policy_definitions_are_loaded_and_merged`, `tests/webapp/test_policies.py::test_malformed_policy_does_not_block_the_others` |
| `policies.macos-large-runners` | macos_large_runners: queued jobs on 'macos\*large' runners are cancelled unless allowed; counters total_workflow_jobs, permitted/cancelled_on_restricted_runners | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_policies.py::test_macos_large_runner_jobs_are_cancelled_unless_allowed` |
| `policies.dependency-track-upload` | dependency_track_upload: a successful workflow run referencing workflow_filter uploads the SBOM artifact (bom.json + metadata.json) to DEPENDENCY_TRACK_URL /api/v1/bom | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_policies.py::test_sbom_upload_to_dependency_track` |

Details:

- **`policies.loading`** (covered, P2, `webapp`): policy definitions (type, name, description, config) from the configs repo (policies/\*.yml) and the config repo (otterdog/policies/\*.yml, merged over the global one)
    - Source: `otterdog/webapp/policies/__init__.py:21-118`, `otterdog/webapp/tasks/fetch_policies.py:39-87`, `otterdog/webapp/webhook/__init__.py:293-303`
    - Operations: config, task, state
    - Known bugs: KB-069
    - Notes: W-POL-LOAD: global macos_large_runners and dependency_track_upload policies load on /internal/init (project page cards: name or 'Overview', Reference URL, config parsed from PrettyFormatter). Org policies pushed to config repo main merge over them: path and name from the org file, the global description kept when the org sets none, allowed and workflow_filter from the org, artifact_name always from the global one (Policy.merge). Removing the org macos file restores the global values. KB-069 (W-POL-LOAD-MALFORMED): a file without 'type' fails FetchPoliciesTask (non-strict xfail, scoped).
- **`policies.macos-large-runners`** (covered, P2, `webapp`): macos_large_runners: queued jobs on 'macos\*large' runners are cancelled unless allowed; counters total_workflow_jobs, permitted/cancelled_on_restricted_runners
    - Source: `otterdog/webapp/policies/macos_large_runners.py:21-79`, `otterdog/webapp/webhook/__init__.py:351-385`
    - Operations: event, task, state
    - Notes: W-POL-MACOS: allowed false -&gt; the workflow_job queued delivery is forwarded, the App cancels the run (conclusion cancelled), cancelled_on_restricted_runners +1, total_workflow_jobs +1, permitted unchanged (/admin/policies). allowed true -&gt; permitted_on_restricted_runners +1, cancelled unchanged, the run is still queued, and the harness cancels it. Skips where the org has larger runners (billing guard).
- **`policies.dependency-track-upload`** (covered, P2, `webapp`): dependency_track_upload: a successful workflow run referencing workflow_filter uploads the SBOM artifact (bom.json + metadata.json) to DEPENDENCY_TRACK_URL /api/v1/bom
    - Source: `otterdog/webapp/policies/dependency_track_upload.py:23-81`, `otterdog/webapp/tasks/policies/upload_sbom.py:1-119`, `otterdog/webapp/webhook/__init__.py:388-420`
    - Operations: event, task
    - Notes: W-POL-SBOM (dtrack_mock): a successful run of the caller of the reusable store workflow -&gt; workflow_run completed -&gt; UploadSBOMTask finished -&gt; PUT /api/v1/bom with X-Api-Key e2e-dummy\*, application/json, {projectName, projectVersion 1.0.0, parentUUID default, autoCreate true, bom == the CycloneDX document}. A non-matching workflow_filter -&gt; no UploadSBOMTask and no upload. The mock answering 500 -&gt; UploadSBOMTask failed ('failed to upload SBOM').

<a id="regressions"></a>

## CHANGELOG fixes (regression guards)

`regressions`: 32 features, 27 covered, 4 partial, 1 gaps (weighted 91%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `regression.790-ruleset-status-checks-strict` | #790 (9bdeb75, after v1.6.1): ruleset status checks without 'strict' are a validation error instead of an apply failure | offline | free | P1 | covered | offline | `O-VAL-RULESET-STRICT`, `regression.repo-ruleset-without-strict`, `O-VAL-ORG-RULESET-STRICT`, `enterprise.org-ruleset.missing-strict`, `tests/differential/test_offline_diff.py::test_change_expected_deltas_observed` |
| `regression.791-code-scanning-new-repos` | #791 (b5f7bb1): code scanning of new repositories is only disabled when it is configured (private repositories without Code Security) | cli | free | P1 | **partial** | **unverified** | `regression.private-repo-template-defaults` |
| `regression.779-user-bypass-actors` | #779 (f055d51): individual users ('@login') as ruleset bypass actors | cli | free | P2 | **partial** | **unverified** | `regression.user-bypass-actors` |
| `regression.775-unformattable-webhook-events` | #775 (5466db5): webhook events whose payload cannot be formatted for the log are still processed | offline | free | P1 | covered | offline | `tests/offline/test_webapp_contract.py::test_unformattable_events_are_still_processed`, `tests/offline/test_webapp_contract.py::test_rejections_name_what_is_wrong`, `tests/offline/test_webapp_contract.py::test_optional_headers` |
| `regression.773-rebase-merge-commits` | #773 (ba3d1f9): every commit of a rebase-merged pull request is applied (base = parent of the first rebased commit) | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_merge_apply.py::test_rebase_merge_applies_every_commit` |
| `regression.771-warning-wording` | #771 (476bf5e): validation comment warnings read 'some of the requested changes ...' (secrets, Web UI, costs) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_pr_validation.py::test_validation_warnings` |
| `regression.767-code-scanning-languages-new-repo` | #767 (8e3a359): code_scanning_default_languages on a repository that does not exist yet is a validation error | cli | free | P1 | **partial** | **unverified** | `regression.code-scanning-new-repo` |
| `regression.770-cost-automerge` | #770 (v1.6.1): cost-related changes (max_cache_size_gb) are excluded from auto-merge | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_pr_validation.py::test_validation_warnings` |
| `regression.766-blueprint-dismissed` | #766 (v1.6.0): a dismissed blueprint stays dismissed (stored status or a closed remediation PR found on GitHub) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_blueprints.py::test_closed_remediation_dismisses_the_blueprint` |
| `regression.765-out-of-sync-warning` | #765 (v1.6.0): the out-of-sync comment is a '&gt; [!WARNING]' alert (was [!NOTE]) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_commands.py::test_drift_check_sync` |
| `regression.751-disabled-ruleset-conditions` | #751 (v1.6.0): disabled rulesets whose conditions are null converge | cli | free | P2 | covered | **unverified** | `regression.disabled-ruleset-without-refs` |
| `regression.731-private-repo-rulesets` | #731 (v1.5.0): rulesets of private repositories on plans without them (403/404) are tolerated | cli | free | P1 | covered | **unverified** | `regression.private-repo-template-defaults`, `cli.neg.private-ruleset` |
| `regression.718-unknown-properties` | #718 (v1.5.0): unknown properties only warn ('ignoring unknown properties found while validating organization config: ...') | offline | free | P1 | covered | offline | `O-VAL-SCHEMA` |
| `regression.713-already-deleted-branch` | #713 (v1.5.0): deleting an otterdog/\* branch GitHub already deleted (delete_branch_on_merge) is not an error | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_otterdog_branches.py::test_otterdog_branches_are_deleted` |
| `regression.712-fail-fast-configuration` | #712 (v1.5.0) and v1.3.2: the webapp refuses to start when required settings are missing or empty (GITHUB_WEBHOOK_SECRET); values are stripped (#677) | offline | free | P1 | **partial** | offline | `tests/offline/test_webapp_runtime.py::test_required_setting_is_refused_at_boot`, `tests/offline/test_webapp_runtime.py::test_refused_boot_exits_non_zero` |
| `regression.699-token-only-operations` | #693 / #699 (v1.4.0): operations that do not need the web UI never read web credentials (token-only env credentials work) | cli | free | P0 | covered | **unverified** | `cli.repo.lifecycle`, `tests/cli/test_smoke.py::test_check_token_permissions` |
| `regression.695-700-491-status-check-mapping` | #491 (v1.1.1), #695, #700 (v1.4.0): ruleset status checks map app slugs and integration ids both ways (org rulesets return only integration_id) | cli | free | P1 | covered | **unverified** | `cli.ruleset.public`, `cli.ruleset.status-checks`, `cli.protection.app-checks` |
| `regression.691-open-pr-author` | #691 (v1.4.0): open-pr requires --author | cli | free | P2 | covered | offline | `tests/cli/test_config_repo_cli.py::test_open_pr`, `tests/offline/test_cli_basics.py::test_usage_errors_exit_2`, `tests/cli/test_commands_config_repo.py::test_open_pr_opens_nothing_when_it_must_not` |
| `regression.685-pin-invalid-workflow` | #685 (v1.4.0): PinWorkflowTask skips workflow files with invalid YAML | webapp | free | P2 | **gap** | - | - |
| `regression.675-ruleset-unset-defaults` | #675 (v1.3.4): ruleset values left UNSET by the template default are rendered and compared correctly (import round trip) | cli | free | P2 | covered | **unverified** | `tests/cli/test_import.py::test_import_plans_no_change`, `tests/cli/test_protection_import.py::test_imported_protections_plan_no_change` |
| `regression.653-string-property` | #653 (v1.3.4): no allowed_values are sent for string / true_false custom properties | cli | free | P2 | covered | **unverified** | `cli.custom-property`, `cli.custom-property.flag` |
| `regression.635-fork-pr-private` | #635 (v1.3.1): fork PR approval calls are skipped for private repositories (GitHub 422) | cli | free | P1 | covered | **unverified** | `regression.private-repo-template-defaults`, `cli.repo.visibility`, `cli.org.member-privileges` |
| `regression.603-automerge-problems-comment` | #603 (v1.3.0): a refused /otterdog merge answers with the automerge problems comment | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply` |
| `regression.nested-dict-printing` | v1.3.0: changes of nested dicts (workflows, team_permissions) print as nested '\~ key = {' blocks | offline | free | P2 | covered | offline | `O-LPLAN-NESTED` |
| `regression.in-sync-not-required` | v1.2.0 / v1.1.0: an out-of-sync organization neither blocks auto-merge nor fails the sync status | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_commands.py::test_drift_check_sync`, `tests/webapp/test_merge_apply.py::test_drifted_org_still_auto_merges` |
| `regression.562-empty-status-checks` | #562 (v1.2.0): rulesets with empty status_checks are created without a required_status_checks rule | cli | free | P1 | covered | **unverified** | `regression.ruleset-empty-status-checks` |
| `regression.472-rename-and-modify` | #472 (v1.1.1): renaming a repository and modifying it in one apply | cli | free | P1 | covered | **unverified** | `regression.rename-and-modify` |
| `regression.450-pages-required-fields` | #450 (v1.1.0): GitHub Pages updates send the required fields together | cli | free | P2 | covered | **unverified** | `cli.repo.pages` |
| `regression.440-rich-escaping` | #440 (v1.1.0): values containing rich markup ('[bold]', '[/]') are printed literally | offline | free | P2 | covered | offline | `O-LPLAN-ESCAPING`, `tests/offline/test_cli_markup.py::test_validation_messages_quote_values_literally` |
| `regression.458-411-435-code-scanning-live` | #411, #435, #458: 'actions' is a valid code scanning language, invalid CodeQL languages from the API are filtered, live code scanning settings compare with the expected default setup | cli | free | P2 | covered | **unverified** | `tests/cli/test_repo_code_scanning.py::test_code_scanning_default_setup` |
| `regression.import-multiple-custom-properties` | v1.0.1: importing an organization with several custom properties | cli | free | P2 | covered | **unverified** | `tests/cli/test_repo_import.py::test_imported_custom_properties_plan_no_change` |
| `regression.local-apply-teams-webhooks` | v1.0.1 / #325 / #330: local-apply (the webapp's apply) updates teams, handles wildcard webhooks and skips web-UI settings | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_web_ui_flags.py::test_web_ui_setting_needs_a_manual_apply`, `tests/webapp/test_merge_apply.py::test_team_and_wildcard_webhook_are_applied` |

Details:

- **`regression.790-ruleset-status-checks-strict`** (covered, P1, `offline`): #790 (9bdeb75, after v1.6.1): ruleset status checks without 'strict' are a validation error instead of an apply failure
    - Source: `otterdog/models/ruleset.py:128-136`, `otterdog/models/ruleset.py:451-458`
    - Operations: validate
    - Known bugs: KB-008
- **`regression.791-code-scanning-new-repos`** (partial, P1, `cli`): #791 (b5f7bb1): code scanning of new repositories is only disabled when it is configured (private repositories without Code Security)
    - Source: `otterdog/providers/github/rest/repo_client.py:464-486`
    - Operations: add, converge
    - Suggested: `regression.private-repo-template-defaults`
    - Steps:
        - regression.private-repo-template-defaults declares fixed_in 1.7.0.dev14: it runs on SUTs containing the fix (branch:main, PR builds) and is skipped on release:latest
    - Assert:
        - covered on the default SUT once a release contains the fix (otterdog &gt;= 1.7.0.dev14)
    - Needs:
        - an otterdog release &gt;= 1.7.0.dev14
- **`regression.779-user-bypass-actors`** (partial, P2, `cli`): #779 (f055d51): individual users ('@login') as ruleset bypass actors
    - Source: `otterdog/models/ruleset.py:655-662`, `otterdog/models/ruleset.py:542-553`
    - Operations: add, converge
    - Notes: fixed_in 1.7.0.dev7 (f055d51 = v1.6.1 + 7). The user actor in the default mode, then pull_request mode, converging; skips on release:latest.
    - Suggested: `regression.user-bypass-actors`
    - Steps:
        - regression.user-bypass-actors declares fixed_in 1.7.0.dev7: it runs on SUTs containing the fix (branch:main, PR builds) and is skipped on release:latest
    - Assert:
        - covered on the default SUT once a release contains the fix (otterdog &gt;= 1.7.0.dev7)
    - Needs:
        - an otterdog release &gt;= 1.7.0.dev7
- **`regression.775-unformattable-webhook-events`** (covered, P1, `offline`): #775 (5466db5): webhook events whose payload cannot be formatted for the log are still processed
    - Source: `otterdog/webapp/webhook/github_webhook.py:123-147`
    - Operations: event
    - Notes: Decided by ancestry of 5466db5 in the webapp image revision: with the fix 204 + warning + processed; v1.6.1 500 and the event dropped (both verified)
- **`regression.771-warning-wording`** (covered, P2, `webapp`): #771 (476bf5e): validation comment warnings read 'some of the requested changes ...' (secrets, Web UI, costs)
    - Source: `otterdog/webapp/tasks/validate_pull_request.py:196-205`
    - Operations: comment
    - Notes: Exact secrets and cost wordings: 'some of the requested changes ...' when the webapp includes 476bf5e, 'some of requested changes ...' when it predates it, either when unknown.
- **`regression.767-code-scanning-languages-new-repo`** (partial, P1, `cli`): #767 (8e3a359): code_scanning_default_languages on a repository that does not exist yet is a validation error
    - Source: `otterdog/models/github_organization.py:229-262`, `otterdog/models/repository.py:318-323`
    - Operations: validate
    - Suggested: `regression.code-scanning-new-repo`
    - Steps:
        - regression.code-scanning-new-repo declares fixed_in 1.7.0.dev2: it runs on SUTs containing the fix (branch:main, PR builds) and is skipped on release:latest
    - Assert:
        - covered on the default SUT once a release contains the fix (otterdog &gt;= 1.7.0.dev2)
    - Needs:
        - an otterdog release &gt;= 1.7.0.dev2
- **`regression.770-cost-automerge`** (covered, P1, `webapp`): #770 (v1.6.1): cost-related changes (max_cache_size_gb) are excluded from auto-merge
    - Source: `CHANGELOG.md:7`, `otterdog/webapp/tasks/validate_pull_request.py:279-286`
    - Operations: permission
    - Notes: Cost change: warning, supports_auto_merge false, no automerge comment, refusal naming 'may incur costs'; new repo with the default 10 GB stays auto-mergeable (automerge comment). Strict xfail (CostAutoMergeRegressionError) on webapps without c4f75eb.
- **`regression.766-blueprint-dismissed`** (covered, P2, `webapp`): #766 (v1.6.0): a dismissed blueprint stays dismissed (stored status or a closed remediation PR found on GitHub)
    - Source: `CHANGELOG.md:37`, `otterdog/webapp/tasks/blueprints/__init__.py:31-86`
    - Operations: task, state
    - Notes: W-BP-DISMISS: a dismissed blueprint whose status is lost (definition removed and re-added) is restored to dismissed from the closed remediation PR on GitHub and no new PR is opened (strict xfail limited to DismissalLostError on webapps without 16f7f32).
- **`regression.765-out-of-sync-warning`** (covered, P2, `webapp`): #765 (v1.6.0): the out-of-sync comment is a '&gt; [!WARNING]' alert (was [!NOTE])
    - Source: `CHANGELOG.md:36`, `otterdog/webapp/templates/comment/out_of_sync_comment.txt:1-3`
    - Operations: comment
    - Notes: The check-sync comment starts with its marker line followed by '&gt; [!WARNING]' when the webapp includes 975cf1b ('&gt; [!NOTE]' before, either when unknown).
- **`regression.718-unknown-properties`** (covered, P1, `offline`): #718 (v1.5.0): unknown properties only warn ('ignoring unknown properties found while validating organization config: ...')
    - Source: `CHANGELOG.md:75`, `otterdog/models/github_organization.py:266-296`
    - Operations: validate
    - Notes: step unknown-properties-ignored of O-VAL-SCHEMA: 'ignoring unknown properties found while validating organization config: Additional properties are not allowed (...)' and 'Validation succeeded' on v1.6.1 and 9bdeb75.
- **`regression.713-already-deleted-branch`** (covered, P2, `webapp`): #713 (v1.5.0): deleting an otterdog/\* branch GitHub already deleted (delete_branch_on_merge) is not an error
    - Source: `CHANGELOG.md:71`, `otterdog/webapp/tasks/delete_branch.py:29-42`
    - Operations: task
    - Notes: Second open-pr PR: the harness deletes otterdog/e2e-&lt;run&gt;-\* first (GitHub closes the PR, flow.close is a no-op then), the closed delivery arrives with the branch gone, the DeleteBranchTask must finish (strict xfail DeletedBranchRegressionError before 2bbd1a4). No delete_branch_on_merge drift needed.
- **`regression.712-fail-fast-configuration`** (partial, P1, `offline`): #712 (v1.5.0) and v1.3.2: the webapp refuses to start when required settings are missing or empty (GITHUB_WEBHOOK_SECRET); values are stripped (#677)
    - Source: `CHANGELOG.md:69`, `CHANGELOG.md:131`, `CHANGELOG.md:115`, `otterdog/webapp/config.py:15-24`, `otterdog/webapp/webhook/github_webhook.py:35-37`
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
    - Source: `CHANGELOG.md:101`, `CHANGELOG.md:104`, `otterdog/operations/diff_operation.py:131-132`
    - Operations: config, security
    - Known bugs: KB-002
    - Notes: every live CLI run provides only api_token (no username, password or TOTP)
- **`regression.695-700-491-status-check-mapping`** (covered, P1, `cli`): #491 (v1.1.1), #695, #700 (v1.4.0): ruleset status checks map app slugs and integration ids both ways (org rulesets return only integration_id)
    - Source: `CHANGELOG.md:187`, `CHANGELOG.md:102`, `CHANGELOG.md:105`, `otterdog/models/ruleset.py:141-227`
    - Operations: add, converge
    - Known bugs: KB-051, KB-054
    - Notes: #700 (integration id of an app that is not installed: 15368) and #491/#695 (installed App slug sent as integration_id and read back as the slug) are strict. The outline's expectation that '&lt;installed app id&gt;:&lt;ctx&gt;' converges is wrong: it never converges (KB-054 known-bug step).
- **`regression.691-open-pr-author`** (covered, P2, `cli`): #691 (v1.4.0): open-pr requires --author
    - Source: `CHANGELOG.md:90`, `otterdog/cli.py:333-344`
    - Operations: run, exit-code
    - Notes: offline: open-pr without -a is a click usage error (exit 2, "Missing option '-a'") before any configuration is loaded; live: an author that is no GitHub user exits 2 ('author ... is not a valid GitHub user') and opens nothing.
- **`regression.685-pin-invalid-workflow`** (gap, P2, `webapp`): #685 (v1.4.0): PinWorkflowTask skips workflow files with invalid YAML
    - Source: `CHANGELOG.md:99`, `otterdog/webapp/tasks/blueprints/pin_workflow.py:31-66`
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
    - Source: `CHANGELOG.md:113`, `otterdog/models/ruleset.py:460-495`
    - Operations: import, converge
    - Notes: Imports a repository with a BPR, a branch ruleset (partial pull_request, status checks, merge queue, bypass actors) and a tag ruleset (pull_request/status checks null). Checks the imported spelling, then plans the cut-out repository block with the baseline: noop (round trip checked offline with otterdog's writer).
- **`regression.653-string-property`** (covered, P2, `cli`): #653 (v1.3.4): no allowed_values are sent for string / true_false custom properties
    - Source: `CHANGELOG.md:114`, `otterdog/models/custom_property.py:177-179`
    - Operations: add
    - Notes: string properties (cli.custom-property) and true_false properties (cli.custom-property.flag) are created without allowed_values and converge.
- **`regression.635-fork-pr-private`** (covered, P1, `cli`): #635 (v1.3.1): fork PR approval calls are skipped for private repositories (GitHub 422)
    - Source: `CHANGELOG.md:143`, `otterdog/providers/github/rest/repo_client.py:1314-1338`
    - Operations: add, converge
    - Notes: Released in v1.3.1: cli.repo.visibility and cli.org.member-privileges plan, apply and converge private repositories (created public, then made private: #791) on release:latest, so the fork PR approval reads and patches of private repositories run there; regression.private-repo-template-defaults (fixed_in 1.7.0.dev14) also creates one directly.
- **`regression.nested-dict-printing`** (covered, P2, `offline`): v1.3.0: changes of nested dicts (workflows, team_permissions) print as nested '\~ key = {' blocks
    - Source: `CHANGELOG.md:161`, `otterdog/operations/plan.py:90-101`
    - Operations: plan
    - Notes: verified offline: repository workflows+ {allowed_actions: 'local_only'} prints '\~ workflows = {', '\~ allowed_actions = "all" -&gt; "local_only"', '\~ }'. scenarios/offline/plan/lplan-nested.yaml: repo workflows, org workflows, team_permissions value change and added entry
- **`regression.in-sync-not-required`** (covered, P1, `webapp`): v1.2.0 / v1.1.0: an out-of-sync organization neither blocks auto-merge nor fails the sync status
    - Source: `CHANGELOG.md:171`, `CHANGELOG.md:203`, `otterdog/webapp/db/models.py:117-200`
    - Operations: permission, status
    - Known bugs: KB-019
    - Notes: W-AUTOMERGE-DRIFT (P1): drifted run repo: check-sync comment, 'sync check failed' with state success, /api in_sync false, automerge comment, /otterdog merge merges, the apply names only the added repo and the drifted description stays on GitHub.
- **`regression.562-empty-status-checks`** (covered, P1, `cli`): #562 (v1.2.0): rulesets with empty status_checks are created without a required_status_checks rule
    - Source: `CHANGELOG.md:175`, `otterdog/models/ruleset.py:171-173`
    - Operations: add
    - Known bugs: KB-021
- **`regression.450-pages-required-fields`** (covered, P2, `cli`): #450 (v1.1.0): GitHub Pages updates send the required fields together
    - Source: `CHANGELOG.md:208`, `otterdog/providers/github/rest/repo_client.py:501-566`
    - Operations: modify
    - Notes: source-path step: only gh_pages_source_path changes (1 change); apply ok and oracle source {branch main, path /docs}.
- **`regression.440-rich-escaping`** (covered, P2, `offline`): #440 (v1.1.0): values containing rich markup ('[bold]', '[/]') are printed literally
    - Source: `CHANGELOG.md:209`, `otterdog/models/__init__.py:566-588`
    - Operations: plan
    - Known bugs: KB-050
    - Notes: scenarios/offline/cli/lplan-escaping.yaml: additions, changes and show print markup literally; validation messages do not
- **`regression.458-411-435-code-scanning-live`** (covered, P2, `cli`): #411, #435, #458: 'actions' is a valid code scanning language, invalid CodeQL languages from the API are filtered, live code scanning settings compare with the expected default setup
    - Source: `CHANGELOG.md:235`, `CHANGELOG.md:214`, `CHANGELOG.md:210`, `otterdog/providers/github/rest/repo_client.py:568-590`
    - Operations: converge, validate
    - Notes: languages ['actions','python'] validate (no 'not detected' message), apply, and converge.
- **`regression.import-multiple-custom-properties`** (covered, P2, `cli`): v1.0.1: importing an organization with several custom properties
    - Source: `CHANGELOG.md:237`, `otterdog/models/organization_settings.py:222-239`
    - Operations: import
    - Notes: Three definitions (single_select, string, true_false) plus repository values; checks the imported spelling, then the blocks plan noop with the baseline (requires custom_properties).
- **`regression.local-apply-teams-webhooks`** (covered, P2, `webapp`): v1.0.1 / #325 / #330: local-apply (the webapp's apply) updates teams, handles wildcard webhooks and skips web-UI settings
    - Source: `CHANGELOG.md:238`, `CHANGELOG.md:320`, `CHANGELOG.md:319`, `otterdog/operations/local_apply.py:24-90`
    - Operations: modify, task
    - Known bugs: KB-068
    - Notes: W-MERGE-TEAM-HOOK (P2): run team + run repo whose hook url carries a token, declared on main with '&lt;prefix&gt;\*' (trusted CLI then reset_main): the merged PR's team description is applied (strict); the wildcard webhook update loses the live url (scoped xfail WildcardWebhookUpdateError: KB-068, otterdog PATCHes config.url = the pattern).

<a id="pending"></a>

## Unmerged otterdog changes (pull requests and local branches)

`pending`: 5 features, 4 covered, 1 partial, 0 gaps (weighted 90%).

| Id | Feature | Tier | Plan | Prio | Status | Verified | Covered by |
|---|---|---|---|---|---|---|---|
| `pending.792-stale-status` | #792 (open): a stale webhook snapshot must not revert a merged pull request to open | webapp | free | P1 | covered | **unverified** | `tests/webapp/test_stale_status.py::test_stale_snapshot_keeps_merged_status` |
| `pending.check-merge-command` | local feature: /otterdog check-merge reports auto-merge eligibility (check-merge comment, previous minimized) and never merges | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_check_merge.py::test_check_merge_command` |
| `pending.update-branch-command` | local feature: /otterdog update-branch [rebase\|merge] updates the PR branch with its base (a rebase only by the author or an admin) | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_update_branch.py::test_update_branch_command` |
| `pending.outdated-branch-note` | local feature: validation and check-merge comments note when the PR branch is behind its base ('... is &lt;n&gt; commit(s) behind ...') | webapp | free | P2 | covered | **unverified** | `tests/webapp/test_update_branch.py::test_update_branch_command` |
| `pending.automerge-state-refresh` | local feature: auto-merge state recomputed from live teams and approvals (automerge_state.py) for merge, help and update-pull-request | webapp | free | P2 | **partial** | **unverified** | `tests/webapp/test_check_merge.py::test_check_merge_refreshes_the_team_membership` |

Details:

- **`pending.792-stale-status`** (covered, P1, `webapp`): #792 (open): a stale webhook snapshot must not revert a merged pull request to open
    - Source: `ws:otterdog-pr/otterdog/webapp/db/service.py:506-579`, `otterdog/webapp/db/service.py:505-564`
    - Operations: state, event
    - Known bugs: KB-018
    - Notes: W-PR-STALE-SNAPSHOT references #792 with its expected delta (--change 792)
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
