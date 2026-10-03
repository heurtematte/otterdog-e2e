"""Oracle state checks: forms, match specials, validation and the retry loop (SPEC 12.2)."""

from __future__ import annotations

from typing import Any

import pytest

from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.scenarios.checks import (
    CHECK_KINDS,
    CheckError,
    evaluate_check,
    evaluate_checks,
    exact_equal,
    subset_mismatches,
    validate_check,
    wait_for_checks,
)
from otterdog_e2e.testing.fakes import FakeOracle

REPO = "e2e-t3c7z8a5-basic"


@pytest.fixture
def oracle() -> FakeOracle:
    """A fake org with one run repository, a team and a ruleset listing that answers 404."""
    fake = FakeOracle()
    fake.add_repo(REPO, description="e2e basic", topics=["b", "a"], visibility="public", homepage=None)
    fake.add_team("e2e-t3c7z8a5-team", members=["e2e-author"])
    fake.set("repo_custom_property_values", REPO, value={"e2e-t3c7z8a5-tier": "gold"})
    fake.mark_unavailable("org_rulesets")
    return fake


# --- subset matching -------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("expected", "actual", "problems"),
    [
        ({"a": 1}, {"a": 1, "b": 2}, []),
        ({"a": {"b": [1, {"c": 3}]}}, {"a": {"b": [1, {"c": 3, "d": 4}], "x": 0}}, []),
        ({"a": 1}, {"a": 2}, ["$.a: expected 1, got 2"]),
        ({"a": 1}, {}, ["$.a: missing"]),
        ({"a": True}, {"a": 1}, ["$.a: expected True, got 1"]),
        ({"a": 1}, {"a": 1.0}, []),
        ([1, 2], [1, 2, 3], ["$: expected 2 item(s), got 3: [1, 2, 3]"]),
        ([{"n": "x"}], [{"n": "y"}], ["$[0].n: expected 'x', got 'y'"]),
        ({"a": [1]}, {"a": "1"}, ["$.a: expected a list, got '1'"]),
        ({"a": {"b": 1}}, {"a": None}, ["$.a: expected a mapping, got None"]),
    ],
)
def test_subset_mismatches(expected: Any, actual: Any, problems: list[str]) -> None:
    """Mappings are subsets, lists are element-wise with the same length, booleans never equal numbers."""
    assert subset_mismatches(expected, actual) == problems


@pytest.mark.parametrize(
    ("expected", "actual", "ok"),
    [
        ({"name": {"$regex": "^e2e-"}}, {"name": "e2e-x"}, True),
        ({"name": {"$regex": "^e2e-"}}, {"name": "prod"}, False),
        ({"name": {"$regex": "x"}}, {"name": 1}, False),
        ({"homepage": {"$exists": False}}, {"homepage": None}, True),
        ({"homepage": {"$exists": False}}, {}, True),
        ({"homepage": {"$exists": True}}, {"homepage": None}, False),
        ({"homepage": {"$exists": True}}, {"homepage": "h"}, True),
        ({"topics": {"$len": 2}}, {"topics": ["a", "b"]}, True),
        ({"topics": {"$len": 1}}, {"topics": ["a", "b"]}, False),
        ({"topics": {"$len": 0}}, {}, False),
        ({"topics": {"$unordered": ["b", "a"]}}, {"topics": ["a", "b"]}, True),
        ({"topics": {"$unordered": ["a", "a"]}}, {"topics": ["a", "b"]}, False),
        ({"t": {"$unordered": [{"n": 1}, {"n": 2}]}}, {"t": [{"n": 2, "x": 0}, {"n": 1}]}, True),
        ({"t": {"$unordered": [{"n": 1}]}}, {"t": [{"n": 1}, {"n": 2}]}, False),
        ({"t": {"$len": 2, "$unordered": ["x", "y"]}}, {"t": ["y", "x"]}, True),
    ],
)
def test_match_specials(expected: Any, actual: Any, ok: bool) -> None:
    """$regex, $exists (null counts as absent), $len and $unordered (one-to-one subset matching)."""
    assert (not subset_mismatches(expected, actual)) is ok


