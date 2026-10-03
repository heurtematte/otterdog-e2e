"""The repository's jsonnet files (scenarios/lib, scenarios/fragments) and the scenarios that use them.

Library helpers compute names in jsonnet, out of reach of the regular expressions of test_yaml_cli.py. Every step of
every live scenario is therefore manifested (jsonnet on the vendored template copy, baseline of a fake target): each
organization-level object and repository beyond the baseline must carry this run's prefix and every webhook URL must
lie under the run's hook base, wherever it was written (inline, fragment file, library, overlay). The shared files are
all used (by a scenario or a documented inject recipe) and each recipe renders and manifests for the offline
organization (the offline tier validates them with otterdog: scenario lint and ``otterdog-e2e inject``).
"""

from __future__ import annotations

import json
import shutil
from functools import cache
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e import procs
from otterdog_e2e.inject import InjectRequest, write_adhoc_scenario
from otterdog_e2e.naming import extract_run_id, new_run_context
from otterdog_e2e.otterdog.render import OrgConfigRenderer, build_baseline, org_profile
from otterdog_e2e.scenarios.collect import collect_scenarios
from otterdog_e2e.scenarios.model import Scenario, load_adhoc_scenario, render_step
from otterdog_e2e.scenarios.offline import OFFLINE_ORG, OfflineEngine, offline_run_context
from otterdog_e2e.settings import IDENTITY_ROLES
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FAKE_MARKER, FAKE_ORG, FakeCli, default_org_json, make_target

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
LIBRARY = SCENARIOS / "lib" / "e2e.libsonnet"
FRAGMENTS = SCENARIOS / "fragments"
DOCS = (ROOT / "docs" / "writing-scenarios.md", ROOT / "docs" / "local-development.md")
TEMPLATE_DIR = ROOT / "tests" / "unit" / "data" / "template"
JSONNET = shutil.which("jsonnet")
SAMPLE_RUN = new_run_context("t3c7z8a5")
LIVE_DIRS = ("cli", "regressions", "enterprise")
# scenarios converted to the shared files (documented examples of docs/writing-scenarios.md)
EXAMPLES = {"cli.environment": "environment-repo.jsonnet", "cli.neg.private-bpr": None}
# documented inject recipes (docs/local-development.md) -> request
RECIPES: dict[str, InjectRequest] = {
    "basic": InjectRequest(fragments=[("repositories", FRAGMENTS / "repo-basic.jsonnet")]),
    "ruleset": InjectRequest(
        fragments=[("repositories", FRAGMENTS / "ruleset-repo.jsonnet")], libraries=[("e2e", LIBRARY)]
    ),
    "variable": InjectRequest(fragments=[("variables", FRAGMENTS / "org-variable.jsonnet")]),
    "overlay": InjectRequest(
        fragments=[("repositories", FRAGMENTS / "repo-basic.jsonnet")],
        overlays=[FRAGMENTS / "overlay-run-topics.jsonnet"],
    ),
    "environment": InjectRequest(
        fragments=[("repositories", FRAGMENTS / "environment-repo.jsonnet")],
        libraries=[("e2e", LIBRARY)],
        variables={"wait_timer": 5, "branch_policies": ["main"]},
    ),
    "config": InjectRequest(config=FRAGMENTS / "offline-config.jsonnet", base=FRAGMENTS / "offline-config.jsonnet"),
}


@cache
def live_scenarios() -> tuple[Scenario, ...]:
    """Every live scenario of the repository."""
    return tuple(collect_scenarios([SCENARIOS / name for name in LIVE_DIRS]))


def manifest(text: str, root: Path, org: str) -> dict[str, Any]:
    """Manifest a rendered org config with jsonnet against the vendored template copy."""
    org_dir = root / "orgs" / org
    if not (org_dir / "vendor" / "template").is_dir():
        shutil.copytree(TEMPLATE_DIR, org_dir / "vendor" / "template")
    config = org_dir / f"{org}.jsonnet"
    config.write_text(text, encoding="utf-8")
    completed = procs.run([str(JSONNET), config.name], cwd=org_dir, timeout=60, home=root / "home")
    assert completed.returncode == 0, completed.stderr[-2000:]
    data: dict[str, Any] = json.loads(completed.stdout)
    return data


