# Checking the instances

`doctor` checks the configuration of an instance and changes nothing: env file, identities and their tokens, machine
accounts, organization, memberships, teams, repositories, GitHub App, web-UI credentials and local tools. It never runs
otterdog, never logs in to the web UI and does not read the rate budgets of the identities, so only a run proves an
installation. This page checks every organization at once, says which `WARN` rows matter, gives the runs that prove
what doctor cannot and how GitHub Actions runs them, at night or on demand.

## Every organization at once

```bash
otterdog-acceptance doctor --target @shards          # the instances of the shards
otterdog-acceptance doctor --target @all             # every instance with an env file
otterdog-acceptance doctor --target free,webapp      # a selection
otterdog-acceptance doctor --target @shards --json   # a JSON list, one entry per instance
make doctor TARGET=@shards
```

`@shards` is the list `~/.config/otterdog-acceptance/lists/shards`, which `setup` fills with each instance it sets up
for a shard ([the organizations of the shards](onboarding.md#the-organizations-of-the-shards)). doctor prints one table
per instance, each checked with its own env file, then `doctor: <n> targets, <m> with failures`. It exits with 1 when a
row of any instance is `FAIL`; `WARN` rows never change the exit code.

Two commands map the instances without calling GitHub: `otterdog-acceptance targets` gives the shard and the
organization of each instance (an instance keeps its name when it serves a shard named otherwise, such as `free` for
`repos`), and `otterdog-acceptance shards` what each shard runs ([organizations and
shards](architecture.md#organizations-and-shards)).

## Reading the rows

- `FAIL` blocks the runs that need the row. Fix the identity, isolation and scope rows first: nothing else can be
  checked without them. Every `FAIL` and `WARN` row prints a `fix:` line.
- `WARN` says what will be skipped, or what doctor could not check.
- A missing row is not a problem in itself. Without an `identity:oracle` row, the instance has no oracle token of its
  own and the admin serves as oracle, which the profiles allow; without `app:` rows, the instance has no App.

The rows that are most often not `OK`:

| Row | When | Blocking | What to do |
|---|---|---|---|
| `docker`: `not available` (`FAIL`) | the docker daemon does not answer | yes: every otterdog command runs in the docker image of its SUT | start docker, or set `E2E_CLI_RUNTIME=host` ([below](#the-unshare-row-on-ubuntu)) |
| `env:app`: `E2E_APP_ID not set` | every instance but the one of the `webapp` shard: the App is installed on one organization | no: the webapp and webhooks tiers are skipped there, and the shards give all their items to `webapp` | nothing |
| `unshare`: `user namespaces unavailable` | only with `E2E_CLI_RUNTIME=host`, on Ubuntu 24.04 ([below](#the-unshare-row-on-ubuntu)); by default the row is `OK`, `not needed` | not locally: offline commands of trusted SUTs run on the host without a network sandbox; `FAIL` in CI, where offline commands are refused | leave `E2E_CLI_RUNTIME` unset, or allow `unshare` |
| `account:<role>`: `not checked (anonymous rate limit)` | doctor ran several times within an hour: each `account:` row reads a public profile anonymously, 60 requests per hour per IP address, six per instance (30 for five shards) | no: only this check is missing | run doctor again an hour later; an account shared by several instances shows its state in their other tables |
| `account:<role>`: `flagged by GitHub` | GitHub hid the profile of the account | can be: a flagged account cannot join an organization, or its comments are hidden | the `fix:` line |
| `web:browser`: `no Playwright Firefox` | on the instance with the web login (`org-level`), before its first web session | no: the first web session installs it | once per machine, its system libraries: `sudo <venv>/bin/python -m playwright install-deps firefox` |
| `web:2fa`: `GET /user did not return two_factor_authentication` | the admin token lacks the `user` scope, without which `GET /user` leaves out the private fields | no, but doctor cannot tell whether 2FA is on | prove it with a web login ([below](#beyond-doctor)) |
| `token:<role>`: `(in <n> day(s))` | a token expires within 14 days | not yet | `otterdog-acceptance setup --target <instance> --rotate <role>` |
| `app:deliveries`: `no delivery in the last 72 h` | the App received no event recently | not by itself | check that the App webhook is active and subscribed to the events |
| `unmanaged:repos`, `unmanaged:teams` | repositories or teams neither protected, in the baseline nor created by a run | teams: baseline resets refuse to delete them | the `fix:` line |

## The unshare row on Ubuntu

By default every otterdog command runs in the docker image of its SUT, offline commands with `--network none`, and
the row says `not needed`. `E2E_CLI_RUNTIME=host` (exported, or in the env file of the instance) installs trusted SUTs
in a host virtualenv instead, a little faster, whose offline commands run in an `unshare -rn` sandbox; the rest of this
section is about that mode. The web mode of the web-UI tier always runs on the host, with live commands only.

Ubuntu 24.04 restricts unprivileged user namespaces (`kernel.apparmor_restrict_unprivileged_userns = 1`). A program
without an AppArmor profile that allows them gets no capability in the namespace it creates, so `unshare -rn true`
fails with `write failed /proc/self/uid_map: Operation not permitted` and the kernel log (`journalctl -k | grep
unshare`) shows:

```text
apparmor="DENIED" operation="capable" profile="unprivileged_userns" comm="unshare" capname="sys_admin"
```

The result depends on the shell. A shell whose `cat /proc/self/attr/current` prints `unconfined` fails; a terminal of
the VS Code snap runs under the profile of the snap (`snap.code.code`, complain mode) and passes. doctor can therefore
show `unshare OK` in one terminal and `WARN` in another on the same machine.

Either fix needs root:

- a profile that lets `unshare` alone create user namespaces, like the ones Ubuntu ships for browsers and VS Code
  (`/etc/apparmor.d/code`). Any program can then create user namespaces through `/usr/bin/unshare`, which partly
  reopens what the restriction closes:

  ```bash
  sudo tee /etc/apparmor.d/unshare-userns >/dev/null <<'EOF'
  abi <abi/4.0>,
  include <tunables/global>

  profile unshare-userns /usr/bin/unshare flags=(unconfined) {
    userns,

    include if exists <local/unshare-userns>
  }
  EOF
  sudo apparmor_parser -r /etc/apparmor.d/unshare-userns
  ```

- or the restriction lifted for every program:

  ```bash
  echo 'kernel.apparmor_restrict_unprivileged_userns = 0' | sudo tee /etc/sysctl.d/60-userns.conf
  sudo sysctl --system
  ```

Then `unshare -rn true && echo sandbox ok` and doctor shows `unshare OK`. Without a fix, local runs go on: offline
commands of trusted SUTs log `unshare -rn is unavailable: offline otterdog commands run without a network sandbox`.
With `CI` set, the harness refuses them (`SafetyError`).

## Beyond doctor

Three runs, cheapest first; each one proves what the previous one cannot.

1. **The smoke test on every organization**: the SUT's `--version`, `check-token-permissions` and `list-projects`
   against each organization.

   ```bash
   otterdog-acceptance run --target @shards --suite cli --scenario cli.smoke --no-reset --parallel 5
   ```

   An explicit `--scenario` is never filtered by shard, so every instance runs it; the first run of a SUT builds its
   docker image, reused afterwards. It changes no setting
   (`--no-reset` skips the baseline reset); like every live session it takes the org lease (the branch `e2e-lease`)
   and tags the run ledger (`e2e-run/<run id>`) in the configs repository. Every target should pass with no skipped
   item. A skip states its reason; `github rate budget: core remaining ...` means an identity has fewer requests left
   than `E2E_MIN_RATE_REMAINING`, and the live items of the session are skipped until its budget recovers.

2. **A web login** on the instance with the web credentials (`org-level`): it installs the SUT's Playwright Firefox,
   then logs in as the admin with its password and a TOTP code, which proves the `web:browser` and `web:2fa` rows. It
   opens a visible browser (a display is needed) and logs out at once
   ([running the web-UI tier locally](web-ui-testing.md#running-it-locally)):

   ```bash
   E2E_WEB_LOGIN=1 E2E_ALLOW_WEB_UI=1 otterdog-acceptance run --target org-level --suite cli \
     --scenario webui.cmd.web-login tests/web_ui
   ```

3. **The live tiers on every shard**, the run the shards are made for:

   ```bash
   otterdog-acceptance run --target @shards --suite cli,webhooks,webapp,enterprise --parallel 5
   ```

## In CI

The workflows of `.github/workflows` run the same sessions on GitHub-hosted runners: `nightly.yml` every night on the
instances of the repository variable `E2E_TARGETS` (`release:latest`, then `branch:main` against it, then the
optional web-UI lane), `janitor.yml` every six hours, `e2e.yml` and `e2e-webui.yml` on demand. Their scheduled runs are
skipped while `E2E_TARGETS` is unset. Each instance needs its GitHub environments, which `ci-sync` creates from its env
file, `E2E_SHARD` included, so that each job runs the share of its shard ([CI: ci-sync](onboarding.md#ci-ci-sync),
[CI environments](security.md#ci-environments)).

1. **The environments of every shard**, from your own terminal: ci-sync writes with your `gh` login (admin of the
   repository) and resolves `pass:` and `bitwarden:` references with your own access. A dry run first, which prints
   names only, then the changes; `--nightly` adds each instance to `E2E_TARGETS`, which starts the scheduled runs:

   ```bash
   for i in $(grep -v '^#' ~/.config/otterdog-acceptance/lists/shards); do
     otterdog-acceptance ci-sync --target "$i" --nightly
   done
   for i in $(grep -v '^#' ~/.config/otterdog-acceptance/lists/shards); do
     otterdog-acceptance ci-sync --target "$i" --nightly --allow-self-review --apply
   done
   ```

   `e2e-<instance>-untrusted`, the environment of the otterdog pull requests, waits for an approval that the person
   who started the run cannot give: name another maintainer with `--reviewer <login>` instead of
   `--allow-self-review` when there is one. `e2e-org-level-webui` is created for the only instance with the web login.

2. **The nightly web-UI lane**, on that instance (repository variables, set by hand):

   ```bash
   gh variable set E2E_WEB_UI_ENABLED --body true
   gh variable set E2E_WEB_UI_TARGETS --body '["org-level"]'
   ```

3. **A first run**: the smoke test on every instance, then the nightly lanes once without waiting for the night
   (`target` takes at most 8 instances):

   ```bash
   gh workflow run e2e.yml -f target=enterprise,free,webapp,org-level,automation -f sut=release:latest \
     -f scenario=cli.smoke
   gh run watch
   gh workflow run nightly.yml
   ```

Every workflow of `main` can read the secrets of these environments, which only deploy from `main`: the security
model protects `main` with a ruleset (pull request with review, no bypass), see
[CI environments](security.md#ci-environments).

### The whole suite on demand

Each workflow also starts by hand, from the Actions tab of the repository (Run workflow) or with `gh workflow run`
from a checkout of it; a run takes the workflows and the harness of `main`. Runs of one instance never overlap: they
share the concurrency group `e2e-<instance>` with the nightly runs and the janitor, and wait for each other.

- **Everything, as at night**: `nightly.yml` has no input. On each instance of `E2E_TARGETS`, `release:latest` (the
  offline and live tiers), then `branch:main` against `release:latest` (the differential tier added), then the web-UI
  tier on the instances of `E2E_WEB_UI_TARGETS` when `E2E_WEB_UI_ENABLED` is `true`:

  ```bash
  gh workflow run nightly.yml
  gh run watch
  ```

- **One SUT on chosen instances**: `e2e.yml`, one job per instance, in parallel. Without `suites` it runs the default
  tiers of `run` (offline, cli, webhooks, webapp and enterprise, plus the differential with a `base_sut`), each
  instance the live items of its shard:

  ```bash
  gh workflow run e2e.yml -f target=enterprise,free,webapp,org-level,automation -f sut=release:latest
  gh workflow run e2e.yml -f target=enterprise,free,webapp,org-level,automation -f sut=branch:main \
    -f base_sut=release:latest
  ```

  | Input | Value |
  |---|---|
  | `target` | instances, comma separated, at most 8, each in the allowlist `E2E_INSTANCES` (default `free`) |
  | `sut` | `release:latest` (default), `tag:vX.Y.Z`, `branch:main`, `sha:<hex>` or `pr:<N>@<40-hex sha>`; an untrusted SUT waits for an approval of `e2e-<instance>-untrusted` |
  | `base_sut` | the base of the differential tier (`auto`: the merge base of a `pr:` SUT); empty: no differential |
  | `suites` | comma separated tiers instead of the default; `auto`, for a `pr:` SUT only, picks them from its changed files |
  | `tags`, `scenario`, `k` | narrow the selection: scenario tags, scenario id globs (`cli.smoke`), a pytest `-k` expression |
  | `lane` | `nightly-full` (default) or `pr-fast`: the time budgets the report checks |
  | `strict_diff` | fail on unexpected differential deltas |

- **The web-UI tier**: its own workflow and environment (`e2e-<instance>-webui`), trusted SUTs only, one instance at a
  time ([web-ui-testing.md](web-ui-testing.md)):

  ```bash
  gh workflow run e2e-webui.yml -f target=org-level -f sut=release:latest
  ```

- **A pull request of otterdog**, pinned to the commit you reviewed, after an approval of the untrusted environments
  ([testing an otterdog PR](testing-an-otterdog-pr.md#in-ci)):

  ```bash
  gh workflow run e2e-otterdog-pr.yml -f pr=<N> -f sha=<40-hex sha> -f target=enterprise,free,webapp,org-level,automation
  ```

Each job writes the report of its instance (`summary.md`) to its job summary and uploads the artifacts of its run,
kept 7 days, once `scrub-artifacts` found no secret in them: `gh run download <run id>` fetches them.
