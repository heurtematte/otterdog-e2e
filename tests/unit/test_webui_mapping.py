"""The table of the 12 web-only org settings (webui.mapping) against vendored otterdog sources and the REST OpenAPI."""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

import pytest

from otterdog_e2e.webui import mapping
from otterdog_e2e.webui.mapping import (
    EXPECTED_UNREAD,
    REST_FIELDS,
    REST_READABLE,
    TRUSTED_READER_ONLY,
    WEB_KEYS,
    WEB_SETTINGS,
    WRITABLE,
    WebDefinition,
    definition_problems,
    differences,
    jsonnet_fields,
    parse_web_definitions,
    rest_values,
    schema_web_keys,
    source_problems,
    web_setting,
)

DATA = Path(__file__).parent / "data" / "webui"
TEMPLATE = Path(__file__).parent / "data" / "template" / "otterdog-defaults.libsonnet"


def definitions() -> dict[str, WebDefinition]:
    """Definitions of the vendored github-web-settings.jsonnet."""
    return parse_web_definitions((DATA / "github-web-settings.jsonnet").read_text(encoding="utf-8"))


def schema_keys() -> list[str]:
    """Web keys of the vendored settings schema."""
    return schema_web_keys(json.loads((DATA / "settings.schema.json").read_text(encoding="utf-8")))


def test_table_matches_the_vendored_otterdog_sources() -> None:
    """No drift between the table and otterdog main 9bdeb75 (schema web keys, pages, inputs, the known mismatch)."""
    assert definition_problems(definitions(), schema_keys()) == []
    assert schema_keys() == list(WEB_KEYS)


def test_twelve_settings_seven_readable_through_rest() -> None:
    """7 REST-readable settings, 5 for the trusted reader only, two_factor_requirement read-only."""
    assert len(WEB_SETTINGS) == 12 and len(set(WEB_KEYS)) == 12
    assert set(REST_READABLE) == {
        "two_factor_requirement",
        "members_can_create_teams",
        "members_can_change_repo_visibility",
        "members_can_delete_repositories",
        "members_can_delete_issues",
        "readers_can_create_discussions",
        "default_branch_name",
    }
    assert set(TRUSTED_READER_ONLY) == {
        "packages_containers_public",
        "packages_containers_internal",
        "has_discussions",
        "discussion_source_repository",
        "members_can_change_project_visibility",
    }
    assert REST_FIELDS["two_factor_requirement"] == "two_factor_requirement_enabled"
    assert REST_FIELDS["default_branch_name"] == "default_repository_branch"
    assert set(WRITABLE) == set(WEB_KEYS) - {"two_factor_requirement"}


def test_rest_fields_are_readable_but_not_writable_through_rest() -> None:
    """Every REST field is a property of organization-full; none is accepted by PATCH /orgs/{org}."""
    fields = json.loads((DATA / "orgs-org-fields.json").read_text(encoding="utf-8"))
    get, patch = set(fields["get_orgs_org"]), set(fields["patch_orgs_org"])
    assert set(REST_FIELDS.values()) <= get
    assert not set(REST_FIELDS.values()) & patch
    assert not set(TRUSTED_READER_ONLY) & get, "a trusted-reader-only setting became readable through REST"


def test_two_factor_requirement_is_never_read_nor_toggled() -> None:
    """Its web definition is named two_factor_required (never loaded) and the model marks it read-only."""
    setting = web_setting("two_factor_requirement")
    assert not setting.writable and not setting.read_by_otterdog and setting.web_name == "two_factor_required"
    assert frozenset({"two_factor_requirement"}) == EXPECTED_UNREAD
    assert "two_factor_required" in definitions() and "two_factor_requirement" not in definitions()
    assert all(s.read_by_otterdog for s in WEB_SETTINGS if s.key != "two_factor_requirement")


def test_plans_parents_and_optional_settings() -> None:
    """Internal packages need Enterprise; the discussion source follows has_discussions; readers' flag optional."""
    assert web_setting("packages_containers_internal").plans == ("enterprise",)
    assert not web_setting("packages_containers_internal").applicable("free")
    assert web_setting("packages_containers_public").applicable("free")
    assert web_setting("discussion_source_repository").parent == "has_discussions"
    assert definitions()["discussion_source_repository"].parent == "has_discussions"
    assert definitions()["has_discussions"].delay_save == "discussion_source_repository"
    assert web_setting("readers_can_create_discussions").optional and definitions()["readers_can_create_discussions"]
    assert definitions()["readers_can_create_discussions"].optional
    with pytest.raises(KeyError, match="not a web setting"):
        web_setting("billing_email")


