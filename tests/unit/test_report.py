"""Unit tests of otterdog_e2e.report: build_summary (sections, PR-template block, size) and scrub_artifacts."""

from __future__ import annotations

import base64
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import report
from otterdog_e2e.differential import ExpectedDelta, compare
from otterdog_e2e.observe import Observation
from otterdog_e2e.redact import Redactor
from otterdog_e2e.report import (
    RunData,
    aggregate_results,
    build_summary,
    fmt_duration,
    limit_bytes,
    line_outcome,
    manual_testing_block,
    rate_usage,
    scrub_artifacts,
    tier_of,
    write_summary,
)
from otterdog_e2e.safety import SafetyError

RUN_ID = "t3c7z8a5"
ORG = "e2e-test-org"
SHA = "d0d3b08" + "1" * 33
SECRET = "e2e-report-secret-0123456789abcdef"
GHP_TOKEN = "ghp_" + "A1b2C3d4E5" * 4
# otterdog .github/pull_request_template.md (upstream main 9bdeb75), "Manual testing" section verbatim
PR_TEMPLATE_EXCERPT = """### Manual testing

<!-- otterdog behavior differs between GitHub plans (e.g. rulesets, branch
protections, custom roles are plan-dependent) — always state the plan used.
Check everything that was actually exercised and fill in the details. -->

- [ ] GitHub API calls only stubbed / mocked in unit tests (no live testing)
- [ ] Tested on a real GitHub organization (live GitHub API):
  - Organization(s) used: <!-- e.g. OtterdogTest -->
  - GitHub plan: <!-- Free / Team / Enterprise Cloud -->
  - [ ] **CLI** — commands run: <!-- e.g. `otterdog plan`, `otterdog apply`, `otterdog validate`, ... -->
  - [ ] **Web app** — pages / flows exercised:
  - [ ] **Webhook interactions** — otterdog bot behavior on PRs (validation / sync checks, bot comments on the config repo PRs); org plan used: <!-- Free / Team / Enterprise Cloud -->

### How to reproduce / test scenario:**
"""


def _jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write JSONL rows."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _cmd(run_dir: Path, relative: str, argv: str) -> None:
    """A redacted cmd.txt copy of OtterdogCli."""
    path = run_dir / relative / "cmd.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(argv + "\n")


def _results() -> list[dict[str, Any]]:
    """results.jsonl of a live pr-fast run (one line per phase for the failing cli test)."""
    cli = "tests/cli/test_scenarios.py::test_scenario"
    return [
        {"nodeid": "tests/offline/test_scenarios.py::test_scenario[O-VAL-OK]", "outcome": "passed", "duration": 12.5,
         "scenario": "O-VAL-OK", "sut": "pr792-d0d3b08", "markers": ["offline", "scenario"]},
        {"nodeid": f"{cli}[cli.repo.lifecycle]", "when": "setup", "outcome": "passed", "duration": 2.0,
         "scenario": "C-REPO-LIFECYCLE", "priority": "P0", "markers": ["live"], "rate": {"admin": {"core": 4000}}},
        {"nodeid": f"{cli}[cli.repo.lifecycle]", "when": "call", "outcome": "failed", "duration": 250.0,
         "failure": f"AssertionError: state mismatch for repo e2e-x-basic\ntoken {SECRET} and {GHP_TOKEN}",
         "rate": {"admin": {"core": 3500, "graphql": 4990}}},
        {"nodeid": f"{cli}[cli.repo.lifecycle]", "when": "teardown", "outcome": "passed", "duration": 1.0,
         "rate": {"admin": {"core": 4900}}},
        {"nodeid": f"{cli}[cli.repo.webhook]", "outcome": "failed", "duration": 30.0, "infra": True,
         "scenario": "C-REPO-WEBHOOK", "failure": "delivery not observed within 300 s (infra)",
         "rate": {"admin": 4800}},
        {"nodeid": f"{cli}[cli.neg.private-ruleset]", "outcome": "skipped", "duration": 0.0,
         "reason": "Skipped: missing capability private_repo_rulesets", "scenario": "C-NEG-PRIVATE-RULESET"},
        {"nodeid": f"{cli}[cli.neg.private-bpr]", "outcome": "skipped", "duration": 0.0,
         "reason": "missing capability private_repo_rulesets", "scenario": "C-NEG-PRIVATE-BPR"},
        {"nodeid": f"{cli}[cli.budget]", "outcome": "skipped", "reason": "github rate budget", "scenario": "C-BUDGET"},
        {"nodeid": f"{cli}[cli.org-variable]", "outcome": "skipped", "wasxfail": "KB-003: unpaginated variable reads",
         "duration": 40.0, "scenario": "C-ORG-VARIABLE", "markers": [{"name": "known_bug", "args": ["KB-003"]}]},
        {"nodeid": f"{cli}[cli.canon]", "outcome": "passed", "wasxfail": "KB-007: canonical-diff labels inverted",
         "duration": 10.0, "scenario": "C-CANON"},
        {"nodeid": "tests/webapp/test_pr_flows.py::test_pr_valid", "outcome": "passed", "duration": 320.0,
         "scenario": "W-PR-VALID", "priority": "P0"},
        {"nodeid": "tests/webhooks/test_app.py::test_app_delivery", "outcome": "passed", "duration": 60.0,
         "scenario": "H-APP-DELIVERY"},
    ]  # fmt: skip


def _differential() -> dict[str, Any]:
    """differential.json with one unexpected and one expected delta."""
    base = [
        Observation("v1.6.1", "base", s, "v", "cli", "validate", "a", {})
        for s in ("O-VAL-RULESET-STRICT", "O-X", "O-SAME")
    ]
    head = [
        Observation("pr792", "head", s, "v", "cli", "validate", c, {})
        for s, c in (("O-VAL-RULESET-STRICT", "b"), ("O-X", "c"), ("O-SAME", "a"))
    ]
    return compare(
        base, head, base_label="v1.6.1", head_label="pr792", expected=[ExpectedDelta("O-VAL-RULESET-STRICT")]
    ).to_json()


