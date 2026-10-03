"""The otterdog base template used by a SUT: upstream, explicit URL, offline or published to the defaults repo (SPEC
10.6).

otterdog clones ``url`` (``https://github.com/<owner>/<repo>#<file>@<ref>``) into the org dir as ``vendor/<repo>/`` and
the org config imports ``vendor/<repo>/<file>``. ``ref`` is a 40-hex commit sha whenever possible (SEC-12); published
tags are only GC handles. Validation hooks (``*.py`` next to the template) are exec'd by otterdog, so a published
template tree must contain exactly the expected ``*.libsonnet`` blobs.
"""

from __future__ import annotations

import hashlib
import logging
import posixpath
import re
import shutil
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.safety import SafetyError, VerifiedOrg

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.sut.spec import ResolvedSut

UPSTREAM_TEMPLATE_FILE = "examples/template/otterdog-defaults.libsonnet"
PUBLISHED_TEMPLATE_FILE = "otterdog-defaults.libsonnet"
OFFLINE_TEMPLATE_URL = "https://github.com/e2e-offline/template#otterdog-defaults.libsonnet@offline"
TEMPLATE_SOURCE_DIR = "examples/template"
TEMPLATE_MODES = ("auto", "upstream", "publish", "url")
UPSTREAM_KINDS = frozenset({"release", "tag", "branch"})  # their shas are reachable from upstream branches/tags
BLOB_MODE = "100644"
DEFAULT_HEAD_TIMEOUT = 30.0  # seconds a just auto-initialized defaults repository may lack its first commit (F3)
HEAD_RETRY_INTERVAL = 3.0
# otterdog's parse_github_url: https://github.com/<owner>/<repo> (checked by _init_base_template)
_GITHUB_REPO_RE = re.compile(r"^https://github\.com/([A-Za-z0-9_.\-]+)/([A-Za-z0-9_.\-]+)$")
_FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REPO_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]+$")
_MAX_TAG_PEEL = 3

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemplateRef:
    """A base template reference as written to otterdog.json (defaults.jsonnet.base_template).

    ``tag`` is the published tag (``sut-<label>-<hash8>``) of a TemplatePublisher template, None otherwise: a GC
    handle only (the session records it in the org lease so the janitor keeps it); otterdog uses the pinned ``ref``.
    """

    url: str
    repo_name: str
    file: str
    ref: str
    tag: str | None = None

    @property
    def import_path(self) -> str:
        """Path imported by the org config: ``vendor/<repo_name>/<file>``."""
        return f"vendor/{self.repo_name}/{self.file}"

    @property
    def is_pinned(self) -> bool:
        """True when ``ref`` is a 40-hex commit sha (immutable, SEC-12)."""
        return bool(_FULL_SHA_RE.match(self.ref))


def upstream_template(sut: ResolvedSut, upstream_repo: str) -> TemplateRef:
    """The upstream example template at the SUT's sha (release/tag/branch SUTs only)."""
    if sut.spec.kind not in UPSTREAM_KINDS:
        raise ValueError(
            f"the upstream template needs a release/tag/branch SUT (got {sut.spec.kind}): otterdog clones the "
            "template repository, which only has upstream branches and tags; publish the template instead"
        )
    name = upstream_repo.split("/", 1)[-1]
    url = f"https://github.com/{upstream_repo}#{UPSTREAM_TEMPLATE_FILE}@{sut.sha}"
    return TemplateRef(url=url, repo_name=name, file=UPSTREAM_TEMPLATE_FILE, ref=sut.sha)


def url_template(url: str) -> TemplateRef:
    """Parse an explicit ``https://github.com/<owner>/<repo>#<file>@<ref>`` template URL."""
    parts = urlparse(url)
    if parts.netloc != "github.com":
        raise ValueError(f"only github.com is supported for template urls: {url!r}")
    repo_url = f"{parts.scheme}://{parts.netloc}{parts.path}"
    if not _GITHUB_REPO_RE.match(repo_url):
        raise ValueError(f"template url {url!r} must look like https://github.com/<owner>/<repo>#<file>@<ref>")
    match = re.match(r"([^@]+)(@(.*))?", parts.fragment)  # otterdog's parse_template_url
    if match is None or not match.group(3):
        raise ValueError(f"template url {url!r} has no <file>@<ref> fragment")
    file, ref = match.group(1), match.group(3)
    _check_relative(file)
    if not _FULL_SHA_RE.match(ref):
        _logger.warning("template ref %r is not a commit sha: the template may change under the run (SEC-12)", ref)
    return TemplateRef(url=url, repo_name=posixpath.basename(repo_url), file=file, ref=ref)


