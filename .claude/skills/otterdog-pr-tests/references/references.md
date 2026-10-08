# Scenario references and the differential report

Reference: `docs/testing-an-otterdog-pr.md` ("Scenario references", "Reading the differential report"); parser and
loader `src/otterdog_e2e/changes.py`, model `src/otterdog_e2e/scenarios/model.py`.

## Organisation: by functionality, never by PR

A PR changes a behaviour; the test of that behaviour is the scenario of the functionality (`O-VAL-RULESET-STRICT`,
`regression.user-bypass-actors`, `W-PR-STALE-SNAPSHOT`), never a scenario, file or directory named after the PR. The
PR is recorded in the `references` of the scenarios it changes; when the behaviour changes again, the next PR is
appended to the same list. `assist check` and the unit tests refuse an id or file name carrying a referenced PR number.

## The `references` field

YAML scenarios: a top-level `references` list. Python tests: the `references` keyword of the scenario marker, a
literal (or a module constant), e.g. `@pytest.mark.scenario("W-PR-STALE-SNAPSHOT", priority="P1", references=REFS)`.

| Key | Default | Meaning |
|---|---|---|
| `pr` | one of `pr`/`change` | eclipse-csi/otterdog pull request number |
| `change` | one of `pr`/`change` | slug of a named change without upstream PR (a maintainer branch), e.g. `check-merge` |
| `note` | `""` | what the change did to this behaviour, the known-bad version, what must not change |
| `expected_deltas` | `[]` | deltas the change causes in THIS scenario between base and head (below) |
| `base` | `null` | differential base of the change (`sha:<hex>`, `tag:v1.6.1`, `branch:main`, `release:latest`; never `pr:` or `dirty:`); default: the merge base of the pin (`--base-sut auto`) |
| `template` | `own` | `own` (each side vendors its own `examples/template`), `head` or `base` (both sides use that side's template) |

The model refuses unknown keys, wrong types, a step pattern matching no step of the scenario, a `step` in a Python
test, duplicate changes or deltas; two references of one change with different `base` or `template` values are an
error at collection. Declare `base`/`template` once per change (the other references may leave them out).

```yaml
# scenarios/offline/rulesets/val-ruleset-strict.yaml (abridged)
id: O-VAL-RULESET-STRICT
references:
  - pr: 790
    note: >-
      "fix: validate required status checks of rulesets", squash commit 9bdeb75; base = its first parent b5f7bb1, so
      the delta is #790 alone; step with-strict must not change
    base: sha:b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8
    template: own
    expected_deltas:
      - step: no-strict
        kind: cli
        key: validate
        note: >-
          head reports "has not set required parameter 'required_status_checks.strict'" (exit 1); base validated it
```

A variant the PR breaks is referenced without an expected delta (`O-VAL-ORG-RULESET-STRICT`: head crashes, KB-008),
so the report keeps flagging it as unexpected. A PR that should change nothing observable needs no expected delta: run
with `--base-sut auto` and report that no delta was expected.

## Selecting a change

`otterdog-e2e run --change <n|#n|slug>` (pytest `--e2e-change`, `E2E_CHANGE`); default: N of a `pr:N@<sha>` SUT, and
`otterdog-e2e pr N` uses N. The scenarios referencing the change pass the `--tags` filter, their expected deltas feed
`differential.md`, their `base` is the default `--base-sut` and their `template` picks the templates.

## Expected deltas

A mapping `{step, kind, key, note}` (fnmatch patterns, the scenario is the referencing one; unset fields match
anything; a key also matches without its `#n` repetition suffix). Be as precise as the evidence allows: a delta
without step, kind and key hides every other change of that scenario, including a regression.

Observation coordinates: `scenario` (id), `step` (step name), `kind` (`cli` for CLI commands), `key` (the command:
`validate`, `local-plan`, `show`, `show-default`, `canonical-diff`, `list-projects`, `version`; live observations:
`validate`, `plan`). Offline scenarios with `observe: true` are recorded on both sides (all of them in a `run` without
`--tags`); live observations need a target and are not part of this skill.

Notes are factual and short: "head <what it prints or returns>; base <what it did>", with exit codes. Never copy the
PR description as a note.

## Reading `differential.md`

1. verdict and counts (unexpected, expected, unchanged, not comparable, expected not observed);
2. a scenario table;
3. **Unexpected deltas**: one block per (scenario, step, kind, key) with a unified diff of the normalized base and
   head outputs. Either the intended change (declare it) or a regression (report it, draft a known bug);
4. **Expected deltas**: matched by the references of the change, with their note;
5. **Expected deltas not observed**: the fix may not work, the scenario may not exercise it, or it did not run (the
   differential tier's last item fails on a scenario recorded on both sides);
6. **Not comparable**: recorded on one side only (a crash or a skip on one side: look at `summary.md`).

Outputs are normalized before the comparison (ANSI codes, boxes, scratch paths, workspace roots, run ids, shas,
timestamps, durations, versions, hash-ordered sets of KB-038), so a remaining delta is a behaviour difference or a
normalization gap. Raw recordings: `observations/base.jsonl`, `observations/head.jsonl`; command outputs of each side
under the run directory (`base/`, `head/`).

## Reproducing a delta by hand

The scenario and its rendered configuration are in the artifacts (`.../workspace/`); `otterdog-e2e inject` re-runs
jsonnet against a SUT offline, for example with the base:

```bash
.venv/bin/otterdog-e2e inject --sut sha:b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8 \
  --library e2e=scenarios/lib/e2e.libsonnet --fragment repositories=scenarios/fragments/ruleset-repo.jsonnet --print
```

Write a reproduction fragment of your own to a scratch file when no shared fragment fits (dummy secrets and
run-prefixed names apply there too), and delete it afterwards.

## The live command for the user

The full PR run (offline tiers, differential, and the live tiers on a test organization they own) is theirs to start:

```bash
.venv/bin/otterdog-e2e pr 790 --sha 0cee9e302282fefa092b4e0767248a997a9272ea --target free
make pr PR=790 SHA=0cee9e302282fefa092b4e0767248a997a9272ea TARGET=free
```

In CI: `gh workflow run e2e-otterdog-pr.yml` with `-f pr=<n> -f sha=<40-hex> -f target=<instance>`, approved by a
human in the untrusted environment after reviewing the pinned commit.
