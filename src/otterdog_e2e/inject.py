"""Jsonnet injected from files: the file references of scenarios and the ad-hoc scenarios of ``otterdog-e2e inject``.

Scenario files may take jsonnet from files instead of inline strings (scenarios.model parses the YAML forms): fragment
entries and step overlays (``{file: <path>, raw: <bool>, vars: <mapping>}``), scenario ``libraries`` (inlined as
``local <name> = (...)`` after the template import, render.py) and the complete configurations of offline steps
(``config``, ``base_config``). A file is read once, when the scenario loads; its path is relative to the scenario file
and must stay inside the project (inside the scenario's directory for a scenario outside any project). Ad-hoc
scenarios (``external`` FileContext) may name any file: they are written by ``otterdog-e2e inject`` from the user's
paths.

The content is kept as a SourceText: a str, so the model and the renderer treat it like an inline snippet, that
remembers its JsonnetFile. ``scenarios.model.render_step`` renders it with the file's own rules (``raw``: never
rendered; ``vars``: extra Jinja variables, their string values rendered with the scenario variables first) and the
model reports every problem as ``<label> (<file>:<line>)``. The content rules themselves (no import statements, dummy
secrets, offline restrictions) live in scenarios.model next to the jsonnet scanner.

The ad-hoc part builds the scenario of an InjectRequest (adhoc_document), and turns the outcome of tests/adhoc into
``<artifacts>/<run>/adhoc/result.json`` (adhoc_result), which the command prints after the session.
"""

from __future__ import annotations

import dataclasses
import functools
import json
import traceback
from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import jinja2
import yaml

from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.otterdog.runner import CliResult
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.scenarios.engine import ScenarioOutcome, StepOutcome
    from otterdog_e2e.scenarios.model import Scenario

FILE_KEYS = ("file", "raw", "vars")
ROLES = ("fragment", "library", "overlay", "config", "base_config")
CONFIG_ROLES = frozenset({"config", "base_config"})
# extra Jinja variables of offline config/base_config files (the renderer's own inputs; org and plan are engine vars)
CONFIG_VARIABLES = ("import_path", "project")
MAX_FILE_BYTES = 512 * 1024  # a jsonnet snippet, library or org config, never a data dump
JINJA_MARKERS = ("{{", "{%", "{#")
TEMPLATE_NAME = "<template>"  # filename of Jinja templates built with from_string (in tracebacks)

# ad-hoc injection (otterdog-e2e inject, tests/adhoc)
ADHOC_ENV = "E2E_ADHOC_SCENARIO"  # path of the generated scenario: tests/adhoc is skipped without it
ADHOC_DIR = "adhoc"  # below the run's scratch dir (scenario.yaml) and artifacts dir (result.json, workspace/)
ADHOC_SCENARIO_FILE = "scenario.yaml"
ADHOC_RESULT_FILE = "result.json"
ADHOC_WORKSPACE_DIR = "workspace"
ADHOC_ID = "adhoc.inject"
ADHOC_STEP = "inject"
MAX_LISTED_OBJECTS = 50


class InjectError(ValueError):
    """A file reference or its content breaks a rule (the message names the file, and the line when known)."""


@dataclass(frozen=True)
class JsonnetFile:
    """A jsonnet file referenced by a scenario: where (``label``), which file and how to render it."""

    label: str  # place in the scenario: fragments.repositories[0], overlay[1], libraries.e2e, config, base_config
    path: Path  # resolved path
    display: str  # path in messages: relative to the containment root, absolute for ad-hoc files
    role: str = "fragment"  # one of ROLES
    raw: bool = False  # never Jinja-rendered
    vars: Mapping[str, Any] = field(default_factory=dict)  # extra Jinja variables of this file

    def location(self, line: int | None = None) -> str:
        """``<label> (<display>[:<line>])`` for messages."""
        return f"{self.label} ({self.display}{f':{line}' if line else ''})"


class SourceText(str):
    """The text of a JsonnetFile: a str (used like an inline snippet) that remembers its file and whether it was
    rendered already (render_step renders it once, with the file's rules)."""

    origin: JsonnetFile
    rendered: bool

    def __new__(cls, text: str, origin: JsonnetFile, rendered: bool = False) -> Self:
        """Wrap ``text`` read from (or rendered for) ``origin``."""
        obj = super().__new__(cls, text)
        obj.origin = origin
        obj.rendered = rendered
        return obj

    def __reduce__(self) -> tuple[Any, ...]:
        """Pickle support (the str value alone would lose the origin)."""
        return (SourceText, (str(self), self.origin, self.rendered))

    def __copy__(self) -> Self:
        """Immutable: the copy is the object itself."""
        return self

    def __deepcopy__(self, memo: dict[int, Any]) -> Self:
        """Immutable: the copy is the object itself."""
        return self


