"""WebhookInjector (SPEC 13.3) against a local receiver that behaves like otterdog's (raw-body sha1, exact type)."""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import threading
import urllib.parse
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.webhooks import payloads
from otterdog_e2e.webhooks.injector import WebhookInjector
from otterdog_e2e.webhooks.signing import FORM_CONTENT_TYPE, sign_sha1, sign_sha256

SECRET = "e2e-injector-secret-0123456789"


@dataclass
class Received:
    """One request seen by the local receiver."""

    headers: dict[str, str]
    body: bytes
    status: int


@dataclass
class Receiver:
    """A loopback receiver mirroring otterdog's checks (github_webhook.py:_post_receive)."""

    url: str
    requests: list[Received] = field(default_factory=list)


def _status(headers: dict[str, str], body: bytes) -> int:
    """otterdog's answer: 400 bad/missing signature or headers, 415 other content types, 400 null, else 204."""
    signature = headers.get("X-Hub-Signature")
    if signature is None:
        return 400
    parts = signature.split("=", 1)
    digest = hmac.new(SECRET.encode(), body, hashlib.sha1).hexdigest()
    if len(parts) < 2 or parts[0] != "sha1" or not hmac.compare_digest(parts[1], digest):
        return 400
    if "X-GitHub-Event" not in headers or "Content-Type" not in headers:
        return 400
    if headers["Content-Type"] == FORM_CONTENT_TYPE:
        data = json.loads(urllib.parse.parse_qs(body.decode())["payload"][0])
    elif headers["Content-Type"] == "application/json":
        data = json.loads(body)
    else:
        return 415
    return 400 if data is None else 204


@pytest.fixture
def receiver() -> Iterator[Receiver]:
    """Run the receiver on 127.0.0.1 in a thread."""
    seen: list[Received] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        """Records the raw request and answers like otterdog."""

        def do_POST(self) -> None:
            """Handle one delivery."""
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            headers = dict(self.headers.items())
            status = _status(headers, body)
            seen.append(Received(headers, body, status))
            self.send_response(status)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, format: str, *args: Any) -> None:
            """Silence the default stderr logging."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield Receiver(f"http://127.0.0.1:{server.server_address[1]}/github-webhook/receive", seen)
    finally:
        server.shutdown()
        server.server_close()


def test_valid_delivery_is_signed_over_the_raw_body(receiver: Receiver) -> None:
    """Both signature headers match the exact bytes received; the delivery id is passed through."""
    injector = WebhookInjector(receiver.url, SECRET)
    response = injector.send("ping", payloads.ping_payload(hook_id=5), delivery_id="guid-42")
    assert response.status_code == 204
    (seen,) = receiver.requests
    assert seen.headers["X-Hub-Signature"] == sign_sha1(SECRET, seen.body)
    assert seen.headers["X-Hub-Signature-256"] == sign_sha256(SECRET, seen.body)
    assert seen.headers["X-GitHub-Delivery"] == "guid-42" and seen.headers["X-GitHub-Event"] == "ping"
    assert seen.headers["Content-Type"] == "application/json"
    assert json.loads(seen.body)["hook_id"] == 5


@pytest.mark.parametrize(
    ("options", "status"),
    [
        ({"signature": "missing"}, 400),
        ({"signature": "invalid"}, 400),
        ({"signature": "sha256-only"}, 400),
        ({"content_type": "application/json; charset=utf-8"}, 415),
        ({"content_type": None}, 400),
        ({"content_type": FORM_CONTENT_TYPE}, 204),
        ({"signature": "sha1-only"}, 204),
    ],
)
def test_o_web_sig_matrix(receiver: Receiver, options: dict[str, Any], status: int) -> None:
    """The O-WEB-SIG cases produce otterdog's answers."""
    response = WebhookInjector(receiver.url, SECRET).send("ping", payloads.ping_payload(), **options)
    assert response.status_code == status


def test_form_delivery_signs_the_encoded_body(receiver: Receiver) -> None:
    """Form deliveries carry payload=<json> and the signature covers those bytes."""
    WebhookInjector(receiver.url, SECRET).send("ping", payloads.ping_payload(), content_type=FORM_CONTENT_TYPE)
    (seen,) = receiver.requests
    assert seen.body.startswith(b"payload=") and seen.headers["X-Hub-Signature"] == sign_sha1(SECRET, seen.body)


