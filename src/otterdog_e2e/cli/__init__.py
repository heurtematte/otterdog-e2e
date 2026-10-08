"""``otterdog-e2e`` command line (SPEC 16): doctor, bootstrap, sut, run, pr, relay, janitor, report, targets,
scrub-artifacts, cache prune, app-manifest, inject, setup, ci-sync and assist. Exit codes: pytest's for run/pr (the most
severe child code with several targets); budget overruns never fail.

Every command builds an E2EContext (the composition root shared with the pytest plugin); collaborators are imported
lazily so that ``--help`` stays fast. Errors are reported as redacted one-line messages (exit 1). ``run`` and ``pr``
call ``pytest.main`` in-process: the plugin's safety model (verify_target, lease, gating, redaction) applies unchanged.

The click group ``main`` and the helpers every command shares live in common.py; each command family has its module:
doctor, bootstrap, sut, run (run and pr), ops (relay and janitor), maintenance (report, targets, scrub-artifacts and
cache prune), app_manifest, inject, onboarding (setup and ci-sync) and assist. Importing this package imports them, so
every command is registered on ``main`` (the ``otterdog-e2e`` console script and ``python -m otterdog_e2e``).
"""

from __future__ import annotations

from otterdog_e2e.cli import (  # noqa: F401 - imported to register their commands on main
    app_manifest,
    assist,
    bootstrap,
    doctor,
    inject,
    maintenance,
    onboarding,
    ops,
    run,
    sut,
)
from otterdog_e2e.cli.common import main

__all__ = ["main"]
