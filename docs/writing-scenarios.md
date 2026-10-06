# Writing scenarios

Most tests are YAML **scenarios**: a sequence of declarative steps, each describing the organization configuration
the step wants (as jsonnet fragments added to the baseline) and what otterdog and GitHub must do with it. The
harness renders the configuration, runs otterdog, checks the output and the real GitHub state, and always cleans up.
Python tests (webapp, webhooks, special cases) use the same fixtures and markers.

## Where scenarios live

| Directory | Tier | Collected by | Runs |
|---|---|---|---|
| `scenarios/offline/` | `offline` | `tests/offline/` | without GitHub: `validate --local`, `local-plan --local`, `show --local`, extra commands |
| `scenarios/cli/` | `cli` | `tests/cli/` | live, on the target org: `validate`, `plan -n`, `apply -f -n`, oracle checks |
| `scenarios/regressions/` | `cli` | `tests/cli/` | live regressions of specific otterdog issues |
| `scenarios/enterprise/` | `enterprise` | `tests/enterprise/` | live, enterprise-only features |

One scenario per `*.yaml` file. The `tier` may be omitted: it is inferred from the directory right below
`scenarios/`, whose subdirectories only group files by topic (`scenarios/offline/cli/output/show.yaml` belongs to
`offline`, not to the inner `cli/`), and a declared tier must match that directory. `scenarios/otterdog-prs/` (PR
manifests) and `scenarios/known_bugs.yaml` are not scenarios. Keep scenario ids unique everywhere (the loader refuses
duplicates among the directories a tier collects, e.g. `cli/` and `regressions/`). Each scenario becomes one pytest
item, for example `tests/cli/test_scenarios.py::<test>[cli.repo.lifecycle]`. The differential tier records the
offline scenarios marked `observe: true` on the base and on the head SUT.

## A first scenario

```yaml
# scenarios/cli/example-repo-lifecycle.yaml
id: cli.example.repo-lifecycle
title: Repository create, update and delete
priority: P0
tags: [repo, smoke]
steps:
  - name: create
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-basic') {
            description: 'e2e basic',
            has_wiki: false,
          }
    plan: {expect: changes, counts: {add: 1}}
    state:
      - {kind: repo, name: "{{ p }}-basic", match: {description: e2e basic, has_wiki: false}}
  - name: update
    fragments:
      repositories:
        - "orgs.newRepo('{{ p }}-basic') { description: 'e2e updated', has_wiki: false }"
    plan: {expect: changes}
    state:
      - {kind: repo, name: "{{ p }}-basic", match: {description: e2e updated}}
  - name: delete
    plan: {expect: changes, counts: {delete: 1}}
    apply: {delete: true}
    state:
      - {kind: repo, name: "{{ p }}-basic", absent: true}
```

For every step the engine renders the baseline plus the step's fragments, runs `plan -n -r e2e-<run>-*`, applies
(`apply -f -n`) because the plan expects changes, checks the repository through the GitHub API, then plans again
until otterdog sees nothing left to do for this run's objects. Run it with:

```bash
make one TARGET=free SCENARIO=cli.example.repo-lifecycle
```

## Scenario fields

