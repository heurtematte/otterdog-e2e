"""The shards of the live tiers (scenarios/shards.yaml): which test organization runs which live items.

One organization serves one live session at a time (its org lease), so a run over several organizations only saves time
when each one runs its share of the live items instead of all of them. The shard map names the shards, in order: each
has the profile of its organization and ``match`` entries over the facts of an item (ItemFacts: tier, scenario domain,
test module, plan, required capabilities, org_level). A live item belongs to the first shard one of whose entries it
satisfies, else to the default shard, so every live item has exactly one shard.

The instance of an organization selects its shard with E2E_SHARD (its env file, written by ``otterdog-acceptance setup``); the
pytest plugin then deselects the live items of the other shards. Offline and unit items are never filtered, an explicit
scenario selection (--e2e-scenario) is never filtered, and without E2E_SHARD an instance runs every live item.
``otterdog-acceptance shards`` shows what each shard runs (static_items: the YAML scenarios and the live test modules).
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

SHARDS_FILE = "scenarios/shards.yaml"
SHARD_ENV = "E2E_SHARD"
SHARDS_LIST = "shards"  # ~/.config/otterdog-acceptance/lists/shards: the instances of the shards (run --target @shards)
# the tiers whose items the shards split (live tiers and the live observations of the differential tier)
SHARDED_TIERS = ("cli", "webhooks", "webapp", "web_ui", "enterprise", "differential")
LIST_KEYS = ("tiers", "domains", "modules", "plans", "requires")
MATCH_KEYS = (*LIST_KEYS, "org_level")
SHARD_KEYS = ("profile", "description", "match", "default")


class ShardError(ValueError):
    """An invalid shard map, or an unknown shard."""


@dataclass(frozen=True)
class ItemFacts:
    """What the shard rules read of a live item (``module``: its test module, from the project root)."""

    tier: str
    domain: str | None = None
    module: str | None = None
    plan: str = "free"
    requires: tuple[str, ...] = ()
    org_level: bool = False


@dataclass(frozen=True)
class Rule:
    """One ``match`` entry: satisfied when each key it sets is (lists: one of their values; modules: a glob)."""

    tiers: frozenset[str] | None = None
    domains: frozenset[str] | None = None
    modules: tuple[str, ...] | None = None
    plans: frozenset[str] | None = None
    requires: frozenset[str] | None = None
    org_level: bool | None = None

    def matches(self, facts: ItemFacts) -> bool:
        """Whether the item satisfies every key of the entry."""
        return (
            (self.tiers is None or facts.tier in self.tiers)
            and (self.domains is None or facts.domain in self.domains)
            and (self.modules is None or any(fnmatch.fnmatch(facts.module or "", glob) for glob in self.modules))
            and (self.plans is None or facts.plan in self.plans)
            and (self.requires is None or not self.requires.isdisjoint(facts.requires))
            and (self.org_level is None or facts.org_level == self.org_level)
        )


@dataclass(frozen=True)
class Shard:
    """One shard: the profile of its organization, what it runs, whether it takes the items no other shard does."""

    name: str
    profile: str
    description: str = ""
    rules: tuple[Rule, ...] = ()
    default: bool = False

    def matches(self, facts: ItemFacts) -> bool:
        """Whether one of its entries matches the item (the default shard takes the rest in ShardMap.assign)."""
        return any(rule.matches(facts) for rule in self.rules)


@dataclass(frozen=True)
class ShardMap:
    """The shards in order; ``source`` names the file in errors."""

    shards: tuple[Shard, ...]
    source: str = SHARDS_FILE

    @property
    def names(self) -> list[str]:
        """The names of the shards, in order."""
        return [shard.name for shard in self.shards]

    def get(self, name: str) -> Shard:
        """The shard ``name`` (ShardError naming the known ones)."""
        for shard in self.shards:
            if shard.name == name:
                return shard
        raise ShardError(f"unknown shard {name!r}: {', '.join(self.names)} ({self.source})")

    def assign(self, facts: ItemFacts) -> Shard:
        """The shard of an item: the first one that matches it, else the default shard."""
        return next(
            (shard for shard in self.shards if not shard.default and shard.matches(facts)),
            next(shard for shard in self.shards if shard.default),
        )


def _rule(data: Any, where: str) -> Rule:
    """One ``match`` entry (ShardError for an unknown key, an empty entry or a value of the wrong type)."""
    if not isinstance(data, Mapping) or not data:
        raise ShardError(f"{where}: a match entry is a mapping of {', '.join(MATCH_KEYS)}")
    unknown = sorted(set(map(str, data)) - set(MATCH_KEYS))
    if unknown:
        raise ShardError(f"{where}: unknown key(s) {', '.join(unknown)} (expected {', '.join(MATCH_KEYS)})")
    values: dict[str, Any] = {}
    for key in LIST_KEYS:
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
            raise ShardError(f"{where}: {key} is a non-empty list of names")
        values[key] = tuple(value) if key == "modules" else frozenset(value)
    if "org_level" in data:
        if not isinstance(data["org_level"], bool):
            raise ShardError(f"{where}: org_level is true or false")
        values["org_level"] = data["org_level"]
    return Rule(**values)


def parse_shards(data: Any, source: str = SHARDS_FILE) -> ShardMap:
    """The shard map of ``data`` (the YAML of SHARDS_FILE); ShardError when invalid: names must be instance names (the
    instance of a shard is usually named after it), exactly one shard is the default, the others match something."""
    from otterdog_acceptance.onboard.envfile import InstanceNameError, check_instance_name

    if not isinstance(data, Mapping) or not isinstance(data.get("shards"), Mapping) or not data["shards"]:
        raise ShardError(f"{source}: expected a mapping 'shards' of shard name -> shard")
    shards: list[Shard] = []
    for name, spec in data["shards"].items():
        where = f"{source}: shard {name}"
        try:
            check_instance_name(str(name))
        except InstanceNameError as exc:
            raise ShardError(f"{where}: {exc}") from None
        if not isinstance(spec, Mapping):
            raise ShardError(f"{where}: expected a mapping of {', '.join(SHARD_KEYS)}")
        unknown = sorted(set(map(str, spec)) - set(SHARD_KEYS))
        if unknown:
            raise ShardError(f"{where}: unknown key(s) {', '.join(unknown)} (expected {', '.join(SHARD_KEYS)})")
        profile = spec.get("profile")
        if not isinstance(profile, str) or not profile:
            raise ShardError(f"{where}: profile names the profile of its organization (targets/<profile>.yaml)")
        default = spec.get("default", False)
        if not isinstance(default, bool):
            raise ShardError(f"{where}: default is true or false")
        match = spec.get("match") or []
        if not isinstance(match, list) or (not match and not default):
            raise ShardError(f"{where}: match is a list of entries (only the default shard may have none)")
        rules = tuple(_rule(entry, f"{where}, match entry {index + 1}") for index, entry in enumerate(match))
        shards.append(Shard(str(name), profile, str(spec.get("description") or ""), rules, default))
    defaults = [shard.name for shard in shards if shard.default]
    if len(defaults) != 1:
        raise ShardError(f"{source}: exactly one shard is the default (default: true), got {len(defaults)}")
    return ShardMap(tuple(shards), source)


def load_shards(root: Path) -> ShardMap | None:
    """The shard map of the project (None without SHARDS_FILE)."""
    path = root / SHARDS_FILE
    if not path.is_file():
        return None
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ShardError(f"{SHARDS_FILE}: {exc}") from None
    return parse_shards(data, SHARDS_FILE)


# --- the items of the project, without pytest ------------------------------------------------------------------------
@dataclass(frozen=True)
class StaticItem:
    """A YAML scenario (``steps``: its step count) or a live test module (``tests``: its test functions)."""

    name: str
    facts: ItemFacts
    steps: int = 0
    tests: int = 0


@dataclass
class ShardLoad:
    """What one shard runs."""

    shard: Shard
    items: list[StaticItem] = field(default_factory=list)

    @property
    def scenarios(self) -> int:
        """Its YAML scenarios."""
        return sum(1 for item in self.items if item.steps)

    @property
    def steps(self) -> int:
        """The steps of its YAML scenarios."""
        return sum(item.steps for item in self.items)

    @property
    def tests(self) -> int:
        """Its test functions (Python modules)."""
        return sum(item.tests for item in self.items)


def static_items(root: Path) -> list[StaticItem]:
    """The live YAML scenarios and the live test modules of the project (tests/<tier>/test_*.py of the sharded tiers
    but the scenario runners, whose items are the scenarios), with what the shard rules read of them."""
    from otterdog_acceptance.scenarios.model import load_scenarios

    items: list[StaticItem] = []
    for tier in ("cli", "enterprise"):
        for scenario in load_scenarios(root / "scenarios" / tier, tier=tier):
            facts = ItemFacts(
                tier=tier,
                domain=scenario.source.parent.name,
                plan=scenario.min_plan,
                requires=tuple(scenario.requires),
                org_level=scenario.org_level,
            )
            items.append(StaticItem(scenario.id, facts, steps=len(scenario.steps)))
    for tier in SHARDED_TIERS:
        for path in sorted((root / "tests" / tier).glob("test_*.py")):
            source = path.read_text(encoding="utf-8")
            if "generate_scenario_tests" in source:
                continue  # a scenario runner: its items are the scenarios above
            tests = source.count("\ndef test_") + source.count("\nasync def test_") + source.count("    def test_")
            module = path.relative_to(root).as_posix()
            facts = ItemFacts(tier=tier, module=module, org_level="mark.org_level" in source)
            items.append(StaticItem(module, facts, tests=tests))
    return items


def shard_loads(shards: ShardMap, items: Iterable[StaticItem]) -> list[ShardLoad]:
    """What each shard runs, in the order of the map."""
    loads = {shard.name: ShardLoad(shard) for shard in shards.shards}
    for item in items:
        loads[shards.assign(item.facts).name].items.append(item)
    return list(loads.values())


def selected(shards: ShardMap, shard: str, facts: Sequence[ItemFacts]) -> list[bool]:
    """For each item, whether the shard ``shard`` runs it."""
    target = shards.get(shard)
    return [shards.assign(item) is target for item in facts]
