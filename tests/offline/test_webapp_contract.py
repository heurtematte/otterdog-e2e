"""Offline webapp contract (SPEC 19: O-WEB-BOOT, O-WEB-SIG, O-WEB-ROUTES): the SUT webapp image with dummy App
credentials.

The webapp image of the SUT under test (plugin fixture ``webapp_image``: built from the SUT source, or the prebuilt
--e2e-webapp-image) runs in the docker compose stack of the harness (webapp + mongodb + valkey, published on a free
loopback port only) with a random dummy App key, app id 1, a random webhook secret and a dummy config token: nothing
it does can reach a real GitHub organization, and none of these tests needs one. /internal/init is never called (it
would list the App installations on GitHub), nor the statistics job of /api/pullrequests/statistics/progress (it asks
GitHub for the App's identity first); every event sent belongs to an installation the webapp does not know, so no
hook calls GitHub either.

O-WEB-BOOT: the stack becomes healthy and the footer of /index shows the SUT image version.
O-WEB-SIG: the receiver contract of otterdog/webapp/webhook/github_webhook.py: only ``X-Hub-Signature: sha1=<hmac>``
over the raw body is checked (missing, wrong or sha256-only -> 400 ``Missing header: X-Hub-Signature`` / ``Invalid
signature``), X-GitHub-Event and Content-Type are required (400 ``Missing header: <name>``), the content type must be
exactly ``application/json`` or ``application/x-www-form-urlencoded`` with a ``payload`` field (anything else, a charset
parameter too -> 415), a ``null`` body and undecodable JSON answer 400; accepted deliveries answer 204 (ping, events
nobody handles, events of an installation the webapp does not know, which it logs as "received event for unknown
installation '<id>'"), replays included (no deduplication). Each event is logged with a description built from its
payload (``<description> (<delivery id>)``), workflow_job only when queued and workflow_run only when completed.
Since 5466db5 (#775, after v1.6.1) a description that cannot be formatted (a null field) only warns and the event is
processed (older SUTs answer 500 and drop it), rejections are logged with their delivery id, and X-GitHub-Delivery is
optional (older SUTs answer 400 ``Missing header: X-Github-Delivery``): these expectations follow the ancestry of the
fix commit in the webapp image (its revision label).
O-WEB-ROUTES: the pages and endpoints that need no installation: redirects, static files, the public and admin pages
(no login), the 404 page, /internal/* (404 ``{}`` for unknown paths), the JSON listings of an empty database, the
GraphQL explorer and queries, the parameter validation of the pull request statistics; /myprojects without a session.
Never write a 500 body to artifacts: under DEBUG it may be a debug page.
"""

from __future__ import annotations

import socket
import uuid
import warnings
from collections.abc import Iterator
from typing import Any

import pytest
import requests

from otterdog_e2e import procs, waiting
from otterdog_e2e.context import E2EContext
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.scenarios.offline import OFFLINE_ORG, offline_run_context
from otterdog_e2e.sut.image import BuiltImage
from otterdog_e2e.sut.source import UpstreamMirror
from otterdog_e2e.webapp.api import parse_html
from otterdog_e2e.webapp.stack import WebappStack, dummy_webapp_settings
from otterdog_e2e.webhooks.injector import WebhookInjector
from otterdog_e2e.webhooks.payloads import (
    ping_payload,
    pull_request_payload,
    push_payload,
    stable_id,
    synthetic_pull_request,
    unknown_event_payload,
    workflow_job_payload,
    workflow_run_payload,
)
from otterdog_e2e.webhooks.signing import FORM_CONTENT_TYPE

# the first test may build the SUT image (docker build of otterdog: several minutes on a cold layer cache)
pytestmark = [
    pytest.mark.offline,
    pytest.mark.docker,
    pytest.mark.tags("offline", "webapp", "webhooks-app"),
    pytest.mark.timeout(2700),
]

