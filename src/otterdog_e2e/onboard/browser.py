"""The browser side of onboard.accounts: github.com in a visible Firefox driven by Playwright, one isolated context per
machine account (its cookies are dropped, and the account signed out, when the account is done).

The selectors follow eclipse-cbi/ci-admin (github/playwright) where they are stable (the sign-in form, the setup key
dialog and the recovery codes of the 2FA enrollment, the expiration menu of the classic token form) and rely on URLs
and links elsewhere. GitHub changes its pages without notice: a step that does not find what it expects raises
AccountError naming the step, and the window stays open (``pause``) for the operator to see the page and finish by
hand, instead of guessing. Nothing is screenshotted or saved: these pages show secrets. The recovery codes download
that unlocks the acknowledgement stays in Playwright's temporary directory, deleted with the context.

Playwright is an optional dependency (``poetry install -E browser``, which ``make init`` installs with Firefox); its
Firefox is Playwright's own, in PLAYWRIGHT_BROWSERS_PATH or else its global cache (``~/.cache/ms-playwright`` on
Linux, shared with otterdog's ``make init``): ``.venv/bin/python -m playwright install firefox``. The web-UI tier keeps
the browsers of each SUT apart (sut.cli_install.playwright_browsers_path).
"""

from __future__ import annotations

import contextlib
import os
import re
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Self

from otterdog_e2e.onboard.accounts import TOTP_PERIOD, AccountError
from otterdog_e2e.redact import REDACTOR

LOGIN_URL = "https://github.com/login"
LOGOUT_URL = "https://github.com/logout"
SECURITY_URL = "https://github.com/settings/security"
TWO_FACTOR_SETUP_URL = "https://github.com/settings/two_factor_authentication/setup/intro"
TOKENS_URL = "https://github.com/settings/tokens"
CLASSIC_TOKEN_RE = re.compile(r"\bghp_[A-Za-z0-9]{36}\b")
DEFAULT_TIMEOUT_MS = 15_000
HUMAN_TIMEOUT = 300.0  # seconds for what the operator does in the window (device code, captcha)
INSTALL_HINT = (
    "install the browser extra and Firefox: make init (or poetry install -E browser, then "
    "{env}.venv/bin/python -m playwright install firefox)"
)


def _message(exc: BaseException) -> str:
    """First line of a Playwright error, redacted."""
    text = str(exc).strip().splitlines()
    return REDACTOR(text[0] if text else type(exc).__name__)


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

    def enroll_two_factor(
        self,
        *,
        keep_seed: Callable[[str], None],
        code: Callable[[str], str],
        keep_recovery_codes: Callable[[list[str]], None],
    ) -> None:
        """Authenticator app enrollment: setup key (kept first), its code, recovery codes (kept first), done."""
        page = self.page
        with self.step("2FA setup key"):
            page.goto(TWO_FACTOR_SETUP_URL)
            page.get_by_role("button", name=re.compile(r"setup key", re.IGNORECASE)).first.click()
            secret = page.locator('[data-target="two-factor-setup-verification.mashedSecret"]')
            secret.first.wait_for()
            raw = " ".join(text.strip() for text in secret.all_inner_texts())
        REDACTOR.add(raw)
        keep_seed(raw)
        with self.step("2FA code"):
            page.keyboard.press("Escape")
            field = page.get_by_role("textbox", name=re.compile(r"verify the code", re.IGNORECASE))
            value = code(raw)
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
    def classic_token(self, *, note: str, url: str, days: int) -> str:
        """Regenerate the classic token ``note`` when it exists (its value cannot be read again), else generate it
        from the prefilled ``url`` (note and scopes); the expiration ``days``; the value GitHub shows once."""
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
                page.get_by_role("button", name=re.compile(r"^generate token$", re.IGNORECASE)).first.click()
        with self.step("new token"):
            page.wait_for_load_state()
            if self.visible(page.get_by_text(re.compile(r"has already been taken", re.IGNORECASE))):
                raise AccountError(
                    f"a classic token noted {note!r} exists but is not in the token list: delete it, then run again"
                )
            shown = page.locator("#new-oauth-token")
            text = shown.first.inner_text() if shown.count() else page.content()
            match = CLASSIC_TOKEN_RE.search(text)
        if match is None:
            raise AccountError("new token: GitHub showed no classic token (ghp_...)")
        REDACTOR.add(match.group(0))
        return match.group(0)

    def expiration(self, days: int) -> None:
        """Pick ``days`` in the expiration menu of the token form (a select on older pages)."""
        page = self.page
        select = page.locator("select#token_expiration")
        if select.count():
            select.first.select_option(str(days))
            return
        page.get_by_role("button", name=re.compile(r"^(\d+ days|custom.*|no expiration)$", re.IGNORECASE)).first.click()
        page.get_by_role("menuitemradio", name=f"{days} days", exact=True).first.click()

    def open(self, url: str) -> None:
        """Show the page ``url``."""
        with self.step(f"page {url}"):
            self.page.goto(url)

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
            self._browser = self._playwright.firefox.launch(headless=self.headless)
        except Error as exc:
            self._playwright.stop()
            raise AccountError(f"Firefox does not start ({_message(exc)}): {hint}") from None
        return self

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
