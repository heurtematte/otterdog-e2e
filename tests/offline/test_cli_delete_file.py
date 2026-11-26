"""delete-file of a repository it skips, offline (O-DELETE-FILE-SKIP).

``delete-file -r <repo> --path <p>`` deletes a file of a repository the configuration declares and does not archive
(otterdog/operations/delete_file.py). Since eclipse-csi/otterdog#961 (main 97bce29, after v1.8.0) the repositories it
skips are reported as warnings, before the credentials are resolved and before any GitHub call, and the exit status
stays 0 (without organization arguments the command runs over every organization, most of which do not have the
repository): "repository '<repo>' not found in the configuration, skipped" and "repository '<org>/<repo>' is
archived, skipped". Before #961 both cases printed nothing for the organization and exited 0.

The live side of #961 (a missing file 'not found, nothing to delete', a refused deletion 'failed' + 'failure deleting
file' and exit 1) is asserted by the cli tier (tests/cli/test_commands_content.py, KB-043 and KB-044).
"""

from __future__ import annotations

from typing import Protocol

import pytest

from otterdog_acceptance.otterdog.output import normalize_text
from otterdog_acceptance.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_acceptance.otterdog.runner import CliResult, OtterdogCli
from otterdog_acceptance.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_ORG,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

RUN = offline_run_context()
ARCHIVED = RUN.name("delete-archived")
UNCONFIGURED = RUN.name("delete-unconfigured")
PATH = "E2E.md"
# eclipse-csi/otterdog#961 "fix(cli): report failures of delete-file and dispatch-workflow": squash commit on main
# and the head of its pull request (a pr: SUT of that head does not contain the squash commit)
FIX_961 = ("97bce293b18c2a429ecec830358e63d143e98a7f", "ff19b12f520fb163b4687cc336819dd1de28b6c2")
REFERENCES_961 = [
    {
        "pr": 961,
        "note": (
            "'fix(cli): report failures of delete-file and dispatch-workflow': delete-file warns about a repository "
            "it skips ('not found in the configuration, skipped', 'is archived, skipped') instead of printing "
            "nothing. Must not change: the exit status 0 of a skipped repository, no deletion attempted"
        ),
    }
]
DELETING = f"Deleting file '{PATH}' in repository"  # the line of a deletion attempt (before its outcome)


class SutHistory(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when it cannot tell."""


def has_961(history: SutHistory) -> bool:
    """Whether the SUT contains #961 (its squash commit or the head of its pull request); skip when undecidable."""
    found = [history.contains(commit) for commit in FIX_961]
    if True in found:
        return True
    if False in found:
        return False
    pytest.skip(f"cannot tell whether {history.label} contains #961 ({FIX_961[0][:7]})")


def write_config(cli: OtterdogCli) -> str:
    """The configuration of the offline organization with the archived repository ARCHIVED; returns the path of
    otterdog.json as the CLI sees it."""
    workspace = cli.workspace
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
    workspace.write_org_config(
        renderer.render(ConfigFragments(repositories=[f"orgs.newRepo('{ARCHIVED}') {{ archived: true }}"]))
    )
    return str(workspace.config_file.resolve())


def delete_file(cli: OtterdogCli, config: str, repo: str) -> CliResult:
    """``delete-file -c <config> --local -r <repo> --path E2E.md <org>``."""
    return cli.invoke("delete-file", "-c", config, "--local", "-r", repo, "--path", PATH, OFFLINE_ORG)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return f"exit {result.exit_code}\n" + "\n".join(normalize_text(result.output).splitlines()[-lines:])


@pytest.mark.scenario("O-DELETE-FILE-SKIP", references=REFERENCES_961)
@pytest.mark.parametrize(
    ("repo", "warning"),
    [
        pytest.param(
            UNCONFIGURED, f"repository '{UNCONFIGURED}' not found in the configuration, skipped", id="unknown"
        ),
        pytest.param(ARCHIVED, f"repository '{OFFLINE_ORG}/{ARCHIVED}' is archived, skipped", id="archived"),
    ],
)
def test_delete_file_warns_about_a_skipped_repository(
    vendored_cli: OtterdogCli, sut_history: SutHistory, repo: str, warning: str
) -> None:
    """A repository the configuration does not declare, or declares archived, is skipped with exit 0 and no deletion
    attempt; since #961 with a warning naming it (the credentials are never resolved: no GitHub call)."""
    fixed = has_961(sut_history)
    result = delete_file(vendored_cli, write_config(vendored_cli), repo)
    text = normalize_text(result.output)
    assert result.exit_code == 0, tail(result)
    assert DELETING not in text and "invalid credentials" not in text, tail(result)
    if fixed:
        assert f"Warning: {warning}" in text, tail(result)
    else:
        assert "skipped" not in text, tail(result)
