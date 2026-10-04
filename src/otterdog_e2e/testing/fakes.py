"""Fakes of the harness collaborators for unit tests: no network, no docker, no otterdog process.

* FakeGitHubHttp - route table with the GitHubHttp method names and error semantics (SPEC 4)
* FakeOracle     - dict-backed Oracle: ``set(method, *args, value=...)`` plus builders (add_repo, add_team, ...)
* FakeCli        - OtterdogCli stand-in returning queued CliResults per command and recording calls (``web`` and
  ``installed`` like OtterdogCli, for web-mode stand-ins)
* FakeWorkspace  - ConfigWorkspace with the real paths and layouts that records its writes in memory (no disk I/O)
* RecordingMutator - records every Mutator call and returns plausible values (optionally updating a FakeOracle), with
  the Mutator's guards (e2e names, run-branch pull requests)
* FakeAppAuth    - AppAuth stand-in serving a list of webhook deliveries (newest first, cursor pagination)
* FakeLease      - OrgLease stand-in (busy/expired holder, ledger, heartbeat) recording calls
* FakeBaselineManager - BaselineManager stand-in recording resets, guarded applies, pushes and removal checks

Helpers: make_verified_org(), make_run_context(), fake_sha(), cli_result(), make_settings(), make_target(),
make_identities().
"""

from __future__ import annotations

import copy
import fnmatch
import hashlib
import itertools
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from otterdog_e2e import naming
from otterdog_e2e.github.http import GitHubError
from otterdog_e2e.github.lease import LeaseBusy
from otterdog_e2e.github.oracle import Oracle
from otterdog_e2e.otterdog.runner import CliResult, DiffOptions
from otterdog_e2e.otterdog.workspace import ConfigWorkspace
from otterdog_e2e.safety import CLASSIC, FINE_GRAINED, SafetyError, TokenInfo, VerifiedOrg, _mint_verified_org
from otterdog_e2e.settings import AppSpec, HarnessSettings, Identity, IdentitySpec, Target, WebappSpec

FAKE_ORG = "e2e-test-org"
FAKE_ORG_ID = 424242
FAKE_MARKER = "[otterdog-e2e]"
FAKE_RUN_ID = "t3c7z8a5"  # base36 of 2025-09-29 + 2 hex: plausible for naming.extract_run_id
FAKE_CLI_CWD = Path("/nonexistent/otterdog-e2e-fake-cli")
FAKE_VERSION = "1.6.1"

# realistic default outputs (captured from otterdog 1.7.0.dev19 with COLUMNS=4096 NO_COLOR=1)
_LEGEND = "\nActions are indicated with the following symbols:\n  + create\n  ~ modify\n  ! forced update\n  - delete\n"
DEFAULT_OUTPUTS: Mapping[str, str] = {
    "--version": f"otterdog.sh, version {FAKE_VERSION}\n",
    "validate": "Validating organization configurations:\n\nProject {org}[github_id={org}] (1/1)\n  Validation succeeded\n",
    "plan": "Planning execution:\n" + _LEGEND + "\nProject {org}[github_id={org}] (1/1)\n  \n"
    "  Plan: 0 to add, 0 to change, 0 to delete.\n",
    "local-plan": "Printing local diff:\n" + _LEGEND + "\nProject {org}[github_id={org}] (1/1)\n  \n"
    "  Plan: 0 to add, 0 to change, 0 to delete.\n",
    "apply": "Applying changes:\n" + _LEGEND + "\nProject {org}[github_id={org}] (1/1)\n\n  No changes required.\n",
}


def fake_sha(seed: object) -> str:
    """Deterministic 40-hex sha derived from ``seed``."""
    return hashlib.sha1(str(seed).encode(), usedforsecurity=False).hexdigest()


def make_run_context(run_id: str = FAKE_RUN_ID, now: datetime | None = None) -> naming.RunContext:
    """A RunContext with a fixed, plausible run id."""
    return naming.new_run_context(run_id, now=now)


def make_verified_org(
    login: str = FAKE_ORG,
    *,
    org_id: int = FAKE_ORG_ID,
    plan: str = "free",
    target: str = "fake",
    description: str = f"{FAKE_MARKER} fake test organization",
    org_json: Mapping[str, Any] | None = None,
) -> VerifiedOrg:
    """A VerifiedOrg for unit tests (bypasses verify_target; never use outside tests)."""
    data = dict(org_json) if org_json is not None else default_org_json(login, org_id=org_id, plan=plan)
    data.setdefault("description", description)
    return _mint_verified_org(login=login, org_id=org_id, plan=plan, target=target, org_json=data)


def default_org_json(login: str = FAKE_ORG, *, org_id: int = FAKE_ORG_ID, plan: str = "free") -> dict[str, Any]:
    """A minimal GET /orgs/{org} answer as an owner sees it."""
    return {
        "login": login,
        "id": org_id,
        "name": "E2E Test Org",
        "description": f"{FAKE_MARKER} fake test organization",
        "billing_email": "billing@example.org",
        "email": None,
        "blog": None,
        "location": None,
        "company": None,
        "twitter_username": None,
        "plan": {"name": plan},
    }


def cli_result(
    command: str,
    stdout: str = "",
    *,
    exit_code: int = 0,
    stderr: str = "",
    args: Sequence[str] = (),
    duration: float = 0.01,
    timed_out: bool = False,
    infra_error: str | None = None,
    cwd: Path = FAKE_CLI_CWD,
) -> CliResult:
    """A CliResult as OtterdogCli would return for ``otterdog <command> <args>``."""
    return CliResult(
        argv=["otterdog", command, *args],
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration=duration,
        cwd=cwd,
        timed_out=timed_out,
        infra_error=infra_error,
    )


# --- FakeGitHubHttp ------------------------------------------------------------------------------------------------
@dataclass
class HttpCall:
    """One request made against FakeGitHubHttp."""

    method: str
    path: str
    params: dict[str, Any] | None = None
    json: Any = None


# responder(call) -> (status, body) or (status, body, headers)
Responder = Callable[[HttpCall], tuple[Any, ...]]


@dataclass
class _Route:
    """One registered FakeGitHubHttp response."""

    status: int
    body: Any
    headers: dict[str, str]
    repeat: bool
    responder: Responder | None = None


class FakeGitHubHttp:
    """Route-table stand-in for github.http.GitHubHttp.

    ``add(method, path, status=200, json=...)`` registers one response (``repeat=True`` keeps it); ``path`` may be an
    fnmatch pattern; a callable ``responder(call) -> (status, body[, headers])`` computes answers. Unregistered requests
    raise AssertionError (``strict``) or answer 404. read_only clients refuse non-GET requests except GraphQL queries;
    write_scope is stored but NOT enforced (the real GitHubHttp does).
    """

    def __init__(
        self,
        *,
        identity: str = "fake",
        scopes: set[str] | None = None,
        read_only: bool = False,
        write_scope: VerifiedOrg | None = None,
        strict: bool = True,
        token_kind: str | None = None,
        expires_at: datetime | None = None,
    ) -> None:
        """Create an empty route table; ``scopes`` is what oauth_scopes() returns (None = fine-grained).

        token_info() reports ``token_kind`` (default: classic with scopes, fine-grained without) and ``expires_at``.
        """
        self.identity = identity
        self.scopes = scopes
        self.token_kind = token_kind
        self.expires_at = expires_at
        self.read_only = read_only
        self.write_scope = write_scope
        self.strict = strict
        self.routes: dict[tuple[str, str], list[_Route]] = {}
        self.calls: list[HttpCall] = []
        self.unavailable: dict[str, int] = {}
        self.rate_remaining = 5000

    def add(
        self,
        method: str,
        path: str,
        *,
        status: int = 200,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
        repeat: bool = False,
        responder: Responder | None = None,
    ) -> FakeGitHubHttp:
        """Register a response for ``method path`` (FIFO; ``repeat`` keeps the last one)."""
        route = _Route(status, json, dict(headers or {}), repeat, responder)
        self.routes.setdefault((method.upper(), path), []).append(route)
        return self

    def calls_to(self, method: str, path: str | None = None) -> list[HttpCall]:
        """Recorded calls with this method (and path pattern)."""
        return [c for c in self.calls if c.method == method.upper() and (path is None or fnmatch.fnmatch(c.path, path))]

    def _route(self, method: str, path: str) -> _Route | None:
        """First matching route (exact path first, then patterns), consumed unless repeat."""
        candidates = [key for key in self.routes if key == (method, path)]
        candidates += [key for key in self.routes if key[0] == method and fnmatch.fnmatch(path, key[1])]
        for key in candidates:
            queue = self.routes[key]
            if queue:
                return queue[0] if queue[0].repeat else queue.pop(0)
        return None

    def _answer(self, call: HttpCall) -> tuple[int, Any, dict[str, str]]:
        """Status, body and headers for a call."""
        route = self._route(call.method, call.path)
        if route is None:
            if self.strict:
                raise AssertionError(f"FakeGitHubHttp: unexpected request {call.method} {call.path}")
            return 404, {"message": "Not Found"}, {}
        if route.responder is None:
            return route.status, copy.deepcopy(route.body), dict(route.headers)
        answer = route.responder(call)
        headers = dict(answer[2]) if len(answer) > 2 else {}
        return answer[0], answer[1], headers

    def _guard(self, method: str, path: str, body: Any) -> None:
        """read_only clients may only GET (and POST /graphql queries)."""
        if not self.read_only or method in ("GET", "HEAD"):
            return
        if method == "POST" and path == "/graphql" and str((body or {}).get("query", "")).lstrip()[:1] in ("q", "{"):
            return
        raise SafetyError(f"read-only client refuses {method} {path}")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json: Any = None,
        data: Any = None,
        headers: Mapping[str, str] | None = None,
        expected: Sequence[int] = (200, 201, 202, 204),
        allow: Sequence[int] = (),
    ) -> requests.Response:
        """Answer from the route table; GitHubError when the status is neither expected nor allowed."""
        method = method.upper()
        self._guard(method, path, json)
        call = HttpCall(method, path, dict(params) if params else None, copy.deepcopy(json))
        self.calls.append(call)
        status, body, response_headers = self._answer(call)
        response = requests.Response()
        response.status_code = status
        response._content = b"" if body is None else json_dumps(body)
        response.headers.update({"Content-Type": "application/json", **response_headers})
        response.url = f"https://api.github.com{path}"
        if status not in expected and status not in allow:
            raise GitHubError(status, method, response.url, response.text, dict(response.headers))
        return response

    @staticmethod
    def _decode(response: requests.Response) -> Any:
        """JSON body or None."""
        return response.json() if response.content else None

    def get(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
        allow_404: bool = False,
    ) -> Any:
        """GET; None on 404 when allow_404."""
        response = self.request("GET", path, params=params, headers=headers, allow=(404,) if allow_404 else ())
        return None if response.status_code == 404 else self._decode(response)

    def paginate(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        per_page: int = 100,
        item_key: str | None = None,
        max_pages: int = 50,
        allow_unavailable: bool = False,
    ) -> list[Any]:
        """One page (the registered body); 403/404 -> [] and unavailable[path] when allow_unavailable."""
        allow = (403, 404) if allow_unavailable else ()
        response = self.request("GET", path, params={**(params or {}), "per_page": per_page}, allow=allow)
        if response.status_code in (403, 404):
            self.unavailable[path] = response.status_code
            return []
        body = self._decode(response)
        items = body.get(item_key, []) if item_key and isinstance(body, dict) else body
        return list(items or [])

    def post(self, path: str, json: Any = None, **kw: Any) -> Any:
        """POST."""
        return self._decode(self.request("POST", path, json=json, **kw))

    def put(self, path: str, json: Any = None, **kw: Any) -> Any:
        """PUT."""
        return self._decode(self.request("PUT", path, json=json, **kw))

    def patch(self, path: str, json: Any = None, **kw: Any) -> Any:
        """PATCH."""
        return self._decode(self.request("PATCH", path, json=json, **kw))

    def delete(self, path: str, *, allow_404: bool = True, **kw: Any) -> None:
        """DELETE (404 ignored when allow_404)."""
        self.request("DELETE", path, allow=(404,) if allow_404 else (), **kw)

    def graphql(self, query: str, variables: Mapping[str, Any] | None = None, *, allow_errors: bool = False) -> dict:
        """POST /graphql; returns ``data`` (GitHubError on ``errors`` unless allow_errors)."""
        body = self.post("/graphql", json={"query": query, "variables": dict(variables or {})}) or {}
        if body.get("errors") and not allow_errors:
            raise GitHubError(200, "POST", "https://api.github.com/graphql", json.dumps(body["errors"]))
        return body.get("data") or {}

    def oauth_scopes(self) -> set[str] | None:
        """The configured scopes."""
        return None if self.scopes is None else set(self.scopes)

    def token_info(self) -> TokenInfo:
        """The configured kind, scopes and expiration."""
        kind = self.token_kind or (CLASSIC if self.scopes is not None else FINE_GRAINED)
        scopes = None if self.scopes is None or kind != CLASSIC else frozenset(self.scopes)
        header = None if self.expires_at is None else self.expires_at.strftime("%Y-%m-%d %H:%M:%S UTC")
        return TokenInfo(kind, scopes, self.expires_at, header)

    def rate_snapshot(self) -> dict[str, Any]:
        """A static core budget."""
        return {"core": {"remaining": self.rate_remaining, "limit": 5000}}

    def rate_limit(self) -> dict:
        """GET /rate_limit equivalent."""
        return {"resources": {"core": {"remaining": self.rate_remaining, "limit": 5000}}}


