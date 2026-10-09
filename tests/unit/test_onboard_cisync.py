"""``otterdog-e2e ci-sync`` (onboard.cisync.CiSync): the names the workflows read per environment, the dry run (names
only), the gh command sequence of --apply with secrets on stdin only, the repository variables, and the refusals."""

from __future__ import annotations

import json
import shutil
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_e2e import cli, procs
from otterdog_e2e.onboard.cisync import (
    TRUSTED,
    UNTRUSTED,
    WEBUI,
    CiSync,
    CiSyncError,
    environment_kinds,
    workflow_names,
)
from otterdog_e2e.procs import CompletedProcess
from otterdog_e2e.vaults import VaultError

ROOT = Path(__file__).resolve().parents[2]
REPO = "acme/otterdog-e2e"
SECRETS = {
    "E2E_ADMIN_TOKEN": "tokadmin_1111111111111111",
    "E2E_AUTHOR_TOKEN": "tokauthor_3333333333333333",
    "E2E_CONFIG_READER_TOKEN": "tokreader_6666666666666666",
    "E2E_APP_WEBHOOK_SECRET": "whsec-0123456789abcdef",
    "E2E_ADMIN_PASSWORD": "correct horse battery staple",
    "E2E_ADMIN_TOTP_SEED": "JBSWY3DPEHPK3PXP",
}
PEM = "-----BEGIN RSA PRIVATE KEY-----\nMIIEfakekeymaterial0123456789\n-----END RSA PRIVATE KEY-----\n"
VARIABLES = {
    "E2E_ORG": "e2e-test-org",
    "E2E_ORG_ID": "424242",
    "E2E_ADMIN_LOGIN": "e2e-admin",
    "E2E_AUTHOR_LOGIN": "e2e-author",
    "E2E_CONFIG_READER_LOGIN": "e2e-reader",
    "E2E_APP_ID": "4242",
    "E2E_APP_SLUG": "otterdog-e2e-e2e-test-org",
    "E2E_PROFILE": "free",
    "E2E_ADMIN_TOKEN_TYPE": "classic",
}


