"""cli.validate.code-scanning-languages (validation.repo.code-scanning, P2): code scanning languages are validated
against the languages GitHub detected in the repository.

A repository enabling the code scanning default setup with languages makes validation call GitHub: the repository
must exist (#767, regression.code-scanning-new-repo) and every configured language must be among the languages
GitHub detected (GET /repos/{org}/{repo}/languages; 'actions' always counts, GitHub names map to code scanning names,
otterdog/models/repository.py:325-378). The test creates a public run repository with the SUT, commits a Python file
with the admin Mutator and waits until otterdog itself reports Python (GitHub detects languages asynchronously), then
validates: 'go' is refused naming the detected languages, 'python' and 'actions' validate, an unknown language is
refused by the enum rule (its value list prints a Python set: KB-038, only the stable prefix is asserted) and by the
detection, and the query suite enum is checked. Validation only after the repository exists: nothing else is
applied; the run repository is removed afterwards (guarded apply -d with the trusted reset CLI).
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import ConfigFragments

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli

DESCRIPTION = "otterdog e2e: code scanning languages"
DETECTION_TIMEOUT = 360.0  # GitHub's language detection runs after the push, usually within a minute
DETECTION_INTERVAL = 20.0  # one validate (org listing, member list, languages) per attempt
STATE_TIMEOUT = 90.0
TAIL = 3000


def repository(name: str, **fields: object) -> str:
    """``orgs.newRepo('<name>') { description, <fields> }`` with json-encoded values."""
    body = ", ".join(f"{key}: {json.dumps(value)}" for key, value in {"description": DESCRIPTION, **fields}.items())
    return f"orgs.newRepo({json.dumps(name)}) {{ {body} }}"


def validate(cli: OtterdogCli, renderer: OrgConfigRenderer, snippet: str) -> tuple[CliResult, str]:
    """``validate`` of the baseline plus one repository: the result and its normalized output."""
    cli.workspace.write_org_config(renderer.render(ConfigFragments(repositories=[snippet])))
    result = cli.validate()
    assert not result.timed_out and result.infra_error is None, result.output[-TAIL:]
    return result, normalize_text(result.output)


@pytest.mark.scenario("cli.validate.code-scanning-languages")
@pytest.mark.tags("cli", "repo")
@pytest.mark.timeout(1200)
def test_code_scanning_languages_must_be_detected(
    e2e: E2EContext,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    mutator: Mutator,
    run_ctx: RunContext,
    otterdog: OtterdogCli,
) -> None:
    """'go' on a Python repository is a validation error naming 'Python'; 'python' and 'actions' validate; 'cobol' is
    refused twice (enum and detection; the exit code is the number of errors, KB-034, so only non-zero is asserted);
    the query suite must be default | extended."""
    name = run_ctx.name("cs")
    header = f'repository[name="{name}"]'
    otterdog.workspace.write_org_config(renderer.render(ConfigFragments(repositories=[repository(name)])))
    try:
        applied = otterdog.apply(repo_filter=run_ctx.repo_filter())
        applied.assert_ok("apply (repository created)")
        assert not applied.apply().failed_patches, applied.output[-TAIL:]
        waiting.wait_until(
            lambda: oracle.branch_sha(name, "main"), timeout=STATE_TIMEOUT, interval=3.0, what=f"{name}:main"
        )
        mutator.commit_files(name, "main", {"main.py": "print('otterdog e2e')\n"}, "otterdog e2e: a Python file")

        go = repository(name, code_scanning_default_setup_enabled=True, code_scanning_default_languages=["go"])
        refused = (
            f"Error: {header} has 'code_scanning_default_languages' configured with 'go' but this language is not "
            "detected in the repository. Detected languages: Python"
        )
        result, text = waiting.poll(
            lambda: validate(otterdog, renderer, go),
            until=lambda outcome: refused in outcome[1],
            timeout=DETECTION_TIMEOUT,
            interval=DETECTION_INTERVAL,
            raise_on_timeout=False,
            what="otterdog reports the detected language Python",
        )
        assert refused in text, f"'go' is not refused with the detected languages:\n{text[-TAIL:]}"
        parsed = result.validation()
        assert not parsed.ok and parsed.errors == 1 and result.exit_code == 1, text[-TAIL:]

        for languages in (["python"], ["python", "actions"]):
            snippet = repository(
                name, code_scanning_default_setup_enabled=True, code_scanning_default_languages=languages
            )
            result, text = validate(otterdog, renderer, snippet)
            parsed = result.validation()
            assert parsed.ok and parsed.errors == 0 and result.exit_code == 0, f"{languages} refused:\n{text[-TAIL:]}"
            assert "code_scanning_default_languages" not in text, text[-TAIL:]

        cobol = repository(name, code_scanning_default_setup_enabled=True, code_scanning_default_languages=["cobol"])
        result, text = validate(otterdog, renderer, cobol)
        undetected = (
            f"Error: {header} has 'code_scanning_default_languages' configured with 'cobol' but this language is not "
            "detected in the repository. Detected languages: Python"
        )
        for message in (
            f"Error: {header} has defined an invalid code scanning language 'cobol', only values (",
            undetected,
        ):
            assert message in text, f"missing {message!r}:\n{text[-TAIL:]}"
        parsed = result.validation()
        assert not parsed.ok and parsed.errors == 2 and result.exit_code != 0, text[-TAIL:]

        suite = repository(name, code_scanning_default_query_suite="full")
        result, text = validate(otterdog, renderer, suite)
        message = (
            f"Error: {header} has 'code_scanning_default_query_suite' set to value 'full', while only values "
            "['default' | 'extended'] are allowed."
        )
        assert message in text, f"the query suite is not refused:\n{text[-TAIL:]}"
        assert result.validation().errors == 1 and result.exit_code == 1, text[-TAIL:]
    finally:
        if not e2e.options.keep:
            e2e.remove_run_objects(baseline, baseline.reset_cli)
