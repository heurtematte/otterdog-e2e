"""The GitHub API requests an otterdog command sent, from its usage statistics (otterdog >= 1.7.0, #881).

otterdog writes, when ``OTTERDOG_STATS_FILE`` names a file, a JSON report of every HTTP request it sent: per api
(``rest``, ``graphql``, ``web``) the number of requests per endpoint, an endpoint being the method and the path with
every name and id replaced by a placeholder (``PATCH /repos/{owner}/{repo}``,
``PUT /orgs/{org}/teams/{name}/repos/{owner}/{repo}``) or, for GraphQL, the operation (``mutation
createBranchProtectionRule``, ``query get-branch-protection-rules``). The report holds no names, ids, values nor
tokens (otterdog/providers/github/stats/__init__.py, rest_endpoint).

The runner sets the variable for every live command, relative to the command's private cwd, and keeps the parsed
report on the CliResult (``api_usage``) and a copy next to the command's artifacts. A scenario step asserts the
requests of its apply with ``apply.api`` (``sent`` / ``not_sent`` endpoints, ApiSpec): this is how a test pins the
HTTP verbs of a change, e.g. that a change of team_permissions alone sends no ``PATCH /repos/{owner}/{repo}``
(otterdog#924, refused with 403 on an archived repository). Older SUTs ignore the variable: no report, the check
is then skipped with a note (``API_USAGE_SINCE``).

``scenarios/api_endpoints.yaml`` is the inventory of the write requests otterdog sends (load_inventory); every
endpoint a scenario names must be in it, and docs/api-coverage.md, generated from both, shows which ones a scenario
asserts.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

API_USAGE_ENV = "OTTERDOG_STATS_FILE"
API_USAGE_FILE = "api-usage.json"  # relative to the command's cwd (host and container alike)
API_USAGE_SINCE = "1.7.0"  # first otterdog release writing the report (#881)
API_USAGE_LIMIT = 1_000_000  # bytes read from the (untrusted) report
APIS = ("rest", "graphql", "web")
WRITE_METHODS = ("POST", "PUT", "PATCH", "DELETE")
ENDPOINT_RE = re.compile(
    r"^(?:(?P<method>GET|POST|PUT|PATCH|DELETE) (?P<path>/[A-Za-z0-9_.{}/-]*)"
    r"|(?P<operation>query|mutation) (?P<name>[A-Za-z][A-Za-z0-9_-]*))$"
)
INVENTORY_FILE = Path("scenarios") / "api_endpoints.yaml"
INVENTORY_KEYS = ("endpoint", "source", "trigger", "feature", "scope", "notes")
INVENTORY_SCOPES = ("cli", "webapp")  # who sends it: the CLI (plan/apply/import) or only the webapp


class ApiUsageError(ValueError):
    """An invalid statistics report or inventory."""


def endpoint_problem(text: Any) -> str | None:
    """Why ``text`` is not an endpoint of otterdog's statistics (``METHOD /path`` or ``query|mutation <name>``)."""
    if not isinstance(text, str) or not ENDPOINT_RE.match(text):
        return f"{text!r} is not an endpoint: 'METHOD /path/{{placeholder}}' or 'mutation <name>'"
    return None


def is_write(endpoint: str) -> bool:
    """True for a REST request that is not a GET and for a GraphQL mutation."""
    match = ENDPOINT_RE.match(endpoint)
    if match is None:
        return False
    return match.group("method") in WRITE_METHODS or match.group("operation") == "mutation"


@dataclass(frozen=True)
class ApiUsage:
    """The requests of one otterdog command: per endpoint (every api merged) the number of requests, the error
    counters (``<status>`` or ``network`` per api, otterdog's keys) and the command's outcome."""

    endpoints: Mapping[str, int] = field(default_factory=dict)
    errors: Mapping[str, int] = field(default_factory=dict)
    outcome: str | None = None

    def count(self, endpoint: str) -> int:
        """Requests sent to ``endpoint`` (0 when none)."""
        return self.endpoints.get(endpoint, 0)

    def writes(self) -> dict[str, int]:
        """The write requests (REST methods other than GET, GraphQL mutations), sorted by endpoint."""
        return {endpoint: count for endpoint, count in sorted(self.endpoints.items()) if is_write(endpoint)}

    def summary(self) -> str:
        """One line: the write requests with their counts, or that there were none."""
        writes = self.writes()
        if not writes:
            return "no write request"
        return ", ".join(f"{endpoint} x{count}" if count > 1 else endpoint for endpoint, count in writes.items())


