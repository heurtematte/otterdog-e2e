"""DeliveryRelay (SPEC 13.3, GH-03): ordering, dedupe, installation filter before detail, accept, sliding lag window,
JWT rate guard, re-signed forwards to a loopback receiver, deliveries.jsonl."""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.testing.fakes import FAKE_ORG, FakeAppAuth
from otterdog_e2e.waiting import WaitTimeoutError
from otterdog_e2e.webapp.api import RemoteEndpointError
from otterdog_e2e.webhooks import payloads
from otterdog_e2e.webhooks.relay import DELIVERIES_FILE, DeliveryRelay, RelayedDelivery
from otterdog_e2e.webhooks.signing import sign_sha1, sign_sha256

SECRET = "e2e-relay-secret-0123456789abcdef"
INSTALLATION = 4242
NOW = datetime(2026, 10, 2, 12, 0, 0, tzinfo=UTC)


@dataclass
class Forwarded:
    """One request received from the relay."""

    headers: dict[str, str]
    body: bytes

    @property
    def payload(self) -> Any:
        """Decoded JSON body."""
        return json.loads(self.body)


@dataclass
class Receiver:
    """Loopback receiver answering 204 (or ``statuses[event]``) and recording requests."""

    url: str
    requests: list[Forwarded] = field(default_factory=list)
    statuses: dict[str, int] = field(default_factory=dict)


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    """Run the receiver on 127.0.0.1."""
    state = Receiver("")

    class Handler(http.server.BaseHTTPRequestHandler):
        """Record and answer."""

        def do_POST(self) -> None:
            """Handle one forwarded delivery."""
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            state.requests.append(Forwarded(dict(self.headers.items()), body))
            self.send_response(state.statuses.get(self.headers.get("X-GitHub-Event", ""), 204))
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            """Silence stderr logging."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    state.url = f"http://127.0.0.1:{server.server_address[1]}/github-webhook/receive"
    try:
        yield state
    finally:
        server.shutdown()
        server.server_close()


class FakeClock:
    """Datetime clock advanced by sleep(); hooks run on sleep."""

    def __init__(self, start: datetime = NOW) -> None:
        """Start at ``start``."""
        self.now = start
        self.hooks: list[Callable[[], None]] = []

    def __call__(self) -> datetime:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance and run the next hook."""
        self.now += timedelta(seconds=seconds)
        if self.hooks:
            self.hooks.pop(0)()


@pytest.fixture
def app() -> FakeAppAuth:
    """The fake App installed on the fake org."""
    return FakeAppAuth(org=FAKE_ORG, installation_id=INSTALLATION)


def make_relay(app: FakeAppAuth, url: str, **overrides: Any) -> DeliveryRelay:
    """A relay since NOW - 10 min for the fake installation."""
    options: dict[str, Any] = {"since": NOW - timedelta(minutes=10), "poll_interval": 0.01}
    options.update(overrides)
    return DeliveryRelay(app, forward_url=url, secret=SECRET, installation_id=INSTALLATION, org=FAKE_ORG, **options)


def pr_payload(number: int, action: str = "opened", *, org: str = FAKE_ORG, sha: str = "a" * 40) -> dict[str, Any]:
    """pull_request payload of the config repo."""
    pull = payloads.synthetic_pull_request(org, "cfg", number, head_ref=f"e2e/t3c7z8a5/{number}", head_sha=sha)
    return payloads.pull_request_payload(action, org=org, repo="cfg", pull_request=pull, installation_id=INSTALLATION)


def at(seconds: float) -> datetime:
    """NOW + seconds."""
    return NOW + timedelta(seconds=seconds)


def details_fetched(app: FakeAppAuth) -> list[int]:
    """Delivery ids whose detail was requested."""
    return [args[0] for name, args in app.calls if name == "get_delivery"]


def list_calls(app: FakeAppAuth) -> int:
    """Number of list_deliveries calls."""
    return sum(1 for name, _ in app.calls if name == "list_deliveries")


