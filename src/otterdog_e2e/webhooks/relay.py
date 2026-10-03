"""Pull relay: forwards real App webhook deliveries from GitHub's delivery log to a loopback webapp (SPEC 13.3).

No inbound exposure: the App's hook URL is a sink; the relay polls GET /app/hook/deliveries with the App JWT, keeps
only deliveries of our installation and org, re-signs them with the webhook secret and POSTs them to ``forward_url``.

Budget (GH-03): the list API has no time filter, so each poll pages newest-first only down to
``stop_at = max(since - 5 s, high_water - lag_window)`` (high_water = newest delivered_at already processed) and at most
``max_pages_per_poll`` pages; list items are filtered on installation_id BEFORE their detail is fetched; the poll is
skipped while the App's JWT budget (AppAuth.rate_remaining) is below ``min_rate_remaining`` - the webapp under test
mints its installation tokens with the same App - until AppAuth.rate_reset (X-RateLimit-Reset), else for
RATE_LIMIT_BACKOFF seconds; one probe poll then refreshes the budget.

Besides the PR keys (pull number, head sha, comment id) each delivery records its repository name and the workflow run
id of workflow_job / workflow_run events, for ``wait_event``; ``replay(delivery_id)`` fetches a delivery from the log
again and forwards it once more with the same GUID (a GitHub redelivery, as the webapp sees it).
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import TracebackType
from typing import TYPE_CHECKING, Any, Self

import requests

from otterdog_e2e import waiting
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.webapp.api import as_utc, local_session, parse_timestamp, require_loopback_url
from otterdog_e2e.webhooks.signing import serialize_payload, webhook_headers

if TYPE_CHECKING:
    from otterdog_e2e.github.app import AppAuth

_logger = logging.getLogger(__name__)

ALWAYS_ACCEPTED_EVENTS = frozenset({"ping", "installation", "installation_repositories"})
SINCE_SLACK_SECONDS = 5.0
PER_PAGE = 100
FORWARD_TIMEOUT = 30.0
RATE_LIMIT_BACKOFF = 60.0  # pause when the App budget is low and the last JWT response had no X-RateLimit-Reset
MAX_DETAIL_ATTEMPTS = 3  # a delivery whose detail cannot be fetched is given up after this many polls
DELIVERIES_FILE = "deliveries.jsonl"
_FORWARDED_HEADERS = {  # original GitHub headers kept on the forwarded request
    "hook_id": "X-GitHub-Hook-ID",
    "target_type": "X-GitHub-Hook-Installation-Target-Type",
    "target_id": "X-GitHub-Hook-Installation-Target-ID",
}


@dataclass
class RelayedDelivery:
    """One delivery seen (and possibly forwarded) by the relay."""

    id: int
    guid: str
    event: str
    action: str | None
    installation_id: int | None
    repository_id: int | None
    pull_number: int | None
    delivered_at: datetime
    seen_at: datetime
    forwarded_at: datetime | None
    github_status_code: int | None
    relay_status: int | None
    error: str | None = None
    redelivery: bool = False
    head_sha: str | None = None  # pull_request.head.sha, or ``after`` of a push
    comment_id: int | None = None  # comment.id of issue_comment events
    sender: str | None = None  # sender.login
    repository_name: str | None = None  # repository.name
    run_id: int | None = None  # workflow_job.run_id / workflow_run.id

    @property
    def lag_seconds(self) -> float | None:
        """Seconds between GitHub's delivery and our forward (None when not forwarded)."""
        if self.forwarded_at is None:
            return None
        return (self.forwarded_at - self.delivered_at).total_seconds()

    @property
    def forwarded_ok(self) -> bool:
        """True when the webapp answered the forwarded delivery with a 2xx status."""
        return self.relay_status is not None and 200 <= self.relay_status < 300

    def to_record(self) -> dict[str, Any]:
        """JSON-serializable record of deliveries.jsonl (no payload)."""
        seen_lag = (self.seen_at - self.delivered_at).total_seconds()
        return {
            "id": self.id,
            "guid": self.guid,
            "event": self.event,
            "action": self.action,
            "installation_id": self.installation_id,
            "repository_id": self.repository_id,
            "pull_number": self.pull_number,
            "head_sha": self.head_sha,
            "comment_id": self.comment_id,
            "sender": self.sender,
            "repository_name": self.repository_name,
            "run_id": self.run_id,
            "redelivery": self.redelivery,
            "delivered_at": self.delivered_at.isoformat(),
            "seen_at": self.seen_at.isoformat(),
            "forwarded_at": self.forwarded_at.isoformat() if self.forwarded_at else None,
            "seen_lag_seconds": round(seen_lag, 3),
            "lag_seconds": None if self.lag_seconds is None else round(self.lag_seconds, 3),
            "github_status_code": self.github_status_code,
            "relay_status": self.relay_status,
            "error": self.error,
        }


