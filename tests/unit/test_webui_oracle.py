"""Independent oracles of the web settings (webui.oracle): show/show-live parsing on REAL otterdog output, the
trusted reader (show-live / plan without -n) on a fake web CLI, REST polling."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e.otterdog.output import parse_plan
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.testing.fakes import FakeCli, FakeOracle, cli_result
from otterdog_e2e.webui import mapping
from otterdog_e2e.webui.oracle import (
    TrustedWebReader,
    parse_settings_block,
    parse_value,
    rest_web_values,
    retrieve_failures,
    settings_changes,
    wait_rest_values,
    web_values,
)

DATA = Path(__file__).parent / "data" / "webui"
TOGGLED = {
    "members_can_change_repo_visibility": True,
    "members_can_delete_repositories": True,
    "members_can_delete_issues": True,
    "readers_can_create_discussions": False,
    "members_can_create_teams": True,
    "two_factor_requirement": True,
    "default_branch_name": "e2e-t3c7z8a5",
    "packages_containers_public": False,
    "packages_containers_internal": False,
    "members_can_change_project_visibility": False,
    "has_discussions": True,
    "discussion_source_repository": "e2e-test-org/otterdog-e2e-fixture-a",
}


def sample(name: str) -> str:
    """Text of a sample of tests/unit/data/webui."""
    return (DATA / f"{name}.txt").read_text(encoding="utf-8")


@dataclass
class FakeSut:
    """The ``installed.sut`` of a fake CLI."""

    trusted: bool = True
    label: str = "v1.6.1"


@dataclass
class FakeInstalled:
    """The ``installed`` of a fake CLI."""

    sut: FakeSut = field(default_factory=FakeSut)


class FakeWebCli(FakeCli):
    """FakeCli with the attributes a web-mode CLI has (web, installed) and a recording workspace."""

    def __init__(self, *, trusted: bool = True, web: bool = True) -> None:
        """A fake trusted web-mode CLI."""
        super().__init__(workspace=FakeWorkspace())
        self.web = object() if web else None
        self.installed = FakeInstalled(FakeSut(trusted=trusted))


@dataclass
class FakeWorkspace:
    """Records the org configs written."""

    texts: list[str] = field(default_factory=list)

    def write_org_config(self, text: str) -> None:
        """Record ``text``."""
        self.texts.append(text)


def test_parse_settings_block_of_real_show_output() -> None:
    """Every web setting of the REAL ``show --local`` sample, scalars parsed, nested blocks skipped."""
    settings = parse_settings_block(sample("webui-show-toggled"))
    assert settings is not None
    assert web_values(settings) == TOGGLED
    assert settings["plan"] == "free" and settings["security_managers"] == [] and settings["company"] is None
    assert "workflows" not in settings and "actions_can_approve_pull_request_reviews" not in settings
    assert "members" not in settings  # the team block after settings is not part of it


def test_parse_settings_block_of_show_live() -> None:
    """show-live (synthetic): UNSET settings are absent, the failed read is reported by retrieve_failures."""
    text = sample("webui-show-live-synthetic")
    values = web_values(parse_settings_block(text) or {})
    assert set(TOGGLED) - set(values) == {"two_factor_requirement", "packages_containers_internal"}
    assert values["default_branch_name"] == "e2e-t3c7z8a5"
    assert retrieve_failures(text) == ["packages_containers_internal"]


def test_parse_settings_block_without_block() -> None:
    """No settings block (e.g. a failed command): None."""
    assert parse_settings_block("Showing live resources:\n\n  Error: could not log in to web UI\n") is None
    assert parse_settings_block("  settings {\n  }\n") == {}


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("true", True),
        ("false", False),
        ("null", None),
        ("10", 10),
        ('"main"', "main"),
        ("[]", []),
        ('"a "b""', 'a "b"'),
    ],
)
def test_parse_value(text: str, value: Any) -> None:
    """JSON literals; a quoted string that is not JSON keeps its inner text."""
    assert parse_value(text) == value


def test_settings_changes_of_real_local_plans() -> None:
    """The web keys of the REAL local-plan samples: toggling plans 11 (the discussion source included), the restore
    10 (otterdog ignores the source while discussions are off); the repository change is not a settings change."""
    toggled = settings_changes(parse_plan(sample("webui-local-plan-toggled")))
    assert sorted(toggled) == sorted(mapping.WRITABLE)
    restore = settings_changes(parse_plan(sample("webui-local-plan-restore")))
    assert sorted(restore) == sorted(set(mapping.WRITABLE) - {"discussion_source_repository"})


def test_settings_changes_skip_read_only_notes() -> None:
    """A read-only key noted by otterdog is not a change."""
    text = (
        "  ~ settings {\n"
        '    ~ plan                     = "enterprise" -> "free"\n'
        "    ~ members_can_create_teams = false -> true\n"
        "  ~ }\n"
        "  Note: setting 'plan' is read-only, will be skipped.\n"
        "  Plan: 0 to add, 1 to change, 0 to delete.\n"
    )
    assert settings_changes(parse_plan(text)) == ["members_can_create_teams"]


def test_rest_web_values_through_the_oracle() -> None:
    """The REST-readable web settings of GET /orgs/{org}."""
    oracle = FakeOracle()
    oracle.set("org", value={"login": "o", "members_can_create_teams": False, "two_factor_requirement_enabled": True})
    assert rest_web_values(oracle) == {"members_can_create_teams": False, "two_factor_requirement": True}  # type: ignore[arg-type]


def test_wait_rest_values_polls_until_the_values_match() -> None:
    """GitHub may serve a stale org briefly: polled until the REST-readable keys match (others ignored)."""
    answers = [
        {"members_can_create_teams": False},
        {"members_can_create_teams": False},
        {"members_can_create_teams": True},
    ]
    clock = {"now": 0.0}

    def sleep(seconds: float) -> None:
        """Advance the fake clock."""
        clock["now"] += seconds

    values, diffs = wait_rest_values(
        lambda: answers.pop(0),
        {"members_can_create_teams": True, "has_discussions": True},
        timeout=60,
        interval=5,
        sleep=sleep,
        clock=lambda: clock["now"],
    )
    assert values == {"members_can_create_teams": True} and diffs == [] and clock["now"] == 10


def test_wait_rest_values_reports_remaining_differences() -> None:
    """At the deadline the remaining differences are returned (no exception)."""
    clock = {"now": 0.0}
    _values, diffs = wait_rest_values(
        lambda: {"default_branch_name": "main"},
        {"default_branch_name": "e2e-t3c7z8a5"},
        timeout=10,
        interval=5,
        sleep=lambda s: clock.__setitem__("now", clock["now"] + s),
        clock=lambda: clock["now"],
    )
    assert diffs == ['default_branch_name: expected "e2e-t3c7z8a5", got "main"']
    assert wait_rest_values(lambda: {"x": 1}, {"has_discussions": True}) == ({"x": 1}, [])


def test_trusted_reader_requires_a_trusted_web_cli() -> None:
    """Refused without web mode or for an untrusted SUT (the SUT under test never reads its own result)."""
    with pytest.raises(SafetyError, match="web-mode"):
        TrustedWebReader(FakeWebCli(web=False))
    with pytest.raises(SafetyError, match="trusted"):
        TrustedWebReader(FakeWebCli(trusted=False))


def test_trusted_reader_reads_show_live() -> None:
    """read(): one ``show-live``, the web values, the keys it could not read and its failures."""
    cli = FakeWebCli()
    cli.queue("show-live", stdout=sample("webui-show-live-synthetic"))
    read = TrustedWebReader(cli).read()
    assert read.ok and read.problem() is None
    assert read.values["has_discussions"] is True and "packages_containers_internal" not in read.values
    assert read.missing == ["two_factor_requirement", "packages_containers_internal"]
    assert read.failed == ["packages_containers_internal"]
    assert [call.command for call in cli.calls] == ["show-live"]


def test_trusted_reader_reports_login_failures() -> None:
    """A failed login: no settings block, the classified failure in the problem text."""
    cli = FakeWebCli()
    cli.queue("show-live", stdout="Showing live resources:\n", stderr="RuntimeError: incorrect 2FA TOTP\n", exit_code=2)
    read = TrustedWebReader(cli).read()
    assert not read.ok and read.failure is not None and read.failure.kind == "totp"
    problem = read.problem() or ""
    assert "exit code 2" in problem and "totp" in problem and "no settings block" in problem


def test_trusted_plan_problems() -> None:
    """plan_problems(): writes the config, plans without -n, reports the web keys still changed."""
    cli = FakeWebCli()
    cli.queue("plan", stdout=sample("webui-local-plan-restore"))
    problems = TrustedWebReader(cli).plan_problems("CONFIG", keys=["has_discussions", "two_factor_requirement"])
    assert problems == ["has_discussions: the trusted plan still changes it"]
    assert cli.workspace.texts == ["CONFIG"]
    cli.queue("plan", stdout="Plan: 0 to add, 0 to change, 0 to delete.\n")
    assert TrustedWebReader(cli).plan_problems("CONFIG") == []
    cli.queue("plan", cli_result("plan", "planning aborted: could not log in to web UI: x\n", exit_code=1))
    assert TrustedWebReader(cli).plan_problems("CONFIG")[0].startswith("trusted plan failed (exit code 1")


# otterdog's import output (operations/import_configuration.py printer lines, web.py WARNING logger line): synthetic
IMPORT_OUTPUT = (
    "Importing resources:\n\n"
    "Project e2e-test-org[github_id=e2e-test-org] (1/1)\n"
    "WARNING  failed to retrieve setting 'members_can_change_project_visibility' via web ui:          web.py:177\n"
    "         Timeout 10000ms exceeded.\n"
    "  Organization definition written to './orgs/e2e-test-org/e2e-test-org.jsonnet'.\n"
)


def test_trusted_reader_via_import() -> None:
    """mode import: ``import -f`` then ``show --local`` (REAL output of an import-shaped config); the failed key and
    the never-read two_factor_requirement (template defaults in the import) are dropped."""
    cli = FakeWebCli()
    cli.queue("import", stdout=IMPORT_OUTPUT)
    cli.queue("show", stdout=sample("webui-show-imported"))
    reader = TrustedWebReader(cli, mode="import")
    read = reader.read()
    assert [call.command for call in cli.calls] == ["import", "show"]
    assert read.ok and read.failed == ["members_can_change_project_visibility"]
    assert read.values["default_branch_name"] == "trunk" and read.values["members_can_create_teams"] is True
    assert read.values["packages_containers_internal"] is False
    assert "two_factor_requirement" not in read.values and "members_can_change_project_visibility" not in read.values
    assert set(read.missing) == {"two_factor_requirement", "members_can_change_project_visibility"}
    assert any("two_factor_requirement: dropped" in note for note in read.notes)


def test_trusted_reader_via_import_failure() -> None:
    """A failed import (login): no show, the failure classified."""
    cli = FakeWebCli()
    cli.queue(
        "import", stdout="Importing resources:\n", stderr="RuntimeError: incorrect username or password\n", exit_code=2
    )
    read = TrustedWebReader(cli, mode="import").read()
    assert not read.ok and read.failure is not None and read.failure.kind == "credentials"
    assert [call.command for call in cli.calls] == ["import"]
    with pytest.raises(ValueError, match="reader mode"):
        TrustedWebReader(cli, mode="plan")
