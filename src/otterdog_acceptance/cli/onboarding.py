"""``otterdog-acceptance setup`` and ``otterdog-acceptance ci-sync`` (SPEC 16, docs/onboarding.md): the onboarding of a test org
instance.

setup runs the interactive wizard of otterdog_acceptance.onboard (org, tokens of every role, web login, the GitHub App through
the manifest flow of app-manifest), then ``bootstrap --apply --wait`` and doctor, each on a fresh copy of the
environment setup started with; ci-sync creates the CI environments of the instance and sets their variables and
secrets with the operator's gh login. Both are refused in CI.
"""

from __future__ import annotations

import contextlib
import dataclasses
import functools
import os
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from otterdog_acceptance.cli.app_manifest import ManifestFlow
from otterdog_acceptance.cli.bootstrap import BOOTSTRAP_WAIT_TIMEOUT, Bootstrap
from otterdog_acceptance.cli.common import _echo, _handled, _settings, main
from otterdog_acceptance.cli.doctor import Doctor, render_rows
from otterdog_acceptance.context import E2EContext, E2EOptions, parse_duration
from otterdog_acceptance.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_acceptance.onboard.accounts import AccountResult, AccountsIO, MachineAccount, SignIn
    from otterdog_acceptance.onboard.browser import PlaywrightBrowser
    from otterdog_acceptance.onboard.wizard import SetupOptions
    from otterdog_acceptance.settings import Target

# --- setup and ci-sync: onboarding of a test org instance (otterdog_acceptance.onboard, docs/onboarding.md) ---------------
ACCOUNT_ROLES = ("admin", "oracle", "author", "approver", "outsider", "config_reader")  # onboard.tokens.ROLES
SETUP_ROTATABLE = (*ACCOUNT_ROLES, "web", "app")


def _instance(target: str) -> str:
    """The one instance of setup / ci-sync (UsageError for an invalid name or a list of targets)."""
    from otterdog_acceptance.onboard.envfile import InstanceNameError, check_instance_name

    try:
        return check_instance_name(target)
    except InstanceNameError as exc:
        raise click.UsageError(f"--target: {exc} (setup and ci-sync take one instance)") from None


def _setup_bootstrap(
    instance: str,
    *,
    pristine: Mapping[str, str],
    wait_timeout: float = BOOTSTRAP_WAIT_TIMEOUT,
    join: Callable[..., object] | None = None,
    automatic: bool = False,
) -> None:
    """``bootstrap --target <instance> --apply --wait`` started by the setup wizard (asks for the typed org login,
    typed by setup itself when ``automatic`` and the org has no foreign member, then waits for the invitations to be accepted, the memberships made public and the App installed). Each run gets
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
            join=join,
            automatic=automatic,
        ).run()
    finally:
        context.close()


def _setup_doctor(instance: str, *, pristine: Mapping[str, str]) -> None:
    """``doctor --target <instance>`` started by the setup wizard (the table only: failures do not stop setup), on a
    fresh copy of ``pristine`` (see _setup_bootstrap)."""
    context = E2EContext.create(E2EOptions(target=instance), environ=dict(pristine), make_dirs=False)
    _echo(render_rows(Doctor(context).run()))


def _setup_echo(text: str = "") -> None:
    """_echo of setup's lines, their marks in colour (click drops the styles when the output is no terminal):
    titles bold, done green, needs attention yellow, skipped and saved dim."""
    from otterdog_acceptance.onboard.wizard import DONE, SKIPPED, WARN

    text = REDACTOR(text)
    body = text.lstrip(" ")
    indent = text[: len(text) - len(body)]
    if body.startswith(("\u2501", "\u25b8 ")):
        text = click.style(text, bold=True)
    elif body.startswith((f"{DONE} ", f"{WARN} ")):
        colour = "green" if body.startswith(DONE) else "yellow"
        text = indent + click.style(body[0], fg=colour, bold=True) + body[1:]
    elif body.startswith((f"{SKIPPED} ", "saved ", "(")):
        text = click.style(text, dim=True)
    click.echo(text)


def _accounts_io(echo: Callable[[str], None] = _echo) -> AccountsIO:
    """The terminal side of onboard.accounts (hidden password prompt, plain device code prompt)."""
    from otterdog_acceptance.onboard.accounts import AccountsIO

    return AccountsIO(
        echo=echo,
        secret_prompt=lambda text: str(click.prompt(text, default="", hide_input=True, show_default=False)),
        prompt=lambda text: str(click.prompt(text, default="", show_default=False)),
    )


def _open_browser(stack: contextlib.ExitStack) -> PlaywrightBrowser:
    """A visible Firefox for the machine accounts, closed with ``stack``; failed accounts pause before closing."""
    from otterdog_acceptance.onboard.browser import PlaywrightBrowser

    def pause(message: str) -> None:
        """Wait for the operator before a failed account's window closes."""
        click.prompt(message, default="", show_default=False)

    browser = PlaywrightBrowser(pause=pause)  # Playwright's Firefox (make init), not the web-UI tier's
    return stack.enter_context(browser)