# --- forwarding ----------------------------------------------------------------------------------------------------
def test_forwards_in_delivered_order_with_valid_signatures(app: FakeAppAuth, receiver: Receiver) -> None:
    """Sorted by (delivered_at, id); re-signed over the forwarded bytes; GitHub headers kept."""
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-30), delivery_id=300, guid="g-300")
    app.add_delivery("pull_request", pr_payload(2), delivered_at=at(-20), delivery_id=500, guid="g-500")
    app.add_delivery("pull_request", pr_payload(3), delivered_at=at(-20), delivery_id=400, guid="g-400")
    relay = make_relay(app, receiver.url)
    new = relay.poll_once()
    assert [d.id for d in new] == [300, 400, 500] == [d.id for d in relay.delivered]
    assert [r.payload["number"] for r in receiver.requests] == [1, 3, 2]
    for request, delivery in zip(receiver.requests, new, strict=True):
        assert request.headers["X-Hub-Signature"] == sign_sha1(SECRET, request.body)
        assert request.headers["X-Hub-Signature-256"] == sign_sha256(SECRET, request.body)
        assert request.headers["X-GitHub-Event"] == "pull_request"
        assert request.headers["X-GitHub-Delivery"] == delivery.guid
        assert request.headers["Content-Type"] == "application/json"
        assert delivery.relay_status == 204 and delivery.forwarded_ok and delivery.error is None
        assert delivery.forwarded_at is not None and delivery.lag_seconds is not None
    assert hmac.compare_digest(
        receiver.requests[0].headers["X-Hub-Signature"],
        "sha1=" + hmac.new(SECRET.encode(), receiver.requests[0].body, hashlib.sha1).hexdigest(),
    )


def test_extracts_pr_comment_and_push_keys(app: FakeAppAuth, receiver: Receiver) -> None:
    """pull_number, head_sha, comment_id and sender are taken from the payload."""
    app.add_delivery("pull_request", pr_payload(7, "synchronize", sha="b" * 40), delivered_at=at(-3))
    comment = payloads.issue_comment_payload(
        org=FAKE_ORG, repo="cfg", number=7, body="/otterdog help", comment_id=99, sender="e2e-author"
    )
    app.add_delivery("issue_comment", comment, delivered_at=at(-2))
    push = payloads.push_payload(org=FAKE_ORG, repo="cfg", ref="refs/heads/main", after="c" * 40)
    app.add_delivery("push", push, delivered_at=at(-1))
    pr, note, pushed = make_relay(app, receiver.url).poll_once()
    assert (pr.pull_number, pr.head_sha, pr.action) == (7, "b" * 40, "synchronize")
    assert (note.pull_number, note.comment_id, note.sender) == (7, 99, "e2e-author")
    assert (pushed.pull_number, pushed.head_sha) == (None, "c" * 40)


def test_original_hook_headers_are_kept(app: FakeAppAuth, receiver: Receiver) -> None:
    """X-GitHub-Hook-ID / installation target headers of the original delivery are forwarded."""
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-5), delivery_id=1)
    original = app.get_delivery

    def with_headers(delivery_id: int) -> dict[str, Any]:
        """Detail with GitHub's request headers."""
        detail = original(delivery_id)
        detail["request"]["headers"] = {"x-github-hook-id": "77", "X-GitHub-Hook-Installation-Target-ID": "123456"}
        return detail

    app.get_delivery = with_headers  # type: ignore[method-assign]
    make_relay(app, receiver.url).poll_once()
    (request,) = receiver.requests
    assert request.headers["X-GitHub-Hook-ID"] == "77"
    assert request.headers["X-GitHub-Hook-Installation-Target-ID"] == "123456"
    assert request.headers["X-GitHub-Hook-Installation-Target-Type"] == "integration"


