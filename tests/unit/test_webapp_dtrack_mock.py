"""The Dependency-Track mock (resources/dtrack_mock.py, compose profile ``dtrack``) and its client (stack.DtrackMock).

The mock runs in-process on 127.0.0.1 here; in the stack it runs in python:3.12-alpine. The request it records was
checked against otterdog main's own UploadSBOMTask._upload_bom in the SUT image: PUT /api/v1/bom, Content-Type
application/json, X-Api-Key, {projectName, projectVersion, parentUUID, autoCreate: true, bom: base64(json)}; a non-200
answer fails the upload with "failed to upload SBOM via '<url>/api/v1/bom': (<status>, <body>)".
"""

from __future__ import annotations

import base64
import json
import signal
import threading
from collections.abc import Iterator
from typing import Any

import pytest
import requests

from otterdog_e2e.resources import dtrack_mock
from otterdog_e2e.waiting import WaitTimeoutError
from otterdog_e2e.webapp.api import RemoteEndpointError, WebappApiError
from otterdog_e2e.webapp.stack import DtrackMock

BOM = {"bomFormat": "CycloneDX", "specVersion": "1.5", "components": []}
TOKEN = "e2e-dummy-token"


def upload_body(**overrides: Any) -> dict[str, Any]:
    """The JSON body otterdog's UploadSBOMTask sends."""
    body = {
        "projectName": "e2e-t3c7z8a5-sbom",
        "projectVersion": "1.0.0",
        "parentUUID": "00000000-0000-0000-0000-000000000000",
        "autoCreate": True,
        "bom": base64.b64encode(json.dumps(BOM).encode()).decode(),
    }
    body.update(overrides)
    return body


