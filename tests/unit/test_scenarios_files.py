"""Jsonnet injected from files in scenario YAML (scenarios.model, inject): the forms of fragment entries, libraries,
overlays and offline config files; path and content rules with ``<file>:<line>`` messages; rendering with the file's
rules; the offline engine writing complete config files."""

from __future__ import annotations

import textwrap
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e.inject import SourceText
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.scenarios.model import (
    Scenario,
    ScenarioError,
    fragment_problems,
    load_scenario,
    offline_problems,
    overlay_changes_settings,
    render_step,
)
from otterdog_e2e.scenarios.offline import OFFLINE_ORG, OfflineEngine, offline_run_context
from otterdog_e2e.sut import template as sut_template
from otterdog_e2e.sut.template import offline_template
from otterdog_e2e.testing.fakes import FakeCli

RUN = new_run_context("t3c7z8a5")
VARIABLES: dict[str, Any] = {
    **RUN.template_vars(),
    "org": "e2e-test-org",
    "plan": "free",
    "logins": {"admin": "e2e-admin"},
    "app_slug": "otterdog-e2e-app",
    "teams": {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"},
}
LIBRARY = "// helpers\n{\n  publicRepo(name):: orgs.newRepo(name) { description: 'e2e' },\n}\n"
REPO = "// a repository\norgs.newRepo('{{ p }}-{{ slug }}') {\n  description: '{{ text }}',\n}\n"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """An otterdog-e2e project root with scenarios/lib/e2e.libsonnet and scenarios/fragments/repo.jsonnet."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "otterdog-e2e"\n')
    write(tmp_path / "scenarios" / "lib" / "e2e.libsonnet", LIBRARY)
    write(tmp_path / "scenarios" / "fragments" / "repo.jsonnet", REPO)
    return tmp_path


def write(path: Path, text: str) -> Path:
    """Write ``text`` (dedented) to ``path`` and return it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(text).lstrip("\n"))
    return path


def scenario(project: Path, body: str, *, tier_dir: str = "cli", header: str = "") -> Scenario:
    """Load a scenario written to scenarios/<tier_dir>/case.yaml (``body``: the YAML of its steps)."""
    text = f"id: t.case\ntitle: case\n{textwrap.dedent(header).strip()}\nsteps:\n{textwrap.dedent(body).strip()}\n"
    return load_scenario(write(project / "scenarios" / tier_dir / "case.yaml", text))


def assert_error(project: Path, match: str, body: str, *, tier_dir: str = "cli", header: str = "") -> None:
    """Loading the scenario raises ScenarioError matching ``match``."""
    with pytest.raises(ScenarioError, match=match):
        scenario(project, body, tier_dir=tier_dir, header=header)


# --- forms ------------------------------------------------------------------------------------------------------------
def test_fragment_entries_are_inline_strings_or_files(project: Path) -> None:
    """A fragment entry is a string or a {file, vars} mapping (a single mapping counts as one entry); order is kept."""
    write(project / "scenarios" / "fragments" / "var.jsonnet", "orgs.newOrgVariable('{{ P }}_V')\n")
    loaded = scenario(
        project,
        """
        - name: s1
          fragments:
            repositories:
              - "orgs.newRepo('{{ p }}-inline')"
              - {file: ../fragments/repo.jsonnet, vars: {slug: a, text: first}}
            variables: {file: ../fragments/var.jsonnet}
        """,
    )
    inline, from_file = loaded.steps[0].fragments.repositories
    assert inline == "orgs.newRepo('{{ p }}-inline')" and not isinstance(inline, SourceText)
    assert isinstance(from_file, SourceText) and from_file == REPO
    assert from_file.origin.display == "scenarios/fragments/repo.jsonnet"
    assert from_file.origin.label == "fragments.repositories[1]" and from_file.origin.vars == {
        "slug": "a",
        "text": "first",
    }
    assert loaded.steps[0].fragments.variables == ["orgs.newOrgVariable('{{ P }}_V')\n"]


