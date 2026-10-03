"""Run identifiers and the naming rules of every GitHub object the harness creates (SPEC 7).

A run id is ``base36(unix seconds)`` (6 chars) followed by 2 random hex chars, e.g. ``"t3k9qa4f"``. Every object a run
creates carries it, so cleanup, the janitor and the removal guards can attribute objects to runs:

* repos, teams, rulesets, environments, custom properties: ``e2e-<id>-<slug>``
* secrets, variables: ``E2E_<ID>_<SLUG>``
* webhook URLs: ``https://otterdog-e2e.invalid/<id>/<slug>`` (the ``.invalid`` TLD never resolves)
* branches: ``e2e/<id>/<slug>``; otterdog open-pr branches: ``otterdog/e2e-<id>-<slug>``; the webapp's blueprint
  remediation branches ``otterdog/blueprint/<blueprint id>`` carry the run id of an ``e2e-<id>-<slug>`` blueprint id
  (branch_run_id)
"""

from __future__ import annotations

import re
import secrets
from dataclasses import dataclass, field
from datetime import UTC, datetime

RUN_ID_RE = re.compile(r"^[0-9a-z]{6}[0-9a-f]{2}$")
HOOK_HOST = "otterdog-e2e.invalid"
HOOK_BASE = f"https://{HOOK_HOST}/"
BLUEPRINT_BRANCH_PREFIX = "otterdog/blueprint/"  # remediation branches of the webapp: otterdog/blueprint/<id>
E2E_NAME_RE = re.compile(r"^(e2e-([0-9a-z]{6}[0-9a-f]{2})-|E2E_([0-9A-Z]{6}[0-9A-F]{2})_)")

# run ids whose timestamp falls outside this window are not considered run ids (human names such as "e2e-sandbox1-x")
PLAUSIBLE_FROM = datetime(2024, 1, 1, tzinfo=UTC)
PLAUSIBLE_UNTIL = datetime(2040, 1, 1, tzinfo=UTC)

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"
_ID = r"[0-9a-z]{6}[0-9a-f]{2}"
_REF_PREFIX = r"(?:refs/)?(?:heads/)?"
_RUN_ID_PATTERNS = (
    re.compile(rf"^e2e-({_ID})-"),
    re.compile(rf"^E2E_({_ID.upper()})_"),
    # anchored: a foreign URL merely mentioning the hook host (e.g. in a query string) is never attributed to a run
    re.compile(rf"^https?://{re.escape(HOOK_HOST)}/({_ID})/"),
    re.compile(rf"^{_REF_PREFIX}e2e/({_ID})/"),
    re.compile(rf"^{_REF_PREFIX}otterdog/e2e-({_ID})(?:-|$)"),
)
_DELETABLE_REF_RES = (
    re.compile(rf"^heads/e2e/({_ID})/.+$"),
    re.compile(rf"^heads/otterdog/e2e-({_ID})(?:-.*)?$"),
    re.compile(r"^tags/sut-.+$"),
    re.compile(rf"^tags/e2e-run/({_ID})$"),
    re.compile(r"^heads/e2e-lease$"),
)


def _base36(value: int, width: int) -> str:
    """Encode a non-negative integer in base36, zero-padded to ``width``."""
    digits = ""
    while value:
        value, rest = divmod(value, 36)
        digits = _BASE36[rest] + digits
    return digits.rjust(width, "0")


