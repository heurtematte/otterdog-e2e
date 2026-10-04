"""Harness settings, target files and identities (SPEC 6).

``HarnessSettings`` locates the project, caches and artifacts; ``Target`` is a parsed ``targets/<name>.yaml`` (with
``${VAR}`` / ``${VAR:-default}`` expansion); identities are dedicated machine accounts whose logins are declared in the
target (non-secret) and whose tokens come from environment variables named by ``token_env``.

Call order of a live session: ``harness_settings()`` -> ``load_env_files(target, root)`` (fills os.environ without
overriding it) -> ``load_target()`` -> ``resolve_identities()`` / ``resolve_app_credentials()`` /
``resolve_web_credentials()``.

Web-UI credentials (docs/web-ui-testing.md) belong to the admin machine account only: its password and TOTP seed come
from the variables named by ``identities.admin.password_env`` / ``totp_seed_env`` (defaults E2E_ADMIN_PASSWORD,
E2E_ADMIN_TOTP_SEED), the username from ``username_env`` (default E2E_ADMIN_USERNAME) or the declared admin login.
They are resolved separately from the identity tokens (``WebCredentials``), so no code path hands them to otterdog
unless it explicitly asks for the web mode.
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import tomllib
import urllib.parse
from collections.abc import Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml

from otterdog_e2e import naming
from otterdog_e2e.capabilities import DERIVED_CAPS, PLANS, Cap
from otterdog_e2e.redact import REDACTOR, SECRET_KEY_RE
from otterdog_e2e.safety import SafetyError, check_org_allowed

if TYPE_CHECKING:
    from otterdog_e2e.naming import RunContext

_logger = logging.getLogger(__name__)

PROJECT_NAME = "otterdog-e2e"
DEFAULT_CACHE_DIR = "~/.cache/otterdog-e2e"
DEFAULT_UPSTREAM_REPO = "eclipse-csi/otterdog"
USER_CONFIG_SUBDIR = ".config/otterdog-e2e"  # below HOME: <target>.env files and app-manifest outputs
DEFAULT_MARKER = "[otterdog-e2e]"
MIN_MARKER_LENGTH = 5
IDENTITY_ROLES = ("admin", "oracle", "author", "approver", "outsider", "config_reader", "readonly")
# identities that may share one token: the oracle falls back to the admin, both read-only roles may be one token
SHAREABLE_TOKEN_GROUPS = (frozenset({"admin", "oracle"}), frozenset({"config_reader", "readonly"}))
TRANSPORTS = ("relay", "external", "none")
TEMPLATE_MODES = ("auto", "upstream", "publish", "url")
# org settings the renderer always takes from the LIVE org (marker, plan, billing): never overridable (F1)
RESERVED_BASELINE_SETTINGS = ("plan", "description", "billing_email")
# team names must equal their slugs: the webapp compares GraphQL team names with slugs
TEAM_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
TARGET_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
LOGIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
REPO_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,100}$")
APP_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
UPSTREAM_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._-]{1,100}$")
_ORG_IDS_RE = re.compile(r"^\d+$")
# web-UI credentials of the admin machine account: key of identities.admin -> default variable name
WEB_CREDENTIAL_KEYS = ("username_env", "password_env", "totp_seed_env")
DEFAULT_WEB_ENV: Mapping[str, str] = {
    "username_env": "E2E_ADMIN_USERNAME",
    "password_env": "E2E_ADMIN_PASSWORD",
    "totp_seed_env": "E2E_ADMIN_TOTP_SEED",
}
WEB_IDENTITY = "admin"  # the only identity with web credentials (org settings pages need an owner)
# required name suffixes of the secret-holding web variables (SECRET_KEY_RE: redacted, never inherited by children)
_WEB_SECRET_SUFFIXES: Mapping[str, str] = {"password_env": "_PASSWORD", "totp_seed_env": "_TOTP_SEED"}
MIN_TOTP_SEED_LENGTH = 16  # base32 characters (80 bits): GitHub's authenticator setup keys are 16 or 32 characters
_BASE32_RE = re.compile(r"^[A-Z2-7]+=*$")
_BOOLEAN_TEXT = {
    "true": True,
    "yes": True,
    "on": True,
    "1": True,
    "false": False,
    "no": False,
    "off": False,
    "0": False,
}
TOP_LEVEL_WEB_UI_KEYS = ("probe_app_slug",)
# identities.<role>.token_type: the declared kind of the token (auto = whatever GET /rate_limit reveals); doctor and
# verify_target fail when the declared kind is not the detected one (docs/setup-free-org.md, fine-grained tokens)
TOKEN_TYPES = ("auto", "classic", "fine-grained")
# roles that cannot use a fine-grained PAT: the outsider comments on the test org's public repos without being a
# member, and a fine-grained token can only write to the resources of its resource owner (docs/security.md)
CLASSIC_ONLY_ROLES = frozenset({"outsider"})

_ENV_REF_RE = re.compile(r"\$\{(?:(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::-(?P<default>[^}]*))?\}|(?P<bad>))")
_ENV_LINE_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=(?P<value>.*)$")
_DOUBLE_QUOTE_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\", "$": "$"}


@dataclass(frozen=True)
class HarnessSettings:
    """Locations of the project, caches, artifacts, targets and scenarios."""

    project_root: Path
    cache_dir: Path
    artifacts_root: Path
    upstream_repo: str
    targets_dir: Path
    scenarios_dir: Path

    def scratch(self, run_id: str) -> Path:
        """Private per-run scratch dir ``cache_dir/run/<run_id>`` (created with mode 0700, never under artifacts)."""
        if not run_id or run_id in (".", "..") or any(char in run_id for char in "/\\\0"):
            raise ValueError(f"invalid run id for a scratch directory: {run_id!r}")
        path = self.cache_dir / "run" / run_id
        for directory in (self.cache_dir, self.cache_dir / "run", path):
            directory.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(directory, 0o700)
        return path


def _home(environ: Mapping[str, str]) -> Path:
    """HOME of ``environ`` (falls back to the process user's home)."""
    return Path(environ["HOME"]) if environ.get("HOME") else Path.home()


def _user_path(value: str, environ: Mapping[str, str]) -> Path:
    """Absolute path of ``value``; a leading ``~`` expands to HOME of ``environ`` (not of the process)."""
    if value == "~" or value.startswith("~/"):
        return _home(environ) / value[2:]
    return Path(value).expanduser().absolute()


def user_config_dir(environ: Mapping[str, str] | None = None) -> Path:
    """Per-user harness config dir ``~/.config/otterdog-e2e`` (<target>.env files, app-manifest outputs)."""
    return _home(os.environ if environ is None else environ) / USER_CONFIG_SUBDIR


def _is_project_root(directory: Path) -> bool:
    """True when ``directory/pyproject.toml`` declares ``[project].name == "otterdog-e2e"``."""
    pyproject = directory / "pyproject.toml"
    if not pyproject.is_file():
        return False
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    return isinstance(project, dict) and project.get("name") == PROJECT_NAME


def _search_upwards(start: Path) -> Path | None:
    """First directory from ``start`` upwards that is the project root, or None."""
    current = start if start.is_dir() else start.parent
    for directory in (current, *current.parents):
        if _is_project_root(directory):
            return directory
    return None


def find_project_root(start: Path | None = None) -> Path:
    """Nearest directory (from ``start`` or cwd upwards) whose pyproject.toml has [project].name == "otterdog-e2e".

    Without ``start``, the package location is searched too (editable installs run from another cwd).
    """
    origins = [Path(start)] if start is not None else [Path.cwd(), Path(__file__).resolve().parent]
    for origin in origins:
        found = _search_upwards(origin.absolute())
        if found is not None:
            return found
    raise FileNotFoundError(
        f"no {PROJECT_NAME} project root (pyproject.toml with name {PROJECT_NAME!r}) found above "
        f"{', '.join(str(origin) for origin in origins)}; set E2E_PROJECT_ROOT"
    )


def _make_private_dir(path: Path) -> None:
    """Create ``path`` (and parents) and restrict it to the owner (0700)."""
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def _check_scratch_outside_artifacts(cache_dir: Path, artifacts_root: Path) -> None:
    """SafetyError when the cache (scratch with credentials) would be uploaded with the artifacts (SEC-01)."""
    cache, artifacts = cache_dir.resolve(), artifacts_root.resolve()
    if cache == artifacts or cache.is_relative_to(artifacts):
        raise SafetyError(
            f"E2E_CACHE_DIR ({cache_dir}) must not be inside E2E_ARTIFACTS ({artifacts_root}): the scratch dirs below "
            "it hold credentials and must never be uploaded"
        )


def harness_settings(environ: Mapping[str, str] | None = None) -> HarnessSettings:
    """Build settings from E2E_PROJECT_ROOT, E2E_CACHE_DIR, E2E_ARTIFACTS, E2E_OTTERDOG_REPO (defaults in SPEC 6.1)."""
    env = os.environ if environ is None else environ
    if env.get("E2E_PROJECT_ROOT"):
        root = _user_path(env["E2E_PROJECT_ROOT"], env)
        if not root.is_dir():
            raise FileNotFoundError(f"E2E_PROJECT_ROOT {root} is not a directory")
    else:
        root = find_project_root()
    cache_dir = _user_path(env.get("E2E_CACHE_DIR") or DEFAULT_CACHE_DIR, env)
    artifacts_root = _user_path(env["E2E_ARTIFACTS"], env) if env.get("E2E_ARTIFACTS") else root / "artifacts"
    upstream_repo = env.get("E2E_OTTERDOG_REPO") or DEFAULT_UPSTREAM_REPO
    if not UPSTREAM_REPO_RE.match(upstream_repo):
        raise ValueError(f"E2E_OTTERDOG_REPO must be <owner>/<repo>, got {upstream_repo!r}")
    _check_scratch_outside_artifacts(cache_dir, artifacts_root)
    _make_private_dir(cache_dir)
    return HarnessSettings(
        project_root=root,
        cache_dir=cache_dir,
        artifacts_root=artifacts_root,
        upstream_repo=upstream_repo,
        targets_dir=root / "targets",
        scenarios_dir=root / "scenarios",
    )


# --- env files ------------------------------------------------------------------------------------------------------
def target_env_name(target: str) -> str:
    """Name used for a target's env files: the target name, or the stem of a target file path."""
    looks_like_path = target.endswith((".yaml", ".yml")) or "/" in target or os.sep in target
    name = Path(target).stem if looks_like_path else target
    if not TARGET_NAME_RE.match(name):
        raise ValueError(f"invalid target name {name!r} (expected {TARGET_NAME_RE.pattern})")
    return name


def env_file_candidates(target: str | None, project_root: Path, environ: Mapping[str, str]) -> list[Path]:
    """Env files in precedence order: ~/.config/otterdog-e2e/<target>.env, <root>/.env.e2e.<target>, <root>/.env.e2e."""
    candidates = []
    if target:
        name = target_env_name(target)
        candidates += [_home(environ) / USER_CONFIG_SUBDIR / f"{name}.env", project_root / f".env.e2e.{name}"]
    candidates.append(project_root / ".env.e2e")
    return candidates


def _closing_quote(text: str, quote: str) -> int | None:
    """Index of the closing ``quote`` in ``text`` (backslash escapes honoured inside double quotes), or None."""
    escaped = False
    for index, char in enumerate(text):
        if escaped:
            escaped = False
        elif char == "\\" and quote == '"':
            escaped = True
        elif char == quote:
            return index
    return None


def _unescape_double_quoted(text: str) -> str:
    """Process ``\\n \\r \\t \\" \\\\ \\$`` in a double-quoted value (other backslashes are kept)."""
    return re.sub(r"\\(.)", lambda m: _DOUBLE_QUOTE_ESCAPES.get(m[1], m[0]), text, flags=re.DOTALL)


def _unquoted_value(raw: str) -> str:
    """Value of an unquoted assignment: an inline comment starts at whitespace + ``#``."""
    match = re.search(r"\s#", raw)
    return (raw[: match.start()] if match else raw).strip()


def parse_env_text(text: str, *, source: str = "<env>") -> dict[str, str]:
    """Parse ``KEY=VALUE`` lines: '#' comments, optional ``export``, optional (multi-line) quotes, NO interpolation.

    Double-quoted values process backslash escapes, single-quoted values are literal; malformed lines are skipped
    with a warning that never shows the value; within one file the last assignment wins.
    """
    values: dict[str, str] = {}
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        line, number = lines[index], index + 1
        index += 1
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        match = _ENV_LINE_RE.match(line)
        if not match:
            _logger.warning("%s:%d: ignoring a line that is not KEY=VALUE", source, number)
            continue
        raw = match["value"].lstrip()
        if raw[:1] not in ("'", '"'):
            values[match["key"]] = _unquoted_value(raw)
            continue
        quote, body = raw[0], raw[1:]
        while _closing_quote(body, quote) is None and index < len(lines):
            body += "\n" + lines[index]
            index += 1
        end = _closing_quote(body, quote)
        if end is None:
            _logger.warning("%s:%d: ignoring %s: unterminated quoted value", source, number, match["key"])
            continue
        if body[end + 1 :].strip() and not body[end + 1 :].strip().startswith("#"):
            _logger.warning("%s:%d: ignoring text after the closing quote of %s", source, number, match["key"])
        value = body[:end]
        values[match["key"]] = _unescape_double_quoted(value) if quote == '"' else value
    return values


def _warn_if_shared(path: Path) -> None:
    """Warn when a secrets file is readable by group or others."""
    try:
        mode = path.stat().st_mode
    except OSError:
        return
    if mode & 0o077:
        _logger.warning("%s is accessible by group/others (mode %o): chmod 600 it", path, mode & 0o777)


def load_env_files(
    target: str | None, project_root: Path, environ: MutableMapping[str, str] | None = None
) -> list[Path]:
    """Load ~/.config/otterdog-e2e/<target>.env, <root>/.env.e2e.<target>, <root>/.env.e2e without overriding.

    KEY=VALUE lines, '#' comments, optional quotes, no interpolation; only SECRET_KEY_RE keys are registered with
    REDACTOR (values from the files and those already in the environment, e.g. CI secrets). Returns the files read.
    """
    env = os.environ if environ is None else environ
    loaded = []
    for path in env_file_candidates(target, project_root, env):
        if not path.is_file():
            continue
        _warn_if_shared(path)
        values = parse_env_text(path.read_text(encoding="utf-8"), source=str(path))
        for key, value in values.items():
            if SECRET_KEY_RE.search(key):
                REDACTOR.add(value)
            if key not in env:
                env[key] = value
        loaded.append(path)
        _logger.debug("loaded %d variable(s) from %s", len(values), path)
    REDACTOR.add(*(value for key, value in env.items() if SECRET_KEY_RE.search(key)))
    return loaded


def expand_env(value: str, environ: Mapping[str, str]) -> str:
    """Expand ``${VAR}`` and ``${VAR:-default}`` references in ``value``.

    Unset ``${VAR}`` expands to ""; ``:-`` also applies to empty values; results are never re-expanded; any other
    ``${`` form raises ValueError.
    """

    def replace(match: re.Match[str]) -> str:
        """Value of one reference."""
        if match["bad"] is not None:
            raise ValueError(f"malformed variable reference at {value[match.start() : match.start() + 20]!r}")
        current = environ.get(match["name"], "")
        if match["default"] is not None and not current:
            return match["default"]
        return current

    return _ENV_REF_RE.sub(replace, value)


# --- targets --------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class IdentitySpec:
    """Declared identity of a target: public login and the NAME of the env var holding its token.

    The admin identity may also name the variables of its web-UI login (``username_env``, ``password_env``,
    ``totp_seed_env``; None = the DEFAULT_WEB_ENV names). ``token_type`` is the declared kind of its token (TOKEN_TYPES).
    """

    name: str
    login: str | None
    token_env: str | None
    username_env: str | None = None
    password_env: str | None = None
    totp_seed_env: str | None = None
    token_type: str = "auto"  # noqa: S105 - a token kind (TOKEN_TYPES), not a secret

    def web_env(self, key: str) -> str:
        """Variable holding one web credential (``username_env``, ``password_env`` or ``totp_seed_env``)."""
        if key not in WEB_CREDENTIAL_KEYS:
            raise ValueError(f"unknown web credential {key!r}, expected one of {WEB_CREDENTIAL_KEYS}")
        return str(getattr(self, key) or DEFAULT_WEB_ENV[key])


@dataclass(frozen=True)
class Identity:
    """Resolved identity with its token (never shown in repr) and the declared token kind (TOKEN_TYPES)."""

    name: str
    login: str | None
    token: str = field(repr=False)
    token_type: str = "auto"  # noqa: S105 - a token kind (TOKEN_TYPES), not a secret


@dataclass(frozen=True)
class WebCredentials:
    """Web-UI login of the admin machine account (otterdog's username, password and TOTP seed; secrets never in repr).

    ``login`` is the declared admin login, ``username`` what otterdog types on github.com/login (the login unless the
    username variable says otherwise, e.g. the account's email), ``totp_seed`` the normalized base32 seed.
    """

    identity: str
    login: str
    username: str
    password: str = field(repr=False)
    totp_seed: str = field(repr=False)


@dataclass(frozen=True)
class AppSpec:
    """Names of the env vars holding the GitHub App credentials."""

    id_env: str
    private_key_env: str | None
    private_key_file_env: str | None
    webhook_secret_env: str
    slug: str | None


@dataclass(frozen=True)
class AppCredentials:
    """Resolved GitHub App credentials (key and secret never shown in repr)."""

    app_id: str
    private_key_pem: str = field(repr=False)
    webhook_secret: str = field(repr=False)
    slug: str | None


@dataclass(frozen=True)
class WebappSpec:
    """Webapp transport and settings of a target."""

    transport: str
    external_url: str | None
    external_init_url: str | None
    validation_context: str
    sync_context: str
    workers: int
    port: int


@dataclass(frozen=True)
class Target:
    """A parsed targets/<name>.yaml (SPEC 6.2)."""

    name: str
    description: str
    org: str
    org_id: int
    allowed_org_ids: tuple[int, ...]
    expected_plan: str
    marker: str
    capability_overrides: Mapping[str, tuple[str, ...]]
    configs_repo: str
    org_config_repo: str
    defaults_repo: str
    template_mode: str
    template_url: str | None
    identities: Mapping[str, IdentitySpec]
    app: AppSpec | None
    admin_team: str
    approval_team: str
    contributors_team: str
    webapp: WebappSpec
    fixture_repos: tuple[str, ...]
    extra_protected_repos: tuple[str, ...]
    baseline_settings: Mapping[str, Any]
    source_path: Path
    # github.saml_sso: SAML SSO is enforced on the org (otterdog's web client cannot log in: web-UI tier disabled)
    saml_sso: bool = False
    # web_ui.probe_app_slug: a harmless GitHub App the web-UI tier installs and uninstalls (install-app/uninstall-app)
    web_probe_app_slug: str | None = None

    def config_repo_for(self, run_ctx: RunContext) -> str:
        """Org config repo of a run: ``auto`` means the per-session repo ``e2e-<run>-config`` (F10)."""
        return run_ctx.name("config") if self.org_config_repo == "auto" else self.org_config_repo

    def protected_repos(self, run_ctx: RunContext) -> tuple[str, ...]:
        """Repos that must never be deleted: run config repo, configs, defaults, fixtures and extra protected repos."""
        names = (
            self.config_repo_for(run_ctx),
            self.configs_repo,
            self.defaults_repo,
            *self.fixture_repos,
            *self.extra_protected_repos,
        )
        return tuple(dict.fromkeys(names))


class TargetError(ValueError):
    """Invalid or incomplete target file / environment."""


_TOP_KEYS = (
    "name",
    "description",
    "github",
    "config",
    "identities",
    "app",
    "teams",
    "webapp",
    "fixtures",
    "baseline",
    "web_ui",
)
_GITHUB_KEYS = ("org", "org_id", "allowed_org_ids", "expected_plan", "marker", "capabilities", "saml_sso")
_CAPABILITY_KEYS = ("add", "remove")
_CONFIG_KEYS = ("configs_repo", "org_config_repo", "defaults_repo", "template")
_TEMPLATE_KEYS = ("mode", "url")
_IDENTITY_KEYS = ("login", "token_env", "token_type", *WEB_CREDENTIAL_KEYS)
_APP_KEYS = ("id_env", "private_key_env", "private_key_file_env", "webhook_secret_env", "slug")
_TEAM_KEYS = ("admin", "approval", "contributors")
_WEBAPP_KEYS = (
    "transport",
    "external_url",
    "external_init_url",
    "validation_context",
    "sync_context",
    "workers",
    "port",
)
_FIXTURE_KEYS = ("repos", "extra_protected_repos")
_BASELINE_KEYS = ("settings",)


class _Section:
    """Strict, typed view of one mapping of a target file: unknown keys and wrong types raise TargetError."""

    def __init__(self, data: Any, where: str, allowed: Iterable[str]) -> None:
        """Wrap ``data`` (None = empty) found at ``where``; keys outside ``allowed`` are errors."""
        allowed = tuple(allowed)
        if data is None:
            data = {}
        if not isinstance(data, Mapping):
            raise TargetError(f"{where or 'target'}: expected a mapping, got {type(data).__name__}")
        unknown = sorted(str(key) for key in data if key not in allowed)
        if unknown:
            raise TargetError(
                f"{where or 'target'}: unknown key(s) {', '.join(unknown)} (allowed: {', '.join(allowed)})"
            )
        self.data: Mapping[Any, Any] = data
        self.where = where

    def path(self, key: str) -> str:
        """Dotted location of ``key`` (for error messages)."""
        return f"{self.where}.{key}" if self.where else key

    def section(self, key: str, allowed: Iterable[str]) -> _Section:
        """Nested section ``key``."""
        return _Section(self.data.get(key), self.path(key), allowed)

    def text(self, key: str, default: str | None = None, *, required: bool = False) -> str | None:
        """Stripped string value; empty or missing -> ``default`` (TargetError when required and no default)."""
        value = self.data.get(key)
        if isinstance(value, bool) or not isinstance(value, str | int | type(None)):
            raise TargetError(f"{self.path(key)}: expected a string, got {type(value).__name__}")
        text = "" if value is None else str(value).strip()
        if text:
            return text
        if required and default is None:
            raise TargetError(f"{self.path(key)} is required")
        return default

    def required_text(self, key: str, default: str | None = None) -> str:
        """Like text() but never None."""
        value = self.text(key, default, required=True)
        assert value is not None
        return value

    def integer(self, key: str, default: int | None = None, *, minimum: int = 1, maximum: int | None = None) -> int:
        """Integer value (digits strings accepted); missing -> ``default`` (TargetError when None) and range checks."""
        value = self.data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            if default is None:
                raise TargetError(f"{self.path(key)} is required (an integer)")
            return default
        if isinstance(value, bool) or not isinstance(value, int | str):
            raise TargetError(f"{self.path(key)}: expected an integer, got {type(value).__name__}")
        if isinstance(value, str) and not _ORG_IDS_RE.match(value.strip()):
            raise TargetError(f"{self.path(key)}: {value!r} is not a non-negative integer")
        number = int(value)
        if number < minimum or (maximum is not None and number > maximum):
            bounds = f">= {minimum}" if maximum is None else f"in [{minimum}, {maximum}]"
            raise TargetError(f"{self.path(key)}: {number} must be {bounds}")
        return number

    def boolean(self, key: str, default: bool = False) -> bool:
        """Boolean value: a YAML boolean or true/false/yes/no/on/off/1/0 text (after ${...} expansion)."""
        value = self.data.get(key)
        if value is None or (isinstance(value, str) and not value.strip()):
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str) and value.strip().lower() in _BOOLEAN_TEXT:
            return _BOOLEAN_TEXT[value.strip().lower()]
        raise TargetError(f"{self.path(key)}: expected a boolean (true/false), got {value!r}")

    def names(self, key: str) -> tuple[str, ...]:
        """List of names: a YAML list or a comma-separated string (empty items dropped)."""
        value = self.data.get(key)
        if value is None:
            return ()
        if isinstance(value, str):
            items = value.split(",")
        elif isinstance(value, list) and all(isinstance(i, str | int) and not isinstance(i, bool) for i in value):
            items = [str(item) for item in value]
        else:
            raise TargetError(f"{self.path(key)}: expected a list of names or a comma-separated string")
        return tuple(item.strip() for item in items if item.strip())


