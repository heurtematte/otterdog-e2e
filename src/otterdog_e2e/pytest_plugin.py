"""pytest plugin of otterdog-e2e (SPEC 15), registered through the ``pytest11`` entry point (never via conftest).

Gating never lives in fixtures: pytest_collection_modifyitems applies tier and scenario marks, deselects by
--e2e-tags/--e2e-scenario, skips live items without a target (and differential items without a base SUT) and adds
known-bug xfails; a tryfirst pytest_runtest_setup checks requires/plan/identities/docker/webapp/rate budget against the
E2EContext before any fixture runs. Reporting redacts every report, writes results.jsonl per item and, at session end,
the differential report and summary.md before the context closes (lease release, artifact scrub).

Web-UI tier (tests/web_ui, docs/web-ui-testing.md): items marked ``web_ui`` drive the GitHub web UI through otterdog
(bot login with TOTP); the gate skips them unless context.web_ui_problems() is empty (admin web credentials,
--e2e-allow-web-ui or E2E_ALLOW_WEB_UI, a trusted SUT, no github.saml_sso, web logins not blocked). The Playwright
Firefox of the trusted SUTs is installed before the first item; the baseline teardown restores the web-only settings
recorded by the tier when its own restore could not be verified.

Webapp tier extras: the identity mutator fixtures (``outsider_mutator``, ``approver_mutator``, ``contributor_mutator``
= the author identity, a contributors-team member) gate on their identity like ``identities(...)``; the compose-only
fixtures (``webapp_stack``, ``webapp_env``, ``dtrack_mock``) skip unless the webapp runs in the compose stack; a
selected item using ``dtrack_mock`` starts the stack with the Dependency-Track mock; ``blueprints`` gives a
blueprints.BlueprintHelper whose definitions, remediation PRs and workflow runs are cleaned up after the test;
``webapp_otterdog_json`` publishes otterdog.json with per-org team overrides and restores it after the test.

Selection (scenarios.collect.item_selected): values inside --e2e-scenario (globs on scenario ids, or on the
``<scenario id>/<step>`` of the offline cases) or inside --e2e-tags
are ORed, the two options are ANDed. tests/unit and tests/offline items (and items outside the tier directories that
carry no e2e marker) are exempt from --e2e-tags, never from --e2e-scenario; the scenarios referencing the change under
test (--e2e-change, E2E_CHANGE, default: N of a ``pr:N@<sha>`` --e2e-sut; changes.py) pass the tags filter like tagged
items, and their expected deltas feed the session's differential report.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import signal
import threading
import time
from collections.abc import Callable, Generator, Iterator, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import redact
from otterdog_e2e.context import (
    DEFAULT_RESET_SUT,
    DEFAULT_SUT,
    OBSERVATIONS_DIR,
    OPTION_ENV,
    ContextError,
    E2EContext,
    E2EOptions,
    SutPair,
    WebappCase,
    describe_error,
    env_flag,
    get_context,
    in_ci,
    peek_context,
    text_or_none,
)

if TYPE_CHECKING:
    from otterdog_e2e.blueprints import BlueprintHelper
    from otterdog_e2e.capabilities import Capabilities
    from otterdog_e2e.changes import ChangeSpec
    from otterdog_e2e.config_repo import ConfigRepoFlow
    from otterdog_e2e.github.app import AppAuth
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.known_bugs import KnownBug
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.scenarios.engine import ScenarioEngine
    from otterdog_e2e.scenarios.model import Scenario
    from otterdog_e2e.settings import HarnessSettings, Identity, Target
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.image import BuiltImage
    from otterdog_e2e.sut.template import TemplateRef
    from otterdog_e2e.webapp.api import WebappApi
    from otterdog_e2e.webapp.stack import DtrackMock, ExternalWebapp, WebappStack
    from otterdog_e2e.webhooks.injector import WebhookInjector
    from otterdog_e2e.webhooks.relay import DeliveryRelay

logger = logging.getLogger(__name__)

MARKERS: dict[str, str] = {
    "live": "needs a real test org (target + admin identity)",
    "requires(*caps)": "skip unless the target has every capability (capabilities.Cap values)",
    "plan(*plans)": "skip unless the target org's plan is one of the given plans",
    "identities(*names)": "skip unless the given identities (author, approver, outsider, config_reader) are configured",
    "webapp": "needs the webapp under test (docker compose stack or external transport)",
    "docker": "needs a working docker daemon",
    "org_level": "touches org-level objects: full baseline reset in cleanup, plan counts not filtered",
    "tags(*tags)": "scenario tags used by --e2e-tags selection",
    "known_bug(id)": "covered by a known otterdog bug (scenarios/known_bugs.yaml): non-strict xfail",
    "differential": "records observations on base and head SUTs (--e2e-base-sut)",
    "scenario(id)": "the YAML scenario a test item runs",
    "slow": "long-running test",
    "offline": "runs without GitHub (local otterdog CLI and/or webapp with dummy credentials)",
    "web_ui": (
        "drives the GitHub web UI through otterdog (bot login with TOTP): needs the admin web credentials,"
        " --e2e-allow-web-ui, a trusted SUT and no SAML SSO (docs/web-ui-testing.md)"
    ),
}


@dataclass(frozen=True)
class OptionSpec:
    """One --e2e-* command line option."""

    flag: str
    help: str
    default: Any = None
    flag_option: bool = False

    @property
    def dest(self) -> str:
        """argparse destination (``--e2e-run-id`` -> ``e2e_run_id``)."""
        return self.flag.lstrip("-").replace("-", "_")


OPTIONS: tuple[OptionSpec, ...] = (
    OptionSpec(
        "--e2e-target",
        "one target: an instance (~/.config/otterdog-e2e/<instance>.env with E2E_PROFILE), a profile of targets/ or a"
        " target file [E2E_TARGET]",
    ),
    OptionSpec("--e2e-sut", f"SUT spec under test [E2E_SUT, default {DEFAULT_SUT}]", DEFAULT_SUT),
    OptionSpec("--e2e-base-sut", "base SUT for differential runs; 'auto' = merge base of the SUT [E2E_BASE_SUT]"),
    OptionSpec(
        "--e2e-reset-sut",
        f"trusted SUT used for resets [E2E_RESET_SUT, default {DEFAULT_RESET_SUT}]",
        DEFAULT_RESET_SUT,
    ),
    OptionSpec(
        "--e2e-tags",
        "comma separated tags: keep items carrying any of them (tests/unit and tests/offline are exempt; ANDed with"
        " --e2e-scenario) [E2E_TAGS]",
    ),
    OptionSpec(
        "--e2e-scenario",
        "comma separated fnmatch globs on scenario ids: keep items whose scenario matches any of them (every tier;"
        " ANDed with --e2e-tags) [E2E_SCENARIO]",
    ),
    OptionSpec("--e2e-artifacts", "artifacts root directory [E2E_ARTIFACTS]"),
    OptionSpec("--e2e-run-id", "reuse this run id (validated, must be new in the ledger) [E2E_RUN_ID]"),
    OptionSpec("--e2e-keep", "keep run resources after the session (no cleanup)", False, True),
    OptionSpec("--e2e-no-reset", "skip the baseline reset at first use", False, True),
    OptionSpec("--e2e-webapp-image", "use this prebuilt webapp image instead of building the SUT [E2E_WEBAPP_IMAGE]"),
    OptionSpec(
        "--e2e-change",
        "change under test: N or #N (an otterdog PR) or a change slug; the scenarios referencing it pass --e2e-tags and"
        " their expected deltas feed the differential report (default: N of a pr:N@<sha> --e2e-sut) [E2E_CHANGE]",
    ),
    OptionSpec("--e2e-strict-diff", "fail the session on unexpected differential deltas", False, True),
    OptionSpec("--e2e-no-http-cache", "disable the otterdog HTTP cache symlink", False, True),
    OptionSpec("--e2e-allow-remote-webapp", "allow a non-loopback external webapp / relay target", False, True),
    OptionSpec(
        "--e2e-trust-code",
        "full 40-hex sha of an untrusted SUT to install and run on the host (interactive terminal only, refused in CI)",
    ),
    OptionSpec(
        "--e2e-allow-web-ui",
        "allow the web-UI tier: otterdog logs in to github.com as the admin bot (password + TOTP; trusted SUTs only)"
        " [E2E_ALLOW_WEB_UI]",
        False,
        True,
    ),
)

TIER_DIRS = ("unit", "offline", "cli", "webhooks", "webapp", "enterprise", "differential", "web_ui", "adhoc")
LIVE_TIERS = frozenset({"cli", "webhooks", "webapp", "enterprise", "web_ui"})
# marker every item of a tier directory gets (gating relies on it even if a test author forgot it)
TIER_MARKERS: dict[str, str] = {
    "offline": "offline",
    "differential": "differential",
    **dict.fromkeys(LIVE_TIERS, "live"),
}
E2E_MARKERS = frozenset(name.split("(")[0] for name in MARKERS) - {"slow"}
NO_TARGET_REASON = "live test without a target: pass --e2e-target (or set E2E_TARGET)"
NO_BASE_REASON = "differential test without a base SUT: pass --e2e-base-sut (or set E2E_BASE_SUT)"
SKIP_PREFIX_RE = re.compile(r"^(Skipped|XFAIL|xfail):\s*")
FULL_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
# failures matching this are infrastructure problems (rate limits, network, lease), not product defects
INFRA_RE = re.compile(
    r"secondary rate limit|API rate limit exceeded|rate budget|Cannot connect to host|\(infra\)|LeaseBusy|"
    r"ConnectionError|ConnectTimeout|ReadTimeout|Max retries exceeded|Temporary failure in name resolution|"
    r"50[234] (Bad Gateway|Service Unavailable|Gateway Time-?out)",
    re.IGNORECASE,
)
FAILURE_MAX_CHARS = 2000
FAILURE_MAX_LINES = 30
SCENARIO_PARAM = "scenario"
IGNORED_MARKERS = frozenset({"parametrize", "usefixtures", "filterwarnings"})
# fixtures acting as a non-admin identity (gated like identities(...)); contributor = the author identity
FIXTURE_IDENTITIES: dict[str, str] = {
    "outsider_mutator": "outsider",
    "approver_mutator": "approver",
    "contributor_mutator": "author",
}
COMPOSE_FIXTURES = frozenset({"webapp_stack", "webapp_env", "dtrack_mock"})  # need the compose webapp stack
DTRACK_FIXTURE = "dtrack_mock"


def _runner_stdout() -> int | None:
    """On GitHub Actions, a duplicate of the process's original stdout (None elsewhere or when it cannot be made).

    The ``::add-mask::`` workflow commands of the redactor must reach the runner, which reads the real stdout; secrets
    are registered while pytest captures fd 1 (target loading, minted JWTs and installation tokens), so the lines would
    land in a capture buffer (ISO-03). pytest imports entry-point plugins before it starts capturing, so the duplicate
    made at import time is the runner's stdout."""
    if os.environ.get("GITHUB_ACTIONS") != "true":
        return None
    try:
        return os.dup(1)
    except OSError:
        return None


