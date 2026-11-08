"""``otterdog-acceptance completion SHELL``: click's completion script of both command names, and the completions it
answers."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from click.testing import CliRunner

from otterdog_acceptance.cli import main
from otterdog_acceptance.cli.completion import COMMAND_NAMES, completion_script, completion_var

PROJECT = Path(__file__).resolve().parents[2]


def test_the_command_names_are_the_console_scripts() -> None:
    """Both console scripts of pyproject.toml get a script, under the variable click derives from their name."""
    scripts = tomllib.loads((PROJECT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    assert set(COMMAND_NAMES) == set(scripts)
    assert completion_var("oda") == "_ODA_COMPLETE"
    assert completion_var("otterdog-acceptance") == "_OTTERDOG_ACCEPTANCE_COMPLETE"


@pytest.mark.parametrize(
    ("shell", "registration"),
    [
        ("zsh", "compdef _{function}_completion {name}"),
        ("bash", "complete -o nosort -F _{function}_completion {name}"),
        ("fish", "complete --no-files --command {name}"),
    ],
)
def test_the_script_registers_both_names(shell: str, registration: str) -> None:
    """One script per shell completes otterdog-acceptance and oda."""
    result = CliRunner().invoke(main, ["completion", shell])
    assert result.exit_code == 0, result.output
    assert result.output.strip() == completion_script(shell).strip()
    for name in COMMAND_NAMES:
        assert registration.format(function=name.replace("-", "_"), name=name) in result.output
        assert f"{completion_var(name)}={shell}_complete" in result.output


def test_an_unknown_shell_is_refused() -> None:
    """Only the shells click completes."""
    result = CliRunner().invoke(main, ["completion", "tcsh"])
    assert result.exit_code == 2 and "'tcsh' is not one of 'bash', 'zsh', 'fish'" in result.output


@pytest.mark.parametrize(
    ("name", "words", "word", "expected"),
    [
        ("oda", "oda ru", 1, {"run"}),
        ("otterdog-acceptance", "otterdog-acceptance assist c", 2, {"check", "coverage"}),
        ("oda", "oda run --su", 2, {"--sut", "--suite"}),
    ],
)
def test_the_completions_of_both_names(name: str, words: str, word: int, expected: set[str]) -> None:
    """What the shell gets back when it runs the command with click's variable set (bash protocol: type,value)."""
    env = {completion_var(name): "bash_complete", "COMP_WORDS": words, "COMP_CWORD": str(word)}
    result = CliRunner().invoke(main, [], prog_name=name, env=env)
    assert result.exit_code == 0, result.output
    assert {line.split(",", 1)[1] for line in result.output.splitlines()} == expected
