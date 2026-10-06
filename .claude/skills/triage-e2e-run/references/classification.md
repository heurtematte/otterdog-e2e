# Classification rules and where the evidence is

## The run directory

`<E2E_ARTIFACTS>/<run_id>/` (default `artifacts/<run_id>/`; README "Run artifacts" lists every file):

| Path | Use |
|---|---|
| `run.json` | target, org, plan, SUT, base and reset SUT with versions and commits, capabilities, lane, the command |
| `results.jsonl` | one line per test phase: `nodeid`, `outcome`, `when`, `failure`, `reason`, `infra` (true for infrastructure problems), `known_bug`, `scenario`, `tier`, `tags`, `phases`, `rate` |
| `summary.md` | outcomes, failures with their short text, skips by reason, known bugs, coverage shares (`.venv/bin/otterdog-e2e report <dir>` prints it) |
| `cli/<nnnn>-<command>/` | every otterdog command of the live session: `cmd.txt` (logical and process argv), `stdout.txt`, `stderr.txt`, `exit_code.txt` |
| `offline/<nnn>-<test>/cli/`, `offline/<nnn>-<test>/workspace/` | per offline item: its commands and the rendered configuration (`<org>.jsonnet.txt`, `-BASE`) |
| `reset/cli/`, `base/.../cli/`, `head/.../cli/` | the reset SUT's commands; the differential sides |
| `webapp/compose.log`, `deliveries.jsonl` | webapp logs, relayed App deliveries (no payloads) |
| `differential.md`, `differential.json`, `observations/` | the differential comparison |
| `leaks.json` | the scrub result |

The triage bundle (`artifacts/assist/triage-<run_id>/`) already lists, per failure, the commands it ran and the
relevant paths: open those first.

## Outcomes

- **FAILED / ERROR**: what you triage (ERROR is a fixture setup or teardown failure: often harness or infrastructure).
- **XFAIL**: a known bug reproduced where expected: nothing to do.
- **XPASS**: a known bug did not show: the bug may be fixed in this SUT. Propose `status: fixed` with `fixed_in` (the
  first version with the fix) after checking the otterdog history; a `KnownBugNotReproducedWarning` says the same for
  a step-level bug.
- **SKIPPED**: never a failure; the reason says which capability, plan, identity, target or `fixed_in` gate applied.

## Pre-classes

| Class | Typical evidence | Confirm by | Action |
|---|---|---|---|
| `known-bug` | the item or step declares `KB-nnn` (or the bug lists the scenario); the output carries the bug's `crash_signature` | reading the bug's section in `docs/known-issues.md` and comparing the failing phase | none for an XFAIL; for a FAIL: why the bug did not cover it (strict step, `phases`, crash without signature, `status: fixed` = regression) |
| `infrastructure` | `infra: true`, `[infra]` prefix; HTTP 500/502/503/504 from GitHub, "secondary rate limit", "abuse detection", connection resets and DNS errors, "timed out waiting for delivery", docker or compose errors, "lease" held by another run | the same item green in the baseline or a rerun; the error comes from GitHub or the host, not from otterdog's logic | rerun (the user runs live ones); nothing to change in the test |
| `harness` | a traceback ending in `src/otterdog_e2e/...`; `ContextError`, `SafetyError`, `TargetError`, render errors, fixture setup or teardown errors | the failing line is harness code, and the SUT output (if any) is fine | a scenario fix when a guard refused a wrong scenario; else a harness fix with a unit test |
| `sut` | an expectation of a step failed: `validate`/`plan`/`apply` mismatch, a `contains` not found, a state check failing on GitHub's answer | the command output contradicts the expectation; decide whether the expectation or otterdog is wrong | scenario fix, or a new known bug |
| `unknown` | none of the above | more evidence: the full command output, the rendered configuration, `run.json`, another SUT | say what is missing |

Hints that change a verdict:

- a failure only on one plan or one target: a capability or plan gate is missing in the scenario (`requires`,
  `min_plan`, `expect_failure_without`), not an otterdog defect;
- a message differing in wording only between SUT versions: the scenario asserts too much text (or needs `fixed_in`
  or `SUT_EXPECTATIONS`);
- converge failures (plans that never become a no-op) are a classic otterdog defect class (KB-020, KB-021, KB-052):
  check the plan output after the apply;
- the oracle reading 403/404 means an unavailable listing, not an absent object (`unavailable_ok`);
- a crash (`Traceback`, `AttributeError`, exit 2) of otterdog is a defect even when the configuration is invalid:
  otterdog should report a validation error.

## Reproducing

| Failure | Offline reproduction |
|---|---|
| offline item | `.venv/bin/otterdog-e2e run --suite offline --sut <sut> --scenario <id>` |
| a live step that should validate or fail validation | `make lint-scenarios SUT=<sut>` (or `assist check <file> --sut <sut>`) |
| a validation or plan behaviour of a live step | copy the step's rendered fragments into an offline scenario step, or `otterdog-e2e inject --sut <sut> --fragment <kind>=<file>` |
| live-only (apply, read-back, webapp, deliveries) | no offline reproduction: propose `make one SCENARIO=<id> TARGET=<instance> SUT=<sut>` to the user |

Compare SUTs (`release:latest`, `branch:main`, `tag:v1.6.0`) to date a regression; the run's own SUT is in
`run.json`.
