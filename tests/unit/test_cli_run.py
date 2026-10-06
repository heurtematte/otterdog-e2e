"""Harness CLI: pass-through argument rules, run/pr pytest arguments, sut classify (SPEC 16, 17)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import click
import pytest
from click.testing import CliRunner

from otterdog_e2e import cli
from otterdog_e2e.testing.fakes import FakeGitHubHttp, fake_sha, make_settings

PIN = fake_sha("pr-head")


@pytest.mark.parametrize(
    "arg",
    [
        "--e2e-sut=pr:1@x",
        "--e2e-target",
        "-p",
        "-pno:otterdog_e2e",
        "-vp",
        "-c",
        "-cpytest.ini",
        "-o",
        "-oaddopts=-p x",
        "-l",
        "-vl",
        "--showlocals",
        "--rootdir=/",
        "--confcutdir",
        "--basetemp=/tmp/x",
        "--pyargs",
        "--override-ini=addopts=",
        "--config-file=x.ini",
        "@args.txt",
    ],
)
def test_check_passthrough_rejects(arg: str) -> None:
    """Arguments able to change the SUT, plugins or configuration (or to print locals) are refused."""
    with pytest.raises(click.UsageError, match="not allowed"):
        cli.check_passthrough(["-x", arg])


@pytest.mark.parametrize(
    "arg", ["-x", "-vv", "-rA", "-rfEp", "--lf", "--maxfail=2", "--tb=short", "-W", "error", "tests/cli/test_x.py", "-"]
)
def test_check_passthrough_accepts(arg: str) -> None:
    """Harmless pytest options and paths pass (``-r`` takes its characters as a value)."""
    cli.check_passthrough([arg])


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A project root with suite dirs; pytest.main is captured (returns 3)."""
    for suite in cli.SUITES:
        (tmp_path / "tests" / suite).mkdir(parents=True)
    settings = make_settings(tmp_path)
    captured: dict[str, Any] = {"code": 3}
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: settings)

    def run_pytest(args: list[str], *, command: str | None = None) -> int:
        """Capture the pytest arguments and the recorded harness command."""
        captured["args"], captured["command"] = list(args), command
        return int(captured["code"])

    monkeypatch.setattr(cli, "run_pytest", run_pytest)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    captured["settings"] = settings
    return captured


def test_run_builds_pytest_arguments(project: dict[str, Any]) -> None:
    """Suites map to tests/<suite>, options to --e2e-x=value, -k is attached, pass-through args follow."""
    root = project["settings"].project_root
    result = CliRunner().invoke(
        cli.main,
        [
            *("run", "--suite", "cli", "--suite", "webapp", "--target", "free", "--sut", "branch:main"),
            *("--tags", "smoke,repo", "--scenario", "cli.repo.*", "-k", "not slow", "--run-id", "t3c7z8a5"),
            *("--keep", "-x"),
        ],
    )
    assert result.exit_code == 3, result.output
    assert project["args"] == [
        str(root / "tests" / "cli"),
        str(root / "tests" / "webapp"),
        "--e2e-target=free",
        "--e2e-sut=branch:main",
        "--e2e-tags=smoke,repo",
        "--e2e-scenario=cli.repo.*",
        "--e2e-run-id=t3c7z8a5",
        "--e2e-keep",
        "-knot slow",
        "-x",
    ]
    assert "artifacts:" in result.output and "t3c7z8a5" in result.output
    assert project["command"] == (
        "otterdog-e2e run --suite cli,webapp --target free --sut branch:main --tags smoke,repo --scenario 'cli.repo.*'"
        " -k 'not slow' -x"
    )


def test_run_default_suites_and_new_run_id(project: dict[str, Any]) -> None:
    """Without --suite every e2e tier runs (differential only with a base SUT); a run id is generated."""
    result = CliRunner().invoke(cli.main, ["run", "--base-sut", "auto"])
    assert result.exit_code == 3, result.output
    dirs = [Path(arg).name for arg in project["args"] if not arg.startswith("-")]
    assert dirs == ["offline", "cli", "webhooks", "webapp", "enterprise", "differential"]
    run_id = next(arg for arg in project["args"] if arg.startswith("--e2e-run-id="))
    assert len(run_id.split("=", 1)[1]) == 8


