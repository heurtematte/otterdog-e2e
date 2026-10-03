"""WP0 contract tests: every module of SPEC section 3 imports, exposes the SPEC names and signatures, follows the
conventions of SPEC 4, and the small modules implemented in WP0 (naming, redact, waiting, procs, signing and the value
objects) behave as specified."""

from __future__ import annotations

import ast
import base64
import dataclasses
import hashlib
import hmac
import importlib
import inspect
import json
import logging
import re
import stat
import sys
import urllib.parse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import naming, procs, redact, waiting
from otterdog_e2e.redact import Redactor
from otterdog_e2e.webhooks import signing

SRC = Path(__file__).resolve().parents[2] / "src" / "otterdog_e2e"

# ------------------------------------------------------------------------------------------------------------------
# public names per module (SPEC sections 5-16)
# ------------------------------------------------------------------------------------------------------------------
PUBLIC_NAMES: dict[str, list[str]] = {
    "otterdog_e2e": ["__version__", "resource", "read_resource", "RESOURCE_NAMES"],
    "otterdog_e2e.settings": [
        "HarnessSettings",
        "harness_settings",
        "find_project_root",
        "load_env_files",
        "expand_env",
        "IdentitySpec",
        "Identity",
        "AppSpec",
        "AppCredentials",
        "WebappSpec",
        "Target",
        "TargetError",
        "load_target",
        "resolve_identities",
        "resolve_app_credentials",
    ],
    "otterdog_e2e.safety": [
        "SafetyError",
        "FORBIDDEN_ORG_PATTERNS",
        "VerifiedOrg",
        "check_org_allowed",
        "verify_target",
        "ALLOWED_SCOPES",
        "check_identity_isolation",
    ],
    "otterdog_e2e.naming": [
        "RUN_ID_RE",
        "HOOK_HOST",
        "HOOK_BASE",
        "E2E_NAME_RE",
        "RunContext",
        "new_run_context",
        "run_id_timestamp",
        "extract_run_id",
        "is_e2e_name",
        "is_deletable_ref",
        "BLUEPRINT_BRANCH_PREFIX",
        "branch_run_id",
    ],
    "otterdog_e2e.capabilities": ["Cap", "PLAN_MATRIX", "PLANS", "Capabilities", "from_plan", "probe_capabilities"],
    "otterdog_e2e.redact": ["Redactor", "REDACTOR", "install_logging_filter", "SECRET_KEY_RE", "RedactingFilter"],
    "otterdog_e2e.waiting": ["WaitTimeoutError", "Deadline", "intervals", "poll", "wait_until", "retry"],
    "otterdog_e2e.procs": ["sanitized_env", "run", "unshare_available", "set_default_home", "default_home"],
    "otterdog_e2e.github": [],
    "otterdog_e2e.github.http": ["GITHUB_API", "GitHubError", "GitHubHttp"],
    "otterdog_e2e.github.app": ["AppAuth"],
    "otterdog_e2e.github.oracle": ["VOLATILE_KEYS", "normalize", "Oracle"],
    "otterdog_e2e.github.mutate": ["Mutator"],
    "otterdog_e2e.github.janitor": ["JanitorItem", "Janitor"],
    "otterdog_e2e.github.lease": ["LeaseBusy", "OrgLease"],
    "otterdog_e2e.sut": [],
    "otterdog_e2e.sut.spec": ["SutSpec", "parse_sut_spec", "ResolvedSut", "resolve_sut"],
    "otterdog_e2e.sut.source": ["UpstreamMirror", "DIRTY_ALLOW", "DIRTY_DENY", "export_local_checkout"],
    "otterdog_e2e.sut.version": ["compute_version", "image_version", "public_version", "validate_version"],
    "otterdog_e2e.sut.cli_install": [
        "POETRY_VERSION",
        "PDV_VERSION",
        "InstalledCli",
        "ensure_poetry_tool",
        "install_cli",
        "image_cli",
    ],
    "otterdog_e2e.sut.image": ["BuiltImage", "build_webapp_image", "prebuilt_image", "docker_available"],
    "otterdog_e2e.sut.template": [
        "TemplateRef",
        "upstream_template",
        "url_template",
        "offline_template",
        "TemplatePublisher",
        "vendor_template",
        "resolve_template",
    ],
    "otterdog_e2e.otterdog": [],
    "otterdog_e2e.otterdog.runtime": ["CliRuntime", "HostRuntime", "DockerRuntime", "runtime_for"],
    "otterdog_e2e.otterdog.runner": ["CliResult", "OtterdogCli", "DiffOptions", "WebOtterdogCli"],
    "otterdog_e2e.otterdog.output": [
        "strip_ansi",
        "unbox",
        "HEADER_RE",
        "LOGGER_LINE_RE",
        "Message",
        "ValidationResult",
        "PlanObject",
        "PlanResult",
        "ApplyResult",
        "parse_validation",
        "parse_plan",
        "parse_apply",
        "parse_messages",
        "NormalizeContext",
        "normalize_text",
        "UNKNOWN_PROPERTIES_RE",
    ],
    "otterdog_e2e.otterdog.workspace": [
        "CREDENTIAL_ENV",
        "credentials_env",
        "ConfigWorkspace",
        "WorkspaceLayout",
        "webapp_otterdog_json",
    ],
    "otterdog_e2e.otterdog.render": [
        "FRAGMENT_KEYS",
        "ConfigFragments",
        "BaselineSpec",
        "RenderError",
        "OrgConfigRenderer",
        "build_baseline",
    ],
    "otterdog_e2e.otterdog.baseline": ["BaselineManager"],
    "otterdog_e2e.webapp": [],
    "otterdog_e2e.webapp.stack": [
        "WebappSettings",
        "WebappStack",
        "ExternalWebapp",
        "DtrackMock",
        "generate_dummy_app_credentials",
    ],
    "otterdog_e2e.webapp.api": ["WebappApi"],
    "otterdog_e2e.webhooks": [],
    "otterdog_e2e.webhooks.signing": ["serialize_payload", "sign_sha1", "sign_sha256", "webhook_headers"],
    "otterdog_e2e.webhooks.injector": ["WebhookInjector"],
    "otterdog_e2e.webhooks.payloads": [
        "ping_payload",
        "pull_request_payload",
        "issue_comment_payload",
        "push_payload",
        "unknown_event_payload",
        "synthetic_repository",
        "synthetic_organization",
        "synthetic_user",
        "synthetic_pull_request",
        "pull_request_review_payload",
        "installation_payload",
        "workflow_job_payload",
        "workflow_run_payload",
    ],
    "otterdog_e2e.webhooks.relay": ["RelayedDelivery", "DeliveryRelay"],
    "otterdog_e2e.config_repo": [
        "MARKERS",
        "APPLIED_TEXTS",
        "ConfigPr",
        "ConfigRepoFlow",
        "normalize_comment",
        "run_branch",
        "checked_paths",
        "check_forwarded",
    ],
    # blueprints, policies and workflow events of the webapp tier
    "otterdog_e2e.blueprints": [
        "BLUEPRINT_TYPES",
        "POLICY_TYPES",
        "BLUEPRINT_STATUSES",
        "BlueprintError",
        "RequiredFile",
        "BlueprintDefinition",
        "PolicyDefinition",
        "BlueprintHelper",
        "large_runner_workflow",
        "sbom_store_workflow",
        "sbom_caller_workflow",
        "unpinned_workflow",
        "scorecard_workflow",
        "uses_larger_runner",
    ],
    # the Dependency-Track mock: a standalone script run in its own container (compose profile dtrack)
    "otterdog_e2e.resources.dtrack_mock": ["BOM_PATH", "MockState", "MockServer", "make_server", "decode_body", "main"],
    "otterdog_e2e.scenarios": [],
    "otterdog_e2e.scenarios.model": [
        "StepSpec",
        "Scenario",
        "ScenarioError",
        "load_scenario",
        "load_scenarios",
        "render_step",
    ],
    "otterdog_e2e.scenarios.checks": [
        "CHECK_KINDS",
        "CheckResult",
        "subset_mismatches",
        "evaluate_check",
        "evaluate_checks",
    ],
    "otterdog_e2e.scenarios.engine": [
        "StepOutcome",
        "ScenarioOutcome",
        "ScenarioEngine",
        "DifferentialRunner",
        "SutSide",
    ],
    "otterdog_e2e.scenarios.offline": ["OfflineEngine"],
    "otterdog_e2e.scenarios.collect": ["scenario_marks", "TIER_TIMEOUTS"],
    "otterdog_e2e.observe": ["Observation", "ObservationRecorder", "load_observations"],
    "otterdog_e2e.differential": [
        "ExpectedDelta",
        "PrManifest",
        "load_pr_manifest",
        "Delta",
        "DiffReport",
        "compare",
    ],
    "otterdog_e2e.selection": ["PATH_RULES", "ALWAYS_TAGS", "select_tags"],
    "otterdog_e2e.report": ["build_summary", "scrub_artifacts"],
    "otterdog_e2e.known_bugs": ["KnownBug", "load"],
    "otterdog_e2e.inject": ["InjectError", "JsonnetFile", "SourceText", "FileContext", "load_source", "render_source"],
    "otterdog_e2e.appmanifest": [
        "DEFAULT_PERMISSIONS",
        "DEFAULT_EVENTS",
        "build_manifest",
        "manifest_form_html",
        "exchange_code",
    ],
    "otterdog_e2e.context": ["E2EContext", "E2EOptions", "get_context", "E2E_CONTEXT_KEY"],
    "otterdog_e2e.pytest_plugin": [
        "pytest_addoption",
        "pytest_configure",
        "pytest_collection_modifyitems",
        "pytest_runtest_setup",
        "pytest_runtest_makereport",
        "pytest_sessionfinish",
        "MARKERS",
        "OPTIONS",
    ],
    "otterdog_e2e.cli": ["main"],
    # web-UI tier (docs/web-ui-testing.md)
    "otterdog_e2e.webui": [],
    "otterdog_e2e.webui.mapping": ["WebSetting", "WEB_SETTINGS", "WEB_KEYS", "REST_FIELDS", "source_problems"],
    "otterdog_e2e.webui.gate": ["LoginGate", "WebLoginBlockedError", "web_ui_problems", "classify_web_failure"],
    "otterdog_e2e.webui.oracle": ["TrustedWebReader", "parse_settings_block", "rest_web_values"],
    "otterdog_e2e.webui.roundtrip": ["WebSettingsRoundTrip", "plan_toggles", "combine_snapshot"],
    "otterdog_e2e.testing": [],
    "otterdog_e2e.testing.fakes": [
        "FakeOracle",
        "FakeCli",
        "RecordingMutator",
        "FakeAppAuth",
        "FakeGitHubHttp",
        "FakeWorkspace",
        "make_verified_org",
        "make_run_context",
        "fake_sha",
        "cli_result",
    ],
}

