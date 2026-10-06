# YAML scenario essentials

A condensed view of `docs/writing-scenarios.md`, which stays the reference (every key, every loading rule). The
loader (`src/otterdog_e2e/scenarios/model.py`) refuses unknown keys, wrong types and every rule broken below, with
the file and the place in the message: `otterdog-e2e assist check` shows those messages.

## Offline skeleton

```yaml
# scenarios/offline/validation/val-<topic>.yaml
id: O-VAL-<NAME>
title: <one line: what otterdog does>
description: >-
  Why the scenario exists: the rule or behaviour, where otterdog implements it (otterdog/<path>:<line>), which issue,
  PR or known bug it pins, and what each step proves. At least 20 words (unit test of the offline scenarios).
priority: P1
tags: [offline, <model-area tag>]
observe: true                  # every offline scenario is recorded by the differential tier
variables: {plan: free}        # plan gates: team or enterprise (rendered into settings.plan)
steps:
  - name: invalid
    fragments:
      repositories:
        - "orgs.newRepo('{{ p }}-a') { <field>: <invalid value> }"
    validate: {ok: false, errors: 1, contains: ["<exact message copied from a run>"]}
  - name: control              # the neighbouring valid case stays strict
    base_fragments: {}         # local-plan runs only with a BASE (here the bare organization)
    fragments:
      repositories: ["orgs.newRepo('{{ p }}-a') { description: 'e2e' }"]
    validate: {ok: true}
    plan:
      expect: changes
      counts: {add: 1, change: 0, delete: 0}
      contains: ['+ add repository[name="{{ p }}-a"]']
```

Offline steps run, per step: `validate --local` (always; checked only when `validate` is given), `local-plan --local`
against `-BASE` (only with `base_fragments` or `base_config`), `show --local` (must exit 0 unless the step expects
validation to fail), then `commands` (`show-default`, `canonical-diff`, `list-projects`, `--version`, each
`{exit_code, contains, not_contains}`; `show` gives the expectations of the show phase).

## Live skeleton

```yaml
# scenarios/cli/<area>-<name>.yaml
id: cli.<area>.<name>
title: <one line>
description: >-
  Why it exists and what each step proves.
priority: P1
tags: [<model-area tag>]
requires: []                   # capabilities of otterdog_e2e.capabilities.Cap, else skipped
steps:
  - name: create
    fragments:
      repositories: &repo
        - "orgs.newRepo('{{ p }}-app') { description: 'e2e app', has_wiki: false }"
    plan: {expect: changes, counts: {add: 1}}
    state:
      - {kind: repo, name: "{{ p }}-app", match: {description: e2e app, has_wiki: false}}
  - name: remove
    plan: {expect: changes, counts: {delete: 1}}
    apply: {delete: true}
    state:
      - {kind: repo, name: "{{ p }}-app", absent: true}
```

Per live step: render, `validate` (only when given), `plan -n -r e2e-<run>-*`, `apply -f -n` (when the plan expects
changes), `state` checks through the read-only oracle (retried up to 60 s, `timeout:` extends it), converge (plan
again until this run's objects are a no-op). The cleanup always runs.

## Keys at a glance

| Scenario key | Notes |
|---|---|
| `id`, `title`, `steps` | required; id `^[A-Za-z0-9][A-Za-z0-9_.-]*$`, unique across every scenario directory |
| `description`, `priority` (`P0`/`P1`/`P2`), `tags` | tags `^[a-z0-9][a-z0-9_.-]*$` from the vocabulary |
| `tier` | inferred from the directory right below `scenarios/` |
| `min_plan`, `requires`, `expect_failure_without`, `identities`, `org_level` | live only |
| `known_bug`, `fixed_in`, `observe`, `variables`, `libraries`, `timeout`, `cleanup` | see `docs/writing-scenarios.md` |
| `references` | the otterdog PRs (`pr: <n>`) or named changes (`change: <slug>`) behind the behaviour: `note`, `expected_deltas`, `base`, `template` ([conventions](conventions.md#references)) |

| Step key | Notes |
|---|---|
| `name`, `fragments`, `overlay`, `known_bug` | every tier |
| `validate` | `ok`, `errors`, `warnings_min`, `infos`/`infos_min` (need `verbose: true`), `exit_code`, `contains`, `not_contains` |
| `plan` | `expect`: `changes`, `noop`, `validation_error`, `error`, `any`; `counts`, `contains`, `not_contains`, `exit_code`, flags `repo_filter`, `update_secrets`, `update_webhooks`, `update_filter`, `only_secrets`, `verbose`; `null` skips plan, apply, converge |
| `apply`, `state`, `converge`, `on_missing_capability` | live only |
| `base_fragments`, `config`, `base_config`, `workspace`, `commands` | offline only |

Fragment keys: `settings`, `custom_properties`, `teams`, `secrets`, `variables`, `webhooks`, `rulesets`, `roles`,
`repositories`, `extra`. Each value is a string or a list of strings (jsonnet expressions of otterdog's template:
`orgs.newRepo`, `newOrgSecret`, `newRepoRuleset`, `newEnvironment`, ...), or a file entry `{file, raw, vars}`. A
fragment must not end with a `//` or `#` comment (the renderer appends a comma).

## State checks (live)

`{kind: <kind>, <parameters>, <one form>}`, kinds in `otterdog_e2e.scenarios.checks.CHECK_KINDS` and in the tables of
`docs/writing-scenarios.md` ("State checks"). Forms: `match: {...}` (subset), `absent: true|false`, `equals: <value>`,
`contains: [...]`, `unavailable: true`; operators `{$regex}`, `{$exists}`, `{$unordered}`, `{$len}` inside values. An
`absent: true` answered by an unavailable listing fails (add `unavailable_ok: true` when that is acceptable).

## Template variables

`{{ run }}`, `{{ p }}` (`e2e-<run>`), `{{ P }}` (`E2E_<RUN>`), `{{ hook_base }}`, `{{ org }}`, `{{ plan }}`,
`{{ app_slug }}`, `{{ app_id }}`, `{{ teams.admin }}`, `{{ teams.approval }}`, `{{ teams.contributors }}`, live only
`{{ logins.<role> }}` (the role listed in `identities`). Offline values are fixed (`run` is `spduo000`, `org` is
`e2e-offline`), so both differential sides render identical names. Unknown variables are load errors; write
`{% raw %}...{% endraw %}` for a literal `{{` in jsonnet.

## Files, libraries, overlays

```yaml
libraries:
  e2e: ../lib/e2e.libsonnet                       # relative to the scenario file, inside the project
steps:
  - name: create
    fragments:
      repositories:
        - file: ../fragments/environment-repo.jsonnet
          vars: {wait_timer: 5, branch_policies: [main]}
    overlay: {file: ../fragments/overlay-run-topics.jsonnet}
```

Files are Jinja-rendered like inline strings (`raw: true` inserts them as they are); insert numbers as they are and
everything else with `tojson`. Overlays merge settings (`settings+:`), never set `plan`, `description` or
`billing_email`, and a live overlay touching settings needs `org_level: true`. Paths of `../lib/...` depend on the
depth of the scenario file below `scenarios/`.

## Trying jsonnet before it becomes a scenario

```bash
.venv/bin/otterdog-e2e inject --fragment repositories=scenarios/fragments/repo-basic.jsonnet --print   # offline
```

`inject` runs offline by default (validate and local-plan with the SUT, `--sut`, `--plan`, `--var NAME=VALUE`,
`--library`, `--overlay`); with `--target` it is live: never without the user's request.