@pytest.fixture
def live_run(tmp_path: Path) -> Path:
    """A complete run directory of a live run with every optional input."""
    run_dir = tmp_path / "artifacts" / RUN_ID
    run_dir.mkdir(parents=True)
    run = {
        "run_id": RUN_ID,
        "started_at": "2026-10-02T10:00:00Z",
        "finished_at": "2026-10-02T10:41:10Z",
        "lane": "pr-fast",
        "target": {"name": "free", "org": ORG, "plan": "free"},
        "sut": {
            "spec": f"pr:792@{SHA}",
            "label": "pr792-d0d3b08",
            "sha": SHA,
            "version": "1.7.0.dev19",
            "trusted": False,
        },
        "base": {"spec": "v1.6.1", "label": "v1.6.1", "sha": "a" * 40, "version": "1.6.1", "trusted": True},
        "reset_sut": {
            "spec": "release:latest",
            "label": "v1.6.1",
            "sha": "a" * 40,
            "version": "1.6.1",
            "trusted": True,
        },
        "capabilities": {"plan": "free", "caps": ["public_repos", "secret_scanning_public"], "probes": {}},
        "argv": ["otterdog-e2e", "run", "--target", "free", "--sut", f"pr:792@{SHA}", "--base-sut", "auto"],
    }
    (run_dir / "run.json").write_text(json.dumps(run))
    _jsonl(run_dir / "results.jsonl", _results())
    (run_dir / "differential.json").write_text(json.dumps(_differential()))
    deliveries = [
        {"event": "pull_request", "action": "opened", "relay_status": 204, "lag_seconds": 12.0},
        {"event": "issue_comment", "action": "created", "relay_status": 204},
        {"event": "push", "action": None, "relay_status": 204},
    ]
    _jsonl(run_dir / "webapp" / "deliveries.jsonl", deliveries)
    _cmd(run_dir, "cli/0001-validate", f"/v/bin/otterdog validate -c /s/otterdog.json --local {ORG}")
    _cmd(run_dir, "cli/0002-plan", f"/v/bin/otterdog plan -c /s/otterdog.json -n {ORG}")
    _cmd(run_dir, "cli/0003-plan", f"/v/bin/otterdog plan -c /s/otterdog.json -n -r 'e2e-x-*' {ORG}")
    _cmd(run_dir, "cli/0004-apply", f"/v/bin/otterdog apply -c /s/otterdog.json -f -n {ORG}")
    _cmd(run_dir, "reset/cli/0001-apply", f"/r/bin/otterdog apply -c /s/otterdog.json -f -n -d {ORG}")
    _cmd(run_dir, "base/cli/0001-validate", f"/b/bin/otterdog validate -c /s/otterdog.json {ORG}")
    (run_dir / "cli" / "0005-broken").mkdir()
    return run_dir


@pytest.fixture
def summary(live_run: Path) -> str:
    """build_summary of the live run with SECRET registered."""
    return build_summary(live_run, redactor=Redactor([SECRET]))


# --- results aggregation ------------------------------------------------------------------------------------------
def test_line_outcomes_and_tiers() -> None:
    """pytest outcomes are normalized (xfail/xpass, setup errors, aliases); tiers come from tests/<tier>/."""
    assert line_outcome({"outcome": "skipped", "wasxfail": "KB-1: x"}) == "xfailed"
    assert line_outcome({"outcome": "passed", "wasxfail": "KB-1: x"}) == "xpassed"
    assert line_outcome({"outcome": "failed", "when": "setup"}) == "error"
    assert line_outcome({"outcome": "failed", "when": "call"}) == "failed"
    assert line_outcome({"outcome": "xpass"}) == "xpassed" and line_outcome({"outcome": "weird"}) == "error"
    assert line_outcome({}) == "passed"
    assert tier_of("tests/webapp/test_x.py::test_y") == "webapp"
    assert tier_of("/abs/tests/differential/test_offline_diff.py::t[x]") == "differential"
    assert tier_of("tests/unit/x.py::t", "cli") == "cli" and tier_of("other/test.py::t") == "other"


def test_aggregate_results_merges_phase_lines() -> None:
    """Lines of one node id fold into one record: worst outcome, summed duration, first failure."""
    records = {record.nodeid: record for record in aggregate_results(_results())}
    lifecycle = records["tests/cli/test_scenarios.py::test_scenario[cli.repo.lifecycle]"]
    assert (lifecycle.outcome, lifecycle.duration, lifecycle.tier) == ("failed", 253.0, "cli")
    assert lifecycle.scenario == "C-REPO-LIFECYCLE" and lifecycle.priority == "P0"
    assert lifecycle.failure is not None and lifecycle.failure.startswith("AssertionError: state mismatch")
    assert not lifecycle.is_infra and lifecycle.is_live
    webhook = records["tests/cli/test_scenarios.py::test_scenario[cli.repo.webhook]"]
    assert webhook.is_infra
    xfail = records["tests/cli/test_scenarios.py::test_scenario[cli.org-variable]"]
    assert (xfail.outcome, xfail.known_bug, xfail.reason) == ("xfailed", "KB-003", "KB-003: unpaginated variable reads")
    skipped = records["tests/cli/test_scenarios.py::test_scenario[cli.neg.private-ruleset]"]
    assert skipped.reason == "missing capability private_repo_rulesets" and not skipped.ran
    budget = records["tests/cli/test_scenarios.py::test_scenario[cli.budget]"]
    assert budget.is_infra


def test_rate_usage_ignores_resets() -> None:
    """Used = sum of decreases between consecutive samples; increases (resets) are not counted."""
    stats = rate_usage(_results())
    core = stats[("admin", "core")]
    assert (core.first, core.last, core.lowest, core.used, core.samples) == (4000, 4800, 3500, 600, 4)
    assert stats[("admin", "graphql")].used == 0
    nested = rate_usage([{"rate": {"oracle": {"core": {"remaining": 10}}}}, {"rate": {"oracle": {"remaining": 7}}}])
    assert nested[("oracle", "core")].used == 3


def test_fmt_duration() -> None:
    """Short durations in seconds, then minutes and hours."""
    assert fmt_duration(12.34) == "12.3 s"
    assert fmt_duration(185) == "3m 05s"
    assert fmt_duration(3720) == "1h 02m"


