"""End-to-end test harness for otterdog (CLI, GitHub App webapp and webhooks) against dedicated GitHub test orgs."""

from __future__ import annotations

from importlib.resources import files
from importlib.resources.abc import Traversable

__version__ = "0.1.0"

RESOURCE_NAMES = ("org.jsonnet.j2", "compose.e2e.yaml", "hypercorn.toml.j2")


def resource(name: str) -> Traversable:
    """Package resource ``otterdog_e2e/resources/<name>`` (ValueError for unknown names)."""
    if name not in RESOURCE_NAMES:
        raise ValueError(f"unknown resource {name!r}, expected one of {RESOURCE_NAMES}")
    return files("otterdog_e2e") / "resources" / name


def read_resource(name: str) -> str:
    """Text of a package resource."""
    return resource(name).read_text(encoding="utf-8")
