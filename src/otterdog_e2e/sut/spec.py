"""System-under-test specifications and their resolution to a concrete source tree (SPEC 10.1, trust: SPEC 5.5).

Spec strings: ``release:latest`` · ``tag:v1.6.1`` (or ``v1.6.1``) · ``branch:main`` (or ``main``) · ``sha:<7-40 hex>``
· ``pr:<N>@<40hex>`` (pin required) · ``path:<dir>`` · ``dirty:<dir>``.

Trust (SEC-03): release, tag, branch:main, path, dirty and shas reachable from upstream main or a v* tag are trusted
and exported to ``cache_dir/src/<label>``. Pull requests and other shas are untrusted: they must be pinned to a full
40-hex sha, are exported to a fresh private directory below ``cache_dir/untrusted`` (removed at exit) and may only be
built as a docker image. Other upstream branches are accepted only when their head is trusted (an untrusted branch
cannot be pinned: use ``sha:<40hex>`` or ``pr:<N>@<sha>``).
"""

from __future__ import annotations

import atexit
import functools
import json
import logging
import re
import secrets
import shutil
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from filelock import FileLock

from otterdog_e2e.safety import SafetyError
from otterdog_e2e.sut.source import FULL_SHA_RE, LOCK_TIMEOUT, UpstreamMirror, export_local_checkout, local_toplevel
from otterdog_e2e.sut.version import compute_version, image_version, validate_version

if TYPE_CHECKING:
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.settings import HarnessSettings

SUT_KINDS = ("release", "tag", "branch", "sha", "pr", "path", "dirty")
TRUSTED_KINDS = frozenset({"release", "tag", "path", "dirty"})  # plus branch:main; sha decided at resolve time
TAG_RE = re.compile(r"^v\d+(?:\.\d+)*(?:[-._]?[A-Za-z]+[-._]?\d*)?$")
BRANCH_RE = re.compile(r"^(?![-./])(?!.*\.\.)(?!.*//)(?!.*@\{)(?!.*\.lock(?:/|$))[A-Za-z0-9._/-]+(?<![./])$")
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
PR_RE = re.compile(r"^(?P<number>[1-9]\d{0,6})(?:@(?P<pin>[0-9A-Fa-f]*))?$")
_LABEL_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
EXPORT_MARKER_SUFFIX = ".e2e-export.json"  # sidecar marker cache_dir/src/<label>.e2e-export.json
CROSS_CHECK_ATTEMPTS = 3

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SutSpec:
    """A parsed SUT spec string."""

    raw: str
    kind: str
    value: str
    pin_sha: str | None = None

    @property
    def trusted(self) -> bool:
        """Spec-level trust (SPEC 5.5): release, tag, branch:main, path, dirty; pr and sha are untrusted until resolved."""
        return self.kind in TRUSTED_KINDS or (self.kind == "branch" and self.value == "main")

    @property
    def normalized(self) -> str:
        """Canonical spec string, e.g. ``tag:v1.6.1`` or ``pr:792@<sha>``."""
        return f"{self.kind}:{self.value}" + (f"@{self.pin_sha}" if self.pin_sha else "")


def _parse_release(raw: str, value: str) -> SutSpec:
    """release:latest (the highest vX.Y.Z tag)."""
    if value.lower() != "latest":
        raise ValueError(f"{raw!r}: only release:latest is supported (use tag:vX.Y.Z for a given release)")
    return SutSpec(raw, "release", "latest")


def _parse_tag(raw: str, value: str) -> SutSpec:
    """tag:vX.Y.Z."""
    if not TAG_RE.match(value):
        raise ValueError(f"{raw!r}: expected a v* version tag such as v1.6.1")
    return SutSpec(raw, "tag", value)


def _parse_branch(raw: str, value: str) -> SutSpec:
    """branch:<name> of the upstream repository."""
    if not BRANCH_RE.match(value):
        raise ValueError(f"{raw!r}: invalid branch name {value!r}")
    return SutSpec(raw, "branch", value)