# --- summary sections ---------------------------------------------------------------------------------------------
def test_summary_title_and_run_table(summary: str) -> None:
    """Verdict counts product vs infrastructure failures; the run table describes target and SUTs."""
    assert summary.startswith(f"# otterdog-e2e run `{RUN_ID}`")
    assert "**FAILED**: 1 product failure(s), 1 infrastructure failure(s) out of 10 test(s)." in summary
    assert f"| Target | `free` (org `{ORG}`, plan Free) |" in summary
    assert "| SUT under test | `pr792-d0d3b08` (spec `pr:792@" in summary and "**untrusted**" in summary
    assert "| Base SUT | `v1.6.1` (version `1.6.1`, sha `aaaaaaaaaaaa`, trusted) |" in summary
    reset = "| Reset SUT | `v1.6.1` (spec `release:latest`, version `1.6.1`, sha `aaaaaaaaaaaa`, trusted) |"
    assert reset in summary and "| Lane | `pr-fast` |" in summary
    assert "| Finished | 2026-10-02T10:41:10+00:00 (duration 41m 10s) |" in summary
    assert "| Capabilities | `public_repos`, `secret_scanning_public` |" in summary
    assert "| Command | `otterdog-e2e run --target free --sut pr:792@" in summary


def test_summary_names_the_profile_of_the_instance(live_run: Path) -> None:
    """run.json target.profile (instances bound to profiles): ``instance (profile p, org o, plan P)``."""
    run = json.loads((live_run / "run.json").read_text(encoding="utf-8"))
    run["target"] = {"name": "acme", "profile": "team", "org": ORG, "plan": "team"}
    run.pop("plan", None)
    (live_run / "run.json").write_text(json.dumps(run), encoding="utf-8")
    text = report.build_summary(live_run, redactor=Redactor())
    assert f"| Target | `acme` (profile `team`, org `{ORG}`, plan Team) |" in text


def test_run_overview_and_tally_text(live_run: Path, tmp_path: Path) -> None:
    """The facts a batch summary shows of a run directory (all optional), and outcome counts in OUTCOMES order."""
    overview = report.run_overview(live_run)
    assert (overview["target"], overview["profile"], overview["org"], overview["plan"]) == ("free", None, ORG, "free")
    assert overview["tests"] == 10 and sum(overview["tallies"].values()) == 10
    assert overview["failures"] == 2 and overview["infra_failures"] == 1
    assert str(overview["command"]).startswith("otterdog-e2e run --target free")
    assert report.run_overview(tmp_path / "missing") == {
        "target": None,
        "profile": None,
        "org": None,
        "plan": None,
        "tests": 0,
        "tallies": {},
        "failures": 0,
        "infra_failures": 0,
        "command": None,
    }
    assert report.tally_text({"skipped": 3, "passed": 12, "failed": 0}) == "12 passed, 3 skipped"
    assert report.tally_text({}) == "no results"


def test_summary_tier_table(summary: str) -> None:
    """Per-tier counts (passed, failed, errors, skipped, xfailed, xpassed) and durations."""
    assert "| offline | 1 | 0 | 0 | 0 | 0 | 0 | 12.5 s |" in summary
    assert "| cli | 0 | 2 | 0 | 3 | 1 | 1 | 5m 33s |" in summary
    assert "| webhooks | 1 | 0 | 0 | 0 | 0 | 0 | 1m 00s |" in summary
    assert "| webapp | 1 | 0 | 0 | 0 | 0 | 0 | 5m 20s |" in summary
    assert "| **total** | 3 | 2 | 0 | 3 | 1 | 1 |" in summary


def test_summary_failures_are_short_classified_and_redacted(summary: str) -> None:
    """Failures show product before infra, redacted (registered secrets and token patterns)."""
    product = summary.index("<b>FAILED</b> (product, scenario <code>C-REPO-LIFECYCLE</code>, 4m 13s)")
    infra = summary.index("<b>FAILED</b> (infrastructure, scenario <code>C-REPO-WEBHOOK</code>")
    assert product < infra
    assert "AssertionError: state mismatch for repo e2e-x-basic" in summary
    assert SECRET not in summary and GHP_TOKEN not in summary and "token *** and ***" in summary
    assert "- Product failures (SUT behaviour or scenario assertions): 1 — `C-REPO-LIFECYCLE`" in summary
    assert "- Infrastructure failures (rate limits, delivery lag, docker, network): 1 — `C-REPO-WEBHOOK`" in summary
    assert "- Skipped for infrastructure reasons (e.g. github rate budget): 1" in summary


def test_summary_skips_known_bugs_budgets_rate_differential(summary: str) -> None:
    """Skips by reason, known-bug xfail/xpass tables, budget overruns, rate usage and the differential summary."""
    assert "## Skips by reason (3)" in summary
    assert "| 2 | missing capability private_repo_rulesets | `C-NEG-PRIVATE-RULESET`, `C-NEG-PRIVATE-BPR` |" in summary
    assert "| 1 | github rate budget | `C-BUDGET` |" in summary
    assert (
        "Still reproduced (xfail, 1):" in summary
        and "| KB-003: unpaginated variable reads | `C-ORG-VARIABLE` |" in summary
    )
    assert (
        "Unexpectedly passing (xpass, 1)" in summary
        and "| KB-007: canonical-diff labels inverted | `C-CANON` |" in summary
    )
    assert "| cli scenario C-REPO-LIFECYCLE | 4m 00s | 4m 13s | **over budget** |" in summary
    assert "| webapp flow W-PR-VALID | 5m 00s | 5m 20s | **over budget** |" in summary
    assert "| webapp tier (P0) | 25m 00s | 5m 20s | ok |" in summary
    assert "| offline tier (pr792-d0d3b08) | 10m 00s | 12.5 s | ok |" in summary
    assert "| pr-fast lane | 45m 00s | 41m 10s | ok |" in summary and "never failures" in summary
    assert "| admin | core | 4000 | 4800 | 3500 | 600 |" in summary
    assert "Base `v1.6.1` vs head `pr792`: **1 unexpected**, 1 expected delta(s), 1 unchanged" in summary
    assert "- `O-X / v / cli / validate`" in summary


