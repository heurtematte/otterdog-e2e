# Web-UI tier samples (tests/unit/test_webui_*.py)

Inputs of the unit tests of `otterdog_e2e.webui` (docs/web-ui-testing.md). Nothing here needs GitHub.

## Upstream files (verbatim, EPL-2.0)

| File | Source | Used for |
|---|---|---|
| `github-web-settings.jsonnet` | otterdog main @9bdeb75 `otterdog/resources/github-web-settings.jsonnet` (identical in v1.6.0 and v1.6.1) | the web client definitions (page, input, optional, parent) the mapping table must match |
| `settings.schema.json` | otterdog main @9bdeb75 `otterdog/resources/schemas/settings.json` (identical in v1.6.1) | the 12 keys with `"provider": "web"` |
| `orgs-org-fields.json` | GitHub REST OpenAPI description (`notes/api.github.com.json` of the research notes): the properties of `components.schemas.organization-full` (what `GET /orgs/{org}` returns to an owner) and of the `PATCH /orgs/{org}` request body | the REST oracle fields exist and are read-only |

## Real otterdog output (otterdog 1.7.0.dev19, offline)

Captured like the samples of `tests/unit/data` (see its README): one `ConfigWorkspace` per case (org `e2e-test-org`,
offline template placeholder, `env` credential provider with the dummy token), the template of `tests/unit/data/template`
vendored into `orgs/e2e-test-org/vendor/template/`, every command run with `--local` inside `unshare -rn` (no network),
`COLUMNS=4096 NO_COLOR=1 TERM=dumb`, cwd = workspace root. The configurations are rendered with `OrgConfigRenderer`
(profile `[otterdog-e2e] Dedicated otterdog e2e test organization`, run `t3c7z8a5`) with the baseline repositories but
no teams (team validation calls GitHub even with `--local`):

* `configs/webui-baseline.jsonnet`: the baseline (template defaults for every web setting);
* `configs/webui-toggled.jsonnet`: the baseline plus every writable web setting pinned with `webui.mapping.jsonnet_fields`
  to the value opposite to the template default (`default_branch_name` `e2e-t3c7z8a5`, discussions on with
  `e2e-test-org/otterdog-e2e-fixture-a` as source);
* `configs/webui-imported.jsonnet` (written by hand in the format of `GitHubOrganization.to_jsonnet`, i.e. what
  `otterdog import` writes: the import statement, then a `settings+:` patch against the template defaults).

| Sample | Command | Exit | What it shows |
|---|---|---|---|
| `webui-show-toggled.txt` | `otterdog show -c otterdog.json --local e2e-test-org` (toggled config) | 0 | the `settings {` block format the trusted reader parses (`show-live` prints the same block) |
| `webui-validate-toggled.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` (toggled config) | 0 | the pinned values (`key::: value`) validate, discussions included |
| `webui-local-plan-toggled.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` (BASE baseline, HEAD toggled) | 0 | the 11 web keys planned when toggling (discussion source included), plus the source repository's `has_discussions` |
| `webui-local-plan-restore.txt` | same, BASE toggled, HEAD baseline | 0 | the restore plans 10 keys: the discussion source is ignored while discussions are off |
| `webui-show-imported.txt` | `otterdog show -c otterdog.json --local e2e-test-org` with `configs/webui-imported.jsonnet` | 0 | what the trusted reader's import mode parses: settings the import did not write (e.g. the never-read `two_factor_requirement`) show the template default |

## Synthetic sample

`webui-show-live-synthetic.txt` stands for `otterdog show-live` (no `-n`), which needs github.com: the real
`webui-show-toggled.txt` with the header of `operations/show_live.py` (`Showing live resources:`), the WARNING logger
line `web.py` prints when a setting cannot be read (`failed to retrieve setting 'packages_containers_internal' via web
ui:` + the Playwright error), and without the two settings a live read leaves UNSET: `packages_containers_internal`
(the failed read) and `two_factor_requirement` (never read: its web definition is named `two_factor_required`).
