"""Run summaries and the artifact scrubber (SPEC 14, 5.7).

Artifacts hold only redacted text copies; scrub_artifacts deletes everything else, scans the remaining bytes for
registered secrets, their variants and token patterns, deletes leaking files and writes leaks.json. CI uploads
artifacts only after a successful scrub (a leak fails the job).

build_summary reads a run directory ``<artifacts_root>/<run_id>/`` (every input is optional):

* ``run.json``: run_id, started_at, finished_at, lane, argv|command, target ({name, org, plan} or a name), org, plan,
  sut / base / reset_sut (ResolvedSut.to_json() or a spec string), versions, capabilities (Capabilities.to_json()).
* ``results.jsonl``: one line per test (or per phase), keys nodeid, outcome (passed|failed|skipped|error|xfailed|
  xpassed; pytest's skipped/passed + wasxfail are understood), when, duration | phases {setup, call, teardown},
  tier, markers, scenario, priority, tags, sut, reason (skip/xfail reason), failure (short, redacted), infra (bool),
  known_bug, rate {identity: remaining | {resource: remaining}}.
* ``differential.json`` (DiffReport.to_json()), ``deliveries.jsonl`` files of the relay (event, action,
  relay_status, github_status_code, lag_seconds) and ``cli/<seq>-<command>/cmd.txt`` copies of OtterdogCli; CLI
  artifacts below a directory named ``reset`` (trusted reset SUT) or ``base`` (differential base SUT) are counted
  separately from the SUT under test, and commands that ran without GitHub access (below an ``offline`` directory,
  or whose ``# process:`` line is a network sandbox) never count as live CLI testing. A ``# web_ui: login gate
  admitted`` line marks a command that logged in to the GitHub web UI (web-UI tier).
* ``run.json`` ``web_ui`` (web-UI tier: enabled, reason, session_logins, waited_seconds) when the session probed it.

Outside the run directory, the coverage matrix ``scenarios/coverage.yaml`` of the otterdog-e2e project (E2E_PROJECT_ROOT
or the nearest project root, see default_coverage_file) gives the "Coverage matrix" section: covered, partial and gap
shares of otterdog's features, and the features whose covering items (scenario ids, pytest node ids) ran.
"""

from __future__ import annotations

import html
import itertools
import json
import logging
import os
import re
import shlex
from collections import Counter
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cached_property
from pathlib import Path
from typing import Any

import yaml

from otterdog_e2e.differential import JSON_FILE as DIFFERENTIAL_JSON
from otterdog_e2e.differential import MARKDOWN_FILE as DIFFERENTIAL_MD
from otterdog_e2e.differential import md_cell, md_code, md_fence
from otterdog_e2e.redact import REDACTOR, Redactor
from otterdog_e2e.safety import SafetyError

ALLOWED_ARTIFACT_SUFFIXES = (".txt", ".json", ".jsonl", ".md", ".log", ".xml")
LEAKS_FILE = "leaks.json"
SUMMARY_FILE = "summary.md"
RESULTS_FILE = "results.jsonl"
RUN_FILE = "run.json"
DELIVERIES_FILE = "deliveries.jsonl"
CLI_DIR = "cli"
CMD_FILE = "cmd.txt"
OFFLINE_DIR = "offline"  # path part of offline-tier CLI artifacts (offline/<test>/cli, <role>/offline/cli)
PROCESS_LINE_PREFIX = "# process:"  # cmd.txt line with the process argv (sandbox or docker prefix included)
WEB_LOGIN_LINE_PREFIX = "# web_ui: login gate admitted"  # cmd.txt note of a command that logged in to the web UI
COVERAGE_FILE = Path("scenarios") / "coverage.yaml"  # the coverage matrix, below the otterdog-e2e project root
COVERAGE_DOC = "docs/coverage-matrix.md"  # its rendering (tests/unit/test_coverage_matrix.py --write)
COVERAGE_STATUSES = ("covered", "partial", "gap")
_YAML_LOADER: Any = getattr(yaml, "CSafeLoader", yaml.SafeLoader)  # libyaml when available: the matrix is large
SUMMARY_MAX_BYTES = 1024 * 1024  # GitHub job summaries are limited to 1 MiB
# time budgets in seconds (SPEC 2); overruns are flagged in the summary, never failures
BUDGETS: dict[str, int] = {
    "offline": 600,
    "cli": 1800,
    "cli_scenario": 240,
    "webapp": 1500,
    "webapp_flow": 300,
    "web_ui": 1800,  # the whole tier: about a dozen bot logins a TOTP window apart (docs/web-ui-testing.md)
    "differential": 900,
    "pr-fast": 2700,
}
TIERS = ("unit", "offline", "cli", "webhooks", "webapp", "web_ui", "enterprise", "differential", "adhoc")
LIVE_TIERS = frozenset({"cli", "webhooks", "webapp", "web_ui", "enterprise"})
OUTCOMES = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
_OUTCOME_RANK = {"passed": 0, "skipped": 1, "xfailed": 2, "xpassed": 3, "error": 4, "failed": 5}
_OUTCOME_ALIASES = {"pass": "passed", "fail": "failed", "errors": "error", "skip": "skipped"}
_OUTCOME_ALIASES |= {"xfail": "xfailed", "xpass": "xpassed"}
PLAN_NAMES = {"free": "Free", "team": "Team", "enterprise": "Enterprise Cloud"}
PROGRAMS = frozenset({"otterdog-e2e", "pytest", "py.test", "python", "python3"})  # argv[0] of a full command line
OTTERDOG_COMMANDS = frozenset(
    {
        "--version", "apply", "approve-blueprints", "canonical-diff", "check-status", "check-token-permissions",
        "delete-file", "dispatch-workflow", "fetch-config", "import", "install-app", "install-deps", "list-advisories",
        "list-apps", "list-blueprints", "list-members", "list-projects", "local-apply", "local-plan", "open-pr", "plan",
        "push-config", "review-permissions", "show", "show-default", "show-live", "sync-template", "uninstall-app",
        "validate", "web-login",
    }
)  # fmt: skip
INFRA_RE = re.compile(
    r"\(infra\)|secondary rate limit|API rate limit exceeded|github rate budget|github-rate-limit"
    r"|Cannot connect to host api\.github\.com|Cannot connect to the Docker daemon|delivery not observed|LeaseBusy",
    re.IGNORECASE,
)
KNOWN_BUG_RE = re.compile(r"\bKB-\d+\b")
_CLI_DIR_RE = re.compile(r"^\d+-(?P<command>.+)$")
_UNSHARE_NET_RE = re.compile(r"^(-[A-Za-z]*n[A-Za-z]*|--net(=.*)?)$")  # unshare options creating a network namespace
_SKIP_PREFIX_RE = re.compile(r"^(Skipped|XFAIL|xfail):\s*")
FAILURE_MAX_LINES = 40
FAILURE_MAX_CHARS = 4000
MAX_FAILURE_DETAILS = 50
MAX_LISTED = 200
MAX_EXAMPLES = 3
SCAN_CHUNK_BYTES = 8 * 1024 * 1024
SCAN_OVERLAP_BYTES = 64 * 1024
# headings of otterdog's .github/pull_request_template.md, verbatim (including its "scenario:**" typo)
PR_TEMPLATE_MANUAL_TESTING = "### Manual testing"
PR_TEMPLATE_REPRODUCE = "### How to reproduce / test scenario:**"
PR_TEMPLATE_NO_LIVE = "GitHub API calls only stubbed / mocked in unit tests (no live testing)"
PR_TEMPLATE_LIVE = "Tested on a real GitHub organization (live GitHub API):"
PR_TEMPLATE_WEBHOOKS = (
    "**Webhook interactions** — otterdog bot behavior on PRs (validation / sync checks, bot comments on the config "
    "repo PRs); org plan used:"
)

log = logging.getLogger(__name__)


# --- inputs -------------------------------------------------------------------------------------------------------
def read_json(path: Path) -> Any:
    """Decoded JSON file, None when missing or invalid (logged)."""
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("cannot read %s: %s", path, exc)
        return None