def test_summary_manual_testing_block_for_a_live_run(summary: str) -> None:
    """The PR-template block is filled from run.json, CLI artifacts, webapp/webhook results and deliveries."""
    block = summary.split("```markdown\n", 1)[1].split("\n```", 1)[0]
    lines = block.splitlines()
    assert lines[0] == "### Manual testing"
    assert "- [ ] GitHub API calls only stubbed / mocked in unit tests (no live testing)" in lines
    assert "- [x] Tested on a real GitHub organization (live GitHub API):" in lines
    assert f"  - Organization(s) used: `{ORG}` (dedicated otterdog-e2e test organization)" in lines
    assert "  - GitHub plan: Free" in lines
    cli_line = next(line for line in lines if "**CLI**" in line)
    assert cli_line.startswith("  - [x] **CLI** — commands run: `otterdog plan` (2), `otterdog apply`")
    assert "validate" not in cli_line
    assert cli_line.endswith("(plus 1 baseline-reset command(s) with the trusted reset SUT, 1 with the base SUT)")
    assert "  - [x] **Web app** — pages / flows exercised: `W-PR-VALID` (passed)" in lines
    webhooks = next(line for line in lines if "**Webhook interactions**" in line)
    assert webhooks.startswith("  - [x] **Webhook interactions** — otterdog bot behavior on PRs")
    assert "org plan used: Free — `H-APP-DELIVERY` (passed); 3 App deliveries relayed" in webhooks
    assert "`pull_request.opened`, `issue_comment.created`, `push`; webapp answered 204: 3)" in webhooks
    assert "### How to reproduce / test scenario:**" in lines
    assert any(line.startswith("2. Run `otterdog-e2e run --target free --sut pr:792@") for line in lines)
    assert any("1 unexpected delta(s)" in line for line in lines)


def _template_lines() -> list[str]:
    """Non-empty lines of the PR template excerpt without HTML comments and trailing blanks."""
    text = re.sub(r"<!--.*?-->", "", PR_TEMPLATE_EXCERPT, flags=re.DOTALL)
    return [line.rstrip() for line in text.splitlines() if line.strip()]


@pytest.mark.parametrize("live", [True, False])
def test_manual_testing_block_mirrors_the_pr_template(live_run: Path, tmp_path: Path, live: bool) -> None:
    """Every line of the template's Manual testing section starts a line of the generated block."""
    directory = live_run if live else tmp_path / "empty"
    generated = [
        re.sub(r"^(\s*- )\[[ x]\]", r"\1[ ]", line)
        for line in manual_testing_block(RunData.load(directory)).splitlines()
    ]
    for line in _template_lines():
        assert any(candidate.startswith(line) for candidate in generated), line


def test_command_line_of_pytest_invocations() -> None:
    """run.json argv holds pytest's invocation args (prefixed with pytest) or a full command line."""
    assert report.command_line({"argv": ["tests/cli", "--e2e-target", "free"]}) == "pytest tests/cli --e2e-target free"
    assert report.command_line({"argv": ["otterdog-e2e", "run", "--sut", "a b"]}) == "otterdog-e2e run --sut 'a b'"
    assert report.command_line({"argv": [], "command": "make e2e"}) == "make e2e"
    harness = {
        "argv": ["/abs/tests/offline", "--e2e-sut=release:latest"],
        "command": "otterdog-e2e run --suite offline",
    }
    assert report.command_line(harness) == "otterdog-e2e run --suite offline"  # the harness command wins
    assert report.command_line({"argv": []}) is None


def test_offline_only_run_checks_the_no_live_box(tmp_path: Path) -> None:
    """Without live items the "stubbed" box is checked and the live items stay unchecked."""
    run_dir = tmp_path / RUN_ID
    rows = [
        {"nodeid": "tests/offline/test_scenarios.py::test_scenario[O-VAL-OK]", "outcome": "passed", "duration": 1.0}
    ]
    _jsonl(run_dir / "results.jsonl", rows)
    _cmd(run_dir, "cli/0001-validate", "otterdog validate --local e2e-offline")
    block = manual_testing_block(RunData.load(run_dir))
    assert "- [x] GitHub API calls only stubbed / mocked in unit tests (no live testing)" in block
    assert "- [ ] Tested on a real GitHub organization (live GitHub API):" in block
    assert "  - Organization(s) used: -" in block and "  - [ ] **CLI** — commands run: none" in block
    assert "1. Check out otterdog-e2e (offline tiers only: no GitHub organization or token is needed" in block
    (run_dir / "run.json").write_text(
        json.dumps({"reset_sut": "release:latest", "command": "otterdog-e2e run --suite offline --sut release:latest"})
    )
    text = build_summary(run_dir, redactor=Redactor())
    assert "**PASSED**: 1 passed, 0 skipped, 0 known-bug xfail(s), 0 xpass(es) out of 1 test(s)." in text
    assert "| Reset SUT | `release:latest` (configured, not used: no baseline reset in this run) |" in text
    assert "2. Run `otterdog-e2e run --suite offline --sut release:latest`." in text