def offline_template() -> TemplateRef:
    """Placeholder template of the offline tier (the files are vendored locally, nothing is cloned)."""
    return TemplateRef(url=OFFLINE_TEMPLATE_URL, repo_name="template", file=PUBLISHED_TEMPLATE_FILE, ref="offline")


def _check_relative(file: str) -> PurePosixPath:
    """A template file path must be relative and stay inside the template repository."""
    path = PurePosixPath(file)
    if not file or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid template file path {file!r}")
    return path


def git_blob_sha(content: bytes) -> str:
    """Git object id of a blob (what ``git hash-object`` prints)."""
    return hashlib.sha1(b"blob %d\0" % len(content) + content, usedforsecurity=False).hexdigest()


def template_files(source_dir: Path) -> dict[str, bytes]:
    """Every regular *.libsonnet of source_dir/examples/template (name -> content)."""
    directory = source_dir / TEMPLATE_SOURCE_DIR
    files = {
        path.name: path.read_bytes()
        for path in sorted(directory.glob("*.libsonnet"))
        if path.is_file() and not path.is_symlink()
    }
    if PUBLISHED_TEMPLATE_FILE not in files:
        raise FileNotFoundError(f"{directory} has no {PUBLISHED_TEMPLATE_FILE}")
    return files


def content_hash8(files: dict[str, bytes]) -> str:
    """First 8 hex digits of sha256 over the sorted (path, content) pairs."""
    digest = hashlib.sha256()
    for name, content in sorted(files.items()):
        digest.update(name.encode("utf-8") + b"\0" + content + b"\0")
    return digest.hexdigest()[:8]


