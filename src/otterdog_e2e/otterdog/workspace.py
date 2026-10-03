"""otterdog configuration workspaces: otterdog.json + orgs/<org>/<org>.jsonnet (SPEC 11.1).

Credentials always use otterdog's ``env`` provider with the E2E_OTTERDOG_* variable names of CREDENTIAL_ENV, so the
token reaches the CLI only through the (sanitized) process environment. The web-UI login (username, password, TOTP
seed) is "unset" except for the commands of a web-mode CLI (web_credentials_env). Workspaces live in the private
scratch dir; only otterdog's configuration and the org config files are copied (redacted) to artifacts.

Layout (otterdog/config.py, otterdog/jsonnet.py): with ``-c <root>/otterdog.json`` otterdog's working dir is
``<root>``; it creates ``<root>/orgs/``, clones templates into ``<root>/orgs/templates/<owner>/<repo>/<ref>/`` and
vendors the template into ``<root>/orgs/<org>/vendor/<repo>/`` (non ``--local`` runs only).

Untrusted SUTs (ISO-01) run in a container with the workspace root bind-mounted read-write, as the host uid: anything
they leave there (a symlink to a host file, a FIFO) would redirect the host-side reads, writes and deletions the
harness does afterwards. The runner therefore calls neutralize_untrusted_tree on the mount after every container
command (links resolving outside the root and special files are removed), host reads of container-written files go
through read_untrusted_text (no symlink, regular file, inside the root) and workspace writes through
write_private_text (a planted link is replaced, never followed).

Config-discovery and loading tests change that layout with a WorkspaceLayout (``workspace.layout = ...`` or
``use_layout``; offline YAML steps: the ``workspace`` key): otterdog.jsonnet instead of otterdog.json, several
organizations, a ``.otterdog-defaults.json`` next to the config file (otterdog deep-merges it OVER the ``defaults``
of the config file), another ``defaults.base_url`` or ``defaults.jsonnet.config_dir``, a complete document of the
test's own, and ``vendor=False`` (the engines then leave the template out: ``--local`` commands fail with "template
file '...' does not exist"). Verified against otterdog/cli.py (``_CONFIG_FILES``, OTTERDOG_CONFIG_ROOT) and
otterdog/config.py (``load_json_or_jsonnet``, ``.otterdog-defaults.json``, ``archived`` entries) at main 9bdeb75.
"""

from __future__ import annotations

import copy
import errno
import json
import logging
import os
import re
import shutil
import stat
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.settings import Identity, Target, WebCredentials
    from otterdog_e2e.sut.template import TemplateRef

CREDENTIAL_ENV = {
    "api_token": "E2E_OTTERDOG_API_TOKEN",
    "username": "E2E_OTTERDOG_USERNAME",
    "password": "E2E_OTTERDOG_PASSWORD",
    "twofa_seed": "E2E_OTTERDOG_TOTP_SEED",
}
OFFLINE_TOKEN = "offline-dummy-token"  # noqa: S105 - dummy token of the offline tier
DEFAULT_BASE_URL = "https://otterdog.invalid"
CONFIG_DIR = "orgs"
TEMPLATES_DIR = "templates"  # <config_dir>/templates/<owner>/<repo>/<ref>: otterdog's template clones
VENDOR_DIR = "vendor"
CONFIG_FILE = "otterdog.json"
JSONNET_CONFIG_FILE = "otterdog.jsonnet"
# otterdog's _CONFIG_FILES (discovery order without -c: otterdog.jsonnet first) by WorkspaceLayout.format
CONFIG_FILES: Mapping[str, str] = {"json": CONFIG_FILE, "jsonnet": JSONNET_CONFIG_FILE}
CONFIG_FORMATS = tuple(CONFIG_FILES)
DEFAULTS_OVERRIDE_FILE = ".otterdog-defaults.json"  # next to the config file, deep-merged over its "defaults"
BASE_SUFFIX = "-BASE"  # the other side of local-plan (otterdog's default -s)
# keys of an extra organization entry (OrganizationConfig.from_dict) and of a layout's defaults override
ORG_ENTRY_KEYS = (
    "name",
    "github_id",
    "config_repo",
    "base_template",
    "archived",
    "approval_teams",
    "admin_teams",
    "credentials",
)
_DIR_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
_SUFFIX_RE = re.compile(r"^[A-Za-z0-9_.-]*$")
UNTRUSTED_READ_LIMIT = 64 * 1024 * 1024  # bytes read_untrusted_text accepts (an org config of a large org fits)
_OPEN_FLAGS = getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
_SPECIAL_MODES = (stat.S_ISLNK, stat.S_ISFIFO, stat.S_ISSOCK, stat.S_ISCHR, stat.S_ISBLK)

