"""Baseline reset and the guarded ``apply -d`` (SPEC 11.5, 5.4).

``-r`` only scopes repositories: org-level objects are always diffed and, with ``-d``, deleted. Every ``apply -d``
therefore goes through guarded_apply: plan with the same filter, parse fail-closed (the ``Plan:`` delete count must
equal the number of ``- remove`` headers, nested included), require a purgeable run id on every REMOVE and no
protected name, then apply. Resets use the trusted reset CLI, never the SUT under test.

Facts the guard relies on (otterdog 1.7.0.dev19, tests/unit/data): removing a whole repository prints a single
``- remove repository[...]`` block (its nested objects are neither printed nor counted); nested removals carry their
parent (``repository=<repo>``, ``environment=<env>`` for env secrets/variables); every REMOVE counts 1 in ``Plan:``.
A REMOVE is attributed to a run through its own name or its parent's (PlanObject.run_id).

The same rules guard config texts sent to the webapp (guard_config_change, SEC-07): it is the only implementation of
the ConfigRepoFlow guard (``local-plan`` base -> head with the trusted reset CLI, then check_removals).

Web-only settings (docs/web-ui-testing.md) are invisible to the ``-n`` reset: the web-UI tier records their original
values (record_web_settings) before it changes them, and restore_web_settings brings them back with a TRUSTED
web-mode CLI (guarded plan + apply of the baseline with every recorded value pinned, no ``-d``). The plugin calls it
at session end while web_restore_pending, i.e. whenever the web-UI tier ran but could not verify its own restore.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Mapping, Sequence
from typing import TYPE_CHECKING, Any

from otterdog_e2e.otterdog.output import ApplyResult
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.runner import OtterdogCli
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.config_repo import ConfigRepoFlow
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.output import PlanObject, PlanResult
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult
    from otterdog_e2e.settings import Target

log = logging.getLogger(__name__)

_HEADER_REPO_RE = re.compile(r"\brepository=\"?(?P<repo>[^\",\]\s]+)")  # nested headers: ..., repository=<name>]
GUARD_WORKSPACE = "guard-workspace"
GUARD_ARTIFACTS = "guard"  # the guard CLI's command copies: <reset artifacts>/guard/cli/ (role "reset" in reports)
CHECK_STATUS_JSON = "baseline-check-status.json"
TAIL_LINES = 30


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    """Last ``lines`` lines of ``text``."""
    return "\n".join(text.splitlines()[-lines:])


def _total(values: Sequence[int | None]) -> int | None:
    """Sum of the values, None when any is None."""
    return None if any(value is None for value in values) else sum(value or 0 for value in values)


def combine_apply_results(results: Sequence[ApplyResult]) -> ApplyResult:
    """One ApplyResult for several applies: summed counts, first ignored/pending, concatenated failures and output."""
    if not results:
        return ApplyResult(0, 0, 0, 0, True, False, 0, [], [], "")
    first = results[0]
    return ApplyResult(
        added=_total([result.added for result in results]),
        changed=_total([result.changed for result in results]),
        deleted=_total([result.deleted for result in results]),
        ignored=first.ignored,
        no_changes=all(result.no_changes for result in results),
        aborted_validation=any(result.aborted_validation for result in results),
        pending_deletions=first.pending_deletions,
        failed_patches=[patch for result in results for patch in result.failed_patches],
        messages=[message for result in results for message in result.messages],
        raw="\n".join(result.raw for result in results),
    )


def noop_apply(plan: PlanResult, *, delete: bool) -> ApplyResult:
    """What ``apply`` reports for a plan with nothing to apply (``No changes required.``), without running it."""
    pending = 0 if delete else (plan.delete or 0)
    return ApplyResult(0, 0, 0, pending, True, False, pending, [], list(plan.messages), plan.raw)


def nothing_to_apply(plan: PlanResult, *, delete: bool) -> bool:
    """True when apply would print ``No changes required.``: 0 to add, 0 to change (and 0 to delete with -d)."""
    return plan.add == 0 and plan.change == 0 and (not delete or plan.delete == 0)


class BaselineManager:
    """Owns the baseline config of a run and every destructive apply."""

    def __init__(
        self,
        *,
        reset_cli: OtterdogCli,
        renderer: OrgConfigRenderer,
        target: Target,
        run_ctx: RunContext,
        oracle: Oracle,
        purgeable: Callable[[str], bool],
        protected_repos: Sequence[str],
    ) -> None:
        """Bind the trusted reset CLI and the renderer of the baseline."""
        self.reset_cli = reset_cli
        self.renderer = renderer
        self.target = target
        self.run_ctx = run_ctx
        self.oracle = oracle
        self.purgeable = purgeable
        self.protected_repos = tuple(protected_repos)
        self._guard_cli: OtterdogCli | None = None
        self._web_snapshot: dict[str, Any] | None = None
        self._web_restored = True
        # precondition of every apply (E2EContext.check_lease_not_lost: refused once the org lease was lost, DESTR-03)
        self.write_check: Callable[[], None] | None = None
        # the last removal of this run's objects (apply -d -r e2e-<run>-*) failed: they may still exist (BAT-06)
        self.run_objects_left = False

    @property
    def baseline_repos(self) -> tuple[str, ...]:
        """Repositories the baseline declares: run config repo, configs repo, defaults repo, fixture repos."""
        target = self.target
        names = (target.config_repo_for(self.run_ctx), target.configs_repo, target.defaults_repo, *target.fixture_repos)
        return tuple(dict.fromkeys(names))

    @property
    def baseline_teams(self) -> tuple[str, ...]:
        """Teams the baseline declares: admin, approval and contributors teams."""
        target = self.target
        return tuple(dict.fromkeys((target.admin_team, target.approval_team, target.contributors_team)))

    def text(self) -> str:
        """The rendered baseline config (no scenario fragments)."""
        return self.renderer.render()

    # --- guard ------------------------------------------------------------------------------------------------------
    def guard_problems(self, plan: PlanResult, *, delete: bool = True) -> list[str]:
        """Reasons why applying ``plan`` is unsafe (empty when safe); removal rules apply only with ``delete``."""
        problems: list[str] = []
        if plan.aborted or plan.add is None or plan.delete is None:
            problems.append("the plan did not complete (no 'Plan:' summary): it cannot be verified")
        problems += [f"{obj.header}: changes the org description" for obj in plan.objects if _touches_description(obj)]
        if not delete:
            return problems
        removals = plan.removals()
        if plan.delete is not None and plan.delete != len(removals):
            problems.append(f"'Plan:' announces {plan.delete} deletion(s) but {len(removals)} '- remove' header(s)")
        problems += [f"{obj.header}: {why}" for obj in removals if (why := self._removal_problem(obj))]
        return problems

    def _removal_problem(self, obj: PlanObject) -> str | None:
        """Why one REMOVE is refused (protected object, no run id, run not purgeable), None when allowed."""
        protected = {name.lower() for name in self.protected_repos}
        if obj.kind == "repository" and obj.value.lower() in protected:
            return "protected repository"
        if obj.kind == "team" and obj.value.lower() in {name.lower() for name in self.baseline_teams}:
            return "baseline team"
        run_id = obj.run_id
        if run_id is None:
            return "carries no e2e run id"
        if not self.purgeable(run_id):
            return f"run {run_id} is not purgeable"
        return None

    def check_changes(self, plan: PlanResult) -> None:
        """SafetyError when the plan changes an object that carries no run id and that the baseline does not declare
        (an extra protected or unmanaged repository and its nested objects, a non-baseline team, an org-level object
        named by hand): the baseline reset can never restore it (DESTR-07). The org ``settings`` are allowed."""
        problems = unmanaged_changes(plan, repos=self.baseline_repos, teams=self.baseline_teams)
        if problems:
            raise SafetyError(
                "refusing an apply that changes objects the baseline reset can never restore (no run id, not declared "
                "by the baseline): " + "; ".join(problems[:10])
            )

    def check_removals(self, plan: PlanResult) -> None:
        """SafetyError unless every REMOVE carries a purgeable run id and names no protected object, the delete count
        equals the number of remove headers, and no ``~ settings`` object touches the description."""
        problems = self.guard_problems(plan, delete=True)
        if problems:
            raise SafetyError("refusing destructive otterdog apply:\n  " + "\n  ".join(problems))

    def guarded_apply(self, cli: OtterdogCli, *, repo_filter: str | None, delete: bool) -> ApplyResult:
        """Plan with the same filter -> check_removals -> apply (``-d`` when delete). A removal of this run's objects
        (``-d -r e2e-<run>-*``: scenario cleanups, Python fixtures, resets) records in ``run_objects_left`` whether it
        failed, so the next scenario removes the leftovers first instead of tripping over them (BAT-06)."""
        run_cleanup = delete and repo_filter == self.run_ctx.repo_filter()
        try:
            result = self._guarded(cli, repo_filter=repo_filter, delete=delete)[1]
        except BaseException:
            if run_cleanup:
                self.run_objects_left = True
            raise
        if run_cleanup:
            self.run_objects_left = bool(result.failed_patches or result.aborted_validation)
        return result

    def _guarded(self, cli: OtterdogCli, *, repo_filter: str | None, delete: bool) -> tuple[PlanResult, ApplyResult]:
        """guarded_apply returning the verified plan too; apply is skipped when the plan has nothing to apply."""
        if self.write_check is not None:
            self.write_check()
        planned = cli.plan(repo_filter=repo_filter)
        _raise_infra(planned, "plan (apply guard)")
        plan = planned.plan()
        problems = self.guard_problems(plan, delete=delete)
        if problems:
            details = "\n  ".join(problems)
            raise SafetyError(f"refusing otterdog apply (-r {repo_filter or '*'}):\n  {details}\n{_tail(plan.raw)}")
        if nothing_to_apply(plan, delete=delete):
            return plan, noop_apply(plan, delete=delete)
        applied = cli.apply(repo_filter=repo_filter, delete=delete)
        _raise_infra(applied, "apply (guarded)")
        result = applied.apply()
        if applied.exit_code != 0 or result.failed_patches:
            log.warning(
                "guarded apply (-r %s) exit %s, failed patches: %s",
                repo_filter,
                applied.exit_code,
                result.failed_patches,
            )
        return plan, result

    def guard_config_change(self, base_text: str, head_text: str, *, allow_invalid_head: bool = True) -> PlanResult:
        """SafetyError unless merging ``head_text`` over ``base_text`` only removes purgeable, unprotected objects.

        The one config guard (SEC-07) of ConfigRepoFlow (``guard=baseline.guard_config_change``): the webapp applies
        merged config PRs with delete_resources=True. ``local-plan`` base -> head runs with the trusted reset CLI in
        its own guard workspace (``--local`` once the template is vendored there), then every removal goes through
        check_removals (fail closed). An empty base is the baseline (~ the live org). With ``allow_invalid_head`` a
        head that explicitly fails to load or validate (for THIS trusted CLI) is accepted: W-PR-INVALID pushes such
        texts on purpose. ConfigRepoFlow passes it for pushes, and for approvals, merges and /otterdog merge|apply only
        when the SUT itself reports the PR invalid (the SUT, possibly newer, decides what it applies: DESTR-04). A
        timeout, an infra error, a base that cannot be loaded or any other failed local-plan is refused. Returns the
        plan.
        """
        cli = self.guard_cli()
        workspace = cli.workspace
        workspace.write_base_config(base_text or self.text())
        workspace.write_org_config(head_text)
        result = cli.local_plan(local=_template_vendored(workspace))
        if result.timed_out or result.infra_error:
            reason = result.infra_error or "timed out"
            raise SafetyError(f"config guard: local-plan incomplete ({reason}), refusing the change")
        plan = result.plan()
        if allow_invalid_head and _invalid_head(plan):
            log.info("config guard: the head config is invalid, the webapp cannot apply it (accepted)")
            return plan
        if result.exit_code != 0:
            raise SafetyError(
                f"config guard: local-plan failed (exit {result.exit_code}), refusing the change:\n{_tail(plan.raw)}"
            )
        self.check_removals(plan)
        return plan

    def guard_cli(self) -> OtterdogCli:
        """The reset SUT's OtterdogCli bound to its own guard workspace (created once; artifacts under ``guard/``)."""
        if self._guard_cli is None:
            reset = self.reset_cli
            source = reset.workspace
            workspace = ConfigWorkspace(
                reset.scratch / GUARD_WORKSPACE,
                org=source.org,
                template=source.template,
                config_repo=source.config_repo,
                project=source.project,
                base_url=source.base_url,
            )
            workspace.write_otterdog_json()
            self._guard_cli = OtterdogCli(
                reset.installed,
                workspace,
                verified=reset.verified,
                identity=reset.identity,
                scratch=reset.scratch,
                artifacts_dir=reset.artifacts_dir / GUARD_ARTIFACTS,
                settings=reset.settings,
                timeout=reset.timeout,
                offline=reset.offline,
                http_cache=reset.http_cache,
                http_cache_root=getattr(reset, "http_cache_root", None),
            )
            self._guard_cli.live_check = getattr(reset, "live_check", None)
        return self._guard_cli

    # --- reset ------------------------------------------------------------------------------------------------------
    def reset(self) -> ApplyResult:
        """Bring the org back to the baseline (SPEC 11.5 steps 1-6) with the trusted reset CLI."""
        cli = self.reset_cli
        if not cli.workspace.config_file.exists():
            cli.workspace.write_otterdog_json()
        cli.workspace.write_org_config(self.text())
        plan, applied = self._guarded(cli, repo_filter=None, delete=False)
        results = [applied]
        for run_id in self._leftover_runs(plan):
            results.append(self.guarded_apply(cli, repo_filter=f"e2e-{run_id}-*", delete=True))
        for repo in self.baseline_repos:
            results.append(self.guarded_apply(cli, repo_filter=repo, delete=True))
        self._check_in_sync()
        self._check_live_baseline()
        combined = combine_apply_results(results)
        if combined.failed_patches:
            log.warning("baseline reset: failed patches %s", combined.failed_patches)
        return combined

    def _leftover_runs(self, plan: PlanResult) -> list[str]:
        """Purgeable run ids owning live objects the baseline does not declare (sorted)."""
        run_ids = {obj.run_id for obj in plan.removals() if obj.run_id is not None}
        refused = sorted(run_id for run_id in run_ids if not self.purgeable(run_id))
        if refused:
            log.warning("baseline reset: objects of non-purgeable runs %s are left in place", refused)
        return sorted(run_id for run_id in run_ids if self.purgeable(run_id))

    def _check_in_sync(self) -> None:
        """``check-status -n -j``: WARN with the remaining plan objects unless in_sync."""
        cli = self.reset_cli
        result, entry = cli.check_status(cli.workspace.root / CHECK_STATUS_JSON)
        sync = (entry or {}).get("sync_status") or {}
        if sync.get("in_sync") is True:
            return
        remaining = [obj.header for obj in cli.plan().plan().objects if not obj.is_read_only]
        log.warning(
            "baseline reset: org not in sync (check-status exit %s, status %s); remaining plan objects: %s",
            result.exit_code,
            entry,
            remaining,
        )

    def _check_live_baseline(self) -> None:
        """Oracle: every baseline repo and team exists and the org description still holds the marker."""
        problems = [f"repository {repo!r} is missing" for repo in self.baseline_repos if self.oracle.repo(repo) is None]
        problems += [f"team {team!r} is missing" for team in self.baseline_teams if self.oracle.team(team) is None]
        description = (self.oracle.org() or {}).get("description") or ""
        if self.target.marker not in description:
            problems.append(f"org description {description!r} lost the safety marker {self.target.marker!r}")
        if problems:
            raise SafetyError("baseline reset left the org in an unexpected state: " + "; ".join(problems))

    def push(self, flow: ConfigRepoFlow) -> str:
        """Write the baseline to the org config repo's main branch via ``flow``; returns the commit sha."""
        return flow.reset_main(self.text(), message=f"otterdog-e2e: baseline of run {self.run_ctx.run_id}")

    # --- web-only settings (docs/web-ui-testing.md) -----------------------------------------------------------------
    @property
    def web_snapshot(self) -> dict[str, Any] | None:
        """The original web-only settings recorded by the web-UI tier (None before it changed anything)."""
        return dict(self._web_snapshot) if self._web_snapshot is not None else None

    @property
    def web_restore_pending(self) -> bool:
        """True while recorded web settings may differ from the live org (no verified restore since)."""
        return self._web_snapshot is not None and not self._web_restored

    def record_web_settings(self, values: Mapping[str, Any]) -> None:
        """Remember the ORIGINAL web-only settings before the web-UI tier changes them (the first record wins: later
        snapshots may already see changed values) and mark a restore as pending."""
        from otterdog_e2e.webui.mapping import WRITABLE

        if self._web_snapshot is None:
            self._web_snapshot = {key: values[key] for key in WRITABLE if key in values}
        self._web_restored = False

    def mark_web_restored(self) -> None:
        """The web-UI tier verified that the live org has the recorded values again."""
        self._web_restored = True

    def web_settings_text(self, values: Mapping[str, Any]) -> str:
        """The baseline with ``key::: <value>`` pinning each writable web setting of ``values`` (scenario layer)."""
        from otterdog_e2e.webui.mapping import jsonnet_fields

        return self.renderer.render(ConfigFragments(settings=jsonnet_fields(values)))

    def restore_web_settings(self, cli: OtterdogCli, values: Mapping[str, Any] | None = None) -> ApplyResult:
        """Restore web-only settings (default: the recorded snapshot) with a TRUSTED web-mode CLI: guarded plan and
        apply (no ``-d``) of the baseline with the values pinned; the pending flag is cleared when the apply
        succeeded (the caller verifies the live values). SafetyError for a CLI without web mode or untrusted."""
        target = dict(values) if values is not None else self.web_snapshot
        if not target:
            return combine_apply_results([])
        if cli.web is None:
            raise SafetyError("restoring web-only settings needs a web-mode CLI (otterdog without -n)")
        if not cli.installed.sut.trusted:
            raise SafetyError(f"web-only settings are restored by a trusted otterdog, not by {cli.installed.sut.label}")
        cli.workspace.write_org_config(self.web_settings_text(target))
        planned = cli.plan()
        _raise_infra(planned, "plan (web settings restore)")
        plan = planned.plan()
        problems = self.guard_problems(plan, delete=False)
        if problems:
            raise SafetyError("refusing the web settings restore:\n  " + "\n  ".join(problems) + f"\n{_tail(plan.raw)}")
        if nothing_to_apply(plan, delete=False):
            applied, exit_code = noop_apply(plan, delete=False), planned.exit_code
        else:
            result = cli.apply()
            _raise_infra(result, "apply (web settings restore)")
            applied, exit_code = result.apply(), result.exit_code
        if exit_code != 0 or applied.failed_patches or applied.aborted_validation:
            log.error(
                "restoring the web-only settings failed (exit %s): %s",
                exit_code,
                applied.failed_patches or ("validation aborted" if applied.aborted_validation else "see the output"),
            )
        elif target == self._web_snapshot:
            self._web_restored = True
        return applied


