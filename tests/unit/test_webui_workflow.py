"""Static checks of the web-UI CI lane (.github/workflows/e2e-webui.yml and the nightly ``webui`` job): the rules of
tests/unit/test_workflows_static.py, plus its own: trusted SUTs only, one job per instance and one at a time, the
e2e-<instance>-webui environment, the instance check, the web secrets on the harness step only, the shared concurrency
group, scrub before upload. The validation of the ``target`` list and the instance check are also run with bash in
tests/unit/test_workflows_static.py (TARGET_VALIDATIONS, INSTANCE_JOBS)."""

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
INSTANCES_ALLOWLIST = '${{ vars.E2E_INSTANCES || vars.E2E_TARGETS || \'["free","team","enterprise"]\' }}'
INSTANCE_VARS = (
    "E2E_PROFILE",
    "E2E_SAML_SSO",
    "E2E_CAPABILITIES_ADD",
    "E2E_CAPABILITIES_REMOVE",
    "E2E_WEB_PROBE_APP_SLUG",
)


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


def step_by_id(job: dict[str, Any], step_id: str) -> tuple[int, dict[str, Any]]:
    """(index, step) of the step with ``id: step_id``."""
    for index, step in enumerate(steps(job)):
        if step.get("id") == step_id:
            return index, step
    raise AssertionError(f"no step with id {step_id!r}")


def test_top_level_rules() -> None:
    """permissions {}, cache-mode none, dispatch + call with target/sut only (target: one instance or a comma list),
    contents: read per job."""
    data = workflow("e2e-webui")
    assert data["permissions"] == {} and data["cache-mode"] == "none"
    on = data.get("on", data.get(True))
    assert set(on) == {"workflow_dispatch", "workflow_call"}
    for trigger in on.values():
        assert set(trigger["inputs"]) == {"target", "sut"}
        target = trigger["inputs"]["target"]
        assert target["type"] == "string" and target["required"] is True and "options" not in target
    assert on["workflow_dispatch"]["inputs"]["target"]["default"] == "free"
    for job_id, job in jobs("e2e-webui").items():
        # the web job holds secrets: its OIDC token logs in to HashiCorp Vault (vault references, vaults.py)
        expected = {"contents": "read", "id-token": "write"} if job_id == "webui" else {"contents": "read"}
        assert job["permissions"] == expected and isinstance(job["timeout-minutes"], int)


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


def test_classify_validates_the_instances() -> None:
    """The target list is validated without secrets (instance name, reserved suffixes, the allowlist, 1 to 8) and
    output as the JSON list of the matrix; per-instance variables are refused at repository level."""
    classify = jobs("e2e-webui")["classify"]
    assert set(classify["outputs"]) == {"sut", "targets"}
    assert classify["outputs"]["targets"] == "${{ steps.inputs.outputs.targets }}"
    _, validate = step_by_id(classify, "inputs")
    assert validate["env"]["TARGET"] == "${{ inputs.target }}"
    assert validate["env"]["INSTANCES"] == INSTANCES_ALLOWLIST
    for name in ("E2E_ORG", "E2E_ORG_ID", "E2E_PROFILE"):
        assert validate["env"][f"REPO_{name}"] == f"${{{{ vars.{name} }}}}", name
    script = validate["run"]
    assert '[[ "$name" =~ ^[a-z0-9][a-z0-9-]{0,38}$ ]]' in script and "*-untrusted | *-webui) fail" in script
    assert "'any(.[]; . == $name)' <<< \"$INSTANCES\"" in script
    assert "(( ${#targets[@]} >= 1 && ${#targets[@]} <= 8 ))" in script
    assert 'echo "targets=$json" >> "$GITHUB_OUTPUT"' in script


def test_web_job_environment_concurrency_and_secrets() -> None:
    """One job per instance, one at a time, each in its e2e-<instance>-webui environment and the org's concurrency
    group, the web secrets on the harness step only."""
    job = jobs("e2e-webui")["webui"]
    assert job["needs"] == "classify"
    assert job["strategy"] == {
        "fail-fast": False,
        "max-parallel": 1,
        "matrix": {"target": "${{ fromJSON(needs.classify.outputs.targets) }}"},
    }
    assert job["environment"] == "${{ format('e2e-{0}-webui', matrix.target) }}"
    assert job["concurrency"] == {"group": "e2e-${{ matrix.target }}", "cancel-in-progress": False, "queue": "max"}
    assert "inputs.target" not in repr(job), "the job of an instance only knows matrix.target"
    for step in steps(job):
        if "TARGET" in (step.get("env") or {}):
            assert step["env"]["TARGET"] == "${{ matrix.target }}", step.get("name")
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


def test_instance_check_precedes_the_session() -> None:
    """The load step maps E2E_PROFILE and the per-instance variables; the instance check (no secrets) follows it and
    precedes every harness step: a missing e2e-<instance>-webui environment is created on the fly, unprotected and
    empty, and must fail before any SUT code runs."""
    job = jobs("e2e-webui")["webui"]
    load_index, load = step_by_id(job, "load")
    for name in INSTANCE_VARS:
        assert load["env"][name] == f"${{{{ vars.{name} }}}}", name
    index, check = step_by_id(job, "instance")
    harness = [i for i, step in enumerate(steps(job)) if HARNESS in str(step.get("run") or "")]
    assert load_index < index < min(harness)
    assert index < step_by_id(job, "run")[0]
    assert check["env"] == {"TARGET": "${{ matrix.target }}"} and not secret_names(check)
    assert 'profile="${E2E_PROFILE:-$TARGET}"' in check["run"] and '"targets/$profile.yaml"' in check["run"]
    assert '"${E2E_ORG:-}"' in check["run"] and '"${E2E_ORG_ID:-}" =~ ^[0-9]+$' in check["run"]


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
    # one instance at a time (like the lists of e2e-webui.yml): the web logins of the bot accounts never overlap
    assert job["strategy"]["max-parallel"] == 1 and job["strategy"]["fail-fast"] is False
    # a caller caps the permissions of e2e-webui.yml: id-token for the Vault login of its web job
    assert job["permissions"] == {"contents": "read", "id-token": "write"}
    assert not secret_names(job) and "environment" not in job


@pytest.mark.parametrize("name", ["e2e", "e2e-otterdog-pr", "janitor", "ci", "docs"])
def test_other_workflows_never_get_web_credentials(name: str) -> None:
    """The web secrets exist only in the web-UI lane (never the trusted or untrusted e2e environments)."""
    assert not secret_names(workflow(name)) & WEB_SECRETS