log = logging.getLogger(__name__)


# --- files written by untrusted containers (ISO-01) --------------------------------------------------------------------
def is_within(path: Path | str, root: Path | str) -> bool:
    """True when the real path of ``path`` is the real path of ``root`` or below it (symlinks resolved)."""
    real, base = os.path.realpath(path), os.path.realpath(root)
    return real == base or real.startswith(base.rstrip(os.sep) + os.sep)


def neutralize_untrusted_tree(root: Path) -> list[str]:
    """Remove from ``root`` (a container's bind mount) every symlink that resolves outside ``root`` and every special
    file (FIFO, socket, device), without following any link; returns the removed paths relative to ``root``.

    A container of an untrusted SUT can create them in the read-write mount; the harness reads, writes and deletes
    files there afterwards (check-status JSON, imported configs, rewritten configs, template cache cleanup), so the
    mount is neutralized after every container command, once the container has exited.
    """
    removed: list[str] = []
    base = os.path.realpath(root)
    if not os.path.isdir(base):
        return removed
    # every decision is taken on the tree as the container left it, before any removal: a link chained through
    # another removed link (chain -> abs -> /outside) must not look harmless just because abs went first
    doomed: list[str] = []
    pending = [base]
    while pending:
        directory = pending.pop()
        try:
            entries = list(os.scandir(directory))
        except PermissionError:
            try:  # a directory the container made unreadable: the host user owns it, so it can open it up again
                os.chmod(directory, 0o700)
                entries = list(os.scandir(directory))
            except OSError as exc:
                raise SafetyError(f"cannot inspect {directory} left by an untrusted container: {exc}") from exc
        except OSError as exc:
            raise SafetyError(f"cannot inspect {directory} left by an untrusted container: {exc}") from exc
        for entry in entries:
            try:
                mode = entry.stat(follow_symlinks=False).st_mode
            except OSError:
                continue
            if stat.S_ISDIR(mode):
                pending.append(entry.path)
                continue
            if stat.S_ISREG(mode) or (stat.S_ISLNK(mode) and is_within(entry.path, base)):
                continue
            if any(check(mode) for check in _SPECIAL_MODES):
                doomed.append(entry.path)
    for path in doomed:
        try:
            os.unlink(path)
        except OSError as exc:
            raise SafetyError(f"cannot remove {path} planted by an untrusted container: {exc}") from exc
        removed.append(os.path.relpath(path, base))
    return sorted(removed)


def read_untrusted_text(path: Path, *, within: Path, limit: int = UNTRUSTED_READ_LIMIT) -> str | None:
    """Text (UTF-8, invalid bytes replaced) of a file an untrusted SUT may have written, None when it does not exist.

    SafetyError when ``path`` resolves outside ``within``, is a symlink (never followed: O_NOFOLLOW) or not a regular
    file (a FIFO cannot block the read: O_NONBLOCK), or holds more than ``limit`` bytes.
    """
    if not is_within(path.parent, within):
        raise SafetyError(f"refusing to read {path}: its directory resolves outside {within}")
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | _OPEN_FLAGS)
    except FileNotFoundError:
        return None
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SafetyError(f"refusing to read {path}: it is a symbolic link") from exc
        raise
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise SafetyError(f"refusing to read {path}: not a regular file")
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise SafetyError(f"refusing to read {path}: larger than {limit} bytes")
    return data.decode("utf-8", errors="replace")


