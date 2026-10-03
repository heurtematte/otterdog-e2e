"""local-plan suffixes, a missing other side (O-LPLAN-SUFFIX) and forced updates of dummy secrets
(O-LPLAN-SECRET-REFS, O-KB-LPLAN-DUMMY-SECRETS), offline.

``local-plan -s SUFFIX`` (default ``-BASE``) diffs ``<org>.jsonnet`` against ``<org>.jsonnet<SUFFIX>`` in the same
directory (otterdog/operations/local_plan.py:68-80): the other side is "current", so its values appear on the left of
``->``. A missing other side is reported after the validation of the head configuration, as ``failed to load current
configuration`` / ``configuration file '<file>' does not exist`` (exit 1, no Plan: line). Verified offline on v1.6.1
and main 9bdeb75 (identical local_plan.py and diff_operation.py).

Dummy secrets (``********``) are skipped by every apply (Secret.include_for_live_patch): ``local-apply
--update-secrets`` plans nothing for them. local-plan first rewrites them to ``<DUMMY>`` on both sides
(LocalPlanOperation.preprocess_orgs), after which they no longer look like dummies, so ``local-plan --update-secrets``
plans their forced update (KB-056, test_local_plan_forces_no_dummy_secret).
"""

from __future__ import annotations

import pytest

from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, DiffOptions, OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_ORG,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "cli")]

RUN = offline_run_context()
REPO = RUN.name("suffix")
CURRENT_ERROR = "Error: failed to load current configuration"
DUMMY_SECRETS = ConfigFragments(
    secrets=[f"orgs.newOrgSecret('{RUN.const('ORG_DUMMY')}') {{ value: '********' }}"],
    repositories=[
        f"orgs.newRepo('{REPO}') {{ secrets: [orgs.newRepoSecret('{RUN.const('REPO_DUMMY')}') {{ value: '********' }}] }}"
    ],
)


def render_org(workspace: ConfigWorkspace, fragments: ConfigFragments) -> str:
    """The configuration of the offline organization with ``fragments``, rendered as OfflineEngine renders it."""
    renderer = OfflineConfigRenderer(
        template=workspace.template,
        org=workspace.org,
        plan=OFFLINE_DEFAULT_PLAN,
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
        project=workspace.project,
    )
    return renderer.render(fragments)


def repository(description: str) -> ConfigFragments:
    """The run repository REPO with a description."""
    return ConfigFragments(repositories=[f"orgs.newRepo('{REPO}') {{ description: '{description}' }}"])


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


def missing_side(result: CliResult, suffix: str) -> None:
    """The plan failed because ``<org>.jsonnet<suffix>`` does not exist: exit 1, the two-line error, no Plan: line."""
    text = normalize_text(result.output)
    assert result.exit_code == 1, f"exit {result.exit_code}\n{tail(result)}"
    assert CURRENT_ERROR in text, tail(result)
    assert f"{OFFLINE_ORG}.jsonnet{suffix}' does not exist" in text, tail(result)
    plan = result.plan()
    assert plan.aborted and plan.add is None, tail(result)
    assert plan.validation is not None and plan.validation.ok, "validation runs (and passes) before the other side"


@pytest.mark.scenario("O-LPLAN-SUFFIX")
def test_local_plan_compares_with_another_suffix(vendored_cli: OtterdogCli) -> None:
    """``local-plan -s -OTHER`` diffs the configuration against ``<org>.jsonnet-OTHER``: the description changes
    from the -OTHER value to the head value (one changed key), while the -BASE file (different again) is ignored."""
    workspace = vendored_cli.workspace
    workspace.write_org_config(render_org(workspace, repository("head")))
    workspace.write_base_config(render_org(workspace, repository("other")), suffix="-OTHER")
    workspace.write_base_config(render_org(workspace, ConfigFragments()))  # -BASE: no repository at all
    result = vendored_cli.local_plan(suffix="-OTHER")
    plan = result.plan()
    text = normalize_text(result.output)
    assert result.exit_code == 0, f"exit {result.exit_code}\n{tail(result)}"
    assert (plan.add, plan.change, plan.delete) == (0, 1, 0), tail(result)
    changed = [obj for obj in plan.objects if obj.op == "change"]
    assert [(obj.kind, obj.value) for obj in changed] == [("repository", REPO)], tail(result)
    assert changed[0].changed_keys == ["description"], changed[0].body
    assert '~ description = "other" -> "head"' in text, tail(result)
    default = vendored_cli.local_plan()  # -BASE has no repository: the same head adds it
    assert default.exit_code == 0 and (default.plan().add, default.plan().change) == (1, 0), tail(default)
    assert f'+ add repository[name="{REPO}"]' in normalize_text(default.output), tail(default)


@pytest.mark.scenario("O-LPLAN-SUFFIX")
def test_missing_other_side_fails_the_plan(vendored_cli: OtterdogCli) -> None:
    """A suffix without its file (-NONE), and the default -BASE when it was never written, fail with 'failed to load
    current configuration' and "configuration file '<org>.jsonnet<suffix>' does not exist" (exit 1)."""
    workspace = vendored_cli.workspace
    workspace.write_org_config(render_org(workspace, repository("head")))
    missing_side(vendored_cli.local_plan(suffix="-NONE"), "-NONE")
    assert not workspace.base_config_file.exists()
    missing_side(vendored_cli.local_plan(), "-BASE")


def dummy_secrets_on_both_sides(cli: OtterdogCli) -> None:
    """The same organization and repository secrets with dummy values in the configuration and in -BASE."""
    workspace = cli.workspace
    workspace.write_org_config(render_org(workspace, DUMMY_SECRETS))
    workspace.write_base_config(render_org(workspace, DUMMY_SECRETS))


@pytest.mark.scenario("O-LPLAN-SECRET-REFS")
def test_local_apply_forces_no_dummy_secret(vendored_cli: OtterdogCli) -> None:
    """local-apply --update-secrets skips secrets that only have a dummy value: nothing to do ('No changes required.',
    no prompt, exit 0); the two dummies are reported as Info only."""
    dummy_secrets_on_both_sides(vendored_cli)
    result = vendored_cli.run("local-apply", "-n", "--update-secrets", local=True, input="n\n")
    text = normalize_text(result.output)
    assert result.exit_code == 0 and "No changes required." in text, tail(result)
    assert "there have been 2 validation infos" in text, tail(result)
    assert "_secret[name=" not in text and "Do you want to perform these actions?" not in text, tail(result)


@pytest.mark.scenario("O-KB-LPLAN-DUMMY-SECRETS")
@pytest.mark.known_bug("KB-056")
def test_local_plan_forces_no_dummy_secret(vendored_cli: OtterdogCli) -> None:
    """local-plan previews local-apply: with --update-secrets it must not plan a forced update of a dummy secret
    (Plan: 0 to add, 0 to change, 0 to delete), like local-apply --update-secrets."""
    dummy_secrets_on_both_sides(vendored_cli)
    result = vendored_cli.local_plan_with(DiffOptions(update_secrets=True))
    plan = result.plan()
    assert result.exit_code == 0 and not plan.aborted, tail(result)
    forced = [obj.header for obj in plan.objects if obj.op == "forced"]
    assert not forced and (plan.add, plan.change, plan.delete) == (0, 0, 0), f"forced: {forced}\n{tail(result)}"