@dataclass
class Gh:
    """Fake gh: answers reads, records every call (args, stdin), fails the configured commands; environments keep the
    body of their PUT (read back by GET, unless ``env_answers`` overrides it) and their deployment branch policies."""

    repo_variables: dict[str, str] = field(default_factory=dict)
    user: dict[str, Any] = field(default_factory=lambda: {"login": "maintainer", "id": 11, "type": "User"})
    users: dict[str, dict[str, Any]] = field(default_factory=dict)
    calls: list[tuple[tuple[str, ...], str | None]] = field(default_factory=list)
    fail: dict[str, tuple[int, str]] = field(default_factory=dict)  # args prefix (joined) -> (returncode, stderr)
    environments: dict[str, dict[str, Any]] = field(default_factory=dict)  # env -> PUT body
    env_answers: dict[str, dict[str, Any]] = field(default_factory=dict)  # env -> GET answer (overrides the body)
    branch_policies: dict[str, list[dict[str, Any]]] = field(default_factory=dict)  # env -> policies

    def __call__(self, args: Sequence[str], stdin: str | None) -> CompletedProcess[str]:
        """One gh invocation."""
        args = tuple(args)
        self.calls.append((args, stdin))
        joined = " ".join(args)
        for prefix, (code, stderr) in self.fail.items():
            if joined.startswith(prefix):
                return CompletedProcess(["gh", *args], code, "", stderr)
        if args[:2] == ("repo", "view"):
            return self.ok(REPO + "\n")
        if args == ("api", "user"):
            return self.ok(json.dumps(self.user))
        if args[0] == "api" and args[1].startswith("users/"):
            login = args[1].split("/", 1)[1]
            if login not in self.users:
                return self.missing(args)
            return self.ok(json.dumps(self.users[login]))
        if args[0] == "api" and "/actions/variables/" in args[1] and len(args) == 2:
            name = args[1].rsplit("/", 1)[1]
            if name not in self.repo_variables:
                return self.missing(args)
            return self.ok(json.dumps({"name": name, "value": self.repo_variables[name]}))
        method, path = (args[2], args[3]) if args[:2] == ("api", "-X") else ("GET", args[1])
        if args[0] == "api" and "/environments/" in path:
            return self.environment(args, method, path, stdin)
        return self.ok("{}")

    def environment(self, args: tuple[str, ...], method: str, path: str, stdin: str | None) -> CompletedProcess[str]:
        """repos/{repo}/environments/{env}[/deployment-branch-policies[/{id}]]."""
        env, _, sub = path.split("/environments/", 1)[1].partition("/")
        sub = sub.split("?", 1)[0]
        if not sub:
            if method == "PUT":
                self.environments[env] = json.loads(stdin or "{}")
                return self.ok("{}")
            if env in self.env_answers:
                return self.ok(json.dumps(self.env_answers[env]))
            if env not in self.environments:
                return self.missing(args)
            return self.ok(json.dumps(self.environment_view(env)))
        policies = self.branch_policies.get(env)
        if sub == "deployment-branch-policies" and method == "GET":
            if policies is None:
                return self.missing(args)
            return self.ok(json.dumps({"total_count": len(policies), "branch_policies": policies}))
        if sub == "deployment-branch-policies" and method == "POST":
            fields = dict(arg.split("=", 1) for arg in args if "=" in arg)
            policies = self.branch_policies.setdefault(env, [])
            if any(policy["name"] == fields["name"] for policy in policies):
                return CompletedProcess(["gh", *args], 1, "", "gh: Name already exists (HTTP 422)")
            policies.append({"id": 100 + len(policies), "name": fields["name"], "type": fields["type"]})
            return self.ok("{}")
        if sub.startswith("deployment-branch-policies/") and method == "DELETE":
            policy_id = int(sub.rsplit("/", 1)[1])
            self.branch_policies[env] = [policy for policy in policies or [] if policy["id"] != policy_id]
            return self.ok("")
        raise AssertionError(f"unexpected gh call {args}")

    def environment_view(self, env: str) -> dict[str, Any]:
        """GET repos/{repo}/environments/{env} after a PUT of ``body``."""
        body = self.environments[env]
        rules: list[dict[str, Any]] = []
        if body.get("reviewers"):
            reviewers = [{"type": item["type"], "reviewer": {"id": item["id"]}} for item in body["reviewers"]]
            rules.append(
                {
                    "type": "required_reviewers",
                    "prevent_self_review": body.get("prevent_self_review", False),
                    "reviewers": reviewers,
                }
            )
        rules.append({"type": "branch_policy"})
        return {
            "name": env,
            "deployment_branch_policy": body.get("deployment_branch_policy"),
            "protection_rules": rules,
        }

    @staticmethod
    def ok(stdout: str) -> CompletedProcess[str]:
        """A successful call."""
        return CompletedProcess(["gh"], 0, stdout, "")

    @staticmethod
    def missing(args: tuple[str, ...]) -> CompletedProcess[str]:
        """A 404."""
        return CompletedProcess(["gh", *args], 1, "", "gh: Not Found (HTTP 404)")

    def writes(self) -> list[tuple[tuple[str, ...], str | None]]:
        """Calls that change something (everything but the reads)."""
        return [
            (args, stdin)
            for args, stdin in self.calls
            if not (args[:2] == ("repo", "view") or (args[0] == "api" and len(args) == 2))
        ]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project root with the real workflows and profiles."""
    root = tmp_path / "project"
    shutil.copytree(ROOT / ".github" / "workflows", root / ".github" / "workflows")
    shutil.copytree(ROOT / "targets", root / "targets")
    return root


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """tmp HOME with the env file of instance org2 (no web credentials, the App key in a file)."""
    for name in ("CI", "GITHUB_ACTIONS", "GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    home = tmp_path / "home"
    write_env(home, web=False)
    return home


def write_env(home: Path, *, web: bool, extra: str = "") -> Path:
    """The instance env file of org2 (secrets, variables, App key file)."""
    directory = home / ".config" / "otterdog-e2e"
    (directory / "org2").mkdir(parents=True, exist_ok=True)
    key = directory / "org2" / "app-4242.private-key.pem"
    key.write_text(PEM)
    values = {
        **VARIABLES,
        **{k: v for k, v in SECRETS.items() if web or ("ADMIN_PASSWORD" not in k and "TOTP" not in k)},
    }
    lines = [f'{key_}="{value}"' for key_, value in values.items()] + [f"E2E_APP_PRIVATE_KEY_FILE={key}", extra]
    path = directory / "org2.env"
    path.write_text("\n".join(lines) + "\n")
    path.chmod(0o600)
    return path


def make_sync(home: Path, project: Path, gh: Gh, **kwargs: Any) -> tuple[CiSync, list[str]]:
    """A CiSync of org2 with the fake gh and an output list."""
    echoed: list[str] = []
    environ = {"HOME": str(home), **kwargs.pop("environ", {})}
    sync = CiSync("org2", environ=environ, project_root=project, gh=gh, echo=echoed.append, **kwargs)
    return sync, echoed


# --- workflow names ---------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("expression", "kinds"),
    [
        (
            (
                "${{ needs.classify.outputs.trust == 'trusted' && format('e2e-{0}', inputs.target) || "
                "format('e2e-{0}-untrusted', inputs.target) }}"
            ),
            {TRUSTED, UNTRUSTED},
        ),
        (
            (
                "${{ needs.classify.outputs.trust == 'trusted' && format('e2e-{0}', matrix.target) || "
                "format('e2e-{0}-untrusted', matrix.target) }}"
            ),
            {TRUSTED, UNTRUSTED},
        ),
        ("e2e-${{ matrix.target }}", {TRUSTED}),
        ("${{ format('e2e-{0}-webui', inputs.target) }}", {WEBUI}),
        ("e2e-${{ matrix.target }}-webui", {WEBUI}),
        ("github-pages", set()),
        ("", set()),
    ],
)
def test_environment_kinds(expression: str, kinds: set[str]) -> None:
    """The environment expressions of the e2e workflows (today's and the matrix forms) map to their kinds."""
    assert environment_kinds(expression) == kinds


def test_workflow_names_of_the_real_workflows() -> None:
    """Trusted and untrusted jobs read the same names; the web secrets only in the webui job; repository variables
    (job conditions, matrices) are not environment names."""
    names = workflow_names(ROOT / ".github" / "workflows")
    trusted, untrusted, webui = names[TRUSTED], names[UNTRUSTED], names[WEBUI]
    assert {"E2E_ORG", "E2E_ORG_ID", "E2E_ADMIN_LOGIN", "E2E_APP_ID", "E2E_CONFIGS_REPO"} <= trusted.variables
    assert {"E2E_ADMIN_TOKEN", "E2E_AUTHOR_TOKEN", "E2E_APP_PRIVATE_KEY", "E2E_APP_WEBHOOK_SECRET"} <= trusted.secrets
    assert untrusted.secrets <= trusted.secrets and untrusted.variables <= trusted.variables
    assert {"E2E_ADMIN_PASSWORD", "E2E_ADMIN_TOTP_SEED"} <= webui.secrets
    assert not {"E2E_ADMIN_PASSWORD", "E2E_ADMIN_TOTP_SEED"} & (trusted.secrets | untrusted.secrets)
    assert "E2E_TARGETS" not in trusted.variables and "E2E_ADMIN_USERNAME" in webui.variables


def test_workflow_names_scan_steps_and_env_only(tmp_path: Path) -> None:
    """vars/secrets of steps and job env count; job conditions and matrices do not; other environments ignored."""
    (tmp_path / "w.yml").write_text(
        """
jobs:
  live:
    if: ${{ vars.E2E_GATE != '' }}
    strategy: {matrix: {target: "${{ fromJSON(vars.E2E_LIST) }}"}}
    environment: e2e-${{ matrix.target }}
    env:
      A: ${{ vars.JOB_LEVEL }}
    steps:
      - run: echo
        env:
          B: ${{ secrets.STEP_SECRET }}
          C: "${{ vars.ONE }}-${{ vars.TWO || 'x' }}"
          D: ${{ secrets.GITHUB_TOKEN }}
  pages:
    environment: {name: github-pages}
    steps:
      - env: {E: "${{ secrets.PAGES_ONLY }}"}
"""
    )
    names = workflow_names(tmp_path)[TRUSTED]
    assert names.variables == {"JOB_LEVEL", "ONE", "TWO"}
    assert names.secrets == {"STEP_SECRET", "GITHUB_TOKEN"}
    (tmp_path / "bad.yml").write_text("jobs: [unclosed")
    with pytest.raises(CiSyncError, match="cannot read the workflow"):
        workflow_names(tmp_path)


# --- dry run ----------------------------------------------------------------------------------------------------------
def test_dry_run_prints_names_never_values_and_writes_nothing(home: Path, project: Path) -> None:
    """Default: only reads run; every planned operation is printed with names; no value appears."""
    gh = Gh(repo_variables={"E2E_TARGETS": '["free"]'})
    sync, echoed = make_sync(home, project, gh)
    operations = sync.run(apply=False)
    output = "\n".join(echoed)
    assert not gh.writes()
    assert f"ci-sync of instance org2 ({home}/.config/otterdog-e2e/org2.env) -> {REPO} (dry run)" in output
    assert "environment e2e-org2: deployment branches: main only" in output
    assert "environment e2e-org2-untrusted: deployment branches: main only, required reviewers maintainer" in output
    assert "secret E2E_ADMIN_TOKEN in e2e-org2-untrusted (value on stdin)" in output
    assert "variable E2E_PROFILE in e2e-org2" in output and "variable E2E_ORG_ID in e2e-org2" in output
    assert "repository variable E2E_INSTANCES: created from E2E_TARGETS + org2" in output
    assert "e2e-org2-webui not managed" in output and "e2e-org2-webui" not in " ".join(
        o.description for o in operations
    )
    assert "skipped: " in output and "E2E_ORACLE_TOKEN" in output  # names without a value
    assert "dry run: re-run with --apply" in output
    for value in (*SECRETS.values(), "MIIEfakekeymaterial", "e2e-test-org", "424242", "e2e-admin"):
        assert value not in output


# --- apply ------------------------------------------------------------------------------------------------------------
def test_apply_sequence_with_secrets_on_stdin_only(home: Path, project: Path) -> None:
    """--apply: environments, branch policies, variables (--body), secrets (stdin), then E2E_INSTANCES."""
    gh = Gh(repo_variables={"E2E_TARGETS": '["free"]'})
    sync, echoed = make_sync(home, project, gh)
    sync.run(apply=True)
    writes = gh.writes()
    for args, _stdin in gh.calls:
        for value in (*SECRETS.values(), "MIIEfakekeymaterial"):
            assert all(value not in arg for arg in args), args
    put = [(args, stdin) for args, stdin in writes if args[:3] == ("api", "-X", "PUT")]
    assert [args[3] for args, _ in put] == [
        f"repos/{REPO}/environments/e2e-org2",
        f"repos/{REPO}/environments/e2e-org2-untrusted",
    ]
    trusted, untrusted = (json.loads(stdin or "") for _, stdin in put)
    branch_policy = {"protected_branches": False, "custom_branch_policies": True}
    assert trusted == {"deployment_branch_policy": branch_policy}
    assert untrusted == {
        "deployment_branch_policy": branch_policy,
        "reviewers": [{"type": "User", "id": 11}],
        "prevent_self_review": True,
    }
    policies = [args for args, _ in writes if args[:3] == ("api", "-X", "POST")]
    assert policies[0] == (
        "api", "-X", "POST", f"repos/{REPO}/environments/e2e-org2/deployment-branch-policies",
        "-f", "name=main", "-f", "type=branch",
    )  # fmt: skip
    secrets = {(args[2], args[4]): stdin for args, stdin in writes if args[:2] == ("secret", "set")}
    assert secrets[("E2E_ADMIN_TOKEN", "e2e-org2")] == SECRETS["E2E_ADMIN_TOKEN"]
    assert secrets[("E2E_APP_PRIVATE_KEY", "e2e-org2-untrusted")] == PEM  # from E2E_APP_PRIVATE_KEY_FILE
    assert all(args[-2:] == ("--repo", REPO) and "--body" not in args for args, _ in writes if args[0] == "secret")
    variables = {
        (args[2], args[4]): args[6] for args, _ in writes if args[:2] == ("variable", "set") and "--env" in args
    }
    assert (
        variables[("E2E_PROFILE", "e2e-org2")] == "free" and variables[("E2E_ORG_ID", "e2e-org2-untrusted")] == "424242"
    )
    assert not [name for name, _ in variables if name in ("E2E_ADMIN_PASSWORD", "E2E_TARGETS", "E2E_INSTANCES")]
    assert writes[-1][0] == ("variable", "set", "E2E_INSTANCES", "--body", '["free","org2"]', "--repo", REPO)
    assert any(text.startswith("done: ") for text in echoed)


def test_other_branch_policies_are_refused_unless_pruned(home: Path, project: Path) -> None:
    """A pre-existing ``*`` policy (or a tag policy) keeps other refs deployable: refused with its name, also in the
    dry run; --prune-branch-policies deletes each one ("would delete" in the dry run) before any value is set."""
    existing = {
        "e2e-org2": [{"id": 7, "name": "*", "type": "branch"}, {"id": 8, "name": "main", "type": "branch"}],
        "e2e-org2-untrusted": [{"id": 9, "name": "v*", "type": "tag"}],
    }
    gh = Gh(branch_policies={env: [dict(item) for item in items] for env, items in existing.items()})
    sync, _ = make_sync(home, project, gh)
    with pytest.raises(
        CiSyncError, match=r"e2e-org2: deployment branch policies other than main exist \('\*' \(branch\)\)"
    ):
        sync.run(apply=False)
    assert not gh.writes()
    sync, echoed = make_sync(home, project, gh, prune_branch_policies=True)
    sync.run(apply=False)
    output = "\n".join(echoed)
    assert "environment e2e-org2: would delete the deployment branch policy '*' (branch)" in output
    assert "environment e2e-org2-untrusted: would delete the deployment branch policy 'v*' (tag)" in output
    assert "'main' (branch)" not in output and not gh.writes()
    sync, echoed = make_sync(home, project, gh, prune_branch_policies=True)
    sync.run(apply=True)
    writes = [args for args, _ in gh.writes()]
    deletes = [args for args in writes if args[:3] == ("api", "-X", "DELETE")]
    assert [args[3] for args in deletes] == [
        f"repos/{REPO}/environments/e2e-org2/deployment-branch-policies/7",
        f"repos/{REPO}/environments/e2e-org2-untrusted/deployment-branch-policies/9",
    ]
    first_secret = next(i for i, args in enumerate(writes) if args[:2] == ("secret", "set") and args[4] == "e2e-org2")
    assert writes.index(deletes[0]) < first_secret
    assert [item["name"] for item in gh.branch_policies["e2e-org2"]] == ["main"]
    assert "ok: environment e2e-org2: delete the deployment branch policy '*' (branch)" in "\n".join(echoed)


def test_the_refusal_names_the_option(home: Path, project: Path) -> None:
    """The refusal tells how to delete the other policies."""
    gh = Gh(branch_policies={"e2e-org2": [{"id": 7, "name": "*", "type": "branch"}]})
    with pytest.raises(CiSyncError, match="re-run with --prune-branch-policies to delete them"):
        make_sync(home, project, gh)[0].run(apply=False)


@pytest.mark.parametrize(
    ("env", "answer", "problem"),
    [
        (
            "e2e-org2",
            {"deployment_branch_policy": {"protected_branches": True, "custom_branch_policies": False}},
            'deployment branch policy {"custom_branch_policies": false, "protected_branches": true}',
        ),
        ("e2e-org2", {"deployment_branch_policy": None}, "deployment branch policy null"),
        (
            "e2e-org2-untrusted",
            {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}},
            "no required reviewers",
        ),
        (
            "e2e-org2-untrusted",
            {
                "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True},
                "protection_rules": [
                    {
                        "type": "required_reviewers",
                        "prevent_self_review": False,
                        "reviewers": [{"type": "User", "reviewer": {"id": 99}}],
                    }
                ],
            },
            "required reviewers without maintainer; prevent_self_review is not true",
        ),
    ],
)
def test_secrets_wait_for_the_protections_read_back(
    home: Path, project: Path, env: str, answer: dict[str, Any], problem: str
) -> None:
    """After the PUT the environment is read back: protections that differ stop the run before its secrets."""
    gh = Gh(env_answers={env: answer})
    sync, _ = make_sync(home, project, gh)
    with pytest.raises(CiSyncError, match=f"environment {env}: its protections differ") as error:
        sync.run(apply=True)
    assert problem in str(error.value) and "refusing to push its secrets" in str(error.value)
    pushed = {args[4] for args, _ in gh.writes() if args[:2] == ("secret", "set")}
    assert env not in pushed
    reads = [args for args, _ in gh.calls if args == ("api", f"repos/{REPO}/environments/{env}")]
    assert len(reads) == 1


