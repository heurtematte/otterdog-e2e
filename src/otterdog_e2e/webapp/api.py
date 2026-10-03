"""Client of the webapp's unauthenticated /api endpoints (SPEC 13.2, OC-07) and helpers for local endpoints.

Facts (otterdog/webapp/api/routes.py, db/service.py): /api/organizations lists [{github_id, project_name}] (rows are
created from otterdog.json even while the App is NOT_INSTALLED); /api/organizations/<id> is 404 until a FetchConfigTask
stored the config; /api/tasks treats every TaskModel field as a ``$regex`` filter (pull_request is an int and cannot be
filtered server-side) next to pageIndex/pageSize/sortField/sortOrder; /api/pullrequests/open|merged only accept the
``id[org_id]``/``id[repo_name]`` keys (any other field key raises KeyError -> HTTP 500); merged = status merged AND
apply_status completed, open = open + merged-not-completed; every timestamp is a naive UTC ISO string.

Blueprints and policies (api/routes.py, db/service.py, home/routes.py): /api/blueprints/remediations and
/api/blueprints/dismissed list blueprint_status rows with status remediation_prepared / dismissed only (filters
``id[org_id]``, ``id[repo_name]``, ``id[blueprint_id]`` as $regex, pageSize default 20); every other status (success,
failure, recheck, not_checked) is only rendered by /projects/<project_name> (tab ``blueprint-<id>``, a Status table of
Repository / Updated At / Status (the enum NAME) / Remediation PR), policy counters only by /admin/policies (one card
per policy type, headers in "Normal Case"), installation statuses only by /admin/organizations (table
``organizations``); the page parsers below read exactly these. /internal/check[/<limit>] evaluates due blueprints and
answers once their tasks are scheduled; /internal/<other> answers 404 ``{}``.
"""

from __future__ import annotations

import ipaddress
import logging
import re
import time
import urllib.parse
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from typing import Any

import requests

from otterdog_e2e import waiting
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError

_logger = logging.getLogger(__name__)

TASK_STATUSES_FINAL = ("finished", "failed")
TASK_STATUSES_ACTIVE = ("created", "scheduled")  # TaskStatus values of tasks that are pending or running
LOOPBACK_NAMES = frozenset({"localhost", "localhost.localdomain"})
DEFAULT_PAGE_SIZE = 100
MAX_PAGES = 20
INIT_TIMEOUT = 180.0  # /internal/init reloads otterdog.json and lists the App installations synchronously
VERSION_RE = re.compile(r"OtterDog - v([^<\s]+)")  # footer of GET /index (templates/includes/footer.html)
BLUEPRINT_PAGE_SIZE = 100
STATISTICS_INTERVALS = ("day", "week", "month")
STATISTICS_RANGES = ("7d", "14d", "30d", "90d", "6m", "12m", "all")
# void elements of HTML: never closed, never parents
_VOID_TAGS = frozenset(
    {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}
)
# start tags that implicitly close an open element of these tags (HTML's optional end tags)
_IMPLIED_CLOSE: dict[str, frozenset[str]] = {
    "td": frozenset({"td", "th"}),
    "th": frozenset({"td", "th"}),
    "tr": frozenset({"tr", "td", "th"}),
    "li": frozenset({"li"}),
    "option": frozenset({"option"}),
}
_WS_RE = re.compile(r"\s+")


class WebappApiError(RuntimeError):
    """A webapp endpoint answered with an unexpected status (url and body are redacted)."""

    def __init__(self, method: str, url: str, status: int, body: str = "") -> None:
        """Store the redacted request/response details."""
        self.method = method
        self.url = REDACTOR(url)
        self.status = status
        self.body = REDACTOR(body)
        super().__init__(f"{method} {self.url} -> HTTP {status}: {self.body[:300]}")


class RemoteEndpointError(SafetyError, ValueError):
    """A local-only endpoint (external webapp, relay target) is not on a loopback address."""


