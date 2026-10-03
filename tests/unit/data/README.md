# Golden samples of otterdog output (WP-D)

REAL output of otterdog **1.7.0.dev19** (the offline CLI of the research notes,
`notes/deploy-runtime/venv-local/bin/otterdog`), captured OFFLINE: every command ran inside
`unshare -rn` (new user + network namespace, no network at all) with the dummy token of the offline tier.
They are the ground truth of `otterdog_e2e/otterdog/output.py` and its tests (`tests/unit/test_otterdog_output.py`).

## How they were captured

* One workspace per case, written with `ConfigWorkspace` (`otterdog_e2e/otterdog/workspace.py`): `otterdog.json` with
  `defaults.base_url = https://otterdog.invalid`, `defaults.jsonnet.base_template =
  https://github.com/e2e-offline/template#otterdog-defaults.libsonnet@offline` (`sut.template.offline_template()`),
  `config_dir = orgs`, `github.config_repo = .otterdog`, and one organization `e2e-test-org` with the `env` credential
  provider (`E2E_OTTERDOG_API_TOKEN`, `E2E_OTTERDOG_USERNAME`, `E2E_OTTERDOG_PASSWORD`, `E2E_OTTERDOG_TOTP_SEED`).
* The upstream example template (`examples/template/*.libsonnet` of otterdog main @9bdeb75) is vendored into
  `orgs/e2e-test-org/vendor/template/`, so every command runs with `--local` (no template clone).
* Org configs (and `-BASE` files for local-plan/local-apply) are rendered with `OrgConfigRenderer`
  (`otterdog_e2e/otterdog/render.py`, two layers, live-like profile `[otterdog-e2e] Dedicated otterdog e2e test
  organization`, run id `t3c7z8a5`); the exact files are in `configs/` (`<case>.jsonnet`, `<case>.jsonnet-BASE`).
* Environment: `procs.sanitized_env` (`COLUMNS=4096 LINES=1000 NO_COLOR=1 TERM=dumb PYTHON_DOTENV_DISABLED=1`, scratch
  HOME, no `OTTERDOG_*`/`E2E_*` from the caller) plus `credentials_env(None)`
  (`E2E_OTTERDOG_API_TOKEN=offline-dummy-token`, the other three `unset`).
* Each command ran with the workspace root as cwd and `-c otterdog.json` (relative, so printed paths are
  `./orgs/...`):

  ```
  cd <workspace> && env -u OTTERDOG_CONFIG_ROOT COLUMNS=4096 NO_COLOR=1 TERM=dumb \
      E2E_OTTERDOG_API_TOKEN=offline-dummy-token E2E_OTTERDOG_USERNAME=unset E2E_OTTERDOG_PASSWORD=unset \
      E2E_OTTERDOG_TOTP_SEED=unset unshare -rn <otterdog> <command line of the table>
  ```
* stdout is stored verbatim (stderr was empty for every sample). The only edit: the absolute capture directory in
  the jsonnet error of `validate-syntax.txt` was replaced by `/tmp/otterdog-e2e-capture/validate-syntax`.

## Synthetic samples

apply cannot complete offline, and check-status needs the live org. Synthetic samples are flagged in `samples.json`:

* `apply-executed*.txt`, `apply-failed-patch.txt`: the REAL `local-apply ... e2e-test-org` output of case
  `local-apply-offline` up to its plan blocks, followed by the tail printed by otterdog's own code (otterdog 1.7.0.dev19
  `IndentingPrinter(CONSOLE_STDOUT)`, rich `Progress`, `print_error`) replaying `operations/apply.py` `handle_finish`
  after approval: `Applying changes:`, the progress bar, optional failed-patch box (`failed to apply patch: ADD -
  repository[...]` + a `GitHubException` text), `Done.` and `Executed plan: 8 added, 0 changed, 1 deleted.`
  (`... 1 live resources ignored.` without `-d`).
* `check-status*.txt` / `check-status*.json`: `operations/check_status.py` `handle_finish` lines and the `-j` JSON
  list (`json.dumps(..., indent=2)`), printed with the same printer.

## Vendored template

`template/` is a verbatim copy of `examples/template/*.libsonnet` of otterdog main @9bdeb75 (EPL-2.0), the template
the samples were rendered against; the renderer tests evaluate rendered configs against it with the local `jsonnet`
binary (skipped when it is not installed).

## Index

`samples.json` maps every sample to its command line, exit code, case, config files and description.

