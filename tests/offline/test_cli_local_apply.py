"""local-apply without GitHub: the deletion hints and the approval prompt (O-LOCAL-APPLY-HINTS, O-LOCAL-APPLY-PROMPT).

``local-apply`` plans the configuration against ``<org>.jsonnet-BASE`` and applies the result to GitHub
(otterdog/operations/apply.py:100-163): with nothing but removals and no ``-d`` it prints ``No changes required.`` and
``<n> resource(s) would be deleted with flag '--delete-resources'.`` and stops (exit 0, no prompt); otherwise, without
``-f``, it prints ``No resource will be removed, use flag '--delete-resources' to delete them.`` (pending removals),
asks ``Do you want to perform these actions? (Only 'yes' or 'y' will be accepted to approve)`` and reads one line
(otterdog/utils.py get_approval): anything else than ``yes``/``y`` prints ``Apply cancelled.`` (exit 0), end of input
raises EOFError (``Error: EOF when reading a line``, exit 2). Verified offline on v1.6.1 and main 9bdeb75.

Since eclipse-csi/otterdog#892 (main after v1.7.1) local-apply first reads the code security configurations of the
organization and the configuration attached to each repository from GitHub (local_apply.py:90-92) whenever the template
defines ``newOrgCodeSecurityConfiguration``: offline it then fails before its plan. The tests above use the template
with that function hidden (fixture ``local_apply_cli``), as a template that predates #892 would be;
test_local_apply_reads_code_security_configurations_from_github pins the new behaviour with the full template.

Safety: these tests never approve and never pass ``-f`` with something to apply; the offline sandbox (``unshare -rn``
or ``--network none``) and the dummy token make any apply fail anyway.
"""

from __future__ import annotations

from typing import Protocol

import pytest

from otterdog_acceptance.otterdog.output import normalize_text
from otterdog_acceptance.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_acceptance.otterdog.runner import CliResult, OtterdogCli
from otterdog_acceptance.otterdog.workspace import ConfigWorkspace
from otterdog_acceptance.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

# eclipse-csi/otterdog#892 "feat(org): manage code security configurations" (squash commit on main)
FIX_892 = "d9dac7868f3cd2d1bae1bf1b1675b572547d9136"
CANNOT_CONNECT = "Cannot connect to host api.github.com"


