"""``otterdog-e2e assist coverage``: the features of the coverage matrix to work on, with their gap outlines.

Lists the features of scenarios/coverage.yaml (status, priority, tier, min_plan, ui_only, source, covered_by and the
gap outline, its ``needs`` split into the ones the harness already provides, ``available: ...``, and the missing
ones), filtered by status (default: gap and partial), priority, area and tier, sorted by priority, then status (gap
before partial before covered), then id. ``--feature <id>`` gives one feature (filters ignored) with what to imitate:
the covering items of the covered and partial features of its area (same tier first) and the scenarios tagged like the
area, the state of the outline's file and scenario id, and the commands that validate the change and regenerate
docs/coverage-matrix.md. The bundle ``assist/coverage/`` holds coverage.json and coverage.md.
"""

from __future__ import annotations

import difflib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from otterdog_e2e.assist.bundle import AssistError, AssistUsageError, json_text, md_cell, md_line, write_bundle
from otterdog_e2e.assist.repo import ProjectIndex
from otterdog_e2e.coverage_matrix import (
    PRIORITIES,
    REGENERATE,
    STATUSES,
    TIERS,
    MatrixError,
    MatrixProject,
    outline_needs,
)

BUNDLE_NAME = "coverage"
COVERAGE_JSON = "coverage.json"
COVERAGE_MD = "coverage.md"
DEFAULT_STATUSES = ("gap", "partial")
STATUS_ORDER = {"gap": 0, "partial": 1, "covered": 2}
MAX_IMITATE = 15
# scenario tags (selection.SCENARIO_TAGS) of the coverage areas: the scenarios to imitate for a feature of the area
AREA_TAGS: Mapping[str, tuple[str, ...]] = {
    "cli": ("cli",),
    "config": ("template", "cli"),
    "validation": ("offline",),
    "plan-semantics": ("offline", "repo"),
    "org-settings": ("org-settings",),
    "org-workflows": ("workflows",),
    "custom-properties": ("custom-properties",),
    "org-roles": ("org-roles",),
    "teams": ("teams",),
    "webhooks": ("webhooks",),
    "secrets-variables": ("secrets", "variables"),
    "repositories": ("repo",),
    "repo-workflows": ("workflows",),
    "branch-protection": ("bpr",),
    "rulesets": ("rulesets",),
    "environments": ("environments",),
    "receiver": ("webhooks-app",),
    "webapp-events": ("webapp", "webhooks-app"),
    "webapp-commands": ("webapp",),
    "webapp-pr": ("webapp",),
    "webapp-automerge": ("webapp",),
    "webapp-runtime": ("webapp",),
    "blueprints": ("webapp",),
    "policies": ("webapp",),
    "regressions": ("regression",),
}


@dataclass(frozen=True)
class CoverageQuery:
    """Filters of ``assist coverage`` (empty = no filter) or one feature id."""

    statuses: tuple[str, ...] = DEFAULT_STATUSES
    priorities: tuple[str, ...] = ()
    areas: tuple[str, ...] = ()
    tiers: tuple[str, ...] = ()
    feature: str | None = None


def parse_values(values: Iterable[str], allowed: Sequence[str], option: str) -> tuple[str, ...]:
    """Comma separated and/or repeated option values, validated against ``allowed`` (AssistUsageError)."""
    parsed = tuple(dict.fromkeys(item.strip() for value in values for item in value.split(",") if item.strip()))
    unknown = [value for value in parsed if value not in allowed]
    if unknown:
        raise AssistUsageError(f"{option}: unknown value(s) {', '.join(unknown)}; expected {', '.join(allowed)}")
    return parsed


