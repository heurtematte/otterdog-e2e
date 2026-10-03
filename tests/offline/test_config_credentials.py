"""Credential providers, offline (O-CREDENTIALS-ENV, O-CREDENTIALS-PROVIDERS).

otterdog resolves the credentials of an organization before any GitHub call (otterdog/config.py CredentialResolver,
otterdog/credentials/*): the organization's ``credentials.provider``, else ``defaults.credentials.provider``, picks
the provider, configured from ``defaults.<provider>``. validate and local-plan (and every ``-n`` command) need the API
token only; local-apply without ``-n`` resolves all four keys (api_token, username, password, twofa_seed), so a
removal-only local-apply without ``-n`` (nothing applied, otterdog/operations/apply.py:155-163) exercises them offline.
A failure is printed as ``invalid credentials`` followed by the provider's message and the organization exits 1.

* env: an organization-level key names the variable literally (``{``/``}`` refused); otherwise ``defaults.env.<key>``
  is a template whose ``{org_name}`` / ``{github_id}`` placeholders are upper-cased with ' ' and '-' replaced by '_';
* plain: the values themselves; pass: ``pass ls`` must work, then ``pass <path>`` per key, ``password_store_dir`` of
  ``defaults.pass`` exported as PASSWORD_STORE_DIR (also from .otterdog-defaults.json, #725); bitwarden: ``bw unlock
  --check`` must work, then ``bw get item <item_id>`` gives a JSON item whose field ``api_token_admin`` (or the
  configured ``api_token_key``) holds the token and whose login holds username, password and totp; unknown providers
  and a missing provider are refused; unexpected keys of ``defaults.<provider>`` only warn. The vault provider needs a
  Vault server (hvac over HTTP), which the network sandbox of the offline tier cannot reach: not exercised.

The pass and bitwarden tests run stub CLIs (shell scripts of the test workspace, first on PATH) that only answer for
the test's own store directory and items: the user's password store and vault are never read (the harness also
strips PASSWORD_STORE_* and BW_* from the environment). Container runtimes skip them (their PATH is the image's).
Verified on v1.6.1 and main 9bdeb75.
"""

from __future__ import annotations

import os
import stat
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import BaselineSpec, ConfigFragments
from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace, WorkspaceLayout
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
GONE = RUN.name("gone")
DUMMY = "offline-dummy-token"
SUCCEEDED = "Validation succeeded"
INVALID = "Error: invalid credentials"
ORG_VAR = "E2E_OFFLINE"  # OFFLINE_ORG as a placeholder value: upper case, '-' -> '_'
# defaults.env templates of the four keys and the variables they resolve to for the offline organization
ENV_TEMPLATES = {
    "api_token": "E2E_{github_id}_TOKEN",
    "username": "E2E_{github_id}_USER",
    "password": "E2E_{github_id}_PASS",
    "twofa_seed": "E2E_{github_id}_SEED",
}
ENV_VALUES = {
    "E2E_E2E_OFFLINE_TOKEN": DUMMY,
    "E2E_E2E_OFFLINE_USER": "e2e-dummy-user",
    "E2E_E2E_OFFLINE_PASS": "e2e-dummy-password",
    "E2E_E2E_OFFLINE_SEED": "e2e-dummy-seed",
}
KEY_OF_VARIABLE = {"E2E_E2E_OFFLINE_TOKEN": "api_token", "E2E_E2E_OFFLINE_USER": "username"} | {
    "E2E_E2E_OFFLINE_PASS": "password",
    "E2E_E2E_OFFLINE_SEED": "twofa_seed",
}
PASS_TOKEN_PATH = f"e2e/{OFFLINE_ORG}/api_token"
# a stub of the pass CLI: answers `pass ls` and `pass <PASS_TOKEN_PATH>` for the expected store directory only
PASS_STUB = """#!/bin/sh
# otterdog-e2e stub of the pass CLI (never the user's password store)
if [ "$PASSWORD_STORE_DIR" != "{store}" ]; then
  echo "Error: e2e stub: unexpected PASSWORD_STORE_DIR '$PASSWORD_STORE_DIR'" >&2
  exit 1
fi
case "$1" in
  ls) echo "Password Store"; echo "e2e"; exit 0 ;;
  {path}) echo "{token}"; exit 0 ;;
  *) echo "Error: $1 is not in the password store." >&2; exit 1 ;;
esac
"""


