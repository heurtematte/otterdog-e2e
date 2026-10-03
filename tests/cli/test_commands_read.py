"""Read-only otterdog commands against the live test org, checked against the independent REST oracle.

cli.show-live: ``show-live -n`` prints the live configuration: the org settings (REST values, no web-only key with
    ``-n``), every repository and team the oracle lists, the incomplete-config warning (otterdog/operations/show_live.py).
cli.list-members: ``list-members`` counts the org members, ``--two-factor-disabled`` the members without 2FA and
    reports the 2FA requirement of the LOCAL configuration (two_factor_requirement), not the live one
    (otterdog/operations/list_members.py).
cli.list-apps: ``list-apps --json`` prints ``[{app_id, app_slug, permissions}]`` sorted by slug, exactly the org's App
    installations (GET /orgs/{org}/installations); without ``--json`` one ``app['<slug>']`` block per installation.
cli.list-advisories: ``list-advisories`` prints the CSV header first, then one row per repository advisory of the
    requested states; a draft advisory of a run repository (created by the mutator, closed and removed with the
    repository afterwards) is the row checked field by field; ``-d`` prints ``advisory['<ghsa>']`` blocks instead.
cli.kb.list-advisories-markup (known bug KB-050): the CSV rows go through rich markup unescaped, so the bracketed
    words of a summary ('[e2e]') disappear from the CSV (and a '[/]' crashes the command).
cli.token-scopes: ``check-token-permissions -l`` prints the classic token's granted scopes; the config_reader
    identity (a fine-grained token: no X-OAuth-Scopes header) is reported with every missing scope and exit 1.

Commands that need the local configuration read the baseline (written into the workspace, never applied); nothing
here changes the org except the advisory tests, which only create run objects.
"""

from __future__ import annotations

import csv
import json
import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.capabilities import Cap
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.webui.mapping import WEB_SETTINGS

if TYPE_CHECKING:
    from conftest import LiveConfig, ShownObject
    from otterdog_e2e.capabilities import Capabilities
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli")]

# otterdog/operations/show_live.py and import_configuration.py (print_warn: a boxed "Warning:" after normalization)
NO_WEB_UI_WARNING = (
    "Warning: the Web UI will not be queried as '--no-web-ui' has been specified, the resulting config will be "
    "incomplete."
)
SHOW_LIVE_HEADER = "Showing live resources:"
# REST-backed org settings (otterdog/resources/schemas/settings.json "provider": "restapi") that otterdog reads from
# GET /orgs/{org} under the same name (plan comes from plan.name)
REST_SETTINGS = (
    "name",
    "billing_email",
    "company",
    "email",
    "twitter_username",
    "location",
    "description",
    "blog",
    "has_organization_projects",
    "default_repository_permission",
    "members_can_create_private_repositories",
    "members_can_create_public_repositories",
    "members_can_fork_private_repositories",
    "web_commit_signoff_required",
    "members_can_create_public_pages",
)
# temporary private forks of security advisories, never loaded by otterdog (utils.is_ghsa_repo)
GHSA_FORK_RE = re.compile(r".*-ghsa(-[23456789cfghjmpqrvwx]{4}){3}")
FOUND_MEMBERS_RE = re.compile(r"^\s*Found (?P<count>\d+) members\.\s*$", re.MULTILINE)
FOUND_2FA_RE = re.compile(
    r"^\s*Found (?P<disabled>\d+) / (?P<total>\d+) members with 2FA disabled\. "
    r"Organization has 2FA '(?P<status>enabled|disabled)'\s*$",
    re.MULTILINE,
)
# otterdog/operations/list_advisories.py CSV_FIELDS (unchanged since v1.4.0)
ADVISORY_FIELDS = (
    "organization",
    "created_at",
    "days_since_created",
    "updated_at",
    "days_since_updated",
    "published_at",
    "last_commented_at",
    "days_since_last_commented",
    "state",
    "severity",
    "ghsa_id",
    "cve_id",
    "html_url",
    "summary",
)
CSV_HEADER = ",".join(ADVISORY_FIELDS)
ALL_STATES = ("triage", "draft", "published", "closed")  # what "-s all" expands to
DEFAULT_STATES = ("triage", "draft")  # the default of -s
# (arguments, states listed)
ADVISORY_LISTINGS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    ((), DEFAULT_STATES),
    (("-s", "all"), ALL_STATES),
    (("-s", "published"), ("published",)),
)
ADVISORY_TIMEOUT = 120.0  # the org listing of repository advisories can lag a creation
CSV_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")  # utils.format_date_for_csv
EXPECTED_SCOPES = frozenset({"admin:org", "admin:org_hook", "delete_repo", "repo", "workflow"})
GRANTED_RE = re.compile(r"^\s*Granted scopes: (?P<scopes>.*?)\s*$", re.MULTILINE)
MISSING_RE = re.compile(r"^\s*Missing scopes: (?P<scopes>.*?)\s*$", re.MULTILINE)


