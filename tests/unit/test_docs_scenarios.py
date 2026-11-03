"""docs_scenarios.py, the scenario explorer of the documentation site: one generated page per YAML scenario and per
Python test module, overview tables and their navigation section.

The hooks run for real in the strict build of .github/workflows/docs.yml (`make docs` locally: every generated link
and anchor is checked there); these tests need neither MkDocs nor the network. They pin the parsing (step lines,
pytest marks, the tables of docs/writing-scenarios.md, CHECK_KINDS), the Markdown helpers, what a step page says it
runs, and that the real repository yields a page for every scenario and module.
"""

from __future__ import annotations

import importlib.util
import re
import sys
from functools import cache
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOKS = ROOT / "docs_scenarios.py"
REPO = "https://github.com/heurtematte/otterdog-e2e"


@cache
def explorer() -> ModuleType:
    """docs_scenarios.py as a module (a file next to zensical.toml, not part of the package)."""
    name = "otterdog_e2e_docs_scenarios_under_test"
    spec = importlib.util.spec_from_file_location(name, HOOKS)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def slugify(value: str, separator: str) -> str:
    """The anchors of the site (pymdownx.slugs.slugify(case='lower')), close enough for these tests."""
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"\s+", separator, value)


@cache
def site() -> Any:
    """The explorer's view of this repository."""
    return explorer().load_site(ROOT, REPO, slugify)


def writer(uri: str = "scenarios/cli/repo/x.md") -> Any:
    """A Writer of a page at ``uri`` on a minimal site."""
    module = explorer()
    return module.Writer(module.Site(root=ROOT, repo_url=REPO, slugify=slugify, upstream_ref="abc1234"), uri)


def scenario(data: dict[str, Any], tier: str = "cli", text: str = "") -> Any:
    """A Scenario of ``data`` (no source lines unless ``text`` is given)."""
    module = explorer()
    lines = module.step_lines(text) if text else ()
    return module.Scenario(f"scenarios/{tier}/repo/x.yaml", tier, "repo", data, text, lines)


# --- sources ------------------------------------------------------------------------------------------------------------
def test_step_lines_stop_before_blank_lines_comments_and_the_next_step() -> None:
    text = """id: x
steps:
  - name: one
    fragments: {}

  # about the next step
  - name: two
    plan:
      expect: noop
"""
    assert explorer().step_lines(text) == ((3, 4), (7, 9))


def test_parse_module_reads_tests_and_their_marks() -> None:
    source = '''"""Module doc."""
import pytest

SCENARIO = "W-X"
pytestmark = [pytest.mark.tags("webapp"), pytest.mark.docker]


@pytest.mark.scenario(SCENARIO, priority="P1", references=[{"pr": 891}, {"change": "slug"}])
@pytest.mark.known_bug("KB-001")
@pytest.mark.timeout(60)
def test_one():
    """First sentence. More."""


class TestGroup:
    @pytest.mark.tags("repo")
    async def test_two(self):
        pass

    def helper(self):
        pass


def helper():
    pass
'''
    module = explorer().parse_module(source, "tests/webapp/test_x.py", "webapp")
    assert module.doc == "Module doc."
    assert module.tags == ("webapp",)
    assert module.marks == ("docker",)
    assert [test.name for test in module.tests] == ["test_one", "TestGroup::test_two"]
    one, two = module.tests
    assert (one.scenario, one.priority, one.references) == ("W-X", "P1", ("#891", "slug"))
    assert one.known_bugs == ("KB-001",)
    assert one.marks == ("timeout(60)",)
    assert one.line == 8 and one.source.startswith("@pytest.mark.scenario(SCENARIO")
    assert one.summary == "First sentence."
    assert two.heading == "TestGroup.test_two"
    assert two.tags == ("webapp", "repo")
    assert two.source.startswith('@pytest.mark.tags("repo")\nasync def test_two')


def test_check_kinds_and_their_documentation_match() -> None:
    """Every check kind of CHECK_KINDS has its oracle method and a row in the State checks tables."""
    current = site()
    assert current.check_kinds["repo_secret"] == ("repo_secret", ("repo", "name"))
    for kind, (method, _params) in current.check_kinds.items():
        assert method in current.oracle_lines, f"oracle method {method} of {kind}"
        assert current.check_values.get(kind), f"check kind {kind} has no row in docs/writing-scenarios.md#state-checks"


def test_features_by_item_strips_parameters_and_steps() -> None:
    features = [
        {"id": "a", "covered_by": ["O-X/case", "tests/offline/test_x.py::test_y[param]", "cli.repo.y"]},
        {"id": "b", "covered_by": ["tests/cli/test_z.py::TestZ::test_w"]},
    ]
    found = explorer().features_by_item(features)
    assert [f["id"] for f in found["O-X"]] == ["a"]
    assert [f["id"] for f in found["tests/offline/test_x.py::test_y"]] == ["a"]
    assert [f["id"] for f in found["tests/cli/test_z.py::TestZ::test_w"]] == ["b"]
    assert "cli.repo.y" in found


