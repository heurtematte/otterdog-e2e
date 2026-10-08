"""Editor schema of the scenario YAML format (.vscode/scenario.schema.json, VS Code YAML extension).

The committed schema must equal scenarios.model.json_schema(), every scenario of the repository must validate against
it (an editor must never flag a scenario the loader accepts), and .vscode/settings.json must map the scenario
directories to it and the other YAML files under scenarios/ to the permissive schema.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from otterdog_e2e.scenarios.model import (
    SCENARIO_KEYS,
    SCHEMA_FILE,
    STEP_KEYS,
    json_schema,
    scenario_files,
)

ROOT = Path(__file__).resolve().parents[2]
SCENARIOS = ROOT / "scenarios"
REGENERATE = (
    ".venv/bin/python -c 'import json; from otterdog_e2e.scenarios.model import json_schema; "
    f"print(json.dumps(json_schema(), indent=2))' > {SCHEMA_FILE}"
)
JSON_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def problems(value: Any, schema: dict[str, Any], where: str = "$") -> list[str]:
    """Violations of the draft-07 subset json_schema() uses (type, enum, pattern, properties, items, oneOf, ...)."""
    if "oneOf" in schema:
        matching = [option for option in schema["oneOf"] if not problems(value, option, where)]
        return [] if len(matching) == 1 else [f"{where}: {len(matching)} oneOf alternatives match"]
    found: list[str] = []
    types = schema.get("type")
    if types is not None:
        allowed = [types] if isinstance(types, str) else types
        is_bool = isinstance(value, bool)
        if not any(isinstance(value, JSON_TYPES[name]) and (name == "boolean" or not is_bool) for name in allowed):
            return [f"{where}: {type(value).__name__} is not {allowed}"]
    if "enum" in schema and value not in schema["enum"]:
        found.append(f"{where}: {value!r} not in enum")
    if isinstance(value, str) and "pattern" in schema and not re.search(schema["pattern"], value):
        found.append(f"{where}: {value!r} does not match {schema['pattern']}")
    if isinstance(value, int) and not isinstance(value, bool) and value < schema.get("minimum", value):
        found.append(f"{where}: {value} < minimum")
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        found += [f"{where}: missing {key!r}" for key in schema.get("required", []) if key not in value]
        for key, item in value.items():
            if key in properties:
                found += problems(item, properties[key], f"{where}.{key}")
            elif schema.get("additionalProperties", True) is False:
                found.append(f"{where}: unexpected key {key!r}")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0):
            found.append(f"{where}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for index, item in enumerate(value):
                found += problems(item, schema["items"], f"{where}[{index}]")
    return found


def test_committed_schema_is_up_to_date() -> None:
    """The committed file is exactly json_schema() (regenerate it after changing the scenario format)."""
    committed = json.loads((ROOT / SCHEMA_FILE).read_text(encoding="utf-8"))
    assert committed == json_schema(), f"{SCHEMA_FILE} is stale, regenerate it: {REGENERATE}"


def test_schema_covers_the_loader_keys() -> None:
    """Top-level and step keys of the schema are exactly the keys the loader accepts."""
    schema = json_schema()
    assert list(schema["properties"]) == list(SCENARIO_KEYS)
    assert list(schema["properties"]["steps"]["items"]["properties"]) == list(STEP_KEYS)


@pytest.mark.parametrize(
    "path",
    [path for name in ("offline", "cli", "enterprise") for path in scenario_files(SCENARIOS / name)],
    ids=lambda path: str(path.relative_to(SCENARIOS)),
)
def test_every_scenario_validates_against_the_schema(path: Path) -> None:
    """No repository scenario gets an editor error."""
    assert problems(yaml.safe_load(path.read_text(encoding="utf-8")), json_schema()) == []


def test_schema_rejects_what_the_loader_rejects() -> None:
    """Unknown keys, bad enums and a step-less scenario are flagged (the schema is not a no-op)."""
    schema = json_schema()
    assert problems({"id": "x", "title": "t", "steps": [{"fragments": {}}], "bogus": 1}, schema)
    assert problems({"id": "x", "title": "t", "steps": [{"plan": {"expect": "maybe"}}]}, schema)
    assert problems({"id": "x", "title": "t", "steps": []}, schema)
    assert problems({"id": "x", "title": "t", "steps": [{"state": [{"kind": "nope"}]}]}, schema)


def test_schema_knows_the_file_forms() -> None:
    """File references, libraries, overlays and offline config files validate; a file reference with unknown keys
    or without ``file`` does not."""
    schema = json_schema()
    ref = {"file": "../fragments/repo.jsonnet", "raw": False, "vars": {"slug": "a"}}
    step = {
        "fragments": {"repositories": ["orgs.newRepo('x')", ref], "variables": ref},
        "overlay": [ref, "{ a:: 1 }"],
        "base_config": ref,
        "config": None,
    }
    scenario = {"id": "x", "title": "t", "libraries": {"e2e": "../lib/e2e.libsonnet", "more": ref}, "steps": [step]}
    assert problems(scenario, schema) == []
    assert problems({"id": "x", "title": "t", "steps": [{"overlay": {"path": "x"}}]}, schema)
    assert problems({"id": "x", "title": "t", "steps": [{"config": {"raw": True}}]}, schema)
    assert problems({"id": "x", "title": "t", "steps": [{"fragments": {"repositories": [{"vars": {}}]}}]}, schema)


def test_vscode_maps_scenario_files_to_the_schemas() -> None:
    """settings.json maps the scenario directories to the schema, known_bugs.yaml and the coverage matrix to a
    permissive one (otherwise SchemaStore's unrelated CrowdSec 'scenario' schema reports false errors)."""
    settings = json.loads((ROOT / ".vscode" / "settings.json").read_text(encoding="utf-8"))
    mapping = settings["yaml.schemas"]
    assert set(mapping[f"./{SCHEMA_FILE}"]) == {
        f"scenarios/{name}/**/*.yaml" for name in ("offline", "cli", "enterprise")
    }  # '**' spans the domain subdirectories (scenarios/<tier>/<domain>/<file>.yaml)
    assert set(mapping["./.vscode/any.schema.json"]) == {
        "scenarios/known_bugs.yaml",
        "scenarios/coverage.yaml",
    }
    permissive = json.loads((ROOT / ".vscode" / "any.schema.json").read_text(encoding="utf-8"))
    assert set(permissive) <= {"$schema", "title", "description"}, "the permissive schema must accept anything"
