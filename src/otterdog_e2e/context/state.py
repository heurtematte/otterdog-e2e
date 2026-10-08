"""Options and shared state of the session context (SPEC 15).

E2EOptions holds the --e2e-* options of a session (environment fallbacks applied). ContextState is the dataclass every
facet of E2EContext builds on: the fields of the session (options, settings, run context, scratch and artifacts dirs,
the live state, finalizers, extras, run.json data), the per-context memoization (_memo), the require_* accessors that
raise ContextError while a resource is missing, and the writers of run.json and results.jsonl.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypeVar, cast

from otterdog_e2e.context.helpers import split_csv, text_or_none
from otterdog_e2e.naming import RunContext
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    import pytest

    from otterdog_e2e.capabilities import Capabilities
    from otterdog_e2e.github.http import GitHubHttp
    from otterdog_e2e.github.lease import OrgLease
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import HarnessSettings, Identity, Target

T = TypeVar("T")

# option dest -> environment fallback (pytest options of SPEC 15)
OPTION_ENV: Mapping[str, str] = {
    "e2e_target": "E2E_TARGET",
    "e2e_sut": "E2E_SUT",
    "e2e_base_sut": "E2E_BASE_SUT",
    "e2e_reset_sut": "E2E_RESET_SUT",
    "e2e_tags": "E2E_TAGS",
    "e2e_scenario": "E2E_SCENARIO",
    "e2e_artifacts": "E2E_ARTIFACTS",
    "e2e_run_id": "E2E_RUN_ID",
    "e2e_webapp_image": "E2E_WEBAPP_IMAGE",
    "e2e_change": "E2E_CHANGE",
    "e2e_allow_web_ui": "E2E_ALLOW_WEB_UI",  # a flag: true/1/yes enables it
}
DEFAULT_SUT = "release:latest"
DEFAULT_RESET_SUT = "release:latest"
AUTO_BASE = "auto"  # --e2e-base-sut auto = the merge base of the SUT (ResolvedSut.base_sha)
RUN_FILE = "run.json"
RESULTS_FILE = "results.jsonl"
HTTP_CACHE_DIR = "http-cache"  # live HTTP caches of the run (scratch) / offline ones of every run (E2E_CACHE_DIR)


class ContextError(RuntimeError):
    """The session cannot provide a resource (missing configuration, identity, App, ...)."""


# --- options -------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class E2EOptions:
    """The --e2e-* options of a session (env fallbacks applied)."""

    target: str | None = None
    sut: str = DEFAULT_SUT
    base_sut: str | None = None
    reset_sut: str = DEFAULT_RESET_SUT
    tags: tuple[str, ...] = ()
    scenario: tuple[str, ...] = ()
    artifacts: Path | None = None
    run_id: str | None = None
    keep: bool = False
    no_reset: bool = False
    webapp_image: str | None = None
    change: str | None = None
    strict_diff: bool = False
    no_http_cache: bool = False
    allow_remote_webapp: bool = False
    trust_code: str | None = None
    allow_web_ui: bool = False

    @classmethod
    def from_config(cls, config: pytest.Config) -> E2EOptions:
        """Read the options registered by pytest_plugin.pytest_addoption."""

        def text(dest: str) -> str | None:
            """Option value as a stripped string or None."""
            return text_or_none(config.getoption(dest, None))

        def flag(dest: str) -> bool:
            """Boolean option value."""
            return bool(config.getoption(dest, False))

        artifacts = text("e2e_artifacts")
        return cls(
            target=text("e2e_target"),
            sut=text("e2e_sut") or DEFAULT_SUT,
            base_sut=text("e2e_base_sut"),
            reset_sut=text("e2e_reset_sut") or DEFAULT_RESET_SUT,
            tags=split_csv(text("e2e_tags")),
            scenario=split_csv(text("e2e_scenario")),
            artifacts=Path(artifacts).expanduser() if artifacts else None,
            run_id=text("e2e_run_id"),
            keep=flag("e2e_keep"),
            no_reset=flag("e2e_no_reset"),
            webapp_image=text("e2e_webapp_image"),
            change=text("e2e_change"),
            strict_diff=flag("e2e_strict_diff"),
            no_http_cache=flag("e2e_no_http_cache"),
            allow_remote_webapp=flag("e2e_allow_remote_webapp"),
            trust_code=text("e2e_trust_code"),
            allow_web_ui=flag("e2e_allow_web_ui"),
        )


# --- the shared state ----------------------------------------------------------------------------------------------
@dataclass
class ContextState:
    """The state every facet of E2EContext shares; live fields stay None until ensure_live() (or the explicit
    load_target/verify/probe/acquire_lease steps of a command)."""

    options: E2EOptions
    settings: HarnessSettings
    run_ctx: RunContext
    scratch: Path
    artifacts_dir: Path
    target: Target | None = None
    identities: dict[str, Identity] = field(default_factory=dict)
    verified: VerifiedOrg | None = None
    capabilities: Capabilities | None = None
    docker_ok: bool | None = None
    app_ok: bool | None = None
    lease: OrgLease | None = None
    live_error: str | None = None
    finalizers: list[Callable[[], None]] = field(default_factory=list)
    extras: dict[str, Any] = field(default_factory=dict)
    environ: MutableMapping[str, str] = field(default_factory=lambda: os.environ, repr=False)
    run_info: dict[str, Any] = field(default_factory=dict, repr=False)
    leaks: list[Path] = field(default_factory=list)
    scrub_error: str | None = None
    closed: bool = False
    _live_attempted: bool = field(default=False, repr=False)
    _http: dict[tuple[str, str], GitHubHttp] = field(default_factory=dict, repr=False)
    _memos: dict[str, Any] = field(default_factory=dict, repr=False)
    _session_lock: Any = field(default=None, repr=False)  # filelock of the run's scratch (one session per run id)

    # --- memoization and requirements ---------------------------------------------------------------------------
    def _memo(self, key: str, factory: Callable[[], T]) -> T:
        """Value of ``factory`` computed once per context."""
        if key not in self._memos:
            self._memos[key] = factory()
        return cast(T, self._memos[key])

    def require_target(self) -> Target:
        """The loaded target (ContextError before load_target)."""
        if self.target is None:
            raise ContextError("no target loaded")
        return self.target

    def require_verified(self) -> VerifiedOrg:
        """The VerifiedOrg (ContextError before verify)."""
        if self.verified is None:
            raise ContextError("the target org has not been verified (no live session)")
        return self.verified

    def require_capabilities(self) -> Capabilities:
        """The probed capabilities (ContextError before probe)."""
        if self.capabilities is None:
            raise ContextError("capabilities have not been probed (no live session)")
        return self.capabilities

    def require_identity(self, name: str) -> Identity:
        """A configured identity (ContextError naming its token env var otherwise)."""
        identity = self.identities.get(name)
        if identity is not None:
            return identity
        spec = self.target.identities.get(name) if self.target is not None else None
        hint = f" (set {spec.token_env})" if spec is not None and spec.token_env else ""
        raise ContextError(f"identity {name!r} is not configured{hint}")

    # --- reporting --------------------------------------------------------------------------------------------------
    def write_run_info(self, **fields: Any) -> None:
        """Merge ``fields`` into run.json (redacted) when the artifacts dir exists."""
        self.run_info.update(fields)
        if self.artifacts_dir.is_dir():
            text = json.dumps(self.run_info, indent=2, sort_keys=True, default=str)
            (self.artifacts_dir / RUN_FILE).write_text(REDACTOR(text) + "\n", encoding="utf-8")

    def append_result(self, line: Mapping[str, Any]) -> None:
        """Append one redacted line to results.jsonl."""
        if not self.artifacts_dir.is_dir():
            return
        with (self.artifacts_dir / RESULTS_FILE).open("a", encoding="utf-8") as handle:
            handle.write(REDACTOR(json.dumps(line, sort_keys=True, default=str)) + "\n")
