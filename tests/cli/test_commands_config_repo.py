"""Variants of the config-repository commands: fetch-config, push-config and open-pr (the happy paths are in
test_config_repo_cli.py).

The ``config_repo`` fixture puts the baseline on the default branch of the session's org config repository before
each test and again after it, closes the pull requests and deletes the run branches the test created (otterdog's own
``otterdog/e2e-<run>-<slug>`` branches included). Configurations that change the model add run repositories only;
they are pushed to the config repository, never applied (the webapp only fetches a pushed configuration).

cli.fetch-config.variants: ``-p <n>`` reads the head of pull request n, ``-r <ref>`` a branch, ``-s <suffix>`` writes
    ``<org>.jsonnet<suffix>``; without ``-f`` an existing file is only overwritten after 'y'; an unknown pull request
    fails (otterdog/operations/fetch_config.py).
cli.kb.fetch-config-ref-message (known bug KB-049): ``-r <ref>`` says it fetched from the default branch.
cli.push-config.variants: the diff against the current definition and the prompt ('n' -> 'push cancelled.', 'y'
    pushes with ``-m`` as message), an identical file pushes nothing, ``-n`` pushes without diff nor prompt with the
    default message "Updating file 'otterdog/<org>.jsonnet' with otterdog.", an invalid configuration is not pushed,
    a config repository without definition asks 'No configuration yet available.' (otterdog/operations/push_config.py).
cli.kb.push-config-invalid-exit-code (known bug KB-046): pushing an invalid configuration exits 0 with 'no changes,
    nothing pushed'.
cli.open-pr.negatives: no PR for an identical configuration, a validation error, an unknown author or a refused
    prompt, and no branch is left behind; the PR otterdog opens has the given title and the fixed body
    (otterdog/operations/open_pull_request.py).
cli.config-repo.missing: fetch-config, push-config and open-pr report a config repository that does not exist.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.workspace import read_untrusted_text

if TYPE_CHECKING:
    from conftest import ConfigRepo, LiveConfig
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli")]

PROMPT_TEXT = "(Only 'yes' or 'y' will be accepted"
DIFF_HEADER = "The following changes compared to the current configuration exist locally:"
PUSH_QUESTION = "Do you want to push these changes?"
PUSHED_TEXT = "organization definition pushed to repo"
NOTHING_PUSHED = "no changes, nothing pushed"
OPEN_PR_QUESTION = "Do you want to open a PR with these changes?"
CREATED_PR_RE = re.compile(r"created pull request #(?P<number>\d+) at (?P<url>\S+)")
ABORTED_TEXT = "Planning aborted due to validation errors."


def variant(text: str, run_ctx: RunContext, purpose: str) -> str:
    """The configuration with one more trailing jsonnet comment (a content change, no model change)."""
    return text.rstrip("\n") + f"\n// otterdog-e2e {purpose} of run {run_ctx.run_id}\n"


def with_repo(baseline: BaselineManager, name: str, description: str) -> str:
    """The baseline plus a run repository (a model change for the local-plan diffs; never applied)."""
    snippet = f"orgs.newRepo('{name}') {{ description: '{description}' }}"
    return baseline.renderer.render(ConfigFragments(repositories=[snippet]))


def head_sha(config_repo: ConfigRepo) -> str | None:
    """Sha of the head commit of the config repository's default branch."""
    head = config_repo.head()
    return str(head["sha"]) if head else None


def invalid(baseline: BaselineManager, name: str) -> str:
    """The baseline plus a run repository with an invalid topic (a validation error)."""
    snippet = f'orgs.newRepo(\'{name}\') {{ description: "otterdog e2e: invalid", topics: ["Invalid_Topic"] }}'
    return baseline.renderer.render(ConfigFragments(repositories=[snippet]))


