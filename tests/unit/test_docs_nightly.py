"""The history of the nightly dashboard (docs_nightly.py): the digest notice read back, the job names of the nightly
parsed, the published history extended with the runs it lacks, everything checked and bounded, and the token sent to
api.github.com only."""

from __future__ import annotations

import importlib
import json
import sys
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from otterdog_acceptance import digest as digest_module

ROOT = Path(__file__).resolve().parents[2]
REPO = "acme/otterdog-acceptance"
SITE = "https://acme.github.io/otterdog-acceptance/"
TOKEN = "ghs_token_of_the_docs_job"


@pytest.fixture(scope="module")
def nightly() -> Iterator[Any]:
    """docs_nightly.py, at the root of the repository."""
    sys.path.insert(0, str(ROOT))
    try:
        yield importlib.import_module("docs_nightly")
    finally:
        sys.path.remove(str(ROOT))


def job(job_id: int, name: str, conclusion: str = "success", **extra: Any) -> dict[str, Any]:
    """A job of the API."""
    return {
        "id": job_id,
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": "2026-11-28T10:22:42Z",
        "completed_at": "2026-11-28T11:43:36Z",
        "html_url": f"https://github.com/{REPO}/actions/runs/1/job/{job_id}",
        **extra,
    }


def run(run_id: int, attempt: int = 1, created: str = "2026-11-28T10:22:09Z") -> dict[str, Any]:
    """A completed run of the API."""
    return {
        "id": run_id,
        "run_attempt": attempt,
        "run_number": run_id % 100,
        "event": "schedule",
        "head_sha": "8bbc05bcb20728dc0cd45b719857c3fa3da986a5",
        "created_at": created,
        "updated_at": created,
        "status": "completed",
        "conclusion": "failure",
        "html_url": f"https://github.com/{REPO}/actions/runs/{run_id}",
    }


MESSAGE_LINES = (
    "766 passed, 1 failed, 0 errors, 61 skipped, 42 xfailed, 0 xpassed",
    "sut: v1.8.0 89ab4aca6d1f",
    "instance: org-level",
    "shard: org-level",
    "session: failure",
    "seconds: 4058",
    "failed: tests/cli/test_scenarios.py::test_cli_scenario[cli.org.variable] · KB-096 · infra",
    "known bugs: KB-090 KB-096 <script>",
)
MESSAGE = "\n".join(MESSAGE_LINES)


class Api:
    """Fake HTTP: the published history, the runs, the jobs and annotations; records every request and its headers."""

    def __init__(self, published: tuple[int, Any] = (404, b""), runs: list[dict[str, Any]] | None = None) -> None:
        """``published``: the answer of the site; ``runs``: the completed runs."""
        self.published = published
        self.runs = runs or []
        self.jobs: dict[int, list[dict[str, Any]]] = {}
        self.annotations: dict[int, list[dict[str, Any]]] = {}
        self.calls: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        """One GET."""
        self.calls.append((url, dict(headers)))
        if url == SITE + "assets/nightly/history.json":
            status, body = self.published
            return status, body if isinstance(body, bytes) else json.dumps(body).encode()
        path = url.removeprefix("https://api.github.com")
        if "/actions/workflows/nightly.yml/runs?" in path:
            return 200, json.dumps({"workflow_runs": self.runs}).encode()
        if "/jobs?" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return 200, json.dumps({"jobs": self.jobs.get(run_id, [])}).encode()
        if "/check-runs/" in path:
            job_id = int(path.split("/check-runs/")[1].split("/")[0])
            return 200, json.dumps(self.annotations.get(job_id, [])).encode()
        return 404, b""


def history(nightly: Any, api: Api, **kwargs: Any) -> dict[str, Any]:
    """collect() with the fake API."""
    client = nightly.Client(api, REPO, TOKEN)
    options = {"instance_shards": {"free": "repos"}, "shards": ["enterprise", "repos", "org-level"], **kwargs}
    return nightly.collect(client, SITE, **options)