def test_render_step_renders_files_once_with_their_vars(project: Path) -> None:
    """vars are rendered with the scenario variables, then the file with both; rendered values are never rendered
    again (a var producing '{{ p }}' stays literal)."""
    loaded = scenario(
        project,
        """
        - name: s1
          fragments:
            repositories:
              - file: ../fragments/repo.jsonnet
                vars: {slug: "{{ label }}", text: "{% raw %}{{ p }}{% endraw %} stays"}
        """,
        header="variables: {label: from-variables}",
    )
    rendered = render_step(loaded.steps[0], {**VARIABLES, **loaded.variables})
    (repo,) = rendered.fragments.repositories
    assert (
        repo == "// a repository\norgs.newRepo('e2e-t3c7z8a5-from-variables') {\n  description: '{{ p }} stays',\n}\n"
    )
    assert isinstance(repo, SourceText) and repo.rendered
    assert loaded.steps[0].fragments.repositories[0] == REPO  # the loaded step is untouched


def test_raw_files_are_never_rendered(project: Path) -> None:
    """raw: true inserts the file as it is (Jinja markup included, no name checks)."""
    write(project / "scenarios" / "fragments" / "raw.jsonnet", "orgs.newRepo('{{ unknown }}')\n")
    loaded = scenario(project, "- fragments: {repositories: [{file: ../fragments/raw.jsonnet, raw: true}]}")
    rendered = render_step(loaded.steps[0], VARIABLES)
    assert rendered.fragments.repositories == ["orgs.newRepo('{{ unknown }}')\n"]


def test_libraries_are_attached_to_every_render(project: Path) -> None:
    """A path or a {file} mapping; the libraries are in the fragments of every step and of the -BASE config."""
    loaded = scenario(
        project,
        """
        - name: one
          base_fragments: {}
          fragments: {repositories: ["e2e.publicRepo('{{ p }}-a')"]}
        - name: two
          fragments: {}
        """,
        tier_dir="offline",
        header="libraries: {e2e: ../lib/e2e.libsonnet, more: {file: ../lib/e2e.libsonnet, raw: true}}",
    )
    assert list(loaded.libraries) == ["e2e", "more"] and loaded.libraries["more"].origin.raw
    one, two = loaded.steps
    assert one.base_fragments is not None and list(one.base_fragments.libraries) == ["e2e", "more"]
    assert list(one.fragments.libraries) == list(two.fragments.libraries) == ["e2e", "more"]
    assert one.fragments.libraries["e2e"].origin.label == "libraries.e2e"


@pytest.mark.parametrize(
    ("header", "match"),
    [
        ("libraries: {std: ../lib/e2e.libsonnet}", "library name 'std' is reserved"),
        ("libraries: {orgs: ../lib/e2e.libsonnet}", "reserved"),
        ("libraries: {local: ../lib/e2e.libsonnet}", "reserved"),
        ("libraries: {'my-lib': ../lib/e2e.libsonnet}", "not a jsonnet identifier"),
        ("libraries: {e2e: {path: x}}", r"unknown key\(s\) \['path'\]"),
        ("libraries: {e2e: {raw: true}}", "missing 'file'"),
        ("libraries: [../lib/e2e.libsonnet]", "expected a mapping"),
    ],
)
def test_library_rules(project: Path, header: str, match: str) -> None:
    """Library names are usable jsonnet locals; entries are paths or {file, raw, vars} mappings."""
    assert_error(project, match, "- fragments: {}", header=header)


def test_overlay_forms(project: Path) -> None:
    """overlay: an inline string, a {file} mapping or a list of them; overlays belong to the step's fragments."""
    write(project / "scenarios" / "fragments" / "overlay.jsonnet", "{ _repositories+: [] }\n")
    loaded = scenario(
        project,
        """
        - name: one
          overlay: "{ _repositories+: [] }"
        - name: two
          overlay: {file: ../fragments/overlay.jsonnet}
        - name: three
          overlay: ["{ a:: 1 }", {file: ../fragments/overlay.jsonnet}]
        """,
    )
    one, two, three = loaded.steps
    assert one.fragments.overlays == ["{ _repositories+: [] }"]
    assert isinstance(two.fragments.overlays[0], SourceText) and two.fragments.overlays[0].origin.label == "overlay[0]"
    assert three.fragments.overlays[0] == "{ a:: 1 }" and three.fragments.overlays[1].origin.label == "overlay[1]"


