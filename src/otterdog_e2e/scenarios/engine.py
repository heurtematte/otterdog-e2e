"""Scenario engines: the live engine and the differential runner (SPEC 12.3, F6).

Outcome dataclasses live here; scenarios.offline imports them (this module imports OfflineEngine only lazily, inside
DifferentialRunner, to avoid an import cycle).

Live step semantics (SPEC 12.1): render + write -> validate (only if given) -> plan -> apply (only if plan.expect is
``changes`` and apply is not null) -> state -> converge (only after a successful apply). The first failing phase
aborts the remaining steps, cleanup always runs, every failure is reported. Plans use ``-r <run prefix>-*`` unless the
scenario is org_level; "changes"/"noop" look only at this run's objects (``RunContext.needles()``; org_level adds the
org ``settings`` object); counts are the raw ``Plan:`` numbers when the plan has no foreign changes (or org_level),
otherwise they are recomputed from this run's objects. ``apply -d`` in a step is guarded by
BaselineManager.check_removals on the step's own plan (same filter, same config); cleanup uses the trusted reset CLI
through BaselineManager.guarded_apply (or reset() for org_level scenarios). When the last removal of the run's objects
failed (BaselineManager.run_objects_left: an earlier scenario or test left objects behind), the scenario's cleanup
runs first, so the run-wide needles of its plans never count another item's leftovers.

Step options: the diff flags of a step's plan and apply (runner.DiffOptions: ``repo_filter``, update flags,
``only_secrets``, ``verbose``) reach ``plan``/``apply`` (offline: ``local-plan``); a live ``repo_filter`` must start
with the run prefix unless org_level (SafetyError), the apply uses the plan's filter unless it has its own, and
converge plans with the apply's filter and no update flag (forced updates never converge). ``validate.verbose`` runs
``validate -v``.

Known bugs per step (``known_bug`` of a step): while the bug affects the SUT (known_bugs.KnownBug.affects; an id
missing from known_bugs.yaml counts as affecting), the expectation failures of that step are recorded as
``ScenarioOutcome.expected_failures`` instead of failures and the next steps run; infra problems and harness errors
(exceptions such as render errors or safety refusals) stay failures. A known-bug step that passes is recorded in
``unexpected_passes``. ``raise_for_failures`` raises ScenarioFailedError for failures, else ``pytest.xfail`` with the
bug when expected failures exist (KnownBugNotReproducedWarning for unexpected passes). The engines read the bugs from
their ``known_bugs`` attribute, else from the known_bugs.yaml found above the scenario file (inside its project).
"""

from __future__ import annotations

import dataclasses
import functools
import logging
import re
import time
import warnings
from collections.abc import Callable, Iterable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from otterdog_e2e import waiting
from otterdog_e2e.capabilities import plans_at_least
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.otterdog import output as od_output
from otterdog_e2e.otterdog.runner import DiffOptions
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.scenarios import checks as checks_module
from otterdog_e2e.scenarios.checks import wait_for_checks
from otterdog_e2e.scenarios.model import render_step

if TYPE_CHECKING:
    from otterdog_e2e.capabilities import Capabilities
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.known_bugs import KnownBug
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.observe import ObservationRecorder
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import ApplyResult, PlanObject, PlanResult
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.scenarios.checks import CheckResult
    from otterdog_e2e.scenarios.model import ApplySpec, CommandSpec, PlanSpec, Scenario, StepSpec, ValidateSpec
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.template import TemplateRef

logger = logging.getLogger(__name__)

PHASES = ("render", "validate", "plan", "apply", "state", "converge", "cleanup")
LIVE_PHASES = ("render", "validate", "plan", "apply", "state", "converge")
SUT_ROLES = ("base", "head")
STATE_TIMEOUT = 60.0
STATE_INTERVAL = 5.0
CONVERGE_ATTEMPTS = 4  # plans: immediately, then after 5, 10 and 20 s (waiting.CONVERGE_BACKOFF)
OUTPUT_TAIL_LINES = 30
# a load error ("failed to load configuration") is a validation error: otterdog prints "Validation failed" for it
VALIDATION_ERROR_MARKERS = ("Planning aborted due to validation errors", "failed to load configuration")
# exceptions turned into phase failures (ScenarioError/RenderError are ValueErrors; SafetyError, GitHubError and
# NotImplementedError are RuntimeErrors); anything else is a harness bug and propagates (after cleanup)
PHASE_ERRORS: tuple[type[Exception], ...] = (ValueError, RuntimeError, OSError)
INFRA_PREFIX = checks_module.INFRA_PREFIX
KNOWN_BUGS_FILE = "known_bugs.yaml"  # scenarios/known_bugs.yaml (context.KNOWN_BUGS_FILE)
PROJECT_MARKER = "pyproject.toml"  # the search for known_bugs.yaml stops at the project root
_UNKNOWN_EXPECTED_RE = re.compile(r"unknown propert", re.IGNORECASE)  # a contains expecting the warning
_SOURCE_SUFFIX_RE = re.compile(r"\s{2,}[\w.\-]+\.py:\d+\s*$")  # RichHandler's ``file.py:line`` column (OC-08)
_MAX_LISTED = 5


class KnownBugNotReproducedWarning(UserWarning):
    """A step declaring a known bug that affects the SUT passed: the bug may be fixed (update known_bugs.yaml)."""


@dataclass
class StepOutcome:
    """What happened in one step: CLI results per phase, check results, whether it ran in negative mode; its known
    bug (``known_bug``, when it affects the SUT), whether its failures were expected (``expected_failure``) and the
    problems that came from exceptions (``errors``: harness errors, never expected)."""

    name: str
    results: dict[str, CliResult] = field(default_factory=dict)
    checks: list[CheckResult] = field(default_factory=list)
    negative: bool = False
    notes: list[str] = field(default_factory=list)
    durations: dict[str, float] = field(default_factory=dict)
    failed_phase: str | None = None
    known_bug: str | None = None
    expected_failure: bool = False
    errors: list[str] = field(default_factory=list)


