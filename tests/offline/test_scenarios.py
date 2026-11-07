"""Offline tier: every YAML scenario of scenarios/offline against the SUT CLI (SPEC 12.3, 12.4, 19).

Offline steps share no state, so every step is a case of its own: one ``test_offline_scenario[<id>/<step>]`` item
(collect.scenario_params per_step), whose result never depends on another step of the scenario. OfflineEngine runs,
per case, validate --local, local-plan --local (steps with base_fragments), show --local and the
step's extra commands on the minimal e2e-offline organization with the SUT's own standard template vendored. Failures
of the scenario's expectations fail the item with the outcome summary (output tails included). Offline items are
exempt from --e2e-tags: the offline regression tier always runs in full (selection still honours --e2e-scenario).

Some behaviour legitimately depends on the SUT's history (a fix that is in some SUTs and not in others). Such steps
leave the varying expectation out of the YAML and SUT_EXPECTATIONS (keyed by scenario id and step) asserts the outcome
that matches the SUT under test, decided by the ancestry of the fix commit in the upstream mirror (conftest.SutHistory). A known upstream defect
detected that way is reported as an expected failure (pytest.xfail) and the item passes again once it is fixed.
"""

from __future__ import annotations

import functools
import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import pytest

from otterdog_acceptance.context import get_context
from otterdog_acceptance.otterdog.output import normalize_text
from otterdog_acceptance.otterdog.runner import CliResult
from otterdog_acceptance.scenarios.collect import collect_scenarios, generate_scenario_tests
from otterdog_acceptance.scenarios.engine import StepOutcome
from otterdog_acceptance.scenarios.model import Scenario
from otterdog_acceptance.scenarios.offline import OfflineEngine, offline_run_context
from otterdog_acceptance.sut.template import PUBLISHED_TEMPLATE_FILE

# eclipse-csi/otterdog#790 "fix: validate required status checks of rulesets" (squash commit on main)
FIX_790 = "9bdeb75f3e82a6cbd107d6bc3c9ec90392475c08"
MISSING_STRICT = "has not set required parameter 'required_status_checks.strict'."
PLANNING_ABORTED = "Planning aborted due to validation errors"
# #790 validates org rulesets with the organization as parent object, which has no get_model_header (upstream defect)
ORG_RULESET_CRASH = "object has no attribute 'get_model_header'"
# eclipse-csi/otterdog#777 (squash commit on main): a jsonschema error of the configuration becomes a load error
# ("Validation failed" + "failed to load configuration: invalid value at '<path>': <message>", exit 1) instead of an
# escaped exception ("Error: <message>" with the schema path, exit 2)
FIX_777 = "7ffc5e5d8bf8a7db7d2757a3fa40af89dc98e6e3"
SCHEMA_LOAD_ERROR = "failed to load configuration: invalid value at '"
# scenario -> step -> (schema message, schema path printed before #777); the YAML keeps the SUT-neutral part
SCHEMA_ERROR_STEPS: dict[str, dict[str, tuple[str, str]]] = {
    "O-EXTEND-REPO": {
        "extension-without-definition": (
            "'private' is a required property",
            "schema['properties']['repositories']['items']",
        ),
    },
    "O-SHOW-ROLE-FIELDS": {
        "visibility-refused": (
            "Unevaluated properties are not allowed ('visibility' was unexpected)",
            "schema['properties']['roles']['items']",
        ),
        "selected-repositories-refused": (
            "Unevaluated properties are not allowed ('selected_repositories' was unexpected)",
            "schema['properties']['roles']['items']",
        ),
    },
    "O-VAL-SCHEMA": {
        "unknown-repository-secret-key": (
            "Unevaluated properties are not allowed ('foo' was unexpected)",
            "['repositories']['items']['properties']['secrets']['items']",
        ),
        "unknown-org-variable-key": (
            "Unevaluated properties are not allowed ('foo' was unexpected)",
            "schema['properties']['variables']['items']",
        ),
        "unknown-ruleset-key": (
            "Unevaluated properties are not allowed ('foo' was unexpected)",
            "['repositories']['items']['properties']['rulesets']['items']",
        ),
        "unknown-role-key": (
            "Unevaluated properties are not allowed ('foo' was unexpected)",
            "schema['properties']['roles']['items']",
        ),
        "unknown-org-workflows-key": (
            "Unevaluated properties are not allowed ('foo' was unexpected)",
            "schema['properties']['settings']['properties']['workflows']",
        ),
        "unknown-repository-workflows-key": (
            "Unevaluated properties are not allowed ('foo' was unexpected)",
            "['repositories']['items']['properties']['workflows']",
        ),
        "wrong-type": ("123 is not of type 'boolean'", "['repositories']['items']['properties']['has_wiki']"),
        "secret-without-value": ("None is not of type 'string'", "['secrets']['items']['properties']['value']"),
        "values-editable-by": (
            "'anyone' is not ",  # anyOf message before #777, enum message ("is not one of [...]") since
            "['custom_properties']['items']['properties']['values_editable_by']",
        ),
    },
}


