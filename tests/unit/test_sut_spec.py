"""SUT spec strings (SPEC 10.1) and spec-level trust (SPEC 5.5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from otterdog_e2e.sut.spec import ResolvedSut, SutSpec, cleanup_source, label_part, parse_sut_spec

PIN = "d0d3b0832d8e21a9da86e0ef967859d2634af894"


@pytest.mark.parametrize(
    ("raw", "kind", "value", "pin"),
    [
        ("release:latest", "release", "latest", None),
        ("release:LATEST", "release", "latest", None),
        ("tag:v1.6.1", "tag", "v1.6.1", None),
        ("v1.6.1", "tag", "v1.6.1", None),
        ("v1.0.0rc1", "tag", "v1.0.0rc1", None),
        ("branch:main", "branch", "main", None),
        ("main", "branch", "main", None),
        ("branch:fix/stale-pr-status-overwrite", "branch", "fix/stale-pr-status-overwrite", None),
        ("sha:9bdeb75", "sha", "9bdeb75", None),
        ("sha:9BDEB75F3E82A6CBD107D6BC3C9EC90392475C08", "sha", "9bdeb75f3e82a6cbd107d6bc3c9ec90392475c08", None),
        (f"pr:792@{PIN}", "pr", "792", PIN),
        (f"pr:792@{PIN.upper()}", "pr", "792", PIN),
        ("path:../otterdog", "path", "../otterdog", None),
        ("dirty:/home/me/otterdog", "dirty", "/home/me/otterdog", None),
        ("dirty:/odd:path", "dirty", "/odd:path", None),
        ("  tag:v1.6.1  ", "tag", "v1.6.1", None),
    ],
)
def test_parse_sut_spec_forms(raw: str, kind: str, value: str, pin: str | None) -> None:
    """Every documented form, with bare tag/main shortcuts and case normalisation of hex values."""
    spec = parse_sut_spec(raw)
    assert (spec.kind, spec.value, spec.pin_sha) == (kind, value, pin)
    assert spec.raw == raw.strip()


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("", "empty"),
        ("   ", "empty"),
        ("release:v1.6.1", "only release:latest"),
        ("tag:1.6.1", "v\\* version tag"),
        ("tag:latest", "v\\* version tag"),
        ("1.6.1", "cannot parse"),
        ("feature-x", "cannot parse"),
        ("branch:-x", "invalid branch"),
        ("branch:a..b", "invalid branch"),
        ("branch:x.lock", "invalid branch"),
        ("branch:x/", "invalid branch"),
        ("branch:", "invalid branch"),
        ("sha:12345", "7 to 40 hex"),
        ("sha:xyz1234", "7 to 40 hex"),
        ("sha:" + "a" * 41, "7 to 40 hex"),
        ("pr:792", "must be pinned"),  # the pin is REQUIRED (SEC-03)
        ("pr:792@", "must be pinned"),
        ("pr:792@d0d3b08", "must be pinned"),  # short shas are not pins
        ("pr:abc@" + PIN, "expected pr:"),
        ("pr:0@" + PIN, "expected pr:"),
        ("path:", "missing checkout"),
        ("dirty:  ", "missing checkout"),
        ("repo:eclipse-csi/otterdog@main", "unknown SUT kind"),
        ("http://example.org", "unknown SUT kind"),
    ],
)
def test_parse_sut_spec_errors(raw: str, message: str) -> None:
    """Malformed specs raise ValueError with a useful message."""
    with pytest.raises(ValueError, match=message):
        parse_sut_spec(raw)


@pytest.mark.parametrize(
    ("raw", "trusted"),
    [
        ("release:latest", True),
        ("v1.6.1", True),
        ("main", True),
        ("branch:feature", False),
        ("sha:9bdeb75", False),  # decided at resolve time
        (f"pr:1@{PIN}", False),
        ("path:.", True),
        ("dirty:.", True),
    ],
)
def test_spec_level_trust(raw: str, trusted: bool) -> None:
    """SPEC 5.5 spec-level trust."""
    assert parse_sut_spec(raw).trusted is trusted


def test_normalized_spec_strings() -> None:
    """Canonical forms (used by `sut classify`)."""
    assert parse_sut_spec("v1.6.1").normalized == "tag:v1.6.1"
    assert parse_sut_spec("main").normalized == "branch:main"
    assert parse_sut_spec(f"pr:7@{PIN.upper()}").normalized == f"pr:7@{PIN}"
    assert parse_sut_spec("release:latest").normalized == "release:latest"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("v1.6.1", "v1.6.1"),
        ("main", "main"),
        ("fix/stale-pr-status-overwrite", "fix-stale-pr-status-overwrite"),
        ("feat/a b@{c}", "feat-a-b-c"),
        ("..x..y.", "x.y"),
        ("///", "x"),
        ("a" * 80, "a" * 60),
    ],
)
def test_label_part_is_docker_and_ref_safe(text: str, expected: str) -> None:
    """Labels end up in docker tags, paths and git tag names."""
    assert label_part(text) == expected


def _sut(tmp_path: Path, *, trusted: bool) -> ResolvedSut:
    """A minimal ResolvedSut whose source dir exists."""
    source = tmp_path / ("src" if trusted else "untrusted")
    source.mkdir()
    spec = parse_sut_spec("v1.6.1" if trusted else f"pr:1@{PIN}")
    return ResolvedSut(spec, "x", PIN, "1.6.1", "1.6.1", source, "https://github.com/eclipse-csi/otterdog", trusted)


def test_resolved_sut_to_json_and_cleanup(tmp_path: Path) -> None:
    """to_json is serializable; cleanup_source only removes untrusted exports."""
    trusted, untrusted = _sut(tmp_path, trusted=True), _sut(tmp_path, trusted=False)
    data = untrusted.to_json()
    assert data["spec"] == f"pr:1@{PIN}" and data["source_dir"] == str(untrusted.source_dir)
    json.dumps(data)
    cleanup_source(trusted)
    cleanup_source(untrusted)
    assert trusted.source_dir.exists() and not untrusted.source_dir.exists()


def test_sut_spec_is_frozen() -> None:
    """Specs are immutable value objects."""
    spec = SutSpec("main", "branch", "main")
    with pytest.raises(AttributeError):
        spec.kind = "tag"  # type: ignore[misc]
