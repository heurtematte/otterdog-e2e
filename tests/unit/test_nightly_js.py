"""docs/assets/nightly.js, the nightly dashboard of the site: it renders data of the GitHub API and of the published
history as text only, and parses job names and digest notices like docs_nightly.py (checked through node when it is
installed)."""

from __future__ import annotations

import importlib
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "docs" / "assets" / "nightly.js"
NAMES = [
    "release:latest (repos) / e2e repos (release:latest, trusted)",
    "branch:main vs release:latest (free) / e2e free (branch:main, trusted)",
    "web-UI tier (release:latest) (org-level) / web-UI org-level (release:latest)",
    "release:latest (free) / classify the SUT (no secrets)",
    "branch:main vs release:latest",
]
NOTICE_LINES = (
    "766 passed, 1 failed, 2 errors, 61 skipped, 42 xfailed, 1 xpassed",
    "sut: v1.8.0 89ab4aca6d1f",
    "shard: org-level",
    "seconds: 4058",
    "failed: tests/cli/test_scenarios.py::test_cli_scenario[cli.org.variable] · KB-096 · infra",
    "error: tests/webapp/test_boot.py::test_webapp_boot",
    "xpassed: tests/cli/test_scenarios.py::test_cli_scenario[cli.kb.fixed] · KB-012",
    "known bugs: KB-090 KB-096",
)
NOTICE = "\n".join(NOTICE_LINES)


@pytest.fixture(scope="module")
def nightly() -> Iterator[Any]:
    """docs_nightly.py, at the root of the repository."""
    sys.path.insert(0, str(ROOT))
    try:
        yield importlib.import_module("docs_nightly")
    finally:
        sys.path.remove(str(ROOT))


def node(code: str) -> Any:
    """Run ``code`` in node with the module's API as ``api``; its JSON output."""
    binary = shutil.which("node")
    if binary is None:
        pytest.skip("node is not installed")
    program = f"const api = require({json.dumps(str(SCRIPT))});\nprocess.stdout.write(JSON.stringify(({code})));"
    result = subprocess.run([binary, "-e", program], capture_output=True, text=True, timeout=30, check=False)
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_strings_are_rendered_as_text_only() -> None:
    """No HTML sink: API and history strings never become markup; links only to github.com."""
    script = SCRIPT.read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert sink not in script, sink
    assert 'href.startsWith("https://github.com/")' in script


def test_the_page_sends_no_credential() -> None:
    """No token, no cookie: the API reads no browser session, the page reads it anonymously."""
    script = SCRIPT.read_text(encoding="utf-8")
    assert "Authorization" not in script and "credentials" not in script
    assert "token" not in script.split("\n", 4)[4].lower()


def test_the_page_polls_within_the_unauthenticated_limit() -> None:
    """At most one job list every 3 minutes and one run list every 10 (60 requests per hour per IP address)."""
    script = SCRIPT.read_text(encoding="utf-8")
    jobs = re.search(r"const JOBS_INTERVAL = (\d+) \* 1000;", script)
    runs = re.search(r"const RUNS_INTERVAL = (\d+) \* 1000;", script)
    assert jobs and runs and int(jobs.group(1)) >= 180 and int(runs.group(1)) >= 600
    assert "document.hidden" in script, "no polling in a hidden tab"


def test_job_names_parse_like_docs_nightly(nightly: Any) -> None:
    """parseJobName of nightly.js and parse_job_name of docs_nightly.py agree."""
    found = node(f"{json.dumps(NAMES)}.map((name) => api.parseJobName(name))")
    expected = [nightly.parse_job_name(name) for name in NAMES]
    assert [[item["lane"], item["label"], item["job"]] if item else None for item in found] == [
        list(item) if item else None for item in expected
    ]


def test_notices_parse_like_docs_nightly(nightly: Any) -> None:
    """parseNotice of nightly.js and parse_notice of docs_nightly.py read the same digest."""
    found = node(f"api.parseNotice({json.dumps(NOTICE)})")
    expected = nightly.parse_notice(NOTICE)
    assert found["counts"] == expected["counts"]
    assert found["problems"] == expected["problems"]
    assert found["known_bugs"] == expected["known_bugs"] == ["KB-090", "KB-096"]
    assert (found["sut"], found["shard"], found["seconds"]) == (expected["sut"], expected["shard"], 4058)
    assert node('api.parseNotice("no digest")') is None


def test_cells_prefer_the_session_job() -> None:
    """One cell per lane and shard: the session job over its classification, the instance mapped to its shard, a
    matrix job skipped as a whole marks its lane."""
    jobs = [
        {"name": "release:latest (free) / classify the SUT (no secrets)", "conclusion": "success"},
        {"name": "release:latest (free) / e2e free (release:latest, trusted)", "status": "in_progress"},
        {"name": "branch:main vs release:latest (${{ fromJSON(vars.X)[matrix.target] }})", "conclusion": "skipped"},
    ]
    found = node(
        f"(() => {{ const cells = api.cellsOf({json.dumps(jobs)}, {{free: 'repos'}});"
        " return {lanes: [...cells.lanes].map(([lane, row]) => [lane, [...row].map(([shard, job]) =>"
        " [shard, job.name, api.stateOf(job)])]), skipped: [...cells.skipped]}; })()"
    )
    assert found == {
        "lanes": [["release:latest", [["repos", jobs[1]["name"], "running"]]]],
        "skipped": ["branch:main vs release:latest"],
    }


def test_counts_and_durations() -> None:
    """The text of a cell."""
    found = node(
        "[api.countsText({passed: 766, failed: 1, error: 0, skipped: 61, xfailed: 42, xpassed: 0}),"
        " api.duration(4058), api.duration(65), api.duration(12), api.stateOf(null),"
        " api.stateOf({status: 'completed', conclusion: 'timed_out'})]"
    )
    assert found == [
        "766 passed · 1 failed · 42 xfailed · 61 skipped",
        "1h 07m",
        "1m 05s",
        "12 s",
        "waiting",
        "failure",
    ]
