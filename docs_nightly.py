"""The history of the nightly dashboard (docs/nightly.md): ``python docs_nightly.py collect [--out FILE]``.

The docs workflow runs it on main before the build (pushes, dispatches, and the end of every nightly: workflow_run),
with GITHUB_TOKEN (``actions: read``, ``checks: read``). It reads:

* the history the site already publishes (``site_url`` of zensical.toml + HISTORY_PATH), without a token: the history
  outlives the runs GitHub deletes, and only the runs it lacks cost API requests. A site without one (404) starts an
  empty history; any other failure stops the build, so a transient error never publishes a truncated history;
* the completed runs of nightly.yml on main, their jobs, and for each session job the annotation
  ``otterdog-acceptance results`` that its digest step printed (src/otterdog_acceptance/digest.py, the line format
  parse_notice reads back);

and writes OUT (git-ignored), served as HISTORY_PATH, which docs/assets/nightly.js renders. A build adds at most
MAX_NEW_RUNS runs (the first builds backfill gradually) and keeps the MAX_RUNS newest.

Everything read is data: job names are parsed with fixed patterns, annotation messages with the line format of
digest.py, every value is checked and bounded (sanitize_run), and the page renders strings as text only. The token
is sent to api.github.com only. Standard library and PyYAML only (the docs workflow installs Zensical's packages).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = "zensical.toml"
SHARDS_FILE = Path("scenarios") / "shards.yaml"
API = "https://api.github.com"
WORKFLOW = "nightly.yml"
BRANCH = "main"
EVENTS = frozenset({"schedule", "workflow_dispatch"})
HISTORY_PATH = "assets/nightly/history.json"
OUT = Path("docs") / HISTORY_PATH
SCHEMA = 1
MAX_RUNS = 60
MAX_NEW_RUNS = 10
RUNS_PAGE = 30
TIMEOUT = 30.0
MAX_BODY = 8 * 1024 * 1024
NOTICE_TITLE = "otterdog-acceptance results"  # digest.NOTICE_TITLE (tests/unit/test_docs_nightly.py)
COUNTED = ("passed", "failed", "error", "skipped", "xfailed", "xpassed")
PROBLEM_OUTCOMES = ("failed", "error", "xpassed")
CONCLUSIONS = frozenset({"success", "failure", "cancelled", "skipped", "timed_out", "action_required", "neutral"})
MAX_TEXT = 300
MAX_PROBLEMS = 30
SEPARATOR = " · "
_COUNTS_RE = re.compile(
    r"^(?P<passed>\d+) passed, (?P<failed>\d+) failed, (?P<error>\d+) errors, (?P<skipped>\d+) skipped, "
    r"(?P<xfailed>\d+) xfailed, (?P<xpassed>\d+) xpassed$"
)
_KEY_RE = re.compile(r"^(?P<key>[a-z][a-z ]*): (?P<value>.*)$")
_LABEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+-]{0,99}$")
_SUT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+-]{0,99}( [0-9a-f]{7,40})?$")
_KB_RE = re.compile(r"^KB-\d{1,5}$")
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_TIME_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
_REPO_RE = re.compile(r"^[A-Za-z0-9-]{1,39}/[A-Za-z0-9._-]{1,100}$")
# "release:latest (repos) / e2e repos (release:latest, trusted)": the matrix job of the caller, then the called job
_CALLER_RE = re.compile(r"^(?P<lane>.+?) \((?P<label>[^()]+)\)$")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]+")

log = logging.getLogger("docs_nightly")

Fetch = Callable[[str, Mapping[str, str]], tuple[int, bytes]]


class CollectError(RuntimeError):
    """The history cannot be built (the build stops, the published site stays as it is)."""


# --- values -----------------------------------------------------------------------------------------------------------
def text(value: Any, limit: int = MAX_TEXT) -> str | None:
    """A one-line string of at most ``limit`` characters, None when ``value`` is not a non-empty string."""
    if not isinstance(value, str):
        return None
    cleaned = _CONTROL_RE.sub(" ", value).strip()
    return (cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…") or None


def matching(value: Any, pattern: re.Pattern[str]) -> str | None:
    """``value`` when it is a string matching ``pattern``."""
    return value if isinstance(value, str) and pattern.match(value) else None


def list_of(value: Any) -> list[Any]:
    """``value`` when it is a list, else []."""
    return value if isinstance(value, list) else []


def count(value: Any, maximum: int = 10**7) -> int | None:
    """A non-negative int below ``maximum``."""
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < maximum else None


def utc(value: Any) -> str | None:
    """An ISO timestamp as ``YYYY-MM-DDTHH:MM:SSZ``."""
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def github_url(value: Any, repo: str) -> str | None:
    """A link into the repository on github.com."""
    prefix = f"https://github.com/{repo}/"
    return value if isinstance(value, str) and value.startswith(prefix) and len(value) < 300 else None


# --- the digest annotation ----------------------------------------------------------------------------------------
def parse_notice(message: Any) -> dict[str, Any] | None:
    """The digest of an ``otterdog-acceptance results`` annotation (digest.Digest.message), None when it is not one."""
    if not isinstance(message, str):
        return None
    lines = message.splitlines()
    match = _COUNTS_RE.match(lines[0].strip()) if lines else None
    if not match:
        return None
    digest: dict[str, Any] = {
        "counts": {name: int(match.group(name)) for name in COUNTED},
        "problems": [],
        "known_bugs": [],
    }
    for line in lines[1:]:
        found = _KEY_RE.match(line.strip())
        if not found:
            continue
        key, value = found.group("key"), found.group("value").strip()
        if key in PROBLEM_OUTCOMES:
            parts = value.split(SEPARATOR)
            nodeid = text(parts[0])
            if nodeid and len(digest["problems"]) < MAX_PROBLEMS:
                digest["problems"].append(
                    {
                        "outcome": key,
                        "nodeid": nodeid,
                        "known_bugs": [part for part in parts[1:] if _KB_RE.match(part)],
                        "infra": "infra" in parts[1:],
                    }
                )
        elif key == "known bugs":
            digest["known_bugs"] = [kb for kb in value.split() if _KB_RE.match(kb)]
        elif key in ("seconds", "more") and value.isdigit():
            digest[key] = int(value)
        elif key == "sut":
            digest["sut"] = matching(value, _SUT_RE)
        elif key in ("instance", "shard", "lane", "session"):
            digest[key] = matching(value, _LABEL_RE)
    return sanitize_digest(digest)


def sanitize_digest(data: Any) -> dict[str, Any] | None:
    """A digest with checked values only (None when it has no counts)."""
    if not isinstance(data, Mapping) or not isinstance(data.get("counts"), Mapping):
        return None
    counts = {name: count(data["counts"].get(name)) for name in COUNTED}
    if any(value is None for value in counts.values()):
        return None
    problems = []
    for problem in list_of(data.get("problems")):
        if not isinstance(problem, Mapping) or problem.get("outcome") not in PROBLEM_OUTCOMES:
            continue
        nodeid = text(problem.get("nodeid"))
        if nodeid:
            kbs = list_of(problem.get("known_bugs"))
            problems.append(
                {
                    "outcome": problem["outcome"],
                    "nodeid": nodeid,
                    "known_bugs": [kb for kb in kbs if matching(kb, _KB_RE)][:10],
                    "infra": problem.get("infra") is True,
                }
            )
    known = list_of(data.get("known_bugs"))
    digest: dict[str, Any] = {
        "counts": counts,
        "problems": problems[:MAX_PROBLEMS],
        "known_bugs": [kb for kb in known if matching(kb, _KB_RE)][:200],
    }
    for key in ("seconds", "more"):
        if count(data.get(key)) is not None:
            digest[key] = data[key]
    if matching(data.get("sut"), _SUT_RE):
        digest["sut"] = data["sut"]
    for key in ("instance", "shard", "lane", "session"):
        if matching(data.get(key), _LABEL_RE):
            digest[key] = data[key]
    return digest


# --- jobs and runs ------------------------------------------------------------------------------------------------
def parse_job_name(name: Any) -> tuple[str, str, str] | None:
    """(lane, label, called job) of a job of a nightly matrix (``release:latest (repos) / e2e repos (...)``): the lane
    without parentheses (``web-UI tier (release:latest)`` of the older runs reads ``web-UI tier release:latest``), the
    label (a shard, an instance in the runs before the shard names) and the job of the called workflow."""
    if not isinstance(name, str) or " / " not in name:
        return None
    caller, called = name.split(" / ", 1)
    match = _CALLER_RE.match(caller.strip())
    if not match:
        return None
    lane = " ".join(match.group("lane").replace("(", " ").replace(")", " ").split())
    lane_text, label, called_text = text(lane, 100), matching(match.group("label"), _LABEL_RE), text(called, 200)
    if not (lane_text and label and called_text):
        return None
    return lane_text, label, called_text


def is_session(called: str) -> bool:
    """The job of a session (``e2e <label> (...)``, ``web-UI <label> (...)``), not the classification before it."""
    return called.startswith(("e2e ", "web-UI "))


def job_entry(
    job: Mapping[str, Any], digest: dict[str, Any] | None, instance_shards: Mapping[str, str], repo: str
) -> dict[str, Any] | None:
    """One cell of a run: lane, shard, the job's conclusion, times and link, and its digest."""
    parsed = parse_job_name(job.get("name"))
    if parsed is None:
        return None
    lane, label, called = parsed
    shard = (digest or {}).get("shard") or instance_shards.get(label, label)
    entry: dict[str, Any] = {
        "lane": lane,
        "shard": shard,
        "job": called,
        "status": job.get("status") if job.get("status") in ("queued", "in_progress", "completed") else None,
        "conclusion": job.get("conclusion") if job.get("conclusion") in CONCLUSIONS else None,
        "started_at": utc(job.get("started_at")),
        "completed_at": utc(job.get("completed_at")),
        "url": github_url(job.get("html_url"), repo),
    }
    if digest:
        entry["digest"] = digest
    return entry


