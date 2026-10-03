"""Offline webapp runtime failures (O-WEB-HOOK-ERROR, O-WEB-BOOT-CONFIG): a database outage and refused settings.

These tests break their own stack on purpose (the SUT webapp image with dummy App credentials, a compose project of
this module only, like tests/offline/test_webapp_contract.py), and restore it before they end:

O-WEB-HOOK-ERROR: with MongoDB stopped (WebappStack.stop_service), whatever needs the database fails after the
driver's 30 s server selection timeout: a pull_request delivery (its hook looks the installation up) answers 500 and,
since 5466db5 (#775), the receiver logs 'failed to process webhook delivery <id> for event 'pull_request' in hook
'on_pull_request_received': <action, repository, sender, installation, null fields>' before propagating the
exception; /internal/check answers 500 ``{}`` (the /internal error handler) and the dashboard the 500 page, while a
ping (no hook) is still accepted. Once MongoDB runs again (empty: it keeps its data in memory) everything answers
again without restarting the webapp.

O-WEB-BOOT-CONFIG (#712, #677): the webapp refuses to start when a required setting is empty, also after stripping
(a value of spaces): WebappStack.restart_webapp fails with the log tail of the exited container ('<NAME> must not be
empty'); GITHUB_WEBHOOK_ENDPOINT moves the receiver (the default path then answers 404). GITHUB_WEBHOOK_SECRET and the
config token are never overridable by the harness (secrets), so their own fail-fast is not exercised here. The
refused container exits with status 0 (hypercorn's supervisor of the workers): O-KB-WEB-BOOT-EXIT-STATUS, KB-061.

O-WEB-LOGIN-REQUIRED: with an OAuth client configured (dummy GITHUB_OAUTH_CLIENT_ID / _SECRET: QuartAuth and the
login routes exist, no login is possible) the login-required page /myprojects answers the 401 page to a request
without session; without OAuth configuration it answers 500 instead (KB-059, tests/offline/test_webapp_contract.py).
"""

from __future__ import annotations

import socket
import uuid
import warnings
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import requests

from otterdog_e2e import procs, waiting
from otterdog_e2e.context import E2EContext
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.scenarios.offline import OFFLINE_ORG
from otterdog_e2e.sut.image import BuiltImage
from otterdog_e2e.sut.source import UpstreamMirror
from otterdog_e2e.webapp.api import local_session, parse_html
from otterdog_e2e.webapp.stack import WEBHOOK_PATH, WebappStack, WebappStackError, dummy_webapp_settings
from otterdog_e2e.webhooks.injector import WebhookInjector
from otterdog_e2e.webhooks.payloads import ping_payload, pull_request_payload, stable_id, synthetic_pull_request

pytestmark = [
    pytest.mark.offline,
    pytest.mark.docker,
    pytest.mark.tags("offline", "webapp", "webhooks-app"),
    pytest.mark.timeout(2700),  # the first test may build the SUT image
]

CONFIG_REPO = "otterdog-e2e-offline-config"
FIX_775 = "5466db562ffbccab7d3105949ea8bb0680a4ae2a"  # eclipse-csi/otterdog#775 (main, after v1.6.1)
OUTAGE_TIMEOUT = 180.0  # the requests that wait for the database (30 s server selection) get this budget
LOG_WAIT = 30.0
CUSTOM_ENDPOINT = "/e2e-hooks/receive"
SENDER = "e2e-user"  # payloads.DEFAULT_SENDER


def free_loopback_port() -> int:
    """A TCP port nothing listens on at 127.0.0.1 right now (compose publishes the webapp there)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def runtime_stack(offline_context: E2EContext, webapp_image: BuiltImage) -> Iterator[WebappStack]:
    """A webapp stack with dummy credentials for this module only (its tests stop services and refuse settings)."""
    stack = WebappStack(
        dummy_webapp_settings(OFFLINE_ORG, port=free_loopback_port()),
        verified=None,
        image=webapp_image.tag,
        run_ctx=new_run_context(),
        scratch=offline_context.scratch / "offline-webapp-runtime",
        artifacts_dir=offline_context.artifacts_dir / "offline-webapp-runtime",
    )
    stack.up(timeout=300)
    try:
        yield stack
    finally:
        try:
            stack.save_logs()
        finally:
            stack.down()


@pytest.fixture(scope="module")
def has_fix_775(offline_context: E2EContext, webapp_image: BuiltImage) -> bool | None:
    """Whether the webapp image contains #775 (ancestry of its revision in the upstream mirror; None: undecidable)."""
    settings = offline_context.settings
    mirror = UpstreamMirror(settings.cache_dir, settings.upstream_repo)
    try:
        if not webapp_image.revision or not (mirror.has_commit(FIX_775) and mirror.has_commit(webapp_image.revision)):
            found = None
        else:
            found = mirror.is_ancestor(FIX_775, webapp_image.revision)
    except (ValueError, OSError, procs.CalledProcessError):
        found = None
    if found is None:
        warnings.warn(f"cannot tell whether {webapp_image.tag} contains #775 ({FIX_775[:7]})", stacklevel=1)
    return found


