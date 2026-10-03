"""otterdog output parsing and normalization against REAL captured samples (tests/unit/data, otterdog 1.7.0.dev19)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from otterdog_e2e.naming import RunContext
from otterdog_e2e.otterdog.output import (
    HEADER_RE,
    UNKNOWN_PROPERTIES_RE,
    Message,
    NormalizeContext,
    normalize_text,
    parse_apply,
    parse_messages,
    parse_plan,
    parse_validation,
    strip_ansi,
    unbox,
)

DATA = Path(__file__).parent / "data"
INDEX: dict[str, dict] = json.loads((DATA / "samples.json").read_text(encoding="utf-8"))
RUN = RunContext("t3c7z8a5")
LOOSE_HEADER_RE = re.compile(r"^\s*(?:\+ add|- remove|~|!) [a-z_]+(?:\[.*\])? \{$")


def sample(name: str) -> str:
    """Text of a golden sample."""
    return (DATA / f"{name}.txt").read_text(encoding="utf-8")


def samples_of(*commands: str) -> list[str]:
    """Names of the samples produced by the given otterdog commands."""
    return sorted(name for name, entry in INDEX.items() if entry["argv"][1] in commands)


def objects(name: str) -> list[tuple[str, str, str, str | None]]:
    """(op, kind, value, parent) of every object of a plan sample."""
    return [(obj.op, obj.kind, obj.value, obj.parent) for obj in parse_plan(sample(name)).objects]


def test_index_describes_every_sample() -> None:
    """Each indexed sample exists, real samples come from otterdog runs, synthetic ones are flagged."""
    assert len(INDEX) >= 40
    for name, entry in INDEX.items():
        assert (DATA / f"{name}.txt").is_file(), name
        assert entry["argv"][0] == "otterdog" and entry["description"]
        for key in ("config", "base", "json"):
            if entry.get(key):
                assert (DATA / entry[key]).is_file(), (name, key)
    assert {name for name, entry in INDEX.items() if entry["synthetic"]} == {
        "apply-executed",
        "apply-executed-ignored",
        "apply-failed-patch",
        "check-status",
        "check-status-out-of-sync",
    }


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("validate-ok", (True, 0, 0, 0, False)),
        ("validate-infos-hidden", (True, None, 0, 0, False)),
        ("validate-infos-verbose", (True, 2, 0, 0, False)),
        ("validate-warnings", (True, 0, 2, 0, False)),
        ("validate-errors", (False, 1, 0, 3, False)),
        ("validate-790", (False, 0, 0, 1, False)),
        ("validate-plan-gate", (False, 0, 0, 1, False)),
        ("validate-syntax", (False, None, None, None, True)),
        ("validate-schema", (False, None, None, None, True)),
        ("validate-unknown-property", (True, 0, 0, 0, False)),
        ("validate-missing-config", (False, None, None, None, True)),
        ("validate-network", (False, None, None, None, False)),
    ],
)
def test_parse_validation_samples(name: str, expected: tuple[object, ...]) -> None:
    """ok/infos/warnings/errors/load_error of every validate sample (OC-10)."""
    result = parse_validation(sample(name))
    assert (result.ok, result.infos, result.warnings, result.errors, result.load_error) == expected
    assert result.raw == sample(name)


def test_validate_samples_cover_every_validate_capture() -> None:
    """Every captured validate output has an expectation above."""
    covered = set(samples_of("validate"))
    assert covered == {
        "validate-ok",
        "validate-infos-hidden",
        "validate-infos-verbose",
        "validate-warnings",
        "validate-errors",
        "validate-790",
        "validate-plan-gate",
        "validate-syntax",
        "validate-schema",
        "validate-unknown-property",
        "validate-missing-config",
        "validate-network",
    }


def test_validation_messages() -> None:
    """Box messages keep their level and full text (multi-line boxes joined with newlines)."""
    errors = parse_validation(sample("validate-errors")).errors_text()
    assert errors == [
        (
            "org_secret[name=\"E2E_T3C7Z8A5_PRIVATE\"] has 'visibility' of value 'private', which is not available "
            "for an organization with free plan."
        ),
        (
            "use of organization rulesets requires an 'enterprise' plan, while this organization is currently on a "
            "'free' plan."
        ),
        (
            'repository[name="e2e-t3c7z8a5-rs", repository=e2e-t3c7z8a5-rs] has not set required parameter '
            "'required_status_checks.strict'."
        ),
    ]
    syntax = parse_validation(sample("validate-syntax")).messages
    assert len(syntax) == 1 and syntax[0].level == "Error" and syntax[0].source == "box"
    lines = syntax[0].text.splitlines()
    assert lines[0] == "Validation failed"
    assert lines[1].startswith("failed to load configuration: failed to evaluate jsonnet file: syntax error")
    assert re.fullmatch(
        r"/tmp/otterdog-e2e-capture/validate-syntax/orgs/e2e-test-org/e2e-test-org\.jsonnet:\d+:\d+", lines[2]
    )
    infos = parse_validation(sample("validate-infos-verbose")).messages
    assert [message.level for message in infos] == ["Info", "Info"]
    assert infos[1].text == 'repo_secret[name="E2E_T3C7Z8A5_SECRET"] only has a dummy value, resource will be skipped.'


def test_logger_warning_is_a_message_without_source_suffix() -> None:
    """RichHandler lines become Message(level='Warning', source='logger') without the file.py:LINE column (OC-08)."""
    text = sample("validate-unknown-property")
    assert any(line.endswith("github_organization.py:288") for line in text.splitlines())
    (message,) = parse_messages(text)
    assert message == Message(
        "Warning",
        "ignoring unknown properties found while validating organization config: Additional properties are not "
        "allowed ('e2e_unknown_setting' was unexpected)",
        "logger",
    )
    assert UNKNOWN_PROPERTIES_RE.search(message.text)


def test_plain_note_and_warning_messages() -> None:
    """Plain ``Note:``/``Warning:`` lines are messages and are attached to the preceding plan object."""
    readonly = parse_plan(sample("local-plan-readonly"))
    assert readonly.messages == [Message("Note", "setting 'plan' is read-only, will be skipped.", "plain")]
    assert readonly.objects[0].notes == ["Note: setting 'plan' is read-only, will be skipped."]
    hook = parse_plan(sample("local-plan-webhook-secret-removed"))
    warning = "removing secret for webhook with url 'https://otterdog-e2e.invalid/t3c7z8a5/hooks'"
    assert hook.messages == [Message("Warning", warning, "plain")]
    assert hook.objects[0].notes == [f"Warning: {warning}"]


def test_click_usage_error_is_a_plain_error() -> None:
    """click's ``Error:`` line (stderr) is parsed as a plain error message."""
    usage = "Usage: otterdog open-pr [OPTIONS] [ORGANIZATIONS]...\n\nError: Missing option '-b' / '--branch'.\n"
    assert parse_messages(usage) == [Message("Error", "Missing option '-b' / '--branch'.", "plain")]