def _checked(value: str, pattern: re.Pattern[str], where: str, what: str) -> str:
    """``value`` if it matches ``pattern``, else TargetError."""
    if not pattern.match(value):
        raise TargetError(f"{where}: {value!r} is not a valid {what} ({pattern.pattern})")
    return value


def _repo_name(value: str, where: str) -> str:
    """A valid GitHub repository name."""
    if value in (".", ".."):
        raise TargetError(f"{where}: {value!r} is not a valid repository name")
    return _checked(value, REPO_NAME_RE, where, "repository name")


def _secret_env_name(value: str, where: str) -> str:
    """Name of an env var holding a secret: must match SECRET_KEY_RE so it is redacted and never reaches children."""
    _checked(value, ENV_NAME_RE, where, "environment variable name")
    if not SECRET_KEY_RE.search(value):
        raise TargetError(
            f"{where}: {value!r} must end with one of _TOKEN/_SECRET/_PASSWORD/_TOTP_SEED/_PRIVATE_KEY so the value is "
            "redacted and removed from child environments"
        )
    return value


def _url(value: str | None, where: str) -> str | None:
    """An http(s) URL (or None)."""
    if value is not None and not re.match(r"^https?://[^/\s]+", value):
        raise TargetError(f"{where}: {value!r} is not an http(s) URL")
    return value


