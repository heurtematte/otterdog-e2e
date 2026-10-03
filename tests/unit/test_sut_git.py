"""Upstream mirror, exports, dirty overlays and resolve_sut against real local git repositories (no network).

The "upstream" is a bare repository in tmp_path served through file:// (LocalMirror); its history mimics otterdog's:
v1.5.0 (annotated), v1.6.0, v1.6.1 (lightweight), three commits on main, an untrusted feature branch and a pull request
head published as refs/pull/7/head.
"""

from __future__ import annotations

import io
import json
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path

import pytest

from otterdog_e2e import procs
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.settings import HarnessSettings
from otterdog_e2e.sut import spec as spec_mod
from otterdog_e2e.sut.source import (
    DIRTY_ALLOW,
    DIRTY_DENY,
    UpstreamMirror,
    export_local_checkout,
    extract_tar,
    path_allowed,
)
from otterdog_e2e.sut.spec import resolve_sut
from otterdog_e2e.testing.fakes import FakeGitHubHttp

GIT_ENV = {
    "GIT_AUTHOR_NAME": "e2e",
    "GIT_AUTHOR_EMAIL": "e2e@example.invalid",
    "GIT_COMMITTER_NAME": "e2e",
    "GIT_COMMITTER_EMAIL": "e2e@example.invalid",
}
UPSTREAM_REPO = "e2e-tests/otterdog"
BASE_FILES = {
    "README.md": "otterdog\n",
    "pyproject.toml": '[project]\nname = "otterdog"\n',
    "otterdog/__init__.py": "VERSION = 1\n",
    "otterdog.sh": "#!/bin/sh\necho otterdog\n",
    "docker/Dockerfile": "FROM scratch\n",
    "docs/old.md": "old docs\n",
    "examples/template/otterdog-defaults.libsonnet": "{ newOrg(name, id):: {} }\n",
    "examples/template/otterdog-functions.libsonnet": "{}\n",
}


def git(cwd: Path, *args: str, read_only: bool = False) -> str:
    """Run git in ``cwd`` for test setup (file protocol allowed, fixed identity; read_only: no index refresh)."""
    argv = ["git", "-c", "init.defaultBranch=main", "-c", "protocol.file.allow=always", *args]
    env = {**GIT_ENV, "GIT_OPTIONAL_LOCKS": "0"} if read_only else GIT_ENV
    result = procs.run(argv, cwd=cwd, extra_env=env, timeout=60)
    assert result.returncode == 0, f"git {args} failed: {result.stderr}"
    return result.stdout.strip()


def write(root: Path, files: dict[str, str]) -> None:
    """Write files below ``root``."""
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)


def commit(work: Path, message: str, files: dict[str, str] | None = None) -> str:
    """Write files (or touch a counter), commit everything and return the sha."""
    write(work, files or {f"changes/{message}.txt": message})
    git(work, "add", "-A")
    git(work, "commit", "-q", "-m", message)
    return git(work, "rev-parse", "HEAD")


class LocalMirror(UpstreamMirror):
    """UpstreamMirror of a local bare repository (file:// allowed for tests)."""

    FILE_PROTOCOL = "always"

    def __init__(self, cache_dir: Path, upstream: Path) -> None:
        """Mirror ``upstream`` below ``cache_dir``."""
        super().__init__(cache_dir, UPSTREAM_REPO)
        self.upstream = upstream

    @property
    def url(self) -> str:
        """file:// URL of the local upstream."""
        return f"file://{self.upstream}"


@dataclass
class Upstream:
    """The fake upstream and its interesting commits."""

    bare: Path
    work: Path
    v150: str
    v160: str
    v161: str
    main: str
    main_parent: str
    feature: str
    pr_pin: str
    pr_head: str


