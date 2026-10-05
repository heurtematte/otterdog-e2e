# otterdog-e2e

<!-- github-only -->

[![docs](https://github.com/heurtematte/otterdog-e2e/actions/workflows/docs.yml/badge.svg?branch=main)](https://github.com/heurtematte/otterdog-e2e/actions/workflows/docs.yml)

Documentation: https://heurtematte.github.io/otterdog-e2e/

<!-- /github-only -->

End-to-end test harness for [otterdog](https://github.com/eclipse-csi/otterdog), the GitOps tool that manages GitHub
organizations as code. It covers the three faces of otterdog:

- the **CLI** (`validate`, `plan`, `apply`, `import`, `push-config`, `open-pr`, ...),
- the **webapp** (Quart application + GitHub App) and its config-repository pull request workflow (validation
  status and comments, `/otterdog` commands, approvals, auto-merge, merge then apply, sync checks),
- **webhooks**: deliveries to the GitHub App receiver and the org/repository webhooks that otterdog manages.

A web-UI tier also covers what otterdog can only do through the GitHub web UI (its Playwright login as a bot owner):
the web-only organization settings and the UI-driven commands.

The harness runs against **real, dedicated GitHub test organizations**: GitHub Free, Team and Enterprise Cloud
organizations on github.com, one or several in one command. It can test a released otterdog version, upstream `main`, a
proposed upstream pull request pinned to a commit, or a local checkout (uncommitted changes included). For a pull
request it compares base and head (differential observations) and reports expected and unexpected deltas.

> [!WARNING]
> Only use **dedicated test organizations** and **dedicated machine accounts** that belong to test organizations
> only. The harness creates, changes and deletes repositories, teams, secrets, webhooks and rulesets. It verifies the
> organization id, its plan, a marker in its description and the memberships of every account before it writes
> anything, but these checks only protect you if the accounts cannot reach any real organization.
> See [docs/security.md](docs/security.md).

## Requirements

- Python 3.11 or later (CI uses 3.12) and [poetry](https://python-poetry.org/) 2.x (the lock file was written by
  poetry 2.5.1); `git`.
- `unshare` (util-linux) with unprivileged user namespaces: offline otterdog commands run without network
  (`unshare -rn`); in CI the harness refuses to run them unsandboxed.
- Docker (with the compose plugin) for the webapp tiers and for every untrusted SUT (pull requests).
- Network access to github.com and PyPI: the SUT is fetched and installed by the harness.

## Quickstart

Without any GitHub organization (offline tier only):

```bash
make init        # poetry install --with dev -> .venv
make unit        # harness self-tests: no network, no docker, about 1 min
make offline     # offline tier of the latest otterdog release (docker for the webapp part), about 6 min warm

# differential proof of concept of otterdog#790: the offline tier of the head, then base and head CLIs on every
# observed offline scenario, about 15 min warm
.venv/bin/otterdog-e2e run --sut sha:9bdeb75 --suite offline,differential --pr-manifest scenarios/otterdog-prs/790.yaml
```

The first run fetches the otterdog repository, installs each SUT and builds its webapp image; later runs reuse the
cache. Everything lands in `E2E_CACHE_DIR` and `E2E_ARTIFACTS`.

With a dedicated test organization: create its machine accounts and the organization by hand, then let `setup`
onboard it ([docs/onboarding.md](docs/onboarding.md) is the fast path, [docs/setup-free-org.md](docs/setup-free-org.md)
the same steps by hand):

```bash
.venv/bin/otterdog-e2e setup --target free             # interactive: org, tokens (prefilled URLs), App, bootstrap
.venv/bin/otterdog-e2e doctor --target free            # read-only checks
.venv/bin/otterdog-e2e ci-sync --target free --apply   # CI environments, variables and secrets (your gh login)
make cli TARGET=free                                   # live CLI tier
make one TARGET=free SCENARIO='cli.repo.*'             # selected scenarios only
make web-ui TARGET=free                                # web-UI tier: the admin bot logs in (docs/web-ui-testing.md)
```

Every test organization is an **instance** (`free` above, or any name such as `acme-a` bound to a profile
`targets/<profile>.yaml` by `E2E_PROFILE`); several of them run in one command, one child process each:

```bash
.venv/bin/otterdog-e2e setup --target acme-a --from free   # a second organization, same settings
.venv/bin/otterdog-e2e targets                             # the instances, their profile and org
make cli TARGET=free,acme-a                                # one after the other (PARALLEL=2: at once)
.venv/bin/otterdog-e2e run --target @all --suite cli       # every instance with an env file
```

## Tiers

| Tier | Directory | Needs | Content |
|---|---|---|---|
| unit | `tests/unit` | nothing (no network, no docker) | harness self-tests |
| offline | `tests/offline`, `scenarios/offline` | the SUT (network once to fetch it), docker for the webapp part | configuration loading, credential providers, template hooks, `validate`, `local-plan`, `local-apply` (declined), `show`, `show-default`, `canonical-diff`, `list-projects`, `--help`, `--version` and exit codes with a vendored template; the offline lint of every live scenario step; webapp boot, runtime and webhook receiver contract with dummy credentials |
| cli | `tests/cli`, `scenarios/cli`, `scenarios/regressions` | target + admin identity | live CLI lifecycle (`plan -n`/`apply -f -n`), run-prefixed resources |
| webhooks | `tests/webhooks` | target (+ GitHub App) | otterdog-managed repository/org webhooks, real App deliveries through the relay |
| webapp | `tests/webapp` | target + GitHub App + docker | the webapp under test in docker compose, config-repo PR workflow |
| web_ui | `tests/web_ui` | target + the admin bot's web credentials (password, TOTP seed) + `--allow-web-ui`, a trusted SUT, no SAML SSO | otterdog's web-UI login: the round trip of the 12 web-only org settings, `import` of web settings, `review-permissions`, `list-advisories -w`, `install-app`/`uninstall-app`, `web-login` (local) ([web-ui-testing.md](docs/web-ui-testing.md)) |
| enterprise | `tests/enterprise`, `scenarios/enterprise` | target with plan `enterprise` | enterprise-only features |
| differential | `tests/differential` | `--base-sut` (+ target for the live part) | observe-only scenarios on base and head, compared |

Lanes: `pr-fast` (at most 45 min: offline tiers of both SUTs, offline differential, tag-selected live scenarios)
and `nightly-full` (everything; the web-UI tier in its own optional lane). Live tests are skipped (with the reason)
when no target is given, when a capability, plan, identity, docker or the GitHub App is missing, or when the rate
budget is low. Web-UI tests also skip without `--allow-web-ui`, web credentials or a trusted SUT.

## Coverage

[`scenarios/coverage.yaml`](scenarios/coverage.yaml) inventories otterdog's features (CLI commands and flags, every
property of the configuration model, validation rules, diff semantics, the webapp's events, commands, tasks and
endpoints, notable fixes) and maps each one to the scenarios and tests that cover it, with an outline of the missing
test for every gap. [docs/coverage-matrix.md](docs/coverage-matrix.md) is generated from it, and a unit test fails
when the two diverge. After editing the YAML, regenerate the page:

```bash
.venv/bin/python tests/unit/test_coverage_matrix.py --write   # rewrites docs/coverage-matrix.md, prints the coverage per area
```

At otterdog main 9bdeb75 the matrix lists 337 features: 300 covered, 32 partial and 5 gaps (89% covered, 94% when a
partial feature counts half); 139 are covered by offline items, the only tier run against real SUTs so far. The battery
behind it has 137 YAML scenarios (59 offline, 64 cli, 7 regressions, 7 enterprise) and 218 Python test functions (75
offline, 58 cli, 5 webhooks, 64 webapp, 11 web-UI, 1 enterprise, 4 differential); the offline tier runs 356 items in
about 6 minutes. [scenarios/known_bugs.yaml](scenarios/known_bugs.yaml) registers 77 otterdog defects (57 confirmed, 20
suspected): the items that reproduce one assert the correct behaviour and run as expected failures while it is open.

Every run's `summary.md` has a "Coverage matrix" section: the covered, partial and gap shares per tier, and the
features whose covering items ran in that run. [docs/battery-guide.md](docs/battery-guide.md) explains how to close a
gap: which harness API, YAML key, fixture or check kind to use for each kind of feature, and the conventions.

## Systems under test (SUT specs)

| Spec | Meaning | Trust |
|---|---|---|
| `release:latest` | newest `v*` release of upstream (default) | trusted |
| `tag:v1.6.1` or `v1.6.1` | an upstream tag | trusted |
| `branch:main` or `main` | upstream main | trusted |
| `sha:<7-40 hex>` | an upstream commit | trusted when reachable from upstream main or a `v*` tag, else untrusted (full 40-hex sha required) |
| `pr:<N>@<40-hex sha>` | upstream pull request N, pinned to a commit reachable from its head | untrusted |
| `path:<dir>` | the committed `HEAD` of a local checkout (read-only) | trusted |
| `dirty:<dir>` | a local checkout including uncommitted changes (allow/deny listed paths) | trusted |

Untrusted SUTs run only inside their own docker image (no network for offline commands, read-only root, no
capabilities, credentials in a 0600 env-file); destructive resets always use a trusted reset SUT
(`--e2e-reset-sut`, default `release:latest`). `otterdog-e2e sut classify SPEC` prints the trust decision.

## Commands

All commands are subcommands of `.venv/bin/otterdog-e2e` (`--help` on each one; `-v`/`-vv` for more logging).

| Command | Purpose |
|---|---|
| `setup --target T [--profile P] [--from I] [--token-type classic\|fine-grained] [--rotate ROLE] [--wait-timeout 30m] [--open]` | interactive onboarding of one instance: org, tokens of every role (prefilled creation URLs, checked before they are written), web-UI login, GitHub App (verified before its installation link), then bootstrap and doctor; writes `~/.config/otterdog-e2e/<instance>.env` ([onboarding.md](docs/onboarding.md)) |
| `ci-sync --target T [--reviewer LOGIN] [--nightly] [--prune-branch-policies] [--apply]` | the CI environments, variables and secrets of an instance, with your own `gh` login (dry run without `--apply`; deployment branch `main` only, the protections read back before any secret) |
| `targets [--json]` | list the instances (env files) and profiles, with their organization |
| `doctor --target T [--json]` | read-only checks: env, identities and their isolation, token kind and expiry, PAT scopes (classic) or permission probes (fine-grained), org id/plan/marker, memberships, teams, repositories, GitHub App, web-UI credentials and login gate (never logs in), docker, unshare (exit 1 on FAIL); several targets: one table each |
| `bootstrap --target T [--apply [--wait [--wait-timeout 30m]]]` | idempotent org preparation: marker (typed confirmation), identities (a separate oracle invited as an owner when its own token proves its login), configs/defaults repositories, lease, template, baseline reset, App checks and delivery probe (dry run without `--apply`; `--wait`, only with `--apply`, waits for the invitations and the App installation) |
| `sut resolve\|install\|image\|classify SPEC` | resolve a SUT to a commit, install its CLI (trusted only), build its webapp image, classify its trust |
| `run [--target T] [--sut S] [--base-sut B] [--suite ...] [--tags ...] [--scenario ...] [-k EXPR] [pytest args]` | run tiers through pytest (also `--pr-manifest` (its `base` is the default `--base-sut`), `--reset-sut`, `--run-id`, `--artifacts`, `--webapp-image`, `--keep`, `--no-reset`, `--strict-diff`, `--allow-web-ui`); several targets (`a,b`, `@all`, `@<list>`): one child process each, `--parallel N`, `--fail-fast`, a batch summary |
| `pr N --sha SHA [--target T] [--suite auto\|...] [--strict-diff] [--allow-web-ui]` | test upstream PR N at SHA: regression tiers, differential against its base, PR manifest scenarios (several targets like `run`) |
| `relay --target T --forward-to URL [--since 10m] [--allow-remote]` | forward the App's webhook deliveries to a local webapp (holds the org lease) |
| `janitor --target T [--older-than 6h] [--run-id ID [--force-takeover]] [--apply]` | list (and delete) leftovers of finished or crashed runs (a lease of `--run-id` renewed within 20 minutes is not taken over unless `--force-takeover`); several targets one after the other |
| `report DIR` | print the summary of a run artifacts directory |
| `scrub-artifacts DIR` | delete non-text files and files leaking a secret (the secret values of its environment included; exit 1 on leaks) |
| `cache prune [--keep 3]` | drop old builds, sources, runs and images from the harness cache (never an entry whose lock a running session or build holds) |
| `app-manifest --target T --webhook-url URL [--port 8765] [--exchange CODE]` | create the e2e GitHub App from a manifest |
| `inject [--target T] [--sut S] --fragment KIND=FILE [--library NAME=FILE] [--overlay FILE] [--config/--base FILE] [--apply] [--print]` | try jsonnet files against a SUT without writing a scenario (offline by default; `--target`: live validate + plan, `--apply` with guards and cleanup) |

`run` refuses pass-through arguments that could change the SUT, load plugins or print secrets (`--e2e-*`, `-p`,
`-c`, `-o`, `--rootdir`, `--showlocals`, `@file`, ...). Its exit code is pytest's; budget overruns never fail a run.
Without `--suite` it runs `offline`, `cli`, `webhooks`, `webapp` and `enterprise`, plus `differential` with a base SUT
and `web_ui` with `--allow-web-ui`. `--allow-web-ui` lets otterdog log in to github.com as the admin bot: only give
it with a target whose web credentials are set up ([web-ui-testing.md](docs/web-ui-testing.md)); a `pr:` SUT is
untrusted, so `pr --allow-web-ui` only passes the option on and the web tests skip.

The same options exist as pytest options when you call pytest directly: `--e2e-target`, `--e2e-sut`,
`--e2e-base-sut`, `--e2e-reset-sut`, `--e2e-tags`, `--e2e-scenario`, `--e2e-artifacts`, `--e2e-run-id`,
`--e2e-keep`, `--e2e-no-reset`, `--e2e-webapp-image`, `--e2e-pr-manifest`, `--e2e-strict-diff`,
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
  environment wins over all of them: `~/.config/otterdog-e2e/<instance>.env` (written by `setup`, with
  `E2E_PROFILE=<profile>`), `.env.e2e.<instance>`, `.env.e2e`. The instances `free`, `team` and `enterprise` use the
  profile of the same name. [.env.example](.env.example) lists every variable with its meaning and the required token
  scopes; [docs/onboarding.md](docs/onboarding.md#instances-and-profiles) the naming rules.
- `E2E_CACHE_DIR` (default `~/.cache/otterdog-e2e`): upstream mirror, SUT sources and builds, tool venvs, private
  per-run scratch directories. `E2E_ARTIFACTS` (default `./artifacts`): redacted run artifacts.

## Run artifacts

Every session that runs e2e tests writes `<E2E_ARTIFACTS>/<run_id>/` (a `--collect-only` session leaves nothing):

| Path | Content |
|---|---|
| `run.json` | target, org, plan, SUT/base/reset SUT details and versions, capabilities, lane, timings (SUT preparation included), the `otterdog-e2e` command |
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
| `ci.yml` | push to main, pull requests | ruff, mypy (non-blocking), unit tier, offline tier of `release:latest` and `branch:main` (no secrets) |
| `e2e.yml` | dispatch, reusable | one live session per instance (`target`: one instance or a comma list, allowlist `E2E_INSTANCES`): `classify` (no secrets) then one `e2e` job per instance in the `e2e-<instance>` or `e2e-<instance>-untrusted` environment |
| `e2e-otterdog-pr.yml` | dispatch only | validates `pr` and the 40-hex `sha`, then calls `e2e.yml` with `pr:<n>@<sha>` and base `auto` |
| `e2e-webui.yml` | dispatch, reusable | the web-UI tier of a trusted SUT on one or several instances (one at a time), in the `e2e-<instance>-webui` environment (the only one holding the bot's password and TOTP seed) |
| `nightly.yml` | schedule | per enabled instance (`E2E_TARGETS`): `release:latest`, then `branch:main` with a differential against `release:latest`; the web-UI lane when `E2E_WEB_UI_ENABLED` is `true` (one instance at a time) |
| `janitor.yml` | every 6 hours | a `check` job (no environment, no secrets) refuses `E2E_ORG`, `E2E_ORG_ID` and `E2E_PROFILE` as repository or organization variables, then sweeps leftovers of old runs on every enabled instance |
| `docs.yml` | push to main and pull requests changing the documentation, dispatch | strict MkDocs build of the documentation site; on main, deploys it to GitHub Pages (no secrets) |

The required repository setup (environments, variables, secrets) is described in
[docs/security.md](docs/security.md#ci-environments) and [docs/setup-free-org.md](docs/setup-free-org.md#ci);
`otterdog-e2e ci-sync` creates it per instance ([docs/onboarding.md](docs/onboarding.md#ci-ci-sync)).

## Documentation

The documentation is published at https://heurtematte.github.io/otterdog-e2e/ (MkDocs, built and deployed by
`docs.yml`; `make docs` builds it locally, see [local-development.md](docs/local-development.md#documentation-site)).

| Document | Content |
|---|---|
| [architecture.md](docs/architecture.md) | components, tiers, data flow, safety model, differential testing |
| [security.md](docs/security.md) | threat model, controls, CI environments, incident runbook |
| [onboarding.md](docs/onboarding.md) | the fast path: `setup`, `ci-sync`, instances and profiles, runs on several organizations, what GitHub does not let a program do |
| [setup-free-org.md](docs/setup-free-org.md) | machine accounts, organization, tokens (classic or fine-grained), bootstrap, GitHub App, first run, by hand |
| [setup-enterprise-org.md](docs/setup-enterprise-org.md) | GitHub Enterprise Cloud specifics (trial, SAML SSO, policies), the Team profile |
| [github-app.md](docs/github-app.md) | the e2e GitHub App: permissions, manifest flow, webhook sink, relay |
| [writing-scenarios.md](docs/writing-scenarios.md) | the YAML scenario model, checks, rules, examples |
| [battery-guide.md](docs/battery-guide.md) | authoring guide of the test battery: which harness API, YAML key, fixture or check kind closes which kind of coverage gap, conventions, the lint and the login budget |
| [web-ui-testing.md](docs/web-ui-testing.md) | the web-UI tier: web-only settings, the bot account, gating, the login gate, CI lane, recovery |
| [testing-an-otterdog-pr.md](docs/testing-an-otterdog-pr.md) | `pr`, local checkouts, PR manifests, differential report, CI dispatch, the `/e2e` trigger |
| [local-development.md](docs/local-development.md) | Makefile, debugging, the relay with `make dev-webapp`, caches, troubleshooting |
| [capability-matrix.md](docs/capability-matrix.md) | what each GitHub plan allows and how the harness gates scenarios |
| [scenario-catalog.md](docs/scenario-catalog.md) | v1 scenarios, the test battery and the backlog |
| [coverage-matrix.md](docs/coverage-matrix.md) | every otterdog feature, its covering scenarios and tests, the outline of each gap (generated from `scenarios/coverage.yaml`) |
| [known-issues.md](docs/known-issues.md) | suspected and confirmed otterdog defects with reproductions (mirrors `scenarios/known_bugs.yaml`) |

Out of scope for v1 (future work): a ghproxy mock (a Dependency-Track mock exists: compose profile `dtrack`), MongoDB
inspection, tunnels (only the pull relay and a loopback external webapp exist), a Helm/Kubernetes lane, GitHub
Enterprise Server, ghe.com and Enterprise Managed Users, `repository_dispatch` triggers. The harness never automates a browser itself: the web-UI tier lets
otterdog's own Playwright client do it.

## License

Eclipse Public License 2.0 (EPL-2.0).
