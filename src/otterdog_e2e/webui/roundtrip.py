"""The web-settings round trip: every web-only setting change of a run in ONE scenario (docs/web-ui-testing.md).

Each web command logs the bot in once (``apply``: twice, read then write), and logins are spaced by a TOTP window,
so the tier groups everything into one scenario with 8 logins:

1. snapshot: REST (7 settings) and the TRUSTED reader (``show-live`` of the reset SUT, every setting it can read);
   both must agree on the overlapping keys, otherwise nothing is changed;
2. set: the SUT applies the baseline with every writable web setting pinned (``key::: <value>``) to its toggled value
   (booleans negated, the default branch renamed, discussions switched with a fixture repository as source); its
   plan must change exactly the toggled keys;
3. verify: REST and the trusted reader see the toggled values;
4. converge: the SUT's own ``plan`` without ``-n`` is a no-op for every web key;
5. restore: the SUT applies the original values, 6. verify again; when the SUT could not restore them, the TRUSTED
   CLI restores them (BaselineManager.restore_web_settings) and they are verified once more.

The original values are recorded in the BaselineManager before anything changes, so the session restores them even
if the scenario dies (pytest_plugin baseline teardown). Not toggled: ``two_factor_requirement`` (read-only in
otterdog; requiring 2FA would remove members), settings the plan does not offer, settings nobody could read.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field
from typing import Any

from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.webui import mapping
from otterdog_e2e.webui.gate import classify_web_failure
from otterdog_e2e.webui.oracle import TrustedWebReader, settings_changes, wait_rest_values

DISCUSSIONS, DISCUSSION_SOURCE = "has_discussions", "discussion_source_repository"
DEFAULT_BRANCH = "default_branch_name"
FALLBACK_BRANCH = "main"
TAIL_CHARS = 1500


def toggled_branch(run_id: str) -> str:
    """The run-specific default branch name the round trip sets (``e2e-<run>``)."""
    return f"e2e-{run_id}"


@dataclass
class WebSnapshot:
    """Original web-only settings: what REST and the trusted reader returned, combined (REST wins), disagreements."""

    rest: dict[str, Any]
    trusted: dict[str, Any]
    values: dict[str, Any]
    problems: list[str] = field(default_factory=list)
    unread: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def writable(self) -> dict[str, Any]:
        """The values of the writable settings (what the round trip pins and restores)."""
        return {key: self.values[key] for key in mapping.WRITABLE if key in self.values}


def combine_snapshot(rest: Mapping[str, Any], trusted: Mapping[str, Any]) -> WebSnapshot:
    """Combine both oracles: REST values first, trusted values for the others; a disagreement on a key both read is a
    problem (the trusted reader is then not trustworthy for the keys only it reads)."""
    values: dict[str, Any] = {}
    problems, notes = [], []
    for key in mapping.WEB_KEYS:
        in_rest, in_trusted = key in rest, key in trusted
        if in_rest and in_trusted and rest[key] != trusted[key]:
            if rest[key] is None:
                notes.append(f"{key}: REST returned null, the trusted reader {mapping.jsonnet_value(trusted[key])}")
            else:
                problems.append(
                    f"{key}: REST says {mapping.jsonnet_value(rest[key])}, the trusted reader "
                    f"{mapping.jsonnet_value(trusted[key])}"
                )
        if in_rest and rest[key] is not None:
            values[key] = rest[key]
        elif in_trusted:
            values[key] = trusted[key]
        elif in_rest:
            values[key] = rest[key]
    unread = [key for key in mapping.WEB_KEYS if key not in values]
    for key in sorted(set(rest) & set(mapping.REST_FIELDS) - set(trusted)):
        if key in mapping.EXPECTED_UNREAD:
            notes.append(f"{key}: read through REST only (otterdog's web client never reads it)")
    return WebSnapshot(dict(rest), dict(trusted), values, problems, unread, notes)


def plan_toggles(
    values: Mapping[str, Any],
    *,
    plan: str,
    run_id: str,
    discussion_repo: str | None,
    readable: Iterable[str] | None = None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """(toggled values, skipped key -> reason) for the writable settings of ``values`` on ``plan``.

    Booleans are negated; the default branch becomes ``e2e-<run>`` (or ``main`` when it already is); discussions are
    switched off (source null) or on with ``discussion_repo`` (``<org>/<repo>``) as source. ``readable``: the keys
    otterdog's web reader returned (the trusted read); others are skipped, since otterdog cannot manage them.
    """
    toggles: dict[str, Any] = {}
    skipped: dict[str, str] = {}
    read_by_otterdog = set(readable) if readable is not None else set(values)
    for setting in mapping.WEB_SETTINGS:
        key = setting.key
        if key == DISCUSSION_SOURCE:
            continue  # switched together with has_discussions
        if not setting.writable:
            skipped[key] = setting.note or "read-only in otterdog"
        elif not setting.applicable(plan):
            skipped[key] = f"not offered on the {plan} plan"
        elif key not in values or values[key] is None:
            skipped[key] = "not read by any oracle (UNSET live): nothing to compare"
        elif key not in read_by_otterdog:
            skipped[key] = "otterdog's web reader did not return it (missing on the settings page)"
        elif key == DISCUSSIONS:
            if values[key]:
                toggles[key], toggles[DISCUSSION_SOURCE] = False, None
            elif discussion_repo:
                toggles[key], toggles[DISCUSSION_SOURCE] = True, discussion_repo
            else:
                skipped[key] = "no public fixture repository to host the org discussions"
        elif key == DEFAULT_BRANCH:
            branch = toggled_branch(run_id)
            toggles[key] = branch if values[key] != branch else FALLBACK_BRANCH
        elif setting.value_type == "boolean":
            toggles[key] = not bool(values[key])
        else:
            skipped[key] = f"no toggle for {setting.value_type} values"
    return toggles, skipped


def expected_changes(before: Mapping[str, Any], after: Mapping[str, Any], keys: Iterable[str]) -> list[str]:
    """Web keys otterdog must plan when going from ``before`` to ``after`` (it ignores the discussion source while
    discussions are switched off in the configuration)."""
    changed = [key for key in keys if before.get(key) != after.get(key)]
    if after.get(DISCUSSIONS) is False:
        changed = [key for key in changed if key != DISCUSSION_SOURCE]
    return changed


@dataclass
class StepRecord:
    """One step of the round trip."""

    name: str
    ok: bool
    detail: str = ""
    seconds: float = 0.0


@dataclass
class RoundTripReport:
    """What the round trip observed (written as evidence, summarized on failure)."""

    snapshot: WebSnapshot | None = None
    toggles: dict[str, Any] = field(default_factory=dict)
    skipped: dict[str, str] = field(default_factory=dict)
    steps: list[StepRecord] = field(default_factory=list)
    restored: bool = False
    changed: bool = False
    # toggled keys REST cannot read, verified only by the trusted reader running the SUT's own web code: no independent
    # evidence (BAT-17: a symmetric bug of otterdog's web reader and writer would pass)
    self_checked: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Every step passed and the original values are back (or nothing was changed)."""
        return bool(self.steps) and all(step.ok for step in self.steps) and (self.restored or not self.changed)

    def failures(self) -> list[str]:
        """``<step>: <detail>`` of every failed step."""
        return [f"{step.name}: {step.detail}" for step in self.steps if not step.ok]

    def summary(self) -> str:
        """Readable, redacted summary (failure message of the test)."""
        lines = [f"web settings round trip: {'ok' if self.ok else 'FAILED'}"]
        lines += [f"  toggled {key} -> {mapping.jsonnet_value(value)}" for key, value in self.toggles.items()]
        lines += [f"  skipped {key}: {reason}" for key, reason in self.skipped.items()]
        lines += [f"  {'ok  ' if s.ok else 'FAIL'} {s.name} ({s.seconds:.0f} s): {s.detail}" for s in self.steps]
        if self.changed and not self.restored:
            lines.append("  ORIGINAL VALUES NOT RESTORED: the session-end restore retries (docs/web-ui-testing.md)")
        if self.self_checked:
            lines.append(
                "  self-checked only (the trusted reader runs the SUT's own code, REST cannot read them): "
                + ", ".join(self.self_checked)
            )
        return REDACTOR("\n".join(lines))

    def to_json(self) -> dict[str, Any]:
        """JSON evidence (artifacts)."""
        return {
            "ok": self.ok,
            "changed": self.changed,
            "restored": self.restored,
            "snapshot": asdict(self.snapshot) if self.snapshot is not None else None,
            "toggles": self.toggles,
            "skipped": self.skipped,
            "steps": [asdict(step) for step in self.steps],
            "self_checked": self.self_checked,
        }