@dataclass(frozen=True)
class FileContext:
    """Where the file references of one scenario file resolve: ``base_dir`` (the scenario's directory), the
    containment ``root`` (the project, or the scenario's directory outside any project) or ``external`` (ad-hoc
    scenarios: absolute paths anywhere)."""

    base_dir: Path
    external: bool = False

    @functools.cached_property
    def root(self) -> Path:
        """Containment root: the otterdog-e2e project above base_dir, else base_dir itself."""
        from otterdog_e2e.settings import find_project_root

        try:
            return find_project_root(self.base_dir).resolve()
        except FileNotFoundError:
            return self.base_dir.resolve()

    def resolve(self, value: str) -> tuple[Path, str]:
        """(resolved path, display path) of a reference; InjectError when absolute (scenarios), missing or outside."""
        if not value.strip():
            raise InjectError("expected a file path, got an empty string")
        candidate = Path(value).expanduser() if self.external else Path(value)
        if candidate.is_absolute() and not self.external:
            raise InjectError(f"{value!r} is absolute: scenario file paths are relative to {self.base_dir}")
        try:
            resolved = (self.base_dir / candidate).resolve(strict=True)
        except (OSError, RuntimeError):
            raise InjectError(f"{value!r} not found (relative to {self.base_dir})") from None
        if self.external:
            return resolved, str(resolved)
        if not resolved.is_relative_to(self.root):
            raise InjectError(
                f"{value!r} resolves to {resolved}, outside {self.root}: files must stay inside the project"
            )
        return resolved, resolved.relative_to(self.root).as_posix()


def read_jsonnet(path: Path, display: str) -> str:
    """UTF-8 text of a regular, non-empty file of at most MAX_FILE_BYTES (InjectError otherwise)."""
    if not path.is_file():
        raise InjectError(f"{display} is not a regular file")
    size = path.stat().st_size
    if size > MAX_FILE_BYTES:
        raise InjectError(f"{display} has {size} bytes, more than {MAX_FILE_BYTES}: not a jsonnet snippet")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise InjectError(f"{display} is not UTF-8 text") from None
    except OSError as exc:
        raise InjectError(f"cannot read {display}: {exc.strerror or exc}") from None
    if not text.strip():
        raise InjectError(f"{display} is empty")
    return text


def load_source(
    value: str,
    files: FileContext,
    *,
    label: str,
    role: str,
    raw: bool = False,
    variables: Mapping[str, Any] | None = None,
) -> SourceText:
    """Resolve and read the file of a reference: its SourceText (InjectError for paths and unreadable files)."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}, expected one of {ROLES}")
    path, display = files.resolve(value)
    origin = JsonnetFile(label, path, display, role=role, raw=raw, vars=dict(variables or {}))
    return SourceText(read_jsonnet(path, display), origin)


# --- rendering -------------------------------------------------------------------------------------------------------
def has_jinja(text: str) -> bool:
    """True when ``text`` contains Jinja markup (plain strings are never passed through Jinja)."""
    return any(marker in text for marker in JINJA_MARKERS)


def jinja_error_line(exc: BaseException) -> int | None:
    """Template line of a Jinja error: the syntax error's line, else the innermost template frame of the traceback."""
    if isinstance(exc, jinja2.TemplateSyntaxError):
        return exc.lineno
    frames = [frame for frame in traceback.extract_tb(exc.__traceback__) if frame.filename == TEMPLATE_NAME]
    return frames[-1].lineno if frames else None


def _render_string(environment: jinja2.Environment, text: str, variables: Mapping[str, Any]) -> str:
    """Render one string (unchanged without Jinja markup)."""
    return environment.from_string(text).render(**variables) if has_jinja(text) else text


def render_value(environment: jinja2.Environment, value: Any, variables: Mapping[str, Any]) -> Any:
    """Copy of a ``vars`` value with every string (nested ones included) rendered with ``variables``."""
    if isinstance(value, str):
        return _render_string(environment, value, variables)
    if isinstance(value, list):
        return [render_value(environment, item, variables) for item in value]
    if isinstance(value, Mapping):
        return {key: render_value(environment, item, variables) for key, item in value.items()}
    return value