def _parse_sha(raw: str, value: str) -> SutSpec:
    """sha:<7-40 hex>."""
    sha = value.lower()
    if not SHA_RE.match(sha):
        raise ValueError(f"{raw!r}: expected 7 to 40 hex digits")
    return SutSpec(raw, "sha", sha)


def _parse_pr(raw: str, value: str) -> SutSpec:
    """pr:<N>@<40hex> (the pin is mandatory: pull requests are untrusted)."""
    match = PR_RE.match(value)
    if match is None:
        raise ValueError(f"{raw!r}: expected pr:<number>@<40-hex sha>")
    pin = (match.group("pin") or "").lower()
    if not FULL_SHA_RE.match(pin):
        raise ValueError(f"{raw!r}: pull requests are untrusted and must be pinned: pr:{match['number']}@<40-hex sha>")
    return SutSpec(raw, "pr", match.group("number"), pin)


def _parse_local(raw: str, value: str, *, kind: str) -> SutSpec:
    """path:<dir> (committed HEAD) or dirty:<dir> (HEAD + allowed working-tree changes)."""
    if not value:
        raise ValueError(f"{raw!r}: missing checkout directory")
    return SutSpec(raw, kind, value)


_PARSERS: dict[str, Callable[[str, str], SutSpec]] = {
    "release": _parse_release,
    "tag": _parse_tag,
    "branch": _parse_branch,
    "sha": _parse_sha,
    "pr": _parse_pr,
    "path": functools.partial(_parse_local, kind="path"),
    "dirty": functools.partial(_parse_local, kind="dirty"),
}


def parse_sut_spec(raw: str) -> SutSpec:
    """Parse a spec string (ValueError when malformed, e.g. a pr without a 40-hex pin)."""
    text = raw.strip()
    if not text:
        raise ValueError("empty SUT spec")
    kind, sep, value = text.partition(":")
    if not sep:
        if TAG_RE.match(text):
            return SutSpec(text, "tag", text)
        if text == "main":
            return SutSpec(text, "branch", "main")
        raise ValueError(
            f"cannot parse SUT spec {text!r}: use release:latest, tag:vX.Y.Z, branch:main, sha:<hex>, pr:<N>@<sha>, "
            "path:<dir> or dirty:<dir>"
        )
    kind = kind.strip().lower()
    if kind not in _PARSERS:
        raise ValueError(f"unknown SUT kind {kind!r} in {raw!r}; expected one of {', '.join(SUT_KINDS)}")
    return _PARSERS[kind](text, value.strip())


@dataclass
class ResolvedSut:
    """A SUT resolved to an exact commit and source tree."""

    spec: SutSpec
    label: str
    sha: str
    version: str
    image_version: str
    source_dir: Path
    repo_url: str
    trusted: bool
    is_dirty: bool = False
    dirty_hash: str | None = None
    pr_number: int | None = None
    pr_base_ref: str | None = None
    base_sha: str | None = None
    changed_files: list[str] = field(default_factory=list)
    dirty_files: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        """JSON-serializable form (run.json): spec as its raw string, paths as strings."""
        data = asdict(self)
        data["spec"] = self.spec.raw
        data["source_dir"] = str(self.source_dir)
        return data


def upstream_mirror(settings: HarnessSettings) -> UpstreamMirror:
    """The upstream mirror used by resolve_sut (monkeypatched by unit tests)."""
    return UpstreamMirror(settings.cache_dir, settings.upstream_repo)


def label_part(text: str) -> str:
    """Docker-tag and git-ref safe fragment of a tag or branch name."""
    cleaned = re.sub(r"\.{2,}", ".", _LABEL_UNSAFE_RE.sub("-", text)).strip(".-")
    return cleaned[:60] or "x"


def cleanup_source(sut: ResolvedSut) -> None:
    """Delete the private export of an untrusted SUT (trusted exports are caches and stay)."""
    if not sut.trusted:
        shutil.rmtree(sut.source_dir, ignore_errors=True)


