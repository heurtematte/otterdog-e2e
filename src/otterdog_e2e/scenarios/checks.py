"""State checks evaluated against the Oracle (SPEC 12.2).

Forms: ``{kind, ...params, match: {...}}`` | ``{..., absent: true}`` (single-object kinds only) | ``{..., equals: v}`` |
``{..., contains: [..]}`` | ``{..., unavailable: true}`` (a listing or a feature setting the lookup reads answered
403/404, or another status the Oracle method documents as "unavailable"). Match specials:
``{"$regex": ".."}`` ``{"$exists": bool}`` ``{"$unordered": [..]}`` ``{"$len": n}``.

``match`` is a subset match: mappings need the listed keys only, lists need the same length (element-wise subset;
``$unordered`` for any order), scalars are equal (booleans never equal numbers). ``$exists: false`` also holds for a
null value. ``equals`` is an exact comparison (operators work inside it too: ``$unordered`` items are then compared
exactly, and a key whose expected value is ``{$exists: false}`` may be missing); ``contains`` holds when every item
is matched by an element of a list (subset semantics), is a substring of a string, or is a key of a mapping. An
optional ``timeout`` (seconds) extends the retry budget of evaluate_checks for slow-to-converge objects.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from otterdog_e2e import waiting
from otterdog_e2e.github.oracle import normalize
from otterdog_e2e.redact import REDACTOR

if TYPE_CHECKING:
    from otterdog_e2e.github.oracle import Oracle

CHECK_KINDS: dict[str, tuple[str, tuple[str, ...]]] = {
    "org": ("org", ()),
    "org_actions": ("org_actions_permissions", ()),
    "org_workflow_permissions": ("org_workflow_permissions", ()),
    "org_secret": ("org_secret", ("name",)),
    "org_secret_repos": ("org_secret_repositories", ("name",)),
    "org_variable": ("org_variable", ("name",)),
    "org_variable_repos": ("org_variable_repositories", ("name",)),
    "org_webhook": ("org_hook_by_url", ("url",)),
    "org_webhook_deliveries": ("org_hook_deliveries_by_url", ("url",)),
    "org_ruleset": ("org_ruleset", ("name",)),
    "org_role": ("org_role", ("name",)),
    "custom_property": ("custom_property", ("name",)),
    "team": ("team", ("slug",)),
    "team_members": ("team_members", ("slug",)),
    "team_repo_permission": ("team_repo_permission", ("slug", "repo")),
    "repo": ("repo", ("name",)),
    "repo_topics": ("repo_topics", ("name",)),
    "repo_actions": ("repo_actions_permissions", ("name",)),
    "repo_workflow_permissions": ("repo_workflow_permissions", ("name",)),
    "repo_secret": ("repo_secret", ("repo", "name")),
    "repo_variable": ("repo_variable", ("repo", "name")),
    "repo_webhook": ("repo_hook_by_url", ("repo", "url")),
    "repo_webhook_deliveries": ("repo_hook_deliveries_by_url", ("repo", "url")),
    "bpr": ("branch_protection_rule", ("repo", "pattern")),
    "repo_ruleset": ("repo_ruleset", ("repo", "name")),
    "environment": ("environment", ("repo", "name")),
    "env_branch_policies": ("environment_branch_policies", ("repo", "env")),
    "env_secret": ("environment_secret", ("repo", "env", "name")),
    "env_variable": ("environment_variable", ("repo", "env", "name")),
    "pages": ("pages", ("repo",)),
    "repo_custom_properties": ("repo_custom_property_values", ("repo",)),
    # organization Actions settings (feature lookups: None + unavailable when the plan lacks them)
    "org_selected_actions": ("org_selected_actions", ()),
    "org_actions_selected_repositories": ("org_actions_selected_repositories", ()),
    "org_fork_pr_approval": ("org_fork_pr_approval", ()),
    "org_fork_pr_workflows_private_repos": ("org_fork_pr_workflows_private_repos", ()),
    "org_cache_storage_limit": ("org_cache_storage_limit", ()),
    "org_cache_storage_limit_orgs_path": ("org_cache_storage_limit_orgs_path", ()),
    # organization security, roles, members and invitations
    "security_managers": ("security_managers", ()),
    "org_role_teams": ("org_role_teams", ("name",)),
    "code_security_defaults": ("code_security_default_configurations", ()),
    "code_security_configuration": ("code_security_configuration", ("name",)),
    "org_members": ("members_with_role", ()),
    "org_members_2fa_disabled": ("members_2fa_disabled", ()),
    "org_membership": ("membership", ("login",)),
    "org_invitations": ("org_invitations", ()),
    "org_security_advisories": ("org_security_advisories", ()),
    "team_membership": ("team_membership", ("slug", "login")),
    "team_invitations": ("team_invitations", ("slug",)),
    # repository Actions settings and workflows
    "repo_selected_actions": ("repo_selected_actions", ("repo",)),
    "repo_fork_pr_approval": ("repo_fork_pr_approval", ("repo",)),
    "repo_fork_pr_workflows_private_repos": ("repo_fork_pr_workflows_private_repos", ("repo",)),
    "repo_cache_storage_limit": ("repo_cache_storage_limit", ("repo",)),
    "workflow": ("workflow", ("repo", "workflow")),
    "workflow_runs": ("workflow_runs", ("repo", "workflow")),
    "repo_workflow_runs": ("repo_workflow_runs", ("repo",)),
    # repository security
    "repo_security_and_analysis": ("repo_security_and_analysis", ("repo",)),
    "repo_vulnerability_alerts": ("repo_vulnerability_alerts", ("repo",)),
    "repo_automated_security_fixes": ("repo_automated_security_fixes", ("repo",)),
    "repo_private_vulnerability_reporting": ("repo_private_vulnerability_reporting", ("repo",)),
    "repo_code_scanning_default_setup": ("repo_code_scanning_default_setup", ("repo",)),
    "repo_security_advisories": ("repo_security_advisories", ("repo",)),
    "repo_security_advisory": ("repo_security_advisory", ("repo", "ghsa_id")),
    # repository branches and access
    "repo_branches": ("repo_branches", ("repo",)),
    "repo_branch": ("repo_branch", ("repo", "branch")),
    "repo_default_branch": ("default_branch", ("repo",)),
    "repo_teams": ("repo_teams", ("repo",)),
    "repo_collaborators": ("repo_collaborators", ("repo",)),
    "repo_collaborator_permission": ("repo_collaborator_permission", ("repo", "login")),
    "repo_invitations": ("repo_invitations", ("repo",)),
    # one webhook delivery in full (request headers and payload): the newest of ``event``
    "org_webhook_delivery": ("org_hook_latest_delivery_by_url", ("url", "event")),
    "repo_webhook_delivery": ("repo_hook_latest_delivery_by_url", ("repo", "url", "event")),
}
# kinds whose lookup returns a list (``absent`` is not allowed for them)
LIST_KINDS = frozenset(
    {
        "org_secret_repos",
        "org_variable_repos",
        "team_members",
        "repo_topics",
        "env_branch_policies",
        "org_webhook_deliveries",
        "repo_webhook_deliveries",
        "org_actions_selected_repositories",
        "security_managers",
        "org_role_teams",
        "code_security_defaults",
        "org_members",
        "org_members_2fa_disabled",
        "org_invitations",
        "org_security_advisories",
        "team_invitations",
        "workflow_runs",
        "repo_workflow_runs",
        "repo_security_advisories",
        "repo_branches",
        "repo_teams",
        "repo_collaborators",
        "repo_invitations",
    }
)
# kinds that never answer None (``absent`` is meaningless): lists and the custom property values mapping
NEVER_NONE_KINDS = LIST_KINDS | {"repo_custom_properties"}
CHECK_FORMS = ("match", "absent", "equals", "contains", "unavailable")
CHECK_OPTIONS = ("timeout", "unavailable_ok")
# absent: true of a nested object proves nothing when its parent is gone: parameter -> (lookup kind, its parameter)
PARENT_LOOKUPS: dict[str, tuple[str, str]] = {"repo": ("repo", "name"), "slug": ("team", "slug")}
MATCH_SPECIALS = ("$regex", "$exists", "$unordered", "$len")
DEFAULT_TIMEOUT = 60.0
DEFAULT_INTERVAL = 5.0
_MISSING = object()  # a key absent from the actual mapping
# GitHubError/NotImplementedError are RuntimeErrors; requests exceptions are OSErrors
_LOOKUP_ERRORS = (RuntimeError, LookupError, TypeError, ValueError, AttributeError, OSError)
_SHORT = 120


class CheckError(ValueError):
    """A malformed check (unknown kind, missing parameter, bad form or operator)."""


INFRA_PREFIX = "[infra]"  # problems caused by the infrastructure (network, 5xx, rate limits), never product defects
_INFRA_STATUSES = frozenset({429, 500, 502, 503, 504})


@dataclass
class CheckResult:
    """Outcome of one check: ok, the check itself, a human message and the observed value; ``error`` marks a check
    that could not be evaluated (malformed check, failed lookup: a harness or infrastructure problem, never the
    expected failure of a known bug)."""

    ok: bool
    check: dict[str, Any]
    message: str
    actual: Any = None
    error: bool = False


def lookup_error_message(label: str, exc: BaseException) -> str:
    """Message of a failed lookup; network errors, 5xx and rate limits are tagged INFRA_PREFIX."""
    text = f"{label}: lookup failed: {type(exc).__name__}: {REDACTOR(str(exc))}"
    status = getattr(exc, "status", None)
    infra = isinstance(exc, OSError) or (isinstance(status, int) and status in _INFRA_STATUSES)
    return f"{INFRA_PREFIX} {text}" if infra else text


# --- validation ------------------------------------------------------------------------------------------------------
def validate_check(check: Mapping[str, Any]) -> None:
    """ValueError unless ``check`` is a well-formed check (known kind, its parameters, exactly one form)."""
    if not isinstance(check, Mapping):
        raise CheckError(f"a check must be a mapping, got {type(check).__name__}")
    kind = check.get("kind")
    if kind not in CHECK_KINDS:
        raise CheckError(f"unknown check kind {kind!r}, expected one of {sorted(CHECK_KINDS)}")
    params = CHECK_KINDS[kind][1]
    unknown = sorted(set(check) - {"kind", *params, *CHECK_FORMS, *CHECK_OPTIONS})
    if unknown:
        raise CheckError(f"check {kind!r}: unknown key(s) {unknown} (parameters: {list(params)}, forms: {CHECK_FORMS})")
    missing = [name for name in params if not isinstance(check.get(name), str) or not check[name]]
    if missing:
        raise CheckError(f"check {kind!r}: parameter(s) {missing} must be non-empty strings")
    forms = [form for form in CHECK_FORMS if form in check]
    if len(forms) != 1:
        raise CheckError(f"check {kind!r}: exactly one of {list(CHECK_FORMS)} is required, got {forms}")
    _validate_form(kind, forms[0], check[forms[0]])
    timeout = check.get("timeout")
    if timeout is not None and (isinstance(timeout, bool) or not isinstance(timeout, int | float) or timeout <= 0):
        raise CheckError(f"check {kind!r}: timeout must be a positive number, got {timeout!r}")


def _validate_form(kind: str, form: str, value: Any) -> None:
    """ValueError for a malformed form value."""
    if form in ("absent", "unavailable") and not isinstance(value, bool):
        raise CheckError(f"check {kind!r}: {form} must be true or false")
    if form == "absent" and kind in NEVER_NONE_KINDS:
        raise CheckError(f"check {kind!r}: absent is only valid for single-object kinds (use equals: [] or $len)")
    if form in ("match", "contains", "equals"):
        _validate_specials(value, f"check {kind!r} {form}")


def _validate_specials(value: Any, where: str) -> None:
    """ValueError for malformed match operators anywhere inside ``value``."""
    if isinstance(value, Mapping):
        if _is_operator(value):
            _validate_operator(value, where)
            return
        for item in value.values():
            _validate_specials(item, where)
    elif isinstance(value, list):
        for item in value:
            _validate_specials(item, where)


def _validate_operator(operator: Mapping[str, Any], where: str) -> None:
    """ValueError for unknown operators or bad operands."""
    unknown = sorted(set(operator) - set(MATCH_SPECIALS))
    if unknown or any(not str(key).startswith("$") for key in operator):
        raise CheckError(f"{where}: unknown operator(s) {unknown or sorted(operator)}, expected {MATCH_SPECIALS}")
    if "$regex" in operator:
        try:
            re.compile(_operand(operator["$regex"], str, "$regex", where))
        except re.error as exc:
            raise CheckError(f"{where}: invalid $regex: {exc}") from None
    if "$exists" in operator:
        _operand(operator["$exists"], bool, "$exists", where)
    if "$len" in operator and (_operand(operator["$len"], int, "$len", where) < 0):
        raise CheckError(f"{where}: $len must not be negative")
    if "$unordered" in operator:
        _validate_specials(_operand(operator["$unordered"], list, "$unordered", where), where)


def _operand(value: Any, expected: type, name: str, where: str) -> Any:
    """The operand of an operator, type-checked (booleans are not integers here)."""
    if not isinstance(value, expected) or (expected is int and isinstance(value, bool)):
        raise CheckError(f"{where}: {name} expects a {expected.__name__}, got {value!r}")
    return value


# --- matching --------------------------------------------------------------------------------------------------------
def subset_mismatches(expected: Any, actual: Any, path: str = "$") -> list[str]:
    """Paths (``$.a[0].b``) where ``actual`` does not contain ``expected`` (mappings: subset; specials supported)."""
    if isinstance(expected, Mapping) and _is_operator(expected):
        return _operator_mismatches(expected, actual, path)
    if actual is _MISSING:
        return [f"{path}: missing"]
    if isinstance(expected, Mapping):
        if not isinstance(actual, Mapping):
            return [f"{path}: expected a mapping, got {_short(actual)}"]
        problems: list[str] = []
        for key, value in expected.items():
            problems += subset_mismatches(value, actual.get(key, _MISSING), f"{path}.{key}")
        return problems
    if isinstance(expected, list):
        if not isinstance(actual, list | tuple):
            return [f"{path}: expected a list, got {_short(actual)}"]
        if len(expected) != len(actual):
            return [f"{path}: expected {len(expected)} item(s), got {len(actual)}: {_short(actual)}"]
        problems = []
        for index, (item, actual_item) in enumerate(zip(expected, actual, strict=True)):
            problems += subset_mismatches(item, actual_item, f"{path}[{index}]")
        return problems
    return [] if _scalar_equal(expected, actual) else [f"{path}: expected {_short(expected)}, got {_short(actual)}"]


def _is_operator(value: Mapping[str, Any]) -> bool:
    """True for a mapping of match operators (any key starting with ``$``)."""
    return bool(value) and any(isinstance(key, str) and key.startswith("$") for key in value)


def _operator_mismatches(operator: Mapping[str, Any], actual: Any, path: str, *, exact: bool = False) -> list[str]:
    """Mismatches of every operator of ``operator`` against ``actual`` (``exact``: the items of ``$unordered`` are
    compared with exact_equal, as inside ``equals``; otherwise with the subset match)."""
    problems: list[str] = []
    if "$exists" in operator:
        present = actual is not _MISSING and actual is not None
        if present != operator["$exists"]:
            problems.append(f"{path}: expected {'present' if operator['$exists'] else 'absent'}, got {_short(actual)}")
    if actual is _MISSING:
        return problems if set(operator) == {"$exists"} else [*problems, f"{path}: missing"]
    if "$regex" in operator and not (isinstance(actual, str) and re.search(operator["$regex"], actual)):
        problems.append(f"{path}: {_short(actual)} does not match /{operator['$regex']}/")
    if "$len" in operator:
        size = len(actual) if isinstance(actual, str | list | tuple | Mapping) else None
        if size != operator["$len"]:
            problems.append(f"{path}: expected length {operator['$len']}, got {size} ({_short(actual)})")
    if "$unordered" in operator:
        problems += _unordered_mismatches(operator["$unordered"], actual, path, exact=exact)
    return problems


def _unordered_mismatches(expected: Sequence[Any], actual: Any, path: str, *, exact: bool = False) -> list[str]:
    """Same length and a one-to-one matching in any order (subset match, or exact_equal when ``exact``)."""
    if not isinstance(actual, list | tuple):
        return [f"{path}: expected a list, got {_short(actual)}"]
    if len(expected) != len(actual):
        return [f"{path}: expected {len(expected)} item(s) in any order, got {len(actual)}: {_short(actual)}"]
    unmatched = _unmatched(list(expected), list(actual), exact=exact)
    return [f"{path}: no distinct item matches {_short(expected[index])}" for index in unmatched]


def _unmatched(expected: list[Any], actual: list[Any], *, exact: bool = False) -> list[int]:
    """Indexes of expected items left unmatched by a maximum one-to-one matching (Kuhn's algorithm)."""
    if exact:
        fits = [[exact_equal(item, candidate) for candidate in actual] for item in expected]
    else:
        fits = [[not subset_mismatches(item, candidate) for candidate in actual] for item in expected]
    owner: dict[int, int] = {}

    def assign(index: int, visited: set[int]) -> bool:
        """Augmenting path for expected item ``index``."""
        for candidate, fit in enumerate(fits[index]):
            if fit and candidate not in visited:
                visited.add(candidate)
                if candidate not in owner or assign(owner[candidate], visited):
                    owner[candidate] = index
                    return True
        return False

    return [index for index in range(len(expected)) if not assign(index, set())]


def _scalar_equal(expected: Any, actual: Any) -> bool:
    """Equality where booleans only equal booleans (``True != 1``)."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return isinstance(expected, bool) and isinstance(actual, bool) and expected == actual
    return bool(expected == actual)


def exact_equal(expected: Any, actual: Any) -> bool:
    """Deep equality for ``equals`` (lists and tuples alike, booleans never equal numbers). The match operators work
    inside it: ``{$regex}``, ``{$len}`` and ``{$exists}`` test the value at their place (``$exists: false`` also lets
    the key be missing), ``{$unordered: [...]}`` needs the same items, each exactly equal, in any order."""
    if isinstance(expected, Mapping) and _is_operator(expected):
        return not _operator_mismatches(expected, actual, "$", exact=True)
    if actual is _MISSING:
        return False
    if isinstance(expected, Mapping) and isinstance(actual, Mapping):
        optional = {key for key, value in expected.items() if _may_be_missing(value)}
        if not set(expected) - optional <= set(actual) <= set(expected):
            return False
        return all(exact_equal(value, actual.get(key, _MISSING)) for key, value in expected.items())
    if isinstance(expected, list | tuple) and isinstance(actual, list | tuple):
        return len(expected) == len(actual) and all(exact_equal(a, b) for a, b in zip(expected, actual, strict=True))
    if isinstance(expected, Mapping | list | tuple) or isinstance(actual, Mapping | list | tuple):
        return False
    return _scalar_equal(expected, actual)


def _may_be_missing(value: Any) -> bool:
    """True for an operator mapping that holds for a missing key (``{$exists: false}``)."""
    return isinstance(value, Mapping) and _is_operator(value) and value.get("$exists") is False and len(value) == 1


def _short(value: Any) -> str:
    """Bounded repr of a value for messages."""
    if value is _MISSING:
        return "<missing>"
    text = repr(value)
    return text if len(text) <= _SHORT else text[: _SHORT - 3] + "..."


# --- evaluation ------------------------------------------------------------------------------------------------------
def describe_check(check: Mapping[str, Any]) -> str:
    """``kind(param='v', ...)`` label of a check."""
    kind = check.get("kind")
    names = CHECK_KINDS.get(kind, ("", ()))[1] if isinstance(kind, str) else ()
    params = ", ".join(f"{name}={check.get(name)!r}" for name in names)
    return f"{kind}({params})"


def evaluate_check(oracle: Oracle, check: Mapping[str, Any]) -> CheckResult:
    """Evaluate one check once (unknown kind or bad form -> ok False with an explanatory message)."""
    data = dict(check)
    label = describe_check(data)
    try:
        validate_check(data)
    except ValueError as exc:
        return CheckResult(False, data, f"{label}: invalid check: {exc}", error=True)
    kind = data["kind"]
    params = {name: data[name] for name in CHECK_KINDS[kind][1]}
    try:
        actual, unavailable = _lookup(oracle, kind, params)
    except _LOOKUP_ERRORS as exc:  # a failed lookup is a failed (retryable) check, never a crash
        return CheckResult(False, data, lookup_error_message(label, exc), error=True)
    form = next(form for form in CHECK_FORMS if form in data)
    problems = _FORMS[form](data[form], actual, unavailable)
    strict = not data.get("unavailable_ok")
    if unavailable and form != "unavailable" and (problems or (strict and form in ("absent", "equals"))):
        # an absent or empty answer of a listing that answered 403/404/409 is not evidence (BAT-11)
        problems.append(f"listing unavailable ({_statuses(unavailable)}): the answer cannot be trusted")
    if not problems and strict and form == "absent" and data[form] is True:
        try:
            problems += _missing_parents(oracle, kind, params)
        except _LOOKUP_ERRORS as exc:
            return CheckResult(False, data, lookup_error_message(label, exc), error=True)
    message = f"{label}: ok" if not problems else f"{label}: " + "; ".join(problems)
    return CheckResult(not problems, data, REDACTOR(message), normalize(actual))


def _missing_parents(oracle: Oracle, kind: str, params: Mapping[str, str]) -> list[str]:
    """Problems of an ``absent: true`` check whose parent objects (the repository, the team, the environment) do not
    exist: a nested object is trivially absent then (BAT-11)."""
    parents = [
        (parent_kind, params[name], {parent_param: params[name]})
        for name, (parent_kind, parent_param) in PARENT_LOOKUPS.items()
        if name in params and parent_kind != kind
    ]
    if "env" in params and "repo" in params:
        parents.append(("environment", params["env"], {"repo": params["repo"], "name": params["env"]}))
    return [
        f"its parent {parent_kind} {value!r} does not exist (absence proves nothing)"
        for parent_kind, value, lookup in parents
        if oracle.lookup(parent_kind, **lookup) is None
    ]


class _UnavailableTracker(dict[Any, int]):
    """A copy of ``Oracle.unavailable`` remembering what one lookup records (403/404) or clears (available again)."""

    def __init__(self, base: Mapping[Any, int]) -> None:
        """Start from the oracle's current records."""
        super().__init__(base)
        self.written: dict[Any, int] = {}
        self.removed: set[Any] = set()

    def __setitem__(self, key: Any, value: int) -> None:
        """Record a listing answering 403/404."""
        self.written[key] = value
        self.removed.discard(key)
        super().__setitem__(key, value)

    def __delitem__(self, key: Any) -> None:
        """Clear a record."""
        self._forget(key)
        super().__delitem__(key)

    def pop(self, key: Any, *default: Any) -> Any:
        """Clear a record (the listing answered again)."""
        self._forget(key)
        return super().pop(key, *default)

    def _forget(self, key: Any) -> None:
        """Remember that ``key`` was cleared."""
        self.written.pop(key, None)
        self.removed.add(key)


def _lookup(oracle: Oracle, kind: str, params: Mapping[str, str]) -> tuple[Any, dict[Any, int]]:
    """Run the lookup; returns its value and the ``unavailable`` entries (403/404 listings) it recorded."""
    previous = oracle.unavailable
    tracker = _UnavailableTracker(previous)
    oracle.unavailable = tracker
    try:
        value = oracle.lookup(kind, **params)
    finally:
        oracle.unavailable = previous
        for key in tracker.removed:
            previous.pop(key, None)
        previous.update(tracker.written)
    return value, dict(tracker.written)


def _statuses(unavailable: Mapping[Any, int]) -> str:
    """``kind scope: status`` list of recorded unavailable listings."""
    return ", ".join(
        f"{' '.join(map(str, key)) if isinstance(key, tuple) else key}: {status}" for key, status in unavailable.items()
    )


def _form_match(expected: Any, actual: Any, _unavailable: Mapping[Any, int]) -> list[str]:
    """``match``: subset match of an existing value."""
    if actual is None:
        return ["not found"]
    return subset_mismatches(expected, actual)


def _form_absent(expected: bool, actual: Any, _unavailable: Mapping[Any, int]) -> list[str]:
    """``absent``: the lookup answers None (true) or a value (false)."""
    if expected and actual is not None:
        return [f"expected absent, found {_short(normalize(actual))}"]
    if not expected and actual is None:
        return ["expected present, not found"]
    return []


def _form_equals(expected: Any, actual: Any, _unavailable: Mapping[Any, int]) -> list[str]:
    """``equals``: exact comparison."""
    return [] if exact_equal(expected, actual) else [f"expected exactly {_short(expected)}, got {_short(actual)}"]


def _form_contains(expected: Any, actual: Any, _unavailable: Mapping[Any, int]) -> list[str]:
    """``contains``: list elements (subset match), substrings or mapping keys."""
    items = expected if isinstance(expected, list) else [expected]
    if actual is None:
        return ["not found"]
    if isinstance(actual, str):
        return [
            f"{_short(item)} not in {_short(actual)}"
            for item in items
            if not (isinstance(item, str) and item in actual)
        ]
    if isinstance(actual, Mapping):
        keys = {str(key) for key in actual}
        return [f"key {_short(item)} not in {_short(sorted(keys))}" for item in items if str(item) not in keys]
    if isinstance(actual, list | tuple):
        return [
            f"no item matches {_short(item)} in {_short(actual)}"
            for item in items
            if not any(not subset_mismatches(item, candidate) for candidate in actual)
        ]
    return [f"cannot look for items in {_short(actual)}"]


def _form_unavailable(expected: bool, _actual: Any, unavailable: Mapping[Any, int]) -> list[str]:
    """``unavailable``: the listing answered 403/404 (true) or not (false)."""
    if expected and not unavailable:
        return ["expected the listing to be unavailable (403/404), it answered"]
    if not expected and unavailable:
        return [f"expected the listing to be available, got {_statuses(unavailable)}"]
    return []


_FORMS: dict[str, Callable[[Any, Any, Mapping[Any, int]], list[str]]] = {
    "match": _form_match,
    "absent": _form_absent,
    "equals": _form_equals,
    "contains": _form_contains,
    "unavailable": _form_unavailable,
}


def evaluate_checks(
    oracle: Oracle, checks: Sequence[Mapping[str, Any]], *, timeout: float = 60, interval: float = 5
) -> list[CheckResult]:
    """Evaluate all checks, re-evaluating the failing ones every ``interval`` s until all pass or ``timeout``."""
    return wait_for_checks(oracle, checks, timeout=timeout, interval=interval)


def wait_for_checks(
    oracle: Oracle,
    checks: Sequence[Mapping[str, Any]],
    *,
    timeout: float = DEFAULT_TIMEOUT,
    interval: waiting.Interval = DEFAULT_INTERVAL,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> list[CheckResult]:
    """evaluate_checks with injectable sleep/clock; the budget is the largest of ``timeout`` and per-check timeouts."""
    results = [evaluate_check(oracle, check) for check in checks]
    budget = max([float(timeout), *(_check_timeout(check) for check in checks)])
    deadline = waiting.Deadline(budget, clock=clock)
    delays = waiting.intervals(interval)
    while not all(result.ok for result in results) and not deadline.expired():
        sleep(min(next(delays), deadline.remaining()))
        results = [result if result.ok else evaluate_check(oracle, result.check) for result in results]
    return results


def _check_timeout(check: Any) -> float:
    """Per-check ``timeout`` (0 when absent or invalid)."""
    value = check.get("timeout") if isinstance(check, Mapping) else None
    if isinstance(value, bool) or not isinstance(value, int | float):
        return 0.0
    return max(0.0, float(value))