def test_a_policy_left_after_the_update_stops_the_secrets(home: Path, project: Path) -> None:
    """A policy other than main still listed when the environment is read back (e.g. created meanwhile): refused."""
    gh = Gh()
    original = gh.environment

    def environment(args: tuple[str, ...], method: str, path: str, stdin: str | None) -> CompletedProcess[str]:
        """A ``*`` policy appears once the environment exists."""
        if method == "PUT":
            gh.branch_policies.setdefault("e2e-org2", []).append({"id": 50, "name": "*", "type": "branch"})
        return original(args, method, path, stdin)

    gh.environment = environment  # type: ignore[method-assign]
    sync, _ = make_sync(home, project, gh)
    with pytest.raises(CiSyncError, match=r"e2e-org2: its protections differ .*deployment branch policies '\*'"):
        sync.run(apply=True)
    assert not [args for args, _ in gh.writes() if args[:2] == ("secret", "set")]


def test_the_dry_run_reads_no_environment(home: Path, project: Path) -> None:
    """The read-back is an operation of --apply: the dry run only lists the policies."""
    gh = Gh()
    make_sync(home, project, gh)[0].run(apply=False)
    assert not [args for args, _ in gh.calls if args[0] == "api" and args[1].endswith("/environments/e2e-org2")]
    assert [args for args, _ in gh.calls if "deployment-branch-policies?per_page=100" in args[-1]]