def render_source(environment: jinja2.Environment, text: SourceText, variables: Mapping[str, Any]) -> SourceText:
    """Render a SourceText once: its ``vars`` with ``variables`` first, then the text with both (unless raw)."""
    if text.rendered:
        return text
    origin = text.origin
    extra: dict[str, Any] = {}
    for name, value in origin.vars.items():
        try:
            extra[name] = render_value(environment, value, variables)
        except jinja2.TemplateError as exc:
            raise InjectError(f"{origin.location()}: cannot render vars.{name}: {exc}") from None
    if origin.raw:
        return SourceText(str(text), origin, rendered=True)
    try:
        rendered = _render_string(environment, str(text), {**variables, **extra})
    except jinja2.TemplateError as exc:
        raise InjectError(f"{origin.location(jinja_error_line(exc))}: cannot render: {exc}") from None
    return SourceText(rendered, origin, rendered=True)


# --- ad-hoc injection (otterdog-e2e inject) --------------------------------------------------------------------------
@dataclass
class InjectRequest:
    """What ``otterdog-e2e inject`` injects: user files (any path, resolved) and the run mode."""

    fragments: list[tuple[str, Path]] = field(default_factory=list)  # (fragment kind, file)
    libraries: list[tuple[str, Path]] = field(default_factory=list)  # (local name, file)
    overlays: list[Path] = field(default_factory=list)
    config: Path | None = None  # offline only: complete org config
    base: Path | None = None  # offline only: -BASE config of local-plan (default: the bare offline org)
    live: bool = False
    apply: bool = False  # live only: guarded apply, converge and cleanup (default: validate + plan)
    keep: bool = False  # no cleanup (live apply)
    variables: dict[str, Any] = field(default_factory=dict)  # scenario variables (plan included)

    @property
    def mode(self) -> str:
        """``offline``, ``live-plan`` or ``live-apply``."""
        if not self.live:
            return "offline"
        return "live-apply" if self.apply else "live-plan"


def _file_entry(path: Path) -> dict[str, str]:
    """The ``{file: <absolute path>}`` reference of a user file."""
    return {"file": str(path.expanduser().resolve())}


def adhoc_document(request: InjectRequest) -> dict[str, Any]:
    """The scenario of an injection (one step ``inject``): offline (validate, local-plan against the bare org or
    ``base``, show), live plan-only (validate + plan, no apply, no cleanup) or live apply (plan expecting changes,
    apply, converge, cleanup unless ``keep``). Live injections are org_level: unfiltered plans see every change of the
    injected content, and the cleanup is a full (guarded) baseline reset."""
    fragments: dict[str, list[dict[str, str]]] = {}
    for kind, path in request.fragments:
        fragments.setdefault(kind, []).append(_file_entry(path))
    step: dict[str, Any] = {"name": ADHOC_STEP}
    if fragments:
        step["fragments"] = fragments
    if request.overlays:
        step["overlay"] = [_file_entry(path) for path in request.overlays]
    if request.config is not None:
        step["config"] = _file_entry(request.config)
    step["validate"] = {"ok": True}
    document: dict[str, Any] = {
        "id": ADHOC_ID,
        "title": "otterdog-e2e inject",
        "description": f"Generated by otterdog-e2e inject ({request.mode}).",
        "tier": "cli" if request.live else "offline",
        "tags": ["adhoc"],
    }
    if request.variables:
        document["variables"] = dict(request.variables)
    if request.libraries:
        document["libraries"] = {name: _file_entry(path) for name, path in request.libraries}
    if request.live:
        document["org_level"] = True
        document["cleanup"] = "auto" if request.apply and not request.keep else "none"
        if request.apply:
            step.update({"plan": {"expect": "changes"}, "apply": {"expect": "ok"}, "converge": True})
        else:
            step.update({"plan": {"expect": "any"}, "apply": None, "converge": False})
    else:
        if request.base is not None:
            step["base_config"] = _file_entry(request.base)
        else:
            step["base_fragments"] = {}
        step["plan"] = {"expect": "any"}
    document["steps"] = [step]
    return document


def write_adhoc_scenario(request: InjectRequest, directory: Path) -> Path:
    """Write the scenario of ``request`` as ``<directory>/scenario.yaml`` (0600, directory 0700) and return its path."""
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    path = directory / ADHOC_SCENARIO_FILE
    text = "# generated by otterdog-e2e inject\n" + yaml.safe_dump(adhoc_document(request), sort_keys=False)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


