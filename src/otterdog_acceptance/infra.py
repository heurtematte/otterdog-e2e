"""Failure texts caused by the infrastructure, never by the product: GitHub 5xx answers, rate limits and abuse
detection, network errors, delivery wait timeouts, docker/compose failures, a busy org lease, and the harness's own
tags (INFRA_PREFIX of the scenario checks and the baseline reset, ``(infra)`` of the delivery and blueprint waits).

One definition for the results.jsonl ``infra`` flag (pytest_plugin.result_line), the report (report.Record.is_infra)
and the infrastructure rules of the triage (assist.triage.RULES): until 2026-11-26 the first two missed otterdog's
``(status=502, body=...)`` and the ``[infra]`` prefix, so nightly 45596269086 marked every failure of a GitHub incident
``infra: false``.

A 5xx counts only in the forms GitHub answers take: otterdog's ``status=502``, the harness's ``GET <url> -> 502``,
``HTTP/1.1 503``, ``HTTPError 500`` and GitHub's ``502 Bad Gateway`` pages. The webapp's own 5xx (``-> HTTP 500`` of
webapp/api.py, ``(HTTP 500) (SUT)`` of config_repo.check_forwarded) is a product failure.
"""

from __future__ import annotations

import re

INFRA_PREFIX = "[infra]"  # problems caused by the infrastructure (network, 5xx, rate limits), never product defects

# (triage rule name, pattern), in the triage's order
INFRA_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("[infra] problem", re.compile(r"\[infra\]|\(infra\)")),
    (
        "GitHub server error (5xx)",
        re.compile(
            r"->\s*5\d\d\b|\b5\d\d (?:Server Error|Internal Server Error|Bad Gateway|Service Unavailable|Gateway "
            r"Time-?out)|\bHTTPError[ /]?5\d\d\b|\bHTTP/\d(?:\.\d)? 5\d\d\b|status(?: code)?[ =:]+5\d\d\b",
            re.IGNORECASE,
        ),
    ),
    ("secondary rate limit", re.compile(r"secondary rate limit", re.IGNORECASE)),
    (
        "rate limit",
        re.compile(r"API rate limit exceeded|github rate budget|github-rate-limit|-> 429\b", re.IGNORECASE),
    ),
    ("abuse detection", re.compile(r"abuse detection|abuse-rate-limits", re.IGNORECASE)),
    (
        "network error",
        re.compile(
            r"ConnectionError|ConnectionResetError|Connection reset by peer|Connection refused|RemoteDisconnected"
            r"|Max retries exceeded|Temporary failure in name resolution|Name or service not known"
            r"|Network is unreachable|Read timed out|ConnectTimeout|ReadTimeout|SSLError|Cannot connect to host",
            re.IGNORECASE,
        ),
    ),
    (
        "delivery wait timeout",
        re.compile(r"delivery not observed|DeliveryTimeoutError|timed out waiting for (?:the )?deliver", re.IGNORECASE),
    ),
    (
        "docker/compose failure",
        re.compile(
            r"Cannot connect to the Docker daemon|Error response from daemon|docker[- ]compose\b[^\n]*(?:failed|error)"
            r"|WebappNotReadyError|WebappStackError|docker: [^\n]*error",
            re.IGNORECASE,
        ),
    ),
    ("org lease busy", re.compile(r"LeaseBusy|org lease (?:held|of)", re.IGNORECASE)),
)
INFRA_RE = re.compile("|".join(f"(?:{pattern.pattern})" for _, pattern in INFRA_PATTERNS), re.IGNORECASE)


def is_infra(text: str | None) -> bool:
    """True when ``text`` (a failure or skip reason) reports an infrastructure problem."""
    return bool(text and INFRA_RE.search(text))
