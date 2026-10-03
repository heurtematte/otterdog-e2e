# Scenario catalog

Status values:

- **verified**: implemented, and passed in a real run of this build. That covers the offline tiers against real
  otterdog SUTs: `release:latest` (v1.6.1), `sha:9bdeb75`, `sha:b5f7bb1`, the untrusted `sha:d0d3b08` (docker
  runtime) and a `dirty:` local checkout;
- **implemented**: the scenario or test exists, loads, is collected and skips cleanly without a target. It needs a
  live test organization (target, App, docker) and has not run against one yet;
- **harness**: covered by a harness feature rather than by a scenario (the code exists in `src/otterdog_e2e`);
- **planned**: backlog, not written yet;
- **future**: needs infrastructure that is out of scope for v1 (ghproxy, Dependency-Track mock, tunnels,
  Helm/Kubernetes, MongoDB inspection, GHES/EMU).

Priorities: P0 must run in the `pr-fast` lane, P1 in `nightly-full`, P2 when time allows. The "Sources" column lists
the research scenario ids the entry was derived from (deduplicated); several research items often became one entry.

This catalog lists scenarios. The feature view is the [coverage matrix](coverage-matrix.md), generated from
`scenarios/coverage.yaml`: every otterdog feature with its status (covered, partial, gap), the scenarios and tests
covering it, and for each gap the outline of the missing test (suggested id, file, steps, assertions, what the harness
needs). After a change to the YAML, regenerate it with `.venv/bin/python tests/unit/test_coverage_matrix.py --write`.
When a new scenario closes a gap, update the feature's `status` and `covered_by` too.

## v1 scenarios

"Implemented by" names the YAML scenario id (file under `scenarios/<tier>/`) or the Python test. Scenario ids select
items with `--scenario` / `--e2e-scenario`.

### Offline (`scenarios/offline`, `tests/offline`)