class _LazyBrowser:
    """The browser of ``accounts``: Firefox starts at the first account that needs it (none when all are complete)."""

    def __init__(self, stack: contextlib.ExitStack) -> None:
        """Bind the exit stack that closes Firefox."""
        self.stack = stack
        self.browser: PlaywrightBrowser | None = None

    def session(self) -> contextlib.AbstractContextManager[Any]:
        """A session of the browser, started first when needed."""
        if self.browser is None:
            self.browser = _open_browser(self.stack)
        return self.browser.session()


def _setup_accounts(browser: _LazyBrowser) -> Callable[..., AccountResult]:
    """``run_account`` of the setup wizard: AccountSetup.setup in ``browser`` (the Firefox of the web steps, started
    at first use), its lines under the step of the role; the classic tokens get no expiration."""
    from otterdog_acceptance.onboard.accounts import AccountSetup

    def run_account(account: MachineAccount, *, org: str, rotate: bool, environ: Mapping[str, str]) -> AccountResult:
        """Set up one machine account."""
        io = _accounts_io(lambda text: _setup_echo(f"  {text}"))
        accounts = AccountSetup(org=org, environ=environ, browser=browser, io=io, rotate=rotate)
        return accounts.setup(account)

    return run_account


def _setup_manifest(
    port: int, open_url: Callable[[str], Any] | None, web: _WebSteps | None = None
) -> Callable[[Target, str], str]:
    """The App manifest flow of the wizard: the loopback listener of app-manifest on ``port``; the admin confirms the
    App in Firefox when ``web`` can sign it in."""

    def ready(url: str) -> None:
        """Confirm the App in Firefox as the admin, else tell where to confirm it (and open it with --open)."""
        if web is not None and web.confirm_app(url):
            return
        _echo(f"open {url} in a browser logged in as an owner of the test org, then confirm the App")
        if open_url is not None:
            open_url(url)

    def run_flow(target: Target, webhook_url: str) -> str:
        """Serve the auto-posting manifest form and return the code of GitHub's redirect."""
        return ManifestFlow(target, webhook_url=webhook_url, port=port).run(on_ready=ready)

    return run_flow


