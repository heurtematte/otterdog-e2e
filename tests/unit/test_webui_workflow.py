"""Static checks of the web-UI CI lane (.github/workflows/e2e-webui.yml and the nightly ``webui`` job): the rules of
tests/unit/test_workflows_static.py, plus its own: trusted SUTs only, the e2e-<target>-webui environment, the web
secrets on the harness step only, the shared concurrency group, scrub before upload."""

from __future__ import annotations

import re
import shutil
import subprocess
from functools import cache
from pathlib import Path
from typing import Any

import click
import pytest
import yaml

from otterdog_e2e import cli

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
PINNED_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
SECRET_REF_RE = re.compile(r"secrets\.([A-Za-z0-9_]+)")
WEB_SECRETS = {"E2E_ADMIN_PASSWORD", "E2E_ADMIN_TOTP_SEED"}
HARNESS = ".venv/bin/otterdog-e2e"


@cache
def workflow(name: str) -> dict[str, Any]:
    """Parsed workflow."""
    data = yaml.safe_load((WORKFLOWS / f"{name}.yml").read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def jobs(name: str) -> dict[str, dict[str, Any]]:
    """Jobs of a workflow."""
    return dict(workflow(name)["jobs"])


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Steps of a job."""
    return list(job.get("steps") or [])


def secret_names(value: Any) -> set[str]:
    """Secrets referenced in ``value``."""
    return set(SECRET_REF_RE.findall(yaml.safe_dump(value))) if value else set()


def test_top_level_rules() -> None:
    """permissions {}, cache-mode none, dispatch + call with target/sut only, contents: read per job."""
    data = workflow("e2e-webui")
    assert data["permissions"] == {} and data["cache-mode"] == "none"
    on = data.get("on", data.get(True))
    assert set(on) == {"workflow_dispatch", "workflow_call"}
    for trigger in on.values():
        assert set(trigger["inputs"]) == {"target", "sut"}
    for job in jobs("e2e-webui").values():
        assert job["permissions"] == {"contents": "read"} and isinstance(job["timeout-minutes"], int)


def test_actions_pinned_and_checkouts_without_credentials() -> None:
    """Every action pinned to a sha; checkouts never persist the GITHUB_TOKEN."""
    for job in jobs("e2e-webui").values():
        for step in steps(job):
            uses = step.get("uses")
            if uses is None:
                continue
            assert PINNED_ACTION_RE.match(uses), uses
            if uses.startswith("actions/checkout@"):
                assert step["with"]["persist-credentials"] is False


def test_no_expressions_in_scripts_and_scripts_fail_fast() -> None:
    """No ``${{ }}`` in run blocks; multi-line scripts start with set -euo pipefail and are valid bash."""
    bash = shutil.which("bash")
    for job in jobs("e2e-webui").values():
        for step in steps(job):
            script = str(step.get("run") or "")
            assert "${{" not in script, step.get("name")
            if "\n" in script.strip():
                assert script.lstrip().startswith("set -euo pipefail"), step.get("name")
            if script and bash:
                result = subprocess.run([bash, "-n"], input=script, capture_output=True, text=True, check=False)
                assert result.returncode == 0, (step.get("name"), result.stderr)


def test_classify_refuses_untrusted_suts_without_secrets() -> None:
    """The classify job holds no secret and fails for pr:/path:/dirty: specs and any untrusted classification."""
    classify = jobs("e2e-webui")["classify"]
    assert not secret_names(classify) and "environment" not in classify
    script = "\n".join(str(step.get("run") or "") for step in steps(classify))
    assert "pr:* | path:* | dirty:*" in script and "sut classify" in script
    assert '[[ "$trust" != trusted ]]' in script


def test_web_job_environment_concurrency_and_secrets() -> None:
    """e2e-<target>-webui environment, the org's concurrency group, the web secrets on the harness step only."""
    job = jobs("e2e-webui")["webui"]
    assert job["needs"] == "classify"
    assert job["environment"] == "${{ format('e2e-{0}-webui', inputs.target) }}"
    assert job["concurrency"] == {"group": "e2e-${{ inputs.target }}", "cancel-in-progress": False, "queue": "max"}
    assert job["env"]["E2E_ALLOW_WEB_UI"] == "true" and not secret_names(job.get("env"))
    holders = {step.get("id") or step.get("name"): secret_names(step.get("env")) for step in steps(job)}
    assert holders["run"] == {"E2E_ADMIN_TOKEN", "E2E_ORACLE_TOKEN", *WEB_SECRETS}
    assert holders["janitor"] == {"E2E_ADMIN_TOKEN"}
    for step in steps(job):
        names = secret_names(step.get("env"))
        assert not secret_names(step.get("with")) and not secret_names(step.get("run"))
        if names:
            assert HARNESS in str(step.get("run")), step.get("name")
    deps = next(step for step in steps(job) if "install-deps" in str(step.get("run")))
    assert steps(job).index(deps) < next(i for i, s in enumerate(steps(job)) if "poetry install" in str(s.get("run")))
    assert not secret_names(deps)


def test_scrub_before_upload_and_the_session_command() -> None:
    """upload-artifact only after a successful scrub (7 days); the session runs tests/web_ui through the harness."""
    job = jobs("e2e-webui")["webui"]
    names = [step.get("id") for step in steps(job)]
    upload = next(step for step in steps(job) if str(step.get("uses", "")).startswith("actions/upload-artifact@"))
    assert "steps.scrub.outcome == 'success'" in upload["if"] and upload["with"]["retention-days"] == 7
    assert names.index("scrub") > names.index("janitor") > names.index("run")
    run = next(step for step in steps(job) if step.get("id") == "run")
    assert "tests/web_ui" in run["run"] and "--scenario 'webui.*'" in run["run"]


def test_harness_commands_and_options_exist() -> None:
    """Every otterdog-e2e command and long option of the lane exists in the click application."""
    commands: dict[str, click.Command] = {}

    def walk(group: click.Group, prefix: str) -> None:
        """Collect the commands."""
        for name, command in group.commands.items():
            commands[f"{prefix}{name}"] = command
            if isinstance(command, click.Group):
                walk(command, f"{prefix}{name} ")

    walk(cli.main, "")
    options = {opt for command in commands.values() for param in command.params for opt in getattr(param, "opts", [])}
    for job in jobs("e2e-webui").values():
        for step in steps(job):
            for line in str(step.get("run") or "").splitlines():
                match = re.search(r"bin/otterdog-e2e\s+([a-z-]+)(?:\s+([a-z-]+))?", line)
                if not match:
                    continue
                path = f"{match[1]} {match[2]}" if f"{match[1]} {match[2]}" in commands else match[1]
                assert path in commands, line
                for option in re.findall(r"(?<![\w$-])--[a-z][a-z0-9-]*", line):
                    assert option in options, (line, option)


def test_nightly_web_job_is_optional_and_last() -> None:
    """nightly webui: only with E2E_WEB_UI_ENABLED, after release and main, release:latest, no secrets in the caller."""
    job = jobs("nightly")["webui"]
    assert job["uses"] == "./.github/workflows/e2e-webui.yml"
    assert job["needs"] == ["release", "main"]
    assert "vars.E2E_WEB_UI_ENABLED == 'true'" in job["if"] and "!cancelled()" in job["if"]
    assert job["with"] == {"target": "${{ matrix.target }}", "sut": "release:latest"}
    assert "E2E_WEB_UI_TARGETS" in job["strategy"]["matrix"]["target"]
    assert job["permissions"] == {"contents": "read"} and not secret_names(job) and "environment" not in job


@pytest.mark.parametrize("name", ["e2e", "e2e-otterdog-pr", "janitor", "ci", "docs"])
def test_other_workflows_never_get_web_credentials(name: str) -> None:
    """The web secrets exist only in the web-UI lane (never the trusted or untrusted e2e environments)."""
    assert not secret_names(workflow(name)) & WEB_SECRETS
