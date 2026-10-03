"""Webapp runtime (coverage area ``webapp-runtime``, live items): team configuration, /internal/init imports, /api/projects
and the pages of a project.

Facts verified in otterdog main 9bdeb75 (identical in v1.6.1):

* teams (utils.py:315-423, config.py:126-127): an otterdog.json organization entry may set ``admin_teams`` and
  ``approval_teams`` (a string or a list, joined with ','); /internal/init stores them in the installation and they
  replace GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS for that org (since otterdog#715, v1.5.0). Admin entries are split
  on ',' WITHOUT stripping (KB-013), approval patterns are stripped and matched with re.search against the team slugs
  of the org. The help comment (templates/comment/help_comment.txt) shows both: "approved by a member of team
  '<slug>'" (or "a team matching pattern '<p>' (no team in this organization currently matches any of these
  patterns)") and the admin team(s) `<org>/<team>, ...` of /otterdog done and apply;
* /internal/init schedules FetchAllPullRequestsTask, which imports the config repo's pull requests targeting 'main'
  (tasks/fetch_all_pull_requests.py:39-62): a PR the webapp missed is listed by /api/pullrequests/open (status open,
  not applied, never validated), a PR against another base is not imported (KB-014: the branch name is hardcoded);
* /api/projects/<project> answers the configuration of /api/organizations/<org> (404 ``{}`` for unknown projects);
  /organizations/<org>[/<subpath>] redirects (302) to /projects/<project>[/<subpath>]; /projects/<project> (+
  /repos/<repo>, /defaults, /playground) render the stored configuration and the template (404 page otherwise);
  /admin/organizations lists the installation (id, status, project) without any login.

W-RT-CONFIG-TEAMS (P1): with GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS pointing at a team that does not exist, the
help comment names the teams of the otterdog.json organization entry; without that entry it names the environment's.
W-RT-ADMIN-TEAMS-SPACES (KB-013): GITHUB_ADMIN_TEAMS 'x, <admin team>' must name '<org>/<admin team>' (non-strict
xfail scoped to AdminTeamsSplitError; the approval patterns of the same form are a strict control).
W-RT-INIT-IMPORTS-PRS: config PRs opened (and one merged) while the webapp is stopped (their deliveries are lost)
are imported by the next /internal/init when they target main (the merged one as applied), and the imported open PR
can be validated with /otterdog validate.
W-RT-INIT-APPLY-STATUS (KB-074): /internal/init must keep the apply status of a partially applied merged PR; the
import sets completed for every merged PR (non-strict xfail scoped to ApplyStatusLostError).
W-RT-API-PROJECTS: /api/projects/<project> equals /api/organizations/<org>; unknown projects and orgs answer 404 {}.
W-RT-PAGES: the project, repository, defaults and playground pages, the /organizations redirects, the 404 pages,
/allprojects and the installation row of /admin/organizations.
"""

from __future__ import annotations

import re
import urllib.parse
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.config_repo import DeliveryTimeoutError, ReactionTimeoutError, comment_contains
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.webapp.api import parse_html

if TYPE_CHECKING:
    from conftest import WebappScenario
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.webapp.stack import ExternalWebapp, WebappStack
    from otterdog_e2e.webhooks.relay import DeliveryRelay, RelayedDelivery

pytestmark = [pytest.mark.webapp]

FIX_715 = "8a316899a606ede828b0ce2c444f72a3152ec478"  # per-organization admin_teams / approval_teams (v1.5.0)
FETCH_ALL_PRS = "FetchAllPullRequestsTask"
NO_MATCH_NOTE = "(no team in this organization currently matches any of these patterns)"  # utils.py:420-423
SECRETS_WARNING = "some of the requested changes require secrets, need to apply these changes manually"
PARTIAL_APPLY = "only partially applied as it requires some access to secrets or the Web UI"
CLOCK_SKEW = timedelta(seconds=60)
DELIVERY_TIMEOUT = 300.0
TASK_TIMEOUT = 240.0
READY_TIMEOUT = 300.0
PAGE_TIMEOUT = 180.0  # /defaults and /playground clone the base template
LONG_TIMEOUT = 2400


class AdminTeamsSplitError(AssertionError):
    """GITHUB_ADMIN_TEAMS 'a, b' yields the team ' b' (KB-013)."""


# --- helpers --------------------------------------------------------------------------------------------------------
def _require_org_teams(s: WebappScenario) -> None:
    """Skip on webapps predating otterdog#715 (v1.5.0): no per-organization admin_teams / approval_teams."""
    if s.webapp_includes(FIX_715) is False:
        pytest.skip("the webapp under test predates otterdog#715 (v1.5.0): no per-organization admin/approval teams")