# --- filters -------------------------------------------------------------------------------------------------------
def test_installation_filter_runs_before_the_detail(app: FakeAppAuth, receiver: Receiver) -> None:
    """Deliveries of other installations (and App-level ones) are never fetched nor forwarded."""
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-3), installation_id=1, delivery_id=11)
    app.add_delivery("ping", payloads.ping_payload(), delivered_at=at(-2), installation_id=None, delivery_id=12)
    app.add_delivery("pull_request", pr_payload(2), delivered_at=at(-1), delivery_id=13)
    relay = make_relay(app, receiver.url)
    assert [d.id for d in relay.poll_once()] == [13]
    assert details_fetched(app) == [13]
    assert len(receiver.requests) == 1


def test_dedupe_by_id_and_guid(app: FakeAppAuth, receiver: Receiver) -> None:
    """A delivery is forwarded once; a redelivery (same guid) is skipped unless include_redeliveries."""
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-30), delivery_id=1, guid="same")
    relay = make_relay(app, receiver.url)
    assert len(relay.poll_once()) == 1
    assert relay.poll_once() == []
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-5), delivery_id=2, guid="same", redelivery=True)
    assert relay.poll_once() == []
    assert len(receiver.requests) == 1
    again = make_relay(app, receiver.url, include_redeliveries=True)
    assert [d.id for d in again.poll_once()] == [1, 2] and again.delivered[1].redelivery is True


def test_redeliveries_in_one_batch_are_forwarded_once(app: FakeAppAuth, receiver: Receiver) -> None:
    """Original and redelivery seen in the same poll: only the first (oldest) is forwarded."""
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-30), delivery_id=1, guid="g")
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-5), delivery_id=2, guid="g", redelivery=True)
    assert [d.id for d in make_relay(app, receiver.url).poll_once()] == [1]


def test_since_window_with_slack(app: FakeAppAuth, receiver: Receiver) -> None:
    """Deliveries before since - 5 s are ignored."""
    since = at(-60)
    app.add_delivery("pull_request", pr_payload(1), delivered_at=since - timedelta(seconds=10), delivery_id=1)
    app.add_delivery("pull_request", pr_payload(2), delivered_at=since - timedelta(seconds=3), delivery_id=2)
    app.add_delivery("pull_request", pr_payload(3), delivered_at=at(-1), delivery_id=3)
    assert [d.id for d in make_relay(app, receiver.url, since=since).poll_once()] == [2, 3]
    assert 1 not in details_fetched(app)


def test_accept_filter(app: FakeAppAuth, receiver: Receiver) -> None:
    """Default: same org or ping/installation events; custom accept decides alone; rejected ones are recorded."""
    app.add_delivery("pull_request", pr_payload(1, org="another-org"), delivered_at=at(-3), delivery_id=1)
    app.add_delivery("ping", payloads.ping_payload(installation_id=INSTALLATION), delivered_at=at(-2), delivery_id=2)
    app.add_delivery("pull_request", pr_payload(3), delivered_at=at(-1), delivery_id=3)
    relay = make_relay(app, receiver.url)
    rejected, ping, accepted = relay.poll_once()
    assert rejected.error == "rejected by the accept filter" and rejected.forwarded_at is None
    assert ping.relay_status == 204 and accepted.relay_status == 204
    assert [r.headers["X-GitHub-Event"] for r in receiver.requests] == ["ping", "pull_request"]
    picky = make_relay(app, receiver.url, accept=lambda payload: payload.get("number") == 3)
    assert [d.id for d in picky.poll_once() if d.forwarded_at] == [3]


def test_missing_payload_is_recorded_not_forwarded(app: FakeAppAuth, receiver: Receiver) -> None:
    """request.payload can be null in the delivery log."""
    app.add_delivery("pull_request", None, delivered_at=at(-1), delivery_id=1, action="opened")
    (delivery,) = make_relay(app, receiver.url).poll_once()
    assert delivery.error == "payload unavailable in the delivery log" and receiver.requests == []


