"""``otterdog-e2e setup`` and ``otterdog-e2e ci-sync`` (SPEC 16, docs/onboarding.md): the onboarding of a test org
instance.

setup runs the interactive wizard of otterdog_e2e.onboard (org, tokens of every role, web login, the GitHub App through
the manifest flow of app-manifest), then ``bootstrap --apply --wait`` and doctor, each on a fresh copy of the
environment setup started with; ci-sync creates the CI environments of the instance and sets their variables and
secrets with the operator's gh login. Both are refused in CI.
"""

from __future__ import annotations

import contextlib
import functools
import os
import sys
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any

import click

from otterdog_e2e.cli.app_manifest import ManifestFlow
from otterdog_e2e.cli.bootstrap import BOOTSTRAP_WAIT_TIMEOUT, Bootstrap
from otterdog_e2e.cli.common import _echo, _handled, _settings, main
from otterdog_e2e.cli.doctor import Doctor, render_rows
from otterdog_e2e.context import E2EContext, E2EOptions, parse_duration
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.onboard.accounts import AccountResult, AccountsIO, MachineAccount
    from otterdog_e2e.onboard.browser import PlaywrightBrowser
    from otterdog_e2e.settings import Target

# --- setup and ci-sync: onboarding of a test org instance (otterdog_e2e.onboard, docs/onboarding.md) ---------------
ACCOUNT_ROLES = ("admin", "oracle", "author", "approver", "outsider", "config_reader")  # onboard.tokens.ROLES
SETUP_ROTATABLE = (*ACCOUNT_ROLES, "web", "app")


def _instance(target: str) -> str:
    """The one instance of setup / ci-sync (UsageError for an invalid name or a list of targets)."""
    from otterdog_e2e.onboard.envfile import InstanceNameError, check_instance_name

    try:
        return check_instance_name(target)
    except InstanceNameError as exc:
        raise click.UsageError(f"--target: {exc} (setup and ci-sync take one instance)") from None


def _setup_bootstrap(
    instance: str, *, pristine: Mapping[str, str], wait_timeout: float = BOOTSTRAP_WAIT_TIMEOUT
) -> None:
    """``bootstrap --target <instance> --apply --wait`` started by the setup wizard (asks for the typed org login,
    then waits for the invitations to be accepted, the memberships made public and the App installed). Each run gets
    a FRESH copy of ``pristine`` (the environment before setup read any env file): load_env_files never overrides,
    so values a former run loaded (an App replaced by setup meanwhile) would win over the env file otherwise."""
    context = E2EContext.create(E2EOptions(target=instance), environ=dict(pristine))
    context.start_session(argv=[REDACTOR(arg) for arg in sys.argv])
    try:
        Bootstrap(
            context,
            apply=True,
            confirm=lambda prompt: str(click.prompt(prompt)),
            wait=True,
            wait_timeout=wait_timeout,
        ).run()
    finally:
        context.close()


def _setup_doctor(instance: str, *, pristine: Mapping[str, str]) -> None:
    """``doctor --target <instance>`` started by the setup wizard (the table only: failures do not stop setup), on a
    fresh copy of ``pristine`` (see _setup_bootstrap)."""
    context = E2EContext.create(E2EOptions(target=instance), environ=dict(pristine), make_dirs=False)
    _echo(render_rows(Doctor(context).run()))


def _accounts_io() -> AccountsIO:
    """The terminal side of onboard.accounts (hidden password prompt, plain device code prompt)."""
    from otterdog_e2e.onboard.accounts import AccountsIO

    return AccountsIO(
        echo=_echo,
        secret_prompt=lambda text: str(click.prompt(text, default="", hide_input=True, show_default=False)),
        prompt=lambda text: str(click.prompt(text, default="", show_default=False)),
    )


def _open_browser(stack: contextlib.ExitStack) -> PlaywrightBrowser:
    """A visible Firefox for the machine accounts, closed with ``stack``; failed accounts pause before closing."""
    from otterdog_e2e.onboard.browser import PlaywrightBrowser
    from otterdog_e2e.sut.cli_install import playwright_browsers_path

    def pause(message: str) -> None:
        """Wait for the operator before a failed account's window closes."""
        click.prompt(message, default="", show_default=False)

    browser = PlaywrightBrowser(browsers_path=playwright_browsers_path(_settings()), pause=pause)
    return stack.enter_context(browser)


