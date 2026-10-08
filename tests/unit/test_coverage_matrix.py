"""Coverage matrix of otterdog's features against the e2e battery (scenarios/coverage.yaml, docs/coverage-matrix.md).

scenarios/coverage.yaml is the machine-readable inventory of what otterdog (main @9bdeb75) can do: CLI commands and
flags, every property of the configuration model grouped into features, validation rules, diff semantics, the webapp
(webhook events, comment commands, tasks, auto-merge, apply, blueprints, policies, /api and /internal) and notable
CHANGELOG fixes. Each feature says which existing scenario ids (scenarios/{offline,cli,enterprise}) or
pytest node ids (tests/<tier>/...::test_x) cover it, and gaps carry an outline precise enough to write the missing test.

These tests keep the file honest (the checks live in otterdog_e2e.coverage_matrix, shared with ``otterdog-e2e assist
check scenarios/coverage.yaml``):

* strict schema (keys, types, enums, unique dotted ids, status rules: covered/partial need covering items,
  partial/gap need a gap outline, gap has none);
* every covered_by item exists (scenario ids through the scenarios loader, node ids through the test file's AST) and
  is not a harness unit test;
* exhaustiveness: every property of every constructor of otterdog's example template (the vendored copy in
  tests/unit/data/template, identical to examples/template at 9bdeb75) belongs to a feature, and the inventory keys
  (CLI commands, webhook events, comment commands, tasks, endpoints, pages, blueprint and policy types, comment
  markers, statuses, receiver checks) match EXPECTED_INVENTORY;
* docs/coverage-matrix.md is exactly what render_markdown() produces.

After editing the YAML, regenerate the documentation:

    .venv/bin/python tests/unit/test_coverage_matrix.py --write

Coverage per area (also printed by ``pytest tests/unit/test_coverage_matrix.py -s -k summary``):

    .venv/bin/python tests/unit/test_coverage_matrix.py
"""

from __future__ import annotations

import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from otterdog_e2e.coverage_matrix import (
    REGENERATE,
    MatrixProject,
    counts,
    live_verified,
    md_cell,
    md_text,
    template_keys,
)

ROOT = Path(__file__).resolve().parents[2]
PROJECT = MatrixProject(ROOT)
MATRIX = PROJECT.matrix_path
DOC = PROJECT.doc_path
TEMPLATE = PROJECT.template_path


def matrix() -> dict[str, Any]:
    """scenarios/coverage.yaml (strict: duplicate keys refused; read once)."""
    return PROJECT.data


def features() -> list[dict[str, Any]]:
    """The feature entries."""
    return PROJECT.features()


# --- tests -------------------------------------------------------------------------------------------------------------
def test_matrix_schema() -> None:
    """Keys, types, enums, unique ids and the status rules hold for every entry."""
    problems = PROJECT.schema_problems(matrix())
    assert not problems, "scenarios/coverage.yaml:\n" + "\n".join(problems)


def test_covered_by_items_exist() -> None:
    """Every covered_by item is a scenario id of the loader or an existing e2e test function."""
    problems = PROJECT.reference_problems(features())
    assert not problems, "\n".join(problems)


def test_known_bug_references_exist() -> None:
    """known_bugs entries of the features exist in scenarios/known_bugs.yaml."""
    problems = PROJECT.known_bug_problems()
    assert not problems, "\n".join(problems)


def test_findings_are_referenced() -> None:
    """Every new finding is referenced by at least one feature (and only defined findings are referenced)."""
    problems = PROJECT.finding_problems()
    assert not problems, "\n".join(problems)


def test_every_template_property_is_inventoried() -> None:
    """Each key of each constructor of otterdog's example template belongs to a feature of its model, and features only
    list template keys (or the model's declared extra, model-only fields)."""
    problems = PROJECT.template_problems()
    assert not problems, "\n".join(problems)


def test_inventory_is_exhaustive() -> None:
    """The inventory keys of the features are exactly EXPECTED_INVENTORY (otterdog main @9bdeb75)."""
    problems = PROJECT.inventory_problems()
    assert not problems, "\n".join(problems)


def test_coverage_summary() -> None:
    """Print the coverage per area (captured: ``-s`` shows it) and check the counts add up."""
    data = matrix()
    sys.stdout.write("\n" + PROJECT.summary_text(data))
    assert sum(counts(list(data["features"])).values()) == len(data["features"])


