"""batch.py: target lists (comma lists, @all, @<list>), batch plans (distinct run ids, one org per parallel target,
webapp ports), the child processes (pristine environment, prefixed lines, fail-fast, forwarded signals), the exit code
and the batch summary."""

from __future__ import annotations

import json
import os
import shutil
import signal
import stat
import sys
import textwrap
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from otterdog_e2e import batch, naming, procs, settings
from otterdog_e2e.batch import BatchEntry, BatchError, BatchPlan, BatchResult
from otterdog_e2e.redact import Redactor
from otterdog_e2e.settings import HarnessSettings
from otterdog_e2e.testing.fakes import make_settings

PROJECT = Path(__file__).resolve().parents[2]
TOKEN = "ghp_" + "b" * 36


@dataclass
class World:
    """A project with the free and team profiles and a HOME holding instance env files."""

    settings: HarnessSettings
    environ: dict[str, str]
    config: Path
    redactor: Redactor = field(default_factory=Redactor)

    def instance(self, name: str, profile: str | None, org_id: int, **extra: str) -> Path:
        """Write ~/.config/otterdog-e2e/<name>.env (0600) of an instance of the org ``<name>-e2e``."""
        values = {
            "E2E_ORG": f"{name}-e2e",
            "E2E_ORG_ID": str(org_id),
            "E2E_ADMIN_LOGIN": f"{name}-admin",
            "E2E_ADMIN_TOKEN": TOKEN,
            **({"E2E_PROFILE": profile} if profile else {}),
            **extra,
        }
        path = self.config / f"{name}.env"
        path.write_text("".join(f"{key}={value}\n" for key, value in values.items()), encoding="utf-8")
        path.chmod(0o600)
        return path


