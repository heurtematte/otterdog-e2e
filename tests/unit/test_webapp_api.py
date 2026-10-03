"""WebappApi (SPEC 13.2, OC-07): anchored regex filters, id[...] keys, naive-UTC timestamps, waits; loopback helpers."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest
import requests
import responses
from responses import matchers

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.waiting import WaitTimeoutError
from otterdog_e2e.webapp.api import (
    RemoteEndpointError,
    WebappApi,
    WebappApiError,
    anchored,
    is_loopback_url,
    parse_timestamp,
    require_loopback_url,
)

BASE = "http://127.0.0.1:5999"
ORG = "e2e-test-org"
REPO = "e2e-t3c7z8a5-config"
PAGING = {"pageSize": "100", "pageIndex": "1", "sortField": "created_at", "sortOrder": "desc"}


class FakeTime:
    """Monotonic clock advanced by sleep(); ``on_sleep`` hooks change the world between polls."""

    def __init__(self) -> None:
        """Start at t=0."""
        self.now = 0.0
        self.sleeps: list[float] = []
        self.on_sleep: list[Any] = []

    def clock(self) -> float:
        """Current fake time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the fake time and run the next hook."""
        self.sleeps.append(seconds)
        self.now += seconds
        if self.on_sleep:
            self.on_sleep.pop(0)()


@pytest.fixture
def fake_time() -> FakeTime:
    """A fresh fake clock."""
    return FakeTime()


@pytest.fixture
def api(fake_time: FakeTime) -> WebappApi:
    """WebappApi on BASE with the fake clock."""
    client = WebappApi(BASE)
    client.sleep = fake_time.sleep
    client.clock = fake_time.clock
    return client


def task(type_: str, status: str, created_at: str, *, pull_request: int = 0, org: str = ORG) -> dict[str, Any]:
    """A /api/tasks row (TaskModel.model_dump(exclude={'id'}))."""
    return {
        "type": type_,
        "org_id": org,
        "repo_name": REPO,
        "pull_request": pull_request,
        "status": status,
        "log": None,
        "cache_stats": "",
        "rate_limit_remaining": "",
        "created_at": created_at,
        "updated_at": created_at,
    }


def pr_record(number: int, status: str = "open", apply_status: str = "not_applied") -> dict[str, Any]:
    """A /api/pullrequests row (PullRequestModel.model_dump())."""
    return {
        "id": {"org_id": ORG, "repo_name": REPO, "pull_request": number},
        "draft": False,
        "status": status,
        "apply_status": apply_status,
        "valid": True,
        "created_at": "2026-10-02T12:00:00",
        "updated_at": "2026-10-02T12:00:00",
        "merged_at": None,
    }


# --- helpers -------------------------------------------------------------------------------------------------------
def test_anchored_escapes_regex_metacharacters() -> None:
    """Filters are exact matches: ^...$ around re.escape (the webapp uses $regex on every TaskModel field)."""
    assert anchored("FetchConfigTask") == "^FetchConfigTask$"
    assert anchored(".otterdog") == r"^\.otterdog$"
    pattern = anchored(REPO)
    assert re.match(pattern, REPO) and not re.match(pattern, REPO + "2") and not re.match(pattern, "x" + REPO)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2026-10-02T12:00:00.123000", datetime(2026, 10, 2, 12, 0, 0, 123000, tzinfo=UTC)),  # webapp: naive UTC
        ("2026-10-02T12:00:00Z", datetime(2026, 10, 2, 12, tzinfo=UTC)),  # GitHub
        ("2026-10-02T14:00:00+02:00", datetime(2026, 10, 2, 12, tzinfo=UTC)),
        (datetime(2026, 10, 2, 12), datetime(2026, 10, 2, 12, tzinfo=UTC)),  # noqa: DTZ001 - naive input
        ("not a date", None),
        (None, None),
        ("", None),
    ],
)
def test_parse_timestamp(value: Any, expected: datetime | None) -> None:
    """Naive timestamps are UTC; offsets are converted; garbage is None."""
    assert parse_timestamp(value) == expected


@pytest.mark.parametrize(
    ("url", "loopback"),
    [
        ("http://127.0.0.1:5000", True),
        ("https://127.10.0.1/x", True),
        ("http://localhost:8080/github-webhook/receive", True),
        ("http://[::1]:5000", True),
        ("http://example.org:5000", False),
        ("http://10.0.0.1:5000", False),
        ("ftp://127.0.0.1/", False),
        ("127.0.0.1:5000", False),
    ],
)
def test_is_loopback_url(url: str, loopback: bool) -> None:
    """Only http(s) URLs on localhost / 127.0.0.0/8 / ::1 are loopback."""
    assert is_loopback_url(url) is loopback


def test_require_loopback_url() -> None:
    """Remote endpoints need allow_remote; the error is both a SafetyError and a ValueError."""
    require_loopback_url("http://127.0.0.1:5000")
    with pytest.raises(RemoteEndpointError) as info:
        require_loopback_url("https://otterdog.example.org", what="external webapp URL")
    assert isinstance(info.value, SafetyError) and isinstance(info.value, ValueError)
    assert "external webapp URL" in str(info.value)
    require_loopback_url("https://otterdog.example.org", allow_remote=True)
    with pytest.raises(RemoteEndpointError):
        require_loopback_url("file:///etc/passwd", allow_remote=True)


def test_session_never_trusts_the_environment() -> None:
    """A given session gets trust_env False (no proxies, no ~/.netrc)."""
    session = requests.Session()
    assert WebappApi(BASE, session=session).session is session and session.trust_env is False
    assert WebappApi(BASE + "/").base_url == BASE


# --- endpoints -----------------------------------------------------------------------------------------------------
@responses.activate
def test_health(api: WebappApi) -> None:
    """200 is healthy; other statuses and connection errors are not."""
    responses.get(f"{BASE}/internal/health", json={})
    assert api.health() is True
    responses.replace(responses.GET, f"{BASE}/internal/health", status=500, json={})
    assert api.health() is False
    assert WebappApi("http://127.0.0.1:1").health() is False  # nothing registered: ConnectionError


@responses.activate
def test_organizations_and_organization(api: WebappApi) -> None:
    """/api/organizations is a list; /api/organizations/<id> is None on 404."""
    responses.get(f"{BASE}/api/organizations", json=[{"github_id": ORG, "project_name": ORG}])
    responses.get(f"{BASE}/api/organizations/{ORG}", json={"github_id": ORG, "settings": {}})
    responses.get(f"{BASE}/api/organizations/other", status=404, json={})
    assert api.organizations() == [{"github_id": ORG, "project_name": ORG}]
    assert api.organization(ORG) == {"github_id": ORG, "settings": {}}
    assert api.organization("other") is None


@responses.activate
def test_errors_are_redacted(api: WebappApi) -> None:
    """Unexpected statuses raise WebappApiError with status and redacted body."""
    secret = "e2e-webapp-api-secret-4242"
    REDACTOR.add(secret)
    responses.get(f"{BASE}/api/organizations", status=500, body=f"boom {secret}")
    with pytest.raises(WebappApiError) as info:
        api.organizations()
    assert info.value.status == 500 and secret not in str(info.value) and "***" in info.value.body


@responses.activate
def test_tasks_send_anchored_filters_and_paging(api: WebappApi) -> None:
    """type/org_id/repo_name/status are anchored regexes; paging and newest-first sorting are explicit."""
    expected = {
        **PAGING,
        "type": "^FetchConfigTask$",
        "org_id": r"^e2e\-test\-org$",
        "repo_name": r"^e2e\-t3c7z8a5\-config$",
        "status": "^finished$",
    }
    rows = [task("FetchConfigTask", "finished", "2026-10-02T12:00:00")]
    responses.get(
        f"{BASE}/api/tasks", json={"data": rows, "itemsCount": 1}, match=[matchers.query_param_matcher(expected)]
    )
    assert api.tasks(org_id=ORG, type_="FetchConfigTask", repo_name=REPO, status="finished") == rows


@responses.activate
def test_tasks_without_filters_and_active_tasks(api: WebappApi) -> None:
    """No filter keys unless given; active tasks use one status alternation."""
    responses.get(f"{BASE}/api/tasks", json={"data": [], "itemsCount": 0}, match=[matchers.query_param_matcher(PAGING)])
    assert api.tasks() == []
    active = {**PAGING, "org_id": r"^e2e\-test\-org$", "status": "^(created|scheduled)$"}
    responses.get(f"{BASE}/api/tasks", json={"data": [], "itemsCount": 0}, match=[matchers.query_param_matcher(active)])
    assert api.active_tasks(org_id=ORG) == []


@responses.activate
def test_wait_task_newest_after_with_client_side_pull_request(api: WebappApi, fake_time: FakeTime) -> None:
    """Tasks before ``after`` and of other PRs are ignored; the newest match must reach a final status."""
    after = datetime(2026, 10, 2, 12, 0, 0, 123456, tzinfo=UTC)
    old = task("ValidatePullRequestTask", "finished", "2026-10-02T11:59:59.999", pull_request=7)
    other = task("ValidatePullRequestTask", "finished", "2026-10-02T12:00:01", pull_request=8)
    running = task("ValidatePullRequestTask", "scheduled", "2026-10-02T12:00:00.123", pull_request=7)  # same ms
    done = dict(running, status="finished")
    url = f"{BASE}/api/tasks"
    responses.get(url, json={"data": [other, running, old], "itemsCount": 3})
    responses.get(url, json={"data": [other, done, old], "itemsCount": 3})
    found = api.wait_task(type_="ValidatePullRequestTask", org_id=ORG, after=after, pull_request=7, interval=5)
    assert found["status"] == "finished" and found["pull_request"] == 7
    assert fake_time.sleeps == [5]
    assert responses.calls[0].request.params["type"] == "^ValidatePullRequestTask$"


@responses.activate
def test_wait_task_naive_after_and_timeout(api: WebappApi, fake_time: FakeTime) -> None:
    """A naive ``after`` is UTC; nothing new before the timeout raises WaitTimeoutError."""
    responses.get(f"{BASE}/api/tasks", json={"data": [task("FetchConfigTask", "finished", "2026-10-02T11:00:00")]})
    with pytest.raises(WaitTimeoutError) as info:
        naive = datetime(2026, 10, 2, 12)  # noqa: DTZ001 - naive ``after`` is UTC
        api.wait_task(type_="FetchConfigTask", org_id=ORG, after=naive, timeout=20, interval=5)
    assert "FetchConfigTask" in str(info.value) and fake_time.now == pytest.approx(20)
    tz = timezone(timedelta(hours=2))
    found = api.wait_task(type_="FetchConfigTask", org_id=ORG, after=datetime(2026, 10, 2, 12, 59, tzinfo=tz))
    assert found["created_at"] == "2026-10-02T11:00:00"


@responses.activate
def test_pull_request_lists_use_id_keys_only(api: WebappApi) -> None:
    """open/merged accept only id[org_id] / id[repo_name] (other keys -> KeyError -> HTTP 500 upstream)."""
    expected = {"id[org_id]": r"^e2e\-test\-org$", "id[repo_name]": r"^e2e\-t3c7z8a5\-config$", "pageSize": "100"}
    expected["pageIndex"] = "1"
    responses.get(
        f"{BASE}/api/pullrequests/open",
        json={"data": [pr_record(1)], "itemsCount": 1},
        match=[matchers.query_param_matcher(expected)],
    )
    responses.get(
        f"{BASE}/api/pullrequests/merged",
        json={"data": [pr_record(2, "merged", "completed")], "itemsCount": 1},
        match=[matchers.query_param_matcher(expected)],
    )
    assert [r["id"]["pull_request"] for r in api.open_pull_requests(org_id=ORG, repo_name=REPO)] == [1]
    assert [r["id"]["pull_request"] for r in api.merged_pull_requests(org_id=ORG, repo_name=REPO)] == [2]
    for call in responses.calls:
        assert "org_id" not in call.request.params and "repo_name" not in call.request.params
        assert "id[pull_request]" not in call.request.params


@responses.activate
def test_pull_request_lists_follow_pages(api: WebappApi) -> None:
    """Pages are read until itemsCount records were returned."""
    url = f"{BASE}/api/pullrequests/open"
    page1 = [pr_record(n) for n in range(100)]
    responses.get(
        url,
        json={"data": page1, "itemsCount": 101},
        match=[matchers.query_param_matcher({"pageSize": "100", "pageIndex": "1"})],
    )
    responses.get(
        url,
        json={"data": [pr_record(100)], "itemsCount": 101},
        match=[matchers.query_param_matcher({"pageSize": "100", "pageIndex": "2"})],
    )
    assert len(api.open_pull_requests()) == 101


@responses.activate
def test_pull_request_lookup(api: WebappApi) -> None:
    """The number is matched client-side in the open list, then in the merged list."""
    responses.get(f"{BASE}/api/pullrequests/open", json={"data": [pr_record(3)], "itemsCount": 1})
    responses.get(
        f"{BASE}/api/pullrequests/merged", json={"data": [pr_record(4, "merged", "completed")], "itemsCount": 1}
    )
    assert api.pull_request(ORG, REPO, 3)["status"] == "open"
    assert api.pull_request(ORG, REPO, 4)["apply_status"] == "completed"
    assert api.pull_request(ORG, REPO, 5) is None


@responses.activate
def test_quiesce_waits_for_a_quiet_period(api: WebappApi, fake_time: FakeTime) -> None:
    """Busy tasks reset the quiet timer; quiet_for seconds without active tasks return."""
    url = f"{BASE}/api/tasks"
    busy = {"data": [task("CheckConfigurationInSyncTask", "created", "2026-10-02T12:00:00", pull_request=3)]}
    responses.get(url, json=busy)
    responses.get(url, json={"data": []})
    api.quiesce(org_id=ORG, quiet_for=10, timeout=60)
    assert fake_time.now >= 10
    assert all(call.request.params["status"] == "^(created|scheduled)$" for call in responses.calls)


@responses.activate
def test_quiesce_timeout_lists_busy_tasks(api: WebappApi, fake_time: FakeTime) -> None:
    """Never quiet: WaitTimeoutError naming the busy tasks."""
    responses.get(
        f"{BASE}/api/tasks",
        json={"data": [task("ApplyChangesTask", "scheduled", "2026-10-02T12:00:00", pull_request=9)]},
    )
    with pytest.raises(WaitTimeoutError) as info:
        api.quiesce(org_id=ORG, quiet_for=15, timeout=30)
    assert "ApplyChangesTask#9:scheduled" in str(info.value)


@responses.activate
def test_quiesce_zero_returns_on_first_quiet_check(api: WebappApi, fake_time: FakeTime) -> None:
    """quiet_for=0 needs a single quiet observation."""
    responses.get(f"{BASE}/api/tasks", json={"data": []})
    api.quiesce(org_id=ORG, quiet_for=0)
    assert fake_time.sleeps == []


@responses.activate
def test_init_and_deployed_version(api: WebappApi) -> None:
    """/internal/init must answer 200; the version comes from the /index footer."""
    responses.get(f"{BASE}/internal/init", json={})
    api.init()
    responses.replace(responses.GET, f"{BASE}/internal/init", status=500, json={})
    with pytest.raises(WebappApiError):
        api.init()
    footer = '<a href="https://github.com/eclipse-csi/otterdog">OtterDog - v1.7.0.dev19+e2e.g9bdeb75</a>'
    responses.get(f"{BASE}/index", body=f"<html><footer>{footer}</footer></html>")
    assert api.deployed_version() == "1.7.0.dev19+e2e.g9bdeb75"
    responses.replace(responses.GET, f"{BASE}/index", body="<a>OtterDog dev</a>")
    assert api.deployed_version() is None