@main.command("setup")
@click.option(
    "--target",
    "target",
    default=None,
    help="instance name (env file ~/.config/otterdog-acceptance/<name>.env), or --shards",
)
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
    "--browser/--no-browser",
    default=None,
    help="create the classic tokens (and enroll 2FA) of the machine accounts in a Firefox window, their secrets in "
    "the accounts store of ~/.config/otterdog-acceptance/setup.yaml, like `otterdog-acceptance accounts` (default: when that "
    "store is configured); --no-browser prints the prefilled token URLs and their steps instead",
)
@click.option(
    "--shard",
    default=None,
    help="the live items the instance runs (scenarios/shards.yaml, `otterdog-acceptance shards`); none: all of them "
    "(default: stored, else the shard named like the instance, confirmed)",
)
@click.option(
    "--shards",
    "all_shards",
    is_flag=True,
    help="set up the instance of every shard in turn (named after it, or the instance whose E2E_SHARD selects it), "
    "asking before setting up again one that is set up already, then list them in ~/.config/otterdog-acceptance/lists/shards",
)
@_handled
def setup_command(
    target: str | None,
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
    browser: bool | None,
    shard: str | None,
    all_shards: bool,
) -> None:
    """Onboard a test org interactively: org, tokens of every role, web login, GitHub App, then bootstrap and doctor.

    Every validated value is written at once to ~/.config/otterdog-acceptance/<instance>.env (0600): an interrupted run
    keeps its progress and the next one continues. Refused in CI. With an accounts store, the classic tokens of the
    machine accounts are created in Firefox (--no-browser: printed as prefilled URLs), and the web steps GitHub gives
    no API for are done there as the machine accounts, after a confirmation (creating the organization, accepting
    the invitations, making memberships public, creating and installing the App); otherwise they are printed as
    prefilled URLs. --shards sets up the instance of every shard in turn.
    """
    from otterdog_acceptance.onboard.wizard import DONE, SKIPPED, SetupOptions, banner
    from otterdog_acceptance.shards import SHARDS_LIST

    if all_shards == (target is not None):
        raise click.UsageError("setup takes --target <instance> or --shards")
    if all_shards and (org or profile or shard):
        raise click.UsageError("--shards sets up several organizations: --org, --profile and --shard name one")
    pristine = dict(os.environ)  # before any env file was read: the wizard, bootstrap and doctor each get a copy
    try:
        timeout = parse_duration(wait_timeout).total_seconds()
    except ValueError as exc:
        raise click.UsageError(f"--wait-timeout: {exc}") from None
    options = SetupOptions(
        instance=_instance(target) if target else "",
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
        shard=shard,
    )
    if not all_shards:
        _setup_instance(options, pristine=pristine, port=port)
        return
    automatic = _automatic(options, pristine)
    instances = _shard_instances(pristine)
    for number, (instance, shard_name) in enumerate(instances, start=1):
        named = "" if instance == shard_name else f" (shard {shard_name})"
        _setup_echo("")
        _setup_echo(banner(f"[{number}/{len(instances)}] {instance}{named}"))
        if _set_up_already(instance, shard_name, pristine) and (
            _setup_finished(instance, pristine)
            if automatic
            else not click.confirm(f"{instance} is set up already: run its setup again?", default=False)
        ):
            _setup_echo(
                f"{SKIPPED} kept as it is" + (f" (setup --target {instance} runs it again)" if automatic else "")
            )
            continue
        try:
            _setup_instance(
                dataclasses.replace(options, instance=instance, shard=shard_name, banner=False),
                pristine=pristine,
                port=port,
            )
        except click.ClickException as exc:
            raise click.ClickException(
                f"setup of {instance} stopped: {exc.message}; `otterdog-acceptance setup --shards` resumes (it asks before "
                "setting up again the instances done)"
            ) from None
    _setup_echo("")
    _setup_echo(banner("every shard has its instance"))
    _setup_echo(
        f"{DONE} {len(instances)} organizations: otterdog-acceptance run --target @{SHARDS_LIST} --parallel {len(instances)}"
    )


def _setup_instance(options: SetupOptions, *, pristine: Mapping[str, str], port: int) -> None:
    """The setup wizard of one instance, with the browser steps when the accounts store has the accounts."""
    import webbrowser

    from otterdog_acceptance.onboard.wizard import SetupError, SetupWizard, WizardIO

    io = WizardIO(
        prompt=lambda text, default: str(click.prompt(text, default=default)).strip(),
        secret_prompt=lambda text: str(click.prompt(text, default="", hide_input=True, show_default=False)),
        confirm=lambda text, default: bool(click.confirm(text, default=default)),
        echo=_setup_echo,
        open_url=webbrowser.open,
    )
    automatic = _automatic(options, pristine)
    with contextlib.ExitStack() as stack:
        web = _WebSteps(stack, options.instance, pristine, automatic=automatic)
        wizard = SetupWizard(
            options,
            io,
            environ=pristine,
            settings=_settings(),
            run_manifest=_setup_manifest(port, webbrowser.open if options.open_urls else None, web),
            bootstrap=functools.partial(
                _setup_bootstrap,
                pristine=pristine,
                wait_timeout=options.wait_timeout,
                join=web.join,
                automatic=automatic,
            ),
            doctor=functools.partial(_setup_doctor, pristine=pristine),
            run_account=None if options.browser is False else _setup_accounts(web.browser),
            sign_in_at=_sign_in_at,
            web=web,
        )
        try:
            wizard.run()
        except SetupError as exc:
            raise click.ClickException(str(exc)) from None


