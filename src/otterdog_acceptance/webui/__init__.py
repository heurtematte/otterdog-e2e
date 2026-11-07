"""Web-UI tier of the harness (docs/web-ui-testing.md): features otterdog only reaches through the GitHub web UI.

otterdog drives github.com with Playwright (Firefox) for 12 organization settings (schema provider ``web``) and a few
commands (install-app, uninstall-app, review-permissions, list-advisories -w, web-login), logging in as a bot owner
with username, password and TOTP. The tier:

* runs otterdog itself WITHOUT ``-n`` (``otterdog.runner.WebOtterdogCli``), only for trusted SUTs on the host, never
  with SAML SSO, only with ``--e2e-allow-web-ui`` (``capabilities.Cap.WEB_UI``, the ``web_ui`` marker);
* checks the results with independent oracles: REST ``GET /orgs/{org}`` for the 7 readable settings
  (``mapping``) and a TRUSTED otterdog release (the reset SUT) reading the 5 others through its own web reader
  (``oracle.TrustedWebReader``);
* serializes every web login of the machine and spaces them by a full TOTP window (``gate.LoginGate``), because
  otterdog only avoids reusing a TOTP code inside one process;
* groups every settings change of a run into one scenario (``roundtrip.WebSettingsRoundTrip``) to keep the number of
  logins (and the lockout risk) low.
"""

from __future__ import annotations
