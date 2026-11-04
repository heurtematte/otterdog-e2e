"""The browser side of onboard.accounts: github.com in a visible Firefox driven by Playwright, one isolated context per
machine account (its cookies are dropped, and the account signed out, when the account is done).

The selectors follow eclipse-cbi/ci-admin (github/playwright) where they are stable (the sign-in form, the setup key
dialog and the recovery codes of the 2FA enrollment, the expiration menu of the classic token form) and rely on URLs
and links elsewhere. GitHub changes its pages without notice: a step that does not find what it expects raises
AccountError naming the step, and the window stays open (``pause``) for the operator to see the page and finish by
hand, instead of guessing. The setup key of the 2FA enrollment is read again until GitHub filled it in, from its
element, its dialog or an otpauth:// URI of the page (invisible characters and the words around dropped); when none
holds a key, the error describes what the element showed (lengths, kinds of characters), never its text. Nothing is
screenshotted or saved: these pages show secrets. The recovery codes download that unlocks the acknowledgement stays
in Playwright's temporary directory, deleted with the context.

Playwright is an optional dependency (``poetry install -E browser``, which ``make init`` installs with Firefox); its
Firefox is Playwright's own, in PLAYWRIGHT_BROWSERS_PATH or else its global cache (``~/.cache/ms-playwright`` on
Linux, shared with otterdog's ``make init``): ``.venv/bin/python -m playwright install firefox``. The web-UI tier keeps
the browsers of each SUT apart (sut.cli_install.playwright_browsers_path).

GNOME 46 (Ubuntu 24.04) moved the font keys of its xsettings schema to a ``.deprecated`` schema, and Playwright's
Firefox still reads them in the first one: it aborts at start. Firefox gets a schema directory with those keys back
(gsettings_compat_dir, GSETTINGS_SCHEMA_DIR), the system untouched.
"""

from __future__ import annotations

import contextlib
import html
import os
import re
import shutil
import sys
import time
import unicodedata
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any, Self

from otterdog_e2e import procs
from otterdog_e2e.onboard.accounts import TOTP_PERIOD, AccountError
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.settings import DEFAULT_CACHE_DIR, WebCredentialsError, normalize_totp_seed

LOGIN_URL = "https://github.com/login"
LOGOUT_URL = "https://github.com/logout"
SECURITY_URL = "https://github.com/settings/security"
TWO_FACTOR_SETUP_URL = "https://github.com/settings/two_factor_authentication/setup/intro"
TOKENS_URL = "https://github.com/settings/tokens"
INVITATION_URL = "https://github.com/orgs/{org}/invitation"
PEOPLE_URL = "https://github.com/orgs/{org}/people?query={login}"
PUBLIC_MEMBER_API = "https://api.github.com/orgs/{org}/public_members/{login}"  # 204: a public member (anonymous)
PUBLIC_CHECKS = 6  # reads of the public API, 2 s apart, until it lists a membership made public (60 reads/hour)
JOIN_RE = re.compile(r"^\s*join\b", re.IGNORECASE)
PRIVATE_RE = re.compile(r"^\s*private\b", re.IGNORECASE)
PUBLIC_RE = re.compile(r"^\s*public\b", re.IGNORECASE)
LOOPBACK_CALLBACK_RE = re.compile(r"^http://127\.0\.0\.1:\d+/callback")
CLASSIC_TOKEN_RE = re.compile(r"\bghp_[A-Za-z0-9]{36}\b")
EXPIRATION_MENU = '#token-expiration button[aria-haspopup="true"]'  # labelled "Expiration", or the current choice
EXPIRATION_FIELD = 'input[name$="[default_expires_at]"]'  # the hidden field the menu sets: 7 ... 90, custom, none
GENERATE_BUTTON = 'form#new_oauth_access button[type="submit"]'
MENU_TIMEOUT_MS = 5_000
SETUP_KEY_SELECTOR = '[data-target="two-factor-setup-verification.mashedSecret"]'
SETUP_KEY_DIALOG = "#two-factor-setup-verification-mashed-secret"
SETUP_KEY_TIMEOUT = 10.0  # seconds for GitHub to fill the setup key in
KEY_GROUPS_RE = re.compile(r"[A-Z2-7]{3,}(?:[ -][A-Z2-7]{3,})*")  # upper case only: the words around are not keys
OTPAUTH_RE = re.compile(r"otpauth://totp/[^\s\"'<>]+", re.IGNORECASE)
KEY_TEXTS_JS = """elements => elements.flatMap(element => {
  const walker = document.createTreeWalker(element, NodeFilter.SHOW_TEXT), texts = [];
  while (walker.nextNode()) texts.push(walker.currentNode.nodeValue);
  for (const field of [element, ...element.querySelectorAll("input, textarea, [value]")]) {
    if (typeof field.value === "string") texts.push(field.value);
    if (field.getAttribute("value")) texts.push(field.getAttribute("value"));
  }
  return texts;
})"""  # each text node apart (the key without the "Copied!" an inline element glues to it), the fields' values
DEFAULT_TIMEOUT_MS = 15_000
HUMAN_TIMEOUT = 300.0  # seconds for what the operator does in the window (device code, captcha)
INSTALL_HINT = (
    "install the browser extra and Firefox: make init (or poetry install -E browser, then "
    "{env}.venv/bin/python -m playwright install firefox)"
)