UNKNOWN_INSTALLATION = stable_id("otterdog-e2e offline: unknown installation", base=900_000_000)
UNKNOWN_INSTALLATION_LOG = f"received event for unknown installation '{UNKNOWN_INSTALLATION}'"
EVENT_LOAD_FAILURE_LOG = "failed to load pull request event data"
CONFIG_REPO = "otterdog-e2e-offline-config"
LOG_WAIT = 30.0
RUN = offline_run_context()
EVENT_REPO = RUN.name("events")  # repository of the synthetic push / workflow events
SENDER = "e2e-user"  # payloads.DEFAULT_SENDER
# eclipse-csi/otterdog#775 "fix: do not drop webhook events whose payload cannot be formatted" (main, after v1.6.1)
FIX_775 = "5466db562ffbccab7d3105949ea8bb0680a4ae2a"
UNKNOWN_PROJECT = f"{OFFLINE_ORG}-no-such-project"
EMPTY_PAGE = {"data": [], "itemsCount": 0}


def free_loopback_port() -> int:
    """A TCP port nothing listens on at 127.0.0.1 right now (compose publishes the webapp there)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="module")
def offline_stack(offline_context: E2EContext, webapp_image: BuiltImage) -> Iterator[WebappStack]:
    """The SUT webapp stack with dummy credentials (own compose project: never the session's live stack)."""
    stack = WebappStack(
        dummy_webapp_settings(OFFLINE_ORG, port=free_loopback_port()),
        verified=None,
        image=webapp_image.tag,
        run_ctx=new_run_context(),
        scratch=offline_context.scratch / "offline-webapp",
        artifacts_dir=offline_context.artifacts_dir / "offline-webapp",
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
def injector(offline_stack: WebappStack) -> WebhookInjector:
    """WebhookInjector on the stack's receiver, signing with the stack's dummy webhook secret."""
    return WebhookInjector(offline_stack.webhook_url, offline_stack.settings.app.webhook_secret)


@pytest.fixture(scope="module")
def has_fix_775(offline_context: E2EContext, webapp_image: BuiltImage) -> bool | None:
    """Whether the webapp image contains #775 (ancestry of its revision in the upstream mirror; None: undecidable,
    e.g. a prebuilt image without revision label)."""
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


def delivery_id(case: str) -> str:
    """A unique X-GitHub-Delivery for one case (log lines are matched by it)."""
    return f"e2e-offline-{case}-{uuid.uuid4().hex[:12]}"


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


def shown(response: requests.Response) -> str:
    """Status and body excerpt of a response for assertion messages; a 5xx body is never shown (DEBUG pages)."""
    if response.status_code >= 500:
        return f"{response.status_code} (body not shown)"
    return f"{response.status_code} {response.text[:200]!r}"


def page_title(response: requests.Response) -> str:
    """The <title> text of an HTML page."""
    titles = parse_html(response.text).iter("title")
    return titles[0].text() if titles else ""


def get(stack: WebappStack, path: str) -> requests.Response:
    """GET ``path`` on the stack without following redirects (any status)."""
    return stack.api.session.get(stack.api.url(path), timeout=60, allow_redirects=False)


@pytest.mark.scenario("O-WEB-BOOT")
def test_webapp_boots_with_dummy_credentials(offline_stack: WebappStack, webapp_image: BuiltImage) -> None:
    """The stack is healthy and /index shows the version the SUT image was built with (images built by the harness
    declare it in their labels; a prebuilt --e2e-webapp-image without version label only has to show one)."""
    assert offline_stack.health(), "GET /internal/health is not 200"
    deployed = offline_stack.deployed_version()
    if not webapp_image.version:
        warnings.warn(f"{webapp_image.tag} has no version label: /index shows {deployed!r}", stacklevel=1)
        assert deployed, "the /index footer shows no 'OtterDog - v<version>'"
        return
    assert deployed == webapp_image.version, (
        f"/index shows version {deployed!r}, the image {webapp_image.tag} was built as {webapp_image.version!r}"
    )


def deliveries() -> list[tuple[str, str, Any, dict[str, Any], int]]:
    """(case, event, payload, injector options, expected status) of the receiver contract, in sending order."""
    ping = ping_payload()
    pull = synthetic_pull_request(OFFLINE_ORG, CONFIG_REPO, 1, head_ref="e2e/offline/contract", head_sha="1" * 40)
    unknown_installation = pull_request_payload(
        "opened", org=OFFLINE_ORG, repo=CONFIG_REPO, pull_request=pull, installation_id=UNKNOWN_INSTALLATION
    )
    return [
        ("missing signature", "ping", ping, {"signature": "missing"}, 400),
        ("invalid signature", "ping", ping, {"signature": "invalid"}, 400),
        ("sha256 signature only", "ping", ping, {"signature": "sha256-only"}, 400),
        ("json with a charset", "ping", ping, {"content_type": "application/json; charset=utf-8"}, 415),
        ("valid ping", "ping", ping, {}, 204),
        ("unknown event", "star", unknown_event_payload("star", org=OFFLINE_ORG), {}, 204),
        ("unknown installation", "pull_request", unknown_installation, {}, 204),
    ]


@pytest.mark.scenario("O-WEB-SIG")
def test_webhook_receiver_contract(offline_stack: WebappStack, injector: WebhookInjector) -> None:
    """Signature and content-type checks answer 400/400/400/415; accepted deliveries answer 204; the event of an
    unknown installation is parsed (no pydantic failure) and logged as such."""
    cases = deliveries()
    statuses = {
        case: injector.send(event, payload, **options).status_code for case, event, payload, options, _ in cases
    }
    assert statuses == {case: expected for case, _, _, _, expected in cases}

    def logged() -> bool:
        """True once the webapp logged the unknown installation."""
        return UNKNOWN_INSTALLATION_LOG in offline_stack.logs(tail=500)

    try:
        waiting.wait_until(logged, timeout=LOG_WAIT, interval=1.0, what="the unknown-installation log line")
    except waiting.WaitTimeoutError:
        pytest.fail(
            f"the webapp never logged {UNKNOWN_INSTALLATION_LOG!r}\n--- log tail ---\n{offline_stack.logs(tail=60)}",
            pytrace=False,
        )
    logs = offline_stack.logs()
    assert EVENT_LOAD_FAILURE_LOG not in logs, "the synthetic pull_request payload failed otterdog's pydantic model"


# --- O-WEB-SIG: rejections, content types, optional headers, replays ----------------------------------------------
@pytest.mark.scenario("O-WEB-SIG")
def test_rejections_name_what_is_wrong(
    offline_stack: WebappStack, injector: WebhookInjector, has_fix_775: bool | None
) -> None:
    """Every rejected delivery answers 400 or 415 with the reason in the body: the signature header and the event and
    content-type headers are required, the content type must be exact, the body must hold a JSON document. With #775
    the webapp logs the invalid signature, the unknown content type and the empty body with the delivery id."""
    ping = ping_payload()
    ids = {case: delivery_id(case) for case in ("invalid-signature", "charset", "plain-text", "null-body")}
    answers = {
        "missing signature": (injector.send("ping", ping, signature="missing"), 400, "Missing header: X-Hub-Signature"),
        "sha256 signature only": (
            injector.send("ping", ping, signature="sha256-only"),
            400,
            "Missing header: X-Hub-Signature",
        ),
        "invalid signature": (
            injector.send("ping", ping, signature="invalid", delivery_id=ids["invalid-signature"]),
            400,
            "Invalid signature",
        ),
        "missing event header": (injector.send(None, ping), 400, "Missing header: X-Github-Event"),
        "missing content type": (injector.send("ping", ping, content_type=None), 400, "Missing header: content-type"),
        "json with a charset": (
            injector.send("ping", ping, content_type="application/json; charset=utf-8", delivery_id=ids["charset"]),
            415,
            "Unknown content type application/json; charset=utf-8",
        ),
        "plain text": (
            injector.send("ping", ping, content_type="text/plain", delivery_id=ids["plain-text"]),
            415,
            "Unknown content type text/plain",
        ),
        "null body": (
            injector.deliver("ping", body=b"null", delivery_id=ids["null-body"]),
            400,
            "Request body must contain data",
        ),
        "undecodable json": (injector.deliver("ping", body=b"{not json"), 400, "Failed to decode JSON"),
    }
    problems = [
        f"{case}: {shown(response)}, expected {status} with {reason!r}"
        for case, (response, status, reason) in answers.items()
        if response.status_code != status or reason not in response.text
    ]
    assert not problems, "\n".join(problems)
    if not has_fix_775:
        return
    wait_logged(
        offline_stack,
        f"rejecting webhook delivery {ids['invalid-signature']}: invalid signature",
        f"rejecting webhook delivery {ids['charset']} for event 'ping': unknown content type "
        "'application/json; charset=utf-8'",
        f"rejecting webhook delivery {ids['plain-text']} for event 'ping': unknown content type 'text/plain'",
        f"rejecting webhook delivery {ids['null-body']} for event 'ping': empty body",
    )


@pytest.mark.scenario("O-WEB-SIG")
def test_form_encoded_delivery_is_processed(offline_stack: WebappStack, injector: WebhookInjector) -> None:
    """A hook configured with content type 'form' posts payload=<json>, signed over the encoded body: 204, and the
    ping is described in the log like a JSON one ('ping from <sender> (<delivery id>)')."""
    form_id = delivery_id("form")
    response = injector.send("ping", ping_payload(), content_type=FORM_CONTENT_TYPE, delivery_id=form_id)
    assert response.status_code == 204, shown(response)
    sent = injector.last("ping")
    assert sent is not None and sent.body.startswith(b"payload=%7B"), "the body was not form-encoded"
    wait_logged(offline_stack, f"ping from {SENDER} ({form_id})")


@pytest.mark.scenario("O-KB-WEB-FORM-WITHOUT-PAYLOAD")
@pytest.mark.known_bug("KB-060")
def test_form_delivery_without_payload_is_rejected(injector: WebhookInjector) -> None:
    """A correctly signed form body without the 'payload' field is a malformed delivery: 400, never a 500."""
    response = injector.deliver("ping", body=b"other=1", content_type=FORM_CONTENT_TYPE)
    assert response.status_code == 400, f"answered {response.status_code} (body not shown)"


@pytest.mark.scenario("O-WEB-SIG")
def test_optional_headers(offline_stack: WebappStack, injector: WebhookInjector, has_fix_775: bool | None) -> None:
    """The receiver ignores User-Agent (a delivery without it is accepted, 204). X-GitHub-Delivery is optional with
    #775 (204, described with '(None)'); older SUTs read it as a required header (400 'Missing header:
    X-Github-Delivery')."""
    agent_id = delivery_id("no-user-agent")
    no_agent = injector.deliver("ping", ping_payload(), delivery_id=agent_id, omit_headers=("User-Agent",))
    assert no_agent.status_code == 204, shown(no_agent)
    wait_logged(offline_stack, f"ping from {SENDER} ({agent_id})")
    no_id = injector.deliver("ping", ping_payload(), omit_headers=("X-GitHub-Delivery",))
    if has_fix_775 is None:
        assert no_id.status_code in (204, 400), no_id.status_code
    elif has_fix_775:
        assert no_id.status_code == 204, shown(no_id)
        wait_logged(offline_stack, f"ping from {SENDER} (None)")
    else:
        assert no_id.status_code == 400 and "Missing header: X-Github-Delivery" in no_id.text, shown(no_id)


@pytest.mark.scenario("O-WEB-SIG")
def test_replayed_delivery_is_processed_again(offline_stack: WebappStack, injector: WebhookInjector) -> None:
    """A GitHub redelivery (the same bytes, headers and X-GitHub-Delivery) is accepted again (204) and processed
    again: otterdog does not deduplicate deliveries, the description is logged twice."""
    replayed = delivery_id("replay")
    first = injector.send("ping", ping_payload(), delivery_id=replayed)
    again = injector.replay(replayed)
    assert (first.status_code, again.status_code) == (204, 204)
    sent = injector.sent[-2:]
    assert sent[0].body == sent[1].body and sent[1].replay_of == replayed
    line = f"ping from {SENDER} ({replayed})"

    def twice() -> bool:
        """True once the description was logged for both deliveries."""
        return offline_stack.logs().count(line) >= 2

    try:
        waiting.wait_until(twice, timeout=LOG_WAIT, interval=1.0, what="the replayed delivery's description twice")
    except waiting.WaitTimeoutError:
        pytest.fail(f"{line!r} was not logged twice\n--- log tail ---\n{offline_stack.logs(tail=40)}", pytrace=False)


# --- O-WEB-SIG: event descriptions (receiver.event-logging, #775) -------------------------------------------------
@pytest.mark.scenario("O-WEB-SIG")
def test_workflow_events_are_described_selectively(offline_stack: WebappStack, injector: WebhookInjector) -> None:
    """Every workflow_job and workflow_run delivery is accepted (204), but only a queued job and a completed run are
    described in the log ('workflow '<name>' on '<labels>' queued in repository <repo>' / 'workflow '<name>'
    completed in repository <repo>'), in_progress jobs and requested runs are not."""
    installation = stable_id("otterdog-e2e offline: workflow events", base=900_000_000)
    ids = {case: delivery_id(case) for case in ("job-in-progress", "job-queued", "run-requested", "run-completed")}
    job = {"org": OFFLINE_ORG, "repo": EVENT_REPO, "run_id": 4242, "installation_id": installation}
    statuses = [
        injector.send("workflow_job", workflow_job_payload("in_progress", **job), delivery_id=ids["job-in-progress"]),
        injector.send("workflow_run", workflow_run_payload("requested", **job), delivery_id=ids["run-requested"]),
        injector.send("workflow_job", workflow_job_payload("queued", **job), delivery_id=ids["job-queued"]),
        injector.send("workflow_run", workflow_run_payload("completed", **job), delivery_id=ids["run-completed"]),
    ]
    assert [response.status_code for response in statuses] == [204] * 4
    full_name = f"{OFFLINE_ORG}/{EVENT_REPO}"
    logs = wait_logged(
        offline_stack,
        f"workflow 'e2e' on '['ubuntu-latest']' queued in repository {full_name} ({ids['job-queued']})",
        f"workflow 'e2e' completed in repository {full_name} ({ids['run-completed']})",
    )
    # the queued/completed lines were sent last: the earlier deliveries would be logged by now
    assert ids["job-in-progress"] not in logs and ids["run-requested"] not in logs, "a filtered event was described"


@pytest.mark.scenario("O-WEB-SIG")
def test_unformattable_events_are_still_processed(
    offline_stack: WebappStack, injector: WebhookInjector, has_fix_775: bool | None
) -> None:
    """A push whose 'pusher' (used by its description) is missing is accepted and processed on every SUT. A push
    whose 'pusher' is null breaks the description with a TypeError: since #775 the webapp warns ('could not format
    webhook delivery <id> for event 'push' (TypeError ...)' with the null fields), describes it as 'push (<id>)' and
    processes it (204, the push hook reports the unknown installation); older SUTs answer 500 and drop the event."""
    missing_installation = stable_id("otterdog-e2e offline: push without pusher", base=900_000_000)
    null_installation = stable_id("otterdog-e2e offline: push with null pusher", base=900_000_000)
    missing = push_payload(
        org=OFFLINE_ORG, repo=EVENT_REPO, ref="refs/heads/main", after="3" * 40, installation_id=missing_installation
    )
    del missing["pusher"]
    missing_id = delivery_id("push-missing-pusher")
    answer = injector.send("push", missing, delivery_id=missing_id)
    assert answer.status_code == 204, f"{answer.status_code} (body not shown)"
    wait_logged(
        offline_stack, f"push ({missing_id})", f"received event for unknown installation '{missing_installation}'"
    )

    null = push_payload(
        org=OFFLINE_ORG, repo=EVENT_REPO, ref="refs/heads/main", after="2" * 40, installation_id=null_installation
    )
    null["pusher"] = None
    null_id = delivery_id("push-null-pusher")
    answer = injector.send("push", null, delivery_id=null_id)
    processed = f"received event for unknown installation '{null_installation}'"
    if has_fix_775 is None:
        assert answer.status_code in (204, 500), answer.status_code
        return
    if not has_fix_775:
        assert answer.status_code == 500, f"a SUT without #775 answered {answer.status_code}"
        # hooks run inside the request: once a later ping is logged, a processed push would be logged too
        barrier = delivery_id("barrier")
        assert injector.send("ping", ping_payload(), delivery_id=barrier).status_code == 204
        logs = wait_logged(offline_stack, f"ping from {SENDER} ({barrier})")
        assert processed not in logs, "a SUT without #775 processed the event"
        return
    assert answer.status_code == 204, f"answered {answer.status_code} (body not shown)"
    logs = wait_logged(
        offline_stack,
        f"could not format webhook delivery {null_id} for event 'push' (TypeError",
        f"push ({null_id})",
        processed,
    )
    warning = next(line for line in logs.splitlines() if f"could not format webhook delivery {null_id}" in line)
    assert f"repository='{OFFLINE_ORG}/{EVENT_REPO}'" in warning and "'pusher'" in warning, warning


# --- O-WEB-ROUTES: pages and endpoints without installation ----------------------------------------------------
@pytest.mark.scenario("O-WEB-ROUTES")
@pytest.mark.parametrize(
    ("path", "location"),
    [
        pytest.param("/", "/index", id="root"),
        pytest.param("/tasks.html", "/admin/tasks", id="template-name"),
        pytest.param("/allprojects.html", "/allprojects", id="html-suffix"),
    ],
)
def test_redirects(offline_stack: WebappStack, path: str, location: str) -> None:
    """/ redirects to /index; /<name>[.html] redirects to the page of the endpoint <name>."""
    response = get(offline_stack, path)
    assert response.status_code == 302, f"GET {path}: {response.status_code}"
    assert response.headers.get("location", "").endswith(location), response.headers.get("location")


@pytest.mark.scenario("O-WEB-ROUTES")
@pytest.mark.parametrize(
    ("path", "title", "needle"),
    [
        pytest.param("/index", "Dashboard", "OtterDog - v", id="index"),
        pytest.param("/allprojects", "Dashboard", "All Projects", id="allprojects"),
        pytest.param("/scorecard/checks", "OSSF Scorecard Checks", "OSSF Scorecard", id="scorecard-checks"),
        pytest.param("/query", "Dashboard", "projects(filter: String): [Project]!", id="query"),
        pytest.param(
            "/admin/organizations", "GitHub Organizations", "List of GitHub organizations", id="organizations"
        ),
        pytest.param("/admin/pullrequests", "Pull Requests", "Pull Requests", id="pullrequests"),
        pytest.param("/admin/blueprints", "Blueprints", "Blueprints", id="blueprints"),
        pytest.param("/admin/policies", "Policies", "Policies", id="policies"),
        pytest.param("/admin/tasks", "Executed Tasks", "Executed Tasks", id="tasks"),
    ],
)
def test_pages_need_no_login(offline_stack: WebappStack, path: str, title: str, needle: str) -> None:
    """The dashboard pages and the five admin pages render without a session (200, their title): their data comes
    from the database (empty here) and the unauthenticated /api endpoints."""
    response = get(offline_stack, path)
    assert response.status_code == 200, f"GET {path}: {response.status_code}"
    assert page_title(response) == f"Otterdog Dashboard - {title} | Eclipse Foundation", page_title(response)
    assert needle in response.text, f"GET {path} lacks {needle!r}"


@pytest.mark.scenario("O-WEB-ROUTES")
def test_admin_pages_of_an_empty_database(offline_stack: WebappStack) -> None:
    """Without installations /admin/organizations lists no organization and /admin/policies no policy status."""
    assert offline_stack.api.installations() == {}
    assert offline_stack.api.policy_status() == {}


@pytest.mark.scenario("O-WEB-ROUTES")
def test_static_files(offline_stack: WebappStack) -> None:
    """/robots.txt (crawlers disallowed) and /favicon.ico are served from the static assets."""
    robots = get(offline_stack, "/robots.txt")
    assert robots.status_code == 200 and robots.headers.get("content-type", "").startswith("text/plain")
    assert robots.text.splitlines() == ["User-agent: *", "Disallow: /"], robots.text
    icon = get(offline_stack, "/favicon.ico")
    assert icon.status_code == 200 and icon.headers.get("content-type") == "image/vnd.microsoft.icon"
    assert icon.content[:4] == b"\x00\x00\x01\x00", "not an ICO file"


@pytest.mark.scenario("O-WEB-ROUTES")
@pytest.mark.parametrize(
    "path",
    [
        pytest.param("/e2e-no-such-page", id="unknown-page"),
        pytest.param(f"/organizations/{UNKNOWN_PROJECT}", id="unknown-organization"),
        pytest.param(f"/projects/{UNKNOWN_PROJECT}", id="unknown-project"),
        pytest.param(f"/projects/{UNKNOWN_PROJECT}/repos/e2e-x", id="unknown-repository"),
    ],
)
def test_not_found_page(offline_stack: WebappStack, path: str) -> None:
    """An unknown page and the pages of an unknown organization, project or repository answer the 404 page."""
    response = get(offline_stack, path)
    assert response.status_code == 404, f"GET {path}: {response.status_code}"
    assert "Error 404 - Page not found" in response.text and page_title(response).startswith(
        "Otterdog Dashboard - Error 404"
    ), page_title(response)


@pytest.mark.scenario("O-KB-WEB-LOGIN-REQUIRED")
@pytest.mark.known_bug("KB-059")
def test_login_required_page_without_session(offline_stack: WebappStack) -> None:
    """/myprojects needs a GitHub OAuth session: a request without cookies gets the 401 page."""
    response = get(offline_stack, "/myprojects")
    assert response.status_code == 401, f"GET /myprojects: {response.status_code} (body not shown)"
    assert "Error 401 - Access Denied" in response.text


@pytest.mark.scenario("O-WEB-ROUTES")
@pytest.mark.parametrize(
    ("path", "status", "body"),
    [
        pytest.param("/internal/health", 200, {}, id="health"),
        pytest.param("/internal/e2e-nope", 404, {}, id="internal-unknown"),
        pytest.param("/internal/check", 200, {}, id="check-without-blueprints"),
        pytest.param("/api/organizations", 200, [], id="organizations"),
        pytest.param(f"/api/organizations/{UNKNOWN_PROJECT}", 404, {}, id="unknown-organization"),
        pytest.param(f"/api/projects/{UNKNOWN_PROJECT}", 404, {}, id="unknown-project"),
        pytest.param("/api/tasks", 200, EMPTY_PAGE, id="tasks"),
        pytest.param("/api/pullrequests/open", 200, EMPTY_PAGE, id="open-pull-requests"),
        pytest.param("/api/pullrequests/merged", 200, EMPTY_PAGE, id="merged-pull-requests"),
        pytest.param("/api/blueprints/remediations", 200, EMPTY_PAGE, id="remediations"),
        pytest.param("/api/blueprints/dismissed", 200, EMPTY_PAGE, id="dismissed"),
        pytest.param("/api/scorecard/results", 200, EMPTY_PAGE, id="scorecard-results"),
    ],
)
def test_json_endpoints(offline_stack: WebappStack, path: str, status: int, body: Any) -> None:
    """/internal and /api answer JSON: health and an empty blueprint check {}, an unknown /internal path 404 {}, the
    listings of an empty database, 404 {} for an unknown organization or project."""
    response = get(offline_stack, path)
    assert response.status_code == status, f"GET {path}: {shown(response)}"
    assert response.headers.get("content-type", "").startswith("application/json"), response.headers
    assert response.json() == body, shown(response)


@pytest.mark.scenario("O-WEB-ROUTES")
def test_graphql_api(offline_stack: WebappStack) -> None:
    """GET /api/graphql serves the GraphQL explorer; POST runs queries over the stored configurations: the schema
    introspection and the (empty) projects list answer 200, an unknown field 400 with its error."""
    explorer = get(offline_stack, "/api/graphql")
    assert explorer.status_code == 200 and "Otterdog GraphQL" in explorer.text, explorer.status_code
    status, result = offline_stack.api.graphql("{ __schema { queryType { name } } }")
    assert (status, result) == (200, {"data": {"__schema": {"queryType": {"name": "Query"}}}}), result
    status, result = offline_stack.api.graphql("{ projects { github_id project_name } }")
    assert (status, result) == (200, {"data": {"projects": []}}), result
    status, result = offline_stack.api.graphql("{ nope }")
    assert status == 400 and [error["message"] for error in result["errors"]] == [
        "Cannot query field 'nope' on type 'Query'."
    ], result


@pytest.mark.scenario("O-WEB-ROUTES")
@pytest.mark.parametrize(
    ("interval", "range_", "error"),
    [
        pytest.param("year", "12m", "unsupported interval 'year'", id="interval"),
        pytest.param("month", "2y", "unsupported range '2y'", id="range"),
        pytest.param("year", "2y", "unsupported interval 'year'", id="interval-first"),
    ],
)
def test_statistics_parameters(offline_stack: WebappStack, interval: str, range_: str, error: str) -> None:
    """The pull request statistics accept interval day|week|month and range 7d|14d|30d|90d|6m|12m|all: other values
    answer 400 {"error": ...} before any job starts (the interval is checked first)."""
    status, answer = offline_stack.api.statistics_progress(interval=interval, range_=range_)
    assert (status, answer) == (400, {"error": error}), answer