# --- paging budget -------------------------------------------------------------------------------------------------
def test_paging_is_bounded_by_max_pages_and_the_lag_window(app: FakeAppAuth, receiver: Receiver) -> None:
    """First poll: at most max_pages_per_poll pages; later polls stop after a page older than high_water - lag."""
    for index in range(350):
        app.add_delivery(
            "push", {"organization": {"login": FAKE_ORG}}, delivered_at=at(-400 + index), delivery_id=index
        )
    relay = make_relay(app, receiver.url, lag_window=30, max_pages_per_poll=3)
    first = relay.poll_once()
    assert list_calls(app) == 3 and len(first) == 300 and first[0].id == 50 and first[-1].id == 349
    assert relay.poll_once() == [] and list_calls(app) == 5  # page 1 (recent), page 2 entirely older -> stop
    app.add_delivery("push", {"organization": {"login": FAKE_ORG}}, delivered_at=at(-60), delivery_id=1000)  # late
    assert [d.id for d in relay.poll_once()] == [1000]


def test_foreign_traffic_also_bounds_paging(app: FakeAppAuth, receiver: Receiver) -> None:
    """Deliveries of other installations advance the paging limit (never forwarded, never fetched)."""
    for index in range(250):
        app.add_delivery("push", {}, delivered_at=at(-300 + index), installation_id=1, delivery_id=index)
    relay = make_relay(app, receiver.url, lag_window=30)
    assert relay.poll_once() == [] and list_calls(app) == 3
    assert relay.poll_once() == [] and list_calls(app) == 5
    assert details_fetched(app) == []


# --- JWT rate guard ------------------------------------------------------------------------------------------------
def test_rate_guard_pauses_polls(app: FakeAppAuth, receiver: Receiver) -> None:
    """Below min_rate_remaining no list call is made; after the backoff one probe poll runs."""
    clock = FakeClock()
    app.rate_remaining = 10
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-1), delivery_id=1)
    relay = make_relay(app, receiver.url, clock=clock, min_rate_remaining=300)
    assert relay.poll_once() == [] and list_calls(app) == 0
    clock.sleep(30)
    assert relay.poll_once() == [] and list_calls(app) == 0
    clock.sleep(31)
    assert [d.id for d in relay.poll_once()] == [1] and list_calls(app) == 1  # probe
    assert relay.poll_once() == [] and list_calls(app) == 1  # still low: paused again
    app.rate_remaining = 4000
    clock.sleep(61)
    relay.poll_once()
    relay.poll_once()
    assert list_calls(app) == 3


def test_rate_guard_uses_the_reset_time_when_known(app: FakeAppAuth, receiver: Receiver) -> None:
    """AppAuth.rate_reset (X-RateLimit-Reset of the last JWT response) pauses the relay until that time."""
    clock = FakeClock()
    app.rate_remaining = 1
    app.rate_reset = NOW + timedelta(seconds=300)
    relay = make_relay(app, receiver.url, clock=clock)
    relay.poll_once()
    clock.sleep(299)
    relay.poll_once()
    assert list_calls(app) == 0
    clock.sleep(2)
    relay.poll_once()
    assert list_calls(app) == 1


# --- failures ------------------------------------------------------------------------------------------------------
class FlakyApp(FakeAppAuth):
    """FakeAppAuth whose get_delivery fails ``failures[id]`` times."""

    def __init__(self, failures: dict[int, int]) -> None:
        """Remember how often each id fails."""
        super().__init__(org=FAKE_ORG, installation_id=INSTALLATION)
        self.failures = dict(failures)

    def get_delivery(self, delivery_id: int) -> dict[str, Any]:
        """Fail, then answer."""
        if self.failures.get(delivery_id, 0) > 0:
            self.failures[delivery_id] -= 1
            raise RuntimeError(f"GET /app/hook/deliveries/{delivery_id} -> 502")
        return super().get_delivery(delivery_id)


