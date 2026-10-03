"""docs_hooks.py, the MkDocs hooks of the documentation site: links leaving docs/ rewritten to GitHub, GitHub callouts
as admonitions, escaped pipes in table code spans, and the home page generated from README.md.

The hooks run for real in the strict build of .github/workflows/docs.yml (`make docs` locally); these tests need
neither MkDocs nor the network, and also check that every link of docs/ leaving the directory has a target and that
no page writes a placeholder (``<org>``) that GitHub and MkDocs would both read as HTML and drop.
"""

from __future__ import annotations

import ast
import importlib.util
import re
import sys
from functools import cache
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "docs_hooks.py"
DOCS = ROOT / "docs"
REPO = "https://github.com/heurtematte/otterdog-e2e"
SITE = "https://heurtematte.github.io/otterdog-e2e/"
# the raw HTML GitHub and the site both render: anchors (<a id>), line breaks, collapsible sections, keys
ALLOWED_TAGS = frozenset({"a", "br", "details", "summary", "sub", "sup", "kbd"})
# an HTML open or closing tag as CommonMark reads it (not a comment, a declaration or an autolink like <https://...>)
HTML_TAG_RE = re.compile(r"</?(?P<name>[A-Za-z][A-Za-z0-9-]*)(?:\s[^<>]*)?/?>")


