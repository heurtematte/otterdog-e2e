"""cli.import.custom-properties (regression.import-multiple-custom-properties): ``import`` of an organization holding
several custom property definitions and a repository with values for each of them round-trips.

v1.0.1 (CHANGELOG "importing an organization with several custom properties"): the import writes every definition
into settings.custom_properties (models/organization_settings.py:222-239, orgs.newCustomProperty blocks) and the
repository values into the repository's custom_properties. The test creates three run definitions (single_select,
string, true_false) and a public run repository with a value for each, imports the organization (``import -f -n``)
into a fresh workspace, checks that the import declares the three definitions and the three values, cuts the three
definition blocks and the repository block out of the imported jsonnet (one 'orgs.<function>('<name>') {' ...
'},' block per object at one indentation level) and plans them with the session's baseline: nothing may change.
Planning the blocks with the regular baseline keeps organization-level import issues (KB-024) out of the round trip.
Property names use '-' (KB-016).
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest
import yaml

from otterdog_e2e.scenarios.model import load_scenario

if TYPE_CHECKING:
    from pathlib import Path

    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.scenarios.engine import ScenarioEngine
    from otterdog_e2e.scenarios.model import Scenario
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli", "custom-properties", "repo")]

SCENARIO_ID = "cli.import.custom-properties"
REPO_SLUG = "imp-props"
PROPERTY_SLUGS = ("imp-tier", "imp-owner", "imp-flag")

CREATE_YAML = """\
id: cli.import.custom-properties
tier: cli
title: Custom property definitions and values for the import round trip
priority: P2
requires: [custom_properties]
tags: [custom-properties, repo]
steps:
  - name: create
    fragments:
      custom_properties:
        - |
          orgs.newCustomProperty('{{ p }}-imp-tier') {
            value_type: "single_select",
            values_editable_by: "org_actors",
            allowed_values: ["gold", "silver"],
            description: "otterdog e2e: import tier",
          }
        - |
          orgs.newCustomProperty('{{ p }}-imp-owner') {
            value_type: "string",
            values_editable_by: "org_actors",
          }
        - |
          orgs.newCustomProperty('{{ p }}-imp-flag') {
            value_type: "true_false",
            values_editable_by: "org_actors",
          }
      repositories:
        - |
          orgs.newRepo('{{ p }}-imp-props') {
            description: "otterdog e2e: import of custom properties",
            custom_properties: {
              "{{ p }}-imp-tier": "silver",
              "{{ p }}-imp-owner": "otterdog-e2e",
              "{{ p }}-imp-flag": "true",
            },
          }
    plan:
      expect: changes
      contains:
        - '+ add custom_property[name="{{ p }}-imp-tier"]'
        - '+ add custom_property[name="{{ p }}-imp-owner"]'
        - '+ add custom_property[name="{{ p }}-imp-flag"]'
        - '+ add repository[name="{{ p }}-imp-props"]'
      counts: {add: 4, change: 0, delete: 0}
    state:
      - kind: repo_custom_properties
        repo: "{{ p }}-imp-props"
        match: {"{{ p }}-imp-tier": silver, "{{ p }}-imp-owner": otterdog-e2e, "{{ p }}-imp-flag": "true"}
"""


def inline_scenario(path: Path, document: str | dict) -> Scenario:
    """The scenario of ``document`` (YAML text or a mapping) loaded with the strict scenario model from ``path``."""
    text = document if isinstance(document, str) else yaml.safe_dump(document, sort_keys=False, width=1000)
    path.write_text(text, encoding="utf-8")
    return load_scenario(path)


def object_block(text: str, function: str, name: str) -> str:
    """The 'orgs.<function>('<name>') { ... }' block of an imported configuration, without its trailing comma."""
    lines = text.splitlines()
    pattern = re.compile(rf"^(\s*)orgs\.{re.escape(function)}\('{re.escape(name)}'\)")
    for index, line in enumerate(lines):
        match = pattern.match(line)
        if match is None:
            continue
        closing = f"{match.group(1)}}},"
        for end in range(index + 1, len(lines)):
            if lines[end] == closing:
                return "\n".join([*lines[index:end], f"{match.group(1)}}}"])
        raise AssertionError(f"the imported block of {name} has no closing line {closing!r}")
    raise AssertionError(f"the import does not declare orgs.{function}('{name}')")


def raw(block: str) -> str:
    """A fragment inserted verbatim (Jinja never interprets the imported text)."""
    return "{% raw %}" + block + "{% endraw %}"


@pytest.mark.scenario(SCENARIO_ID)
@pytest.mark.requires("custom_properties")
@pytest.mark.timeout(1200)
def test_imported_custom_properties_plan_no_change(
    scenario_engine: ScenarioEngine,
    e2e: E2EContext,
    sut: InstalledCli,
    template_ref: TemplateRef,
    run_ctx: RunContext,
    tmp_path: Path,
) -> None:
    """The import declares the three definitions and the repository values, and planning them changes nothing."""
    create = inline_scenario(tmp_path / "create.yaml", CREATE_YAML)
    reason = scenario_engine.skip_reason(create)
    if reason:
        pytest.skip(reason)
    properties = [run_ctx.name(slug) for slug in PROPERTY_SLUGS]
    repo = run_ctx.name(REPO_SLUG)
    failed = False
    try:
        scenario_engine.run(create, cleanup=False)
        workspace = e2e.workspace(e2e.unique_name("import-custom-properties"), template_ref)
        cli = e2e.cli(sut, workspace, name=f"ws-{workspace.root.name}")
        cli.import_config(force=True).assert_ok("import -f -n")
        text = workspace.read_org_config()
        definitions = [object_block(text, "newCustomProperty", name) for name in properties]
        assert '"single_select"' in definitions[0] and '"gold"' in definitions[0], definitions[0]
        assert '"true_false"' in definitions[2], definitions[2]
        block = object_block(text, "newRepo", repo)
        values = [f'"{properties[0]}": "silver"', f'"{properties[1]}": "otterdog-e2e"', f'"{properties[2]}": "true"']
        missing = [value for value in values if value not in block]
        assert not missing, f"the imported block of {repo} lacks the values {missing}:\n{block}"
        roundtrip = {
            "id": SCENARIO_ID,
            "tier": "cli",
            "title": "Imported custom properties plan no change",
            "priority": "P2",
            "tags": ["custom-properties", "repo"],
            "steps": [
                {
                    "name": "roundtrip",
                    "fragments": {
                        "custom_properties": [raw(definition) for definition in definitions],
                        "repositories": [raw(block)],
                    },
                    "validate": {"ok": True},
                    "plan": {"expect": "noop"},
                }
            ],
        }
        scenario_engine.run(inline_scenario(tmp_path / "roundtrip.yaml", roundtrip), cleanup=False)
    except BaseException:
        failed = True
        raise
    finally:
        try:
            scenario_engine.cleanup(create)
        except Exception as exc:
            if not failed:
                raise AssertionError(f"cleanup of {create.id} failed: {type(exc).__name__}: {exc}") from exc