| Id | Scenario | Priority | Status | Implemented by | Sources |
|---|---|---|---|---|---|
| O-VERSION | `otterdog --version` prints the SUT's version | P0 | verified | `tests/offline/test_cli_basics.py` (`O-VERSION`) | CLI-00, DEP-BUILD-02 |
| O-LIST-PROJECTS | `list-projects` lists the offline organization | P1 | verified | `tests/offline/test_cli_basics.py` (`O-LIST-PROJECTS`) | CLI-18 |
| O-VAL-OK | `validate --local` of the baseline succeeds | P0 | verified | `O-VAL-OK` (`val-ok.yaml`) | CLI-02 |
| O-VAL-SYNTAX | a jsonnet syntax error is a load error (`failed to load configuration`) | P0 | verified | `O-VAL-SYNTAX` (`val-syntax.yaml`) | CLI-01, CLI-02 |
| O-VAL-PLAN-GATE | an organization ruleset with plan `free` is rejected (requires enterprise) | P0 | verified | `O-VAL-PLAN-GATE` (`val-plan-gate.yaml`) | PLAN-GATE-FREE-001, MOD-GATE-FREE-01, CFG-10 |
| O-VAL-ORGSECRET-PRIVATE-FREE | an org secret with `visibility: private` is rejected on free | P0 | verified | `O-VAL-ORGSECRET-PRIVATE-FREE` | PLAN-GATE-FREE-001, MOD-GATE-FREE-01 |
| O-VAL-790 | ruleset status checks without `strict` (#790); differential proof of concept | P0 | verified | `O-VAL-790` (`val-790.yaml`; SUT-dependent expectation by git ancestry) | CS790-01, CS790-02, MOD-DIFF-790-01 |
| O-VAL-790-ORG | the organization-ruleset side of #790: SUTs with #790 crash (KB-008, reported as xfail when detected) | P1 | verified | `O-VAL-790-ORG` (`val-790-org.yaml`) | CS790-03 |
| O-LPLAN-ADD | `local-plan` of an added repository | P0 | verified | `O-LPLAN-ADD` | CLI-03, MOD-LOCALPLAN-01 |
| O-LPLAN-CHANGE | `local-plan` of changed attributes | P0 | verified | `O-LPLAN-CHANGE` | CLI-03, MOD-LOCALPLAN-01 |
| O-LPLAN-REMOVE | `local-plan` of a removed repository and nested objects | P0 | verified | `O-LPLAN-REMOVE` | CLI-03, MOD-LOCALPLAN-01 |
| O-SHOW-DEFAULT | `show-default` of the vendored template | P0 | verified | `O-SHOW-DEFAULT` (YAML) and `tests/offline/test_cli_basics.py` | CLI-18 |
| O-CANON | `canonical-diff` of a configuration: diff content, an already canonical file gives an empty diff; steps declare KB-010 (swapped labels) and KB-050 (bracketed words dropped from the canonical form) | P1 | verified | `O-CANON` (`canonical-diff.yaml`) | CLI-18 |
| O-WEB-BOOT | webapp boots with dummy credentials: health, deployed version | P0 | verified | `tests/offline/test_webapp_contract.py` (`O-WEB-BOOT`) | APP-HEALTH-01, DEP-BOOT-01 |
| O-WEB-SIG | receiver contract: missing/invalid/sha256-only signature 400, `application/json; charset=utf-8` 415, valid ping 204, unknown event 204, unknown installation 204 + log line | P0 | verified | `tests/offline/test_webapp_contract.py` (`O-WEB-SIG`) | WH-SIG-01, WH-SIG-001, APP-WH-01, DEP-WH-01, REG-WEBHOOK-ROBUST, WH-NEG-01 |

### CLI (`scenarios/cli`, `scenarios/regressions`, `tests/cli`)

| Id | Scenario | Priority | Status | Implemented by | Sources |
|---|---|---|---|---|---|
| C-SMOKE | `--version`, `check-token-permissions`, `list-projects` | P0 | implemented | `tests/cli/test_smoke.py` (`cli.smoke`) | CLI-00, CLI-06, PRV-AUTH-01 |
| C-BASELINE | `check-status` reports in sync after the baseline reset | P0 | implemented | `tests/cli/test_baseline.py` (`cli.baseline`) | MOD-INFRA-01, CFG-01, REG-CHECK-STATUS-ORACLE |
| C-REPO-LIFECYCLE | create, oracle check, converge, update, delete a repository | P0 | implemented | `cli.repo.lifecycle` | CLI-08, MOD-REPO-PUB-01, PRV-REPO-01, MOD-REPO-DELETE-01 |
| C-TEAM | team with `team_permissions` on a run repository; the creator is not a member | P0 | implemented | `cli.team` | MOD-TEAM-01, MOD-TEAMPERM-01, PRV-TEAM-01, PRV-TPERM-01 |
| C-SECRETS | dummy repository secret and variable, `--update-secrets` | P0 | implemented | `cli.secrets` | MOD-RSV-01, PRV-SECVAR-01, CLI-13 |
| C-REPO-WEBHOOK | managed repository webhook below the e2e hook base, ping, deliveries through the oracle (300 s) | P0 | implemented | `cli.repo.webhook` + the ping probe of `tests/cli/conftest.py` | PRV-HOOK-01, WH-ORGHOOK-001 |
| C-PUSH-FETCH | `push-config` / `fetch-config` round trip on the session config repository | P0 | implemented | `tests/cli/test_config_repo_cli.py` (`cli.push-fetch`) | CLI-10 |
| C-OPEN-PR | `open-pr` creates an `otterdog/e2e-<run>-...` branch and PR | P1 | implemented | `tests/cli/test_config_repo_cli.py` (`cli.open-pr`) | CLI-11, BR-OPENPR-01 |
| C-IMPORT | `import -f -n` round trip (known quirks as known bugs) | P1 | implemented | `tests/cli/test_import.py` (`cli.import`, `cli.import.validate`, `cli.import.plan`) | CLI-07, MOD-IMPORT-01, PRV-FREE-01 |
| C-BPR-PUBLIC | branch protection rule on a public repository | P1 | implemented | `cli.bpr.public` | MOD-BPR-01, PRV-BPR-01 |
| C-RULESET-PUBLIC | repository ruleset on a public repository | P1 | implemented | `cli.ruleset.public` | MOD-RRS-01, PRV-RS-01, RULESET-FREE-PUBLIC-001, CS790-04 |
| C-ENV | environment with a deployment branch policy (`env_branch_policies`) | P1 | implemented | `cli.environment` | MOD-ENV-01, PRV-ENV-01, ENV-PLAN-001 |
| C-ORG-VARIABLE | organization variable with selected repositories (org level) | P1 | implemented | `cli.org.variable` | MOD-OVAR-01, PRV-SECVAR-01 |
| C-CUSTOM-PROPERTY | custom property definition and repository values (requires `custom_properties`) | P1 | implemented | `cli.custom-property` | MOD-CP-01, PRV-CP-01 |
| C-NEG-PRIVATE-BPR | branch protection on a private repository: expected failure without `private_repo_branch_protection` (discovery) | P0 | implemented | `cli.neg.private-bpr` (also observed by D-LIVE-PLAN) | MOD-FREE-PRIV-BPR-01, BPR-FREE-PRIVATE-001, PRV-BPR-02 |
| C-NEG-PRIVATE-RULESET | ruleset on a private repository without `private_repo_rulesets` (discovery) | P2 | implemented | `cli.neg.private-ruleset` (also observed by D-LIVE-PLAN) | MOD-FREE-PRIV-RS-01, RULESET-FREE-PRIVATE-001 |
| C-PLAN-MISMATCH | `variables.plan` differs from the live plan: read-only note only | P1 | implemented | `cli.plan-mismatch` | PLAN-CONFIG-001, MOD-GATE-SPOOF-01 |

Regressions (`scenarios/regressions`) and known-bug scenarios (each runs as a non-strict xfail while its bug is
open, see [known-issues.md](known-issues.md)):

| Id | Scenario | Priority | Status | Gating |
|---|---|---|---|---|
| `regression.472-rename-and-modify` | rename a repository and change it in one apply (#472) | P1 | implemented | |
| `regression.562-ruleset-empty-status-checks` | ruleset with empty status checks (#562) | P1 | implemented | |
| `regression.751-disabled-ruleset` | disabled ruleset whose ref conditions come back null (#751) | P2 | implemented | |
| `regression.767-code-scanning-new-repo` | code scanning languages on a not-yet-existing repository (#767) | P1 | implemented | `fixed_in: 1.7.0.dev2` |
| `regression.790-repo-ruleset-without-strict` | repository ruleset without `strict` is a validation error (#790) | P1 | implemented | `fixed_in: 1.7.0.dev15` |
| `regression.791-731-private-repo` | private repository with the template defaults (#791, #731, #635) | P1 | implemented | `fixed_in: 1.7.0.dev14` |
| `cli.kb.apply-exit-code` | KB-001: apply exits 0 on validation errors (`tests/cli/test_known_bugs.py`) | - | implemented | xfail KB-001 |
| `cli.kb.variables-pagination` | KB-003: more than 10 variables | P2 | implemented | xfail KB-003 |
| `cli.kb.webhook-url-alias` | KB-004: webhook URL change through `aliases` | P2 | implemented | xfail KB-004 |
| `cli.kb.team-permissions-removal` | KB-005: removing a `team_permissions` entry | P2 | implemented | xfail KB-005 |
| `cli.kb.custom-property-underscore` | KB-016: `_` in a custom property name with multi_select values | P2 | implemented | xfail KB-016 |
| `cli.kb.ruleset-any-status-check` | KB-020: `any:<context>` status checks never converge | P2 | implemented | xfail KB-020 |
| `cli.kb.ruleset-default-status-checks` | KB-021: the template's empty `newStatusChecks()` never converges | P2 | implemented | xfail KB-021 |
| `cli.kb.org-variable-same-apply` | KB-022: org variable selecting a repository created by the same apply | P2 | implemented | xfail KB-022 |

### Webhooks (`tests/webhooks`)

| Id | Scenario | Priority | Status | Implemented by | Sources |
|---|---|---|---|---|---|
| H-APP-DELIVERY | a config PR produces a `pull_request` delivery of the installation, relayed with 204 | P0 | implemented | `tests/webhooks/test_app_delivery.py` | DEP-WH-03, WH-RELAY-001, PRV-HOOKAPP-01 |
| H-REPO-HOOK-PING | managed repository webhook ping (covered by C-REPO-WEBHOOK) | P0 | implemented | the probe of `cli.repo.webhook` | PRV-HOOK-01 |
| H-ORG-HOOK | managed organization webhook, ping and deliveries (org level) | P1 | implemented | `tests/webhooks/test_org_hook.py` | MOD-OWH-01, WH-ORGHOOK-001 |

### Webapp (`tests/webapp`)

| Id | Scenario | Priority | Status | Implemented by | Sources |
|---|---|---|---|---|---|
| W-BOOT | stack up, `/internal/init`, the organization and its config are registered | P0 | implemented | `tests/webapp/test_boot.py` | DEP-INIT-01, APP-INIT-01, INFRA-INIT-01 |
| W-PR-VALID | fixture repository description change: validation success, validate comment mentions the repository, help comment for member authors (no merge) | P0 | implemented | `tests/webapp/test_pr_validation.py` | PR-OPEN-01, DEP-PR-01 |
| W-PR-INVALID | syntax error: error status and comment | P0 | implemented | `tests/webapp/test_pr_validation.py` | PR-INVALID-01 |
| W-CMD-HELP | `/otterdog help` | P0 | implemented | `tests/webapp/test_commands.py` | CMD-01 |
| W-CMD-VALIDATE | `/otterdog validate` re-runs the validation | P1 | implemented | `tests/webapp/test_commands.py` | CMD-01 |
| W-MERGE-APPLY | PR adds `e2e-<run>-w-apply`, admin squash merge, apply comment, repository exists, `/api` shows merged and applied | P0 | implemented | `tests/webapp/test_merge_apply.py` | WH-PUSH-APPLY-001, PRV-WAPPLY-01, MOD-PR-APPLY-01 |
| W-AUTOMERGE | auto-merge by author and approver | P0 | implemented | `tests/webapp/test_merge_apply.py` | AM-AUTHOR-01, AM-APPROVAL-01 |
| W-DRIFT-CHECKSYNC | drift on a run repository, `/otterdog check-sync`: check-sync comment and failed sync description or out-of-sync text | P1 | implemented | `tests/webapp/test_commands.py` | PR-DRIFT-01, REG-765 |
| W-REBASE-MULTI | rebase merge of a multi-commit PR applies every commit (#773) | P1 | implemented | `tests/webapp/test_merge_apply.py` | AP-REBASE-01, REG-773 |
| W-STALE-STATUS-792 | a stale `converted_to_draft` snapshot after the merge must not reopen the PR (#792; expected delta of manifest 792) | P1 | implemented | `tests/webapp/test_stale_status.py` (non-strict xfail unless the image contains the fix) | CS792-01, CS792-02, CS792-03, OPR-STALE-01, WH-ORDER-001, APP-PR-03 |
| W-CMD-CHECK-MERGE | `/otterdog check-merge` posts an eligibility comment (previous one minimized) and never merges; skipped unless the webapp's source has the feature (local branch feat/check-merge-command, manifest local-check-merge) | P2 | implemented | `tests/webapp/test_check_merge.py` | CM-01, CM-02, OPR-CHECKMERGE-01 |
| W-PR-WEBUI | a config PR changing a web-only setting (`members_can_delete_issues`) is flagged ("require accessing the Web UI"), not auto-mergeable, applied partially once merged; the live setting stays unchanged (REST) and `/otterdog done` completes the PR (no web credentials) | P1 | implemented | `tests/webapp/test_web_ui_flags.py` | PR-WEBUI-01 |
| W-LIFECYCLE-792 | regression check of #792: a full PR lifecycle still records every task result | P0 | planned | | CS792-05 |

### Web UI (`tests/web_ui`)

otterdog itself drives github.com (Playwright Firefox, the admin bot's password and TOTP), independent oracles check
the result; the tier needs `--allow-web-ui`, the bot's web credentials and a trusted SUT
([web-ui-testing.md](web-ui-testing.md)). Each scenario id selects its item with `--scenario`.

| Id | Scenario | Priority | Status | Implemented by | Sources |
|---|---|---|---|---|---|
| `webui.settings.table` | the harness table of the 12 web-only settings still matches the SUT's schema and web definitions (no login) | P1 | implemented | `tests/web_ui/test_web_settings.py` | MOD-ORGSET-WEB-01 |
| `webui.settings.round-trip` | snapshot (REST + trusted reader), the SUT applies toggled values without `-n`, both oracles verify, the SUT's plan converges, the SUT restores (trusted fallback) and both oracles verify again (8 logins) | P1 | implemented | `tests/web_ui/test_web_settings.py` | PRV-WEB-01, CLI-09, MOD-ORGSET-WEB-01 |
| `webui.import.web-settings` | `import` without `-n` writes the web settings GitHub reports (REST-readable ones) | P2 | implemented | `tests/web_ui/test_web_settings.py` | CLI-09, MOD-FREE-WEB-01 |
| `webui.cmd.review-permissions` | `review-permissions` reads the installations page and approves nothing (never `-g`) | P2 | implemented | `tests/web_ui/test_web_commands.py` | CLI-19, PRV-PERM-01 |
| `webui.cmd.list-advisories` | `list-advisories -w -s all` prints a complete CSV | P2 | implemented | `tests/web_ui/test_web_commands.py` | CLI-19 |
| `webui.cmd.install-app` | `install-app` then `uninstall-app` of a harmless probe App, verified through REST; non-strict xfail of KB-002 | P2 | implemented | `tests/web_ui/test_web_commands.py` | CLI-20, PRV-INSTALL-01 |
| `webui.cmd.web-login` | `web-login` opens the bot's browser session (local runs with a display only) | P2 | implemented | `tests/web_ui/test_web_commands.py` | CLI-19 |

The web side of the webapp is `W-PR-WEBUI` above (it runs in the webapp tier, without web credentials). The research
item PRV-WEB-03 (the read-only `two_factor_requirement` is never retrieved) became known bug KB-041; PRV-WEB-02 (web
credential failure modes) is covered by the login gate's classification and its unit tests, never by real failed
logins (they could lock the bot out).

### Enterprise (`scenarios/enterprise`, `tests/enterprise`)

| Id | Scenario | Priority | Status | Implemented by | Sources |
|---|---|---|---|---|---|
| E-ORG-ROLE | custom organization role (oracle check kind `org_role`) | P0 | implemented | `enterprise.org-role` | MOD-ENT-ROLES-01, PRV-ENT-ROLE-01 |
| E-ORG-RULESET | organization ruleset; known bug #790 (`AttributeError` for status checks without `strict`) | P0 | implemented | `enterprise.org-ruleset`, `enterprise.org-ruleset.790-missing-strict` (xfail KB-008), `enterprise.kb.org-ruleset-repo-patterns` (xfail KB-023) | MOD-ENT-ORS-01, PRV-ENT-ORS-01, CS790-03 |
| E-PRIVATE-BPR | branch protection on a private repository | P0 | implemented | `enterprise.private-bpr` | MOD-ENT-PRIV-01, CLI-16 |
| E-ENV-REVIEWERS-PRIVATE | environment reviewers on a private repository | P0 | implemented | `enterprise.env-reviewers-private` | MOD-ENT-PRIV-01, ENV-PLAN-001 |

### Differential (`tests/differential`) and PR manifests (`scenarios/otterdog-prs`)

| Id | Scenario | Priority | Status | Implemented by | Sources |
|---|---|---|---|---|---|
| D-OFFLINE | every offline scenario with `observe: true`, on both sides | P0 | verified | `tests/differential/test_offline_diff.py` | CLI-03, CFG-19 |
| D-LIVE-PLAN | `observe_live` (validate + plan, never apply) of the live scenarios with `observe: true` | P1 | implemented | `tests/differential/test_live_diff.py` (needs a target and a base SUT) | CLI-23, MOD-DIFF-GENERIC-01, DEP-DIFF-01 |
| PR-790 | `790.yaml`: expected delta on O-VAL-790 | P0 | verified | 2 expected deltas observed; the O-VAL-790-ORG crash stays unexpected (KB-008) | CS790-01, MOD-DIFF-790-01 |
| PR-792 | `792.yaml`: webapp tag, expected delta on W-STALE-STATUS-792 | P1 | verified (offline part), implemented (webapp part) | untrusted head `sha:d0d3b08` in docker vs `sha:9bdeb75`: 0 offline deltas, as the manifest states; W-STALE-STATUS-792 needs a target | CS792-01, APP-PR-03 |
| PR-CHECK-MERGE | `local-check-merge.yaml`: `dirty:../otterdog` feat/check-merge-command, base v1.6.0, marker check-merge, scenario W-CMD-CHECK-MERGE | P2 | verified (offline part), implemented (webapp part) | `dirty:` checkout vs `tag:v1.6.0`: 0 offline deltas (wave-2 run); W-CMD-CHECK-MERGE needs a target | CM-01, CM-02, OPR-CHECKMERGE-01 |

### Harness features

| Feature | Covers | Status | Where |
|---|---|---|---|
| SUT resolution, mirror, version, host install, image build | CLI-00, DEP-BUILD-01, DEP-BUILD-02 | harness | `sut/` |
| version guard (shallow, tagless, placeholder versions refused) | DEP-BUILD-03 | harness | `sut/version.py` |
| capability probe and gating | CAP-PROBE-001, PRV-CAP-01 | harness | `capabilities.py`, plugin gating |
| bootstrap of configs/defaults repositories, baseline, App checks | CFG-01, MOD-INFRA-01 | harness | `otterdog-e2e bootstrap` |
| base template resolution and publishing (pinned to a commit) | CFG-02 (template part) | harness | `sut/template.py` |
| pull relay of App deliveries | DEP-WH-03, WH-RELAY-001 | harness | `webhooks/relay.py` |
| rate budget gating | PRV-RL-01 | harness | `E2E_MIN_RATE_REMAINING` |
| SUTs installed and images built before the first item (no cold install inside an item timeout) | DEP-BUILD-01 | harness (verified) | `pytest_plugin.pytest_runtestloop` |
| `fixed_in` gating of regressions of unreleased fixes; fixed known bugs xfail only on older SUTs | REG-* | harness | `scenarios/engine.py`, `known_bugs.py`, plugin |
| untrusted SUT CLI in its own image (`--network none`, read-only, no capabilities) | DEP-BUILD-01, SEC-03 | harness (verified offline with `sha:d0d3b08`) | `otterdog/runtime.py` |
| read-only `dirty:`/`path:` checkouts (`GIT_OPTIONAL_LOCKS=0`, export only) | CM-01 | harness (verified: checkout unchanged) | `sut/source.py` |
| editor schema of the scenario format | - | harness | `.vscode/scenario.schema.json` (`scenarios.model.json_schema`) |
| web-UI gating and login gate (credentials, `--allow-web-ui`, trusted SUTs, one login per TOTP window, block after a blocking failure) | PRV-WEB-02 | harness | `webui/gate.py`, `pytest_plugin` (`web_ui` marker) |
| coverage matrix: inventory of otterdog's features, gap outlines, the summary section of each run | - | harness | `scenarios/coverage.yaml`, [coverage-matrix.md](coverage-matrix.md), `report.section_coverage` |

## Test battery

The battery written against the [coverage matrix](coverage-matrix.md): 226 scenario ids beyond the v1
scenarios above (generated from the scenario files, the test markers and `scenarios/coverage.yaml`; the last column
lists the features whose `covered_by` names the item). Offline items are **verified**: they ran green, or as
expected failures of a registered known bug, on `release:latest` (v1.6.1) and `sha:9bdeb75`. Live items are
**implemented**: they load, are collected and skip cleanly without a target, and the steps of the live YAML
scenarios pass the offline scenario lint where they can run offline; they have not run against a test organization
yet. Known-bug items assert the correct behaviour and run as non-strict expected failures while the bug is open
([known-issues.md](known-issues.md)); `xfail KB-nnn` marks them (step-level known bugs are not listed).

### Offline scenarios (`scenarios/offline`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `O-LPLAN-ERRORS` | local-plan error paths exit 1 with the reason and no Plan line | P1 | verified | `offline/cli/local-plan/lplan-errors.yaml` | `cli.plan.errors` |
| `O-LPLAN-ONLY-SECRETS` | --only-secrets plans secret patches only, organization, repository and environment ones | P2 | verified | `offline/cli/local-plan/lplan-only-secrets.yaml` | `cli.plan.only-secrets` |
| `O-LPLAN-SECRET-REFS` | local-plan shows dummy secrets as &lt;DUMMY&gt; and diffs secret references | P1 | verified | `offline/cli/local-plan/lplan-secrets.yaml` | `cli.local-plan.dummy-secrets` |
| `O-LPLAN-WEBHOOK-SECRET-REMOVED` | Removing a webhook secret is planned as a change with a warning | P2 | verified | `offline/cli/local-plan/lplan-webhook-secret.yaml` | `cli.plan.webhook-secret-removal` |
| `O-SHOW` | show prints the organization settings and every model object as key = value blocks | P2 | verified | `offline/cli/output/show.yaml` | `cli.show` |
| `O-EXTEND-REPO` | extendRepo merges into the repository of the same name (later entries win) | P2 | verified | `offline/models/extend-repo.yaml` | `repositories.extend` |
| `O-SHOW-ROLE-FIELDS` | Organization role visibility and selected_repositories cannot be configured | P2 | verified | `offline/models/show-role-fields.yaml` | `org-roles.unused-model-fields` |
| `O-LPLAN-ARCHIVED` | Archived repositories ignore read-only fields and their rules; archiving plans the other changes too | P0 | verified | `offline/plan/lplan-archived.yaml` | `plan-semantics.ignored-archived` |
| `O-LPLAN-BPR-DEPENDENTS` | Branch protection settings behind a disabled toggle are not diffed | P1 | verified | `offline/plan/lplan-bpr-dependents.yaml` | `plan-semantics.bpr-dependents-ignored` |
| `O-LPLAN-COERCE-SIGNOFF` | Organization settings make repository fields unmanaged or forced (signoff, projects, Pages, discussions) | P0 | verified | `offline/plan/lplan-coerce.yaml` | `plan-semantics.coerce.org-signoff`, `plan-semantics.coerce.org-projects-pages`, `plan-semantics.coerce.discussion-source`, `plan-semantics.code-security-disable-only`, `repositories.features` |
| `O-LPLAN-CUSTOM-PROPERTY-DEFAULTS` | Required custom property defaults fill repositories; a value_type change aborts planning | P2 | verified | `offline/plan/lplan-custom-property-defaults.yaml` | `plan-semantics.coerce.required-custom-properties`, `custom-properties.value-type-immutable` |
| `O-LPLAN-DICT-ONE-WAY` | Removing a team_permissions or custom_properties entry is only planned with another change | P1 | verified | `offline/plan/lplan-dict-one-way.yaml` | `plan-semantics.dict-one-way` |
| `O-LPLAN-ENV-POLICIES` | Environment branch policies are only diffed with the 'selected' deployment branch policy | P1 | verified | `offline/plan/lplan-env-policies.yaml` | `plan-semantics.env-branch-policies-ignored` |
| `O-LPLAN-FORCED-SECRETS` | Secret values, dummy secrets and --update-secrets / --update-filter / --only-secrets in local-plan | P1 | verified | `offline/plan/lplan-forced-secrets.yaml` | `cli.plan.update-secrets`, `cli.plan.only-secrets`, `cli.local-plan.dummy-secrets` |
| `O-LPLAN-FORCED-WEBHOOKS` | Webhook secrets and --update-webhooks / --update-filter in local-plan | P1 | verified | `offline/plan/lplan-forced-webhooks.yaml` | `cli.plan.update-webhooks`, `cli.plan.webhook-secret-removal`, `cli.local-plan.dummy-secrets`, `webhooks.org.secret`, `webhooks.repo.secret` |
| `O-LPLAN-IGNORED-FIELDS` | Fields made irrelevant by other settings are not diffed (security, Pages, code scanning, Actions) | P1 | verified | `offline/plan/lplan-ignored-fields.yaml` | `plan-semantics.ignored-fields`, `plan-semantics.ignored-org-actions` |
| `O-LPLAN-READ-ONLY-KEYS` | Read-only keys are shown with a note and never counted (plan, two_factor_requirement, template_repository) | P1 | verified | `offline/plan/lplan-read-only.yaml` | `cli.plan.read-only-note`, `org-settings.web-ui.two-factor` |
| `O-LPLAN-RENAME` | Aliases turn a renamed repository or webhook into a change instead of remove + add | P1 | verified | `offline/plan/lplan-rename.yaml` | `plan-semantics.rename-aliases` |
| `O-LPLAN-FILTER` | The repository filter keeps other repositories out of the plan, organization objects stay planned | P0 | verified | `offline/plan/lplan-repo-filter.yaml` | `cli.plan.repo-filter` |
| `O-LPLAN-RESOURCE-TYPES` | local-plan adds, changes and removes every resource type (enterprise plan) | P1 | verified | `offline/plan/lplan-resource-types.yaml` | `plan-semantics.add-block`, `plan-semantics.change-block`, `plan-semantics.remove-block` |
| `O-LPLAN-WILDCARD` | A webhook url ending with '*' matches the existing hook whose url starts with the prefix | P1 | verified | `offline/plan/lplan-wildcard.yaml` | `plan-semantics.wildcard-keys` |
| `O-LPLAN-ESCAPING` | Values containing rich markup are printed literally by local-plan and show | P2 | verified | `offline/regressions/changelog/lplan-escaping.yaml` | `regression.440-rich-escaping` |
| `O-LPLAN-NESTED` | Changes inside nested settings and dicts print as nested blocks with old and new values | P2 | verified | `offline/regressions/changelog/lplan-nested.yaml` | `regression.nested-dict-printing` |
| `O-VAL-BPR` | Branch protection rule dependencies are validated (errors, warnings, infos) | P1 | verified | `offline/validation/val-bpr.yaml` | `validation.bpr` |
| `O-VAL-COERCED` | Repository rules that depend on organization settings never fire (coercion at load) | P2 | verified | `offline/validation/val-coerced.yaml` | `validation.repo.pages`, `validation.repo.coerced-rules`, `plan-semantics.coerce.org-projects-pages` |
| `O-VAL-CUSTOM-PROPERTIES` | Custom property definitions are validated rule by rule | P1 | verified | `offline/validation/val-custom-properties.yaml` | `validation.custom-properties` |
| `O-VAL-ENVIRONMENTS` | Environment wait timer, branch policy and reviewer settings are validated | P1 | verified | `offline/validation/val-environments.yaml` | `validation.environments` |
| `O-VAL-INFOS` | Info messages are hidden without -v and printed with -v (archived repositories, ignored review count) | P2 | verified | `offline/validation/val-infos.yaml` | `cli.global.verbosity`, `validation.repo.archived-bpr` |
| `O-VAL-MERGE-SETTINGS` | Squash and merge commit titles and messages are validated as values and as pairs | P1 | verified | `offline/validation/val-merge-settings.yaml` | `validation.repo.merge-commit-settings` |
| `O-VAL-ORG-ROLES` | Organization role base roles and permissions are validated | P2 | verified | `offline/validation/val-org-roles.yaml` | `validation.org-roles` |
| `O-VAL-ORG-RULESETS` | Organization ruleset repository patterns and nested rules are validated | P2 | verified | `offline/validation/val-org-rulesets.yaml` | `validation.org-rulesets` |
| `O-VAL-ORG-SECRETS` | Organization secret visibility and selected repositories are validated | P2 | verified | `offline/validation/val-org-secrets.yaml` | `validation.org-secrets` |
| `O-VAL-ORG-SETTINGS` | Organization settings rules (description, discussions source, default permission) | P1 | verified | `offline/validation/val-org-settings.yaml` | `validation.org-settings` |
| `O-VAL-ORGVAR` | Organization variables should be validated like secrets and repository variables | P1 | verified | `offline/validation/val-org-variables.yaml` | `validation.plan-gate.org-variable-private` |
| `O-VAL-ORG-WORKFLOWS` | Organization Actions settings are validated (enums and ignored settings) | P1 | verified | `offline/validation/val-org-workflows.yaml` | `validation.org-workflows` |
| `O-VAL-PAGES-ENTERPRISE` | GitHub Pages visibility is validated on the enterprise plan | P1 | verified | `offline/validation/val-pages-enterprise.yaml` | `validation.repo.pages`, `plan-semantics.coerce.org-projects-pages` |
| `O-VAL-PAGES` | GitHub Pages build type, legacy source path and the organization site are validated | P1 | verified | `offline/validation/val-pages.yaml` | `validation.repo.pages` |
| `O-VAL-PLAN-GATES-ENTERPRISE` | The enterprise plan accepts every plan-gated feature | P1 | verified | `offline/validation/val-plan-gates-enterprise.yaml` | `validation.plan-gate.org-rulesets`, `validation.plan-gate.org-secret-private`, `validation.plan-gate.org-roles`, `validation.plan-gate.ruleset-evaluate`, `validation.plan-gate.private-pages`, `validation.plan-gate.private-repo-wiki` |
| `O-VAL-PLAN-GATES-TEAM` | The team plan lifts the team gates and keeps the enterprise gates | P1 | verified | `offline/validation/val-plan-gates-team.yaml` | `validation.plan-gate.org-rulesets`, `validation.plan-gate.org-secret-private`, `validation.plan-gate.org-roles`, `validation.plan-gate.ruleset-evaluate`, `validation.plan-gate.private-pages`, `validation.plan-gate.private-repo-wiki` |
| `O-VAL-PLAN-GATES` | Plan-gated features are refused or flagged on the free plan | P0 | verified | `offline/validation/val-plan-gates.yaml` | `validation.plan-gate.org-rulesets`, `validation.plan-gate.org-secret-private`, `validation.plan-gate.org-roles`, `validation.plan-gate.ruleset-evaluate`, `validation.plan-gate.private-pages`, `validation.plan-gate.private-repo-wiki` |
| `O-VAL-REPO-WORKFLOWS` | Repository Actions settings are validated against the organization Actions settings | P2 | verified | `offline/validation/val-repo-workflows.yaml` | `validation.repo-workflows` |
| `O-VAL-REPO` | Repository rules (description, topics, forking, secret scanning, template, fork, properties, code scanning) | P1 | verified | `offline/validation/val-repository.yaml` | `validation.repo.description-topics`, `validation.repo.forking`, `validation.repo.secret-scanning`, `validation.repo.template-fork`, `validation.repo.custom-properties`, `validation.repo.code-scanning` |
| `O-VAL-RULESET-NESTED` | Ruleset pull request and merge queue settings are validated | P1 | verified | `offline/validation/val-ruleset-nested.yaml` | `validation.ruleset-nested` |
| `O-VAL-RULESETS` | Repository ruleset target, enforcement, ref patterns and deployment rules are validated | P1 | verified | `offline/validation/val-rulesets.yaml` | `validation.rulesets` |
| `O-VAL-SCHEMA` | Unknown properties and schema violations of the configuration | P1 | verified | `offline/validation/val-schema.yaml` | `validation.repo.team-permissions`, `validation.schema.unknown-properties`, `validation.schema.type-errors`, `regression.718-unknown-properties` |
| `O-VAL-SECRETS` | Secret names and values are validated at every level | P1 | verified | `offline/validation/val-secrets.yaml` | `config.secret-references`, `validation.secrets` |
| `O-VAL-VARIABLES` | Repository and environment variable names are validated | P1 | verified | `offline/validation/val-variables.yaml` | `validation.variables` |
| `O-VAL-WEBHOOKS` | Webhook content type, SSL flag and secret notices are validated | P1 | verified | `offline/validation/val-webhooks.yaml` | `validation.webhooks` |

### Live CLI scenarios (`scenarios/cli`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `cli.org.actions-allowed` | Organization allowed actions and fork pull request approval policy | P1 | implemented | `cli/org/actions-allowed.yaml` | `org-workflows.allowed-actions`, `org-workflows.fork-pr-approval`, `repo-workflows.allowed-actions` |
| `cli.org.actions-enabled-repositories` | Organization Actions availability for all or selected repositories | P1 | implemented | `cli/org/actions-enabled.yaml` | `org-workflows.enabled-repositories`, `repo-workflows.enabled` |
| `cli.org.cache-size` | Organization Actions cache storage limit | P2 | implemented | `cli/org/cache-size.yaml` | `org-workflows.cache-size` |
| `cli.custom-property.flag` | true_false custom property and removing a property definition | P2 | implemented | `cli/org/custom-property-flag.yaml` | `custom-properties.true-false`, `custom-properties.remove`, `regression.653-string-property` |
| `cli.custom-property.required` | Required custom property with a default value | P2 | implemented | `cli/org/custom-property-required.yaml` | `plan-semantics.coerce.required-custom-properties`, `custom-properties.required-default` |
| `cli.environment.secrets` | Environment and repository secrets and variables (add, change, forced update, remove) | P1 | implemented | `cli/org/environment-secrets.yaml` | `cli.plan.update-secrets`, `secrets-variables.env-secret.lifecycle`, `secrets-variables.env-variable.lifecycle`, `secrets-variables.remove` |
| `cli.kb.org-secret-same-apply` | Org secret selecting a repository created in the same apply (known bug KB-022, secret variant) | P2 | implemented | `cli/org/kb-org-secret-same-apply.yaml` | `plan-semantics.patch-order`, `secrets-variables.org-secret.selected-repositories` |
| `cli.kb.team-privacy-message` | Team privacy validation message names the accepted values (known bug KB-037) | P2 | implemented | `cli/org/kb-team-privacy-message.yaml` | `validation.teams` |
| `cli.org.member-privileges` | Organization member privileges, repository creation, forking and Pages creation | P1 | implemented | `cli/org/member-privileges.yaml` | `org-settings.member-privileges`, `org-settings.pages-creation` |
| `cli.org.profile` | Organization profile (name, blog, location, company, email, twitter_username) | P0 | implemented | `cli/org/profile.yaml` | `org-settings.profile` |
| `cli.org.secret-private` | Organization secret visible to private repositories (Team and Enterprise plans) | P2 | implemented | `cli/org/secret-private.yaml` | `secrets-variables.org-secret.lifecycle` |
| `cli.org.secret` | Organization secrets (values, visibility, selected repositories, forced update, removal) | P0 | implemented | `cli/org/secret.yaml` | `cli.plan.update-secrets`, `config.secret-references`, `secrets-variables.org-secret.lifecycle`, `secrets-variables.org-secret.selected-repositories`, `secrets-variables.remove` |
| `cli.org.security-managers` | Security manager teams (assigned and removed to match) | P2 | implemented | `cli/org/security-managers.yaml` | `plan-semantics.patch-order`, `org-settings.security-managers` |
| `cli.org.signoff` | Organization web commit signoff and the repositories that inherit it | P0 | implemented | `cli/org/signoff.yaml` | `plan-semantics.coerce.org-signoff`, `org-settings.web-commit-signoff`, `repositories.signoff` |
| `cli.team.members` | Team members (added, removed, then unmanaged with skip_members) | P1 | implemented | `cli/org/team-members.yaml` | `teams.members` |
| `cli.team.settings` | Team privacy (visible, secret) and notifications | P1 | implemented | `cli/org/team-settings.yaml` | `teams.privacy`, `teams.notifications` |
| `cli.validate.team-non-member` | Team validation with skip_non_organization_members and a user outside the organization | P1 | implemented | `cli/org/validate-team-non-member.yaml` | `validation.teams`, `teams.members` |
| `cli.validate.teams` | Team validation rules (privacy values, skip_members with members) | P1 | implemented | `cli/org/validate-teams.yaml` | `validation.teams` |
| `cli.org.workflow-permissions` | Organization default workflow permissions and pull request approvals by GitHub Actions | P0 | implemented | `cli/org/workflow-permissions.yaml` | `org-workflows.default-permissions`, `repo-workflows.default-permissions` |
| `cli.protection.app-checks` | Status checks, allowances and a bypass actor bound to an installed GitHub App | P1 | implemented | `cli/protection/app-checks.yaml` | `branch-protection.review-dismissal`, `branch-protection.bypass-allowances`, `branch-protection.status-checks`, `branch-protection.push-restrictions`, `rulesets.bypass-actors`, `rulesets.status-checks`, `regression.695-700-491-status-check-mapping` |
| `cli.bpr.allowances` | Branch protection allowances for users and teams | P1 | implemented | `cli/protection/bpr-allowances.yaml` | `branch-protection.review-dismissal`, `branch-protection.bypass-allowances`, `branch-protection.push-restrictions` |
| `cli.bpr.deployments` | Branch protection rule requiring successful deployments | P2 | implemented | `cli/protection/bpr-deployments.yaml` | `branch-protection.deployments` |
| `cli.bpr.lock` | Lock branches matching a branch protection rule | P2 | implemented | `cli/protection/bpr-lock.yaml` | `branch-protection.lock-branch` |
| `cli.bpr.settings` | Branch protection review, history, force push and status check settings | P0 | implemented | `cli/protection/bpr-settings.yaml` | `branch-protection.pull-request-reviews`, `branch-protection.status-checks`, `branch-protection.history-and-signatures`, `branch-protection.force-push-deletion-admin` |
| `cli.environment.policies` | Environment branch and tag policies, protected branches, environment removal | P0 | implemented | `cli/protection/environment-policies.yaml` | `environments.lifecycle`, `environments.branch-policies` |
| `cli.environment.private` | Environment with branch and tag policies on a private repository (Team and Enterprise) | P2 | implemented | `cli/protection/environment-private.yaml` | `environments.lifecycle`, `environments.branch-policies` |
| `cli.environment.reviewers` | Environment required reviewers (team and user) on a public repository | P1 | implemented | `cli/protection/environment-reviewers.yaml` | `environments.reviewers` |
| `cli.ruleset.bypass` | Ruleset bypass actors (roles and teams) and their bypass modes | P1 | implemented | `cli/protection/ruleset-bypass.yaml` | `rulesets.bypass-actors` |
| `cli.ruleset.deployments` | Ruleset requiring successful deployments | P2 | implemented | `cli/protection/ruleset-deployments.yaml` | `rulesets.deployments` |
| `cli.ruleset.merge-queue` | Ruleset requiring a merge queue | P2 | implemented | `cli/protection/ruleset-merge-queue.yaml` | `rulesets.merge-queue` |
| `cli.ruleset.pull-request` | Ruleset pull request parameters and removal of the rule | P1 | implemented | `cli/protection/ruleset-pull-request.yaml` | `rulesets.pull-request` |
| `cli.ruleset.rules` | Ruleset simple rules on a branch ruleset and a tag ruleset | P1 | implemented | `cli/protection/ruleset-rules.yaml` | `rulesets.targets`, `rulesets.rules` |
| `cli.ruleset.status-checks` | Ruleset status checks with do_not_enforce_on_create and an integration id | P1 | implemented | `cli/protection/ruleset-status-checks.yaml` | `rulesets.status-checks`, `regression.695-700-491-status-check-mapping` |
| `cli.repo.actions` | Repository Actions enablement, allowed actions and fork pull request approval | P1 | implemented | `cli/repo/repo-actions.yaml` | `repo-workflows.enabled`, `repo-workflows.allowed-actions`, `repo-workflows.default-permissions`, `repo-workflows.fork-pr-approval` |
| `cli.repo.archive` | Archive a repository, ignore changes while archived, unarchive it | P0 | implemented | `cli/repo/repo-archive.yaml` | `repositories.archive` |
| `cli.repo.cache-limit` | Repository Actions cache storage limit | P2 | implemented | `cli/repo/repo-cache-limit.yaml` | `repo-workflows.cache-size` |
| `cli.repo.features` | Repository features and merge settings round trip | P0 | implemented | `cli/repo/repo-features.yaml` | `repositories.features`, `repositories.merge-methods` |
| `cli.repo.fork` | Create a repository as a fork of a public repository | P2 | implemented | `cli/repo/repo-fork.yaml` | `repositories.fork` |
| `cli.repo.merge-messages` | Squash and merge commit title and message defaults | P1 | implemented | `cli/repo/repo-merge-messages.yaml` | `repositories.merge-commit-messages` |
| `cli.repo.org-coerced` | Repository signoff and default workflow permissions under a permissive organization | P0 | implemented | `cli/repo/repo-org-coerced.yaml` | `repositories.signoff`, `repo-workflows.default-permissions` |
| `cli.repo.pages` | GitHub Pages from a branch, from a workflow, then disabled | P1 | implemented | `cli/repo/repo-pages.yaml` | `repositories.pages`, `regression.450-pages-required-fields` |
| `cli.repo.security` | Secret scanning, push protection, Dependabot and private vulnerability reporting | P1 | implemented | `cli/repo/repo-security.yaml` | `repositories.security` |
| `cli.repo.visibility` | Switch an existing repository between public and private | P1 | implemented | `cli/repo/repo-visibility.yaml` | `repositories.visibility-forking` |
| `cli.repo.webhook-secret` | Repository webhook secrets (plain value, dummy, --update-webhooks, removal) | P1 | implemented | `cli/webhooks/repo-webhook-secret.yaml` | `cli.plan.update-webhooks`, `webhooks.repo.secret` |
| `cli.repo.webhook-settings` | Repository webhook settings (events, content_type, active, insecure_ssl) | P1 | implemented | `cli/webhooks/repo-webhook-settings.yaml` | `webhooks.repo.settings` |

### Regressions (`scenarios/regressions`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `regression.779-user-bypass-actors` | #779: an individual user ('@login') as a ruleset bypass actor | P2 | implemented | `regressions/779-user-bypass-actors.yaml` (fixed_in 1.7.0.dev7) | `rulesets.bypass-actors`, `regression.779-user-bypass-actors` |

### Enterprise scenarios (`scenarios/enterprise`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `enterprise.ruleset-merge-queue-private` | Ruleset requiring a merge queue on a private repository (Enterprise) | P2 | implemented | `enterprise/ruleset-merge-queue-private.yaml` | `rulesets.merge-queue` |

### Offline Python tests (`tests/offline`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `O-CONFIG-ARCHIVED-ORG` | Organizations with archived: true are never listed, never processed and unknown when named (exit 2); an archived entry is not even checked (one without... | - | verified | `tests/offline/test_config_loading.py` (1 test) | `config.archived-organizations` |
| `O-CONFIG-DEFAULTS-OVERRIDE` | .otterdog-defaults.json {"jsonnet": {"config_dir": "orgs-override"}} next to otterdog.json (whose config_dir is "orgs") moves the organization directory to... | - | verified | `tests/offline/test_config_loading.py` (1 test) | `config.local-defaults-override` |
| `O-CONFIG-DISCOVERY` | Without -c and with OTTERDOG_CONFIG_ROOT set to the workspace, otterdog uses its otterdog.json; once an otterdog.jsonnet naming another project (same... | - | verified | `tests/offline/test_config_loading.py` (2 tests) | `config.discovery` |
| `O-CONFIG-JSONNET` | otterdog.jsonnet (the document behind a jsonnet ``local``, which no JSON parser accepts) works like otterdog.json for validate and list-projects | - | verified | `tests/offline/test_config_loading.py` (2 tests) | `config.jsonnet-config-file` |
| `O-CONFIG-NO-BASE-TEMPLATE` | Without defaults.jsonnet.base_template, an organization with its own base_template still fails to load: every command exits 2 with 'need to define a base... | - | verified | `tests/offline/test_config_loading.py` (1 test) | `config.base-template-required` |
| `O-CONFIG-ORG-ENTRIES` | One invalid entry among the organizations stops the loading of the whole configuration (exit 2, the valid organization is not listed either) | - | verified | `tests/offline/test_config_loading.py` (2 tests) | `config.organization-entries`, `config.template-url` |
| `O-CREDENTIALS-ENV` | Without organization credentials, defaults.credentials.provider env and defaults.env templates resolve {github_id} and {org_name} (upper case, ' ' and '-'... | - | verified | `tests/offline/test_config_credentials.py` (3 tests) | `config.credentials.env` |
| `O-CREDENTIALS-PROVIDERS` | plain uses the configured values; defaults.credentials.provider applies to organizations that name none; unexpected keys of defaults.&lt;provider&gt; only warn... | - | verified | `tests/offline/test_config_credentials.py` (4 tests) | `config.credentials.other-providers`, `config.local-defaults-override` |
| `O-EXIT-CODES` | A valid configuration exits 0 ('Validation succeeded'); one validation error exits 1 with the error and the 'Validation failed: 0 info(s), 0 warning(s), 1... | - | verified | `tests/offline/test_cli_exit_codes.py` (4 tests) | `cli.global.exit-codes`, `cli.global.verbosity` |
| `O-HELP` | ``otterdog --help`` (and its alias ``-h``) exits 0 with the group usage, the --version option and every subcommand with a one-line help; a command the... | - | verified | `tests/offline/test_cli_basics.py` (3 tests) | `cli.help`, `regression.691-open-pr-author` |
| `O-KB-EXIT-STATUS-ERROR-COUNT` | Validation errors should exit 1 whatever their number, keeping 2 for crashes: today two errors exit 2 and 256 errors exit 0 (validate and local-plan), KB-034 | - | verified | `tests/offline/test_cli_exit_codes.py` (1 test; xfail KB-034) | `cli.global.exit-codes` |
| `O-KB-LPLAN-DUMMY-SECRETS` | local-plan previews local-apply: with --update-secrets it must not plan a forced update of a dummy secret (Plan: 0 to add, 0 to change, 0 to delete), like... | - | verified | `tests/offline/test_cli_local_plan_flags.py` (1 test; xfail KB-056) | `cli.local-plan.dummy-secrets` |
| `O-KB-SECRET-WITH-COLONS` | A secret value 'pass:a:b' (provider pass, path 'a:b') should validate; today the split into exactly two parts crashes the validation ('too many values to... | - | verified | `tests/offline/test_cli_exit_codes.py` (1 test; xfail KB-025) | `cli.global.exit-codes` |
| `O-KB-SHOW-MARKDOWN-LINKS` | The page title of `repo-<name>.md` is the markdown link `# Repo [<name>](https://github.com/<org>/<name>)` and the Repositories row of configuration.md links... | - | verified | `tests/offline/test_cli_basics.py` (1 test; xfail KB-050) | `cli.show.markdown` |
| `O-KB-VALIDATION-MARKUP` | An invalid squash_merge_commit_title holding markup is reported with its literal value in both messages | - | verified | `tests/offline/test_cli_markup.py` (1 test; xfail KB-050) | `regression.440-rich-escaping` |
| `O-KB-WEB-BOOT-EXIT-STATUS` | A webapp that refuses its configuration at boot is a failure for its supervisor: the exited container should report a non-zero status (KB-061: it exits 0... | - | verified | `tests/offline/test_webapp_runtime.py` (1 test; xfail KB-061) | `regression.712-fail-fast-configuration` |
| `O-KB-WEB-FORM-WITHOUT-PAYLOAD` | A correctly signed form body without the 'payload' field is a malformed delivery: 400, never a 500 | - | verified | `tests/offline/test_webapp_contract.py` (1 test; xfail KB-060) | `receiver.content-types` |
| `O-KB-WEB-LOGIN-REQUIRED` | /myprojects needs a GitHub OAuth session: a request without cookies gets the 401 page | - | verified | `tests/offline/test_webapp_contract.py` (1 test; xfail KB-059) | `webapp-runtime.login-required` |
| `O-LOCAL-APPLY-HINTS` | Only a removal planned and no -d: the removal is shown, then 'No changes required.' and the hint that one resource would be deleted with --delete-resources... | - | verified | `tests/offline/test_cli_local_apply.py` (1 test) | `cli.apply.deletion-hints` |
| `O-LOCAL-APPLY-PROMPT` | An addition and a pending removal without -f: the plan, the removal hint and the prompt are printed; any answer other than exactly 'yes' or 'y' cancels... | - | verified | `tests/offline/test_cli_local_apply.py` (2 tests) | `cli.apply.deletion-hints`, `cli.apply.prompt` |
| `O-LOCAL-MISSING-TEMPLATE` | --local never clones the base template: without &lt;org dir&gt;/vendor/&lt;repo&gt;/&lt;file&gt;, validate and show exit 2 with "template file '...' does not exist" (before... | - | verified | `tests/offline/test_config_loading.py` (1 test) | `cli.global.local-mode` |
| `O-LPLAN-ERRORS` | plan reads the live organization: in the network sandbox of the offline tier GitHub is unreachable, the connection error escapes the operation ('Error... | - | verified | `tests/offline/test_cli_exit_codes.py` (1 test) | `cli.plan.errors` |
| `O-LPLAN-SECRET-REFS` | local-apply --update-secrets skips secrets that only have a dummy value: nothing to do ('No changes required.', no prompt, exit 0); the two dummies are... | - | verified | `tests/offline/test_cli_local_plan_flags.py` (1 test) | `cli.local-plan.dummy-secrets` |
| `O-LPLAN-SUFFIX` | ``local-plan -s -OTHER`` diffs the configuration against ``<org>.jsonnet-OTHER``: the description changes from the -OTHER value to the head value (one... | - | verified | `tests/offline/test_cli_local_plan_flags.py` (2 tests) | `cli.local-plan.suffix-and-missing-base` |
| `O-MISSING-ORG-CONFIG` | otterdog.json and the vendored template but no orgs/&lt;org&gt;/&lt;org&gt;.jsonnet: validate and show exit 1 with "configuration file '...' does not exist, run... | - | verified | `tests/offline/test_config_loading.py` (1 test) | `cli.validate.missing-config` |
| `O-ORG-SELECTION` | Two organizations, the first with one validation error, the second valid: without positional both are processed in configuration order and the exit status... | - | verified | `tests/offline/test_config_loading.py` (1 test) | `cli.global.organizations` |
| `O-SHOW` | show only evaluates the configuration: with an organization entry whose credentials name no provider it still prints the configuration (exit 0), while... | - | verified | `tests/offline/test_cli_basics.py` (1 test) | `cli.show` |
| `O-SHOW-DEFAULT-MARKDOWN` | ``show-default --markdown`` prints the template defaults as mkdocs tabs: one ``=== "<object>"`` tab per object type holding a jsonnet code fence with the... | - | verified | `tests/offline/test_cli_basics.py` (1 test) | `cli.show-default.markdown` |
| `O-SHOW-MARKDOWN` | ``show --markdown --output-dir DIR`` creates DIR and writes configuration.md (front matter, the five organization tabs with the webhook, secret, variable... | - | verified | `tests/offline/test_cli_basics.py` (1 test) | `cli.show.markdown` |
| `O-TEMPLATE-HOOK-PRE-ADD` | pre-add-object-hook.py runs once per added object while local-apply prints its plan, before the prompt (answered 'n'); local-plan never runs it and changes... | - | verified | `tests/offline/test_config_template_hooks.py` (1 test) | `config.hook.pre-add-object` |
| `O-TEMPLATE-HOOK-VALIDATE` | A validate-org-settings.py requiring default_repository_permission 'none' turns the template default 'read' into a validation error (validate exits 1... | - | verified | `tests/offline/test_config_template_hooks.py` (2 tests) | `config.hook.validate-org-settings` |
| `O-TEMPLATE-URL` | A base template URL (here from the defaults override) that is not on github.com or lacks its `#<file>@<ref>` fragment stops the loading: exit 2 for... | - | verified | `tests/offline/test_config_loading.py` (1 test) | `config.template-url` |
| `O-VERBOSITY` | Without -v the Info of a dummy secret is only counted ('in order to print validation infos ...'); -v prints the Info box and drops the hint; -vv adds DEBUG... | - | verified | `tests/offline/test_cli_exit_codes.py` (1 test) | `cli.global.verbosity` |
| `O-WEB-BOOT-CONFIG` | A required setting that is empty, or only whitespace (values are stripped), stops the webapp at boot with '&lt;SETTING&gt; must not be empty': the recreated... | - | verified | `tests/offline/test_webapp_runtime.py` (2 tests) | `regression.712-fail-fast-configuration`, `receiver.endpoint` |
| `O-WEB-HOOK-ERROR` | MongoDB stopped: a pull_request delivery answers 500 (with #775 the hook failure is logged with the delivery context), /internal/check 500 {} and /index the... | - | verified | `tests/offline/test_webapp_runtime.py` (1 test) | `receiver.hook-exception`, `webapp-runtime.internal-unknown` |
| `O-WEB-LOGIN-REQUIRED` | With a (dummy) OAuth client the webapp initializes its login manager: /myprojects without a session answers 401 with the 'Error 401 - Access Denied' page... | - | verified | `tests/offline/test_webapp_runtime.py` (1 test) | `webapp-runtime.login-required` |
| `O-WEB-ROUTES` | / redirects to /index; /&lt;name&gt;[.html] redirects to the page of the endpoint &lt;name&gt; | - | verified | `tests/offline/test_webapp_contract.py` (8 tests) | `webapp-runtime.pages-public`, `webapp-runtime.api-graphql`, `webapp-runtime.pages-admin`, `webapp-runtime.internal-unknown`, `webapp-runtime.api-statistics` |

### Live CLI Python tests (`tests/cli`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `cli.check-status` | After the apply, check-status of the same configuration is valid-but-warning and out of sync with no change; pending description changes count per filtered... | P0 | implemented | `tests/cli/test_commands_check_status.py` (2 tests) | `cli.check-status` |
| `cli.cmd.apply-failed-patches` | Two repositories granting a team that does not exist: exactly two 'failed to apply patch' errors and a non-zero exit, a third repository is created normally, the failing... | P1 | implemented | `tests/cli/test_commands_errors.py` (1 test) | `cli.apply.failed-patches` |
| `cli.cmd.missing-config` | Without ``orgs/<org>/<org>.jsonnet`` the command names the missing file and exits 1 | P2 | implemented | `tests/cli/test_commands_errors.py` (1 test) | `cli.validate.missing-config` |
| `cli.config-repo.missing` | With a config_repo that does not exist, fetch-config, push-config and open-pr print their failure and exit 1; nothing is created | P1 | implemented | `tests/cli/test_commands_config_repo.py` (1 test) | `cli.fetch-config`, `cli.push-config`, `cli.open-pr` |
| `cli.delete-file` | ``delete-file`` removes a file of a configured repository with ``-m`` as commit message, then another one with the default message; a file that does not... | P2 | implemented | `tests/cli/test_commands_content.py` (1 test) | `cli.delete-file` |
| `cli.dispatch-workflow` | A workflow_dispatch workflow of a run repository is dispatched on the default branch (a workflow_dispatch run of that workflow appears); an unknown workflow... | P2 | implemented | `tests/cli/test_commands_content.py` (1 test) | `cli.dispatch-workflow` |
| `cli.fetch-config.variants` | ``fetch-config -f -p <n> -s -PR`` writes the head of the pull request, ``-r <branch> -s -REF`` the branch, the plain fetch the default branch, each to its... | P0 | implemented | `tests/cli/test_commands_config_repo.py` (2 tests) | `cli.fetch-config` |
| `cli.http-cache` | Warm the shared HTTP cache with a plan of a run repository, change its description out of band, and the next plan (same CLI, same cache, well within... | - | implemented | `tests/cli/test_org_config.py` (1 test) | `config.http-cache` |
| `cli.import.custom-properties` | The import declares the three definitions and the repository values, and planning them changes nothing | - | implemented | `tests/cli/test_repo_import.py` (1 test) | `regression.import-multiple-custom-properties` |
| `cli.import.no-web-ui-warning` | ``import -f -n`` warns that the Web UI is not queried, writes the file it names, sets no web-only setting and reads every secret value as the dummy GitHub... | P2 | implemented | `tests/cli/test_commands_import.py` (1 test) | `cli.import.web-ui` |
| `cli.import.overwrite` | The second import backs the edited file up to ``<file>.bak``, copies the literal secret values of the edited file (repository secret, unmasked webhook) and... | P1 | implemented | `tests/cli/test_commands_import.py` (2 tests) | `cli.import.overwrite-backup-secrets` |
| `cli.import.protections` | The imported repository block declares both rulesets (nested defaults and nulls spelled out) and the rule, and planning it against the live organization... | - | implemented | `tests/cli/test_protection_import.py` (1 test) | `regression.675-ruleset-unset-defaults` |
| `cli.kb.blueprint-commands-without-webapp` | Without defaults.base_url the command refuses to run ('no base_url set ...', exit 2) instead of crashing on the webapp modules a CLI-only install lacks (KB-042) | P1 | implemented | `tests/cli/test_commands_blueprints.py` (1 test; xfail KB-042) | `cli.list-blueprints`, `cli.approve-blueprints` |
| `cli.kb.check-status-exit-code` | check-status of an invalid configuration exits non-zero (KB-011: it always exits 0) | P2 | implemented | `tests/cli/test_commands_check_status.py` (1 test; xfail KB-011) | `cli.check-status` |
| `cli.kb.delete-file-missing` | Deleting a file that does not exist (in the session's config repository, declared by the baseline) must not be reported 'succeeded' (KB-044: otterdog prints... | P2 | implemented | `tests/cli/test_commands_content.py` (1 test; xfail KB-044) | `cli.delete-file` |
| `cli.kb.delete-file-refused` | A deletion GitHub refuses (the default branch requires pull requests, admins included) prints 'failure deleting file' and exits 1, the file stays (KB-043... | P2 | implemented | `tests/cli/test_commands_content.py` (1 test; xfail KB-043) | `cli.delete-file` |
| `cli.kb.dispatch-workflow-exit-code` | A dispatch GitHub refuses (no such workflow in the session's config repository: a 404, nothing changes) is a failure: 'failed to dispatch workflow' and a... | P2 | implemented | `tests/cli/test_commands_content.py` (1 test; xfail KB-045) | `cli.dispatch-workflow` |
| `cli.kb.fetch-config-ref-message` | ``fetch-config -r <branch>`` must not claim it read the default branch (KB-049: the message ignores -r) | P2 | implemented | `tests/cli/test_commands_config_repo.py` (1 test; xfail KB-049) | `cli.fetch-config` |
| `cli.kb.import-masked-webhook-secret` | The masked webhook keeps the secret of the previous configuration like every other webhook (KB-048: secrets are copied by exact URL before the URLs are... | P2 | implemented | `tests/cli/test_commands_import.py` (1 test; xfail KB-048) | `cli.import.overwrite-backup-secrets` |
| `cli.kb.list-advisories-markup` | The CSV holds an advisory summary verbatim, brackets included (KB-050: the rows are printed through rich markup, so '[e2e]' and '[x]' vanish from the... | P2 | implemented | `tests/cli/test_commands_read.py` (1 test; xfail KB-050) | `cli.list-advisories` |
| `cli.kb.push-config-invalid-exit-code` | Refusing to push an invalid configuration is a failure: a non-zero exit and no 'no changes' claim (KB-046: exit 0 and 'no changes, nothing pushed') | P2 | implemented | `tests/cli/test_commands_config_repo.py` (1 test; xfail KB-046) | `cli.push-config` |
| `cli.list-advisories` | A draft advisory of a run repository is a complete CSV row of ``list-advisories`` (default states triage and draft) and of ``-s all``, absent from ``-s published``... | P2 | implemented | `tests/cli/test_commands_read.py` (1 test) | `cli.list-advisories` |
| `cli.list-apps` | ``list-apps --json``: the JSON array equals the installations (app_id, app_slug, permissions) sorted by slug, the e2e App included when it is ready; without... | P2 | implemented | `tests/cli/test_commands_read.py` (1 test) | `cli.list-apps` |
| `cli.list-members` | ``list-members``: 'Found &lt;n&gt; members.' with n = GET /orgs/{org}/members; ``--two-factor-disabled``: the number of members without 2FA out of n, and the 2FA... | P2 | implemented | `tests/cli/test_commands_read.py` (1 test) | `cli.list-members` |
| `cli.local-apply` | local-apply adds, ignores live drift and (only with -d) deletes, following the BASE -> config diff | P1 | implemented | `tests/cli/test_commands_local_apply.py` (1 test) | `cli.apply.prompt`, `cli.local-apply` |
| `cli.open-pr.negatives` | open-pr opens no pull request and creates no branch for a configuration identical to the default branch (exit 0), one with a validation error (exit 1), an... | P1 | implemented | `tests/cli/test_commands_config_repo.py` (2 tests) | `cli.open-pr`, `regression.691-open-pr-author` |
| `cli.org.code-security-defaults` | A default configuration makes otterdog plan 'false -> true'; the apply removes every default; enabling (true -> false) is never planned | - | implemented | `tests/cli/test_org_code_security.py` (1 test) | `org-settings.code-security-defaults` |
| `cli.plan.missing-web-credentials` | Without ``-n`` and without web credentials the command stops at 'invalid credentials' (exit 1) naming the missing username variable; import writes no file | P2 | implemented | `tests/cli/test_commands_errors.py` (1 test) | `cli.plan.web-ui` |
| `cli.push-config.variants` | ``push-config -m <msg>`` shows the local-plan diff against the current definition and asks: 'n' pushes nothing, 'y' pushes with the message; pushing the... | P0 | implemented | `tests/cli/test_commands_config_repo.py` (4 tests) | `cli.push-config` |
| `cli.repo.code-scanning` | The default setup is configured with the extended suite for actions and python, converges, then is disabled | - | implemented | `tests/cli/test_repo_code_scanning.py` (1 test) | `repositories.code-scanning`, `regression.458-411-435-code-scanning-live` |
| `cli.repo.default-branch` | A missing default branch is a rename of the current one, an existing one a switch that keeps the old branch | - | implemented | `tests/cli/test_repo_default_branch.py` (1 test) | `repositories.default-branch` |
| `cli.repo.from-template` | The generated repository has the template's files, README.md rendered for it, NOTICE.md left as it is | - | implemented | `tests/cli/test_repo_template.py` (1 test) | `repositories.template-repositories` |
| `cli.repo.ghsa-ignored` | Neither plan nor ``apply -d`` touches the advisory's temporary private fork, which keeps existing | - | implemented | `tests/cli/test_repo_ghsa.py` (1 test) | `repositories.ghsa-forks-ignored` |
| `cli.show-live` | ``show-live -n``: the settings block holds the REST values and no web-only key, and every repository and team the oracle lists (the baseline ones included)... | P2 | implemented | `tests/cli/test_commands_read.py` (1 test) | `cli.show-live` |
| `cli.sync-template` | A repository created from a run template repository renders README.md (post_process_template_content); after the template changes, ``sync-template`` copies... | P2 | implemented | `tests/cli/test_commands_content.py` (1 test) | `cli.sync-template` |
| `cli.team.exclude-pattern` | A live team matching defaults.github.exclude_teams is not planned for removal, not imported, and declaring a matching team fails validation with the... | - | implemented | `tests/cli/test_org_config.py` (1 test) | `config.exclude-teams`, `validation.teams` |
| `cli.template.hidden-fields` | ``has_wiki:: false`` is never sent (GitHub keeps its default, true) nor diffed (live true, hidden false: no change); ``has_wiki: false`` mixed in after it... | - | implemented | `tests/cli/test_org_config.py` (1 test) | `config.template-feature-gating` |
| `cli.token-scopes` | ``check-token-permissions -l`` with the admin token: 'Granted scopes:' lists exactly the X-OAuth-Scopes of the token (a superset of the five otterdog... | P1 | implemented | `tests/cli/test_commands_read.py` (2 tests) | `cli.check-token-permissions` |
| `cli.validate.code-scanning-languages` | 'go' on a Python repository is a validation error naming 'Python'; 'python' and 'actions' validate; 'cobol' is refused twice (enum and detection; the exit... | - | implemented | `tests/cli/test_org_validation.py` (1 test) | `validation.repo.code-scanning` |

### Webhooks (`tests/webhooks`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `H-ORG-HOOK-ALIAS` | docs/userguide/renaming.md: a new url with the old one in ``aliases`` updates the hook in place (no add, no remove). otterdog matches the live hook through... | P2 | implemented | `tests/webhooks/test_managed_org_hook.py` (1 test; xfail KB-004) | `webhooks.org.aliases` |
| `H-ORG-HOOK-SECRET` | A plain secret is applied once (GitHub signs the deliveries, reports `********`), never compared afterwards, forced by --update-webhooks (url filter)... | P1 | implemented | `tests/webhooks/test_managed_org_hook.py` (1 test) | `cli.plan.update-webhooks`, `webhooks.org.secret` |
| `H-ORG-HOOK-UPDATE` | events, content_type, active and insecure_ssl are changed in one '~ org_webhook' change, then changed back; after each apply the oracle reads them (events... | P1 | implemented | `tests/webhooks/test_managed_org_hook.py` (1 test) | `webhooks.org.settings` |

### Webapp (`tests/webapp`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `W-AUTOMERGE-AUTHOR-TEAM` | The approver (approval team) authors the PR: author_can_auto_merge true, auto-merge offered without any review, ``/otterdog merge`` merges and applies | P0 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-automerge.eligibility` |
| `W-AUTOMERGE-DISMISS` | Contributor PR: requested changes leave has_required_approvals false (no offer); the approval sets it and offers auto-merge; the admin dismisses the... | P1 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-events.review` |
| `W-AUTOMERGE-DRIFT` | A declared run repository drifts: the PR adding another repository is out of sync (check-sync comment, in_sync false) yet offered for auto-merge... | P1 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-pr.apply`, `regression.in-sync-not-required` |
| `W-AUTOMERGE-THIRD-PARTY` | Eligible contributor PR (approved): ``/otterdog merge`` by an outsider is refused ("Only the author of the pull request, a member of ... is allowed to... | P1 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-automerge.third-party` |
| `W-BP-APPEND` | A config PR appends the rendered snippet to otterdog/&lt;org&gt;.jsonnet and requests the approval team; the webapp validates it; merging applies the new... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test) | `blueprints.append-configuration` |
| `W-BP-CHECK` | With BLUEPRINT_CHECK_INTERVAL=3600 a second /internal/check skips both evaluated blueprints (logged at debug level); with 0 again /internal/check/1... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test) | `webapp-runtime.config`, `blueprints.check-endpoint` |
| `W-BP-DISMISS` | Close -> dismissed (comment, branch deleted by the webapp, /api/blueprints/dismissed); a check opens no new PR; reopen -> reinstated; after a second close... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test) | `webapp-events.pr-reopened`, `blueprints.status-and-dismissal`, `blueprints.remediations-api`, `regression.766-blueprint-dismissed` |
| `W-BP-GLOBAL-PUSH` | A global definition pushed to the configs repo is loaded without /internal/init (webhook/__init__.py:319-334) | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test; xfail KB-015) | `webapp-events.push`, `blueprints.loading` |
| `W-BP-LOAD` | Org definitions load with the push of config repo main (an untyped one is logged and skipped); an init loads a global definition, which then wins over an... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test) | `webapp-runtime.init`, `blueprints.loading` |
| `W-BP-LOAD-YAML` | A definition file that is not YAML is skipped and the valid definition next to it loads (the broken file is committed first, so no fetch can load the valid... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test; xfail KB-069) | `blueprints.loading` |
| `W-BP-PIN` | The remediation PR pins ``actions/checkout@v4`` to its tag's commit and keeps the other references; merging it gives success | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test; xfail KB-073) | `blueprints.pin-workflow` |
| `W-BP-RECHECK-LOST` | A changed definition of a blueprint in status success is re-evaluated by the next /internal/check (control: one fetch), also when another fetch (an... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test; xfail KB-071) | `blueprints.loading` |
| `W-BP-REQUIRED-FILE` | Remediation PR with rendered files, /api/blueprints/remediations, strict rewrite on a recheck (non-strict edits kept), merge -> success, and a push removing... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test) | `webapp-events.push`, `blueprints.required-file`, `blueprints.status-and-dismissal`, `blueprints.remediations-api` |
| `W-BP-SCORECARD` | The remediation PR adds the rendered scorecard workflow; merging gives success; the next check syncs the scorecard result (none is stored for a repository... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test) | `blueprints.scorecard-integration` |
| `W-BP-TYPE-CHANGE` | The definition file of a required_file blueprint becomes a pin_workflow one (same id): after the fetches that store it (two are needed, see W-BP-UPDATE)... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test; xfail KB-072) | `blueprints.loading`, `blueprints.check-endpoint` |
| `W-BP-UPDATE` | A commit changing the name and the repo selector of a definition is stored completely by the fetch it triggers (the new name proves that this fetch ran... | P2 | implemented | `tests/webapp/test_blueprints.py` (1 test; xfail KB-070) | `blueprints.loading` |
| `W-CLI-BLUEPRINTS` | list-blueprints lists the run's remediation PR (and refuses to run without base_url); approve-blueprints merges it; the webapp records the merge, deletes... | P1 | implemented | `tests/webapp/test_cli_blueprints.py` (1 test) | `cli.list-blueprints`, `cli.approve-blueprints` |
| `W-CMD-APPLY` | The PR adds a repository that already exists on GitHub (created out of band): the apply fails ([!CAUTION], 'failed to apply patch', apply_status... | P1 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-commands.apply`, `webapp-pr.apply-guards` |
| `W-CMD-CHECK-MERGE-REFRESH` | Approval team = a run team (otterdog.json override): the contributor's PR is not eligible; once the contributor is a member of that team, ``/otterdog check-merge``... | P2 | implemented | `tests/webapp/test_check_merge.py` (1 test) | `pending.automerge-state-refresh` |
| `W-CMD-NEG` | re.match at the start of the body: 'please /otterdog help' is ignored, '/otterdog validate' validates, '/otterdog helpme ...' helps, a second line is... | P1 | implemented | `tests/webapp/test_commands.py` (1 test) | `webapp-events.issue-comment`, `webapp-commands.matching` |
| `W-CMD-TEAM-INFO` | Contributor PR: team-info comment on open (author, role, contributors team), /api author_can_auto_merge false; ``/otterdog team-info`` by the author posts a... | P1 | implemented | `tests/webapp/test_commands.py` (1 test) | `webapp-commands.team-info` |
| `W-CMD-UPDATE-BRANCH` | Outdated note, refusal of a third party, merge update by the author (note gone), rebase by an admin | P2 | implemented | `tests/webapp/test_update_branch.py` (1 test) | `pending.update-branch-command`, `pending.outdated-branch-note` |
| `W-CMD-VALIDATE-INFO` | A dummy repository secret (Info "only has a dummy value"): the default validation only counts the infos, ``/otterdog validate info`` prints them; the... | P2 | implemented | `tests/webapp/test_commands.py` (1 test) | `webapp-commands.validate-info` |
| `W-INSTALLATION-EVENTS` | suspend -> suspended; unsuspend -> installed + data refresh; deleted -> not_installed, id 0; created -> installed with the real id + data refresh | P2 | implemented | `tests/webapp/test_installation_events.py` (1 test) | `webapp-events.installation` |
| `W-MERGE-APPLY-CRASH` | A merged PR whose local-apply raises (the trigger is KB-039: a ``#Admin`` bypass actor validates, building the ruleset payload raises KeyError): the apply... | P1 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-pr.apply-guards` |
| `W-MERGE-COMMIT-APPLY` | Two commits merged with a merge commit: the base of the apply is the first parent, so the repositories of both commits are created and named by the apply... | P0 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-pr.apply` |
| `W-MERGE-DELETE` | A PR removing a declared run repository: the validation shows the removal, auto-merge is never offered and ``/otterdog merge`` refused (deletions); the... | P0 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-pr.apply-deletions`, `webapp-automerge.blockers` |
| `W-MERGE-INVALID` | A PR failing validation (invalid topic) merged through the API (no /otterdog): the ApplyChangesTask skips it (finished, no comment), nothing is created on... | P1 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-pr.apply-guards` |
| `W-MERGE-SECRET` | A new run repository with a secret, merged by the admin: the webapp creates the repository but never the secret (partially_applied, "only partially... | P1 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-commands.done`, `webapp-commands.apply`, `webapp-pr.apply-partial` |
| `W-MERGE-TEAM-HOOK` | A run team and a run repository whose webhook url carries a token, declared on main with a wildcard url (``.../<slug>*``): the merged PR changing the team... | P2 | implemented | `tests/webapp/test_merge_apply.py` (1 test; xfail KB-068) | `plan-semantics.wildcard-keys`, `regression.local-apply-teams-webhooks` |
| `W-OPEN-PR-BRANCH` | open-pr PRs: closing one makes the webapp delete its otterdog/* branch; deleting the branch of the other one first (GitHub closes the PR) leaves the webapp... | P2 | implemented | `tests/webapp/test_otterdog_branches.py` (1 test) | `webapp-events.pr-closed`, `webapp-pr.delete-otterdog-branch`, `regression.713-already-deleted-branch` |
| `W-POL-LOAD` | Global policies load on /internal/init; org policies pushed to config repo main merge over them (path, name, allowed and workflow_filter from the org... | P2 | implemented | `tests/webapp/test_policies.py` (1 test) | `webapp-runtime.init`, `policies.loading` |
| `W-POL-LOAD-MALFORMED` | A policy file without ``type`` is skipped and the valid org policy next to it loads (the malformed file is committed first, so no fetch can load the valid... | P2 | implemented | `tests/webapp/test_policies.py` (1 test; xfail KB-069) | `policies.loading` |
| `W-POL-MACOS` | allowed false: the queued job is cancelled by the App (run cancelled, cancelled counter +1); allowed true: the job is only counted (permitted counter +1... | P2 | implemented | `tests/webapp/test_policies.py` (1 test) | `webapp-events.workflow-events`, `webapp-runtime.pages-admin`, `policies.macos-large-runners` |
| `W-POL-SBOM` | A matching successful run uploads {projectName, projectVersion, parentUUID, autoCreate, bom} with the API key; a non-matching workflow_filter uploads... | P2 | implemented | `tests/webapp/test_policies.py` (1 test) | `webapp-events.workflow-events`, `webapp-runtime.config`, `policies.dependency-track-upload` |
| `W-PR-CLOSED` | A PR closed without merge leaves /api (status closed) without ApplyChangesTask or apply comment; a PR merged into another branch than the default one is... | P0 | implemented | `tests/webapp/test_merge_apply.py` (1 test) | `webapp-events.pr-closed`, `webapp-pr.apply-guards` |
| `W-PR-DRAFT` | Draft: record only (draft true), no comment, no status | P1 | implemented | `tests/webapp/test_pr_validation.py` (1 test) | `webapp-events.pr-draft`, `webapp-commands.team-info` |
| `W-PR-EVAL-ERROR` | A team_permissions value outside the schema raises while the configuration loads (KB-032): the validate comment shows the friendly evaluation error (no... | P1 | implemented | `tests/webapp/test_pr_validation.py` (1 test) | `webapp-pr.validation-failure` |
| `W-PR-IMPORT-CONFINEMENT` | A repository description imported from ``../<file>`` (outside the org directory): the import is refused before any read ("is not allowed", not "can't... | P1 | implemented | `tests/webapp/test_pr_validation.py` (1 test) | `webapp-pr.import-confinement` |
| `W-PR-NO-CHANGES` | README.md only: "No changes." and success; the org config plus README.md in one commit (multi-file PR): the config diff is validated | P2 | implemented | `tests/webapp/test_pr_validation.py` (1 test) | `webapp-pr.no-changes`, `webapp-automerge.blockers` |
| `W-PR-REOPEN` | Closed without merge: gone from /api (status closed), no ApplyChangesTask, no apply comment | P2 | implemented | `tests/webapp/test_pr_validation.py` (1 test) | `webapp-events.pr-reopened` |
| `W-PR-SYNCHRONIZE` | Three commits: each head gets its own validation and validate comment (the previous one minimized); the sync status of commits 2 and 3 is copied from the... | P0 | implemented | `tests/webapp/test_pr_validation.py` (1 test) | `webapp-events.pr-synchronize`, `webapp-pr.sync-propagation` |
| `W-PR-WARNINGS` | Secret: secrets warning, manual apply, no auto-merge | P1 | implemented | `tests/webapp/test_pr_validation.py` (1 test) | `webapp-pr.validation-warnings`, `webapp-automerge.blockers`, `regression.771-warning-wording`, `regression.770-cost-automerge` |
| `W-RT-ADMIN-TEAMS-SPACES` | GITHUB_ADMIN_TEAMS `x, <admin>` names `<org>/x, <org>/<admin>` in the help comment; the approval patterns `^x$, ^<approval>$` (stripped by otterdog) are the... | P2 | implemented | `tests/webapp/test_runtime.py` (1 test; xfail KB-013) | `webapp-runtime.config` |
| `W-RT-API-PROJECTS` | /api/projects/&lt;project&gt; answers the stored configuration of /api/organizations/&lt;org&gt;; an unknown project or organization answers 404 with an empty JSON object | P2 | implemented | `tests/webapp/test_runtime.py` (1 test) | `webapp-runtime.api-projects` |
| `W-RT-CONFIG-TEAMS` | GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS name a team that does not exist: the help comment names the admin and approval teams of the otterdog.json... | P1 | implemented | `tests/webapp/test_runtime.py` (1 test) | `webapp-runtime.config` |
| `W-RT-INIT-APPLY-STATUS` | A merged PR adding a repository secret is partially applied (secrets need a manual apply); a later /internal/init re-imports the config repo's PRs and must... | P2 | implemented | `tests/webapp/test_runtime.py` (1 test; xfail KB-074) | `webapp-runtime.fetch-all-pull-requests` |
| `W-RT-INIT-IMPORTS-PRS` | PRs opened while the webapp is stopped: /internal/init imports the open one targeting main (open, not applied, never validated) and the one merged meanwhile... | P2 | implemented | `tests/webapp/test_runtime.py` (1 test) | `webapp-runtime.init`, `webapp-runtime.fetch-all-pull-requests` |
| `W-RT-PAGES` | Redirects of /organizations/&lt;org&gt;[/repos/&lt;repo&gt;], the project, repository, defaults and playground pages, the 404 pages of unknown names, /allprojects and... | P2 | implemented | `tests/webapp/test_runtime.py` (1 test) | `webapp-runtime.pages-projects`, `webapp-runtime.pages-admin` |
| `W-SYNC-FAILURE` | Main raises while it loads (team_permissions schema error, KB-032): the sync check of a PR and of ``/otterdog check-sync`` crash: status failure, no... | P2 | implemented | `tests/webapp/test_commands.py` (1 test; xfail KB-040) | `webapp-pr.sync-failure` |
| `W-SYNC-INVALID-MAIN` | Main declares a repository with an invalid topic (validation error): the sync plan of main aborts before comparing anything with GitHub, so the sync check... | P2 | implemented | `tests/webapp/test_commands.py` (1 test; xfail KB-067) | `webapp-pr.sync-check` |
| `W-SYNC-PROPAGATION-DRIFT` | Drifted org, PR out of sync; a second commit pushed within the hour copies the previous sync status | P2 | implemented | `tests/webapp/test_pr_validation.py` (1 test; xfail KB-066) | `webapp-pr.sync-propagation` |

### Web UI (`tests/web_ui`)

| Id | Scenario | Priority | Status | Implemented by | Features (coverage.yaml) |
|---|---|---|---|---|---|
| `webui.cmd.install-deps` | With the tier's browsers dir (the SUT's Firefox installed) install-deps succeeds offline: no error (a download attempt would fail without network) and no... | - | implemented | `tests/web_ui/test_web_commands.py` (2 tests) | `cli.install-deps` |
| `webui.kb.import-two-factor` | The import without ``-n`` (the module's single login) carries the live two_factor_requirement (KB-041: the web reader never loads the security page, the... | - | implemented | `tests/web_ui/test_web_settings.py` (1 test; xfail KB-041) | `org-settings.web-ui.two-factor` |
| `webui.kb.install-deps-exit-code` | A failed browser installation is a failure of install-deps: non-zero exit (KB-047: it exits 0) | - | implemented | `tests/web_ui/test_web_commands.py` (1 test; xfail KB-047) | `cli.install-deps` |

## Backlog

Entries that the [test battery](#test-battery) implements name its items in their status ("in part" when some of
the entry is still open); the others are still planned or future.

### Offline

| Id | Scenario | Priority | Status | Sources |
|---|---|---|---|---|
| O-CONFIG-LOAD-NEG | config discovery and load failures: missing or invalid `otterdog.json`, unknown organization, bad base template | P0 | verified: `O-CONFIG-DISCOVERY`, `O-CONFIG-JSONNET`, `O-CONFIG-ORG-ENTRIES`, `O-CONFIG-NO-BASE-TEMPLATE`, `O-CONFIG-ARCHIVED-ORG`, `O-TEMPLATE-URL`, `O-MISSING-ORG-CONFIG`, `O-LOCAL-MISSING-TEMPLATE` | CLI-01, CFG-04 |
| O-VAL-MATRIX | validation matrix of organization, repository and nested rules (errors, warnings, infos) | P0 | verified: the `O-VAL-*` scenarios of `scenarios/offline/validation` (see the battery tables) | CLI-02, MOD-VAL-ORG-01, MOD-VAL-REPO-01, MOD-VAL-NESTED-01 |
| O-PLAN-GATES | every plan-gated message: organization roles, `evaluate` enforcement, private Pages, private-visibility org variables, private wiki warning | P0 | verified: `O-VAL-PLAN-GATES`, `O-VAL-PLAN-GATES-TEAM` (KB-009), `O-VAL-PLAN-GATES-ENTERPRISE`, `O-VAL-ORGVAR` (KB-028) | PLAN-GATE-FREE-001, MOD-GATE-FREE-01, CFG-10 |
| O-SCHEMA | schema strictness (unknown properties as warnings vs blocking errors) and type crash cases | P1 | verified: `O-VAL-SCHEMA` (KB-032) | MOD-SCHEMA-01, MOD-SCHEMA-02 |
| O-LPLAN-CORPUS | local-plan golden corpus: nested objects, forced updates, read-only notes, real-world configurations | P1 | verified in part: `O-LPLAN-RESOURCE-TYPES`, `O-LPLAN-NESTED`, `O-LPLAN-FORCED-SECRETS`, `O-LPLAN-FORCED-WEBHOOKS`, `O-LPLAN-READ-ONLY-KEYS`; real-world configurations planned | CLI-03, MOD-LOCALPLAN-01, CFG-19 |
| O-TEMPLATE-FORMS | base template URL forms, caching, subdirectory copy, `.otterdog-defaults.json` and per-org precedence | P1 | verified in part: `O-TEMPLATE-URL`, `O-CONFIG-DEFAULTS-OVERRIDE`, `O-CONFIG-ORG-ENTRIES`, `O-CONFIG-NO-BASE-TEMPLATE`; template caching and the subdirectory copy planned | CFG-02, CFG-03, CLI-22 |
| O-JSONNET-CONFINE | jsonnet imports outside the organization directory are refused | P1 | implemented in the webapp tier (`W-PR-IMPORT-CONFINEMENT`); the offline CLI part is planned | CFG-07, REG-JSONNET-CONFINE |
| O-CUSTOM-JSONNET | customized jsonnet: helpers, overridden functions, appended snippets, `extendRepo`, aliases | P1 | verified in part: `O-EXTEND-REPO` (extendRepo), `O-LPLAN-RENAME` (aliases); helpers, overridden functions and appended snippets planned | CFG-24 |
| O-LOCAL-APPLY | `local-apply` semantics without network | P1 | verified: `O-LOCAL-APPLY-HINTS`, `O-LOCAL-APPLY-PROMPT`, `O-LPLAN-SECRET-REFS`, `O-TEMPLATE-HOOK-PRE-ADD`; live: `cli.local-apply` (implemented) | CLI-04 |
| O-ENV-CREDENTIALS | env credential provider resolution and error messages | P1 | verified: `O-CREDENTIALS-ENV`, `O-CREDENTIALS-PROVIDERS` | CLI-05 |
| O-WEB-BOOT-NEG | the webapp fails fast on invalid configuration (missing `BASE_URL`, blank token, missing secret, Mongo URI without database, `CACHE_CONTROL` unset under DEBUG) | P0 | verified in part: `O-WEB-BOOT-CONFIG` (empty and blank required settings), `O-KB-WEB-BOOT-EXIT-STATUS` (KB-061); the other boot failures planned | APP-BOOT-01, DEP-NEG-01 |
| O-SECRET-FORMATS | secret value formats (credential provider references, dummies) | P2 | verified: `O-VAL-SECRETS`, `O-KB-SECRET-WITH-COLONS` (KB-025), `O-LPLAN-SECRET-REFS`, `O-CREDENTIALS-PROVIDERS` | CFG-23 |
| O-PROMPTS | prompt and stdin contract of interactive commands | P2 | verified in part: `O-LOCAL-APPLY-PROMPT`; `cli.push-config.variants` (implemented); the other interactive commands planned | CLI-25 |
| O-UPSTREAM-COMPOSE | otterdog's own development compose file still works with the SUT | P2 | planned | DEP-UP-01 |

### CLI

| Id | Scenario | Priority | Status | Sources |
|---|---|---|---|---|
| C-ORG-SETTINGS | organization REST settings lifecycle (org level) | P0 | implemented: `cli.org.profile`, `cli.org.member-privileges`, `cli.org.signoff`, `cli.org.security-managers`, `cli.org.code-security-defaults` | MOD-ORGSET-REST-01, CLI-09 |
| C-ORG-SECRETS | organization secrets lifecycle, `--update-secrets`, selected repositories | P0 | implemented: `cli.org.secret`, `cli.org.secret-private`, `cli.kb.org-secret-same-apply` (KB-022) | MOD-OSEC-01, PRV-SECVAR-01 |
| C-REPO-PRIVATE | private repository and visibility-dependent fields; private repositories do not break import/plan on Free (#731, #791) | P0 | implemented: `cli.repo.visibility`, `cli.environment.private`, `regression.791-731-private-repo` | MOD-REPO-PRIV-01, REG-731-FREE, REG-767-791, MOD-DIFF-791-01 |
| C-REPO-RENAME | rename through aliases, repo-filter isolation | P0 | verified offline: `O-LPLAN-RENAME`, `O-LPLAN-FILTER` (KB-077); live: `regression.472-rename-and-modify` (implemented) | MOD-REPO-RENAME-01, CLI-24 |
| C-CACHE-LIMIT | Actions cache storage limit on Free without billing; endpoint path check | P0 | implemented: `cli.org.cache-size`, `cli.repo.cache-limit` | MOD-FREE-CACHE-01, CACHE-LIMIT-001, PRV-ACT-01 |
| C-HTTP-CACHE | a warm otterdog HTTP cache still detects out-of-band changes | P0 | implemented: `cli.http-cache` | PRV-CACHE-01 |
| C-CRED-ERRORS | credential, scope and API error contract (messages, exit codes) | P0 | implemented in part: `cli.plan.missing-web-credentials`, `cli.token-scopes`, `cli.config-repo.missing`; verified offline: `O-LPLAN-ERRORS`, `O-CREDENTIALS-PROVIDERS` | CLI-21, PRV-ERR-01 |
| C-BYPASS-ACTORS | ruleset bypass actors of every kind, user actors (#779), unknown actor types kept | P0 | implemented: `cli.ruleset.bypass` (KB-052 step), `cli.protection.app-checks`, `regression.779-user-bypass-actors`; unknown actor types planned | PRV-RS-01, BYPASS-USER-779, BYPASS-UNKNOWN-001, MOD-DIFF-767-779-01 |
| C-TEMPLATE-HOOKS | template hook contract in the CLI | P0 | verified offline: `O-TEMPLATE-HOOK-VALIDATE`, `O-TEMPLATE-HOOK-PRE-ADD`; validate-team, post-add-objects and the live part planned | CFG-08, MOD-HOOKS-01 |
| C-ORG-ACTIONS | organization and repository Actions settings, org coercion | P1 | implemented: `cli.org.actions-allowed`, `cli.org.actions-enabled-repositories`, `cli.org.workflow-permissions`, `cli.repo.actions`, `cli.repo.org-coerced` | MOD-ORGWF-01, MOD-REPOWF-01, PRV-ACT-01 |
| C-REPO-ARCHIVE | archive and unarchive ordering | P1 | implemented: `cli.repo.archive` | MOD-REPO-ARCHIVE-01 |
| C-REPO-BRANCH | default branch switch and rename | P1 | implemented: `cli.repo.default-branch` | MOD-REPO-BRANCH-01 |
| C-REPO-TEMPLATE | repository from a template with post-processing, `sync-template` | P1 | implemented: `cli.repo.from-template`, `cli.sync-template` | MOD-REPO-TEMPLATE-01, CFG-25, CLI-17 |
| C-REPO-SECURITY | security and analysis settings of a public repository (secret scanning, push protection, private vulnerability reporting, Dependabot) | P1 | implemented: `cli.repo.security` | MOD-REPO-SEC-01, GHAS-PUBLIC-001 |
| C-WEBHOOK-SECRETS | webhook secrets and `--update-webhooks`, URL change through aliases and wildcards | P1 | implemented: `cli.repo.webhook-secret`, `H-ORG-HOOK-SECRET`, `H-ORG-HOOK-ALIAS` (KB-004); verified offline: `O-LPLAN-FORCED-WEBHOOKS`, `O-LPLAN-WILDCARD` | MOD-WHSEC-01, MOD-WHALIAS-01, CLI-13 |
| C-PAGINATION | more than 10 variables and 30 secrets are read completely | P1 | implemented in part: variables (`cli.kb.variables-pagination`, KB-003); more than 30 secrets planned | PRV-PAGE-01 |
| C-RULESET-IDEMPOTENT | ruleset idempotency with default empty status checks | P1 | implemented: `cli.kb.ruleset-default-status-checks` (KB-021) and the converge steps of `cli.ruleset.*` | MOD-RRS-02 |
| C-RULESET-CRASH | apply-time resolution failures in rulesets | P1 | verified offline in part: `O-VAL-RULESETS` (KB-039), `O-VAL-RULESET-NESTED` (KB-031); webapp: `W-MERGE-APPLY-CRASH` (implemented) | MOD-CRASH-01 |
| C-ORDER | cross-resource dependencies in a single apply | P1 | implemented: `cli.kb.org-secret-same-apply` (KB-022), `cli.org.security-managers`, with `cli.kb.org-variable-same-apply` and `cli.team` | MOD-ORDER-01 |
| C-CHECK-STATUS | `check-status` JSON contract and semantics | P1 | implemented: `cli.check-status`, `cli.kb.check-status-exit-code` (KB-011) | CLI-14, MOD-CHECKSTATUS-01 |
| C-NEG-PRIVATE-ENV | environment on a private repository of a Free organization | P1 | planned (the Team/Enterprise case is `cli.environment.private`, implemented) | MOD-FREE-PRIV-ENV-01, PRV-ENV-02 |
| C-NO-WEB-UI | `--no-web-ui` semantics (the web side: the round trip's converge step and `W-PR-WEBUI`) | P1 | implemented: `cli.import.no-web-ui-warning`, `cli.plan.missing-web-credentials` | MOD-NOWEB-01 |
| C-CONFIG-REPO-PROTECTION | config repository protection versus `push-config` | P1 | planned (a refused deletion on a protected default branch: `cli.kb.delete-file-refused`) | CFG-22 |
| C-CODE-SCANNING | code scanning default setup on a public repository | P2 | implemented: `cli.repo.code-scanning`, `cli.validate.code-scanning-languages`; verified offline: `O-VAL-REPO` | MOD-REPO-CS-01 |
| C-REPO-FORK | repository creation from a fork | P2 | implemented: `cli.repo.fork` | MOD-REPO-FORK-01, PRV-FORK-01 |
| C-REPO-PAGES | GitHub Pages on a public repository and the `github-pages` environment | P2 | implemented: `cli.repo.pages`; verified offline: `O-VAL-PAGES`, `O-VAL-PAGES-ENTERPRISE` | MOD-REPO-PAGES-01 |
| C-MERGE-QUEUE | ruleset merge queue | P2 | implemented: `cli.ruleset.merge-queue`, `enterprise.ruleset-merge-queue-private` | MOD-RRS-03 |
| C-LISTINGS | listing commands and machine-readable outputs | P2 | implemented: `cli.list-apps`, `cli.list-members`, `cli.list-advisories`, `cli.show-live`, `cli.token-scopes`; verified offline: `O-SHOW`, `O-SHOW-MARKDOWN`, `O-SHOW-DEFAULT-MARKDOWN`, `O-HELP` | CLI-18 |
| C-CONTENT-OPS | `delete-file`, `dispatch-workflow` | P2 | implemented: `cli.delete-file`, `cli.dispatch-workflow` and their known bugs (KB-043, KB-044, KB-045) | CLI-17 |
| C-FREE-MISC | other private-repository features on Free | P2 | planned | MOD-FREE-MISC-01 |
| C-GHAS-VISIBILITY-FLIP | a public-to-private flip on Free disables GHAS features (drift handling) | P2 | implemented in part: `cli.repo.visibility` (security fields ignored while private) | GHAS-VISIBILITY-FLIP-001 |

### Webhooks

| Id | Scenario | Priority | Status | Sources |
|---|---|---|---|---|
| H-DELIVERY-AUDIT | every real App delivery of a session is accepted by the receiver | P1 | planned | WH-DLV-01, PRV-HOOKAPP-01 |
| H-REDELIVERY | redeliveries and duplicate replays are idempotent | P1 | planned | WH-REDELIVER-001 |
| H-NON-CONFIG-REPO | PRs and commands on a non-configuration repository are ignored | P1 | implemented in part: `W-CMD-NEG` (comments of another repository schedule nothing) | WH-NEG-02 |
| H-INSTALLATION-SUSPEND | installation suspend and unsuspend lifecycle | P1 | implemented: `W-INSTALLATION-EVENTS` | APP-WH-02, INFRA-SUSPEND-01 |
| H-OTTERDOG-JSON-PUSH | a push to `otterdog.json` and its refresh paths (needs `/internal/init` today) | P1 | planned | APP-WH-03, DEP-CFG-01 |
| H-RELAY-PAGINATION | relay pagination, watermark and exactly-once forwarding | P2 | planned | WH-PAGINATION-001 |
| H-SMEE | smee transport smoke test and signature fidelity | P2 | future | WH-SMEE-001, DEP-WH-02 |

### Webapp

| Id | Scenario | Priority | Status | Sources |
|---|---|---|---|---|
| W-PR-SYNC | new commit: revalidation, older comment minimized, sync status | P0 | implemented: `W-PR-SYNCHRONIZE`, `W-SYNC-PROPAGATION-DRIFT` (KB-066) | PR-SYNC-01 |
| W-PR-FLAGS | validation flags per change type | P0 | implemented: `W-PR-WARNINGS`, `W-MERGE-DELETE`, `W-MERGE-SECRET`, `W-PR-NO-CHANGES` | MOD-PR-FLAGS-01 |
| W-API-CONTRACT | REST API contract for tasks, pull requests and blueprints | P0 | implemented: `W-RT-API-PROJECTS` and the /api checks of the PR and blueprint tests; verified offline: `O-WEB-ROUTES` | APP-API-01 |
| W-TEMPLATE-HOOKS | template hook contract in the webapp (validation and apply comment) | P0 | planned | CFG-09 |
| W-REAL-WORLD-SETTINGS | high-frequency real-world settings through config-repo PRs | P0 | planned | CFG-21 |
| W-APP-AUTH | App authentication: JWT, installation token, cache | P0 | planned | PRV-APP-01 |
| W-PR-DRAFT | draft PRs are ignored until ready for review; draft/close/reopen lifecycle | P1 | implemented: `W-PR-DRAFT`, `W-PR-REOPEN` | PR-DRAFT-01, PR-LIFE-01 |
| W-PR-NONCFG | touching a non-configuration file blocks auto-merge | P1 | implemented: `W-PR-NO-CHANGES` | PR-NONCFG-01 |
| W-PR-DELETE | a resource removal is flagged and blocks auto-merge | P1 | implemented: `W-MERGE-DELETE` | PR-DELETE-01 |
| W-PR-COST | cost-related changes (Actions cache size) block auto-merge; new repository with default cache size stays auto-mergeable | P1 | implemented: `W-PR-WARNINGS` | PR-COST-01, MOD-PR-COST-01, REG-770, MOD-DIFF-770-01 |
| W-CMD-NEG | command parsing negatives and comment edits | P1 | implemented: `W-CMD-NEG` | CMD-NEG-01 |
| W-AUTOMERGE-NEG | ineligible approvals, dismissed approvals, `/otterdog merge` by a third person or on a closed PR, merge refused by GitHub, refusal comments | P1 | implemented: `W-AUTOMERGE-DISMISS`, `W-AUTOMERGE-THIRD-PARTY`, `W-MERGE-DELETE` | AM-NEG-01, AM-NEG-02, AM-NEG-03, AM-NEG-04, AM-THIRD-01, REG-603 |
| W-APPLY-RETRY | apply failure, `/otterdog apply` permissions, successful retry; merged invalid PRs are not applied | P1 | implemented: `W-CMD-APPLY`, `W-MERGE-INVALID`, `W-MERGE-APPLY-CRASH` | AP-RETRY-01, AP-NEG-01 |
| W-APPLY-MERGE-COMMIT | apply after a merge commit uses the first parent as base | P1 | implemented: `W-MERGE-COMMIT-APPLY` | AP-MERGE-01 |
| W-APPLY-DRIFT | apply replays only the PR diff and leaves unrelated drift | P1 | implemented: `W-AUTOMERGE-DRIFT` | AP-DRIFT-01 |
| W-PUSH-REFRESH | a push to the default branch refreshes the stored config without applying | P1 | implemented in part: the blueprint tests wait for the configuration a push to main stores; 'without applying' is not asserted | AP-PUSH-01 |
| W-RENAME-AND-MODIFY | rename a repository and change its settings in one PR | P1 | planned | REG-472 |
| W-RULESET-STATUS | required otterdog statuses through a ruleset | P1 | planned | RULESET-01 |
| W-INIT-NEG | case-mismatched `github_id`, broken global configuration | P1 | planned | APP-INIT-02, APP-INIT-03 |
| W-ORG-OVERRIDES | per-org `admin_teams`/`approval_teams` overrides from `otterdog.json` | P1 | implemented: `W-RT-CONFIG-TEAMS`, `W-CMD-CHECK-MERGE-REFRESH`, `W-RT-ADMIN-TEAMS-SPACES` (KB-013) | APP-INIT-04, INFRA-OVERRIDE-01, CFG-05 |
| W-CLI-PARITY | CLI `local-plan` matches the webapp validation comment; post-merge convergence | P1 | planned | CLI-PARITY-01, CLI-12 |
| W-API-GRAPHQL | GraphQL queries over stored configurations | P1 | verified offline in part: `O-WEB-ROUTES` (the GraphQL endpoint) | APP-API-02 |
| W-UI-PAGES | HTML pages without OAuth (HTTP checks only, no browser) | P1 | implemented: `W-RT-PAGES`; verified offline: `O-WEB-ROUTES`, `O-WEB-LOGIN-REQUIRED`, `O-KB-WEB-LOGIN-REQUIRED` (KB-059) | APP-UI-01 |
| W-UPGRADE-IN-PLACE | the head build continues the base build's database (upgrade in place) | P1 | planned | APP-PR-02, CS792-06 |
| W-BP-REQUIRED-FILE | `required_file` blueprint opens a remediation PR | P0 | implemented: `W-BP-REQUIRED-FILE` | APP-BP-01, CFG-12 |
| W-BP-APPEND-CONFIG | `append_configuration` blueprint creates a config PR that runs through the PR workflow | P0 | implemented: `W-BP-APPEND` | APP-BP-06, CFG-13 |
| W-BP-DISMISSAL | blueprint dismissal and reinstatement; a dismissed remediation PR is not recreated | P0 | implemented: `W-BP-DISMISS` | APP-BP-02, REG-766 |
| W-BP-APPROVE | `approve-blueprints` merges the remediation PR | P1 | implemented: `W-CLI-BLUEPRINTS` | APP-BP-03 |
| W-BP-REEVALUATION | push-triggered re-evaluation, check interval and limits | P1 | implemented: `W-BP-CHECK`, `W-BP-RECHECK-LOST` (KB-071), `W-BP-REQUIRED-FILE` (push re-evaluation) | APP-BP-04, APP-BP-05, DEP-BP-01 |
| W-BP-PRECEDENCE | org-level blueprints, id collisions, definition sync and precedence | P1 | implemented: `W-BP-LOAD`, `W-BP-GLOBAL-PUSH` (KB-015), `W-BP-UPDATE` (KB-070), `W-BP-TYPE-CHANGE` (KB-072) | CFG-14, APP-BP-09 |
| W-POLICY-MACOS | `macos_large_runners` policy (global deny, org override allow) cancels restricted jobs | P1 | implemented: `W-POL-MACOS` | APP-POL-01, CFG-16 |
| W-POLICY-OVERRIDES | policy override merge semantics | P2 | implemented: `W-POL-LOAD` | APP-POL-03 |
| W-BP-PIN-WORKFLOW | `pin_workflow` and `scorecard_integration` blueprints | P2 | implemented: `W-BP-PIN` (KB-073), `W-BP-SCORECARD` | APP-BP-07, APP-BP-08, CFG-15 |
| W-BP-MALFORMED | malformed blueprint and policy YAML robustness | P2 | implemented: `W-BP-LOAD-YAML`, `W-POL-LOAD-MALFORMED` (KB-069) | CFG-18 |
| W-STATS | pull request statistics endpoint | P2 | verified offline in part: `O-WEB-ROUTES` (parameter errors) | APP-STATS-01 |
| W-NON-DEFAULT-BRANCH | a PR merged into a non-default branch is validated but not applied | P2 | implemented: `W-PR-CLOSED` | AP-NEG-02 |
| W-BRANCH-DELETED | branch already deleted by GitHub after merging an `otterdog/*` PR | P2 | implemented: `W-OPEN-PR-BRANCH` | REG-713 |
| W-BOT-PR | PR authored by a bot account | P2 | planned | BOT-PR-01 |
| W-RACE-MERGE | `/otterdog merge` while a new commit is revalidated, or before the sync check finished | P2 | planned | NEG-RACE-01, CS792-04 |
| W-MULTI-WORKER | production-like multi-worker parity | P2 | planned | APP-MW-01 |
| W-CHECK-MERGE-FEATURE | the rest of the feature branch: outdated-branch note, `/otterdog update-branch`, stale team refresh, PRs unknown to the database (`/otterdog check-merge` itself: W-CMD-CHECK-MERGE) | P1 | implemented in part: `W-CMD-UPDATE-BRANCH` (outdated-branch note, `/otterdog update-branch`), `W-CMD-CHECK-MERGE-REFRESH` (stale team refresh); PRs unknown to the database planned | CM-01, CM-02, CM-03, CM-04, CM-05, CM-06, CM-07, OPR-CHECKMERGE-01, OPR-UPDATEBRANCH-01, OPR-REFRESH-01, OPR-LATEVALID-01 |
| W-POLICY-DTRACK | `dependency_track_upload` policy uploads an SBOM | P2 | implemented: `W-POL-SBOM` (the Dependency-Track mock, compose profile `dtrack`) | APP-POL-02, CFG-17, DEP-DT-01 |
| W-GHPROXY | ghproxy coherence and production-like boot with the ghproxy profile | P2 | future | PRV-GHP-01, DEP-BOOT-02 |
| W-TUNNEL-EXPOSURE | `/internal` endpoints unreachable through a public tunnel | P1 | future | DEP-SEC-01 |
| W-HELM | Helm chart lane on kind with the SUT image | P2 | future | DEP-HELM-01 |
| W-ARM64 | arm64 image build and boot | P2 | future | DEP-ARM-01 |

### Enterprise

| Id | Scenario | Priority | Status | Sources |
|---|---|---|---|---|
| E-PLAN-PERMISSION | custom org roles need the App's "Organization plan" permission; behaviour without it | P1 | planned | ROLES-ENT-001, PLAN-PERM-001 |
| E-EVALUATE | rulesets with `evaluate` enforcement | P1 | planned | MOD-ENT-EVAL-01 |
| E-FREE-VS-ENTERPRISE | the same enterprise-only configuration rejected on Free and accepted on Enterprise | P1 | planned | CLI-15, CFG-11 |
| E-ECLIPSE-COMPAT | an Eclipse-Foundation-derived template with hooks on the enterprise org | P1 | planned | CFG-20 |
| E-WEBAPP | the webapp serving an Enterprise Cloud org, private config repository regression pack | P1 | planned | DEP-ENT-01, APP-ENT-01, ENT-PRIVATE-01 |
| E-INTERNAL-REPO | an internal repository survives import, plan and apply | P1 | planned | MOD-ENT-INTERNAL-01, INTERNAL-REPO-ENT-001 |
| E-PRIVATE-PAGES | private Pages, cache limits and other enterprise-only settings | P2 | planned | MOD-ENT-PAGES-01, PAGES-ENT-001, PRV-ENT-02 |
| E-ORG-RULESET-CRASH | organization ruleset validation crash paths | P1 | planned | MOD-ENT-ORS-CRASH-01, CS790-03 |
| E-SSO-POLICY | SAML SSO and enterprise-policy-locked settings | P2 | planned | MOD-ENT-POLICY-01, PRV-ENT-SSO-01 |
| E-TEAM-PLAN | Team plan middle ground: organization rulesets (#776), push rulesets, private ruleset without perpetual diff | P1 | planned | MOD-TEAMPLAN-01, PLAN-GATE-TEAM-776, PUSH-RULESET-TEAM-001, REG-731-TEAM, CLI-16 |
| E-TRIAL-TRANSFER | transfer the Free test org into a trial and back | P2 | planned | ENT-TRIAL-001 |
| E-UNSUPPORTED-HOSTS | EMU, ghe.com and GHES organizations fail fast as unsupported | P2 | future | UNSUPPORTED-HOST-001 |

### Differential

| Id | Scenario | Priority | Status | Sources |
|---|---|---|---|---|
| D-TEMPLATE-MATRIX | base versus PR code crossed with base versus PR template (manifest `template`) | P0 | planned | CFG-06 |
| D-API-RECORDER | record the GitHub API calls of both sides and compare them | P0 | planned | PRV-DIFF-01 |
| D-WEBAPP | differential run of the webapp suite (merge-base image versus PR image) | P0 | planned | APP-PR-01, DEP-DIFF-01 |
| D-CHECK-STATUS | `check-status` JSON as the live-state oracle, base versus head | P1 | planned | REG-CHECK-STATUS-ORACLE |
| D-DEFAULTS-BLAST-RADIUS | blast radius of an otterdog-defaults template change | P1 | planned | CFG-26 |
| D-REPLAY-BURST | replay a captured delivery burst concurrently (#792 race) | P1 | planned | DEP-DIFF-02 |
| D-CROSS-VERSION-790 | PR validated by the base build, merged after the upgrade to the head build | P2 | planned | CS790-05 |

### Web UI

Implemented (see the web-UI table above): `CLI-09` (web part), `CLI-19`, `CLI-20`, `MOD-ORGSET-WEB-01`,
`MOD-FREE-WEB-01`, `PRV-WEB-01`, `PRV-WEB-03` (KB-041), `PRV-PERM-01`, `PRV-INSTALL-01`; the battery added
`webui.cmd.install-deps`, `webui.kb.install-deps-exit-code` (KB-047) and `webui.kb.import-two-factor` (KB-041). Still open: an approval through
`review-permissions -g` (it would change the e2e App's installation), the web settings of an Enterprise Cloud target
(`packages_containers_internal`), and every web-only feature the coverage matrix lists as a gap.