ADD = [
    ("add", "custom_property", "e2e-t3c7z8a5-tier", None),
    ("add", "org_webhook", "https://otterdog-e2e.invalid/t3c7z8a5/org-hook", None),
    ("add", "org_secret", "E2E_T3C7Z8A5_ORG_SECRET", None),
    ("add", "org_variable", "E2E_T3C7Z8A5_ORG_VAR", None),
    ("add", "repository", "e2e-t3c7z8a5-basic", None),
    ("add", "repo_webhook", "https://otterdog-e2e.invalid/t3c7z8a5/repo-hook", "e2e-t3c7z8a5-basic"),
    ("add", "repo_secret", "E2E_T3C7Z8A5_SECRET", "e2e-t3c7z8a5-basic"),
    ("add", "repo_variable", "E2E_T3C7Z8A5_VAR", "e2e-t3c7z8a5-basic"),
    ("add", "environment", "e2e-t3c7z8a5-env", "e2e-t3c7z8a5-basic"),
    ("add", "branch_protection_rule", "main", "e2e-t3c7z8a5-basic"),
]
NESTED = [
    ("env_secret", "E2E_T3C7Z8A5_ENV_SECRET", "e2e-t3c7z8a5-env"),
    ("env_variable", "E2E_T3C7Z8A5_ENV_VAR", "e2e-t3c7z8a5-env"),
    ("repo_ruleset", "e2e-t3c7z8a5-rs", "e2e-t3c7z8a5-envs"),
]


