"""OrgLease: acquire/busy/steal/renew/release, ledger tags and the heartbeat (SPEC 5.3)."""

from __future__ import annotations

import hashlib
import json
import re
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import requests
import responses

from otterdog_e2e.github.http import GITHUB_API, GitHubError, GitHubHttp
from otterdog_e2e.github.lease import UNPARSEABLE_HOLDER, LeaseBusy, OrgLease, format_time
from otterdog_e2e.github.mutate import Mutator
from otterdog_e2e.github.oracle import Oracle
from otterdog_e2e.naming import new_run_context
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FAKE_ORG, make_verified_org

REPO = "otterdog-e2e-configs"
BASE = f"{GITHUB_API}/repos/{FAKE_ORG}/{REPO}"
NOW = datetime(2030, 3, 1, 12, 0, tzinfo=UTC)
MAIN_SHA, MAIN_TREE = "a" * 40, "b" * 40
RUN = new_run_context("t3c7z8a5")
OTHER = new_run_context("t3c7z9b1")
Callback = Callable[[requests.PreparedRequest], tuple[int, dict[str, str], str]]


class GitServer:
    """In-memory refs and commits of one repository behind the GitHub git-data REST API."""

    def __init__(self, mock: responses.RequestsMock) -> None:
        """Register the callbacks on ``mock``."""
        self.refs: dict[str, str] = {"refs/heads/main": MAIN_SHA}
        self.commits: dict[str, dict[str, Any]] = {
            MAIN_SHA: self._commit(MAIN_SHA, "initial commit", MAIN_TREE, [], NOW - timedelta(days=90))
        }
        self.before_patch: Callable[[], None] | None = None
        self.refused_prefix: str | None = None  # simulates a ruleset restricting ref creation
        self.patches: list[dict[str, Any]] = []
        tail = r"(?:\?.*)?$"
        mock.add(responses.GET, BASE, json={"name": REPO, "default_branch": "main"})
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE)}/git/ref/(.+?){tail}"), self.get_ref)
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE)}/git/matching-refs/(.+?){tail}"), self.matching)
        mock.add_callback(responses.GET, re.compile(rf"{re.escape(BASE)}/git/commits/(\w+){tail}"), self.get_commit)
        mock.add_callback(responses.POST, f"{BASE}/git/commits", self.create_commit)
        mock.add_callback(responses.POST, f"{BASE}/git/refs", self.create_ref)
        mock.add_callback(responses.PATCH, re.compile(rf"{re.escape(BASE)}/git/refs/(.+)$"), self.update_ref)
        mock.add_callback(responses.DELETE, re.compile(rf"{re.escape(BASE)}/git/refs/(.+)$"), self.delete_ref)

    @staticmethod
    def _commit(sha: str, message: str, tree: str, parents: list[str], when: datetime) -> dict[str, Any]:
        """A git commit object."""
        date = format_time(when)
        return {
            "sha": sha,
            "message": message,
            "tree": {"sha": tree},
            "parents": [{"sha": p} for p in parents],
            "committer": {"date": date},
            "author": {"date": date},
        }

    @staticmethod
    def _path_ref(request: requests.PreparedRequest, marker: str) -> str:
        """The ref named in the URL after ``marker``."""
        return "refs/" + str(request.path_url).split(marker, 1)[1].split("?", 1)[0]

    @staticmethod
    def _json(status: int, data: Any) -> tuple[int, dict[str, str], str]:
        """A JSON callback answer."""
        return status, {"Content-Type": "application/json"}, json.dumps(data)

    def _ref_object(self, ref: str) -> dict[str, Any]:
        """REST ref representation."""
        return {"ref": ref, "object": {"sha": self.refs[ref], "type": "commit"}}

    def get_ref(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        """GET git/ref/{ref}."""
        ref = self._path_ref(request, "/git/ref/")
        if ref not in self.refs:
            return self._json(404, {"message": "Not Found"})
        return self._json(200, self._ref_object(ref))

    def matching(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        """GET git/matching-refs/{prefix}."""
        prefix = self._path_ref(request, "/git/matching-refs/")
        return self._json(200, [self._ref_object(ref) for ref in sorted(self.refs) if ref.startswith(prefix)])

    def get_commit(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        """GET git/commits/{sha}."""
        sha = str(request.path_url).rsplit("/", 1)[1].split("?", 1)[0]
        if sha not in self.commits:
            return self._json(404, {"message": "Not Found"})
        return self._json(200, self.commits[sha])

    def create_commit(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        """POST git/commits."""
        data = json.loads(request.body or "{}")
        sha = hashlib.sha1(json.dumps([data, len(self.commits)]).encode(), usedforsecurity=False).hexdigest()
        self.commits[sha] = self._commit(sha, data["message"], data["tree"], list(data["parents"]), NOW)
        return self._json(201, self.commits[sha])

    def create_ref(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        """POST git/refs (422 when the ref exists)."""
        data = json.loads(request.body or "{}")
        if self.refused_prefix and data["ref"].startswith(self.refused_prefix):
            return self._json(422, {"message": "Repository rule violations found"})
        if data["ref"] in self.refs:
            return self._json(422, {"message": "Reference already exists"})
        self.refs[data["ref"]] = data["sha"]
        return self._json(201, self._ref_object(data["ref"]))

    def _descends(self, sha: str, ancestor: str) -> bool:
        """True when ``ancestor`` is reachable from ``sha``."""
        todo = [sha]
        while todo:
            current = todo.pop()
            if current == ancestor:
                return True
            todo.extend(p["sha"] for p in self.commits.get(current, {}).get("parents", []))
        return False

    def update_ref(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        """PATCH git/refs/{ref} (fast-forward check unless force)."""
        if self.before_patch is not None:
            hook, self.before_patch = self.before_patch, None
            hook()
        ref = self._path_ref(request, "/git/refs/")
        data = json.loads(request.body or "{}")
        self.patches.append(data)
        if ref not in self.refs:
            return self._json(422, {"message": "Reference does not exist"})
        if not data.get("force") and not self._descends(data["sha"], self.refs[ref]):
            return self._json(422, {"message": "Update is not a fast forward"})
        self.refs[ref] = data["sha"]
        return self._json(200, self._ref_object(ref))

    def delete_ref(self, request: requests.PreparedRequest) -> tuple[int, dict[str, str], str]:
        """DELETE git/refs/{ref}."""
        ref = self._path_ref(request, "/git/refs/")
        if self.refs.pop(ref, None) is None:
            return self._json(422, {"message": "Reference does not exist"})
        return 204, {}, ""

    def put_lease(self, record: dict[str, Any] | str, *, when: datetime = NOW) -> str:
        """Make refs/heads/e2e-lease point at a commit carrying ``record``."""
        message = record if isinstance(record, str) else json.dumps(record)
        sha = hashlib.sha1(message.encode(), usedforsecurity=False).hexdigest()
        self.commits[sha] = self._commit(sha, message, MAIN_TREE, [MAIN_SHA], when)
        self.refs["refs/heads/e2e-lease"] = sha
        return sha

    def record(self, ref: str = "refs/heads/e2e-lease") -> dict[str, Any]:
        """Decoded lease record of the commit ``ref`` points at."""
        return json.loads(self.commits[self.refs[ref]]["message"])


@pytest.fixture
def server() -> Iterator[GitServer]:
    """A fresh git server."""
    with responses.RequestsMock(assert_all_requests_are_fired=False) as mock:
        yield GitServer(mock)


@pytest.fixture
def sleeps() -> list[float]:
    """Recorded sleeps."""
    return []


def make_lease(sleeps: list[float], run_ctx: Any = RUN, holder: str = "local:test") -> OrgLease:
    """A lease over real Oracle/Mutator clients with a frozen clock."""
    verified = make_verified_org()
    token = "ghp_" + "LeaseTestToken0123456789abcdefghijklm"
    mutator = Mutator(GitHubHttp(token, write_scope=verified, min_write_interval=0.0, sleep=sleeps.append), verified)
    oracle = Oracle(GitHubHttp(token, read_only=True, sleep=sleeps.append), FAKE_ORG)
    lease = OrgLease(mutator, oracle, repo=REPO, run_ctx=run_ctx, holder=holder)
    lease.clock = lambda: NOW
    lease.sleep = sleeps.append
    return lease


def foreign(expires: datetime, run_ctx: Any = OTHER) -> dict[str, Any]:
    """Another session's lease record."""
    return {"run_id": run_ctx.run_id, "holder": "ci:other", "expires_at": format_time(expires)}


def test_acquire_creates_the_lease_and_the_ledger_tag(server: GitServer, sleeps: list[float]) -> None:
    """A JSON-message commit on the default-branch tree, refs/heads/e2e-lease and refs/tags/e2e-run/<id>."""
    lease = make_lease(sleeps)
    lease.acquire()
    assert lease.held
    sha = server.refs["refs/heads/e2e-lease"]
    commit = server.commits[sha]
    assert commit["tree"]["sha"] == MAIN_TREE and commit["parents"] == [{"sha": MAIN_SHA}]
    assert json.loads(commit["message"]) == {
        "run_id": RUN.run_id,
        "holder": "local:test",
        "expires_at": "2030-03-01T15:00:00Z",
    }
    assert server.refs[f"refs/tags/e2e-run/{RUN.run_id}"] == sha
    assert lease.ledger() == [RUN.run_id]
    assert lease.holder_record() == lease.record
    lease.acquire()  # idempotent while held
    assert server.refs["refs/heads/e2e-lease"] == sha


def test_acquire_busy(server: GitServer, sleeps: list[float]) -> None:
    """An unexpired foreign lease -> LeaseBusy carrying the holder; nothing is changed or registered."""
    sha = server.put_lease(foreign(NOW + timedelta(hours=1)))
    lease = make_lease(sleeps)
    with pytest.raises(LeaseBusy) as info:
        lease.acquire()
    assert info.value.holder["holder"] == "ci:other" and info.value.holder["run_id"] == OTHER.run_id
    assert server.refs["refs/heads/e2e-lease"] == sha
    assert not any(ref.startswith("refs/tags/") for ref in server.refs)
    assert not lease.held


def test_acquire_waits_then_gives_up(server: GitServer, sleeps: list[float]) -> None:
    """wait=N re-checks every 30 s (virtual time) and then raises LeaseBusy."""
    server.put_lease(foreign(NOW + timedelta(hours=1)))
    lease = make_lease(sleeps)
    with pytest.raises(LeaseBusy):
        lease.acquire(wait=75)
    assert sleeps == [30.0, 30.0, 15.0]


def test_acquire_waits_until_released(server: GitServer, sleeps: list[float]) -> None:
    """A lease released while waiting is acquired at the next check."""
    server.put_lease(foreign(NOW + timedelta(hours=1)))
    lease = make_lease(sleeps)
    lease.sleep = lambda seconds: (sleeps.append(seconds), server.refs.pop("refs/heads/e2e-lease"))  # type: ignore[assignment,func-returns-value]
    lease.acquire(wait=600)
    assert lease.held and sleeps == [30.0]


def test_steal_expired_lease_with_compare_and_swap(server: GitServer, sleeps: list[float]) -> None:
    """An expired lease is stolen by a fast-forward (non-forced) update on top of the expired lease commit."""
    old = server.put_lease(foreign(NOW - timedelta(minutes=1)))
    lease = make_lease(sleeps)
    lease.acquire()
    sha = server.refs["refs/heads/e2e-lease"]
    assert sha != old and server.commits[sha]["parents"] == [{"sha": old}]
    assert server.record()["run_id"] == RUN.run_id
    assert server.patches[-1] == {"sha": sha, "force": False}
    assert lease.held and lease.ledger() == [RUN.run_id]


def test_steal_disabled(server: GitServer, sleeps: list[float]) -> None:
    """steal_expired=False keeps an expired lease."""
    server.put_lease(foreign(NOW - timedelta(minutes=1)))
    with pytest.raises(LeaseBusy, match="stealing is disabled"):
        make_lease(sleeps).acquire(steal_expired=False)


def test_steal_lost_race(server: GitServer, sleeps: list[float]) -> None:
    """When another session steals first, our update is not a fast-forward and LeaseBusy names the winner."""
    old = server.put_lease(foreign(NOW - timedelta(minutes=1)))

    def other_steals() -> None:
        """A concurrent stealer moves the ref first."""
        winner = {"run_id": "t3c7zaaa", "holder": "ci:winner", "expires_at": format_time(NOW + timedelta(hours=3))}
        sha = hashlib.sha1(b"winner", usedforsecurity=False).hexdigest()
        server.commits[sha] = GitServer._commit(sha, json.dumps(winner), MAIN_TREE, [old], NOW)
        server.refs["refs/heads/e2e-lease"] = sha

    server.before_patch = other_steals
    lease = make_lease(sleeps)
    with pytest.raises(LeaseBusy) as info:
        lease.acquire()
    assert info.value.holder["holder"] == "ci:winner"
    assert not lease.held
    assert not any(ref.startswith("refs/tags/") for ref in server.refs)


def test_unparseable_lease_expires_after_ttl(server: GitServer, sleeps: list[float]) -> None:
    """A lease commit without a JSON record expires ttl after its commit date."""
    server.put_lease("manual lease", when=NOW - timedelta(hours=1))
    lease = make_lease(sleeps)
    record = lease.holder_record()
    assert record == {"run_id": None, "holder": UNPARSEABLE_HOLDER, "expires_at": "2030-03-01T14:00:00Z"}
    with pytest.raises(LeaseBusy):
        lease.acquire()
    server.put_lease("manual lease", when=NOW - timedelta(hours=4))
    lease.acquire()
    assert lease.held


def test_renew_extends_and_chains(server: GitServer, sleeps: list[float]) -> None:
    """renew() adds a child commit with a later expires_at and fast-forwards the ref."""
    lease = make_lease(sleeps)
    lease.acquire()
    first = server.refs["refs/heads/e2e-lease"]
    lease.clock = lambda: NOW + timedelta(hours=1)
    lease.renew()
    second = server.refs["refs/heads/e2e-lease"]
    assert server.commits[second]["parents"] == [{"sha": first}]
    assert server.record()["expires_at"] == "2030-03-01T16:00:00Z"
    assert server.patches[-1]["force"] is False


def test_renew_detects_a_lost_lease(server: GitServer, sleeps: list[float]) -> None:
    """If someone else moved the ref, renew raises LeaseBusy and the lease is marked lost."""
    lease = make_lease(sleeps)
    lease.acquire()
    server.put_lease(foreign(NOW + timedelta(hours=2)))
    with pytest.raises(LeaseBusy):
        lease.renew()
    assert lease.lost and not lease.held
    lease.release()  # not ours any more: left in place
    assert server.record()["holder"] == "ci:other"


def test_release_deletes_only_our_lease(server: GitServer, sleeps: list[float]) -> None:
    """release() deletes the lease ref we hold and keeps the ledger tag; a second release is a no-op."""
    lease = make_lease(sleeps)
    lease.acquire()
    lease.release()
    assert "refs/heads/e2e-lease" not in server.refs
    assert f"refs/tags/e2e-run/{RUN.run_id}" in server.refs
    assert not lease.held
    lease.release()
    assert lease.holder_record() is None


def test_ledger_collision(server: GitServer, sleeps: list[float]) -> None:
    """An existing ledger tag for our run id -> SafetyError and the fresh lease is released again."""
    server.refs[f"refs/tags/e2e-run/{RUN.run_id}"] = MAIN_SHA
    lease = make_lease(sleeps)
    with pytest.raises(SafetyError, match="already registered"):
        lease.acquire()
    assert "refs/heads/e2e-lease" not in server.refs
    assert not lease.held


def test_ledger_collision_is_refused_before_the_lease_is_touched(server: GitServer, sleeps: list[float]) -> None:
    """DESTR-03: a run id already in the ledger is refused before any lease commit or ref is written."""
    server.refs[f"refs/tags/e2e-run/{RUN.run_id}"] = MAIN_SHA
    commits = len(server.commits)
    with pytest.raises(SafetyError, match="already registered in the ledger"):
        make_lease(sleeps).acquire()
    assert len(server.commits) == commits and "refs/heads/e2e-lease" not in server.refs and not server.patches


def test_a_second_session_with_the_same_run_id_never_takes_over_the_live_lease(
    server: GitServer, sleeps: list[float]
) -> None:
    """DESTR-03: session B reusing the live run id of session A (same holder) is refused; A keeps its lease (the ref
    still points at A's commit) and later sessions stay locked out."""
    first = make_lease(sleeps)
    first.acquire()
    lease_sha = server.refs["refs/heads/e2e-lease"]
    second = make_lease(sleeps)  # same run id, same holder, another process
    with pytest.raises(SafetyError, match="already registered in the ledger"):
        second.acquire()
    assert server.refs["refs/heads/e2e-lease"] == lease_sha and first.held and not second.held
    del server.refs[f"refs/tags/e2e-run/{RUN.run_id}"]  # even without the ledger tag (registration race)
    with pytest.raises(LeaseBusy, match="another session of run"):
        make_lease(sleeps).acquire()
    assert server.refs["refs/heads/e2e-lease"] == lease_sha and first.held
    with pytest.raises(LeaseBusy):
        make_lease(sleeps, run_ctx=OTHER).acquire()
    first.renew()  # A still holds it
    assert first.held


def test_the_same_run_id_may_take_over_its_own_expired_lease(server: GitServer, sleeps: list[float]) -> None:
    """A crashed session of the same run id left an EXPIRED lease: stealing it is fine (compare-and-swap)."""
    server.put_lease({"run_id": RUN.run_id, "holder": "local:test", "expires_at": format_time(NOW - timedelta(1))})
    lease = make_lease(sleeps)
    lease.acquire()
    assert lease.held and server.record()["run_id"] == RUN.run_id


def test_janitor_takeover_needs_a_dead_run(server: GitServer, sleeps: list[float]) -> None:
    """DESTR-05: takeover_run replaces an unexpired lease of that run with a compare-and-swap update only when its
    last renewal is older than 20 minutes, the holder is trusted (this CI job) or the takeover is forced; the ref
    is never deleted."""
    record = {"run_id": OTHER.run_id, "holder": "local:alice", "expires_at": format_time(NOW + timedelta(hours=2))}
    server.put_lease(record, when=NOW - timedelta(minutes=5))
    lease = make_lease(sleeps, holder="local:janitor")
    with pytest.raises(LeaseBusy, match="renewed the org lease 300 s ago"):
        lease.acquire(takeover_run=OTHER.run_id)
    assert server.record()["run_id"] == OTHER.run_id and not lease.held
    lease.acquire(takeover_run=OTHER.run_id, trusted_holder="local:alice")
    assert lease.held and server.record()["run_id"] == RUN.run_id
    lease.release()
    server.put_lease(record, when=NOW - timedelta(minutes=25))
    stale = make_lease(sleeps, run_ctx=new_run_context("t3c7z8c1"))
    stale.acquire(takeover_run=OTHER.run_id)
    assert stale.held and server.record()["run_id"] == "t3c7z8c1"
    stale.release()
    server.put_lease(record, when=NOW - timedelta(minutes=1))
    forced = make_lease(sleeps, run_ctx=new_run_context("t3c7z8c2"))
    forced.acquire(takeover_run=OTHER.run_id, force_takeover=True)
    assert forced.held and not any(patch.get("force") for patch in server.patches)


def test_janitor_takeover_loses_against_a_session_that_acquired_meanwhile(
    server: GitServer, sleeps: list[float]
) -> None:
    """The takeover is a compare-and-swap: when the lease moved between the read and the update (the old run
    released and another session acquired), the takeover fails and the new holder keeps the lease."""
    record = {"run_id": OTHER.run_id, "holder": "local:alice", "expires_at": format_time(NOW + timedelta(hours=2))}
    server.put_lease(record, when=NOW - timedelta(hours=1))
    newcomer = {"run_id": "t3c7z8d4", "holder": "ci:other", "expires_at": format_time(NOW + timedelta(hours=3))}
    server.before_patch = lambda: server.put_lease(newcomer)
    lease = make_lease(sleeps, holder="local:janitor")
    with pytest.raises(LeaseBusy):
        lease.acquire(takeover_run=OTHER.run_id)
    assert server.record()["run_id"] == "t3c7z8d4" and not lease.held


def test_the_base_commit_of_a_just_created_repository_is_awaited(server: GitServer, sleeps: list[float]) -> None:
    """F3: right after bootstrap created the configs repository (auto_init), its head may be unreadable for a few
    seconds (404/409): acquire waits for it instead of failing with 'missing or empty'."""
    head = server.refs.pop("refs/heads/main")
    lease = make_lease(sleeps)

    def sleep(seconds: float) -> None:
        """The initial commit shows up during the second wait."""
        sleeps.append(seconds)
        if len(sleeps) == 2:
            server.refs["refs/heads/main"] = head

    lease.sleep = sleep
    lease.acquire()
    assert lease.held and sleeps == [3.0, 3.0]


def test_a_lease_repository_without_head_fails_after_the_retries(server: GitServer, sleeps: list[float]) -> None:
    """A repository that stays empty fails with a message naming bootstrap."""
    del server.refs["refs/heads/main"]
    with pytest.raises(RuntimeError, match="no readable default branch head after 30 s"):
        make_lease(sleeps).acquire()


def test_ledger_lists_valid_run_ids(server: GitServer, sleeps: list[float]) -> None:
    """Only refs/tags/e2e-run/<RUN_ID_RE> tags count (the prefix filter excludes look-alikes)."""
    for name in ("t3c7z8a5", "t3c7z9b1", "not-a-run", "T3C7Z8A5"):
        server.refs[f"refs/tags/e2e-run/{name}"] = MAIN_SHA
    server.refs["refs/tags/e2e-runner"] = MAIN_SHA
    assert make_lease(sleeps).ledger() == ["t3c7z8a5", "t3c7z9b1"]


def test_purgeable_fn(server: GitServer, sleeps: list[float]) -> None:
    """In the ledger and not the unexpired holder's run id (our own run is purgeable for us)."""
    for run_id in (RUN.run_id, OTHER.run_id, "t3c7zccc"):
        server.refs[f"refs/tags/e2e-run/{run_id}"] = MAIN_SHA
    server.put_lease(foreign(NOW + timedelta(hours=1)))
    purgeable = make_lease(sleeps).purgeable_fn()
    assert purgeable("t3c7zccc") and purgeable(RUN.run_id)
    assert not purgeable(OTHER.run_id) and not purgeable("t3c7zddd")
    server.put_lease(foreign(NOW - timedelta(hours=1)))
    assert make_lease(sleeps).purgeable_fn()(OTHER.run_id)


def test_reference_is_recorded(server: GitServer, sleeps: list[float]) -> None:
    """reference() lists refs in the lease record so the janitor keeps them."""
    lease = make_lease(sleeps)
    lease.acquire()
    lease.reference("refs/tags/sut-v1.6.1-abcd1234")
    assert server.record()["refs"] == ["tags/sut-v1.6.1-abcd1234"]


def test_dry_run_mutator_cannot_hold_the_lease(sleeps: list[float]) -> None:
    """A dry-run mutator would fake exclusivity: refused."""
    verified = make_verified_org()
    http = GitHubHttp(None, read_only=True)
    lease = OrgLease(Mutator(http, verified, dry_run=True), Oracle(http, FAKE_ORG), repo=REPO, run_ctx=RUN, holder="x")
    with pytest.raises(SafetyError):
        lease.acquire()


def test_heartbeat_renews_until_stopped(server: GitServer, sleeps: list[float]) -> None:
    """The daemon thread renews every interval; stop_heartbeat (and release) stop it."""
    lease = make_lease(sleeps)
    lease.acquire()
    first = server.refs["refs/heads/e2e-lease"]
    lease.start_heartbeat(interval=0.01)
    deadline = time.monotonic() + 5
    while server.refs["refs/heads/e2e-lease"] == first and time.monotonic() < deadline:
        time.sleep(0.01)
    lease.stop_heartbeat()
    assert server.refs["refs/heads/e2e-lease"] != first
    assert not any(t.name == f"e2e-lease-{RUN.run_id}" for t in threading.enumerate())
    lease.stop_heartbeat()
    lease.release()
    assert "refs/heads/e2e-lease" not in server.refs


def test_rule_violations_are_not_mistaken_for_a_held_lease(server: GitServer, sleeps: list[float]) -> None:
    """A 422 that is not "Reference already exists" (e.g. a ruleset) surfaces as the GitHubError it is."""
    server.refused_prefix = "refs/heads/"
    with pytest.raises(GitHubError, match="rule violations"):
        make_lease(sleeps).acquire()
    server.refused_prefix = "refs/tags/"
    lease = make_lease(sleeps)
    with pytest.raises(GitHubError, match="rule violations"):
        lease.acquire()
    assert not lease.held and "refs/heads/e2e-lease" not in server.refs