# eclipse-csi/otterdog#878 "Configuration guides playground" (squash commit on main, v1.7.0): the JSON schemas enumerate
# the allowed values of most string settings, so an invalid value is a load error ("Validation failed" + "failed to
# load configuration: invalid value at '<path>': '<value>' is not one of [...]", exit 1, #777) and the model's own
# check of the value, which the YAML asserted before, can no longer be reached from the CLI
FIX_878 = "a26b5433c11028ea706bf52ceccd7cea5a12d2b6"
OFFLINE_RUN = offline_run_context()


@dataclass(frozen=True)
class EnumSchemaStep:
    """The SUT-dependent outcome of a step with a value the schema enumerates since #878 (``{{ p }}``/``{{ P }}`` are
    the offline names, like in the YAML, and ``{{ hook_base }}``).

    ``path``/``schema_message``: the load error since #878 (the first invalid value of the step); ``before``/``errors``:
    the model's validation errors before; ``known_bug``: before #878 the model misses the value (or crashes on it), an
    expected failure of that bug, which #878 makes unreachable.
    """

    path: str
    schema_message: str
    before: tuple[str, ...] = ()
    errors: int = 1
    known_bug: str | None = None


def offline_names(text: str) -> str:
    """``{{ p }}``, ``{{ P }}`` and ``{{ hook_base }}`` replaced by their offline values (e2e-spduo000, E2E_SPDUO000,
    https://otterdog-e2e.invalid/spduo000/)."""
    for variable, value in (
        ("{{ hook_base }}", OFFLINE_RUN.hook_base),
        ("{{ p }}", OFFLINE_RUN.prefix),
        ("{{ P }}", OFFLINE_RUN.const_prefix.rstrip("_")),
    ):
        text = text.replace(variable, value)
    return text