SYSTEM_SCHEMAS = Path("/usr/share/glib-2.0/schemas")
XSETTINGS_SCHEMA = "org.gnome.settings-daemon.plugins.xsettings"
GSD_ENUMS = "org.gnome.settings-daemon.enums.xml"  # the enums the font keys use
MISSING_FIREFOX_RE = re.compile(r"Executable doesn't exist|playwright install", re.IGNORECASE)


def _message(exc: BaseException) -> str:
    """First line of a Playwright error, redacted."""
    text = str(exc).strip().splitlines()
    return REDACTOR(text[0] if text else type(exc).__name__)


def _launch_error(exc: BaseException) -> str:
    """Why Firefox stopped: the last line of its error output in the Playwright error, else its first line."""
    printed = [line.split("[err]", 1)[1].strip() for line in str(exc).splitlines() if "[err]" in line]
    printed = [line for line in printed if line]
    return REDACTOR(printed[-1]) if printed else _message(exc)


def _visible_text(text: str) -> str:
    """``text`` without its invisible characters (zero-width spaces, soft hyphens), its dashes as ``-``."""
    kinds = {char: unicodedata.category(char) for char in set(text)}
    return "".join("-" if kinds[char] == "Pd" else char for char in text if kinds[char] != "Cf")


def setup_key_in(texts: Iterable[str]) -> str | None:
    """The first base32 key, normalized, in the texts of GitHub's setup key dialog: an ``otpauth://`` URI or a run of
    upper-case base32 groups (``ABCD EFGH ...``); None when no text holds one of at least 80 bits."""
    for text in texts:
        visible = _visible_text(html.unescape(text))
        for candidate in [*OTPAUTH_RE.findall(visible), *KEY_GROUPS_RE.findall(visible)]:
            with contextlib.suppress(WebCredentialsError):
                return normalize_totp_seed(candidate)
    return None


def _char_kind(char: str) -> str:
    """The kind of a character of a setup key text, named without the character when it may belong to a key."""
    if char.isupper():
        return "upper-case letters"
    if char.islower():
        return "lower-case letters"
    if char.isdigit():
        return "digits 2-7" if char in "234567" else "digits 0 1 8 9"
    if char.isspace():
        return "spaces"
    return unicodedata.name(char, f"U+{ord(char):04X}").lower()


def describe_key_texts(texts: list[str]) -> str:
    """What the setup key elements showed, without the key: the length and the kinds of characters of each text."""
    if not texts:
        return "no setup key element"
    shapes = []
    for text in texts:
        kinds = sorted({_char_kind(char) for char in text})
        shapes.append(f"{len(text)} characters" + (f" ({', '.join(kinds)})" if kinds else ""))
    return "; ".join(shapes)