def read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    """(JSON objects of a JSONL file, number of malformed lines); missing file -> ([], 0)."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
    except OSError as exc:
        log.warning("cannot read %s: %s", path, exc)
        text = ""
    rows: list[dict[str, Any]] = []
    bad = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            value = None
        if isinstance(value, dict):
            rows.append(value)
        else:
            bad += 1
    return rows, bad


def lookup(data: Any, *paths: str) -> Any:
    """First non-empty value among dotted ``paths`` of nested mappings."""
    for dotted in paths:
        node = data
        for part in dotted.split("."):
            node = node.get(part) if isinstance(node, Mapping) else None
        if node not in (None, "", [], {}):
            return node
    return None


# --- test results -------------------------------------------------------------------------------------------------
@dataclass
class TestRecord:
    """One test item aggregated over its results.jsonl lines."""

    __test__ = False  # not a pytest test class

    nodeid: str
    tier: str
    outcome: str = "passed"
    duration: float = 0.0
    scenario: str | None = None
    priority: str | None = None
    sut: str | None = None
    tags: list[str] = field(default_factory=list)
    markers: list[str] = field(default_factory=list)
    reason: str | None = None
    failure: str | None = None
    infra: bool = False
    known_bug: str | None = None

    @property
    def name(self) -> str:
        """Scenario id, else the test name part of the node id."""
        return self.scenario or self.nodeid.split("::")[-1]

    @property
    def ran(self) -> bool:
        """True unless skipped (an xfail ran)."""
        return self.outcome != "skipped"

    @property
    def is_live(self) -> bool:
        """Live item: ``live`` marker or a live tier directory."""
        return "live" in self.markers or self.tier in LIVE_TIERS

    @property
    def is_failure(self) -> bool:
        """Failed or errored."""
        return self.outcome in ("failed", "error")

    @property
    def is_infra(self) -> bool:
        """Failure (or skip) caused by infrastructure: infra flag or a known infrastructure message."""
        text = self.failure if self.is_failure else self.reason
        return self.infra or bool(text and INFRA_RE.search(text))


def tier_of(nodeid: str, declared: Any = None) -> str:
    """Tier of a test: the declared one, else the directory below ``tests/`` in the node id."""
    if isinstance(declared, str) and declared in TIERS:
        return declared
    parts = nodeid.split("::", 1)[0].replace("\\", "/").split("/")
    for index, part in enumerate(parts[:-1]):
        if part == "tests" and parts[index + 1] in TIERS:
            return parts[index + 1]
    return "other"


def line_outcome(line: Mapping[str, Any]) -> str:
    """Normalized outcome of one results line (xfail/xpass and setup/teardown errors resolved)."""
    outcome = str(line.get("outcome") or "passed").lower()
    outcome = _OUTCOME_ALIASES.get(outcome, outcome)
    xfail = line.get("wasxfail") or line.get("xfail")
    if xfail and outcome == "skipped":
        return "xfailed"
    if xfail and outcome == "passed":
        return "xpassed"
    if outcome == "failed" and line.get("when") in ("setup", "teardown"):
        return "error"
    return outcome if outcome in _OUTCOME_RANK else "error"


def line_duration(line: Mapping[str, Any]) -> float:
    """``duration`` of a line, else the sum of its ``phases``."""
    value = line.get("duration")
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    phases = line.get("phases")
    if isinstance(phases, Mapping):
        return float(sum(v for v in phases.values() if isinstance(v, int | float) and not isinstance(v, bool)))
    return 0.0


def marker_names(markers: Any) -> list[str]:
    """Marker names of a results line (strings like ``known_bug(KB-001)`` or {"name": ...} objects)."""
    names: list[str] = []
    for marker in markers if isinstance(markers, list) else []:
        name = marker.get("name") if isinstance(marker, Mapping) else marker
        if isinstance(name, str) and name:
            names.append(name.split("(", 1)[0])
    return names


def known_bug_of(line: Mapping[str, Any]) -> str | None:
    """Known bug id of a line: ``known_bug`` key, else a KB-<n> in markers or reason."""
    declared = line.get("known_bug")
    if isinstance(declared, str) and declared:
        return declared
    match = KNOWN_BUG_RE.search(json.dumps(line.get("markers", []), default=str))
    if match:
        return match.group(0)
    reason = line.get("reason") or line.get("wasxfail")
    match = KNOWN_BUG_RE.search(reason) if isinstance(reason, str) else None
    return match.group(0) if match else None


def short_text(text: str, *, max_lines: int = FAILURE_MAX_LINES, max_chars: int = FAILURE_MAX_CHARS) -> str:
    """At most max_lines lines / max_chars characters of ``text``."""
    lines = text.strip("\n").splitlines()
    clipped = "\n".join(lines[:max_lines])[:max_chars]
    return clipped + ("\n..." if len(lines) > max_lines or len(clipped) < len("\n".join(lines[:max_lines])) else "")


def clean_reason(reason: Any) -> str | None:
    """Skip/xfail reason without pytest's ``Skipped:`` prefix."""
    if not isinstance(reason, str) or not reason.strip():
        return None
    return _SKIP_PREFIX_RE.sub("", reason.strip())


def _first_text(*values: Any) -> str | None:
    """First non-empty string."""
    return next((value for value in values if isinstance(value, str) and value), None)


def _merge_line(record: TestRecord, line: Mapping[str, Any]) -> None:
    """Fold one results line into a TestRecord."""
    outcome = line_outcome(line)
    if _OUTCOME_RANK[outcome] > _OUTCOME_RANK[record.outcome]:
        record.outcome = outcome
    record.duration += line_duration(line)
    record.scenario = record.scenario or _first_text(line.get("scenario"))
    record.priority = record.priority or _first_text(line.get("priority"))
    record.sut = record.sut or _first_text(line.get("sut"))
    record.tags = list(dict.fromkeys([*record.tags, *(t for t in line.get("tags") or [] if isinstance(t, str))]))
    record.markers = list(dict.fromkeys([*record.markers, *marker_names(line.get("markers"))]))
    if outcome in ("skipped", "xfailed", "xpassed"):
        record.reason = record.reason or clean_reason(_first_text(line.get("reason"), line.get("wasxfail")))
    failure = _first_text(line.get("failure"), line.get("longrepr"))
    if outcome in ("failed", "error") and failure and not record.failure:
        record.failure = short_text(failure)
    record.infra = record.infra or bool(line.get("infra"))
    record.known_bug = record.known_bug or known_bug_of(line)


def aggregate_results(lines: Iterable[Mapping[str, Any]]) -> list[TestRecord]:
    """TestRecords per node id, in first-seen order."""
    records: dict[str, TestRecord] = {}
    for line in lines:
        nodeid = line.get("nodeid")
        if not isinstance(nodeid, str) or not nodeid:
            continue
        if nodeid not in records:
            records[nodeid] = TestRecord(nodeid, tier_of(nodeid, line.get("tier")))
        _merge_line(records[nodeid], line)
    return list(records.values())


# --- rate budget --------------------------------------------------------------------------------------------------
@dataclass
class RateStats:
    """Remaining-request samples of one identity/resource, in run order."""

    first: int | None = None
    last: int | None = None
    lowest: int | None = None
    used: int = 0
    samples: int = 0

    def add(self, remaining: int) -> None:
        """Add a sample; decreases between consecutive samples count as used (increases are resets)."""
        if self.last is not None and remaining < self.last:
            self.used += self.last - remaining
        self.first = remaining if self.first is None else self.first
        self.lowest = remaining if self.lowest is None else min(self.lowest, remaining)
        self.last = remaining
        self.samples += 1


def _remaining(value: Any) -> int | None:
    """Integer remaining count of a rate sample ({"remaining": n} or n)."""
    if isinstance(value, Mapping):
        value = value.get("remaining")
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return int(value)


def rate_usage(lines: Iterable[Mapping[str, Any]]) -> dict[tuple[str, str], RateStats]:
    """RateStats per (identity, resource) from the ``rate`` field of results lines."""
    stats: dict[tuple[str, str], RateStats] = {}
    for line in lines:
        rate = line.get("rate")
        for identity, value in rate.items() if isinstance(rate, Mapping) else ():
            is_resource_map = isinstance(value, Mapping) and "remaining" not in value
            resources = value if is_resource_map else {"core": value}
            for resource, sample in resources.items():
                remaining = _remaining(sample)
                if remaining is not None:
                    stats.setdefault((str(identity), str(resource)), RateStats()).add(remaining)
    return stats