WORKFLOW_VALUES = "('all' | 'local_only' | 'selected') are allowed."
# scenario -> step -> outcome (the YAML step only expects validate ok: false, or records when an older SUT validates)
ENUM_SCHEMA_STEPS: dict[str, dict[str, EnumSchemaStep]] = {
    "O-VAL-CUSTOM-PROPERTIES": {
        "value-type": EnumSchemaStep(
            'settings.custom_properties[name="{{ p }}-num"].value_type',
            "'number' is not one of ['string', 'single_select', 'multi_select', 'true_false']",
            (
                (
                    "custom_property[name=\"{{ p }}-num\"] has 'value_type' set to 'number', while only values ('string' | "
                    "'single_select' | 'multi_select' | 'true_false') are allowed."
                ),
            ),
        ),
    },
    "O-VAL-ENVIRONMENTS": {
        "template-comment-policy": EnumSchemaStep(
            'repositories[name="{{ p }}-env"].environments[name="{{ p }}-policy"].deployment_branch_policy',
            "'protected_branches' is not one of ['all', 'protected', 'selected']",
            (
                (
                    "Error: environment[name=\"{{ p }}-policy\", repository={{ p }}-env] has 'deployment_branch_policy' of "
                    "value 'protected_branches', while only values ('all' | 'protected' | 'selected') are allowed."
                ),
            ),
        ),
    },
    "O-VAL-ORG-ROLES": {
        "unknown-base-role": EnumSchemaStep(
            'roles[name="{{ p }}-r1"].base_role',
            "'super' is not one of ['none', 'read', 'triage', 'write', 'maintain', 'admin']",
            (
                (
                    "org_role[name=\"{{ p }}-r1\"] has 'base_role' of value 'super', while only values ('none' | 'read' | "
                    "'triage' | 'write' | 'maintain' | 'admin') are allowed."
                ),
            ),
        ),
    },
    "O-VAL-ORG-SETTINGS": {
        "default-repository-permission": EnumSchemaStep(
            "settings.default_repository_permission",
            "'maintain' is not one of ['none', 'read', 'write', 'admin']",
            (
                (
                    "'default_repository_permission' has value 'maintain', while only values ('none' | 'read' | 'write' | "
                    "'admin') are allowed."
                ),
            ),
        ),
    },
    "O-VAL-MERGE-SETTINGS": {
        "squash-title-value": EnumSchemaStep(
            'repositories[name="{{ p }}-merge"].squash_merge_commit_title',
            "'X' is not one of ['PR_TITLE', 'COMMIT_OR_PR_TITLE']",
            (
                (
                    "Error: repository[name=\"{{ p }}-merge\"] has 'squash_merge_commit_title' of value 'X', while only "
                    "values ('PR_TITLE' | 'COMMIT_OR_PR_TITLE') are allowed."
                ),
                "of value ('X', 'COMMIT_MESSAGES'), while only combinations",
            ),
            errors=2,
        ),
        "squash-message-value": EnumSchemaStep(
            'repositories[name="{{ p }}-merge"].squash_merge_commit_message',
            "'X' is not one of ['PR_BODY', 'COMMIT_MESSAGES', 'BLANK']",
            (
                (
                    "Error: repository[name=\"{{ p }}-merge\"] has 'squash_merge_commit_message' of value 'X', while only "
                    "values ('PR_BODY' | 'COMMIT_MESSAGES' | 'BLANK') are allowed."
                ),
                "of value ('COMMIT_OR_PR_TITLE', 'X'), while only combinations",
            ),
            errors=2,
        ),
        "merge-title-value": EnumSchemaStep(
            'repositories[name="{{ p }}-merge"].merge_commit_title',
            "'X' is not one of ['PR_TITLE', 'MERGE_MESSAGE']",
            (
                (
                    "Error: repository[name=\"{{ p }}-merge\"] has 'merge_commit_title' of value 'X', while only values "
                    "('PR_TITLE' | 'MERGE_MESSAGE') are allowed."
                ),
                "of value ('X', 'PR_TITLE'), while only combinations",
            ),
            errors=2,
        ),
        "merge-message-value": EnumSchemaStep(
            'repositories[name="{{ p }}-merge"].merge_commit_message',
            "'X' is not one of ['PR_TITLE', 'PR_BODY', 'BLANK']",
            (
                (
                    "Error: repository[name=\"{{ p }}-merge\"] has 'merge_commit_message' of value 'X', while only values "
                    "('PR_TITLE' | 'PR_BODY' | 'BLANK') are allowed."
                ),
                "of value ('PR_TITLE', 'X'), while only combinations",
            ),
            errors=2,
        ),
    },
    "O-VAL-PAGES-ENTERPRISE": {
        "unknown-visibility": EnumSchemaStep(
            'repositories[name="{{ p }}-pages"].gh_pages_visibility',
            "'hidden' is not one of ['public', 'private']",
            (
                (
                    "Error: repository[name=\"{{ p }}-pages\"] has 'gh_pages_visibility' set to value 'hidden', while only "
                    "values ['public' | 'private'] are allowed."
                ),
            ),
        ),
    },
    "O-VAL-COERCED": {
        "pages-visibility-below-enterprise": EnumSchemaStep(
            'repositories[name="{{ p }}-pages"].gh_pages_visibility',
            "'hidden' is not one of ['public', 'private']",
            (
                (
                    "Error: repository[name=\"{{ p }}-pages\"] has 'gh_pages_visibility' set to value 'hidden', while only "
                    "values ['public' | 'private'] are allowed."
                ),
            ),
            known_bug="KB-033",
        ),
    },
    "O-VAL-PAGES": {
        "unknown-build-type": EnumSchemaStep(
            'repositories[name="{{ p }}-pages"].gh_pages_build_type',
            "'foo' is not one of ['disabled', 'legacy', 'workflow']",
            (
                (
                    "Error: repository[name=\"{{ p }}-pages\"] has 'gh_pages_build_type' set to value 'foo', while only "
                    "values ['disabled' | 'legacy' | 'workflow'] are allowed."
                ),
            ),
        ),
    },
    "O-VAL-REPO": {
        "code-scanning-query-suite": EnumSchemaStep(
            'repositories[name="{{ p }}-cs"].code_scanning_default_query_suite',
            "'full' is not one of ['default', 'extended']",
            (
                (
                    "Error: repository[name=\"{{ p }}-cs\"] has 'code_scanning_default_query_suite' set to value 'full', "
                    "while only values ['default' | 'extended'] are allowed."
                ),
            ),
        ),
        # the enum gained 'javascript' and 'typescript' with #888 (main after v1.7.1): the list is left out
        "code-scanning-language": EnumSchemaStep(
            'repositories[name="{{ p }}-lang"].code_scanning_default_languages[0]',
            "'cobol' is not one of ['actions', 'c-cpp', ",
            (
                (
                    "Error: repository[name=\"{{ p }}-lang\"] has defined an invalid code scanning language 'cobol', only "
                    "values ("
                ),
            ),
        ),
    },
    "O-VAL-ORG-RULESETS": {
        "target-and-enforcement": EnumSchemaStep(
            'rulesets[name="{{ p }}-ors"].target',
            "'tags' is not one of ['branch', 'tag', 'push']",
            (
                (
                    "org_ruleset[name=\"{{ p }}-ors\"] has 'target' of value 'tags', while only values ('branch' | 'tag' | "
                    "'push') are allowed."
                ),
                (
                    "org_ruleset[name=\"{{ p }}-ors\"] has 'enforcement' of value 'on', while only values ('active' | "
                    "'disabled' | 'evaluate') are allowed."
                ),
            ),
            errors=2,
        ),
    },
    "O-VAL-RULESET-NESTED": {
        "merge-queue-values": EnumSchemaStep(
            'repositories[name="{{ p }}-nested"].rulesets[name="{{ p }}-queue"].required_merge_queue.merge_method',
            "'FAST' is not one of ['MERGE', 'SQUASH', 'REBASE']",
            (
                (
                    "has 'required_merge_queue.merge_method' of value 'FAST', only values ('MERGE' | 'SQUASH' | 'REBASE') "
                    "are allowed."
                ),
                (
                    "has 'required_merge_queue.build_concurrency' of value '-1' while only non-negative integers are "
                    "allowed."
                ),
                (
                    "has 'required_merge_queue.status_check_timeout' of value '-5' while only non-negative integers are "
                    "allowed."
                ),
            ),
            errors=3,
        ),
    },
    "O-VAL-RULESETS": {
        "target-and-enforcement": EnumSchemaStep(
            'repositories[name="{{ p }}-rs"].rulesets[name="{{ p }}-target"].target',
            "'tags' is not one of ['branch', 'tag', 'push']",
            (
                (
                    "Error: repo_ruleset[name=\"{{ p }}-target\", repository={{ p }}-rs] has 'target' of value 'tags', "
                    "while only values ('branch' | 'tag' | 'push') are allowed."
                ),
                (
                    "Error: repo_ruleset[name=\"{{ p }}-enforcement\", repository={{ p }}-rs] has 'enforcement' of value "
                    "'on', while only values ('active' | 'disabled' | 'evaluate') are allowed."
                ),
            ),
            errors=2,
        ),
    },
    "O-VAL-ORG-SECRETS": {
        "unknown-visibility": EnumSchemaStep(
            'secrets[name="{{ P }}_VIS"].visibility',
            "'everyone' is not one of ['public', 'private', 'selected']",
            (
                (
                    "Error: org_secret[name=\"{{ P }}_VIS\"] has 'visibility' of value 'everyone', while only values "
                    "('public' | 'private' | 'selected') are allowed."
                ),
            ),
        ),
    },
    "O-VAL-ORGVAR": {
        "invalid-visibility": EnumSchemaStep(
            'variables[name="{{ P }}_VIS"].visibility',
            "'nonsense' is not one of ['public', 'private', 'selected']",
            (
                (
                    "org_variable[name=\"{{ P }}_VIS\"] has 'visibility' of value 'nonsense', while only values ('public' | "
                    "'private' | 'selected') are allowed."
                ),
            ),
            known_bug="KB-028",
        ),
    },
    "O-VAL-WEBHOOKS": {
        "invalid-webhooks": EnumSchemaStep(
            "webhooks[0].content_type",
            "'xml' is not one of ['json', 'form']",
            (
                (
                    "Error: org_webhook[url=\"{{ hook_base }}org-invalid\"] has 'content_type' of value "
                    "'xml', while only values ('json' | 'form') are allowed."
                ),
                (
                    "Error: org_webhook[url=\"{{ hook_base }}org-invalid\"] has 'insecure_ssl' of value "
                    "'2', while only values ('0' | '1') are allowed."
                ),
                "has 'content_type' of value 'xml', while only values ('json' | 'form') are allowed.",
            ),
            errors=3,
        ),
    },
    "O-VAL-ORG-WORKFLOWS": {
        "allowed-actions": EnumSchemaStep(
            "settings.workflows.allowed_actions",
            "'some' is not one of ['all', 'local_only', 'selected']",
            (f"settings has 'workflows.allowed_actions' of value 'some', while only values {WORKFLOW_VALUES}",),
        ),
        "allowed-actions-with-repository": EnumSchemaStep(
            "settings.workflows.allowed_actions",
            "'some' is not one of ['all', 'local_only', 'selected']",
            (f"settings has 'workflows.allowed_actions' of value 'some', while only values {WORKFLOW_VALUES}",),
            known_bug="KB-029",
        ),
        "workflow-permissions": EnumSchemaStep(
            "settings.workflows.default_workflow_permissions",
            "'admin' is not one of ['read', 'write']",
            (
                (
                    "settings has 'workflows.default_workflow_permissions' of value 'admin', while only values ('read' | "
                    "'write') are allowed."
                ),
            ),
        ),
        "fork-pr-approval-policy": EnumSchemaStep(
            "settings.workflows.fork_pr_approval_policy",
            "'nobody' is not one of ['first_time_contributors_new_to_github', 'first_time_contributors', "
            "'all_external_contributors']",
            (  # a Python set before #878 (KB-038): the values come in any order
                "settings has 'workflows.fork_pr_approval_policy' of value 'nobody', while only values {",
                "'first_time_contributors'",
                "'first_time_contributors_new_to_github'",
                "'all_external_contributors'",
                "} are allowed.",
            ),
        ),
        "enabled-repositories": EnumSchemaStep(
            "settings.workflows.enabled_repositories",
            "'some' is not one of ['all', 'none', 'selected']",
            (
                (
                    "settings has 'enabled_repositories' of value 'some', while only values ('all' | 'none' | 'selected') "
                    "are allowed."
                ),
            ),
        ),
    },
    "O-VAL-REPO-WORKFLOWS": {
        "workflow-enums": EnumSchemaStep(
            'repositories[name="{{ p }}-wf"].workflows.default_workflow_permissions',
            "'admin' is not one of ['read', 'write']",
            (
                (
                    "Error: repository[name=\"{{ p }}-wf\"] has 'workflows.default_workflow_permissions' of value 'admin', "
                    "while only values ('read' | 'write') are allowed."
                ),
                (
                    "Error: repository[name=\"{{ p }}-wf\"] has 'workflows.fork_pr_approval_policy' of value 'nobody', "
                    "while only values {"
                ),
            ),
            errors=2,
        ),
        "unknown-allowed-actions": EnumSchemaStep(
            'repositories[name="{{ p }}-wf"].workflows.allowed_actions',
            "'some' is not one of ['all', 'local_only', 'selected']",
            (
                (
                    "Error: repository[name=\"{{ p }}-wf\"] has 'workflows.allowed_actions' of value 'some', while only "
                    f"values {WORKFLOW_VALUES}"
                ),
            ),
            known_bug="KB-029",
        ),
    },
}