def parse_query(
    *,
    status: Sequence[str] = (),
    priority: Sequence[str] = (),
    area: Sequence[str] = (),
    tier: Sequence[str] = (),
    feature: str | None = None,
) -> CoverageQuery:
    """The CoverageQuery of the command options (``--status`` default gap,partial; ``all`` lists every status)."""
    statuses = parse_values(status, (*STATUSES, "all"), "--status") or DEFAULT_STATUSES
    return CoverageQuery(
        statuses=STATUSES if "all" in statuses else statuses,
        priorities=parse_values(priority, PRIORITIES, "--priority"),
        areas=tuple(dict.fromkeys(item.strip() for value in area for item in value.split(",") if item.strip())),
        tiers=parse_values(tier, TIERS, "--tier"),
        feature=feature.strip() if feature else None,
    )


def load_project(root: Path) -> MatrixProject:
    """The coverage matrix of the checkout (AssistError when it cannot be read)."""
    project = MatrixProject(root)
    try:
        project.data  # noqa: B018 - read now: a broken matrix is an error of the command
    except MatrixError as exc:
        raise AssistError(str(exc)) from None
    return project


def feature_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    """The listed fields of a feature (gap outline needs split into available and missing)."""
    outline = entry.get("gap_outline") if isinstance(entry.get("gap_outline"), Mapping) else None
    available, missing = outline_needs(outline)
    return {
        "id": entry.get("id"),
        "title": entry.get("title"),
        "area": entry.get("area"),
        "status": entry.get("status"),
        "priority": entry.get("priority"),
        "tier": entry.get("tier"),
        "min_plan": entry.get("min_plan"),
        "ui_only": bool(entry.get("ui_only")),
        "source": list(entry.get("source") or []),
        "covered_by": list(entry.get("covered_by") or []),
        "known_bugs": list(entry.get("known_bugs") or []),
        "notes": entry.get("notes"),
        "gap_outline": dict(outline) if outline else None,
        "needs_available": available,
        "needs_missing": missing,
    }


def sort_key(entry: Mapping[str, Any]) -> tuple[int, int, str]:
    """Priority (P0 first), then status (gap, partial, covered), then id."""
    priority = PRIORITIES.index(entry["priority"]) if entry.get("priority") in PRIORITIES else len(PRIORITIES)
    return priority, STATUS_ORDER.get(str(entry.get("status")), len(STATUS_ORDER)), str(entry.get("id"))


def build_coverage(root: Path, query: CoverageQuery) -> dict[str, Any]:
    """The coverage listing of ``query`` (AssistUsageError for an unknown area or feature)."""
    project = load_project(root)
    data = project.data
    entries = [entry for entry in data.get("features") or [] if isinstance(entry, Mapping) and entry.get("id")]
    areas = [str(area.get("id")) for area in data.get("areas") or [] if isinstance(area, Mapping)]
    unknown_areas = [area for area in query.areas if area not in areas]
    if unknown_areas:
        raise AssistUsageError(f"--area: unknown area(s) {', '.join(unknown_areas)}; expected {', '.join(areas)}")
    totals = {status: sum(1 for entry in entries if entry.get("status") == status) for status in STATUSES}
    result: dict[str, Any] = {
        "kind": "coverage",
        "matrix": "scenarios/coverage.yaml",
        "otterdog_ref": (data.get("otterdog") or {}).get("ref") if isinstance(data.get("otterdog"), Mapping) else None,
        "totals": {"features": len(entries), **totals},
        "filters": {
            "status": list(query.statuses),
            "priority": list(query.priorities),
            "area": list(query.areas),
            "tier": list(query.tiers),
            "feature": query.feature,
        },
        "commands": commands(None),
    }
    if query.feature is not None:
        by_id = {entry["id"]: entry for entry in entries}
        if query.feature not in by_id:
            close = difflib.get_close_matches(query.feature, list(by_id), n=3)
            hint = f" (did you mean {', '.join(close)}?)" if close else ""
            raise AssistUsageError(f"--feature: unknown feature {query.feature!r}{hint}")
        feature = feature_entry(by_id[query.feature])
        feature["imitate"] = imitate(root, by_id[query.feature], entries)
        result["features"] = [feature]
        result["commands"] = commands(feature)
        return result
    selected = [
        entry
        for entry in entries
        if (not query.statuses or entry.get("status") in query.statuses)
        and (not query.priorities or entry.get("priority") in query.priorities)
        and (not query.areas or entry.get("area") in query.areas)
        and (not query.tiers or entry.get("tier") in query.tiers)
    ]
    result["features"] = [feature_entry(entry) for entry in sorted(selected, key=sort_key)]
    return result