_RUNNER_STDOUT_FD = _runner_stdout()
_MASK_SINK_KEY = pytest.StashKey[Any]()
_REPORTS_KEY = pytest.StashKey[dict[str, pytest.TestReport]]()
_KNOWN_BUG_KEY = pytest.StashKey[str]()
_FIXED_BUGS_KEY = pytest.StashKey[list[str]]()
_SIGTERM_KEY = pytest.StashKey[Any]()


# --- configuration --------------------------------------------------------------------------------------------------
def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the --e2e-* options (environment fallbacks of context.OPTION_ENV)."""
    group = parser.getgroup("otterdog-e2e", "otterdog end-to-end harness")
    for option in OPTIONS:
        if option.flag_option:
            env_name = OPTION_ENV.get(option.dest)
            default = env_flag(os.environ, env_name) if env_name else False
            group.addoption(option.flag, action="store_true", default=default, dest=option.dest, help=option.help)
        else:
            env_name = OPTION_ENV.get(option.dest)
            default = os.environ.get(env_name, option.default) if env_name else option.default
            group.addoption(option.flag, action="store", default=default, dest=option.dest, help=option.help)


def pytest_configure(config: pytest.Config) -> None:
    """Register the markers of SPEC 15, check --e2e-trust-code (refused in CI, full sha only), install the SIGTERM
    handler and, on GitHub Actions, route ``::add-mask::`` lines to the runner's real stdout."""
    for name, description in MARKERS.items():
        config.addinivalue_line("markers", f"{name}: {description}")
    if not config.pluginmanager.hasplugin("timeout"):  # -p no:timeout: tier and scenario timeout marks stay valid
        config.addinivalue_line("markers", "timeout(seconds): pytest-timeout is disabled, the mark is ignored")
    trust_code = text_or_none(config.getoption("e2e_trust_code", None))
    if trust_code and in_ci(os.environ):
        raise pytest.UsageError("--e2e-trust-code is refused when CI is set (untrusted code never runs on CI hosts)")
    if trust_code and not FULL_SHA_RE.match(trust_code.lower()):
        raise pytest.UsageError("--e2e-trust-code needs the full 40-hex sha of the untrusted SUT to run on the host")
    _install_sigterm_handler(config)
    if _RUNNER_STDOUT_FD is not None:  # ::add-mask:: lines bypass pytest's capture (ISO-03)
        config.stash[_MASK_SINK_KEY] = redact.mask_sink()
        redact.set_mask_sink(redact.fd_mask_sink(_RUNNER_STDOUT_FD))


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore the previous SIGTERM handler and mask sink; close a context left open by an aborted session."""
    guard = config.stash.get(_SIGTERM_KEY, None)
    if guard is not None:
        guard.uninstall(config)
        del config.stash[_SIGTERM_KEY]
    context = peek_context(config)
    if context is not None and not context.closed:
        context.close()
    if _MASK_SINK_KEY in config.stash:  # the sink of an enclosing session (pytester) or the default
        redact.set_mask_sink(config.stash[_MASK_SINK_KEY])
        del config.stash[_MASK_SINK_KEY]


class InterruptGuard:
    """SIGTERM raises KeyboardInterrupt so finalizers (cleanup, webapp down, lease release) run (SEC-17).

    Only the first interruption is raised: GitHub cancels with SIGINT, then SIGTERM 7.5 s later; a second
    KeyboardInterrupt would abort the teardown in progress (and with it pytest_sessionfinish/unconfigure).
    """

    def __init__(self) -> None:
        """Nothing interrupted yet."""
        self.interrupted = False
        self.previous: Any = None

    def install(self, config: pytest.Config) -> bool:
        """Install the SIGTERM handler (main thread only) and listen for interruptions."""
        if threading.current_thread() is not threading.main_thread():
            return False
        self.previous = signal.signal(signal.SIGTERM, self.handle)
        config.pluginmanager.register(self, f"otterdog-e2e-interrupt-guard-{id(self)}")
        return True

    def uninstall(self, config: pytest.Config) -> None:
        """Restore the previous handler."""
        if threading.current_thread() is threading.main_thread():
            signal.signal(signal.SIGTERM, self.previous)
        if config.pluginmanager.is_registered(self):
            config.pluginmanager.unregister(self)

    def handle(self, signum: int, frame: Any) -> None:
        """First interruption: KeyboardInterrupt; later ones are logged while the cleanup runs."""
        if self.interrupted:
            logger.warning("signal %s ignored: cleanup in progress", signum)
            return
        self.interrupted = True
        raise KeyboardInterrupt(f"signal {signum}")

    def pytest_keyboard_interrupt(self, excinfo: pytest.ExceptionInfo[BaseException]) -> None:
        """A Ctrl-C/SIGINT is being handled: later SIGTERMs must not interrupt its cleanup."""
        self.interrupted = True


def _install_sigterm_handler(config: pytest.Config) -> None:
    """Install the InterruptGuard of this session."""
    guard = InterruptGuard()
    if guard.install(config):
        config.stash[_SIGTERM_KEY] = guard


# --- item helpers ---------------------------------------------------------------------------------------------------
def item_tier(item: pytest.Item) -> str | None:
    """Tier of an item from its path (``.../tests/<tier>/...``), None outside the tier directories."""
    parts = Path(item.path).parts
    for index in range(len(parts) - 2, -1, -1):
        if parts[index] == "tests" and parts[index + 1] in TIER_DIRS:
            return parts[index + 1]
    return None


def scenario_param(item: pytest.Item) -> Scenario | None:
    """The Scenario an item is parametrized with (tests calling collect.generate_scenario_tests)."""
    callspec = getattr(item, "callspec", None)
    return callspec.params.get(SCENARIO_PARAM) if callspec is not None else None


def item_scenario_id(item: pytest.Item) -> str | None:
    """Scenario id of an item: its scenario(id) marker, else the id of its Scenario parameter."""
    marker = item.get_closest_marker("scenario")
    if marker is not None and marker.args:
        return str(marker.args[0])
    scenario = scenario_param(item)
    return str(scenario.id) if scenario is not None and getattr(scenario, "id", None) else None


def item_case_id(item: pytest.Item) -> str | None:
    """``<scenario id>/<step>`` of an item running one case of a scenario (Scenario.cases), else None."""
    scenario = scenario_param(item)
    return str(scenario.case_id) if scenario is not None and getattr(scenario, "case", None) is not None else None


def item_priority(item: pytest.Item) -> str | None:
    """Priority of an item: its Scenario parameter's, else the ``priority`` keyword of its scenario(id) marker (Python
    tests), None when neither gives one (report budgets then count the item as P0)."""
    scenario = scenario_param(item)
    if scenario is not None and getattr(scenario, "priority", None):
        return str(scenario.priority)
    marker = item.get_closest_marker("scenario")
    value = marker.kwargs.get("priority") if marker is not None else None
    return value if isinstance(value, str) and value else None


def item_tags(item: pytest.Item) -> list[str]:
    """Union of the tags(*tags) markers of an item."""
    return list(dict.fromkeys(str(tag) for marker in item.iter_markers("tags") for tag in marker.args))


def marker_args(item: pytest.Item, name: str) -> list[str]:
    """Union of the positional arguments of every ``name`` marker of an item."""
    return list(dict.fromkeys(str(arg) for marker in item.iter_markers(name) for arg in marker.args))


def is_e2e(item: pytest.Item) -> bool:
    """True for items of the e2e tiers, items carrying an e2e marker and scenario items."""
    tier = item_tier(item)
    if tier is not None and tier != "unit":
        return True
    return scenario_param(item) is not None or any(marker.name in E2E_MARKERS for marker in item.iter_markers())


def is_live(item: pytest.Item) -> bool:
    """True for items marked live."""
    return item.get_closest_marker("live") is not None


# --- collection -----------------------------------------------------------------------------------------------------
def pytest_collection_modifyitems(session: pytest.Session, config: pytest.Config, items: list[pytest.Item]) -> None:
    """Tier/scenario marks, --e2e-tags/--e2e-scenario selection, collection-time skips and known-bug xfails; with live
    items, --showlocals and a list of targets are usage errors."""
    for item in items:
        _apply_item_marks(item)
    _deselect(config, items, E2EOptions.from_config(config))
    if not any(is_e2e(item) for item in items):
        return
    context = get_context(config)
    _change_spec(context)  # an invalid --e2e-change or invalid/conflicting references are usage errors
    bugs = context.known_bugs()
    for item in items:
        if is_e2e(item):
            _apply_known_bugs(item, bugs)
            _apply_collection_skips(item, context)
    _reject_showlocals(config, items)
    _reject_target_list(context, items)


def _apply_item_marks(item: pytest.Item) -> None:
    """Scenario marks (collect.apply_scenario_marks), the tier marker and the per-tier timeout (SPEC 2).

    The timeout of a live item covers its test call only (``func_only``): the first live item of a session would
    otherwise pay, within its own timer, for the session setup its fixtures trigger (lease wait, verification, the
    template clone, the first baseline reset); a timeout there would be cached by the session fixture and error every
    later item (F1). An explicit timeout marker of a live item is re-applied with ``func_only=True`` (unless it sets
    func_only itself).
    """
    if scenario_param(item) is not None:
        from otterdog_e2e.scenarios.collect import apply_scenario_marks

        apply_scenario_marks(item)
    tier = item_tier(item)
    if tier is None or tier == "unit":
        return
    marker = TIER_MARKERS.get(tier)
    if marker is not None and item.get_closest_marker(marker) is None:
        item.add_marker(marker)
    if not item.config.pluginmanager.hasplugin("timeout"):
        return  # pytest-timeout disabled: its marker is not registered (--strict-markers)
    from otterdog_e2e.scenarios.collect import TIER_TIMEOUTS

    timeout, existing, live = TIER_TIMEOUTS.get(tier), item.get_closest_marker("timeout"), is_live(item)
    if existing is None:
        if timeout is not None:
            item.add_marker(pytest.mark.timeout(timeout, func_only=True) if live else pytest.mark.timeout(timeout))
    elif live and "func_only" not in existing.kwargs:
        item.add_marker(pytest.mark.timeout(*existing.args, **existing.kwargs, func_only=True), append=False)


def _deselect(config: pytest.Config, items: list[pytest.Item], options: E2EOptions) -> None:
    """Keep the items passing --e2e-scenario AND --e2e-tags (module docstring); the others are deselected.

    The scenarios referencing the change under test are read only when an item fails the tags filter (such an item
    is an e2e item, so the session context exists anyway)."""
    if not options.tags and not options.scenario:
        return
    extra: list[tuple[str, ...]] = []

    def change_scenarios() -> tuple[str, ...]:
        """Ids of the scenarios referencing the change under test (read once)."""
        if not extra:
            spec = _change_spec(get_context(config)) if options.tags else None
            extra.append(tuple(spec.scenarios) if spec is not None else ())
        return extra[0]

    keep: list[pytest.Item] = []
    drop: list[pytest.Item] = []
    for item in items:
        (keep if _selected(item, options.tags, options.scenario, change_scenarios) else drop).append(item)
    if drop:
        config.hook.pytest_deselected(items=drop)
        items[:] = keep


def _change_spec(context: E2EContext) -> ChangeSpec | None:
    """context.change_spec(); UsageError for a malformed --e2e-change or invalid or conflicting references."""
    from otterdog_e2e.changes import ChangeError

    try:
        return context.change_spec()
    except ChangeError as exc:
        raise pytest.UsageError(f"--e2e-change: {exc}") from None


def tags_exempt(item: pytest.Item) -> bool:
    """True for items --e2e-tags never deselects: tests/unit, tests/offline and non-e2e items outside the tiers."""
    from otterdog_e2e.scenarios.collect import TAGS_EXEMPT_TIERS

    tier = item_tier(item)
    return tier in TAGS_EXEMPT_TIERS or (tier is None and not is_e2e(item))


def _selected(item: pytest.Item, tags: Sequence[str], globs: Sequence[str], extra: Callable[[], Sequence[str]]) -> bool:
    """collect.item_selected for one item (its scenario id, tags markers and tier exemption); ``extra`` gives the
    scenarios passing the tags filter like tagged items, read only when the item fails the filter otherwise."""
    from otterdog_e2e.scenarios.collect import item_selected

    scenario_id, exempt, case_id = item_scenario_id(item), tags_exempt(item), item_case_id(item)
    if item_selected(scenario_id, item_tags(item), globs=globs, tags=tags, tags_exempt=exempt, case_id=case_id):
        return True
    if not tags or scenario_id is None or not item_selected(scenario_id, (), globs=globs, case_id=case_id):
        return False
    return item_selected(scenario_id, (), globs=globs, tags=tags, extra_scenarios=extra(), case_id=case_id)


def known_bug_xfail(item: pytest.Item, reason: str) -> pytest.MarkDecorator:
    """The non-strict xfail of a known bug, scoped to the exception that reports the bug (``raises=``, BAT-03).

    A YAML scenario item accepts only KnownBugReproduced: its engine reports the bug's expected failures with
    pytest.xfail itself, so a strict step, a harness error or a failed cleanup stays a failure, and a run without the
    bug is an XPASS. A Python test accepts only AssertionError (its asserts report the bug): any other exception of the
    body (a GitHub error of the harness, a broken helper, a pytest-timeout or pytest.fail) stays a failure. A test
    whose bug surfaces as another exception declares its own ``xfail(raises=...)``, which takes precedence (the
    webapp and webhooks tiers always do)."""
    from otterdog_e2e.known_bugs import KnownBugReproduced

    if scenario_param(item) is not None:
        return pytest.mark.xfail(reason=reason, strict=False, raises=KnownBugReproduced)
    return pytest.mark.xfail(reason=reason, strict=False, raises=AssertionError)


def _apply_known_bugs(item: pytest.Item, bugs: dict[str, KnownBug]) -> None:
    """known_bug(id) markers and bugs listing the item's scenario become non-strict xfails (known_bug_xfail).

    Bugs with status ``fixed`` get no xfail at collection: their tests guard against regressions. pytest_runtest_setup
    adds the xfail back only when the SUT under test predates the bug's ``fixed_in`` (KnownBug.affects). The xfail of
    a known bug never covers the setup or teardown of an item (pytest_runtest_makereport): fixture errors and failed
    cleanups stay errors.
    """
    ids = marker_args(item, "known_bug")
    scenario_id = item_scenario_id(item)
    if scenario_id is not None:
        ids += [bug.id for bug in bugs.values() if scenario_id in bug.scenarios]
    for bug_id in dict.fromkeys(ids):
        bug = bugs.get(bug_id)
        if bug is not None and bug.fixed:
            item.stash.setdefault(_FIXED_BUGS_KEY, []).append(bug_id)
            continue
        reason = bug.xfail_reason if bug is not None else f"{bug_id}: not listed in known_bugs.yaml"
        item.add_marker(known_bug_xfail(item, reason))
        item.stash.setdefault(_KNOWN_BUG_KEY, bug_id)


def _xfail_fixed_bugs_on_older_suts(item: pytest.Item, context: E2EContext) -> None:
    """Fixed bugs of an item still xfail (non strict) when the SUT under test predates their ``fixed_in``."""
    fixed = item.stash.get(_FIXED_BUGS_KEY, None)
    if not fixed:
        return
    bugs, version = context.known_bugs(), context.sut_version()
    for bug_id in fixed:
        bug = bugs.get(bug_id)
        if bug is None or not bug.affects(version):
            continue
        reason = f"{bug.xfail_reason} (fixed in {bug.fixed_in}; SUT {version} predates the fix)"
        item.add_marker(known_bug_xfail(item, reason))
        item.stash.setdefault(_KNOWN_BUG_KEY, bug_id)


def _apply_collection_skips(item: pytest.Item, context: E2EContext) -> None:
    """Live items without target and differential items without base SUT are skipped at collection."""
    if is_live(item) and not context.options.target:
        item.add_marker(pytest.mark.skip(reason=NO_TARGET_REASON))
    if item.get_closest_marker("differential") is not None and not context.options.base_sut:
        item.add_marker(pytest.mark.skip(reason=NO_BASE_REASON))


def _reject_showlocals(config: pytest.Config, items: list[pytest.Item]) -> None:
    """--showlocals prints fixture values (tokens, keys) in tracebacks: refused when live items are selected."""
    if config.getoption("showlocals", False) and any(is_live(item) for item in items):
        raise pytest.UsageError("--showlocals (-l) is refused when live tests are selected: locals may hold secrets")


def _reject_target_list(context: E2EContext, items: list[pytest.Item]) -> None:
    """A session loads the env files of ONE org: a list of targets (a comma, @all, @<list>) in --e2e-target or
    E2E_TARGET is refused when live items are selected (unit and offline sessions never load a target)."""
    target = context.options.target or ""
    if ("," in target or target.startswith("@")) and any(is_live(item) for item in items):
        raise pytest.UsageError(
            f"--e2e-target names one target (an instance, a profile or a target file), got {target!r}: a session"
            " loads the env files of one org; run several targets with `otterdog-e2e run --target a,b` (one session"
            " per target)"
        )


# --- gating ---------------------------------------------------------------------------------------------------------
@pytest.hookimpl(tryfirst=True)
def pytest_runtest_setup(item: pytest.Item) -> None:
    """Skip before any fixture when requires/plan/identities/docker/webapp/rate budget are not satisfied; xfail the
    items of fixed known bugs on SUTs that predate the fix (runs before the skipping plugin evaluates xfail marks)."""
    if not is_e2e(item) or _statically_skipped(item):
        return
    context = get_context(item.config)
    reason = gate_reason(item, context)
    if reason:
        pytest.skip(reason)
    _xfail_fixed_bugs_on_older_suts(item, context)


def _statically_skipped(item: pytest.Item) -> bool:
    """True when a skip marker (or a literal-True skipif) will skip the item anyway."""
    if item.get_closest_marker("skip") is not None:
        return True
    return any(marker.args and all(arg is True for arg in marker.args) for marker in item.iter_markers("skipif"))


def gate_reason(item: pytest.Item, context: E2EContext) -> str | None:
    """Skip reason of an item, None when it may run; fails the item when the live session cannot be built."""
    if not is_live(item):
        return _local_gate(item, context)
    context.ensure_live()
    if context.live_error or not context.is_live:
        pytest.fail(f"live session setup failed: {context.live_error or context.live_problem()}", pytrace=False)
    checks = (
        _capability_gate,
        _plan_gate,
        _identity_gate,
        _docker_gate,
        _webapp_gate,
        _compose_gate,
        _web_ui_gate,
        _rate_gate,
    )
    for check in checks:
        reason = check(item, context)
        if reason:
            return reason
    return None


def _local_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """Non-live items: only docker can be checked (webapp/docker markers, requires("docker"))."""
    if item.get_closest_marker("web_ui") is not None:
        return "web_ui tests drive github.com: mark the test live (tests/web_ui)"
    caps = marker_args(item, "requires")
    other = [cap for cap in caps if cap != "docker"]
    if other:
        return f"capabilities {', '.join(other)} need a live target (mark the test live)"
    needs_docker = "docker" in caps or any(item.get_closest_marker(name) for name in ("docker", "webapp"))
    if needs_docker and not context.docker_available():
        return "docker is not available"
    return None


def _capability_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """requires(*caps): every capability must be present."""
    missing = context.require_capabilities().missing(marker_args(item, "requires"))
    return f"missing capabilities: {', '.join(missing)}" if missing else None


def _plan_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """plan(*plans): the org plan must be listed by every plan marker."""
    plan = context.require_verified().plan
    for marker in item.iter_markers("plan"):
        allowed = [str(arg) for arg in marker.args]
        if allowed and plan not in allowed:
            return f"needs plan {' | '.join(allowed)} (target plan: {plan})"
    return None


def fixture_identities(item: pytest.Item) -> list[str]:
    """Identities an item needs: its identities(...) markers and the identity mutator fixtures it uses."""
    names = set(getattr(item, "fixturenames", ()))
    from_fixtures = [identity for fixture, identity in FIXTURE_IDENTITIES.items() if fixture in names]
    return list(dict.fromkeys([*marker_args(item, "identities"), *from_fixtures]))


def _identity_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """identities(*names) and identity mutator fixtures: every identity must be configured."""
    missing = [name for name in fixture_identities(item) if name not in context.identities]
    return f"missing identities: {', '.join(missing)} (set their token env vars)" if missing else None


def _docker_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """docker marker: the daemon must answer."""
    if item.get_closest_marker("docker") is not None and not context.docker_ok:
        return "docker is not available"
    return None


def _webapp_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """webapp marker: a usable transport, a ready App, docker for compose and a config_reader identity for untrusted
    SUTs (pr:, and sha:/branch: specs that resolve untrusted: the resolution may fetch the upstream mirror)."""
    if item.get_closest_marker("webapp") is None:
        return None
    transport = context.require_target().webapp.transport
    if transport not in ("relay", "external"):
        return f"webapp transport is {transport!r}"
    if not context.app_ok and context.extras.get("app_unsafe"):
        # a safety refusal (safety.verify_app) is a configuration error to fix, never a quiet skip
        pytest.fail(str(context.extras.get("app_reason")), pytrace=False)
    if not context.app_ok:
        return f"GitHub App not ready: {context.extras.get('app_reason') or 'unknown reason'}"
    if transport == "relay" and not context.docker_ok:
        return "docker is not available (webapp compose stack)"
    if "config_reader" not in context.identities and context.sut_trusted("head") is False:
        return (
            f"untrusted SUT {context.options.sut}: the webapp tier needs a config_reader identity"
            " (E2E_CONFIG_READER_TOKEN) for OTTERDOG_CONFIG_TOKEN"
        )
    return None


def _compose_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """Compose-only fixtures (webapp_stack, webapp_env, dtrack_mock) need the relay transport and docker."""
    used = sorted(COMPOSE_FIXTURES & set(getattr(item, "fixturenames", ())))
    if not used:
        return None
    transport = context.require_target().webapp.transport
    if transport != "relay":
        return f"{', '.join(used)} need(s) the compose webapp stack (webapp transport is {transport!r})"
    if not context.docker_ok:
        return "docker is not available (webapp compose stack)"
    return None


def _web_ui_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """web_ui marker: context.web_ui_problems() must be empty (re-evaluated per item: a failed login blocks the gate
    during the session)."""
    if item.get_closest_marker("web_ui") is None:
        return None
    problems = context.web_ui_problems()
    return "web-UI tier: " + "; ".join(problems) if problems else None


def _rate_gate(item: pytest.Item, context: E2EContext) -> str | None:
    """Skip live items when an identity's core budget is below E2E_MIN_RATE_REMAINING."""
    rates = context.rate_remaining()
    threshold = context.min_rate_threshold()
    low = {name: remaining for name, remaining in rates.items() if remaining < threshold}
    if not low:
        return None
    details = ", ".join(f"{name} {remaining}" for name, remaining in sorted(low.items()))
    return f"github rate budget: core remaining {details} < {threshold}"