def write_private_text(path: Path, text: str, *, within: Path | None = None) -> Path:
    """Write ``text`` to ``path`` (parents created 0700, file 0600) without ever following a link at ``path``: a
    symlink or special file found there is removed first. With ``within``, the directory of ``path`` must resolve
    inside it (SafetyError otherwise)."""
    if within is not None and not is_within(path.parent, within):  # checked before mkdir follows a planted link
        raise SafetyError(f"refusing to write {path}: its directory resolves outside {within}")
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        mode = os.lstat(path).st_mode
    except FileNotFoundError:
        mode = None
    if mode is not None and any(check(mode) for check in _SPECIAL_MODES):
        path.unlink()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | _OPEN_FLAGS, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        os.fchmod(handle.fileno(), 0o600)
        handle.write(text)
    return path


def credentials_env(identity: Identity | None) -> dict[str, str]:
    """Env vars of CREDENTIAL_ENV: the identity's token (or OFFLINE_TOKEN when None); username/password/seed "unset"."""
    return {
        CREDENTIAL_ENV["api_token"]: identity.token if identity is not None else OFFLINE_TOKEN,
        CREDENTIAL_ENV["username"]: "unset",
        CREDENTIAL_ENV["password"]: "unset",
        CREDENTIAL_ENV["twofa_seed"]: "unset",
    }


def web_credentials_env(identity: Identity | None, web: WebCredentials) -> dict[str, str]:
    """credentials_env() plus the bot's web-UI login (username, password, TOTP seed) for ONE web-mode command.

    Only the web mode of otterdog.runner calls it (trusted SUTs on the host, docs/web-ui-testing.md).
    """
    return {
        **credentials_env(identity),
        CREDENTIAL_ENV["username"]: web.username,
        CREDENTIAL_ENV["password"]: web.password,
        CREDENTIAL_ENV["twofa_seed"]: web.totp_seed,
    }


def _defaults(
    template: TemplateRef, *, config_repo: str, base_url: str | None, config_dir: str = CONFIG_DIR
) -> dict[str, Any]:
    """The ``defaults`` section shared by the CLI and webapp otterdog.json."""
    return {
        "base_url": base_url or DEFAULT_BASE_URL,
        "jsonnet": {"base_template": template.url, "config_dir": config_dir},
        "github": {"config_repo": config_repo},
    }


def _write_private(path: Path, text: str, *, root: Path | None = None) -> Path:
    """write_private_text inside ``root`` (the workspace root: the mount of container runtimes)."""
    return write_private_text(path, text, within=root)


def dir_name_problem(value: Any, what: str) -> str | None:
    """Why ``value`` cannot be a directory of the workspace (one relative path segment, no ``..``), None when it can:
    the harness writes the org configs there, so it must stay inside the workspace root."""
    if not isinstance(value, str) or not _DIR_NAME_RE.match(value) or value in (".", ".."):
        return f"{what} {value!r} is not a directory name ([A-Za-z0-9_][A-Za-z0-9_.-]*, one path segment)"
    return None


def jsonnet_config_text(document: Mapping[str, Any]) -> str:
    """otterdog.jsonnet holding ``document`` behind a jsonnet ``local`` (a JSON parser would refuse it, so a working
    command proves otterdog evaluated it as jsonnet)."""
    body = json.dumps(document, indent=2)
    return (
        "// otterdog.jsonnet written by otterdog-e2e (WorkspaceLayout format 'jsonnet'), evaluated by otterdog\n"
        f"local config = {body};\n\nconfig\n"
    )