def cells(entries: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One entry per (lane, shard): the session job, else the job that ran before it (a failed classification)."""
    chosen: dict[tuple[str, str], dict[str, Any]] = {}
    for entry in entries:
        key = (entry["lane"], entry["shard"])
        current = chosen.get(key)
        if current is None or (is_session(entry["job"]) and not is_session(current["job"])):
            chosen[key] = entry
    return list(chosen.values())


def run_entry(run: Mapping[str, Any], jobs: list[dict[str, Any]], repo: str) -> dict[str, Any] | None:
    """A run of the history (sanitize_run checks it)."""
    return sanitize_run(
        {
            "id": run.get("id"),
            "attempt": run.get("run_attempt"),
            "number": run.get("run_number"),
            "event": run.get("event"),
            "sha": run.get("head_sha"),
            "created_at": run.get("created_at"),
            "updated_at": run.get("updated_at"),
            "conclusion": run.get("conclusion"),
            "url": run.get("html_url"),
            "jobs": jobs,
        },
        repo,
    )


def sanitize_run(data: Any, repo: str) -> dict[str, Any] | None:
    """A run of the history with checked values only, None when it is not one (the previous history is data too)."""
    if not isinstance(data, Mapping):
        return None
    run_id = count(data.get("id"), 10**15)
    if run_id is None:
        return None
    jobs = []
    for job in list_of(data.get("jobs")):
        if not isinstance(job, Mapping):
            continue
        lane, shard, called = text(job.get("lane"), 100), matching(job.get("shard"), _LABEL_RE), text(job.get("job"))
        if not (lane and shard and called):
            continue
        entry: dict[str, Any] = {
            "lane": lane,
            "shard": shard,
            "job": called,
            "status": job.get("status") if job.get("status") in ("queued", "in_progress", "completed") else None,
            "conclusion": job.get("conclusion") if job.get("conclusion") in CONCLUSIONS else None,
            "started_at": utc(job.get("started_at")),
            "completed_at": utc(job.get("completed_at")),
            "url": github_url(job.get("url"), repo),
        }
        digest = sanitize_digest(job.get("digest"))
        if digest:
            entry["digest"] = digest
        jobs.append(entry)
    return {
        "id": run_id,
        "attempt": count(data.get("attempt"), 1000) or 1,
        "number": count(data.get("number")),
        "event": data.get("event") if data.get("event") in EVENTS else None,
        "sha": matching(data.get("sha"), _SHA_RE),
        "created_at": utc(data.get("created_at")),
        "updated_at": utc(data.get("updated_at")),
        "conclusion": data.get("conclusion") if data.get("conclusion") in CONCLUSIONS else None,
        "url": github_url(data.get("url"), repo),
        "jobs": jobs[:100],
    }


# --- HTTP ---------------------------------------------------------------------------------------------------------
class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """API requests never follow a redirect (the token stays on api.github.com)."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        """Refuse every redirect: the 3xx answer is returned as is."""


def urllib_fetch(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
    """GET ``url``: (status, body of at most MAX_BODY bytes); redirects followed only without Authorization."""
    if not url.startswith("https://"):
        raise CollectError(f"GET {url}: only https URLs are read")
    handlers = [_NoRedirect()] if "Authorization" in headers else []
    opener = urllib.request.build_opener(*handlers)
    request = urllib.request.Request(url, headers={"User-Agent": "otterdog-acceptance-docs", **headers})  # noqa: S310 (https only)
    try:
        with opener.open(request, timeout=TIMEOUT) as response:
            return response.status, response.read(MAX_BODY + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(MAX_BODY + 1) if exc.fp else b""
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise CollectError(f"GET {url}: {exc}") from None


class Client:
    """The reads of the collector: the published history (no token) and the API (the token, if any)."""

    def __init__(self, fetch: Fetch, repo: str, token: str | None) -> None:
        """``repo``: owner/name; ``token``: GITHUB_TOKEN (None: unauthenticated, 60 requests per hour)."""
        if not _REPO_RE.match(repo):
            raise CollectError(f"invalid repository {repo!r} (owner/name)")
        self.fetch, self.repo, self.token = fetch, repo, token
        self.requests = 0

    def api(self, path: str) -> Any:
        """GET ``API + path`` as JSON (CollectError unless 200)."""
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.requests += 1
        status, body = self.fetch(f"{API}{path}", headers)
        if status != 200:
            raise CollectError(f"GET {path}: HTTP {status}")
        return _json(body, path)

    def published(self, site_url: str) -> list[dict[str, Any]]:
        """The runs of the history the site publishes ([] when it has none yet: 404, another schema)."""
        url = site_url.rstrip("/") + "/" + HISTORY_PATH
        status, body = self.fetch(url, {"Accept": "application/json"})
        if status == 404:
            log.info("no published history at %s: a new one starts", url)
            return []
        if status != 200:
            raise CollectError(f"GET {url}: HTTP {status} (the published history is kept: the build stops)")
        data = _json(body, url)
        if not isinstance(data, Mapping) or data.get("schema") != SCHEMA or not isinstance(data.get("runs"), list):
            log.warning("the published history is not of schema %d: a new one starts", SCHEMA)
            return []
        return [run for item in data["runs"] if (run := sanitize_run(item, self.repo))]

    def runs(self) -> list[Mapping[str, Any]]:
        """The completed runs of WORKFLOW on BRANCH (scheduled or dispatched), newest first."""
        data = self.api(
            f"/repos/{self.repo}/actions/workflows/{WORKFLOW}/runs?branch={BRANCH}&status=completed&per_page={RUNS_PAGE}"
        )
        runs = data.get("workflow_runs") if isinstance(data, Mapping) else None
        return [run for run in runs or [] if isinstance(run, Mapping) and run.get("event") in EVENTS]

    def jobs(self, run_id: int) -> list[Mapping[str, Any]]:
        """The jobs of the latest attempt of a run."""
        data = self.api(f"/repos/{self.repo}/actions/runs/{run_id}/jobs?filter=latest&per_page=100")
        jobs = data.get("jobs") if isinstance(data, Mapping) else None
        return [job for job in jobs or [] if isinstance(job, Mapping)]

    def digest(self, job_id: int) -> dict[str, Any] | None:
        """The digest annotation of a job (None without one)."""
        data = self.api(f"/repos/{self.repo}/check-runs/{job_id}/annotations?per_page=50")
        for annotation in data if isinstance(data, list) else []:
            if isinstance(annotation, Mapping) and annotation.get("title") == NOTICE_TITLE:
                return parse_notice(annotation.get("message"))
        return None


def _json(body: bytes, where: str) -> Any:
    """``body`` as JSON (CollectError when too large or invalid)."""
    if len(body) > MAX_BODY:
        raise CollectError(f"{where}: answer larger than {MAX_BODY} bytes")
    try:
        return json.loads(body)
    except ValueError as exc:
        raise CollectError(f"{where}: invalid JSON ({exc})") from None


# --- collection ---------------------------------------------------------------------------------------------------
def fetch_run(client: Client, run: Mapping[str, Any], instance_shards: Mapping[str, str]) -> dict[str, Any] | None:
    """A completed run with its cells (the digest of every completed session job)."""
    run_id = count(run.get("id"), 10**15)
    if run_id is None:
        return None
    entries = []
    for job in client.jobs(run_id):
        parsed = parse_job_name(job.get("name"))
        if parsed is None:
            continue
        job_id = count(job.get("id"), 10**15)
        digest = None
        if job_id is not None and is_session(parsed[2]) and job.get("conclusion") in ("success", "failure"):
            digest = client.digest(job_id)
        if (entry := job_entry(job, digest, instance_shards, client.repo)) is not None:
            entries.append(entry)
    return run_entry(run, cells(entries), client.repo)


def collect(
    client: Client,
    site_url: str,
    *,
    instance_shards: Mapping[str, str],
    shards: Sequence[str],
    max_new: int = MAX_NEW_RUNS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """The history: the published runs, plus at most ``max_new`` runs it lacks (or whose attempt changed)."""
    previous = {run["id"]: run for run in client.published(site_url)}
    added = 0
    for run in client.runs():
        known = previous.get(count(run.get("id"), 10**15) or -1)
        if known is not None and known["attempt"] == (count(run.get("run_attempt"), 1000) or 1):
            continue
        if added >= max_new:
            log.info("%d new run(s) per build: the next builds add the older ones", max_new)
            break
        entry = fetch_run(client, run, instance_shards)
        if entry is not None:
            previous[entry["id"]] = entry
            added += 1
    runs = sorted(previous.values(), key=lambda run: (run["created_at"] or "", run["id"]), reverse=True)[:MAX_RUNS]
    log.info("history: %d run(s), %d added, %d API request(s)", len(runs), added, client.requests)
    return {
        "schema": SCHEMA,
        "generated_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": client.repo,
        "workflow": WORKFLOW,
        "shards": list(shards),
        "instance_shards": dict(instance_shards),
        "runs": runs,
    }


def dashboard_block() -> str:
    """The mount point of docs/assets/nightly.js, the line ``<!-- site:nightly -->`` of docs/nightly.md on the site (the
    source keeps a comment, which github.com hides): the workflow and the history it reads, relative to the page."""
    return (
        f'<div class="e2e-nightly" data-workflow="{WORKFLOW}" data-history="../{HISTORY_PATH}">\n'
        "<p>This dashboard needs JavaScript: it reads the public GitHub API from your browser.</p>\n"
        "</div>\n"
    )


def site_url(root: Path) -> str:
    """``site_url`` of zensical.toml."""
    project = tomllib.loads((root / CONFIG).read_text(encoding="utf-8")).get("project") or {}
    url = project.get("site_url")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise CollectError(f"{CONFIG}: no https site_url")
    return url


def shard_order(root: Path) -> list[str]:
    """The shards of scenarios/shards.yaml, in their order ([] without the file)."""
    path = root / SHARDS_FILE
    if not path.is_file():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    shards = data.get("shards") if isinstance(data, Mapping) else None
    return [name for name in shards or {} if isinstance(name, str) and _LABEL_RE.match(name)]


def instance_shards(value: str | None) -> dict[str, str]:
    """E2E_INSTANCE_SHARDS (the repository variable ci-sync writes: {instance: shard}); {} when unset or invalid."""
    try:
        data = json.loads(value) if value else {}
    except ValueError:
        log.warning("E2E_INSTANCE_SHARDS is not JSON: the instances keep their names")
        return {}
    if not isinstance(data, Mapping):
        return {}
    return {key: shard for key, shard in data.items() if matching(key, _LABEL_RE) and matching(shard, _LABEL_RE)}


def main(
    argv: Sequence[str] | None = None, environ: Mapping[str, str] | None = None, fetch: Fetch = urllib_fetch
) -> int:
    """``collect``: write the history (module docstring); GITHUB_REPOSITORY, GITHUB_TOKEN and E2E_INSTANCE_SHARDS
    from the environment."""
    parser = argparse.ArgumentParser(prog="docs_nightly.py", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("collect",))
    parser.add_argument("--out", type=Path, default=ROOT / OUT, help=f"the history file (default: {OUT})")
    parser.add_argument("--max-new", type=int, default=MAX_NEW_RUNS, help="runs added at most")
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    environ = os.environ if environ is None else environ
    try:
        client = Client(fetch, environ.get("GITHUB_REPOSITORY", ""), environ.get("GITHUB_TOKEN") or None)
        history = collect(
            client,
            site_url(ROOT),
            instance_shards=instance_shards(environ.get("E2E_INSTANCE_SHARDS")),
            shards=shard_order(ROOT),
            max_new=options.max_new,
        )
    except CollectError as exc:
        log.error("%s", exc)
        return 1
    options.out.parent.mkdir(parents=True, exist_ok=True)
    options.out.write_text(json.dumps(history, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    log.info("wrote %s", options.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