def _shard_instances(environ: Mapping[str, str]) -> list[tuple[str, str]]:
    """(instance, shard) of every shard, in the order of the map: the instance whose E2E_SHARD selects it, else the
    instance named after it."""
    from otterdog_acceptance.batch import list_instances
    from otterdog_acceptance.shards import SHARDS_FILE, ShardError, load_shards

    settings = _settings()
    try:
        shards = load_shards(settings.project_root)
    except ShardError as exc:
        raise click.ClickException(str(exc)) from None
    if shards is None:
        raise click.ClickException(f"--shards: no {SHARDS_FILE} in {settings.project_root}")
    selected: dict[str, str] = {}
    for info in list_instances(settings, environ):
        if info.shard:
            selected.setdefault(info.shard, info.name)
    return [(selected.get(shard.name, shard.name), shard.name) for shard in shards.shards]


def _automatic(options: SetupOptions, environ: Mapping[str, str]) -> bool:
    """Whether setup decides instead of asking (SetupWizard.automatic): an accounts store, the browser not refused."""
    from otterdog_acceptance.onboard.accounts import AccountError, load_accounts_config

    if options.browser is False:
        return False
    try:
        return load_accounts_config(environ) is not None
    except AccountError:
        return False


def _setup_finished(instance: str, environ: Mapping[str, str]) -> bool:
    """Whether a setup of ``instance`` ran to its end: it then joined the list of the shards (@shards)."""
    from otterdog_acceptance.batch import listed
    from otterdog_acceptance.shards import SHARDS_LIST

    return listed(SHARDS_LIST, instance, environ)


def _set_up_already(instance: str, shard: str, environ: Mapping[str, str]) -> bool:
    """Whether the env file of ``instance`` holds its organization, its admin token and the shard (setup got past
    them: running it again only checks what is stored)."""
    from otterdog_acceptance.onboard.envfile import instance_env_path, read_env_file

    path = instance_env_path(instance, environ)
    values = read_env_file(path) if path.is_file() else {}
    return bool(values.get("E2E_ORG_ID") and values.get("E2E_ADMIN_TOKEN")) and values.get("E2E_SHARD") == shard


class _WebSteps:
    """The GitHub web steps of setup and bootstrap done in Firefox as the machine accounts of the accounts store
    (onboard.wizard.WebSteps): each step asks first (``automatic``: done without asking); one the store cannot
    sign in for, or that fails (the window stays
    open to finish it by hand), is left to the operator, whom setup's wait then waits for."""

    def __init__(
        self, stack: contextlib.ExitStack, instance: str, environ: Mapping[str, str], *, automatic: bool = False
    ) -> None:
        """Bind; Firefox starts at the first step done."""
        self.instance = instance
        self.automatic = automatic
        self.environ = environ
        self.browser = _LazyBrowser(stack)

    def _account(self, role: str) -> SignIn | None:
        """The sign-in of the role's account in the accounts store (its set's), None without it."""
        from otterdog_acceptance.onboard.accounts import AccountError, AccountSetup, load_accounts_config
        from otterdog_acceptance.onboard.wizard import WARN

        try:
            config = load_accounts_config(self.environ)
            if config is None:
                return None
            store = AccountSetup(org=None, environ=self.environ, browser=self.browser, io=_accounts_io())
            account = config.account(self.instance, role)
            return store.sign_in(account) if store.read(account, "password") is not None else None
        except AccountError as exc:
            _setup_echo(f"  {WARN} {role}: browser: {exc}")
            return None

    def _do(self, role: str, what: str, action: Callable[[Any], None]) -> bool:
        """Sign the role's account in and do ``action`` with its session, after a confirmation; whether it was done."""
        from otterdog_acceptance.onboard.accounts import AccountError, signed_in
        from otterdog_acceptance.onboard.wizard import DONE, WARN

        account = self._account(role)
        if account is None or not (
            self.automatic or click.confirm(f"  {role}: {what} in Firefox, as {account.name}?", default=True)
        ):
            return False
        try:
            with signed_in(self.browser, _accounts_io(), account) as (session, _):
                action(session)
        except AccountError as exc:
            _setup_echo(f"  {WARN} {role}: browser: {exc}: left to you")
            return False
        _setup_echo(f"  {DONE} {role}: {what}")
        return True

    def join(self, role: str, org: str, login: str, *, public: bool) -> bool:
        """``login`` accepts its invitation of ``org`` (and makes its membership public)."""
        what = f"accept the invitation of {org}" + (" and make the membership public" if public else "")
        return self._do(role, what, lambda session: session.join_org(org, login, public=public))

    def install_app(self, url: str) -> bool:
        """The admin installs the App."""
        return self._do("admin", "install the GitHub App", lambda session: session.install_app(url))

    def confirm_app(self, url: str) -> bool:
        """The admin creates the App of setup's manifest form ``url``."""
        return self._do("admin", "create the GitHub App", lambda session: session.confirm_app(url))


