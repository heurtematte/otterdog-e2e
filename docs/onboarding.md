# Onboarding a test organization

`otterdog-e2e setup` onboards one test organization interactively: it checks the organization, asks the token of
every role through prefilled creation URLs, stores the web-UI login, creates the GitHub App, then offers `bootstrap`
and `doctor`. `otterdog-e2e ci-sync` then creates the CI environments of the organization with your own `gh` login.
What GitHub does not let a program do stays manual, but guided: the harness prints the exact URL, then polls until the
step is done ([What cannot be automated](#what-cannot-be-automated)).

Vocabulary used below (details in [Instances and profiles](#instances-and-profiles)):

- an **instance** is one test organization: `--target <instance>` everywhere, its env file
  `~/.config/otterdog-e2e/<instance>.env`, its CI environments `e2e-<instance>`, `e2e-<instance>-untrusted` and
  `e2e-<instance>-webui`;
- a **profile** is a target file `targets/<profile>.yaml` (`free`, `team`, `enterprise`) holding no org-specific
  value; `E2E_PROFILE` in the env file binds an instance to its profile.

[setup-free-org.md](setup-free-org.md) and [setup-enterprise-org.md](setup-enterprise-org.md) describe the same setup
step by step, by hand: use them as the reference of what `setup` does, or when you cannot run it.

## The fast path

By hand, before `setup` (no API can do these, see [What cannot be automated](#what-cannot-be-automated)):

1. create the machine accounts (at least the admin; author, approver, outsider and config_reader for the webapp
   flows and the negative tests), each with two-factor authentication;
2. signed in as the admin account, create the organization and keep it empty (no repositories, teams or
   organization secrets; Enterprise Cloud: [setup-enterprise-org.md](setup-enterprise-org.md)).

Then, from the repository root (`make init` done, `OTTERDOG_CONFIG_ROOT` unset):

```bash
.venv/bin/otterdog-e2e setup --target acme-a --profile free    # org, tokens, web login, App, then bootstrap and doctor
.venv/bin/otterdog-e2e bootstrap --target acme-a --apply --wait # only when you declined it in setup
.venv/bin/otterdog-e2e doctor --target acme-a                   # every row OK (WARN rows say what will be skipped)
.venv/bin/otterdog-e2e ci-sync --target acme-a                  # dry run: the environments, variables and secrets
.venv/bin/otterdog-e2e ci-sync --target acme-a --apply          # writes them with your gh login
make cli TARGET=acme-a                                          # first live run, locally
gh workflow run e2e.yml -f target=acme-a -f sut=release:latest  # first run in CI
```

The Makefile has the same steps:

```bash
make setup TARGET=acme-a PROFILE=free                         # FROM=<instance>: --from, PROFILE=<profile>: --profile
make bootstrap TARGET=acme-a APPLY=1 WAIT=1                   # --apply --wait
make ci-sync TARGET=acme-a                                    # dry run
make ci-sync TARGET=acme-a REVIEWER=alice NIGHTLY=1 APPLY=1   # --reviewer alice --nightly --apply
```

Without `--profile`, setup proposes the profile named after the organization's plan. The names `free`, `team` and
`enterprise` are valid instance names too: they use the profile of the same name.

Most of the time goes into creating the tokens in the browser. A second organization with the same profile and
settings is faster: `setup --target acme-b --from acme-a` ([A second organization](#a-second-organization)).

## What setup asks and writes

`setup` writes every validated answer to `~/.config/otterdog-e2e/<instance>.env` at once: an interrupted run (Ctrl-C,
a closed terminal) keeps its progress, and the next run continues where it stopped. It reads and writes only that
file (not `.env.e2e.<instance>` nor `.env.e2e`), and is refused when `CI` or `GITHUB_ACTIONS` is set.

| Step | What setup does | Keys written |
|---|---|---|
| 1. organization | the login (`--org`, the stored `E2E_ORG`, else asked), read with `GET /orgs/{org}`: exact-case login and id. A missing organization gets the creation hint of the profile's plan and a "Check again?" prompt; while the profile is not known yet (no `--profile`, no stored `E2E_PROFILE`, an instance not named after a profile), the hint shows the Free URL (`?plan=free`, and the Team one), the Enterprise Cloud note (`createEnterpriseOrganization`, not automated by setup) and suggests `--profile` | `E2E_ORG`, `E2E_ORG_ID` |
| 2. admin token (required) | the prefilled URL, a hidden prompt, then the checks below; the admin must be an active owner | `E2E_ADMIN_LOGIN`, `E2E_ADMIN_TOKEN`, `E2E_ADMIN_TOKEN_TYPE` |
| 3. profile | an instance named after a profile uses it; else `--profile`, the stored `E2E_PROFILE`, else the organization's plan; the profile's `expected_plan` must be the live plan | `E2E_PROFILE` |
| 4. the other roles (optional) | in order oracle (skipped by default: the admin token serves as oracle), author, approver, outsider (classic PAT only), config_reader (fine-grained only); answer no, or enter no token, to skip a role | `E2E_<ROLE>_LOGIN`, `E2E_<ROLE>_TOKEN`, `E2E_<ROLE>_TOKEN_TYPE` (config_reader: `E2E_CONFIG_READER_LOGIN`, `E2E_CONFIG_READ_TOKEN`, `E2E_CONFIG_READ_TOKEN_TYPE`) |
| 5. web-UI login (optional, default no) | [The web login step](#the-web-login-step) | `E2E_ADMIN_PASSWORD`, `E2E_ADMIN_TOTP_SEED` |
| 6. GitHub App (optional, default yes) | [The App step](#the-app-step) | `E2E_APP_WEBHOOK_URL`, `E2E_APP_ID`, `E2E_APP_SLUG`, `E2E_APP_PRIVATE_KEY_FILE`, `E2E_APP_WEBHOOK_SECRET` |
| 7. bootstrap and doctor (offered) | `bootstrap --apply --wait` (you type the organization login for the safety marker; it waits for the invitations and the App installation, up to `--wait-timeout`), the App and a second bootstrap when the App waited for the marker, then `doctor` | - |
| end | the list of what is still manual for this instance, and the `ci-sync` command | - |

The env file:

- is created with mode 0600 and a header comment, in a directory created with mode 0700 when it is missing; every
  write is atomic (a temporary file renamed over the old one), keeps your comments and other lines, and never
  follows a symlink;
- holds values that the harness reads back exactly (quoted and escaped when needed);
- loses against exported `E2E_*` variables in every session, as every env file does: `setup` names those that differ
  from the file when it ends.

### Tokens

For each role `setup` prints a creation URL that preselects what URL parameters can carry. Open it **signed in as
that role's machine account** (a private window or a browser profile per account helps), click "Generate token" and
paste the token into the hidden prompt.

| Kind | Prefilled URL | Still selected by hand |
|---|---|---|
| classic | `https://github.com/settings/tokens/new?scopes=<the role's scopes>&description=<role, org, instance>` | the expiration (no URL parameter exists for it) |
| fine-grained | `https://github.com/settings/personal-access-tokens/new?name=otterdog-e2e-<instance>-<role>&description=...&target_name=<org>&expires_in=<days>&<permission>=<access>...` | Repository access: **All repositories** (config_reader: **Public repositories**); no URL parameter exists for it |

The scopes and permissions are those of [setup-free-org.md](setup-free-org.md#3-tokens) and
[Permissions per role](setup-free-org.md#permissions-per-role) (a unit test keeps the page and the URLs equal). The
config_reader's fine-grained token has its own account as resource owner and no permission.

Each token is checked before anything is written: its shape, `GET /user` (the login is taken from the token), its kind,
the classic scopes of the role, the isolation of the account (`safety.check_identity_isolation`, as in every session)
and, for the admin, an active owner membership. A token or an account already stored for another role is refused (only
the oracle may be the admin). A refused token is never written; after 5 refused tokens setup stops (what was saved
stays).

| Option | Effect |
|---|---|
| `--token-type classic` / `--token-type fine-grained` | kind of the prefilled URLs of the roles that accept both (default: the stored `E2E_<ROLE>_TOKEN_TYPE`, else classic) |
| `--expires-in DAYS` | `expires_in` of the fine-grained URLs: 1 to 366 days, default 90 |
| `--rotate ROLE` | ask again even when the stored token is valid: `admin`, `oracle`, `author`, `approver`, `outsider`, `config_reader`, `web` (the web login), `app` (a new App); repeatable |
| `--wait-timeout DURATION` | how long setup waits for an invitation to be accepted or the App to be installed, and how long the `bootstrap --wait` it starts waits: a duration as for bootstrap (`30m`, the default, `90s`, `1h`, or plain seconds `1800`) |
| `--open` | open the token, invitation, App and installation URLs in a browser (they are printed anyway) |

Fine-grained tokens of the author, the approver and a separate oracle need an **active membership first**: GitHub only
offers the organization as resource owner to its members. For these roles setup therefore asks the login first,
invites it with the admin token (author and approver as members, the oracle as an owner; an existing membership is
never changed), prints `https://github.com/orgs/<org>/invitation` and polls every 10 s (up to `--wait-timeout`, default
`30m`) until the account accepted. Only then it shows the token URL. After a timeout the role is skipped and the
pending invitation is kept, so the next setup run resumes waiting for it; the message names the People page
`https://github.com/orgs/<org>/people`, where you cancel the invitation of a mistyped login. A member's token may also
wait for an owner's approval (when the organization requires it, the default): approve it signed in as the admin at
`https://github.com/organizations/<org>/settings/personal-access-token-requests` before you paste it, since a pending
token only reads public resources and fails its isolation check.

When the token pasted for such a role belongs to another account than the invited login, it is refused. If the role
then ends without a token (you enter none, or 5 tokens were refused), setup withdraws the invitation it created in
the same run when it is still pending (`DELETE /orgs/{org}/memberships/{login}`, admin token; the stored login goes
too unless the role keeps a stored token). An account that already accepted that invitation stays a member: setup
warns and names the People page, where you remove it when it is not the role's machine account. An invitation or
membership that existed before the run is never touched.

Classic tokens need no membership: setup checks them at once, and `bootstrap` invites the accounts later (and, with
`--wait` as setup runs it, waits until they accepted and made their membership public). A separate oracle is invited
by bootstrap only when it has its own token, whose `GET /user` login is `E2E_ORACLE_LOGIN`
([6. Memberships](setup-free-org.md#6-memberships)).

Accounts that serve several test organizations: a classic token lists every organization of its account, and the
isolation check refuses any organization outside `E2E_ALLOWED_ORG_IDS`. Setup offers to allow them (once the
token's login, kind and scopes passed, right before the isolation check that needs the answer) only when every such
organization is the validated test organization of another instance: an organization id N of the instance `x`
qualifies when

- `~/.config/otterdog-e2e/<x>.env` pins `E2E_ORG` and `E2E_ORG_ID=N` and holds `E2E_ADMIN_LOGIN` and
  `E2E_ADMIN_TOKEN` (setup writes them only after the admin's owner check: a setup of `x` interrupted earlier does not
  qualify),
- the target of `x` loads with these values (the denylist of production organizations included),
- and `GET /orgs/<x org>`, read through the token being checked, answers the id N and a description carrying the
  safety marker of `x` (set by the bootstrap of `x`).

When one organization of the account does not qualify, nothing is offered and the isolation check refuses the token
as usual: for an organization pinned by a known instance setup prints why it does not qualify, an organization that
no instance pins is named by the isolation check. The question ("org id N (instance x)") defaults to No. A yes is used for the checks of this token only, in memory: nothing is written before the token
passed every check, then `E2E_ALLOWED_ORG_IDS` gains this organization's id in the env files of the other instances
and their ids in this instance's file; a refused token changes no file. In every other case set `E2E_ALLOWED_ORG_IDS`
by hand (comma separated ids, in both env files). Fine-grained tokens have one resource owner: such an account needs
one token per organization.

### Re-runs and rotation

Run `setup --target <instance>` again at any time. Stored tokens are checked again and kept when they pass; a stored
token that fails is asked again (for an optional role you may also remove it). `--rotate` replaces valid values:

```bash
.venv/bin/otterdog-e2e setup --target acme-a --rotate admin --rotate author   # new tokens (regenerating them works too)
.venv/bin/otterdog-e2e setup --target acme-a --rotate web                     # a new password or TOTP setup key
.venv/bin/otterdog-e2e setup --target acme-a --rotate app                     # registers a NEW App: delete the old one
```

The org is pinned: `--org` naming another organization than the stored `E2E_ORG`, or an `E2E_ORG_ID` that no longer
matches the live organization, stops setup without changing anything (set the other organization up as another
instance).

### A second organization

`--from <instance>` copies the settings of another instance that are neither secret nor specific to its organization,
and only those the new instance does not set yet: `E2E_PROFILE` (unless the new instance is named after a profile),
the `E2E_<ROLE>_TOKEN_TYPE` kinds, the team and repository names, the template mode and URL, the transport, the commit
status contexts, the webapp workers, `E2E_APP_WEBHOOK_URL`, `E2E_MIN_RATE_REMAINING`, `E2E_LEASE_WAIT` and
`E2E_WEB_LOGIN_SPACING`.

```bash
.venv/bin/otterdog-e2e setup --target acme-b --from acme-a
make setup TARGET=acme-b FROM=acme-a
```

The tokens, logins, App and web login of the new organization are asked as usual: each test organization has its own
App, and fine-grained tokens are bound to one organization.

## The App step

The webapp and webhooks tiers need a GitHub App owned by the test organization ([github-app.md](github-app.md)).

1. The App is only created in an organization whose description carries the safety marker. On a fresh organization
   `bootstrap` adds it later: setup then postpones the App, and right after the bootstrap it runs it offers it again
   ("The marker is set now: create the GitHub App?").
2. The webhook sink URL: `--webhook-url`, the stored `E2E_APP_WEBHOOK_URL`, else asked. Any `https` endpoint you
   control that answers 2xx, never a loopback URL: the harness pulls the deliveries from GitHub.
3. The manifest flow: setup listens on `http://127.0.0.1:8765/` (`--port`) and prints that URL; open it in a browser
   signed in as an organization owner (the admin account) and confirm the App on GitHub. GitHub redirects back with a
   code, which setup exchanges at once (the listener waits 10 minutes for the redirect).
4. The credentials land in `~/.config/otterdog-e2e/<instance>/` (mode 0700): `app-<id>.private-key.pem`,
   `app-<id>.webhook-secret` and `app-<id>.env` (mode 0600). Setup writes `E2E_APP_ID`, `E2E_APP_SLUG`,
   `E2E_APP_PRIVATE_KEY_FILE` and `E2E_APP_WEBHOOK_SECRET` into the instance env file itself (and removes an inline
   `E2E_APP_PRIVATE_KEY` of a former App).
5. The installation: setup first verifies the App, a new one or the one stored (`safety.verify_app`, as before
   every webapp start: `GET /app` names the test organization as owner, every installation is on a test
   organization). An App that fails gets no installation link: setup stops with the reason and the command that
   registers a new App, `otterdog-e2e setup --target <instance> --rotate app`. Otherwise it prints
   `https://github.com/apps/<slug>/installations/new/permissions?target_id=<org id>` (the organization preselected).
   Install the App for **All repositories**; setup polls `GET /orgs/{org}/installation` with the App's JWT every 10 s,
   up to `--wait-timeout`, then checks the installation (all repositories, permissions, events, not suspended).
6. The bootstrap that setup offers next (a second one when the App waited for the marker) writes the webapp's
   `otterdog.json` and probes the deliveries.

On a timeout nothing is lost: install the App, then run `setup` (or `bootstrap --apply --wait`) again. A stored App is
kept on re-runs (setup verifies it again and only waits for its installation); `--rotate app` registers a new one.

When the browser cannot reach the local listener (a remote machine), use
`otterdog-e2e app-manifest --target <instance> --webhook-url <url>` and its `--exchange <code>` fallback
([github-app.md](github-app.md#creating-the-app)), add the printed lines to the env file, then run setup again.

## The web login step

The optional web-UI tier lets otterdog log in to github.com as the admin account
([web-ui-testing.md](web-ui-testing.md)). Setup asks for it only when you accept the question (default no), or with
`--rotate web`:

1. enable two-factor authentication on the admin account with an **authenticator app** (TOTP) only, and keep the
   setup key GitHub shows while you enroll it (base32, or the `otpauth://` URI): GitHub never shows it again;
2. enter the account's password and the setup key in the hidden prompts. The key is normalized (spaces, dashes, case,
   the `otpauth://` URI) and checked; a wrong key is asked again.

Setup writes `E2E_ADMIN_PASSWORD` and `E2E_ADMIN_TOTP_SEED`; `doctor` checks them without logging in. With these keys
`ci-sync` also manages the `e2e-<instance>-webui` environment, the only one that receives them. Nothing logs in until
a run passes `--allow-web-ui`.

## CI: ci-sync

`otterdog-e2e ci-sync --target <instance>` creates the GitHub environments of an instance and sets their variables and
secrets from its env file.

| Environment | Managed | Protection set by ci-sync | Values |
|---|---|---|---|
| `e2e-<instance>` | always | deployment branches: custom policy, `main` only; no reviewers set | the variables and secrets the trusted jobs read |
| `e2e-<instance>-untrusted` | always | the same, plus required reviewers (`--reviewer`, repeatable, at most 6; default: your `gh` login) and prevent self-review (unless `--allow-self-review`) | the same names |
| `e2e-<instance>-webui` | only when the env file holds `E2E_ADMIN_PASSWORD` and `E2E_ADMIN_TOTP_SEED` | deployment branches: `main` only | the names of the web-UI job, the only environment holding the password and the TOTP seed |

- **Names**: the `${{ vars.X }}` and `${{ secrets.X }}` that the steps of the workflow jobs running in each kind of
  environment read (`.github/workflows/*.yml`), always plus `E2E_PROFILE`. Repository variables (`E2E_INSTANCES`,
  `E2E_TARGETS`, `E2E_WEB_UI_ENABLED`, `E2E_WEB_UI_TARGETS`) and `GITHUB_TOKEN` are never copied into an environment.
- **Values**: from `~/.config/otterdog-e2e/<instance>.env` only; the secret `E2E_APP_PRIVATE_KEY` is the content of
  `E2E_APP_PRIVATE_KEY_FILE`; `E2E_PROFILE` of an instance named after a profile is that name. A name without a value
  is skipped and listed. A variable whose name looks like a secret, or whose value holds a secret or a line break, is
  refused.
- **`main` only, verified**: ci-sync first lists the deployment branch policies of each existing environment. A
  policy other than the branch `main` (a `*` pattern keeps every branch deployable) is refused with its name, unless
  `--prune-branch-policies`, which deletes each of them (the dry run prints "would delete" for each). Before it pushes
  the variables and secrets of an environment, ci-sync reads the environment back and refuses to go on when the
  protections differ from the ones it set: custom branch policies without protected branches, no policy but `main`,
  and for `e2e-<instance>-untrusted` a required reviewers rule holding every expected reviewer with the requested
  prevent self-review (an organization or repository rule may override them).
- **Repository variables**: `E2E_INSTANCES` (the allowlist of the dispatchable instances) gains the instance. While it
  does not exist, the workflows fall back to `E2E_TARGETS`, else `["free", "team", "enterprise"]`: ci-sync then
  creates `E2E_INSTANCES` from that old allowlist plus the instance when the instance is missing from it or when
  `E2E_TARGETS` changes (set before `E2E_TARGETS`, so the allowlist never loses an instance), and otherwise only notes
  that the instance is dispatchable already. `--nightly` also adds the instance to `E2E_TARGETS` (the nightly and
  janitor runs); an absent `E2E_TARGETS` is created as the workflows' default `["free"]` plus the instance, which
  starts the scheduled runs. `E2E_WEB_UI_ENABLED` and `E2E_WEB_UI_TARGETS` stay yours to set.
- **Your credential**: every call goes through your own `gh` CLI login (`gh auth login`; `GH_TOKEN`, `GITHUB_TOKEN`,
  `GH_HOST` and `GH_CONFIG_DIR` are passed on when you export them), never a machine account's token: ci-sync refuses
  to run when that credential is a token or secret of the instance, or when `gh` is logged in as one of its machine
  accounts.
  Creating environments needs admin access to the repository.
- **Secrets on stdin only**: `gh secret set NAME --env ENV` reads each value from its standard input
  ([gh secret set](https://cli.github.com/manual/gh_secret_set)); no secret ever appears on a command line.
  Environments are written with `gh api -X PUT repos/{repo}/environments/{env} --input -` and a deployment branch
  policy for `main` ([REST environments](https://docs.github.com/en/rest/deployments/environments)).
- **Dry run by default**: the operations are printed with names only, never values (the reads still run: the
  repository, your `gh` user, the reviewers, the repository variables, the deployment branch policies). `--apply`
  runs them in order and stops at the first failure; every operation is idempotent, so run it again.
- `--repo owner/name` names the harness repository (default: the one of the checkout, `gh repo view`). Refused when
  `CI` or `GITHUB_ACTIONS` is set.

```bash
.venv/bin/otterdog-e2e ci-sync --target acme-a                                        # dry run
.venv/bin/otterdog-e2e ci-sync --target acme-a --reviewer alice --reviewer bob --apply
.venv/bin/otterdog-e2e ci-sync --target acme-a --nightly --apply                      # also nightly and janitor
.venv/bin/otterdog-e2e ci-sync --target acme-a --prune-branch-policies                # dry run: "would delete"
```

When you are the only required reviewer and self-review is prevented, you cannot approve the untrusted runs you
start: add `--reviewer`, or pass `--allow-self-review`. ci-sync does not touch the ruleset that must protect `main` of
this repository ([security.md](security.md#ci-environments)); the manual `gh` commands remain in
[setup-free-org.md](setup-free-org.md#ci).

## Instances and profiles

A **profile** (`targets/free.yaml`, `targets/team.yaml`, `targets/enterprise.yaml`) describes a kind of test
organization: its expected plan, identities, repositories, teams, webapp transport. Every org-specific value comes
from `E2E_*` variables, including those that differ between two organizations of one profile: `E2E_SAML_SSO`,
`E2E_CAPABILITIES_ADD`, `E2E_CAPABILITIES_REMOVE` and `E2E_WEB_PROBE_APP_SLUG` ([.env.example](../.env.example)).

An **instance** is one test organization. `--target <value>` resolves to an instance, a profile and a file:

| `--target` value | Instance | Profile |
|---|---|---|
| a path (`targets/free.yaml`, anything with `/` or a `.yaml`/`.yml` suffix) | the file name without suffix | the same |
| a name with a file `targets/<name>.yaml` (`free`, `team`, `enterprise`) | the name | the name (an `E2E_PROFILE` naming another profile is refused as ambiguous) |
| any other name (`acme-a`) | the name | `E2E_PROFILE`, read from the instance's env files; without it the error tells you to run `otterdog-e2e setup --target acme-a` or to add `E2E_PROFILE=<profile>` to `~/.config/otterdog-e2e/acme-a.env` |

Instance names: lower-case letters, digits and `-`, at most 39 characters, starting with a letter or a digit
(`^[a-z0-9][a-z0-9-]{0,38}$`), never ending with `-untrusted` or `-webui` (the suffixes of its CI environments), and
not `lists` (the directory `~/.config/otterdog-e2e/lists/` holds the target lists). The
env files of an instance, first value wins and the process environment wins over all of them:
`~/.config/otterdog-e2e/<instance>.env`, `.env.e2e.<instance>`, `.env.e2e`.

`otterdog-e2e targets` (`make targets`) lists the instances: every `~/.config/otterdog-e2e/<instance>.env` and every
profile (an instance of its own name), with the profile, the organization and the env file, and a `problem:` line
under an instance whose target cannot be loaded. It is read-only and contacts nothing; `--json` prints the same as
JSON.

```text
INSTANCE    PROFILE     ORG          ENV FILE
acme-a      free        acme-e2e-a   /home/me/.config/otterdog-e2e/acme-a.env
enterprise  enterprise  -            -
  problem: not configured (otterdog-e2e setup --target enterprise)
free        free        my-e2e-free  /home/me/.config/otterdog-e2e/free.env
team        team        -            -
  problem: not configured (otterdog-e2e setup --target team)
```

`run.json` records the profile next to the instance (`target.profile`), and `summary.md` and `doctor` show both.
Two instances may pin the same organization: setup notes it, and `--parallel` refuses to run them at the same time.

## Running on one organization or a list

One target works as before. `run`, `pr`, `doctor` and `janitor` also accept several:

| `--target` | Targets |
|---|---|
| `--target acme-a,acme-b` or `--target acme-a --target acme-b` | these instances, in order, duplicates dropped |
| `--target @all` | every instance with an env file `~/.config/otterdog-e2e/<instance>.env` (sorted; a profile without env file is not included; a file whose name cannot be an instance, such as `acme.bak.env` or `my_org.env`, is skipped unless it is named after a profile) |
| `--target @nightly` | the instances of the list file `~/.config/otterdog-e2e/lists/nightly`: one per line, `#` starts a comment |

The other commands (`bootstrap`, `relay`, `app-manifest`, `inject`, `setup`, `ci-sync`) take one target and refuse a
list, and so does pytest's `--e2e-target` (or `E2E_TARGET`) when live tests are selected.

```bash
install -d -m 700 ~/.config/otterdog-e2e/lists
printf '%s\n' '# instances of my nightly runs' free acme-a > ~/.config/otterdog-e2e/lists/nightly

.venv/bin/otterdog-e2e run --target free,acme-a --suite cli                  # one after the other
.venv/bin/otterdog-e2e run --target @all --suite cli --parallel 2 --fail-fast
.venv/bin/otterdog-e2e pr 792 --sha <40-hex> --target @nightly
.venv/bin/otterdog-e2e doctor --target @all                                  # one table per instance
make cli TARGET=free,acme-a PARALLEL=2
make doctor TARGET=@all
```

How several targets run:

- **One child process per target** for `run`, `pr` and `janitor` (`python -P -m otterdog_e2e run --target=<instance>
  --run-id=<id> ...`, with the same interpreter, after the `-v`/`-vv` of the batch command; `-P` keeps the working
  directory off `sys.path`, so an `otterdog_e2e` package in the current directory, such as the `src/` of another
  checkout, is never imported). An env file fills the environment without overriding it, so two
  organizations in one process would mix their values: the parent never loads an env file into its own environment,
  every child gets the parent's environment unchanged (plus its webapp port, below) and loads the env files of its
  own target.
- **Exported per-instance values are refused**: for the same reason an exported value would serve every target. With
  several targets, an exported `E2E_ORG`, `E2E_ORG_ID` or `E2E_PROFILE` stops the batch, and so does an exported login
  (`*_LOGIN`) or secret (a name ending with `_TOKEN`, `_SECRET`, `_PASSWORD`, `_TOTP_SEED` or `_PRIVATE_KEY`) that the
  env file of an instance sets to another value. The message names the variables and instances, never a value: unset
  them, or give one target.
- **Everything is checked first**: each target is loaded with a private copy of the environment before any child
  starts; an invalid target, an instance listed twice, an exported per-instance value or a `--parallel` conflict stops
  the batch before anything runs.
- **Each target gets its own run id** and its own artifacts directory `<artifacts>/<run id>/`; `--run-id` names one
  run and is refused with several targets.
- **Sequential by default.** `--parallel N` runs up to N children at once. It refuses two targets of the same
  organization (an organization serves one session at a time) and two `external` transport targets with the same
  webapp URL (one webapp serves one session at a time), gives each relay webapp that pins no port a free loopback
  port (`E2E_WEBAPP_PORT`), and refuses two instances pinning the same `E2E_WEBAPP_PORT`. Sessions testing the same
  SUT build its webapp image once (a file lock per image tag), and `cache prune` never removes an entry whose lock a
  running session or build holds.
- `--fail-fast` starts no further target after a failure. Ctrl-C (or SIGTERM) is forwarded to the running children,
  which clean up (sweep, lease release) and exit; no further target starts. Every command, a child included, turns
  the first SIGTERM into the same interruption as Ctrl-C, so its cleanup (lease release, scrub) runs; a second
  SIGTERM during that cleanup is ignored (GitHub Actions cancels with SIGINT, then SIGTERM).
- Every output line is prefixed with `[<instance>] `.
- **`doctor`** runs in-process instead (read-only): one table per target, each checked with its own copy of the
  environment, `--json` prints a list, exit code 1 when any target has a `FAIL`.
- **`janitor`** runs its children one after the other, without `--run-id` or `--force-takeover` (they name one run of
  one target) and without batch summary; a janitor child sweeps under a run id of its own, so its batch lines show no
  run id.

The batch summary of `run` and `pr`, below the artifacts root (`--artifacts`, `E2E_ARTIFACTS`, default
`./artifacts`):

| File | Content |
|---|---|
| `batch-<id>.md` | the verdict and one row per target: instance, profile, org, run id, exit code, duration, results, the command reproducing it; appended to `GITHUB_STEP_SUMMARY` when set |
| `batch-<id>.json` | the same, plus the batch command, mode, start times and webapp ports |
| `batch-<id>-<instance>.log` | the console output of one child |

All three are redacted and written with mode 0600. Each target's own report stays `<artifacts>/<run id>/summary.md`.

The exit code is 0 only when every target exited 0, else the most severe code of the children: 3 (internal error) >
2 (interrupted) > 4 (usage error) > 1 (tests failed) > 5 (no tests collected). A child killed by a signal counts as
interrupted, a target never started counts as interrupted unless another one failed.

In CI the `target` input of `e2e.yml`, `e2e-webui.yml` and `e2e-otterdog-pr.yml` takes one instance or a comma
separated list of at most 8, each in the allowlist `E2E_INSTANCES`: one job per instance, in that instance's
environments ([security.md](security.md#ci-environments)).

```bash
gh workflow run e2e.yml -f target=free,acme-a -f sut=release:latest
```

## What cannot be automated

GitHub keeps these steps to a person in a browser. The harness identifies each one, prints what to open and, where it
can, waits for the result.

| Step | Why it is manual | What the harness does instead |
|---|---|---|
| Creating the machine accounts | GitHub's [Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service): an account must be created by a human, accounts registered by bots or other automated methods are not permitted; a machine account is set up by a human who is responsible for it, and a person may maintain no more than one free machine account besides their own account, so the roles need accounts held by several people | the roles and their rules: [setup-free-org.md](setup-free-org.md#1-machine-accounts); setup validates each account through its token (isolation, one account per role) |
| Enrolling two-factor authentication (TOTP) | done in the account's security settings ([configuring 2FA](https://docs.github.com/en/authentication/securing-your-account-with-two-factor-authentication-2fa/configuring-two-factor-authentication)); the setup key is shown once while enrolling and cannot be read back | setup asks the key in a hidden prompt and normalizes it; doctor checks the account's 2FA and the key without logging in |
| Creating a personal access token, classic or fine-grained | no API creates a token; the creation page takes URL parameters for the name, description, resource owner, expiration (`expires_in`, at most 366 days) and permissions, but none for the repository access ([pre-filling a fine-grained token](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens#pre-filling-fine-grained-personal-access-token-details-using-url-parameters)); a classic token has no expiration parameter | prefilled URLs per role and kind; "All repositories" (config_reader: "Public repositories") and the classic expiration are named as the steps left; the token is checked before it is written |
| Creating a Free or Team organization | no REST or GraphQL API creates one. Enterprise Cloud enterprise owners can create an organization with the GraphQL mutation `createEnterpriseOrganization` ([enterprise administration](https://docs.github.com/en/enterprise-cloud@latest/graphql/reference/enterprise-admin)): the harness does not, it never holds an enterprise owner's token | setup prints the creation URL of the profile's plan (`https://github.com/account/organizations/new?plan=free` for the Free profile), or the Enterprise Cloud hint; while the profile is not known, the Free (and Team) URL with the Enterprise Cloud note and the hint to pass `--profile`; it reads `GET /orgs/{org}` again when you answer "Check again?" |
| The organization's token policies (allow classic or fine-grained tokens, require approval, maximum lifetime) | organization settings only ([setting a token policy](https://docs.github.com/en/organizations/managing-programmatic-access-to-your-organization/setting-a-personal-access-token-policy-for-your-organization)); the REST API only reviews requests and revokes tokens, for GitHub Apps ([REST personal access tokens](https://docs.github.com/en/rest/orgs/personal-access-tokens)) | the settings to choose: [organization prerequisites](setup-free-org.md#organization-prerequisites); a token the policy blocks is refused by setup and doctor with the reason |
| Registering the GitHub App | the manifest flow ends with an owner confirming the App on github.com ([registering an App from a manifest](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)) | setup and `app-manifest` serve the auto-posting form on `127.0.0.1`, receive GitHub's redirect, exchange the code at once and store the credentials |
| Installing the GitHub App | an organization owner's click on github.com; Enterprise Cloud has an API for installing Apps on the organizations of an enterprise, which the harness does not use | the installation URL with `target_id` (the organization preselected); setup and `bootstrap --wait` poll `GET /orgs/{org}/installation` until the App is installed, then check it |
| Accepting an invitation, making a membership public | done by the invited account; with their minimal scopes (`public_repo`, `read:org`) the member tokens are usually refused by the membership endpoints ([REST members](https://docs.github.com/en/rest/orgs/members)), and a fine-grained token cannot exist before the membership | bootstrap tries with the member's own token, then prints `https://github.com/orgs/<org>/invitation` and the People page `https://github.com/orgs/<org>/people`; `--wait` polls every 10 s until each account is active and public; setup invites and waits for the fine-grained roles |
| Approving a member's fine-grained token request | an owner's action in the organization settings; the API exists for GitHub Apps only (permission `organization_personal_access_token_requests`), and is deliberately not used: the e2e App's private key reaches the webapp under test, untrusted pull request images included, which could then approve tokens | the approval URL `https://github.com/organizations/<org>/settings/personal-access-token-requests` in setup's token steps and closing list, and in bootstrap's hint when a member's token is refused |
| Authorizing a classic token for SAML SSO | a click in the token settings (Configure SSO) with an active SAML session ([authorizing a token for SSO](https://docs.github.com/en/enterprise-cloud@latest/authentication/authenticating-with-single-sign-on/authorizing-a-personal-access-token-for-use-with-single-sign-on)); fine-grained tokens are authorized when they are created | doctor and every session report the SSO requirement of a token (`X-GitHub-SSO`); [setup-enterprise-org.md](setup-enterprise-org.md#saml-single-sign-on) |

Everything else is automated: the org checks, the token checks, the env file, the invitations (bootstrap and setup),
the safety marker after your typed confirmation, the repositories, teams and baseline, the App credentials, and the
CI environments, protections, variables and secrets (`ci-sync`).

## GitHub limits that matter

| Limit | Value | Effect here |
|---|---|---|
| Organization invitations ([REST members](https://docs.github.com/en/rest/orgs/members)) | 50 per 24 hours for an organization younger than a month on a free plan, 500 otherwise | a test organization needs at most three (author, approver, oracle), but repeated re-invitations count |
| Invitation lifetime | 7 days | an expired invitation is gone: `bootstrap --apply` (or setup, for fine-grained roles) invites again |
| Fine-grained tokens per user | 50 | an account serving several instances needs one fine-grained token per organization |
| Fine-grained token lifetime | `expires_in` 1 to 366 days; organizations cap it at 366 days by default, an enterprise maximum caps it further | `--expires-in`, default 90; doctor warns 14 days before the expiry |
| Fine-grained token name | 40 characters | setup names tokens `otterdog-e2e-<instance>-<role>`, shortened with a hash when longer |
| App manifest code ([manifest flow](https://docs.github.com/en/apps/sharing-github-apps/registering-a-github-app-from-a-manifest)) | valid one hour | setup exchanges it at once; `app-manifest --exchange <code>` must run within the hour |
| Required reviewers per environment ([REST environments](https://docs.github.com/en/rest/deployments/environments)) | 6 | `ci-sync --reviewer` at most 6 times |
| Free machine accounts ([Terms of Service](https://docs.github.com/en/site-policy/github-terms/github-terms-of-service)) | one per person, besides their own account | a full set of roles (admin, author, approver, outsider, config_reader, optionally oracle) needs several people |
