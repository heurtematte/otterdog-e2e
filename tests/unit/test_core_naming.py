"""WP-A: run ids and naming rules (SPEC 7)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from otterdog_e2e import naming
from otterdog_e2e.naming import (
    E2E_NAME_RE,
    HOOK_BASE,
    RUN_ID_RE,
    RunContext,
    extract_run_id,
    is_deletable_ref,
    is_e2e_name,
    new_run_context,
    run_id_timestamp,
)

RUN_ID = "t3c7z8a5"


def run_id_at(when: datetime, suffix: str = "a5") -> str:
    """Run id encoding ``when``."""
    return new_run_context(now=when).run_id[:6] + suffix


def test_new_run_ids_are_time_ordered_and_unique_enough() -> None:
    """base36 seconds keep ids sortable by creation time; the hex suffix separates same-second runs."""
    first = new_run_context(now=datetime(2026, 1, 1, tzinfo=UTC))
    later = new_run_context(now=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC))
    assert first.run_id[:6] < later.run_id[:6]
    assert all(RUN_ID_RE.match(ctx.run_id) for ctx in (first, later))
    assert len({new_run_context(now=first.created_at).run_id[6:] for _ in range(64)}) > 1


def test_naive_now_is_utc() -> None:
    """SPEC 4: naive datetimes are UTC (ids do not depend on the local timezone)."""
    ctx = new_run_context(now=datetime(2026, 3, 1, 12, 0, 0))  # noqa: DTZ001 - naive on purpose
    assert ctx.created_at == datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    assert run_id_timestamp(ctx.run_id) == ctx.created_at


def test_given_run_id_is_kept_and_validated() -> None:
    """Reused ids (--e2e-run-id) are validated (SEC-17)."""
    assert new_run_context(RUN_ID).run_id == RUN_ID
    for bad in ("T3C7Z8A5", "t3c7z8a", "t3c7z8az", "../../x", ""):
        with pytest.raises(ValueError, match="invalid run id"):
            RunContext(bad)


def test_run_context_derived_names() -> None:
    """Every derived name of SPEC 7."""
    ctx = RunContext(RUN_ID)
    assert ctx.const("a-b-c9") == "E2E_T3C7Z8A5_A_B_C9"
    assert ctx.prop("tier") == ctx.name("tier") == "e2e-t3c7z8a5-tier"
    assert ctx.hook_url("org") == f"{HOOK_BASE}{RUN_ID}/org"
    assert ctx.hook_base == f"{HOOK_BASE}{RUN_ID}/"
    assert ctx.branch("pr-1") == f"e2e/{RUN_ID}/pr-1"
    assert all(
        needle in ctx.name("x") or needle in ctx.const("x") or needle in ctx.hook_url("x") for needle in ctx.needles()
    )
    for value in (ctx.name("x"), ctx.const("x"), ctx.hook_url("x"), ctx.branch("x"), f"otterdog/{ctx.name('x')}"):
        assert extract_run_id(value) == RUN_ID, value


def test_extract_run_id_hook_urls_are_anchored() -> None:
    """Only URLs under the hook host carry a run id (a foreign URL mentioning it is never attributed)."""
    assert extract_run_id(f"http://otterdog-e2e.invalid/{RUN_ID}/x") == RUN_ID
    assert extract_run_id(f"https://example.org/?next=https://otterdog-e2e.invalid/{RUN_ID}/x") is None
    assert extract_run_id(f"https://otterdog-e2e.invalid.example.org/{RUN_ID}/x") is None
    assert extract_run_id(f"https://otterdog-e2e.invalid/{RUN_ID}") is None


def test_extract_run_id_plausibility_window() -> None:
    """Ids decoding before 2024 are human names, not runs (e2e-sandbox1-x)."""
    old = run_id_at(datetime(2023, 6, 1, tzinfo=UTC))
    recent = run_id_at(datetime(2025, 6, 1, tzinfo=UTC))
    assert extract_run_id(f"e2e-{old}-x") is None
    assert extract_run_id(f"e2e-{recent}-x") == recent
    assert extract_run_id(f"E2E_{recent.upper()}_X") == recent
    assert not is_e2e_name(f"e2e-{old}-x") and is_e2e_name(f"e2e-{recent}-x")
    assert E2E_NAME_RE.match(f"e2e-{old}-x")  # the shape alone (used for protected-name checks)


def test_run_id_timestamp_round_trip() -> None:
    """The first 6 characters encode the creation second."""
    when = datetime(2027, 7, 7, 7, 7, 7, tzinfo=UTC)
    assert run_id_timestamp(run_id_at(when)) == when
    assert run_id_timestamp("zzzzzzff") == datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=36**6 - 1)
    assert run_id_timestamp("nope") is None


@pytest.mark.parametrize(
    ("ref", "deletable"),
    [
        (f"heads/e2e/{RUN_ID}/branch", True),
        (f"refs/heads/e2e/{RUN_ID}/a/b", True),
        (f"heads/e2e/{RUN_ID}/", False),
        (f"heads/otterdog/e2e-{RUN_ID}", True),
        (f"heads/otterdog/e2e-{RUN_ID}-slug", True),
        (f"heads/otterdog/e2e-{RUN_ID}x", False),
        ("tags/sut-v1.6.1-1a2b3c4d", True),
        ("tags/sut-", False),
        (f"tags/e2e-run/{RUN_ID}", True),
        ("tags/e2e-run/000000aa", False),
        ("heads/e2e-lease", True),
        ("heads/main", False),
        ("tags/v1.6.1", False),
        ("heads/e2e-lease/x", False),
    ],
)
def test_is_deletable_ref(ref: str, deletable: bool) -> None:
    """Mutator.delete_ref guard of SPEC 5.2."""
    assert is_deletable_ref(ref) is deletable


def test_template_vars_are_strings() -> None:
    """Jinja variables are plain strings."""
    assert all(isinstance(value, str) for value in RunContext(RUN_ID).template_vars().values())
    assert naming.PLAUSIBLE_FROM < naming.PLAUSIBLE_UNTIL


@pytest.mark.parametrize(
    ("ref", "expected"),
    [
        (f"e2e/{RUN_ID}/case", RUN_ID),
        (f"refs/heads/e2e/{RUN_ID}/case", RUN_ID),
        (f"heads/otterdog/e2e-{RUN_ID}-open-pr", RUN_ID),
        (f"otterdog/e2e-{RUN_ID}", RUN_ID),
        (f"otterdog/blueprint/e2e-{RUN_ID}-required-file", RUN_ID),  # a remediation branch of a run blueprint
        (f"refs/heads/otterdog/blueprint/e2e-{RUN_ID}-pin", RUN_ID),
        ("otterdog/blueprint/default-security-policy", None),  # a blueprint of somebody else
        ("otterdog/blueprint/e2e-zzzzzzzz-x", None),  # implausible run id
        (f"e2e-{RUN_ID}-repo", None),  # a repository name, not a branch
        (f"feature/e2e/{RUN_ID}/x", None),
        ("main", None),
    ],
)
def test_branch_run_id(ref: str, expected: str | None) -> None:
    """Pull request heads of a run: e2e/<id>/..., otterdog/e2e-<id>-... and otterdog/blueprint/e2e-<id>-... only."""
    assert naming.branch_run_id(ref) == expected