def test_reviewers_and_self_review(home: Path, project: Path) -> None:
    """--reviewer logins are resolved to ids; --allow-self-review turns prevent_self_review off."""
    gh = Gh(users={"alice": {"login": "alice", "id": 21, "type": "User"}, "bob": {"login": "Bob", "id": 22}})
    sync, echoed = make_sync(home, project, gh, reviewers=("alice", "bob"), allow_self_review=True)
    sync.run(apply=True)
    body = next(
        json.loads(stdin or "")
        for args, stdin in gh.calls
        if args[:4] == ("api", "-X", "PUT", f"repos/{REPO}/environments/e2e-org2-untrusted")
    )
    assert body["reviewers"] == [{"type": "User", "id": 21}, {"type": "User", "id": 22}]
    assert body["prevent_self_review"] is False
    assert "required reviewers alice, Bob, self-review allowed" in "\n".join(echoed)


def test_the_only_reviewer_with_prevented_self_review_is_noted(home: Path, project: Path) -> None:
    """Default reviewer = the gh user: the note says they cannot approve their own runs."""
    sync, echoed = make_sync(home, project, Gh())
    sync.run(apply=False)
    assert "you are the only required reviewer and self-review is prevented" in "\n".join(echoed)


def test_bad_reviewers_are_refused(home: Path, project: Path) -> None:
    """Unknown users, organizations and too many reviewers."""
    gh = Gh(users={"some-org": {"login": "some-org", "id": 5, "type": "Organization"}})
    for reviewers, message in (
        (("ghost",), "gh api users/ghost failed"),
        (("some-org",), "not a GitHub user"),
        (tuple(f"user{i}" for i in range(7)), "at most 6"),
        (("bad login!",), "is not a GitHub login"),
    ):
        sync, _ = make_sync(home, project, gh, reviewers=reviewers)
        with pytest.raises(CiSyncError, match=message):
            sync.run(apply=False)


