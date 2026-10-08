"""Rich markup in validation messages (O-KB-VALIDATION-MARKUP, KB-050), next to the #440 regression guard.

otterdog prints through rich, which interprets ``[bold]``, ``[/]`` and ``[link=...]`` as markup. #440 (v1.1.0)
escapes the string values of plan and show output (otterdog/operations/__init__.py:233, the object headers in
otterdog/models/__init__.py:566-588), which scenarios/offline/cli/lplan-escaping.yaml guards. The
messages of validate are printed as rich table cells without escaping (otterdog/logging.py:174-198 _print_message), so
a validation message quoting such a value loses its markup: '[bold]NOPE[/bold]' is quoted as 'NOPE' (KB-050,
like the repository links of ``show --markdown``, tests/offline/test_cli_basics.py). Verified on v1.6.1 and main
9bdeb75.
"""

from __future__ import annotations

import pytest

from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

RUN = offline_run_context()
REPO = RUN.name("markup")
MARKUP_VALUE = "[bold]NOPE[/bold]"


def render_org(workspace: ConfigWorkspace, fragments: ConfigFragments) -> str:
    """The configuration of the offline organization with ``fragments``, rendered as OfflineEngine renders it."""
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
    return renderer.render(fragments)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


@pytest.mark.scenario("O-KB-VALIDATION-MARKUP")
@pytest.mark.known_bug("KB-050")
def test_validation_messages_quote_values_literally(vendored_cli: OtterdogCli) -> None:
    """An invalid squash_merge_commit_title holding markup is reported with its literal value in both messages."""
    workspace = vendored_cli.workspace
    fragments = ConfigFragments(
        repositories=[f"orgs.newRepo('{REPO}') {{ squash_merge_commit_title: '{MARKUP_VALUE}' }}"]
    )
    workspace.write_org_config(render_org(workspace, fragments))
    result = vendored_cli.validate(local=True)
    messages = result.validation().errors_text()
    assert len(messages) == 2 and all("squash_merge_commit_title" in text for text in messages), tail(result)
    assert all(f"'{MARKUP_VALUE}'" in text for text in messages), f"the value lost its markup:\n{messages}"