@main.command("accounts")
@click.option(
    "--target", "target", required=True, help="instance name (env file ~/.config/otterdog-acceptance/<name>.env)"
)
@click.option(
    "--role",
    "roles",
    multiple=True,
    type=click.Choice(ACCOUNT_ROLES),
    help="role(s) to set up, repeatable (default: every role whose account is in the accounts store)",
)
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="setup configuration file with the accounts section (default: E2E_SETUP_CONFIG, else "
    "~/.config/otterdog-acceptance/setup.yaml)",
)
@click.option("--rotate", is_flag=True, help="create a new token even when the one in the store is valid")
@click.option(
    "--expires-in",
    default="none",
    show_default=True,
    type=click.Choice(["7", "30", "60", "90", "none"]),
    help="days of validity of the classic tokens (none: no expiration)",
)
@_handled
def accounts_command(
    target: str, roles: tuple[str, ...], config_path: Path | None, rotate: bool, expires_in: str
) -> None:
    """Set up machine accounts in a Firefox window: sign in, enroll 2FA when missing, create the classic token.

    Where their secrets are (store pass:<directory> or vault:<secret path>, entry name, item names) is the accounts
    section of the setup configuration file (docs/onboarding.md); pass runs with PASSWORD_STORE_DIR. The env file
    gets nothing: `otterdog-acceptance setup` then finds each token in the store and checks it. Refused in CI.
    """
    from otterdog_acceptance.context import in_ci
    from otterdog_acceptance.onboard.accounts import (
        SETUP_CONFIG_ENV,
        AccountError,
        AccountSetup,
        load_accounts_config,
        setup_config_path,
    )
    from otterdog_acceptance.onboard.envfile import instance_env_path, read_env_file

    if in_ci(os.environ):
        raise click.ClickException("accounts drives a visible browser and is refused when CI is set")
    instance = _instance(target)
    path = instance_env_path(instance, os.environ)
    values = read_env_file(path) if path.is_file() else {}
    environ = {**os.environ, **values, **({SETUP_CONFIG_ENV: str(config_path)} if config_path else {})}
    try:
        config = load_accounts_config(environ)
    except AccountError as exc:
        raise click.ClickException(str(exc)) from None
    if config is None:
        raise click.UsageError(
            f"no accounts section in {setup_config_path(environ)}: add one (store, entry, items: docs/onboarding.md)"
        )
    with contextlib.ExitStack() as stack:
        setup = AccountSetup(
            org=values.get("E2E_ORG"),
            environ=environ,
            browser=_LazyBrowser(stack),
            io=_accounts_io(),
            days=None if expires_in == "none" else int(expires_in),
            rotate=rotate,
        )
        accounts = [config.account(instance, role) for role in roles or ACCOUNT_ROLES]
        if not roles:
            accounts = [account for account in accounts if setup.exists(account)]
            if not accounts:
                raise click.UsageError(
                    f"no account of instance {instance} in {config.store} (e.g. "
                    f"{config.account(instance, 'admin').ref('password')}): --role to set one up anyway"
                )
        try:
            for result in setup.run(accounts):
                state = "created" if result.token_created else "kept"
                enrolled = ", 2FA enrolled" if result.enrolled else ""
                _echo(f"{result.role}: {result.login}: token {state} at {result.token_ref}{enrolled}")
        except AccountError as exc:
            raise click.ClickException(str(exc)) from None
    _echo(
        f"next: otterdog-acceptance setup --target {instance} (finds the tokens in the accounts store and checks them)"
    )