# --- CLI commands and deliveries ----------------------------------------------------------------------------------
@dataclass(frozen=True)
class CliCommand:
    """One otterdog invocation found in the artifacts (cli/<seq>-<command>/cmd.txt).

    ``offline``: run without GitHub access, i.e. inside the network sandbox (``unshare -rn`` or ``docker run
    --network none``) or by an offline tier (``offline`` path part: ``offline/<test>/cli``, ``<role>/offline/cli``).
    ``web``: logged in to the GitHub web UI (the web-UI tier's login gate admitted it).
    """

    command: str
    local: bool
    role: str  # "sut" | "reset" | "base"
    argv: tuple[str, ...]
    offline: bool = False
    web: bool = False


def _split(text: str) -> tuple[str, ...]:
    """shlex tokens of a command line (whitespace split when the quoting is broken)."""
    try:
        return tuple(shlex.split(text))
    except ValueError:
        return tuple(text.split())


def _cmd_file_info(cmd_file: Path) -> tuple[str, str, bool]:
    """(logical command line, ``# process:`` command line, web login) of a redacted cmd.txt copy (empty when
    unreadable).

    OtterdogCli writes the logical argv first, then ``# key: value`` comment lines (process, runtime, cwd, ...; web
    commands add ``# web_ui: login gate admitted ...``).
    """
    try:
        lines = cmd_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "", "", False
    logical = next((line.strip() for line in lines if line.strip() and not line.lstrip().startswith("#")), "")
    process = next((line.split(":", 1)[1].strip() for line in lines if line.startswith(PROCESS_LINE_PREFIX)), "")
    return logical, process, any(line.startswith(WEB_LOGIN_LINE_PREFIX) for line in lines)


def _cmd_file_lines(cmd_file: Path) -> tuple[str, str]:
    """(logical command line, ``# process:`` command line) of a redacted cmd.txt copy (empty when unreadable)."""
    logical, process, _web = _cmd_file_info(cmd_file)
    return logical, process


def _argv_of(cmd_file: Path) -> tuple[str, ...]:
    """Tokens of the logical command line of a redacted cmd.txt copy (empty when unreadable)."""
    return _split(_cmd_file_lines(cmd_file)[0])


def sandboxed(process: Sequence[str]) -> bool:
    """True for a process argv run without network: ``unshare -rn ...`` or ``docker run ... --network none ...``."""
    if process[:1] == ("unshare",):
        options = []
        for token in process[1:]:  # unshare's own options end at the wrapped command
            if not token.startswith("-"):
                break
            options.append(token)
        return any(_UNSHARE_NET_RE.match(token) for token in options)
    if process[:2] != ("docker", "run"):
        return False
    pairs = itertools.pairwise(process)
    return "--network=none" in process or any(a == "--network" and b == "none" for a, b in pairs)


def cli_commands(artifacts_dir: Path) -> list[CliCommand]:
    """otterdog commands run in this run, from the cli/<seq>-<command>/ artifact directories."""
    found = []
    for cmd_file in sorted(artifacts_dir.rglob(CMD_FILE)):
        match = _CLI_DIR_RE.match(cmd_file.parent.name)
        if not match or cmd_file.parent.parent.name != CLI_DIR:
            continue
        parts = cmd_file.relative_to(artifacts_dir).parts[:-3]
        role = "reset" if "reset" in parts else "base" if "base" in parts else "sut"
        logical, process, web = _cmd_file_info(cmd_file)
        argv = _split(logical)
        command = match.group("command")
        if command not in OTTERDOG_COMMANDS:
            command = next((token for token in argv if token in OTTERDOG_COMMANDS), command)
        offline = OFFLINE_DIR in parts or sandboxed(_split(process))
        found.append(CliCommand(command, "--local" in argv, role, argv, offline, web))
    return found


def deliveries(artifacts_dir: Path) -> list[dict[str, Any]]:
    """Every relay delivery line (deliveries.jsonl anywhere in the run directory)."""
    rows: list[dict[str, Any]] = []
    for path in sorted(artifacts_dir.rglob(DELIVERIES_FILE)):
        rows.extend(read_jsonl(path)[0])
    return rows


# --- coverage matrix ----------------------------------------------------------------------------------------------
class CoverageError(ValueError):
    """A coverage matrix file that holds no feature list."""


@dataclass(frozen=True)
class CoverageFeature:
    """One feature of scenarios/coverage.yaml, reduced to what the run summary shows."""

    id: str
    area: str
    tier: str
    status: str  # covered | partial | gap
    priority: str
    covered_by: tuple[str, ...]  # scenario ids and pytest node ids


@dataclass(frozen=True)
class CoverageMatrix:
    """The features of scenarios/coverage.yaml and the order of its tiers."""

    path: Path
    features: tuple[CoverageFeature, ...]
    tiers: tuple[str, ...]
    ref: str | None = None  # the otterdog commit the matrix inventories


def default_coverage_file(environ: Mapping[str, str] | None = None) -> Path | None:
    """scenarios/coverage.yaml of the otterdog-e2e project: below E2E_PROJECT_ROOT, else below the nearest project
    root of the working directory or of the installed package; None when there is none."""
    env = os.environ if environ is None else environ
    if env.get("E2E_PROJECT_ROOT"):
        root = Path(env["E2E_PROJECT_ROOT"]).expanduser()
    else:
        from otterdog_e2e.settings import find_project_root

        try:
            root = find_project_root()
        except (FileNotFoundError, OSError):
            return None
    path = root / COVERAGE_FILE
    return path if path.is_file() else None


def load_coverage(path: Path) -> CoverageMatrix:
    """The coverage matrix of ``path`` (CoverageError or yaml.YAMLError when it is no matrix); entries without an id or
    a known status are skipped (tests/unit/test_coverage_matrix.py validates the file itself)."""
    data = yaml.load(path.read_text(encoding="utf-8"), Loader=_YAML_LOADER)  # noqa: S506 - a safe loader
    entries = data.get("features") if isinstance(data, Mapping) else None
    if not isinstance(entries, list):
        raise CoverageError("no features list")
    features = []
    for entry in entries:
        if not isinstance(entry, Mapping) or not isinstance(entry.get("id"), str):
            continue
        if entry.get("status") not in COVERAGE_STATUSES:
            continue
        raw = entry.get("covered_by")
        covered_by: list[Any] = raw if isinstance(raw, list) else []
        features.append(
            CoverageFeature(
                id=entry["id"],
                area=str(entry.get("area") or ""),
                tier=str(entry.get("tier") or ""),
                status=entry["status"],
                priority=str(entry.get("priority") or ""),
                covered_by=tuple(item for item in covered_by if isinstance(item, str) and item),
            )
        )
    declared = tuple(str(tier) for tier in data["tiers"]) if isinstance(data.get("tiers"), Mapping) else ()
    tiers = (*declared, *dict.fromkeys(f.tier for f in features if f.tier and f.tier not in declared))
    ref = lookup(data, "otterdog.ref")
    return CoverageMatrix(path, tuple(features), tiers, str(ref) if ref else None)


def relative_nodeid(nodeid: str) -> str:
    """A node id from its ``tests/`` directory on (pytest may report it below another root, or absolute)."""
    path, separator, rest = nodeid.partition("::")
    parts = path.replace("\\", "/").split("/")
    for index in range(len(parts) - 2, -1, -1):
        if parts[index] == "tests":
            return "/".join(parts[index:]) + separator + rest
    return nodeid


