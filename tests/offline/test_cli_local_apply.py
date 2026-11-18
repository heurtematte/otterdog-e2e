"""local-apply without GitHub: the deletion hints, the approval prompt, validation errors and the delete filter
(O-LOCAL-APPLY-HINTS, O-LOCAL-APPLY-PROMPT, O-LOCAL-APPLY-VALIDATION-ERRORS, O-LOCAL-APPLY-DELETE-FILTER).

``local-apply`` plans the configuration against ``<org>.jsonnet-BASE`` and applies the result to GitHub
(otterdog/operations/apply.py:100-163): with nothing but removals and no ``-d`` it prints ``No changes required.`` and
``<n> resource(s) would be deleted with flag '--delete-resources'.`` and stops (exit 0, no prompt); otherwise, without
``-f``, it prints ``No resource will be removed, use flag '--delete-resources' to delete them.`` (pending removals),
asks ``Do you want to perform these actions? (Only 'yes' or 'y' will be accepted to approve)`` and reads one line
(otterdog/utils.py get_approval): anything else than ``yes``/``y`` prints ``Apply cancelled.`` (exit 0), end of input
raises EOFError (``Error: EOF when reading a line``, exit 2). Verified offline on v1.6.1 and main 9bdeb75.

A validation error aborts the planning ('Planning aborted due to validation errors.'); before eclipse-csi/otterdog#923
(1.8.0) ApplyOperation.handle_finish then saw an empty diff, printed ``No changes required.`` and exited 0 (KB-001);
since, it returns the validation error count.

Since eclipse-csi/otterdog#892 (main after v1.7.1) local-apply first reads the code security configurations of the
organization and the configuration attached to each repository from GitHub (local_apply.py:90-92) whenever the template
defines ``newOrgCodeSecurityConfiguration``: offline it then fails before its plan. The tests above use the template
with that function hidden (fixture ``local_apply_cli``), as a template that predates #892 would be;
test_local_apply_reads_code_security_configurations_from_github pins the new behaviour with the full template.

Since eclipse-csi/otterdog#939 (main 61faaff after v1.8.0) apply and local-apply take ``--delete-filter SELECTOR``
(repeatable, only with ``-d``: "option '--delete-filter' requires '--delete-resources'", exit 2): a selector is a
type (shell pattern) optionally followed by ``[key=value, ...]`` conditions on the key of the resource or the key of
its parent named by its type (``repo_variable[repository=<repo>]``), values being shell patterns, quoted or not
(otterdog/models/__init__.py ResourceSelector; a malformed one is a usage error "invalid resource selector", exit 2).
The apply then becomes a targeted deletion: only the selected removals are planned, shown and applied, every other
patch (additions, changes, other removals) is only counted: ``N other change(s) are skipped, only the deletions
selected by '--delete-filter' are applied.`` before the prompt (operations/apply.py handle_finish,
diff_operation.include_live_patch). A selector that matches no removal prints the warning ``no resource to delete
matches the delete filter '<selector>'.``; with nothing selected at all it ends with ``No changes required.`` and the
skipped line (exit 0, no prompt). Nested resources of a renamed repository are deleted by its current name: only the
deletions are applied, so the rename is skipped and their removals name the old repository (``children_parent``,
models/repository.py). Older SUTs refuse the option as unknown (exit 2).

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
# eclipse-csi/otterdog#939 "feat(cli): apply only selected deletions with --delete-filter": squash commit on main and
# head of the pull request (a pr: SUT of that head does not contain the squash commit)
FEATURE_939 = ("61faaff93b43af9eccac89381141575f74e27742", "83c4700c86ce574c9a904b0c98ac9b91fda8765c")
DELETE_FILTER_REFERENCES = [
    {
        "pr": 939,
        "note": (
            "'feat(cli): apply only selected deletions with --delete-filter': apply and local-apply take repeatable "
            "--delete-filter selectors (type[key=value, ...], shell patterns, a parent named by its type) that need "
            "-d and restrict the apply to the selected deletions, the other changes being skipped and counted; "
            "before, the option was unknown (exit 2). Without the option the plan, prompt and summary must not change"
        ),
    }
]
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
DELETE_FILTER_REQUIRES_D = "option '--delete-filter' requires '--delete-resources'"
INVALID_SELECTOR = "invalid resource selector"
NO_SUCH_OPTION = "No such option"  # click's usage error of an unknown option (SUTs without #939)
PLANNING_ABORTED = "Planning aborted due to validation errors."  # operations/plan.py handle_validation_status


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


@pytest.mark.scenario(
    "O-LOCAL-APPLY-VALIDATION-ERRORS",
    references=[
        {
            "pr": 923,
            "note": (
                "'feat: restrict the secrets that an organization can reference' also makes "
                "ApplyOperation.handle_finish return the validation error count (KB-001): local-apply then exits 1 "
                "instead of printing 'No changes required.' and exiting 0"
            ),
        }
    ],
)
@pytest.mark.known_bug("KB-001")
def test_validation_errors_fail_the_local_apply(local_apply_cli: OtterdogCli) -> None:
    """A configuration with one validation error (a secret named with the reserved GITHUB_ prefix) and something to
    add: validation aborts the planning, nothing is planned nor asked, and local-apply exits with the error (1), never
    with 'No changes required.' and 0 (KB-001, fixed by #923 in 1.8.0: the same ApplyOperation.handle_finish as
    apply)."""
    invalid = ConfigFragments(
        repositories=[f"orgs.newRepo('{NEW}')"],
        secrets=[f"orgs.newOrgSecret('GITHUB_{RUN.const_prefix}LOCAL') {{ value: 'pass:e2e/local' }}"],
    )
    sides(local_apply_cli, base=ConfigFragments(), head=invalid)
    result = local_apply(local_apply_cli, "-f", input="")
    text = normalize_text(result.output)
    assert "starts with prefix 'GITHUB_' which is not allowed for secrets." in text, tail(result)
    assert PLANNING_ABORTED in text and f'+ add repository[name="{NEW}"]' not in text, tail(result)
    assert PROMPT not in text and EXECUTED not in text, tail(result)
    assert NO_CHANGES not in text, f"local-apply reports success despite the validation error (KB-001)\n{tail(result)}"
    assert result.exit_code == 1, f"exit {result.exit_code} despite 1 validation error (KB-001)\n{tail(result)}"


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


# --- delete filter (#939) ---------------------------------------------------------------------------------------------
DF_REPO = RUN.name("df-repo")
DF_GONE = RUN.name("df-gone")
DF_NEW = RUN.name("df-new")
DF_ENV = RUN.name("df-env")
DF_V1 = f"{RUN.const_prefix}DF_V1"
DF_V2 = f"{RUN.const_prefix}DF_V2"
DF_ORG_VAR = f"{RUN.const_prefix}DF_ORG"
DF_OLD = RUN.name("df-old")
DF_RENAMED = RUN.name("df-renamed")
DF_RV = f"{RUN.const_prefix}DF_RV"
# the four removals of delete_filter_sides, by name, and its two other changes
DF_REMOVALS = {
    "variable": f'- remove repo_variable[name="{DF_V2}", repository={DF_REPO}]',
    "environment": f'- remove environment[name="{DF_ENV}", repository={DF_REPO}]',
    "repository": f'- remove repository[name="{DF_GONE}"]',
    "org_variable": f'- remove org_variable[name="{DF_ORG_VAR}"]',
}
DF_OTHERS = (f'+ add repository[name="{DF_NEW}"]', f'~ repository[name="{DF_REPO}"]')
NO_MATCH = "no resource to delete matches the delete filter '{}'."


def skipped_line(count: int) -> str:
    """The line of an apply whose delete filter skipped ``count`` changes (operations/apply.py handle_finish)."""
    return f"{count} other change(s) are skipped, only the deletions selected by '--delete-filter' are applied."


def has_939(history: SutHistory) -> bool:
    """Whether the SUT contains #939 (its squash commit or the head of its pull request); skip when undecidable."""
    found = [history.contains(commit) for commit in FEATURE_939]
    if True in found:
        return True
    if False in found:
        return False
    pytest.skip(f"cannot tell whether {history.label} contains #939 ({FEATURE_939[0][:7]})")