def _get(data: Any, *keys: str) -> Any:
    """Nested lookup tolerant to missing keys and non-dict values."""
    for key in keys:
        if not isinstance(data, Mapping):
            return None
        data = data.get(key)
    return data


def _int_or_none(value: Any) -> int | None:
    """``value`` as an int (None for None, bools and non-numbers)."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def payload_pull_number(payload: Any) -> int | None:
    """Pull request (or issue) number carried by a payload."""
    for keys in (("pull_request", "number"), ("issue", "number"), ("number",)):
        number = _int_or_none(_get(payload, *keys))
        if number is not None:
            return number
    return None


def payload_head_sha(payload: Any) -> str | None:
    """pull_request.head.sha, else the ``after`` sha of a push."""
    sha = _get(payload, "pull_request", "head", "sha") or _get(payload, "after")
    return sha if isinstance(sha, str) else None


def payload_run_id(payload: Any) -> int | None:
    """Workflow run id of a workflow_job (workflow_job.run_id) or workflow_run (workflow_run.id) payload."""
    run_id = _int_or_none(_get(payload, "workflow_job", "run_id"))
    return run_id if run_id is not None else _int_or_none(_get(payload, "workflow_run", "id"))


def payload_repository_name(payload: Any) -> str | None:
    """repository.name of a payload."""
    name = _get(payload, "repository", "name")
    return name if isinstance(name, str) else None


def _header(headers: Mapping[str, Any], name: str) -> str | None:
    """Case-insensitive header lookup in a delivery's request headers."""
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted and value is not None:
            return str(value)
    return None


def _utc_now() -> datetime:
    """Current aware UTC time."""
    return datetime.now(UTC)


def _reset_time(app: AppAuth) -> datetime | None:
    """AppAuth.rate_reset (X-RateLimit-Reset of the last JWT response) as an aware UTC datetime, None when unknown."""
    reset = app.rate_reset
    return as_utc(reset) if isinstance(reset, datetime) else None


