"""WebappApi blueprint/scorecard/project endpoints, /internal/check, GraphQL, statistics and the page parsers.

The HTML fragments below are trimmed copies of the pages the webapp image of otterdog main 9bdeb75 rendered in local
docker from documents inserted into its MongoDB (installation, policy_status, blueprint, blueprint_status): the same
structure, classes, ids and values (statuses are the enum NAMES, the org cell starts with an icon and ``&nbsp;``).
The same run checked the API answers: /internal/<unknown> 404, statistics ``interval=hour`` 400 {"error":
"unsupported interval 'hour'"}, GraphQL 200 {"data": {"projects": []}} and 400 for an invalid query.
"""

from __future__ import annotations

from typing import Any

import pytest
import responses
from responses import matchers

from otterdog_e2e.webapp.api import (
    WebappApi,
    WebappApiError,
    anchored,
    parse_blueprint_statuses,
    parse_html,
    parse_installations,
    parse_policy_status,
    snake_key,
    table_rows,
)

BASE = "http://127.0.0.1:5997"
ORG = "e2e-test-org"
PROJECT = "e2e-project"
BLUEPRINT = "e2e-t3c7z8a5-bp"

ORGANIZATIONS_PAGE = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><title>Otterdog Dashboard - Organizations</title>
<script>var x = "<td>not a cell</td>";</script></head>
<body><div class="wrapper"><div class="content-wrapper"><section class="content"><div class="card">
<div class="card-header"><h3 class="card-title">List of GitHub organizations</h3></div>
<div class="card-body">
                <table id="organizations" class="table table-bordered table-hover">
                  <thead>
                  <tr>
                    <th>Installation ID</th>
                    <th>Installation Status</th>
                    <th>Project Name</th>
                    <th>GitHub Organization</th>
                  </tr>
                  </thead>
                  <tbody>
                    <tr>
                      <td>4242</td>
                      <td>INSTALLED</td>
                      <td>e2e-project</td>
                      <td><a href="https://github.com/e2e-test-org" target="_blank"><i class="fab fa-github"></i> &nbsp; e2e-test-org</a></td>
                    </tr>
                    <tr>
                      <td>0</td>
                      <td>NOT_INSTALLED</td>
                      <td>other</td>
                      <td><a href="https://github.com/e2e-other" target="_blank"><i class="fab fa-github"></i> &nbsp; e2e-other</a></td>
                    </tr>
                  </tbody>
                </table>
</div></div></section></div></div></body></html>
"""

POLICIES_PAGE = """<!DOCTYPE html><html lang="en"><body><div class="content-wrapper"><section class="content">
      <div class="container-fluid">
        <div class="card card-info">
          <div class="card-header">
            <h3 class="card-title">macos_large_runners</h3>
          </div>
          <div class="card-body">
            <div class="table-responsive p-0">
              <table class="table table-hover text-nowrap">
                <thead>
                  <tr>
                    <th>Total Workflow Jobs</th>
                    <th>Permitted On Restricted Runners</th>
                    <th>Cancelled On Restricted Runners</th>
                  </tr>
                </thead>
                <tbody>
                  <tr>
                    <td>3</td>
                    <td>1</td>
                    <td>2</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>
</section></div></body></html>
"""

STATUS_ROWS = """
                                      <tr class="table-warning">
                                        <td><a href="https://github.com/e2e-test-org/e2e-t3c7z8a5-bp-a">e2e-t3c7z8a5-bp-a</a></td>
                                        <td>2026-10-03 08:00:00</td>
                                        <td>REMEDIATION_PREPARED</td>
                                        <td>
                                            <a href="https://github.com/e2e-test-org/e2e-t3c7z8a5-bp-a/pull/7">#7</a>
                                        </td>
                                      </tr>
                                      <tr class="table-success">
                                        <td><a href="https://github.com/e2e-test-org/e2e-t3c7z8a5-bp-b">e2e-t3c7z8a5-bp-b</a></td>
                                        <td>2026-10-03 08:01:00</td>
                                        <td>SUCCESS</td>
                                        <td>
                                            N/A
                                        </td>
                                      </tr>