def _slug(name: str) -> str:
    """GitHub slug of a team name of the target (lower case, runs of other characters as '-')."""
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def _approval_line(team_slug: str) -> str:
    """The help comment's approval condition when the patterns match ``team_slug`` only."""
    return f"approved by a member of team '{team_slug}'"


def _no_approval_line(pattern: str) -> str:
    """The help comment's approval condition when no team of the org matches ``pattern``."""
    return f"approved by a member of a team matching pattern '{pattern}' {NO_MATCH_NOTE}"


def _location(response: Any) -> str:
    """The unquoted Location of a redirect."""
    return urllib.parse.unquote(str(response.headers.get("Location") or ""))


def _wait_task(s: WebappScenario, type_: str, repo: str, *, after: datetime) -> dict[str, Any]:
    """The newest final ``type_`` task of ``repo`` created after ``after`` (ReactionTimeoutError, SUT)."""
    try:
        return s.api.wait_task(type_=type_, org_id=s.org, after=after, repo_name=repo, timeout=TASK_TIMEOUT)
    except waiting.WaitTimeoutError as exc:
        raise ReactionTimeoutError(
            f"webapp did not run {type_} for {repo} within {TASK_TIMEOUT:g} s (SUT): {exc}"
        ) from None


def _wait_lost(relay: DeliveryRelay, wanted: set[tuple[int, str]], *, after: datetime) -> list[RelayedDelivery]:
    """The pull_request deliveries ``wanted`` ((PR number, action) pairs) once the relay tried them while the webapp
    was down: a failed forward is never retried, so the webapp cannot learn of these events through webhooks."""
    floor = after - CLOCK_SKEW
    found: dict[tuple[int, str], RelayedDelivery] = {}

    def matches(delivery: RelayedDelivery) -> bool:
        """A wanted delivery (remembered until all of them are seen)."""
        key = (int(delivery.pull_number or 0), str(delivery.action))
        if delivery.event == "pull_request" and key in wanted and delivery.delivered_at >= floor:
            found[key] = delivery
        return set(found) == wanted

    try:
        relay.wait_for(matches, timeout=DELIVERY_TIMEOUT)
    except waiting.WaitTimeoutError:
        missing = sorted(wanted - set(found))
        raise DeliveryTimeoutError(
            f"pull_request deliveries {missing} not observed within {DELIVERY_TIMEOUT:g} s (infra)"
        ) from None
    forwarded = [delivery for delivery in found.values() if delivery.relay_status is not None]
    assert not forwarded, f"deliveries reached the stopped webapp (precondition): {[d.guid for d in forwarded]}"
    return list(found.values())


# --- configuration --------------------------------------------------------------------------------------------------
@pytest.mark.scenario("W-RT-CONFIG-TEAMS", priority="P1")
@pytest.mark.tags("webapp", "teams", "webhooks-app")
def test_organization_teams_override_the_environment(
    webapp_scenario: WebappScenario,
    webapp_env: Callable[[Mapping[str, str]], None],
    webapp_otterdog_json: Callable[[Mapping[str, Any]], None],
) -> None:
    """GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS name a team that does not exist: the help comment names the admin
    and approval teams of the otterdog.json organization entry; once the entry drops them, the environment's."""
    s, texts = webapp_scenario, webapp_scenario.texts
    _require_org_teams(s)
    nobody = s.run_ctx.name(f"{s.slug}-nobody")  # no team of the org carries this slug
    admin, approval = s.target.admin_team, _slug(s.target.approval_team)
    webapp_env({"GITHUB_ADMIN_TEAMS": nobody, "GITHUB_APPROVAL_TEAMS": f"^{nobody}$"})
    pr = s.open_pr(s.harmless_text())  # otterdog.json of the run: admin_teams [admin], approval_teams [^approval$]
    first = s.wait_comment(pr, marker="help")
    body = first.get("body") or ""
    assert comment_contains(body, texts.HELP), f"help comment without its greeting: {body[:300]!r}"
    assert comment_contains(body, _approval_line(approval)), f"help comment ignores the org approval teams:\n{body}"
    assert comment_contains(body, f"`{s.org}/{admin}`"), f"help comment ignores the org admin teams:\n{body}"
    assert nobody not in body, (
        f"the environment's teams leaked into the help comment of an org that sets its own:\n{body}"
    )

    webapp_otterdog_json({"admin_teams": None, "approval_teams": None})
    s.flow.comment(pr, "/otterdog help")
    second = s.wait_comment(pr, marker="help", exclude=[first])
    body = second.get("body") or ""
    assert comment_contains(body, _no_approval_line(f"^{nobody}$")), f"help comment ignores the environment:\n{body}"
    assert comment_contains(body, f"`{s.org}/{nobody}`"), f"help comment ignores GITHUB_ADMIN_TEAMS:\n{body}"
    assert f"{s.org}/{admin}`" not in body, f"the dropped org admin teams still apply:\n{body}"


