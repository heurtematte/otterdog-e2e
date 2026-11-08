"""``otterdog-acceptance completion SHELL``: the shell completion script of both command names.

click completes a command when the environment variable ``_<NAME>_COMPLETE`` is set (``_ODA_COMPLETE`` for ``oda``,
``_OTTERDOG_ACCEPTANCE_COMPLETE`` for ``otterdog-acceptance``); this command prints click's script for each console
script of pyproject.toml, so one line of the shell's startup file completes both: ``eval "$(oda completion zsh)"``
(~/.zshrc, after compinit), ``eval "$(oda completion bash)"`` (~/.bashrc) or ``oda completion fish | source``
(~/.config/fish/config.fish). Each completion runs the command, which imports its collaborators lazily.
"""

from __future__ import annotations

from collections.abc import Sequence

import click

from otterdog_acceptance.cli.common import main

COMMAND_NAMES = ("otterdog-acceptance", "oda")  # the console scripts of pyproject.toml
SHELLS = ("bash", "zsh", "fish")


def completion_var(name: str) -> str:
    """The environment variable click reads to complete the command ``name`` (as click.Command.main derives it)."""
    return f"_{name}_COMPLETE".replace("-", "_").upper()


def completion_script(shell: str, names: Sequence[str] = COMMAND_NAMES) -> str:
    """click's completion script of ``shell`` for each command name."""
    from click.shell_completion import get_completion_class

    completer = get_completion_class(shell)
    if completer is None:
        raise click.UsageError(f"no completion for the shell {shell!r} (expected {', '.join(SHELLS)})")
    return "\n".join(completer(main, {}, name, completion_var(name)).source() for name in names)


@main.command("completion")
@click.argument("shell", type=click.Choice(SHELLS))
def completion(shell: str) -> None:
    """Print the completion script of otterdog-acceptance and oda for SHELL.

    Add to the shell's startup file: eval "$(oda completion zsh)" (~/.zshrc, after compinit), eval "$(oda completion
    bash)" (~/.bashrc) or oda completion fish | source (~/.config/fish/config.fish).
    """
    click.echo(completion_script(shell))