class WebSettingsRoundTrip:
    """Runs the round trip of the module docstring with injected collaborators (unit-testable with fakes).

    ``sut``: web-mode CLI of the SUT; ``reader``: TrustedWebReader (reset SUT); ``rest()``: REST web values;
    ``render(values)``: the baseline config with ``values`` pinned; ``record(values)`` / ``restored()``: the
    BaselineManager bookkeeping; ``trusted_restore(values)``: the trusted fallback restore (ApplyResult-like).
    """

    def __init__(
        self,
        *,
        sut: Any,
        reader: TrustedWebReader,
        rest: Callable[[], Mapping[str, Any]],
        render: Callable[[Mapping[str, Any]], str],
        plan: str,
        run_id: str,
        discussion_repo: str | None = None,
        record: Callable[[Mapping[str, Any]], None] | None = None,
        restored: Callable[[], None] | None = None,
        trusted_restore: Callable[[Mapping[str, Any]], Any] | None = None,
        verify_timeout: float = 120.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        reader_is_sut: bool = False,
    ) -> None:
        """Bind the collaborators; ``reader_is_sut``: the trusted reader runs the same otterdog code as the SUT (the
        web-only keys then have no independent oracle: RoundTripReport.self_checked)."""
        self.sut = sut
        self.reader = reader
        self.rest = rest
        self.render = render
        self.plan = plan
        self.run_id = run_id
        self.discussion_repo = discussion_repo
        self.record = record
        self.restored = restored
        self.trusted_restore = trusted_restore
        self.verify_timeout = verify_timeout
        self.sleep = sleep
        self.clock = clock
        self.reader_is_sut = reader_is_sut

    # --- steps ------------------------------------------------------------------------------------------------------
    def _step(self, report: RoundTripReport, name: str, action: Callable[[], str | None]) -> bool:
        """Run one step: ``action`` returns None when it passed, else the failure detail; exceptions fail it."""
        started = self.clock()
        try:
            problem = action()
        except Exception as exc:  # noqa: BLE001 - recorded: the restore steps must still run
            problem = REDACTOR(f"{type(exc).__name__}: {exc}")[:TAIL_CHARS]
        report.steps.append(StepRecord(name, problem is None, problem or "", round(self.clock() - started, 3)))
        return problem is None

    def _snapshot(self, report: RoundTripReport) -> str | None:
        """Step 1: REST + trusted read, cross-checked."""
        rest = dict(self.rest())
        read = self.reader.read()
        if not read.ok:
            return read.problem()
        snapshot = combine_snapshot(rest, read.values)
        report.snapshot = snapshot
        if snapshot.problems:
            return "the oracles disagree, nothing was changed: " + "; ".join(snapshot.problems)
        return None

    def _apply(
        self, values: Mapping[str, Any], *, before: Mapping[str, Any], keys: Iterable[str], strict: bool = True
    ) -> str | None:
        """Steps 2 and 5: the SUT applies the pinned values; with ``strict`` its plan must change exactly the expected
        web keys (the restore is judged by its verification: a failed set may have changed only some keys)."""
        self.sut.workspace.write_org_config(self.render(values))
        result = self.sut.apply()
        failure = classify_web_failure(result.output)
        applied = result.apply()
        if result.exit_code != 0 or result.timed_out or failure is not None or applied.failed_patches:
            reason = f"{failure.kind}: {failure.hint}" if failure else "; ".join(applied.failed_patches) or "failed"
            return f"apply exit code {result.exit_code} ({reason}):\n{_tail(result.output)}"
        if applied.aborted_validation:
            return f"apply aborted on validation errors:\n{_tail(result.output)}"
        planned = [key for key in settings_changes(result.plan()) if key in mapping.WEB_KEYS]
        wanted = expected_changes(before, values, keys)
        if strict and sorted(planned) != sorted(wanted):
            return f"the SUT planned web changes {sorted(planned)}, expected {sorted(wanted)}"
        return None

    def _verify(self, expected: Mapping[str, Any], keys: Iterable[str]) -> str | None:
        """Steps 3 and 6: REST (polled) and the trusted reader see ``expected`` for ``keys``."""
        keys = list(keys)
        wanted = {key: expected.get(key) for key in keys}
        _values, rest_diffs = wait_rest_values(
            self.rest, wanted, timeout=self.verify_timeout, sleep=self.sleep, clock=self.clock
        )
        read = self.reader.read()
        if not read.ok:
            return "; ".join([*(f"REST {line}" for line in rest_diffs), read.problem() or "trusted read failed"])
        trusted_diffs = mapping.differences(wanted, read.values, keys)
        problems = [*(f"REST {line}" for line in rest_diffs), *(f"trusted {line}" for line in trusted_diffs)]
        return "; ".join(problems) or None

    def _converge(self, values: Mapping[str, Any]) -> str | None:
        """Step 4: the SUT's own ``plan`` without -n is a no-op for every web key."""
        self.sut.workspace.write_org_config(self.render(values))
        result = self.sut.plan()
        failure = classify_web_failure(result.output)
        plan = result.plan()
        if result.exit_code != 0 or result.timed_out or failure is not None or plan.aborted or plan.add is None:
            reason = f" ({failure.kind}: {failure.hint})" if failure else ""
            return f"plan exit code {result.exit_code}{reason}:\n{_tail(result.output)}"
        changed = [key for key in settings_changes(plan) if key in mapping.WEB_KEYS]
        return f"the SUT still plans web changes {changed}" if changed else None

    def _trusted_restore(self, original: Mapping[str, Any]) -> str | None:
        """Fallback: the TRUSTED CLI restores the original values."""
        if self.trusted_restore is None:
            return "no trusted restore configured"
        applied = self.trusted_restore(original)
        if getattr(applied, "failed_patches", None) or getattr(applied, "aborted_validation", False):
            return f"trusted restore failed: {getattr(applied, 'failed_patches', None)}"
        return None

    # --- the scenario -----------------------------------------------------------------------------------------------
    def run(self) -> RoundTripReport:
        """The whole round trip (never raises for step failures: see RoundTripReport.ok and summary())."""
        report = RoundTripReport()
        if not self._step(report, "snapshot", lambda: self._snapshot(report)) or report.snapshot is None:
            return report
        snapshot = report.snapshot
        report.toggles, report.skipped = plan_toggles(
            snapshot.values,
            plan=self.plan,
            run_id=self.run_id,
            discussion_repo=self.discussion_repo,
            readable=snapshot.trusted,
        )
        if not report.toggles:
            report.steps.append(StepRecord("toggles", False, "no web setting can be toggled on this target"))
            return report
        if self.reader_is_sut:
            report.self_checked = sorted(key for key in report.toggles if key not in mapping.REST_READABLE)
        original = snapshot.writable()
        expected = {**original, **report.toggles}
        keys = list(report.toggles)
        if self.record is not None:
            self.record(original)
        report.changed = True
        try:
            if self._step(report, "set", lambda: self._apply(expected, before=original, keys=keys)):
                self._step(report, "verify", lambda: self._verify(expected, keys))
                self._step(report, "converge", lambda: self._converge(expected))
        finally:
            restored = self._step(
                report, "restore", lambda: self._apply(original, before=expected, keys=keys, strict=False)
            )
            restored = restored and self._step(report, "verify-restore", lambda: self._verify(original, keys))
            if not restored and self.trusted_restore is not None:
                restored = self._step(report, "trusted-restore", lambda: self._trusted_restore(original))
                restored = restored and self._step(
                    report, "verify-trusted-restore", lambda: self._verify(original, keys)
                )
            report.restored = restored
            if restored and self.restored is not None:
                self.restored()
        return report


def _tail(text: str) -> str:
    """Redacted tail of a command output."""
    return REDACTOR(text)[-TAIL_CHARS:]