def injector_for(stack: WebappStack, url: str | None = None) -> WebhookInjector:
    """WebhookInjector on ``url`` (default: the stack's current receiver), signing with the stack's dummy secret."""
    return WebhookInjector(url or stack.webhook_url, stack.settings.app.webhook_secret)


def delivery_id(case: str) -> str:
    """A unique X-GitHub-Delivery for one case."""
    return f"e2e-offline-{case}-{uuid.uuid4().hex[:12]}"


def pull_request_opened(installation_id: int) -> dict[str, Any]:
    """A pull_request opened event on the offline config repository of an installation the webapp does not know."""
    pull = synthetic_pull_request(OFFLINE_ORG, CONFIG_REPO, 7, head_ref="e2e/offline/runtime", head_sha="7" * 40)
    return pull_request_payload(
        "opened", org=OFFLINE_ORG, repo=CONFIG_REPO, pull_request=pull, installation_id=installation_id
    )


def wait_logged(stack: WebappStack, *needles: str) -> str:
    """The webapp log once it contains every needle (pytest.fail with the log tail after LOG_WAIT seconds)."""

    def logged() -> str | None:
        """The log when it holds every needle."""
        text = stack.logs()
        return text if all(needle in text for needle in needles) else None

    try:
        return str(waiting.wait_until(logged, timeout=LOG_WAIT, interval=1.0, what=f"log lines {needles}"))
    except waiting.WaitTimeoutError:
        missing = [needle for needle in needles if needle not in stack.logs()]
        pytest.fail(f"the webapp never logged {missing}\n--- log tail ---\n{stack.logs(tail=60)}", pytrace=False)


def page_title(response: requests.Response) -> str:
    """The <title> text of an HTML page."""
    titles = parse_html(response.text).iter("title")
    return titles[0].text() if titles else ""


def concurrently(*calls: Callable[[], requests.Response]) -> list[requests.Response]:
    """Run the calls in parallel (each request of a database outage waits 30 s) and return their responses."""
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return [future.result() for future in [pool.submit(call) for call in calls]]


@pytest.mark.scenario("O-WEB-HOOK-ERROR")
def test_database_outage(runtime_stack: WebappStack, has_fix_775: bool | None) -> None:
    """MongoDB stopped: a pull_request delivery answers 500 (with #775 the hook failure is logged with the delivery
    context), /internal/check 500 {} and /index the 500 page, a ping still 204; MongoDB started again: the same
    requests succeed without restarting the webapp."""
    stack = runtime_stack
    injector = injector_for(stack)
    installation = stable_id("otterdog-e2e offline: database outage", base=900_000_000)
    failed_id = delivery_id("outage")
    pages, internal = local_session(), local_session()
    stack.stop_service("mongodb")
    try:
        assert "mongodb" not in stack.running_services()
        hook, check, index = concurrently(
            lambda: injector.send(
                "pull_request", pull_request_opened(installation), delivery_id=failed_id, timeout=OUTAGE_TIMEOUT
            ),
            lambda: internal.get(stack.api.url("/internal/check"), timeout=OUTAGE_TIMEOUT, allow_redirects=False),
            lambda: pages.get(stack.api.url("/index"), timeout=OUTAGE_TIMEOUT, allow_redirects=False),
        )
        assert hook.status_code == 500, f"the pull_request hook answered {hook.status_code} without database"
        assert check.status_code == 500 and check.json() == {}, f"/internal/check: {check.status_code}"
        assert index.status_code == 500 and page_title(index).startswith("Otterdog Dashboard - Error 500"), (
            index.status_code
        )
        assert injector.send("ping", ping_payload()).status_code == 204, "a ping needs no database"
        if has_fix_775:
            context = (
                f"failed to process webhook delivery {failed_id} for event 'pull_request' in hook "
                f"'on_pull_request_received': action='opened', repository='{OFFLINE_ORG}/{CONFIG_REPO}', "
                f"sender='{SENDER}', installation={installation}, null fields=[]"
            )
            wait_logged(stack, context)
    finally:
        stack.start_service("mongodb")
    assert stack.health(), "the webapp did not survive the outage"
    recovered_id = delivery_id("recovered")
    recovered = injector.send(
        "pull_request", pull_request_opened(installation), delivery_id=recovered_id, timeout=OUTAGE_TIMEOUT
    )
    assert recovered.status_code == 204, f"after the outage the pull_request answered {recovered.status_code}"
    wait_logged(stack, f"received event for unknown installation '{installation}'")
    check = internal.get(stack.api.url("/internal/check"), timeout=OUTAGE_TIMEOUT, allow_redirects=False)
    assert check.status_code == 200 and check.json() == {}, f"/internal/check after the outage: {check.status_code}"