class DeliveryRelay:
    """Polls the App delivery log and forwards accepted deliveries in (delivered_at, id) order."""

    def __init__(
        self,
        app: AppAuth,
        *,
        forward_url: str,
        secret: str,
        since: datetime,
        installation_id: int,
        org: str,
        accept: Callable[[dict], bool] | None = None,
        poll_interval: float = 5.0,
        lag_window: float = 600.0,
        max_pages_per_poll: int = 3,
        min_rate_remaining: int = 300,
        include_redeliveries: bool = False,
        artifacts_dir: Path | None = None,
        keep_payloads: bool = False,
        allow_remote: bool = False,
        session: requests.Session | None = None,
        clock: Callable[[], datetime] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Configure the relay; forward_url must be loopback unless allow_remote (ValueError otherwise)."""
        require_loopback_url(forward_url, allow_remote=allow_remote, what="relay forward URL")
        self.app = app
        self.forward_url = forward_url
        self.secret = secret
        self.since = as_utc(since)
        self.installation_id = int(installation_id)
        self.org = org
        self.accept = accept
        self.poll_interval = poll_interval
        self.lag_window = lag_window
        self.max_pages_per_poll = max(1, max_pages_per_poll)
        self.min_rate_remaining = min_rate_remaining
        self.include_redeliveries = include_redeliveries
        self.artifacts_dir = artifacts_dir
        self.keep_payloads = keep_payloads
        self.allow_remote = allow_remote
        self.session = local_session(session)
        self.clock = clock or _utc_now
        self.sleep = sleep
        self.forward_timeout = FORWARD_TIMEOUT
        self.deliveries_file = artifacts_dir / DELIVERIES_FILE if artifacts_dir is not None else None
        self.polls = 0
        self.poll_errors = 0
        REDACTOR.add(secret)
        self._changed = threading.Condition(threading.RLock())
        self._poll_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._delivered: list[RelayedDelivery] = []
        self._seen_ids: set[int] = set()
        self._seen_guids: set[str] = set()
        self._detail_failures: dict[int, int] = {}
        self._high_water: datetime | None = None  # newest delivered_at processed for our installation
        self._listed_high_water: datetime | None = None  # newest delivered_at listed (any installation)
        self._blocked_until: datetime | None = None

    # --- polling --------------------------------------------------------------------------------------------------
    def poll_once(self) -> list[RelayedDelivery]:
        """One poll: page newest-first down to max(since - 5 s, high_water - lag_window), filter on installation_id
        before fetching details, dedupe, accept(payload), forward sorted by (delivered_at, id); returns the new ones."""
        with self._poll_lock:
            if self._rate_limited():
                return []
            self.polls += 1
            new: list[RelayedDelivery] = []
            for item in self._candidates(self._list_recent()):
                detail = self._detail(item)
                if detail is None:
                    break  # keep the forward order: retry this delivery (and the newer ones) at the next poll
                new.append(self._handle(item, detail))
            return new

    def _floor(self) -> datetime:
        """Oldest delivered_at ever forwarded: since - 5 s."""
        return self.since - timedelta(seconds=SINCE_SLACK_SECONDS)

    def _stop_at(self) -> datetime:
        """Paging limit of one poll: max(since - 5 s, high_water - lag_window).

        high_water is the newest delivered_at processed, or listed for any installation of the App: deliveries of
        other installations then bound the paging too (the delivery log is shared by every installation).
        """
        marks = [mark for mark in (self._high_water, self._listed_high_water) if mark is not None]
        if not marks:
            return self._floor()
        return max(self._floor(), max(marks) - timedelta(seconds=self.lag_window))

    def _list_recent(self) -> list[dict[str, Any]]:
        """List pages newest-first until a page is entirely older than stop_at, the end, or max_pages_per_poll."""
        stop_at = self._stop_at()
        items: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(self.max_pages_per_poll):
            page, cursor = self.app.list_deliveries(per_page=PER_PAGE, cursor=cursor)
            items.extend(page)
            if not page or cursor is None or all(self._older(item, stop_at) for item in page):
                break
        listed = [stamp for stamp in (parse_timestamp(item.get("delivered_at")) for item in items) if stamp]
        if listed and (self._listed_high_water is None or max(listed) > self._listed_high_water):
            self._listed_high_water = max(listed)
        return items

    @staticmethod
    def _older(item: Mapping[str, Any], limit: datetime) -> bool:
        """True when the list item was delivered before ``limit`` (unparsable timestamps count as old)."""
        delivered_at = parse_timestamp(item.get("delivered_at"))
        return delivered_at is None or delivered_at < limit

    def _candidates(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """New list items of our installation since ``since`` (deduped), sorted by (delivered_at, id)."""
        floor = self._floor()
        fresh: dict[int, dict[str, Any]] = {}
        for item in items:
            delivery_id = _int_or_none(item.get("id"))
            if delivery_id is None or delivery_id in self._seen_ids or delivery_id in fresh:
                continue
            if _int_or_none(item.get("installation_id")) != self.installation_id:
                continue  # filtered BEFORE fetching the detail
            if self._older(item, floor):
                continue
            if not self.include_redeliveries and item.get("guid") in self._seen_guids:
                continue
            fresh[delivery_id] = item
        ordered = sorted(fresh.values(), key=lambda it: (parse_timestamp(it["delivered_at"]), int(it["id"])))
        if self.include_redeliveries:
            return ordered
        unique: list[dict[str, Any]] = []
        guids: set[str] = set()
        for item in ordered:
            if item.get("guid") not in guids:
                guids.add(str(item.get("guid")))
                unique.append(item)
        return unique

    def _detail(self, item: Mapping[str, Any]) -> dict[str, Any] | None:
        """GET the delivery detail; None to retry later (an empty detail after MAX_DETAIL_ATTEMPTS failures)."""
        delivery_id = int(item["id"])
        try:
            return dict(self.app.get_delivery(delivery_id))
        except (RuntimeError, OSError, KeyError, ValueError) as exc:  # GitHubError, network: transient
            failures = self._detail_failures.get(delivery_id, 0) + 1
            self._detail_failures[delivery_id] = failures
            _logger.warning("relay: delivery %s detail failed (%d): %s", delivery_id, failures, REDACTOR(str(exc)))
            if failures >= MAX_DETAIL_ATTEMPTS:
                return {"request": {"headers": None, "payload": None}, "_error": "delivery detail unavailable"}
            return None

    def _rate_limited(self) -> bool:
        """JWT rate guard: True (skip this poll) while the App budget is below min_rate_remaining."""
        now = self.clock()
        if self._blocked_until is not None:
            if now < self._blocked_until:
                return True
            self._blocked_until = None
            return False  # one probe poll refreshes the budget seen by AppAuth
        remaining = self.app.rate_remaining
        if remaining is None or remaining >= self.min_rate_remaining:
            return False
        reset = _reset_time(self.app)
        self._blocked_until = max(reset or now + timedelta(seconds=RATE_LIMIT_BACKOFF), now + timedelta(seconds=1))
        _logger.warning(
            "relay paused until %s: App JWT budget %s < %s", self._blocked_until, remaining, self.min_rate_remaining
        )
        return True

    # --- one delivery ---------------------------------------------------------------------------------------------
    def _handle(self, item: Mapping[str, Any], detail: Mapping[str, Any]) -> RelayedDelivery:
        """Build the RelayedDelivery, forward it when its payload exists and is accepted, record it."""
        request = detail.get("request") or {}
        payload = request.get("payload")
        delivery = RelayedDelivery(
            id=int(item["id"]),
            guid=str(item.get("guid") or ""),
            event=str(item.get("event") or ""),
            action=item.get("action"),
            installation_id=_int_or_none(item.get("installation_id")),
            repository_id=_int_or_none(item.get("repository_id")),
            pull_number=payload_pull_number(payload),
            delivered_at=parse_timestamp(item.get("delivered_at")) or self.clock(),
            seen_at=self.clock(),
            forwarded_at=None,
            github_status_code=_int_or_none(item.get("status_code")),
            relay_status=None,
            redelivery=bool(item.get("redelivery")),
            head_sha=payload_head_sha(payload),
            comment_id=_int_or_none(_get(payload, "comment", "id")),
            sender=_get(payload, "sender", "login"),
            repository_name=payload_repository_name(payload),
            run_id=payload_run_id(payload),
        )
        if not isinstance(payload, dict):
            delivery.error = str(detail.get("_error") or "payload unavailable in the delivery log")
        elif not self._accepted(delivery.event, payload):
            delivery.error = "rejected by the accept filter"
        else:
            self._forward(delivery, payload, request.get("headers") or {})
        self._remember(delivery, payload)
        return delivery

    def _accepted(self, event: str, payload: dict[str, Any]) -> bool:
        """accept(payload), default: organization.login == org or an ALWAYS_ACCEPTED_EVENTS event."""
        if self.accept is not None:
            return bool(self.accept(payload))
        return default_accept(payload, org=self.org, event=event)

    def _forward(self, delivery: RelayedDelivery, payload: dict[str, Any], original: Mapping[str, Any]) -> None:
        """Re-serialize, re-sign and POST the payload to forward_url; records status or error on ``delivery``."""
        body = serialize_payload(payload)
        extra = {key: _header(original, name) for key, name in _FORWARDED_HEADERS.items()}
        headers = webhook_headers(
            delivery.event,
            body,
            self.secret,
            delivery_id=delivery.guid or None,
            hook_id=extra["hook_id"],
            target_type=extra["target_type"] or "integration",
            target_id=extra["target_id"],  # the App id for App hooks; omitted when GitHub did not record it
        )
        try:
            response = self.session.post(
                self.forward_url, data=body, headers=headers, timeout=self.forward_timeout, allow_redirects=False
            )
        except requests.RequestException as exc:
            delivery.error = REDACTOR(f"forward failed: {exc}")
            return
        delivery.forwarded_at = self.clock()
        delivery.relay_status = response.status_code
        if not delivery.forwarded_ok:
            delivery.error = f"webapp answered HTTP {response.status_code}"

    def _remember(self, delivery: RelayedDelivery, payload: Any) -> None:
        """Mark the delivery seen, advance the high-water mark, append deliveries.jsonl, wake waiters."""
        with self._changed:
            self._seen_ids.add(delivery.id)
            self._seen_guids.add(delivery.guid)
            self._detail_failures.pop(delivery.id, None)
            if self._high_water is None or delivery.delivered_at > self._high_water:
                self._high_water = delivery.delivered_at
            self._delivered.append(delivery)
            self._write_record(delivery, payload)
            self._changed.notify_all()
        _logger.info(
            "relay: %s %s/%s pr=%s delivered %s -> %s%s",
            delivery.guid,
            delivery.event,
            delivery.action,
            delivery.pull_number,
            delivery.delivered_at.isoformat(),
            delivery.relay_status,
            f" ({delivery.error})" if delivery.error else "",
        )

    def _write_record(self, delivery: RelayedDelivery, payload: Any) -> None:
        """Append one redacted JSON line to deliveries.jsonl (payload only with keep_payloads)."""
        if self.deliveries_file is None:
            return
        record = delivery.to_record()
        if self.keep_payloads:
            record["payload"] = payload
        self.deliveries_file.parent.mkdir(parents=True, exist_ok=True)
        with self.deliveries_file.open("a", encoding="utf-8") as handle:
            handle.write(REDACTOR(json.dumps(record, sort_keys=True, default=str)) + "\n")

    # --- background thread and waits ------------------------------------------------------------------------------
    def start(self) -> None:
        """Poll in a daemon thread every poll_interval seconds."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run, name=f"otterdog-e2e-relay-{self.installation_id}", daemon=True
        )
        self._thread.start()

    def _run(self) -> None:
        """Thread body: poll until stopped; errors are logged (redacted) and polling continues."""
        while not self._stop_event.is_set():
            try:
                self.poll_once()
            except Exception as exc:  # noqa: BLE001 - the session's relay must survive any poll failure
                self.poll_errors += 1
                _logger.warning("relay poll failed: %s", REDACTOR(f"{type(exc).__name__}: {exc}"))
            self._stop_event.wait(self.poll_interval)

    def running(self) -> bool:
        """True while the polling thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    def stop(self, timeout: float = 10) -> None:
        """Stop the polling thread and flush deliveries.jsonl (idempotent)."""
        self._stop_event.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout)
            if thread.is_alive():
                _logger.warning("relay thread did not stop within %s s", timeout)
        with self._changed:
            self._changed.notify_all()

    @property
    def delivered(self) -> list[RelayedDelivery]:
        """Every delivery seen so far, in forward order."""
        with self._changed:
            return list(self._delivered)

    def _find(self, predicate: Callable[[RelayedDelivery], bool]) -> RelayedDelivery | None:
        """First seen delivery matching ``predicate``."""
        with self._changed:
            return next((delivery for delivery in self._delivered if predicate(delivery)), None)

    def wait_for(self, predicate: Callable[[RelayedDelivery], bool], *, timeout: float = 300) -> RelayedDelivery:
        """First delivery matching ``predicate`` (waiting.WaitTimeoutError after ``timeout``)."""
        deadline = waiting.Deadline(timeout, clock=lambda: self.clock().timestamp())
        attempts = 0
        while True:
            attempts += 1
            match = self._find(predicate)
            if match is None and not self.running():
                self.poll_once()
                match = self._find(predicate)
            if match is not None:
                return match
            if deadline.expired():
                raise waiting.WaitTimeoutError("relayed delivery matching the predicate", timeout, attempts=attempts)
            pause = min(self.poll_interval, max(deadline.remaining(), 0.0))
            if self.running():
                with self._changed:
                    self._changed.wait(pause)
            else:
                self.sleep(pause)

    def wait_event(
        self,
        event: str,
        *,
        action: str | None = None,
        repository_name: str | None = None,
        run_id: int | None = None,
        after: datetime | None = None,
        timeout: float = 300,
    ) -> RelayedDelivery:
        """First delivery of ``event`` (and action, repository, workflow run id when given) delivered at or after
        ``after`` minus SINCE_SLACK_SECONDS (waiting.WaitTimeoutError after ``timeout``)."""
        floor = as_utc(after) - timedelta(seconds=SINCE_SLACK_SECONDS) if after is not None else None

        def matches(delivery: RelayedDelivery) -> bool:
            """The wanted event of the wanted repository / run."""
            return (
                delivery.event == event
                and (action is None or delivery.action == action)
                and (repository_name is None or delivery.repository_name == repository_name)
                and (run_id is None or delivery.run_id == run_id)
                and (floor is None or delivery.delivered_at >= floor)
            )

        return self.wait_for(matches, timeout=timeout)

    def replay(self, delivery_id: int) -> RelayedDelivery:
        """Fetch delivery ``delivery_id`` from the App's delivery log again and forward it once more (same GUID and
        payload, re-signed): the webapp sees a GitHub redelivery. The new record has ``redelivery=True``."""
        item = next((delivery for delivery in self.delivered if delivery.id == delivery_id), None)
        detail = dict(self.app.get_delivery(int(delivery_id)))
        request = detail.get("request") or {}
        payload = request.get("payload")
        guid = str(detail.get("guid") or (item.guid if item is not None else ""))
        event = str(detail.get("event") or (item.event if item is not None else ""))
        now = self.clock()
        delivery = RelayedDelivery(
            id=int(delivery_id),
            guid=guid,
            event=event,
            action=detail.get("action", item.action if item is not None else None),
            installation_id=_int_or_none(detail.get("installation_id")),
            repository_id=_int_or_none(detail.get("repository_id")),
            pull_number=payload_pull_number(payload),
            delivered_at=parse_timestamp(detail.get("delivered_at")) or now,
            seen_at=now,
            forwarded_at=None,
            github_status_code=_int_or_none(detail.get("status_code")),
            relay_status=None,
            redelivery=True,
            head_sha=payload_head_sha(payload),
            comment_id=_int_or_none(_get(payload, "comment", "id")),
            sender=_get(payload, "sender", "login"),
            repository_name=payload_repository_name(payload),
            run_id=payload_run_id(payload),
        )
        if isinstance(payload, dict):
            self._forward(delivery, payload, request.get("headers") or {})
        else:
            delivery.error = "payload unavailable in the delivery log"
        with self._changed:
            self._delivered.append(delivery)
            self._write_record(delivery, payload)
            self._changed.notify_all()
        _logger.info(
            "relay: replayed %s %s/%s -> %s", delivery.guid, delivery.event, delivery.action, delivery.relay_status
        )
        return delivery

    def __enter__(self) -> Self:
        """Start polling."""
        self.start()
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: TracebackType | None
    ) -> None:
        """Stop polling."""
        self.stop()


def default_accept(payload: dict[str, Any], *, org: str, event: str | None = None) -> bool:
    """Default filter: payload organization.login == org, or the event is in ALWAYS_ACCEPTED_EVENTS."""
    if event in ALWAYS_ACCEPTED_EVENTS:
        return True
    organization = payload.get("organization") or {}
    return isinstance(organization, dict) and organization.get("login") == org
