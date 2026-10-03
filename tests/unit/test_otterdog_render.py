"""OrgConfigRenderer and build_baseline (SPEC 11.4): two layers, live profile, verbatim fragments, jsonnet output."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import procs
from otterdog_e2e.naming import RunContext
from otterdog_e2e.otterdog.render import (
    CACHE_LIMIT_OVERRIDES,
    BaselineSpec,
    ConfigFragments,
    OrgConfigRenderer,
    RenderError,
    baseline_settings_fields,
    build_baseline,
    org_profile,
    settings_field,
)
from otterdog_e2e.settings import IdentitySpec, Target, WebappSpec
from otterdog_e2e.sut.template import offline_template

TEMPLATE_DIR = Path(__file__).parent / "data" / "template"
RUN = RunContext("t3c7z8a5")
ORG = "e2e-test-org"
MARKER = "[otterdog-e2e]"
PROFILE: dict[str, Any] = {
    "billing_email": "billing@example.org",
    "description": f"{MARKER} Dedicated test org",
    "name": "E2E Test Org",
    "email": None,
    "blog": "",
    "location": None,
    "company": None,
    "twitter_username": None,
}


def make_target(**overrides: Any) -> Target:
    """A Target with the defaults of targets/free.yaml (logins declared for admin and approver only)."""
    identities = {
        "admin": IdentitySpec("admin", "e2e-admin-bot", "E2E_ADMIN_TOKEN"),
        "approver": IdentitySpec("approver", "e2e-approver-bot", "E2E_APPROVER_TOKEN"),
        "author": IdentitySpec("author", None, "E2E_AUTHOR_TOKEN"),
    }
    values: dict[str, Any] = {
        "name": "free",
        "description": "test target",
        "org": ORG,
        "org_id": 424242,
        "allowed_org_ids": (424242,),
        "expected_plan": "free",
        "marker": MARKER,
        "capability_overrides": {"add": (), "remove": ()},
        "configs_repo": "otterdog-e2e-configs",
        "org_config_repo": "auto",
        "defaults_repo": "otterdog-e2e-defaults",
        "template_mode": "auto",
        "template_url": None,
        "identities": identities,
        "app": None,
        "admin_team": "otterdog-admins",
        "approval_team": "project-leads",
        "contributors_team": "e2e-contributors",
        "webapp": WebappSpec("relay", None, None, "e2e/otterdog-validate", "e2e/otterdog-sync", 1, 5000),
        "fixture_repos": ("otterdog-e2e-fixture-a",),
        "extra_protected_repos": ("human-repo",),
        "baseline_settings": {
            "workflows": {"default_workflow_permissions": "read"},
            "web_commit_signoff_required": False,
        },
        "source_path": Path("targets/free.yaml"),
    }
    values.update(overrides)
    return Target(**values)


def make_renderer(
    *, baseline: BaselineSpec | None = None, hide_cache_limit: bool = False, profile: dict[str, Any] | None = None
) -> OrgConfigRenderer:
    """Renderer of the test org with the offline template."""
    return OrgConfigRenderer(
        template=offline_template(),
        org=ORG,
        plan="free",
        org_profile=PROFILE if profile is None else profile,
        baseline=baseline if baseline is not None else build_baseline(make_target(), RUN),
        marker=MARKER,
        hide_cache_limit=hide_cache_limit,
    )


def layers(text: str) -> tuple[str, str]:
    """(layer 1, layer 2) of a rendered config."""
    first, second = text.split("*/", 1)[1].split("\n} {\n")
    return first, second


def test_layer_one_pins_the_live_profile() -> None:
    """plan + every profile field json-encoded (null stays null), then the baseline settings (OC-01)."""
    first, second = layers(make_renderer().render())
    assert "local orgs0 = import 'vendor/template/otterdog-defaults.libsonnet';\nlocal orgs = orgs0;" in first
    assert f"orgs.newOrg('{ORG}', '{ORG}') {{" in first
    for line in (
        '    plan: "free",',
        '    billing_email: "billing@example.org",',
        f'    description: "{MARKER} Dedicated test org",',
        "    email: null,",
        '    blog: "",',
        # the target's workflows settings merged over the pinned BASELINE_WORKFLOW_DEFAULTS (BAT-14)
        '    workflows+: {"default_workflow_permissions": "read", "fork_pr_approval_policy": "first_time_contributors"},',
        "    web_commit_signoff_required: false,",
    ):
        assert line in first, line
    assert second.strip() == "}"


def test_the_baseline_pins_the_workflow_defaults_the_template_leaves_unset() -> None:
    """BAT-14: fork_pr_approval_policy (changed by cli.org.actions-allowed) is pinned to GitHub's default, so every
    baseline reset restores it; the target's own value wins; workflows: null keeps the template block alone."""
    from otterdog_e2e.otterdog.render import baseline_settings

    assert baseline_settings({}) == {"workflows": {"fork_pr_approval_policy": "first_time_contributors"}}
    assert baseline_settings({"workflows": {"fork_pr_approval_policy": "all_external_contributors"}}) == {
        "workflows": {"fork_pr_approval_policy": "all_external_contributors"}
    }
    assert baseline_settings({"workflows": None}) == {"workflows": None}