class History(Protocol):
    """conftest.SutHistory: whether the SUT under test contains an upstream commit."""

    label: str

    def contains(self, commit: str) -> bool | None:
        """True/False from the upstream mirror, None when undecidable."""


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """One ``test_offline_scenario`` item per step of scenarios/offline/**/*.yaml (marks from collect.scenario_marks)."""
    scenarios_dir = get_context(metafunc.config).settings.scenarios_dir
    generate_scenario_tests(metafunc, [scenarios_dir / "offline"], tier="offline", per_step=True)


@pytest.mark.timeout(1800)  # the first offline item installs (or builds the image of) the SUT
def test_sut_template_can_be_vendored(template_src: Path) -> None:
    """The SUT ships the example template every offline scenario vendors (and is installed before the scenarios)."""
    assert (template_src / PUBLISHED_TEMPLATE_FILE).stat().st_size > 0
    assert sorted(path.name for path in template_src.glob("*.libsonnet")), f"no *.libsonnet in {template_src}"


def test_offline_scenario(scenario: Scenario, offline_engine: OfflineEngine, sut_history: History) -> None:
    """Run one offline case (a scenario narrowed to one step); then the SUT-dependent expectation of that step
    (SUT_EXPECTATIONS)."""
    outcome = offline_engine.run(scenario)
    if outcome.skipped:
        pytest.skip(outcome.skipped)
    outcome.raise_for_failures()
    for step in outcome.steps:
        check = SUT_EXPECTATIONS.get((scenario.id, step.name))
        if check is not None:
            check(step, sut_history)