def imitate(root: Path, entry: Mapping[str, Any], entries: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What to imitate for one feature: covering items of the same area (same tier first), scenarios tagged like the
    area, and whether the outline's file and scenario id exist already."""
    index = ProjectIndex(root)
    area, tier = entry.get("area"), entry.get("tier")
    items: dict[str, dict[str, Any]] = {}
    for other in entries:
        if other.get("area") != area or other.get("id") == entry.get("id") or other.get("status") == "gap":
            continue
        for item in other.get("covered_by") or []:
            found = items.setdefault(
                item, {"item": item, "tier": other.get("tier"), "files": index.files_of(item), "features": []}
            )
            found["features"].append(other["id"])
    same_area = sorted(items.values(), key=lambda found: (found["tier"] != tier, found["item"]))[:MAX_IMITATE]
    tags = AREA_TAGS.get(str(area), ())
    tagged = [
        {"id": ref.id, "kind": ref.kind, "tier": ref.tier, "file": index.relative(ref.path), "test": ref.test}
        for ref in index.tagged(tags)
    ]
    tagged.sort(key=lambda ref: (ref["tier"] != tier, ref["id"], ref["file"]))
    raw_outline = entry.get("gap_outline")
    outline: Mapping[str, Any] = raw_outline if isinstance(raw_outline, Mapping) else {}
    file = outline.get("file") if isinstance(outline.get("file"), str) else None
    scenario = outline.get("scenario") if isinstance(outline.get("scenario"), str) else None
    return {
        "same_area": same_area,
        "tags": list(tags),
        "tagged": _unique(tagged)[:MAX_IMITATE],
        "outline_file": {"path": file, "exists": (root / file).is_file()} if file else None,
        "outline_scenario": {"id": scenario, "exists": bool(index.refs(scenario))} if scenario else None,
    }


def _unique(items: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Items with distinct (id, file) pairs, first kept."""
    seen: set[tuple[Any, Any]] = set()
    found = []
    for item in items:
        if (item["id"], item["file"]) not in seen:
            seen.add((item["id"], item["file"]))
            found.append(item)
    return found


def commands(feature: Mapping[str, Any] | None) -> list[str]:
    """Commands that validate a change of the matrix and regenerate its documentation (plus the run of the new test
    for one feature: offline here, live tiers by the user)."""
    found = [
        "otterdog-e2e assist check scenarios/coverage.yaml <new or changed files>",
        REGENERATE,
        ".venv/bin/python -m pytest -q tests/unit/test_coverage_matrix.py",
    ]
    if feature is None:
        return found
    outline = feature.get("gap_outline") or {}
    scenario = outline.get("scenario") or "<scenario id>"
    if feature.get("tier") == "offline":
        found.append(f"otterdog-e2e run --suite offline --sut release:latest --scenario {scenario}")
    else:
        found.append(
            f"otterdog-e2e run --suite {feature.get('tier')} --target <instance> --scenario {scenario}"
            "   # live tier: the user runs it (target, tokens, org lease)"
        )
    return found


def render_markdown(listing: Mapping[str, Any]) -> str:
    """coverage.md: totals, filters, a table of the features, then the details and gap outlines of each."""
    totals, filters, features = listing["totals"], listing["filters"], listing["features"]
    described = ", ".join(f"{key} {','.join(value)}" for key, value in filters.items() if value and key != "feature")
    lines = [
        "# Coverage features to work on",
        "",
        (
            f"`{listing['matrix']}` (otterdog `{str(listing.get('otterdog_ref') or '-')[:12]}`): {totals['features']} "
            f"features, {totals['covered']} covered, {totals['partial']} partial, {totals['gap']} gaps."
        ),
        "",
        (
            f"Feature `{filters['feature']}`."
            if filters.get("feature")
            else f"Filters: {described or 'none'}; {len(features)} feature(s), sorted by priority, then status."
        ),
        "",
    ]
    if features:
        lines += ["| Feature | Status | Priority | Tier | Plan | Title |", "|---|---|---|---|---|---|"]
        lines += [
            f"| `{item['id']}` | {item['status']} | {item['priority']} | {item['tier']} | {item['min_plan']} | "
            f"{md_cell(item['title'])}{' (UI only)' if item['ui_only'] else ''} |"
            for item in features
        ]
        lines.append("")
    for item in features:
        lines += _details(item)
    lines += ["## Validate and regenerate", "", "```bash", *listing["commands"], "```", ""]
    return "\n".join(lines).rstrip("\n") + "\n"


def _details(item: Mapping[str, Any]) -> list[str]:
    """The detail section of one feature."""
    lines = [
        f"## `{item['id']}` ({item['status']}, {item['priority']}, `{item['tier']}`)",
        "",
        md_line(item["title"]),
        "",
    ]
    lines.append(f"- Source: {', '.join(f'`{source}`' for source in item['source']) or '-'}")
    lines.append(f"- Covered by: {', '.join(f'`{entry}`' for entry in item['covered_by']) or '-'}")
    if item["known_bugs"]:
        lines.append(f"- Known bugs: {', '.join(item['known_bugs'])}")
    if item.get("notes"):
        lines.append(f"- Notes: {md_line(item['notes'])}")
    outline = item.get("gap_outline")
    if outline:
        target = f"`{outline.get('scenario')}`" + (f" in `{outline['file']}`" if outline.get("file") else "")
        lines.append(f"- Suggested: {target}")
        lines += [f"    - step: {md_line(step)}" for step in outline.get("steps") or []]
        lines += [f"    - assert: {md_line(assertion)}" for assertion in outline.get("assertions") or []]
        lines += [f"    - available: {md_line(need)}" for need in item["needs_available"]]
        lines += [f"    - missing: {md_line(need)}" for need in item["needs_missing"]]
    imitate_data = item.get("imitate")
    if imitate_data:
        lines += ["", "To imitate:", ""]
        for found in imitate_data["same_area"]:
            files = ", ".join(f"`{name}`" for name in found["files"]) or "-"
            lines.append(f"- `{found['item']}` ({found['tier']}; covers {', '.join(found['features'])}): {files}")
        for found in imitate_data["tagged"]:
            test = f" `{found['test']}`" if found.get("test") else ""
            lines.append(
                f"- tagged {', '.join(imitate_data['tags'])}: `{found['id']}` ({found['tier']}) in `{found['file']}`{test}"
            )
        for key, label in (("outline_file", "Outline file"), ("outline_scenario", "Outline scenario id")):
            value = imitate_data.get(key)
            if value:
                name = value.get("path") or value.get("id")
                lines.append(f"- {label} `{name}`: {'exists (extend it)' if value['exists'] else 'new'}")
    return [*lines, ""]


def write_coverage(listing: Mapping[str, Any], parent: Path) -> tuple[Path, dict[str, Any]]:
    """Write the bundle ``coverage`` below ``parent``; returns (its path, the summary printed by the command)."""
    path = write_bundle(
        parent,
        BUNDLE_NAME,
        {COVERAGE_JSON: json_text(listing), COVERAGE_MD: render_markdown(listing)},
        marker=COVERAGE_JSON,
    )
    summary = {
        "bundle": str(path),
        "files": sorted([COVERAGE_JSON, COVERAGE_MD]),
        "filters": listing["filters"],
        "features": [
            {key: item[key] for key in ("id", "status", "priority", "tier", "min_plan", "ui_only")}
            for item in listing["features"]
        ],
        "totals": listing["totals"],
    }
    return path, summary
