"""Live CLI tier helpers (SPEC 19): the scenario runner with mid-scenario probes and an OtterdogCli factory.

A probe is a Python check that YAML cannot express, run between two steps of a scenario while the objects of the
earlier steps still exist. ``run_scenario`` splits such a scenario after the probe's step: the steps up to it run
without cleanup, then the probe, then the remaining steps; the scenario's cleanup always runs once at the end.
Steps are declarative (config(step k) = baseline + fragments(step k)), so splitting changes nothing for the engine.

Known bugs of steps: when the steps before the probe end with expected failures only (a step ``known_bug`` the SUT
still has), ``engine.run`` xfails (ScenarioOutcome.raise_for_failures): the cleanup runs, the probe and the remaining
steps do not, and the item is XFAIL. Put a known-bug step after the probe when the probe must run.

Timeouts are scenario data: a scenario with a probe declares its own ``timeout`` (cli.repo.webhook: 960 s, the probe
waits up to 60 s for the hook and 300 s for a delivery), org_level scenarios get the tier timeout plus
collect.ORG_LEVEL_EXTRA_TIMEOUT (their cleanup is a full baseline reset). Regressions of unreleased fixes declare
``fixed_in``: ScenarioEngine.skip_reason skips them on older SUTs.

Probes:
- ``cli.repo.webhook`` after ``update`` (C-REPO-WEBHOOK / H-REPO-HOOK-PING): an explicit ping
  (POST /repos/{org}/{repo}/hooks/{id}/pings) must appear in the hook's delivery log within 300 s (delivery logs lag
  "a few minutes", GH-04). The hook URL lies under naming.HOOK_BASE (reserved TLD .invalid): GitHub logs a failed
  delivery but never reaches a server.

Helpers of the command tests (tests/cli/test_commands_*.py), all bound to run objects only:
- ``live_config`` (LiveConfig): renders baseline + fragments, applies them with the SUT under test
  (``apply -f -n -r e2e-<run>-*``) in a workspace of its own and, when anything was applied (or ``touch()`` was
  called after a mutator write), removes the run's objects after the test (guarded ``apply -d`` with the trusted reset
  CLI, ``E2EContext.remove_run_objects``);
- ``config_repo`` (ConfigRepo): the session's org config repository (``target.config_repo_for(run_ctx)``): run
  branches with a configuration of the test, pull requests from them, branches otterdog creates (``open-pr``); after
  the test every pull request is closed, every branch deleted and the default branch holds the baseline again;
- ``shown_objects`` / ``shown`` (fixtures returning parse_shown_objects / shown_value): the object blocks printed by
  ``show``, ``show-live``, ``list-apps`` and ``list-advisories -d`` (``kind[key="value", parent=p] {`` ... ``}``,
  ``app['slug'] {``) and the Python value of one of their raw fields;
- ``cli_lines`` (cli_text): the normalized output of a command (normalize_text: no ANSI codes, unboxed messages).

Test modules cannot import this module at run time (``--import-mode=importlib``): they get the helpers through these
fixtures and import the classes under TYPE_CHECKING only.
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.github.oracle import deliveries_since
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import ConfigFragments

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.scenarios.engine import ScenarioEngine, ScenarioOutcome
    from otterdog_e2e.scenarios.model import Scenario
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.template import TemplateRef

logger = logging.getLogger(__name__)

HOOK_DELIVERY_TIMEOUT = 300.0  # GitHub delivery logs lag "a few minutes" (GH-04)
HOOK_DELIVERY_INTERVAL = 10.0
HOOK_LOOKUP_TIMEOUT = 60.0


@dataclass(frozen=True)
class ProbeEnv:
    """What a probe may use: the read-only oracle, the admin mutator, the run context and the scenario variables."""

    oracle: Oracle
    mutator: Mutator
    run_ctx: RunContext
    variables: Mapping[str, Any]


@dataclass(frozen=True)
class Probe:
    """A Python check run after the step named ``after`` (AssertionError or WaitTimeoutError on failure)."""

    after: str
    check: Callable[[ProbeEnv], None]


def hook_ping_deliveries(oracle: Oracle, repo: str, hook_id: int) -> list[dict[str, Any]]:
    """The 'ping' deliveries of a repository hook (newest first, as GitHub lists them)."""
    return [delivery for delivery in oracle.repo_hook_deliveries(repo, hook_id) if delivery.get("event") == "ping"]


def webhook_ping_probe(env: ProbeEnv) -> None:
    """The managed hook exists and an explicit ping shows up as a new 'ping' delivery within 300 s."""
    repo = f"{env.run_ctx.prefix}-hooks"
    url = f"{env.run_ctx.hook_base}repo-hook"
    hook = waiting.wait_until(
        lambda: env.oracle.repo_hook_by_url(repo, url),
        timeout=HOOK_LOOKUP_TIMEOUT,
        interval=5.0,
        what=f"webhook {url} of {repo}",
    )
    hook_id = int(hook["id"])
    seen = {delivery.get("id") for delivery in hook_ping_deliveries(env.oracle, repo, hook_id)}
    logger.info("hook %s of %s: %d ping delivery(ies) before the explicit ping", hook_id, repo, len(seen))
    # only deliveries after GitHub's time of the ping count: the creation ping logged late is not this one (BAT-10)
    pinged_at = env.mutator.ping_repo_hook(repo, hook_id)
    try:
        deliveries = waiting.poll(
            lambda: deliveries_since(hook_ping_deliveries(env.oracle, repo, hook_id), pinged_at),
            until=lambda found: any(delivery.get("id") not in seen for delivery in found),
            timeout=HOOK_DELIVERY_TIMEOUT,
            interval=HOOK_DELIVERY_INTERVAL,
            what=f"a new 'ping' delivery of hook {hook_id} ({url}) after POST .../pings",
        )
    except waiting.WaitTimeoutError as exc:  # GitHub accepted the ping (204): a missing log entry is delivery lag
        raise AssertionError(f"ping delivery not observed within {HOOK_DELIVERY_TIMEOUT:.0f} s (infra): {exc}") from exc
    new = [delivery for delivery in deliveries if delivery.get("id") not in seen]
    assert all(delivery.get("event") == "ping" for delivery in new)
    logger.info("hook %s: ping delivered, status %s", hook_id, new[0].get("status"))


PROBES: Mapping[str, Probe] = {
    "cli.repo.webhook": Probe(after="update", check=webhook_ping_probe),
}


def split_scenario(scenario: Scenario, after: str) -> tuple[Scenario, Scenario]:
    """(steps up to and including ``after``, the remaining steps) of a scenario; ValueError for an unknown step."""
    names = [step.name for step in scenario.steps]
    if after not in names:
        raise ValueError(f"scenario {scenario.id} has no step {after!r} (steps: {names})")
    index = names.index(after) + 1
    return (
        dataclasses.replace(scenario, steps=scenario.steps[:index]),
        dataclasses.replace(scenario, steps=scenario.steps[index:]),
    )


def run_with_probe(
    engine: ScenarioEngine, scenario: Scenario, probe: Probe, env_factory: Callable[[], ProbeEnv]
) -> ScenarioOutcome:
    """Run the steps up to the probe, the probe, then the remaining steps; one cleanup at the end, always.

    A failing cleanup fails the test unless an earlier failure is already propagating (it is then logged).
    """
    head, tail = split_scenario(scenario, probe.after)
    failed = False
    try:
        outcome = engine.run(head, cleanup=False)
        probe.check(env_factory())
        if tail.steps:
            outcome = engine.run(tail, cleanup=False)
        return outcome
    except BaseException:
        failed = True
        raise
    finally:
        if scenario.cleanup == "auto":
            _cleanup(engine, scenario, failed=failed)


def _cleanup(engine: ScenarioEngine, scenario: Scenario, *, failed: bool) -> None:
    """engine.cleanup(scenario); its error is raised only when nothing failed before."""
    try:
        engine.cleanup(scenario)
    except Exception as exc:
        if not failed:
            raise AssertionError(f"cleanup of {scenario.id} failed: {type(exc).__name__}: {exc}") from exc
        logger.error("cleanup of %s failed after an earlier failure: %s", scenario.id, type(exc).__name__)


@pytest.fixture
def run_scenario(request: pytest.FixtureRequest, scenario_engine: ScenarioEngine) -> Callable[[Scenario], None]:
    """Run a live scenario (with its probe, if any); skips when the target cannot run it, fails on any failure."""

    def env_factory() -> ProbeEnv:
        """Probe environment (the admin mutator is only built when a probe runs)."""
        e2e: E2EContext = request.getfixturevalue("e2e")
        return ProbeEnv(
            oracle=request.getfixturevalue("oracle"),
            mutator=request.getfixturevalue("mutator"),
            run_ctx=e2e.run_ctx,
            variables=scenario_engine.variables,
        )

    def run(scenario: Scenario) -> None:
        """Skip, run (engine or probe split) and let ScenarioFailedError fail the test."""
        reason = scenario_engine.skip_reason(scenario)  # capabilities, plan, SUT older than fixed_in
        if reason:
            pytest.skip(reason)
        probe = PROBES.get(scenario.id)
        if probe is None:
            outcome = scenario_engine.run(scenario)
        else:
            outcome = run_with_probe(scenario_engine, scenario, probe, env_factory)
        if outcome.skipped:
            pytest.skip(outcome.skipped)

    return run


@pytest.fixture
def make_cli(e2e: E2EContext, sut: InstalledCli) -> Callable[[ConfigWorkspace], OtterdogCli]:
    """OtterdogCli factory for a workspace (the SUT under test, admin identity, scratch named after the workspace)."""

    def build(workspace: ConfigWorkspace) -> OtterdogCli:
        """A CLI bound to ``workspace``."""
        return e2e.cli(sut, workspace, name=f"ws-{workspace.root.name}")

    return build


# --- helpers of the command tests (tests/cli/test_commands_*.py) ----------------------------------------------------
STATE_TIMEOUT = 90.0  # GitHub reads after a write (contents, refs, repositories) can lag a few seconds
STATE_INTERVAL = 3.0
TAIL = 3000  # characters of command output quoted by assertion messages
# a shown object block: ``kind[key="value", parent_kind=parent] {`` (show, show-live), ``settings {``, ``app['x'] {``
SHOWN_HEADER_RE = re.compile(
    r"^(?P<indent>\s*)(?P<kind>[a-z_]+)"
    r'(?:\[(?P<key>[a-z_]+)="(?P<value>[^"]*)"(?:, (?P<parent_kind>[a-z_]+)=(?P<parent>[^\]]+))?\]'
    r"|\['(?P<label>[^']*)'\])? \{$"
)
SHOWN_FIELD_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][\w\-]*)\s+= (?P<value>.*?)\s*$")


def tail(text: str, limit: int = TAIL) -> str:
    """The end of a command output for assertion messages."""
    return text[-limit:]


def cli_text(result: CliResult) -> str:
    """Normalized output of a command (otterdog_e2e.otterdog.output.normalize_text: no ANSI codes, boxed messages
    unboxed as ``Error: <message>`` with left-trimmed continuation lines, progress bars replaced)."""
    return normalize_text(result.output)


@dataclass(frozen=True)
class ShownObject:
    """One object block of ``show``/``show-live`` like output: kind, header key/value, parent and the raw values of
    its first-level fields (``key = <raw value>``; nested dicts and list items are not parsed)."""

    kind: str
    key: str | None
    value: str | None
    parent_kind: str | None
    parent: str | None
    label: str | None
    fields: Mapping[str, str]


def parse_shown_objects(text: str) -> list[ShownObject]:
    """Every object block of a normalized output: a header ``<indent>kind[...] {`` up to the line ``<indent>}``."""
    lines = text.splitlines()
    objects: list[ShownObject] = []
    index = 0
    while index < len(lines):
        match = SHOWN_HEADER_RE.match(lines[index])
        if match is None:
            index += 1
            continue
        indent = match.group("indent")
        closing = f"{indent}}}"
        fields: dict[str, str] = {}
        index += 1
        while index < len(lines) and lines[index].rstrip() != closing:
            found = SHOWN_FIELD_RE.match(lines[index])
            if found is not None and len(found.group("indent")) == len(indent) + 2:
                fields[found.group("key")] = found.group("value")
            index += 1
        objects.append(
            ShownObject(
                kind=match.group("kind"),
                key=match.group("key"),
                value=match.group("value"),
                parent_kind=match.group("parent_kind"),
                parent=match.group("parent"),
                label=match.group("label"),
                fields=fields,
            )
        )
        index += 1
    return objects


def shown_value(raw: str | None) -> Any:
    """Python value of a raw shown field: quoted strings unquoted, null/true/false/integers converted, else raw."""
    if raw is None:
        return None
    raw = raw.rstrip(",")
    if len(raw) >= 2 and raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    literals: dict[str, Any] = {"null": None, "true": True, "false": False}
    if raw in literals:
        return literals[raw]
    return int(raw) if re.fullmatch(r"-?\d+", raw) else raw


def wait_state(
    fn: Callable[[], Any], until: Callable[[Any], bool], what: str, *, timeout: float = STATE_TIMEOUT
) -> Any:
    """Poll a GitHub read until ``until`` holds; the last value is returned when it never does (the caller asserts)."""
    return waiting.poll(fn, until=until, timeout=timeout, interval=STATE_INTERVAL, what=what, raise_on_timeout=False)


@dataclass
class LiveConfig:
    """baseline + fragments applied with the SUT under test from a workspace of its own (``live_config`` fixture).

    Every object the configurations add must be a run object (``name(slug)``, ``const(slug)``, ``hook_url(slug)``);
    applies are filtered to this run's repositories (``-r e2e-<run>-*``). The fixture removes the run's objects after
    the test when ``apply`` ran or ``touch()`` recorded another write (a repository created by the mutator).
    """

    e2e: E2EContext
    baseline: BaselineManager
    renderer: OrgConfigRenderer
    run_ctx: RunContext
    oracle: Oracle
    workspace: ConfigWorkspace
    cli: OtterdogCli
    touched: bool = False

    def name(self, slug: str) -> str:
        """``e2e-<run>-<slug>``."""
        return self.run_ctx.name(slug)

    def const(self, slug: str) -> str:
        """``E2E_<RUN>_<SLUG>``."""
        return self.run_ctx.const(slug)

    def hook_url(self, slug: str) -> str:
        """``https://otterdog-e2e.invalid/<run>/<slug>``."""
        return self.run_ctx.hook_url(slug)

    def render(self, *repositories: str, plan: str | None = None, **fragments: Sequence[str]) -> str:
        """The baseline plus ``repositories`` (and other ConfigFragments keys, e.g. ``settings=[...]``)."""
        snippets = {"repositories": list(repositories), **{key: list(values) for key, values in fragments.items()}}
        return self.renderer.render(ConfigFragments.from_mapping(snippets), plan=plan)

    def write(self, text: str, *, suffix: str = "") -> None:
        """Write the org configuration (``suffix``: another side, e.g. ``-BASE``)."""
        if suffix:
            self.workspace.write_base_config(text, suffix=suffix)
        else:
            self.workspace.write_org_config(text)

    def touch(self) -> None:
        """Record a write outside ``apply`` (the run's objects are removed after the test)."""
        self.touched = True

    def apply(self, text: str, *, what: str) -> CliResult:
        """Write ``text`` and ``apply -f -n -r e2e-<run>-*`` it; AssertionError unless it exits 0 without failed
        patches."""
        self.write(text)
        self.touch()
        result = self.cli.apply(repo_filter=self.run_ctx.repo_filter())
        result.assert_ok(what)
        failed = result.apply().failed_patches
        assert not failed, f"{what}: failed patches {failed}\n{tail(result.output)}"
        return result

    def wait_repo(self, name: str, *, present: bool = True) -> dict[str, Any] | None:
        """The repository once it exists (``present``) or None once it is gone."""
        return wait_state(
            lambda: self.oracle.repo(name),
            lambda repo: (repo is not None) == present,
            f"repository {name} {'present' if present else 'absent'}",
        )

    def wait_file(self, repo: str, path: str, expected: str | None, *, ref: str | None = None) -> str | None:
        """The content of ``repo:path`` once it equals ``expected`` (None: once the file is gone)."""
        return wait_state(
            lambda: self.oracle.file_content(repo, path, ref=ref),
            lambda content: content == expected,
            f"{repo}:{path} {'absent' if expected is None else 'updated'}",
        )

    def cleanup(self) -> None:
        """Baseline-only configuration + guarded ``apply -d -r e2e-<run>-*`` with the trusted reset CLI."""
        self.e2e.remove_run_objects(self.baseline, self.baseline.reset_cli)


