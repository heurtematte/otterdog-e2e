# Writing the test battery

The battery closes the gaps of the coverage matrix: [`scenarios/coverage.yaml`](../scenarios/coverage.yaml) lists 337
otterdog features (81 covered, 77 partial, 179 gaps when this guide was written), and every partial or gap feature
carries a `gap_outline`: the suggested scenario id and file, the steps, the assertions and what the test needs. This
guide tells you, for each kind of gap, which harness API, YAML key, fixture or check kind to use, and lists the
conventions and checks every submission passes.

References: [writing-scenarios.md](writing-scenarios.md) is the reference of the YAML model (every key, every rule),
[architecture.md](architecture.md) of the components, [web-ui-testing.md](web-ui-testing.md) of the web-UI tier,
[security.md](security.md) of the guards. The generated [coverage-matrix.md](coverage-matrix.md) shows the same
outlines as the YAML.

## 1. From a gap outline to a merged test

1. **Pick a feature.** P0 first, then P1. In `scenarios/coverage.yaml` (or its page) read the feature's `title`,
   `notes`, `known_bugs` and `gap_outline`. Several features often share one suggested scenario (`O-VAL-PLAN-GATES`
   covers three plan gates): write one scenario that covers them all and list it in every feature's `covered_by`.
2. **Read the needs.** A need starting with `available:` names the harness API that provides it (the API exists and
   is unit-tested). `target`, `offline`, `webapp`, `docker`, `app`, `org_level`, `identity <role>`, `enterprise target`,
   App permissions and events are requirements of the target or the tier. Any other harness need (`TemplatePublisher on
   a branch`, `harness: vendor hook files`, ...) is still missing: do not work around it in a test, report it.
3. **Choose the tool** (section 3): a YAML scenario when the test is a sequence of configurations with otterdog and
   GitHub expectations, a Python test for everything else (CLI commands and flags, configuration loading, the webapp,
   webhooks, the web UI).
4. **Write it** following the conventions (section 2), with dummy secrets and run-prefixed names only.
5. **Run it alone**, offline first, then live:

    ```bash
    make one SCENARIO=O-VAL-ORGVAR                         # an offline scenario (no GitHub)
    make lint-scenarios                                    # every live scenario step validated offline
    make one SCENARIO=cli.org.workflow-permissions TARGET=free
    .venv/bin/otterdog-e2e run --target free --suite webapp -k test_draft_pr   # a Python test of a tier
    make report                                            # summary.md of the newest run
    ```

6. **Update the coverage matrix** (section 7) and run `make check` and `make offline`.
7. **Submit** with the checklist of section 9.

`otterdog-e2e assist coverage` lists the gap and partial features with their outlines, and the `fill-coverage-gap`
skill follows these steps with an AI agent, under the same gates and your review
([ai-assistance.md](ai-assistance.md)).

## 2. Conventions

### Ids, files and priorities

| Kind | Id | File |
|---|---|---|
| offline YAML scenario | `O-<AREA>-<NAME>` (`O-VAL-ORGVAR`, `O-LPLAN-RENAME`) | `scenarios/offline/<domain>/<command>-<name>.yaml` (`variables/val-org-variables.yaml`) |
| live CLI scenario | `cli.<area>.<name>` (`cli.org.workflow-permissions`) | `scenarios/cli/<domain>/<name>.yaml` (`workflows/org-workflow-permissions.yaml`) |
| known-bug reproduction (live) | `cli.kb.<name>` (`cli.kb.webhook-url-alias`) | `scenarios/cli/<domain>/kb-<name>.yaml` |
| negative test of a missing capability | `cli.neg.<name>` | `scenarios/cli/<domain>/neg-<name>.yaml` |
| regression of an otterdog PR or issue | `regression.<behaviour>` | `scenarios/cli/<domain>/<behaviour>.yaml` |
| enterprise-only scenario | `enterprise.<name>` (`enterprise.org-role`, `enterprise.kb.<name>`) | `scenarios/enterprise/<domain>/<name>.yaml` |
| offline Python test | `scenario("O-<NAME>")` marker | `tests/offline/test_<topic>.py` |
| live CLI Python test | `scenario("cli.<name>")` marker | `tests/cli/test_<topic>.py` |
| webapp / webhooks Python test | `scenario("W-<NAME>", priority="P1")` / `scenario("H-<NAME>", priority=...)` | `tests/webapp/test_<topic>.py`, `tests/webhooks/test_<topic>.py` |
| web-UI Python test | `scenario("webui.<area>.<name>")` | `tests/web_ui/test_web_<topic>.py` |

