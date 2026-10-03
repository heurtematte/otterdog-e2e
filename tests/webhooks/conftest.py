"""Shared fixtures and helpers of the webhooks tier (SPEC 19: H-* scenarios).

H-APP-DELIVERY checks the real App delivery path (GitHub -> delivery log -> pull relay -> webapp receiver);
H-ORG-HOOK checks an otterdog-managed organization webhook (created, pinged and removed through the SUT CLI). Waits
are classified like in the webapp tier: something GitHub should have recorded or delivered and did not is an
infrastructure problem (DeliveryTimeoutError, "(infra)"), a missing reaction of the system under test (webapp task,
live state after an otterdog apply) is a SUT problem (ReactionTimeoutError, "(SUT)"). Tests never sleep blindly.

Helpers are reached through the ``webhook_helpers`` fixture: ``--import-mode=importlib`` keeps test modules from
importing this conftest (or the webapp tier's) at run time.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.config_repo import DeliveryTimeoutError, ReactionTimeoutError
from otterdog_e2e.otterdog.output import UNKNOWN_PROPERTIES_RE
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.scenarios.collect import TIER_TIMEOUTS

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import ApplyResult
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult
    from otterdog_e2e.settings import Target
    from otterdog_e2e.webapp.api import WebappApi

T = TypeVar("T")

TIER_DIR = Path(__file__).resolve().parent
POLL_INTERVAL = 5.0
TASK_TIMEOUT = 120.0  # webapp task of a forwarded delivery
STATE_TIMEOUT = 120.0  # live state after an otterdog apply
HOOK_DELIVERY_TIMEOUT = 300.0  # GitHub logs hook deliveries (even to the never-resolving HOOK_HOST) within minutes
CONVERGE_TIMEOUT = 150.0
PR_BODY = "Opened by the otterdog-e2e harness (scenario {scenario}, run {run}); the harness closes it."


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    """Webhooks items get the tier timeout for the test call only (``func_only``, see the webapp tier conftest):
    session setup (SUT install, webapp stack, baseline reset) and the org_level reset teardown are not timed."""
    if not config.pluginmanager.hasplugin("timeout"):
        return  # pytest-timeout disabled: its marker is unknown (--strict-markers)
    for item in items:
        if Path(item.path).resolve().is_relative_to(TIER_DIR) and item.get_closest_marker("timeout") is None:
            item.add_marker(pytest.mark.timeout(TIER_TIMEOUTS["webhooks"], func_only=True))


class WebhookHelpers:
    """Helpers of the webhooks tier (``webhook_helpers`` fixture) and its budgets (seconds)."""

    STATE_TIMEOUT = STATE_TIMEOUT
    HOOK_DELIVERY_TIMEOUT = HOOK_DELIVERY_TIMEOUT
    CONVERGE_TIMEOUT = CONVERGE_TIMEOUT

    @staticmethod
    def harmless_text(renderer: OrgConfigRenderer, target: Target, description: str) -> str:
        """Baseline plus a description change of a declared repository (first fixture repo, else the configs repo):
        a PR-only change that is never merged (mergeByKey on the name overrides the description only)."""
        repo = next(iter(target.fixture_repos), target.configs_repo)
        override = f"{{ name: {json.dumps(repo)}, description: {json.dumps(description)} }}"
        return renderer.render(ConfigFragments(repositories=[override]))

    @staticmethod
    def pr_body(scenario: str, run_id: str) -> str:
        """Body of a harness PR."""
        return PR_BODY.format(scenario=scenario, run=run_id)

    @staticmethod
    def reaction(
        fn: Callable[[], T],
        *,
        until: Callable[[T], bool],
        what: str,
        timeout: float,
        infra: bool = False,
        interval: float | Sequence[float] = POLL_INTERVAL,
    ) -> T:
        """Poll ``fn`` until ``until`` holds; DeliveryTimeoutError "(infra)" or ReactionTimeoutError "(SUT)"."""
        try:
            return waiting.poll(fn, until=until, timeout=timeout, interval=interval, what=what)
        except waiting.WaitTimeoutError as exc:
            last = REDACTOR(repr(exc.last))[:1500]
            if infra:
                raise DeliveryTimeoutError(f"{what}: not observed within {timeout:g} s (infra); last: {last}") from None
            raise ReactionTimeoutError(f"{what}: not observed within {timeout:g} s (SUT); last: {last}") from None

    @staticmethod
    def wait_task(
        api: WebappApi,
        *,
        type_: str,
        org: str,
        repo: str,
        pull_request: int,
        after: datetime,
        timeout: float = TASK_TIMEOUT,
    ) -> dict[str, Any]:
        """The newest finished/failed webapp task ``type_`` of a PR created after ``after`` (ReactionTimeoutError)."""
        try:
            return api.wait_task(
                type_=type_, org_id=org, after=after, repo_name=repo, pull_request=pull_request, timeout=timeout
            )
        except waiting.WaitTimeoutError as exc:
            raise ReactionTimeoutError(
                f"webapp did not run {type_} for PR #{pull_request} within {timeout:g} s (SUT): {exc}"
            ) from None

    @staticmethod
    def delivery_records(path: Path | None) -> list[dict[str, Any]]:
        """Parsed lines of the relay's deliveries.jsonl (unparsable or partial lines are skipped)."""
        if path is None or not path.is_file():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if isinstance(record, dict):
                records.append(record)
        return records

    @staticmethod
    def assert_applied(result: CliResult, what: str) -> ApplyResult:
        """An otterdog apply that went through: exit 0, no validation abort, no failed patch, no ignored property."""
        result.assert_ok(what)
        applied = result.apply()
        assert not applied.aborted_validation, f"{what}: apply aborted by validation errors:\n{applied.raw[-2000:]}"
        assert not applied.failed_patches, f"{what}: failed patches {applied.failed_patches}"
        assert not UNKNOWN_PROPERTIES_RE.search(result.output), f"{what}: otterdog ignored unknown properties"
        return applied


@pytest.fixture
def webhook_helpers() -> type[WebhookHelpers]:
    """The WebhookHelpers namespace."""
    return WebhookHelpers


@pytest.fixture
def org_level_reset(e2e: E2EContext, baseline: BaselineManager) -> Iterator[None]:
    """Teardown of org_level scenarios outside the webapp: full baseline reset with the trusted reset CLI (SPEC 12.1:
    org_level => BaselineManager.reset() in cleanup), skipped with --e2e-keep."""
    yield
    if not e2e.options.keep:
        baseline.reset()