def gsettings_compat_dir(target: Path, system: Path = SYSTEM_SCHEMAS) -> Path | None:
    """``target`` holding the xsettings schema of GNOME with the font keys its ``.deprecated`` schema took over
    (antialiasing, hinting, rgba-order) back in it, compiled: GSETTINGS_SCHEMA_DIR for Firefox, its schemas winning
    over the system's (the other schemas still come from the system). None when the system schema needs nothing,
    or the directory cannot be built (no glib-compile-schemas); rebuilt only when the system schemas change."""
    name = re.escape(XSETTINGS_SCHEMA)
    try:
        source = (system / f"{XSETTINGS_SCHEMA}.gschema.xml").read_text(encoding="utf-8")
        enums = (system / GSD_ENUMS).read_text(encoding="utf-8")
    except OSError:
        return None
    main = re.search(rf'<schema\b[^>]*\bid="{name}"[^>]*>(?P<keys>.*?)(?=\s*</schema>)', source, re.DOTALL)
    deprecated = re.search(rf'<schema\b[^>]*\bid="{name}\.deprecated"[^>]*>(?P<keys>.*?)</schema>', source, re.DOTALL)
    if main is None or deprecated is None or 'name="antialiasing"' in main["keys"]:
        return None
    merged = source[: main.end("keys")] + deprecated["keys"].rstrip() + source[main.end("keys") :]
    files = {f"{XSETTINGS_SCHEMA}.gschema.xml": merged, GSD_ENUMS: enums}
    compiled = target / "gschemas.compiled"
    with contextlib.suppress(OSError):
        if compiled.is_file() and all(
            (target / file).read_text(encoding="utf-8") == text for file, text in files.items()
        ):
            return target
    compiler = shutil.which("glib-compile-schemas")
    if compiler is None:
        return None
    try:
        target.mkdir(parents=True, exist_ok=True)
        for file, text in files.items():
            (target / file).write_text(text, encoding="utf-8")
        result = procs.run([compiler, str(target)], timeout=60)
    except (OSError, procs.TimeoutExpired):
        return None
    return target if result.returncode == 0 and compiled.is_file() else None