def test_unordered_needs_a_distinct_match_for_each_item() -> None:
    """Greedy matching would fail here: the first expected item fits both actual items."""
    expected = {"$unordered": [{}, {"n": 1}]}
    assert subset_mismatches(expected, [{"n": 1}, {"n": 2}]) == []


def test_exact_equal() -> None:
    """``equals`` is exact (no extra keys) and boolean-aware."""
    assert exact_equal({"a": [1, 2]}, {"a": (1, 2)})
    assert not exact_equal({"a": 1}, {"a": 1, "b": 2})
    assert not exact_equal([True], [1])
    assert not exact_equal([], {})


@pytest.mark.parametrize(
    ("expected", "actual", "ok"),
    [
        ({"$unordered": ["a", "b"]}, ["b", "a"], True),
        ({"$unordered": ["a", "b"]}, ["b", "a", "c"], False),
        ({"$unordered": [{"x": 1}]}, [{"x": 1, "y": 2}], False),  # items are compared exactly inside equals
        ({"$unordered": [{"x": 1}]}, [{"x": 1}], True),
        ({"names": {"$unordered": ["a", "b"]}, "n": 2}, {"names": ["b", "a"], "n": 2}, True),
        ({"names": {"$unordered": ["a", "b"]}}, {"names": ["b", "a"], "n": 2}, False),  # still no extra key
        ({"sha": {"$regex": "^[0-9a-f]{40}$"}, "ok": True}, {"sha": "a" * 40, "ok": True}, True),
        ({"sha": {"$regex": "^[0-9a-f]{40}$"}}, {"sha": "nope"}, False),
        ({"items": {"$len": 2}}, {"items": [1, 2]}, True),
        ({"a": 1, "gone": {"$exists": False}}, {"a": 1}, True),  # a key expected absent may be missing
        ({"a": 1, "gone": {"$exists": False}}, {"a": 1, "gone": None}, True),
        ({"a": 1, "gone": {"$exists": False}}, {"a": 1, "gone": "x"}, False),
        ({"a": 1, "here": {"$exists": True}}, {"a": 1}, False),
        ([{"$regex": "^e2e-"}, 1], ["e2e-x", 1], True),
    ],
)
def test_exact_equal_evaluates_operators(expected: Any, actual: Any, ok: bool) -> None:
    """The documented operators work inside ``equals`` (validate_check already accepts them there)."""
    assert exact_equal(expected, actual) is ok


# --- validation ------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("check", "match"),
    [
        ({"kind": "nope", "absent": True}, "unknown check kind"),
        ({"kind": "repo", "absent": True}, r"parameter\(s\) \['name'\]"),
        ({"kind": "repo", "name": "", "absent": True}, "non-empty"),
        ({"kind": "repo", "name": "x"}, "exactly one"),
        ({"kind": "repo", "name": "x", "absent": True, "match": {}}, "exactly one"),
        ({"kind": "repo", "name": "x", "absent": "yes"}, "true or false"),
        ({"kind": "repo_topics", "name": "x", "absent": True}, "single-object"),
        ({"kind": "repo_custom_properties", "repo": "x", "absent": True}, "single-object"),
        ({"kind": "repo", "name": "x", "match": {"a": {"$near": 1}}}, "unknown operator"),
        ({"kind": "repo", "name": "x", "match": {"a": {"$len": True}}}, "expects a int"),
        ({"kind": "repo", "name": "x", "match": {"a": {"$len": 1, "b": 2}}}, "unknown operator"),
        ({"kind": "repo", "name": "x", "match": {"a": {"$exists": 1}}}, "expects a bool"),
        ({"kind": "repo", "name": "x", "match": {"a": {"$unordered": "ab"}}}, "expects a list"),
        ({"kind": "repo", "name": "x", "absent": True, "timeout": 0}, "positive"),
        ({"kind": "repo", "name": "x", "absent": True, "pattern": "p"}, "unknown key"),
    ],
)
def test_validate_check_refuses_malformed_checks(check: dict[str, Any], match: str) -> None:
    """Load-time validation of check mappings."""
    with pytest.raises(CheckError, match=match):
        validate_check(check)