# --- SUT preparation ------------------------------------------------------------------------------------------------
# fixtures (anywhere in an item's fixture closure) that install a SUT role / build its webapp image
SUT_FIXTURE_ROLES: dict[str, tuple[str, ...]] = {
    "sut": ("head",),
    "base_sut": ("base",),
    "reset_sut": ("reset",),
    "sut_pair": ("base", "head"),
}
IMAGE_FIXTURE_ROLES: dict[str, tuple[str, ...]] = {"webapp_image": ("head",)}


def suts_to_prepare(items: Sequence[pytest.Item]) -> tuple[list[str], list[str]]:
    """(SUT roles to install, roles whose webapp image to build) for the e2e items that are not statically skipped
    (``sut_pair`` only counts for items marked differential: the fixture refuses the others)."""
    roles: dict[str, None] = {}
    images: dict[str, None] = {}
    for item in items:
        if not is_e2e(item) or _statically_skipped(item):
            continue
        names = set(getattr(item, "fixturenames", ()))
        if item.get_closest_marker("differential") is None:
            names.discard("sut_pair")
        for fixtures, found in ((SUT_FIXTURE_ROLES, roles), (IMAGE_FIXTURE_ROLES, images)):
            for fixture, needed in fixtures.items():
                if fixture in names:
                    found.update(dict.fromkeys(needed))
    order = ("head", "base", "reset")
    return [role for role in order if role in roles], [role for role in order if role in images]


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session: pytest.Session) -> None:
    """Install the SUTs (and build the images) the selected items need before the first item runs.

    pytest-timeout times fixture setup too, so without this the first item of a tier would pay a cold install or
    image build within its own timeout (or a scenario item when --e2e-scenario deselects the warm-up items). Failures
    are only reported here: the fixtures raise them again for the items that need the SUT.
    """
    option = session.config.option
    if option.collectonly or getattr(option, "setupplan", False) or session.testsfailed or not session.items:
        return
    context = peek_context(session.config)
    if context is None:
        return
    if needs_dtrack_mock(session.items):
        context.extras["dtrack_mock"] = True  # E2EContext.webapp_deployment starts the stack with the mock
    roles, images = suts_to_prepare(session.items)
    if images and not context.docker_available():
        images = []
    timings: dict[str, float] = {}
    for what, role, prepare in [
        *(("SUT", role, context.installed) for role in roles),
        *(("webapp image", role, context.image_for) for role in images),
        *(("Playwright Firefox", role, context.web_browsers) for role in web_browser_roles(session.items, context)),
    ]:
        timings[f"{what}:{role}"] = _prepare_one(session, context, what, role, prepare)
    if needs_live_session(session.items, context):
        timings["live session"] = _go_live_before_items(session, context)
    if timings:
        context.write_run_info(sut_prepare_seconds=timings)