# class members (methods/properties) per SPEC
CLASS_MEMBERS: dict[str, list[str]] = {
    "otterdog_e2e.settings.HarnessSettings": ["scratch"],
    "otterdog_e2e.settings.Target": ["config_repo_for", "protected_repos"],
    "otterdog_e2e.naming.RunContext": [
        "prefix",
        "const_prefix",
        "name",
        "const",
        "prop",
        "hook_url",
        "branch",
        "repo_filter",
        "needles",
        "template_vars",
    ],
    "otterdog_e2e.capabilities.Capabilities": ["has", "missing", "to_json"],
    "otterdog_e2e.redact.Redactor": ["PATTERNS", "add", "__call__", "redact_bytes", "contains_secret", "redact_file"],
    "otterdog_e2e.github.http.GitHubHttp": [
        "request",
        "get",
        "paginate",
        "post",
        "put",
        "patch",
        "delete",
        "graphql",
        "oauth_scopes",
        "rate_snapshot",
        "rate_limit",
    ],
    "otterdog_e2e.github.app.AppAuth": [
        "jwt",
        "app_http",
        "get_app",
        "installations",
        "slug",
        "bot_login",
        "installation_for_org",
        "installation_token",
        "installation_http",
        "hook_config",
        "list_deliveries",
        "get_delivery",
        "rate_remaining",
        "rate_reset",
    ],
    "otterdog_e2e.github.oracle.Oracle": [
        "org",
        "plan_name",
        "org_actions_permissions",
        "org_workflow_permissions",
        "org_secrets",
        "org_secret",
        "org_secret_repositories",
        "org_variables",
        "org_variable",
        "org_variable_repositories",
        "org_hooks",
        "org_hook_by_url",
        "org_hook_deliveries",
        "org_rulesets",
        "org_ruleset",
        "custom_properties",
        "custom_property",
        "org_roles",
        "members",
        "membership",
        "teams",
        "team",
        "team_members",
        "team_repo_permission",
        "repos",
        "repo",
        "repo_topics",
        "repo_actions_permissions",
        "repo_workflow_permissions",
        "repo_secrets",
        "repo_secret",
        "repo_variables",
        "repo_variable",
        "repo_hooks",
        "repo_hook_by_url",
        "repo_hook_deliveries",
        "branch_protection_rules",
        "branch_protection_rule",
        "repo_rulesets",
        "repo_ruleset",
        "environments",
        "environment",
        "environment_branch_policies",
        "environment_secrets",
        "environment_secret",
        "environment_variables",
        "environment_variable",
        "pages",
        "repo_custom_property_values",
        "default_branch",
        "branch_sha",
        "file_content",
        "pull",
        "pulls",
        "combined_status",
        "latest_status",
        "issue_comments",
        "pr_comments",
        "lookup",
    ],
    "otterdog_e2e.github.mutate.Mutator": [
        "create_branch",
        "delete_ref",
        "put_file",
        "commit_files",
        "create_commit",
        "create_ref",
        "update_ref",
        "create_pull",
        "comment",
        "review",
        "merge_pull",
        "close_pull",
        "patch_repo",
        "create_repo",
        "delete_repo",
        "delete_team",
        "delete_org_hook",
        "delete_repo_hook",
        "delete_org_secret",
        "delete_org_variable",
        "delete_org_ruleset",
        "delete_custom_property",
        "ping_repo_hook",
        "ping_org_hook",
        "ensure_membership",
        "set_org_description",
        # pull request edits of the webapp flows (run-branch pull requests only)
        "reopen_pull",
        "edit_comment",
        "delete_comment",
        "dismiss_review",
        "mark_pull_ready",
        "convert_pull_to_draft",
        # probe and drift writes of the battery (e2e objects only)
        "set_repo_topics",
        "add_repo_collaborator",
        "remove_repo_collaborator",
        "delete_repo_invitation",
        "create_team",
        "patch_team",
        "add_team_member",
        "remove_team_member",
        "dispatch_workflow",
        "cancel_workflow_run",
        "rerun_workflow_run",
        "create_security_advisory",
        "create_advisory_fork",
        "close_security_advisory",
        "create_code_security_configuration",
        "set_code_security_default",
        "delete_code_security_configuration",
    ],
    "otterdog_e2e.github.janitor.Janitor": ["scan", "sweep"],
    "otterdog_e2e.github.lease.OrgLease": [
        "acquire",
        "renew",
        "release",
        "ledger",
        "start_heartbeat",
        "stop_heartbeat",
    ],
    "otterdog_e2e.sut.spec.SutSpec": ["trusted"],
    "otterdog_e2e.sut.spec.ResolvedSut": ["to_json"],
    "otterdog_e2e.sut.source.UpstreamMirror": [
        "path",
        "git",
        "ensure",
        "fetch_pr",
        "fetch_from_local",
        "rev_parse",
        "merge_base",
        "is_ancestor",
        "changed_files",
        "describe",
        "latest_release_tag",
        "export",
    ],
    "otterdog_e2e.sut.template.TemplateRef": ["import_path"],
    "otterdog_e2e.sut.template.TemplatePublisher": ["publish"],
    "otterdog_e2e.otterdog.runtime.CliRuntime": ["command", "env"],
    "otterdog_e2e.otterdog.runtime.HostRuntime": ["command", "env"],
    "otterdog_e2e.otterdog.runtime.DockerRuntime": ["command", "env"],
    "otterdog_e2e.otterdog.workspace.ConfigWorkspace": [
        "config_file",
        "org_dir",
        "org_config_file",
        "base_config_file",
        "write_otterdog_json",
        "write_org_config",
        "write_base_config",
        "read_org_config",
        "clean_template_cache",
        "export_to",
        "use_layout",
        "config_texts",
        "org_dir_for",
        "org_config_file_for",
    ],
    "otterdog_e2e.otterdog.runner.CliResult": ["output", "plan", "apply", "validation", "assert_ok"],
    "otterdog_e2e.otterdog.runner.OtterdogCli": [
        "run",
        "version",
        "validate",
        "plan",
        "apply",
        "local_plan",
        "import_config",
        "push_config",
        "fetch_config",
        "open_pr",
        "check_status",
        "show",
        "show_default",
        "canonical_diff",
        "list_projects",
        "list_members",
        "check_token_permissions",
        "invoke",
        "plan_with",
        "apply_with",
        "local_plan_with",
    ],
    "otterdog_e2e.otterdog.output.PlanResult": ["objects_for", "is_noop", "removals"],
    "otterdog_e2e.otterdog.render.ConfigFragments": ["merged", "from_mapping"],
    "otterdog_e2e.otterdog.render.OrgConfigRenderer": ["render"],
    "otterdog_e2e.otterdog.baseline.BaselineManager": ["text", "check_removals", "guarded_apply", "reset", "push"],
    "otterdog_e2e.webapp.stack.WebappStack": [
        "project_name",
        "base_url",
        "webhook_url",
        "up",
        "health",
        "init",
        "wait_ready",
        "deployed_version",
        "logs",
        "save_logs",
        "down",
        "__enter__",
        "__exit__",
        "stop_service",
        "start_service",
        "restart_webapp",
        "enable_dtrack_mock",
        "dtrack",
    ],
    "otterdog_e2e.webapp.stack.ExternalWebapp": ["api", "init", "wait_ready", "webhook_url"],
    "otterdog_e2e.webapp.api.WebappApi": [
        "health",
        "organizations",
        "organization",
        "tasks",
        "wait_task",
        "open_pull_requests",
        "merged_pull_requests",
        "pull_request",
        "quiesce",
        "init",
        "check",
        "project_name",
        "blueprint_remediations",
        "dismissed_blueprints",
        "blueprint_statuses",
        "policy_status",
    ],
    "otterdog_e2e.webhooks.injector.WebhookInjector": ["send", "build", "deliver", "replay", "last"],
    "otterdog_e2e.webhooks.relay.DeliveryRelay": [
        "poll_once",
        "start",
        "stop",
        "delivered",
        "wait_for",
        "wait_event",
        "replay",
        "__enter__",
        "__exit__",
    ],
    "otterdog_e2e.config_repo.ConfigRepoFlow": [
        "config_path",
        "main_sha",
        "main_config",
        "reset_main",
        "open_pr",
        "push_commit",
        "comment",
        "approve",
        "merge",
        "close",
        "wait_delivery",
        "wait_status",
        "bot_comments",
        "wait_comment",
        "wait_merged",
        "cleanup",
        "open_pr_files",
        "push_files",
        "edit_comment",
        "delete_comment",
        "request_changes",
        "dismiss_review",
        "mark_ready",
        "convert_to_draft",
        "reopen",
        "adopt_pr",
    ],
    "otterdog_e2e.blueprints.BlueprintHelper": [
        "add_blueprint",
        "add_policy",
        "add_definition_text",
        "remove",
        "sweep_stale",
        "reload",
        "check",
        "wait_evaluation",
        "statuses",
        "wait_status",
        "policy_status",
        "wait_policy_counter",
        "remediation_prs",
        "wait_remediation_pr",
        "close_remediation_pr",
        "reopen_remediation_pr",
        "merge_remediation_pr",
        "add_workflow",
        "add_large_runner_workflow",
        "add_sbom_workflows",
        "dispatch",
        "workflow_runs",
        "wait_run",
        "cancel_run",
        "wait_workflow_delivery",
        "cleanup",
    ],
    "otterdog_e2e.scenarios.engine.ScenarioOutcome": ["ok"],
    "otterdog_e2e.scenarios.engine.ScenarioEngine": ["run", "cleanup"],
    "otterdog_e2e.scenarios.engine.DifferentialRunner": ["observe_offline", "observe_live"],
    "otterdog_e2e.scenarios.offline.OfflineEngine": ["run"],
    "otterdog_e2e.observe.ObservationRecorder": ["scope", "record"],
    "otterdog_e2e.differential.DiffReport": ["unexpected", "expected", "to_markdown", "to_json"],
    "otterdog_e2e.context.E2EContext": ["close", "ensure_live"],
}