@pytest.fixture
def live_config(
    request: pytest.FixtureRequest,
    e2e: E2EContext,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    run_ctx: RunContext,
    oracle: Oracle,
    template_ref: TemplateRef,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
) -> Iterator[LiveConfig]:
    """LiveConfig of the test; the run's objects are removed afterwards when the test wrote any (unless --e2e-keep)."""
    workspace = e2e.workspace(e2e.unique_name(f"live-{request.node.name}"), template_ref)
    config = LiveConfig(e2e, baseline, renderer, run_ctx, oracle, workspace, make_cli(workspace))
    yield config
    if config.touched and not e2e.options.keep:
        config.cleanup()


@dataclass
class ConfigRepo:
    """The session's org config repository and what a test changes in it (``config_repo`` fixture).

    ``branch(slug, text)`` commits a configuration to the run branch ``e2e/<run>/<slug>`` (from the default branch),
    ``pull(branch)`` opens a pull request from it, ``track_ref(ref)`` registers a branch otterdog creates
    (``otterdog/e2e-<run>-<slug>`` of open-pr); ``restore()`` (always called after the test) closes the pull requests,
    deletes the branches and commits the baseline to the default branch when it holds something else.
    """

    baseline: BaselineManager
    oracle: Oracle
    mutator: Mutator
    target: Target
    run_ctx: RunContext
    pulls: list[int] = field(default_factory=list)
    refs: list[str] = field(default_factory=list)

    @property
    def repo(self) -> str:
        """Name of the org config repository of the session."""
        return self.target.config_repo_for(self.run_ctx)

    @property
    def path(self) -> str:
        """Path of the org definition in the repository (``otterdog/<org>.jsonnet``)."""
        return f"otterdog/{self.target.org}.jsonnet"

    @property
    def default_branch(self) -> str:
        """Default branch of the repository."""
        return self.oracle.default_branch(self.repo) or "main"

    def remote(self, ref: str | None = None) -> str | None:
        """The org definition on ``ref`` (default branch when None), None when absent."""
        return self.oracle.file_content(self.repo, self.path, ref=ref)

    def wait_remote(self, expected: str, *, ref: str | None = None) -> str | None:
        """The org definition once it equals ``expected`` (the last value read when it never does)."""
        return wait_state(lambda: self.remote(ref), lambda content: content == expected, f"{self.repo}:{self.path}")

    def head(self, branch: str | None = None) -> dict[str, Any] | None:
        """Head commit (``git/commits``: sha, message, ...) of ``branch`` (default branch when None)."""
        sha = self.oracle.branch_sha(self.repo, branch or self.default_branch)
        commit = self.oracle.git_commit(self.repo, sha) if sha else None
        return {**commit, "sha": sha} if commit is not None else None

    def set_default(self, text: str, message: str) -> None:
        """Commit ``text`` as the org definition of the default branch (no-op when it holds it already)."""
        if self.remote() == text:
            return
        self.mutator.commit_files(self.repo, self.default_branch, {self.path: text}, message)
        content = self.wait_remote(text)
        assert content == text, f"{self.repo}:{self.path} does not hold the committed configuration"

    def branch(self, slug: str, text: str) -> str:
        """Run branch ``e2e/<run>/<slug>`` from the default branch with ``text`` as the org definition."""
        name = self.run_ctx.branch(slug)
        sha = self.oracle.branch_sha(self.repo, self.default_branch)
        assert sha, f"{self.repo} has no default branch head"
        self.track_ref(f"heads/{name}")
        self.mutator.create_branch(self.repo, name, sha)
        self.mutator.commit_files(self.repo, name, {self.path: text}, f"otterdog-e2e {self.run_ctx.run_id}: {slug}")
        content = self.wait_remote(text, ref=name)
        assert content == text, f"{self.repo}@{name} does not hold the committed configuration"
        return name

    def pull(self, branch: str, title: str) -> int:
        """Pull request from ``branch`` to the default branch; its number."""
        pull = self.mutator.create_pull(self.repo, head=branch, base=self.default_branch, title=title)
        number = int(pull["number"])
        self.pulls.append(number)
        return number

    def track_ref(self, ref: str) -> None:
        """Delete ``ref`` (``heads/<branch>``, a run branch) after the test."""
        if ref not in self.refs:
            self.refs.append(ref)

    def track_pull(self, number: int) -> None:
        """Close pull request ``number`` (one otterdog opened) after the test."""
        if number not in self.pulls:
            self.pulls.append(number)

    def restore(self) -> None:
        """Close the pull requests, delete the branches, put the baseline back on the default branch (every step is
        attempted; the errors are raised together at the end)."""
        errors: list[str] = []

        def attempt(what: str, step: Callable[[], None]) -> None:
            """Run one cleanup step, recording its error."""
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - every cleanup step runs, failures are reported together
                errors.append(f"{what}: {type(exc).__name__}: {exc}")

        for number in self.pulls:
            attempt(f"close #{number}", functools.partial(self.mutator.close_pull, self.repo, number))
        for ref in self.refs:
            attempt(f"delete {ref}", functools.partial(self.mutator.delete_ref, self.repo, ref))
        message = f"otterdog-e2e {self.run_ctx.run_id}: restore the baseline"
        attempt("restore the baseline", lambda: self.set_default(self.baseline.text(), message))
        if errors:
            raise AssertionError(f"config repository cleanup of {self.repo} failed: {'; '.join(errors)}")


@pytest.fixture
def config_repo(
    e2e: E2EContext, baseline: BaselineManager, oracle: Oracle, mutator: Mutator, target: Target, run_ctx: RunContext
) -> Iterator[ConfigRepo]:
    """ConfigRepo of the test: the default branch holds the baseline before, and again after the test."""
    repo = ConfigRepo(baseline, oracle, mutator, target, run_ctx)
    repo.set_default(baseline.text(), f"otterdog-e2e {run_ctx.run_id}: baseline before a config repository test")
    yield repo
    if not e2e.options.keep:
        repo.restore()


@pytest.fixture(scope="session")
def cli_lines() -> Callable[[CliResult], str]:
    """``cli_text``: the normalized output of a command."""
    return cli_text


@pytest.fixture(scope="session")
def shown_objects() -> Callable[[str], list[ShownObject]]:
    """``parse_shown_objects``: the object blocks of a normalized output."""
    return parse_shown_objects


@pytest.fixture(scope="session")
def shown() -> Callable[[str | None], Any]:
    """``shown_value``: the Python value of a raw shown field."""
    return shown_value