def needs_live_session(items: Sequence[pytest.Item], context: E2EContext) -> bool:
    """True when a runnable live item is selected and a target is given (its live session is then built before the
    first item, outside any item timer: E2E_LEASE_WAIT may well exceed a tier timeout)."""
    return bool(context.options.target) and any(
        is_e2e(item) and is_live(item) and not _statically_skipped(item) for item in items
    )


def _go_live_before_items(session: pytest.Session, context: E2EContext) -> float:
    """context.ensure_live() before the first item (failures are stored in live_error and reported by the gate of
    every live item); returns its duration in seconds."""
    started = time.monotonic()
    _terminal_line(session, f"otterdog-e2e: verifying the target {context.options.target} and taking the org lease ...")
    context.ensure_live()
    if context.live_error:
        _terminal_line(session, f"otterdog-e2e: live session unavailable: {context.live_error}")
    return round(time.monotonic() - started, 3)


def needs_dtrack_mock(items: Sequence[pytest.Item]) -> bool:
    """True when a runnable e2e item uses the dtrack_mock fixture (the compose stack then starts the mock with the
    webapp instead of recreating it later)."""
    return any(
        is_e2e(item) and not _statically_skipped(item) and DTRACK_FIXTURE in getattr(item, "fixturenames", ())
        for item in items
    )


