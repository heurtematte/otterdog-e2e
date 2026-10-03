"""MkDocs hooks of the documentation site (``hooks:`` in mkdocs.yml).

The pages stay GitHub-flavored Markdown that renders on github.com. These hooks bridge what Python-Markdown (MkDocs)
does differently, without changing the sources:

* the home page (``index.md``) is generated from README.md: the blocks between ``<!-- github-only -->`` and
  ``<!-- /github-only -->`` are dropped and the links are rebased from the repository root to docs/;
* GitHub callouts (``> [!WARNING]``) become admonitions;
* in table rows, ``\\|`` inside a code span becomes ``|``: GitHub needs the escape to keep the pipe in its cell, while
  Python-Markdown already ignores the pipes of code spans and would print the backslash;
* links that leave docs/ (``../scenarios/coverage.yaml``) point to the file on GitHub (``blob/main/...``, or
  ``tree/main/...`` for a directory); a target missing from the repository is a warning, so an error with ``--strict``.

Only the standard library is needed at import time: tests/unit/test_docs_hooks.py imports this file without MkDocs.
"""

from __future__ import annotations

import logging
import posixpath
import re
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import quote, unquote, urlsplit, urlunsplit

if TYPE_CHECKING:
    from mkdocs.config.defaults import MkDocsConfig
    from mkdocs.structure.files import Files
    from mkdocs.structure.pages import Page

# below the "mkdocs" logger, so its warnings count for `mkdocs build --strict`
log = logging.getLogger("mkdocs.plugins.docs_hooks")

HOME = "index.md"
README = "README.md"
DOCS_DIR = "docs"
# the branch the site is built from (also in the edit_uri of mkdocs.yml)
BRANCH = "main"

GITHUB_ONLY_RE = re.compile(
    r"^[ ]{0,3}<!-- github-only -->[ \t]*\n.*?^[ ]{0,3}<!-- /github-only -->[ \t]*(?:\n|\Z)", re.MULTILINE | re.DOTALL
)
# an opening or closing code fence, also inside a list item or a blockquote
FENCE_RE = re.compile(r"^[ \t>]*(?P<fence>`{3,}|~{3,})(?P<info>.*)$")
BACKTICKS_RE = re.compile(r"`+")
# the destination of an inline link or image (``](dest``) and of a link reference definition (``[label]: dest``)
INLINE_DEST_RE = re.compile(r"\]\((?P<dest><[^<>\n]*>|[^\s()<>]+)")
REFERENCE_DEST_RE = re.compile(r"^[ ]{0,3}\[[^\]\n]+\]:[ \t]*(?P<dest><[^<>\n]*>|\S+)", re.MULTILINE)
DELIMITER_ROW_RE = re.compile(r"^[ \t]*\|?(?:[ \t]*:?-+:?[ \t]*\|)*[ \t]*:?-+:?[ \t]*\|?[ \t]*$")
# the inline content of a table row or a heading is parsed on its own, and a list item starts a new block: a code span
# never crosses them
TABLE_ROW_RE = re.compile(r"^[ \t>]*\|")
HEADING_RE = re.compile(r"^[ \t>]*#{1,6}(?:[ \t]|$)")
LIST_ITEM_RE = re.compile(r"^[ \t>]*(?:[-*+]|\d{1,9}[.)])(?:[ \t]|$)")
CALLOUT_RE = re.compile(r"^(?P<indent>[ ]{0,3})>[ ]?\[!(?P<kind>[A-Za-z]+)\][ \t]*$")
# GitHub callout -> Material admonition type and title
CALLOUTS = {
    "NOTE": ("note", "Note"),
    "TIP": ("tip", "Tip"),
    "IMPORTANT": ("info", "Important"),
    "WARNING": ("warning", "Warning"),
    "CAUTION": ("danger", "Caution"),
}


# --- Markdown scanning ------------------------------------------------------------------------------------------------
def fenced_lines(lines: Sequence[str]) -> list[bool]:
    """For each line, whether it belongs to a fenced code block (its fences included)."""
    flags: list[bool] = []
    fence = ""
    for line in lines:
        match = FENCE_RE.match(line)
        if fence:
            flags.append(True)
            if (
                match
                and match["fence"][0] == fence[0]
                and len(match["fence"]) >= len(fence)
                and not match["info"].strip()
            ):
                fence = ""
        elif match and not (match["fence"][0] == "`" and "`" in match["info"]):
            fence = match["fence"]
            flags.append(True)
        else:
            flags.append(False)
    return flags


