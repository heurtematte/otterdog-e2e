"""The 12 web-only organization settings of otterdog and their independent oracles (docs/web-ui-testing.md).

Verified against otterdog main 9bdeb75 and v1.6.1 (identical files): the settings schema
(``otterdog/resources/schemas/settings.json``, ``"provider": "web"``), the web client definitions
(``otterdog/resources/github-web-settings.jsonnet``: page, input, optional, parent), the model
(``otterdog/models/organization_settings.py``: ``two_factor_requirement`` is read-only) and the GitHub REST OpenAPI
description (``components.schemas.organization-full``: what ``GET /orgs/{org}`` returns to an owner token with
``admin:org``; ``PATCH /orgs/{org}`` accepts none of these fields, so REST is a read-only oracle here).

Findings the table encodes:

* 7 settings are readable through REST: ``two_factor_requirement`` (``two_factor_requirement_enabled``),
  ``members_can_create_teams``, ``members_can_change_repo_visibility``, ``members_can_delete_repositories``,
  ``members_can_delete_issues``, ``readers_can_create_discussions`` and ``default_branch_name``
  (``default_repository_branch``);
* the 5 others (``packages_containers_public``, ``packages_containers_internal``, ``has_discussions``,
  ``discussion_source_repository``, ``members_can_change_project_visibility``) only exist on settings pages: a trusted
  otterdog reads them (oracle.TrustedWebReader);
* ``two_factor_requirement`` is never read by otterdog's web client: its definition is named ``two_factor_required``,
  so the security page is never loaded (``WebClient._get_pages`` matches definition names against the schema keys)
  and the value stays UNSET; the model marks it read-only. The harness never toggles it either: requiring 2FA removes
  every member without 2FA from the organization;
* ``packages_containers_internal`` needs internal visibility (Enterprise Cloud); ``discussion_source_repository``
  only counts while ``has_discussions`` is true (``<org>/<repo>``, a public repository of the org);
* the definition file also lists ``default_workflow_permissions`` (settings/actions), which is managed through REST
  (``workflows``) and is not a web setting of the schema.

source_problems() re-checks the table against the source of any otterdog build (the SUT under test), so a release
that adds, renames or fixes a web setting is reported instead of silently ignored.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from otterdog_e2e.capabilities import PLANS

MEMBER_PRIVILEGES = "settings/member_privileges"
SECURITY = "settings/security"
REPOSITORY_DEFAULTS = "settings/repository-defaults"
PACKAGES = "settings/packages"
DISCUSSIONS = "settings/discussions"
PROJECTS = "settings/projects"
WEB_SETTINGS_FILE = Path("otterdog") / "resources" / "github-web-settings.jsonnet"
SETTINGS_SCHEMA_FILE = Path("otterdog") / "resources" / "schemas" / "settings.json"
# definitions of github-web-settings.jsonnet that are not web settings of the schema (managed through REST)
KNOWN_EXTRA_DEFINITIONS = frozenset({"default_workflow_permissions"})
# schema web keys otterdog's web reader never loads (definition name mismatch, see the module docstring)
EXPECTED_UNREAD = frozenset({"two_factor_requirement"})
_ENTRY_RE = re.compile(r"\bnew(?P<kind>Checkbox|TextInput|RadioInput|SelectMenuInput)\((?P<args>.*)$")
_PAGE_RE = re.compile(r"^\s*'(?P<page>settings/[\w/-]+)'\s*:\s*\[")
_QUOTED_RE = re.compile(r"'([^']*)'")
_INPUT_TYPES = {"Checkbox": "checkbox", "TextInput": "text", "RadioInput": "radio", "SelectMenuInput": "select-menu"}


@dataclass(frozen=True)
class WebSetting:
    """One web-only org setting: where otterdog finds it, which oracle reads it, whether the harness may toggle it."""

    key: str
    page: str
    web_name: str
    input_type: str
    input_name: str
    value_type: str
    rest_field: str | None
    writable: bool = True
    plans: tuple[str, ...] = PLANS
    parent: str | None = None
    optional: bool = False
    nullable: bool = False
    note: str = ""

    @property
    def rest_readable(self) -> bool:
        """True when ``GET /orgs/{org}`` (owner token) returns the value."""
        return self.rest_field is not None

    @property
    def read_by_otterdog(self) -> bool:
        """True when otterdog's web reader loads the setting (its definition carries the schema key as name)."""
        return self.web_name == self.key

    def applicable(self, plan: str) -> bool:
        """True when GitHub offers the setting on ``plan``."""
        return plan in self.plans


