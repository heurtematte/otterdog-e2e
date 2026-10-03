"""Janitor: classification of leftovers, tolerance to unavailable listings and guarded sweeping (SPEC 9.5)."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import responses

from otterdog_e2e.github.http import GITHUB_API, GitHubError, GitHubHttp
from otterdog_e2e.github.janitor import JANITOR_KINDS, SWEEP_ORDER, Janitor, JanitorItem
from otterdog_e2e.github.lease import format_time
from otterdog_e2e.github.mutate import Mutator
from otterdog_e2e.naming import HOOK_BASE
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FAKE_ORG, FakeOracle, RecordingMutator, fake_sha, make_verified_org

NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
CONFIGS, DEFAULTS, FIXTURE = "otterdog-e2e-configs", "otterdog-e2e-defaults", "otterdog-e2e-fixture-a"
_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def run_id(when: datetime, suffix: str = "aa") -> str:
    """A run id created at ``when``."""
    value, digits = int(when.timestamp()), ""
    while value:
        value, rest = divmod(value, 36)
        digits = _B36[rest] + digits
    return digits.rjust(6, "0") + suffix


OLD = run_id(NOW - timedelta(hours=8))  # crashed run, in the ledger
ACTIVE = run_id(NOW - timedelta(hours=1), "bb")  # unexpired foreign holder
OWN = run_id(NOW, "cc")  # this session
UNKNOWN = run_id(NOW - timedelta(hours=5), "dd")  # never registered in the ledger
ANCIENT = run_id(NOW - timedelta(days=40), "ee")  # ledger tag only
ANCIENT_BUSY = run_id(NOW - timedelta(days=40), "ff")  # ledger tag + a leftover team
LEDGER = {OLD, ACTIVE, OWN, ANCIENT, ANCIENT_BUSY}


def purgeable(rid: str) -> bool:
    """SPEC 9.5 predicate for the scenario above."""
    return rid in LEDGER and rid != ACTIVE


class GitFakeOracle(FakeOracle):
    """FakeOracle with the git lookups the janitor and the lease use."""

    def matching_refs(self, repo: str, prefix: str) -> list[dict[str, Any]]:
        """Stored refs of ``repo`` starting with refs/<prefix>."""
        return [ref for ref in self._list("matching_refs", repo) if ref["ref"].startswith(f"refs/{prefix}")]

    def git_commit(self, repo: str, sha: str) -> dict[str, Any] | None:
        """Stored commit or None."""
        return self._values.get(("git_commit", (repo, sha)))


class JanitorRecordingMutator(RecordingMutator):
    """RecordingMutator with the janitor-only deletions."""

    def delete_org_role(self, role_id: int, *, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("org role", name)
        self._record("delete_org_role", role_id, name=name)

    def delete_repo_ruleset(self, repo: str, ruleset_id: int, *, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("repo ruleset", name)
        self._record("delete_repo_ruleset", repo, ruleset_id, name=name)

    def delete_branch_protection_rule(self, repo: str, rule_id: str, *, pattern: str) -> None:
        """Record."""
        self._record("delete_branch_protection_rule", repo, rule_id, pattern=pattern)

    def delete_environment(self, repo: str, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("environment", name)
        self._record("delete_environment", repo, name)

    def delete_repo_secret(self, repo: str, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("repo secret", name)
        self._record("delete_repo_secret", repo, name)

    def delete_repo_variable(self, repo: str, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("repo variable", name)
        self._record("delete_repo_variable", repo, name)


class StubLease:
    """The OrgLease surface used by the janitor."""

    def __init__(self, *, held: bool = True, refs: list[str] | None = None, record: dict | None = None) -> None:
        """Configure the lease state."""
        self.repo = CONFIGS
        self.held = held
        self.refs = refs or []
        self.record = record

    def holder_record(self) -> dict | None:
        """Current lease record."""
        return self.record

    def ledger(self) -> list[str]:
        """The scenario's ledger."""
        return sorted(LEDGER)


def ref(name: str, sha: str = "a" * 40, kind: str = "commit") -> dict[str, Any]:
    """A git ref."""
    return {"ref": name, "object": {"sha": sha, "type": kind}}