class TemplatePublisher:
    """Publishes a SUT's examples/template/*.libsonnet as a tagged commit of the defaults repo."""

    def __init__(self, http: GitHubHttp, verified: VerifiedOrg, repo: str) -> None:
        """Bind the publisher to the defaults repo of the verified org."""
        if not isinstance(verified, VerifiedOrg):
            raise SafetyError("TemplatePublisher requires a VerifiedOrg")
        scope = getattr(http, "write_scope", None)
        if not isinstance(scope, VerifiedOrg) or scope.login != verified.login or scope.org_id != verified.org_id:
            raise SafetyError(f"TemplatePublisher needs a GitHubHttp whose write_scope is {verified.login}")
        if not _REPO_NAME_RE.match(repo):
            raise ValueError(f"invalid repository name {repo!r}")
        self.http = http
        self.verified = verified
        self.repo = repo
        self.sleep: Callable[[float], None] = time.sleep
        self.head_timeout = DEFAULT_HEAD_TIMEOUT

    @property
    def _api(self) -> str:
        """REST prefix of the defaults repo."""
        return f"/repos/{self.verified.login}/{self.repo}"

    def publish(self, sut: ResolvedSut) -> TemplateRef:
        """Publish (or verify an existing) tag ``sut-<label>-<hash8>`` and return a sha-pinned TemplateRef (its
        ``tag`` names the published or reused tag).

        files = every *.libsonnet of sut.source_dir/examples/template (repo root, no hooks); hash8 = sha256 of the
        sorted (path, content); an existing tag must have exactly the expected root blobs (else SafetyError); otherwise
        POST git/trees (no base_tree) -> git/commits (parent: default-branch head) -> git/refs refs/tags/<tag>
        (422: accept only an identical tree); never updates the default branch.
        """
        files = template_files(sut.source_dir)
        expected = {name: git_blob_sha(content) for name, content in files.items()}
        tag = f"sut-{sut.label}-{content_hash8(files)}"
        commit = self._tag_commit(tag)
        if commit is not None:
            self._verify_commit(commit, expected, tag)
            _logger.info("template tag %s already published at %s", tag, commit[:12])
        else:
            commit = self._create(sut, tag, files, expected)
        url = f"https://github.com/{self.verified.login}/{self.repo}#{PUBLISHED_TEMPLATE_FILE}@{commit}"
        return TemplateRef(url=url, repo_name=self.repo, file=PUBLISHED_TEMPLATE_FILE, ref=commit, tag=tag)

    def _tag_commit(self, tag: str) -> str | None:
        """Commit sha the tag points to (None when the tag does not exist)."""
        ref = self.http.get(f"{self._api}/git/ref/tags/{tag}", allow_404=True)
        if ref is None:
            return None
        if ref.get("ref") != f"refs/tags/{tag}":
            raise SafetyError(f"unexpected answer for refs/tags/{tag}: {ref.get('ref')!r}")
        return self._peel(ref.get("object") or {}, tag)

    def _peel(self, obj: dict[str, Any], tag: str) -> str:
        """Follow annotated tag objects down to a commit."""
        for _ in range(_MAX_TAG_PEEL):
            if obj.get("type") == "commit":
                return str(obj["sha"])
            if obj.get("type") != "tag":
                break
            obj = (self.http.get(f"{self._api}/git/tags/{obj['sha']}") or {}).get("object") or {}
        raise SafetyError(f"tag {tag} does not point to a commit")

    def _verify_commit(self, commit: str, expected: dict[str, str], tag: str) -> None:
        """SafetyError unless the commit's root tree holds exactly the expected blobs."""
        data = self.http.get(f"{self._api}/git/commits/{commit}")
        tree = self.http.get(f"{self._api}/git/trees/{data['tree']['sha']}")
        if tree.get("truncated"):
            raise SafetyError(f"tree of {tag} is truncated")
        self._verify_entries(tree.get("tree") or [], expected, tag)

    @staticmethod
    def _verify_entries(entries: list[dict[str, Any]], expected: dict[str, str], tag: str) -> None:
        """Entries must be exactly the expected 100644 blobs (no extra file such as a *.py hook)."""
        actual = {str(e.get("path")): (e.get("type"), e.get("mode"), e.get("sha")) for e in entries}
        wanted = {name: ("blob", BLOB_MODE, sha) for name, sha in expected.items()}
        if actual != wanted:
            extra = sorted(set(actual) - set(wanted))
            changed = sorted(name for name in set(actual) & set(wanted) if actual[name] != wanted[name])
            missing = sorted(set(wanted) - set(actual))
            raise SafetyError(f"template {tag} differs: extra {extra}, changed {changed}, missing {missing}")

    def _default_head(self) -> str:
        """Head commit of the defaults repo's default branch (the parent of published commits)."""
        repo = self.http.get(self._api)
        if repo.get("private") is not False:
            raise RuntimeError(
                f"{self.verified.login}/{self.repo} must be public: otterdog clones templates anonymously"
            )
        branch = repo.get("default_branch") or "main"
        waited = 0.0
        while True:  # a repository bootstrap just created (auto_init) answers 404/409 for a few seconds (F3)
            try:
                ref = self.http.get(f"{self._api}/git/ref/heads/{branch}", allow_404=True)
            except GitHubError as ex:
                if ex.status != 409:
                    raise
                ref = None
            if ref is not None:
                return str(ref["object"]["sha"])
            if waited >= self.head_timeout:
                raise RuntimeError(
                    f"{self.verified.login}/{self.repo} has no commit on {branch} after {waited:g} s (create it with "
                    "auto_init)"
                )
            self.sleep(HEAD_RETRY_INTERVAL)
            waited += HEAD_RETRY_INTERVAL

    def _create(self, sut: ResolvedSut, tag: str, files: dict[str, bytes], expected: dict[str, str]) -> str:
        """POST tree (no base_tree) -> commit (parent: default head) -> lightweight tag; returns the commit sha."""
        head = self._default_head()
        entries = [
            {"path": name, "mode": BLOB_MODE, "type": "blob", "content": content.decode("utf-8")}
            for name, content in sorted(files.items())
        ]
        tree = self.http.post(f"{self._api}/git/trees", json={"tree": entries})
        self._verify_entries(tree.get("tree") or [], expected, tag)
        message = f"otterdog-e2e template {tag}\n\nexamples/template of {sut.label} ({sut.sha})\n"
        commit = self.http.post(
            f"{self._api}/git/commits", json={"message": message, "tree": tree["sha"], "parents": [head]}
        )
        response = self.http.request(
            "POST", f"{self._api}/git/refs", json={"ref": f"refs/tags/{tag}", "sha": commit["sha"]}, allow=(422,)
        )
        if response.status_code != 422:
            _logger.info("published template tag %s at %s", tag, str(commit["sha"])[:12])
            return str(commit["sha"])
        existing = self._tag_commit(tag)  # concurrent publisher: accept only an identical tree
        if existing is None:
            raise RuntimeError(f"creating refs/tags/{tag} failed with 422 but the tag does not exist")
        self._verify_commit(existing, expected, tag)
        return existing


