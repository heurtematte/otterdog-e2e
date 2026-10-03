"""Template hook scripts, offline: validate-org-settings.py (O-TEMPLATE-HOOK-VALIDATE) and pre-add-object-hook.py
(O-TEMPLATE-HOOK-PRE-ADD).

otterdog executes Python files of the template's root directory (its ``template_dir``, ``<org dir>/vendor/<repo>/``):
``validate-org-settings.py`` while the organization settings are validated (otterdog/models/organization_settings.py
:104-106, ``exec`` with ``self`` = the settings and ``context`` = the ValidationContext, whose ``property_equals``
reports "<header> has '<key>' set to '<value>' but '<required>' is required." as an error), and
``pre-add-object-hook.py`` for every object an apply adds, while the plan is printed (otterdog/operations/apply.py
:61-68, ``self`` = the apply operation, ``model_object`` = the added object). Eclipse's otterdog-defaults relies on the
validation hook; validation runs it for validate, plan, local-plan and the webapp alike. The hooks are vendored next to
the template by sut.template.vendor_template(hooks=...). Verified offline on v1.6.1 and main 9bdeb75.

Safety: local-apply is answered 'n' (nothing is applied; the offline sandbox and the dummy token would refuse anyway).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.scenarios.offline import (
    OFFLINE_DEFAULT_PLAN,
    OFFLINE_MARKER,
    OFFLINE_PROFILE,
    OfflineConfigRenderer,
    offline_run_context,
)
from otterdog_e2e.sut.template import vendor_template

pytestmark = [pytest.mark.offline, pytest.mark.tags("offline", "template")]

RUN = offline_run_context()
REPO = RUN.name("hooked")
VARIABLE = RUN.const("hooked")
VALIDATE_HOOK = "context.property_equals(self, 'default_repository_permission', 'none')\n"
PRE_ADD_HOOK = (
    "self.printer.print_warn(f'e2e pre-add {model_object.model_object_name} {model_object.get_key_value()}')\n"
)
REQUIRED_NONE = "settings has 'default_repository_permission' set to 'read' but 'none' is required."
PROMPT = "Do you want to perform these actions? (Only 'yes' or 'y' will be accepted to approve)"


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


def text_of(result: CliResult) -> str:
    """The normalized output (boxes unwrapped)."""
    return normalize_text(result.output)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(text_of(result).splitlines()[-lines:])


def vendor_with_hooks(cli: OtterdogCli, template_src: Path, hooks: dict[str, str]) -> ConfigWorkspace:
    """Vendor the SUT template with ``hooks`` into the workspace of ``cli``."""
    workspace = cli.workspace
    vendor_template(template_src, workspace.org_dir, workspace.template, hooks=hooks)
    return workspace


@pytest.mark.scenario("O-TEMPLATE-HOOK-VALIDATE")
def test_validate_org_settings_hook(offline_cli: OtterdogCli, template_src: Path) -> None:
    """A validate-org-settings.py requiring default_repository_permission 'none' turns the template default 'read'
    into a validation error (validate exits 1, local-plan aborts); the required value validates."""
    workspace = vendor_with_hooks(offline_cli, template_src, {"validate-org-settings.py": VALIDATE_HOOK})
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    refused = offline_cli.validate(local=True)
    validation = refused.validation()
    assert refused.exit_code == 1 and validation.errors == 1, tail(refused)
    assert f"Error: {REQUIRED_NONE}" in text_of(refused), tail(refused)
    workspace.write_base_config(render_org(workspace, ConfigFragments()))
    aborted = offline_cli.local_plan()
    assert aborted.exit_code == 1, tail(aborted)
    assert REQUIRED_NONE in text_of(aborted) and "Planning aborted due to validation errors." in text_of(aborted)
    assert "Plan:" not in text_of(aborted), tail(aborted)

    workspace.write_org_config(
        render_org(workspace, ConfigFragments(settings=["default_repository_permission: 'none'"]))
    )
    accepted = offline_cli.validate(local=True)
    assert accepted.exit_code == 0 and accepted.validation().ok, tail(accepted)
    assert REQUIRED_NONE not in text_of(accepted), tail(accepted)


@pytest.mark.scenario("O-TEMPLATE-HOOK-VALIDATE")
def test_without_the_hook_the_template_default_validates(vendored_cli: OtterdogCli) -> None:
    """Control: the same configuration validates when the template has no hook file."""
    workspace = vendored_cli.workspace
    workspace.write_org_config(render_org(workspace, ConfigFragments()))
    result = vendored_cli.validate(local=True)
    assert result.exit_code == 0 and result.validation().ok, tail(result)
    assert "is required." not in text_of(result), tail(result)


@pytest.mark.scenario("O-TEMPLATE-HOOK-PRE-ADD")
def test_pre_add_object_hook_runs_for_every_addition(offline_cli: OtterdogCli, template_src: Path) -> None:
    """pre-add-object-hook.py runs once per added object while local-apply prints its plan, before the prompt (answered
    'n'); local-plan never runs it and changes do not trigger it."""
    workspace = vendor_with_hooks(offline_cli, template_src, {"pre-add-object-hook.py": PRE_ADD_HOOK})
    base = ConfigFragments(repositories=[f"orgs.newRepo('{RUN.name('kept')}') {{ description: 'a' }}"])
    head = ConfigFragments(
        variables=[f"orgs.newOrgVariable('{VARIABLE}') {{ value: 'v' }}"],
        repositories=[
            f"orgs.newRepo('{RUN.name('kept')}') {{ description: 'b' }}",
            f"orgs.newRepo('{REPO}') {{ description: 'x' }}",
        ],
    )
    workspace.write_base_config(render_org(workspace, base))
    workspace.write_org_config(render_org(workspace, head))

    plan = offline_cli.local_plan()
    parsed = plan.plan()
    assert plan.exit_code == 0 and (parsed.add, parsed.change, parsed.delete) == (2, 1, 0), tail(plan)
    assert "e2e pre-add" not in text_of(plan), tail(plan)

    result = offline_cli.run("local-apply", "-n", local=True, input="n\n")
    text = text_of(result)
    assert result.exit_code == 0 and "Apply cancelled." in text, tail(result)
    hooked = [line.strip() for line in text.splitlines() if "e2e pre-add" in line]
    assert hooked == [
        f"Warning: e2e pre-add org_variable {VARIABLE}",
        f"Warning: e2e pre-add repository {REPO}",
    ], tail(result)
    assert text.index(f"e2e pre-add repository {REPO}") < text.index(PROMPT), tail(result)
    assert f"e2e pre-add repository {RUN.name('kept')}" not in text, tail(result)
