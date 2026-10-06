# Coverage matrix rules

`scenarios/coverage.yaml` is the machine-readable inventory of otterdog's features; its header comment documents
every field. `tests/unit/test_coverage_matrix.py` validates it and generates `docs/coverage-matrix.md`;
`docs/battery-guide.md` section 7 is the human procedure.

## Feature fields

| Key | Meaning |
|---|---|
| `id` | stable dotted id (`area.name[.detail]`, lower case); rename only with every reference |
| `area` | one of `areas` (`cli`, `config`, `validation`, `plan-semantics`, `org-settings`, ..., `regressions`, `pending`) |
| `title`, `source` | one line; otterdog paths at the matrix's ref with lines (`otterdog/models/ruleset.py:128-136`) |
| `model`, `properties`, `inventory` | the template keys or inventory keys the feature groups (exhaustiveness checks) |
| `operations` | what must be exercised (`add`, `modify`, `remove`, `rename`, `converge`, `validate`, `plan`, `coerce`, `forced-update`, `filter`, `run`, `exit-code`, `error`, `config`, `event`, `comment`, `status`, `permission`, `api`, ...) |
| `min_plan`, `tier`, `ui_only`, `priority` | lowest plan, tier where it is (or must be) tested, web-UI only, `P0`/`P1`/`P2` |
| `status` | `covered`, `partial` or `gap` |
| `covered_by` | scenario ids (`scenarios/{offline,cli,regressions,enterprise}`) or pytest node ids `tests/<tier>/<file>.py::<test>`; never `tests/unit` |
| `known_bugs`, `findings` | `KB-nnn` of `scenarios/known_bugs.yaml`, `F-nn` of `findings` |
| `notes` | verified behaviour and exact messages |
| `gap_outline` | `partial`/`gap` only: `scenario` (suggested id), `file` (below `scenarios/`, `tests/` or `src/`), `steps`, `assertions`, `needs` (non-empty lists of strings) |
| `verified_on` | green live runs of the covering items: `{target, sut, run, date}`; only for features with a live covering item |

## Status rules (checked by the unit test)

- `covered` and `partial` need at least one `covered_by` item; `gap` has none;
- `partial` and `gap` need a `gap_outline`; `covered` has none;
- `covered` needs at least one covering item that runs strictly on the default SUT: an item that is only a known-bug
  XFAIL (a scenario-level bug, a Python `known_bug` test without its own `xfail(raises=...)`) or a scenario skipped
  on `release:latest` by `fixed_in` leaves the feature `partial`;
- every `covered_by` item must exist (scenario ids through the loader, node ids through the test file's AST).

Beyond what the test can check: `covered` means every listed operation is exercised **with an assertion** (a step
that only runs a command, or a record-only step, covers nothing). When one operation is missing, the status is
`partial` and the outline names what is left.

## Gap outline needs

- `available: <API>`: the harness provides it (a fixture, a YAML key, a check kind, a Mutator call): use it;
- `target`, `offline`, `webapp`, `docker`, `app`, `org_level`, `identity <role>`, `enterprise target`, App
  permissions and events: requirements of the tier or the target (live: the user runs it);
- anything else (`harness: ...`, `runner: ...`, `TemplatePublisher ...`): a missing harness capability. Report it;
  do not work around it in a test.

## Editing and regenerating

```bash
.venv/bin/python tests/unit/test_coverage_matrix.py --write    # rewrites docs/coverage-matrix.md, prints the shares
.venv/bin/python tests/unit/test_coverage_matrix.py            # coverage per area, nothing written
env -u OTTERDOG_CONFIG_ROOT .venv/bin/python -m pytest -q -p no:cacheprovider tests/unit/test_coverage_matrix.py
```

The matrix renders a covered or partial feature without `verified_on` as **unverified** unless an offline item
covers it; `verified_on` entries come from a green live run's `run.json` (`run` is the run id), reported by the user.
Keep the README's coverage numbers as they are unless the user asks you to update them.