def test_unknown_event_and_unknown_installation_are_accepted(receiver: Receiver) -> None:
    """Events otterdog ignores (unknown event, unknown installation) still get 204."""
    injector = WebhookInjector(receiver.url, SECRET)
    assert injector.send("star", payloads.unknown_event_payload(org="e2e-test-org")).status_code == 204
    pull = payloads.synthetic_pull_request("e2e-test-org", "cfg", 1, head_ref="e2e/t3c7z8a5/x", head_sha="a" * 40)
    unknown = payloads.pull_request_payload(
        "opened", org="e2e-test-org", repo="cfg", pull_request=pull, installation_id=1
    )
    assert injector.send("pull_request", unknown).status_code == 204


def test_build_is_deterministic_for_the_body(receiver: Receiver) -> None:
    """build() returns exactly what send() posts."""
    injector = WebhookInjector(receiver.url, SECRET)
    body, headers = injector.build("ping", {"zen": "z"}, delivery_id="d1")
    assert body == b'{"zen":"z"}' and headers["X-Hub-Signature"] == sign_sha1(SECRET, body)


def test_session_and_secret_hygiene() -> None:
    """The session ignores the environment and the secret is redacted."""
    session = requests.Session()
    injector = WebhookInjector("http://127.0.0.1:1/x", SECRET, session=session)
    assert injector.session is session and session.trust_env is False
    assert REDACTOR(f"secret={SECRET}") == "secret=***"


# --- deliver(): omitted headers, raw bodies, replay ------------------------------------------------------------------
def _otterdog_answer(headers: dict[str, str], body: bytes) -> tuple[int, str]:
    """otterdog's _post_receive, message included (github_webhook.py: signature, then event, then content type)."""
    lowered = {key.lower(): value for key, value in headers.items()}
    if "x-hub-signature" not in lowered:
        return 400, "Missing header: X-Hub-Signature"
    parts = lowered["x-hub-signature"].split("=", 1)
    digest = hmac.new(SECRET.encode(), body, hashlib.sha1).hexdigest()
    if len(parts) < 2 or parts[0] != "sha1" or not hmac.compare_digest(parts[1], digest):
        return 400, "Invalid signature"
    for name in ("X-Github-Event", "content-type"):
        if name.lower() not in lowered:
            return 400, f"Missing header: {name}"
    if lowered["content-type"] == FORM_CONTENT_TYPE:
        form = urllib.parse.parse_qs(body.decode())
        if "payload" not in form:
            return 500, "KeyError: 'payload'"
        data = json.loads(form["payload"][0])
    elif lowered["content-type"] == "application/json":
        try:
            data = json.loads(body)
        except ValueError:
            return 400, "Failed to decode JSON"
    else:
        return 415, "Unknown content type"
    return (400, "Request body must contain data") if data is None else (204, "")


@pytest.fixture
def otterdog_receiver() -> Iterator[Receiver]:
    """A loopback receiver answering exactly like otterdog's (status and message)."""
    seen: list[Received] = []

    class Handler(http.server.BaseHTTPRequestHandler):
        """Records the raw request and answers like otterdog."""

        def do_POST(self) -> None:
            """Handle one delivery."""
            body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
            headers = dict(self.headers.items())
            status, message = _otterdog_answer(headers, body)
            seen.append(Received(headers, body, status))
            self.send_response(status)
            self.send_header("Content-Length", str(len(message)))
            self.end_headers()
            self.wfile.write(message.encode())

        def log_message(self, format: str, *args: Any) -> None:
            """Silence the default stderr logging."""

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield Receiver(f"http://127.0.0.1:{server.server_address[1]}/github-webhook/receive", seen)
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize(
    ("event", "options", "status", "message"),
    [
        (None, {}, 400, "Missing header: X-Github-Event"),
        ("ping", {"omit_headers": ["content-TYPE"]}, 400, "Missing header: content-type"),
        ("ping", {"omit_headers": ["X-Hub-Signature"]}, 400, "Missing header: X-Hub-Signature"),
        ("ping", {"body": b"null"}, 400, "Request body must contain data"),
        ("ping", {"body": b"{not json"}, 400, "Failed to decode JSON"),
        ("ping", {"body": b"foo=bar", "content_type": FORM_CONTENT_TYPE}, 500, "KeyError"),
        ("ping", {"headers": {"x-hub-signature": "sha1=" + "0" * 40}}, 400, "Invalid signature"),
        ("ping", {"content_type": "text/plain"}, 415, "Unknown content type"),
        ("ping", {"content_type": FORM_CONTENT_TYPE}, 204, ""),
    ],
)
def test_deliver_negative_cases(
    otterdog_receiver: Receiver, event: str | None, options: dict[str, Any], status: int, message: str
) -> None:
    """The receiver cases of coverage receiver.*: omitted headers, raw bodies (null, broken JSON, a form without
    payload), a foreign signature header, other content types."""
    injector = WebhookInjector(otterdog_receiver.url, SECRET)
    payload = None if "body" in options else payloads.ping_payload()
    response = injector.deliver(event, payload, **options)
    assert response.status_code == status and message in response.text
    (seen,) = otterdog_receiver.requests
    if "body" in options:
        assert seen.body == options["body"]
    if "headers" not in options and "omit_headers" not in options:
        assert seen.headers["X-Hub-Signature"] == sign_sha1(SECRET, seen.body)  # raw bodies are signed too