def _setup_accounts(instance: str, days: int, stack: contextlib.ExitStack) -> Callable[..., AccountResult]:
    """``run_account`` of the setup wizard (--browser): AccountSetup.setup in one browser opened at first use."""
    from otterdog_e2e.onboard.accounts import AccountSetup

    opened: list[PlaywrightBrowser] = []

    def run_account(account: MachineAccount, *, org: str, rotate: bool, environ: Mapping[str, str]) -> AccountResult:
        """Set up one machine account."""
        if not opened:
            opened.append(_open_browser(stack))
        accounts = AccountSetup(
            instance, org=org, environ=environ, browser=opened[0], io=_accounts_io(), days=days, rotate=rotate
        )
        return accounts.setup(account)

    return run_account


def _setup_manifest(port: int, open_url: Callable[[str], Any] | None) -> Callable[[Target, str], str]:
    """The App manifest flow of the wizard: the loopback listener of app-manifest on ``port``."""

    def ready(url: str) -> None:
        """Tell where to confirm the App (and open it with --open)."""
        _echo(f"open {url} in a browser logged in as an owner of the test org, then confirm the App")
        if open_url is not None:
            open_url(url)

    def run_flow(target: Target, webhook_url: str) -> str:
        """Serve the auto-posting manifest form and return the code of GitHub's redirect."""
        return ManifestFlow(target, webhook_url=webhook_url, port=port).run(on_ready=ready)

    return run_flow


@main.command("setup")
@click.option("--target", "target", required=True, help="instance name (env file ~/.config/otterdog-e2e/<name>.env)")
@click.option("--profile", default=None, help="targets/<profile>.yaml of the instance (default: the org plan)")
@click.option("--org", default=None, help="login of the dedicated test organization (default: stored or asked)")
@click.option(
    "--token-type",
    type=click.Choice(["classic", "fine-grained"]),
    default=None,
    help="kind of the prefilled token URLs (default: the stored E2E_<ROLE>_TOKEN_TYPE, else classic)",
)
@click.option(
    "--rotate",
    multiple=True,
    type=click.Choice(SETUP_ROTATABLE),
    help="ask again for a role's token (or the web login, or a new App) even when the stored one is valid; repeatable",
)
@click.option("--from", "from_instance", default=None, help="copy the non-secret settings of another instance")
@click.option(
    "--expires-in",
    default=90,
    show_default=True,
    type=click.IntRange(1, 366),
    help="days of validity of the prefilled fine-grained tokens",
)
@click.option(
    "--webhook-url", default=None, help="App webhook sink URL (https, non-loopback; default: stored or asked)"
)
@click.option("--port", default=8765, show_default=True, help="local callback port of the App manifest flow")
@click.option(
    "--wait-timeout",
    default="30m",
    show_default=True,
    help="how long to wait for an invitation to be accepted or the App to be installed (90s, 10m, 1h; re-run setup "
    "afterwards); bootstrap --wait started by setup waits as long",
)
@click.option("--open", "open_browser", is_flag=True, help="open the token, App and installation URLs in a browser")
@click.option(
    "--store",
    default=None,
    help="keep the secrets in a secret store, vault:<prefix> or pass:<prefix> (e.g. vault:otterdog-e2e): the env file "
    "gets references only (docs/security.md, reference layout)",
)
@click.option(
    "--browser",
    is_flag=True,
    help="create the classic tokens (and enroll 2FA) of the machine accounts in a Firefox window, their secrets in "
    "pass (ci-admin layout, E2E_<ROLE>_PASS_DIR), like `otterdog-e2e accounts`",
)
@_handled
def setup_command(
    target: str,
    profile: str | None,
    org: str | None,
    token_type: str | None,
    rotate: tuple[str, ...],
    from_instance: str | None,
    expires_in: int,
    webhook_url: str | None,
    port: int,
    wait_timeout: str,
    open_browser: bool,
    store: str | None,
    browser: bool,
) -> None:
    """Onboard a test org interactively: org, tokens of every role, web login, GitHub App, then bootstrap and doctor.

    Every validated value is written at once to ~/.config/otterdog-e2e/<instance>.env (0600): an interrupted run
    keeps its progress and the next one continues. Refused in CI. What GitHub does not let a program do (accounts,
    org creation, App clicks) is printed as prefilled URLs; token creation too, unless --browser.
    """
    import webbrowser

    from otterdog_e2e.onboard.wizard import SetupError, SetupOptions, SetupWizard, WizardIO

    pristine = dict(os.environ)  # before any env file was read: the wizard, bootstrap and doctor each get a copy
    try:
        timeout = parse_duration(wait_timeout).total_seconds()
    except ValueError as exc:
        raise click.UsageError(f"--wait-timeout: {exc}") from None
    options = SetupOptions(
        instance=_instance(target),
        profile=profile,
        org=org,
        token_type=token_type,
        rotate=rotate,
        from_instance=from_instance,
        expires_in=expires_in,
        webhook_url=webhook_url,
        open_urls=open_browser,
        wait_timeout=timeout,
        store=store,
        browser=browser,
    )
    io = WizardIO(
        prompt=lambda text, default: str(click.prompt(text, default=default)).strip(),
        secret_prompt=lambda text: str(click.prompt(text, default="", hide_input=True, show_default=False)),
        confirm=lambda text, default: bool(click.confirm(text, default=default)),
        echo=_echo,
        open_url=webbrowser.open,
    )
    with contextlib.ExitStack() as stack:
        wizard = SetupWizard(
            options,
            io,
            environ=pristine,
            settings=_settings(),
            run_manifest=_setup_manifest(port, webbrowser.open if open_browser else None),
            bootstrap=functools.partial(_setup_bootstrap, pristine=pristine, wait_timeout=timeout),
            doctor=functools.partial(_setup_doctor, pristine=pristine),
            run_account=_setup_accounts(options.instance, expires_in, stack) if browser else None,
        )
        try:
            wizard.run()
        except SetupError as exc:
            raise click.ClickException(str(exc)) from None