def test_missing_profile_fields_are_hidden() -> None:
    """Fields absent from the live profile are rendered ``key:: null`` (UNSET, never PATCHed)."""
    first, _ = layers(make_renderer(profile={"description": f"{MARKER} x"}).render())
    assert "    billing_email:: null," in first and "    twitter_username:: null," in first
    assert f'    description: "{MARKER} x",' in first


def test_org_profile_from_org_json() -> None:
    """Only profile keys GitHub returned are kept (a non-owner answer without billing_email stays unmanaged)."""
    org_json = {"login": ORG, "id": 1, "description": f"{MARKER} x", "name": None, "plan": {"name": "free"}}
    assert org_profile(org_json) == {"description": f"{MARKER} x", "name": None}


def test_plan_override_for_negative_tests() -> None:
    """render(plan=...) replaces settings.plan."""
    assert '    plan: "enterprise",' in make_renderer().render(plan="enterprise")


def test_cache_limit_hiding() -> None:
    """hide_cache_limit: template override for repos and a separate settings layer for the org (OC-06)."""
    text = make_renderer(hide_cache_limit=True).render()
    assert f"local orgs = orgs0 {CACHE_LIMIT_OVERRIDES};" in text
    assert "  } + {\n    workflows+: { max_cache_size_gb:: null },\n  }," in text
    assert "max_cache_size_gb" not in make_renderer().render().split("*/", 1)[1]


def test_fragments_are_inserted_verbatim() -> None:
    """Fragments land in layer 2, untouched by Jinja (they were rendered once by the scenario engine)."""
    fragments = ConfigFragments.from_mapping(
        {
            "settings": ["web_commit_signoff_required: true"],
            "repositories": ["orgs.newRepo('e2e-t3c7z8a5-x') { description: '{{ not jinja }} ${{ github.sha }}' }"],
            "extra": ["_e2e_marker:: true"],
        }
    )
    _, second = layers(make_renderer().render(fragments))
    assert "  settings+: {\n    web_commit_signoff_required: true,\n  }," in second
    assert "orgs.newRepo('e2e-t3c7z8a5-x') { description: '{{ not jinja }} ${{ github.sha }}' }," in second
    assert "  _e2e_marker:: true," in second


@pytest.mark.parametrize(
    "snippet",
    [
        "description: 'x'",
        "plan: 'team'",
        "billing_email: ''",
        "  description+:: null",
        "has_wiki: false, description: 'x'",
        "'description': 'quoted field name'",
    ],
)
def test_settings_fragments_must_not_touch_protected_keys(snippet: str) -> None:
    """plan/description/billing_email come from the live profile and render(plan=...) only (SPEC 12.1 rule 7)."""
    with pytest.raises(RenderError, match="must not set"):
        make_renderer().render(ConfigFragments(settings=[snippet]))


def test_nested_keys_of_settings_fragments_are_not_protected() -> None:
    """Only top-level settings fields count: a nested ``description`` (custom property, string) is fine."""
    fragment = (
        "custom_properties+: [orgs.newCustomProperty('e2e-t3c7z8a5-p') { description: 'plan: x' }], name: 'a, plan: b'"
    )
    assert "custom_properties+: [orgs.newCustomProperty(" in make_renderer().render(
        ConfigFragments(settings=[fragment])
    )


def test_include_baseline_false_keeps_the_profile() -> None:
    """Without the baseline: no teams/repos/baseline settings, but the profile (marker) is still pinned."""
    first, _ = layers(make_renderer().render(include_baseline=False))
    assert "teams+" not in first and "_repositories+" not in first and "web_commit_signoff_required" not in first
    assert f'    description: "{MARKER} Dedicated test org",' in first


