"""otterdog's cached clone of the base template, offline (O-TEMPLATE-CACHE).

Without ``--local``, otterdog keeps one clone of the base template repository per ref in
``<config_dir>/templates/<owner>/<repo>/<ref>`` (otterdog/jsonnet.py ``JsonnetConfig._init_base_template`` and
``_update_template_repo``): the first run clones it from github.com (live tiers only), a later run pulls it when the
ref is a branch (an attached head) and never touches it when the ref is a tag or a commit sha (a detached head); the
clone is then copied, without ``.git``, to ``<org dir>/vendor/<repo>``. Offline, the tests seed that cache with a
clone whose ``origin`` is a bare repository at the workspace root, named by a path relative to the clone: git
resolves it from the clone directory, on the host as in the container's ``/ws`` mount, so the pull needs no network.

* since eclipse-csi/otterdog#921 (1.8.0), a branch ref is reported once per process: "base template '<url>'
  references the branch '<ref>': every push to it changes the default configuration and the python scripts that
  otterdog executes from it, reference a tag or a commit SHA instead"; a tag or a commit sha is not reported;
* since eclipse-csi/otterdog#927 (1.8.0), the clone or pull holds an exclusive flock on ``<template dir>.lock``, so
  the otterdog processes sharing the cache wait for each other instead of cloning or pulling the same directory at
  once (before, a second process failed or raced). The test holds that lock itself: a SUT with #927 cannot finish
  its update before the test releases it.

Every host git command (run_git: no hooks, no fsmonitor) runs before the first otterdog command of a test: the
container of an untrusted SUT can write in the workspace, its bare repository included; vendored files are read back
with read_untrusted_text.
"""

from __future__ import annotations

import fcntl
import os
import shutil
import threading
from pathlib import Path
from typing import Protocol

import pytest

from otterdog_acceptance.otterdog.output import normalize_text
from otterdog_acceptance.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_acceptance.otterdog.runner import CliResult, OtterdogCli
from otterdog_acceptance.otterdog.workspace import ConfigWorkspace, WorkspaceLayout, read_untrusted_text
from otterdog_acceptance.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_ORG,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
)
from otterdog_acceptance.sut.source import run_git
from otterdog_acceptance.sut.template import PUBLISHED_TEMPLATE_FILE

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli", "template")]

# squash commit on main and head of the pull request (a pr: SUT of that head does not contain the squash commit)
FIX_921 = ("8d0da8b44c43ab6741e32d37e8604371ae7833f1", "3994f9abb0f348f00fbb44831bb126bacb16f02d")
FIX_927 = ("29ddd00280959a1e8c9fd4ca0c64d5299d4407bb", "bacb26723b63ee9e6211387b1f98c4d2e8e52c74")
REFERENCES = [
    {
        "pr": 921,
        "note": (
            "'feat: warn when base_template references a branch': a non-local run whose base template ref is a "
            "branch logs one warning per process (a tag or a commit sha none); the pull of the branch and the copy "
            "to vendor/ must not change"
        ),
    },
    {
        "pr": 927,
        "note": (
            "'fix: synchronize the otterdog processes updating the same base template': the clone or pull of a "
            "cached template holds an exclusive flock on <template dir>.lock, so a second process waits for the "
            "first; the pull and the copy to vendor/ must not change"
        ),
    },
]
OWNER, REPO = "e2e-offline", "template"  # of the offline template URL: the clone is templates/<owner>/<repo>/<ref>
TEMPLATE_URL = f"https://github.com/{OWNER}/{REPO}#{PUBLISHED_TEMPLATE_FILE}@{{ref}}"
ORIGIN = "template-origin.git"  # the bare repository at the workspace root that the seeded clones pull from
SOURCE = "template-source"  # the working repository the commits of the origin are made in
BRANCH, TAG = "main", "v1.0.0"
MARKER = "// e2e: second commit of the base template"  # a jsonnet comment, appended by the second commit
GIT_IDENTITY = ("-c", "user.name=e2e", "-c", "user.email=e2e@example.invalid", "-c", f"init.defaultBranch={BRANCH}")
SECOND = f"{OFFLINE_ORG}-2"  # github_id of the second organization
SECOND_PROJECT = f"{OFFLINE_ORG}-two"
SUCCEEDED = "Validation succeeded"
BRANCH_WARNING = "references the branch '{ref}'"
HOLD = 10.0  # seconds the test holds the lock of the clone


