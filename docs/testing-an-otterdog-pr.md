# Testing an otterdog pull request or a local checkout

The harness can test a proposed upstream pull request (pinned to the commit you reviewed) or your own checkout,
uncommitted changes included. It runs the regression tiers against it, runs the same observe-only scenarios on the
change and on its base, and reports which differences (deltas) were expected and which were not.

## What `otterdog-e2e pr` does

```bash
.venv/bin/otterdog-e2e pr 792 --sha d0d3b08...                 # offline tiers + differential, no GitHub org needed
.venv/bin/otterdog-e2e pr 792 --sha d0d3b08... --target free   # plus the live tiers on the test org
make pr PR=792 SHA=<40-hex> TARGET=free
```

`--sha` must be the full 40-hex commit. Get the current head with
`git ls-remote https://github.com/eclipse-csi/otterdog refs/pull/792/head` (or
`gh pr view 792 -R eclipse-csi/otterdog --json headRefOid -q .headRefOid`) and review it before running anything.

1. **Resolve** `pr:792@<sha>`: fetch `refs/pull/792/head` into the upstream mirror, check that the pin is the head or
   one of its ancestors, and export exactly the pin (a later push changes nothing). The PR must target
   eclipse-csi/otterdog. Its version is upstream's dynamic version of the pin, e.g. `1.7.0.dev19+e2e.gd0d3b08`, label
   `pr792-d0d3b08`.
2. **Trust**: a PR is untrusted. Its CLI and its webapp run only from its own docker image (built under the untrusted
   image namespace, never reused for trusted runs), with no network for offline commands, no capabilities and
   credentials only in a 0600 env-file. Resets, cleanups and PR-text guards use the trusted reset SUT
   (`release:latest`). Docker is therefore required.
3. **Select**: tags are derived from the changed files (`git diff` between the merge base and the pin, mapped by
   `otterdog_e2e.selection.PATH_RULES`; `smoke` always); the scenarios whose `references` name the PR (the change
   under test, `--change` to pick another one) are selected in addition. The offline tier always runs in full; the differential and live tiers run the selected
   scenarios.
4. **Run** the suites: `auto` (default) = `offline` and `differential`, plus `cli`, `webhooks`, `webapp` and
   `enterprise` when a target is given. `--suite` takes an explicit comma separated list.
5. **Compare**: the base SUT is the `base` the references of the PR declare, or `auto` (the merge base of the pin
   with the PR's base branch). Both sides record their observations; `differential.md` and `differential.json` classify every delta.
   `--strict-diff` fails the run on unexpected deltas.

Before the first test runs, the plugin resolves and installs every SUT the selected tests need, and builds the
images they need (`otterdog-e2e: preparing the head SUT (...)` lines), then builds the live session (verification and
the org lease). A cold install, an image build or a lease wait therefore never counts against the timeout of the
first test of a tier; live tests are timed on their test call only. The artifacts directory is printed at the end
(`pytest exit code N; artifacts: ...`), with the delta counts.

`--e2e-base-sut auto` needs a SUT with a merge base: `pr:`, `path:` and `dirty:` SUTs have one. A `sha:`, `tag:`,
`branch:` or `release:` SUT needs an explicit base, for example `--base-sut sha:<parent commit>`. Otherwise the
differential items fail with a message saying so.

### Running a PR's CLI on the host

Never by default. `--e2e-trust-code <sha>` (pytest option, from an interactive terminal only, refused when `CI` is
set) lets you install the untrusted CLI of exactly that commit on the host after you reviewed it, for debugging. It
is not a `run`/`pr` option; call pytest directly:

```bash
.venv/bin/python -m pytest tests/offline --e2e-sut pr:792@<40-hex> --e2e-trust-code <the same 40-hex>
```

## Local checkouts: `path:` and `dirty:`

```bash
# committed HEAD of a local otterdog checkout (the checkout is only read)
.venv/bin/otterdog-e2e run --sut path:../otterdog --base-sut auto --suite offline,differential

# HEAD plus uncommitted changes
.venv/bin/otterdog-e2e run --sut dirty:../otterdog --base-sut auto --suite offline,differential

# against the test org, compared with a release
.venv/bin/otterdog-e2e run --target free --sut dirty:../otterdog --base-sut tag:v1.6.1
```

- `auto` is the merge base of the checkout's `HEAD` with upstream main (the local commits are fetched into the
  mirror; the checkout is never modified).