"""


def blueprint_pane(blueprint_id: str, rows: str) -> str:
    """One blueprint tab of /projects/<project> (templates/home/organization.html)."""
    return f"""
                          <div class="tab-pane show active" id="blueprint-{blueprint_id}" role="tabpanel" aria-labelledby="blueprint-{blueprint_id}-tab">
                            <div class="card card-primary">
                              <div class="card-header"><h3 class="card-title">E2E</h3></div>
                              <div class="card-body">
                                <div id="blueprint-{blueprint_id}-desc"></div>
                                <script>
                                  document.getElementById('blueprint-{blueprint_id}-desc').innerHTML =
                                    marked.parse('desc', {{ gfm: true, breaks: true}});
                                </script>
                                Reference: <a href="https://github.com/x" target="_blank">https://github.com/x</a>
                              </div>
                            </div>
                            <div class="card card-primary collapsed-card">
                              <div class="card-body">
                                <pre><code class="language-json">{{ &#39;files&#39; : [] }}</code></pre>
                              </div>
                            </div>
                            <div class="card card-info">
                              <div class="card-body">
                                <div class="table-responsive p-0">
                                  <table class="table table-hover text-nowrap">
                                    <thead>
                                      <tr>
                                        <th>Repository</th>
                                        <th>Updated At</th>
                                        <th>Status</th>
                                        <th>Remediation PR</th>
                                      </tr>
                                    </thead>
                                    <tbody>{rows}</tbody>
                                  </table>
                                </div>
                              </div>
                            </div>
                          </div>"""


PROJECT_PAGE = f"""<!DOCTYPE html><html lang="en"><body>
<a class="nav-link active" id="blueprint-{BLUEPRINT}-tab" data-toggle="pill" href="#blueprint-{BLUEPRINT}" role="tab">{BLUEPRINT}</a>
<div class="tab-content" id="blueprints-tabContent">
{blueprint_pane(BLUEPRINT, STATUS_ROWS)}
{blueprint_pane(BLUEPRINT + "-other", "")}
</div>
<table class="table"><thead><tr><th>Repository</th><th>Updated At</th><th>Status</th></tr></thead>
<tbody><tr><td>outside</td><td>x</td><td>FAILURE</td><td>N/A</td></tr></tbody></table>
</body></html>
"""


@pytest.fixture
def api() -> WebappApi:
    """WebappApi on BASE."""
    return WebappApi(BASE)


# --- parsers -------------------------------------------------------------------------------------------------------
def test_parse_installations() -> None:
    """github_id -> installation id, lower-case status value, project name (icons and &nbsp; ignored)."""
    assert parse_installations(ORGANIZATIONS_PAGE) == {
        ORG: {"installation_id": 4242, "status": "installed", "project_name": PROJECT},
        "e2e-other": {"installation_id": 0, "status": "not_installed", "project_name": "other"},
    }
    with pytest.raises(WebappApiError, match="table#organizations"):
        parse_installations("<html><body><table></table></body></html>")


def test_parse_policy_status() -> None:
    """policy type -> snake_case counters as ints."""
    assert parse_policy_status(POLICIES_PAGE) == {
        "macos_large_runners": {
            "total_workflow_jobs": 3,
            "permitted_on_restricted_runners": 1,
            "cancelled_on_restricted_runners": 2,
        }
    }
    assert parse_policy_status("<html><body><div class='card'><h3 class='card-title'>x</h3></div></body></html>") == {}


def test_parse_blueprint_statuses() -> None:
    """Rows of the blueprint's own Status table only: lower-case statuses, PR numbers, None for N/A; a blueprint
    without rows is {}; an unknown blueprint None."""
    assert parse_blueprint_statuses(PROJECT_PAGE, BLUEPRINT) == {
        "e2e-t3c7z8a5-bp-a": {
            "status": "remediation_prepared",
            "updated_at": "2026-10-03 08:00:00",
            "remediation_pr": 7,
        },
        "e2e-t3c7z8a5-bp-b": {"status": "success", "updated_at": "2026-10-03 08:01:00", "remediation_pr": None},
    }
    assert parse_blueprint_statuses(PROJECT_PAGE, BLUEPRINT + "-other") == {}
    assert parse_blueprint_statuses(PROJECT_PAGE, "e2e-t3c7z8a5-unknown") is None


def test_html_tree_tolerates_real_world_markup() -> None:
    """Void elements, self-closing tags, unclosed cells and stray end tags; script and style text is dropped."""
    root = parse_html(
        "<div id='a'><br><img src=x><input/><p>one<td>two</p></span>"
        "<style>.x{}</style><script>var t='<b>';</script><table><tr><th>H a</th><td>1<td>2</tr></table></div>"
    )
    node = root.find_id("a")
    assert node is not None and node.tag == "div"
    assert "var t" not in node.text() and ".x" not in node.text()
    headers, rows = table_rows(node.iter("table")[0])
    assert headers == ["H a"] and rows == [["1", "2"]]
    assert root.find_id("missing") is None and node.has_class("x") is False


def test_snake_key() -> None:
    """otterdog's snake_to_normal filter reversed."""
    assert snake_key("Permitted On Restricted Runners") == "permitted_on_restricted_runners"
    assert snake_key(" Updated At ") == "updated_at" and snake_key("Remediation PR") == "remediation_pr"


# --- endpoints -----------------------------------------------------------------------------------------------------
@responses.activate
def test_check(api: WebappApi) -> None:
    """/internal/check and /internal/check/<limit>; bad limits are refused locally."""
    responses.get(f"{BASE}/internal/check", json={})
    responses.get(f"{BASE}/internal/check/5", json={})
    api.check()
    api.check(5)
    assert [call.request.url for call in responses.calls] == [f"{BASE}/internal/check", f"{BASE}/internal/check/5"]
    for bad in (-1, True):
        with pytest.raises(ValueError):
            api.check(bad)
    responses.get(f"{BASE}/internal/check/1", status=500, json={})
    with pytest.raises(WebappApiError):
        api.check(1)


@responses.activate
def test_project_name_and_project(api: WebappApi) -> None:
    """project_name from /api/organizations (exact github_id); /api/projects/<name> None on 404."""
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": ORG.upper(), "project_name": "x"}])
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": ORG, "project_name": PROJECT}])
    assert api.project_name(ORG) is None
    assert api.project_name(ORG) == PROJECT
    responses.get(f"{BASE}/api/projects/{PROJECT}", json={"github_id": ORG, "project_name": PROJECT})
    responses.get(f"{BASE}/api/projects/nope", status=404, json={})
    assert api.project(PROJECT) == {"github_id": ORG, "project_name": PROJECT}
    assert api.project("nope") is None


def status_row(repo: str, status: str, pr: int | None) -> dict[str, Any]:
    """A /api/blueprints/* row (BlueprintStatusModel.model_dump)."""
    return {
        "id": {"org_id": ORG, "repo_name": repo, "blueprint_id": BLUEPRINT},
        "updated_at": "2026-10-03T08:00:00",
        "status": status,
        "remediation_pr": pr,
    }


@responses.activate
def test_blueprint_listings_use_anchored_id_filters_and_pages(api: WebappApi, monkeypatch: pytest.MonkeyPatch) -> None:
    """remediations / dismissed / scorecard: id[...] filters as anchored regexes, every page followed."""
    monkeypatch.setattr("otterdog_e2e.webapp.api.BLUEPRINT_PAGE_SIZE", 1)
    first = {"id[org_id]": anchored(ORG), "id[blueprint_id]": anchored(BLUEPRINT), "pageSize": "1", "pageIndex": "1"}
    second = {**first, "pageIndex": "2"}
    url = f"{BASE}/api/blueprints/remediations"
    responses.get(
        url,
        match=[matchers.query_param_matcher(first)],
        json={"data": [status_row("a", "remediation_prepared", 7)], "itemsCount": 2},
    )
    responses.get(
        url,
        match=[matchers.query_param_matcher(second)],
        json={"data": [status_row("b", "remediation_prepared", 8)], "itemsCount": 2},
    )
    rows = api.blueprint_remediations(org_id=ORG, blueprint_id=BLUEPRINT)
    assert [row["remediation_pr"] for row in rows] == [7, 8]
    dismissed = {"id[repo_name]": "^c$", "pageSize": "1", "pageIndex": "1"}
    responses.get(
        f"{BASE}/api/blueprints/dismissed",
        match=[matchers.query_param_matcher(dismissed)],
        json={"data": [status_row("c", "dismissed", 9)], "itemsCount": 1},
    )
    assert api.dismissed_blueprints(repo_name="c")[0]["status"] == "dismissed"
    scorecard = {"id[org_id]": anchored(ORG), "pageSize": "1", "pageIndex": "1"}
    responses.get(
        f"{BASE}/api/scorecard/results",
        match=[matchers.query_param_matcher(scorecard)],
        json={"data": [], "itemsCount": 0},
    )
    assert api.scorecard_results(org_id=ORG) == []


@responses.activate
def test_page_reads(api: WebappApi) -> None:
    """installations(), policy_status() and blueprint_statuses() read and parse the pages; an unknown project is
    None."""
    responses.get(f"{BASE}/admin/organizations", body=ORGANIZATIONS_PAGE)
    responses.get(f"{BASE}/admin/policies", body=POLICIES_PAGE)
    responses.get(f"{BASE}/projects/{PROJECT}", body=PROJECT_PAGE)
    responses.get(f"{BASE}/projects/nope", status=404, body="<html>404</html>")
    assert api.installations()[ORG]["status"] == "installed"
    assert api.policy_status()["macos_large_runners"]["total_workflow_jobs"] == 3
    statuses = api.blueprint_statuses(PROJECT, BLUEPRINT)
    assert statuses is not None and statuses["e2e-t3c7z8a5-bp-a"]["remediation_pr"] == 7
    assert api.blueprint_statuses("nope", BLUEPRINT) is None


@responses.activate
def test_graphql(api: WebappApi) -> None:
    """POST /api/graphql: 200 results and 400 errors are returned, variables only when given."""
    responses.post(
        f"{BASE}/api/graphql",
        match=[matchers.json_params_matcher({"query": "{ projects { github_id } }"})],
        json={"data": {"projects": [{"github_id": ORG}]}},
    )
    responses.post(
        f"{BASE}/api/graphql",
        match=[matchers.json_params_matcher({"query": "{ nope }", "variables": {"a": 1}})],
        status=400,
        json={"errors": [{"message": "Cannot query field 'nope'"}]},
    )
    assert api.graphql("{ projects { github_id } }") == (200, {"data": {"projects": [{"github_id": ORG}]}})
    status, body = api.graphql("{ nope }", {"a": 1})
    assert status == 400 and body["errors"]
    responses.post(f"{BASE}/api/graphql", status=500, body="boom")
    with pytest.raises(WebappApiError):
        api.graphql("{ projects { github_id } }")


@responses.activate
def test_statistics_progress(api: WebappApi) -> None:
    """interval/range/org parameters as given; a 400 for unsupported values is returned, not raised."""
    responses.get(
        f"{BASE}/api/pullrequests/statistics/progress",
        match=[matchers.query_param_matcher({"interval": "week", "range": "30d", "org": ORG})],
        json={"status": "running", "progress": 0},
    )
    responses.get(
        f"{BASE}/api/pullrequests/statistics/progress",
        match=[matchers.query_param_matcher({"interval": "hour", "range": "12m"})],
        status=400,
        json={"error": "unsupported interval 'hour'"},
    )
    assert api.statistics_progress(interval="week", range_="30d", org=ORG) == (
        200,
        {"status": "running", "progress": 0},
    )
    assert api.statistics_progress(interval="hour") == (400, {"error": "unsupported interval 'hour'"})


@responses.activate
def test_post_errors_are_redacted_api_errors(api: WebappApi) -> None:
    """post(): statuses outside ``allow`` raise WebappApiError."""
    responses.post(f"{BASE}/x", status=404, body="missing")
    with pytest.raises(WebappApiError, match=r"POST .*/x -> HTTP 404"):
        api.post("/x", json_body={})
    assert api.post("/x", json_body={}, allow=(404,)).status_code == 404