def render_org(workspace: ConfigWorkspace, fragments: ConfigFragments, *, project: str | None = None) -> str:
    """The configuration of the offline organization with ``fragments``, rendered as OfflineEngine renders it."""
    renderer = OfflineConfigRenderer(
        template=workspace.template,
        org=workspace.org,
        plan=OFFLINE_DEFAULT_PLAN,
        org_profile=OFFLINE_PROFILE,
        baseline=BaselineSpec(),
        marker=OFFLINE_MARKER,
        hide_cache_limit=False,
        project=project or workspace.project,
    )
    return renderer.render(fragments)


def use_credentials(
    cli: OtterdogCli,
    credentials: Mapping[str, Any] | None,
    *,
    defaults: Mapping[str, Any] | None = None,
    project: str | None = None,
    override: Mapping[str, Any] | None = None,
) -> None:
    """otterdog.json of the offline organization with ``credentials`` as its entry's credentials (None: no key at
    all), ``defaults`` merged into its defaults, ``override`` as .otterdog-defaults.json; plus its configuration."""
    workspace = cli.workspace
    workspace.layout = WorkspaceLayout()  # start from the harness document, not from the previous variant
    document = workspace.otterdog_json()
    entry = document["organizations"][0]
    entry.pop("credentials")
    if credentials is not None:
        entry["credentials"] = dict(credentials)
    if project is not None:
        entry["name"] = project
    document["defaults"].update(defaults or {})
    workspace.use_layout(WorkspaceLayout(document=document, defaults_override=override))
    workspace.write_org_config(render_org(workspace, ConfigFragments(), project=project))


def validate(cli: OtterdogCli, env: Mapping[str, str] | None = None) -> CliResult:
    """``validate -c <config> --local <org>`` with ``env`` added (invoke: the variables of a custom provider setup)."""
    config = str(cli.workspace.config_file.resolve())
    return cli.invoke("validate", "-c", config, "--local", OFFLINE_ORG, env=env or None)


def local_apply_all_keys(cli: OtterdogCli, env: Mapping[str, str] | None = None) -> CliResult:
    """A removal-only ``local-apply -f`` WITHOUT -n (all four credential keys resolved; nothing applied)."""
    workspace = cli.workspace
    workspace.write_base_config(render_org(workspace, ConfigFragments(repositories=[f"orgs.newRepo('{GONE}')"])))
    config = str(workspace.config_file.resolve())
    return cli.invoke("local-apply", "-c", config, "--local", "-f", OFFLINE_ORG, env=env or None)


def tail(result: CliResult, lines: int = 30) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


def succeeded(result: CliResult) -> None:
    """validate exited 0 with 'Validation succeeded' and no credential error."""
    text = normalize_text(result.output)
    assert result.exit_code == 0 and SUCCEEDED in text and INVALID not in text, tail(result)


def refused(result: CliResult, message: str) -> None:
    """The organization's credentials were refused: 'invalid credentials' + message, exit 1."""
    text = normalize_text(result.output)
    assert result.exit_code == 1, f"exit {result.exit_code}, expected 1 for {message!r}\n{tail(result)}"
    assert f"{INVALID}\n{message}" in text, f"{message!r} not printed after 'invalid credentials'\n{tail(result)}"
    assert SUCCEEDED not in text, tail(result)


def host_only(cli: OtterdogCli) -> None:
    """Skip on container runtimes: the stub provider must be on the PATH of the CLI process."""
    if cli.installed.runtime != "host":
        pytest.skip(f"stub provider binaries need a host runtime ({cli.installed.sut.label} runs in docker)")


BW_ITEM = "e2e-item"
BW_ITEM_WITHOUT_TOTP = "e2e-item-without-totp"
# a stub of the bitwarden CLI: an unlocked vault with two items (never the user's vault)
BW_STUB = """#!/bin/sh
# otterdog-e2e stub of the bitwarden CLI (never the user's vault)
if [ "$1 $2" = "unlock --check" ]; then
  if [ -e "{locked}" ]; then echo "Vault is locked." >&2; exit 1; fi
  echo "Vault is unlocked!"; exit 0
fi
if [ "$1 $2" = "get item" ]; then
  case "$3" in
    {item}) echo '{{"id": "{item}", "fields": [{{"name": "api_token_admin", "value": "{token}"}}, {{"name": "e2e_token", "value": "{token}"}}], "login": {{"username": "e2e-bot", "password": "e2e-dummy-password", "totp": "e2e-dummy-seed"}}}}'; exit 0 ;;
    {no_totp}) echo '{{"id": "{no_totp}", "fields": [{{"name": "api_token_admin", "value": "{token}"}}], "login": {{"username": "e2e-bot", "password": "e2e-dummy-password", "totp": null}}}}'; exit 0 ;;
    *) echo "Not found."; exit 1 ;;
  esac
fi
echo "e2e stub: unexpected bw $*" >&2
exit 1
"""


