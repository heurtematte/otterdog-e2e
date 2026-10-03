"""otterdog_e2e.inject: file references (paths, containment, reading), SourceText, rendering with the file's rules,
the ad-hoc scenarios of ``otterdog-e2e inject`` and the result they report."""

from __future__ import annotations

import copy
import json
import pickle
from pathlib import Path
from typing import Any

import jinja2
import jinja2.sandbox
import pytest
import yaml

from otterdog_e2e import inject
from otterdog_e2e.inject import (
    MAX_FILE_BYTES,
    FileContext,
    InjectError,
    InjectRequest,
    JsonnetFile,
    SourceText,
    adhoc_document,
    adhoc_mode,
    adhoc_result,
    config_files,
    foreign_additions,
    jinja_error_line,
    load_source,
    parse_assignment,
    parse_variables,
    plan_only,
    plan_summary,
    read_adhoc_result,
    read_jsonnet,
    record_adhoc_run,
    render_source,
    result_lines,
    validation_summary,
    write_adhoc_scenario,
)
from otterdog_e2e.otterdog.runner import CliResult
from otterdog_e2e.scenarios.engine import ScenarioOutcome, StepOutcome
from otterdog_e2e.scenarios.model import ScenarioError, load_adhoc_scenario, load_scenario

DATA = Path(__file__).parent / "data"


def make_project(root: Path) -> Path:
    """An otterdog-e2e project root (pyproject.toml with the project name) with a scenarios/cli directory."""
    root.mkdir(parents=True, exist_ok=True)
    (root / "pyproject.toml").write_text('[project]\nname = "otterdog-e2e"\n')
    (root / "scenarios" / "cli").mkdir(parents=True)
    return root


def write(path: Path, text: str) -> Path:
    """Write ``text`` to ``path`` (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def environment() -> jinja2.Environment:
    """The scenario model's Jinja environment (sandboxed, strict, keeps the trailing newline)."""
    return jinja2.sandbox.SandboxedEnvironment(
        undefined=jinja2.StrictUndefined, keep_trailing_newline=True, autoescape=False
    )


def source(text: str, *, raw: bool = False, variables: dict[str, Any] | None = None) -> SourceText:
    """A SourceText of a fragment file (nothing is read)."""
    origin = JsonnetFile("fragments.repositories[0]", Path("/x/repo.jsonnet"), "repo.jsonnet", raw=raw)
    if variables is not None:
        origin = JsonnetFile(origin.label, origin.path, origin.display, raw=raw, vars=variables)
    return SourceText(text, origin)


def cli_result(command: str, sample: str, exit_code: int = 0) -> CliResult:
    """A CliResult of ``otterdog <command>`` whose stdout is a sample of tests/unit/data."""
    return CliResult(["otterdog", command], exit_code, (DATA / sample).read_text(), "", 0.1, Path("/nonexistent"))


def cli_result_text(command: str, stdout: str, exit_code: int = 0) -> CliResult:
    """A CliResult of ``otterdog <command>`` with the given stdout."""
    return CliResult(["otterdog", command], exit_code, stdout, "", 0.1, Path("/nonexistent"))


# --- file references --------------------------------------------------------------------------------------------------
def test_relative_paths_resolve_inside_the_project(tmp_path: Path) -> None:
    """Paths are relative to the scenario directory; the display path is relative to the project root."""
    root = make_project(tmp_path / "proj")
    write(root / "scenarios" / "fragments" / "repo.jsonnet", "orgs.newRepo('x')\n")
    files = FileContext(root / "scenarios" / "cli")
    path, display = files.resolve("../fragments/repo.jsonnet")
    assert files.root == root.resolve() and path == (root / "scenarios/fragments/repo.jsonnet").resolve()
    assert display == "scenarios/fragments/repo.jsonnet"