def test_sandboxed_offline_commands_are_not_live_cli_testing(tmp_path: Path) -> None:
    """Commands of the offline tiers (offline/ path part, or an ``unshare -rn`` / ``--network none`` process line)
    never count as live CLI commands, even without --local (``--version``, ``list-projects``)."""
    run_dir = tmp_path / RUN_ID
    _jsonl(
        run_dir / "results.jsonl", [{"nodeid": "tests/offline/test_cli_basics.py::test_version", "outcome": "passed"}]
    )
    sandbox = "# process: unshare -rn /c/build/v1.6.1-cli/.venv/bin/otterdog"
    _cmd(run_dir, "offline/001-test_version/cli/0001-version", f"otterdog --version\n{sandbox} --version")
    _cmd(run_dir, "offline/002-test_list/cli/0002-list-projects", "otterdog list-projects -c /s/otterdog.json")
    _cmd(run_dir, "base/offline/cli/0003-validate", f"otterdog validate --local e2e-offline\n{sandbox} validate")
    docker = "# process: docker run --rm --init --read-only --network none --entrypoint /app/.venv/bin/otterdog img"
    _cmd(run_dir, "head/x/cli/0004-show-default", f"otterdog show-default -c /ws/otterdog.json\n{docker} show-default")
    _cmd(
        run_dir,
        "cli/0005-plan",
        "otterdog plan -c /s/otterdog.json -n e2e-test-org\n# process: /v/bin/otterdog plan -n",
    )
    commands = {cmd.command: cmd for cmd in RunData.load(run_dir).commands}
    assert {name for name, cmd in commands.items() if cmd.offline} == {
        "--version",
        "list-projects",
        "validate",
        "show-default",
    }
    assert commands["--version"].argv == ("otterdog", "--version") and not commands["plan"].offline
    cli_line = next(line for line in manual_testing_block(RunData.load(run_dir)).splitlines() if "**CLI**" in line)
    assert cli_line.endswith("commands run: `otterdog plan` (plus 4 offline command(s) without GitHub access)")
    assert report.sandboxed(("unshare", "-rn", "/v/otterdog", "plan")) and report.sandboxed(("unshare", "--net", "x"))
    assert not report.sandboxed(("unshare", "-r", "/v/otterdog", "plan", "-n"))  # -n of otterdog, not of unshare
    assert report.sandboxed(("docker", "run", "--network=none", "img")) and not report.sandboxed(("docker", "run", "i"))


def test_summary_of_an_empty_or_missing_directory(tmp_path: Path) -> None:
    """No inputs at all still give a summary (and malformed result lines are counted)."""
    assert "**NO RESULTS**" in build_summary(tmp_path / "missing", redactor=Redactor())
    run_dir = tmp_path / "bad"
    run_dir.mkdir()
    (run_dir / "results.jsonl").write_text('not json\n[1]\n{"nodeid": ""}\n')
    (run_dir / "run.json").write_text("{broken")
    text = build_summary(run_dir, redactor=Redactor())
    assert "**NO RESULTS**" in text and "_2 malformed line(s) of results.jsonl were ignored._" in text
    assert f"# otterdog-e2e run `{run_dir.name}`" in text


def test_summary_stays_below_one_mebibyte(tmp_path: Path) -> None:
    """Thousands of long failures are capped (details for the first ones, one line for the rest)."""
    run_dir = tmp_path / RUN_ID
    rows = [
        {"nodeid": f"tests/cli/test_scenarios.py::test_scenario[s{i}]", "outcome": "failed", "failure": "x" * 5000}
        for i in range(400)
    ]
    _jsonl(run_dir / "results.jsonl", rows)
    text = build_summary(run_dir, redactor=Redactor())
    assert len(text.encode()) < report.SUMMARY_MAX_BYTES
    assert text.count("<details>") == report.MAX_FAILURE_DETAILS
    assert "... and 150 more (see results.jsonl)" in text


def test_limit_bytes_closes_open_blocks() -> None:
    """Hard truncation keeps fences and <details> balanced and appends a notice."""
    text = "# t\n\n<details><summary>x</summary>\n\n````text\n" + "line\n" * 2000 + "````\n\n</details>\n"
    cut = limit_bytes(text, 3000)
    assert len(cut.encode()) < 3000 and cut.endswith("see the run artifacts)_\n")
    assert cut.count("````") == 2 and cut.count("</details>") == 1
    assert limit_bytes("short", 3000) == "short"


def test_write_summary(live_run: Path) -> None:
    """write_summary writes summary.md into the run directory."""
    path = write_summary(live_run, redactor=Redactor([SECRET]))
    assert path == live_run / "summary.md" and SECRET not in path.read_text()


# --- scrub_artifacts ----------------------------------------------------------------------------------------------
@pytest.fixture
def artifacts(tmp_path: Path) -> Path:
    """An artifacts run dir with allowed text, disallowed files, leaks and symlinks (plus an outside target)."""
    root = tmp_path / "artifacts" / RUN_ID
    files: dict[str, bytes] = {
        "summary.md": b"# ok\n",
        "run.json": b"{}",
        "results.jsonl": b'{"nodeid": "x"}\n',
        "junit.xml": b"<testsuite/>",
        "cli/0001-plan/stdout.txt": b"Plan: 0 to add\n",
        "webapp/webapp.log": "│ box ✓\n".encode(),
        "screenshot.png": b"\x89PNG\r\n\x1a\n",
        "noext": b"plain",
        ".cache/async_http/responses.sqlite": b"SQLite format 3\x00",
        "cli/0002-apply/stdout.txt": f"leaked {SECRET}\n".encode(),
        "webapp/compose.log": base64.b64encode(f"x-access-token:{SECRET}".encode()),
        "results-extra.json": json.dumps({"t": GHP_TOKEN}).encode(),
        "cache.pickle": b"\x80\x04" + SECRET.encode(),
    }
    for relative, content in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "keep.txt").write_text("outside")
    (root / "link.txt").symlink_to(outside / "keep.txt")
    (root / "linkdir").symlink_to(outside, target_is_directory=True)
    os.mkfifo(root / "fifo.log")
    return root


def test_scrub_keeps_clean_text_and_deletes_everything_else(artifacts: Path, tmp_path: Path) -> None:
    """Allowed clean files stay; other extensions, symlinks and special files go; symlinks are never followed."""
    leaks = scrub_artifacts(artifacts, Redactor([SECRET]))
    kept = sorted(p.relative_to(artifacts).as_posix() for p in artifacts.rglob("*") if p.is_file() or p.is_symlink())
    assert kept == [
        "cli/0001-plan/stdout.txt",
        "junit.xml",
        "leaks.json",
        "results.jsonl",
        "run.json",
        "summary.md",
        "webapp/webapp.log",
    ]
    assert (tmp_path / "outside" / "keep.txt").read_text() == "outside"
    assert sorted(path.relative_to(artifacts).as_posix() for path in leaks) == [
        "cache.pickle",
        "cli/0002-apply/stdout.txt",
        "results-extra.json",
        "webapp/compose.log",
    ]


