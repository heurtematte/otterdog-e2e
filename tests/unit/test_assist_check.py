"""otterdog_e2e.assist.check and ``otterdog-e2e assist check``: every validation kind (scenarios and their references,
coverage matrix, known bugs, jsonnet, Python tests and their references), the changed files of git status, the offline
lint through the run_pytest seam and the exit codes."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_e2e import cli, coverage_matrix
from otterdog_e2e.assist import check
from otterdog_e2e.assist.check import Problem, check_files
from otterdog_e2e.testing.fakes import make_settings

REPO = Path(__file__).resolve().parents[2]
DESCRIPTION = " ".join(["Why this offline scenario exists, it pins the validation of a repository."] * 3)
OFFLINE = f"""\
id: O-VAL
title: A repository validates
description: {DESCRIPTION}
tags: [offline, repo]
observe: true
references:
  - pr: 790
    note: the change of the validation
    base: sha:b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8
    expected_deltas:
      - {{step: validate, kind: cli, key: validate}}
steps:
  - name: validate
    fragments:
      repositories:
        - file: ../../fragments/repo.jsonnet
    validate: {{ok: true}}
"""
LIVE = """\
id: cli.repo.x
title: A repository
tags: [repo]
steps:
  - name: create
    fragments:
      repositories:
        - "orgs.newRepo('{{ p }}-x') { description: 'x' }"
    plan:
      expect: changes
  - name: update
    fragments:
      repositories:
        - "orgs.newRepo('{{ p }}-x') { description: 'y' }"
"""
KNOWN_BUGS = """\
- id: KB-001
  title: apply exit code
  status: confirmed
  evidence: ["otterdog/operations/apply.py:1"]
  scenarios: [W-PY]
- id: KB-002
  title: fixed thing
  status: fixed
  fixed_in: 1.7.0
  evidence: ["otterdog/x.py:1"]
"""
KNOWN_ISSUES = "# Known issues\n\n### KB-001 apply\n\nStatus: **confirmed**\n\n### KB-002 x\n\nStatus: **fixed**\n"
AFTER_BEHAVIOUR = "name the behaviour, the PR goes in the references"
PYTHON_TEST = (
    "import pytest\n\n\n@pytest.mark.scenario('W-PY', references=[{'pr': 790, 'expected_deltas': [{'note': 'n'}]}])\n"
    "@pytest.mark.known_bug('KB-001')\ndef test_py():\n"
    '    """W-PY."""\n'
)


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A checkout with a valid offline and live scenario, a shared fragment, known bugs and their doc and a Python e2e
    test (the offline scenario and the Python test reference #790)."""
    root = tmp_path / "project"
    for directory in (
        "scenarios/offline/repo",
        "scenarios/cli/repo",
        "scenarios/fragments",
        "tests/webapp",
        "tests/offline",
        "docs",
    ):
        (root / directory).mkdir(parents=True)
    (root / "pyproject.toml").write_text('[project]\nname = "otterdog-e2e"\n')
    (root / "scenarios" / "offline" / "repo" / "val.yaml").write_text(OFFLINE)
    (root / "scenarios" / "cli" / "repo" / "repo.yaml").write_text(LIVE)
    (root / "scenarios" / "fragments" / "repo.jsonnet").write_text("orgs.newRepo('{{ p }}-r') { description: 'r' }\n")
    (root / "scenarios" / "fragments" / "unused.jsonnet").write_text("{}\n")
    (root / "scenarios" / "known_bugs.yaml").write_text(KNOWN_BUGS)
    (root / "docs" / "known-issues.md").write_text(KNOWN_ISSUES)
    (root / "tests" / "webapp" / "test_py.py").write_text(PYTHON_TEST)
    return root


def write(root: Path, relative: str, text: str) -> Path:
    """Write a file of the checkout."""
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def problems_of(root: Path, *relatives: str) -> list[Problem]:
    """Sorted problems of checking these files."""
    return sorted(check_files(root, [root / relative for relative in relatives]).problems)


def messages(root: Path, *relatives: str) -> list[tuple[str, str]]:
    """(location, message) of the problems."""
    return [(problem.location, problem.message) for problem in problems_of(root, *relatives)]


