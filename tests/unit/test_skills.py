"""The agent skills of .claude/skills (docs/ai-assistance.md): portable format, and only commands that exist.

Every ``.claude/skills/<name>/SKILL.md`` follows the open Agent Skills format with its standard fields only, so any
agent supporting skills can load it: ``name`` equal to the directory (lower case letters, digits and single hyphens,
at most 64 characters), ``description`` saying what the skill does and when to use it (at most 1024 characters, no
XML tags), optional ``license``, ``compatibility`` (at most 500 characters), ``metadata`` and ``allowed-tools``. The
body stays short (details in ``references/*.md``, one level deep) and has a Safety section.

What the skills tell an agent to run or read must exist, so they cannot drift from the harness:

* every ``otterdog-e2e <command> [<subcommand>]`` written in a code span or a fenced block, and its ``--long``
  options, exist in the click CLI (``otterdog_e2e.cli.main``);
* every ``make <target>`` exists in the Makefile;
* every repository path (``docs/``, ``scenarios/``, ``src/``, ``tests/``) of a code span or a shell block exists;
  placeholders (``<n>``), globs and variables are skipped;
* every relative link and every ``references/`` file a skill names exists.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import click
import pytest
import yaml

from otterdog_e2e.cli import main

ROOT = Path(__file__).resolve().parents[2]
SKILLS = ROOT / ".claude" / "skills"
MAKEFILE = ROOT / "Makefile"
EXPECTED_SKILLS = ("fill-coverage-gap", "otterdog-pr-tests", "triage-e2e-run", "write-e2e-scenario")
# the assist subcommand each skill is built around (the parser must find it: a regression guard of the parser too)
SKILL_COMMANDS = {
    "fill-coverage-gap": ("assist", "coverage"),
    "otterdog-pr-tests": ("assist", "pr-context"),
    "triage-e2e-run": ("assist", "triage"),
    "write-e2e-scenario": ("assist", "check"),
}

# --- the Agent Skills format (agentskills.io specification) ------------------------------------------------------------
ALLOWED_KEYS = frozenset({"name", "description", "license", "compatibility", "metadata", "allowed-tools"})
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
RESERVED_NAME_WORDS = ("anthropic", "claude")
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
MAX_BODY_LINES = 300  # the body stays below this; details go to references/*.md
FRONTMATTER_RE = re.compile(r"\A---\n(?P<yaml>.*?)\n---\n(?P<body>.*)\Z", re.DOTALL)
XML_TAG_RE = re.compile(r"</?[A-Za-z][^<>]*>")

# --- markdown --------------------------------------------------------------------------------------------------------
FENCE_RE = re.compile(r"^[ \t>]*(?P<marker>`{3,}|~{3,})(?P<info>[^`]*)$")
CODE_SPAN_RE = re.compile(r"(?<!`)(?P<ticks>`+)(?!`)(?P<code>.+?)(?<!`)(?P=ticks)(?!`)")
LINK_RE = re.compile(r"(?<!!)\[[^\]\n]*\]\((?P<dest>[^)\s]+)(?:\s+\"[^\"]*\")?\)")
SHELL_INFOS = frozenset({"bash", "sh", "shell", "console", "zsh"})
REFERENCE_RE = re.compile(r"(?<![\w./-])references/[A-Za-z0-9_.-]+\.md")

# --- commands --------------------------------------------------------------------------------------------------------
INVOCATION_RE = re.compile(r"(?:^|(?<=[\s/`(]))otterdog-e2e[ \t]+(?P<args>[^\n]*)")
MAKE_RE = re.compile(r"(?:^|(?<=[\s`(]))make[ \t]+(?P<args>[^\n]*)")
SEPARATOR_RE = re.compile(r"&&|\|\||[;|]")
LONG_OPTION_RE = re.compile(r"^--[a-z][a-z0-9-]*")
MAKE_TARGET_RE = re.compile(r"^(?P<target>[a-z][a-z0-9-]*)[ \t]*:(?!=)", re.MULTILINE)
ASSIGNMENT_RE = re.compile(r"^[A-Z_][A-Z0-9_]*=")
# repository paths checked for existence; placeholders, globs and variables are skipped
PATH_RE = re.compile(r"(?<![\w./-])(?:docs|scenarios|src|tests)/[^\s`'\"(),;]*")
PLACEHOLDER_CHARS = frozenset("<>*{}$[]?|")


@dataclass(frozen=True)
class Invocation:
    """One ``otterdog-e2e`` command line found in a skill file."""

    file: str
    words: tuple[str, ...]

    @property
    def label(self) -> str:
        """``<file>: otterdog-e2e <words>``."""
        return f"{self.file}: otterdog-e2e {' '.join(self.words)}"


# --- files -------------------------------------------------------------------------------------------------------------
def skill_dirs() -> list[Path]:
    """The skill directories (every directory of .claude/skills)."""
    return sorted(path for path in SKILLS.iterdir() if path.is_dir()) if SKILLS.is_dir() else []


def skill_files() -> list[Path]:
    """Every markdown file of every skill (SKILL.md and references/*.md)."""
    return sorted(path for directory in skill_dirs() for path in directory.rglob("*.md"))


def relative(path: Path) -> str:
    """Repository-relative path of a file (the path itself outside the repository)."""
    return str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)


@cache
def split_skill(path: Path) -> tuple[dict[str, Any], str]:
    """(frontmatter mapping, body) of a SKILL.md; AssertionError when the frontmatter is missing or not a mapping."""
    match = FRONTMATTER_RE.match(path.read_text(encoding="utf-8"))
    assert match is not None, f"{relative(path)}: no YAML frontmatter between '---' lines at the top"
    data = yaml.safe_load(match["yaml"])
    assert isinstance(data, dict), f"{relative(path)}: the frontmatter must be a mapping"
    return data, match["body"]


def split_markdown(text: str) -> tuple[list[str], list[tuple[str, str]]]:
    """(paragraphs outside fenced blocks, (info string, content) of every fenced block); a fence closes with the
    same character, at least as long."""
    paragraphs: list[str] = []
    blocks: list[tuple[str, str]] = []
    current: list[str] = []
    fence: tuple[str, str] | None = None
    fenced: list[str] = []
    for line in text.split("\n"):
        match = FENCE_RE.match(line)
        if fence is None:
            if match:
                fence, fenced = (match["marker"], match["info"].strip().split(" ")[0].lower()), []
                paragraphs.append("\n".join(current))
                current = []
            elif line.strip():
                current.append(line)
            else:
                paragraphs.append("\n".join(current))
                current = []
        elif match and not match["info"].strip() and match["marker"][0] == fence[0][0]:
            if len(match["marker"]) >= len(fence[0]):
                blocks.append((fence[1], "\n".join(fenced)))
                fence = None
            else:
                fenced.append(line)
        else:
            fenced.append(line)
    paragraphs.append("\n".join(current))
    return [paragraph for paragraph in paragraphs if paragraph], blocks


def code_spans(paragraph: str) -> list[str]:
    """The code spans of a paragraph (line breaks inside a span read as spaces)."""
    return [match["code"].strip() for match in CODE_SPAN_RE.finditer(paragraph.replace("\n", " "))]


def command_lines(text: str) -> Iterator[str]:
    """Command lines of a skill file: every code span, and every line of every fenced block (backslash continuations
    joined, ``#`` comments dropped), split at ``&&``, ``||``, ``;`` and ``|``."""
    paragraphs, blocks = split_markdown(text)
    lines = [span for paragraph in paragraphs for span in code_spans(paragraph)]
    for _, content in blocks:
        lines += content.replace("\\\n", " ").split("\n")
    for line in lines:
        line = re.sub(r"(^|\s)#.*$", "", line)
        yield from (part.strip() for part in SEPARATOR_RE.split(line) if part.strip())


def invocations(path: Path) -> list[Invocation]:
    """Every ``otterdog-e2e`` invocation of a skill file, as its words after the program name."""
    found = []
    for line in command_lines(path.read_text(encoding="utf-8")):
        for match in INVOCATION_RE.finditer(line):
            words = tuple(word.strip("[]()") for word in match["args"].split())
            if words and words[0] and not words[0].startswith(("<", "$")):
                found.append(Invocation(relative(path), words))
    return found


def make_targets_used(path: Path) -> set[str]:
    """The targets of every ``make`` command of a skill file (the first word that is no assignment nor option)."""
    targets = set()
    for line in command_lines(path.read_text(encoding="utf-8")):
        for match in MAKE_RE.finditer(line):
            words = [word for word in match["args"].split() if not ASSIGNMENT_RE.match(word)]
            if words and not words[0].startswith(("-", "<", "$")):
                targets.add(words[0])
    return targets


def repository_paths(path: Path) -> set[str]:
    """Repository paths named in code spans and shell blocks (``::node``, ``:line`` and ``#anchor`` suffixes
    dropped; placeholders, globs and variables skipped)."""
    paragraphs, blocks = split_markdown(path.read_text(encoding="utf-8"))
    texts = [span for paragraph in paragraphs for span in code_spans(paragraph)]
    texts += [content for info, content in blocks if info in SHELL_INFOS]
    found = set()
    for text in texts:
        for match in PATH_RE.finditer(text):
            candidate = re.split(r"::|#|:(?=\d)", match.group())[0].rstrip(".:")
            if candidate and not PLACEHOLDER_CHARS & set(candidate):
                found.add(candidate)
    return found


def links(path: Path) -> list[str]:
    """Relative link destinations of a skill file (outside fenced blocks; anchors dropped)."""
    paragraphs, _ = split_markdown(path.read_text(encoding="utf-8"))
    found = []
    for paragraph in paragraphs:
        for match in LINK_RE.finditer(paragraph):
            dest = match["dest"]
            if re.match(r"^[a-z][a-z0-9+.-]*:", dest) or dest.startswith("#"):
                continue
            found.append(dest.split("#")[0])
    return found


# --- the CLI and the Makefile -------------------------------------------------------------------------------------------
def option_names(command: click.Command) -> set[str]:
    """Long option names of a click command (``--help`` included)."""
    names = {"--help"}
    for param in command.params:
        if isinstance(param, click.Option):
            names |= {name for name in (*param.opts, *param.secondary_opts) if name.startswith("--")}
    return names


def invocation_problems(invocation: Invocation) -> list[str]:
    """Why an invocation does not match the click CLI (unknown command, subcommand or long option)."""
    words = list(invocation.words)
    command: click.Command = main
    context = click.Context(main)
    path = []
    while isinstance(command, click.Group) and words and not words[0].startswith("-"):
        name = words.pop(0)
        if name.startswith("<"):
            return []
        sub = command.get_command(context, name)
        if sub is None:
            return [f"{invocation.label}: unknown command {' '.join([*path, name])!r}"]
        command, path = sub, [*path, name]
    if isinstance(command, click.Group) and path and "--help" not in words:
        return [f"{invocation.label}: {' '.join(path)!r} needs a subcommand"]
    known = option_names(command)
    problems = []
    for word in words:
        if word == "--":
            break
        match = LONG_OPTION_RE.match(word)
        if match and match.group() not in known:
            problems.append(f"{invocation.label}: {' '.join(path) or 'otterdog-e2e'} has no option {match.group()}")
    return problems


@cache
def makefile_targets() -> frozenset[str]:
    """The targets defined in the Makefile."""
    return frozenset(MAKE_TARGET_RE.findall(MAKEFILE.read_text(encoding="utf-8")))


# --- the skills -------------------------------------------------------------------------------------------------------
def test_the_skills_exist() -> None:
    """The four skills of docs/ai-assistance.md exist, each with its SKILL.md."""
    assert tuple(path.name for path in skill_dirs()) == EXPECTED_SKILLS
    for directory in skill_dirs():
        assert (directory / "SKILL.md").is_file(), f"{relative(directory)} has no SKILL.md"


@pytest.mark.parametrize("name", EXPECTED_SKILLS)
def test_frontmatter_uses_the_standard_fields(name: str) -> None:
    """Only the Agent Skills fields; name equals the directory and is lower case with single hyphens; description
    (what and when) and compatibility within their limits, without XML tags; metadata maps strings to strings."""
    data, _ = split_skill(SKILLS / name / "SKILL.md")
    assert set(data) <= ALLOWED_KEYS, f"non-standard keys {sorted(set(data) - ALLOWED_KEYS)}"
    assert data.get("name") == name, "name must equal the directory name"
    assert len(name) <= MAX_NAME and NAME_RE.match(name), name
    assert not any(word in name for word in RESERVED_NAME_WORDS), name
    description = data.get("description")
    assert isinstance(description, str) and description.strip(), "description is required"
    assert len(description) <= MAX_DESCRIPTION, f"description has {len(description)} characters"
    assert not XML_TAG_RE.search(description), "no XML tags in the description"
    assert "Use when" in description, "the description says when to use the skill (it drives automatic invocation)"
    if "compatibility" in data:
        compatibility = data["compatibility"]
        assert isinstance(compatibility, str) and 0 < len(compatibility) <= MAX_COMPATIBILITY
    if "license" in data:
        assert isinstance(data["license"], str) and data["license"].strip()
    if "metadata" in data:
        metadata = data["metadata"]
        assert isinstance(metadata, dict)
        assert all(isinstance(key, str) and isinstance(value, str) for key, value in metadata.items())
    if "allowed-tools" in data:
        assert isinstance(data["allowed-tools"], str) and data["allowed-tools"].strip()


@pytest.mark.parametrize("name", EXPECTED_SKILLS)
def test_body_is_short_and_has_its_sections(name: str) -> None:
    """The body stays below the line limit and has the sections every skill shares (input, steps, done, safety)."""
    _, body = split_skill(SKILLS / name / "SKILL.md")
    assert len(body.split("\n")) < MAX_BODY_LINES, "move details to references/*.md"
    headings = set(re.findall(r"^## (.+?)\s*$", body, flags=re.MULTILINE))
    assert {"Input", "Steps", "Done means", "Safety"} <= headings, sorted(headings)
    assert any(heading.startswith("Report example") for heading in headings), sorted(headings)
    assert "$ARGUMENTS" in body, "say where the arguments come from (the text after the skill name)"
    safety = body.split("## Safety", 1)[1].split("\n## ", 1)[0]
    for topic in ("Untrusted content", "No secrets", "No live tiers", "No commits"):
        assert topic in safety, f"the Safety section misses {topic!r}"


@pytest.mark.parametrize("name", EXPECTED_SKILLS)
def test_references_are_one_level_deep_and_linked(name: str) -> None:
    """A skill holds SKILL.md and references/*.md only; each reference is named by SKILL.md, and every reference it
    names exists."""
    directory = SKILLS / name
    files = {relative(path) for path in directory.rglob("*") if path.is_file()}
    allowed = {relative(directory / "SKILL.md")} | {relative(path) for path in directory.glob("references/*.md")}
    assert files == allowed, f"unexpected files {sorted(files - allowed)}"
    text = (directory / "SKILL.md").read_text(encoding="utf-8")
    named = set(REFERENCE_RE.findall(text))
    assert {f"references/{path.name}" for path in directory.glob("references/*.md")} <= named, "orphan reference"
    for reference in named:
        assert (directory / reference).is_file(), f"{name}: {reference} does not exist"


@pytest.mark.parametrize("path", skill_files(), ids=relative)
def test_relative_links_exist(path: Path) -> None:
    """Every relative link of a skill file names a file or a directory of the repository."""
    for dest in links(path):
        target = (path.parent / dest).resolve()
        assert target.is_relative_to(ROOT), f"{relative(path)}: {dest} leaves the repository"
        assert target.exists(), f"{relative(path)}: broken link {dest}"


@pytest.mark.parametrize("path", skill_files(), ids=relative)
def test_otterdog_e2e_invocations_exist(path: Path) -> None:
    """Every otterdog-e2e command, subcommand and long option a skill file names exists in the click CLI."""
    problems = [problem for invocation in invocations(path) for problem in invocation_problems(invocation)]
    assert problems == []


@pytest.mark.parametrize("name", EXPECTED_SKILLS)
def test_each_skill_runs_its_assist_command(name: str) -> None:
    """Each skill names the assist subcommand it is built around (so the invocation check is not vacuous)."""
    found = {invocation.words[:2] for path in (SKILLS / name).rglob("*.md") for invocation in invocations(path)}
    assert SKILL_COMMANDS[name] in found, sorted(found)


@pytest.mark.parametrize("path", skill_files(), ids=relative)
def test_make_targets_exist(path: Path) -> None:
    """Every make target a skill file names is defined in the Makefile."""
    assert sorted(make_targets_used(path) - makefile_targets()) == []


@pytest.mark.parametrize("path", skill_files(), ids=relative)
def test_repository_paths_exist(path: Path) -> None:
    """Every repository path of a code span or a shell block exists (placeholders and globs are skipped)."""
    assert sorted(found for found in repository_paths(path) if not (ROOT / found).exists()) == []


# --- the parsers themselves --------------------------------------------------------------------------------------------
SAMPLE = """\
Run `.venv/bin/otterdog-e2e run --suite offline --sut release:latest --scenario <id>` then `make one SCENARIO=x`.
Read `docs/writing-scenarios.md#known-bugs`, `tests/unit/test_yaml_cli.py::test_x`, `scenarios/offline/<topic>/<n>.yaml`.

```bash
.venv/bin/otterdog-e2e sut resolve release:latest && make lint-scenarios   # comment --not-an-option
.venv/bin/otterdog-e2e run --sut x \\
  --no-such-option
```

````markdown
```text
otterdog-e2e nope
```
````
"""


def test_parsers_read_commands_options_targets_and_paths(tmp_path: Path) -> None:
    """Code spans and fenced blocks (continuations, comments, nested fences) give the invocations, make targets and
    repository paths; placeholders are skipped and unknown commands or options are reported."""
    sample = tmp_path / "SKILL.md"
    sample.write_text(SAMPLE, encoding="utf-8")
    found = [invocation.words for invocation in invocations(sample)]
    assert ("run", "--suite", "offline", "--sut", "release:latest", "--scenario", "<id>") in found
    assert ("sut", "resolve", "release:latest") in found
    assert ("run", "--sut", "x", "--no-such-option") in found
    assert ("nope",) in found
    assert make_targets_used(sample) == {"one", "lint-scenarios"}
    assert repository_paths(sample) == {"docs/writing-scenarios.md", "tests/unit/test_yaml_cli.py"}
    problems = [problem for invocation in invocations(sample) for problem in invocation_problems(invocation)]
    assert any("has no option --no-such-option" in problem for problem in problems)
    assert any("unknown command 'nope'" in problem for problem in problems)
    assert not any("--not-an-option" in problem for problem in problems)
    assert invocation_problems(Invocation("x", ("sut",))) == ["x: otterdog-e2e sut: 'sut' needs a subcommand"]