# --- HTML pages ----------------------------------------------------------------------------------------------------
@dataclass
class HtmlNode:
    """One element of a parsed page: tag, attributes, children and direct text."""

    tag: str
    attrs: dict[str, str] = field(default_factory=dict)
    children: list[HtmlNode] = field(default_factory=list)
    texts: list[str] = field(default_factory=list)

    def text(self) -> str:
        """Whitespace-normalized text content (descendants included)."""
        parts: list[str] = []
        self._collect(parts)
        return _WS_RE.sub(" ", " ".join(parts)).strip()

    def _collect(self, parts: list[str]) -> None:
        """Append the texts of this node and its descendants (document order is approximate: own texts first)."""
        parts.extend(self.texts)
        for child in self.children:
            child._collect(parts)

    def iter(self, tag: str | None = None) -> list[HtmlNode]:
        """Descendants (self included) with ``tag`` (every element without one), in document order."""
        found = [self] if tag is None or self.tag == tag else []
        for child in self.children:
            found.extend(child.iter(tag))
        return found

    def find_id(self, element_id: str) -> HtmlNode | None:
        """The first descendant (or self) whose id is ``element_id``."""
        return next((node for node in self.iter() if node.attrs.get("id") == element_id), None)

    def has_class(self, name: str) -> bool:
        """True when ``name`` is one of the element's classes."""
        return name in self.attrs.get("class", "").split()


class _TreeBuilder(HTMLParser):
    """Tolerant HTMLParser building an HtmlNode tree (void elements, unclosed tags and stray end tags)."""

    def __init__(self) -> None:
        """An empty document."""
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document")
        self._stack = [self.root]
        self._skip = 0  # inside <script>/<style>: no text

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """Open an element (void elements are leaves; a cell, row or list item closes the open one)."""
        closes = _IMPLIED_CLOSE.get(tag, frozenset())
        while len(self._stack) > 1 and self._stack[-1].tag in closes:
            self._stack.pop()
        node = HtmlNode(tag, {key: value or "" for key, value in attrs})
        self._stack[-1].children.append(node)
        if tag in ("script", "style"):
            self._skip += 1
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        """A self-closing element is a leaf."""
        self._stack[-1].children.append(HtmlNode(tag, {key: value or "" for key, value in attrs}))

    def handle_endtag(self, tag: str) -> None:
        """Close up to the innermost open element with ``tag`` (stray end tags are ignored)."""
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        """Text of the current element (script and style contents are dropped)."""
        if not self._skip and data.strip():
            self._stack[-1].texts.append(data)


def parse_html(text: str) -> HtmlNode:
    """The HtmlNode tree of a page."""
    builder = _TreeBuilder()
    builder.feed(text)
    builder.close()
    return builder.root


def table_rows(table: HtmlNode) -> tuple[list[str], list[list[str]]]:
    """(header texts, body rows of cell texts) of a <table> (thead/th headers, tbody/td cells)."""
    headers = [cell.text() for cell in table.iter("th")]
    rows = []
    for row in table.iter("tr"):
        cells = [cell.text() for cell in row.children if cell.tag == "td"]
        if cells:
            rows.append(cells)
    return headers, rows


def snake_key(header: str) -> str:
    """``snake_case`` of a "Normal Case" header (otterdog's snake_to_normal filter reversed)."""
    return re.sub(r"[^a-z0-9]+", "_", header.lower()).strip("_")


def parse_installations(page: str) -> dict[str, dict[str, Any]]:
    """/admin/organizations: github_id -> {installation_id, status (installed|not_installed|suspended), project_name}."""
    table = parse_html(page).find_id("organizations")
    if table is None:
        raise WebappApiError("GET", "/admin/organizations", 200, "no table#organizations in the page")
    installations: dict[str, dict[str, Any]] = {}
    for cells in table_rows(table)[1]:
        if len(cells) < 4:
            continue
        installation_id = int(cells[0]) if cells[0].isdigit() else None
        installations[cells[3]] = {
            "installation_id": installation_id,
            "status": cells[1].strip().lower(),
            "project_name": cells[2],
        }
    return installations


def parse_policy_status(page: str) -> dict[str, dict[str, int]]:
    """/admin/policies: policy type -> {counter (snake_case): value} (the counters of every org, summed)."""
    statuses: dict[str, dict[str, int]] = {}
    for card in parse_html(page).iter("div"):
        if not card.has_class("card"):
            continue
        titles = [node for node in card.iter("h3") if node.has_class("card-title")]
        tables = card.iter("table")
        if not titles or not tables:
            continue
        headers, rows = table_rows(tables[0])
        if not rows:
            continue
        values = {}
        for header, cell in zip(headers, rows[0], strict=False):
            try:
                values[snake_key(header)] = int(cell)
            except ValueError:
                continue
        statuses[titles[0].text()] = values
    return statuses