@pytest.fixture
def server() -> Iterator[str]:
    """The mock serving on a free loopback port; yields its base URL."""
    mock = dtrack_mock.make_server("127.0.0.1", 0)
    thread = threading.Thread(target=mock.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{mock.server_address[1]}"
    finally:
        mock.shutdown()
        mock.server_close()


@pytest.fixture
def http() -> requests.Session:
    """A session ignoring proxies."""
    session = requests.Session()
    session.trust_env = False
    return session


def test_upload_is_recorded_and_answered_like_dependency_track(server: str, http: requests.Session) -> None:
    """PUT /api/v1/bom answers 200 {"token"}; the record keeps the headers, the JSON and the decoded bom."""
    response = http.put(f"{server}/api/v1/bom", json=upload_body(), headers={"X-Api-Key": TOKEN})
    assert response.status_code == 200 and set(response.json()) == {"token"}
    (record,) = http.get(f"{server}/requests").json()
    assert record["seq"] == 1 and record["method"] == "PUT" and record["path"] == "/api/v1/bom"
    assert record["headers"]["X-Api-Key"] == TOKEN and record["headers"]["Content-Type"] == "application/json"
    assert record["json"]["projectName"] == "e2e-t3c7z8a5-sbom" and record["json"]["autoCreate"] is True
    assert record["bom"] == BOM and record["bom_error"] is None and record["status"] == 200
    assert record["received_at"].endswith("Z") and record["body_size"] > 0
    http.post(f"{server}/api/v1/bom", json=upload_body())  # Dependency-Track's other upload method
    assert [entry["method"] for entry in http.get(f"{server}/requests").json()] == ["PUT", "POST"]


def test_configured_answer_and_its_validation(server: str, http: requests.Session) -> None:
    """POST /config sets the status and body of later uploads; invalid configs are refused (400)."""
    assert http.get(f"{server}/config").json() == {"status": 200, "body": None}
    assert http.post(f"{server}/config", json={"status": 500, "body": "boom"}).json() == {"status": 500, "body": "boom"}
    failed = http.put(f"{server}/api/v1/bom", json=upload_body())
    assert (failed.status_code, failed.text) == (500, "boom")
    for bad in ({"status": 99}, {"status": 200, "body": 3}, "not an object"):
        assert http.post(f"{server}/config", json=bad).status_code == 400
    assert http.post(f"{server}/config", data=b"\xff").status_code == 400
    assert http.get(f"{server}/config").json()["status"] == 500
    assert [entry["path"] for entry in http.get(f"{server}/requests").json()] == ["/api/v1/bom"]  # control not recorded


def test_unknown_routes_are_recorded_404(server: str, http: requests.Session) -> None:
    """Anything else answers 404 and is recorded (unexpected calls show up); bodies that are not JSON keep text."""
    assert http.post(f"{server}/api/v1/project", data=b"plain text").status_code == 404
    assert http.get(f"{server}/api/version").status_code == 404
    first, second = http.get(f"{server}/requests").json()
    assert (first["status"], first["text"], first["json"]) == (404, "plain text", None)
    assert second["method"] == "GET" and second["body_size"] == 0


def test_clear_health_and_bad_bom(server: str, http: requests.Session) -> None:
    """DELETE /requests empties the record; /health answers; an undecodable bom is reported, not fatal."""
    http.put(f"{server}/api/v1/bom", json=upload_body(bom="%%%not-base64"))
    (record,) = http.get(f"{server}/requests").json()
    assert record["bom"] is None and record["bom_error"].startswith("Error")
    assert http.delete(f"{server}/requests").json() == {"cleared": True}
    assert http.get(f"{server}/requests").json() == []
    assert http.get(f"{server}/health").json() == {"status": "ok"}


def test_size_and_record_limits(server: str, http: requests.Session, monkeypatch: pytest.MonkeyPatch) -> None:
    """Bodies above MAX_BODY_BYTES answer 413; only the newest MAX_RECORDS requests are kept."""
    monkeypatch.setattr(dtrack_mock, "MAX_BODY_BYTES", 16)
    assert http.put(f"{server}/api/v1/bom", data=b"x" * 64).status_code == 413
    monkeypatch.setattr(dtrack_mock, "MAX_RECORDS", 2)
    for _ in range(3):
        http.put(f"{server}/api/v1/bom", data=b"{}")
    assert [entry["seq"] for entry in http.get(f"{server}/requests").json()] == [2, 3]


def test_decode_body() -> None:
    """JSON, text and base64 bom decoding."""
    assert dtrack_mock.decode_body(b"") == {"json": None, "text": None, "bom": None, "bom_error": None}
    assert dtrack_mock.decode_body(b"[1]")["json"] == [1]
    decoded = dtrack_mock.decode_body(json.dumps(upload_body()).encode())
    assert decoded["bom"] == BOM
    not_json = dtrack_mock.decode_body(base64.b64encode(b"x") + b"{")
    assert not_json["json"] is None and not_json["text"]
    bad = dtrack_mock.decode_body(json.dumps({"bom": base64.b64encode(b"not json").decode()}).encode())
    assert bad["bom"] is None and bad["bom_error"].startswith("JSONDecodeError")


def test_main_reads_the_environment_and_stops_on_sigterm(monkeypatch: pytest.MonkeyPatch) -> None:
    """main(): host, port and status from the environment, a SIGTERM handler, a clean exit on interruption."""
    seen: dict[str, Any] = {}

    class FakeServer:
        """make_server stand-in interrupted at once."""

        server_address = ("127.0.0.1", 8181)
        state = dtrack_mock.MockState(503)

        def serve_forever(self) -> None:
            """Interrupted like by docker stop."""
            raise KeyboardInterrupt

        def server_close(self) -> None:
            """Record."""
            seen["closed"] = True

    def make_server(host: str, port: int, *, status: int) -> FakeServer:
        """Record the arguments."""
        seen.update(host=host, port=port, status=status)
        return FakeServer()

    previous = signal.getsignal(signal.SIGTERM)
    monkeypatch.setattr(dtrack_mock, "make_server", make_server)
    try:
        assert dtrack_mock.main({"DTRACK_MOCK_PORT": "8181", "DTRACK_MOCK_STATUS": "503"}) == 0
        assert signal.getsignal(signal.SIGTERM) is dtrack_mock._interrupt
    finally:
        signal.signal(signal.SIGTERM, previous)
    assert seen == {"host": dtrack_mock.DEFAULT_HOST, "port": 8181, "status": 503, "closed": True}
    with pytest.raises(KeyboardInterrupt):
        dtrack_mock._interrupt(signal.SIGTERM, None)


# --- the client ----------------------------------------------------------------------------------------------------
class FakeTime:
    """Fake monotonic clock; hooks run on sleep."""

    def __init__(self) -> None:
        """t=0."""
        self.now = 0.0
        self.hooks: list[Any] = []

    def clock(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance and run the next hook."""
        self.now += seconds
        if self.hooks:
            self.hooks.pop(0)()


def test_client_round_trip(server: str, http: requests.Session) -> None:
    """health, uploads (BOM requests only), recorded, set_response, config, clear."""
    client = DtrackMock(server)
    assert client.health()
    http.put(f"{server}/api/v1/bom", json=upload_body(), headers={"X-Api-Key": TOKEN})
    http.get(f"{server}/nope")
    assert len(client.recorded()) == 2 and [entry["bom"] for entry in client.uploads()] == [BOM]
    assert client.set_response(502, "bad gateway") == {"status": 502, "body": "bad gateway"}
    assert client.config()["status"] == 502
    client.clear()
    assert client.recorded() == []
    with pytest.raises(WebappApiError):
        client.set_response(42)


def test_client_wait_uploads(server: str, http: requests.Session) -> None:
    """wait_uploads polls until enough matching uploads arrived, else WaitTimeoutError."""
    client = DtrackMock(server)
    fake = FakeTime()
    client.sleep, client.clock = fake.sleep, fake.clock
    fake.hooks.append(lambda: http.put(f"{server}/api/v1/bom", json=upload_body(projectName="other")))
    fake.hooks.append(lambda: http.put(f"{server}/api/v1/bom", json=upload_body()))
    found = client.wait_uploads(predicate=lambda entry: entry["json"]["projectName"] == "e2e-t3c7z8a5-sbom", interval=5)
    assert len(found) == 1 and fake.now == 10
    with pytest.raises(WaitTimeoutError):
        client.wait_uploads(count=3, timeout=10, interval=5)


def test_client_is_loopback_only_and_unhealthy_when_down() -> None:
    """Remote URLs are refused; a closed port is unhealthy."""
    with pytest.raises(RemoteEndpointError):
        DtrackMock("http://dtrack.example.org:8080")
    assert DtrackMock("http://127.0.0.1:1").health() is False