def test_webui_environment_only_with_web_credentials(home: Path, project: Path) -> None:
    """With the web login: e2e-org2-webui is managed and is the only environment receiving it."""
    write_env(home, web=True)
    gh = Gh()
    sync, _ = make_sync(home, project, gh)
    sync.run(apply=True)
    secrets = {(args[2], args[4]) for args, _ in gh.writes() if args[:2] == ("secret", "set")}
    assert ("E2E_ADMIN_PASSWORD", "e2e-org2-webui") in secrets and ("E2E_ADMIN_TOTP_SEED", "e2e-org2-webui") in secrets
    assert not [
        env
        for name, env in secrets
        if name in ("E2E_ADMIN_PASSWORD", "E2E_ADMIN_TOTP_SEED") and env != "e2e-org2-webui"
    ]
    assert ("E2E_AUTHOR_TOKEN", "e2e-org2-webui") not in secrets  # the webui job does not read it
    put = [args[3] for args, _ in gh.writes() if args[:3] == ("api", "-X", "PUT")]
    assert put[-1] == f"repos/{REPO}/environments/e2e-org2-webui"


# --- repository variables ---------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("existing", "nightly", "expected"),
    [
        ({}, False, [("E2E_INSTANCES", '["free","team","enterprise","org2"]')]),
        ({"E2E_TARGETS": '["free"]'}, False, [("E2E_INSTANCES", '["free","org2"]')]),
        ({"E2E_INSTANCES": '["free","x"]'}, False, [("E2E_INSTANCES", '["free","x","org2"]')]),
        ({"E2E_INSTANCES": '["org2"]'}, False, []),
        ({"E2E_INSTANCES": '["org2"]', "E2E_TARGETS": '["free"]'}, True, [("E2E_TARGETS", '["free","org2"]')]),
        ({}, True, [("E2E_INSTANCES", '["free","team","enterprise","org2"]'), ("E2E_TARGETS", '["free","org2"]')]),
        ({"E2E_TARGETS": '["free"]'}, True, [("E2E_INSTANCES", '["free","org2"]'), ("E2E_TARGETS", '["free","org2"]')]),
        ({"E2E_TARGETS": '["org2"]'}, True, []),
        ({"E2E_INSTANCES": '["org2"]', "E2E_TARGETS": '["org2"]'}, True, []),
    ],
)
def test_repository_variables(
    home: Path, project: Path, existing: dict[str, str], nightly: bool, expected: list[tuple[str, str]]
) -> None:
    """E2E_INSTANCES gains the instance (created from the workflows' fallback); --nightly adds it to E2E_TARGETS."""
    gh = Gh(repo_variables=existing)
    sync, _ = make_sync(home, project, gh, nightly=nightly)
    sync.run(apply=True)
    found = [(args[2], args[4]) for args, _ in gh.writes() if args[:2] == ("variable", "set") and "--env" not in args]
    assert found == expected


