"""The YAML of scenarios/offline and the references of the repository's scenarios (no network, no otterdog, no docker).

Every offline scenario loads with the strict model, renders for the offline organization exactly as OfflineEngine
renders it, and follows the catalogue conventions; the references of every scenario (YAML and Python tests) load, the
references of one change agree on its base and template, and the migrated changes (#790, #792, check-merge) keep the
expectations of their former PR manifests; the references to #790 classify proof-of-concept-shaped observations as
expected and unexpected deltas.
"""

from __future__ import annotations

import re
from functools import cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from otterdog_e2e.changes import ChangeId, ChangeSpec, ReferencingScenario, change_spec, collect_references, conflicts
from otterdog_e2e.differential import compare
from otterdog_e2e.observe import Observation
from otterdog_e2e.scenarios.collect import scenario_marks
from otterdog_e2e.scenarios.model import Scenario, load_scenario, load_scenarios, render_step, scenario_files
from otterdog_e2e.scenarios.offline import OFFLINE_ORG, OfflineEngine, offline_run_context
from otterdog_e2e.selection import SCENARIO_TAGS
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli

PROJECT = Path(__file__).resolve().parents[2]
OFFLINE_DIR = PROJECT / "scenarios" / "offline"
# SPEC 19 offline catalogue (YAML scenarios; O-VERSION, O-WEB-BOOT and O-WEB-SIG are Python tests of tests/offline)
CATALOGUE = {
    "O-VAL-OK": "P0",
    "O-VAL-SYNTAX": "P0",
    "O-VAL-PLAN-GATE": "P0",
    "O-VAL-ORGSECRET-PRIVATE-FREE": "P0",
    "O-VAL-RULESET-STRICT": "P0",
    "O-LPLAN-ADD": "P0",
    "O-LPLAN-CHANGE": "P0",
    "O-LPLAN-REMOVE": "P0",
    "O-SHOW-DEFAULT": "P0",
    "O-CANON": "P1",
}
# offline reproduction of the org-ruleset crash of #790 (E-ORG-RULESET offline)
EXTENSIONS = {"O-VAL-ORG-RULESET-STRICT": "P1"}
# every offline scenario file (catalogue, extensions and the battery's scenarios) gets the metadata and render checks
SCENARIO_IDS = sorted(
    {**CATALOGUE, **EXTENSIONS, **{load_scenario(path).id: "" for path in scenario_files(OFFLINE_DIR)}}
)
# fragment keys whose snippets set fields instead of naming objects (offline settings may set the profile)
UNNAMED_FRAGMENT_KEYS = frozenset({"settings", "extra"})
BASE_790 = "b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8"  # first parent of the #790 squash commit 9bdeb75
# a run of 3+ digits in a scenario id or file name reads as a PR or issue number (name the behaviour instead)
NUMBER_RE = re.compile(r"(?<![0-9])[0-9]{3,}(?![0-9])")


@cache
def offline_scenarios() -> dict[str, Scenario]:
    """scenarios/offline by id (load_scenarios: strict model, unique ids)."""
    return {scenario.id: scenario for scenario in load_scenarios(OFFLINE_DIR)}


@cache
def references() -> tuple[ReferencingScenario, ...]:
    """Every references entry of the repository (YAML scenarios and Python tests)."""
    return tuple(collect_references(PROJECT / "scenarios", PROJECT / "tests"))


def spec(change: str) -> ChangeSpec:
    """The ChangeSpec of a change of the repository."""
    return change_spec(ChangeId.parse(change), references())


def offline_engine() -> OfflineEngine:
    """An OfflineEngine over a fake CLI: its variables and renderer are exactly those of the offline tier."""
    workspace = SimpleNamespace(org=OFFLINE_ORG, project=OFFLINE_ORG, template=offline_template())
    return OfflineEngine(
        cli=FakeCli(org=OFFLINE_ORG),  # type: ignore[arg-type]
        workspace=workspace,  # type: ignore[arg-type]
        template_src=Path("/nonexistent"),
        run_ctx=offline_run_context(),
    )


