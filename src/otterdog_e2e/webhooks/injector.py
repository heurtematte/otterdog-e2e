"""Direct injection of signed (or deliberately mis-signed) webhook deliveries into a webapp receiver (SPEC 13.3).

The receiver (otterdog/webapp/webhook/github_webhook.py) hashes the RAW request body, so the signature is always
computed over the exact bytes sent: the compact JSON document, ``payload=<json>`` for the form content type
(``application/x-www-form-urlencoded``: the receiver reads ``(await request.form)["payload"]`` and json-decodes it), or
the raw ``body`` bytes given to deliver(). Expected answers: 204 accepted (ping, unknown and ignored events, pydantic
failures alike), 400 bad or missing signature, missing X-GitHub-Event or Content-Type (``Missing header: <name>``), a
null body (``Request body must contain data``) or an undecodable JSON body, 415 any other content type (a charset
parameter too), 500 handler exceptions (a form body without ``payload`` included).

Every delivery sent is recorded (``sent``); ``replay(delivery_id)`` posts the identical bytes and headers again, as a
GitHub redelivery does (same ``X-GitHub-Delivery``; otterdog does not deduplicate deliveries). Under DEBUG the webapp
answers a 500 with a debug page that may show the handler's local variables: never write such bodies to artifacts.
"""

from __future__ import annotations

import logging
from collections.abc import Collection, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from urllib3.util import SKIP_HEADER

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.webapp.api import local_session
from otterdog_e2e.webhooks.signing import JSON_CONTENT_TYPE, encode_body, webhook_headers

if TYPE_CHECKING:
    import requests

_logger = logging.getLogger(__name__)

# default headers of requests (Accept, Connection: omitted by sending None, which removes them from the merged
# request headers) and of urllib3 (User-Agent, Accept-Encoding, Host: omitted by urllib3's SKIP_HEADER value);
# Content-Length is always sent
REQUESTS_DEFAULT_HEADERS = ("Accept", "Connection")
URLLIB3_SKIPPABLE_HEADERS = ("User-Agent", "Accept-Encoding", "Host")
SIGNATURE_HEADERS = ("X-Hub-Signature", "X-Hub-Signature-256")


@dataclass(frozen=True)
class SentDelivery:
    """One delivery posted by the injector: the exact body bytes and headers, and the receiver's answer."""

    event: str | None
    delivery_id: str | None
    body: bytes
    headers: dict[str, str | None]
    status_code: int
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    replay_of: str | None = None  # delivery id of the delivery this one replayed


def _lower(names: Collection[str]) -> set[str]:
    """Lower-cased header names."""
    return {name.lower() for name in names}