# --- the digest notice --------------------------------------------------------------------------------------------
def test_the_notice_title_is_the_one_of_the_digest(nightly: Any) -> None:
    """docs_nightly.py reads the annotation digest.py prints (and docs/assets/nightly.js too)."""
    assert nightly.NOTICE_TITLE == digest_module.NOTICE_TITLE
    script = (ROOT / "docs" / "assets" / "nightly.js").read_text(encoding="utf-8")
    assert f'const NOTICE_TITLE = "{digest_module.NOTICE_TITLE}";' in script


def test_parse_notice(nightly: Any) -> None:
    """Counts, meta, problems with known bugs and the infrastructure flag; values that are not ids are dropped."""
    parsed = nightly.parse_notice(MESSAGE)
    assert parsed["counts"] == {"passed": 766, "failed": 1, "error": 0, "skipped": 61, "xfailed": 42, "xpassed": 0}
    assert (parsed["sut"], parsed["shard"], parsed["session"], parsed["seconds"]) == (
        "v1.8.0 89ab4aca6d1f",
        "org-level",
        "failure",
        4058,
    )
    assert parsed["problems"] == [
        {
            "outcome": "failed",
            "nodeid": "tests/cli/test_scenarios.py::test_cli_scenario[cli.org.variable]",
            "known_bugs": ["KB-096"],
            "infra": True,
        }
    ]
    assert parsed["known_bugs"] == ["KB-090", "KB-096"]
    assert nightly.parse_notice("not a digest") is None and nightly.parse_notice(None) is None


def test_parse_notice_reads_what_the_digest_writes(nightly: Any, tmp_path: Path) -> None:
    """A digest of real run directories, printed by digest.py, read back by docs_nightly.py."""
    directory = tmp_path / "tpdigest1"
    directory.mkdir()
    (directory / "run.json").write_text(json.dumps({"sut": "release:latest"}))
    lines = [
        {"nodeid": "tests/cli/t.py::test[a]", "outcome": "passed"},
        {"nodeid": "tests/cli/t.py::test[b]", "outcome": "failed", "known_bug": "KB-007"},
        {"nodeid": "tests/cli/t.py::test[c]", "outcome": "skipped", "wasxfail": "KB-096: x"},
    ]
    (directory / "results.jsonl").write_text("".join(json.dumps(item) + "\n" for item in lines))
    built = digest_module.build([directory], {"shard": "repos", "session": "failure"})
    parsed = nightly.parse_notice(built.message())
    assert parsed["counts"] == built.counts
    assert parsed["problems"] == [
        {"outcome": "failed", "nodeid": "tests/cli/t.py::test[b]", "known_bugs": ["KB-007"], "infra": False}
    ]
    assert (parsed["known_bugs"], parsed["sut"], parsed["shard"]) == (["KB-096"], "release:latest", "repos")


# --- job names ----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("name", "expected"),
    [
        (
            "release:latest (repos) / e2e repos (release:latest, trusted)",
            ("release:latest", "repos", "e2e repos (release:latest, trusted)"),
        ),
        (
            "branch:main vs release:latest (free) / e2e free (branch:main, trusted)",
            ("branch:main vs release:latest", "free", "e2e free (branch:main, trusted)"),
        ),
        (
            "web-UI tier (release:latest) (org-level) / web-UI org-level (release:latest)",
            ("web-UI tier release:latest", "org-level", "web-UI org-level (release:latest)"),
        ),
        (
            "web-UI tier release:latest (org-level) / web-UI org-level (release:latest)",
            ("web-UI tier release:latest", "org-level", "web-UI org-level (release:latest)"),
        ),
        (
            "release:latest (free) / classify the SUT (no secrets)",
            ("release:latest", "free", "classify the SUT (no secrets)"),
        ),
        ("branch:main vs release:latest", None),
        ("release:latest / e2e", None),
        ("release:latest (<b>x</b>) / e2e", None),
        (None, None),
    ],
)
def test_parse_job_name(nightly: Any, name: Any, expected: Any) -> None:
    """Lane, label and called job of the matrix jobs of the nightly (older names included)."""
    assert nightly.parse_job_name(name) == expected