@pytest.mark.scenario("W-RT-ADMIN-TEAMS-SPACES", priority="P2")
@pytest.mark.tags("webapp", "teams")
@pytest.mark.known_bug("KB-013")
@pytest.mark.xfail(
    raises=AdminTeamsSplitError,
    strict=False,
    reason="KB-013: GITHUB_ADMIN_TEAMS entries are split on ',' without stripping",
)
def test_admin_teams_list_with_spaces(
    webapp_scenario: WebappScenario,
    webapp_env: Callable[[Mapping[str, str]], None],
    webapp_otterdog_json: Callable[[Mapping[str, Any]], None],
) -> None:
    """GITHUB_ADMIN_TEAMS 'x, <admin>' names '<org>/x, <org>/<admin>' in the help comment; the approval patterns
    '^x$, ^<approval>$' (stripped by otterdog) are the strict control."""
    s = webapp_scenario
    _require_org_teams(s)
    nobody = s.run_ctx.name(f"{s.slug}-nobody")
    admin, approval = s.target.admin_team, _slug(s.target.approval_team)
    webapp_otterdog_json({"admin_teams": None, "approval_teams": None})  # the environment applies to the org
    webapp_env({"GITHUB_ADMIN_TEAMS": f"{nobody}, {admin}", "GITHUB_APPROVAL_TEAMS": f"^{nobody}$, ^{approval}$"})
    pr = s.open_pr(s.harmless_text())
    body = s.wait_comment(pr, marker="help").get("body") or ""
    assert comment_contains(body, _approval_line(approval)), f"approval patterns with spaces do not match:\n{body}"
    s.write_evidence({"help": body})
    if not comment_contains(body, f"`{s.org}/{nobody}, {s.org}/{admin}`"):
        raise AdminTeamsSplitError(f"GITHUB_ADMIN_TEAMS '{nobody}, {admin}' is not rendered as two teams:\n{body}")


# --- /internal/init -------------------------------------------------------------------------------------------------
@pytest.mark.scenario("W-RT-INIT-IMPORTS-PRS", priority="P2")
@pytest.mark.tags("webapp")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
def test_init_imports_existing_pull_requests(
    webapp_scenario: WebappScenario, webapp_stack: WebappStack, relay: DeliveryRelay, mutator: Mutator
) -> None:
    """PRs opened while the webapp is stopped: /internal/init imports the open one targeting main (open, not applied,
    never validated) and the one merged meanwhile (merged and considered applied, although nothing applied it), but not
    the one targeting another branch; /otterdog validate then validates the imported open PR."""
    s = webapp_scenario
    base, head = s.run_ctx.branch(f"{s.slug}-base"), s.run_ctx.branch(f"{s.slug}-other")
    other: int | None = None
    s.quiesce()
    stopped_at = datetime.now(UTC)
    webapp_stack.stop_service("webapp")
    try:
        try:
            pr = s.open_pr(s.harmless_text())
            merged = s.open_pr(
                s.text(overrides={s.harmless_repo: s.describe("merged while the webapp was stopped")}), suffix="merged"
            )
            s.flow.merge(merged, method="squash")
            main = s.flow.main_sha()
            mutator.create_branch(s.repo, base, main)
            mutator.create_branch(s.repo, head, main)
            note = f"e2e-{s.run_ctx.run_id}-{s.slug}.md"  # not a configuration file: no guard needed
            mutator.commit_files(s.repo, head, {note: s.describe("PR against another base")}, "otterdog-e2e: note")
            pull = mutator.create_pull(
                s.repo, head=head, base=base, title=f"e2e {s.run_ctx.run_id} {s.sid} other base", body=s.describe("x")
            )
            other = int(pull["number"])
            lost = {(pr.number, "opened"), (other, "opened"), (merged.number, "opened"), (merged.number, "closed")}
            _wait_lost(relay, lost, after=stopped_at)
        finally:
            webapp_stack.start_service("webapp")
        initialized = datetime.now(UTC)
        webapp_stack.init()
        webapp_stack.wait_ready(timeout=READY_TIMEOUT)
        task = _wait_task(s, FETCH_ALL_PRS, s.repo, after=initialized)
        assert task.get("status") == "finished", f"{FETCH_ALL_PRS} after /internal/init failed (SUT): {task}"

        record = s.api.pull_request(s.org, s.repo, pr.number)
        assert record is not None, f"/internal/init did not import PR #{pr.number} into /api/pullrequests/open (SUT)"
        assert record.get("status") == "open" and record.get("draft") is False, f"imported record: {record}"
        assert record.get("apply_status") == "not_applied" and record.get("valid") is None, f"imported: {record}"
        assert s.api.pull_request(s.org, s.repo, other) is None, f"PR #{other} against {base} was imported"
        assert not s.flow.bot_comments(pr), f"the webapp commented PR #{pr.number} it should not know of"
        imported = s.api.pull_request(s.org, s.repo, merged.number)
        assert imported is not None and imported.get("status") == "merged", f"merged PR not imported: {imported}"
        assert imported.get("apply_status") == "completed", f"an imported merged PR counts as applied: {imported}"
        assert not s.flow.bot_comments(merged), f"the webapp reacted to PR #{merged.number} merged while it was down"
        s.write_evidence({"open": record, "merged": imported, "other_base": other})

        s.flow.comment(pr, "/otterdog validate")
        validate = s.wait_comment(pr, marker="validate")
        assert comment_contains(validate.get("body") or "", f"{s.texts.DIFF_FOR} {pr.head_sha}"), "validate comment"
        s.wait_validation(pr)
        s.wait_api_pull(pr, until=lambda r: r.get("valid") is True, what="valid after /otterdog validate")
    finally:
        if other is not None:
            mutator.close_pull(s.repo, other)
        for branch in (head, base):
            mutator.delete_ref(s.repo, f"heads/{branch}")