def test_scrub_writes_leaks_json_without_secrets(artifacts: Path) -> None:
    """leaks.json lists leaks (with the kind of match) and removed entries, never secret values."""
    scrub_artifacts(artifacts, Redactor([SECRET]))
    text = (artifacts / "leaks.json").read_text()
    assert SECRET not in text and GHP_TOKEN not in text
    data = json.loads(text)
    leaks = {item["path"]: item for item in data["leaks"]}
    assert leaks["results-extra.json"]["match"] == "token pattern"
    assert leaks["cli/0002-apply/stdout.txt"]["match"] == "registered secret"
    assert all(item["deleted"] and item["reason"] == "secret" for item in leaks.values())
    removed = {item["path"]: item["reason"] for item in data["removed"]}
    assert removed == {
        ".cache/async_http/responses.sqlite": "extension .sqlite not allowed",
        "fifo.log": "special file",
        "link.txt": "symlink",
        "linkdir": "symlink",
        "noext": "extension (none) not allowed",
        "screenshot.png": "extension .png not allowed",
    }
    assert data["kept"] == 6 and "scrubbed_at" in data


def test_scrub_again_keeps_reporting_previous_leaks(artifacts: Path) -> None:
    """A later scrub (e.g. the CI step after the pytest session) still returns earlier leaks."""
    first = scrub_artifacts(artifacts, Redactor([SECRET]))
    second = scrub_artifacts(artifacts, Redactor([SECRET]))
    assert sorted(second) == sorted(first) and second
    data = json.loads((artifacts / "leaks.json").read_text())
    assert all(item["previous"] for item in data["leaks"]) and data["removed"] == []


def test_scrub_detects_secrets_in_file_names_and_across_chunks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """File names are checked; a secret crossing a read-chunk boundary is still found."""
    monkeypatch.setattr(report, "SCAN_CHUNK_BYTES", 16)
    monkeypatch.setattr(report, "SCAN_OVERLAP_BYTES", 64)
    root = tmp_path / "run"
    root.mkdir()
    (root / f"{SECRET}.txt").write_text("clean")
    (root / "long.log").write_text("." * 25 + SECRET + "." * 40)
    (root / "clean.log").write_text("." * 200)
    leaks = scrub_artifacts(root, Redactor([SECRET]))
    assert sorted(path.name for path in leaks) == ["***.txt", "long.log"]
    assert (root / "clean.log").exists() and not (root / "long.log").exists()
    assert not (root / f"{SECRET}.txt").exists()
    assert SECRET not in (root / "leaks.json").read_text()


def test_scrub_refuses_dangerous_roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Home, its ancestors, the filesystem root, source checkouts and files are refused."""
    home = tmp_path / "home" / "user"
    home.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    for root in (home, home.parent, Path("/")):
        with pytest.raises(SafetyError):
            scrub_artifacts(root)
    checkout = tmp_path / "checkout"
    (checkout / ".git").mkdir(parents=True)
    with pytest.raises(SafetyError, match=re.escape(".git")):
        scrub_artifacts(checkout)
    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\n")
    with pytest.raises(SafetyError, match=re.escape("pyproject.toml")):
        scrub_artifacts(project)
    file_root = tmp_path / "file.txt"
    file_root.write_text("x")
    with pytest.raises(SafetyError, match="not a directory"):
        scrub_artifacts(file_root)
    assert (home.parent / "user").is_dir()


def test_scrub_missing_root_is_a_no_op(tmp_path: Path) -> None:
    """Nothing to scrub: [] and no leaks.json created."""
    assert scrub_artifacts(tmp_path / "missing") == []
    assert not (tmp_path / "missing").exists()


def test_scrub_reports_undeletable_files_as_leaks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A disallowed file that cannot be deleted would be uploaded: it is reported as a leak."""
    root = tmp_path / "run"
    root.mkdir()
    (root / "data.bin").write_bytes(b"\x00")

    def refuse(path: Path) -> str | None:
        """Pretend the file cannot be deleted."""
        return "PermissionError: denied"

    monkeypatch.setattr(report, "_unlink", refuse)
    leaks = scrub_artifacts(root, Redactor())
    assert leaks == [root / "data.bin"]
    entry = json.loads((root / "leaks.json").read_text())["leaks"][0]
    assert entry["reason"] == "undeletable: extension .bin not allowed" and entry["deleted"] is False


def test_scrub_leaves_permissions_of_kept_files(artifacts: Path) -> None:
    """Kept files are untouched (content and mode)."""
    path = artifacts / "summary.md"
    path.chmod(0o640)
    scrub_artifacts(artifacts, Redactor([SECRET]))
    assert path.read_text() == "# ok\n" and stat.S_IMODE(path.stat().st_mode) == 0o640


# --- web-UI tier --------------------------------------------------------------------------------------------------
def test_web_ui_tier_is_a_live_tier_with_a_budget(tmp_path: Path) -> None:
    """tests/web_ui items are the web_ui tier (live, own row), budgeted as a whole (30 min, never a failure)."""
    run_dir = tmp_path / RUN_ID
    rows = [
        {"nodeid": "tests/web_ui/test_web_settings.py::test_web_settings_round_trip", "outcome": "passed",
         "duration": 1500.0, "scenario": "webui.settings.round-trip"},
        {"nodeid": "tests/web_ui/test_web_commands.py::test_review_permissions_lists_requests", "outcome": "passed",
         "duration": 400.0, "scenario": "webui.cmd.review-permissions"},
        {"nodeid": "tests/web_ui/test_web_commands.py::test_web_login_opens_a_session", "outcome": "skipped",
         "reason": "web-login opens a visible browser"},
    ]  # fmt: skip
    _jsonl(run_dir / "results.jsonl", rows)
    data = RunData.load(run_dir, coverage_file=tmp_path / "no-matrix.yaml")
    assert tier_of(rows[0]["nodeid"]) == "web_ui" and all(record.is_live for record in data.records)
    assert data.live and "web_ui" in report.TIERS and "web_ui" in report.LIVE_TIERS
    text = report.summary_text(data, redactor=Redactor())
    assert "| web_ui | 2 | 0 | 0 | 1 | 0 | 0 | 31m 40s |" in text
    assert "| web_ui tier | 30m 00s | 31m 40s | **over budget** |" in text
    assert "## Coverage matrix" not in text  # no matrix file: no section