def web_browser_roles(items: Sequence[pytest.Item], context: E2EContext) -> list[str]:
    """SUT roles whose Playwright Firefox the selected web_ui items need (trusted SUTs, --e2e-allow-web-ui given)."""
    if not context.options.allow_web_ui:
        return []
    if not any(item.get_closest_marker("web_ui") and not _statically_skipped(item) for item in items):
        return []
    return [role for role in ("head", "reset") if context.sut_trusted(role) is True]


def _prepare_one(session: pytest.Session, context: E2EContext, what: str, role: str, prepare: Any) -> float:
    """Run one preparation step (reported on the terminal); returns its duration in seconds."""
    started = time.monotonic()
    _terminal_line(session, f"otterdog-e2e: preparing the {role} {what} ({_role_spec(context, role)}) ...")
    try:
        prepare(role)
    except Exception as exc:  # noqa: BLE001 - the fixtures report it again for the items that need this SUT
        _terminal_line(session, f"otterdog-e2e: {role} {what} unavailable: {describe_error(exc)}")
        logger.warning("preparing the %s %s failed: %s", role, what, describe_error(exc))
    else:
        logger.info("%s %s ready in %.1f s", role, what, time.monotonic() - started)
    return round(time.monotonic() - started, 3)


def _role_spec(context: E2EContext, role: str) -> str:
    """The spec of a SUT role for messages (the raw option when it cannot be derived yet)."""
    try:
        return context.spec_for(role)
    except Exception:  # noqa: BLE001 - message only: the preparation step reports the real error
        return str(context.options.base_sut if role == "base" else role)


def _terminal_line(session: pytest.Session, text: str) -> None:
    """Write a line to the terminal outside output capturing (no-op without the terminal reporter)."""
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is None:
        return
    capture = session.config.pluginmanager.get_plugin("capturemanager")
    guard = capture.global_and_fixture_disabled() if capture is not None else contextlib.nullcontext()
    with guard:
        reporter.write_line(redact.REDACTOR(text))


# --- reporting ------------------------------------------------------------------------------------------------------
@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Generator[None, Any, Any]:
    """Redact longrepr and captured sections; append a results.jsonl line after the teardown phase."""
    report = yield
    _unmask_fixture_errors(item, call, report)
    redact_report(report)
    reports = item.stash.setdefault(_REPORTS_KEY, {})
    reports[report.when] = report
    context = peek_context(item.config)
    if report.when == "teardown" and context is not None:
        context.append_result(result_line(item, reports, context))
    return report


