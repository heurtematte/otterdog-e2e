# Web-UI testing

Some otterdog features are only reachable through the GitHub web UI: otterdog drives github.com with Playwright
(Firefox), logged in as a bot owner with a username, a password and a TOTP code. The token tiers never see them:
every live command of the harness uses `-n` (`--no-web-ui`) and the webapp always applies with `no_web_ui=True`. The
web-UI tier (`tests/web_ui`, package `otterdog_e2e.webui`) covers them.

| Feature | otterdog | How the harness tests it |
|---|---|---|
| 12 organization settings (schema provider `web`) | `plan`, `apply`, `import`, `show-live`, `check-status` without `-n` | the settings round trip, the import test |
| install / uninstall a GitHub App | `install-app`, `uninstall-app` | with a harmless probe App (known bug KB-002) |
| pending App permission requests | `review-permissions` (never `-g`) | read-only listing |
| latest comment of security advisories | `list-advisories -w` | CSV check |
| a browser logged in as the bot | `web-login` | local runs with a display only |
| the webapp never uses the UI | webapp validation, merge, apply | `W-PR-WEBUI` in the webapp tier (no web login) |

## Strategy

1. **otterdog itself drives the UI.** The SUT runs `plan`/`apply`/`import` WITHOUT `-n` (`WebOtterdogCli`), with the
   admin machine account's web login. The harness never automates the browser itself.
2. **Independent oracles check the result.** 7 of the 12 settings are readable through REST (`GET /orgs/{org}` with
   the owner token, `admin:org`); the 5 others are read by a TRUSTED otterdog release (the reset SUT, never the SUT
   under test) through its own web reader (`show-live` without `-n`). Before anything changes, both oracles must agree
   on the overlapping keys.