def test_the_fixture_checkout_is_clean(project: Path) -> None:
    """Valid scenarios (references included), known bugs and Python test: no problem; the live scenario is to be
    linted."""
    result = check_files(
        project,
        [
            project / path
            for path in (
                "scenarios/offline/repo/val.yaml",
                "scenarios/cli/repo/repo.yaml",
                "scenarios/known_bugs.yaml",
                "tests/webapp/test_py.py",
            )
        ],
    )
    assert result.problems == [] and result.ok
    assert result.live == {"cli.repo.x": "scenarios/cli/repo/repo.yaml"}
    kinds = {item["path"]: item["kind"] for item in result.files}
    assert kinds == {
        "scenarios/offline/repo/val.yaml": "scenario",
        "scenarios/cli/repo/repo.yaml": "scenario",
        "scenarios/known_bugs.yaml": "known-bugs",
        "tests/webapp/test_py.py": "python",
    }


def test_the_repository_files_are_clean() -> None:
    """The real scenarios (those with references among them), known bugs and Python tests with references of this
    repository have no problem."""
    paths = sorted(
        [
            *(path for tier in ("offline", "cli", "enterprise") for path in REPO.glob(f"scenarios/{tier}/*/*.yaml")),
            REPO / "scenarios" / "known_bugs.yaml",
            REPO / "tests" / "webapp" / "test_stale_status.py",
            REPO / "tests" / "webapp" / "test_check_merge.py",
        ]
    )
    assert check_files(REPO, paths).problems == []


# --- references --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (OFFLINE.replace("note: the change", "typo: 1\n    note: the change"), ("references[0]", "unknown key(s)")),
        (
            OFFLINE.replace("base: sha:b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8", f"base: pr:12@{'a' * 40}"),
            ("references[0].base", "is a pr spec, a base is one of"),
        ),
        (
            OFFLINE.replace("base: sha:b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8", "base: 'nonsense:x'"),
            ("references[0].base", "is not a SUT spec"),
        ),
        (
            OFFLINE.replace("{step: validate, kind", "{step: plan, kind"),
            ("references[0].expected_deltas[0].step", "'plan' matches no step of the scenario"),
        ),
        (OFFLINE.replace("  - pr: 790\n", "  - pr: 790\n    change: x\n"), ("references[0]", "exactly one of")),
        (
            OFFLINE.replace("base: sha:b5f7bb1c79ad29cdcde8506f5fa7ec4c070ffda8", "base: tag:v1.6.0"),
            ("references", "#790: conflicting 'base' of its references ('sha:b5f7bb1"),
        ),
        (OFFLINE.replace("id: O-VAL", "id: O-VAL-790"), ("id", "carries the number of a PR it references (#790)")),
        (OFFLINE.replace("id: O-VAL", "id: O-VAL-791"), ("id", "carries a PR-like number (791)")),
    ],
)
def test_reference_problems(project: Path, text: str, expected: tuple[str, str]) -> None:
    """The references of a scenario: the model's rules (with their key path), the consistency of a change across
    the repository, an id naming the behaviour (never a PR number)."""
    other = OFFLINE.replace("id: O-VAL", "id: O-VAL-OTHER")
    write(project, "scenarios/offline/repo/other.yaml", other)  # the same change, base sha:b5f7bb1...
    write(project, "scenarios/offline/repo/val.yaml", text)
    found = messages(project, "scenarios/offline/repo/val.yaml")
    assert len(found) == 1 and found[0][0] == expected[0] and expected[1] in found[0][1], found


def test_a_file_name_carrying_a_referenced_pr(project: Path) -> None:
    """A scenario file named after a PR it references is a problem (the file names the behaviour)."""
    (project / "scenarios/offline/repo/val.yaml").rename(project / "scenarios/offline/repo/val-790.yaml")
    assert messages(project, "scenarios/offline/repo/val-790.yaml") == [
        ("file name", f"'val-790' carries the number of a PR it references (#790): {AFTER_BEHAVIOUR}")
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (PYTHON_TEST.replace("'note': 'n'", "'step': 's'"), ("references", "a Python test has no steps")),
        (PYTHON_TEST.replace("references=[", "references=REFS + ["), ("references", "must be literals")),
        (PYTHON_TEST.replace("'W-PY'", "'W-PY-790'"), ("W-PY-790", "carries the number of a PR it references")),
        (
            PYTHON_TEST.replace("{'pr': 790,", "{'pr': 790, 'base': 'tag:v1.6.0',"),
            ("references", "#790: conflicting 'base' of its references"),
        ),
    ],
)
def test_python_reference_problems(project: Path, text: str, expected: tuple[str, str]) -> None:
    """The references of the scenario markers of a Python test: literals, valid entries, consistent with the
    repository; their scenario ids carry no PR number."""
    write(project, "tests/webapp/test_py.py", text)
    found = messages(project, "tests/webapp/test_py.py")
    assert len(found) == 1 and found[0][0] == expected[0] and expected[1] in found[0][1], found


