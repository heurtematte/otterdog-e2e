"""``otterdog-e2e inject``: option checks, the generated scenario, the pytest arguments and the final report
(pytest.main is replaced: no session, no otterdog, no GitHub)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from click.testing import CliRunner

from otterdog_e2e import cli
from otterdog_e2e.inject import ADHOC_ENV, InjectRequest, write_adhoc_result
from otterdog_e2e.scenarios.model import load_adhoc_scenario
from otterdog_e2e.testing.fakes import make_settings

RUN_ID = "t3c7z8a5"
REPO = "orgs.newRepo('{{ p }}-x') { description: 'injected' }\n"


@pytest.fixture
def session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Settings below tmp_path; run_pytest captures its arguments, the scenario it is given and writes what a
    session would (results.jsonl, adhoc/result.json, the exported config), then returns ``code``."""
    settings = make_settings(tmp_path)
    captured: dict[str, Any] = {"code": 0, "outcome": "passed"}
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: settings)
    monkeypatch.delenv(ADHOC_ENV, raising=False)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)

    def run_pytest(args: list[str], *, command: str | None = None) -> int:
        """Record the call and fake the artifacts of the ad-hoc item."""
        scenario_file = Path(os.environ[ADHOC_ENV])
        captured.update(args=list(args), command=command, scenario_file=scenario_file)
        captured["scenario"] = load_adhoc_scenario(scenario_file)
        run_dir = settings.artifacts_root / RUN_ID
        config = run_dir / "adhoc" / "workspace" / "e2e-offline.jsonnet.txt"
        config.parent.mkdir(parents=True, exist_ok=True)
        config.write_text("orgs.newOrg('e2e-offline') {}\n")
        steps = [{"name": "inject", "validate": {"ok": True, "errors": 0, "warnings": 0}}]
        write_adhoc_result(run_dir / "adhoc", {"config": str(config), "steps": steps, "failures": []})
        line = {"nodeid": "tests/adhoc/test_adhoc.py::test_adhoc_injection[adhoc.inject]", "outcome": "passed"}
        (run_dir / "results.jsonl").write_text(json.dumps({**line, "outcome": captured["outcome"]}) + "\n")
        return int(captured["code"])

    monkeypatch.setattr(cli, "run_pytest", run_pytest)
    captured["settings"] = settings
    return captured


def user_file(tmp_path: Path, name: str = "repo.jsonnet", text: str = REPO) -> Path:
    """A user file outside the project."""
    path = tmp_path / "user" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def invoke(*args: str) -> Any:
    """Run ``otterdog-e2e inject <args>`` with a fixed run id."""
    return CliRunner().invoke(cli.main, ["inject", "--run-id", RUN_ID, *args])


def test_offline_injection(session: dict[str, Any], tmp_path: Path) -> None:
    """The scenario is written in the run's scratch dir, E2E_ADHOC_SCENARIO names it during the session only, pytest
    runs tests/adhoc with the run and every selection option cleared, and the report follows."""
    repo = user_file(tmp_path)
    result = invoke("--fragment", f"repositories={repo}", "--plan", "team", "--var", "label=x", "--print")
    assert result.exit_code == 0, result.output
    settings = session["settings"]
    assert session["scenario_file"] == settings.cache_dir / "run" / RUN_ID / "adhoc" / "scenario.yaml"
    assert ADHOC_ENV not in os.environ
    assert session["args"] == [
        str(settings.project_root / "tests" / "adhoc"),
        "--tb=short",
        f"--e2e-run-id={RUN_ID}",
        "--e2e-target=",
        "--e2e-tags=",
        "--e2e-scenario=",
        "--e2e-base-sut=",
        "--e2e-pr-manifest=",
    ]
    scenario = session["scenario"]
    assert scenario.tier == "offline" and scenario.variables == {"label": "x", "plan": "team"}
    assert scenario.steps[0].fragments.repositories == [REPO]
    assert session["command"] == f"otterdog-e2e inject --fragment repositories={repo} --plan team --var label=x"
    assert "otterdog-e2e inject (offline): artifacts" in result.output
    assert "rendered config: " in result.output and "validate: ok (0 error(s), 0 warning(s))" in result.output
    assert "result: passed" in result.output and "orgs.newOrg('e2e-offline') {}" in result.output  # --print


def test_live_injection_arguments(session: dict[str, Any], tmp_path: Path) -> None:
    """--target makes a live org_level scenario; --apply/--keep shape its steps and cleanup; options reach pytest."""
    repo = user_file(tmp_path)
    result = invoke(
        *("--target", "free", "--sut", "branch:main", "--reset-sut", "tag:v1.6.1", "--artifacts", str(tmp_path / "a")),
        *("--fragment", f"repositories={repo}", "--apply", "--keep", "--no-reset"),
    )
    assert result.exit_code == 0, result.output
    args = session["args"]
    assert "--e2e-target=free" in args and "--e2e-sut=branch:main" in args and "--e2e-reset-sut=tag:v1.6.1" in args
    assert f"--e2e-artifacts={tmp_path / 'a'}" in args and args[-2:] == ["--e2e-keep", "--e2e-no-reset"]
    scenario = session["scenario"]
    assert scenario.tier == "cli" and scenario.org_level and scenario.cleanup == "none"
    step = scenario.steps[0]
    assert step.plan is not None and step.plan.expect == "changes" and step.apply is not None and step.converge
    assert "(live-apply)" in result.output and "not run" in result.output  # results went to the --artifacts root