def _org_ids(section: _Section, org_id: int) -> tuple[int, ...]:
    """github.allowed_org_ids (comma list, int or list) with the pinned org id always first."""
    value = section.data.get("allowed_org_ids")
    raw = [value] if isinstance(value, int) and not isinstance(value, bool) else section.names("allowed_org_ids")
    ids = []
    for item in raw:
        text = str(item).strip()
        if not _ORG_IDS_RE.match(text) or int(text) <= 0:
            raise TargetError(f"{section.path('allowed_org_ids')}: {text!r} is not a positive organization id")
        ids.append(int(text))
    return tuple(dict.fromkeys((org_id, *ids)))


def _capability_names(names: Iterable[str], where: str) -> tuple[str, ...]:
    """Validated capability names (lower snake case values of Cap)."""
    valid = {cap.value for cap in Cap}
    result = []
    for name in names:
        if name.lower() not in valid:
            raise TargetError(f"{where}: unknown capability {name!r} (known: {', '.join(sorted(valid))})")
        result.append(name.lower())
    return tuple(dict.fromkeys(result))


@dataclass(frozen=True)
class _GithubPart:
    """The github section of a target."""

    org: str
    org_id: int
    allowed_org_ids: tuple[int, ...]
    expected_plan: str
    marker: str
    capability_overrides: dict[str, tuple[str, ...]]
    saml_sso: bool = False