def test_sut_expectations_name_existing_steps(pytestconfig: pytest.Config) -> None:
    """Every SUT_EXPECTATIONS key names a step of an offline scenario (a renamed step would silently lose its check)."""
    scenarios_dir = get_context(pytestconfig).settings.scenarios_dir
    scenarios = collect_scenarios([scenarios_dir / "offline"], tier="offline")
    steps = {(scenario.id, step.name) for scenario in scenarios for step in scenario.steps}
    assert set(SUT_EXPECTATIONS) <= steps, sorted(set(SUT_EXPECTATIONS) - steps)


# --- SUT-dependent expectations -------------------------------------------------------------------------------------
def result_of(step: StepOutcome, command: str) -> CliResult:
    """The CliResult of ``command`` in a step (AssertionError when it did not run)."""
    result = step.results.get(command)
    if result is None:
        raise AssertionError(f"step {step.name!r} did not run {command} (ran: {sorted(step.results)})")
    return result


def tail(result: CliResult, lines: int = 25) -> str:
    """Last lines of the normalized output (assertion messages)."""
    return "\n".join(normalize_text(result.output).splitlines()[-lines:])


def has_commit(history: History, commit: str, what: str) -> bool | None:
    """history.contains(commit); a warning when the mirror cannot decide (the check then accepts both behaviours)."""
    found = history.contains(commit)
    if found is None:
        warnings.warn(f"cannot tell whether {history.label} contains {what} ({commit[:7]})", stacklevel=2)
    return found