def test_deliver_omits_requests_default_headers(otterdog_receiver: Receiver) -> None:
    """User-Agent (the built one and the HTTP client's default), Accept and Accept-Encoding can be omitted; the
    delivery id stays."""
    injector = WebhookInjector(otterdog_receiver.url, SECRET)
    omit = ["user-agent", "Accept", "accept-encoding"]
    response = injector.deliver("ping", payloads.ping_payload(), delivery_id="d-ua", omit_headers=omit)
    assert response.status_code == 204
    (seen,) = otterdog_receiver.requests
    lowered = {key.lower() for key in seen.headers}
    assert not {"user-agent", "accept", "accept-encoding"} & lowered
    assert seen.headers["X-GitHub-Delivery"] == "d-ua"
    assert injector.sent[-1].headers["Accept"] is None  # recorded as passed to requests


def test_deliver_header_overrides_replace_case_insensitively(otterdog_receiver: Receiver) -> None:
    """``headers`` replaces a built header whatever its case and adds new ones."""
    injector = WebhookInjector(otterdog_receiver.url, SECRET)
    injector.deliver("ping", payloads.ping_payload(), headers={"x-github-event": "star", "X-Extra": "1"})
    (seen,) = otterdog_receiver.requests
    assert seen.headers["x-github-event"] == "star" and seen.headers["X-Extra"] == "1"
    assert [key for key in seen.headers if key.lower() == "x-github-event"] == ["x-github-event"]


def test_deliver_takes_a_payload_or_a_body() -> None:
    """Both at once is a usage error (nothing is sent)."""
    injector = WebhookInjector("http://127.0.0.1:1/x", SECRET)
    with pytest.raises(ValueError):
        injector.deliver("ping", {"zen": "z"}, body=b"{}")
    assert injector.sent == []


def test_send_without_event_header(otterdog_receiver: Receiver) -> None:
    """send(None, ...) omits X-GitHub-Event like deliver()."""
    response = WebhookInjector(otterdog_receiver.url, SECRET).send(None, payloads.ping_payload())
    assert response.status_code == 400 and "X-Github-Event" in response.text
    body, headers = WebhookInjector(otterdog_receiver.url, SECRET).build(None, {"zen": "z"})
    assert "X-GitHub-Event" not in headers and headers["X-Hub-Signature"] == sign_sha1(SECRET, body)


def test_replay_resends_the_identical_delivery(otterdog_receiver: Receiver) -> None:
    """replay(id): same bytes, same headers (signature and delivery id included); recorded with replay_of."""
    injector = WebhookInjector(otterdog_receiver.url, SECRET)
    injector.send("ping", payloads.ping_payload(), delivery_id="d-1", content_type=FORM_CONTENT_TYPE)
    injector.send("ping", payloads.ping_payload(), delivery_id="d-2")
    response = injector.replay("d-1")
    assert response.status_code == 204
    first, _, again = otterdog_receiver.requests
    assert again.body == first.body and again.headers == first.headers
    assert [sent.delivery_id for sent in injector.sent] == ["d-1", "d-2", "d-1"]
    assert injector.sent[-1].replay_of == "d-1" and injector.sent[0].replay_of is None
    assert [sent.status_code for sent in injector.sent] == [204, 204, 204]
    assert injector.last("ping") is injector.sent[-1] and injector.last("star") is None
    with pytest.raises(KeyError):
        injector.replay("never-sent")
