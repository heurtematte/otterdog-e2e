"""otterdog_acceptance.infra: one infrastructure classification for results.jsonl, the report and the triage."""

from __future__ import annotations

import pytest

from otterdog_acceptance import infra, report
from otterdog_acceptance.assist import triage
from otterdog_acceptance.scenarios import checks

INFRA_TEXTS = (
    # otterdog's apply box during the GitHub incident of nightly 45596269086
    "Exception while accessing 'https://api.github.com/orgs/o/repos': (status=502, body={",
    "GitHubError: GET https://api.github.com/orgs/o/hooks -> 502: Bad Gateway",
    "<html><title>503 Service Unavailable</title>",
    "requests.exceptions.HTTPError 500",
    "HTTP/1.1 504 Gateway Timeout",
    "  - step 'a' state: [infra] r: lookup failed",
    "delivery not observed within 300 s (infra)",
    "otterdog plan failed (exit code 1, infra error: secondary rate limit)",
    "github rate budget: core remaining 12 < 50",
    "You have exceeded a secondary rate limit; abuse detection",
    "ConnectionResetError: [Errno 104] Connection reset by peer",
    "Cannot connect to the Docker daemon at unix:///var/run/docker.sock",
    "LeaseBusy: org lease held by run tp1zn393",
)
PRODUCT_TEXTS = (
    "AssertionError: plan expected 1 change, got 2",
    # the webapp's own 5xx are product failures (webapp/api.py, config_repo.check_forwarded)
    "POST http://127.0.0.1:5000/internal/init -> HTTP 500: Internal error",
    "webapp failed on push delivery 1234 for the config PR (HTTP 500) (SUT)",
    "Exception while accessing 'https://api.github.com/orgs/o': (status=409, body={",
    'body={"message":"Repository creation failed.","status":"422"}',
    "failed to create repo from template 'o/tpl': repo not initialized after 5s",
)


@pytest.mark.parametrize("text", INFRA_TEXTS)
def test_infrastructure_texts(text: str) -> None:
    """GitHub 5xx (otterdog's status=5xx included), rate limits, network, docker, lease and the harness tags."""
    assert infra.is_infra(text)
    assert any(rule.pattern.search(text) for rule in triage.RULES if rule.category == "infrastructure")


@pytest.mark.parametrize("text", PRODUCT_TEXTS)
def test_product_texts(text: str) -> None:
    """Assertion failures, 4xx answers and the webapp's own 5xx are no infrastructure problems."""
    assert not infra.is_infra(text)
    assert not any(rule.pattern.search(text) for rule in triage.RULES if rule.category == "infrastructure")


def test_one_definition() -> None:
    """The report, the scenario checks and the triage use the shared patterns, in the triage's order."""
    assert report.INFRA_RE is infra.INFRA_RE
    assert checks.INFRA_PREFIX == infra.INFRA_PREFIX == "[infra]"
    infra_rules = [(rule.name, rule.pattern) for rule in triage.RULES if rule.category == "infrastructure"]
    assert infra_rules == list(infra.INFRA_PATTERNS)
    # the infrastructure rules come first: they win over the harness error types (a SafetyError tagged [infra])
    assert all(rule.category == "infrastructure" for rule in triage.RULES[: len(infra_rules)])


def test_is_infra_of_nothing() -> None:
    """No text (a passed item) is no infrastructure problem."""
    assert not infra.is_infra(None) and not infra.is_infra("")