def expect_ruleset_strict(step: StepOutcome, history: History) -> None:
    """O-VAL-RULESET-STRICT step no-strict: SUTs containing #790 refuse the ruleset at validation (and local-plan
    aborts); older SUTs validate it and plan the repository and its ruleset."""
    validate, local_plan = result_of(step, "validate"), result_of(step, "local-plan")
    validation, plan = validate.validation(), local_plan.plan()
    has_fix = has_commit(history, FIX_790, "#790")
    if has_fix is None:  # either behaviour, but a refusal must be the #790 error
        if not validation.ok:
            assert MISSING_STRICT in normalize_text(validate.output), tail(validate)
        return
    if has_fix:
        assert not validation.ok and validation.errors == 1, (
            f"{history.label} contains #790 ({FIX_790[:7]}): validate must report the missing 'strict' as 1 error, "
            f"got ok={validation.ok} errors={validation.errors}\n{tail(validate)}"
        )
        assert MISSING_STRICT in normalize_text(validate.output), tail(validate)
        assert validate.exit_code != 0, f"validate exited 0 despite the validation error\n{tail(validate)}"
        assert PLANNING_ABORTED in normalize_text(local_plan.output), tail(local_plan)
        assert plan.add is None, f"local-plan printed a Plan: line despite the validation error\n{tail(local_plan)}"
        return
    assert validation.ok, (
        f"{history.label} does not contain #790 ({FIX_790[:7]}): the ruleset passes validation there, got "
        f"errors={validation.errors}\n{tail(validate)}"
    )
    assert MISSING_STRICT not in normalize_text(validate.output), tail(validate)
    assert (plan.add, plan.change, plan.delete) == (2, 0, 0), (
        f"local-plan must add the repository and its ruleset\n{tail(local_plan)}"
    )