class SutHistory(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when undecidable."""


RUN = offline_run_context()
GONE = RUN.name("gone")
NEW = RUN.name("new")
PROMPT = "Do you want to perform these actions? (Only 'yes' or 'y' will be accepted to approve)"
ENTER = "Enter a value:"
CANCELLED = "Apply cancelled."
NO_CHANGES = "No changes required."
WOULD_DELETE = "1 resource(s) would be deleted with flag '--delete-resources'."
NOT_REMOVED = "No resource will be removed, use flag '--delete-resources' to delete them."
EOF_ERROR = "EOF when reading a line"
EXECUTED = "Executed plan:"


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


def repositories(*names: str) -> ConfigFragments:
    """Fragments with one plain run repository per name."""
    return ConfigFragments(repositories=[f"orgs.newRepo('{name}')" for name in names])


def sides(cli: OtterdogCli, *, base: ConfigFragments, head: ConfigFragments) -> None:
    """Write the -BASE ("live") and the head configuration."""
    cli.workspace.write_base_config(render_org(cli.workspace, base))
    cli.workspace.write_org_config(render_org(cli.workspace, head))


def local_apply(cli: OtterdogCli, *args: str, input: str | None = None) -> CliResult:
    """``local-apply -n [args] --local`` (no web UI; -s -BASE is the default suffix)."""
    return cli.run("local-apply", "-n", *args, local=True, input=input)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


@pytest.mark.scenario("O-LOCAL-APPLY-HINTS")
@pytest.mark.parametrize("force", [True, False], ids=["forced", "interactive"])
def test_removals_without_delete_flag_are_only_hinted(local_apply_cli: OtterdogCli, force: bool) -> None:
    """Only a removal planned and no -d: the removal is shown, then 'No changes required.' and the hint that one
    resource would be deleted with --delete-resources; nothing is applied and no approval is asked (exit 0), with or
    without -f."""
    sides(local_apply_cli, base=repositories(GONE), head=ConfigFragments())
    result = local_apply(local_apply_cli, *(["-f"] if force else []), input="")
    text = normalize_text(result.output)
    applied = result.apply()
    assert result.exit_code == 0, f"exit {result.exit_code}\n{tail(result)}"
    assert f'- remove repository[name="{GONE}"]' in text, tail(result)
    assert NO_CHANGES in text and WOULD_DELETE in text, tail(result)
    assert (applied.no_changes, applied.pending_deletions) == (True, 1), tail(result)
    assert PROMPT not in text and EXECUTED not in text and EOF_ERROR not in text, tail(result)


@pytest.mark.scenario("O-LOCAL-APPLY-PROMPT")
@pytest.mark.parametrize("answer", ["n\n", "no\n", "YES\n"], ids=["n", "no", "upper-case-yes"])
def test_declined_approval_cancels_the_apply(local_apply_cli: OtterdogCli, answer: str) -> None:
    """An addition and a pending removal without -f: the plan, the removal hint and the prompt are printed; any answer
    other than exactly 'yes' or 'y' cancels ('Apply cancelled.', exit 0) and nothing is executed."""
    sides(local_apply_cli, base=repositories(GONE), head=repositories(NEW))
    result = local_apply(local_apply_cli, input=answer)
    text = normalize_text(result.output)
    assert result.exit_code == 0, f"answer {answer!r}: exit {result.exit_code}\n{tail(result)}"
    assert f'+ add repository[name="{NEW}"]' in text and f'- remove repository[name="{GONE}"]' in text, tail(result)
    order = [text.find(NOT_REMOVED), text.find(PROMPT), text.find(ENTER), text.find(CANCELLED)]
    assert all(index >= 0 for index in order) and order == sorted(order), f"order {order}\n{tail(result)}"
    assert EXECUTED not in text and NO_CHANGES not in text, tail(result)


@pytest.mark.scenario("O-LOCAL-APPLY-PROMPT")
def test_end_of_input_at_the_prompt_exits_2(local_apply_cli: OtterdogCli) -> None:
    """Without -f and with an empty stdin the prompt meets end of input: 'Error: EOF when reading a line' and exit
    2, nothing executed (no 'Apply cancelled.' either)."""
    sides(local_apply_cli, base=ConfigFragments(), head=repositories(NEW))
    result = local_apply(local_apply_cli, input="")
    text = normalize_text(result.output)
    assert result.exit_code == 2, f"exit {result.exit_code}\n{tail(result)}"
    assert PROMPT in text and EOF_ERROR in text, tail(result)
    assert text.find(PROMPT) < text.find(EOF_ERROR), tail(result)
    assert CANCELLED not in text and EXECUTED not in text and NOT_REMOVED not in text, tail(result)


@pytest.mark.scenario("O-LOCAL-APPLY-CODE-SECURITY", references=[{"pr": 892}])
def test_local_apply_reads_code_security_configurations_from_github(
    vendored_cli: OtterdogCli, sut_history: SutHistory
) -> None:
    """With the SUT's full template, a SUT containing #892 reads the code security configurations from GitHub before
    printing the plan of local-apply, also when no repository references one: offline the read fails ('Cannot
    connect to host api.github.com', exit 2) before any plan line or prompt. Older SUTs plan without GitHub."""
    if sut_history.contains(FIX_892) is not True:
        pytest.skip(f"{sut_history.label} does not contain #892 ({FIX_892[:7]}): local-apply plans without GitHub")
    sides(vendored_cli, base=ConfigFragments(), head=repositories(NEW))
    result = local_apply(vendored_cli, input="n\n")
    text = normalize_text(result.output)
    assert result.exit_code == 2 and CANNOT_CONNECT in text, f"exit {result.exit_code}\n{tail(result)}"
    assert f'+ add repository[name="{NEW}"]' not in text and PROMPT not in text, tail(result)
