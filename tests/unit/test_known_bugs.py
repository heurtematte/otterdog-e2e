"""known_bugs.yaml loading and links to scenarios (SPEC 12.5)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from otterdog_e2e.known_bugs import KnownBug, KnownBugError, bugs_for_scenario, check_references, load

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "scenarios" / "known_bugs.yaml"
COVERAGE = ROOT / "scenarios" / "coverage.yaml"
KNOWN_ISSUES = ROOT / "docs" / "known-issues.md"
# findings of the coverage matrix -> their entry in the registry (F-01 -> KB-028 ... F-13 -> KB-040)
FINDING_BUGS = {f"F-{index:02d}": f"KB-{27 + index:03d}" for index in range(1, 14)}
WEB_UI_BUG = "KB-041"  # two_factor_requirement never read through the web UI (found by the web-UI tier)

VALID = """
- id: KB-001
  title: apply exits 0 on validation errors
  status: confirmed
  evidence: [otterdog/operations/apply.py:121]
  upstream: null
  fixed_in: null
  scenarios: [C-NEG-VALIDATION]
- id: KB-002
  title: stale PR status overwrite
  status: fixed
  fixed_in: pr-792
  upstream: https://github.com/eclipse-csi/otterdog/pull/792
  scenarios: [W-PR-STALE-SNAPSHOT]
- id: KB-003
  title: unpaginated variable reads
"""


def write(tmp_path: Path, text: str) -> Path:
    """Write known_bugs.yaml."""
    path = tmp_path / "known_bugs.yaml"
    path.write_text(text)
    return path


def test_load_valid_file(tmp_path: Path) -> None:
    """Entries keyed by id with defaults for optional fields."""
    bugs = load(write(tmp_path, VALID))
    assert list(bugs) == ["KB-001", "KB-002", "KB-003"]
    assert bugs["KB-001"].evidence == ["otterdog/operations/apply.py:121"] and bugs["KB-001"].status == "confirmed"
    assert bugs["KB-002"].fixed_in == "pr-792" and bugs["KB-002"].upstream.endswith("/792")  # type: ignore[union-attr]
    assert bugs["KB-003"] == KnownBug("KB-003", "unpaginated variable reads")


def test_crash_signature_explains_only_its_own_crash(tmp_path: Path) -> None:
    """crash_signature is optional; a bug explains a crash only when the output carries its signature."""
    path = tmp_path / "known_bugs.yaml"
    path.write_text(
        "- id: KB-008\n  title: org ruleset crash\n  status: confirmed\n"
        "  crash_signature: \"object has no attribute 'get_model_header'\"\n"
        "- id: KB-009\n  title: no crash documented\n"
    )
    bugs = load(path)
    crash = "Error: 'GitHubOrganization' object has no attribute 'get_model_header'"
    other = "Error: 'Repository' object has no attribute 'environments'"
    assert bugs["KB-008"].explains_crash(crash) and not bugs["KB-008"].explains_crash(other)
    assert bugs["KB-009"].crash_signature is None and not bugs["KB-009"].explains_crash(crash)
    assert not KnownBug("KB-010", "empty signature", crash_signature="").explains_crash(crash)


def test_xfail_mark_is_not_strict() -> None:
    """A fixed bug shows up as XPASS instead of failing the run."""
    mark = KnownBug("KB-001", "apply exits 0").xfail_mark().mark
    assert mark.name == "xfail" and mark.kwargs == {"reason": "KB-001: apply exits 0", "strict": False}


def test_missing_or_empty_file_has_no_bugs(tmp_path: Path) -> None:
    """known_bugs.yaml is optional."""
    assert load(tmp_path / "absent.yaml") == {}
    assert load(write(tmp_path, "")) == {}


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("- {id: KB-001, title: a}\n- {id: KB-001, title: b}\n", "duplicate known bug id"),
        ("- {id: KB-001, title: a, severity: high}\n", "unknown key"),
        ("- {id: KB-001, title: a, status: wontfix}\n", "status"),
        ("- {id: BUG-1, title: a}\n", "does not match"),
        ("- {id: KB-001}\n", "title"),
        ("- {id: KB-001, title: a, scenarios: x}\n", "list of strings"),
        ("{id: KB-001}\n", "expected a list"),
        ("- [KB-001]\n", "expected a mapping"),
        ("- {id: KB-001, title: [unclosed\n", "invalid YAML"),
    ],
)
def test_invalid_files(tmp_path: Path, text: str, match: str) -> None:
    """Strict validation (KnownBugError is a ValueError)."""
    with pytest.raises(KnownBugError, match=match):
        load(write(tmp_path, text))
    assert issubclass(KnownBugError, ValueError)


def test_bugs_for_scenario_and_references(tmp_path: Path) -> None:
    """A scenario links through its own known_bug field or through a bug's scenarios list."""
    bugs = load(write(tmp_path, VALID))
    assert [b.id for b in bugs_for_scenario(bugs, "W-PR-STALE-SNAPSHOT")] == ["KB-002"]
    assert [b.id for b in bugs_for_scenario(bugs, "C-NEG-VALIDATION", declared="KB-001")] == ["KB-001"]
    assert [b.id for b in bugs_for_scenario(bugs, "other", declared="KB-003")] == ["KB-003"]
    with pytest.raises(KeyError, match="KB-999"):
        bugs_for_scenario(bugs, "x", declared="KB-999")
    problems = check_references(bugs, [("C-NEG-VALIDATION", "KB-001"), ("x", "KB-999")])
    assert problems == [
        "scenario 'x' declares unknown known bug 'KB-999'",
        "KB-002 lists unknown scenario 'W-PR-STALE-SNAPSHOT'",
    ]


