# Commands and configuration

The reference of the harness's command line, its Makefile, its configuration, the artifacts of a run and the
continuous integration workflows. The [README](../README.md) (the home page of this site) introduces the harness,
its tiers and its coverage; [onboarding.md](onboarding.md) sets up a test organization.

## Commands

All commands are subcommands of `otterdog-acceptance`, on your `PATH` after `make init` (its alias `oda` is the same
command; [local-development.md](local-development.md) explains the link): `--help` on each one, `-v`/`-vv` for more
logging.

| Command | Purpose |
|---|---|
| `setup --target T [--profile P] [--shard S] [--from I] [--token-type classic\|fine-grained] [--rotate ROLE] [--wait-timeout 30m] [--open] [--no-browser]`, `setup --shards` | interactive onboarding of one instance, or of the instance of every shard in turn: org, tokens of every role (prefilled creation URLs, checked before they are written), web-UI login, GitHub App (verified before its installation link), then bootstrap and doctor; with an accounts store, the classic tokens and the web steps (org creation, invitations, public memberships, App creation and installation) in Firefox as the machine accounts; writes `~/.config/otterdog-acceptance/<instance>.env` ([onboarding.md](onboarding.md)) |
| `accounts --target T [--role R] [--rotate] [--expires-in none] [--config FILE]` | set up machine accounts in a Firefox window (optional extra `browser`): sign in, enroll 2FA when missing, create the classic token; secrets in the accounts store of `~/.config/otterdog-acceptance/setup.yaml` (pass or Vault, ci-admin's names), the tokens checked and registered by `setup` ([onboarding.md](onboarding.md#machine-accounts-in-the-browser)) |
| `web-login [ACCOUNT \| --target T [--role R]] [--url URL]` | a visible Firefox signed in as an account of the accounts store (by the name of its entries), of an instance (admin by default) or typed in the terminal, on the test organization or `--url`; Enter signs it out ([onboarding.md](onboarding.md#signing-in-as-an-account)) |
| `ci-sync --target T [--reviewer LOGIN] [--nightly] [--prune-branch-policies] [--apply]` | the CI environments, variables and secrets of an instance, with your own `gh` login (dry run without `--apply`; deployment branch `main` only, the protections read back before any secret) |
| `targets [--json]` | list the instances (env files) and profiles, with their shard and organization |
| `shards [--json]` | what each shard of `scenarios/shards.yaml` runs (one test organization each) and the instances that select it ([architecture.md](architecture.md#organizations-and-shards)) |
| `doctor --target T [--json]` | read-only checks: env, identities and their isolation, token kind and expiry, PAT scopes (classic) or permission probes (fine-grained), org id/plan/marker, memberships, teams, repositories, GitHub App, web-UI credentials and login gate (never logs in), docker, unshare (exit 1 on FAIL); several targets: one table each |
| `bootstrap --target T [--apply [--wait [--wait-timeout 30m]]]` | idempotent org preparation: marker (typed confirmation), identities (a separate oracle invited as an owner when its own token proves its login), configs/defaults repositories, lease, template, baseline reset, App checks and delivery probe (dry run without `--apply`; `--wait`, only with `--apply`, waits for the invitations and the App installation) |
| `sut resolve\|install\|image\|classify SPEC` | resolve a SUT to a commit, install its CLI (trusted only), build its webapp image, classify its trust |
| `run [--target T] [--sut S] [--base-sut B] [--suite ...] [--tags ...] [--scenario ...] [-k EXPR] [pytest args]` | run tiers through pytest (also `--change N\|slug` (the scenarios referencing the change: expected deltas, extra scenarios, its `base` is the default `--base-sut`; default: N of a `pr:N@<sha>` SUT), `--reset-sut`, `--run-id`, `--artifacts`, `--webapp-image`, `--keep`, `--no-reset`, `--strict-diff`, `--allow-web-ui`); several targets (`a,b`, `@all`, `@<list>`): one child process each, `--parallel N`, `--fail-fast`, a batch summary |
| `pr N --sha SHA [--target T] [--suite auto\|...] [--strict-diff] [--allow-web-ui] [--change C]` | test upstream PR N at SHA: regression tiers, differential against its base, the scenarios referencing the PR (several targets like `run`) |
| `relay --target T --forward-to URL [--since 10m] [--allow-remote]` | forward the App's webhook deliveries to a local webapp (holds the org lease) |
| `janitor --target T [--older-than 6h] [--run-id ID [--force-takeover]] [--apply]` | list (and delete) leftovers of finished or crashed runs (a lease of `--run-id` renewed within 20 minutes is not taken over unless `--force-takeover`); several targets one after the other |
| `report DIR` | print the summary of a run artifacts directory |
| `compare-runs BASELINE RUN [--json]` | the outcome of every item of two runs of the same SUT, typically by two harness revisions (`make harness-check`): exit 1 when an outcome changed, 2 when the runs are not comparable |
| `scrub-artifacts DIR` | delete non-text files and files leaking a secret (the secret values of its environment included; exit 1 on leaks) |
| `cache prune [--keep 3]` | drop old builds, sources, runs and images from the harness cache (never an entry whose lock a running session or build holds) |
| `completion bash\|zsh\|fish` | print the shell completion script of `otterdog-acceptance` and `oda` (`eval "$(oda completion zsh)"` in `~/.zshrc`, [local-development.md](local-development.md#shell-completion)) |
| `app-manifest --target T --webhook-url URL [--port 8765] [--exchange CODE]` | create the e2e GitHub App from a manifest |
| `inject [--target T] [--sut S] --fragment KIND=FILE [--library NAME=FILE] [--overlay FILE] [--config/--base FILE] [--apply] [--print]` | try jsonnet files against a SUT without writing a scenario (offline by default; `--target`: live validate + plan, `--apply` with guards and cleanup) |
| `assist pr-context N [--sha SHA] \| check [PATHS] [--sut S] [--no-lint] \| triage DIR\|latest [--baseline DIR] \| coverage [--status ...] [--feature ID]` | deterministic helpers of AI-assisted test writing: the context bundle of an otterdog PR, validation of the files an agent wrote, triage of a run's failures (after a scrub), the coverage gaps; `--json` on each ([ai-assistance.md](ai-assistance.md)) |

`run` refuses pass-through arguments that could change the SUT, load plugins or print secrets (`--e2e-*`, `-p`,
`-c`, `-o`, `--rootdir`, `--showlocals`, `@file`, ...). Its exit code is pytest's; budget overruns never fail a run.
Without `--suite` it runs `offline`, `cli`, `webhooks`, `webapp` and `enterprise`, plus `differential` with a base SUT
and `web_ui` with `--allow-web-ui`. `--allow-web-ui` lets otterdog log in to github.com as the admin bot: only give
it with a target whose web credentials are set up ([web-ui-testing.md](web-ui-testing.md)); a `pr:` SUT is
untrusted, so `pr --allow-web-ui` only passes the option on and the web tests skip.

The same options exist as pytest options when you call pytest directly: `--e2e-target`, `--e2e-sut`,
`--e2e-base-sut`, `--e2e-reset-sut`, `--e2e-tags`, `--e2e-scenario`, `--e2e-artifacts`, `--e2e-run-id`,
`--e2e-keep`, `--e2e-no-reset`, `--e2e-webapp-image`, `--e2e-change`, `--e2e-strict-diff`,
`--e2e-no-http-cache`, `--e2e-allow-remote-webapp`, `--e2e-trust-code`, `--e2e-allow-web-ui` (most fall back to an
`E2E_*` variable; `E2E_ALLOW_WEB_UI` only from the process environment).

## Makefile

`make help` lists every target. The main ones: `init`, `unit`, `lint`, `format`, `typecheck`, `check`, `offline`,
`lint-scenarios` (the offline lint of every live scenario step), `inject ARGS='--fragment KIND=FILE ...'`,
`cli`, `webhooks`, `webapp`, `web-ui`, `enterprise`, `differential`, `e2e`, `one SCENARIO=<glob>`, `pr PR=<n> SHA=<sha>`,
`setup [FROM=<instance>] [PROFILE=<profile>]`, `ci-sync [REVIEWER=<login>] [NIGHTLY=1] [APPLY=1]`, `targets`, `doctor`,
`bootstrap [APPLY=1] [WAIT=1]`, `janitor [APPLY=1]`, `relay`, `report [RUN=<dir>]`, `scrub`, `cache-prune`, `sut`.
They read `TARGET` (default
`$E2E_TARGET`; a comma list, `@all` or `@<list>` for the run-based targets, `pr`, `doctor` and `janitor`), `PARALLEL`,
`SUT` (default `release:latest`), `BASE_SUT`, `SUITE` and `ARGS` (extra pytest arguments), and never pass
`OTTERDOG_CONFIG_ROOT` on.

## Configuration

- `targets/<profile>.yaml`: the profiles (`free.yaml`, `team.yaml`, `enterprise.yaml`), holding no org-specific
  value. Values come from environment variables; secrets are never written there (`*_env` keys name the variable
  holding them).
- Instances: one test organization each, `--target <instance>`. Its environment files, first one wins and the process
  environment wins over all of them: `~/.config/otterdog-acceptance/<instance>.env` (written by `setup`, with
  `E2E_PROFILE=<profile>`), `.env.e2e.<instance>`, `.env.e2e`. The instances `free`, `team` and `enterprise` use the
  profile of the same name. [.env.example](../.env.example) lists every variable with its meaning and the required token
  scopes; [docs/onboarding.md](onboarding.md#instances-and-profiles) the naming rules.
- `E2E_CACHE_DIR` (default `~/.cache/otterdog-acceptance`): upstream mirror, SUT sources and builds, tool venvs, private
  per-run scratch directories. `E2E_ARTIFACTS` (default `./artifacts`): redacted run artifacts.
- The project was named otterdog-e2e: while `~/.config/otterdog-acceptance` (or `~/.cache/otterdog-acceptance`) does
  not exist, the harness keeps using `~/.config/otterdog-e2e` (or `~/.cache/otterdog-e2e`) as it is. The names it
  gives on GitHub and in the secret stores keep the former prefix: the org marker `[otterdog-e2e]`, the repositories
  `otterdog-e2e-configs` and `otterdog-e2e-defaults`, the App `otterdog-e2e-<org>`, the token names, the accounts
  store entries, the webhook host `otterdog-e2e.invalid` and the docker images `otterdog-e2e/*`.

## Run artifacts

Every session that runs e2e tests writes `<E2E_ARTIFACTS>/<run_id>/` (a `--collect-only` session leaves nothing):

| Path | Content |
|---|---|
| `run.json` | target, org, plan, SUT/base/reset SUT details and versions, capabilities, lane, timings (SUT preparation included), the `otterdog-acceptance` command |
| `results.jsonl` | one line per test: outcome, phase durations, tier, scenario, tags, skip/xfail reason, short failure, infra flag, rate budget |
| `summary.md` | human summary: outcomes, failures, skips by reason, known bugs, coverage matrix (shares and the features the run exercised), budget overruns, differential summary, a "Manual testing" block for otterdog's PR template |
| `cli/`, `reset/cli/`, `base/…/cli/`, `head/…/cli/`, `offline/<test>/cli/` | redacted `cmd.txt` (logical and process argv, runtime, duration), `stdout.txt`, `stderr.txt`, `exit_code.txt` of every otterdog command |
| `offline/<test>/workspace/` | the rendered configuration of an offline test (`otterdog.json`, `<org>.jsonnet.txt`, `-BASE`) |
| `webapp/compose.log`, `offline-webapp/webapp/compose.log`, `deliveries.jsonl` | webapp logs and relayed App deliveries (no payloads) |
| `observations/{base,head}.jsonl`, `differential.{md,json}` | differential recordings and their comparison |
| `webui/<scenario>.json` | evidence of the web-UI scenarios (values read and written, restore results, the login gate's counters) |
| `leaks.json` | result of the artifact scrub |

Artifacts contain redacted text files only; credentials, otterdog's HTTP cache and the App key live in the private
scratch directory below `E2E_CACHE_DIR`, which is deleted at session end (unless `--e2e-keep`).

## Continuous integration

| Workflow | Trigger | What |
|---|---|---|
| `ci.yml` | push to main, pull requests | ruff, mypy, unit tier, offline tier of `release:latest` and `branch:main`, all blocking (no secrets) |
| `e2e.yml` | dispatch, reusable | one live session per instance (`target`: one instance or a comma list, allowlist `E2E_INSTANCES`): `classify` (no secrets) then one `e2e` job per instance in the `e2e-<instance>` or `e2e-<instance>-untrusted` environment |
| `e2e-otterdog-pr.yml` | dispatch only | validates `pr` and the 40-hex `sha`, then calls `e2e.yml` with `pr:<n>@<sha>` and base `auto` |
| `e2e-webui.yml` | dispatch, reusable | the web-UI tier of a trusted SUT on one or several instances (one at a time), in the `e2e-<instance>-webui` environment (the only one holding the bot's password and TOTP seed) |
| `nightly.yml` | schedule | per enabled instance (`E2E_TARGETS`): `release:latest`, then `branch:main` with a differential against `release:latest`; the web-UI lane when `E2E_WEB_UI_ENABLED` is `true` (one instance at a time) |
| `janitor.yml` | every 6 hours | a `check` job (no environment, no secrets) refuses `E2E_ORG`, `E2E_ORG_ID` and `E2E_PROFILE` as repository or organization variables, then sweeps leftovers of old runs on every enabled instance |
| `docs.yml` | push to main and pull requests changing the documentation, dispatch | strict Zensical build of the documentation site (staged by `docs_site.py`); on main, deploys it to GitHub Pages (no secrets) |

The required repository setup (environments, variables, secrets) is described in
[docs/security.md](security.md#ci-environments) and [docs/setup-free-org.md](setup-free-org.md#ci);
`otterdog-acceptance ci-sync` creates it per instance ([docs/onboarding.md](onboarding.md#ci-ci-sync)).