@pytest.mark.scenario("O-WEB-BOOT-CONFIG")
@pytest.mark.parametrize(
    ("setting", "value"),
    [
        pytest.param("GITHUB_WEBHOOK_VALIDATION_CONTEXT", "", id="empty"),
        pytest.param("GITHUB_ADMIN_TEAMS", "   ", id="blank-after-strip"),
        pytest.param("GITHUB_WEBHOOK_SYNC_CONTEXT", "", id="empty-sync-context"),
    ],
)
def test_required_setting_is_refused_at_boot(runtime_stack: WebappStack, setting: str, value: str) -> None:
    """A required setting that is empty, or only whitespace (values are stripped), stops the webapp at boot with
    '<SETTING> must not be empty': the recreated container exits and never becomes healthy; the defaults bring it
    back."""
    stack = runtime_stack
    try:
        with pytest.raises(WebappStackError) as refused:
            stack.restart_webapp({setting: value}, timeout=120)
        assert f"ValueError: {setting} must not be empty" in str(refused.value), str(refused.value)[-2000:]
        assert not stack.health(), "the webapp answers with a refused setting"
        assert "webapp" not in stack.running_services()
    finally:
        stack.restart_webapp({})
    assert stack.health() and injector_for(stack).send("ping", ping_payload()).status_code == 204


@pytest.mark.scenario("O-WEB-BOOT-CONFIG")
def test_webhook_endpoint_is_configurable(runtime_stack: WebappStack) -> None:
    """GITHUB_WEBHOOK_ENDPOINT moves the receiver: a signed ping on the configured path answers 204 and the default
    path is no longer routed (404); the default endpoint is back once the override is removed."""
    stack = runtime_stack
    default_url = f"{stack.base_url}{WEBHOOK_PATH}"
    try:
        stack.restart_webapp({"GITHUB_WEBHOOK_ENDPOINT": CUSTOM_ENDPOINT})
        assert stack.webhook_url == f"{stack.base_url}{CUSTOM_ENDPOINT}"
        moved_id = delivery_id("custom-endpoint")
        assert injector_for(stack).send("ping", ping_payload(), delivery_id=moved_id).status_code == 204
        wait_logged(stack, f"ping from {SENDER} ({moved_id})")
        assert injector_for(stack, default_url).send("ping", ping_payload()).status_code == 404
    finally:
        stack.restart_webapp({})
    assert stack.webhook_url == default_url
    assert injector_for(stack).send("ping", ping_payload()).status_code == 204


@pytest.mark.scenario("O-KB-WEB-BOOT-EXIT-STATUS")
@pytest.mark.known_bug("KB-061")
def test_refused_boot_exits_non_zero(runtime_stack: WebappStack) -> None:
    """A webapp that refuses its configuration at boot is a failure for its supervisor: the exited container should
    report a non-zero status (KB-061: it exits 0, hypercorn's supervisor of the workers ends cleanly)."""
    stack = runtime_stack
    try:
        with pytest.raises(WebappStackError) as refused:
            stack.restart_webapp({"GITHUB_WEBHOOK_SYNC_CONTEXT": ""}, timeout=120)
        assert "ValueError: GITHUB_WEBHOOK_SYNC_CONTEXT must not be empty" in str(refused.value)
        state, code = stack.service_states().get("webapp", ("missing", None))
        assert state == "exited", f"the refused webapp container is {state}"
        assert code not in (None, 0), f"the refused webapp container exited with status {code}"
    finally:
        stack.restart_webapp({})
    assert stack.health()


@pytest.mark.scenario("O-WEB-LOGIN-REQUIRED")
def test_login_required_page_with_oauth_configured(runtime_stack: WebappStack) -> None:
    """With a (dummy) OAuth client the webapp initializes its login manager: /myprojects without a session answers
    401 with the 'Error 401 - Access Denied' page, the public pages still answer 200; the default stack is restored."""
    stack = runtime_stack
    oauth = {"GITHUB_OAUTH_CLIENT_ID": "e2e-dummy-oauth-client", "GITHUB_OAUTH_CLIENT_SECRET": "e2e-dummy-oauth-secret"}
    pages = local_session()
    try:
        stack.restart_webapp(oauth)
        response = pages.get(stack.api.url("/myprojects"), timeout=60, allow_redirects=False)
        assert response.status_code == 401, f"GET /myprojects without session: {response.status_code} (body not shown)"
        assert "Error 401 - Access Denied" in response.text
        index = pages.get(stack.api.url("/index"), timeout=60, allow_redirects=False)
        assert index.status_code == 200, f"/index with OAuth configured: {index.status_code}"
    finally:
        stack.restart_webapp({})
    assert stack.health()
