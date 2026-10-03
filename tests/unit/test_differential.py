"""Unit tests of otterdog_e2e.differential: PR manifests, compare() and the markdown/JSON reports."""

from __future__ import annotations

import json
import re
import textwrap
from pathlib import Path

import pytest

from otterdog_e2e.differential import (
    Delta,
    DiffReport,
    ExpectedDelta,
    PrManifest,
    PrManifestError,
    compare,
    compare_files,
    load_pr_manifest,
    md_code,
    md_fence,
    truncate_lines,
    unified_diff,
)
from otterdog_e2e.observe import Observation
from otterdog_e2e.redact import Redactor

BASE, HEAD = "v1.6.1", "pr790-0a1b2c3"


def obs(scenario: str, step: str, key: str, content: str, *, role: str = "base", kind: str = "cli") -> Observation:
    """An observation of the base or head SUT."""
    return Observation(BASE if role == "base" else HEAD, role, scenario, step, kind, key, content, {})


def head(scenario: str, step: str, key: str, content: str, *, kind: str = "cli") -> Observation:
    """An observation of the head SUT."""
    return obs(scenario, step, key, content, role="head", kind=kind)


# --- ExpectedDelta ------------------------------------------------------------------------------------------------
def test_expected_delta_fields_are_fnmatch_patterns() -> None:
    """None matches anything; patterns use fnmatch (case-sensitive); keys also match without #n."""
    assert ExpectedDelta("O-VAL-*").matches("O-VAL-790", "s", "cli", "validate")
    assert ExpectedDelta("O-VAL-790", step="st*", kind="cli", key="val*").matches(
        "O-VAL-790", "step1", "cli", "validate"
    )
    assert not ExpectedDelta("O-VAL-790", kind="oracle").matches("O-VAL-790", "s", "cli", "validate")
    assert not ExpectedDelta("o-val-790").matches("O-VAL-790", "s", "cli", "validate")
    assert ExpectedDelta("W-*", key="plan").matches("W-X", "s", "cli", "plan#2")
    assert not ExpectedDelta("W-*", step="other").matches("W-X", "", "cli", "plan")
    assert ExpectedDelta("W-*", step="").matches("W-X", "", "cli", "plan")
    assert ExpectedDelta("S", kind="cli").label() == "S/*/cli/*"


# --- PR manifests -------------------------------------------------------------------------------------------------
def _manifest(tmp_path: Path, text: str, name: str = "790.yaml") -> Path:
    """Write a manifest file."""
    path = tmp_path / name
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_load_full_manifest(tmp_path: Path) -> None:
    """Every field is parsed; expected deltas accept mappings and bare scenario patterns."""
    path = _manifest(
        tmp_path,
        """
        pr: 790
        title: "fix: status checks of rulesets without strict"
        base: v1.6.1
        template: head
        tags: [validate, rulesets]
        scenarios: [O-VAL-790, "cli.ruleset.*"]
        scenario_dirs: [otterdog-prs/790]
        expected_deltas:
          - {scenario: O-VAL-790, step: validate, kind: cli, key: validate, note: "error -> warning"}
          - O-LPLAN-*
        markers: {check-merge: "<!-- Otterdog Comment: check-merge -->"}
        notes: |
          Reviewed by hand.
        """,
    )
    manifest = load_pr_manifest(path)
    assert manifest == PrManifest(
        pr=790,
        title="fix: status checks of rulesets without strict",
        base="v1.6.1",
        template="head",
        tags=["validate", "rulesets"],
        scenarios=["O-VAL-790", "cli.ruleset.*"],
        scenario_dirs=["otterdog-prs/790"],
        expected_deltas=[
            ExpectedDelta("O-VAL-790", "validate", "cli", "validate", "error -> warning"),
            ExpectedDelta("O-LPLAN-*"),
        ],
        markers={"check-merge": "<!-- Otterdog Comment: check-merge -->"},
        notes="Reviewed by hand.\n",
    )