# --- scenarios/offline ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("path", scenario_files(OFFLINE_DIR), ids=lambda path: path.name)
def test_offline_scenario_file_loads(path: Path) -> None:
    """Each file loads alone with the strict model (tier offline inferred from the directory, never live)."""
    scenario = load_scenario(path)
    assert scenario.tier == "offline" and not scenario.is_live


def test_the_catalogue_is_complete() -> None:
    """Every SPEC 19 offline YAML scenario and declared extension exists with its priority (the battery's other
    scenarios need no registration here: scenarios/coverage.yaml lists them in covered_by)."""
    found = {scenario_id: scenario.priority for scenario_id, scenario in offline_scenarios().items()}
    expected = {**CATALOGUE, **EXTENSIONS}
    assert {scenario_id: found.get(scenario_id) for scenario_id in expected} == expected
    assert set(SCENARIO_IDS) == set(found), "every offline scenario gets the metadata and render checks"


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_scenario_metadata(scenario_id: str) -> None:
    """A title, a description saying why, tags of the selection vocabulary (offline first), observed by the
    differential tier, offline marks only (never live)."""
    scenario = offline_scenarios()[scenario_id]
    assert scenario.title.strip() and len(scenario.description.split()) >= 20, "describe why the scenario exists"
    assert scenario.tags and scenario.tags[0] == "offline"
    assert set(scenario.tags) <= set(SCENARIO_TAGS), sorted(set(scenario.tags) - set(SCENARIO_TAGS))
    assert scenario.observe, "every offline scenario is recorded by tests/differential"
    names = {mark.name for mark in scenario_marks(scenario)}
    assert {"offline", "scenario", "tags", "timeout"} <= names and "live" not in names


@pytest.mark.parametrize("scenario_id", SCENARIO_IDS)
def test_scenario_renders_for_the_offline_organization(scenario_id: str) -> None:
    """Every step renders once (Jinja) into an org config, and a -BASE config for local-plan steps, with
    OfflineEngine's own variables and renderer; every object is named after the (offline) run context."""
    scenario, engine = offline_scenarios()[scenario_id], offline_engine()
    variables, renderer = engine.variables_for(scenario), engine.renderer_for(scenario)
    run_id = offline_run_context().run_id
    for step in scenario.steps:
        rendered = render_step(step, variables)
        for fragments in (rendered.fragments, rendered.base_fragments):
            if fragments is None:
                continue
            text = renderer.render(fragments, plan=engine.plan_for(scenario))
            assert f"orgs.newOrg('{OFFLINE_ORG}', '{OFFLINE_ORG}')" in text
            assert f'plan: "{engine.plan_for(scenario)}"' in text
            assert "{{" not in text and "{%" not in text
            for key, items in fragments.to_mapping().items():
                for snippet in items:
                    assert snippet.strip().rstrip(",") in text
                    if key not in UNNAMED_FRAGMENT_KEYS:
                        assert run_id in snippet.lower(), (
                            f"{scenario_id}/{step.name}: name objects with p, P or hook_base"
                        )


def test_local_plan_steps_check_their_counts() -> None:
    """local-plan scenarios assert all three Plan: counts (the numbers the apply -d guard relies on)."""
    for scenario_id in ("O-LPLAN-ADD", "O-LPLAN-CHANGE", "O-LPLAN-REMOVE"):
        (step,) = offline_scenarios()[scenario_id].steps
        assert step.base_fragments is not None and step.plan is not None
        assert step.plan.expect == "changes" and set(step.plan.counts) == {"add", "change", "delete"}


