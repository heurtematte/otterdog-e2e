"""shards.py and scenarios/shards.yaml: which test organization runs which live items.

The map of the repository is checked against the items of the repository: every live item has exactly one shard (the
default one takes the rest), an item never lands on a shard whose plan lacks a capability it requires (it would be
skipped there, so nowhere), the App's items land where the App is, the profiles exist.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from click.testing import CliRunner

from otterdog_e2e.capabilities import PLAN_MATRIX
from otterdog_e2e.settings import profile_names
from otterdog_e2e.shards import (
    SHARDS_FILE,
    ItemFacts,
    ShardError,
    load_shards,
    parse_shards,
    shard_loads,
    static_items,
)
from otterdog_e2e.testing.fakes import make_settings

ROOT = Path(__file__).resolve().parents[2]
MAP = {
    "shards": {
        "paid": {"profile": "enterprise", "match": [{"tiers": ["enterprise"]}, {"plans": ["team", "enterprise"]}]},
        "app": {"profile": "free", "match": [{"tiers": ["webapp"]}, {"requires": ["app"]}]},
        "whole": {"profile": "free", "match": [{"org_level": True, "tiers": ["cli"]}]},
        "repos": {"profile": "free", "match": [{"domains": ["repo"]}, {"modules": ["tests/cli/test_repo_*.py"]}]},
        "rest": {"profile": "free", "default": True},
    }
}


# --- the map ----------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("facts", "shard"),
    [
        (ItemFacts("enterprise"), "paid"),
        (ItemFacts("cli", domain="repo", plan="team"), "paid"),  # the first shard that matches wins
        (ItemFacts("webapp", org_level=True), "app"),
        (ItemFacts("cli", domain="bpr", requires=("private_repo_rulesets", "app")), "app"),
        (ItemFacts("cli", domain="secrets", org_level=True), "whole"),
        (ItemFacts("webhooks", org_level=True), "rest"),  # every key of an entry must match
        (ItemFacts("cli", domain="repo"), "repos"),
        (ItemFacts("cli", module="tests/cli/test_repo_template.py"), "repos"),
        (ItemFacts("cli", module="tests/cli/test_commands_read.py"), "rest"),
        (ItemFacts("differential"), "rest"),
    ],
)
def test_an_item_belongs_to_the_first_shard_that_matches_else_the_default(facts: ItemFacts, shard: str) -> None:
    """Entries are ORed, the keys of an entry ANDed; the default shard takes what no other shard matches."""
    assert parse_shards(MAP).assign(facts).name == shard


@pytest.mark.parametrize(
    ("data", "message"),
    [
        ({}, "expected a mapping 'shards'"),
        ({"shards": {"Bad Name": {"profile": "free", "default": True}}}, "shard Bad Name"),
        ({"shards": {"a": {"profile": "free", "match": [{"tiers": ["cli"]}]}}}, "exactly one shard is the default"),
        ({"shards": {"a": {"profile": "free", "default": True, "x": 1}}}, "unknown key(s) x"),
        ({"shards": {"a": {"default": True}}}, "profile names the profile"),
        ({"shards": {"a": {"profile": "free"}, "b": {"profile": "free", "default": True}}}, "only the default shard"),
        ({"shards": {"a": {"profile": "free", "default": True, "match": [{"tier": ["cli"]}]}}}, "unknown key(s) tier"),
        ({"shards": {"a": {"profile": "free", "default": True, "match": [{"tiers": "cli"}]}}}, "non-empty list"),
        ({"shards": {"a": {"profile": "free", "default": True, "match": [{"org_level": "yes"}]}}}, "true or false"),
        ({"shards": {"a": {"profile": "free", "default": True, "match": [{}]}}}, "a match entry is a mapping"),
    ],
)
def test_invalid_maps_are_refused(data: Any, message: str) -> None:
    """Names are instance names, keys are known, values typed, exactly one default, the others match something."""
    with pytest.raises(ShardError, match=message.replace("(", r"\(").replace(")", r"\)")):
        parse_shards(data)


def test_an_unknown_shard_names_the_known_ones() -> None:
    """ShardMap.get."""
    with pytest.raises(ShardError, match="unknown shard 'nope': paid, app, whole, repos, rest"):
        parse_shards(MAP).get("nope")


# --- the map of the repository -----------------------------------------------------------------------------------------
def repository_map() -> Any:
    """scenarios/shards.yaml."""
    shards = load_shards(ROOT)
    assert shards is not None, f"{SHARDS_FILE} is missing"
    return shards


def test_the_shards_of_the_repository() -> None:
    """Five shards: their profiles exist, the default one is the last, every live item has a shard."""
    shards = repository_map()
    assert shards.names == ["enterprise", "webapp", "org-level", "repos", "automation"]
    assert {shard.profile for shard in shards.shards} <= set(profile_names(make_settings(ROOT)))
    assert [shard.name for shard in shards.shards if shard.default] == ["automation"]
    loads = shard_loads(shards, static_items(ROOT))
    assert all(load.items for load in loads), [load.shard.name for load in loads if not load.items]
    assert sum(len(load.items) for load in loads) == len(static_items(ROOT))


def test_no_item_lands_where_it_would_be_skipped() -> None:
    """An item requiring a capability of a higher plan, or a higher plan, lands on a shard whose profile has it; the
    App's items on the shard of the App; the web-UI tier on the shard of the whole organization."""
    shards = repository_map()
    plan_caps = {plan: {str(cap) for cap in caps} for plan, caps in PLAN_MATRIX.items()}
    above_free = set().union(*plan_caps.values()) - plan_caps["free"]
    for item in static_items(ROOT):
        shard = shards.assign(item.facts)
        needs = set(item.facts.requires) & above_free
        assert needs <= plan_caps[shard.profile], f"{item.name} needs {sorted(needs)}, on {shard.name}"
        if item.facts.plan != "free":
            assert shard.profile == "enterprise", f"{item.name} needs plan {item.facts.plan}, on {shard.name}"
        if "app" in item.facts.requires or item.facts.tier in ("webapp", "webhooks"):
            assert shard.name == "webapp", item.name
        if item.facts.tier == "web_ui" or (item.facts.org_level and item.facts.tier == "cli"):
            assert shard.name in ("org-level", "enterprise"), item.name