def scope_set(text: str) -> set[str]:
    """Scopes of a ``, `` separated list."""
    return {scope.strip() for scope in text.split(",") if scope.strip()}


def baseline_cli(
    baseline: BaselineManager,
    workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    *,
    settings: tuple[str, ...] = (),
) -> OtterdogCli:
    """A CLI whose workspace holds the baseline plus ``settings`` fields (a local configuration, never applied)."""
    workspace.write_org_config(baseline.renderer.render(ConfigFragments(settings=list(settings))))
    return make_cli(workspace)


# --- show-live ---------------------------------------------------------------------------------------------------------
@pytest.mark.scenario("cli.show-live", priority="P2")
@pytest.mark.tags("repo", "teams", "org-settings")
def test_show_live_prints_the_live_org(
    baseline: BaselineManager,
    oracle: Oracle,
    target: Target,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
    shown_objects: Callable[[str], list[ShownObject]],
    shown: Callable[[str | None], Any],
) -> None:
    """``show-live -n``: the settings block holds the REST values and no web-only key, and every repository and team
    the oracle lists (the baseline ones included) has its block."""
    result = make_cli(fresh_workspace).run("show-live", "-n").assert_ok("show-live -n")
    text = cli_lines(result)
    assert text.lstrip().startswith(SHOW_LIVE_HEADER), text[:500]
    assert NO_WEB_UI_WARNING in text, f"no --no-web-ui warning:\n{text[:2000]}"
    objects = shown_objects(text)
    settings = [obj for obj in objects if obj.kind == "settings"]
    assert len(settings) == 1, f"{len(settings)} settings block(s) in:\n{text[:2000]}"
    fields = settings[0].fields
    web_keys = sorted(setting.key for setting in WEB_SETTINGS if setting.key in fields)
    assert not web_keys, f"show-live -n printed the web-only settings {web_keys}"
    org = oracle.org() or {}
    compared = [key for key in REST_SETTINGS if key in org]
    assert "description" in compared, f"GET /orgs/{target.org} returned no description"
    differing = {key: (shown(fields.get(key)), org[key]) for key in compared if shown(fields.get(key)) != org[key]}
    assert not differing, f"show-live -n settings differ from GET /orgs/{target.org} (shown, REST): {differing}"
    plan = (org.get("plan") or {}).get("name")
    if plan:
        assert shown(fields.get("plan")) == plan, (fields.get("plan"), plan)
    repos = {obj.value for obj in objects if obj.kind == "repository"}
    live_repos = {str(repo["name"]) for repo in oracle.repos()}
    expected_repos = {name for name in live_repos if not GHSA_FORK_RE.match(name)} | set(baseline.baseline_repos)
    assert expected_repos <= repos, f"repositories missing from show-live: {sorted(expected_repos - repos)}"
    teams = {obj.value for obj in objects if obj.kind == "team"}
    expected_teams = {str(team["name"]) for team in oracle.teams()} | set(baseline.baseline_teams)
    assert expected_teams <= teams, f"teams missing from show-live: {sorted(expected_teams - teams)}"