def parse_api_usage(text: str) -> ApiUsage:
    """ApiUsage of otterdog's JSON report (``apis.<api>.endpoints.<endpoint>.requests``, ``apis.<api>.errors``);
    ApiUsageError when it is not such a report. Endpoints that do not match ENDPOINT_RE are kept as written."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ApiUsageError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("apis"), dict):
        raise ApiUsageError("no 'apis' object")
    endpoints: dict[str, int] = {}
    errors: dict[str, int] = {}
    for api, statistics in data["apis"].items():
        if not isinstance(statistics, dict):
            raise ApiUsageError(f"apis.{api} is not an object")
        for endpoint, values in (statistics.get("endpoints") or {}).items():
            requests = values.get("requests") if isinstance(values, dict) else None
            if not isinstance(endpoint, str) or not isinstance(requests, int) or isinstance(requests, bool):
                raise ApiUsageError(f"apis.{api}.endpoints: invalid entry {endpoint!r}")
            endpoints[endpoint] = endpoints.get(endpoint, 0) + requests
        for error, count in (statistics.get("errors") or {}).items():
            if isinstance(count, int) and not isinstance(count, bool):
                errors[f"{api}:{error}"] = count
    outcome = data.get("outcome")
    return ApiUsage(endpoints, errors, outcome if isinstance(outcome, str) else None)


@dataclass
class ApiSpec:
    """Expected requests of a step's apply: every ``sent`` endpoint got at least one request, no ``not_sent``
    endpoint got any (a request counts whatever its response, a failed one included)."""

    sent: list[str] = field(default_factory=list)
    not_sent: list[str] = field(default_factory=list)


def api_problems(spec: ApiSpec, usage: ApiUsage, *, what: str = "apply") -> list[str]:
    """Failures of the requests of a command against ``spec``, each naming the write requests it did send."""
    problems = []
    missing = [endpoint for endpoint in spec.sent if usage.count(endpoint) == 0]
    unexpected = [endpoint for endpoint in spec.not_sent if usage.count(endpoint) > 0]
    if missing:
        problems.append(f"{what}.api: expected request(s) not sent: {', '.join(missing)}")
    if unexpected:
        counts = ", ".join(f"{endpoint} x{usage.count(endpoint)}" for endpoint in unexpected)
        problems.append(f"{what}.api: unexpected request(s) sent: {counts}")
    if problems:
        problems.append(f"{what}.api: the write requests sent: {usage.summary()}")
    return problems


# --- inventory of the write requests (scenarios/api_endpoints.yaml) --------------------------------------------------


@dataclass(frozen=True)
class InventoryEndpoint:
    """One write request otterdog sends: where (``source``), on which configuration change (``trigger``), the
    coverage feature it belongs to, and whether the CLI or only the webapp sends it."""

    endpoint: str
    source: str
    trigger: str
    feature: str | None = None
    scope: str = "cli"
    notes: str | None = None


@dataclass(frozen=True)
class ApiInventory:
    """scenarios/api_endpoints.yaml: the otterdog ref it was built at and its endpoints (in file order)."""

    ref: str
    endpoints: tuple[InventoryEndpoint, ...]

    def names(self) -> set[str]:
        """Every endpoint of the inventory."""
        return {entry.endpoint for entry in self.endpoints}


def load_inventory(path: Path) -> ApiInventory:
    """Parse and check the inventory (ApiUsageError naming the problems)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    problems: list[str] = []
    if not isinstance(data, dict) or not isinstance(data.get("endpoints"), list):
        raise ApiUsageError(f"{path}: expected a mapping with an 'endpoints' list")
    otterdog = data.get("otterdog")
    ref = otterdog.get("ref") if isinstance(otterdog, dict) else None
    if not isinstance(ref, str) or not re.fullmatch(r"[0-9a-f]{40}", ref):
        problems.append("otterdog.ref must be a 40-hex commit of eclipse-csi/otterdog")
    entries: list[InventoryEndpoint] = []
    seen: set[str] = set()
    for index, item in enumerate(data["endpoints"]):
        where = f"endpoints[{index}]"
        if not isinstance(item, dict):
            problems.append(f"{where}: expected a mapping")
            continue
        unknown = sorted(set(item) - set(INVENTORY_KEYS))
        if unknown:
            problems.append(f"{where}: unknown key(s) {unknown}")
        endpoint = item.get("endpoint")
        problem = endpoint_problem(endpoint)
        if problem or not isinstance(endpoint, str):
            problems.append(f"{where}: {problem}")
            continue
        if not is_write(endpoint):
            problems.append(f"{where}: {endpoint} is not a write request")
        if endpoint in seen:
            problems.append(f"{where}: duplicate endpoint {endpoint}")
        seen.add(endpoint)
        for key in ("source", "trigger"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                problems.append(f"{where} ({endpoint}): '{key}' must be a non-empty string")
        scope = item.get("scope", "cli")
        if scope not in INVENTORY_SCOPES:
            problems.append(f"{where} ({endpoint}): scope must be one of {list(INVENTORY_SCOPES)}")
        entries.append(
            InventoryEndpoint(
                endpoint,
                str(item.get("source", "")),
                str(item.get("trigger", "")),
                item.get("feature"),
                scope,
                item.get("notes"),
            )
        )
    if problems:
        raise ApiUsageError(f"{path}: " + "; ".join(problems))
    return ApiInventory(ref or "", tuple(entries))


def unknown_endpoints(endpoints: Iterable[str], inventory: ApiInventory) -> list[str]:
    """The write endpoints of ``endpoints`` that the inventory does not list (sorted, unique)."""
    names = inventory.names()
    return sorted({endpoint for endpoint in endpoints if is_write(endpoint) and endpoint not in names})
