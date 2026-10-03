"""Dependency-Track mock of the webapp tier: compose profile ``dtrack`` (python:3.12-alpine, standard library only).

otterdog's dependency_track_upload policy (otterdog/webapp/tasks/policies/upload_sbom.py) PUTs
``{DEPENDENCY_TRACK_URL}/api/v1/bom`` with the headers ``Content-Type: application/json`` and
``X-Api-Key: <DEPENDENCY_TRACK_TOKEN>`` and the JSON body ``{projectName, projectVersion, parentUUID, autoCreate: true,
bom: base64(json)}``; any answer but 200 fails the upload task. This server records every request and answers:

* ``PUT|POST /api/v1/bom``: the configured status (env ``DTRACK_MOCK_STATUS``, default 200) and body (default
  ``{"token": "<uuid>"}``, Dependency-Track's own answer);
* ``GET /requests``: the recorded requests as a JSON list (oldest first; the ``bom`` of an upload decoded);
  ``DELETE /requests`` forgets them;
* ``GET /config`` and ``POST /config`` ``{"status": <int>, "body": <str|null>}``: the answer of the next uploads;
* ``GET /health``: 200;
* anything else: 404, recorded too, so unexpected calls show up.

The harness reaches it on a 127.0.0.1 port mapping, the webapp on the compose network (``http://dtrack-mock:8080``).
It only ever holds dummy data: the dummy DEPENDENCY_TRACK_TOKEN and SBOMs of e2e repositories.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import os
import signal
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

DEFAULT_HOST = "0.0.0.0"  # noqa: S104 - inside its container; compose publishes it on 127.0.0.1 only
DEFAULT_PORT = 8080
DEFAULT_STATUS = 200
BOM_PATH = "/api/v1/bom"
REQUESTS_PATH = "/requests"
CONFIG_PATH = "/config"
HEALTH_PATH = "/health"
MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_RECORDS = 200
MAX_TEXT_CHARS = 4096
RECORDED_HEADERS = ("Content-Type", "Content-Length", "X-Api-Key", "User-Agent", "Accept")

_logger = logging.getLogger("dtrack-mock")


def _now() -> str:
    """Current UTC time, ISO 8601 with a ``Z`` suffix."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def decode_body(raw: bytes) -> dict[str, Any]:
    """``json`` (the parsed body or None), ``text`` (a non-JSON body, truncated), ``bom`` (the base64 ``bom`` field of
    an upload decoded as JSON) and ``bom_error`` (why it could not be decoded)."""
    result: dict[str, Any] = {"json": None, "text": None, "bom": None, "bom_error": None}
    if not raw:
        return result
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        result["text"] = raw.decode("utf-8", errors="replace")[:MAX_TEXT_CHARS]
        return result
    result["json"] = document
    encoded = document.get("bom") if isinstance(document, dict) else None
    if isinstance(encoded, str):
        try:
            result["bom"] = json.loads(base64.b64decode(encoded, validate=True).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            result["bom_error"] = f"{type(exc).__name__}: {exc}"
    return result


class MockState:
    """Recorded requests and the configured upload answer (thread safe)."""

    def __init__(self, status: int = DEFAULT_STATUS, body: str | None = None) -> None:
        """No request recorded yet; uploads answer ``status`` / ``body``."""
        self._lock = threading.Lock()
        self._records: list[dict[str, Any]] = []
        self._seq = 0
        self.status = status
        self.body = body

    def record(self, entry: dict[str, Any]) -> dict[str, Any]:
        """Store one request (sequence number added; only the newest MAX_RECORDS are kept)."""
        with self._lock:
            self._seq += 1
            entry = {"seq": self._seq, **entry}
            self._records.append(entry)
            del self._records[:-MAX_RECORDS]
            return entry

    def snapshot(self) -> list[dict[str, Any]]:
        """The recorded requests, oldest first."""
        with self._lock:
            return list(self._records)

    def clear(self) -> None:
        """Forget every recorded request."""
        with self._lock:
            self._records.clear()

    def configure(self, status: int, body: str | None) -> None:
        """Answer later uploads with ``status`` and ``body`` (None: Dependency-Track's token document)."""
        with self._lock:
            self.status, self.body = status, body

    def config(self) -> dict[str, Any]:
        """The configured upload answer."""
        with self._lock:
            return {"status": self.status, "body": self.body}

    def upload_answer(self) -> tuple[int, bytes]:
        """Status and body bytes of an upload answer."""
        with self._lock:
            status, body = self.status, self.body
        if body is None:
            body = json.dumps({"token": str(uuid.uuid4())})
        return status, body.encode("utf-8")


class Handler(BaseHTTPRequestHandler):
    """Routes the mock's requests (module docstring); ``server.state`` holds the MockState."""

    server_version = "otterdog-e2e-dtrack-mock/1"

    @property
    def state(self) -> MockState:
        """The MockState of the serving MockServer."""
        return self.server.state  # type: ignore[attr-defined]

    def do_GET(self) -> None:
        """GET /health, /requests, /config (anything else: 404)."""
        self._dispatch("GET")

    def do_POST(self) -> None:
        """POST /api/v1/bom, /config."""
        self._dispatch("POST")

    def do_PUT(self) -> None:
        """PUT /api/v1/bom."""
        self._dispatch("PUT")

    def do_DELETE(self) -> None:
        """DELETE /requests."""
        self._dispatch("DELETE")

    def _dispatch(self, method: str) -> None:
        """Read the body, answer and record the request (control endpoints are not recorded)."""
        path = urlsplit(self.path).path
        raw = self._body()
        if raw is None:
            self._answer(413, {"error": f"body larger than {MAX_BODY_BYTES} bytes"})
            return
        if path == HEALTH_PATH and method == "GET":
            self._answer(200, {"status": "ok"})
        elif path == REQUESTS_PATH and method == "GET":
            self._answer(200, self.state.snapshot())
        elif path == REQUESTS_PATH and method == "DELETE":
            self.state.clear()
            self._answer(200, {"cleared": True})
        elif path == CONFIG_PATH and method == "GET":
            self._answer(200, self.state.config())
        elif path == CONFIG_PATH and method == "POST":
            self._configure(raw)
        elif path == BOM_PATH and method in ("PUT", "POST"):
            status, body = self.state.upload_answer()
            self._send(status, body, "application/json")
            self._record(method, raw, status)
        else:
            self._answer(404, {"error": f"no route {method} {path}"})
            self._record(method, raw, 404)

    def _body(self) -> bytes | None:
        """The request body (by Content-Length), None when it is too large."""
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length > MAX_BODY_BYTES:
            return None
        return self.rfile.read(length) if length > 0 else b""

    def _configure(self, raw: bytes) -> None:
        """POST /config: validate and store the next upload answer."""
        try:
            document = json.loads(raw.decode("utf-8") or "{}")
            status = int(document.get("status", DEFAULT_STATUS))
            body = document.get("body")
        except (UnicodeDecodeError, ValueError, TypeError, AttributeError) as exc:
            self._answer(400, {"error": f"invalid config: {exc}"})
            return
        if not 100 <= status <= 599 or not (body is None or isinstance(body, str)):
            self._answer(400, {"error": "status must be an HTTP status, body a string or null"})
            return
        self.state.configure(status, body)
        self._answer(200, self.state.config())

    def _record(self, method: str, raw: bytes, status: int) -> None:
        """Record one request with its interesting headers and decoded body."""
        parts = urlsplit(self.path)
        headers = {name: self.headers[name] for name in RECORDED_HEADERS if self.headers.get(name) is not None}
        self.state.record(
            {
                "received_at": _now(),
                "method": method,
                "path": parts.path,
                "query": parts.query,
                "headers": headers,
                "status": status,
                "body_size": len(raw),
                **decode_body(raw),
            }
        )

    def _answer(self, status: int, document: Any) -> None:
        """Send a JSON document."""
        self._send(status, json.dumps(document).encode("utf-8"), "application/json")

    def _send(self, status: int, body: bytes, content_type: str) -> None:
        """Send one complete response."""
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        """Log request lines through logging (never the headers: X-Api-Key)."""
        _logger.info("%s - %s", self.address_string(), format % args)


class MockServer(ThreadingHTTPServer):
    """ThreadingHTTPServer carrying the MockState."""

    daemon_threads = True

    def __init__(self, address: tuple[str, int], state: MockState) -> None:
        """Bind ``address`` and keep ``state`` for the handlers."""
        super().__init__(address, Handler)
        self.state = state


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, *, status: int = DEFAULT_STATUS) -> MockServer:
    """A bound (not yet serving) mock answering uploads with ``status``."""
    return MockServer((host, port), MockState(status))


def _interrupt(signum: int, frame: Any) -> None:
    """SIGTERM handler: stop serving (as PID 1 of its container the default action would be ignored)."""
    raise KeyboardInterrupt(f"signal {signum}")


def main(environ: dict[str, str] | None = None) -> int:
    """Serve forever on DTRACK_MOCK_HOST:DTRACK_MOCK_PORT (default 0.0.0.0:8080), uploads answer DTRACK_MOCK_STATUS."""
    env = dict(os.environ if environ is None else environ)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s dtrack-mock %(message)s")
    server = make_server(
        env.get("DTRACK_MOCK_HOST", DEFAULT_HOST),
        int(env.get("DTRACK_MOCK_PORT") or DEFAULT_PORT),
        status=int(env.get("DTRACK_MOCK_STATUS") or DEFAULT_STATUS),
    )
    signal.signal(signal.SIGTERM, _interrupt)
    _logger.info("listening on %s:%s, uploads answer %s", *server.server_address[:2], server.state.status)
    try:
        server.serve_forever()
    except KeyboardInterrupt:  # docker stop (SIGTERM) or Ctrl-C when run by hand
        _logger.info("stopping")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
