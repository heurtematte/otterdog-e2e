"""Token requirements and prefilled creation URLs (onboard.tokens): exact parameters per role, GitHub's limits, and the
tables of docs/setup-free-org.md kept equal to the code (the single source of truth)."""

from __future__ import annotations

import re
import urllib.parse
from pathlib import Path

import pytest
import yaml

from otterdog_e2e import cli, safety
from otterdog_e2e.onboard import tokens
from otterdog_e2e.onboard.tokens import (
    ACCESS_LABELS,
    ADMIN_PERMISSIONS,
    MEMBER_PERMISSIONS,
    ORACLE_PERMISSIONS,
    ORG_PERMISSION_LABELS,
    REPO_PERMISSION_LABELS,
    ROLE_TOKENS,
    classic_token_url,
    fine_grained_token_url,
    missing_scopes,
    token_name,
    token_steps,
    token_url,
)

ROOT = Path(__file__).resolve().parents[2]
SETUP_GUIDE = ROOT / "docs" / "setup-free-org.md"


def query(url: str) -> dict[str, str]:
    """Single-valued query parameters of a URL (every parameter appears once)."""
    parsed = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query, keep_blank_values=True)
    assert all(len(values) == 1 for values in parsed.values()), parsed
    return {key: values[0] for key, values in parsed.items()}


# --- classic --------------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("role", "scopes"),
    [
        ("admin", "repo,workflow,admin:org,admin:org_hook,delete_repo"),
        ("oracle", "repo,admin:org,admin:org_hook"),
        ("author", "public_repo,read:org"),
        ("approver", "public_repo,read:org"),
        ("outsider", "public_repo,read:org"),
    ],
)
def test_classic_urls_carry_exactly_the_role_scopes(role: str, scopes: str) -> None:
    """https://github.com/settings/tokens/new?scopes=...&description=... (no expiration parameter exists)."""
    url = token_url(role, "classic", instance="free2", org="my-org")
    assert url.startswith("https://github.com/settings/tokens/new?")
    params = query(url)
    assert params == {"scopes": scopes, "description": tokens.token_description("free2", role, "my-org")}
    assert f"scopes={scopes}&" in url  # commas kept readable
    assert role in params["description"] and "my-org" in params["description"] and "free2" in params["description"]


def test_the_config_reader_has_no_classic_url() -> None:
    """The webapp's read-only token must be fine-grained."""
    with pytest.raises(ValueError, match="no classic PAT"):
        classic_token_url("config_reader", description="x")


# --- fine-grained ---------------------------------------------------------------------------------------------------
def test_fine_grained_admin_url_parameters() -> None:
    """name, description, target_name = the org, expires_in, then every admin permission and nothing else."""
    params = query(token_url("admin", "fine-grained", instance="free2", org="my-org", expires_in=30))
    assert params.pop("name") == "otterdog-e2e-free2-admin"
    assert params.pop("description") == tokens.token_description("free2", "admin", "my-org")
    assert params.pop("target_name") == "my-org"
    assert params.pop("expires_in") == "30"
    assert params == dict(ADMIN_PERMISSIONS)
    assert params["workflows"] == "write" and params["organization_custom_properties"] == "admin"


@pytest.mark.parametrize(
    ("role", "expected"),
    [("oracle", ORACLE_PERMISSIONS), ("author", MEMBER_PERMISSIONS), ("approver", MEMBER_PERMISSIONS)],
)
def test_fine_grained_role_permissions(role: str, expected: dict[str, str]) -> None:
    """Each role's URL carries exactly its permission set, the org as resource owner, the default 90 days."""
    params = query(token_url(role, "fine-grained", instance="free2", org="my-org"))
    assert (params.pop("target_name"), params.pop("expires_in")) == ("my-org", "90")
    params.pop("name"), params.pop("description")
    assert params == dict(expected)


def test_the_oracle_is_read_only_but_for_the_reads_listed_under_write() -> None:
    """Every admin permission at read, workflows left out (write only), two reads GitHub lists under write."""
    assert "workflows" not in ORACLE_PERMISSIONS
    assert {name for name, access in ORACLE_PERMISSIONS.items() if access != "read"} == {
        "organization_administration",
        "repository_advisories",
    }
    assert set(ORACLE_PERMISSIONS) == set(ADMIN_PERMISSIONS) - {"workflows"}


def test_the_config_reader_url_has_its_own_account_as_owner_and_no_permission() -> None:
    """Resource owner = its own login when known (else GitHub's default, the signed-in account), no permission."""
    params = query(token_url("config_reader", "fine-grained", instance="free2", org="my-org", login="reader-bot"))
    assert params["target_name"] == "reader-bot"
    assert set(params) == {"name", "description", "target_name", "expires_in"}
    unknown = query(token_url("config_reader", "fine-grained", instance="free2", org="my-org"))
    assert "target_name" not in unknown


def test_the_outsider_has_no_fine_grained_url() -> None:
    """A fine-grained token cannot write to an org its account does not belong to."""
    with pytest.raises(ValueError, match="no fine-grained PAT"):
        token_url("outsider", "fine-grained", instance="free2", org="my-org")
    assert ROLE_TOKENS["outsider"].kinds == ("classic",) and ROLE_TOKENS["config_reader"].kinds == ("fine-grained",)