def test_step_level_references(tmp_path: Path) -> None:
    """Step-level known bugs must exist and stay out of the bug's scenarios list (that would xfail the whole item),
    unless the scenario declares the same bug itself."""
    bugs = load(write(tmp_path, VALID))
    pairs = [("C-NEG-VALIDATION", "KB-001"), ("W-PR-STALE-SNAPSHOT", None), ("offline.x", None)]
    steps = [("offline.x", "crash", "KB-003"), ("offline.x", "typo", "KB-999"), ("W-PR-STALE-SNAPSHOT", "s", "KB-002")]
    listed = (
        "KB-002 lists scenario 'W-PR-STALE-SNAPSHOT', whose step 's' declares it: the whole item would xfail"
        " (keep step-level bugs out of the bug's scenarios list)"
    )
    assert check_references(bugs, pairs, steps) == [
        "scenario 'offline.x' step 'typo' declares unknown known bug 'KB-999'",
        listed,
    ]
    assert check_references(bugs, pairs, [("C-NEG-VALIDATION", "s", "KB-001")]) == []  # declared by the scenario too


def test_fixed_bugs_affect_only_older_suts() -> None:
    """Open bugs affect every SUT; a fixed bug only SUTs older than a PEP 440 fixed_in."""
    assert KnownBug("KB-001", "t").affects(None) and not KnownBug("KB-001", "t").fixed
    fixed = KnownBug("KB-008", "t", status="fixed", fixed_in="1.7.0.dev15")
    assert fixed.fixed and fixed.affects("1.6.1") and not fixed.affects("1.7.0.dev15+e2e.g9bdeb75")
    assert not fixed.affects(None)
    assert not KnownBug("KB-018", "t", status="fixed", fixed_in="pr-792").affects("1.6.1")


# --- the project registry -----------------------------------------------------------------------------------------
def test_registry_holds_the_coverage_and_web_ui_findings() -> None:
    """F-01..F-13 of the coverage matrix and the web-UI finding are confirmed entries; KB-002 lists the web-UI test
    that exercises install-app (its known_bug marker)."""
    bugs = load(REGISTRY)
    for bug_id in (*FINDING_BUGS.values(), WEB_UI_BUG):
        assert bugs[bug_id].status == "confirmed" and bugs[bug_id].evidence, bug_id
        assert bugs[bug_id].upstream is None and bugs[bug_id].fixed_in is None, bug_id
    assert "webui.cmd.install-app" in bugs["KB-002"].scenarios
    assert "two_factor_required" in bugs[WEB_UI_BUG].title


def test_every_scenario_and_step_link_is_valid() -> None:
    """Scenario and step known_bug ids of every YAML scenario directory exist, bugs list existing scenarios or Python
    scenario ids of the live test tiers (tests/unit/test_yaml_cli.py checks the latter), and step-level bugs stay
    step-level."""
    from otterdog_e2e.scenarios.collect import collect_scenarios

    scenarios = [
        scenario
        for name in ("offline", "cli", "enterprise")
        for scenario in collect_scenarios([ROOT / "scenarios" / name])
    ]
    pairs = [(scenario.id, scenario.known_bug) for scenario in scenarios]
    steps = [
        (scenario.id, step.name, step.known_bug) for scenario in scenarios for step in scenario.steps if step.known_bug
    ]
    problems = [
        problem
        for problem in check_references(load(REGISTRY), pairs, steps)
        if " lists unknown scenario " not in problem  # Python tests carry the other ids (test_yaml_cli)
    ]
    assert not problems, problems


def test_coverage_findings_name_their_known_bug() -> None:
    """Each finding of scenarios/coverage.yaml says which entry registers it, and every feature citing a finding lists
    that entry in known_bugs (the coverage matrix test checks that the ids exist)."""
    data = yaml.safe_load(COVERAGE.read_text(encoding="utf-8"))
    findings = {finding["id"]: finding for finding in data["findings"]}
    for finding_id, bug_id in FINDING_BUGS.items():
        assert f"registered as {bug_id}" in findings[finding_id]["suggestion"], finding_id
    for feature in data["features"]:
        for finding_id in feature.get("findings") or []:
            if finding_id in FINDING_BUGS:
                assert FINDING_BUGS[finding_id] in (feature.get("known_bugs") or []), (feature["id"], finding_id)
    two_factor = next(feature for feature in data["features"] if feature["id"] == "org-settings.web-ui.two-factor")
    assert WEB_UI_BUG in two_factor["known_bugs"]


def test_known_issues_sections_name_their_finding() -> None:
    """The doc section of each registered finding says which coverage finding it is (traceability both ways)."""
    sections = {
        match.group(1): part
        for part in re.split(r"(?m)^### ", KNOWN_ISSUES.read_text(encoding="utf-8"))[1:]
        if (match := re.match(r"(KB-\d{3,})\b", part))
    }
    for finding_id, bug_id in FINDING_BUGS.items():
        assert f"Coverage finding {finding_id}." in sections[bug_id], bug_id
        assert f"| {bug_id} |" in KNOWN_ISSUES.read_text(encoding="utf-8"), f"{bug_id} missing from the summary table"
