"""C-IMPORT (SPEC 19, P1): ``import -f -n`` of the live test org round-trips.

The SUT imports the org (after the baseline reset) into a new, empty workspace; the imported configuration must
declare the org and the baseline repositories, validate, and plan no change against the live org it was read from
(objects carrying an e2e run id are ignored: only run-independent objects are compared). Both sides use -n: import
without -n would leave web settings at template defaults (FACTS cli R 13).

Known quirks are marked with their known bug: below Enterprise the API may report members_can_create_private_pages
true, which otterdog's validation accepts on Enterprise only (KB-024, fixed in 1.8.0 by #925: the value reported for
another plan is no longer read, so it is neither imported nor compared). On SUTs older than 1.8.0 test_import_validates
xfails (raises=PrivatePagesNotAllowedError) only when that error is the only one and the plan is not enterprise; any
other validation error fails (BAT-07), and from 1.8.0 it runs strict. The plan test then leaves that one key unmanaged
(``members_can_create_private_pages:: null``, the baseline's own way) in a copy of the import and still checks the
round trip; other validation errors fail it.

The import writes its configuration through rich markup (KB-050), so the safety marker every test organization
carries in its description ('[otterdog-e2e]') is dropped from the imported description, and the plan right after the
import changes it back (seen live on 1.8.0). test_import_plans_no_change accepts exactly that difference as KB-050
(raises=BracketedWordsLostError, after checking that nothing else differs): any other difference fails.

cli.import.workflow-keys (eclipse-csi/otterdog#919, 1.8.0): without an expected configuration, import reads only the
workflow settings the default configuration of the base template defines (a key absent or null is never requested),
like plan and apply. The standard template sets max_cache_size_gb at both levels, so the cache size of the
organization and of every repository is read; a local copy of that template (#917, 1.8.0) with max_cache_size_gb null
at both levels sends none of these requests and writes no max_cache_size_gb, the other workflow settings are still
read (otterdog's request statistics, CliResult.api_usage).
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING

import pytest

from otterdog_acceptance.otterdog.workspace import WorkspaceLayout, read_untrusted_text, write_private_text
from otterdog_acceptance.sut.template import PUBLISHED_TEMPLATE_FILE, copy_template, template_source_dir
from otterdog_acceptance.sut.version import predates

if TYPE_CHECKING:
    from otterdog_acceptance.context import E2EContext
    from otterdog_acceptance.otterdog.api_usage import ApiUsage
    from otterdog_acceptance.otterdog.baseline import BaselineManager
    from otterdog_acceptance.otterdog.output import PlanObject
    from otterdog_acceptance.otterdog.runner import OtterdogCli
    from otterdog_acceptance.otterdog.workspace import ConfigWorkspace
    from otterdog_acceptance.safety import VerifiedOrg
    from otterdog_acceptance.settings import Target
    from otterdog_acceptance.sut.cli_install import InstalledCli
    from otterdog_acceptance.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli", "repo", "teams", "org-settings")]

MAX_LISTED = 15
PRIVATE_PAGES_ERROR = "enabling 'members_can_create_private_pages' requires an 'enterprise' plan."  # KB-024
PRIVATE_PAGES_RE = re.compile(r"\bmembers_can_create_private_pages\s*:\s*true\b")
# KB-050: a rich markup tag (rich.markup.RE_TAGS without its escapes) and a settings description change of the plan
MARKUP_TAG_RE = re.compile(r"\[[a-zA-Z#/@][^\[]*?\]")
JSON_STRING = r'"(?:[^"\\]|\\.)*"'
DESCRIPTION_CHANGE_RE = re.compile(
    rf"^\s*~ description\s*=\s*(?P<live>{JSON_STRING})\s*->\s*(?P<imported>{JSON_STRING})\s*$"
)


PRIVATE_PAGES_REFERENCES = [
    {
        "pr": 925,
        "note": (
            "fix: ignore the private pages setting reported for non-enterprise plans (c0d9203, in v1.8.0):"
            " OrganizationSettings.get_mapping_from_provider leaves members_can_create_private_pages unset when the"
            " organization's plan is not enterprise, so import no longer writes the 'true' GitHub reports for a Free or"
            " Team organization (KB-024 fixed: the import validates) and plan no longer compares it; an enterprise"
            " organization, or an unknown plan, keeps the value. Live only (provider data): no offline delta."
        ),
    }
]
# eclipse-csi/otterdog#919 "fix: only retrieve workflow settings defined by the default config on import" (squash
# 7c5477c after v1.7.1, 1.8.0); the local base template of the test needs #917 (1.8.0) too
WORKFLOW_KEYS_SINCE = "1.8.0"
WORKFLOW_KEYS_REFERENCES = [
    {
        "pr": 919,
        "note": (
            "'fix: only retrieve workflow settings defined by the default config on import': without an expected "
            "configuration, import requested every workflow setting (the cache size of the organization and of each "
            "repository whatever the template); it now requests the keys the default configuration defines (not "
            "absent nor null), as plan and apply already did. With the standard template, which defines every key, "
            "nothing changes"
        ),
    }
]
IMPORT_PLAN_REFERENCES = [
    {
        "pr": 925,
        "note": (
            "fix: ignore the private pages setting reported for non-enterprise plans (c0d9203, in v1.8.0):"
            " OrganizationSettings.get_mapping_from_provider leaves members_can_create_private_pages unset when the"
            " organization's plan is not enterprise, so import no longer writes the 'true' GitHub reports for a Free or"
            " Team organization (KB-024 fixed: the import validates) and plan no longer compares it; an enterprise"
            " organization, or an unknown plan, keeps the value. Live only (provider data): no offline delta."
        ),
    },
    {
        "pr": 919,
        "note": (
            "the standard template defines every workflow key, so import still reads them all and the import must "
            "still plan no change"
        ),
    },
]
LOCAL_TEMPLATE_DIR = "local-templates/template"
CACHE_SIZE_RE = re.compile(r"^(?P<indent>[ \t]*)max_cache_size_gb:[^,\n]*,", re.MULTILINE)
ORG_CACHE_SIZE = "GET /orgs/{org}/actions/cache/storage-limit"
REPO_CACHE_SIZE = "GET /repos/{owner}/{repo}/actions/cache/storage-limit"
REPO_ACTIONS = "GET /repos/{owner}/{repo}/actions/permissions"


class PrivatePagesNotAllowedError(AssertionError):
    """The import validates except for members_can_create_private_pages on a non-enterprise plan (KB-024)."""


class BracketedWordsLostError(AssertionError):
    """The import differs from the live org only by the bracketed words its description lost (KB-050)."""


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


def lost_bracketed_words(obj: PlanObject) -> bool:
    """True for a '~ settings' change of the description alone where the imported value is the live one without its
    rich markup tags (KB-050: '[otterdog-e2e]' -> '')."""
    lines = [line for line in obj.body if line.strip()]
    if obj.kind != "settings" or obj.op != "change" or len(lines) != 1:
        return False
    match = DESCRIPTION_CHANGE_RE.match(lines[0])
    if match is None:
        return False
    live, imported = json.loads(match["live"]), json.loads(match["imported"])
    return live != imported and MARKUP_TAG_RE.sub("", live) == imported


@pytest.mark.scenario("cli.import")
def test_import_writes_config(imported: tuple[ConfigWorkspace, OtterdogCli], target: Target) -> None:
    """The imported jsonnet declares the org and every baseline repository."""
    workspace, _ = imported
    text = workspace.read_org_config()
    assert "orgs.newOrg(" in text, text[:500]
    assert target.org in text, f"the import does not mention the org {target.org}"
    missing = [repo for repo in (target.configs_repo, target.defaults_repo, *target.fixture_repos) if repo not in text]
    assert not missing, f"the import lacks the baseline repositories {missing}"


@pytest.mark.scenario("cli.import.validate", references=PRIVATE_PAGES_REFERENCES)
@pytest.mark.known_bug("KB-024", raises=PrivatePagesNotAllowedError)
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


@pytest.mark.scenario("cli.import.plan", references=IMPORT_PLAN_REFERENCES)
@pytest.mark.known_bug("KB-050", raises=BracketedWordsLostError)
def test_import_plans_no_change(
    imported: tuple[ConfigWorkspace, OtterdogCli],
    e2e: E2EContext,
    sut: InstalledCli,
    template_ref: TemplateRef,
    verified_org: VerifiedOrg,
) -> None:
    """``plan -n`` of the imported configuration changes no run-independent object. When KB-024 is the only
    validation error, members_can_create_private_pages is left unmanaged in a copy of the import (``:: null``) and
    the copy is planned; any other validation error fails. The description the import wrote without its bracketed
    words (KB-050) is the only difference tolerated, reported last as BracketedWordsLostError."""
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
    lost = [obj for obj in changed if lost_bracketed_words(obj)]
    changed = [obj for obj in changed if obj not in lost]
    shown = "; ".join(obj.header.strip() for obj in changed[:MAX_LISTED])
    assert not changed, f"{len(changed)} object(s) differ right after the import: {shown}"
    if lost:
        raise BracketedWordsLostError(
            f"KB-050: the import wrote the description without its bracketed words: {lost[0].body[0].strip()}"
        )


def imported_usage(cli: OtterdogCli) -> ApiUsage:
    """The requests of ``import -f -n`` (otterdog's request statistics), which must succeed."""
    result = cli.import_config(force=True).assert_ok("import -f -n")
    assert result.api_usage is not None, "import wrote no request statistics (OTTERDOG_STATS_FILE)"
    return result.api_usage


def cache_size_requests(usage: ApiUsage) -> str:
    """The cache size and repository Actions requests of an import (assertion messages)."""
    counts = {endpoint: usage.count(endpoint) for endpoint in (ORG_CACHE_SIZE, REPO_CACHE_SIZE, REPO_ACTIONS)}
    return ", ".join(f"{endpoint} x{count}" for endpoint, count in counts.items())


@pytest.mark.scenario("cli.import.workflow-keys", priority="P2", references=WORKFLOW_KEYS_REFERENCES)
def test_import_reads_only_the_workflow_settings_of_the_template(
    e2e: E2EContext, sut: InstalledCli, template_ref: TemplateRef
) -> None:
    """``import -f -n`` with the standard template reads the cache size of the organization and of the repositories
    (the template sets max_cache_size_gb at both levels); with a local copy of that template whose max_cache_size_gb
    is null at both levels, it sends none of these requests and writes no max_cache_size_gb, while the other
    repository Actions settings are still read."""
    if predates(sut.sut.version, WORKFLOW_KEYS_SINCE):
        pytest.skip(f"SUT {sut.sut.version} predates otterdog {WORKFLOW_KEYS_SINCE} (#917 local base template, #919)")
    standard = e2e.workspace(e2e.unique_name("import-workflow-keys"), template_ref)
    usage = imported_usage(e2e.cli(sut, standard, name=f"ws-{standard.root.name}"))
    assert usage.count(ORG_CACHE_SIZE) >= 1 and usage.count(REPO_CACHE_SIZE) >= 1, (
        f"the standard template sets max_cache_size_gb: import must read the cache sizes ({cache_size_requests(usage)})"
    )

    workspace = e2e.workspace(e2e.unique_name("import-workflow-keys-null"), template_ref)
    template_dir = workspace.root / LOCAL_TEMPLATE_DIR
    copy_template(template_source_dir(sut.sut.source_dir), template_dir, root=workspace.root)
    template_file = template_dir / PUBLISHED_TEMPLATE_FILE
    text = read_untrusted_text(template_file, within=workspace.root)
    assert text is not None, f"{PUBLISHED_TEMPLATE_FILE} was not copied"
    text, count = CACHE_SIZE_RE.subn(r"\g<indent>max_cache_size_gb: null,", text)
    assert count == 2, f"the template sets max_cache_size_gb {count} time(s), expected the org and repository defaults"
    write_private_text(template_file, text, within=workspace.root)
    workspace.use_layout(
        WorkspaceLayout(
            vendor=False,
            local_template=LOCAL_TEMPLATE_DIR,
            defaults_override={"jsonnet": {"base_template": f"{LOCAL_TEMPLATE_DIR}/{PUBLISHED_TEMPLATE_FILE}"}},
        )
    )
    usage = imported_usage(e2e.cli(sut, workspace, name=f"ws-{workspace.root.name}"))
    assert usage.count(ORG_CACHE_SIZE) == 0 and usage.count(REPO_CACHE_SIZE) == 0, (
        f"max_cache_size_gb is null in the template: import must not read cache sizes ({cache_size_requests(usage)})"
    )
    assert usage.count(REPO_ACTIONS) >= 1, f"the other workflow settings are still read ({cache_size_requests(usage)})"
    assert "max_cache_size_gb" not in workspace.read_org_config(), "import wrote max_cache_size_gb"