# --- collection ---------------------------------------------------------------------------------------------------
def test_a_new_history_from_the_runs(nightly: Any) -> None:
    """No published history: the runs, one cell per lane and shard (the session job over its classification), the
    instance of the older names mapped to its shard, the digests of the finished session jobs only."""
    api = Api(runs=[run(11)])
    api.jobs[11] = [
        job(1, "release:latest (free) / classify the SUT (no secrets)"),
        job(2, "release:latest (free) / e2e free (release:latest, trusted)"),
        job(3, "release:latest (org-level) / e2e org-level (release:latest, trusted)", "failure"),
        job(4, "branch:main vs release:latest (enterprise) / classify the SUT (no secrets)", "failure"),
        job(5, "branch:main vs release:latest (enterprise) / e2e enterprise (branch:main, trusted)", "skipped"),
        job(6, "web-UI tier release:latest (org-level) / web-UI org-level (release:latest)", "cancelled"),
        job(7, "branch:main vs release:latest", "skipped"),
    ]
    api.annotations[3] = [
        {"title": "something else", "message": "1 passed"},
        {"title": "otterdog-acceptance results", "message": MESSAGE},
    ]
    data = history(nightly, api)
    assert data["schema"] == 1 and data["repository"] == REPO and data["shards"] == ["enterprise", "repos", "org-level"]
    assert data["instance_shards"] == {"free": "repos"}
    [entry] = data["runs"]
    assert entry["id"] == 11 and entry["event"] == "schedule" and entry["conclusion"] == "failure"
    cells = {(cell["lane"], cell["shard"]): cell for cell in entry["jobs"]}
    assert set(cells) == {
        ("release:latest", "repos"),
        ("release:latest", "org-level"),
        ("branch:main vs release:latest", "enterprise"),
        ("web-UI tier release:latest", "org-level"),
    }
    assert (
        cells[("release:latest", "repos")]["job"].startswith("e2e free")
        and "digest" not in cells[("release:latest", "repos")]
    )
    assert cells[("release:latest", "org-level")]["digest"]["counts"]["passed"] == 766
    assert cells[("branch:main vs release:latest", "enterprise")]["conclusion"] == "skipped"
    annotation_calls = [url for url, _ in api.calls if "/check-runs/" in url]
    assert [url.split("/check-runs/")[1].split("/")[0] for url in annotation_calls] == ["2", "3"]


def test_the_token_goes_to_the_api_only(nightly: Any) -> None:
    """The published history is read without the token; every API request carries it."""
    api = Api(runs=[run(11)])
    history(nightly, api)
    for url, headers in api.calls:
        if url.startswith("https://api.github.com/"):
            assert headers.get("Authorization") == f"Bearer {TOKEN}", url
        else:
            assert "Authorization" not in headers and TOKEN not in json.dumps(headers), url


def test_the_published_history_is_extended(nightly: Any) -> None:
    """Runs of the published history are kept without a request; a run it lacks or whose attempt changed is read;
    at most max_new per build, newest first, the published values checked again."""
    published = {
        "schema": 1,
        "runs": [
            {"id": 10, "attempt": 1, "created_at": "2026-11-27T11:00:02Z", "jobs": [], "url": "javascript:alert(1)"},
            {"id": 9, "attempt": 1, "created_at": "2026-11-26T11:00:02Z", "jobs": []},
            {"id": "x", "attempt": 1},
        ],
    }
    api = Api(
        published=(200, published),
        runs=[
            run(12, created="2026-11-29T10:00:00Z"),
            run(11),
            run(10),
            run(9, attempt=2, created="2026-11-26T11:00:02Z"),
        ],
    )
    data = history(nightly, api, max_new=2)
    assert [entry["id"] for entry in data["runs"]] == [12, 11, 10, 9]
    assert data["runs"][2]["url"] is None, "a link outside the repository is dropped"
    assert data["runs"][3]["attempt"] == 1, "max_new reached: run 9 waits for the next build"
    jobs_calls = [url for url, _ in api.calls if "/jobs?" in url]
    assert len(jobs_calls) == 2
    again = history(nightly, Api(published=(200, data), runs=api.runs), max_new=5)
    assert [entry["attempt"] for entry in again["runs"]] == [1, 1, 1, 2]


