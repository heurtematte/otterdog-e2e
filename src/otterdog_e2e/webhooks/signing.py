"""Webhook payload serialization, HMAC signatures and delivery headers (SPEC 13.3).

otterdog's receiver (otterdog/webapp/webhook/github_webhook.py) only checks ``X-Hub-Signature: sha1=<hmac-sha1(secret,
raw body)>`` and requires ``Content-Type`` to be exactly ``application/json`` (or ``application/x-www-form-urlencoded``);
``X-Hub-Signature-256`` is never read. The headers built here mirror a real GitHub delivery so that both are present.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import urllib.parse
import uuid
from typing import Any

JSON_CONTENT_TYPE = "application/json"
FORM_CONTENT_TYPE = "application/x-www-form-urlencoded"
USER_AGENT = "GitHub-Hookshot/otterdog-e2e"
TARGET_TYPES = ("integration", "repository", "organization")
# valid: sha1 + sha256 (as GitHub sends) | sha1-only | sha256-only (rejected by otterdog) | invalid (wrong key) | missing
SIGNATURE_MODES = ("valid", "sha1-only", "sha256-only", "invalid", "missing")


def _key(secret: str | bytes) -> bytes:
    """HMAC key bytes (str secrets are UTF-8 encoded like the receiver does)."""
    return secret if isinstance(secret, bytes) else secret.encode("utf-8")


def serialize_payload(payload: Any) -> bytes:
    """Compact UTF-8 JSON of a payload; bytes are returned unchanged and str is encoded as is."""
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def encode_body(payload: Any, content_type: str = JSON_CONTENT_TYPE) -> bytes:
    """Request body for ``content_type``: the JSON itself, or ``payload=<json>`` for the form content type."""
    body = serialize_payload(payload)
    if content_type == FORM_CONTENT_TYPE:
        return urllib.parse.urlencode({"payload": body.decode("utf-8")}).encode("ascii")
    return body


def sign_sha1(secret: str | bytes, body: bytes) -> str:
    """``X-Hub-Signature`` value: ``sha1=<hex hmac-sha1(secret, body)>``."""
    return "sha1=" + hmac.new(_key(secret), body, hashlib.sha1).hexdigest()


def sign_sha256(secret: str | bytes, body: bytes) -> str:
    """``X-Hub-Signature-256`` value: ``sha256=<hex hmac-sha256(secret, body)>``."""
    return "sha256=" + hmac.new(_key(secret), body, hashlib.sha256).hexdigest()


def _signature_headers(secret: str | bytes, body: bytes, signature: str) -> dict[str, str]:
    """Signature headers for one of SIGNATURE_MODES."""
    if signature not in SIGNATURE_MODES:
        raise ValueError(f"unknown signature mode {signature!r}, expected one of {SIGNATURE_MODES}")
    if signature == "missing":
        return {}
    key = _key(secret) + b"-wrong" if signature == "invalid" else secret
    headers = {}
    if signature != "sha256-only":
        headers["X-Hub-Signature"] = sign_sha1(key, body)
    if signature != "sha1-only":
        headers["X-Hub-Signature-256"] = sign_sha256(key, body)
    return headers


def webhook_headers(
    event: str,
    body: bytes,
    secret: str | bytes,
    *,
    delivery_id: str | None = None,
    content_type: str | None = JSON_CONTENT_TYPE,
    signature: str = "valid",
    hook_id: int | str | None = None,
    target_type: str | None = "integration",
    target_id: int | str | None = None,
) -> dict[str, str]:
    """Headers of a GitHub webhook delivery of ``body``; ``content_type=None`` omits Content-Type (receiver: 400)."""
    headers = {
        "User-Agent": USER_AGENT,
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": delivery_id or str(uuid.uuid4()),
    }
    if content_type is not None:
        headers["Content-Type"] = content_type
    if hook_id is not None:
        headers["X-GitHub-Hook-ID"] = str(hook_id)
    if target_type is not None:
        headers["X-GitHub-Hook-Installation-Target-Type"] = target_type
    if target_id is not None:
        headers["X-GitHub-Hook-Installation-Target-ID"] = str(target_id)
    headers.update(_signature_headers(secret, body, signature))
    return headers
