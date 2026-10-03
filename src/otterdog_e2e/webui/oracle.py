"""Independent oracles of the web-only org settings (docs/web-ui-testing.md).

* REST: ``GET /orgs/{org}`` with the owner token returns 7 of the 12 settings (mapping.REST_FIELDS); it never goes
  through otterdog, but GitHub only exposes them read-only (``PATCH /orgs/{org}`` accepts none of them).
* trusted reader: a TRUSTED otterdog (the reset SUT, never the SUT under test) reads all of them through its own web
  client: ``show-live`` without ``-n`` prints the live model, whose ``settings {`` block holds every setting otterdog
  could read (a setting it could not read is UNSET and not printed). An alternative check is a trusted ``plan``
  without ``-n`` that must not change the web keys (plan_problems).

Output format (otterdog ``Operation.print_dict``, identical for ``show`` and ``show-live``):
``  settings {`` / ``    <key padded> = <value>`` with ``true``/``false``/``null``/numbers/``"strings"``, nested
dicts as ``= {`` ... ``}`` and lists as ``= [`` ... ``],`` (or ``[]``), the block closed by ``  }``.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from otterdog_e2e import waiting
from otterdog_e2e.otterdog.output import strip_ansi
from otterdog_e2e.safety import SafetyError
from otterdog_e2e.webui import mapping
from otterdog_e2e.webui.gate import WebFailure, classify_web_failure

if TYPE_CHECKING:
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.otterdog.output import PlanResult
    from otterdog_e2e.otterdog.runner import CliResult

SETTINGS_HEADER_RE = re.compile(r"^(?P<indent>\s*)settings \{$")
KEY_VALUE_RE = re.compile(r"^(?P<indent>\s*)(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s+=\s?(?P<value>.*?)\s*$")
RETRIEVE_FAILED_RE = re.compile(r"failed to retrieve setting '(?P<key>[A-Za-z_]+)' via web ui")
SHOW_LIVE = "show-live"
_NESTED_OPENERS = ("{", "[")


def parse_value(text: str) -> Any:
    """A printed value: JSON literals (true, false, null, numbers, "strings", [], {}), else the raw text."""
    value = text.strip().removesuffix(",")
    try:
        return json.loads(value)
    except ValueError:
        if len(value) >= 2 and value.startswith('"') and value.endswith('"'):
            return value[1:-1]
        return value


def parse_settings_block(text: str) -> dict[str, Any] | None:
    """Top-level values of the first ``settings {`` block of show / show-live output (None when there is none).

    Nested values (``workflows = {`` ..., non-empty lists) are skipped: the web settings are scalars.
    """
    lines = strip_ansi(text).splitlines()
    start = next((index for index, line in enumerate(lines) if SETTINGS_HEADER_RE.match(line.rstrip())), None)
    if start is None:
        return None
    header = SETTINGS_HEADER_RE.match(lines[start].rstrip())
    assert header is not None
    indent = len(header.group("indent"))
    values: dict[str, Any] = {}
    key_indent: int | None = None
    nested_indent: int | None = None
    for line in lines[start + 1 :]:
        content = line.strip()
        if not content:
            continue
        lead = len(line) - len(line.lstrip())
        if nested_indent is not None:
            if lead == nested_indent and content.rstrip(",") in ("}", "]"):
                nested_indent = None
            continue
        if lead <= indent and content == "}":
            break
        match = KEY_VALUE_RE.match(line.rstrip())
        if match is None:
            continue
        key_indent = len(match.group("indent")) if key_indent is None else key_indent
        if len(match.group("indent")) != key_indent:
            continue
        raw = match.group("value")
        if raw in _NESTED_OPENERS:
            nested_indent = key_indent
            continue
        values[match.group("key")] = parse_value(raw)
    return values


def web_values(settings: Mapping[str, Any]) -> dict[str, Any]:
    """The web settings (mapping.WEB_KEYS) of a parsed settings block."""
    return {key: settings[key] for key in mapping.WEB_KEYS if key in settings}


def retrieve_failures(text: str) -> list[str]:
    """Keys otterdog's web client reported as ``failed to retrieve setting '<key>' via web ui`` (in order)."""
    return list(dict.fromkeys(match.group("key") for match in RETRIEVE_FAILED_RE.finditer(strip_ansi(text))))


def settings_changes(plan: PlanResult) -> list[str]:
    """Keys a plan changes in the org ``settings`` object (read-only notes excluded)."""
    keys: list[str] = []
    for obj in plan.objects:
        if obj.kind != "settings" or obj.op not in ("change", "forced"):
            continue
        read_only = set(obj.read_only_keys)
        keys += [key for key in obj.changed_keys if key not in read_only and key not in keys]
    return keys


def rest_web_values(oracle: Oracle) -> dict[str, Any]:
    """The REST-readable web settings of the org (``GET /orgs/{org}``, owner token)."""
    return mapping.rest_values(oracle.org() or {})


def wait_rest_values(
    read: Callable[[], Mapping[str, Any]],
    expected: Mapping[str, Any],
    *,
    timeout: float = 120.0,
    interval: float = 5.0,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> tuple[dict[str, Any], list[str]]:
    """Poll the REST values until the REST-readable keys of ``expected`` match (GitHub caches org reads briefly);
    returns the last values and the remaining differences (empty when they match)."""
    keys = [key for key in expected if key in mapping.REST_FIELDS]
    if not keys:
        return dict(read()), []
    last = waiting.poll(
        lambda: dict(read()),
        until=lambda values: not mapping.differences(expected, values, keys),
        timeout=timeout,
        interval=interval,
        what="REST web settings",
        raise_on_timeout=False,
        sleep=sleep,
        clock=clock,
    )
    return last, mapping.differences(expected, last, keys)


@dataclass
class WebRead:
    """One read of the web settings through the trusted otterdog."""

    values: dict[str, Any]
    missing: list[str]
    failed: list[str]
    result: CliResult
    failure: WebFailure | None = None
    settings_found: bool = True
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """The command succeeded, printed a settings block and hit no recognized web-client failure."""
        return self.result.exit_code == 0 and not self.result.timed_out and self.settings_found and not self.failure

    def problem(self) -> str | None:
        """Why the read cannot be used (None when ok)."""
        if self.ok:
            return None
        reason = f"exit code {self.result.exit_code}" + (", timed out" if self.result.timed_out else "")
        if self.failure is not None:
            reason += f", {self.failure.kind}: {self.failure.hint}"
        if not self.settings_found:
            reason += ", no settings block in the output"
        return f"trusted web read failed ({reason})"


class TrustedWebReader:
    """Reads the web-only settings with the web reader of a TRUSTED otterdog (``show-live`` without -n, or ``import``
    without -n followed by ``show --local`` with ``mode="import"``).

    ``cli`` must be a web-mode CLI (``web`` attribute) of a trusted SUT: the reset SUT, never the SUT under test.
    """

    MODES = (SHOW_LIVE, "import")

    def __init__(self, cli: Any, *, mode: str = SHOW_LIVE) -> None:
        """Bind the trusted web-mode CLI (SafetyError otherwise)."""
        if getattr(cli, "web", None) is None:
            raise SafetyError("the trusted web reader needs a web-mode otterdog CLI (WebOtterdogCli)")
        sut = getattr(getattr(cli, "installed", None), "sut", None)
        if getattr(sut, "trusted", False) is not True:
            raise SafetyError("the trusted web reader must run a trusted otterdog (the reset SUT)")
        if mode not in self.MODES:
            raise ValueError(f"unknown reader mode {mode!r}, expected one of {self.MODES}")
        self.cli = cli
        self.mode = mode
        self.reads: list[WebRead] = []

    def read(self) -> WebRead:
        """One read of the web settings (1 web login) in the reader's mode."""
        return self.read_via_import() if self.mode == "import" else self.read_live()

    def read_via_import(self) -> WebRead:
        """``import -f`` without -n into the reader's workspace (1 web login), then ``show --local`` of the imported
        configuration (offline). An unread setting gets the template default in the imported configuration, so the
        keys otterdog reported as failed and those it never reads (EXPECTED_UNREAD) are dropped."""
        imported: CliResult = self.cli.import_config()
        failed = retrieve_failures(imported.output)
        failure = classify_web_failure(imported.output)
        if imported.exit_code != 0 or imported.timed_out or failure is not None:
            read = WebRead({}, list(mapping.WEB_KEYS), failed, imported, failure, settings_found=False)
        else:
            shown: CliResult = self.cli.show(local=True)
            settings = parse_settings_block(shown.output)
            unreliable = set(failed) | mapping.EXPECTED_UNREAD
            values = {key: value for key, value in web_values(settings or {}).items() if key not in unreliable}
            read = WebRead(
                values=values,
                missing=[key for key in mapping.WEB_KEYS if key not in values],
                failed=failed,
                result=shown,
                failure=classify_web_failure(shown.output),
                settings_found=settings is not None,
                notes=[f"{key}: dropped (template default in the import)" for key in sorted(unreliable)],
            )
        self.reads.append(read)
        return read

    def read_live(self) -> WebRead:
        """``show-live`` (1 web login): the web settings otterdog read, the ones it did not, its failures."""
        result: CliResult = self.cli.run(SHOW_LIVE)
        output = result.output
        settings = parse_settings_block(output)
        values = web_values(settings or {})
        read = WebRead(
            values=values,
            missing=[key for key in mapping.WEB_KEYS if key not in values],
            failed=retrieve_failures(output),
            result=result,
            failure=classify_web_failure(output),
            settings_found=settings is not None,
        )
        self.reads.append(read)
        return read

    def plan_problems(self, config_text: str, keys: Iterable[str] = mapping.WEB_KEYS) -> list[str]:
        """Trusted ``plan`` without -n of ``config_text`` (1 web login): problems for each changed key of ``keys``
        (empty: the trusted reader sees the live org as configured)."""
        self.cli.workspace.write_org_config(config_text)
        result: CliResult = self.cli.plan()
        failure = classify_web_failure(result.output)
        plan = result.plan()
        if result.exit_code != 0 or result.timed_out or plan.aborted or plan.add is None or failure is not None:
            detail = f", {failure.kind}: {failure.hint}" if failure is not None else ""
            return [f"trusted plan failed (exit code {result.exit_code}{detail})"]
        wanted = set(keys)
        return [f"{key}: the trusted plan still changes it" for key in settings_changes(plan) if key in wanted]
