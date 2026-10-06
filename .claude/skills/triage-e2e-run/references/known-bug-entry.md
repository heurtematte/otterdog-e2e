# Known bug entry, documentation section and upstream issue text

The registry is `scenarios/known_bugs.yaml` (loaded by `src/otterdog_e2e/known_bugs.py`), mirrored by
`docs/known-issues.md`; `tests/unit/test_yaml_cli.py` checks that every entry has its section with its status, a
reproduction when confirmed, and its linked scenarios named.

## Registry entry

Next free id: the highest `KB-nnn` of the file plus one (`grep -o 'id: KB-[0-9]*' scenarios/known_bugs.yaml | tail -1`).
Append the entry at the end of the file:

```yaml
- id: KB-081
  title: <one line: what otterdog does wrong, with the object and the command>
  status: suspected            # suspected: from the source and docs; confirmed: reproduced offline; fixed: with fixed_in
  crash_signature: "<text only this crash prints>"   # only for crashes, e.g. "object has no attribute 'get_model_header'"
  evidence:
    - otterdog/<path>.py:<line>-<line>          # otterdog source at the ref named in the section
    - "e2e: scenarios/offline/<file>.yaml (step <name> declares the bug)"
  upstream: null               # or the eclipse-csi/otterdog issue or PR URL
  fixed_in: null               # PEP 440 version of the first otterdog with the fix (pr-N until released)
  scenarios: []                # scenario ids linked AS A WHOLE only; never a scenario whose step declares the bug
```

Keys: exactly `id`, `title`, `status`, `evidence`, `upstream`, `fixed_in`, `scenarios`, `crash_signature`. Rules:

- `crash_signature`: a substring that appears in the output of this crash and of no other (an exception message, not
  a generic `Traceback`); the offline lint accepts a crash as the expected failure only with it;
- `evidence`: precise `path:line` or `path:line-line` of the otterdog repository; `e2e:` entries for files of this
  repository that reproduce the bug; `openapi:` for GitHub's REST description;
- `scenarios`: the scenario-level links (YAML ids or Python `scenario(...)` ids); both sides agree (the scenario
  declares `known_bug`, the bug lists it). A step-level bug lists nothing here for that scenario;
- `status: confirmed` needs a reproduction section in the documentation.

## Documentation section

Add a row to the "Summary" table and a section under "Issues" of `docs/known-issues.md`, in id order:

```markdown
| KB-081 | <short title> | suspected | <area: model, CLI, provider, webapp, ...> | `O-VAL-EXAMPLE` |
```

````markdown
### KB-081 — <title>

Status: **suspected** · Upstream: none · Scenarios: none

Evidence: `otterdog/<path>.py:<line>-<line>`.

<What otterdog does, what it should do and why (source, documentation, GitHub API), which configurations hit it, which
step of which scenario declares it.>

#### Reproduction

```jsonnet
  _repositories+: [orgs.newRepo('repo') { <field>: <value> }],
```

```console
$ otterdog validate -c otterdog.json --local e2e-test-org         # exit code <n>
<the relevant output lines>
```
````

The "Reproducing offline" section of `docs/known-issues.md` describes the minimal workspace the reproductions use. A
step-level bug's section names the step and its evidence the file (`Scenarios: step of <id>` in the summary row).

## Upstream issue text (report only, never filed by you)

```text
Title: <component>: <what goes wrong>

otterdog version: <version and commit from run.json>
Configuration (minimal):
  <jsonnet>
Command: otterdog <command> ...
Expected: <correct behaviour and the source or docs that say so>
Actual: <exit code and output lines>
Found by the e2e scenario <id> (step <name>) of the otterdog end-to-end test harness.
```
