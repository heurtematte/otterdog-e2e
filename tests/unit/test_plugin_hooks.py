"""pytest plugin hooks (SPEC 15) exercised with pytester: gating before fixtures, known bugs, selection, tier marks,
reporting (results.jsonl, summary.md, redaction), --showlocals refusal, SIGTERM, strict differential."""

from __future__ import annotations

import contextlib
import json
import secrets
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from otterdog_e2e.capabilities import from_plan
from otterdog_e2e.context import E2EContext
from otterdog_e2e.known_bugs import KnownBug
from otterdog_e2e.redact import REDACTOR
from otterdog_e2e.scenarios import collect  # imported before any inner session (see kept())
from otterdog_e2e.testing.fakes import (
    FAKE_RUN_ID,
    FakeGitHubHttp,
    FakeLease,
    make_identities,
    make_settings,
    make_target,
    make_verified_org,
)
from otterdog_e2e.webapp import stack as _webapp_stack  # noqa: F401 - like collect: the plugin imports it lazily
from otterdog_e2e.webhooks import relay as _relay  # noqa: F401 - like collect: the plugin imports it lazily

pytest_plugins = ["pytester"]

CLEARED_ENV = (
    "E2E_TARGET",
    "E2E_SUT",
    "E2E_BASE_SUT",
    "E2E_RESET_SUT",
    "E2E_TAGS",
    "E2E_SCENARIO",
    "E2E_ARTIFACTS",
    "E2E_RUN_ID",
    "E2E_CHANGE",
    "E2E_WEBAPP_IMAGE",
    "E2E_MIN_RATE_REMAINING",
    "GITHUB_STEP_SUMMARY",
    "GITHUB_ACTIONS",
    "CI",
)


PREPARATION_STEPS = ("installed", "image_for", "web_browsers")  # what pytest_runtestloop prepares before the items


def no_preparation(context: E2EContext, role: str) -> Any:
    """Inner sessions never install a SUT, build its image or install its browsers: the real steps would clone otterdog
    from github.com (unit tests need no network) and take seconds before failing."""
    raise RuntimeError(f"unit tests do not prepare the {role} SUT")


