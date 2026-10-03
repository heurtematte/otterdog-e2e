"""``import`` over an existing configuration: backup, secrets copied from it, masked webhook URLs, the overwrite prompt.

One module fixture applies a run repository holding a repository secret and two repository webhooks (dummy values,
hook URLs under naming.HOOK_BASE), imports the org (``import -f -n``) into a new workspace, edits the imported file the
way an operator does (the secret gets its literal value back, the webhooks their secrets, one URL is masked with a
trailing ``*``; written as an overlay merged by name over the imported repository) and imports again. The tests then
read both imports (``show --local`` evaluates them offline: import vendored the template) and the outputs
(otterdog/operations/import_configuration.py, operations/__init__.py check_config_file_overwrite_if_exists):

cli.import.no-web-ui-warning: ``import -n`` warns that the Web UI is not queried and writes no web-only setting (they
    keep their template defaults).
cli.import.overwrite: the second import copies the old file to ``<file>.bak``, copies the secrets of the previous
    configuration ('Copying secrets from previous configuration.') and masks the URL ('1 URLs have been masked.');
    ``import -n`` without ``-f`` asks first and 'n' cancels (exit 1, file unchanged).
cli.kb.import-masked-webhook-secret (known bug KB-048): the secret of the masked webhook is lost: secrets are copied
    BEFORE the URLs are masked, and by exact URL, so the previous masked hook never matches the live one.

Cleanup: the run's objects are removed after the module (guarded ``apply -d`` with the trusted reset CLI).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e import waiting
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.workspace import read_untrusted_text
from otterdog_e2e.webui.mapping import WEB_SETTINGS

if TYPE_CHECKING:
    from conftest import ShownObject
    from otterdog_e2e.context import E2EContext
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.template import TemplateRef

pytestmark = [pytest.mark.tags("cli", "repo", "secrets", "webhooks")]

NO_WEB_UI_WARNING = (
    "Warning: the Web UI will not be queried as '--no-web-ui' has been specified, the resulting config will be "
    "incomplete."
)
WRITTEN_RE = re.compile(r"Organization definition written to '(?P<path>[^']+)'\.")
BACKUP_RE = re.compile(r"Existing definition copied to '(?P<path>[^']+)'\.")
COPYING_TEXT = "Copying secrets from previous configuration."
MASKED_TEXT = "Masking webhooks from previous configuration... 1 URLs have been masked."
DUMMY_SECRET = "********"  # what GitHub returns for (and import writes as) every secret value
# web-only org settings: an import with -n leaves them UNSET, i.e. never written (has_discussions is also a
# repository key, so it is left out of the text check)
WEB_ONLY_KEYS = tuple(setting.key for setting in WEB_SETTINGS if setting.key != "has_discussions")
LIVE_TIMEOUT = 90.0


@dataclass
class Reimport:
    """The two imports of the module fixture and what the tests compare."""

    workspace: ConfigWorkspace
    cli: OtterdogCli
    repo: str
    secret: str
    secret_value: str
    plain_url: str
    masked_live_url: str
    masked_url: str
    first: CliResult
    first_text: str
    first_file: str
    first_objects: list[ShownObject]
    edited: str
    second: CliResult
    second_text: str
    second_objects: list[ShownObject]


def find(objects: list[ShownObject], kind: str, value: str, parent: str) -> ShownObject | None:
    """The shown object of ``kind`` with key value ``value`` below repository ``parent``."""
    return next((obj for obj in objects if (obj.kind, obj.value, obj.parent) == (kind, value, parent)), None)


def overlay(repo: str, secret: str, value: str, plain_url: str, masked_url: str) -> str:
    """Jsonnet mixin appended to an imported configuration: the repository's secret and webhooks replaced (merged by
    name: orgs.mergeByKey) with literal values and one masked URL."""
    return (
        " + {\n"
        "  _repositories+:: [\n"
        "    {\n"
        f"      name: '{repo}',\n"
        f"      secrets: [orgs.newRepoSecret('{secret}') {{ value: '{value}' }}],\n"
        "      webhooks: [\n"
        f"        orgs.newRepoWebhook('{plain_url}') {{ events: ['push'], secret: '{value}' }},\n"
        f"        orgs.newRepoWebhook('{masked_url}') {{ events: ['push'], secret: '{value}' }},\n"
        "      ],\n"
        "    },\n"
        "  ],\n"
        "}\n"
    )


def shown_config(cli: OtterdogCli, parse: Callable[[str], list[ShownObject]], what: str) -> list[ShownObject]:
    """Objects of ``show --local`` (the imported file evaluated offline with the vendored template)."""
    from otterdog_e2e.otterdog.output import normalize_text

    result = cli.show(local=True).assert_ok(f"show --local of {what}")
    return parse(normalize_text(result.output))


def wait_live(oracle: Oracle, repo: str, secret: str, urls: tuple[str, ...]) -> None:
    """The secret and every webhook of ``repo`` are visible through REST (an import right after the apply)."""

    def ready() -> bool:
        """True once GitHub lists all of them."""
        return oracle.repo_secret(repo, secret) is not None and all(oracle.repo_hook_by_url(repo, url) for url in urls)

    found = waiting.poll(
        ready, until=bool, timeout=LIVE_TIMEOUT, interval=3.0, what=f"{repo} secrets and hooks", raise_on_timeout=False
    )
    assert found, f"{repo}: the secret or the webhooks never appeared"


@pytest.fixture(scope="module")
def reimport(
    e2e: E2EContext,
    sut: InstalledCli,
    baseline: BaselineManager,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    run_ctx: RunContext,
    template_ref: TemplateRef,
    shown_objects: Callable[[str], list[ShownObject]],
    cli_lines: Callable[[CliResult], str],
) -> Iterator[Reimport]:
    """Apply the run repository, import, edit, import again; the run's objects are removed afterwards."""
    repo, secret = run_ctx.name("import"), run_ctx.const("import")
    value = f"e2e-dummy-{run_ctx.run_id}"
    plain_url = run_ctx.hook_url("import/plain")
    masked_live_url, masked_url = run_ctx.hook_url("import/masked-token"), run_ctx.hook_url("import/masked") + "*"
    snippet = (
        f"orgs.newRepo('{repo}') {{ description: 'otterdog e2e: import over an existing file', "
        f"secrets: [orgs.newRepoSecret('{secret}') {{ value: '{value}' }}], webhooks: ["
        f"orgs.newRepoWebhook('{plain_url}') {{ events: ['push'], secret: '{value}' }}, "
        f"orgs.newRepoWebhook('{masked_live_url}') {{ events: ['push'], secret: '{value}' }}] }}"
    )
    applier = e2e.workspace(e2e.unique_name("import-apply"), template_ref)
    try:
        applier.write_org_config(renderer.render(ConfigFragments(repositories=[snippet])))
        applied = e2e.cli(sut, applier, name=f"ws-{applier.root.name}").apply(repo_filter=run_ctx.repo_filter())
        applied.assert_ok("apply the import repository")
        assert not applied.apply().failed_patches, applied.output[-3000:]
        wait_live(oracle, repo, secret, (plain_url, masked_live_url))
        workspace = e2e.workspace(e2e.unique_name("import-overwrite"), template_ref)
        cli = e2e.cli(sut, workspace, name=f"ws-{workspace.root.name}")
        first = cli.import_config(force=True).assert_ok("import -f -n")
        first_file = workspace.read_org_config()
        first_objects = shown_config(cli, shown_objects, "the first import")
        edited = first_file.rstrip("\n") + overlay(repo, secret, value, plain_url, masked_url)
        workspace.write_org_config(edited)
        second = cli.import_config(force=True).assert_ok("import -f -n over the edited file")
        yield Reimport(
            workspace=workspace,
            cli=cli,
            repo=repo,
            secret=secret,
            secret_value=value,
            plain_url=plain_url,
            masked_live_url=masked_live_url,
            masked_url=masked_url,
            first=first,
            first_text=cli_lines(first),
            first_file=first_file,
            first_objects=first_objects,
            edited=edited,
            second=second,
            second_text=cli_lines(second),
            second_objects=shown_config(cli, shown_objects, "the second import"),
        )
    finally:
        if not e2e.options.keep:
            e2e.remove_run_objects(baseline, baseline.reset_cli)


