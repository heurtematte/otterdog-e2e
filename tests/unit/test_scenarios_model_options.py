"""Scenario model extensions: validate verbose/infos/exit_code, plan and apply diff options, the live repo_filter rule,
per-step known_bug, the offline step ``workspace``, offline profile settings, the extended dummy-secret rule
(provider references, the KB-025 literal offline, webhook e2e-dummy secrets) and ``commands.show``."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.naming import new_run_context
from otterdog_e2e.otterdog.workspace import WorkspaceLayout
from otterdog_e2e.scenarios.model import (
    APPLY_KEYS,
    PLAN_KEYS,
    STEP_KEYS,
    VALIDATE_KEYS,
    ApplySpec,
    PlanSpec,
    ScenarioError,
    ValidateSpec,
    is_dummy_secret,
    json_schema,
    load_scenario,
    render_step,
    repo_filter_problems,
)

RUN = new_run_context("t3c7z8a5")
VARIABLES: dict[str, Any] = {
    **RUN.template_vars(),
    "org": "e2e-test-org",
    "plan": "free",
    "logins": {"admin": "e2e-admin"},
    "app_slug": "otterdog-e2e-app",
    "teams": {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"},
}


def load(tmp_path: Path, step: str, *, header: str = "", tier_dir: str = "cli") -> Any:
    """Load a one-step scenario (``step``: the YAML body of the step) from tmp_path/<tier_dir>/case.yaml."""
    body = textwrap.indent(textwrap.dedent(step).strip("\n"), "    ")
    text = f"id: t.case\ntitle: case\n{textwrap.dedent(header).strip()}\nsteps:\n  - name: s1\n{body}\n"
    path = tmp_path / tier_dir / "case.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return load_scenario(path)


def refused(tmp_path: Path, match: str, step: str, *, header: str = "", tier_dir: str = "cli") -> None:
    """Loading raises ScenarioError matching ``match``."""
    with pytest.raises(ScenarioError, match=match):
        load(tmp_path, step, header=header, tier_dir=tier_dir)


# --- validate --------------------------------------------------------------------------------------------------------
def test_validate_verbose_infos_and_exit_code(tmp_path: Path) -> None:
    """verbose, infos, infos_min and exit_code parse; infos counts need verbose (validate hides Infos without -v)."""
    step = load(tmp_path, "fragments: {}\nvalidate: {verbose: true, infos: 2, infos_min: 1, exit_code: 0}").steps[0]
    assert step.validate == ValidateSpec(ok=True, infos=2, infos_min=1, exit_code=0, verbose=True)
    assert (
        load(tmp_path, "validate: {ok: false, exit_code: null}", tier_dir="offline").steps[0].validate.exit_code is None
    )
    refused(tmp_path, r"infos need verbose: true", "validate: {infos: 1}")
    refused(tmp_path, r"infos_min need verbose", "validate: {infos_min: 1, verbose: false}")
    refused(tmp_path, "non-negative integer", "validate: {verbose: true, infos: -1}")
    refused(tmp_path, "expected true or false", "validate: {verbose: 1}")


# --- plan and apply options ------------------------------------------------------------------------------------------
def test_plan_and_apply_diff_options(tmp_path: Path) -> None:
    """repo_filter, update_secrets, update_webhooks, update_filter, only_secrets, verbose and exit_code."""
    step = load(
        tmp_path,
        """
        fragments: {}
        plan:
          repo_filter: "{{ p }}-a*"
          update_secrets: true
          update_filter: "{{ P }}_A*"
          verbose: true
          exit_code: 0
        apply: {update_webhooks: true, only_secrets: true, update_filter: "{{ hook_base }}*", repo_filter: "{{ p }}-a"}
        """,
    ).steps[0]
    assert step.plan == PlanSpec(
        exit_code=0, repo_filter="{{ p }}-a*", update_secrets=True, update_filter="{{ P }}_A*", verbose=True
    )
    assert step.apply == ApplySpec(
        update_webhooks=True, only_secrets=True, update_filter="{{ hook_base }}*", repo_filter="{{ p }}-a"
    )
    rendered = render_step(step, VARIABLES)
    assert rendered.plan.repo_filter == f"{RUN.prefix}-a*" and rendered.apply.update_filter == f"{RUN.hook_base}*"
    assert ApplySpec("any", True, True, True, ["Done"], []).repo_filter is None  # positional order kept


def test_update_filter_needs_a_forced_update(tmp_path: Path) -> None:
    """--update-filter only selects what --update-secrets / --update-webhooks force."""
    refused(tmp_path, "update_filter: it only selects", "plan: {update_filter: 'E2E_*'}")
    refused(tmp_path, "update_filter: it only selects", "apply: {update_filter: 'E2E_*', only_secrets: true}")


def test_live_repo_filters_stay_inside_the_run(tmp_path: Path) -> None:
    """A live repo_filter must start with the run prefix unless org_level (load time, sample prefix)."""
    refused(tmp_path, r"plan.repo_filter '\*' does not start with the run prefix", "plan: {repo_filter: '*'}")
    refused(tmp_path, "apply.repo_filter 'other-.*' does not start", "apply: {repo_filter: 'other-*'}")
    refused(tmp_path, "does not start with the run prefix", "plan: {repo_filter: '{{ p }}*'}")  # e2e-<run>x* too
    assert load(tmp_path, "plan: {repo_filter: '*'}", header="org_level: true").steps[0].plan.repo_filter == "*"
    assert load(tmp_path, "base_fragments: {}\nplan: {repo_filter: 'x*'}", tier_dir="offline").steps[0].plan
    negative = """
    fragments: {}
    on_missing_capability: {plan: {repo_filter: 'foreign-*'}}
    """
    refused(tmp_path, "plan.repo_filter 'foreign-", negative, header="expect_failure_without: [private_pages]")


def test_repo_filter_problems_uses_the_given_prefix(tmp_path: Path) -> None:
    """repo_filter_problems: the engine's run-time check with the real prefix."""
    rendered = render_step(load(tmp_path, "plan: {repo_filter: '{{ p }}-a'}").steps[0], VARIABLES)
    assert repo_filter_problems(rendered, RUN.prefix) == []
    assert repo_filter_problems(rendered, "e2e-other000")[0].startswith("plan.repo_filter")


