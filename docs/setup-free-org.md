# Setting up a GitHub Free test organization

The fast path is [onboarding.md](onboarding.md): `otterdog-e2e setup --target <instance>` asks for everything below
interactively (prefilled token URLs, checks, env file, App, bootstrap), and `otterdog-e2e ci-sync` creates the CI
environments. This page is the reference of the same steps done by hand.

This guide prepares an instance of the profile `free` (`targets/free.yaml`): a dedicated GitHub Free organization,
its machine accounts and tokens, the harness repositories and teams, and the GitHub App of the webapp tiers. The
examples use the instance `free`, which is bound to the profile of the same name. Any other instance name works the
same way with `E2E_PROFILE=free` in its env file, for example `--target acme-a` and
`~/.config/otterdog-e2e/acme-a.env` (names: lower-case letters, digits and `-`, at most 39 characters, not ending
with `-untrusted` or `-webui`, not `lists`; [onboarding.md](onboarding.md#instances-and-profiles)). Budget about an
hour the first time. Commands assume the repository root and `make init` done.

## 1. Machine accounts

Create dedicated GitHub accounts (machine accounts, following GitHub's terms of service: a human creates each account
and is responsible for it, and a person may hold at most one free machine account besides their own account, see
[What cannot be automated](onboarding.md#what-cannot-be-automated)). They must never belong to, collaborate on, or be
invited to any organization other than your test organizations: the harness checks their memberships on every run
and refuses the session otherwise.

| Role | Required | Purpose | Membership |
|---|---|---|---|
| `admin` | yes | owner of the test org; runs otterdog, resets the org, creates the App | owner |
| `author` | for webapp flows | opens config PRs as a plain member | member (public), contributors team |
| `approver` | for approval / auto-merge flows | approves config PRs | member (public), approval team |
| `outsider` | for negative tests | comments as a non-member | **not** a member |
| `config_reader` | for webapp tests of untrusted SUTs | powerless token given to the webapp under test (`OTTERDOG_CONFIG_TOKEN`), worthless if an untrusted SUT leaks it | none: not a member |
| `oracle` | optional | separate read-only ground truth (falls back to admin) | owner |

What each role does in the tests, what is skipped without it, and how the roles interact with otterdog and the
organization: [roles.md](roles.md).

For every account:

- enable two-factor authentication and keep the recovery codes in your password manager (the token tiers never use
  passwords or TOTP seeds; only the optional web-UI tier logs the admin account in, see
  [10. Web-UI tier](#10-web-ui-tier-optional));
- give it **prior public activity**: push at least one commit to a public repository owned by the account before
  using it. GitHub tags the pull requests of an account that never committed anything as `FIRST_TIMER`, a value
  otterdog's webhook models do not accept, so the webapp would ignore its PRs;
- one token per account and role: two roles never share a token (only `oracle` may be omitted and fall back to
  `admin`), and two roles never declare the same login (compared case-insensitively; only `admin` and `oracle` may
  be one account): a target declaring one login twice does not load.

## 2. The organization

1. Signed in as the admin account, create the organization on the Free plan:
   https://github.com/account/organizations/new?plan=free. Pick a name that is clearly a test organization (names
   of real organizations such as `eclipse-*`, `eclipsefdn*`, `adoptium`, `jakartaee*` are refused).
2. Keep it empty: no repositories, no teams, no organization secrets or variables. The harness refuses to mark an
   organization holding repositories it does not manage, and every reset fails while an unmanaged organization-level
   object exists.
3. Do not enable SAML SSO or IP allow lists (see [setup-enterprise-org.md](setup-enterprise-org.md) for those).
4. Note the exact-case login and the numeric id:

    ```bash
    curl -s https://api.github.com/orgs/<org> | jq '{login, id}'
    ```

## 3. Tokens

Classic PATs are created in each account's settings (Developer settings, Personal access tokens, Tokens (classic));
set an expiry and a reminder to rotate them. `setup` prints a creation URL per role with these scopes preselected
(`https://github.com/settings/tokens/new?scopes=...`), see [onboarding.md](onboarding.md#tokens).

| Identity | Token | Scopes |
|---|---|---|
| admin | classic | `repo`, `workflow`, `admin:org`, `admin:org_hook`, `delete_repo` (nothing else; `read:user` and `user:email` are tolerated) |
| oracle | classic | `repo`, `admin:org`, `admin:org_hook` |
| author, approver, outsider | classic | `public_repo`, `read:org` |
| config_reader | fine-grained | resource owner: the config_reader account itself; repository access: "Public repositories"; no permissions |

Every classic token needs `read:org`, given directly or through `admin:org`: the isolation check lists
`GET /user/orgs`, which answers 403 without it. Any scope outside the role's allowlist fails the session (see
[security.md](security.md#dedicated-machine-accounts-t1-t2)).

Organizations or enterprises that forbid classic PATs can use fine-grained personal access tokens for every role
except the `outsider`: see [Fine-grained personal access tokens](#fine-grained-personal-access-tokens) below.

## 4. Environment file

`setup` writes this file for you (mode 0600). By hand:

```bash
install -d -m 700 ~/.config/otterdog-e2e
install -m 600 .env.example ~/.config/otterdog-e2e/free.env
$EDITOR ~/.config/otterdog-e2e/free.env
```

Uncomment and fill at least:

```bash
# E2E_PROFILE=free                    # needed for any instance not named after its profile (acme-a.env)
E2E_ORG=my-otterdog-e2e-free          # exact-case login
E2E_ORG_ID=123456789                  # numeric id from step 2
E2E_ADMIN_LOGIN=my-e2e-admin
E2E_ADMIN_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
E2E_AUTHOR_LOGIN=my-e2e-author
E2E_AUTHOR_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
E2E_APPROVER_LOGIN=my-e2e-approver
E2E_APPROVER_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
E2E_OUTSIDER_LOGIN=my-e2e-outsider
E2E_OUTSIDER_TOKEN=ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
E2E_CONFIG_READER_LOGIN=my-e2e-reader
E2E_CONFIG_READER_TOKEN=github_pat_xxxxxxxxxxxxxxxxxxxxxx
```

Notes:

- files are read in this order and the first value wins: `~/.config/otterdog-e2e/free.env`, `.env.e2e.free`,
  `.env.e2e` (for the instance `acme-a`: `acme-a.env`, `.env.e2e.acme-a`, `.env.e2e`); an exported variable always
  wins over every file. There is no `${...}` interpolation in env files;
- if the same machine accounts also serve another test organization (for example the enterprise instance), list the
  other organization's id in `E2E_ALLOWED_ORG_IDS` (comma separated) in both instances' files. Setup offers it for a
  classic token (default No) only when the other organization is already a set up and bootstrapped instance, and
  writes it once the token passed every check ([onboarding.md](onboarding.md#tokens)); otherwise set it by hand;
- per-instance values of the profile: `E2E_SAML_SSO`, `E2E_CAPABILITIES_ADD`, `E2E_CAPABILITIES_REMOVE`,
  `E2E_WEB_PROBE_APP_SLUG` ([.env.example](../.env.example));
- `otterdog-e2e targets` lists the instances found and their profile, organization and env file;
- process options (`E2E_TARGET`, `E2E_SUT`, `E2E_CACHE_DIR`, `E2E_ARTIFACTS`, ...) are not read from env files:
  export them or use the command line flags;
- in a custom target file, quote `${...}` values inside YAML flow mappings (`{login: "${E2E_X}"}`), and keep the
  `*_env` names ending with `_TOKEN`, `_SECRET`, `_PASSWORD`, `_TOTP_SEED` or `_PRIVATE_KEY` so their values are
  redacted.

## 5. First doctor run

```bash
.venv/bin/otterdog-e2e doctor --target free
```

doctor is read-only. On a fresh organization expect `FAIL` rows for the marker, the repositories
(`otterdog-e2e-configs`, `otterdog-e2e-defaults`, `otterdog-e2e-fixture-a`) and the teams, plus `WARN` rows for the
missing App. Every row with a problem prints a `fix:` hint. Fix the identity, isolation and scope rows now: nothing
else can be checked without them.

## 6. Memberships

The author and the approver must be **active and public** members, a separate oracle an **active owner**, the
outsider must not be a member.

1. Invite the author and the approver (organization People page, Invite member), or let `bootstrap --apply` invite
   them. bootstrap invites a separate oracle account as an **owner** (an active member is promoted to owner, an
   existing membership is never demoted) only when the oracle has a token of its own (`E2E_ORACLE_TOKEN`) whose
   `GET /user` login is `E2E_ORACLE_LOGIN`: a declared login alone could name any account. Otherwise a bootstrap step
   says why the oracle is not invited nor promoted (no token of its own: the admin serves as oracle; a token of
   another account; `GET /user` failing). A fine-grained oracle token only works once the account is an owner: invite
   it as an Owner on the People page, or let `setup` do it ([onboarding.md](onboarding.md#tokens)).
2. Signed in as each of them, accept the invitation (`https://github.com/orgs/<org>/invitation`) and set the
   membership visibility to public on the organization's People page (`https://github.com/orgs/<org>/people`).

With their minimal scopes (`public_repo`, `read:org`: read-only access to memberships) the machine-account tokens are
usually refused when bootstrap tries to accept or publicize a membership through the API: bootstrap then prints the
step with both URLs (`accept the invitation at ... and make the membership public at ... in the web UI, logged in as
<login>`). Without `--wait` it goes on with the repositories, the lease, the baseline and the App; do it in the web UI
and run bootstrap again. With `--wait` (which needs `--apply`: a dry run with `--wait` is a usage error) it polls every
10 s until every invited account is active (and, for the author and the approver, public), for at most
`--wait-timeout` (default `30m`); a timeout or Ctrl-C stops it, and running it again resumes (every step is
idempotent). An invitation expires after 7 days: bootstrap then invites again.

## 7. Bootstrap

```bash
.venv/bin/otterdog-e2e bootstrap --target free                  # dry run: reports what it would do
.venv/bin/otterdog-e2e bootstrap --target free --apply          # asks you to type the organization login
.venv/bin/otterdog-e2e bootstrap --target free --apply --wait   # also waits for the invitations and the App
```

`setup` offers to run `bootstrap --apply --wait` itself. `bootstrap --apply` is idempotent and runs, in order:

1. verification of the organization (id, login, plan) and of the identities' isolation (a fine-grained token of the
   author, the approver or the oracle that cannot prove it yet gets the steps GitHub requires first: membership,
   then the owner's approval of a member's token);
2. the safety marker `[otterdog-e2e]` added to the organization description, after you typed the login (refused in
   CI, refused when the organization holds repositories the harness does not manage);
3. memberships: the admin must be an active owner; invitations for the author and the approver and, when it is a
   separate account whose own token proves its login, the oracle as an owner (all invited first, then accepted, and
   for the members made public, with their own tokens when GitHub lets them, else printed as manual steps with their
   URLs; `--wait` waits for them); the outsider must not be a member;
4. the public repositories `otterdog-e2e-configs` (the webapp's `otterdog.json`, the org lease and the run ledger) and
   `otterdog-e2e-defaults` (published templates);
5. the org lease, then the base template of the trusted reset SUT;
6. a baseline reset with the trusted reset SUT: teams `otterdog-admins` (admin), `project-leads` (approver),
   `e2e-contributors` (author), the fixture repository `otterdog-e2e-fixture-a`, organization settings;
7. the baseline pushed to a fixed org config repository (with the default `org_config_repo: auto` each session
   creates its own `e2e-<run>-config` repository instead; the one created by bootstrap's own baseline stays until
   the janitor removes it, after 6 hours);
8. with a GitHub App configured: `otterdog.json` written to the configs repository, the installation checked, and a
   delivery probe (a throwaway branch `e2e/<run>/bootstrap` pushed to the configs repository; its push delivery must
   show up in the App's delivery log within 300 s, the budget every delivery wait of the harness uses: GitHub may
   list deliveries a few minutes late, so a timeout points at a webhook problem only when it persists). An App that
   is not installed yet: bootstrap prints its installation URL
   (`https://github.com/apps/<slug>/installations/new/permissions?target_id=<org id>`) and stops, or with `--wait`
   polls until it is installed.

## 8. The GitHub App

The webapp and webhooks tiers need a GitHub App owned by the test organization. [github-app.md](github-app.md)
explains every detail. `setup` creates it, writes its keys into the instance env file, verifies it (owned by the test
organization, installed on test organizations only) and waits for its installation
([onboarding.md](onboarding.md#the-app-step)); the short version by hand:

```bash
.venv/bin/otterdog-e2e app-manifest --target free --webhook-url https://<a-sink-you-control>/otterdog-e2e
```

The webhook URL is only a **sink**: any HTTPS endpoint you control that answers 2xx, or a smee.io channel used only
as a sink (public: anyone with the URL can read the payloads). GitHub records every delivery, and the harness pulls
them from the deliveries API and relays them to the webapp under test; nothing ever needs to reach your machine.

1. Open the printed `http://127.0.0.1:8765/` URL in a browser signed in as the admin account and confirm the App.
2. The command exchanges the code and writes the private key, the webhook secret and an env snippet to
   `~/.config/otterdog-e2e/<instance>/` (here `~/.config/otterdog-e2e/free/`, mode 0600). Append the snippet:

    ```bash
    cat ~/.config/otterdog-e2e/free/app-<id>.env >> ~/.config/otterdog-e2e/free.env
    ```

3. Install the App on the organization for **All repositories** with the printed URL
   (`https://github.com/apps/<slug>/installations/new/permissions?target_id=<org id>`: the organization is
   preselected).
4. Run `bootstrap --target free --apply --wait` again: it waits for the installation if needed, writes
   `otterdog.json` and probes the deliveries.

## 9. Check and run

```bash
.venv/bin/otterdog-e2e doctor --target free    # every row OK (WARN rows explain what will be skipped)
make offline                                   # no GitHub involved
make cli TARGET=free                           # live CLI tier
make webhooks TARGET=free
make webapp TARGET=free                        # docker compose stack + relay
make report                                    # summary of the newest run
make cli TARGET=free,acme-a                    # several instances, one after the other (PARALLEL=2: at once)
```

Skipped tests always state why (missing capability, identity, App, docker, low rate budget). After a crash run
`make janitor TARGET=free` (dry run) and `make janitor TARGET=free APPLY=1`. Several instances in one command:
[onboarding.md](onboarding.md#running-on-one-organization-or-a-list).

## 10. Web-UI tier (optional)

The web-UI tier lets otterdog log in to github.com as the admin account to test the settings and commands only
reachable through the UI ([web-ui-testing.md](web-ui-testing.md)). It is off unless you set it up:

1. On the admin account, use an **authenticator app** as the two-factor method and store its setup key (base32, or
   the `otpauth://` URI) when you enroll it; keep TOTP the only 2FA method (no passkey, no security key, no SMS).
2. Add the web login to `~/.config/otterdog-e2e/free.env` (`setup` asks for both in hidden prompts, or
   `setup --rotate web` later):

    ```bash
    E2E_ADMIN_PASSWORD='<password of the admin account>'
    E2E_ADMIN_TOTP_SEED='<base32 setup key>'
    # E2E_ADMIN_USERNAME=  only when the login form needs another username than E2E_ADMIN_LOGIN (e.g. the email)
    ```

3. `doctor --target free` checks the variables, the seed, the account's 2FA, the Playwright browser and the login
   gate (it never logs in). The first web session installs the Playwright Firefox into
   `<E2E_CACHE_DIR>/ms-playwright`; its system libraries need root once:
   `sudo <SUT venv>/bin/python -m playwright install-deps firefox`.
4. Optional: a probe App for `install-app`/`uninstall-app` (a second App of the org without permissions, not
   installed), declared with `E2E_WEB_PROBE_APP_SLUG` (`web_ui.probe_app_slug` of the profile).
5. Run it explicitly (logins are never a side effect):
   `E2E_ALLOW_WEB_UI=1 .venv/bin/otterdog-e2e run --target free --suite cli --scenario 'webui.*' tests/web_ui`.

## CI

To run the live lanes from GitHub Actions (`e2e.yml`, `nightly.yml`, `janitor.yml`, `e2e-otterdog-pr.yml`), each
instance needs its environments `e2e-<instance>` and `e2e-<instance>-untrusted` (plus `e2e-<instance>-webui` for the
web-UI lane), holding its variables and secrets, and must be listed in the repository variable `E2E_INSTANCES`.

`ci-sync` does all of it from the instance's env file, with your own `gh` login (secrets on stdin only), as a dry run
unless `--apply` ([onboarding.md](onboarding.md#ci-ci-sync)):

```bash
.venv/bin/otterdog-e2e ci-sync --target free                    # dry run: operations and names, never values
.venv/bin/otterdog-e2e ci-sync --target free --nightly --apply  # also adds free to E2E_TARGETS (nightly, janitor)
gh workflow run e2e.yml -f target=free -f sut=release:latest
```

An existing environment with deployment branch policies other than `main` is refused (`--prune-branch-policies`
deletes them), and every environment is read back before its secrets are pushed: ci-sync stops when its protections
differ from the ones it set.

Then protect `main` with a ruleset (pull request with review, no bypass): environment secrets are only reachable from
`main`. ci-sync does not do that.

By hand, the same steps for the instance `free`:

1. Create the environments `e2e-free` (deployment branches: `main` only, no reviewers) and `e2e-free-untrusted`
   (deployment branches: `main` only, required reviewers, prevent self-review) in the repository settings.
2. Add the secrets to both environments (values read from stdin, never from the command line):

    ```bash
    for env in e2e-free e2e-free-untrusted; do
      gh secret set E2E_ADMIN_TOKEN --env "$env" < ~/secrets/e2e-admin.token
      gh secret set E2E_AUTHOR_TOKEN --env "$env" < ~/secrets/e2e-author.token
      gh secret set E2E_APPROVER_TOKEN --env "$env" < ~/secrets/e2e-approver.token
      gh secret set E2E_OUTSIDER_TOKEN --env "$env" < ~/secrets/e2e-outsider.token
      gh secret set E2E_CONFIG_READER_TOKEN --env "$env" < ~/secrets/e2e-reader.token
      gh secret set E2E_APP_PRIVATE_KEY --env "$env" < ~/.config/otterdog-e2e/free/app-<id>.private-key.pem
      gh secret set E2E_APP_WEBHOOK_SECRET --env "$env" < ~/.config/otterdog-e2e/free/app-<id>.webhook-secret
    done
    ```

3. Add the non-secret variables to both environments (an instance not named after its profile also needs
   `E2E_PROFILE`, for example `gh variable set E2E_PROFILE --env e2e-acme-a --body free`):

    ```bash
    for env in e2e-free e2e-free-untrusted; do
      gh variable set E2E_ORG --env "$env" --body my-otterdog-e2e-free
      gh variable set E2E_ORG_ID --env "$env" --body 123456789
      gh variable set E2E_ADMIN_LOGIN --env "$env" --body my-e2e-admin
      gh variable set E2E_AUTHOR_LOGIN --env "$env" --body my-e2e-author
      gh variable set E2E_APPROVER_LOGIN --env "$env" --body my-e2e-approver
      gh variable set E2E_OUTSIDER_LOGIN --env "$env" --body my-e2e-outsider
      gh variable set E2E_CONFIG_READER_LOGIN --env "$env" --body my-e2e-reader
      gh variable set E2E_APP_ID --env "$env" --body <app id>
      gh variable set E2E_APP_SLUG --env "$env" --body <app slug>
    done
    gh variable set E2E_INSTANCES --body '["free"]'     # instances a dispatch may name (e2e, e2e-webui, otterdog PR)
    gh variable set E2E_TARGETS --body '["free"]'       # instances of the nightly and janitor workflows
    ```

    Until `E2E_TARGETS` is set, the scheduled nightly and janitor runs are skipped (manual `workflow_dispatch` runs
    still work), so the repository stays quiet before the test org is configured. While `E2E_INSTANCES` is unset,
    `E2E_TARGETS` serves as the allowlist, else `["free", "team", "enterprise"]`. Never set `E2E_ORG`, `E2E_ORG_ID` or
    `E2E_PROFILE` at repository or organization level: the `classify` jobs of `e2e.yml` and `e2e-webui.yml` and the
    `check` job of `janitor.yml` refuse it.

4. Protect `main` with a ruleset (pull request with review, no bypass): environment secrets are only reachable from
   `main`.
5. Start a first run: `gh workflow run e2e.yml -f target=free -f sut=release:latest` (or a comma separated list of
   instances, `-f target=free,acme-a`: one job per instance).
6. Optional web-UI lane: create a third environment `e2e-free-webui` (deployment branches: `main` only), the ONLY one
   holding the admin account's web login, with `E2E_ADMIN_TOKEN` and the same variables as `e2e-free` (ci-sync
   creates it when the env file holds the web login):

    ```bash
    gh secret set E2E_ADMIN_TOKEN --env e2e-free-webui < ~/secrets/e2e-admin.token
    gh secret set E2E_ADMIN_PASSWORD --env e2e-free-webui < ~/secrets/e2e-admin.password
    gh secret set E2E_ADMIN_TOTP_SEED --env e2e-free-webui < ~/secrets/e2e-admin.totp-seed
    gh variable set E2E_WEB_UI_ENABLED --body true          # nightly webui job
    gh variable set E2E_WEB_UI_TARGETS --body '["free"]'
    gh workflow run e2e-webui.yml -f target=free -f sut=release:latest
    ```

    Never add the password or the seed to `e2e-free` or `e2e-free-untrusted`. `E2E_WEB_UI_ENABLED` and
    `E2E_WEB_UI_TARGETS` are set by hand in both cases.

The full list of variables and the protections are in [security.md](security.md#ci-environments).

## Fine-grained personal access tokens

Classic PATs cannot always be used: an organization owner can restrict them, and an enterprise policy can restrict
them for every organization of the enterprise ("Restrict access via personal access tokens (classic)",
organizations cannot override it). Every role except the `outsider` then works with a fine-grained personal access
token. The harness detects the kind of each token and applies the rules of
[security.md](security.md#fine-grained-personal-access-tokens-t1-t2); declare the kind to make a mix-up fail early:

```bash
E2E_ADMIN_TOKEN=github_pat_xxxxxxxxxxxxxxxxxxxxxx
E2E_ADMIN_TOKEN_TYPE=fine-grained      # auto (default) | classic | fine-grained, likewise E2E_<ROLE>_TOKEN_TYPE
```

A target file can also say it directly: `admin: {login: ..., token_env: E2E_ADMIN_TOKEN, token_type: fine-grained}`
(see the comments of `targets/free.yaml`). Doctor shows the kind and the expiry of every token (`token:<role>` rows,
`WARN` under 14 days) and, for a fine-grained admin or oracle, probes the read side of the permissions below
(`permissions:<role>`), naming each missing one with the permission GitHub asks for.

### Organization prerequisites

In the test organization, as an owner: **Settings, Personal access tokens, Settings, Fine-grained tokens**:

- "Allow access via fine-grained personal access tokens" (a restricted organization does not even appear as a
  resource owner when the token is created);
- "Require administrator approval" (the default) is fine: the tokens of organization owners (`admin`, a separate
  `oracle`) are approved automatically, those of members (`author`, `approver`) wait under **Personal access tokens,
  Pending requests** until an owner approves them. A pending token "will only be able to read public resources", so
  the harness refuses it (its proof read answers 403 or 404) until it is approved;
- maximum lifetime ("Set maximum lifetimes for personal access tokens"): the organization default for fine-grained
  tokens is 366 days, an enterprise maximum caps it, and a token over the limit is blocked from the organization
  without being revoked. Classic tokens have no expiration requirement. Rotate before doctor's `WARN`.

In an enterprise, the same settings live under **Enterprise, Policies, Personal access tokens** (Fine-grained tokens /
Tokens (classic) tabs); "Allow organizations to configure access requirements" leaves the choice to the organization.

SAML single sign-on: fine-grained tokens "are authorized during token creation, before access to the organization is
granted" (no separate "Configure SSO" step as for classic tokens); the account may need an active SAML session while it
creates the token, and the organization's approval policy then applies.

The membership comes first: a fine-grained token can only be created for an organization the account already belongs
to. The `author` and `approver` therefore accept the invitation of `bootstrap` and make their membership public in
the web UI (`https://github.com/orgs/<org>/people`) before their tokens exist, see
[Limitations](#limitations-of-fine-grained-tokens). A separate `oracle` must be an active owner before its
fine-grained token exists, so `bootstrap` cannot invite it: bootstrap invites or promotes an oracle only when the
oracle's own token proves its login (`GET /user` answers `E2E_ORACLE_LOGIN`, [6. Memberships](#6-memberships)).
Invite it as an Owner on the People page (Invite member), or let `setup` do it, and accept the invitation signed in
as the oracle.
`setup` follows this order by itself: for the author, the approver and the oracle it asks the login, sends the
invitation with the admin token (the oracle as an owner), waits until it is accepted, and only then prints the token
URL ([onboarding.md](onboarding.md#tokens)).

### Token settings (every role)

| Setting | Value | Why |
|---|---|---|
| Resource owner | the test organization (`E2E_ORG`) | a fine-grained token reaches the resources of one owner only; the harness proves it is the test org |
| Expiration | 90 days or less is a sensible default (366 days at most by default) | doctor warns 14 days before |
| Repository access | **All repositories** | the run repositories (`e2e-<run>-*`) and the per-session config repository `e2e-<run>-config` are created during the run, so "Only select repositories" cannot list them in advance |

Whether "All repositories" covers repositories created after the token is not stated by GitHub's docs: to confirm on
the first live run (a run repository that the admin token cannot read shows up as 404s right after its creation).

### Permissions per role

Only what the role needs; GitHub always adds Metadata (read). The sources are the endpoints otterdog
(`otterdog/providers/github/rest/*.py`, `graphql.py`, `main` 9bdeb75) and the harness (Mutator, Oracle, janitor,
lease, bootstrap) call, mapped with GitHub's tables "Permissions required for fine-grained personal access tokens".

**`admin`** (otterdog, the harness writes, and the oracle when no separate oracle is configured):

| Organization permission | Access | Needed for |
|---|---|---|
| Administration | Read and write | organization settings (`PATCH /orgs/{org}`), Actions permissions, code security configurations, App installations, organization rulesets (GitHub lists even `GET /orgs/{org}/rulesets` under write) |
| Custom organization roles | Read | `GET /orgs/{org}/organization-roles` (security managers, custom roles); probably Read and write on Enterprise Cloud to manage custom roles (to confirm on the first live run) |
| Custom properties | Admin | property definitions (`PUT`/`DELETE /orgs/{org}/properties/schema/{name}`) |
| Members | Read and write | teams, team members, team repository permissions, security manager teams, organization memberships (`bootstrap`) |
| Plan | Read | the `plan` of `GET /orgs/{org}` (read by otterdog and checked by the harness); GitHub documents it for Apps only: to confirm on the first live run |
| Secrets | Read and write | organization Actions secrets |
| Variables | Read and write | organization Actions variables |
| Webhooks | Read and write | organization webhooks (and the harness proof read `GET /orgs/{org}/hooks`) |

| Repository permission | Access | Needed for |
|---|---|---|
| Actions | Read and write | environments and deployment branch policies (read), Actions cache limit, workflow dispatch / cancel / re-run (harness, `dispatch-workflow`) |
| Administration | Read and write | create, update, delete repositories (and from templates or forks), rulesets, branch protection rules (REST and GraphQL), topics, Actions settings, Dependabot alerts, private vulnerability reporting, code scanning default setup, environments, collaborators, team access |
| Commit statuses | Read | the oracle's view of webapp statuses |
| Contents | Read and write | branches, files, refs, commits, merges, the org lease and run ledger refs |
| Custom properties | Read and write | repository property values |
| Environments | Read and write | environment secrets and variables |
| Metadata | Read | mandatory |
| Pages | Read | GitHub Pages configuration (writes go through Administration) |
| Pull requests | Read and write | `open-pr`, `fetch-config --pull-request`, the harness pull requests, comments, reviews and draft toggles |
| Repository security advisories | Read and write | `list-advisories` (GitHub lists `GET /orgs/{org}/security-advisories` under write) and the advisory scenarios |
| Secrets | Read and write | repository Actions secrets |
| Variables | Read and write | repository Actions variables |
| Webhooks | Read and write | repository webhooks |
| Workflows | Read and write | files under `.github/workflows` (template repositories, `push-config`, `delete-file`, scenario workflows) |

Not needed: organization Blocking users, Projects, Self-hosted runners, Dependabot or Codespaces secrets; repository
Issues, Deployments, Dependabot alerts, Code scanning alerts, Secret scanning alerts (otterdog toggles these features
through Administration and `PATCH /repos/{owner}/{repo}`).

**`oracle`** (optional; omit it to let the admin token serve as oracle): an organization owner, every permission of
the admin table at **Read**, except two reads that GitHub lists under write: organization Administration **Read and
write** (organization rulesets, Team and Enterprise plans) and repository Repository security advisories **Read and
write** (the organization advisory listing). With read-only access there, GitHub refuses those reads and the oracle
records them as unavailable, so the checks that need them cannot pass.

**`author`** and **`approver`** (organization members):

| Permission | Access | Needed for |
|---|---|---|
| Organization > Members | Read | the isolation proof `GET /user/memberships/orgs/{org}` (see [security.md](security.md#fine-grained-personal-access-tokens-t1-t2)) |
| Repository > Contents | Read and write | branches and commits of their pull requests |
| Repository > Metadata | Read | mandatory |
| Repository > Pull requests | Read and write | open, comment, review (`approver`), reopen, draft toggles |

**`outsider`**: a fine-grained token is not possible (below); keep a classic PAT with `public_repo` and `read:org`,
or leave the role unset (its negative tests are skipped).

**`config_reader`**: unchanged, a fine-grained token whose resource owner is the config_reader account itself,
repository access "Public repositories", no permission (step [3. Tokens](#3-tokens)).

### Limitations of fine-grained tokens

What does not work, or works differently, with fine-grained tokens:

| Limitation | Effect | Status |
|---|---|---|
| The `outsider` cannot use one: GitHub's fine-grained tokens cannot "contribute to public repos where the user is not a member" ("only personal access tokens (classic) have write access for public repositories that are not owned by you or an organization that you are not a member of") | `token_type: fine-grained` is refused for the outsider; without a classic PAT, leave it unset and its tests are skipped | documented by GitHub |
| `otterdog check-token-permissions` only knows classic scopes | it reports all five scopes missing and exits 1 for a fine-grained token ([KB-078](known-issues.md#kb-078--check-token-permissions-reports-every-classic-scope-missing-for-a-fine-grained-token)); the smoke test reports an expected failure | otterdog defect, reproduced offline |
| otterdog's requester raises on a 403 naming classic scopes when the token has none | an expected 403 (rulesets of a private repository on Free) may abort a command instead of being tolerated ([KB-079](known-issues.md#kb-079--a-403-with-x-accepted-oauth-scopes-aborts-a-fine-grained-session)) | otterdog defect, suspected: to confirm on the first live run |
| otterdog takes several refused reads as absent configuration | a missing permission yields a wrong live configuration instead of an error ([KB-080](known-issues.md#kb-080--reads-refused-for-lack-of-a-permission-are-taken-as-absent-configuration)); doctor's read probes catch the usual cases | otterdog defect, suspected |
| no API reads a token's own fine-grained permissions | the harness cannot enforce least privilege as it does with classic scope allowlists; doctor probes the **read** side only, missing **write** access shows up as failures of the first live run | GitHub limitation |
| members cannot accept the `bootstrap` invitation nor publicize their membership with a fine-grained token (the organization is not a resource owner choice before the membership is active) | do both in the web UI, then create the token; `bootstrap` reports the step it cannot do with its URL, `setup` invites first and waits | GitHub limitation |
| one resource owner per token | machine accounts shared by several test organizations (`E2E_ALLOWED_ORG_IDS`) need one token per organization and instance | GitHub limitation |
| organization approval | members' tokens only read public resources until an owner approves them (the harness refuses them meanwhile) | GitHub behaviour |
| the `plan` field of `GET /orgs/{org}` | GitHub documents the Plan permission for Apps only; without the plan the session stops ("the plan of ... is not visible") | to confirm on the first live run |
| "All repositories" and repositories created later | not stated by GitHub's docs | to confirm on the first live run |
| forks and template repositories owned by another account (otterdog `forked_repository` / `template_repository` naming a repository outside the test org) | the token can read public repositories of other owners, whether GitHub lets it create a fork or a repository from them in the test org is not documented | to confirm on the first live run |
| the expiry date | doctor reads the `github-authentication-token-expiration` response header, which GitHub's REST docs do not describe; without it doctor reports "no expiration" | to confirm on the first live run |

Unchanged with fine-grained tokens: GraphQL ("You can authenticate to the GraphQL API using a personal access token")
with the same permissions, the GitHub App of the webapp tiers ([github-app.md](github-app.md)), the web-UI tier
(it logs in with the admin account's password and TOTP seed, not with a token). GitHub caps every user at 50
fine-grained tokens and removes tokens unused for a year.