@main.command("accounts")
@click.option("--target", "target", required=True, help="instance name (env file ~/.config/otterdog-e2e/<name>.env)")
@click.option(
    "--role",
    "roles",
    multiple=True,
    type=click.Choice(ACCOUNT_ROLES),
    help="role(s) to set up, repeatable (default: every role with a pass directory)",
)
@click.option(
    "--pass-dir",
    "pass_dirs",
    multiple=True,
    metavar="ROLE=DIR",
    help="pass directory of a role's machine account in the ci-admin layout (e.g. admin=bots/<project>/github.com), "
    "written as E2E_<ROLE>_PASS_DIR; repeatable",
)
@click.option("--rotate", is_flag=True, help="create a new token even when the one in pass is valid")
@click.option(
    "--expires-in",
    default="90",
    show_default=True,
    type=click.Choice(["7", "30", "60", "90"]),
    help="days of validity of the classic tokens",
)
@_handled
def accounts_command(
    target: str, roles: tuple[str, ...], pass_dirs: tuple[str, ...], rotate: bool, expires_in: str
) -> None:
    """Set up machine accounts in a Firefox window: sign in, enroll 2FA when missing, create the classic token.

    Secrets in pass, ci-admin layout (<dir>/username, password, 2FA-seed, 2FA-recovery-codes,
    otterdog-e2e-<instance>-token); PASSWORD_STORE_DIR, else ~/.cbi/config. The env file gets the pass directories
    only: `otterdog-e2e setup` then finds each token in pass and checks it. Refused in CI.
    """
    from otterdog_e2e.context import in_ci
    from otterdog_e2e.onboard.accounts import (
        AccountError,
        AccountSetup,
        MachineAccount,
        check_pass_dir,
        pass_dir_env,
        pass_environ,
    )
    from otterdog_e2e.onboard.envfile import instance_env_path, read_env_file, update_env_file
    from otterdog_e2e.onboard.wizard import ENV_FILE_HEADER

    if in_ci(os.environ):
        raise click.ClickException("accounts drives a visible browser and is refused when CI is set")
    instance = _instance(target)
    path = instance_env_path(instance, os.environ)
    values = read_env_file(path) if path.is_file() else {}
    updates: dict[str, str | None] = {}
    for item in pass_dirs:
        role, sep, directory = item.partition("=")
        if not sep or role.strip() not in ACCOUNT_ROLES:
            raise click.UsageError(f"--pass-dir: expected ROLE=DIR with a role of setup, got {item!r}")
        try:
            updates[pass_dir_env(role.strip())] = check_pass_dir(directory)
        except AccountError as exc:
            raise click.UsageError(f"--pass-dir: {exc}") from None
    environ = {**os.environ, **values, **{key: str(value) for key, value in updates.items()}}
    store_dir = pass_environ(environ).get("PASSWORD_STORE_DIR")
    if store_dir and not environ.get("PASSWORD_STORE_DIR"):
        updates["PASSWORD_STORE_DIR"] = store_dir  # from ~/.cbi/config: runs must resolve the same references
    if updates:
        for name in update_env_file(path, updates, header=ENV_FILE_HEADER.format(instance=instance)):
            _echo(f"saved {name} in {path}")
        values = read_env_file(path)
    selected = roles or tuple(role for role in ACCOUNT_ROLES if values.get(pass_dir_env(role)))
    missing = [role for role in selected if not values.get(pass_dir_env(role))]
    if not selected or missing:
        raise click.UsageError(
            f"no pass directory for {', '.join(missing) or 'any role'}: --pass-dir <role>=bots/<project>/github.com"
        )
    accounts = [MachineAccount(role, values[pass_dir_env(role)]) for role in selected]
    with contextlib.ExitStack() as stack:
        setup = AccountSetup(
            instance,
            org=values.get("E2E_ORG"),
            environ={**os.environ, **values},
            browser=_open_browser(stack),
            io=_accounts_io(),
            days=int(expires_in),
            rotate=rotate,
        )
        try:
            for result in setup.run(accounts):
                state = "created" if result.token_created else "kept"
                enrolled = ", 2FA enrolled" if result.enrolled else ""
                _echo(f"{result.role}: {result.login}: token {state} at {result.token_ref}{enrolled}")
        except AccountError as exc:
            raise click.ClickException(str(exc)) from None
    _echo(f"next: otterdog-e2e setup --target {instance} (finds the tokens in pass and checks them)")