def test_an_apply_that_deletes_uses_the_plans_filter(tmp_path: Path) -> None:
    """apply -d is guarded by the step's plan: its own repo_filter must be the plan's (or absent)."""
    refused(tmp_path, "set repo_filter on plan only", "apply: {delete: true, repo_filter: '{{ p }}-a'}")
    same = "plan: {repo_filter: '{{ p }}-a'}\napply: {delete: true, repo_filter: '{{ p }}-a'}"
    assert load(tmp_path, same).steps[0].apply.delete
    assert load(tmp_path, "plan: {repo_filter: '{{ p }}-a'}\napply: {delete: true}").steps[0].apply.repo_filter is None


# --- known_bug -------------------------------------------------------------------------------------------------------
def test_step_known_bug(tmp_path: Path) -> None:
    """A step may declare a known bug of its own (KB-<nnn>)."""
    assert load(tmp_path, "known_bug: KB-025\nfragments: {}").steps[0].known_bug == "KB-025"
    assert load(tmp_path, "fragments: {}").steps[0].known_bug is None
    refused(tmp_path, r"steps\[0\].known_bug", "known_bug: BUG-1")


# --- offline workspace -----------------------------------------------------------------------------------------------
WORKSPACE = """
fragments: {}
workspace:
  format: jsonnet
  orgs: ["{{ org }}-2", {github_id: e2e-archived, archived: true}, {name: null, github_id: e2e-x, credentials: null}]
  defaults_override: {jsonnet: {config_dir: orgs-override, base_template: null}, github: {exclude_teams: [x]}}
  base_url: https://otterdog-e2e.invalid/base
  config_dir: orgs-alt
  vendor: false
"""