def flat(text: str) -> str:
    """Normalized output with every run of whitespace collapsed (warnings are boxed and may wrap)."""
    return " ".join(normalize_text(text).split())


def filters(*selectors: str) -> list[str]:
    """``--delete-filter <selector>`` per selector."""
    return [arg for selector in selectors for arg in ("--delete-filter", selector)]


def delete_filter_sides(cli: OtterdogCli) -> None:
    """-BASE: a repository with two variables and an environment, a second repository and an organization variable;
    head: the first repository with one variable left and another description, a new repository instead of the
    second, no organization variable. The plan: 4 removals (a repository variable, an environment, a repository, an
    organization variable), 1 addition and 1 change."""
    base = ConfigFragments(
        repositories=[
            f"""orgs.newRepo('{DF_REPO}') {{
              description: 'one',
              variables: [
                orgs.newRepoVariable('{DF_V1}') {{ value: 'kept' }},
                orgs.newRepoVariable('{DF_V2}') {{ value: 'gone' }},
              ],
              environments: [orgs.newEnvironment('{DF_ENV}')],
            }}""",
            f"orgs.newRepo('{DF_GONE}')",
        ],
        variables=[f"orgs.newOrgVariable('{DF_ORG_VAR}') {{ value: 'gone' }}"],
    )
    head = ConfigFragments(
        repositories=[
            f"""orgs.newRepo('{DF_REPO}') {{
              description: 'two',
              variables: [orgs.newRepoVariable('{DF_V1}') {{ value: 'kept' }}],
            }}""",
            f"orgs.newRepo('{DF_NEW}')",
        ]
    )
    sides(cli, base=base, head=head)