def test_template_declares_every_web_setting() -> None:
    """The vendored upstream template sets a default for each web setting (otterdog only reads included keys)."""
    text = TEMPLATE.read_text(encoding="utf-8")
    new_org = text[text.index("local newOrg(") :]
    for key in WEB_KEYS:
        assert re.search(rf"^\s*{key}:", new_org, flags=re.MULTILINE), key


def test_rest_values() -> None:
    """GET /orgs/{org} fields keyed by the otterdog key; absent fields (non-owner token) are left out."""
    org = {
        "login": "o",
        "two_factor_requirement_enabled": False,
        "members_can_create_teams": True,
        "default_repository_branch": "main",
        "members_can_delete_issues": None,
    }
    assert rest_values(org) == {
        "two_factor_requirement": False,
        "members_can_create_teams": True,
        "default_branch_name": "main",
        "members_can_delete_issues": None,
    }
    assert rest_values({"login": "o"}) == {}


def test_jsonnet_fields_pin_writable_settings_in_table_order() -> None:
    """``key::: <json>`` (visible even when hidden by the baseline), read-only keys never rendered, unknown keys fail."""
    fields = jsonnet_fields(
        {
            "has_discussions": True,
            "two_factor_requirement": True,
            "discussion_source_repository": "o/r",
            "members_can_create_teams": False,
            "default_branch_name": "e2e-t3c7z8a5",
        }
    )
    assert fields == [
        "members_can_create_teams::: false",
        'default_branch_name::: "e2e-t3c7z8a5"',
        "has_discussions::: true",
        'discussion_source_repository::: "o/r"',
    ]
    assert jsonnet_fields({"discussion_source_repository": None}) == ["discussion_source_repository::: null"]
    with pytest.raises(KeyError):
        jsonnet_fields({"plan": "free"})


def test_differences() -> None:
    """Value mismatches and unread keys, restricted to the given keys."""
    expected = {"a_key": True, "b_key": "x", "c_key": None}
    assert differences(expected, {"a_key": True, "b_key": "y"}) == [
        'b_key: expected "x", got "y"',
        "c_key: expected null, not read",
    ]
    assert differences(expected, {"a_key": False}, ["a_key"]) == ["a_key: expected true, got false"]
    assert differences({}, {"a_key": 1}) == []


def test_definition_problems_report_drift() -> None:
    """Added/removed schema keys, moved or renamed inputs, a fixed definition name and new definitions are reported."""
    defs = definitions()
    keys = schema_keys()
    assert any("added ['new_setting']" in p for p in definition_problems(defs, [*keys, "new_setting"]))
    assert any(
        "removed ['members_can_create_teams']" in p
        for p in definition_problems(defs, [k for k in keys if k != "members_can_create_teams"])
    )
    moved = dict(
        defs,
        members_can_delete_issues=WebDefinition(
            "members_can_delete_issues", "settings/other", "checkbox", "members_can_delete_issues"
        ),
    )
    assert any("defined on settings/other" in p for p in definition_problems(moved, keys))
    renamed = dict(
        defs,
        packages_containers_public=WebDefinition(
            "packages_containers_public", "settings/packages", "checkbox", "packages[public]"
        ),
    )
    assert any("packages[public]" in p for p in definition_problems(renamed, keys))
    fixed = dict(
        defs, two_factor_requirement=WebDefinition("two_factor_requirement", "settings/security", "checkbox", "x")
    )
    assert any("never read by otterdog" in p for p in definition_problems(fixed, keys))
    extra = dict(defs, brand_new=WebDefinition("brand_new", "settings/new", "checkbox", "brand_new"))
    assert any("unknown to the harness table: ['brand_new']" in p for p in definition_problems(extra, keys))


def test_parse_web_definitions_inputs() -> None:
    """Input types and names of the definition helpers (quoted names with brackets included)."""
    defs = definitions()
    assert defs["packages_containers_public"].input_name == "packages[containers][public]"
    assert defs["default_branch_name"].input_type == "text"
    assert defs["discussion_source_repository"].input_type == "select-menu"
    assert defs["default_workflow_permissions"].input_type == "radio"
    assert defs["members_can_change_project_visibility"].page == mapping.PROJECTS


def test_source_problems_of_a_source_tree(tmp_path: Path) -> None:
    """A source tree with the vendored files has no problem; missing files are reported, not raised."""
    resources = tmp_path / "otterdog" / "resources"
    (resources / "schemas").mkdir(parents=True)
    shutil.copy(DATA / "github-web-settings.jsonnet", resources / "github-web-settings.jsonnet")
    shutil.copy(DATA / "settings.schema.json", resources / "schemas" / "settings.json")
    assert source_problems(tmp_path) == []
    assert source_problems(tmp_path / "missing")[0].startswith("cannot read the web settings of")
