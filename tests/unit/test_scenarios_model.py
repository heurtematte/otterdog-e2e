"""Scenario YAML model: strict loading, the ScenarioError rules of SPEC 12.1 (7) and the single Jinja pass."""

from __future__ import annotations

import textwrap
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.naming import new_run_context
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.scenarios.model import (
    ApplySpec,
    PlanSpec,
    ScenarioError,
    StepSpec,
    ValidateSpec,
    domain_problem,
    fragment_problems,
    load_scenario,
    load_scenarios,
    render_step,
    scenario_domain,
    scenario_files,
    tier_directory,
)

RUN = new_run_context("t3c7z8a5")
VARIABLES: dict[str, Any] = {
    **RUN.template_vars(),
    "org": "e2e-test-org",
    "plan": "free",
    "logins": {"admin": "e2e-admin", "author": "e2e-author"},
    "app_slug": "otterdog-e2e-app",
    "teams": {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"},
}

MINIMAL = """
id: cli.repo.basic
title: Basic repository
steps:
  - name: create
    fragments:
      repositories: ["orgs.newRepo('{{ p }}-basic') { description: 'e2e basic' }"]
"""


def write(root: Path, relative: str, text: str) -> Path:
    """Write a dedented YAML file below ``root`` and return its path."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return path


def scenario_yaml(step: str = "", *, header: str = "", tier_dir: str = "cli") -> tuple[str, str]:
    """A scenario document with one custom step body (indented YAML) and optional extra top-level keys."""
    body = textwrap.indent(textwrap.dedent(step).strip("\n"), "    ") if step else "    fragments: {}"
    text = f"id: t.case\ntitle: case\n{textwrap.dedent(header).strip()}\nsteps:\n  - name: s1\n{body}\n"
    return f"{tier_dir}/case.yaml", text


def load_text(tmp_path: Path, step: str = "", *, header: str = "", tier_dir: str = "cli") -> Any:
    """Load a scenario built by scenario_yaml."""
    relative, text = scenario_yaml(step, header=header, tier_dir=tier_dir)
    return load_scenario(write(tmp_path, relative, text))


def assert_error(tmp_path: Path, match: str, step: str = "", *, header: str = "", tier_dir: str = "cli") -> None:
    """Loading the scenario raises ScenarioError matching ``match``."""
    with pytest.raises(ScenarioError, match=match):
        load_text(tmp_path, step, header=header, tier_dir=tier_dir)


# --- loading and defaults --------------------------------------------------------------------------------------------
def test_minimal_live_scenario_defaults(tmp_path: Path) -> None:
    """Missing keys take the documented defaults; the tier comes from the directory name."""
    scenario = load_scenario(write(tmp_path, "cli/basic.yaml", MINIMAL))
    assert (scenario.id, scenario.tier, scenario.priority, scenario.min_plan) == ("cli.repo.basic", "cli", "P1", "free")
    assert scenario.is_live and not scenario.org_level and scenario.cleanup == "auto"
    assert scenario.source == tmp_path / "cli/basic.yaml"
    step = scenario.steps[0]
    assert step.plan == PlanSpec(expect="changes") and step.apply == ApplySpec(expect="ok")
    assert step.validate is None and step.state == [] and step.converge is True and step.base_fragments is None
    assert step.fragments.repositories == ["orgs.newRepo('{{ p }}-basic') { description: 'e2e basic' }"]


def test_full_scenario_fields(tmp_path: Path) -> None:
    """Every documented key is parsed."""
    path = write(
        tmp_path,
        "cli/full.yaml",
        """
        id: C-REPO-LIFECYCLE
        title: lifecycle
        description: create, update, delete
        tier: cli
        priority: P0
        min_plan: team
        requires: [public_repos]
        expect_failure_without: [private_repo_branch_protection]
        identities: [author, approver]
        tags: [repo, smoke]
        known_bug: KB-007
        org_level: true
        observe: true
        variables: {plan: team, label: x}
        cleanup: none
        steps:
          - name: create
            fragments: {settings: ["web_commit_signoff_required: true"]}
            validate: {warnings_min: 1, contains: [Validation]}
            plan:
              expect: changes
              contains: [a]
              not_contains: [b]
              counts: {add: 1, change: 0, delete: 0}
              update_secrets: true
              update_webhooks: true
            apply: {expect: any, delete: true, update_secrets: true, update_webhooks: true, contains: [Done]}
            state: [{kind: repo, name: "{{ p }}-x", match: {private: false}}]
            converge: false
            on_missing_capability: {apply: {expect: error}, state: [], converge: false}
        """,
    )
    scenario = load_scenario(path)
    assert scenario.requires == ["public_repos"] and scenario.identities == ["author", "approver"]
    assert scenario.known_bug == "KB-007" and scenario.observe and scenario.cleanup == "none"
    assert scenario.plan_override == "team" and scenario.variables["label"] == "x"
    step = scenario.steps[0]
    assert step.validate == ValidateSpec(ok=True, warnings_min=1, contains=["Validation"])
    assert step.plan is not None and step.plan.counts == {"add": 1, "change": 0, "delete": 0}
    assert step.apply == ApplySpec("any", True, True, True, ["Done"], [])
    negative = step.for_missing_capability()
    assert negative.apply == ApplySpec("error", True, True, True, ["Done"], [])  # merged over the step's apply
    assert negative.state == [] and negative.converge is False and step.state != []


def test_plan_and_apply_null_skip_phases(tmp_path: Path) -> None:
    """``plan: null`` / ``apply: null`` disable those phases."""
    scenario = load_text(tmp_path, "fragments: {}\nvalidate: {}\nplan: null\napply: null")
    step = scenario.steps[0]
    assert step.plan is None and step.apply is None and step.validate == ValidateSpec(ok=True)


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("{}", ValidateSpec(ok=True)),
        ("{errors: 2}", ValidateSpec(ok=False, errors=2)),
        ("{errors: 0}", ValidateSpec(ok=True, errors=0)),
        ("{ok: false, contains: [boom]}", ValidateSpec(ok=False, contains=["boom"])),
    ],
)
def test_validate_ok_inference(tmp_path: Path, spec: str, expected: ValidateSpec) -> None:
    """``ok`` defaults to ``errors == 0``."""
    assert load_text(tmp_path, f"validate: {spec}").steps[0].validate == expected


def test_validate_ok_contradicting_errors(tmp_path: Path) -> None:
    """ok and errors must agree."""
    assert_error(tmp_path, "contradicts", "validate: {ok: true, errors: 1}")


def test_tier_must_match_directory(tmp_path: Path) -> None:
    """A tier that does not belong in its directory is refused; outside known dirs the tier is required."""
    assert_error(tmp_path, "does not belong", header="tier: cli", tier_dir="offline")
    assert_error(tmp_path, "does not belong", header="tier: offline", tier_dir="enterprise")
    assert_error(tmp_path, "missing 'tier'", tier_dir="elsewhere")
    assert_error(tmp_path, "missing 'tier'", tier_dir="regressions")  # regressions live in the domains of scenarios/cli
    assert load_text(tmp_path, header="tier: enterprise", tier_dir="elsewhere").tier == "enterprise"
    assert load_text(tmp_path, tier_dir="cli").tier == "cli"


def test_tier_comes_from_the_directory_below_scenarios(tmp_path: Path) -> None:
    """Subdirectories inherit the tier of the tier directory right below scenarios/: an offline scenario may live in
    scenarios/offline/cli/ (the inner 'cli' is a topic, not the live tier) and a live one in scenarios/cli/org/."""
    root = tmp_path / "scenarios"
    _, text = scenario_yaml()
    assert load_scenario(write(root, "offline/cli/output/case.yaml", text)).tier == "offline"
    assert load_scenario(write(root, "cli/org/case.yaml", text)).tier == "cli"
    assert load_scenario(write(root, "enterprise/org/case.yaml", text)).tier == "enterprise"
    with pytest.raises(ScenarioError, match=r"does not belong in scenarios/offline/"):
        load_scenario(write(root, "offline/cli/bad.yaml", "tier: cli\n" + text))
    assert tier_directory(root / "cli" / "org" / "case.yaml") == "cli"
    assert tier_directory(root / "offline" / "cli" / "case.yaml") == "offline"
    assert tier_directory(tmp_path / "elsewhere" / "case.yaml") is None


def test_domain_directories(tmp_path: Path) -> None:
    """scenarios/<tier>/<domain>/<file>.yaml: the domain is the directory right below the tier directory (an inner
    tier name included); domain_problem refuses files outside a domain directory, unknown or nested directories and a
    model domain without its tag, and ignores files outside the tier directories."""
    root = tmp_path / "scenarios"
    assert scenario_domain(root / "offline" / "cli" / "case.yaml") == "cli"
    assert scenario_domain(root / "cli" / "repo" / "sub" / "case.yaml") == "repo"
    assert scenario_domain(root / "cli" / "case.yaml") is None
    assert scenario_domain(tmp_path / "elsewhere" / "case.yaml") is None
    _, text = scenario_yaml(header="tags: [repo]")

    def problem(relative: str, body: str = text) -> str | None:
        return domain_problem(load_scenario(write(root, relative, body)))

    assert problem("cli/repo/case.yaml") is None
    assert problem("cli/plan/case.yaml") is None  # cross-cutting domains need no tag
    assert "domain directory scenarios/<tier>/<domain>/" in str(problem("cli/case.yaml"))
    assert "'org' is not a domain directory" in str(problem("cli/org/case.yaml"))
    assert "no subdirectory below the domain directory 'repo'" in str(problem("cli/repo/sub/case.yaml"))
    assert "carries the 'teams' tag" in str(problem("cli/teams/case.yaml"))
    assert domain_problem(load_scenario(write(tmp_path, "elsewhere/case.yaml", "tier: cli\n" + text))) is None


def test_cases_narrow_the_scenario_to_one_step(tmp_path: Path) -> None:
    """Scenario.cases: one copy per step (same id and metadata), ``case`` names the step, ``case_id`` <id>/<step>."""
    scenario = load_scenario(
        write(tmp_path, "cli/repo/case.yaml", "id: cli.x\ntitle: x\ntags: [repo]\nsteps: [{name: a}, {name: b}]\n")
    )
    assert (scenario.case, scenario.case_id) == (None, "cli.x")
    cases = scenario.cases()
    assert [(case.id, case.case, case.case_id, [s.name for s in case.steps]) for case in cases] == [
        ("cli.x", "a", "cli.x/a", ["a"]),
        ("cli.x", "b", "cli.x/b", ["b"]),
    ]
    assert cases[0].tags == scenario.tags and len(scenario.steps) == 2


@pytest.mark.parametrize(
    ("header", "step", "match"),
    [
        ("colour: red", "", r"unknown key\(s\) \['colour'\]"),
        ("", "fragments: {}\nplan: {expected: changes}", r"unknown key\(s\) \['expected'\]"),
        ("", "fragments: {}\napply: {force: true}", r"unknown key\(s\) \['force'\]"),
        ("", "fragments: {}\nvalidate: {ok: true, error: 1}", r"unknown key\(s\) \['error'\]"),
        ("", "fragments: {}\nplan: {counts: {added: 1}}", r"unknown key\(s\) \['added'\]"),
        ("", "fragments: {}\nwait: 3", r"unknown key\(s\) \['wait'\]"),
        ("", "fragments: {repos: []}", "unknown fragment key"),
        ("", "state: [{kind: repo, name: x, matches: {}}]", "unknown key"),
        ("expect_failure_without: [private_pages]", "on_missing_capability: {skip: true}", "unknown key"),
    ],
)
def test_unknown_keys_are_refused(tmp_path: Path, header: str, step: str, match: str) -> None:
    """Strict validation of every mapping of the format."""
    assert_error(tmp_path, match, step, header=header)


@pytest.mark.parametrize(
    ("header", "step", "match"),
    [
        ("priority: P9", "", "priority"),
        ("min_plan: gold", "", "min_plan"),
        ("requires: [warp_drive]", "", "unknown capability"),
        ("identities: [mallory]", "", "identities"),
        ("tags: [Bad Tag]", "", "tags"),
        ("known_bug: BUG-1", "", "known_bug"),
        ("org_level: yes please", "", "org_level"),
        ("cleanup: later", "", "cleanup"),
        ("variables: {p: x}", "", "provided by the engine"),
        ("variables: {plan: 3}", "", "variables.plan"),
        ("", "fragments: {}\nplan: {expect: maybe}", "expect"),
        ("", "fragments: {}\napply: {expect: done}", "expect"),
        ("", "fragments: {}\nplan: {counts: {add: -1}}", "non-negative"),
        ("", "fragments: {}\nplan: {counts: {add: true}}", "non-negative"),
        ("", "fragments: {}\nconverge: maybe", "converge"),
        ("", "state: [{kind: no_such_kind, name: x, absent: true}]", "unknown check kind"),
        ("", "state: [{kind: team_members, slug: x, absent: true}]", "single-object"),
        ("", "state: [{kind: repo_secret, name: x, absent: true}]", "repo"),
        ("", "state: [{kind: repo, name: x, absent: true, equals: 1}]", "exactly one"),
        ("", "state: [{kind: repo, name: x, match: {name: {$regex: '('}}}]", "regex"),
        ("", "on_missing_capability: {apply: {expect: error}}", "requires expect_failure_without"),
    ],
)
def test_bad_values_are_refused(tmp_path: Path, header: str, step: str, match: str) -> None:
    """Enumerations, capability and identity names, formats and check forms are validated."""
    assert_error(tmp_path, match, step, header=header)


def test_required_keys_and_empty_steps(tmp_path: Path) -> None:
    """id, title and a non-empty step list are required."""
    with pytest.raises(ScenarioError, match="missing required key 'title'"):
        load_scenario(write(tmp_path, "cli/a.yaml", "id: a\nsteps: [{fragments: {}}]\n"))
    with pytest.raises(ScenarioError, match="non-empty list"):
        load_scenario(write(tmp_path, "cli/b.yaml", "id: b\ntitle: b\nsteps: []\n"))
    with pytest.raises(ScenarioError, match="empty scenario file"):
        load_scenario(write(tmp_path, "cli/c.yaml", "\n"))


def test_duplicate_yaml_keys_are_refused(tmp_path: Path) -> None:
    """PyYAML would silently keep the last value: the strict loader refuses duplicates."""
    path = write(tmp_path, "cli/dup.yaml", "id: a\ntitle: a\nid: b\nsteps: [{fragments: {}}]\n")
    with pytest.raises(ScenarioError, match=r"dup.yaml: duplicate key 'id' \(line 3\)"):
        load_scenario(path)


def test_yaml_anchors_and_merge_keys(tmp_path: Path) -> None:
    """Declarative steps repeat objects with anchors; merge keys may be overridden."""
    path = write(
        tmp_path,
        "cli/anchors.yaml",
        """
        id: anchors
        title: anchors
        steps:
          - name: create
            fragments: {repositories: [&repo "orgs.newRepo('{{ p }}-a')"]}
            plan: &plan {expect: changes, contains: [x]}
          - name: keep
            fragments: {repositories: [*repo]}
            plan: {<<: *plan, expect: noop}
        """,
    )
    steps = load_scenario(path).steps
    assert steps[0].fragments.repositories == steps[1].fragments.repositories
    assert steps[1].plan == PlanSpec(expect="noop", contains=["x"])


def test_duplicate_step_names(tmp_path: Path) -> None:
    """Step names identify observations: they must be unique; missing names are numbered."""
    path = write(tmp_path, "cli/s.yaml", "id: s\ntitle: s\nsteps: [{name: a}, {name: a}]\n")
    with pytest.raises(ScenarioError, match=r"duplicate step name\(s\) \['a'\]"):
        load_scenario(path)
    path = write(tmp_path, "cli/t.yaml", "id: t\ntitle: t\nsteps: [{fragments: {}}, {fragments: {}}]\n")
    assert [step.name for step in load_scenario(path).steps] == ["step-1", "step-2"]


def test_load_scenarios_ignores_known_bugs_and_dotfiles(tmp_path: Path) -> None:
    """Recursive and sorted; known_bugs.yaml, dotfiles and non-YAML files are skipped."""
    write(tmp_path, "cli/b.yaml", MINIMAL.replace("cli.repo.basic", "b"))
    write(tmp_path, "cli/a.yaml", MINIMAL.replace("cli.repo.basic", "a"))
    write(tmp_path, "offline/o.yml", "id: o\ntitle: o\nsteps: [{fragments: {}}]\n")
    write(tmp_path, "known_bugs.yaml", "- {id: KB-001, title: x}\n")
    write(tmp_path, "cli/.draft.yaml", "not: a scenario\n")
    write(tmp_path, "cli/notes.txt", "ignored\n")
    assert [s.id for s in load_scenarios(tmp_path)] == ["a", "b", "o"]
    assert [s.id for s in load_scenarios(tmp_path, tier="offline")] == ["o"]
    assert [p.name for p in scenario_files(tmp_path)] == ["a.yaml", "b.yaml", "o.yml"]
    assert load_scenarios(tmp_path / "missing") == []
    with pytest.raises(ScenarioError, match="unknown tier"):
        load_scenarios(tmp_path, tier="webapp")


def test_duplicate_ids_across_files(tmp_path: Path) -> None:
    """Scenario ids are unique within a directory tree."""
    write(tmp_path, "cli/a.yaml", MINIMAL)
    write(tmp_path, "cli/repo/b.yaml", MINIMAL)
    with pytest.raises(ScenarioError, match=r"duplicate scenario id 'cli\.repo\.basic'"):
        load_scenarios(tmp_path)


def test_errors_name_the_file(tmp_path: Path) -> None:
    """Every ScenarioError starts with the scenario path."""
    path = write(tmp_path, "cli/bad.yaml", "id: x\ntitle: x\nsteps: [{plan: {expect: maybe}}]\n")
    with pytest.raises(ScenarioError) as info:
        load_scenario(path)
    assert str(info.value).startswith(f"{path}: steps[0].plan.expect")


# --- fragment rules --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    "settings",
    [
        "plan: 'team'",
        "description: 'wiped'",
        "billing_email: ''",
        "web_commit_signoff_required: true, plan+: 'x'",
        "'description':: null",
    ],
)
def test_settings_fragments_cannot_set_protected_fields(tmp_path: Path, settings: str) -> None:
    """plan, description and billing_email belong to the baseline layer (OC-01, F5)."""
    step = f'fragments: {{settings: ["{settings}"]}}'
    assert_error(tmp_path, "must not set", step, header="org_level: true")


def test_nested_description_in_settings_is_fine(tmp_path: Path) -> None:
    """Only top-level settings fields are protected (custom properties have their own description)."""
    step = """fragments: {settings: ["custom_properties+: [orgs.newCustomProperty('x') { description: 'd' }]"]}"""
    assert load_text(tmp_path, step, header="org_level: true").org_level


def test_live_settings_fragments_require_org_level(tmp_path: Path) -> None:
    """Settings carry no run prefix: only an org-level plan sees them and a reset undoes them."""
    assert_error(tmp_path, "set org_level: true", 'fragments: {settings: ["web_commit_signoff_required: true"]}')


@pytest.mark.parametrize(
    "fragment",
    [
        "repositories: [\"orgs.newRepo('{{ p }}-a') { secrets: [orgs.newRepoSecret('S') { value: 'hunter2' }] }\"]",
        "secrets: [\"orgs.newOrgSecret('{{ P }}_S') { value: 'plain' }\"]",
        "secrets: [\"{ name: 'S', value: 'plain' }\"]",
        "repositories: [\"orgs.newRepo('{{ p }}-a') { secrets+: [{ name: 'S', value: 'raw' }] }\"]",
        "webhooks: [\"orgs.newOrgWebhook('{{ hook_base }}h') { secret: 's3cr3t' }\"]",
        "secrets: [\"orgs.newOrgSecret('S') + { value: 'composed' }\"]",
        "secrets: [\"orgs.newOrgSecret('S') { visibility: 'public' } { value: 'chained' }\"]",
        "secrets: [\"orgs.newOrgSecret('S') { value: std.base64('x') }\"]",
        "secrets: [\"orgs.newOrgSecret('S') { value: 'e2e-dummy-TOOSHORT' }\"]",
    ],
)
def test_secret_values_must_be_dummies(tmp_path: Path, fragment: str) -> None:
    """otterdog prints plain secret values in validate/plan output and PR comments (SPEC 5.8)."""
    with pytest.raises(ScenarioError, match="dummy") as info:
        load_text(tmp_path, f"fragments: {{{fragment}}}")
    for secret in ("hunter2", "s3cr3t", "plain'", "raw", "composed", "chained"):
        assert secret not in str(info.value)


@pytest.mark.parametrize(
    "fragment",
    [
        "secrets: [\"orgs.newOrgSecret('{{ P }}_S') { value: '********' }\"]",
        "secrets: [\"orgs.newOrgSecret('{{ P }}_S') { value: 'e2e-dummy-{{ run }}' }\"]",
        "secrets: [\"orgs.newOrgSecret('{{ P }}_S') { value: null }\"]",
        "webhooks: [\"orgs.newOrgWebhook('{{ hook_base }}h') { secret: 'e2e-dummy-abcdef12', active: true }\"]",
        "variables: [\"orgs.newOrgVariable('{{ P }}_V') { value: 'plain values are fine for variables' }\"]",
        "repositories: [\"orgs.newRepo('{{ p }}-a') { variables: [orgs.newRepoVariable('V') { value: 'x' }] }\"]",
        "repositories: [\"orgs.newRepo('{{ p }}-a') { description: 'secret: value: plain' }\"]",
    ],
)
def test_dummy_secret_values_and_variables_are_accepted(tmp_path: Path, fragment: str) -> None:
    """Dummies (``****``, ``e2e-dummy-<8>`` incl. ``{{ run }}``), null, variables and strings mentioning secrets."""
    load_text(tmp_path, f"fragments: {{{fragment}}}")


def test_rendered_secret_from_a_variable_is_checked(tmp_path: Path) -> None:
    """render_step re-checks the rendered text: variables cannot smuggle plain secret values in."""
    scenario = load_text(
        tmp_path,
        "fragments: {secrets: [\"orgs.newOrgSecret('S') { value: '{{ value }}' }\"]}",
        header="variables: {value: '********'}",
    )
    assert render_step(scenario.steps[0], {**VARIABLES, "value": "********"}).fragments.secrets
    with pytest.raises(ScenarioError, match="dummy"):
        render_step(scenario.steps[0], {**VARIABLES, "value": "real-secret"})


@pytest.mark.parametrize(
    "step",
    [
        "fragments: {teams: [\"orgs.newTeam('{{ p }}-t')\"]}",
        "fragments: {repositories: [\"orgs.newRepo('{{ p }}-a') { team_permissions: {} } + orgs.newTeam('x')\"]}",
        "fragments: {repositories: [\"orgs.newRepo('{{ p }}-a') { code_scanning_default_languages: ['python'] }\"]}",
        "base_fragments: {teams: [\"{ name: 'x' }\"]}",
    ],
)
def test_offline_fragments_cannot_reach_github(tmp_path: Path, step: str) -> None:
    """Teams and code scanning languages make validate/local-plan call GitHub even with --local (OC-04)."""
    assert_error(tmp_path, "offline scenarios cannot", step, tier_dir="offline")


def test_offline_mentions_in_strings_are_fine(tmp_path: Path) -> None:
    """The offline scan looks at tokens, not at strings or comments."""
    step = "fragments: {repositories: [\"orgs.newRepo('{{ p }}-a') { description: 'no newTeam here' } /* newTeam */\"]}"
    assert load_text(tmp_path, step, tier_dir="offline").tier == "offline"


@pytest.mark.parametrize(
    ("header", "step", "match"),
    [
        ("", "fragments: {}\napply: {expect: ok}", "cannot apply"),
        ("", "state: [{kind: repo, name: x, absent: true}]", "no oracle"),
        ("requires: [public_repos]", "", "cannot depend"),
        ("identities: [author]", "", "cannot depend"),
        ("org_level: true", "", "no org to reset"),
        ("min_plan: team", "", "variables.plan"),
    ],
)
def test_offline_tier_restrictions(tmp_path: Path, header: str, step: str, match: str) -> None:
    """Offline scenarios never apply, never check state and never depend on the live org."""
    assert_error(tmp_path, match, step, header=header, tier_dir="offline")


def test_offline_steps_get_no_apply_and_may_run_commands(tmp_path: Path) -> None:
    """Offline steps never apply; extra commands are parsed with defaults."""
    scenario = load_text(
        tmp_path,
        """
        base_fragments: {}
        commands:
          show-default: {contains: ["newRepo"]}
          canonical-diff:
          --version: {exit_code: null}
        """,
        tier_dir="offline",
    )
    step = scenario.steps[0]
    assert step.apply is None and step.base_fragments == ConfigFragments()
    assert step.commands["show-default"].contains == ["newRepo"] and step.commands["canonical-diff"].exit_code == 0
    assert step.commands["--version"].exit_code is None
    assert_error(tmp_path, "show-live", "commands: {show-live: {}}", tier_dir="offline")


@pytest.mark.parametrize(
    ("step", "match"),
    [("base_fragments: {}", "only offline scenarios"), ("commands: {show-default: {}}", "only offline scenarios")],
)
def test_live_tier_restrictions(tmp_path: Path, step: str, match: str) -> None:
    """BASE configs and extra commands are offline-only."""
    assert_error(tmp_path, match, step)


@pytest.mark.parametrize(
    ("snippet", "bad"),
    [
        ("orgs.newRepo('x') // keep", True),
        ("orgs.newRepo('x') # keep", True),
        ("orgs.newRepo('x') /* keep */", False),
        ("orgs.newRepoWebhook('https://otterdog-e2e.invalid/x#frag') { events: ['push'] }", False),
        ("orgs.newRepo('x') // comment\n  { description: 'y' }", False),
    ],
)
def test_trailing_line_comments(snippet: str, bad: bool) -> None:
    """The renderer appends a comma after every fragment: a trailing line comment would swallow it."""
    problems = fragment_problems(ConfigFragments(repositories=[snippet]), offline=False)
    assert bool([p for p in problems if "line comment" in p]) is bad


# --- templates -------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("header", "step", "match"),
    [
        ("", "fragments: {repositories: [\"orgs.newRepo('{{ pp }}-a')\"]}", r"unknown template variable\(s\) \['pp'\]"),
        ("", "fragments: {repositories: [\"orgs.newRepo('{{ p }-a')\"]}", "Jinja syntax error"),
        ("", "state: [{kind: team, slug: '{{ teams.admn }}', absent: false}]", "admn"),
        ("", "plan: {contains: ['{{ undefined_name }}']}", "unknown template variable"),
    ],
)
def test_template_errors_are_found_at_load_time(tmp_path: Path, header: str, step: str, match: str) -> None:
    """Syntax errors, unknown variables and attribute typos fail at load time, not mid-run."""
    assert_error(tmp_path, match, step, header=header)


def test_fixed_in_and_timeout_keys(tmp_path: Path) -> None:
    """fixed_in is a public PEP 440 version, timeout a positive int; both default to None; scenario keys are not
    variables (``variables.fixed_in`` would silently do nothing)."""
    plain = load_text(tmp_path)
    assert plain.fixed_in is None and plain.timeout is None
    scenario = load_text(tmp_path, header="fixed_in: '1.7.0.dev15'\ntimeout: 960")
    assert scenario.fixed_in == "1.7.0.dev15" and scenario.timeout == 960
    assert load_text(tmp_path, header="fixed_in: 1.7.0", tier_dir="offline").fixed_in == "1.7.0"
    assert_error(tmp_path, "fixed_in: 'pr-792' is not a PEP 440 version", header="fixed_in: pr-792")
    assert_error(tmp_path, "local version part", header="fixed_in: 1.7.0.dev15+e2e.g9bdeb75")
    assert_error(tmp_path, "fixed_in: expected a non-empty string", header="fixed_in: 1.7")
    assert_error(tmp_path, "timeout: expected a positive number", header="timeout: 0")
    assert_error(tmp_path, "'fixed_in' is a scenario key", header="variables: {fixed_in: '1.7.0'}")


def test_scenario_variables_are_known_template_variables(tmp_path: Path) -> None:
    """Variables declared by the scenario may be used in its templates."""
    scenario = load_text(tmp_path, "plan: {contains: ['{{ label }}']}", header="variables: {label: hello}")
    rendered = render_step(scenario.steps[0], {**VARIABLES, **scenario.variables})
    assert rendered.plan is not None and rendered.plan.contains == ["hello"]


def test_render_step_renders_every_string_once(tmp_path: Path) -> None:
    """Fragments, contains, state keys and values, overrides are rendered; values are never rendered twice."""
    path = write(
        tmp_path,
        "cli/render.yaml",
        """
        id: render
        title: render
        expect_failure_without: [private_pages]
        variables: {text: placeholder}
        steps:
          - name: keep
            fragments:
              repositories: ["orgs.newRepo('{{ p }}-a') { description: '{{ text }}' }"]
              webhooks: ["orgs.newOrgWebhook('{{ hook_base }}h')"]
            plan: {contains: ['repository[name="{{ p }}-a"]']}
            state:
              - {kind: repo_custom_properties, repo: "{{ p }}-a", match: {"{{ p }}-prop": "{{ logins.admin }}"}}
            on_missing_capability: {plan: {contains: ["{{ org }}"]}}
        """,
    )
    step = load_scenario(path).steps[0]
    rendered = render_step(step, {**VARIABLES, "text": "{{ p }} stays literal"})
    assert rendered.name == "keep"
    assert rendered.fragments.repositories == [
        "orgs.newRepo('e2e-t3c7z8a5-a') { description: '{{ p }} stays literal' }"
    ]
    assert rendered.fragments.webhooks == ["orgs.newOrgWebhook('https://otterdog-e2e.invalid/t3c7z8a5/h')"]
    assert rendered.plan is not None and rendered.plan.contains == ['repository[name="e2e-t3c7z8a5-a"]']
    assert rendered.state == [
        {"kind": "repo_custom_properties", "repo": "e2e-t3c7z8a5-a", "match": {"e2e-t3c7z8a5-prop": "e2e-admin"}}
    ]
    negative = rendered.for_missing_capability()
    assert negative.plan is not None and negative.plan.contains == ["e2e-test-org"]
    assert step.fragments.repositories[0].startswith("orgs.newRepo('{{ p }}-a')")  # the original is untouched


def test_render_step_strict_undefined() -> None:
    """A variable missing at run time (e.g. no App configured) is a ScenarioError naming the step."""
    step = StepSpec(name="s", fragments=ConfigFragments(repositories=["orgs.newRepo('{{ app_slug }}')"]))
    with pytest.raises(ScenarioError, match="step 's': cannot render"):
        render_step(step, {k: v for k, v in VARIABLES.items() if k != "app_slug"})


def test_plain_strings_bypass_jinja() -> None:
    """Strings without Jinja markup are kept verbatim (jsonnet braces are not Jinja); names are never rendered."""
    snippet = "orgs.newRepo('x') { a: { b: 1 } }"
    step = StepSpec(name="{{ p }}", fragments=ConfigFragments(repositories=[snippet]))
    rendered = render_step(step, {})
    assert rendered.fragments.repositories == [snippet] and rendered.name == "{{ p }}"


@pytest.mark.parametrize(
    ("header", "step", "tier_dir", "match"),
    [
        ("", "plan: {contains: ['{{ logins.author }}']}", "cli", r"uses logins \['author'\]: declare them"),
        ("", "plan: {contains: [\"{{ logins['approver'] }}\"]}", "cli", r"uses logins \['approver'\]"),
        ("identities: [author]", "plan: {contains: ['{{ logins.writer }}']}", "cli", "unknown identities"),
        (
            "",
            "fragments: {}\nvalidate: {contains: ['{{ logins.admin }}']}",
            "offline",
            "offline scenarios have no logins",
        ),
    ],
)
def test_logins_must_be_declared_identities(tmp_path: Path, header: str, step: str, tier_dir: str, match: str) -> None:
    """Optional identities used in templates must be declared so that gating skips targets lacking them."""
    assert_error(tmp_path, match, step, header=header, tier_dir=tier_dir)


def test_declared_and_admin_logins_are_accepted(tmp_path: Path) -> None:
    """admin is always configured; declared identities may be used."""
    step = "plan: {contains: ['{{ logins.admin }}', '{{ logins.author }}']}"
    assert load_text(tmp_path, step, header="identities: [author]").identities == ["author"]


def test_step_known_bug_with_phases(tmp_path: Path) -> None:
    """known_bug {id, phases}: the bug explains only those phases; malformed forms are refused."""
    step = load_text(tmp_path, "fragments: {}\nknown_bug: {id: KB-054, phases: [converge, converge]}").steps[0]
    assert step.known_bug == "KB-054" and step.known_bug_phases == ("converge",)
    plain = load_text(tmp_path, "fragments: {}\nknown_bug: KB-054").steps[0]
    assert plain.known_bug == "KB-054" and plain.known_bug_phases is None
    assert_error(
        tmp_path, r"known_bug.phases: unknown phase\(s\) \['render'\]", "known_bug: {id: KB-054, phases: [render]}"
    )
    assert_error(tmp_path, "known_bug.phases: a non-empty list", "known_bug: {id: KB-054, phases: []}")
    assert_error(tmp_path, "known_bug.id: required", "known_bug: {phases: [plan]}")
    assert_error(tmp_path, r"unknown key\(s\) \['why'\]", "known_bug: {id: KB-054, phases: [plan], why: x}")
