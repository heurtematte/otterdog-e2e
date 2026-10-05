"""``otterdog-e2e ci-sync``: the GitHub environments, variables and secrets of one instance (docs/onboarding.md).

Every call goes through the OPERATOR's own ``gh`` CLI login (never a machine account token): ``procs.run`` with the
operator's HOME (gh's configuration), GH_TOKEN / GITHUB_TOKEN / GH_HOST / GH_CONFIG_DIR passed through when exported
(procs strips credential variables from children), and a refusal when that credential is a token of the instance or
gh is logged in as one of its machine accounts. Secrets reach gh on stdin ONLY (``gh secret set NAME --env ENV`` reads
the value from stdin without --body); variables are non-secret (a name that looks secret, or a value holding a
registered secret, is refused) and passed with --body.

Environments of instance ``<i>`` (``gh api -X PUT repos/{repo}/environments/{env} --input -``, then the deployment
branch policy ``main``; there is no ``gh environment`` command):

* ``e2e-<i>``: deployment branches: custom policy, branch ``main`` only; reviewers are not touched;
* ``e2e-<i>-untrusted``: the same plus required reviewers (--reviewer, default: the gh user) and prevent_self_review
  (unless --allow-self-review);
* ``e2e-<i>-webui``: only when the web credentials (E2E_ADMIN_PASSWORD, E2E_ADMIN_TOTP_SEED) exist; the only
  environment that receives them.

"``main`` only" is enforced: the existing deployment branch policies are listed first (a ``*`` policy would keep any
branch deployable); policies other than the branch ``main`` are refused with their names unless
--prune-branch-policies (then deleted, each printed; the dry run says "would delete"). Before the values of an
environment, it is read back (``GET repos/{repo}/environments/{env}`` and its policies): custom branch policies, no
protected-branches policy, no policy but ``main``, and for ``-untrusted`` a required_reviewers rule holding every
expected reviewer id with the requested prevent_self_review; an environment whose protections differ gets no secret.

Names per environment: the ``${{ vars.X }}`` and ``${{ secrets.X }}`` the workflow jobs running in that kind of
environment read in their steps and env (.github/workflows/*.yml), always plus E2E_PROFILE; repository variables
(E2E_INSTANCES, E2E_TARGETS, E2E_WEB_UI_*) and GITHUB_TOKEN never. Values come from the instance env file
(E2E_APP_PRIVATE_KEY = the content of E2E_APP_PRIVATE_KEY_FILE when only the file is set); names without a value are
skipped and listed. Repository variables last: E2E_INSTANCES (JSON list of the dispatchable instances) gains the
instance, and with --nightly E2E_TARGETS too (created from the nightly/janitor default ``["free"]`` plus the instance
when absent). The workflows' allowlist is E2E_INSTANCES, else E2E_TARGETS, else the default instances: while
E2E_INSTANCES is absent it is created from that OLD allowlist plus the instance whenever the instance is not in it or
E2E_TARGETS changes (and before E2E_TARGETS), so the allowlist never loses an instance.

Dry run by default: the operations are printed with names, never values (the reads still run: repository, gh user,
reviewers, current repository variables, deployment branch policies); --apply runs them in order and stops at the
first failure (re-runnable: every operation is idempotent).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from otterdog_e2e.context import in_ci
from otterdog_e2e.onboard.envfile import check_instance_name, instance_env_path, read_env_file
from otterdog_e2e.procs import CompletedProcess
from otterdog_e2e.redact import REDACTOR, SECRET_KEY_RE
from otterdog_e2e.settings import DEFAULT_WEB_ENV, LOGIN_RE, TARGET_FILE_SUFFIXES, UPSTREAM_REPO_RE

TRUSTED, UNTRUSTED, WEBUI = "trusted", "untrusted", "webui"
ENVIRONMENT_KINDS = (TRUSTED, UNTRUSTED, WEBUI)
ENVIRONMENT_SUFFIXES: Mapping[str, str] = {TRUSTED: "", UNTRUSTED: "-untrusted", WEBUI: "-webui"}
INSTANCES_VARIABLE, TARGETS_VARIABLE = "E2E_INSTANCES", "E2E_TARGETS"
DEFAULT_INSTANCES = ("free", "team", "enterprise")  # the workflows' allowlist without E2E_INSTANCES / E2E_TARGETS
DEFAULT_NIGHTLY = ("free",)  # nightly.yml / janitor.yml: fromJSON(vars.E2E_TARGETS || '["free"]')
# repository-level variables of the workflows (job conditions and matrices): never copied into an environment
REPOSITORY_VARIABLES = frozenset({INSTANCES_VARIABLE, TARGETS_VARIABLE, "E2E_WEB_UI_ENABLED", "E2E_WEB_UI_TARGETS"})
ALWAYS_VARIABLES = frozenset({"E2E_PROFILE"})
WEB_SECRETS = frozenset({DEFAULT_WEB_ENV["password_env"], DEFAULT_WEB_ENV["totp_seed_env"]})
AUTOMATIC_SECRETS = frozenset({"GITHUB_TOKEN"})
APP_KEY_SECRET, APP_KEY_FILE = "E2E_APP_PRIVATE_KEY", "E2E_APP_PRIVATE_KEY_FILE"
DEPLOYMENT_BRANCH = "main"
BRANCH_POLICY_PAGE = 100  # one page of GET .../deployment-branch-policies (more is refused: not verifiable)
MAX_REVIEWERS = 6  # GitHub's limit of required reviewers per environment
GH_PASSTHROUGH = ("GH_TOKEN", "GITHUB_TOKEN", "GH_HOST", "GH_CONFIG_DIR")  # the operator's gh login and config
GH_SETTINGS: Mapping[str, str] = {"GH_PROMPT_DISABLED": "1", "GH_NO_UPDATE_NOTIFIER": "1"}
GH_TIMEOUT = 120.0
WORKFLOWS_DIR = Path(".github") / "workflows"
_EXPRESSION_RE = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_REFERENCE_RE = re.compile(r"\b(vars|secrets)\.([A-Za-z_][A-Za-z0-9_]*)")
# environment names of the e2e workflows: format('e2e-{0}', ...), e2e-${{ matrix.target }}, ... with a kind suffix
_ENVIRONMENT_RE = re.compile(r"e2e-(?:\{0\}|\$\{\{[^}]*\}\})(-untrusted|-webui)?")
_KIND_OF_SUFFIX = {suffix: kind for kind, suffix in ENVIRONMENT_SUFFIXES.items()}

GhRunner = Callable[[Sequence[str], str | None], CompletedProcess[str]]


class CiSyncError(RuntimeError):
    """ci-sync cannot go on (the message never contains a value)."""


@dataclass(frozen=True)
class EnvironmentNames:
    """Variables and secrets the workflow jobs of one environment kind read."""

    variables: frozenset[str] = frozenset()
    secrets: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Operation:
    """One gh call: what it does (names only), its arguments (never a secret) and its stdin (a secret or a JSON
    body, never shown); ``tolerate``: stderr fragments meaning the change is already there; ``preview``: the dry
    run's wording when it differs; ``check(stdout)``: raises CiSyncError when the answer is not the expected one
    (the run stops there)."""

    description: str
    args: tuple[str, ...]
    stdin: str | None = field(default=None, repr=False)
    tolerate: tuple[str, ...] = ()
    preview: str = ""
    check: Callable[[str], None] | None = field(default=None, repr=False, compare=False)


def environment_kinds(expression: str) -> set[str]:
    """Kinds (TRUSTED, UNTRUSTED, WEBUI) of the e2e environments a job's ``environment`` expression can name."""
    return {_KIND_OF_SUFFIX[match.group(1) or ""] for match in _ENVIRONMENT_RE.finditer(expression)}