def test_every_kind_validates_with_its_parameters() -> None:
    """Each CHECK_KINDS entry accepts exactly its parameter names."""
    for kind, (_, params) in CHECK_KINDS.items():
        validate_check({"kind": kind, **dict.fromkeys(params, "x"), "equals": None})


# --- evaluation ------------------------------------------------------------------------------------------------------
def test_match_form(oracle: FakeOracle) -> None:
    """Subset match of the looked-up object; the result carries the normalized actual value."""
    result = evaluate_check(oracle, {"kind": "repo", "name": REPO, "match": {"description": "e2e basic"}})
    assert result.ok and result.message == f"repo(name='{REPO}'): ok"
    assert result.actual["name"] == REPO and "html_url" not in result.actual
    result = evaluate_check(oracle, {"kind": "repo", "name": REPO, "match": {"description": "other"}})
    assert not result.ok and "$.description: expected 'other', got 'e2e basic'" in result.message
    assert not evaluate_check(oracle, {"kind": "repo", "name": "missing", "match": {}}).ok


def test_absent_form(oracle: FakeOracle) -> None:
    """absent true/false on single-object kinds."""
    assert evaluate_check(oracle, {"kind": "repo", "name": "gone", "absent": True}).ok
    assert evaluate_check(oracle, {"kind": "repo", "name": REPO, "absent": False}).ok
    result = evaluate_check(oracle, {"kind": "repo", "name": REPO, "absent": True})
    assert not result.ok and "expected absent" in result.message


def test_equals_and_contains_forms(oracle: FakeOracle) -> None:
    """equals is exact; contains works on lists, mappings and strings."""
    assert evaluate_check(oracle, {"kind": "team_members", "slug": "e2e-t3c7z8a5-team", "equals": ["e2e-author"]}).ok
    assert not evaluate_check(oracle, {"kind": "repo_topics", "name": REPO, "equals": ["a", "b"]}).ok
    assert evaluate_check(oracle, {"kind": "repo_topics", "name": REPO, "match": {"$unordered": ["a", "b"]}}).ok
    assert evaluate_check(oracle, {"kind": "repo_topics", "name": REPO, "contains": ["a"]}).ok
    assert evaluate_check(oracle, {"kind": "repo_topics", "name": REPO, "contains": "b"}).ok
    missing = evaluate_check(oracle, {"kind": "repo_topics", "name": REPO, "contains": ["c"]})
    assert not missing.ok and "no item matches 'c'" in missing.message
    props = {"kind": "repo_custom_properties", "repo": REPO, "contains": ["e2e-t3c7z8a5-tier"]}
    assert evaluate_check(oracle, props).ok
    assert evaluate_check(oracle, {"kind": "team_members", "slug": "nobody", "equals": []}).ok