@dataclass
class ScenarioOutcome:
    """Outcome of a scenario: its steps, every failure message, the skip reason (if skipped), the failures of steps
    whose known bug affects the SUT (``expected_failures``, with the bug of each such step in ``expected_bugs``) and
    the known-bug steps that passed (``unexpected_passes``)."""

    scenario: str
    steps: list[StepOutcome] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skipped: str | None = None
    expected_failures: list[str] = field(default_factory=list)
    expected_bugs: dict[str, str] = field(default_factory=dict)  # step name -> "<bug id>: <title>"
    unexpected_passes: list[str] = field(default_factory=list)
    _warned: bool = field(default=False, init=False, repr=False, compare=False)

    @property
    def ok(self) -> bool:
        """True when nothing failed (a skipped scenario is ok; expected failures are not failures)."""
        return not self.failures

    @property
    def infra(self) -> bool:
        """True when a failure is attributed to infrastructure (rate limits, timeouts, network)."""
        return any(INFRA_PREFIX in failure for failure in self.failures)

    @property
    def xfail_reason(self) -> str | None:
        """Reason of the expected failure of the scenario: known-bug steps failed and nothing else did (else None)."""
        if self.failures or not self.expected_failures:
            return None
        bugs = "; ".join(f"{reason} (step {name!r})" for name, reason in self.expected_bugs.items())
        more = len(self.expected_failures) - 1
        return REDACTOR(f"{bugs}: {self.expected_failures[0]}" + (f" (+{more} more)" if more > 0 else ""))

    def summary(self) -> str:
        """Redacted multi-line report: failures, expected failures, then the notes (output tails) of failed steps."""
        lines = [f"scenario {self.scenario} failed ({len(self.failures)} failure(s)):"]
        lines += [f"  - {failure}" for failure in self.failures]
        if self.expected_failures:
            lines.append(f"expected failures (known bugs: {', '.join(sorted(set(self.expected_bugs.values())))}):")
            lines += [f"  - {failure}" for failure in self.expected_failures]
        for step in self.steps:
            if step.failed_phase is not None:
                lines += [f"step {step.name!r}: {note}" for note in step.notes]
        return REDACTOR("\n".join(lines))

    def raise_for_failures(self) -> ScenarioOutcome:
        """Return self when nothing failed; raise ScenarioFailedError for failures, ``pytest.xfail(xfail_reason)``
        when only known-bug steps failed (a KnownBugNotReproducedWarning per known-bug step that passed, once)."""
        if self.failures:
            raise ScenarioFailedError(self)
        if self.unexpected_passes and not self._warned:
            self._warned = True
            for item in self.unexpected_passes:
                message = f"{self.scenario}: {item} passed, the known bug did not show (fixed? update known_bugs.yaml)"
                warnings.warn(KnownBugNotReproducedWarning(message), stacklevel=2)
        reason = self.xfail_reason
        if reason:
            import pytest

            pytest.xfail(reason)
        return self


class ScenarioFailedError(AssertionError):
    """A scenario failed; ``outcome`` holds the details (the message is the outcome summary)."""

    def __init__(self, outcome: ScenarioOutcome) -> None:
        """Build the assertion message from the outcome."""
        super().__init__(outcome.summary())
        self.outcome = outcome


class CleanupError(RuntimeError):
    """The cleanup apply did not complete (failed patches or validation abort)."""


# --- SUT gating (shared with the offline engine) ---------------------------------------------------------------------
def sut_version_of(cli: OtterdogCli) -> str | None:
    """Version of the SUT an OtterdogCli runs (``installed.sut.version``), None when unknown."""
    version = getattr(getattr(getattr(cli, "installed", None), "sut", None), "version", None)
    return str(version) if version else None


def fixed_in_skip_reason(scenario: Scenario, sut_version: str | None) -> str | None:
    """Skip reason when the SUT predates the scenario's ``fixed_in`` (PEP 440, local part ignored).

    Regressions of fixes merged after the latest release would otherwise fail on every release:latest run; SUTs that
    contain the fix (main, PR and local builds) run them. An unknown SUT version runs the scenario.
    """
    from otterdog_e2e.sut.version import predates

    if scenario.fixed_in and predates(sut_version, scenario.fixed_in):
        return f"SUT {sut_version} predates otterdog {scenario.fixed_in}, the first version {scenario.id} asserts"
    return None


# --- known bugs of steps (shared with the offline engine) ------------------------------------------------------------
@dataclass(frozen=True)
class StepBug:
    """The known bug a step declares as it applies to the SUT: ``reason`` is ``<id>: <title>``; ``affects`` is False
    for a fixed bug the SUT contains (the step is strict again: a regression guard); ``phases`` (None = every phase)
    are the phases whose expectation failures the bug explains (``known_bug: {id: KB-054, phases: [converge]}``)."""

    id: str
    reason: str
    affects: bool
    phases: tuple[str, ...] | None = None
    scenario_level: bool = False  # the scenario's known_bug: every step inherits it, an expected failure ends the run

    def covers(self, phase: str) -> bool:
        """True when the bug affects the SUT and explains failures of ``phase``."""
        return self.affects and (self.phases is None or phase in self.phases)


def known_bugs_near(path: Path) -> Mapping[str, KnownBug]:
    """known_bugs.yaml of the nearest directory above the scenario file ``path`` that has one, without leaving its
    project (the directory holding pyproject.toml); {} when there is none or it is invalid (cached per file and
    modification time)."""
    directory = Path(path).absolute().parent
    for candidate in (directory, *directory.parents):
        file = candidate / KNOWN_BUGS_FILE
        if file.is_file():
            try:
                return _load_known_bugs(str(file), file.stat().st_mtime_ns)
            except (OSError, ValueError) as exc:
                logger.warning("cannot load %s: %s", file, exc)
                return {}
        if (candidate / PROJECT_MARKER).is_file():
            break
    return {}


@functools.lru_cache(maxsize=16)
def _load_known_bugs(path: str, mtime_ns: int) -> Mapping[str, KnownBug]:
    """known_bugs.load of ``path`` (``mtime_ns`` only keys the cache), read-only."""
    from types import MappingProxyType

    from otterdog_e2e import known_bugs

    return MappingProxyType(dict(known_bugs.load(Path(path))))


def scenario_bug(scenario: Scenario, bugs: Mapping[str, KnownBug], sut_version: str | None) -> StepBug | None:
    """The scenario-level known bug (its ``known_bug``, else a registered bug listing the scenario id) as a StepBug
    every step without its own known_bug inherits (BAT-03: its expectation failures are expected, infra problems,
    harness errors and cleanup failures stay failures); None without one."""
    bug_id = scenario.known_bug or next((bug.id for bug in bugs.values() if scenario.id in bug.scenarios), None)
    if bug_id is None:
        return None
    bug = bugs.get(bug_id)
    if bug is None:
        return StepBug(bug_id, f"{bug_id}: not listed in known_bugs.yaml", True, None, scenario_level=True)
    return StepBug(bug.id, bug.xfail_reason, bug.affects(sut_version), None, scenario_level=True)