GITHUB = "https://github.com"


def web_login_url(url: str | None, org: str | None) -> str:
    """The page web-login shows: ``url`` (a page of github.com, or its path), else the page of the organization."""
    if not url:
        return f"{GITHUB}/{org}" if org else f"{GITHUB}/"
    if url.startswith("/"):
        return GITHUB + url
    if url == GITHUB or url.startswith(f"{GITHUB}/"):
        return url
    raise click.UsageError(f"--url {url!r}: a page of github.com (https://github.com/... or a path /...)")


def _admin_sign_in(instance: str, environ: Mapping[str, str]) -> tuple[SignIn | None, str | None]:
    """The web credentials of the admin in the env file of the instance (E2E_ADMIN_PASSWORD, E2E_ADMIN_TOTP_SEED),
    resolved as runs resolve them; else None and why."""
    from otterdog_acceptance.onboard.accounts import SignIn
    from otterdog_acceptance.settings import TargetError, load_target, resolve_web_credentials, web_credential_env_names

    try:
        target = load_target(instance, _settings(), environ)
        web = resolve_web_credentials(target, environ)
    except TargetError as exc:
        return None, str(exc)
    if web is None:
        return None, "E2E_ADMIN_PASSWORD and E2E_ADMIN_TOTP_SEED are not set"
    source = web_credential_env_names(target)["password_env"]
    return SignIn("admin", web.username, web.login, web.password, web.totp_seed, source), None


def _typed_sign_in(name: str | None) -> SignIn:
    """An account typed in the terminal: its login or e-mail (``name``, else asked) and its password (hidden); the
    2FA code is asked when GitHub asks it."""
    from otterdog_acceptance.onboard.accounts import SignIn

    name = (name or str(click.prompt("login or e-mail of the account"))).strip()
    password = str(click.prompt(f"password of {name} (input hidden)", default="", hide_input=True, show_default=False))
    if not name or not password:
        raise click.UsageError("web-login needs the login (or e-mail) and the password of the account")
    REDACTOR.add(password)
    return SignIn("account", name, None if "@" in name else name, password, None, "the terminal")


def _named_sign_in(name: str | None, config_path: Path | None, stack: contextlib.ExitStack) -> SignIn:
    """The account ``name`` of the accounts store when the store has its password (entries ``<name>-<item>``, e.g.
    otterdog-e2e-free-admin), else typed in the terminal."""
    from otterdog_acceptance.onboard.accounts import (
        SETUP_CONFIG_ENV,
        AccountSetup,
        load_accounts_config,
        setup_config_path,
    )

    environ = {**os.environ, **({SETUP_CONFIG_ENV: str(config_path)} if config_path else {})}
    if not name:
        return _typed_sign_in(name)
    config = load_accounts_config(environ)
    if config is None:
        _echo(
            f"no accounts store in {setup_config_path(environ)} (docs/onboarding.md): the password of {name} is typed"
        )
        return _typed_sign_in(name)
    store = AccountSetup(org=None, environ=environ, browser=_LazyBrowser(stack), io=_accounts_io())
    account = config.named(name)
    if store.read(account, "password") is None:
        _echo(f"no password of {name} at {account.ref('password')}: it is typed")
        return _typed_sign_in(name)
    return store.sign_in(account)