- `dirty:` overlays the modified and untracked files of allowed paths only (`otterdog/**`, `tests/**`, `docs/**`,
  `examples/**`, `docker/**`, `dev/**`, `pyproject.toml`, `poetry.lock`, `README.md`, `CHANGELOG.md`, `mkdocs.yml`,
  `otterdog.sh`, `Makefile`) and never copies secrets or local state (`*.pem`, `*.key`, `.env*`, `values*.yaml`,
  `otterdog.json`, `otterdog.jsonnet`, `orgs/**`, `approot/**`, `github-app/**`, `.venv/**`, `*.sqlite`, ...).
  Labels: `local-<sha7>` and `local-<sha7>-dirty-<hash8>`; the version carries `.dirty.<hash8>`.
- Local SUTs are trusted (your own code): the CLI is installed on the host.
- The checkout is only read. Every git command on it runs with `GIT_OPTIONAL_LOCKS=0`, so even the index is not
  refreshed. Verified with a clean checkout (`dirty:` of a checkout without changes gives label `local-<sha7>`):
  `git status`, HEAD, refs, stash, the content hash of every file and the mtimes of `.git` and `.git/index` were
  identical before and after an offline run.

`run --change <N|#N|slug>` applies the references of a change to any SUT (default: N of a `pr:N@<sha>` SUT): the
scenarios referencing it pass `--tags`, their expected deltas classify the differential, their `base` becomes the
default `--base-sut` (which also adds the differential suite when no `--suite` is given) and their `template` picks
the templates. The pytest option is `--e2e-change` (environment fallback `E2E_CHANGE`); pytest needs the base
explicitly:

```bash
.venv/bin/otterdog-e2e run --target free --sut dirty:../otterdog \
  --change check-merge                                                 # base tag:v1.6.0 from the references

.venv/bin/python -m pytest tests/offline tests/differential \
  --e2e-sut dirty:../otterdog --e2e-base-sut tag:v1.6.0 --e2e-change check-merge
```

## Regression scenarios of unreleased fixes (`fixed_in`)

A regression scenario asserts the behaviour a fix introduced, so it fails on every SUT that predates the fix. Such a
scenario declares the first otterdog version containing the fix:

```yaml
id: regression.repo-ruleset-without-strict
fixed_in: "1.7.0.dev15"     # 9bdeb75 = v1.6.1 + 15 commits
```

The live engine (tiers `cli`, `enterprise`) and the offline engine skip the scenario when the SUT version is older
(PEP 440 order, local part ignored): `release:latest` (1.6.1) skips the #767, #790 and #791 regressions, while
`branch:main`, PR and local builds containing the fix run them. A differential run records the scenario on both sides
anyway, because the difference is the point. The version is a heuristic: a PR branched off an old main can have a
higher dev number without the fix. When ancestry matters, the offline tier decides with git
(`tests/offline/conftest.py` SutHistory), as O-VAL-RULESET-STRICT does.

Known bugs follow the same idea. A `scenarios/known_bugs.yaml` entry with `status: fixed` no longer turns its tests
into xfails: they guard against the regression. The exception is a SUT whose version predates a PEP 440 `fixed_in`;
there the xfail stays, with "SUT ... predates the fix" in its reason.

## Scenario references

Scenarios are organised by functionality, never by pull request: the tests of a PR extend the scenario of the
behaviour it changes (or add a generic one named after that behaviour), and the scenario records the PR, or the PRs
when the behaviour evolved several times, in its `references`. A YAML scenario has a top-level `references` list; a
Python test passes the same list as the `references` keyword of its `pytest.mark.scenario(...)` marker (a literal or a
module constant). With an AI agent, the `otterdog-pr-tests` skill finds the scenarios of the PR from
`otterdog-e2e assist pr-context`, extends them, runs the offline and differential tiers on the pinned PR in docker
and explains every delta for your review ([ai-assistance.md](ai-assistance.md)).

