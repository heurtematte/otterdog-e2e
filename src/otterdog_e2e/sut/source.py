"""Upstream git mirror and source exports (SPEC 10.2).

Every git command runs through procs.run with ``-c core.hooksPath=/dev/null -c core.fsmonitor=false`` and
``protocol.file.allow=never`` (``user`` only for fetch_from_local). Exports go through ``git archive`` into a tar file
extracted with ``tarfile`` ``filter="data"`` (required); absolute or escaping symlinks abort the export, also in
dirty overlays. Local checkouts are only read: git runs with GIT_OPTIONAL_LOCKS=0 (no index refresh) and nothing is
fetched into them.
"""

from __future__ import annotations

import fnmatch
import functools
import hashlib
import logging
import os
import posixpath
import re
import secrets
import shutil
import stat
import tarfile
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath

from filelock import FileLock

from otterdog_e2e import procs
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.sut.version import TAG_VERSION_RE

DIRTY_ALLOW = (
    "otterdog/**",
    "tests/**",
    "docs/**",
    "examples/**",
    "docker/**",
    "dev/**",
    "pyproject.toml",
    "poetry.lock",
    "README.md",
    "CHANGELOG.md",
    "mkdocs.yml",
    "otterdog.sh",
    "Makefile",
)
DIRTY_DENY = (
    "values*.yaml",
    "**/values*.yaml",
    "*.pem",
    "**/*.pem",
    "*.key",
    ".env*",
    "**/.env*",
    "**/__pycache__/**",
    "approot/**",
    "orgs/**",
    "otterdog.json",
    "otterdog.jsonnet",
    "**/*.sqlite",
    "triage.sh",
    ".venv/**",
    ".git/**",
    "**/node_modules/**",
    "github-app/**",
    ".poetry/**",
    ".cache/**",
)

# editor/OS noise never overlaid: git runs without the operator's global excludes (GIT_CONFIG_GLOBAL=/dev/null), and
# such files would change the dirty hash (and the label) on every editing session
DIRTY_NOISE = ("**/*.swp", "**/*.swo", "**/*~", "**/.DS_Store", "**/.idea/**", "**/.vscode/**", "**/*.pyc", "**/*.orig")

_logger = logging.getLogger(__name__)

GIT_HARDENING = ("-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")
_HARDENING_VALUES = frozenset(
    {*GIT_HARDENING[1::2], *(f"protocol.file.allow={value}" for value in ("never", "user", "always"))}
)
LOCAL_GIT_ENV = {"GIT_OPTIONAL_LOCKS": "0"}  # git status must not refresh (write) the index of a local checkout
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
RELEASE_TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
REPO_RE = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
LOCK_TIMEOUT = 900.0
FETCH_TIMEOUT = 900.0
_FOR_EACH_REF_FORMAT = (
    "%(refname)@{%(objectname)@{%(creatordate:iso-strict)@{%(*committerdate:iso-strict)@{%(taggerdate:iso-strict)"
)


class GitCommandError(procs.CalledProcessError):
    """A git command failed; str() carries the redacted tail of its stderr."""

    def __str__(self) -> str:
        """Command (without the hardening options), exit code and stderr tail (redacted)."""
        args = [str(arg) for arg in self.cmd] if isinstance(self.cmd, list | tuple) else [str(self.cmd)]
        shown = [arg for arg in args if arg != "-c" and arg not in _HARDENING_VALUES]
        tail = "\n".join(str(self.stderr or "").strip().splitlines()[-5:])
        return REDACTOR(f"{' '.join(shown)[:400]} failed with exit {self.returncode}: {tail}")


def _git_argv(args: Sequence[str], *, file_protocol: str, git_dir: Path | None = None) -> list[str]:
    """Hardened git argv (no hooks, no fsmonitor, restricted file protocol)."""
    argv = ["git", *GIT_HARDENING, "-c", f"protocol.file.allow={file_protocol}"]
    if git_dir is not None:
        argv += ["--git-dir", str(git_dir)]
    return [*argv, *args]