def plan_summary(result: CliResult) -> dict[str, Any]:
    """The ``Plan:`` line, counts and object headers of a plan/local-plan result."""
    plan = result.plan()
    summary = None
    if plan.add is not None:
        summary = f"Plan: {plan.add} to add, {plan.change} to change, {plan.delete} to delete."
    headers = [obj.header.strip().removesuffix("{").rstrip() for obj in plan.objects]
    return {
        "exit_code": result.exit_code,
        "summary": summary,
        "counts": {"add": plan.add, "change": plan.change, "delete": plan.delete},
        "objects": headers[:MAX_LISTED_OBJECTS],
        "more_objects": max(0, len(headers) - MAX_LISTED_OBJECTS),
        "aborted": plan.aborted,
    }


def validation_summary(result: CliResult) -> dict[str, Any]:
    """Outcome, counts and the first error messages of a validate result."""
    validation = result.validation()
    return {
        "exit_code": result.exit_code,
        "ok": validation.ok,
        "errors": validation.errors,
        "warnings": validation.warnings,
        "load_error": validation.load_error,
        "messages": [message.text.strip().splitlines()[0] for message in validation.messages if message.text][:10],
    }


def apply_summary(result: CliResult) -> dict[str, Any]:
    """Counts of the ``Executed plan:`` line and the failed patches of an apply result."""
    applied = result.apply()
    return {
        "exit_code": result.exit_code,
        "counts": {"add": applied.added, "change": applied.changed, "delete": applied.deleted},
        "no_changes": applied.no_changes,
        "failed_patches": [patch.strip().splitlines()[0] for patch in applied.failed_patches if patch.strip()][:10],
    }


def _step_report(step: StepOutcome) -> dict[str, Any]:
    """Per-command summaries of one step outcome (validate, plan/local-plan, apply, converge)."""
    report: dict[str, Any] = {"name": step.name, "failed_phase": step.failed_phase, "notes": list(step.notes)}
    for command, result in step.results.items():
        if command == "validate":
            report["validate"] = validation_summary(result)
        elif command in ("plan", "local-plan", "converge"):
            report[command] = plan_summary(result)
        elif command == "apply":
            report["apply"] = apply_summary(result)
        else:
            report[command] = {"exit_code": result.exit_code}
    return report


def adhoc_result(
    outcome: ScenarioOutcome | None,
    *,
    mode: str,
    config: Path | None,
    base_config: Path | None,
    error: str | None = None,
) -> dict[str, Any]:
    """The result.json document of an injection (paths of the exported configs, step summaries, failures)."""
    return {
        "mode": mode,
        "config": str(config) if config is not None else None,
        "base_config": str(base_config) if base_config is not None else None,
        "skipped": outcome.skipped if outcome is not None else None,
        "failures": list(outcome.failures) if outcome is not None else [],
        "steps": [_step_report(step) for step in outcome.steps] if outcome is not None else [],
        "error": error,
    }


def write_adhoc_result(directory: Path, result: Mapping[str, Any]) -> Path:
    """Write ``result`` (redacted) to ``<directory>/result.json`` and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / ADHOC_RESULT_FILE
    path.write_text(REDACTOR(json.dumps(result, indent=2, sort_keys=True, default=str)) + "\n", encoding="utf-8")
    return path


def plan_only(scenario: Scenario) -> Scenario:
    """Copy of an injected scenario that plans but never applies (no apply, state, converge nor cleanup)."""
    steps = [dataclasses.replace(step, apply=None, state=[], converge=False) for step in scenario.steps]
    return dataclasses.replace(scenario, steps=steps, cleanup="none")


def foreign_additions(outcome: ScenarioOutcome, run_id: str) -> list[str]:
    """Headers of the objects the plans of ``outcome`` add without carrying ``run_id`` (named by hand: the guarded
    cleanup could never remove them, so a live injection refuses to apply them)."""
    found = []
    for step in outcome.steps:
        result = step.results.get("plan")
        if result is None:
            continue
        found += [
            obj.header.strip().removesuffix("{").rstrip()
            for obj in result.plan().objects
            if obj.op == "add" and obj.run_id != run_id
        ]
    return found


def unrestorable_changes(outcome: ScenarioOutcome, *, repos: Collection[str], teams: Collection[str]) -> list[str]:
    """Headers of the objects the plans of ``outcome`` change although they carry no run id and the baseline does not
    declare them (baseline.unmanaged_changes: an extra protected repository, a team or org object named by hand):
    the cleanup's baseline reset could never restore them, so a live injection refuses to apply them (DESTR-07)."""
    from otterdog_e2e.otterdog.baseline import unmanaged_changes

    found: list[str] = []
    for step in outcome.steps:
        result = step.results.get("plan")
        if result is not None:
            found += unmanaged_changes(result.plan(), repos=repos, teams=teams)
    return found