def test_offline_workspace_layout(tmp_path: Path) -> None:
    """The workspace key becomes a WorkspaceLayout; its strings are rendered like every other string."""
    step = load(tmp_path, WORKSPACE, tier_dir="offline").steps[0]
    assert step.offline and isinstance(step.workspace, WorkspaceLayout)
    layout = step.workspace
    assert (layout.format, layout.config_dir, layout.vendor) == ("jsonnet", "orgs-alt", False)
    assert layout.effective_config_dir == "orgs-override" and layout.base_url == "https://otterdog-e2e.invalid/base"
    rendered = render_step(step, {**VARIABLES, "org": "e2e-offline"}).workspace
    assert rendered.orgs[0] == "e2e-offline-2" and rendered.orgs[1] == {"github_id": "e2e-archived", "archived": True}
    assert load(tmp_path, "fragments: {}\nworkspace: {}", tier_dir="offline").steps[0].workspace.is_default


@pytest.mark.parametrize(
    ("step", "match"),
    [
        ("workspace: {format: yaml}", "is not one of"),
        ("workspace: {colour: red}", r"unknown key\(s\) \['colour'\]"),
        ("workspace: {config_dir: ../out}", "is not a directory name"),
        ("workspace: {config_dir: '{{ p }}'}", "is not a directory name"),
        ("workspace: {defaults_override: {jsonnet: {config_dir: /tmp}}}", "is not a directory name"),
        ("workspace: {defaults_override: {pass: {password_store_dir: /x}}}", r"unknown key\(s\) \['pass'\]"),
        ("workspace: {defaults_override: {credentials: {provider: pass}}}", r"unknown key\(s\) \['credentials'\]"),
        ("workspace: {defaults_override: {jsonnet: {repo: x}}}", r"unknown key\(s\) \['repo'\]"),
        ("workspace: {orgs: [{github_id: x, credentials: {provider: pass}}]}", "credentials: only null"),
        ("workspace: {orgs: [{github_id: x, token: t}]}", r"unknown key\(s\) \['token'\]"),
        ("workspace: {orgs: e2e-x}", "expected a list"),
        ("workspace: {vendor: no-thanks}", "expected true or false"),
    ],
)
def test_offline_workspace_refusals(tmp_path: Path, step: str, match: str) -> None:
    """Strict keys; directories stay inside the workspace; no credential provider settings anywhere."""
    refused(tmp_path, match, step, tier_dir="offline")


def test_workspace_is_offline_only(tmp_path: Path) -> None:
    """Live steps never change otterdog's own configuration."""
    refused(tmp_path, "only offline scenarios change otterdog's own configuration", "workspace: {format: jsonnet}")


# --- offline settings and plan ---------------------------------------------------------------------------------------
def test_offline_settings_may_set_the_profile_but_not_the_plan(tmp_path: Path) -> None:
    """Offline (nothing is applied): description, billing_email, name... are allowed, plan stays variables.plan; live
    scenarios keep refusing description and billing_email."""
    profile = "fragments: {settings: [\"description: std.repeat('d', 161)\", \"billing_email: 'x@example.org'\"]}"
    step = load(tmp_path, profile, tier_dir="offline").steps[0]
    assert render_step(step, {**VARIABLES, "org": "e2e-offline"}).fragments.settings[0].startswith("description")
    refused(tmp_path, r"must not set \['plan'\]", "fragments: {settings: [\"plan: 'team'\"]}", tier_dir="offline")
    refused(tmp_path, "must not set", profile, header="org_level: true")
    overlay = "overlay: \"{ settings+: { description: 'd', name: 'n' } }\""
    assert load(tmp_path, overlay, tier_dir="offline").steps[0].fragments.overlays
    refused(
        tmp_path,
        r"overlays must not set settings \['plan'\]",
        "overlay: '{ settings+: { plan: 1 } }'",
        tier_dir="offline",
    )
    refused(tmp_path, "overlays must not set settings", overlay, header="org_level: true")


def test_offline_plan_expectations_need_a_base(tmp_path: Path) -> None:
    """local-plan only runs against a BASE configuration: plan expectations without one would be ignored."""
    refused(tmp_path, "add base_fragments: {}", "fragments: {}\nplan: {expect: validation_error}", tier_dir="offline")
    assert load(tmp_path, "fragments: {}\nplan: null", tier_dir="offline").steps[0].plan is None
    step = load(tmp_path, "base_fragments: {}\nplan: {expect: validation_error, contains: [x]}", tier_dir="offline")
    assert step.steps[0].plan.contains == ["x"]


