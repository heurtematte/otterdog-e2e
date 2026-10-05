"""Onboarding of a test organization instance (docs/onboarding.md): ``otterdog-e2e setup`` and ``otterdog-e2e ci-sync``.

An instance is one dedicated test org: its env file ``~/.config/otterdog-e2e/<instance>.env`` (0600) holds the org,
its pinned id, the logins and tokens of the machine accounts, the GitHub App credentials and ``E2E_PROFILE`` (the
``targets/<profile>.yaml`` it uses). In CI it is the environments ``e2e-<instance>``, ``e2e-<instance>-untrusted`` and
``e2e-<instance>-webui``.

* ``envfile``  - the only writer of env files (atomic, 0600, comments kept, values that ``settings.parse_env_text``
  reads back exactly) and the instance names;
* ``tokens``   - per role the token requirements (classic scopes, fine-grained permissions: the single source of the
  tables of docs/setup-free-org.md) and the PREFILLED token creation URLs;
* ``wizard``   - ``SetupWizard``: the interactive flow of ``setup`` (every I/O injected), refused in CI;
* ``cisync``   - ``CiSync``: the GitHub environments, variables and secrets of an instance, set through the operator's
  own ``gh`` CLI (secrets on stdin only), dry run by default.

What GitHub does not let a program do (accounts, 2FA, token creation, org creation, App registration and installation
clicks, invitations, approvals) stays manual: the wizard prints prefilled URLs and polls for the result.
"""
