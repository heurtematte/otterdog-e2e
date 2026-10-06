"""Unit tests of otterdog_e2e.changes: scenario references to otterdog PRs and named changes, change identifiers, the
references of YAML scenarios and Python tests, conflicts and the ChangeSpec of a differential run."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.changes import (
    ChangeError,
    ChangeId,
    DeltaPattern,
    Reference,
    ReferencingScenario,
    change_spec,
    collect_references,
    conflicts,
    default_change,
    load_change,
    parse_references,
    python_references,
    yaml_references,
)
from otterdog_e2e.differential import ExpectedDelta
from otterdog_e2e.scenarios.collect import collect_scenarios
from otterdog_e2e.scenarios.model import ScenarioError, load_scenario

SHA = "a" * 40
STEPS = ("no-strict", "with-strict")


# --- change identifiers -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected", "label"),
    [
        ("790", ChangeId(pr=790), "#790"),
        ("#790", ChangeId(pr=790), "#790"),
        (" 790 ", ChangeId(pr=790), "#790"),
        ("check-merge", ChangeId(slug="check-merge"), "check-merge"),
    ],
)
def test_change_ids_parse(text: str, expected: ChangeId, label: str) -> None:
    """N and #N are pull requests, a lowercase slug starting with a letter is a named change."""
    change = ChangeId.parse(text)
    assert change == expected and change.label == label and ChangeId.parse(str(change)) == change


@pytest.mark.parametrize("text", ["0", "#0", "", "Check-Merge", "1abc", "pr:790", "check merge", "#x"])
def test_invalid_change_ids(text: str) -> None:
    """Anything else is a ChangeError (a ValueError)."""
    with pytest.raises(ChangeError):
        ChangeId.parse(text)


def test_default_change_is_the_pr_of_a_pr_sut() -> None:
    """--change wins; else N of a pr:N@<sha> SUT; other SUTs have no default change."""
    assert default_change(None, f"pr:790@{SHA}") == ChangeId(pr=790)
    assert default_change("check-merge", f"pr:790@{SHA}") == ChangeId(slug="check-merge")
    assert default_change("  ", f"pr:792@{SHA}") == ChangeId(pr=792)
    assert default_change(None, "sha:9bdeb75") is None and default_change(None, None) is None
    assert default_change(None, "release:latest") is None and default_change(None, "pr:x@y") is None
    with pytest.raises(ChangeError):
        default_change("not a change", "sha:9bdeb75")


# --- parse_references -------------------------------------------------------------------------------------------------
def test_full_reference() -> None:
    """Every key is parsed; notes are stripped; template None when not declared."""
    (reference, local) = parse_references(
        [
            {
                "pr": 790,
                "note": " fixes it \n",
                "base": "sha:b5f7bb1",
                "template": "own",
                "expected_deltas": [
                    {"step": "no-*", "kind": "cli", "key": "validate", "note": "error"},
                    {"key": "local-plan"},
                ],
            },
            {"change": "check-merge"},
        ],
        steps=STEPS,
    )
    assert reference == Reference(
        ChangeId(pr=790),
        "fixes it",
        (DeltaPattern("no-*", "cli", "validate", "error"), DeltaPattern(key="local-plan")),
        "sha:b5f7bb1",
        "own",
    )
    assert local == Reference(ChangeId(slug="check-merge"))
    assert reference.to_json() == {
        "pr": 790,
        "note": "fixes it",
        "expected_deltas": [{"step": "no-*", "kind": "cli", "key": "validate", "note": "error"}, {"key": "local-plan"}],
        "base": "sha:b5f7bb1",
        "template": "own",
    }
    assert parse_references(None, steps=STEPS) == [] and local.to_json() == {"change": "check-merge"}


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ({"pr": 790}, "expected a list of references"),
        (["790"], r"references\[0\]: expected a mapping"),
        ([{"note": "x"}], "exactly one of 'pr'"),
        ([{"pr": 790, "change": "x"}], "exactly one of 'pr'"),
        ([{"pr": 790, "typo": 1}], r"unknown key\(s\) \['typo'\]"),
        ([{"pr": True}], "positive pull request number"),
        ([{"pr": 0}], "positive pull request number"),
        ([{"pr": "790"}], "positive pull request number"),
        ([{"change": "Check"}], "is not a change slug"),
        ([{"change": "42"}], "is not a change slug"),
        ([{"pr": 790, "note": 3}], r"references\[0\]\.note: expected a non-empty string"),
        ([{"pr": 790, "template": "mine"}], "is not one of"),
        ([{"pr": 790, "base": "pr:1@" + SHA}], "is a pr spec"),
        ([{"pr": 790, "base": "dirty:../otterdog"}], "is a dirty spec"),
        ([{"pr": 790, "base": "nonsense"}], "is not a SUT spec"),
        ([{"pr": 790, "base": ""}], "expected a non-empty string"),
        ([{"pr": 790, "expected_deltas": {"step": "x"}}], "expected a list of mappings"),
        ([{"pr": 790, "expected_deltas": [{"scenario": "x"}]}], r"unknown key\(s\) \['scenario'\]"),
        ([{"pr": 790, "expected_deltas": [{"kind": 3}]}], r"expected_deltas\[0\]\.kind: expected a non-empty string"),
        ([{"pr": 790, "expected_deltas": [{"step": "missing"}]}], "matches no step of the scenario"),
        ([{"pr": 790, "expected_deltas": [{"key": "v"}, {"key": "v"}]}], "duplicate expected delta"),
        ([{"pr": 790}, {"pr": 790}], "#790 is referenced twice"),
        ([{"change": "x"}, {"change": "x"}], "x is referenced twice"),
    ],
)
def test_invalid_references(value: Any, message: str) -> None:
    """Unknown keys, wrong types, bad bases, unknown steps and duplicates are ChangeErrors naming the key path."""
    with pytest.raises(ChangeError, match=message):
        parse_references(value, steps=STEPS)