def adhoc_mode(scenario: Scenario) -> str:
    """``offline``, ``live-plan`` or ``live-apply`` (a step applies) of an injected scenario."""
    if not scenario.is_live:
        return "offline"
    return "live-apply" if any(step.apply is not None for step in scenario.steps) else "live-plan"


def record_adhoc_run(
    directory: Path,
    *,
    scenario: Scenario,
    workspace: ConfigWorkspace,
    outcome: ScenarioOutcome | None,
    error: str | None = None,
) -> Path:
    """Export the rendered configuration (``workspace/``), a copy of the scenario (``scenario.yaml.txt``) and
    result.json below ``directory`` (an artifacts dir: redacted text files only); returns the result.json path."""
    exported = directory / ADHOC_WORKSPACE_DIR
    workspace.export_to(exported)
    if scenario.source.is_file():
        copy = directory / f"{ADHOC_SCENARIO_FILE}.txt"
        copy.write_text(REDACTOR(scenario.source.read_text(encoding="utf-8")), encoding="utf-8")
    config, base_config = config_files(exported)
    result = adhoc_result(outcome, mode=adhoc_mode(scenario), config=config, base_config=base_config, error=error)
    return write_adhoc_result(directory, result)


def read_adhoc_result(directory: Path) -> dict[str, Any] | None:
    """result.json of an injection, None when the test did not write it (skipped or failed setup)."""
    path = directory / ADHOC_RESULT_FILE
    if not path.is_file():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else None


def result_lines(result: Mapping[str, Any]) -> list[str]:
    """Human summary of a result.json: rendered configs, validation and plan of each step, failures."""
    lines = []
    for key, label in (("config", "rendered config"), ("base_config", "BASE config")):
        if result.get(key):
            lines.append(f"{label}: {result[key]}")
    for step in result.get("steps") or []:
        validate = step.get("validate")
        if validate:
            state = "ok" if validate.get("ok") else ("load error" if validate.get("load_error") else "failed")
            lines.append(
                f"validate: {state} ({validate.get('errors')} error(s), {validate.get('warnings')} warning(s))"
            )
            lines += [f"  {message}" for message in validate.get("messages") or [] if not validate.get("ok")]
        for command in ("local-plan", "plan", "converge"):
            plan = step.get(command)
            if not plan:
                continue
            lines.append(f"{command}: {plan.get('summary') or 'no Plan: summary'} (exit code {plan.get('exit_code')})")
            lines += [f"  {header}" for header in plan.get("objects") or []]
            if plan.get("more_objects"):
                lines.append(f"  ... and {plan['more_objects']} more object(s)")
        applied = step.get("apply")
        if applied:
            counts = applied.get("counts") or {}
            done = (
                "no changes"
                if applied.get("no_changes")
                else (f"{counts.get('add')} added, {counts.get('change')} changed, {counts.get('delete')} deleted")
            )
            lines.append(f"apply: {done} (exit code {applied.get('exit_code')})")
            lines += [f"  failed patch: {patch}" for patch in applied.get("failed_patches") or []]
    return lines


def config_files(workspace_dir: Path) -> tuple[Path | None, Path | None]:
    """(org config, -BASE config) copies exported to ``workspace_dir`` (ConfigWorkspace.export_to), None if absent."""
    found = sorted(workspace_dir.glob("*.jsonnet.txt")) if workspace_dir.is_dir() else []
    base = sorted(workspace_dir.glob("*.jsonnet-BASE.txt")) if workspace_dir.is_dir() else []
    return (found[0] if found else None), (base[0] if base else None)


def parse_assignment(value: str, what: str) -> tuple[str, str]:
    """``NAME=VALUE`` -> (NAME, VALUE); InjectError when the ``=`` or a side is missing."""
    name, sep, rest = value.partition("=")
    if not sep or not name.strip() or not rest.strip():
        raise InjectError(f"{what}: expected NAME=VALUE, got {value!r}")
    return name.strip(), rest.strip()


def parse_variables(assignments: Sequence[str]) -> dict[str, Any]:
    """``--var NAME=VALUE`` options: values parsed as YAML (``5`` is a number, ``[a, b]`` a list, ``x`` a string)."""
    variables: dict[str, Any] = {}
    for assignment in assignments:
        name, text = parse_assignment(assignment, "--var")
        try:
            variables[name] = yaml.safe_load(text)
        except yaml.YAMLError:
            variables[name] = text
    return variables