def test_run_table_web_ui_row(tmp_path: Path) -> None:
    """run.json web_ui (written by the session probe and the login gate) becomes one line of the run table."""
    assert report.web_ui_text({"enabled": True, "session_logins": 8, "waited_seconds": 250.5}) == (
        "enabled, 8 web login(s) of the admin bot, 4m 10s waiting for the login gate"
    )
    assert report.web_ui_text({"enabled": True, "session_logins": 0}) == "enabled"
    reason = "web-UI tests are not allowed: pass --e2e-allow-web-ui (or set E2E_ALLOW_WEB_UI=1)"
    assert report.web_ui_text({"enabled": False, "reason": reason}) == f"disabled ({reason})"
    assert report.web_ui_text({"enabled": False, "reason": None}) == "disabled"
    assert report.web_ui_text(None) is None and report.web_ui_text({"reason": "x"}) is None
    run_dir = tmp_path / RUN_ID
    run_dir.mkdir()
    (run_dir / "run.json").write_text(json.dumps({"web_ui": {"enabled": False, "reason": reason}}))
    text = build_summary(run_dir, redactor=Redactor())
    assert f"| Web UI | disabled ({reason}) |" in text


def test_web_ui_commands_are_named_in_the_cli_line(tmp_path: Path) -> None:
    """Commands whose cmd.txt notes a login of the gate are listed as web-UI commands in the PR template block."""
    run_dir = tmp_path / RUN_ID
    _jsonl(run_dir / "results.jsonl", [{"nodeid": "tests/web_ui/test_web_settings.py::test_x", "outcome": "passed"}])
    gate = "# web_ui: login gate admitted {} after 32.0 s (login #1)"
    _cmd(run_dir, "cli/0001-plan", f"otterdog plan -c /s/otterdog.json {ORG}\n{gate.format('plan')}")
    _cmd(run_dir, "cli/0002-apply", f"otterdog apply -c /s/otterdog.json -f {ORG}\n{gate.format('apply')}")
    _cmd(run_dir, "cli/0003-plan", f"otterdog plan -c /s/otterdog.json -n {ORG}")
    _cmd(
        run_dir, "reset/cli/0001-show-live", f"otterdog show-live -c /s/otterdog.json {ORG}\n{gate.format('show-live')}"
    )
    commands = RunData.load(run_dir).commands
    assert [(cmd.command, cmd.role, cmd.web) for cmd in commands] == [
        ("plan", "sut", True),
        ("apply", "sut", True),
        ("plan", "sut", False),
        ("show-live", "reset", True),
    ]
    cli_line = next(line for line in manual_testing_block(RunData.load(run_dir)).splitlines() if "**CLI**" in line)
    assert cli_line.endswith(
        "commands run: `otterdog plan` (2), `otterdog apply`; through the GitHub web UI (bot login): `otterdog plan`,"
        " `otterdog apply` (plus 1 baseline-reset command(s) with the trusted reset SUT)"
    )


# --- coverage matrix ----------------------------------------------------------------------------------------------
COVERAGE = """
schema_version: 1
otterdog: {repository: eclipse-csi/otterdog, ref: 9bdeb75f3e82a6cbd107d6bc3c9ec90392475c08}
tiers: {offline: o, cli: c, web_ui: w}
features:
  - {id: cli.version, area: cli, tier: offline, priority: P0, status: covered, covered_by: [O-VERSION]}
  - {id: cli.validate, area: cli, tier: offline, priority: P0, status: partial,
     covered_by: ["tests/offline/test_scenarios.py::test_offline_scenario"]}
  - {id: repo.lifecycle, area: repositories, tier: cli, priority: P0, status: covered,
     covered_by: ["tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.lifecycle]"]}
  - {id: repo.archive, area: repositories, tier: cli, priority: P1, status: gap, covered_by: []}
  - {id: webui.round-trip, area: org-settings, tier: web_ui, priority: P1, status: partial,
     covered_by: [webui.settings.round-trip]}
  - {id: webui.login, area: org-settings, tier: web_ui, priority: P2, status: covered,
     covered_by: ["tests/web_ui/test_web_commands.py::test_web_login_opens_a_session"]}
  - {id: broken, status: unknown}
  - not a mapping
"""


def _coverage_run(tmp_path: Path) -> tuple[Path, Path]:
    """(run dir, matrix file): offline, cli and web_ui items, one skipped, one failing, one absolute node id."""
    matrix = tmp_path / "coverage.yaml"
    matrix.write_text(COVERAGE)
    run_dir = tmp_path / RUN_ID
    rows = [
        {"nodeid": "tests/offline/test_cli_basics.py::test_version", "outcome": "passed", "scenario": "O-VERSION"},
        {"nodeid": "/abs/project/tests/offline/test_scenarios.py::test_offline_scenario[O-VAL-OK]",
         "outcome": "passed", "scenario": "O-VAL-OK"},
        {"nodeid": "tests/offline/test_scenarios.py::test_offline_scenario[O-VAL-SYNTAX]", "outcome": "failed",
         "scenario": "O-VAL-SYNTAX", "failure": "AssertionError"},
        {"nodeid": "tests/cli/test_scenarios.py::test_cli_scenario[cli.repo.lifecycle]", "outcome": "skipped",
         "scenario": "cli.repo.lifecycle", "reason": "live test without a target"},
        {"nodeid": "tests/web_ui/test_web_settings.py::test_web_settings_round_trip", "outcome": "skipped",
         "wasxfail": "KB-041: x", "scenario": "webui.settings.round-trip"},
    ]  # fmt: skip
    _jsonl(run_dir / "results.jsonl", rows)
    return run_dir, matrix


def test_load_coverage_reads_features_tiers_and_ref(tmp_path: Path) -> None:
    """Entries without an id or a known status are skipped; tiers keep the matrix order."""
    _run_dir, path = _coverage_run(tmp_path)
    matrix = report.load_coverage(path)
    assert [feature.id for feature in matrix.features] == [
        "cli.version",
        "cli.validate",
        "repo.lifecycle",
        "repo.archive",
        "webui.round-trip",
        "webui.login",
    ]
    assert matrix.tiers == ("offline", "cli", "web_ui") and matrix.ref == "9bdeb75f3e82a6cbd107d6bc3c9ec90392475c08"
    assert matrix.features[1].covered_by == ("tests/offline/test_scenarios.py::test_offline_scenario",)
    (tmp_path / "bad.yaml").write_text("features: {}\n")
    with pytest.raises(report.CoverageError):
        report.load_coverage(tmp_path / "bad.yaml")