def run_git(
    args: Sequence[str],
    *,
    file_protocol: str = "never",
    git_dir: Path | None = None,
    cwd: Path | None = None,
    extra_env: Mapping[str, str] | None = None,
    timeout: float = 600,
    check: bool = True,
) -> procs.CompletedProcess[str]:
    """Run one hardened git command through procs.run (GitCommandError on failure when check)."""
    argv = _git_argv(args, file_protocol=file_protocol, git_dir=git_dir)
    result = procs.run(argv, cwd=cwd, extra_env=extra_env, timeout=timeout)
    if check and result.returncode != 0:
        raise GitCommandError(result.returncode, argv, result.stdout, result.stderr)
    return result


def _check_rev(rev: str) -> str:
    """Refuse revisions that git could parse as options."""
    if not rev or rev.startswith("-") or any(ch in rev for ch in "\0\n"):
        raise ValueError(f"invalid git revision {rev!r}")
    return rev


@dataclass(frozen=True)
class _TagInfo:
    """One tag merged into a commit, as dunamai lists it (for-each-ref)."""

    ref: str
    best_date: float

    @classmethod
    def parse(cls, line: str) -> _TagInfo | None:
        """Parse a for-each-ref line ``ref@{object@{creatordate@{*committerdate@{taggerdate``."""
        parts = line.split("@{")
        if len(parts) != 5:
            return None
        dates = [parts[4], parts[3], parts[2]]  # dunamai: tagger date, else commit date, else creator date
        best = next((value for value in dates if value), "")
        return cls(parts[0], datetime.fromisoformat(best).timestamp() if best else 0.0)


def _tag_offsets(log_output: str) -> dict[str, int]:
    """dunamai's topo-order lookup: tag ref -> line offset in ``git log --simplify-by-decoration``."""
    lines = [line for line in log_output.strip().splitlines() if " (" not in line or "tag: " in line]
    offsets: dict[str, int] = {}
    for offset, line in enumerate(lines):
        _, _, decorations = line.partition("(")
        for item in decorations[:-1].split(", "):
            item = item.strip()
            if item.startswith("tag: "):
                name = item.split()[-1]
                offsets[name if name.startswith("refs/tags/") else f"refs/tags/{name}"] = offset
    return offsets