def write_bw_stub(workspace: ConfigWorkspace) -> tuple[Path, Path]:
    """The stub bitwarden CLI in <workspace>/stubs; returns (stub dir, lock file: the vault is locked while it
    exists)."""
    stubs, locked = workspace.root / "stubs", workspace.root / "bw-locked"
    stubs.mkdir(mode=0o700, exist_ok=True)
    script = stubs / "bw"
    script.write_text(
        BW_STUB.format(locked=locked.resolve(), item=BW_ITEM, no_totp=BW_ITEM_WITHOUT_TOTP, token=DUMMY),
        encoding="utf-8",
    )
    script.chmod(stat.S_IRWXU)
    return stubs, locked


def write_pass_stub(workspace: ConfigWorkspace) -> tuple[Path, Path]:
    """The stub pass CLI in <workspace>/stubs and an empty store directory; returns (stub dir, store dir)."""
    stubs, store = workspace.root / "stubs", workspace.root / "pass-store"
    stubs.mkdir(mode=0o700, exist_ok=True)
    store.mkdir(mode=0o700, exist_ok=True)
    script = stubs / "pass"
    script.write_text(PASS_STUB.format(store=store.resolve(), path=PASS_TOKEN_PATH, token=DUMMY), encoding="utf-8")
    script.chmod(stat.S_IRWXU)
    return stubs, store


def stub_path(stubs: Path) -> dict[str, str]:
    """PATH with the stub directory first (the system PATH after it: the sandbox command is looked up there)."""
    return {"PATH": f"{stubs.resolve()}{os.pathsep}{os.environ.get('PATH', '/usr/bin:/bin')}"}


# --- env provider ---------------------------------------------------------------------------------------------------
@pytest.mark.scenario("O-CREDENTIALS-ENV")
def test_env_defaults_templates_resolve_placeholders(vendored_cli: OtterdogCli) -> None:
    """Without organization credentials, defaults.credentials.provider env and defaults.env templates resolve
    {github_id} and {org_name} (upper case, ' ' and '-' -> '_'): the token is read from E2E_E2E_OFFLINE_TOKEN, and
    for the project 'e2e offline-proj' from E2E_E2E_OFFLINE_PROJ_TOKEN; the unset variable is named in the error."""
    defaults = {"credentials": {"provider": "env"}, "env": {"api_token": ENV_TEMPLATES["api_token"]}}
    use_credentials(vendored_cli, None, defaults=defaults)
    succeeded(validate(vendored_cli, {"E2E_E2E_OFFLINE_TOKEN": DUMMY}))
    refused(validate(vendored_cli), "environment variable 'E2E_E2E_OFFLINE_TOKEN' for key 'api_token' not found")

    by_name = {"credentials": {"provider": "env"}, "env": {"api_token": "E2E_{org_name}_TOKEN"}}
    use_credentials(vendored_cli, None, defaults=by_name, project="e2e offline-proj")
    succeeded(validate(vendored_cli, {"E2E_E2E_OFFLINE_PROJ_TOKEN": DUMMY}))