def test_parse_plan_additions() -> None:
    """Adds of org-level and nested objects, in output order, with their parents."""
    plan = parse_plan(sample("local-plan-add"))
    assert (plan.add, plan.change, plan.delete, plan.aborted) == (10, 0, 0, False)
    assert objects("local-plan-add") == ADD
    assert plan.validation is not None and plan.validation.ok and plan.validation.infos == 2
    repo = plan.objects[4]
    assert repo.header == '+ add repository[name="e2e-t3c7z8a5-basic"] {'
    assert repo.changed_keys[:3] == ["allow_auto_merge", "allow_forking", "allow_merge_commit"]
    assert "workflows" in repo.changed_keys and "max_cache_size_gb" not in repo.changed_keys
    assert any("max_cache_size_gb" in line for line in repo.body)
    assert all(obj.run_id == "t3c7z8a5" for obj in plan.objects)


def test_parse_plan_changes_and_key_counting() -> None:
    """``N to change`` counts changed keys: local-plan-change has 10 keys in 7 objects."""
    plan = parse_plan(sample("local-plan-change"))
    assert (plan.add, plan.change, plan.delete) == (0, 10, 0)
    keys = [(obj.kind, obj.value, obj.changed_keys) for obj in plan.objects]
    assert keys == [
        ("settings", "", ["web_commit_signoff_required"]),
        ("repository", "e2e-t3c7z8a5-basic", ["description", "topics", "web_commit_signoff_required"]),
        ("repo_webhook", "https://otterdog-e2e.invalid/t3c7z8a5/repo-hook", ["events"]),
        ("repo_variable", "E2E_T3C7Z8A5_VAR", ["value"]),
        ("environment", "e2e-t3c7z8a5-env", ["wait_timer"]),
        ("branch_protection_rule", "main", ["required_approving_review_count", "requires_linear_history"]),
        ("repository", "otterdog-e2e-fixture-a", ["web_commit_signoff_required"]),
    ]
    assert plan.objects[0].key == "" and plan.objects[0].parent is None and plan.objects[0].header == "~ settings {"
    run_objects = plan.objects_for(RUN.needles())
    assert [obj.kind for obj in run_objects] == [
        "repository",
        "repo_webhook",
        "repo_variable",
        "environment",
        "branch_protection_rule",
    ]
    assert plan.op_counts(RUN.needles()) == {"add": 0, "remove": 0, "change": 5, "forced": 0}
    assert not plan.is_noop() and not plan.is_noop(RUN.needles())


def test_parse_plan_removals() -> None:
    """Removals of org-level objects, of nested objects of a kept repo and of a whole repo."""
    plan = parse_plan(sample("local-plan-remove"))
    assert (plan.add, plan.change, plan.delete) == (0, 0, 10)
    assert [(obj.kind, obj.value, obj.parent) for obj in plan.removals()] == [
        ("custom_property", "e2e-t3c7z8a5-tier", None),
        ("org_webhook", "https://otterdog-e2e.invalid/t3c7z8a5/org-hook", None),
        ("org_secret", "E2E_T3C7Z8A5_ORG_SECRET", None),
        ("org_variable", "E2E_T3C7Z8A5_ORG_VAR", None),
        ("repo_webhook", "https://otterdog-e2e.invalid/t3c7z8a5/repo-hook", "e2e-t3c7z8a5-basic"),
        ("repo_secret", "E2E_T3C7Z8A5_SECRET", "e2e-t3c7z8a5-basic"),
        ("repo_variable", "E2E_T3C7Z8A5_VAR", "e2e-t3c7z8a5-basic"),
        ("environment", "e2e-t3c7z8a5-env", "e2e-t3c7z8a5-basic"),
        ("branch_protection_rule", "main", "e2e-t3c7z8a5-basic"),
        ("repository", "e2e-t3c7z8a5-gone", None),
    ]
    assert {obj.parent_kind for obj in plan.removals() if obj.parent} == {"repository"}


def test_repo_filter_does_not_scope_org_level_objects() -> None:
    """``-r <repo>`` still removes every org-level object (OC-02): 4 org-level + 1 repo removal."""
    plan = parse_plan(sample("local-plan-remove-filtered"))
    assert plan.delete == 5
    assert [obj.kind for obj in plan.removals()] == [
        "custom_property",
        "org_webhook",
        "org_secret",
        "org_variable",
        "repository",
    ]


