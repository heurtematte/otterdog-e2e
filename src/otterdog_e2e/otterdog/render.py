"""Rendering of the single, self-contained org config file from resources/org.jsonnet.j2 (SPEC 11.4, OC-01).

Two layers: layer 1 (baseline) pins the LIVE org profile (json.dumps, so null stays null and the safety marker in
the description is never wiped), the target's baseline settings (dict values as ``key+:``), baseline custom
properties, teams and repos; layer 2 holds the scenario fragments verbatim (Jinja is applied once, by
scenarios.model.render_step). ConfigFragments also carries the jsonnet injected around the two layers, verbatim too:
``libraries`` (``local <name> = (<expression>);`` right after the template import: the webapp evaluates ONE file, so
helpers cannot be imported from sibling files) and ``overlays`` (object mixins applied after layer 2:
``<newOrg(...) {layer 1} {layer 2}> + (<overlay>)``). Template variables are documented at the top of org.jsonnet.j2:
import_path, template_overrides, project, org, settings, custom_properties, hide_cache_limit, teams, repositories,
fragments (a mapping with every FRAGMENT_KEYS key), libraries ((name, expression) pairs) and overlays.

Profile fields missing from the live profile are rendered hidden (``key:: null``): otterdog then reads them as UNSET
and never diffs nor PATCHes them. With ``hide_cache_limit`` the template's ``max_cache_size_gb`` (org and repo level)
is hidden the same way (OC-06); a scenario that wants to manage it must use ``max_cache_size_gb::: <n>`` since a plain
``:`` keeps an inherited hidden field hidden.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import jinja2

from otterdog_e2e import read_resource

if TYPE_CHECKING:
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.template import TemplateRef

TEMPLATE_RESOURCE = "org.jsonnet.j2"
FRAGMENT_KEYS = (
    "settings",
    "teams",
    "secrets",
    "variables",
    "webhooks",
    "rulesets",
    "roles",
    "custom_properties",
    "repositories",
    "extra",
)
ORG_PROFILE_FIELDS = (
    "billing_email",
    "description",
    "name",
    "email",
    "blog",
    "location",
    "company",
    "twitter_username",
)
# hides the repo-level max_cache_size_gb (UNSET, never PUT) when Cap.ACTIONS_CACHE_LIMIT is missing (OC-06)
CACHE_LIMIT_OVERRIDES = "{ newRepo(name):: orgs0.newRepo(name) { workflows+: { max_cache_size_gb:: null } } }"
# settings keys scenario fragments must never set (SPEC 12.1 rule 7): the plan comes from render(plan=...)
PROTECTED_SETTINGS = ("plan", "description", "billing_email")
# settings keys layer 1 already renders (a baseline setting with one of these names would be a duplicate field)
LAYER1_SETTINGS = ("plan", *ORG_PROFILE_FIELDS)

CONFIG_REPO_DESCRIPTION = "otterdog e2e: organization configuration"
CONFIGS_REPO_DESCRIPTION = "otterdog e2e: webapp configuration (otterdog.json), org lease and run ledger"
DEFAULTS_REPO_DESCRIPTION = "otterdog e2e: published base templates"
FIXTURE_REPO_DESCRIPTION = "otterdog e2e: fixture repository"
TEAM_DESCRIPTIONS = {
    "admin": "otterdog e2e: otterdog admins",
    "approval": "otterdog e2e: config change approvers",
    "contributors": "otterdog e2e: config change authors",
}
TEAM_PRIVACY = "visible"

# names a library must not take: the template locals, jsonnet's std and object keywords, every jsonnet keyword
RESERVED_LIBRARY_NAMES = ("orgs", "orgs0", "std", "self", "super", "$")
JSONNET_KEYWORDS = (
    "assert",
    "else",
    "error",
    "false",
    "for",
    "function",
    "if",
    "import",
    "importbin",
    "importstr",
    "in",
    "local",
    "null",
    "self",
    "super",
    "tailstrict",
    "then",
    "true",
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SETTINGS_FIELD_RE = re.compile(r"^\s*(?P<quote>['\"]?)(?P<key>[A-Za-z_][A-Za-z0-9_]*)(?P=quote)\s*\+?:{1,3}")
_UNQUOTABLE_RE = re.compile(r"['\\\n\r]")


@dataclass
class ConfigFragments:
    """Jsonnet snippets per FRAGMENT_KEYS key (settings: object fields; extra: raw layer-2 fields; others: list items),
    plus the libraries (``local <name> = (<expression>);``) and overlays (object mixins after layer 2) of a render."""

    settings: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    secrets: list[str] = field(default_factory=list)
    variables: list[str] = field(default_factory=list)
    webhooks: list[str] = field(default_factory=list)
    rulesets: list[str] = field(default_factory=list)
    roles: list[str] = field(default_factory=list)
    custom_properties: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    libraries: dict[str, str] = field(default_factory=dict)
    overlays: list[str] = field(default_factory=list)

    def merged(self, other: ConfigFragments) -> ConfigFragments:
        """New fragments with ``other``'s snippets and overlays appended after this one's, key by key (libraries:
        ``other``'s definition wins for a name both define)."""
        snippets = {key: [*getattr(self, key), *getattr(other, key)] for key in FRAGMENT_KEYS}
        return ConfigFragments(
            **snippets,
            libraries={**self.libraries, **other.libraries},
            overlays=[*self.overlays, *other.overlays],
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> ConfigFragments:
        """Build from a YAML mapping (a string value counts as one snippet); ValueError for unknown keys or non-strings."""
        if not data:
            return cls()
        unknown = sorted(set(data) - set(FRAGMENT_KEYS))
        if unknown:
            raise ValueError(f"unknown fragment key(s) {unknown}, expected {list(FRAGMENT_KEYS)}")
        values: dict[str, Any] = {}  # FRAGMENT_KEYS -> list[str]
        for key, value in data.items():
            items = [value] if isinstance(value, str) else list(value or [])
            if not all(isinstance(item, str) for item in items):
                raise ValueError(f"fragment {key!r} must be a string or a list of strings")
            values[key] = items
        return cls(**values)

    def to_mapping(self) -> dict[str, list[str]]:
        """Plain mapping with every FRAGMENT_KEYS key (the ``fragments`` template variable; no libraries, overlays)."""
        return {key: list(getattr(self, key)) for key in FRAGMENT_KEYS}

    def is_empty(self) -> bool:
        """True when no key holds a snippet and no overlay is set (libraries alone change nothing)."""
        return not self.overlays and not any(getattr(self, key) for key in FRAGMENT_KEYS)


@dataclass
class BaselineSpec:
    """Layer-1 content: settings fields, team/repository expressions and custom property definitions."""

    settings: list[str] = field(default_factory=list)
    teams: list[str] = field(default_factory=list)
    repositories: list[str] = field(default_factory=list)
    custom_properties: list[str] = field(default_factory=list)


class RenderError(ValueError):
    """The org config cannot be rendered safely (e.g. the description would lose the safety marker)."""


def _jinja_environment() -> jinja2.Environment:
    """Strict Jinja environment for jsonnet output (no HTML escaping, undefined variables fail)."""
    return jinja2.Environment(
        undefined=jinja2.StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,  # noqa: S701 - renders jsonnet, not HTML
    )


def library_name_problem(name: str) -> str | None:
    """Why ``name`` cannot be the local of a library (None when it can): a jsonnet identifier that is no keyword and
    does not shadow the template locals (orgs, orgs0) or std/self/super/$."""
    if not isinstance(name, str) or not _IDENTIFIER_RE.match(name):
        return f"library name {name!r} is not a jsonnet identifier ([A-Za-z_][A-Za-z0-9_]*)"
    if name in RESERVED_LIBRARY_NAMES or name in JSONNET_KEYWORDS:
        return f"library name {name!r} is reserved (orgs, orgs0, std, self, super, $ and jsonnet keywords)"
    return None


def _check_quotable(what: str, value: str) -> str:
    """Return ``value`` when it can sit inside a single-quoted jsonnet string, else RenderError."""
    if not value or _UNQUOTABLE_RE.search(value):
        raise RenderError(f"{what} {value!r} cannot be rendered inside a single-quoted jsonnet string")
    return value


def settings_key(snippet: str) -> str | None:
    """Field name set by a settings snippet (``key: v``, ``key+: v``, ``key:: v``), or None."""
    match = _SETTINGS_FIELD_RE.match(snippet)
    return match.group("key") if match else None


def _top_level_fields(snippet: str) -> list[str]:
    """The comma-separated fields of a snippet at nesting depth 0 (quotes and brackets respected)."""
    fields_: list[str] = []
    depth, quote, escaped, start = 0, "", False, 0
    for index, char in enumerate(snippet):
        if quote:
            if char == quote and not escaped:
                quote = ""
            escaped = not escaped and char == "\\"
            continue
        if char in "'\"":
            quote, escaped = char, False
        elif char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif char == "," and depth == 0:
            fields_.append(snippet[start:index])
            start = index + 1
    fields_.append(snippet[start:])
    return fields_


def settings_keys(snippet: str) -> list[str]:
    """Every field name a settings snippet sets at its top level."""
    return [key for key in map(settings_key, _top_level_fields(snippet)) if key]


def settings_field(key: str, value: Any) -> str:
    """One layer-1 settings field: ``key+: <json>`` for objects (merge), ``key: <json>`` otherwise."""
    if not _IDENTIFIER_RE.match(key):
        raise RenderError(f"invalid settings key {key!r}")
    operator = "+:" if isinstance(value, Mapping) else ":"
    return f"{key}{operator} {json.dumps(value, sort_keys=True)}"


def hidden_field(key: str) -> str:
    """``key:: null``: a hidden field, so otterdog reads the key as UNSET and leaves it unmanaged."""
    if not _IDENTIFIER_RE.match(key):
        raise RenderError(f"invalid settings key {key!r}")
    return f"{key}:: null"


def baseline_settings_fields(settings: Mapping[str, Any]) -> list[str]:
    """Layer-1 fields of the target's baseline settings (RenderError for keys layer 1 renders itself); a ``null``
    value hides the key (unmanaged), e.g. a template default the org cannot have (members_can_create_private_pages
    on Free)."""
    clashing = sorted(set(settings) & set(LAYER1_SETTINGS))
    if clashing:
        raise RenderError(f"baseline settings must not set {clashing}: they come from the live org profile and plan")
    return [hidden_field(key) if value is None else settings_field(key, value) for key, value in settings.items()]


def org_profile(org_json: Mapping[str, Any]) -> dict[str, Any]:
    """ORG_PROFILE_FIELDS present in a GET /orgs/{org} answer (absent keys stay absent: rendered hidden, unmanaged)."""
    return {key: org_json[key] for key in ORG_PROFILE_FIELDS if key in org_json}


class OrgConfigRenderer:
    """Renders org configs for one org: baseline layer + scenario fragments."""

    def __init__(
        self,
        *,
        template: TemplateRef,
        org: str,
        plan: str,
        org_profile: Mapping[str, Any],
        baseline: BaselineSpec,
        marker: str,
        hide_cache_limit: bool,
        project: str | None = None,
    ) -> None:
        """Bind the live org profile (ORG_PROFILE_FIELDS of VerifiedOrg.org_json); RenderError if it lacks the marker."""
        description = org_profile.get("description") or ""
        if marker not in description:
            raise RenderError(f"org description {description!r} does not contain the safety marker {marker!r}")
        self.template = template
        self.org = org
        self.plan = plan
        self.org_profile = dict(org_profile)
        self.baseline = baseline
        self.marker = marker
        self.hide_cache_limit = hide_cache_limit
        self.project = project or org

    def render(
        self, fragments: ConfigFragments | None = None, *, include_baseline: bool = True, plan: str | None = None
    ) -> str:
        """Render the org config; ``plan`` overrides settings.plan (negative tests); fragments, libraries and overlays
        are inserted verbatim."""
        fragments = fragments or ConfigFragments()
        self._check_fragments(fragments)
        baseline = self.baseline if include_baseline else BaselineSpec()
        variables = {
            "import_path": _check_quotable("template import path", self.template.import_path),
            "template_overrides": CACHE_LIMIT_OVERRIDES if self.hide_cache_limit else "",
            "project": _check_quotable("project", self.project),
            "org": _check_quotable("org", self.org),
            "settings": [*self.profile_fields(plan or self.plan), *baseline.settings],
            "custom_properties": list(baseline.custom_properties),
            "hide_cache_limit": self.hide_cache_limit,
            "teams": list(baseline.teams),
            "repositories": list(baseline.repositories),
            "fragments": fragments.to_mapping(),
            "libraries": [(name, text.strip()) for name, text in fragments.libraries.items()],
            "overlays": [text.strip() for text in fragments.overlays],
        }
        return _jinja_environment().from_string(read_resource(TEMPLATE_RESOURCE)).render(**variables)

    def profile_fields(self, plan: str) -> list[str]:
        """``plan`` plus every ORG_PROFILE_FIELDS key: live values json-encoded, missing keys hidden (UNSET)."""
        items = [settings_field("plan", plan)]
        for key in ORG_PROFILE_FIELDS:
            items.append(settings_field(key, self.org_profile[key]) if key in self.org_profile else f"{key}:: null")
        return items

    @staticmethod
    def _check_fragments(fragments: ConfigFragments) -> None:
        """RenderError when a settings fragment sets plan, description or billing_email (SPEC 12.1 rule 7), for an
        unusable library name and for empty libraries or overlays (they would not parse)."""
        keys = {key for snippet in fragments.settings for key in settings_keys(snippet)}
        protected = sorted(keys & set(PROTECTED_SETTINGS))
        if protected:
            raise RenderError(f"settings fragments must not set {protected} (use render(plan=...) for the plan)")
        for name, text in fragments.libraries.items():
            problem = library_name_problem(name)
            if problem:
                raise RenderError(problem)
            if not text.strip():
                raise RenderError(f"library {name!r} is empty")
        if any(not text.strip() for text in fragments.overlays):
            raise RenderError("an overlay is empty")


def _team(name: str, members: Iterable[str], description: str) -> str:
    """``orgs.newTeam(name) {...}`` with visible privacy and the given members."""
    body = {"description": description, "members": list(members), "privacy": TEAM_PRIVACY}
    return f"orgs.newTeam({json.dumps(_check_quotable('team', name))}) {_object(body)}"


def _repo(name: str, fields_: Mapping[str, Any]) -> str:
    """``orgs.newRepo(name) {...}``."""
    return f"orgs.newRepo({json.dumps(_check_quotable('repository', name))}) {_object(fields_)}"


def _object(data: Mapping[str, Any]) -> str:
    """A jsonnet object literal whose fields are json-encoded values (sorted, one line)."""
    return "{ " + ", ".join(f"{key}: {json.dumps(value, sort_keys=True)}" for key, value in sorted(data.items())) + " }"


def _declared_login(target: Target, role: str) -> str | None:
    """Login DECLARED in the target for an identity role (never derived from a token, F8)."""
    spec = target.identities.get(role)
    return spec.login if spec is not None and spec.login else None


def baseline_teams(target: Target) -> list[str]:
    """Admin, approval and contributors teams (members: declared admin/approver/author logins; same names merged)."""
    admin = _declared_login(target, "admin")
    if admin is None:
        raise RenderError(f"target {target.name!r} declares no admin login (identities.admin.login)")
    roles = (
        ("admin", target.admin_team, admin),
        ("approval", target.approval_team, _declared_login(target, "approver")),
        ("contributors", target.contributors_team, _declared_login(target, "author")),
    )
    teams: dict[str, tuple[str, list[str]]] = {}
    for role, name, login in roles:
        _, members = teams.setdefault(name, (TEAM_DESCRIPTIONS[role], []))
        if login is not None and login not in members:
            members.append(login)
    return [_team(name, members, description) for name, (description, members) in teams.items()]


def baseline_repositories(target: Target, run_ctx: RunContext) -> list[str]:
    """Run config repo, configs repo, defaults repo and fixture repos (all public, distinct names)."""
    permissions = {target.contributors_team: "push", target.approval_team: "push"}
    permissions[target.admin_team] = "admin"
    config_repo = {
        "description": CONFIG_REPO_DESCRIPTION,
        "allow_merge_commit": True,
        "allow_rebase_merge": True,
        "allow_squash_merge": True,
        "delete_branch_on_merge": False,
        "private": False,
        "team_permissions": permissions,
    }
    repos: dict[str, Mapping[str, Any]] = {target.config_repo_for(run_ctx): config_repo}
    repos.setdefault(target.configs_repo, {"description": CONFIGS_REPO_DESCRIPTION, "private": False})
    repos.setdefault(target.defaults_repo, {"description": DEFAULTS_REPO_DESCRIPTION, "private": False})
    for fixture in target.fixture_repos:
        repos.setdefault(fixture, {"description": FIXTURE_REPO_DESCRIPTION, "private": False, "auto_init": True})
    return [_repo(name, data) for name, data in repos.items()]


# org settings the example template leaves unset but scenarios change: the baseline pins them, so the reset of every
# session and the cleanup of org_level scenarios restore them (BAT-14: GitHub's default for new organizations)
BASELINE_WORKFLOW_DEFAULTS: Mapping[str, Any] = {"fork_pr_approval_policy": "first_time_contributors"}


def baseline_settings(target_settings: Mapping[str, Any]) -> dict[str, Any]:
    """The target's baseline settings with BASELINE_WORKFLOW_DEFAULTS merged into ``workflows`` (the target's own
    values win; ``workflows: null`` keeps the template's block untouched)."""
    settings = dict(target_settings)
    if "workflows" not in settings:
        settings["workflows"] = dict(BASELINE_WORKFLOW_DEFAULTS)
    elif isinstance(settings["workflows"], Mapping):
        settings["workflows"] = {**BASELINE_WORKFLOW_DEFAULTS, **settings["workflows"]}
    return settings


def build_baseline(target: Target, run_ctx: RunContext) -> BaselineSpec:
    """Baseline layer of a run: config/configs/defaults/fixture repos (public), admin/approval/contributors teams.

    Config repo for the run: description "otterdog e2e: organization configuration", squash/merge/rebase merges
    enabled, delete_branch_on_merge false, team_permissions {contributors: push, approval: push, admin: admin}; fixture
    repos auto_init true; teams with privacy "visible" and members from the DECLARED logins of the target (F8);
    settings: target.baseline_settings plus BASELINE_WORKFLOW_DEFAULTS (baseline_settings).
    """
    return BaselineSpec(
        settings=baseline_settings_fields(baseline_settings(target.baseline_settings)),
        teams=baseline_teams(target),
        repositories=baseline_repositories(target, run_ctx),
        custom_properties=[],
    )