def _untrusted_dir(settings: HarnessSettings, label: str) -> Path:
    """Fresh private export dir for untrusted code, removed at interpreter exit (never a trusted cache)."""
    root = settings.cache_dir / "untrusted"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = root / f"{label}-{secrets.token_hex(4)}"
    atexit.register(shutil.rmtree, path, ignore_errors=True)
    return path


def _read_marker(marker: Path) -> dict[str, Any] | None:
    """Content of an export marker (None when missing or unreadable)."""
    try:
        data = json.loads(marker.read_text())
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _trusted_export(
    settings: HarnessSettings, label: str, sha: str, export: Callable[[Path], Path], *, dirty_hash: str | None = None
) -> Path:
    """cache_dir/src/<label>, reused when its sidecar marker records the same sha and dirty hash."""
    root = settings.cache_dir / "src"
    root.mkdir(mode=0o700, parents=True, exist_ok=True)
    dest, marker = root / label, root / f"{label}{EXPORT_MARKER_SUFFIX}"
    expected = {"label": label, "sha": sha, "dirty_hash": dirty_hash}
    with FileLock(str(root / f"{label}.lock"), timeout=LOCK_TIMEOUT):
        if dest.is_dir() and _read_marker(marker) == expected:
            _logger.debug("reusing the export %s", dest)
            return dest
        marker.unlink(missing_ok=True)
        export(dest)
        marker.write_text(json.dumps(expected))
    return dest


def _move_into(staging: Path, dest: Path) -> Path:
    """Replace ``dest`` with the ``staging`` tree."""
    if dest.is_symlink() or dest.is_file():
        dest.unlink()
    elif dest.exists():
        shutil.rmtree(dest)
    staging.rename(dest)
    return dest


def _cross_checked(mirror: UpstreamMirror, ref: str) -> str:
    """Commit of ``ref`` in the mirror, verified against ``git ls-remote`` (re-fetching when the mirror lags)."""
    local = remote = None
    for _ in range(CROSS_CHECK_ATTEMPTS):
        local = mirror.rev_parse(ref)
        remote = mirror.remote_commit(ref)
        if remote is None:
            raise ValueError(f"{ref} does not exist in {mirror.repo}")
        if remote == local:
            return local
        _logger.info("mirror %s differs from upstream (%s != %s): fetching again", ref, local[:12], remote[:12])
        mirror.ensure()
    raise SafetyError(f"the mirror's {ref} ({local}) disagrees with git ls-remote of {mirror.repo} ({remote})")


def _upstream_sut(
    spec: SutSpec,
    settings: HarnessSettings,
    mirror: UpstreamMirror,
    *,
    label: str,
    sha: str,
    trusted: bool,
    **extra: Any,
) -> ResolvedSut:
    """Version, export and ResolvedSut of an upstream commit."""
    tag, distance = mirror.describe(sha)
    version = compute_version(tag, distance, sha)
    validate_version(version)
    if trusted:
        source_dir = _trusted_export(settings, label, sha, lambda dest: mirror.export(sha, dest))
    else:
        source_dir = mirror.export(sha, _untrusted_dir(settings, label))
    repo_url = f"https://github.com/{mirror.repo}"
    return ResolvedSut(spec, label, sha, version, image_version(version), source_dir, repo_url, trusted, **extra)


def _resolve_release(
    spec: SutSpec, settings: HarnessSettings, mirror: UpstreamMirror, http: GitHubHttp | None
) -> ResolvedSut:
    """release:latest = the highest vX.Y.Z tag of the upstream."""
    mirror.ensure()
    return _resolve_tagged(spec, settings, mirror, mirror.latest_release_tag())


def _resolve_tag(
    spec: SutSpec, settings: HarnessSettings, mirror: UpstreamMirror, http: GitHubHttp | None
) -> ResolvedSut:
    """tag:vX.Y.Z."""
    mirror.ensure()
    return _resolve_tagged(spec, settings, mirror, spec.value)


def _resolve_tagged(spec: SutSpec, settings: HarnessSettings, mirror: UpstreamMirror, tag: str) -> ResolvedSut:
    """A release tag, cross-checked with ls-remote; label = the tag."""
    sha = _cross_checked(mirror, f"refs/tags/{tag}")
    return _upstream_sut(spec, settings, mirror, label=label_part(tag), sha=sha, trusted=True)