def test_hook_delivery_and_org_role_kinds(oracle: FakeOracle) -> None:
    """repo/org_webhook_deliveries list the deliveries of the hook with that URL ([] without it); org_role is a
    single object (absent works)."""
    url = "https://otterdog-e2e.invalid/t3c7z8a5/repo-hook"
    hook_repo = "e2e-t3c7z8a5-hooks"
    hook = oracle.add_repo_hook(hook_repo, url)
    oracle.set("repo_hook_deliveries", hook_repo, hook["id"], value=[{"id": 7, "event": "ping"}])
    check = {"kind": "repo_webhook_deliveries", "repo": hook_repo, "url": url, "contains": [{"event": "ping"}]}
    assert evaluate_check(oracle, check).ok
    other = "https://otterdog-e2e.invalid/t3c7z8a5/other"
    assert evaluate_check(oracle, {"kind": "repo_webhook_deliveries", "repo": hook_repo, "url": other, "equals": []}).ok
    org_hook = oracle.add_org_hook(url)
    oracle.set("org_hook_deliveries", org_hook["id"], value=[{"id": 8, "event": "ping"}, {"id": 9, "event": "push"}])
    assert evaluate_check(oracle, {"kind": "org_webhook_deliveries", "url": url, "match": {"$len": 2}}).ok
    with pytest.raises(CheckError, match="absent is only valid"):
        validate_check({"kind": "org_webhook_deliveries", "url": url, "absent": True})
    oracle.set("org_roles", value=[{"id": 3, "name": "e2e-t3c7z8a5-role", "base_role": "read"}])
    assert evaluate_check(oracle, {"kind": "org_role", "name": "e2e-t3c7z8a5-role", "match": {"base_role": "read"}}).ok
    assert evaluate_check(oracle, {"kind": "org_role", "name": "e2e-t3c7z8a5-gone", "absent": True}).ok


def test_unavailable_form(oracle: FakeOracle) -> None:
    """unavailable tells a 403/404 listing (paid plan) apart from an absent object."""
    assert evaluate_check(oracle, {"kind": "org_ruleset", "name": "e2e-t3c7z8a5-rs", "unavailable": True}).ok
    assert evaluate_check(oracle, {"kind": "repo_topics", "name": REPO, "unavailable": False}).ok
    result = evaluate_check(oracle, {"kind": "repo_topics", "name": REPO, "unavailable": True})
    assert not result.ok and "it answered" in result.message
    absent = evaluate_check(oracle, {"kind": "org_ruleset", "name": "e2e-t3c7z8a5-rs", "match": {"enforcement": "x"}})
    assert not absent.ok and "listing unavailable" in absent.message
    assert oracle.unavailable  # recorded entries are kept on the oracle


def test_unavailable_is_detected_on_every_retry(oracle: FakeOracle) -> None:
    """A listing already recorded as unavailable is still detected by later evaluations."""
    check = {"kind": "org_ruleset", "name": "x", "unavailable": True}
    assert evaluate_check(oracle, check).ok and evaluate_check(oracle, check).ok


def test_invalid_check_and_lookup_errors_are_failed_results(oracle: FakeOracle, monkeypatch: Any) -> None:
    """Malformed checks and lookup exceptions never crash evaluation."""
    assert "invalid check" in evaluate_check(oracle, {"kind": "nope"}).message

    def boom(name: str) -> None:
        """A failing lookup."""
        raise GitHubError(500, "GET", "https://api.github.com/x", "server error")

    monkeypatch.setattr(oracle, "repo", boom)
    result = evaluate_check(oracle, {"kind": "repo", "name": REPO, "absent": False})
    assert not result.ok and "lookup failed: GitHubError" in result.message


class _Clock:
    """A fake clock advanced by its sleep."""

    def __init__(self) -> None:
        """Start at 0."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance the clock."""
        self.sleeps.append(seconds)
        self.now += seconds


def test_wait_for_checks_retries_only_failing_checks(oracle: FakeOracle) -> None:
    """Failing checks are re-evaluated every interval until they pass."""
    clock = _Clock()
    lookups: list[str] = []
    original = oracle.repo

    def eventually(name: str) -> dict[str, Any] | None:
        """The second repo appears after two lookups."""
        lookups.append(name)
        if name == "late" and lookups.count("late") < 3:
            return None
        return original(REPO)

    oracle.repo = eventually  # type: ignore[method-assign]
    checks = [{"kind": "repo", "name": REPO, "absent": False}, {"kind": "repo", "name": "late", "absent": False}]
    results = wait_for_checks(oracle, checks, timeout=60, interval=5, sleep=clock.sleep, clock=clock)
    assert all(result.ok for result in results)
    assert clock.sleeps == [5, 5] and lookups.count(REPO) == 1 and lookups.count("late") == 3