def exercised_features(
    matrix: CoverageMatrix, records: Iterable[TestRecord]
) -> list[tuple[CoverageFeature, list[TestRecord]]]:
    """(feature, the records of its covering items that ran) of every feature exercised by the run, in matrix order.

    A covering scenario id matches the records of that scenario; a node id matches its test, and a node id without
    parameters every parametrization of it (``tests/x.py::test_y`` covers ``tests/x.py::test_y[a]``).
    """
    by_scenario: dict[str, list[TestRecord]] = {}
    by_node: dict[str, list[TestRecord]] = {}
    for record in records:
        if not record.ran:
            continue
        if record.scenario:
            by_scenario.setdefault(record.scenario, []).append(record)
        node = relative_nodeid(record.nodeid)
        by_node.setdefault(node, []).append(record)
        if node.endswith("]") and "[" in node:
            by_node.setdefault(node.split("[", 1)[0], []).append(record)
    found = []
    for feature in matrix.features:
        matched: dict[str, TestRecord] = {}
        for item in feature.covered_by:
            for record in (by_node if "::" in item else by_scenario).get(item, []):
                matched.setdefault(record.nodeid, record)
        if matched:
            found.append((feature, list(matched.values())))
    return found


def worst_outcome(records: Iterable[TestRecord]) -> str:
    """The most severe outcome of the records (failed > error > xpassed > xfailed > skipped > passed)."""
    return max((record.outcome for record in records), key=lambda outcome: _OUTCOME_RANK[outcome], default="passed")


def _share(count: int, total: int, label: str = "") -> str:
    """``count (pct%)``, or ``count label (pct%)`` with a label."""
    named = f"{count} {label}" if label else str(count)
    return f"{named} ({100.0 * count / total:.0f}%)" if total else named


def _weighted(features: Sequence[CoverageFeature]) -> str:
    """Weighted coverage of features (a partial feature counts half), ``-`` without features."""
    if not features:
        return "-"
    score = sum(1.0 if f.status == "covered" else 0.5 if f.status == "partial" else 0.0 for f in features)
    return f"{100.0 * score / len(features):.0f}%"


# --- run data -----------------------------------------------------------------------------------------------------
@dataclass
class RunData:
    """Everything build_summary reads from a run directory."""

    directory: Path
    run: dict[str, Any]
    lines: list[dict[str, Any]]
    malformed: int
    records: list[TestRecord]
    differential: dict[str, Any] | None
    commands: list[CliCommand]
    deliveries: list[dict[str, Any]]
    leaks: dict[str, Any] | None
    coverage_file: Path | None = None

    @classmethod
    def load(cls, directory: Path, *, coverage_file: Path | None = None) -> RunData:
        """Read run.json, results.jsonl, differential.json, CLI command copies, deliveries and leaks.json; the coverage
        matrix (``coverage_file``, default: default_coverage_file()) is read when a section needs it."""
        run = read_json(directory / RUN_FILE)
        lines, malformed = read_jsonl(directory / RESULTS_FILE)
        differential = read_json(directory / DIFFERENTIAL_JSON)
        leaks = read_json(directory / LEAKS_FILE)
        return cls(
            directory=directory,
            run=run if isinstance(run, dict) else {},
            lines=lines,
            malformed=malformed,
            records=aggregate_results(lines),
            differential=differential if isinstance(differential, dict) else None,
            commands=cli_commands(directory) if directory.is_dir() else [],
            deliveries=deliveries(directory) if directory.is_dir() else [],
            leaks=leaks if isinstance(leaks, dict) else None,
            coverage_file=coverage_file if coverage_file is not None else default_coverage_file(),
        )

    @cached_property
    def coverage(self) -> tuple[CoverageMatrix | None, str | None]:
        """(the coverage matrix, None), (None, why it could not be read), or (None, None) without a matrix file."""
        if self.coverage_file is None or not self.coverage_file.is_file():
            return None, None
        try:
            return load_coverage(self.coverage_file), None
        except (OSError, UnicodeDecodeError, ValueError, yaml.YAMLError) as exc:
            log.warning("cannot read the coverage matrix %s: %s", self.coverage_file, exc)
            return None, f"{exc.__class__.__name__}: {' '.join(str(exc).split())[:300]}"

    @property
    def run_id(self) -> str:
        """Run id from run.json, else the directory name."""
        return str(lookup(self.run, "run_id", "run.run_id") or self.directory.name)

    @property
    def org(self) -> str | None:
        """Test org login."""
        value = lookup(self.run, "org", "target.org", "verified.login")
        return str(value) if value else None

    @property
    def plan(self) -> str | None:
        """GitHub plan of the test org."""
        value = lookup(self.run, "plan", "target.plan", "verified.plan", "capabilities.plan")
        return str(value) if value else None

    @property
    def target(self) -> str | None:
        """Target name."""
        target = self.run.get("target")
        value = target if isinstance(target, str) else lookup(self.run, "target.name", "target_name")
        return str(value) if value else None

    def failures(self) -> list[TestRecord]:
        """Failed and errored items, product failures first."""
        failed = [record for record in self.records if record.is_failure]
        return sorted(failed, key=lambda record: record.is_infra)

    def ran(self, tier: str) -> list[TestRecord]:
        """Items of a tier that ran (not skipped)."""
        return [record for record in self.records if record.tier == tier and record.ran]

    @property
    def live(self) -> bool:
        """True when at least one live item ran."""
        return any(record.is_live and record.ran for record in self.records)


