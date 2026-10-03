"""otterdog's own configuration, offline: discovery, file formats, defaults override, organization entries, archived
organizations, organization selection, template URLs, the local mode and missing files.

Behaviour of otterdog/cli.py (``load_otterdog_config``, ``_execute_operation``), otterdog/config.py
(``OtterdogConfig.from_file``, ``OrganizationConfig.from_dict``), otterdog/jsonnet.py (``init_template``) and
otterdog/utils.py (``parse_template_url``), identical in v1.6.1 and main 9bdeb75 and verified offline:

* without ``-c`` otterdog looks for otterdog.jsonnet, then otterdog.json, in ``$OTTERDOG_CONFIG_ROOT`` (else the cwd),
  and exits 2 when neither exists; ``-c`` of a missing file is a click usage error;
* otterdog.jsonnet is evaluated as jsonnet (#542), otterdog.json must hold one JSON object;
* ``.otterdog-defaults.json`` next to the configuration file is deep-merged over its ``defaults``, its values win (#725);
* ``defaults.jsonnet.base_template`` is always required, even when every organization has its own;
* organization entries need ``name`` and ``github_id``, ``credentials`` may not be null and ``approval_teams`` /
  ``admin_teams`` are a string or a list of strings; entries with ``archived: true`` are ignored entirely (#463);
* the ORGANIZATIONS positional selects by project name or github_id, case-insensitively, in the given order; without
  it every organization is processed and the exit status is the largest of theirs;
* template URLs must be ``https://github.com/<owner>/<repo>#<file>@<ref>``; ``--local`` never clones and fails when
  ``<org dir>/vendor/<repo>/<file>`` is missing (validate and show exit 2, local-plan reports 'planning aborted', 1);
* a missing organization configuration: validate/show exit 1 with "... does not exist, run 'fetch-config' or 'import'
  first.", local-plan with "... does not yet exist, run fetch-config or import first.".

Every configuration error that stops the loading is printed as a boxed ``Error: <message>`` and exits 2. Paths in
messages are matched by their workspace-relative tail (container runtimes see the workspace as /ws).
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from otterdog_e2e.otterdog.output import normalize_text, strip_ansi
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
from otterdog_e2e.otterdog.workspace import (
    CONFIG_FILE,
    JSONNET_CONFIG_FILE,
    ConfigWorkspace,
    WorkspaceLayout,
    jsonnet_config_text,
)
from otterdog_e2e.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_ORG,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)
from otterdog_e2e.sut.template import vendor_template

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

RUN = offline_run_context()
SECOND = f"{OFFLINE_ORG}-2"  # github_id of the second organization
SECOND_PROJECT = f"{OFFLINE_ORG}-two"  # its project name
OTHER = f"{OFFLINE_ORG}-other"
ARCHIVED = f"{OFFLINE_ORG}-archived"
JSONNET_PROJECT = f"{OFFLINE_ORG}-jsonnet"
ONE_ERROR = ConfigFragments(settings=["description: std.repeat('d', 161)"])
DESCRIPTION_ERROR = "setting 'description' exceeds maximum allowed length of 160 chars."
SUCCEEDED = "Validation succeeded"
NOT_FOUND = (
    """No configuration file specified, and default files "['otterdog.jsonnet', 'otterdog.json']" not found in "."."""
)
NEED_BASE_TEMPLATE = "need to define a base template in your otterdog config, key: 'defaults.jsonnet.base_template'"
MISSING_CONFIG = "' does not exist, run 'fetch-config' or 'import' first."
MISSING_CONFIG_PLAN = "' does not yet exist, run fetch-config or import first."


def render_org(
    workspace: ConfigWorkspace, fragments: ConfigFragments, *, org: str | None = None, project: str | None = None
) -> str:
    """The configuration of an organization of the workspace (default: its own) with ``fragments``, rendered as
    OfflineEngine renders the offline organization."""
    renderer = OfflineConfigRenderer(
        template=workspace.template,
        org=org or workspace.org,
        plan=OFFLINE_DEFAULT_PLAN,
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
        project=project or (workspace.project if org is None else org),
    )
    return renderer.render(fragments)


def text_of(result: CliResult) -> str:
    """The normalized output (boxes unwrapped)."""
    return normalize_text(result.output)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(text_of(result).splitlines()[-lines:])


def projects_table(result: CliResult) -> list[list[str]]:
    """Body rows (project name, GitHub ID, index) of the list-projects table (none when no table was printed)."""
    rows: list[list[str]] = []
    started = False
    for line in strip_ansi(result.output).splitlines():
        if "│" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("│").split("│")]
        if cells == ["Project name", "GitHub ID", "Index"]:
            started = True
        elif started and len(cells) == 3:
            rows.append(cells)
    return rows


def headers(result: CliResult) -> list[str]:
    """The ``Project <name>[github_id=<id>] (<i>/<n>)`` lines, in order."""
    return [line.strip() for line in text_of(result).splitlines() if line.startswith("Project ")]


def header(project: str, github_id: str, index: int, count: int) -> str:
    """One project header line."""
    return f"Project {project}[github_id={github_id}] ({index}/{count})"


def config_error(result: CliResult, message: str) -> None:
    """The command stopped on a configuration error: exit 2 and the boxed message, nothing processed."""
    text = text_of(result)
    assert result.exit_code == 2, f"exit {result.exit_code}, expected 2 for {message!r}\n{tail(result)}"
    assert f"Error: {message}" in text, f"{message!r} not printed\n{tail(result)}"
    assert not headers(result) and not projects_table(result), f"an organization was processed\n{tail(result)}"


def validate_org(cli: OtterdogCli, *organizations: str) -> CliResult:
    """``validate --local [organizations...]`` (no positional: every organization)."""
    return cli.run("validate", *organizations, org=False, local=True)


# --- discovery and file formats -------------------------------------------------------------------------------------
@pytest.mark.scenario("O-CONFIG-DISCOVERY")
def test_configuration_is_discovered_in_the_config_root(vendored_cli: OtterdogCli) -> None:
    """Without -c and with OTTERDOG_CONFIG_ROOT set to the workspace, otterdog uses its otterdog.json; once an
    otterdog.jsonnet naming another project (same github_id) sits next to it, the jsonnet file wins."""
    workspace = vendored_cli.workspace
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    found = vendored_cli.invoke("validate", "--local", config_root=True)
    assert found.exit_code == 0 and SUCCEEDED in text_of(found), tail(found)
    assert headers(found) == [header(OFFLINE_ORG, OFFLINE_ORG, 1, 1)], tail(found)

    document = workspace.otterdog_json()
    document["organizations"][0]["name"] = JSONNET_PROJECT
    (workspace.root / JSONNET_CONFIG_FILE).write_text(jsonnet_config_text(document), encoding="utf-8")
    assert (workspace.root / CONFIG_FILE).is_file()
    both = vendored_cli.invoke("validate", "--local", config_root=True)
    assert both.exit_code == 0 and SUCCEEDED in text_of(both), tail(both)
    assert headers(both) == [header(JSONNET_PROJECT, OFFLINE_ORG, 1, 1)], f"otterdog.jsonnet must win\n{tail(both)}"
    listed = vendored_cli.invoke("list-projects", config_root=True).assert_ok("list-projects")
    assert projects_table(listed) == [[JSONNET_PROJECT, OFFLINE_ORG, "1"]], listed.output


@pytest.mark.scenario("O-CONFIG-DISCOVERY")
def test_no_configuration_file_found(offline_cli: OtterdogCli) -> None:
    """Without -c nor OTTERDOG_CONFIG_ROOT, in an empty cwd, nothing is found: exit 2 with the default file names; -c
    of a file that does not exist is a click usage error (exit 2, on stderr)."""
    missing = offline_cli.invoke("validate", "--local")
    config_error(missing, NOT_FOUND)
    path = str(offline_cli.workspace.root.resolve() / "missing.json")
    absent = offline_cli.invoke("validate", "-c", path, "--local")
    stderr = strip_ansi(absent.stderr)
    assert absent.exit_code == 2, tail(absent)
    assert "Invalid value for '-c' / '--config'" in stderr and "missing.json' does not exist." in stderr, stderr


@pytest.mark.scenario("O-CONFIG-JSONNET")
def test_jsonnet_configuration_file(vendored_cli: OtterdogCli) -> None:
    """otterdog.jsonnet (the document behind a jsonnet ``local``, which no JSON parser accepts) works like
    otterdog.json for validate and list-projects."""
    workspace = vendored_cli.workspace
    workspace.use_layout(WorkspaceLayout(format="jsonnet"))
    assert workspace.config_file.name == JSONNET_CONFIG_FILE and not (workspace.root / CONFIG_FILE).exists()
    assert workspace.config_file.read_text(encoding="utf-8").count("local config = {") == 1
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    result = vendored_cli.validate(local=True)
    assert result.exit_code == 0 and SUCCEEDED in text_of(result), tail(result)
    assert headers(result) == [header(OFFLINE_ORG, OFFLINE_ORG, 1, 1)], tail(result)
    listed = vendored_cli.list_projects().assert_ok("list-projects")
    assert projects_table(listed) == [[OFFLINE_ORG, OFFLINE_ORG, "1"]], listed.output


@pytest.mark.scenario("O-CONFIG-JSONNET")
@pytest.mark.parametrize(
    ("name", "text", "message"),
    [
        pytest.param(CONFIG_FILE, '{"defaults": {', "failed to parse json file '", id="malformed-json"),
        pytest.param(CONFIG_FILE, "[1, 2]", "expected JSON object in file '", id="json-array"),
        pytest.param(JSONNET_CONFIG_FILE, "local x = ;\nx\n", "failed to evaluate jsonnet file", id="jsonnet-error"),
    ],
)
def test_unreadable_configuration_file(offline_cli: OtterdogCli, name: str, text: str, message: str) -> None:
    """A configuration file that does not hold one JSON object (or does not evaluate) stops every command with exit
    2: 'failed to parse json file', 'expected JSON object in file', 'failed to evaluate jsonnet file'."""
    path = offline_cli.workspace.root / name
    path.write_text(text, encoding="utf-8")
    result = offline_cli.invoke("list-projects", "-c", str(path.resolve()))
    config_error(result, message)
    if name == CONFIG_FILE:
        assert f"{name}'" in text_of(result), f"the message names the file\n{tail(result)}"


# --- defaults override and the base template -------------------------------------------------------------------------
@pytest.mark.scenario("O-CONFIG-DEFAULTS-OVERRIDE")
def test_defaults_override_wins_over_the_configuration_file(vendored_cli: OtterdogCli, template_src: Any) -> None:
    """.otterdog-defaults.json {"jsonnet": {"config_dir": "orgs-override"}} next to otterdog.json (whose config_dir
    is "orgs") moves the organization directory to orgs-override/; without the override the same command reads orgs/,
    where no configuration exists."""
    workspace = vendored_cli.workspace
    workspace.use_layout(WorkspaceLayout(defaults_override={"jsonnet": {"config_dir": "orgs-override"}}))
    assert json.loads(workspace.config_file.read_text(encoding="utf-8"))["defaults"]["jsonnet"]["config_dir"] == "orgs"
    assert workspace.defaults_override_file.is_file() and workspace.config_dir == "orgs-override"
    vendor_template(template_src, workspace.org_dir, workspace.template)
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    assert workspace.org_config_file.parts[-3] == "orgs-override"
    overridden = vendored_cli.validate(local=True)
    assert overridden.exit_code == 0 and SUCCEEDED in text_of(overridden), tail(overridden)

    workspace.use_layout(WorkspaceLayout())  # removes .otterdog-defaults.json
    assert not workspace.defaults_override_file.exists()
    plain = vendored_cli.validate(local=True)
    text = text_of(plain)
    assert plain.exit_code == 1, f"exit {plain.exit_code}\n{tail(plain)}"
    assert f"orgs/{OFFLINE_ORG}/{OFFLINE_ORG}.jsonnet{MISSING_CONFIG}" in text, tail(plain)


@pytest.mark.scenario("O-CONFIG-NO-BASE-TEMPLATE")
def test_default_base_template_is_required(vendored_cli: OtterdogCli) -> None:
    """Without defaults.jsonnet.base_template, an organization with its own base_template still fails to load: every
    command exits 2 with 'need to define a base template ...'."""
    workspace = vendored_cli.workspace
    document = workspace.otterdog_json()
    del document["defaults"]["jsonnet"]["base_template"]
    document["organizations"][0]["base_template"] = workspace.template.url
    workspace.use_layout(WorkspaceLayout(document=document))
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    config_error(vendored_cli.validate(local=True), NEED_BASE_TEMPLATE)
    config_error(vendored_cli.list_projects(), NEED_BASE_TEMPLATE)


@pytest.mark.scenario("O-TEMPLATE-URL")
@pytest.mark.parametrize(
    ("url", "message"),
    [
        pytest.param(
            "https://gitlab.com/e2e-offline/template#otterdog-defaults.libsonnet@main",
            "only github.com is supported for template urls: gitlab.com",
            id="not-github",
        ),
        pytest.param(
            "https://github.com/e2e-offline/template#otterdog-defaults.libsonnet",
            "failed to parse ref from template url: https://github.com/e2e-offline/template#otterdog-defaults.libsonnet",
            id="no-ref",
        ),
        pytest.param(
            "https://github.com/e2e-offline/template",
            "failed to parse file from template url: https://github.com/e2e-offline/template",
            id="no-file",
        ),
    ],
)
def test_invalid_template_url(vendored_cli: OtterdogCli, url: str, message: str) -> None:
    """A base template URL (here from the defaults override) that is not on github.com or lacks its #<file>@<ref>
    fragment stops the loading: exit 2 for list-projects and validate."""
    workspace = vendored_cli.workspace
    workspace.use_layout(WorkspaceLayout(defaults_override={"jsonnet": {"base_template": url}}))
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    config_error(vendored_cli.list_projects(), message)
    config_error(vendored_cli.validate(local=True), message)


# --- organization entries -------------------------------------------------------------------------------------------
@pytest.mark.scenario("O-CONFIG-ORG-ENTRIES")
@pytest.mark.parametrize(
    ("entry", "message"),
    [
        pytest.param(
            {"github_id": OTHER, "name": None},
            "missing required name for organization config with data: '{",
            id="no-name",
        ),
        pytest.param(
            {"name": OTHER},
            f"missing required github_id for organization config with name '{OTHER}'",
            id="no-github-id",
        ),
        pytest.param(
            {"github_id": OTHER, "credentials": None},
            f"missing required credentials for organization config with name '{OTHER}'",
            id="null-credentials",
        ),
        pytest.param(
            {"github_id": OTHER, "approval_teams": 42},
            f"invalid 'approval_teams' for organization config with name '{OTHER}': expected a string or a list of "
            "strings, got <class 'int'>",
            id="approval-teams-int",
        ),
        pytest.param(
            {"github_id": OTHER, "admin_teams": {"team": "otterdog-admins"}},
            f"invalid 'admin_teams' for organization config with name '{OTHER}': expected a string or a list of "
            "strings, got <class 'dict'>",
            id="admin-teams-mapping",
        ),
    ],
)
def test_invalid_organization_entry(offline_cli: OtterdogCli, entry: dict[str, Any], message: str) -> None:
    """One invalid entry among the organizations stops the loading of the whole configuration (exit 2, the valid
    organization is not listed either)."""
    offline_cli.workspace.use_layout(WorkspaceLayout(orgs=(entry,)))
    config_error(offline_cli.list_projects(), message)


@pytest.mark.scenario("O-CONFIG-ORG-ENTRIES")
def test_organization_entry_variants(vendored_cli: OtterdogCli) -> None:
    """approval_teams as a list and admin_teams as a string are accepted (listed with their index); a per-organization
    base_template replaces the default one for that organization only: its vendored template path is
    <org dir>/vendor/<repo of the URL>/<file of the URL>."""
    workspace = vendored_cli.workspace
    entries = (
        {
            "github_id": SECOND,
            "name": SECOND_PROJECT,
            "approval_teams": ["project-leads", ".*-committers$"],
            "admin_teams": "otterdog-admins",
        },
        {"github_id": OTHER, "base_template": "https://github.com/e2e-offline/other-template#sub/other.libsonnet@v1"},
    )
    workspace.use_layout(WorkspaceLayout(orgs=entries))
    listed = vendored_cli.list_projects().assert_ok("list-projects")
    expected = [[OFFLINE_ORG, OFFLINE_ORG, "1"], [SECOND_PROJECT, SECOND, "2"], [OTHER, OTHER, "3"]]
    assert projects_table(listed) == expected, listed.output

    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    own = validate_org(vendored_cli, OFFLINE_ORG)
    assert own.exit_code == 0 and SUCCEEDED in text_of(own), tail(own)
    other = validate_org(vendored_cli, OTHER)
    text = text_of(other)
    assert other.exit_code == 2, f"exit {other.exit_code}\n{tail(other)}"
    assert f"{OTHER}/vendor/other-template/sub/other.libsonnet' does not exist" in text, tail(other)


@pytest.mark.scenario("O-CONFIG-ARCHIVED-ORG")
def test_archived_organizations_are_ignored(vendored_cli: OtterdogCli) -> None:
    """Organizations with archived: true are never listed, never processed and unknown when named (exit 2); an
    archived entry is not even checked (one without github_id loads)."""
    workspace = vendored_cli.workspace
    workspace.use_layout(
        WorkspaceLayout(
            orgs=({"github_id": ARCHIVED, "archived": True}, {"name": f"{ARCHIVED}-broken", "archived": True})
        )
    )
    listed = vendored_cli.list_projects().assert_ok("list-projects")
    assert projects_table(listed) == [[OFFLINE_ORG, OFFLINE_ORG, "1"]], listed.output

    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    every = validate_org(vendored_cli)
    assert every.exit_code == 0 and headers(every) == [header(OFFLINE_ORG, OFFLINE_ORG, 1, 1)], tail(every)
    config_error(validate_org(vendored_cli, ARCHIVED), f"unknown organization with name / github_id '{ARCHIVED}'")


# --- organization selection -----------------------------------------------------------------------------------------
@pytest.mark.scenario("O-ORG-SELECTION")
def test_organizations_positional(vendored_cli: OtterdogCli, template_src: Any) -> None:
    """Two organizations, the first with one validation error, the second valid: without positional both are processed
    in configuration order and the exit status is the largest (1, not the last organization's 0); a github_id or a
    project name in another case selects that organization only; several positionals keep their order; an unknown
    name exits 2 before any organization is processed."""
    workspace = vendored_cli.workspace
    workspace.use_layout(WorkspaceLayout(orgs=({"github_id": SECOND, "name": SECOND_PROJECT},)))
    vendor_template(template_src, workspace.org_dir_for(SECOND), workspace.template)
    workspace.write_org_config(render_org(workspace, ONE_ERROR))
    second = render_org(workspace, ConfigFragments(), org=SECOND, project=SECOND_PROJECT)
    workspace.write_org_config(second, org=SECOND)

    every = validate_org(vendored_cli)
    first_header, second_header = header(OFFLINE_ORG, OFFLINE_ORG, 1, 2), header(SECOND_PROJECT, SECOND, 2, 2)
    assert headers(every) == [first_header, second_header], tail(every)
    assert every.exit_code == 1, f"the largest exit status of the organizations is 1, got {every.exit_code}"
    assert text_of(every).count(DESCRIPTION_ERROR) == 1 and SUCCEEDED in text_of(every), tail(every)

    by_id = validate_org(vendored_cli, SECOND.upper())
    assert by_id.exit_code == 0 and headers(by_id) == [header(SECOND_PROJECT, SECOND, 1, 1)], tail(by_id)
    by_project = validate_org(vendored_cli, "E2E-Offline-Two")
    assert by_project.exit_code == 0 and headers(by_project) == [header(SECOND_PROJECT, SECOND, 1, 1)], tail(by_project)
    ordered = validate_org(vendored_cli, SECOND, OFFLINE_ORG)
    expected = [header(SECOND_PROJECT, SECOND, 1, 2), header(OFFLINE_ORG, OFFLINE_ORG, 2, 2)]
    assert headers(ordered) == expected and ordered.exit_code == 1, tail(ordered)
    config_error(validate_org(vendored_cli, "nope"), "unknown organization with name / github_id 'nope'")


# --- local mode and missing files -----------------------------------------------------------------------------------
@pytest.mark.scenario("O-LOCAL-MISSING-TEMPLATE")
def test_local_mode_needs_the_vendored_template(offline_cli: OtterdogCli, template_src: Any) -> None:
    """--local never clones the base template: without <org dir>/vendor/<repo>/<file>, validate and show exit 2 with
    "template file '...' does not exist" (before any project header) and local-plan reports 'planning aborted' (exit
    1); once the template is vendored the same configuration validates."""
    workspace = offline_cli.workspace
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    workspace.write_base_config(render_org(workspace, ConfigFragments()))
    template_file = f"{OFFLINE_ORG}/vendor/{workspace.template.repo_name}/{workspace.template.file}' does not exist"
    for result in (offline_cli.validate(local=True), offline_cli.show(local=True)):
        text = text_of(result)
        assert result.exit_code == 2, f"exit {result.exit_code}\n{tail(result)}"
        assert "Error: template file '" in text and template_file in text, tail(result)
        assert not headers(result), f"the template is loaded before the project header\n{tail(result)}"
    planned = offline_cli.local_plan()
    text = text_of(planned)
    assert planned.exit_code == 1 and "Error: planning aborted: template file '" in text, tail(planned)
    assert template_file in text and planned.plan().add is None, tail(planned)

    vendor_template(template_src, workspace.org_dir, workspace.template)
    vendored = offline_cli.validate(local=True)
    assert vendored.exit_code == 0 and SUCCEEDED in text_of(vendored), tail(vendored)


@pytest.mark.scenario("O-MISSING-ORG-CONFIG")
def test_missing_organization_configuration(vendored_cli: OtterdogCli) -> None:
    """otterdog.json and the vendored template but no orgs/<org>/<org>.jsonnet: validate and show exit 1 with
    "configuration file '...' does not exist, run 'fetch-config' or 'import' first.", local-plan with "... does not
    yet exist, run fetch-config or import first."."""
    config_file = f"orgs/{OFFLINE_ORG}/{OFFLINE_ORG}.jsonnet"
    assert not vendored_cli.workspace.org_config_file.exists()
    for result, message in (
        (vendored_cli.validate(local=True), MISSING_CONFIG),
        (vendored_cli.show(local=True), MISSING_CONFIG),
        (vendored_cli.local_plan(), MISSING_CONFIG_PLAN),
    ):
        text = text_of(result)
        assert result.exit_code == 1, f"{result.argv[1]} exited {result.exit_code}\n{tail(result)}"
        assert "Error: configuration file '" in text and f"{config_file}{message}" in text, tail(result)
        assert headers(result) == [header(OFFLINE_ORG, OFFLINE_ORG, 1, 1)], tail(result)