def step_bug(
    step: StepSpec, bugs: Mapping[str, KnownBug], sut_version: str | None, inherited: StepBug | None = None
) -> StepBug | None:
    """The StepBug of a step's ``known_bug`` (``inherited``, the scenario's, without one); an id missing from
    ``bugs`` affects every SUT."""
    if step.known_bug is None:
        return inherited
    phases = step.known_bug_phases
    bug = bugs.get(step.known_bug)
    if bug is None:
        return StepBug(step.known_bug, f"{step.known_bug}: not listed in known_bugs.yaml", True, phases)
    return StepBug(bug.id, bug.xfail_reason, bug.affects(sut_version), phases)


def start_step_bug(step: StepOutcome, bug: StepBug | None, sut_version: str | None) -> None:
    """Note the known bug of a step on its outcome (``known_bug`` only while the bug affects the SUT)."""
    if bug is None:
        return
    if bug.affects:
        step.known_bug = bug.id
        scope = f" in {', '.join(bug.phases)}" if bug.phases is not None else ""
        step.notes.append(f"known bug {bug.reason}: the failures of this step{scope} are expected")
    else:
        step.notes.append(f"known bug {bug.id} is fixed in SUT {sut_version}: the step runs strict (regression guard)")


def record_phase_problems(
    outcome: ScenarioOutcome, step: StepOutcome, phase: str, problems: Sequence[str], bug: StepBug | None
) -> list[str]:
    """Add the problems of a failed phase to ``outcome``; returns the failures among them (they stop the scenario).

    With a known bug that affects the SUT (and covers ``phase``: StepBug.phases), the expectation problems become
    expected failures; infra problems and the errors of the phase (exceptions: render errors, safety refusals,
    harness bugs; checks that could not be evaluated: failed oracle lookups) stay failures.
    """
    if bug is None or not bug.covers(phase):
        outcome.failures += [f"step {step.name!r} {phase}: {problem}" for problem in problems]
        return list(problems)
    failures = [problem for problem in problems if INFRA_PREFIX in problem or problem in step.errors]
    expected = [problem for problem in problems if problem not in failures]
    outcome.failures += [f"step {step.name!r} {phase}: {problem}" for problem in failures]
    if expected:
        step.expected_failure = True
        outcome.expected_failures += [f"step {step.name!r} {phase}: {problem}" for problem in expected]
        outcome.expected_bugs[step.name] = bug.reason
        step.notes.append(f"expected failure ({bug.id}): {len(expected)} problem(s) in {phase}")
    return failures


def record_step_passed(outcome: ScenarioOutcome, step: StepOutcome, bug: StepBug | None) -> None:
    """A step whose known bug affects the SUT passed: record it in ``unexpected_passes`` (the bug may be fixed); a
    scenario-level bug is judged on the whole scenario (record_scenario_passed)."""
    if bug is not None and bug.scenario_level:
        return
    if bug is not None and bug.affects and not step.expected_failure and step.failed_phase is None:
        outcome.unexpected_passes.append(f"{bug.reason} (step {step.name!r})")
        step.notes.append(f"known bug {bug.id} did not show: the step passed")


def record_scenario_passed(outcome: ScenarioOutcome, bug: StepBug | None) -> None:
    """A scenario whose scenario-level known bug affects the SUT ran without any failure: ``unexpected_passes``."""
    if bug is None or not bug.affects or outcome.failures or outcome.expected_failures:
        return
    outcome.unexpected_passes.append(f"{bug.reason} (scenario)")


def diff_options(spec: PlanSpec | ApplySpec | None, *, repo_filter: str | None) -> DiffOptions:
    """runner.DiffOptions of a plan or apply spec with the (already decided) repository filter."""
    if spec is None:
        return DiffOptions(repo_filter=repo_filter)
    return DiffOptions(
        repo_filter=repo_filter,
        update_webhooks=spec.update_webhooks,
        update_secrets=spec.update_secrets,
        only_secrets=spec.only_secrets,
        update_filter=spec.update_filter,
        verbose=spec.verbose,
    )


# --- expectations (shared with the offline engine) -------------------------------------------------------------------
def infra_problems(result: CliResult) -> list[str]:
    """Timeouts and infra errors (rate limits, network) of a CLI result: they make its output meaningless."""
    problems = []
    if result.timed_out:
        problems.append(f"{INFRA_PREFIX} otterdog timed out after {result.duration:.0f} s")
    if result.infra_error:
        problems.append(f"{INFRA_PREFIX} {result.infra_error}")
    return problems


def unknown_properties_problem(result: CliResult, *, expected: bool) -> str | None:
    """Failure when otterdog ignored unknown properties (a misplaced fragment) and the step did not expect it."""
    if expected:
        return None
    for line in result.output.splitlines():
        if od_output.UNKNOWN_PROPERTIES_RE.search(line):
            text = " ".join(_SOURCE_SUFFIX_RE.sub("", line).split())
            return f"otterdog ignored unknown properties (misplaced fragment?): {text[:240]}"
    return None


def unknown_properties_expected(step: StepSpec) -> bool:
    """True when a ``contains`` of the step's validate/plan/apply mentions the unknown-properties warning."""
    specs = [spec for spec in (step.validate, step.plan, step.apply) if spec is not None]
    return any(_UNKNOWN_EXPECTED_RE.search(text) for spec in specs for text in spec.contains)


def text_problems(output: str, contains: Sequence[str], not_contains: Sequence[str] = ()) -> list[str]:
    """``contains``/``not_contains`` against normalize_text(output) (ANSI/box/whitespace normalization only)."""
    if not contains and not not_contains:
        return []
    text = od_output.normalize_text(output, None)
    problems = [f"output does not contain {item!r}" for item in contains if item not in text]
    return problems + [f"output contains {item!r}" for item in not_contains if item in text]