def build_oracle() -> GitFakeOracle:
    """An org with leftovers of every kind next to objects the janitor must keep."""
    oracle = GitFakeOracle()
    for name in (
        f"e2e-{OLD}-basic",
        f"e2e-{OLD}-config",
        f"e2e-{ACTIVE}-x",
        f"e2e-{UNKNOWN}-y",
        "random",
        CONFIGS,
        DEFAULTS,
        FIXTURE,
        f"e2e-{OWN}-config",
    ):
        oracle.add_repo(name)
    oracle.add_team(f"e2e-{OLD}-team")
    oracle.add_team(f"e2e-{ANCIENT_BUSY}-team")
    oracle.add_team("otterdog-admins")
    oracle.set("org_secrets", value=[{"name": f"E2E_{OLD.upper()}_TOKEN"}, {"name": "PROD_TOKEN"}])
    oracle.set("org_variables", value=[{"name": f"E2E_{OLD.upper()}_VAR"}, {"name": f"E2E_{ACTIVE.upper()}_VAR"}])
    oracle.set("org_rulesets", value=[{"id": 7, "name": f"e2e-{OLD}-rs"}, {"id": 8, "name": "protect-main"}])
    oracle.set("custom_properties", value=[{"property_name": f"e2e-{OLD}-prop"}, {"property_name": "tier"}])
    oracle.add_org_hook(f"{HOOK_BASE}{OLD}/org", id=11)
    oracle.add_org_hook("https://ci.example.org/hook", id=12)
    oracle.add_org_hook(f"{HOOK_BASE}{ACTIVE}/org", id=13)
    oracle.set("org_roles", value=[{"id": 21, "name": f"e2e-{OLD}-role"}, {"id": 22, "name": "all_repo_read"}])
    oracle.add_repo_hook(FIXTURE, f"{HOOK_BASE}{OLD}/repo", id=31)
    oracle.add_repo_hook(FIXTURE, "https://ci.example.org/repo", id=32)
    oracle.set("repo_rulesets", FIXTURE, value=[{"id": 41, "name": f"e2e-{OLD}-r"}, {"id": 42, "name": "main"}])
    oracle.set(
        "branch_protection_rules",
        FIXTURE,
        value=[{"id": "BPR_1", "pattern": f"e2e/{OLD}/*"}, {"id": "BPR_2", "pattern": "main"}],
    )
    oracle.set("environments", FIXTURE, value=[{"name": f"e2e-{OLD}-env"}, {"name": "github-pages"}])
    oracle.set("repo_secrets", FIXTURE, value=[{"name": f"E2E_{OLD.upper()}_S"}])
    oracle.set("repo_variables", FIXTURE, value=[{"name": f"E2E_{OLD.upper()}_V"}, {"name": "VERSION"}])
    repo_full = {"full_name": f"{FAKE_ORG}/{FIXTURE}"}
    oracle.add_pull(FIXTURE, {"number": 5, "head": {"ref": f"e2e/{OLD}/pr", "repo": repo_full}})
    oracle.add_pull(FIXTURE, {"number": 6, "head": {"ref": "feature", "repo": repo_full}})
    oracle.add_pull(FIXTURE, {"number": 7, "head": {"ref": f"e2e/{OLD}/fork", "repo": {"full_name": "someone/fork"}}})
    oracle.set(
        "matching_refs",
        FIXTURE,
        value=[
            ref(f"refs/heads/e2e/{OLD}/b"),
            ref(f"refs/heads/otterdog/e2e-{OLD}-c"),
            ref(f"refs/heads/e2e/{ACTIVE}/d"),
        ],
    )
    old_tag, new_tag, used_tag = fake_sha("old"), fake_sha("new"), fake_sha("used")
    oracle.set(
        "matching_refs",
        DEFAULTS,
        value=[
            ref("refs/tags/sut-v1.6.1-aaaa1111", old_tag),
            ref("refs/tags/sut-main-9bdeb75-bbbb2222", new_tag),
            ref("refs/tags/sut-pr792-d0d3b08-cccc3333", used_tag),
            ref("refs/tags/sut-annotated", fake_sha("annotated"), kind="tag"),
        ],
    )
    for sha, age in ((old_tag, 20), (new_tag, 5), (used_tag, 30)):
        oracle.set(
            "git_commit",
            DEFAULTS,
            sha,
            value={"sha": sha, "committer": {"date": format_time(NOW - timedelta(days=age))}},
        )
    return oracle


def make_janitor(oracle: GitFakeOracle, mutator: Any = None, lease: Any = None) -> Janitor:
    """A janitor over the scenario."""
    unexpired = {
        "run_id": OWN,
        "holder": "local",
        "expires_at": format_time(NOW + timedelta(hours=2)),
        "refs": ["tags/sut-pr792-d0d3b08-cccc3333"],
    }
    janitor = Janitor(
        oracle,  # type: ignore[arg-type]
        mutator or JanitorRecordingMutator(oracle=oracle),  # type: ignore[arg-type]
        lease=lease or StubLease(record=unexpired),  # type: ignore[arg-type]
        configs_repo=CONFIGS,
        defaults_repo=DEFAULTS,
        protected_repos=[f"e2e-{OWN}-config", CONFIGS, DEFAULTS, FIXTURE],
        purgeable=purgeable,
    )
    janitor.clock = lambda: NOW
    return janitor