class UpstreamMirror:
    """Blob-less bare mirror of the upstream otterdog repository under cache_dir/mirror."""

    FILE_PROTOCOL = "never"  # protocol.file.allow for every command except fetch_from_local

    def __init__(self, cache_dir: Path, repo: str = "eclipse-csi/otterdog") -> None:
        """Bind the mirror to ``owner/name`` below ``cache_dir``."""
        if not REPO_RE.match(repo):
            raise ValueError(f"invalid upstream repository {repo!r} (expected owner/name)")
        self.cache_dir = cache_dir
        self.repo = repo

    @property
    def path(self) -> Path:
        """Bare repository path: cache_dir/mirror/<owner>__<name>.git."""
        owner, name = self.repo.split("/", 1)
        return self.cache_dir / "mirror" / f"{owner}__{name}.git"

    @property
    def url(self) -> str:
        """Clone URL https://github.com/<repo>.git."""
        return f"https://github.com/{self.repo}.git"

    def _run(
        self, *args: str, timeout: float = 600, check: bool = True, file_protocol: str | None = None
    ) -> procs.CompletedProcess[str]:
        """Run git on the mirror."""
        protocol = file_protocol or self.FILE_PROTOCOL
        return run_git(args, file_protocol=protocol, git_dir=self.path, timeout=timeout, check=check)

    def git(self, *args: str, timeout: float = 600) -> str:
        """Run git on the mirror (hardened -c options, --git-dir <path>) and return stdout (CalledProcessError on failure)."""
        return self._run(*args, timeout=timeout).stdout

    def _lock(self) -> FileLock:
        """Inter-process lock serializing clone and fetches of this mirror."""
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        return FileLock(str(self.path.with_suffix(".lock")), timeout=LOCK_TIMEOUT)

    def _is_valid(self) -> bool:
        """True when the mirror exists, is bare and points at the expected origin URL."""
        if not self.path.is_dir():
            return False
        bare = self._run("rev-parse", "--is-bare-repository", check=False)
        origin = self._run("config", "--get", "remote.origin.url", check=False)
        return bare.returncode == 0 and bare.stdout.strip() == "true" and origin.stdout.strip() == self.url

    def _clone(self) -> None:
        """Fresh blob-less bare clone, moved into place atomically."""
        tmp = self.path.with_name(f".{self.path.name}.tmp-{secrets.token_hex(4)}")
        try:
            argv = ["clone", "--bare", "--filter=blob:none", "--quiet", self.url, str(tmp)]
            run_git(argv, file_protocol=self.FILE_PROTOCOL, timeout=FETCH_TIMEOUT)
            shutil.rmtree(self.path, ignore_errors=True)
            tmp.rename(self.path)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def ensure(self) -> Path:
        """Clone (bare, --filter=blob:none) when missing or the origin URL differs; fetch heads and tags (prune)."""
        with self._lock():
            if not self._is_valid():
                _logger.info("cloning %s into %s", self.url, self.path)
                self._clone()
            refspecs = ("+refs/heads/*:refs/heads/*", "+refs/tags/*:refs/tags/*")
            self._run("fetch", "--prune", "--quiet", "origin", *refspecs, timeout=FETCH_TIMEOUT)
        return self.path

    def fetch_pr(self, number: int) -> str:
        """Fetch refs/pull/<number>/head (stored as refs/e2e/pull/<number>); returns its sha."""
        if number <= 0:
            raise ValueError(f"invalid pull request number {number}")
        ref = f"refs/e2e/pull/{number}"
        with self._lock():
            result = self._run(
                "fetch", "--no-tags", "--quiet", "origin", f"+refs/pull/{number}/head:{ref}", check=False
            )
            if result.returncode != 0:
                raise ValueError(f"cannot fetch refs/pull/{number}/head from {self.repo}: {result.stderr.strip()}")
            return self.rev_parse(ref)

    def fetch_from_local(self, local_repo: Path, rev: str = "HEAD") -> str:
        """Fetch ``rev`` of a local checkout into the mirror (local repo untouched); returns its sha."""
        top = local_toplevel(local_repo)
        sha = local_commit(top, rev)
        with self._lock():
            ref = f"refs/e2e/local/{sha}"
            self._run("fetch", "--no-tags", "--quiet", str(top), f"+{sha}:{ref}", file_protocol="user")
            fetched = self.rev_parse(ref)
        if fetched != sha:
            raise RuntimeError(f"fetched {fetched} from {top} instead of {sha}")
        return sha

    def rev_parse(self, rev: str) -> str:
        """Full sha of ``rev`` (peeled to its commit; ValueError when unknown)."""
        result = self._run("rev-parse", "--verify", "--quiet", f"{_check_rev(rev)}^{{commit}}", check=False)
        sha = result.stdout.strip()
        if result.returncode != 0 or not FULL_SHA_RE.match(sha):
            raise ValueError(f"unknown revision {rev!r} in the {self.repo} mirror")
        return sha

    def has_commit(self, rev: str) -> bool:
        """True when ``rev`` names a commit present in the mirror."""
        try:
            self.rev_parse(rev)
        except ValueError:
            return False
        return True

    def merge_base(self, a: str, b: str) -> str:
        """git merge-base a b (ValueError when the histories are unrelated)."""
        result = self._run("merge-base", _check_rev(a), _check_rev(b), check=False)
        if result.returncode == 1 and not result.stdout.strip():
            raise ValueError(f"{a} and {b} have no common ancestor")
        if result.returncode != 0:
            raise GitCommandError(result.returncode, ["git", "merge-base", a, b], result.stdout, result.stderr)
        return result.stdout.split()[0]

    def is_ancestor(self, a: str, b: str) -> bool:
        """git merge-base --is-ancestor a b (a == b counts)."""
        result = self._run("merge-base", "--is-ancestor", _check_rev(a), _check_rev(b), check=False)
        if result.returncode in (0, 1):
            return result.returncode == 0
        raise GitCommandError(result.returncode, ["git", "merge-base", "--is-ancestor", a, b], "", result.stderr)

    def changed_files(self, base: str, head: str) -> list[str]:
        """Paths changed between base and head (git diff --name-only; renames as delete + add, no blob fetch)."""
        out = self.git("diff", "--name-only", "-z", "--no-renames", _check_rev(base), _check_rev(head), "--")
        return sorted({path for path in out.split("\0") if path})

    def is_trusted_commit(self, sha: str) -> bool:
        """True when ``sha`` is reachable from upstream main or from a v* tag (SPEC 5.5)."""
        out = self.git(
            "for-each-ref", "--contains", _check_rev(sha), "--format=%(refname)", "refs/heads/main", "refs/tags/"
        )
        refs = out.split()
        return "refs/heads/main" in refs or any(TAG_VERSION_RE.match(ref.removeprefix("refs/tags/")) for ref in refs)

    def remote_commit(self, ref: str) -> str | None:
        """Commit sha of ``ref`` according to ``git ls-remote`` of the upstream (peeled for annotated tags)."""
        out = self.git("ls-remote", self.url, ref, f"{ref}^{{}}", timeout=120)
        found: dict[str, str] = {}
        for line in out.splitlines():
            sha, _, name = line.partition("\t")
            found[name.strip()] = sha.strip()
        return found.get(f"{ref}^{{}}") or found.get(ref)

    def describe(self, sha: str) -> tuple[str, int]:
        """Nearest v* tag reachable from sha and the distance to it."""
        sha = _check_rev(sha)
        merged = self.git("for-each-ref", "refs/tags/", "--merged", sha, f"--format={_FOR_EACH_REF_FORMAT}")
        tags = [info for info in map(_TagInfo.parse, merged.strip().splitlines()) if info is not None]
        if not tags:
            raise ValueError(f"no tag is reachable from {sha}: cannot compute an otterdog version")
        log = self.git(
            "log", "--simplify-by-decoration", "--topo-order", "--decorate=full", sha, "--format=%H%d",
            "--decorate-refs=refs/tags/",
        )  # fmt: skip
        offsets = _tag_offsets(log)
        # dunamai (latest-tag = true): nearest tag in topo order, newest first among tags of one commit
        nearest = min(tags, key=lambda info: (offsets.get(info.ref, 2**31), -info.best_date))
        tag = nearest.ref.removeprefix("refs/tags/")
        if not TAG_VERSION_RE.match(tag):
            raise ValueError(f"the nearest tag {tag!r} of {sha} is not a v* version tag")
        distance = int(self.git("rev-list", "--count", f"refs/tags/{tag}..{sha}").strip())
        return tag, distance

    def latest_release_tag(self) -> str:
        """Highest vX.Y.Z tag (no pre-releases)."""
        names = self.git("for-each-ref", "--format=%(refname:strip=2)", "refs/tags/").split()
        releases = [name for name in names if RELEASE_TAG_RE.match(name)]
        if not releases:
            raise ValueError(f"no vX.Y.Z release tag in the {self.repo} mirror")
        return max(releases, key=lambda name: tuple(int(part) for part in RELEASE_TAG_RE.findall(name)[0]))

    def export(self, sha: str, dest: Path) -> Path:
        """git archive <sha> extracted with tarfile filter="data" into dest; rejects absolute/escaping symlinks."""
        commit = self.rev_parse(sha)
        dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        archive = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tar")
        try:
            self._run("archive", "--format=tar", f"--output={archive}", commit, timeout=FETCH_TIMEOUT)
            extract_tar(archive, dest)
        finally:
            archive.unlink(missing_ok=True)
        _logger.info("exported %s@%s to %s", self.repo, commit[:7], dest)
        return dest