class WebhookInjector:
    """POSTs payloads to the receiver endpoint with GitHub-like headers (requests session with trust_env False)."""

    def __init__(self, endpoint_url: str, secret: str, *, session: requests.Session | None = None) -> None:
        """Bind the endpoint (e.g. WebappStack.webhook_url) and the webhook secret (registered with REDACTOR)."""
        self.endpoint_url = endpoint_url
        self.secret = secret
        self.session = local_session(session)
        self.sent: list[SentDelivery] = []
        REDACTOR.add(secret)

    def build(
        self,
        event: str | None,
        payload: Any,
        *,
        delivery_id: str | None = None,
        content_type: str | None = JSON_CONTENT_TYPE,
        signature: str = "valid",
    ) -> tuple[bytes, dict[str, str]]:
        """Body bytes and headers of one delivery (the signature covers exactly these bytes); ``event=None`` omits
        X-GitHub-Event."""
        body = encode_body(payload, content_type or JSON_CONTENT_TYPE)
        headers = webhook_headers(
            event or "", body, self.secret, delivery_id=delivery_id, content_type=content_type, signature=signature
        )
        if event is None:
            del headers["X-GitHub-Event"]
        return body, headers

    def send(
        self,
        event: str | None,
        payload: Any,
        *,
        delivery_id: str | None = None,
        content_type: str | None = JSON_CONTENT_TYPE,
        signature: str = "valid",
        timeout: float = 30,
    ) -> requests.Response:
        """Serialize, sign (signing.SIGNATURE_MODES) and POST one delivery; returns the raw response.

        ``content_type=FORM_CONTENT_TYPE`` sends the payload form-encoded (``payload=<json>``); ``None`` omits the
        Content-Type header, ``event=None`` the X-GitHub-Event header.
        """
        body, headers = self.build(
            event, payload, delivery_id=delivery_id, content_type=content_type, signature=signature
        )
        return self._post(event, body, headers, timeout=timeout)

    def deliver(
        self,
        event: str | None,
        payload: Any = None,
        *,
        body: bytes | None = None,
        delivery_id: str | None = None,
        content_type: str | None = JSON_CONTENT_TYPE,
        signature: str = "valid",
        omit_headers: Collection[str] = (),
        headers: Mapping[str, str] | None = None,
        timeout: float = 30,
    ) -> requests.Response:
        """POST one delivery with full control over its bytes and headers (negative receiver cases).

        ``body``: raw bytes sent as they are instead of the encoded ``payload`` (invalid JSON, ``null``, a form body
        without ``payload``, ...), still signed over exactly these bytes (signing.SIGNATURE_MODES). ``headers`` are
        added or replace the built ones after signing (e.g. a foreign ``X-Hub-Signature``); ``omit_headers`` removes
        headers (case-insensitive), the HTTP client's own User-Agent, Accept, Accept-Encoding, Connection and Host
        included (Content-Length is always sent).
        """
        if body is None:
            raw, built = self.build(
                event, payload, delivery_id=delivery_id, content_type=content_type, signature=signature
            )
        else:
            if payload is not None:
                raise ValueError("deliver() takes either a payload or raw body bytes, not both")
            raw = bytes(body)
            built = webhook_headers(
                event or "", raw, self.secret, delivery_id=delivery_id, content_type=content_type, signature=signature
            )
            if event is None:
                del built["X-GitHub-Event"]
        final: dict[str, str | None] = dict(built)
        for name, value in (headers or {}).items():
            for existing in [key for key in final if key.lower() == name.lower()]:
                del final[existing]
            final[name] = value
        omitted = _lower(omit_headers)
        final = {key: value for key, value in final.items() if key.lower() not in omitted}
        for name in REQUESTS_DEFAULT_HEADERS:
            if name.lower() in omitted:
                final[name] = None  # requests drops None-valued headers from the merged request headers
        for name in URLLIB3_SKIPPABLE_HEADERS:
            if name.lower() in omitted:
                final[name] = SKIP_HEADER  # urllib3 neither sends it nor adds its default
        return self._post(event, raw, final, timeout=timeout)

    def replay(self, delivery_id: str, *, timeout: float = 30) -> requests.Response:
        """POST the last delivery sent with ``delivery_id`` again, byte for byte and with the same headers (a GitHub
        redelivery); KeyError when no such delivery was sent."""
        original = next((sent for sent in reversed(self.sent) if sent.delivery_id == delivery_id), None)
        if original is None:
            raise KeyError(f"no delivery {delivery_id!r} was sent by this injector")
        return self._post(
            original.event, original.body, original.headers, timeout=timeout, replay_of=original.delivery_id
        )

    def last(self, event: str | None = None) -> SentDelivery | None:
        """The last delivery sent (of ``event`` when given)."""
        return next((sent for sent in reversed(self.sent) if event is None or sent.event == event), None)

    def _post(
        self,
        event: str | None,
        body: bytes,
        headers: Mapping[str, str | None],
        *,
        timeout: float,
        replay_of: str | None = None,
    ) -> requests.Response:
        """POST the bytes and headers, record the delivery and return the response."""
        response = self.session.post(
            self.endpoint_url, data=body, headers=dict(headers), timeout=timeout, allow_redirects=False
        )
        delivery_id = next((value for key, value in headers.items() if key.lower() == "x-github-delivery"), None)
        self.sent.append(
            SentDelivery(event, delivery_id, body, dict(headers), response.status_code, replay_of=replay_of)
        )
        _logger.debug(
            "injected %s delivery %s (%s, signature %s)%s -> HTTP %s",
            event,
            delivery_id,
            next((value for key, value in headers.items() if key.lower() == "content-type"), None),
            "present" if any(key in headers for key in SIGNATURE_HEADERS) else "absent",
            f" replaying {replay_of}" if replay_of else "",
            response.status_code,
        )
        return response