class Inner:
    """An isolated inner pytest session factory."""

    def __init__(self, pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> None:
        """Tmp harness settings, fake summary/scrub, no e2e environment."""
        self.pytester = pytester
        self.monkeypatch = monkeypatch
        self.settings = make_settings(pytester.path / "harness")
        self.summaries: list[Path] = []
        self.leaks: list[Path] = []
        monkeypatch.setattr("otterdog_e2e.settings.harness_settings", lambda environ=None: self.settings)
        monkeypatch.setattr("otterdog_e2e.redact.install_logging_filter", lambda *a: None)
        monkeypatch.setattr("otterdog_e2e.report.build_summary", self._summary)
        monkeypatch.setattr("otterdog_e2e.report.scrub_artifacts", lambda root, redactor=None: list(self.leaks))
        for name in PREPARATION_STEPS:  # a test that needs one patches it again
            monkeypatch.setattr(E2EContext, name, no_preparation)
        for name in CLEARED_ENV:
            monkeypatch.delenv(name, raising=False)

    def _summary(self, directory: Path, **kwargs: Any) -> str:
        """Fake build_summary recording its directory."""
        self.summaries.append(directory)
        return f"# summary of {directory.name}\n"

    @property
    def artifacts(self) -> Path:
        """Artifacts dir of the inner run."""
        return self.settings.artifacts_root / FAKE_RUN_ID

    def results(self) -> list[dict[str, Any]]:
        """results.jsonl lines of the inner run."""
        path = self.artifacts / "results.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def run(self, *args: str, **kwargs: Any) -> pytest.RunResult:
        """runpytest with the fixed run id."""
        return self.pytester.runpytest("-p", "no:cacheprovider", f"--e2e-run-id={FAKE_RUN_ID}", *args, **kwargs)

    def live(
        self,
        *,
        plan: str = "free",
        identities: tuple[str, ...] = ("admin",),
        error: str | None = None,
        app_ok: bool = False,
        docker_ok: bool = True,
        rate: int | None = None,
        app_unsafe: bool = False,
    ) -> list[str]:
        """Replace E2EContext.ensure_live by a fake live session; returns the list of calls."""
        calls: list[str] = []

        def ensure_live(context: E2EContext) -> None:
            """Fake live session."""
            calls.append("ensure_live")
            if context._live_attempted:
                return
            context._live_attempted = True
            if error is not None:
                context.live_error = error
                return
            context.target = make_target()
            context.identities = make_identities(*identities)
            context.verified = make_verified_org(plan=plan)
            context.capabilities = from_plan(plan)
            context.lease = FakeLease()
            context.lease.acquire()
            context.docker_ok, context.app_ok = docker_ok, app_ok
            context.extras["app_reason"] = "the GitHub App is not installed on the org"
            if app_unsafe:
                context.extras["app_unsafe"] = True
                context.extras["app_reason"] = "unsafe GitHub App: SafetyError: the GitHub App 'x' is owned by 'dev'"
            if rate is not None:
                http = FakeGitHubHttp(identity="admin")
                http.rate_remaining = rate
                context._http[("admin", "read")] = http  # type: ignore[assignment]

        self.monkeypatch.setattr(E2EContext, "ensure_live", ensure_live)
        self.monkeypatch.setenv("E2E_TARGET", "fake")
        return calls


@pytest.fixture
def inner(pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch) -> Inner:
    """Inner session factory."""
    return Inner(pytester, monkeypatch)


def test_markers_and_options_are_registered(inner: Inner) -> None:
    """--markers lists the SPEC 15 markers, --help the --e2e-* options."""
    result = inner.pytester.runpytest("--markers")
    for marker in ("live", "requires(*caps)", "plan(*plans)", "identities(*names)", "known_bug(id)", "differential"):
        result.stdout.fnmatch_lines([f"@pytest.mark.{marker}:*"])
    help_text = inner.pytester.runpytest("--help").stdout.str()
    assert "--e2e-target" in help_text and "--e2e-strict-diff" in help_text and "--e2e-trust-code" in help_text


def test_plain_sessions_have_no_context(inner: Inner) -> None:
    """Sessions without e2e items create no context, scratch or artifacts."""
    inner.pytester.makepyfile(test_plain="def test_plain():\n    assert True\n")
    inner.run().assert_outcomes(passed=1)
    assert not inner.settings.artifacts_root.exists() and not inner.settings.cache_dir.exists()


def test_live_without_target_is_skipped_at_collection(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """No target: live items are skipped by collection, the live session is never attempted."""
    monkeypatch.setattr(E2EContext, "ensure_live", lambda self: pytest.fail("must not be called"))
    inner.pytester.makepyfile(
        test_live="""
        import pytest

        @pytest.mark.live
        def test_live():
            pass
        """
    )
    result = inner.run("-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*live test without a target*--e2e-target*"])
    [line] = inner.results()
    assert line["outcome"] == "skipped" and "without a target" in line["reason"]


def test_gating_skips_before_any_fixture(inner: Inner, tmp_path: Path) -> None:
    """requires/plan/identities/webapp are checked in tryfirst runtest_setup: the session fixture never runs."""
    events = tmp_path / "events.txt"
    calls = inner.live(plan="free", identities=("admin",), app_ok=False)
    inner.pytester.makepyfile(
        test_gates=f"""
        import pathlib
        import pytest

        EVENTS = pathlib.Path(r"{events}")

        @pytest.fixture(scope="session")
        def heavy():
            EVENTS.write_text("heavy session fixture ran")
            yield

        @pytest.mark.live
        @pytest.mark.requires("custom_org_roles")
        def test_roles(heavy):
            pass

        @pytest.mark.live
        @pytest.mark.plan("team", "enterprise")
        def test_paid(heavy):
            pass

        @pytest.mark.live
        @pytest.mark.identities("approver", "author")
        def test_people(heavy):
            pass

        @pytest.mark.live
        @pytest.mark.webapp
        def test_webapp(heavy):
            pass
        """
    )
    result = inner.run("-rs")
    result.assert_outcomes(skipped=4)
    assert not events.exists()
    result.stdout.fnmatch_lines(
        [
            "*missing capabilities: custom_org_roles*",
            "*needs plan team | enterprise (target plan: free)*",
            "*missing identities: approver, author*",
            "*GitHub App not ready: the GitHub App is not installed*",
        ],
        consecutive=False,
    )
    assert calls.count("ensure_live") == 5  # once before the first item (pytest_runtestloop), then per item gate


def test_an_unsafe_app_fails_webapp_items_instead_of_skipping_them(inner: Inner) -> None:
    """DESTR-01: an App refused by safety.verify_app is a configuration error: webapp items fail with the reason,
    the other live items still run."""
    inner.live(identities=("admin",), app_ok=False, app_unsafe=True)
    inner.pytester.makepyfile(
        test_unsafe="""
        import pytest

        @pytest.mark.live
        @pytest.mark.webapp
        def test_webapp():
            pass

        @pytest.mark.live
        def test_cli():
            pass
        """
    )
    result = inner.run("-rA")
    result.assert_outcomes(passed=1, errors=1)
    result.stdout.fnmatch_lines(["*unsafe GitHub App: SafetyError: the GitHub App 'x' is owned by 'dev'*"])


def test_add_mask_lines_bypass_pytest_capture(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """ISO-03: on GitHub Actions a secret registered inside a test (pytest captures fd 1) reaches the runner's real
    stdout as ``::add-mask::``; the previous sink is restored after the session."""
    import os

    from otterdog_e2e import pytest_plugin, redact

    read_fd, write_fd = os.pipe()
    monkeypatch.setattr(pytest_plugin, "_RUNNER_STDOUT_FD", write_fd)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    before = redact.mask_sink()
    inner.pytester.makepyfile(
        test_mask="""
        from otterdog_e2e.redact import REDACTOR

        def test_registers_a_secret():
            REDACTOR.add("iso03-minted-token-0123456789", variants=False)
        """
    )
    try:
        inner.run().assert_outcomes(passed=1)
        os.close(write_fd)
        with os.fdopen(read_fd, "rb") as handle:
            written = handle.read().decode()
    finally:
        for fd in (read_fd, write_fd):
            with contextlib.suppress(OSError):
                os.close(fd)
    assert "::add-mask::iso03-minted-token-0123456789\n" in written
    assert redact.mask_sink() is before


def test_satisfied_live_items_run_with_session_fixtures(inner: Inner) -> None:
    """A live item whose requirements hold runs and sees the live fixtures."""
    inner.live(plan="team", identities=("admin", "approver"))
    inner.pytester.makepyfile(
        test_ok="""
        import pytest

        @pytest.mark.live
        @pytest.mark.requires("org_rulesets")
        @pytest.mark.plan("team")
        @pytest.mark.identities("approver")
        def test_ok(e2e, target, verified_org, capabilities, identities, run_ctx, harness):
            assert verified_org.login == target.org == "e2e-test-org"
            assert capabilities.plan == "team" and "approver" in identities
            assert run_ctx.run_id == e2e.run_ctx.run_id
            assert harness is e2e.settings
        """
    )
    inner.run().assert_outcomes(passed=1)


def test_live_setup_failure_errors_items(inner: Inner) -> None:
    """A failed live session (verification, lease, ...) errors every live item with the reason."""
    inner.live(error="SafetyError: org id 1 != 424242")
    inner.pytester.makepyfile(
        test_fail="""
        import pytest

        @pytest.mark.live
        def test_one():
            pass

        @pytest.mark.live
        def test_two():
            pass
        """
    )
    result = inner.run()
    result.assert_outcomes(errors=2)
    result.stdout.fnmatch_lines(["*live session setup failed: SafetyError: org id 1 != 424242*"])
    assert {line["outcome"] for line in inner.results()} == {"error"}


def test_low_rate_budget_skips(inner: Inner) -> None:
    """Below E2E_MIN_RATE_REMAINING the live items are skipped."""
    inner.live(rate=120)
    inner.pytester.makepyfile(
        test_rate="""
        import pytest

        @pytest.mark.live
        def test_live():
            pass
        """
    )
    result = inner.run("-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*github rate budget: core remaining admin 120 < 800*"])


def test_known_bugs_become_non_strict_xfails(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """known_bug(id) and bugs listing a scenario xfail (non strict): fixed bugs show up as XPASS."""
    scenarios_dir = inner.settings.scenarios_dir
    scenarios_dir.mkdir(parents=True)
    (scenarios_dir / "known_bugs.yaml").write_text("- {id: KB-001, title: apply exits 0 on validation errors}\n")
    bug = KnownBug("KB-001", "apply exits 0 on validation errors", scenarios=["cli.plan.validation"])
    monkeypatch.setattr("otterdog_e2e.known_bugs.load", lambda path: {"KB-001": bug})
    inner.pytester.makepyfile(
        test_bugs="""
        import pytest

        @pytest.mark.known_bug("KB-001")
        def test_still_broken():
            assert False

        @pytest.mark.known_bug("KB-001")
        def test_fixed():
            pass

        @pytest.mark.scenario("cli.plan.validation")
        def test_listed_by_the_bug():
            assert False

        @pytest.mark.known_bug("KB-999")
        def test_undeclared_bug():
            assert False
        """
    )
    result = inner.run("-rxX")
    result.assert_outcomes(xfailed=3, xpassed=1)
    result.stdout.fnmatch_lines(
        ["*KB-001: apply exits 0 on validation errors*", "*KB-999: not listed*"], consecutive=False
    )
    outcomes = {line["nodeid"].split("::")[-1]: (line["outcome"], line["known_bug"]) for line in inner.results()}
    assert outcomes["test_fixed"] == ("xpassed", "KB-001")
    assert outcomes["test_listed_by_the_bug"] == ("xfailed", "KB-001")


def test_known_bug_xfails_never_hide_fixture_errors(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """BAT-03: the xfail of a known bug covers the test body only: a failing fixture setup or teardown (a cleanup
    leaving objects behind) of a known-bug item is an error, and results.jsonl records the failed teardown."""
    scenarios_dir = inner.settings.scenarios_dir
    scenarios_dir.mkdir(parents=True)
    (scenarios_dir / "known_bugs.yaml").write_text("- {id: KB-001, title: t}\n")
    bug = KnownBug("KB-001", "apply exits 0 on validation errors")
    monkeypatch.setattr("otterdog_e2e.known_bugs.load", lambda path: {"KB-001": bug})
    inner.pytester.makepyfile(
        test_fixture_errors="""
        import pytest

        @pytest.fixture
        def broken_setup():
            raise RuntimeError("could not create the run repository")

        @pytest.fixture
        def leaking_cleanup():
            yield
            raise RuntimeError("cleanup failed: e2e-run-x left behind")

        @pytest.mark.known_bug("KB-001")
        def test_setup_error(broken_setup):
            assert False

        @pytest.mark.known_bug("KB-001")
        def test_cleanup_error(leaking_cleanup):
            assert False  # the bug: XFAIL for the body, but the teardown error must show

        @pytest.mark.known_bug("KB-001")
        def test_imperative(leaking_cleanup):
            pytest.xfail("explicit")
        """
    )
    result = inner.run("-rA")
    result.assert_outcomes(errors=3, xfailed=2)
    outcomes = {line["nodeid"].split("::")[-1]: (line["outcome"], line["when"]) for line in inner.results()}
    assert outcomes == {
        "test_setup_error": ("error", "setup"),
        "test_cleanup_error": ("error", "teardown"),
        "test_imperative": ("error", "teardown"),
    }
    result.stdout.fnmatch_lines(["*cleanup failed: e2e-run-x left behind*"])


def test_python_known_bug_xfails_accept_only_assertions(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """BAT-03: the xfail of a Python known-bug test accepts only AssertionError (the asserts that report the bug). A
    harness error in the body (a GitHub error, a broken helper, pytest.fail) is a failure. The test's own
    xfail(raises=...) takes precedence."""
    scenarios_dir = inner.settings.scenarios_dir
    scenarios_dir.mkdir(parents=True)
    (scenarios_dir / "known_bugs.yaml").write_text("- {id: KB-001, title: t}\n")
    monkeypatch.setattr("otterdog_e2e.known_bugs.load", lambda path: {"KB-001": KnownBug("KB-001", "t")})
    inner.pytester.makepyfile(
        test_scoped="""
        import pytest

        class GitHubError(Exception):
            pass

        class BugSeen(Exception):
            pass

        @pytest.mark.known_bug("KB-001")
        def test_bug_reproduced():
            assert 0 == 1, "apply exited 0 on validation errors"

        @pytest.mark.known_bug("KB-001")
        def test_harness_error():
            raise GitHubError("GET /orgs/e2e/repos: HTTP 502")

        @pytest.mark.known_bug("KB-001")
        def test_explicit_failure():
            pytest.fail("the harness gave up")

        @pytest.mark.known_bug("KB-001")
        @pytest.mark.xfail(raises=BugSeen, strict=False, reason="KB-001: as the test reports it")
        def test_own_exception():
            raise BugSeen("the bug")
        """
    )
    result = inner.run("-rA")
    found = {line["nodeid"].split("::")[-1]: line["outcome"] for line in inner.results()}
    assert found == {
        "test_bug_reproduced": "xfailed",
        "test_harness_error": "failed",
        "test_explicit_failure": "failed",
        "test_own_exception": "xfailed",
    }, result.stdout.str()
    result.stdout.fnmatch_lines(["*GET /orgs/e2e/repos: HTTP 502*"])


SCENARIO_ITEMS = """
from pathlib import Path

import pytest

from otterdog_e2e.scenarios.model import Scenario, StepSpec


def make(name):
    return Scenario(id=f"cli.kb.{name}", title=name, tier="cli", steps=[StepSpec("s")], source=Path("x.yaml"),
                    known_bug="KB-001")


@pytest.mark.parametrize("scenario", [make("expected")])
def test_expected(scenario):
    pytest.xfail("KB-001: t (step 's'): expected noop, got changes")


@pytest.mark.parametrize("scenario", [make("strict")])
def test_strict_failure(scenario):
    raise AssertionError("scenario failed: cleanup: CleanupError: 1 failed patch")


@pytest.mark.parametrize("scenario", [make("fixed")])
def test_passes(scenario):
    pass
"""


def test_yaml_scenario_items_xfail_only_on_their_engines_expected_failures(
    inner: Inner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """BAT-03: the known-bug xfail of a YAML scenario item accepts only KnownBugReproduced: the engine's own
    pytest.xfail (expected failures) is XFAIL, any other failure (a strict step, a failed cleanup) FAILS, a pass is
    an XPASS."""
    inner.live(identities=("admin",))
    scenarios_dir = inner.settings.scenarios_dir
    scenarios_dir.mkdir(parents=True)
    (scenarios_dir / "known_bugs.yaml").write_text("- {id: KB-001, title: t}\n")
    monkeypatch.setattr("otterdog_e2e.known_bugs.load", lambda path: {"KB-001": KnownBug("KB-001", "t")})
    inner.pytester.makepyfile(test_scenario_items=SCENARIO_ITEMS)
    result = inner.run("-rA")
    found = {line["nodeid"].split("::")[-1]: line["outcome"] for line in inner.results()}
    assert found == {
        "test_expected[scenario0]": "xfailed",
        "test_strict_failure[scenario0]": "failed",
        "test_passes[scenario0]": "xpassed",
    }, result.stdout.str()


@pytest.mark.parametrize(
    ("sut_version", "outcomes"),
    [
        ("1.7.0.dev15+e2e.g9bdeb75", {"test_regressed": "failed", "test_still_fixed": "passed"}),
        ("1.6.1", {"test_regressed": "xfailed", "test_still_fixed": "xpassed"}),
        (None, {"test_regressed": "failed", "test_still_fixed": "passed"}),
    ],
)
def test_fixed_known_bugs_only_xfail_on_older_suts(
    inner: Inner, monkeypatch: pytest.MonkeyPatch, sut_version: str | None, outcomes: dict[str, str]
) -> None:
    """A bug with status fixed no longer hides failures (regression guard), except on SUTs predating fixed_in."""
    scenarios_dir = inner.settings.scenarios_dir
    scenarios_dir.mkdir(parents=True)
    (scenarios_dir / "known_bugs.yaml").write_text("- {id: KB-008, title: t}\n")
    bug = KnownBug("KB-008", "org ruleset crash", status="fixed", fixed_in="1.7.0.dev15")
    monkeypatch.setattr("otterdog_e2e.known_bugs.load", lambda path: {"KB-008": bug})
    monkeypatch.setattr(E2EContext, "sut_version", lambda self: sut_version)
    inner.pytester.makepyfile(
        test_fixed_bugs="""
        import pytest

        @pytest.mark.known_bug("KB-008")
        def test_regressed():
            assert False

        @pytest.mark.known_bug("KB-008")
        def test_still_fixed():
            pass
        """
    )
    result = inner.run("-rxX")
    found = {line["nodeid"].split("::")[-1]: line["outcome"] for line in inner.results()}
    assert found == outcomes, result.stdout.str()
    if sut_version == "1.6.1":
        result.stdout.fnmatch_lines(["*KB-008: org ruleset crash (fixed in 1.7.0.dev15; SUT 1.6.1 predates the fix)*"])


SELECTION = """
import pytest

@pytest.mark.scenario("cli.repo.lifecycle")
@pytest.mark.tags("smoke", "repo")
def test_repo_lifecycle():
    pass

@pytest.mark.scenario("cli.repo.secrets")
@pytest.mark.tags("secrets")
def test_repo_secrets():
    pass

@pytest.mark.scenario("cli.team.basic")
@pytest.mark.tags("smoke")
def test_team_basic():
    pass

@pytest.mark.tags("smoke")
def test_smoke_only():
    pass

def test_plain_helper():
    pass
"""
ALL_SELECTION = {"test_repo_lifecycle", "test_repo_secrets", "test_team_basic", "test_smoke_only", "test_plain_helper"}


def kept(inner: Inner, *options: str) -> set[str]:
    """Names of the items left after collection (selection applied) of an inner --collect-only run.

    inline_run restores sys.modules afterwards: a module first imported by the inner session (the plugin imports
    scenarios.collect lazily) would leave dotted monkeypatch targets of later tests stale, hence the module import.
    """
    recorder = inner.pytester.inline_run(
        "--collect-only", "-p", "no:cacheprovider", f"--e2e-run-id={FAKE_RUN_ID}", *options
    )
    return {item.name for item in recorder.getcalls("pytest_collection_finish")[0].session.items}


@pytest.mark.parametrize(
    ("options", "selected"),
    [
        ((), ALL_SELECTION),
        (("--e2e-tags=smoke",), ALL_SELECTION - {"test_repo_secrets"}),  # non-e2e helpers ignore --e2e-tags
        (("--e2e-tags=smoke,secrets",), ALL_SELECTION),  # OR inside one filter
        (("--e2e-scenario=cli.repo.*",), {"test_repo_lifecycle", "test_repo_secrets"}),  # helpers have no scenario
        (("--e2e-scenario=cli.repo.lifecycle,cli.team.*",), {"test_repo_lifecycle", "test_team_basic"}),
        (("--e2e-tags=smoke", "--e2e-scenario=cli.repo.*"), {"test_repo_lifecycle"}),  # AND between the filters
    ],
)
def test_tags_and_scenario_selection(inner: Inner, options: tuple[str, ...], selected: set[str]) -> None:
    """OR inside --e2e-tags or --e2e-scenario, AND between them; deselected items are reported as such."""
    inner.pytester.makepyfile(test_select=SELECTION)
    assert kept(inner, *options) == selected
    inner.run(*options).assert_outcomes(passed=len(selected), deselected=len(ALL_SELECTION) - len(selected))


def test_tags_spare_unit_and_offline_tiers_but_not_the_scenario_filter(inner: Inner) -> None:
    """tests/unit and tests/offline are exempt from --e2e-tags only; live and differential tiers are tag-filtered."""
    inner.pytester.mkpydir("tests")
    marked = (
        "import pytest\n\n@pytest.mark.scenario({scenario!r})\n@pytest.mark.tags({tag!r})\ndef {name}():\n    pass\n"
    )
    files = {
        "unit/test_u.py": "def test_unit():\n    pass\n",
        "offline/test_o.py": marked.format(scenario="O-VAL-OK", tag="validate", name="test_offline"),
        "cli/test_c.py": marked.format(scenario="cli.repo.basic", tag="smoke", name="test_cli_smoke"),
        "webapp/test_w.py": marked.format(scenario="W-BOOT", tag="webapp", name="test_webapp"),
        "differential/test_d.py": marked.format(scenario="O-VAL-OK", tag="validate", name="test_differential"),
    }
    for relative, text in files.items():
        path = inner.pytester.path / "tests" / relative
        path.parent.mkdir(exist_ok=True)
        path.write_text(text)
    assert sorted(collect.TAGS_EXEMPT_TIERS) == ["offline", "unit"]
    assert kept(inner, "--e2e-tags=smoke") == {"test_unit", "test_offline", "test_cli_smoke"}
    assert kept(inner, "--e2e-tags=validate") == {"test_unit", "test_offline", "test_differential"}
    assert kept(inner, "--e2e-scenario=O-*") == {"test_offline", "test_differential"}  # unit tests have no scenario
    assert kept(inner, "--e2e-scenario=O-*,W-*", "--e2e-tags=webapp") == {"test_offline", "test_webapp"}


REFERENCING_TEST = """
import pytest

@pytest.mark.scenario("cli.repo.secrets", references=[{"pr": 790, "note": "the change under test"}])
def test_referencing():
    pass
"""


def test_scenarios_referencing_the_change_pass_the_tags_filter(inner: Inner) -> None:
    """The scenarios referencing the change under test (--e2e-change, default: N of a pr:N@<sha> SUT) are extra
    scenarios of --e2e-tags (still ANDed with --e2e-scenario); invalid references are usage errors."""
    inner.pytester.makepyfile(test_select=SELECTION)
    referencing = inner.settings.project_root / "tests" / "cli" / "test_referencing.py"
    referencing.parent.mkdir(parents=True)
    referencing.write_text(REFERENCING_TEST)
    # the referencing module (a cli tier test of the project, scenario cli.repo.secrets) is collected too
    assert kept(inner, "--e2e-tags=smoke", "--e2e-change=790") == {*ALL_SELECTION, "test_referencing"}
    expected = {"test_repo_secrets", "test_plain_helper", "test_referencing"}
    assert kept(inner, "--e2e-tags=webapp", "--e2e-change=#790") == expected
    assert kept(inner, "--e2e-tags=webapp", f"--e2e-sut=pr:790@{'a' * 40}") == expected  # implied by the pr: SUT
    assert kept(inner, "--e2e-tags=webapp", f"--e2e-sut=pr:791@{'a' * 40}") == {"test_plain_helper"}
    assert kept(inner, "--e2e-tags=webapp", "--e2e-change=791") == {"test_plain_helper"}
    narrowed = kept(inner, "--e2e-tags=webapp", "--e2e-scenario=cli.team.*", "--e2e-change=790")
    assert narrowed == set()
    result = inner.run("--e2e-tags=smoke", "--e2e-change=not a change")
    assert result.ret == pytest.ExitCode.USAGE_ERROR and "--e2e-change" in result.stderr.str()
    referencing.write_text(REFERENCING_TEST.replace('"pr": 790', '"pr": 790, "base": "pr:1@x"'))
    result = inner.run("--e2e-tags=smoke", "--e2e-change=790")
    assert result.ret == pytest.ExitCode.USAGE_ERROR and "--e2e-change" in result.stderr.str()


def test_scenario_parameters_get_scenario_marks(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """Items parametrized with a Scenario get collect.apply_scenario_marks; selection and results use them."""

    def apply_scenario_marks(item: pytest.Item) -> None:
        """Fake WP-E marks: scenario(id) and tags(*tags)."""
        scenario = item.callspec.params["scenario"]  # type: ignore[attr-defined]
        item.add_marker(pytest.mark.scenario(scenario.id))
        item.add_marker(pytest.mark.tags(*scenario.tags))

    monkeypatch.setattr("otterdog_e2e.scenarios.collect.apply_scenario_marks", apply_scenario_marks)
    inner.pytester.makepyfile(
        test_scenarios="""
        from types import SimpleNamespace

        SCENARIOS = [
            SimpleNamespace(id="cli.repo.basic", tags=["repo"], priority="P0", variables={}),
            SimpleNamespace(id="cli.team.basic", tags=["teams"], priority="P1", variables={}),
        ]

        def pytest_generate_tests(metafunc):
            if "scenario" in metafunc.fixturenames:
                metafunc.parametrize("scenario", SCENARIOS, ids=lambda s: s.id)

        def test_scenario(scenario):
            pass
        """
    )
    inner.run("--e2e-tags=repo").assert_outcomes(passed=1, deselected=1)
    [line] = inner.results()
    assert line["scenario"] == "cli.repo.basic" and line["priority"] == "P0" and line["tags"] == ["repo"]


def test_python_items_record_the_priority_of_their_scenario_marker(inner: Inner) -> None:
    """results.jsonl takes the priority of a Python test from its scenario(id, priority=...) marker (the cli and webapp
    tier budgets only count P0 items, and items without a priority)."""
    inner.pytester.makepyfile(
        test_markers="""
        import pytest

        @pytest.mark.scenario("cli.example.p2", priority="P2")
        def test_p2():
            pass

        @pytest.mark.scenario("cli.example.none")
        def test_without_priority():
            pass
        """
    )
    inner.run().assert_outcomes(passed=2)
    priorities = {line["scenario"]: line["priority"] for line in inner.results()}
    assert priorities == {"cli.example.p2": "P2", "cli.example.none": None}


def test_tier_directories_get_markers_and_timeouts(inner: Inner) -> None:
    """tests/<tier>/ items get their tier marker (offline, live, differential) and the tier timeout."""
    inner.pytester.mkpydir("tests")
    for tier in ("offline", "cli", "webapp", "differential", "unit"):
        directory = inner.pytester.path / "tests" / tier
        directory.mkdir()
        (directory / f"test_{tier}_tier.py").write_text("def test_it():\n    pass\n")
    explicit = inner.pytester.path / "tests" / "cli" / "test_cli_explicit.py"
    explicit.write_text("import pytest\n\n@pytest.mark.timeout(42)\ndef test_it():\n    pass\n")
    recorder = inner.pytester.inline_run("--collect-only", "-p", "no:cacheprovider", f"--e2e-run-id={FAKE_RUN_ID}")
    items = {item.path.stem: item for item in recorder.getcalls("pytest_collection_finish")[0].session.items}

    def marks(name: str) -> tuple[set[str], int | None]:
        """Marker names and timeout of an item."""
        item = items[name]
        timeout = item.get_closest_marker("timeout")
        return {mark.name for mark in item.iter_markers()}, (timeout.args[0] if timeout else None)

    assert {"offline"} <= marks("test_offline_tier")[0] and marks("test_offline_tier")[1] == 300
    assert {"live"} <= marks("test_cli_tier")[0] and marks("test_cli_tier")[1] == 600
    assert {"live"} <= marks("test_webapp_tier")[0] and marks("test_webapp_tier")[1] == 900
    assert {"differential"} <= marks("test_differential_tier")[0]
    assert marks("test_unit_tier") == (set(), None)
    assert marks("test_cli_explicit")[1] == 42

    def func_only(name: str) -> Any:
        """func_only of an item's (closest) timeout marker."""
        return items[name].get_closest_marker("timeout").kwargs.get("func_only")

    # F1: live items time their call only (the first one pays for the session setup); offline items time everything
    assert func_only("test_cli_tier") is True and func_only("test_webapp_tier") is True
    assert func_only("test_cli_explicit") is True and func_only("test_offline_tier") is None


def test_live_session_setup_is_not_timed_by_the_first_item(inner: Inner, tmp_path: Path) -> None:
    """F1: the live session is built in pytest_runtestloop (before any item timer), and a slow session fixture (the
    baseline reset) does not count against the first live item's timeout: both items pass."""
    calls = inner.live(identities=("admin",))
    inner.pytester.mkpydir("tests")
    directory = inner.pytester.path / "tests" / "cli"
    directory.mkdir()
    (directory / "test_slow_setup.py").write_text(
        "import time\n"
        "import pytest\n\n"
        "@pytest.fixture(scope='session')\n"
        "def slow_reset():\n"
        "    time.sleep(2.5)\n\n"
        "@pytest.mark.timeout(1)\n"
        "def test_first(slow_reset):\n"
        "    pass\n\n"
        "@pytest.mark.timeout(1)\n"
        "def test_second(slow_reset):\n"
        "    pass\n"
    )
    result = inner.run("-rA")
    result.assert_outcomes(passed=2)
    result.stdout.fnmatch_lines(["*otterdog-e2e: verifying the target fake and taking the org lease ...*"])
    assert calls[0] == "ensure_live"


def test_results_jsonl_and_reports_are_redacted(inner: Inner) -> None:
    """Every item gets a results.jsonl line; secrets never reach the terminal, the reports or results.jsonl."""
    secret = "e2e-hook-secret-" + secrets.token_hex(8)
    REDACTOR.add(secret)
    inner.pytester.makepyfile(
        test_report=f"""
        import pytest

        pytestmark = pytest.mark.offline

        def test_pass():
            pass

        def test_fail():
            print("leaking {secret} on stdout")
            assert False, "token {secret} in the message"

        def test_skip():
            pytest.skip("not today")

        @pytest.mark.xfail(reason="expected")
        def test_xfail():
            assert False
        """
    )
    result = inner.run("-rA")
    result.assert_outcomes(passed=1, failed=1, skipped=1, xfailed=1)
    assert secret not in result.stdout.str() and secret not in result.stderr.str()
    lines = {line["nodeid"].split("::")[-1]: line for line in inner.results()}
    assert {name: line["outcome"] for name, line in lines.items()} == {
        "test_pass": "passed",
        "test_fail": "failed",
        "test_skip": "skipped",
        "test_xfail": "xfailed",
    }
    failed = lines["test_fail"]
    assert "***" in failed["failure"] and failed["when"] == "call" and failed["infra"] is False
    assert set(failed["phases"]) == {"setup", "call", "teardown"} and "offline" in failed["markers"]
    assert lines["test_skip"]["reason"] == "not today" and lines["test_xfail"]["reason"] == "expected"
    for path in inner.artifacts.iterdir():
        assert secret not in path.read_text(), path
    assert (inner.artifacts / "summary.md").read_text().startswith("# summary of")
    run = json.loads((inner.artifacts / "run.json").read_text())
    assert run["run_id"] == FAKE_RUN_ID and run["exitstatus"] == 1 and "finished_at" in run


def test_infra_failures_are_classified(inner: Inner) -> None:
    """Rate limits and connection problems are infra, not product failures."""
    inner.pytester.makepyfile(
        test_infra="""
        import pytest

        @pytest.mark.offline
        def test_rate_limited():
            raise AssertionError("otterdog plan failed (exit code 1, infra error: secondary rate limit)")
        """
    )
    inner.run().assert_outcomes(failed=1)
    [line] = inner.results()
    assert line["infra"] is True


def test_showlocals_refused_with_live_items(inner: Inner) -> None:
    """-l/--showlocals is a usage error when live items are selected, fine otherwise."""
    inner.pytester.makepyfile(
        test_locals="""
        import pytest

        @pytest.mark.live
        def test_live():
            pass
        """
    )
    result = inner.run("-l")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "--showlocals" in result.stderr.str()
    inner.pytester.makepyfile(test_locals="def test_plain():\n    pass\n")
    inner.run("--showlocals").assert_outcomes(passed=1)


def test_trust_code_refused_in_ci(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """--e2e-trust-code is a usage error when CI is set."""
    monkeypatch.setenv("CI", "true")
    inner.pytester.makepyfile(test_trust="def test_plain():\n    pass\n")
    result = inner.run("--e2e-trust-code=" + "a" * 40)
    assert result.ret == pytest.ExitCode.USAGE_ERROR and "refused when CI is set" in result.stderr.str()


@pytest.mark.parametrize("target", ["free,team", "@all", "@nightly"])
def test_a_live_session_has_one_target(inner: Inner, monkeypatch: pytest.MonkeyPatch, target: str) -> None:
    """--e2e-target (or E2E_TARGET) naming several targets is a usage error when live items are selected: a session
    loads the env files of one org (otterdog-e2e run starts one session per target); sessions without live items
    (unit, offline: an exported list for make) are not affected."""
    inner.pytester.makepyfile(
        test_live="""
        import pytest

        @pytest.mark.live
        def test_live():
            pass
        """,
        test_plain="def test_plain():\n    pass\n",
    )
    result = inner.run(f"--e2e-target={target}")
    assert result.ret == pytest.ExitCode.USAGE_ERROR
    assert "names one target" in result.stderr.str() and "otterdog-e2e run --target a,b" in result.stderr.str()
    monkeypatch.setenv("E2E_TARGET", target)
    assert inner.run().ret == pytest.ExitCode.USAGE_ERROR
    inner.run("test_plain.py").assert_outcomes(passed=1)  # no live item selected


def test_trust_code_needs_a_full_sha(inner: Inner) -> None:
    """--e2e-trust-code names exactly one commit: anything but 40 hex digits is a usage error."""
    inner.pytester.makepyfile(test_trust="def test_plain():\n    pass\n")
    result = inner.run("--e2e-trust-code=abc1234")
    assert result.ret == pytest.ExitCode.USAGE_ERROR and "full 40-hex sha" in result.stderr.str()
    inner.run("--e2e-trust-code=" + "A" * 40).assert_outcomes(passed=1)


WEBAPP_ITEM = """
import pytest

@pytest.mark.live
@pytest.mark.webapp
def test_webapp():
    pass
"""


def test_untrusted_sha_suts_skip_webapp_items_without_config_reader(
    inner: Inner, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A sha: SUT that resolves untrusted skips webapp items before any fixture (no config_reader identity)."""
    resolved: list[str] = []

    def resolve_sut(spec: Any, settings: Any, *, http: Any = None) -> SimpleNamespace:
        """An untrusted commit (not on main nor a release tag)."""
        resolved.append(spec.raw)
        return SimpleNamespace(trusted=False)

    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", resolve_sut)
    inner.live(identities=("admin",), app_ok=True)
    inner.pytester.makepyfile(test_webapp=WEBAPP_ITEM)
    sha = secrets.token_hex(20)
    result = inner.run("-rs", f"--e2e-sut=sha:{sha}")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines([f"*untrusted SUT sha:{sha}: the webapp tier needs a config_reader identity*"])
    assert resolved == [f"sha:{sha}"]
    inner.live(identities=("admin", "config_reader"), app_ok=True)
    inner.run(f"--e2e-sut=sha:{sha}").assert_outcomes(passed=1)


def test_pr_suts_skip_webapp_items_without_resolution(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """pr: SUTs are untrusted by their spec: the gate never resolves them; trusted SUTs are not gated."""

    def resolve_sut(spec: Any, settings: Any, *, http: Any = None) -> Any:
        """The gate must not resolve."""
        raise AssertionError(f"resolved {spec.raw}")

    monkeypatch.setattr("otterdog_e2e.sut.spec.resolve_sut", resolve_sut)
    inner.live(identities=("admin",), app_ok=True)
    inner.pytester.makepyfile(test_webapp=WEBAPP_ITEM)
    result = inner.run("-rs", f"--e2e-sut=pr:792@{secrets.token_hex(20)}")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*untrusted SUT pr:792@*config_reader identity*"])
    inner.run("--e2e-sut=release:latest").assert_outcomes(passed=1)


def test_sigterm_runs_finalizers(inner: Inner, tmp_path: Path) -> None:
    """SIGTERM raises KeyboardInterrupt: session fixtures are finalized (cleanup, lease release)."""
    mark = tmp_path / "finalized.txt"
    inner.pytester.makepyfile(
        test_term=f"""
        import os
        import pathlib
        import signal

        import pytest

        MARK = pathlib.Path(r"{mark}")

        @pytest.fixture(scope="session")
        def resource():
            yield
            MARK.write_text("finalized")

        def test_terminated(resource):
            os.kill(os.getpid(), signal.SIGTERM)

        def test_never_reached():
            pass
        """
    )
    result = inner.run(no_reraise_ctrlc=True)
    assert result.ret == pytest.ExitCode.INTERRUPTED
    assert mark.read_text() == "finalized"


def test_second_interruption_does_not_abort_the_cleanup(inner: Inner, tmp_path: Path) -> None:
    """Once interrupted (SIGTERM or Ctrl-C), later SIGTERMs are ignored so the teardown completes."""
    marks = {name: tmp_path / f"{name}.txt" for name in ("term", "ctrl_c")}
    inner.pytester.makepyfile(
        test_twice="""
        import os
        import pathlib
        import signal

        import pytest

        @pytest.fixture(scope="session")
        def resource(request):
            yield
            os.kill(os.getpid(), signal.SIGTERM)  # GitHub's SIGTERM arriving during the cleanup
            pathlib.Path(request.config.getoption("--mark")).write_text("cleanup completed")

        def test_interrupted(resource, request):
            if request.config.getoption("--mode") == "term":
                os.kill(os.getpid(), signal.SIGTERM)
            raise KeyboardInterrupt
        """
    )
    inner.pytester.makeconftest(
        """
        def pytest_addoption(parser):
            parser.addoption("--mark")
            parser.addoption("--mode")
        """
    )
    for mode, mark in marks.items():
        result = inner.run(f"--mark={mark}", f"--mode={mode}", no_reraise_ctrlc=True)
        assert result.ret == pytest.ExitCode.INTERRUPTED
        assert mark.read_text() == "cleanup completed", mode


def test_differential_items_without_base_are_skipped(inner: Inner) -> None:
    """differential items need --e2e-base-sut."""
    inner.pytester.makepyfile(
        test_diff="""
        import pytest

        @pytest.mark.differential
        def test_diff():
            pass
        """
    )
    result = inner.run("-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines(["*without a base SUT*--e2e-base-sut*"])


def test_strict_diff_fails_on_unexpected_deltas(inner: Inner) -> None:
    """Observations of both sides are compared at session end; --e2e-strict-diff turns deltas into a failure."""
    observations = inner.artifacts / "observations"

    def line(role: str, content: str) -> str:
        """One observation record."""
        record = {
            "sut": f"{role}-sut",
            "role": role,
            "scenario": "O-VAL-RULESET-STRICT",
            "step": "validate",
            "kind": "cli",
        }
        return json.dumps({**record, "key": "validate", "content": content, "meta": {}}) + "\n"

    base_line = line("base", "exit_code: 1\nAttributeError")
    head_line = line("head", "exit_code: 0\nValidation succeeded")
    inner.pytester.makepyfile(
        test_observe=f"""
        import pathlib

        import pytest

        @pytest.mark.offline
        def test_record():
            directory = pathlib.Path(r"{observations}")
            directory.mkdir(parents=True, exist_ok=True)
            (directory / "base.jsonl").write_text({base_line!r})
            (directory / "head.jsonl").write_text({head_line!r})
        """
    )
    lenient = inner.run()
    lenient.assert_outcomes(passed=1)
    assert lenient.ret == pytest.ExitCode.OK
    report = json.loads((inner.artifacts / "differential.json").read_text())
    assert report["counts"]["unexpected"] == 1 and (inner.artifacts / "differential.md").exists()
    strict = inner.run("--e2e-strict-diff")
    strict.assert_outcomes(passed=1)
    assert strict.ret == pytest.ExitCode.TESTS_FAILED


def test_scrub_leaks_fail_the_session(inner: Inner) -> None:
    """A leak found by the artifact scrub fails an otherwise green session."""
    inner.leaks.append(Path("cli/0001-plan/stdout.txt"))
    inner.pytester.makepyfile(test_leak="import pytest\n\n@pytest.mark.offline\ndef test_ok():\n    pass\n")
    result = inner.run()
    result.assert_outcomes(passed=1)
    assert result.ret == pytest.ExitCode.TESTS_FAILED


def test_step_summary_is_appended(inner: Inner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """$GITHUB_STEP_SUMMARY receives the (redacted) summary."""
    step_summary = tmp_path / "step-summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(step_summary))
    inner.pytester.makepyfile(test_summary="import pytest\n\n@pytest.mark.offline\ndef test_ok():\n    pass\n")
    inner.run().assert_outcomes(passed=1)
    assert step_summary.read_text().startswith("# summary of")


def test_live_fixtures_refuse_non_live_tests(inner: Inner) -> None:
    """A non-live test requesting a live fixture errors with an explanation; sut_pair needs differential."""
    inner.pytester.makepyfile(
        test_misuse="""
        import pytest

        @pytest.mark.offline
        def test_wants_org(verified_org):
            pass

        @pytest.mark.offline
        def test_wants_pair(sut_pair):
            pass
        """
    )
    result = inner.run()
    result.assert_outcomes(errors=2)
    result.stdout.fnmatch_lines(
        ["*live fixture 'e2e' unavailable*", "*sut_pair is only available to tests marked differential*"],
        consecutive=False,
    )


def test_offline_fixtures(inner: Inner) -> None:
    """scenario_vars and fresh_workspace of offline tests use the offline org."""
    inner.pytester.makepyfile(
        test_offline_fixtures="""
        import pytest

        @pytest.mark.offline
        def test_vars(scenario_vars, fresh_workspace, run_ctx):
            assert scenario_vars["org"] == "e2e-offline" and scenario_vars["p"] == run_ctx.prefix
            assert fresh_workspace.org == "e2e-offline" and fresh_workspace.config_file.exists()
        """
    )
    inner.run().assert_outcomes(passed=1)


def test_session_context_is_closed(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """The context is closed at session end: lease released and scratch removed."""
    released: list[str] = []
    monkeypatch.setattr(E2EContext, "release_lease", lambda self: released.append(self.run_ctx.run_id))
    inner.pytester.makepyfile(test_close="import pytest\n\n@pytest.mark.offline\ndef test_ok():\n    pass\n")
    inner.run().assert_outcomes(passed=1)
    assert released == [FAKE_RUN_ID]
    assert not (inner.settings.cache_dir / "run" / FAKE_RUN_ID).exists()


@pytest.fixture
def wired(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Fake live session whose context factories record setup/teardown events."""
    from otterdog_e2e.testing.fakes import FakeBaselineManager, FakeOracle, RecordingMutator

    events: list[str] = []
    inner.live(plan="free", identities=("admin", "author"), app_ok=True)

    class Baseline(FakeBaselineManager):
        """Records resets as events."""

        def reset(self) -> Any:
            """Record."""
            events.append("baseline.reset")
            return super().reset()

    class Deployment:
        """Running webapp stand-in."""

        base_url = "http://127.0.0.1:5000"
        webhook_url = "http://127.0.0.1:5000/github-webhook/receive"

    class Relay:
        """DeliveryRelay stand-in."""

        def stop(self, timeout: float = 10) -> None:
            """Record."""
            events.append("relay.stop")

    class Flow:
        """ConfigRepoFlow stand-in."""

        def cleanup(self) -> None:
            """Record."""
            events.append("flow.cleanup")

    def record(name: str, value: Any = None) -> Any:
        """Factory recording ``name``."""

        def factory(self: E2EContext, *args: Any, **kwargs: Any) -> Any:
            """Record and return the value."""
            events.append(name)
            return value() if callable(value) else value

        return factory

    patches = {
        "template_for": record("template", SimpleNamespace(url="t")),
        "renderer": record("renderer", SimpleNamespace()),
        "workspace": record("workspace", SimpleNamespace()),
        "installed": record("installed", SimpleNamespace(sut=SimpleNamespace(label="v1.6.1"))),
        "cli": record("cli", SimpleNamespace()),
        "baseline_manager": record("baseline", Baseline),
        "scenario_variables": record("variables", dict),
        "oracle": record("oracle", FakeOracle),
        "mutator": record("mutator", RecordingMutator),
        "start_webapp": record("webapp.start", Deployment),
        "stop_webapp": record("webapp.stop"),
        "start_relay": record("relay.start", Relay),
        "installation_id": record("installation", 4242),
        "app_auth": record("app_auth", SimpleNamespace(bot_login="otterdog-e2e-test[bot]")),
        "config_flow": record("flow", Flow),
        "begin_webapp_case": record("case.begin", SimpleNamespace()),
        "end_webapp_case": record("case.end"),
        "sweep_own_run": record("sweep"),
        "require_app_credentials": record("credentials", SimpleNamespace(webhook_secret="hook-secret-1234")),
    }
    for name, factory in patches.items():
        monkeypatch.setattr(E2EContext, name, factory)
    return events


def test_live_fixture_graph_order(inner: Inner, wired: list[str]) -> None:
    """Setup: reset before the webapp, relay after it; teardown in reverse: case, flow, relay, webapp, sweep."""
    inner.pytester.makepyfile(
        test_graph="""
        import pytest

        @pytest.mark.live
        def test_cli_graph(scenario_engine, otterdog, reset_cli, workspace, renderer, mutators):
            assert scenario_engine.cli is otterdog and set(mutators) == {"admin", "author"}

        @pytest.mark.live
        @pytest.mark.webapp
        def test_webapp_graph(webapp_case, injector, webapp_api):
            assert webapp_api.base_url == "http://127.0.0.1:5000"
            assert injector.endpoint_url.endswith("/github-webhook/receive")
        """
    )
    inner.run().assert_outcomes(passed=2)
    setup = [event for event in wired if event in ("baseline.reset", "webapp.start", "relay.start", "case.begin")]
    assert setup == ["baseline.reset", "webapp.start", "relay.start", "case.begin"]
    teardown = [event for event in wired if event in ("case.end", "flow.cleanup", "relay.stop", "webapp.stop", "sweep")]
    assert teardown == ["case.end", "flow.cleanup", "relay.stop", "webapp.stop", "sweep"]
    assert wired.count("baseline.reset") == 1 and wired.index("installation") < wired.index("relay.start")


def test_no_reset_and_keep(inner: Inner, wired: list[str]) -> None:
    """--e2e-no-reset skips the first reset; --e2e-keep skips the session sweep and the webapp cleanups."""
    inner.pytester.makepyfile(
        test_keep="""
        import pytest

        @pytest.mark.live
        @pytest.mark.webapp
        def test_webapp(webapp_case, baseline):
            pass
        """
    )
    inner.run("--e2e-no-reset", "--e2e-keep").assert_outcomes(passed=1)
    assert "baseline.reset" not in wired
    assert not {"sweep", "case.end", "flow.cleanup"} & set(wired)
    assert "webapp.stop" in wired and "relay.stop" in wired


def test_timeout_marks_stay_valid_without_pytest_timeout(inner: Inner) -> None:
    """With -p no:timeout the plugin registers the timeout marker: --strict-markers still accepts tier and scenario
    timeouts (they are simply not enforced)."""
    inner.pytester.makepyfile(
        test_timeouts="""
        import pytest

        @pytest.mark.timeout(1800)
        @pytest.mark.offline
        def test_slow_first_item():
            pass
        """
    )
    inner.run("--strict-markers", "-p", "no:timeout").assert_outcomes(passed=1)


def test_suts_are_prepared_before_the_first_item(inner: Inner, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """pytest_runtestloop installs the SUT roles of the runnable items before any item (and its timer) starts;
    statically skipped items (live without target) and misused sut_pair fixtures add nothing; a failing preparation
    only reports, the fixture raises it again for the items that need it."""
    events = tmp_path / "events.txt"

    def installed(context: E2EContext, role: str) -> Any:
        """Fake install recording the role (base fails)."""
        with events.open("a") as handle:
            handle.write(f"prepare {role}\n")
        if role == "base":
            raise RuntimeError("base SUT unavailable")
        return SimpleNamespace(role=role)

    monkeypatch.setattr(E2EContext, "installed", installed)
    inner.pytester.makepyfile(
        test_prepare=f"""
        import pathlib
        import pytest

        EVENTS = pathlib.Path(r"{events}")

        @pytest.mark.offline
        def test_first(sut):
            EVENTS.open("a").write("item test_first\\n")
            assert sut.role == "head"

        @pytest.mark.differential
        def test_needs_base(base_sut):
            pass

        @pytest.mark.live
        def test_live_skipped(reset_sut):
            pass

        @pytest.mark.offline
        def test_misused_pair(sut_pair):
            pass
        """
    )
    result = inner.run("--e2e-base-sut=tag:v1.6.0", "-rs")
    result.assert_outcomes(passed=1, skipped=1, errors=2)
    lines = events.read_text().splitlines()
    # both roles before the first item (the fake is not memoized like E2EContext.installed: fixtures call it again)
    assert lines[:2] == ["prepare head", "prepare base"] and lines.index("item test_first") > 1, lines
    result.stdout.fnmatch_lines(
        ["*otterdog-e2e: preparing the head SUT (release:latest)*", "*base SUT unavailable: RuntimeError*"],
        consecutive=False,
    )
    run = json.loads((inner.artifacts / "run.json").read_text())
    assert set(run["sut_prepare_seconds"]) == {"SUT:head", "SUT:base"}


def test_collect_only_sessions_leave_no_artifacts(inner: Inner) -> None:
    """--collect-only collects e2e items (context created) but writes no summary and removes its artifacts dir."""
    inner.pytester.makepyfile(test_collected="import pytest\n\n@pytest.mark.offline\ndef test_x():\n    pass\n")
    result = inner.run("--collect-only", "-q")
    assert result.ret == pytest.ExitCode.OK and inner.summaries == []
    assert not inner.artifacts.exists()
    inner.run().assert_outcomes(passed=1)  # a real session keeps its artifacts
    assert (inner.artifacts / "run.json").is_file() and inner.summaries


# --- webapp tier extras: identity mutators, compose-only fixtures, dtrack mock, blueprints ------------------------------
def live_session(
    inner: Inner,
    *,
    identities: tuple[str, ...] = ("admin",),
    transport: str = "relay",
    docker_ok: bool = True,
    app_ok: bool = True,
) -> None:
    """Like Inner.live, with the webapp transport of the target chosen."""
    from otterdog_e2e.settings import WebappSpec

    inner.live(identities=identities, docker_ok=docker_ok, app_ok=app_ok)
    original = E2EContext.ensure_live

    def ensure_live(context: E2EContext) -> None:
        """Fake live session with the chosen transport."""
        original(context)
        url = "http://127.0.0.1:5000" if transport == "external" else None
        spec = WebappSpec(transport, url, None, "e2e/otterdog-validate", "e2e/otterdog-sync", 1, 5000)
        context.target = make_target(webapp=spec)

    inner.monkeypatch.setattr(E2EContext, "ensure_live", ensure_live)


def test_identity_mutator_fixtures_are_gated_like_identities(inner: Inner, monkeypatch: pytest.MonkeyPatch) -> None:
    """outsider_mutator / approver_mutator / contributor_mutator (= author) skip before any fixture without their
    identity and give that identity's Mutator otherwise."""
    from otterdog_e2e.context import E2EContext as Context

    monkeypatch.setattr(Context, "mutator", lambda self, name="admin": f"mutator:{name}")
    inner.pytester.makepyfile(
        test_mutators="""
        import pytest

        @pytest.mark.live
        def test_contributor(contributor_mutator):
            assert contributor_mutator == "mutator:author"

        @pytest.mark.live
        def test_approver(approver_mutator):
            assert approver_mutator == "mutator:approver"

        @pytest.mark.live
        def test_outsider(outsider_mutator):
            assert outsider_mutator == "mutator:outsider"
        """
    )
    live_session(inner, identities=("admin",))
    result = inner.run("-rs")
    result.assert_outcomes(skipped=3)
    result.stdout.fnmatch_lines(
        ["*missing identities: author*", "*missing identities: approver*", "*missing identities: outsider*"],
        consecutive=False,
    )
    live_session(inner, identities=("admin", "author", "approver", "outsider"))
    inner.run().assert_outcomes(passed=3)


COMPOSE_ITEMS = """
import pytest

@pytest.mark.live
@pytest.mark.webapp
def test_stack(webapp_stack):
    pass
"""


@pytest.mark.parametrize(
    ("transport", "docker_ok", "reason"),
    [
        ("external", True, "*webapp_stack need(s) the compose webapp stack (webapp transport is 'external')*"),
        ("relay", False, "*docker is not available*"),
    ],
)
def test_compose_only_fixtures_are_gated(inner: Inner, transport: str, docker_ok: bool, reason: str) -> None:
    """webapp_stack / webapp_env / dtrack_mock skip unless the webapp runs in the compose stack with docker."""
    inner.pytester.makepyfile(test_compose=COMPOSE_ITEMS)
    live_session(inner, transport=transport, docker_ok=docker_ok)
    result = inner.run("-rs")
    result.assert_outcomes(skipped=1)
    result.stdout.fnmatch_lines([reason])


class StackStandIn:
    """Compose WebappStack stand-in (installed as otterdog_e2e.webapp.stack.WebappStack for isinstance)."""

    events: list[str] = []

    def __init__(self) -> None:
        """No overrides yet."""
        self.base_url = "http://127.0.0.1:5000"
        self.webhook_url = "http://127.0.0.1:5000/github-webhook/receive"
        self.env_overrides: dict[str, str] = {}

    def restart_webapp(self, env: Any = None, *, timeout: float = 300) -> None:
        """Record and keep the overrides."""
        self.events.append(f"restart:{sorted(env or {})}")
        self.env_overrides = dict(env or {})


def test_webapp_stack_and_webapp_env(inner: Inner, wired: list[str], monkeypatch: pytest.MonkeyPatch) -> None:
    """webapp_stack is the compose stack; webapp_env applies overrides and restores the defaults after the test."""
    from otterdog_e2e.webapp import stack as stack_module

    StackStandIn.events = wired
    monkeypatch.setattr(stack_module, "WebappStack", StackStandIn)
    monkeypatch.setattr(E2EContext, "start_webapp", lambda self, baseline, template: StackStandIn())
    inner.pytester.makepyfile(
        test_env="""
        import pytest

        @pytest.mark.live
        @pytest.mark.webapp
        def test_env(webapp_stack, webapp_env):
            webapp_env({"GITHUB_ADMIN_TEAMS": "a, otterdog-admins"})
            assert webapp_stack.env_overrides == {"GITHUB_ADMIN_TEAMS": "a, otterdog-admins"}

        @pytest.mark.live
        @pytest.mark.webapp
        def test_untouched(webapp_env):
            pass
        """
    )
    inner.run().assert_outcomes(passed=2)
    assert [event for event in wired if event.startswith("restart")] == ["restart:['GITHUB_ADMIN_TEAMS']", "restart:[]"]


def test_webapp_stack_refuses_other_deployments(inner: Inner, wired: list[str]) -> None:
    """The fixture fails clearly when the session webapp is not a compose stack (external transport)."""
    inner.pytester.makepyfile(test_compose=COMPOSE_ITEMS)
    result = inner.run()
    result.assert_outcomes(errors=1)
    result.stdout.fnmatch_lines(["*webapp_stack needs the compose webapp stack*"])


def test_dtrack_mock_fixture_resets_the_mock_and_requests_it_early(
    inner: Inner, wired: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A selected item using dtrack_mock sets extras["dtrack_mock"] before the first item (the stack then starts with
    the mock); the fixture empties the mock and makes it answer 200 before and after the test."""

    class Client:
        """DtrackMock stand-in."""

        def clear(self) -> None:
            """Record."""
            wired.append("mock.clear")

        def set_response(self, status: int = 200, body: str | None = None) -> None:
            """Record."""
            wired.append(f"mock.status:{status}")

    monkeypatch.setattr(E2EContext, "dtrack_mock", lambda self, deployment: Client())
    inner.pytester.makepyfile(
        test_mock="""
        import pytest
        from otterdog_e2e.context import get_context

        @pytest.mark.live
        def test_flag_is_set_before_the_first_item(request):
            assert get_context(request.config).extras.get("dtrack_mock") is True

        @pytest.mark.live
        @pytest.mark.webapp
        def test_mock(dtrack_mock):
            dtrack_mock.set_response(500)
        """
    )
    inner.run().assert_outcomes(passed=2)
    assert [event for event in wired if event.startswith("mock.")] == [
        "mock.clear",
        "mock.status:200",
        "mock.status:500",
        "mock.status:200",
        "mock.clear",
    ]


def test_no_dtrack_flag_without_dtrack_items(inner: Inner) -> None:
    """Sessions without dtrack_mock items leave the stack as it is."""
    inner.live()
    inner.pytester.makepyfile(
        test_plain="""
        import pytest
        from otterdog_e2e.context import get_context

        @pytest.mark.live
        def test_flag(request):
            assert "dtrack_mock" not in get_context(request.config).extras
        """
    )
    inner.run().assert_outcomes(passed=1)


def test_blueprints_fixture_sweeps_first_and_cleans_up_before_the_case(
    inner: Inner, wired: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """blueprints: stale definitions swept at setup, the helper's cleanup after the test and before the webapp_case
    cleanup; --e2e-keep skips the cleanup."""

    class Helper:
        """BlueprintHelper stand-in."""

        def sweep_stale(self) -> list[str]:
            """Record."""
            wired.append("helper.sweep")
            return []

        def cleanup(self) -> None:
            """Record."""
            wired.append("helper.cleanup")

    def blueprint_helper(self: E2EContext, case: Any, *, relay: Any = None) -> Helper:
        """Record the wiring."""
        wired.append(f"helper.create(relay={type(relay).__name__})")
        return Helper()

    monkeypatch.setattr(E2EContext, "blueprint_helper", blueprint_helper)
    inner.pytester.makepyfile(
        test_bp="""
        import pytest

        @pytest.mark.live
        @pytest.mark.webapp
        def test_blueprints(blueprints):
            blueprints.cleanup  # the helper is handed over
        """
    )
    inner.run().assert_outcomes(passed=1)
    order = [event for event in wired if event.startswith(("helper.", "case."))]
    assert order == ["case.begin", "helper.create(relay=Relay)", "helper.sweep", "helper.cleanup", "case.end"]
    wired.clear()
    inner.run("--e2e-keep").assert_outcomes(passed=1)
    assert "helper.cleanup" not in wired and "helper.sweep" in wired


def test_adhoc_items_have_their_own_tier() -> None:
    """tests/adhoc (otterdog-e2e inject) is a tier directory of its own in results.jsonl."""
    from otterdog_e2e.pytest_plugin import TIER_DIRS, item_tier

    assert "adhoc" in TIER_DIRS
    assert item_tier(SimpleNamespace(path=Path("/p/tests/adhoc/test_adhoc.py"))) == "adhoc"  # type: ignore[arg-type]


def test_webapp_otterdog_json_fixture_restores_the_file(
    inner: Inner, wired: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """apply(organization) publishes and reloads; the run's otterdog.json is published and reloaded after the test."""

    def publish(self: E2EContext, template: Any, *, organization: Any = None) -> None:
        """Record."""
        wired.append(f"publish:{sorted(organization or {})}")

    monkeypatch.setattr(E2EContext, "publish_otterdog_json", publish)
    monkeypatch.setattr(E2EContext, "reload_webapp", lambda self, deployment: wired.append("reload"))
    inner.pytester.makepyfile(
        test_json="""
        import pytest

        @pytest.mark.live
        @pytest.mark.webapp
        def test_teams(webapp_otterdog_json):
            webapp_otterdog_json({"admin_teams": ["e2e-admins"], "approval_teams": None})

        @pytest.mark.live
        @pytest.mark.webapp
        def test_untouched(webapp_otterdog_json):
            pass
        """
    )
    inner.run().assert_outcomes(passed=2)
    assert [e for e in wired if e.startswith(("publish", "reload"))] == [
        "publish:['admin_teams', 'approval_teams']",
        "reload",
        "publish:[]",
        "reload",
    ]
