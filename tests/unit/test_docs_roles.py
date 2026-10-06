"""docs/roles.md stays current with the roles of the harness and with the tests that need them.

* the table of "The roles at a glance" lists exactly ``settings.IDENTITY_ROLES``, and each role has its section
  (a ``### `<role>``` heading);
* every file that needs a role is named (repository-relative path) in the section of that role. A test module
  (``tests/**/test_*.py`` outside ``tests/unit``) needs a role when its source marks a test with
  ``pytest.mark.identities("<role>", ...)`` or a test function takes an identity fixture of the plugin
  (``pytest_plugin.FIXTURE_IDENTITIES``: ``contributor_mutator`` is the author); a scenario (``scenarios/**/*.yaml``)
  when its ``identities`` list names the role.

The sources are scanned with regular expressions (markers, test signatures) and the scenarios loaded as YAML, so the
check needs neither a target nor a pytest collection.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from functools import cache
from pathlib import Path

import yaml

from otterdog_e2e.pytest_plugin import FIXTURE_IDENTITIES
from otterdog_e2e.settings import IDENTITY_ROLES

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "docs" / "roles.md"
TESTS = ROOT / "tests"
UNIT = TESTS / "unit"
SCENARIOS = ROOT / "scenarios"
TABLE_HEADING = "The roles at a glance"  # a level-2 heading
SECTION_LEVEL = 3  # ### `<role>`
FENCE_RE = re.compile(r"^[ \t>]*(`{3,}|~{3,})")
HEADING_RE = re.compile(r"^(?P<level>#{1,6})[ \t]+(?P<title>.*?)[ \t]*$")
ROLE_TITLE_RE = re.compile(r"^`(?P<role>[a-z_]+)`$")
TABLE_ROLE_RE = re.compile(r"^\|[ \t]*`(?P<role>[a-z_]+)`[ \t]*\|")
# pytest.mark.identities("author", "approver"): the quoted names of its arguments
MARKER_RE = re.compile(r"pytest\.mark\.identities\((?P<args>[^)]*)\)")
QUOTED_NAME_RE = re.compile(r"""["'](?P<name>[a-z_]+)["']""")
# the parameters of a test function (annotations may hold brackets, never parentheses)
TEST_SIGNATURE_RE = re.compile(
    r"^[ \t]*(?:async[ \t]+)?def[ \t]+test\w*[ \t]*\((?P<params>.*?)\)[ \t]*(?:->[^:]*)?:", re.MULTILINE | re.DOTALL
)


# --- the page --------------------------------------------------------------------------------------------------------
@cache
def page_lines() -> tuple[str, ...]:
    """The lines of docs/roles.md."""
    return tuple(PAGE.read_text(encoding="utf-8").split("\n"))


def headings(lines: tuple[str, ...]) -> Iterator[tuple[int, int, str]]:
    """(line index, level, title) of every heading outside fenced code blocks."""
    fence: str | None = None
    for index, line in enumerate(lines):
        match = FENCE_RE.match(line)
        if match:
            marker = match.group(1)
            if fence is None:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = None
            continue
        if fence is None and (heading := HEADING_RE.match(line)):
            yield index, len(heading["level"]), heading["title"]


def section(lines: tuple[str, ...], start: int, level: int) -> list[str]:
    """The lines below the heading at ``start`` up to the next heading of ``level`` or higher."""
    end = next((index for index, depth, _ in headings(lines) if index > start and depth <= level), len(lines))
    return list(lines[start + 1 : end])


def role_sections() -> dict[str, str]:
    """Role -> text of its ``### `<role>``` section."""
    lines = page_lines()
    sections: dict[str, str] = {}
    for index, level, title in headings(lines):
        match = ROLE_TITLE_RE.match(title)
        if level == SECTION_LEVEL and match:
            assert match["role"] not in sections, f"two sections for the role {match['role']}"
            sections[match["role"]] = "\n".join(section(lines, index, SECTION_LEVEL))
    return sections


def table_roles() -> list[str]:
    """The roles of the first table below TABLE_HEADING, in their order."""
    lines = page_lines()
    start = next((index for index, level, title in headings(lines) if (level, title) == (2, TABLE_HEADING)), None)
    assert start is not None, f"docs/roles.md has no {TABLE_HEADING!r} heading"
    rows: list[str] = []
    for line in section(lines, start, 2):
        if line.startswith("|"):
            rows.append(line)
        elif rows:
            break  # the end of the first table
    assert len(rows) > 2, f"no table below {TABLE_HEADING!r}"
    return [match["role"] for row in rows[2:] if (match := TABLE_ROLE_RE.match(row))]


# --- the files that need a role ---------------------------------------------------------------------------------------
def roles_in_source(source: str) -> set[str]:
    """Roles a test module needs: the names of its identities(...) markers and its identity fixtures."""
    roles = {name["name"] for marker in MARKER_RE.finditer(source) for name in QUOTED_NAME_RE.finditer(marker["args"])}
    for signature in TEST_SIGNATURE_RE.finditer(source):
        params = set(re.findall(r"\b\w+\b", signature["params"]))
        roles.update(role for fixture, role in FIXTURE_IDENTITIES.items() if fixture in params)
    return roles


def roles_in_scenario(path: Path) -> set[str]:
    """Roles of the ``identities`` list of a scenario file (empty for other YAML files)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    identities = data.get("identities") if isinstance(data, dict) else None
    return {str(name) for name in identities} if isinstance(identities, list) else set()


@cache
def files_needing_roles() -> dict[str, frozenset[str]]:
    """Repository-relative path -> roles, for every test module (outside tests/unit) and scenario needing one."""
    found: dict[str, frozenset[str]] = {}
    for path in sorted(TESTS.rglob("test_*.py")):
        if UNIT in path.parents:
            continue
        if roles := roles_in_source(path.read_text(encoding="utf-8")):
            found[path.relative_to(ROOT).as_posix()] = frozenset(roles)
    for path in sorted(SCENARIOS.rglob("*.yaml")):
        if roles := roles_in_scenario(path):
            found[path.relative_to(ROOT).as_posix()] = frozenset(roles)
    return found


# --- tests -----------------------------------------------------------------------------------------------------------
def test_the_table_lists_exactly_the_identity_roles() -> None:
    """The reference table names every role of settings.IDENTITY_ROLES once, and no other."""
    roles = table_roles()
    assert len(roles) == len(set(roles)), f"a role is listed twice: {roles}"
    assert sorted(roles) == sorted(IDENTITY_ROLES)


def test_every_role_has_its_section() -> None:
    """One ``### `<role>``` section per role, none for anything else."""
    assert sorted(role_sections()) == sorted(IDENTITY_ROLES)


def test_every_file_needing_a_role_is_named_in_its_section() -> None:
    """A test module or scenario that needs a role is named by its path in that role's section of the page."""
    sections = role_sections()
    unknown = sorted(
        f"{path}: {role}" for path, roles in files_needing_roles().items() for role in roles - set(sections)
    )
    assert unknown == [], "roles without a section in docs/roles.md (or unknown roles)"
    missing = sorted(
        f"{path} needs {role}: name it in the section ### `{role}` of docs/roles.md"
        for path, roles in files_needing_roles().items()
        for role in roles
        if path not in sections[role]
    )
    assert missing == []


def test_the_scan_sees_the_battery() -> None:
    """The scan finds test modules and scenarios needing roles (an empty scan would make the check above vacuous)."""
    found = files_needing_roles()
    assert any(path.startswith("tests/") for path in found), found
    assert any(path.startswith("scenarios/") for path in found), found


def test_roles_in_source() -> None:
    """Markers (decorators and pytestmark lists) and identity fixtures in multi-line, annotated test signatures."""
    source = '''
pytestmark = [pytest.mark.webapp, pytest.mark.identities("config_reader")]


@pytest.mark.identities("author", 'approver')
def test_one(webapp_scenario: WebappScenario) -> None:
    """Docstrings may say outsider_mutator without needing it."""


def test_two(
    e2e: E2EContext,
    outsider_mutator: Mutator,
    make: Callable[[Mapping[str, Any]], None],
) -> None:
    pass


async def test_three(contributor_mutator):
    pass


def helper(approver_mutator):
    pass
'''
    assert roles_in_source(source) == {"config_reader", "author", "approver", "outsider"}
    assert roles_in_source("def test_plain(mutator, mutators) -> None:\n    pass\n") == set()


def test_role_sections_ignore_fenced_code() -> None:
    """A heading-like line inside a fenced block does not end a section."""
    lines = ("### `author`", "text", "```bash", "### not a heading", "```", "more", "### `approver`", "other")
    starts = [(index, level, title) for index, level, title in headings(lines)]
    assert starts == [(0, 3, "`author`"), (6, 3, "`approver`")]
    assert section(lines, 0, SECTION_LEVEL) == ["text", "```bash", "### not a heading", "```", "more"]
