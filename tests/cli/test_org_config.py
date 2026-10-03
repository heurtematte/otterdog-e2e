"""Live checks of otterdog's own configuration (config area of scenarios/coverage.yaml): team exclusion and HTTP cache.

* cli.team.exclude-pattern (config.exclude-teams): ``defaults.github.exclude_teams`` (regexes, joined with '|';
  otterdog/config.py:296-306) hides matching live teams when otterdog loads the org (plan, import:
  otterdog/models/github_organization.py:625-642) and makes declaring one a validation error
  (otterdog/models/team.py:66-75). The pattern comes from ``.otterdog-defaults.json`` of a workspace of the test
  (WorkspaceLayout.defaults_override, merged over otterdog.json's defaults); the excluded team is created out of band
  with the admin Mutator. A plan of the session workspace (no exclusion) is the control: it plans the removal of the
  same team.
* cli.http-cache (config.http-cache): every command runs in a fresh cwd whose ``.cache/async_http`` links to the
  HTTP cache of the SUT and identity shared by the run's commands (in the run's private scratch: it holds the token,
  otterdog_e2e.otterdog.runner); otterdog revalidates cached responses
  (otterdog/providers/github/cache/file.py), so a plan right after an out-of-band change must see it although the
  same request was cached seconds before (GitHub's responses say ``max-age=60``: honouring it would hide the change).
* cli.template.hidden-fields (config.template-feature-gating, the hidden-field part): a field hidden with ``::`` is
  not manifested, so otterdog reads it as UNSET and neither sends nor diffs it (the mechanism a template uses to leave
  a key unmanaged, and the harness to hide max_cache_size_gb, OC-06); a plain ``:`` keeps an inherited hidden field
  hidden, ``:::`` makes it managed again.

The tests create run objects only and remove them afterwards (guarded ``apply -d`` of the baseline with the trusted
reset CLI; the excluded team, never in a configuration, is deleted with the Mutator).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.workspace import WorkspaceLayout

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import PlanResult
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.settings import Target

STATE_TIMEOUT = 90.0  # GitHub reads after a write can lag a few seconds
STATE_INTERVAL = 3.0
TAIL = 3000


def wait_for(fn: Callable[[], object], what: str, *, timeout: float = STATE_TIMEOUT) -> object:
    """Poll a GitHub read until it is truthy (WaitTimeoutError after ``timeout``)."""
    return waiting.wait_until(fn, timeout=timeout, interval=STATE_INTERVAL, what=what)


def team_objects(plan: PlanResult, name: str) -> list[str]:
    """Headers of the team objects of a plan named ``name``."""
    return [obj.header.strip() for obj in plan.objects if obj.kind == "team" and obj.value == name]


@pytest.mark.scenario("cli.team.exclude-pattern")
@pytest.mark.tags("cli", "teams")
def test_excluded_teams_are_neither_loaded_nor_configurable(
    e2e: E2EContext,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    mutator: Mutator,
    run_ctx: RunContext,
    target: Target,
    otterdog: OtterdogCli,
    fresh_workspace: ConfigWorkspace,
    make_cli: Callable[[ConfigWorkspace], OtterdogCli],
) -> None:
    """A live team matching defaults.github.exclude_teams is not planned for removal, not imported, and declaring a
    matching team fails validation with the exclusion message; without the pattern the same plan removes it."""
    excluded = run_ctx.name("excluded-a")
    declared = run_ctx.name("excluded-b")
    pattern = f"^{run_ctx.prefix}-excluded-.*"
    fresh_workspace.use_layout(WorkspaceLayout(defaults_override={"github": {"exclude_teams": [pattern]}}))
    cli = make_cli(fresh_workspace)
    mutator.create_team(excluded, description="otterdog e2e: team hidden by exclude_teams", privacy="closed")
    try:
        wait_for(lambda: oracle.team(excluded), f"team {excluded} created")

        otterdog.workspace.write_org_config(baseline.text())
        control = waiting.poll(  # GitHub's team listing may lag the team's creation by a few seconds
            lambda: otterdog.plan(repo_filter=run_ctx.repo_filter()),
            until=lambda result: bool(team_objects(result.plan(), excluded)),
            timeout=STATE_TIMEOUT,
            interval=10.0,
            raise_on_timeout=False,
            what=f"the control plan removes {excluded}",
        )
        control.assert_ok("plan without exclusion")
        assert team_objects(control.plan(), excluded) == [f'- remove team[name="{excluded}"] {{'], (
            f"the control plan (no exclude_teams) does not remove the unknown team {excluded}:\n{control.output[-TAIL:]}"
        )

        fresh_workspace.write_org_config(baseline.text())
        result = cli.plan(repo_filter=run_ctx.repo_filter())
        result.assert_ok("plan with exclude_teams")
        assert not team_objects(result.plan(), excluded), f"{excluded} is planned although excluded:\n{result.output}"
        assert excluded not in result.output, f"the excluded team shows up in the plan:\n{result.output[-TAIL:]}"

        cli.import_config(force=True).assert_ok("import -f -n with exclude_teams")
        imported = fresh_workspace.read_org_config()
        assert excluded not in imported, f"import wrote the excluded team {excluded}"
        assert target.admin_team in imported, f"import lost the baseline team {target.admin_team}"

        team = (
            f"orgs.newTeam('{declared}') {{ description: 'otterdog e2e: excluded', privacy: 'visible', members: [] }}"
        )
        fresh_workspace.write_org_config(renderer.render(ConfigFragments(teams=[team])))
        validation = cli.validate()
        message = (
            f"Error: team[name=\"{declared}\"] has 'name' of value '{declared}', which is not allowed due to exclusion "
            f"pattern '{pattern}'."
        )
        text = normalize_text(validation.output)
        assert message in text, f"validate does not refuse the excluded team:\n{text[-TAIL:]}"
        parsed = validation.validation()
        assert not parsed.ok and parsed.errors == 1 and validation.exit_code == 1, text[-TAIL:]
    finally:
        mutator.delete_team(excluded)
        if not e2e.options.keep:
            e2e.remove_run_objects(baseline, baseline.reset_cli)


@pytest.mark.scenario("cli.http-cache")
@pytest.mark.tags("cli", "repo")
def test_http_cache_does_not_hide_out_of_band_changes(
    e2e: E2EContext,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    mutator: Mutator,
    run_ctx: RunContext,
    otterdog: OtterdogCli,
) -> None:
    """Warm the run's HTTP cache with a plan of a run repository, change its description out of band, and the next
    plan (same CLI, same cache, well within GitHub's max-age of 60 s) shows the description change."""
    if not otterdog.http_cache:
        pytest.skip("the HTTP cache is disabled (--e2e-no-http-cache): nothing to test")
    repo = run_ctx.name("cache")
    configured = "otterdog e2e: http cache"
    drifted = "otterdog e2e: changed out of band"
    snippet = f"orgs.newRepo('{repo}') {{ description: '{configured}' }}"
    otterdog.workspace.write_org_config(renderer.render(ConfigFragments(repositories=[snippet])))
    scope, needles = run_ctx.repo_filter(), run_ctx.needles()
    try:
        applied = otterdog.apply(repo_filter=scope)
        applied.assert_ok("apply (repository created)")
        assert not applied.apply().failed_patches, applied.output[-TAIL:]
        wait_for(lambda: (oracle.repo(repo) or {}).get("description") == configured, f"{repo} created")
        warm = waiting.poll(
            lambda: otterdog.plan(repo_filter=scope).plan(),
            until=lambda plan: plan.is_noop(needles),
            max_attempts=4,
            interval=waiting.CONVERGE_BACKOFF,
            what="plan converged after the repository was created (warm cache)",
        )
        assert warm.is_noop(needles)
        cache = otterdog.http_cache_dir()
        assert cache.is_dir() and any(cache.iterdir()), f"the HTTP cache {cache} is empty after the plans"

        mutator.patch_repo(repo, description=drifted)
        wait_for(lambda: (oracle.repo(repo) or {}).get("description") == drifted, f"{repo} changed out of band")
        # a few quick plans absorb GitHub's replica lag; a cache serving the cached answer (max-age 60 s) fails them all
        result = waiting.poll(
            lambda: otterdog.plan(repo_filter=scope),
            until=lambda plan: f'~ repository[name="{repo}"]' in normalize_text(plan.output),
            max_attempts=3,
            interval=(5.0, 10.0),
            raise_on_timeout=False,
            what="plan shows the out-of-band description change",
        )
        text = normalize_text(result.output)
        assert f'~ repository[name="{repo}"]' in text, f"the plan does not see the out-of-band change:\n{text[-TAIL:]}"
        assert f'"{drifted}" -> "{configured}"' in text, text[-TAIL:]
    finally:
        if not e2e.options.keep:
            e2e.remove_run_objects(baseline, baseline.reset_cli)


@pytest.mark.scenario("cli.template.hidden-fields")
@pytest.mark.tags("cli", "repo", "template")
def test_hidden_fields_are_unmanaged(
    e2e: E2EContext,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    run_ctx: RunContext,
    otterdog: OtterdogCli,
) -> None:
    """``has_wiki:: false`` is never sent (GitHub keeps its default, true) nor diffed (live true, hidden false: no
    change); ``has_wiki: false`` mixed in after it stays hidden; ``has_wiki::: false`` manages it again."""
    repo = run_ctx.name("hidden")
    scope, needles = run_ctx.repo_filter(), run_ctx.needles()

    def configure(*mixins: str) -> None:
        """The baseline plus the run repository extended by the given object mixins (in order)."""
        objects = " ".join(f"{{ {mixin} }}" for mixin in mixins)
        snippet = f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: hidden fields' }} {objects}"
        otterdog.workspace.write_org_config(renderer.render(ConfigFragments(repositories=[snippet])))

    def has_wiki() -> object:
        """has_wiki of the run repository (None while it does not exist)."""
        return (oracle.repo(repo) or {}).get("has_wiki")

    try:
        configure("has_wiki:: false")
        created = otterdog.plan(repo_filter=scope)
        created.assert_ok("plan (repository with a hidden field)")
        text = normalize_text(created.output)
        assert f'+ add repository[name="{repo}"]' in text, text[-TAIL:]
        assert "has_wiki" not in text, f"the hidden field is planned:\n{text[-TAIL:]}"
        applied = otterdog.apply(repo_filter=scope)
        applied.assert_ok("apply (repository with a hidden field)")
        assert not applied.apply().failed_patches, applied.output[-TAIL:]
        wait_for(lambda: has_wiki() is not None, f"{repo} created")
        assert has_wiki() is True, "the hidden has_wiki false was sent to GitHub"

        for mixins in (("has_wiki:: false",), ("has_wiki:: false", "has_wiki: false")):
            configure(*mixins)
            result = waiting.poll(  # the converge backoff of the scenario engine: a new repository settles first
                lambda: otterdog.plan(repo_filter=scope),
                until=lambda plan: plan.plan().is_noop(needles),
                max_attempts=4,
                interval=waiting.CONVERGE_BACKOFF,
                raise_on_timeout=False,
                what=f"plan {mixins} is a no-op",
            )
            result.assert_ok(f"plan {mixins}")
            assert result.plan().is_noop(needles), f"{mixins} is managed:\n{result.output[-TAIL:]}"

        configure("has_wiki:: false", "has_wiki::: false")
        result = otterdog.plan(repo_filter=scope)
        result.assert_ok("plan (has_wiki made visible with :::)")
        text = normalize_text(result.output)
        assert f'~ repository[name="{repo}"]' in text and "has_wiki" in text, text[-TAIL:]
        assert "true -> false" in text, text[-TAIL:]
        applied = otterdog.apply(repo_filter=scope)
        applied.assert_ok("apply (has_wiki managed again)")
        assert not applied.apply().failed_patches, applied.output[-TAIL:]
        wait_for(lambda: has_wiki() is False, f"{repo} wiki disabled by otterdog")
    finally:
        if not e2e.options.keep:
            e2e.remove_run_objects(baseline, baseline.reset_cli)