@dataclass(frozen=True)
class RunContext:
    """Identity of one harness run: derives every object name, branch and hook URL of the run."""

    run_id: str
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        """Reject run ids that do not match RUN_ID_RE."""
        if not RUN_ID_RE.match(self.run_id):
            raise ValueError(f"invalid run id {self.run_id!r} (expected {RUN_ID_RE.pattern})")

    @property
    def prefix(self) -> str:
        """Lower-case object prefix ``e2e-<id>``."""
        return f"e2e-{self.run_id}"

    @property
    def const_prefix(self) -> str:
        """Upper-case prefix ``E2E_<ID>_`` for secrets and variables."""
        return f"E2E_{self.run_id.upper()}_"

    @property
    def hook_base(self) -> str:
        """Base URL of this run's webhooks: ``https://otterdog-e2e.invalid/<id>/``."""
        return f"{HOOK_BASE}{self.run_id}/"

    def name(self, slug: str) -> str:
        """Name of a repo, team, ruleset, environment or custom property: ``e2e-<id>-<slug>``."""
        return f"{self.prefix}-{slug}"

    def const(self, slug: str) -> str:
        """Name of a secret or variable: ``E2E_<ID>_<SLUG>`` ('-' become '_')."""
        return f"{self.const_prefix}{slug.upper().replace('-', '_')}"

    def prop(self, slug: str) -> str:
        """Custom property name, same as name(); '_' become '-' since '_' names cannot hold multi_select values (OC-05)."""
        return self.name(slug.replace("_", "-"))

    def hook_url(self, slug: str) -> str:
        """Webhook URL under the never-resolving HOOK_HOST: ``https://otterdog-e2e.invalid/<id>/<slug>``."""
        return f"{self.hook_base}{slug}"

    def branch(self, slug: str) -> str:
        """Branch name ``e2e/<id>/<slug>``."""
        return f"e2e/{self.run_id}/{slug}"

    def repo_filter(self) -> str:
        """otterdog ``-r`` filter matching every repo of this run: ``e2e-<id>-*``."""
        return f"{self.prefix}-*"

    def needles(self) -> tuple[str, ...]:
        """Substrings identifying this run's objects in plan headers (PlanResult.objects_for)."""
        return (self.prefix + "-", self.const_prefix, self.hook_base)

    def template_vars(self) -> dict[str, str]:
        """Jinja variables of scenarios: run (id), p (``e2e-<id>``), P (``E2E_<ID>``), hook_base (``.../<id>/``)."""
        return {"run": self.run_id, "p": self.prefix, "P": self.const_prefix.rstrip("_"), "hook_base": self.hook_base}


def new_run_context(run_id: str | None = None, now: datetime | None = None) -> RunContext:
    """Create a RunContext; a new run id is base36(now) (6 chars) + 2 random hex chars, a given one is validated.

    A naive ``now`` is taken as UTC (SPEC 4).
    """
    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    if run_id is None:
        run_id = _base36(int(created_at.timestamp()), 6) + secrets.token_hex(1)
    return RunContext(run_id=run_id, created_at=created_at)


def run_id_timestamp(run_id: str) -> datetime | None:
    """Creation time encoded in a run id, or None when the id is malformed."""
    if not RUN_ID_RE.match(run_id):
        return None
    return datetime.fromtimestamp(int(run_id[:6], 36), tz=UTC)


def _plausible(run_id: str) -> bool:
    """True when the run id decodes to a creation time inside the plausible window (2024-2040)."""
    ts = run_id_timestamp(run_id)
    return ts is not None and PLAUSIBLE_FROM <= ts < PLAUSIBLE_UNTIL


def extract_run_id(name: str) -> str | None:
    """Run id carried by a name, constant, hook URL or branch/ref (see module docstring), or None."""
    for pattern in _RUN_ID_PATTERNS:
        match = pattern.search(name)
        if match:
            run_id = match.group(1).lower()
            return run_id if _plausible(run_id) else None
    return None


def branch_run_id(ref: str) -> str | None:
    """Run id of a pull request head branch (``refs/heads/`` optional): ``e2e/<id>/...``, ``otterdog/e2e-<id>-...``
    (open-pr) or a blueprint remediation branch ``otterdog/blueprint/e2e-<id>-...`` (the branch of a blueprint id of
    the run); None for any other branch."""
    branch = ref.removeprefix("refs/").removeprefix("heads/")
    if branch.startswith(BLUEPRINT_BRANCH_PREFIX):
        blueprint_id = branch.removeprefix(BLUEPRINT_BRANCH_PREFIX)
        return extract_run_id(blueprint_id) if is_e2e_name(blueprint_id) else None
    return extract_run_id(branch) if branch.startswith(("e2e/", "otterdog/e2e-")) else None


def is_e2e_name(name: str) -> bool:
    """True when ``name`` starts with an e2e prefix (E2E_NAME_RE) whose run id is plausible."""
    match = E2E_NAME_RE.match(name)
    if not match:
        return False
    return _plausible((match.group(2) or match.group(3)).lower())


def is_deletable_ref(ref: str) -> bool:
    """Mutator.delete_ref guard (SPEC 5.2): heads/e2e/<id>/…, heads/otterdog/e2e-<id>…, tags/sut-…, tags/e2e-run/<id>,
    heads/e2e-lease (a leading ``refs/`` is accepted)."""
    ref = ref.removeprefix("refs/")
    for pattern in _DELETABLE_REF_RES:
        match = pattern.match(ref)
        if match:
            return not match.groups() or _plausible(match.group(1))
    return False