class ApplyStatusLostError(AssertionError):
    """/internal/init turned the apply status of a merged PR into completed (FetchAllPullRequestsTask, KB-074)."""


@pytest.mark.scenario("W-RT-INIT-APPLY-STATUS", priority="P2")
@pytest.mark.tags("webapp", "secrets", "repo")
@pytest.mark.known_bug("KB-074")
@pytest.mark.timeout(LONG_TIMEOUT, func_only=True)
@pytest.mark.xfail(
    raises=ApplyStatusLostError,
    strict=False,
    reason="KB-074: FetchAllPullRequestsTask imports every merged PR as completed, also over partially_applied",
)
def test_init_keeps_the_apply_status(
    e2e: E2EContext, webapp: WebappStack | ExternalWebapp, webapp_scenario: WebappScenario
) -> None:
    """A merged PR adding a repository secret is partially applied (secrets need a manual apply); a later
    /internal/init re-imports the config repo's PRs and must keep it partially applied, so that ``/otterdog done``
    still completes it (tasks/fetch_all_pull_requests.py:53-62 and db/service.py:538-539 overwrite it)."""
    s = webapp_scenario
    name, secret = s.run_repo(), s.run_ctx.const(f"{s.slug}-secret")
    repo = (
        f"orgs.newRepo('{name}') {{ description: '{s.describe('secret needs a manual apply')}', "
        f"secrets: [ orgs.newRepoSecret('{secret}') {{ value: '********' }} ] }}"
    )
    pr = s.open_pr(s.renderer.render(ConfigFragments(repositories=[repo])))
    s.wait_settled(pr)
    body = s.wait_comment(pr, marker="validate").get("body") or ""
    assert comment_contains(body, SECRETS_WARNING), f"the validation does not ask for a manual apply:\n{body[:2000]}"
    s.flow.merge(pr, method="squash")
    s.wait_merged(pr)
    applied = s.wait_applied(pr).get("body") or ""
    assert comment_contains(applied, PARTIAL_APPLY), f"the apply comment does not report a partial apply:\n{applied}"
    s.wait_repo(name)
    before = s.wait_api_pull(pr, until=lambda r: r.get("apply_status") == "partially_applied", what="partially applied")

    initialized = datetime.now(UTC)
    e2e.reload_webapp(webapp)  # /internal/init and the readiness wait of the session
    task = _wait_task(s, FETCH_ALL_PRS, s.repo, after=initialized)
    assert task.get("status") == "finished", f"{FETCH_ALL_PRS} after /internal/init failed (SUT): {task}"
    after = s.api.pull_request(s.org, s.repo, pr.number)
    s.write_evidence({"before": before, "after": after})
    assert after is not None and after.get("status") == "merged", f"PR #{pr.number} after /internal/init: {after}"
    if after.get("apply_status") != "partially_applied":
        raise ApplyStatusLostError(
            f"/internal/init changed the apply status of PR #{pr.number} from partially_applied to "
            f"{after.get('apply_status')!r}: /otterdog done and /otterdog apply now skip it"
        )


