"""``otterdog-e2e inject`` (SPEC 16): jsonnet files injected into a rendered configuration, without a scenario.

inject_request checks the options (fragments, libraries, overlays, a complete --config, variables); the ad-hoc
scenario is written to the run's scratch and checked by the scenario model before any session starts, then tests/adhoc
runs it through pytest in-process (run_pytest): offline in the sandbox, or on a live target with the org lease,
baseline reset, guarded apply and cleanup. echo_inject_report prints the rendered configurations and the result.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from otterdog_e2e.cli.common import (
    RUN_ID_ARG_RE,
    _check_addopts,
    _echo,
    _handled,
    _settings,
    _single_target,
    main,
)
from otterdog_e2e.cli.run import run_pytest

if TYPE_CHECKING:
    from otterdog_e2e.inject import InjectRequest

# --- inject: jsonnet files injected into a rendered configuration, without a scenario ------------------------------
INJECT_FILE = click.Path(exists=True, dir_okay=False, path_type=Path)
INJECT_PLANS = ("free", "team", "enterprise")  # capabilities.PLANS (checked in inject_request)


def _existing_file(value: str, option: str) -> Path:
    """Resolved path of the existing file an option value names (UsageError otherwise)."""
    path = Path(value).expanduser()
    if not path.is_file():
        raise click.UsageError(f"{option}: {value!r} is not an existing file")
    return path.resolve()


def inject_request(
    *,
    live: bool,
    fragments: Sequence[str],
    libraries: Sequence[str],
    overlays: Sequence[Path],
    config: Path | None,
    base: Path | None,
    plan: str | None,
    variables: Sequence[str],
    apply_: bool,
    keep: bool,
) -> InjectRequest:
    """The InjectRequest of the inject options (UsageError for inconsistent options; files may lie anywhere)."""
    from otterdog_e2e.capabilities import PLANS
    from otterdog_e2e.inject import InjectError, InjectRequest, parse_assignment, parse_variables
    from otterdog_e2e.otterdog.render import FRAGMENT_KEYS, library_name_problem

    if not (fragments or overlays or config):
        raise click.UsageError("nothing to inject: give --fragment KIND=FILE, --overlay FILE or --config FILE")
    if live and (config or base):
        raise click.UsageError("--config and --base are offline only (live configs are rendered on the baseline)")
    if apply_ and not live:
        raise click.UsageError("--apply needs a live target (--target without --offline)")
    if config and (fragments or overlays):
        raise click.UsageError("--config replaces the rendered configuration: drop --fragment and --overlay")
    if plan is not None and plan not in PLANS:
        raise click.UsageError(f"--plan: {plan!r} is not one of {', '.join(PLANS)}")
    try:
        kinds = [parse_assignment(item, "--fragment") for item in fragments]
        names = [parse_assignment(item, "--library") for item in libraries]
        extra = parse_variables(variables)
    except InjectError as exc:
        raise click.UsageError(str(exc)) from None
    unknown = [kind for kind, _ in kinds if kind not in FRAGMENT_KEYS]
    if unknown:
        raise click.UsageError(f"--fragment: unknown kind(s) {', '.join(unknown)}; expected {', '.join(FRAGMENT_KEYS)}")
    for name, _ in names:
        problem = library_name_problem(name)
        if problem:
            raise click.UsageError(f"--library: {problem}")
    if len({name for name, _ in names}) != len(names):
        raise click.UsageError("--library: each NAME may be given once")
    if "plan" in extra:
        raise click.UsageError("--var plan=...: use --plan")
    if plan:
        extra["plan"] = plan
    return InjectRequest(
        fragments=[(kind, _existing_file(path, "--fragment")) for kind, path in kinds],
        libraries=[(name, _existing_file(path, "--library")) for name, path in names],
        overlays=[path.resolve() for path in overlays],
        config=config.resolve() if config is not None else None,
        base=base.resolve() if base is not None else None,
        live=live,
        apply=apply_,
        keep=keep,
        variables=extra,
    )


def inject_pytest_args(
    project_root: Path,
    *,
    run_id: str,
    target: str | None,
    sut: str | None,
    reset_sut: str | None,
    artifacts: str | None,
    keep: bool,
    no_reset: bool,
) -> list[str]:
    """pytest.main arguments of an injection: tests/adhoc, short tracebacks (the command prints its own summary) and
    the --e2e-* options; the target and the selection and differential options are always given (empty), so their
    E2E_* environment fallbacks never apply."""
    args = [
        str(project_root / "tests" / "adhoc"),
        "--tb=short",
        f"--e2e-run-id={run_id}",
        f"--e2e-target={target or ''}",
        "--e2e-tags=",
        "--e2e-scenario=",
        "--e2e-base-sut=",
        "--e2e-change=",
    ]
    values = {"--e2e-sut": sut, "--e2e-reset-sut": reset_sut, "--e2e-artifacts": artifacts}
    args += [f"{flag}={value}" for flag, value in values.items() if value]
    return args + [flag for flag, enabled in (("--e2e-keep", keep), ("--e2e-no-reset", no_reset)) if enabled]


def inject_command_line(
    request: InjectRequest, *, target: str | None, sut: str | None, reset_sut: str | None, no_reset: bool
) -> str:
    """The ``otterdog-e2e inject`` command of a request (run.json ``command``: summary.md "How to reproduce")."""
    options = {"--target": target, "--sut": sut, "--reset-sut": reset_sut}
    argv = ["otterdog-e2e", "inject", *(part for flag, value in options.items() if value for part in (flag, value))]
    argv += [part for kind, path in request.fragments for part in ("--fragment", f"{kind}={path}")]
    argv += [part for name, path in request.libraries for part in ("--library", f"{name}={path}")]
    argv += [part for path in request.overlays for part in ("--overlay", str(path))]
    files = {"--config": request.config, "--base": request.base}
    argv += [part for flag, path in files.items() if path is not None for part in (flag, str(path))]
    variables = dict(request.variables)
    plan = variables.pop("plan", None)
    if plan:
        argv += ["--plan", str(plan)]
    for name, value in variables.items():
        argv += ["--var", f"{name}={value if isinstance(value, str) else json.dumps(value)}"]
    flags = (("--apply", request.apply), ("--keep", request.keep), ("--no-reset", no_reset))
    return shlex.join([*argv, *(flag for flag, enabled in flags if enabled)])


def adhoc_item(run_dir: Path) -> dict[str, Any] | None:
    """The results.jsonl line of the injection's test item, None when it did not run."""
    path = run_dir / "results.jsonl"
    found = None
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                data = json.loads(line)
            except ValueError:
                continue
            if isinstance(data, dict) and "tests/adhoc/" in str(data.get("nodeid", "")):
                found = data
    return found


