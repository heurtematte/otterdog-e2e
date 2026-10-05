# Setting up a GitHub Enterprise Cloud test organization

The profile `enterprise` (`targets/enterprise.yaml`, `expected_plan: enterprise`) runs the enterprise tier
(`tests/enterprise`, `scenarios/enterprise`, scenarios with `min_plan: enterprise`) and every other tier with the
enterprise capabilities. Every Enterprise Cloud test organization is an **instance** of it: the instance
`enterprise` (bound to the profile of the same name), or any other name whose env file sets `E2E_PROFILE=enterprise`
([onboarding.md](onboarding.md#instances-and-profiles)). `otterdog-e2e setup --target <instance> --profile enterprise`
onboards it ([onboarding.md](onboarding.md)); [setup-free-org.md](setup-free-org.md) describes the steps by hand:
accounts, tokens, env file, doctor, bootstrap and the GitHub App work the same way. This page lists what differs.

## Supported

- **GitHub Enterprise Cloud on github.com only.** otterdog hard-codes `api.github.com`, `api.github.com/graphql` and
  `https://github.com`, so GitHub Enterprise Server and GitHub Enterprise Cloud with data residency (`*.ghe.com`)
  cannot be tested without code changes.
- **No Enterprise Managed Users (EMU).** Managed users have no password, cannot be invited outside the enterprise and
  EMU organizations have no public repositories, while the harness relies on public fixture repositories and on
  personal machine accounts.
- A **Team** organization uses the profile `team` (`targets/team.yaml`, `expected_plan: team`; the plan matrix
  grants its capabilities): `otterdog-e2e setup --target team` (or another instance name with `--profile team`),
  then `ci-sync` for its CI environments.

## Getting an Enterprise Cloud organization

| Option | Notes |
|---|---|
| Enterprise Cloud trial | 30 days, no payment method, up to 50 licenses, includes Code Security and Secret Protection, no larger runners. You can create up to three organizations in the trial enterprise or transfer existing ones. Organizations created in the trial cannot be removed before you purchase; expired trials are deleted 90 days after the end. |
| Transfer a Free test organization into a trial | not possible for organizations with Marketplace apps or owned by another enterprise; on expiry or cancellation the organization reverts to its previous plan and settings. Re-run bootstrap afterwards (the plan in the baseline changes). |
| Sandbox organization in an existing enterprise | no extra seats for members who already hold a license; the enterprise's policies apply (see below). |
| Paid upgrade | Enterprise Cloud is billed per user. |

Whatever the option, the organization must stay a dedicated test organization: same machine accounts rules, same
safety marker, no unmanaged repositories.

Creating the organization stays manual. An enterprise owner creates it in the enterprise (Organizations, New
organization), or with the GraphQL mutation `createEnterpriseOrganization`
([enterprise administration](https://docs.github.com/en/enterprise-cloud@latest/graphql/reference/enterprise-admin)):
`setup` prints that hint when the organization does not exist yet (for the `enterprise` profile, or next to the Free
URL while the profile is not known: pass `--profile enterprise`), but never creates one, since it would need an
enterprise owner's token ([What cannot be automated](onboarding.md#what-cannot-be-automated)).

## Instance and env file

```bash
.venv/bin/otterdog-e2e setup --target enterprise                   # or: setup --target acme-ghec --profile enterprise
.venv/bin/otterdog-e2e doctor --target enterprise
```

By hand (the file setup would write):

```bash
install -m 600 .env.example ~/.config/otterdog-e2e/enterprise.env
$EDITOR ~/.config/otterdog-e2e/enterprise.env      # E2E_ORG, E2E_ORG_ID, identities of this organization
.venv/bin/otterdog-e2e doctor --target enterprise
.venv/bin/otterdog-e2e bootstrap --target enterprise --apply --wait
```

Another instance name needs `E2E_PROFILE=enterprise` in its file (`~/.config/otterdog-e2e/acme-ghec.env`). Several
Enterprise Cloud organizations are several instances of the same profile; their per-instance differences live in
their env files (below), never in `targets/enterprise.yaml`.

- When the same machine accounts serve the Free and the Enterprise organizations, list the other organization's id
  in `E2E_ALLOWED_ORG_IDS` of **both** env files; otherwise the isolation check fails. `setup` offers it for a classic
  token only when the other organization is already a set up and bootstrapped instance (its env file holds the admin
  login and token, its description the safety marker), and writes both files once the token passed every check
  ([onboarding.md](onboarding.md#tokens)); otherwise set it by hand. Fine-grained tokens are bound to one
  organization: such accounts need one token per organization.
- Enterprises often forbid classic PATs: use fine-grained tokens
  ([setup-free-org.md](setup-free-org.md#fine-grained-personal-access-tokens)), set `E2E_<ROLE>_TOKEN_TYPE=fine-grained`
  and leave the `outsider` unset if it cannot have a classic PAT (its negative tests are skipped). On an Enterprise
  Cloud organization the admin token most likely also needs organization Custom organization roles **Read and write**
  (custom roles are managed there; the Enterprise Cloud role endpoints are missing from GitHub's fine-grained
  permission tables: to confirm on the first live run).
- Capability overrides adjust what the plan matrix grants, per instance: `E2E_CAPABILITIES_ADD` and
  `E2E_CAPABILITIES_REMOVE` (comma separated capability names) in the env file, or as variables of its CI
  environments (`ci-sync` copies them). For a trial:

    ```bash
    E2E_CAPABILITIES_ADD=ghas_private
    E2E_CAPABILITIES_REMOVE=larger_runners
    ```

    `ghas_private` is never probed: add it only when Code Security / Secret Protection covers private repositories.
    A custom profile can also write them literally (`capabilities: {add: [ghas_private], remove: [larger_runners]}`).
    See [capability-matrix.md](capability-matrix.md).

- One GitHub App per test organization: `setup` creates it for each instance, or
  `app-manifest --target <instance> --webhook-url ...` (the credentials go to `~/.config/otterdog-e2e/<instance>/`,
  here `~/.config/otterdog-e2e/enterprise/`).

## SAML single sign-on

With SAML SSO enforced on the organization (or its enterprise):

- authorize **every classic PAT** for the organization (token settings, Configure SSO, Authorize): a click in the
  web UI with an active SAML session, which no API can do
  ([authorizing a token for SSO](https://docs.github.com/en/enterprise-cloud@latest/authentication/authenticating-with-single-sign-on/authorizing-a-personal-access-token-for-use-with-single-sign-on)).
  Authorize it before you paste it into `setup`, whose checks would otherwise fail. An unauthorized token gets
  403/404 answers with an `X-GitHub-SSO` header; doctor and the harness report the SSO requirement (the
  authorization link itself is never printed);
- the machine accounts need an identity in your IdP and an active SAML session to accept invitations and to
  authorize tokens;
- fine-grained tokens (config_reader, and every role in an enterprise that forbids classic PATs) need no SSO
  authorization step: GitHub authorizes them when they are created (an active SAML session of the account may be
  required then). They are subject to the organization's fine-grained token policy instead: allow them, and approve
  the token requests of members ([organization prerequisites](setup-free-org.md#organization-prerequisites));
- set `E2E_SAML_SSO=true` for the instance (env file, and the CI variable `ci-sync` copies; it fills
  `github.saml_sso` of the profile): otterdog's web client cannot log in through SSO ("Your organization requires
  single sign-on login which is currently not supported by the web client"), so the web-UI tier
  ([web-ui-testing.md](web-ui-testing.md)) is skipped with that reason; the token tiers are unaffected. Without SSO,
  the web-UI tier also covers `packages_containers_internal`, the web setting that only exists with internal
  visibility (Enterprise Cloud).

## IP allow lists

GitHub-hosted runners use changing IP addresses. If the organization or its enterprise enforces an IP allow list,
either keep it disabled for the test organization or run the live lanes from runners whose egress addresses you
allow. The GitHub App needs "IP allow list configuration for installed GitHub Apps" if the list is enabled.

## Enterprise policies

Enterprise policies can lock organization settings (repository creation, forking, Actions permissions, base
permissions, two-factor requirement, ...). A locked setting that the baseline or a scenario tries to change makes
`apply` fail or leaves a permanent drift (converge never reaches a no-op). Keep the enterprise policies permissive
for the test organization, or set `baseline.settings` in the target to the values the policies enforce.

The enterprise's personal access token policies (**Policies, Personal access tokens**) decide which token kinds
reach the organization: with "Restrict access via personal access tokens (classic)" every classic PAT gets 403
answers, so switch the roles to fine-grained tokens (see above); the maximum lifetime set there caps the
organization's.

Enterprise-level objects visible in the organization count as unmanaged organization-level objects: an enterprise
ruleset or an enterprise custom property applying to the test organization appears as a removal in every guarded
`apply -d` plan, and the baseline reset stops with a `SafetyError`. Do not target the test organization with
enterprise rulesets or custom properties.

## Running

```bash
make enterprise TARGET=enterprise          # enterprise tier
make cli TARGET=enterprise                 # the CLI tier with enterprise capabilities (private repo protections, ...)
make e2e TARGET=enterprise                 # every tier
make cli TARGET=free,enterprise            # the Free and the Enterprise Cloud organizations, one after the other
```

In CI, `ci-sync` creates the environments `e2e-<instance>` and `e2e-<instance>-untrusted` of the instance with its
secrets and variables, and adds it to the allowlist `E2E_INSTANCES`; `--nightly` also adds it to `E2E_TARGETS` (for
example `["free", "enterprise"]`) for the nightly and janitor runs ([onboarding.md](onboarding.md#ci-ci-sync),
[security.md](security.md#ci-environments)). A dispatch can then name several instances:

```bash
.venv/bin/otterdog-e2e ci-sync --target enterprise --nightly --apply
gh workflow run e2e.yml -f target=free,enterprise -f sut=release:latest   # one job per instance
```