Use the id and file of the gap outline unless a better grouping emerges. One YAML scenario per file, in the domain
directory of the feature it pins (`<domain>`: a model-area tag of the scenario, or `template`, `cli`, `plan`;
[writing-scenarios.md](writing-scenarios.md#where-scenarios-live)); ids are unique across every directory. The `priority` is the feature's priority (P0 items count for the lane budgets). A scenario
linked to a known bug as a whole is never P0 and carries the `known-bug` tag.

### Tags

The vocabulary is `otterdog_e2e.selection.SCENARIO_TAGS`: the model areas `repo`, `bpr`, `rulesets`,
`environments`, `secrets`, `variables`, `webhooks`, `teams`, `custom-properties`, `org-settings`, `workflows`,
`org-roles`, and `template`, `cli`, `webapp`, `webhooks-app`, `offline`, `smoke` (the PR lane selects scenarios by the
files a PR changes, through these tags). Live YAML scenarios carry at least one model-area tag and may add
`regression` and `pr-<n>` (regressions) and `known-bug` (scenario-level known bugs); offline YAML scenarios start with
`offline` and use the vocabulary only; webapp and webhooks tests carry `tags(...)` from the vocabulary only.

### Names and secrets

Every object a test creates carries the run prefix: `{{ p }}-<slug>` (repositories, teams, rulesets, environments,
custom properties, roles), `{{ P }}_<SLUG>` (secrets, variables), `{{ hook_base }}<slug>` (webhook URLs), branches from
`run_ctx.branch(slug)` (`e2e/<run>/<slug>`); in Python `run_ctx.name(slug)`, `run_ctx.const(slug)`,
`run_ctx.hook_url(slug)`. Never `orgs.extendRepo` a baseline repository. Secret values are `********`,
`'e2e-dummy-{{ run }}'`, `pass:<path>` or `<provider>:e2e/<path>` references (and offline only `pass:a:b`, KB-025):
otterdog prints secret values.

### Known bugs and fixed_in

- `scenarios/known_bugs.yaml` is the registry ([known-issues.md](known-issues.md) mirrors it, a unit test checks that
  every entry has its section there). A new defect gets a new `KB-nnn` entry (`status: suspected` until reproduced,
  `confirmed` with a reproduction, `fixed` with `fixed_in`), its evidence (`otterdog/<path>:<line>`) and its doc
  section.
- **Scenario-level** `known_bug: KB-nnn` (or the bug's `scenarios:` list naming the scenario id): every step without
  a bug of its own inherits it, so the expectation failures of the steps are expected and the first one ends the run
  (XFAIL after the cleanup); infra problems, harness errors (exceptions, oracle lookups that fail) and a failed
  cleanup stay failures, and a run without the bug is an XPASS (the item's xfail accepts only
  `KnownBugReproduced`, never a `ScenarioFailedError`). Both sides must agree: the bug lists the scenario and the
  scenario declares the bug.
- **Step-level** `known_bug: KB-nnn` on a step: only that step's failures are expected, the other steps stay strict.
  `known_bug: {id: KB-nnn, phases: [converge]}` limits it to some phases (a converge bug then never hides a plan,
  apply or state failure of its step). The bug must NOT list the scenario (that would xfail the whole item);
  `tests/unit/test_known_bugs.py` checks every scenario and step link. Prefer it whenever a scenario tests more than
  the bug.
- **Python tests**: `@pytest.mark.known_bug("KB-nnn")` next to `@pytest.mark.scenario("<id>")`, and the bug lists the
  scenario id. The xfail covers the test body only: an error in a fixture's setup or teardown (a cleanup that leaves
  objects behind) is reported as an error, also in `results.jsonl`. It accepts only `AssertionError`
  (`raises=AssertionError`): the test reports the bug with `assert` (or an AssertionError subclass), and any other
  exception of the body (a GitHub error of the harness, a broken helper, `pytest.fail`, a pytest-timeout) stays a
  failure. A bug that surfaces as another exception needs the test's own `pytest.mark.xfail(raises=...)`, which takes
  precedence. In the webapp and webhooks tiers that extra `pytest.mark.xfail` naming the exception it tolerates is
  required, and `pytest.xfail()` is not used.
- A fixed bug (`status: fixed`, `fixed_in: 1.7.0.devN`) turns its tests into regression guards; SUTs older than
  `fixed_in` still xfail.
- **Unreleased fixes**: a regression of a fix merged after the latest release declares `fixed_in` (the version of the
  fix commit: `X.(Y+1).0.dev<n>` with `n = git rev-list --count v<last release>..<sha>`, computed in the harness mirror
  `$E2E_CACHE_DIR/mirror/eclipse-csi__otterdog.git`), and is listed in `UNRELEASED_FIXES` of
  `tests/unit/test_yaml_cli.py`. Offline scenarios whose outcome depends on the history leave the varying expectation
  out and assert it in `SUT_EXPECTATIONS` of `tests/offline/test_scenarios.py` (ancestry of the fix commit).

### Registries a new test touches

| Test | Also update |
|---|---|
| any test closing a gap | `scenarios/coverage.yaml` (`status`, `covered_by`, `gap_outline`), then regenerate `docs/coverage-matrix.md` |
| a new defect | `scenarios/known_bugs.yaml` + a `### KB-nnn` section of `docs/known-issues.md` (and its summary table row) |
| a regression with `fixed_in` | `UNRELEASED_FIXES` of `tests/unit/test_yaml_cli.py` |
| a live scenario with a probe | `PROBES` of `tests/cli/conftest.py` and the scenario's own `timeout` (only probe scenarios declare one) |
| an otterdog PR with expected differential deltas | a `references` entry `{pr: <n>, expected_deltas}` of the scenario of the behaviour ([testing-an-otterdog-pr.md](testing-an-otterdog-pr.md)) |

New offline scenarios and new webapp/webhooks tests need no registration in the unit tests: every offline scenario
file gets the metadata checks of `tests/unit/test_yaml_offline.py` (title, a description of 20 words or more, `offline`
as first tag, `observe: true`, objects named with the run prefix), every tier test the static checks of
`tests/unit/test_suite_webapp_static.py` (one `scenario(id, priority=...)` marker, tags, markers matching the
fixtures, no blind sleeps).

## 3. Which tool for which gap

| Area of the gap | Tool | Section |
|---|---|---|
| `validation` (errors, warnings, infos, plan gates) | offline YAML scenario | 3.1 |
| `plan-semantics`, `cli.local-plan.*`, forced updates, filters | offline YAML scenario with a `-BASE` | 3.2 |
| `config` (otterdog.json, discovery, defaults override, credentials) | offline YAML `workspace` key or a Python offline test | 3.3 |
| `cli` (commands, flags, usage errors, exit codes, stdin) | Python test (offline or `tests/cli`) | 3.4 |
| live objects (`org-settings`, `org-workflows`, `repositories`, `branch-protection`, `rulesets`, `environments`, `teams`, `secrets-variables`, `custom-properties`, `org-roles`) | live YAML scenario with state checks | 3.5 |
| enterprise-only features | `scenarios/enterprise` | 3.6 |
| `webhooks` (managed hooks, deliveries) | live YAML (`*_webhook*` kinds) or `tests/webhooks` | 3.7 |
| `receiver` (the webhook endpoint contract) | `tests/offline/test_webapp_contract.py` with the injector | 3.8 |
| `webapp-events`, `webapp-commands`, `webapp-pr`, `webapp-automerge` | `tests/webapp` with `webapp_scenario` | 3.9 |
| `blueprints`, `policies` | `tests/webapp` with the `blueprints` fixture | 3.10 |
| `webapp-runtime` (boot, environment, API, pages) | `tests/webapp` with `webapp_stack`, `webapp_env`, `webapp_api` | 3.11 |
| web-only settings and UI commands | `tests/web_ui` | 3.12 |
| `regressions`, `pending` (fixes and unmerged changes) | scenarios tagged `regression` in their domain, scenario `references`, differential | 3.13 |

### 3.1 Offline validation rules

Validation rules need no GitHub: write an offline YAML scenario (`scenarios/offline/<domain>/`). Each step renders the
minimal organization `e2e-offline` plus the step's fragments and runs `validate --local` (always; checked when
`validate` is given). Each step is an independent case with its own pytest item and result: one rule per negative
step, named after the case, and a control step at the limits. Useful keys:

- `validate: {ok, errors, warnings_min, contains, not_contains, exit_code}`; otterdog exits with the number of errors
  (two errors exit 2, like a crash: KB-034), so assert messages, not only exit codes;
- `validate: {verbose: true, infos: N}` (or `infos_min`) for Info messages: otterdog prints them with `-v` only
  (`Info: <message>` after normalization);
- `variables: {plan: team}` (or `enterprise`) for plan gates: validation reads the configured `settings.plan`;
- offline settings fragments may set the profile (`description`, `name`, `billing_email`, ...), never `plan`;
- `teams`, `newTeam` and `code_scanning_default_languages` are refused offline (their validation calls GitHub): test
  those rules live (3.5); languages set beside `code_scanning_default_setup_enabled: false` are validated offline (the
  language enum, `O-VAL-REPO`);
- a rule otterdog does not enforce yet (a registered bug): give the step `known_bug: KB-nnn`.

```yaml
# scenarios/offline/variables/val-org-variables.yaml
id: O-VAL-ORGVAR
title: Organization variables are validated like organization secrets
description: >-
  Organization variables with a visibility the plan does not offer or the reserved GITHUB_ prefix should be
  reported like secrets are; otterdog never validates organization variables (KB-028), so the strict expectation
  runs as an expected failure of its own step while the control step stays strict.
priority: P1
tags: [offline, variables]
observe: true
variables: {plan: free}
steps:
  - name: invalid-variables
    known_bug: KB-028
    fragments:
      variables:
        - "orgs.newOrgVariable('{{ P }}_PRIV') { value: 'x', visibility: 'private' }"
        - "orgs.newOrgVariable('GITHUB_{{ P }}') { value: 'x' }"
    validate:
      ok: false
      errors: 2
      contains: ["has 'visibility' of value 'private', which is not available for an organization with free plan."]
  - name: control
    fragments:
      variables: ["orgs.newOrgVariable('{{ P }}_OK') { value: 'x' }"]
    validate: {ok: true, errors: 0}
```

### 3.2 Diff and local-plan semantics

`local-plan` compares the step's configuration with a `-BASE` configuration, offline. Give the step `base_fragments`
(`{}` = the bare organization) or a complete `base_config: {file: ...}`; the plan expectations then apply to
`local-plan -s -BASE --local`:

- `plan: {expect: changes|noop|validation_error|error|any, counts: {add, change, delete}, contains, not_contains,
  exit_code}`: offline counts are otterdog's raw `Plan:` numbers; `contains`/`not_contains` match the normalized output
  (`'+ add repository[name="{{ p }}-a"]'`, `'~ ...'`, `'- remove ...'`, `'! ...'` for forced updates) whatever the
  outcome, so a failing plan can assert its messages;
- the diff flags `repo_filter`, `update_secrets`, `update_webhooks`, `update_filter` (needs an update flag),
  `only_secrets`, `verbose` (plan and apply options of writing-scenarios.md);
- dummy secrets (`********`) are never compared nor updated (`<DUMMY>` in local-plan); values are never compared at
  all: `update_secrets: true` forces them (`!`);
- coercions (repository values ignored because of org settings): put the org setting in `fragments.settings`;
- one complete configuration of your own: `config: {file: files/<x>.jsonnet}` (the domain's `files/` directory; full
  control over ordering).

```yaml
- name: force-one-secret
  base_fragments:
    repositories: &vault
      - |
        orgs.newRepo('{{ p }}-vault') {
          secrets: [
            orgs.newRepoSecret('{{ P }}_A1') { value: 'e2e-dummy-{{ run }}' },
            orgs.newRepoSecret('{{ P }}_B1') { value: 'e2e-dummy-{{ run }}' },
          ],
        }
  fragments:
    repositories: *vault
  plan:
    expect: changes
    update_secrets: true
    update_filter: "{{ P }}_A*"
    contains: ['! repo_secret[name="{{ P }}_A1"']
    not_contains: ['! repo_secret[name="{{ P }}_B1"']
```

### 3.3 Configuration loading

otterdog's own configuration (otterdog.json/jsonnet, organizations, `.otterdog-defaults.json`, `base_url`, the template)
is varied per offline step with `workspace` (writing-scenarios.md, "Workspace variants"):

```yaml
- name: defaults-override
  fragments: {}
  workspace:
    format: jsonnet
    orgs: ["{{ org }}-2", {github_id: e2e-archived, archived: true}]
    defaults_override: {jsonnet: {config_dir: orgs-override}}
  validate: {ok: true}
  commands:
    list-projects: {contains: [e2e-offline-2], not_contains: [e2e-archived]}
```

What YAML cannot express goes into a Python offline test (`tests/offline/test_config_loading.py` in the outlines) with
the `offline_cli` / `vendored_cli` fixtures:

- `offline_cli.workspace.use_layout(WorkspaceLayout(...))`: `format`, `orgs`, `defaults_override`, `base_url`,
  `config_dir`, `vendor`, and `document` (a complete otterdog.json/jsonnet of your own, credentials entries included);
- `write_org_config(text, org=...)`, `write_base_config(text, suffix="-OTHER")` for other organizations or another
  `local-plan -s` side; `sut.template.vendor_template(template_src, workspace.org_dir_for(org), workspace.template)`
  for the template of an extra organization, with `hooks={"validate-org-settings.py": "<python>"}` (names of
  `sut.template.HOOK_FILES`) to vendor template hook scripts next to it (`tests/offline/test_config_template_hooks.py`);
- `offline_cli.invoke(*args, config_root=True)` for discovery (`OTTERDOG_CONFIG_ROOT` = the workspace root; every other
  command strips it), `env={...}` for credential variables or a `PATH` with stub provider binaries (keep the system
  `PATH` after them).

```python
from otterdog_e2e.otterdog.workspace import WorkspaceLayout


@pytest.mark.scenario("O-CONFIG-DISCOVERY")
def test_otterdog_jsonnet_wins(vendored_cli: OtterdogCli) -> None:
    """With OTTERDOG_CONFIG_ROOT and no -c, otterdog finds the workspace's otterdog.jsonnet."""
    vendored_cli.workspace.use_layout(WorkspaceLayout(format="jsonnet"))
    result = vendored_cli.invoke("list-projects", config_root=True).assert_ok("list-projects")
    assert vendored_cli.workspace.org in result.output
    missing = vendored_cli.invoke("validate", "--local")  # empty cwd, no -c: exit 2
    assert missing.exit_code == 2 and "No configuration file specified" in missing.output
```

### 3.4 CLI commands, flags and exit codes

- **Offline** (no GitHub): `offline_cli` (fresh `e2e-offline` workspace, dummy token, no network) and `vendored_cli`
  (the same with the SUT's template vendored). Every command has a method (`validate`, `local_plan`, `show`,
  `show_default`, `canonical_diff`, `list_projects`, ...) returning a `CliResult` (`exit_code`, `stdout`, `output`,
  `validation()`, `plan()`, `apply()`, `assert_ok()`); other flags and stdin go through
  `run(command, *args, org=True, input=None, local=False)`; `invoke(*args)` runs `otterdog <args>` exactly (`--help`,
  usage errors such as `open-pr` without `-a`, no `-c`); the diff commands take `DiffOptions`
  (`plan_with`, `apply_with`, `local_plan_with`).
- **Live** (`tests/cli`): the `otterdog` fixture (the SUT CLI on the session workspace), `make_cli(workspace)` or
  `e2e.cli(sut, workspace, name=..., identity="config_reader")` for another workspace or identity, `fresh_workspace`,
  `oracle`, `mutator`, `baseline`, `reset_cli`, `run_ctx`. The command methods of live CLIs add `-n` (never log in
  to the web UI) and no live command gets more than `-v`; `run()` passes your arguments as they are, so give `-n` to
  a command that would otherwise log in (`run("show-live", "-n")`). Whatever a live test creates is run-prefixed;
  the baseline teardown sweeps the run, but a test that changes org-level state is `org_level` and resets the
  baseline itself.
- Commands that prompt read `input=` (`run("import", input="y\n")`, `run("local-apply", ..., input=...)`).
- Exit codes: otterdog exits with the number of validation errors (KB-034) and `check-status` always exits 0
  (KB-011): assert the output too.

```python
@pytest.mark.scenario("O-HELP")
def test_open_pr_requires_an_author(offline_cli: OtterdogCli) -> None:
    """open-pr without -a is a click usage error (exit 2) naming the option."""
    result = offline_cli.invoke("open-pr", "-b", "x", "-t", "y")
    assert result.exit_code == 2 and "Missing option '-a'" in result.output
```

### 3.5 Live objects: create, change, converge, remove

The live CLI tier runs YAML scenarios of `scenarios/cli` (regressions included) with the SUT: each step plans
(`plan -n -r e2e-<run>-*`), applies (`apply -f -n`), checks the GitHub state with the independent oracle and plans
again until the run's objects converge; the cleanup is a guarded `apply -d` (or a baseline reset for `org_level`).

- **State checks** (writing-scenarios.md, "State checks"): `kind` + parameters + one form (`match`, `absent`, `equals`,
  `contains`, `unavailable`). Beyond the object kinds (`repo`, `team`, `bpr`, `repo_ruleset`, `environment`, ...): the
  Actions settings (`org_selected_actions`, `org_actions_selected_repositories`, `org_fork_pr_approval`,
  `repo_selected_actions`, `repo_fork_pr_approval`, the cache limits), security (`repo_security_and_analysis`,
  `repo_vulnerability_alerts`, `repo_automated_security_fixes`, `repo_private_vulnerability_reporting`,
  `repo_code_scanning_default_setup`, `security_managers`, `code_security_defaults`), access (`repo_teams`,
  `repo_collaborators`, `team_membership`, `org_members`), branches (`repo_branches`, `repo_branch`,
  `repo_default_branch`), workflows (`workflow`, `workflow_runs`) and deliveries (`org_webhook_delivery`,
  `repo_webhook_delivery` with request headers and payload). The `bpr` kind returns the actor allowances in
  otterdog's notation (`'@login'`, `'@org/team'`, `'app-slug'`) and `requiredStatusChecks` with their app.
- **Org settings** (`fragments.settings`, overlays touching `settings`) need `org_level: true`; never `plan`,
  `description` or `billing_email` live. The template coerces some repository values from org settings (signoff,
  workflow permissions, allowed actions): set the org setting in the same step.
- **Plan-gated features**: `requires: [<cap>]` skips without the capability, `min_plan: team|enterprise` skips below
  the plan, `expect_failure_without: [<cap>]` + `on_missing_capability` asserts how otterdog or GitHub refuses it.
  Capabilities: `otterdog_e2e.capabilities.Cap` ([capability-matrix.md](capability-matrix.md)); `actions_cache_limit`
  means "otterdog can manage the cache limit here" (KB-006: never on the documented API alone).
- **Identities** (`identities: [author, approver, outsider, config_reader]`) for logins in fragments
  (`{{ logins.author }}`), e.g. team members; a missing identity skips.
- **App-bound settings**: `{{ app_slug }}` (BPR status checks `'<slug>:<context>'`) and `{{ app_id }}` (ruleset
  status checks `'{{ app_id }}:<context>'`, Integration bypass actors).
- **Forced updates and filters**: `apply: {update_secrets: true, update_filter: ...}`; converge never re-applies forced
  updates (use `converge: false` after an `only_secrets` apply).
- **Removals**: a step without the object plans its removal; `apply: {delete: true}` applies it (guarded: only this
  run's objects).
- **Drift and checks YAML cannot express** run as *probes* between two steps (`tests/cli/conftest.py` `PROBES`, a
  `ProbeEnv` with the oracle, the admin `Mutator`, the run context and the variables). The Mutator offers drift and
  probe writes on run objects only: `patch_repo`, `set_repo_topics`, `add_repo_collaborator` /
  `remove_repo_collaborator`, `create_team` / `patch_team` / `add_team_member` / `remove_team_member`,
  `dispatch_workflow` / `cancel_workflow_run` / `rerun_workflow_run`, `create_security_advisory` /
  `create_advisory_fork` / `close_security_advisory`, `create_code_security_configuration` /
  `set_code_security_default` / `delete_code_security_configuration`, `commit_files`, `create_ref`. A probe scenario
  declares a `timeout` covering the probe.
- A step's own `known_bug` keeps the other steps strict; an expected failure before a probe ends the item as XFAIL
  (the probe does not run): place known-bug steps after the probe.

```yaml
# scenarios/cli/workflows/org-workflow-permissions.yaml
id: cli.org.workflow-permissions
title: Organization and repository default workflow permissions
description: >-
  The organization's default workflow permissions and the approval flag are applied and converge; a repository
  value is managed while the organization allows it.
priority: P0
org_level: true
tags: [workflows, org-settings]
steps:
  - name: write
    fragments:
      settings:
        - "workflows+: { default_workflow_permissions: 'write', actions_can_approve_pull_request_reviews: false }"
      repositories:
        - "orgs.newRepo('{{ p }}-wf') { workflows+: { default_workflow_permissions: 'write' } }"
    state:
      - {kind: org_workflow_permissions, match: {default_workflow_permissions: write, can_approve_pull_request_reviews: false}}
      - {kind: repo_workflow_permissions, name: "{{ p }}-wf", match: {default_workflow_permissions: write}}
```

### 3.6 Enterprise-only features

`scenarios/enterprise/` (ids `enterprise.*`, `min_plan: enterprise`), run on a GitHub Enterprise Cloud target only
(`tests/enterprise`); private-repository variants of team/enterprise features use `min_plan` or
`expect_failure_without` in `scenarios/cli` instead. Enterprise-level objects visible in the org (rulesets, custom
properties) are foreign objects for the guards: see [setup-enterprise-org.md](setup-enterprise-org.md).

### 3.7 Managed webhooks and deliveries

otterdog-managed hooks point to `{{ hook_base }}<slug>` (`https://otterdog-e2e.invalid/<run>/`, never resolves; GitHub
still records the attempts). In YAML: kinds `org_webhook` / `repo_webhook` (the hook), `*_webhook_deliveries` (the
list, `contains: [{event: ping}]`), `org_webhook_delivery` / `repo_webhook_delivery` `{url, event}` (the newest
delivery in full, e.g. `match: {request: {headers: {X-Hub-Signature-256: {$regex: '^sha256='}}}}`), always with a
`timeout` (delivery logs lag minutes). Webhook secrets are `'e2e-dummy-{{ run }}'`; `update_webhooks: true` forces
them. The App delivery path (GitHub -> delivery log -> relay -> webapp) and org-hook lifecycles are Python tests of
`tests/webhooks` (`webhook_helpers`, `org_level_reset`, `relay`, `app_auth`; `relay.wait_event(event,
repository_name=..., run_id=..., after=...)`, `relay.replay(delivery_id)` for a redelivery).

### 3.8 The webhook receiver contract (offline)

`tests/offline/test_webapp_contract.py` runs the SUT's webapp image with dummy credentials (`offline_stack`, no
GitHub) and posts deliveries with the `injector` (`WebhookInjector`):

- `send(event, payload, content_type=..., signature="valid"|"sha1-only"|"sha256-only"|"invalid"|"missing")`;
  `content_type=FORM_CONTENT_TYPE` form-encodes (`payload=<json>`), `None` omits Content-Type, `event=None` omits
  X-GitHub-Event;
- `deliver(event, payload=None, body=b"null", omit_headers=("User-Agent",), headers={...})`: raw bytes (still signed
  over exactly these bytes), header omission (the HTTP client's own headers included), overrides after signing;
- `sent`, `last(event)`, `replay(delivery_id)` (the same bytes and headers again: a GitHub redelivery);
- payload builders of `otterdog_e2e.webhooks.payloads`: `ping_payload`, `pull_request_payload`,
  `issue_comment_payload`, `push_payload`, `pull_request_review_payload`, `installation_payload`,
  `workflow_job_payload`, `workflow_run_payload`, `unknown_event_payload`, `synthetic_*` (the review, installation and
  workflow builders were checked against otterdog's pydantic models in the SUT image).

Expected answers (main 9bdeb75): 204 accepted, 400 `Missing header: X-Github-Event` / `Missing header: content-type`
/ `Request body must contain data` / `Failed to decode JSON` / `Invalid signature`, 415 other content types, 500 a
form body without `payload` (KB-060, expected 400). Never write a 500 body to the artifacts (DEBUG pages may show locals).

### 3.9 Webapp events, commands, PR validation and auto-merge

`tests/webapp` tests run the SUT's webapp in docker compose with the real e2e GitHub App; App deliveries reach it
through the relay. Write them with the `webapp_scenario` fixture (`tests/webapp/conftest.py`, `WebappScenario`): it
isolates the test (`webapp_case`: config repo main reset to the baseline and the webapp quiet before; PRs closed,
branches deleted, main and run objects restored after), builds config texts (`text(repos=..., overrides=...)`,
`harmless_text()`, `syntax_error_text()`, `declare_live(repos)`) and waits with classified errors (`wait_validation`,
`wait_sync`, `wait_settled`, `wait_comment`, `wait_applied`, `wait_merged`, `wait_minimized`, `wait_api_pull`,
`wait_task`, `reaction`): a delivery that never arrives is `(infra)`, a webapp that does not react is `(SUT)`.

`s.flow` is the `ConfigRepoFlow` of the run's config repository. Every config text passes the guard (a trusted
`local-plan`) before it is pushed, approved, merged or commented with `/otterdog merge|apply`:

| Event or command | Flow call |
|---|---|
| opened / synchronize | `open_pr(slug=..., config_texts=..., draft=False)`, `open_pr_files(files={...})` (several files, non-config files), `push_commit(pr, text)`, `push_files(pr, files)` |
| ready_for_review / converted_to_draft / reopened / closed | `open_pr(..., draft=True)`, `mark_ready(pr)`, `convert_to_draft(pr)`, `reopen(pr)`, `close(pr)` |
| issue_comment created / edited / deleted | `comment(pr, "/otterdog <cmd>", identity=...)`, `edit_comment(pr, comment, body)` (the webapp re-runs an edited command), `delete_comment(pr, comment)` |
| pull_request_review submitted / dismissed | `approve(pr, identity="approver")`, `request_changes(pr)`, `dismiss_review(pr, review)` |
| merge (merge, squash, rebase) | `merge(pr, method="merge")`, `wait_merged(pr)` |
| PRs the harness did not open (open-pr, blueprint remediation) | `adopt_pr(number)` (its head must be a run branch) |

Identities: the `author`, `approver`, `outsider` identities (`identity="..."` arguments, or the `approver_mutator`,
`outsider_mutator`, `contributor_mutator` fixtures) need the `identities(...)` marker listing exactly the non-admin
identities the test acts as. Synthetic events (an installation the webapp does not know, a review from a
FIRST_TIMER) go through the `injector` instead of GitHub. The webapp's records: `webapp_api.tasks(...)`,
`wait_task(...)`, `pull_request(org, repo, number)`, `open_pull_requests()`, `merged_pull_requests()`.

Static rules of the tier (`tests/unit/test_suite_webapp_static.py`): exactly one `scenario("W-...", priority=...)`
marker, `tags(...)` from the vocabulary, `webapp` on every test, `docker` only for docker-only fixtures, `org_level`
with an org-level cleanup, no `time.sleep`, no direct `waiting.poll` in test modules (use `s.reaction`), xfail marks
with `raises=`, the conftest imported under `TYPE_CHECKING` only.

```python
"""W-PR-DRAFT: a draft config PR is validated once it is marked ready for review."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from conftest import WebappScenario

pytestmark = [pytest.mark.webapp]


@pytest.mark.scenario("W-PR-DRAFT", priority="P1")
@pytest.mark.tags("webapp", "repo")
def test_draft_pr_is_validated_when_ready(webapp_scenario: WebappScenario) -> None:
    """A draft PR is ignored until it is marked ready; then it gets the help comment and a validation."""
    s = webapp_scenario
    pr = s.flow.open_pr(slug=s.slug, config_texts=s.harmless_text(), title=f"e2e {s.sid}", draft=True)
    s.flow.mark_ready(pr)
    s.wait_validation(pr, state="success")
    s.wait_comment(pr, marker="help")
```

### 3.10 Blueprints and policies

The `blueprints` fixture gives a `BlueprintHelper` bound to the test's webapp case (definitions, statuses,
remediation PRs, workflows), cleaned up after the test (runs cancelled, remediation PRs closed, definitions removed,
the webapp reloaded); stale definitions of finished runs are removed first.

- Definitions: `BlueprintDefinition.required_file(id, files=[RequiredFile(path, content, strict)], name_pattern=...)`,
  `.pin_workflow(...)`, `.append_configuration(condition=..., content=...)`, `.scorecard_integration(...)`;
  `PolicyDefinition.macos_large_runners(allowed=...)`, `.dependency_track_upload(artifact_name, workflow_filter)`;
  `add_blueprint(definition, scope="org"|"global")`, `add_policy(...)`, `add_definition_text(kind, slug, text)` for
  malformed files. Ids are `blueprints.blueprint_id(slug)` (`e2e-<run>-<slug>`); the webapp keeps one GLOBAL definition
  per type, so prefer org definitions.
- Triggers and reads: `reload()` (/internal/init and the fetch tasks), `check(limit)` (/internal/check),
  `wait_evaluation(definition, repo, after=...)`, `statuses(id)`, `wait_status(id, repo, "success"|...)`,
  `remediations()`, `dismissed()`, `policy_status(type)`, `wait_policy_counter(type, counter, at_least=n)`.
- Remediation PRs: `wait_remediation_pr(repo, definition)`, `close_remediation_pr` (dismissal), `reopen_remediation_pr`
  (recreates the deleted branch first), `merge_remediation_pr` (config-repository PRs through the guarded flow).
- Workflows (run repositories only): `add_workflow(repo, slug, content)`, `add_large_runner_workflow(repo)`,
  `add_sbom_workflows(repo, artifact_name=...)`, `dispatch(repo, workflow)`, `wait_run(...)`, `cancel_run(...)`,
  `wait_workflow_delivery("workflow_job"|"workflow_run", repo=..., run_id=...)`. A job on a macOS larger runner is
  refused where a runner could pick it up and bill it (`allow_billing=True` accepts it).
- Dependency-Track: the `dtrack_mock` fixture (compose profile `dtrack`, `DEPENDENCY_TRACK_URL` points at it):
  `uploads()`, `wait_uploads(...)`, `set_response(status)`.

Needs of these outlines: the App permissions and events listed in the gap outline (contents and workflows write,
`Workflow job` / `Workflow run` events) must be granted to the e2e App ([github-app.md](github-app.md)).

### 3.11 Webapp runtime: boot, environment, API and pages

- `webapp_stack` (compose transport only; other transports skip): `stop_service("mongodb"|"redis"|"webapp")`,
  `start_service(...)` (in-memory stores start empty: call `init()` and `wait_ready()` after), `running_services()`,
  `logs()`;
- `webapp_env({...})`: recreate the webapp with environment overrides (`GITHUB_ADMIN_TEAMS`,
  `GITHUB_APPROVAL_TEAMS`, `GITHUB_WEBHOOK_ENDPOINT`, contexts, `BLUEPRINT_CHECK_INTERVAL`, `DEBUG`, ...: secrets and
  stores are never overridable), restored after the test;
- `webapp_otterdog_json({"admin_teams": [...], "approval_teams": None})`: otterdog.json with org-entry overrides, then a
  reload, restored after;
- `webapp_api` (`WebappApi`): `/api` (`organizations`, `organization`, `project`, `tasks`, `wait_task`,
  `open_pull_requests`, `merged_pull_requests`, `blueprint_remediations`, `dismissed_blueprints`, `scorecard_results`,
  `graphql`, `statistics_progress`), `/internal` (`init`, `check`, `health`), and the pages the API does not expose
  (`installations()` of /admin/organizations, `policy_status()` of /admin/policies, `blueprint_statuses(project, id)`
  of /projects/&lt;project&gt;, `deployed_version()`);
- offline boot and route checks with dummy credentials belong to `tests/offline/test_webapp_contract.py` (no App).

### 3.12 Web UI

Web-only organization settings and the UI-driven commands are tested in Python only, in `tests/web_ui` (YAML scenarios
always run otterdog with `-n`): every item gets the `web_ui` marker and is gated before any fixture (admin web
credentials, `--e2e-allow-web-ui`, a trusted SUT, no SAML SSO, logins not blocked). Scenario ids start with
`webui.` (the CI lane `e2e-webui.yml` selects `--scenario 'webui.*' tests/web_ui`). Use the `web_tier` fixture
(`WebUiTier`: the web-mode SUT `sut`, the trusted reader `reader`, `rest()`, `record()`, `restored()`, `round_trip()`,
`web_cli(name)`, `installed_slugs()`, `write_evidence()`).

The **login budget** is the constraint: every command that logs in costs one bot login (`apply` costs two), logins are
serialized machine-wide and at least 32 s apart (`E2E_WEB_LOGIN_SPACING`), and a blocking failure stops every further
login for hours. Today's tier spends about a dozen logins (15 to 25 minutes):

| Item | Logins |
|---|---|
| settings round trip | 8 (+3 for the trusted fallback restore) |
| import | 1 |
| review-permissions | 1 |
| list-advisories -w | 0-1 |
| install-app / uninstall-app | 0 today (KB-002), 2 once fixed |
| web-login (local) | 1 |

Rules: add web settings to the existing round trip instead of new scenarios; never retry a login in a loop; treat
`WebLoginBlockedError` as final; before changing a web-only setting record the original values (`web_tier.record`)
and pin every writable web key (`webui.mapping.jsonnet_fields`, `key:::`); never run a web-mode plan or apply with the
plain baseline; never toggle `two_factor_requirement` (KB-041); use the REST oracle (`webui.oracle.rest_web_values`)
for the 7 readable keys and the trusted reader (never the SUT under test) for the others. The webapp side of web-only
settings (no login) belongs to `tests/webapp/test_web_ui_flags.py`. Details: [web-ui-testing.md](web-ui-testing.md).

### 3.13 Regressions, unmerged changes and differential runs

- A regression of an otterdog fix is a live scenario of `scenarios/cli/<domain>/`, next to the scenarios of the
  feature it guards, named after the behaviour (`regression.<behaviour>`, never the PR number), with the tag
  `regression`, `references: [{pr: <n>}]` for the
  fixing PR(s), the PR or issue link and the known-bad version in the description and `fixed_in` for fixes not
  released yet; or, offline, an offline scenario with `observe: true`.
- A pending change (an otterdog PR, a maintainer branch) is a `references` entry (`pr: <n>` or `change: <slug>`, with
  its expected differential deltas, base and template) of the scenarios of the functionality it changes, never a
  PR-named scenario or directory; it is tested with `otterdog-e2e pr <n> --sha <sha>` or
  `run --sut dirty:<checkout> --change <slug>` ([testing-an-otterdog-pr.md](testing-an-otterdog-pr.md)).
- `observe: true` offline scenarios are recorded on both SUT sides of a differential run; live scenarios with
  `observe: true` are observed with `validate` and `plan` only.

## 4. Quick reference

### YAML keys added for the battery

| Key | Where | Use |
|---|---|---|
| `validate.verbose`, `infos`, `infos_min` | validate | Info messages (`-v`) |
| `validate.exit_code`, `plan.exit_code` | validate, plan | exit status (`null`: not checked) |
| `repo_filter`, `update_secrets`, `update_webhooks`, `update_filter`, `only_secrets`, `verbose` | plan, apply | otterdog's diff flags (offline: local-plan) |
| `known_bug` | step | expected failures of one step |
| `workspace` | offline step | otterdog.json/jsonnet, organizations, defaults override, base_url, config_dir, vendor |
| `commands.show` | offline step | expectations of the show phase |
| `fragments.settings` with profile keys | offline step | description, name, billing_email, ... |
| `libraries`, `overlay`, `config`, `base_config`, `{file, raw, vars}` entries | scenario, step | jsonnet from files |
| `{{ app_id }}` | any string | the e2e App id |

### Fixtures

| Tier | Fixtures |
|---|---|
| every tier | `harness`, `run_ctx`, `e2e`, `sut`, `scenario_vars`, `fresh_workspace` |
| offline | `offline_context`, `template_src`, `sut_history`, `offline_cli`, `vendored_cli`, `offline_engine` |
| live | `target`, `identities`, `verified_org`, `oracle`, `mutator`, `mutators`, `capabilities`, `reset_sut`, `template_ref`, `renderer`, `workspace`, `otterdog`, `reset_cli`, `baseline`, `scenario_engine`; cli tier: `run_scenario`, `make_cli` |
| webapp | `webapp`, `webapp_api`, `relay`, `config_flow`, `injector`, `app_auth`, `installation_id`, `webapp_image`, `webapp_case`, `webapp_scenario`, `webapp_stack`, `webapp_env`, `webapp_otterdog_json`, `dtrack_mock`, `blueprints`, `outsider_mutator`, `approver_mutator`, `contributor_mutator` |
| webhooks | `webhook_helpers`, `org_level_reset` (+ the webapp ones) |
| web_ui | `web_sut`, `web_reader`, `web_tier` |
| differential | `base_sut`, `base_template_ref`, `change_spec`, `sut_pair` |

### Python APIs

| Need | API |
|---|---|
| run otterdog | `OtterdogCli`: command methods, `run`, `invoke`, `plan_with` / `apply_with` / `local_plan_with` (`DiffOptions`) |
| otterdog's configuration | `ConfigWorkspace.use_layout(WorkspaceLayout(...))`, `write_org_config`, `write_base_config`, `org_dir_for` |
| GitHub truth | `Oracle` (every check kind is an Oracle method; `find_workflow_runs`, `workflow_run_jobs`, delivery details) |
| GitHub writes | `Mutator` (run objects and run-branch PRs only; section 3.5) |
| config PR workflow | `ConfigRepoFlow` (section 3.9) |
| webhook payloads | `WebhookInjector`, `otterdog_e2e.webhooks.payloads`, `DeliveryRelay.wait_event` / `replay` |
| the webapp | `WebappStack`, `WebappApi`, `DtrackMock`, `BlueprintHelper` |
| fakes for unit tests | `otterdog_e2e.testing.fakes`: `FakeOracle`, `RecordingMutator` (with the Mutator's guards), `FakeCli`, `FakeWorkspace`, `FakeGitHubHttp`, `FakeAppAuth`, `FakeLease` |

## 5. The offline scenario lint

`tests/offline/test_scenario_lint.py` validates every step of every live scenario (`scenarios/cli`,
`scenarios/enterprise`) offline with the SUT: the step is rendered for the offline
organization (marker description; plan `variables.plan`, else `min_plan`) and checked with `validate --local`. A step
whose `validate.ok` is false or whose `plan.expect` is `validation_error` must produce errors, every other step must
validate (warnings are fine, "ignoring unknown properties" is not). Steps using teams or
`code_scanning_default_languages` are skipped (their validation calls GitHub), so are scenarios whose `fixed_in` the
SUT predates; a mismatch in a step whose own `known_bug` the SUT has, or in a scenario of such a bug, is an expected
failure.

**Rule: a live scenario is submitted only once it passes the lint** (`make lint-scenarios`, i.e.
`otterdog-e2e run --suite offline -k lint`, with `SUT=branch:main` too for scenarios of unreleased fixes). The lint
runs in every `make offline` and in CI, so a broken scenario fails the offline tier of everybody, before any live
run. `make inject ARGS='--fragment repositories=<file> --print'` (`otterdog-e2e inject`) tries jsonnet before it
becomes a scenario.

## 6. Unit tests of the harness

A new harness capability (a check kind, a Mutator call, a fixture) is unit-tested with the fakes (no network): the
fakes mirror the real interfaces (`tests/unit/test_testing_fakes.py` checks every public method), `responses` mocks
`api.github.com` for the real clients; check every REST endpoint, field, status and media type against GitHub's
OpenAPI description and every GraphQL document against its schema before relying on it. A battery test itself is
never a unit test: `covered_by` may not name `tests/unit`.

## 7. Updating the coverage matrix

After the test runs green (live tests on a target), edit the feature in `scenarios/coverage.yaml`:

1. `covered_by`: add the YAML scenario id or the pytest node id (`tests/<tier>/<file>.py::<test>`); the matrix test
   checks that it exists;
2. `status`: `covered` when every operation of the feature is exercised with assertions, else `partial`; a covered
   feature needs at least one covering item that runs strictly on the default SUT: an item that is only a known-bug
   xfail (a scenario-level bug, a Python `known_bug` test without its own `xfail(raises=...)`) or a scenario skipped on
   `release:latest` by `fixed_in` leaves the feature `partial` (the matrix test refuses it);
3. `gap_outline`: remove it for `covered`, shrink it to what is still missing for `partial`;
4. `known_bugs`: the bugs the test hit (new ones registered first);
5. `verified_on`: append the green live run that exercised the covering items,
   `{target: free, sut: release:latest, run: <run id>, date: YYYY-MM-DD}` (run.json of the artifacts); until then the
   matrix renders the feature as **unverified** (implemented, never run), whatever its status;
6. regenerate and check:

```bash
.venv/bin/python tests/unit/test_coverage_matrix.py --write   # rewrites docs/coverage-matrix.md, prints the shares
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/test_coverage_matrix.py
```

The matrix test also fails when a referenced test is renamed: keep `covered_by` in sync. Every run's `summary.md`
reports the matrix shares and the features whose covering items ran.

## 8. Safety reminders

- Never touch an object without the run prefix; the guards refuse deletions of foreign objects, writes to non-e2e
  objects and pull request edits outside run branches, and every `apply -d` is checked by a plan first.
- Org-level changes (`settings`, org Actions, code security defaults) are `org_level` (full baseline reset as cleanup).
  Code security defaults: otterdog's apply sets every default configuration to `none`, foreign ones included: skip the
  scenario when `code_security_defaults` lists a non-e2e configuration before the run.
- Security advisories cannot be deleted through the API: summaries start with the run prefix and the run repository's
  deletion removes them; the janitor sweeps leftover e2e code security configurations and run repositories (temporary
  advisory forks included).
- `pass:<path>` secrets cannot be applied live (the harness provides no `pass`); use `e2e-dummy-{{ run }}` values for
  live applies.
- No live command gets more than `-v`; no real credential ever appears in a scenario, a fixture file or an artifact.

## 9. Submission checklist

- [ ] id, file, tags and priority follow section 2; the scenario says why it exists (`description`);
- [ ] names use `{{ p }}`, `{{ P }}`, `{{ hook_base }}` (or `run_ctx`); secrets are dummies or references;
- [ ] org-level changes are `org_level`; capabilities, plans and identities are declared;
- [ ] known bugs are linked at the right level (step for one step, scenario for the whole item) and registered;
- [ ] offline scenario: `make one SCENARIO=<id>` green on `release:latest` (and `branch:main` when relevant);
- [ ] live scenario: `make lint-scenarios` green, then `make one SCENARIO=<id> TARGET=free` green;
- [ ] Python test: the tier's static checks green (`make unit`), the test green on a target;
- [ ] `scenarios/coverage.yaml` updated, `docs/coverage-matrix.md` regenerated, `make check` and `make offline` green.
