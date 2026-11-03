"""The documentation site (GitHub Pages), built by Zensical: ``python docs_site.py build|serve [--strict]``.

Zensical reads mkdocs.yml but runs no MkDocs hooks, so what they did happens before it builds, in the staging directory
``.docs-site/`` (git-ignored), from the sources of the commit being built:

* the pages of docs/, the home page generated from README.md (docs_hooks.readme_to_home) and the pages of the
  scenario explorer (docs_scenarios.pages); a generated page names its source in the front matter ``edit_url``, which
  the theme override docs-theme/partials/actions.html gives its edit button;
* every page as Python-Markdown needs it (docs_hooks.render_page): GitHub callouts as admonitions, unescaped pipes in
  table code spans, links leaving docs/ to GitHub; a link to a file missing from the repository is a problem;
* ``.docs-site/mkdocs.yml``: mkdocs.yml with the staged pages (docs_dir), the theme override copied next to them
  (custom_dir) and the nav entry of the explorer expanded into its section (docs_scenarios.expand_nav). Zensical keeps
  every path of a project below the directory of its configuration (its cache .docs-site/.cache/ too).

``build`` stages, runs ``zensical build`` into .docs-site/site/ and copies it to site/ (what the docs workflow
uploads); ``--strict`` fails on any problem of the staging and on Zensical's warnings (broken links and anchors). ``serve`` stages, runs ``zensical serve`` and stages again whenever
docs/, README.md, mkdocs.yml, docs-theme/, scenarios/ or tests/ change (only the files that differ are written, so the
preview reloads what changed). ``make docs`` and ``make docs-serve`` run them; the docs workflow runs ``build --strict``.

Only the standard library and PyYAML are needed at import time (pymdownx, a dependency of Zensical, is imported by
stage): tests/unit/test_docs_site.py imports this file without the docs group.
"""

from __future__ import annotations

import argparse
import logging
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import docs_hooks
import docs_scenarios
import yaml

ROOT = Path(__file__).resolve().parent
CONFIG = "mkdocs.yml"
STAGING = ".docs-site"
THEME = "docs-theme"
SITE = "site"
DOCS = "docs"
# the sources a preview watches (their changes are staged again)
WATCHED = (DOCS, "README.md", CONFIG, THEME, "scenarios", "tests")
POLL_INTERVAL = 1.0
# the settings docs_site.py sets in the staged configuration, never in mkdocs.yml
STAGED_KEYS = ("docs_dir", "site_dir", "hooks")
STAGED_THEME = "theme"  # docs-theme/ copied below .docs-site/
_TOP_LEVEL_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][A-Za-z0-9_]*):", re.MULTILINE)

log = logging.getLogger("docs_site")


class SiteError(RuntimeError):
    """The site cannot be staged (an invalid mkdocs.yml, a page where a generated one goes)."""


class _MkDocsLoader(yaml.SafeLoader):
    """SafeLoader reading the ``!!python/...`` tags of mkdocs.yml as plain data (nothing is imported)."""


def _python_tag(loader: yaml.SafeLoader, suffix: str, node: yaml.Node) -> Any:
    """The value under a python tag, as data."""
    if isinstance(node, yaml.MappingNode):
        return loader.construct_mapping(node, deep=True)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node, deep=True)
    assert isinstance(node, yaml.ScalarNode)
    return loader.construct_scalar(node)


_MkDocsLoader.add_multi_constructor("tag:yaml.org,2002:python/", _python_tag)


def read_config(text: str) -> dict[str, Any]:
    """mkdocs.yml as data (the python tags as plain values)."""
    # _MkDocsLoader is a SafeLoader: the python tags are read as data, nothing is constructed
    data = yaml.load(text, Loader=_MkDocsLoader)  # noqa: S506
    if not isinstance(data, dict):
        raise SiteError(f"{CONFIG}: expected a mapping")
    return data


def _drop_top_level(text: str, key: str) -> str:
    """``text`` without the top-level ``key:`` block (up to the next top-level key)."""
    matches = list(_TOP_LEVEL_KEY_RE.finditer(text))
    for index, match in enumerate(matches):
        if match.group("key") == key:
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            return text[: match.start()] + text[end:]
    return text