@main.command("web-login")
@click.argument("name", metavar="[ACCOUNT]", required=False)
@click.option(
    "--target",
    "target",
    default=None,
    help="instance whose account signs in (env file ~/.config/otterdog-acceptance/<name>.env), instead of ACCOUNT",
)
@click.option("--role", default=None, type=click.Choice(ACCOUNT_ROLES), help="account of the instance [default: admin]")
@click.option("--login", "login", default=None, help="ACCOUNT, as an option")
@click.option("--url", default=None, help="page to show: https://github.com/... or a path (default: the organization)")
@click.option(
    "--config",
    "config_path",
    default=None,
    type=click.Path(dir_okay=False, path_type=Path),
    help="setup configuration file with the accounts section (default: E2E_SETUP_CONFIG, else "
    "~/.config/otterdog-acceptance/setup.yaml)",
)
@_handled
def web_login_command(
    name: str | None,
    target: str | None,
    role: str | None,
    login: str | None,
    url: str | None,
    config_path: Path | None,
) -> None:
    """Open Firefox signed in as an account (like otterdog web-login): ACCOUNT, or an account of an instance on its
    test organization.

    ACCOUNT (a login, an e-mail, or the name of its entries in the accounts store, e.g. otterdog-e2e-free-admin):
    signs in with the password and 2FA key of the store when it has them, else the password and the 2FA code are
    typed (asked too without ACCOUNT). --target: admin signs in with the web credentials of the env file
    (E2E_ADMIN_PASSWORD, E2E_ADMIN_TOTP_SEED), else from the accounts store; the other roles from the accounts store
    (docs/onboarding.md). Enter in the terminal signs the account out and closes the window. Refused in CI.
    """
    from otterdog_acceptance.context import in_ci
    from otterdog_acceptance.onboard.accounts import AccountError, web_login

    if in_ci(os.environ):
        raise click.ClickException("web-login drives a visible browser and is refused when CI is set")
    if name and login and name != login:
        raise click.UsageError(f"ACCOUNT {name!r} or --login {login!r}: one account")
    name = name or login
    with contextlib.ExitStack() as stack:
        try:
            if target is None:
                if role:
                    raise click.UsageError("--role names an account of an instance: pass --target")
                account, page = _named_sign_in(name, config_path, stack), web_login_url(url, None)
            else:
                if name:
                    raise click.UsageError(f"ACCOUNT {name!r} or --target: an instance names its own accounts")
                account, page = _instance_sign_in(target, role or "admin", url, config_path, stack)
            shown = web_login(
                _open_browser(stack),
                _accounts_io(),
                account,
                page,
                until=lambda message: click.prompt(message, default="", show_default=False),
            )
        except AccountError as exc:
            raise click.ClickException(str(exc)) from None
    _echo(f"{account.role}: {shown} signed out, window closed")


def _sign_in_at(name: str, url: str) -> None:
    """``web-login ACCOUNT --url URL`` for setup: the creation of the organization by its admin account."""
    from otterdog_acceptance.onboard.accounts import web_login

    with contextlib.ExitStack() as stack:
        account = _named_sign_in(name, None, stack)
        web_login(
            _open_browser(stack),
            _accounts_io(),
            account,
            url,
            until=lambda message: click.prompt(message, default="", show_default=False),
        )


def _instance_sign_in(
    target: str, role: str, url: str | None, config_path: Path | None, stack: contextlib.ExitStack
) -> tuple[SignIn, str]:
    """The sign-in of the ``role`` account of an instance and the page to show (web-login --target)."""
    from otterdog_acceptance.onboard.accounts import (
        SETUP_CONFIG_ENV,
        AccountSetup,
        load_accounts_config,
        setup_config_path,
    )
    from otterdog_acceptance.onboard.envfile import instance_env_path, read_env_file

    instance = _instance(target)
    path = instance_env_path(instance, os.environ)
    values = read_env_file(path) if path.is_file() else {}
    environ = {**os.environ, **values, **({SETUP_CONFIG_ENV: str(config_path)} if config_path else {})}
    page = web_login_url(url, values.get("E2E_ORG"))
    account, why = _admin_sign_in(instance, environ) if role == "admin" and values else (None, None)
    if account is not None:
        return account, page
    config = load_accounts_config(environ)
    if config is None:
        env = f" ({path}: {why})" if why else ""
        raise click.UsageError(
            f"no web sign-in of the {role} account of {instance}{env}: add an accounts section to "
            f"{setup_config_path(environ)} (docs/onboarding.md)"
        )
    store = AccountSetup(org=values.get("E2E_ORG"), environ=environ, browser=_LazyBrowser(stack), io=_accounts_io())
    return store.sign_in(config.account(instance, role)), page


@main.command("ci-sync")
@click.option(
    "--target", "target", required=True, help="instance name (env file ~/.config/otterdog-acceptance/<name>.env)"
)
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
    from otterdog_acceptance.onboard.cisync import CiSync, CiSyncError

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
