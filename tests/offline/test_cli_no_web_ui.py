"""The web UI default of otterdog.json and the -n/--no-web-ui option pair, offline (O-CONFIG-NO-WEB-UI).

Since eclipse-csi/otterdog#913 (main 946d17b after v1.7.1, 1.8.0) ``defaults.github.no_web_ui`` of otterdog.json is
the default of the option ``-n/--no-web-ui`` of show-live, import, plan, check-status, apply and local-apply, and
``--web-ui`` disables it for one call: an explicit flag wins over the configured default in both directions
(otterdog/cli.py ``_no_web_ui_option`` and ``_resolve_no_web_ui``, otterdog/config.py ``default_no_web_ui``). Before,
``-n`` was a plain flag (default off), ``--web-ui`` a usage error ("No such option", exit 2) and the setting ignored.

Offline, local-apply shows which value an operation got: with no_web_ui it unsets the organization settings read
through the web UI in its ``-BASE`` side (otterdog/operations/local_apply.py:91-92), so a change of such a setting
(``members_can_create_teams``) is not planned, while the addition of a repository is planned either way. Every case
answers 'n' at the approval prompt: nothing is applied (the offline sandbox and the dummy token would make an apply
fail anyway). The other five commands resolve the option with the same ``_resolve_no_web_ui`` but need GitHub; their
help is checked here.
"""

from __future__ import annotations

from typing import Protocol

import pytest

from otterdog_acceptance.otterdog.output import normalize_text
from otterdog_acceptance.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_acceptance.otterdog.runner import CliResult, OtterdogCli
from otterdog_acceptance.otterdog.workspace import ConfigWorkspace, WorkspaceLayout
from otterdog_acceptance.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli", "org-settings")]

# eclipse-csi/otterdog#913 "feat: allow to disable the web ui by default via otterdog.json": squash commit on main and
# head of the pull request (a pr: SUT of that head does not contain the squash commit)
FIX_913 = ("946d17b21624b58f9d21f060ec7e36979e1c8f14", "9fce57502e95b5f8fdb4c516a67b9a6f8e81c73a")
REFERENCES = [
    {
        "pr": 913,
        "note": (
            "'feat: allow to disable the web ui by default via otterdog.json': defaults.github.no_web_ui is the "
            "default of -n/--no-web-ui, --web-ui overrides it; before, the setting was ignored and --web-ui unknown"
        ),
    }
]
COMMANDS = ("show-live", "import", "plan", "check-status", "apply", "local-apply")
WEB_SETTING = "members_can_create_teams"  # read through the web UI (schemas/settings.json provider "web")
RUN = offline_run_context()
NEW = RUN.name("web-ui")
PROMPT = "Do you want to perform these actions? (Only 'yes' or 'y' will be accepted to approve)"
CANCELLED = "Apply cancelled."
NO_SUCH_OPTION = "No such option '--web-ui'"  # click's usage error


class SutHistory(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when undecidable."""


def has_913(history: SutHistory) -> bool:
    """Whether the SUT contains #913 (its squash commit or the head of its pull request); skip when undecidable."""
    found = [history.contains(commit) for commit in FIX_913]
    if True in found:
        return True
    if False in found:
        return False
    pytest.skip(f"cannot tell whether {history.label} contains #913 ({FIX_913[0][:7]})")


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


@pytest.mark.scenario("O-CONFIG-NO-WEB-UI", references=REFERENCES)
@pytest.mark.parametrize(
    ("configured", "args", "web_ui"),
    [
        pytest.param(None, (), True, id="default"),
        pytest.param(None, ("-n",), False, id="default-n"),
        pytest.param(None, ("--no-web-ui",), False, id="default-no-web-ui"),
        pytest.param(False, (), True, id="false"),
        pytest.param(False, ("--no-web-ui",), False, id="false-no-web-ui"),
        pytest.param(True, (), False, id="true"),
        pytest.param(True, ("-n",), False, id="true-n"),
        pytest.param(True, ("--web-ui",), True, id="true-web-ui"),
    ],
)
def test_no_web_ui_defaults_to_the_configuration(
    local_apply_cli: OtterdogCli,
    sut_history: SutHistory,
    configured: bool | None,
    args: tuple[str, ...],
    web_ui: bool,
) -> None:
    """local-apply plans the change of a web UI setting unless no_web_ui is in effect: an explicit -n/--no-web-ui or
    --web-ui decides, otherwise defaults.github.no_web_ui of otterdog.json (since #913); the repository addition is
    planned in every case and the prompt answered 'n' cancels the apply. SUTs without #913 ignore the setting (the web
    UI setting is planned whenever -n is absent) and refuse --web-ui as an unknown option."""
    fixed = has_913(sut_history)
    workspace = local_apply_cli.workspace
    override = None if configured is None else {"github": {"no_web_ui": configured}}
    workspace.use_layout(WorkspaceLayout(defaults_override=override))
    workspace.write_base_config(render_org(workspace, ConfigFragments(settings=[f"{WEB_SETTING}: false"])))
    head = ConfigFragments(settings=[f"{WEB_SETTING}: true"], repositories=[f"orgs.newRepo('{NEW}')"])
    workspace.write_org_config(render_org(workspace, head))

    result = local_apply_cli.run("local-apply", *args, local=True, input="n\n")
    text = normalize_text(result.output)
    if not fixed and "--web-ui" in args:
        assert result.exit_code == 2 and NO_SUCH_OPTION in text, f"exit {result.exit_code}\n{tail(result)}"
        return
    expected_web_ui = web_ui if fixed else not ({"-n", "--no-web-ui"} & set(args))
    assert result.exit_code == 0, f"exit {result.exit_code}\n{tail(result)}"
    assert f'+ add repository[name="{NEW}"]' in text and PROMPT in text and CANCELLED in text, tail(result)
    planned = WEB_SETTING in text
    assert planned is expected_web_ui, (
        f"{sut_history.label}: no_web_ui={configured!r} and {list(args)} must "
        f"{'plan' if expected_web_ui else 'skip'} the change of the web UI setting {WEB_SETTING}\n{tail(result)}"
    )


@pytest.mark.scenario("O-CONFIG-NO-WEB-UI", references=REFERENCES)
@pytest.mark.parametrize("command", COMMANDS)
def test_every_command_offers_both_flags(offline_cli: OtterdogCli, sut_history: SutHistory, command: str) -> None:
    """The six commands that read the web UI take -n/--no-web-ui and, since #913, --web-ui, documented as defaulting
    to the 'no_web_ui' setting of the otterdog configuration; before, -n/--no-web-ui only."""
    fixed = has_913(sut_history)
    result = offline_cli.invoke(command, "--help")
    text = normalize_text(result.output)
    assert result.exit_code == 0 and "-n, --no-web-ui" in text, f"exit {result.exit_code}\n{tail(result)}"
    if fixed:
        assert "--no-web-ui / --web-ui" in text and "'no_web_ui' setting of the otterdog" in text, tail(result)
    else:
        assert "--web-ui" not in text.replace("--no-web-ui", ""), tail(result)
