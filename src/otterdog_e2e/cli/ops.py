"""``otterdog-e2e relay`` and ``otterdog-e2e janitor`` (SPEC 16): operations on a live test org, under its lease.

relay forwards the App's webhook deliveries to a local webapp until Ctrl-C (poll errors are logged and retried);
janitor lists, and with --apply deletes, the leftovers of finished or crashed runs (ledger runs without an active
lease, older than --older-than or exactly --run-id), several targets in turn through child processes (run_targets).
"""

from __future__ import annotations

import logging
import sys
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import click

from otterdog_e2e.cli.common import (
    RUN_ID_ARG_RE,
    TARGETS_HELP,
    _echo,
    _handled,
    _session,
    _settings,
    main,
    target_names,
)
from otterdog_e2e.cli.run import run_targets
from otterdog_e2e.context import E2EContext, describe_error, parse_duration

if TYPE_CHECKING:
    from otterdog_e2e.github.janitor import JanitorItem
    from otterdog_e2e.webhooks.relay import DeliveryRelay, RelayedDelivery

logger = logging.getLogger(__name__)


# --- relay ----------------------------------------------------------------------------------------------------------
def build_relay(context: E2EContext, *, forward_to: str, since: datetime, allow_remote: bool) -> DeliveryRelay:
    """DeliveryRelay of the target's App installation (preflight checked) to ``forward_to``."""
    from otterdog_e2e.webhooks.relay import DeliveryRelay

    return DeliveryRelay(
        context.app_auth(),
        forward_url=forward_to,
        secret=context.require_app_credentials().webhook_secret,
        since=since,
        installation_id=context.installation_id(),
        org=context.require_target().org,
        artifacts_dir=context.artifacts_dir,
        allow_remote=allow_remote,
    )


def delivery_line(delivery: RelayedDelivery) -> str:
    """One line per relayed delivery."""
    event = delivery.event + (f"/{delivery.action}" if delivery.action else "")
    pull = f" #{delivery.pull_number}" if delivery.pull_number else ""
    outcome = delivery.error or f"-> {delivery.relay_status}"
    return f"{delivery.delivered_at:%H:%M:%S} {event}{pull} {outcome}"


def relay_loop(
    relay: DeliveryRelay, *, sleep: Callable[[float], None] = time.sleep, max_polls: int | None = None
) -> None:
    """Poll and print until Ctrl-C (or ``max_polls``); poll errors are logged and retried; the relay is stopped."""
    polls = 0
    try:
        while max_polls is None or polls < max_polls:
            polls += 1
            try:
                for delivery in relay.poll_once():
                    _echo(delivery_line(delivery))
            except Exception as exc:  # noqa: BLE001 - a long-running relay survives transient poll failures
                logger.warning("relay poll failed: %s", describe_error(exc))
            sleep(relay.poll_interval)
    except KeyboardInterrupt:
        _echo("relay stopped", err=True)
    finally:
        relay.stop()


@main.command()
@click.option("--target", "target", required=True, help="target name or path")
@click.option("--forward-to", "forward_to", required=True, help="webhook receiver URL (loopback)")
@click.option("--since", default="10m", show_default=True, help="forward deliveries newer than this")
@click.option("--allow-remote", is_flag=True, help="allow a non-loopback --forward-to")
@_handled
def relay(target: str, forward_to: str, since: str, allow_remote: bool) -> None:
    """Forward the App's webhook deliveries to a local webapp (holds the org lease)."""
    window = parse_duration(since)
    with _session(target, allow_remote_webapp=allow_remote) as context:
        context.load_target()
        context.verify()
        context.acquire_lease()
        delivery_relay = build_relay(
            context, forward_to=forward_to, since=datetime.now(UTC) - window, allow_remote=allow_remote
        )
        _echo(f"relaying deliveries of {context.require_target().org} to {forward_to} (Ctrl-C to stop)", err=True)
        relay_loop(delivery_relay)


# --- janitor --------------------------------------------------------------------------------------------------------
def janitor_filter(
    context: E2EContext, *, older_than: timedelta, run_id: str | None, now: datetime | None = None
) -> Callable[[str], bool]:
    """purgeable for the janitor: ledger runs without active lease, exactly ``run_id`` or older than the cutoff."""
    from otterdog_e2e.naming import run_id_timestamp

    cutoff = (now or datetime.now(UTC)) - older_than

    def purgeable(candidate: str) -> bool:
        """True for the runs this janitor invocation may sweep."""
        if candidate == context.run_ctx.run_id:
            return False
        if run_id is not None:
            return candidate == run_id and context.purgeable(candidate)
        created = run_id_timestamp(candidate)
        return created is not None and created <= cutoff and context.purgeable(candidate)

    return purgeable


def render_items(items: Iterable[JanitorItem]) -> str:
    """Table of janitor items."""
    rows = [(item.kind, item.name, item.run_id or "-", item.scope, item.detail) for item in items]
    if not rows:
        return "nothing to sweep"
    widths = [max(len(str(row[index])) for row in rows) for index in range(4)]
    return "\n".join(
        "  ".join(str(value).ljust(width) for value, width in zip(row[:4], widths, strict=True))
        + f"  {row[4]}".rstrip()
        for row in rows
    )


@main.command()
@click.option("--target", "targets", multiple=True, required=True, help=TARGETS_HELP)
@click.option("--older-than", default="6h", show_default=True, help="minimum age of swept runs")
@click.option("--run-id", default=None, help="sweep exactly this run (no age threshold)")
@click.option("--apply", "apply_", is_flag=True, help="delete (default: dry run)")
@click.option(
    "--force-takeover",
    is_flag=True,
    help="with --run-id: take over that run's lease even if it was renewed recently (the run is known to be dead)",
)
@_handled
def janitor(targets: tuple[str, ...], older_than: str, run_id: str | None, apply_: bool, force_takeover: bool) -> None:
    """List (and with --apply delete) leftovers of finished or crashed runs.

    With --run-id and --apply, a lease still held by that run is taken over (compare-and-swap) only when the run looks
    dead: no renewal for 20 minutes, or the holder is this CI job; --force-takeover skips that check. Several targets:
    one child janitor process per target, in turn (--run-id and --force-takeover name one run of one target).
    """
    age = parse_duration(older_than)
    if run_id is not None and not RUN_ID_ARG_RE.match(run_id):
        raise click.UsageError(f"--run-id {run_id!r} is not a run id")
    if force_takeover and run_id is None:
        raise click.UsageError("--force-takeover needs --run-id")
    names = target_names(targets, required=True)
    if len(names) > 1:
        if run_id is not None:
            raise click.UsageError("--run-id and --force-takeover name one run of one target: give one target")
        settings = _settings()
        sys.exit(
            run_targets(
                names,
                lambda entry: [
                    "janitor",
                    f"--target={entry.target}",
                    f"--older-than={older_than}",
                    *(["--apply"] if apply_ else []),
                ],
                settings=settings,
                artifacts_root=settings.artifacts_root,
                summary=False,
                run_ids=False,  # a janitor child gets no --run-id: it sweeps under a run id of its own
            )
        )
    with _session(names[0]) as context:
        context.load_target()
        context.verify()
        if apply_:
            context.acquire_lease(takeover_run=run_id, force_takeover=force_takeover)
        sweeper = context.janitor(janitor_filter(context, older_than=age, run_id=run_id))
        items = sweeper.scan()
        _echo(render_items(items))
        if not apply_:
            if items:
                _echo("dry run: re-run with --apply to delete", err=True)
            return
        deleted = sweeper.sweep(items)
        _echo(f"deleted {len(deleted)} of {len(items)} item(s)", err=True)