def test_minimal_and_local_manifests(tmp_path: Path) -> None:
    """Only pr is required; pr 0 is a local change (any file name)."""
    assert load_pr_manifest(_manifest(tmp_path, "pr: 792\n", "792.yaml")) == PrManifest(pr=792)
    local = load_pr_manifest(_manifest(tmp_path, "pr: 0\nbase: v1.6.0\n", "local-check-merge.yaml"))
    assert (local.pr, local.base, local.template) == (0, "v1.6.0", "own")


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("pr: 790\nscenarioz: []\n", "unknown keys \\['scenarioz'\\]"),
        ("title: x\n", "'pr' must be a non-negative integer"),
        ("pr: true\n", "'pr' must be"),
        ("pr: -1\n", "'pr' must be"),
        ("pr: '790'\n", "'pr' must be"),
        ("pr: 791\n", "does not match the file name"),
        ("pr: 790\ntemplate: mine\n", "'template' must be one of"),
        ("pr: 790\ntags: smoke\n", "'tags' must be a list"),
        ("pr: 790\nscenarios: ['']\n", "'scenarios' must be a list of non-empty strings"),
        ("pr: 790\nscenario_dirs: [/etc]\n", "relative paths"),
        ("pr: 790\nscenario_dirs: ['../outside']\n", "relative paths"),
        ("pr: 790\nmarkers: {a: 1}\n", "'markers' must be a mapping"),
        ("pr: 790\nexpected_deltas: {scenario: x}\n", "'expected_deltas' must be a list"),
        ("pr: 790\nexpected_deltas: [{step: x}]\n", "needs a non-empty 'scenario'"),
        ("pr: 790\nexpected_deltas: [{scenario: x, typo: 1}]\n", "unknown keys \\['typo'\\]"),
        ("pr: 790\nexpected_deltas: [{scenario: x, kind: 3}]\n", "kind must be a string"),
        ("pr: 790\nexpected_deltas: [3]\n", "must be a mapping or a scenario pattern"),
        ("pr: 790\nnotes: [a]\n", "'notes' must be a string"),
        ("- pr: 790\n", "must be a mapping"),
        ("", "must be a mapping"),
        ("pr: [unclosed\n", "invalid YAML"),
    ],
)
def test_invalid_manifests(tmp_path: Path, text: str, message: str) -> None:
    """Invalid manifests raise PrManifestError (a ValueError) naming the file."""
    path = _manifest(tmp_path, text)
    with pytest.raises(PrManifestError, match=message) as info:
        load_pr_manifest(path)
    assert isinstance(info.value, ValueError) and str(path) in str(info.value)


# --- compare ------------------------------------------------------------------------------------------------------
def test_compare_counts_unchanged_and_reports_changed_contents() -> None:
    """Equal contents are unchanged; different ones are deltas with a unified diff."""
    base = [obs("S1", "validate", "validate", "exit_code: 0\nok"), obs("S1", "plan", "plan", "exit_code: 0\nPlan: 1")]
    new = [head("S1", "validate", "validate", "exit_code: 0\nok"), head("S1", "plan", "plan", "exit_code: 2\nPlan: 1")]
    report = compare(base, new, base_label=BASE, head_label=HEAD)
    assert report.unchanged == 1 and report.not_comparable == []
    (delta,) = report.deltas
    assert (delta.scenario, delta.step, delta.kind, delta.key) == ("S1", "plan", "cli", "plan")
    assert (delta.base, delta.head, delta.expected, delta.change) == (
        "exit_code: 0\nPlan: 1",
        "exit_code: 2\nPlan: 1",
        False,
        "changed",
    )
    assert delta.diff.splitlines()[:2] == [f"--- base ({BASE})", f"+++ head ({HEAD})"]
    assert "-exit_code: 0" in delta.diff and "+exit_code: 2" in delta.diff
    assert report.unexpected() == [delta] and report.expected() == []


def test_one_sided_scenarios_are_not_comparable_never_deltas() -> None:
    """Scenarios recorded on one side only are listed (with their side), never compared."""
    base = [obs("S1", "", "validate", "a"), obs("ONLY-BASE", "", "validate", "x")]
    new = [head("S1", "", "validate", "a"), head("ONLY-HEAD", "", "validate", "y")]
    report = compare(base, new, base_label=BASE, head_label=HEAD)
    assert report.deltas == [] and report.unchanged == 1
    assert report.not_comparable == ["ONLY-BASE", "ONLY-HEAD"]
    assert report.not_comparable_sides == {"ONLY-BASE": "base", "ONLY-HEAD": "head"}


def test_missing_observation_inside_a_comparable_scenario_is_a_delta() -> None:
    """Within a comparable scenario an observation recorded on one side only is a delta (None on the other)."""
    base = [obs("S1", "s", "validate", "a"), obs("S1", "s", "plan", "p")]
    new = [head("S1", "s", "validate", "a"), head("S1", "s", "show", "w")]
    report = compare(base, new, base_label=BASE, head_label=HEAD)
    assert [(d.key, d.change) for d in report.deltas] == [("plan", "missing on head"), ("show", "missing on base")]
    assert report.deltas[0].head is None and report.deltas[1].base is None
    assert "head (not recorded)" in report.deltas[0].diff and "base (not recorded)" in report.deltas[1].diff