def validation_problems(spec: ValidateSpec, result: CliResult, *, unknown_ok: bool = False) -> list[str]:
    """Failures of a ``validate`` result against its spec (ok, errors, warnings_min, infos, infos_min, exit_code,
    contains)."""
    problems = infra_problems(result)
    if problems:
        return problems
    parsed = result.validation()
    if spec.ok is not None and parsed.ok != spec.ok:
        expected, actual = ("succeed" if spec.ok else "fail"), ("succeeded" if parsed.ok else "failed")
        problems.append(f"expected validation to {expected}, it {actual} ({_validation_counts(parsed)})")
    elif spec.ok and result.exit_code != 0 and spec.exit_code is None:
        problems.append(f"validation succeeded but otterdog exited {result.exit_code}")
    if spec.exit_code is not None and result.exit_code != spec.exit_code:
        problems.append(f"expected exit code {spec.exit_code}, got {result.exit_code}")
    if spec.errors is not None and parsed.errors != spec.errors:
        problems.append(f"expected {spec.errors} error(s), got {parsed.errors}")
    if spec.warnings_min is not None and (parsed.warnings or 0) < spec.warnings_min:
        problems.append(f"expected at least {spec.warnings_min} warning(s), got {parsed.warnings}")
    if spec.infos is not None and parsed.infos != spec.infos:
        problems.append(f"expected {spec.infos} info(s), got {parsed.infos}")
    if spec.infos_min is not None and (parsed.infos or 0) < spec.infos_min:
        problems.append(f"expected at least {spec.infos_min} info(s), got {parsed.infos}")
    problems += text_problems(result.output, spec.contains, spec.not_contains)
    unknown = unknown_properties_problem(result, expected=unknown_ok)
    return problems + ([unknown] if unknown else [])


def _validation_counts(parsed: Any) -> str:
    """``E error(s), W warning(s)`` (``load error`` for configs that do not load)."""
    if getattr(parsed, "load_error", False):
        return "load error"
    return f"{parsed.errors} error(s), {parsed.warnings} warning(s)"


def relevant_objects(plan: PlanResult, needles: Sequence[str] | None, *, org_level: bool = False) -> list[PlanObject]:
    """Plan objects a scenario owns: all (needles None), this run's objects, plus org ``settings`` for org_level."""
    if needles is None:
        return list(plan.objects)
    objects = plan.objects_for(needles)
    if org_level:
        objects += [obj for obj in plan.objects if obj.kind == "settings" and obj not in objects]
    return objects


def validation_failed(result: CliResult, plan: PlanResult | None = None) -> bool:
    """True when the output reports validation errors or a configuration that does not load."""
    validation = plan.validation if plan is not None else None
    if validation is not None and (validation.errors or validation.load_error):
        return True
    return any(marker in result.output for marker in VALIDATION_ERROR_MARKERS)


def classify_plan(result: CliResult, plan: PlanResult, relevant: Sequence[PlanObject], *, unfiltered: bool) -> str:
    """``validation_error``, ``error``, ``changes`` or ``noop`` (read-only changes never count)."""
    if validation_failed(result, plan):
        return "validation_error"
    if result.exit_code != 0 or result.timed_out or plan.aborted or plan.add is None:
        return "error"
    changed = any(not obj.is_read_only for obj in relevant)
    if unfiltered:
        changed = changed or (plan.add, plan.change, plan.delete) != (0, 0, 0)
    return "changes" if changed else "noop"


def plan_problems(
    spec: PlanSpec,
    result: CliResult,
    plan: PlanResult,
    *,
    needles: Sequence[str] | None,
    org_level: bool = False,
    unknown_ok: bool = False,
) -> list[str]:
    """Failures of a plan/local-plan result against its spec (expect, exit_code, contains, counts, unknown
    properties); contains/not_contains are checked whatever the outcome (validation errors and aborted plans
    included)."""
    relevant = relevant_objects(plan, needles, org_level=org_level)
    outcome = classify_plan(result, plan, relevant, unfiltered=needles is None)
    problems = []
    if spec.expect != "any" and outcome != spec.expect:
        problems.append(f"expected {spec.expect}, got {outcome}{_plan_detail(result, plan, relevant, outcome)}")
    if spec.exit_code is not None and result.exit_code != spec.exit_code:
        problems.append(f"expected exit code {spec.exit_code}, got {result.exit_code}")
    problems += text_problems(result.output, spec.contains, spec.not_contains)
    if spec.counts:
        problems += count_problems(spec.counts, plan, needles=needles, org_level=org_level)
    unknown = unknown_properties_problem(result, expected=unknown_ok)
    return problems + ([unknown] if unknown else [])


def _plan_detail(result: CliResult, plan: PlanResult, relevant: Sequence[PlanObject], outcome: str) -> str:
    """Short explanation appended to a plan expectation mismatch."""
    if outcome == "changes":
        return ": " + _headers(obj for obj in relevant if not obj.is_read_only)
    if outcome == "noop":
        foreign = len([obj for obj in plan.objects if obj not in relevant and not obj.is_read_only])
        return f" (no change planned for this run's objects; {foreign} foreign change(s) ignored)"
    errors = [message.text for message in plan.messages if message.level.lower().startswith("error")]
    if not errors and plan.validation is not None:
        errors = [m.text for m in plan.validation.messages if m.level.lower().startswith("error")]
    return f" (exit code {result.exit_code}" + (f": {_first_lines(errors)})" if errors else ")")


def _headers(objects: Iterable[PlanObject]) -> str:
    """Up to _MAX_LISTED object headers, stripped."""
    headers = [obj.header.strip() for obj in objects]
    shown = "; ".join(headers[:_MAX_LISTED])
    return shown + (f"; ... ({len(headers)} in total)" if len(headers) > _MAX_LISTED else "")


def _first_lines(texts: Sequence[str], limit: int = 3) -> str:
    """First line of up to ``limit`` messages."""
    return "; ".join(text.strip().splitlines()[0] for text in texts[:limit] if text.strip())


def count_problems(
    expected: Mapping[str, int], plan: PlanResult, *, needles: Sequence[str] | None, org_level: bool = False
) -> list[str]:
    """Count mismatches: raw ``Plan:`` numbers, or this run's objects only when the plan has foreign changes."""
    if plan.add is None:
        return ["counts: the plan printed no 'Plan:' summary"]
    filtered = needles is not None and not org_level and _has_foreign_changes(plan, needles)
    actual = filtered_counts(plan.objects_for(needles or ())) if filtered else _raw_counts(plan)
    scope = " (this run's objects; foreign changes in the plan)" if filtered else ""
    return [
        f"counts.{key}: expected {count}, got {actual.get(key)}{scope}"
        for key, count in expected.items()
        if actual.get(key) != count
    ]


def _has_foreign_changes(plan: PlanResult, needles: Sequence[str]) -> bool:
    """True when objects outside this run plan non-read-only changes."""
    own = plan.objects_for(needles)
    return any(obj not in own and not obj.is_read_only for obj in plan.objects)