def test_commands_show_holds_the_show_expectations(tmp_path: Path) -> None:
    """``show`` is accepted in commands (the expectations of the show phase)."""
    step = load(tmp_path, "commands: {show: {exit_code: 1, contains: [Error]}}", tier_dir="offline").steps[0]
    assert step.commands["show"].exit_code == 1 and step.commands["show"].contains == ["Error"]


# --- secrets ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("value", "offline", "accepted"),
    [
        ("********", False, True),
        ("e2e-dummy-abcdef12", False, True),
        ("pass:bots/technology.csi/github.com/otterdog-token", False, True),
        ("pass:e2e/a", False, True),
        ("foo:e2e/b", False, True),
        ("pass:a:b", False, False),
        ("pass:a:b", True, True),
        ("pass:e2e/a:b:c", True, True),
        ("pass:$(id)", True, False),
        ("pass:a b", True, False),
        ("pass:-x", False, False),
        ("vault:e2e/x", True, False),
        ("bitwarden:e2e/x", True, False),
        ("foo:bar", True, False),
        ("hunter2", True, False),
        ("e2e-dummy-TOOSHORT", True, False),
        ("", False, True),
    ],
)
def test_dummy_secret_values(value: str, offline: bool, accepted: bool) -> None:
    """Dummies and references are not secrets; shell metacharacters and resolvable vault providers are refused."""
    assert is_dummy_secret(value, offline=offline) is accepted


@pytest.mark.parametrize(
    "fragment",
    [
        "secrets: [\"orgs.newOrgSecret('{{ P }}_A') { value: 'pass:e2e/a' }\"]",
        "secrets: [\"orgs.newOrgSecret('{{ P }}_B') { value: 'foo:e2e/b' }\"]",
        "webhooks: [\"orgs.newOrgWebhook('{{ hook_base }}h') { secret: 'e2e-dummy-{{ run }}' }\"]",
        "webhooks: [\"orgs.newOrgWebhook('{{ hook_base }}h') { secret: 'pass:e2e/hook' }\"]",
        (
            "repositories: [\"orgs.newRepo('{{ p }}-r') { webhooks: [orgs.newRepoWebhook('{{ hook_base }}r') "
            "{ secret: 'e2e-dummy-{{ run }}' }] }\"]"
        ),
    ],
)
def test_references_and_webhook_dummies_load_in_every_tier(tmp_path: Path, fragment: str) -> None:
    """pass:/e2e references and 'e2e-dummy-{{ run }}' webhook secrets load live and offline."""
    load(tmp_path, f"fragments: {{{fragment}}}")
    load(tmp_path, f"fragments: {{{fragment}}}", tier_dir="offline")


def test_the_kb025_literal_is_offline_only(tmp_path: Path) -> None:
    """'pass:a:b' (validation crashes with 'too many values to unpack', KB-025) loads offline only, also after the
    run-time render."""
    fragment = "fragments: {secrets: [\"orgs.newOrgSecret('{{ P }}_C') { value: '{{ value }}' }\"]}"
    offline = load(tmp_path, fragment, header="variables: {value: 'pass:a:b'}", tier_dir="offline")
    assert render_step(offline.steps[0], {**VARIABLES, "value": "pass:a:b"}).fragments.secrets
    refused(tmp_path, "dummy", fragment, header="variables: {value: 'pass:a:b'}")
    with pytest.raises(ScenarioError, match="dummy"):
        render_step(offline.steps[0], {**VARIABLES, "value": "pass:$(id)"})


# --- schema ----------------------------------------------------------------------------------------------------------
def test_schema_knows_the_new_keys() -> None:
    """The editor schema follows the loader's key lists."""
    schema = json_schema()
    step = schema["properties"]["steps"]["items"]["properties"]
    assert {"known_bug", "workspace"} <= set(step) and list(step) == list(STEP_KEYS)
    assert list(step["validate"]["properties"]) == list(VALIDATE_KEYS)
    assert list(step["plan"]["properties"]) == list(PLAN_KEYS)
    assert list(step["apply"]["properties"]) == list(APPLY_KEYS)
    assert "show" in step["commands"]["properties"]
    assert set(step["workspace"]["properties"]) == {
        "format",
        "orgs",
        "defaults_override",
        "base_url",
        "config_dir",
        "vendor",
    }