def test_whole_repository_removal_is_one_header() -> None:
    """A removed repo with webhooks, secrets, BPRs and environments prints and counts ONE remove block."""
    plan = parse_plan(sample("local-plan-remove-repo"))
    assert plan.delete == 1 and objects("local-plan-remove-repo") == [
        ("remove", "repository", "e2e-t3c7z8a5-basic", None)
    ]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("local-plan-env-nested-add", [("add", kind, value, parent) for kind, value, parent in NESTED]),
        ("local-plan-env-nested-remove", [("remove", kind, value, parent) for kind, value, parent in NESTED]),
        (
            "local-plan-remove-teams",
            [("remove", "team", "e2e-t3c7z8a5-team", None), ("remove", "team", "otterdog-admins", None)],
        ),
        (
            "local-plan-remove-enterprise",
            [("remove", "org_role", "e2e-t3c7z8a5-role", None), ("remove", "org_ruleset", "e2e-t3c7z8a5-org-rs", None)],
        ),
        ("local-plan-description-removed", [("change", "settings", "", None)]),
        (
            "local-plan-forced",
            [
                ("forced", "repo_webhook", "https://otterdog-e2e.invalid/t3c7z8a5/sec-hook", "e2e-t3c7z8a5-sec"),
                ("forced", "repo_secret", "E2E_T3C7Z8A5_PLAIN", "e2e-t3c7z8a5-sec"),
            ],
        ),
        ("local-plan-add-cache-hidden", [("add", "repository", "e2e-t3c7z8a5-basic", None)]),
        ("local-plan-noop", []),
        ("local-plan-cache-limit-hidden", []),
    ],
)
def test_parse_plan_objects(name: str, expected: list[tuple[str, str, str, str | None]]) -> None:
    """Objects of the remaining plan samples."""
    assert objects(name) == expected


def test_environment_parent_of_env_objects() -> None:
    """env secrets/variables are parented by their environment, not by the repository."""
    plan = parse_plan(sample("local-plan-env-nested-remove"))
    assert [obj.parent_kind for obj in plan.objects] == ["environment", "environment", "repository"]


def test_read_only_change_is_a_noop() -> None:
    """``~ plan`` + Note read-only: object present, 0 to change, is_noop (OC-10)."""
    plan = parse_plan(sample("local-plan-readonly"))
    (obj,) = plan.objects
    assert (obj.op, obj.kind, obj.changed_keys, obj.read_only_keys) == ("change", "settings", ["plan"], ["plan"])
    assert obj.is_read_only and (plan.add, plan.change, plan.delete) == (0, 0, 0)
    assert plan.is_noop() and plan.is_noop(RUN.needles())


def test_description_removal_is_a_settings_change() -> None:
    """A wiped description shows as ``- description = ...`` inside ``~ settings`` (OC-01)."""
    (obj,) = parse_plan(sample("local-plan-description-removed")).objects
    assert obj.changed_keys == ["description"] and obj.body[0].lstrip().startswith("- description = ")


def test_forced_updates_count_every_key() -> None:
    """``!`` blocks list every key; all of them are counted."""
    plan = parse_plan(sample("local-plan-forced"))
    assert plan.change == 9 and sum(len(obj.changed_keys) for obj in plan.objects) == 9
    assert plan.validation is not None and plan.validation.warnings == 2


def test_hidden_cache_limit_never_reaches_otterdog() -> None:
    """With hide_cache_limit the added repo's workflows block has no max_cache_size_gb (OC-06)."""
    (repo,) = parse_plan(sample("local-plan-add-cache-hidden")).objects
    assert not any("max_cache_size_gb" in line for line in repo.body)
    assert parse_plan(sample("local-plan-cache-limit-hidden")).is_noop()


@pytest.mark.parametrize("name", ["local-plan-validation-error", "plan-validation-error"])
def test_validation_errors_abort_the_plan(name: str) -> None:
    """``Planning aborted due to validation errors.``: no counts, aborted, validation errors counted."""
    plan = parse_plan(sample(name))
    assert (plan.add, plan.change, plan.delete, plan.aborted, plan.objects) == (None, None, None, True, [])
    assert plan.validation is not None
    assert (plan.validation.ok, plan.validation.errors, plan.validation.load_error) == (False, 1, False)
    assert not plan.is_noop()


def test_missing_base_is_not_a_validation_failure() -> None:
    """local-plan without -BASE: validation passed, the current configuration could not be loaded."""
    plan = parse_plan(sample("local-plan-missing-base"))
    assert plan.aborted and plan.add is None
    assert plan.validation is not None and plan.validation.ok and not plan.validation.load_error
    assert plan.messages[0].text.startswith("failed to load current configuration\nconfiguration file")


