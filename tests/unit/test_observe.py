"""Unit tests of otterdog_e2e.observe: recorder scopes, normalization, duplicate keys and the JSONL format."""

from __future__ import annotations

import dataclasses
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import observe
from otterdog_e2e.observe import (
    Observation,
    ObservationRecorder,
    base_key,
    duplicate_key,
    iter_observations,
    load_observations,
)
from otterdog_e2e.otterdog.output import NormalizeContext
from otterdog_e2e.redact import REDACTOR

SECRET = "e2e-observe-secret-0123456789abcdef"


@pytest.fixture
def normalize_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, NormalizeContext | None]]:
    """Replace output.normalize_text (owned by WP-D) with a recording fake: ``N[<stripped text>]``."""
    calls: list[tuple[str, NormalizeContext | None]] = []

    def fake(text: str, ctx: NormalizeContext | None = None) -> str:
        """Record the call and return a recognizable normalized form."""
        calls.append((text, ctx))
        return f"N[{text.strip()}]"

    monkeypatch.setattr(observe, "normalize_text", fake)
    return calls


@pytest.fixture
def out_file(tmp_path: Path) -> Path:
    """observations/base.jsonl of a fresh artifacts dir."""
    return tmp_path / "artifacts" / "observations" / "base.jsonl"


def _recorder(path: Path, *, role: str = "base", ctx: NormalizeContext | None = None) -> ObservationRecorder:
    """A recorder of SUT v1.6.1."""
    return ObservationRecorder("v1.6.1", role, path, ctx)


def test_cli_output_gets_exit_code_header_and_normalization(
    out_file: Path, normalize_calls: list[tuple[str, NormalizeContext | None]]
) -> None:
    """F6: content = "exit_code: N" + newline + normalize_text(raw stdout, ctx)."""
    ctx = NormalizeContext([("/scratch/run", "<TMP>")])
    recorder = _recorder(out_file, ctx=ctx)
    with recorder.scope("O-VAL-OK", "validate"):
        recorder.record("cli", "validate", "Validation succeeded\n", meta={"exit_code": 1})
    (observation,) = load_observations(out_file)
    assert observation.content == "exit_code: 1\nN[Validation succeeded]"
    assert normalize_calls == [("Validation succeeded\n", ctx)]
    assert (observation.sut, observation.role, observation.scenario, observation.step) == (
        "v1.6.1",
        "base",
        "O-VAL-OK",
        "validate",
    )
    assert (observation.kind, observation.key) == ("cli", "validate")
    assert observation.meta == {"exit_code": 1, "seq": 1}


def test_text_without_exit_code_has_no_header(
    out_file: Path, normalize_calls: list[tuple[str, NormalizeContext | None]]
) -> None:
    """Plain text observations are only normalized."""
    recorder = _recorder(out_file)
    with recorder.scope("s"):
        recorder.record("webapp", "comment", "  body  ")
        recorder.record("webapp", "raw", b"bytes \xff")
    first, second = load_observations(out_file)
    assert first.content == "N[body]" and first.step == ""
    assert second.content == "N[bytes �]"
    assert normalize_calls[0] == ("  body  ", None)


def test_mappings_are_sorted_json_without_volatile_keys(out_file: Path) -> None:
    """mapping/list -> json.dumps(oracle.normalize(content), sort_keys=True, indent=1)."""
    recorder = _recorder(out_file)
    content = {
        "b": 1,
        "a": {"name": "x", "url": "u", "node_id": "n", "hooks_url": "h", "_links": {}},
        "created_at": "2026-01-01T00:00:00Z",
    }
    with recorder.scope("s", "state"):
        recorder.record("oracle", "repo", content)
    (observation,) = load_observations(out_file)
    assert observation.content == json.dumps({"a": {"name": "x"}, "b": 1}, sort_keys=True, indent=1)


@dataclasses.dataclass
class _Sample:
    """A dataclass recorded as an observation."""

    name: str
    tags: tuple[str, ...]