@pytest.mark.scenario("O-CREDENTIALS-ENV")
def test_env_organization_keys_are_literal(vendored_cli: OtterdogCli) -> None:
    """An organization-level variable name wins over the defaults.env template and is used as it is: placeholders
    are refused there, an unset variable is named, and a provider without api_token is refused."""
    defaults = {"env": {"api_token": ENV_TEMPLATES["api_token"]}}
    use_credentials(vendored_cli, {"provider": "env", "api_token": "E2E_CUSTOM_TOKEN"}, defaults=defaults)
    succeeded(validate(vendored_cli, {"E2E_CUSTOM_TOKEN": DUMMY}))
    refused(
        validate(vendored_cli, {"E2E_E2E_OFFLINE_TOKEN": DUMMY}),
        "environment variable 'E2E_CUSTOM_TOKEN' for key 'api_token' not found",
    )
    use_credentials(vendored_cli, {"provider": "env", "api_token": "E2E_{github_id}_TOKEN"})
    refused(
        validate(vendored_cli, {"E2E_E2E_OFFLINE_TOKEN": DUMMY}),
        "placeholders '{' or '}' in org-specific setting for key 'api_token' are not allowed: E2E_{github_id}_TOKEN",
    )
    use_credentials(vendored_cli, {"provider": "env"})
    refused(validate(vendored_cli), "required key 'api_token' not found in credential data")


@pytest.mark.scenario("O-CREDENTIALS-ENV")
def test_env_resolves_the_four_keys_without_no_web_ui(vendored_cli: OtterdogCli) -> None:
    """local-apply without -n resolves api_token, username, password and twofa_seed (each missing variable is named
    with its key, exit 1); with every variable set the removal-only apply ends with 'No changes required.' (exit 0)."""
    use_credentials(vendored_cli, None, defaults={"credentials": {"provider": "env"}, "env": dict(ENV_TEMPLATES)})
    complete = local_apply_all_keys(vendored_cli, ENV_VALUES)
    text = normalize_text(complete.output)
    assert complete.exit_code == 0 and "No changes required." in text, tail(complete)
    assert "1 resource(s) would be deleted with flag '--delete-resources'." in text, tail(complete)
    for variable, key in KEY_OF_VARIABLE.items():
        partial = {name: value for name, value in ENV_VALUES.items() if name != variable}
        refused(
            local_apply_all_keys(vendored_cli, partial),
            f"environment variable '{variable}' for key '{key}' not found",
        )


# --- other providers ------------------------------------------------------------------------------------------------
@pytest.mark.scenario("O-CREDENTIALS-PROVIDERS")
def test_plain_and_default_providers(vendored_cli: OtterdogCli) -> None:
    """plain uses the configured values; defaults.credentials.provider applies to organizations that name none;
    unexpected keys of defaults.<provider> only warn; an unknown provider and no provider at all are refused."""
    use_credentials(vendored_cli, {"provider": "plain", "api_token": DUMMY})
    succeeded(validate(vendored_cli))
    use_credentials(vendored_cli, {"provider": "plain"})
    refused(validate(vendored_cli), "required key 'api_token' not found in credential data")
    use_credentials(vendored_cli, {"api_token": DUMMY}, defaults={"credentials": {"provider": "plain"}})
    succeeded(validate(vendored_cli))
    use_credentials(vendored_cli, {"provider": "plain", "api_token": DUMMY}, defaults={"plain": {"e2e_extra": "x"}})
    warned = validate(vendored_cli)
    succeeded(warned)
    assert "Warning: found unexpected key/value pair 'e2e_extra:x' in defaults for provider 'plain'" in (
        normalize_text(warned.output)
    ), tail(warned)
    use_credentials(vendored_cli, {"provider": "e2e-nope"})
    refused(validate(vendored_cli), "unsupported credential provider 'e2e-nope'")
    use_credentials(vendored_cli, {})
    refused(validate(vendored_cli), f"no credential provider configured for organization '{OFFLINE_ORG}'")
    use_credentials(vendored_cli, None)
    refused(validate(vendored_cli), f"no credential provider configured for organization '{OFFLINE_ORG}'")