def test_expected_deltas_mark_deltas_and_unmatched_ones_are_kept() -> None:
    """ExpectedDelta matches flag deltas (with the note); declared deltas that never occur are reported."""
    base = [obs("O-VAL-790", "v", "validate", "error"), obs("O-OTHER", "v", "validate", "a")]
    new = [head("O-VAL-790", "v", "validate", "warning"), head("O-OTHER", "v", "validate", "b")]
    expected = [ExpectedDelta("O-VAL-*", note="fixed by #790"), ExpectedDelta("W-STALE-*", note="webapp")]
    report = compare(base, new, base_label=BASE, head_label=HEAD, expected=expected)
    first, second = report.deltas
    assert (first.expected, first.note) == (True, "fixed by #790")
    assert (second.expected, second.note) == (False, "")
    assert report.expected() == [first] and report.unexpected() == [second]
    assert report.unmatched_expected == [ExpectedDelta("W-STALE-*", note="webapp")]


def test_compare_keeps_first_seen_order_and_suffixes_repeated_identities() -> None:
    """Order follows the base recording, then head-only identities; repeated identities are numbered."""
    base = [obs("S", "", "b", "1"), obs("S", "", "a", "1"), obs("S", "", "a", "2")]
    new = [head("S", "", "b", "x"), head("S", "", "a", "1"), head("S", "", "a", "3"), head("S", "", "c", "1")]
    report = compare(base, new, base_label=BASE, head_label=HEAD)
    assert [d.key for d in report.deltas] == ["b", "a#2", "c"]
    assert report.unchanged == 1 and report.unchanged_by_scenario == {"S": 1}


def test_unified_diff_of_whitespace_only_changes() -> None:
    """Contents differing only by a trailing newline still get an explanatory diff text."""
    assert "line endings" in unified_diff("a\n", "a", base_label=BASE, head_label=HEAD)
    assert unified_diff("a", "a", base_label=BASE, head_label=HEAD) == ""


def test_compare_files_uses_recorded_sut_labels(tmp_path: Path) -> None:
    """compare_files loads both JSONL files; labels default to the SUT labels of the observations."""
    base_file, head_file = tmp_path / "base.jsonl", tmp_path / "head.jsonl"
    base_file.write_text(json.dumps(obs("S", "", "k", "1").to_json()) + "\n")
    head_file.write_text(json.dumps(head("S", "", "k", "2").to_json()) + "\n")
    report = compare_files(base_file, head_file)
    assert (report.base_label, report.head_label, len(report.deltas)) == (BASE, HEAD, 1)
    empty = compare_files(tmp_path / "none.jsonl", tmp_path / "none2.jsonl", head_label="h")
    assert (empty.base_label, empty.head_label, empty.deltas) == ("base", "h", [])


# --- reports ------------------------------------------------------------------------------------------------------
def _report() -> DiffReport:
    """A report with one unexpected, one expected delta, one unmatched expectation and one one-sided scenario."""
    base = [
        obs("O-VAL-790", "validate", "validate", "exit_code: 2\nError: get_model_header"),
        obs("O-LPLAN-ADD", "local-plan", "local-plan", "exit_code: 0\n" + "\n".join(f"line {i}" for i in range(100))),
        obs("O-SAME", "validate", "validate", "same"),
        obs("O-BASE-ONLY", "validate", "validate", "x"),
    ]
    new = [
        head("O-VAL-790", "validate", "validate", "exit_code: 0\nValidation succeeded"),
        head("O-LPLAN-ADD", "local-plan", "local-plan", "exit_code: 0\n" + "\n".join(f"LINE {i}" for i in range(100))),
        head("O-SAME", "validate", "validate", "same"),
    ]
    expected = [ExpectedDelta("O-VAL-790", note="#790 fixes the AttributeError"), ExpectedDelta("W-STALE-STATUS-792")]
    return compare(base, new, base_label=BASE, head_label=HEAD, expected=expected)


def test_markdown_report_sections() -> None:
    """Summary counts, scenario matrix, unexpected before expected deltas, unmatched and not comparable lists."""
    markdown = _report().to_markdown()
    assert markdown.startswith(f"# Differential report: `{BASE}` (base) vs `{HEAD}` (head)")
    assert "**1 unexpected delta(s)**" in markdown
    assert "| Unexpected deltas | 1 |" in markdown and "| Expected deltas | 1 |" in markdown
    assert "| Unchanged observations | 1 |" in markdown and "| Not comparable scenarios | 1 |" in markdown
    assert "| `O-LPLAN-ADD` | 0 | 0 | 1 | **unexpected change** |" in markdown
    assert "| `O-VAL-790` | 0 | 1 | 0 | expected change |" in markdown
    assert "| `O-SAME` | 1 | 0 | 0 | unchanged |" in markdown
    unexpected_at, expected_at = markdown.index("## Unexpected deltas (1)"), markdown.index("## Expected deltas (1)")
    assert unexpected_at < expected_at
    assert markdown.count("<details><summary>") == 2 and markdown.count("</details>") == 2
    assert "Note: #790 fixes the AttributeError" in markdown
    assert "## Expected deltas not observed (1)" in markdown and "`W-STALE-STATUS-792/*/*/*`" in markdown
    assert "## Not comparable (1)" in markdown and "`O-BASE-ONLY` — recorded on base only" in markdown