def test_absolute_missing_and_escaping_paths_are_refused(tmp_path: Path) -> None:
    """Scenario files never name absolute paths, missing files or files outside the project (.. or symlinks)."""
    root = make_project(tmp_path / "proj")
    outside = write(tmp_path / "outside.jsonnet", "{}\n")
    (root / "scenarios" / "cli" / "link.jsonnet").symlink_to(outside)
    files = FileContext(root / "scenarios" / "cli")
    with pytest.raises(InjectError, match="is absolute"):
        files.resolve(str(outside))
    with pytest.raises(InjectError, match="not found"):
        files.resolve("../fragments/missing.jsonnet")
    with pytest.raises(InjectError, match=r"outside .*: files must stay inside the project"):
        files.resolve("../../../outside.jsonnet")
    with pytest.raises(InjectError, match="outside"):
        files.resolve("link.jsonnet")
    with pytest.raises(InjectError, match="empty string"):
        files.resolve("  ")


def test_outside_a_project_the_scenario_directory_is_the_root(tmp_path: Path) -> None:
    """A scenario outside any otterdog-e2e project may only name files below its own directory."""
    write(tmp_path / "loose" / "ok.jsonnet", "{}\n")
    write(tmp_path / "other.jsonnet", "{}\n")
    files = FileContext(tmp_path / "loose")
    assert files.root == (tmp_path / "loose").resolve() and files.resolve("ok.jsonnet")[1] == "ok.jsonnet"
    with pytest.raises(InjectError, match="outside"):
        files.resolve("../other.jsonnet")


def test_external_contexts_accept_any_file(tmp_path: Path) -> None:
    """Ad-hoc scenarios (otterdog-e2e inject) name user files by absolute path; messages show that path."""
    user = write(tmp_path / "home" / "me" / "repo.jsonnet", "{}\n")
    files = FileContext(tmp_path / "scratch", external=True)
    assert files.resolve(str(user)) == (user.resolve(), str(user.resolve()))
    with pytest.raises(InjectError, match="not found"):
        files.resolve(str(tmp_path / "missing.jsonnet"))


def test_read_rules(tmp_path: Path) -> None:
    """Regular, non-empty UTF-8 files of at most MAX_FILE_BYTES."""
    with pytest.raises(InjectError, match="is empty"):
        read_jsonnet(write(tmp_path / "empty.jsonnet", " \n"), "empty.jsonnet")
    with pytest.raises(InjectError, match="not a regular file"):
        read_jsonnet(tmp_path, "dir")
    big = write(tmp_path / "big.jsonnet", "x" * (MAX_FILE_BYTES + 1))
    with pytest.raises(InjectError, match="more than"):
        read_jsonnet(big, "big.jsonnet")
    latin = tmp_path / "latin.jsonnet"
    latin.write_bytes(b"{ a: '\xe9' }")
    with pytest.raises(InjectError, match="not UTF-8"):
        read_jsonnet(latin, "latin.jsonnet")
    assert read_jsonnet(write(tmp_path / "ok.jsonnet", "{}\n"), "ok.jsonnet") == "{}\n"


def test_load_source_keeps_the_reference(tmp_path: Path) -> None:
    """load_source reads the file once and records label, role, raw and vars in the origin."""
    root = make_project(tmp_path / "proj")
    write(root / "scenarios" / "lib" / "e2e.libsonnet", "{ f(x):: x }\n")
    text = load_source(
        "../lib/e2e.libsonnet",
        FileContext(root / "scenarios" / "cli"),
        label="libraries.e2e",
        role="library",
        variables={"a": 1},
    )
    assert text == "{ f(x):: x }\n" and text.origin.role == "library" and text.origin.vars == {"a": 1}
    assert text.origin.location(3) == "libraries.e2e (scenarios/lib/e2e.libsonnet:3)" and not text.rendered
    with pytest.raises(ValueError, match="unknown role"):
        load_source("../lib/e2e.libsonnet", FileContext(root / "scenarios" / "cli"), label="x", role="snippet")