def unmanaged_changes(plan: PlanResult, *, repos: Collection[str], teams: Collection[str]) -> list[str]:
    """Headers of the changed (or force-updated) objects without a run id that are neither the org ``settings``, nor a
    repository of ``repos`` (or an object nested in one), nor a team of ``teams``: changes the baseline reset never
    restores (DESTR-07)."""
    found = []
    for obj in plan.objects:
        if obj.op not in ("change", "forced") or obj.is_read_only or obj.run_id is not None or obj.kind == "settings":
            continue
        if obj.kind == "repository":
            repo: str | None = obj.value
        elif obj.parent_kind == "repository":
            repo = obj.parent
        else:
            match = _HEADER_REPO_RE.search(obj.header)
            repo = match.group("repo") if match else None
        if (repo is not None and repo in repos) or (repo is None and obj.kind == "team" and obj.value in teams):
            continue
        found.append(obj.header.strip().removesuffix("{").rstrip())
    return found


def _invalid_head(plan: PlanResult) -> bool:
    """True when local-plan reports that the HEAD config explicitly failed to load or validate.

    A BASE that cannot be loaded ("failed to load current configuration") parses as a passed validation, so it is
    never mistaken for an invalid head.
    """
    validation = plan.validation
    return validation is not None and not validation.ok and bool(validation.load_error or validation.errors)


def _template_vendored(workspace: ConfigWorkspace) -> bool:
    """True when otterdog already vendored the workspace's template (``orgs/<org>/vendor/<repo>/<file>``)."""
    return (workspace.org_dir / workspace.template.import_path).is_file()


def _touches_description(obj: PlanObject) -> bool:
    """True for a settings change/forced update whose changed keys include the org description."""
    return obj.kind == "settings" and obj.op in ("change", "forced") and "description" in obj.changed_keys


def _raise_infra(result: CliResult, what: str) -> None:
    """AssertionError (redacted tail) when the command timed out or hit a GitHub rate limit/connection error."""
    if result.timed_out or result.infra_error:
        result.assert_ok(what)