# --- list-members ------------------------------------------------------------------------------------------------------
@pytest.mark.scenario("cli.list-members", priority="P2")
@pytest.mark.tags("org-settings")
def test_list_members_counts_the_members(
    e2e: E2EContext,
    baseline: BaselineManager,
    oracle: Oracle,
    template_ref: TemplateRef,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``list-members``: 'Found <n> members.' with n = GET /orgs/{org}/members; ``--two-factor-disabled``: the number
    of members without 2FA out of n, and the 2FA requirement of the LOCAL configuration: the same live org is reported
    'enabled' with two_factor_requirement true and 'disabled' with false."""
    members = oracle.members()
    disabled = oracle.members_2fa_disabled()
    cli = baseline_cli(baseline, e2e.workspace(e2e.unique_name("members"), template_ref), make_cli)
    listed = cli.run("list-members").assert_ok("list-members")
    found = FOUND_MEMBERS_RE.search(cli_lines(listed))
    assert found, f"no 'Found <n> members.' line:\n{listed.output[-2000:]}"
    assert int(found.group("count")) == len(members), (found.group(0), sorted(members))
    for requirement, status in ((True, "enabled"), (False, "disabled")):
        workspace = e2e.workspace(e2e.unique_name(f"members-2fa-{status}"), template_ref)
        field = f"two_factor_requirement::: {str(requirement).lower()}"  # ':::': visible even if layer 1 hides it
        two_factor = baseline_cli(baseline, workspace, make_cli, settings=(field,)).run(
            "list-members", "--two-factor-disabled"
        )
        two_factor.assert_ok("list-members --two-factor-disabled")
        line = FOUND_2FA_RE.search(cli_lines(two_factor))
        assert line, f"no 2FA summary line:\n{two_factor.output[-2000:]}"
        assert (int(line.group("disabled")), int(line.group("total"))) == (len(disabled), len(members)), line.group(0)
        assert line.group("status") == status, f"two_factor_requirement {requirement}: {line.group(0)!r}"


# --- list-apps ---------------------------------------------------------------------------------------------------------
def installations(e2e: E2EContext, org: str) -> list[dict[str, Any]]:
    """GET /orgs/{org}/installations with the admin token (read-only client)."""
    return list(e2e.http("admin").paginate(f"/orgs/{org}/installations", item_key="installations", per_page=100))


@pytest.mark.scenario("cli.list-apps", priority="P2")
def test_list_apps_matches_the_installations(
    e2e: E2EContext,
    target: Target,
    capabilities: Capabilities,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
    shown_objects: Callable[[str], list[ShownObject]],
    shown: Callable[[str | None], Any],
) -> None:
    """``list-apps --json``: the JSON array equals the installations (app_id, app_slug, permissions) sorted by slug,
    the e2e App included when it is ready; without ``--json``: one ``app['<slug>']`` block per installation."""
    cli = make_cli(fresh_workspace)
    listed = cli.run("list-apps", "--json").assert_ok("list-apps --json")
    try:
        apps = json.loads(listed.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"list-apps --json did not print JSON ({exc}):\n{listed.stdout[-2000:]}") from exc
    assert isinstance(apps, list), apps
    expected = sorted(
        (
            {"app_id": item["app_id"], "app_slug": item["app_slug"], "permissions": item["permissions"]}
            for item in installations(e2e, target.org)
        ),
        key=lambda app: str(app["app_slug"]),
    )
    assert apps == expected, f"list-apps --json differs from GET /orgs/{target.org}/installations"
    slugs = [str(app["app_slug"]) for app in apps]
    variables = e2e.scenario_variables()
    if capabilities.has(Cap.APP) and variables["app_slug"]:
        listed_app = next((app for app in apps if app["app_slug"] == variables["app_slug"]), None)
        assert listed_app is not None, f"the e2e App {variables['app_slug']} is not listed: {slugs}"
        assert str(listed_app["app_id"]) == variables["app_id"], listed_app
    text = cli_lines(cli.run("list-apps").assert_ok("list-apps"))
    assert "Listing app installations:" in text, text[:500]
    blocks = {obj.label or "": obj for obj in shown_objects(text) if obj.kind == "app"}
    assert set(blocks) == set(slugs), (sorted(blocks), slugs)
    for app in apps:
        assert shown(blocks[str(app["app_slug"])].fields.get("app_id")) == app["app_id"], app["app_slug"]


# --- list-advisories ---------------------------------------------------------------------------------------------------
def csv_rows(stdout: str) -> tuple[str, list[dict[str, str]]]:
    """(first non-empty line, rows after it as field -> value) of a list-advisories output; AssertionError for a row
    without the 14 fields."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    assert lines, "list-advisories printed nothing"
    rows = list(csv.reader(lines[1:]))
    incomplete = [row for row in rows if len(row) != len(ADVISORY_FIELDS)]
    assert not incomplete, f"CSV rows without the {len(ADVISORY_FIELDS)} fields: {incomplete[:3]}"
    return lines[0], [dict(zip(ADVISORY_FIELDS, row, strict=True)) for row in rows]


def advisory_ids(oracle: Oracle, states: tuple[str, ...]) -> set[str]:
    """GHSA ids of the org's repository advisories in ``states`` (GET /orgs/{org}/security-advisories)."""
    return {str(item["ghsa_id"]) for item in oracle.org_security_advisories() if item.get("state") in states}


def draft_advisory(
    live_config: LiveConfig, mutator: Mutator, oracle: Oracle, slug: str, summary: str
) -> tuple[str, str]:
    """(repository, GHSA id) of a draft advisory with ``summary`` in a new run repository, once the org listing
    shows it."""
    repo = live_config.name(slug)
    live_config.apply(
        live_config.render(f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: list-advisories' }}"),
        what=f"apply {repo}",
    )
    assert live_config.wait_repo(repo) is not None, f"{repo} was not created"
    ghsa = str(mutator.create_security_advisory(repo, summary=summary, severity="low")["ghsa_id"])
    listed = waiting.poll(
        lambda: advisory_ids(oracle, ALL_STATES),
        until=lambda ids: ghsa in ids,
        timeout=ADVISORY_TIMEOUT,
        interval=5.0,
        what=f"advisory {ghsa} in the org listing",
        raise_on_timeout=False,
    )
    assert ghsa in listed, f"{ghsa} never appeared in the org's repository advisories"
    return repo, ghsa


@pytest.mark.scenario("cli.list-advisories", priority="P2")
@pytest.mark.tags("repo")
@pytest.mark.timeout(1200)
def test_list_advisories_prints_the_csv(
    live_config: LiveConfig,
    mutator: Mutator,
    oracle: Oracle,
    target: Target,
    cli_lines: Callable[[CliResult], str],
    shown_objects: Callable[[str], list[ShownObject]],
    shown: Callable[[str | None], Any],
) -> None:
    """A draft advisory of a run repository is a complete CSV row of ``list-advisories`` (default states triage and
    draft) and of ``-s all``, absent from ``-s published``; ``-d`` prints its block without the CSV header; every
    listing has exactly the advisories GitHub reports for its states."""
    summary = f"{live_config.name('advisory')} list-advisories"
    repo, ghsa = draft_advisory(live_config, mutator, oracle, "advisories", summary)
    try:
        for args, states in ADVISORY_LISTINGS:
            result = live_config.cli.run("list-advisories", *args).assert_ok(f"list-advisories {' '.join(args)}")
            first, rows = csv_rows(result.stdout)
            assert first == CSV_HEADER, f"the first line is not the CSV header: {first!r}"
            by_id = {row["ghsa_id"]: row for row in rows}
            assert set(by_id) == advisory_ids(oracle, states), (args, sorted(by_id))
            if "draft" not in states:
                assert ghsa not in by_id, f"the draft {ghsa} is listed for the states {states}"
                continue
            row = by_id[ghsa]
            assert (row["organization"], row["state"], row["severity"], row["cve_id"]) == (
                target.org,
                "draft",
                "low",
                "NO_CVE",
            ), row
            assert row["summary"] == summary, row
            assert row["html_url"].endswith(f"/{repo}/security/advisories/{ghsa}"), row
            assert CSV_DATE_RE.match(row["created_at"]) and CSV_DATE_RE.match(row["updated_at"]), row
            assert row["days_since_created"].isdigit() and row["published_at"] == "", row
            assert (row["last_commented_at"], row["days_since_last_commented"]) == ("", ""), "no -w: no comment date"
        details = cli_lines(live_config.cli.run("list-advisories", "-d").assert_ok("list-advisories -d"))
        assert CSV_HEADER not in details, "list-advisories -d printed the CSV header"
        blocks = {obj.label or "": obj for obj in shown_objects(details) if obj.kind == "advisory"}
        assert ghsa in blocks, f"no advisory['{ghsa}'] block:\n{details[-2000:]}"
        assert shown(blocks[ghsa].fields.get("summary")) == summary, blocks[ghsa].fields
        assert shown(blocks[ghsa].fields.get("state")) == "draft", blocks[ghsa].fields
    finally:
        mutator.close_security_advisory(repo, ghsa)


@pytest.mark.scenario("cli.kb.list-advisories-markup", priority="P2")
@pytest.mark.known_bug("KB-050")
@pytest.mark.tags("repo", "known-bug")
@pytest.mark.timeout(1200)
def test_list_advisories_keeps_brackets_of_summaries(live_config: LiveConfig, mutator: Mutator, oracle: Oracle) -> None:
    """The CSV holds an advisory summary verbatim, brackets included (KB-050: the rows are printed through rich
    markup, so '[e2e]' and '[x]' vanish from the summary column)."""
    summary = f"{live_config.name('advisory-markup')} [e2e] title [x]"
    repo, ghsa = draft_advisory(live_config, mutator, oracle, "advisory-markup", summary)
    try:
        result = live_config.cli.run("list-advisories").assert_ok("list-advisories")
        first, rows = csv_rows(result.stdout)
        assert first == CSV_HEADER, first
        row = next((row for row in rows if row["ghsa_id"] == ghsa), None)
        assert row is not None, f"{ghsa} is not listed:\n{result.stdout[-2000:]}"
        assert row["summary"] == summary, f"summary {row['summary']!r} instead of {summary!r}"
    finally:
        mutator.close_security_advisory(repo, ghsa)


# --- check-token-permissions -------------------------------------------------------------------------------------------
@pytest.mark.scenario("cli.token-scopes", priority="P1")
def test_check_token_permissions_lists_the_granted_scopes(
    e2e: E2EContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``check-token-permissions -l`` with the admin token: 'Granted scopes:' lists exactly the X-OAuth-Scopes of the
    token (a superset of the five otterdog needs), no 'Missing scopes', exit 0."""
    granted = e2e.http("admin").oauth_scopes()
    if granted is None:
        pytest.skip("the admin token is not a classic token (no X-OAuth-Scopes): otterdog needs a classic PAT")
    result = make_cli(fresh_workspace).run("check-token-permissions", "-l")
    text = cli_lines(result)
    assert result.exit_code == 0, f"exit {result.exit_code}:\n{text[-2000:]}"
    line = GRANTED_RE.search(text)
    assert line, f"no 'Granted scopes:' line:\n{text[-2000:]}"
    assert scope_set(line.group("scopes")) == granted, (line.group("scopes"), sorted(granted))
    assert granted >= EXPECTED_SCOPES, f"the admin token lacks {sorted(EXPECTED_SCOPES - granted)}"
    assert MISSING_RE.search(text) is None, text[-2000:]


@pytest.mark.scenario("cli.token-scopes", priority="P1")
@pytest.mark.identities("config_reader")
def test_check_token_permissions_reports_missing_scopes(
    e2e: E2EContext,
    sut: InstalledCli,
    fresh_workspace: ConfigWorkspace,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``check-token-permissions`` with the config_reader identity (a fine-grained token: no X-OAuth-Scopes): 'Missing
    scopes:' names exactly the scopes otterdog needs that the token lacks (all five for a fine-grained token), exit 1."""
    granted = e2e.http("config_reader").oauth_scopes() or set()
    missing = EXPECTED_SCOPES - granted
    if not missing:
        pytest.skip("the config_reader token holds every scope otterdog needs: nothing can be reported missing")
    cli = e2e.cli(sut, fresh_workspace, name=f"ws-{fresh_workspace.root.name}-reader", identity="config_reader")
    result = cli.run("check-token-permissions")
    text = cli_lines(result)
    line = MISSING_RE.search(text)
    assert line, f"no 'Missing scopes:' line:\n{text[-2000:]}"
    assert scope_set(line.group("scopes")) == missing, (line.group("scopes"), sorted(missing))
    assert result.exit_code == 1, f"exit {result.exit_code} although scopes are missing"