@pytest.mark.parametrize("days", [1, 90, 366])
def test_expires_in_bounds_accepted(days: int) -> None:
    """1..366 days."""
    assert query(fine_grained_token_url("author", name="n", description="d", target_name="o", expires_in=days))[
        "expires_in"
    ] == str(days)


@pytest.mark.parametrize("days", [0, -1, 367, True])
def test_expires_in_out_of_bounds_refused(days: int) -> None:
    """Outside 1..366 (and booleans) is a ValueError."""
    with pytest.raises(ValueError, match="expires_in"):
        fine_grained_token_url("author", name="n", description="d", target_name="o", expires_in=days)


def test_name_and_description_limits() -> None:
    """name 1..40 characters, description at most 1024."""
    with pytest.raises(ValueError, match="names have 1 to 40"):
        fine_grained_token_url("author", name="x" * 41, description="d", target_name="o")
    with pytest.raises(ValueError, match="names have 1 to 40"):
        fine_grained_token_url("author", name="", description="d", target_name="o")
    with pytest.raises(ValueError, match="at most 1024"):
        fine_grained_token_url("author", name="n", description="d" * 1025, target_name="o")
    assert len(tokens.token_description("x" * 39, "config_reader", "o" * 39)) <= 1024


def test_token_names_are_capped_and_stay_unique() -> None:
    """Long instance names are cut to 40 characters with a hash: distinct per instance and role, deterministic."""
    names = {token_name(f"{'x' * 30}{suffix}", role) for suffix in ("a", "b") for role in ("admin", "config_reader")}
    assert len(names) == 4 and all(len(name) <= 40 for name in names)
    assert token_name("x" * 39, "approver") == token_name("x" * 39, "approver")
    assert token_name("free", "admin") == "otterdog-e2e-free-admin"
    longest = token_url("config_reader", "fine-grained", instance="x" * 39, org="o")
    assert len(query(longest)["name"]) <= 40


def test_missing_scopes_honours_implied_scopes() -> None:
    """repo covers public_repo, admin:org covers read:org; anything else must be granted."""
    assert missing_scopes("author", {"repo", "admin:org"}) == []
    assert missing_scopes("author", {"public_repo"}) == ["read:org"]
    assert missing_scopes("admin", {"repo", "workflow", "admin:org", "admin:org_hook"}) == ["delete_repo"]
    assert missing_scopes("config_reader", set()) == []


def test_token_steps_name_what_urls_cannot_preselect() -> None:
    """Repository access and the classic expiration are selected by hand; members need membership and approval."""
    assert any("All repositories" in step for step in token_steps("admin", "fine-grained", "my-org"))
    assert any("Public repositories" in step for step in token_steps("config_reader", "fine-grained", "my-org"))
    assert any("Expiration" in step for step in token_steps("outsider", "classic", "my-org"))
    member = " ".join(token_steps("author", "fine-grained", "my-org"))
    assert "active member" in member and "/organizations/my-org/settings/personal-access-token-requests" in member


# --- consistency with the rest of the harness ------------------------------------------------------------------------
def test_classic_scopes_are_allowed_by_the_isolation_rules() -> None:
    """Every scope a URL asks for passes safety's allowlist of the role; the admin's are otterdog's requirement."""
    for role, spec in ROLE_TOKENS.items():
        allowed = safety.ALLOWED_SCOPES["admin" if role in safety.OWNER_ROLES else "other"]
        assert set(spec.classic_scopes) <= allowed, role
        assert "read:org" in spec.classic_scopes or "admin:org" in spec.classic_scopes or not spec.classic_scopes
    assert set(ROLE_TOKENS["admin"].classic_scopes) == set(cli.REQUIRED_ADMIN_SCOPES)


def test_permission_names_and_levels_are_valid() -> None:
    """Every permission is a known URL parameter at read/write/admin; workflows only at write."""
    for spec in ROLE_TOKENS.values():
        for name, access in (spec.fine_grained or {}).items():
            assert name in tokens.ORG_PERMISSIONS or name in tokens.REPO_PERMISSIONS
            assert access in tokens.ACCESS_LEVELS
            assert name not in tokens.WRITE_ONLY_PERMISSIONS or access == "write"
    assert set(ORG_PERMISSION_LABELS.values()) == set(tokens.ORG_PERMISSIONS)
    assert set(REPO_PERMISSION_LABELS.values()) == set(tokens.REPO_PERMISSIONS)


def test_env_names_match_the_target_files() -> None:
    """login / token_env / token_type variables of every role are those of targets/*.yaml."""
    for path in sorted((ROOT / "targets").glob("*.yaml")):
        identities = yaml.safe_load(path.read_text())["identities"]
        for role, spec in ROLE_TOKENS.items():
            entry = identities[role]
            assert entry["token_env"] == spec.token_env, (path.name, role)
            assert f"${{{spec.login_env}" in entry["login"], (path.name, role)
            assert f"${{{spec.type_env}" in entry["token_type"], (path.name, role)