# --- SourceText -------------------------------------------------------------------------------------------------------
def test_source_text_is_a_str_that_keeps_its_origin() -> None:
    """Equal (and hashed) like its text, immutable for copy/deepcopy, origin kept through pickling."""
    text = source("orgs.newRepo('x')")
    assert isinstance(text, str) and text == "orgs.newRepo('x')" and hash(text) == hash("orgs.newRepo('x')")
    assert copy.copy(text) is text and copy.deepcopy([text])[0] is text
    restored = pickle.loads(pickle.dumps(text))  # noqa: S301 - our own bytes
    assert restored == text and restored.origin == text.origin and restored.rendered is False
    assert type(str(text)) is str and json.dumps([text]) == "[\"orgs.newRepo('x')\"]"


# --- rendering --------------------------------------------------------------------------------------------------------
def test_render_source_with_vars_and_raw() -> None:
    """vars are rendered with the scenario variables first, then the text with both; raw files are never rendered;
    a rendered text is never rendered again."""
    text = source("orgs.newRepo('{{ name }}') { d: '{{ p }}' }\n", variables={"name": "{{ p }}-x"})
    rendered = render_source(environment(), text, {"p": "e2e-t3c7z8a5"})
    assert rendered == "orgs.newRepo('e2e-t3c7z8a5-x') { d: 'e2e-t3c7z8a5' }\n" and rendered.rendered
    assert rendered.origin is text.origin and render_source(environment(), rendered, {}) is rendered
    raw = render_source(environment(), source("{ a: '{{ p }}' }", raw=True), {"p": "x"})
    assert raw == "{ a: '{{ p }}' }" and raw.rendered
    plain = source("{ a: 1 }")
    assert render_source(environment(), plain, {}) == "{ a: 1 }"  # no Jinja markup: unchanged
    nested = source("{{ items | tojson }}", variables={"items": ["{{ p }}", {"k": "{{ p }}"}]})
    assert render_source(environment(), nested, {"p": "v"}) == '["v", {"k": "v"}]'


def test_render_errors_name_the_file_and_line() -> None:
    """Undefined variables or attributes at run time are InjectErrors with ``<file>:<line>``."""
    text = source("{\n  a: 1,\n  b: '{{ teams.missing }}',\n}\n")
    with pytest.raises(InjectError, match=r"fragments\.repositories\[0\] \(repo\.jsonnet:3\): cannot render"):
        render_source(environment(), text, {"teams": {}})
    bad_vars = source("{}", variables={"x": "{{ nope }}"})
    with pytest.raises(InjectError, match=r"cannot render vars\.x"):
        render_source(environment(), bad_vars, {})


def test_jinja_error_line() -> None:
    """Syntax errors carry their line; runtime errors are found in the template frames of the traceback."""
    with pytest.raises(jinja2.TemplateSyntaxError) as syntax:
        environment().parse("a\nb {{ x }\n")
    assert jinja_error_line(syntax.value) == 2
    with pytest.raises(jinja2.UndefinedError) as runtime:
        environment().from_string("a\nb\n{{ x.y }}").render(x={})
    assert jinja_error_line(runtime.value) == 3
    assert jinja_error_line(ValueError("no template")) is None


# --- ad-hoc scenarios ---------------------------------------------------------------------------------------------
def test_offline_document_defaults(tmp_path: Path) -> None:
    """Offline: validate must succeed, local-plan against the bare org (base_fragments {}), nothing is expected of
    the plan; the files are absolute references."""
    fragment = write(tmp_path / "repo.jsonnet", "orgs.newRepo('{{ p }}-x')\n")
    document = adhoc_document(InjectRequest(fragments=[("repositories", fragment)]))
    assert (document["id"], document["tier"], document["tags"]) == ("adhoc.inject", "offline", ["adhoc"])
    (step,) = document["steps"]
    assert step["fragments"] == {"repositories": [{"file": str(fragment.resolve())}]}
    assert step["base_fragments"] == {} and step["validate"] == {"ok": True} and step["plan"] == {"expect": "any"}
    assert "apply" not in step and "org_level" not in document and "libraries" not in document


