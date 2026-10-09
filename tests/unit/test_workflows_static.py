"""Static checks of the CI workflows (SPEC 17, SEC-14..17), the Makefile and the repository hygiene files.

actionlint is not a dependency of the project: every workflow is parsed with PyYAML and the security rules are
asserted directly (empty top-level permissions, read-only jobs, pinned actions, no persisted credentials, no
expressions inside ``run:``, secrets only on harness steps, scrub before upload, environments and concurrency for
jobs holding secrets). Commands and options used in workflows and in the Makefile are checked against the real
``otterdog-e2e`` click application, and the variables of targets/*.yaml against the workflows and .env.example.

Instances: the ``target`` input of e2e.yml, e2e-webui.yml and e2e-otterdog-pr.yml is one instance or a comma list; the
validation scripts and the instance check of every job running in the environment of an instance are executed here
with bash and jq (skipped when missing) on accepted and refused values.

docs.yml (the documentation site on GitHub Pages) follows the same rules, with the two exceptions a Pages deployment
needs: its deploy job, the only job of the repository writing anything, holds ``pages: write`` and ``id-token: write``
and runs in the ``github-pages`` environment (without secrets); its build job may read the Pages settings. The jobs
holding secrets, and the jobs calling their workflows, also hold ``id-token: write``: their OIDC token logs in to
HashiCorp Vault when the secrets are kept as vault references (vaults.py); no other job gets one.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from functools import cache
from pathlib import Path
from typing import Any

import click
import pytest
import yaml

from otterdog_e2e import cli
from otterdog_e2e.redact import SECRET_KEY_RE

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS_DIR = ROOT / ".github" / "workflows"
WORKFLOW_NAMES = ("ci", "e2e", "e2e-otterdog-pr", "nightly", "janitor", "docs")
# checked by tests/unit/test_webui_workflow.py
OTHER_WORKFLOWS = ("e2e-webui",)
# SPEC 17 pins (other actions must be pinned to a full commit sha as well)
SPEC_PINS = {
    "actions/checkout": ("3d3c42e5aac5ba805825da76410c181273ba90b1", "v7.0.1"),
    "actions/setup-python": ("5fda3b95a4ea91299a34e894583c3862153e4b97", "v7.0.0"),
    "actions/upload-artifact": ("043fb46d1a93c77aae656e7c1c64a875d1fc6a0a", "v7.0.1"),
}
# the GitHub Pages actions of docs.yml
PAGES_PINS = {
    "actions/configure-pages": ("45bfe0192ca1faeb007ade9deae92b16b8254a0d", "v6.0.0"),
    "actions/upload-pages-artifact": ("fc324d3547104276b827a68afc52ff2a11cc49c9", "v5.0.0"),
    "actions/deploy-pages": ("368f82528645a54fb793d4d04e342629a3f51346", "v5.0.1"),
}
PINS = {**SPEC_PINS, **PAGES_PINS}
PINNED_ACTION_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_./-]+@[0-9a-f]{40}$")
LOCAL_WORKFLOW_RE = re.compile(r"^\./\.github/workflows/[a-z0-9-]+\.yml$")
EXPRESSION_RE = re.compile(r"\$\{\{")
FORBIDDEN_IN_RUN_RE = re.compile(r"\$\{\{\s*(inputs\.|github\.event\.)")
SECRET_REF_RE = re.compile(r"secrets\.([A-Za-z0-9_]+)")
GITHUB_TOKEN_RE = re.compile(r"\$\{\{\s*(github\.token|secrets\.GITHUB_TOKEN)\s*\}\}")
VARS_REF_RE = re.compile(r"^\$\{\{\s*vars\.([A-Za-z0-9_]+)\s*\}\}$")
SECRETS_REF_RE = re.compile(r"^\$\{\{\s*secrets\.([A-Za-z0-9_]+)\s*\}\}$")
HARNESS = ".venv/bin/otterdog-e2e"
SUBCOMMAND_RE = re.compile(r"(?:bin/otterdog-e2e\s+|\bargs=\()([a-z][a-z-]*)(?:\s+([a-z][a-z-]*))?")
LONG_OPTION_RE = re.compile(r"(?<![\w$-])--[a-z][a-z0-9-]*")
TARGET_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)")
ENV_NAME_KEY_SUFFIX = "_env"
# target variables that CI never sets: the webapp runs in the compose stack (transport relay) and the App key is a
# secret holding the PEM, not a file
CI_UNMAPPED_TARGET_VARS = frozenset(
    {"E2E_TRANSPORT", "E2E_EXTERNAL_URL", "E2E_EXTERNAL_INIT_URL", "E2E_APP_PRIVATE_KEY_FILE"}
)
E2E_ENVIRONMENT = (
    "${{ needs.classify.outputs.trust == 'trusted' && format('e2e-{0}', matrix.target) "
    "|| format('e2e-{0}-untrusted', matrix.target) }}"
)
# instances (one test org each): `target` is one instance or a comma list, validated without secrets and fanned out as
# a matrix, one job per instance, each in the environments and the concurrency group of its instance
INSTANCES_ALLOWLIST = '${{ vars.E2E_INSTANCES || vars.E2E_TARGETS || \'["free","team","enterprise"]\' }}'
MATRIX_FROM_CLASSIFY = "${{ fromJSON(needs.classify.outputs.targets) }}"
INSTANCE_CONCURRENCY = {"group": "e2e-${{ matrix.target }}", "cancel-in-progress": False, "queue": "max"}
# settings.INSTANCE_NAME_RE and settings.RESERVED_INSTANCE_SUFFIXES, in bash
INSTANCE_VALIDATION = (
    '[[ "$name" =~ ^[a-z0-9][a-z0-9-]{0,38}$ ]]',
    "*-untrusted | *-webui) fail",
    'jq -e --arg name "$name" \'any(.[]; . == $name)\' <<< "$INSTANCES"',
    "(( ${#targets[@]} >= 1 && ${#targets[@]} <= 8 ))",
)
# repository/organization variables classify refuses: per-instance values live in the instance's environments only
REPO_LEVEL_REFUSED = {f"REPO_{name}": f"${{{{ vars.{name} }}}}" for name in ("E2E_ORG", "E2E_ORG_ID", "E2E_PROFILE")}
# mapped by every job of an instance: its profile (read by the harness, never by a target file) and the per-instance
# values of the profiles
INSTANCE_VARS = (
    "E2E_PROFILE",
    "E2E_SAML_SSO",
    "E2E_CAPABILITIES_ADD",
    "E2E_CAPABILITIES_REMOVE",
    "E2E_WEB_PROBE_APP_SLUG",
)
# (workflow, job) of every job running in the environment of an instance
INSTANCE_JOBS = (("e2e", "e2e"), ("e2e-webui", "webui"), ("janitor", "janitor"))
# (workflow, job, step id) of the steps validating the `target` input
TARGET_VALIDATIONS = (
    ("e2e", "classify", "inputs"),
    ("e2e-webui", "classify", "inputs"),
    ("e2e-otterdog-pr", "resolve", "check"),
)
# (workflow, job, step id) of the environment-less steps refusing REPO_LEVEL_REFUSED, before any job of an instance
REPO_LEVEL_CHECKS = (*TARGET_VALIDATIONS[:2], ("janitor", "check", "repository"))
# jobs whose permissions are not exactly {contents: read}: the GitHub Pages build and deployment of the documentation
# the jobs holding secrets (VAULT_JOBS) and the callers of their workflows (VAULT_CALLERS: a caller caps the
# permissions of the called workflow) log in to HashiCorp Vault with their OIDC token (vaults.py)
VAULT_JOBS = (("e2e", "e2e"), ("e2e-webui", "webui"), ("janitor", "janitor"))
VAULT_CALLERS = (("nightly", "release"), ("nightly", "main"), ("nightly", "webui"), ("e2e-otterdog-pr", "e2e"))
JOB_PERMISSIONS = {
    ("docs", "build"): {"contents": "read", "pages": "read"},
    ("docs", "deploy"): {"pages": "write", "id-token": "write"},
    **{job: {"contents": "read", "id-token": "write"} for job in (*VAULT_JOBS, *VAULT_CALLERS)},
}
PAGES_ENVIRONMENT = {"name": "github-pages", "url": "${{ steps.deployment.outputs.page_url }}"}
DEPLOY_CONDITION = "github.event_name != 'pull_request' && github.ref == 'refs/heads/main'"
DOCS_PATHS = ["docs/**", "README.md", "mkdocs.yml", "docs_hooks.py", ".github/workflows/docs.yml"]
MAKE_TARGETS = (
    "help",
    "init",
    "unit",
    "lint",
    "typecheck",
    "offline",
    "cli",
    "webapp",
    "one",
    "doctor",
    "bootstrap",
    "janitor",
    "report",
    "cache-prune",
    "docs",
    "docs-serve",
)
GITIGNORE_PATTERNS = (
    ".env.e2e*",
    "*.pem",
    "artifacts/",
    ".cache/",
    "secrets/",
    ".venv/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    "site/",
    ".claude/settings.local.json",
    ".claude/worktrees/",
)


# --- loading -------------------------------------------------------------------------------------------------------
@cache
def workflow(name: str) -> dict[str, Any]:
    """Parsed .github/workflows/<name>.yml."""
    data = yaml.safe_load((WORKFLOWS_DIR / f"{name}.yml").read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{name}.yml is not a mapping"
    return data


def workflow_text(name: str) -> str:
    """Raw text of a workflow."""
    return (WORKFLOWS_DIR / f"{name}.yml").read_text(encoding="utf-8")


def triggers(data: dict[str, Any]) -> dict[str, Any]:
    """The ``on:`` mapping (PyYAML reads the bare key ``on`` as the boolean True)."""
    value = data.get("on", data.get(True))
    assert isinstance(value, dict), "triggers must be a mapping"
    return value


def jobs(name: str) -> dict[str, dict[str, Any]]:
    """Jobs of a workflow."""
    value = workflow(name)["jobs"]
    assert isinstance(value, dict)
    return value


def steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Steps of a job ([] for jobs calling a reusable workflow)."""
    return list(job.get("steps") or [])


