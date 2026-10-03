# Setting up a GitHub Free test organization

This guide prepares the target `free` (`targets/free.yaml`): a dedicated GitHub Free organization, its machine
accounts and tokens, the harness repositories and teams, and the GitHub App of the webapp tiers. Budget about an hour
the first time. Commands assume the repository root and `make init` done.

## 1. Machine accounts

Create dedicated GitHub accounts (machine accounts, following GitHub's terms of service). They must never belong to,
collaborate on, or be invited to any organization other than your test organizations: the harness checks their
memberships on every run and refuses the session otherwise.

| Role | Required | Purpose | Membership |
|---|---|---|---|
| `admin` | yes | owner of the test org; runs otterdog, resets the org, creates the App | owner |
| `author` | for webapp flows | opens config PRs as a plain member | member (public), contributors team |
| `approver` | for approval / auto-merge flows | approves config PRs | member (public), approval team |
| `outsider` | for negative tests | comments as a non-member | **not** a member |
| `config_reader` | for webapp tests of untrusted SUTs | read-only token of the webapp (`OTTERDOG_CONFIG_TOKEN`) | none needed |
| `oracle` | optional | separate read-only ground truth (falls back to admin) | owner |

For every account:

- enable two-factor authentication and keep the recovery codes in your password manager (the token tiers never use
  passwords or TOTP seeds; only the optional web-UI tier logs the admin account in, see
  [10. Web-UI tier](#10-web-ui-tier-optional));
- give it **prior public activity**: push at least one commit to a public repository owned by the account before
  using it. GitHub tags the pull requests of an account that never committed anything as `FIRST_TIMER`, a value
  otterdog's webhook models do not accept, so the webapp would ignore its PRs;
- one token per account and role: two roles never share a token (only `oracle` may be omitted and fall back to
  `admin`).

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
set an expiry and a reminder to rotate them.

| Identity | Token | Scopes |
|---|---|---|
| admin | classic | `repo`, `workflow`, `admin:org`, `admin:org_hook`, `delete_repo` (nothing else; `read:user` and `user:email` are tolerated) |
| oracle | classic | `repo`, `admin:org`, `admin:org_hook` |
| author, approver, outsider | classic | `public_repo`, `read:org` |
| config_reader | fine-grained | resource owner: the config_reader account itself; repository access: "Public repositories"; no permissions |

Every classic token needs `read:org`, given directly or through `admin:org`: the isolation check lists
`GET /user/orgs`, which answers 403 without it. Any scope outside the role's allowlist fails the session (see
[security.md](security.md#dedicated-machine-accounts-t1-t2)).

## 4. Environment file

```bash
install -d -m 700 ~/.config/otterdog-e2e
install -m 600 .env.example ~/.config/otterdog-e2e/free.env
$EDITOR ~/.config/otterdog-e2e/free.env
```

Uncomment and fill at least:

```bash
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
E2E_CONFIG_READ_TOKEN=github_pat_xxxxxxxxxxxxxxxxxxxxxx
```

Notes:

- files are read in this order and the first value wins: `~/.config/otterdog-e2e/free.env`, `.env.e2e.free`,
  `.env.e2e`; an exported variable always wins over every file. There is no `${...}` interpolation in env files;
- if the same machine accounts also serve another test organization (for example the enterprise target), list the
  other organization's id in `E2E_ALLOWED_ORG_IDS` (comma separated) in both targets' files;
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

The author and the approver must be **active and public** members, the outsider must not be a member.

1. Invite the author and the approver (organization People page, Invite member), or let `bootstrap --apply` invite
   them.
2. Signed in as each of them, accept the invitation (https://github.com/orgs/<org>/invitation) and set the
   membership visibility to public on the organization's People page.

With their minimal scopes (`public_repo`, `read:org`: read-only access to memberships) the machine-account tokens are
usually refused when bootstrap tries to accept or publicize a membership through the API: bootstrap then reports the
step as manual (`accept the invitation and make the membership public in the web UI, logged in as <login>`) and goes
on with the repositories, the lease, the baseline and the App; do it in the web UI and run bootstrap again.

## 7. Bootstrap

```bash
.venv/bin/otterdog-e2e bootstrap --target free           # dry run: reports what it would do
.venv/bin/otterdog-e2e bootstrap --target free --apply   # asks you to type the organization login
```

`bootstrap --apply` is idempotent and runs, in order:

1. verification of the organization (id, login, plan) and of the identities' isolation;
2. the safety marker `[otterdog-e2e]` added to the organization description, after you typed the login (refused in
   CI, refused when the organization holds repositories the harness does not manage);
3. memberships: invitations for the author and the approver (both invited first, then accepted and made public
   with their own tokens when GitHub lets them, else reported as manual steps); the outsider must not be a member;
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
   list deliveries a few minutes late, so a timeout points at a webhook problem only when it persists).

## 8. The GitHub App

The webapp and webhooks tiers need a GitHub App owned by the test organization. [github-app.md](github-app.md)
explains every detail; the short version:

```bash
.venv/bin/otterdog-e2e app-manifest --target free --webhook-url https://<a-sink-you-control>/otterdog-e2e
```

The webhook URL is only a **sink**: any HTTPS endpoint you control that answers 2xx, or a smee.io channel used only
as a sink (public: anyone with the URL can read the payloads). GitHub records every delivery, and the harness pulls
them from the deliveries API and relays them to the webapp under test; nothing ever needs to reach your machine.

1. Open the printed `http://127.0.0.1:8765/` URL in a browser signed in as the admin account and confirm the App.
2. The command exchanges the code and writes the private key, the webhook secret and an env snippet to
   `~/.config/otterdog-e2e/free/` (mode 0600). Append the snippet:

   ```bash
   cat ~/.config/otterdog-e2e/free/app-<id>.env >> ~/.config/otterdog-e2e/free.env
   ```

3. Install the App on the organization for **All repositories** (https://github.com/apps/<slug>/installations/new).
4. Run `bootstrap --target free --apply` again: it writes `otterdog.json` and probes the deliveries.

## 9. Check and run

```bash
.venv/bin/otterdog-e2e doctor --target free    # every row OK (WARN rows explain what will be skipped)
make offline                                   # no GitHub involved
make cli TARGET=free                           # live CLI tier
make webhooks TARGET=free
make webapp TARGET=free                        # docker compose stack + relay
make report                                    # summary of the newest run
```

Skipped tests always state why (missing capability, identity, App, docker, low rate budget). After a crash run
`make janitor TARGET=free` (dry run) and `make janitor TARGET=free APPLY=1`.

## 10. Web-UI tier (optional)

The web-UI tier lets otterdog log in to github.com as the admin account to test the settings and commands only
reachable through the UI ([web-ui-testing.md](web-ui-testing.md)). It is off unless you set it up:

1. On the admin account, use an **authenticator app** as the two-factor method and store its setup key (base32, or
   the `otpauth://` URI) when you enroll it; keep TOTP the only 2FA method (no passkey, no security key, no SMS).
2. Add the web login to `~/.config/otterdog-e2e/free.env`:

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
   installed), declared as `web_ui.probe_app_slug` in the target.
5. Run it explicitly (logins are never a side effect):
   `E2E_ALLOW_WEB_UI=1 .venv/bin/otterdog-e2e run --target free --suite cli --scenario 'webui.*' tests/web_ui`.

## CI

To run the live lanes from GitHub Actions (`e2e.yml`, `nightly.yml`, `janitor.yml`, `e2e-otterdog-pr.yml`):

1. Create the environments `e2e-free` (deployment branches: `main` only, no reviewers) and `e2e-free-untrusted`
   (deployment branches: `main` only, required reviewers, prevent self-review) in the repository settings.
2. Add the secrets to both environments (values read from stdin, never from the command line):

   ```bash
   for env in e2e-free e2e-free-untrusted; do
     gh secret set E2E_ADMIN_TOKEN --env "$env" < ~/secrets/e2e-admin.token
     gh secret set E2E_AUTHOR_TOKEN --env "$env" < ~/secrets/e2e-author.token
     gh secret set E2E_APPROVER_TOKEN --env "$env" < ~/secrets/e2e-approver.token
     gh secret set E2E_OUTSIDER_TOKEN --env "$env" < ~/secrets/e2e-outsider.token
     gh secret set E2E_CONFIG_READ_TOKEN --env "$env" < ~/secrets/e2e-reader.token
     gh secret set E2E_APP_PRIVATE_KEY --env "$env" < ~/.config/otterdog-e2e/free/app-<id>.private-key.pem
     gh secret set E2E_APP_WEBHOOK_SECRET --env "$env" < ~/.config/otterdog-e2e/free/app-<id>.webhook-secret
   done
   ```

3. Add the non-secret variables to both environments:

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
   gh variable set E2E_TARGETS --body '["free"]'      # targets of the nightly and janitor workflows
   ```

   Until `E2E_TARGETS` is set, the scheduled nightly and janitor runs are skipped (manual `workflow_dispatch` runs
   still work), so the repository stays quiet before the test org is configured.

4. Protect `main` with a ruleset (pull request with review, no bypass): environment secrets are only reachable from
   `main`.
5. Start a first run: `gh workflow run e2e.yml -f target=free -f sut=release:latest`.
6. Optional web-UI lane: create a third environment `e2e-free-webui` (deployment branches: `main` only), the ONLY one
   holding the admin account's web login, with `E2E_ADMIN_TOKEN` and the same variables as `e2e-free`:

   ```bash
   gh secret set E2E_ADMIN_TOKEN --env e2e-free-webui < ~/secrets/e2e-admin.token
   gh secret set E2E_ADMIN_PASSWORD --env e2e-free-webui < ~/secrets/e2e-admin.password
   gh secret set E2E_ADMIN_TOTP_SEED --env e2e-free-webui < ~/secrets/e2e-admin.totp-seed
   gh variable set E2E_WEB_UI_ENABLED --body true          # nightly webui job
   gh variable set E2E_WEB_UI_TARGETS --body '["free"]'
   gh workflow run e2e-webui.yml -f target=free -f sut=release:latest
   ```

   Never add the password or the seed to `e2e-free` or `e2e-free-untrusted`.

The full list of variables and the protections are in [security.md](security.md#ci-environments).
