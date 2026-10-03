"""Ad-hoc injection (``otterdog-e2e inject``): one generated scenario, run with the regular fixtures and safety.

The module is skipped unless E2E_ADHOC_SCENARIO names the scenario YAML that ``otterdog-e2e inject`` wrote into the
run's scratch directory. Its files may lie anywhere (scenarios.model.load_adhoc_scenario); every content rule of the
scenario model still applies. Offline scenarios run with the OfflineEngine of the SUT (validate --local, local-plan
--local against the -BASE config, show --local; no network); live ones with the session's ScenarioEngine exactly like
tests/cli: org lease, baseline reset, plan, and for ``--apply`` the guarded apply, converge and the cleanup by the
trusted reset CLI. Before a live apply, a plan-only pass refuses objects the injection would add without this run's
id: user files are not checked like the repository's scenarios, and the guarded cleanup could never remove them.
Whatever happens, the test exports the rendered configuration and writes ``<artifacts>/<run>/adhoc/result.json``
(validation and plan summaries, failures), which the command prints.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from otterdog_e2e import inject
from otterdog_e2e.context import describe_error, get_context
from otterdog_e2e.scenarios.collect import scenario_params
from otterdog_e2e.scenarios.engine import ScenarioFailedError, ScenarioOutcome
from otterdog_e2e.scenarios.model import Scenario, load_adhoc_scenario
from otterdog_e2e.sut.cli_install import InstalledCli

SCENARIO_FILE = os.environ.get(inject.ADHOC_ENV, "")
if not SCENARIO_FILE:
    pytest.skip(
        f"{inject.ADHOC_ENV} is not set: tests/adhoc only runs the scenario written by otterdog-e2e inject",
        allow_module_level=True,
    )


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Parametrize ``scenario`` with the injected scenario (marks of collect.scenario_marks: live or offline, ...)."""
    if "scenario" in metafunc.fixturenames:
        metafunc.parametrize("scenario", scenario_params([load_adhoc_scenario(Path(SCENARIO_FILE))]))


def test_adhoc_injection(scenario: Scenario, sut: InstalledCli, request: pytest.FixtureRequest) -> None:
    """Run the injected scenario (OfflineEngine or the live ScenarioEngine) and record its result for the command."""
    engine = request.getfixturevalue("scenario_engine" if scenario.is_live else "offline_engine")
    directory = get_context(request.config).artifacts_dir / inject.ADHOC_DIR
    outcome: ScenarioOutcome | None = None
    error: str | None = None
    try:
        if scenario.is_live:
            reason = engine.skip_reason(scenario)
            if reason:
                pytest.skip(reason)
        if inject.adhoc_mode(scenario) == "live-apply":
            outcome = engine.run(inject.plan_only(scenario), cleanup=False)
            foreign = inject.foreign_additions(outcome, engine.run_ctx.run_id)
            if foreign:
                pytest.fail(
                    f"refusing to apply: the injection adds objects without the run prefix {engine.run_ctx.prefix} "
                    f"(name them with {{{{ p }}}}, {{{{ P }}}} or {{{{ hook_base }}}}): {'; '.join(foreign)}",
                    pytrace=False,
                )
            baseline = engine.baseline
            changed = inject.unrestorable_changes(outcome, repos=baseline.baseline_repos, teams=baseline.baseline_teams)
            if changed:
                pytest.fail(
                    "refusing to apply: the injection changes objects without the run prefix that the baseline reset "
                    f"never restores (protected or unmanaged repositories, teams, org objects): {'; '.join(changed)}",
                    pytrace=False,
                )
        outcome = engine.run(scenario)  # the live engine raises ScenarioFailedError after its cleanup
        if outcome.skipped:
            pytest.skip(outcome.skipped)
        outcome.raise_for_failures()
    except ScenarioFailedError as exc:
        outcome = exc.outcome
        raise
    except Exception as exc:
        error = describe_error(exc)
        raise
    finally:
        workspace = engine.cli.workspace if scenario.is_live else engine.workspace
        inject.record_adhoc_run(directory, scenario=scenario, workspace=workspace, outcome=outcome, error=error)