def _unmask_fixture_errors(item: pytest.Item, call: pytest.CallInfo[None], report: pytest.TestReport) -> None:
    """A known bug's xfail explains the test body only: an error in the setup or teardown of a known-bug item (a
    fixture, a failed cleanup leaving objects behind) that pytest's skipping plugin turned into an xfail is reported
    as the error it is (BAT-03). An imperative pytest.xfail() keeps its outcome."""
    if report.when == "call" or item.stash.get(_KNOWN_BUG_KEY, None) is None:
        return
    if (
        not hasattr(report, "wasxfail")
        or call.excinfo is None
        or isinstance(call.excinfo.value, pytest.xfail.Exception)
    ):
        return
    report.outcome = "failed"
    del report.wasxfail


def redact_report(report: pytest.TestReport) -> None:
    """Replace secrets in longrepr (kept structured unless something was redacted), sections and wasxfail."""
    redactor = redact.REDACTOR
    longrepr = report.longrepr
    if isinstance(longrepr, tuple) and len(longrepr) == 3:
        report.longrepr = (longrepr[0], longrepr[1], redactor(str(longrepr[2])))
    elif longrepr is not None:
        text = str(longrepr)
        redacted = redactor(text)
        if redacted != text:
            report.longrepr = redacted
    report.sections = [(title, redactor(content)) for title, content in report.sections]
    wasxfail = getattr(report, "wasxfail", None)
    if isinstance(wasxfail, str):
        report.wasxfail = redactor(wasxfail)


def final_outcome(reports: dict[str, pytest.TestReport]) -> tuple[str, pytest.TestReport | None]:
    """(outcome, decisive report): passed|failed|error|skipped|xfailed|xpassed over the setup/call/teardown phases."""
    setup, call, teardown = (reports.get(when) for when in ("setup", "call", "teardown"))
    if setup is not None and setup.failed:
        return "error", setup
    if setup is not None and setup.skipped:
        return ("xfailed" if hasattr(setup, "wasxfail") else "skipped"), setup
    if call is not None and call.failed and not hasattr(call, "wasxfail"):
        return "failed", call
    if teardown is not None and teardown.failed:
        return "error", teardown  # a failed teardown (cleanup) outweighs a passed, skipped or xfailed call (BAT-03)
    if call is not None:
        if hasattr(call, "wasxfail"):
            return ("xpassed" if call.passed else "xfailed"), call
        if call.skipped:
            return "skipped", call
    return "passed", call or setup or teardown


def result_line(item: pytest.Item, reports: dict[str, pytest.TestReport], context: E2EContext) -> dict[str, Any]:
    """One results.jsonl line (keys read by report.build_summary)."""
    outcome, decisive = final_outcome(reports)
    phases = {when: round(report.duration, 3) for when, report in reports.items()}
    failure_text = _failure_text(decisive) if outcome in ("failed", "error") else None
    return {
        "nodeid": item.nodeid,
        "outcome": outcome,
        "when": decisive.when if decisive is not None else None,
        "duration": round(sum(phases.values()), 3),
        "phases": phases,
        "tier": item_tier(item),
        "markers": sorted({marker.name for marker in item.iter_markers()} - IGNORED_MARKERS),
        "scenario": item_scenario_id(item),
        "priority": item_priority(item),
        "tags": item_tags(item),
        "sut": context.sut_label(),
        "reason": _reason(decisive) if outcome in ("skipped", "xfailed", "xpassed") else None,
        "failure": _short(failure_text) if failure_text else None,
        "infra": bool(failure_text and INFRA_RE.search(failure_text)),
        "known_bug": item.stash.get(_KNOWN_BUG_KEY, None),
        "rate": context.rate_remaining(),
        "finished_at": datetime.now(UTC).isoformat(),
    }


def _reason(report: pytest.TestReport | None) -> str | None:
    """Skip reason (from the longrepr tuple) or xfail reason of a report."""
    if report is None:
        return None
    wasxfail = getattr(report, "wasxfail", None)
    if isinstance(wasxfail, str) and wasxfail:
        return wasxfail
    if isinstance(report.longrepr, tuple) and len(report.longrepr) == 3:
        return SKIP_PREFIX_RE.sub("", str(report.longrepr[2]))
    return None


def _failure_text(report: pytest.TestReport | None) -> str | None:
    """Redacted crash message (or longrepr text) of a failed report."""
    if report is None or report.longrepr is None:
        return None
    crash = getattr(report.longrepr, "reprcrash", None)
    message = getattr(crash, "message", None)
    return redact.REDACTOR(str(message) if message else report.longreprtext)


def _short(text: str) -> str:
    """At most FAILURE_MAX_LINES trailing lines / FAILURE_MAX_CHARS characters."""
    lines = text.strip("\n").splitlines()
    return "\n".join(lines[-FAILURE_MAX_LINES:])[-FAILURE_MAX_CHARS:]


@pytest.hookimpl(trylast=True)
def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    """Write the differential report and summary.md, close the context (lease, scrub); leaks fail the session.

    A ``--collect-only`` session runs nothing: it writes no summary and leaves no artifacts directory behind.
    """
    context = peek_context(session.config)
    if context is None:
        return
    collect_only = bool(session.config.option.collectonly)
    try:
        if not collect_only:
            _write_differential(session, context)
            _write_summary(context, session)
    finally:
        context.close()
    if collect_only:
        _discard_unused_artifacts(context)
    if (context.leaks or context.scrub_error) and session.exitstatus in (
        pytest.ExitCode.OK,
        pytest.ExitCode.NO_TESTS_COLLECTED,
    ):
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


UNUSED_ARTIFACTS = frozenset({"run.json", "leaks.json"})  # all a session that ran nothing writes


def _discard_unused_artifacts(context: E2EContext) -> None:
    """Remove the run's artifacts directory when it holds nothing but run.json and the scrub's leaks.json."""
    directory = context.artifacts_dir
    if not directory.is_dir() or directory.is_symlink() or context.leaks or context.scrub_error:
        return
    if all(entry.is_file() and entry.name in UNUSED_ARTIFACTS for entry in directory.iterdir()):
        shutil.rmtree(directory, ignore_errors=True)


def _write_differential(session: pytest.Session, context: E2EContext) -> None:
    """differential.{md,json} when both sides recorded observations; --e2e-strict-diff fails on unexpected deltas."""
    base_file, head_file = (context.artifacts_dir / OBSERVATIONS_DIR / f"{role}.jsonl" for role in ("base", "head"))
    if not (base_file.is_file() and head_file.is_file()):
        return
    from otterdog_e2e.differential import compare
    from otterdog_e2e.observe import load_observations

    base, head = load_observations(base_file), load_observations(head_file)
    spec = _change_spec_or_none(context)
    report = compare(
        base,
        head,
        base_label=_side_label(base, "base"),
        head_label=_side_label(head, "head"),
        expected=spec.expected_deltas if spec is not None else (),
    )
    (context.artifacts_dir / "differential.md").write_text(redact.REDACTOR(report.to_markdown()), encoding="utf-8")
    text = json.dumps(report.to_json(), indent=2, sort_keys=True, default=str)
    (context.artifacts_dir / "differential.json").write_text(redact.REDACTOR(text) + "\n", encoding="utf-8")
    unexpected = report.unexpected()
    if unexpected and context.options.strict_diff:
        logger.error("%d unexpected differential delta(s) (--e2e-strict-diff)", len(unexpected))
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def _change_spec_or_none(context: E2EContext) -> ChangeSpec | None:
    """The ChangeSpec of the change under test, None without a change or when its references are invalid (logged)."""
    try:
        return context.change_spec()
    except Exception as exc:  # noqa: BLE001 - every delta then counts as unexpected
        logger.error("invalid references of the change under test: %s", exc)
        return None


def _side_label(observations: list[Any], default: str) -> str:
    """SUT label recorded in the first observation of a side."""
    return str(observations[0].sut) if observations else default


def _write_summary(context: E2EContext, session: pytest.Session) -> None:
    """summary.md (and $GITHUB_STEP_SUMMARY when set); run.json gets the finish time and exit status."""
    context.write_run_info(finished_at=datetime.now(UTC).isoformat(), exitstatus=int(session.exitstatus))
    if not context.artifacts_dir.is_dir():
        return
    from otterdog_e2e import report

    try:
        summary = redact.REDACTOR(report.build_summary(context.artifacts_dir))
    except Exception as exc:  # noqa: BLE001 - a fallback summary is written instead
        logger.error("could not build summary.md: %s", exc)
        summary = f"# otterdog-e2e run {context.run_ctx.run_id}\n\nsummary unavailable: {redact.REDACTOR(str(exc))}\n"
    (context.artifacts_dir / "summary.md").write_text(summary, encoding="utf-8")
    step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if step_summary:
        with Path(step_summary).open("a", encoding="utf-8") as handle:
            handle.write(summary + "\n")