def _github_part(top: _Section) -> _GithubPart:
    """Parse and validate the github section (org pin, plan, marker, capability overrides, SAML SSO flag)."""
    github = top.section("github", _GITHUB_KEYS)
    org = _checked(github.required_text("org"), LOGIN_RE, github.path("org"), "organization login")
    check_org_allowed(org)
    org_id = github.integer("org_id")
    plan = github.required_text("expected_plan").lower()
    if plan not in PLANS:
        raise TargetError(f"{github.path('expected_plan')}: {plan!r} is not one of {', '.join(PLANS)}")
    marker = github.required_text("marker", DEFAULT_MARKER)
    if len(marker) < MIN_MARKER_LENGTH:
        raise TargetError(f"{github.path('marker')}: {marker!r} is too short (at least {MIN_MARKER_LENGTH} characters)")
    caps = github.section("capabilities", _CAPABILITY_KEYS)
    overrides = {key: _capability_names(caps.names(key), caps.path(key)) for key in _CAPABILITY_KEYS}
    derived = sorted(set(overrides["add"]) & {cap.value for cap in DERIVED_CAPS})
    if derived:
        raise TargetError(
            f"{caps.path('add')}: {', '.join(derived)} cannot be added: it is derived from the web credentials, "
            "--e2e-allow-web-ui, the SUT trust and github.saml_sso (docs/web-ui-testing.md)"
        )
    saml_sso = github.boolean("saml_sso", False)
    return _GithubPart(org, org_id, _org_ids(github, org_id), plan, marker, overrides, saml_sso)


