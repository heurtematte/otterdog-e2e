# Security policy

## Reporting a vulnerability of Otterdog Acceptance

Please report a vulnerability of the harness privately, through
[GitHub private vulnerability reporting](https://github.com/heurtematte/otterdog-e2e/security/advisories/new).
**Do not report it in a public issue, discussion or pull request.**

Only the `main` branch is maintained: fixes land there.

Please include what you can of:

- the kind of issue, e.g. a secret written to an artifact or a log, untrusted pull request code reaching the host or
  a credential, a write to an organization that is not a test organization;
- the commit of Otterdog Acceptance and the command, scenario or workflow involved;
- the steps to reproduce it and its impact;
- the files and lines of the source concerned.

Never attach a real token, private key or webhook secret to a report, even an expired one: describe where it appeared.

## A vulnerability of otterdog found with the harness

A run can reveal a vulnerability of otterdog itself. Report it to the otterdog project as its
[security policy](https://github.com/eclipse-csi/otterdog/security/policy) asks (the Eclipse Foundation Vulnerability
Reporting Policy), not here. Until it is disclosed, keep it out of everything this repository publishes: scenarios,
`scenarios/known_bugs.yaml`, `docs/known-issues.md`, run reports and pull request comments.

## A leaked secret

If a run, an artifact or a CI log exposed a token, a private key or a webhook secret, revoke or rotate it first (GitHub
settings of the account or the App, the secret store it comes from), then report how it leaked.

## Security model

How the harness protects the credentials of the test organizations and isolates untrusted otterdog code is described
in [docs/security.md](docs/security.md).