def expect_org_ruleset_strict(step: StepOutcome, history: History) -> None:
    """O-VAL-ORG-RULESET-STRICT step org-no-strict: without #790 the org ruleset validates; with it the missing
    'strict' must be a validation error, and the AttributeError crash of current SUTs is an expected failure (known
    upstream defect)."""
    validate = result_of(step, "validate")
    validation, text = validate.validation(), normalize_text(validate.output)
    has_fix = has_commit(history, FIX_790, "#790")
    if has_fix is False:
        assert validation.ok, f"{history.label} predates #790: the org ruleset validates there\n{tail(validate)}"
        return
    if ORG_RULESET_CRASH in text:
        pytest.xfail(
            "known otterdog defect since #790: validating an org ruleset without required_status_checks.strict "
            f"crashes ({ORG_RULESET_CRASH}, exit {validate.exit_code}) instead of reporting the missing parameter"
        )
    if has_fix:
        assert not validation.ok and MISSING_STRICT in text, (
            f"{history.label} contains #790: the missing 'strict' of the org ruleset must be a validation error\n"
            f"{tail(validate)}"
        )


def expect_schema_error(message: str, schema_path: str, step: StepOutcome, history: History) -> None:
    """A step of SCHEMA_ERROR_STEPS: since #777 the schema error is a load error naming the invalid value (exit 1);
    before, the exception escapes with its schema path (exit 2, no validation summary). When the mirror cannot tell,
    the step must show one of the two behaviours consistently."""
    has_fix = has_commit(history, FIX_777, "#777")
    validate, name = result_of(step, "validate"), step.name
    text = normalize_text(validate.output)
    assert message in text, f"step {name!r}: {message!r} missing\n{tail(validate)}"
    load_error = has_fix if has_fix is not None else validate.exit_code == 1
    if load_error:
        assert validate.exit_code == 1, f"step {name!r}: since #777 exit 1, got {validate.exit_code}"
        assert "Validation failed" in text and SCHEMA_LOAD_ERROR in text, f"step {name!r}\n{tail(validate)}"
    else:
        assert validate.exit_code == 2, f"step {name!r}: before #777 exit 2, got {validate.exit_code}"
        assert f"Error: {message}" in text and schema_path in text, f"step {name!r}\n{tail(validate)}"
        assert "Validation failed" not in text, f"step {name!r}: no validation summary\n{tail(validate)}"


