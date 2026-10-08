# Conventions and the unit tests that enforce them

Source: `docs/battery-guide.md` section 2. The unit tests named here run in `make unit`; run them alone with
`env -u OTTERDOG_CONFIG_ROOT .venv/bin/python -m pytest -q -p no:cacheprovider <file>`.

## Ids and files

| Kind | Id | File |
|---|---|---|
| offline YAML scenario | `O-<AREA>-<NAME>` (`O-VAL-ORGVAR`, `O-LPLAN-RENAME`) | `scenarios/offline/<domain>/<command>-<name>.yaml` (`variables/val-org-variables.yaml`) |
| live CLI scenario | `cli.<area>.<name>` | `scenarios/cli/<domain>/<name>.yaml` |
| known-bug reproduction (live) | `cli.kb.<name>` | `scenarios/cli/<domain>/kb-<name>.yaml` |
| negative test of a missing capability | `cli.neg.<name>` | `scenarios/cli/<domain>/neg-<name>.yaml` |
| regression of an otterdog PR or issue | `regression.<behaviour>` + tag `regression` + `references: [{pr: <n>}]` | `scenarios/cli/<domain>/<behaviour>.yaml` |
| enterprise-only scenario | `enterprise.<name>` | `scenarios/enterprise/<domain>/<name>.yaml` |
| offline Python test | marker `scenario("O-<NAME>")` | `tests/offline/test_<topic>.py` |
| live CLI Python test | marker `scenario("cli.<name>")` | `tests/cli/test_<topic>.py` |
| webapp, webhooks Python test | `scenario("W-<NAME>", priority="P1")`, `scenario("H-<NAME>", priority=...)` | `tests/webapp/`, `tests/webhooks/` |
| web-UI Python test | `scenario("webui.<area>.<name>")` | `tests/web_ui/test_web_<topic>.py` |

`<domain>` is the directory of the feature the scenario pins, the same names in every tier: a model area (`repo`,
`workflows`, `org-settings`, `org-roles`, `teams`, `custom-properties`, `secrets`, `variables`, `webhooks`, `bpr`,
`rulesets`, `environments`; the scenario carries that tag) or the cross-cutting `template` (the configuration as
written), `cli` (command output and flags across areas) and `plan` (diff semantics across object types). No deeper
subdirectory; jsonnet files of one domain go into its `files/`. Regressions and known-bug reproductions sit in the
domain of their feature (`model.domain_problem`, enforced by `tests/unit/test_yaml_cli.py`,
`tests/unit/test_yaml_offline.py` and `assist check`).

Use the id and file of a coverage gap outline when there is one. Ids are unique across every directory. The priority
is the coverage feature's (P0 items count for the lane budgets). Ids, file names and directories name the BEHAVIOUR,
never a PR or issue number (`assist check` and the unit tests refuse a referenced PR number or a 3+ digit run).

## References

The otterdog PRs (`pr: <n>`) or named changes without PR (`change: <slug>`) behind a behaviour go into the scenario's
`references` (YAML) or the `references=[...]` keyword of its `pytest.mark.scenario` marker (Python, a literal). Add a
reference when a PR fixes, implements or changes the behaviour the scenario pins (a regression always references its
fix); append to the list when the behaviour changes again. Each entry: exactly one of `pr`/`change`, optional `note`,
`expected_deltas` (`{step?, kind?, key?, note?}`: what the change makes differ between base and head in this
scenario; Python tests name no step), `base` (release, tag, branch or sha spec) and `template` (own, head, base),
declared once per change. Format and use: the `otterdog-pr-tests` skill (`references/references.md`).

## Tags

Vocabulary `otterdog_e2e.selection.SCENARIO_TAGS`: model areas `repo`, `bpr`, `rulesets`, `environments`, `secrets`,
`variables`, `webhooks`, `teams`, `custom-properties`, `org-settings`, `workflows`, `org-roles`, and `template`, `cli`,
`webapp`, `webhooks-app`, `offline`, `smoke`. The PR lane selects scenarios by the files a PR changes through these
tags (`PATH_RULES` of `src/otterdog_e2e/selection.py`).

- offline YAML: `offline` first, then vocabulary tags only;
- live YAML: at least one model-area tag; regressions add `regression` (their PR goes into `references`, no `pr-<n>`
  tag); scenario-level known bugs add
  `known-bug`;
- webapp and webhooks Python tests: `tags(...)` from the vocabulary only.

## What the unit tests check

| Test file | Rules |
|---|---|
| `tests/unit/test_yaml_offline.py` | every offline file loads; title; description of 20 words or more; `offline` first tag; vocabulary tags; `observe: true`; every named object uses the run prefix; every reference of the repository loads and the references of one change agree on `base` and `template`; no scenario id or file name carries a PR number |
| `tests/unit/test_yaml_cli.py` | live ids follow the directory (`cli.`, `regression.`, `enterprise.`); unique ids; a model-area tag; known-bug scenarios tagged `known-bug` and never P0; run-prefixed objects, no `extendRepo`; webhook URLs under `{{ hook_base }}`; regressions reference their PR(s) (`references`, no `pr-<n>` tag, no number in the id or file name) and link `otterdog/pull/<n>` (or issues) with a "Known-bad" version; enterprise scenarios `min_plan: enterprise`; probes; `UNRELEASED_FIXES`; private repositories not created by their first apply; `docs/known-issues.md` mirrors `scenarios/known_bugs.yaml` |
| `tests/unit/test_known_bugs.py` | registry format, scenario and step links (a step-level bug never lists its scenario) |
| `tests/unit/test_coverage_matrix.py` | `scenarios/coverage.yaml` schema, `covered_by` items exist, status rules, `docs/coverage-matrix.md` up to date |
| `tests/unit/test_suite_webapp_static.py` | webapp and webhooks tests: one `scenario(id, priority=...)` marker, tags, markers matching fixtures, no `time.sleep` |

## Registries a new test touches

| Test | Also update |
|---|---|
| any test closing a coverage gap | `scenarios/coverage.yaml`, then `.venv/bin/python tests/unit/test_coverage_matrix.py --write` |
| a new defect | `scenarios/known_bugs.yaml` and a `### KB-nnn` section plus a summary row in `docs/known-issues.md` |
| a live regression with `fixed_in` | `UNRELEASED_FIXES` of `tests/unit/test_yaml_cli.py` |
| an offline step whose outcome depends on the SUT history | `SUT_EXPECTATIONS` of `tests/offline/test_scenarios.py` |
| a live scenario with a probe | `PROBES` of `tests/cli/conftest.py` and the scenario's own `timeout` |
| an otterdog PR with expected deltas | a `references` entry `{pr: <n>, expected_deltas}` in the scenario of the behaviour |

## Python tests

Same fixtures and markers as the YAML engine (`docs/writing-scenarios.md` "Python tests", `docs/battery-guide.md`
sections 3.3 to 3.12): offline `offline_cli` and `vendored_cli` (`OtterdogCli`: `validate`, `local_plan`, `show`,
`run`, `invoke`, `CliResult.assert_ok()`), live `otterdog`, `oracle`, `mutator`, `run_ctx`, webapp
`webapp_scenario`. Module docstring, one `scenario(...)` marker per test, a docstring per test, names from `run_ctx`.
A battery test is never a unit test: `covered_by` may not name `tests/unit`.