def test_offline_document_with_libraries_overlays_config_and_base(tmp_path: Path) -> None:
    """Libraries are scenario-level, overlays and config/base_config step-level; variables become the scenario's."""
    files = {name: write(tmp_path / name, "{}\n") for name in ("lib.libsonnet", "o.jsonnet", "c.jsonnet", "b.jsonnet")}
    request = InjectRequest(
        libraries=[("e2e", files["lib.libsonnet"])],
        overlays=[files["o.jsonnet"]],
        config=files["c.jsonnet"],
        base=files["b.jsonnet"],
        variables={"plan": "team", "label": 3},
    )
    document = adhoc_document(request)
    (step,) = document["steps"]
    assert document["libraries"] == {"e2e": {"file": str(files["lib.libsonnet"])}}
    assert document["variables"] == {"plan": "team", "label": 3}
    assert step["overlay"] == [{"file": str(files["o.jsonnet"])}] and step["config"] == {
        "file": str(files["c.jsonnet"])
    }
    assert step["base_config"] == {"file": str(files["b.jsonnet"])} and "base_fragments" not in step


@pytest.mark.parametrize(
    ("apply", "keep", "expected"),
    [
        (False, False, ({"expect": "any"}, None, False, "none")),
        (True, False, ({"expect": "changes"}, {"expect": "ok"}, True, "auto")),
        (True, True, ({"expect": "changes"}, {"expect": "ok"}, True, "none")),
    ],
)
def test_live_documents(tmp_path: Path, apply: bool, keep: bool, expected: tuple[Any, ...]) -> None:
    """Live injections are org_level cli scenarios: plan-only (no apply, no converge, no cleanup) or apply (plan
    expecting changes, apply, converge, cleanup unless keep)."""
    fragment = write(tmp_path / "repo.jsonnet", "orgs.newRepo('{{ p }}-x')\n")
    request = InjectRequest(fragments=[("repositories", fragment)], live=True, apply=apply, keep=keep)
    document = adhoc_document(request)
    (step,) = document["steps"]
    assert document["tier"] == "cli" and document["org_level"] is True and "base_fragments" not in step
    assert (step["plan"], step["apply"], step["converge"], document["cleanup"]) == expected
    assert request.mode == ("live-apply" if apply else "live-plan")


def test_written_scenario_loads_with_external_files(tmp_path: Path) -> None:
    """write_adhoc_scenario writes a private YAML file that load_adhoc_scenario accepts (files anywhere), while the
    project loader refuses its absolute paths; every content rule still applies."""
    library = write(tmp_path / "user" / "lib.libsonnet", "{ repo(name):: orgs.newRepo(name) }\n")
    fragment = write(tmp_path / "user" / "repo.jsonnet", "e2e.repo('{{ p }}-x')\n")
    request = InjectRequest(fragments=[("repositories", fragment)], libraries=[("e2e", library)])
    path = write_adhoc_scenario(request, tmp_path / "scratch" / "adhoc")
    assert path.stat().st_mode & 0o777 == 0o600 and path.read_text().startswith("# generated by otterdog-e2e inject")
    scenario = load_adhoc_scenario(path)
    (step,) = scenario.steps
    assert scenario.id == "adhoc.inject" and adhoc_mode(scenario) == "offline" and step.base_fragments is not None
    assert isinstance(step.fragments.repositories[0], SourceText)
    assert step.fragments.repositories[0].origin.display == str(fragment.resolve())
    assert list(step.fragments.libraries) == ["e2e"] and list(step.base_fragments.libraries) == ["e2e"]
    with pytest.raises(ScenarioError, match="is absolute"):
        load_scenario(path)
    write(fragment, "orgs.newRepo('{{ p }}-x') { secrets: [orgs.newRepoSecret('S') { value: 'real' }] }\n")
    with pytest.raises(ScenarioError, match=r"repo\.jsonnet:1\): value is not a dummy value"):
        load_adhoc_scenario(write_adhoc_scenario(request, tmp_path / "scratch" / "adhoc"))