@dataclass(frozen=True)
class _ConfigPart:
    """The config section of a target."""

    configs_repo: str
    org_config_repo: str
    defaults_repo: str
    template_mode: str
    template_url: str | None


def _config_part(top: _Section) -> _ConfigPart:
    """Parse and validate the config section (repos and template mode)."""
    config = top.section("config", _CONFIG_KEYS)
    configs_repo = _repo_name(config.required_text("configs_repo", "otterdog-e2e-configs"), config.path("configs_repo"))
    org_config_repo = config.required_text("org_config_repo", "auto")
    if org_config_repo != "auto":
        _repo_name(org_config_repo, config.path("org_config_repo"))
    defaults_repo = _repo_name(
        config.required_text("defaults_repo", "otterdog-e2e-defaults"), config.path("defaults_repo")
    )
    template = config.section("template", _TEMPLATE_KEYS)
    mode = template.required_text("mode", "auto")
    if mode not in TEMPLATE_MODES:
        raise TargetError(f"{template.path('mode')}: {mode!r} is not one of {', '.join(TEMPLATE_MODES)}")
    url = template.text("url")
    if url is not None and not url.startswith("https://"):
        raise TargetError(f"{template.path('url')}: {url!r} must be an https:// base template URL")
    if mode == "url" and url is None:
        raise TargetError(f"{template.path('url')} is required when the template mode is 'url'")
    return _ConfigPart(configs_repo, org_config_repo, defaults_repo, mode, url)


def _web_env_names(entry: _Section, name: str) -> dict[str, str | None]:
    """The web credential variable names of one identity entry (only the admin may declare them)."""
    names = {key: entry.text(key) for key in WEB_CREDENTIAL_KEYS}
    declared = sorted(key for key, value in names.items() if value is not None)
    if declared and name != WEB_IDENTITY:
        raise TargetError(
            f"{entry.where}: {', '.join(declared)}: web-UI credentials are only supported for the admin identity "
            "(the org settings pages need an organization owner)"
        )
    for key, value in names.items():
        if value is None:
            continue
        _checked(value, ENV_NAME_RE, entry.path(key), "environment variable name")
        suffix = _WEB_SECRET_SUFFIXES.get(key)
        if suffix is not None and not value.endswith(suffix):
            raise TargetError(
                f"{entry.path(key)}: {value!r} must end with {suffix} so the value is redacted and removed from child "
                "environments"
            )
    return names