@pytest.mark.scenario("cli.import.no-web-ui-warning", priority="P2")
@pytest.mark.timeout(1500)
def test_import_without_web_ui_warns_and_skips_web_settings(
    reimport: Reimport, shown: Callable[[str | None], Any]
) -> None:
    """``import -f -n`` warns that the Web UI is not queried, writes the file it names, sets no web-only setting and
    reads every secret value as the dummy GitHub returns."""
    text = reimport.first_text
    assert NO_WEB_UI_WARNING in text, f"no --no-web-ui warning:\n{text[-2000:]}"
    written = WRITTEN_RE.search(text)
    assert written and written.group("path").endswith(reimport.workspace.org_config_file.name), text[-2000:]
    present = [key for key in WEB_ONLY_KEYS if re.search(rf"\b{key}\s*:", reimport.first_file)]
    assert not present, f"import -n wrote the web-only settings {present}"
    secret = find(reimport.first_objects, "repo_secret", reimport.secret, reimport.repo)
    assert secret is not None and shown(secret.fields.get("value")) == DUMMY_SECRET, secret
    for url in (reimport.plain_url, reimport.masked_live_url):
        hook = find(reimport.first_objects, "repo_webhook", url, reimport.repo)
        assert hook is not None and shown(hook.fields.get("secret")) == DUMMY_SECRET, (url, hook)