@pytest.mark.parametrize(
    ("header", "overlay", "match"),
    [
        (
            "org_level: true",
            "{ settings: { web_commit_signoff_required: true } }",
            "replaces the organization settings",
        ),
        ("org_level: true", "{ settings+: { description: 'x' } }", r"must not set settings \['description'\]"),
        ("org_level: true", "{ a:: 1 } + { settings+: { plan: 'enterprise' } }", r"settings \['plan'\]"),
        ("", "{ settings+: { web_commit_signoff_required: true } }", "set org_level: true"),
    ],
)
def test_overlay_settings_rules(project: Path, header: str, overlay: str, match: str) -> None:
    """Overlays merge settings (settings+:), never set plan/description/billing_email, and need org_level live."""
    assert_error(project, match, f'- overlay: "{overlay}"', header=header)


def test_overlays_touching_settings(project: Path) -> None:
    """org_level live scenarios and offline scenarios may change other settings through an overlay."""
    overlay = '- overlay: "{ settings+: { web_commit_signoff_required: true } }"'
    assert scenario(project, overlay, header="org_level: true").org_level
    assert scenario(project, overlay, tier_dir="offline").tier == "offline"
    assert overlay_changes_settings("{ settings+: {} }") and not overlay_changes_settings("{ _repositories+: [] }")
    assert not overlay_changes_settings("e2e.overlay()")  # best effort: only object literals are inspected


# --- paths --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("file", "match"),
    [
        ("/etc/hostname", "is absolute"),
        ("../fragments/missing.jsonnet", "not found"),
        ("../../../outside.jsonnet", "outside"),
        ("", "expected a non-empty string"),
    ],
)
def test_file_paths(project: Path, file: str, match: str) -> None:
    """Relative to the scenario file, inside the project, existing."""
    write(project.parent / "outside.jsonnet", "{}\n")
    assert_error(project, match, f"- fragments: {{repositories: [{{file: '{file}'}}]}}")


@pytest.mark.parametrize(
    ("entry", "match"),
    [
        ("{file: ../fragments/repo.jsonnet, raw: true, vars: {slug: a}}", "a raw file is never rendered"),
        ("{file: ../fragments/repo.jsonnet, vars: {p: x}}", "provided by the engine"),
        ("{file: ../fragments/repo.jsonnet, vars: {import_path: x}}", "provided by the engine"),
        ("{file: ../fragments/repo.jsonnet, vars: {'bad-name': x}}", "does not match"),
        ("{file: ../fragments/repo.jsonnet, raw: maybe}", "expected true or false"),
        ("{file: ../fragments/repo.jsonnet, encoding: utf-8}", r"unknown key\(s\) \['encoding'\]"),
        ("{vars: {}}", "missing 'file'"),
        ("42", "expected a jsonnet string or a {file: <path>} mapping, got int"),
    ],
)
def test_file_reference_rules(project: Path, entry: str, match: str) -> None:
    """vars are identifiers that do not shadow engine variables, raw files take no vars, keys are file/raw/vars."""
    assert_error(project, match, f"- fragments: {{repositories: [{entry}]}}")


# --- content rules ------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "content", "match"),
    [
        ("f.jsonnet", "orgs.newRepo('{{ p }}-a') {\n  d: importstr 'x',\n}\n", r"\(scenarios/fragments/f\.jsonnet:2\)"),
        ("f.jsonnet", "local x = import 'x.libsonnet';\norgs.newRepo('{{ p }}-a')\n", "import is not allowed"),
        ("f.jsonnet", "orgs.newRepo('{{ p }}-a') { d: importbin 'x' }\n", "importbin is not allowed"),
        (
            "f.jsonnet",
            "orgs.newRepo('{{ p }}-a') {\n  secrets: [\n    orgs.newRepoSecret('S') { value: 'real' },\n  ],\n}\n",
            r"\(scenarios/fragments/f\.jsonnet:3\): value is not a dummy value",
        ),
        ("f.jsonnet", "orgs.newRepo('{{ p }}-a')\n// the end\n", r"f\.jsonnet:2\): ends with a line comment"),
        ("f.jsonnet", "orgs.newRepo('{{ p }}-a') {\n\n  d: '{{ nope }}',\n}\n", r"\['nope'\] in .*f\.jsonnet:3\)"),
        ("f.jsonnet", "orgs.newRepo('{{ p }}-a') {\n  d: '{{ p }',\n}\n", r"Jinja syntax error in .*f\.jsonnet:2\)"),
        (
            "f.jsonnet",
            "orgs.newRepo('{{ p }}-a') { d: '{{ import_path }}' }\n",
            r"unknown template variable.*import_path",
        ),
    ],
)
def test_file_content_problems_name_the_file_and_line(project: Path, path: str, content: str, match: str) -> None:
    """Imports, secrets, trailing comments and Jinja errors of a file are reported with ``<file>:<line>``."""
    write(project / "scenarios" / "fragments" / path, content)
    assert_error(project, match, f"- fragments: {{repositories: [{{file: ../fragments/{path}}}]}}")