def test_network_error_leaves_validation_unknown() -> None:
    """An offline ``plan -n`` stops on the network: aborted, validation None."""
    plan = parse_plan(sample("plan-network"))
    assert plan.aborted and plan.validation is None
    assert plan.messages == [
        Message(
            "Error",
            "Cannot connect to host api.github.com:443 ssl:default [Temporary failure in name resolution]",
            "box",
        )
    ]


def test_unknown_property_plan_keeps_logger_warning() -> None:
    """A misplaced fragment only shows as a logger warning; the plan itself is a no-op (OC-05/OC-08)."""
    plan = parse_plan(sample("local-plan-unknown-property"))
    assert plan.is_noop()
    assert [(m.level, m.source) for m in plan.messages] == [("Warning", "logger")]
    assert UNKNOWN_PROPERTIES_RE.search(plan.messages[0].text)


@pytest.mark.parametrize("name", samples_of("local-plan", "plan", "local-apply"))
def test_plan_invariants(name: str) -> None:
    """Every printed header parses, counts match objects: adds, removes (nested incl.) and non-read-only keys."""
    text = sample(name)
    headers = [line for line in strip_ansi(text).splitlines() if LOOSE_HEADER_RE.match(line)]
    assert all(HEADER_RE.match(line) for line in headers), headers
    plan = parse_plan(text)
    assert len(plan.objects) == len(headers)
    if plan.add is None:
        return
    assert plan.add == sum(obj.op == "add" for obj in plan.objects)
    assert plan.delete == len(plan.removals())
    modified = [obj for obj in plan.objects if obj.op in ("change", "forced")]
    assert plan.change == sum(len(set(obj.changed_keys) - set(obj.read_only_keys)) for obj in modified)


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("apply-executed", (8, 0, 1, 0, False, False, 0, [])),
        ("apply-executed-ignored", (8, 0, 0, 1, False, False, 1, [])),
        ("apply-failed-patch", (8, 0, 1, 0, False, False, 0, ['ADD - repository[name="e2e-t3c7z8a5-basic"]'])),
        ("apply-validation-error", (0, 0, 0, 0, True, True, 0, [])),
        ("local-apply-no-changes", (0, 0, 0, 1, True, False, 1, [])),
        ("apply-network", (None, None, None, None, False, False, None, [])),
        ("local-apply-network", (None, None, None, None, False, False, None, [])),
    ],
)
def test_parse_apply_samples(name: str, expected: tuple[object, ...]) -> None:
    """added/changed/deleted/ignored/no_changes/aborted_validation/pending_deletions/failed_patches."""
    result = parse_apply(sample(name))
    actual = (
        result.added,
        result.changed,
        result.deleted,
        result.ignored,
        result.no_changes,
        result.aborted_validation,
        result.pending_deletions,
        result.failed_patches,
    )
    assert actual == expected
    assert result.raw == sample(name)


def test_failed_patch_message_keeps_github_error() -> None:
    """The failed-patch box carries the GitHub error below the patch line."""
    (message,) = parse_apply(sample("apply-failed-patch")).messages
    assert message.level == "Error"
    assert message.text.splitlines()[1] == "failed to add repo with name 'e2e-test-org/e2e-t3c7z8a5-basic':"


def test_check_status_json_samples() -> None:
    """check-status -j writes a JSON LIST of per-org status objects."""
    for name, in_sync in (("check-status", True), ("check-status-out-of-sync", False)):
        (entry,) = json.loads((DATA / f"{name}.json").read_text(encoding="utf-8"))
        assert entry["org_id"] == "e2e-test-org" and entry["sync_status"]["in_sync"] is in_sync
        assert f"Synchronization status: {in_sync}" in sample(name)


# --- normalization ---------------------------------------------------------------------------------------------
def test_strip_ansi() -> None:
    """SGR, cursor and OSC sequences are removed."""
    assert strip_ansi("\x1b[31mError\x1b[0m: \x1b[1mbold\x1b[22m\x1b[2K\x1b]8;;http://x\x1b\\link\x1b]8;;\x1b\\") == (
        "Error: boldlink"
    )


def test_unbox_messages_and_keep_tables() -> None:
    """Boxes become ``Level: text`` lines; the list-projects table (│ without ╷) is untouched."""
    unboxed = unbox(sample("validate-syntax"))
    assert "╷" not in unboxed and "│" not in unboxed and "╵" not in unboxed
    assert "Error: Validation failed\nfailed to load configuration: " in unboxed
    table = sample("list-projects")
    assert unbox(table) == table and "│ e2e-test-org │ e2e-test-org │     1 │" in table