def test_wait_for_checks_gives_up_after_the_budget(oracle: FakeOracle) -> None:
    """The budget is the largest of the timeout and per-check timeouts; the last sleep never overshoots."""
    clock = _Clock()
    checks = [{"kind": "repo", "name": "never", "absent": False, "timeout": 12}]
    results = wait_for_checks(oracle, checks, timeout=0, interval=5, sleep=clock.sleep, clock=clock)
    assert not results[0].ok and clock.sleeps == [5, 5, 2] and clock.now == 12


def test_evaluate_checks_without_timeout_evaluates_once(oracle: FakeOracle) -> None:
    """timeout 0: one pass, no sleep."""
    results = evaluate_checks(oracle, [{"kind": "repo", "name": "missing", "absent": False}], timeout=0)
    assert len(results) == 1 and not results[0].ok


def test_unavailable_records_are_kept_in_sync_with_the_oracle(oracle: FakeOracle) -> None:
    """Entries a lookup records are kept; entries it clears (listing answers again) are removed."""
    oracle.unavailable[("org_rulesets", "stale")] = 404

    def org_ruleset(name: str) -> None:
        """A lookup clearing a stale record and recording a new one."""
        oracle.unavailable.pop(("org_rulesets", "stale"), None)
        oracle.unavailable[("org_rulesets", "e2e-test-org")] = 403

    oracle.org_ruleset = org_ruleset  # type: ignore[method-assign,assignment]
    assert evaluate_check(oracle, {"kind": "org_ruleset", "name": "x", "unavailable": True}).ok
    assert oracle.unavailable == {("org_rulesets", "e2e-test-org"): 403}
    assert isinstance(oracle.unavailable, dict) and type(oracle.unavailable) is dict


def test_checks_with_the_real_oracle() -> None:
    """The real Oracle (over FakeGitHubHttp): 404 on a paid-plan listing is ``unavailable``; repo lookups match."""
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.testing.fakes import FAKE_ORG, FakeGitHubHttp

    http = FakeGitHubHttp(read_only=True)
    http.add("GET", f"/orgs/{FAKE_ORG}/rulesets", status=404, json={"message": "Not Found"}, repeat=True)
    http.add("GET", f"/repos/{FAKE_ORG}/{REPO}", json={"name": REPO, "description": "e2e basic"}, repeat=True)
    http.add("GET", f"/repos/{FAKE_ORG}/missing", status=404, json={"message": "Not Found"}, repeat=True)
    oracle = Oracle(http, FAKE_ORG)  # type: ignore[arg-type]
    assert evaluate_check(oracle, {"kind": "org_ruleset", "name": "e2e-x", "unavailable": True}).ok
    assert evaluate_check(oracle, {"kind": "repo", "name": REPO, "match": {"description": "e2e basic"}}).ok
    assert evaluate_check(oracle, {"kind": "repo", "name": "missing", "absent": True}).ok
    assert oracle.unavailable == {("org_rulesets", FAKE_ORG): 404}


def test_unevaluated_checks_are_errors_and_network_failures_are_infra() -> None:
    """BAT-02: a malformed check or a failed lookup sets CheckResult.error (never a known bug's expected failure);
    network errors, 5xx and rate limits are tagged [infra], harness exceptions are not."""
    from otterdog_e2e.scenarios.checks import INFRA_PREFIX, lookup_error_message

    assert evaluate_check(FakeOracle(), {"kind": "nope"}).error
    assert not evaluate_check(FakeOracle(), {"kind": "repo", "name": "x", "absent": True}).error
    assert lookup_error_message("repo(name='x')", TypeError("boom")) == "repo(name='x'): lookup failed: TypeError: boom"
    assert lookup_error_message("r", ConnectionError("reset")).startswith(f"{INFRA_PREFIX} r: lookup failed")
    assert lookup_error_message("r", GitHubError(502, "GET", "/x", "Bad Gateway")).startswith(INFRA_PREFIX)
    assert not lookup_error_message("r", GitHubError(404, "GET", "/x", "Not Found")).startswith(INFRA_PREFIX)