def parse_blueprint_statuses(page: str, blueprint_id: str) -> dict[str, dict[str, Any]] | None:
    """/projects/<project>: repo -> {status (lower-case value), updated_at, remediation_pr} of the blueprint's Status
    table; None when the page has no tab for the blueprint (unknown to the webapp)."""
    pane = parse_html(page).find_id(f"blueprint-{blueprint_id}")
    if pane is None:
        return None
    statuses: dict[str, dict[str, Any]] = {}
    for table in pane.iter("table"):
        headers, rows = table_rows(table)
        if [snake_key(header) for header in headers][:3] != ["repository", "updated_at", "status"]:
            continue
        for cells in rows:
            if len(cells) < 4:
                continue
            pr_text = cells[3].lstrip("#")
            statuses[cells[0]] = {
                "status": cells[2].strip().lower(),
                "updated_at": cells[1],
                "remediation_pr": int(pr_text) if pr_text.isdigit() else None,
            }
    return statuses


def local_session(session: requests.Session | None = None) -> requests.Session:
    """A requests session for local endpoints: trust_env False (no proxy variables, no ~/.netrc)."""
    session = session if session is not None else requests.Session()
    session.trust_env = False
    return session


def is_loopback_url(url: str) -> bool:
    """True for http(s) URLs whose host is localhost or a loopback address (127.0.0.0/8, ::1)."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return False
    if parts.hostname.lower() in LOOPBACK_NAMES:
        return True
    try:
        return ipaddress.ip_address(parts.hostname).is_loopback
    except ValueError:
        return False


def require_loopback_url(url: str, *, allow_remote: bool = False, what: str = "URL") -> None:
    """RemoteEndpointError unless ``url`` is an http(s) URL on a loopback host (any http(s) URL with allow_remote)."""
    scheme = urllib.parse.urlsplit(url).scheme
    if scheme not in ("http", "https"):
        raise RemoteEndpointError(f"{what} must be an http(s) URL, got {REDACTOR(url)!r}")
    if not allow_remote and not is_loopback_url(url):
        raise RemoteEndpointError(
            f"{what} {REDACTOR(url)!r} is not a loopback address (127.0.0.1/localhost); "
            "use --e2e-allow-remote-webapp / --allow-remote to allow it explicitly"
        )


def anchored(value: str) -> str:
    """Exact-match regex for the webapp's ``$regex`` query filters: ``^<escaped value>$``."""
    return f"^{re.escape(value)}$"


def as_utc(value: datetime) -> datetime:
    """``value`` as an aware UTC datetime (naive values are taken as UTC)."""
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def parse_timestamp(value: Any) -> datetime | None:
    """Aware UTC datetime of a webapp (naive ISO) or GitHub (``Z``) timestamp; None when absent or unparsable."""
    if isinstance(value, datetime):
        return as_utc(value)
    if not isinstance(value, str) or not value:
        return None
    try:
        return as_utc(datetime.fromisoformat(value))
    except ValueError:
        return None


