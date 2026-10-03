"""C-IMPORT (SPEC 19, P1): ``import -f -n`` of the live test org round-trips.

The SUT imports the org (after the baseline reset) into a new, empty workspace; the imported configuration must
declare the org and the baseline repositories, validate, and plan no change against the live org it was read from
(objects carrying an e2e run id are ignored: only run-independent objects are compared). Both sides use -n: import
without -n would leave web settings at template defaults (FACTS cli R 13).

Known quirks are marked with their known bug: below Enterprise the API may report members_can_create_private_pages
true, which otterdog's validation accepts on Enterprise only (KB-024). test_import_validates xfails (raises=
PrivatePagesNotAllowedError) only when that error is the only one and the plan is not enterprise; any other validation
error fails (BAT-07). The plan test then leaves that one key unmanaged (``members_can_create_private_pages:: null``,
the baseline's own way) in a copy of the import and still checks the round trip; other validation errors fail it.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import PlanObject
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.safety import VerifiedOrg
    from otterdog_e2e.settings import Target
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli", "repo", "teams", "org-settings")]

MAX_LISTED = 15
PRIVATE_PAGES_ERROR = "enabling 'members_can_create_private_pages' requires an 'enterprise' plan."  # KB-024
PRIVATE_PAGES_RE = re.compile(r"\bmembers_can_create_private_pages\s*:\s*true\b")


class PrivatePagesNotAllowedError(AssertionError):
    """The import validates except for members_can_create_private_pages on a non-enterprise plan (KB-024)."""


def kb024_only(errors: list[str], plan: str) -> bool:
    """True when the only validation error is KB-024's and the org is not on the enterprise plan."""
    return plan != "enterprise" and len(errors) == 1 and PRIVATE_PAGES_ERROR in errors[0]


@pytest.fixture(scope="module")
def imported(
    e2e: E2EContext, sut: InstalledCli, baseline: BaselineManager, template_ref: TemplateRef
) -> tuple[ConfigWorkspace, OtterdogCli]:
    """A new workspace holding ``import -f -n`` of the live org (after the baseline reset) and its CLI."""
    workspace = e2e.workspace(e2e.unique_name("import"), template_ref)
    cli = e2e.cli(sut, workspace, name=f"ws-{workspace.root.name}")
    cli.import_config(force=True).assert_ok("import -f -n")
    return workspace, cli


def run_independent(objects: list[PlanObject]) -> list[PlanObject]:
    """Plan objects that are not read-only and carry no e2e run id (PlanObject.run_id: key value or parent)."""
    return [obj for obj in objects if not obj.is_read_only and obj.run_id is None]


@pytest.mark.scenario("cli.import")
def test_import_writes_config(imported: tuple[ConfigWorkspace, OtterdogCli], target: Target) -> None:
    """The imported jsonnet declares the org and every baseline repository."""
    workspace, _ = imported
    text = workspace.read_org_config()
    assert "orgs.newOrg(" in text, text[:500]
    assert target.org in text, f"the import does not mention the org {target.org}"
    missing = [repo for repo in (target.configs_repo, target.defaults_repo, *target.fixture_repos) if repo not in text]
    assert not missing, f"the import lacks the baseline repositories {missing}"


@pytest.mark.scenario("cli.import.validate")
@pytest.mark.known_bug("KB-024")
@pytest.mark.xfail(
    raises=PrivatePagesNotAllowedError,
    strict=False,
    reason="KB-024: an imported organization below Enterprise fails validation on members_can_create_private_pages",
)
def test_import_validates(imported: tuple[ConfigWorkspace, OtterdogCli], verified_org: VerifiedOrg) -> None:
    """``validate`` accepts the imported configuration (no error); KB-024 alone (not on enterprise) is the only
    tolerated failure, any other error fails the test."""
    _, cli = imported
    result = cli.validate()
    parsed = result.validation()
    if parsed.ok and not parsed.errors:
        return
    message = f"the imported configuration does not validate:\n{result.output[-3000:]}"
    if not parsed.load_error and kb024_only(parsed.errors_text(), verified_org.plan):
        raise PrivatePagesNotAllowedError(message)
    raise AssertionError(message)


@pytest.mark.scenario("cli.import.plan")
def test_import_plans_no_change(
    imported: tuple[ConfigWorkspace, OtterdogCli],
    e2e: E2EContext,
    sut: InstalledCli,
    template_ref: TemplateRef,
    verified_org: VerifiedOrg,
) -> None:
    """``plan -n`` of the imported configuration changes no run-independent object. When KB-024 is the only
    validation error, members_can_create_private_pages is left unmanaged in a copy of the import (``:: null``) and
    the copy is planned; any other validation error fails."""
    workspace, cli = imported
    result = cli.plan()
    plan = result.plan()
    validation = plan.validation
    if validation is not None and (validation.errors or validation.load_error):
        errors = validation.errors_text()
        assert not validation.load_error and kb024_only(errors, verified_org.plan), (
            f"the imported configuration does not validate: {errors}\n{result.output[-3000:]}"
        )
        text, count = PRIVATE_PAGES_RE.subn("members_can_create_private_pages:: null", workspace.read_org_config())
        assert count == 1, f"members_can_create_private_pages: true not found once in the import ({count})"
        copy = e2e.workspace(e2e.unique_name("import-kb024"), template_ref)
        copy.write_org_config(text)
        cli = e2e.cli(sut, copy, name=f"ws-{copy.root.name}")
        result = cli.plan()
        plan = result.plan()
    assert result.exit_code == 0 and not plan.aborted and plan.add is not None, result.output[-3000:]
    changed = run_independent(plan.objects)
    shown = "; ".join(obj.header.strip() for obj in changed[:MAX_LISTED])
    assert not changed, f"{len(changed)} object(s) differ right after the import: {shown}"