def test_mentions_find_quoted_ids_and_cases() -> None:
    files = [("tests/offline/test_x.py", 'A = ("O-X", "case")\nB = "O-X/other"\nC = "O-XY"\n# O-X unquoted\n')]
    assert explorer().mentions(files, {"O-X"}) == {
        "O-X": [
            ("tests/offline/test_x.py", 1, 'A = ("O-X", "case")'),
            ("tests/offline/test_x.py", 2, 'B = "O-X/other"'),
        ]
    }


# --- Markdown -------------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [("a", "`a`"), ("a`b", "``a`b``"), ("`a", "`` `a ``"), ("", '`""`'), ("a\nb", "`a\\nb`")],
)
def test_code_spans_hold_any_text(text: str, expected: str) -> None:
    assert explorer().code(text) == expected


def test_fenced_uses_a_longer_fence_than_the_content() -> None:
    assert explorer().fenced("```\nx\n```", "md", indent="    ") == [
        "    ````md",
        "    ```",
        "    x",
        "    ```",
        "    ````",
    ]


def test_prose_links_pull_requests_bugs_and_sources() -> None:
    w = writer()
    text = (
        "Since #892 (KB-033) see otterdog/models/repo.py:12-20 and tests/offline/test_scenarios.py, not tests/nope.py."
    )
    out = w.prose(text)
    assert "[#892](https://github.com/eclipse-csi/otterdog/pull/892)" in out
    assert "[KB-033](../../../known-issues.md)" in out
    assert (
        "[`otterdog/models/repo.py:12-20`](https://github.com/eclipse-csi/otterdog/blob/abc1234/otterdog/models/repo.py#L12-L20)"
        in out
    )
    assert f"[`tests/offline/test_scenarios.py`]({REPO}/blob/main/tests/offline/test_scenarios.py)" in out
    assert "`tests/nope.py`." in out


def test_prose_escapes_markup_and_keeps_lists_and_wrapped_code() -> None:
    w = writer()
    text = "a <run> *b* x_y\n- item one\n* item two\n#790 starts a line\n+ add x\nsee `a\nb` and ``c``"
    out = w.prose(text).split("\n")
    assert out[0] == r"a &lt;run&gt; \*b\* x\_y"
    assert out[1:3] == ["- item one", "* item two"]
    assert out[3].startswith("[#790](")
    assert out[4] == "+ add x"  # a list item, like "- " and "* "
    assert out[5] == "see `a b` and `c`"


def test_prose_splits_paragraphs_at_scenario_id_lines() -> None:
    out = writer().prose("Intro line.\nO-WEB-BOOT: boots.\nO-WEB-SIG: signs\nwrapped.")
    assert out == "Intro line.\n\nO-WEB-BOOT: boots.\n\nO-WEB-SIG: signs\nwrapped."


def test_upstream_urls_show_as_numbers() -> None:
    assert writer().inline("https://github.com/eclipse-csi/otterdog/pull/891") == (
        "[#891](https://github.com/eclipse-csi/otterdog/pull/891)"
    )


def test_cell_escapes_pipes_and_line_breaks() -> None:
    assert explorer().cell("`a|b` c|d\ne") == r"`a\|b` c\|d e"


def test_first_sentence_and_versions() -> None:
    module = explorer()
    assert module.first_sentence("One thing. Two.\n\nOther.") == "One thing."
    assert module.first_sentence("x" * 300, limit=10) == "xxxxxxx..."
    assert module.is_newer("1.8.0.dev7", "v1.7.1")
    assert not module.is_newer("1.7.0.dev58", "v1.7.1")
    assert not module.is_newer("garbage", "v1.7.1")


# --- step rendering -------------------------------------------------------------------------------------------------------
def test_live_step_runs_plan_apply_state_converge() -> None:
    module = explorer()
    current = scenario({"id": "cli.x"})
    step = {
        "plan": {"expect": "changes", "counts": {"add": 1}, "contains": ["+ add"]},
        "apply": {"delete": True},
        "state": [{"kind": "repo", "name": "{{ p }}-a", "match": {"archived": True}}],
    }
    w = writer()
    w.site.check_kinds = {"repo": ("repo", ("name",))}
    out = "\n".join(module._live_phases(w, current, step))
    assert "`otterdog plan -n -r '{{ p }}-*'`: expects **changes**, plan summary 1 to add." in out
    assert "- output contains `+ add`" in out
    assert "`otterdog apply -f -n -d -r '{{ p }}-*'`: expects **success**. Removals are applied" in out
    assert "| `repo` | name `{{ p }}-a` | match `{archived: true}` |" in out
    assert "**converge**" in out


def test_live_step_without_apply_or_plan() -> None:
    module = explorer()
    org_level = scenario({"id": "cli.x", "org_level": True})
    out = "\n".join(module._live_phases(writer(), org_level, {"plan": {"expect": "noop"}}))
    assert "`otterdog plan -n`: expects **no change**" in out
    assert "**apply** · not run (the plan expects no changes)" in out
    assert "converge" not in out
    out = "\n".join(module._live_phases(writer(), org_level, {"plan": None}))
    assert "skipped (`plan: null`)" in out