def test_renderer_refuses_unsafe_values() -> None:
    """No marker in the description, or names that cannot be single-quoted, are RenderErrors."""
    with pytest.raises(RenderError, match="safety marker"):
        make_renderer(profile={**PROFILE, "description": "production org"})
    renderer = OrgConfigRenderer(
        template=offline_template(),
        org="bad'org",
        plan="free",
        org_profile=PROFILE,
        baseline=BaselineSpec(),
        marker=MARKER,
        hide_cache_limit=False,
    )
    with pytest.raises(RenderError, match="single-quoted"):
        renderer.render()


def test_settings_fields() -> None:
    """Objects merge (``key+:``), scalars replace; keys rendered by layer 1 itself are refused."""
    assert settings_field("workflows", {"b": 1, "a": True}) == 'workflows+: {"a": true, "b": 1}'
    assert settings_field("has_discussions", False) == "has_discussions: false"
    assert baseline_settings_fields({"members_can_create_teams": False}) == ["members_can_create_teams: false"]
    # null hides the key (UNSET: unmanaged), e.g. a template default a Free org cannot have
    assert baseline_settings_fields({"members_can_create_private_pages": None}) == [
        "members_can_create_private_pages:: null"
    ]
    with pytest.raises(RenderError, match="invalid settings key"):
        baseline_settings_fields({"bad-key": None})
    with pytest.raises(RenderError, match="must not set"):
        baseline_settings_fields({"description": "x"})
    with pytest.raises(RenderError, match="invalid settings key"):
        settings_field("bad-key", 1)


def test_build_baseline_teams() -> None:
    """Teams from DECLARED logins only (F8), visible, admin always member; shared names are merged."""
    teams = build_baseline(make_target(), RUN).teams
    assert teams == [
        (
            'orgs.newTeam("otterdog-admins") { description: "otterdog e2e: otterdog admins", '
            'members: ["e2e-admin-bot"], privacy: "visible" }'
        ),
        (
            'orgs.newTeam("project-leads") { description: "otterdog e2e: config change approvers", '
            'members: ["e2e-approver-bot"], privacy: "visible" }'
        ),
        (
            'orgs.newTeam("e2e-contributors") { description: "otterdog e2e: config change authors", '
            'members: [], privacy: "visible" }'
        ),
    ]
    merged = build_baseline(make_target(approval_team="otterdog-admins"), RUN).teams
    assert len(merged) == 2 and '["e2e-admin-bot", "e2e-approver-bot"]' in merged[0]
    no_admin = {"admin": IdentitySpec("admin", None, "E2E_ADMIN_TOKEN")}
    with pytest.raises(RenderError, match="admin login"):
        build_baseline(make_target(identities=no_admin), RUN)


def test_build_baseline_repositories() -> None:
    """Run config repo (merges, team permissions), configs, defaults, fixtures; extra protected repos never rendered."""
    repos = build_baseline(make_target(), RUN).repositories
    assert [repo.split('"')[1] for repo in repos] == [
        "e2e-t3c7z8a5-config",
        "otterdog-e2e-configs",
        "otterdog-e2e-defaults",
        "otterdog-e2e-fixture-a",
    ]
    assert repos[0] == (
        'orgs.newRepo("e2e-t3c7z8a5-config") { allow_merge_commit: true, allow_rebase_merge: true, '
        'allow_squash_merge: true, delete_branch_on_merge: false, description: "otterdog e2e: organization '
        'configuration", private: false, team_permissions: {"e2e-contributors": "push", "otterdog-admins": "admin", '
        '"project-leads": "push"} }'
    )
    assert "auto_init: true" in repos[3] and "human-repo" not in "".join(repos)
    fixed = build_baseline(make_target(org_config_repo=".otterdog"), RUN).repositories
    assert fixed[0].startswith('orgs.newRepo(".otterdog")')


def test_build_baseline_settings() -> None:
    """target.baseline_settings become layer-1 fields (dict values merged, over the pinned workflow defaults)."""
    assert build_baseline(make_target(), RUN).settings == [
        'workflows+: {"default_workflow_permissions": "read", "fork_pr_approval_policy": "first_time_contributors"}',
        "web_commit_signoff_required: false",
    ]
    assert build_baseline(make_target(), RUN).custom_properties == []


# --- evaluation with the jsonnet binary --------------------------------------------------------------------------
JSONNET = shutil.which("jsonnet")