def test_markdown_truncates_long_diffs() -> None:
    """Diffs are cut to max_diff_lines with a pointer to differential.json."""
    markdown = _report().to_markdown(max_diff_lines=10)
    block = markdown[markdown.index("## Unexpected deltas") : markdown.index("## Expected deltas (1)")]
    fence = re.search(r"```diff\n(.*?)\n```", block, re.DOTALL)
    assert fence is not None
    lines = fence.group(1).splitlines()
    assert len(lines) == 11 and re.match(r"^\.\.\. \(\d+ more lines; full contents in differential.json\)$", lines[-1])
    assert "more lines" not in _report().to_markdown(max_diff_lines=0)


def test_markdown_without_differences() -> None:
    """An empty comparison says so and lists no delta sections."""
    report = compare([obs("S", "", "k", "1")], [head("S", "", "k", "1")], base_label=BASE, head_label=HEAD)
    markdown = report.to_markdown()
    assert "No differences between base and head" in markdown
    assert "## Unexpected deltas" not in markdown and "<details>" not in markdown


def test_markdown_escapes_markup_from_observations() -> None:
    """Coordinates are HTML-escaped in <summary>; fences outgrow backtick runs of the diff."""
    diff = unified_diff("```\na", "```\nb", base_label="b", head_label="h")
    delta = Delta("S<x>", "st&p", "cli", "k|`y`", "```\na", "```\nb", diff, False)
    markdown = DiffReport(BASE, HEAD, [delta]).to_markdown()
    assert "<summary><code>S&lt;x&gt;</code> / st&amp;p / cli / <code>k|`y`</code> (changed)</summary>" in markdown
    assert "<code>S<x></code>" not in markdown
    assert "````diff\n" in markdown and "\n````\n" in markdown


def test_markdown_size_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    """Over the size budget remaining deltas are listed without diff."""
    from otterdog_e2e import differential

    monkeypatch.setattr(differential, "MARKDOWN_MAX_BYTES", 4000)
    diff = "-" + "a" * 300 + "\n+" + "b" * 300
    deltas = [Delta(f"S{i}", "", "cli", "k", "a" * 300, "b" * 300, diff, False) for i in range(50)]
    markdown = DiffReport(BASE, HEAD, deltas).to_markdown()
    assert "Size budget reached" in markdown and "more delta(s) listed without diff" in markdown
    assert markdown.count("<details>") < 50 and len(markdown.encode()) < 8000


def test_to_json_counts_and_write(tmp_path: Path) -> None:
    """to_json keeps the contract counts and the additive fields; write() redacts both files."""
    report = _report()
    data = report.to_json()
    assert data["counts"] == {"unexpected": 1, "expected": 1}
    assert data["unmatched_expected"] == [
        {"scenario": "W-STALE-STATUS-792", "step": None, "kind": None, "key": None, "note": ""}
    ]
    assert data["not_comparable_sides"] == {"O-BASE-ONLY": "base"}
    json.dumps(data)
    secret = "e2e-differential-secret-0123456789"
    report.deltas[0].note = f"leaked {secret}"
    markdown_path, json_path = report.write(tmp_path / "out", redactor=Redactor([secret]))
    assert markdown_path.name == "differential.md" and json_path.name == "differential.json"
    for path in (markdown_path, json_path):
        assert secret not in path.read_text() and "***" in path.read_text()
    assert json.loads(json_path.read_text())["counts"] == {"unexpected": 1, "expected": 1}


def test_markdown_helpers() -> None:
    """Code spans and fences survive backticks; truncate_lines notes omitted lines."""
    assert md_code("a`b") == "``a`b``" and md_code("`x") == "`` `x ``"
    assert md_fence("```\ncode", "diff").startswith("````diff\n")
    assert md_fence("plain") == "```\nplain\n```"
    assert truncate_lines("a\nb\nc", 2) == "a\nb\n... (1 more lines)"
    assert truncate_lines("a\nb", 2) == "a\nb"
