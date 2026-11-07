# Contributing to otterdog-acceptance

Contributions are welcome: new scenarios, fixes of the harness, documentation. By contributing, you agree that your
contribution is licensed under the [Eclipse Public License 2.0](LICENSE), the license of the project.

## Set up

```bash
make init        # .venv with the harness and its dev tools, otterdog-acceptance and oda in ~/.local/bin
make check       # ruff, mypy and the unit tier: no network, no docker
make offline     # the offline tier against an otterdog release (docker, no GitHub)
```

[Local development](docs/local-development.md) covers the rest: the Makefile, artifacts, the harness cache, the
documentation site (`make docs`).

The live tiers write to real GitHub organizations: only run them on dedicated test organizations and machine accounts
([onboarding](docs/onboarding.md)).

## Writing tests

- [Writing scenarios](docs/writing-scenarios.md): YAML scenarios, their ids, tags, steps and expectations.
- [Writing the test battery](docs/battery-guide.md): the Python tests of each tier.
- [Testing an otterdog pull request](docs/testing-an-otterdog-pr.md): references, expected deltas, the differential.
- [AI-assisted test writing](docs/ai-assistance.md): the skills of `.claude/skills/`.

A scenario follows a functionality of otterdog, never a pull request: no PR number in an id, a file or a directory;
the pull requests that change a behaviour go into the `references` of its scenarios. When a test covers a feature of
the [coverage matrix](docs/coverage-matrix.md), update `scenarios/coverage.yaml` and regenerate the matrix.

## Before opening a pull request

- `make check` passes, and `make offline` for a change of the offline tier or the scenarios;
- `.venv/bin/otterdog-acceptance assist check <files>` reports no problem for the scenarios and tests you wrote;
- `make docs` builds the documentation site without warning when you changed `docs/`, `README.md` or `zensical.toml`;
- no secret anywhere: not in scenarios, fixtures, artifacts you attach or pull request text (dummy values only; see
  [security](docs/security.md));
- commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, ...).

## Reporting issues

Open a GitHub issue for a bug of the harness or a missing test. A security issue goes through
[SECURITY.md](SECURITY.md), never a public issue.