@pytest.mark.scenario("cli.import.overwrite", priority="P1")
@pytest.mark.timeout(1500)
def test_reimport_backs_up_copies_secrets_and_masks_urls(
    reimport: Reimport, shown: Callable[[str | None], Any]
) -> None:
    """The second import backs the edited file up to ``<file>.bak``, copies the literal secret values of the edited
    file (repository secret, unmasked webhook) and replaces the live URL of the masked webhook by the masked one."""
    text = reimport.second_text
    backup = BACKUP_RE.search(text)
    expected_backup = f"{reimport.workspace.org_config_file.name}.bak"
    assert backup and backup.group("path").endswith(expected_backup), f"no backup message:\n{text[-2000:]}"
    backup_file = reimport.workspace.org_config_file.with_name(expected_backup)
    backup_text = read_untrusted_text(backup_file, within=reimport.workspace.root)
    assert backup_text == reimport.edited, "the backup is not the previous file"
    assert COPYING_TEXT in text and MASKED_TEXT in text, text[-2000:]
    objects = reimport.second_objects
    secret = find(objects, "repo_secret", reimport.secret, reimport.repo)
    assert secret is not None and shown(secret.fields.get("value")) == reimport.secret_value, secret
    plain = find(objects, "repo_webhook", reimport.plain_url, reimport.repo)
    assert plain is not None and shown(plain.fields.get("secret")) == reimport.secret_value, plain
    masked = find(objects, "repo_webhook", reimport.masked_url, reimport.repo)
    assert masked is not None, f"the masked URL {reimport.masked_url} is not in the new import"
    assert find(objects, "repo_webhook", reimport.masked_live_url, reimport.repo) is None, "the live URL is unmasked"


@pytest.mark.scenario("cli.import.overwrite", priority="P1")
@pytest.mark.timeout(1500)
def test_import_without_force_asks_before_overwriting(
    reimport: Reimport, cli_lines: Callable[[CliResult], str]
) -> None:
    """``import -n`` without ``-f`` over an existing file asks first; 'n' cancels: exit 1, nothing written."""
    workspace = reimport.workspace
    before = workspace.read_org_config()
    backup_file = workspace.org_config_file.with_name(f"{workspace.org_config_file.name}.bak")
    backup = read_untrusted_text(backup_file, within=workspace.root)
    result = reimport.cli.run("import", "-n", input="n\n")
    text = cli_lines(result)
    assert "Configuration already exists at '" in text and workspace.org_config_file.name in text, text[-2000:]
    assert "Do you want to continue? (Only 'yes' or 'y' will be accepted to approve)" in text, text[-2000:]
    assert "Operation cancelled." in text, text[-2000:]
    assert result.exit_code == 1, f"exit {result.exit_code}"
    assert workspace.read_org_config() == before, "the cancelled import changed the file"
    assert read_untrusted_text(backup_file, within=workspace.root) == backup, "the cancelled import changed the backup"


@pytest.mark.scenario("cli.kb.import-masked-webhook-secret", priority="P2")
@pytest.mark.known_bug("KB-048")
@pytest.mark.tags("known-bug")
@pytest.mark.timeout(1500)
def test_reimport_keeps_the_secret_of_a_masked_webhook(reimport: Reimport, shown: Callable[[str | None], Any]) -> None:
    """The masked webhook keeps the secret of the previous configuration like every other webhook (KB-048: secrets
    are copied by exact URL before the URLs are masked, so its secret is the dummy GitHub returns)."""
    masked = find(reimport.second_objects, "repo_webhook", reimport.masked_url, reimport.repo)
    assert masked is not None, f"the masked URL {reimport.masked_url} is not in the new import"
    assert shown(masked.fields.get("secret")) == reimport.secret_value, masked.fields
