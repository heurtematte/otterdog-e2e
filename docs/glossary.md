# Glossary

The words of the harness and of this documentation. On the documentation site, the abbreviations of the
[last table](#abbreviations) show their meaning wherever the pointer rests on them.

## Systems under test

- **SUT** (system under test): the otterdog version a run tests, with its CLI, its webapp image and its standard
  template. A run names it with `--sut` (`SUT=` for `make`), `release:latest` by default.
- **SUT spec**: the text that names a SUT: `release:latest`, `tag:v1.7.1`, `branch:main`, `sha:<hex>`,
  `pr:<N>@<40-hex>`, `path:<dir>`, `dirty:<dir>` (the [README](../README.md#systems-under-test-sut-specs) lists
  them); `otterdog-e2e sut resolve SPEC` resolves one to a commit.
- **trusted and untrusted SUTs**: a release, a tag, upstream `main`, a commit reachable from them and a local checkout
  are trusted, their CLI may run in a virtualenv on the host. A pull request, or another commit, is untrusted: it only
  runs in its own docker image, without network for offline commands, and never receives web-UI credentials
  ([architecture](architecture.md#systems-under-test-and-trust), [security](security.md#untrusted-suts-t1-t3)).
- **head and base SUT**: a differential run compares two SUTs, the head (`--sut`) and the base (`--base-sut`; `auto`
  is the merge base of the head with upstream `main`).
- **reset SUT**: the trusted SUT that resets the test organization to its baseline (`--e2e-reset-sut`,
  `release:latest` by default), never the SUT under test.
- **pin**: the full 40-hex commit a pull request SUT is built from (`pr:900@<sha>`): a later push changes nothing in
  the run.

## Runs and tiers

- **tier**: a family of tests grouped by what they need: `unit` (nothing), `offline` (the SUT only), `cli`,
  `webhooks`, `webapp`, `enterprise` and `web_ui` (a target organization), `differential` (two SUTs)
  ([architecture](architecture.md#tiers-and-lanes)).
- **offline and live**: offline tests need no GitHub organization (`validate`, `local-plan`, `show`, the webapp with
  dummy credentials); live tests apply configurations to a test organization and check the result on GitHub.
- **lane**: the selection of a CI job: `pr-fast` (at most 45 minutes) and `nightly-full` (everything).
- **priority**: `P0` runs in the `pr-fast` lane, `P1` in `nightly-full`, `P2` when time allows.
- **run**: one `otterdog-e2e run` (or `pr`) session, named by its run id; its reports are in `artifacts/<run id>/`
  (`summary.md`, `run.json`, `differential.md`).

## Targets

- **target**: the dedicated GitHub test organization the live tiers write to, never a real one.
- **instance**: a configured target, `~/.config/otterdog-e2e/<instance>.env` (the organization and its tokens),
  written by `otterdog-e2e setup`; `--target <instance>` (`TARGET=` for `make`) selects it ([onboarding](onboarding.md)).
- **profile**: what a target is expected to be (`targets/<profile>.yaml`: its plan and features), shared by instances.
- **role**: an account of a target and its token: `admin`, `oracle`, `author`, `approver`, `outsider`,
  `config_reader` ([roles](roles.md)).
- **capability**: what a target can do (its plan, its features, its roles), probed once per session; the tests that
  need a missing capability are skipped with the reason ([capability matrix](capability-matrix.md)).
- **baseline**: the known state of a test organization that a live session starts from and resets to.

## Scenarios and tests

- **scenario**: a YAML test of `scenarios/<tier>/<domain>/`, with an id, steps and expectations
  ([writing scenarios](writing-scenarios.md)).
- **step**: one case of a scenario: the jsonnet fragments it adds to the configuration, the commands it runs and what
  it expects of their outputs; offline steps are independent, live steps are chained.
- **fragment**: a piece of jsonnet that a step adds to the configuration of the organization (repositories, rulesets,
  teams, settings).
- **tag**: a label that selects scenarios and Python tests (`--tags`); the scenario explorer has a page per tag.
- **known bug**: an otterdog bug of `scenarios/known_bugs.yaml` (`KB-<n>`), described in
  [known issues](known-issues.md); the tests it breaks are expected failures (xfail) until the version that fixes it.
- **fixed_in**: the first otterdog version a scenario asserts; older SUTs skip it.

## Differential testing

- **observation**: an output recorded on both sides of a differential run, keyed by scenario, step, kind and key
  (for example the `validate` output of a step).
- **delta**: an observation that differs between the base and the head SUT once normalized.
- **change**: what a differential run tests, an upstream pull request (`pr: 900`) or a named change (`--change`).
- **reference**: an entry of a scenario's `references` naming a change that alters its behaviour, with the deltas it
  expects; the other deltas are reported as unexpected ([testing an otterdog PR](testing-an-otterdog-pr.md)).

## Abbreviations

| Abbreviation | Meaning |
|---|---|
| SUT | System under test: the otterdog version a run tests (--sut) |
| SUTs | Systems under test: the otterdog versions a run tests (--sut, --base-sut) |
| KB | Known bug of otterdog (scenarios/known_bugs.yaml) |
| PAT | Personal access token of a GitHub account |
| TOTP | Time-based one-time password: the code of two-factor authentication |