def test_detail_failures_keep_the_forward_order(receiver: Receiver) -> None:
    """A failing detail blocks newer deliveries until it succeeds (order preserved)."""
    app = FlakyApp({1: 2})
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-2), delivery_id=1)
    app.add_delivery("pull_request", pr_payload(2), delivered_at=at(-1), delivery_id=2)
    relay = make_relay(app, receiver.url)
    assert relay.poll_once() == [] and relay.poll_once() == []
    assert [d.id for d in relay.poll_once()] == [1, 2]
    assert [r.payload["number"] for r in receiver.requests] == [1, 2]


def test_permanent_detail_failure_is_given_up(receiver: Receiver) -> None:
    """After MAX_DETAIL_ATTEMPTS polls the delivery is recorded with an error and the rest proceeds."""
    app = FlakyApp({1: 99})
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-2), delivery_id=1)
    app.add_delivery("pull_request", pr_payload(2), delivered_at=at(-1), delivery_id=2)
    relay = make_relay(app, receiver.url)
    relay.poll_once()
    relay.poll_once()
    given_up, forwarded = relay.poll_once()
    assert given_up.error == "delivery detail unavailable" and given_up.forwarded_at is None
    assert forwarded.relay_status == 204


def test_forward_errors_are_recorded(app: FakeAppAuth, receiver: Receiver) -> None:
    """Webapp 500s and connection errors end up on the delivery (never raised)."""
    receiver.statuses["pull_request"] = 500
    app.add_delivery("pull_request", pr_payload(1), delivered_at=at(-1), delivery_id=1)
    (failed,) = make_relay(app, receiver.url).poll_once()
    assert failed.relay_status == 500 and failed.error == "webapp answered HTTP 500" and not failed.forwarded_ok
    (unreachable,) = make_relay(app, "http://127.0.0.1:9/github-webhook/receive").poll_once()
    assert unreachable.relay_status is None and unreachable.forwarded_at is None
    assert unreachable.error is not None and unreachable.error.startswith("forward failed")


def test_forward_url_must_be_loopback(app: FakeAppAuth) -> None:
    """Remote targets need allow_remote (the error is a ValueError)."""
    with pytest.raises(ValueError) as info:
        make_relay(app, "https://webhooks.example.org/receive")
    assert isinstance(info.value, RemoteEndpointError)
    make_relay(app, "https://webhooks.example.org/receive", allow_remote=True)


# --- artifacts -----------------------------------------------------------------------------------------------------
def test_deliveries_jsonl_without_payloads(app: FakeAppAuth, receiver: Receiver, tmp_path: Path) -> None:
    """One redacted record per delivery with timings and statuses; payloads only with keep_payloads."""
    app.add_delivery("pull_request", pr_payload(5), delivered_at=at(-4), delivery_id=1, guid="guid-1")
    make_relay(app, receiver.url, artifacts_dir=tmp_path).poll_once()
    (line,) = (tmp_path / DELIVERIES_FILE).read_text().splitlines()
    record = json.loads(line)
    assert record["id"] == 1 and record["guid"] == "guid-1" and record["event"] == "pull_request"
    assert record["action"] == "opened" and record["pull_number"] == 5 and record["relay_status"] == 204
    assert record["delivered_at"] == at(-4).isoformat() and record["forwarded_at"] and record["lag_seconds"] is not None
    assert "seen_lag_seconds" in record and "payload" not in record


def test_deliveries_jsonl_payloads_are_redacted(app: FakeAppAuth, receiver: Receiver, tmp_path: Path) -> None:
    """keep_payloads stores the payload, passed through REDACTOR."""
    leaked = "ghp_" + "L3akedT0ken" * 4
    REDACTOR.add(leaked)
    payload = pr_payload(6)
    payload["pull_request"]["body"] = f"token {leaked} and {SECRET}"
    app.add_delivery("pull_request", payload, delivered_at=at(-1), delivery_id=1)
    make_relay(app, receiver.url, artifacts_dir=tmp_path, keep_payloads=True).poll_once()
    text = (tmp_path / DELIVERIES_FILE).read_text()
    assert leaked not in text and SECRET not in text and json.loads(text)["payload"]["number"] == 6