def test_adhoc_document_round_trips_through_yaml(tmp_path: Path) -> None:
    """The written YAML is the document (plus the header comment)."""
    fragment = write(tmp_path / "v.jsonnet", "orgs.newOrgVariable('{{ P }}_V') { value: 'x' }\n")
    request = InjectRequest(fragments=[("variables", fragment)], live=True)
    path = write_adhoc_scenario(request, tmp_path / "adhoc")
    assert yaml.safe_load(path.read_text()) == adhoc_document(request)


# --- results --------------------------------------------------------------------------------------------------------
def test_plan_and_validation_summaries() -> None:
    """Plan: line, counts and object headers of a local-plan; outcome and counts of a validate."""
    plan = plan_summary(cli_result("local-plan", "local-plan-add.txt"))
    assert plan["summary"] is not None and plan["summary"].startswith("Plan: ")
    assert plan["objects"] and all(not header.endswith("{") for header in plan["objects"])
    assert plan["counts"]["add"] == len([h for h in plan["objects"] if h.startswith("+ add")])
    validation = validation_summary(cli_result("validate", "validate-ok.txt"))
    assert validation["ok"] is True and validation["errors"] == 0
    errors = validation_summary(cli_result("validate", "validate-errors.txt", exit_code=1))
    assert errors["ok"] is False and errors["errors"] and errors["messages"]


def outcome_with_results() -> ScenarioOutcome:
    """A failed injection outcome with validate and local-plan results."""
    step = StepOutcome("inject")
    step.results["validate"] = cli_result("validate", "validate-errors.txt", exit_code=1)
    step.results["local-plan"] = cli_result("local-plan", "local-plan-add.txt")
    step.failed_phase = "validate"
    return ScenarioOutcome("adhoc.inject", steps=[step], failures=["step 'inject' validate: expected ..."])


def test_adhoc_result_and_lines(tmp_path: Path) -> None:
    """result.json holds the exported configs, step summaries and failures; result_lines prints them."""
    result = adhoc_result(
        outcome_with_results(), mode="offline", config=tmp_path / "o.jsonnet.txt", base_config=None, error=None
    )
    assert result["mode"] == "offline" and result["failures"] == ["step 'inject' validate: expected ..."]
    lines = result_lines(result)
    assert lines[0] == f"rendered config: {tmp_path / 'o.jsonnet.txt'}"
    assert any(line.startswith("validate: failed (") for line in lines)
    assert any(line.startswith("local-plan: Plan: ") for line in lines)
    assert any(line.startswith("  + add ") for line in lines)
    assert adhoc_result(None, mode="live-plan", config=None, base_config=None, error="boom")["steps"] == []


def test_apply_summary_lines() -> None:
    """A live apply reports the Executed plan counts (and its failed patches)."""
    step = StepOutcome("inject")
    step.results["apply"] = cli_result("apply", "apply-executed.txt")
    outcome = ScenarioOutcome("adhoc.inject", steps=[step])
    lines = result_lines(adhoc_result(outcome, mode="live-apply", config=None, base_config=None))
    assert len(lines) == 1 and lines[0].startswith("apply: ") and lines[0].endswith("(exit code 0)")
    assert "added" in lines[0] or "no changes" in lines[0]


class ExportingWorkspace:
    """ConfigWorkspace stand-in: export_to writes an org config and its -BASE copy."""

    def export_to(self, artifacts_dir: Path) -> None:
        """Write the exported copies."""
        write(artifacts_dir / "e2e-offline.jsonnet.txt", "{}\n")
        write(artifacts_dir / "e2e-offline.jsonnet-BASE.txt", "{}\n")