# parameter names of key callables (self included for methods)
SIGNATURES: dict[str, list[str]] = {
    "otterdog_e2e.procs.sanitized_env": ["extra", "home", "keep_home", "base"],
    "otterdog_e2e.procs.run": ["argv", "cwd", "extra_env", "timeout", "input", "keep_home", "home", "check"],
    "otterdog_e2e.procs.unshare_available": [],
    "otterdog_e2e.settings.harness_settings": ["environ"],
    "otterdog_e2e.settings.find_project_root": ["start"],
    "otterdog_e2e.settings.load_env_files": ["target", "project_root", "environ"],
    "otterdog_e2e.settings.expand_env": ["value", "environ"],
    "otterdog_e2e.settings.load_target": ["name_or_path", "settings", "environ"],
    "otterdog_e2e.settings.resolve_identities": ["target", "environ"],
    "otterdog_e2e.settings.resolve_app_credentials": ["target", "environ"],
    "otterdog_e2e.settings.HarnessSettings.scratch": ["self", "run_id"],
    "otterdog_e2e.settings.Target.config_repo_for": ["self", "run_ctx"],
    "otterdog_e2e.safety.check_org_allowed": ["login"],
    "otterdog_e2e.safety.verify_target": ["admin_http", "target", "identities", "require_marker", "check_identities"],
    "otterdog_e2e.safety.check_identity_isolation": ["http", "role", "allowed_org_ids", "test_org_id"],
    "otterdog_e2e.naming.new_run_context": ["run_id", "now"],
    "otterdog_e2e.naming.run_id_timestamp": ["run_id"],
    "otterdog_e2e.naming.extract_run_id": ["name"],
    "otterdog_e2e.capabilities.from_plan": ["plan", "extra", "remove"],
    "otterdog_e2e.capabilities.probe_capabilities": [
        "admin_http",
        "verified",
        "identities",
        "app_ok",
        "docker_ok",
        "overrides",
        "fixture_repo",
    ],
    "otterdog_e2e.redact.Redactor.__init__": ["self", "secrets"],
    "otterdog_e2e.redact.Redactor.add": ["self", "values", "variants"],
    "otterdog_e2e.redact.install_logging_filter": ["redactor"],
    "otterdog_e2e.github.http.GitHubHttp.__init__": [
        "self",
        "token",
        "base_url",
        "auth_scheme",
        "user_agent",
        "timeout",
        "session",
        "max_retries",
        "sleep",
        "write_scope",
        "read_only",
        "min_write_interval",
        "identity",
    ],
    "otterdog_e2e.github.http.GitHubHttp.request": [
        "self",
        "method",
        "path",
        "params",
        "json",
        "data",
        "headers",
        "expected",
        "allow",
    ],
    "otterdog_e2e.github.http.GitHubHttp.get": ["self", "path", "params", "headers", "allow_404"],
    "otterdog_e2e.github.http.GitHubHttp.paginate": [
        "self",
        "path",
        "params",
        "per_page",
        "item_key",
        "max_pages",
        "allow_unavailable",
    ],
    "otterdog_e2e.github.http.GitHubHttp.delete": ["self", "path", "allow_404", "kw"],
    "otterdog_e2e.github.http.GitHubHttp.graphql": ["self", "query", "variables", "allow_errors"],
    "otterdog_e2e.github.app.AppAuth.__init__": ["self", "creds", "base_url", "session", "clock"],
    "otterdog_e2e.github.app.AppAuth.installation_http": ["self", "installation_id", "verified"],
    "otterdog_e2e.github.app.AppAuth.list_deliveries": ["self", "per_page", "cursor"],
    "otterdog_e2e.github.oracle.Oracle.__init__": ["self", "http", "org"],
    "otterdog_e2e.github.oracle.Oracle.file_content": ["self", "repo", "path", "ref"],
    "otterdog_e2e.github.oracle.Oracle.lookup": ["self", "kind", "params"],
    "otterdog_e2e.github.mutate.Mutator.__init__": ["self", "http", "verified", "dry_run"],
    "otterdog_e2e.github.mutate.Mutator.put_file": ["self", "repo", "path", "content", "message", "branch", "sha"],
    "otterdog_e2e.github.mutate.Mutator.commit_files": ["self", "repo", "branch", "files", "message"],
    "otterdog_e2e.github.mutate.Mutator.create_commit": ["self", "repo", "tree_sha", "parents", "message"],
    "otterdog_e2e.github.mutate.Mutator.create_pull": ["self", "repo", "head", "base", "title", "body", "draft"],
    "otterdog_e2e.github.mutate.Mutator.merge_pull": ["self", "repo", "number", "method", "sha"],
    "otterdog_e2e.github.mutate.Mutator.create_repo": ["self", "name", "private", "description", "auto_init"],
    "otterdog_e2e.github.mutate.Mutator.delete_org_ruleset": ["self", "ruleset_id", "name"],
    # what ConfigRepoFlow and BlueprintHelper call (blueprints.py passes ref= and inputs= by keyword)
    "otterdog_e2e.github.mutate.Mutator.reopen_pull": ["self", "repo", "number"],
    "otterdog_e2e.github.mutate.Mutator.edit_comment": ["self", "repo", "comment_id", "body"],
    "otterdog_e2e.github.mutate.Mutator.delete_comment": ["self", "repo", "comment_id"],
    "otterdog_e2e.github.mutate.Mutator.dismiss_review": ["self", "repo", "number", "review_id", "message"],
    "otterdog_e2e.github.mutate.Mutator.mark_pull_ready": ["self", "repo", "number"],
    "otterdog_e2e.github.mutate.Mutator.convert_pull_to_draft": ["self", "repo", "number"],
    "otterdog_e2e.github.mutate.Mutator.dispatch_workflow": ["self", "repo", "workflow_file", "ref", "inputs"],
    "otterdog_e2e.github.mutate.Mutator.cancel_workflow_run": ["self", "repo", "run_id", "force_cancel"],
    "otterdog_e2e.github.janitor.Janitor.__init__": [
        "self",
        "oracle",
        "mutator",
        "lease",
        "configs_repo",
        "defaults_repo",
        "protected_repos",
        "purgeable",
    ],
    "otterdog_e2e.github.lease.OrgLease.__init__": ["self", "mutator", "oracle", "repo", "run_ctx", "holder", "ttl"],
    "otterdog_e2e.github.lease.OrgLease.acquire": [
        "self",
        "wait",
        "steal_expired",
        "takeover_run",
        "force_takeover",
        "trusted_holder",
    ],
    "otterdog_e2e.github.lease.OrgLease.start_heartbeat": ["self", "interval"],
    "otterdog_e2e.sut.spec.parse_sut_spec": ["raw"],
    "otterdog_e2e.sut.spec.resolve_sut": ["spec", "settings", "http"],
    "otterdog_e2e.sut.source.UpstreamMirror.__init__": ["self", "cache_dir", "repo"],
    "otterdog_e2e.sut.source.UpstreamMirror.git": ["self", "args", "timeout"],
    "otterdog_e2e.sut.source.UpstreamMirror.export": ["self", "sha", "dest"],
    "otterdog_e2e.sut.source.export_local_checkout": ["path", "dest", "dirty"],
    "otterdog_e2e.sut.version.compute_version": ["tag", "distance", "sha", "dirty_hash"],
    "otterdog_e2e.sut.version.validate_version": ["version", "minimum"],
    "otterdog_e2e.sut.cli_install.ensure_poetry_tool": ["settings"],
    "otterdog_e2e.sut.cli_install.install_cli": ["sut", "settings", "with_app", "force"],
    "otterdog_e2e.sut.cli_install.image_cli": ["sut", "image"],
    "otterdog_e2e.sut.image.build_webapp_image": ["sut", "force", "extra_args"],
    "otterdog_e2e.sut.image.prebuilt_image": ["ref"],
    "otterdog_e2e.sut.template.upstream_template": ["sut", "upstream_repo"],
    "otterdog_e2e.sut.template.url_template": ["url"],
    "otterdog_e2e.sut.template.TemplatePublisher.__init__": ["self", "http", "verified", "repo"],
    "otterdog_e2e.sut.template.vendor_template": ["template_src_dir", "org_dir", "ref", "hooks"],
    "otterdog_e2e.sut.template.resolve_template": ["mode", "sut", "upstream_repo", "publisher", "url"],
    "otterdog_e2e.otterdog.runtime.CliRuntime.command": ["self", "args", "workdir", "env_file"],
    "otterdog_e2e.otterdog.runtime.CliRuntime.env": ["self", "credentials"],
    "otterdog_e2e.otterdog.runtime.runtime_for": ["installed", "offline"],
    "otterdog_e2e.otterdog.workspace.credentials_env": ["identity"],
    "otterdog_e2e.otterdog.workspace.ConfigWorkspace.__init__": [
        "self",
        "root",
        "org",
        "template",
        "config_repo",
        "project",
        "base_url",
    ],
    "otterdog_e2e.otterdog.workspace.ConfigWorkspace.export_to": ["self", "artifacts_dir"],
    "otterdog_e2e.otterdog.workspace.webapp_otterdog_json": ["target", "template", "config_repo", "project"],
    "otterdog_e2e.otterdog.runner.CliResult.assert_ok": ["self", "what"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.__init__": [
        "self",
        "installed",
        "workspace",
        "verified",
        "identity",
        "scratch",
        "artifacts_dir",
        "settings",
        "recorder",
        "timeout",
        "offline",
        "http_cache",
        "http_cache_root",
    ],
    "otterdog_e2e.otterdog.runner.OtterdogCli.run": [
        "self",
        "command",
        "args",
        "org",
        "input",
        "timeout",
        "local",
        "observe",
    ],
    "otterdog_e2e.otterdog.runner.OtterdogCli.validate": ["self", "local", "verbose", "observe"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.plan": ["self", "repo_filter", "local", "observe"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.apply": [
        "self",
        "repo_filter",
        "delete",
        "update_secrets",
        "update_webhooks",
        "local",
        "observe",
    ],
    "otterdog_e2e.otterdog.runner.OtterdogCli.local_plan": ["self", "suffix", "local", "observe"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.plan_with": ["self", "options", "local", "observe"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.apply_with": ["self", "options", "delete", "local", "observe"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.local_plan_with": ["self", "options", "suffix", "local", "observe"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.invoke": [
        "self",
        "args",
        "input",
        "timeout",
        "config_root",
        "env",
        "observe",
    ],
    "otterdog_e2e.otterdog.runner.OtterdogCli.import_config": ["self", "force"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.push_config": ["self", "message"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.fetch_config": ["self", "ref", "pull_request"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.open_pr": ["self", "branch", "title", "author"],
    "otterdog_e2e.otterdog.runner.OtterdogCli.check_status": ["self", "json_file"],
    "otterdog_e2e.otterdog.output.normalize_text": ["text", "ctx"],
    "otterdog_e2e.otterdog.output.PlanResult.objects_for": ["self", "needles"],
    "otterdog_e2e.otterdog.output.PlanResult.is_noop": ["self", "needles"],
    "otterdog_e2e.otterdog.render.ConfigFragments.merged": ["self", "other"],
    "otterdog_e2e.otterdog.render.ConfigFragments.from_mapping": ["data"],
    "otterdog_e2e.otterdog.render.OrgConfigRenderer.__init__": [
        "self",
        "template",
        "org",
        "plan",
        "org_profile",
        "baseline",
        "marker",
        "hide_cache_limit",
        "project",
    ],
    "otterdog_e2e.otterdog.render.OrgConfigRenderer.render": ["self", "fragments", "include_baseline", "plan"],
    "otterdog_e2e.otterdog.render.build_baseline": ["target", "run_ctx"],
    "otterdog_e2e.otterdog.baseline.BaselineManager.__init__": [
        "self",
        "reset_cli",
        "renderer",
        "target",
        "run_ctx",
        "oracle",
        "purgeable",
        "protected_repos",
    ],
    "otterdog_e2e.otterdog.baseline.BaselineManager.guarded_apply": ["self", "cli", "repo_filter", "delete"],
    "otterdog_e2e.otterdog.baseline.BaselineManager.push": ["self", "flow"],
    "otterdog_e2e.webapp.stack.WebappStack.__init__": [
        "self",
        "settings",
        "verified",
        "image",
        "run_ctx",
        "scratch",
        "artifacts_dir",
    ],
    "otterdog_e2e.webapp.stack.WebappStack.up": ["self", "timeout"],
    "otterdog_e2e.webapp.stack.WebappStack.logs": ["self", "tail"],
    "otterdog_e2e.webapp.stack.ExternalWebapp.__init__": ["self", "base_url", "init_url", "allow_remote"],
    "otterdog_e2e.webapp.stack.ExternalWebapp.wait_ready": ["self", "org", "timeout"],
    "otterdog_e2e.webapp.api.WebappApi.__init__": ["self", "base_url", "timeout", "session"],
    "otterdog_e2e.webapp.api.WebappApi.tasks": ["self", "org_id", "type_", "repo_name", "status", "page_size"],
    "otterdog_e2e.webapp.api.WebappApi.wait_task": [
        "self",
        "type_",
        "org_id",
        "after",
        "repo_name",
        "pull_request",
        "statuses",
        "timeout",
        "interval",
    ],
    "otterdog_e2e.webapp.api.WebappApi.pull_request": ["self", "org_id", "repo_name", "number"],
    "otterdog_e2e.webapp.api.WebappApi.quiesce": ["self", "org_id", "quiet_for", "timeout"],
    "otterdog_e2e.webhooks.signing.serialize_payload": ["payload"],
    "otterdog_e2e.webhooks.signing.sign_sha1": ["secret", "body"],
    "otterdog_e2e.webhooks.signing.sign_sha256": ["secret", "body"],
    "otterdog_e2e.webhooks.signing.webhook_headers": [
        "event",
        "body",
        "secret",
        "delivery_id",
        "content_type",
        "signature",
        "hook_id",
        "target_type",
        "target_id",
    ],
    "otterdog_e2e.webhooks.injector.WebhookInjector.__init__": ["self", "endpoint_url", "secret", "session"],
    "otterdog_e2e.webhooks.injector.WebhookInjector.send": [
        "self",
        "event",
        "payload",
        "delivery_id",
        "content_type",
        "signature",
        "timeout",
    ],
    "otterdog_e2e.webhooks.relay.DeliveryRelay.__init__": [
        "self",
        "app",
        "forward_url",
        "secret",
        "since",
        "installation_id",
        "org",
        "accept",
        "poll_interval",
        "lag_window",
        "max_pages_per_poll",
        "min_rate_remaining",
        "include_redeliveries",
        "artifacts_dir",
        "keep_payloads",
        "allow_remote",
        "session",
        "clock",
        "sleep",
    ],
    "otterdog_e2e.webhooks.relay.DeliveryRelay.stop": ["self", "timeout"],
    "otterdog_e2e.webhooks.relay.DeliveryRelay.wait_for": ["self", "predicate", "timeout"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.__init__": [
        "self",
        "org",
        "repo",
        "oracle",
        "mutators",
        "run_ctx",
        "validation_context",
        "sync_context",
        "guard",
        "bot_login",
        "relay",
        "delivery_timeout",
        "default_branch",
    ],
    "otterdog_e2e.config_repo.ConfigRepoFlow.reset_main": ["self", "text", "message", "identity"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.open_pr": [
        "self",
        "slug",
        "config_texts",
        "title",
        "identity",
        "draft",
        "body",
    ],
    "otterdog_e2e.config_repo.ConfigRepoFlow.push_commit": ["self", "pr", "text", "message", "identity"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.comment": ["self", "pr", "body", "identity"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.approve": ["self", "pr", "identity"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.merge": ["self", "pr", "method", "identity"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.wait_delivery": ["self", "pr", "event", "action", "after"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.wait_status": ["self", "pr", "context", "final", "timeout"],
    "otterdog_e2e.config_repo.ConfigRepoFlow.wait_comment": [
        "self",
        "pr",
        "marker",
        "contains",
        "exclude_ids",
        "timeout",
    ],
    "otterdog_e2e.config_repo.normalize_comment": ["body"],
    "otterdog_e2e.scenarios.model.load_scenario": ["path"],
    "otterdog_e2e.scenarios.model.load_scenarios": ["directory", "tier"],
    "otterdog_e2e.scenarios.model.render_step": ["step", "variables"],
    "otterdog_e2e.scenarios.checks.subset_mismatches": ["expected", "actual", "path"],
    "otterdog_e2e.scenarios.checks.evaluate_check": ["oracle", "check"],
    "otterdog_e2e.scenarios.checks.evaluate_checks": ["oracle", "checks", "timeout", "interval"],
    "otterdog_e2e.scenarios.engine.ScenarioEngine.__init__": [
        "self",
        "cli",
        "renderer",
        "oracle",
        "run_ctx",
        "capabilities",
        "baseline",
        "variables",
        "sleep",
    ],
    "otterdog_e2e.scenarios.engine.ScenarioEngine.run": ["self", "scenario", "cleanup"],
    "otterdog_e2e.scenarios.engine.DifferentialRunner.__init__": [
        "self",
        "base",
        "head",
        "renderer_factory",
        "template_src_for",
    ],
    "otterdog_e2e.scenarios.offline.OfflineEngine.__init__": [
        "self",
        "cli",
        "workspace",
        "template_src",
        "run_ctx",
        "variables",
    ],
    "otterdog_e2e.scenarios.collect.scenario_marks": ["scenario"],
    "otterdog_e2e.observe.ObservationRecorder.__init__": ["self", "sut_label", "role", "out_file", "normalize_ctx"],
    "otterdog_e2e.observe.ObservationRecorder.scope": ["self", "scenario", "step"],
    "otterdog_e2e.observe.ObservationRecorder.record": ["self", "kind", "key", "content", "meta"],
    "otterdog_e2e.observe.load_observations": ["path"],
    "otterdog_e2e.differential.load_pr_manifest": ["path"],
    "otterdog_e2e.differential.compare": ["base", "head", "base_label", "head_label", "expected"],
    "otterdog_e2e.differential.DiffReport.to_markdown": ["self", "max_diff_lines"],
    "otterdog_e2e.selection.select_tags": ["changed_files"],
    "otterdog_e2e.report.build_summary": ["artifacts_dir", "redactor"],
    "otterdog_e2e.report.scrub_artifacts": ["root", "redactor"],
    "otterdog_e2e.known_bugs.load": ["path"],
    "otterdog_e2e.appmanifest.build_manifest": ["target", "webhook_url", "redirect_url"],
    "otterdog_e2e.appmanifest.manifest_form_html": ["org", "manifest", "state"],
    "otterdog_e2e.appmanifest.exchange_code": ["code", "out_dir"],
}

# SPEC dataclass fields (actual fields must start with these, in this order; additive fields may follow)
DATACLASS_FIELDS: dict[str, list[str]] = {
    "otterdog_e2e.settings.HarnessSettings": [
        "project_root",
        "cache_dir",
        "artifacts_root",
        "upstream_repo",
        "targets_dir",
        "scenarios_dir",
    ],
    "otterdog_e2e.settings.IdentitySpec": ["name", "login", "token_env"],
    "otterdog_e2e.settings.Identity": ["name", "login", "token"],
    "otterdog_e2e.settings.AppSpec": [
        "id_env",
        "private_key_env",
        "private_key_file_env",
        "webhook_secret_env",
        "slug",
    ],
    "otterdog_e2e.settings.AppCredentials": ["app_id", "private_key_pem", "webhook_secret", "slug"],
    "otterdog_e2e.settings.WebappSpec": [
        "transport",
        "external_url",
        "external_init_url",
        "validation_context",
        "sync_context",
        "workers",
        "port",
    ],
    "otterdog_e2e.settings.Target": [
        "name",
        "description",
        "org",
        "org_id",
        "allowed_org_ids",
        "expected_plan",
        "marker",
        "capability_overrides",
        "configs_repo",
        "org_config_repo",
        "defaults_repo",
        "template_mode",
        "template_url",
        "identities",
        "app",
        "admin_team",
        "approval_team",
        "contributors_team",
        "webapp",
        "fixture_repos",
        "extra_protected_repos",
        "baseline_settings",
        "source_path",
    ],
    "otterdog_e2e.safety.VerifiedOrg": ["login", "org_id", "plan", "target", "verified_at", "org_json"],
    "otterdog_e2e.naming.RunContext": ["run_id", "created_at"],
    "otterdog_e2e.capabilities.Capabilities": ["plan", "caps", "probes"],
    "otterdog_e2e.github.janitor.JanitorItem": ["kind", "name", "run_id", "scope", "detail"],
    "otterdog_e2e.sut.spec.SutSpec": ["raw", "kind", "value", "pin_sha"],
    "otterdog_e2e.sut.spec.ResolvedSut": [
        "spec",
        "label",
        "sha",
        "version",
        "image_version",
        "source_dir",
        "repo_url",
        "trusted",
        "is_dirty",
        "dirty_hash",
        "pr_number",
        "pr_base_ref",
        "base_sha",
        "changed_files",
        "dirty_files",
    ],
    "otterdog_e2e.sut.cli_install.InstalledCli": [
        "sut",
        "runtime",
        "venv_dir",
        "otterdog_bin",
        "image",
        "version_output",
    ],
    "otterdog_e2e.sut.image.BuiltImage": ["tag", "image_id", "version", "revision", "trusted"],
    "otterdog_e2e.sut.template.TemplateRef": ["url", "repo_name", "file", "ref", "tag"],
    "otterdog_e2e.otterdog.runner.CliResult": [
        "argv",
        "exit_code",
        "stdout",
        "stderr",
        "duration",
        "cwd",
        "timed_out",
        "infra_error",
    ],
    "otterdog_e2e.otterdog.output.Message": ["level", "text", "source"],
    "otterdog_e2e.otterdog.output.ValidationResult": [
        "ok",
        "infos",
        "warnings",
        "errors",
        "messages",
        "load_error",
        "raw",
    ],
    "otterdog_e2e.otterdog.output.PlanObject": [
        "op",
        "kind",
        "key",
        "value",
        "parent_kind",
        "parent",
        "header",
        "body",
    ],
    "otterdog_e2e.otterdog.output.PlanResult": [
        "add",
        "change",
        "delete",
        "objects",
        "aborted",
        "validation",
        "messages",
        "raw",
    ],
    "otterdog_e2e.otterdog.output.ApplyResult": [
        "added",
        "changed",
        "deleted",
        "ignored",
        "no_changes",
        "aborted_validation",
        "pending_deletions",
        "failed_patches",
        "messages",
        "raw",
    ],
    "otterdog_e2e.otterdog.output.NormalizeContext": ["literals"],
    "otterdog_e2e.otterdog.render.ConfigFragments": [
        "settings",
        "teams",
        "secrets",
        "variables",
        "webhooks",
        "rulesets",
        "roles",
        "custom_properties",
        "repositories",
        "extra",
    ],
    "otterdog_e2e.otterdog.render.BaselineSpec": ["settings", "teams", "repositories", "custom_properties"],
    "otterdog_e2e.webapp.stack.WebappSettings": [
        "org",
        "configs_repo",
        "config_token",
        "app",
        "validation_context",
        "sync_context",
        "admin_team",
        "approval_team",
        "workers",
        "port",
    ],
    "otterdog_e2e.webhooks.relay.RelayedDelivery": [
        "id",
        "guid",
        "event",
        "action",
        "installation_id",
        "repository_id",
        "pull_number",
        "delivered_at",
        "seen_at",
        "forwarded_at",
        "github_status_code",
        "relay_status",
        "error",
    ],
    "otterdog_e2e.config_repo.ConfigPr": ["number", "branch", "head_sha", "url", "author", "comment_ids_before"],
    "otterdog_e2e.scenarios.checks.CheckResult": ["ok", "check", "message", "actual"],
    "otterdog_e2e.scenarios.engine.StepOutcome": ["name", "results", "checks", "negative", "notes", "durations"],
    "otterdog_e2e.scenarios.engine.ScenarioOutcome": ["scenario", "steps", "failures", "skipped"],
    "otterdog_e2e.scenarios.engine.SutSide": ["role", "installed", "cli", "recorder", "template"],
    "otterdog_e2e.observe.Observation": ["sut", "role", "scenario", "step", "kind", "key", "content", "meta"],
    "otterdog_e2e.differential.ExpectedDelta": ["scenario", "step", "kind", "key", "note"],
    "otterdog_e2e.differential.PrManifest": [
        "pr",
        "title",
        "base",
        "template",
        "tags",
        "scenarios",
        "scenario_dirs",
        "expected_deltas",
        "markers",
        "notes",
    ],
    "otterdog_e2e.differential.Delta": [
        "scenario",
        "step",
        "kind",
        "key",
        "base",
        "head",
        "diff",
        "expected",
        "note",
    ],
    "otterdog_e2e.differential.DiffReport": ["base_label", "head_label", "deltas", "unchanged", "not_comparable"],
    "otterdog_e2e.known_bugs.KnownBug": ["id", "title", "status", "evidence", "upstream", "fixed_in", "scenarios"],
}


def _resolve(dotted: str) -> Any:
    """Import ``a.b.c.Name.attr`` (module part = longest importable prefix)."""
    parts = dotted.split(".")
    for cut in range(len(parts), 0, -1):
        try:
            obj: Any = importlib.import_module(".".join(parts[:cut]))
        except ModuleNotFoundError:
            continue
        for part in parts[cut:]:
            if not inspect.isclass(obj):
                obj = getattr(obj, part)
                continue
            static = inspect.getattr_static(obj, part)
            if isinstance(static, classmethod):
                obj = getattr(obj, part)  # bound: no cls parameter
            elif isinstance(static, staticmethod):
                obj = static.__func__
            else:
                obj = static
        return obj
    raise ImportError(dotted)


# ------------------------------------------------------------------------------------------------------------------
# structure
# ------------------------------------------------------------------------------------------------------------------
def _source_modules() -> list[str]:
    """Dotted names of every module file of the package."""
    names = []
    for path in sorted(SRC.rglob("*.py")):
        relative = path.relative_to(SRC.parent).with_suffix("")
        parts = list(relative.parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.append(".".join(parts))
    return names


def test_every_source_module_is_listed_and_spec_modules_exist() -> None:
    """The module list of SPEC section 3 and the files on disk agree."""
    assert sorted(_source_modules()) == sorted(PUBLIC_NAMES)


@pytest.mark.parametrize("module_name", sorted(PUBLIC_NAMES))
def test_module_imports_and_exposes_spec_names(module_name: str) -> None:
    """Each module imports, has a docstring and every SPEC public name."""
    module = importlib.import_module(module_name)
    assert (module.__doc__ or "").strip(), f"{module_name} has no module docstring"
    missing = [name for name in PUBLIC_NAMES[module_name] if not hasattr(module, name)]
    assert not missing, f"{module_name} misses {missing}"


@pytest.mark.parametrize("class_path", sorted(CLASS_MEMBERS))
def test_class_members(class_path: str) -> None:
    """Classes expose the SPEC methods and properties."""
    cls = _resolve(class_path)
    missing = [name for name in CLASS_MEMBERS[class_path] if not hasattr(cls, name)]
    assert not missing, f"{class_path} misses {missing}"


@pytest.mark.parametrize("callable_path", sorted(SIGNATURES))
def test_signatures(callable_path: str) -> None:
    """Key callables have the SPEC parameter names, in order."""
    params = list(inspect.signature(_resolve(callable_path)).parameters)
    assert params == SIGNATURES[callable_path]


@pytest.mark.parametrize("class_path", sorted(DATACLASS_FIELDS))
def test_dataclass_fields(class_path: str) -> None:
    """Value objects are dataclasses whose leading fields are the SPEC fields."""
    cls = _resolve(class_path)
    assert dataclasses.is_dataclass(cls), class_path
    names = [f.name for f in dataclasses.fields(cls)]
    expected = DATACLASS_FIELDS[class_path]
    assert names[: len(expected)] == expected


def _functions_and_classes(tree: ast.Module) -> list[ast.AST]:
    """Every function and class definition of a module."""
    return [node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)]


def test_every_function_and_class_has_a_docstring() -> None:
    """SPEC 4: one-line docstrings everywhere."""
    missing = []
    for path in sorted(SRC.rglob("*.py")):
        for node in _functions_and_classes(ast.parse(path.read_text())):
            if not ast.get_docstring(node):  # type: ignore[arg-type]
                missing.append(f"{path.relative_to(SRC)}:{node.lineno} {node.name}")  # type: ignore[attr-defined]
    assert not missing, missing


def _raises_not_implemented(node: ast.AST) -> bool:
    """True for ``raise NotImplementedError``, ``raise NotImplementedError(...)`` and ``builtins.`` spellings."""
    if not isinstance(node, ast.Raise) or node.exc is None:
        return False
    exc = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
    if isinstance(exc, ast.Name):
        return exc.id == "NotImplementedError"
    return isinstance(exc, ast.Attribute) and exc.attr == "NotImplementedError"


def _not_implemented_lines(source: str) -> list[int]:
    """Line numbers of the ``raise NotImplementedError`` statements of a module source."""
    return sorted(
        node.lineno
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Raise) and _raises_not_implemented(node)
    )


def _not_implemented_raises() -> list[str]:
    """``<path>:<line>`` of every ``raise NotImplementedError`` left in the package."""
    return [
        f"{path.relative_to(SRC)}:{line}"
        for path in sorted(SRC.rglob("*.py"))
        for line in _not_implemented_lines(path.read_text())
    ]


def test_no_not_implemented_stub_remains() -> None:
    """Every WP0 stub (SPEC 20) is implemented: any ``raise NotImplementedError`` left in src is a failure."""
    assert not _not_implemented_raises()


def test_the_stub_detector_sees_every_spelling() -> None:
    """The detector itself: bare, called and qualified raises are found; other raises are not."""
    source = (
        "def a():\n    raise NotImplementedError\n"
        "def b():\n    raise NotImplementedError('WP-X: later')\n"
        "def c():\n    raise builtins.NotImplementedError()\n"
        "def d():\n    raise ValueError('NotImplementedError')\n"
        "def e():\n    try:\n        pass\n    except NotImplementedError:\n        raise\n"
    )
    assert _not_implemented_lines(source) == [2, 4, 6]


_FORBIDDEN_CALLS = {("os", "system"), ("os", "popen"), ("os", "execv"), ("os", "execvp"), ("os", "spawnv")}


def test_subprocesses_only_through_procs() -> None:
    """SPEC 4/5.6: no subprocess, os.system/popen/exec*/spawn* or asyncio subprocess outside procs.py."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        relative = str(path.relative_to(SRC))
        if relative == "procs.py":
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import) and any(alias.name.split(".")[0] == "subprocess" for alias in node.names):
                offenders.append(f"{relative}:{node.lineno} import subprocess")
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] == "subprocess":
                offenders.append(f"{relative}:{node.lineno} from subprocess")
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                pair = (node.value.id, node.attr)
                if (
                    pair in _FORBIDDEN_CALLS
                    or node.value.id == "subprocess"
                    or node.attr.startswith("create_subprocess")
                ):
                    offenders.append(f"{relative}:{node.lineno} {pair[0]}.{pair[1]}")
    assert not offenders, offenders


def test_no_print_in_library_code() -> None:
    """SPEC 4: no print() (cli.py uses click.echo)."""
    offenders = []
    for path in sorted(SRC.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
                offenders.append(f"{path.relative_to(SRC)}:{node.lineno}")
    assert not offenders, offenders


def test_future_annotations_everywhere() -> None:
    """SPEC 4: every module starts with ``from __future__ import annotations`` (empty package inits excepted)."""
    missing = []
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text())
        has_code = any(not isinstance(node, ast.Expr) for node in tree.body)
        future = any(isinstance(n, ast.ImportFrom) and n.module == "__future__" for n in tree.body)
        if has_code and not future:
            missing.append(str(path.relative_to(SRC)))
    assert not missing, missing


def test_plugin_registers_markers_and_options(pytestconfig: pytest.Config) -> None:
    """SPEC 15 markers and --e2e-* options exist (plugin loaded via the pytest11 entry point)."""
    from otterdog_e2e import pytest_plugin

    assert pytestconfig.pluginmanager.has_plugin("otterdog_e2e")
    registered = {line.split(":")[0].split("(")[0] for line in pytestconfig.getini("markers")}
    expected = {
        "live",
        "requires",
        "plan",
        "identities",
        "webapp",
        "docker",
        "org_level",
        "tags",
        "known_bug",
        "differential",
        "scenario",
        "slow",
        "offline",
    }
    assert expected <= registered
    flags = {option.flag for option in pytest_plugin.OPTIONS}
    spec_flags = {
        "--e2e-target",
        "--e2e-sut",
        "--e2e-base-sut",
        "--e2e-reset-sut",
        "--e2e-tags",
        "--e2e-scenario",
        "--e2e-artifacts",
        "--e2e-run-id",
        "--e2e-keep",
        "--e2e-no-reset",
        "--e2e-webapp-image",
        "--e2e-pr-manifest",
        "--e2e-strict-diff",
        "--e2e-no-http-cache",
        "--e2e-allow-remote-webapp",
    }
    assert spec_flags <= flags
    for option in pytest_plugin.OPTIONS:
        pytestconfig.getoption(option.dest)  # registered (raises ValueError otherwise)
    assert pytestconfig.getoption("e2e_keep") is False


def test_cli_entry_point_lists_commands() -> None:
    """The click group exposes the SPEC 16 commands."""
    from click.testing import CliRunner

    from otterdog_e2e.cli import main

    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for command in (
        "doctor",
        "bootstrap",
        "sut",
        "run",
        "pr",
        "relay",
        "janitor",
        "report",
        "scrub-artifacts",
        "cache",
    ):
        assert command in result.output
    assert "app-manifest" in result.output


# ------------------------------------------------------------------------------------------------------------------
# naming
# ------------------------------------------------------------------------------------------------------------------
RUN_ID = "t3c7z8a5"


def test_run_id_re() -> None:
    """RUN_ID_RE: 6 base36 chars + 2 hex chars."""
    assert naming.RUN_ID_RE.match(RUN_ID)
    for bad in ("abcdefgh", "T3C7Z8A5", "t3c7z8a", "t3c7z8a5x", "t3c7-8a5"):
        assert not naming.RUN_ID_RE.match(bad), bad


def test_new_run_context_encodes_time() -> None:
    """New ids are base36(seconds) + 2 hex; run_id_timestamp decodes them."""
    now = datetime(2026, 3, 1, 12, 0, 0, tzinfo=UTC)
    ctx = naming.new_run_context(now=now)
    assert naming.RUN_ID_RE.match(ctx.run_id)
    assert naming.run_id_timestamp(ctx.run_id) == now
    assert ctx.created_at == now
    assert naming.new_run_context(RUN_ID).run_id == RUN_ID
    assert naming.run_id_timestamp("bad") is None


def test_new_run_context_rejects_bad_ids() -> None:
    """Reused ids are validated (SEC-17)."""
    with pytest.raises(ValueError, match="invalid run id"):
        naming.new_run_context("abcdefgh")


def test_run_context_names() -> None:
    """Names, constants, hooks, branches, filters and template vars of SPEC 7."""
    ctx = naming.RunContext(RUN_ID)
    assert ctx.prefix == "e2e-t3c7z8a5"
    assert ctx.const_prefix == "E2E_T3C7Z8A5_"
    assert ctx.name("basic") == "e2e-t3c7z8a5-basic"
    assert ctx.const("my-secret") == "E2E_T3C7Z8A5_MY_SECRET"
    assert ctx.prop("tier") == ctx.name("tier")
    assert ctx.prop("multi_select") == "e2e-t3c7z8a5-multi-select"
    assert ctx.hook_url("repo") == "https://otterdog-e2e.invalid/t3c7z8a5/repo"
    assert ctx.branch("pr") == "e2e/t3c7z8a5/pr"
    assert ctx.repo_filter() == "e2e-t3c7z8a5-*"
    assert ctx.needles() == ("e2e-t3c7z8a5-", "E2E_T3C7Z8A5_", "https://otterdog-e2e.invalid/t3c7z8a5/")
    assert ctx.template_vars() == {
        "run": RUN_ID,
        "p": "e2e-t3c7z8a5",
        "P": "E2E_T3C7Z8A5",
        "hook_base": "https://otterdog-e2e.invalid/t3c7z8a5/",
    }
    assert naming.HOOK_BASE == "https://otterdog-e2e.invalid/"


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("e2e-t3c7z8a5-basic", RUN_ID),
        ("E2E_T3C7Z8A5_SECRET", RUN_ID),
        ("https://otterdog-e2e.invalid/t3c7z8a5/repo", RUN_ID),
        ("e2e/t3c7z8a5/branch", RUN_ID),
        ("heads/e2e/t3c7z8a5/branch", RUN_ID),
        ("refs/heads/otterdog/e2e-t3c7z8a5-pr", RUN_ID),
        ("otterdog/e2e-t3c7z8a5-slug", RUN_ID),
        ("e2e-sandbox1-x", None),
        ("e2e-000000aa-x", None),
        ("my-repo", None),
        ("x-e2e-t3c7z8a5-basic", None),
        ("e2e-t3c7z8a5", None),
    ],
)
def test_extract_run_id(name: str, expected: str | None) -> None:
    """Every naming form carries its run id; implausible or foreign names carry none."""
    assert naming.extract_run_id(name) == expected


def test_e2e_name_guards() -> None:
    """is_e2e_name and is_deletable_ref implement the SPEC 5.2 deletion guards."""
    assert naming.E2E_NAME_RE.match("e2e-t3c7z8a5-x")
    assert naming.is_e2e_name("e2e-t3c7z8a5-x")
    assert naming.is_e2e_name("E2E_T3C7Z8A5_X")
    assert not naming.is_e2e_name("e2e-000000aa-x")
    assert not naming.is_e2e_name(".otterdog")
    for ref in (
        "heads/e2e/t3c7z8a5/x",
        "heads/otterdog/e2e-t3c7z8a5-slug",
        "tags/sut-v1.6.1-1a2b3c4d",
        "tags/e2e-run/t3c7z8a5",
        "heads/e2e-lease",
        "refs/heads/e2e-lease",
    ):
        assert naming.is_deletable_ref(ref), ref
    for ref in ("heads/main", "tags/v1.6.1", "heads/e2e/sandbox1/x", "tags/e2e-run/t3c7z8a5x", "heads/e2e-lease2"):
        assert not naming.is_deletable_ref(ref), ref


# ------------------------------------------------------------------------------------------------------------------
# redact
# ------------------------------------------------------------------------------------------------------------------
SECRET = "s3cr$t-value-123"
TOKEN = "ghp_" + "A1b2C3d4" * 5  # 40 chars after the prefix
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEAx1y2z3abcdefghij\nqrstuvwxyz0123456789ABCDEFGH\n-----END RSA PRIVATE KEY-----"


def test_redactor_literal_and_ignored_values() -> None:
    """Registered values become ***; None and short values are ignored."""
    redactor = Redactor([SECRET, None, "short"])
    assert redactor(f"a {SECRET} b") == "a *** b"
    assert redactor("short") == "short"
    assert SECRET in redactor.literals


@pytest.mark.parametrize(
    "form",
    [
        base64.b64encode(SECRET.encode()).decode(),
        base64.b64encode(f"x-access-token:{SECRET}".encode()).decode(),
        urllib.parse.quote(SECRET, safe=""),
        json.dumps(SECRET)[1:-1],
        SECRET.replace("$", "$$"),
    ],
)
def test_redactor_variants(form: str) -> None:
    """Transformed forms of a secret are redacted too (SEC-09)."""
    assert Redactor([SECRET])(f"[{form}]") == "[***]"


def test_redactor_variants_can_be_disabled() -> None:
    """variants=False registers the literal only."""
    redactor = Redactor()
    redactor.add(SECRET, variants=False)
    encoded = base64.b64encode(SECRET.encode()).decode()
    assert redactor(encoded) == encoded


def test_redactor_longest_first() -> None:
    """Overlapping secrets: the longest wins, nothing leaks."""
    redactor = Redactor(["abcdef", "abcdefgh12"])
    assert redactor("xx abcdefgh12 yy abcdef") == "xx *** yy ***"


@pytest.mark.parametrize(
    "text",
    [
        TOKEN,
        "ghs_" + "x" * 36,
        "github_pat_" + "A" * 30,
        "eyJhbGciOiJSUzI1NiJ9.eyJpc3MiOiIxMjM0NSJ9.c2lnbmF0dXJlLXZhbHVl",
        PEM,
    ],
)
def test_redactor_patterns(text: str) -> None:
    """Token-shaped strings are redacted even when never registered."""
    assert Redactor()(f"<{text}>") == "<***>"


def test_redactor_pem_lines() -> None:
    """Each long PEM line is registered (JSON-escaped or wrapped PEMs leak line by line otherwise)."""
    redactor = Redactor([PEM])
    assert redactor("MIIEowIBAAKCAQEAx1y2z3abcdefghij") == "***"
    assert redactor(json.dumps(PEM)) == '"***"'


def test_redactor_bytes_and_files(tmp_path: Path) -> None:
    """redact_bytes, contains_secret and redact_file share the text rules."""
    redactor = Redactor([SECRET])
    data = f"a {SECRET} b {TOKEN}".encode()
    assert redactor.redact_bytes(data) == b"a *** b ***"
    assert redactor.contains_secret(data)
    assert redactor.contains_secret(TOKEN.encode())
    assert not redactor.contains_secret(b"nothing here")
    path = tmp_path / "out.txt"
    path.write_bytes(data)
    redactor.redact_file(path)
    assert path.read_bytes() == b"a *** b ***"


def test_redactor_add_mask_on_github_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """On GitHub Actions every new literal is masked once with ::add-mask::."""
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    redactor = Redactor()
    redactor.add("100%-secret-value", variants=False)
    redactor.add("100%-secret-value", variants=False)
    lines = [line for line in capsys.readouterr().out.splitlines() if line.startswith("::add-mask::")]
    assert lines == ["::add-mask::100%25-secret-value"]


def test_redactor_mask_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    """set_mask_sink routes add-mask lines (e.g. around pytest capture)."""
    lines: list[str] = []
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    previous = redact.mask_sink()
    redact.set_mask_sink(lines.append)
    try:
        Redactor().add("another-secret-1", variants=False)
    finally:
        redact.set_mask_sink(previous)
    assert lines == ["::add-mask::another-secret-1\n"]


def test_redactor_no_mask_outside_actions(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    """Outside GitHub Actions nothing is printed."""
    monkeypatch.delenv("GITHUB_ACTIONS", raising=False)
    Redactor([SECRET])
    assert capsys.readouterr().out == ""


def test_secret_key_re() -> None:
    """Only credential-like env keys are registered by load_env_files."""
    for key in (
        "E2E_ADMIN_TOKEN",
        "E2E_APP_WEBHOOK_SECRET",
        "X_PASSWORD",
        "E2E_ADMIN_TOTP_SEED",
        "E2E_APP_PRIVATE_KEY",
    ):
        assert redact.SECRET_KEY_RE.search(key), key
    for key in ("E2E_ORG", "E2E_APP_ID", "E2E_ADMIN_LOGIN", "E2E_APP_PRIVATE_KEY_FILE", "E2E_TOKEN_ENV_NAME"):
        assert not redact.SECRET_KEY_RE.search(key), key


@pytest.fixture
def restore_record_factory() -> Any:
    """Restore the logging record factory changed by install_logging_filter."""
    factory = logging.getLogRecordFactory()
    yield
    logging.setLogRecordFactory(factory)


def test_install_logging_filter(restore_record_factory: Any, caplog: pytest.LogCaptureFixture) -> None:
    """After installation every record (message, args, exception text) is redacted for all handlers."""
    redactor = Redactor(["logged-secret-42"])
    redact.install_logging_filter(redactor)
    redact.install_logging_filter(redactor)  # idempotent
    logger = logging.getLogger("otterdog_e2e.test")
    with caplog.at_level(logging.INFO, logger="otterdog_e2e.test"):
        logger.info("token %s", "logged-secret-42")
        try:
            raise ValueError("boom logged-secret-42")
        except ValueError:
            logger.exception("failed")
    assert "logged-secret-42" not in caplog.text
    assert "token ***" in caplog.text
    assert "boom ***" in caplog.text


def test_redacting_filter() -> None:
    """RedactingFilter redacts records passing through a handler."""
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "value=%s", ("filter-secret-7",), None)
    assert redact.RedactingFilter(Redactor(["filter-secret-7"])).filter(record)
    assert record.getMessage() == "value=***"


# ------------------------------------------------------------------------------------------------------------------
# waiting
# ------------------------------------------------------------------------------------------------------------------


class FakeClock:
    """Monotonic clock advanced by sleep()."""

    def __init__(self) -> None:
        """Start at 0."""
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        """Current time."""
        return self.now

    def sleep(self, seconds: float) -> None:
        """Advance time."""
        self.sleeps.append(seconds)
        self.now += seconds


def test_intervals() -> None:
    """Constant intervals repeat; schedules repeat their last step."""
    constant = waiting.intervals(2)
    assert [next(constant) for _ in range(3)] == [2.0, 2.0, 2.0]
    schedule = waiting.intervals(waiting.CONVERGE_BACKOFF)
    assert [next(schedule) for _ in range(5)] == [5.0, 10.0, 20.0, 20.0, 20.0]
    with pytest.raises(ValueError):
        next(waiting.intervals(()))


def test_poll_returns_first_matching_value() -> None:
    """poll stops as soon as until() holds."""
    clock = FakeClock()
    values = iter([1, 2, 3, 4])
    result = waiting.poll(
        lambda: next(values), until=lambda v: v >= 3, timeout=60, interval=5, sleep=clock.sleep, clock=clock
    )
    assert result == 3
    assert clock.sleeps == [5, 5]


def test_poll_timeout_carries_last_value() -> None:
    """On timeout WaitTimeoutError carries the last value and attempts; sleeps never overshoot."""
    clock = FakeClock()
    with pytest.raises(waiting.WaitTimeoutError) as info:
        waiting.poll(
            lambda: "pending",
            until=lambda v: False,
            timeout=12,
            interval=5,
            what="status",
            sleep=clock.sleep,
            clock=clock,
        )
    assert info.value.last == "pending"
    assert info.value.attempts == 4
    assert clock.sleeps == [5, 5, 2]
    assert "status" in str(info.value)
    assert isinstance(info.value, TimeoutError)


def test_poll_without_raise_and_max_attempts() -> None:
    """raise_on_timeout=False returns the last value; max_attempts bounds the calls."""
    clock = FakeClock()
    calls = []

    def fn() -> int:
        """Count calls."""
        calls.append(1)
        return len(calls)

    result = waiting.poll(
        fn,
        until=lambda v: False,
        max_attempts=3,
        interval=(1, 2),
        raise_on_timeout=False,
        sleep=clock.sleep,
        clock=clock,
    )
    assert result == 3
    assert clock.sleeps == [1, 2]
    with pytest.raises(ValueError):
        waiting.poll(fn, until=bool)


def test_wait_until_returns_truthy_value() -> None:
    """wait_until returns the condition's value."""
    clock = FakeClock()
    values = iter([None, {}, {"ok": True}])
    assert waiting.wait_until(lambda: next(values), timeout=30, interval=1, sleep=clock.sleep, clock=clock) == {
        "ok": True
    }


def test_retry() -> None:
    """retry re-calls on accepted exceptions, re-raises others and the last one when exhausted."""
    clock = FakeClock()
    attempts = []

    def flaky() -> str:
        """Fail twice, then succeed."""
        attempts.append(1)
        if len(attempts) < 3:
            raise ConnectionError("409")
        return "ok"

    assert (
        waiting.retry(
            flaky,
            retry_if=lambda e: isinstance(e, ConnectionError),
            timeout=30,
            interval=5,
            sleep=clock.sleep,
            clock=clock,
        )
        == "ok"
    )
    assert clock.sleeps == [5, 5]
    with pytest.raises(KeyError):
        waiting.retry(
            lambda: {}["x"],
            retry_if=lambda e: isinstance(e, ConnectionError),
            max_attempts=3,
            sleep=clock.sleep,
            clock=clock,
        )

    def always() -> None:
        """Always fail."""
        raise ConnectionError("still")

    with pytest.raises(ConnectionError):
        waiting.retry(always, retry_if=lambda e: True, max_attempts=2, interval=0, sleep=clock.sleep, clock=clock)


def test_deadline() -> None:
    """Deadline tracks elapsed/remaining time; None never expires."""
    clock = FakeClock()
    deadline = waiting.Deadline(10, clock=clock)
    clock.sleep(4)
    assert deadline.elapsed() == 4
    assert deadline.remaining() == 6
    assert not deadline.expired()
    clock.sleep(6)
    assert deadline.expired()
    assert waiting.Deadline(None, clock=clock).remaining() == float("inf")


# ------------------------------------------------------------------------------------------------------------------
# procs
# ------------------------------------------------------------------------------------------------------------------
BASE_ENV = {
    "PATH": "/usr/bin:/bin",
    "LANG": "C.UTF-8",
    "E2E_ADMIN_TOKEN": "x",
    "E2E_ORG": "org",
    "OTTERDOG_CONFIG_ROOT": "/real/configs",
    "OTTER_X": "1",
    "GITHUB_TOKEN": "x",
    "GH_TOKEN": "x",
    "GITHUB_PAT_X": "x",
    "ACTIONS_RUNTIME_TOKEN": "x",
    "NPM_TOKEN": "x",
    "MY_SECRET": "x",
    "DB_PASSWORD": "x",
    "ADMIN_TOTP_SEED": "x",
    "SSH_AUTH_SOCK": "/tmp/ssh",
    "GIT_ASKPASS": "x",
    "SSH_ASKPASS": "x",
    "PYTHONPATH": "/x",
    "PYTHONSTARTUP": "/x",
    "VIRTUAL_ENV": "/venv",
    "PIP_INDEX_URL": "https://x",
    "PIP_EXTRA_INDEX_URL": "https://x",
    "FORCE_COLOR": "1",
    "HOME": "/home/operator",
    "GITHUB_ACTIONS": "true",
}


def test_sanitized_env_removes_credentials_and_hooks(tmp_path: Path) -> None:
    """Credentials, operator hooks and interpreter overrides never reach children."""
    env = procs.sanitized_env(base=BASE_ENV, home=tmp_path / "home")
    for key, value in BASE_ENV.items():
        if key in ("PATH", "LANG", "GITHUB_ACTIONS"):
            assert env[key] == value
        elif key != "HOME":
            assert key not in env, key


def test_sanitized_env_sets_deterministic_output_and_isolated_home(tmp_path: Path) -> None:
    """SET_ENV values, HOME and XDG dirs below the scratch home."""
    home = tmp_path / "home"
    env = procs.sanitized_env(base=BASE_ENV, home=home)
    expected = {
        "COLUMNS": "4096",
        "LINES": "1000",
        "NO_COLOR": "1",
        "TERM": "dumb",
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_TERMINAL_PROMPT": "0",
        "NETRC": "/dev/null",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / ".config"),
        "XDG_CACHE_HOME": str(home / ".cache"),
        "XDG_DATA_HOME": str(home / ".local/share"),
    }
    assert {key: env[key] for key in expected} == expected
    assert not home.exists()  # pure: nothing created


def test_sanitized_env_keep_home_and_extra(tmp_path: Path) -> None:
    """keep_home keeps the operator HOME (docker); extra is applied last (credentials for otterdog)."""
    env = procs.sanitized_env({"E2E_OTTERDOG_API_TOKEN": "tok", "COLUMNS": "80"}, base=BASE_ENV, keep_home=True)
    assert env["HOME"] == "/home/operator"
    assert "XDG_CONFIG_HOME" not in env
    assert env["E2E_OTTERDOG_API_TOKEN"] == "tok"
    assert env["COLUMNS"] == "80"


def test_default_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """The default HOME is the configured scratch home, else <E2E_CACHE_DIR>/home."""
    monkeypatch.setenv("E2E_CACHE_DIR", str(tmp_path / "cache"))
    assert procs.default_home() == tmp_path / "cache" / "home"
    procs.set_default_home(tmp_path / "scratch-home")
    try:
        assert procs.sanitized_env(base={})["HOME"] == str(tmp_path / "scratch-home")
    finally:
        procs.set_default_home(None)


def test_run_uses_sanitized_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """run() passes the sanitized env, creates the scratch HOME and captures text output."""
    monkeypatch.setenv("E2E_ADMIN_TOKEN", "must-not-leak")
    home = tmp_path / "home"
    code = "import json, os; print(json.dumps({k: os.environ.get(k) for k in ('E2E_ADMIN_TOKEN', 'HOME', 'X')}))"
    result = procs.run([sys.executable, "-c", code], home=home, extra_env={"X": "1"}, cwd=tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == {"E2E_ADMIN_TOKEN": None, "HOME": str(home), "X": "1"}
    assert stat.S_IMODE(home.stat().st_mode) == 0o700
    assert (home / ".config").is_dir()


def test_run_input_check_and_timeout(tmp_path: Path) -> None:
    """stdin input, check=True and timeouts behave like subprocess.run."""
    home = tmp_path / "home"
    echo = procs.run([sys.executable, "-c", "import sys; print(sys.stdin.read().upper())"], input="y\n", home=home)
    assert echo.stdout.strip() == "Y"
    closed = procs.run([sys.executable, "-c", "import sys; print(repr(sys.stdin.read()))"], home=home)
    assert closed.stdout.strip() == "''"
    with pytest.raises(procs.CalledProcessError):
        procs.run([sys.executable, "-c", "raise SystemExit(3)"], home=home, check=True)
    with pytest.raises(procs.TimeoutExpired):
        procs.run([sys.executable, "-c", "import time; time.sleep(5)"], home=home, timeout=0.2)


def test_unshare_available_is_bool(monkeypatch: pytest.MonkeyPatch) -> None:
    """unshare_available never raises."""

    def missing(*args: Any, **kwargs: Any) -> Any:
        """Simulate a missing binary."""
        raise FileNotFoundError("unshare")

    monkeypatch.setattr(procs, "run", missing)
    assert procs.unshare_available() is False


# ------------------------------------------------------------------------------------------------------------------
# webhooks/signing
# ------------------------------------------------------------------------------------------------------------------
DOC_SECRET = "It's a Secret to Everybody"
DOC_SIGNATURE = "sha256=757107ea0eb2509fc211221cce984b8a37570b6d7586c22c46f4379c8b043e17"


def test_sign_matches_github_documentation() -> None:
    """GitHub's documented test vector (validating-webhook-deliveries)."""
    assert signing.sign_sha256(DOC_SECRET, b"Hello, World!") == DOC_SIGNATURE
    expected_sha1 = hmac.new(DOC_SECRET.encode(), b"Hello, World!", hashlib.sha1).hexdigest()
    assert signing.sign_sha1(DOC_SECRET, b"Hello, World!") == f"sha1={expected_sha1}"
    assert signing.sign_sha1(DOC_SECRET.encode(), b"Hello, World!") == f"sha1={expected_sha1}"


def test_serialize_payload() -> None:
    """Compact UTF-8 JSON; bytes and str pass through."""
    assert signing.serialize_payload({"a": 1, "b": "é"}) == '{"a":1,"b":"é"}'.encode()
    assert signing.serialize_payload(b"raw") == b"raw"
    assert signing.serialize_payload("text") == b"text"
    body = signing.encode_body({"zen": "x y"}, signing.FORM_CONTENT_TYPE)
    assert urllib.parse.parse_qs(body.decode()) == {"payload": ['{"zen":"x y"}']}


def test_webhook_headers_valid() -> None:
    """Valid deliveries carry both signatures, event, guid and installation target headers."""
    body = signing.serialize_payload({"zen": "z"})
    headers = signing.webhook_headers("ping", body, "secret", delivery_id="guid-1", hook_id=7, target_id=42)
    assert headers["X-GitHub-Event"] == "ping"
    assert headers["X-GitHub-Delivery"] == "guid-1"
    assert headers["Content-Type"] == "application/json"
    assert headers["X-Hub-Signature"] == signing.sign_sha1("secret", body)
    assert headers["X-Hub-Signature-256"] == signing.sign_sha256("secret", body)
    assert headers["X-GitHub-Hook-ID"] == "7"
    assert headers["X-GitHub-Hook-Installation-Target-Type"] == "integration"
    assert headers["X-GitHub-Hook-Installation-Target-ID"] == "42"
    assert headers["User-Agent"].startswith("GitHub-Hookshot/")


def test_webhook_headers_modes() -> None:
    """Signature modes used by O-WEB-SIG: missing, invalid, sha256-only, sha1-only; content type override."""
    body = b"{}"
    assert "X-Hub-Signature" not in signing.webhook_headers("ping", body, "s", signature="missing")
    assert "X-Hub-Signature-256" not in signing.webhook_headers("ping", body, "s", signature="missing")
    invalid = signing.webhook_headers("ping", body, "s", signature="invalid")
    assert invalid["X-Hub-Signature"].startswith("sha1=")
    assert invalid["X-Hub-Signature"] != signing.sign_sha1("s", body)
    only256 = signing.webhook_headers("ping", body, "s", signature="sha256-only")
    assert "X-Hub-Signature" not in only256
    assert only256["X-Hub-Signature-256"] == signing.sign_sha256("s", body)
    only1 = signing.webhook_headers("ping", body, "s", signature="sha1-only")
    assert "X-Hub-Signature-256" not in only1
    charset = signing.webhook_headers("ping", body, "s", content_type="application/json; charset=utf-8")
    assert charset["Content-Type"] == "application/json; charset=utf-8"
    assert "Content-Type" not in signing.webhook_headers("ping", body, "s", content_type=None, target_type=None)
    guid = signing.webhook_headers("ping", body, "s")["X-GitHub-Delivery"]
    assert re.fullmatch(r"[0-9a-f-]{36}", guid)
    with pytest.raises(ValueError):
        signing.webhook_headers("ping", body, "s", signature="bogus")


# ------------------------------------------------------------------------------------------------------------------
# value objects with WP0-implemented behaviour
# ------------------------------------------------------------------------------------------------------------------
def test_template_ref_import_path_and_offline_template() -> None:
    """TemplateRef.import_path is vendor/<repo>/<file>; the offline template matches SPEC 10.6."""
    from otterdog_e2e.sut.template import TemplateRef, offline_template

    ref = TemplateRef(
        "https://github.com/o/r#examples/template/otterdog-defaults.libsonnet@abc",
        "r",
        "examples/template/otterdog-defaults.libsonnet",
        "abc",
    )
    assert ref.import_path == "vendor/r/examples/template/otterdog-defaults.libsonnet"
    offline = offline_template()
    assert offline.url == "https://github.com/e2e-offline/template#otterdog-defaults.libsonnet@offline"
    assert offline.repo_name == "template"
    assert offline.import_path == "vendor/template/otterdog-defaults.libsonnet"


def test_capabilities_plan_matrix() -> None:
    """PLAN_MATRIX nests free < team < enterprise; probe/override-only caps are not plan caps."""
    from otterdog_e2e.capabilities import PLAN_MATRIX, Cap

    assert PLAN_MATRIX["free"] == {Cap.PUBLIC_REPOS, Cap.SECRET_SCANNING_PUBLIC}
    assert PLAN_MATRIX["free"] < PLAN_MATRIX["team"] < PLAN_MATRIX["enterprise"]
    assert Cap.ORG_RULESETS in PLAN_MATRIX["team"]
    assert Cap.OTTERDOG_ORG_RULESETS not in PLAN_MATRIX["team"]
    assert Cap.OTTERDOG_ORG_RULESETS in PLAN_MATRIX["enterprise"]
    for cap in (Cap.CUSTOM_PROPERTIES, Cap.ACTIONS_CACHE_LIMIT, Cap.GHAS_PRIVATE, Cap.APP, Cap.DOCKER):
        assert all(cap not in caps for caps in PLAN_MATRIX.values())
    assert all(cap.value == cap.name.lower() for cap in Cap)


def test_capabilities_from_plan_has_missing_to_json() -> None:
    """from_plan applies extra/remove; has/missing accept names; unknown names fail loudly."""
    from otterdog_e2e.capabilities import Cap, from_plan, plans_at_least

    caps = from_plan("enterprise", extra=["ghas_private"], remove=[Cap.LARGER_RUNNERS])
    assert caps.has("ghas_private") and caps.has(Cap.INTERNAL_REPOS)
    assert not caps.has("larger_runners")
    assert caps.missing(["public_repos", "larger_runners", Cap.CUSTOM_PROPERTIES]) == [
        "larger_runners",
        "custom_properties",
    ]
    data = caps.to_json()
    assert data["plan"] == "enterprise"
    assert data["caps"] == sorted(data["caps"]) and "ghas_private" in data["caps"]
    json.dumps(data)
    with pytest.raises(ValueError):
        caps.has("no_such_capability")
    with pytest.raises(ValueError):
        from_plan("pro")
    assert plans_at_least("team") == ("team", "enterprise")


def _plan_object(
    op: str,
    header: str,
    body: list[str] | None = None,
    notes: list[str] | None = None,
    value: str = "",
    parent: str | None = None,
) -> Any:
    """A PlanObject for tests."""
    from otterdog_e2e.otterdog.output import PlanObject

    return PlanObject(
        op, "repository", "name", value, "repository" if parent else None, parent, header, body or [], notes or []
    )


def _plan(
    objects: list[Any], counts: tuple[int | None, int | None, int | None] = (0, 0, 0), aborted: bool = False
) -> Any:
    """A PlanResult for tests."""
    from otterdog_e2e.otterdog.output import PlanResult

    return PlanResult(counts[0], counts[1], counts[2], objects, aborted, None, [], "")


def test_plan_object_read_only_detection() -> None:
    """A change whose every changed key is reported read-only is a no-op for converge (OC-10)."""
    read_only = _plan_object(
        "change",
        "~ settings {",
        ['    ~ plan = "free" -> "team"'],
        ["Note: setting 'plan' is read-only, will be skipped."],
    )
    assert read_only.changed_keys == ["plan"]
    assert read_only.read_only_keys == ["plan"]
    assert read_only.is_read_only
    mixed = _plan_object(
        "change",
        "~ settings {",
        [
            '    ~ name = "a" -> "b"',
            '    ~ plan = "free" -> "team"',
            "  Note: setting 'plan' is read-only, will be skipped.",
        ],
    )
    assert mixed.changed_keys == ["name", "plan"]
    assert not mixed.is_read_only
    nested = _plan_object(
        "change",
        '~ repository[name="x"] {',
        [
            "    ~ topics      = [",
            '      + "e2e"',
            "    ~ ]",
            "    ~ workflows = {",
            "      ~ enabled = true -> false",
            "    ~ }",
        ],
    )
    assert nested.changed_keys == ["topics", "workflows"]
    assert not _plan_object(
        "remove", "- remove x {", ["    - plan = 1"], ["Note: setting 'plan' is read-only, will be skipped."]
    ).is_read_only


def test_plan_object_run_id() -> None:
    """Removals are attributed through their value or their parent repository."""
    assert _plan_object("remove", "h", value="e2e-t3c7z8a5-basic").run_id == RUN_ID
    assert _plan_object("remove", "h", value="main", parent="e2e-t3c7z8a5-basic").run_id == RUN_ID
    assert _plan_object("remove", "h", value="human-repo").run_id is None


def test_plan_result_filters_and_noop() -> None:
    """objects_for/removals/is_noop of SPEC 11.3."""
    mine = _plan_object(
        "add",
        '+ add repository[name="e2e-t3c7z8a5-basic"] {',
        ['    + name = "e2e-t3c7z8a5-basic"'],
        value="e2e-t3c7z8a5-basic",
    )
    foreign = _plan_object("remove", '- remove repository[name="other"] {', value="other")
    read_only = _plan_object(
        "change",
        "~ settings {",
        ['    ~ plan = "free" -> "team"'],
        ["Note: setting 'plan' is read-only, will be skipped."],
    )
    needles = naming.RunContext(RUN_ID).needles()
    plan = _plan([mine, foreign, read_only], counts=(1, 0, 1))
    assert plan.objects_for(needles) == [mine]
    assert plan.removals() == [foreign]
    assert not plan.is_noop()
    assert not plan.is_noop(needles)
    assert _plan([foreign, read_only], counts=(0, 0, 1)).is_noop(needles)
    assert not _plan([read_only], counts=(0, 0, 1)).is_noop()
    assert _plan([read_only], counts=(0, 0, 0)).is_noop()
    assert not _plan([], counts=(None, None, None)).is_noop()
    assert not _plan([], counts=(0, 0, 0), aborted=True).is_noop(needles)


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("  ~ settings {", ("~", "settings", None, None, None)),
        ('  ~ repository[name="e2e-t3c7z8a5-basic"] {', ("~", "repository", "name", "e2e-t3c7z8a5-basic", None)),
        (
            '  + add custom_property[name="e2e-t3c7z8a5-tier"] {',
            ("+", "custom_property", "name", "e2e-t3c7z8a5-tier", None),
        ),
        ('  - remove repository[name="e2e-t3c7z8a5-gone"] {', ("-", "repository", "name", "e2e-t3c7z8a5-gone", None)),
        (
            '  + add repo_secret[name="E2E_T3C7Z8A5_SEC", repository=e2e-t3c7z8a5-basic] {',
            ("+", "repo_secret", "name", "E2E_T3C7Z8A5_SEC", "e2e-t3c7z8a5-basic"),
        ),
        (
            '  - remove branch_protection_rule[pattern="main", repository=e2e-t3c7z8a5-basic] {',
            ("-", "branch_protection_rule", "pattern", "main", "e2e-t3c7z8a5-basic"),
        ),
        ('  ! repository[name="x"] {', ("!", "repository", "name", "x", None)),
        (
            '  + add org_webhook[url="https://otterdog-e2e.invalid/t3c7z8a5/org"] {',
            ("+", "org_webhook", "url", "https://otterdog-e2e.invalid/t3c7z8a5/org", None),
        ),
    ],
)
def test_header_re_matches_real_headers(line: str, expected: tuple[str | None, ...]) -> None:
    """HEADER_RE parses the headers otterdog 1.7.0.dev19 printed offline (OC-10)."""
    from otterdog_e2e.otterdog.output import HEADER_RE

    match = HEADER_RE.match(line)
    assert match is not None
    symbol = next(group for group in match.groups()[:4] if group)
    assert (symbol, match["kind"], match["key"], match["val"], match["pval"]) == expected


def test_logger_and_unknown_property_patterns() -> None:
    """LOGGER_LINE_RE and UNKNOWN_PROPERTIES_RE match otterdog's logger output (OC-08)."""
    from otterdog_e2e.otterdog.output import LOGGER_LINE_RE, LOGGER_SOURCE_SUFFIX_RE, UNKNOWN_PROPERTIES_RE

    line = (
        "WARNING  ignoring unknown properties found while validating organization config: x"
        + " " * 40
        + "github_organization.py:288"
    )
    assert LOGGER_LINE_RE.match(line)
    assert UNKNOWN_PROPERTIES_RE.search(line)
    assert LOGGER_SOURCE_SUFFIX_RE.sub("", line).endswith("config: x")


def test_config_fragments() -> None:
    """from_mapping validates keys, merged concatenates per key, to_mapping feeds the template."""
    from otterdog_e2e.otterdog.render import FRAGMENT_KEYS, ConfigFragments

    first = ConfigFragments.from_mapping({"repositories": ["orgs.newRepo('a')"], "settings": "has_discussions: true"})
    assert first.settings == ["has_discussions: true"]
    second = ConfigFragments.from_mapping({"repositories": ["orgs.newRepo('b')"], "extra": []})
    merged = first.merged(second)
    assert merged.repositories == ["orgs.newRepo('a')", "orgs.newRepo('b')"]
    assert first.repositories == ["orgs.newRepo('a')"]
    assert tuple(merged.to_mapping()) == FRAGMENT_KEYS
    assert ConfigFragments.from_mapping(None).is_empty()
    with pytest.raises(ValueError, match="unknown fragment"):
        ConfigFragments.from_mapping({"repos": []})
    with pytest.raises(ValueError, match="string"):
        ConfigFragments.from_mapping({"teams": [1]})


def _target(**overrides: Any) -> Any:
    """A Target value object for tests."""
    from otterdog_e2e.settings import IdentitySpec, Target, WebappSpec

    values: dict[str, Any] = {
        "name": "free",
        "description": "test",
        "org": "e2e-test-org",
        "org_id": 1,
        "allowed_org_ids": (1,),
        "expected_plan": "free",
        "marker": "[otterdog-e2e]",
        "capability_overrides": {"add": (), "remove": ()},
        "configs_repo": "otterdog-e2e-configs",
        "org_config_repo": "auto",
        "defaults_repo": "otterdog-e2e-defaults",
        "template_mode": "auto",
        "template_url": None,
        "identities": {"admin": IdentitySpec("admin", "e2e-admin", "E2E_ADMIN_TOKEN")},
        "app": None,
        "admin_team": "otterdog-admins",
        "approval_team": "project-leads",
        "contributors_team": "e2e-contributors",
        "webapp": WebappSpec("relay", None, None, "e2e/otterdog-validate", "e2e/otterdog-sync", 1, 5000),
        "fixture_repos": ("otterdog-e2e-fixture-a", "otterdog-e2e-configs"),
        "extra_protected_repos": ("human",),
        "baseline_settings": {},
        "source_path": Path("targets/free.yaml"),
    }
    values.update(overrides)
    return Target(**values)


def test_target_config_repo_and_protected_repos() -> None:
    """auto -> per-session config repo; protected repos deduplicated in SPEC order."""
    ctx = naming.RunContext(RUN_ID)
    target = _target()
    assert target.config_repo_for(ctx) == "e2e-t3c7z8a5-config"
    assert target.protected_repos(ctx) == (
        "e2e-t3c7z8a5-config",
        "otterdog-e2e-configs",
        "otterdog-e2e-defaults",
        "otterdog-e2e-fixture-a",
        "human",
    )
    assert _target(org_config_repo=".otterdog").config_repo_for(ctx) == ".otterdog"


def test_harness_settings_scratch(tmp_path: Path) -> None:
    """scratch() is cache_dir/run/<id>, created private."""
    from otterdog_e2e.settings import HarnessSettings

    settings = HarnessSettings(
        tmp_path, tmp_path / "cache", tmp_path / "artifacts", "eclipse-csi/otterdog", tmp_path, tmp_path
    )
    scratch = settings.scratch(RUN_ID)
    assert scratch == tmp_path / "cache" / "run" / RUN_ID
    assert stat.S_IMODE(scratch.stat().st_mode) == 0o700
    assert stat.S_IMODE((tmp_path / "cache").stat().st_mode) == 0o700


def test_identity_and_credentials_hide_secrets() -> None:
    """Tokens, keys and webhook secrets never appear in repr."""
    from otterdog_e2e.settings import AppCredentials, Identity

    assert "tok-123456" not in repr(Identity("admin", "e2e-admin", "tok-123456"))
    creds = AppCredentials("1", "PEM-SECRET", "hook-secret", "slug")
    assert "PEM-SECRET" not in repr(creds) and "hook-secret" not in repr(creds)


def test_verified_org_requires_verify_target() -> None:
    """VerifiedOrg cannot be forged by constructor or dataclasses.replace (SEC-08)."""
    from otterdog_e2e.safety import SafetyError, VerifiedOrg
    from otterdog_e2e.testing.fakes import make_verified_org

    with pytest.raises(SafetyError):
        VerifiedOrg("org", 1, "free", "t", datetime.now(UTC), {})
    verified = make_verified_org()
    assert verified.login == "e2e-test-org" and verified.plan == "free"
    with pytest.raises(SafetyError):
        dataclasses.replace(verified, login="eclipse")
    assert "org_json" not in repr(verified)


def test_safety_constants() -> None:
    """Denylist and scope allowlists of SPEC 5.1."""
    from otterdog_e2e.safety import ALLOWED_SCOPES, FORBIDDEN_ORG_PATTERNS

    def forbidden(login: str) -> bool:
        """Denylist match."""
        return any(re.search(pattern, login, re.IGNORECASE) for pattern in FORBIDDEN_ORG_PATTERNS)

    for login in (
        "eclipse",
        "Eclipse-Foo",
        "eclipsefdn-x",
        "eclipse-csi",
        "adoptium",
        "jakartaee",
        "EclipseNebula",
        "jetty-project",
    ):
        assert forbidden(login), login
    for login in ("eclipsed-e2e", "e2e-test-org", "my-adoptium", "osgi-e2e"):
        assert not forbidden(login), login
    assert "delete_repo" in ALLOWED_SCOPES["admin"] and "delete_repo" not in ALLOWED_SCOPES["other"]


def test_cli_result_output_and_assert_ok() -> None:
    """output joins stdout/stderr; assert_ok raises a redacted, informative AssertionError."""
    from otterdog_e2e.testing.fakes import cli_result

    ok = cli_result("validate", "out\n", stderr="err")
    assert ok.output == "out\nerr"
    assert ok.assert_ok() is ok
    assert cli_result("validate", "only").output == "only"
    assert cli_result("validate", "", stderr="e").output == "e"
    failed = cli_result("plan", f"line\nboom {TOKEN}", exit_code=2)
    with pytest.raises(AssertionError) as info:
        failed.assert_ok("plan step")
    assert "exit code 2" in str(info.value) and TOKEN not in str(info.value) and "plan step" in str(info.value)
    with pytest.raises(AssertionError, match="timed out"):
        cli_result("plan", timed_out=True).assert_ok()
    with pytest.raises(AssertionError, match="infra error"):
        cli_result("plan", infra_error="API rate limit exceeded").assert_ok()


def test_sut_spec_trust_and_resolved_to_json() -> None:
    """Spec-level trust (SPEC 5.5) and the JSON form of ResolvedSut."""
    from otterdog_e2e.sut.spec import ResolvedSut, SutSpec

    trusted = {"release": "latest", "tag": "v1.6.1", "path": "/x", "dirty": "/x"}
    for kind, value in trusted.items():
        assert SutSpec(f"{kind}:{value}", kind, value).trusted
    assert SutSpec("branch:main", "branch", "main").trusted
    assert not SutSpec("branch:feature", "branch", "feature").trusted
    assert not SutSpec("pr:1@" + "a" * 40, "pr", "1", "a" * 40).trusted
    assert not SutSpec("sha:abcdef1", "sha", "abcdef1").trusted
    sut = ResolvedSut(
        SutSpec("v1.6.1", "tag", "v1.6.1"),
        "v1.6.1",
        "a" * 40,
        "1.6.1",
        "1.6.1",
        Path("/src"),
        "https://github.com/eclipse-csi/otterdog",
        True,
    )
    data = sut.to_json()
    assert data["spec"] == "v1.6.1" and data["source_dir"] == "/src" and data["changed_files"] == []
    json.dumps(data)


def test_differential_value_objects() -> None:
    """ExpectedDelta matching and DiffReport partitions."""
    from otterdog_e2e.differential import Delta, DiffReport, ExpectedDelta

    expected = ExpectedDelta("O-VAL-790", kind="cli")
    assert expected.matches("O-VAL-790", "s1", "cli", "validate")
    assert not expected.matches("O-VAL-790", "s1", "oracle", "x")
    deltas = [
        Delta("a", "s", "cli", "k", "1", "2", "-1\n+2", True),
        Delta("b", "s", "cli", "k", None, "2", "+2", False),
    ]
    report = DiffReport("v1.6.1", "pr792-d0d3b08", deltas, unchanged=3, not_comparable=["c"])
    assert report.expected() == [deltas[0]] and report.unexpected() == [deltas[1]]
    data = report.to_json()
    assert data["counts"] == {"unexpected": 1, "expected": 1}
    json.dumps(data)


def test_small_value_objects() -> None:
    """Remaining simple behaviours of WP0 value objects."""
    from otterdog_e2e.config_repo import MARKERS, comment_marker
    from otterdog_e2e.github.http import GitHubError
    from otterdog_e2e.github.lease import LeaseBusy
    from otterdog_e2e.github.oracle import normalize
    from otterdog_e2e.known_bugs import KnownBug
    from otterdog_e2e.observe import Observation
    from otterdog_e2e.otterdog.workspace import CREDENTIAL_ENV, ConfigWorkspace, credentials_env
    from otterdog_e2e.scenarios.engine import ScenarioOutcome
    from otterdog_e2e.settings import Identity
    from otterdog_e2e.sut.source import UpstreamMirror
    from otterdog_e2e.sut.template import offline_template
    from otterdog_e2e.webhooks.relay import RelayedDelivery, default_accept

    assert MARKERS["validate"] == "<!-- Otterdog Comment: validate -->"
    assert comment_marker("x\n<!-- Otterdog Comment: check-sync -->\ny") == "check-sync"
    assert comment_marker("plain") is None
    error = GitHubError(404, "GET", "https://api.github.com/x", f"token {TOKEN}", {"X-GitHub-SSO": "required"})
    assert TOKEN not in str(error) and error.status == 404 and error.headers == {"X-GitHub-SSO": "required"}
    assert LeaseBusy({"holder": "ci", "run_id": RUN_ID}).holder["holder"] == "ci"
    assert normalize({"id": 1, "url": "u", "html_url": "h", "hooks_url": "x", "n": [{"node_id": "n", "v": 2}]}) == {
        "id": 1,
        "n": [{"v": 2}],
    }
    assert KnownBug("KB-001", "apply exits 0").xfail_reason == "KB-001: apply exits 0"
    observation = Observation("v1", "base", "s", "step", "cli", "validate", "exit_code: 0\n", {"a": 1})
    assert observation.identity == ("s", "step", "cli", "validate") and hash(observation)
    assert credentials_env(None) == {
        CREDENTIAL_ENV["api_token"]: "offline-dummy-token",
        **dict.fromkeys(list(CREDENTIAL_ENV.values())[1:], "unset"),
    }
    assert credentials_env(Identity("admin", "a", "tok"))["E2E_OTTERDOG_API_TOKEN"] == "tok"
    workspace = ConfigWorkspace(Path("/ws"), org="o", template=offline_template(), config_repo=".otterdog")
    assert workspace.config_file == Path("/ws/otterdog.json")
    assert workspace.org_config_file == Path("/ws/orgs/o/o.jsonnet")
    assert workspace.base_config_file == Path("/ws/orgs/o/o.jsonnet-BASE")
    assert workspace.project == "o"
    assert ScenarioOutcome("s").ok and not ScenarioOutcome("s", failures=["x"]).ok
    now = datetime(2026, 1, 1, tzinfo=UTC)
    delivery = RelayedDelivery(1, "g", "ping", None, 1, None, None, now, now, now + timedelta(seconds=3), 200, 204)
    assert delivery.lag_seconds == 3
    assert default_accept({"organization": {"login": "o"}}, org="o")
    assert not default_accept({"organization": {"login": "other"}}, org="o")
    assert default_accept({}, org="o", event="ping")
    assert UpstreamMirror(Path("/c")).path == Path("/c/mirror/eclipse-csi__otterdog.git")


def test_org_config_renderer_refuses_profiles_without_marker() -> None:
    """The renderer refuses to start from a description without the safety marker (OC-01)."""
    from otterdog_e2e.otterdog.render import BaselineSpec, OrgConfigRenderer, RenderError
    from otterdog_e2e.sut.template import offline_template

    kwargs: dict[str, Any] = {
        "template": offline_template(),
        "org": "o",
        "plan": "free",
        "baseline": BaselineSpec(),
        "marker": "[otterdog-e2e]",
        "hide_cache_limit": False,
    }
    with pytest.raises(RenderError):
        OrgConfigRenderer(org_profile={"description": "production org"}, **kwargs)
    renderer = OrgConfigRenderer(org_profile={"description": "[otterdog-e2e] test"}, **kwargs)
    assert renderer.project == "o"


def test_appmanifest_permissions() -> None:
    """GH-01: permission names are the parameterized App permission names."""
    from otterdog_e2e.appmanifest import DEFAULT_EVENTS, DEFAULT_PERMISSIONS

    assert DEFAULT_PERMISSIONS["organization_custom_org_roles"] == "write"
    assert DEFAULT_PERMISSIONS["actions_variables"] == "write"
    assert DEFAULT_PERMISSIONS["organization_custom_properties"] == "admin"
    assert {"custom_properties", "variables", "organization_variables", "organization_custom_roles"}.isdisjoint(
        DEFAULT_PERMISSIONS
    )
    assert DEFAULT_EVENTS == [
        "issue_comment",
        "pull_request",
        "pull_request_review",
        "push",
        "workflow_job",
        "workflow_run",
    ]


def test_unit_tier_blocks_network_but_not_loopback() -> None:
    """tests/unit/conftest.py refuses non-loopback connections (no network in the unit tier)."""
    import socket

    with pytest.raises(RuntimeError, match="network access is not allowed"):
        socket.create_connection(("192.0.2.1", 443), timeout=0.5)
    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with socket.create_connection(server.getsockname(), timeout=2):
            pass