class SutHistory(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when undecidable."""


def has_fix(history: SutHistory, commits: tuple[str, str], pr: int) -> bool:
    """Whether the SUT contains the pull request (its squash commit or its head); skip when undecidable."""
    found = [history.contains(commit) for commit in commits]
    if True in found:
        return True
    if False in found:
        return False
    pytest.skip(f"cannot tell whether {history.label} contains #{pr} ({commits[0][:7]})")


def git(*args: str, cwd: Path) -> str:
    """A hardened host git command (no hooks) with a fixed identity; local paths allowed; returns stdout."""
    return run_git([*GIT_IDENTITY, *args], cwd=cwd, file_protocol="always").stdout


def render_org(workspace: ConfigWorkspace, *, org: str | None = None, project: str | None = None) -> str:
    """An empty configuration of an organization of the workspace, rendered as OfflineEngine renders it; it imports
    ``vendor/template/otterdog-defaults.libsonnet``, the copy of the cached clone."""
    renderer = OfflineConfigRenderer(
        template=workspace.template,
        org=org or workspace.org,
        plan=OFFLINE_DEFAULT_PLAN,
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
        project=project or (workspace.project if org is None else org),
    )
    return renderer.render(ConfigFragments())


def use_template_ref(workspace: ConfigWorkspace, ref: str, *, second_org: bool = False) -> None:
    """Base template ``https://github.com/e2e-offline/template#otterdog-defaults.libsonnet@<ref>`` (defaults override)
    and the configuration of the organization (and of a second one sharing the template)."""
    orgs = ({"github_id": SECOND, "name": SECOND_PROJECT},) if second_org else ()
    override = {"jsonnet": {"base_template": TEMPLATE_URL.format(ref=ref)}}
    workspace.use_layout(WorkspaceLayout(orgs=orgs, defaults_override=override))
    workspace.write_org_config(render_org(workspace))
    if second_org:
        workspace.write_org_config(render_org(workspace, org=SECOND, project=SECOND_PROJECT), org=SECOND)


def publish_origin(workspace: ConfigWorkspace, template_src: Path) -> str:
    """The SUT's template committed on branch main (tag v1.0.0) of a source repository, cloned bare as the origin at
    the workspace root; returns the sha of that first commit."""
    source = workspace.root / SOURCE
    git("init", "-q", str(source), cwd=workspace.root)
    for path in sorted(template_src.glob("*.libsonnet")):
        if path.is_file() and not path.is_symlink():
            shutil.copyfile(path, source / path.name)
    git("add", "-A", cwd=source)
    git("commit", "-q", "-m", "first", cwd=source)
    git("tag", TAG, cwd=source)
    git("clone", "-q", "--bare", str(source), str(workspace.root / ORIGIN), cwd=workspace.root)
    return git("rev-parse", "HEAD", cwd=source).strip()


def seed_clone(workspace: ConfigWorkspace, ref: str, checkout: str) -> Path:
    """otterdog's cached clone of the template at ``ref`` (templates/e2e-offline/template/<ref>), checked out at
    ``checkout`` (the branch: attached head; a tag or a sha: detached head), its origin the bare repository named
    relative to the clone."""
    clone = workspace.templates_dir / OWNER / REPO / ref
    clone.parent.mkdir(parents=True, exist_ok=True)
    git("clone", "-q", str(workspace.root / ORIGIN), str(clone), cwd=workspace.root)
    git("checkout", "-q", checkout, cwd=clone)
    git("remote", "set-url", "origin", os.path.relpath(workspace.root / ORIGIN, clone), cwd=clone)
    return clone


def push_second_commit(workspace: ConfigWorkspace, *, move_tag: bool = False) -> None:
    """A second commit (MARKER appended to the template file) pushed to main of the origin; ``move_tag`` also moves
    the tag v1.0.0 of the origin to it."""
    source = workspace.root / SOURCE
    template = source / PUBLISHED_TEMPLATE_FILE
    template.write_text(template.read_text(encoding="utf-8") + f"\n{MARKER}\n", encoding="utf-8")
    git("commit", "-q", "-a", "-m", "second", cwd=source)
    origin = str(workspace.root / ORIGIN)
    git("push", "-q", origin, BRANCH, cwd=source)
    if move_tag:
        git("tag", "-f", TAG, cwd=source)
        git("push", "-q", "-f", origin, f"refs/tags/{TAG}", cwd=source)


def vendored_template(workspace: ConfigWorkspace, org: str | None = None) -> str:
    """The template file otterdog copied to vendor/template of an organization ('' when missing)."""
    path = workspace.org_dir_for(org or workspace.org) / "vendor" / REPO / PUBLISHED_TEMPLATE_FILE
    return read_untrusted_text(path, within=workspace.root) or ""


def validate(cli: OtterdogCli) -> CliResult:
    """``validate`` WITHOUT --local (the cached clone is updated and copied), every organization."""
    return cli.run("validate", org=False, local=False)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


def branch_warnings(result: CliResult, ref: str) -> int:
    """How many times the output reports the base template as referencing branch ``ref``."""
    return normalize_text(result.output).count(BRANCH_WARNING.format(ref=ref))


@pytest.mark.scenario("O-TEMPLATE-CACHE", references=REFERENCES)
def test_a_branch_ref_is_pulled_and_reported_once(
    offline_cli: OtterdogCli, template_src: Path, sut_history: SutHistory
) -> None:
    """Two organizations share a base template whose ref is the branch main; its cached clone is one commit behind
    the origin. validate pulls the branch: both vendored copies hold the second commit (without .git). A SUT with #921
    reports the branch once (one process, two organizations), an older SUT never."""
    warns = has_fix(sut_history, FIX_921, 921)
    workspace = offline_cli.workspace
    use_template_ref(workspace, BRANCH, second_org=True)
    publish_origin(workspace, template_src)
    seed_clone(workspace, BRANCH, BRANCH)
    push_second_commit(workspace)

    result = validate(offline_cli)
    assert result.exit_code == 0 and SUCCEEDED in normalize_text(result.output), (
        f"exit {result.exit_code}\n{tail(result)}"
    )
    for org in (OFFLINE_ORG, SECOND):
        assert MARKER in vendored_template(workspace, org), f"{org}: the branch was not pulled before the copy"
        assert not (workspace.org_dir_for(org) / "vendor" / REPO / ".git").exists(), f"{org}: .git was copied"
    assert branch_warnings(result, BRANCH) == (1 if warns else 0), (
        f"{sut_history.label} (#921: {warns}): the branch warning must appear {1 if warns else 0} time(s)\n"
        f"{tail(result)}"
    )


@pytest.mark.scenario("O-TEMPLATE-CACHE", references=REFERENCES)
@pytest.mark.parametrize("kind", ["tag", "sha"])
def test_a_tag_or_commit_ref_is_never_refreshed_nor_reported(
    offline_cli: OtterdogCli, template_src: Path, kind: str
) -> None:
    """A base template pinned to a tag (moved to a second commit in the origin since) or to a commit sha: the cached
    clone, a detached head, is copied as it is (no second commit) and no SUT reports a branch."""
    workspace = offline_cli.workspace
    first = publish_origin(workspace, template_src)
    ref = TAG if kind == "tag" else first
    use_template_ref(workspace, ref)
    seed_clone(workspace, ref, ref)
    push_second_commit(workspace, move_tag=kind == "tag")

    result = validate(offline_cli)
    assert result.exit_code == 0 and SUCCEEDED in normalize_text(result.output), (
        f"exit {result.exit_code}\n{tail(result)}"
    )
    vendored = vendored_template(workspace)
    assert vendored and MARKER not in vendored, f"the cached clone of {kind} {ref} was refreshed or not copied"
    assert "references the branch" not in normalize_text(result.output), tail(result)


@pytest.mark.scenario("O-TEMPLATE-CACHE", references=REFERENCES)
def test_a_process_waits_for_the_lock_of_the_cached_clone(
    offline_cli: OtterdogCli, template_src: Path, sut_history: SutHistory
) -> None:
    """Another process (the test) holds the flock of templates/e2e-offline/template/main.lock for HOLD seconds: a SUT
    with #927 waits for it before it pulls the clone (validate lasts at least HOLD seconds), then validates with the
    pulled template; an older SUT ignores the lock. Both succeed."""
    waits = has_fix(sut_history, FIX_927, 927)
    workspace = offline_cli.workspace
    use_template_ref(workspace, BRANCH)
    publish_origin(workspace, template_src)
    clone = seed_clone(workspace, BRANCH, BRANCH)
    push_second_commit(workspace)
    lock_file = clone.parent / f"{clone.name}.lock"  # created here, before any otterdog command could plant a link

    with open(lock_file, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        release = threading.Timer(HOLD, fcntl.flock, args=(lock, fcntl.LOCK_UN))
        release.start()
        try:
            result = validate(offline_cli)
        finally:
            release.cancel()
            fcntl.flock(lock, fcntl.LOCK_UN)

    assert result.exit_code == 0 and SUCCEEDED in normalize_text(result.output), (
        f"exit {result.exit_code}\n{tail(result)}"
    )
    assert MARKER in vendored_template(workspace), "the branch was not pulled before the copy"
    if waits:
        assert result.duration >= HOLD - 1, (
            f"{sut_history.label} contains #927 but validate took {result.duration:.1f} s while another process held "
            f"{lock_file.name} for {HOLD:.0f} s: it did not wait for the lock"
        )