# --- scenarios ---------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("relative", "text", "expected"),
    [
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("observe: true", "observe: true\nsetps: []"),
            ("scenario", "unknown key(s) ['setps']"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("validate: {ok: true}", "plan: {expect: changes}"),
            ("steps[0].plan", "offline plan expectations are checked by local-plan"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("../../fragments/repo.jsonnet", "../../fragments/missing.jsonnet"),
            ("steps[0].fragments.repositories[0].file", "'../../fragments/missing.jsonnet' not found"),
        ),
        (
            "scenarios/offline/repo/dup.yaml",
            OFFLINE,
            ("id", "duplicate scenario id 'O-VAL' (also in scenarios/offline/repo/val.yaml)"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("observe: true", "observe: true\nknown_bug: KB-404"),
            ("known_bug", "scenario 'O-VAL' declares unknown known bug 'KB-404'"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("observe: true", "observe: true\nknown_bug: KB-002"),
            ("known_bug", "KB-002 does not list 'O-VAL' in its scenarios"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace(f"description: {DESCRIPTION}", "description: too short"),
            ("description", "describe why the scenario exists (20 words)"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("tags: [offline, repo]", "tags: [repo, offline]"),
            ("tags", "the tags of an offline scenario start with 'offline'"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("tags: [offline, repo]", "tags: [offline, repo, repos]"),
            ("tags", "unknown tag(s) ['repos']"),
        ),
        (
            "scenarios/offline/repo/val.yaml",
            OFFLINE.replace("observe: true", "observe: false"),
            ("observe", "offline scenarios set observe: true"),
        ),
        (
            "scenarios/cli/repo/repo.yaml",
            LIVE.replace("id: cli.repo.x", "id: repo.x"),
            ("id", "ids of scenarios/cli/ start with 'cli.'"),
        ),
        (
            "scenarios/cli/cli/repo.yaml",
            LIVE.replace("id: cli.repo.x", "id: cli.repo.y").replace("tags: [repo]", "tags: [cli]"),
            ("tags", "no model area tag"),
        ),
        (
            "scenarios/cli/repo/repo.yaml",
            LIVE.replace("tags: [repo]", "tags: [repo]\nmin_plan: enterprise"),
            ("min_plan", "scenarios/enterprise need min_plan enterprise"),
        ),
        (
            "scenarios/cli/repo.yaml",
            LIVE.replace("id: cli.repo.x", "id: cli.repo.y"),
            ("file", "file it in a domain directory scenarios/<tier>/<domain>/"),
        ),
        (
            "scenarios/cli/teams/repo.yaml",
            LIVE.replace("id: cli.repo.x", "id: cli.repo.y"),
            ("file", "a scenario of the 'teams' domain carries the 'teams' tag"),
        ),
        (
            "scenarios/cli/repo/sub/repo.yaml",
            LIVE.replace("id: cli.repo.x", "id: cli.repo.y"),
            ("file", "no subdirectory below the domain directory 'repo'"),
        ),
        (
            "scenarios/offline/validation/val.yaml",
            OFFLINE.replace("id: O-VAL", "id: O-VAL-OTHER"),
            ("file", "'validation' is not a domain directory"),
        ),
    ],
)
def test_scenario_problems(project: Path, relative: str, text: str, expected: tuple[str, str]) -> None:
    """The model's errors (with their key path), a duplicate id, known-bug links and the conventions."""
    write(project, relative, text)
    found = messages(project, relative)
    assert len(found) == 1 and found[0][0] == expected[0] and expected[1] in found[0][1], found


def test_live_known_bug_conventions_and_step_bugs(project: Path) -> None:
    """A live scenario linked to a bug: listed by it, tagged known-bug, not P0; a step-level bug must not list it."""
    text = LIVE.replace("tags: [repo]", "tags: [repo]\nknown_bug: KB-001\npriority: P0")
    write(project, "scenarios/cli/repo/repo.yaml", text)
    assert messages(project, "scenarios/cli/repo/repo.yaml") == [
        ("known_bug", "KB-001 does not list 'cli.repo.x' in its scenarios"),
        ("known_bug", "a scenario linked to a known bug has the 'known-bug' tag and is not P0"),
    ]
    write(
        project, "scenarios/known_bugs.yaml", KNOWN_BUGS.replace("scenarios: [W-PY]", "scenarios: [W-PY, cli.repo.x]")
    )
    step_bug = LIVE.replace("  - name: update\n", "  - name: update\n    known_bug: KB-001\n")
    write(project, "scenarios/cli/repo/repo.yaml", step_bug)
    (found,) = messages(project, "scenarios/cli/repo/repo.yaml")
    assert found[0] == "known_bug" and "whose step 'update' declares it: the whole item would xfail" in found[1]


def test_regression_conventions(project: Path) -> None:
    """A regression (in the domain of the feature it guards) references the PR(s) of its fix and links them, has the
    regression tag, an id starting with 'regression.' and a file name naming the behaviour (never the PR number), and
    the known-bad version."""
    references = "tags: [repo]\nreferences: [{pr: 41}]"
    text = LIVE.replace("id: cli.repo.x", "id: regression.41-x").replace("tags: [repo]", references)
    write(project, "scenarios/cli/repo/41-x.yaml", text)
    assert messages(project, "scenarios/cli/repo/41-x.yaml") == [
        ("description", "link the upstream otterdog/pull/41 (or issues/41)"),
        ("description", "state the known-bad version ('Known-bad: ...')"),
        ("file name", f"'41-x' carries the number of a PR it references (#41): {AFTER_BEHAVIOUR}"),
        ("id", f"'regression.41-x' carries the number of a PR it references (#41): {AFTER_BEHAVIOUR}"),
        ("tags", "a regression has the 'regression' tag"),
    ]
    good = LIVE.replace("id: cli.repo.x", "id: regression.renamed-x").replace(
        "tags: [repo]", "tags: [repo, regression]\nreferences: [{pr: 41, note: the fix}]"
    )
    good = good.replace(
        "title: A repository",
        "title: A repository\ndescription: 'https://github.com/eclipse-csi/otterdog/pull/41 Known-bad: v1.0.0'",
    )
    write(project, "scenarios/cli/repo/renamed-x.yaml", good)
    assert messages(project, "scenarios/cli/repo/renamed-x.yaml") == []
    write(project, "scenarios/cli/repo/renamed-x.yaml", LIVE.replace("id: cli.repo.x", "id: regression.renamed-x"))
    assert messages(project, "scenarios/cli/repo/renamed-x.yaml") == [
        ("references", "a regression references the PR(s) of its fix: references: [{pr: <n>}]")
    ]
    write(project, "scenarios/cli/repo/renamed-x.yaml", good.replace("id: regression.renamed-x", "id: cli.renamed-x"))
    assert messages(project, "scenarios/cli/repo/renamed-x.yaml") == [
        ("id", "ids of regressions start with 'regression.'")
    ]


# --- coverage matrix ----------------------------------------------------------------------------------------------------
def test_coverage_schema_problems_name_the_feature(project: Path) -> None:
    """Schema problems of coverage.yaml; feature problems carry the feature id as location."""
    tiers = dict.fromkeys(coverage_matrix.TIERS, "x")
    data = {
        "schema_version": 1,
        "title": "t",
        "description": "d",
        "otterdog": {},
        "areas": [{"id": "a", "title": "A"}],
        "tiers": tiers,
        "operations": {"validate": "v"},
        "models": [],
        "findings": [],
        "features": [
            {
                "id": "a.b",
                "area": "nope",
                "title": "t",
                "source": ["otterdog/x.py:1"],
                "operations": ["validate"],
                "min_plan": "free",
                "tier": "offline",
                "ui_only": False,
                "priority": "P0",
                "status": "gap",
                "covered_by": [],
                "gap_outline": {"scenario": "s", "steps": ["s"], "assertions": ["a"], "needs": ["n"]},
            }
        ],
    }
    write(project, "scenarios/coverage.yaml", json.dumps(data))
    assert messages(project, "scenarios/coverage.yaml") == [("feature a.b", "unknown area 'nope'")]
    write(project, "scenarios/coverage.yaml", "schema_version: 1\n")
    assert ("", "missing top-level key 'areas'") in messages(project, "scenarios/coverage.yaml")
    write(project, "scenarios/coverage.yaml", "a: [\n")
    ((location, message),) = messages(project, "scenarios/coverage.yaml")
    assert location == "" and "cannot be read" in message


def test_coverage_of_the_repository_and_a_stale_doc(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The repository's matrix passes every check; a stale generated doc is a problem naming the regeneration."""
    coverage = REPO / "scenarios" / "coverage.yaml"
    assert check_files(REPO, [coverage]).problems == []
    stale = tmp_path / "coverage-matrix.md"
    stale.write_text("# old\n")
    monkeypatch.setattr(coverage_matrix, "DOC_FILE", stale)
    (problem,) = check_files(REPO, [coverage]).problems
    assert problem.file == "scenarios/coverage.yaml" and problem.message.endswith(
        f"is stale, regenerate it: {coverage_matrix.REGENERATE}"
    )


# --- known bugs, jsonnet, Python, other files ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("text", "doc", "expected"),
    [
        (
            KNOWN_BUGS.replace("KB-001", "KB-009"),
            KNOWN_ISSUES.replace("KB-001", "KB-009"),
            ("", "keep the entries sorted by id"),
        ),
        (KNOWN_BUGS.replace("  fixed_in: 1.7.0\n", ""), KNOWN_ISSUES, ("KB-002", "status fixed goes with fixed_in")),
        (KNOWN_BUGS.replace('  evidence: ["otterdog/x.py:1"]\n', ""), KNOWN_ISSUES, ("KB-002", "no evidence")),
        (
            KNOWN_BUGS.replace("scenarios: [W-PY]", "scenarios: [W-PY, O-NOPE]"),
            KNOWN_ISSUES,
            ("KB-001", "KB-001 lists unknown scenario 'O-NOPE'"),
        ),
        (KNOWN_BUGS, KNOWN_ISSUES.replace("### KB-002 x", "### KB-003 x"), ("KB-002", "has no '### KB-002' section")),
        (
            KNOWN_BUGS,
            KNOWN_ISSUES.replace("**fixed**", "**confirmed**"),
            ("KB-002", "does not state 'Status: **fixed**'"),
        ),
        ("- id: KB-1\n", KNOWN_ISSUES, ("", "does not match ^KB-[0-9]{3,}$")),
    ],
)
def test_known_bugs_problems(project: Path, text: str, doc: str, expected: tuple[str, str]) -> None:
    """known_bugs.yaml: loads, order, fixed_in, evidence, listed scenarios (YAML or Python ids), its doc sections."""
    write(project, "scenarios/known_bugs.yaml", text)
    write(project, "docs/known-issues.md", doc)
    found = messages(project, "scenarios/known_bugs.yaml")
    assert len(found) == 1 and found[0][0] == expected[0] and expected[1] in found[0][1], found


def test_a_broken_known_bugs_file_is_reported_once_for_scenarios(project: Path) -> None:
    """A scenario check cannot verify its bugs with an unreadable registry: one problem on the registry."""
    write(project, "scenarios/known_bugs.yaml", "- id: nope\n")
    assert [problem.file for problem in problems_of(project, "scenarios/offline/repo/val.yaml")] == [
        "scenarios/known_bugs.yaml"
    ]


def test_jsonnet_files_check_the_scenarios_using_them(project: Path) -> None:
    """A changed fragment: the scenarios referencing it are checked; an unreferenced one is noted."""
    result = check_files(
        project, [project / "scenarios/fragments/repo.jsonnet", project / "scenarios/fragments/unused.jsonnet"]
    )
    assert {item["path"]: item["kind"] for item in result.files} == {
        "scenarios/fragments/repo.jsonnet": "jsonnet",
        "scenarios/fragments/unused.jsonnet": "jsonnet",
        "scenarios/offline/repo/val.yaml": "scenario",
    }
    assert result.problems == [] and "scenarios/fragments/unused.jsonnet: referenced by no scenario" in result.notes[0]
    write(project, "scenarios/fragments/repo.jsonnet", "orgs.newRepo('{{ p }}-r') { value: 'x' } // comment")
    (problem,) = check_files(project, [project / "scenarios/fragments/repo.jsonnet"]).problems
    assert problem.file == "scenarios/offline/repo/val.yaml" and "line comment" in problem.message


def test_python_files(project: Path) -> None:
    """Python tests parse and name existing known bugs; they are otherwise only noted (run them with pytest)."""
    write(project, "tests/webapp/test_bad.py", "def test_x(:\n    pass\n")
    assert messages(project, "tests/webapp/test_bad.py") == [("line 1", "syntax error: invalid syntax")]
    write(
        project,
        "tests/webapp/test_bug.py",
        "import pytest\n\n@pytest.mark.known_bug('KB-777')\ndef test_y():\n    pass\n",
    )
    assert messages(project, "tests/webapp/test_bug.py") == [("test_y", "known_bug marker names unknown bug 'KB-777'")]


def test_other_and_missing_files(project: Path) -> None:
    """Unsupported files are noted, missing ones are problems; each file is checked once."""
    write(project, "docs/x.md", "# x\n")
    result = check_files(
        project, [project / "docs/x.md", project / "scenarios/offline/nope.yaml", project / "docs/x.md"]
    )
    assert result.notes == ["docs/x.md: not checked (no rule for this kind of file)"]
    assert result.problems == [Problem("scenarios/offline/nope.yaml", "", "no such file")]
    assert len(result.files) == 2


@pytest.mark.parametrize(
    ("relative", "kind"),
    [
        ("scenarios/otterdog-prs/1.yaml", "scenario"),  # no PR manifest any more: a YAML file of scenarios/
        ("scenarios/coverage.yaml", "coverage"),
        ("scenarios/known_bugs.yaml", "known-bugs"),
        ("scenarios/cli/sub/x.yml", "scenario"),
        ("scenarios/lib/e2e.libsonnet", "jsonnet"),
        ("tests/cli/test_x.py", "python"),
        ("tests/unit/data/x.yaml", "other"),
        ("docs/coverage.yaml", "other"),
    ],
)
def test_file_kinds(project: Path, relative: str, kind: str) -> None:
    """File kinds by location and suffix."""
    assert check.file_kind(project / relative, project) == kind


def test_split_location() -> None:
    """Model messages starting with a key path are split; others keep no location."""
    assert check.split_location("steps[0].plan: offline plan") == ("steps[0].plan", "offline plan")
    assert check.split_location("tier 'cli' does not belong in scenarios/offline/") == (
        "",
        "tier 'cli' does not belong in scenarios/offline/",
    )


# --- git status --------------------------------------------------------------------------------------------------------
def git(root: Path, *args: str) -> None:
    """Run git in the checkout (test setup only)."""
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.invalid",
            "-c",
            "core.hooksPath=/dev/null",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=root,
        check=True,
        capture_output=True,
    )


def test_changed_files_of_git_status(project: Path) -> None:
    """Modified, added (untracked, in new directories too), renamed and deleted files under scenarios/ and tests/;
    other directories are ignored."""
    write(project, "scenarios/offline/gone.yaml", "id: O-GONE\n")
    write(project, "scenarios/offline/old-name.yaml", "id: O-OLD\n")
    git(project, "init", "-q")
    git(project, "add", "-A")
    git(project, "commit", "-q", "-m", "init")
    write(project, "scenarios/cli/repo/repo.yaml", LIVE + "# changed\n")
    write(project, "scenarios/offline/sub/new.yaml", OFFLINE)
    write(project, "docs/new.md", "# not checked\n")
    (project / "scenarios/offline/gone.yaml").unlink()
    git(project, "mv", "scenarios/offline/old-name.yaml", "scenarios/offline/new-name.yaml")
    existing, deleted = check.changed_files(project)
    assert [path.relative_to(project).as_posix() for path in existing] == [
        "scenarios/cli/repo/repo.yaml",
        "scenarios/offline/new-name.yaml",
        "scenarios/offline/sub/new.yaml",
    ]
    assert deleted == ["scenarios/offline/gone.yaml"]


def test_changed_files_outside_a_repository(tmp_path: Path) -> None:
    """Without git metadata: an error asking for the paths."""
    with pytest.raises(ValueError, match="give the paths to check"):
        check.changed_files(tmp_path)


# --- lint ---------------------------------------------------------------------------------------------------------------
def test_lint_keyword_matches_exact_ids() -> None:
    """``[<id>/`` selects the lint items of exactly that scenario."""
    assert check.lint_keyword(["cli.b", "cli.a", "cli.a"]) == "test_live_scenario_lint and ([cli.a/ or [cli.b/)"
    with pytest.raises(ValueError):
        check.lint_keyword([])


def lint_line(scenario_id: str, step: str, outcome: str, **extra: Any) -> dict[str, Any]:
    """A results.jsonl line of a lint item."""
    nodeid = f"tests/offline/test_scenario_lint.py::test_live_scenario_lint[{scenario_id}/{step}]"
    return {"nodeid": nodeid, "outcome": outcome, "when": "call", "tier": "offline", **extra}


def test_lint_result(tmp_path: Path) -> None:
    """Failed items are problems of their scenario file and step; skips and xfails are notes; a scenario without
    any item is a problem."""
    rows = [
        lint_line("cli.a", "create", "passed"),
        lint_line("cli.a", "update", "failed", failure="cli.a step 'update' (plan free): no validation error\nline 2"),
        lint_line("cli.a", "teams", "skipped", reason="not linted offline (teams fragments, newTeam)"),
        {"nodeid": "tests/offline/test_cli_basics.py::test_version", "outcome": "failed", "failure": "unrelated"},
    ]
    (tmp_path / "results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    data, problems = check.lint_result(
        tmp_path, 1, {"cli.a": "scenarios/cli/a.yaml", "cli.b": "scenarios/cli/b.yaml"}, sut="release:latest"
    )
    assert problems == [
        Problem(
            "scenarios/cli/a.yaml",
            "step update",
            "offline lint failed: cli.a step 'update' (plan free): no validation error\nline 2",
        ),
        Problem("scenarios/cli/b.yaml", "", "no lint item ran for this scenario (see the lint summary)"),
    ]
    assert data["outcomes"] == {"failed": 1, "passed": 1, "skipped": 1} and data["exit_code"] == 1 and data["ran"]
    assert data["notes"] == ["scenarios/cli/a.yaml: step teams skipped: not linted offline (teams fragments, newTeam)"]


def test_lint_result_without_results(tmp_path: Path) -> None:
    """A pytest error without results (collection, usage) is a problem naming the summary."""
    _data, problems = check.lint_result(tmp_path, 4, {}, sut="release:latest")
    assert problems == [Problem("(lint)", "", f"the lint run exited with pytest code 4, see {tmp_path / 'summary.md'}")]


# --- the command -------------------------------------------------------------------------------------------------------
@pytest.fixture
def command(project: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Settings of the checkout; run_pytest replaced: it records its arguments, prints to stdout (the command must
    keep its JSON clean) and writes the results of the lint items it is given."""
    settings = make_settings(project)
    monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: settings)
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)
    state: dict[str, Any] = {
        "calls": [],
        "rows": [lint_line("cli.repo.x", "create", "passed"), lint_line("cli.repo.x", "update", "passed")],
        "code": 0,
    }

    def run_pytest(args: list[str], *, command: str | None = None) -> int:
        """Record the call and write results.jsonl into the run directory."""
        state["calls"].append({"args": list(args), "command": command})
        print("pytest output that must not reach stdout")  # noqa: T201 - the seam prints like pytest
        run_id = next(arg.split("=", 1)[1] for arg in args if arg.startswith("--e2e-run-id="))
        run = settings.artifacts_root / run_id
        run.mkdir(parents=True)
        (run / "results.jsonl").write_text("".join(json.dumps(row) + "\n" for row in state["rows"]))
        return int(state["code"])

    monkeypatch.setattr("otterdog_e2e.cli.assist.run_pytest", run_pytest)
    state["settings"] = settings
    return state


def test_command_lints_live_scenarios(command: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """The live scenario is linted with the offline suite, -k restricted to its id, the SUT given; pytest output goes
    to stderr; exit 0 when clean (paths are relative to the working directory)."""
    monkeypatch.chdir(command["settings"].project_root)
    result = CliRunner().invoke(cli.main, ["assist", "check", "scenarios/cli/repo/repo.yaml", "--json"])
    assert result.exit_code == 0, result.output
    (call,) = command["calls"]
    root = command["settings"].project_root
    assert call["args"][0] == str(root / "tests" / "offline")
    assert "--e2e-sut=release:latest" in call["args"] and "-ktest_live_scenario_lint and ([cli.repo.x/)" in call["args"]
    assert (
        call["command"]
        == "otterdog-e2e run --suite offline --sut release:latest -k 'test_live_scenario_lint and ([cli.repo.x/)'"
    )
    data = json.loads(result.stdout)
    assert data["ok"] is True and data["lint"]["ran"] and data["lint"]["outcomes"] == {"passed": 2}
    assert data["lint"]["scenarios"] == ["cli.repo.x"] and data["lint"]["sut"] == "release:latest"
    assert "pytest output that must not reach stdout" in result.stderr


def test_command_lint_failures_exit_1(command: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A failing lint item is a problem of the scenario (exit 1), with an untrusted SUT spec passed through."""
    monkeypatch.chdir(command["settings"].project_root)
    command["rows"] = [lint_line("cli.repo.x", "create", "failed", failure="no validation error reported")]
    command["code"] = 1
    sut = f"pr:790@{'0' * 40}"
    result = CliRunner().invoke(cli.main, ["assist", "check", "scenarios/cli/repo/repo.yaml", "--sut", sut])
    assert result.exit_code == 1, result.output
    assert f"--e2e-sut={sut}" in command["calls"][0]["args"]
    assert (
        "PROBLEM scenarios/cli/repo/repo.yaml [step create]: offline lint failed: no validation error reported"
        in result.stdout
    )
    assert "PROBLEM scenarios/cli/repo/repo.yaml [step update]" not in result.stdout
    assert "FAILED: 1 problem(s)" in result.stdout


def test_command_skips_the_lint(command: dict[str, Any]) -> None:
    """--no-lint, no live scenario, or problems (an invalid scenario breaks the collection): no lint run."""
    root = command["settings"].project_root
    result = CliRunner().invoke(cli.main, ["assist", "check", str(root / "scenarios/cli/repo/repo.yaml"), "--no-lint"])
    assert result.exit_code == 0 and "lint: skipped (--no-lint)" in result.stdout
    result = CliRunner().invoke(cli.main, ["assist", "check", str(root / "scenarios/offline/repo/val.yaml")])
    assert result.exit_code == 0 and "lint: skipped (no live scenario" in result.stdout
    write(root, "scenarios/cli/repo/broken.yaml", "id: cli.broken\n")
    result = CliRunner().invoke(
        cli.main,
        ["assist", "check", str(root / "scenarios/cli/repo/repo.yaml"), str(root / "scenarios/cli/repo/broken.yaml")],
    )
    assert result.exit_code == 1 and "lint: skipped (fix the problems first" in result.stdout
    assert "PROBLEM scenarios/cli/repo/broken.yaml [scenario]: missing required key 'title'" in result.stdout
    assert command["calls"] == []


def test_command_defaults_to_the_changed_files(command: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Without paths: the files of git status (deleted ones listed); nothing changed is a clean result."""
    root = command["settings"].project_root
    monkeypatch.setattr(
        check, "changed_files", lambda project_root: ([root / "scenarios/offline/repo/val.yaml"], ["scenarios/x.yaml"])
    )
    result = CliRunner().invoke(cli.main, ["assist", "check", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.stdout)
    assert data["files"] == [
        {"path": "scenarios/offline/repo/val.yaml", "kind": "scenario"},
        {"path": "scenarios/x.yaml", "kind": "deleted"},
    ]
    monkeypatch.setattr(check, "changed_files", lambda project_root: ([], []))
    result = CliRunner().invoke(cli.main, ["assist", "check"])
    assert result.exit_code == 0 and "checked 0 file(s): none" in result.stdout


def test_command_errors(command: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """git failures are harness errors (exit 1); a rejected PYTEST_ADDOPTS is a usage error before the lint (exit 2)."""

    def broken(project_root: Path) -> None:
        """git status failed."""
        raise ValueError("cannot list the changed files (give the paths to check): not a git repository")

    monkeypatch.setattr(check, "changed_files", broken)
    result = CliRunner().invoke(cli.main, ["assist", "check"])
    assert result.exit_code == 1 and "give the paths to check" in result.output
    monkeypatch.setenv("PYTEST_ADDOPTS", "-p evil")
    root = command["settings"].project_root
    result = CliRunner().invoke(cli.main, ["assist", "check", str(root / "scenarios/cli/repo/repo.yaml")])
    assert result.exit_code == 2 and "is not allowed" in result.output and command["calls"] == []