def test_offline_step_phases() -> None:
    module = explorer()
    step = {
        "validate": {"ok": False, "errors": 2, "contains": ["Error"]},
        "base_fragments": {},
        "plan": {"expect": "validation_error", "update_secrets": True},
        "commands": {"canonical-diff": {"exit_code": None}, "--version": {"contains": ["otterdog"]}},
    }
    out = "\n".join(module._offline_phases(writer("scenarios/offline/repo/x.md"), step))
    assert "`otterdog validate --local`: expects validation to **fail** with exactly 2 error(s)." in out
    assert "`otterdog local-plan --local --update-secrets`: expects a **validation error**." in out
    assert "`otterdog show --local`: may fail (validation is expected to fail)." in out
    assert "`otterdog canonical-diff --local`: expects any exit code." in out
    assert "`otterdog --version`: expects exit code 0." in out
    without_base = "\n".join(module._offline_phases(writer(), {"validate": {"ok": True}}))
    assert "local-plan" not in without_base and "show --local`: must exit 0" in without_base


def test_missing_capability_merges_expectations() -> None:
    step = {
        "plan": {"expect": "changes", "contains": ["a"]},
        "state": [{"kind": "repo"}],
        "on_missing_capability": {"plan": {"expect": "error"}, "state": []},
    }
    merged = explorer().missing_capability_step(step)
    assert merged["plan"] == {"expect": "error", "contains": ["a"]}
    assert merged["state"] == []


def test_fragments_block_inlines_files(tmp_path: Path) -> None:
    module = explorer()
    (tmp_path / "scenarios/cli/repo").mkdir(parents=True)
    (tmp_path / "scenarios/fragments").mkdir()
    (tmp_path / "scenarios/fragments/f.jsonnet").write_text("orgs.newRepo('{{ name }}')\n", encoding="utf-8")
    w = module.Writer(module.Site(root=tmp_path, repo_url=REPO, slugify=slugify), "scenarios/cli/repo/x.md")
    files: list[str] = []
    fragments = {"repositories": ["orgs.newRepo('a')", {"file": "../../fragments/f.jsonnet", "vars": {"name": "b"}}]}
    out = module._fragments_block(w, scenario({"id": "x"}), fragments, files)
    assert out == [
        "```jsonnet",
        "// repositories -> _repositories",
        "orgs.newRepo('a'),",
        "// file scenarios/fragments/f.jsonnet, vars {name: b}",
        "orgs.newRepo('{{ name }}'),",
        "```",
    ]
    assert files == ["scenarios/fragments/f.jsonnet"]


# --- the repository -------------------------------------------------------------------------------------------------------
def test_every_scenario_and_module_gets_a_page() -> None:
    module = explorer()
    current = site()
    pages = module.pages(current)
    yaml_files = [p for tier in ("offline", "cli", "enterprise") for p in (ROOT / "scenarios" / tier).glob("*/*.yaml")]
    assert len(current.scenarios) == len(yaml_files)
    assert {s.uri for s in current.scenarios} <= set(pages)
    assert {m.uri for m in current.modules} <= set(pages)
    assert len({s.id for s in current.scenarios}) == len(current.scenarios)
    for scenario_ in current.scenarios:
        assert len(scenario_.step_lines) == len(scenario_.steps), scenario_.path
        lines = scenario_.text.split("\n")
        for first, last in scenario_.step_lines:
            assert lines[first - 1].lstrip().startswith("- "), (scenario_.path, first)
            assert first <= last
        assert pages[scenario_.uri].source == scenario_.path


def test_every_known_bug_of_a_scenario_has_an_anchor() -> None:
    current = site()
    for scenario_ in current.scenarios:
        for kb in scenario_.known_bugs():
            assert kb in current.kb_anchors, f"{scenario_.path}: {kb} has no section in docs/known-issues.md"


def test_nav_lists_every_generated_page_once() -> None:
    module = explorer()
    current = site()

    def flatten(entry: Any) -> list[str]:
        if isinstance(entry, str):
            return [entry]
        if isinstance(entry, dict):
            return [page for value in entry.values() for page in flatten(value)]
        return [page for item in entry for page in flatten(item)]

    listed = flatten(module.nav(current))
    assert len(listed) == len(set(listed))
    assert set(listed) == set(module.pages(current))


def test_expand_nav_replaces_the_explorer_entry() -> None:
    module = explorer()
    entries: list[Any] = ["index.md", {"Reference": [{"Explorer": "scenarios/index.md"}]}]
    assert module.expand_nav(entries, ["scenarios/index.md", {"Offline": []}])
    assert entries[1] == {"Reference": [{"Explorer": ["scenarios/index.md", {"Offline": []}]}]}
    assert not module.expand_nav(["index.md"], [])


def test_nav_labels_drop_a_trailing_parenthesis_unless_taken() -> None:
    module = explorer()
    taken: set[str] = set()
    labels = [
        module.nav_label(scenario({"id": f"x{i}", "title": title}), taken)
        for i, title in enumerate(["Rename (keep)", "Rename (drop)", "Plain"])
    ]
    assert labels == ["Rename", "Rename (drop)", "Plain"]