def test_secret_messages_never_quote_the_value(project: Path) -> None:
    """A non-dummy secret in a file is named by file and line, never by value."""
    write(project / "scenarios" / "fragments" / "s.jsonnet", "orgs.newOrgSecret('{{ P }}_S') { value: 'hunter2' }\n")
    with pytest.raises(ScenarioError) as info:
        scenario(project, "- fragments: {secrets: [{file: ../fragments/s.jsonnet}]}")
    assert "s.jsonnet:1" in str(info.value) and "hunter2" not in str(info.value)


@pytest.mark.parametrize(
    ("header", "body", "match"),
    [
        ("", "- fragments: {repositories: [\"orgs.newRepo('x') { d: import 'y' }\"]}", "import is not allowed"),
        ("", "- overlay: \"{ d: importstr '/etc/hostname' }\"", "importstr is not allowed"),
        ("libraries: {bad: ../fragments/lib.libsonnet}", "- fragments: {}", r"libraries\.bad \(scenarios/fragments"),
    ],
)
def test_imports_are_refused_everywhere(project: Path, header: str, body: str, match: str) -> None:
    """Inline fragments, overlays and libraries may not import (the webapp evaluates ONE file)."""
    write(project / "scenarios" / "fragments" / "lib.libsonnet", "local x = import 'helpers.libsonnet';\nx\n")
    assert_error(project, match, body, header=header)


def test_strings_mentioning_import_are_fine(project: Path) -> None:
    """Only the keywords count: field names in quotes and strings are not statements."""
    loaded = scenario(project, "- fragments: {repositories: [\"orgs.newRepo('{{ p }}-a') { 'import': 'importstr' }\"]}")
    assert loaded.steps[0].fragments.repositories


def test_offline_rules_apply_to_files(project: Path) -> None:
    """newTeam and code_scanning_default_languages are refused offline, in files and libraries too."""
    write(project / "scenarios" / "lib" / "teams.libsonnet", "{ team(n):: orgs.newTeam(n) }\n")
    assert_error(
        project,
        r"libraries\.t .*newTeam",
        "- fragments: {}",
        tier_dir="offline",
        header="libraries: {t: ../lib/teams.libsonnet}",
    )
    write(
        project / "scenarios" / "fragments" / "cs.jsonnet",
        "orgs.newRepo('{{ p }}-a') {\n  code_scanning_default_languages: ['go'],\n}\n",
    )
    body = "- fragments: {repositories: [{file: ../fragments/cs.jsonnet}]}"
    assert_error(project, r"cs\.jsonnet:2\): offline scenarios cannot use code_scanning", body, tier_dir="offline")


def test_offline_logins_in_files_are_refused(project: Path) -> None:
    """Offline scenarios have no logins, in files and their vars too."""
    write(project / "scenarios" / "fragments" / "l.jsonnet", "orgs.newRepo('{{ p }}-{{ who }}')\n")
    body = "- fragments: {repositories: [{file: ../fragments/l.jsonnet, vars: {who: '{{ logins.admin }}'}}]}"
    assert_error(project, r"offline scenarios have no logins .*vars\.who", body, tier_dir="offline")


# --- offline config files -----------------------------------------------------------------------------------------
CONFIG = """\
local orgs = import '{{ import_path }}';

orgs.newOrg('{{ project }}', '{{ org }}') {
  settings+: { plan: '{{ plan }}', description: '[otterdog-e2e] offline' },
  _repositories+: [orgs.newRepo('{{ p }}-cfg')],
}
"""


