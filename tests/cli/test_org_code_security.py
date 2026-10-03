"""cli.org.code-security-defaults (org-settings.code-security-defaults, P2, org_level): disabling the organization's
default code security configurations.

``settings.default_code_security_configurations_disabled`` is read as "the org has no default configuration"
(GET /orgs/{org}/code-security/configurations/defaults is empty, otterdog/providers/github/rest/org_client.py:59-61)
and true makes otterdog set every default configuration to 'none' (org_client.py:683-707). The setting only disables:
a change from true to false is dropped from the plan (otterdog/models/organization_settings.py:266-273). The template
value true is the baseline, so the test first makes a run configuration (an e2e-named code security configuration
created with the admin Mutator) the default for new public repositories, then plans the baseline: otterdog plans
'false -> true', the apply leaves no default configuration (oracle), and the plan converges. Configuring false while
no default exists plans nothing.

otterdog's apply sets EVERY default configuration to 'none', foreign ones included: the test skips when the org has a
default configuration that is not an e2e one. org_level: the teardown is a full baseline reset; the run configuration
is deleted afterwards (the janitor sweeps leftovers too).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.naming import is_e2e_name
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import ConfigFragments

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import PlanObject, PlanResult
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli

pytestmark = [pytest.mark.org_level]

KEY = "default_code_security_configurations_disabled"
STATE_TIMEOUT = 90.0
STATE_INTERVAL = 3.0
TAIL = 3000


@pytest.fixture
def org_reset(e2e: E2EContext, baseline: BaselineManager) -> Iterator[None]:
    """org_level teardown: full baseline reset with the trusted reset CLI (skipped with --e2e-keep)."""
    yield
    if not e2e.options.keep:
        baseline.reset()


def default_names(oracle: Oracle) -> list[str]:
    """Names of the org's default code security configurations."""
    entries = oracle.code_security_default_configurations()
    return [str((entry.get("configuration") or {}).get("name") or "") for entry in entries]


def wait_defaults(oracle: Oracle, until: Callable[[list[str]], bool], what: str) -> list[str]:
    """Poll the default configurations until ``until`` holds (WaitTimeoutError after STATE_TIMEOUT)."""
    return waiting.poll(
        lambda: default_names(oracle), until=until, timeout=STATE_TIMEOUT, interval=STATE_INTERVAL, what=what
    )


def settings_objects(plan: PlanResult) -> list[PlanObject]:
    """The ``settings`` objects of a plan that change ``default_code_security_configurations_disabled``."""
    return [obj for obj in plan.objects if obj.kind == "settings" and KEY in obj.changed_keys]


def planned(cli: OtterdogCli, run_ctx: RunContext, what: str) -> tuple[CliResult, PlanResult]:
    """``plan -n -r e2e-<run>-*`` that completed (org settings are always diffed)."""
    result = cli.plan(repo_filter=run_ctx.repo_filter())
    result.assert_ok(what)
    plan = result.plan()
    assert plan.add is not None and not plan.aborted, f"{what}: no plan summary\n{result.output[-TAIL:]}"
    return result, plan


@pytest.mark.scenario("cli.org.code-security-defaults")
@pytest.mark.tags("cli", "org-settings")
def test_default_code_security_configurations_are_disabled(
    org_reset: None,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    mutator: Mutator,
    run_ctx: RunContext,
    otterdog: OtterdogCli,
) -> None:
    """A default configuration makes otterdog plan 'false -> true'; the apply removes every default; enabling (true ->
    false) is never planned."""
    foreign = [name for name in default_names(oracle) if not is_e2e_name(name)]
    if foreign:
        pytest.skip(f"the org has foreign default code security configurations {foreign}: otterdog would unset them")
    name = run_ctx.name("csd")
    try:
        created: dict[str, Any] = mutator.create_code_security_configuration(
            name, description="otterdog e2e: default code security configuration"
        )
    except GitHubError as exc:
        if exc.status in (403, 404):
            pytest.skip(f"code security configurations are not available on this target (HTTP {exc.status})")
        raise
    configuration_id = int(created["id"])
    try:
        mutator.set_code_security_default(configuration_id, name=name, default_for_new_repos="public")
        wait_defaults(oracle, lambda names: name in names, f"{name} is a default configuration")

        otterdog.workspace.write_org_config(baseline.text())
        result, plan = planned(otterdog, run_ctx, "plan (a default configuration exists)")
        objects = settings_objects(plan)
        assert len(objects) == 1, f"no '{KEY}' change planned:\n{result.output[-TAIL:]}"
        assert "false -> true" in normalize_text("\n".join(objects[0].body)), objects[0].body
        problems = baseline.guard_problems(plan, delete=False)
        assert not problems, f"refusing to apply: {problems}"
        applied = otterdog.apply(repo_filter=run_ctx.repo_filter())
        applied.assert_ok("apply (default configurations disabled)")
        assert not applied.apply().failed_patches, applied.output[-TAIL:]
        assert wait_defaults(oracle, lambda names: not names, "no default configuration left") == []
        converged = waiting.poll(
            lambda: planned(otterdog, run_ctx, "converge plan")[1],
            until=lambda again: not settings_objects(again),
            max_attempts=4,
            interval=waiting.CONVERGE_BACKOFF,
            raise_on_timeout=False,
            what=f"plan without a '{KEY}' change",
        )
        assert not settings_objects(converged), f"not converged:\n{converged.raw[-TAIL:]}"

        enable = renderer.render(ConfigFragments(settings=[f"{KEY}: false"]))
        otterdog.workspace.write_org_config(enable)
        result, plan = planned(otterdog, run_ctx, f"plan ({KEY} false while no default exists)")
        assert not settings_objects(plan), f"enabling is planned although it is not supported:\n{result.output}"
    finally:
        mutator.delete_code_security_configuration(configuration_id, name=name)