def _strings(node: Any) -> Iterator[str]:
    """Every string value of a parsed YAML tree."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, Mapping):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for item in node:
            yield from _strings(item)


def references(texts: Iterator[str]) -> tuple[set[str], set[str]]:
    """(vars names, secrets names) referenced in ``${{ }}`` expressions of ``texts``."""
    variables: set[str] = set()
    secrets: set[str] = set()
    for text in texts:
        for expression in _EXPRESSION_RE.findall(text):
            for context, name in _REFERENCE_RE.findall(expression):
                (variables if context == "vars" else secrets).add(name)
    return variables, secrets


def _job_environment(job: Mapping[str, Any]) -> str:
    """The ``environment`` of a job as text (a mapping's ``name``)."""
    environment = job.get("environment")
    if isinstance(environment, Mapping):
        environment = environment.get("name")
    return environment if isinstance(environment, str) else ""


def workflow_names(workflows_dir: Path) -> dict[str, EnvironmentNames]:
    """Per environment kind, the vars and secrets read by the steps and env of the jobs running in it (job
    conditions and matrices are evaluated before the environment applies: not scanned)."""
    found: dict[str, tuple[set[str], set[str]]] = {kind: (set(), set()) for kind in ENVIRONMENT_KINDS}
    paths = sorted({*workflows_dir.glob("*.yml"), *workflows_dir.glob("*.yaml")}) if workflows_dir.is_dir() else []
    for path in paths:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            raise CiSyncError(f"cannot read the workflow {path}: {exc}") from None
        jobs = data.get("jobs") if isinstance(data, Mapping) else None
        for job in (jobs or {}).values() if isinstance(jobs, Mapping) else ():
            if not isinstance(job, Mapping):
                continue
            kinds = environment_kinds(_job_environment(job))
            if not kinds:
                continue
            variables, secrets = references(_strings([job.get("env"), job.get("steps")]))
            for kind in kinds:
                found[kind][0].update(variables)
                found[kind][1].update(secrets)
    return {kind: EnvironmentNames(frozenset(names[0]), frozenset(names[1])) for kind, names in found.items()}


def _user_path(value: str, environ: Mapping[str, str]) -> Path:
    """A path of the env file: a leading ``~`` is HOME of ``environ``."""
    if (value == "~" or value.startswith("~/")) and environ.get("HOME"):
        return Path(environ["HOME"]) / value[2:]
    return Path(value).expanduser()


def _json_list(text: str, name: str) -> list[str]:
    """A JSON list of instance names (CiSyncError otherwise)."""
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise CiSyncError(f"the repository variable {name} is not a JSON list of instance names: fix it first")
    return value


class CiSync:
    """Plan (and with apply run) the gh operations of one instance; every gh call goes through ``gh(args, stdin)``."""

    def __init__(
        self,
        instance: str,
        *,
        environ: Mapping[str, str],
        project_root: Path,
        repo: str | None = None,
        reviewers: Sequence[str] = (),
        allow_self_review: bool = False,
        nightly: bool = False,
        prune_branch_policies: bool = False,
        gh: GhRunner | None = None,
        echo: Callable[[str], None] | None = None,
    ) -> None:
        """Bind the options; nothing is read before run()."""
        self.instance = check_instance_name(instance)
        self.environ = environ
        self.project_root = project_root
        self.repo = repo
        self.reviewer_logins = tuple(dict.fromkeys(reviewers))
        self.allow_self_review = allow_self_review
        self.nightly = nightly
        self.prune_branch_policies = prune_branch_policies
        self.gh = gh or self._run_gh
        self._echo = echo or (lambda text: None)
        self.env_path = instance_env_path(self.instance, environ)
        self.values: dict[str, str] = {}
        self.skipped: dict[str, list[str]] = {}
        self.notes: list[str] = []

    def echo(self, text: str = "") -> None:
        """Print redacted text."""
        self._echo(REDACTOR(text))

    # --- gh -----------------------------------------------------------------------------------------------------
    def gh_env(self) -> dict[str, str]:
        """Extra environment of gh: the operator's exported gh credential/config (refused when it is a token of the
        instance) and no prompts."""
        machine = {value for key, value in self.values.items() if SECRET_KEY_RE.search(key)}
        env = dict(GH_SETTINGS)
        for key in GH_PASSTHROUGH:
            value = self.environ.get(key)
            if not value:
                continue
            if value in machine:
                raise CiSyncError(
                    f"{key} holds a token of {self.env_path}: ci-sync runs with YOUR gh login, never with a machine "
                    f"account token (unset {key})"
                )
            env[key] = value
        return env

    def _run_gh(self, args: Sequence[str], stdin: str | None) -> CompletedProcess[str]:
        """``gh <args>`` through procs.run with the operator's HOME (gh's login) and ``stdin``."""
        from otterdog_e2e import procs

        try:
            return procs.run(
                ["gh", *args],
                cwd=self.project_root,
                extra_env=self.gh_env(),
                timeout=GH_TIMEOUT,
                input=stdin,
                keep_home=True,
            )
        except FileNotFoundError:
            raise CiSyncError(
                "gh (the GitHub CLI) is not installed: https://cli.github.com, then `gh auth login`"
            ) from None

    def call(self, args: Sequence[str], *, stdin: str | None = None, allow_missing: bool = False) -> str | None:
        """stdout of a gh call; None for a 404 when ``allow_missing``; CiSyncError (redacted stderr) otherwise."""
        result = self.gh(list(args), stdin)
        if result.returncode == 0:
            return str(result.stdout or "")
        stderr = REDACTOR(str(result.stderr or "")).strip()
        if allow_missing and ("HTTP 404" in stderr or "Not Found" in stderr):
            return None
        raise CiSyncError(f"gh {' '.join(args[:3])} failed ({result.returncode}): {stderr[:500] or 'no message'}")

    def call_json(self, args: Sequence[str], *, allow_missing: bool = False) -> Any:
        """Decoded JSON stdout of a gh call (None for a 404 when ``allow_missing``)."""
        text = self.call(args, allow_missing=allow_missing)
        if text is None:
            return None
        try:
            return json.loads(text)
        except ValueError:
            raise CiSyncError(f"gh {' '.join(args[:2])}: unexpected output (not JSON)") from None

    # --- inputs -------------------------------------------------------------------------------------------------
    def load_values(self) -> dict[str, str]:
        """The instance env file (secrets registered with REDACTOR); E2E_PROFILE defaulted for an instance named after
        a profile (targets/<instance>.yaml or .yml); the App key read from E2E_APP_PRIVATE_KEY_FILE when no inline key
        is set."""
        if not self.env_path.is_file():
            raise CiSyncError(
                f"{self.env_path} does not exist: run `otterdog-e2e setup --target {self.instance}` first"
            )
        values = read_env_file(self.env_path)
        REDACTOR.add(*(value for key, value in values.items() if SECRET_KEY_RE.search(key)))
        missing = [key for key in ("E2E_ORG", "E2E_ORG_ID") if not values.get(key)]
        if missing:
            raise CiSyncError(
                f"{self.env_path} lacks {', '.join(missing)}: run `otterdog-e2e setup --target {self.instance}`"
            )
        if not values.get("E2E_PROFILE"):
            targets = self.project_root / "targets"
            if not any((targets / f"{self.instance}{suffix}").is_file() for suffix in TARGET_FILE_SUFFIXES):
                raise CiSyncError(f"{self.env_path} lacks E2E_PROFILE (the targets/<profile>.yaml of the instance)")
            values["E2E_PROFILE"] = self.instance
        if not values.get(APP_KEY_SECRET) and values.get(APP_KEY_FILE):
            path = _user_path(values[APP_KEY_FILE], self.environ)
            try:
                pem = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                raise CiSyncError(f"{APP_KEY_FILE}: cannot read {path} ({type(exc).__name__})") from None
            REDACTOR.add(pem, pem.strip())
            if "PRIVATE KEY-----" not in pem:
                raise CiSyncError(f"{APP_KEY_FILE}: {path} is not a PEM private key")
            values[APP_KEY_SECRET] = pem.strip() + "\n"
        return values

    def repository(self) -> str:
        """--repo, else the repository of the checkout (gh repo view)."""
        repo = self.repo or (self.call(["repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"]) or "")
        repo = repo.strip()
        if not UPSTREAM_REPO_RE.fullmatch(repo):
            raise CiSyncError(f"not a repository (owner/name): {repo!r}")
        return repo

    def gh_user(self) -> dict[str, Any]:
        """The gh login (GET /user); refused when it is one of the instance's machine accounts."""
        user = self.call_json(["api", "user"])
        login = str((user or {}).get("login") or "")
        machine = {
            value.lower() for key, value in self.values.items() if key.endswith("_LOGIN") and key.startswith("E2E_")
        }
        if login.lower() in machine:
            raise CiSyncError(
                f"gh is logged in as {login}, a machine account of {self.instance}: use your own account (gh auth login)"
            )
        return dict(user or {})

    def reviewers(self, user: Mapping[str, Any]) -> list[tuple[str, int]]:
        """(login, id) of the required reviewers of the untrusted environment (default: the gh user)."""
        logins = self.reviewer_logins or (str(user.get("login") or ""),)
        if len(logins) > MAX_REVIEWERS:
            raise CiSyncError(f"at most {MAX_REVIEWERS} required reviewers per environment")
        found = []
        for login in logins:
            if not LOGIN_RE.fullmatch(login):
                raise CiSyncError(f"--reviewer: {login!r} is not a GitHub login")
            data = (
                user
                if login.lower() == str(user.get("login") or "").lower()
                else self.call_json(["api", f"users/{login}"])
            )
            reviewer_id = (data or {}).get("id")
            if (
                isinstance(reviewer_id, bool)
                or not isinstance(reviewer_id, int)
                or (data or {}).get("type") not in (None, "User")
            ):
                raise CiSyncError(f"--reviewer {login}: not a GitHub user")
            found.append((str((data or {}).get("login") or login), reviewer_id))
        return found

    def repository_list(self, repo: str, name: str) -> list[str] | None:
        """A repository variable holding a JSON list (None when it does not exist)."""
        data = self.call_json(["api", f"repos/{repo}/actions/variables/{name}"], allow_missing=True)
        if data is None:
            return None
        return _json_list(str((data or {}).get("value") or ""), name)

    # --- plan ---------------------------------------------------------------------------------------------------
    def environment_name(self, kind: str) -> str:
        """``e2e-<instance>`` plus the kind's suffix."""
        return f"e2e-{self.instance}{ENVIRONMENT_SUFFIXES[kind]}"

    def branch_policies(self, repo: str, env: str) -> list[Mapping[str, Any]]:
        """The deployment branch policies of an environment (none when it or its custom policies do not exist);
        CiSyncError when one page does not list them all."""
        path = f"repos/{repo}/environments/{env}/deployment-branch-policies?per_page={BRANCH_POLICY_PAGE}"
        data = self.call_json(["api", path], allow_missing=True)
        data = data if isinstance(data, Mapping) else {}
        items = [item for item in data.get("branch_policies") or [] if isinstance(item, Mapping)]
        total = data.get("total_count")
        if isinstance(total, int) and not isinstance(total, bool) and total > len(items):
            raise CiSyncError(
                f"environment {env}: {total} deployment branch policies, more than one page lists: remove the extra "
                "ones in the repository settings first"
            )
        return items

    @staticmethod
    def _policy_label(policy: Mapping[str, Any]) -> str:
        """``'name' (type)`` of a deployment branch policy."""
        return f"{str(policy.get('name') or '?')!r} ({policy.get('type') or 'branch'})"

    def other_policies(self, repo: str, env: str) -> list[Mapping[str, Any]]:
        """The deployment branch policies of ``env`` but the branch DEPLOYMENT_BRANCH."""
        return [
            policy
            for policy in self.branch_policies(repo, env)
            if not (policy.get("name") == DEPLOYMENT_BRANCH and (policy.get("type") or "branch") == "branch")
        ]

    def protection_problems(self, data: Any, kind: str, reviewers: Sequence[tuple[str, int]]) -> list[str]:
        """What differs between an environment read back (GET repos/{repo}/environments/{env}) and the protections
        ci-sync sets: custom branch policies without protected branches, and for the untrusted one a required_reviewers
        rule with every expected reviewer id and the requested prevent_self_review."""
        data = data if isinstance(data, Mapping) else {}
        problems = []
        policy = data.get("deployment_branch_policy")
        policy = policy if isinstance(policy, Mapping) else {}
        if policy.get("custom_branch_policies") is not True or policy.get("protected_branches") is not False:
            problems.append(
                f"deployment branch policy {json.dumps(dict(policy) or None, sort_keys=True)} instead of custom "
                "branch policies without protected branches"
            )
        if kind != UNTRUSTED:
            return problems
        rules = [
            rule
            for rule in data.get("protection_rules") or []
            if isinstance(rule, Mapping) and rule.get("type") == "required_reviewers"
        ]
        if not rules:
            return [*problems, "no required reviewers"]
        found = {
            (item.get("reviewer") or {}).get("id")
            for rule in rules
            for item in rule.get("reviewers") or []
            if isinstance(item, Mapping) and item.get("type") == "User" and isinstance(item.get("reviewer"), Mapping)
        }
        missing = [login for login, reviewer_id in reviewers if reviewer_id not in found]
        if missing:
            problems.append(f"required reviewers without {', '.join(missing)}")
        expected = not self.allow_self_review
        if any(rule.get("prevent_self_review") is not expected for rule in rules):
            problems.append(f"prevent_self_review is not {str(expected).lower()}")
        return problems

    def check_environment(
        self, repo: str, env: str, kind: str, reviewers: Sequence[tuple[str, int]], stdout: str
    ) -> None:
        """The check of the read-back operation: CiSyncError (no secret of the environment is pushed) unless its
        protections are the ones set and no deployment branch policy but DEPLOYMENT_BRANCH is left."""
        try:
            data = json.loads(stdout)
        except ValueError:
            raise CiSyncError(f"environment {env}: unexpected answer of GET (not JSON)") from None
        problems = self.protection_problems(data, kind, reviewers)
        others = self.other_policies(repo, env)
        if others:
            problems.append(f"deployment branch policies {', '.join(map(self._policy_label, others))}")
        if problems:
            raise CiSyncError(
                f"environment {env}: its protections differ from the ones set ({'; '.join(problems)}): refusing to "
                "push its secrets (an organization or repository rule may override them: check its settings, then "
                "run ci-sync again)"
            )

    def environment_operations(self, repo: str, kind: str, reviewers: Sequence[tuple[str, int]]) -> list[Operation]:
        """PUT the environment (deployment branch policy, reviewers of the untrusted one), the main policy, the
        deletion of the other policies (--prune-branch-policies; refused otherwise), then the read-back check."""
        env = self.environment_name(kind)
        others = self.other_policies(repo, env)
        if others and not self.prune_branch_policies:
            raise CiSyncError(
                f"environment {env}: deployment branch policies other than {DEPLOYMENT_BRANCH} exist "
                f"({', '.join(map(self._policy_label, others))}): they keep those refs deployable to it and its "
                "secrets; re-run with --prune-branch-policies to delete them"
            )
        body: dict[str, Any] = {
            "deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}
        }
        detail = f"deployment branches: {DEPLOYMENT_BRANCH} only"
        if kind == UNTRUSTED:
            body["reviewers"] = [{"type": "User", "id": reviewer_id} for _, reviewer_id in reviewers]
            body["prevent_self_review"] = not self.allow_self_review
            detail += f", required reviewers {', '.join(login for login, _ in reviewers)}"
            detail += ", self-review allowed" if self.allow_self_review else ", prevent self-review"
        operations = [
            Operation(
                f"environment {env}: {detail}",
                ("api", "-X", "PUT", f"repos/{repo}/environments/{env}", "--input", "-"),
                stdin=json.dumps(body, sort_keys=True),
            ),
            Operation(
                f"environment {env}: deployment branch policy {DEPLOYMENT_BRANCH}",
                (
                    "api",
                    "-X",
                    "POST",
                    f"repos/{repo}/environments/{env}/deployment-branch-policies",
                    "-f",
                    f"name={DEPLOYMENT_BRANCH}",
                    "-f",
                    "type=branch",
                ),
                tolerate=("already exists", "already been taken"),
            ),
        ]
        for policy in others:
            policy_id = policy.get("id")
            if isinstance(policy_id, bool) or not isinstance(policy_id, int):
                raise CiSyncError(f"environment {env}: the policy {self._policy_label(policy)} has no numeric id")
            label = self._policy_label(policy)
            operations.append(
                Operation(
                    f"environment {env}: delete the deployment branch policy {label}",
                    ("api", "-X", "DELETE", f"repos/{repo}/environments/{env}/deployment-branch-policies/{policy_id}"),
                    tolerate=("http 404",),
                    preview=f"environment {env}: would delete the deployment branch policy {label}",
                )
            )
        operations.append(
            Operation(
                f"environment {env}: protections read back before its values",
                ("api", f"repos/{repo}/environments/{env}"),
                check=lambda stdout: self.check_environment(repo, env, kind, reviewers, stdout),
            )
        )
        return operations

    def value_operations(self, repo: str, kind: str, names: EnvironmentNames) -> list[Operation]:
        """``gh variable set`` / ``gh secret set`` (stdin) of the names the environment's jobs read."""
        env = self.environment_name(kind)
        variables = sorted((names.variables | ALWAYS_VARIABLES) - REPOSITORY_VARIABLES)
        secrets = sorted(names.secrets - AUTOMATIC_SECRETS - (frozenset() if kind == WEBUI else WEB_SECRETS))
        operations, skipped = [], []
        for name in variables:
            if SECRET_KEY_RE.search(name):
                raise CiSyncError(f"the workflows read vars.{name}, a secret name: refusing to store it as a variable")
            value = self.values.get(name, "")
            if not value:
                skipped.append(name)
                continue
            if REDACTOR(value) != value or "\n" in value or "\r" in value:
                raise CiSyncError(
                    f"{name}: the value holds a secret or a line break: refusing to store it as a variable"
                )
            operations.append(
                Operation(
                    f"variable {name} in {env}",
                    ("variable", "set", name, "--env", env, "--body", value, "--repo", repo),
                )
            )
        for name in secrets:
            value = self.values.get(name, "")
            if not value:
                skipped.append(name)
                continue
            operations.append(
                Operation(
                    f"secret {name} in {env} (value on stdin)",
                    ("secret", "set", name, "--env", env, "--repo", repo),
                    stdin=value,
                )
            )
        if skipped:
            self.skipped[env] = skipped
        return operations

    def repository_operations(self, repo: str) -> list[Operation]:
        """E2E_INSTANCES gains the instance; --nightly: E2E_TARGETS gains it (created from DEFAULT_NIGHTLY, what
        nightly and janitor fall back to, when absent). The workflows' allowlist is E2E_INSTANCES, else E2E_TARGETS,
        else DEFAULT_INSTANCES: while E2E_INSTANCES is absent, it is created from that old allowlist plus the instance
        when the instance is not in it or E2E_TARGETS changes, and set before E2E_TARGETS (never a shrinking
        allowlist)."""
        operations = []
        targets = self.repository_list(repo, TARGETS_VARIABLE)
        instances = self.repository_list(repo, INSTANCES_VARIABLE)
        nightly: Operation | None = None
        if self.nightly:
            if targets is None:
                default = json.dumps(list(DEFAULT_NIGHTLY))
                nightly = self._list_operation(
                    repo,
                    TARGETS_VARIABLE,
                    [*DEFAULT_NIGHTLY, self.instance],
                    f"created from the nightly and janitor default {default} + {self.instance} (scheduled runs start)",
                )
            elif self.instance in targets:
                self.notes.append(f"{TARGETS_VARIABLE} lists {self.instance} already")
            else:
                nightly = self._list_operation(
                    repo, TARGETS_VARIABLE, [*targets, self.instance], f"add {self.instance} (nightly and janitor)"
                )
        if instances is None:
            source = TARGETS_VARIABLE if targets is not None else "the default instances"
            base = list(targets) if targets is not None else list(DEFAULT_INSTANCES)
            if self.instance in base and nightly is None:
                self.notes.append(f"{self.instance} is dispatchable already ({INSTANCES_VARIABLE} unset, {source})")
            else:
                why = f" (before {TARGETS_VARIABLE} changes: the allowlist keeps {source})" if nightly else ""
                operations.append(
                    self._list_operation(
                        repo,
                        INSTANCES_VARIABLE,
                        [*base, self.instance],
                        f"created from {source} + {self.instance}{why}",
                    )
                )
        elif self.instance not in instances:
            operations.append(
                self._list_operation(repo, INSTANCES_VARIABLE, [*instances, self.instance], f"add {self.instance}")
            )
        else:
            self.notes.append(f"{INSTANCES_VARIABLE} lists {self.instance} already")
        if nightly is not None:
            operations.append(nightly)
        return operations

    @staticmethod
    def _list_operation(repo: str, name: str, items: Sequence[str], detail: str) -> Operation:
        """``gh variable set`` of a repository variable holding a JSON list."""
        body = json.dumps(list(dict.fromkeys(items)), separators=(",", ":"))
        return Operation(
            f"repository variable {name}: {detail}", ("variable", "set", name, "--body", body, "--repo", repo)
        )

    def plan(self) -> list[Operation]:
        """Every operation in order: environments with their values, then the repository variables."""
        repo = self.repository()
        user = self.gh_user()
        names = workflow_names(self.project_root / WORKFLOWS_DIR)
        web = all(self.values.get(name) for name in WEB_SECRETS)
        kinds = [TRUSTED, UNTRUSTED, *([WEBUI] if web else [])]
        if not web:
            self.notes.append(f"no web credentials in {self.env_path}: {self.environment_name(WEBUI)} not managed")
        reviewers = self.reviewers(user)
        if not self.allow_self_review and [login.lower() for login, _ in reviewers] == [
            str(user.get("login") or "").lower()
        ]:
            self.notes.append(
                "you are the only required reviewer and self-review is prevented: you cannot approve the untrusted "
                "runs you start (add --reviewer, or --allow-self-review)"
            )
        operations = []
        for kind in kinds:
            operations += self.environment_operations(repo, kind, reviewers)
            operations += self.value_operations(repo, kind, names[kind])
        operations += self.repository_operations(repo)
        self.repo = repo
        return operations

    # --- run ----------------------------------------------------------------------------------------------------
    def run(self, *, apply: bool) -> list[Operation]:
        """Plan, print (names only) and with ``apply`` execute the operations."""
        if in_ci(self.environ):
            raise CiSyncError("ci-sync uses your own gh login on your machine: refused when CI is set")
        self.values = self.load_values()
        operations = self.plan()
        self.echo(
            f"ci-sync of instance {self.instance} ({self.env_path}) -> {self.repo}" + ("" if apply else " (dry run)")
        )
        for operation in operations:
            self.echo(f"  {(not apply and operation.preview) or operation.description}")
        for env, names in self.skipped.items():
            self.echo(f"  {env}: not set in {self.env_path.name}, skipped: {', '.join(names)}")
        for note in self.notes:
            self.echo(f"note: {note}")
        if not apply:
            self.echo("dry run: re-run with --apply to perform these operations")
            return operations
        for operation in operations:
            self.execute(operation)
        self.echo(f"done: {len(operations)} operation(s)")
        return operations

    def execute(self, operation: Operation) -> None:
        """Run one operation (an already existing branch policy is fine) and its check; CiSyncError with gh's
        redacted message or the check's."""
        result = self.gh(list(operation.args), operation.stdin)
        stderr = REDACTOR(str(result.stderr or "")).strip()
        if result.returncode != 0 and not any(fragment in stderr.lower() for fragment in operation.tolerate):
            raise CiSyncError(
                f"{operation.description}: gh failed ({result.returncode}): {stderr[:500] or 'no message'}"
            )
        if operation.check is not None and result.returncode == 0:
            operation.check(str(result.stdout or ""))
        self.echo(f"ok: {operation.description}")