def test_offline_config_files(project: Path) -> None:
    """config/base_config: complete configs with the template import (the only import allowed) and the extra
    variables import_path and project."""
    write(project / "scenarios" / "fragments" / "config.jsonnet", CONFIG)
    loaded = scenario(
        project,
        "- {config: {file: ../fragments/config.jsonnet}, base_config: {file: ../fragments/config.jsonnet}}",
        tier_dir="offline",
    )
    step = loaded.steps[0]
    assert isinstance(step.config, SourceText) and step.config.origin.role == "config"
    assert step.base_config is not None and step.base_config.origin.label == "base_config"
    variables = {**VARIABLES, "import_path": "vendor/x/y.libsonnet", "project": "proj"}
    rendered = render_step(step, variables)
    assert rendered.config is not None and "import 'vendor/x/y.libsonnet';" in rendered.config
    assert "orgs.newOrg('proj', 'e2e-test-org')" in rendered.config
    with pytest.raises(ScenarioError, match="import is not allowed"):  # another import path than the template's
        render_step(step, {**variables, "import_path": None, "project": "proj"})


@pytest.mark.parametrize(
    ("content", "body", "tier_dir", "match"),
    [
        (CONFIG + "+ import 'other.libsonnet'\n", "- config: {file: ../fragments/c.jsonnet}", "offline", "only import"),
        (CONFIG, "- {config: {file: ../fragments/c.jsonnet}, fragments: {repositories: ['x']}}", "offline", "drop"),
        (CONFIG, "- {config: {file: ../fragments/c.jsonnet}, overlay: '{}'}", "offline", "drop fragments/overlay"),
        (CONFIG, "- {base_config: {file: ../fragments/c.jsonnet}, base_fragments: {}}", "offline", "not both"),
        (CONFIG, "- config: {file: ../fragments/c.jsonnet}", "cli", "only offline scenarios replace"),
        (CONFIG, "- base_config: {file: ../fragments/c.jsonnet}", "cli", "only offline scenarios replace"),
        (CONFIG, "- config: ../fragments/c.jsonnet", "offline", r"expected a \{file: <path>\} mapping, got str"),
    ],
)
def test_config_file_rules(project: Path, content: str, body: str, tier_dir: str, match: str) -> None:
    """Config files are offline only, replace fragments/overlay (base_config: base_fragments) and import nothing
    else than the template."""
    write(project / "scenarios" / "fragments" / "c.jsonnet", content)
    assert_error(project, match, body, tier_dir=tier_dir)


class Workspace:
    """ConfigWorkspace stand-in recording the files written."""

    def __init__(self) -> None:
        """The offline organization with the offline template."""
        self.org = self.project = OFFLINE_ORG
        self.template = offline_template()
        self.org_dir = Path("/nonexistent/orgs") / OFFLINE_ORG
        self.writes: list[str] = []
        self.base_writes: list[str] = []

    def write_org_config(self, text: str) -> Path:
        """Record the org config."""
        self.writes.append(text)
        return self.org_dir / f"{self.org}.jsonnet"

    def write_base_config(self, text: str) -> Path:
        """Record the -BASE config."""
        self.base_writes.append(text)
        return self.org_dir / f"{self.org}.jsonnet-BASE"

    def write_otterdog_json(self) -> Path:
        """Nothing to write."""
        return self.org_dir