@pytest.mark.scenario("O-LOCAL-APPLY-DELETE-FILTER", references=DELETE_FILTER_REFERENCES)
@pytest.mark.parametrize(
    ("selectors", "selected"),
    [
        pytest.param((f'repo_variable[name="{DF_V2}"]',), ("variable",), id="key"),
        pytest.param(("environment", f'repository[name="{DF_GONE}"]'), ("environment", "repository"), id="repeated"),
        pytest.param((f"org_variable[name={RUN.const_prefix}DF_*]",), ("org_variable",), id="value-pattern"),
        pytest.param((f"*[repository={DF_REPO}]",), ("variable", "environment"), id="parent"),
        pytest.param(("repo_*",), ("variable",), id="type-pattern"),
    ],
)
def test_a_delete_filter_applies_only_the_selected_deletions(
    local_apply_cli: OtterdogCli, sut_history: SutHistory, selectors: tuple[str, ...], selected: tuple[str, ...]
) -> None:
    """local-apply -d --delete-filter: only the removals the selectors match are shown, the other removals, the
    addition and the change are skipped and counted before the prompt; 'n' cancels (since #939; older SUTs refuse the
    option, exit 2)."""
    fixed = has_939(sut_history)
    delete_filter_sides(local_apply_cli)
    result = local_apply(local_apply_cli, "-d", *filters(*selectors), input="n\n")
    text = normalize_text(result.output)
    if not fixed:
        assert result.exit_code == 2 and NO_SUCH_OPTION in text, f"exit {result.exit_code}\n{tail(result)}"
        return
    assert result.exit_code == 0, f"exit {result.exit_code}\n{tail(result)}"
    shown = {name for name, header in DF_REMOVALS.items() if header in text}
    assert shown == set(selected), f"removals shown {sorted(shown)}, selected {sorted(selected)}\n{tail(result, 60)}"
    assert not [header for header in DF_OTHERS if header in text], tail(result, 60)
    skipped = len(DF_REMOVALS) + len(DF_OTHERS) - len(selected)
    order = [text.find(skipped_line(skipped)), text.find(PROMPT), text.find(CANCELLED)]
    assert all(index >= 0 for index in order) and order == sorted(order), f"order {order}\n{tail(result, 60)}"
    assert NOT_REMOVED not in text and EXECUTED not in text and "matches the delete filter" not in text, tail(result)


