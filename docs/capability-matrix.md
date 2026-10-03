# Capability matrix

A scenario declares what it needs (`requires`, `expect_failure_without`, `min_plan`, `identities`); the session
computes the target's capabilities once and the plugin skips, before any fixture runs, what the target cannot do.
`run.json` records the capabilities and the raw probe results of every session.

How the capabilities of a session are computed (`capabilities.probe_capabilities`):

1. the **plan matrix** of the verified plan (`GET /orgs/{org}` `plan.name`, readable only with an owner token holding
   `admin:org`);
2. read-only **probes** (they never fail a session; their HTTP statuses are recorded);
3. **environment** capabilities (App, docker, configured identities);
4. the target's **overrides** `github.capabilities: {add: [...], remove: [...]}`, applied last (remove wins);
5. the **derived** capability `web_ui`, which the session decides itself (overrides can remove it, never add it).

## Plan capabilities

| Capability | Free | Team | Enterprise Cloud | GitHub | otterdog |
|---|:-:|:-:|:-:|---|---|
| `public_repos` | yes | yes | yes | every plan has public repositories (EMU organizations have none: unsupported) | |
| `secret_scanning_public` | yes | yes | yes | secret scanning and push protection run for free on public repositories | an error when `secret_scanning` is disabled with push protection enabled (`models/repository.py:467-474`) |
| `private_repo_branch_protection` | no | yes | yes | Free organizations: branch protection on public repositories only | not validated (managed through GraphQL): on Free GitHub refuses it at apply time |
| `private_repo_rulesets` | no | yes | yes | Free: rulesets on private repositories are stored but "won't be enforced" | repository rulesets are always read, 403/404 become `[]` (`rest/repo_client.py:378-386`) |
| `private_repo_environments` | no | yes | yes | Free: environments, environment secrets and deployment branches on public repositories only | no plan validation |
| `org_secrets_private_repos` | no | yes | yes | Free: organization secrets and variables are not accessible from private repositories | `visibility: private` is an error on free for organization secrets (`models/organization_secret.py:45-49`); organization variables have the same check (`models/organization_variable.py:45-49`), but validation never calls it, so a `private` organization variable validates on free (known bug KB-028) |
| `org_rulesets` | no | yes | yes | organization rulesets on Team since 2025-06-16 | |
| `otterdog_org_rulesets` | no | no | yes | | otterdog rejects organization rulesets unless the plan is `enterprise` (`models/github_organization.py:219-224`, issue #776) |
| `push_rulesets` | no | yes | yes | push rulesets: private repositories and their forks on Team | target `push` accepted (`models/ruleset.py:367`), push rules are not modelled |
| `larger_runners` | no | yes | yes | Team and Enterprise Cloud; not included in the Enterprise Cloud trial | not managed by otterdog |
| `private_repo_env_protection_rules` | no | no | yes | required reviewers and wait timers on private repositories: Enterprise | no plan validation |
| `private_pages` | no | no | yes | private Pages publishing: Enterprise Cloud | `members_can_create_private_pages` requires `enterprise` (`models/organization_settings.py:126-129`); `gh_pages_visibility` is unset on other plans (`models/repository.py:293-294`) |
| `ruleset_evaluate` | no | no | yes | the `evaluate` enforcement is Enterprise only | an error unless the plan is `enterprise` (`models/ruleset.py:383-388`) |
| `custom_org_roles` | no | no | yes | custom organization roles: Enterprise Cloud (up to 20) | an error unless `enterprise` (`models/github_organization.py:198-206`); read only when the live plan is `enterprise` (`models/github_organization.py:617`) |
| `internal_repos` | no | no | yes | internal repositories: organizations of an enterprise account | otterdog models `private: bool` only (`models/repository.py:66`) |
| `merge_queue_private` | no | no | yes | merge queue on private repositories: Enterprise Cloud (public repositories: every plan) | |

Notes on the plan checks of otterdog:

- validation uses the plan written in the jsonnet configuration (`settings.plan`, read-only): the harness renders the
  live plan; a scenario overrides it with `variables.plan` to test plan-gated validation, and otterdog then only
  prints `setting 'plan' is read-only, will be skipped` (`operations/plan.py:113-115`);
- exact messages, for `validate.contains`: `use of organization roles requires an 'enterprise' plan, while this
  organization is currently on a '<plan>' plan.`, `use of organization rulesets requires an 'enterprise' plan, ...`,
  `... has 'enforcement' of value 'evaluate' which is only available for an 'enterprise' plan.`, `enabling
  'members_can_create_private_pages' requires an 'enterprise' plan.`, `... has 'visibility' of value 'private', which
  is not available for an organization with free plan.` (organization secrets only: KB-028), and the warning `private
  ... has 'has_wiki' enabled, which requires at least GitHub Team billing, currently using '<plan>' plan.`

## Probed capabilities

| Capability | Probe (admin token, GET) | Granted when |
|---|---|---|
| `custom_properties` | `/orgs/{org}/properties/schema` | 200 (custom properties are documented for every plan; the probe confirms it) |
| `actions_cache_limit` | `/repos/{org}/{fixture}/actions/cache/storage-limit` and `/orgs/{org}/actions/cache/storage-limit` | both answer 200 |
| (recorded only) | `/orgs/{org}/custom-repository-roles` | an Enterprise Cloud sanity check: a warning when it does not answer 200 on an enterprise target |
| (recorded only) | `/organizations/{org}/actions/cache/storage-limit` | the documented org path: 200 there and 404 on otterdog's `/orgs/` path is the KB-006 evidence (`probes['org_cache_storage_limit_documented']`) |

`actions_cache_limit`: GitHub documents the organization endpoint as `/organizations/{org}/actions/cache/storage-limit`,
otterdog calls `/orgs/{org}/...` (`rest/org_client.py:563-590`), so the probe normally answers 404 and the capability
is absent. The renderer then hides `max_cache_size_gb`, so otterdog never manages the setting on such targets (it
would otherwise send the update although its read reported the setting unavailable); GitHub also requires "a payment
method on file" for cache settings. The capability therefore means "otterdog can manage the cache limit here", not
"GitHub offers it": the documented path is only recorded, and scenarios read both paths through the check kinds
`org_cache_storage_limit` and `org_cache_storage_limit_orgs_path`.

## Override-only capability

| Capability | Meaning |
|---|---|
| `ghas_private` | GitHub Code Security / Secret Protection cover private repositories (purchasable on Team and Enterprise Cloud, included in the Enterprise Cloud trial on github.com). Never probed: add it in the target when it applies. |

Typical overrides of an Enterprise Cloud trial: `capabilities: {add: [ghas_private], remove: [larger_runners]}`.

## Environment capabilities

| Capability | Granted when |
|---|---|
| `app` | App credentials are configured and the App is installed on the organization for all repositories, not suspended |
| `docker` | the docker daemon answers |
| `identity_author`, `identity_approver`, `identity_outsider`, `identity_config_reader` | the identity has a token |
| `separate_oracle` | the oracle identity has its own token (not the admin's) |

## Derived capability

| Capability | Granted when |
|---|---|
| `web_ui` | all of: web credentials of the admin bot (`E2E_ADMIN_PASSWORD` and `E2E_ADMIN_TOTP_SEED`, complete and valid), `--e2e-allow-web-ui` (or `E2E_ALLOW_WEB_UI=1` in the process environment; `otterdog-e2e run --allow-web-ui`), a trusted SUT under test (never `pr:` or an untrusted `sha:`, even with `--e2e-trust-code`), `github.saml_sso: false`, and web logins not blocked by the login gate |

`E2EContext.probe` derives it from `web_ui_problems()` and records the decision with its reason in `run.json`
(`web_ui`); `summary.md` shows it in the run table. Every item of `tests/web_ui` carries the `web_ui` marker, which
the plugin re-evaluates before each item: a login failure during the session (the gate blocks) skips the remaining web
tests. `github.capabilities.add: [web_ui]` is refused, `remove: [web_ui]` turns the tier off for a target. Details:
[web-ui-testing.md](web-ui-testing.md).

Webapp items are additionally gated on the transport (`relay` needs docker; `external` needs a URL), on the App and,
for untrusted SUTs, on a `config_reader` identity. Live items are skipped with "github rate budget" when an identity
has less than `E2E_MIN_RATE_REMAINING` (default 800) core requests left.

## Plans of the targets

| Target | `expected_plan` | Notes |
|---|---|---|
| `free` (`targets/free.yaml`) | `free` | positive tests on public repositories, negative tests (`expect_failure_without`) on private ones; if the baseline keeps `members_can_create_private_pages` pending (GitHub `true`, template `false`, `true` is enterprise-only in otterdog), leave it unmanaged with `baseline: settings: {members_can_create_private_pages: null}` (verified offline: the pending change disappears) |
| `team` (create `targets/team.yaml` from `free.yaml`) | `team` | private-repository protections; organization rulesets are still rejected by otterdog (#776) |
| `enterprise` (`targets/enterprise.yaml`) | `enterprise` | everything above; GitHub Enterprise Cloud on github.com only |

GitHub Enterprise Server, ghe.com (data residency) and Enterprise Managed Users are not supported: otterdog
hard-codes `api.github.com` and `https://github.com` (`providers/github/rest/__init__.py:32-34`,
`providers/github/graphql.py:35`, `providers/github/web.py`), and EMU removes public repositories and password logins.

Sources: GitHub documentation (github/docs gated-features reusables, the REST OpenAPI descriptions, the changelog),
cross-checked against otterdog at 9bdeb75; the file references above are otterdog paths.