def _raw_counts(plan: PlanResult) -> dict[str, int | None]:
    """The ``Plan:`` numbers."""
    return {"add": plan.add, "change": plan.change, "delete": plan.delete}


def filtered_counts(objects: Sequence[PlanObject]) -> dict[str, int | None]:
    """Counts computed like otterdog's ``Plan:`` line over the given objects (change = changed non-read-only keys)."""
    changes = 0
    for obj in objects:
        if obj.op in ("change", "forced"):
            read_only = set(obj.read_only_keys)
            keys = [key for key in obj.changed_keys if key not in read_only]
            changes += len(keys) if obj.changed_keys else (0 if obj.is_read_only else 1)
    return {
        "add": sum(1 for obj in objects if obj.op == "add"),
        "change": changes,
        "delete": sum(1 for obj in objects if obj.op == "remove"),
    }


def classify_apply(result: CliResult, applied: ApplyResult) -> str:
    """``validation_error``, ``error`` or ``ok`` (exit 0, summary printed, no failed patch)."""
    if applied.aborted_validation or validation_failed(result):
        return "validation_error"
    if result.exit_code != 0 or result.timed_out or applied.failed_patches:
        return "error"
    return "ok" if applied.no_changes or applied.added is not None else "error"


def apply_problems(spec: ApplySpec, result: CliResult, applied: ApplyResult, *, unknown_ok: bool = False) -> list[str]:
    """Failures of an apply result against its spec (ok = exit 0, no validation abort, no failed patch)."""
    outcome = classify_apply(result, applied)
    problems = []
    if spec.expect != "any" and outcome != spec.expect:
        detail = f": {_first_lines(applied.failed_patches)}" if applied.failed_patches else ""
        problems.append(f"expected {spec.expect}, got {outcome} (exit code {result.exit_code}){detail}")
    problems += text_problems(result.output, spec.contains, spec.not_contains)
    unknown = unknown_properties_problem(result, expected=unknown_ok)
    return problems + ([unknown] if unknown else [])


def command_problems(command: str, spec: CommandSpec, result: CliResult) -> list[str]:
    """Failures of an extra offline command (exit code, contains)."""
    problems = infra_problems(result)
    if problems:
        return problems
    if spec.exit_code is not None and result.exit_code != spec.exit_code:
        problems.append(f"{command}: expected exit code {spec.exit_code}, got {result.exit_code}")
    return problems + [f"{command}: {p}" for p in text_problems(result.output, spec.contains, spec.not_contains)]


def output_tail(result: CliResult, lines: int = OUTPUT_TAIL_LINES) -> str:
    """Last ``lines`` lines of the normalized output (falls back to the raw output if normalization fails)."""
    try:
        text = od_output.normalize_text(result.output, None)
    except PHASE_ERRORS:
        text = result.output
    return "\n".join(text.splitlines()[-lines:])


def run_phase(outcome: StepOutcome, phase: str, handler: Callable[[], list[str] | None]) -> list[str] | None:
    """Run one phase: None = skipped, [] = passed, else problems (expected exceptions become problems, also kept in
    ``outcome.errors``: they are never expected failures of a known bug)."""
    started = time.monotonic()
    raised = False
    try:
        problems = handler()
    except PHASE_ERRORS as exc:
        logger.info("phase %s of step %s raised %s", phase, outcome.name, type(exc).__name__)
        problems = [f"{type(exc).__name__}: {REDACTOR(str(exc))}"]
        raised = True
    if problems is not None:
        outcome.durations[phase] = round(time.monotonic() - started, 3)
    if problems:
        outcome.failed_phase = outcome.failed_phase or phase
        problems = [REDACTOR(problem) for problem in problems]
        if raised:
            outcome.errors += problems
    return problems


def add_tail(outcome: StepOutcome, key: str) -> None:
    """Note the output tail of ``outcome.results[key]`` (used for failed phases)."""
    result = outcome.results.get(key)
    if result is not None:
        outcome.notes.append(f"{key} output (last {OUTPUT_TAIL_LINES} lines):\n{REDACTOR(output_tail(result))}")


# --- live engine -----------------------------------------------------------------------------------------------------
class _SleepClock:
    """A clock advanced only by the engine's sleeps: retry budgets stay deterministic with an injected sleep."""

    def __init__(self, sleep: Callable[[float], None]) -> None:
        """Wrap ``sleep``."""
        self._sleep = sleep
        self.now = 0.0

    def __call__(self) -> float:
        """Seconds slept so far."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Sleep and advance the clock."""
        self._sleep(seconds)
        self.now += seconds


@dataclass
class _LiveStep:
    """Mutable state of one live step while its phases run."""

    scenario: Scenario
    spec: StepSpec
    outcome: StepOutcome
    variables: Mapping[str, Any]
    rendered: StepSpec | None = None
    plan: PlanResult | None = None
    applied_ok: bool = False
    unknown_ok: bool = False