def _token_type(entry: _Section, name: str) -> str:
    """identities.<name>.token_type (default auto); a fine-grained outsider is refused (CLASSIC_ONLY_ROLES)."""
    value = entry.required_text("token_type", "auto")
    if value not in TOKEN_TYPES:
        raise TargetError(f"{entry.path('token_type')}: {value!r} must be one of {', '.join(TOKEN_TYPES)}")
    if value == "fine-grained" and name in CLASSIC_ONLY_ROLES:
        raise TargetError(
            f"{entry.path('token_type')}: the {name} identity needs a classic PAT: it comments on the test org's "
            "public repositories without being a member, and a fine-grained token can only write to the resources of "
            "its resource owner (docs/security.md)"
        )
    return value


def _identity_specs(top: _Section) -> dict[str, IdentitySpec]:
    """Parse the identities section; admin needs a login and a token env var (and may name its web credentials)."""
    section = top.section("identities", IDENTITY_ROLES)
    specs = {}
    for name in IDENTITY_ROLES:
        if name not in section.data:
            continue
        entry = section.section(name, _IDENTITY_KEYS)
        login = entry.text("login")
        if login is not None:
            _checked(login, LOGIN_RE, entry.path("login"), "GitHub login")
        token_env = entry.text("token_env")
        if token_env is not None:
            _secret_env_name(token_env, entry.path("token_env"))
        token_type = _token_type(entry, name)
        specs[name] = IdentitySpec(name, login, token_env, **_web_env_names(entry, name), token_type=token_type)
    admin = specs.get("admin")
    if admin is None or admin.login is None or admin.token_env is None:
        raise TargetError("identities.admin needs a login and a token_env")
    return specs


def _web_ui_part(top: _Section) -> str | None:
    """web_ui.probe_app_slug (a GitHub App slug, None when absent)."""
    section = top.section("web_ui", TOP_LEVEL_WEB_UI_KEYS)
    slug = section.text("probe_app_slug")
    if slug is not None:
        _checked(slug, APP_SLUG_RE, section.path("probe_app_slug"), "GitHub App slug")
    return slug


def _app_spec(top: _Section) -> AppSpec | None:
    """Parse the app section (None when absent)."""
    if top.data.get("app") is None:
        return None
    app = top.section("app", _APP_KEYS)
    id_env = _checked(app.required_text("id_env"), ENV_NAME_RE, app.path("id_env"), "environment variable name")
    key_env = app.text("private_key_env")
    key_file_env = app.text("private_key_file_env")
    if key_env is None and key_file_env is None:
        raise TargetError(f"{app.where}: private_key_env or private_key_file_env is required")
    if key_env is not None:
        _secret_env_name(key_env, app.path("private_key_env"))
    if key_file_env is not None:
        _checked(key_file_env, ENV_NAME_RE, app.path("private_key_file_env"), "environment variable name")
    secret_env = _secret_env_name(app.required_text("webhook_secret_env"), app.path("webhook_secret_env"))
    slug = app.text("slug")
    if slug is not None:
        _checked(slug, APP_SLUG_RE, app.path("slug"), "GitHub App slug")
    return AppSpec(id_env, key_env, key_file_env, secret_env, slug)


def _teams(top: _Section) -> tuple[str, str, str]:
    """Admin, approval and contributors team names (slug-shaped and distinct)."""
    teams = top.section("teams", _TEAM_KEYS)
    defaults = {"admin": "otterdog-admins", "approval": "project-leads", "contributors": "e2e-contributors"}
    names = [
        _checked(teams.required_text(key, default), TEAM_NAME_RE, teams.path(key), "team name (= slug)")
        for key, default in defaults.items()
    ]
    if len(set(names)) != len(names):
        raise TargetError(f"teams: admin, approval and contributors must be distinct, got {names}")
    return names[0], names[1], names[2]


def _webapp_spec(top: _Section) -> WebappSpec:
    """Parse and validate the webapp section."""
    web = top.section("webapp", _WEBAPP_KEYS)
    transport = web.required_text("transport", "relay")
    if transport not in TRANSPORTS:
        raise TargetError(f"{web.path('transport')}: {transport!r} is not one of {', '.join(TRANSPORTS)}")
    external_url = _url(web.text("external_url"), web.path("external_url"))
    if transport == "external" and external_url is None:
        raise TargetError(f"{web.path('external_url')} is required when the transport is 'external'")
    validation_context = web.required_text("validation_context", "e2e/otterdog-validate")
    sync_context = web.required_text("sync_context", "e2e/otterdog-sync")
    if validation_context == sync_context:
        raise TargetError(f"{web.where}: validation_context and sync_context must differ")
    return WebappSpec(
        transport=transport,
        external_url=external_url,
        external_init_url=_url(web.text("external_init_url"), web.path("external_init_url")),
        validation_context=validation_context,
        sync_context=sync_context,
        workers=web.integer("workers", 1, minimum=1, maximum=64),
        port=web.integer("port", 5000, minimum=1, maximum=65535),
    )


def _fixtures(top: _Section) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Fixture repos and extra protected repos (validated names)."""
    fixtures = top.section("fixtures", _FIXTURE_KEYS)
    repos = tuple(_repo_name(name, fixtures.path("repos")) for name in fixtures.names("repos"))
    extra = tuple(
        _repo_name(name, fixtures.path("extra_protected_repos")) for name in fixtures.names("extra_protected_repos")
    )
    return repos, extra


def _baseline_settings(top: _Section) -> dict[str, Any]:
    """baseline.settings: org settings overrides, never the live-derived plan/description/billing_email."""
    baseline = top.section("baseline", _BASELINE_KEYS)
    value = baseline.data.get("settings")
    if value is None:
        return {}
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise TargetError(f"{baseline.path('settings')}: expected a mapping of org settings")
    reserved = sorted(set(value) & set(RESERVED_BASELINE_SETTINGS))
    if reserved:
        raise TargetError(f"{baseline.path('settings')}: {', '.join(reserved)} always come from the live organization")
    return dict(value)


def _check_protected_names(names: Iterable[str]) -> None:
    """Protected repos must never look like run objects (the janitor and removal guards purge those)."""
    for name in names:
        if naming.E2E_NAME_RE.match(name):
            raise TargetError(f"protected repository {name!r} looks like a run-prefixed name (e2e-<run id>-...)")


def _target_path(name_or_path: str, settings: HarnessSettings) -> Path:
    """Target file for a name (targets_dir/<name>.yaml) or a path (cwd-relative, then project-relative)."""
    looks_like_path = name_or_path.endswith((".yaml", ".yml")) or "/" in name_or_path or os.sep in name_or_path
    if looks_like_path:
        path = Path(name_or_path).expanduser()
        candidates = [path] if path.is_absolute() else [Path.cwd() / path, settings.project_root / path]
    else:
        if not TARGET_NAME_RE.match(name_or_path):
            raise TargetError(f"invalid target name {name_or_path!r} (expected {TARGET_NAME_RE.pattern})")
        candidates = [settings.targets_dir / f"{name_or_path}{suffix}" for suffix in (".yaml", ".yml")]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.absolute()
    available = sorted(p.stem for p in settings.targets_dir.glob("*.y*ml")) if settings.targets_dir.is_dir() else []
    raise TargetError(f"target {name_or_path!r} not found (looked at {candidates[0]}; available: {available})")


def _read_yaml(path: Path) -> Mapping[str, Any]:
    """Parse a target file (TargetError on unreadable or non-mapping YAML)."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        raise TargetError(f"{path}: cannot read target file: {exc}") from exc
    if not isinstance(data, Mapping):
        raise TargetError(f"{path}: expected a mapping at the top level")
    return data