| Key | Type | Default | Meaning |
|---|---|---|---|
| `id` | string, required | | unique id, `^[A-Za-z0-9][A-Za-z0-9_.-]*$` (dotted by convention: `cli.repo.lifecycle`) |
| `title` | string, required | | one line |
| `description` | string | `""` | free text |
| `tier` | `offline` \| `cli` \| `enterprise` | from the directory | |
| `priority` | `P0` \| `P1` \| `P2` | `P1` | P0 items count for the lane budgets |
| `min_plan` | `free` \| `team` \| `enterprise` | `free` | skipped on lower plans (adds `plan(...)` marks); offline scenarios use `variables.plan` instead |
| `requires` | list of capabilities | `[]` | missing capability: the scenario is skipped |
| `expect_failure_without` | list of capabilities | `[]` | missing capability: the steps run with their `on_missing_capability` overrides (negative test) |
| `identities` | list of roles | `[]` | `author`, `approver`, `outsider`, `config_reader`, `oracle`, `admin`; missing ones skip the scenario ([roles.md](roles.md)) |
| `tags` | list | `[]` | selection tags, `^[a-z0-9][a-z0-9_.-]*$` (vocabulary below) |
| `known_bug` | `KB-<nnn>` | `null` | id from `scenarios/known_bugs.yaml`: every step inherits it (expected failures; the first one ends the run as XFAIL; infra, harness and cleanup failures stay failures; a run without the bug is an XPASS) |
| `org_level` | bool | `false` | the scenario changes org-level state: full baseline reset as cleanup, plans not filtered by `-r` |
| `observe` | bool | `false` | record the outputs for differential runs |
| `variables` | mapping | `{}` | extra Jinja variables; `plan` overrides the plan rendered into the settings |
| `libraries` | mapping | `{}` | jsonnet libraries inlined into every rendered configuration of the scenario: `<name>: <path>` or `<name>: {file, raw, vars}` ([Injecting jsonnet from files](#injecting-jsonnet-from-files)) |
| `fixed_in` | PEP 440 version | `null` | first otterdog version with the fix or feature the scenario asserts (e.g. `"1.7.0.dev15"`): older SUTs skip it (live and offline tiers; differential runs record it on both sides) |
| `timeout` | positive int | tier timeout | pytest timeout of the item in seconds; default: the tier timeout (cli/enterprise 600, offline 300), plus 600 for `org_level` live scenarios |
| `steps` | list, required | | at least one step |
| `cleanup` | `auto` \| `none` | `auto` | `none` keeps the objects (debugging only) |

Capabilities are the values of `otterdog_e2e.capabilities.Cap` (see [capability-matrix.md](capability-matrix.md)):
`public_repos`, `private_repo_branch_protection`, `private_repo_rulesets`, `private_repo_environments`,
`private_repo_env_protection_rules`, `private_pages`, `org_rulesets`, `otterdog_org_rulesets`, `push_rulesets`,
`ruleset_evaluate`, `custom_org_roles`, `custom_properties`, `internal_repos`, `org_secrets_private_repos`,
`secret_scanning_public`, `ghas_private`, `larger_runners`, `merge_queue_private`, `actions_cache_limit`, `app`,
`docker`, `identity_author`, `identity_approver`, `identity_outsider`, `identity_config_reader`, `separate_oracle`.

Tag vocabulary (also used by the PR tag selection, `otterdog_e2e.selection`): `repo`, `bpr`, `rulesets`,
`environments`, `secrets`, `variables`, `webhooks`, `teams`, `custom-properties`, `org-settings`, `workflows`,
`org-roles`, `template`, `cli`, `webapp`, `webhooks-app`, `offline`, `smoke` (always selected).

## Step fields

| Key | Default | Meaning |
|---|---|---|
| `name` | `step-<n>` | unique within the scenario, `^[A-Za-z0-9][A-Za-z0-9_.-]*$` |
| `known_bug` | `null` | `KB-<nnn>`: the failures of THIS step are expected while the bug affects the SUT, the other steps stay strict; `{id: KB-<nnn>, phases: [converge]}` limits it to some phases (`validate`, `plan`, `apply`, `state`, `converge`; offline `local-plan`, `show`, `commands`) ([Known bugs](#known-bugs)) |
| `fragments` | `{}` | jsonnet added to the baseline for this step (below); an entry is an inline string or a file |
| `overlay` | `null` | object mixin(s) applied after both layers: an inline string, `{file, raw, vars}` or a list of them |
| `base_fragments` | `null` | offline only: fragments of the `-BASE` configuration; `local-plan` runs only when they are given (`{}` = the bare organization) |
| `config` | `null` | offline only: `{file, raw, vars}`, a complete organization configuration written instead of the rendered one |
| `base_config` | `null` | offline only: `{file, raw, vars}`, a complete `-BASE` configuration (instead of `base_fragments`; `local-plan` runs) |
| `workspace` | `null` | offline only: otterdog's own configuration for this step (otterdog.jsonnet, more organizations, `.otterdog-defaults.json`, `base_url`, `config_dir`, no vendored template), see [Workspace variants](#workspace-variants-offline) |
| `validate` | `null` | expectations of `validate`; live: `validate` runs only when given; offline: always runs, checked only when given |
| `plan` | `{expect: changes}` | expectations and flags of `plan` (live) or `local-plan` (offline: only with a BASE configuration); `null` skips plan, apply and converge |
| `apply` | `{expect: ok}` | live only; runs only when `plan.expect` is `changes`; `null` skips it |
| `state` | `[]` | live only: oracle checks after the apply |
| `converge` | `true` | live: after a successful apply, plan again until this run's objects are a no-op |
| `on_missing_capability` | `{}` | replacements of `validate`, `plan`, `apply` (merged over the step's), `state`, `converge` used when an `expect_failure_without` capability is missing |
| `commands` | `{}` | offline only: extra commands `show-default`, `canonical-diff`, `list-projects`, `--version`, each `{exit_code: 0, contains: [], not_contains: []}` (`exit_code: null` = any); `show` gives the expectations of the show phase instead (show runs once per step anyway) |

| Expectation | Keys |
|---|---|
| `validate` | `ok` (default: `errors == 0`, so `true` without `errors`), `errors`, `warnings_min`, `infos`, `infos_min` (both need `verbose`), `exit_code` (`null`: not checked), `verbose` (`validate -v`), `contains`, `not_contains` |
| `plan` | `expect`: `changes` \| `noop` \| `validation_error` \| `error` \| `any`; `contains`, `not_contains` (checked whatever the outcome); `counts`: `{add, change, delete}`; `exit_code`; flags `repo_filter`, `update_secrets`, `update_webhooks`, `update_filter`, `only_secrets`, `verbose` ([Plan and apply options](#plan-and-apply-options)) |
| `apply` | `expect`: `ok` \| `error` \| `validation_error` \| `any`; `delete` (`-d`); flags `repo_filter`, `update_secrets`, `update_webhooks`, `update_filter`, `only_secrets`, `verbose`; `contains`, `not_contains` |

## Steps are declarative

The configuration of step *k* is **the baseline plus the fragments of step *k*** only: an object of step 1 that is
not repeated in step 2 is removed in step 2. Repeat objects to keep them (YAML anchors help):

```yaml
steps:
  - name: create
    fragments:
      repositories: &repo
        - "orgs.newRepo('{{ p }}-keep') { description: 'kept' }"
  - name: add-variable
    fragments:
      repositories: *repo
      variables:
        - "orgs.newOrgVariable('{{ P }}_MODE') { value: 'on' }"
```

A removal is planned but only applied by a step with `apply: {delete: true}`; otherwise converge reports it as
pending. Phases per step: render and write, `validate` (if given), `plan`, `apply`, `state`, `converge`. The first
failing phase stops the scenario, the cleanup always runs, and every failure is reported with the tail of the
command output.

## Fragments

| Key | Inserted as | Example |
|---|---|---|
| `settings` | fields of the org `settings` object | `"web_commit_signoff_required: true"` |
| `custom_properties` | expressions in `settings.custom_properties` | `"orgs.newCustomProperty('{{ p }}-tier') { value_type: 'string' }"` |
| `teams` | expressions in `teams` | `"orgs.newTeam('{{ p }}-devs') { members: ['{{ logins.author }}'] }"` |
| `secrets` | expressions in the org `secrets` | `"orgs.newOrgSecret('{{ P }}_TOKEN') { value: '********' }"` |
| `variables` | expressions in the org `variables` | `"orgs.newOrgVariable('{{ P }}_MODE') { value: 'on' }"` |
| `webhooks` | expressions in the org `webhooks` | `"orgs.newOrgWebhook('{{ hook_base }}org') { events+: ['repository'] }"` |
| `rulesets` | expressions in the org `rulesets` | `"orgs.newOrgRuleset('{{ p }}-main') { include_repo_names: ['{{ p }}-*'] }"` |
| `roles` | expressions in the org `roles` | `"orgs.newOrgRole('{{ p }}-auditor') { base_role: 'read' }"` |
| `repositories` | expressions in `_repositories` | `"orgs.newRepo('{{ p }}-app') { description: 'x' }"` |
| `extra` | raw fields appended to the scenario layer of the org object (escape hatch; must not repeat a key of the other sections) | `"_e2e_marker:: true"` |

Each value is a string or a list of strings, inserted verbatim after the Jinja render; the renderer appends a comma
after each one, so a fragment must not end with a `//` or `#` comment. A list item (or the single value) may also be
a file reference `{file: <path>, raw: <bool>, vars: <mapping>}`, see
[Injecting jsonnet from files](#injecting-jsonnet-from-files). The functions are those of otterdog's
template (`orgs.newRepo`, `newTeam`, `newOrgSecret`, `newOrgVariable`, `newOrgWebhook`, `newOrgRuleset`,
`newOrgRole`, `newCustomProperty`, `newRepoSecret`, `newRepoVariable`, `newRepoWebhook`, `newBranchProtectionRule`,
`newRepoRuleset`, `newEnvironment`, `newEnvSecret`, `newEnvVariable`, `newPullRequest`, `newStatusChecks`,
`newMergeQueue`, `extendRepo`).

The baseline contains the live org profile, the baseline teams and repositories. When the target cannot manage the
Actions cache limit (capability `actions_cache_limit` missing), `max_cache_size_gb` is hidden in the template; a
scenario that manages it must write `max_cache_size_gb::: <n>` (`:::` makes a hidden field visible again).

## Naming: everything carries the run prefix

Cleanup, plan filtering, the janitor and the safety guards recognize a run's objects by their names. Name every
object with the template variables:

| Object | Name |
|---|---|
| repositories, teams, rulesets, environments, custom properties, roles | `{{ p }}-<slug>` (`e2e-<run>-<slug>`); custom property names use `-`, never `_` |
| secrets, variables | `{{ P }}_<SLUG>` (`E2E_<RUN>_<SLUG>`) |
| webhook URLs | `{{ hook_base }}<slug>` (`https://otterdog-e2e.invalid/<run>/<slug>`, never resolves) |

An object without the prefix is a foreign object: plan counts and `changes`/`noop` ignore it, and a guarded delete
refuses to remove it.

## Template variables

Every string of a step (fragments, `contains`, checks) is rendered once by Jinja2 with `StrictUndefined` (an unknown
variable is an error at load time):

| Variable | Live value | Offline value |
|---|---|---|
| `run` | the run id, e.g. `t3c7z8a5` | `spduo000` (fixed, so both differential sides render identical names) |
| `p` | `e2e-<run>` | `e2e-spduo000` |
| `P` | `E2E_<RUN>` (write `{{ P }}_NAME`) | `E2E_SPDUO000` |
| `hook_base` | `https://otterdog-e2e.invalid/<run>/` | same form |
| `org` | the target org login | `e2e-offline` |
| `plan` | the live plan, or `variables.plan` | `variables.plan`, default `free` |
| `logins.<role>` | declared login of an identity (list optional roles in `identities`) | not available |
| `app_slug` | the App slug (or `""`) | `e2e-offline-app` |
| `app_id` | the e2e App id as a string (or `""`): app-bound ruleset status checks `'{{ app_id }}:<context>'`, Integration bypass actors | `1` |
| `teams.admin`, `teams.approval`, `teams.contributors` | the target's team names | `otterdog-admins`, `project-leads`, `e2e-contributors` |

`variables` adds names (any identifier except the ones above; `plan` may be overridden). Use
`{% raw %}...{% endraw %}` for literal `{{` in jsonnet.

## Injecting jsonnet from files

Jsonnet that would make a long YAML string, that several steps or scenarios share, or that you prefer to keep in a
real file can come from files. The rendered configuration stays ONE self-contained file (the webapp evaluates exactly
one file), so file content is inlined, never imported.

| Where | YAML | Inserted as |
|---|---|---|
| a fragment entry (`fragments`, `base_fragments`) | `{file: <path>, raw: <bool>, vars: <mapping>}` instead of a string, in a list or as the single value of a key | the entry, exactly like an inline fragment |
| scenario `libraries` | `<name>: <path>` or `<name>: {file, raw, vars}` | `local <name> = (` newline, the file, newline, `);` right after the template import, in declaration order, in every rendered configuration of the scenario (the `-BASE` one included) |
| step `overlay` | an inline string, `{file, raw, vars}` or a list of them | `<org> + (` newline, the overlay, newline, `)` after both layers, in order |
| offline step `config` | `{file, raw, vars}` | the whole organization configuration of the step (nothing is rendered around it) |
| offline step `base_config` | `{file, raw, vars}` | the whole `-BASE` configuration (`local-plan` runs), instead of `base_fragments` |

```yaml
libraries:
  e2e: ../lib/e2e.libsonnet                     # a path: the short form of {file: ...}
steps:
  - name: create
    fragments:
      repositories:
        - "orgs.newRepo('{{ p }}-inline')"       # inline and file entries mix
        - file: ../fragments/environment-repo.jsonnet
          vars: {wait_timer: 5, branch_policies: [main, "release/*"]}
      variables: {file: ../fragments/org-variable.jsonnet}
    overlay: {file: ../fragments/overlay-run-topics.jsonnet}
```

**Paths** are relative to the directory of the scenario file and must resolve, symlinks followed, inside the project
(the directory holding otterdog-e2e's `pyproject.toml`; for a scenario outside any project, its own directory):
`../lib/e2e.libsonnet` from `scenarios/cli/` is fine, absolute paths and paths leaving the project are refused. Files are read once, when the scenario loads: UTF-8, not
empty, at most 512 KiB.

**Rendering.** A file is Jinja-rendered at run time like an inline string (StrictUndefined, every
[template variable](#template-variables) and the scenario's `variables`), plus:

- `vars`: extra variables of this file only (identifiers; they may shadow the scenario's `variables`, never an engine
  variable). Their string values, nested ones included, are rendered with the scenario variables first, so
  `vars: {name: "{{ p }}-a"}` works. Insert numbers as they are (`{{ wait_timer }}`), everything else with
  `tojson` (`{{ branch_policies | tojson }}`, `{{ flag | tojson }}`: JSON is valid jsonnet, while Jinja alone would
  print Python's `True` or `None`);
- `raw: true`: the file is inserted as it is, never rendered (no `vars`). A file without Jinja markup is never
  rendered anyway;
- `config` and `base_config` files also get `import_path` (the template import path, `vendor/<repo>/<file>`) and
  `project`; with `org` and `plan` they can declare the organization themselves:

```jsonnet
// scenarios/fragments/offline-config.jsonnet
local orgs = import '{{ import_path }}';

orgs.newOrg('{{ project }}', '{{ org }}') {
  settings+: { plan: '{{ plan }}', description: '[otterdog-e2e] offline organization' },
  _repositories+: [orgs.newRepo('{{ p }}-from-config')],
}
```

**Libraries** are jsonnet expressions, usually an object of hidden helper functions (`name(args):: ...`). Their
names are jsonnet identifiers other than `orgs`, `orgs0`, `std`, `self`, `super`, `$` and the jsonnet keywords. A
library sees the template local `orgs` (with the harness overrides, e.g. the hidden cache limit) and the libraries
declared before it. Editors report `orgs` as an unknown variable in a library file: the rendered configuration
defines it. `config`/`base_config` files get no libraries (they are complete).

**Overlays** are object mixins applied after both layers: they see and may rewrite everything, baseline objects
included (`super._repositories`, `super.settings`). Use them for what fragments cannot express (a change applied to
every repository of the run, a field of the organization object). An overlay must merge settings (`settings+:`, a plain
`settings:` would drop the live profile and the safety marker), must never set `plan`, `description` or
`billing_email`, and a live overlay touching `settings` needs `org_level: true` (the check is best effort: it inspects
the object literals of the overlay). Removals an overlay causes stay guarded like any other (`apply: {delete: true}`
removes only this run's objects).

```jsonnet
// scenarios/fragments/overlay-run-topics.jsonnet: one more topic on every repository of the run
{
  _repositories: [
    if std.startsWith(repo.name, '{{ p }}-') then repo { topics+: ['e2e-overlay'] } else repo
    for repo in super._repositories
  ],
}
```

**Content rules** (inline strings included): no `import`, `importstr` or `importbin` (the webapp evaluates one file,
and an import could read files of the workspace such as otterdog's HTTP cache, which holds request headers), except
the template import of a `config`/`base_config` file (`import '{{ import_path }}'`); [dummy secret
values](#secrets), checked again after the run-time render; the [offline restrictions](#offline-scenarios); the
settings rules above. A fragment entry must not end with a `//` or `#` comment (the renderer appends a comma),
libraries and overlays may (their closing parenthesis has its own line). Since names are computed by jsonnet in
library helpers, give the helpers names written with `{{ p }}`, `{{ P }}` and `{{ hook_base }}`: a unit test manifests
every live step and refuses objects without this run's prefix.

**Errors** name the place in the scenario and the file and line (lines of the text after the Jinja render, the same
as the file's unless a Jinja block adds or removes lines):

```text
scenarios/cli/x.yaml: steps[0].fragments.repositories[1].file: '../fragment/repo.jsonnet' not found (relative to .../scenarios/cli)
scenarios/cli/x.yaml: step 'create': unknown template variable(s) ['slug'] in fragments.repositories[1] (scenarios/fragments/repo.jsonnet:3)
scenarios/cli/x.yaml: step 'create': fragments.repositories[1] (scenarios/fragments/repo.jsonnet:7): value is not a dummy value: use '********' or 'e2e-dummy-<8 chars [0-9a-z]>' (otterdog prints it)
scenarios/cli/x.yaml: step 'create': libraries.e2e (scenarios/lib/e2e.libsonnet:4): importstr is not allowed: the webapp evaluates one file, an import could read the workspace (use libraries)
scenarios/cli/x.yaml: step 'create': overlay[0] changes the organization settings: set org_level: true
```

**Shared files** of the repository:

| File | Content |
|---|---|
| `scenarios/lib/e2e.libsonnet` | library `e2e`: `publicRepo(name, description)`, `privateRepo(name, description)` (`private`, `allow_forking: false`, `has_wiki: false`), `defaultBranchRuleset(name)`, `statusChecks(checks, strict=true)`, `selectedBranchesEnvironment(name, branches, wait_timer=0)` |
| `scenarios/fragments/environment-repo.jsonnet` | a run repository with the environment `e2e-staging` (library `e2e`; vars `wait_timer`, `branch_policies`) |
| `scenarios/fragments/repo-basic.jsonnet` | a public run repository with a description and a topic |
| `scenarios/fragments/ruleset-repo.jsonnet` | a run repository with a default-branch ruleset (library `e2e`) |
| `scenarios/fragments/org-variable.jsonnet` | an organization variable visible to every repository (a `variables` fragment) |
| `scenarios/fragments/overlay-run-topics.jsonnet` | the overlay above |
| `scenarios/fragments/offline-config.jsonnet` | the complete offline configuration above (`config`, `base_config`) |

`cli.environment` (both steps render `environment-repo.jsonnet` with their own `vars`) and `cli.neg.private-bpr`
(`e2e.privateRepo` in an inline fragment) are the examples among the live scenarios. Every live step is validated
offline by the scenario lint ([Linting live scenarios offline](#linting-live-scenarios-offline)), and
`otterdog-e2e inject` tries files without writing a scenario
([local-development.md](local-development.md#ad-hoc-injection)).

## Expectations

**plan / local-plan** outcomes, in this order:

- `validation_error`: validation errors, or a configuration that does not load (`Planning aborted due to validation
  errors`, `failed to load configuration`);
- `error`: non-zero exit, timeout, aborted plan or no `Plan:` summary;
- `changes`: at least one non-read-only change of this run's objects (offline: of any object; `org_level`: of this
  run's objects or of the org `settings`);
- `noop`: nothing (read-only notes such as `setting 'plan' is read-only` never count);
- `any`: no check.

`counts` are otterdog's raw `Plan:` numbers (`change` counts changed attributes) for offline and `org_level`
scenarios, and for live scenarios whose plan holds no foreign change; when foreign objects changed too (drift on the
org), they are recomputed from this run's objects with the same arithmetic.

**apply** `ok` means: exit code 0, a summary printed, no failed patch, no validation abort. A step with
`delete: true` first checks its own plan with the guard (every removal must belong to this run).

**contains / not_contains** match the output after removing ANSI codes, box borders and padding; the rendered
strings already contain the real prefix, so write `'+ add repository[name="{{ p }}-basic"]'`. They are checked
whatever the outcome: a plan expected to fail (`validation_error`, `error`) can assert its messages. An offline step
whose `validate.ok` is false or whose `plan.expect` is `validation_error` also accepts a failing `show` (a
configuration that does not load fails every command).

**exit_code** (`validate`, `plan`) compares otterdog's exit status; `null` (the default) does not check it. otterdog
exits with the number of validation errors (two errors exit 2, like a crash) and with 2 for a configuration or
loading error, so assert the messages too:

```yaml
- name: two-errors
  base_fragments: {}
  fragments:
    repositories:
      - "orgs.newRepo('{{ p }}-a') { squash_merge_commit_title: 'NOPE' }"
  validate: {ok: false, errors: 2, exit_code: 2}
  plan: {expect: validation_error, exit_code: 2, contains: ["Planning aborted due to validation errors"]}
```

**Info messages** are printed by `validate` only with `-v`: `validate: {verbose: true}` runs `validate -v`, and only
then `infos` (exact count) and `infos_min` can be checked (the loader refuses them without `verbose`). Boxed messages
read `Info: <message>` after normalization. Without `-v`, `validate` prints `in order to print validation infos,
enable printing info messages by adding '-v' flag.` and `local-plan` `there have been <n> validation infos, enable
verbose output to display them.` (`plan: {verbose: true}` shows them in a plan):

```yaml
- name: infos
  fragments:
    secrets: ["orgs.newOrgSecret('{{ P }}_S') { value: '********' }"]
    repositories:
      - "orgs.newRepo('{{ p }}-arch') { archived: true, branch_protection_rules: [orgs.newBranchProtectionRule('main')] }"
  validate:
    verbose: true
    infos: 2
    contains:
      - 'Info: org_secret[name="{{ P }}_S"] only has a dummy value, resource will be skipped.'
      - 'Info: repository[name="{{ p }}-arch"] is archived but has branch_protection_rules which will be ignored.'
```

A warning `ignoring unknown properties found while validating` (a fragment in the wrong place) fails the phase
unless a `contains` of the step's `validate`, `plan` or `apply` mentions "unknown propert".

## Plan and apply options

`plan` and `apply` take the flags otterdog's diff commands share (verified against otterdog/cli.py: `plan`,
`local-plan` and `apply` all have them; `local-plan` has no `-n`):

| Key | otterdog flag | Meaning |
|---|---|---|
| `repo_filter` | `-r <pattern>` | shell pattern of the repositories included; organization-level objects are never filtered |
| `update_secrets` | `--update-secrets` | forced update (`!`) of every secret with a value, whether it changed or not (values are never compared otherwise) |
| `update_webhooks` | `--update-webhooks` | forced update of every webhook with a secret |
| `update_filter` | `--update-filter <pattern>` | shell pattern of the secret names / webhook urls a forced update includes; needs `update_secrets` or `update_webhooks` |
| `only_secrets` | `--only-secrets` | only secret changes are planned or applied |
| `verbose` | `-v` | Info messages (never more than one `-v` live) |

Live steps: the plan flags go to `plan -n`, the apply flags to `apply -f -n`; they are independent (`update_secrets`
on the plan shows the forced updates, on the apply performs them), except `repo_filter`: the apply uses the plan's
unless it has its own, and an apply with `delete: true` must use the plan's filter and the plan's diff flags
(`update_secrets`, `update_webhooks`, `update_filter`, `only_secrets`; the guard checked that plan), and never
`only_secrets` (a secrets-only plan hides the other removals). Converge
plans with the apply's filter and never with an update flag (forced updates never converge; an `only_secrets` apply
leaves other changes pending: use `converge: false`). Without `repo_filter` live plans use `-r e2e-<run>-*`
(`org_level`: no filter). A live `repo_filter` must start with `{{ p }}-` unless the scenario is `org_level`: the
loader checks it with a sample prefix and the engine again with the real one (SafetyError), so a scenario can never
plan or apply other repositories.

```yaml
- name: force-one-secret          # after a step that created the repository and its secrets
  fragments:
    repositories: &vault
      - |
        orgs.newRepo('{{ p }}-vault') {
          secrets: [
            orgs.newRepoSecret('{{ P }}_A1') { value: 'e2e-dummy-{{ run }}' },
            orgs.newRepoSecret('{{ P }}_B1') { value: 'e2e-dummy-{{ run }}' },
          ],
        }
  plan:
    expect: changes
    repo_filter: "{{ p }}-vault"
    update_secrets: true
    update_filter: "{{ P }}_A*"
    contains: ['! repo_secret[name="{{ P }}_A1", repository={{ p }}-vault]']
    not_contains: ['! repo_secret[name="{{ P }}_B1"']
  apply: {update_secrets: true, update_filter: "{{ P }}_A*"}
```

Offline steps: the plan flags go to `local-plan -s -BASE --local` (any `repo_filter`: nothing is applied):

```yaml
- name: only-secrets
  base_fragments:
    secrets: ["orgs.newOrgSecret('{{ P }}_S') { value: 'pass:e2e/a' }"]
    repositories: ["orgs.newRepo('{{ p }}-a') { description: 'a' }"]
  fragments:
    secrets: ["orgs.newOrgSecret('{{ P }}_S') { value: 'pass:e2e/a' }"]
    repositories: ["orgs.newRepo('{{ p }}-a') { description: 'b' }"]
  plan:
    expect: changes
    only_secrets: true
    update_secrets: true
    contains: ['! org_secret[name="{{ P }}_S"]']
    not_contains: ['repository[']
```

## State checks

`state` entries are evaluated against the independent read-only oracle (GitHub REST/GraphQL, never otterdog), retried
every 5 s for up to 60 s (a check's own `timeout:` in seconds extends the budget, e.g. for webhook deliveries).
`otterdog_e2e.scenarios.checks.CHECK_KINDS` is the reference: each kind names an `Oracle` method and its parameters
(a unit test checks that they match). Kinds marked *list* return a list and refuse `absent`.

**Organization: profile, Actions, members and security**

| Kind | Parameters | Value |
|---|---|---|
| `org` | | `GET /orgs/{org}` |
| `org_actions` | | org Actions permissions (`enabled_repositories`, `allowed_actions`) |
| `org_workflow_permissions` | | default workflow permissions |
| `org_selected_actions` | | `{github_owned_allowed, verified_allowed, patterns_allowed}`; absent while `allowed_actions` is not `selected` (409) |
| `org_actions_selected_repositories` | | *list*: names of the repositories Actions is enabled for (`[]` unless `enabled_repositories` is `selected`) |
| `org_fork_pr_approval` | | `{approval_policy}` |
| `org_fork_pr_workflows_private_repos` | | `{run_workflows_from_fork_pull_requests, send_write_tokens_to_workflows, send_secrets_and_variables, require_approval_for_fork_pr_workflows}`; otterdog does not manage it: assert that it stays unchanged |
| `org_cache_storage_limit` | | `{max_cache_size_gb}` of the documented `/organizations/{org}/actions/cache/storage-limit` |
| `org_cache_storage_limit_orgs_path` | | the same through `/orgs/{org}/...`, the path otterdog calls (KB-006 evidence: `unavailable: true` means that path does not work) |
| `org_secret` | `name` | secret metadata (never the value) |
| `org_secret_repos` | `name` | *list* of selected repository names |
| `org_variable` | `name` | variable |
| `org_variable_repos` | `name` | *list* of selected repository names |
| `org_webhook` | `url` | hook with this config URL |
| `org_webhook_deliveries` | `url` | *list* of the deliveries of the org hook with this URL (`[]` while it does not exist) |
| `org_webhook_delivery` | `url`, `event` | the newest delivery of `event` of that hook, in full (`request.headers`, `request.payload`, `response`) |
| `org_ruleset` | `name` | ruleset |
| `org_role` | `name` | organization role (`GET /orgs/{org}/organization-roles`: `description`, `base_role`, `permissions`) |
| `org_role_teams` | `name` | *list* of the team slugs holding the role (`[]` and recorded 404 for a missing role, 422 when roles are disabled) |
| `security_managers` | | *list* of the team slugs of the predefined `security_manager` role (the legacy security-managers endpoint is closing down and never used) |
| `code_security_defaults` | | *list* `[{default_for_new_repos, configuration}]`; `[]` is otterdog's `default_code_security_configurations_disabled` |
| `code_security_configuration` | `name` | code security configuration |
| `custom_property` | `name` | property definition |
| `org_members` | | *list* `[{login, role: admin\|member}]` |
| `org_members_2fa_disabled` | | *list* of logins without two-factor authentication |
| `org_membership` | `login` | `{state, role}` |
| `org_invitations` | | *list* of pending invitations |
| `org_security_advisories` | | *list*: the repository advisories of the org (the listing behind `list-advisories`) |

**Teams**

| Kind | Parameters | Value |
|---|---|---|
| `team` | `slug` | team |
| `team_members` | `slug` | *list* of member logins |
| `team_membership` | `slug`, `login` | `{role, state}` |
| `team_invitations` | `slug` | *list* of pending invitations |
| `team_repo_permission` | `slug`, `repo` | `pull`, `triage`, `push`, `maintain`, `admin` or a custom role |

**Repositories: settings, access, branches, workflows and security**

| Kind | Parameters | Value |
|---|---|---|
| `repo` | `name` | repository |
| `repo_topics` | `name` | *list* of topics |
| `repo_default_branch` | `repo` | the default branch name (a string) |
| `repo_branches` | `repo` | *list* of branch names |
| `repo_branch` | `repo`, `branch` | branch (`name`, `commit`, `protected`, `protection`); absent when missing or renamed (GitHub redirects to the new name) |
| `repo_teams` | `repo` | *list* of teams granted access (`slug`, `permission`, ...) |
| `repo_collaborators` | `repo` | *list* of the direct collaborators `[{login, role_name, permissions}]` |
| `repo_collaborator_permission` | `repo`, `login` | `{permission, role_name}` |
| `repo_invitations` | `repo` | *list* of open invitations |
| `repo_actions` | `name` | repository Actions permissions |
| `repo_workflow_permissions` | `name` | repository workflow permissions |
| `repo_selected_actions` | `repo` | as `org_selected_actions` (409: absent) |
| `repo_fork_pr_approval` | `repo` | `{approval_policy}` (otterdog manages it on public repositories only) |
| `repo_fork_pr_workflows_private_repos` | `repo` | as the org kind (not managed by otterdog) |
| `repo_cache_storage_limit` | `repo` | `{max_cache_size_gb}` (KB-007 evidence when unavailable) |
| `workflow` | `repo`, `workflow` (file name or id) | `{id, name, path, state}` |
| `workflow_runs` | `repo`, `workflow` | *list* of runs, newest first, at most 200 |
| `repo_workflow_runs` | `repo` | *list* of the runs of every workflow, newest first, at most 200 |
| `repo_security_and_analysis` | `repo` | `security_and_analysis` of the repository: `secret_scanning`, `secret_scanning_push_protection`, `dependabot_security_updates`, ... each `{status}` |
| `repo_vulnerability_alerts` | `repo` | `{enabled}` (204 enabled, 404 disabled; absent only when the repository is missing) |
| `repo_automated_security_fixes` | `repo` | `{enabled, paused}`, `{enabled: false}` on 404 |
| `repo_private_vulnerability_reporting` | `repo` | `{enabled}` (403/422: unavailable) |
| `repo_code_scanning_default_setup` | `repo` | `{state, languages, query_suite, ...}` (403, GitHub Advanced Security not enabled: unavailable) |
| `repo_security_advisories` | `repo` | *list* of the repository's advisories (every state the owner token sees) |
| `repo_security_advisory` | `repo`, `ghsa_id` | advisory |
| `repo_secret` | `repo`, `name` | secret metadata |
| `repo_variable` | `repo`, `name` | variable |
| `repo_webhook` | `repo`, `url` | hook with this config URL |
| `repo_webhook_deliveries` | `repo`, `url` | *list* of the deliveries of the repository hook with this URL (`[]` while it does not exist) |
| `repo_webhook_delivery` | `repo`, `url`, `event` | the newest delivery of `event` of that hook, in full |
| `repo_custom_properties` | `repo` | mapping of property values |
| `pages` | `repo` | Pages site |

**Branch protection, rulesets, environments**

| Kind | Parameters | Value |
|---|---|---|
| `bpr` | `repo`, `pattern` | branch protection rule (GraphQL): `pattern`, `requiresApprovingReviews`, `requiredApprovingReviewCount`, `requiresStatusChecks`, `requiresStrictStatusChecks`, `requiredStatusCheckContexts`, `isAdminEnforced`, `allowsForcePushes`, `allowsDeletions`, `requiresLinearHistory`, `requiresConversationResolution`, `requiresCommitSignatures`, `dismissesStaleReviews`, `requiresCodeOwnerReviews`, `lockBranch`, `restrictsPushes`, `blocksCreations`, `lockAllowsFetchAndMerge`, `requireLastPushApproval`, `restrictsReviewDismissals`, `requiresDeployments`, `requiredDeploymentEnvironments`, `requiredStatusChecks` (`[{context, app: {slug} \| null}]`, `null`: any source) and the actor lists `bypassPullRequestAllowances`, `bypassForcePushAllowances`, `pushAllowances`, `reviewDismissalAllowances` in otterdog's notation (`'@login'`, `'@org/team'`, `'app-slug'`) |
| `repo_ruleset` | `repo`, `name` | ruleset |
| `environment` | `repo`, `name` | environment |
| `env_branch_policies` | `repo`, `env` | *list* of deployment branch policies |
| `env_secret` | `repo`, `env`, `name` | secret metadata |
| `env_variable` | `repo`, `env`, `name` | variable |

Each check uses exactly one form:

| Form | Holds when |
|---|---|
| `match: {...}` | the value exists and contains the given fields (subset match: mappings need the listed keys, lists need the same length and element-wise matches, scalars are equal; booleans never equal numbers) |
| `absent: true` / `absent: false` | the object does not exist / exists (single-object kinds only); `absent: true` also needs its parents (the `repo`, the `slug` team, the `env` environment) to exist and the listing to be available |
| `equals: <value>` | exact equality, from an available listing |
| `contains: [...]` | every item is matched by a list element, is a substring of a string, or is a key of a mapping |
| `unavailable: true` | the listing or the feature setting is not available on the plan: 403/404, 402 for the cache limits, 422 for private vulnerability reporting and organization roles |

An `absent: true` or an `equals` answered by a listing that was unavailable (403/404) is a (retried) failure, not a
pass: an unavailable listing proves nothing. Add `unavailable_ok: true` to a check that means "absent or unavailable".
A 409 "does not apply" answer (selected actions while `allowed_actions` is not `selected`) is not unavailable, but its
empty answer is not evidence either: check the policy itself instead of `equals: []` on such a selection.

Inside `match`, `contains` and `equals` values: `{$regex: "..."}` (search), `{$exists: true|false}` (`false` also
holds for null), `{$unordered: [...]}` (same items in any order), `{$len: n}`. Inside `equals` the comparison stays
exact around them: `$unordered` items must equal the actual items exactly, a mapping may not have extra keys, and only
a key expected `{$exists: false}` may be missing.

```yaml
state:
  - {kind: repo, name: "{{ p }}-app", match: {visibility: public, topics: {$unordered: [e2e, otterdog]}}}
  - {kind: team_members, slug: "{{ p }}-devs", equals: ["{{ logins.author }}"]}
  - {kind: repo_webhook, repo: "{{ p }}-app", url: "{{ hook_base }}push", match: {active: true}, timeout: 120}
  - {kind: repo_webhook_deliveries, repo: "{{ p }}-app", url: "{{ hook_base }}push", contains: [{event: ping}], timeout: 300}
  - {kind: repo_webhook_delivery, repo: "{{ p }}-app", url: "{{ hook_base }}push", event: ping, timeout: 300,
     match: {request: {headers: {X-Hub-Signature-256: {$regex: '^sha256='}}}}}
  - {kind: org_ruleset, name: "{{ p }}-main", unavailable: true}
  - {kind: bpr, repo: "{{ p }}-app", pattern: main,
     match: {requireLastPushApproval: true, reviewDismissalAllowances: {$unordered: ['@{{ org }}/{{ p }}-maint']}}}
  - {kind: org_selected_actions, match: {github_owned_allowed: true, patterns_allowed: {$unordered: ['actions/*']}}}
```

GitHub sends a `ping` when a hook is created, and its delivery log lags by up to a few minutes; give delivery checks
a `timeout`. Checks that YAML cannot express run as Python *probes* between two steps (`tests/cli/conftest.py`
`PROBES`, e.g. the explicit ping of `cli.repo.webhook`): a probe gets the oracle, the admin `Mutator` (workflow
dispatch, team members, topics, collaborators, advisories, code security configurations: run objects only) and the
scenario variables. A scenario with a probe declares a `timeout` that covers it.

## Capabilities, plans and negative tests

- `requires: [custom_properties]` skips the scenario (before any fixture runs) when the target lacks the capability;
  `min_plan: enterprise` skips it below Enterprise Cloud.
- `expect_failure_without` runs the scenario anyway when the capability is missing, with the step's
  `on_missing_capability` overrides: the documented way to test that otterdog reports, or GitHub refuses, a feature
  the plan does not include.

```yaml
id: cli.example.private-bpr
title: Branch protection on a private repository needs a paid plan
priority: P2
tags: [bpr]
expect_failure_without: [private_repo_branch_protection]
steps:
  - name: public
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-private') {
            has_wiki: false,
          }
  - name: protect
    fragments:
      repositories:
        - |
          orgs.newRepo('{{ p }}-private') {
            private: true,
            allow_forking: false,
            has_wiki: false,
            branch_protection_rules: [
              orgs.newBranchProtectionRule('main'),
            ],
          }
    state:
      - {kind: bpr, repo: "{{ p }}-private", pattern: main, match: {pattern: main}}
    on_missing_capability:
      apply: {expect: any}
      state: []
      converge: false
```

(A private repository needs `allow_forking: false` with the template's defaults, and `has_wiki: false` avoids a
plan warning on Free. Create it public and make it private in a later step: otterdog before 1.7.0.dev14, the
default SUT `release:latest` included, sends the code scanning default setup PATCH after creating any repository,
which GitHub refuses for a private repository of an organization without Code Security, so a first apply that
creates a private repository fails (#791). `tests/unit/test_yaml_cli.py` refuses such a step unless the scenario's
`fixed_in` is at least 1.7.0.dev14.)

- `variables: {plan: enterprise}` renders another plan into `settings.plan`: on a Free org the live plan is still
  `free`, and otterdog only prints `setting 'plan' is read-only`; this is how plan-gated validation is tested.

## Organization-level scenarios

A scenario whose fragments contain `settings` must declare `org_level: true` (settings carry no run prefix, so only an
unfiltered plan sees them and only a full baseline reset restores them). `org_level` scenarios plan without `-r`,
count the org `settings` object as one of theirs, and run `BaselineManager.reset()` as cleanup:

```yaml
id: cli.example.org-setting
title: Organization setting round trip
org_level: true
tags: [org-settings]
steps:
  - name: enable
    fragments:
      settings:
        - "web_commit_signoff_required: true"
    state:
      - {kind: org, match: {web_commit_signoff_required: true}}
```

Live settings fragments must never set `plan`, `description` or `billing_email` (they come from the live
organization; the description holds the safety marker). The other profile keys (`name`, `email`, `blog`, `location`,
`company`, `twitter_username`) may be set by `org_level` scenarios; layer 1 renders the live values, and a key the live
organization did not return is hidden there (`key:: null`): manage it with `key::: value`. Offline scenarios may set
every profile key, `plan` excepted ([Offline scenarios](#offline-scenarios)).

## Secrets

otterdog prints secret values in validate and plan output and in PR comments. Every secret value in a scenario
(webhook `secret`, `value` of `newOrgSecret`/`newRepoSecret`/`newEnvSecret` objects) must be one of:

| Value | Tiers | Notes |
|---|---|---|
| `********` (any number of `*`) | all | otterdog skips dummy values entirely (never added nor updated; Info "only has a dummy value") |
| `e2e-dummy-<8 chars [0-9a-z]>`, usually `'e2e-dummy-{{ run }}'` | all | a plain value otterdog applies as it is (Warning "does not use a credential provider"); webhook secrets too |
| `pass:<path>` (`[A-Za-z0-9_][A-Za-z0-9._/-]*`, e.g. `pass:bots/technology.csi/github.com/otterdog-token`) | all | a provider reference as in real configurations: validated silently, shown as is by plan; a live apply resolves it with the `pass` CLI, which the harness never provides (the apply fails) |
| `<provider>:e2e/<path>` of another provider than pass, bitwarden or vault (e.g. `foo:e2e/b`) | all | otterdog warns that it does not use a credential provider and applies the literal |
| `pass:<path>:<more>` (several `:`, e.g. `pass:a:b`) | offline only | reproduces KB-025: validation crashes with `too many values to unpack (expected 2)` (exit 2) |
| empty string or `null` | all | |

Paths are restricted to shell-safe characters: otterdog resolves `pass:` references with a shell command at apply time.
`apply: {update_secrets: true}` (or `update_webhooks`) forces otterdog to write values it cannot compare. Since plain
dummies warn with the secret's name, assert forced updates on the header: `not_contains: ['! repo_secret[name="..."']`.

```yaml
fragments:
  repositories:
    - |
      orgs.newRepo('{{ p }}-vault') {
        secrets: [
          orgs.newRepoSecret('{{ P }}_TOKEN') { value: 'e2e-dummy-{{ run }}' },
        ],
        webhooks: [
          orgs.newRepoWebhook('{{ hook_base }}secured') { secret: 'e2e-dummy-{{ run }}' },
        ],
      }
```

## Offline scenarios

Offline scenarios run against the minimal organization `e2e-offline` (plan from `variables.plan`, default `free`), no
baseline repositories, with the SUT's template vendored and the network blocked (`unshare -rn`, or `--network none`
for untrusted SUTs). Per step: the step's [workspace variant](#workspace-variants-offline), `validate --local`
(always; `-v` with `validate.verbose`), `local-plan --local` against the `-BASE` file when `base_fragments` or
`base_config` is given (with the [plan flags](#plan-and-apply-options)), `show --local` (must exit 0 unless the step
expects validation to fail, i.e. `validate.ok` false or `plan.expect` validation_error; `commands.show` gives its own
expectations), then the `commands`. A step's `config` file replaces the rendered configuration
([Injecting jsonnet from files](#injecting-jsonnet-from-files)).

Offline scenarios cannot use `apply`, `state`, `requires`, `expect_failure_without`, `identities`, `org_level`,
`logins.*` or a `min_plan` other than free; `teams`, `newTeam` and `code_scanning_default_languages` are refused
because their validation calls GitHub even with `--local` (languages are allowed in an object that also sets
`code_scanning_default_setup_enabled: false`: the language detection only reads GitHub for an enabled setup, the
language enum is then validated offline). A `plan` mapping needs a BASE configuration
(`base_fragments: {}` is the bare organization): `local-plan` never runs without one, so its expectations would be
ignored.

Offline settings fragments may set the organization profile, `description`, `billing_email`, `name`, `email`, `blog`,
`location`, `company`, `twitter_username`, since nothing is applied; `plan` stays `variables.plan`. Such snippets are
rendered as an overlay `{ settings+: { ... } }` right after the scenario layer, and layer 1 leaves those keys out, so a
plain `key: value` is visible. Offline overlays may set them too, but layer 1 still hides every profile key except
`description` there: write `key::: value` in an overlay.

```yaml
- name: description-length
  fragments: {settings: ["description: std.repeat('d', 161)"]}
  validate: {ok: false, errors: 1, contains: ["setting 'description' exceeds maximum allowed length of 160 chars."]}
- name: profile
  fragments: {settings: ["name: 'E2E Offline Name'", "billing_email: 'billing@example.org'"]}
  commands:
    show: {contains: ['E2E Offline Name', 'billing@example.org']}
```

```yaml
id: offline.example.plan-gate
title: Organization rulesets are rejected on the free plan
priority: P1
tags: [rulesets]
observe: true
steps:
  - name: validate
    fragments:
      rulesets:
        - |
          orgs.newOrgRuleset('{{ p }}-all') {
            include_repo_names: ['~ALL'],
          }
    validate:
      ok: false
      errors: 1
      contains:
        - "use of organization rulesets requires an 'enterprise' plan"
```

```yaml
id: offline.example.local-plan-add
title: local-plan shows a new repository
tags: [repo]
observe: true
steps:
  - name: add
    base_fragments: {}
    fragments:
      repositories:
        - "orgs.newRepo('{{ p }}-basic') { description: 'e2e basic' }"
    validate: {ok: true}
    plan:
      expect: changes
      counts: {add: 1}
      contains:
        - '+ add repository[name="{{ p }}-basic"]'
    commands:
      show-default: {contains: ["newRepo"]}
```

Offline counts are the raw `Plan:` numbers of `local-plan` (BASE versus the step configuration).

### Workspace variants (offline)

`workspace` changes otterdog's own configuration for one step (configuration discovery and loading tests). The engine
writes it before the step's configuration and switches back to the harness layout (otterdog.json, one organization,
`orgs/`, the vendored template) at the next step without `workspace`. Its strings are rendered like every other
string, except `config_dir` (a literal directory name).

| Key | Default | Meaning |
|---|---|---|
| `format` | `json` | `jsonnet` writes `otterdog.jsonnet` instead of `otterdog.json` (the document behind a jsonnet `local`, so only jsonnet evaluation reads it); the `-c` file follows |
| `orgs` | `[]` | extra `organizations` entries: a string is the github_id (and name) of an ordinary organization; a mapping of `name`, `github_id`, `config_repo`, `base_template`, `archived`, `approval_teams`, `admin_teams`, `credentials` (null only) is merged over `{name: <github_id>, config_repo, credentials: env provider}`; `null` values are written as null (otterdog then reports the missing key). Their configurations are not written: the step's commands run on `e2e-offline` |
| `defaults_override` | `null` | content of `.otterdog-defaults.json` next to the config file: keys `base_url`, `jsonnet` (`base_template`, `config_dir`), `github` (`config_repo`, `exclude_teams`), `cost_policy`; otterdog merges it OVER the defaults of the config file (a null value too). No credential provider settings |
| `base_url` | `null` | `defaults.base_url` (default `https://otterdog.invalid`) |
| `config_dir` | `orgs` | `defaults.jsonnet.config_dir`; the harness writes the org configs and the vendored template to `<config dir>/e2e-offline/`, the override's `jsonnet.config_dir` winning (one path segment) |
| `vendor` | `true` | `false`: no vendored template, `--local` commands then fail with `template file '...' does not exist` |

```yaml
id: offline.example.workspace
title: otterdog's configuration variants
steps:
  - name: jsonnet-and-orgs
    fragments: {}
    workspace:
      format: jsonnet
      orgs: ["{{ org }}-2", {github_id: e2e-archived, archived: true}]
    validate: {ok: true}
    commands:
      list-projects: {contains: [e2e-offline-2], not_contains: [e2e-archived]}
  - name: override
    fragments: {}
    workspace: {defaults_override: {jsonnet: {config_dir: orgs-override}}}
    validate: {ok: true}
  - name: no-vendor
    fragments: {}
    workspace: {vendor: false}
    validate: {ok: false, exit_code: 2, contains: ["does not exist"]}
  - name: missing-github-id
    fragments: {}
    workspace: {orgs: [{name: e2e-x}]}
    validate: {ok: false, exit_code: 2, contains: ["missing required github_id for organization config with name 'e2e-x'"]}
  - name: no-base-template
    fragments: {}
    workspace: {defaults_override: {jsonnet: {base_template: null}}}
    validate: {ok: false, exit_code: 2, contains: ["need to define a base template"]}
```

Python tests use the same layouts (`otterdog_e2e.otterdog.workspace.WorkspaceLayout`, [Python tests](#python-tests)),
plus `document` (a complete configuration of their own) and the raw `invoke` API for commands without `-c`.

## Linting live scenarios offline

The offline tier also lints the live scenarios (`tests/offline/test_scenario_lint.py`, one item
`test_live_scenario_lint[<scenario id>/<step>]` per step of `scenarios/cli`, `scenarios/regressions` and
`scenarios/enterprise`): each step is rendered for the offline organization (marker description; plan
`variables.plan`, else `min_plan`), with the SUT's template, and validated with `validate --local`. A step whose
`validate.ok` is false or whose `plan.expect` is `validation_error` must produce errors, every other step must
validate (warnings are fine, the misplaced-field warning is not). Broken jsonnet, misspelled fields, bad files and
wrong expectations thus fail `make offline`, before any live run. Skipped with the reason: steps with teams or
`code_scanning_default_languages` (their validation calls GitHub) and scenarios whose `fixed_in` the SUT predates;
a mismatch in a scenario of a known bug the SUT has is an expected failure. Run only the lint with
`otterdog-e2e run --suite offline -k lint`.

## Differential observation

With `observe: true`, the offline engine records every command of every step (`validate`, `local-plan`, `show`,
`commands`) through the recorder of each SUT side; differential runs compare base and head per
(scenario, step, kind, key). Live scenarios are observed with `validate` and `plan` only (never `apply`), so their
step *k* always plans against an org without the objects of earlier steps. Expected deltas are declared in the PR
manifest ([testing-an-otterdog-pr.md](testing-an-otterdog-pr.md)).

## Known bugs

`known_bug: KB-<nnn>` (or the bug's own `scenarios:` list in `scenarios/known_bugs.yaml`) turns the item into a
non-strict xfail with the reason `<id>: <title>`: the scenario still runs, a failure is reported as XFAIL and a fixed
bug shows up as XPASS. Once the entry has `status: fixed`, the xfail is dropped and the item guards against the
regression. The exception is a SUT whose version predates a PEP 440 `fixed_in` of the bug: the xfail stays there.
See [known-issues.md](known-issues.md).

A **step** can declare a known bug of its own, so that only its expectations are expected to fail while the other
steps stay strict:

```yaml
steps:
  - name: crash
    known_bug: KB-025          # validation crashes on a value with two ':'
    fragments: {secrets: ["orgs.newOrgSecret('{{ P }}_C') { value: 'pass:a:b' }"]}
    validate: {ok: true}      # what otterdog should do
  - name: after
    fragments: {}
    validate: {ok: true}      # strict: a failure here fails the item
```

While the bug affects the SUT (its `status` is not `fixed`, or the SUT predates its `fixed_in`; an id missing from
known_bugs.yaml counts as affecting), a failing phase of that step is an **expected failure**: it stops the step, is
recorded in `ScenarioOutcome.expected_failures` (with the bug in `expected_bugs` and `StepOutcome.expected_failure`),
and the scenario goes on with the next step. Infra problems (`[infra]`) and harness errors (render errors, safety
refusals, exceptions, state checks that could not be evaluated because the oracle lookup raised) of the step stay
failures; with `known_bug: {id: KB-<nnn>, phases: [...]}` the failures of the other phases stay failures too. When nothing else failed, the item ends as XFAIL with the reason
`KB-025: <title> (step 'crash'): <first expected failure>` (`raise_for_failures` calls `pytest.xfail`, after the
cleanup of a live scenario). A known-bug step that passes is recorded in `unexpected_passes` and reported with a
`KnownBugNotReproducedWarning` (the bug may be fixed: update known_bugs.yaml). For a fixed bug the SUT contains, the
step is strict again (a regression guard). The engines read the bugs from their `known_bugs` attribute (the
`scenario_engine` and `offline_engine` fixtures set it to the session's registry), else from the `known_bugs.yaml`
above the scenario file (`scenarios/known_bugs.yaml`). A bug declared by a step must NOT list the scenario in its
`scenarios:` (a listed scenario xfails as a whole at collection, the other steps would no longer be strict); a unit
test checks every scenario and step link. The offline scenario lint honours a step's own `known_bug` too, and in a
cli scenario with a probe an expected failure before the probe ends the item as XFAIL after the cleanup (the probe
and the remaining steps do not run).

## Fixes that are not released yet

A regression scenario of a fix merged after the latest release declares `fixed_in` (the version of the fix commit,
`v<last release> + n commits` -> `X.(Y+1).0.dev<n>`; `git rev-list --count v1.6.1..<sha>` in the harness mirror gives
`n`). `release:latest` then skips it with "SUT 1.6.1 predates otterdog 1.7.0.dev15, ...", and `branch:main`, PR and
local builds run it. Offline scenarios whose expectation depends on the exact history decide with git ancestry
instead (`SUT_EXPECTATIONS` in `tests/offline/test_scenarios.py`).

## Loading rules

`load_scenario` refuses (`ScenarioError`, the collection fails with the file and the reason):

- unknown keys, YAML duplicate keys (merge keys `<<` are allowed), wrong types, duplicate scenario ids or step names;
- a tier that does not match its directory, offline-only keys in live scenarios and live-only keys in offline ones;
- `on_missing_capability` without `expect_failure_without`;
- settings fragments setting `plan`, `description` or `billing_email` (offline: `plan` only), or live settings
  fragments without `org_level`;
- secret values that are no dummy nor reference ([Secrets](#secrets); the KB-025 literal offline only), offline
  `teams`/`newTeam`/`code_scanning_default_languages` (languages beside `code_scanning_default_setup_enabled: false`
  are allowed);
- `infos`/`infos_min` without `validate.verbose`, an `update_filter` without `update_secrets` or `update_webhooks`, a
  live `repo_filter` that does not start with `{{ p }}-` (unless `org_level`), an apply with `delete: true` and a
  `repo_filter` other than its plan's, an offline `plan` without `base_fragments`/`base_config`;
- `workspace` in a live step; its unknown keys, formats other than `json`/`jsonnet`, a `config_dir` (or the
  override's `jsonnet.config_dir`) that is not one path segment, organization entries with other keys or non-null
  `credentials`, defaults override keys other than `base_url`, `jsonnet`, `github`, `cost_policy`;
- fragments ending with a line comment;
- `import`, `importstr` or `importbin` anywhere (a `config`/`base_config` file may import the template only);
- file references: unknown keys (`file`, `raw`, `vars`), missing, absolute or out-of-project paths, empty, non-UTF-8 or
  larger than 512 KiB files, `vars` naming an engine variable or given with `raw: true`;
- library names that are no jsonnet identifier, a keyword, `orgs`, `orgs0`, `std`, `self`, `super` or `$`;
- overlays replacing `settings` or setting `plan`, `description` or `billing_email`, live overlays changing settings
  without `org_level`;
- `config` with `fragments` or `overlay`, `base_config` with `base_fragments`, either of them in a live scenario;
- Jinja syntax errors, unknown variables, overriding a reserved variable (`import_path` and `project` included),
  `logins.<role>` of a role that is not `admin` and not listed in `identities`;
- a `fixed_in` that is not a public PEP 440 version (`pr-792`, `1.7.0+local`), a `timeout` that is not a positive
  integer, and a scenario key used as a variable name (`variables: {fixed_in: ...}` would silently do nothing).

## Editor support

`.vscode/settings.json` maps `scenarios/{offline,cli,regressions,enterprise}/*.yaml` to
`.vscode/scenario.schema.json` (VS Code YAML extension: completion and key checks). It also maps
`scenarios/known_bugs.yaml` and `scenarios/otterdog-prs/*.yaml` to a permissive schema, because SchemaStore would
otherwise apply its unrelated CrowdSec "scenario" schema to them. The schema is generated from the loader's constants and
knows the file forms (`{file, raw, vars}`, `libraries`, `overlay`, `config`, `base_config`), the step options
(`known_bug`, `workspace`, the plan/apply flags, `validate.verbose`, `infos`, `exit_code`). The loader stays the
reference for every rule, and a unit test fails when the committed file is stale. Regenerate it
with:

```bash
.venv/bin/python -c 'import json; from otterdog_e2e.scenarios.model import json_schema; print(json.dumps(json_schema(), indent=2))' > .vscode/scenario.schema.json
```

Load a file quickly with:

```bash
.venv/bin/python -c 'import sys; from pathlib import Path; from otterdog_e2e.scenarios.model import load_scenario; print(load_scenario(Path(sys.argv[1])))' scenarios/cli/repo-lifecycle.yaml
```

## Markers and selection

Collection adds marks to every scenario item: `live` (cli, enterprise) or `offline`, `plan(<plans >= min_plan>)`,
`requires(...)`, `identities(...)`, `tags(...)`, `known_bug(...)`, `org_level`, `scenario(<id>)` and the timeout
(`timeout`, else the tier timeout, plus 600 s for `org_level` live scenarios; a live scenario's timeout covers the
test call only, not the session setup its fixtures trigger). With `-p no:timeout` the timeout marks are accepted and
ignored. Select with:

```bash
otterdog-e2e run --scenario 'cli.repo.*,cli.team.*' ...     # fnmatch globs on ids (every tier, unit included)
otterdog-e2e run --tags repo,secrets ...                    # any of the tags; tests/unit and tests/offline are exempt
```

Values inside one option are ORed, the two options are ANDed. `pytest -m` works on the same marks.

## Python tests

Python tests in `tests/<tier>/` use the plugin's fixtures and markers; gating happens before any fixture runs.

Markers: `live`, `offline`, `webapp`, `docker`, `differential`, `requires(*caps)`, `plan(*plans)`,
`identities(*names)`, `tags(*tags)`, `known_bug(id)`, `org_level`, `scenario(id)`, `slow`.

Session fixtures: `harness`, `run_ctx`, `e2e`, `target`, `identities`, `verified_org`, `oracle`, `mutator`,
`mutators`, `outsider_mutator`, `approver_mutator`, `contributor_mutator` (the author identity; these three gate on
their identity like `identities(...)`), `capabilities`, `sut`, `reset_sut`, `base_sut`, `template_ref`,
`base_template_ref`, `pr_manifest`, `renderer`, `workspace`, `otterdog`, `reset_cli`, `baseline`, `scenario_engine`,
`app_auth`, `installation_id`, `webapp_image`, `webapp`, `webapp_api`, `relay`, `config_flow`, `injector`,
`webapp_stack` (the compose stack; items using it skip with another transport). Function fixtures: `scenario_vars`,
`fresh_workspace`, `webapp_case` (isolation of one webapp test: main reset to the baseline and the webapp quiet
before; PRs closed, branches deleted, main restored and run objects removed after), `webapp_env` (recreate the webapp
with environment overrides, restored after), `webapp_otterdog_json` (publish otterdog.json with org-entry overrides,
restored after), `dtrack_mock` (the Dependency-Track mock, emptied before and after), `blueprints` (a
`blueprints.BlueprintHelper` cleaned up after the test), `sut_pair` (differential only). The offline tier adds
`offline_context`, `template_src`, `sut_history`, `offline_cli`, `vendored_cli` and `offline_engine`
(`tests/offline/conftest.py`), the web-UI tier `web_sut`, `web_reader` and `web_tier` (`tests/web_ui/conftest.py`).
[battery-guide.md](battery-guide.md) shows which API answers which kind of gap.

```python
"""Webapp: a valid config PR gets a success status and a validation comment."""

import pytest

from otterdog_e2e.otterdog.render import ConfigFragments

pytestmark = [pytest.mark.webapp, pytest.mark.tags("webapp")]


@pytest.mark.scenario("webapp.example.valid-pr")
@pytest.mark.identities("author")
def test_valid_pr(webapp_case, renderer, run_ctx):
    name = run_ctx.name("w-valid")
    head = renderer.render(ConfigFragments(repositories=[f"orgs.newRepo('{name}')"]))
    pr = webapp_case.flow.open_pr(slug="w-valid", config_texts=head, title="e2e: add a repository", identity="author")
    status = webapp_case.flow.wait_status(pr, "validation")
    assert status["state"] == "success"
    webapp_case.flow.wait_comment(pr, marker="validate", contains=name)
```

Every config text goes through the guard (a trusted `local-plan`) before it is pushed; webhook payloads can be
injected with the `injector` fixture (signed like GitHub does).

### The otterdog CLI from Python

`OtterdogCli` (fixtures `otterdog`, `offline_cli`, `vendored_cli` of the offline tier, `make_cli` of the cli tier)
wraps every command (`validate`, `plan`, `apply`, `local_plan`, `import_config`, `push_config`, `fetch_config`,
`open_pr`, `check_status`, `show`, `show_default`, `canonical_diff`, `list_projects`, `list_members`,
`check_token_permissions`) and returns a `CliResult` (`argv`, `exit_code`, `stdout`, `stderr`, `output`, parsers
`validation()`, `plan()`, `apply()`, `assert_ok()`). Other flags and stdin go through
`run(command, *args, org=True, input=None, local=False)` (``-c`` and the organization are added).

The diff commands take `DiffOptions` (`otterdog_e2e.otterdog.runner`): `repo_filter`, `update_webhooks`,
`update_secrets`, `only_secrets`, `update_filter`, `verbose`:

```python
from otterdog_e2e.otterdog.runner import DiffOptions

options = DiffOptions(repo_filter=run_ctx.repo_filter(), update_secrets=True, update_filter=f"{run_ctx.const_prefix}A*")
result = otterdog.plan_with(options)  # plan -n -r ... --update-secrets --update-filter ...
offline_cli.local_plan_with(DiffOptions(only_secrets=True), suffix="-BASE")  # local-plan -s -BASE --only-secrets
otterdog.apply_with(options, delete=False)  # apply -f -n ...
```

`invoke(*args, input=None, timeout=None, config_root=False, env=None)` runs `otterdog <args>` exactly as given,
without `-c`, `--local` nor organization, in a fresh empty cwd (same credentials, sandbox, `-v` limit and artifacts
as every command): `--help`, `otterdog` alone, click usage errors, and configuration discovery with
`config_root=True`, which sets `OTTERDOG_CONFIG_ROOT` (stripped from every other command) to the workspace root (`/ws`
in a container). `env` (offline CLIs only) adds variables, e.g. the dummy token of a custom credential variable name
or a `PATH` with stub provider binaries (keep the system `PATH` after them: the sandbox command is looked up there):

```python
help_text = offline_cli.invoke("--help").assert_ok().stdout
usage = offline_cli.invoke("open-pr", "-b", "x", "-t", "y")  # exit 2: Missing option '-a' / '--author'
missing = offline_cli.invoke("validate", "--local")  # exit 2: No configuration file specified ...
found = offline_cli.invoke("list-projects", config_root=True)  # finds <workspace>/otterdog.json(net)
config = str(offline_cli.workspace.config_file.resolve())
custom = offline_cli.invoke("validate", "-c", config, "--local", "e2e-offline", env={"E2E_CUSTOM_TOKEN": "dummy"})
```

Workspace variants for configuration tests (`otterdog_e2e.otterdog.workspace.WorkspaceLayout`, the YAML
[workspace](#workspace-variants-offline) key): `workspace.use_layout(layout)` writes the configuration of the layout
(`format`, `orgs`, `defaults_override`, `base_url`, `config_dir`, `vendor`, and Python only `document`, a complete
configuration written as it is); `config_file`, `org_dir`, `org_dir_for(org)`, `org_config_file_for(org, suffix=...)`
follow it, `write_org_config(text, org=...)` and `write_base_config(text, suffix="-OTHER")` write the configuration of
another organization or another `local-plan -s` side. Vendor the template yourself for extra organizations
(`sut.template.vendor_template(template_src, workspace.org_dir_for(org), workspace.template)`). Live workspaces take
layouts too, e.g. `WorkspaceLayout(defaults_override={"github": {"exclude_teams": [f"^{run_ctx.prefix}-excluded-.*"]}})`
for otterdog's team exclusion (live otterdog clones its template, `vendor` only concerns the offline engine).

```python
from otterdog_e2e.otterdog.workspace import WorkspaceLayout

ws = offline_cli.workspace
ws.use_layout(
    WorkspaceLayout(
        document={
            "defaults": {"jsonnet": {"config_dir": "orgs"}},
            "organizations": [{"name": ws.org, "github_id": ws.org, "base_template": ws.template.url}],
        }
    )
)
result = offline_cli.validate(local=True)  # exit 2: need to define a base template in your otterdog config
```

Unit tests use the fakes of `otterdog_e2e.testing.fakes`: `FakeCli` mirrors every public `OtterdogCli` method
(results queued per command; `plan_with`/`apply_with`/`local_plan_with` calls are recorded under their command with
`options` and its fields, `invoke` under its first argument) and `FakeWorkspace` is a `ConfigWorkspace` with the real
paths and layouts that records its writes in memory (`writes`, `base_writes`, `documents`, `files`).

### The web_ui marker

Web-UI behaviour (otterdog driving github.com with a bot login: the 12 web-only organization settings, `install-app`,
`review-permissions`, `list-advisories -w`, `web-login`) is tested in **Python only**, in `tests/web_ui`: every item
there is marked `web_ui` and gated before any fixture (admin web credentials, `--e2e-allow-web-ui`, a trusted SUT, no
SAML SSO, a login gate that is not blocked). YAML scenarios always run otterdog with `-n` (`--no-web-ui`) and never
log in to the web UI, so a scenario never declares `requires: [web_ui]` and never tests a web-only setting. See
[web-ui-testing.md](web-ui-testing.md) for the fixtures (`web_tier`, `e2e.web_cli(...)`), the login budget and the
restore rules.

## Checklist

- every object name uses `{{ p }}`, `{{ P }}` or `{{ hook_base }}`; a live `repo_filter` starts with `{{ p }}-`;
- steps repeat the objects they keep; removals use `apply: {delete: true}`;
- secret values are dummies or references; no `plan`/`description`/`billing_email` in live settings; `org_level`
  for settings;
- a known bug that concerns one step goes on that step (`known_bug`), the scenario-level one xfails the whole item;
- offline `plan` expectations come with `base_fragments` (or `base_config`); Info assertions with `verbose: true`;
- capabilities declared (`requires`, `expect_failure_without`, `min_plan`, `identities`);
- tags from the vocabulary; `observe: true` for offline scenarios worth comparing across SUT versions;
- long or shared jsonnet in files (`scenarios/fragments/`, helpers in `scenarios/lib/`), live steps lint-clean
  offline (`otterdog-e2e run --suite offline -k lint`);
- run it alone first: `make one SCENARIO=<id> [TARGET=free]`, then read `artifacts/<run>/summary.md` and the `cli/`
  outputs.