# hook scripts otterdog executes from the template directory (vendor/<repo>/, the repository root of the template):
# validation (models/__init__.py execute_custom_validation_if_present) and apply (operations/apply.py)
HOOK_FILES = ("validate-org-settings.py", "validate-team.py", "pre-add-object-hook.py", "post-add-objects-hook.py")


def vendor_template(
    template_src_dir: Path, org_dir: Path, ref: TemplateRef, *, hooks: Mapping[str, str] | None = None
) -> None:
    """Copy *.libsonnet of ``template_src_dir`` to org_dir/vendor/<repo_name>/<dirname(file)>/ (offline vendoring).

    ``hooks`` maps HOOK_FILES names to the Python source otterdog executes (offline tests of the template hooks): they
    are written to org_dir/vendor/<repo_name>/, where otterdog looks for them (its template_dir, also when the
    template file lies in a subdirectory). Other names are refused.
    """
    unknown = sorted(set(hooks or {}) - set(HOOK_FILES))
    if unknown:
        raise ValueError(f"unknown template hook file(s) {unknown}, expected some of {HOOK_FILES}")
    file = _check_relative(ref.file)
    if not _REPO_NAME_RE.match(ref.repo_name) or ref.repo_name in (".", ".."):
        raise ValueError(f"invalid template repository name {ref.repo_name!r}")
    sources = sorted(p for p in template_src_dir.glob("*.libsonnet") if p.is_file() and not p.is_symlink())
    if file.name not in {p.name for p in sources}:
        raise FileNotFoundError(f"{template_src_dir} has no {file.name}")
    vendor_root = org_dir / "vendor" / ref.repo_name
    if vendor_root.is_symlink() or vendor_root.is_file():
        vendor_root.unlink()
    elif vendor_root.exists():
        shutil.rmtree(vendor_root)
    target = vendor_root.joinpath(*file.parent.parts)
    target.mkdir(parents=True)
    for source in sources:
        shutil.copyfile(source, target / source.name)
    for name, source_text in (hooks or {}).items():
        (vendor_root / name).write_text(source_text, encoding="utf-8")


def needs_publisher(mode: str, sut: ResolvedSut) -> bool:
    """True when resolve_template publishes to the defaults repo: mode publish, or auto for a non-upstream SUT."""
    if mode not in TEMPLATE_MODES:
        raise ValueError(f"unknown template mode {mode!r}; expected one of {', '.join(TEMPLATE_MODES)}")
    return mode == "publish" or (mode == "auto" and sut.spec.kind not in UPSTREAM_KINDS)


def resolve_template(
    mode: str,
    sut: ResolvedSut,
    *,
    upstream_repo: str,
    publisher: TemplatePublisher | None,
    url: str | None,
) -> TemplateRef:
    """Pick the template by mode: auto (upstream for release/tag/branch, publish otherwise), upstream, publish, url."""
    if mode == "url":
        if not url:
            raise ValueError("template mode 'url' needs a template url (E2E_TEMPLATE_URL)")
        return url_template(url)
    if not needs_publisher(mode, sut):
        return upstream_template(sut, upstream_repo)
    if publisher is None:
        raise ValueError(f"template mode {mode!r} for a {sut.spec.kind} SUT needs a publisher (a verified live target)")
    return publisher.publish(sut)