def _expand_tree(node: Any, environ: Mapping[str, str]) -> Any:
    """Expand ``${...}`` in every string value of a parsed YAML tree (keys untouched, no YAML re-parsing)."""
    if isinstance(node, str):
        return expand_env(node, environ)
    if isinstance(node, list):
        return [_expand_tree(item, environ) for item in node]
    if isinstance(node, Mapping):
        return {key: _expand_tree(value, environ) for key, value in node.items()}
    return node


def _build_target(data: Mapping[str, Any], path: Path) -> Target:
    """Validate an expanded target tree and build the Target."""
    top = _Section(data, "", _TOP_KEYS)
    name = _checked(top.required_text("name", path.stem), TARGET_NAME_RE, "name", "target name")
    github = _github_part(top)
    config = _config_part(top)
    admin_team, approval_team, contributors_team = _teams(top)
    fixture_repos, extra_protected = _fixtures(top)
    fixed_config = () if config.org_config_repo == "auto" else (config.org_config_repo,)
    _check_protected_names((config.configs_repo, config.defaults_repo, *fixed_config, *fixture_repos, *extra_protected))
    app = _app_spec(top)
    probe_app = _web_ui_part(top)
    if probe_app is not None and app is not None and app.slug == probe_app:
        raise TargetError(
            "web_ui.probe_app_slug must not be the e2e GitHub App (the web-UI tier uninstalls the probe App)"
        )
    return Target(
        name=name,
        description=top.text("description", "") or "",
        org=github.org,
        org_id=github.org_id,
        allowed_org_ids=github.allowed_org_ids,
        expected_plan=github.expected_plan,
        marker=github.marker,
        capability_overrides=github.capability_overrides,
        configs_repo=config.configs_repo,
        org_config_repo=config.org_config_repo,
        defaults_repo=config.defaults_repo,
        template_mode=config.template_mode,
        template_url=config.template_url,
        identities=_identity_specs(top),
        app=app,
        admin_team=admin_team,
        approval_team=approval_team,
        contributors_team=contributors_team,
        webapp=_webapp_spec(top),
        fixture_repos=fixture_repos,
        extra_protected_repos=extra_protected,
        baseline_settings=_baseline_settings(top),
        source_path=path,
        saml_sso=github.saml_sso,
        web_probe_app_slug=probe_app,
    )


def load_target(name_or_path: str, settings: HarnessSettings, environ: Mapping[str, str] | None = None) -> Target:
    """Load targets/<name>.yaml (or a path), expanding ``${...}`` from ``environ`` (os.environ); TargetError if invalid.

    A target naming a production org raises SafetyError (safety.check_org_allowed).
    """
    env = os.environ if environ is None else environ
    path = _target_path(name_or_path, settings)
    raw = _read_yaml(path)
    try:
        data = _expand_tree(raw, env)
    except ValueError as exc:
        raise TargetError(f"{path}: {exc}") from exc
    try:
        return _build_target(data, path)
    except TargetError as exc:
        raise TargetError(f"{path}: {exc}") from None


# --- identities and App credentials ---------------------------------------------------------------------------------
def _env_value(environ: Mapping[str, str], name: str | None) -> str | None:
    """Stripped value of env var ``name`` (None when the name is None or the value empty)."""
    if not name:
        return None
    return (environ.get(name) or "").strip() or None


def _check_distinct_tokens(identities: Mapping[str, Identity]) -> None:
    """TargetError when distinct roles share a token (each role needs its own machine account)."""
    by_token: dict[str, set[str]] = {}
    for name, identity in identities.items():
        by_token.setdefault(identity.token, set()).add(name)
    for names in by_token.values():
        if len(names) > 1 and not any(names <= group for group in SHAREABLE_TOKEN_GROUPS):
            raise TargetError(
                f"identities {', '.join(sorted(names))} share one token: use one machine account per role"
            )


def resolve_identities(target: Target, environ: Mapping[str, str]) -> dict[str, Identity]:
    """Identities whose token env var is set; oracle falls back to admin, optional ones without token are omitted.

    TargetError when the admin token is missing or distinct roles share a token; tokens are registered with REDACTOR.
    """
    found = {}
    for name, spec in target.identities.items():
        token = _env_value(environ, spec.token_env)
        if token is not None:
            found[name] = Identity(name, spec.login, token, spec.token_type)
    admin = found.get("admin")
    if admin is None:
        env_name = target.identities["admin"].token_env if "admin" in target.identities else "the admin token_env"
        raise TargetError(f"{target.name}: {env_name} (admin token) is not set")
    found.setdefault("oracle", Identity("oracle", admin.login, admin.token, admin.token_type))
    _check_distinct_tokens(found)
    REDACTOR.add(*(identity.token for identity in found.values()))
    return {name: found[name] for name in IDENTITY_ROLES if name in found}