| sample | command (cwd = workspace root) | exit | kind | configs | what it shows |
|---|---|---|---|---|---|
| `apply-executed.txt` | `otterdog local-apply -f -n -d e2e-test-org` | 0 | synthetic | `configs/local-apply-offline.jsonnet`, `configs/local-apply-offline.jsonnet-BASE` | Executed plan with -d: real local-apply prefix + otterdog's own printer tail |
| `apply-executed-ignored.txt` | `otterdog local-apply -f -n e2e-test-org` | 0 | synthetic | `configs/local-apply-offline.jsonnet`, `configs/local-apply-offline.jsonnet-BASE` | Executed plan without -d: real local-apply prefix + otterdog's own printer tail |
| `apply-failed-patch.txt` | `otterdog local-apply -f -n -d e2e-test-org` | 1 | synthetic | `configs/local-apply-offline.jsonnet`, `configs/local-apply-offline.jsonnet-BASE` | one failed patch: real local-apply prefix + otterdog's own printer tail |
| `apply-network.txt` | `otterdog apply -c otterdog.json --local -f -n e2e-test-org` | 2 | real | `configs/plan-offline.jsonnet` | apply -f -n offline: network error (exit 2) |
| `apply-validation-error.txt` | `otterdog apply -c otterdog.json --local -f -n e2e-test-org` | 0 | real | `configs/plan-validation-error.jsonnet` | apply -f -n with a validation error: exit 0 (known bug) |
| `canonical-diff.txt` | `otterdog canonical-diff -c otterdog.json --local e2e-test-org` | 0 | real | `configs/show.jsonnet` | canonical-diff --local (labels inverted) |
| `check-status.txt` | `otterdog check-status -c otterdog.json -n -j check-status.json e2e-test-org` | 0 | synthetic | - | check_status.py handle_finish/post_execute output (live only) |
| `check-status-network.txt` | `otterdog check-status -c otterdog.json --local -n -j status.json e2e-test-org` | 2 | real | `configs/check-status-offline.jsonnet` | check-status -n -j offline: network error, no JSON |
| `check-status-out-of-sync.txt` | `otterdog check-status -c otterdog.json -n -j check-status-out-of-sync.json e2e-test-org` | 0 | synthetic | - | check_status.py handle_finish/post_execute output (live only) |
| `list-projects.txt` | `otterdog list-projects -c otterdog.json` | 0 | real | `configs/list-projects.jsonnet` | list-projects (rich table, no org positional) |
| `local-apply-network.txt` | `otterdog local-apply -c otterdog.json --local -f -n -d e2e-test-org` | 2 | real | `configs/local-apply-offline.jsonnet`, `configs/local-apply-offline.jsonnet-BASE` | local-apply -f -n -d offline: plan blocks, progress bar, network error |
| `local-apply-no-changes.txt` | `otterdog local-apply -c otterdog.json --local -f -n e2e-test-org` | 0 | real | `configs/local-apply-nochange.jsonnet`, `configs/local-apply-nochange.jsonnet-BASE` | No changes required + would be deleted without -d |
| `local-plan-add.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-add.jsonnet`, `configs/local-plan-add.jsonnet-BASE` | adds: repo with secret/variable/webhook/BPR/environment, org secret/variable/webhook, custom property |
| `local-plan-add-cache-hidden.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-add-cache-hidden.jsonnet`, `configs/local-plan-add-cache-hidden.jsonnet-BASE` | repo add with hidden max_cache_size_gb |
| `local-plan-cache-limit-hidden.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-cache-limit.jsonnet`, `configs/local-plan-cache-limit.jsonnet-BASE` | hide_cache_limit vs visible max_cache_size_gb: no diff (UNSET) |
| `local-plan-change.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-change.jsonnet`, `configs/local-plan-change.jsonnet-BASE` | changes incl. nested objects and an org setting (coerced repo keys) |
| `local-plan-description-removed.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-profile-wipe.jsonnet`, `configs/local-plan-profile-wipe.jsonnet-BASE` | org description removed (what the baseline guard refuses) |
| `local-plan-env-nested-add.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-env-nested.jsonnet`, `configs/local-plan-env-nested.jsonnet-BASE` | env secret/variable (parent environment=) and repo ruleset adds |
| `local-plan-env-nested-remove.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-env-nested-remove.jsonnet`, `configs/local-plan-env-nested-remove.jsonnet-BASE` | the same objects removed |
| `local-plan-forced.txt` | `otterdog local-plan -c otterdog.json --local --update-secrets --update-webhooks e2e-test-org` | 0 | real | `configs/local-plan-forced.jsonnet`, `configs/local-plan-forced.jsonnet-BASE` | --update-secrets --update-webhooks: forced (!) updates |
| `local-plan-missing-base.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 1 | real | `configs/local-plan-missing-base.jsonnet` | -BASE missing: failed to load current configuration |
| `local-plan-noop.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-noop.jsonnet`, `configs/local-plan-noop.jsonnet-BASE` | identical configs |
| `local-plan-readonly.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-readonly.jsonnet`, `configs/local-plan-readonly.jsonnet-BASE` | plan free -> team: Note read-only, 0 to change |
| `local-plan-remove.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-remove.jsonnet`, `configs/local-plan-remove.jsonnet-BASE` | removals: org-level objects, nested objects of a kept repo, a whole repo |
| `local-plan-remove-enterprise.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-enterprise-remove.jsonnet`, `configs/local-plan-enterprise-remove.jsonnet-BASE` | org role and org ruleset removals (plan enterprise) |
| `local-plan-remove-filtered.txt` | `otterdog local-plan -c otterdog.json --local -r e2e-t3c7z8a5-gone e2e-test-org` | 0 | real | `configs/local-plan-remove.jsonnet`, `configs/local-plan-remove.jsonnet-BASE` | same with -r <repo>: org-level removals are NOT filtered (OC-02) |
| `local-plan-remove-repo.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-remove-nested-repo.jsonnet`, `configs/local-plan-remove-nested-repo.jsonnet-BASE` | removing a repo with nested objects: ONE header, counted once |
| `local-plan-remove-teams.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-remove-teams.jsonnet`, `configs/local-plan-remove-teams.jsonnet-BASE` | team removals (run team and a baseline-like team) |
| `local-plan-unknown-property.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/validate-unknown-property.jsonnet`, `configs/validate-unknown-property.jsonnet-BASE` | unknown settings key in a local-plan |
| `local-plan-validation-error.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 1 | real | `configs/local-plan-validation-error.jsonnet`, `configs/local-plan-validation-error.jsonnet-BASE` | validation error: 'Planning aborted', no Plan: line |
| `local-plan-webhook-secret-removed.txt` | `otterdog local-plan -c otterdog.json --local e2e-test-org` | 0 | real | `configs/local-plan-webhook-secret-removed.jsonnet`, `configs/local-plan-webhook-secret-removed.jsonnet-BASE` | plain 'Warning: removing secret for webhook' line |
| `plan-network.txt` | `otterdog plan -c otterdog.json --local -n e2e-test-org` | 2 | real | `configs/plan-offline.jsonnet` | plan -n offline: network error (exit 2) |
| `plan-validation-error.txt` | `otterdog plan -c otterdog.json --local -n e2e-test-org` | 1 | real | `configs/plan-validation-error.jsonnet` | plan -n with a validation error (exit 1) |
| `push-config-network.txt` | `otterdog push-config -c otterdog.json --local -f -m e2e push e2e-test-org` | 2 | real | `configs/push-config-offline.jsonnet` | push-config -f offline: network error |
| `show.txt` | `otterdog show -c otterdog.json --local e2e-test-org` | 0 | real | `configs/show.jsonnet` | show --local |
| `show-default.txt` | `otterdog show-default -c otterdog.json --local e2e-test-org` | 0 | real | `configs/show.jsonnet` | show-default --local |
| `validate-790.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 1 | real | `configs/validate-790.jsonnet` | repo ruleset required_status_checks without strict (#790) |
| `validate-errors.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 3 | real | `configs/validate-errors.jsonnet` | 3 errors: private org secret on free, org ruleset on free, ruleset status checks without strict |
| `validate-infos-hidden.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 0 | real | `configs/validate-infos.jsonnet` | dummy secrets: infos hidden without -v |
| `validate-infos-verbose.txt` | `otterdog validate -c otterdog.json --local -v e2e-test-org` | 0 | real | `configs/validate-infos.jsonnet` | same config with -v: Info boxes |
| `validate-missing-config.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 1 | real | - | org config file missing |
| `validate-network.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 2 | real | `configs/validate-teams-offline.jsonnet` | teams make validate call GitHub: network error offline (exit 2) |
| `validate-ok.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 0 | real | `configs/validate-ok.jsonnet` | valid config, no notices |
| `validate-plan-gate.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 1 | real | `configs/validate-plan-gate.jsonnet` | org ruleset with plan free |
| `validate-schema.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 2 | real | `configs/validate-schema.jsonnet` | JSON-schema type error (uncaught, exit 2) |
| `validate-syntax.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 1 | real | `configs/validate-syntax.jsonnet` | jsonnet syntax error (load error, exit 1) |
| `validate-unknown-property.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 0 | real | `configs/validate-unknown-property.jsonnet`, `configs/validate-unknown-property.jsonnet-BASE` | unknown settings key: logger WARNING with file.py:LINE |
| `validate-warnings.txt` | `otterdog validate -c otterdog.json --local e2e-test-org` | 0 | real | `configs/validate-warnings.jsonnet` | warnings only (plain secret value, private repo wiki on free) |
| `version.txt` | `otterdog --version` | 0 | real | - | --version |
