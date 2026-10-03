# Known otterdog issues

This page mirrors [`scenarios/known_bugs.yaml`](../scenarios/known_bugs.yaml): suspected or confirmed otterdog
defects found while building the e2e harness, each with precise evidence. `tests/unit/test_yaml_cli.py` checks that
the two stay in sync.

How the registry is used:

- A scenario that exercises a bug declares it (`known_bug: KB-nnn` in YAML, or `@pytest.mark.known_bug("KB-nnn")` on
  a Python test), and the bug lists the scenario in `scenarios`. Each such test asserts the **correct** behaviour.
  At collection the plugin marks it `xfail(strict=False)`, scoped to the exception that reports the bug
  (`KnownBugReproduced` for a YAML scenario, `AssertionError` for a Python test, so harness errors stay failures): it
  reports XFAIL while the bug exists and XPASS once it is fixed. On an XPASS, set `status: fixed` and `fixed_in: <version or pr-N>` and update this page. From then on the
  plugin no longer adds the xfail: the test guards against a regression. Only SUTs whose version predates a PEP 440
  `fixed_in` (for example `1.7.0.dev21`) keep it, with "SUT ... predates the fix" in the reason. A `pr-N` value
  cannot be compared with versions: replace it with the released version once there is one.
- Evidence entries prefixed `e2e:` point at a file of this project that detects the bug. Offline scenarios that
  detect a bug themselves (pytest.xfail when detected) are cited there instead of in `scenarios`, which would xfail
  them on every SUT.
- `status: confirmed` means the claim was reproduced **offline**, with the commands given in the bug's
  "Reproduction" section. `status: suspected` means it is established from the source code and the GitHub docs but
  needs a live org (or a running webapp) to reproduce.
- Evidence paths are relative to the otterdog repository at `main` 9bdeb75 (after v1.6.1). `chart:` refers to the
  Helm chart `otterdog-1.5.4` (eclipse-csi/helm-charts). `openapi:` refers to GitHub's REST OpenAPI description.
- KB-028 to KB-040 are the findings F-01 to F-13 of the coverage matrix (`scenarios/coverage.yaml`,
  [coverage-matrix.md](coverage-matrix.md)), KB-041 the finding of the web-UI tier
  ([web-ui-testing.md](web-ui-testing.md)), KB-042 to KB-077 the findings of the test battery. The matrix features
  they affect list them in `known_bugs`. A bug that only one step of a YAML scenario exercises is declared by that
  step (`known_bug` of the step) and is not listed in `scenarios`: its section names the step, its evidence the file.

## Reproducing offline

The reproductions ran with otterdog 1.7.0.dev19. Its CLI code is byte-identical to `main` 9bdeb75 for every file
involved (`models/`, `operations/`, `providers/`, `credentials/`, `resources/`, `utils.py`, `config.py`, `cli.py`).
Every command ran inside `unshare -rn`, a new network namespace with no network at all, so none of them reached
GitHub. A minimal workspace is enough. The org configs contain no team, because validation lists the org members as
soon as a team is defined (KB-037 replaces that one read with a constant). The webapp reproduction (KB-040) ran in
the webapp image the harness built from `main` 9bdeb75 (`otterdog-e2e/otterdog:sha-9bdeb75`, `docker run --network
none`), whose `otterdog/webapp` is identical to the source.

```text
otterdog.json
orgs/e2e-test-org/e2e-test-org.jsonnet        # HEAD (the configuration under test)
orgs/e2e-test-org/e2e-test-org.jsonnet-BASE   # BASE (local-plan only: the "current" side)
orgs/e2e-test-org/vendor/template/*.libsonnet  # copy of otterdog's examples/template/*.libsonnet
```

```json
{
  "defaults": {"jsonnet": {"base_template": "https://github.com/e2e-offline/template#otterdog-defaults.libsonnet@offline",
                           "config_dir": "orgs"}},
  "organizations": [{"name": "e2e-test-org", "github_id": "e2e-test-org",
                     "credentials": {"provider": "env", "api_token": "E2E_OTTERDOG_API_TOKEN",
                                     "username": "E2E_OTTERDOG_USERNAME", "password": "E2E_OTTERDOG_PASSWORD",
                                     "twofa_seed": "E2E_OTTERDOG_TOTP_SEED"}}]
}
```

```console
$ cd <workspace>
$ env -u OTTERDOG_CONFIG_ROOT COLUMNS=4096 NO_COLOR=1 PYTHON_DOTENV_DISABLED=1 \
      E2E_OTTERDOG_API_TOKEN=offline-dummy-token E2E_OTTERDOG_USERNAME=unset \
      E2E_OTTERDOG_PASSWORD=unset E2E_OTTERDOG_TOTP_SEED=unset \
      unshare -rn otterdog <command> -c otterdog.json --local e2e-test-org
```

Every HEAD file below starts with `local orgs = import 'vendor/template/otterdog-defaults.libsonnet';`. Outputs are
shortened to the relevant lines.

## Summary