class PlaywrightSession:
    """One machine account in one browser context (onboard.accounts.GitHubSession)."""

    def __init__(self, page: Any) -> None:
        """Bind the context's page."""
        self.page = page
        self.password: str | None = None  # kept for a sudo confirmation, as the 2FA code source
        self.code: Callable[[], str] | None = None
        self.last_code: str | None = None

    @contextlib.contextmanager
    def step(self, name: str) -> Iterator[None]:
        """Turn a Playwright error of a step into AccountError naming the step."""
        from playwright.sync_api import Error

        try:
            yield
        except Error as exc:
            raise AccountError(f"{name}: {_message(exc)} (page {self.page.url})") from None

    def fresh_code(self, code: Callable[[], str]) -> str:
        """A TOTP code GitHub has not seen in this session: waits for the next period when the current one was used."""
        value = code()
        if value == self.last_code:
            time.sleep(TOTP_PERIOD - time.time() % TOTP_PERIOD + 1)
            value = code()
        self.last_code = value
        return value

    def current_login(self) -> str:
        """The signed-in login of the page (``<meta name="user-login">``), '' when signed out."""
        meta = self.page.locator('meta[name="user-login"]')
        return (meta.first.get_attribute("content") or "").strip() if meta.count() else ""

    def visible(self, locator: Any) -> bool:
        """Whether the locator matches a visible element."""
        return bool(locator.count()) and bool(locator.first.is_visible())

    # --- sign-in ------------------------------------------------------------------------------------------------
    def login(self, username: str, password: str, *, code: Callable[[], str], device_code: Callable[[], str]) -> str:
        """Sign in, answering the 2FA code, the e-mailed device code and the account checkups GitHub may show."""
        page = self.page
        self.password, self.code = password, code
        with self.step("sign-in page"):
            page.goto(LOGIN_URL)
            page.locator("#login_field").fill(username)
            page.locator("#password").fill(password)
            page.locator("input[type=submit][name=commit]").click()
        deadline = time.monotonic() + HUMAN_TIMEOUT
        while time.monotonic() < deadline:
            with self.step("sign-in"):
                page.wait_for_load_state()
                url = page.url
                if "/sessions/two-factor" in url:
                    self.two_factor_code(code)
                elif "/sessions/verified-device" in url:
                    self.verified_device(device_code)
                elif self.visible(page.get_by_text("Incorrect username or password")):
                    raise AccountError("sign-in refused: incorrect username or password (check the password in pass)")
                elif login := self.current_login():
                    self.checkups(code)
                    return login
                else:
                    page.wait_for_timeout(1000)  # a captcha or a page in progress: the operator sees the window
        raise AccountError(f"sign-in did not complete within {HUMAN_TIMEOUT:.0f} s (page {page.url})")

    def two_factor_code(self, code: Callable[[], str]) -> None:
        """The 2FA page: the authenticator app code (the method chosen first when GitHub proposes another one)."""
        page = self.page
        field = page.locator("#app_totp")
        if not field.count():
            page.get_by_role("link", name=re.compile(r"authenticator app", re.IGNORECASE)).first.click()
            page.wait_for_load_state()
        field.fill(self.fresh_code(code))  # submits itself once the 6 digits are in
        page.wait_for_url(lambda url: "/sessions/two-factor" not in url)

    def verified_device(self, device_code: Callable[[], str]) -> None:
        """The device verification page: the e-mailed code typed in the terminal, else in the window."""
        page = self.page
        value = device_code()
        if value:
            field = page.locator("#otp")
            field.fill(value)
            field.press("Enter")
        page.wait_for_url(lambda url: "/sessions/verified-device" not in url, timeout=HUMAN_TIMEOUT * 1000)

    def checkups(self, code: Callable[[], str]) -> None:
        """The pages GitHub may put after a sign-in: confirm the recovery settings, verify 2FA (as ci-admin does)."""
        page = self.page
        confirm = page.get_by_role("button", name="Confirm", exact=True)
        if self.visible(page.get_by_text("Confirm your account recovery settings")) and confirm.count():
            confirm.first.click()
            page.wait_for_load_state()
        verify = page.get_by_role("button", name=re.compile(r"verify 2fa now", re.IGNORECASE))
        if self.visible(verify):
            verify.first.click()
            page.locator("input[autocomplete='one-time-code'], #app_totp").first.fill(self.fresh_code(code))
            page.wait_for_load_state()
            done = page.get_by_role("link", name="Done", exact=True)
            if done.count():
                done.first.click()

    def sudo(self) -> None:
        """Answer GitHub's "Confirm access" (sudo mode) with the password, else a 2FA code of the sign-in's source."""
        page = self.page
        page.wait_for_load_state()
        if "/sessions/sudo" not in page.url and not self.visible(page.get_by_role("heading", name="Confirm access")):
            return
        password = page.locator("input[type=password]:visible")
        totp = page.locator("input[autocomplete='one-time-code']:visible, #app_totp:visible")
        if password.count() and self.password:
            password.first.fill(self.password)
            password.first.press("Enter")
        elif totp.count() and self.code is not None:
            totp.first.fill(self.fresh_code(self.code))
        else:
            raise AccountError("confirm access: neither a password nor a code field (confirm it in the window)")
        page.wait_for_load_state()

    # --- two-factor authentication ------------------------------------------------------------------------------
    def two_factor_enabled(self) -> bool:
        """False when the security settings offer to enable 2FA."""
        page = self.page
        with self.step("security settings"):
            page.goto(SECURITY_URL)
            self.sudo()
            enable = page.locator('a[href*="/settings/two_factor_authentication/setup"]')
            return not (enable.count() or self.visible(page.get_by_text("Two-factor authentication is not enabled")))

    def setup_key(self, ask_key: Callable[[str], str]) -> str:
        """The setup key of a new authenticator app, from the dialog of the setup page (the key elements as shown,
        their text nodes and field values, their text as written, the dialog, an otpauth:// URI of the page), read
        again until GitHub filled it in; ``ask_key(problem)`` when none holds a key (copied from the open dialog)."""
        page = self.page
        with self.step("2FA setup key"):
            page.goto(TWO_FACTOR_SETUP_URL)
            self.sudo()
            page.get_by_role("button", name=re.compile(r"setup key", re.IGNORECASE)).first.click()
            elements, dialog = page.locator(SETUP_KEY_SELECTOR), page.locator(SETUP_KEY_DIALOG)
            deadline = time.monotonic() + SETUP_KEY_TIMEOUT
            while True:
                shown = elements.all_inner_texts()
                inside = [text for text in elements.evaluate_all(KEY_TEXTS_JS) if text.strip()]
                around = [*dialog.all_inner_texts(), *dialog.evaluate_all(KEY_TEXTS_JS)]
                key = setup_key_in([*shown, *inside, *elements.all_text_contents(), *around])
                key = key or setup_key_in(OTPAUTH_RE.findall(html.unescape(page.content())))
                if key is not None or time.monotonic() >= deadline:
                    break
                page.wait_for_timeout(500)
        if key is None:
            seen = list(dict.fromkeys([*shown, *inside]))
            return ask_key(f"GitHub's setup key could not be read ({describe_key_texts(seen)})")
        REDACTOR.add(key)
        return key

    def enroll_two_factor(
        self,
        *,
        keep_seed: Callable[[str], None],
        code: Callable[[str], str],
        keep_recovery_codes: Callable[[list[str]], None],
        ask_key: Callable[[str], str],
    ) -> None:
        """Authenticator app enrollment: setup key (kept first), its code, recovery codes (kept first), done."""
        page = self.page
        key = self.setup_key(ask_key)
        keep_seed(key)
        with self.step("2FA code"):
            page.keyboard.press("Escape")
            field = page.get_by_role("textbox", name=re.compile(r"verify the code", re.IGNORECASE))
            value = code(key)
            self.last_code = value
            field.first.fill(value)
            proceed = page.get_by_role("button", name=re.compile(r"^continue$", re.IGNORECASE))
            if self.visible(proceed) and proceed.first.is_enabled():
                proceed.first.click()
        with self.step("2FA recovery codes"):
            codes = page.locator(".two-factor-recovery-code")
            codes.first.wait_for()
            found = [text.strip() for text in codes.all_text_contents()]
        REDACTOR.add(*found)
        keep_recovery_codes(found)
        with self.step("2FA acknowledgement"):
            with page.expect_download():  # GitHub unlocks the acknowledgement once the codes were saved somewhere
                page.get_by_role("button", name=re.compile(r"^download$", re.IGNORECASE)).first.click()
            page.get_by_role("button", name=re.compile(r"I have saved my recovery codes", re.IGNORECASE)).first.click()
            done = page.get_by_role("button", name=re.compile(r"^done$", re.IGNORECASE))
            if done.count():
                done.first.click()
            page.wait_for_load_state()

    # --- classic token ------------------------------------------------------------------------------------------
    def classic_token(self, *, note: str, url: str, days: int | None) -> str:
        """Regenerate the classic token ``note`` when it exists (its value cannot be read again), else generate it
        from the prefilled ``url`` (note and scopes); the expiration ``days`` (None: none); the value GitHub shows
        once."""
        page = self.page
        with self.step("token list"):
            page.goto(TOKENS_URL)
            self.sudo()
            existing = page.get_by_role("link", name=note, exact=True)
            regenerate = bool(existing.count())
        if regenerate:
            with self.step("regenerate the token"):
                existing.first.click()
                page.get_by_role("link", name=re.compile(r"regenerate token", re.IGNORECASE)).first.click()
                self.sudo()
                self.expiration(days)
                page.get_by_role("button", name=re.compile(r"^regenerate token$", re.IGNORECASE)).first.click()
        else:
            with self.step("generate the token"):
                page.goto(url)
                self.sudo()
                self.expiration(days)
                submit = page.locator(GENERATE_BUTTON)
                if not submit.count():
                    submit = page.get_by_role("button", name=re.compile(r"^generate token$", re.IGNORECASE))
                submit.first.click()
        with self.step("new token"):
            page.wait_for_load_state()
            if self.visible(page.get_by_text(re.compile(r"has already been taken", re.IGNORECASE))):
                raise AccountError(
                    f"a classic token noted {note!r} exists but is not in the token list: delete it, then run again"
                )
            shown = page.locator("#new-oauth-token")
            text = shown.first.inner_text() if shown.count() else page.content()
            match = CLASSIC_TOKEN_RE.search(text)
            flash = page.locator(".flash-error:visible, .error:visible")
            refused = " ".join(flash.first.inner_text().split()) if match is None and flash.count() else ""
        if match is None:
            said = f": {REDACTOR(refused)}" if refused else ""
            raise AccountError(f"new token: GitHub showed no classic token (ghp_...){said} (page {page.url})")
        REDACTOR.add(match.group(0))
        return match.group(0)

    def expiration(self, days: int | None) -> None:
        """Pick ``days`` (None: no expiration) in the expiration menu of the token form (a select on older pages):
        the menu button found by its place (its label is "Expiration" or the current choice), the item by its value;
        the hidden field the form submits is then checked, and set when the menu did not set it."""
        from playwright.sync_api import Error

        page = self.page
        value = "none" if days is None else str(days)
        select = page.locator("select#token_expiration")
        if select.count():
            select.first.select_option(value)
            return
        field = page.locator(EXPIRATION_FIELD)
        try:
            menu = page.locator(EXPIRATION_MENU)
            if not menu.count():
                menu = page.get_by_role("button", name=re.compile(r"expiration|\d+ days", re.IGNORECASE))
            menu.first.click(timeout=MENU_TIMEOUT_MS)
            item = page.locator(f'[role="menuitemradio"][data-value="{value}"]')
            if not item.count():
                item = page.get_by_role("menuitemradio", name="No expiration" if days is None else f"{days} days")
            item.first.click(timeout=MENU_TIMEOUT_MS)
        except Error:
            if not field.count():
                raise
        if field.count() and field.first.input_value() != value:
            field.first.evaluate("(input, value) => { input.value = value; }", value)

    def open(self, url: str) -> None:
        """Show the page ``url``."""
        with self.step(f"page {url}"):
            self.page.goto(url)

    # --- the web steps of setup and bootstrap -------------------------------------------------------------------
    def join_org(self, org: str, login: str, *, public: bool) -> None:
        """Accept the pending invitation of ``org`` (its page shows a Join button; an accepted one shows none: the
        page is loaded again after the click, a Join button left is an error), then, with ``public``, switch the
        membership of ``login`` from Private to Public on the People page; done only once GitHub's public API lists
        ``login`` as a public member (AccountError otherwise: nothing is taken for done on a page's say-so)."""
        from playwright.sync_api import Error

        page = self.page
        with self.step("invitation"):
            page.goto(INVITATION_URL.format(org=org))
            join = self.join_button()
            if join is not None:
                join.click()
                page.wait_for_load_state()
                page.goto(INVITATION_URL.format(org=org))
                if self.join_button() is not None:
                    raise AccountError(
                        f"invitation: {org} still shows its Join button after the click (page {page.url})"
                    )
        if not public:
            return
        with self.step("public membership"):
            if self.public_member(org, login):
                return
            page.goto(PEOPLE_URL.format(org=org, login=login))
            private = page.locator("summary, button, [role=button], a").filter(has_text=PRIVATE_RE, visible=True)
            try:  # the page renders its members after it loaded: wait for the switch
                private.first.wait_for(state="visible", timeout=DEFAULT_TIMEOUT_MS)
            except Error:
                raise AccountError(
                    f"public membership: no Private switch for {login} on the People page within "
                    f"{DEFAULT_TIMEOUT_MS // 1000} s (is {login} a member of {org} yet?) (page {page.url})"
                ) from None
            private.first.click()
            choices = page.locator("[role=menuitemradio], [role=menuitem], button, [role=button]")
            choices.filter(has_text=PUBLIC_RE, visible=True).first.click()
            page.wait_for_load_state()
            for _ in range(PUBLIC_CHECKS):
                if self.public_member(org, login):
                    return
                page.wait_for_timeout(2000)
        raise AccountError(
            f"public membership: GitHub does not list {login} as a public member of {org} after the switch "
            f"(page {page.url})"
        )

    def join_button(self) -> Any:
        """The Join button of an invitation page (by its name, else the submit button of the invitation form), None
        without one."""
        page = self.page
        for locator in (
            page.get_by_role("button", name=JOIN_RE),
            page.locator('form[action*="/invitation"] [type="submit"]'),
        ):
            if self.visible(locator):
                return locator.first
        return None

    def public_member(self, org: str, login: str) -> bool:
        """Whether GitHub's public API lists ``login`` as a public member of ``org`` (204; 404 otherwise); AccountError
        when its anonymous rate limit is spent (nothing is taken for done unchecked)."""
        status = self.page.request.get(PUBLIC_MEMBER_API.format(org=org, login=login)).status
        if status in (403, 429):
            raise AccountError(
                f"public membership: GitHub's API refuses anonymous reads for now (HTTP {status}, rate limit): check "
                f"{PEOPLE_URL.format(org=org, login=login)}"
            )
        return status == 204

    def install_app(self, url: str) -> None:
        """Install the App from its installation page (the organization preselected by ``url``) on all repositories,
        answering a sudo confirmation."""
        page = self.page
        with self.step("App installation"):
            page.goto(url)
            self.sudo()
            everything = page.get_by_label(re.compile(r"^\s*all repositories", re.IGNORECASE))
            if self.visible(everything):
                everything.first.check()
            page.get_by_role("button", name=re.compile(r"^\s*install", re.IGNORECASE)).first.click()
            page.wait_for_load_state()
            self.sudo()

    def confirm_app(self, url: str) -> None:
        """Open setup's manifest form (served on the loopback ``url``, it posts itself to GitHub), create the App and
        follow GitHub's redirect back to the loopback callback."""
        page = self.page
        with self.step("App creation"):
            page.goto(url)
            page.wait_for_url(re.compile(r"^https://github\.com/"))
            self.sudo()
            page.get_by_role("button", name=re.compile(r"^\s*create github app", re.IGNORECASE)).first.click()
            page.wait_for_url(LOOPBACK_CALLBACK_RE, timeout=HUMAN_TIMEOUT * 1000)

    def sign_out(self) -> None:
        """Best effort: end the session server-side (the context is closed anyway)."""
        page = self.page
        with contextlib.suppress(Exception):
            page.goto(LOGOUT_URL)
            page.get_by_role("button", name=re.compile(r"^sign out", re.IGNORECASE)).first.click(timeout=5000)