def json_dumps(body: Any) -> bytes:
    """UTF-8 JSON bytes of a fake response body."""
    return json.dumps(body).encode("utf-8")


# --- FakeOracle ----------------------------------------------------------------------------------------------------
ORACLE_METHODS = frozenset(
    name for name in vars(Oracle) if not name.startswith("_") and callable(getattr(Oracle, name)) and name != "lookup"
)


class FakeOracle:
    """Dict-backed stand-in for github.oracle.Oracle (same method names, same None/[] semantics).

    Values are stored per (method, args): ``set("repo", "x", value={...})``; single lookups also search the matching
    list (repo() in repos(), team() in teams(), *_by_url() in hooks by config.url, ...). Every call is recorded in
    ``calls``; ``mark_unavailable(method, *args)`` makes a list lookup answer [] and record ``unavailable``.
    """

    def __init__(self, org: str = FAKE_ORG, *, org_id: int = FAKE_ORG_ID, plan: str = "free") -> None:
        """Create an empty fake for ``org`` (org() answers default_org_json until set)."""
        self.org_login = org
        self.org_id = org_id
        self.http: Any = None
        self.unavailable: dict[tuple[str, str], int] = {}
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._values: dict[tuple[str, tuple[Any, ...]], Any] = {}
        self._unavailable: dict[tuple[str, tuple[Any, ...]], int] = {}
        self._ids = itertools.count(1000)
        self.set("org", value=default_org_json(org, org_id=org_id, plan=plan))

    # --- storage ------------------------------------------------------------------------------------------------
    def set(self, method: str, *args: Any, value: Any) -> FakeOracle:
        """Store the answer of ``method(*args)`` (deep-copied)."""
        if method not in ORACLE_METHODS:
            raise AttributeError(f"Oracle has no lookup {method!r}")
        self._values[(method, args)] = copy.deepcopy(value)
        return self

    def remove(self, method: str, *args: Any) -> None:
        """Forget the stored answer of ``method(*args)``."""
        self._values.pop((method, args), None)

    def mark_unavailable(self, method: str, *args: Any, status: int = 404) -> None:
        """Make the list lookup ``method(*args)`` behave like a 403/404 listing."""
        self._unavailable[(method, args)] = status

    def _record(self, method: str, args: tuple[Any, ...]) -> None:
        """Remember a call."""
        self.calls.append((method, args))

    def _single(self, method: str, *args: Any) -> Any:
        """Stored single-object answer or None."""
        self._record(method, args)
        value = self._values.get((method, args))
        return copy.deepcopy(value)

    def _has(self, method: str, *args: Any) -> bool:
        """True when an answer is stored for ``method(*args)``."""
        return (method, args) in self._values

    def _list(self, method: str, *args: Any) -> list[Any]:
        """Stored list answer or [] (unavailable lookups record their status)."""
        self._record(method, args)
        status = self._unavailable.get((method, args))
        if status is not None:
            self.unavailable[(method, "/".join(str(a) for a in args) or self.org_login)] = status
            return []
        return copy.deepcopy(self._values.get((method, args), []))

    def _feature(self, method: str, *args: Any) -> Any:
        """Stored feature setting or None; mark_unavailable(method, *args) answers None and records the status."""
        status = self._unavailable.get((method, args))
        if status is not None:
            self._record(method, args)
            self.unavailable[(method, "/".join(str(a) for a in args) or self.org_login)] = status
            return None
        return self._single(method, *args)

    def _items(self, method: str, prefix: tuple[Any, ...] = ()) -> list[Any]:
        """Items of every stored list of ``method`` whose arguments start with ``prefix`` (no call recorded)."""
        return [
            copy.deepcopy(item)
            for (name, args), items in self._values.items()
            if name == method and args[: len(prefix)] == prefix and isinstance(items, list)
            for item in items
        ]

    def _find(self, method: str, args: tuple[Any, ...], items: Iterable[Any], match: Callable[[Any], bool]) -> Any:
        """Explicit answer of method(*args), else the first matching list item, else None."""
        if self._has(method, *args):
            return self._single(method, *args)
        self._record(method, args)
        return next((copy.deepcopy(item) for item in items if match(item)), None)

    def _append(self, method: str, args: tuple[Any, ...], item: Mapping[str, Any]) -> dict[str, Any]:
        """Append ``item`` to the stored list of method(*args)."""
        items = self._values.setdefault((method, args), [])
        items.append(dict(item))
        return dict(item)

    # --- builders -----------------------------------------------------------------------------------------------
    def add_repo(self, name: str, **fields: Any) -> dict[str, Any]:
        """Add a repository to repos() (defaults: public, default branch main)."""
        repo = {
            "id": next(self._ids),
            "name": name,
            "full_name": f"{self.org_login}/{name}",
            "private": False,
            "archived": False,
            "default_branch": "main",
            "description": None,
            **fields,
        }
        return self._append("repos", (), repo)

    def remove_repo(self, name: str) -> None:
        """Remove a repository from repos() (and its explicit repo() answer)."""
        repos = self._values.get(("repos", ()), [])
        self._values[("repos", ())] = [r for r in repos if r.get("name") != name]
        self.remove("repo", name)

    def add_team(self, slug: str, *, members: Sequence[str] = (), **fields: Any) -> dict[str, Any]:
        """Add a team to teams() and its members to team_members(slug)."""
        team = {"id": next(self._ids), "slug": slug, "name": fields.pop("name", slug), "privacy": "closed", **fields}
        self.set("team_members", slug, value=list(members))
        return self._append("teams", (), team)

    def remove_team(self, slug: str) -> None:
        """Remove a team from teams()."""
        teams = self._values.get(("teams", ()), [])
        self._values[("teams", ())] = [t for t in teams if t.get("slug") != slug]
        self.remove("team", slug)

    def add_org_hook(self, url: str, **fields: Any) -> dict[str, Any]:
        """Add an org webhook with config.url == url."""
        hook = {"id": next(self._ids), "active": True, "events": ["push"], "config": {"url": url}, **fields}
        return self._append("org_hooks", (), hook)

    def add_repo_hook(self, repo: str, url: str, **fields: Any) -> dict[str, Any]:
        """Add a repo webhook with config.url == url."""
        hook = {"id": next(self._ids), "active": True, "events": ["push"], "config": {"url": url}, **fields}
        return self._append("repo_hooks", (repo,), hook)

    def add_file(self, repo: str, path: str, content: str, *, ref: str | None = None) -> None:
        """Make file_content(repo, path, ref) return ``content``."""
        self.set("file_content", repo, path, ref, value=content)

    def add_status(self, repo: str, sha: str, context: str, state: str, description: str = "") -> dict[str, Any]:
        """Add a commit status (newest first) to combined_status(repo, sha)."""
        combined = self._values.setdefault(("combined_status", (repo, sha)), {"sha": sha, "statuses": []})
        status = {"context": context, "state": state, "description": description, "id": next(self._ids)}
        combined["statuses"] = [s for s in combined["statuses"] if s["context"] != context]
        combined["statuses"].insert(0, status)
        combined["state"] = state
        return dict(status)

    def add_pull(self, repo: str, pull: Mapping[str, Any], *, state: str = "open") -> dict[str, Any]:
        """Add a pull request (needs ``number``) to pulls(repo, state)."""
        return self._append("pulls", (repo, state), pull)

    def add_pr_comment(self, repo: str, number: int, body: str, *, author: str = "otterdog-e2e-app") -> dict[str, Any]:
        """Add a PR comment (pr_comments shape: id, author, body, is_minimized, ...)."""
        database_id = next(self._ids)
        comment = {
            "id": f"IC_{database_id}",
            "database_id": database_id,
            "author": author.removesuffix("[bot]"),
            "body": body,
            "is_minimized": False,
            "minimized_reason": None,
            "created_at": datetime.now(UTC).isoformat(),
        }
        return self._append("pr_comments", (repo, number), comment)

    def add_branch(self, repo: str, name: str, *, sha: str | None = None, protected: bool = False) -> dict[str, Any]:
        """Add a branch to repo_branches(repo); repo_branch(repo, name) and branch_sha(repo, name) answer it."""
        head = sha or fake_sha((repo, name))
        branch = {"name": name, "commit": {"sha": head}, "protected": protected}
        names = self._values.setdefault(("repo_branches", (repo,)), [])
        if name not in names:
            names.append(name)
        self.set("repo_branch", repo, name, value=branch)
        self.set("branch_sha", repo, name, value=head)
        return copy.deepcopy(branch)

    def add_workflow_run(self, repo: str, workflow: str, **fields: Any) -> dict[str, Any]:
        """Add a run (newest first) to workflow_runs(repo, workflow); defaults: queued workflow_dispatch run on main."""
        run = {
            "id": next(self._ids),
            "name": workflow,
            "path": f".github/workflows/{workflow}",
            "event": "workflow_dispatch",
            "status": "queued",
            "conclusion": None,
            "head_branch": "main",
            "head_sha": fake_sha((repo, workflow)),
            "run_attempt": 1,
            **fields,
        }
        self._values.setdefault(("workflow_runs", (repo, workflow)), []).insert(0, run)
        return copy.deepcopy(run)

    def add_security_advisory(self, repo: str, *, summary: str, state: str = "draft", **fields: Any) -> dict[str, Any]:
        """Add a repository security advisory (newest first) to repo_security_advisories(repo)."""
        number = next(self._ids)
        advisory = {
            "ghsa_id": f"GHSA-{number:04d}-e2e0-0000",
            "summary": summary,
            "state": state,
            "severity": "low",
            "private_fork": None,
            **fields,
        }
        self._values.setdefault(("repo_security_advisories", (repo,)), []).insert(0, advisory)
        return copy.deepcopy(advisory)

    def add_code_security_configuration(
        self, name: str, *, default_for_new_repos: str | None = None, **fields: Any
    ) -> dict[str, Any]:
        """Add an org code security configuration; a default_for_new_repos other than none also makes it a default."""
        configuration = {"id": next(self._ids), "name": name, "target_type": "organization", **fields}
        self._append("code_security_configurations", (), configuration)
        if default_for_new_repos not in (None, "none"):
            entry = {"default_for_new_repos": default_for_new_repos, "configuration": copy.deepcopy(configuration)}
            self._append("code_security_default_configurations", (), entry)
        return copy.deepcopy(configuration)

    # --- organization -------------------------------------------------------------------------------------------
    def org(self) -> dict[str, Any]:
        """Stored org (default_org_json by default)."""
        return self._single("org")

    def plan_name(self) -> str | None:
        """plan.name of org() unless set."""
        if self._has("plan_name"):
            return self._single("plan_name")
        return (self.org() or {}).get("plan", {}).get("name")

    def org_actions_permissions(self) -> dict[str, Any] | None:
        """Stored value or None."""
        return self._single("org_actions_permissions")

    def org_workflow_permissions(self) -> dict[str, Any] | None:
        """Stored value or None."""
        return self._single("org_workflow_permissions")

    def org_selected_actions(self) -> dict[str, Any] | None:
        """Stored feature value or None (mark_unavailable records the status)."""
        return self._feature("org_selected_actions")

    def org_actions_selected_repositories(self) -> list[str]:
        """Stored list or []."""
        return self._list("org_actions_selected_repositories")

    def org_fork_pr_approval(self) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("org_fork_pr_approval")

    def org_fork_pr_workflows_private_repos(self) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("org_fork_pr_workflows_private_repos")

    def org_cache_storage_limit(self) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("org_cache_storage_limit")

    def org_cache_storage_limit_orgs_path(self) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("org_cache_storage_limit_orgs_path")

    def org_role_teams(self, name: str) -> list[str]:
        """Stored list or []."""
        return self._list("org_role_teams", name)

    def security_managers(self) -> list[str]:
        """Stored list, else org_role_teams('security_manager')."""
        if self._has("security_managers") or ("security_managers", ()) in self._unavailable:
            return self._list("security_managers")
        return self.org_role_teams("security_manager")

    def code_security_configurations(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("code_security_configurations")

    def code_security_configuration(self, name: str) -> dict[str, Any] | None:
        """Explicit value or the code_security_configurations() entry named ``name``."""
        items = self.code_security_configurations()
        return self._find("code_security_configuration", (name,), items, lambda c: c.get("name") == name)

    def code_security_default_configurations(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("code_security_default_configurations")

    def members_with_role(self) -> list[dict[str, Any]]:
        """Stored list ([{login, role}]) or []."""
        return self._list("members_with_role")

    def members_2fa_disabled(self) -> list[str]:
        """Stored list or []."""
        return self._list("members_2fa_disabled")

    def org_invitations(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("org_invitations")

    def org_security_advisories(self) -> list[dict[str, Any]]:
        """Stored list, else the advisories of every repository."""
        if self._has("org_security_advisories") or ("org_security_advisories", ()) in self._unavailable:
            return self._list("org_security_advisories")
        self._record("org_security_advisories", ())
        return self._items("repo_security_advisories")

    def org_secrets(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("org_secrets")

    def org_secret(self, name: str) -> dict[str, Any] | None:
        """Explicit value or the org_secrets() entry named ``name``."""
        return self._find("org_secret", (name,), self.org_secrets(), lambda s: s.get("name") == name)

    def org_secret_repositories(self, name: str) -> list[str]:
        """Stored list or []."""
        return self._list("org_secret_repositories", name)

    def org_variables(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("org_variables")

    def org_variable(self, name: str) -> dict[str, Any] | None:
        """Explicit value or the org_variables() entry named ``name``."""
        return self._find("org_variable", (name,), self.org_variables(), lambda v: v.get("name") == name)

    def org_variable_repositories(self, name: str) -> list[str]:
        """Stored list or []."""
        return self._list("org_variable_repositories", name)

    def org_hooks(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("org_hooks")

    def org_hook_by_url(self, url: str) -> dict[str, Any] | None:
        """Explicit value or the org hook whose config.url == url."""
        return self._find("org_hook_by_url", (url,), self.org_hooks(), lambda h: h.get("config", {}).get("url") == url)

    def org_hook_deliveries(self, hook_id: int) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("org_hook_deliveries", hook_id)

    def org_hook_deliveries_by_url(self, url: str) -> list[dict[str, Any]]:
        """Deliveries of the org hook whose config.url == url ([] without such a hook)."""
        hook = self.org_hook_by_url(url)
        return [] if hook is None else self.org_hook_deliveries(hook["id"])

    def org_hook_delivery(self, hook_id: int, delivery_id: int) -> dict[str, Any] | None:
        """Explicit value or the org_hook_deliveries(hook_id) entry with this id."""
        items = self.org_hook_deliveries(hook_id)
        return self._find("org_hook_delivery", (hook_id, delivery_id), items, lambda d: d.get("id") == delivery_id)

    def org_hook_latest_delivery_by_url(self, url: str, event: str) -> dict[str, Any] | None:
        """The newest ``event`` delivery of the org hook with this URL (org_hook_delivery), None without one."""
        hook = self.org_hook_by_url(url)
        if hook is None:
            return None
        found = next((d for d in self.org_hook_deliveries(hook["id"]) if d.get("event") == event), None)
        return None if found is None else self.org_hook_delivery(hook["id"], found["id"])

    def org_rulesets(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("org_rulesets")

    def org_ruleset(self, name: str) -> dict[str, Any] | None:
        """Explicit value or the org_rulesets() entry named ``name``."""
        return self._find("org_ruleset", (name,), self.org_rulesets(), lambda r: r.get("name") == name)

    def custom_properties(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("custom_properties")

    def custom_property(self, name: str) -> dict[str, Any] | None:
        """Explicit value or the custom_properties() entry with property_name ``name``."""
        items = self.custom_properties()
        return self._find("custom_property", (name,), items, lambda p: p.get("property_name") == name)

    def org_roles(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("org_roles")

    def org_role(self, name: str) -> dict[str, Any] | None:
        """Explicit value or the org_roles() entry named ``name``."""
        return self._find("org_role", (name,), self.org_roles(), lambda r: r.get("name") == name)

    def members(self) -> list[str]:
        """Stored list or []."""
        return self._list("members")

    def membership(self, login: str) -> dict[str, Any] | None:
        """Stored value or None."""
        return self._single("membership", login)

    # --- teams --------------------------------------------------------------------------------------------------
    def teams(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("teams")

    def team(self, slug: str) -> dict[str, Any] | None:
        """Explicit value or the teams() entry with this slug."""
        return self._find("team", (slug,), self.teams(), lambda t: t.get("slug") == slug)

    def team_members(self, slug: str) -> list[str]:
        """Stored list or []."""
        return self._list("team_members", slug)

    def team_membership(self, slug: str, login: str) -> dict[str, Any] | None:
        """Explicit value, else an active member membership when ``login`` is in team_members(slug), else None."""
        if self._has("team_membership", slug, login):
            return self._single("team_membership", slug, login)
        self._record("team_membership", (slug, login))
        return {"role": "member", "state": "active"} if login in self.team_members(slug) else None

    def team_invitations(self, slug: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("team_invitations", slug)

    def team_repo_permission(self, slug: str, repo: str) -> str | None:
        """Stored value or None."""
        return self._single("team_repo_permission", slug, repo)

    # --- repositories -------------------------------------------------------------------------------------------
    def repos(self) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repos")

    def repo(self, name: str) -> dict[str, Any] | None:
        """Explicit value or the repos() entry named ``name``."""
        return self._find("repo", (name,), self.repos(), lambda r: r.get("name") == name)

    def repo_topics(self, name: str) -> list[str]:
        """Stored list, else the topics of repo(name), else []."""
        if self._has("repo_topics", name):
            return self._list("repo_topics", name)
        return list((self.repo(name) or {}).get("topics", []))

    def repo_actions_permissions(self, name: str) -> dict[str, Any] | None:
        """Stored value or None."""
        return self._single("repo_actions_permissions", name)

    def repo_workflow_permissions(self, name: str) -> dict[str, Any] | None:
        """Stored value or None."""
        return self._single("repo_workflow_permissions", name)

    def repo_selected_actions(self, repo: str) -> dict[str, Any] | None:
        """Stored feature value or None (mark_unavailable records the status)."""
        return self._feature("repo_selected_actions", repo)

    def repo_fork_pr_approval(self, repo: str) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("repo_fork_pr_approval", repo)

    def repo_fork_pr_workflows_private_repos(self, repo: str) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("repo_fork_pr_workflows_private_repos", repo)

    def repo_cache_storage_limit(self, repo: str) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("repo_cache_storage_limit", repo)

    def repo_security_and_analysis(self, repo: str) -> dict[str, Any] | None:
        """Explicit value or repo(repo).security_and_analysis (None without it)."""
        if self._has("repo_security_and_analysis", repo):
            return self._single("repo_security_and_analysis", repo)
        block = (self.repo(repo) or {}).get("security_and_analysis")
        return block if isinstance(block, dict) else None

    def _enabled_flag(self, method: str, repo: str) -> dict[str, Any] | None:
        """Explicit value, else {enabled: False} for an existing repository, else None."""
        if self._has(method, repo):
            return self._single(method, repo)
        self._record(method, (repo,))
        return None if self.repo(repo) is None else {"enabled": False}

    def repo_vulnerability_alerts(self, repo: str) -> dict[str, Any] | None:
        """Explicit value, else {enabled: False} for an existing repository, else None."""
        return self._enabled_flag("repo_vulnerability_alerts", repo)

    def repo_automated_security_fixes(self, repo: str) -> dict[str, Any] | None:
        """Explicit value, else {enabled: False} for an existing repository, else None."""
        return self._enabled_flag("repo_automated_security_fixes", repo)

    def repo_private_vulnerability_reporting(self, repo: str) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("repo_private_vulnerability_reporting", repo)

    def repo_code_scanning_default_setup(self, repo: str) -> dict[str, Any] | None:
        """Stored feature value or None."""
        return self._feature("repo_code_scanning_default_setup", repo)

    def repo_security_advisories(self, repo: str) -> list[dict[str, Any]]:
        """Stored list (add_security_advisory) or []."""
        return self._list("repo_security_advisories", repo)

    def repo_security_advisory(self, repo: str, ghsa_id: str) -> dict[str, Any] | None:
        """Explicit value or the repo_security_advisories(repo) entry with this ghsa_id."""
        items = self.repo_security_advisories(repo)
        return self._find("repo_security_advisory", (repo, ghsa_id), items, lambda a: a.get("ghsa_id") == ghsa_id)

    def repo_languages(self, repo: str) -> dict[str, int] | None:
        """Stored value (set), else {} for a stored repository, else None."""
        if self._has("repo_languages", repo):
            return self._single("repo_languages", repo)
        self._record("repo_languages", (repo,))
        return {} if self.repo(repo) is not None else None

    def repo_branches(self, repo: str) -> list[str]:
        """Stored branch names (add_branch) or []."""
        return self._list("repo_branches", repo)

    def repo_branch(self, repo: str, branch: str) -> dict[str, Any] | None:
        """Explicit value (add_branch), else a plain branch when repo_branches(repo) lists it, else None."""
        if self._has("repo_branch", repo, branch):
            return self._single("repo_branch", repo, branch)
        self._record("repo_branch", (repo, branch))
        if branch not in self.repo_branches(repo):
            return None
        return {"name": branch, "commit": {"sha": fake_sha((repo, branch))}, "protected": False}

    def repo_teams(self, repo: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repo_teams", repo)

    def repo_collaborators(self, repo: str) -> list[dict[str, Any]]:
        """Stored list ([{login, role_name, ...}]) or []."""
        return self._list("repo_collaborators", repo)

    def repo_collaborator_permission(self, repo: str, login: str) -> dict[str, Any] | None:
        """Explicit value, else derived from the repo_collaborators(repo) entry of ``login``, else None."""
        if self._has("repo_collaborator_permission", repo, login):
            return self._single("repo_collaborator_permission", repo, login)
        self._record("repo_collaborator_permission", (repo, login))
        entry = next((c for c in self.repo_collaborators(repo) if c.get("login") == login), None)
        if entry is None:
            return None
        role = entry.get("role_name", "write")
        legacy = {"maintain": "write", "triage": "read"}.get(role, role)
        return {"permission": legacy, "role_name": role, "user": {"login": login}}

    def repo_invitations(self, repo: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repo_invitations", repo)

    def workflow(self, repo: str, workflow: str) -> dict[str, Any] | None:
        """Stored value or None."""
        return self._single("workflow", repo, workflow)

    def workflow_runs(self, repo: str, workflow: str) -> list[dict[str, Any]]:
        """Stored runs (add_workflow_run, newest first) or []."""
        return self._list("workflow_runs", repo, workflow)

    def repo_workflow_runs(self, repo: str) -> list[dict[str, Any]]:
        """Stored list, else the runs of every workflow of the repository, newest (highest id) first."""
        if self._has("repo_workflow_runs", repo) or ("repo_workflow_runs", (repo,)) in self._unavailable:
            return self._list("repo_workflow_runs", repo)
        self._record("repo_workflow_runs", (repo,))
        return sorted(self._items("workflow_runs", (repo,)), key=lambda run: -int(run.get("id", 0)))

    def find_workflow_runs(
        self,
        repo: str,
        *,
        workflow: str | None = None,
        event: str | None = None,
        branch: str | None = None,
        status: str | None = None,
        head_sha: str | None = None,
        created: str | None = None,
    ) -> list[dict[str, Any]]:
        """workflow_runs / repo_workflow_runs filtered on event, head_branch, status or conclusion, head_sha
        (``created`` is recorded but not evaluated)."""
        self._record("find_workflow_runs", (repo, workflow, event, branch, status, head_sha, created))
        runs = self.workflow_runs(repo, workflow) if workflow else self.repo_workflow_runs(repo)
        wanted = {"event": event, "head_branch": branch, "head_sha": head_sha}
        return [
            run
            for run in runs
            if all(value is None or run.get(key) == value for key, value in wanted.items())
            and (status is None or status in (run.get("status"), run.get("conclusion")))
        ]

    def workflow_run(self, repo: str, run_id: int) -> dict[str, Any] | None:
        """Explicit value or the run with this id among the runs of the repository."""
        if self._has("workflow_run", repo, run_id):
            return self._single("workflow_run", repo, run_id)
        self._record("workflow_run", (repo, run_id))
        return next((run for run in self._items("workflow_runs", (repo,)) if run.get("id") == run_id), None)

    def workflow_run_jobs(self, repo: str, run_id: int) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("workflow_run_jobs", repo, run_id)

    def _update_run(self, repo: str, run_id: int, **fields: Any) -> None:
        """Change the fields of a stored run (every list holding it)."""
        for (method, args), items in self._values.items():
            if method == "workflow_runs" and args[0] == repo and isinstance(items, list):
                for run in items:
                    if run.get("id") == run_id:
                        run.update(fields)

    def repo_secrets(self, name: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repo_secrets", name)

    def repo_secret(self, repo: str, name: str) -> dict[str, Any] | None:
        """Explicit value or the repo_secrets(repo) entry named ``name``."""
        return self._find("repo_secret", (repo, name), self.repo_secrets(repo), lambda s: s.get("name") == name)

    def repo_variables(self, name: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repo_variables", name)

    def repo_variable(self, repo: str, name: str) -> dict[str, Any] | None:
        """Explicit value or the repo_variables(repo) entry named ``name``."""
        return self._find("repo_variable", (repo, name), self.repo_variables(repo), lambda v: v.get("name") == name)

    def repo_hooks(self, name: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repo_hooks", name)

    def repo_hook_by_url(self, repo: str, url: str) -> dict[str, Any] | None:
        """Explicit value or the repo hook whose config.url == url."""
        hooks = self.repo_hooks(repo)
        return self._find("repo_hook_by_url", (repo, url), hooks, lambda h: h.get("config", {}).get("url") == url)

    def repo_hook_deliveries(self, repo: str, hook_id: int) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repo_hook_deliveries", repo, hook_id)

    def repo_hook_deliveries_by_url(self, repo: str, url: str) -> list[dict[str, Any]]:
        """Deliveries of the repo hook whose config.url == url ([] without such a hook)."""
        hook = self.repo_hook_by_url(repo, url)
        return [] if hook is None else self.repo_hook_deliveries(repo, hook["id"])

    def repo_hook_delivery(self, repo: str, hook_id: int, delivery_id: int) -> dict[str, Any] | None:
        """Explicit value or the repo_hook_deliveries(repo, hook_id) entry with this id."""
        items = self.repo_hook_deliveries(repo, hook_id)
        args = (repo, hook_id, delivery_id)
        return self._find("repo_hook_delivery", args, items, lambda d: d.get("id") == delivery_id)

    def repo_hook_latest_delivery_by_url(self, repo: str, url: str, event: str) -> dict[str, Any] | None:
        """The newest ``event`` delivery of the repo hook with this URL (repo_hook_delivery), None without one."""
        hook = self.repo_hook_by_url(repo, url)
        if hook is None:
            return None
        found = next((d for d in self.repo_hook_deliveries(repo, hook["id"]) if d.get("event") == event), None)
        return None if found is None else self.repo_hook_delivery(repo, hook["id"], found["id"])

    def branch_protection_rules(self, repo: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("branch_protection_rules", repo)

    def branch_protection_rule(self, repo: str, pattern: str) -> dict[str, Any] | None:
        """Explicit value or the rule with this pattern."""
        rules = self.branch_protection_rules(repo)
        return self._find("branch_protection_rule", (repo, pattern), rules, lambda r: r.get("pattern") == pattern)

    def repo_rulesets(self, repo: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("repo_rulesets", repo)

    def repo_ruleset(self, repo: str, name: str) -> dict[str, Any] | None:
        """Explicit value or the repo_rulesets(repo) entry named ``name``."""
        return self._find("repo_ruleset", (repo, name), self.repo_rulesets(repo), lambda r: r.get("name") == name)

    def environments(self, repo: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("environments", repo)

    def environment(self, repo: str, name: str) -> dict[str, Any] | None:
        """Explicit value or the environments(repo) entry named ``name``."""
        return self._find("environment", (repo, name), self.environments(repo), lambda e: e.get("name") == name)

    def environment_branch_policies(self, repo: str, env: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("environment_branch_policies", repo, env)

    def environment_secrets(self, repo: str, env: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("environment_secrets", repo, env)

    def environment_secret(self, repo: str, env: str, name: str) -> dict[str, Any] | None:
        """Explicit value or the environment_secrets entry named ``name``."""
        items = self.environment_secrets(repo, env)
        return self._find("environment_secret", (repo, env, name), items, lambda s: s.get("name") == name)

    def environment_variables(self, repo: str, env: str) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("environment_variables", repo, env)

    def environment_variable(self, repo: str, env: str, name: str) -> dict[str, Any] | None:
        """Explicit value or the environment_variables entry named ``name``."""
        items = self.environment_variables(repo, env)
        return self._find("environment_variable", (repo, env, name), items, lambda v: v.get("name") == name)

    def pages(self, repo: str) -> dict[str, Any] | None:
        """Stored value or None."""
        return self._single("pages", repo)

    def repo_custom_property_values(self, repo: str) -> dict[str, Any]:
        """Stored mapping or {}."""
        return self._single("repo_custom_property_values", repo) or {}

    # --- git and pull requests ----------------------------------------------------------------------------------
    def default_branch(self, repo: str) -> str | None:
        """Explicit value or repo(repo).default_branch."""
        if self._has("default_branch", repo):
            return self._single("default_branch", repo)
        return (self.repo(repo) or {}).get("default_branch")

    def branch_sha(self, repo: str, branch: str) -> str | None:
        """Stored value or None."""
        return self._single("branch_sha", repo, branch)

    def matching_refs(self, repo: str, prefix: str) -> list[dict[str, Any]]:
        """Stored refs of (repo, prefix without ``refs/``) or []."""
        return self._list("matching_refs", repo, prefix.removeprefix("refs/"))

    def git_commit(self, repo: str, sha: str) -> dict[str, Any] | None:
        """Stored commit or None."""
        return self._single("git_commit", repo, sha)

    def file_content(self, repo: str, path: str, ref: str | None = None) -> str | None:
        """Stored content for (repo, path, ref), falling back to ref None."""
        if self._has("file_content", repo, path, ref):
            return self._single("file_content", repo, path, ref)
        return self._single("file_content", repo, path, None)

    def pull(self, repo: str, number: int) -> dict[str, Any] | None:
        """Explicit value or the pulls(repo, state) entry with this number (any state)."""
        if self._has("pull", repo, number):
            return self._single("pull", repo, number)
        self._record("pull", (repo, number))
        for (method, args), items in self._values.items():
            if method == "pulls" and args[0] == repo:
                found = next((p for p in items if p.get("number") == number), None)
                if found:
                    return copy.deepcopy(found)
        return None

    def pulls(self, repo: str, state: str = "open") -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("pulls", repo, state)

    def combined_status(self, repo: str, sha: str) -> dict[str, Any]:
        """Stored combined status or an empty pending one."""
        return self._single("combined_status", repo, sha) or {"sha": sha, "state": "pending", "statuses": []}

    def latest_status(self, repo: str, sha: str, context: str) -> dict[str, Any] | None:
        """Explicit value or the newest combined_status entry of ``context``."""
        statuses = self.combined_status(repo, sha).get("statuses", [])
        return self._find("latest_status", (repo, sha, context), statuses, lambda s: s.get("context") == context)

    def commit_statuses(self, repo: str, ref: str) -> list[dict[str, Any]]:
        """Stored list (newest first) or []."""
        return self._list("commit_statuses", repo, ref)

    def issue_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("issue_comments", repo, number)

    def pr_comments(self, repo: str, number: int) -> list[dict[str, Any]]:
        """Stored list or []."""
        return self._list("pr_comments", repo, number)

    def lookup(self, kind: str, **params: Any) -> Any:
        """Dispatch through scenarios.checks.CHECK_KINDS like the real Oracle (KeyError for unknown kinds)."""
        from otterdog_e2e.scenarios.checks import CHECK_KINDS

        method, names = CHECK_KINDS[kind]
        missing = [name for name in names if name not in params]
        if missing:
            raise TypeError(f"check kind {kind!r} needs parameter(s) {missing}")
        return getattr(self, method)(*(params[name] for name in names))


# --- FakeCli -------------------------------------------------------------------------------------------------------
@dataclass
class CliCall:
    """One FakeCli invocation: command name, positional args and keyword options."""

    command: str
    args: tuple[str, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


class FakeCli:
    """OtterdogCli stand-in: each command pops the next queued CliResult (default: DEFAULT_OUTPUTS, exit 0).

    ``queue(command, stdout=..., exit_code=...)`` accepts a CliResult or builds one; ``check_status`` results may
    carry the status dict to return. ``strict`` raises AssertionError when a command has nothing queued.
    ``plan_with`` / ``apply_with`` / ``local_plan_with`` are recorded (and queued) under their command with the
    DiffOptions (``options``) and its fields; ``invoke`` under its first argument (``""`` without one).
    """

    def __init__(
        self,
        *,
        org: str = FAKE_ORG,
        workspace: Any = None,
        strict: bool = False,
        web: Any = None,
        installed: Any = None,
    ) -> None:
        """Create a fake CLI for ``org`` (``workspace``, ``web`` and ``installed`` are exposed like the OtterdogCli
        attributes: any object as ``web`` makes a web-mode stand-in, ``installed.sut.trusted`` its trust)."""
        self.org = org
        self.workspace = workspace
        self.strict = strict
        self.web = web
        self.installed = installed
        self.calls: list[CliCall] = []
        self._queues: dict[str, list[tuple[CliResult, dict[str, Any] | None]]] = {}

    def queue(
        self,
        command: str,
        result: CliResult | None = None,
        *,
        stdout: str = "",
        stderr: str = "",
        exit_code: int = 0,
        status: dict[str, Any] | None = None,
        timed_out: bool = False,
        infra_error: str | None = None,
    ) -> CliResult:
        """Queue the next result of ``command`` (e.g. "plan", "local-plan", "--version")."""
        if result is None:
            result = cli_result(
                command, stdout, exit_code=exit_code, stderr=stderr, timed_out=timed_out, infra_error=infra_error
            )
        self._queues.setdefault(command, []).append((result, status))
        return result

    def calls_to(self, command: str) -> list[CliCall]:
        """Recorded invocations of ``command``."""
        return [call for call in self.calls if call.command == command]

    def pending(self) -> dict[str, int]:
        """Number of queued, unconsumed results per command."""
        return {command: len(queue) for command, queue in self._queues.items() if queue}

    def http_cache_dir(self) -> Path:
        """A fixed (never created) HTTP cache path."""
        return FAKE_CLI_CWD / "http-cache"

    def _next(
        self, command: str, args: Sequence[str] = (), /, **kwargs: Any
    ) -> tuple[CliResult, dict[str, Any] | None]:
        """Record the call and pop its result."""
        self.calls.append(CliCall(command, tuple(args), dict(kwargs)))
        queue = self._queues.get(command)
        if queue:
            return queue.pop(0)
        if self.strict:
            raise AssertionError(f"FakeCli: no result queued for {command!r}")
        stdout = DEFAULT_OUTPUTS.get(command, "").replace("{org}", self.org)
        return cli_result(command, stdout, args=args), None

    def run(
        self,
        command: str,
        *args: str,
        org: bool = True,
        input: str | None = None,
        timeout: float | None = None,
        local: bool = False,
        observe: str | None = None,
    ) -> CliResult:
        """Generic command."""
        return self._next(command, args, org=org, input=input, timeout=timeout, local=local, observe=observe)[0]

    def invoke(
        self,
        *args: str,
        input: str | None = None,
        timeout: float | None = None,
        config_root: bool = False,
        env: Mapping[str, str] | None = None,
        observe: str | None = None,
    ) -> CliResult:
        """Raw invocation, recorded and queued under its first argument (``""`` without arguments)."""
        options = {"input": input, "timeout": timeout, "config_root": config_root, "env": env, "observe": observe}
        return self._next(args[0] if args else "", args[1:], invoke=True, **options)[0]

    @staticmethod
    def _diff_kwargs(options: DiffOptions) -> dict[str, Any]:
        """Recorded keyword options of a DiffOptions call: the object and its fields."""
        fields = ("repo_filter", "update_webhooks", "update_secrets", "only_secrets", "update_filter", "verbose")
        return {"options": options, **{name: getattr(options, name) for name in fields}}

    def version(self) -> str:
        """stdout of the next --version result."""
        return self._next("--version")[0].stdout

    def validate(self, *, local: bool = False, verbose: bool = False, observe: str | None = None) -> CliResult:
        """validate."""
        return self._next("validate", local=local, verbose=verbose, observe=observe)[0]

    def plan(self, *, repo_filter: str | None = None, local: bool = False, observe: str | None = None) -> CliResult:
        """plan."""
        return self._next("plan", repo_filter=repo_filter, local=local, observe=observe)[0]

    def plan_with(self, options: DiffOptions, *, local: bool = False, observe: str | None = None) -> CliResult:
        """plan with DiffOptions (recorded as ``plan`` with the options and their fields)."""
        return self._next("plan", **self._diff_kwargs(options), local=local, observe=observe)[0]

    def apply(
        self,
        *,
        repo_filter: str | None = None,
        delete: bool = False,
        update_secrets: bool = False,
        update_webhooks: bool = False,
        local: bool = False,
        observe: str | None = None,
    ) -> CliResult:
        """apply."""
        options = {"update_secrets": update_secrets, "update_webhooks": update_webhooks, "local": local}
        return self._next("apply", repo_filter=repo_filter, delete=delete, observe=observe, **options)[0]

    def apply_with(
        self, options: DiffOptions, *, delete: bool = False, local: bool = False, observe: str | None = None
    ) -> CliResult:
        """apply with DiffOptions (recorded as ``apply`` with the options, their fields and ``delete``)."""
        return self._next("apply", **self._diff_kwargs(options), delete=delete, local=local, observe=observe)[0]

    def local_plan(self, *, suffix: str = "-BASE", local: bool = True, observe: str | None = None) -> CliResult:
        """local-plan."""
        return self._next("local-plan", suffix=suffix, local=local, observe=observe)[0]

    def local_plan_with(
        self, options: DiffOptions, *, suffix: str = "-BASE", local: bool = True, observe: str | None = None
    ) -> CliResult:
        """local-plan with DiffOptions (recorded as ``local-plan`` with the options, their fields and ``suffix``)."""
        return self._next("local-plan", **self._diff_kwargs(options), suffix=suffix, local=local, observe=observe)[0]

    def import_config(self, *, force: bool = True) -> CliResult:
        """import."""
        return self._next("import", force=force)[0]

    def push_config(self, *, message: str) -> CliResult:
        """push-config."""
        return self._next("push-config", message=message)[0]

    def fetch_config(self, *, ref: str | None = None, pull_request: int | None = None) -> CliResult:
        """fetch-config."""
        return self._next("fetch-config", ref=ref, pull_request=pull_request)[0]

    def open_pr(self, *, branch: str, title: str, author: str) -> CliResult:
        """open-pr."""
        return self._next("open-pr", branch=branch, title=title, author=author)[0]

    def check_status(self, json_file: Path) -> tuple[CliResult, dict | None]:
        """check-status: the queued result and its status dict (None unless queued)."""
        return self._next("check-status", json_file=json_file)

    def show(self, *, local: bool = True) -> CliResult:
        """show."""
        return self._next("show", local=local)[0]

    def show_default(self, *, local: bool = True) -> CliResult:
        """show-default."""
        return self._next("show-default", local=local)[0]

    def canonical_diff(self, *, local: bool = True) -> CliResult:
        """canonical-diff."""
        return self._next("canonical-diff", local=local)[0]

    def list_projects(self) -> CliResult:
        """list-projects."""
        return self._next("list-projects")[0]

    def list_members(self) -> CliResult:
        """list-members."""
        return self._next("list-members")[0]

    def check_token_permissions(self) -> CliResult:
        """check-token-permissions."""
        return self._next("check-token-permissions")[0]


# --- FakeWorkspace -------------------------------------------------------------------------------------------------
FAKE_WORKSPACE_ROOT = Path("/nonexistent/otterdog-e2e-fake-workspace")


class FakeWorkspace(ConfigWorkspace):
    """ConfigWorkspace stand-in: the real paths and layout logic (otterdog_e2e.otterdog.workspace), no disk I/O.

    Writes are recorded in memory: ``writes`` / ``base_writes`` (texts of the org and ``-BASE`` configs, every org),
    ``documents`` (configuration documents written, ``otterdog_json_writes`` counts them), ``files`` (path -> text of
    every file written, read back by read_org_config; config_texts() removals drop entries), ``cleaned``
    (clean_template_cache calls) and ``exports`` (export_to targets). The root defaults to a nonexistent directory,
    so ``config_file.exists()`` stays False.
    """

    def __init__(
        self,
        org: str = FAKE_ORG,
        *,
        root: Path = FAKE_WORKSPACE_ROOT,
        template: Any = None,
        config_repo: str = ".otterdog",
        project: str | None = None,
        base_url: str | None = None,
    ) -> None:
        """Bind to ``org`` (template: the offline placeholder template by default)."""
        from otterdog_e2e.sut.template import offline_template

        template = template if template is not None else offline_template()
        super().__init__(root, org=org, template=template, config_repo=config_repo, project=project, base_url=base_url)
        self.writes: list[str] = []
        self.base_writes: list[str] = []
        self.documents: list[dict[str, Any]] = []
        self.otterdog_json_writes = 0
        self.files: dict[Path, str] = {}
        self.cleaned = 0
        self.exports: list[Path] = []

    def write_otterdog_json(self) -> Path:
        """Record the configuration document and the files of config_texts()."""
        self.otterdog_json_writes += 1
        self.documents.append(self.otterdog_json())
        for path, text in self.config_texts().items():
            if text is None:
                self.files.pop(path, None)
            else:
                self.files[path] = text
        return self.config_file

    def write_org_config(self, text: str, *, org: str | None = None) -> Path:
        """Record the org config (of ``org``, default the workspace's)."""
        path = self.org_config_file_for(org or self.org)
        self.writes.append(text)
        self.files[path] = text
        return path

    def write_base_config(self, text: str, *, org: str | None = None, suffix: str = "-BASE") -> Path:
        """Record the -BASE config (or another ``suffix``)."""
        path = self.org_config_file_for(org or self.org, suffix=suffix)
        self.base_writes.append(text)
        self.files[path] = text
        return path

    def read_org_config(self, *, org: str | None = None) -> str:
        """The last org config recorded for ``org`` (FileNotFoundError when none was written)."""
        path = self.org_config_file_for(org or self.org)
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def clean_template_cache(self) -> None:
        """Count the call."""
        self.cleaned += 1

    def export_to(self, artifacts_dir: Path) -> None:
        """Record the target directory."""
        self.exports.append(artifacts_dir)


# --- RecordingMutator ----------------------------------------------------------------------------------------------
@dataclass
class MutatorCall:
    """One RecordingMutator invocation."""

    method: str
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)


class RecordingMutator:
    """Mutator stand-in: records calls, returns plausible values and (optionally) updates a FakeOracle.

    With ``guard`` (default) the SPEC 5.2 deletion guards are enforced (SafetyError): e2e names for deletions unless
    ``force``, naming.is_deletable_ref for delete_ref, HOOK_BASE URLs for hook deletions (when the oracle knows them).
    """

    def __init__(
        self, verified: VerifiedOrg | None = None, *, oracle: FakeOracle | None = None, guard: bool = True
    ) -> None:
        """Create a recorder for ``verified`` (default make_verified_org())."""
        self.verified = verified or make_verified_org()
        self.oracle = oracle
        self.guard = guard
        self.dry_run = False
        self.calls: list[MutatorCall] = []
        self._numbers = itertools.count(1)
        self._ids = itertools.count(5000)

    @property
    def org(self) -> str:
        """Login of the verified org."""
        return self.verified.login

    def calls_to(self, method: str) -> list[MutatorCall]:
        """Recorded calls of ``method``."""
        return [call for call in self.calls if call.method == method]

    def _record(self, name: str, /, *args: Any, **kwargs: Any) -> None:
        """Remember one call."""
        self.calls.append(MutatorCall(name, args, kwargs))

    def _check_name(self, kind: str, name: str, force: bool = False) -> None:
        """SafetyError for deleting a non-e2e name without force."""
        if self.guard and not force and not naming.is_e2e_name(name):
            raise SafetyError(f"refusing to delete {kind} {name!r}: not an e2e name")

    def _check_hook(self, hooks: Iterable[Mapping[str, Any]], hook_id: int) -> None:
        """SafetyError for deleting a hook whose known URL is outside HOOK_BASE."""
        hook = next((h for h in hooks if h.get("id") == hook_id), None)
        url = (hook or {}).get("config", {}).get("url", "")
        if self.guard and hook is not None and not url.startswith(naming.HOOK_BASE):
            raise SafetyError(f"refusing to delete hook {hook_id} with url {url!r}")

    def _require_e2e(self, kind: str, name: str) -> None:
        """SafetyError for a probe or drift write on a non-e2e object (Mutator._require_e2e)."""
        if self.guard and not naming.is_e2e_name(name):
            raise SafetyError(f"refusing to change {kind} {name!r}: not an e2e name")

    def _check_pull(self, repo: str, number: int) -> dict[str, Any]:
        """SafetyError when the oracle knows the pull request and its head is not a run branch (naming.branch_run_id,
        as Mutator._check_e2e_pull); returns it ({})."""
        pull = self.oracle.pull(repo, number) if self.oracle is not None else None
        ref = str(((pull or {}).get("head") or {}).get("ref") or "")
        if self.guard and pull is not None and naming.branch_run_id(ref) is None:
            raise SafetyError(f"refusing to change pull request {repo}#{number}: head {ref!r} is not a run branch")
        return dict(pull or {})

    def _update_pull(self, repo: str, number: int, **fields: Any) -> None:
        """Change fields of a pull request known to the oracle (every stored pulls(repo, state) list)."""
        if self.oracle is None:
            return
        for (method, args), items in self.oracle._values.items():
            if method == "pulls" and args[0] == repo and isinstance(items, list):
                for pull in items:
                    if pull.get("number") == number:
                        pull.update(fields)

    def _set_pull_draft(self, repo: str, number: int, draft: bool) -> None:
        """Change the draft flag of a pull request known to the oracle."""
        self._update_pull(repo, number, draft=draft)

    # --- git ----------------------------------------------------------------------------------------------------
    def create_branch(self, repo: str, branch: str, from_sha: str) -> None:
        """Record; the oracle's branch_sha(repo, branch) becomes from_sha."""
        self._record("create_branch", repo, branch, from_sha)
        if self.oracle is not None:
            self.oracle.set("branch_sha", repo, branch, value=from_sha)

    def delete_ref(self, repo: str, ref: str) -> None:
        """Record (guard: naming.is_deletable_ref)."""
        if self.guard and not naming.is_deletable_ref(ref):
            raise SafetyError(f"refusing to delete ref {ref!r}")
        self._record("delete_ref", repo, ref)

    def put_file(self, repo: str, path: str, content: str, message: str, *, branch: str, sha: str | None = None) -> str:
        """Record; returns a fake commit sha; the oracle serves the content on that branch."""
        self._record("put_file", repo, path, content, message, branch=branch, sha=sha)
        if self.oracle is not None:
            self.oracle.add_file(repo, path, content, ref=branch)
        return fake_sha(("put_file", repo, path, content, branch, len(self.calls)))

    def commit_files(self, repo: str, branch: str, files: Mapping[str, str | None], message: str) -> str:
        """Record; returns a fake commit sha; the oracle serves written files on that branch."""
        self._record("commit_files", repo, branch, dict(files), message)
        if self.oracle is not None:
            for path, content in files.items():
                if content is not None:
                    self.oracle.add_file(repo, path, content, ref=branch)
        return fake_sha(("commit_files", repo, branch, len(self.calls)))

    def create_commit(self, repo: str, *, tree_sha: str, parents: Sequence[str], message: str) -> str:
        """Record; returns a fake commit sha."""
        self._record("create_commit", repo, tree_sha=tree_sha, parents=list(parents), message=message)
        return fake_sha(("create_commit", repo, tree_sha, message, len(self.calls)))

    def create_ref(self, repo: str, ref: str, sha: str) -> dict[str, Any]:
        """Record; returns the ref object."""
        self._record("create_ref", repo, ref, sha)
        full_ref = ref if ref.startswith("refs/") else f"refs/{ref}"
        return {"ref": full_ref, "object": {"sha": sha, "type": "commit"}}

    def update_ref(self, repo: str, ref: str, sha: str, *, force: bool = False) -> None:
        """Record."""
        self._record("update_ref", repo, ref, sha, force=force)

    # --- pull requests ------------------------------------------------------------------------------------------
    def create_pull(
        self, repo: str, *, head: str, base: str, title: str, body: str = "", draft: bool = False
    ) -> dict[str, Any]:
        """Record; returns an open PR with an incrementing number (also added to the oracle's pulls)."""
        self._record("create_pull", repo, head=head, base=base, title=title, body=body, draft=draft)
        number = next(self._numbers)
        pull = {
            "number": number,
            "state": "open",
            "title": title,
            "body": body,
            "draft": draft,
            "merged": False,
            "html_url": f"https://github.com/{self.org}/{repo}/pull/{number}",
            "head": {"ref": head, "sha": fake_sha((repo, head, number))},
            "base": {"ref": base},
            "user": {"login": "e2e-admin"},
        }
        if self.oracle is not None:
            self.oracle.add_pull(repo, pull)
        return pull

    def comment(self, repo: str, number: int, body: str) -> dict[str, Any]:
        """Record; returns a comment."""
        self._record("comment", repo, number, body)
        comment_id = next(self._ids)
        return {"id": comment_id, "node_id": f"IC_{comment_id}", "body": body}

    def review(self, repo: str, number: int, *, event: str = "APPROVE", body: str = "") -> dict[str, Any]:
        """Record; returns a review."""
        self._record("review", repo, number, event=event, body=body)
        state = {"APPROVE": "APPROVED", "REQUEST_CHANGES": "CHANGES_REQUESTED"}.get(event, "COMMENTED")
        return {"id": next(self._ids), "state": state, "body": body}

    def merge_pull(self, repo: str, number: int, *, method: str = "squash", sha: str | None = None) -> dict[str, Any]:
        """Record; returns a merge result."""
        self._record("merge_pull", repo, number, method=method, sha=sha)
        return {"sha": fake_sha(("merge", repo, number)), "merged": True, "message": "Pull Request successfully merged"}

    def close_pull(self, repo: str, number: int) -> None:
        """Record."""
        self._record("close_pull", repo, number)

    def reopen_pull(self, repo: str, number: int) -> None:
        """Record (guard as dismiss_review); the oracle's pull request is open again."""
        self._check_pull(repo, number)
        self._record("reopen_pull", repo, number)
        self._update_pull(repo, number, state="open")

    def edit_comment(self, repo: str, comment_id: int, body: str) -> dict[str, Any]:
        """Record; returns the edited comment."""
        self._record("edit_comment", repo, comment_id, body)
        return {"id": comment_id, "node_id": f"IC_{comment_id}", "body": body}

    def delete_comment(self, repo: str, comment_id: int) -> None:
        """Record; the oracle's pr_comments of ``repo`` forget the comment (id or database_id)."""
        self._record("delete_comment", repo, comment_id)
        if self.oracle is None:
            return
        for (method, args), items in self.oracle._values.items():
            if method == "pr_comments" and args[0] == repo and isinstance(items, list):
                items[:] = [c for c in items if comment_id not in (c.get("database_id"), c.get("id"))]

    def dismiss_review(
        self, repo: str, number: int, review_id: int, *, message: str = "e2e: dismissed"
    ) -> dict[str, Any]:
        """Record (guard: a pull request of a run branch, when the oracle knows it); returns the dismissed review."""
        self._check_pull(repo, number)
        self._record("dismiss_review", repo, number, review_id, message=message)
        return {"id": review_id, "state": "DISMISSED"}

    def mark_pull_ready(self, repo: str, number: int) -> None:
        """Record (guard as dismiss_review); the oracle's pull request is no longer a draft."""
        self._check_pull(repo, number)
        self._record("mark_pull_ready", repo, number)
        self._set_pull_draft(repo, number, False)

    def convert_pull_to_draft(self, repo: str, number: int) -> None:
        """Record (guard as dismiss_review); the oracle's pull request becomes a draft."""
        self._check_pull(repo, number)
        self._record("convert_pull_to_draft", repo, number)
        self._set_pull_draft(repo, number, True)

    # --- repositories, teams and org objects ---------------------------------------------------------------------
    def patch_repo(self, repo: str, **fields: Any) -> dict[str, Any]:
        """Record; returns the patched fields with the repo name."""
        self._record("patch_repo", repo, **fields)
        return {"name": repo, **fields}

    def create_repo(
        self, name: str, *, private: bool = False, description: str = "", auto_init: bool = True
    ) -> dict[str, Any]:
        """Record; returns the repository (also added to the oracle)."""
        self._record("create_repo", name, private=private, description=description, auto_init=auto_init)
        if self.oracle is not None:
            return self.oracle.add_repo(name, private=private, description=description or None)
        return {"name": name, "full_name": f"{self.org}/{name}", "private": private, "default_branch": "main"}

    def delete_repo(self, name: str, *, force: bool = False) -> None:
        """Record (guard: e2e name unless force); removes it from the oracle."""
        self._check_name("repository", name, force)
        self._record("delete_repo", name, force=force)
        if self.oracle is not None:
            self.oracle.remove_repo(name)

    def delete_team(self, slug: str, *, force: bool = False) -> None:
        """Record (guard: e2e name unless force); removes it from the oracle."""
        self._check_name("team", slug, force)
        self._record("delete_team", slug, force=force)
        if self.oracle is not None:
            self.oracle.remove_team(slug)

    def delete_org_hook(self, hook_id: int) -> None:
        """Record (guard: URL under HOOK_BASE when known to the oracle)."""
        if self.oracle is not None:
            self._check_hook(self.oracle.org_hooks(), hook_id)
        self._record("delete_org_hook", hook_id)

    def delete_repo_hook(self, repo: str, hook_id: int) -> None:
        """Record (guard: URL under HOOK_BASE when known to the oracle)."""
        if self.oracle is not None:
            self._check_hook(self.oracle.repo_hooks(repo), hook_id)
        self._record("delete_repo_hook", repo, hook_id)

    def delete_org_secret(self, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("org secret", name)
        self._record("delete_org_secret", name)

    def delete_org_variable(self, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("org variable", name)
        self._record("delete_org_variable", name)

    def delete_org_ruleset(self, ruleset_id: int, *, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("org ruleset", name)
        self._record("delete_org_ruleset", ruleset_id, name=name)

    def delete_custom_property(self, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("custom property", name)
        self._record("delete_custom_property", name)

    def delete_org_role(self, role_id: int, *, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("org role", name)
        self._record("delete_org_role", role_id, name=name)

    def delete_repo_ruleset(self, repo: str, ruleset_id: int, *, name: str) -> None:
        """Record (guard: e2e name)."""
        self._check_name("repo ruleset", name)
        self._record("delete_repo_ruleset", repo, ruleset_id, name=name)

    def delete_branch_protection_rule(self, repo: str, rule_id: str, *, pattern: str) -> None:
        """Record (guard: the pattern carries a run id)."""
        if self.guard and naming.extract_run_id(pattern) is None:
            raise SafetyError(f"refusing to delete branch protection rule {pattern!r}: no e2e run id")
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

    def ping_repo_hook(self, repo: str, hook_id: int) -> datetime:
        """Record; returns the time of the ping."""
        self._record("ping_repo_hook", repo, hook_id)
        return datetime.now(UTC)

    def ping_org_hook(self, hook_id: int) -> datetime:
        """Record; returns the time of the ping."""
        self._record("ping_org_hook", hook_id)
        return datetime.now(UTC)

    def ensure_membership(self, login: str) -> dict[str, Any]:
        """Record; returns an active membership."""
        self._record("ensure_membership", login)
        return {"state": "active", "role": "member", "user": {"login": login}}

    def set_org_description(self, description: str) -> None:
        """Record; updates the oracle's org description."""
        self._record("set_org_description", description)
        if self.oracle is not None:
            org = self.oracle.org()
            org["description"] = description
            self.oracle.set("org", value=org)

    # --- repository drift: topics, collaborators, invitations --------------------------------------------------
    def set_repo_topics(self, repo: str, topics: Sequence[str]) -> list[str]:
        """Record (guard: e2e repository); the oracle's repo_topics(repo) becomes ``topics``."""
        self._require_e2e("repository", repo)
        self._record("set_repo_topics", repo, list(topics))
        if self.oracle is not None:
            self.oracle.set("repo_topics", repo, value=list(topics))
        return list(topics)

    def add_repo_collaborator(self, repo: str, login: str, *, permission: str = "push") -> dict[str, Any]:
        """Record (guard: e2e repository); the oracle lists the direct collaborator; returns {} (org member)."""
        self._require_e2e("repository", repo)
        self._record("add_repo_collaborator", repo, login, permission=permission)
        if self.oracle is not None:
            role = {"pull": "read", "push": "write"}.get(permission, permission)
            items = [c for c in self.oracle.repo_collaborators(repo) if c.get("login") != login]
            self.oracle.set("repo_collaborators", repo, value=[*items, {"login": login, "role_name": role}])
        return {}

    def remove_repo_collaborator(self, repo: str, login: str) -> None:
        """Record (guard: e2e repository); the oracle forgets the collaborator."""
        self._require_e2e("repository", repo)
        self._record("remove_repo_collaborator", repo, login)
        if self.oracle is not None:
            items = [c for c in self.oracle.repo_collaborators(repo) if c.get("login") != login]
            self.oracle.set("repo_collaborators", repo, value=items)

    def delete_repo_invitation(self, repo: str, invitation_id: int) -> None:
        """Record (guard: e2e repository)."""
        self._require_e2e("repository", repo)
        self._record("delete_repo_invitation", repo, invitation_id)

    # --- teams --------------------------------------------------------------------------------------------------
    def create_team(
        self, name: str, *, description: str = "", privacy: str = "closed", notification_setting: str | None = None
    ) -> dict[str, Any]:
        """Record (guard: e2e name); returns the team (also added to the oracle)."""
        self._require_e2e("team", name)
        self._record(
            "create_team", name, description=description, privacy=privacy, notification_setting=notification_setting
        )
        fields: dict[str, Any] = {"description": description, "privacy": privacy}
        if notification_setting is not None:
            fields["notification_setting"] = notification_setting
        if self.oracle is not None:
            return self.oracle.add_team(name, **fields)
        return {"id": next(self._ids), "slug": name, "name": name, **fields}

    def patch_team(self, slug: str, **fields: Any) -> dict[str, Any]:
        """Record (guard: e2e team and e2e new name); updates the oracle's team."""
        self._require_e2e("team", slug)
        if "name" in fields:
            self._require_e2e("team name", str(fields["name"]))
        self._record("patch_team", slug, **fields)
        team = self.oracle.team(slug) if self.oracle is not None else None
        if team is None or self.oracle is None:
            return {"slug": slug, **fields}
        updated = {**team, **fields}
        self.oracle.remove_team(slug)
        self.oracle._append("teams", (), updated)
        return dict(updated)

    def add_team_member(self, slug: str, login: str, *, role: str = "member") -> dict[str, Any]:
        """Record (guard: e2e team; a login the oracle's org members do not list, when it lists any, is refused like
        the Mutator refuses non-members); the oracle's team_members(slug) gains ``login``."""
        self._require_e2e("team", slug)
        if role not in ("member", "maintainer"):
            raise ValueError(f"team role must be member or maintainer, got {role!r}")
        if self.guard and self.oracle is not None:
            known = set(self.oracle.members()) | {m.get("login") for m in self.oracle.members_with_role()}
            if known and login not in known and self.oracle.membership(login) is None:
                raise SafetyError(f"refusing to add {login!r} to team {slug!r}: not an org member")
        self._record("add_team_member", slug, login, role=role)
        if self.oracle is not None:
            members = self.oracle.team_members(slug)
            self.oracle.set("team_members", slug, value=members if login in members else [*members, login])
        return {"role": role, "state": "active"}

    def remove_team_member(self, slug: str, login: str) -> None:
        """Record (guard: e2e team); the oracle's team_members(slug) loses ``login``."""
        self._require_e2e("team", slug)
        self._record("remove_team_member", slug, login)
        if self.oracle is not None:
            self.oracle.set("team_members", slug, value=[m for m in self.oracle.team_members(slug) if m != login])

    # --- workflows ----------------------------------------------------------------------------------------------
    def dispatch_workflow(
        self, repo: str, workflow_file: str, ref: str, inputs: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        """Record (guard: e2e repository); a queued workflow_dispatch run appears in the oracle; returns its details."""
        self._require_e2e("repository", repo)
        self._record("dispatch_workflow", repo, workflow_file, ref, dict(inputs or {}))
        if self.oracle is not None:
            run_id = self.oracle.add_workflow_run(repo, workflow_file, head_branch=ref)["id"]
        else:
            run_id = next(self._ids)
        url = f"https://api.github.com/repos/{self.org}/{repo}/actions/runs/{run_id}"
        return {
            "workflow_run_id": run_id,
            "run_url": url,
            "html_url": url.replace("api.github.com/repos", "github.com"),
        }

    def cancel_workflow_run(self, repo: str, run_id: int, *, force_cancel: bool = False) -> bool:
        """Record (guard: e2e repository); the oracle's run completes as cancelled; False for a completed run."""
        self._require_e2e("repository", repo)
        self._record("cancel_workflow_run", repo, run_id, force_cancel=force_cancel)
        run = self.oracle.workflow_run(repo, run_id) if self.oracle is not None else None
        if run is not None and run.get("status") == "completed":
            return False
        if self.oracle is not None:
            self.oracle._update_run(repo, run_id, status="completed", conclusion="cancelled")
        return True

    def rerun_workflow_run(self, repo: str, run_id: int) -> None:
        """Record (guard: e2e repository); the oracle's run is queued again with the next attempt number."""
        self._require_e2e("repository", repo)
        self._record("rerun_workflow_run", repo, run_id)
        run = self.oracle.workflow_run(repo, run_id) if self.oracle is not None else None
        if run is not None and self.oracle is not None:
            attempt = int(run.get("run_attempt") or 1) + 1
            self.oracle._update_run(repo, run_id, status="queued", conclusion=None, run_attempt=attempt)

    # --- repository security advisories -------------------------------------------------------------------------
    def create_security_advisory(
        self,
        repo: str,
        *,
        summary: str,
        description: str = "",
        severity: str = "low",
        ecosystem: str = "other",
        package: str | None = None,
        start_private_fork: bool = False,
    ) -> dict[str, Any]:
        """Record (guard: e2e repository and e2e summary); returns a draft advisory (also added to the oracle)."""
        self._require_e2e("repository", repo)
        self._require_e2e("security advisory summary", summary)
        self._record(
            "create_security_advisory",
            repo,
            summary=summary,
            description=description,
            severity=severity,
            ecosystem=ecosystem,
            package=package,
            start_private_fork=start_private_fork,
        )
        fields = {"description": description or summary, "severity": severity}
        if self.oracle is not None:
            return self.oracle.add_security_advisory(repo, summary=summary, **fields)
        return {"ghsa_id": f"GHSA-{next(self._ids):04d}-e2e0-0000", "state": "draft", "summary": summary, **fields}

    def create_advisory_fork(self, repo: str, ghsa_id: str) -> dict[str, Any]:
        """Record (guard: e2e repository); the private fork ``<repo>-<ghsa id>`` appears in the oracle."""
        self._require_e2e("repository", repo)
        self._record("create_advisory_fork", repo, ghsa_id)
        name = f"{repo}-{ghsa_id.lower()}"
        if self.oracle is not None:
            return self.oracle.add_repo(name, private=True, fork=True)
        return {"name": name, "full_name": f"{self.org}/{name}", "private": True, "fork": True}

    def close_security_advisory(self, repo: str, ghsa_id: str) -> dict[str, Any]:
        """Record (guard: e2e repository); the oracle's advisory becomes closed; returns it ({} when unknown)."""
        self._require_e2e("repository", repo)
        self._record("close_security_advisory", repo, ghsa_id)
        if self.oracle is None:
            return {"ghsa_id": ghsa_id, "state": "closed"}
        advisories = self.oracle.repo_security_advisories(repo)
        for advisory in advisories:
            if advisory.get("ghsa_id") == ghsa_id:
                advisory["state"] = "closed"
                self.oracle.set("repo_security_advisories", repo, value=advisories)
                return dict(advisory)
        return {}

    # --- code security configurations ---------------------------------------------------------------------------
    def create_code_security_configuration(
        self, name: str, *, description: str = "otterdog-e2e probe", **settings: Any
    ) -> dict[str, Any]:
        """Record (guard: e2e name); returns the configuration (also added to the oracle)."""
        self._require_e2e("code security configuration", name)
        self._record("create_code_security_configuration", name, description=description, **settings)
        if self.oracle is not None:
            return self.oracle.add_code_security_configuration(name, description=description, **settings)
        return {"id": next(self._ids), "name": name, "description": description, **settings}

    def set_code_security_default(
        self, configuration_id: int, *, name: str, default_for_new_repos: str
    ) -> dict[str, Any]:
        """Record (guard: e2e name); the oracle's code_security_default_configurations follow."""
        if default_for_new_repos not in ("all", "none", "private_and_internal", "public"):
            raise ValueError(f"invalid default_for_new_repos {default_for_new_repos!r}")
        self._require_e2e("code security configuration", name)
        self._record(
            "set_code_security_default", configuration_id, name=name, default_for_new_repos=default_for_new_repos
        )
        if self.oracle is not None:
            defaults = [
                entry
                for entry in self.oracle.code_security_default_configurations()
                if (entry.get("configuration") or {}).get("id") != configuration_id
            ]
            if default_for_new_repos != "none":
                configuration = {"id": configuration_id, "name": name}
                defaults.append({"default_for_new_repos": default_for_new_repos, "configuration": configuration})
            self.oracle.set("code_security_default_configurations", value=defaults)
        return {"default_for_new_repos": default_for_new_repos, "configuration": {"id": configuration_id, "name": name}}

    def delete_code_security_configuration(self, configuration_id: int, *, name: str) -> None:
        """Record (guard: e2e name); the oracle forgets the configuration and its default."""
        self._check_name("code security configuration", name)
        self._record("delete_code_security_configuration", configuration_id, name=name)
        if self.oracle is not None:
            configurations = [c for c in self.oracle.code_security_configurations() if c.get("id") != configuration_id]
            self.oracle.set("code_security_configurations", value=configurations)
            defaults = [
                entry
                for entry in self.oracle.code_security_default_configurations()
                if (entry.get("configuration") or {}).get("id") != configuration_id
            ]
            self.oracle.set("code_security_default_configurations", value=defaults)


# --- FakeAppAuth ---------------------------------------------------------------------------------------------------
class FakeAppAuth:
    """AppAuth stand-in serving webhook deliveries added with add_delivery (list newest first, cursor = offset).

    The installation grants the manifest's permissions and events (appmanifest defaults) unless given. The App is
    owned by ``org`` (``owner`` overrides GET /app's owner) and installed on it only, plus ``extra_installations``
    (GET /app/installations items, for safety.verify_app tests).
    """

    def __init__(
        self,
        *,
        app_id: str = "1",
        slug: str = "otterdog-e2e-test",
        org: str = FAKE_ORG,
        installation_id: int = 4242,
        rate_remaining: int | None = 5000,
        rate_reset: datetime | None = None,
        permissions: Mapping[str, str] | None = None,
        events: Sequence[str] | None = None,
        repository_selection: str = "all",
        suspended_at: str | None = None,
        hook_url: str = "https://sink.example.org/otterdog-e2e",
        org_id: int = FAKE_ORG_ID,
        owner: Mapping[str, Any] | None = None,
        extra_installations: Sequence[Mapping[str, Any]] = (),
        installations_count: int | None = None,
    ) -> None:
        """Create a fake App owned by and installed on ``org``."""
        from otterdog_e2e.appmanifest import DEFAULT_EVENTS, DEFAULT_PERMISSIONS

        self.app_id = app_id
        self._slug = slug
        self.org = org
        self.org_id = org_id
        self.owner = dict(owner) if owner is not None else {"login": org, "id": org_id, "type": "Organization"}
        self.extra_installations = [dict(item) for item in extra_installations]
        self.installations_count = installations_count
        self.installation_id = installation_id
        self._rate_remaining = rate_remaining
        self._rate_reset = rate_reset
        self.permissions = dict(DEFAULT_PERMISSIONS if permissions is None else permissions)
        self.events = list(DEFAULT_EVENTS if events is None else events)
        self.repository_selection = repository_selection
        self.suspended_at = suspended_at
        self.hook_url = hook_url
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._deliveries: list[dict[str, Any]] = []
        self._ids = itertools.count(90000)

    @property
    def slug(self) -> str:
        """App slug."""
        return self._slug

    @property
    def bot_login(self) -> str:
        """``<slug>[bot]``."""
        return f"{self._slug}[bot]"

    @property
    def rate_remaining(self) -> int | None:
        """Configured JWT budget."""
        return self._rate_remaining

    @rate_remaining.setter
    def rate_remaining(self, value: int | None) -> None:
        """Change the JWT budget (to test rate guards)."""
        self._rate_remaining = value

    @property
    def rate_reset(self) -> datetime | None:
        """Configured reset time of the JWT budget (aware UTC datetime, like AppAuth.rate_reset)."""
        return self._rate_reset

    @rate_reset.setter
    def rate_reset(self, value: datetime | None) -> None:
        """Change the reset time (to test the relay's pause)."""
        self._rate_reset = value

    def jwt(self) -> str:
        """A fake JWT-shaped string."""
        self.calls.append(("jwt", ()))
        return "eyJfake0000000.eyJfake0000000.signature000"

    def get_app(self, *, refresh: bool = False) -> dict[str, Any]:
        """GET /app equivalent (owner, installations_count)."""
        self.calls.append(("get_app", (refresh,)))
        count = self.installations_count if self.installations_count is not None else 1 + len(self.extra_installations)
        return {"id": int(self.app_id), "slug": self._slug, "owner": dict(self.owner), "installations_count": count}

    def installations(self) -> list[dict[str, Any]]:
        """GET /app/installations equivalent: the installation on ``org`` and the extra ones."""
        self.calls.append(("installations", ()))
        return [self._installation(), *(dict(item) for item in self.extra_installations)]

    def installation_for_org(self, org: str) -> dict[str, Any] | None:
        """The installation on ``org`` (None for other orgs)."""
        self.calls.append(("installation_for_org", (org,)))
        return self._installation() if org == self.org else None

    def _installation(self) -> dict[str, Any]:
        """The installation on ``org`` (GET /orgs/{org}/installation and GET /app/installations item)."""
        org = self.org
        return {
            "id": self.installation_id,
            "account": {"login": org, "id": self.org_id, "type": "Organization"},
            "target_id": self.org_id,
            "target_type": "Organization",
            "repository_selection": self.repository_selection,
            "suspended_at": self.suspended_at,
            "permissions": dict(self.permissions),
            "events": list(self.events),
        }

    def installation_token(self, installation_id: int) -> str:
        """A fake installation token."""
        self.calls.append(("installation_token", (installation_id,)))
        return f"ghs_fake{installation_id:032d}"

    def hook_config(self) -> dict[str, Any]:
        """A sink hook config."""
        self.calls.append(("hook_config", ()))
        return {"url": self.hook_url, "content_type": "json", "insecure_ssl": "0"}

    def add_delivery(
        self,
        event: str,
        payload: Mapping[str, Any] | None,
        *,
        action: str | None = None,
        installation_id: int | None = -1,
        repository_id: int | None = None,
        delivered_at: datetime | None = None,
        guid: str | None = None,
        redelivery: bool = False,
        status_code: int = 202,
        delivery_id: int | None = None,
    ) -> dict[str, Any]:
        """Add a delivery (installation_id -1 = this App's installation); returns the list item."""
        delivery_id = delivery_id if delivery_id is not None else next(self._ids)
        when = delivered_at or (datetime.now(UTC) - timedelta(seconds=1))
        item = {
            "id": delivery_id,
            "guid": guid or f"guid-{delivery_id}",
            "delivered_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "redelivery": redelivery,
            "duration": 0.1,
            "status": "OK" if status_code < 400 else "Invalid HTTP Response",
            "status_code": status_code,
            "event": event,
            "action": action if action is not None else (payload or {}).get("action"),
            "installation_id": self.installation_id if installation_id == -1 else installation_id,
            "repository_id": repository_id,
        }
        detail: dict[str, Any] = {
            **item,
            "url": "https://sink.example.org/otterdog-e2e",
            "request": {"headers": {"X-GitHub-Event": event}, "payload": copy.deepcopy(payload)},
            "response": {"headers": {}, "payload": None},
        }
        self._deliveries.append(detail)
        self._deliveries.sort(key=lambda d: (d["delivered_at"], d["id"]), reverse=True)
        return dict(item)

    def list_deliveries(
        self, *, per_page: int = 100, cursor: str | None = None
    ) -> tuple[list[dict[str, Any]], str | None]:
        """One page, newest first; the cursor is the offset of the next page (None at the end)."""
        self.calls.append(("list_deliveries", (per_page, cursor)))
        start = int(cursor or 0)
        page = self._deliveries[start : start + per_page]
        items = [{k: v for k, v in d.items() if k not in ("url", "request", "response")} for d in page]
        end = start + per_page
        return items, (str(end) if end < len(self._deliveries) else None)

    def get_delivery(self, delivery_id: int) -> dict[str, Any]:
        """Delivery detail with request.headers and request.payload (KeyError when unknown)."""
        self.calls.append(("get_delivery", (delivery_id,)))
        for delivery in self._deliveries:
            if delivery["id"] == delivery_id:
                return copy.deepcopy(delivery)
        raise KeyError(delivery_id)


# --- settings, targets and identities ------------------------------------------------------------------------------
FAKE_LOGINS: Mapping[str, str] = {
    "admin": "e2e-admin",
    "author": "e2e-author",
    "approver": "e2e-approver",
    "outsider": "e2e-outsider",
    "config_reader": "e2e-config-reader",
}
FAKE_TOKEN_ENV: Mapping[str, str] = {
    "admin": "E2E_ADMIN_TOKEN",
    "oracle": "E2E_ORACLE_TOKEN",
    "author": "E2E_AUTHOR_TOKEN",
    "approver": "E2E_APPROVER_TOKEN",
    "outsider": "E2E_OUTSIDER_TOKEN",
    "config_reader": "E2E_CONFIG_READ_TOKEN",
}


def make_settings(root: Path, **overrides: Any) -> HarnessSettings:
    """HarnessSettings rooted at ``root`` (cache, artifacts, targets and scenarios below it; nothing is created)."""
    values: dict[str, Any] = {
        "project_root": root,
        "cache_dir": root / "cache",
        "artifacts_root": root / "artifacts",
        "upstream_repo": "eclipse-csi/otterdog",
        "targets_dir": root / "targets",
        "scenarios_dir": root / "scenarios",
    }
    values.update(overrides)
    return HarnessSettings(**values)


def make_target(name: str = "fake", **overrides: Any) -> Target:
    """A Target of the fake org: every identity declared, an App section, relay transport, one fixture repo."""
    identities = {
        role: IdentitySpec(role, FAKE_LOGINS.get(role), token_env) for role, token_env in FAKE_TOKEN_ENV.items()
    }
    values: dict[str, Any] = {
        "name": name,
        "description": "fake test target",
        "org": FAKE_ORG,
        "org_id": FAKE_ORG_ID,
        "allowed_org_ids": (FAKE_ORG_ID,),
        "expected_plan": "free",
        "marker": FAKE_MARKER,
        "capability_overrides": {"add": (), "remove": ()},
        "configs_repo": "otterdog-e2e-configs",
        "org_config_repo": "auto",
        "defaults_repo": "otterdog-e2e-defaults",
        "template_mode": "auto",
        "template_url": None,
        "identities": identities,
        "app": AppSpec("E2E_APP_ID", "E2E_APP_PRIVATE_KEY", "E2E_APP_PRIVATE_KEY_FILE", "E2E_APP_WEBHOOK_SECRET", None),
        "admin_team": "otterdog-admins",
        "approval_team": "project-leads",
        "contributors_team": "e2e-contributors",
        "webapp": WebappSpec("relay", None, None, "e2e/otterdog-validate", "e2e/otterdog-sync", 1, 5000),
        "fixture_repos": ("otterdog-e2e-fixture-a",),
        "extra_protected_repos": (),
        "baseline_settings": {},
        "source_path": Path("targets") / f"{name}.yaml",
    }
    values.update(overrides)
    return Target(**values)


def fake_token(name: str) -> str:
    """A classic-PAT-shaped fake token (``ghp_`` + 36 chars): Redactor.PATTERNS mask it."""
    return "ghp_" + hashlib.sha256(name.encode()).hexdigest()[:36]


def make_identities(*names: str) -> dict[str, Identity]:
    """Identities with fake tokens (default: admin; oracle falls back to admin like settings.resolve_identities)."""
    identities = {name: Identity(name, FAKE_LOGINS.get(name), fake_token(name)) for name in names or ("admin",)}
    if "admin" in identities and "oracle" not in identities:
        admin = identities["admin"]
        identities["oracle"] = Identity("oracle", admin.login, admin.token, admin.token_type)
    return identities


# --- FakeLease -----------------------------------------------------------------------------------------------------
class FakeLease:
    """OrgLease stand-in: ``busy`` makes acquire raise LeaseBusy with ``holder``; calls are recorded in ``calls``."""

    def __init__(
        self,
        *,
        run_id: str = FAKE_RUN_ID,
        ledger: Iterable[str] = (),
        holder: Mapping[str, Any] | None = None,
        busy: bool = False,
    ) -> None:
        """Create a free (or busy) lease whose ledger lists ``ledger`` run ids."""
        self.run_id = run_id
        self.ledger_ids = list(ledger)
        self.holder = dict(holder) if holder is not None else None
        self.busy = busy
        self.calls: list[str] = []
        self.refs: list[str] = []
        self.held = False
        self.heartbeat = False
        self.takeovers: list[tuple[str, bool, str | None]] = []  # (run id, force, trusted holder) of acquire()
        self.takeover_refused = False  # the lease of the takeover run looks alive (renewed recently)

    def acquire(
        self,
        *,
        wait: float = 0,
        steal_expired: bool = True,
        takeover_run: str | None = None,
        force_takeover: bool = False,
        trusted_holder: str | None = None,
    ) -> None:
        """Hold the lease and register this run in the ledger (LeaseBusy when busy); ``takeover_run`` is recorded in
        ``takeovers`` and replaces a lease of that run unless ``takeover_refused``."""
        self.calls.append("acquire")
        if takeover_run is not None:
            self.takeovers.append((takeover_run, force_takeover, trusted_holder))
            held_by = (self.holder or {}).get("run_id")
            if held_by == takeover_run and self.takeover_refused and not force_takeover:
                raise LeaseBusy(dict(self.holder or {}), f"run {takeover_run!r} renewed the org lease recently")
            if held_by == takeover_run:
                self.busy = False
        if self.busy:
            raise LeaseBusy(dict(self.holder or {"run_id": "t3c7z8b6", "holder": "local:other"}))
        self.held = True
        self.holder = {"run_id": self.run_id, "holder": "fake", "expires_at": "2099-01-01T00:00:00Z"}
        if self.run_id not in self.ledger_ids:
            self.ledger_ids.append(self.run_id)

    def renew(self) -> None:
        """Record a renewal."""
        self.calls.append("renew")

    def release(self) -> None:
        """Release the lease."""
        self.calls.append("release")
        if self.held:
            self.held = False
            self.holder = None

    def ledger(self) -> list[str]:
        """Run ids of the ledger."""
        self.calls.append("ledger")
        return list(self.ledger_ids)

    def holder_record(self) -> dict[str, Any] | None:
        """Current holder record."""
        self.calls.append("holder_record")
        return dict(self.holder) if self.holder is not None else None

    def reference(self, *refs: str) -> None:
        """Record referenced refs."""
        self.refs.extend(refs)

    def start_heartbeat(self, interval: float = 600.0) -> None:
        """Record the heartbeat start."""
        self.calls.append("start_heartbeat")
        self.heartbeat = True

    def stop_heartbeat(self) -> None:
        """Record the heartbeat stop."""
        self.calls.append("stop_heartbeat")
        self.heartbeat = False


# --- FakeBaselineManager -------------------------------------------------------------------------------------------
class FakeBaselineManager:
    """BaselineManager stand-in: text() returns ``baseline_text``; ``refuse`` makes check_removals raise SafetyError."""

    def __init__(self, baseline_text: str = "// baseline\n", *, refuse: str | None = None) -> None:
        """Create the fake (``refuse``: message of the SafetyError raised by check_removals/guarded_apply)."""
        self.baseline_text = baseline_text
        self.refuse = refuse
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.run_objects_left = False

    def calls_to(self, method: str) -> list[tuple[tuple[Any, ...], dict[str, Any]]]:
        """Recorded (args, kwargs) of ``method``."""
        return [(args, kwargs) for name, args, kwargs in self.calls if name == method]

    def text(self) -> str:
        """The baseline text."""
        self.calls.append(("text", (), {}))
        return self.baseline_text

    def check_changes(self, plan: Any) -> None:
        """Record the change guard (SafetyError when ``refuse`` is set)."""
        self.calls.append(("check_changes", (plan,), {}))
        if self.refuse:
            raise SafetyError(self.refuse)

    def check_removals(self, plan: Any) -> None:
        """Record; SafetyError when ``refuse`` is set."""
        self.calls.append(("check_removals", (plan,), {}))
        if self.refuse:
            raise SafetyError(self.refuse)

    def guarded_apply(self, cli: Any, *, repo_filter: str | None, delete: bool) -> Any:
        """Record; SafetyError when ``refuse`` is set."""
        self.calls.append(("guarded_apply", (cli,), {"repo_filter": repo_filter, "delete": delete}))
        if self.refuse:
            raise SafetyError(self.refuse)
        return None

    def guard_config_change(self, base_text: str, head_text: str, *, allow_invalid_head: bool = True) -> Any:
        """Record the config guard (ConfigRepoFlow's guard); SafetyError when ``refuse`` is set."""
        self.calls.append(("guard_config_change", (base_text, head_text), {"allow_invalid_head": allow_invalid_head}))
        if self.refuse:
            raise SafetyError(self.refuse)
        return None

    def reset(self) -> Any:
        """Record a reset."""
        self.calls.append(("reset", (), {}))
        return None

    def push(self, flow: Any) -> str:
        """Record; reset_main(text) on the flow like the real push."""
        self.calls.append(("push", (flow,), {}))
        return str(flow.reset_main(self.baseline_text, message="otterdog-e2e: baseline"))