# --- fixture helpers ------------------------------------------------------------------------------------------------
def _context(request: pytest.FixtureRequest) -> E2EContext:
    """The session context (created on first use)."""
    return get_context(request.config)


def _live(request: pytest.FixtureRequest) -> E2EContext:
    """The live context; a test that is not live (or whose live setup failed) fails clearly."""
    context = _context(request)
    context.ensure_live()
    if not context.is_live:
        reason = context.live_error or context.live_problem() or "the test is not marked live"
        pytest.fail(f"live fixture {request.fixturename!r} unavailable: {reason}", pytrace=False)
    return context


def _call(what: str, factory: Any, *args: Any, **kwargs: Any) -> Any:
    """Run a context factory; ContextError becomes a clean fixture failure."""
    try:
        return factory(*args, **kwargs)
    except ContextError as exc:
        pytest.fail(f"{what}: {exc}", pytrace=False)


# --- session fixtures (SPEC 15) -------------------------------------------------------------------------------------
@pytest.fixture(scope="session")
def harness(request: pytest.FixtureRequest) -> HarnessSettings:
    """HarnessSettings of the session."""
    return _context(request).settings


@pytest.fixture(scope="session")
def run_ctx(request: pytest.FixtureRequest) -> RunContext:
    """RunContext of the session."""
    return _context(request).run_ctx


@pytest.fixture(scope="session")
def e2e(request: pytest.FixtureRequest) -> E2EContext:
    """The E2EContext (live part built)."""
    return _live(request)


@pytest.fixture(scope="session")
def target(e2e: E2EContext) -> Target:
    """The Target of --e2e-target."""
    return e2e.require_target()


@pytest.fixture(scope="session")
def identities(e2e: E2EContext) -> dict[str, Identity]:
    """Resolved identities (isolation checked)."""
    return dict(e2e.identities)


@pytest.fixture(scope="session")
def verified_org(e2e: E2EContext) -> VerifiedOrg:
    """The VerifiedOrg every mutating fixture depends on."""
    return e2e.require_verified()


@pytest.fixture(scope="session")
def oracle(e2e: E2EContext) -> Oracle:
    """Read-only Oracle of the test org."""
    return e2e.oracle()


@pytest.fixture(scope="session")
def mutator(e2e: E2EContext) -> Mutator:
    """Admin Mutator."""
    return e2e.mutator("admin")


@pytest.fixture(scope="session")
def mutators(e2e: E2EContext) -> dict[str, Mutator]:
    """Mutators per configured identity."""
    return e2e.mutators()


def _identity_mutator(request: pytest.FixtureRequest, identity: str) -> Mutator:
    """Mutator of ``identity`` (the identity gate skips the item before this when it is not configured)."""
    context = _live(request)
    mutator: Mutator = _call(str(request.fixturename), context.mutator, identity)
    return mutator


@pytest.fixture(scope="session")
def outsider_mutator(request: pytest.FixtureRequest) -> Mutator:
    """Mutator of the outsider identity (not an org member)."""
    return _identity_mutator(request, "outsider")


@pytest.fixture(scope="session")
def approver_mutator(request: pytest.FixtureRequest) -> Mutator:
    """Mutator of the approver identity (approval team member)."""
    return _identity_mutator(request, "approver")


@pytest.fixture(scope="session")
def contributor_mutator(request: pytest.FixtureRequest) -> Mutator:
    """Mutator of the contributor: the author identity (org member, contributors team only)."""
    return _identity_mutator(request, "author")


@pytest.fixture(scope="session")
def capabilities(e2e: E2EContext) -> Capabilities:
    """Capabilities of the target."""
    return e2e.require_capabilities()


@pytest.fixture(scope="session")
def sut(request: pytest.FixtureRequest) -> InstalledCli:
    """InstalledCli of --e2e-sut (host for trusted, docker image CLI for untrusted)."""
    return _call("sut", _context(request).installed, "head")


@pytest.fixture(scope="session")
def reset_sut(e2e: E2EContext) -> InstalledCli:
    """InstalledCli of the trusted reset SUT."""
    return _call("reset_sut", e2e.installed, "reset")


@pytest.fixture(scope="session")
def base_sut(request: pytest.FixtureRequest) -> InstalledCli:
    """InstalledCli of --e2e-base-sut."""
    return _call("base_sut", _context(request).installed, "base")


@pytest.fixture(scope="session")
def template_ref(e2e: E2EContext) -> TemplateRef:
    """TemplateRef of the SUT under test (resolution only, no install)."""
    return e2e.template_for("head")


@pytest.fixture(scope="session")
def base_template_ref(e2e: E2EContext) -> TemplateRef:
    """TemplateRef of the base SUT (resolution only, no install)."""
    return e2e.template_for("base")


@pytest.fixture(scope="session")
def change_spec(request: pytest.FixtureRequest) -> ChangeSpec | None:
    """ChangeSpec of the change under test (--e2e-change, default: N of a pr:N@<sha> SUT; None without one)."""
    return _context(request).change_spec()


@pytest.fixture(scope="session")
def renderer(e2e: E2EContext, template_ref: TemplateRef) -> OrgConfigRenderer:
    """OrgConfigRenderer of the session."""
    return e2e.renderer(template_ref)


@pytest.fixture(scope="session")
def workspace(e2e: E2EContext, template_ref: TemplateRef) -> ConfigWorkspace:
    """Session ConfigWorkspace (in scratch)."""
    return e2e.workspace("sut", template_ref)


@pytest.fixture(scope="session")
def otterdog(e2e: E2EContext, sut: InstalledCli, workspace: ConfigWorkspace) -> OtterdogCli:
    """OtterdogCli of the SUT under test."""
    return e2e.cli(sut, workspace, name="sut")


@pytest.fixture(scope="session")
def reset_cli(e2e: E2EContext, reset_sut: InstalledCli, template_ref: TemplateRef) -> OtterdogCli:
    """OtterdogCli of the trusted reset SUT (same template as the SUT, artifacts under reset/)."""
    return e2e.cli(reset_sut, e2e.workspace("reset", template_ref), name="reset", artifacts="reset")


@pytest.fixture(scope="session")
def baseline(e2e: E2EContext, reset_cli: OtterdogCli, renderer: OrgConfigRenderer) -> Iterator[BaselineManager]:
    """BaselineManager (first use performs reset() unless --e2e-no-reset); the run's leftovers are swept at session
    end unless --e2e-keep."""
    manager = e2e.baseline_manager(reset_cli, renderer)
    if not e2e.options.no_reset:
        manager.reset()
    yield manager
    e2e.restore_web_settings(manager)  # web-UI tier safety net: no-op unless a restore is pending
    if not e2e.options.keep:
        e2e.sweep_own_run()


@pytest.fixture(scope="session")
def scenario_engine(
    e2e: E2EContext,
    otterdog: OtterdogCli,
    renderer: OrgConfigRenderer,
    capabilities: Capabilities,
    baseline: BaselineManager,
) -> ScenarioEngine:
    """Live ScenarioEngine (step known bugs read from the session's known_bugs.yaml)."""
    from otterdog_e2e.scenarios.engine import ScenarioEngine

    engine = ScenarioEngine(
        cli=otterdog,
        renderer=renderer,
        oracle=e2e.oracle(),
        run_ctx=e2e.run_ctx,
        capabilities=capabilities,
        baseline=baseline,
        variables=e2e.scenario_variables(),
    )
    engine.known_bugs = e2e.known_bugs()
    return engine


@pytest.fixture(scope="session")
def app_auth(e2e: E2EContext) -> AppAuth:
    """AppAuth of the e2e App."""
    return _call("app_auth", e2e.app_auth)


@pytest.fixture(scope="session")
def installation_id(e2e: E2EContext) -> int:
    """Installation id of the App on the test org (preflight checked)."""
    return _call("installation_id", e2e.installation_id)


