# Setting up a GitHub Enterprise Cloud test organization

The target `enterprise` (`targets/enterprise.yaml`, `expected_plan: enterprise`) runs the enterprise tier
(`tests/enterprise`, `scenarios/enterprise`, scenarios with `min_plan: enterprise`) and every other tier with the
enterprise capabilities. Follow [setup-free-org.md](setup-free-org.md) first: accounts, tokens, env file, doctor,
bootstrap and the GitHub App work the same way. This page lists what differs.

## Supported

- **GitHub Enterprise Cloud on github.com only.** otterdog hard-codes `api.github.com`, `api.github.com/graphql` and
  `https://github.com`, so GitHub Enterprise Server and GitHub Enterprise Cloud with data residency (`*.ghe.com`)
  cannot be tested without code changes.
- **No Enterprise Managed Users (EMU).** Managed users have no password, cannot be invited outside the enterprise and
  EMU organizations have no public repositories, while the harness relies on public fixture repositories and on
  personal machine accounts.
- A **Team** organization works through capabilities: copy `targets/free.yaml` to `targets/team.yaml`, set
  `name: team` and `expected_plan: team`, create `~/.config/otterdog-e2e/team.env` and the CI environments
  `e2e-team` and `e2e-team-untrusted`.

## Getting an Enterprise Cloud organization

| Option | Notes |
|---|---|
| Enterprise Cloud trial | 30 days, no payment method, up to 50 licenses, includes Code Security and Secret Protection, no larger runners. You can create up to three organizations in the trial enterprise or transfer existing ones. Organizations created in the trial cannot be removed before you purchase; expired trials are deleted 90 days after the end. |
| Transfer a Free test organization into a trial | not possible for organizations with Marketplace apps or owned by another enterprise; on expiry or cancellation the organization reverts to its previous plan and settings. Re-run bootstrap afterwards (the plan in the baseline changes). |
| Sandbox organization in an existing enterprise | no extra seats for members who already hold a license; the enterprise's policies apply (see below). |
| Paid upgrade | Enterprise Cloud is billed per user. |

Whatever the option, the organization must stay a dedicated test organization: same machine accounts rules, same
safety marker, no unmanaged repositories.

## Target and env file

```bash
install -m 600 .env.example ~/.config/otterdog-e2e/enterprise.env
$EDITOR ~/.config/otterdog-e2e/enterprise.env      # E2E_ORG, E2E_ORG_ID, identities of this organization
.venv/bin/otterdog-e2e doctor --target enterprise
.venv/bin/otterdog-e2e bootstrap --target enterprise --apply
```

- When the same machine accounts serve the Free and the Enterprise organizations, list the other organization's id
  in `E2E_ALLOWED_ORG_IDS` of **both** env files; otherwise the isolation check fails.
- Capability overrides (`github.capabilities` in the target file) adjust what the plan matrix grants. For a trial:

    ```yaml
    capabilities: {add: [ghas_private], remove: [larger_runners]}
    ```

    `ghas_private` is never probed: add it only when Code Security / Secret Protection covers private repositories.
    See [capability-matrix.md](capability-matrix.md).

- One GitHub App per test organization: create a second App with
  `app-manifest --target enterprise --webhook-url ...` (the credentials go to `~/.config/otterdog-e2e/enterprise/`).

## SAML single sign-on

With SAML SSO enforced on the organization (or its enterprise):

- authorize **every classic PAT** for the organization (token settings, Configure SSO, Authorize). An unauthorized
  token gets 403/404 answers with an `X-GitHub-SSO` header; doctor and the harness report the SSO requirement (the
  authorization link itself is never printed);
- the machine accounts need an identity in your IdP and an active SAML session to accept invitations and to
  authorize tokens;
- fine-grained tokens (config_reader) are subject to the organization's fine-grained token policy: allow them, or
  approve the token request;
- set `github.saml_sso: true` in `targets/enterprise.yaml`: otterdog's web client cannot log in through SSO ("Your
  organization requires single sign-on login which is currently not supported by the web client"), so the web-UI tier
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

Enterprise-level objects visible in the organization count as unmanaged organization-level objects: an enterprise
ruleset or an enterprise custom property applying to the test organization appears as a removal in every guarded
`apply -d` plan, and the baseline reset stops with a `SafetyError`. Do not target the test organization with
enterprise rulesets or custom properties.

## Running

```bash
make enterprise TARGET=enterprise          # enterprise tier
make cli TARGET=enterprise                 # the CLI tier with enterprise capabilities (private repo protections, ...)
make e2e TARGET=enterprise                 # every tier
```

In CI, add `enterprise` to the repository variable `E2E_TARGETS` (for example `["free", "enterprise"]`) and create
the environments `e2e-enterprise` and `e2e-enterprise-untrusted` with the same secrets and variables as for `free`
(see [security.md](security.md#ci-environments)).