def all_steps() -> Iterator[tuple[str, str, int, dict[str, Any]]]:
    """(workflow, job id, index, step) of every step of every workflow."""
    for name in WORKFLOW_NAMES:
        for job_id, job in jobs(name).items():
            for index, step in enumerate(steps(job)):
                yield name, job_id, index, step


def step_by_id(job: dict[str, Any], step_id: str) -> tuple[int, dict[str, Any]]:
    """(index, step) of the step with ``id: step_id``."""
    for index, step in enumerate(steps(job)):
        if step.get("id") == step_id:
            return index, step
    raise AssertionError(f"no step with id {step_id!r}")


def is_harness_step(step: dict[str, Any]) -> bool:
    """True for steps whose script runs the harness command line."""
    return HARNESS in str(step.get("run") or "")


def secret_names(value: Any) -> set[str]:
    """Names of the secrets referenced anywhere in ``value``."""
    return set(SECRET_REF_RE.findall(yaml.safe_dump(value))) if value else set()


def uses_secrets(job: dict[str, Any]) -> bool:
    """True when a job references a secret other than GITHUB_TOKEN."""
    return bool(secret_names(job) - {"GITHUB_TOKEN"})


def target_variables() -> set[str]:
    """Every environment variable a target file reads: ${VAR} references in values and the values of *_env keys."""
    names: set[str] = set()

    def walk(node: Any, key: str = "") -> None:
        """Collect references from the parsed YAML (comments are not data)."""
        if isinstance(node, dict):
            for child_key, child in node.items():
                walk(child, str(child_key))
        elif isinstance(node, list):
            for child in node:
                walk(child, key)
        elif isinstance(node, str):
            names.update(TARGET_VAR_RE.findall(node))
            if key.endswith(ENV_NAME_KEY_SUFFIX) and node:
                names.add(node)

    for path in sorted((ROOT / "targets").glob("*.yaml")):
        walk(yaml.safe_load(path.read_text(encoding="utf-8")))
    return names


def click_commands() -> dict[str, click.Command]:
    """Every otterdog-e2e command by path (``run``, ``sut classify``, ``cache prune``)."""
    found: dict[str, click.Command] = {}

    def walk(group: click.Group, prefix: str) -> None:
        """Collect the commands of a group recursively."""
        for name, command in group.commands.items():
            path = f"{prefix}{name}"
            found[path] = command
            if isinstance(command, click.Group):
                walk(command, f"{path} ")

    walk(cli.main, "")
    return found


def known_long_options() -> set[str]:
    """Long options of every otterdog-e2e command (and of the main group)."""
    options = {"--help", "--version"}
    for command in [cli.main, *click_commands().values()]:
        for param in command.params:
            options |= {opt for opt in getattr(param, "opts", []) if opt.startswith("--")}
            options |= {opt for opt in getattr(param, "secondary_opts", []) if opt.startswith("--")}
    return options


def harness_lines(script: str) -> list[str]:
    """Script lines (comments excluded) that invoke the harness or build its argument list."""
    lines = [line for line in script.splitlines() if not line.lstrip().startswith("#")]
    return [line for line in lines if "bin/otterdog-e2e" in line or re.search(r"\bargs(\+)?=\(", line)]


