# Security

otterdog-e2e gives a program that can create, change and delete GitHub resources (otterdog, possibly an unreviewed
pull request of it) organization-owner credentials. This document describes what can go wrong, which controls the
harness enforces, what you must set up yourself, and what to do when something went wrong.

## Threat model

**Assets**

- the dedicated test organizations and everything in them;
- the credentials: the admin classic PAT (`admin:org`, `delete_repo`), the other machine-account tokens, the GitHub
  App private key and its webhook secret, and, for the optional web-UI tier, the admin bot's password and TOTP seed
  (a full interactive login to github.com: [web-ui-testing.md](web-ui-testing.md));
- every other organization those credentials could reach: this is the main risk;
- this repository: its workflows and the secrets of its CI environments.

**Threats**

| Id | Threat |
|---|---|
| T1 | A buggy or malicious SUT (an upstream pull request runs arbitrary code at build and run time) acts on a real organization or exfiltrates credentials. |
| T2 | A harness bug deletes objects it does not own (unmanaged repositories, protected repositories, organization settings). |
| T3 | Secrets leak into logs, artifacts, observations, step summaries or PR comments (otterdog prints secret values and caches request headers). |
| T4 | Concurrent sessions (local, CI, janitor, App deliveries) race on the same organization. |
| T5 | CI-specific: script injection through inputs, credentials persisted by checkout, cache poisoning between runs, untrusted code reaching secrets without review, workflow edits on a branch obtaining environment secrets. |
| T6 | The webapp's unauthenticated `/internal` and `/api` endpoints exposed beyond the local machine. |

## Controls enforced by the harness

### Dedicated machine accounts (T1, T2)

The decisive control: every identity must be a machine account that belongs **only** to test organizations. A
token of a personal account that owns or belongs to real organizations is refused, so even code that ignores every
other check cannot reach a real organization.

`verify_target` checks every configured identity before a session writes anything:

- `GET /user/orgs` and the pending memberships (`GET /user/memberships/orgs?state=pending`): every organization id
  must be in `github.allowed_org_ids` (the pinned org id plus `E2E_ALLOWED_ORG_IDS`); a membership in a denylisted
  organization is refused even when its id is allowed; the `outsider` must not belong to (nor be invited by) the
  test organization;
- classic token scopes (`X-OAuth-Scopes`) must be a subset of the role's allowlist:

| Role | Allowed classic scopes | Notes |
|---|---|---|
| `admin` | `repo`, `workflow`, `admin:org`, `admin:org_hook`, `delete_repo`, `read:org`, `read:user`, `user:email` | doctor also requires `repo`, `workflow`, `admin:org`, `admin:org_hook`, `delete_repo` (otterdog's requirement) |
| `oracle` (optional, separate) | same as admin | must be an organization owner |
| `author`, `approver`, `outsider` | `public_repo`, `repo`, `read:org`, `read:user`, `user:email`, `workflow` | use `public_repo` + `read:org` |
| `config_reader`, `readonly` | fine-grained tokens only | public repositories, read-only |

- fine-grained tokens are accepted for every role except the `outsider`, under the rules of
  [Fine-grained personal access tokens](#fine-grained-personal-access-tokens-t1-t2) below (GitHub answers
  `200 []` to `GET /user/orgs` for them, so the account check above proves nothing and the proof moves to the token);
- the kind of every token is detected (`X-OAuth-Scopes` present on `GET /rate_limit`: classic; absent and
  `github_pat_` prefix: fine-grained) and must match `identities.<role>.token_type` when the target declares it
  (`classic` or `fine-grained`; `auto` by default, from `E2E_<ROLE>_TOKEN_TYPE` in the shipped targets);
- two roles never share a token (except `oracle` falling back to `admin`, and `config_reader` with `readonly`);
- logins are declared in the target (public data) and compared with `GET /user`; they are never derived from tokens.

### Fine-grained personal access tokens (T1, T2)

Some enterprises forbid classic PATs. Every role except the `outsider` can then use a fine-grained PAT; the setup
(resource owner, repository access, permissions per role, org approval) is in
[setup-free-org.md](setup-free-org.md#fine-grained-personal-access-tokens).

A fine-grained PAT is bound to **one resource owner** (a user or an organization) and can only reach the resources of
that owner, plus read access to public repositories ("Each token is limited to access resources owned by a single
user or organization"; "Tokens always include read-only access to all public repositories", GitHub docs, *Managing
your personal access tokens*). Its account's other memberships are therefore irrelevant: what must be proven is that
the token's resource owner is the test organization. `check_identity_isolation` does it per role, failing closed on
any other answer (403, 404, an error), and the `SafetyError` names the permission GitHub asks for
(`X-Accepted-GitHub-Permissions`):

| Role | Proof (every request must answer 200) | Why it proves the resource owner |
|---|---|---|
| `admin`, `oracle` | `GET /orgs/{org}/actions/permissions` and `GET /orgs/{org}/hooks` | organization-owner data, reachable only through the organization permissions Administration (read) and Webhooks (read); organization permissions exist only on a token whose resource owner is that organization, and only an owner's token can read them |
| `author`, `approver` | `GET /user/memberships/orgs/{org}`: `state` `active`, `organization.id` = the pinned id | the token user's membership, read through the organization permission Members (read), which again only applies to the token's resource owner |
| `outsider` | refused | see below |
| `config_reader`, `readonly` | unchanged (any non-classic token, visible memberships checked) | they only read public data |

Without the organization login a fine-grained owner or member token is refused (fail closed). Classic tokens keep the
account-membership and scope checks above.

The `outsider` must stay a non-member and comment on the test organization's public repositories. GitHub documents
that fine-grained tokens cannot "contribute to public repos where the user is not a member" and that "only personal
access tokens (classic) have write access for public repositories that are not owned by you or an organization that
you are not a member of": the `outsider` therefore requires a classic PAT, `token_type: fine-grained` is refused when
the target is loaded, and a fine-grained token found at run time fails the isolation check. In an enterprise that
forbids classic PATs everywhere, leave the `outsider` unset: its negative tests are skipped.

What the harness cannot check for fine-grained tokens, and what remains to confirm on the first live run:

- **least privilege**: GitHub exposes no API that lets a token read its own fine-grained permissions (the
  organization listing `GET /orgs/{org}/personal-access-tokens` is GitHub App only), so the scope allowlists above
  have no fine-grained equivalent. Grant exactly the permissions of the setup tables; doctor probes the **read** side
  of the admin/oracle permissions, the write side shows up in the first live run;
- **"All repositories"**: whether the token covers repositories created after it is not readable either; the
  harness creates run repositories and the per-session config repository during the run (to confirm on the first live
  run: GitHub's docs extract does not state it);
- the exact answer of a token bound to another owner (403 "Resource not accessible by personal access token" or 404)
  is not documented; both fail the proof;
- the `github-authentication-token-expiration` response header that doctor reads for the expiry date is not in
  GitHub's REST docs; when it is absent doctor reports "no expiration".

### Organization pin (T1, T2)

`verify_target` requires, with the admin token: the exact-case login of the target, the pinned numeric `org_id`,
the expected plan (`free`, `team` or `enterprise`; reading it needs an owner token with `admin:org`, or a fine-grained owner token with the organization permission Plan, which GitHub documents for Apps only: to confirm on the first live run), and the safety
marker (default `[otterdog-e2e]`) in the organization description. Logins matching a denylist of real organizations
are always refused (`eclipse`, `eclipse-*`, `eclipsefdn*`, `eclipse-csi`, `adoptium`, `jakartaee*`, `openhwgroup*`,
`osgi`, `jetty*`, `microprofile*`, `locationtech*`, `deeplearning4j`, `eclipsenebula`, `orcwg`, `rust-sig`,
`winery`, `cra-attestations`). The renderer refuses an organization description without the marker, so an apply can
never remove it.

`bootstrap --apply` is the only path that writes the marker: it requires typing the organization login, it is
refused when `CI` is set, and it refuses an organization holding repositories the harness does not manage.

### Capability objects and write scope (T1, T2)

Only `verify_target` can construct a `VerifiedOrg`. Every writer requires one: `Mutator`, `TemplatePublisher`,
`Janitor`, `OrgLease`, `WebappStack`, a live `OtterdogCli` and a write-scoped `GitHubHttp`. A write-scoped client
sends non-GET requests only to `/repos/<org>/…`, `/orgs/<org>[/…]`, `/app/installations/<id>/access_tokens`,
`/app-manifests/…`, `/user/memberships/orgs/<org>` and GraphQL; a read-only client refuses any write (GraphQL
mutations included). Mutating calls never follow redirects: a 3xx answer (a renamed or transferred repository is
answered with a 307 to `/repositories/<id>`) surfaces as an error instead of taking the write outside the verified
organization; reads and GraphQL queries still follow redirects. Deletion helpers accept only run-prefixed names
(`e2e-<run>-…`, `E2E_<RUN>_…`), harness refs and hooks below `https://otterdog-e2e.invalid/`. The probe and drift
writes of the battery (topics, collaborators, teams and team members, workflow dispatch/cancel/re-run, security
advisories, code security configurations) only touch e2e-named objects; pull request edits (comment edits and
deletions, review dismissals, ready/draft, reopen) only touch pull requests whose head is a run branch of the same
repository (`e2e/<run>/…`, `otterdog/e2e-<run>-…`, `otterdog/blueprint/e2e-<run>-…`); a team member must already be
an organization member (GitHub would otherwise send an organization invitation).

### GitHub App isolation (T1)

Token isolation does not cover the GitHub App, whose private key reaches the webapp under test (untrusted PR images
included): with it, code can list the App's installations and mint installation tokens for each of them. Before the
key is written for a webapp stack (re-checked at every start) and for the installation preflight (`installation_id`,
`check_app`, the relay), `safety.verify_app` requires, with a fresh `GET /app` and every page of
`GET /app/installations`:

- the owner is the test organization: `owner.type` Organization, `owner.id` equal to the pinned `org_id` (and the
  login of the target);
- every installation is an organization installation on the test organization, or on another id of
  `github.allowed_org_ids` that passes the denylist; enterprise and user installations are refused;
- `installations_count` does not exceed the number of listed installations.

A refusal is a `SafetyError`: webapp items fail with the reason (they are not skipped), and doctor's `app:owner` row
fails. Use only the private App created in the test organization by `otterdog-e2e app-manifest`.

### Org lease and run ledger (T4)

A session that may write holds the org lease: the ref `refs/heads/e2e-lease` in the configs repository, pointing to a
commit whose message records the run id, the holder (`local:<user>` or the CI run URL) and an expiry (3 hours,
renewed by a heartbeat; steal and renew use compare-and-swap). The lease is taken by every live pytest session,
`bootstrap --apply`, `janitor --apply`, the standalone `relay` and template publishing. Each run also registers
`refs/tags/e2e-run/<run>`; the janitor and resets only purge run ids that are in this ledger and do not hold an
unexpired lease, so a name that merely looks like a run prefix is never swept. `E2E_LEASE_WAIT` (seconds) makes a
session wait for a busy lease instead of failing.

- A run id serves one session: a run id already in the ledger is refused before the lease is touched, an unexpired
  lease is never taken over because it names the same run id and holder (only the session's own lease commit is
  "its" lease), and a second session reusing a running session's run id on the same machine is refused at start
  (lock `<E2E_CACHE_DIR>/run/<run>.lock`), so it can neither steal, delete nor share the first one's lease and
  scratch directory.
- Losing the lease stops the session's writes: once a renewal fails (taken over or deleted), live items fail, and
  write-scoped GitHub clients, guarded otterdog applies and live otterdog commands raise `SafetyError`.
- `janitor --run-id <run> --apply` takes the lease of that run over with the same compare-and-swap update as an
  expired steal (never a delete, so a session that acquired the lease meanwhile keeps it), and only when the run looks
  dead: its last renewal is older than 20 minutes (the heartbeat renews every 10), or the holder is the janitor's own
  CI job; `--force-takeover` is the explicit override for a run you know is dead.

### Guarded destructive operations (T1, T2)

- otterdog's `-r` filter scopes repositories only: organization-level objects (settings, teams, org secrets,
  variables, webhooks, rulesets, roles, custom properties) are always diffed and, with `-d`, deleted. Every
  `apply -d` therefore goes through `BaselineManager.guarded_apply()`: a `plan` with the same filter, parsed
  fail-closed (the `Plan:` delete count must equal the number of `- remove …` headers, nested objects included),
  then every removal must carry a purgeable run id and must not name a protected object, otherwise `SafetyError`
  and nothing is applied. A change of the organization description is refused as well. The `apply -d` of a scenario
  step is guarded by a plan with exactly the apply's diff flags (`--only-secrets` hides every non-secret removal
  from a plan): the model refuses a deleting step whose plan and apply flags differ, or that uses `only_secrets`, and
  the engine plans again with the apply's options when a step reaches it anyway.
- Protected repositories (the run's config repository, the configs, defaults and fixture repositories,
  `fixtures.extra_protected_repos`) are never in a `-d` scope; extra protected repositories are never rendered.
- Every apply of a scenario step (and every live `inject`, already in its plan-only pre-pass) refuses a plan that
  changes an object without a run id the baseline does not declare: an extra protected or unmanaged repository and
  its nested objects, a team or an organization-level object named by hand. The baseline reset could never restore
  such a change; only the organization `settings`, the baseline repositories and the baseline teams may change.
- Consequence for your test organization: any unmanaged organization-level object without a run id (a team created
  by hand, an org secret, enterprise-level rulesets or custom properties visible in the org) makes every guarded
  reset fail until you delete it or declare it in the baseline. doctor lists unmanaged repositories and teams.
- Webapp merges apply with `delete_resources`; every PR text is therefore checked by a guard (a `local-plan` with the
  trusted reset CLI) before the harness pushes, approves, merges or comments `/otterdog merge|apply`. A head the
  trusted CLI cannot load or validate is accepted unchecked for a push only; before an approval, a merge or a
  `/otterdog merge|apply` it is accepted only when the SUT itself reports the PR invalid (a `failure` or `error`
  validation status on that head), otherwise the removal check must pass (a newer SUT may accept what the release
  cannot load, and would then apply it).

### Trusted reset SUT (T1, T2)

Baseline resets, scenario cleanups and PR guards run with a trusted SUT (`--e2e-reset-sut`, default
`release:latest`), never with the SUT under test; an untrusted reset SUT is refused.

### Untrusted SUTs (T1, T3)

Pull requests (`pr:N@sha`) and shas not reachable from upstream main or a `v*` tag are untrusted:

- they must be pinned to a full 40-hex sha that is reachable from `refs/pull/N/head`, and exactly that commit is
  built (a push after the review does not change what runs);
- they are exported to a private directory and only built as a docker image (`otterdog-e2e/untrusted:<label>`,
  never reused as trusted); host installs are refused unless an operator passes `--e2e-trust-code <sha>` from an
  interactive terminal (refused when `CI` is set);
- the CLI runs in the image: `docker run --rm --init --name otterdog-e2e-<run>-<seq> --read-only --tmpfs /tmp
  --user <uid>:<gid> -e HOME=/tmp --cap-drop ALL --security-opt no-new-privileges`, the workspace bind-mounted at
  `/ws`, an env-file (0600) holding only the `E2E_OTTERDOG_*` credentials, `--network none` for offline commands; a
  timed-out container is removed (`docker rm -f`), so it cannot keep applying;
- the mounted workspace is untrusted once a container ran in it (same uid, read-write): after every container
  command the harness removes every symlink that resolves outside the workspace and every special file (FIFO, socket)
  the container left there, reads the files it wrote (check-status JSON, imported and fetched configs) only as
  regular files inside the workspace without following links (`O_NOFOLLOW`, `O_NONBLOCK`), replaces a planted link
  instead of writing through it, and refuses to create, write or delete anything whose directory resolves outside
  the workspace; otherwise a planted `check-status.json -> ~/.aws/credentials` would be read and exported, or a
  planted destination link would turn a copy into a host file write;
- they never receive web-UI credentials (username, password, TOTP: the harness passes `unset`), and the webapp tier
  of an untrusted SUT requires a `config_reader` fine-grained token for `OTTERDOG_CONFIG_TOKEN`;
- they never write the trusted caches (sources, builds, HTTP cache).

### Web-UI credentials (T1, T3, T4)

The web-UI tier ([web-ui-testing.md](web-ui-testing.md)) lets otterdog log in to github.com as the admin bot
(username, password, TOTP seed: more than any token, since it opens a browser session of an organization owner):

- `Cap.WEB_UI` needs the credentials AND `--e2e-allow-web-ui` (or `E2E_ALLOW_WEB_UI`) AND a trusted SUT under test AND
  `github.saml_sso: false`; target overrides can never add it; the gate runs before any fixture;
- the credentials are resolved apart from the tokens (`settings.WebCredentials`), must belong to the admin machine
  account, and reach otterdog only for the commands that log in, through the env credential provider; ordinary CLIs
  and every other command get `unset`;
- `WebOtterdogCli` refuses container runtimes and untrusted SUTs (even with `--e2e-trust-code`); the Playwright
  browser is installed only with the Playwright of trusted host installs;
- the password and the seed are redacted (their variable names end with `_PASSWORD` and `_TOTP_SEED`); otterdog never
  gets more than `-v` (`-vvv` logs TOTP codes and exception locals); its Playwright page dumps stay in the scratch;
- a login gate serializes the web logins of a machine and spaces them by a TOTP window; a blocking login failure
  stops further attempts (no lockout through retries);
- the original web settings are recorded before the tier changes them and restored with the trusted reset SUT.

### Processes and environment (T3)

Every subprocess runs through `procs.run()` with a sanitized environment: variables matching `E2E_*`, `OTTER*`,
`GITHUB_TOKEN`, `GH_*`, `ACTIONS_*`, `*_TOKEN`, `*_SECRET`, `*_PASSWORD`, `*_TOTP*`, credential-like names, SSH and
askpass helpers, `PIP_*`, `POETRY_*`, `PYTHON*`, `KUBECONFIG` and the GitHub Actions files are removed; `HOME`
points to the run's scratch directory; `GIT_CONFIG_GLOBAL=/dev/null`, `GIT_TERMINAL_PROMPT=0`, `NETRC=/dev/null`,
`PYTHON_DOTENV_DISABLED=1`. Children run in their own process group, which is terminated on timeout or interrupt.
Credentials reach otterdog only through the variables named in the generated `otterdog.json`.

### Scratch versus artifacts (T3)

- otterdog's HTTP cache (`.cache/async_http`) pickles request headers, the `Authorization` header included. Every
  otterdog command therefore runs in a fresh private directory below `E2E_CACHE_DIR/run/<run>/` (mode 0700, never
  below the artifacts root; the harness refuses `E2E_CACHE_DIR` inside `E2E_ARTIFACTS`), and the HTTP caches of live
  commands live there too (`run/<run>/http-cache/<sut>-<identity>`), trusted SUTs included; only the caches of offline
  commands (dummy token) are shared across runs in `E2E_CACHE_DIR/http-cache/<sut>-offline`. Live caches that older
  harness versions kept in `E2E_CACHE_DIR/http-cache` are deleted at the end of every session. The App key,
  env-files and compose files live in the scratch directory too. It is deleted at session end unless `--e2e-keep`.
- Artifacts are redacted text copies only (`*.txt`, `*.json`, `*.jsonl`, `*.md`, `*.log`, `*.xml`).
  `scrub-artifacts` deletes every other file, symlinks and special files, scans the remaining bytes for every
  registered secret and its variants and for token patterns, deletes leaking files and writes `leaks.json`; a leak
  fails the session and the CI job, and CI uploads artifacts only after a successful scrub (retention 7 days).
- Never write `docker compose config` or `docker inspect` output anywhere: both inline the secrets.

### Redaction (T3)

The redactor replaces registered secrets (tokens, App key, JWTs, installation tokens, webhook secret, `SECRET_KEY`)
and their variants (base64, `x-access-token:` base64, URL-encoded, JSON-escaped, `$$`-escaped, each PEM line) and the
patterns `gh[pousr]_…`, `github_pat_…`, JWTs and PEM private keys with `***`, in logs, reports, pytest reports and
artifacts. In GitHub Actions it also emits `::add-mask::` for each value, written to the runner's original stdout
(duplicated before pytest starts capturing: a capture buffer would swallow the workflow command), so values registered
during the session (minted JWTs and installation tokens included) are masked in the job log too. Only variables
whose name ends with
`_TOKEN`, `_SECRET`, `_PASSWORD`, `_TOTP_SEED` or `_PRIVATE_KEY` are registered: keep these suffixes.

Scenario secret values must be dummies or references (otterdog prints secret values in validate, plan and PR
comments): `********`, `e2e-dummy-<8 chars [0-9a-z]>` (webhook secrets too), `pass:<path>` references with shell-safe
paths (`[A-Za-z0-9_][A-Za-z0-9._/-]*`: otterdog resolves them with a shell command at apply time, which fails since
the harness provides no `pass`), `<provider>:e2e/<path>` for providers other than pass, bitwarden and vault, and,
offline only, the KB-025 literal with several `:` (`pass:a:b`); the loader refuses anything else, after the Jinja
render too. Live otterdog commands never get more than `-v`; pytest's `--showlocals` is refused when live tests are
selected.

### Webhooks and the webapp (T6)

- Managed webhooks point to `https://otterdog-e2e.invalid/<run>/<slug>`, a host that never resolves (GitHub still
  records the delivery attempts).
- The compose stack publishes only the webapp, on `127.0.0.1`; mongodb and valkey (which holds installation tokens)
  are never published.
- The external transport and the relay accept loopback URLs only, unless `--e2e-allow-remote-webapp` /
  `relay --allow-remote` is given explicitly. Do not expose a webapp under test through a tunnel: its `/internal` and
  `/api` endpoints are unauthenticated.
- The App webhook URL must be a non-loopback sink. A smee.io channel works as a sink but is public: anyone with the
  URL can read the test organization's payloads. Prefer an endpoint you control.

## CI environments

The workflows assume two environments per target (`free`, `team`, `enterprise`), plus an optional third one for the
web-UI lane:

| Environment | Used by | Protection | Contents |
|---|---|---|---|
| `e2e-<target>` | `e2e.yml` for trusted SUTs (manual runs, nightly), `janitor.yml` | no required reviewers; deployment branches: `main` only | secrets and variables below |
| `e2e-<target>-untrusted` | `e2e.yml` for untrusted SUTs (`e2e-otterdog-pr.yml`, `pr:`/untrusted `sha:` specs) | required reviewers (maintainers), prevent self-review, deployment branches: `main` only | same secrets and variables; `E2E_CONFIG_READ_TOKEN` is required for the webapp tier; never add web-UI credentials |
| `e2e-<target>-webui` (optional) | `e2e-webui.yml` (dispatch, nightly `webui` job when `E2E_WEB_UI_ENABLED` is `true`), trusted SUTs only | deployment branches: `main` only (required reviewers block the nightly job) | `E2E_ADMIN_TOKEN`, optionally `E2E_ORACLE_TOKEN`, and the ONLY copy of `E2E_ADMIN_PASSWORD` and `E2E_ADMIN_TOTP_SEED`; the variables of `e2e-<target>` plus optionally `E2E_ADMIN_USERNAME`, `E2E_WEB_LOGIN_SPACING` |

Secrets (environment secrets): `E2E_ADMIN_TOKEN` (required), `E2E_ORACLE_TOKEN`, `E2E_AUTHOR_TOKEN`,
`E2E_APPROVER_TOKEN`, `E2E_OUTSIDER_TOKEN`, `E2E_CONFIG_READ_TOKEN`, `E2E_APP_PRIVATE_KEY` (the PEM),
`E2E_APP_WEBHOOK_SECRET`.

Variables (environment variables, identical in both environments of a target): `E2E_ORG`, `E2E_ORG_ID`,
`E2E_ALLOWED_ORG_IDS`, `E2E_ADMIN_LOGIN`, `E2E_ORACLE_LOGIN`, `E2E_AUTHOR_LOGIN`, `E2E_APPROVER_LOGIN`,
`E2E_OUTSIDER_LOGIN`, `E2E_CONFIG_READER_LOGIN`, `E2E_APP_ID`, `E2E_APP_SLUG`, and optionally `E2E_CONFIGS_REPO`,
`E2E_ORG_CONFIG_REPO`, `E2E_DEFAULTS_REPO`, `E2E_TEMPLATE_MODE`, `E2E_TEMPLATE_URL`, `E2E_ADMIN_TEAM`,
`E2E_APPROVAL_TEAM`, `E2E_CONTRIBUTORS_TEAM`, `E2E_VALIDATION_CONTEXT`, `E2E_SYNC_CONTEXT`, `E2E_WEBAPP_WORKERS`,
`E2E_WEBAPP_PORT`, `E2E_MIN_RATE_REMAINING`, and the declared token kinds `E2E_ADMIN_TOKEN_TYPE`, `E2E_ORACLE_TOKEN_TYPE`, `E2E_AUTHOR_TOKEN_TYPE`, `E2E_APPROVER_TOKEN_TYPE`, `E2E_OUTSIDER_TOKEN_TYPE`, `E2E_CONFIG_READ_TOKEN_TYPE` (`auto`, `classic` or `fine-grained`). Repository variable: `E2E_TARGETS`, the JSON list of targets the nightly
and janitor workflows run on (default `["free"]`); while it is unset, their scheduled runs are skipped.

What the workflows enforce (and `tests/unit/test_workflows_static.py` checks):

- `permissions: {}` at the top of every workflow and `contents: read` per job (except the GitHub Pages jobs of
  `docs.yml`, below); actions pinned to full commit shas; `actions/checkout` with `persist-credentials: false` (the
  SUT must not find the `GITHUB_TOKEN` in `.git/config`);
- no `${{ }}` expression inside `run:` scripts: inputs and outputs reach scripts through `env:`, always quoted, and
  are validated in bash (`target` allowlist, suites allowlist, tag/glob/`-k` character sets, `pr` and `sha` regular
  expressions);
- `e2e.yml` first runs a `classify` job without secrets: `otterdog-e2e sut classify` decides the trust (an untrusted
  base SUT makes the run untrusted too) and writes, for untrusted SUTs, the PR title (as a code span), author, head
  repository, pinned sha versus head and the changed build/template files into the step summary, which is what the
  environment reviewer reads before approving;
- the `e2e` job selects the environment from that classification, joins the concurrency group `e2e-<target>` (no
  cancellation, queued runs wait), maps secrets on the harness steps only (the final janitor step gets the admin
  token only; the `scrub-artifacts` step gets every secret of its job, since a separate step inherits none and the
  scan must recognize leaked values without a token shape when the session step was killed before its own scrub),
  times out after 150 minutes (the session step after 120), always runs `janitor --run-id <run> --apply` when the
  session reached the test organization, and uploads artifacts only after `scrub-artifacts` succeeded;
- `cache-mode: none` everywhere: no Actions cache is restored or saved, so an untrusted run cannot poison a later
  trusted one; the upstream mirror and tool venvs are rebuilt in every run;
- `e2e-otterdog-pr.yml` is `workflow_dispatch` only (no `repository_dispatch`, no `pull_request_target`); its
  `resolve` job checks with the GitHub API that the PR targets eclipse-csi/otterdog and that the pinned sha is
  reachable from the PR head;
- `docs.yml` (the documentation site) uses no secret. Its build job runs for pull requests too, with `contents: read`
  plus `pages: read` (`actions/configure-pages`, on main only), and installs MkDocs from `docs/requirements.txt`
  (exact versions, `--require-hashes`, wheels only). Its deploy job, the only job of the repository allowed to write,
  holds just `pages: write` and `id-token: write`, runs only on `main` (never for a pull request) in the
  `github-pages` environment, and only publishes the artifact of the build job.

What you must configure: the two environments per target with the protections above, the secrets and variables, a
ruleset on `main` of this repository (pull request with review, no bypass), and GitHub-hosted runners only (never run
untrusted lanes on self-hosted or persistent runners). On a GitHub-hosted runner the PR code still controls the
container it runs in and the image it builds; the reviewer gate and the account confinement are the real controls.

## Residual risks

- A pull request under test receives the credentials of the untrusted environment inside its container: by design it
  can do anything those accounts can do in the test organizations. Keep the accounts confined to test organizations
  and review the classify summary before approving.
- The guarded apply is check-then-act: otterdog recomputes its diff after the verified plan. The lease and the webapp
  quiescing reduce, but do not remove, the window.
- Account isolation lists organization memberships only: outside-collaborator access of a machine account to
  repositories of other organizations is not detected. Do not add machine accounts as collaborators anywhere else.
- Memberships of fine-grained tokens cannot be verified through the API (they are accepted on their token type).
- A template published from a pull request is evaluated by the trusted reset CLI (jsonnet is data; every removal is
  still guarded).
- The lease is cooperative: a person or another tool can still change the test organization during a session.
- The web-UI tier hands a real interactive login of an organization owner to a trusted otterdog: a bug in that
  release could change any setting of the test organization the bot can reach in the UI. GitHub may also challenge or
  lock the bot (device verification, unusual activity of CI IP ranges); the login gate stops after the first blocking
  failure, the account still has to be checked by hand. Logins from two machines with the same bot are not
  coordinated (TOTP reuse): use one bot per target.

## Incident runbook

Use it after a suspicious untrusted run, a leaked artifact or log line, or an unexpected change in a test
organization.

1. **Stop.** Cancel the running workflows; temporarily add a deployment-branch rule that matches nothing (or disable
   the environments) so no new job gets secrets; suspend the GitHub App installation on the test organization
   (organization settings, GitHub Apps, Configure, Suspend), which also invalidates its installation tokens.
2. **Rotate** every credential the run could see:
    - each machine account's PATs (account settings, Developer settings, Personal access tokens: delete the old
      token, create a new one with the same scopes) and the fine-grained `config_reader` token;
    - the App private key (App settings, Private keys: generate a new key, then delete the old one) and the webhook
      secret (App settings, Webhook secret);
    - with the web-UI tier: the admin bot's password, its TOTP seed (remove the authenticator app from the account and
      add it again: a new setup key) and its web sessions (account settings, Sessions: revoke them), then
      `E2E_ADMIN_PASSWORD`/`E2E_ADMIN_TOTP_SEED` in `e2e-<target>-webui` and in the local env files;
    - the CI environment secrets of both environments and your local env files.
3. **Inspect** the organization: its audit log (organization settings, Logs, Audit log), owners
   (`GET /orgs/{org}/members?role=admin`), outside collaborators, deploy keys and default-branch heads of the
   configs, defaults and fixture repositories, organization and repository webhooks not pointing to
   `https://otterdog-e2e.invalid/`, the App hook URL, the `sut-*` tags of the defaults repository and the
   `e2e-lease` ref. Check the machine accounts' own security logs for new tokens, SSH keys or OAuth grants.
4. **Clean up**: `otterdog-e2e janitor --target <t> --apply`, then `otterdog-e2e bootstrap --target <t> --apply` to
   restore the baseline; delete the affected workflow artifacts (Actions run page, Artifacts).
5. **Report**: inform the maintainers of this repository; for an otterdog vulnerability follow the Eclipse Foundation
   vulnerability reporting process (https://www.eclipse.org/security/). Unsuspend the App and lift the environment
   block only after the rotation.