class ScenarioEngine:
    """Runs live scenarios (tier cli/enterprise) with the SUT CLI; ``-d`` cleanup goes through guarded_apply.

    ``known_bugs`` (None = the known_bugs.yaml above each scenario file, known_bugs_near) decides whether the known
    bug of a step affects the SUT; it may be set after construction (the session's bugs).
    """

    def __init__(
        self,
        *,
        cli: OtterdogCli,
        renderer: OrgConfigRenderer,
        oracle: Oracle,
        run_ctx: RunContext,
        capabilities: Capabilities,
        baseline: BaselineManager,
        variables: Mapping[str, Any],
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        """Bind the collaborators of a live run (``variables["p"]``, when given, must be the run prefix)."""
        if variables.get("p", run_ctx.prefix) != run_ctx.prefix:
            raise ValueError(
                f"variables p={variables['p']!r} do not belong to run {run_ctx.run_id}: cleanup would miss"
            )
        self.cli = cli
        self.renderer = renderer
        self.oracle = oracle
        self.run_ctx = run_ctx
        self.capabilities = capabilities
        self.baseline = baseline
        self.variables = dict(variables)
        self.sleep = sleep
        self._clock = _SleepClock(sleep)
        self.known_bugs: Mapping[str, KnownBug] | None = None

    def bugs_for(self, scenario: Scenario) -> Mapping[str, KnownBug]:
        """Known bugs deciding the scenario's step known_bug: ``known_bugs``, else known_bugs_near(source)."""
        return self.known_bugs if self.known_bugs is not None else known_bugs_near(scenario.source)

    def run(self, scenario: Scenario, *, cleanup: bool = True) -> ScenarioOutcome:
        """Run every step (phases of SPEC 12.1), then cleanup; raises AssertionError(summary) if anything failed and
        xfails (pytest.xfail) when only the steps of a known bug failed (ScenarioOutcome.raise_for_failures)."""
        if not scenario.is_live:
            raise ValueError(f"scenario {scenario.id} is tier {scenario.tier}: use OfflineEngine")
        outcome = ScenarioOutcome(scenario.id)
        outcome.skipped = self.skip_reason(scenario)
        if outcome.skipped:
            return outcome
        missing = self.capabilities.missing(scenario.expect_failure_without)
        variables = self.variables_for(scenario)
        inherited = scenario_bug(scenario, self.bugs_for(scenario), sut_version_of(self.cli))
        if cleanup and not self._remove_leftovers(scenario, outcome):
            return outcome.raise_for_failures()
        try:
            for step in scenario.steps:
                problems = self._run_step(scenario, step, variables, missing, outcome, inherited)
                if problems or (
                    inherited is not None and step.known_bug is None and outcome.steps[-1].expected_failure
                ):
                    break  # a scenario-level bug's expected failure ends the reproduction (the cleanup still runs)
            record_scenario_passed(outcome, inherited)
        finally:
            if cleanup and scenario.cleanup == "auto":
                self._safe_cleanup(scenario, outcome)
        return outcome.raise_for_failures()

    def skip_reason(self, scenario: Scenario) -> str | None:
        """Why the target or the SUT cannot run the scenario (missing ``requires`` capabilities, plan below
        ``min_plan``, a ``variables.plan`` override equal to the target's plan: the rendered plan would not differ from
        the live one, BAT-16; SUT older than ``fixed_in``)."""
        missing = self.capabilities.missing(scenario.requires)
        if missing:
            return f"missing capabilities: {', '.join(missing)}"
        if self.capabilities.plan not in plans_at_least(scenario.min_plan):
            return f"plan {self.capabilities.plan!r} is below min_plan {scenario.min_plan!r}"
        if scenario.plan_override is not None and scenario.plan_override == self.capabilities.plan:
            return (
                f"variables.plan {scenario.plan_override!r} is the target's own plan: the scenario renders a plan that "
                "differs from the live one"
            )
        return fixed_in_skip_reason(scenario, sut_version_of(self.cli))

    def variables_for(self, scenario: Scenario) -> dict[str, Any]:
        """Jinja variables of a scenario: run context, engine variables, then the scenario's (``plan`` override)."""
        return {**self.run_ctx.template_vars(), **self.variables, **scenario.variables}

    def cleanup(self, scenario: Scenario) -> None:
        """org_level: baseline.reset(); else guarded ``apply -d -r "<p>-*"`` with the baseline-only config."""
        if scenario.org_level:
            _check_cleanup(self.baseline.reset(), "baseline reset")
            return
        reset_cli = self.baseline.reset_cli
        if not reset_cli.workspace.config_file.exists():  # no reset ran yet (--e2e-no-reset)
            reset_cli.workspace.write_otterdog_json()
        reset_cli.workspace.write_org_config(self.baseline.text())
        applied = self.baseline.guarded_apply(reset_cli, repo_filter=self.run_ctx.repo_filter(), delete=True)
        _check_cleanup(applied, f"cleanup apply -d -r {self.run_ctx.repo_filter()}")

    def _remove_leftovers(self, scenario: Scenario, outcome: ScenarioOutcome) -> bool:
        """Before a scenario: when the last removal of this run's objects failed (an earlier scenario or test left
        objects behind), remove them first with the scenario's own cleanup: the plans of this scenario cover the whole
        run (RunContext.needles), so leftovers would fail its noop, count and converge checks (BAT-06). False (with a
        failure naming the leftovers, not the scenario's expectations) when they cannot be removed."""
        if not self.baseline.run_objects_left:
            return True
        logger.warning(
            "objects of an earlier item of run %s are left: removing them before %s", self.run_ctx.run_id, scenario.id
        )
        try:
            self.cleanup(scenario)
        except PHASE_ERRORS as exc:
            outcome.failures.append(
                REDACTOR(
                    "leftovers: objects an earlier item of this run left behind could not be removed before this "
                    f"scenario ({type(exc).__name__}: {exc}); its plans would count them"
                )
            )
            return False
        return True

    def _safe_cleanup(self, scenario: Scenario, outcome: ScenarioOutcome) -> None:
        """Cleanup recording its failure instead of raising."""
        try:
            self.cleanup(scenario)
        except PHASE_ERRORS as exc:
            logger.warning("cleanup of %s failed: %s", scenario.id, type(exc).__name__)
            outcome.failures.append(REDACTOR(f"cleanup: {type(exc).__name__}: {exc}"))

    def _run_step(
        self,
        scenario: Scenario,
        step: StepSpec,
        variables: Mapping[str, Any],
        missing: Sequence[str],
        outcome: ScenarioOutcome,
        inherited: StepBug | None = None,
    ) -> list[str]:
        """Run the phases of one step (negative variant when capabilities are missing); returns the problems that stop
        the scenario (the expected failures of a known-bug step do not); ``inherited``: the scenario-level bug."""
        negative = bool(missing)
        state = _LiveStep(
            scenario=scenario,
            spec=step.for_missing_capability() if negative else step,
            outcome=StepOutcome(step.name, negative=negative),
            variables=variables,
        )
        outcome.steps.append(state.outcome)
        if negative:
            state.outcome.notes.append(f"negative mode: missing {', '.join(missing)} (on_missing_capability applied)")
        version = sut_version_of(self.cli)
        bug = step_bug(step, self.bugs_for(scenario), version, inherited)
        start_step_bug(state.outcome, bug, version)
        for phase in LIVE_PHASES:
            problems = run_phase(state.outcome, phase, functools.partial(getattr(self, f"_{phase}"), state))
            if problems:
                add_tail(state.outcome, phase)
                return record_phase_problems(outcome, state.outcome, phase, problems, bug)
        record_step_passed(outcome, state.outcome, bug)
        return []

    def _repo_filter(self, scenario: Scenario) -> str | None:
        """``-r`` filter of plans and applies: this run's repos, none for org-level scenarios."""
        return None if scenario.org_level else self.run_ctx.repo_filter()

    def _filter(self, scenario: Scenario, override: str | None) -> str | None:
        """The step's ``repo_filter`` override (SafetyError when a non org_level scenario's pattern does not start
        with this run's prefix), else the default filter."""
        if override is None:
            return self._repo_filter(scenario)
        if not scenario.org_level and not override.startswith(f"{self.run_ctx.prefix}-"):
            raise SafetyError(
                f"repo_filter {override!r} does not start with this run's prefix {self.run_ctx.prefix}-: only "
                "org_level scenarios may plan or apply other repositories"
            )
        return override

    def _plan_filter(self, state: _LiveStep) -> str | None:
        """``-r`` of the step's plan: its ``repo_filter``, else the default."""
        assert state.rendered is not None
        plan = state.rendered.plan
        return self._filter(state.scenario, plan.repo_filter if plan is not None else None)

    def _apply_filter(self, state: _LiveStep) -> str | None:
        """``-r`` of the step's apply and converge plans: the apply's ``repo_filter``, else the plan's, else the
        default."""
        assert state.rendered is not None
        apply, plan = state.rendered.apply, state.rendered.plan
        override = apply.repo_filter if apply is not None and apply.repo_filter is not None else None
        if override is None and plan is not None:
            override = plan.repo_filter
        return self._filter(state.scenario, override)

    def _render(self, state: _LiveStep) -> list[str]:
        """Render the step once (Jinja), render the org config and write it to the SUT workspace."""
        state.rendered = render_step(state.spec, state.variables)
        state.unknown_ok = unknown_properties_expected(state.rendered)
        text = self.renderer.render(state.rendered.fragments, plan=state.scenario.plan_override)
        self.cli.workspace.write_org_config(text)
        return []

    def _validate(self, state: _LiveStep) -> list[str] | None:
        """``validate [-v]`` (only when the step gives expectations)."""
        assert state.rendered is not None
        spec = state.rendered.validate
        if spec is None:
            return None
        result = self.cli.validate(verbose=spec.verbose)
        state.outcome.results["validate"] = result
        return validation_problems(spec, result, unknown_ok=state.unknown_ok)

    def _plan(self, state: _LiveStep) -> list[str] | None:
        """``plan -n [-r <run>-*]`` with the step's diff flags, checked against the plan spec."""
        assert state.rendered is not None
        spec = state.rendered.plan
        if spec is None:
            return None
        result = self.cli.plan_with(diff_options(spec, repo_filter=self._plan_filter(state)))
        state.outcome.results["plan"] = result
        problems = infra_problems(result)
        if problems:
            return problems
        state.plan = result.plan()
        needles = self.run_ctx.needles()
        org_level = state.scenario.org_level
        return plan_problems(
            spec, result, state.plan, needles=needles, org_level=org_level, unknown_ok=state.unknown_ok
        )

    def _apply(self, state: _LiveStep) -> list[str] | None:
        """``apply -f -n`` with the step's diff flags when the plan expected changes (``-d`` only after
        check_removals of the step's plan, which used the same filter)."""
        assert state.rendered is not None
        spec, plan_spec = state.rendered.apply, state.rendered.plan
        if spec is None or plan_spec is None or plan_spec.expect != "changes" or state.plan is None:
            return None
        repo_filter = self._apply_filter(state)
        if spec.delete and repo_filter != self._plan_filter(state):
            raise SafetyError(
                "apply -d must use the repository filter of the step's plan (the guard checked that plan)"
            )
        options = diff_options(spec, repo_filter=repo_filter)
        self._guard_apply(spec, self._guard_plan(state, options) if spec.delete else state.plan)
        result = self.cli.apply_with(options, delete=spec.delete)
        state.outcome.results["apply"] = result
        problems = infra_problems(result)
        if problems:
            return problems
        applied = result.apply()
        state.applied_ok = classify_apply(result, applied) == "ok"
        return apply_problems(spec, result, applied, unknown_ok=state.unknown_ok)

    def _guard_plan(self, state: _LiveStep, options: DiffOptions) -> PlanResult:
        """The plan that guards an ``apply -d`` (DESTR-02): the step's plan when it ran with exactly the apply's diff
        flags (``-v`` aside), else a fresh plan with the apply's options (a ``--only-secrets`` plan hides every
        non-secret removal: check_removals must see what the apply deletes)."""
        assert state.plan is not None and state.rendered is not None
        planned = diff_options(state.rendered.plan, repo_filter=self._plan_filter(state))
        if dataclasses.replace(planned, verbose=False) == dataclasses.replace(options, verbose=False):
            return state.plan
        result = self.cli.plan_with(dataclasses.replace(options, verbose=False))
        state.outcome.results["guard-plan"] = result
        if infra_problems(result) or result.exit_code != 0:
            raise SafetyError(f"apply -d: the guard plan with the apply's flags failed (exit code {result.exit_code})")
        state.outcome.notes.append("apply -d guarded by a plan with the apply's diff flags (they differ from the plan)")
        return result.plan()

    def _guard_apply(self, spec: ApplySpec, plan: PlanResult) -> None:
        """SafetyError before an apply that would delete unsafe objects, change objects the baseline reset can never
        restore (no run id, not declared by the baseline: DESTR-07) or touch the org description (marker)."""
        self.baseline.check_changes(plan)
        if spec.delete:
            self.baseline.check_removals(plan)
        touched = [obj for obj in plan.objects if obj.kind == "settings" and "description" in obj.changed_keys]
        if touched:
            raise SafetyError(f"refusing to apply a plan that changes the org description: {_headers(touched)}")

    def _state(self, state: _LiveStep) -> list[str] | None:
        """Oracle checks, retried every STATE_INTERVAL s up to STATE_TIMEOUT s (or per-check timeouts)."""
        assert state.rendered is not None
        checks = state.rendered.state
        if not checks:
            return None
        results = wait_for_checks(
            self.oracle,
            checks,
            timeout=STATE_TIMEOUT,
            interval=STATE_INTERVAL,
            sleep=self._clock.sleep,
            clock=self._clock,
        )
        state.outcome.checks = results
        # a check that could not be evaluated (failed lookup, malformed check) is a harness/infra error: never the
        # expected failure of a known bug (BAT-02)
        state.outcome.errors += [REDACTOR(result.message) for result in results if not result.ok and result.error]
        return [result.message for result in results if not result.ok]

    def _converge(self, state: _LiveStep) -> list[str] | None:
        """After a successful apply: plan until this run's objects are a no-op (backoff 5/10/20 s, 4 plans)."""
        assert state.rendered is not None
        if not state.rendered.converge or not state.applied_ok:
            return None
        attempts: list[tuple[CliResult, str, PlanResult | None]] = []
        waiting.poll(
            lambda: self._converge_attempt(state, attempts),
            until=lambda outcome: outcome == "noop",
            max_attempts=CONVERGE_ATTEMPTS,
            interval=waiting.CONVERGE_BACKOFF,
            raise_on_timeout=False,
            sleep=self._clock.sleep,
            clock=self._clock,
        )
        result, outcome, plan = attempts[-1]
        state.outcome.results["converge"] = result
        state.outcome.notes.append(f"converge: {outcome} after {len(attempts)} plan(s)")
        if outcome == "noop":
            return []
        return [self._not_converged(result, outcome, plan, state.scenario, len(attempts))]

    def _converge_attempt(self, state: _LiveStep, attempts: list[tuple[CliResult, str, PlanResult | None]]) -> str:
        """One converge plan (the apply's filter, no update flag: forced updates never converge); returns its
        classification (``infra`` when the output is unusable)."""
        result = self.cli.plan_with(DiffOptions(repo_filter=self._apply_filter(state)))
        if infra_problems(result):
            attempts.append((result, "infra", None))
            return "infra"
        plan = result.plan()
        relevant = relevant_objects(plan, self.run_ctx.needles(), org_level=state.scenario.org_level)
        outcome = classify_plan(result, plan, relevant, unfiltered=False)
        attempts.append((result, outcome, plan))
        return outcome

    def _not_converged(
        self, result: CliResult, outcome: str, plan: PlanResult | None, scenario: Scenario, count: int
    ) -> str:
        """Failure message of a converge loop that never reached a no-op."""
        if plan is None:
            return f"not converged after {count} plan(s): " + "; ".join(infra_problems(result))
        relevant = relevant_objects(plan, self.run_ctx.needles(), org_level=scenario.org_level)
        pending = [obj for obj in relevant if not obj.is_read_only]
        message = f"not converged after {count} plan(s), last plan: {outcome}"
        if pending:
            message += ": " + _headers(pending)
        if any(obj.op == "remove" for obj in pending):
            message += " (removals stay pending unless the apply uses delete: true)"
        return message


def _check_cleanup(applied: ApplyResult | None, what: str) -> None:
    """CleanupError when a cleanup apply failed patches or aborted on validation errors."""
    if applied is None:
        return
    if applied.aborted_validation:
        raise CleanupError(f"{what}: aborted by validation errors")
    if applied.failed_patches:
        raise CleanupError(
            f"{what}: {len(applied.failed_patches)} failed patch(es): {_first_lines(applied.failed_patches)}"
        )


# --- differential ----------------------------------------------------------------------------------------------------
@dataclass
class SutSide:
    """One side of a differential run: the SUT's CLI, its recorder and its template."""

    role: str
    installed: InstalledCli
    cli: OtterdogCli
    recorder: ObservationRecorder
    template: TemplateRef


class DifferentialRunner:
    """Records the same scenarios on the base and head SUTs for differential.compare (observe-only, F6).

    ``run_ctx`` (default: the deterministic offline run context, so both sides render identical names) and
    ``variables`` (e.g. the session's scenario variables for observe_live) may be set after construction.
    observe_offline keeps going after failing phases so both sides record the same keys; outcomes per scenario and
    role are kept in ``outcomes``.
    """

    def __init__(
        self,
        *,
        base: SutSide,
        head: SutSide,
        renderer_factory: Callable[[SutSide], OrgConfigRenderer] | None,
        template_src_for: Callable[[SutSide], Path],
    ) -> None:
        """Bind both sides; renderer_factory is required for observe_live."""
        from otterdog_e2e.scenarios.offline import offline_run_context

        self.base = base
        self.head = head
        self.renderer_factory = renderer_factory
        self.template_src_for = template_src_for
        self.run_ctx: RunContext = offline_run_context()
        self.variables: dict[str, Any] = {}
        self.outcomes: dict[str, dict[str, ScenarioOutcome]] = {}

    @property
    def sides(self) -> tuple[SutSide, SutSide]:
        """(base, head), the recording order."""
        return (self.base, self.head)

    def observe_offline(self, scenario: Scenario) -> None:
        """OfflineEngine per side (each side's own template unless the change under test requests one side's)."""
        from otterdog_e2e.scenarios.offline import OfflineEngine

        for side in self.sides:
            engine = OfflineEngine(
                cli=side.cli,
                workspace=side.cli.workspace,
                template_src=self.template_src_for(side),
                run_ctx=self.run_ctx,
                variables=self.variables,
            )
            engine.observe = True
            engine.keep_going = True
            engine.skip_older_suts = False  # fixed_in: both sides record, the difference is the point
            self.outcomes.setdefault(scenario.id, {})[side.role] = engine.run(scenario)

    def observe_live(self, scenario: Scenario) -> None:
        """Per step: render+write, then validate + plan with base then head (the step's ``validate.verbose`` and plan
        flags, ``repo_filter`` included); NEVER apply."""
        if self.renderer_factory is None:
            raise ValueError("observe_live needs a renderer_factory")
        if not scenario.is_live:
            raise ValueError(f"scenario {scenario.id} is tier {scenario.tier}: use observe_offline")
        renderers = {side.role: self.renderer_factory(side) for side in self.sides}
        variables = {**self.run_ctx.template_vars(), **self.variables, **scenario.variables}
        default_filter = None if scenario.org_level else f"{variables['p']}-*"  # the prefix the fragments use
        for step in scenario.steps:
            rendered = render_step(step, variables)
            plan = rendered.plan
            repo_filter = plan.repo_filter if plan is not None and plan.repo_filter else default_filter
            options = diff_options(plan, repo_filter=repo_filter)
            verbose = rendered.validate is not None and rendered.validate.verbose
            for side in self.sides:
                text = renderers[side.role].render(rendered.fragments, plan=scenario.plan_override)
                side.cli.workspace.write_org_config(text)
                with _scope(side.recorder, scenario.id, step.name):
                    side.cli.validate(verbose=verbose, observe="validate")
                    side.cli.plan_with(options, observe="plan")


def _scope(recorder: ObservationRecorder | None, scenario: str, step: str) -> AbstractContextManager[None]:
    """The recorder's scope for (scenario, step), or a no-op without recorder."""
    return recorder.scope(scenario, step) if recorder is not None else nullcontext()


OFFLINE_EPOCH = datetime(2025, 1, 1, tzinfo=UTC)


def deterministic_run_context(run_id: str) -> RunContext:
    """A RunContext with a fixed creation time (identical names and template variables on every run)."""
    return new_run_context(run_id, now=OFFLINE_EPOCH)