def test_lists_tuples_sets_dataclasses_and_scalars_are_deterministic(out_file: Path) -> None:
    """Tuples become lists, sets sorted lists, dataclasses dicts; scalars are JSON values."""
    recorder = _recorder(out_file)
    with recorder.scope("s"):
        recorder.record("oracle", "list", [{"id": 1, "url": "x"}, ("a", "b")])
        recorder.record("oracle", "set", {"z", "a", "m"})
        recorder.record("oracle", "dataclass", _Sample("n", ("t",)))
        recorder.record("oracle", "scalar", 3)
        recorder.record("oracle", "none", None)
    contents = [observation.content for observation in load_observations(out_file)]
    assert contents == [
        json.dumps([{"id": 1}, ["a", "b"]], indent=1),
        json.dumps(["a", "m", "z"], indent=1),
        json.dumps({"name": "n", "tags": ["t"]}, indent=1),
        "3",
        "null",
    ]


def test_scopes_nest_and_restore_even_on_errors(
    out_file: Path, normalize_calls: list[tuple[str, NormalizeContext | None]]
) -> None:
    """The innermost scope wins; leaving it (also by exception) restores the outer one."""
    recorder = _recorder(out_file)
    assert recorder.current_scope is None
    with recorder.scope("scenario-a"):
        with recorder.scope("scenario-a", "step-1"):
            recorder.record("cli", "plan", "x")
        with pytest.raises(KeyError), recorder.scope("scenario-a", "step-2"):
            raise KeyError("boom")
        recorder.record("cli", "show", "y")
        assert recorder.current_scope == ("scenario-a", "")
    assert recorder.current_scope is None
    assert [(o.step, o.key) for o in load_observations(out_file)] == [("step-1", "plan"), ("", "show")]


def test_record_outside_scope_and_empty_scenario_are_errors(out_file: Path) -> None:
    """Recording without a scenario is a programming error, nothing is written."""
    recorder = _recorder(out_file)
    with pytest.raises(RuntimeError, match="outside scope"):
        recorder.record("cli", "validate", "x", meta={"exit_code": 0})
    with pytest.raises(ValueError, match="scenario"):
        recorder.scope("")
    assert not out_file.exists()


def test_repeated_keys_get_suffixes(out_file: Path, normalize_calls: list[tuple[str, NormalizeContext | None]]) -> None:
    """A key recorded twice in the same scenario/step/kind becomes key#2, key#3 (never overwritten)."""
    recorder = _recorder(out_file)
    with recorder.scope("s", "converge"):
        for _ in range(3):
            recorder.record("cli", "plan", "out", meta={"exit_code": 0})
        recorder.record("oracle", "plan", {"a": 1})
    with recorder.scope("s", "other"):
        recorder.record("cli", "plan", "out", meta={"exit_code": 0})
    keys = [(o.step, o.kind, o.key) for o in load_observations(out_file)]
    assert keys == [
        ("converge", "cli", "plan"),
        ("converge", "cli", "plan#2"),
        ("converge", "cli", "plan#3"),
        ("converge", "oracle", "plan"),
        ("other", "cli", "plan"),
    ]
    assert [o.meta["seq"] for o in load_observations(out_file)] == [1, 2, 3, 4, 5]


def test_new_recorder_on_the_same_file_continues_numbering(
    out_file: Path, normalize_calls: list[tuple[str, NormalizeContext | None]]
) -> None:
    """Numbering is seeded from existing lines of the same SUT and role only."""
    first = _recorder(out_file)
    with first.scope("s", "step"):
        first.record("cli", "plan", "a")
    second = _recorder(out_file)
    other_role = _recorder(out_file, role="head")
    with second.scope("s", "step"):
        second.record("cli", "plan", "b")
    with other_role.scope("s", "step"):
        other_role.record("cli", "plan", "c")
    observations = load_observations(out_file)
    assert [(o.role, o.key, o.meta["seq"]) for o in observations] == [
        ("base", "plan", 1),
        ("base", "plan#2", 2),
        ("head", "plan", 1),
    ]


def test_duplicate_key_helpers() -> None:
    """base_key strips only the recorder's suffixes (#2 and above)."""
    assert duplicate_key("plan", 1) == "plan"
    assert duplicate_key("plan", 2) == "plan#2"
    assert base_key("plan#2") == "plan" and base_key("plan#12") == "plan"
    assert base_key("plan") == "plan" and base_key("plan#1") == "plan#1" and base_key("#2") == "#2"