3. **The webapp never uses the UI.** A config PR touching a web-only setting is flagged ("require accessing the Web
   UI, need to apply these changes manually"), is not auto-mergeable, is applied partially once merged, and the live
   setting stays unchanged (REST); `/otterdog done` completes it (`tests/webapp/test_web_ui_flags.py`).
4. **UI-driven CLI commands** run against the test organization; `web-login` is interactive (local only).

## The 12 web-only settings

Verified against otterdog main 9bdeb75 and v1.6.0/v1.6.1 (`otterdog/resources/schemas/settings.json`,
`otterdog/resources/github-web-settings.jsonnet`, `otterdog/models/organization_settings.py`) and the REST OpenAPI
description (`components.schemas.organization-full`). `webui.mapping.WEB_SETTINGS` encodes it; the test
`webui.settings.table` re-checks it against the source of every SUT, so a release that adds, renames or fixes a web
setting is reported.

| Setting | Settings page | REST field (read-only) | Round trip |
|---|---|---|---|
| `members_can_change_repo_visibility` | `member_privileges` | `members_can_change_repo_visibility` | negated |
| `members_can_delete_repositories` | `member_privileges` | `members_can_delete_repositories` | negated |
| `members_can_delete_issues` | `member_privileges` | `members_can_delete_issues` | negated |
| `readers_can_create_discussions` | `member_privileges` (optional input) | `readers_can_create_discussions` | negated |
| `members_can_create_teams` | `member_privileges` | `members_can_create_teams` | negated |
| `two_factor_requirement` | `security` | `two_factor_requirement_enabled` | never (see below) |
| `default_branch_name` | `repository-defaults` | `default_repository_branch` | `e2e-<run>` |
| `packages_containers_public` | `packages` | - | negated |
| `packages_containers_internal` | `packages` | - | negated, Enterprise Cloud only |
| `members_can_change_project_visibility` | `projects` | - | negated |
| `has_discussions` | `discussions` | - | switched, with a fixture repository as source |
| `discussion_source_repository` | `discussions` (select menu) | - | `<org>/<first fixture repo>` or null |

Findings:

* `PATCH /orgs/{org}` accepts none of these fields: REST can read 7 of them but never change one, so the harness cannot
  restore them through the API either; every restore goes through otterdog's web client.
* `two_factor_requirement` is never read by otterdog: its web definition is named `two_factor_required`, so the
  security page is never loaded and the value stays UNSET; the model marks it read-only. The harness reads it
  through REST only and never toggles it: requiring 2FA removes every member without 2FA from the organization.
* While `has_discussions` is false otterdog ignores `discussion_source_repository`; enabling discussions also sets
  `has_discussions` on the source repository (the baseline reset puts it back).
* The definition file also holds `default_workflow_permissions` (settings/actions), managed through REST since the
  `workflows` settings; it is not a web setting.

## Scenarios

| Scenario | Test | Logins | What |
|---|---|---|---|
| `webui.settings.table` | `tests/web_ui/test_web_settings.py` | 0 | the table matches the SUT's schema and web definitions |
| `webui.settings.round-trip` | `tests/web_ui/test_web_settings.py` | 8 | every settings change of the run, in one scenario (below) |
| `webui.import.web-settings` | `tests/web_ui/test_web_settings.py` | 1 | `import` without `-n` writes the REST-readable values GitHub reports (`show --local` evaluates the import) |
| `webui.kb.import-two-factor` | `tests/web_ui/test_web_settings.py` | 0 (the import's login) | the same import must carry the live `two_factor_requirement`; non-strict xfail KB-041, skipped when the live value equals the template default |
| `webui.cmd.review-permissions` | `tests/web_ui/test_web_commands.py` | 1 | logs in, reads the installations page, approves nothing |
| `webui.cmd.list-advisories` | `tests/web_ui/test_web_commands.py` | 0-1 | `list-advisories -w -s all` CSV (logs in only when the org has advisories) |
| `webui.cmd.install-app` | `tests/web_ui/test_web_commands.py` | 0-2 | `install-app` then `uninstall-app` of the probe App, verified through `GET /orgs/{org}/installations`; non-strict xfail KB-002 |
| `webui.cmd.web-login` | `tests/web_ui/test_web_commands.py` | 1 | `web-login` opens a visible browser and logs out at once; local, display and `E2E_WEB_LOGIN=1` only |
| `webui.cmd.install-deps` | `tests/web_ui/test_web_commands.py` | 0 | `install-deps` with the tier's browsers dir succeeds offline without a new Firefox build; with an empty browsers dir and no network it reports 'could not install required dependencies' and installs nothing |
| `webui.kb.install-deps-exit-code` | `tests/web_ui/test_web_commands.py` | 0 | a failed installation must exit non-zero; non-strict xfail KB-047 |
| `W-PR-WEBUI` | `tests/webapp/test_web_ui_flags.py` | 0 | the webapp side (runs in the normal webapp tier, needs the App and docker, no web credentials) |

The round trip (`webui.roundtrip.WebSettingsRoundTrip`):

1. **snapshot**: REST and the trusted reader; a disagreement stops everything before any change;
2. **set**: the SUT applies the baseline with every writable web setting pinned (`key::: <value>`) to its toggled
   value; its plan must change exactly the toggled keys (a setting its web reader misses shows up here);
3. **verify**: REST (polled) and the trusted reader see the toggled values;
4. **converge**: the SUT's own `plan` without `-n` is a no-op for every web key;
5. **restore** with the SUT, then 6. **verify** again; when the SUT cannot restore, the TRUSTED CLI does
   (`BaselineManager.restore_web_settings`) and both oracles verify it once more.

The original values are recorded before step 2 in the `BaselineManager` (the baseline teardown restores them with the
trusted CLI when the scenario could not) and in `<E2E_CACHE_DIR>/webui/pending-restore-<org id>.json` (a killed
session: the next round trip on the machine restores them first). Evidence: `<artifacts>/<run>/webui/*.json`.

The keys REST cannot read (`has_discussions`, `discussion_source_repository`, `members_can_change_project_visibility`,
`packages_containers_internal`, `packages_containers_public`) are verified by the trusted reader only. When the reset
SUT runs the same commit as the SUT under test (the default: both `release:latest`), that reader is the code under
test, so a symmetric bug of otterdog's web reader and writer would pass: the report lists such keys as
`self_checked`, and the coverage matrix counts them as partial until an independent read exists. Run the tier with
another `--reset-sut` (or a SUT that differs from the reset SUT) to cross-check them.

## Gating and safety

`Cap.WEB_UI` (and the `web_ui` marker every item of `tests/web_ui` gets) requires, checked in `pytest_runtest_setup`
before any fixture:

* the admin bot's web credentials (`E2E_ADMIN_PASSWORD` and `E2E_ADMIN_TOTP_SEED`, complete and valid);
* `--e2e-allow-web-ui` (or `E2E_ALLOW_WEB_UI=1` in the process environment): web logins are never a side effect of
  having credentials in an env file;
* a trusted SUT under test (`release`, `tag`, `branch:main`, reachable `sha`, `path`, `dirty`; never `pr:` or an
  untrusted `sha:`, even with `--e2e-trust-code`);
* `github.saml_sso: false`: otterdog's web client cannot log in through SAML SSO;
* web logins not blocked (below).

The target overrides can remove `web_ui` but never add it. Every reason a web test is skipped is printed.

Credentials:

* they belong to the admin machine account (the token otterdog uses and the web login are the same account; a
  username that is a login must be the declared admin login, an email is accepted as is);
* they are resolved apart from the identity tokens (`settings.WebCredentials`) and reach otterdog only for the
  commands that log in (`runner.WEB_LOGIN_COMMANDS`), through the `E2E_OTTERDOG_USERNAME/PASSWORD/TOTP_SEED`
  variables of the env credential provider; every other command, and every ordinary CLI, gets `unset`;
* `WebOtterdogCli` refuses container runtimes, untrusted SUTs and other identities; the plugin never builds a web
  CLI for the SUT of an untrusted lane, and the CI lane refuses untrusted SUTs before any environment;
* the password and the seed (raw and normalized) are registered with the redactor; otterdog never gets more than `-v`
  (`-vvv` would log TOTP codes and exception locals holding the credentials);
* otterdog's Playwright page dumps (`web_*.html`, `web_*.png`, written into its cwd at `-vv` and more, which live
  commands never get) stay in the private scratch directory and are never exported (the scrubber deletes such files
  anyway).

The login gate (`webui.gate.LoginGate`, `<E2E_CACHE_DIR>/webui/<login>.{lock,json}`):

* a file lock serializes the web commands of every harness process of the machine;
* the next web command starts at least `E2E_WEB_LOGIN_SPACING` seconds (default 32, never below one TOTP window) after
  the END of the previous one: otterdog only avoids reusing a TOTP code inside one process, and GitHub refuses a code
  that was already used;
* a blocking failure (wrong username or password, too many failed attempts, a TOTP rejection, an unexpected page after
  the login, SSO, another account) blocks further logins (6 h, 1 h for a TOTP rejection, 24 h for SSO): the
  remaining web tests skip instead of locking the bot out. `doctor` shows the block and the file to delete once the
  account is checked.

## Setup

### The bot account

Use the admin machine account of the target (an owner of the test organization, member of test organizations only):

1. sign in once in a browser as the bot and enable two-factor authentication with an **authenticator app**: on the
   "Scan the QR code" page choose "setup key" and store the base32 key (or the `otpauth://` URI) in your password
   manager, then finish the setup with a code; keep the recovery codes;
2. keep the authenticator app as the preferred 2FA method and add no passkey, security key or SMS: otterdog types a
   TOTP code on `https://github.com/sessions/two-factor/app`;
3. sign out, then check the login once with `otterdog web-login` on your machine (below): it shows every interstitial
   GitHub may present ("Verify 2FA now", "Confirm your account recovery settings");
4. `doctor --target <t>` checks the variables, the seed, the bot's 2FA (`GET /user`), SSO, the browser and the gate.

### Environment

| Variable | Meaning |
|---|---|
| `E2E_ADMIN_PASSWORD` | password of the admin bot (secret) |
| `E2E_ADMIN_TOTP_SEED` | base32 setup key of its authenticator app, or the `otpauth://totp/...` URI (secret; spaces, dashes and case are normalized) |
| `E2E_ADMIN_USERNAME` | optional: the username typed on github.com/login (default: `E2E_ADMIN_LOGIN`; may be the account's email) |
| `E2E_ALLOW_WEB_UI` | process environment only: `1`/`true` = `--e2e-allow-web-ui` |
| `E2E_WEB_LOGIN_SPACING` | optional: seconds between two web logins (default 32) |
| `E2E_WEB_LOGIN` | process environment only: `1` lets the `web-login` test open a visible browser |
| `E2E_WEB_READER` | process environment only: `import` makes the trusted reader use `import` + `show --local` instead of `show-live` (keys the import leaves at the template default are dropped) |

Put the secrets in `~/.config/otterdog-e2e/<target>.env` (chmod 600) like the tokens. Other variable names can be
declared in the target: `identities.admin.username_env`, `password_env` (must end with `_PASSWORD`) and
`totp_seed_env` (must end with `_TOTP_SEED`). `github.saml_sso: true` disables the tier for a target;
`web_ui.probe_app_slug` names the probe App.

### The probe App (optional)

`webui.cmd.install-app` installs and uninstalls an App: create a second, harmless GitHub App owned by the test
organization (no permissions, webhook inactive, "Only on this account"), keep it NOT installed, and set
`web_ui.probe_app_slug` in the target. Never use the e2e App (the target loader refuses it): uninstalling it would
break the webapp and webhooks tiers. Since otterdog #693/#699 both commands resolve token-only credentials and fail
with "username not available" (KB-002, a non-strict xfail: an XPASS reveals the fix).

### Playwright Firefox

The first web session installs the Firefox build of each trusted SUT's own Playwright into
`<E2E_CACHE_DIR>/ms-playwright` (`<venv>/bin/python -m playwright install firefox`, what `otterdog install-deps`
does; never for untrusted SUTs). Its system libraries need root once per machine:
`sudo <venv>/bin/python -m playwright install-deps firefox` (the CI lane does it with a throwaway venv before any SUT
code runs). `doctor` reports the installed builds.

### CI

`.github/workflows/e2e-webui.yml` (dispatch, or the nightly `webui` job when the repository variable
`E2E_WEB_UI_ENABLED` is `true`, for the targets of `E2E_WEB_UI_TARGETS`, default `["free"]`):

* a `classify` job without secrets refuses untrusted SUTs and `pr:`/`path:`/`dirty:` specs;
* the `webui` job runs in the environment **`e2e-<target>-webui`**, the only one holding `E2E_ADMIN_PASSWORD` and
  `E2E_ADMIN_TOTP_SEED` (plus `E2E_ADMIN_TOKEN`, optionally `E2E_ORACLE_TOKEN`, and the variables of `e2e-<target>`,
  optionally `E2E_ADMIN_USERNAME` and `E2E_WEB_LOGIN_SPACING`). Protect it like `e2e-<target>` (deployment branches:
  `main` only; required reviewers are possible for dispatched runs, they would block the nightly job);
* it joins the concurrency group `e2e-<target>` (never in parallel with another session of the org) and runs
  `otterdog-e2e run --target <t> --sut <s> --suite cli --scenario 'webui.*' tests/web_ui` with `E2E_ALLOW_WEB_UI=true`,
  then the janitor, the scrub and the upload, like `e2e.yml`.

Never add the web credentials to `e2e-<target>` or `e2e-<target>-untrusted` (`tests/unit/test_webui_workflow.py`
checks that no other workflow references them). `W-PR-WEBUI` needs no web credentials and runs in the normal webapp
tier of `e2e.yml`.

## Running it locally

```bash
.venv/bin/otterdog-e2e doctor --target free                       # web:* rows (never logs in)
E2E_ALLOW_WEB_UI=1 .venv/bin/otterdog-e2e run --target free --suite cli --scenario 'webui.*' tests/web_ui
# one scenario
E2E_ALLOW_WEB_UI=1 .venv/bin/otterdog-e2e run --target free --suite cli --scenario webui.settings.round-trip tests/web_ui
# the bot's browser session (visible window, closes at once)
E2E_WEB_LOGIN=1 E2E_ALLOW_WEB_UI=1 .venv/bin/otterdog-e2e run --target free --suite cli --scenario webui.cmd.web-login tests/web_ui
# pytest directly works too
.venv/bin/pytest tests/web_ui --e2e-target free --e2e-allow-web-ui -p no:cacheprovider
```

`--suite cli` only provides the scenario ids that `--scenario 'webui.*'` deselects; `tests/web_ui` is not a suite of
`run` yet. A SUT under test that is not trusted makes every web test skip with the reason. The reset SUT
(`--reset-sut`, default `release:latest`) is the trusted reader.

## Costs

| Item | Logins |
|---|---|
| settings round trip | 8 (snapshot 1, set 2, verify 1, converge 1, restore 2, verify 1), +3 with the trusted fallback restore |
| import | 1 |
| review-permissions | 1 |
| list-advisories -w | 0-1 |
| install-app / uninstall-app | 0 today (KB-002), 2 once fixed |
| web-login (local) | 1 |

About a dozen logins per run, at least 32 s apart: 6 to 7 minutes of spacing plus the browser runs (each web command
starts Firefox and loads several settings pages), 15 to 25 minutes in total. REST usage is negligible. The tier runs
nightly at most; `run.json` (`web_ui`) records the logins and the time spent waiting for the gate.

## Risks

| Risk | Mitigation |
|---|---|
| Account lockout after failed logins | the gate blocks after the first blocking failure; `doctor` shows it; check the account before deleting `<E2E_CACHE_DIR>/webui/<login>.json` |
| TOTP code reuse | one web login at a time on a machine, a TOTP window apart; one bot per target, never the same bot from CI and a workstation at the same time (the org lease serializes sessions of one org only) |
| Login challenges (device verification, passkey prompts, a new 2FA method, "unusual activity" checks of datacenter IPs) | classified as `challenge` (blocking); log in once interactively (`web-login`), keep TOTP the only 2FA method; CI runners may be challenged more often |
| SAML SSO | `github.saml_sso: true` skips the tier |
| GitHub changes the settings pages | that is what the tier detects: otterdog's selectors fail (`failed to retrieve setting ... via web ui`), the round trip reports the keys |
| Settings left toggled | first-record-wins snapshot, trusted fallback restore, session-end restore, persisted pending restore |
| Credentials reaching PR code | trusted SUTs only, host CLIs only, a separate CI environment, refusals in `WebOtterdogCli`, redaction |
| Organization damage | `two_factor_requirement` never toggled; only org-level settings and one fixture repository's discussions change, all restored |

## Recovery

* "ORIGINAL VALUES NOT RESTORED" (round trip summary) or "the web-only org settings ... may still differ" (session
  log): the original values are in the log, in `<artifacts>/<run>/webui/settings-round-trip.json` and, on the
  machine of the run, in `<E2E_CACHE_DIR>/webui/pending-restore-<org id>.json`; the next round trip on that machine
  restores them first. Otherwise restore them in the GitHub UI (Organization settings: Member privileges, Repository
  defaults, Packages, Discussions, Projects).
* "web logins of &lt;bot&gt; are blocked until ...": sign in as the bot in a browser, fix the cause (password, seed, a
  pending verification), then delete `<E2E_CACHE_DIR>/webui/<login>.json` (or wait for the block to expire).
* A locked-out bot: wait for GitHub's lockout to end; recovery codes or a password reset if needed; never retry in a
  loop.
