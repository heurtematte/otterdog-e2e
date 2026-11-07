"""``python -m otterdog_acceptance``: the otterdog-acceptance command line (batch runs start one such child process per target)."""

from __future__ import annotations

from otterdog_acceptance.cli import main

if __name__ == "__main__":
    main(prog_name="otterdog-acceptance")
