"""Offline CLI basics (SPEC 19): O-VERSION, list-projects, show-default, the help and usage errors (O-HELP) and the
markdown modes of show and show-default (O-SHOW-MARKDOWN, O-SHOW-DEFAULT-MARKDOWN) and the credential-free show
(O-SHOW), directly against the SUT CLI.

These commands need no organization configuration (list-projects only reads otterdog.json, show-default only
evaluates the vendored template, --help and usage errors stop in click) and give the first signal that the SUT under
test is installed and runnable. The module comes first in the tier (pytest orders modules by name), so its first test
also pays the SUT installation (cold cache: resolve + install, or the image build of an untrusted SUT): it carries a
larger timeout.

Verified on v1.6.1 and main 9bdeb75 (otterdog/cli.py is identical in both): the group lists 29 subcommands, ``-h`` is
an alias of ``--help``, ``otterdog`` alone prints the usage on stderr and exits 2 (click's ``no_args_is_help`` of a
group), unknown options and commands are click usage errors (exit 2, ``Try '... --help' for help.``). ``show
--markdown --output-dir DIR`` writes ``DIR/configuration.md`` and one ``DIR/repo-<name>.md`` per repository (mkdocs
pages with ``=== "<tab>"`` blocks) instead of printing the configuration; ``show-default --markdown`` prints one tab per
object type with a jsonnet code fence and no ``Showing defaults configurations:`` header. Both markdown writers go
through rich markup (otterdog/utils.py IndentingPrinter.print): the ``[<name>]`` text of the repository links is
swallowed as a style tag (KB-050, test_show_markdown_keeps_the_repository_links). ``show`` never resolves
credentials (otterdog/operations/show.py), unlike validate.
"""

from __future__ import annotations

import re
import warnings
from pathlib import Path

import pytest

from otterdog_e2e.otterdog.output import normalize_text, strip_ansi
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace, WorkspaceLayout
from otterdog_e2e.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_ORG,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)
from otterdog_e2e.sut.cli_install import InstalledCli, installed_version

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

RUN = offline_run_context()  # deterministic names: e2e-spduo000-<slug>, E2E_SPDUO000_<SLUG>
# the 29 subcommands of otterdog/cli.py:179-969 (EXPECTED_INVENTORY["command"] of tests/unit/test_coverage_matrix.py)
COMMANDS = (
    "apply",
    "approve-blueprints",
    "canonical-diff",
    "check-status",
    "check-token-permissions",
    "delete-file",
    "dispatch-workflow",
    "fetch-config",
    "import",
    "install-app",
    "install-deps",
    "list-advisories",
    "list-apps",
    "list-blueprints",
    "list-members",
    "list-projects",
    "local-apply",
    "local-plan",
    "open-pr",
    "plan",
    "push-config",
    "review-permissions",
    "show",
    "show-default",
    "show-live",
    "sync-template",
    "uninstall-app",
    "validate",
    "web-login",
)
# options every organization command shares (otterdog/cli.py StdCommand)
STD_OPTIONS = ("--local", "-c, --config FILE", "-v, --verbose", "-h, --help")
GROUP_USAGE = "[OPTIONS] COMMAND [ARGS]..."
COMMAND_LINE_RE = re.compile(r"^  (?P<name>[a-z][a-z-]*)\s{2,}(?P<help>\S.*)$")
# tabs of the markdown pages (otterdog/operations/show.py _print_markdown and _print_repo_markdown)
CONFIGURATION_TABS = (
    '=== "Organization Settings"',
    '=== "Organization Webhooks"',
    '=== "Organization Secrets"',
    '=== "Organization Variables"',
    '=== "Repositories"',
)
REPOSITORY_TABS = (
    '=== "Settings"',
    '=== "Webhooks"',
    '=== "Secrets"',
    '=== "Variables"',
    '=== "Branch Protection Rules"',
    '=== "Rulesets"',
)
FRONT_MATTER = "---\nhide:\n  - navigation\n---\n"
JSONNET_FENCE = "``` jsonnet"