def _resolve_branch(
    spec: SutSpec, settings: HarnessSettings, mirror: UpstreamMirror, http: GitHubHttp | None
) -> ResolvedSut:
    """branch:<name>, cross-checked with ls-remote; label <name>-<sha7>; non-main heads must be trusted."""
    mirror.ensure()
    sha = _cross_checked(mirror, f"refs/heads/{spec.value}")
    if spec.value != "main" and not mirror.is_trusted_commit(sha):
        raise SafetyError(
            f"branch {spec.value!r} ({sha[:12]}) is not reachable from main or a release tag: untrusted code must "
            f"be pinned, use sha:{sha} or pr:<N>@{sha}"
        )
    return _upstream_sut(spec, settings, mirror, label=f"{label_part(spec.value)}-{sha[:7]}", sha=sha, trusted=True)


def _resolve_sha(
    spec: SutSpec, settings: HarnessSettings, mirror: UpstreamMirror, http: GitHubHttp | None
) -> ResolvedSut:
    """sha:<hex>: trusted when reachable from main or a v* tag, else untrusted (full 40-hex pin required)."""
    mirror.ensure()
    try:
        sha = mirror.rev_parse(spec.value)
    except ValueError as ex:
        raise ValueError(f"{ex} (commits of pull requests need pr:<N>@<sha>)") from ex
    trusted = mirror.is_trusted_commit(sha)
    if not trusted and not FULL_SHA_RE.match(spec.value):
        raise SafetyError(f"commit {sha[:12]} is untrusted (not on main or a release tag): pin it as sha:{sha}")
    return _upstream_sut(spec, settings, mirror, label=f"sha-{sha[:7]}", sha=sha, trusted=trusted)


def _pull_request_base(http: GitHubHttp | None, repo: str, number: int) -> str:
    """Base branch of an upstream pull request (GET /repos/{repo}/pulls/{n}; "main" without http)."""
    if http is None:
        return "main"
    pull = http.get(f"/repos/{repo}/pulls/{number}", allow_404=True)
    if pull is None:
        raise ValueError(f"pull request #{number} does not exist in {repo}")
    base = pull.get("base") or {}
    base_repo = str((base.get("repo") or {}).get("full_name") or repo)
    if base_repo.lower() != repo.lower():
        raise SafetyError(f"pull request #{number} targets {base_repo}, not {repo}")
    _logger.info(
        "pull request #%s %r by %s (%s)",
        number,
        pull.get("title"),
        (pull.get("user") or {}).get("login"),
        pull.get("state"),
    )
    return str(base.get("ref") or "main")


def _resolve_pr(
    spec: SutSpec, settings: HarnessSettings, mirror: UpstreamMirror, http: GitHubHttp | None
) -> ResolvedSut:
    """pr:<N>@<pin>: the pin must be an ancestor-or-equal of refs/pull/N/head; always untrusted."""
    number, pin = int(spec.value), (spec.pin_sha or "").lower()
    if not FULL_SHA_RE.match(pin):
        raise SafetyError(f"pull request SUTs must be pinned to a 40-hex sha: pr:{number}@<sha>")
    base_ref = _pull_request_base(http, settings.upstream_repo, number)
    mirror.ensure()
    head = mirror.fetch_pr(number)
    if not mirror.has_commit(pin) or not mirror.is_ancestor(pin, head):
        raise SafetyError(f"pin {pin} is not reachable from refs/pull/{number}/head ({head[:12]})")
    base_sha = mirror.merge_base(pin, mirror.rev_parse(f"refs/heads/{base_ref}"))
    return _upstream_sut(
        spec,
        settings,
        mirror,
        label=f"pr{number}-{pin[:7]}",
        sha=pin,
        trusted=False,
        pr_number=number,
        pr_base_ref=base_ref,
        base_sha=base_sha,
        changed_files=mirror.changed_files(base_sha, pin),
    )