def test_exercised_features_match_scenario_ids_and_node_ids(tmp_path: Path) -> None:
    """Scenario ids match records of the scenario, node ids their test (every parametrization without [...]); skipped
    items never exercise a feature, an xfail does; the worst outcome is kept."""
    run_dir, path = _coverage_run(tmp_path)
    data = RunData.load(run_dir, coverage_file=path)
    matrix, error = data.coverage
    assert error is None and matrix is not None
    found = {feature.id: [record.name for record in records] for feature, records in exercised_features(matrix, data)}
    assert found == {
        "cli.version": ["O-VERSION"],
        "cli.validate": ["O-VAL-OK", "O-VAL-SYNTAX"],
        "webui.round-trip": ["webui.settings.round-trip"],
    }
    outcomes = {feature.id: report.worst_outcome(records) for feature, records in exercised_features(matrix, data)}
    assert outcomes == {"cli.version": "passed", "cli.validate": "failed", "webui.round-trip": "xfailed"}
    assert report.relative_nodeid("/a/b/tests/x/test_y.py::t[p]") == "tests/x/test_y.py::t[p]"
    assert report.relative_nodeid("tests/x/test_y.py::t") == "tests/x/test_y.py::t"
    assert report.relative_nodeid("other/test_y.py::t") == "other/test_y.py::t"


def exercised_features(matrix: report.CoverageMatrix, data: RunData) -> list[Any]:
    """report.exercised_features of the run's records."""
    return report.exercised_features(matrix, data.records)


def test_coverage_section_shares_tiers_and_exercised_features(tmp_path: Path) -> None:
    """The summary shows the matrix shares, a per-tier table and the features the run exercised (worst outcome)."""
    run_dir, path = _coverage_run(tmp_path)
    text = report.summary_text(RunData.load(run_dir, coverage_file=path), redactor=Redactor())
    section = text.split("## Coverage matrix", 1)[1].split("\n## ", 1)[0]
    assert (
        "`scenarios/coverage.yaml` (otterdog `9bdeb75`) inventories **6 features**: 3 covered (50%), 2 partial (33%),"
        " 1 gaps (17%); weighted coverage 67% (a partial feature counts half)." in section
    )
    assert (
        "This run exercised **3** of them (50%): the covering items of 1 covered and 2 partial feature(s) ran; worst"
        " outcome per feature: 1 passed, 1 failed, 1 xfailed." in section
    )
    assert "| `offline` | 2 | 1 (50%) | 1 (50%) | 0 (0%) | 75% | 2 (100%) |" in section
    assert "| `cli` | 2 | 1 (50%) | 0 (0%) | 1 (50%) | 50% | 0 (0%) |" in section
    assert "| `web_ui` | 2 | 1 (50%) | 1 (50%) | 0 (0%) | 75% | 1 (50%) |" in section
    assert "| **total** | 6 | 3 (50%) | 2 (33%) | 1 (17%) | 67% | 3 (50%) |" in section
    assert "<details><summary>Features exercised by this run (3)</summary>" in section
    assert "| `cli.validate` | offline | partial | failed | `O-VAL-OK`, `O-VAL-SYNTAX` |" in section
    assert "| `webui.round-trip` | web_ui | partial | xfailed | `webui.settings.round-trip` |" in section
    assert text.index("## Known bugs") < text.index("## Coverage matrix") < text.index("## Manual testing")


def test_coverage_section_without_exercised_features_or_matrix(tmp_path: Path) -> None:
    """No covering item ran: a one-line note and no details; an unreadable matrix: a note; no matrix: no section."""
    _run_dir, path = _coverage_run(tmp_path)
    other = tmp_path / "other"
    _jsonl(other / "results.jsonl", [{"nodeid": "tests/cli/test_x.py::test_y", "outcome": "passed"}])
    text = report.summary_text(RunData.load(other, coverage_file=path), redactor=Redactor())
    assert "No covering item of the matrix ran in this run." in text and "<details>" not in text
    broken = tmp_path / "broken.yaml"
    broken.write_text("features: [unclosed\n")
    section = report.section_coverage(RunData.load(other, coverage_file=broken))
    assert section.startswith("## Coverage matrix\n\n_`scenarios/coverage.yaml` could not be read: ")
    assert "Error: while parsing" in section  # yaml ParserError (one line)
    assert "\n" not in section.split("\n\n", 1)[1] and "| **total** |" not in section
    text = report.summary_text(RunData.load(other, coverage_file=tmp_path / "missing.yaml"), redactor=Redactor())
    assert "## Coverage matrix" not in text


def test_default_coverage_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """E2E_PROJECT_ROOT, else the nearest project root (None without one, or without the file)."""
    (tmp_path / "scenarios").mkdir()
    assert report.default_coverage_file({"E2E_PROJECT_ROOT": str(tmp_path)}) is None
    (tmp_path / "scenarios" / "coverage.yaml").write_text(COVERAGE)
    assert report.default_coverage_file({"E2E_PROJECT_ROOT": str(tmp_path)}) == tmp_path / "scenarios" / "coverage.yaml"

    def no_project() -> Path:
        """Raise like find_project_root outside any project."""
        raise FileNotFoundError("no project")

    monkeypatch.setattr("otterdog_e2e.settings.find_project_root", no_project)
    assert report.default_coverage_file({}) is None


def test_the_project_matrix_loads() -> None:
    """The repository's scenarios/coverage.yaml (the default of build_summary) loads with every tier of the report."""
    path = Path(__file__).resolve().parents[2] / report.COVERAGE_FILE
    matrix = report.load_coverage(path)
    assert len(matrix.features) > 300 and {f.status for f in matrix.features} == set(report.COVERAGE_STATUSES)
    assert set(matrix.tiers) <= set(report.TIERS) and "web_ui" in matrix.tiers