@dataclass(frozen=True)
class WorkspaceLayout:
    """How a ConfigWorkspace writes otterdog's own configuration; the default is the harness layout (otterdog.json,
    one organization, config_dir ``orgs``, no defaults override, vendored template).

    * ``format``: ``json`` writes otterdog.json, ``jsonnet`` otterdog.jsonnet (jsonnet_config_text);
    * ``orgs``: extra entries of ``organizations`` after the workspace's own; a string is the github_id (and name) of
      an ordinary organization, a mapping (keys ORG_ENTRY_KEYS) is merged over ``{name: <github_id>, config_repo,
      credentials: env provider}``: a key set to None is written as null (otterdog then reports the missing key);
    * ``defaults_override``: content of .otterdog-defaults.json (None: no such file; otterdog merges it OVER the
      config file's defaults, a null value included);
    * ``base_url``: ``defaults.base_url`` (None: the workspace's, else DEFAULT_BASE_URL);
    * ``config_dir``: ``defaults.jsonnet.config_dir``; the org configs live in ``<root>/<config dir>/<org>/`` with
      the override's ``jsonnet.config_dir`` winning (ConfigWorkspace.config_dir);
    * ``vendor``: False tells the engines not to vendor the template (the workspace itself never vendors);
    * ``document``: a complete document written as it is instead of the generated one (Python tests only: the YAML
      ``workspace`` key cannot set it), e.g. one without ``defaults.jsonnet.base_template``.

    ValueError for an unknown format, a config dir that is not one path segment, entries of the wrong type.
    """

    format: str = "json"
    orgs: tuple[str | Mapping[str, Any], ...] = ()
    defaults_override: Mapping[str, Any] | None = None
    base_url: str | None = None
    config_dir: str = CONFIG_DIR
    vendor: bool = True
    document: Mapping[str, Any] | None = None

    def __post_init__(self) -> None:
        """Validate the fields (lists of orgs become tuples)."""
        if self.format not in CONFIG_FORMATS:
            raise ValueError(f"workspace format {self.format!r} is not one of {list(CONFIG_FORMATS)}")
        problem = dir_name_problem(self.config_dir, "config_dir")
        if problem:
            raise ValueError(problem)
        orgs = tuple(self.orgs) if isinstance(self.orgs, Sequence) and not isinstance(self.orgs, str) else None
        if orgs is None:
            raise ValueError(f"orgs must be a list of organization entries, got {type(self.orgs).__name__}")
        for entry in orgs:
            if isinstance(entry, Mapping):
                unknown = sorted(set(map(str, entry)) - set(ORG_ENTRY_KEYS))
                if unknown:
                    raise ValueError(f"organization entry {dict(entry)!r}: unknown key(s) {unknown}")
            elif not isinstance(entry, str) or not entry:
                raise ValueError(f"organization entry {entry!r} is neither a github_id nor a mapping")
        object.__setattr__(self, "orgs", orgs)
        for name, value in (("defaults_override", self.defaults_override), ("document", self.document)):
            if value is not None and not isinstance(value, Mapping):
                raise ValueError(f"{name} must be a mapping or None, got {type(value).__name__}")
        override_dir = _override_config_dir(self.defaults_override)
        if override_dir is not None:
            problem = dir_name_problem(override_dir, "defaults_override.jsonnet.config_dir")
            if problem:
                raise ValueError(problem)

    @property
    def is_default(self) -> bool:
        """True for the harness layout (WorkspaceLayout())."""
        return self == WorkspaceLayout()

    @property
    def effective_config_dir(self) -> str:
        """The org config directory otterdog reads: the override's ``jsonnet.config_dir``, else ``config_dir``."""
        override_dir = _override_config_dir(self.defaults_override)
        return override_dir if isinstance(override_dir, str) else self.config_dir


def _override_config_dir(override: Mapping[str, Any] | None) -> Any:
    """``jsonnet.config_dir`` of a defaults override as written (None when it sets none)."""
    jsonnet = override.get("jsonnet") if isinstance(override, Mapping) else None
    return jsonnet.get("config_dir") if isinstance(jsonnet, Mapping) else None


def entry_github_id(entry: str | Mapping[str, Any]) -> str | None:
    """github_id of an extra organization entry (None when the entry has none)."""
    if isinstance(entry, str):
        return entry
    value = entry.get("github_id")
    return value if isinstance(value, str) and value else None