def test_libraries_overlays_and_config_files(session: dict[str, Any], tmp_path: Path) -> None:
    """Libraries and overlays go into the scenario; --config and --base are offline complete configs."""
    library = user_file(tmp_path, "lib.libsonnet", "{ repo(n):: orgs.newRepo(n) }\n")
    overlay = user_file(tmp_path, "overlay.jsonnet", "{ _repositories+: [] }\n")
    fragment = user_file(tmp_path, "uses.jsonnet", "e2e.repo('{{ p }}-x')\n")
    result = invoke("--library", f"e2e={library}", "--fragment", f"repositories={fragment}", "--overlay", str(overlay))
    assert result.exit_code == 0, result.output
    step = session["scenario"].steps[0]
    assert list(step.fragments.libraries) == ["e2e"] and step.fragments.overlays == ["{ _repositories+: [] }\n"]
    config = user_file(tmp_path, "config.jsonnet", "local orgs = import '{{ import_path }}';\norgs.newOrg('x')\n")
    result = invoke("--config", str(config), "--base", str(config))
    assert result.exit_code == 0, result.output
    step = session["scenario"].steps[0]
    assert step.config is not None and step.base_config is not None and step.base_fragments is None


@pytest.mark.parametrize(
    ("options", "message"),
    [
        ((), "nothing to inject"),
        (("--apply", "--fragment", "repositories={repo}"), "--apply needs a live target"),
        (("--target", "free", "--config", "{repo}"), "--config and --base are offline only"),
        (("--config", "{repo}", "--fragment", "repositories={repo}"), "--config replaces the rendered configuration"),
        (("--fragment", "repos={repo}"), "unknown kind(s) repos"),
        (("--fragment", "repositories"), "expected NAME=VALUE"),
        (("--fragment", "repositories={repo}", "--library", "std={repo}"), "reserved"),
        (("--fragment", "repositories={repo}", "--library", "a={repo}", "--library", "a={repo}"), "given once"),
        (("--fragment", "repositories={repo}", "--offline", "--target", "free"), "exclude each other"),
        (("--fragment", "repositories={repo}", "--var", "plan=team"), "use --plan"),
        (("--fragment", "repositories={repo}", "--plan", "gold"), "is not one of"),
        (("--fragment", "repositories=/nonexistent/x.jsonnet"), "is not an existing file"),
    ],
)
def test_usage_errors(session: dict[str, Any], tmp_path: Path, options: tuple[str, ...], message: str) -> None:
    """Inconsistent options are usage errors (exit 2) and never start a session."""
    repo = str(user_file(tmp_path))
    result = invoke(*(option.replace("{repo}", repo) for option in options))
    assert result.exit_code == 2 and message in result.output, result.output
    assert "args" not in session


def test_bad_run_id(session: dict[str, Any], tmp_path: Path) -> None:
    """--run-id must be a run id."""
    result = CliRunner().invoke(
        cli.main, ["inject", "--run-id", "x", "--fragment", f"repositories={user_file(tmp_path)}"]
    )
    assert result.exit_code == 2 and "is not a run id" in result.output


def test_rule_violations_stop_before_the_session(session: dict[str, Any], tmp_path: Path) -> None:
    """A file breaking a scenario rule: exit 1 with the file and line, no session, scratch removed."""
    bad = user_file(tmp_path, "bad.jsonnet", "orgs.newRepo('{{ p }}-x') {\n  d: importstr '/etc/hostname',\n}\n")
    result = invoke("--fragment", f"repositories={bad}")
    assert result.exit_code == 1 and f"({bad.resolve()}:2): importstr is not allowed" in result.output
    assert "scenario.yaml:" not in result.output and "args" not in session
    assert not (session["settings"].cache_dir / "run" / RUN_ID).exists()


def test_failure_report_and_exit_code(session: dict[str, Any], tmp_path: Path) -> None:
    """The exit code is pytest's; the outcome comes from results.jsonl."""
    session.update(code=1, outcome="failed")
    result = invoke("--fragment", f"repositories={user_file(tmp_path)}")
    assert result.exit_code == 1 and "result: failed" in result.output


def test_command_line_and_adhoc_item(tmp_path: Path) -> None:
    """inject_command_line rebuilds the command (run.json); adhoc_item finds the ad-hoc line of results.jsonl."""
    request = InjectRequest(
        fragments=[("repositories", Path("/u/r.jsonnet"))],
        libraries=[("e2e", Path("/u/l.libsonnet"))],
        overlays=[Path("/u/o.jsonnet")],
        live=True,
        apply=True,
        variables={"plan": "team", "n": 5, "s": "a b"},
    )
    line = cli.inject_command_line(request, target="free", sut=None, reset_sut=None, no_reset=True)
    assert line == (
        "otterdog-e2e inject --target free --fragment repositories=/u/r.jsonnet --library e2e=/u/l.libsonnet "
        "--overlay /u/o.jsonnet --plan team --var n=5 --var 's=a b' --apply --no-reset"
    )
    assert cli.adhoc_item(tmp_path) is None
    (tmp_path / "results.jsonl").write_text('{"nodeid": "tests/offline/x"}\nnot json\n{"nodeid": "tests/adhoc/t"}\n')
    assert cli.adhoc_item(tmp_path) == {"nodeid": "tests/adhoc/t"}


def test_the_generated_yaml_is_the_documented_scenario(session: dict[str, Any], tmp_path: Path) -> None:
    """The scenario file is a regular scenario YAML (it can be copied into scenarios/ once paths are relative)."""
    assert invoke("--fragment", f"variables={user_file(tmp_path)}").exit_code == 0
    document = yaml.safe_load(session["scenario_file"].read_text())
    assert document["id"] == "adhoc.inject" and document["steps"][0]["name"] == "inject"