@pytest.mark.scenario("O-LOCAL-APPLY-DELETE-FILTER", references=DELETE_FILTER_REFERENCES)
def test_without_delete_filter_every_change_is_planned(local_apply_cli: OtterdogCli) -> None:
    """Control on every SUT: the same sides with -d and no filter plan the four removals, the addition and the change
    and skip nothing (#939 must not change the plan of an unfiltered apply)."""
    delete_filter_sides(local_apply_cli)
    result = local_apply(local_apply_cli, "-d", input="n\n")
    text = normalize_text(result.output)
    assert result.exit_code == 0, f"exit {result.exit_code}\n{tail(result)}"
    missing = [header for header in (*DF_REMOVALS.values(), *DF_OTHERS) if header not in text]
    assert not missing, f"missing {missing}\n{tail(result, 60)}"
    assert "other change(s) are skipped" not in text and PROMPT in text and CANCELLED in text, tail(result)


@pytest.mark.scenario("O-LOCAL-APPLY-DELETE-FILTER", references=DELETE_FILTER_REFERENCES)
def test_a_delete_filter_selecting_nothing_changes_nothing(
    local_apply_cli: OtterdogCli, sut_history: SutHistory
) -> None:
    """Selectors that match no removal (a type with nothing to delete, a misspelled type) are each warned about; with
    no removal selected at all every change is skipped: 'No changes required.', the skipped line, exit 0 and no
    prompt. A selector next to one that matches is warned about while the other's deletion is planned."""
    fixed = has_939(sut_history)
    delete_filter_sides(local_apply_cli)
    result = local_apply(local_apply_cli, "-d", *filters("org_secret", "repo_variables"), input="")
    text = normalize_text(result.output)
    if not fixed:
        assert result.exit_code == 2 and NO_SUCH_OPTION in text, f"exit {result.exit_code}\n{tail(result)}"
        return
    assert result.exit_code == 0, f"exit {result.exit_code}\n{tail(result)}"
    assert NO_MATCH.format("org_secret") in flat(text) and NO_MATCH.format("repo_variables") in flat(text), tail(result)
    assert NO_CHANGES in text and skipped_line(6) in text, tail(result)
    assert not [header for header in (*DF_REMOVALS.values(), *DF_OTHERS) if header in text], tail(result, 60)
    assert PROMPT not in text and EOF_ERROR not in text and EXECUTED not in text, tail(result)

    partly = local_apply(local_apply_cli, "-d", *filters("environment", "org_secret"), input="n\n")
    text = normalize_text(partly.output)
    assert partly.exit_code == 0, f"exit {partly.exit_code}\n{tail(partly)}"
    assert NO_MATCH.format("org_secret") in flat(text) and NO_MATCH.format("environment") not in flat(text)
    assert DF_REMOVALS["environment"] in text and skipped_line(5) in text and CANCELLED in text, tail(partly, 60)