class ConfigWorkspace:
    """A directory holding otterdog's configuration and the org config (plus the ``-BASE`` file for local-plan);
    ``layout`` (WorkspaceLayout) decides the file names and the organizations written."""

    def __init__(
        self,
        root: Path,
        *,
        org: str,
        template: TemplateRef,
        config_repo: str,
        project: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Bind the workspace to ``root`` (nothing is written yet); project defaults to the org login."""
        self.root = root
        self.org = org
        self.template = template
        self.config_repo = config_repo
        self.project = project or org
        self.base_url = base_url
        self.layout = WorkspaceLayout()

    @property
    def config_file(self) -> Path:
        """root/otterdog.json (root/otterdog.jsonnet with the ``jsonnet`` layout format): the ``-c`` file."""
        return self.root / CONFIG_FILES[self.layout.format]

    @property
    def defaults_override_file(self) -> Path:
        """root/.otterdog-defaults.json (written when the layout has a defaults override)."""
        return self.root / DEFAULTS_OVERRIDE_FILE

    @property
    def config_dir(self) -> str:
        """Directory of the org configs below root: WorkspaceLayout.effective_config_dir (default ``orgs``)."""
        return self.layout.effective_config_dir

    @property
    def org_dir(self) -> Path:
        """root/<config dir>/<org>."""
        return self.org_dir_for(self.org)

    def org_dir_for(self, org: str) -> Path:
        """root/<config dir>/<org> of any organization of the workspace."""
        return self.root / self.config_dir / org

    @property
    def org_config_file(self) -> Path:
        """root/<config dir>/<org>/<org>.jsonnet."""
        return self.org_config_file_for(self.org)

    def org_config_file_for(self, org: str, *, suffix: str = "") -> Path:
        """root/<config dir>/<org>/<org>.jsonnet<suffix> (``suffix`` e.g. ``-BASE``)."""
        if not _SUFFIX_RE.match(suffix):
            raise ValueError(f"invalid config file suffix {suffix!r}")
        return self.org_dir_for(org) / f"{org}.jsonnet{suffix}"

    @property
    def base_config_file(self) -> Path:
        """root/<config dir>/<org>/<org>.jsonnet-BASE (the other side of ``local-plan``)."""
        return self.org_config_file_for(self.org, suffix=BASE_SUFFIX)

    @property
    def vendor_dir(self) -> Path:
        """root/<config dir>/<org>/vendor (the vendored template, imported as ``vendor/<repo>/<file>``)."""
        return self.org_dir / VENDOR_DIR

    @property
    def templates_dir(self) -> Path:
        """root/<config dir>/templates (otterdog's clones of base templates)."""
        return self.root / self.config_dir / TEMPLATES_DIR

    @property
    def org_ids(self) -> list[str]:
        """github_ids of the workspace's organizations: its own, then the layout's extra entries that have one."""
        extra = [entry_github_id(entry) for entry in self.layout.orgs]
        return [self.org, *(org for org in extra if org)]

    def otterdog_json(self) -> dict[str, Any]:
        """The configuration document of this workspace (env credential provider, no secret values; the layout's
        ``document`` as it is when it has one)."""
        if self.layout.document is not None:
            return copy.deepcopy(dict(self.layout.document))
        organization = {
            "name": self.project,
            "github_id": self.org,
            "config_repo": self.config_repo,
            "credentials": self._credentials(),
        }
        defaults = _defaults(
            self.template,
            config_repo=self.config_repo,
            base_url=self.layout.base_url or self.base_url,
            config_dir=self.layout.config_dir,
        )
        extra = [self._org_entry(entry) for entry in self.layout.orgs]
        return {"defaults": defaults, "organizations": [organization, *extra]}

    @staticmethod
    def _credentials() -> dict[str, str]:
        """The env credential provider (variable names only)."""
        return {"provider": "env", **CREDENTIAL_ENV}

    def _org_entry(self, entry: str | Mapping[str, Any]) -> dict[str, Any]:
        """An extra ``organizations`` entry (WorkspaceLayout.orgs): name (= github_id unless given), github_id,
        config_repo and the env credentials, overridden by the entry's own keys."""
        data: Mapping[str, Any] = {"github_id": entry} if isinstance(entry, str) else entry
        result: dict[str, Any] = {}
        if "github_id" in data:
            result.update(name=data["github_id"], github_id=data["github_id"])
        result.update({"config_repo": self.config_repo, "credentials": self._credentials()})
        result.update(copy.deepcopy(dict(data)))
        return result

    def use_layout(self, layout: WorkspaceLayout) -> Path:
        """Switch to ``layout`` and write its configuration (write_otterdog_json); returns the config file."""
        self.layout = layout
        return self.write_otterdog_json()

    def config_texts(self) -> dict[Path, str | None]:
        """The files write_otterdog_json writes (path -> text) or removes (path -> None): the config file of the
        layout, the config file of the other format (removed) and .otterdog-defaults.json (removed without an
        override: otterdog reads it whenever it exists)."""
        document = self.otterdog_json()
        text = jsonnet_config_text(document) if self.layout.format == "jsonnet" else json.dumps(document, indent=2)
        texts: dict[Path, str | None] = {self.root / name: None for name in CONFIG_FILES.values()}
        texts[self.config_file] = text.rstrip("\n") + "\n"
        override = self.layout.defaults_override
        texts[self.defaults_override_file] = None if override is None else json.dumps(override, indent=2) + "\n"
        return texts

    def write_otterdog_json(self) -> Path:
        """Write the configuration of the layout (default: otterdog.json with defaults base_url, jsonnet.base_template
        = template.url, config_dir "orgs", github.config_repo and one organization with the env credential provider;
        files of config_texts()) and return its path."""
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        for path, text in self.config_texts().items():
            if text is not None:
                _write_private(path, text, root=self.root)
            elif path.is_file() or path.is_symlink():
                path.unlink()
        return self.config_file

    def write_org_config(self, text: str, *, org: str | None = None) -> Path:
        """Write the org config file (of ``org``, default the workspace's organization)."""
        return _write_private(self.org_config_file_for(org or self.org), text, root=self.root)

    def write_base_config(self, text: str, *, org: str | None = None, suffix: str = BASE_SUFFIX) -> Path:
        """Write the ``-BASE`` config file used by local-plan (``suffix``: another ``local-plan -s`` side)."""
        return _write_private(self.org_config_file_for(org or self.org, suffix=suffix), text, root=self.root)

    def read_org_config(self, *, org: str | None = None) -> str:
        """Read the org config file (of ``org``, default the workspace's organization) with read_untrusted_text: an
        untrusted SUT may have written it (import, fetch-config); FileNotFoundError when it does not exist."""
        path = self.org_config_file_for(org or self.org)
        text = read_untrusted_text(path, within=self.root)
        if text is None:
            raise FileNotFoundError(errno.ENOENT, "no such org config file", str(path))
        return text

    def clean_template_cache(self) -> None:
        """Remove cloned templates and the vendored copies so the next command re-clones the template (or, offline,
        finds no template)."""
        for directory in (self.templates_dir, *(self.org_dir_for(org) / VENDOR_DIR for org in self.org_ids)):
            if directory.is_symlink():
                directory.unlink()
            elif directory.exists():
                if not is_within(directory, self.root):  # a parent link planted by a container (ISO-01)
                    raise SafetyError(f"refusing to delete {directory}: it resolves outside {self.root}")
                shutil.rmtree(directory)

    def export_to(self, artifacts_dir: Path) -> None:
        """Copy otterdog's configuration and orgs/<org>/<org>.jsonnet* of every organization (redacted) to
        ``artifacts_dir``; nothing else.

        Copies keep text extensions only (SPEC 5.7): org configs and otterdog.jsonnet get a ``.txt`` suffix
        (``<org>.jsonnet.txt``, ``<org>.jsonnet-BASE.txt``, ``otterdog.jsonnet.txt``); otterdog.json and
        .otterdog-defaults.json keep their names.
        """
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        copies: dict[Path, Path] = {}
        for name in CONFIG_FILES.values():
            copies[self.root / name] = artifacts_dir / (name if name.endswith(".json") else f"{name}.txt")
        copies[self.defaults_override_file] = artifacts_dir / DEFAULTS_OVERRIDE_FILE
        for org in self.org_ids:
            directory = self.org_dir_for(org)
            if directory.is_dir() and is_within(directory, self.root):
                for source in sorted(directory.glob(f"{org}.jsonnet*")):
                    copies[source] = artifacts_dir / f"{source.name}.txt"
        for source, target in copies.items():
            if source.is_file() and not source.is_symlink() and is_within(source, self.root):
                text = read_untrusted_text(source, within=self.root)
                if text is not None:
                    target.write_text(REDACTOR(text), encoding="utf-8")


def webapp_otterdog_json(
    target: Target, template: TemplateRef, *, config_repo: str, project: str | None = None
) -> dict[str, Any]:
    """otterdog.json for the webapp: same defaults without credentials; organization entry {name, github_id,
    config_repo, admin_teams: [admin_team], approval_teams: [f"^{approval_team}$"]}."""
    organization = {
        "name": project or target.org,
        "github_id": target.org,
        "config_repo": config_repo,
        "admin_teams": [target.admin_team],
        "approval_teams": [f"^{target.approval_team}$"],
    }
    return {"defaults": _defaults(template, config_repo=config_repo, base_url=None), "organizations": [organization]}