def _read_private_key_file(path: Path, env_name: str) -> str:
    """Text of a PEM key file (TargetError when unreadable); warns when it is readable by others."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise TargetError(f"{env_name}: cannot read the App private key file {path}: {type(exc).__name__}") from None
    _warn_if_shared(path)
    return text


def _normalize_pem(pem: str, where: str) -> str:
    """PEM with literal ``\\n`` turned into newlines (CI secrets); TargetError if it is not a private key PEM."""
    pem = pem.strip()
    if "\\n" in pem and "\n" not in pem:
        pem = pem.replace("\\n", "\n")
    if not re.search(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", pem) or not re.search(
        r"-----END [A-Z ]*PRIVATE KEY-----", pem
    ):
        raise TargetError(f"{where}: the GitHub App private key is not a PEM private key")
    return pem + "\n"


def resolve_app_credentials(target: Target, environ: Mapping[str, str]) -> AppCredentials | None:
    """App credentials from the env vars of target.app (key inline or from a file), None when not configured.

    TargetError when the App is only partially configured; the key and webhook secret are registered with REDACTOR.
    """
    spec = target.app
    if spec is None:
        return None
    app_id = _env_value(environ, spec.id_env)
    key_inline = _env_value(environ, spec.private_key_env)
    key_file = _env_value(environ, spec.private_key_file_env)
    secret = _env_value(environ, spec.webhook_secret_env)
    if not any((app_id, key_inline, key_file, secret)):
        return None
    missing = [spec.id_env] if app_id is None else []
    if key_inline is None and key_file is None:
        missing.append(" or ".join(name for name in (spec.private_key_env, spec.private_key_file_env) if name))
    if secret is None:
        missing.append(spec.webhook_secret_env)
    if missing or app_id is None or secret is None:
        raise TargetError(f"{target.name}: GitHub App partially configured, missing {', '.join(missing)}")
    if not app_id.isdigit():
        raise TargetError(f"{spec.id_env}: the GitHub App id must be numeric")
    if key_inline is not None:
        REDACTOR.add(key_inline)  # raw form too (CI secrets may carry literal \n)
        pem = _normalize_pem(key_inline, spec.private_key_env or "app")
    else:
        assert key_file is not None and spec.private_key_file_env is not None
        file_env = spec.private_key_file_env
        pem = _normalize_pem(_read_private_key_file(_user_path(key_file, environ), file_env), file_env)
    REDACTOR.add(pem, secret)
    return AppCredentials(app_id=app_id, private_key_pem=pem, webhook_secret=secret, slug=spec.slug)


# --- web-UI credentials (docs/web-ui-testing.md) --------------------------------------------------------------------
class WebCredentialsError(TargetError):
    """Web-UI credentials are partially configured or invalid (the message never contains a secret)."""


def _otpauth_secret(value: str, where: str) -> str:
    """The ``secret`` of an ``otpauth://totp/...`` URI (only the defaults otterdog supports: SHA1, 6 digits, 30 s)."""
    parsed = urllib.parse.urlsplit(value)
    if parsed.netloc.lower() != "totp":
        raise WebCredentialsError(f"{where}: only otpauth://totp/ URIs are supported")
    query = urllib.parse.parse_qs(parsed.query)
    unsupported = {
        key: values[0]
        for key, expected in (("algorithm", "SHA1"), ("digits", "6"), ("period", "30"))
        if (values := query.get(key)) and values[0].upper() != expected
    }
    if unsupported:
        raise WebCredentialsError(
            f"{where}: otterdog computes SHA1 6-digit codes every 30 s; the URI asks for {sorted(unsupported)}"
        )
    secrets = query.get("secret") or []
    if not secrets:
        raise WebCredentialsError(f"{where}: the otpauth URI has no secret parameter")
    return secrets[0]


def normalize_totp_seed(value: str, *, where: str = "TOTP seed") -> str:
    """The base32 TOTP seed otterdog expects: spaces/dashes removed, upper case, no padding (an ``otpauth://`` URI is
    accepted too). WebCredentialsError (never quoting the value) unless it decodes to at least 80 bits."""
    text = value.strip()
    if text.lower().startswith("otpauth://"):
        text = _otpauth_secret(text, where)
    seed = re.sub(r"[\s-]+", "", text).upper().rstrip("=")
    padded = seed + "=" * (-len(seed) % 8)
    try:
        valid = bool(_BASE32_RE.match(padded)) and len(base64.b32decode(padded)) > 0
    except (binascii.Error, ValueError):
        valid = False
    if not valid or len(seed) < MIN_TOTP_SEED_LENGTH:
        raise WebCredentialsError(
            f"{where}: not a base32 TOTP secret of at least {MIN_TOTP_SEED_LENGTH} characters (use the setup key "
            "GitHub shows when an authenticator app is added to the account, or its otpauth:// URI)"
        )
    return seed


def web_credential_env_names(target: Target) -> dict[str, str]:
    """Variables holding the web credentials of the admin identity (declared names, else DEFAULT_WEB_ENV)."""
    spec = target.identities.get(WEB_IDENTITY) or IdentitySpec(WEB_IDENTITY, None, None)
    return {key: spec.web_env(key) for key in WEB_CREDENTIAL_KEYS}


def resolve_web_credentials(target: Target, environ: Mapping[str, str]) -> WebCredentials | None:
    """Web-UI credentials of the admin machine account, None when neither password nor TOTP seed is set.

    WebCredentialsError when only one of them is set, when the seed is not a base32 secret, when no username can be
    derived, or when the username is a login that is not the declared admin login (the web login must be the admin
    machine account, whose token otterdog uses too); an email username is accepted as is. The password and the seed
    are registered with REDACTOR.
    """
    names = web_credential_env_names(target)
    password = _env_value(environ, names["password_env"])
    seed = _env_value(environ, names["totp_seed_env"])
    REDACTOR.add(password, seed)
    if password is None and seed is None:
        return None
    if password is None or seed is None:
        missing = names["password_env"] if password is None else names["totp_seed_env"]
        raise WebCredentialsError(f"{target.name}: web-UI credentials partially configured, {missing} is not set")
    normalized = normalize_totp_seed(seed, where=names["totp_seed_env"])
    REDACTOR.add(normalized, normalized.lower())
    spec = target.identities.get(WEB_IDENTITY)
    login = spec.login if spec is not None else None
    if not login:
        raise WebCredentialsError(f"{target.name}: identities.admin.login is required for the web-UI credentials")
    username = _env_value(environ, names["username_env"]) or login
    if "@" not in username and username.lower() != login.lower():
        raise WebCredentialsError(
            f"{names['username_env']}: {username!r} is not the admin login {login!r}: the web-UI credentials must "
            "belong to the admin machine account"
        )
    return WebCredentials(WEB_IDENTITY, login, username, password, normalized)