def staged_config(text: str, nav: list[Any]) -> str:
    """mkdocs.yml for Zensical in .docs-site/: the expanded ``nav``, the staged pages, site and theme override (paths
    below .docs-site/, where Zensical wants them)."""
    config = read_config(text)
    present = [key for key in STAGED_KEYS if key in config]
    if present:
        raise SiteError(f"{CONFIG}: {', '.join(present)} must not be set (docs_site.py sets the staged ones)")
    custom_dir = (config.get("theme") or {}).get("custom_dir")
    if custom_dir != THEME:
        raise SiteError(f"{CONFIG}: theme.custom_dir must be {THEME} (the edit button of generated pages)")
    text = _drop_top_level(text, "nav").rstrip("\n")
    text, count = re.subn(rf"(?m)^(\s+custom_dir:\s*){re.escape(THEME)}\s*$", rf"\g<1>{STAGED_THEME}", text)
    assert count == 1
    staged = {"docs_dir": DOCS, "site_dir": SITE}
    return (
        text
        + "\n\n# set by docs_site.py\n"
        + yaml.safe_dump(staged, sort_keys=False)
        + yaml.safe_dump({"nav": nav}, sort_keys=False, allow_unicode=True)
    )


def with_edit_url(markdown: str, url: str) -> str:
    """``markdown`` with ``edit_url: <url>`` in its front matter (added when it has none)."""
    line = f"edit_url: {url}\n"
    if markdown.startswith("---\n"):
        return "---\n" + line + markdown[4:]
    return f"---\n{line}---\n\n{markdown}"


@dataclass
class Staging:
    """The files of the staged site (path below .docs-site/ -> content) and the problems found while staging."""

    files: dict[str, bytes] = field(default_factory=dict)
    problems: list[str] = field(default_factory=list)


class _Problems(logging.Handler):
    """Collects the warnings the staging functions log (docs_scenarios)."""

    def __init__(self, problems: list[str]) -> None:
        """Append to ``problems``."""
        super().__init__(logging.WARNING)
        self.problems = problems

    def emit(self, record: logging.LogRecord) -> None:
        """One problem per warning."""
        self.problems.append(record.getMessage())


def stage(root: Path, slugify: docs_scenarios.Slugify | None = None) -> Staging:
    """Every file of the staged site (module docstring), in memory; ``slugify``: the anchors of the toc extension
    (default pymdownx.slugs.slugify(case='lower'), as in mkdocs.yml)."""
    if slugify is None:
        from pymdownx.slugs import slugify as pymdownx_slugify  # a dependency of Zensical (docs group)

        slugify = pymdownx_slugify(case="lower")
    result = Staging()
    text = (root / CONFIG).read_text(encoding="utf-8")
    config = read_config(text)
    repo_url = str(config.get("repo_url") or "")
    edit = f"{repo_url.rstrip('/')}/edit/{docs_hooks.BRANCH}/"
    handler = _Problems(result.problems)
    docs_scenarios.log.addHandler(handler)
    try:
        site = docs_scenarios.load_site(root, repo_url, slugify)
        generated = docs_scenarios.pages(site)
    finally:
        docs_scenarios.log.removeHandler(handler)
    nav = config.get("nav")
    if not isinstance(nav, list) or not docs_scenarios.expand_nav(nav, docs_scenarios.nav(site)):
        raise SiteError(
            f"{CONFIG}: the nav must hold an entry '<title>: {docs_scenarios.INDEX}' (the scenario explorer)"
        )
    result.files[CONFIG] = staged_config(text, nav).encode()
    theme = root / THEME
    for path in sorted(theme.rglob("*")):
        if path.is_file():
            result.files[f"{STAGED_THEME}/{path.relative_to(theme).as_posix()}"] = path.read_bytes()

    markdown: dict[str, str] = {}
    docs = root / DOCS
    for path in sorted(docs.rglob("*")):
        if not path.is_file():
            continue
        uri = path.relative_to(docs).as_posix()
        if path.suffix == ".md":
            markdown[uri] = path.read_text(encoding="utf-8")
        else:
            result.files[f"{DOCS}/{uri}"] = path.read_bytes()
    for uri, page in {
        docs_hooks.HOME: docs_scenarios.Generated(
            docs_hooks.readme_to_home((root / docs_hooks.README).read_text(encoding="utf-8")), docs_hooks.README
        ),
        **generated,
    }.items():
        if uri in markdown:
            raise SiteError(f"{DOCS}/{uri} must not exist: it is generated (from {page.source})")
        markdown[uri] = with_edit_url(page.markdown, edit + page.source)
    for uri, text in markdown.items():
        rendered, missing = docs_hooks.render_page(text, uri, repo_url, root)
        result.problems += [
            f"Doc file '{uri}' contains a link '{dest}', but its target is not in the repository." for dest in missing
        ]
        result.files[f"{DOCS}/{uri}"] = rendered.encode()
    return result


