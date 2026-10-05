"""``python -m otterdog_e2e``: the otterdog-e2e command line (batch runs start one such child process per target)."""

from __future__ import annotations

from otterdog_e2e.cli import main

if __name__ == "__main__":
    main(prog_name="otterdog-e2e")