def floor_to_millis(value: datetime) -> datetime:
    """Truncate to milliseconds (MongoDB stores datetimes with millisecond precision)."""
    return value.replace(microsecond=value.microsecond // 1000 * 1000)


class WebappApi:
    """Thin requests client (trust_env False) of /internal/health, /internal/init, /index and /api/*."""

    def __init__(self, base_url: str, *, timeout: float = 30.0, session: requests.Session | None = None) -> None:
        """Bind the base URL; a session gets trust_env = False."""
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = local_session(session)
        self.sleep: Callable[[float], None] = time.sleep  # injectable for tests
        self.clock: Callable[[], float] = time.monotonic

    # --- plumbing -------------------------------------------------------------------------------------------------
    def url(self, path: str) -> str:
        """Absolute URL of ``path`` (which starts with '/')."""
        return f"{self.base_url}{path}"

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        allow: Sequence[int] = (200,),
        timeout: float | None = None,
    ) -> requests.Response:
        """GET ``path`` (no redirects); WebappApiError unless the status is in ``allow``."""
        response = self.session.get(
            self.url(path), params=params, timeout=timeout or self.timeout, allow_redirects=False
        )
        if response.status_code not in allow:
            raise WebappApiError("GET", response.url or self.url(path), response.status_code, response.text)
        return response

    def _json(self, path: str, params: Mapping[str, Any] | None = None) -> Any:
        """Decoded JSON of a 200 answer."""
        return self.get(path, params=params).json()

    def post(
        self,
        path: str,
        *,
        json_body: Any = None,
        allow: Sequence[int] = (200,),
        timeout: float | None = None,
    ) -> requests.Response:
        """POST a JSON document to ``path`` (no redirects); WebappApiError unless the status is in ``allow``."""
        response = self.session.post(
            self.url(path), json=json_body, timeout=timeout or self.timeout, allow_redirects=False
        )
        if response.status_code not in allow:
            raise WebappApiError("POST", response.url or self.url(path), response.status_code, response.text)
        return response

    # --- internal endpoints ---------------------------------------------------------------------------------------
    def health(self) -> bool:
        """GET /internal/health == 200 (connection errors count as unhealthy)."""
        try:
            response = self.session.get(self.url("/internal/health"), timeout=self.timeout, allow_redirects=False)
        except requests.RequestException:
            return False
        return response.status_code == 200

    def init(self, *, timeout: float = INIT_TIMEOUT) -> None:
        """GET /internal/init (reload otterdog.json, policies, blueprints and installations); WebappApiError unless 200."""
        self.get("/internal/init", timeout=timeout)

    def check(self, limit: int | None = None, *, timeout: float = INIT_TIMEOUT) -> None:
        """GET /internal/check (or /internal/check/<limit>): evaluate the blueprints whose last check is older than
        BLUEPRINT_CHECK_INTERVAL (0 in the e2e stack); answers once their tasks are scheduled."""
        if limit is not None and (isinstance(limit, bool) or int(limit) < 0):
            raise ValueError(f"invalid blueprint check limit {limit!r}")
        self.get("/internal/check" if limit is None else f"/internal/check/{int(limit)}", timeout=timeout)

    def deployed_version(self) -> str | None:
        """Version in the footer of GET /index (VERSION_RE), None when absent (e.g. 'OtterDog dev')."""
        match = VERSION_RE.search(self.get("/index").text)
        return match.group(1) if match else None

    # --- projects -------------------------------------------------------------------------------------------------
    def project_name(self, github_id: str) -> str | None:
        """project_name of an organization listed by /api/organizations (exact github_id), None when absent."""
        for row in self.organizations():
            if row.get("github_id") == github_id:
                return str(row.get("project_name")) if row.get("project_name") else None
        return None

    def project(self, project_name: str) -> dict[str, Any] | None:
        """GET /api/projects/<project_name>: the stored configuration (None on 404)."""
        response = self.get(f"/api/projects/{urllib.parse.quote(project_name, safe='')}", allow=(200, 404))
        return None if response.status_code == 404 else response.json()

    # --- blueprints and scorecard ---------------------------------------------------------------------------------
    def _paged(self, path: str, filters: Mapping[str, str | None]) -> list[dict[str, Any]]:
        """Every page of a blueprint/scorecard listing with anchored id[...] filters."""
        params = {key: anchored(value) for key, value in filters.items() if value}
        records: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = self._json(path, {**params, "pageSize": BLUEPRINT_PAGE_SIZE, "pageIndex": page}) or {}
            data = list(body.get("data") or [])
            records.extend(data)
            if len(data) < BLUEPRINT_PAGE_SIZE or len(records) >= int(body.get("itemsCount") or 0):
                break
        return records

    def blueprint_remediations(
        self, *, org_id: str | None = None, repo_name: str | None = None, blueprint_id: str | None = None
    ) -> list[dict[str, Any]]:
        """GET /api/blueprints/remediations: blueprint_status rows with status remediation_prepared
        ({id: {org_id, repo_name, blueprint_id}, updated_at, status, remediation_pr})."""
        filters = {"id[org_id]": org_id, "id[repo_name]": repo_name, "id[blueprint_id]": blueprint_id}
        return self._paged("/api/blueprints/remediations", filters)

    def dismissed_blueprints(
        self, *, org_id: str | None = None, repo_name: str | None = None, blueprint_id: str | None = None
    ) -> list[dict[str, Any]]:
        """GET /api/blueprints/dismissed: blueprint_status rows with status dismissed."""
        filters = {"id[org_id]": org_id, "id[repo_name]": repo_name, "id[blueprint_id]": blueprint_id}
        return self._paged("/api/blueprints/dismissed", filters)

    def scorecard_results(self, *, org_id: str | None = None, repo_name: str | None = None) -> list[dict[str, Any]]:
        """GET /api/scorecard/results: stored scorecard results (each check score also as a top-level key)."""
        return self._paged("/api/scorecard/results", {"id[org_id]": org_id, "id[repo_name]": repo_name})

    def blueprint_statuses(self, project_name: str, blueprint_id: str) -> dict[str, dict[str, Any]] | None:
        """Statuses of one blueprint per repository, read from /projects/<project_name> (parse_blueprint_statuses);
        None when the webapp does not know the blueprint or the project."""
        response = self.get(f"/projects/{urllib.parse.quote(project_name, safe='')}", allow=(200, 404))
        if response.status_code == 404:
            return None
        return parse_blueprint_statuses(response.text, blueprint_id)

    # --- admin pages ----------------------------------------------------------------------------------------------
    def installations(self) -> dict[str, dict[str, Any]]:
        """/admin/organizations: github_id -> {installation_id, status, project_name} (parse_installations)."""
        return parse_installations(self.get("/admin/organizations").text)

    def policy_status(self) -> dict[str, dict[str, int]]:
        """/admin/policies: policy type -> counters summed over the orgs (parse_policy_status)."""
        return parse_policy_status(self.get("/admin/policies").text)

    # --- GraphQL and statistics -----------------------------------------------------------------------------------
    def graphql(self, query: str, variables: Mapping[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        """POST /api/graphql (queries over the stored configurations): (status 200 or 400, decoded result)."""
        document: dict[str, Any] = {"query": query}
        if variables:
            document["variables"] = dict(variables)
        response = self.post("/api/graphql", json_body=document, allow=(200, 400))
        return response.status_code, dict(response.json() or {})

    def statistics_progress(
        self, *, interval: str = "month", range_: str = "12m", org: str | None = None
    ) -> tuple[int, dict[str, Any]]:
        """GET /api/pullrequests/statistics/progress (a background job polled by the caller): (status 200 or 400,
        decoded answer); unsupported values are sent as given (400 {"error": ...})."""
        params = {"interval": interval, "range": range_, **({"org": org} if org else {})}
        response = self.get("/api/pullrequests/statistics/progress", params=params, allow=(200, 400))
        return response.status_code, dict(response.json() or {})

    # --- organizations --------------------------------------------------------------------------------------------
    def organizations(self) -> list[dict[str, Any]]:
        """GET /api/organizations."""
        return list(self._json("/api/organizations") or [])

    def organization(self, github_id: str) -> dict[str, Any] | None:
        """GET /api/organizations/<github_id> (None on 404)."""
        response = self.get(f"/api/organizations/{urllib.parse.quote(github_id, safe='')}", allow=(200, 404))
        return None if response.status_code == 404 else response.json()

    # --- tasks ----------------------------------------------------------------------------------------------------
    def _tasks(self, filters: Mapping[str, str], page_size: int) -> list[dict[str, Any]]:
        """One page of /api/tasks, newest first, with raw regex filters."""
        params = {"pageSize": page_size, "pageIndex": 1, "sortField": "created_at", "sortOrder": "desc", **filters}
        return list((self._json("/api/tasks", params) or {}).get("data") or [])

    def tasks(
        self,
        *,
        org_id: str | None = None,
        type_: str | None = None,
        repo_name: str | None = None,
        status: str | None = None,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """GET /api/tasks with anchored-regex filters (type, org_id, repo_name, status), newest first."""
        given = {"type": type_, "org_id": org_id, "repo_name": repo_name, "status": status}
        return self._tasks({key: anchored(value) for key, value in given.items() if value is not None}, page_size)

    def active_tasks(self, *, org_id: str, page_size: int = 100) -> list[dict[str, Any]]:
        """Tasks of the org that are pending or running (status created or scheduled)."""
        statuses = "|".join(re.escape(status) for status in TASK_STATUSES_ACTIVE)
        return self._tasks({"org_id": anchored(org_id), "status": f"^({statuses})$"}, page_size)

    def wait_task(
        self,
        *,
        type_: str,
        org_id: str,
        after: datetime,
        repo_name: str | None = None,
        pull_request: int | None = None,
        statuses: Sequence[str] = TASK_STATUSES_FINAL,
        timeout: float = 300,
        interval: float = 5,
    ) -> dict[str, Any]:
        """Newest task of ``type_`` created after ``after`` (pull_request filtered client-side), once its status is in
        ``statuses``; waiting.WaitTimeoutError after ``timeout``."""
        floor = floor_to_millis(as_utc(after))

        def newest() -> dict[str, Any] | None:
            """Newest matching task, or None."""
            for task in self.tasks(org_id=org_id, type_=type_, repo_name=repo_name):
                created = parse_timestamp(task.get("created_at"))
                if created is None or created < floor:
                    continue
                if pull_request is not None and task.get("pull_request") != pull_request:
                    continue
                return task
            return None

        found: dict[str, Any] | None = waiting.poll(
            newest,
            until=lambda task: task is not None and task.get("status") in statuses,
            timeout=timeout,
            interval=interval,
            what=f"webapp task {type_} of {org_id} (pull request {pull_request}) in {tuple(statuses)}",
            sleep=self.sleep,
            clock=self.clock,
        )
        assert found is not None  # poll only returns values accepted by ``until``
        return found

    # --- pull requests --------------------------------------------------------------------------------------------
    def _pull_requests(self, kind: str, org_id: str | None, repo_name: str | None) -> list[dict[str, Any]]:
        """Every page of /api/pullrequests/<kind> filtered with id[org_id] / id[repo_name] (anchored regexes)."""
        filters = {
            key: anchored(value) for key, value in (("id[org_id]", org_id), ("id[repo_name]", repo_name)) if value
        }
        records: list[dict[str, Any]] = []
        for page in range(1, MAX_PAGES + 1):
            body = (
                self._json(f"/api/pullrequests/{kind}", {**filters, "pageSize": DEFAULT_PAGE_SIZE, "pageIndex": page})
                or {}
            )
            data = list(body.get("data") or [])
            records.extend(data)
            if len(data) < DEFAULT_PAGE_SIZE or len(records) >= int(body.get("itemsCount") or 0):
                break
        return records

    def open_pull_requests(self, *, org_id: str | None = None, repo_name: str | None = None) -> list[dict[str, Any]]:
        """GET /api/pullrequests/open (open + merged-not-completed)."""
        return self._pull_requests("open", org_id, repo_name)

    def merged_pull_requests(self, *, org_id: str | None = None, repo_name: str | None = None) -> list[dict[str, Any]]:
        """GET /api/pullrequests/merged (status merged AND apply_status completed)."""
        return self._pull_requests("merged", org_id, repo_name)

    def pull_request(self, org_id: str, repo_name: str, number: int) -> dict[str, Any] | None:
        """The PR record from the open or merged list (matched client-side), None when absent."""
        for records in (
            self.open_pull_requests(org_id=org_id, repo_name=repo_name),
            self.merged_pull_requests(org_id=org_id, repo_name=repo_name),
        ):
            for record in records:
                if (record.get("id") or {}).get("pull_request") == number:
                    return record
        return None

    def quiesce(self, *, org_id: str, quiet_for: float = 15, timeout: float = 180) -> None:
        """Wait until no task of the org is pending/running for ``quiet_for`` seconds (WaitTimeoutError otherwise)."""
        deadline = waiting.Deadline(timeout, clock=self.clock)
        interval = max(0.5, min(5.0, quiet_for / 3)) if quiet_for > 0 else 0.5
        quiet_since: float | None = None
        attempts = 0
        while True:
            attempts += 1
            busy = self.active_tasks(org_id=org_id)
            now = self.clock()
            if busy:
                quiet_since = None
            elif quiet_since is None:
                quiet_since = now
            if quiet_since is not None and now - quiet_since >= quiet_for:
                return
            if deadline.expired():
                summary = [f"{t.get('type')}#{t.get('pull_request')}:{t.get('status')}" for t in busy]
                raise waiting.WaitTimeoutError(
                    f"webapp tasks of {org_id} did not quiesce (busy: {summary})", timeout, last=busy, attempts=attempts
                )
            self.sleep(min(interval, max(deadline.remaining(), 0.0)))
