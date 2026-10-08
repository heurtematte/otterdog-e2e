"""``otterdog-e2e sut`` (SPEC 16): resolve, install, build and classify systems under test.

``sut install`` installs the CLI of a trusted SUT on the host, ``sut image`` builds the webapp image; ``sut classify``
is the CI classify job (no secrets): trust and normalized specs, written to GITHUB_OUTPUT, and for an untrusted SUT a
review block in GITHUB_STEP_SUMMARY (the PR title as a code span, the changed build and template files flagged).
"""

from __future__ import annotations

import dataclasses
import os
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from otterdog_e2e.cli.common import _echo_json, _handled, _session, _settings, main
from otterdog_e2e.context import AUTO_BASE
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.sut.spec import SutSpec

# files of a PR that run code at build time or change templates: flagged in the classify step summary
RISKY_PATHS = ("pyproject.toml", "poetry.lock", "docker/*", "*Dockerfile*", "examples/template/*")


# --- sut ------------------------------------------------------------------------------------------------------------
@main.group()
def sut() -> None:
    """Resolve, install, build and classify systems under test."""


@sut.command("resolve")
@click.argument("spec")
@_handled
def sut_resolve(spec: str) -> None:
    """Resolve SPEC and print the ResolvedSut as JSON."""
    with _session(sut=spec, artifacts=False) as context:
        _echo_json(context.resolve(spec).to_json())


@sut.command("install")
@click.argument("spec")
@_handled
def sut_install(spec: str) -> None:
    """Install the CLI of a trusted SPEC on the host."""
    with _session(sut=spec, artifacts=False) as context:
        resolved = context.resolve(spec)
        if not resolved.trusted:
            raise click.ClickException(f"{resolved.label} is untrusted: it never runs on the host (use `sut image`)")
        installed = context.installed("head")
        _echo_json(
            {
                "label": resolved.label,
                "version": resolved.version,
                "runtime": installed.runtime,
                "otterdog": str(installed.otterdog_bin),
                "version_output": installed.version_output.strip(),
            }
        )


@sut.command("image")
@click.argument("spec")
@_handled
def sut_image(spec: str) -> None:
    """Build the webapp image of SPEC."""
    with _session(sut=spec, artifacts=False) as context:
        _echo_json(dataclasses.asdict(context.image_for("head")))


def normalize_spec(spec: SutSpec) -> str:
    """Canonical spec string (``v1.6.1`` -> ``tag:v1.6.1``, ``pr:792@<sha>``)."""
    return f"{spec.kind}:{spec.value}" + (f"@{spec.pin_sha}" if spec.pin_sha else "")


def pr_details(number: int, pin: str | None, upstream: str, http: GitHubHttp) -> dict[str, Any]:
    """Title, author, head repo/sha and risky changed files of an upstream PR (anonymous public reads)."""
    from fnmatch import fnmatch

    pull = http.get(f"/repos/{upstream}/pulls/{number}") or {}
    files = [str(item.get("filename")) for item in http.paginate(f"/repos/{upstream}/pulls/{number}/files")]
    head = pull.get("head") or {}
    return {
        "number": number,
        "title": pull.get("title"),
        "author": (pull.get("user") or {}).get("login"),
        "head_repo": (head.get("repo") or {}).get("full_name"),
        "head_sha": head.get("sha"),
        "pin_is_head": head.get("sha") == pin,
        "changed_files": len(files),
        "risky_files": sorted(f for f in files if any(fnmatch(f, pattern) for pattern in RISKY_PATHS)),
    }


def _code_span(text: Any) -> str:
    """Markdown code span of untrusted text (backticks and newlines neutralized)."""
    return "`" + str(text or "").replace("`", "'").replace("\n", " ") + "`"


def _write_github_files(info: Mapping[str, Any], environ: Mapping[str, str]) -> None:
    """GITHUB_OUTPUT trust/sut/base_sut lines; for untrusted SUTs a review block in GITHUB_STEP_SUMMARY."""
    output = environ.get("GITHUB_OUTPUT")
    if output:
        with Path(output).open("a", encoding="utf-8") as handle:
            handle.writelines(f"{key}={info.get(key) or ''}\n" for key in ("trust", "sut", "base_sut"))
    summary = environ.get("GITHUB_STEP_SUMMARY")
    if summary and info.get("trust") == "untrusted":
        with Path(summary).open("a", encoding="utf-8") as handle:
            handle.write(REDACTOR(_untrusted_summary(info)))


def _untrusted_summary(info: Mapping[str, Any]) -> str:
    """Markdown review block of an untrusted SUT (PR title as a code span, risky files flagged)."""
    lines = ["### Untrusted SUT: review before approving the environment", "", f"- spec: {_code_span(info.get('sut'))}"]
    pull = info.get("pr") or {}
    if pull:
        lines += [
            f"- PR #{pull.get('number')}: {_code_span(pull.get('title'))}",
            f"- author: {_code_span(pull.get('author'))}, head repo: {_code_span(pull.get('head_repo'))}",
            f"- head sha: {_code_span(pull.get('head_sha'))} (pin is head: {pull.get('pin_is_head')})",
            f"- changed files: {pull.get('changed_files')}",
        ]
        risky = pull.get("risky_files") or []
        lines.append("- build/template files changed: " + (", ".join(_code_span(f) for f in risky) or "none"))
    return "\n".join(lines) + "\n"


@sut.command("classify")
@click.argument("spec")
@click.option("--base-sut", default=None, help="base SUT spec to normalize as well")
@_handled
def sut_classify(spec: str, base_sut: str | None) -> None:
    """Print trust (trusted|untrusted) and normalized specs (CI classify job, no secrets)."""
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.sut.spec import parse_sut_spec

    parsed = parse_sut_spec(spec)
    base = AUTO_BASE if base_sut in (None, "", AUTO_BASE) else normalize_spec(parse_sut_spec(str(base_sut)))
    trusted = parsed.trusted
    if parsed.kind == "sha":
        with _session(sut=spec, artifacts=False) as context:
            trusted = context.resolve(spec).trusted
    info: dict[str, Any] = {
        "trust": "trusted" if trusted else "untrusted",
        "sut": normalize_spec(parsed),
        "base_sut": base,
        "kind": parsed.kind,
    }
    if parsed.kind == "pr":
        http = GitHubHttp(None, read_only=True, identity="anonymous")
        info["pr"] = pr_details(int(parsed.value), parsed.pin_sha, _settings().upstream_repo, http)
    _write_github_files(info, os.environ)
    _echo_json(info)