@main.command("ci-sync")
@click.option("--target", "target", required=True, help="instance name (env file ~/.config/otterdog-e2e/<name>.env)")
@click.option("--repo", default=None, help="owner/name of the harness repository (default: the checkout's)")
@click.option(
    "--reviewer",
    "reviewers",
    multiple=True,
    help="required reviewer (login) of e2e-<instance>-untrusted, repeatable (default: your gh login)",
)
@click.option("--allow-self-review", is_flag=True, help="let a reviewer approve the untrusted runs they started")
@click.option("--nightly", is_flag=True, help="also add the instance to E2E_TARGETS (nightly and janitor runs)")
@click.option(
    "--prune-branch-policies",
    is_flag=True,
    help="delete the deployment branch policies other than main of the environments (default: refuse them)",
)
@click.option("--apply", "apply_", is_flag=True, help="perform the changes (default: dry run, names only)")
@_handled
def ci_sync(
    target: str,
    repo: str | None,
    reviewers: tuple[str, ...],
    allow_self_review: bool,
    nightly: bool,
    prune_branch_policies: bool,
    apply_: bool,
) -> None:
    """Create the CI environments of an instance and set their variables and secrets with YOUR gh login.

    e2e-<instance> and e2e-<instance>-untrusted (required reviewers), e2e-<instance>-webui only with web credentials;
    deployment branch main only (other policies refused unless --prune-branch-policies), the protections read back
    before any secret; the names the workflows read, values from the instance env file (secrets on gh's stdin only);
    E2E_INSTANCES gains the instance. Dry run by default; refused in CI.
    """
    from otterdog_e2e.onboard.cisync import CiSync, CiSyncError

    sync = CiSync(
        _instance(target),
        environ=os.environ,
        project_root=_settings().project_root,
        repo=repo,
        reviewers=reviewers,
        allow_self_review=allow_self_review,
        nightly=nightly,
        prune_branch_policies=prune_branch_policies,
        echo=_echo,
    )
    try:
        sync.run(apply=apply_)
    except CiSyncError as exc:
        raise click.ClickException(str(exc)) from None
