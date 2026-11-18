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

O-WEB-READINESS (#949, main 2f18e71 after v1.8.0): GET /internal/ready checks MongoDB, Redis and ghproxy (a TCP connect
to GHPROXY_URI, no request) within 2 s each, reuses the result for 5 s, and answers 200 ``{"status": "ok", "checks":
{<name>: {"status": "ok"}}}`` when all are reachable, 503 with ``"status": "error"`` and ``{"status": "error", "error":
"<exception type>"}`` (the type only, never the message) for the others; /internal/health stays the liveness probe and
answers 200 during an outage. The ghproxy of the offline stack is https://api.github.com (never overridable): whether
the container reaches it depends on the host network, so only its form is asserted. SUTs without #949 answer 404 ``{}``
(an unknown /internal path).
O-WEB-INTERNAL-LEASE (#949): /internal/init and /internal/check take a Redis lease (keys ``internal-init`` and
``internal-check``, 300 s, renewed while the work runs; the init keeps it until the installation tasks it scheduled
completed) before doing anything, and answer 429 ``{"status": "<what> is already running"}`` with ``Retry-After: 60``
while another worker holds it. The test holds the leases itself (WebappStack.hold_lease, as another worker would), so
/internal/init is refused before it could reach GitHub; a check that answered releases its lease. SUTs without #949
ignore the keys (the check of an empty database answers 200) and /internal/init is never called on them.
"""

from __future__ import annotations

import re
import socket
import uuid
import warnings
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
import requests

from otterdog_acceptance import procs, waiting
from otterdog_acceptance.context import E2EContext
from otterdog_acceptance.naming import new_run_context
from otterdog_acceptance.scenarios.offline import OFFLINE_ORG
from otterdog_acceptance.sut.image import BuiltImage
from otterdog_acceptance.sut.source import UpstreamMirror
from otterdog_acceptance.webapp.api import local_session, parse_html
from otterdog_acceptance.webapp.stack import WEBHOOK_PATH, WebappStack, WebappStackError, dummy_webapp_settings
from otterdog_acceptance.webhooks.injector import WebhookInjector
from otterdog_acceptance.webhooks.payloads import ping_payload, pull_request_payload, stable_id, synthetic_pull_request

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
# eclipse-csi/otterdog#949 "feat(web): add /internal/ready and run init and check once at a time": merge commit on main
# (after v1.8.0) and head of the pull request (a pr: SUT of that head does not contain the merge commit)
FEATURE_949 = ("2f18e71fb22f93a63da5badda852c8ee1c1ba2f0", "9c27dc109b43fc5dce0e76abbeb2d6833dbdecf0")
REFERENCES_949 = [
    {
        "pr": 949,
        "note": (
            "'feat(web): add /internal/ready and run init and check once at a time': a readiness probe of MongoDB, "
            "Redis and ghproxy (200 or 503 with each check) and Redis leases that make /internal/init and "
            "/internal/check answer 429 with Retry-After 60 while another call runs; before, /internal/ready was an "
            "unknown path (404 {}) and nothing kept two inits or checks apart. Webapp only: the CLI and the offline "
            "scenarios must not change"
        ),
    }
]
REFERENCE_949_OUTAGE = [
    {
        "pr": 949,
        "note": (
            "must not change: /internal/check now takes a Redis lease first; a check failing with 500 during the "
            "MongoDB outage must release it, so the check after the outage answers 200 (not 429)"
        ),
    }
]
READY_CHECKS = {"mongodb", "redis", "ghproxy"}
READY_WAIT = 60.0  # the readiness result is reused for 5 s, each check gives up after 2 s
LEASE_TTL = 120
ERROR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")  # an exception type name, never a message


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


@pytest.fixture(scope="module")
def has_949(offline_context: E2EContext, webapp_image: BuiltImage) -> bool:
    """Whether the webapp image contains #949 (its merge commit or the head of its pull request); skip when
    undecidable (/internal/init must never be called on a SUT without the lease)."""
    settings = offline_context.settings
    mirror = UpstreamMirror(settings.cache_dir, settings.upstream_repo)
    found: list[bool | None] = []
    for commit in FEATURE_949:
        try:
            if not webapp_image.revision or not (
                mirror.has_commit(commit) and mirror.has_commit(webapp_image.revision)
            ):
                found.append(None)
            else:
                found.append(mirror.is_ancestor(commit, webapp_image.revision))
        except (ValueError, OSError, procs.CalledProcessError):
            found.append(None)
    if True in found:
        return True
    if False in found:
        return False
    pytest.skip(f"cannot tell whether {webapp_image.tag} contains #949 ({FEATURE_949[0][:7]})")


def readiness(stack: WebappStack) -> tuple[int, dict[str, Any]]:
    """Status and JSON body of GET /internal/ready."""
    response = local_session().get(stack.api.url("/internal/ready"), timeout=60, allow_redirects=False)
    return response.status_code, response.json()


def wait_readiness(stack: WebappStack, expected: dict[str, str], what: str) -> tuple[int, dict[str, Any]]:
    """/internal/ready once the status of the named checks is ``expected`` ({name: ok|error}); pytest.fail with the
    last answer after READY_WAIT seconds."""
    last: list[tuple[int, dict[str, Any]]] = []

    def matches() -> tuple[int, dict[str, Any]] | None:
        """The answer when every named check has the expected status."""
        code, body = readiness(stack)
        last[:] = [(code, body)]
        checks = body.get("checks") if isinstance(body, dict) else None
        if isinstance(checks, dict) and all(
            (checks.get(name) or {}).get("status") == status for name, status in expected.items()
        ):
            return code, body
        return None

    try:
        found: tuple[int, dict[str, Any]] = waiting.wait_until(matches, timeout=READY_WAIT, interval=1.0, what=what)
    except waiting.WaitTimeoutError:
        pytest.fail(f"/internal/ready never reported {expected} ({what}): last answer {last}", pytrace=False)
    return found


def assert_readiness_form(code: int, body: dict[str, Any]) -> dict[str, dict[str, str]]:
    """The answer of /internal/ready is consistent: the three checks, each ok or an error with an exception type
    only, 200 and 'ok' exactly when every check is ok, else 503 and 'error'; returns the checks."""
    checks = body.get("checks")
    assert isinstance(checks, dict) and set(checks) == READY_CHECKS, f"/internal/ready checks: {body}"
    for name, check in checks.items():
        assert check.get("status") in ("ok", "error"), f"check {name}: {check}"
        if check["status"] == "error":
            assert set(check) == {"status", "error"} and ERROR_TYPE_RE.match(str(check["error"])), (
                f"the failed check {name} must only name the exception type (no message): {check}"
            )
        else:
            assert set(check) == {"status"}, f"check {name}: {check}"
    ready = all(check["status"] == "ok" for check in checks.values())
    assert (code, body.get("status")) == ((200, "ok") if ready else (503, "error")), f"/internal/ready {code} {body}"
    return checks


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


@pytest.mark.scenario("O-WEB-HOOK-ERROR", references=REFERENCE_949_OUTAGE)
def test_database_outage(runtime_stack: WebappStack, has_fix_775: bool | None) -> None:
    """MongoDB stopped: a pull_request delivery answers 500 (with #775 the hook failure is logged with the delivery
    context), /internal/check 500 {} and /index the 500 page, a ping still 204; MongoDB started again: the same
    requests succeed without restarting the webapp."""
    stack = runtime_stack
    injector = injector_for(stack)
    installation = stable_id("otterdog-acceptance offline: database outage", base=900_000_000)
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


@pytest.mark.scenario("O-WEB-READINESS", references=REFERENCES_949)
def test_readiness_reports_each_dependency(runtime_stack: WebappStack, has_949: bool) -> None:
    """/internal/ready: MongoDB and Redis ok (ghproxy depends on the host network); Redis stopped: 503 with the redis
    check failed (exception type only) while /internal/health stays 200; Redis back: ok again; the same for MongoDB.
    Without #949: 404 {}."""
    stack = runtime_stack
    if not has_949:
        code, body = readiness(stack)
        assert (code, body) == (404, {}), f"a SUT without #949 has no /internal/ready: {code} {body}"
        return
    code, body = wait_readiness(stack, {"mongodb": "ok", "redis": "ok"}, "every dependency up")
    assert_readiness_form(code, body)
    for service in ("redis", "mongodb"):
        others = {name: "ok" for name in ("mongodb", "redis") if name != service}
        stack.stop_service(service)
        try:
            code, body = wait_readiness(stack, {service: "error", **others}, f"{service} stopped")
            checks = assert_readiness_form(code, body)
            assert code == 503 and checks[service]["status"] == "error", f"{service} stopped: {code} {body}"
            assert stack.health(), f"/internal/health must not depend on {service} (liveness probe)"
        finally:
            stack.start_service(service)
        code, body = wait_readiness(stack, {"mongodb": "ok", "redis": "ok"}, f"{service} started again")
        assert_readiness_form(code, body)