| id | title | status | area | linked scenarios |
|----|-------|--------|------|------------------|
| KB-001 | apply exits 0 (webapp reports success) when validation fails | confirmed | CLI, webapp | `cli.kb.apply-exit-code` |
| KB-002 | install-app/uninstall-app: token-only credentials but a web login | suspected | CLI | `webui.cmd.install-app` |
| KB-003 | variables read without pagination (10 per page) | suspected | provider | `cli.kb.variables-pagination` |
| KB-004 | webhook URL change through `aliases` never applied | confirmed | model | `cli.kb.webhook-url-alias`, `H-ORG-HOOK-ALIAS` |
| KB-005 | one-way dict diffs (team_permissions/custom_properties removals) | confirmed | model | `cli.kb.team-permissions-removal` |
| KB-006 | org cache storage-limit on `/orgs/...` instead of `/organizations/...` | suspected | provider | - |
| KB-007 | cache storage-limit PUT although the GET said unavailable | suspected | provider | - |
| KB-008 | org ruleset validation AttributeError (#790, deployment rules) | confirmed | model | `enterprise.org-ruleset.790-missing-strict` |
| KB-009 | org rulesets rejected unless plan enterprise (#776) | confirmed | model | - |
| KB-010 | canonical-diff labels inverted | confirmed | CLI | - |
| KB-011 | check-status always exits 0 | confirmed | CLI | `cli.kb.check-status-exit-code` |
| KB-012 | Helm chart sets WEBHOOK_ENDPOINT | confirmed | deployment | - |
| KB-013 | GITHUB_ADMIN_TEAMS entries not stripped | confirmed | webapp | `W-RT-ADMIN-TEAMS-SPACES` |
| KB-014 | FetchAllPullRequestsTask hard-codes `main` | suspected | webapp | - |
| KB-015 | otterdog.json not reloaded on App push deliveries | suspected | webapp | `W-BP-GLOBAL-PUSH` |
| KB-016 | `_` in a custom property name forbids multi_select values | confirmed | schema | `cli.kb.custom-property-underscore` |
| KB-017 | author_association FIRST_TIMER drops the event | confirmed | webapp | - |
| KB-018 | stale snapshot overwrites a merged PR status (#792) | suspected | webapp | - |
| KB-019 | sync status `success` even when out of sync | suspected | webapp | - |
| KB-020 | ruleset status check `any:<ctx>` never converges | confirmed | model | `cli.kb.ruleset-any-status-check` |
| KB-021 | ruleset with the default empty newStatusChecks() never converges | confirmed | model | `cli.kb.ruleset-default-status-checks` |
| KB-022 | org variable selecting a repo created by the same apply fails | suspected | apply order | `cli.kb.org-variable-same-apply` |
| KB-023 | org ruleset repo-name patterns after the first warn spuriously | confirmed | model | `enterprise.kb.org-ruleset-repo-patterns` |
| KB-024 | imported Free org fails validation (members_can_create_private_pages) | suspected | import | `cli.import.validate` |
| KB-025 | secret value with two or more `:` crashes (ValueError) | confirmed | model | `O-KB-SECRET-WITH-COLONS` |
| KB-026 | plain secret values echoed in output and PR comments | confirmed | model, webapp | - |
| KB-027 | auto-merge eligibility compares team names with slugs | suspected | webapp | - |
| KB-028 | organization variables are never validated (F-01) | confirmed | model | - |
| KB-029 | invalid `workflows.allowed_actions` crashes validation with a KeyError (F-02) | confirmed | model | - |
| KB-030 | required custom property without default crashes loading (F-03) | confirmed | model | - |
| KB-031 | missing `required_pull_request` / `required_merge_queue` keys unreported, apply crashes (F-04) | confirmed | model | - |
| KB-032 | `team_permissions` values: uncaught schema error, dead model check (F-05) | confirmed | schema | - |
| KB-033 | org-dependent repository rules never fire (coerced at load) (F-06) | confirmed | model | - |
| KB-034 | validate/plan exit with the error count (256 errors exit 0) (F-07) | confirmed | CLI | `O-KB-EXIT-STATUS-ERROR-COUNT` |
| KB-035 | docs use `newEnvironmentSecret` / `newEnvironmentVariable` (F-08) | confirmed | docs | - |
| KB-036 | template comment of `deployment_branch_policy` lists invalid values (F-09) | confirmed | template | - |
| KB-037 | team privacy error lists `('secret' \| 'closed')` (F-10) | confirmed | model | - |
| KB-038 | set-ordered values in two validation messages (F-11) | confirmed | model | - |
| KB-039 | unknown `#role` bypass actor validates, apply crashes with a KeyError (F-12) | confirmed | model | - |
| KB-040 | crashing sync check: misleading `failure` status (F-13) | confirmed | webapp | `W-SYNC-FAILURE` |
| KB-041 | `two_factor_requirement` never read through the web UI | confirmed | web UI | `webui.kb.import-two-factor` |
| KB-042 | list-blueprints/approve-blueprints need the webapp package and its dependencies | confirmed | CLI, packaging | `cli.kb.blueprint-commands-without-webapp` |
| KB-043 | delete-file UnboundLocalError on a refused deletion | confirmed | CLI | `cli.kb.delete-file-refused` |
| KB-044 | delete-file reports 'succeeded' for a missing file | confirmed | CLI | `cli.kb.delete-file-missing` |
| KB-045 | dispatch-workflow exits 0 when the dispatch fails | confirmed | CLI | `cli.kb.dispatch-workflow-exit-code` |
| KB-046 | push-config of an invalid configuration exits 0 | confirmed | CLI | `cli.kb.push-config-invalid-exit-code` |
| KB-047 | install-deps exits 0 when the installation fails | confirmed | CLI | `webui.kb.install-deps-exit-code` |
| KB-048 | re-import drops the secret of a masked webhook | confirmed | import | `cli.kb.import-masked-webhook-secret` |
| KB-049 | fetch-config -r reports the default branch | confirmed | CLI | `cli.kb.fetch-config-ref-message` |
| KB-050 | free text printed as rich markup (list-advisories, show --markdown, validation messages, canonical form) | confirmed | CLI | `cli.kb.list-advisories-markup`, `O-KB-SHOW-MARKDOWN-LINKS`, `O-KB-VALIDATION-MARKUP`, step of `O-CANON` |
| KB-051 | App installations read without pagination | suspected | provider | - |
| KB-052 | bypass actor `<actor>:always` never converges | confirmed | model | step of `cli.ruleset.bypass` |
| KB-053 | `merge_commit_message` sent without `merge_commit_title` | suspected | model | step of `cli.repo.merge-messages` |
| KB-054 | app status checks in a spelling otterdog does not read back never converge | confirmed | model | steps of `cli.ruleset.status-checks`, `cli.protection.app-checks` |
| KB-055 | nested ruleset messages name the repository twice | confirmed | model | - |
| KB-056 | local-plan diffs and forces dummy-secret objects that every apply skips | confirmed | CLI, webapp | `O-KB-LPLAN-DUMMY-SECRETS` |
| KB-057 | webhook secrets: unknown providers validate, several `:` crash the apply | confirmed | model | - |
| KB-058 | topics of an archived repository planned and sent | suspected | model | - |
| KB-059 | /myprojects answers 500 without OAuth configuration | confirmed | webapp | `O-KB-WEB-LOGIN-REQUIRED` |
| KB-060 | form-encoded delivery without `payload` answers 500 | confirmed | webapp | `O-KB-WEB-FORM-WITHOUT-PAYLOAD` |
| KB-061 | a refused boot configuration exits 0 | confirmed | webapp | `O-KB-WEB-BOOT-EXIT-STATUS` |
| KB-062 | custom property value type `url` refused | confirmed | model | - |
| KB-063 | list replacements printed inconsistently | confirmed | CLI | - |
| KB-064 | clearing a value sends JSON null | suspected | provider | - |
| KB-065 | settings the create endpoint ignores are never re-applied | suspected | provider | - |
| KB-066 | copied sync status always 'completed successfully' | suspected | webapp | `W-SYNC-PROPAGATION-DRIFT` |
| KB-067 | sync check of an invalid main reports in sync | confirmed | webapp | `W-SYNC-INVALID-MAIN` |
| KB-068 | wildcard webhook PATCHed with the pattern as its url | confirmed | model, webapp | `W-MERGE-TEAM-HOOK` |
| KB-069 | one unreadable definition file fails the blueprint or policy fetch | confirmed | webapp | `W-BP-LOAD-YAML`, `W-POL-LOAD-MALFORMED` |
| KB-070 | multi-field definition change stored one field per fetch | confirmed | webapp | `W-BP-UPDATE` |
| KB-071 | a second fetch drops a pending blueprint recheck | confirmed | webapp | `W-BP-RECHECK-LOST` |
| KB-072 | blueprint type change breaks /internal/check | confirmed | webapp | `W-BP-TYPE-CHANGE` |
| KB-073 | pin_workflow skips workflows with docker:// actions | confirmed | webapp | `W-BP-PIN` |
| KB-074 | /internal/init marks every merged PR completed | suspected | webapp | `W-RT-INIT-APPLY-STATUS` |
| KB-075 | blueprint status updated_at never refreshed | suspected | webapp | - |
| KB-076 | global blueprints de-duplicated by type | suspected | webapp | - |
| KB-077 | local-plan/local-apply ignore -r for repositories only in the other configuration | confirmed | CLI | step of `O-LPLAN-FILTER` |

## Issues

### KB-001 — apply exits 0 (and the webapp reports success) when validation fails

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.apply-exit-code` (tests/cli/test_known_bugs.py)

Evidence: `otterdog/operations/plan.py:121-126`, `otterdog/operations/plan.py:128-139`,
`otterdog/operations/apply.py:97-108`, `otterdog/webapp/tasks/apply_changes.py:139-143`,
`otterdog/webapp/tasks/apply_changes.py:209-211`.

When validation fails, `PlanOperation.handle_validation_status` prints "Planning aborted due to validation errors."
and the live org is never loaded. `plan` then returns the error count, but `ApplyOperation.handle_finish` sees an
empty diff, prints "No changes required." and returns 0. The webapp's ApplyChangesTask calls the same operation
(`LocalApplyOperation`), takes exit 0 as `apply_success`, sets `apply_status` to `completed` and posts "The following
changes have been applied successfully". The merged changes are never applied, and only the live state shows it. The
harness never trusts the exit code: the scenario engine classifies an apply as `validation_error` from its output.

#### Reproduction

HEAD:

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [orgs.newRepo('repo') { topics: ['Invalid_Topic'] }],
}
```

```console
$ otterdog apply -c otterdog.json --local -f -n e2e-test-org        # exit code 0
│ Error:   repository[name="repo"] has defined an invalid topic 'Invalid_Topic'. Only lower-case, numbers and '-' are allowed characters.
  Planning aborted due to validation errors.
  No changes required.
```

The same configuration with `validate` or `plan` exits 1. The golden sample `tests/unit/data/apply-validation-error.txt`
shows the same output.

### KB-002 — install-app/uninstall-app resolve token-only credentials but need a web login

Status: **suspected** · Upstream: none · Scenarios: `webui.cmd.install-app` (tests/web_ui/test_web_commands.py)

Evidence: `otterdog/operations/install_app.py:55`, `otterdog/operations/install_app.py:71`,
`otterdog/operations/uninstall_app.py:55`, `otterdog/operations/uninstall_app.py:68`,
`otterdog/credentials/env_provider.py:113-116`, `otterdog/credentials/__init__.py:39-41`,
`otterdog/providers/github/web.py:600`.

Since #693/#699 (v1.4.0) both operations request `only_token=True` credentials, so the username, password and TOTP
seed are `None`. They then log in to the GitHub web UI through Playwright (`web_client.install_github_app` and
`uninstall_github_app`). Typing the login reads `credentials.username`, which raises "username not available". Not
reproduced offline: the operations read the installations through REST and the login opens github.com before the
username is read. The token tiers never run these commands (every live command uses `-n`, the e2e App is installed
through the GitHub UI). The web-UI tier does: `webui.cmd.install-app` installs and uninstalls a harmless probe App
(`web_ui.probe_app_slug`) and verifies both through `GET /orgs/{org}/installations`; it is a non-strict xfail of this
bug, so an XPASS reveals the fix ([web-ui-testing.md](web-ui-testing.md)).

### KB-003 — organization, repository and environment variables are read without pagination

Status: **suspected** · Upstream: none · Scenarios: `cli.kb.variables-pagination`

Evidence: `otterdog/providers/github/rest/org_client.py:386-390`, `otterdog/providers/github/rest/repo_client.py:1109-1116`,
`otterdog/providers/github/rest/repo_client.py:868-877`, openapi: `GET /repos/{owner}/{repo}/actions/variables`
(`per_page` default 10, max 30; the org and environment listings are the same).

The three listings are single GETs without `per_page` (`request_json` and `request_raw`, not `request_paged_json`).
With more than 10 variables in one scope, the plan sees only the first page, wants to add the rest again, and the
apply then fails with 409/422 "already exists". The live scenario creates 12 repository variables in one apply (a new
repository has no live variables to read) and asserts convergence. The oracle pages with `per_page=30`. Workaround:
keep at most 10 variables per org, repository or environment.

### KB-004 — a webhook URL change through `aliases` is never applied

Status: **confirmed** · Upstream: none · Scenarios: `H-ORG-HOOK-ALIAS` (tests/webhooks/test_managed_org_hook.py); step `rename-url` of `cli.kb.webhook-url-alias`

Evidence: `otterdog/models/webhook.py:65-70`, `docs/userguide/renaming.md:29-50`, `docs/reference/organization/webhook.md:7`.

The user guide documents `aliases` as the way to change a webhook URL "without re-creating the webhook as a whole".
The alias does let otterdog match the live hook, so there is no add or remove. But
`Webhook.include_field_for_diff_computation` excludes `url` and `aliases` from the diff, so no change is planned and
the URL stays the old one, unless another field of the hook changes in the same apply.

#### Reproduction

BASE and HEAD (local-plan treats BASE as the live side):

```jsonnet
// BASE
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [orgs.newRepo('repo') { webhooks: [orgs.newRepoWebhook('https://hooks.example.org/before') {}] }],
}
// HEAD
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [orgs.newRepo('repo') { webhooks: [orgs.newRepoWebhook('https://hooks.example.org/after')
                                                    { aliases: ['https://hooks.example.org/before'] }] }],
}
```

```console
$ otterdog local-plan -c otterdog.json --local e2e-test-org       # exit code 0
  Plan: 0 to add, 0 to change, 0 to delete.
```

Also reproduced offline by the step `webhook-alias-url` of `O-LPLAN-RENAME`
(`scenarios/offline/plan/lplan-rename.yaml`, a step-level known bug); `H-ORG-HOOK-ALIAS` checks the organization hook
side live.

### KB-005 — dict values diff one way only

Status: **confirmed** · Upstream: none · Scenarios: step `remove-permission` of `cli.kb.team-permissions-removal`

Evidence: `otterdog/utils.py:105-124`, `otterdog/models/__init__.py:437-475`.

`is_different_ignoring_order(value, other)` iterates only the keys of its first argument. `get_difference_from` calls
it with the EXPECTED value first (`models/__init__.py:472`), so a key that exists live but was removed from the
configuration is never seen. Removing a team from a repository's `team_permissions` therefore keeps the team's access,
and removing a value from a repository's `custom_properties` keeps the value. The removal only goes through when
another key of the same dict changes too, because the whole dict is then compared. Since #623 the repository's team
permissions are reconciled from `from`/`to` dicts (`repository.py:1379-1450`), so a detected change would remove the
team; the bug is the detection. The harness's custom property scenario never removes a value for this reason.

#### Reproduction

```jsonnet
// BASE
  _repositories+: [orgs.newRepo('repo') { team_permissions: { 'team-a': 'push', 'team-b': 'pull' } }],
// HEAD
  _repositories+: [orgs.newRepo('repo') { team_permissions: { 'team-a': 'push' } }],
```

```console
$ otterdog local-plan -c otterdog.json --local e2e-test-org       # exit code 0
  Plan: 0 to add, 0 to change, 0 to delete.
```

The same holds for repository `custom_properties`: BASE `{a: 'x', b: 'y'}`, HEAD `{a: 'x'}` gives 0 changes.

### KB-006 — the organization Actions cache storage-limit endpoint is called on the wrong path

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/providers/github/rest/org_client.py:562-569`, `otterdog/providers/github/rest/org_client.py:581-591`,
openapi: only `/organizations/{org}/actions/cache/storage-limit` (GET, PUT) and the repository and enterprise variants
exist.

otterdog reads and writes `/orgs/{org}/actions/cache/storage-limit`, a path GitHub's REST description does not
contain. The GET answers 404, which `_get_optional_json` turns into "not available" (warning only), so the org-level
`workflows.max_cache_size_gb` is never compared. The PUT of KB-007 then fails. The harness probe
(`capabilities.probe_capabilities`) uses otterdog's path on purpose, records the status in
`Capabilities.probes['org_cache_storage_limit']` and normally leaves `actions_cache_limit` absent. The renderer then
hides `max_cache_size_gb` at org and repository level (OC-06). The documented path is probed too and only recorded
(`Capabilities.probes['org_cache_storage_limit_documented']`): 200 there and 404 on otterdog's path is the evidence of
this bug on a target. Scenarios read both through the check kinds `org_cache_storage_limit` (documented path) and
`org_cache_storage_limit_orgs_path` (otterdog's path).

### KB-007 — the cache storage-limit PUT is sent although the GET reported the feature unavailable

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/providers/github/rest/__init__.py:156-181`, `otterdog/models/repository.py:1493-1509`,
`otterdog/models/repository.py:1531-1536`, `otterdog/providers/github/rest/repo_client.py:1227-1229`,
`otterdog/providers/github/rest/repo_client.py:1252-1262`, `otterdog/providers/github/rest/org_client.py:557-558`.

A 402/403/404 on the GET only logs a warning, but the configured value is still sent. On a repository ADD, the whole
workflow settings, including `max_cache_size_gb` (10 in the template), go to `update_repo_workflow_settings`
before the team permissions are reconciled. A non-204 answer to `PUT .../actions/cache/storage-limit` raises
RuntimeError, so the patch fails, the repository stays without its team permissions, and apply exits 1. Any later
change of the workflow settings resends the PUT. Not reproduced: it needs an org where the endpoint is unavailable.
The harness avoids it by hiding the field when `actions_cache_limit` is missing. A scenario that wants the field must
write `max_cache_size_gb::: <n>` and require the capability.

### KB-008 — org ruleset validation raises AttributeError for incomplete nested rules (#790) and deployment rules

Status: **confirmed** · Upstream: https://github.com/eclipse-csi/otterdog/pull/790 ·
Scenarios: `enterprise.org-ruleset.790-missing-strict`

Evidence: `otterdog/models/ruleset.py:128-136`, `otterdog/models/ruleset.py:57-65`, `otterdog/models/ruleset.py:240-247`,
`otterdog/models/ruleset.py:451-458`, `otterdog/models/github_organization.py:84-85`,
`otterdog/models/github_organization.py:226-227`, `otterdog/models/__init__.py:566`.

PR #790 (9bdeb75) made `Ruleset.validate` call `StatusCheckSettings.validate`. That method builds its error with
`parent_object.get_model_header(parent_object)`. For an ORGANIZATION ruleset the parent is `GitHubOrganization`, a
plain dataclass without `get_model_header` (only `ModelObject` has one). A missing `strict` or `status_checks`
therefore crashes validation with AttributeError instead of producing an error. The CLI exits 2, and the webapp
posts the generic "Validation failed while evaluating the configuration". The validators of `required_pull_request`
and `required_merge_queue` (any unset parameter) use the same call, but they never report a missing parameter
(KB-031), so only their range and enum checks can reach it. Only reachable with
`settings.plan: enterprise`, because other plans reject org rulesets first (KB-009). Repository rulesets are fine and
get the intended error (`regression.790-repo-ruleset-without-strict`).

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'enterprise' },
  rulesets+: [
    orgs.newOrgRuleset('org-rules') {
      include_refs+: ['~DEFAULT_BRANCH'],
      required_status_checks: { status_checks: ['ci'] },
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   'GitHubOrganization' object has no attribute 'get_model_header'
```

Offline evidence in this project: `O-VAL-790-ORG` (`scenarios/offline/val-790-org.yaml`, checked by
`tests/offline/test_scenarios.py`) renders exactly this case on the e2e offline organization. On SUTs containing #790
(9bdeb75, d0d3b08) `validate --local` exits 2 with the AttributeError and the test reports it as an xfail. On SUTs
without #790 (v1.6.1, b5f7bb1) the org ruleset validates and the test passes. The scenario is deliberately not
listed under `scenarios` in `known_bugs.yaml`: that would add an xfail on every SUT, and SUTs without #790 would then
show XPASS. In the #790 differential (`scenarios/otterdog-prs/790.yaml`) the crash is the one *unexpected* delta.

#### Deployment rules (since before v1.6.1)

`Ruleset.validate` also checks the environments of a deployment rule with `cast("Repository",
parent_object).environments` (`otterdog/models/ruleset.py:436-447`). For an organization ruleset with
`requires_deployments: true` and environments the parent is the organization again, and validation crashes with
`'GitHubOrganization' object has no attribute 'environments'` (exit 2) on every version that has the check (v1.6.1
included), where the repository variant reports an undefined environment. GitHub's `org-rules` include the
`required_deployments` rule, so the configuration itself is valid. Both crashes are steps of `O-VAL-ORG-RULESETS`
(`scenarios/offline/validation/val-org-rulesets.yaml`: `review-count-range` and `deployment-rule`, step-level known
bugs); KB-055 is the same root cause for repository rulesets (their messages name the repository twice).

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'enterprise' },
  rulesets+: [
    orgs.newOrgRuleset('org-deploy') {
      include_refs+: ['~DEFAULT_BRANCH'],
      include_repo_names: ['~ALL'],
      requires_deployments: true,
      required_deployment_environments: ['prod'],
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   'GitHubOrganization' object has no attribute 'environments'
```

### KB-009 — organization rulesets are rejected unless settings.plan is enterprise (#776)

Status: **confirmed** · Upstream: https://github.com/eclipse-csi/otterdog/issues/776 · Scenarios: none

Evidence: `otterdog/models/github_organization.py:219-227`.

The validation refuses any organization ruleset when the configured plan is not `enterprise`. GitHub Team supports
organization rulesets since 2025-06-16 (FACTS plans.json). Only otterdog's side is reproduced here; that GitHub
offers the feature on Team comes from GitHub's changelog. The harness gates its org ruleset scenarios on
`otterdog_org_rulesets` (Enterprise only) for this reason.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'team' },
  rulesets+: [orgs.newOrgRuleset('org-rules') { include_refs+: ['~DEFAULT_BRANCH'] }],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 1
│ Error:   use of organization rulesets requires an 'enterprise' plan, while this organization is currently on a 'team' plan.
  Validation failed: 0 info(s), 0 warning(s), 1 error(s)
```

Reproduced offline by the step `org-rulesets-on-team` of `O-VAL-PLAN-GATES-TEAM`
(`scenarios/offline/validation/val-plan-gates-team.yaml`, a step-level known bug: a Team plan configuration with an
organization ruleset is expected to validate).

### KB-010 — canonical-diff labels are inverted

Status: **confirmed** · Upstream: none · Scenarios: step `labels` of `O-CANON` (scenarios/offline/canonical-diff.yaml)

Evidence: `otterdog/operations/canonical_diff.py:73-74`, `otterdog/operations/canonical_diff.py:86-100`.

`_diff(a=canonical, b=original, "canonical", "original")` writes `a` to a temporary file and pipes `b` on stdin, then
runs `diff --label canonical --label original -u -w - <file>`. The first operand, stdin, is the ORIGINAL file, yet it
is labelled "canonical", and the canonical file is labelled "original". Read the output the other way round: `-`
lines are in the user's file, `+` lines are the canonical form. Like a report, it exits 0 whatever the diff shows
(1 only when the configuration is missing or does not load).

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  // a comment line
  _repositories+: [orgs.newRepo('repo')],
}
```

```console
$ otterdog canonical-diff -c otterdog.json --local e2e-test-org   # exit code 0
--- canonical
+++ original
-orgs.newOrg('e2e-test-org') {
-  // a comment line
+orgs.newOrg('e2e-test-org', 'e2e-test-org') {
+  _repositories+:: [
```

The comment and the one-argument `newOrg` only exist in the user's file, yet they appear on the "canonical" side.
The golden sample `tests/unit/data/canonical-diff.txt` shows the same.

### KB-011 — check-status exits 0 even when the configuration is invalid or out of sync

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.check-status-exit-code`
(tests/cli/test_commands_check_status.py)

Evidence: `otterdog/operations/check_status.py:50-78`, `otterdog/operations/check_status.py:80-81`.

`CheckStatusOperation.handle_finish` always returns 0. With validation errors the live org is not loaded,
`handle_finish` still runs and the JSON says `is_valid: false`, yet the exit code is 0. Only a missing or unloadable
configuration (1) and exceptions such as a network failure (2) exit non-zero. This may be intended for a reporting command, but scripts must read the JSON. The
harness does: C-BASELINE asserts `validation_status` and `sync_status.in_sync`.

#### Reproduction

Use the KB-001 HEAD, which contains an invalid topic. check-status needs one GitHub read after a failed validation,
`GET /orgs/{org}` (archived?), so this reproduction replaces only that read with a constant:

```console
$ unshare -rn python - <<'EOF'      # run in the otterdog venv, inside the workspace, same environment as above
import sys
from otterdog.providers.github.rest import org_client
async def is_archived(self, org_id):
    return False
org_client.OrgClient.is_archived = is_archived
from otterdog.cli import cli
sys.argv = ["otterdog", "check-status", "-c", "otterdog.json", "--local", "-n", "-j", "status.json", "e2e-test-org"]
cli()
EOF
│ Error:   repository[name="repo"] has defined an invalid topic 'Invalid_Topic'. ...
  Validation status: False
  Synchronization status: False
# exit code 0; status.json: [{"org_id": "e2e-test-org", "validation_status": {"is_valid": false, ..., "errors": 1}, ...}]
```

### KB-012 — the Helm chart sets WEBHOOK_ENDPOINT, the webapp reads GITHUB_WEBHOOK_ENDPOINT

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: chart: `templates/deployment.yaml:125-126`, chart: `values.yaml:90`, `otterdog/webapp/config.py:87`,
`otterdog/webapp/webhook/github_webhook.py:33`.

The chart passes `github.webhookEndpoint` as the env var `WEBHOOK_ENDPOINT`, which the app never reads. The app always
falls back to its default `/github-webhook/receive`. The chart default value is also malformed: values.yaml has
`/github-webhook/receive""`. The chart sets no `GITHUB_APPROVAL_TEAMS` either (default `project-leads$`). The
harness's compose stack sets `GITHUB_WEBHOOK_ENDPOINT` itself.

#### Reproduction

```console
$ unshare -rn helm template e2e otterdog-1.5.4.tgz | grep -A1 'name: WEBHOOK_ENDPOINT'    # offline render
            - name: WEBHOOK_ENDPOINT
              value: "/github-webhook/receive\"\""
```

### KB-013 — GITHUB_ADMIN_TEAMS entries are not stripped

Status: **confirmed** · Upstream: none · Scenarios: `W-RT-ADMIN-TEAMS-SPACES` (tests/webapp/test_runtime.py)

Evidence: `otterdog/webapp/utils.py:315-334`, `otterdog/webapp/utils.py:337-338`, `otterdog/webapp/utils.py:342`,
`otterdog/webapp/utils.py:366`, `otterdog/webapp/tasks/__init__.py:280-284`.

`get_admin_teams` returns `teams_config.split(",")`. The approval team patterns are stripped (line 366) and so is
the human-readable description (line 342), but the admin team slugs used for the membership checks
(`tasks/__init__.py:282-284`, apply and done commands) keep their spaces. `"otterdog-admins, e2e-admins"` therefore
yields `" e2e-admins"`, which never matches, while the comment text shows the team correctly. The same applies to a
per-org `admin_teams` string in otterdog.json. Workaround: no spaces in the value (the harness writes a single team).

#### Reproduction

Snapshot webapp code with the dependencies of the otterdog development venv, a bare Quart app context and no
MongoDB. The installation lookup is replaced by "no override", so the global setting applies:

```console
$ PYTHONPATH=<otterdog checkout> unshare -rn python - <<'EOF'
import asyncio
from quart import Quart
from otterdog.webapp.db import service
from otterdog.webapp.utils import get_admin_teams, get_full_admin_team_slugs, get_approval_team_patterns
async def no_installation(github_id):
    return None
service.get_installation_by_github_id = no_installation
app = Quart("kb013")
app.config.update(GITHUB_ADMIN_TEAMS="otterdog-admins, e2e-admins", GITHUB_APPROVAL_TEAMS="project-leads$, e2e-leads$")
async def main():
    async with app.app_context():
        print(await get_admin_teams(), await get_full_admin_team_slugs("org"), await get_approval_team_patterns())
asyncio.run(main())
EOF
['otterdog-admins', ' e2e-admins'] ['org/otterdog-admins', 'org/ e2e-admins'] ['project-leads$', 'e2e-leads$']
```

### KB-014 — FetchAllPullRequestsTask only imports pull requests targeting `main`

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/webapp/tasks/fetch_all_pull_requests.py:39-41`.

`/internal/init` imports existing pull requests with `base_ref="main"`, whatever the config repository's default
branch is. Config repositories with another default branch get no PR history in the database, and their merged PRs
are not marked as applied. The harness requires `main` (baseline repos use the template's `default_branch: main`).
Webapp scenarios belong to the webapp tier (tests/webapp).

### KB-015 — otterdog.json is not reloaded when the push arrives as an App delivery

Status: **suspected** · Upstream: none · Scenarios: `W-BP-GLOBAL-PUSH` (tests/webapp/test_blueprints.py)

Evidence: `otterdog/webapp/webhook/__init__.py:262-317`, `otterdog/webapp/webhook/__init__.py:319-334`.

The push handler returns inside the `event.installation is not None and event.organization is not None` branch. The
global otterdog.json refresh (`refresh_otterdog_config`, `update_installations_from_config`) only runs for pushes
without an installation, that is a plain repository webhook. If the configs repository lives in an org where the App
is installed, which is the e2e setup, committing otterdog.json changes nothing until `/internal/init`. The harness
calls `/internal/init` after every otterdog.json write (webapp fixture, SPEC 15).

### KB-016 — a custom property whose name contains `_` cannot hold a multi_select value

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.custom-property-underscore`

Evidence: `otterdog/resources/schemas/types.json:32-41`, `otterdog/resources/schemas/repository.json:58`.

The repository schema types `custom_properties` as an object whose keys matching `^.*_` must be strings, so the list
value of a multi_select property named with an underscore is rejected. The uncaught jsonschema error makes validate
exit 2. GitHub allows `_` in property names. The harness names its properties with `-` (`naming.prop`, OC-05).

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free', custom_properties+: [orgs.newCustomProperty('my_tags') { value_type: 'multi_select', allowed_values: ['a', 'b'] }] },
  _repositories+: [orgs.newRepo('repo') { custom_properties: { my_tags: ['a', 'b'] } }],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   {'my_tags': ['a', 'b']} is not valid under any of the given schemas
│          Failed validating 'anyOf' in schema['properties']['repositories']['items']['properties']['custom_properties']:
│              {'anyOf': [{'type': 'object', 'patternProperties': {'^.*_': {'type': 'string'}}}, {'type': 'null'}]}
```

### KB-017 — GitHub's author_association FIRST_TIMER is not accepted

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/webapp/webhook/github_models.py:134-145`, `otterdog/webapp/webhook/github_models.py:81`,
`otterdog/webapp/webhook/github_models.py:156`.

`AuthorAssociation.FIRST_TIMER = "FIRST_TIME"`, but GitHub sends the value `FIRST_TIMER`, so a pull request or issue
comment from a first-time author fails pydantic validation and the whole event is dropped. The receiver still answers
204. Test accounts must have prior public activity (docs/setup-free-org.md).

#### Reproduction

```console
$ PYTHONPATH=<otterdog checkout> unshare -rn python -c "
from otterdog.webapp.webhook.github_models import AuthorAssociation
print(sorted(m.value for m in AuthorAssociation)); AuthorAssociation('FIRST_TIMER')"
['COLLABORATOR', 'CONTRIBUTOR', 'FIRST_TIME', 'FIRST_TIME_CONTRIBUTOR', 'MANNEQUIN', 'MEMBER', 'NONE', 'OWNER']
ValueError: 'FIRST_TIMER' is not a valid AuthorAssociation
```

### KB-018 — a stale webhook snapshot can overwrite the status of a merged pull request

Status: **suspected** · Upstream: https://github.com/eclipse-csi/otterdog/pull/792 (open) · Scenarios: none

Evidence: `otterdog/webapp/db/service.py:505-564`, `otterdog/webapp/tasks/check_sync.py:73-133`.

`update_or_create_pull_request` writes the lifecycle fields (draft, status, timestamps) from the task's snapshot
unconditionally. CheckConfigurationInSyncTask sleeps at least 60 s (backoff) while holding the snapshot of the open
PR, so it can turn a merged PR back to `open`. Upstream incident: osgi/.eclipsefdn#25. PR #792 makes the update
conditional and atomic. Once it is merged, set `fixed_in: pr-792`. The deterministic e2e check (injecting a stale
`converted_to_draft` snapshot after the merge) belongs to the webapp tier (W-STALE-STATUS-792, manifest
scenarios/otterdog-prs/792.yaml).

### KB-019 — the sync status is `success` even when the configuration is out of sync

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/webapp/tasks/check_sync.py:236-257`.

`_update_final_status` posts `success` in both branches; only the description changes, to "otterdog sync check
failed, check comment history". The code comment says this is deliberate: the check is informational and must not
block merges. It is listed so that tests assert the description and the check-sync comment, never the state
(W-DRIFT-CHECKSYNC, OC-11). An exception gives `failure` with "otterdog detected out of sync changes, but they will
not prevent a successful merge" (KB-040).

### KB-020 — a ruleset status check written as `any:<context>` never converges

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.ruleset-any-status-check`

Evidence: `otterdog/models/ruleset.py:141-160`, `otterdog/models/ruleset.py:163-224`, `otterdog/models/__init__.py:248-272`,
`docs/reference/organization/repository/status-check.md:10-13`.

The docs say that for rulesets `any:` "is not needed ... and will give the same result as omitting it". otterdog
sends `any:ci` as `{"context": "ci"}` (lines 197-207) but reads it back as plain `ci` (lines 145-151). The embedded
diff then compares `any:ci` with `ci` on every plan, and every apply re-sends the same rule. Branch protection rules
are not affected: their GraphQL read maps a null app back to `any:` (`branch_protection_rule.py:273-283`).

#### Reproduction

Model round trip, offline, with no network: a configured status check goes through otterdog's own payload
mapping, is wrapped as the rule GitHub stores (no rule for an empty payload) and is read back:

```console
$ unshare -rn python - <<'EOF'      # run in the otterdog venv
import asyncio
from otterdog.models.repo_ruleset import RepositoryRuleset
from otterdog.models.ruleset import StatusCheckSettings
class NoApps:                        # provider stub: no app slug needs resolving
    async def get_app_ids(self, slugs):
        return {}
async def main():
    for checks in (["any:e2e-ci"], ["e2e-ci"], []):
        data = {"do_not_enforce_on_create": False, "strict": True, "status_checks": checks}
        payload = await StatusCheckSettings.dict_to_provider_data("e2e-test-org", data, NoApps())
        rules = [{"type": "required_status_checks", "parameters": payload}] if payload else []
        live = {"name": "rs", "target": "branch", "enforcement": "active", "rules": rules}
        read = RepositoryRuleset.from_provider_data("e2e-test-org", live).required_status_checks
        print(checks, "->", payload, "->", None if read is None else read.status_checks)
asyncio.run(main())
EOF
['any:e2e-ci'] -> {..., 'required_status_checks': [{'context': 'e2e-ci'}]} -> ['e2e-ci']
['e2e-ci']     -> {..., 'required_status_checks': [{'context': 'e2e-ci'}]} -> ['e2e-ci']
[]             -> {} -> None
```

The diff that follows, with BASE holding the read-back value:

```jsonnet
// BASE
  _repositories+: [orgs.newRepo('repo') { rulesets: [orgs.newRepoRuleset('rs') { required_status_checks+: { status_checks+: ['ci'] } }] }],
// HEAD
  _repositories+: [orgs.newRepo('repo') { rulesets: [orgs.newRepoRuleset('rs') { required_status_checks+: { status_checks+: ['any:ci'] } }] }],
```

```console
$ otterdog local-plan -c otterdog.json --local e2e-test-org       # exit code 0
  ~ repo_ruleset[name="rs", repository=repo] {
    ~ required_status_checks     = {
      ~ status_checks              = [
        ~ "ci"   -> "any:ci"
  Plan: 0 to add, 1 to change, 0 to delete.
```

### KB-021 — a ruleset with the template's empty newStatusChecks() never converges

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.ruleset-default-status-checks`

Evidence: `otterdog/models/ruleset.py:171-173`, `otterdog/models/ruleset.py:584-588`, `otterdog/models/ruleset.py:714-728`,
`otterdog/models/__init__.py:457-473`, `examples/template/otterdog-defaults.libsonnet:166-170`.

`newRepoRuleset` defaults `required_status_checks` to `newStatusChecks()` =
`{do_not_enforce_on_create: false, strict: false, status_checks: []}`. Since #562 an empty list sends no rule at all
(lines 171-173 return `{}`, so no rule is added at 714-728). GitHub then has no `required_status_checks` rule, and
otterdog reads the field back as `null` (584-588). `get_difference_from` compares the configured object with `null`
and reports a change on every plan, so every ruleset built from the template default never converges. `import`
writes `required_status_checks: null` explicitly, which avoids it. The harness's own rulesets either set non-empty
checks or `null`. The #562 regression scenario asserts the apply but not convergence, so that it is not masked by
this bug.

#### Reproduction

The model round trip above, third line: `[] -> payload {} -> read back None`. The diff that follows:

```jsonnet
// BASE (what is read back)
  _repositories+: [orgs.newRepo('repo') { rulesets: [orgs.newRepoRuleset('rs') { required_status_checks: null }] }],
// HEAD (template default)
  _repositories+: [orgs.newRepo('repo') { rulesets: [orgs.newRepoRuleset('rs')] }],
```

```console
$ otterdog local-plan -c otterdog.json --local e2e-test-org       # exit code 0
  ~ repo_ruleset[name="rs", repository=repo] {
    ~ required_status_checks     = {
      + do_not_enforce_on_create   = false
      + status_checks              = [
      + ]
      + strict                     = false
  Plan: 0 to add, 1 to change, 0 to delete.
```

### KB-022 — an org variable or secret selecting a repository created by the same apply fails

Status: **suspected** · Upstream: none · Scenarios: `cli.kb.org-variable-same-apply`

Evidence: `otterdog/models/github_organization.py:529-545`, `otterdog/models/organization_variable.py:91-93`,
`otterdog/providers/github/__init__.py:477-482`, `otterdog/operations/apply.py:135-151`.

Live patches are generated, and applied, in a fixed order: roles, teams, settings, org webhooks, org secrets, org
variables, org rulesets, then repositories. apply only moves read-only patches last. Adding an org variable with
`visibility: selected` resolves the ids of its repositories with one GET each (`get_repo_ids`). A repository created
by the same apply does not exist yet, so the variable patch fails with "failed to apply patch" and apply exits 1. A
second apply succeeds. One configuration change, for example one webapp PR, cannot add both. Org secrets with
selected repositories and org workflow settings use the same id lookup. `cli.org.variable` creates the repository
in a first step for this reason.

### KB-023 — org ruleset repository-name patterns after the first one warn spuriously

Status: **confirmed** · Upstream: none · Scenarios: `enterprise.kb.org-ruleset-repo-patterns`

Evidence: `otterdog/models/organization_ruleset.py:45-69`.

`all_repo_names = (x.name for x in repositories)` is a generator, consumed by the first `fnmatch.filter`. Every
later `include_repo_names` or `exclude_repo_names` pattern sees an empty sequence and gets the warning "does not
match any existing repository". Warnings also make `check-status` report the org as not valid and not in sync.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'enterprise' },
  rulesets+: [orgs.newOrgRuleset('org-rules') { include_repo_names: ['repo-a', 'repo-b'] }],
  _repositories+: [orgs.newRepo('repo-a'), orgs.newRepo('repo-b')],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 0
│ Warning:   org_ruleset[name="org-rules"] has an 'include_repo_names' pattern 'repo-b' that does not match any existing repository
  Validation succeeded': 0 info(s), 1 warning(s), 0 error(s)
```

Only the second pattern is reported, although both repositories are declared. Swapping the patterns moves the
warning to `repo-a`.

### KB-024 — an imported Free organization can fail validation (members_can_create_private_pages)

Status: **suspected** · Upstream: none · Scenarios: `cli.import.validate` (tests/cli/test_import.py)

Evidence: `otterdog/models/organization_settings.py:126-130`, `otterdog/resources/schemas/settings.json:74-77`.

The validation accepts `members_can_create_private_pages: true` only with plan `enterprise`. The GitHub API was seen
to report `true` for a Free org (the maintainer's imported config, FACTS cli R 19), so `import` then writes a
configuration that does not validate. The import round trip test is marked with this bug. If the live value cannot
be changed on Free, the baseline might not converge either: the template renders `false` and the setting is a
REST setting. In that case C-BASELINE reports `members_can_create_private_pages` as pending. The target cannot
declare `true`, because that is an error on non-enterprise plans. Report it, so that the baseline renderer can hide
the key.

### KB-025 — a secret value containing two or more `:` crashes validation and apply

Status: **confirmed** · Upstream: none · Scenarios: `O-KB-SECRET-WITH-COLONS` (tests/offline/test_cli_exit_codes.py)

Evidence: `otterdog/models/secret.py:50-53`, `otterdog/config.py:234-236`.

`provider_type, _ = re.split(":", value)` unpacks into exactly two names. `a:b:c` raises ValueError "too many values
to unpack" and the command exits 2. `CredentialResolver.get_secret` has the same split, so an apply crashes too.
Offline scenarios may use the literal (`pass:a:b`, several `:`; live scenarios cannot): a step declaring
`known_bug: KB-025` with `validate: {ok: true}` reproduces it as an expected failure while the other steps stay strict
(writing-scenarios.md, "Known bugs"); since the bug is declared per step, it lists no scenario here.

#### Reproduction

```jsonnet
  _repositories+: [orgs.newRepo('repo') { secrets: [orgs.newRepoSecret('S') { value: 'a:b:c' }] }],
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   too many values to unpack (expected 2)
```

The step `two-colons` of `O-VAL-SECRETS` (`scenarios/offline/validation/val-secrets.yaml`) asserts the same offline as a
step-level known bug. Webhook secrets with several `:` are not split at validation: they crash at apply time instead
(KB-057).

### KB-026 — plain secret values are echoed in validate/plan output and in the webapp's validation comments

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/secret.py:56-61`, `otterdog/models/webhook.py:85-95`,
`otterdog/webapp/tasks/validate_pull_request.py:157-181`, `otterdog/webapp/tasks/validate_pull_request.py:207-211`.

A secret or webhook secret that does not use a credential provider produces the warning "has a value
'&lt;value&gt;' that does not use a credential provider", which contains the value itself. The webapp renders the same
validation output into the PR comment, which is public on a public config repository. The harness only allows dummy
values (SPEC 5.8) and redacts every registered secret.

#### Reproduction

```jsonnet
  _repositories+: [orgs.newRepo('repo') { secrets: [orgs.newRepoSecret('S') { value: 'plain-value' }] }],
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 0
│ Warning:   repo_secret[name="S"] has a value 'plain-value' that does not use a credential provider.
  Validation succeeded': 0 info(s), 1 warning(s), 0 error(s)
```

Also visible in the golden sample `tests/unit/data/validate-warnings.txt`. In passing: the stray quote in
`Validation succeeded':` is a cosmetic bug of `operations/validate.py`.

### KB-027 — auto-merge eligibility compares GraphQL team names with the admin team slugs and approval patterns

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/webapp/tasks/retrieve_team_membership.py:86-89`, `otterdog/webapp/tasks/update_pull_request.py:62-70`,
`otterdog/webapp/tasks/__init__.py:280-297`, `otterdog/webapp/utils.py:384-392`,
`otterdog/resources/graphql/get-team-membership.gql:1-15`.

The GraphQL query returns both `name` and `slug` of the author's (and approvers') teams, but RetrieveTeamMembershipTask
and UpdatePullRequestTask keep only `team["name"]`. They compare those names with `GITHUB_ADMIN_TEAMS` and with the
approval patterns. Elsewhere the same settings are slugs: the admin checks of `/otterdog apply` and `/otterdog
done`, and `get_teams_matching_approval_pattern`, which matches `team_slugs`. The team links in the team-info comment
are built from the name too. A team whose display name differs from its slug, for example "Project Leads" with slug
`project-leads`, therefore never makes its members eligible for auto-merge, nor its approvals count. The harness
requires team names that equal their slugs (`^[a-z0-9][a-z0-9-]*$`, validated in the target file), so its webapp
tier does not hit this.


### KB-028 — organization variables are never validated

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/github_organization.py:196-234`, `otterdog/models/organization_variable.py:40-63`,
`otterdog/models/variable.py:29-42`.

Coverage finding F-01. `GitHubOrganization.validate` validates the settings, roles, teams, webhooks, secrets,
rulesets and repositories, but it has no loop over `self.variables`. So `OrganizationVariable.validate` (visibility
values, `private` on a free plan, `selected_repositories` without `selected`) and `Variable.validate` (the `GITHUB_`
prefix, uppercase names) never run for organization variables. Repository and environment variables are validated
by their parents. The errors otterdog defines for organization variables never print, and the configuration goes on
to the apply, where GitHub decides what happens.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  variables+: [
    orgs.newOrgVariable('lower_case') { value: 'x', visibility: 'private' },
    orgs.newOrgVariable('GITHUB_X') { value: 'x', visibility: 'nonsense', selected_repositories: ['a'] },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 0
  Validation succeeded
```

Four errors and one warning were expected. The same two objects declared with `orgs.newOrgSecret` (`value:
'********'`) are validated (secrets accept lowercase names), and so is a lowercase repository variable:

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # the org secrets: exit code 3
│ Error:   org_secret[name="lower_case"] has 'visibility' of value 'private', which is not available for an organization with free plan.
│ Error:   org_secret[name="GITHUB_X"] starts with prefix 'GITHUB_' which is not allowed for secrets.
│ Error:   org_secret[name="GITHUB_X"] has 'visibility' of value 'nonsense', while only values ('public' | 'private' | 'selected') are allowed.
│ Warning:   org_secret[name="GITHUB_X"] has 'visibility' set to 'nonsense', but 'selected_repositories' is set to '['a']', setting will be ignored.
  Validation failed: 2 info(s), 1 warning(s), 3 error(s)
$ otterdog validate -c otterdog.json --local e2e-test-org         # orgs.newRepoVariable('lower_case'): exit code 1
│ Error:   repo_variable[name="lower_case", repository=r1] has 'name' of value 'lower_case' which is not uppercase, while only uppercase names are allowed for variables.
```

### KB-029 — an invalid workflows.allowed_actions crashes validation with a KeyError

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/workflow_settings.py:94-99`, `otterdog/models/workflow_settings.py:101-106`,
`otterdog/models/repo_workflow_settings.py:99-105`, `otterdog/models/workflow_settings.py:115-123`,
`otterdog/cli.py:999-1001`.

Coverage finding F-02. The level of a value comes from a plain lookup, `_allowed_actions_level[allowed_actions]`.
The settings validation records the documented error ("settings has 'workflows.allowed_actions' of value ..."), but
the validation of every repository then compares its actions with the organization's
(`are_actions_more_restricted`), and the lookup raises KeyError for the invalid value. The exception discards the
whole validation result: the CLI prints only the key and exits 2. An invalid repository value crashes the same way,
because it is compared with the organization's value.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free', workflows+: { allowed_actions: 'some' } },
  _repositories+: [orgs.newRepo('r1')],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   'some'
```

Without the repository the documented error appears (exit code 1):
`settings has 'workflows.allowed_actions' of value 'some', while only values ('all' | 'local_only' | 'selected') are
allowed.` A repository with `workflows+: { allowed_actions: 'x' }` under the template's organization settings prints
`Error:   'x'` (exit code 2).

### KB-030 — a required custom property without default crashes loading when a repository exists

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/repository.py:296-303`, `otterdog/models/github_organization.py:349-351`,
`otterdog/models/custom_property.py:83-90`.

Coverage finding F-03. Repositories are coerced from the organization settings while the configuration loads. For a
required property that a repository does not set, the coercion copies the property's `default_value`, and it raises
`ValueError("unexpected None value")` when there is none. The validation error written for exactly this case ("has
'required' set to 'true', but no property 'default_value' is specified") is only printed when the organization has
no repository at all.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free', custom_properties+: [orgs.newCustomProperty('p') { required: true, default_value: null }] },
  _repositories+: [orgs.newRepo('r1')],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   unexpected None value
```

Without the repository (exit code 1):
`custom_property[name="p"] has 'required' set to 'true', but no property 'default_value' is specified.`

### KB-031 — missing keys of required_pull_request / required_merge_queue are never reported, the apply crashes

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/ruleset.py:57-65`, `otterdog/models/ruleset.py:240-248`,
`otterdog/models/__init__.py:329-350`, `otterdog/models/ruleset.py:128-136`, `otterdog/models/ruleset.py:698-712`,
`otterdog/models/ruleset.py:296-312`, `otterdog/models/ruleset.py:746-760`,
`otterdog/providers/github/rest/requester.py:123-125`, `otterdog/operations/apply.py:146-153`, openapi:
`repository-rule-pull-request` parameters require `required_approving_review_count` (and four more),
`repository-rule-merge-queue` requires all seven parameters.

Coverage finding F-04. `PullRequestSettings.validate` and `MergeQueueSettings.validate` look for unset parameters by
iterating `self.keys(False)`, but `keys()` skips unset keys by default (`exclude_unset_keys=True`). The error "has not
set required parameter 'required_pull_request.&lt;key&gt;'" can therefore never print. `StatusCheckSettings.validate`
iterates a fixed key list since #790 and works. The incomplete rule then reaches the apply. The pull request
parameters carry `UNSET`, which `json.dumps` in the REST requester cannot serialize (TypeError). The merge queue
mapping reads every key and raises jsonbender's BendingException. Neither is a RuntimeError, the only exception the
apply loop catches per patch: the apply stops at that patch, the patches after it are not applied, and the CLI exits
2.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [
    orgs.newRepo('r1') {
      rulesets: [
        orgs.newRepoRuleset('pr-only') {
          required_pull_request: { requires_code_owner_review: true },
          required_status_checks: null,
        },
        orgs.newRepoRuleset('mq-only') {
          required_pull_request: null,
          required_status_checks: null,
          required_merge_queue: { merge_method: 'MERGE' },
        },
      ],
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 0
  Validation succeeded
```

The same ruleset with `required_status_checks: { status_checks: ['ci'] }` gets the error (exit code 1):
`repository[name="r1", repository=r1] has not set required parameter 'required_status_checks.strict'.`

The payload an apply would send, built by the model (`RepositoryRuleset.to_provider_data`, the call of
`repo_ruleset.py:49-53`), offline:

```console
$ unshare -rn python - <<'EOF'      # run in the otterdog venv
import asyncio, json
from otterdog.models.repo_ruleset import RepositoryRuleset
ruleset = {"name": "rs", "target": "branch", "enforcement": "active", "bypass_actors": [],
           "include_refs": ["~DEFAULT_BRANCH"], "exclude_refs": [], "allows_creations": False,
           "allows_deletions": False, "allows_updates": True, "allows_force_pushes": False,
           "requires_commit_signatures": False, "requires_linear_history": False,
           "required_status_checks": None, "requires_deployments": False}
async def main():
    for nested in ({"required_pull_request": {"requires_code_owner_review": True}, "required_merge_queue": None},
                   {"required_pull_request": None, "required_merge_queue": {"merge_method": "MERGE"}}):
        model = RepositoryRuleset.from_model_data({**ruleset, **nested})
        try:  # the payload of an apply (repo_ruleset.py:49-53), then what the REST requester sends
            payload = await model.to_provider_data("e2e-test-org", None)
            print(payload["rules"][-1])
            json.dumps(payload)
        except Exception as exc:
            print(type(exc).__name__, exc)
asyncio.run(main())
EOF
{'type': 'pull_request', 'parameters': {'required_approving_review_count': <UNSET>, 'dismiss_stale_reviews_on_push': False, 'require_code_owner_review': True, 'require_last_push_approval': False, 'required_review_thread_resolution': False}}
TypeError Object of type _Unset is not JSON serializable
BendingException Error for key max_entries_to_build: 'build_concurrency'
```

### KB-032 — team_permissions values: an uncaught schema error, the model's check is dead code

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/resources/schemas/team-permission.json:1-11`, `otterdog/resources/schemas/repository.json:89-95`,
`otterdog/models/github_organization.py:285-296`, `otterdog/models/repository.py:194-205`,
`otterdog/models/repository.py:491-499`.

Coverage finding F-05. The repository schema restricts `team_permissions` values to `pull`, `triage`, `push`,
`maintain` and `admin`. A blocking schema error is raised as it is while the configuration loads, so the CLI prints
the jsonschema dump and exits 2. The model's own check, which also accepts the uppercase `READ`, `TRIAGE`, `WRITE`,
`MAINTAIN` and `ADMIN` and has a readable message ("invalid permission ... allowed values are ('read/pull' | 'triage'
| 'write/push' | 'maintain' | 'admin')"), is never reached.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [orgs.newRepo('r1') { team_permissions: { 'team-a': 'super' } }],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   'super' is not one of ['pull', 'triage', 'push', 'maintain', 'admin']
│
│          Failed validating 'enum' in schema['properties']['repositories']['items']['properties']['team_permissions']['patternProperties']['.*']:
```

`'WRITE'`, accepted by the model, gives the same error.

### KB-033 — repository rules that depend on organization settings never fire

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/github_organization.py:349-351`, `otterdog/models/repository.py:284-316`,
`otterdog/models/repository.py:436-465`, `otterdog/models/repository.py:583-600`.

Coverage finding F-06. `GitHubOrganization.from_model_data` replaces every repository by its coerced copy while the
configuration loads, and validation runs on the copies. The coercion clears exactly the values that four documented
messages test:

- `has_projects` is unset when the organization disables `has_organization_projects`: the warning "has
  'has_projects' enabled, while the organization disables 'has_organization_projects'" never prints;
- `web_commit_signoff_required` is unset when the organization requires signoff: the warning "has
  'web_commit_signoff_required' disabled, while the organization requires it" never prints;
- `has_discussions` becomes `true` on the organization's discussion source repository: the error "has
  'has_discussions' disabled, while the organization uses this repo as source repository for discussions" never
  prints, and a configured `false` is silently managed as `true`;
- `gh_pages_visibility` is unset below the enterprise plan: a `private` value is ignored without a message.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: {
    plan: 'free',
    has_organization_projects: false,
    web_commit_signoff_required: true,
    has_discussions: true,
    discussion_source_repository: 'e2e-test-org/r3',
  },
  _repositories+: [
    orgs.newRepo('r1') { has_projects: true },
    orgs.newRepo('r2') { web_commit_signoff_required: false },
    orgs.newRepo('r3') { has_discussions: false },
    orgs.newRepo('r4') {
      gh_pages_build_type: 'workflow',
      gh_pages_visibility: 'private',
      environments: [orgs.newEnvironment('github-pages') { deployment_branch_policy: 'selected', branch_policies: ['main'] }],
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 0
  Validation succeeded
```

With `plan: 'enterprise'` only the Pages rule appears (exit code 1): `repository[name="r4"] has 'gh_pages_visibility'
set to value 'private', but this setting is only available for private repositories.` The three other messages never
print on any plan.

### KB-034 — validate and plan exit with the number of validation errors

Status: **confirmed** · Upstream: none · Scenarios: `O-KB-EXIT-STATUS-ERROR-COUNT` (tests/offline/test_cli_exit_codes.py)

Evidence: `otterdog/operations/validate.py:102`, `otterdog/operations/plan.py:121-139`, `otterdog/cli.py:993-997`,
`otterdog/cli.py:999-1001`.

Coverage finding F-07. `ValidateOperation.execute` and `PlanOperation.handle_finish` return the number of errors,
and the CLI exits with the largest value of its organizations (`sys.exit(exit_code)`). Two errors therefore exit 2,
like an uncaught exception (`cli.py:999-1001`). The exit status is that number modulo 256, so 256 errors exit 0, as
a success. `local-plan` behaves the same. Scripts and CI jobs must read the output. The harness never uses the exit
code alone (see also KB-001 and KB-011).

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [orgs.newRepo('r1') { squash_merge_commit_title: 'BAD' }],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
  Validation failed: 0 info(s), 0 warning(s), 2 error(s)
```

256 repositories with an invalid topic:

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [orgs.newRepo('r%d' % i) { topics: ['Bad'] } for i in std.range(1, 256)],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 0
  Validation failed: 0 info(s), 0 warning(s), 256 error(s)
$ otterdog local-plan -c otterdog.json --local e2e-test-org       # exit code 0 (BASE: the bare organization)
  Planning aborted due to validation errors.
```

### KB-035 — the environment docs use newEnvironmentSecret / newEnvironmentVariable

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `docs/reference/organization/repository/environment/index.md:45-54`,
`examples/template/otterdog-defaults.libsonnet:288-292`.

Coverage finding F-08. The example of the environment reference page calls `orgs.newEnvironmentSecret` and
`orgs.newEnvironmentVariable`. The template defines `newEnvSecret` and `newEnvVariable`, so the copied example does
not load.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [
    orgs.newRepo('r1') {
      environments: [
        orgs.newEnvironment('e1') { secrets+: [orgs.newEnvironmentSecret('TEST_SECRET') { value: '********' }] },
      ],
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 1
│ Error:   Validation failed
│          failed to load configuration: failed to evaluate jsonnet file: no such field: newEnvironmentSecret
│          There is fields with similar names present: newEnvironment, newEnvSecret, newEnvVariable
```

With `orgs.newEnvSecret` and `orgs.newEnvVariable` the configuration validates.

### KB-036 — the template comment of deployment_branch_policy lists values validation rejects

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `examples/template/otterdog-defaults.libsonnet:281-282`, `otterdog/models/environment.py:128-135`,
`docs/reference/organization/repository/environment/index.md:9`.

Coverage finding F-09. The template documents `# Can be one of: all, protected_branches, branch_policies`. The
validation and the reference page accept `all`, `protected` or `selected`, so a value taken from the comment is an
error.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [
    orgs.newRepo('r1') {
      environments: [
        orgs.newEnvironment('e1') { deployment_branch_policy: 'protected_branches' },
        orgs.newEnvironment('e2') { deployment_branch_policy: 'branch_policies', branch_policies: ['main'] },
      ],
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 2
│ Error:   environment[name="e1", repository=r1] has 'deployment_branch_policy' of value 'protected_branches', while only values ('all' | 'protected' | 'selected') are allowed.
│ Error:   environment[name="e2", repository=r1] has 'deployment_branch_policy' of value 'branch_policies', while only values ('all' | 'protected' | 'selected') are allowed.
│ Warning:   environment[name="e2", repository=r1] has 'deployment_branch_policy' set to 'branch_policies', but 'branch_policies' is set to '['main']', setting will be ignored.
```

### KB-037 — the team privacy error lists ('secret' | 'closed')

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/team.py:77-83`, `docs/reference/organization/team.md:7`.

Coverage finding F-10. The check accepts `secret` and `visible`, but its message names `('secret' | 'closed')`.
`closed` is the REST API's word for `visible` (the model maps it when reading), and it is exactly the value the
message suggests and the check rejects.

#### Reproduction

A team validation lists the organization members once, through REST. This reproduction replaces only that read with
a constant ("no members"):

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  teams+: [
    orgs.newTeam('team-closed') { privacy: 'closed' },
    orgs.newTeam('team-visible') { privacy: 'visible' },
  ],
}
```

```console
$ unshare -rn python - <<'EOF'      # run in the otterdog venv, inside the workspace, same environment as above
import sys
from otterdog.providers.github.rest import org_client
async def list_members(self, org_id, two_factor_disabled=False):
    return []                        # the one GitHub read of a team validation: no members
org_client.OrgClient.list_members = list_members
from otterdog.cli import cli
sys.argv = ["otterdog", "validate", "-c", "otterdog.json", "--local", "e2e-test-org"]
cli()
EOF
│ Error:   team[name="team-closed"] has 'privacy' of value 'closed', while only values ('secret' | 'closed') are allowed.
  Validation failed: 0 info(s), 0 warning(s), 1 error(s)
# exit code 1
```

### KB-038 — two validation messages print Python sets in a random order

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/workflow_settings.py:30-34`, `otterdog/models/workflow_settings.py:143-150`,
`otterdog/models/repository.py:611-618`, `otterdog/models/repository.py:731-732`.

Coverage finding F-11. The `fork_pr_approval_policy` error formats the set `_FORK_PR_APPROVAL_POLICIES` directly,
and the code scanning language error joins the set `_valid_code_scanning_languages`. String hashing is randomized per
process (`PYTHONHASHSEED`), so the values come in a different order from one run to the next. Scenarios assert only
the stable prefix of these messages; otterdog could sort the values.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free', workflows+: { fork_pr_approval_policy: 'nobody' } },
}
```

```console
$ PYTHONHASHSEED=1 otterdog validate -c otterdog.json --local e2e-test-org | grep -o "while only values.*"
while only values {'all_external_contributors', 'first_time_contributors', 'first_time_contributors_new_to_github'} are allowed.
$ PYTHONHASHSEED=2 otterdog validate -c otterdog.json --local e2e-test-org | grep -o "while only values.*"
while only values {'first_time_contributors', 'first_time_contributors_new_to_github', 'all_external_contributors'} are allowed.
```

### KB-039 — an unknown role in ruleset bypass_actors validates, the apply crashes with a KeyError

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/ruleset.py:360-361`, `otterdog/models/ruleset.py:648-654`,
`otterdog/models/repo_ruleset.py:48-53`, `otterdog/operations/apply.py:146-153`.

Coverage finding F-12. A `#<role>` bypass actor is mapped with `cls._inverted_roles[role]`, which only knows
`RepositoryAdmin`, `Write`, `Maintain` and `OrganizationAdmin`. Validation does not check the role, so `#Admin` (or
a typo) validates and plans as a normal ruleset. Building the payload of the apply then raises KeyError, which is
not a RuntimeError: the apply stops at that patch, the patches after it are not applied, and the CLI exits 2.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [
    orgs.newRepo('r1') {
      rulesets: [orgs.newRepoRuleset('rs') { bypass_actors: ['#Admin'], required_status_checks: null }],
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code 0
  Validation succeeded
```

The payload of the apply, built by the model, offline:

```console
$ unshare -rn python - <<'EOF'      # run in the otterdog venv
import asyncio
from otterdog.models.repo_ruleset import RepositoryRuleset
ruleset = {"name": "rs", "target": "branch", "enforcement": "active", "include_refs": ["~DEFAULT_BRANCH"],
           "exclude_refs": [], "allows_creations": False, "allows_deletions": False, "allows_updates": True,
           "allows_force_pushes": False, "requires_commit_signatures": False, "requires_linear_history": False,
           "required_pull_request": None, "required_status_checks": None, "requires_deployments": False,
           "required_merge_queue": None}
async def main():
    for actors in (["#Maintain"], ["#Admin"]):
        model = RepositoryRuleset.from_model_data({**ruleset, "bypass_actors": actors})
        try:  # '#role' actors need no provider call
            print(actors, "->", (await model.to_provider_data("e2e-test-org", None))["bypass_actors"])
        except Exception as exc:
            print(actors, "->", type(exc).__name__, exc)
asyncio.run(main())
EOF
['#Maintain'] -> [{'actor_id': 2, 'actor_type': 'RepositoryRole', 'bypass_mode': 'always'}]
['#Admin'] -> KeyError 'Admin'
```

### KB-040 — a crashing sync check posts a misleading failure status

Status: **confirmed** · Upstream: none · Scenarios: `W-SYNC-FAILURE` (tests/webapp/test_commands.py)

Evidence: `otterdog/webapp/tasks/check_sync.py:135-139`, `otterdog/webapp/tasks/check_sync.py:225-234`,
`otterdog/webapp/tasks/__init__.py:67-78`.

Coverage finding F-13. When the sync plan raises (a rate limit, an unloadable BASE configuration, a GitHub error),
`Task.execute` passes the exception to `_post_execute`. `CheckConfigurationInSyncTask` then posts the sync context as
`failure` with the description "otterdog detected out of sync changes, but they will not prevent a successful merge".
Nothing was detected: the task failed. A required sync context (branch protection or ruleset) then blocks the merge,
contrary to the description. An out-of-sync result without an exception is `success` (KB-019). The pull request is
not updated either (`in_sync`, auto-merge), because that only happens in `_update_final_status`.

#### Reproduction

The webapp code of the image the harness built from 9bdeb75, without network. GitHub REST and MongoDB are replaced
by recorders, and the sync plan raises:

```console
$ docker run --rm --network none --read-only -v "$PWD/kb040.py:/tmp/kb040.py:ro" \
      --entrypoint /app/.venv/bin/python otterdog-e2e/otterdog:sha-9bdeb75 /tmp/kb040.py 2>/dev/null
failure  otterdog-sync: otterdog detected out of sync changes, but they will not prevent a successful merge
success  otterdog-sync: otterdog sync check failed, check comment history
```

`kb040.py`:

```python
import asyncio
from types import SimpleNamespace as NS
from quart import Quart
import otterdog.webapp.webhook  # noqa: F401 - the app's import order (circular imports)
import otterdog.webapp.tasks as tasks
import otterdog.webapp.tasks.check_sync as check_sync

statuses = []


async def nothing(*args, **kwargs):
    return None


async def record_status(org_id, repo, sha, state, context, description):
    statuses.append(f"{state:8} {context}: {description}")


async def rest_api(installation_id):  # GitHub REST: records the commit statuses
    return NS(commit=NS(create_commit_status=record_status), statistics=tasks.RequestStatistics(), close=nothing)


async def pre_execute(self):  # the pre-checks passed: the sync plan starts
    self._pull_request = NS(number=1, head=NS(sha="0" * 40))
    return True


async def execute(self):  # any exception of the sync plan (rate limit, unloadable BASE, ...)
    raise RuntimeError("API rate limit exceeded")


async def pull_request_model(*args, **kwargs):
    return NS(can_be_automerged=lambda: asyncio.sleep(0, result=False))


tasks.get_rest_api_for_installation = rest_api
for name in ("create_task", "schedule_task", "fail_task", "finish_task"):  # MongoDB
    setattr(tasks, name, nothing)
check_sync.update_or_create_pull_request = pull_request_model
Task = check_sync.CheckConfigurationInSyncTask
Task._pre_execute, Task._execute = pre_execute, execute


async def main():
    app = Quart("kb040")
    app.config["GITHUB_WEBHOOK_SYNC_CONTEXT"] = "otterdog-sync"
    async with app.app_context():
        task = Task(1, "e2e-test-org", "otterdog-configs", 1)
        await task.execute()  # Task.execute: the exception goes to _post_execute
        await task._update_final_status(False)  # for comparison: the out-of-sync result without an exception
    print("\n".join(statuses))


asyncio.run(main())
```

### KB-041 — two_factor_requirement is never read through the web UI

Status: **confirmed** · Upstream: none · Scenarios: `webui.kb.import-two-factor` (tests/web_ui/test_web_settings.py)

Evidence: `otterdog/resources/github-web-settings.jsonnet:40-42`, `otterdog/resources/schemas/settings.json:102-105`,
`otterdog/providers/github/__init__.py:33-35`, `otterdog/providers/github/__init__.py:116-120`,
`otterdog/providers/github/web.py:93-99`, `otterdog/models/organization_settings.py:68`,
e2e: `src/otterdog_e2e/webui/mapping.py` (the web-UI tier reads it through REST and never toggles it).

Found by the web-UI tier. The settings schema declares `two_factor_requirement` as a web setting, and the provider
requests it from the web client whenever `-n` is not given. The page definitions name it `two_factor_required`, and
the web client loads only the pages that define a requested name, so the security page is never loaded and the value
never comes back. `plan`, `import` and `show-live` without `-n` never see it (an imported configuration shows the
template's `true`, whatever GitHub has). The model marks it read-only, so otterdog never writes it either, and a drift
of this security setting goes unnoticed. REST reports it (`two_factor_requirement_enabled` of `GET /orgs/{org}`).

#### Reproduction

The page selection of the real web client, offline (no browser, no login):

```console
$ unshare -rn python - <<'EOF'      # run in the otterdog venv
from otterdog.providers.github import _SETTINGS_WEB_KEYS
from otterdog.providers.github.web import WebClient
web = WebClient(credentials=None)    # page selection only: no browser, no login
defined = {setting["name"] for page in web.web_settings_definition.values() for setting in page}
print("schema web keys without a page definition:", sorted(_SETTINGS_WEB_KEYS - defined))
for keys in ({"two_factor_requirement"}, {"members_can_delete_issues"}):
    print(sorted(keys), "-> pages loaded:", [url for url, _ in web._get_pages(keys)])
EOF
schema web keys without a page definition: ['discussion_source_repository_id', 'two_factor_requirement']
['two_factor_requirement'] -> pages loaded: []
['members_can_delete_issues'] -> pages loaded: ['settings/member_privileges']
```

`discussion_source_repository_id` is an internal key of the updates (`providers/github/__init__.py:34-35`).

### KB-042 — list-blueprints and approve-blueprints crash with ModuleNotFoundError without the webapp dependencies

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.blueprint-commands-without-webapp`

Evidence: `otterdog/operations/list_blueprints.py:17`, `otterdog/operations/approve_blueprints.py:16`,
`otterdog/cli.py:384`, `otterdog/cli.py:395`, `otterdog/webapp/__init__.py:18`.

Both operation modules import `otterdog.webapp.db.models` at module level. The published distribution excludes
`otterdog/webapp` (pyproject.toml `exclude`) and the webapp's dependencies (quart, quart-flask-patch, odmantic, ...) are
the optional `app` dependency group, so with the CLI alone the two commands die with a traceback (exit 1) before
anything else runs: `pip install otterdog` gives "No module named 'otterdog.webapp'", `poetry sync --only main` (the
harness's host install) "No module named 'quart_flask_patch'". Only the development setup (`make init`, every group)
and the webapp image can run them. The test asserts the documented refusal without `defaults.base_url` ("no base_url
set which is required when using operation '&lt;command&gt;'", exit 2).

#### Reproduction

```console
$ pip install <otterdog checkout>        # or: poetry sync --only main
$ otterdog list-blueprints -c otterdog.json e2e-test-org        # exit code 1, same for approve-blueprints
  File ".../otterdog/operations/list_blueprints.py", line 17, in <module>
    from otterdog.webapp.db.models import BlueprintStatusModel
ModuleNotFoundError: No module named 'otterdog.webapp'
```

### KB-043 — delete-file crashes with an UnboundLocalError when GitHub refuses the deletion

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.delete-file-refused`

Evidence: `otterdog/operations/delete_file.py:85-104`, `otterdog/providers/github/rest/content_client.py:145-149`.

`DeleteFileOperation.execute` assigns `deleted_file` inside a `try` whose `except RuntimeError` only records the error;
when the DELETE of the contents API fails (a protected default branch, missing permissions) the next line reads the
unbound variable. The intended 'failure deleting file' message and exit code 1 are unreachable: the command prints
"cannot access local variable 'deleted_file' where it is not associated with a value" and exits 2.

#### Reproduction

The DELETE answer is replaced by the RuntimeError the content client raises for a refused deletion (409); run in the
otterdog venv inside a workspace whose configuration declares the repository:

```python
# unshare -rn python repro.py
from otterdog import cli
from otterdog.providers.github.rest.content_client import ContentClient


async def delete_content(self, org_id, repo_name, path, message=None):
    raise RuntimeError(f"failed deleting content '{path}' in repo '{repo_name}':\n(status=409)")


ContentClient.delete_content = delete_content
cli.cli.main(["delete-file", "-c", "otterdog.json", "--local", "-r", "repo", "--path", "E2E.md", "e2e-test-org"])
```

```console
  Deleting file 'E2E.md' in repository 'e2e-test-org/repo': ╷
│ Error:   cannot access local variable 'deleted_file' where it is not associated with a value
╵                                                                     # exit code 2
```

### KB-044 — delete-file reports 'succeeded' for a file that does not exist

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.delete-file-missing`

Evidence: `otterdog/operations/delete_file.py:96-99`, `otterdog/providers/github/rest/content_client.py:130-139`.

`ContentClient.delete_content` returns False when the file is not found (no sha), and the operation prints
"succeeded" for both outcomes (only the color differs, green or red, invisible with NO_COLOR and in logs), exit 0.

#### Reproduction

As for KB-043, with the GET of the file answering 404:

```python
from otterdog import cli
from otterdog.providers.github.rest.content_client import ContentClient


async def get_content_object(self, org_id, repo_name, path, ref=None):
    raise RuntimeError("failed retrieving content: (status=404)")


ContentClient.get_content_object = get_content_object
cli.cli.main(["delete-file", "-c", "otterdog.json", "--local", "-r", "repo", "--path", "missing.md", "e2e-test-org"])
```

```console
  Deleting file 'missing.md' in repository 'e2e-test-org/repo': succeeded           # exit code 0
```

### KB-045 — dispatch-workflow exits 0 when GitHub refuses the dispatch

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.dispatch-workflow-exit-code`

Evidence: `otterdog/operations/dispatch_workflow.py:61-69`, `otterdog/providers/github/rest/repo_client.py:1361-1366`.

`RepoClient.dispatch_workflow` returns False for any answer other than 204 (unknown workflow, a workflow without
`workflow_dispatch`, missing permissions); the operation prints "failed to dispatch workflow '&lt;wf&gt;' for repo
'&lt;repo&gt;'" and still returns 0. An unknown repository, by contrast, raises and exits 2.

#### Reproduction

```python
from otterdog import cli
from otterdog.providers.github.rest.repo_client import RepoClient


async def dispatch_workflow(self, org_id, repo_name, workflow_name):
    return False  # GitHub answered 404 / 422


RepoClient.dispatch_workflow = dispatch_workflow
cli.cli.main(
    ["dispatch-workflow", "-c", "otterdog.json", "--local", "-r", "repo", "--workflow", "missing.yml", "e2e-test-org"]
)
```

```console
  failed to dispatch workflow 'missing.yml' for repo 'repo'                          # exit code 0
```

### KB-046 — push-config of an invalid configuration prints 'no changes, nothing pushed' and exits 0

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.push-config-invalid-exit-code`

Evidence: `otterdog/operations/push_config.py:186-192`, `otterdog/operations/push_config.py:138-141`.

push-config validates the local configuration through the local-plan diff against the current definition; with
validation errors `_display_diff` returns False and the operation reports "no changes, nothing pushed" with exit 0,
even with `-f`. Nothing invalid is pushed, but scripts cannot tell a refused push from an unchanged configuration.

#### Reproduction

The HEAD has a repository with `topics: ["Invalid_Topic"]`, `base.jsonnet` is a valid current definition:

```python
from otterdog import cli
from otterdog.providers.github import GitHubProvider
from otterdog.providers.github.rest.repo_client import RepoClient


async def default_branch(self, org_id, repo_name):
    return "main"


async def get_content(self, org_id, repo_name, path, ref=None):
    return open("base.jsonnet").read()


RepoClient.get_default_branch = default_branch
GitHubProvider.get_content = get_content
cli.cli.main(["push-config", "-c", "otterdog.json", "--local", "-f", "-m", "x", "e2e-test-org"])
```

```console
│ Error:   repository[name="repo"] has defined an invalid topic 'Invalid_Topic'. ...
    Planning aborted due to validation errors.
  no changes, nothing pushed                                                          # exit code 0
```

### KB-047 — install-deps exits 0 when the Playwright browser installation fails

Status: **confirmed** · Upstream: none · Scenarios: `webui.kb.install-deps-exit-code`

Evidence: `otterdog/cli.py:953-969`.

`install_deps` runs `<python> -m playwright install firefox`, prints "could not install required dependencies:
&lt;status&gt;" for a non-zero status and returns normally, so the command exits 0 and a setup script goes on without a
browser; every later web-UI command then fails.

#### Reproduction

```console
$ PLAYWRIGHT_BROWSERS_PATH=$(mktemp -d) unshare -rn otterdog install-deps     # no network: the download fails
Failed to install browsers
Error: Failed to download Firefox 155.0 (playwright firefox v1543), caused by
│ Error:   could not install required dependencies: 1
$ echo $?
0
```

### KB-048 — a re-import drops the secret of a webhook whose URL is masked

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.import-masked-webhook-secret`

Evidence: `otterdog/operations/import_configuration.py:103-117`, `otterdog/models/repository.py:1044-1049`,
`otterdog/models/github_organization.py:365-369`.

`import` over an existing configuration copies the secrets of the previous file (`copy_secrets`) and then masks the
webhook URLs that end with `*`. The webhook secrets are looked up by the exact URL of the LIVE webhook, which never
equals the masked URL of the previous file, and the masking only happens afterwards: the masked webhook comes out with
the dummy secret GitHub returns (`********`) while every other webhook keeps its secret.

#### Reproduction

`load_from_provider` returns a "live" org read from `live.jsonnet` (secrets `********`, webhook
`.../import/masked-token`); the existing file has the literal secrets and the masked URL `.../import/masked*`:

```python
from otterdog import cli
from otterdog.models.github_organization import GitHubOrganization


async def load_from_provider(cls, project_name, github_id, jsonnet_config, provider, *args, **kwargs):
    return GitHubOrganization.load_from_file(github_id, "live.jsonnet")


GitHubOrganization.load_from_provider = classmethod(load_from_provider)
cli.cli.main(["import", "-c", "otterdog.json", "--local", "-f", "-n", "e2e-test-org"])
```

```console
  Copying secrets from previous configuration.
  Masking webhooks from previous configuration... 1 URLs have been masked.
# the new file: repo secret 'e2e-dummy-x', webhook .../import/plain secret 'e2e-dummy-x',
#               webhook .../import/masked* secret '********'
```

### KB-049 — fetch-config -r reports that it fetched from the default branch

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.fetch-config-ref-message`

Evidence: `otterdog/operations/fetch_config.py:80-91`, `otterdog/operations/fetch_config.py:104-109`.

With `-r <ref>` the content of the ref is fetched, but the message only distinguishes pull requests from everything
else: "organization definition fetched from default branch to '&lt;file&gt;'".

#### Reproduction

```python
from otterdog import cli
from otterdog.providers.github import GitHubProvider


async def get_content(self, org_id, repo_name, path, ref=None):
    print(f"(content of ref {ref!r})")
    return "// fetched\n"


GitHubProvider.get_content = get_content
cli.cli.main(["fetch-config", "-c", "otterdog.json", "--local", "-f", "-r", "e2e/branch", "-s", "-REF", "e2e-test-org"])
```

```console
(content of ref 'e2e/branch')
  organization definition fetched from default branch to './orgs/e2e-test-org/e2e-test-org.jsonnet-REF'
```

### KB-050 — free text is printed as rich markup (list-advisories, show --markdown, validation messages, canonical form)

Status: **confirmed** · Upstream: none · Scenarios: `cli.kb.list-advisories-markup` (tests/cli/test_commands_read.py),
`O-KB-SHOW-MARKDOWN-LINKS` (tests/offline/test_cli_basics.py), `O-KB-VALIDATION-MARKUP` (tests/offline/test_cli_markup.py),
step `bracketed-description` of `O-CANON` (scenarios/offline/canonical-diff.yaml)

Evidence: `otterdog/operations/list_advisories.py:140-146`, `otterdog/operations/show.py:177-182`,
`otterdog/operations/show.py:207`, `otterdog/utils.py:301-315`, `otterdog/logging.py:174-198`,
`otterdog/utils.py:173-221`, `otterdog/models/github_organization.py:394-395`, `otterdog/operations/canonical_diff.py:68`,
`otterdog/operations/import_configuration.py:122`.

otterdog prints through rich, whose console interprets `[word]`, `[/]` and `[link=...]` as markup. #440 (v1.1.0)
escapes the values of the plan and show printers (`regression.440-rich-escaping`, `O-LPLAN-ESCAPING`), but other
outputs still hand free text to the console unescaped (follow-up of #440):

- `list-advisories` joins its CSV row and prints it with `IndentingPrinter.println` (only `print_dict`, used for `-d`,
  escapes): a summary `[draft] x` loses `[draft]`, and `[/]` raises a MarkupError (the command exits 2). Advisory
  summaries are free text of repository maintainers.
- `show --markdown` writes its pages through the same printer: the link texts `[<repo>]` of the repository page title
  and of the Repositories table of `configuration.md` are swallowed as style tags.
- validation messages are rich table cells (`_print_message`): a message quoting a value with markup loses it.
- the canonical form of a configuration: `GitHubOrganization.to_jsonnet` writes into a `StringIO` through an
  `IndentingPrinter`, i.e. a rich console, and `write_patch_object_as_json` prints the `json.dumps` of every value
  unescaped. A description `[e2e] canonical form` becomes `" canonical form"` in the canonical form, so
  `canonical-diff` of an already canonical file is not empty (found offline by `O-CANON`; same result on 1.6.0, 1.6.1
  and main at 9bdeb75 and b5f7bb1).
  A value holding `[/]` makes `canonical-diff` crash (`rich.errors.MarkupError: closing tag '[/]' ... has nothing to
  close`, checked offline on 1.6.1). `import` writes the same `to_jsonnet` output (`import_configuration.py:122`), so
  an imported configuration loses the bracketed words of its values (the next apply changes them on GitHub) and `[/]`
  makes the import crash (read from the code: import needs GitHub, it is not run offline).

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [orgs.newRepo('repo') { squash_merge_commit_title: '[bold]NOPE[/bold]' }],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org
│ Error:   repository[name="repo"] has 'squash_merge_commit_title' of value 'NOPE', while only values ('PR_TITLE' | 'COMMIT_OR_PR_TITLE') are allowed.
```

With `_repositories+: [orgs.newRepo('repo')]`:

```console
$ otterdog show -c otterdog.json --local --markdown --output-dir md e2e-test-org
$ grep -n '^# Repo' md/repo-repo.md
6:# Repo (https://github.com/e2e-test-org/repo)
$ grep -n 'repo-repo.md' md/configuration.md
64:    | (repo-repo.md)  [:octicons-link-external-16:](https://github.com/e2e-test-org/repo){:target='_blank'} | ...
```

```python
from otterdog.logging import CONSOLE_STDOUT
from otterdog.utils import IndentingPrinter

printer = IndentingPrinter(CONSOLE_STDOUT)
printer.println('"x","[draft] summary","y"', soft_wrap=True)  # prints "x"," summary","y"
printer.println('"x","a [/] b","y"', soft_wrap=True)  # rich.errors.MarkupError: closing tag '[/]' ... nothing to close
```

Canonical form (`scenarios/offline/files/canonical-form.jsonnet` with `repo_description: "[e2e] canonical form"`, the
labels of the diff are swapped, KB-010):

```console
$ otterdog canonical-diff -c otterdog.json --local e2e-offline
--- canonical
+++ original
@@ -3,7 +3,7 @@
 orgs.newOrg('e2e-offline', 'e2e-offline') {
   _repositories+:: [
     orgs.newRepo('e2e-spduo000-canon') {
-      description: "[e2e] canonical form"
+      description: " canonical form"
```

(the console prints the `-` line as `" canonical form"` too: the diff lines go through the same console.)

### KB-051 — GitHub App installations are read without pagination

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/providers/github/rest/org_client.py:484-491`, `otterdog/models/github_organization.py:574-578`,
`otterdog/operations/list_apps.py:66`, "openapi: GET /orgs/{org}/installations per_page default 30, max 100".

`OrgClient.get_app_installations` reads `GET /orgs/{org}/installations` with `request_json` (one page of 30, no
`per_page`). `list-apps` lists only those, and `load_from_provider` builds the integration id -> app slug map of the
ruleset status checks from them: a check of an app beyond the first 30 reads back as `<integration id>:<context>` and a
configuration written with the slug never converges (as in KB-054). Not reproducible on the test organizations (far
fewer than 30 installations); `cli.list-apps` compares the listing with the paginated oracle and would show it.

### KB-052 — a bypass actor written as `<actor>:always` never converges

Status: **confirmed** · Upstream: none · Scenarios: none (step `explicit-always` of `cli.ruleset.bypass` declares it)

Evidence: `otterdog/models/ruleset.py:565-567`, `otterdog/models/ruleset.py:636-645`,
`docs/reference/organization/repository/bypass-actor.md:20-30`.

The reference documents the explicit mode `<actor>:always` (example `#Maintain:always`). The write path accepts it,
but the read-back adds the `:<mode>` suffix only when the mode is not `always`, so the live ruleset reads `#Maintain`
and every plan shows the configured `#Maintain:always` as a change.

#### Reproduction

otterdog's own read-back of a live ruleset (no network):

```python
from otterdog.models.repo_ruleset import RepositoryRuleset
from otterdog.utils import is_different_ignoring_order

live = {
    "id": 1,
    "name": "r",
    "node_id": "n",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "bypass_actors": [{"actor_id": 2, "actor_type": "RepositoryRole", "bypass_mode": "always"}],
    "rules": [],
}
ruleset = RepositoryRuleset.from_provider_data("org", live)
print(ruleset.bypass_actors)  # ['#Maintain']
print(is_different_ignoring_order(["#Maintain:always"], ruleset.bypass_actors))  # True: never converges
```

### KB-053 — merge_commit_message is sent without merge_commit_title

Status: **suspected** · Upstream: none · Scenarios: none (step `merge-message` of `cli.repo.merge-messages` declares it)

Evidence: `otterdog/models/repository.py:1330-1355`, `otterdog/models/repository.py:1514-1519`, "openapi: PATCH
/repos/{owner}/{repo} merge_commit_title: Required when using merge_commit_message".

`_include_squash_merge_patch_required_properties` completes the squash pair (title and message are always sent
together), but nothing completes the merge-commit pair. A change of `merge_commit_message` alone is PATCHed without
`merge_commit_title`, which GitHub's REST description marks as required with it. Whether GitHub refuses the PATCH
(422) or ignores the message needs a live org.

### KB-054 — ruleset status checks bound to an app spelled in a form otterdog does not read back never converge

Status: **confirmed** · Upstream: none · Scenarios: none (steps `actions-slug` of `cli.ruleset.status-checks` and
`app-id` of `cli.protection.app-checks` declare it)

Evidence: `otterdog/models/github_organization.py:810-816`, `otterdog/models/ruleset.py:145-151`,
`otterdog/models/ruleset.py:177-211`, `docs/reference/organization/repository/status-check.md:7`.

The write path resolves `<app-slug>:<context>` through `GET /apps/{slug}` (any public app), and accepts
`<integration id>:<context>`. The read-back adds the app slug only for apps INSTALLED in the organization (the slug
map of `load_from_provider`); otherwise it keeps the integration id. So the documented `github-actions:build` (GitHub
Actions is never an org installation) reads back as `15368:build`, and `<id of an installed app>:<context>` reads back
as `<slug>:<context>`: both plans never converge. `<installed slug>:<context>` and `<id of a non-installed
app>:<context>` converge (#491, #695, #700).

#### Reproduction

```python
from otterdog.models.repo_ruleset import RepositoryRuleset
from otterdog.utils import is_different_ignoring_order

checks = [
    {"context": "e2e/id", "integration_id": 123456, "app_slug": "e2e-app"},  # installed: slug added
    {"context": "build", "integration_id": 15368},  # GitHub Actions: id kept
]
live = {
    "id": 1,
    "name": "r",
    "node_id": "n",
    "target": "branch",
    "enforcement": "active",
    "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
    "bypass_actors": [],
    "rules": [
        {
            "type": "required_status_checks",
            "parameters": {
                "strict_required_status_checks_policy": True,
                "do_not_enforce_on_create": False,
                "required_status_checks": checks,
            },
        }
    ],
}
ruleset = RepositoryRuleset.from_provider_data("org", live)
print(ruleset.required_status_checks.status_checks)  # ['e2e-app:e2e/id', '15368:build']
print(
    is_different_ignoring_order(["123456:e2e/id", "github-actions:build"], ruleset.required_status_checks.status_checks)
)  # True
```

### KB-055 — nested ruleset messages name the repository twice

Status: **confirmed** · Upstream: none · Scenarios: none (`O-VAL-RULESET-NESTED` asserts the messages after the header)

Evidence: `otterdog/models/ruleset.py:57-73`, `otterdog/models/ruleset.py:128-136`, `otterdog/models/ruleset.py:240-272`,
`otterdog/models/ruleset.py:451-458`.

`Ruleset.validate` passes its own parent (the repository) to the validators of `required_pull_request`,
`required_status_checks` and `required_merge_queue`, which build their header with
`parent_object.get_model_header(parent_object)`: the repository's header with the repository as parent, instead of
the ruleset's header. Same root cause as KB-008, where the organization parent of an org ruleset crashes instead.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  _repositories+: [
    orgs.newRepo('r') {
      rulesets: [orgs.newRepoRuleset('rs') { include_refs: ['~DEFAULT_BRANCH'],
                                             required_pull_request+: { required_approving_review_count: 11 } }],
    },
  ],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org
│ Error:   repository[name="r", repository=r] has 'required_pull_request.required_approving_review_count' of value '11' while only integers in the range [0, 10] are allowed.
```

### KB-056 — local-plan diffs objects whose secret is a dummy

Status: **confirmed** · Upstream: none · Scenarios: `O-KB-LPLAN-DUMMY-SECRETS` (tests/offline/test_cli_local_plan_flags.py); step `dummy-skipped` of `O-LPLAN-FORCED-SECRETS`

Evidence: `otterdog/operations/local_plan.py:82-87`, `otterdog/models/secret.py:69-72`, `otterdog/models/secret.py:87-88`,
`otterdog/models/secret.py:125-147`, `otterdog/models/webhook.py:80-81`, `otterdog/models/webhook.py:155-157`,
`otterdog/webapp/tasks/validate_pull_request.py:159`.

plan, apply and local-apply skip every secret and webhook whose configured value is the dummy `********`
(`include_for_live_patch`, "will be skipped" Info). local-plan first replaces the dummies by `<DUMMY>` on both sides
(`preprocess_orgs`), after which they no longer look like dummies: showing their addition and removal is intended
(#245, 46818e7), but local-plan also shows CHANGES of such webhooks (e.g. new events of one of the many hooks kept with
a dummy secret) and, with `--update-secrets` / `--update-webhooks`, forced updates `! value = "<DUMMY>" -> "<DUMMY>"`
that no apply performs. The webapp validates pull requests with local-plan, so a PR comment can announce changes the
merge never applies.

#### Reproduction

HEAD and BASE both contain `secrets+: [orgs.newOrgSecret('E2E_X') { value: '********' }]`:

```console
$ otterdog local-plan -c otterdog.json --local --update-secrets e2e-test-org
  ! org_secret[name="E2E_X"] {
    ! value                 = "<DUMMY>" -> "<DUMMY>"
  Plan: 0 to add, 4 to change, 0 to delete.
$ echo n | otterdog local-apply -c otterdog.json --local -n --update-secrets e2e-test-org
  No changes required.
```

A webhook with `secret: '********'` in both files whose events change (`['push']` -> `['push', 'pull_request']`):
local-plan prints `~ org_webhook[url="..."] { ~ events = [ + "pull_request" ] }` while `validate -v` says the hook
"will be skipped".

### KB-057 — webhook secrets get a weaker check than secrets

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/webhook.py:83-93`, `otterdog/models/secret.py:51-62`, `otterdog/config.py:230-243`.

Secrets warn "has a value '...' that does not use a credential provider." unless the value starts with a supported
provider (`pass`, `bitwarden`, `vault`). Webhook secrets only check that a `:` is present: an unknown prefix such as
`foo:e2e/b` validates silently and the apply then sends the literal value (`get_secret` returns it for an unknown
provider). A value with several `:` validates too and makes the apply crash on the unpacking of `re.split` (the
webhook side of KB-025, where secrets already crash at validation).

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free' },
  secrets+: [orgs.newOrgSecret('E2E_X') { value: 'foo:e2e/b' }],
  webhooks+: [orgs.newOrgWebhook('https://otterdog-e2e.invalid/x/h') { events+: ['push'], secret: 'foo:e2e/b' }],
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org
│ Warning:   org_secret[name="E2E_X"] has a value 'foo:e2e/b' that does not use a credential provider.
  Validation succeeded': 0 info(s), 1 warning(s), 0 error(s)          # nothing for the webhook secret
```

### KB-058 — topics of an archived repository are planned and sent

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/repository.py:137-163`, `otterdog/models/repository.py:782-790`,
`otterdog/providers/github/rest/repo_client.py:119`, `otterdog/providers/github/rest/repo_client.py:139-140`.

While a repository stays archived, the diff ignores the fields of `_unavailable_fields_in_archived_repos`
(description, merge settings, security, has_wiki, ...). `topics` is not in that set: a topics change of an archived
repository is planned (`~ topics = [ ~ "a" -> "b" ]`, offline with local-plan) and the apply calls
`PUT /repos/{org}/{repo}/topics`, which GitHub presumably refuses for a read-only repository (403). `O-LPLAN-ARCHIVED`
leaves topics out; a live run must confirm GitHub's answer.

### KB-059 — /myprojects answers 500 without OAuth configuration

Status: **confirmed** · Upstream: none · Scenarios: `O-KB-WEB-LOGIN-REQUIRED` (tests/offline/test_webapp_contract.py)

Evidence: `otterdog/webapp/__init__.py:42-64`, `otterdog/webapp/home/routes.py:153-166`,
`otterdog/webapp/templates/home/page-401.html:3`.

QuartAuth is only initialized when `GITHUB_OAUTH_CLIENT_ID` is set. Without it, the `login_required` decorator of
`/myprojects` raises `KeyError: 'QUART_AUTH'` and the page answers the 500 page instead of 401. A deployment without
OAuth (the e2e offline stack, a webapp used only for its App) shows an error page for the "My Projects" link. Once
the 401 page renders, its `<title>` says "Error 403" (`page-401.html:3`) while its body says "Error 401 - Access
Denied" (cosmetic).

#### Reproduction

The offline webapp stack of the harness (dummy credentials, no OAuth variables), then:

```console
$ curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:<port>/myprojects
500
$ docker compose logs webapp | grep QUART_AUTH
KeyError: 'QUART_AUTH'
```

### KB-060 — a form-encoded delivery without `payload` answers 500

Status: **confirmed** · Upstream: none · Scenarios: `O-KB-WEB-FORM-WITHOUT-PAYLOAD` (tests/offline/test_webapp_contract.py)

Evidence: `otterdog/webapp/webhook/github_webhook.py:83-87`.

The receiver reads `formdata["payload"]` without checking it: a correctly signed `application/x-www-form-urlencoded`
delivery without that field raises KeyError and answers 500, while every other malformed delivery gets a 400 that
names the problem (missing header, empty body, undecodable JSON).

#### Reproduction

Offline webapp stack, then with the harness injector (signed over the raw body):

```python
injector.deliver("ping", body=b"other=1", content_type="application/x-www-form-urlencoded").status_code  # 500
```

### KB-061 — a webapp that refuses its configuration at boot exits 0

Status: **confirmed** · Upstream: none · Scenarios: `O-KB-WEB-BOOT-EXIT-STATUS` (tests/offline/test_webapp_runtime.py)

Evidence: `otterdog/webapp/config.py:47-52`, `otterdog/webapp/config.py:115`.

Since #712 the webapp refuses empty required settings at import (`ValueError: <NAME> must not be empty`). The image
starts hypercorn with 4 workers (`docker/hypercorn-cfg.toml`); the refusal kills the workers and the process exits
with status 0, so a supervisor watching exit codes (`restart: on-failure`, CI smoke checks) sees a clean stop.
`test_required_setting_is_refused_at_boot` asserts the refusal itself, `O-KB-WEB-BOOT-EXIT-STATUS` the exit status
(`WebappStack.service_states`).

#### Reproduction

```console
$ docker run --rm --network none -e BASE_URL=http://localhost -e APP_ROOT=/tmp/approot -e GITHUB_APP_ID=1 \
      -e GITHUB_APP_PRIVATE_KEY=e2e-dummy -e DEPENDENCY_TRACK_URL=http://dtrack.invalid \
      -e DEPENDENCY_TRACK_TOKEN=e2e-dummy -e GITHUB_WEBHOOK_SECRET=e2e-dummy -e GITHUB_WEBHOOK_SYNC_CONTEXT= \
      otterdog-e2e/otterdog:sha-9bdeb75; echo "exit status: $?"
ValueError: GITHUB_WEBHOOK_SYNC_CONTEXT must not be empty
exit status: 0
```

Same with the v1.6.1 image.

### KB-062 — the custom property value type 'url' is refused

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/custom_property.py:52-58`, `otterdog/models/custom_property.py:32-46`, "openapi:
components/schemas/custom-property value_type enum [string, single_select, multi_select, true_false, url]".

GitHub's custom properties have five value types; otterdog validates against four and does not model
`require_explicit_values`. An organization that defines a `url` property (e.g. in the GitHub UI) cannot be validated:
an import writes the property and the next validation fails.

#### Reproduction

```jsonnet
orgs.newOrg('e2e-test-org') {
  settings+: { plan: 'free', custom_properties+: [orgs.newCustomProperty('link') { value_type: 'url', values_editable_by: 'org_actors' }] },
}
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org
│ Error:   custom_property[name="link"] has 'value_type' set to 'url', while only values ('string' | 'single_select' | 'multi_select' | 'true_false') are allowed.
```

### KB-063 — list replacements are printed inconsistently

Status: **confirmed** · Upstream: none · Scenarios: none

Evidence: `otterdog/operations/__init__.py:392-410`.

The list printer of plan output iterates `range(i1, min(diff_i, diff_j))` for a replaced block instead of
`range(min(diff_i, diff_j))`: a replacement is shown as `~ "x" -> "y"` only when it starts at the first element of the
sorted lists; anywhere else it becomes a removal and an addition (cosmetic, the change itself is right).

#### Reproduction

BASE topics `['a', 'b', 'x']` and `['x']`, HEAD topics `['a', 'b', 'y']` and `['y']` (two repositories):

```console
$ otterdog local-plan -c otterdog.json --local -s -BASE e2e-test-org
  ~ repository[name="r"] {
    ~ topics = [
      - "x"
      + "y"
  ~ repository[name="s"] {
    ~ topics = [
      ~ "x" -> "y"
```

### KB-064 — clearing a value sends JSON null

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/models/__init__.py:610-617`, `otterdog/models/webhook.py:126-141`, "openapi: PATCH /orgs/{org}
company, email, location, twitter_username, blog of type string", "openapi: components/schemas/webhook-config-secret
type string".

A key going back to null (an org profile field, a webhook secret removed from the configuration) is sent as JSON
`null`, where GitHub documents strings. If GitHub refuses or ignores null, the profile cannot be cleared and a webhook
secret is never removed (a perpetual `- secret` plan). The live steps `restore` of `cli.org.profile`,
`remove-secret` of `cli.repo.webhook-secret` and `H-ORG-HOOK-SECRET` assert the documented outcome and will show it.

### KB-065 — settings the create endpoint does not document are never re-applied

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/providers/github/rest/repo_client.py:254-265`, `otterdog/providers/github/rest/repo_client.py:286-296`,
"openapi: POST /orgs/{org}/repos request body has no allow_forking, allow_update_branch, has_discussions".

A new repository is created with `POST /orgs/{org}/repos` carrying every configured key; only the keys of
`update_keys` (security, topics, pages, custom properties, ...) are re-applied by a PATCH afterwards. `allow_forking`,
`allow_update_branch` and `has_discussions` are not documented by the create endpoint and not re-applied, so a new
repository may come up with GitHub's defaults and converge only at the next apply. The live create steps of
`cli.repo.features` and `cli.org.member-privileges` converge right after the creation and will show it.

### KB-066 — a copied sync status always reads 'completed successfully'

Status: **suspected** · Upstream: none · Scenarios: `W-SYNC-PROPAGATION-DRIFT` (tests/webapp/test_pr_validation.py)

Evidence: `otterdog/webapp/tasks/check_sync.py:100-124`, `otterdog/webapp/tasks/check_sync.py:236-257`.

For a commit pushed within an hour of the previous one, the sync check copies the previous non-pending sync status
instead of running: `_update_final_status(commit_status[0]["state"] == "success")`. Both final results have the state
`success` (in sync, and out of sync too, see KB-019), so the copy always posts "otterdog sync check completed
successfully" and records `in_sync: true`, even when the previous status said "otterdog sync check failed, check
comment history". Established from the source; the webapp test reproduces it live (drifted org, two commits).

### KB-067 — the sync check of an invalid main reports in sync

Status: **confirmed** · Upstream: none · Scenarios: `W-SYNC-INVALID-MAIN` (tests/webapp/test_commands.py)

Evidence: `otterdog/webapp/tasks/check_sync.py:163-169`, `otterdog/operations/plan.py:121-126`,
`otterdog/operations/diff_operation.py:160-176`, `otterdog/operations/diff_operation.py:225-230`.

`CheckConfigurationInSyncTask` starts with `config_in_sync = True` and lets the plan callback set it. When the
configuration of main fails validation, the plan aborts before reading GitHub and calls the callback with an empty diff
(in sync); when it fails to load, the callback is never called. Either way the sync status says "otterdog sync check
completed successfully" and `in_sync` is true although nothing was compared.

#### Reproduction

otterdog's PlanOperation driven like the task (local mode, no network), on a configuration with validation errors and
then on one that does not evaluate:

```python
import asyncio, io
from otterdog.config import OtterdogConfig
from otterdog.operations.plan import PlanOperation
from otterdog.utils import IndentingPrinter

config = OtterdogConfig.from_file("otterdog.json", True)
calls = []
operation = PlanOperation(True, "*", False, False, False, "")
operation.set_callback(lambda org, diff, validation, patches: calls.append(diff.total_changes(True)))
operation.init(config, IndentingPrinter(io.StringIO()))
status = asyncio.run(operation.execute(config.get_organization_config("e2e-test-org")))
print(status, calls)  # validation errors: '2 [0]' (in sync); load failure: '1 []' (stays in sync)
```

### KB-068 — a changed wildcard webhook is PATCHed with the pattern as its url

Status: **confirmed** · Upstream: none · Scenarios: `W-MERGE-TEAM-HOOK` (tests/webapp/test_merge_apply.py)

Evidence: `otterdog/models/__init__.py:825-839`, `otterdog/models/repo_webhook.py:64-72`,
`otterdog/models/organization_webhook.py:58-65`, `otterdog/models/webhook.py:126-141`.

A webhook url ending with `*` matches a live hook by prefix (#84), which hides a token at the end of the url. A
change of such a hook (events, active, ...) is applied with `expected_object.to_provider_data(...)`: the whole
configured hook, whose `config.url` is the pattern itself and whose `config.secret` is null. The live url, and its
hidden part, is overwritten (or GitHub refuses the url and the patch fails). This affects the CLI apply and the
webapp's local-apply, for organization and repository hooks.

#### Reproduction

```console
$ python -c "
import asyncio
from otterdog.models.repo_webhook import RepositoryWebhook as W
w = W.from_model_data({'url': 'https://otterdog-e2e.invalid/x/hook-*', 'events': ['push'], 'active': True,
                       'content_type': 'json', 'insecure_ssl': '0', 'secret': None})
print(asyncio.run(w.to_provider_data('o', None)))"
{'events': ['push'], 'active': True, 'config': {'url': 'https://otterdog-e2e.invalid/x/hook-*', 'content_type': 'json', 'insecure_ssl': '0', 'secret': None}}
```

### KB-069 — one unreadable definition file fails the whole blueprint or policy fetch

Status: **confirmed** · Upstream: none · Scenarios: `W-BP-LOAD-YAML` (tests/webapp/test_blueprints.py),
`W-POL-LOAD-MALFORMED` (tests/webapp/test_policies.py)

Evidence: `otterdog/webapp/tasks/fetch_policies.py:70-85`, `otterdog/webapp/tasks/fetch_blueprints.py:78-93`,
`otterdog/webapp/policies/__init__.py:67-74`, `otterdog/webapp/blueprints/__init__.py:116-124`,
`otterdog/webapp/utils.py:249-263`, `otterdog/webapp/utils.py:294-310`.

The fetch loops catch only some exceptions per file: FetchPoliciesTask `(ValueError, RuntimeError)`, so a policy file
without `type` or `config` (KeyError in `read_policy`) fails the task; neither task catches `yaml.YAMLError` or a
document that is not a mapping (TypeError). One invalid file in `otterdog/blueprints` or `otterdog/policies` of a
config repository therefore keeps every org definition from (re)loading. The global loaders of `/internal/init` have
the same narrow `except`.

#### Reproduction

In the webapp image (`docker run --rm --network none --entrypoint /app/.venv/bin/python otterdog-e2e/otterdog:sha-9bdeb75`):

```python
from otterdog.webapp.policies import read_policy

try:
    read_policy("p", {"type": "macos_large_runners"})  # a policy file without 'config'
except (ValueError, RuntimeError):
    print("skipped like a bad file")
except Exception as ex:
    print("fails the task:", type(ex).__name__, ex)  # fails the task: KeyError 'config'
```

### KB-070 — a definition change of several fields is stored one field per fetch

Status: **confirmed** · Upstream: none · Scenarios: `W-BP-UPDATE` (tests/webapp/test_blueprints.py)

Evidence: `otterdog/webapp/db/service.py:943-958`.

`update_or_create_blueprint` chains `recheck = recheck or update_if_changed(blueprint_model, <attr>, ...)` over path,
name, description and config: the `or` short-circuits after the first changed attribute. A commit changing the name
and the repository selector of a definition is stored with the new name and the OLD config, which the next
`/internal/check` evaluates; the config follows only with the next fetch.

#### Reproduction

`update_or_create_blueprint` run in the webapp image with the MongoDB calls stubbed (the probe used for the e2e
test): after the fetch of a definition whose name and `repo_selector` changed, the stored model has the new name and
the previous `repo_selector`; a second identical fetch stores the selector.

### KB-071 — a second fetch drops the pending recheck of a changed definition

Status: **confirmed** · Upstream: none · Scenarios: `W-BP-RECHECK-LOST` (tests/webapp/test_blueprints.py)

Evidence: `otterdog/webapp/db/service.py:958`, `otterdog/webapp/internal/routes.py:83-89`,
`otterdog/webapp/blueprints/__init__.py:84-91`.

Every FetchBlueprintsTask assigns `recheck_needed = <did this fetch change something>` instead of keeping a pending
`True` until `/internal/check` consumes it. A second fetch before the next check (an `/internal/init`, another push
touching the definitions) clears it, so repositories in status success, remediation_prepared or dismissed are not
re-evaluated: a changed strict required file is never rewritten.

#### Reproduction

Same probe as KB-070: a fetch changing the description sets `recheck_needed: True`, the next fetch of the unchanged
definition sets it back to `False` before any check ran.

### KB-072 — a blueprint whose type changes breaks /internal/check

Status: **confirmed** · Upstream: none · Scenarios: `W-BP-TYPE-CHANGE` (tests/webapp/test_blueprints.py)

Evidence: `otterdog/webapp/db/models.py:245-258`, `otterdog/webapp/db/service.py:925-961`,
`otterdog/webapp/internal/routes.py:61-93`, `otterdog/webapp/blueprints/__init__.py:173-181`.

`BlueprintId`, the primary key of `BlueprintModel`, includes the blueprint type, and `update_or_create_blueprint` looks
the model up by organization and id and never re-keys it. When a definition keeps its id and changes its type (an
edited file, or a global and an org definition sharing an id), the stored type stays the old one; once the config is
replaced, `create_blueprint_from_model` raises a pydantic ValidationError inside `/internal/check`, which has no
per-blueprint error handling: every call answers 500, the broken blueprint never gets `last_checked`, stays first, and
no blueprint of any organization is evaluated any more.

#### Reproduction

In the webapp image with a seeded database (offline, GitHub hosts pinned to 127.0.0.1): a `required_file` blueprint
whose stored config is replaced by an `append_configuration` one makes `create_blueprint_from_model` raise
`ValidationError: 1 validation error for RequiredFileBlueprint`, and `/internal/check` answers 500 on repeated calls.

### KB-073 — pin_workflow skips workflows that reference a docker:// action

Status: **confirmed** · Upstream: none · Scenarios: `W-BP-PIN` (tests/webapp/test_blueprints.py; the scoped xfail only
covers its last check)

Evidence: `otterdog/webapp/tasks/blueprints/pinning/actions.py:44-46`,
`otterdog/webapp/tasks/blueprints/pin_workflow.py:53-61`, `otterdog/webapp/tasks/blueprints/pin_workflow.py:99-110`,
`otterdog/webapp/tasks/blueprints/check_scorecard_integration.py:47-79`.

`ActionRef.of_pattern` calls `next()` over the subclasses without a default: for `docker://...` no subclass matches and
StopIteration escapes into the coroutine, which Python turns into `RuntimeError('coroutine raised StopIteration')`.
PinWorkflowTask skips the whole file on RuntimeError, so the other unpinned actions of that workflow stay unpinned while
the blueprint can report success; CheckScorecardIntegrationTask turns the same error into a failed check.

#### Reproduction

In the webapp image: pinning a workflow whose steps use `actions/checkout@v4` and `docker://alpine:3.19` raises
`RuntimeError coroutine raised StopIteration`, which `except RuntimeError` in `PinWorkflowTask` swallows.

### KB-074 — /internal/init records every merged pull request as completed

Status: **suspected** · Upstream: none · Scenarios: `W-RT-INIT-APPLY-STATUS` (tests/webapp/test_runtime.py)

Evidence: `otterdog/webapp/tasks/fetch_all_pull_requests.py:50-62`, `otterdog/webapp/db/service.py:538-539`,
`otterdog/webapp/tasks/complete_pull_request.py:60-66`, `otterdog/webapp/tasks/apply_changes.py:95-101`,
`otterdog/webapp/internal/routes.py:38-46`.

FetchAllPullRequestsTask (run by `/internal/init` and by the installation events `unsuspend` and `created`) passes
`apply_status=COMPLETED` for every merged pull request of the config repository, and
`update_or_create_pull_request` overwrites the stored status. Merged pull requests recorded `partially_applied`
(secrets, web UI settings, a failed patch) or `not_applied` (invalid) become `completed`; `/otterdog done` and
`/otterdog apply` then skip them as already applied.

### KB-075 — the updated_at of a blueprint status is never refreshed

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/webapp/db/models.py:280-285`, `otterdog/webapp/db/service.py:1021-1040`,
`otterdog/webapp/tasks/blueprints/update_blueprint_status.py:44-65`, `otterdog/webapp/db/service.py:1046-1052`.

`BlueprintStatusModel.updated_at` has a `default_factory` and is never assigned afterwards
(`update_or_create_blueprint_status` and UpdateBlueprintStatusTask save the model without touching it). The dashboard's
"Updated At" column and the default sort (`updated_at desc`) of `/api/blueprints/remediations` and
`/api/blueprints/dismissed` show the creation time of the row.

### KB-076 — global blueprints are de-duplicated by type

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/webapp/utils.py:303-308`, `docs/reference/blueprints/index.md:6-8`.

The docs define blueprints as additive: several blueprints of one type, told apart by their `id`. The loader of the
global blueprints keys them by TYPE and skips the next one of a type ("duplicate global blueprint with type ...,
skipping"), so a second global blueprint of a type is silently ignored (org blueprints are keyed by id). A live test
needs a BlueprintHelper option that writes two global definitions of one type.

### KB-077 — local-plan and local-apply ignore -r for repositories only in the other configuration

Status: **confirmed** · Upstream: none · Scenarios: none (step `removal-outside-the-filter` of `O-LPLAN-FILTER`
declares it)

Evidence: `otterdog/models/__init__.py:669-675`, `otterdog/models/__init__.py:827-839`,
`otterdog/models/github_organization.py:905-916`, `otterdog/operations/local_plan.py:68-80`,
`otterdog/models/repository.py:793-796`.

`-r/--repo-filter` restricts the repositories that are planned. The live `plan` reads only the matching repositories
from GitHub (`load_from_provider` filters the repository names), and the configured side is filtered by
`Repository.include_for_live_patch`. local-plan and local-apply load the other side from a file, entirely, and a
repository that exists only there goes through `include_existing_object_for_live_patch`, which ignores the filter: its
removal is planned whatever the filter, and `local-apply -r <pattern> -d` deletes it. The webapp always uses `*`.

#### Reproduction

BASE declares repositories `a` and `old`, HEAD only `a` (both with the same description):

```console
$ otterdog local-plan -c otterdog.json --local -s -BASE -r a e2e-test-org
  - remove repository[name="old"] {
  Plan: 0 to add, 0 to change, 1 to delete.
$ echo n | otterdog local-apply -c otterdog.json --local -n -s -BASE -r a -d e2e-test-org
  - remove repository[name="old"] {
  Do you want to perform these actions? (Only 'yes' or 'y' will be accepted to approve)
```

Same on v1.6.1 and main 9bdeb75.