# --- fetch-config ------------------------------------------------------------------------------------------------------
@pytest.mark.scenario("cli.fetch-config.variants", priority="P0")
def test_fetch_config_from_a_pull_request_and_a_ref(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    run_ctx: RunContext,
    target: Target,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``fetch-config -f -p <n> -s -PR`` writes the head of the pull request, ``-r <branch> -s -REF`` the branch, the
    plain fetch the default branch, each to its own file; an unknown pull request fails without writing."""
    pr_text = variant(baseline.text(), run_ctx, "fetch-config -p")
    ref_text = variant(baseline.text(), run_ctx, "fetch-config -r")
    number = config_repo.pull(config_repo.branch("fetch-pr", pr_text), f"otterdog-e2e {run_ctx.run_id}: fetch -p")
    ref_branch = config_repo.branch("fetch-ref", ref_text)
    cli = make_cli(fresh_workspace)

    def read(path: Path) -> str | None:
        """A file the SUT wrote (never through a link it planted: ISO-01)."""
        return read_untrusted_text(path, within=fresh_workspace.root)

    pr_file = fresh_workspace.org_config_file_for(target.org, suffix="-PR")
    ref_file = fresh_workspace.org_config_file_for(target.org, suffix="-REF")
    by_pr = cli_lines(cli.run("fetch-config", "-f", "-p", str(number), "-s", "-PR").assert_ok("fetch-config -p"))
    assert f"organization definition fetched from pull request #{number} to '" in by_pr, by_pr[-2000:]
    assert f"{pr_file.name}'" in by_pr, by_pr[-2000:]
    assert read(pr_file) == pr_text, "fetch-config -p did not write the pull request head"
    by_ref = cli_lines(cli.run("fetch-config", "-f", "-r", ref_branch, "-s", "-REF").assert_ok("fetch-config -r"))
    assert f"{ref_file.name}'" in by_ref, by_ref[-2000:]
    assert read(ref_file) == ref_text, f"fetch-config -r did not write {ref_branch}"
    default = cli_lines(cli.run("fetch-config", "-f").assert_ok("fetch-config"))
    assert "organization definition fetched from default branch to '" in default, default[-2000:]
    assert fresh_workspace.read_org_config() == baseline.text(), "fetch-config did not write the default branch"
    assert read(pr_file) == pr_text and read(ref_file) == ref_text
    missing_file = fresh_workspace.org_config_file_for(target.org, suffix="-MISSING")
    missing = cli.run("fetch-config", "-f", "-p", "999999", "-s", "-MISSING")
    text = cli_lines(missing)
    assert f"failed to fetch definition from repo '{config_repo.repo}'" in text, text[-2000:]
    assert missing.exit_code == 1, f"exit {missing.exit_code}"
    assert not missing_file.exists(), "a failed fetch wrote a file"


@pytest.mark.scenario("cli.fetch-config.variants", priority="P0")
def test_fetch_config_asks_before_overwriting(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """Without ``-f`` an existing local file is kept on 'n' (exit 1, 'Operation cancelled.') and replaced by the
    default branch on 'y'."""
    local = variant(baseline.text(), run_ctx, "local edit kept by fetch-config")
    fresh_workspace.write_org_config(local)
    cli = make_cli(fresh_workspace)
    refused = cli.run("fetch-config", input="n\n")
    text = cli_lines(refused)
    assert "Configuration already exists at '" in text and PROMPT_TEXT in text, text[-2000:]
    assert "Operation cancelled." in text and refused.exit_code == 1, f"exit {refused.exit_code}:\n{text[-2000:]}"
    assert fresh_workspace.read_org_config() == local, "the refused fetch overwrote the local file"
    accepted = cli_lines(cli.run("fetch-config", input="y\n").assert_ok("fetch-config answered 'y'"))
    assert "organization definition fetched from default branch" in accepted, accepted[-2000:]
    assert fresh_workspace.read_org_config() == baseline.text(), "the accepted fetch did not write the default branch"


@pytest.mark.scenario("cli.kb.fetch-config-ref-message", priority="P2")
@pytest.mark.known_bug("KB-049")
@pytest.mark.tags("known-bug")
def test_fetch_config_names_the_ref(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``fetch-config -r <branch>`` must not claim it read the default branch (KB-049: the message ignores -r)."""
    branch = config_repo.branch("fetch-ref-message", variant(baseline.text(), run_ctx, "fetch-config -r message"))
    text = cli_lines(make_cli(fresh_workspace).run("fetch-config", "-f", "-r", branch).assert_ok("fetch-config -r"))
    assert "fetched from default branch" not in text, f"fetch-config -r {branch} reported the default branch"


# --- push-config -------------------------------------------------------------------------------------------------------
@pytest.mark.scenario("cli.push-config.variants", priority="P0")
def test_push_config_shows_the_diff_and_asks(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    run_ctx: RunContext,
    target: Target,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``push-config -m <msg>`` shows the local-plan diff against the current definition and asks: 'n' pushes
    nothing, 'y' pushes with the message; pushing the same file again pushes nothing and asks nothing."""
    repo_name = run_ctx.name("push-diff")
    text = with_repo(baseline, repo_name, "otterdog e2e: push-config diff")
    fresh_workspace.write_org_config(text)
    cli = make_cli(fresh_workspace)
    message = f"otterdog-e2e {run_ctx.run_id}: push-config with a diff"
    before = config_repo.head()
    refused = cli.run("push-config", "-m", message, input="n\n")
    output = cli_lines(refused)
    assert refused.exit_code == 0, f"exit {refused.exit_code}:\n{output[-2000:]}"
    for expected in (DIFF_HEADER, f'+ add repository[name="{repo_name}"]', PUSH_QUESTION, "push cancelled."):
        assert expected in output, f"{expected!r} missing:\n{output[-3000:]}"
    assert NOTHING_PUSHED in output and PUSHED_TEXT not in output, output[-2000:]
    assert config_repo.remote() == baseline.text(), "the refused push changed the definition"
    assert before and head_sha(config_repo) == before["sha"], "the refused push created a commit"
    accepted = cli_lines(cli.run("push-config", "-m", message, input="y\n").assert_ok("push-config answered 'y'"))
    assert f"{PUSHED_TEXT} '{target.org}/{config_repo.repo}'" in accepted, accepted[-2000:]
    assert f"- '{config_repo.path}'" in accepted, accepted[-2000:]
    assert config_repo.wait_remote(text) == text, "the accepted push did not write the definition"
    pushed = config_repo.head()
    assert pushed and pushed["message"] == message, pushed
    same = cli_lines(cli.run("push-config", "-m", message).assert_ok("push-config of the pushed file"))
    assert NOTHING_PUSHED in same and DIFF_HEADER not in same and PUSH_QUESTION not in same, same[-2000:]
    assert head_sha(config_repo) == pushed["sha"], "pushing the same file created a commit"


@pytest.mark.scenario("cli.push-config.variants", priority="P0")
def test_push_config_without_diff_uses_the_default_message(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    run_ctx: RunContext,
    target: Target,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """``push-config -n`` (no diff, no ``-m``, no ``-f``) pushes at once, without diff nor question, with the default
    commit message."""
    text = variant(baseline.text(), run_ctx, "push-config -n")
    fresh_workspace.write_org_config(text)
    output = cli_lines(make_cli(fresh_workspace).run("push-config", "-n").assert_ok("push-config -n"))
    assert f"{PUSHED_TEXT} '{target.org}/{config_repo.repo}'" in output, output[-2000:]
    assert DIFF_HEADER not in output and PUSH_QUESTION not in output, output[-2000:]
    assert config_repo.wait_remote(text) == text, "push-config -n did not write the definition"
    head = config_repo.head()
    assert head and head["message"] == f"Updating file '{config_repo.path}' with otterdog.", head


@pytest.mark.scenario("cli.push-config.variants", priority="P0")
def test_push_config_refuses_an_invalid_configuration(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """A configuration with a validation error is not pushed, even with ``-f``: the diff stops at the validation
    errors and the definition stays as it was."""
    fresh_workspace.write_org_config(invalid(baseline, run_ctx.name("push-invalid")))
    before = config_repo.head()
    result = make_cli(fresh_workspace).run("push-config", "-f", "-m", f"otterdog-e2e {run_ctx.run_id}: invalid")
    output = cli_lines(result)
    assert ABORTED_TEXT in output, f"no validation abort:\n{output[-3000:]}"
    assert PUSHED_TEXT not in output, output[-2000:]
    assert before and config_repo.remote() == baseline.text(), "an invalid configuration was pushed"
    assert head_sha(config_repo) == before["sha"], "refusing an invalid configuration created a commit"


@pytest.mark.scenario("cli.kb.push-config-invalid-exit-code", priority="P2")
@pytest.mark.known_bug("KB-046")
@pytest.mark.tags("known-bug")
def test_push_config_of_an_invalid_configuration_fails(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    run_ctx: RunContext,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """Refusing to push an invalid configuration is a failure: a non-zero exit and no 'no changes' claim (KB-046:
    exit 0 and 'no changes, nothing pushed')."""
    fresh_workspace.write_org_config(invalid(baseline, run_ctx.name("push-invalid-exit")))
    result = make_cli(fresh_workspace).run("push-config", "-f", "-m", f"otterdog-e2e {run_ctx.run_id}: invalid")
    output = cli_lines(result)
    assert ABORTED_TEXT in output, output[-3000:]
    assert NOTHING_PUSHED not in output, "an invalid configuration was reported as 'no changes'"
    assert result.exit_code != 0, f"exit {result.exit_code} although nothing could be pushed"


@pytest.mark.scenario("cli.push-config.variants", priority="P0")
@pytest.mark.tags("repo")
def test_push_config_to_a_repository_without_definition(
    live_config: LiveConfig,
    mutator: Mutator,
    oracle: Oracle,
    baseline: BaselineManager,
    run_ctx: RunContext,
    target: Target,
    cli_lines: Callable[[CliResult], str],
) -> None:
    """A config repository without ``otterdog/<org>.jsonnet`` (a new run repository): push-config says 'No
    configuration yet available.' and asks; 'n' pushes nothing, 'y' creates the definition."""
    repo = run_ctx.name("push-new-config")
    live_config.touch()  # removed with the run's objects
    mutator.create_repo(repo, description="otterdog e2e: config repository without definition", auto_init=True)
    assert live_config.wait_repo(repo) is not None, f"{repo} was not created"
    workspace = live_config.workspace
    workspace.config_repo = repo
    workspace.write_otterdog_json()
    workspace.write_org_config(baseline.text())
    path = f"otterdog/{target.org}.jsonnet"
    message = f"otterdog-e2e {run_ctx.run_id}: first definition"
    refused = live_config.cli.run("push-config", "-m", message, input="n\n")
    output = cli_lines(refused)
    for expected in ("No configuration yet available.", PUSH_QUESTION, "push cancelled.", NOTHING_PUSHED):
        assert expected in output, f"{expected!r} missing:\n{output[-2000:]}"
    assert oracle.file_content(repo, path) is None, "the refused push created the definition"
    accepted = cli_lines(live_config.cli.run("push-config", "-m", message, input="y\n").assert_ok("push-config 'y'"))
    assert f"{PUSHED_TEXT} '{target.org}/{repo}'" in accepted, accepted[-2000:]
    assert live_config.wait_file(repo, path, baseline.text()) == baseline.text(), "the definition was not created"


# --- open-pr -----------------------------------------------------------------------------------------------------------
def no_branch(config_repo: ConfigRepo, oracle: Oracle, branch: str) -> bool:
    """True when ``otterdog/<branch>`` does not exist and no open pull request comes from it."""
    head = f"otterdog/{branch}"
    pulls = [pull for pull in oracle.pulls(config_repo.repo) if (pull.get("head") or {}).get("ref") == head]
    return oracle.branch_sha(config_repo.repo, head) is None and not pulls


@pytest.mark.scenario("cli.open-pr.negatives", priority="P1")
def test_open_pr_opens_nothing_when_it_must_not(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    oracle: Oracle,
    run_ctx: RunContext,
    target: Target,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """open-pr opens no pull request and creates no branch for a configuration identical to the default branch
    (exit 0), one with a validation error (exit 1), an author that is no GitHub user (exit 2) and a refused prompt
    (exit 1)."""
    author = target.identities["admin"].login
    assert author, "the target declares no admin login"
    cli = make_cli(fresh_workspace)
    changed = with_repo(baseline, run_ctx.name("opr-change"), "otterdog e2e: open-pr")
    unknown_author = run_ctx.name("nobody")
    cases = (
        ("opr-same", baseline.text(), author, "y\n", 0, "no local changes, no PR has been opened"),
        ("opr-invalid", invalid(baseline, run_ctx.name("opr-invalid")), author, "y\n", 1,
         "the local configuration contains validation error"),
        ("opr-author", changed, unknown_author, "y\n", 2, f"author '{unknown_author}' is not a valid GitHub user"),
        ("opr-cancel", changed, author, "n\n", 1, "Open PR cancelled."),
    )  # fmt: skip
    for slug, text, who, answer, exit_code, expected in cases:
        branch = run_ctx.name(slug)
        config_repo.track_ref(f"heads/otterdog/{branch}")
        fresh_workspace.write_org_config(text)
        result = cli.run(
            "open-pr", "-b", branch, "-t", f"otterdog-e2e {run_ctx.run_id}: {slug}", "-a", who, input=answer
        )
        output = cli_lines(result)
        assert expected in output, f"{slug}: {expected!r} missing:\n{output[-3000:]}"
        assert result.exit_code == exit_code, f"{slug}: exit {result.exit_code}, expected {exit_code}"
        assert "created pull request" not in output, f"{slug}: a pull request was opened"
        assert no_branch(config_repo, oracle, branch), f"{slug}: otterdog/{branch} or its pull request exists"
        if slug == "opr-cancel":
            assert OPEN_PR_QUESTION in output and DIFF_HEADER in output, output[-3000:]


@pytest.mark.scenario("cli.open-pr.negatives", priority="P1")
def test_open_pr_title_and_body(
    config_repo: ConfigRepo,
    baseline: BaselineManager,
    oracle: Oracle,
    run_ctx: RunContext,
    target: Target,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """The pull request otterdog opens after showing the diff has the given title, the fixed body naming the author,
    the head ``otterdog/<branch>`` and the URL otterdog prints."""
    author = target.identities["admin"].login
    assert author, "the target declares no admin login"
    repo_name = run_ctx.name("opr-body")
    fresh_workspace.write_org_config(with_repo(baseline, repo_name, "otterdog e2e: open-pr body"))
    branch, title = run_ctx.name("opr-body"), f"otterdog-e2e {run_ctx.run_id}: open-pr title and body"
    config_repo.track_ref(f"heads/otterdog/{branch}")
    result = make_cli(fresh_workspace).open_pr(branch=branch, title=title, author=author).assert_ok("open-pr")
    output = cli_lines(result)
    assert DIFF_HEADER in output and f'+ add repository[name="{repo_name}"]' in output, output[-3000:]
    created = CREATED_PR_RE.search(output)
    assert created, f"open-pr printed no pull request:\n{output[-2000:]}"
    number = int(created.group("number"))
    config_repo.track_pull(number)
    assert created.group("url") == f"https://github.com/{target.org}/{config_repo.repo}/pull/{number}", created.group(0)
    pull = oracle.pull(config_repo.repo, number)
    assert pull is not None, f"pull request #{number} not found"
    assert pull.get("title") == title, pull.get("title")
    expected_body = f"This PR has been created automatically on behalf of @{author} using the otterdog cli."
    assert pull.get("body") == expected_body, pull.get("body")
    assert (pull.get("head") or {}).get("ref") == f"otterdog/{branch}", pull.get("head")


# --- a config repository that does not exist ---------------------------------------------------------------------------
@pytest.mark.scenario("cli.config-repo.missing", priority="P1")
def test_config_repo_commands_report_a_missing_repository(
    e2e: E2EContext,
    baseline: BaselineManager,
    oracle: Oracle,
    run_ctx: RunContext,
    target: Target,
    template_ref: TemplateRef,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
    cli_lines: Callable[[CliResult], str],
) -> None:
    """With a config_repo that does not exist, fetch-config, push-config and open-pr print their failure and exit 1;
    nothing is created."""
    missing = run_ctx.name("no-such-config")
    assert oracle.repo(missing) is None, f"{missing} exists"
    workspace = e2e.workspace(e2e.unique_name("missing-config-repo"), template_ref)
    workspace.config_repo = missing
    workspace.write_otterdog_json()
    workspace.write_org_config(baseline.text())
    cli = make_cli(workspace)
    author = target.identities["admin"].login or ""
    commands = (
        (("fetch-config", "-f", "-s", "-FETCHED"), None, f"failed to fetch definition from repo '{missing}'"),
        (
            ("push-config", "-f", "-m", "otterdog-e2e"),
            None,
            f"failed to push definition to repo '{target.org}/{missing}'",
        ),
        (
            ("open-pr", "-b", run_ctx.name("missing-pr"), "-t", "otterdog-e2e", "-a", author),
            "y\n",
            f"failed to open pull request in repo '{target.org}/{missing}'",
        ),
    )
    for args, answer, expected in commands:
        result = cli.run(*args, input=answer)
        output = cli_lines(result)
        assert expected in output, f"{args[0]}: {expected!r} missing:\n{output[-2000:]}"
        assert result.exit_code == 1, f"{args[0]}: exit {result.exit_code}"
    assert not workspace.org_config_file_for(target.org, suffix="-FETCHED").exists(), "the failed fetch wrote a file"
    assert oracle.repo(missing) is None, f"{missing} was created"