def evaluate(text: str, tmp_path: Path) -> dict[str, Any]:
    """Manifest a rendered config with the local jsonnet binary against the vendored template copy."""
    org_dir = tmp_path / "orgs" / ORG
    shutil.copytree(TEMPLATE_DIR, org_dir / "vendor" / "template")
    config = org_dir / f"{ORG}.jsonnet"
    config.write_text(text, encoding="utf-8")
    completed = procs.run([str(JSONNET), config.name], cwd=org_dir, timeout=60, home=tmp_path / "home")
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
def test_rendered_baseline_manifests(tmp_path: Path) -> None:
    """The baseline evaluates: live profile kept, hidden cache limit, teams, repos and team permissions."""
    org = evaluate(make_renderer(hide_cache_limit=True).render(), tmp_path)
    settings = org["settings"]
    assert settings["description"] == PROFILE["description"] and settings["billing_email"] == "billing@example.org"
    assert settings["plan"] == "free" and settings["email"] is None and settings["blog"] == ""
    assert settings["web_commit_signoff_required"] is False
    assert settings["workflows"]["default_workflow_permissions"] == "read"
    assert settings["workflows"]["allowed_actions"] == "all"  # merged, not replaced
    assert "max_cache_size_gb" not in settings["workflows"]
    repos = {repo["name"]: repo for repo in org["repositories"]}
    assert list(repos) == sorted(repos)
    config = repos["e2e-t3c7z8a5-config"]
    assert config["team_permissions"] == {
        "e2e-contributors": "push",
        "otterdog-admins": "admin",
        "project-leads": "push",
    }
    assert (config["allow_merge_commit"], config["delete_branch_on_merge"], config["private"]) == (True, False, False)
    assert all("max_cache_size_gb" not in repo["workflows"] for repo in repos.values())
    assert repos["otterdog-e2e-fixture-a"]["auto_init"] is True
    teams = {team["name"]: team for team in org["teams"]}
    assert teams["otterdog-admins"]["members"] == ["e2e-admin-bot"] and teams["e2e-contributors"]["members"] == []
    assert {team["privacy"] for team in teams.values()} == {"visible"}


@pytest.mark.skipif(JSONNET is None, reason="jsonnet binary not installed")
def test_rendered_fragments_manifest(tmp_path: Path) -> None:
    """Layer 2 extends layer 1: new objects, baseline repo overrides (mergeByKey), settings, custom properties."""
    fragments = ConfigFragments.from_mapping(
        {
            "settings": ["has_organization_projects: false", "workflows+: { max_cache_size_gb::: 2 }"],
            "custom_properties": ["orgs.newCustomProperty('e2e-t3c7z8a5-tier') { allowed_values: ['a'] }"],
            "secrets": ["orgs.newOrgSecret('E2E_T3C7Z8A5_S') { value: '********' }"],
            "webhooks": ["orgs.newOrgWebhook('https://otterdog-e2e.invalid/t3c7z8a5/org') { events+: ['push'] }"],
            "repositories": [
                "orgs.newRepo('e2e-t3c7z8a5-basic') { description: 'e2e basic' }",
                "orgs.extendRepo('otterdog-e2e-fixture-a') { description: 'changed by a scenario' }",
            ],
        }
    )
    baseline = BaselineSpec(
        settings=baseline_settings_fields({"members_can_create_teams": False}),
        repositories=build_baseline(make_target(), RUN).repositories,
        custom_properties=["orgs.newCustomProperty('e2e-t3c7z8a5-base')"],
    )
    org = evaluate(make_renderer(baseline=baseline, hide_cache_limit=True).render(fragments, plan="team"), tmp_path)
    settings = org["settings"]
    assert settings["plan"] == "team" and settings["description"] == PROFILE["description"]
    assert settings["has_organization_projects"] is False and settings["members_can_create_teams"] is False
    assert settings["workflows"]["max_cache_size_gb"] == 2  # ':::' makes a hidden field visible again
    assert [prop["name"] for prop in settings["custom_properties"]] == ["e2e-t3c7z8a5-base", "e2e-t3c7z8a5-tier"]
    assert [secret["name"] for secret in org["secrets"]] == ["E2E_T3C7Z8A5_S"]
    assert org["webhooks"][0]["events"] == ["push"]
    repos = {repo["name"]: repo for repo in org["repositories"]}
    assert repos["e2e-t3c7z8a5-basic"]["description"] == "e2e basic"
    fixture = repos["otterdog-e2e-fixture-a"]
    assert fixture["description"] == "changed by a scenario" and fixture["auto_init"] is True