# --- safe tar extraction ------------------------------------------------------------------------------------------
def _escapes(base: PurePosixPath, target: str) -> bool:
    """True when ``target`` (relative to directory ``base`` inside a tree) is absolute or leaves the tree."""
    if target.startswith("/") or PurePosixPath(target).is_absolute():
        return True
    joined = posixpath.normpath(posixpath.join(str(base), target))
    return joined == ".." or joined.startswith(("../", "/"))


def _check_member(member: tarfile.TarInfo) -> None:
    """Refuse absolute/escaping names, links leaving the tree and special files."""
    name = PurePosixPath(member.name)
    if name.is_absolute() or ".." in name.parts:
        raise SafetyError(f"archive member {member.name!r} escapes the export directory")
    if member.issym():
        if _escapes(name.parent, member.linkname):
            raise SafetyError(f"symlink {member.name!r} -> {member.linkname!r} is absolute or escapes the export")
    elif not (member.isfile() or member.isdir()):
        raise SafetyError(f"archive member {member.name!r} is not a regular file, directory or symlink")


def check_tree_symlinks(root: Path) -> None:
    """SafetyError when any symlink below ``root`` is absolute or resolves outside ``root``."""
    real_root = root.resolve()
    for current, dirs, files in os.walk(root):
        for name in [*dirs, *files]:
            path = Path(current) / name
            if not path.is_symlink():
                continue
            target = os.readlink(path)
            try:
                resolved = (path.parent / target).resolve()
            except (OSError, RuntimeError) as ex:
                raise SafetyError(f"symlink {path.relative_to(root)} -> {target} cannot be resolved: {ex}") from ex
            if os.path.isabs(target) or not resolved.is_relative_to(real_root):
                raise SafetyError(f"symlink {path.relative_to(root)} -> {target} is absolute or escapes the export")