WEB_SETTINGS: tuple[WebSetting, ...] = (
    WebSetting(
        "members_can_change_repo_visibility",
        MEMBER_PRIVILEGES,
        "members_can_change_repo_visibility",
        "checkbox",
        "members_can_change_repo_visibility",
        "boolean",
        "members_can_change_repo_visibility",
    ),
    WebSetting(
        "members_can_delete_repositories",
        MEMBER_PRIVILEGES,
        "members_can_delete_repositories",
        "checkbox",
        "members_can_delete_repositories",
        "boolean",
        "members_can_delete_repositories",
    ),
    WebSetting(
        "members_can_delete_issues",
        MEMBER_PRIVILEGES,
        "members_can_delete_issues",
        "checkbox",
        "members_can_delete_issues",
        "boolean",
        "members_can_delete_issues",
    ),
    WebSetting(
        "readers_can_create_discussions",
        MEMBER_PRIVILEGES,
        "readers_can_create_discussions",
        "checkbox",
        "readers_can_create_discussions",
        "boolean",
        "readers_can_create_discussions",
        optional=True,
        nullable=True,
        note="optional on the page: otterdog skips it silently when the checkbox is missing",
    ),
    WebSetting(
        "members_can_create_teams",
        MEMBER_PRIVILEGES,
        "members_can_create_teams",
        "checkbox",
        "members_can_create_teams",
        "boolean",
        "members_can_create_teams",
    ),
    WebSetting(
        "two_factor_requirement",
        SECURITY,
        "two_factor_required",
        "checkbox",
        "two_factor_required",
        "boolean",
        "two_factor_requirement_enabled",
        writable=False,
        note=(
            "read-only in otterdog and never read by its web client (definition named two_factor_required); never "
            "toggled: requiring 2FA removes every member without 2FA"
        ),
    ),
    WebSetting(
        "default_branch_name",
        REPOSITORY_DEFAULTS,
        "default_branch_name",
        "text",
        "default_branch_name",
        "string",
        "default_repository_branch",
        note="toggled to a run-specific branch name, restored afterwards",
    ),
    WebSetting(
        "packages_containers_public",
        PACKAGES,
        "packages_containers_public",
        "checkbox",
        "packages[containers][public]",
        "boolean",
        None,
    ),
    WebSetting(
        "packages_containers_internal",
        PACKAGES,
        "packages_containers_internal",
        "checkbox",
        "packages[containers][internal]",
        "boolean",
        None,
        plans=("enterprise",),
        note="internal visibility only exists on Enterprise Cloud",
    ),
    WebSetting(
        "members_can_change_project_visibility",
        PROJECTS,
        "members_can_change_project_visibility",
        "checkbox",
        "organization[members_can_change_project_visibility]",
        "boolean",
        None,
    ),
    WebSetting(
        "has_discussions",
        DISCUSSIONS,
        "has_discussions",
        "checkbox",
        "discussions_enabled",
        "boolean",
        None,
        note="enabling it needs discussion_source_repository (a public repository of the org)",
    ),
    WebSetting(
        "discussion_source_repository",
        DISCUSSIONS,
        "discussion_source_repository",
        "select-menu",
        "js-selected-repository-name",
        "repository",
        None,
        parent="has_discussions",
        nullable=True,
        note="'<org>/<repo>'; ignored (null) while has_discussions is false",
    ),
)
WEB_KEYS: tuple[str, ...] = tuple(setting.key for setting in WEB_SETTINGS)
_BY_KEY: Mapping[str, WebSetting] = {setting.key: setting for setting in WEB_SETTINGS}
REST_FIELDS: Mapping[str, str] = {s.key: s.rest_field for s in WEB_SETTINGS if s.rest_field is not None}
REST_READABLE: tuple[str, ...] = tuple(REST_FIELDS)
TRUSTED_READER_ONLY: tuple[str, ...] = tuple(s.key for s in WEB_SETTINGS if s.rest_field is None)
WRITABLE: tuple[str, ...] = tuple(s.key for s in WEB_SETTINGS if s.writable)


def web_setting(key: str) -> WebSetting:
    """The WebSetting of ``key`` (KeyError naming the known keys otherwise)."""
    try:
        return _BY_KEY[key]
    except KeyError:
        raise KeyError(f"{key!r} is not a web setting of otterdog (known: {', '.join(WEB_KEYS)})") from None


def rest_values(org_json: Mapping[str, Any]) -> dict[str, Any]:
    """Web settings readable in a ``GET /orgs/{org}`` answer, keyed by the otterdog key (fields absent from the answer,
    e.g. for a non-owner token, are left out)."""
    return {key: org_json[field] for key, field in REST_FIELDS.items() if field in org_json}


def jsonnet_value(value: Any) -> str:
    """A setting value as a jsonnet literal (JSON)."""
    return json.dumps(value)