def test_run_accepts_comma_separated_suites(project: dict[str, Any]) -> None:
    """CI passes one suites string: comma lists and repeated --suite both work; unknown suites are refused."""
    result = CliRunner().invoke(cli.main, ["run", "--suite", "offline,cli", "--suite", "webapp", "--tags", ""])
    assert result.exit_code == 3, result.output
    assert [Path(arg).name for arg in project["args"] if not arg.startswith("-")] == ["offline", "cli", "webapp"]
    assert not [arg for arg in project["args"] if arg.startswith("--e2e-tags")]
    result = CliRunner().invoke(cli.main, ["run", "--suite", "offline,bogus"])
    assert result.exit_code == 2 and "bogus" in result.output


REFERENCING_SCENARIO = """\
id: O-VAL-EXAMPLE
title: Example
references:
  - pr: 790
    base: sha:b5f7bb1
    expected_deltas: [{step: no-strict, key: validate}]
steps:
  - name: no-strict
"""


def write_reference(settings: Any, text: str = REFERENCING_SCENARIO) -> Path:
    """A scenario of the project referencing #790."""
    path = settings.scenarios_dir / "offline" / "val-example.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def test_run_change_option(project: dict[str, Any]) -> None:
    """--change is passed as --e2e-change; the base of its references is the default --base-sut, so the default
    suites include differential; an explicit --base-sut wins; a pr: SUT implies its change; invalid changes or
    references are usage errors."""
    path = write_reference(project["settings"])
    result = CliRunner().invoke(cli.main, ["run", "--sut", "sha:9bdeb75", "--change", "#790"])
    assert result.exit_code == 3, result.output
    args = project["args"]
    assert "--e2e-change=790" in args and "--e2e-base-sut=sha:b5f7bb1" in args
    assert project["command"].endswith("--sut sha:9bdeb75 --base-sut sha:b5f7bb1 --change 790")
    assert [Path(arg).name for arg in args if not arg.startswith("-")][-1] == "differential"
    assert "change #790: referencing scenarios O-VAL-EXAMPLE; 1 expected delta(s); base sha:b5f7bb1" in result.output
    project.pop("args")
    result = CliRunner().invoke(
        cli.main, ["run", "--suite", "offline,differential", "--base-sut", "tag:v1.6.0", "--change", "790"]
    )
    assert result.exit_code == 3 and "--e2e-base-sut=tag:v1.6.0" in project["args"]
    project.pop("args")
    result = CliRunner().invoke(cli.main, ["run", "--suite", "offline", "--sut", f"pr:790@{PIN}"])
    assert result.exit_code == 3 and "--e2e-change=790" in project["args"]
    assert "--e2e-base-sut=sha:b5f7bb1" in project["args"]
    project.pop("args")
    result = CliRunner().invoke(cli.main, ["run", "--suite", "offline", "--sut", "sha:9bdeb75"])
    assert result.exit_code == 3 and not [arg for arg in project["args"] if arg.startswith("--e2e-change")]
    project.pop("args")
    result = CliRunner().invoke(cli.main, ["run", "--change", "Not A Change"])
    assert result.exit_code == 2 and "--change" in result.output and "args" not in project
    path.write_text(REFERENCING_SCENARIO.replace("sha:b5f7bb1", "pr:1@x"))
    result = CliRunner().invoke(cli.main, ["run", "--change", "790"])
    assert result.exit_code == 2 and "--change 790" in result.output and "args" not in project