@cache
def hooks() -> ModuleType:
    """docs_hooks.py as a module (a file next to mkdocs.yml, not part of the package)."""
    name = "otterdog_e2e_docs_hooks_under_test"
    spec = importlib.util.spec_from_file_location(name, HOOKS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def text(*lines: str) -> str:
    """Markdown from its lines."""
    return "\n".join(lines)


def destinations(markdown: str) -> list[str]:
    """Every link destination rewrite_links sees (outside code)."""
    found: list[str] = []

    def collect(dest: str) -> None:
        """Record without rewriting."""
        found.append(dest)

    hooks().rewrite_links(markdown, collect)
    return found


def test_hooks_import_only_the_standard_library() -> None:
    """The module imports MkDocs only for type checking or inside the hooks: the unit tier runs without the docs
    group installed."""
    for node in ast.parse(HOOKS.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        for name in names:
            assert name.split(".")[0] in sys.stdlib_module_names, f"top-level import of {name}"


# --- scanning ----------------------------------------------------------------------------------------------------------
def test_fenced_lines() -> None:
    """Backtick and tilde fences, in lists and blockquotes, closed by a fence of the same character at least as long;
    a backtick line whose info string holds a backtick is not a fence; an unclosed fence runs to the end."""
    lines = [
        "text",
        "```bash",
        "[x](../a)",
        "~~~",
        "```",
        "1. item",
        "    ~~~~ yaml",
        "    ```",
        "    ~~~~~",
        "> ```",
        "> code",
        "> ```",
        "``` not ` a fence",
        "```python",
        "end",
    ]
    expected = [False, True, True, True, True, False, True, True, True, True, True, True, False, True, True]
    assert hooks().fenced_lines(lines) == expected


def test_code_spans() -> None:
    """A backtick run opens a code span closed by the next run of the same length; an unmatched run is text."""
    sample = "a `b` c ``d ` e`` f ``` g"
    assert [sample[start:end] for start, end in hooks().code_spans(sample)] == ["`b`", "``d ` e``"]
    assert hooks().code_spans("no code") == []


def test_rewrite_links_outside_code_only() -> None:
    """Inline links, images, angle-bracket destinations and reference definitions are rewritten (titles kept); code
    spans and fenced blocks are not; None keeps a destination."""
    markdown = text(
        'See [a](x.md), ![img](x.png "title") and [b](<x y.md>).',
        "`[c](x.md)` and ``[d](x.md)``, [g](other.md#a)",
        '[ref]: x.md "t"',
        "",
        "```",
        "[e](x.md)",
        "```",
    )
    rewritten = hooks().rewrite_links(markdown, lambda dest: dest.upper() if dest.startswith("x") else None)
    assert rewritten.split("\n") == [
        'See [a](X.MD), ![img](X.PNG "title") and [b](<X Y.MD>).',
        "`[c](x.md)` and ``[d](x.md)``, [g](other.md#a)",
        '[ref]: X.MD "t"',
        "",
        "```",
        "[e](x.md)",
        "```",
    ]


def test_code_span_across_lines_hides_its_links() -> None:
    """Code spans are found per paragraph: a span wrapped over two lines still hides the link it contains, and a
    stray backtick of one paragraph never pairs with one of the next."""
    markdown = "a `[x](../a)\nb` [y](../b)\n\nstray ` here\n\n[z](../c) and ` again"
    assert destinations(markdown) == ["../b", "../c"]


def test_inline_blocks() -> None:
    """A paragraph (over several lines), a list item with its continuation lines, a heading and each table row are
    blocks of their own; blank lines and fenced code belong to none."""
    lines = [
        "# Title",  # 0
        "text",
        "more text",
        "",
        "- item",  # 4
        "  continued",
        "    - nested",
        "1. ordered",
        "",
        "| a | b |",  # 9
        "|---|---|",
        "| c | d |",
        "```",
        "code",
        "```",
        "> quoted",  # 15
        "> ## heading",
    ]
    assert [(block.start, block.stop) for block in hooks().inline_blocks(lines)] == [
        (0, 1),
        (1, 3),
        (4, 6),
        (6, 7),
        (7, 8),
        (9, 10),
        (10, 11),
        (11, 12),
        (15, 16),
        (16, 17),
    ]


def test_code_spans_stay_in_their_table_row_or_list_item() -> None:
    """A backtick run left open in a table row or a list item (a cut ``code...``) never pairs with a run of the next
    row or item, which would hide its links or expose the links of its code spans."""
    markdown = text(
        "| Id | Summary |",
        "|---|---|",
        "| `a` | cut ``code... |",
        "| `b` | [y](../b) and ``[c](../c)`` |",
        "",
        "- stray ` here",
        "- [z](../d) and `[e](../e)`",
    )
    assert destinations(markdown) == ["../b", "../d"]


# --- links leaving docs/ -----------------------------------------------------------------------------------------------
@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A repository with docs/, a file and a directory outside it."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "page.md").write_text("# page\n", encoding="utf-8")
    (tmp_path / "scenarios").mkdir()
    (tmp_path / "scenarios" / "coverage.yaml").write_text("{}\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("", encoding="utf-8")
    (tmp_path / "a b.txt").write_text("", encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize(
    ("dest", "page", "expected"),
    [
        ("../scenarios/coverage.yaml", "page.md", (f"{REPO}/blob/main/scenarios/coverage.yaml", True)),
        ("../scenarios/coverage.yaml#L3", "page.md", (f"{REPO}/blob/main/scenarios/coverage.yaml#L3", True)),
        ("../scenarios/coverage.yaml?plain=1", "page.md", (f"{REPO}/blob/main/scenarios/coverage.yaml?plain=1", True)),
        ("../scenarios", "page.md", (f"{REPO}/tree/main/scenarios", True)),
        ("../scenarios/", "page.md", (f"{REPO}/tree/main/scenarios", True)),
        ("../.env.example", "index.md", (f"{REPO}/blob/main/.env.example", True)),
        ("../a%20b.txt", "page.md", (f"{REPO}/blob/main/a%20b.txt", True)),
        ("../../.env.example", "sub/page.md", (f"{REPO}/blob/main/.env.example", True)),
        ("..", "page.md", (f"{REPO}/tree/main", True)),
        ("../missing.md", "page.md", (f"{REPO}/blob/main/missing.md", False)),
        # MkDocs validates these itself
        ("../page.md", "sub/page.md", None),
        ("other.md#anchor", "page.md", None),
        ("#anchor", "page.md", None),
        (".", "page.md", None),
        ("/absolute.md", "page.md", None),
        ("../../outside.md", "page.md", None),
        ("https://example.org/../x", "page.md", None),
        ("mailto:someone@example.org", "page.md", None),
    ],
)
def test_github_url(repo: Path, dest: str, page: str, expected: tuple[str, bool] | None) -> None:
    """Links of docs/<page> leaving docs/ point to GitHub (blob for files, tree for directories), with their anchor
    and query; whether the target exists is reported; every other link is left to MkDocs."""
    assert hooks().github_url(dest, page, REPO, repo) == expected


@pytest.mark.parametrize("page", sorted(path.name for path in DOCS.glob("*.md")))
def test_links_leaving_docs_have_a_target(page: str) -> None:
    """Every link of a page that leaves docs/ names a file or a directory of the repository (the docs build fails
    otherwise; this catches it in the unit tier)."""
    leaving = [
        hooks().github_url(dest, page, REPO, ROOT)
        for dest in destinations(DOCS.joinpath(page).read_text(encoding="utf-8"))
    ]
    assert [found[0] for found in leaving if found is not None and not found[1]] == []


def test_the_known_links_leaving_docs_are_rewritten() -> None:
    """The pages that link to the YAML registries get their GitHub URL."""
    for page, target in (
        ("battery-guide.md", "scenarios/coverage.yaml"),
        ("coverage-matrix.md", "scenarios/coverage.yaml"),
        ("known-issues.md", "scenarios/known_bugs.yaml"),
    ):
        urls = [
            hooks().github_url(dest, page, REPO, ROOT)
            for dest in destinations(DOCS.joinpath(page).read_text(encoding="utf-8"))
        ]
        assert (f"{REPO}/blob/main/{target}", True) in urls, page


@pytest.mark.parametrize("page", ["README.md", *sorted(f"docs/{path.name}" for path in DOCS.glob("*.md"))])
def test_no_placeholder_is_read_as_html(page: str) -> None:
    """Outside code, ``<org>`` is an HTML tag for GitHub and for MkDocs, and both drop it ("accept the invitation
    (https://github.com/orgs//invitation)"): a placeholder goes in a code span (`orgs/<org>`) or is written
    ``&lt;org&gt;``. Only the raw HTML both render is allowed (ALLOWED_TAGS)."""
    lines = (ROOT / page).read_text(encoding="utf-8").split("\n")
    found: list[str] = []
    for block in hooks().inline_blocks(lines):
        block_text = "\n".join(lines[block.start : block.stop])
        spans = hooks().code_spans(block_text)
        for match in HTML_TAG_RE.finditer(block_text):
            if match["name"].lower() in ALLOWED_TAGS or any(start <= match.start() < end for start, end in spans):
                continue
            found.append(f"{page}:{block.start + block_text.count(chr(10), 0, match.start()) + 1}: {match.group()}")
    assert found == []


# --- callouts and tables -----------------------------------------------------------------------------------------------
def test_convert_callouts() -> None:
    """GitHub callouts become admonitions (any case); other blockquotes and code are kept."""
    markdown = text(
        "> [!WARNING]",
        "> Only **test** organizations.",
        ">",
        "> See [x](x.md).",
        "",
        "> [!important]",
        "> Lower case.",
        "",
        "> [!TODO]",
        "> unknown kind",
        "",
        "> plain quote",
        "",
        "```",
        "> [!NOTE]",
        "> in code",
        "```",
    )
    assert hooks().convert_callouts(markdown).split("\n") == [
        '!!! warning "Warning"',
        "",
        "    Only **test** organizations.",
        "",
        "    See [x](x.md).",
        "",
        '!!! info "Important"',
        "",
        "    Lower case.",
        "",
        "> [!TODO]",
        "> unknown kind",
        "",
        "> plain quote",
        "",
        "```",
        "> [!NOTE]",
        "> in code",
        "```",
    ]


@pytest.mark.parametrize(
    ("kind", "admonition"),
    [
        ("NOTE", '!!! note "Note"'),
        ("TIP", '!!! tip "Tip"'),
        ("IMPORTANT", '!!! info "Important"'),
        ("WARNING", '!!! warning "Warning"'),
        ("CAUTION", '!!! danger "Caution"'),
    ],
)
def test_callout_kinds(kind: str, admonition: str) -> None:
    """The five GitHub callouts map to Material admonition types, titled like on GitHub."""
    assert hooks().convert_callouts(f"> [!{kind}]\n> text") == f"{admonition}\n\n    text"


def test_unescape_table_code_pipes() -> None:
    """In table rows only, ``\\|`` inside a code span loses its backslash; escaped pipes in text, code outside
    tables and fenced blocks are kept."""
    markdown = text(
        "| Command | What |",
        "|---|:--:|",
        "| `a\\|b` | x \\| y |",
        "| ``c \\| d`` | `e` |",
        "",
        "`f\\|g` outside a table",
        "",
        "```",
        "| `h\\|i` | j |",
        "|---|---|",
        "```",
    )
    assert hooks().unescape_table_code_pipes(markdown).split("\n") == [
        "| Command | What |",
        "|---|:--:|",
        "| `a|b` | x \\| y |",
        "| ``c | d`` | `e` |",
        "",
        "`f\\|g` outside a table",
        "",
        "```",
        "| `h\\|i` | j |",
        "|---|---|",
        "```",
    ]


# --- home page ---------------------------------------------------------------------------------------------------------
def test_readme_to_home() -> None:
    """The github-only blocks are dropped; links are rebased from the repository root to docs/; external links,
    anchors and code are kept."""
    readme = text(
        "# Title",
        "",
        "<!-- github-only -->",
        "",
        "[![docs](https://example.org/badge.svg)](https://example.org/actions)",
        "",
        "<!-- /github-only -->",
        "",
        "See [security](docs/security.md#ci), [coverage](scenarios/coverage.yaml), [env](.env.example),",
        "[dir](scenarios/), [web](https://example.org/x), [top](#tiers) and `[code](docs/x.md)`.",
    )
    assert hooks().readme_to_home(readme).split("\n") == [
        "# Title",
        "",
        "",
        "See [security](security.md#ci), [coverage](../scenarios/coverage.yaml), [env](../.env.example),",
        "[dir](../scenarios/), [web](https://example.org/x), [top](#tiers) and `[code](docs/x.md)`.",
    ]


def test_readme_home_page() -> None:
    """README.md has one github-only block (the docs badge and the link to the site); the home page generated from it
    has no link left to docs/ and every relative link resolves (a page of docs/ or a file of the repository)."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert readme.count("<!-- github-only -->") == readme.count("<!-- /github-only -->") == 1
    block = readme.split("<!-- github-only -->")[1].split("<!-- /github-only -->")[0]
    assert SITE in block and "actions/workflows/docs.yml/badge.svg" in block
    home = hooks().readme_to_home(readme)
    assert "github-only" not in home and "badge.svg" not in home
    relative = [dest for dest in destinations(home) if not urlsplit(dest).scheme and not dest.startswith("#")]
    assert relative, "the README links the documentation"
    for dest in relative:
        assert not dest.startswith("docs/"), dest
        assert (DOCS / unquote(urlsplit(dest).path)).resolve().exists(), dest
