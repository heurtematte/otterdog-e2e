"""webhooks/signing (SPEC 13.3): body encodings and the signature matrix of otterdog's receiver.

The receiver only checks ``X-Hub-Signature: sha1=<hmac-sha1(secret, raw body)>`` and an exact Content-Type
(otterdog/webapp/webhook/github_webhook.py:_post_receive). The status matrix asserted here was verified against the real
GitHubWebhook class of otterdog main (Quart test client, offline): missing/invalid/sha256-only 400, charset 415,
missing Content-Type 400, null body 400, sha1(+sha256) / sha1-only / form 204.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
from typing import Any

import pytest

from otterdog_e2e.webhooks.signing import (
    FORM_CONTENT_TYPE,
    JSON_CONTENT_TYPE,
    SIGNATURE_MODES,
    encode_body,
    serialize_payload,
    sign_sha1,
    sign_sha256,
    webhook_headers,
)

SECRET = "It's a Secret to Everybody"


def otterdog_status(body: bytes, headers: dict[str, str], secret: str = SECRET) -> int:
    """Answer of otterdog's receiver for a delivery (mirror of github_webhook.py:_post_receive)."""
    signature = headers.get("X-Hub-Signature")
    if signature is None:
        return 400  # _get_header: "Missing header"
    parts = signature.split("=", 1)
    digest = hmac.new(secret.encode(), body, hashlib.sha1).hexdigest()
    if len(parts) < 2 or parts[0] != "sha1" or not hmac.compare_digest(parts[1], digest):
        return 400
    if "X-GitHub-Event" not in headers or "Content-Type" not in headers:
        return 400
    if headers["Content-Type"] == FORM_CONTENT_TYPE:
        data = json.loads(urllib.parse.parse_qs(body.decode())["payload"][0])
    elif headers["Content-Type"] == JSON_CONTENT_TYPE:
        data = json.loads(body)
    else:
        return 415
    return 400 if data is None else 204


def test_github_test_vector() -> None:
    """GitHub's documented example (validating-webhook-deliveries) for the sha256 header."""
    expected = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"
    assert sign_sha256(SECRET, b"Hello, World!") == expected
    assert sign_sha1(SECRET.encode(), b"x") == sign_sha1(SECRET, b"x")


def test_serialize_payload_is_compact_utf8() -> None:
    """Compact separators, UTF-8 (not ASCII-escaped); bytes and str pass through."""
    assert serialize_payload({"a": 1, "b": ["é"]}) == '{"a":1,"b":["é"]}'.encode()
    assert serialize_payload(b'{"raw":true}') == b'{"raw":true}'
    assert serialize_payload('{"text":1}') == b'{"text":1}'
    assert serialize_payload(None) == b"null"


def test_form_body_carries_the_json_in_payload() -> None:
    """application/x-www-form-urlencoded bodies are ``payload=<json>``; the signature covers the encoded bytes."""
    payload = {"zen": "a & b = c", "hook_id": 1}
    body = encode_body(payload, FORM_CONTENT_TYPE)
    assert body.startswith(b"payload=")
    assert json.loads(urllib.parse.parse_qs(body.decode())["payload"][0]) == payload
    assert encode_body(payload) == serialize_payload(payload)
    headers = webhook_headers("ping", body, SECRET, content_type=FORM_CONTENT_TYPE)
    assert headers["X-Hub-Signature"] == sign_sha1(SECRET, body)


@pytest.mark.parametrize(
    ("options", "status"),
    [
        ({}, 204),
        ({"signature": "sha1-only"}, 204),
        ({"signature": "sha256-only"}, 400),
        ({"signature": "invalid"}, 400),
        ({"signature": "missing"}, 400),
        ({"content_type": "application/json; charset=utf-8"}, 415),
        ({"content_type": None}, 400),
        ({"content_type": FORM_CONTENT_TYPE}, 204),
    ],
)
def test_receiver_matrix(options: dict[str, Any], status: int) -> None:
    """Every signature mode / content type gets the answer of otterdog's receiver (O-WEB-SIG)."""
    content_type = options.get("content_type", JSON_CONTENT_TYPE)
    body = encode_body({"zen": "z", "hook_id": 1}, content_type or JSON_CONTENT_TYPE)
    headers = webhook_headers("ping", body, SECRET, **options)
    assert otterdog_status(body, headers) == status


def test_null_body_is_rejected() -> None:
    """A JSON ``null`` body is signed fine but rejected with 400 (empty body)."""
    body = serialize_payload(None)
    assert otterdog_status(body, webhook_headers("ping", body, SECRET)) == 400


def test_signature_is_bound_to_the_exact_bytes() -> None:
    """Re-serializing with different whitespace breaks the signature (relays must sign what they send)."""
    payload = {"a": 1, "b": 2}
    compact = serialize_payload(payload)
    headers = webhook_headers("ping", compact, SECRET)
    pretty = json.dumps(payload, indent=2).encode()
    assert otterdog_status(compact, headers) == 204
    assert otterdog_status(pretty, headers) == 400


def test_headers_are_github_like() -> None:
    """Event, delivery, hook and installation target headers like a real App delivery."""
    body = b"{}"
    headers = webhook_headers("pull_request", body, SECRET, delivery_id="guid-1", hook_id=7, target_id=123)
    assert headers["X-GitHub-Event"] == "pull_request" and headers["X-GitHub-Delivery"] == "guid-1"
    assert headers["X-GitHub-Hook-ID"] == "7" and headers["X-GitHub-Hook-Installation-Target-ID"] == "123"
    assert headers["X-GitHub-Hook-Installation-Target-Type"] == "integration"
    assert headers["User-Agent"].startswith("GitHub-Hookshot/")
    assert set(SIGNATURE_MODES) == {"valid", "sha1-only", "sha256-only", "invalid", "missing"}