def test_run_rejects_dangerous_passthrough(project: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Rejected pass-through args (or PYTEST_ADDOPTS) are usage errors; pytest never starts."""
    result = CliRunner().invoke(cli.main, ["run", "--suite", "cli", "-p", "evil_plugin"])
    assert result.exit_code == 2 and "not allowed" in result.output
    monkeypatch.setenv("PYTEST_ADDOPTS", "--e2e-sut=pr:1@x")
    result = CliRunner().invoke(cli.main, ["run", "--suite", "cli"])
    assert result.exit_code == 2 and "args" not in project


def test_run_missing_suite_dir(project: dict[str, Any]) -> None:
    """A suite whose directory is missing is a usage error."""
    (project["settings"].project_root / "tests" / "enterprise").rmdir()
    result = CliRunner().invoke(cli.main, ["run", "--suite", "enterprise"])
    assert result.exit_code == 2 and "does not exist" in result.output


@dataclass
class Resolved:
    """Minimal ResolvedSut of a PR."""

    label: str = "pr790-abc1234"
    sha: str = PIN
    trusted: bool = False
    base_sha: str | None = fake_sha("base")
    changed_files: list[str] = field(default_factory=lambda: ["otterdog/webapp/webhook/__init__.py", "README.md"])


def test_pr_plans_tags_change_and_base(project: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """pr: tags from the changed files, the base of the references of the PR, the pinned spec; the scenarios
    referencing the PR stay extra scenarios of the tags filter (read by the plugin from --e2e-change), never an
    --e2e-scenario restriction."""
    settings = project["settings"]
    write_reference(settings, REFERENCING_SCENARIO.replace("sha:b5f7bb1", "tag:v1.6.0"))
    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", lambda spec, settings, http=None: Resolved())
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", lambda token, **kw: FakeGitHubHttp())
    selected: list[list[str]] = []
    monkeypatch.setattr(
        "otterdog_e2e.selection.select_tags", lambda files: selected.append(files) or {"smoke", "webapp"}
    )
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", PIN.upper(), "--target", "free", "--strict-diff"])
    assert result.exit_code == 3, result.output
    args = project["args"]
    assert f"--e2e-sut=pr:790@{PIN}" in args and "--e2e-base-sut=tag:v1.6.0" in args
    tags = next(arg for arg in args if arg.startswith("--e2e-tags=")).split("=", 1)[1].split(",")
    assert tags == ["smoke", "webapp"] and selected == [Resolved().changed_files]
    assert "--e2e-change=790" in args
    assert not [arg for arg in args if arg.startswith("--e2e-scenario")]
    assert "referencing scenarios O-VAL-EXAMPLE" in result.output
    assert "--e2e-strict-diff" in args and "--e2e-target=free" in args
    assert project["command"] == f"otterdog-e2e pr 790 --sha {PIN} --target free --strict-diff"
    dirs = [Path(arg).name for arg in args if not arg.startswith("-")]
    assert dirs == ["offline", "differential", "cli", "webhooks", "webapp", "enterprise"]


def test_pr_change_option(project: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """pr --change: another change than the PR (its references give the base), recorded in the command; the PR's own
    number is the default and never repeated; without a base in the references the base is the merge base (auto)."""
    write_reference(project["settings"], REFERENCING_SCENARIO.replace("pr: 790", "change: check-merge"))
    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", lambda spec, settings, http=None: Resolved())
    monkeypatch.setattr("otterdog_e2e.selection.select_tags", lambda files: {"smoke"})
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", PIN, "--change", "check-merge"])
    assert result.exit_code == 3, result.output
    assert "--e2e-change=check-merge" in project["args"] and "--e2e-base-sut=sha:b5f7bb1" in project["args"]
    assert project["command"] == f"otterdog-e2e pr 790 --sha {PIN} --change check-merge"
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", PIN, "--change", "#790"])
    assert result.exit_code == 3, result.output
    assert "--e2e-change=790" in project["args"] and "--e2e-base-sut=auto" in project["args"]
    assert project["command"] == f"otterdog-e2e pr 790 --sha {PIN}"
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", PIN, "--change", "bad change"])
    assert result.exit_code == 2 and "--change" in result.output


def test_pr_validates_its_arguments(project: dict[str, Any]) -> None:
    """The sha must be a 40-hex pin; suites are validated."""
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", "abc"])
    assert result.exit_code == 2 and "40-hex" in result.output
    assert cli.pr_suites("auto", None) == ("offline", "differential")
    assert cli.pr_suites("offline,cli", "free") == ("offline", "cli")
    with pytest.raises(click.UsageError):
        cli.pr_suites("offline,bogus", None)


def test_classify_trusted_spec_writes_outputs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Trusted specs need no network; GITHUB_OUTPUT gets trust and normalized specs."""
    output = tmp_path / "github-output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    result = CliRunner().invoke(cli.main, ["sut", "classify", "v1.6.1", "--base-sut", "main"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info == {"trust": "trusted", "sut": "tag:v1.6.1", "base_sut": "branch:main", "kind": "tag"}
    assert output.read_text() == "trust=trusted\nsut=tag:v1.6.1\nbase_sut=branch:main\n"


def test_classify_pr_reports_review_details(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Untrusted PR specs: PR details from anonymous reads, step summary with code spans and risky files."""
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    monkeypatch.delenv("GITHUB_OUTPUT", raising=False)
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: make_settings(tmp_path))
    http = FakeGitHubHttp(read_only=True)
    pull = {
        "title": "evil `title`\nnext",
        "user": {"login": "someone"},
        "head": {"sha": PIN, "repo": {"full_name": "someone/otterdog"}},
    }
    http.add("GET", "/repos/eclipse-csi/otterdog/pulls/792", json=pull)
    files = [{"filename": "otterdog/webapp/x.py"}, {"filename": "poetry.lock"}, {"filename": "docker/Dockerfile"}]
    http.add("GET", "/repos/eclipse-csi/otterdog/pulls/792/files", json=files)
    monkeypatch.setattr("otterdog_e2e.github.http.GitHubHttp", lambda token, **kw: http)
    result = CliRunner().invoke(cli.main, ["sut", "classify", f"pr:792@{PIN}"])
    assert result.exit_code == 0, result.output
    info = json.loads(result.output)
    assert info["trust"] == "untrusted" and info["sut"] == f"pr:792@{PIN}" and info["base_sut"] == "auto"
    assert info["pr"]["pin_is_head"] is True and info["pr"]["risky_files"] == ["docker/Dockerfile", "poetry.lock"]
    text = summary.read_text()
    assert "`evil 'title' next`" in text and "`poetry.lock`" in text and "Untrusted SUT" in text


def test_classify_rejects_bad_specs() -> None:
    """Malformed specs (e.g. an unpinned PR) are errors."""
    result = CliRunner().invoke(cli.main, ["sut", "classify", "pr:792"])
    assert result.exit_code == 1 and "pinned" in result.output


def test_run_web_ui_suite_and_allow_flag(project: dict[str, Any]) -> None:
    """--suite web_ui maps to tests/web_ui; --allow-web-ui becomes --e2e-allow-web-ui and is part of the recorded
    command; without the flag the option is never passed (E2E_ALLOW_WEB_UI stays pytest's own fallback)."""
    root = project["settings"].project_root
    result = CliRunner().invoke(
        cli.main, ["run", "--suite", "web_ui", "--target", "free", "--allow-web-ui", "--run-id", "t3c7z8a5"]
    )
    assert result.exit_code == 3, result.output
    assert project["args"] == [
        str(root / "tests" / "web_ui"),
        "--e2e-target=free",
        "--e2e-run-id=t3c7z8a5",
        "--e2e-allow-web-ui",
    ]
    assert project["command"] == "otterdog-e2e run --suite web_ui --target free --allow-web-ui"
    result = CliRunner().invoke(cli.main, ["run", "--suite", "web_ui", "--target", "free"])
    assert result.exit_code == 3 and "--e2e-allow-web-ui" not in project["args"]
    assert "web_ui" in cli.SUITE_HELP and "--allow-web-ui" in CliRunner().invoke(cli.main, ["run", "--help"]).output


def test_run_default_suites_include_web_ui_only_when_allowed(project: dict[str, Any]) -> None:
    """Without --suite, --allow-web-ui adds the web_ui tier (after differential when there is a base SUT)."""
    result = CliRunner().invoke(cli.main, ["run", "--allow-web-ui", "--base-sut", "auto"])
    assert result.exit_code == 3, result.output
    dirs = [Path(arg).name for arg in project["args"] if not arg.startswith("-")]
    assert dirs == ["offline", "cli", "webhooks", "webapp", "enterprise", "differential", "web_ui"]
    assert cli.default_suites(base_sut=None, allow_web_ui=False) == cli.DEFAULT_SUITES
    assert cli.default_suites(base_sut=None, allow_web_ui=True) == (*cli.DEFAULT_SUITES, "web_ui")
    assert cli.parse_suites(["offline,web_ui"]) == ("offline", "web_ui")


def test_request_maps_allow_web_ui_without_changing_other_arguments(tmp_path: Path) -> None:
    """RunRequest.allow_web_ui adds exactly --e2e-allow-web-ui (pytest) and --allow-web-ui (command line)."""
    base = cli.RunRequest(suites=("web_ui",), target="free", strict_diff=True)
    allowed = cli.RunRequest(suites=("web_ui",), target="free", strict_diff=True, allow_web_ui=True)
    (tmp_path / "tests" / "web_ui").mkdir(parents=True)
    assert allowed.pytest_args(tmp_path) == [*base.pytest_args(tmp_path), "--e2e-allow-web-ui"]
    assert allowed.command_line(tmp_path) == base.command_line(tmp_path) + " --allow-web-ui"
    assert not cli.RunRequest(suites=("cli",)).allow_web_ui


def test_pr_passes_allow_web_ui_and_explains_the_untrusted_sut(
    project: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """pr --allow-web-ui maps to --e2e-allow-web-ui and says that a pr: SUT (untrusted) skips the web_ui items; the
    auto suites stay the regression suites."""
    monkeypatch.setattr("otterdog_e2e.sut.spec.parse_sut_spec", lambda raw: raw)
    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", lambda spec, settings, http=None: Resolved())
    monkeypatch.setattr("otterdog_e2e.selection.select_tags", lambda files: {"smoke"})
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", PIN, "--target", "free", "--allow-web-ui"])
    assert result.exit_code == 3, result.output
    assert "--e2e-allow-web-ui" in project["args"] and "untrusted" in result.output
    assert project["command"] == f"otterdog-e2e pr 790 --sha {PIN} --target free --allow-web-ui"
    assert "web_ui" not in [Path(arg).name for arg in project["args"] if not arg.startswith("-")]
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", PIN, "--suite", "web_ui", "--allow-web-ui"])
    assert result.exit_code == 3, result.output
    assert [Path(arg).name for arg in project["args"] if not arg.startswith("-")] == ["web_ui"]
    project.pop("args")
    result = CliRunner().invoke(cli.main, ["pr", "790", "--sha", PIN])
    assert result.exit_code == 3 and "--e2e-allow-web-ui" not in project["args"] and "untrusted" not in result.output


def test_makefile_web_ui_target_runs_the_web_ui_suite() -> None:
    """make web-ui runs the web_ui suite of SUT on TARGET with --allow-web-ui (both exist in the click application)."""
    makefile = (Path(__file__).resolve().parents[2] / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("\nweb-ui: require-target ##", 1)[1].split("\n\n", 1)[0].splitlines()[1]
    assert recipe == (
        '\t$(E2E) run --target "$(TARGET)" --sut "$(SUT)" --suite web_ui --allow-web-ui $(PARALLEL_ARG) $(ARGS)'
    )
    assert "web-ui" in makefile.split(".PHONY:", 1)[1].split("\n\n", 1)[0]
    assert "web_ui" in cli.SUITES and "--allow-web-ui" in {opt for param in cli.run.params for opt in param.opts}