# show-default prints one block per object type (headers verified on v1.6.1 and main 9bdeb75)
DEFAULT_OBJECTS = (
    "orgs.newOrg('<project-name>', '<github-id>') =",
    "orgs.newOrgRole('<name>') =",
    "orgs.newOrgWebhook('<url>') =",
    "orgs.newOrgSecret('<name>') =",
    "orgs.newOrgVariable('<name>') =",
    "orgs.newRepo('<repo-name>') =",
    "orgs.newRepoWebhook('<url>') =",
    "orgs.newRepoSecret('<name>') =",
    "orgs.newRepoVariable('<name>') =",
    "orgs.newBranchProtectionRule('<pattern>') =",
    "orgs.newRepoRuleset('<name>') =",
    "orgs.newEnvironment('<name>') =",
)


def table_rows(output: str) -> list[list[str]]:
    """Cells of the rows of a rich table (box-drawing borders removed, header and rules included)."""
    rows = []
    for line in strip_ansi(output).splitlines():
        if "│" not in line:
            continue
        cells = [cell.strip() for cell in line.strip().strip("│").split("│")]
        rows.append(cells)
    return rows


def listed_commands(help_text: str) -> dict[str, str]:
    """Subcommands of a group help page (name -> one-line help), read from its ``Commands:`` section."""
    lines = strip_ansi(help_text).splitlines()
    try:
        start = lines.index("Commands:") + 1
    except ValueError:
        return {}
    commands = {}
    for line in lines[start:]:
        match = COMMAND_LINE_RE.match(line.rstrip())
        if match is None:
            break
        commands[match.group("name")] = match.group("help")
    return commands


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


def render_org(workspace: ConfigWorkspace, fragments: ConfigFragments) -> str:
    """The configuration of the offline organization with ``fragments``, rendered exactly as OfflineEngine renders
    it (minimal organization, the SUT template's defaults, free plan)."""
    renderer = OfflineConfigRenderer(
        template=workspace.template,
        org=workspace.org,
        plan=OFFLINE_DEFAULT_PLAN,
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
        project=workspace.project,
    )
    return renderer.render(fragments)


def markdown_fixture(workspace: ConfigWorkspace) -> dict[str, str]:
    """Write a configuration with one object per markdown tab and return the names it uses."""
    names = {
        "repo": RUN.name("shown"),
        "hook": RUN.hook_url("org"),
        "org_secret": RUN.const("TOKEN"),
        "org_variable": RUN.const("LEVEL"),
        "repo_variable": RUN.const("MODE"),
    }
    repository = (
        f"orgs.newRepo('{names['repo']}') {{ description: 'e2e shown', "
        f"variables: [orgs.newRepoVariable('{names['repo_variable']}') {{ value: 'on' }}], "
        "branch_protection_rules: [orgs.newBranchProtectionRule('main') { required_approving_review_count: 2 }] }"
    )
    fragments = ConfigFragments(
        webhooks=[f"orgs.newOrgWebhook('{names['hook']}') {{ events+: ['repository'] }}"],
        secrets=[f"orgs.newOrgSecret('{names['org_secret']}') {{ value: '********' }}"],
        variables=[f"orgs.newOrgVariable('{names['org_variable']}') {{ value: 'high' }}"],
        repositories=[repository],
    )
    workspace.write_org_config(render_org(workspace, fragments))
    return names


def run_show_markdown(cli: OtterdogCli) -> tuple[CliResult, Path]:
    """``show --local --markdown --output-dir <workspace>/md`` (the directory does not exist yet); the result and the
    output directory."""
    output_dir = cli.workspace.root.resolve() / "md"
    result = cli.run("show", "--markdown", "--output-dir", str(output_dir), local=True)
    return result, output_dir


def section(text: str, start: str, end: str | None) -> str:
    """The part of ``text`` from the line ``start`` up to (excluded) the line ``end`` (None: the end)."""
    lines = text.splitlines()
    first = lines.index(start)
    last = lines.index(end, first) if end is not None else len(lines)
    return "\n".join(lines[first:last])


@pytest.mark.scenario("O-VERSION")
@pytest.mark.timeout(1800)  # first test of the offline tier: may install the SUT (or build its image)
def test_version_is_the_resolved_sut_version(offline_cli: OtterdogCli, sut: InstalledCli) -> None:
    """``otterdog --version`` (argv exactly [otterdog, --version]) prints the version the SUT resolved to: the full
    version for host installs, the hash-free image version for the CLI of an untrusted SUT's image."""
    output = offline_cli.version()
    expected = sut.sut.image_version if sut.runtime == "docker" else sut.sut.version
    assert installed_version(output) == expected, f"{sut.sut.label}: --version printed {output!r}, expected {expected}"
    assert output.startswith("otterdog"), output


