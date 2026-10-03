"""Sweeps leftovers of crashed or cancelled runs (SPEC 9.5).

``purgeable(run_id)`` = run id in the ledger AND not the run id of an unexpired lease holder (the current session's own
run id is purgeable for itself); OrgLease.purgeable_fn() builds it. Listings answering 403/404 are logged and skipped,
never errors; other listing errors are logged in ``scan_errors`` and the scan goes on. Protected repositories are never
deleted: only run-named objects inside them are. A ledger tag is swept only once no other object of its run is left
(otherwise the run would no longer be purgeable), template tags only when no unexpired lease references them.

Battery probes leave other run objects too: e2e-named code security configurations are swept (a default of one is set
to ``none`` first, GitHub refuses to delete a default); security advisories cannot be deleted through the API, but the
Mutator only creates them in run repositories, whose deletion removes them, and their temporary private forks
(``<run repo>-ghsa-...``) carry the run prefix, so the repository sweep deletes them.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from otterdog_e2e import naming
from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.github.lease import LEDGER_PREFIX, parse_time, record_expired
from otterdog_e2e.safety import SafetyError

if TYPE_CHECKING:
    from otterdog_e2e.github.lease import OrgLease
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle

logger = logging.getLogger(__name__)

TEMPLATE_TAG_MAX_AGE_DAYS = 14
LEDGER_TAG_MAX_AGE_DAYS = 30
TEMPLATE_TAG_PREFIX = "tags/sut-"
BRANCH_PREFIXES = ("heads/e2e/", "heads/otterdog/e2e-")
JANITOR_KINDS = (
    "repo",
    "team",
    "org_secret",
    "org_variable",
    "org_ruleset",
    "custom_property",
    "org_hook",
    "org_role",
    "code_security_configuration",
    "repo_hook",
    "repo_ruleset",
    "bpr",
    "environment",
    "repo_secret",
    "repo_variable",
    "pull_request",
    "branch",
    "config_repo",
    "template_tag",
    "ledger_tag",
)
# deletion order: PRs before their branches, objects inside repos before org objects, repos late, the ledger last
SWEEP_ORDER = (
    "pull_request",
    "branch",
    "repo_hook",
    "repo_ruleset",
    "bpr",
    "environment",
    "repo_secret",
    "repo_variable",
    "org_hook",
    "org_ruleset",
    "org_secret",
    "org_variable",
    "custom_property",
    "org_role",
    "code_security_configuration",
    "team",
    "repo",
    "config_repo",
    "template_tag",
    "ledger_tag",
)


@dataclass(frozen=True)
class JanitorItem:
    """One leftover object: kind (JANITOR_KINDS), name, owning run id, scope (e.g. repo) and detail (e.g. id)."""

    kind: str
    name: str
    run_id: str | None
    scope: str = ""
    detail: str = ""


class Janitor:
    """Finds and deletes objects of purgeable runs; never touches protected or non-e2e objects."""

    def __init__(
        self,
        oracle: Oracle,
        mutator: Mutator,
        *,
        lease: OrgLease,
        configs_repo: str,
        defaults_repo: str | None,
        protected_repos: Sequence[str],
        purgeable: Callable[[str], bool],
    ) -> None:
        """Bind the oracle/mutator; the lease must be held by the caller."""
        self.oracle = oracle
        self.mutator = mutator
        self.lease = lease
        self.configs_repo = configs_repo
        self.defaults_repo = defaults_repo
        self.protected_repos = tuple(protected_repos)
        self.purgeable = purgeable
        self.clock: Callable[[], datetime] = lambda: datetime.now(UTC)
        self.scan_errors: list[str] = []
        self.failures: list[tuple[JanitorItem, str]] = []

    # --- scan ---------------------------------------------------------------------------------------------------
    def scan(self) -> list[JanitorItem]:
        """List purgeable leftovers (org objects, objects inside protected repos, PRs/branches, config repos, tags)."""
        self.scan_errors = []
        items: list[JanitorItem] = []
        sections: list[tuple[str, Callable[[], list[JanitorItem]]]] = [
            ("repositories", self._scan_repos),
            ("teams", lambda: self._named("team", self.oracle.teams(), key="slug")),
            ("org secrets", lambda: self._named("org_secret", self.oracle.org_secrets())),
            ("org variables", lambda: self._named("org_variable", self.oracle.org_variables())),
            ("org rulesets", lambda: self._named("org_ruleset", self.oracle.org_rulesets(), detail="id")),
            (
                "custom properties",
                lambda: self._named("custom_property", self.oracle.custom_properties(), key="property_name"),
            ),
            ("org hooks", lambda: self._hooks("org_hook", self.oracle.org_hooks())),
            ("org roles", lambda: self._named("org_role", self.oracle.org_roles(), detail="id")),
            (
                "code security configurations",
                lambda: self._named(
                    "code_security_configuration", self.oracle.code_security_configurations(), detail="id"
                ),
            ),
        ]
        for label, section in sections:
            items.extend(self._run(label, section))
        for repo in self._protected():
            items.extend(self._scan_protected_repo(repo))
        items.extend(self._run("template tags", self._scan_template_tags))
        items.extend(self._run("ledger", lambda: self._scan_ledger(items)))
        for (kind, scope), status in sorted(self.oracle.unavailable.items()):
            logger.info("janitor: %s(%s) unavailable (HTTP %s), skipped", kind, scope, status)
        logger.info("janitor: %d purgeable object(s) found", len(items))
        return items

    def _run(self, label: str, section: Callable[[], list[JanitorItem]]) -> list[JanitorItem]:
        """Run one scan section; 403/404 are skipped, other GitHub errors are logged in scan_errors."""
        try:
            return section()
        except GitHubError as exc:
            self._scan_error(label, exc)
            return []

    def _scan_error(self, label: str, exc: GitHubError) -> None:
        """Log a failed listing: 403/404 are skipped quietly, other errors are kept in scan_errors."""
        if exc.status in (403, 404):
            logger.info("janitor: %s unavailable (HTTP %s), skipped", label, exc.status)
        else:
            logger.warning("janitor: scanning %s failed: %s", label, exc)
            self.scan_errors.append(f"{label}: {exc}")

    def _protected(self) -> list[str]:
        """Protected repositories (configs and defaults repos included), sorted."""
        names = set(self.protected_repos) | {self.configs_repo}
        if self.defaults_repo:
            names.add(self.defaults_repo)
        return sorted(names)

    def _run_id(self, name: Any) -> str | None:
        """Run id of an e2e name when that run is purgeable, else None."""
        if not isinstance(name, str) or not naming.is_e2e_name(name):
            return None
        run_id = naming.extract_run_id(name)
        return run_id if run_id is not None and self.purgeable(run_id) else None

    def _named(
        self, kind: str, entries: Iterable[Any], *, key: str = "name", scope: str = "", detail: str | None = None
    ) -> list[JanitorItem]:
        """Items for entries whose ``key`` is an e2e name of a purgeable run."""
        items = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            run_id = self._run_id(entry.get(key))
            if run_id is not None:
                info = str(entry.get(detail, "")) if detail else ""
                items.append(JanitorItem(kind, str(entry[key]), run_id, scope, info))
        return items

    def _hooks(self, kind: str, hooks: Iterable[Any], scope: str = "") -> list[JanitorItem]:
        """Items for hooks whose config.url is under HOOK_BASE and carries a purgeable run id."""
        items = []
        for hook in hooks:
            url = str(((hook or {}).get("config") or {}).get("url") or "") if isinstance(hook, dict) else ""
            run_id = naming.extract_run_id(url) if url.startswith(naming.HOOK_BASE) else None
            if run_id is not None and self.purgeable(run_id):
                items.append(JanitorItem(kind, url, run_id, scope, str(hook.get("id", ""))))
        return items

    def _scan_repos(self) -> list[JanitorItem]:
        """Run repositories and per-session config repos (``e2e-<id>-config``) of purgeable runs."""
        protected = set(self._protected())
        items = []
        for repo in self.oracle.repos():
            name = repo.get("name") if isinstance(repo, dict) else None
            run_id = self._run_id(name)
            if run_id is None or name in protected:
                continue
            kind = "config_repo" if name == f"e2e-{run_id}-config" else "repo"
            items.append(JanitorItem(kind, str(name), run_id))
        return items

    def _scan_protected_repo(self, repo: str) -> list[JanitorItem]:
        """Run-named hooks, rulesets, BPRs, environments, secrets, variables, open PRs and branches of a protected repo."""
        if not self._exists(repo):
            return []
        sections: list[tuple[str, Callable[[], list[JanitorItem]]]] = [
            ("hooks", lambda: self._hooks("repo_hook", self.oracle.repo_hooks(repo), repo)),
            ("rulesets", lambda: self._named("repo_ruleset", self.oracle.repo_rulesets(repo), scope=repo, detail="id")),
            ("branch protection rules", lambda: self._bprs(repo)),
            ("environments", lambda: self._named("environment", self.oracle.environments(repo), scope=repo)),
            ("secrets", lambda: self._named("repo_secret", self.oracle.repo_secrets(repo), scope=repo)),
            ("variables", lambda: self._named("repo_variable", self.oracle.repo_variables(repo), scope=repo)),
            ("pull requests", lambda: self._pulls(repo)),
            ("branches", lambda: self._branches(repo)),
        ]
        items = []
        for label, section in sections:
            items.extend(self._run(f"{repo} {label}", section))
        return items

    def _exists(self, repo: str) -> bool:
        """True when the repository exists (lookup errors are logged like listing errors)."""
        try:
            return self.oracle.repo(repo) is not None
        except GitHubError as exc:
            self._scan_error(f"repository {repo}", exc)
            return False

    def _bprs(self, repo: str) -> list[JanitorItem]:
        """Branch protection rules whose pattern carries a purgeable run id."""
        items = []
        for rule in self.oracle.branch_protection_rules(repo):
            pattern = str(rule.get("pattern") or "")
            run_id = naming.extract_run_id(pattern)
            if run_id is not None and self.purgeable(run_id) and rule.get("id"):
                items.append(JanitorItem("bpr", pattern, run_id, repo, str(rule["id"])))
        return items

    def _pulls(self, repo: str) -> list[JanitorItem]:
        """Open same-repo PRs whose head branch is ``e2e/<id>/…`` or ``otterdog/e2e-<id>…`` of a purgeable run."""
        items = []
        full_name = f"{self.oracle.org_login}/{repo}".lower()
        for pull in self.oracle.pulls(repo, "open"):
            head = pull.get("head") or {}
            ref = str(head.get("ref") or "")
            head_repo = str(((head.get("repo") or {}).get("full_name")) or full_name).lower()
            run_id = naming.extract_run_id(ref) if naming.is_deletable_ref(f"heads/{ref}") else None
            if run_id is not None and head_repo == full_name and self.purgeable(run_id):
                items.append(JanitorItem("pull_request", ref, run_id, repo, str(pull.get("number", ""))))
        return items

    def _branches(self, repo: str) -> list[JanitorItem]:
        """Branches ``e2e/<id>/…`` and ``otterdog/e2e-<id>…`` of purgeable runs (one matching-refs call each)."""
        items = []
        for prefix in BRANCH_PREFIXES:
            for ref in self.oracle.matching_refs(repo, prefix):
                short = str(ref.get("ref", "")).removeprefix("refs/")
                run_id = naming.extract_run_id(short) if naming.is_deletable_ref(short) else None
                if run_id is not None and self.purgeable(run_id):
                    items.append(
                        JanitorItem("branch", short, run_id, repo, str((ref.get("object") or {}).get("sha", "")))
                    )
        return items

    def _lease_refs(self) -> set[str]:
        """Refs referenced by an unexpired lease (the holder record's ``refs``, plus this session's own)."""
        refs = {ref.removeprefix("refs/") for ref in getattr(self.lease, "refs", [])}
        record = self.lease.holder_record()
        if record is not None and not record_expired(record, self.clock()):
            refs |= {str(ref).removeprefix("refs/") for ref in record.get("refs") or []}
        return refs

    def _scan_template_tags(self) -> list[JanitorItem]:
        """Template tags ``sut-*`` of the defaults repo older than 14 days and not referenced by an unexpired lease."""
        if not self.defaults_repo:
            return []
        referenced = self._lease_refs()
        cutoff = self.clock() - timedelta(days=TEMPLATE_TAG_MAX_AGE_DAYS)
        items = []
        for ref in self.oracle.matching_refs(self.defaults_repo, TEMPLATE_TAG_PREFIX):
            short = str(ref.get("ref", "")).removeprefix("refs/")
            target = ref.get("object") or {}
            if short in referenced or target.get("type") != "commit" or not naming.is_deletable_ref(short):
                continue
            commit = self.oracle.git_commit(self.defaults_repo, str(target.get("sha"))) or {}
            committed = parse_time((commit.get("committer") or {}).get("date"))
            if committed is not None and committed < cutoff:
                items.append(JanitorItem("template_tag", short, None, self.defaults_repo, str(target.get("sha"))))
        return items

    def _scan_ledger(self, found: Sequence[JanitorItem]) -> list[JanitorItem]:
        """Ledger tags older than 30 days of purgeable runs that have no other leftover object."""
        busy = {item.run_id for item in found if item.run_id}
        cutoff = self.clock() - timedelta(days=LEDGER_TAG_MAX_AGE_DAYS)
        repo = getattr(self.lease, "repo", self.configs_repo)
        items = []
        for run_id in self.lease.ledger():
            created = naming.run_id_timestamp(run_id)
            if created is None or created >= cutoff or run_id in busy or not self.purgeable(run_id):
                continue
            items.append(JanitorItem("ledger_tag", f"{LEDGER_PREFIX}{run_id}", run_id, repo))
        return items

    # --- sweep --------------------------------------------------------------------------------------------------
    def sweep(self, items: Iterable[JanitorItem] | None = None) -> list[JanitorItem]:
        """Delete ``items`` (default: scan()); returns the items actually deleted."""
        todo = self.scan() if items is None else list(items)
        if not self.mutator.dry_run and not self.lease.held:
            raise SafetyError("the janitor sweeps only while holding the org lease")
        self.failures = []
        deleted: list[JanitorItem] = []
        for item in sorted(todo, key=self._order):
            try:
                self._delete(item)
            except SafetyError as exc:
                logger.error("janitor: refused to delete %s %r: %s", item.kind, item.name, exc)
                self.failures.append((item, str(exc)))
                continue
            except GitHubError as exc:
                if exc.status in (403, 404):
                    logger.info("janitor: %s %r not deletable (HTTP %s), skipped", item.kind, item.name, exc.status)
                else:
                    logger.warning("janitor: deleting %s %r failed: %s", item.kind, item.name, exc)
                    self.failures.append((item, str(exc)))
                continue
            deleted.append(item)
        logger.info("janitor: deleted %d of %d object(s)", len(deleted), len(todo))
        return deleted

    @staticmethod
    def _order(item: JanitorItem) -> tuple[int, str, str]:
        """Sort key following SWEEP_ORDER."""
        rank = SWEEP_ORDER.index(item.kind) if item.kind in SWEEP_ORDER else len(SWEEP_ORDER)
        return rank, item.scope, item.name

    def _delete(self, item: JanitorItem) -> None:
        """Dispatch one item to its guarded Mutator call."""
        m, scope, name = self.mutator, item.scope, item.name
        actions: dict[str, Callable[[], None]] = {
            "repo": lambda: m.delete_repo(name),
            "config_repo": lambda: m.delete_repo(name),
            "team": lambda: m.delete_team(name),
            "org_secret": lambda: m.delete_org_secret(name),
            "org_variable": lambda: m.delete_org_variable(name),
            "org_ruleset": lambda: m.delete_org_ruleset(int(item.detail), name=name),
            "custom_property": lambda: m.delete_custom_property(name),
            "org_hook": lambda: m.delete_org_hook(int(item.detail)),
            "org_role": lambda: m.delete_org_role(int(item.detail), name=name),
            "code_security_configuration": lambda: self._delete_code_security_configuration(item),
            "repo_hook": lambda: m.delete_repo_hook(scope, int(item.detail)),
            "repo_ruleset": lambda: m.delete_repo_ruleset(scope, int(item.detail), name=name),
            "bpr": lambda: m.delete_branch_protection_rule(scope, item.detail, pattern=name),
            "environment": lambda: m.delete_environment(scope, name),
            "repo_secret": lambda: m.delete_repo_secret(scope, name),
            "repo_variable": lambda: m.delete_repo_variable(scope, name),
            "pull_request": lambda: m.close_pull(scope, int(item.detail)),
            "branch": lambda: m.delete_ref(scope, name),
            "template_tag": lambda: m.delete_ref(scope, name),
            "ledger_tag": lambda: m.delete_ref(scope, name),
        }
        action = actions.get(item.kind)
        if action is None:
            raise SafetyError(f"unknown janitor item kind {item.kind!r}")
        logger.info("janitor: deleting %s %r%s", item.kind, name, f" in {scope}" if scope else "")
        action()

    def _delete_code_security_configuration(self, item: JanitorItem) -> None:
        """Set a default code security configuration back to ``none`` (a default cannot be deleted), then delete it
        (both guarded: e2e name matching the live configuration)."""
        configuration_id = int(item.detail)
        defaults = self.oracle.code_security_default_configurations()
        if any((entry.get("configuration") or {}).get("id") == configuration_id for entry in defaults):
            self.mutator.set_code_security_default(configuration_id, name=item.name, default_for_new_repos="none")
        self.mutator.delete_code_security_configuration(configuration_id, name=item.name)