def test_python_references_name_no_step() -> None:
    """A Python test has no steps (steps=None): a step pattern is refused, other delta keys are fine."""
    with pytest.raises(ChangeError, match="a Python test has no steps"):
        parse_references([{"pr": 792, "expected_deltas": [{"step": "x"}]}], steps=None)
    (reference,) = parse_references([{"pr": 792, "expected_deltas": [{"note": "webapp"}]}], steps=None)
    assert reference.expected_deltas == (DeltaPattern(note="webapp"),)


# --- conflicts and change specs ---------------------------------------------------------------------------------------
def entry(scenario: str, change: ChangeId, **values: Any) -> ReferencingScenario:
    """A referencing scenario of a YAML file."""
    return ReferencingScenario(scenario, Path(f"{scenario}.yaml"), "yaml", Reference(change, **values))


def test_change_spec_gathers_the_references_of_one_change() -> None:
    """Scenarios (unique, in order), expected deltas with the scenario implied, the declared base and template."""
    pr = ChangeId(pr=790)
    entries = [
        entry("O-A", pr, expected_deltas=(DeltaPattern("s", "cli", "validate", "n"),), base="sha:b5f7bb1"),
        entry("O-B", pr, template="head"),
        entry("O-C", ChangeId(pr=792), base="tag:v1.6.0"),
        entry("O-A", pr, expected_deltas=(DeltaPattern("s", "cli", "validate", "n"),)),
    ]
    spec = change_spec(pr, entries)
    assert (spec.change, spec.base, spec.template, spec.label) == (pr, "sha:b5f7bb1", "head", "#790")
    assert spec.scenarios == ["O-A", "O-B"]
    assert spec.expected_deltas == [ExpectedDelta("O-A", "s", "cli", "validate", "n")]
    assert [item.scenario for item in spec.referencing] == ["O-A", "O-B", "O-A"]
    empty = change_spec(ChangeId(slug="nobody"), entries)
    assert (empty.base, empty.template, empty.scenarios, empty.expected_deltas) == (None, "own", [], [])


def test_conflicting_bases_and_templates_are_errors() -> None:
    """Two references of one change with different base (or template) values conflict; equal or unset ones do not."""
    pr = ChangeId(pr=790)
    entries = [
        entry("O-A", pr, base="sha:b5f7bb1", template="own"),
        entry("O-B", pr, base="tag:v1.6.0", template="own"),
        entry("O-C", pr),
        entry("O-D", ChangeId(slug="x"), template="head"),
        entry("O-E", ChangeId(slug="x"), template="base"),
    ]
    assert conflicts(entries) == [
        "#790: conflicting 'base' of its references ('sha:b5f7bb1' in O-A; 'tag:v1.6.0' in O-B)",
        "x: conflicting 'template' of its references ('base' in O-E; 'head' in O-D)",
    ]
    with pytest.raises(ChangeError, match="#790: conflicting 'base'"):
        change_spec(pr, entries)
    assert change_spec(ChangeId(pr=792), entries).scenarios == []


# --- reading the repository -------------------------------------------------------------------------------------------
YAML_SCENARIO = """\
id: O-VAL-EXAMPLE
title: Example
references:
  - pr: 790
    base: sha:b5f7bb1
    expected_deltas:
      - {step: no-strict, key: validate}
steps:
  - name: no-strict
    validate: {ok: true}
"""

PYTHON_TEST = """\
import pytest

SCENARIO = "W-EXAMPLE"
REFERENCES = [{"pr": 792, "template": "own", "expected_deltas": [{"note": "webapp only"}]}]
pytestmark = [pytest.mark.webapp]


@pytest.mark.scenario(SCENARIO, priority="P1", references=REFERENCES)
def test_constant_references():
    pass


@pytest.mark.scenario("W-INLINE", references=[{"change": "check-merge", "base": "tag:v1.6.0"}])
def test_inline_references():
    pass


@pytest.mark.scenario("W-NONE", priority="P2")
def test_without_references():
    pass


class TestGroup:
    @pytest.mark.scenario("W-METHOD", references=[{"pr": 790}])
    def test_method(self):
        pass
"""