def test_canonical_diff_checks_content_and_an_empty_diff() -> None:
    """BAT-12: O-CANON checks what canonical-diff prints, not only its labels. The harness header is a removed line
    and the canonical import an added one. A file already in otterdog's canonical form gives an empty diff (no hunk).
    The label orientation (KB-010) and the bracketed words the canonical form drops (KB-050) are step-level known
    bugs of the commands phase only."""
    scenario, engine = offline_scenarios()["O-CANON"], offline_engine()
    steps = {step.name: step for step in scenario.steps}
    content = steps["canonical"].commands["canonical-diff"].contains
    assert any(text.startswith("-") for text in content) and any(text.startswith("+local orgs") for text in content)
    variables = engine.variables_for(scenario)
    configs = {}
    for name, bug in (("already-canonical", None), ("bracketed-description", "KB-050")):
        step = steps[name]
        assert step.known_bug == bug and step.known_bug_phases == (None if bug is None else ("commands",))
        assert "@@ " in step.commands["canonical-diff"].not_contains, f"{name}: an empty diff has no hunk"
        config = render_step(step, variables).config
        assert config is not None, f"{name}: a complete configuration file, written as it is"
        body = [line for line in config.splitlines() if not line.lstrip().startswith("#")]
        # canonical-diff drops the lines starting with '#' only: any other comment would show as a diff line
        assert not any("//" in line or "/*" in line for line in body), name
        assert body[0] == "local orgs = import 'vendor/template/otterdog-defaults.libsonnet';", name
        configs[name] = "\n".join(body)
    values = re.findall(r'"([^"]*)"', configs["already-canonical"])
    assert values and not any("[" in value for value in values), "the canonical form drops bracketed words (KB-050)"
    assert '"[e2e] canonical form"' in configs["bracketed-description"]
    assert steps["labels"].known_bug == "KB-010" and steps["labels"].known_bug_phases == ("commands",)


def test_sut_dependent_steps_leave_the_varying_expectation_out() -> None:
    """O-VAL-RULESET-STRICT/no-strict and O-VAL-ORG-RULESET-STRICT only record validation (their outcome depends on the SUT and is asserted
    by tests/offline/test_scenarios.py); the strict variant of O-VAL-RULESET-STRICT must pass on every SUT."""
    no_strict, with_strict = offline_scenarios()["O-VAL-RULESET-STRICT"].steps
    assert (no_strict.name, with_strict.name) == ("no-strict", "with-strict")
    assert no_strict.validate is None and no_strict.plan is not None and no_strict.plan.expect == "any"
    assert no_strict.base_fragments is not None, "local-plan must run: its abort on head is an expected delta"
    assert with_strict.validate is not None and with_strict.validate.ok is True
    assert with_strict.plan is not None and with_strict.plan.counts == {"add": 2, "change": 0, "delete": 0}
    org = offline_scenarios()["O-VAL-ORG-RULESET-STRICT"]
    (org_step,) = org.steps
    assert org_step.name == "org-no-strict" and org_step.validate is None and org.variables["plan"] == "enterprise"


# --- references --------------------------------------------------------------------------------------------------
def test_references_load_and_agree() -> None:
    """Every reference loads (YAML scenarios through the model, Python tests from their markers) and the references of
    one change never declare two bases or two templates; there is no PR manifest directory any more."""
    assert references(), "the repository's scenarios reference otterdog PRs"
    assert conflicts(references()) == []
    assert not (PROJECT / "scenarios" / "otterdog-prs").exists(), "one mechanism: the references of the scenarios"
    for entry in references():
        if entry.kind == "yaml":
            assert entry.reference in load_scenario(entry.source).references, entry


def test_scenarios_are_named_after_the_behaviour() -> None:
    """No scenario id or scenario file name carries the number of a PR it references (nor any PR-like number): the
    PR goes into the references."""
    by_id = {entry.scenario: entry for entry in references()}
    for scenario_id, entry in by_id.items():
        numbers = {str(item.reference.change.pr) for item in references() if item.scenario == scenario_id}
        assert not NUMBER_RE.search(scenario_id), f"{scenario_id}: name the behaviour, reference the PR"
        if entry.kind == "yaml":
            assert not set(NUMBER_RE.findall(entry.source.stem)) & numbers, entry.source
    for directory in ("offline", "cli", "regressions", "enterprise"):
        for path in scenario_files(PROJECT / "scenarios" / directory):
            assert not NUMBER_RE.search(path.stem), f"{path}: name the file after the behaviour"
            assert not NUMBER_RE.search(load_scenario(path).id), f"{path}: name the scenario after the behaviour"