def code_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) of the code spans of a paragraph: a backtick run up to the next run of the same length."""
    runs = list(BACKTICKS_RE.finditer(text))
    spans: list[tuple[int, int]] = []
    index = 0
    while index < len(runs):
        size = len(runs[index].group())
        closing = next((later for later in range(index + 1, len(runs)) if len(runs[later].group()) == size), None)
        if closing is None:
            index += 1
            continue
        spans.append((runs[index].start(), runs[closing].end()))
        index = closing + 1
    return spans


def _in_spans(position: int, spans: Sequence[tuple[int, int]]) -> bool:
    """True when ``position`` falls inside one of ``spans``."""
    return any(start <= position < end for start, end in spans)


def inline_blocks(lines: Sequence[str]) -> list[range]:
    """The ranges of lines whose inline content (code spans, links) is parsed as one text: a paragraph, a list item up
    to the next item, a heading, a table row. Blank lines and fenced code blocks belong to none."""
    blocks: list[range] = []
    start: int | None = None
    for index, (line, fenced) in enumerate(zip(lines, fenced_lines(lines), strict=True)):
        blank = fenced or not line.strip()
        single = not blank and bool(TABLE_ROW_RE.match(line) or HEADING_RE.match(line))
        if start is not None and (blank or single or LIST_ITEM_RE.match(line)):
            blocks.append(range(start, index))
            start = None
        if single:
            blocks.append(range(index, index + 1))
        elif not blank and start is None:
            start = index
    if start is not None:
        blocks.append(range(start, len(lines)))
    return blocks


def rewrite_links(markdown: str, rewrite: Callable[[str], str | None]) -> str:
    """Replace the destination of every link, image and link reference definition outside code by ``rewrite(dest)``
    (``None`` keeps it). Fenced code blocks are skipped, and code spans are found per block (inline_blocks)."""
    lines = markdown.split("\n")
    out: list[str] = []
    done = 0
    for block in inline_blocks(lines):
        out += lines[done : block.start]
        out.append(_rewrite_paragraph("\n".join(lines[block.start : block.stop]), rewrite))
        done = block.stop
    out += lines[done:]
    return "\n".join(out)


def _rewrite_paragraph(text: str, rewrite: Callable[[str], str | None]) -> str:
    """rewrite_links on one block of inline_blocks (no fenced code, no blank line)."""
    spans = code_spans(text)
    edits: list[tuple[int, int, str]] = []
    for regex in (INLINE_DEST_RE, REFERENCE_DEST_RE):
        for match in regex.finditer(text):
            if _in_spans(match.start(), spans):
                continue
            dest = match["dest"]
            bracketed = dest.startswith("<")
            new = rewrite(dest[1:-1] if bracketed else dest)
            if new is not None:
                edits.append((match.start("dest"), match.end("dest"), f"<{new}>" if bracketed else new))
    for start, end, new in sorted(edits, reverse=True):
        text = text[:start] + new + text[end:]
    return text


# --- transformations ---------------------------------------------------------------------------------------------------
def convert_callouts(markdown: str) -> str:
    """GitHub callouts (a blockquote opened by ``[!NOTE]``, ``[!TIP]``, ``[!IMPORTANT]``, ``[!WARNING]`` or
    ``[!CAUTION]``) as Material admonitions; other blockquotes and code blocks are kept."""
    lines = markdown.split("\n")
    fenced = fenced_lines(lines)
    out: list[str] = []
    index = 0
    while index < len(lines):
        match = None if fenced[index] else CALLOUT_RE.match(lines[index])
        callout = CALLOUTS.get(match["kind"].upper()) if match else None
        if match is None or callout is None:
            out.append(lines[index])
            index += 1
            continue
        indent = match["indent"]
        out += [f'{indent}!!! {callout[0]} "{callout[1]}"', ""]
        index += 1
        while index < len(lines) and lines[index].startswith(f"{indent}>"):
            body = lines[index][len(indent) + 1 :]
            body = body.removeprefix(" ")
            out.append(f"{indent}    {body}" if body.strip() else "")
            index += 1
    return "\n".join(out)


def unescape_table_code_pipes(markdown: str) -> str:
    """``\\|`` inside the code spans of table rows becomes ``|``: GitHub needs the escape to keep the pipe in its cell,
    Python-Markdown already ignores the pipes of code spans and would print the backslash."""
    lines = markdown.split("\n")
    fenced = fenced_lines(lines)
    rows = [False] * len(lines)
    for index in range(1, len(lines)):
        header, delimiter = lines[index - 1], lines[index]
        if fenced[index] or fenced[index - 1] or "|" not in header or "|" not in delimiter:
            continue
        if not DELIMITER_ROW_RE.match(delimiter):
            continue
        end = index + 1
        while end < len(lines) and lines[end].strip() and not fenced[end]:
            end += 1
        rows[index - 1 : end] = [True] * (end - index + 1)
    for index, row in enumerate(rows):
        if row and "\\|" in lines[index]:
            lines[index] = _unescape_code_pipes(lines[index])
    return "\n".join(lines)


def _unescape_code_pipes(row: str) -> str:
    """``\\|`` -> ``|`` inside the code spans of one table row."""
    parts: list[str] = []
    last = 0
    for start, end in code_spans(row):
        parts += [row[last:start], row[start:end].replace("\\|", "|")]
        last = end
    parts.append(row[last:])
    return "".join(parts)


def github_url(dest: str, page: str, repo_url: str, root: Path) -> tuple[str, bool] | None:
    """For a link of docs/``page`` whose target leaves docs/: its URL on GitHub (``blob`` for a file, ``tree`` for a
    directory) and whether the target exists. None for every other link (external, anchor only, absolute, inside
    docs/, or outside the repository: MkDocs validates those)."""
    parts = urlsplit(dest)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
        return None
    target = posixpath.normpath(posixpath.join(DOCS_DIR, posixpath.dirname(page), unquote(parts.path)))
    if target in (DOCS_DIR, "..") or target.startswith((f"{DOCS_DIR}/", "../")):
        return None
    path = root / target
    kind = "tree" if path.is_dir() or parts.path.endswith("/") or target == "." else "blob"
    url = f"{repo_url.rstrip('/')}/{kind}/{BRANCH}" + ("" if target == "." else f"/{quote(target)}")
    url += (f"?{parts.query}" if parts.query else "") + (f"#{parts.fragment}" if parts.fragment else "")
    return url, path.exists()


def readme_to_home(readme: str) -> str:
    """The home page: README.md without its github-only blocks, its links rebased from the repository root to docs/
    (``docs/x.md`` -> ``x.md``, ``scenarios/y`` -> ``../scenarios/y``)."""
    return rewrite_links(GITHUB_ONLY_RE.sub("", readme), _rebase_on_docs)


def _rebase_on_docs(dest: str) -> str | None:
    """A README link destination as seen from docs/ (None keeps external links, anchors and absolute paths)."""
    parts = urlsplit(dest)
    if parts.scheme or parts.netloc or not parts.path or parts.path.startswith("/"):
        return None
    path = posixpath.relpath(posixpath.normpath(parts.path), DOCS_DIR)
    if parts.path.endswith("/") and not path.endswith("/"):
        path += "/"
    return urlunsplit(("", "", path, parts.query, parts.fragment))


# --- MkDocs hooks ------------------------------------------------------------------------------------------------------
def on_files(files: Files, *, config: MkDocsConfig) -> Files:
    """Add the home page, generated from README.md."""
    from mkdocs.exceptions import PluginError
    from mkdocs.structure.files import File

    if files.get_file_from_path(HOME) is not None:
        raise PluginError(f"{DOCS_DIR}/{HOME} must not exist: the home page is generated from {README}")
    readme = (Path(config.docs_dir).parent / README).read_text(encoding="utf-8")
    files.append(File.generated(config, HOME, content=readme_to_home(readme)))
    return files


def on_pre_page(page: Page, *, config: MkDocsConfig, files: Files) -> Page:
    """The edit button of the generated home page opens README.md."""
    if page.file.src_uri == HOME and config.repo_url:
        page.edit_url = f"{config.repo_url.rstrip('/')}/edit/{BRANCH}/{README}"
    return page


def on_page_markdown(markdown: str, *, page: Page, config: MkDocsConfig, files: Files) -> str:
    """GitHub callouts as admonitions, unescaped pipes in table code spans, links leaving docs/ to GitHub."""
    root = Path(config.docs_dir).parent
    repo_url = config.repo_url
    source = page.file.src_uri

    def to_github(dest: str) -> str | None:
        """The GitHub URL of a link leaving docs/ (a missing target is reported)."""
        found = github_url(dest, source, repo_url, root) if repo_url else None
        if found is None:
            return None
        url, exists = found
        if not exists:
            log.warning("Doc file '%s' contains a link '%s', but its target is not in the repository.", source, dest)
        return url

    return rewrite_links(unescape_table_code_pipes(convert_callouts(markdown)), to_github)