def write(root: Path, relative: str, text: str) -> Path:
    """Write a file below ``root``."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text), encoding="utf-8")
    return path


def test_yaml_and_python_references(tmp_path: Path) -> None:
    """YAML scenarios (lenient read, strict references) and Python markers (AST literals or module constants)."""
    scenario = write(tmp_path, "scenarios/offline/val-example.yaml", YAML_SCENARIO)
    module = write(tmp_path, "tests/webapp/test_example.py", PYTHON_TEST)
    write(tmp_path, "scenarios/offline/other.yaml", "id: O-OTHER\ntitle: t\nsteps: [{name: s}]\n")
    write(tmp_path, "scenarios/offline/broken.yaml", "id: [unclosed\nreferences: x\n")
    write(tmp_path, "tests/unit/test_ignored.py", PYTHON_TEST)  # not an e2e tier directory
    (yaml_entry,) = yaml_references(scenario)
    assert (yaml_entry.scenario, yaml_entry.kind, yaml_entry.reference.base) == ("O-VAL-EXAMPLE", "yaml", "sha:b5f7bb1")
    found = python_references(module)
    assert [(item.scenario, item.test, item.reference.change.label) for item in found] == [
        ("W-EXAMPLE", "test_constant_references", "#792"),
        ("W-INLINE", "test_inline_references", "check-merge"),
        ("W-METHOD", "test_method", "#790"),
    ]
    assert found[0].reference.expected_deltas == (DeltaPattern(note="webapp only"),)
    entries = collect_references(tmp_path / "scenarios", tmp_path / "tests")
    assert [item.scenario for item in entries] == ["O-VAL-EXAMPLE", "W-EXAMPLE", "W-INLINE", "W-METHOD"]
    spec = load_change(tmp_path / "scenarios", tmp_path / "tests", ChangeId(pr=790))
    assert spec.scenarios == ["O-VAL-EXAMPLE", "W-METHOD"] and spec.base == "sha:b5f7bb1"
    assert spec.expected_deltas == [ExpectedDelta("O-VAL-EXAMPLE", "no-strict", None, "validate")]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("@pytest.mark.scenario('W-X', references=REFS)\ndef test_x():\n    pass\n", "must be literals"),
        ("@pytest.mark.scenario(ID, references=[])\ndef test_x():\n    pass\n", "must be literals"),
        ("@pytest.mark.scenario(references=[{'pr': 1}])\ndef test_x():\n    pass\n", "needs a literal scenario id"),
        (
            (
                "@pytest.mark.scenario('W-X', references=[{'pr': 1, 'expected_deltas': [{'step': 's'}]}])\n"
                "def test_x():\n    pass\n"
            ),
            "test_x: references.*a Python test has no steps",
        ),
    ],
)
def test_invalid_python_references(tmp_path: Path, text: str, message: str) -> None:
    """Non-literal references or ids and invalid entries are ChangeErrors naming the file and line."""
    module = write(tmp_path, "tests/cli/test_bad.py", "import pytest\n\n\n" + text)
    with pytest.raises(ChangeError, match=message) as info:
        python_references(module)
    assert f"{module}:4" in str(info.value)


def test_invalid_yaml_references_name_the_file(tmp_path: Path) -> None:
    """A YAML scenario with invalid references is a ChangeError naming its file."""
    path = write(tmp_path, "scenarios/cli/x.yaml", YAML_SCENARIO.replace("no-strict, key", "missing, key"))
    with pytest.raises(ChangeError, match="matches no step of the scenario") as info:
        yaml_references(path)
    assert str(path) in str(info.value)


# --- the scenario model -----------------------------------------------------------------------------------------------
def test_the_model_reads_and_validates_references(tmp_path: Path) -> None:
    """Scenario.references; invalid references are ScenarioErrors with the key path; collection refuses conflicts."""
    scenario = load_scenario(write(tmp_path, "scenarios/offline/a.yaml", YAML_SCENARIO))
    assert scenario.references == [
        Reference(ChangeId(pr=790), "", (DeltaPattern("no-strict", None, "validate"),), "sha:b5f7bb1")
    ]
    bad = write(tmp_path, "scenarios/offline/b.yaml", YAML_SCENARIO.replace("pr: 790", "pr: 790\n    typo: 1"))
    with pytest.raises(ScenarioError, match=r"references\[0\]: unknown key\(s\) \['typo'\]"):
        load_scenario(bad)
    bad.write_text(
        YAML_SCENARIO.replace("O-VAL-EXAMPLE", "O-VAL-OTHER").replace("sha:b5f7bb1", "tag:v1.6.0"), encoding="utf-8"
    )
    with pytest.raises(ScenarioError, match="#790: conflicting 'base'"):
        collect_scenarios([tmp_path / "scenarios" / "offline"])