def test_790_references_keep_the_manifest_expectations() -> None:
    """#790: base = first parent of the squash commit, template own, the two expected deltas on step no-strict of
    O-VAL-RULESET-STRICT, the org-ruleset crash (O-VAL-ORG-RULESET-STRICT) referenced WITHOUT an expected delta."""
    found = spec("790")
    assert found.base == f"sha:{BASE_790}" and found.template == "own"
    assert {"O-VAL-RULESET-STRICT", "O-VAL-ORG-RULESET-STRICT"} <= set(found.scenarios)
    assert {(d.scenario, d.step, d.kind, d.key) for d in found.expected_deltas} == {
        ("O-VAL-RULESET-STRICT", "no-strict", "cli", "validate"),
        ("O-VAL-RULESET-STRICT", "no-strict", "cli", "local-plan"),
    }
    assert all(delta.note for delta in found.expected_deltas)
    steps = {step.name for step in offline_scenarios()["O-VAL-RULESET-STRICT"].steps}
    assert {delta.step for delta in found.expected_deltas} <= steps


def test_792_and_check_merge_references_keep_the_manifest_expectations() -> None:
    """#792: the webapp test W-PR-STALE-SNAPSHOT with its expected delta, no base (merge base), template own; the
    named change check-merge: base v1.6.0, its expected delta on W-CMD-CHECK-MERGE, the comment markers in its note."""
    stale = spec("#792")
    assert stale.scenarios == ["W-PR-STALE-SNAPSHOT"] and stale.base is None and stale.template == "own"
    assert [(d.scenario, d.step, d.kind, d.key) for d in stale.expected_deltas] == [
        ("W-PR-STALE-SNAPSHOT", None, None, None)
    ]
    local = spec("check-merge")
    assert local.base == "tag:v1.6.0" and local.template == "own" and "W-CMD-CHECK-MERGE" in local.scenarios
    assert [d.scenario for d in local.expected_deltas] == ["W-CMD-CHECK-MERGE"]
    notes = " ".join(entry.reference.note for entry in local.referencing)
    assert "<!-- Otterdog Comment: check-merge -->" in notes and "<!-- Otterdog Comment: update-branch -->" in notes


def observation(role: str, scenario: str, step: str, key: str, content: str) -> Observation:
    """One cli observation of a side."""
    return Observation(f"sha-{role}", role, scenario, step, "cli", key, content)


def test_790_references_classify_the_proof_of_concept() -> None:
    """Base b5f7bb1 vs head 9bdeb75: the #790 validate/local-plan changes are expected, the org-ruleset crash stays
    unexpected, an unchanged observation is no delta, and no expected delta is missing."""
    found = spec("790")
    ok = "exit_code: 0\n  Validation succeeded\n"
    base = [
        observation("base", "O-VAL-RULESET-STRICT", "no-strict", "validate", ok),
        observation("base", "O-VAL-RULESET-STRICT", "no-strict", "local-plan", "exit_code: 0\n  Plan: 2 to add\n"),
        observation("base", "O-VAL-RULESET-STRICT", "with-strict", "validate", ok),
        observation("base", "O-VAL-ORG-RULESET-STRICT", "org-no-strict", "validate", ok),
    ]
    head = [
        observation("head", "O-VAL-RULESET-STRICT", "no-strict", "validate", "exit_code: 1\nError: ... 'strict'.\n"),
        observation("head", "O-VAL-RULESET-STRICT", "no-strict", "local-plan", "exit_code: 1\nError: ... 'strict'.\n"),
        observation("head", "O-VAL-RULESET-STRICT", "with-strict", "validate", ok),
        observation(
            "head", "O-VAL-ORG-RULESET-STRICT", "org-no-strict", "validate", "exit_code: 2\nError: AttributeError\n"
        ),
    ]
    report = compare(base, head, base_label="sha-b5f7bb1", head_label="sha-9bdeb75", expected=found.expected_deltas)
    assert sorted((d.scenario, d.key) for d in report.expected()) == [
        ("O-VAL-RULESET-STRICT", "local-plan"),
        ("O-VAL-RULESET-STRICT", "validate"),
    ]
    assert [(d.scenario, d.key) for d in report.unexpected()] == [("O-VAL-ORG-RULESET-STRICT", "validate")]
    assert report.unchanged == 1 and report.unmatched_expected == [] and report.not_comparable == []