def test_an_instance_dispatchable_through_the_fallback_needs_no_variable(home: Path, project: Path) -> None:
    """Instance free without E2E_INSTANCES: already allowed by the default list, nothing created."""
    directory = home / ".config" / "otterdog-e2e"
    shutil.copy(directory / "org2.env", directory / "free.env")
    gh = Gh()
    echoed: list[str] = []
    CiSync("free", environ={"HOME": str(home)}, project_root=project, gh=gh, echo=echoed.append).run(apply=True)
    assert not [args for args, _ in gh.writes() if args[:3] == ("variable", "set", "E2E_INSTANCES")]
    assert "free is dispatchable already" in "\n".join(echoed)


def test_nightly_of_a_default_instance_keeps_the_allowlist_and_the_nightly_default(home: Path, project: Path) -> None:
    """``ci-sync --target team --nightly`` without E2E_INSTANCES and E2E_TARGETS: E2E_INSTANCES is created from the
    default instances first (else the new E2E_TARGETS would become the allowlist), E2E_TARGETS from ["free"] + team."""
    directory = home / ".config" / "otterdog-e2e"
    shutil.copy(directory / "org2.env", directory / "team.env")
    gh = Gh()
    echoed: list[str] = []
    sync = CiSync("team", environ={"HOME": str(home)}, project_root=project, gh=gh, echo=echoed.append, nightly=True)
    sync.run(apply=True)
    found = [(args[2], args[4]) for args, _ in gh.writes() if args[:2] == ("variable", "set") and "--env" not in args]
    assert found == [("E2E_INSTANCES", '["free","team","enterprise"]'), ("E2E_TARGETS", '["free","team"]')]
    output = "\n".join(echoed)
    assert 'repository variable E2E_TARGETS: created from the nightly and janitor default ["free"] + team' in output
    assert "repository variable E2E_INSTANCES: created from the default instances + team (before E2E_TARGETS" in output


def test_a_malformed_repository_list_is_refused(home: Path, project: Path) -> None:
    """E2E_INSTANCES that is not a JSON list of names: fix it first."""
    sync, _ = make_sync(home, project, Gh(repo_variables={"E2E_INSTANCES": "free,team"}))
    with pytest.raises(CiSyncError, match="E2E_INSTANCES is not a JSON list"):
        sync.run(apply=False)


# --- refusals and failures --------------------------------------------------------------------------------------------
def test_refused_in_ci(home: Path, project: Path) -> None:
    """CI set: nothing read, nothing called."""
    gh = Gh()
    sync, _ = make_sync(home, project, gh, environ={"GITHUB_ACTIONS": "true"})
    with pytest.raises(CiSyncError, match="refused when CI is set"):
        sync.run(apply=True)
    assert not gh.calls


def test_a_machine_token_as_gh_credential_is_refused(home: Path, project: Path) -> None:
    """GH_TOKEN holding a token of the instance: refused before any gh call of the default runner."""
    sync, _ = make_sync(home, project, Gh(), environ={"GH_TOKEN": SECRETS["E2E_ADMIN_TOKEN"]})
    sync.values = sync.load_values()
    with pytest.raises(CiSyncError, match="GH_TOKEN holds a token of"):
        sync.gh_env()


def test_gh_logged_in_as_a_machine_account_is_refused(home: Path, project: Path) -> None:
    """gh auth as e2e-admin: refused (the operator's own account only)."""
    sync, _ = make_sync(home, project, Gh(user={"login": "E2E-Admin", "id": 3, "type": "User"}))
    with pytest.raises(CiSyncError, match="a machine account of org2"):
        sync.run(apply=False)


def test_a_variable_holding_a_secret_is_refused(home: Path, project: Path) -> None:
    """A non-secret variable whose value is a registered secret is never sent with --body."""
    write_env(home, web=False, extra=f'E2E_CONFIGS_REPO="{SECRETS["E2E_ADMIN_TOKEN"]}"')
    gh = Gh()
    sync, _ = make_sync(home, project, gh)
    with pytest.raises(CiSyncError, match="E2E_CONFIGS_REPO: the value holds a secret"):
        sync.run(apply=True)
    assert not gh.writes()


def test_missing_instance_values_are_refused(home: Path, project: Path, tmp_path: Path) -> None:
    """No env file, no org, no profile: run setup first."""
    sync, _ = make_sync(tmp_path / "nobody", project, Gh())
    with pytest.raises(CiSyncError, match="does not exist: run `otterdog-e2e setup --target org2` first"):
        sync.run(apply=False)
    path = home / ".config" / "otterdog-e2e" / "org2.env"
    path.write_text("E2E_ORG=x\n")
    with pytest.raises(CiSyncError, match="lacks E2E_ORG_ID"):
        make_sync(home, project, Gh())[0].run(apply=False)
    path.write_text("E2E_ORG=x\nE2E_ORG_ID=1\n")
    with pytest.raises(CiSyncError, match="lacks E2E_PROFILE"):
        make_sync(home, project, Gh())[0].run(apply=False)