def jsonnet_fields(values: Mapping[str, Any]) -> list[str]:
    """Layer-2 settings fields pinning web settings: ``key::: <json>`` for every WRITABLE key of ``values``, in table
    order (``:::`` keeps the field visible even when the baseline hides it; read-only keys are never rendered).
    KeyError for keys that are not web settings."""
    for key in values:
        web_setting(key)
    return [f"{key}::: {jsonnet_value(values[key])}" for key in WRITABLE if key in values]


def differences(expected: Mapping[str, Any], actual: Mapping[str, Any], keys: Iterable[str] | None = None) -> list[str]:
    """``key: expected X, got Y`` for every key (default: those of ``expected``) whose values differ; a key missing
    from ``actual`` counts as ``<not read>``."""
    lines = []
    for key in keys if keys is not None else expected:
        want = expected.get(key)
        if key not in actual:
            lines.append(f"{key}: expected {jsonnet_value(want)}, not read")
        elif actual[key] != want:
            lines.append(f"{key}: expected {jsonnet_value(want)}, got {jsonnet_value(actual[key])}")
    return lines


# --- consistency with an otterdog source ----------------------------------------------------------------------------
@dataclass(frozen=True)
class WebDefinition:
    """One entry of otterdog's github-web-settings.jsonnet."""

    name: str
    page: str
    input_type: str
    input_name: str
    optional: bool = False
    parent: str | None = None
    delay_save: str | None = None


def parse_web_definitions(text: str) -> dict[str, WebDefinition]:
    """Entries of github-web-settings.jsonnet by name (line based: one ``newCheckbox(...)``-like call per line)."""
    definitions: dict[str, WebDefinition] = {}
    page: str | None = None
    for line in text.splitlines():
        header = _PAGE_RE.match(line)
        if header is not None:
            page = header.group("page")
            continue
        entry = _ENTRY_RE.search(line)
        if entry is None or page is None:
            continue
        quoted = _QUOTED_RE.findall(entry.group("args"))
        if not quoted:
            continue
        name = quoted[0]
        parent = re.search(r"'parent'\s*:\s*'([^']+)'", line)
        delay = re.search(r"'delay_save'\s*:\s*'([^']+)'", line)
        definitions[name] = WebDefinition(
            name=name,
            page=page,
            input_type=_INPUT_TYPES[entry.group("kind")],
            input_name=quoted[1] if len(quoted) > 1 else name,
            optional=re.search(r"\boptional\s*=\s*true\b", line) is not None,
            parent=parent.group(1) if parent else None,
            delay_save=delay.group(1) if delay else None,
        )
    return definitions


def schema_web_keys(schema: Mapping[str, Any]) -> list[str]:
    """Keys of the settings schema whose provider is ``web``, in schema order."""
    properties = schema.get("properties") or {}
    return [key for key, value in properties.items() if isinstance(value, Mapping) and value.get("provider") == "web"]


def definition_problems(definitions: Mapping[str, WebDefinition], schema_keys: Sequence[str]) -> list[str]:
    """Differences between the harness table and an otterdog source (schema web keys + web definitions)."""
    problems = []
    added, removed = sorted(set(schema_keys) - set(WEB_KEYS)), sorted(set(WEB_KEYS) - set(schema_keys))
    if added or removed:
        problems.append(f"web settings of the schema differ from the harness table: added {added}, removed {removed}")
    for setting in WEB_SETTINGS:
        definition = definitions.get(setting.web_name)
        if definition is None:
            problems.append(f"{setting.key}: no web definition named {setting.web_name!r}")
            continue
        if definition.page != setting.page:
            problems.append(f"{setting.key}: defined on {definition.page}, the table says {setting.page}")
        if definition.input_name != setting.input_name or definition.input_type != setting.input_type:
            problems.append(
                f"{setting.key}: {definition.input_type} {definition.input_name!r}, the table says "
                f"{setting.input_type} {setting.input_name!r}"
            )
    unread = sorted(set(schema_keys) - set(definitions))
    if set(unread) != EXPECTED_UNREAD:
        problems.append(
            f"schema web keys without a web definition of the same name (never read by otterdog): {unread}, "
            f"expected {sorted(EXPECTED_UNREAD)}"
        )
    known = {setting.web_name for setting in WEB_SETTINGS} | KNOWN_EXTRA_DEFINITIONS
    unknown = sorted(set(definitions) - known)
    if unknown:
        problems.append(f"web definitions unknown to the harness table: {unknown}")
    return problems


def source_problems(source_dir: Path) -> list[str]:
    """definition_problems() of an otterdog source tree (missing or unreadable files are problems too)."""
    try:
        definitions = parse_web_definitions((source_dir / WEB_SETTINGS_FILE).read_text(encoding="utf-8"))
        schema = json.loads((source_dir / SETTINGS_SCHEMA_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        return [f"cannot read the web settings of {source_dir}: {type(exc).__name__}: {exc}"]
    return definition_problems(definitions, schema_web_keys(schema))