| Key | Default | Meaning |
|---|---|---|
| `pr` | one of `pr`/`change` | eclipse-csi/otterdog pull request number |
| `change` | one of `pr`/`change` | slug of a named change without upstream PR (e.g. a maintainer branch: `check-merge`) |
| `note` | `""` | what the change did to this behaviour (known-bad version, evidence, what must not change) |
| `expected_deltas` | `[]` | deltas the change causes in THIS scenario between base and head (below) |
| `base` | `null` | differential base of the change (a release, tag, branch or sha spec; default: the merge base) |
| `template` | `own` | `own` (each side vendors its own `examples/template`), `head` or `base` (both sides use that side's template), to separate code changes from template changes |

The scenario model validates the references (unknown keys, types, a step pattern that matches no step of the
scenario, a `step` in a Python test, duplicates); two references of one change with different `base` or `template`
values are a collection error, so declare them once per change. `assist check` and the unit tests also refuse a
scenario id or file name that carries the number of a PR it references.

An expected delta is a mapping `{step, kind, key, note}` (fnmatch patterns, unset fields match anything, the scenario
is the referencing one; a key also matches without its `#n` repetition suffix). Observations of CLI commands have
`kind: cli` and the command as key (`validate`, `local-plan`, `show`, `show-default`, `canonical-diff`,
`list-projects`, `version`; live: `validate`, `plan`). A change is selected with `--change` (`run`, `pr`), pytest
`--e2e-change` or `E2E_CHANGE`; by default it is N of a `pr:N@<sha>` SUT, and `pr N` uses N.

Abridged from the repository:

```yaml
# scenarios/offline/validation/val-ruleset-strict.yaml
id: O-VAL-RULESET-STRICT
references:
  - pr: 790
    note: squash commit 9bdeb75; base = its first parent, so the delta is #790 alone
    base: sha:b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8
    template: own
    expected_deltas:
      - step: no-strict
        kind: cli
        key: validate
        note: head reports the missing required_status_checks.strict as a validation error; base failed at apply time
      - step: no-strict
        kind: cli
        key: local-plan
        note: head aborts local-plan on the validation error; base planned the ruleset

# scenarios/offline/validation/val-org-ruleset-strict.yaml: referenced WITHOUT expected delta (head crashes, KB-008)
id: O-VAL-ORG-RULESET-STRICT
references:
  - pr: 790
    note: the crash introduced by #790 must stay an unexpected delta until it is fixed
```

```python
# tests/webapp/test_stale_status.py (W-PR-STALE-SNAPSHOT) and tests/webapp/test_check_merge.py (W-CMD-CHECK-MERGE)
@pytest.mark.scenario("W-PR-STALE-SNAPSHOT", priority="P1", references=REFERENCES)  # {pr: 792, expected_deltas: ...}
@pytest.mark.scenario("W-CMD-CHECK-MERGE", priority="P2", references=CHECK_MERGE_REFERENCES)  # {change: check-merge, base: tag:v1.6.0}
```

The differential proof of concept of #790 needs no GitHub organization at all:

```bash
.venv/bin/otterdog-e2e run --sut sha:9bdeb75 --change 790 --suite offline,differential   # base sha:b5f7bb1 from the references
```

With warm caches it takes 15 to 30 minutes (the offline tier of the head runs first). The verified outcome is 388
passed, 8 skipped and 30 xfailed (registered known bugs), with `differential: 1 unexpected, 2 expected delta(s)`:

- expected: `O-VAL-RULESET-STRICT / no-strict / cli / validate` goes from exit 0 `Validation succeeded` to exit 1 `has not set
  required parameter 'required_status_checks.strict'`, and `.../local-plan` goes from `Plan: 2 to add` to an abort
  with exit 1;
- unexpected: `O-VAL-ORG-RULESET-STRICT / org-no-strict / cli / validate` goes from exit 0 to exit 2 `'GitHubOrganization'
  object has no attribute 'get_model_header'`. This is a defect #790 introduced (KB-008), and the report keeps
  flagging it until upstream fixes it, so `--strict-diff` fails this run;
- the other 696 observations of the 59 observed scenarios are unchanged, for example O-VAL-SYNTAX, whose jsonnet
  error prints a different workspace path on each side.

Check the references of the scenarios you changed with `.venv/bin/otterdog-e2e assist check <files>`.

## Reading the differential report

`differential.md` (also appended to the CI job summary) contains:

1. a verdict and the counts: unexpected deltas, expected deltas, unchanged observations, not comparable scenarios,
   expected deltas not observed;
2. a scenario table (unchanged, expected, unexpected, result);
3. **Unexpected deltas**: one collapsible block per (scenario, step, kind, key) with a unified diff of the normalized
   base and head outputs: regressions, or behaviour changes a reference should declare;
4. **Expected deltas**: changes matched by `expected_deltas`, with their note;
5. **Expected deltas not observed**: declared deltas that did not happen (the fix may not work, or the scenario did not
   run);
6. **Not comparable**: scenarios recorded on one side only (for example a scenario that crashed on one side).

The last item of the differential tier fails when an expected delta of the change concerns a scenario recorded on
both sides but did not happen: the PR does not change what it claims to change.

Outputs are normalized before the comparison (ANSI codes, boxes, progress bars, scratch paths, each side's workspace
root as `<WORKSPACE>` (also the `/ws` mount of a docker side), run ids, shas, timestamps, durations, the printed
versions and the values of the Python sets two validation messages print in a hash-dependent order, KB-038), so only
behaviour differences remain. Every observation is in `observations/base.jsonl` and
`observations/head.jsonl`.

`summary.md` also has a **Manual testing** block (organization, plan, CLI commands run, webapp flows, webhook
interactions) in the shape of otterdog's pull request template, ready to paste into the PR description. Commands
that ran without GitHub access (offline tiers, `--local`, network sandbox) are not listed as live CLI testing; they
are only counted ("plus N offline command(s) without GitHub access"). "How to reproduce" quotes the `otterdog-e2e
run|pr` command of the run.

## In CI

```bash
gh workflow run e2e-otterdog-pr.yml --repo <owner>/otterdog-e2e --ref main \
  -f pr=792 -f sha=<40-hex> -f target=free

# several test organizations: one job per instance, each approved separately
gh workflow run e2e-otterdog-pr.yml --repo <owner>/otterdog-e2e --ref main \
  -f pr=792 -f sha=<40-hex> -f target=free,acme-a
```

`target` is one instance or a comma separated list of at most 8 instances (spaces ignored, duplicates dropped). An
instance is a test organization with its environments `e2e-<instance>` and `e2e-<instance>-untrusted`
([security.md](security.md#ci-environments)); every instance must be in the repository variable `E2E_INSTANCES`
(while it is unset: `E2E_TARGETS`, else `free`, `team` and `enterprise`).

1. `resolve` (no secrets) checks `pr` (`^[0-9]{1,7}$`), `sha` (`^[0-9a-f]{40}$`), each instance (name
   `^[a-z0-9][a-z0-9-]{0,38}$`, no `-untrusted` or `-webui` suffix, in the allowlist) and the suites, and, with the
   GitHub API, that the PR targets eclipse-csi/otterdog and that the sha is its head or an ancestor of it. It calls
   `e2e.yml` once with the validated comma separated list.
2. `e2e.yml` validates the instances again, classifies `pr:<n>@<sha>` (untrusted) and writes the review block to the
   job summary: PR title (as a code span), author, head repository, pinned sha versus current head, number of changed
   files, the changed build or template files (`pyproject.toml`, `poetry.lock`, `docker/*`, Dockerfiles,
   `examples/template/*`) and the instances.
3. One `e2e` job per instance waits for an approval of its `e2e-<instance>-untrusted` environment. **Review the PR at
   the pinned sha and the classify summary before approving**: once approved, the PR code runs with the credentials of
   that test organization. The jobs of the other instances keep running when one fails.
4. Each job checks that its environment configures the instance (an environment that does not exist is created by
   GitHub on the fly, unprotected: the job then fails before any SUT code runs), runs
   `otterdog-e2e pr <n> --sha <sha> --target <instance> --suite auto` in the lane `pr-fast`, sweeps its run
   (`janitor --run-id`), scrubs and uploads the artifacts (7 days).

## Triggering from an otterdog pull request

A maintainer can start the run from the PR with a `/e2e` comment (instance `free`), `/e2e <instance>` or
`/e2e <instance>,<instance>` (several test organizations). The trigger lives in eclipse-csi/otterdog and uses
a dedicated GitHub App whose only permission is **Actions: write** (plus the mandatory metadata read), installed only
on the e2e repository: it can dispatch workflows there and do nothing else (no contents access, so a leaked token
cannot change the e2e workflows). The head sha is read from the API when the comment is handled.

```yaml
# eclipse-csi/otterdog: .github/workflows/e2e-trigger.yml
name: e2e trigger

on:
  issue_comment:
    types: [created]

permissions: {}

jobs:
  dispatch:
    # "/e2e" or "/e2e <instance>[,<instance>...]" on a pull request, by an owner or member of the organization
    if: >-
      github.event.issue.pull_request &&
      startsWith(github.event.comment.body, '/e2e') &&
      contains(fromJSON('["OWNER", "MEMBER"]'), github.event.comment.author_association)
    runs-on: ubuntu-24.04
    timeout-minutes: 5
    permissions:
      pull-requests: read
    steps:
      - name: Mint a token that can only dispatch workflows of the e2e repository
        id: token
        # pin to the full commit sha of a release you reviewed
        uses: actions/create-github-app-token@<40-hex sha> # vX.Y.Z
        with:
          app-id: ${{ vars.E2E_TRIGGER_APP_ID }}
          private-key: ${{ secrets.E2E_TRIGGER_APP_PRIVATE_KEY }}
          owner: <e2e repository owner>
          repositories: otterdog-e2e
          permission-actions: write
      - name: Dispatch e2e-otterdog-pr.yml
        env:
          GH_TOKEN: ${{ steps.token.outputs.token }}
          UPSTREAM_TOKEN: ${{ github.token }}
          E2E_REPO: <e2e repository owner>/otterdog-e2e
          PR: ${{ github.event.issue.number }}
          BODY: ${{ github.event.comment.body }}
        run: |
          set -euo pipefail
          sha="$(GH_TOKEN="$UPSTREAM_TOKEN" gh api "repos/$GITHUB_REPOSITORY/pulls/$PR" --jq .head.sha)"
          # one instance or a comma separated list; e2e-otterdog-pr.yml validates each one against its allowlist
          target=free
          if [[ "$BODY" =~ ^/e2e[[:space:]]+([a-z0-9][a-z0-9,-]{0,200})[[:space:]]*$ ]]; then
            target="${BASH_REMATCH[1]}"
          elif [[ ! "$BODY" =~ ^/e2e[[:space:]]*$ ]]; then
            echo "::error::usage: /e2e or /e2e <instance>[,<instance>...]"
            exit 1
          fi
          gh workflow run e2e-otterdog-pr.yml --repo "$E2E_REPO" --ref main \
            -f pr="$PR" -f sha="$sha" -f target="$target"
          echo "dispatched the e2e run of #$PR at \`$sha\` on \`$target\`" >> "$GITHUB_STEP_SUMMARY"
```

Notes:

- `issue_comment` runs the workflow of the default branch; it never checks out the PR, and the comment reaches the
  script only through `env:` and a regular expression (lower case letters, digits, `-` and `,` only: a comment with
  other arguments fails instead of falling back to `free`); the e2e repository decides which instances exist
  (`E2E_INSTANCES`), so the trigger needs no list of them;
- the dispatch targets `main` of the e2e repository, where the environment protections apply; the run still waits for
  an environment approval in the e2e repository;
- the e2e run does not comment back on the otterdog PR (it holds no token for that): link the run, or paste the
  Manual testing block of `summary.md` into the PR.