# --- docs/setup-free-org.md ------------------------------------------------------------------------------------------
def _section(text: str, heading: str) -> str:
    """Text of a markdown section, up to the next heading of the same or a higher level."""
    level = heading.split(" ", 1)[0]
    start = text.index(heading + "\n")
    rest = text[start + len(heading) + 1 :]
    following = re.search(rf"^#{{1,{len(level)}}} ", rest, re.MULTILINE)
    return rest[: following.start()] if following else rest


def _table_after(text: str, header: str) -> list[list[str]]:
    """Rows (cells) of the markdown table whose header line starts with ``header``."""
    lines = text[text.index(header) :].splitlines()
    rows = []
    for line in lines[2:]:
        if not line.startswith("|"):
            break
        rows.append([cell.strip() for cell in line.strip().strip("|").split("|")])
    return rows


def _permissions(rows: list[list[str]], labels: dict[str, str]) -> dict[str, str]:
    """{URL parameter: access} of the (permission, access, ...) rows of a docs table."""
    return {labels[row[0]]: ACCESS_LABELS[row[1]] for row in rows}


def test_the_docs_permission_tables_match_the_code() -> None:
    """docs/setup-free-org.md "Permissions per role" describes exactly the permission sets of the URLs."""
    section = _section(SETUP_GUIDE.read_text(), "### Permissions per role")
    admin_part = section[section.index("**`admin`**") :]
    admin = _permissions(_table_after(admin_part, "| Organization permission |"), dict(ORG_PERMISSION_LABELS))
    admin |= _permissions(_table_after(admin_part, "| Repository permission |"), dict(REPO_PERMISSION_LABELS))
    assert admin == dict(ADMIN_PERMISSIONS)
    members_part = section[section.index("**`author`** and **`approver`**") :]
    members = {}
    for scope, label, access in (
        (*row[0].split(" > ", 1), row[1]) for row in _table_after(members_part, "| Permission |")
    ):
        labels = ORG_PERMISSION_LABELS if scope == "Organization" else REPO_PERMISSION_LABELS
        members[labels[label]] = ACCESS_LABELS[access]
    assert members == dict(MEMBER_PERMISSIONS)
    assert ROLE_TOKENS["author"].fine_grained == ROLE_TOKENS["approver"].fine_grained == MEMBER_PERMISSIONS


def test_the_docs_oracle_sentence_matches_the_code() -> None:
    """The oracle: every admin permission at Read, except the reads the docs name at a higher access."""
    section = _section(SETUP_GUIDE.read_text(), "### Permissions per role")
    paragraph = " ".join(section[section.index("**`oracle`**") :].split("\n\n", 1)[0].split())
    assert "every permission of the admin table at **Read**" in paragraph
    exceptions = {}
    for scope, label, access in re.findall(
        r"\b(organization|repository) ([A-Z][A-Za-z ]+?) \*\*(Read and write|Admin)\*\*", paragraph
    ):
        labels = ORG_PERMISSION_LABELS if scope == "organization" else REPO_PERMISSION_LABELS
        exceptions[labels[label]] = ACCESS_LABELS[access]
    assert exceptions == {"organization_administration": "write", "repository_advisories": "write"}
    expected = {name: "read" for name in ADMIN_PERMISSIONS if name not in tokens.WRITE_ONLY_PERMISSIONS} | exceptions
    assert expected == dict(ORACLE_PERMISSIONS)


def test_the_docs_outsider_and_config_reader_rules_match_the_code() -> None:
    """outsider: classic only; config_reader: own account as owner, Public repositories, no permission."""
    section = _section(SETUP_GUIDE.read_text(), "### Permissions per role")
    outsider = " ".join(section[section.index("**`outsider`**") :].split("\n\n", 1)[0].split())
    reader = " ".join(section[section.index("**`config_reader`**") :].split("\n\n", 1)[0].split())
    assert "classic PAT" in outsider and "`public_repo`" in outsider and "`read:org`" in outsider
    assert ROLE_TOKENS["outsider"].fine_grained is None
    assert "config_reader account itself" in reader and "Public repositories" in reader and "no permission" in reader
    spec = ROLE_TOKENS["config_reader"]
    assert spec.own_owner and spec.repository_access == "Public repositories" and spec.fine_grained == {}


def test_the_docs_classic_scope_table_matches_the_code() -> None:
    """docs/setup-free-org.md "3. Tokens": the scopes of each identity row are those of the classic URLs."""
    rows = _table_after(_section(SETUP_GUIDE.read_text(), "## 3. Tokens"), "| Identity | Token | Scopes |")
    documented = {}
    for identities, kind, scopes in rows:
        for role in (name.strip() for name in identities.split(",")):
            documented[role] = (kind, tuple(re.findall(r"`([^`]+)`", scopes.split("(", 1)[0])))
    for role, spec in ROLE_TOKENS.items():
        kind, scopes = documented[role]
        if spec.classic_scopes:
            assert (kind, scopes) == ("classic", spec.classic_scopes), role
        else:
            assert kind == "fine-grained", role