def test_the_history_keeps_the_newest_runs(nightly: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    """At most MAX_RUNS runs."""
    monkeypatch.setattr(nightly, "MAX_RUNS", 2)
    api = Api(runs=[run(3, created="2026-11-28T00:00:00Z"), run(2, created="2026-11-27T00:00:00Z"), run(1)])
    assert [entry["id"] for entry in history(nightly, api)["runs"]] == [1, 3]


@pytest.mark.parametrize(
    ("published", "message"),
    [((500, b""), "HTTP 500"), ((200, b"<html>"), "invalid JSON")],
)
def test_an_unreadable_published_history_stops_the_build(nightly: Any, published: Any, message: str) -> None:
    """Never publish a history truncated by a transient error: the build fails, the site stays as it is."""
    with pytest.raises(nightly.CollectError, match=message):
        history(nightly, Api(published=published))


def test_another_schema_starts_a_new_history(nightly: Any) -> None:
    """A published history of another schema is replaced."""
    data = history(nightly, Api(published=(200, {"schema": 99, "runs": [{"id": 1}]}), runs=[run(5)]))
    assert [entry["id"] for entry in data["runs"]] == [5]


def test_sanitize_drops_what_is_not_data(nightly: Any) -> None:
    """Unknown conclusions, non-ids, links leaving the repository and malformed digests are dropped."""
    entry = nightly.sanitize_run(
        {
            "id": 7,
            "event": "pull_request",
            "conclusion": "<img>",
            "sha": "not-a-sha",
            "jobs": [
                {"lane": "release:latest", "shard": "<b>", "job": "e2e x"},
                {
                    "lane": "release:latest",
                    "shard": "repos",
                    "job": "e2e repos",
                    "url": "https://evil.example/",
                    "digest": {"counts": {"passed": -1}},
                },
            ],
        },
        REPO,
    )
    assert (entry["event"], entry["conclusion"], entry["sha"]) == (None, None, None)
    [cell] = entry["jobs"]
    assert cell["shard"] == "repos" and cell["url"] is None and "digest" not in cell
    assert nightly.sanitize_run({"id": True}, REPO) is None


def test_instance_shards(nightly: Any) -> None:
    """E2E_INSTANCE_SHARDS: names only, {} when unset or not JSON."""
    assert nightly.instance_shards('{"free": "repos", "x": "<b>"}') == {"free": "repos"}
    assert nightly.instance_shards("free") == {} and nightly.instance_shards(None) == {}


def test_the_repository_is_checked(nightly: Any) -> None:
    """GITHUB_REPOSITORY must be owner/name."""
    with pytest.raises(nightly.CollectError, match="invalid repository"):
        nightly.Client(Api(), "../etc", None)


def test_main_writes_the_history(nightly: Any, tmp_path: Path) -> None:
    """``collect --out``: the history file; a CollectError exits 1 without writing it."""
    out = tmp_path / "history.json"
    environ = {"GITHUB_REPOSITORY": REPO, "GITHUB_TOKEN": TOKEN, "E2E_INSTANCE_SHARDS": '{"free":"repos"}'}
    api = Api(runs=[run(11)])

    def fetch(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        return api(url.replace(nightly.site_url(ROOT), SITE), headers)

    assert nightly.main(["collect", "--out", str(out)], environ, fetch) == 0
    data = json.loads(out.read_text())
    assert [entry["id"] for entry in data["runs"]] == [11] and data["shards"][0] == "enterprise"
    failing = Api(published=(503, b""))

    def broken(url: str, headers: Mapping[str, str]) -> tuple[int, bytes]:
        return failing(url.replace(nightly.site_url(ROOT), SITE), headers)

    other = tmp_path / "other.json"
    assert nightly.main(["collect", "--out", str(other)], environ, broken) == 1
    assert not other.exists()