def test_markdown_is_up_to_date() -> None:
    """docs/coverage-matrix.md is the rendering of the matrix (regenerate it after editing the YAML)."""
    expected = PROJECT.render_markdown(matrix())
    current = DOC.read_text(encoding="utf-8") if DOC.is_file() else ""
    assert current == expected, f"{DOC.relative_to(ROOT)} is stale, regenerate it: {REGENERATE}"
    assert PROJECT.markdown_problems() == []


def test_covered_needs_an_item_that_runs_strictly_on_the_default_sut() -> None:
    """BAT-13: known-bug xfails (scenario-level bugs, unscoped known_bug tests) and fixed_in scenarios alone do not make
    a feature covered; a scoped known-bug test (xfail(raises=...)) and a plain scenario do."""
    strict = PROJECT.strict_on_default_sut
    assert not strict("regression.user-bypass-actors")  # fixed_in 1.7.0.dev7
    assert strict("cli.kb.team-permissions-removal")  # a step-level bug: the rest stays strict
    assert not strict("cli.kb.variables-pagination")  # scenario-level KB-003
    assert not strict("tests/cli/test_known_bugs.py::test_apply_fails_on_validation_errors")
    assert strict("tests/webapp/test_commands.py::test_sync_check_crash")  # xfail(raises=...)
    assert strict("cli.repo.visibility")
    entry = {"status": "covered", "covered_by": ["regression.user-bypass-actors"], "gap_outline": None}
    assert any("runs strictly on the default SUT" in problem for problem in PROJECT.status_problems(entry))


def test_verified_on_records_green_live_runs() -> None:
    """BAT-13: verified_on lists {target, sut, run, date} of live runs, only for features with a live item."""
    run = {"target": "free", "sut": "release:latest", "run": "t3c7z8a5", "date": "2026-10-03"}
    live = {"status": "covered", "covered_by": ["cli.repo.visibility"], "verified_on": [run]}
    assert PROJECT.verified_problems(live) == [] and live_verified(live) and PROJECT.verification(live) == "live"
    assert PROJECT.verified_problems({**live, "verified_on": []})
    assert PROJECT.verified_problems({**live, "verified_on": [{**run, "run": "latest"}]}) == [
        "verified_on[0].run: invalid value 'latest'"
    ]
    offline_only = {"status": "covered", "covered_by": ["O-VAL-OK"], "verified_on": [run]}
    assert PROJECT.verified_problems(offline_only) == [
        "verified_on records live runs: the feature needs a live covering item"
    ]
    assert PROJECT.verification({"status": "covered", "covered_by": ["cli.repo.visibility"]}) == "**unverified**"


def test_template_parser_reads_nested_and_inherited_keys() -> None:
    """The template parser handles nested objects, inheritance and aliases (newRepoWebhook = newOrgWebhook)."""
    tpl = template_keys(TEMPLATE.read_text(encoding="utf-8"))
    assert {"max_cache_size_gb", "fork_pr_approval_policy", "enabled"} <= tpl["newRepo.workflows"]
    assert {"enabled_repositories", "selected_repositories"} <= tpl["newOrg.settings.workflows"]
    assert {"include_repo_names", "required_merge_queue", "bypass_actors"} <= tpl["newOrgRuleset"]
    assert tpl["newRepoWebhook"] == tpl["newOrgWebhook"]
    assert tpl["newEnvSecret"] == tpl["newRepoSecret"] == {"name", "value"}
    assert "workflows" in tpl["newOrg.settings"] and "plan" in tpl["newOrg.settings"]


def test_markdown_text_escapes_outside_code_spans() -> None:
    """Free text keeps code spans verbatim and escapes what GitHub would turn into tags, emphasis or strikethrough."""
    assert md_text("a <org>  *x*\n`<y> *z*` ~w~") == "a &lt;org&gt; \\*x\\* `<y> *z*` \\~w\\~"
    assert md_cell(md_text("('a' | 'b')")) == "('a' \\| 'b')"


def test_the_assist_check_reports_the_same_problems() -> None:
    """MatrixProject.all_problems (otterdog-e2e assist check scenarios/coverage.yaml) is clean for the committed
    matrix: it runs every check above."""
    assert PROJECT.all_problems() == []


def main(argv: Sequence[str]) -> int:
    """``--write`` regenerates docs/coverage-matrix.md; without arguments, print the coverage per area."""
    data = matrix()
    if "--write" in argv:
        DOC.write_text(PROJECT.render_markdown(data), encoding="utf-8")
        sys.stdout.write(f"wrote {DOC.relative_to(ROOT)}\n")
    sys.stdout.write(PROJECT.summary_text(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