# --- waiting -------------------------------------------------------------------------------------------------------
def test_wait_for_polls_without_a_thread(app: FakeAppAuth, receiver: Receiver) -> None:
    """Without the background thread wait_for polls itself, sleeping poll_interval between polls."""
    clock = FakeClock()
    relay = make_relay(app, receiver.url, clock=clock, sleep=clock.sleep, poll_interval=5)
    clock.hooks.append(lambda: None)
    clock.hooks.append(lambda: app.add_delivery("push", {"organization": {"login": FAKE_ORG}}, delivered_at=clock.now))
    found = relay.wait_for(lambda d: d.event == "push", timeout=60)
    assert found.event == "push" and clock.now == NOW + timedelta(seconds=10)
    with pytest.raises(WaitTimeoutError):
        relay.wait_for(lambda d: d.event == "never", timeout=20)


def test_background_thread_start_stop(app: FakeAppAuth, receiver: Receiver) -> None:
    """start() polls in a daemon thread; wait_for wakes up on new deliveries; stop() is idempotent."""
    relay = make_relay(app, receiver.url, since=datetime.now(UTC) - timedelta(minutes=1))
    with relay:
        assert relay.running()
        app.add_delivery("pull_request", pr_payload(9))
        found = relay.wait_for(lambda d: d.pull_number == 9, timeout=10)
        assert isinstance(found, RelayedDelivery) and found.relay_status == 204
        relay.start()  # already running: no second thread
    assert not relay.running()
    relay.stop()
    assert relay.polls >= 1


def test_poll_errors_do_not_kill_the_thread(receiver: Receiver) -> None:
    """A failing list call is logged and polling continues."""

    class BrokenApp(FakeAppAuth):
        """list_deliveries fails twice."""

        def __init__(self) -> None:
            """Fail counter."""
            super().__init__(org=FAKE_ORG, installation_id=INSTALLATION)
            self.broken = 2

        def list_deliveries(self, *, per_page: int = 100, cursor: str | None = None) -> Any:
            """Fail, then list."""
            if self.broken:
                self.broken -= 1
                raise RuntimeError("502 Bad Gateway")
            return super().list_deliveries(per_page=per_page, cursor=cursor)

    app = BrokenApp()
    app.add_delivery("pull_request", pr_payload(4))
    relay = make_relay(app, receiver.url, since=datetime.now(UTC) - timedelta(minutes=1))
    relay.start()
    try:
        assert relay.wait_for(lambda d: d.pull_number == 4, timeout=10).relay_status == 204
        assert relay.poll_errors == 2
    finally:
        relay.stop()


# --- workflow events, wait_event and replay ------------------------------------------------------------------------
def workflow_job(run_id: int, *, repo: str = "e2e-t3c7z8a5-wf", action: str = "queued") -> dict[str, Any]:
    """workflow_job payload of a run repository."""
    return payloads.workflow_job_payload(
        action, org=FAKE_ORG, repo=repo, run_id=run_id, labels=["macos-latest-large"], installation_id=INSTALLATION
    )