EXPECTED = {
    JanitorItem("repo", f"e2e-{OLD}-basic", OLD),
    JanitorItem("config_repo", f"e2e-{OLD}-config", OLD),
    JanitorItem("team", f"e2e-{OLD}-team", OLD),
    JanitorItem("team", f"e2e-{ANCIENT_BUSY}-team", ANCIENT_BUSY),
    JanitorItem("org_secret", f"E2E_{OLD.upper()}_TOKEN", OLD),
    JanitorItem("org_variable", f"E2E_{OLD.upper()}_VAR", OLD),
    JanitorItem("org_ruleset", f"e2e-{OLD}-rs", OLD, "", "7"),
    JanitorItem("custom_property", f"e2e-{OLD}-prop", OLD),
    JanitorItem("org_hook", f"{HOOK_BASE}{OLD}/org", OLD, "", "11"),
    JanitorItem("org_role", f"e2e-{OLD}-role", OLD, "", "21"),
    JanitorItem("repo_hook", f"{HOOK_BASE}{OLD}/repo", OLD, FIXTURE, "31"),
    JanitorItem("repo_ruleset", f"e2e-{OLD}-r", OLD, FIXTURE, "41"),
    JanitorItem("bpr", f"e2e/{OLD}/*", OLD, FIXTURE, "BPR_1"),
    JanitorItem("environment", f"e2e-{OLD}-env", OLD, FIXTURE),
    JanitorItem("repo_secret", f"E2E_{OLD.upper()}_S", OLD, FIXTURE),
    JanitorItem("repo_variable", f"E2E_{OLD.upper()}_V", OLD, FIXTURE),
    JanitorItem("pull_request", f"e2e/{OLD}/pr", OLD, FIXTURE, "5"),
    JanitorItem("branch", f"heads/e2e/{OLD}/b", OLD, FIXTURE, "a" * 40),
    JanitorItem("branch", f"heads/otterdog/e2e-{OLD}-c", OLD, FIXTURE, "a" * 40),
    JanitorItem("template_tag", "tags/sut-v1.6.1-aaaa1111", None, DEFAULTS, fake_sha("old")),
    JanitorItem("ledger_tag", f"tags/e2e-run/{ANCIENT}", ANCIENT, CONFIGS),
}


def test_scan_classifies_leftovers() -> None:
    """Only objects of purgeable runs, outside protected repos, with e2e names/URLs/branches are listed."""
    items = make_janitor(build_oracle()).scan()
    assert set(items) == EXPECTED
    assert len(items) == len(EXPECTED)
    assert {item.kind for item in items} <= set(JANITOR_KINDS)


def test_scan_tolerates_unavailable_and_failing_listings(caplog: pytest.LogCaptureFixture) -> None:
    """403/404 listings are skipped; other errors are recorded and the scan goes on."""
    oracle = build_oracle()
    oracle.mark_unavailable("org_rulesets", status=403)
    oracle.mark_unavailable("custom_properties", status=404)
    oracle.mark_unavailable("repo_rulesets", FIXTURE, status=404)

    def broken() -> list[dict[str, Any]]:
        """A listing failing with a server error."""
        raise GitHubError(500, "GET", f"{GITHUB_API}/orgs/{FAKE_ORG}/teams", "boom")

    oracle.teams = broken  # type: ignore[method-assign]
    janitor = make_janitor(oracle)
    with caplog.at_level("INFO"):
        items = janitor.scan()
    kinds = {item.kind for item in items}
    assert "org_ruleset" not in kinds and "custom_property" not in kinds and "repo_ruleset" not in kinds
    assert "team" not in kinds and "repo" in kinds and "bpr" in kinds
    assert len(janitor.scan_errors) == 1 and "teams" in janitor.scan_errors[0]
    assert "org_rulesets" in caplog.text