def write(staging: Path, files: Mapping[str, bytes]) -> list[str]:
    """Make ``staging`` hold exactly ``files`` (the content of the files that differ written, the other staged pages
    and theme files removed; Zensical's cache and site kept); the paths that changed."""
    changed = []
    for name, content in files.items():
        path = staging / name
        if path.is_file() and path.read_bytes() == content:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        changed.append(name)
    for directory in (staging / DOCS, staging / STAGED_THEME):
        for path in sorted(directory.rglob("*"), reverse=True) if directory.is_dir() else []:
            name = path.relative_to(staging).as_posix()
            if path.is_file() and name not in files:
                path.unlink()
                changed.append(name)
            elif path.is_dir() and not any(path.iterdir()):
                path.rmdir()
    return changed


def prepare(
    root: Path, *, strict: bool, staging: Path | None = None, slugify: docs_scenarios.Slugify | None = None
) -> Path:
    """Stage the site into ``staging`` (default root/.docs-site); its configuration (SystemExit 1 on problems with
    ``strict``, nothing written)."""
    staging = staging or root / STAGING
    result = stage(root, slugify)
    for problem in result.problems:
        log.warning("%s", problem)
    if result.problems and strict:
        raise SystemExit(f"{len(result.problems)} problem(s) while staging the site (--strict)")
    write(staging, result.files)
    return staging / CONFIG


def zensical(*args: str) -> list[str]:
    """The Zensical command next to this interpreter (the docs group's), else the one on PATH."""
    local = Path(sys.executable).parent / "zensical"
    found = str(local) if local.exists() else shutil.which("zensical")
    if found is None:
        raise SystemExit("zensical is not installed: poetry install --with docs")
    return [found, *args]


def signature(root: Path, watched: Sequence[str] = WATCHED) -> tuple[tuple[str, int, int], ...]:
    """Path, size and mtime of every watched file (a change of any of them changes the signature)."""

    def files() -> Iterator[Path]:
        for name in watched:
            path = root / name
            yield from (item for item in path.rglob("*") if item.is_file()) if path.is_dir() else [path]

    return tuple(
        sorted(
            (item.relative_to(root).as_posix(), stat.st_size, stat.st_mtime_ns)
            for item in files()
            if "__pycache__" not in item.parts and item.exists() and (stat := item.stat())
        )
    )


def serve(root: Path, *, strict: bool, sleep: Callable[[float], None] = time.sleep) -> int:
    """Stage, run ``zensical serve`` and stage again on every change of the watched sources until it stops."""
    config = prepare(root, strict=strict)
    process = subprocess.Popen(zensical("serve", "-f", str(config)))
    seen = signature(root)
    try:
        while process.poll() is None:
            sleep(POLL_INTERVAL)
            current = signature(root)
            if current != seen:
                seen = current
                try:
                    result = stage(root)
                except SiteError as exc:
                    log.error("%s", exc)
                    continue
                for problem in result.problems:
                    log.warning("%s", problem)
                changed = write(root / STAGING, result.files)
                log.info("staged again: %d file(s) changed", len(changed))
    except KeyboardInterrupt:
        process.terminate()
    return process.wait()


def main(argv: Sequence[str] | None = None) -> int:
    """``build`` or ``serve`` (module docstring)."""
    parser = argparse.ArgumentParser(prog="docs_site.py", description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=("build", "serve", "stage"))
    parser.add_argument("--strict", action="store_true", help="fail on staging problems and Zensical warnings")
    options = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    try:
        if options.command == "serve":
            return serve(ROOT, strict=options.strict)
        config = prepare(ROOT, strict=options.strict)
    except SiteError as exc:
        raise SystemExit(str(exc)) from None
    if options.command == "stage":
        return 0
    command = zensical("build", "--clean", "-f", str(config), *(["--strict"] if options.strict else []))
    code = subprocess.run(command, check=False).returncode
    if code == 0:
        publish(ROOT)
    return code


def publish(root: Path) -> None:
    """Replace site/ by the site Zensical built in .docs-site/site/."""
    built, site = root / STAGING / SITE, root / SITE
    if site.is_symlink() or site.is_file():
        site.unlink()
    elif site.exists():
        shutil.rmtree(site)
    shutil.copytree(built, site)
    log.info("site/: %d page(s)", sum(1 for _ in site.rglob("*.html")))


if __name__ == "__main__":
    raise SystemExit(main())