@pytest.mark.scenario("O-LIST-PROJECTS")
def test_list_projects_lists_the_offline_organization(offline_cli: OtterdogCli) -> None:
    """``list-projects`` (no organization positional) prints the single project of otterdog.json with its index."""
    result = offline_cli.list_projects().assert_ok("list-projects")
    rows = table_rows(result.output)
    assert ["Project name", "GitHub ID", "Index"] in rows, result.output
    assert [OFFLINE_ORG, OFFLINE_ORG, "1"] in rows, result.output


@pytest.mark.scenario("O-SHOW-DEFAULT")
def test_show_default_prints_every_object_type(vendored_cli: OtterdogCli) -> None:
    """``show-default --local`` evaluates the vendored SUT template and prints the defaults of each object type."""
    result = vendored_cli.show_default(local=True).assert_ok("show-default --local")
    text = normalize_text(result.output)
    assert text.startswith("Showing defaults configurations:"), text[:200]
    missing = [header for header in DEFAULT_OBJECTS if header not in text]
    assert not missing, f"show-default lacks {missing}\n{text[:2000]}"


@pytest.mark.scenario("O-HELP")
def test_help_lists_every_command(offline_cli: OtterdogCli) -> None:
    """``otterdog --help`` (and its alias ``-h``) exits 0 with the group usage, the --version option and every
    subcommand with a one-line help; a command the coverage inventory does not know only warns (a new command)."""
    result = offline_cli.invoke("--help").assert_ok("--help")
    text = strip_ansi(result.stdout)
    assert text.startswith("Usage: ") and GROUP_USAGE in text.splitlines()[0], text[:300]
    assert "Managing GitHub organizations at scale." in text, text[:500]
    assert "--version" in text and "-h, --help" in text, text[:800]
    commands = listed_commands(text)
    missing = [name for name in COMMANDS if name not in commands]
    assert not missing, f"--help does not list {missing}\n{text}"
    assert all(commands[name].strip() for name in COMMANDS), commands
    extra = sorted(set(commands) - set(COMMANDS))
    if extra:
        warnings.warn(f"--help lists commands the coverage inventory lacks: {extra}", stacklevel=1)
    alias = offline_cli.invoke("-h").assert_ok("-h")
    assert listed_commands(alias.stdout) == commands, "-h and --help differ"


@pytest.mark.scenario("O-HELP")
def test_command_help_lists_the_shared_options(offline_cli: OtterdogCli) -> None:
    """``otterdog validate --help`` exits 0 and lists the options every organization command shares (--local, -c,
    -v, -h) and the ORGANIZATIONS positional."""
    result = offline_cli.invoke("validate", "--help").assert_ok("validate --help")
    text = strip_ansi(result.stdout)
    assert "[OPTIONS] [ORGANIZATIONS]..." in text.splitlines()[0], text[:300]
    assert "Validates the configuration for organizations." in text, text
    missing = [option for option in STD_OPTIONS if option not in text]
    assert not missing, f"validate --help lacks {missing}\n{text}"


@pytest.mark.scenario("O-HELP")
@pytest.mark.parametrize(
    ("args", "needles"),
    [
        pytest.param((), ("Usage: ", GROUP_USAGE, "Commands:"), id="no-subcommand"),
        pytest.param(("validate", "--bogus"), ("No such option", "--bogus", "validate --help"), id="unknown-option"),
        pytest.param(("nope",), ("No such command", "'nope'", "--help"), id="unknown-command"),
        pytest.param(("open-pr", "-b", "x", "-t", "y"), ("Missing option", "'-a'"), id="missing-required-option"),
    ],
)
def test_usage_errors_exit_2(offline_cli: OtterdogCli, args: tuple[str, ...], needles: tuple[str, ...]) -> None:
    """``otterdog`` alone, an unknown option, an unknown command and a missing required option are click usage errors:
    exit 2 with the usage message on stderr, before any configuration is loaded (no -c, empty cwd: a loaded
    configuration would have failed with 'No configuration file specified')."""
    result = offline_cli.invoke(*args)
    output = strip_ansi(result.output)
    assert result.exit_code == 2, f"otterdog {' '.join(args)} exited {result.exit_code}\n{output[-1500:]}"
    missing = [needle for needle in needles if needle not in output]
    assert not missing, f"otterdog {' '.join(args)} does not print {missing}\n{output[-1500:]}"
    assert "No configuration file specified" not in output and "Traceback" not in output, output[-1500:]
    if args:
        assert "Usage: " in strip_ansi(result.stderr), f"the usage error is not on stderr\n{result.stderr[-800:]}"