def _merge_base_or_none(mirror: UpstreamMirror, a: str, b: str) -> str | None:
    """merge-base, or None when the histories are unrelated."""
    try:
        return mirror.merge_base(a, b)
    except ValueError:
        _logger.warning("%s has no common history with %s of %s", a[:12], b, mirror.repo)
        return None


def _resolve_local(
    spec: SutSpec, settings: HarnessSettings, mirror: UpstreamMirror, http: GitHubHttp | None
) -> ResolvedSut:
    """path:/dirty:<dir>: export (read-only), fetch HEAD into the mirror for describe/merge-base, label local-<sha7>."""
    top = local_toplevel(Path(spec.value))
    staging = settings.cache_dir / "src" / f".staging-{secrets.token_hex(4)}"
    try:
        sha, overlaid, dirty_hash = export_local_checkout(top, staging, dirty=spec.kind == "dirty")
        mirror.ensure()
        if mirror.fetch_from_local(top) != sha:
            raise RuntimeError(f"HEAD of {top} moved during the export; retry")
        tag, distance = mirror.describe(sha)
        version = compute_version(tag, distance, sha, dirty_hash=dirty_hash)
        validate_version(version)
        label = f"local-{sha[:7]}" + (f"-dirty-{dirty_hash[:8]}" if dirty_hash else "")
        source_dir = _trusted_export(
            settings, label, sha, lambda dest: _move_into(staging, dest), dirty_hash=dirty_hash
        )
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    base_sha = _merge_base_or_none(mirror, sha, "refs/heads/main")
    changed = set(mirror.changed_files(base_sha, sha)) if base_sha else set()
    return ResolvedSut(
        spec=spec,
        label=label,
        sha=sha,
        version=version,
        image_version=image_version(version),
        source_dir=source_dir,
        repo_url=str(top),
        trusted=True,
        is_dirty=dirty_hash is not None,
        dirty_hash=dirty_hash,
        base_sha=base_sha,
        changed_files=sorted(changed | set(overlaid)),
        dirty_files=overlaid,
    )


_Resolver = Callable[[SutSpec, "HarnessSettings", UpstreamMirror, "GitHubHttp | None"], ResolvedSut]
_RESOLVERS: dict[str, _Resolver] = {
    "release": _resolve_release,
    "tag": _resolve_tag,
    "branch": _resolve_branch,
    "sha": _resolve_sha,
    "pr": _resolve_pr,
    "path": _resolve_local,
    "dirty": _resolve_local,
}


def resolve_sut(spec: SutSpec | str, settings: HarnessSettings, *, http: GitHubHttp | None = None) -> ResolvedSut:
    """Resolve a spec to sha/version/label and export its source (trusted: cache_dir/src/<label>, else private).

    Labels: "v1.6.1" "main-9bdeb75" "sha-9bdeb75" "pr792-d0d3b08" "local-d0d3b08" "local-d0d3b08-dirty-1a2b3c4d".
    PR: GET /repos/{upstream}/pulls/{n} (base ref, when ``http`` is given), fetch refs/pull/N/head, the pin must be an
    ancestor-or-equal of it, base_sha = merge-base(pin, origin base ref), changed files = git diff base_sha..pin.
    path/dirty: base_sha = merge-base(HEAD, upstream main) in the mirror after fetch_from_local (local repo untouched).
    release/tag/branch: sha cross-checked with ``git ls-remote https://github.com/<repo>``. Untrusted sources go to a
    fresh private dir below cache_dir/untrusted (removed at exit or by cleanup_source).
    """
    parsed = parse_sut_spec(spec) if isinstance(spec, str) else spec
    resolver = _RESOLVERS.get(parsed.kind)
    if resolver is None:
        raise ValueError(f"unknown SUT kind {parsed.kind!r}")
    sut = resolver(parsed, settings, upstream_mirror(settings), http)
    trust = "trusted" if sut.trusted else "untrusted"
    _logger.info("SUT %s -> %s (%s, otterdog %s, %s)", parsed.raw, sut.label, sut.sha[:12], sut.version, trust)
    return sut