class PlaywrightBrowser:
    """A visible Firefox (``with`` block); ``session()`` gives each account a fresh context. ``pause(message)`` is
    called before a failed session closes, so the operator can look at the page."""

    def __init__(
        self, *, pause: Callable[[str], None], browsers_path: Path | None = None, headless: bool = False
    ) -> None:
        """Bind (``browsers_path``: PLAYWRIGHT_BROWSERS_PATH when it is not set, else Playwright's); nothing starts
        before ``__enter__``."""
        self.browsers_path = browsers_path
        self.pause = pause
        self.headless = headless
        self._playwright: Any = None
        self._browser: Any = None

    def __enter__(self) -> Self:
        """Start Playwright and Firefox (AccountError with the install hint when either is missing)."""
        where = os.environ.get("PLAYWRIGHT_BROWSERS_PATH") or (self.browsers_path and str(self.browsers_path))
        hint = INSTALL_HINT.format(env=f"PLAYWRIGHT_BROWSERS_PATH={where} " if where else "")
        try:
            from playwright.sync_api import Error, sync_playwright
        except ImportError:
            raise AccountError(f"Playwright is not installed: {hint}") from None
        if self.browsers_path is not None:
            os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(self.browsers_path))
        self._playwright = sync_playwright().start()
        try:
            self._browser = self._playwright.firefox.launch(headless=self.headless, env=self.launch_env())
        except Error as exc:
            self._playwright.stop()
            if MISSING_FIREFOX_RE.search(str(exc)):
                raise AccountError(f"Firefox is not installed ({_message(exc)}): {hint}") from None
            raise AccountError(f"Firefox does not start: {_launch_error(exc)}") from None
        return self

    @staticmethod
    def launch_env() -> dict[str, str] | None:
        """Firefox's environment: this one, with the schema directory of gsettings_compat_dir first in
        GSETTINGS_SCHEMA_DIR when the system needs it (None: this environment as it is)."""
        if not sys.platform.startswith("linux"):
            return None
        cache = Path(os.environ.get("E2E_CACHE_DIR") or DEFAULT_CACHE_DIR).expanduser()
        compat = gsettings_compat_dir(cache / "gsettings-schemas")
        if compat is None:
            return None
        current = os.environ.get("GSETTINGS_SCHEMA_DIR")
        return {**os.environ, "GSETTINGS_SCHEMA_DIR": f"{compat}:{current}" if current else str(compat)}

    def __exit__(self, *exc_info: object) -> None:
        """Close Firefox and stop Playwright."""
        with contextlib.suppress(Exception):
            self._browser.close()
        with contextlib.suppress(Exception):
            self._playwright.stop()

    @contextlib.contextmanager
    def session(self) -> Iterator[PlaywrightSession]:
        """A fresh context and page; on AccountError the window stays open until the operator continues."""
        context = self._browser.new_context(accept_downloads=True)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)
        session = PlaywrightSession(page)
        try:
            yield session
        except AccountError as exc:
            self.pause(f"{exc}: the window stays open to look at the page or finish by hand; press Enter to close it")
            raise
        finally:
            session.sign_out()
            with contextlib.suppress(Exception):
                context.close()