def run_step(step: dict[str, Any], env: dict[str, str], cwd: Path) -> tuple[int, dict[str, str], str]:
    """Run the script of a step like the runner (``bash -e -o pipefail``) with the names of its ``env:`` set to ""
    unless ``env`` gives a value; returns the exit code, the GITHUB_OUTPUT values and stdout + stderr."""
    bash = shutil.which("bash")
    if bash is None or shutil.which("jq") is None:
        pytest.skip("bash and jq are needed to run workflow scripts")
    script, output = cwd / "step.sh", cwd / "github-output"
    script.write_text(str(step["run"]), encoding="utf-8")
    output.write_text("", encoding="utf-8")
    environ = {
        "PATH": env.get("PATH") or os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(cwd),
        "LC_ALL": "C",
        **dict.fromkeys(step.get("env") or {}, ""),
        **env,
        "GITHUB_OUTPUT": str(output),
        "GITHUB_STEP_SUMMARY": str(cwd / "step-summary"),
        "GITHUB_ENV": str(cwd / "github-env"),
    }
    result = subprocess.run(
        [bash, "--noprofile", "--norc", "-e", "-o", "pipefail", str(script)],
        cwd=cwd,
        env=environ,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    outputs: dict[str, str] = {}
    for line in output.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator:
            outputs[key] = value
    return result.returncode, outputs, result.stdout + result.stderr


def assert_validates_instances(name: str, job_id: str, step_id: str) -> str:
    """The step validates the `target` input against the instance rules and the allowlist; returns its script."""
    _, step = step_by_id(jobs(name)[job_id], step_id)
    assert step["env"]["TARGET"] == "${{ inputs.target }}", f"{name}.{job_id}"
    assert step["env"]["INSTANCES"] == INSTANCES_ALLOWLIST, f"{name}.{job_id}: the allowlist of the instances"
    for fragment in INSTANCE_VALIDATION:
        assert fragment in step["run"], f"{name}.{job_id}: {fragment}"
    return str(step["run"])


def assert_checks_the_instance(name: str, job_id: str) -> None:
    """The job of an instance loads its variables (E2E_PROFILE and the per-instance values included), then checks
    without secrets, before any harness (SUT) step, that its environment configures the instance: a missing
    environment is created on the fly by GitHub, unprotected and empty."""
    job = jobs(name)[job_id]
    job_steps = steps(job)
    load_index, load = step_by_id(job, "load")
    for variable in INSTANCE_VARS:
        assert load["env"].get(variable) == f"${{{{ vars.{variable} }}}}", f"{name}.{job_id}: {variable}"
    index, check = step_by_id(job, "instance")
    assert load_index < index, f"{name}.{job_id}: the check reads the loaded variables"
    harness = [i for i, step in enumerate(job_steps) if is_harness_step(step)]
    assert harness and index < min(harness), f"{name}.{job_id}: the check precedes every harness step"
    assert check["env"] == {"TARGET": "${{ matrix.target }}"} and not secret_names(check), f"{name}.{job_id}"
    script = str(check["run"])
    assert 'profile="${E2E_PROFILE:-$TARGET}"' in script and '"targets/$profile.yaml"' in script
    assert '"${E2E_ORG:-}"' in script and '"${E2E_ORG_ID:-}" =~ ^[0-9]+$' in script


# --- files -----------------------------------------------------------------------------------------------------------
def test_workflow_files_exist_and_parse() -> None:
    """The workflows of SPEC 17 and docs.yml exist and are YAML mappings with a name, triggers and jobs; every workflow
    file is checked (here or in tests/unit/test_webui_workflow.py)."""
    present = {path.stem for path in WORKFLOWS_DIR.glob("*.yml")}
    assert present == {*WORKFLOW_NAMES, *OTHER_WORKFLOWS}, "check a new workflow in this module"
    assert not list(WORKFLOWS_DIR.glob("*.yaml")), "use the .yml extension"
    for name in WORKFLOW_NAMES:
        data = workflow(name)
        assert data.get("name"), name
        assert triggers(data), name
        assert jobs(name), name


# --- permissions, pins and credentials ------------------------------------------------------------------------------
@pytest.mark.parametrize("name", WORKFLOW_NAMES)
def test_top_level_permissions_are_empty(name: str) -> None:
    """Every workflow starts with ``permissions: {}``."""
    assert workflow(name).get("permissions") == {}


@pytest.mark.parametrize("name", WORKFLOW_NAMES)
def test_every_job_only_reads_contents(name: str) -> None:
    """Each job (reusable workflow calls included) grants exactly ``contents: read``, except the GitHub Pages jobs of
    docs.yml and the Vault logins of the jobs holding secrets (JOB_PERMISSIONS)."""
    for job_id, job in jobs(name).items():
        expected = JOB_PERMISSIONS.get((name, job_id), {"contents": "read"})
        assert job.get("permissions") == expected, f"{name}.{job_id}"


def test_checkouts_do_not_persist_credentials() -> None:
    """actions/checkout always runs with ``persist-credentials: false`` (the SUT must not read GITHUB_TOKEN)."""
    checkouts = [entry for entry in all_steps() if str(entry[3].get("uses", "")).startswith("actions/checkout@")]
    assert checkouts
    for name, job_id, index, step in checkouts:
        assert (step.get("with") or {}).get("persist-credentials") is False, f"{name}.{job_id} step {index}"


def test_actions_are_pinned_to_full_commit_shas() -> None:
    """Every ``uses:`` is a 40-hex pin (SPEC pins for checkout, setup-python, upload-artifact) or a local workflow."""
    for name, job_id, index, step in all_steps():
        uses = step.get("uses")
        if uses is None:
            continue
        assert PINNED_ACTION_RE.match(uses), f"{name}.{job_id} step {index}: {uses!r} is not pinned to a sha"
        action, sha = uses.split("@", 1)
        if action in PINS:
            assert sha == PINS[action][0], f"{name}.{job_id} step {index}: {uses!r} is not the expected pin"
    for name in WORKFLOW_NAMES:
        for job_id, job in jobs(name).items():
            if "uses" in job:
                assert LOCAL_WORKFLOW_RE.match(job["uses"]), f"{name}.{job_id}: only local reusable workflows"


@pytest.mark.parametrize("name", WORKFLOW_NAMES)
def test_pins_carry_their_version_comment(name: str) -> None:
    """Pinned SPEC and Pages actions keep a ``# vX.Y.Z`` comment so updates stay reviewable."""
    for line in workflow_text(name).splitlines():
        match = re.search(r"uses:\s*([^@\s]+)@([0-9a-f]{40})(.*)$", line)
        if match and match.group(1) in PINS:
            assert match.group(3).strip() == f"# {PINS[match.group(1)][1]}", line.strip()


# --- scripts ---------------------------------------------------------------------------------------------------------
def test_no_expressions_inside_run_blocks() -> None:
    """No ``${{ }}`` in ``run:`` (inputs and event data reach scripts through ``env:`` and quoted variables)."""
    for name, job_id, index, step in all_steps():
        script = str(step.get("run") or "")
        where = f"{name}.{job_id} step {index} ({step.get('name')})"
        assert not FORBIDDEN_IN_RUN_RE.search(script), f"{where}: inputs/github.event interpolated into run"
        assert not EXPRESSION_RE.search(script), f"{where}: pass expressions through env instead"


def test_run_blocks_are_valid_bash() -> None:
    """``bash -n`` accepts every script (the runner executes them with bash -e)."""
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("bash is not installed")
    for name, job_id, index, step in all_steps():
        script = step.get("run")
        if not script:
            continue
        result = subprocess.run([bash, "-n"], input=script, capture_output=True, text=True, timeout=30, check=False)
        assert result.returncode == 0, f"{name}.{job_id} step {index}: {result.stderr}"


def test_multi_line_scripts_fail_fast() -> None:
    """Multi-line scripts start with ``set -euo pipefail``."""
    for name, job_id, index, step in all_steps():
        script = str(step.get("run") or "")
        if "\n" in script.strip():
            assert script.lstrip().startswith("set -euo pipefail"), f"{name}.{job_id} step {index}"


def test_harness_commands_and_options_exist() -> None:
    """Every otterdog-e2e command and long option used by a workflow exists in src/otterdog_e2e/cli/."""
    commands, options = click_commands(), known_long_options()
    seen: set[str] = set()
    for name, job_id, index, step in all_steps():
        for line in harness_lines(str(step.get("run") or "")):
            where = f"{name}.{job_id} step {index}: {line.strip()}"
            for first, second in SUBCOMMAND_RE.findall(line):
                path = f"{first} {second}" if f"{first} {second}" in commands else first
                assert path in commands, f"{where}: unknown command {path!r}"
                seen.add(path)
            for option in LONG_OPTION_RE.findall(line):
                assert option in options, f"{where}: unknown option {option}"
    assert {"run", "pr", "janitor", "scrub-artifacts", "sut classify"} <= seen


# --- secrets, environments and concurrency --------------------------------------------------------------------------
def test_secrets_are_mapped_on_harness_steps_only() -> None:
    """Secrets appear only in the ``env:`` of steps running the harness; never in workflow/job env, ``with:``,
    ``secrets: inherit`` or reusable workflow calls."""
    for name in WORKFLOW_NAMES:
        data = workflow(name)
        assert not secret_names(data.get("env")), f"{name}: secrets in the workflow env"
        assert "secrets: inherit" not in workflow_text(name)
        for job_id, job in jobs(name).items():
            assert not secret_names(job.get("env")), f"{name}.{job_id}: secrets in the job env"
            assert "secrets" not in job, f"{name}.{job_id}: secrets passed to a reusable workflow"
            for index, step in enumerate(steps(job)):
                where = f"{name}.{job_id} step {index} ({step.get('name')})"
                assert not secret_names(step.get("with")), f"{where}: secrets in with"
                assert not secret_names(step.get("run")), f"{where}: secrets in run"
                names = secret_names(step.get("env"))
                if names - {"GITHUB_TOKEN"}:
                    assert is_harness_step(step), f"{where}: secrets on a step that does not run the harness"


def test_scrub_steps_get_every_secret_of_their_job() -> None:
    """ISO-02: a scrub step runs in its own process and inherits no secret: it gets every secret the other steps of its
    job map (minus GITHUB_TOKEN), so register_environment_secrets can find leaked values without a token shape (the
    webhook secret, the bot password and TOTP seed) when the session step was killed before its own scrub."""
    checked = 0
    for name in (*WORKFLOW_NAMES, "e2e-webui"):
        for job_id, job in jobs(name).items():
            job_steps = steps(job)
            scrubs = [step for step in job_steps if "scrub-artifacts" in str(step.get("run") or "")]
            if not scrubs:
                continue
            others = set().union(*(secret_names(step.get("env")) for step in job_steps if step not in scrubs))
            for scrub in scrubs:
                assert secret_names(scrub.get("env")) == others - {"GITHUB_TOKEN"}, f"{name}.{job_id}"
                checked += 1
    assert checked >= 4


def test_github_token_only_where_no_environment_secret_is_used() -> None:
    """GITHUB_TOKEN (read-only API reads of the upstream PR) is used only by jobs without environment secrets."""
    for name in WORKFLOW_NAMES:
        for job_id, job in jobs(name).items():
            if GITHUB_TOKEN_RE.search(yaml.safe_dump(job)):
                assert not uses_secrets(job) and "environment" not in job, f"{name}.{job_id}"


def test_jobs_with_secrets_declare_environment_and_concurrency() -> None:
    """Jobs holding secrets run in a protected environment and in the per-target concurrency group (never cancel)."""
    holders = []
    for name in WORKFLOW_NAMES:
        for job_id, job in jobs(name).items():
            if not uses_secrets(job):
                if (name, job_id) == ("docs", "deploy"):
                    assert job["environment"] == PAGES_ENVIRONMENT, "the Pages deployment environment"
                    continue
                assert "environment" not in job, f"{name}.{job_id}: environment without secrets"
                continue
            holders.append(f"{name}.{job_id}")
            assert job.get("environment"), f"{name}.{job_id}: no environment"
            concurrency = job.get("concurrency")
            assert isinstance(concurrency, dict), f"{name}.{job_id}: no concurrency"
            assert str(concurrency.get("group", "")).startswith("e2e-${{"), f"{name}.{job_id}"
            assert concurrency.get("cancel-in-progress") is False, f"{name}.{job_id}"
    assert sorted(holders) == ["e2e.e2e", "janitor.janitor"]


def test_uploads_follow_a_successful_scrub() -> None:
    """upload-artifact runs only after ``otterdog-e2e scrub-artifacts`` succeeded, with a 7-day retention."""
    uploads = [entry for entry in all_steps() if str(entry[3].get("uses", "")).startswith("actions/upload-artifact@")]
    assert uploads
    for name, job_id, index, step in uploads:
        job = jobs(name)[job_id]
        condition = str(step.get("if") or "")
        match = re.search(r"steps\.([A-Za-z0-9_-]+)\.outcome\s*==\s*'success'", condition)
        assert match, f"{name}.{job_id}: the upload does not depend on the scrub outcome"
        scrub_index, scrub = step_by_id(job, match.group(1))
        assert scrub_index < index
        assert "scrub-artifacts" in str(scrub.get("run")), f"{name}.{job_id}: {match.group(1)} is not a scrub step"
        assert "always()" in str(scrub.get("if")), f"{name}.{job_id}: the scrub must run after failures too"
        assert "always()" in condition
        assert (step.get("with") or {}).get("retention-days") == 7, f"{name}.{job_id}"


@pytest.mark.parametrize("name", WORKFLOW_NAMES)
def test_jobs_with_steps_have_timeouts(name: str) -> None:
    """Every job running steps has ``timeout-minutes``."""
    for job_id, job in jobs(name).items():
        if steps(job):
            assert isinstance(job.get("timeout-minutes"), int), f"{name}.{job_id}"


@pytest.mark.parametrize("name", WORKFLOW_NAMES)
def test_no_actions_cache(name: str) -> None:
    """The harness never uses the Actions cache: ``cache-mode: none``, no cache action, no setup-python cache."""
    assert workflow(name).get("cache-mode") == "none"
    for job_id, job in jobs(name).items():
        if "uses" in job:
            assert job.get("cache-mode", "none") == "none", f"{name}.{job_id}"
        for step in steps(job):
            uses = str(step.get("uses", ""))
            assert not uses.startswith("actions/cache"), f"{name}.{job_id}"
            if uses.startswith("actions/setup-python@"):
                assert "cache" not in (step.get("with") or {}), f"{name}.{job_id}"


# --- per-workflow contracts -----------------------------------------------------------------------------------------
def test_ci_workflow_has_no_secrets() -> None:
    """ci.yml (push/PR) never touches secrets nor environments and runs lint, unit and the offline tier."""
    assert "secrets." not in workflow_text("ci")
    assert {"push", "pull_request"} <= set(triggers(workflow("ci")))
    ci_jobs = jobs("ci")
    assert {"lint", "unit", "offline"} <= set(ci_jobs)
    assert all("environment" not in job for job in ci_jobs.values())
    mypy = [step for step in steps(ci_jobs["lint"]) if "mypy" in str(step.get("run"))]
    assert mypy and "continue-on-error" not in mypy[0], "mypy is blocking"
    # a red job must make the workflow red: no step or job of ci.yml may continue on error
    assert "continue-on-error" not in workflow_text("ci"), "every ci.yml job and step is blocking"
    assert ci_jobs["offline"]["strategy"]["matrix"]["sut"] == ["release:latest", "branch:main"]


def test_e2e_workflow_contract() -> None:
    """e2e.yml: dispatch + call inputs, classify without secrets (instances validated against the allowlist), one job
    per instance with the two-environment rule, concurrency, timeouts, the instance check, final janitor --run-id,
    scrub before upload, job summary."""
    on = triggers(workflow("e2e"))
    assert set(on) == {"workflow_dispatch", "workflow_call"}
    expected = {"target", "sut", "base_sut", "suites", "tags", "scenario", "k", "lane", "strict_diff"}
    for trigger in ("workflow_dispatch", "workflow_call"):
        assert set(on[trigger]["inputs"]) == expected, trigger
        target = on[trigger]["inputs"]["target"]
        assert target["type"] == "string" and target["required"] is True, "one instance or a comma list"
        assert "options" not in target, trigger
    assert on["workflow_dispatch"]["inputs"]["target"]["default"] == "free"
    classify, e2e = jobs("e2e")["classify"], jobs("e2e")["e2e"]
    assert not uses_secrets(classify) and "environment" not in classify
    assert any("sut classify" in str(step.get("run")) for step in steps(classify))
    assert set(classify["outputs"]) == {"trust", "sut", "base_sut", "targets"}
    assert classify["outputs"]["targets"] == "${{ steps.inputs.outputs.targets }}"
    assert_validates_instances("e2e", "classify", "inputs")
    _, validate = step_by_id(classify, "inputs")
    assert REPO_LEVEL_REFUSED.items() <= validate["env"].items(), "per-instance variables at repository level"
    assert e2e["needs"] == "classify"
    assert e2e["strategy"] == {"fail-fast": False, "matrix": {"target": MATRIX_FROM_CLASSIFY}}
    assert e2e["environment"] == E2E_ENVIRONMENT
    assert e2e["concurrency"] == INSTANCE_CONCURRENCY
    assert "inputs.target" not in repr(e2e), "the job of an instance only knows matrix.target"
    assert "matrix.target" in e2e["name"]
    for step in steps(e2e):
        if "TARGET" in (step.get("env") or {}):
            assert step["env"]["TARGET"] == "${{ matrix.target }}", step.get("name")
    assert_checks_the_instance("e2e", "e2e")
    assert e2e["timeout-minutes"] == 150
    assert e2e["env"]["E2E_LANE"] == "${{ inputs.lane }}"
    run_index, run = step_by_id(e2e, "run")
    assert run["timeout-minutes"] == 120
    assert "otterdog-e2e" in run["run"]
    janitor_index, janitor = step_by_id(e2e, "janitor")
    assert janitor_index > run_index
    assert "always()" in str(janitor.get("if"))
    assert janitor["timeout-minutes"] == 15
    assert "--run-id" in janitor["run"] and "--apply" in janitor["run"]
    assert set(secret_names(janitor.get("env"))) == {"E2E_ADMIN_TOKEN"}, "the janitor gets the admin token only"
    scrub_index, _ = step_by_id(e2e, "scrub")
    assert scrub_index > janitor_index, "scrub after the janitor (its session writes artifacts too)"
    assert "GITHUB_STEP_SUMMARY" in str(steps(e2e)[-1].get("run")), "job summary"


def test_e2e_secrets_and_variables_cover_the_target_files() -> None:
    """Every variable of targets/*.yaml is mapped in e2e.yml (secret-named ones from secrets, others from vars)."""
    e2e = jobs("e2e")["e2e"]
    mapped: dict[str, str] = {}
    for step in steps(e2e):
        for key, value in (step.get("env") or {}).items():
            text = str(value)
            if (match := SECRETS_REF_RE.match(text)) or (match := VARS_REF_RE.match(text)):
                assert match.group(1) == key, f"{key} maps {text}"
                mapped[key] = "secrets" if text.lstrip("${ ").startswith("secrets.") else "vars"
    for name in sorted(target_variables() - CI_UNMAPPED_TARGET_VARS):
        assert name in mapped, f"{name} (targets/*.yaml) is not mapped in e2e.yml"
        expected = "secrets" if SECRET_KEY_RE.search(name) else "vars"
        assert mapped[name] == expected, f"{name} must come from {expected}"


def test_otterdog_pr_workflow_contract() -> None:
    """e2e-otterdog-pr.yml: dispatch only, pin validated in bash and through the API, then e2e.yml with base auto."""
    on = triggers(workflow("e2e-otterdog-pr"))
    assert set(on) == {"workflow_dispatch"}, "no repository_dispatch, no pull_request_target"
    inputs = on["workflow_dispatch"]["inputs"]
    assert inputs["pr"]["required"] is True and inputs["sha"]["required"] is True
    target = inputs["target"]
    assert target["type"] == "string" and target["required"] is True and target["default"] == "free"
    assert "options" not in target, "one instance or a comma list"
    resolve, e2e = jobs("e2e-otterdog-pr")["resolve"], jobs("e2e-otterdog-pr")["e2e"]
    script = "\n".join(str(step.get("run")) for step in steps(resolve))
    assert '[[ "$PR" =~ ^[0-9]{1,7}$ ]]' in script
    assert '[[ "$SHA" =~ ^[0-9a-f]{40}$ ]]' in script
    assert "eclipse-csi/otterdog" in yaml.safe_dump(resolve) and "compare/" in script
    assert "environment" not in resolve and not uses_secrets(resolve)
    assert_validates_instances("e2e-otterdog-pr", "resolve", "check")
    assert set(resolve["outputs"]) == {"sut", "target", "suites"}
    assert e2e["uses"] == "./.github/workflows/e2e.yml"
    assert e2e["needs"] == "resolve"
    assert "strategy" not in e2e, "a single call: e2e.yml runs one job per instance"
    assert e2e["with"]["target"] == "${{ needs.resolve.outputs.target }}"
    assert e2e["with"]["sut"] == "${{ needs.resolve.outputs.sut }}"
    assert e2e["with"]["base_sut"] == "auto"
    assert e2e["with"]["lane"] == "pr-fast"
    assert 'echo "sut=pr:$PR@$SHA"' in script
    assert 'echo "target=$target"' in script, "the validated comma list"


def test_nightly_runs_release_then_main() -> None:
    """nightly.yml: release:latest, then branch:main (differential against release:latest), through e2e.yml."""
    assert "schedule" in triggers(workflow("nightly"))
    release, main = jobs("nightly")["release"], jobs("nightly")["main"]
    for job in (release, main):
        assert job["uses"] == "./.github/workflows/e2e.yml"
        assert job["with"]["lane"] == "nightly-full"
        assert job["with"]["target"] == "${{ matrix.target }}"
    assert release["with"]["sut"] == "release:latest"
    assert main["with"]["sut"] == "branch:main" and main["with"]["base_sut"] == "release:latest"
    assert main["needs"] == "release"


def test_janitor_workflow_contract() -> None:
    """janitor.yml: an environment-less check job refusing per-instance repository/organization variables, then the
    scheduled matrix over the enabled targets (after it), trusted environment, same concurrency group."""
    assert "schedule" in triggers(workflow("janitor"))
    assert set(jobs("janitor")) == {"check", "janitor"}
    check, job = jobs("janitor")["check"], jobs("janitor")["janitor"]
    assert "environment" not in check and not uses_secrets(check) and "concurrency" not in check
    assert check["permissions"] == {"contents": "read"} and isinstance(check["timeout-minutes"], int)
    assert check["if"] == job["if"], "skipped together (a fresh fork stays quiet)"
    assert not [step for step in steps(check) if "uses" in step], "no action: nothing to pin, nothing checked out"
    _, repository = step_by_id(check, "repository")
    assert repository["env"] == REPO_LEVEL_REFUSED and "repository or organization variable" in repository["run"]
    assert job["needs"] == "check"
    assert "vars.E2E_TARGETS" in str(job["strategy"]["matrix"]["target"])
    assert job["environment"] == "e2e-${{ matrix.target }}"
    assert job["concurrency"] == INSTANCE_CONCURRENCY
    _, step = step_by_id(job, "janitor")
    assert set(secret_names(step.get("env"))) == {"E2E_ADMIN_TOKEN"}
    assert_checks_the_instance("janitor", "janitor")
    _, check = step_by_id(job, "instance")
    assert INSTANCE_VALIDATION[0].replace("$name", "$TARGET") in check["run"], "E2E_TARGETS has no classify job"
    assert "*-untrusted | *-webui) fail" in check["run"]


# --- instances: the `target` input and the instance check -------------------------------------------------------------
ALLOWED = ["free", "team", "enterprise", "acme-1", "free-untrusted", "b-webui", *(f"i{n}" for n in range(1, 10))]
# (target input, instances allowlist (None: the default), the JSON list of instances or the expected error fragment)
TARGET_CASES = [
    ("free", None, ["free"]),
    ("free,team", None, ["free", "team"]),
    (" team , free,team,  enterprise ", None, ["team", "free", "enterprise"]),
    ("acme-1", ALLOWED, ["acme-1"]),
    (",".join(f"i{n}" for n in range(1, 9)), ALLOWED, [f"i{n}" for n in range(1, 9)]),
    ("i1,i1,i1", ALLOWED, ["i1"]),
    ("acme-1", None, "instance acme-1 is not allowed"),
    ("acme-1", '["free"]', "instance acme-1 is not allowed"),
    ("", None, "target must be an instance name or a comma separated list"),
    (",free", None, "target must be an instance name or a comma separated list"),
    ("free,", None, "target must be an instance name or a comma separated list"),
    ("free,,team", None, "target must be an instance name or a comma separated list"),
    ("Free", None, "target must be an instance name or a comma separated list"),
    ("free;id", None, "target must be an instance name or a comma separated list"),
    ("../free", None, "target must be an instance name or a comma separated list"),
    ("-free", ALLOWED, "invalid instance name: -free"),
    ("a" * 40, ALLOWED, "invalid instance name"),
    ("free-untrusted", ALLOWED, "cannot end with -untrusted or -webui"),
    ("free,b-webui", ALLOWED, "cannot end with -untrusted or -webui"),
    ("lists", [*ALLOWED, "lists"], "lists is a reserved name"),
    (",".join(f"i{n}" for n in range(1, 10)), ALLOWED, "target must list 1 to 8 instances"),
    ("free", '{"free": true}', "must be a JSON list of instance names"),
    ("free", '["free", 1]', "must be a JSON list of instance names"),
    ("free", "free", "must be a JSON list of instance names"),
]


def fake_gh(directory: Path, sha: str) -> str:
    """A ``gh`` answering the three API reads of the PR resolve step (PR #792 of eclipse-csi/otterdog at ``sha``);
    returns a PATH starting with it."""
    directory.mkdir()
    gh = directory / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        'case "$*" in\n'
        '  *"--jq .base.repo.full_name"*) echo eclipse-csi/otterdog ;;\n'
        f'  *"--jq .head.sha"*) echo {sha} ;;\n'
        '  *"compare/"*) echo identical ;;\n'
        "  *) exit 3 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    return f"{directory}:{os.environ.get('PATH', '/usr/bin:/bin')}"


@pytest.mark.parametrize(("name", "job_id", "step_id"), TARGET_VALIDATIONS)
@pytest.mark.parametrize(("target", "allowed", "expected"), TARGET_CASES)
def test_target_validation_runs(
    tmp_path: Path, name: str, job_id: str, step_id: str, target: str, allowed: Any, expected: Any
) -> None:
    """The validation scripts accept one instance or a comma list (spaces ignored, duplicates dropped, order kept),
    refuse invalid names, the reserved suffixes, instances missing from the allowlist (E2E_INSTANCES, else
    E2E_TARGETS, else free/team/enterprise), more than 8 instances and an allowlist that is not a JSON list of names;
    e2e.yml and e2e-webui.yml output the JSON list of the matrix, the PR workflow the comma list for e2e.yml."""
    _, step = step_by_id(jobs(name)[job_id], step_id)
    sha = "d0d3b08" + "0" * 33
    env = {
        "TARGET": target,
        "INSTANCES": json.dumps(allowed) if isinstance(allowed, list) else allowed or '["free","team","enterprise"]',
        "SUT": "release:latest",
        "LANE": "nightly-full",
        "PR": "792",
        "SHA": sha,
        "SUITES": "auto",
        "UPSTREAM": "eclipse-csi/otterdog",
    }
    if name == "e2e":
        env["SUITES"] = ""
    if name == "e2e-otterdog-pr":
        env["PATH"] = fake_gh(tmp_path / "bin", sha)
    code, outputs, log = run_step(step, env, tmp_path)
    if isinstance(expected, str):
        assert code != 0 and "::error::" in log and expected in log, log
        assert "targets" not in outputs and "target" not in outputs
        return
    assert code == 0, log
    if name == "e2e-otterdog-pr":
        assert outputs["target"] == ",".join(expected)
        assert outputs["sut"] == f"pr:792@{sha}"
    else:
        assert json.loads(outputs["targets"]) == expected


@pytest.mark.parametrize(("name", "job_id", "step_id"), REPO_LEVEL_CHECKS)
@pytest.mark.parametrize("variable", sorted(REPO_LEVEL_REFUSED))
def test_classify_refuses_repository_level_instance_variables(
    tmp_path: Path, name: str, job_id: str, step_id: str, variable: str
) -> None:
    """E2E_ORG, E2E_ORG_ID and E2E_PROFILE are refused as repository or organization variables (visible to classify,
    and to the janitor's check job, which have no environment): a job of a missing, auto-created environment would
    inherit them and pass the instance check."""
    _, step = step_by_id(jobs(name)[job_id], step_id)
    assert REPO_LEVEL_REFUSED.items() <= step["env"].items()
    env = {"TARGET": "free", "INSTANCES": '["free"]', "SUT": "release:latest", "LANE": "nightly-full", variable: "x"}
    code, outputs, log = run_step(step, env, tmp_path)
    assert code != 0 and "repository or organization variable" in log and not outputs, log


def test_the_janitor_check_passes_without_repository_level_instance_variables(tmp_path: Path) -> None:
    """Unset (or empty) repository variables: the janitor's check job passes and the matrix jobs may start."""
    _, step = step_by_id(jobs("janitor")["check"], "repository")
    code, _, log = run_step(step, {}, tmp_path)
    assert code == 0 and "no per-instance variable at repository or organization level" in log, log


# (instance, environment variables loaded by the job, expected error fragment or None)
INSTANCE_CASES = [
    ("free", {"E2E_ORG": "acme", "E2E_ORG_ID": "42"}, None),
    ("free", {"E2E_PROFILE": "free", "E2E_ORG": "acme", "E2E_ORG_ID": "42"}, None),
    ("acme-1", {"E2E_PROFILE": "team", "E2E_ORG": "acme", "E2E_ORG_ID": "42"}, None),
    ("acme-1", {"E2E_ORG": "acme", "E2E_ORG_ID": "42"}, "no profile targets/acme-1.yaml"),
    ("acme-1", {"E2E_PROFILE": "missing", "E2E_ORG": "acme", "E2E_ORG_ID": "42"}, "no profile targets/missing.yaml"),
    ("acme-1", {"E2E_PROFILE": "../free", "E2E_ORG": "acme", "E2E_ORG_ID": "42"}, "E2E_PROFILE must be the name"),
    ("free", {"E2E_PROFILE": "team", "E2E_ORG": "acme", "E2E_ORG_ID": "42"}, "instance free is a profile name"),
    ("free", {}, "E2E_ORG is not set"),
    ("acme-1", {"E2E_PROFILE": "team", "E2E_ORG_ID": "42"}, "E2E_ORG is not set"),
    ("free", {"E2E_ORG": "acme"}, "E2E_ORG_ID is not a numeric id"),
    ("free", {"E2E_ORG": "acme", "E2E_ORG_ID": "42; id"}, "E2E_ORG_ID is not a numeric id"),
    ("Free", {"E2E_ORG": "acme", "E2E_ORG_ID": "42"}, "invalid instance name"),
]


@pytest.mark.parametrize(("name", "job_id"), INSTANCE_JOBS)
@pytest.mark.parametrize(("instance", "variables", "expected"), INSTANCE_CASES)
def test_instance_check_runs(
    tmp_path: Path, name: str, job_id: str, instance: str, variables: dict[str, str], expected: str | None
) -> None:
    """The instance check fails, before any SUT code, when the environment of the job does not configure the instance
    (no E2E_ORG/E2E_ORG_ID: a missing environment GitHub created on the fly) or names no existing profile, and
    refuses a profile name bound to another profile."""
    _, step = step_by_id(jobs(name)[job_id], "instance")
    (tmp_path / "targets").mkdir()
    for profile in ("free", "team", "enterprise"):
        (tmp_path / "targets" / f"{profile}.yaml").write_text("{}\n", encoding="utf-8")
    code, _, log = run_step(step, {"TARGET": instance, **variables}, tmp_path)
    if expected is None:
        assert code == 0, log
        assert f"instance {instance}: profile {variables.get('E2E_PROFILE') or instance}" in log
    else:
        assert code != 0 and "::error::" in log and expected in log, log


def test_janitor_instance_check_refuses_reserved_suffixes(tmp_path: Path) -> None:
    """The janitor has no classify job: its instance check refuses the reserved suffixes and the reserved name lists
    of E2E_TARGETS entries."""
    _, step = step_by_id(jobs("janitor")["janitor"], "instance")
    (tmp_path / "targets").mkdir()
    (tmp_path / "targets" / "free.yaml").write_text("{}\n", encoding="utf-8")
    for instance in ("acme-untrusted", "acme-webui"):
        env = {"TARGET": instance, "E2E_PROFILE": "free", "E2E_ORG": "acme", "E2E_ORG_ID": "42"}
        code, _, log = run_step(step, env, tmp_path)
        assert code != 0 and "cannot end with -untrusted or -webui" in log, log
    env = {"TARGET": "lists", "E2E_PROFILE": "free", "E2E_ORG": "acme", "E2E_ORG_ID": "42"}
    code, _, log = run_step(step, env, tmp_path)
    assert code != 0 and "lists is a reserved name" in log, log


def test_docs_workflow_contract() -> None:
    """docs.yml: build (strict, pinned hash-checked packages) on pull requests and main, deploy from main only."""
    on = triggers(workflow("docs"))
    assert set(on) == {"push", "pull_request", "workflow_dispatch"}, "no pull_request_target"
    assert on["push"]["branches"] == ["main"]
    assert on["push"]["paths"] == on["pull_request"]["paths"] == DOCS_PATHS
    assert "secrets." not in workflow_text("docs")
    assert set(jobs("docs")) == {"build", "deploy"}
    build, deploy = jobs("docs")["build"], jobs("docs")["deploy"]
    assert "environment" not in build and "if" not in build, "pull requests build the site too"
    concurrency = workflow("docs")["concurrency"]
    assert "'refs/heads/main' && 'pages'" in concurrency["group"], "runs of main share the group pages"
    assert concurrency["cancel-in-progress"] is False, "never cancel a deployment"

    kinds = [str(step["uses"]).split("@")[0] if "uses" in step else "run" for step in steps(build)]
    assert kinds == [
        "actions/checkout",
        "actions/setup-python",
        "run",
        "run",
        "actions/configure-pages",
        "actions/upload-pages-artifact",
    ]
    assert steps(build)[1]["with"] == {"python-version": "3.12"}, "no setup-python cache"
    install, run = steps(build)[2]["run"], steps(build)[3]["run"]
    assert "--require-hashes" in install and "--only-binary=:all:" in install and "-r docs/requirements.txt" in install
    assert run == "mkdocs build --strict"
    configure, upload = steps(build)[4], steps(build)[5]
    assert configure["uses"].startswith("actions/configure-pages@")
    assert upload["uses"].startswith("actions/upload-pages-artifact@") and upload["with"] == {"path": "site/"}
    assert configure["if"] == upload["if"] == DEPLOY_CONDITION, "pull requests never upload a site"

    assert deploy["needs"] == "build"
    assert deploy["if"] == DEPLOY_CONDITION, "deploy from main only, never from a pull request"
    assert deploy["environment"] == PAGES_ENVIRONMENT
    assert [step["uses"].split("@")[0] for step in steps(deploy)] == ["actions/deploy-pages"]
    assert steps(deploy)[0]["id"] == "deployment"


def test_only_the_pages_deployment_and_the_vault_logins_write() -> None:
    """``pages: write`` and ``id-token: write`` are granted to the deploy job of docs.yml, ``id-token: write`` alone to
    VAULT_JOBS and VAULT_CALLERS, nothing anywhere else."""
    for name in (*WORKFLOW_NAMES, *OTHER_WORKFLOWS):
        data = workflow(name)
        for scope, permissions in [
            ("workflow", data.get("permissions")),
            *[(job_id, job.get("permissions")) for job_id, job in jobs(name).items()],
        ]:
            if isinstance(permissions, str):  # read-all or write-all
                writes = {permissions} if permissions == "write-all" else set()
            else:
                writes = {key for key, value in (permissions or {}).items() if value == "write"}
            if (name, scope) == ("docs", "deploy"):
                expected = {"pages", "id-token"}
            else:
                expected = {"id-token"} if (name, scope) in (*VAULT_JOBS, *VAULT_CALLERS) else set()
            assert writes == expected, f"{name}.{scope}: {permissions}"


def test_the_vault_logins_are_the_jobs_holding_secrets() -> None:
    """VAULT_JOBS are exactly the jobs reading ``secrets.*`` (a secret kept as a vault reference must resolve there),
    VAULT_CALLERS exactly the jobs calling e2e.yml or e2e-webui.yml."""
    holding, calling = set(), set()
    for name in (*WORKFLOW_NAMES, *OTHER_WORKFLOWS):
        for job_id, job in jobs(name).items():
            if "secrets." in json.dumps(job.get("steps") or []) + json.dumps(job.get("env") or {}):
                holding.add((name, job_id))
            if str(job.get("uses", "")).endswith(("/e2e.yml", "/e2e-webui.yml")):
                calling.add((name, job_id))
    assert holding == set(VAULT_JOBS) and calling == set(VAULT_CALLERS), (sorted(holding), sorted(calling))


# --- Makefile and hygiene files ---------------------------------------------------------------------------------------
@cache
def makefile() -> str:
    """Text of the Makefile."""
    return (ROOT / "Makefile").read_text(encoding="utf-8")


def test_makefile_targets() -> None:
    """The Makefile provides the documented targets, uses the project venv and never exports OTTERDOG_CONFIG_ROOT."""
    defined = set(re.findall(r"^([a-z][a-z0-9-]*):", makefile(), flags=re.MULTILINE))
    assert set(MAKE_TARGETS) <= defined, sorted(set(MAKE_TARGETS) - defined)
    assert ".venv/bin/otterdog-e2e" in makefile()
    assert re.search(r"^unexport OTTERDOG_CONFIG_ROOT$", makefile(), flags=re.MULTILINE)
    assert re.search(r"^\.PHONY:", makefile(), flags=re.MULTILINE)


def test_makefile_harness_commands_and_options_exist() -> None:
    """Commands and long options of the ``$(E2E)`` recipe lines exist in the otterdog-e2e command line."""
    commands, options = click_commands(), known_long_options()
    lines = [line for line in makefile().splitlines() if line.startswith("\t") and "$(E2E)" in line]
    assert lines
    for line in lines:
        words = line.split("$(E2E)", 1)[1].split()
        assert words and words[0] in commands, f"{line.strip()}: unknown command"
        if isinstance(commands[words[0]], click.Group):
            assert len(words) > 1 and f"{words[0]} {words[1]}" in commands, f"{line.strip()}: unknown subcommand"
        for option in LONG_OPTION_RE.findall(line):
            assert option in options, f"{line.strip()}: unknown option {option}"


def test_gitignore_keeps_secrets_and_outputs_out_of_git() -> None:
    """.gitignore covers env files, keys, artifacts, caches and the venv; poetry.toml and .env.example stay tracked."""
    lines = [line.strip() for line in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()]
    for pattern in GITIGNORE_PATTERNS:
        assert pattern in lines, pattern
    assert "poetry.toml" not in lines
    assert "!.env.example" in lines or not any(line in (".env*", ".env.*") for line in lines)


def test_gitignore_hides_no_scenario_file() -> None:
    """The secrets/ rule never hides a scenario file: the secrets domain (scenarios/<tier>/secrets/, dummy values only)
    is excepted, so every file below scenarios/ can be committed."""
    git = shutil.which("git")
    if git is None or not (ROOT / ".git").exists():
        pytest.skip("not a git checkout")
    paths = [path.relative_to(ROOT).as_posix() for path in sorted((ROOT / "scenarios").rglob("*")) if path.is_file()]
    found = subprocess.run(
        [git, "check-ignore", "--no-index", "--stdin"],
        cwd=ROOT,
        input="\n".join(paths),
        capture_output=True,
        text=True,
        check=False,
    )
    assert found.returncode in (0, 1), found.stderr
    assert found.stdout.split() == [], f"ignored scenario files: {found.stdout.split()}"
    assert "secrets/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines(), "secrets/ stays ignored"


def test_env_example_lists_every_target_variable_without_values() -> None:
    """.env.example documents every variable of targets/*.yaml and assigns no value."""
    text = (ROOT / ".env.example").read_text(encoding="utf-8")
    assignments = re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=(.*)$", text, flags=re.MULTILINE)
    names = {name for name, _ in assignments}
    missing = sorted(target_variables() - names)
    assert not missing, f".env.example misses {missing}"
    with_values = sorted(name for name, value in assignments if value.strip())
    assert not with_values, f".env.example must not hold values: {with_values}"
    assert "read:org" in text, "document the read:org scope of classic PATs"