@pytest.fixture(scope="session")
def webapp_image(request: pytest.FixtureRequest) -> BuiltImage:
    """BuiltImage of the webapp under test."""
    return _call("webapp_image", _context(request).image_for, "head")


@pytest.fixture(scope="session")
def webapp(
    e2e: E2EContext, baseline: BaselineManager, template_ref: TemplateRef
) -> Iterator[WebappStack | ExternalWebapp]:
    """Running webapp (stack up, baseline on config repo main, otterdog.json, init, wait_ready)."""
    deployment = _call("webapp", e2e.start_webapp, baseline, template_ref)
    try:
        yield deployment
    finally:
        e2e.stop_webapp(deployment)


@pytest.fixture(scope="session")
def webapp_api(webapp: WebappStack | ExternalWebapp) -> WebappApi:
    """WebappApi of the running webapp."""
    from otterdog_e2e.webapp.api import WebappApi

    return WebappApi(webapp.base_url)


@pytest.fixture(scope="session")
def relay(e2e: E2EContext, webapp: WebappStack | ExternalWebapp, installation_id: int) -> Iterator[DeliveryRelay]:
    """DeliveryRelay forwarding App deliveries since the webapp was ready (compose and external transports)."""
    delivery_relay = e2e.start_relay(webapp)
    try:
        yield delivery_relay
    finally:
        delivery_relay.stop()


@pytest.fixture(scope="session")
def config_flow(
    e2e: E2EContext, relay: DeliveryRelay, baseline: BaselineManager, app_auth: AppAuth
) -> Iterator[ConfigRepoFlow]:
    """ConfigRepoFlow on the org config repo (the relay implies the running webapp), guarded by the baseline."""
    flow = e2e.config_flow(baseline, relay=relay, bot_login=app_auth.bot_login)
    yield flow
    if not e2e.options.keep:
        flow.cleanup()


@pytest.fixture(scope="session")
def injector(e2e: E2EContext, webapp: WebappStack | ExternalWebapp) -> WebhookInjector:
    """WebhookInjector on the webapp receiver."""
    from otterdog_e2e.webhooks.injector import WebhookInjector

    return WebhookInjector(webapp.webhook_url, e2e.require_app_credentials().webhook_secret)


@pytest.fixture(scope="session")
def webapp_stack(webapp: WebappStack | ExternalWebapp) -> WebappStack:
    """The compose WebappStack of the session (stop_service, start_service, restart_webapp, dtrack); the compose gate
    skips items using it with another transport."""
    from otterdog_e2e.webapp.stack import WebappStack

    if not isinstance(webapp, WebappStack):
        pytest.fail("webapp_stack needs the compose webapp stack (webapp transport relay)", pytrace=False)
    return webapp


# --- function fixtures ----------------------------------------------------------------------------------------------
@pytest.fixture
def sut_pair(request: pytest.FixtureRequest) -> SutPair:
    """(base, head) SutSide pair (tests marked differential only): live sides for live tests, offline otherwise."""
    if request.node.get_closest_marker("differential") is None:
        pytest.fail("sut_pair is only available to tests marked differential", pytrace=False)
    live = request.node.get_closest_marker("live") is not None
    context = _live(request) if live else _context(request)
    return _call("sut_pair", context.sut_pair, live=live)


@pytest.fixture
def scenario_vars(request: pytest.FixtureRequest) -> dict[str, Any]:
    """Jinja variables of the current scenario (live or offline base variables + the scenario's variables)."""
    live = request.node.get_closest_marker("live") is not None
    variables = _live(request).scenario_variables() if live else _context(request).offline_variables()
    scenario = scenario_param(request.node)
    if scenario is not None:
        variables.update(getattr(scenario, "variables", None) or {})
    return variables


@pytest.fixture
def fresh_workspace(request: pytest.FixtureRequest) -> Iterator[ConfigWorkspace]:
    """A new ConfigWorkspace for one test (the test org for live tests, the offline org otherwise)."""
    context = _context(request)
    name = context.unique_name(request.node.name)
    if request.node.get_closest_marker("live") is not None:
        template: TemplateRef = request.getfixturevalue("template_ref")
        yield _live(request).workspace(name, template)
    else:
        yield context.offline_workspace(name)


@pytest.fixture
def webapp_env(webapp_stack: WebappStack) -> Iterator[Callable[[Mapping[str, str]], None]]:
    """``apply(env)``: recreate the webapp with environment overrides (WebappStack.restart_webapp, e.g.
    GITHUB_ADMIN_TEAMS with spaces); the defaults are restored after the test. An overridden GITHUB_WEBHOOK_ENDPOINT
    moves ``webapp_stack.webhook_url``: re-point ``relay.forward_url`` / ``injector.endpoint_url`` while it holds."""
    applied: list[dict[str, str]] = []

    def apply(env: Mapping[str, str]) -> None:
        """Recreate the webapp with exactly ``env`` as overrides."""
        webapp_stack.restart_webapp(env)
        applied.append(dict(env))

    yield apply
    if applied and webapp_stack.env_overrides:
        webapp_stack.restart_webapp({})


@pytest.fixture
def webapp_otterdog_json(
    e2e: E2EContext, webapp: WebappStack | ExternalWebapp, template_ref: TemplateRef
) -> Iterator[Callable[[Mapping[str, Any]], None]]:
    """``apply(organization)``: publish otterdog.json with org-entry overrides (admin_teams / approval_teams; None
    drops a key so the webapp's GITHUB_*_TEAMS apply) and reload the webapp; the run's otterdog.json is restored and
    reloaded after the test."""
    applied: list[dict[str, Any]] = []

    def apply(organization: Mapping[str, Any]) -> None:
        """Publish the overrides and make the webapp read them."""
        e2e.publish_otterdog_json(template_ref, organization=organization)
        applied.append(dict(organization))
        e2e.reload_webapp(webapp)

    yield apply
    if applied:
        e2e.publish_otterdog_json(template_ref)
        e2e.reload_webapp(webapp)


@pytest.fixture
def dtrack_mock(e2e: E2EContext, webapp: WebappStack | ExternalWebapp) -> Iterator[DtrackMock]:
    """The Dependency-Track mock of the compose stack (DEPENDENCY_TRACK_URL of the webapp), emptied and answering 200
    before and after the test."""
    client: DtrackMock = _call("dtrack_mock", e2e.dtrack_mock, webapp)
    client.clear()
    client.set_response(200)
    yield client
    try:
        client.set_response(200)
        client.clear()
    except Exception as exc:  # noqa: BLE001 - teardown of a mock: the next test resets it again
        logger.warning("could not reset the Dependency-Track mock: %s", describe_error(exc))


@pytest.fixture
def blueprints(e2e: E2EContext, webapp_case: WebappCase, relay: DeliveryRelay) -> Iterator[BlueprintHelper]:
    """BlueprintHelper of the test (definitions, /internal/init|check, statuses, remediation PRs, workflows); stale
    definitions of finished runs are removed first, everything the helper created is cleaned up after the test
    (before the webapp_case cleanup), unless --e2e-keep."""
    helper: BlueprintHelper = _call("blueprints", e2e.blueprint_helper, webapp_case, relay=relay)
    try:
        helper.sweep_stale()
    except Exception as exc:  # noqa: BLE001 - leftovers only matter for global definitions of the same type
        logger.warning("could not remove stale blueprint definitions: %s", describe_error(exc))
    yield helper
    if not e2e.options.keep:
        helper.cleanup()


@pytest.fixture
def webapp_case(
    request: pytest.FixtureRequest,
    e2e: E2EContext,
    config_flow: ConfigRepoFlow,
    webapp_api: WebappApi,
    baseline: BaselineManager,
    reset_cli: OtterdogCli,
) -> Iterator[WebappCase]:
    """Isolation of one webapp test (F10): main == baseline before, PRs/branches/main/run objects reset after."""
    case = e2e.begin_webapp_case(config_flow, webapp_api, baseline)
    yield case
    if not e2e.options.keep:
        org_level = request.node.get_closest_marker("org_level") is not None
        e2e.end_webapp_case(case, baseline=baseline, reset_cli=reset_cli, org_level=org_level)
