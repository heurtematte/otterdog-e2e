"""Session context of the harness (SPEC 15, F3): the composition root shared by the pytest plugin and the CLI.

An E2EContext is created per pytest session (``config.stash[E2E_CONTEXT_KEY]``, see get_context) or per harness
command. Its live part (target, identities, VerifiedOrg, capabilities, docker/App availability, the org lease) is
built by ensure_live() at the first live item only, so offline-only runs never touch GitHub; gating hooks and session
fixtures read the same context. Collaborators are imported lazily inside methods: the plugin is loaded by every pytest
session and must stay cheap and robust to import.

E2EContext (core.py) is assembled from one class per facet over ContextState (state.py: E2EOptions and the shared
state): LiveFacet (live.py: target, verification, GitHub clients, App, org lease, janitor), SutFacet (sut.py: systems
under test, otterdog drivers, differential sides), WebUiFacet (webui.py: web-UI tier), WebappFacet (webapp.py: webapp
tier) and RunDataFacet (rundata.py: scenario variables, rate budget, known bugs, change under test); each facet extends
the facets it builds on. helpers.py holds the small helpers. Import the names below from ``otterdog_e2e.context``.
"""

from __future__ import annotations

import pytest

from otterdog_e2e.context.core import INVOCATION_ENV, E2EContext
from otterdog_e2e.context.helpers import (
    describe_error,
    env_flag,
    in_ci,
    installation_problems,
    lease_holder,
    lock_held,
    parse_duration,
    parse_time,
    printed_version,
    split_csv,
    target_env_name,
    text_or_none,
    workspace_literals,
)
from otterdog_e2e.context.state import (
    AUTO_BASE,
    DEFAULT_RESET_SUT,
    DEFAULT_SUT,
    OPTION_ENV,
    ContextError,
    E2EOptions,
)
from otterdog_e2e.context.sut import OBSERVATIONS_DIR, SutPair
from otterdog_e2e.context.webapp import WebappCase, check_organization_overrides
from otterdog_e2e.redact import REDACTOR

__all__ = [
    "AUTO_BASE",
    "DEFAULT_RESET_SUT",
    "DEFAULT_SUT",
    "E2E_CONTEXT_KEY",
    "INVOCATION_ENV",
    "OBSERVATIONS_DIR",
    "OPTION_ENV",
    "ContextError",
    "E2EContext",
    "E2EOptions",
    "SutPair",
    "WebappCase",
    "check_organization_overrides",
    "describe_error",
    "env_flag",
    "get_context",
    "in_ci",
    "installation_problems",
    "lease_holder",
    "lock_held",
    "parse_duration",
    "parse_time",
    "peek_context",
    "printed_version",
    "split_csv",
    "target_env_name",
    "text_or_none",
    "workspace_literals",
]

E2E_CONTEXT_KEY: pytest.StashKey[E2EContext] = pytest.StashKey[E2EContext]()


def get_context(config: pytest.Config) -> E2EContext:
    """The session's E2EContext (created on first use: settings, run context, scratch and artifacts dirs)."""
    context = config.stash.get(E2E_CONTEXT_KEY, None)
    if context is None:
        context = E2EContext.create(E2EOptions.from_config(config))
        try:
            context.start_session(argv=[REDACTOR(str(arg)) for arg in config.invocation_params.args])
        except ContextError as exc:  # e.g. the run id is used by another session of this machine
            raise pytest.UsageError(str(exc)) from None
        config.stash[E2E_CONTEXT_KEY] = context
    return context


def peek_context(config: pytest.Config) -> E2EContext | None:
    """The session's E2EContext if one was created (never creates it)."""
    return config.stash.get(E2E_CONTEXT_KEY, None)