def test_scan_without_defaults_repo_and_with_expired_lease_refs() -> None:
    """No defaults repo => no template tags; refs of an expired lease no longer protect tags."""
    janitor = make_janitor(build_oracle())
    janitor.defaults_repo = None
    assert not any(item.kind == "template_tag" for item in janitor.scan())
    expired = {
        "run_id": ACTIVE,
        "holder": "x",
        "expires_at": format_time(NOW - timedelta(hours=1)),
        "refs": ["tags/sut-pr792-d0d3b08-cccc3333"],
    }
    tags = {
        item.name
        for item in make_janitor(build_oracle(), lease=StubLease(record=expired)).scan()
        if item.kind == "template_tag"
    }
    assert tags == {"tags/sut-v1.6.1-aaaa1111", "tags/sut-pr792-d0d3b08-cccc3333"}
    session_refs = StubLease(record=None, refs=["refs/tags/sut-v1.6.1-aaaa1111"])
    assert not any(
        i.kind == "template_tag" and "aaaa1111" in i.name
        for i in make_janitor(build_oracle(), lease=session_refs).scan()
    )


def test_sweep_requires_the_lease() -> None:
    """Without the lease nothing is deleted (dry-run mutators may sweep for a report)."""
    oracle = build_oracle()
    with pytest.raises(SafetyError):
        make_janitor(oracle, lease=StubLease(held=False)).sweep()
    dry = JanitorRecordingMutator(oracle=oracle)
    dry.dry_run = True
    assert make_janitor(oracle, mutator=dry, lease=StubLease(held=False)).sweep(
        [JanitorItem("team", f"e2e-{OLD}-team", OLD)]
    )


def test_sweep_dispatches_in_order() -> None:
    """Each kind maps to its guarded Mutator call; PRs before branches, repos late, the ledger last."""
    oracle = build_oracle()
    mutator = JanitorRecordingMutator(oracle=oracle)
    janitor = make_janitor(oracle, mutator=mutator)
    deleted = janitor.sweep()
    assert set(deleted) == EXPECTED and janitor.failures == []
    calls = [call.method for call in mutator.calls]
    assert calls[0] == "close_pull" and calls[-1] == "delete_ref"
    assert (
        calls.index("close_pull") < calls.index("delete_ref") < calls.index("delete_team") < calls.index("delete_repo")
    )
    assert mutator.calls_to("close_pull")[0].args == (FIXTURE, 5)
    assert mutator.calls_to("delete_org_ruleset")[0].args == (7,) and mutator.calls_to("delete_org_ruleset")[
        0
    ].kwargs == {"name": f"e2e-{OLD}-rs"}
    assert mutator.calls_to("delete_branch_protection_rule")[0].args == (FIXTURE, "BPR_1")
    assert mutator.calls[-1].args == (CONFIGS, f"tags/e2e-run/{ANCIENT}")
    assert [kind for kind in SWEEP_ORDER if kind not in JANITOR_KINDS] == []


def test_sweep_continues_after_failures() -> None:
    """Refusals and errors are recorded; 403/404 are skipped; the remaining items are still deleted."""
    oracle = build_oracle()
    mutator = JanitorRecordingMutator(oracle=oracle)

    def gone(slug: str, *, force: bool = False) -> None:
        """The team vanished meanwhile."""
        raise GitHubError(404, "DELETE", f"{GITHUB_API}/orgs/{FAKE_ORG}/teams/{slug}", "Not Found")

    def boom(name: str) -> None:
        """A server error."""
        raise GitHubError(502, "DELETE", f"{GITHUB_API}/orgs/{FAKE_ORG}/actions/secrets/{name}", "Bad Gateway")

    mutator.delete_team = gone  # type: ignore[method-assign]
    mutator.delete_org_secret = boom  # type: ignore[method-assign]
    items = [
        JanitorItem("team", f"e2e-{OLD}-team", OLD),
        JanitorItem("org_secret", f"E2E_{OLD.upper()}_TOKEN", OLD),
        JanitorItem("repo", "not-e2e", OLD),
        JanitorItem("mystery", "x", OLD),
        JanitorItem("repo", f"e2e-{OLD}-basic", OLD),
    ]
    janitor = make_janitor(oracle, mutator=mutator)
    assert janitor.sweep(items) == [JanitorItem("repo", f"e2e-{OLD}-basic", OLD)]
    assert {item.name for item, _ in janitor.failures} == {f"E2E_{OLD.upper()}_TOKEN", "not-e2e", "x"}