def extract_tar(archive: Path, dest: Path) -> Path:
    """Extract a git archive tar into ``dest`` (replaced) with filter="data" after checking every member."""
    if not hasattr(tarfile, "data_filter"):
        raise SafetyError("this Python's tarfile has no filter='data' (Python >= 3.11.4 is required)")
    tmp = dest.with_name(f".{dest.name}.extract-{secrets.token_hex(4)}")
    try:
        tmp.mkdir(mode=0o700, parents=True)
        with tarfile.open(archive, "r:") as tar:
            members = tar.getmembers()
            for member in members:
                _check_member(member)
            tar.extractall(tmp, members=members, filter="data")
        check_tree_symlinks(tmp)
        _remove(dest)
        tmp.rename(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return dest


def _remove(path: Path) -> None:
    """Delete a file, symlink or directory tree if present (symlinks are never followed)."""
    if path.is_symlink() or path.is_file():
        path.unlink()
    elif path.is_dir():
        shutil.rmtree(path)


# --- local checkouts ----------------------------------------------------------------------------------------------
def local_git(top: Path, *args: str, timeout: float = 300) -> str:
    """Hardened, read-only git command in a local checkout (GIT_OPTIONAL_LOCKS=0); returns stdout."""
    return run_git(["-C", str(top), *args], extra_env=LOCAL_GIT_ENV, timeout=timeout).stdout


def local_commit(top: Path, rev: str = "HEAD") -> str:
    """Full sha of ``rev`` in a local checkout (ValueError when it names no commit)."""
    argv = ["-C", str(top), "rev-parse", "--verify", "--quiet", f"{_check_rev(rev)}^{{commit}}"]
    result = run_git(argv, extra_env=LOCAL_GIT_ENV, check=False)
    sha = result.stdout.strip()
    if result.returncode != 0 or not FULL_SHA_RE.match(sha):
        raise ValueError(f"{rev!r} is not a commit of {top}")
    return sha


def local_toplevel(path: Path) -> Path:
    """Top-level directory of the non-bare git checkout containing ``path`` (ValueError otherwise)."""
    path = Path(path).expanduser().resolve()
    if not path.is_dir():
        raise ValueError(f"{path} is not a directory")
    result = run_git(["-C", str(path), "rev-parse", "--show-toplevel"], extra_env=LOCAL_GIT_ENV, check=False)
    if result.returncode != 0 or not result.stdout.strip():
        raise ValueError(f"{path} is not inside a git checkout: {result.stderr.strip()}")
    return Path(result.stdout.strip())


@functools.lru_cache(maxsize=256)
def _glob_regex(pattern: str) -> re.Pattern[str]:
    """Segment-aware glob: ``**/`` = any directories (also none), ``**`` = anything, ``*``/``?`` stay in a segment."""
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:[^/]*/)*")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        else:
            out.append({"*": "[^/]*", "?": "[^/]"}.get(pattern[i], re.escape(pattern[i])))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def path_allowed(path: str, allow: Iterable[str] = DIRTY_ALLOW, deny: Iterable[str] = DIRTY_DENY) -> bool:
    """True when ``path`` matches an allow pattern and no deny pattern (deny also matches fnmatch-style, across /)."""
    if not any(_glob_regex(pattern).match(path) for pattern in allow):
        return False
    return not any(_glob_regex(pattern).match(path) or fnmatch.fnmatchcase(path, pattern) for pattern in deny)