def test_the_enterprise_shard_takes_every_capability_a_free_organization_lacks() -> None:
    """Its `requires` entry names exactly the plan capabilities Free does not have: a new one must be added there."""
    shards = repository_map()
    plan_caps = {plan: {str(cap) for cap in caps} for plan, caps in PLAN_MATRIX.items()}
    above_free = set().union(*plan_caps.values()) - plan_caps["free"]
    taken = set().union(*(rule.requires or set() for rule in shards.get("enterprise").rules))
    assert above_free <= taken, sorted(above_free - taken)


# --- otterdog-e2e shards --------------------------------------------------------------------------------------------------
def test_shards_command_shows_what_each_shard_runs(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sizes per shard, the instances whose env file selects one, and the domains and modules of each."""
    from otterdog_e2e import cli

    config = tmp_path / ".config" / "otterdog-e2e"
    config.mkdir(parents=True)
    (config / "repos.env").write_text("E2E_PROFILE=free\nE2E_SHARD=repos\nE2E_ORG=otterdog-e2e-repos\n")
    monkeypatch.setattr("otterdog_e2e.cli.maintenance._settings", lambda: make_settings(ROOT))
    result = CliRunner().invoke(cli.main, ["shards"], env={"HOME": str(tmp_path), "XDG_CONFIG_HOME": None})
    assert result.exit_code == 0, result.output
    lines = result.output.splitlines()
    assert lines[0].split() == ["SHARD", "PROFILE", "SCENARIOS", "STEPS", "TESTS", "INSTANCES"]
    assert next(line for line in lines if line.startswith("repos ")).split()[-1] == "repos"
    assert "automation (default)" in result.output and "  scenario domains: bpr, repo, teams" in result.output
    as_json = CliRunner().invoke(cli.main, ["shards", "--json"], env={"HOME": str(tmp_path)})
    assert as_json.exit_code == 0 and '"shard": "webapp"' in as_json.output