@pytest.fixture
def api() -> Iterator[responses.RequestsMock]:
    """Mocked api.github.com."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield mock


def test_sweep_with_the_real_mutator_guards(api: responses.RequestsMock) -> None:
    """A stale scan item is re-checked by the Mutator: a hook whose live URL changed is not deleted."""
    verified = make_verified_org()
    mutator = Mutator(
        GitHubHttp("ghp_" + "JanitorTestToken0123456789abcdefghijk", write_scope=verified, min_write_interval=0.0),
        verified,
    )
    org = f"{GITHUB_API}/orgs/{FAKE_ORG}"
    api.add(responses.GET, f"{org}/hooks/11", json={"id": 11, "config": {"url": "https://ci.example.org/re-used"}})
    api.add(responses.GET, f"{org}/hooks/12", json={"id": 12, "config": {"url": f"{HOOK_BASE}{OLD}/org"}})
    api.add(responses.DELETE, f"{org}/hooks/12", status=204)
    api.add(responses.DELETE, f"{GITHUB_API}/repos/{FAKE_ORG}/{CONFIGS}/git/refs/tags/e2e-run/{ANCIENT}", status=204)
    janitor = make_janitor(build_oracle(), mutator=mutator)
    items = [
        JanitorItem("org_hook", f"{HOOK_BASE}{OLD}/org", OLD, "", "11"),
        JanitorItem("org_hook", f"{HOOK_BASE}{OLD}/org", OLD, "", "12"),
        JanitorItem("ledger_tag", f"tags/e2e-run/{ANCIENT}", ANCIENT, CONFIGS),
    ]
    deleted = janitor.sweep(items)
    assert [item.detail for item in deleted] == ["12", ""]
    assert len(janitor.failures) == 1 and "not under" in janitor.failures[0][1]
    assert [call.request.method for call in api.calls] == ["GET", "GET", "DELETE", "DELETE"]


def test_janitor_with_the_official_fakes() -> None:
    """The janitor runs on testing.fakes' FakeOracle, RecordingMutator and FakeLease (as other packages use it)."""
    from otterdog_e2e.testing.fakes import FakeLease

    oracle = FakeOracle()
    oracle.add_repo(f"e2e-{OLD}-basic")
    oracle.add_repo(FIXTURE)
    oracle.set("matching_refs", FIXTURE, "heads/e2e/", value=[ref(f"refs/heads/e2e/{OLD}/b")])
    lease = FakeLease(run_id=OWN, ledger=sorted(LEDGER))
    janitor = Janitor(
        oracle,  # type: ignore[arg-type]
        RecordingMutator(oracle=oracle),  # type: ignore[arg-type]
        lease=lease,  # type: ignore[arg-type]
        configs_repo=CONFIGS,
        defaults_repo=None,
        protected_repos=[FIXTURE],
        purgeable=purgeable,
    )
    janitor.clock = lambda: NOW
    items = janitor.scan()
    assert set(items) == {
        JanitorItem("repo", f"e2e-{OLD}-basic", OLD),
        JanitorItem("branch", f"heads/e2e/{OLD}/b", OLD, FIXTURE, "a" * 40),
        JanitorItem("ledger_tag", f"tags/e2e-run/{ANCIENT}", ANCIENT, CONFIGS),
        JanitorItem("ledger_tag", f"tags/e2e-run/{ANCIENT_BUSY}", ANCIENT_BUSY, CONFIGS),  # no leftover here
    }
    with pytest.raises(SafetyError):
        janitor.sweep(items)
    lease.acquire()
    assert set(janitor.sweep(items)) == set(items)


def test_code_security_configurations_of_finished_runs_are_swept() -> None:
    """e2e configurations of purgeable runs are listed (with their id); a default is set back to none before the
    deletion; foreign and active-run configurations are kept."""
    oracle = GitFakeOracle()
    old = oracle.add_code_security_configuration(f"e2e-{OLD}-csc", default_for_new_repos="all")
    plain = oracle.add_code_security_configuration(f"e2e-{OLD}-plain")
    oracle.add_code_security_configuration(f"e2e-{ACTIVE}-csc")
    oracle.add_code_security_configuration("GitHub recommended", target_type="global")
    janitor = make_janitor(oracle, mutator=RecordingMutator(oracle=oracle))
    items = [item for item in janitor.scan() if item.kind == "code_security_configuration"]
    assert set(items) == {
        JanitorItem("code_security_configuration", f"e2e-{OLD}-csc", OLD, "", str(old["id"])),
        JanitorItem("code_security_configuration", f"e2e-{OLD}-plain", OLD, "", str(plain["id"])),
    }
    mutator = janitor.mutator
    assert set(janitor.sweep(items)) == set(items) and janitor.failures == []
    calls = [(call.method, call.args) for call in mutator.calls]  # type: ignore[attr-defined]
    assert calls.index(("set_code_security_default", (old["id"],))) < calls.index(
        ("delete_code_security_configuration", (old["id"],))
    )
    assert ("set_code_security_default", (plain["id"],)) not in calls
    assert [c["name"] for c in oracle.code_security_configurations()] == [f"e2e-{ACTIVE}-csc", "GitHub recommended"]
    assert oracle.code_security_default_configurations() == []