def echo_inject_report(run_dir: Path, *, mode: str, code: int, print_config: bool) -> None:
    """After the session: rendered config paths, validation and plan summaries, the result (and the configs)."""
    from otterdog_e2e.inject import ADHOC_DIR, read_adhoc_result, result_lines

    sys.stdout.flush()  # pytest's summary first
    result = read_adhoc_result(run_dir / ADHOC_DIR) or {}
    _echo(f"otterdog-e2e inject ({mode}): artifacts {run_dir}")
    for line in result_lines(result):
        _echo(line)
    item = adhoc_item(run_dir)
    if item is None:
        _echo(f"result: not run (pytest exit code {code}), see {run_dir / 'summary.md'}")
    elif result.get("failures"):
        _echo(f"result: {item.get('outcome')}")
        for failure in result["failures"]:
            _echo(f"  - {failure}")
    else:
        detail = item.get("failure") or item.get("reason") or result.get("error")
        _echo(f"result: {item.get('outcome')}" + (f": {detail}" if detail else ""))
    if print_config:
        for key in ("config", "base_config"):
            if result.get(key) and Path(result[key]).is_file():
                _echo(f"--- {result[key]}")
                _echo(Path(result[key]).read_text(encoding="utf-8").rstrip("\n"))


@main.command("inject")
@click.option("--target", default=None, help="target name or path: live injection (validate + plan; --apply applies)")
@click.option("--sut", "sut_spec", default=None, help="SUT spec (default: release:latest)")
@click.option("--reset-sut", default=None, help="trusted reset SUT spec (live)")
@click.option(
    "--fragment",
    "fragments",
    multiple=True,
    metavar="KIND=FILE",
    help="fragment file of KIND (repositories, settings, secrets, variables, webhooks, ...), repeatable",
)
@click.option(
    "--library",
    "libraries",
    multiple=True,
    metavar="NAME=FILE",
    help="library file inlined as 'local NAME = (...);' after the template import, repeatable",
)
@click.option("--overlay", "overlays", multiple=True, type=INJECT_FILE, help="object mixin applied last, repeatable")
@click.option("--config", default=None, type=INJECT_FILE, help="offline: complete org config replacing the rendering")
@click.option("--base", default=None, type=INJECT_FILE, help="offline: -BASE config of local-plan (default: bare org)")
@click.option("--plan", default=None, help=f"plan rendered into settings.plan: {', '.join(INJECT_PLANS)}")
@click.option("--var", "variables", multiple=True, metavar="NAME=VALUE", help="Jinja variable (YAML value), repeatable")
@click.option("--offline", is_flag=True, help="offline injection (the default without --target)")
@click.option("--apply", "apply_", is_flag=True, help="live: guarded apply, converge, cleanup (default: validate+plan)")
@click.option("--keep", is_flag=True, help="no cleanup: keep the run's objects (live) and scratch directory")
@click.option("--no-reset", is_flag=True, help="live: skip the baseline reset at session start")
@click.option("--print", "print_config", is_flag=True, help="print the rendered configuration after the run")
@click.option("--run-id", default=None, help="run id (default: a new one)")
@click.option("--artifacts", default=None, help="artifacts root directory")
@_handled
def inject_command(
    target: str | None,
    sut_spec: str | None,
    reset_sut: str | None,
    fragments: tuple[str, ...],
    libraries: tuple[str, ...],
    overlays: tuple[Path, ...],
    config: Path | None,
    base: Path | None,
    plan: str | None,
    variables: tuple[str, ...],
    offline: bool,
    apply_: bool,
    keep: bool,
    no_reset: bool,
    print_config: bool,
    run_id: str | None,
    artifacts: str | None,
) -> None:
    """Inject jsonnet files without writing a scenario: validate and plan them offline, or on a live target.

    The files (any path) go through the scenario model's rules; the generated scenario runs in tests/adhoc with the
    regular fixtures and safety (offline sandbox; live: org lease, baseline reset, guarded apply, cleanup).
    """
    from otterdog_e2e.inject import ADHOC_DIR, ADHOC_ENV, write_adhoc_scenario
    from otterdog_e2e.naming import new_run_context
    from otterdog_e2e.scenarios.model import ScenarioError, load_adhoc_scenario

    target = _single_target(target)  # a list of targets: refused before the ad-hoc scenario is written
    if offline and target:
        raise click.UsageError("--offline and --target exclude each other (an offline injection uses no target)")
    if run_id is not None and not RUN_ID_ARG_RE.match(run_id):
        raise click.UsageError(f"--run-id {run_id!r} is not a run id ({RUN_ID_ARG_RE.pattern})")
    _check_addopts(os.environ)
    live = bool(target)
    request = inject_request(
        live=live,
        fragments=fragments,
        libraries=libraries,
        overlays=overlays,
        config=config,
        base=base,
        plan=plan,
        variables=variables,
        apply_=apply_,
        keep=keep,
    )
    settings = _settings()
    run_id = run_id or new_run_context().run_id
    scratch = settings.scratch(run_id)
    path = write_adhoc_scenario(request, scratch / ADHOC_DIR)
    try:
        load_adhoc_scenario(path)  # every content rule, with <file>:<line> messages, before any session starts
    except ScenarioError as exc:
        if not keep:
            shutil.rmtree(scratch, ignore_errors=True)
        raise click.ClickException(str(exc).removeprefix(f"{path}: ")) from None
    args = inject_pytest_args(
        settings.project_root,
        run_id=run_id,
        target=target if live else None,
        sut=sut_spec,
        reset_sut=reset_sut,
        artifacts=artifacts,
        keep=keep,
        no_reset=no_reset,
    )
    command = inject_command_line(request, target=target, sut=sut_spec, reset_sut=reset_sut, no_reset=no_reset)
    previous = os.environ.get(ADHOC_ENV)
    os.environ[ADHOC_ENV] = str(path)
    try:
        code = run_pytest(args, command=command)
    finally:
        if previous is None:
            os.environ.pop(ADHOC_ENV, None)
        else:
            os.environ[ADHOC_ENV] = previous
    root = Path(artifacts).expanduser().resolve() if artifacts else settings.artifacts_root
    echo_inject_report(root / run_id, mode=request.mode, code=code, print_config=print_config)
    sys.exit(code)