# --- formatting helpers -------------------------------------------------------------------------------------------
def fmt_duration(seconds: float) -> str:
    """``12.3 s``, ``3m 05s`` or ``1h 02m``."""
    if seconds < 60:
        return f"{seconds:.1f} s"
    minutes, secs = divmod(round(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def plan_label(plan: str | None) -> str:
    """Human plan name as in otterdog's PR template (Free / Team / Enterprise Cloud)."""
    if not plan:
        return "unknown"
    return PLAN_NAMES.get(plan.lower(), plan)


def parse_time(value: Any) -> datetime | None:
    """ISO timestamp (``Z`` or offset; naive = UTC) or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def sut_text(value: Any) -> str | None:
    """One-line description of a SUT entry of run.json (ResolvedSut.to_json() or a spec string)."""
    if isinstance(value, str) and value:
        return md_code(value)
    if not isinstance(value, Mapping):
        return None
    label = _first_text(value.get("label"), value.get("spec"), value.get("raw"))
    details = []
    for name in ("spec", "version"):
        if isinstance(value.get(name), str) and value[name] != label:
            details.append(f"{name} {md_code(value[name])}")
    if isinstance(value.get("sha"), str):
        details.append(f"sha {md_code(value['sha'][:12])}")
    if isinstance(value.get("trusted"), bool):
        details.append("trusted" if value["trusted"] else "**untrusted**")
    head = md_code(label) if label else "(unnamed)"
    return head + (f" ({', '.join(details)})" if details else "")


def names_list(names: Sequence[str], limit: int = MAX_EXAMPLES) -> str:
    """Comma separated code spans, ``(+N more)`` beyond ``limit``."""
    shown = ", ".join(md_code(name) for name in names[:limit])
    return shown + (f" (+{len(names) - limit} more)" if len(names) > limit else "")


def counted(counter: Counter[str]) -> str:
    """``a (3), b`` in first-seen order (counts shown above 1)."""
    return ", ".join(f"{md_code(name)} ({count})" if count > 1 else md_code(name) for name, count in counter.items())


# --- sections -----------------------------------------------------------------------------------------------------
def _tally(records: Iterable[TestRecord]) -> Counter[str]:
    """Outcome counts."""
    return Counter(record.outcome for record in records)


def section_title(data: RunData) -> str:
    """Title and one-line verdict."""
    tally = _tally(data.records)
    failures = data.failures()
    infra = sum(record.is_infra for record in failures)
    if not data.records:
        verdict = "**NO RESULTS**: no test results were recorded."
    elif failures:
        verdict = f"**FAILED**: {len(failures) - infra} product failure(s), {infra} infrastructure failure(s)"
        verdict += f" out of {len(data.records)} test(s)."
    else:
        verdict = f"**PASSED**: {tally['passed']} passed, {tally['skipped']} skipped, {tally['xfailed']} known-bug"
        verdict += f" xfail(s), {tally['xpassed']} xpass(es) out of {len(data.records)} test(s)."
    lines = [f"# otterdog-e2e run {md_code(data.run_id)}", verdict]
    if data.malformed:
        lines.append(f"_{data.malformed} malformed line(s) of {RESULTS_FILE} were ignored._")
    return "\n\n".join(lines)


def _run_rows(data: RunData) -> list[tuple[str, str]]:
    """(label, value) rows of the run table."""
    run = data.run
    target = data.target
    org_bits = ", ".join(
        bit for bit in (f"org {md_code(data.org)}" if data.org else "", f"plan {plan_label(data.plan)}") if bit
    )
    rows = [("Run id", md_code(data.run_id))]
    if target or data.org:
        rows.append(("Target", f"{md_code(target) if target else '-'} ({org_bits})"))
    for label, key in (("SUT under test", "sut"), ("Base SUT", "base"), ("Reset SUT", "reset_sut")):
        text = sut_text(run.get(key))
        if text and key == "reset_sut" and isinstance(run.get(key), str):
            text += " (configured, not used: no baseline reset in this run)"  # replaced by the SUT once installed
        if text:
            rows.append((label, text))
    if isinstance(run.get("lane"), str):
        rows.append(("Lane", md_code(run["lane"])))
    rows.extend(_time_rows(run))
    if isinstance(run.get("exitstatus"), int) and not isinstance(run["exitstatus"], bool):
        rows.append(("pytest exit status", str(run["exitstatus"])))
    caps = lookup(run, "capabilities.caps")
    if isinstance(caps, list) and caps:
        rows.append(("Capabilities", ", ".join(md_code(str(cap)) for cap in caps)))
    web_ui = web_ui_text(run.get("web_ui"))
    if web_ui:
        rows.append(("Web UI", web_ui))
    command = command_line(run)
    if command:
        rows.append(("Command", md_code(command)))
    return rows


def _time_rows(run: Mapping[str, Any]) -> list[tuple[str, str]]:
    """Started/finished rows."""
    started, finished, wall = parse_time(run.get("started_at")), parse_time(run.get("finished_at")), run_seconds(run)
    rows = []
    if started:
        rows.append(("Started", started.isoformat()))
    if finished:
        took = f" (duration {fmt_duration(wall)})" if wall is not None else ""
        rows.append(("Finished", finished.isoformat() + took))
    return rows


def command_line(run: Mapping[str, Any]) -> str | None:
    """The command of the run: run.json command (the ``otterdog-e2e run|pr`` command that started pytest), else argv
    (pytest invocation args get a ``pytest`` prefix)."""
    if isinstance(run.get("command"), str) and run["command"]:
        return str(run["command"])
    argv = run.get("argv")
    if isinstance(argv, list) and argv and all(isinstance(arg, str) for arg in argv):
        return shlex.join(argv if Path(argv[0]).name in PROGRAMS else ["pytest", *argv])
    return None


def _number(value: Any) -> float | None:
    """A JSON number (booleans excluded) as float, else None."""
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def web_ui_text(info: Any) -> str | None:
    """The web-UI tier of run.json (``web_ui``: enabled, reason, session_logins, waited_seconds) in one line."""
    if not isinstance(info, Mapping) or not isinstance(info.get("enabled"), bool):
        return None
    if not info["enabled"]:
        reason = info.get("reason")
        return "disabled" + (f" ({reason[:300]})" if isinstance(reason, str) and reason else "")
    text = "enabled"
    logins, waited = _number(info.get("session_logins")), _number(info.get("waited_seconds"))
    if logins:
        text += f", {logins:.0f} web login(s) of the admin bot"
        if waited:
            text += f", {fmt_duration(waited)} waiting for the login gate"
    return text


def section_run(data: RunData) -> str:
    """Run information table."""
    rows = _run_rows(data)
    return "## Run\n\n| | |\n|---|---|\n" + "\n".join(f"| {name} | {md_cell(value)} |" for name, value in rows)


def section_tiers(data: RunData) -> str:
    """Outcome counts and duration per tier."""
    if not data.records:
        return ""
    tiers = [tier for tier in (*TIERS, "other") if any(record.tier == tier for record in data.records)]
    header = "| Tier | Passed | Failed | Errors | Skipped | xfailed | xpassed | Duration |"
    lines = ["## Outcomes per tier", "", header, "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for tier in [*tiers, None]:
        records = [record for record in data.records if tier is None or record.tier == tier]
        tally = _tally(records)
        name = tier or "**total**"
        counts = " | ".join(str(tally[outcome]) for outcome in OUTCOMES)
        lines.append(f"| {name} | {counts} | {fmt_duration(sum(record.duration for record in records))} |")
    return "\n".join(lines)


def section_classification(data: RunData) -> str:
    """Infrastructure vs product failures (and infrastructure skips)."""
    failures = data.failures()
    infra_skips = [record for record in data.records if record.outcome == "skipped" and record.is_infra]
    if not failures and not infra_skips:
        return ""
    product = [record.name for record in failures if not record.is_infra]
    infra = [record.name for record in failures if record.is_infra]
    lines = ["## Infrastructure vs product", ""]
    lines.append(f"- Product failures (SUT behaviour or scenario assertions): {len(product)}")
    if product:
        lines[-1] += f" — {names_list(product, 10)}"
    lines.append(f"- Infrastructure failures (rate limits, delivery lag, docker, network): {len(infra)}")
    if infra:
        lines[-1] += f" — {names_list(infra, 10)}"
    if infra_skips:
        lines.append(f"- Skipped for infrastructure reasons (e.g. github rate budget): {len(infra_skips)}")
    return "\n".join(lines)


def _failure_block(record: TestRecord) -> str:
    """<details> block with the (short, redacted) failure text of one item."""
    kind = "infrastructure" if record.is_infra else "product"
    extra = f", scenario <code>{_html(record.scenario)}</code>" if record.scenario else ""
    summary = f"<b>{record.outcome.upper()}</b> ({kind}{extra}, {fmt_duration(record.duration)}) "
    summary += f"<code>{_html(record.nodeid)}</code>"
    body = md_fence(record.failure, "text") if record.failure else "_no failure text recorded_"
    return f"<details><summary>{summary}</summary>\n\n{body}\n\n</details>"


def _html(text: str) -> str:
    """HTML-escaped text for <summary> elements."""
    return html.escape(text, quote=False)


def section_failures(data: RunData) -> str:
    """Failures with short, redacted texts (first MAX_FAILURE_DETAILS detailed, then one line each)."""
    failures = data.failures()
    if not failures:
        return ""
    parts = [f"## Failures ({len(failures)})"]
    parts.extend(_failure_block(record) for record in failures[:MAX_FAILURE_DETAILS])
    rest = failures[MAX_FAILURE_DETAILS:]
    if rest:
        listed = [f"- {record.outcome} {md_code(record.nodeid)}" for record in rest[:MAX_LISTED]]
        if len(rest) > MAX_LISTED:
            listed.append(f"- ... and {len(rest) - MAX_LISTED} more (see {RESULTS_FILE})")
        parts.append("\n".join(listed))
    return "\n\n".join(parts)


def section_skips(data: RunData) -> str:
    """Skipped items grouped by reason."""
    groups: dict[str, list[str]] = {}
    for record in data.records:
        if record.outcome == "skipped":
            groups.setdefault(record.reason or "(no reason recorded)", []).append(record.name)
    if not groups:
        return ""
    total = sum(len(names) for names in groups.values())
    lines = [f"## Skips by reason ({total})", "", "| Count | Reason | Examples |", "|---:|---|---|"]
    for reason, names in sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))[:MAX_LISTED]:
        lines.append(f"| {len(names)} | {md_cell(reason[:300])} | {md_cell(names_list(names))} |")
    return "\n".join(lines)


def _bug_rows(records: Iterable[TestRecord]) -> list[str]:
    """Table rows ``| bug | tests |`` grouped by known bug (id or reason)."""
    groups: dict[str, list[str]] = {}
    for record in records:
        groups.setdefault(record.reason or record.known_bug or "(unknown bug)", []).append(record.name)
    return [f"| {md_cell(bug)} | {md_cell(names_list(names, 10))} |" for bug, names in groups.items()]


def section_known_bugs(data: RunData) -> str:
    """Known bugs: still failing (xfail) and possibly fixed (xpass)."""
    xfailed = [record for record in data.records if record.outcome == "xfailed"]
    xpassed = [record for record in data.records if record.outcome == "xpassed"]
    if not xfailed and not xpassed:
        return ""
    parts = ["## Known bugs"]
    if xfailed:
        rows = "\n".join(_bug_rows(xfailed))
        parts.append(f"Still reproduced (xfail, {len(xfailed)}):\n\n| Bug | Tests |\n|---|---|\n{rows}")
    if xpassed:
        rows = "\n".join(_bug_rows(xpassed))
        intro = f"Unexpectedly passing (xpass, {len(xpassed)}): the bug may be fixed, update scenarios/known_bugs.yaml."
        parts.append(f"{intro}\n\n| Bug | Tests |\n|---|---|\n{rows}")
    return "\n\n".join(parts)


def _coverage_table(matrix: CoverageMatrix, exercised: set[str]) -> list[str]:
    """Per-tier table of the matrix: features, covered / partial / gap shares, weighted coverage, exercised."""
    lines = [
        "| Tier | Features | Covered | Partial | Gap | Weighted | Exercised by this run |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    groups = [(md_code(tier), [f for f in matrix.features if f.tier == tier]) for tier in matrix.tiers]
    for label, features in [*groups, ("**total**", list(matrix.features))]:
        if not features:
            continue
        found = Counter(f.status for f in features)
        shares = " | ".join(_share(found[status], len(features)) for status in COVERAGE_STATUSES)
        hits = sum(1 for f in features if f.id in exercised)
        lines.append(
            f"| {label} | {len(features)} | {shares} | {_weighted(features)} | {_share(hits, len(features))} |"
        )
    return lines


def section_coverage(data: RunData) -> str:
    """The coverage matrix (scenarios/coverage.yaml): covered / partial / gap shares per tier and the features whose
    covering items ran in this run (with their worst outcome)."""
    matrix, error = data.coverage
    if error:
        return f"## Coverage matrix\n\n_{md_code(str(COVERAGE_FILE))} could not be read: {md_cell(error)}_"
    if matrix is None or not matrix.features:
        return ""
    total = len(matrix.features)
    found = Counter(f.status for f in matrix.features)
    ref = f" (otterdog {md_code(matrix.ref[:7])})" if matrix.ref else ""
    intro = (
        f"{md_code(str(COVERAGE_FILE))}{ref} inventories **{total} features**: "
        f"{_share(found['covered'], total, 'covered')}, {_share(found['partial'], total, 'partial')}, "
        f"{_share(found['gap'], total, 'gaps')}; weighted coverage {_weighted(matrix.features)} (a partial feature "
        f"counts half). Details and gap outlines: {md_code(COVERAGE_DOC)}."
    )
    exercised = exercised_features(matrix, data.records)
    if exercised:
        statuses = Counter(feature.status for feature, _ in exercised)
        outcomes = Counter(worst_outcome(records) for _, records in exercised)
        summary = (
            f"This run exercised **{len(exercised)}** of them ({100.0 * len(exercised) / total:.0f}%): the covering items "
            f"of {statuses['covered']} covered and {statuses['partial']} partial feature(s) ran; worst outcome per "
            f"feature: {', '.join(f'{outcomes[name]} {name}' for name in OUTCOMES if outcomes[name])}."
        )
    elif data.records:
        summary = "No covering item of the matrix ran in this run."
    else:
        summary = ""
    parts = ["## Coverage matrix", intro, *([summary] if summary else [])]
    parts.append("\n".join(_coverage_table(matrix, {feature.id for feature, _ in exercised})))
    if exercised:
        rows = [
            f"| {md_code(feature.id)} | {md_cell(feature.tier)} | {feature.status} | {worst_outcome(records)} | "
            f"{md_cell(names_list(list(dict.fromkeys(record.name for record in records))))} |"
            for feature, records in exercised[:MAX_LISTED]
        ]
        if len(exercised) > MAX_LISTED:
            rows.append(f"| ... | | | | {len(exercised) - MAX_LISTED} more |")
        table = "\n".join(["| Feature | Tier | Matrix status | Outcome | Items |", "|---|---|---|---|---|", *rows])
        parts.append(
            f"<details><summary>Features exercised by this run ({len(exercised)})</summary>\n\n{table}\n\n</details>"
        )
    return "\n\n".join(parts)


@dataclass(frozen=True)
class BudgetCheck:
    """One budget of SPEC 2 evaluated against the run."""

    name: str
    limit: float
    actual: float

    @property
    def over(self) -> bool:
        """True when the actual duration exceeds the limit."""
        return self.actual > self.limit


def _counts_for_tier_budget(record: TestRecord) -> bool:
    """cli/webapp tier budgets cover P0 items (all items when no priority was recorded)."""
    return record.priority in (None, "P0")


def _tier_checks(data: RunData, tier: str, item_budget: str, label: str) -> list[BudgetCheck]:
    """P0 tier total and per-item overruns (cli scenarios, webapp PR flows)."""
    records = [record for record in data.ran(tier) if _counts_for_tier_budget(record)]
    if not records:
        return []
    checks = [BudgetCheck(f"{tier} tier (P0)", BUDGETS[tier], sum(record.duration for record in records))]
    checks += [
        BudgetCheck(f"{label} {record.name}", BUDGETS[item_budget], record.duration)
        for record in records
        if record.duration > BUDGETS[item_budget]
    ]
    return checks


def run_seconds(run: Mapping[str, Any]) -> float | None:
    """Wall time of the run from run.json started_at/finished_at."""
    started, finished = parse_time(run.get("started_at")), parse_time(run.get("finished_at"))
    return (finished - started).total_seconds() if started and finished else None


def budget_checks(data: RunData) -> list[BudgetCheck]:
    """Tier, per-scenario and lane budgets of SPEC 2 for the tiers that ran."""
    offline: dict[str, float] = {}
    for record in data.ran("offline"):
        offline[record.sut or "sut"] = offline.get(record.sut or "sut", 0.0) + record.duration
    checks = [BudgetCheck(f"offline tier ({sut})", BUDGETS["offline"], total) for sut, total in offline.items()]
    checks += _tier_checks(data, "cli", "cli_scenario", "cli scenario")
    checks += _tier_checks(data, "webapp", "webapp_flow", "webapp flow")
    web_ui = data.ran("web_ui")
    if web_ui:
        checks.append(BudgetCheck("web_ui tier", BUDGETS["web_ui"], sum(record.duration for record in web_ui)))
    differential = data.ran("differential")
    if differential:
        checks.append(BudgetCheck("differential tier", BUDGETS["differential"], sum(r.duration for r in differential)))
    if data.run.get("lane") == "pr-fast":
        wall = run_seconds(data.run)
        total = wall if wall is not None else sum(record.duration for record in data.records)
        checks.append(BudgetCheck("pr-fast lane", BUDGETS["pr-fast"], total))
    return checks


def section_budgets(data: RunData) -> str:
    """Budget table; overruns are flagged, never failures."""
    checks = budget_checks(data)
    if not checks:
        return ""
    lines = ["## Time budgets", "", "Budget overruns are flagged, never failures (SPEC 2).", ""]
    lines += ["| Budget | Limit | Actual | Status |", "|---|---:|---:|---|"]
    for check in checks:
        status = "**over budget**" if check.over else "ok"
        lines.append(
            f"| {md_cell(check.name)} | {fmt_duration(check.limit)} | {fmt_duration(check.actual)} | {status} |"
        )
    return "\n".join(lines)


def section_rate(data: RunData) -> str:
    """GitHub rate budget used per identity (from the rate samples of results.jsonl)."""
    stats = rate_usage(data.lines)
    if not stats:
        return ""
    lines = [
        "## GitHub rate budget per identity",
        "",
        "| Identity | Resource | First | Last | Lowest | Used (approx.) |",
    ]
    lines.append("|---|---|---:|---:|---:|---:|")
    for (identity, resource), item in sorted(stats.items()):
        lines.append(
            f"| {md_cell(identity)} | {md_cell(resource)} | {item.first} | {item.last} | {item.lowest} | {item.used} |"
        )
    return "\n".join(lines)


def _delta_label(delta: Mapping[str, Any]) -> str:
    """scenario / step / kind / key of a differential.json delta."""
    parts = [str(delta.get(name) or "-") for name in ("scenario", "step", "kind", "key")]
    return " / ".join(parts)


def section_differential(data: RunData) -> str:
    """Summary of differential.json."""
    report = data.differential
    if report is None:
        return ""
    deltas = [delta for delta in report.get("deltas") or [] if isinstance(delta, Mapping)]
    unexpected = [delta for delta in deltas if not delta.get("expected")]
    unmatched = report.get("unmatched_expected") or []
    base, head = str(report.get("base_label") or "base"), str(report.get("head_label") or "head")
    text = (
        f"Base {md_code(base)} vs head {md_code(head)}: **{len(unexpected)} unexpected**, "
        f"{len(deltas) - len(unexpected)} expected delta(s), {report.get('unchanged', 0)} unchanged observation(s), "
        f"{len(report.get('not_comparable') or [])} not comparable scenario(s), {len(unmatched)} expected delta(s) "
        f"not observed. Full report: {md_code(DIFFERENTIAL_MD)}."
    )
    lines = ["## Differential", "", text]
    if unexpected:
        lines += ["", "Unexpected deltas:", ""]
        lines += [f"- {md_code(_delta_label(delta))}" for delta in unexpected[:20]]
        if len(unexpected) > 20:
            lines.append(f"- ... and {len(unexpected) - 20} more")
    return "\n".join(lines)


def section_scrub(data: RunData) -> str:
    """Leaks reported by an earlier scrub of this directory (leaks.json)."""
    leaks = [item for item in (data.leaks or {}).get("leaks") or [] if isinstance(item, Mapping)]
    if not leaks:
        return ""
    lines = [f"## Artifact scrub: {len(leaks)} leaking file(s) deleted", ""]
    lines += [f"- {md_code(str(item.get('path')))}: {item.get('reason', 'secret')}" for item in leaks[:MAX_LISTED]]
    return "\n".join(lines)


# --- manual testing block (otterdog .github/pull_request_template.md) ---------------------------------------------
def _box(checked: bool) -> str:
    """Markdown task-list checkbox."""
    return "[x]" if checked else "[ ]"


def _cli_line(data: RunData) -> tuple[bool, str]:
    """(checked, text) of the CLI item: live otterdog commands of the SUT under test (``--local`` and sandboxed
    offline commands never count as live testing; they are summarized after the list)."""
    online = [cmd for cmd in data.commands if not cmd.offline]
    live = Counter(f"otterdog {cmd.command}" for cmd in online if cmd.role == "sut" and not cmd.local)
    web = Counter(f"otterdog {cmd.command}" for cmd in online if cmd.role == "sut" and not cmd.local and cmd.web)
    others = Counter(cmd.role for cmd in online if cmd.role != "sut")
    others["offline"] = len(data.commands) - len(online)
    extra = [
        f"{others[role]} {label}"
        for role, label in (
            ("reset", "baseline-reset command(s) with the trusted reset SUT"),
            ("base", "with the base SUT"),
            ("offline", "offline command(s) without GitHub access"),
        )
        if others[role]
    ]
    text = counted(live) if live else "none"
    if web:
        text += f"; through the GitHub web UI (bot login): {counted(web)}"
    text += f" (plus {', '.join(extra)})" if extra else ""
    return bool(live), f"**CLI** — commands run: {text}"


def _flow_names(records: Sequence[TestRecord], limit: int = 15) -> str:
    """``name (outcome)`` items of the records that ran."""
    items = [f"{md_code(record.name)} ({record.outcome})" for record in records[:limit]]
    if len(records) > limit:
        items.append(f"+{len(records) - limit} more")
    return ", ".join(items)


def _webapp_line(data: RunData) -> tuple[bool, str]:
    """(checked, text) of the Web app item: webapp-tier flows that ran."""
    records = data.ran("webapp")
    detail = _flow_names(records) if records else "none"
    return bool(records), f"**Web app** — pages / flows exercised: {detail}"


def _deliveries_text(rows: Sequence[Mapping[str, Any]]) -> str:
    """``N App deliveries relayed (event.action (n), ...; webapp answered 204: n)``."""
    events = Counter(
        ".".join(str(part) for part in (row.get("event"), row.get("action")) if part) or "unknown" for row in rows
    )
    statuses = Counter(str(row.get("relay_status")) for row in rows if row.get("relay_status") is not None)
    answered = ", ".join(f"{status}: {count}" for status, count in sorted(statuses.items()))
    return f"{len(rows)} App deliveries relayed ({counted(events)}" + (
        f"; webapp answered {answered})" if answered else ")"
    )


def _webhooks_line(data: RunData) -> tuple[bool, str]:
    """(checked, text) of the Webhook interactions item."""
    records = data.ran("webhooks")
    details = []
    if records:
        details.append(_flow_names(records))
    if data.deliveries:
        details.append(_deliveries_text(data.deliveries))
    text = f"{PR_TEMPLATE_WEBHOOKS} {plan_label(data.plan)}"
    if details:
        text += " — " + "; ".join(details)
    return bool(records or data.deliveries), text


def _reproduce_lines(data: RunData) -> list[str]:
    """Numbered steps of the "How to reproduce" section."""
    target = data.target or "<target>"
    command = command_line(data.run) or _rebuilt_command(data.run, target)
    tally = _tally(data.records)
    outcome = ", ".join(f"{tally[name]} {name}" for name in OUTCOMES if tally[name]) or "no results"
    guide = "docs/setup-enterprise-org.md" if (data.plan or "").lower() == "enterprise" else "docs/setup-free-org.md"
    prepare = (
        f"Prepare a dedicated test organization and machine accounts (otterdog-e2e {md_code(guide)}), "
        f"target {md_code(target)}, then {md_code(f'otterdog-e2e doctor --target {target}')}."
    )
    if not data.live:
        prepare = (
            "Check out otterdog-e2e (offline tiers only: no GitHub organization or token is needed; docker for the "
            "webapp contract tests)."
        )
    steps = [
        prepare,
        f"Run {md_code(command)}.",
        f"Outcome of otterdog-e2e run {md_code(data.run_id)}: {outcome}.",
    ]
    if data.differential is not None:
        unexpected = [
            d for d in data.differential.get("deltas") or [] if isinstance(d, Mapping) and not d.get("expected")
        ]
        steps.append(f"Differential report ({md_code(DIFFERENTIAL_MD)}): {len(unexpected)} unexpected delta(s).")
    return [f"{index}. {step}" for index, step in enumerate(steps, start=1)]


def _rebuilt_command(run: Mapping[str, Any], target: str) -> str:
    """``otterdog-e2e run --target T --sut S [--base-sut B]`` from run.json SUT specs."""
    parts = ["otterdog-e2e", "run", "--target", target]
    for flag, key in (("--sut", "sut"), ("--base-sut", "base")):
        value = run.get(key)
        spec = value if isinstance(value, str) else lookup(value, "spec", "raw", "label")
        if isinstance(spec, str) and spec:
            parts += [flag, spec]
    return shlex.join(parts)


def manual_testing_block(data: RunData) -> str:
    """Markdown for the "Manual testing" and "How to reproduce" sections of otterdog's PR template."""
    live = data.live
    lines = [
        PR_TEMPLATE_MANUAL_TESTING,
        "",
        f"- {_box(not live)} {PR_TEMPLATE_NO_LIVE}",
        f"- {_box(live)} {PR_TEMPLATE_LIVE}",
    ]
    org = f"{md_code(data.org)} (dedicated otterdog-e2e test organization)" if data.org else "-"
    lines.append(f"  - Organization(s) used: {org if live else '-'}")
    lines.append(f"  - GitHub plan: {plan_label(data.plan) if live else '-'}")
    for checked, text in (_cli_line(data), _webapp_line(data), _webhooks_line(data)):
        lines.append(f"  - {_box(live and checked)} {text}")
    lines += ["", PR_TEMPLATE_REPRODUCE, "", *_reproduce_lines(data)]
    return "\n".join(lines)


def section_manual_testing(data: RunData) -> str:
    """The PR-template block as a copyable markdown code block."""
    intro = "Paste into the otterdog pull request description (sections of `.github/pull_request_template.md`):"
    return f"## Manual testing (otterdog PR template)\n\n{intro}\n\n{md_fence(manual_testing_block(data), 'markdown')}"


SECTIONS = (
    section_title,
    section_run,
    section_tiers,
    section_classification,
    section_failures,
    section_skips,
    section_known_bugs,
    section_coverage,
    section_budgets,
    section_rate,
    section_differential,
    section_manual_testing,
    section_scrub,
)


def limit_bytes(text: str, max_bytes: int) -> str:
    """``text`` cut below ``max_bytes`` UTF-8 bytes at a line boundary, open fences/details closed, with a notice."""
    if len(text.encode()) < max_bytes:
        return text
    notice = "\n\n_(summary truncated to stay below the 1 MiB job summary limit; see the run artifacts)_\n"
    budget = max_bytes - len(notice.encode()) - 1024
    kept = text.encode()[:budget].decode("utf-8", errors="ignore").rsplit("\n", 1)[0]
    fence = None
    for line in kept.splitlines():
        match = re.match(r"^(`{3,})", line)
        if match and (fence is None or match.group(1) == fence):
            fence = None if fence else match.group(1)
    if fence:
        kept += f"\n{fence}"
    kept += "\n</details>" * max(0, kept.count("<details>") - kept.count("</details>"))
    return kept + notice


def build_summary(artifacts_dir: Path, *, redactor: Redactor = REDACTOR) -> str:
    """Markdown summary of a run directory (run info, per-tier outcomes, failures, skips, known bugs, coverage
    matrix, budgets, rate budget per identity, differential summary, infra-vs-product classification, "Manual testing"
    block); < 1 MiB. The coverage matrix is the project's (default_coverage_file(); none: no section)."""
    return summary_text(RunData.load(artifacts_dir), redactor=redactor)


def summary_text(data: RunData, *, redactor: Redactor = REDACTOR) -> str:
    """The summary of loaded run data (build_summary; tests pass RunData.load(..., coverage_file=...))."""
    text = "\n\n".join(part for part in (section(data) for section in SECTIONS) if part) + "\n"
    return limit_bytes(redactor(text), SUMMARY_MAX_BYTES)


def write_summary(artifacts_dir: Path, *, redactor: Redactor = REDACTOR) -> Path:
    """build_summary() written to ``<artifacts_dir>/summary.md``."""
    path = artifacts_dir / SUMMARY_FILE
    path.write_text(build_summary(artifacts_dir, redactor=redactor), encoding="utf-8")
    return path


# --- scrubbing ----------------------------------------------------------------------------------------------------
_PATTERNS_ONLY = Redactor()


def _check_scrub_root(root: Path) -> Path:
    """Resolved scrub root; SafetyError for a filesystem root, $HOME or its ancestors, or a source checkout."""
    resolved = root.resolve()
    if not resolved.is_dir():
        raise SafetyError(f"scrub_artifacts: {root} is not a directory")
    try:
        home: Path | None = Path.home().resolve()
    except (KeyError, RuntimeError):
        home = None
    if resolved == Path(resolved.anchor) or (home is not None and home.is_relative_to(resolved)):
        raise SafetyError(f"scrub_artifacts refuses to scrub {resolved} (filesystem root or home directory)")
    for marker in (".git", "pyproject.toml"):
        if (resolved / marker).exists():
            raise SafetyError(
                f"scrub_artifacts refuses to scrub {resolved}: it contains {marker} (not an artifacts dir)"
            )
    return resolved


def _windows(path: Path) -> Iterator[bytes]:
    """File content in overlapping chunks (secrets crossing a chunk boundary stay visible)."""
    with path.open("rb") as handle:
        tail = b""
        while chunk := handle.read(SCAN_CHUNK_BYTES):
            window = tail + chunk
            yield window
            tail = window[-SCAN_OVERLAP_BYTES:]


def secret_match(path: Path, redactor: Redactor) -> str | None:
    """Leak kind ("token pattern" or "registered secret") found in the file content, else None."""
    for window in _windows(path):
        if redactor.contains_secret(window):
            return "token pattern" if _PATTERNS_ONLY.contains_secret(window) else "registered secret"
    return None


@dataclass
class _Scrubber:
    """State of one scrub_artifacts() walk."""

    root: Path
    redactor: Redactor
    leaks: list[dict[str, Any]] = field(default_factory=list)
    removed: list[dict[str, Any]] = field(default_factory=list)
    kept: int = 0

    def relative(self, path: Path) -> str:
        """Redacted POSIX path relative to the root."""
        return self.redactor(path.relative_to(self.root).as_posix())

    def walk(self, directory: Path) -> None:
        """Visit every entry below ``directory`` without following symlinks (unreadable dirs are leaks)."""
        try:
            with os.scandir(directory) as iterator:
                entries = sorted(iterator, key=lambda entry: entry.name)
        except OSError as exc:
            relative = self.relative(directory)
            error = f"{exc.__class__.__name__}: {exc.strerror or exc}"
            self.leaks.append({"path": relative, "reason": "unreadable directory", "deleted": False, "error": error})
            log.error("artifact scrub cannot read directory %s: %s", relative, error)
            return
        for entry in entries:
            path = Path(entry.path)
            if entry.is_symlink():
                self.remove(path, "symlink")
            elif entry.is_dir(follow_symlinks=False):
                self.walk(path)
            elif entry.is_file(follow_symlinks=False):
                self.check_file(path)
            else:
                self.remove(path, "special file")

    def check_file(self, path: Path) -> None:
        """Delete leaking files and files with a non-allowed extension; keep the rest."""
        relative = path.relative_to(self.root).as_posix()
        try:
            match = "secret in file name" if self.redactor(relative) != relative else secret_match(path, self.redactor)
        except OSError as exc:
            match = f"unreadable ({exc.__class__.__name__})"
        if match:
            self.leak(path, match)
        elif path.suffix.lower() not in ALLOWED_ARTIFACT_SUFFIXES:
            self.remove(path, f"extension {path.suffix or '(none)'} not allowed")
        else:
            self.kept += 1

    def leak(self, path: Path, match: str) -> None:
        """Record and delete a leaking file."""
        error = _unlink(path)
        entry: dict[str, Any] = {"path": self.relative(path), "reason": "secret", "match": match, "deleted": not error}
        if error:
            entry["error"] = error
        self.leaks.append(entry)
        log.error("artifact leak: %s (%s)%s", entry["path"], match, " NOT DELETED: " + error if error else "")

    def remove(self, path: Path, reason: str) -> None:
        """Delete a non-allowed entry (an undeletable one becomes a leak: it would be uploaded)."""
        error = _unlink(path)
        entry = {"path": self.relative(path), "reason": reason}
        if error:
            self.leaks.append({**entry, "reason": f"undeletable: {reason}", "deleted": False, "error": error})
            log.error("artifact scrub cannot delete %s: %s", entry["path"], error)
        else:
            self.removed.append(entry)
            log.info("artifact scrub removed %s (%s)", entry["path"], reason)


def _unlink(path: Path) -> str | None:
    """Delete a file or symlink; the error text on failure."""
    try:
        path.unlink()
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{exc.__class__.__name__}: {exc.strerror or exc}"
    return None


def _previous_leaks(root: Path) -> list[dict[str, Any]]:
    """Leaks recorded by an earlier scrub of the same tree (they stay recorded so later CI steps still fail)."""
    data = read_json(root / LEAKS_FILE)
    items = data.get("leaks") if isinstance(data, dict) else None
    return [dict(item, previous=True) for item in items or [] if isinstance(item, dict) and item.get("path")]


def scrub_artifacts(root: Path, redactor: Redactor = REDACTOR) -> list[Path]:
    """Delete non-text artifacts and files containing secrets; returns the deleted leaking files (leaks.json)."""
    if not root.exists():
        return []
    resolved = _check_scrub_root(root)
    previous = _previous_leaks(resolved)
    scrubber = _Scrubber(resolved, redactor)
    scrubber.walk(resolved)
    known = {item["path"] for item in scrubber.leaks}
    leaks = [*(item for item in previous if item["path"] not in known), *scrubber.leaks]
    report = {
        "scrubbed_at": datetime.now(UTC).isoformat(),
        "kept": scrubber.kept,
        "leaks": leaks,
        "removed": scrubber.removed,
    }
    (resolved / LEAKS_FILE).write_text(redactor(json.dumps(report, indent=1)) + "\n", encoding="utf-8")
    return [root / item["path"] for item in leaks]