# eclipse-csi/otterdog#890 "feat: manage Dependabot and Codespaces secrets" (squash commit on main, after v1.7.1):
# Secret.validate requires uppercase names for every kind of secret
FIX_890 = "664e2907400532c920cd1d09f0a2b6df89765128"
LOWERCASE_SECRET = (
    "Error: repo_secret[name=\"{{ P | lower }}_lower\"] has 'name' of value '{{ P | lower }}_lower' which is not "
    "uppercase, while only uppercase names are allowed for secrets."
)


def expect_secret_name_case(step: StepOutcome, history: History) -> None:
    """O-VAL-SECRETS step lowercase-name: a lowercase repository secret name validates before #890 (GitHub
    upper-cases it) and is one validation error since (exit 1)."""
    validate = result_of(step, "validate")
    text, validation = normalize_text(validate.output), validate.validation()
    message = LOWERCASE_SECRET.replace("{{ P | lower }}", OFFLINE_RUN.const_prefix.rstrip("_").lower())
    has_fix = has_commit(history, FIX_890, "#890")
    rejected = has_fix if has_fix is not None else not validation.ok
    if rejected:
        assert validation.errors == 1 and validate.exit_code == 1, f"since #890 one error, exit 1\n{tail(validate)}"
        assert message in text, f"{message!r} missing\n{tail(validate)}"
        return
    assert validation.ok and validate.exit_code == 0, f"before #890 the name validates\n{tail(validate)}"
    assert "Error:" not in text and "Warning:" not in text, tail(validate)


def expect_enum_schema_error(spec: EnumSchemaStep, step: StepOutcome, history: History) -> None:
    """A step of ENUM_SCHEMA_STEPS: since #878 the invalid value is a load error naming its path (exit 1); before, the
    model reports its validation errors, or misses the value (spec.known_bug: an expected failure). When the mirror
    cannot tell, the output decides which of the two behaviours must hold."""
    validate, name = result_of(step, "validate"), step.name
    text, validation = normalize_text(validate.output), validate.validation()
    has_fix = has_commit(history, FIX_878, "#878")
    load_error = has_fix if has_fix is not None else SCHEMA_LOAD_ERROR in text
    if load_error:
        expected = f"{SCHEMA_LOAD_ERROR}{offline_names(spec.path)}': {offline_names(spec.schema_message)}"
        assert validate.exit_code == 1, f"step {name!r}: since #878 exit 1, got {validate.exit_code}\n{tail(validate)}"
        assert "Validation failed" in text and expected in text, (
            f"step {name!r}: {expected!r} missing\n{tail(validate)}"
        )
        return
    before = [offline_names(message) for message in spec.before]
    missing = [message for message in before if message not in text]
    if spec.known_bug is not None and (missing or validation.errors != spec.errors):
        pytest.xfail(
            f"{spec.known_bug} (before #878, step {name!r}): the model misses the invalid value, got exit "
            f"{validate.exit_code} and errors={validation.errors}"
        )
    assert not missing, f"step {name!r}: before #878 the model reports {missing!r}\n{tail(validate)}"
    assert validation.errors == spec.errors, (
        f"step {name!r}: before #878 {spec.errors} validation error(s), got {validation.errors}\n{tail(validate)}"
    )


# (scenario id, step) -> the check of that step's outcome
SUT_EXPECTATIONS: dict[tuple[str, str], Callable[[StepOutcome, History], None]] = {
    ("O-VAL-RULESET-STRICT", "no-strict"): expect_ruleset_strict,
    ("O-VAL-ORG-RULESET-STRICT", "org-no-strict"): expect_org_ruleset_strict,
    ("O-VAL-SECRETS", "lowercase-name"): expect_secret_name_case,
    **{
        (scenario, step): functools.partial(expect_schema_error, message, schema_path)
        for scenario, steps in SCHEMA_ERROR_STEPS.items()
        for step, (message, schema_path) in steps.items()
    },
    **{
        (scenario, step): functools.partial(expect_enum_schema_error, spec)
        for scenario, steps in ENUM_SCHEMA_STEPS.items()
        for step, spec in steps.items()
    },
}