def test_an_instance_named_after_a_yml_profile_defaults_its_profile(home: Path, project: Path) -> None:
    """No E2E_PROFILE: targets/<instance>.yml counts like .yaml (settings.TARGET_FILE_SUFFIXES)."""
    path = home / ".config" / "otterdog-e2e" / "org2.env"
    lines = [line for line in path.read_text().splitlines() if not line.startswith("E2E_PROFILE=")]
    path.write_text("\n".join(lines) + "\n")
    shutil.copy(project / "targets" / "free.yaml", project / "targets" / "org2.yml")
    gh = Gh()
    make_sync(home, project, gh)[0].run(apply=True)
    profiles = {args[4]: args[6] for args, _ in gh.writes() if args[:3] == ("variable", "set", "E2E_PROFILE")}
    assert profiles == {"e2e-org2": "org2", "e2e-org2-untrusted": "org2"}


def test_a_failed_operation_stops_and_an_existing_policy_is_fine(home: Path, project: Path) -> None:
    """An existing branch policy is tolerated; a refused secret stops the run with gh's (redacted) message."""
    gh = Gh(
        fail={
            "api -X POST": (1, "gh: Name already exists (HTTP 422)"),
            "secret set E2E_AUTHOR_TOKEN": (1, f"HTTP 403: Resource not accessible {SECRETS['E2E_AUTHOR_TOKEN']}"),
        }
    )
    sync, echoed = make_sync(home, project, gh)
    with pytest.raises(CiSyncError, match=r"secret E2E_AUTHOR_TOKEN in e2e-org2 .*gh failed \(1\)") as error:
        sync.run(apply=True)
    assert SECRETS["E2E_AUTHOR_TOKEN"] not in str(error.value)
    assert "ok: environment e2e-org2: deployment branch policy main" in "\n".join(echoed)
    assert not [args for args, _ in gh.calls if args[:2] == ("variable", "set") and args[2] == "E2E_INSTANCES"]