def test_offline_engine_writes_config_files(project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The engine writes a config file as it is (no rendering around it), the base_config as the -BASE file, and
    runs local-plan because a BASE config exists."""
    monkeypatch.setattr(sut_template, "vendor_template", lambda *args: None)
    write(project / "scenarios" / "fragments" / "config.jsonnet", CONFIG)
    loaded = scenario(
        project,
        """
        - name: diff
          config: {file: ../fragments/config.jsonnet}
          base_fragments: {}
          plan: {expect: any}
        """,
        tier_dir="offline",
    )
    workspace = Workspace()
    cli = FakeCli(org=OFFLINE_ORG, workspace=workspace)
    engine = OfflineEngine(
        cli=cli,  # type: ignore[arg-type]
        workspace=workspace,  # type: ignore[arg-type]
        template_src=Path("/nonexistent"),
        run_ctx=offline_run_context(),
    )
    outcome = engine.run(loaded)
    assert [call.command for call in cli.calls] == ["validate", "local-plan", "show"], outcome.failures
    (config,) = workspace.writes
    assert config.startswith(f"local orgs = import '{offline_template().import_path}';")
    assert f"orgs.newOrg('{OFFLINE_ORG}', '{OFFLINE_ORG}')" in config and "e2e-spduo000-cfg" in config
    (base,) = workspace.base_writes
    assert base.startswith("/*") and "e2e-spduo000-cfg" not in base  # the rendered bare organization


def test_offline_engine_variables_include_the_config_variables() -> None:
    """import_path and project come from the workspace (the template it vendors)."""
    workspace = SimpleNamespace(org=OFFLINE_ORG, project="proj", template=offline_template())
    engine = OfflineEngine(
        cli=FakeCli(org=OFFLINE_ORG),  # type: ignore[arg-type]
        workspace=workspace,  # type: ignore[arg-type]
        template_src=Path("/nonexistent"),
        run_ctx=offline_run_context(),
    )
    loaded = SimpleNamespace(variables={}, plan_override=None)
    variables = engine.variables_for(loaded)  # type: ignore[arg-type]
    assert variables["import_path"] == offline_template().import_path and variables["project"] == "proj"


# --- helpers of the lint and backward compatibility -----------------------------------------------------------------
def test_offline_problems_lists_github_constructs() -> None:
    """The scenario lint skips steps whose validation calls GitHub (teams, newTeam, code scanning languages)."""
    assert offline_problems(ConfigFragments(repositories=["orgs.newRepo('a')"])) == []
    teams = ConfigFragments(teams=["orgs.newTeam('t')"])
    assert offline_problems(teams) == ["teams fragments", "newTeam"]
    scanning = ConfigFragments(
        overlays=["{ _repositories+: [orgs.newRepo('a') { code_scanning_default_languages: [] }] }"]
    )
    assert offline_problems(scanning) == ["code_scanning_default_languages"]


@pytest.mark.parametrize(
    ("snippet", "github"),
    [
        (
            "orgs.newRepo('a') { code_scanning_default_setup_enabled: false, code_scanning_default_languages: ['cobol'] }",
            False,
        ),
        (
            "orgs.newRepo('a') { code_scanning_default_languages: ['go'], code_scanning_default_setup_enabled: false }",
            False,
        ),
        (
            "orgs.newRepo('a') { code_scanning_default_setup_enabled:: false, code_scanning_default_languages: ['go'] }",
            False,
        ),
        (
            "orgs.newRepo('a') { code_scanning_default_setup_enabled: true, code_scanning_default_languages: ['go'] }",
            True,
        ),
        ("orgs.newRepo('a') { code_scanning_default_languages: ['go'] }", True),  # the template may enable the setup
        (
            "orgs.newRepo('a') { workflows+: { code_scanning_default_setup_enabled: false }, code_scanning_default_languages: [] }",
            True,
        ),
        (
            "orgs.newRepo('a') { code_scanning_default_setup_enabled: std.isString('x'), code_scanning_default_languages: [] }",
            True,
        ),
    ],
)
def test_code_scanning_languages_validate_offline_with_the_setup_disabled(snippet: str, github: bool) -> None:
    """Validation reads the repository languages from GitHub only while the default setup is enabled: languages beside
    a literal ``code_scanning_default_setup_enabled: false`` of the same object are validated offline."""
    found = offline_problems(ConfigFragments(repositories=[snippet]))
    assert (found == ["code_scanning_default_languages"]) is github, found
    assert bool(fragment_problems(ConfigFragments(repositories=[snippet]), offline=True)) is github


def test_inline_scenarios_load_as_before(project: Path) -> None:
    """Scenarios without files: plain strings, no libraries, no overlays, no config files."""
    loaded = scenario(project, "- fragments: {repositories: \"orgs.newRepo('{{ p }}-a')\"}")
    step = loaded.steps[0]
    assert step.fragments.repositories == ["orgs.newRepo('{{ p }}-a')"] and type(step.fragments.repositories[0]) is str
    assert step.fragments.libraries == {} and step.fragments.overlays == [] and step.config is step.base_config is None
    assert loaded.libraries == {}