def test_content_and_meta_are_redacted(out_file: Path) -> None:
    """Secrets never reach the observation files (content and meta)."""
    REDACTOR.add(SECRET)
    recorder = _recorder(out_file)
    with recorder.scope("s"):
        recorder.record("oracle", "hook", {"config": {"secret": SECRET}}, meta={"argv": ["otterdog", SECRET]})
    text = out_file.read_text()
    assert SECRET not in text
    (observation,) = load_observations(out_file)
    assert json.loads(observation.content) == {"config": {"secret": "***"}}
    assert observation.meta["argv"] == ["otterdog", "***"]


def test_jsonl_format_is_one_sorted_object_per_line(
    out_file: Path, normalize_calls: list[tuple[str, NormalizeContext | None]]
) -> None:
    """Every line is a JSON object with the Observation fields (UTF-8 kept readable)."""
    recorder = _recorder(out_file)
    with recorder.scope("s", "step"):
        recorder.record("cli", "show", "│ box ✓\nline 2", meta={"exit_code": 0})
    lines = out_file.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and "✓" in lines[0]
    data = json.loads(lines[0])
    assert list(data) == sorted(data)
    assert set(data) == {"sut", "role", "scenario", "step", "kind", "key", "content", "meta"}


def test_load_observations_skips_missing_files_and_malformed_lines(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Missing file -> []; blank, invalid and incomplete lines are skipped with a warning."""
    assert load_observations(tmp_path / "missing.jsonl") == []
    good = Observation("v1", "base", "s", "", "cli", "validate", "exit_code: 0\n", {"seq": 1})
    path = tmp_path / "obs.jsonl"
    lines = [
        json.dumps(good.to_json()),
        "",
        "{not json",
        json.dumps({"sut": "v1", "role": "base"}),
        json.dumps([1, 2]),
        json.dumps({**good.to_json(), "meta": "not a dict", "extra": 1}),
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="otterdog_e2e.observe"):
        loaded = load_observations(path)
    assert loaded == [good, good]
    assert loaded[1].meta == {}
    assert len([r for r in caplog.records if "malformed" in r.getMessage()]) == 3


def test_iter_observations_is_lazy(tmp_path: Path) -> None:
    """iter_observations returns an iterator (no list materialized)."""
    path = tmp_path / "obs.jsonl"
    path.write_text(json.dumps(Observation("v", "head", "s", "", "k", "x", "c").to_json()) + "\n")
    iterator = iter_observations(path)
    assert isinstance(iterator, Iterator)
    assert next(iterator).key == "x"


def test_observation_identity_and_equality_ignore_meta() -> None:
    """identity is (scenario, step, kind, key); meta is not compared."""
    one = Observation("v1", "base", "s", "st", "cli", "plan", "x", {"seq": 1})
    two = Observation("v1", "base", "s", "st", "cli", "plan", "x", {"seq": 9})
    assert one == two and hash(one) == hash(two)
    assert one.identity == ("s", "st", "cli", "plan")


def test_recorder_uses_the_real_normalize_text(out_file: Path) -> None:
    """Integration with output.normalize_text: ANSI codes never reach observations."""
    recorder = _recorder(out_file, ctx=NormalizeContext([]))
    with recorder.scope("O-VAL-OK", "validate"):
        recorder.record("cli", "validate", "\x1b[1mValidation succeeded\x1b[0m\n", meta={"exit_code": 0})
    (observation,) = load_observations(out_file)
    assert observation.content.startswith("exit_code: 0\n")
    assert "Validation succeeded" in observation.content and "\x1b" not in observation.content


def _content(value: Any) -> str:
    """render_content of a mapping (no normalize_text involved)."""
    return observe.render_content(value, {}, None)


def test_render_content_handles_non_json_values() -> None:
    """Paths and other objects are stringified instead of failing."""
    assert json.loads(_content({"path": Path("/x/y")})) == {"path": "/x/y"}
