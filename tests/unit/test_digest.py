"""The results digest of a CI session (src/otterdog_acceptance/digest.py, ``otterdog-acceptance digest``): the counts,
the SUT, the problem node ids and known bugs of run directories, as the notice the nightly dashboard reads; never a
failure text, and no line break that could start another workflow command."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from otterdog_acceptance import cli
from otterdog_acceptance.digest import MAX_PROBLEMS, NOTICE_TITLE, build, escape_data

RUN = {
    "run_id": "tpdigest1",
    "started_at": "2026-11-28T11:44:08+00:00",
    "finished_at": "2026-11-28T12:51:46+00:00",
    "sut": {"label": "v1.8.0", "sha": "89ab4aca6d1f4443cb9a431a82ca1607600000ff", "spec": "release:latest"},
}
SECRET_FAILURE = "AssertionError: otterdog printed ghp_notpublished and a GitHub comment"


def line(nodeid: str, outcome: str, **extra: Any) -> dict[str, Any]:
    """One results.jsonl line."""
    return {"nodeid": nodeid, "outcome": outcome, "when": "call", "duration": 1.0, **extra}


def write_run(directory: Path, lines: list[dict[str, Any]], run: dict[str, Any] | None = None) -> Path:
    """A run directory with run.json and results.jsonl."""
    directory.mkdir(parents=True)
    (directory / "run.json").write_text(json.dumps(run or RUN))
    (directory / "results.jsonl").write_text("".join(json.dumps(item) + "\n" for item in lines))
    return directory


def sample(tmp_path: Path) -> Path:
    """A session with every outcome."""
    return write_run(
        tmp_path / "tpdigest1",
        [
            line("tests/cli/test_scenarios.py::test_cli_scenario[cli.org.profile]", "passed"),
            line("tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.basic]", "passed"),
            line(
                "tests/cli/test_scenarios.py::test_cli_scenario[cli.org.variable]",
                "skipped",
                wasxfail="KB-096: updating the selected repositories fails (step 'selected-two')",
            ),
            line(
                "tests/cli/test_scenarios.py::test_cli_scenario[cli.org.immutable-releases]",
                "skipped",
                wasxfail="KB-090: ...; KB-090: ...",
            ),
            line("tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.webhook]", "failed", failure=SECRET_FAILURE),
            line(
                "tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.flaky]",
                "failed",
                failure="GitHub answered 502 Bad Gateway",
                infra=True,
            ),
            line("tests/webapp/test_boot.py::test_webapp_boot", "failed", when="setup", failure="boom"),
            line("tests/cli/test_scenarios.py::test_cli_scenario[cli.kb.fixed]", "passed", wasxfail="KB-012: fixed?"),
            line("tests/cli/test_scenarios.py::test_cli_scenario[cli.skip]", "skipped", reason="no capability"),
        ],
    )


def test_the_message_holds_counts_sut_problems_and_known_bugs(tmp_path: Path) -> None:
    """Six counts in a fixed order, the SUT and the meta of the job, the problems (failed, then errors, then xpassed)
    with their known bugs and infrastructure flag, and the known bugs of the xfailed items."""
    digest = build([sample(tmp_path)], {"instance": "free", "shard": "repos", "lane": "nightly-full"})
    lines = digest.message().splitlines()
    assert lines[0] == "2 passed, 2 failed, 1 errors, 1 skipped, 2 xfailed, 1 xpassed"
    assert lines[1:5] == ["sut: v1.8.0 89ab4aca6d1f", "instance: free", "shard: repos", "lane: nightly-full"]
    assert "seconds: 4058" in lines
    problems = [entry for entry in lines if entry.split(":", 1)[0] in ("failed", "error", "xpassed")]
    assert problems == [
        "failed: tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.webhook]",
        "failed: tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.flaky] · infra",
        "error: tests/webapp/test_boot.py::test_webapp_boot",
        "xpassed: tests/cli/test_scenarios.py::test_cli_scenario[cli.kb.fixed] · KB-012",
    ]
    assert lines[-1] == "known bugs: KB-090 KB-096"


def test_no_failure_text_reaches_the_digest(tmp_path: Path) -> None:
    """Failure texts and reasons come from the SUT or GitHub: they stay in the artifacts."""
    message = build([sample(tmp_path)], {}).message()
    for text in ("ghp_notpublished", "AssertionError", "Bad Gateway", "boom", "no capability", "selected-two"):
        assert text not in message


def test_the_notice_cannot_start_another_command(tmp_path: Path) -> None:
    """The message is escaped (%, CR, LF): one line, whatever a node id holds; control characters and the separator
    of a node id are neutralized, long node ids cut."""
    nodeid = "tests/cli/test_x.py::test[a\n::error::injected\r% · KB-1]" + "x" * 400
    directory = write_run(tmp_path / "tpdigest2", [line(nodeid, "failed")])
    digest = build([directory], {"instance": "free\n::error::x"})
    notice = digest.notice()
    assert notice.startswith(f"::notice title={NOTICE_TITLE}::") and "\n" not in notice and "\r" not in notice
    problem = next(entry for entry in digest.message().splitlines() if entry.startswith("failed: "))
    assert "::error::injected" in problem and " · " not in problem and len(problem) <= len("failed: ") + 300
    assert "instance:" not in digest.message(), "a value that is not an identifier is left out"
    assert escape_data("50%\r\n") == "50%25%0D%0A"


def test_problems_beyond_the_limit_are_counted(tmp_path: Path) -> None:
    """At most MAX_PROBLEMS problem lines, then ``more: <n>``."""
    directory = write_run(tmp_path / "tpdigest3", [line(f"tests/cli/t.py::test[{n}]", "failed") for n in range(45)])
    lines = build([directory], {}).message().splitlines()
    assert sum(entry.startswith("failed: ") for entry in lines) == MAX_PROBLEMS
    assert lines[-1] == f"more: {45 - MAX_PROBLEMS}"


def test_a_session_without_run_directory_counts_nothing(tmp_path: Path) -> None:
    """A session that never started (no run directory): zero counts, the SUT spec and the session outcome given."""
    digest = build([tmp_path / "missing"], {"sut": "branch:main", "session": "failure"})
    assert digest.message().splitlines() == [
        "0 passed, 0 failed, 0 errors, 0 skipped, 0 xfailed, 0 xpassed",
        "sut: branch:main",
        "session: failure",
    ]


def test_the_digest_command(tmp_path: Path) -> None:
    """``otterdog-acceptance digest DIR... --github-notice`` prints the notice (the e2e workflow's digest step)."""
    directory = sample(tmp_path)
    result = CliRunner().invoke(
        cli.main,
        [
            *("digest", str(directory), str(tmp_path / "absent")),
            *("--instance", "free", "--shard", "repos", "--session", "success", "--github-notice"),
        ],
    )
    assert result.exit_code == 0, result.output
    assert result.output.startswith(f"::notice title={NOTICE_TITLE}::2 passed, 2 failed, 1 errors")
    assert "%0Ashard: repos%0A" in result.output and "%0Asession: success" in result.output
    plain = CliRunner().invoke(cli.main, ["digest", str(directory)])
    assert plain.exit_code == 0 and plain.output.splitlines()[0].startswith("2 passed")