@pytest.mark.scenario("O-LOCAL-APPLY-DELETE-FILTER", references=DELETE_FILTER_REFERENCES)
@pytest.mark.parametrize(
    ("args", "message"),
    [
        pytest.param(("--delete-filter", "environment"), DELETE_FILTER_REQUIRES_D, id="without-d"),
        pytest.param(("-d", "--delete-filter", ""), INVALID_SELECTOR, id="empty"),
        pytest.param(("-d", "--delete-filter", "org_variable[]"), INVALID_SELECTOR, id="no-condition"),
        pytest.param(("-d", "--delete-filter", 'org_variable[name="a" b]'), INVALID_SELECTOR, id="after-quote"),
        pytest.param(("-d", "--delete-filter", "org_variable[=a]"), INVALID_SELECTOR, id="no-name"),
        pytest.param(("-d", "--delete-filter", "org_variable[name=a"), INVALID_SELECTOR, id="unclosed"),
    ],
)
def test_delete_filter_usage_errors(
    local_apply_cli: OtterdogCli, sut_history: SutHistory, args: tuple[str, ...], message: str
) -> None:
    """--delete-filter without -d and malformed selectors are usage errors: exit 2 before any plan (since #939;
    older SUTs refuse the option itself)."""
    fixed = has_939(sut_history)
    delete_filter_sides(local_apply_cli)
    result = local_apply(local_apply_cli, *args, input="")
    text = normalize_text(result.output)
    assert result.exit_code == 2, f"exit {result.exit_code}\n{tail(result)}"
    assert (message if fixed else NO_SUCH_OPTION) in flat(text), tail(result)
    assert not [header for header in (*DF_REMOVALS.values(), *DF_OTHERS) if header in text], tail(result, 60)
    assert PROMPT not in text, tail(result)


@pytest.mark.scenario("O-LOCAL-APPLY-DELETE-FILTER", references=DELETE_FILTER_REFERENCES)
@pytest.mark.parametrize(
    ("selectors", "repository", "skipped"),
    [
        pytest.param((), DF_RENAMED, None, id="unfiltered"),
        pytest.param(("repo_variable",), DF_OLD, 1, id="filtered"),
        pytest.param((f"repo_variable[repository={DF_RENAMED}]",), None, 2, id="new-name"),
    ],
)
def test_deletions_in_a_renamed_repository(
    local_apply_cli: OtterdogCli,
    sut_history: SutHistory,
    selectors: tuple[str, ...],
    repository: str | None,
    skipped: int | None,
) -> None:
    """A repository renamed through aliases that loses a variable: an unfiltered -d plans the rename and the removal
    under the new name; with a delete filter only the deletion is applied, the rename is skipped, so the variable is
    removed from the repository by its current (old) name and a selector naming the new name selects nothing."""
    if selectors and not has_939(sut_history):
        pytest.skip(f"{sut_history.label} does not contain #939: no --delete-filter")
    base = ConfigFragments(
        repositories=[f"orgs.newRepo('{DF_OLD}') {{ variables: [orgs.newRepoVariable('{DF_RV}') {{ value: 'r' }}] }}"]
    )
    head = ConfigFragments(repositories=[f"orgs.newRepo('{DF_RENAMED}') {{ aliases: ['{DF_OLD}'] }}"])
    sides(local_apply_cli, base=base, head=head)
    result = local_apply(local_apply_cli, "-d", *filters(*selectors), input="n\n")
    text = normalize_text(result.output)
    assert result.exit_code == 0, f"exit {result.exit_code}\n{tail(result)}"
    headers = {name: f'- remove repo_variable[name="{DF_RV}", repository={name}]' for name in (DF_OLD, DF_RENAMED)}
    removed = [name for name, header in headers.items() if header in text]
    assert removed == ([repository] if repository else []), f"removed under {removed}\n{tail(result, 60)}"
    renamed = f'~ repository[name="{DF_RENAMED}"]' in text
    assert renamed is (not selectors), tail(result, 60)
    if skipped is None:
        assert "other change(s) are skipped" not in text and CANCELLED in text, tail(result)
    else:
        assert skipped_line(skipped) in text, tail(result)
    if repository is None:
        assert NO_MATCH.format(selectors[0]) in flat(text) and NO_CHANGES in text and PROMPT not in text, tail(result)