@pytest.fixture
def world(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> World:
    """Profiles free and team, instances acme (free, org 11) and beta (team, org 22), the env file of the profile
    instance free (org 33); a fresh redactor."""
    root = tmp_path / "project"
    (root / "targets").mkdir(parents=True)
    for profile in ("free", "team"):
        shutil.copy(PROJECT / "targets" / f"{profile}.yaml", root / "targets" / f"{profile}.yaml")
    config = tmp_path / "home" / ".config" / "otterdog-e2e"
    config.mkdir(parents=True)
    world = World(make_settings(root), {"HOME": str(tmp_path / "home"), "E2E_KEEP_ME": "parent"}, config)
    monkeypatch.setattr(settings, "REDACTOR", world.redactor)
    monkeypatch.setattr(batch, "REDACTOR", world.redactor)
    world.instance("acme", "free", 11)
    world.instance("beta", "team", 22)
    world.instance("free", None, 33)
    return world


# --- target lists ----------------------------------------------------------------------------------------------------
def test_is_target_list() -> None:
    """A comma, @all or @<list> names several targets; a name or a path names one."""
    for value in ("a,b", " a , ", "@all", "@nightly", " @x"):
        assert batch.is_target_list(value), value
    for value in (None, "", "free", "targets/free.yaml", "a@b"):
        assert not batch.is_target_list(value), value


def test_parse_targets_splits_repeats_and_deduplicates(world: World) -> None:
    """Repeated values and comma lists in order, blanks dropped, duplicates removed; a single value is one target."""
    assert batch.parse_targets(["acme, beta", "free", "acme", " ,"], world.environ) == ("acme", "beta", "free")
    assert batch.parse_targets("targets/free.yaml", world.environ) == ("targets/free.yaml",)
    assert batch.parse_targets(None, world.environ) == () and batch.parse_targets([], world.environ) == ()


def test_all_names_every_instance_env_file(world: World) -> None:
    """@all: the stems of ~/.config/otterdog-e2e/*.env with a valid name, sorted; lists, directories, App credential
    dirs and other files are not instances."""
    (world.config / "lists").mkdir()
    (world.config / "acme").mkdir()  # App credentials of acme
    (world.config / "notes.txt").write_text("x", encoding="utf-8")
    (world.config / "Bad Name.env").write_text("x=1\n", encoding="utf-8")
    (world.config / "dir.env").mkdir()
    assert batch.env_file_instances(world.environ) == ["acme", "beta", "free"]
    assert batch.parse_targets(["beta,@all"], world.environ) == ("beta", "acme", "free")


def test_all_skips_env_files_that_can_never_be_instances(world: World) -> None:
    """A backup (acme.bak.env), a name with an underscore or a reserved one (lists.env) can never be loaded as an
    instance: @all and the targets listing ignore them instead of refusing the whole batch; an env file named after a
    profile that keeps the wider target-name rule (targets/my_org.yaml) still counts."""
    for name in ("acme.bak", "my_org", "lists", "x-webui"):
        (world.config / f"{name}.env").write_text("E2E_PROFILE=free\n", encoding="utf-8")
    assert batch.env_file_instances(world.environ, world.settings) == ["acme", "beta", "free"]
    assert batch.parse_targets("@all", world.environ, world.settings) == ("acme", "beta", "free")
    plan = batch.plan_batch(batch.parse_targets("@all", world.environ), world.settings, environ=world.environ)
    assert [entry.instance for entry in plan.entries] == ["acme", "beta", "free"]
    shutil.copy(world.settings.targets_dir / "free.yaml", world.settings.targets_dir / "my_org.yaml")
    assert batch.env_file_instances(world.environ, world.settings) == ["acme", "beta", "free", "my_org"]
    names = [info.name for info in batch.list_instances(world.settings, world.environ)]
    assert names == ["acme", "beta", "free", "my_org", "team"]


def test_all_without_env_files_is_an_error(tmp_path: Path) -> None:
    """@all with no instance env file says how to create one."""
    with pytest.raises(BatchError, match=r"no instance env file .*otterdog-e2e setup --target <instance>"):
        batch.parse_targets("@all", {"HOME": str(tmp_path)})
    assert batch.env_file_instances({"HOME": str(tmp_path)}) == []


def test_target_list_files(world: World) -> None:
    """@<list>: ~/.config/otterdog-e2e/lists/<list>, one instance per line, # comments (inline too), blank lines."""
    lists = world.config / "lists"
    lists.mkdir()
    (lists / "nightly").write_text("# the nightly orgs\nbeta\n\n  acme   # GHEC trial\n", encoding="utf-8")
    assert batch.read_target_list("nightly", world.environ) == ["beta", "acme"]
    assert batch.parse_targets("free,@nightly", world.environ) == ("free", "beta", "acme")
    assert batch.list_file("nightly", world.environ) == lists / "nightly"


@pytest.mark.parametrize(
    ("content", "name", "message"),
    [
        (None, "missing", "no list file"),
        (None, "../etc", "invalid list name"),
        (None, "", "invalid list name"),
        ("# nothing\n\n", "empty", "lists no instance"),
        ("acme,beta\n", "commas", "one instance per line"),
        ("@all\n", "nested", "one instance per line"),
        ("acme beta\n", "spaces", "one instance per line"),
    ],
)
def test_bad_target_lists(world: World, content: str | None, name: str, message: str) -> None:
    """Unknown, odd, empty or malformed lists are BatchErrors (the CLI reports a usage error)."""
    lists = world.config / "lists"
    lists.mkdir()
    if content is not None:
        (lists / name).write_text(content, encoding="utf-8")
    with pytest.raises(BatchError, match=message):
        batch.parse_targets(f"@{name}", world.environ)


def test_instance_environ_is_a_copy(world: World) -> None:
    """The env files of the target fill a copy (never overriding it); the given environment is never changed."""
    environ = {**world.environ, "E2E_ORG": "from-the-process"}
    copy = batch.instance_environ("acme", world.settings, environ)
    assert copy["E2E_ORG"] == "from-the-process" and copy["E2E_PROFILE"] == "free" and copy["E2E_ORG_ID"] == "11"
    assert environ == {**world.environ, "E2E_ORG": "from-the-process"}
    assert world.redactor(TOKEN) == "***"  # secrets of the env files are known to the parent's redactor


# --- plans -------------------------------------------------------------------------------------------------------------
def test_plan_batch_resolves_every_target_without_touching_the_environment(world: World) -> None:
    """Instance, profile, org and transport of every target; distinct run ids; the parent's environment unchanged."""
    before = dict(world.environ)
    plan = batch.plan_batch(["acme", "beta", "free"], world.settings, environ=world.environ)
    assert world.environ == before
    rows = [(e.target, e.instance, e.profile, e.org, e.org_id, e.transport, e.webapp_port) for e in plan.entries]
    assert rows == [
        ("acme", "acme", "free", "acme-e2e", 11, "relay", None),
        ("beta", "beta", "team", "beta-e2e", 22, "relay", None),
        ("free", "free", "free", "free-e2e", 33, "relay", None),
    ]
    ids = [plan.batch_id, *(entry.run_id for entry in plan.entries)]
    assert len(set(ids)) == 4 and all(naming.RUN_ID_RE.match(run_id) for run_id in ids)
    assert (plan.parallel, plan.fail_fast, plan.mode) == (1, False, "sequential")


def test_plan_batch_refuses_broken_and_duplicate_targets(world: World) -> None:
    """Every target that cannot be loaded is listed (nothing runs); one instance named twice is refused."""
    world.instance("gamma", None, 44)  # no E2E_PROFILE: not a profile either
    world.instance("delta", "free", 0)  # org id 0: invalid
    with pytest.raises(BatchError) as info:
        batch.plan_batch(["acme", "gamma", "delta"], world.settings, environ=world.environ)
    message = str(info.value)
    assert "gamma: target 'gamma' not found" in message and "delta: " in message and "acme:" not in message
    path = str(world.settings.targets_dir / "free.yaml")
    with pytest.raises(BatchError, match="the instance free is already listed"):
        batch.plan_batch(["free", path], world.settings, environ=world.environ)
    with pytest.raises(BatchError, match="at least one target"):
        batch.plan_batch([], world.settings, environ=world.environ)
    with pytest.raises(BatchError, match="at least 1"):
        batch.plan_batch(["acme"], world.settings, environ=world.environ, parallel=0)


@pytest.mark.parametrize("names", [["E2E_ORG"], ["E2E_ORG_ID"], ["E2E_PROFILE"], ["E2E_ORG", "E2E_PROFILE"]])
def test_several_targets_refuse_an_exported_org_or_profile(world: World, names: list[str]) -> None:
    """The env files never override the environment: an exported E2E_ORG, E2E_ORG_ID or E2E_PROFILE (even empty)
    would make every target of the batch test one org; refused naming the variables, never their values. One target
    keeps the in-process rules (the variable wins, as for any session)."""
    exported = {**world.environ, **dict.fromkeys(names, "")}
    exported[names[0]] = "exported-value-x"
    with pytest.raises(BatchError) as info:
        batch.plan_batch(["acme", "beta"], world.settings, environ=exported)
    message = str(info.value)
    assert all(name in message for name in names) and "exported-value-x" not in message
    assert "set in the environment" in message
    assert batch.plan_batch(["acme"], world.settings, environ={**world.environ, "E2E_PROFILE": "free"}).entries


def test_several_targets_refuse_exported_logins_and_secrets_an_env_file_sets_otherwise(world: World) -> None:
    """An exported login or secret that the env file of an instance sets to another value would be used for every
    instance (one bot's web password tried for another): refused, naming variables and instances, never values; an
    exported value equal to the files', or a variable no env file sets, is fine."""
    world.instance("acme", "free", 11, E2E_ADMIN_PASSWORD="acme-web-password-1")
    world.instance("beta", "team", 22, E2E_ADMIN_PASSWORD="beta-web-password-2")
    exported = {**world.environ, "E2E_ADMIN_PASSWORD": "acme-web-password-1", "E2E_ADMIN_LOGIN": "other-admin"}
    with pytest.raises(BatchError) as info:
        batch.plan_batch(["acme", "beta"], world.settings, environ=exported)
    message = str(info.value)
    assert "E2E_ADMIN_LOGIN (env file of acme, beta)" in message
    assert "E2E_ADMIN_PASSWORD (env file of beta)" in message
    assert "password" not in message.replace("E2E_ADMIN_PASSWORD", "") and "other-admin" not in message
    same = {**world.environ, "E2E_ADMIN_TOKEN": TOKEN, "E2E_APPROVER_TOKEN": "ghp_" + "z" * 36}
    assert len(batch.plan_batch(["acme", "beta"], world.settings, environ=same).entries) == 2
    exported_one = {**world.environ, "E2E_ADMIN_PASSWORD": "acme-web-password-1"}
    assert batch.plan_batch(["acme"], world.settings, environ=exported_one).entries  # one target: in-process rules


def test_run_ids_stay_distinct_when_new_ids_repeat(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """Ids created in the same second differ by their random part only: repeats are drawn again."""
    sequence = iter(["t3c7z8a5", "t3c7z8a5", "t3c7z8b6", "t3c7z8a5", "t3c7z8c7"])
    monkeypatch.setattr(naming, "new_run_context", lambda run_id=None, now=None: naming.RunContext(next(sequence)))
    plan = batch.plan_batch(["acme", "beta"], world.settings, environ=world.environ)
    assert [plan.batch_id, *(entry.run_id for entry in plan.entries)] == ["t3c7z8a5", "t3c7z8b6", "t3c7z8c7"]


def test_parallel_refuses_two_targets_of_one_org(world: World) -> None:
    """An org serves one session at a time (lease): parallel targets need distinct org ids; sequential is fine."""
    world.instance("acme2", "team", 11)
    with pytest.raises(BatchError, match=r"acme, acme2 \(org id 11\) test the same organization"):
        batch.plan_batch(["acme", "acme2", "beta"], world.settings, environ=world.environ, parallel=2)
    plan = batch.plan_batch(["acme", "acme2"], world.settings, environ=world.environ)
    assert [entry.org_id for entry in plan.entries] == [11, 11]


def ports(*values: int) -> Callable[[], int]:
    """A free_port stand-in returning ``values`` in turn."""
    iterator = iter(values)
    return lambda: next(iterator)


def test_parallel_relay_children_get_distinct_free_ports(world: World) -> None:
    """Relay children without a pinned port get distinct free loopback ports (a port already given is drawn again);
    a pinned E2E_WEBAPP_PORT is kept and never handed out; other transports need no port."""
    world.instance("pinned", "free", 55, E2E_WEBAPP_PORT="41001")
    world.instance("ext", "free", 66, E2E_TRANSPORT="external", E2E_EXTERNAL_URL="http://127.0.0.1:8080")
    plan = batch.plan_batch(
        ["acme", "beta", "pinned", "ext"],
        world.settings,
        environ=world.environ,
        parallel=8,
        free_port=ports(41000, 41000, 41001, 41002),
    )
    assert plan.parallel == 4 and plan.mode == "parallel 4"
    assert {entry.instance: entry.webapp_port for entry in plan.entries} == {
        "acme": 41000,
        "beta": 41002,
        "pinned": None,
        "ext": None,
    }
    assert plan.entries[0].child_env({})[batch.WEBAPP_PORT_ENV] == "41000"


def test_parallel_refuses_two_external_targets_of_one_webapp(world: World) -> None:
    """Two ``external`` targets of one webapp URL (a trailing slash aside) would reconfigure one webapp for each
    other: refused with --parallel; distinct URLs, or a sequential batch, are fine."""
    world.instance("ext1", "free", 55, E2E_TRANSPORT="external", E2E_EXTERNAL_URL="http://127.0.0.1:8080")
    world.instance("ext2", "team", 66, E2E_TRANSPORT="external", E2E_EXTERNAL_URL="http://127.0.0.1:8080/")
    world.instance("ext3", "free", 77, E2E_TRANSPORT="external", E2E_EXTERNAL_URL="http://127.0.0.1:8081")
    with pytest.raises(BatchError, match="ext1, ext2 use the same external webapp URL"):
        batch.plan_batch(["ext1", "ext2", "acme"], world.settings, environ=world.environ, parallel=3)
    plan = batch.plan_batch(["ext1", "ext3"], world.settings, environ=world.environ, parallel=2)
    assert [entry.transport for entry in plan.entries] == ["external", "external"]
    assert len(batch.plan_batch(["ext1", "ext2"], world.settings, environ=world.environ).entries) == 2


def test_parallel_refuses_equal_pinned_ports(world: World) -> None:
    """Two relay instances pinning one port would collide on the loopback: refused (and when the process environment
    pins it for every instance)."""
    world.instance("one", "free", 55, E2E_WEBAPP_PORT="6000")
    world.instance("two", "team", 66, E2E_WEBAPP_PORT="6000")
    with pytest.raises(BatchError, match="one and two pin the same webapp port 6000"):
        batch.plan_batch(["one", "two"], world.settings, environ=world.environ, parallel=2)
    exported = {**world.environ, "E2E_WEBAPP_PORT": "5000"}
    with pytest.raises(BatchError, match="acme and beta pin the same webapp port 5000"):
        batch.plan_batch(["acme", "beta"], world.settings, environ=exported, parallel=2)
    plan = batch.plan_batch(["one", "two"], world.settings, environ=world.environ)  # sequential: no port check
    assert [entry.webapp_port for entry in plan.entries] == [None, None]


def test_a_profile_with_a_literal_port_pins_it(world: World) -> None:
    """A custom profile that writes ``port: 6000`` ignores E2E_WEBAPP_PORT: its instances count as pinned."""
    text = (world.settings.targets_dir / "free.yaml").read_text(encoding="utf-8")
    custom = text.replace("port: ${E2E_WEBAPP_PORT:-5000}", "port: 6000").replace("name: free", "name: fixed")
    assert custom != text
    (world.settings.targets_dir / "fixed.yaml").write_text(custom, encoding="utf-8")
    world.instance("one", "fixed", 55)
    world.instance("two", "fixed", 66)
    with pytest.raises(BatchError, match="one and two pin the same webapp port 6000"):
        batch.plan_batch(["one", "two"], world.settings, environ=world.environ, parallel=2)
    plan = batch.plan_batch(
        ["one", "acme"], world.settings, environ=world.environ, parallel=2, free_port=ports(6000, 7)
    )
    assert [entry.webapp_port for entry in plan.entries] == [None, 7]  # never the pinned 6000


def test_child_env_is_the_parent_environment(world: World) -> None:
    """The child gets the given (parent) environment, unbuffered output and its webapp port; nothing else."""
    entry = BatchEntry("acme", "acme", "free", "acme-e2e", 11, "t3c7z8a5", webapp_port=41000)
    assert entry.child_env({"A": "1"}) == {"A": "1", "PYTHONUNBUFFERED": "1", "E2E_WEBAPP_PORT": "41000"}
    assert "E2E_WEBAPP_PORT" not in BatchEntry("a", "a", "free", "o", 1, "t3c7z8a5").child_env({})


# --- execution -----------------------------------------------------------------------------------------------------------
@dataclass
class FakeRunner:
    """procs.run_harness stand-in: records each call, prints two lines, returns the exit code of the instance."""

    codes: dict[str, int] = field(default_factory=dict)
    calls: list[dict[str, Any]] = field(default_factory=list)
    during: Callable[[str], None] | None = None

    def __call__(
        self, argv: Sequence[str], *, env: dict[str, str], on_line: Callable[[str], None], log_path: Path | None = None
    ) -> int:
        """Record the call and answer."""
        instance = next(arg.split("=", 1)[1] for arg in argv if arg.startswith("--target="))
        self.calls.append({"argv": list(argv), "env": env, "log_path": log_path, "instance": instance})
        if self.during is not None:
            self.during(instance)
        on_line(f"running {instance}")
        on_line(f"token {env.get('E2E_ADMIN_TOKEN')}")
        return self.codes.get(instance, 0)


def child_args(entry: BatchEntry) -> list[str]:
    """The child arguments of the tests: ``run --target=<t> --run-id=<id>``."""
    return ["run", f"--target={entry.target}", f"--run-id={entry.run_id}"]


def test_run_batch_runs_one_child_per_target_in_turn(world: World, tmp_path: Path) -> None:
    """Sequential children with python -m otterdog_e2e, the parent's environment (no env-file value), prefixed lines,
    one log per target and an exit line."""
    plan = batch.plan_batch(["acme", "beta"], world.settings, environ=world.environ)
    runner, echoed = FakeRunner(codes={"beta": 1}), []
    results = batch.run_batch(
        plan, child_args, echo=echoed.append, environ=world.environ, log_dir=tmp_path / "logs", runner=runner
    )
    assert [call["instance"] for call in runner.calls] == ["acme", "beta"]
    first = runner.calls[0]
    assert first["argv"] == [sys.executable, "-P", "-m", "otterdog_e2e", *child_args(plan.entries[0])]
    assert first["env"] == {**world.environ, "PYTHONUNBUFFERED": "1"}  # E2E_ORG, E2E_PROFILE, tokens: never
    assert first["log_path"] == tmp_path / "logs" / f"batch-{plan.batch_id}-acme.log"
    assert stat.S_IMODE((tmp_path / "logs").stat().st_mode) == 0o700
    assert echoed[:2] == ["[acme] running acme", "[acme] token None"]
    assert echoed[2].startswith("[acme] exit code 0 after ") and echoed[2].endswith(f"(run {plan.entries[0].run_id})")
    assert [(result.exit_code, result.status) for result in results] == [(0, "passed"), (1, "failed")]
    assert all(result.started_at is not None and result.duration is not None for result in results)


def test_fail_fast_starts_no_further_target(world: World) -> None:
    """With fail_fast, the targets after a failure are not started (exit code None)."""
    plan = batch.plan_batch(["acme", "beta", "free"], world.settings, environ=world.environ, fail_fast=True)
    runner, echoed = FakeRunner(codes={"acme": 4}), []
    results = batch.run_batch(plan, child_args, echo=echoed.append, environ=world.environ, runner=runner)
    assert [call["instance"] for call in runner.calls] == ["acme"]
    assert [result.status for result in results] == ["failed", "not started", "not started"]
    assert "[beta] not started (--fail-fast: an earlier target failed)" in echoed
    assert batch.batch_exit_code(result.exit_code for result in results) == 4


def test_parallel_children_run_at_the_same_time(world: World) -> None:
    """parallel 2: both children are running at once (a barrier both must reach)."""
    plan = batch.plan_batch(["acme", "beta"], world.settings, environ=world.environ, parallel=2, free_port=ports(1, 2))
    barrier = threading.Barrier(2, timeout=10)
    runner = FakeRunner(during=lambda instance: barrier.wait())
    results = batch.run_batch(plan, child_args, echo=lambda line: None, environ=world.environ, runner=runner)
    assert [result.exit_code for result in results] == [0, 0]
    assert sorted(call["env"]["E2E_WEBAPP_PORT"] for call in runner.calls) == ["1", "2"]


def test_a_child_that_cannot_start_is_an_internal_error(world: World) -> None:
    """OSError when starting the child (missing interpreter, fd limit): exit code 3, the batch goes on."""
    plan = batch.plan_batch(["acme", "beta"], world.settings, environ=world.environ)
    echoed: list[str] = []

    def runner(argv: Sequence[str], **kwargs: Any) -> int:
        """Fail for acme only."""
        if "--target=acme" in argv:
            raise FileNotFoundError("no such interpreter")
        return 0

    results = batch.run_batch(plan, child_args, echo=echoed.append, environ=world.environ, runner=runner)
    assert [result.exit_code for result in results] == [3, 0]
    assert "[acme] cannot start the child process: FileNotFoundError: no such interpreter" in echoed


def test_a_forwarded_signal_starts_no_further_target(world: World) -> None:
    """SIGTERM while a child runs is forwarded (procs.forward_signals), not raised; the next targets do not start and
    the batch exits 2 (interrupted) even though the running child passed."""

    def interrupt(instance: str) -> None:
        """Signal this process while the first child "runs"."""
        with procs.forward_signals() as forwarded:
            os.kill(os.getpid(), signal.SIGTERM)
            assert forwarded.wait(5)

    plan = batch.plan_batch(["acme", "beta"], world.settings, environ=world.environ)
    echoed: list[str] = []
    results = batch.run_batch(
        plan, child_args, echo=echoed.append, environ=world.environ, runner=FakeRunner(during=interrupt)
    )
    assert [result.status for result in results] == ["passed", "not started"]
    assert "[beta] not started (interrupted)" in echoed
    assert batch.batch_exit_code(result.exit_code for result in results) == 2


def test_a_signal_during_a_parallel_batch_reaches_the_main_thread(world: World) -> None:
    """parallel: the main thread (waiting for the workers) forwards the signal; queued targets do not start."""

    both_running = threading.Barrier(2, timeout=10)

    def interrupt(instance: str) -> None:
        """Once both children run, acme signals this process; both wait until the signal was forwarded."""
        with procs.forward_signals() as forwarded:  # a worker thread: the main thread's handler is in place
            both_running.wait()
            if instance == "acme":
                os.kill(os.getpid(), signal.SIGTERM)
            assert forwarded.wait(5)

    plan = batch.plan_batch(
        ["acme", "beta", "free"], world.settings, environ=world.environ, parallel=2, free_port=ports(1, 2, 3)
    )
    echoed: list[str] = []
    runner = FakeRunner(during=interrupt)
    results = batch.run_batch(plan, child_args, echo=echoed.append, environ=world.environ, runner=runner)
    assert [result.status for result in results] == ["passed", "passed", "not started"]
    assert sorted(call["instance"] for call in runner.calls) == ["acme", "beta"]
    assert "[free] not started (interrupted)" in echoed


CHILD = """
    import os
    print("org", os.environ.get("E2E_ORG"), "profile", os.environ.get("E2E_PROFILE"), flush=True)
    print("keep", os.environ.get("E2E_KEEP_ME"), "port", os.environ.get("E2E_WEBAPP_PORT"), flush=True)
"""


def test_real_children_never_see_the_env_files_of_the_parent(world: World, tmp_path: Path) -> None:
    """End to end with procs.run_harness: the children of a parallel batch see the parent's variables and their port,
    never a value of the instances' env files (each child loads its own)."""
    plan = batch.plan_batch(["acme", "beta"], world.settings, environ=world.environ, parallel=2)

    def runner(argv: Sequence[str], **kwargs: Any) -> int:
        """Run a tiny python child instead of the harness."""
        return procs.run_harness([sys.executable, "-c", textwrap.dedent(CHILD)], **kwargs)

    environ = {**os.environ, **world.environ}
    environ.pop("E2E_ORG", None), environ.pop("E2E_PROFILE", None), environ.pop("E2E_WEBAPP_PORT", None)
    echoed: list[str] = []
    batch.run_batch(plan, child_args, echo=echoed.append, environ=environ, runner=runner, log_dir=tmp_path)
    for entry in plan.entries:
        assert f"[{entry.instance}] org None profile None" in echoed
        assert f"[{entry.instance}] keep parent port {entry.webapp_port}" in echoed
        log = (tmp_path / batch.log_name(plan, entry)).read_text(encoding="utf-8")
        assert log.startswith("org None profile None\n")


def test_python_m_otterdog_e2e_is_the_command_line() -> None:
    """__main__: ``python -m otterdog_e2e`` (the batch child command) runs the click application."""
    lines: list[str] = []
    assert procs.run_harness(batch.harness_argv(["--help"]), env=os.environ, on_line=lines.append) == 0
    text = "\n".join(lines)
    assert "Usage: otterdog-e2e" in text and "targets" in text and "doctor" in text


def test_children_never_import_a_package_of_the_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A batch started from a directory holding an ``otterdog_e2e`` package (src/ of a PR checkout) still runs this
    harness installation: -P keeps the working directory off sys.path of the child, which holds every credential."""
    shadow = tmp_path / "otterdog_e2e"
    shadow.mkdir()
    (shadow / "__init__.py").write_text("print('shadow package imported', flush=True)\nraise SystemExit(42)\n")
    (shadow / "__main__.py").write_text("raise SystemExit(43)\n")
    monkeypatch.chdir(tmp_path)
    argv = batch.harness_argv(["--help"])
    assert argv[:4] == [sys.executable, "-P", "-m", "otterdog_e2e"]
    lines: list[str] = []
    assert procs.run_harness(argv, env=os.environ, on_line=lines.append) == 0
    assert "shadow package imported" not in lines and "Usage: otterdog-e2e" in "\n".join(lines)


@pytest.mark.parametrize(
    ("codes", "expected"),
    [
        ([0, 0, 0], 0),
        ([0, 1, 5], 1),
        ([5, 0], 5),
        ([1, 4], 4),
        ([4, 2, 1], 2),
        ([2, 3, 4], 3),
        ([0, -15], 2),  # killed by a signal: interrupted
        ([1, 99], 3),  # unknown code: internal error
        ([1, None], 1),  # --fail-fast keeps the failure's code
        ([0, None], 2),  # interrupted before the next target
        ([], 0),
    ],
)
def test_batch_exit_code(codes: list[int | None], expected: int) -> None:
    """0 only when every target passed, else the most severe code: 3 > 2 > 4 > 1 > 5."""
    assert batch.EXIT_SEVERITY == (3, 2, 4, 1, 5)
    assert batch.batch_exit_code(codes) == expected


# --- summary -------------------------------------------------------------------------------------------------------------
@pytest.fixture
def finished(world: World, tmp_path: Path) -> tuple[BatchPlan, list[BatchResult], Path]:
    """A finished batch of acme (run.json + results), beta (failed, no artifacts) and free (not started)."""
    plan = batch.plan_batch(["acme", "beta", "free"], world.settings, environ=world.environ)
    root = tmp_path / "artifacts"
    run_dir = root / plan.entries[0].run_id
    run_dir.mkdir(parents=True)
    run = {
        "run_id": plan.entries[0].run_id,
        "command": f"otterdog-e2e run --suite cli --target acme --sut {TOKEN}",
        "target": {"name": "acme", "profile": "free", "org": "acme-e2e", "plan": "free"},
    }
    (run_dir / "run.json").write_text(json.dumps(run), encoding="utf-8")
    lines = [
        {"nodeid": "tests/cli/test_a.py::test_x", "outcome": "passed"},
        {"nodeid": "tests/cli/test_a.py::test_y", "outcome": "passed"},
        {"nodeid": "tests/cli/test_a.py::test_z", "outcome": "skipped", "reason": "no app"},
    ]
    (run_dir / "results.jsonl").write_text("".join(json.dumps(line) + "\n" for line in lines), encoding="utf-8")
    started = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
    results = [
        BatchResult(plan.entries[0], 0, started, 185.0),
        BatchResult(plan.entries[1], 1, started, 12.34),
        BatchResult(plan.entries[2]),
    ]
    return plan, results, root


def test_write_batch_summary(finished: tuple[BatchPlan, list[BatchResult], Path], tmp_path: Path, world: World) -> None:
    """batch-<id>.md and .json below the artifacts root (0600, redacted), appended to GITHUB_STEP_SUMMARY: one row
    per target with its profile, org, run id, exit code, duration, results and reproduce command."""
    plan, results, root = finished
    world.redactor.add(TOKEN)
    step_summary = tmp_path / "step-summary.md"
    step_summary.write_text("# previous\n", encoding="utf-8")
    markdown, data = batch.write_batch_summary(
        plan,
        results,
        root,
        environ={"GITHUB_STEP_SUMMARY": str(step_summary)},
        reproduce=lambda entry: f"otterdog-e2e run --target {entry.target}",
        command="otterdog-e2e run --target acme,beta,free",
    )
    assert (markdown, data) == (root / f"batch-{plan.batch_id}.md", root / f"batch-{plan.batch_id}.json")
    assert {stat.S_IMODE(path.stat().st_mode) for path in (markdown, data)} == {0o600}
    text = markdown.read_text(encoding="utf-8")
    acme, beta, free = plan.entries
    assert f"# otterdog-e2e batch `{plan.batch_id}`" in text
    assert "**FAILED** (exit code 1): 2 of 3 target(s) did not pass (sequential)." in text
    assert (
        f"| `acme` | `free` | `acme-e2e` | `{acme.run_id}` | 0 | 3m 05s | 2 passed, 1 skipped |"
        " `otterdog-e2e run --suite cli --target acme --sut ***` |"
    ) in text
    assert f"| `beta` | `team` | `beta-e2e` | `{beta.run_id}` | 1 | 12.3 s | no results |" in text
    assert f"| `free` | `free` | `free-e2e` | `{free.run_id}` | not started | - | no results |" in text
    assert TOKEN not in text and step_summary.read_text(encoding="utf-8") == "# previous\n" + text + "\n"
    document = json.loads(data.read_text(encoding="utf-8"))
    assert (document["batch_id"], document["exit_code"], document["mode"]) == (plan.batch_id, 1, "sequential")
    assert document["command"] == "otterdog-e2e run --target acme,beta,free"
    rows = {row["instance"]: row for row in document["targets"]}
    assert rows["acme"]["tallies"] == {"passed": 2, "skipped": 1} and rows["acme"]["tests"] == 3
    assert rows["beta"]["command"] == "otterdog-e2e run --target beta" and rows["beta"]["status"] == "failed"
    assert (rows["free"]["exit_code"], rows["free"]["status"], rows["free"]["duration_seconds"]) == (
        None,
        "not started",
        None,
    )
    assert rows["acme"]["artifacts"] == str(root / acme.run_id) and rows["acme"]["log"] == batch.log_name(plan, acme)


def test_a_passing_batch_summary(finished: tuple[BatchPlan, list[BatchResult], Path]) -> None:
    """Every target passed: PASSED verdict, exit code 0, no step summary without GITHUB_STEP_SUMMARY."""
    plan, results, root = finished
    passing = [BatchResult(result.entry, 0, result.started_at, 1.0) for result in results]
    markdown, data = batch.write_batch_summary(plan, passing, root, environ={})
    assert "**PASSED**: 3 target(s) passed (sequential)." in markdown.read_text(encoding="utf-8")
    assert json.loads(data.read_text(encoding="utf-8"))["exit_code"] == 0


def test_result_lines(finished: tuple[BatchPlan, list[BatchResult], Path]) -> None:
    """One console line per target: status, exit code, duration, run id (none when the children get no run id)."""
    plan, results, _root = finished
    lines = batch.result_lines(results)
    assert lines[0].split() == ["acme", "passed", "exit", "0", "3m", "05s", "run", plan.entries[0].run_id]
    assert lines[2].split() == ["free", "not", "started", "exit", "-", "-", "run", plan.entries[2].run_id]
    lines = batch.result_lines(results, run_ids=False)
    assert lines[0].split() == ["acme", "passed", "exit", "0", "3m", "05s"]


def test_a_batch_without_run_ids_never_shows_one(world: World) -> None:
    """run_ids=False (janitor children get no --run-id): the exit lines carry no run id that never existed."""
    plan = batch.plan_batch(["acme", "beta"], world.settings, environ=world.environ, run_ids=False)
    assert plan.run_ids is False
    echoed: list[str] = []
    batch.run_batch(plan, child_args, echo=echoed.append, environ=world.environ, runner=FakeRunner())
    exits = [line for line in echoed if " exit code " in line]
    assert len(exits) == 2 and not any(
        "run " in line or entry.run_id in line for line in exits for entry in plan.entries
    )


# --- otterdog-e2e targets ------------------------------------------------------------------------------------------------
def test_list_instances(world: World) -> None:
    """Env-file instances and the profiles of targets/ with profile, org and env file; unusable ones say why."""
    world.instance("gamma", None, 44)
    infos = {info.name: info for info in batch.list_instances(world.settings, world.environ)}
    assert sorted(infos) == ["acme", "beta", "free", "gamma", "team"]
    assert (infos["acme"].profile, infos["acme"].org, infos["acme"].env_file) == (
        "free",
        "acme-e2e",
        str(world.config / "acme.env"),
    )
    assert infos["acme"].problem is None and infos["beta"].profile == "team"
    assert infos["gamma"].profile is None and infos["gamma"].org == "gamma-e2e"
    assert "E2E_PROFILE" in str(infos["gamma"].problem)
    assert infos["team"].profile == "team" and infos["team"].env_file is None
    assert infos["team"].problem == "not configured (otterdog-e2e setup --target team)"  # a profile, no env file
    assert world.environ == {"HOME": world.environ["HOME"], "E2E_KEEP_ME": "parent"}


def test_list_instances_without_anything(tmp_path: Path) -> None:
    """No env file, no targets dir: nothing."""
    assert batch.list_instances(make_settings(tmp_path / "project"), {"HOME": str(tmp_path)}) == []