@pytest.mark.scenario("O-WEB-INTERNAL-LEASE", references=REFERENCES_949)
def test_init_and_check_run_once_at_a_time(runtime_stack: WebappStack, has_949: bool) -> None:
    """While another worker holds the lease, /internal/check and /internal/init answer 429 'already running' with
    Retry-After 60 and leave the lease alone; once it is gone, a check answers 200 {} and releases its own lease.
    Without #949 the keys mean nothing: the check answers 200 (init is never called on such a SUT)."""
    stack = runtime_stack
    internal = local_session()
    check_url, init_url = stack.api.url("/internal/check"), stack.api.url("/internal/init")
    try:
        assert stack.hold_lease("internal-check", ttl=LEASE_TTL), "the check lease is already held"
        busy = internal.get(check_url, timeout=60, allow_redirects=False)
        if not has_949:
            assert busy.status_code == 200 and busy.json() == {}, f"a SUT without #949 has no lease: {busy.status_code}"
            return
        assert busy.status_code == 429, f"/internal/check while the lease is held: {busy.status_code} {busy.text[:200]}"
        assert busy.headers.get("Retry-After") == "60", f"Retry-After of the refused check: {dict(busy.headers)}"
        assert busy.json() == {"status": "a check of the blueprints is already running"}, busy.json()
        assert stack.hold_lease("internal-init", ttl=LEASE_TTL), "the init lease is already held"
        refused = internal.get(init_url, timeout=60, allow_redirects=False)
        assert refused.status_code == 429, f"/internal/init while the lease is held: {refused.status_code}"
        assert refused.headers.get("Retry-After") == "60", f"Retry-After of the refused init: {dict(refused.headers)}"
        assert refused.json() == {"status": "an initialization is already running"}, refused.json()
        assert stack.lease_held("internal-init") and stack.lease_held("internal-check"), (
            "a refused call dropped the lease of the worker holding it"
        )
    finally:
        stack.drop_lease("internal-init")
        stack.drop_lease("internal-check")
    done = internal.get(check_url, timeout=60, allow_redirects=False)
    assert done.status_code == 200 and done.json() == {}, f"/internal/check after the lease is gone: {done.status_code}"
    assert not stack.lease_held("internal-check"), "the check kept its lease after answering"