def test_normalize_text_logger_lines_and_boxes() -> None:
    """Logger suffix/padding removed, boxes unboxed, trailing spaces dropped."""
    normalized = normalize_text(sample("validate-unknown-property"))
    assert (
        "WARNING ignoring unknown properties found while validating organization config: Additional properties are "
        "not allowed ('e2e_unknown_setting' was unexpected)\n"
    ) in normalized
    assert "github_organization.py" not in normalized
    errors = normalize_text(sample("validate-errors"))
    assert "Error: use of organization rulesets requires an 'enterprise' plan, while this organization is " in errors
    assert all(line == line.rstrip() for line in errors.splitlines())


def test_normalize_text_sorts_logger_runs_and_collapses_blanks() -> None:
    """Consecutive logger lines are sorted (concurrent repo loading, OC-08); blank runs collapse to one."""
    text = "x\nWARNING  zeta     a.py:1\nWARNING  alpha     b.py:22\ny   \n\n\n\nz\n\n"
    assert normalize_text(text) == "x\nWARNING alpha\nWARNING zeta\ny\n\nz\n"


def test_normalize_text_progress_bars() -> None:
    """Real (``11% -:--:--``) and finished (``100% 0:00:00``) progress bars become <PROGRESS>."""
    for name in ("local-apply-network", "apply-executed"):
        normalized = normalize_text(sample(name))
        assert "<PROGRESS>" in normalized and "━" not in normalized


def test_normalize_text_context_replacements() -> None:
    """With a context: literals (longest first), then <SHA>, <TS>, <DUR>, <TMP>; without: nothing replaced."""
    sha = "0123456789abcdef0123456789abcdef01234567"
    text = f"commit {sha} at 2026-10-02T12:00:00Z took 1.5s in /tmp/run/x/y and /scratch/run/abc/cli\n"
    ctx = NormalizeContext([("/scratch/run", "<A>"), ("/scratch/run/abc", "<B>")])
    assert normalize_text(text, ctx) == "commit <SHA> at <TS> took <DUR> in <TMP> and <B>/cli\n"
    assert normalize_text(text) == text
    paths = NormalizeContext.for_paths(Path("/scratch/run/abc"))
    assert normalize_text(text, paths).endswith("and <TMP>/cli\n")
    syntax = normalize_text(sample("validate-syntax"), NormalizeContext())
    assert re.search(r"^<TMP>:\d+:\d+$", syntax, re.MULTILINE) and "/tmp/otterdog-e2e-capture" not in syntax


def test_normalize_text_sorts_printed_sets_in_observations() -> None:
    """KB-038: values otterdog prints from Python sets come in a hash-seed dependent order; observations sort them
    (set reprs and the code scanning '"a" | "b"' list), plain matching keeps the text as printed."""
    first = (
        "Error: settings has 'workflows.fork_pr_approval_policy' of value 'x', while only values "
        "{'first_time_contributors', 'all_external_contributors', 'first_time_contributors_new_to_github'} are allowed."
    )
    second = first.replace(
        "{'first_time_contributors', 'all_external_contributors', 'first_time_contributors_new_to_github'}",
        "{'all_external_contributors', 'first_time_contributors_new_to_github', 'first_time_contributors'}",
    )
    ctx = NormalizeContext()
    assert normalize_text(first, ctx) == normalize_text(second, ctx)
    assert "{'all_external_contributors', 'first_time_contributors', 'first_time_contributors_new_to_github'}" in (
        normalize_text(second, ctx)
    )
    assert normalize_text(first) != normalize_text(second)  # matching sees the real output
    languages = 'only values ("python" | "go" | "actions") are allowed.'
    assert normalize_text(languages, ctx).strip() == 'only values ("actions" | "go" | "python") are allowed.'
    plain = "values ('PR_TITLE' | 'COMMIT_OR_PR_TITLE') and {'only': 'a dict'}"
    assert normalize_text(plain, ctx).strip() == plain  # single-quoted alternatives and dict reprs are kept


@pytest.mark.parametrize("name", sorted(INDEX))
def test_normalize_text_is_idempotent(name: str) -> None:
    """Normalizing twice changes nothing (observations stay comparable)."""
    once = normalize_text(sample(name))
    assert normalize_text(once) == once