def live_variables(scenario: Scenario) -> dict[str, Any]:
    """Jinja variables of a live render (sample run), the scenario's variables last."""
    return {
        **SAMPLE_RUN.template_vars(),
        "org": FAKE_ORG,
        "plan": "free",
        "logins": {role: f"e2e-sample-{role.replace('_', '-')}" for role in IDENTITY_ROLES},
        "app_slug": "e2e-sample-app",
        "app_id": "123456",
        "teams": {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"},
        **scenario.variables,
    }


def foreign_objects(org: dict[str, Any], baseline: dict[str, Any], run_id: str, hook_base: str) -> list[str]:
    """Objects of a manifested org without the run prefix (beyond the baseline) and webhooks outside the hook base."""
    problems = []
    known = {key: {item["name"] for item in baseline.get(key, [])} for key in ("repositories", "teams")}
    for key in ("repositories", "teams", "secrets", "variables", "rulesets", "roles"):
        for item in org.get(key, []):
            name = item.get("name", "")
            if name not in known.get(key, set()) and extract_run_id(name) != run_id:
                problems.append(f"{key}: {name}")
    for prop in org["settings"].get("custom_properties", []):
        if extract_run_id(prop["name"]) != run_id:
            problems.append(f"custom property: {prop['name']}")
    hooks = [hook["url"] for hook in org.get("webhooks", [])]
    hooks += [hook["url"] for repo in org.get("repositories", []) for hook in repo.get("webhooks", [])]
    problems += [f"webhook: {url}" for url in hooks if not url.startswith(hook_base)]
    return problems


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
def test_every_live_step_creates_run_prefixed_objects_only(tmp_path: Path) -> None:
    """Whatever wrote it (inline jsonnet, a fragment file, a library helper, an overlay), each object a live step
    adds carries this run's id: the guarded cleanup and the janitor can remove all of them."""
    target = make_target()
    renderer = OrgConfigRenderer(
        template=offline_template(),
        org=FAKE_ORG,
        plan="free",
        org_profile=org_profile(default_org_json()),
        baseline=build_baseline(target, SAMPLE_RUN),
        marker=FAKE_MARKER,
        hide_cache_limit=True,
    )
    baseline = manifest(renderer.render(), tmp_path, FAKE_ORG)
    problems = []
    for scenario in live_scenarios():
        for step in scenario.steps:
            rendered = render_step(step, live_variables(scenario))
            org = manifest(renderer.render(rendered.fragments, plan=scenario.plan_override), tmp_path, FAKE_ORG)
            found = foreign_objects(org, baseline, SAMPLE_RUN.run_id, SAMPLE_RUN.hook_base)
            problems += [f"{scenario.id}/{step.name}: {problem}" for problem in found]
    assert not problems, problems


def test_converted_examples_use_the_shared_files() -> None:
    """The documented examples load the library (and the shared fragment) from the repository files."""
    by_id = {scenario.id: scenario for scenario in live_scenarios()}
    for scenario_id, fragment in EXAMPLES.items():
        scenario = by_id[scenario_id]
        assert scenario.libraries["e2e"].origin.display == "scenarios/lib/e2e.libsonnet"
        if fragment is not None:
            files = [
                snippet.origin.display
                for step in scenario.steps
                for snippet in step.fragments.repositories
                if hasattr(snippet, "origin")
            ]
            assert files and set(files) == {f"scenarios/fragments/{fragment}"}, files


def test_every_shared_file_is_used() -> None:
    """Each file of scenarios/lib and scenarios/fragments is used by a scenario or an inject recipe and documented."""
    used = {Path(scenario.libraries[name].origin.path) for scenario in live_scenarios() for name in scenario.libraries}
    for scenario in live_scenarios():
        for step in scenario.steps:
            for snippets in step.fragments.to_mapping().values():
                used |= {Path(snippet.origin.path) for snippet in snippets if hasattr(snippet, "origin")}
    for request in RECIPES.values():
        used |= {path for _, path in [*request.fragments, *request.libraries]} | set(request.overlays)
        used |= {path for path in (request.config, request.base) if path is not None}
    docs = "\n".join(path.read_text(encoding="utf-8") for path in DOCS)
    for path in sorted([*FRAGMENTS.glob("*"), *(SCENARIOS / "lib").glob("*")]):
        assert path.resolve() in {item.resolve() for item in used}, f"{path.relative_to(ROOT)} is not used"
        assert str(path.relative_to(ROOT)) in docs, f"{path.relative_to(ROOT)} is not documented"


def offline_engine() -> OfflineEngine:
    """An OfflineEngine over a fake CLI: the variables and renderer of the offline tier."""
    workspace = SimpleNamespace(org=OFFLINE_ORG, project=OFFLINE_ORG, template=offline_template())
    return OfflineEngine(
        cli=FakeCli(org=OFFLINE_ORG),  # type: ignore[arg-type]
        workspace=workspace,  # type: ignore[arg-type]
        template_src=Path("/nonexistent"),
        run_ctx=offline_run_context(),
    )


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
@pytest.mark.parametrize("recipe", sorted(RECIPES))
def test_inject_recipes_render_for_the_offline_organization(recipe: str, tmp_path: Path) -> None:
    """Each documented recipe loads as an ad-hoc scenario and manifests: run-prefixed objects, overlay applied."""
    scenario = load_adhoc_scenario(write_adhoc_scenario(RECIPES[recipe], tmp_path / "adhoc"))
    engine = offline_engine()
    rendered = render_step(scenario.steps[0], engine.variables_for(scenario))
    text = rendered.config or engine.renderer_for(scenario).render(rendered.fragments, plan=engine.plan_for(scenario))
    org = manifest(text, tmp_path, OFFLINE_ORG)
    run = offline_run_context()
    assert not foreign_objects(org, {}, run.run_id, run.hook_base)
    names = [item["name"] for key in ("repositories", "variables") for item in org.get(key, [])]
    assert names and all(extract_run_id(name) == run.run_id for name in names)
    if recipe == "overlay":
        assert org["repositories"][0]["topics"] == ["otterdog-e2e", "e2e-overlay"]
    if recipe == "environment":
        (environment,) = org["repositories"][0]["environments"]
        assert (environment["wait_timer"], environment["branch_policies"]) == (5, ["main"])
