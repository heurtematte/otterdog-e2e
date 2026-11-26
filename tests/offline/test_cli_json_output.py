"""JSON written to stdout, offline (O-JSON-STDOUT): ``list-apps --json`` and ``check-status --json -``.

Both commands print a JSON document after the organizations ran (``post_execute``). Since eclipse-csi/otterdog#963
(main 02e0e72, after v1.8.0) a command that writes structured output to stdout sends every other message to stderr
(``StdCommand(structured_stdout=...)``, ``otterdog.logging.messages_to_stderr``): the operation's output, warnings,
errors and log records. ``list-apps --json`` prints the JSON with ``click.echo`` (no rich markup, no wrapping) and
``check-status --json -`` writes it to stdout (``click.open_file``), even when no organization could be checked
(``[]``). Before #963 the messages went to stdout with the JSON, and ``check-status --json -`` wrote nothing for an
empty status list (and created a file named ``-`` otherwise).

The tests refuse the credentials of the organization (the ``plain`` provider without ``api_token``): the
organization prints ``invalid credentials`` and exits 1 before any GitHub call, and the JSON is then the empty list.
``-v`` adds the Info messages and the API usage log record (#881), which must not reach stdout either; check-status
runs with ``-n`` (token only, like list-apps), so the same key is reported missing.
"""

from __future__ import annotations

import json
from typing import Any, Protocol

import pytest

from otterdog_acceptance.otterdog.output import normalize_text
from otterdog_acceptance.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_acceptance.otterdog.runner import CliResult, OtterdogCli
from otterdog_acceptance.otterdog.workspace import ConfigWorkspace, WorkspaceLayout
from otterdog_acceptance.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_ORG,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
)

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

# eclipse-csi/otterdog#963 "fix(cli): keep errors and logs out of JSON written to stdout": squash commit on main and
# the head of its pull request (a pr: SUT of that head does not contain the squash commit)
FIX_963 = ("02e0e72fac934e162e1d9b777c70f6b0c8d710b1", "2d437e9823eff0fe05272afa955e7fbe6e8d09e4")
REFERENCES_963 = [
    {
        "pr": 963,
        "note": (
            "'fix(cli): keep errors and logs out of JSON written to stdout': list-apps --json and check-status "
            "--json - print only the JSON on stdout, the messages, errors and log records go to stderr; check-status "
            "--json - writes '[]' when no organization could be checked. Must not change: the exit status and the "
            "messages themselves (now on stderr)"
        ),
    }
]
INVALID = "Error: invalid credentials"
MISSING_TOKEN = "required key 'api_token' not found in credential data"


class SutHistory(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when it cannot tell."""


def has_963(history: SutHistory) -> bool:
    """Whether the SUT contains #963 (its squash commit or the head of its pull request); skip when undecidable."""
    found = [history.contains(commit) for commit in FIX_963]
    if True in found:
        return True
    if False in found:
        return False
    pytest.skip(f"cannot tell whether {history.label} contains #963 ({FIX_963[0][:7]})")


def refuse_credentials(cli: OtterdogCli) -> str:
    """otterdog.json whose organization uses the plain provider without api_token (refused before any GitHub call),
    plus the configuration of the organization; returns the path of otterdog.json as the CLI sees it."""
    workspace: ConfigWorkspace = cli.workspace
    workspace.layout = WorkspaceLayout()  # the harness document, not a previous variant
    document = workspace.otterdog_json()
    document["organizations"][0]["credentials"] = {"provider": "plain"}
    workspace.use_layout(WorkspaceLayout(document=document))
    renderer = OfflineConfigRenderer(
        template=workspace.template,
        org=workspace.org,
        plan=OFFLINE_DEFAULT_PLAN,
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
        project=workspace.project,
    )
    workspace.write_org_config(renderer.render(ConfigFragments()))
    return str(workspace.config_file.resolve())


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of stdout and stderr (assertion messages)."""
    return f"exit {result.exit_code}\n--- stdout\n{result.stdout[-2000:]}\n--- stderr\n" + "\n".join(
        normalize_text(result.stderr).splitlines()[-lines:]
    )


def stdout_json(result: CliResult) -> Any:
    """The JSON document of stdout (AssertionError when stdout holds anything else)."""
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssertionError(f"stdout is not one JSON document ({exc}):\n{tail(result)}") from exc


def assert_refused_on_stderr(result: CliResult) -> None:
    """Exit 1 (the organization failed), the credential error on stderr only."""
    assert result.exit_code == 1, tail(result)
    assert f"{INVALID}\n{MISSING_TOKEN}" in normalize_text(result.stderr), tail(result)
    assert "invalid credentials" not in result.stdout, tail(result)


@pytest.mark.scenario("O-JSON-STDOUT", references=REFERENCES_963)
@pytest.mark.parametrize("verbose", [pytest.param((), id="quiet"), pytest.param(("-v",), id="info")])
def test_list_apps_json_keeps_stdout_for_the_json(
    vendored_cli: OtterdogCli, sut_history: SutHistory, verbose: tuple[str, ...]
) -> None:
    """``list-apps --json`` of an organization whose credentials are refused: since #963 stdout is exactly the JSON
    array (empty) and the error, the Info messages and the log records of ``-v`` are on stderr; before, the error
    went to stdout ahead of the JSON. The exit status is 1 either way."""
    fixed = has_963(sut_history)
    config = refuse_credentials(vendored_cli)
    result = vendored_cli.invoke("list-apps", "-c", config, "--local", "--json", *verbose, OFFLINE_ORG)
    if not fixed:
        assert result.exit_code == 1 and "invalid credentials" in result.stdout, tail(result)
        return
    assert_refused_on_stderr(result)
    assert stdout_json(result) == [], tail(result)
    assert result.stdout == "[]\n", tail(result)
    if verbose:
        assert "Listing app installations:" in normalize_text(result.stderr), tail(result)


@pytest.mark.scenario("O-JSON-STDOUT", references=REFERENCES_963)
def test_check_status_json_dash_writes_the_json_to_stdout(vendored_cli: OtterdogCli, sut_history: SutHistory) -> None:
    """``check-status --json -`` of an organization whose credentials are refused: since #963 ``-`` is stdout, which
    holds only the status list (empty: no organization was checked), the messages go to stderr; before, the messages
    went to stdout and nothing was written for an empty status list. The exit status is 1 either way."""
    fixed = has_963(sut_history)
    config = refuse_credentials(vendored_cli)
    result = vendored_cli.invoke("check-status", "-c", config, "--local", "-n", "--json", "-", OFFLINE_ORG)
    if not fixed:
        assert result.exit_code == 1 and "invalid credentials" in result.stdout, tail(result)
        assert result.stdout.strip() and not result.stdout.lstrip().startswith("["), tail(result)
        return
    assert_refused_on_stderr(result)
    assert stdout_json(result) == [], tail(result)
    assert OFFLINE_ORG in normalize_text(result.stderr), f"the organization header is not on stderr\n{tail(result)}"