@pytest.mark.scenario("O-SHOW-MARKDOWN")
def test_show_markdown_writes_the_pages(vendored_cli: OtterdogCli) -> None:
    """``show --markdown --output-dir DIR`` creates DIR and writes configuration.md (front matter, the five
    organization tabs with the webhook, secret, variable and repository rows) and repo-<name>.md (the six repository
    tabs with its settings, variable and branch protection rule) instead of printing the configuration."""
    names = markdown_fixture(vendored_cli.workspace)
    result, output_dir = run_show_markdown(vendored_cli)
    result.assert_ok("show --markdown")
    assert "Showing organization resources:" not in result.output, tail(result)
    assert "repository[" not in result.output, f"show --markdown printed the configuration\n{tail(result)}"
    pages = sorted(path.name for path in output_dir.iterdir())
    assert pages == ["configuration.md", f"repo-{names['repo']}.md"], pages

    configuration = (output_dir / "configuration.md").read_text(encoding="utf-8")
    assert configuration.startswith(FRONT_MATTER), configuration[:200]
    assert "# Current configuration" in configuration.splitlines(), configuration[:400]
    tabs = [line for line in configuration.splitlines() if line.startswith("=== ")]
    assert tabs == list(CONFIGURATION_TABS), tabs
    settings = section(configuration, CONFIGURATION_TABS[0], CONFIGURATION_TABS[1])
    assert f"    {JSONNET_FENCE}" in settings and "settings {" in settings, settings[:300]
    assert re.search(r'description\s+: "\[otterdog-e2e\] offline organization",', settings), settings
    webhooks = section(configuration, CONFIGURATION_TABS[1], CONFIGURATION_TABS[2])
    assert "| URL | Uses SSL | Secret | Resolved Secret |" in webhooks and f"| {names['hook']} |" in webhooks, webhooks
    secrets = section(configuration, CONFIGURATION_TABS[2], CONFIGURATION_TABS[3])
    assert "| Name | Resolved Secret |" in secrets and f"| {names['org_secret']} |" in secrets, secrets
    variables = section(configuration, CONFIGURATION_TABS[3], CONFIGURATION_TABS[4])
    assert f"| {names['org_variable']} | high |" in variables, variables
    repositories = section(configuration, CONFIGURATION_TABS[4], None)
    header = "| Repository | Branch Protections | Secrets | Variables | Webhooks | Secret Scanning |"
    assert header in repositories, repositories
    row = next((line for line in repositories.splitlines() if f"(repo-{names['repo']}.md)" in line), None)
    assert row is not None, f"no row links repo-{names['repo']}.md\n{repositories}"
    assert f"(https://github.com/{OFFLINE_ORG}/{names['repo']})" in row, row

    page = (output_dir / f"repo-{names['repo']}.md").read_text(encoding="utf-8")
    assert page.startswith(FRONT_MATTER), page[:200]
    assert [line for line in page.splitlines() if line.startswith("=== ")] == list(REPOSITORY_TABS), page[:400]
    repo_settings = section(page, REPOSITORY_TABS[0], REPOSITORY_TABS[1])
    assert "repository {" in repo_settings and re.search(r'description\s+: "e2e shown",', repo_settings), repo_settings
    assert re.search(rf'name\s+: "{re.escape(names["repo"])}",', repo_settings), repo_settings
    assert "No webhooks." in section(page, REPOSITORY_TABS[1], REPOSITORY_TABS[2])
    assert "No secrets." in section(page, REPOSITORY_TABS[2], REPOSITORY_TABS[3])
    assert f"| {names['repo_variable']} | on |" in section(page, REPOSITORY_TABS[3], REPOSITORY_TABS[4])
    rules = section(page, REPOSITORY_TABS[4], REPOSITORY_TABS[5])
    assert "branch_protection_rule {" in rules and re.search(r'pattern\s+: "main",', rules), rules
    assert re.search(r"required_approving_review_count\s+: 2,", rules), rules
    assert "No rulesets." in section(page, REPOSITORY_TABS[5], None)