@pytest.mark.scenario("O-CREDENTIALS-PROVIDERS")
def test_pass_provider_with_a_stub_store(vendored_cli: OtterdogCli) -> None:
    """pass: defaults.pass.password_store_dir is exported to the pass CLI, ``pass ls`` must work and ``pass <path>``
    gives the token, the path being the organization's api_token or defaults.pass.api_token_pattern with its
    {github_id} placeholder. An organization path the store lacks and an inaccessible store are refused with the CLI's
    own message; a pattern path the store lacks only warns (the pattern lookup of api_token is not strict)."""
    host_only(vendored_cli)
    stubs, store = write_pass_stub(vendored_cli.workspace)
    env = stub_path(stubs)
    store_dir = {"password_store_dir": str(store.resolve())}
    use_credentials(vendored_cli, {"provider": "pass", "api_token": PASS_TOKEN_PATH}, defaults={"pass": store_dir})
    succeeded(validate(vendored_cli, env))
    pattern = {"pass": {**store_dir, "api_token_pattern": "e2e/{github_id}/api_token"}}
    use_credentials(vendored_cli, {"provider": "pass"}, defaults=pattern)
    succeeded(validate(vendored_cli, env))

    use_credentials(vendored_cli, {"provider": "pass", "api_token": "e2e/missing"}, defaults={"pass": store_dir})
    refused(validate(vendored_cli, env), "'e2e/missing' could not be retrieved from your pass vault:")
    lenient = {"pass": {**store_dir, "api_token_pattern": "e2e/{github_id}/missing"}}
    use_credentials(vendored_cli, {"provider": "pass"}, defaults=lenient)
    warned = validate(vendored_cli, env)
    succeeded(warned)
    message = f"WARNING '{'e2e/' + OFFLINE_ORG + '/missing'}' could not be retrieved from your pass vault:"
    assert message in normalize_text(warned.output), tail(warned)
    use_credentials(vendored_cli, {"provider": "pass", "api_token": PASS_TOKEN_PATH})  # no password_store_dir
    refused(validate(vendored_cli, env), "could not access pass vault:")


@pytest.mark.scenario("O-CREDENTIALS-PROVIDERS")
def test_pass_store_dir_from_the_defaults_override(vendored_cli: OtterdogCli) -> None:
    """#725: defaults.pass.password_store_dir given by .otterdog-defaults.json (and only there) reaches the pass
    provider: the stub store answers and the organization validates."""
    host_only(vendored_cli)
    stubs, store = write_pass_stub(vendored_cli.workspace)
    override = {"pass": {"password_store_dir": str(store.resolve())}}
    use_credentials(vendored_cli, {"provider": "pass", "api_token": PASS_TOKEN_PATH}, override=override)
    succeeded(validate(vendored_cli, stub_path(stubs)))


@pytest.mark.scenario("O-CREDENTIALS-PROVIDERS")
def test_bitwarden_provider_with_a_stub_vault(vendored_cli: OtterdogCli) -> None:
    """bitwarden: the item's api_token_admin field (or the organization's api_token_key, or defaults.bitwarden
    api_token_key) gives the token; a missing item, a missing field, a missing item_id and a locked vault are refused
    with the provider's message; local-apply without -n also reads the login and refuses an item without totp."""
    host_only(vendored_cli)
    stubs, locked = write_bw_stub(vendored_cli.workspace)
    env = stub_path(stubs)
    use_credentials(vendored_cli, {"provider": "bitwarden", "item_id": BW_ITEM})
    succeeded(validate(vendored_cli, env))
    use_credentials(vendored_cli, {"provider": "bitwarden", "item_id": BW_ITEM, "api_token_key": "e2e_token"})
    succeeded(validate(vendored_cli, env))
    use_credentials(
        vendored_cli,
        {"provider": "bitwarden", "item_id": BW_ITEM},
        defaults={"bitwarden": {"api_token_key": "e2e_nope"}},
    )
    refused(validate(vendored_cli, env), f"field with key 'e2e_nope' not found in item with id '{BW_ITEM}'")
    use_credentials(vendored_cli, {"provider": "bitwarden", "item_id": "e2e-missing"})
    refused(validate(vendored_cli, env), "item with id 'e2e-missing' not found in your bitwarden vault: Not found.")
    use_credentials(vendored_cli, {"provider": "bitwarden"})
    refused(validate(vendored_cli, env), "required key 'item_id' not found in authorization data")

    use_credentials(vendored_cli, {"provider": "bitwarden", "item_id": BW_ITEM})
    complete = local_apply_all_keys(vendored_cli, env)
    assert complete.exit_code == 0 and "No changes required." in normalize_text(complete.output), tail(complete)
    use_credentials(vendored_cli, {"provider": "bitwarden", "item_id": BW_ITEM_WITHOUT_TOTP})
    refused(local_apply_all_keys(vendored_cli, env), f"totp is empty in item with id '{BW_ITEM_WITHOUT_TOTP}'")

    locked.touch()
    use_credentials(vendored_cli, {"provider": "bitwarden", "item_id": BW_ITEM})
    refused(validate(vendored_cli, env), "could not access bitwarden vault:\nVault is locked.")