def test_the_default_runner_uses_procs_with_the_operator_home(
    home: Path, project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """procs.run(["gh", ...], keep_home=True, input=<secret>) with the exported gh credential passed through."""
    calls: list[dict[str, Any]] = []
    gh = Gh()

    def fake_run(argv: Sequence[str], **kwargs: Any) -> CompletedProcess[str]:
        """Record and answer like gh."""
        calls.append({"argv": list(argv), **kwargs})
        return gh(list(argv)[1:], kwargs.get("input"))

    monkeypatch.setattr(procs, "run", fake_run)
    sync = CiSync(
        "org2",
        environ={"HOME": str(home), "GH_TOKEN": "gho_operator_token_000000000000"},
        project_root=project,
        repo=REPO,
    )
    sync.run(apply=True)
    assert all(call["argv"][0] == "gh" and call["keep_home"] is True for call in calls)
    assert all(call["extra_env"]["GH_TOKEN"] == "gho_operator_token_000000000000" for call in calls)
    assert all(call["extra_env"]["GH_PROMPT_DISABLED"] == "1" for call in calls)
    secret = next(call for call in calls if call["argv"][1:4] == ["secret", "set", "E2E_ADMIN_TOKEN"])
    assert secret["input"] == SECRETS["E2E_ADMIN_TOKEN"]
    assert not [call for call in calls if call["argv"][1:3] == ["repo", "view"]]  # --repo given


def test_a_missing_gh_is_reported(home: Path, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """gh not installed: a clear error."""

    def missing(argv: Sequence[str], **kwargs: Any) -> CompletedProcess[str]:
        """Popen of a missing executable."""
        raise FileNotFoundError("gh")

    monkeypatch.setattr(procs, "run", missing)
    with pytest.raises(CiSyncError, match="gh \\(the GitHub CLI\\) is not installed"):
        CiSync("org2", environ={"HOME": str(home)}, project_root=project).run(apply=False)


# --- the CLI command --------------------------------------------------------------------------------------------------
def test_cli_ci_sync_dry_run(home: Path, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``ci-sync --target org2``: dry run through procs (faked), exit 0, names only."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        "otterdog_e2e.settings.harness_settings", lambda environ=None: type("S", (), {"project_root": project})()
    )
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *args: None)
    gh = Gh()
    monkeypatch.setattr(procs, "run", lambda argv, **kwargs: gh(list(argv)[1:], kwargs.get("input")))
    result = CliRunner().invoke(cli.main, ["ci-sync", "--target", "org2"])
    assert result.exit_code == 0, result.output
    assert "(dry run)" in result.output and not gh.writes()
    assert SECRETS["E2E_ADMIN_TOKEN"] not in result.output
    gh.branch_policies["e2e-org2"] = [{"id": 7, "name": "*", "type": "branch"}]
    result = CliRunner().invoke(cli.main, ["ci-sync", "--target", "org2"])
    assert result.exit_code == 1 and "--prune-branch-policies" in result.output
    result = CliRunner().invoke(cli.main, ["ci-sync", "--target", "org2", "--prune-branch-policies"])
    assert result.exit_code == 0 and "would delete the deployment branch policy '*' (branch)" in result.output


def test_cli_ci_sync_errors(home: Path, project: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A list of targets is a usage error; CI is a one-line error."""
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *args: None)
    result = CliRunner().invoke(cli.main, ["ci-sync", "--target", "a,b"])
    assert result.exit_code == 2 and "take one instance" in result.output
    monkeypatch.setattr(
        "otterdog_e2e.settings.harness_settings", lambda environ=None: type("S", (), {"project_root": project})()
    )
    monkeypatch.setenv("CI", "true")
    result = CliRunner().invoke(cli.main, ["ci-sync", "--target", "org2", "--apply"])
    assert result.exit_code == 1 and "Error: ci-sync uses your own gh login" in result.output


# --- vault references --------------------------------------------------------------------------------------------------
REFERENCES = {
    "vault:e2e/org2/admin/token": SECRETS["E2E_ADMIN_TOKEN"],
    "pass:e2e/org2/author": SECRETS["E2E_AUTHOR_TOKEN"],
}
VAULT_ROLES = """\
E2E_ADMIN_TOKEN="vault:e2e/org2/admin/token"
E2E_AUTHOR_TOKEN="pass:e2e/org2/author"
E2E_VAULT_ADDR=https://vault.example.org
E2E_VAULT_ROLE=otterdog-e2e-org2
E2E_VAULT_ROLE_UNTRUSTED=otterdog-e2e-org2-untrusted"""


@pytest.fixture
def vault(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The operator's vaults: REFERENCES resolve, any other reference is unreadable (VaultError)."""

    def resolve(value: str, environ: object) -> str:
        """REFERENCES[value]."""
        if value not in REFERENCES:
            raise VaultError(f"{value}: not found")
        return REFERENCES[value]

    monkeypatch.setattr("otterdog_e2e.onboard.cisync.resolve", resolve)
    return REFERENCES


def env_writes(gh: Gh, command: str) -> dict[tuple[str, str], str | None]:
    """(name, environment) -> stdin (secrets) or --body (variables) of the environment writes of ``command``."""
    return {
        (args[2], args[4]): stdin if command == "secret" else args[6]
        for args, stdin in gh.writes()
        if args[:2] == (command, "set") and "--env" in args
    }


def test_vault_references_stay_references_for_jobs_with_a_vault_role(
    home: Path, project: Path, vault: dict[str, str]
) -> None:
    """With E2E_VAULT_ROLE and E2E_VAULT_ADDR a vault: reference is stored as it is (the jobs read Vault with their
    OIDC token), a pass: reference is resolved here and its value stored; every environment gets the Vault
    variables, the untrusted one its own role; the dry run says which secret is a reference."""
    write_env(home, web=False, extra=VAULT_ROLES)
    sync, echoed = make_sync(home, project, Gh(repo_variables={"E2E_TARGETS": '["free"]'}))
    sync.run(apply=False)
    assert "  secret E2E_ADMIN_TOKEN in e2e-org2 (vault reference on stdin, the jobs read the value)" in echoed
    assert "  secret E2E_AUTHOR_TOKEN in e2e-org2 (value of its pass reference, on stdin)" in echoed
    gh = Gh(repo_variables={"E2E_TARGETS": '["free"]'})
    sync, _ = make_sync(home, project, gh)
    sync.run(apply=True)
    secrets, variables = env_writes(gh, "secret"), env_writes(gh, "variable")
    for env in ("e2e-org2", "e2e-org2-untrusted"):
        assert secrets[("E2E_ADMIN_TOKEN", env)] == "vault:e2e/org2/admin/token"
        assert secrets[("E2E_AUTHOR_TOKEN", env)] == SECRETS["E2E_AUTHOR_TOKEN"]
        assert variables[("E2E_VAULT_ADDR", env)] == "https://vault.example.org"
    assert variables[("E2E_VAULT_ROLE", "e2e-org2")] == "otterdog-e2e-org2"
    assert variables[("E2E_VAULT_ROLE", "e2e-org2-untrusted")] == "otterdog-e2e-org2-untrusted"
    assert not [name for name, _ in variables if name.startswith("E2E_VAULT_ROLE_")]


def test_vault_references_are_resolved_without_a_vault_role(home: Path, project: Path, vault: dict[str, str]) -> None:
    """Without E2E_VAULT_ROLE the jobs cannot read Vault: the reference is resolved here and the value stored."""
    write_env(home, web=False, extra='E2E_ADMIN_TOKEN="vault:e2e/org2/admin/token"')
    gh = Gh(repo_variables={"E2E_TARGETS": '["free"]'})
    sync, _ = make_sync(home, project, gh)
    sync.run(apply=True)
    assert env_writes(gh, "secret")[("E2E_ADMIN_TOKEN", "e2e-org2")] == SECRETS["E2E_ADMIN_TOKEN"]


@pytest.mark.parametrize(
    ("extra", "message"),
    [
        ('E2E_ADMIN_TOKEN="pass:e2e/org2/nope"', "E2E_ADMIN_TOKEN: pass:e2e/org2/nope: not found"),
        (
            'E2E_ADMIN_TOKEN="vault:e2e/org2/admin/token"\nE2E_VAULT_ROLE=otterdog-e2e-org2',
            "E2E_ADMIN_TOKEN: a vault reference read by the jobs needs E2E_VAULT_ADDR in the env file",
        ),
    ],
)
def test_unusable_references_are_refused(
    home: Path, project: Path, vault: dict[str, str], extra: str, message: str
) -> None:
    """An unreadable reference, or a vault reference for jobs that would not know the Vault, stops ci-sync."""
    write_env(home, web=False, extra=extra)
    sync, _ = make_sync(home, project, Gh(repo_variables={"E2E_TARGETS": '["free"]'}))
    with pytest.raises(CiSyncError, match=None) as info:
        sync.run(apply=True)
    assert message in str(info.value)