@pytest.mark.scenario("O-KB-SHOW-MARKDOWN-LINKS")
@pytest.mark.known_bug("KB-050")
def test_show_markdown_keeps_the_repository_links(vendored_cli: OtterdogCli) -> None:
    """The page title of repo-<name>.md is the markdown link '# Repo [<name>](https://github.com/<org>/<name>)' and
    the Repositories row of configuration.md links the page as '[<name>](repo-<name>.md)'."""
    names = markdown_fixture(vendored_cli.workspace)
    result, output_dir = run_show_markdown(vendored_cli)
    result.assert_ok("show --markdown")
    repo = names["repo"]
    page = (output_dir / f"repo-{repo}.md").read_text(encoding="utf-8")
    title = next((line for line in page.splitlines() if line.startswith("# Repo")), "")
    assert title == f"# Repo [{repo}](https://github.com/{OFFLINE_ORG}/{repo})", f"repo page title: {title!r}"
    configuration = (output_dir / "configuration.md").read_text(encoding="utf-8")
    assert f"| [{repo}](repo-{repo}.md)" in configuration, section(configuration, CONFIGURATION_TABS[4], None)


@pytest.mark.scenario("O-SHOW-DEFAULT-MARKDOWN")
def test_show_default_markdown_prints_one_tab_per_object(vendored_cli: OtterdogCli) -> None:
    """``show-default --markdown`` prints the template defaults as mkdocs tabs: one ``=== "<object>"`` tab per object
    type holding a jsonnet code fence with the ``orgs.new...(...) = {`` block, and no plain-text header."""
    result = vendored_cli.run("show-default", "--markdown", local=True).assert_ok("show-default --markdown")
    text = strip_ansi(result.stdout)
    assert "Showing defaults configurations:" not in text, text[:300]
    assert "Project e2e-offline" not in text, text[:300]
    lines = [line.rstrip() for line in text.splitlines()]
    tabs = [line for line in lines if line.startswith('=== "')]
    fences = [line for line in lines if line.strip() == JSONNET_FENCE]
    closing = [line for line in lines if line.strip() == "```"]
    assert len(tabs) == len(DEFAULT_OBJECTS) == len(fences) == len(closing), (tabs, len(fences), len(closing))
    assert tabs[0] == '=== "Organization Settings"' and '=== "Repository"' in tabs, tabs
    for header in DEFAULT_OBJECTS:
        block = next((line for line in lines if line.strip().startswith(header)), None)
        assert block is not None and block.strip() == f"{header} {{", f"no block {header!r}\n{text[:1500]}"
    # every block sits inside its fence: tab, fence, block header in this order
    for tab_index, tab in enumerate(tabs):
        start = lines.index(tab)
        assert lines[start + 1].strip() == JSONNET_FENCE, (tab, lines[start + 1])
        assert lines[start + 2].strip().startswith("orgs.new"), (tab, lines[start + 2])
        assert tab_index == len(tabs) - 1 or lines.index(tabs[tab_index + 1]) > start + 2


@pytest.mark.scenario("O-SHOW")
def test_show_needs_no_credentials(vendored_cli: OtterdogCli) -> None:
    """show only evaluates the configuration: with an organization entry whose credentials name no provider it still
    prints the configuration (exit 0), while validate refuses the credentials ('no credential provider configured',
    exit 1)."""
    workspace = vendored_cli.workspace
    document = workspace.otterdog_json()
    document["organizations"][0]["credentials"] = {}
    workspace.use_layout(WorkspaceLayout(document=document))
    repo = RUN.name("shown")
    workspace.write_org_config(render_org(workspace, ConfigFragments(repositories=[f"orgs.newRepo('{repo}')"])))
    shown = vendored_cli.show(local=True)
    text = normalize_text(shown.output)
    assert shown.exit_code == 0 and f'repository[name="{repo}"] {{' in text, tail(shown)
    assert "invalid credentials" not in text, tail(shown)
    validated = vendored_cli.validate(local=True)
    text = normalize_text(validated.output)
    assert validated.exit_code == 1 and "Error: invalid credentials" in text, tail(validated)
    assert f"no credential provider configured for organization '{OFFLINE_ORG}'" in text, tail(validated)
