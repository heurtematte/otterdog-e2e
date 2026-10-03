"""Version strings of SUT builds (SPEC 10.3), compatible with poetry-dynamic-versioning's bypass variable.

otterdog's ``[tool.poetry-dynamic-versioning]`` (latest-tag, format-jinja) gives ``serialize_pep440(base, stage,
revision)`` on a tag and ``serialize_pep440(bump_version(base, 1), stage, revision, dev=distance)`` otherwise: the
MINOR part is bumped, so v1.6.1 + 19 commits is 1.7.0.dev19. The harness appends a PEP 440 local label
``+e2e.g<sha7>[.dirty.<hash8>]`` naming the exact build; it survives in the installed metadata, so ``otterdog
--version`` (importlib.metadata) prints it. The same string is passed as POETRY_DYNAMIC_VERSIONING_BYPASS.
"""

from __future__ import annotations

import re

MINIMUM_VERSION = "1.4.0"  # env credential provider + python-dotenv (PYTHON_DOTENV_DISABLED) both present

# dunamai's default version pattern (VERSION_SOURCE_PATTERN): v-prefixed tags only
TAG_VERSION_RE = re.compile(
    r"^v((?P<epoch>\d+)!)?(?P<base>\d+(\.\d+)*)"
    r"([-._]?((?P<stage>[a-zA-Z]+)[-._]?(?P<revision>\d+)?))?"
    r"(\+(?P<tagged_metadata>.+))?$"
)
PEP440_RE = re.compile(
    r"^(?:(?P<epoch>\d+)!)?(?P<release>\d+(?:\.\d+)*)"
    r"(?:(?P<pre_l>a|b|rc)(?P<pre_n>\d+))?(?:\.post(?P<post>\d+))?(?:\.dev(?P<dev>\d+))?"
    r"(?:\+(?P<local>[a-z0-9]+(?:\.[a-z0-9]+)*))?$"
)
# placeholders: no build-arg (0.0.0.dev0), plugin missing (0.0.0), shallow or tagless checkout (0.1.0.devN)
PLACEHOLDER_RE = re.compile(r"^(?:0\.0\.0|0\.0\.0\.dev0|0\.1\.0\.dev\d+)$")
_SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")
_HASH_RE = re.compile(r"^[0-9a-f]{8,64}$")
_DIRTY_LOCAL_RE = re.compile(r"(\+(?:[a-z0-9]+\.)*dirty)\.[0-9a-f]+$")
_STAGE_ALIASES = {"alpha": "a", "beta": "b", "c": "rc", "pre": "rc", "preview": "rc"}
_PRE_RANK = {"a": 0, "b": 1, "rc": 2}
_MINOR = 1  # bump_version(base, 1) in otterdog's format-jinja


def parse_tag(tag: str) -> tuple[str, str | None, int | None]:
    """(base, stage, revision) of a v* tag as dunamai matches it (ValueError for other tags)."""
    match = TAG_VERSION_RE.match(tag)
    if match is None:
        raise ValueError(f"tag {tag!r} is not a v* version tag")
    revision = match.group("revision")
    return match.group("base"), match.group("stage"), int(revision) if revision is not None else None


def bump_version(base: str, index: int = _MINOR) -> str:
    """dunamai.bump_version: increment part ``index`` and zero the following parts."""
    parts = [int(part) for part in base.split(".")]
    if index >= len(parts):
        raise ValueError(f"cannot bump part {index} of {base!r}")
    parts[index] += 1
    parts[index + 1 :] = [0] * (len(parts) - index - 1)
    return ".".join(str(part) for part in parts)


def serialize_pep440(
    base: str, stage: str | None = None, revision: int | None = None, *, dev: int | None = None
) -> str:
    """dunamai.serialize_pep440 for the arguments otterdog's format uses (base, stage, revision, dev)."""
    out = base
    if stage is not None:
        out += _STAGE_ALIASES.get(stage.lower(), stage.lower()) + str(revision if revision is not None else 0)
    if dev is not None:
        out += f".dev{dev}"
    if not PEP440_RE.match(out):
        raise ValueError(f"{out!r} is not a valid PEP 440 version")
    return out


def compute_version(tag: str, distance: int, sha: str, *, dirty_hash: str | None = None) -> str:
    """Version string: "X.Y.Z" on a tag, else "X.(Y+1).0.dev<distance>+e2e.g<sha7>" (+ ".dirty.<hash8>")."""
    if distance < 0:
        raise ValueError(f"negative distance {distance}")
    sha = sha.lower()
    if not _SHA_RE.match(sha):
        raise ValueError(f"not a commit sha: {sha!r}")
    if dirty_hash is not None and not _HASH_RE.match(dirty_hash):
        raise ValueError(f"not a dirty hash: {dirty_hash!r}")
    base, stage, revision = parse_tag(tag)
    if distance == 0:
        public = serialize_pep440(base, stage, revision)
        if dirty_hash is None:
            return public
    else:
        public = serialize_pep440(bump_version(base), stage, revision, dev=distance)
    local = f"e2e.g{sha[:7]}" + (f".dirty.{dirty_hash[:8]}" if dirty_hash else "")
    return f"{public}+{local}"


def image_version(version: str) -> str:
    """Hash-free docker build version: ".dirty.<hash>" becomes ".dirty" so dependency layers stay cached (F12)."""
    return _DIRTY_LOCAL_RE.sub(r"\1", version)


def public_version(version: str) -> str:
    """The version without its PEP 440 local part (``otterdog --version`` output always contains it)."""
    return version.split("+", 1)[0]


def version_key(version: str) -> tuple[object, ...]:
    """PEP 440 ordering key (local part ignored), as packaging.version orders public versions."""
    match = PEP440_RE.match(version)
    if match is None:
        raise ValueError(f"{version!r} is not a PEP 440 version")
    release = [int(part) for part in match.group("release").split(".")]
    while len(release) > 1 and release[-1] == 0:
        release.pop()
    pre_l, post, dev = match.group("pre_l"), match.group("post"), match.group("dev")
    if pre_l is not None:
        pre: tuple[int, int] = (_PRE_RANK[pre_l], int(match.group("pre_n")))
    elif post is None and dev is not None:
        pre = (-1, 0)  # X.Y.Z.devN sorts before X.Y.ZaN
    else:
        pre = (3, 0)  # final release after its pre-releases
    return (
        int(match.group("epoch") or 0),
        tuple(release),
        pre,
        -1 if post is None else int(post),
        (1, 0) if dev is None else (0, int(dev)),
    )


def predates(version: str | None, fixed_in: str | None) -> bool | None:
    """Whether ``version`` is older than ``fixed_in`` (PEP 440, local parts ignored): True/False, None when either
    is missing or not a PEP 440 version (``pr-792``, a commit sha, ...)."""
    if not version or not fixed_in:
        return None
    try:
        return version_key(public_version(version)) < version_key(public_version(fixed_in))
    except ValueError:
        return None


def validate_version(version: str, *, minimum: str = MINIMUM_VERSION) -> None:
    """ValueError for placeholder versions (0.0.0, 0.0.0.dev0, 0.1.0.dev*) and versions below ``minimum``."""
    if not PEP440_RE.match(version):
        raise ValueError(f"{version!r} is not a PEP 440 version")
    public = public_version(version)
    if PLACEHOLDER_RE.match(public):
        raise ValueError(
            f"placeholder version {version!r}: the version build-arg is missing, poetry-dynamic-versioning is not "
            "installed or the checkout has no git history/tags"
        )
    if version_key(public) < version_key(minimum):
        raise ValueError(f"otterdog {public} is older than the supported minimum {minimum}")