def _dirty_paths(top: Path) -> list[str]:
    """Paths whose working-tree state differs from HEAD: tracked changes (incl. deletions) and untracked files."""
    tracked = local_git(top, "diff", "--name-only", "-z", "--no-renames", "--ignore-submodules=all", "HEAD", "--")
    untracked = local_git(top, "ls-files", "--others", "--exclude-standard", "-z", "--")
    paths = {path for path in (tracked + "\0" + untracked).split("\0") if path and not path.endswith("/")}
    return sorted(paths)


def _overlay_one(top: Path, dest: Path, rel: str) -> str | None:
    """Apply one working-tree path to the export; returns its hash entry (None when skipped)."""
    if PurePosixPath(rel).is_absolute() or ".." in PurePosixPath(rel).parts:
        raise SafetyError(f"refusing overlay path {rel!r}")
    src, dst = top / rel, dest / rel
    if not os.path.lexists(src):
        if dst.is_symlink() or dst.is_file():
            dst.unlink()
        return "D"
    info = os.lstat(src)
    if stat.S_ISLNK(info.st_mode):
        target = os.readlink(src)
        if _escapes(PurePosixPath(rel).parent, target):
            raise SafetyError(f"dirty overlay symlink {rel} -> {target} is absolute or escapes the checkout")
        _replace(dst)
        dst.symlink_to(target)
        return f"L {target}"
    if not stat.S_ISREG(info.st_mode):
        _logger.info("dirty overlay: skipping %s (not a regular file)", rel)
        return None
    content = src.read_bytes()
    mode = 0o755 if info.st_mode & stat.S_IXUSR else 0o644
    _replace(dst)
    dst.write_bytes(content)
    dst.chmod(mode)
    return f"F {mode:o} {hashlib.sha256(content).hexdigest()}"


def _replace(dst: Path) -> None:
    """Make room for a new file or symlink at ``dst`` (parents created, old entry removed)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    _remove(dst)


def _overlay(top: Path, dest: Path) -> tuple[list[str], str | None]:
    """Copy allowed working-tree changes over the export; returns (overlaid paths, dirty hash)."""
    entries: dict[str, str] = {}
    denied: list[str] = []
    for rel in _dirty_paths(top):
        if not path_allowed(rel, DIRTY_ALLOW, (*DIRTY_DENY, *DIRTY_NOISE)):
            denied.append(rel)
            continue
        entry = _overlay_one(top, dest, rel)
        if entry is not None:
            entries[rel] = entry
    if denied:
        _logger.info("dirty overlay: %d changed path(s) outside DIRTY_ALLOW or in DIRTY_DENY ignored", len(denied))
        _logger.debug("dirty overlay ignored: %s", denied)
    check_tree_symlinks(dest)
    if not entries:
        return [], None
    digest = hashlib.sha256("\0".join(f"{path}\0{entry}" for path, entry in sorted(entries.items())).encode())
    return sorted(entries), digest.hexdigest()


def export_local_checkout(path: Path, dest: Path, *, dirty: bool) -> tuple[str, list[str], str | None]:
    """Export HEAD of a local checkout (plus, if dirty, its DIRTY_ALLOW-minus-DIRTY_DENY working-tree changes).

    Read-only on ``path``; returns (HEAD sha, overlaid files, dirty hash).
    """
    top = local_toplevel(path)
    sha = local_commit(top)
    dest.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive = dest.with_name(f".{dest.name}.{secrets.token_hex(4)}.tar")
    try:
        local_git(top, "archive", "--format=tar", f"--output={archive}", sha, timeout=FETCH_TIMEOUT)
        extract_tar(archive, dest)
    finally:
        archive.unlink(missing_ok=True)
    if not dirty:
        pending = local_git(top, "status", "--porcelain", "--untracked-files=no", "--ignore-submodules=all")
        if pending.strip():
            _logger.info("path: SUT %s ignores uncommitted changes (use dirty: to include them)", top)
        return sha, [], None
    overlaid, dirty_hash = _overlay(top, dest)
    _logger.info("exported %s@%s with %d overlaid path(s) to %s", top, sha[:7], len(overlaid), dest)
    return sha, overlaid, dirty_hash