def test_workflow_deliveries_carry_repository_and_run(app: FakeAppAuth, receiver: Receiver, tmp_path: Path) -> None:
    """repository.name and the workflow run id (workflow_job.run_id, workflow_run.id) are recorded."""
    app.add_delivery("workflow_job", workflow_job(77), delivered_at=at(-3), delivery_id=1)
    run = payloads.workflow_run_payload(org=FAKE_ORG, repo="e2e-t3c7z8a5-wf", run_id=78, installation_id=INSTALLATION)
    app.add_delivery("workflow_run", run, delivered_at=at(-2), delivery_id=2)
    app.add_delivery("pull_request", pr_payload(3), delivered_at=at(-1), delivery_id=3)
    job, completed, pull = make_relay(app, receiver.url, artifacts_dir=tmp_path).poll_once()
    assert (job.repository_name, job.run_id, job.action) == ("e2e-t3c7z8a5-wf", 77, "queued")
    assert (completed.repository_name, completed.run_id) == ("e2e-t3c7z8a5-wf", 78)
    assert (pull.repository_name, pull.run_id) == ("cfg", None)
    records = [json.loads(line) for line in (tmp_path / DELIVERIES_FILE).read_text().splitlines()]
    assert [(r["repository_name"], r["run_id"]) for r in records] == [
        ("e2e-t3c7z8a5-wf", 77),
        ("e2e-t3c7z8a5-wf", 78),
        ("cfg", None),
    ]


def test_wait_event_filters(app: FakeAppAuth, receiver: Receiver) -> None:
    """wait_event matches event, action, repository, run id and the delivery time (with the since slack)."""
    clock = FakeClock()
    relay = make_relay(app, receiver.url, clock=clock, sleep=clock.sleep, poll_interval=5)
    app.add_delivery("workflow_job", workflow_job(1), delivered_at=at(-60), delivery_id=1)
    app.add_delivery("workflow_job", workflow_job(2, repo="e2e-t3c7z8a5-other"), delivered_at=at(-2), delivery_id=2)
    app.add_delivery("workflow_job", workflow_job(3, action="completed"), delivered_at=at(-1), delivery_id=3)
    clock.hooks.append(lambda: app.add_delivery("workflow_job", workflow_job(4), delivered_at=clock.now, delivery_id=4))
    found = relay.wait_event(
        "workflow_job", action="queued", repository_name="e2e-t3c7z8a5-wf", after=at(-10), timeout=30
    )
    assert found.id == 4 and found.run_id == 4
    assert relay.wait_event("workflow_job", run_id=1, timeout=1).id == 1
    with pytest.raises(WaitTimeoutError):
        relay.wait_event("workflow_job", run_id=1, after=at(-10), timeout=5)


def test_replay_forwards_the_same_delivery_again(app: FakeAppAuth, receiver: Receiver, tmp_path: Path) -> None:
    """replay() fetches the delivery again and forwards it with the same GUID and payload (redelivery=True)."""
    app.add_delivery("pull_request", pr_payload(5), delivered_at=at(-5), delivery_id=9, guid="g-9")
    relay = make_relay(app, receiver.url, artifacts_dir=tmp_path)
    (first,) = relay.poll_once()
    again = relay.replay(9)
    assert again.redelivery and again.guid == first.guid == "g-9" and again.relay_status == 204
    assert (again.pull_number, again.event, again.action) == (5, "pull_request", "opened")
    assert [r.headers["X-GitHub-Delivery"] for r in receiver.requests] == ["g-9", "g-9"]
    assert receiver.requests[0].body == receiver.requests[1].body
    assert receiver.requests[1].headers["X-Hub-Signature"] == sign_sha1(SECRET, receiver.requests[1].body)
    assert [d.redelivery for d in relay.delivered] == [False, True]
    assert len((tmp_path / DELIVERIES_FILE).read_text().splitlines()) == 2
    assert relay.poll_once() == []  # the replay does not make the original new again


def test_replay_without_payload_is_recorded_not_forwarded(app: FakeAppAuth, receiver: Receiver) -> None:
    """A delivery whose payload the log no longer has is recorded with an error and not forwarded."""
    app.add_delivery("pull_request", None, action="opened", delivered_at=at(-5), delivery_id=10)
    relay = make_relay(app, receiver.url)
    replayed = relay.replay(10)
    assert replayed.error == "payload unavailable in the delivery log" and replayed.relay_status is None
    assert receiver.requests == [] and relay.delivered == [replayed]