# --- /api/projects and pages ----------------------------------------------------------------------------------------
@pytest.mark.scenario("W-RT-API-PROJECTS", priority="P2")
@pytest.mark.tags("webapp")
def test_project_api(webapp_scenario: WebappScenario) -> None:
    """/api/projects/<project> answers the stored configuration of /api/organizations/<org>; an unknown project or
    organization answers 404 with an empty JSON object."""
    s = webapp_scenario
    s.quiesce()  # no FetchConfigTask may replace the configuration between the two reads
    project = s.api.project_name(s.org)
    assert project, f"/api/organizations does not list {s.org}"
    stored = s.api.organization(s.org)
    assert stored is not None and stored.get("github_id") == s.org, f"/api/organizations/{s.org}: {stored}"
    assert s.api.project(project) == stored, f"/api/projects/{project} differs from /api/organizations/{s.org}"
    unknown = s.run_ctx.name(f"{s.slug}-unknown")
    for path in (f"/api/projects/{unknown}", f"/api/organizations/{unknown}"):
        response = s.api.get(path, allow=(404,))
        assert response.json() == {}, f"GET {path}: {response.status_code} {response.text[:200]!r}"


@pytest.mark.scenario("W-RT-PAGES", priority="P2")
@pytest.mark.tags("webapp", "template")
def test_project_and_admin_pages(webapp_scenario: WebappScenario, installation_id: int) -> None:
    """Redirects of /organizations/<org>[/repos/<repo>], the project, repository, defaults and playground pages, the
    404 pages of unknown names, /allprojects and the installation row of /admin/organizations."""
    s = webapp_scenario
    project, repo = s.api.project_name(s.org), s.harmless_repo
    assert project, f"/api/organizations does not list {s.org}"
    quoted = urllib.parse.quote(project, safe="")
    response = s.api.get(f"/organizations/{s.org}", allow=(302,))
    assert _location(response).endswith(f"/projects/{project}"), (
        f"redirect of /organizations/{s.org}: {_location(response)}"
    )
    response = s.api.get(f"/organizations/{s.org}/repos/{repo}", allow=(302,))
    assert _location(response).endswith(f"/projects/{project}/repos/{repo}"), f"redirect: {_location(response)}"

    page = s.api.get(f"/projects/{quoted}").text
    root = parse_html(page)
    assert root.find_id("policies") is not None and root.find_id("blueprints") is not None, "project page tabs"
    assert f"https://github.com/{s.org}/{repo}" in page, f"the project page does not list {repo}"
    repo_page = parse_html(s.api.get(f"/projects/{quoted}/repos/{repo}").text).text()
    assert f"Repository {repo}" in repo_page, f"the repository page does not name {repo}"

    defaults = parse_html(s.api.get(f"/projects/{quoted}/defaults", timeout=PAGE_TIMEOUT).text).text()
    for snippet in ("orgs.newOrg('<project-name>', '<github-id>') =", "orgs.newRepo('<name>') ="):
        assert snippet in defaults, f"the defaults page lacks {snippet!r} (template not evaluated?)"
    playground = parse_html(s.api.get(f"/projects/{quoted}/playground", timeout=PAGE_TIMEOUT).text)
    templates = [
        area
        for area in playground.iter("textarea")
        if area.attrs.get("id") not in ("playground-jsonnet", "json-output")
    ]
    assert any("newRepo" in area.text() for area in templates), "the playground does not show the base template"

    unknown = s.run_ctx.name(f"{s.slug}-unknown")
    for path in (f"/organizations/{unknown}", f"/projects/{unknown}", f"/projects/{quoted}/repos/{unknown}"):
        response = s.api.get(path, allow=(404,))
        assert "text/html" in response.headers.get("Content-Type", ""), f"GET {path}: not the 404 page"
    assert project in parse_html(s.api.get("/allprojects").text).text(), f"/allprojects does not list {project}"
    row = s.api.installations().get(s.org)
    assert row == {"installation_id": installation_id, "status": "installed", "project_name": project}, (
        f"/admin/organizations row of {s.org}: {row}"
    )