def test_record_adhoc_run(tmp_path: Path) -> None:
    """The workspace export, a copy of the scenario and result.json land in the adhoc artifacts directory."""
    fragment = write(tmp_path / "repo.jsonnet", "orgs.newRepo('{{ p }}-x')\n")
    scenario = load_adhoc_scenario(
        write_adhoc_scenario(InjectRequest(fragments=[("repositories", fragment)]), tmp_path / "scratch")
    )
    directory = tmp_path / "artifacts" / "adhoc"
    path = record_adhoc_run(
        directory,
        scenario=scenario,
        workspace=ExportingWorkspace(),  # type: ignore[arg-type]
        outcome=outcome_with_results(),
    )
    result = read_adhoc_result(directory)
    assert path == directory / inject.ADHOC_RESULT_FILE and result is not None
    assert result["config"] == str(directory / "workspace" / "e2e-offline.jsonnet.txt")
    assert result["base_config"] == str(directory / "workspace" / "e2e-offline.jsonnet-BASE.txt")
    assert (directory / "scenario.yaml.txt").read_text().startswith("# generated by otterdog-e2e inject")
    assert read_adhoc_result(tmp_path / "nothing") is None
    assert config_files(tmp_path / "nothing") == (None, None)


def test_live_apply_preview(tmp_path: Path) -> None:
    """plan_only keeps validate and plan, drops apply, state, converge and cleanup; foreign_additions lists the
    added objects without the run's id (the gate before a live apply)."""
    fragment = write(tmp_path / "repo.jsonnet", "orgs.newRepo('{{ p }}-x')\n")
    request = InjectRequest(fragments=[("repositories", fragment)], live=True, apply=True)
    scenario = load_adhoc_scenario(write_adhoc_scenario(request, tmp_path / "adhoc"))
    preview = plan_only(scenario)
    (step,) = preview.steps
    assert step.apply is None and not step.converge and step.state == [] and preview.cleanup == "none"
    assert step.validate is not None and step.plan is not None and step.plan.expect == "changes"
    assert scenario.steps[0].apply is not None and adhoc_mode(scenario) == "live-apply"
    plan = StepOutcome("inject")
    plan.results["plan"] = cli_result("plan", "local-plan-add.txt")
    outcome = ScenarioOutcome("adhoc.inject", steps=[plan, StepOutcome("other")])
    assert foreign_additions(outcome, "t3c7z8a5") == []
    foreign = foreign_additions(outcome, "a0b1c2d3")
    assert foreign and foreign[0] == '+ add custom_property[name="e2e-t3c7z8a5-tier"]'


def test_live_apply_preview_refuses_changes_the_reset_cannot_restore() -> None:
    """DESTR-07: a live injection changing a repository the baseline does not declare (an extra protected one) is
    refused before the apply; baseline repositories and run objects are fine."""
    from otterdog_e2e.inject import unrestorable_changes

    plan = StepOutcome("inject")
    output = (
        '  ~ repository[name="precious-website"] {\n    ~ archived = false -> true\n  }\n'
        '  ~ repository[name="otterdog-e2e-configs"] {\n    ~ description = "a" -> "b"\n  }\n'
        "Plan: 0 to add, 2 to change, 0 to delete.\n"
    )
    plan.results["plan"] = cli_result_text("plan", output)
    outcome = ScenarioOutcome("adhoc.inject", steps=[plan])
    changed = unrestorable_changes(outcome, repos=("otterdog-e2e-configs",), teams=())
    assert changed == ['~ repository[name="precious-website"]']


def test_parse_assignment_and_variables() -> None:
    """NAME=VALUE options; --var values are YAML (numbers, lists), broken YAML stays a string."""
    assert parse_assignment("repositories=a=b.jsonnet", "--fragment") == ("repositories", "a=b.jsonnet")
    for bad in ("repositories", "=x", "x="):
        with pytest.raises(InjectError, match="expected NAME=VALUE"):
            parse_assignment(bad, "--fragment")
    assert parse_variables(["n=5", "l=[main, 'release/*']", "s=text", "b=[unclosed"]) == {
        "n": 5,
        "l": ["main", "release/*"],
        "s": "text",
        "b": "[unclosed",
    }