@pytest.fixture(autouse=True)
def _scratch_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Child processes get a HOME inside tmp_path (never the operator's ~/.cache)."""
    monkeypatch.setattr(procs, "_default_home", tmp_path / "home")


@pytest.fixture()
def upstream(tmp_path: Path) -> Upstream:
    """Build the fake upstream repository."""
    work = tmp_path / "upstream-work"
    work.mkdir()
    git(work, "init", "-q")
    commit(work, "initial", BASE_FILES)
    git(work, "tag", "-a", "v1.5.0", "-m", "release 1.5.0")
    v150 = git(work, "rev-parse", "HEAD")
    v160 = commit(work, "feature-1")
    git(work, "tag", "v1.6.0")
    v161 = commit(work, "fix-1", {"otterdog/__init__.py": "VERSION = 161\n"})
    git(work, "tag", "v1.6.1")
    commit(work, "main-1")
    main_parent = commit(work, "main-2")
    main = commit(work, "main-3", {"docs/new.md": "new\n"})
    git(work, "checkout", "-q", "-b", "feature/x", v161)
    feature = commit(work, "feature-x")
    git(work, "checkout", "-q", "-b", "pr7", main_parent)
    pr_pin = commit(work, "pr-1", {"otterdog/pr.py": "PR = 1\n"})
    pr_head = commit(work, "pr-2", {"otterdog/pr.py": "PR = 2\n"})
    git(work, "checkout", "-q", "main")
    bare = tmp_path / "upstream.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    git(bare, "update-ref", "refs/pull/7/head", pr_head)
    git(bare, "branch", "-D", "pr7")
    git(bare, "config", "uploadpack.allowFilter", "true")
    return Upstream(bare, work, v150, v160, v161, main, main_parent, feature, pr_pin, pr_head)


@pytest.fixture()
def settings(tmp_path: Path) -> HarnessSettings:
    """Harness settings rooted in tmp_path."""
    return HarnessSettings(
        project_root=tmp_path,
        cache_dir=tmp_path / "cache",
        artifacts_root=tmp_path / "artifacts",
        upstream_repo=UPSTREAM_REPO,
        targets_dir=tmp_path / "targets",
        scenarios_dir=tmp_path / "scenarios",
    )


@pytest.fixture()
def mirror(settings: HarnessSettings, upstream: Upstream) -> LocalMirror:
    """An ensured mirror of the fake upstream."""
    local = LocalMirror(settings.cache_dir, upstream.bare)
    local.ensure()
    return local


@pytest.fixture()
def use_local_mirror(monkeypatch: pytest.MonkeyPatch, upstream: Upstream) -> None:
    """resolve_sut uses a LocalMirror of the fake upstream."""
    monkeypatch.setattr(spec_mod, "upstream_mirror", lambda s: LocalMirror(s.cache_dir, upstream.bare))


# --- mirror --------------------------------------------------------------------------------------------------------
def test_ensure_clones_a_bare_partial_mirror(
    mirror: LocalMirror, upstream: Upstream, settings: HarnessSettings
) -> None:
    """Bare, blob-less (promisor) clone at cache_dir/mirror/<owner>__<name>.git with heads and tags."""
    assert mirror.path == settings.cache_dir / "mirror" / "e2e-tests__otterdog.git"
    assert mirror.git("rev-parse", "--is-bare-repository").strip() == "true"
    assert mirror.git("config", "--get", "remote.origin.partialclonefilter").strip() == "blob:none"
    assert mirror.rev_parse("refs/heads/main") == upstream.main
    assert mirror.rev_parse("refs/tags/v1.5.0") == upstream.v150  # annotated tags are peeled
    assert mirror.rev_parse("refs/heads/feature/x") == upstream.feature


def test_ensure_fetches_new_commits_prunes_and_reclones(mirror: LocalMirror, upstream: Upstream) -> None:
    """A second ensure() picks up new commits and deleted branches; a foreign origin URL triggers a re-clone."""
    new_main = commit(upstream.work, "main-4")
    git(upstream.work, "push", "-q", str(upstream.bare), "main")
    git(upstream.bare, "branch", "-D", "feature/x")
    mirror.ensure()
    assert mirror.rev_parse("refs/heads/main") == new_main
    assert not mirror.has_commit("refs/heads/feature/x")
    mirror.git("config", "remote.origin.url", "https://example.invalid/other.git")
    mirror.ensure()
    assert mirror.git("config", "--get", "remote.origin.url").strip() == mirror.url
    assert mirror.rev_parse("refs/heads/main") == new_main


def test_rev_parse_errors(mirror: LocalMirror) -> None:
    """Unknown revisions and option-like strings are refused."""
    with pytest.raises(ValueError, match="unknown revision"):
        mirror.rev_parse("refs/tags/v9.9.9")
    with pytest.raises(ValueError, match="invalid git revision"):
        mirror.rev_parse("--all")


def test_describe_follows_dunamai(mirror: LocalMirror, upstream: Upstream) -> None:
    """Nearest tag in topo order and the commit distance to it (dunamai with latest-tag)."""
    assert mirror.describe(upstream.main) == ("v1.6.1", 3)
    assert mirror.describe(upstream.v161) == ("v1.6.1", 0)
    assert mirror.describe(upstream.v150) == ("v1.5.0", 0)
    assert mirror.describe(upstream.feature) == ("v1.6.1", 1)
    assert mirror.describe(upstream.pr_pin) == ("v1.6.1", 3)


def test_describe_refuses_non_version_nearest_tag(upstream: Upstream, settings: HarnessSettings) -> None:
    """With latest-tag, a nearer non-v tag makes pdv fall back to 0.0.0: the harness refuses instead."""
    git(upstream.bare, "tag", "nightly", upstream.main)
    mirror = LocalMirror(settings.cache_dir, upstream.bare)
    mirror.ensure()
    with pytest.raises(ValueError, match="not a v\\* version tag"):
        mirror.describe(upstream.main)


def test_latest_release_tag_ignores_prereleases(upstream: Upstream, settings: HarnessSettings) -> None:
    """Highest vX.Y.Z wins numerically; rc and non-v tags are ignored."""
    git(upstream.bare, "tag", "v1.10.0rc1", upstream.main)
    git(upstream.bare, "tag", "v1.6.10", upstream.main_parent)
    git(upstream.bare, "tag", "release-9", upstream.main)
    mirror = LocalMirror(settings.cache_dir, upstream.bare)
    mirror.ensure()
    assert mirror.latest_release_tag() == "v1.6.10"


def test_ancestry_helpers(mirror: LocalMirror, upstream: Upstream) -> None:
    """is_ancestor (equal counts), merge_base, changed_files and is_trusted_commit."""
    head = mirror.fetch_pr(7)
    assert head == upstream.pr_head
    assert mirror.is_ancestor(upstream.pr_pin, head) and mirror.is_ancestor(head, head)
    assert not mirror.is_ancestor(upstream.feature, head)
    assert mirror.merge_base(upstream.pr_pin, "refs/heads/main") == upstream.main_parent
    assert mirror.changed_files(upstream.main_parent, head) == ["otterdog/pr.py"]
    assert mirror.changed_files(upstream.v161, upstream.main) == [
        "changes/main-1.txt",
        "changes/main-2.txt",
        "docs/new.md",
    ]
    assert mirror.is_trusted_commit(upstream.main_parent)
    assert mirror.is_trusted_commit(upstream.v150)
    assert not mirror.is_trusted_commit(upstream.feature)
    assert not mirror.is_trusted_commit(upstream.pr_pin)
    with pytest.raises(ValueError, match="refs/pull/8/head"):
        mirror.fetch_pr(8)


def test_remote_commit_peels_annotated_tags(mirror: LocalMirror, upstream: Upstream) -> None:
    """ls-remote cross-check values: peeled commit for annotated tags, None for missing refs."""
    assert mirror.remote_commit("refs/tags/v1.5.0") == upstream.v150
    assert mirror.remote_commit("refs/tags/v1.6.1") == upstream.v161
    assert mirror.remote_commit("refs/heads/main") == upstream.main
    assert mirror.remote_commit("refs/tags/v9.9.9") is None


def test_export_extracts_the_commit(mirror: LocalMirror, upstream: Upstream, tmp_path: Path) -> None:
    """git archive of the exact commit, modes kept, existing destination replaced."""
    dest = tmp_path / "export"
    (dest / "stale").mkdir(parents=True)
    mirror.export(upstream.v161, dest)
    assert (dest / "otterdog/__init__.py").read_text() == "VERSION = 161\n"
    assert not (dest / "stale").exists() and not (dest / "docs/new.md").exists()
    assert os.access(dest / "otterdog.sh", os.X_OK) is False  # committed without the x bit
    assert not list(tmp_path.glob(".export*"))  # no temporary leftovers


def _symlink_commit(upstream: Upstream, link: str, target: str) -> str:
    """Commit a symlink on a throwaway branch of the upstream."""
    git(upstream.work, "checkout", "-q", "-b", f"link-{len(target)}", upstream.main)
    (upstream.work / link).parent.mkdir(parents=True, exist_ok=True)
    (upstream.work / link).symlink_to(target)
    sha = commit(upstream.work, f"link-{len(target)}", {})
    git(upstream.work, "push", "-q", str(upstream.bare), "HEAD")
    git(upstream.work, "checkout", "-q", "main")
    return sha


@pytest.mark.parametrize("target", ["/etc/passwd", "../../../outside", "../.."])
def test_export_rejects_absolute_and_escaping_symlinks(
    mirror: LocalMirror, upstream: Upstream, tmp_path: Path, target: str
) -> None:
    """SEC-03 (d): an absolute or escaping symlink aborts the export."""
    sha = _symlink_commit(upstream, "docs/link", target)
    mirror.ensure()
    with pytest.raises(SafetyError, match="symlink"):
        mirror.export(sha, tmp_path / "export")
    assert not (tmp_path / "export").exists()


def test_export_keeps_internal_symlinks(mirror: LocalMirror, upstream: Upstream, tmp_path: Path) -> None:
    """Relative symlinks staying inside the tree are fine."""
    sha = _symlink_commit(upstream, "docs/readme-link", "../README.md")
    mirror.ensure()
    dest = mirror.export(sha, tmp_path / "export")
    assert (dest / "docs/readme-link").is_symlink() and (dest / "docs/readme-link").read_text() == "otterdog\n"


def _tar(tmp_path: Path, *members: tuple[tarfile.TarInfo, bytes | None]) -> Path:
    """Write a tar with the given members."""
    path = tmp_path / "crafted.tar"
    with tarfile.open(path, "w") as tar:
        for info, data in members:
            tar.addfile(info, io.BytesIO(data) if data is not None else None)
    return path


def _member(
    name: str, kind: bytes = tarfile.REGTYPE, *, linkname: str = "", data: bytes = b"x"
) -> tuple[tarfile.TarInfo, bytes | None]:
    """A tar member description."""
    info = tarfile.TarInfo(name)
    info.type = kind
    info.linkname = linkname
    info.size = len(data) if kind == tarfile.REGTYPE else 0
    return info, data if kind == tarfile.REGTYPE else None


@pytest.mark.parametrize(
    "member",
    [
        _member("/abs.txt"),
        _member("a/../../escape.txt"),
        _member("link", tarfile.SYMTYPE, linkname="/etc"),
        _member("a/link", tarfile.SYMTYPE, linkname="../../x"),
        _member("hard", tarfile.LNKTYPE, linkname="a.txt"),
        _member("dev", tarfile.CHRTYPE),
        _member("fifo", tarfile.FIFOTYPE),
    ],
)
def test_extract_tar_rejects_dangerous_members(tmp_path: Path, member: tuple[tarfile.TarInfo, bytes | None]) -> None:
    """Absolute/escaping names and links, hard links and special files are refused before extraction."""
    archive = _tar(tmp_path, _member("a.txt"), member)
    with pytest.raises(SafetyError):
        extract_tar(archive, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_extract_tar_rejects_symlink_chains_escaping(tmp_path: Path) -> None:
    """A link to a link that leaves the tree is caught by the post-extraction walk (or tarfile's data filter)."""
    archive = _tar(
        tmp_path,
        _member("a/b", tarfile.DIRTYPE),
        _member("a/b/up", tarfile.SYMTYPE, linkname=".."),
        _member("a/up2", tarfile.SYMTYPE, linkname="b/up/.."),
        _member("esc", tarfile.SYMTYPE, linkname="a/up2/.."),
    )
    out = tmp_path / "out"
    try:
        extract_tar(archive, out)
    except (SafetyError, tarfile.FilterError):
        return
    for link in ("a/b/up", "a/up2", "esc"):  # every surviving link must stay inside
        assert (out / link).resolve().is_relative_to(out.resolve())


# --- overlay filtering -----------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("path", "allowed"),
    [
        ("otterdog/cli.py", True),
        ("otterdog/webapp/static/x.js", True),
        ("tests/test_x.py", True),
        ("pyproject.toml", True),
        ("poetry.lock", True),
        ("examples/template/otterdog-defaults.libsonnet", True),
        ("docker/Dockerfile", True),
        ("Makefile", True),
        ("notes.txt", False),  # outside DIRTY_ALLOW
        ("scripts/x.sh", False),
        ("README.md.orig", False),
        (".env", False),
        (".env.local", False),
        ("otterdog/.env", False),
        ("dev/.env.dev", False),
        ("values.yaml", False),
        ("dev/values-local.yaml", False),
        ("key.pem", False),
        ("docker/certs/server.pem", False),
        ("dev/certs/server.key", False),  # *.key also matches nested paths (fnmatch-style deny)
        ("otterdog/__pycache__/cli.cpython-312.pyc", False),
        ("approot/db/x", False),
        ("orgs/o/o.jsonnet", False),
        ("otterdog.json", False),
        ("otterdog.jsonnet", False),
        ("tests/data/db.sqlite", False),
        ("triage.sh", False),
        (".venv/bin/python", False),
        (".git/config", False),
        ("otterdog/webapp/static/node_modules/x/index.js", False),
        ("github-app/private-key.pem", False),
        (".poetry/plugins/x.py", False),
        (".cache/async_http/x", False),
    ],
)
def test_path_allowed(path: str, allowed: bool) -> None:
    """DIRTY_ALLOW minus DIRTY_DENY."""
    assert path_allowed(path) is allowed
    assert path_allowed(path, DIRTY_ALLOW, DIRTY_DENY) is allowed


@dataclass
class Checkout:
    """A local clone of the upstream with uncommitted changes."""

    path: Path
    head: str


SECRET_FILES = {
    ".env": "E2E_ADMIN_TOKEN=ghp_dummy\n",
    "otterdog/.env.local": "X=1\n",
    "values-local.yaml": "token: x\n",
    "dev/values-dev.yaml": "token: x\n",
    "key.pem": "-----BEGIN PRIVATE KEY-----\n",
    "github-app/app.pem": "-----BEGIN PRIVATE KEY-----\n",
    "approot/db/x.sqlite": "db",
    "orgs/test/test.jsonnet": "{}",
    "otterdog.json": "{}",
    "triage.sh": "echo\n",
    "notes.txt": "private notes\n",
}


@pytest.fixture()
def checkout(upstream: Upstream, tmp_path: Path) -> Checkout:
    """Clone the upstream and make tracked, deleted and untracked (allowed and denied) changes."""
    path = tmp_path / "checkout"
    git(tmp_path, "clone", "-q", str(upstream.bare), str(path))
    head = git(path, "rev-parse", "HEAD")
    write(path, {"otterdog/__init__.py": "VERSION = 'dirty'\n", "tests/test_new.py": "def test(): pass\n"})
    write(path, SECRET_FILES)
    (path / "docs/old.md").unlink()
    (path / "otterdog.sh").chmod(0o755)
    git(path, "add", "tests/test_new.py")  # staged and untracked changes alike
    return Checkout(path, head)


def _repo_state(path: Path) -> tuple[str, str, bytes, int]:
    """Refs, status, index bytes and index mtime of a checkout (to prove read-only access)."""
    index = path / ".git" / "index"
    snapshot = index.read_bytes(), index.stat().st_mtime_ns
    refs = git(path, "for-each-ref", "--format=%(refname) %(objectname)", read_only=True)
    status = git(path, "status", "--porcelain", "--untracked-files=all", read_only=True)
    return refs, status, *snapshot


def test_export_local_checkout_dirty_overlay(checkout: Checkout, tmp_path: Path) -> None:
    """Allowed changes are overlaid (incl. deletions and modes), denied/unlisted files never reach the export."""
    before = _repo_state(checkout.path)
    dest = tmp_path / "export"
    sha, overlaid, dirty_hash = export_local_checkout(checkout.path, dest, dirty=True)
    assert sha == checkout.head
    assert overlaid == ["docs/old.md", "otterdog.sh", "otterdog/__init__.py", "tests/test_new.py"]
    assert dirty_hash is not None and len(dirty_hash) == 64
    assert (dest / "otterdog/__init__.py").read_text() == "VERSION = 'dirty'\n"
    assert (dest / "tests/test_new.py").exists() and not (dest / "docs/old.md").exists()
    assert os.access(dest / "otterdog.sh", os.X_OK)
    for secret in SECRET_FILES:
        assert not (dest / secret).exists(), secret
    assert _repo_state(checkout.path) == before  # read-only: no index refresh, no refs, nothing written


def test_dirty_hash_is_stable_and_content_sensitive(checkout: Checkout, tmp_path: Path) -> None:
    """Same changes -> same hash; denied files and editor noise never influence it; content edits change it."""
    _, _, first = export_local_checkout(checkout.path, tmp_path / "e1", dirty=True)
    noise = {"otterdog/.cli.py.swp": "x", "otterdog/cli.py~": "x", "docs/.DS_Store": "x", "tests/.idea/a.xml": "x"}
    write(checkout.path, {".env": "changed secret\n", "notes.txt": "changed\n", **noise})
    _, _, second = export_local_checkout(checkout.path, tmp_path / "e2", dirty=True)
    write(checkout.path, {"otterdog/__init__.py": "VERSION = 'dirtier'\n"})
    _, _, third = export_local_checkout(checkout.path, tmp_path / "e3", dirty=True)
    assert first == second != third


def test_export_local_checkout_clean_and_path_mode(checkout: Checkout, upstream: Upstream, tmp_path: Path) -> None:
    """dirty=False exports HEAD only; a dirty checkout without allowed changes has no dirty hash."""
    sha, overlaid, dirty_hash = export_local_checkout(checkout.path / "otterdog", tmp_path / "head", dirty=False)
    assert (sha, overlaid, dirty_hash) == (checkout.head, [], None)
    assert (tmp_path / "head/otterdog/__init__.py").read_text() == "VERSION = 161\n"
    assert (tmp_path / "head/docs/old.md").exists()
    clean = tmp_path / "clean"
    git(tmp_path, "clone", "-q", str(upstream.bare), str(clean))
    write(clean, {".env": "TOKEN=x\n"})
    assert export_local_checkout(clean, tmp_path / "clean-export", dirty=True)[1:] == ([], None)


def test_dirty_overlay_rejects_escaping_symlinks(checkout: Checkout, tmp_path: Path) -> None:
    """An allowed path that is a symlink leaving the checkout aborts the export."""
    (checkout.path / "otterdog/evil").symlink_to("/etc/passwd")
    with pytest.raises(SafetyError, match="symlink"):
        export_local_checkout(checkout.path, tmp_path / "export", dirty=True)


def test_export_local_checkout_requires_a_checkout(tmp_path: Path) -> None:
    """Plain directories and missing paths are refused."""
    with pytest.raises(ValueError, match="not inside a git checkout"):
        export_local_checkout(tmp_path, tmp_path / "x", dirty=True)
    with pytest.raises(ValueError, match="not a directory"):
        export_local_checkout(tmp_path / "missing", tmp_path / "x", dirty=True)


def test_fetch_from_local_leaves_the_checkout_untouched(mirror: LocalMirror, checkout: Checkout) -> None:
    """The local HEAD lands in the mirror (under refs/e2e/local/) without writing to the checkout."""
    before = _repo_state(checkout.path)
    assert mirror.fetch_from_local(checkout.path) == checkout.head
    assert mirror.rev_parse(f"refs/e2e/local/{checkout.head}") == checkout.head
    assert _repo_state(checkout.path) == before


# --- resolve_sut -----------------------------------------------------------------------------------------------------
def _marker(settings: HarnessSettings, label: str) -> dict[str, object]:
    """Sidecar export marker of a trusted label."""
    return json.loads((settings.cache_dir / "src" / f"{label}.e2e-export.json").read_text())


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_release_latest(settings: HarnessSettings, upstream: Upstream) -> None:
    """release:latest = highest vX.Y.Z; trusted export below cache_dir/src/<tag>, reused on the next resolve."""
    sut = resolve_sut("release:latest", settings)
    assert (sut.label, sut.sha, sut.version, sut.image_version) == ("v1.6.1", upstream.v161, "1.6.1", "1.6.1")
    assert sut.trusted and sut.source_dir == settings.cache_dir / "src" / "v1.6.1"
    assert (sut.source_dir / "otterdog/__init__.py").read_text() == "VERSION = 161\n"
    assert sut.repo_url == f"https://github.com/{UPSTREAM_REPO}"
    assert _marker(settings, "v1.6.1") == {"label": "v1.6.1", "sha": upstream.v161, "dirty_hash": None}
    (sut.source_dir / "reuse-probe").write_text("x")
    assert (resolve_sut("tag:v1.6.1", settings).source_dir / "reuse-probe").exists()


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_annotated_tag(settings: HarnessSettings, upstream: Upstream) -> None:
    """Annotated tags resolve to their commit."""
    sut = resolve_sut("v1.5.0", settings)
    assert (sut.label, sut.sha, sut.version, sut.spec.kind) == ("v1.5.0", upstream.v150, "1.5.0", "tag")


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_branch_main(settings: HarnessSettings, upstream: Upstream) -> None:
    """branch:main -> main-<sha7>, dev version with the e2e local label."""
    sut = resolve_sut("main", settings)
    short = upstream.main[:7]
    assert (sut.label, sut.sha, sut.trusted) == (f"main-{short}", upstream.main, True)
    assert sut.version == f"1.7.0.dev3+e2e.g{short}" and sut.image_version == sut.version


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_untrusted_branch_is_refused(settings: HarnessSettings) -> None:
    """An upstream branch that is not on main/a tag cannot be pinned: refused."""
    with pytest.raises(SafetyError, match="untrusted code must be pinned"):
        resolve_sut("branch:feature/x", settings)


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_sha_trust_at_resolve_time(settings: HarnessSettings, upstream: Upstream) -> None:
    """A sha on main is trusted (short form ok); an off-main sha is untrusted and needs the full 40-hex pin."""
    trusted = resolve_sut(f"sha:{upstream.main_parent[:9]}", settings)
    assert (trusted.label, trusted.trusted) == (f"sha-{upstream.main_parent[:7]}", True)
    assert trusted.source_dir.parent == settings.cache_dir / "src"
    with pytest.raises(SafetyError, match="pin it as"):
        resolve_sut(f"sha:{upstream.feature[:10]}", settings)
    untrusted = resolve_sut(f"sha:{upstream.feature}", settings)
    assert not untrusted.trusted and untrusted.label == f"sha-{upstream.feature[:7]}"
    assert untrusted.source_dir.parent == settings.cache_dir / "untrusted"
    assert untrusted.version == f"1.7.0.dev1+e2e.g{upstream.feature[:7]}"
    with pytest.raises(ValueError, match="pr:<N>@<sha>"):
        resolve_sut("sha:" + "f" * 40, settings)


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_pull_request(settings: HarnessSettings, upstream: Upstream) -> None:
    """pr:N@pin: untrusted, exactly the pin, base = merge-base with main, changed files of base..pin."""
    sut = resolve_sut(f"pr:7@{upstream.pr_pin}", settings)
    assert (sut.label, sut.sha, sut.trusted) == (f"pr7-{upstream.pr_pin[:7]}", upstream.pr_pin, False)
    assert (sut.pr_number, sut.pr_base_ref, sut.base_sha) == (7, "main", upstream.main_parent)
    assert sut.changed_files == ["otterdog/pr.py"]
    assert (sut.source_dir / "otterdog/pr.py").read_text() == "PR = 1\n"  # the pin, not the PR head
    assert sut.source_dir.parent == settings.cache_dir / "untrusted"
    assert not (settings.cache_dir / "src").exists() or not any((settings.cache_dir / "src").iterdir())
    assert sut.version == f"1.7.0.dev3+e2e.g{upstream.pr_pin[:7]}"
    head = resolve_sut(f"pr:7@{upstream.pr_head}", settings)
    assert head.source_dir != sut.source_dir  # every untrusted export gets a fresh private dir


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_pull_request_pin_must_be_in_the_pr(settings: HarnessSettings, upstream: Upstream) -> None:
    """A pin that is not an ancestor-or-equal of refs/pull/N/head is refused."""
    with pytest.raises(SafetyError, match="not reachable from refs/pull/7/head"):
        resolve_sut(f"pr:7@{upstream.feature}", settings)
    with pytest.raises(SafetyError, match="not reachable"):
        resolve_sut("pr:7@" + "e" * 40, settings)
    with pytest.raises(SafetyError, match="must be pinned"):
        resolve_sut(spec_mod.SutSpec("pr:7", "pr", "7"), settings)


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_pull_request_base_from_api(settings: HarnessSettings, upstream: Upstream) -> None:
    """With an http client the PR's base branch comes from GET /repos/{upstream}/pulls/{n}."""
    http = FakeGitHubHttp()
    pull = {"base": {"ref": "main", "repo": {"full_name": UPSTREAM_REPO}}, "title": "fix", "user": {"login": "dev"}}
    http.add("GET", f"/repos/{UPSTREAM_REPO}/pulls/7", json=pull)
    sut = resolve_sut(f"pr:7@{upstream.pr_pin}", settings, http=http)  # type: ignore[arg-type]
    assert sut.pr_base_ref == "main" and sut.base_sha == upstream.main_parent
    http.add("GET", f"/repos/{UPSTREAM_REPO}/pulls/8", status=404, json={"message": "Not Found"})
    with pytest.raises(ValueError, match="does not exist"):
        resolve_sut(f"pr:8@{upstream.pr_pin}", settings, http=http)  # type: ignore[arg-type]
    foreign = {"base": {"ref": "main", "repo": {"full_name": "someone/fork"}}}
    http.add("GET", f"/repos/{UPSTREAM_REPO}/pulls/9", json=foreign)
    with pytest.raises(SafetyError, match="targets someone/fork"):
        resolve_sut(f"pr:9@{upstream.pr_pin}", settings, http=http)  # type: ignore[arg-type]


@pytest.mark.usefixtures("use_local_mirror")
def test_resolve_path_and_dirty(settings: HarnessSettings, checkout: Checkout, upstream: Upstream) -> None:
    """path: = committed HEAD; dirty: = HEAD + allowed changes, labelled with the overlay hash."""
    before = _repo_state(checkout.path)
    clean = resolve_sut(f"path:{checkout.path}", settings)
    short = checkout.head[:7]
    assert (clean.label, clean.version, clean.trusted, clean.is_dirty) == (
        f"local-{short}",
        f"1.7.0.dev3+e2e.g{short}",
        True,
        False,
    )
    assert clean.base_sha == upstream.main and clean.repo_url == str(checkout.path)
    dirty = resolve_sut(f"dirty:{checkout.path}", settings)
    assert dirty.is_dirty and dirty.dirty_hash is not None
    hash8 = dirty.dirty_hash[:8]
    assert dirty.label == f"local-{short}-dirty-{hash8}"
    assert dirty.version == f"1.7.0.dev3+e2e.g{short}.dirty.{hash8}"
    assert dirty.image_version == f"1.7.0.dev3+e2e.g{short}.dirty"
    assert dirty.source_dir == settings.cache_dir / "src" / dirty.label
    assert dirty.dirty_files == ["docs/old.md", "otterdog.sh", "otterdog/__init__.py", "tests/test_new.py"]
    assert set(dirty.dirty_files) <= set(dirty.changed_files)
    assert not (dirty.source_dir / ".env").exists() and not (dirty.source_dir / "notes.txt").exists()
    assert _repo_state(checkout.path) == before
    assert not list((settings.cache_dir / "src").glob(".staging-*"))


class _LaggingMirror(LocalMirror):
    """A mirror whose ls-remote cross-check always disagrees."""

    def remote_commit(self, ref: str) -> str | None:
        """Pretend upstream moved."""
        return "0" * 40


def test_resolve_cross_check_mismatch(
    settings: HarnessSettings, upstream: Upstream, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A mirror that keeps disagreeing with git ls-remote is a SafetyError."""
    monkeypatch.setattr(spec_mod, "upstream_mirror", lambda s: _LaggingMirror(s.cache_dir, upstream.bare))
    with pytest.raises(SafetyError, match="disagrees with git ls-remote"):
        resolve_sut("release:latest", settings)


def test_resolve_refuses_old_versions(
    settings: HarnessSettings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Versions below the 1.4.0 minimum are refused before anything is exported."""
    work = tmp_path / "old"
    work.mkdir()
    git(work, "init", "-q")
    commit(work, "initial", BASE_FILES)
    git(work, "tag", "v1.3.4")
    bare = tmp_path / "old.git"
    git(tmp_path, "clone", "-q", "--bare", str(work), str(bare))
    monkeypatch.setattr(spec_mod, "upstream_mirror", lambda s: LocalMirror(s.cache_dir, bare))
    with pytest.raises(ValueError, match="older than the supported minimum"):
        resolve_sut("release:latest", settings)
    assert not (settings.cache_dir / "src" / "v1.3.4").exists()
