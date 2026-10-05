# Local development

## Setup

```bash
make init          # poetry install --with dev: .venv with the harness, pytest, ruff, mypy
make check         # ruff check, ruff format --check, mypy, unit tier
```

`poetry.toml` keeps the virtualenv in `.venv/`; every Makefile target and workflow calls `.venv/bin/otterdog-e2e`.

### `OTTERDOG_CONFIG_ROOT` pitfall

Without `-c`, otterdog looks for `otterdog.jsonnet` or `otterdog.json` in `$OTTERDOG_CONFIG_ROOT` (default: the
current directory). If your shell exports it for your real configurations (the Eclipse Foundation ones, for
example), an otterdog command you replay by hand would act on real organizations with their credentials.

- The harness always passes `-c <workspace>/otterdog.json` and removes every `OTTER*` variable from the processes it
  starts; the Makefile `unexport`s `OTTERDOG_CONFIG_ROOT`.
- Unset it in every shell used for e2e work (`unset OTTERDOG_CONFIG_ROOT`, or `env -u OTTERDOG_CONFIG_ROOT <command>`),
  and when you replay a command from `artifacts/<run>/cli/<seq>-<command>/cmd.txt`, keep its `-c`.

## Makefile

| Target | What |
|---|---|
| `help` | list targets and variables |
| `init`, `check`, `unit`, `lint`, `format`, `typecheck` | development |
| `offline` | offline tier of `SUT` (default `release:latest`) |
| `lint-scenarios` | only the offline lint of every live scenario step (`run --suite offline -k lint`): run it before submitting a live scenario |
| `inject ARGS='--fragment KIND=FILE ...'` | `otterdog-e2e inject` with `SUT` (offline; live with `TARGET`) |
| `cli`, `webhooks`, `webapp`, `enterprise` | one live tier on `TARGET` (several instances: `TARGET=a,b`, `@all` or `@<list>`, and `PARALLEL=<n>`) |
| `web-ui` | the web-UI tier on `TARGET` (`--suite web_ui --allow-web-ui`: the admin bot logs in, see below) |
| `differential` | offline (+ live with `TARGET`) differential of `SUT` against `BASE_SUT` |
| `e2e` | every tier (live ones skip without `TARGET`) |
| `one SCENARIO=<glob>` | only matching scenarios (comma separated globs) |
| `pr PR=<n> SHA=<sha>` | `otterdog-e2e pr` |
| `setup [FROM=<instance>] [PROFILE=<profile>]` | interactive onboarding of the instance `TARGET` (`--from`, `--profile`; [onboarding.md](onboarding.md)) |
| `ci-sync [REVIEWER=<login>] [NIGHTLY=1] [APPLY=1]` | the GitHub environments, variables and secrets of the instance `TARGET` (dry run without `APPLY`; `--reviewer`, `--nightly`) |
| `targets` | the instances (`~/.config/otterdog-e2e/<instance>.env`) and the profiles of `targets/` |
| `doctor`, `bootstrap [APPLY=1] [WAIT=1]`, `janitor [APPLY=1] [OLDER_THAN=6h] [RUN_ID=<id>]` | org operations on `TARGET` (`doctor` and `janitor` accept several instances; `WAIT=1` needs `APPLY=1`) |
| `relay [FORWARD_TO=<url>] [SINCE=10m]` | standalone delivery relay |
| `report [RUN=<dir>]`, `scrub [RUN=<dir>]` | summary / scrub of a run (default: the newest run) |
| `cache-prune [KEEP=3]`, `sut` | cache maintenance, resolve `SUT` |
| `clean` | Python caches (never artifacts nor the harness cache) |
| `docs`, `docs-serve` | strict build of the documentation site into `site/`, live preview (see [Documentation site](#documentation-site)) |

`ARGS` passes extra pytest arguments, e.g. `make cli TARGET=free ARGS='-x -k lifecycle'` (options that could change
the SUT, load plugins or show locals are refused). `TARGET` (default `$E2E_TARGET`) names an instance or a profile:
[onboarding.md](onboarding.md#instances-and-profiles).

## Common workflows

```bash
# a scenario you are writing, offline then live
make one SCENARIO='offline.my.*'
make one SCENARIO='cli.my.*' TARGET=free

# keep the resources and the scratch directory of a failing session for inspection
.venv/bin/otterdog-e2e run --target free --scenario 'cli.my.*' --keep
# ... then sweep exactly that run
make janitor TARGET=free RUN_ID=<run id> APPLY=1

# skip the baseline reset when iterating (the org must already be at the baseline)
.venv/bin/otterdog-e2e run --target free --scenario 'cli.my.*' --no-reset

# your otterdog checkout, uncommitted changes included, compared with its merge base
.venv/bin/otterdog-e2e run --sut dirty:../otterdog --base-sut auto --suite offline,differential

# a webapp image you built yourself
.venv/bin/otterdog-e2e run --target free --suite webapp --webapp-image ghcr.io/eclipse-csi/otterdog:local

# jsonnet files tried without a scenario (offline; --target for a live plan): see "Ad-hoc injection"
.venv/bin/otterdog-e2e inject --fragment repositories=scenarios/fragments/repo-basic.jsonnet --print

# the offline lint of every live scenario step (validate --local with the SUT)
make lint-scenarios        # = .venv/bin/otterdog-e2e run --suite offline --sut release:latest -k lint
```

`otterdog-e2e run` without `--suite` runs `offline`, `cli`, `webhooks`, `webapp` and `enterprise`, plus `differential`
with `--base-sut` and `web_ui` with `--allow-web-ui`.

`otterdog-e2e -v ...` / `-vv ...` log at INFO/DEBUG (redacted). `otterdog-e2e sut resolve SPEC` shows what a spec
resolves to (label, sha, version, trust, base sha, changed files). `python -m otterdog_e2e` is the same command line
as `.venv/bin/otterdog-e2e` (`.venv/bin/python -m otterdog_e2e doctor --target free`): batch runs start their
children as `python -P -m otterdog_e2e`, with the interpreter of the parent (`-P`: an `otterdog_e2e` package in the
current directory is never imported).

## Several targets

`otterdog-e2e targets` (`make targets`) lists the instances: every `~/.config/otterdog-e2e/<instance>.env` and every
profile of `targets/`, with its profile, organization and env file, and a `problem:` line for an instance that cannot
be loaded (read-only, no network; `--json` for scripts).

`run`, `pr`, `doctor` and `janitor` accept several targets: a comma list or a repeated `--target`, `@all` (every
instance with an env file) or `@<list>` (the file `~/.config/otterdog-e2e/lists/<list>`, one instance per line, `#`
comments). Details and rules: [onboarding.md](onboarding.md#running-on-one-organization-or-a-list).

```bash
.venv/bin/otterdog-e2e targets
.venv/bin/otterdog-e2e run --target free,acme-a --suite cli --scenario 'cli.my.*'   # one child process per target
.venv/bin/otterdog-e2e run --target @all --suite cli --parallel 2 --fail-fast        # distinct orgs, at most 2 at once
.venv/bin/otterdog-e2e doctor --target @all --json                                  # a JSON list, one entry per target
make cli TARGET=free,acme-a PARALLEL=2
make report RUN=artifacts/<run id>                                                   # one target's own report
```

- Each target runs in a child process (`python -P -m otterdog_e2e run --target=<instance> --run-id=<id> ...`, after
  the `-v`/`-vv` of the batch command) with its own run id and artifacts directory; every line it prints is prefixed
  with `[<instance>] `. `--run-id` is refused with several targets; janitor children get none (they sweep under a
  run id of their own) and their lines show none.
- With several targets an exported `E2E_ORG`, `E2E_ORG_ID` or `E2E_PROFILE` is refused, and so is an exported login
  (`*_LOGIN`) or secret variable that an instance's env file sets to another value (the message names the variables
  only): the exported value would serve every target. Unset them, or give one target.
- The batch writes `<artifacts>/batch-<id>.md` and `.json` (one row per target: instance, profile, org, run id, exit
  code, duration, results, the command reproducing it) and one redacted log per target,
  `<artifacts>/batch-<id>-<instance>.log`.
- The exit code is 0 only when every target passed, else the most severe child code (3 > 2 > 4 > 1 > 5).
- Sequential by default; `--parallel N`: distinct organizations only, and distinct webapp URLs for `external`
  transport targets; each relay webapp without a pinned `E2E_WEBAPP_PORT` gets a free loopback port, sessions testing
  the same SUT build its webapp image once. `--fail-fast` starts no further target after a failure.
- Ctrl-C (or SIGTERM) reaches every running child, which cleans up (sweep, lease release) before it exits; no
  further target starts. Every command treats the first SIGTERM like Ctrl-C and ignores a second one during its
  cleanup.
- pytest called directly (`--e2e-target`, `E2E_TARGET`) takes one target: a list is refused when live tests are
  selected.

Before the first test, the session prepares every SUT and image the selected tests need. It prints
`otterdog-e2e: preparing the head SUT (<spec>) ...` and records the durations in `run.json` (`sut_prepare_seconds`).
Measured on a warm cache: 1-6 s per SUT install check and 25 s for a new webapp image whose dependency layers were
cached. The first install of a SUT (cold mirror and poetry cache) took 17 s in wave 2. Cold image builds take
minutes, but no item timeout is spent on them.

`pytest --collect-only` sessions leave no artifacts directory, and `-p no:timeout` keeps working (the plugin
registers the `timeout` marker when pytest-timeout is disabled).

## The web-UI tier locally

The web-UI tier (`tests/web_ui`, [web-ui-testing.md](web-ui-testing.md)) lets otterdog log in to github.com as the
admin bot of the target (password and TOTP seed). Prepare the bot once as described there (authenticator-app 2FA,
setup key stored), put `E2E_ADMIN_PASSWORD` and `E2E_ADMIN_TOTP_SEED` in `~/.config/otterdog-e2e/<instance>.env`
(chmod 600; `setup --target <instance> --rotate web` asks for both), then:

```bash
.venv/bin/otterdog-e2e doctor --target free          # web:* rows: credentials, seed, 2FA, browser, login gate (never logs in)
make web-ui TARGET=free                              # = otterdog-e2e run --target free --suite web_ui --allow-web-ui
make web-ui TARGET=free SUT=branch:main ARGS='-k round_trip'
.venv/bin/otterdog-e2e run --target free --suite web_ui --allow-web-ui --scenario webui.settings.round-trip
# your otterdog checkout (dirty: and path: SUTs are trusted locally; CI runs only released or upstream SUTs)
.venv/bin/otterdog-e2e run --target free --sut dirty:../otterdog --suite web_ui --allow-web-ui
# the bot's browser session: a visible window that closes at once (a display is needed)
E2E_WEB_LOGIN=1 .venv/bin/otterdog-e2e run --target free --suite web_ui --allow-web-ui --scenario webui.cmd.web-login
```

- Nothing logs in without `--allow-web-ui` (or `E2E_ALLOW_WEB_UI=1` in the process environment): every web test then
  skips with the reason, like the tests of an untrusted SUT (`pr:`, an untrusted `sha:`).
- One web login at a time per machine, at least 32 s apart (`E2E_WEB_LOGIN_SPACING`): a tier run takes 15 to 25
  minutes. Never run the tier of one target from CI and from your workstation at the same time (same bot, same TOTP
  codes).
- The first session installs Playwright Firefox into `$E2E_CACHE_DIR/ms-playwright`; its system libraries need root
  once: `sudo <the SUT venv>/bin/python -m playwright install-deps firefox`.
- After a blocking login failure (wrong password, TOTP refused, a challenge) the gate blocks further logins: sign in
  as the bot in a browser, fix the cause, then delete `$E2E_CACHE_DIR/webui/<login>.json` (`doctor` names it).
- `summary.md` shows the web logins and the time spent waiting for the gate in its run table (`Web UI`), and
  `artifacts/<run>/webui/*.json` the evidence of each scenario (round trip values, restore result).

## Ad-hoc injection

`otterdog-e2e inject` runs jsonnet files through otterdog without writing a scenario. It builds a one-step scenario
from the files ([writing-scenarios.md](writing-scenarios.md#injecting-jsonnet-from-files)) in the run's scratch
directory (`$E2E_CACHE_DIR/run/<run>/adhoc/scenario.yaml`), checks it with every scenario rule (no import statements,
dummy secrets, offline restrictions, Jinja: errors name `<file>:<line>` and stop before any session starts), then
runs `tests/adhoc/` with pytest (the module only runs when `E2E_ADHOC_SCENARIO` names that file) with the regular
fixtures and safety. The files may lie anywhere; they are Jinja-rendered like scenario files (`{{ p }}` and
`{{ P }}` are the run prefixes, `{{ hook_base }}` the webhook base, plus `--var`).

| Option | Meaning |
|---|---|
| `--fragment KIND=FILE` | a fragment file of KIND: `repositories`, `settings`, `secrets`, `variables`, `webhooks`, `rulesets`, `roles`, `custom_properties`, `teams`, `extra` (repeatable) |
| `--library NAME=FILE` | a library, inlined as `local NAME = (...);` after the template import (repeatable, in order) |
| `--overlay FILE` | an object mixin applied after both layers (repeatable, in order) |
| `--config FILE` | offline: a complete organization configuration instead of the rendered one (Jinja variables `import_path`, `project`, `org`, `plan`) |
| `--base FILE` | offline: the `-BASE` configuration of `local-plan` (default: the bare offline organization) |
| `--plan PLAN` | `free`, `team` or `enterprise` rendered into `settings.plan` (the offline organization's plan; live: plan-gated validation, like `variables.plan`) |
| `--var NAME=VALUE` | a Jinja variable of the files, VALUE parsed as YAML (`5`, `'[main, release/*]'`, `text`) (repeatable) |
| `--offline` | offline mode, the default without `--target` (`E2E_TARGET` never switches to live mode) |
| `--target T` | live mode on the test organization: validate and plan only |
| `--apply` | live: also apply, converge and clean up |
| `--keep` | no cleanup: live objects stay (the janitor sweeps the run later) and the scratch directory is kept |
| `--no-reset` | live: skip the baseline reset at session start |
| `--print` | print the rendered configuration after the run |
| `--sut`, `--reset-sut`, `--run-id`, `--artifacts` | as for `run` |

Modes:

- **offline** (default): the organization `e2e-offline` with the SUT's template, network blocked: `validate --local`
  (must succeed), `local-plan --local` against `--base` or the bare organization, `show --local`;
- **live, plan only** (`--target`): the session takes the org lease and resets the baseline (unless `--no-reset`), then
  renders the baseline plus the files and runs `validate` (must succeed) and `plan`. Live injections are `org_level`:
  the plan is not filtered by `-r`, so every change of the injected content shows. Nothing is applied;
- **live apply** (`--target --apply`): a first plan-only pass refuses the injection when its plan adds objects without
  this run's prefix (the guarded cleanup could never remove them: name objects with `{{ p }}`, `{{ P }}` or
  `{{ hook_base }}`); then the plan must show changes, `apply -f -n` runs (a plan that would change the org
  description is refused), converge, and the cleanup: a full baseline reset with the trusted reset CLI, whose
  removals are guarded (only objects of this run).

After pytest's own output the command prints where the rendered configuration is, the validation and plan summaries
and the result; its exit code is pytest's (a file breaking a rule exits 1 before any session, a usage error 2):

```text
otterdog-e2e inject (offline): artifacts .../artifacts/<run>
rendered config: .../artifacts/<run>/adhoc/workspace/e2e-offline.jsonnet.txt
BASE config: .../artifacts/<run>/adhoc/workspace/e2e-offline.jsonnet-BASE.txt
validate: ok (0 error(s), 0 warning(s))
local-plan: Plan: 4 to add, 0 to change, 0 to delete. (exit code 0)
  + add org_variable[name="E2E_SPDUO000_INJECTED"]
  + add repository[name="e2e-spduo000-basic"]
  + add repository[name="e2e-spduo000-rules"]
  + add repo_ruleset[name="e2e-spduo000-main", repository=e2e-spduo000-rules]
result: passed
```

`<artifacts>/<run>/adhoc/` also holds `result.json` (the same summaries), `scenario.yaml.txt` (the generated scenario)
and, offline, the CLI outputs (`adhoc/cli/`); live commands write to `cli/` as usual. The rendered configuration of a
live injection contains the test organization's profile (billing email included): it stays in your local artifacts.

Recipes (from the project root, `OTTERDOG_CONFIG_ROOT` unset):

```bash
# a repository fragment, validated and planned offline with the latest release
.venv/bin/otterdog-e2e inject --fragment repositories=scenarios/fragments/repo-basic.jsonnet

# a library and a fragment using it, with upstream main, printing the rendered configuration
.venv/bin/otterdog-e2e inject --sut branch:main --library e2e=scenarios/lib/e2e.libsonnet \
  --fragment repositories=scenarios/fragments/ruleset-repo.jsonnet --print

# the vars of a scenario file become --var options
.venv/bin/otterdog-e2e inject --library e2e=scenarios/lib/e2e.libsonnet \
  --fragment repositories=scenarios/fragments/environment-repo.jsonnet --var wait_timer=5 --var 'branch_policies=[main]'

# an organization variable and an overlay
.venv/bin/otterdog-e2e inject --fragment variables=scenarios/fragments/org-variable.jsonnet \
  --fragment repositories=scenarios/fragments/repo-basic.jsonnet --overlay scenarios/fragments/overlay-run-topics.jsonnet

# an enterprise-only feature, offline
.venv/bin/otterdog-e2e inject --plan enterprise --fragment rulesets=my-org-ruleset.jsonnet

# a complete configuration, planned against another one (local-plan: BASE -> config)
.venv/bin/otterdog-e2e inject --config scenarios/fragments/offline-config.jsonnet --base my-previous-config.jsonnet

# your otterdog checkout, uncommitted changes included
.venv/bin/otterdog-e2e inject --sut dirty:../otterdog --fragment repositories=my-repo.jsonnet

# live: validate and plan on the test organization, then apply and clean up
.venv/bin/otterdog-e2e inject --target free --fragment variables=scenarios/fragments/org-variable.jsonnet
.venv/bin/otterdog-e2e inject --target free --apply --fragment repositories=scenarios/fragments/repo-basic.jsonnet
```

Teams and `code_scanning_default_languages` are refused offline (their validation calls GitHub; languages beside
`code_scanning_default_setup_enabled: false` are fine): inject them with a target. When an injection works, turn it into a scenario: the same files become `{file: ...}` entries.

## Artifacts and debugging

Each session prints its artifacts directory (`<E2E_ARTIFACTS>/<run_id>/`, default `./artifacts/<run_id>/`):

- `summary.md`: start here (failures, skips by reason, known bugs, the coverage matrix with the features the run
  exercised, budgets, differential summary);
- `results.jsonl`: one line per test, including the skip reason and a short redacted failure;
- `cli/<seq>-<command>/{cmd.txt,stdout.txt,stderr.txt,exit_code.txt}`: every otterdog command of the SUT (the reset
  CLI under `reset/`, the PR-text guard under `reset/guard/`, differential sides under `base/` and `head/`, offline
  tests under `offline/<seq>-<test>/`). `cmd.txt` holds the logical command (`otterdog <command> -c ...`), then
  `# process:` (the real argv, with its `unshare -rn` or `docker run ... --network none` prefix), `# runtime:`,
  `# cwd:`, `# duration:`, `# timed_out:` and `# infra_error:` lines;
- `offline/<seq>-<test>/workspace/`: the rendered configuration of an offline test;
- `webapp/compose.log`, `offline-webapp/webapp/compose.log`, `deliveries.jsonl`: webapp logs and the relayed
  deliveries;
- `run.json`: what ran (SUTs, versions, capabilities, lane, the `otterdog-e2e` command, SUT preparation times).

`make report RUN=artifacts/<run_id>` prints the summary again. The private scratch directory
(`$E2E_CACHE_DIR/run/<run_id>/`: CLI working directories, workspaces, otterdog's HTTP cache) is deleted at the end of
the session unless `--keep`; it may contain tokens, never copy it anywhere.

A failure tagged `[infra]` (rate limits, network, timeouts, lease busy, delivery not observed) is not a product
defect; `results.jsonl` has `"infra": true` for it.

## The webapp of `make dev-webapp` (external transport)

To test a webapp you run yourself, for example otterdog's development deployment (minikube + skaffold), use the
`external` transport. The session then skips the compose stack, calls the webapp's `/internal/init`, waits until it
lists the test organization and relays the App deliveries to it.

1. In your otterdog checkout, create the `values.yaml` of the development deployment for the **test** organization:
   the e2e GitHub App of the target (id, private key, webhook secret), the config owner `<test org>`, the config repo
   `otterdog-e2e-configs`, path `otterdog.json`, a read-only config token, and the validation/sync contexts of the
   target (by default `e2e/otterdog-validate` and `e2e/otterdog-sync`; the development values use
   `otterdog/otterdog-validation` and `otterdog/otterdog-sync`, so either override them there or set
   `E2E_VALIDATION_CONTEXT`/`E2E_SYNC_CONTEXT` accordingly). Then start it:

    ```bash
    cd ../otterdog && env -u OTTERDOG_CONFIG_ROOT make dev-webapp
    ```

2. Forward the webapp to a loopback port:

    ```bash
    kubectl -n otterdog port-forward svc/otterdog 5000:5000
    ```

3. Point the target at it (env file or shell) and run the webapp tier:

    ```bash
    export E2E_TRANSPORT=external
    export E2E_EXTERNAL_URL=http://127.0.0.1:5000
    export E2E_EXTERNAL_INIT_URL=http://127.0.0.1:5000/internal/init
    make webapp TARGET=free
    ```

    Only loopback URLs are accepted (`--e2e-allow-remote-webapp` overrides it; never point it to a shared deployment).
    Without `E2E_EXTERNAL_INIT_URL` the webapp is not re-initialized after the harness writes `otterdog.json`.

To explore by hand (open PRs in the test org yourself and watch the webapp react), run only the relay:

```bash
.venv/bin/otterdog-e2e relay --target free --forward-to http://127.0.0.1:5000/github-webhook/receive --since 30m
```

It forwards the App deliveries newer than `--since` and prints one line per delivery until Ctrl-C. It holds the org
lease: stop it before starting a test session (or set `E2E_LEASE_WAIT` on the session).

## Harness cache

`E2E_CACHE_DIR` (default `~/.cache/otterdog-e2e`, mode 0700):

| Path | Content |
|---|---|
| `mirror/eclipse-csi__otterdog.git` | blob-less bare mirror of upstream |
| `src/<label>` | exported trusted SUT sources |
| `build/<label>-cli` | host installations of trusted SUT CLIs |
| `tools/poetry-<version>`, `poetry-cache/` | the pinned poetry used for SUT installs and its download cache |
| `http-cache/<label>-offline` | otterdog's HTTP cache of offline commands per SUT (dummy token); the caches of live commands hold the token (pickled `Authorization` header) and stay in `run/<run_id>/http-cache/` |
| `run/<run_id>` | private per-run scratch (deleted at session end; `cache prune` never removes the one of a running session, whose lock `run/<run_id>.lock` is held) |
| `untrusted/` | private exports of untrusted SUTs (deleted at exit) and their image build locks `<label>.image.lock` |

```bash
make cache-prune KEEP=3      # keep the 3 newest entries of run/, build/, src/, http-cache/ and SUT images
```

`cache prune` removes an older entry together with its exact sidecar files only (`<name>.lock`, `<name>.image.lock`,
`<name>.e2e-export.json`: pruning `src/v1.2` never touches the files of `src/v1.2.1`), and keeps every entry whose
`<name>.lock` or `<name>.image.lock` is held right now (a running session, a source export, an install or an image
build, for example by a parallel batch). The image build locks of untrusted SUTs (`untrusted/<label>.image.lock`)
are removed once nobody holds them.

Docker images are tagged `otterdog-e2e/otterdog:<label>` (trusted) and `otterdog-e2e/untrusted:<label>`.

## Unit tests

`tests/unit` must stay fast and network-free (a fixture fails any non-loopback connection). Use `responses` for
`GitHubHttp`, and the fakes of `otterdog_e2e.testing.fakes` (`FakeGitHubHttp`, `FakeOracle`, `FakeCli`, `RecordingMutator`,
`FakeAppAuth`, `FakeLease`, `FakeBaselineManager`) for higher layers; real otterdog output samples live in `tests/unit/data/`. Test modules cannot import each
other (`--import-mode=importlib`): shared helpers belong in a `conftest.py` or `otterdog_e2e.testing`.

`tests/unit/test_workflows_static.py` checks the CI workflows, the Makefile, `.gitignore` and `.env.example`; run it
after editing any of them.

To prove that the unit tier needs no network, run it in a network namespace with only the loopback interface:
`unshare -rn sh -c 'ip link set lo up && exec .venv/bin/python -m pytest -q -p no:cacheprovider tests/unit'` (this
build: about 2900 tests). The suite also writes nothing below `$HOME` when `E2E_CACHE_DIR` is unset.

## Editor

`.vscode/settings.json` maps the scenario files to `.vscode/scenario.schema.json` (YAML extension: completion and key
checks), and `scenarios/known_bugs.yaml`, `scenarios/coverage.yaml` and the PR manifests to a permissive schema, so
SchemaStore's unrelated CrowdSec "scenario" schema no longer reports false errors. See
[writing-scenarios.md](writing-scenarios.md#editor-support) for regenerating it.

## Coverage matrix

`scenarios/coverage.yaml` is the inventory of otterdog's features and of what covers them
([coverage-matrix.md](coverage-matrix.md) is generated from it). When you add a scenario or a test that closes a gap,
update the feature (`status`, `covered_by`, drop the `gap_outline` once covered), then:

```bash
.venv/bin/python tests/unit/test_coverage_matrix.py --write      # regenerate docs/coverage-matrix.md, print the coverage per area
.venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/test_coverage_matrix.py
```

Renaming a test or a scenario id listed in `covered_by` fails that test until the YAML follows.

## Documentation site

The site (https://heurtematte.github.io/otterdog-e2e/) is built with MkDocs and Material for MkDocs from `docs/` and
`README.md`, its home page. `.github/workflows/docs.yml` runs the strict build for every pull request that changes the
documentation, and deploys the site to GitHub Pages from `main`. Publishing needs one repository setting: Settings,
Pages, Build and deployment, Source **GitHub Actions** (GitHub then creates the `github-pages` environment, which only
accepts deployments from `main`).

```bash
poetry install --with docs     # MkDocs, Material for MkDocs, pymdown-extensions (the docs group of poetry.lock)
make docs                      # strict build into site/: a broken link or anchor, a page missing from the nav fails
make docs-serve                # live preview on http://127.0.0.1:8000/otterdog-e2e/
```

The pages stay GitHub-flavored Markdown that renders on github.com; `docs_hooks.py` adapts them for the site:

- the home page is `README.md`, with its links rebased on `docs/` and without the blocks between
  `<!-- github-only -->` and `<!-- /github-only -->` (the badge, the link to the site): there is no `docs/index.md`;
- a link that leaves `docs/` (`../scenarios/coverage.yaml`) points to the file on GitHub (`blob/main`, `tree/main`
  for a directory), and its target must exist;
- GitHub callouts (`> [!WARNING]`) become admonitions;
- `\|` in a code span of a table row (GitHub needs it to keep the pipe in its cell) loses its backslash.

Python-Markdown is stricter than GitHub in a few places. Both render the page as written when you:

- indent everything nested in a list item by 4 spaces per level: sub-lists, code blocks and paragraphs (GitHub also
  accepts 2 or 3, MkDocs then flattens or splits the list), and leave a blank line before a list;
- leave a blank line between a nested paragraph or code block and the next item of the list;
- never start a line of text with `#` (`#790` becomes a heading) and write masked values in a code span (`********`);
- write a placeholder in a code span (`orgs/<org>`) or as `&lt;org&gt;`: anywhere else `<org>` is an HTML tag, which
  GitHub and MkDocs both drop (`tests/unit/test_docs_hooks.py` checks every page);
- link pages relatively (`security.md#ci-environments`): anchors are GitHub's (lower case, punctuation dropped, spaces
  as dashes), and `make docs` checks every link and anchor.

The workflow installs `docs/requirements.txt`: the docs group of `poetry.lock` with the hashes of every file. After
`poetry update --only docs` (or `poetry lock` after editing the group's constraints), regenerate it with
`.venv/bin/python tests/unit/test_docs_site.py --write` (the unit tier fails while it differs from the lock).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `unshare` FAIL in doctor, offline commands refused in CI | unprivileged user namespaces are disabled (Ubuntu 24.04 AppArmor): `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, or an AppArmor profile for `unshare` |
| `live session setup failed: ...` on every live test | verification, isolation, scopes, lease or token problem: run `otterdog-e2e doctor --target <instance>` |
| `LeaseBusy` | another session holds the org lease (its holder and expiry are in the message); wait, set `E2E_LEASE_WAIT`, or, for a crashed run, `make janitor TARGET=<instance> RUN_ID=<id> APPLY=1` |
| `target 'acme-a' not found: no profile targets/acme-a.yaml ... E2E_PROFILE is not set` | the instance has no env file or no `E2E_PROFILE`: `otterdog-e2e setup --target acme-a`, or add `E2E_PROFILE=<profile>` to `~/.config/otterdog-e2e/acme-a.env` |
| `--target 'a,b': a list of targets (a,b / @all / @<list>) is only accepted by run, pr, doctor, janitor` | `bootstrap`, `relay`, `app-manifest`, `inject`, `setup` and `ci-sync` take one target: run them once per instance |
| `--parallel: ... test the same organization` | two instances pin one organization, which serves one session at a time: drop `--parallel` |
| `E2E_ORG is set in the environment: the env files never override the environment ...` (or `the environment overrides what the env files of the batch set differently: ...`) | a batch of several targets with an exported per-instance value, login or secret: unset the named variables (each env file keeps its own), or give one target |
| `SafetyError` during a reset | an unmanaged org-level object (team, org secret/variable, ruleset, custom property) without a run id: delete it or declare it in the baseline |
| skipped: `github rate budget` | an identity has less than `E2E_MIN_RATE_REMAINING` (default 800) core requests left; wait for the reset |
| skipped: `GitHub App not ready` | App env missing, not installed on All repositories, or suspended: `doctor` shows which |
| `otterdog ignored unknown properties` | a fragment is in the wrong place (e.g. a repository field at org level) |
| `did not converge` | an applied change keeps appearing in the plan (drift, plan limitation, a removal without `delete: true`) |
| C-BASELINE reports `members_can_create_private_pages` pending on a Free org | GitHub reports `true` there while the template renders `false`, and declaring `true` is an enterprise-only validation error: set `baseline: settings: {members_can_create_private_pages: null}` in the target file (`null` leaves a key unmanaged) |
| `--e2e-base-sut auto` fails for a `sha:`/`tag:` SUT | only `pr:`, `path:` and `dirty:` SUTs have a merge base: pass the base explicitly |
