"""H-ORG-HOOK-UPDATE / H-ORG-HOOK-SECRET / H-ORG-HOOK-ALIAS: otterdog-managed organization webhooks (org_level).

H-ORG-HOOK (test_org_hook.py) creates, pings and removes one organization hook. These tests cover the rest of the
model (otterdog/models/webhook.py, organization_webhook.py): every setting of the hook changed and changed back, the
secret (a plain value is sent once and never compared, the dummy '********' skips the hook, ``--update-webhooks``
forces it, a removal is planned with a warning and GitHub stops signing the deliveries), and a URL change through
``aliases`` (KB-004: never applied). Hook URLs lie under the never-resolving HOOK_BASE (GitHub records the failed
deliveries, nothing is reached). Every apply goes through the SUT CLI on the session workspace with ``-r e2e-<run>-*``
(organization webhooks are org-level objects, always diffed); removals use the guarded ``apply -d``; the teardown is
a full baseline reset (org_level_reset). Waits use the tier's classified helpers: a delivery GitHub does not log in
time is ``(infra)``, a state otterdog does not reach is ``(SUT)``.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

from otterdog_e2e.github.oracle import deliveries_since
from otterdog_e2e.otterdog.output import normalize_text
from otterdog_e2e.otterdog.render import ConfigFragments
from otterdog_e2e.otterdog.runner import DiffOptions
from otterdog_e2e.waiting import CONVERGE_BACKOFF

if TYPE_CHECKING:
    from conftest import WebhookHelpers
    from otterdog_e2e.github.mutate import Mutator
    from otterdog_e2e.github.oracle import Oracle
    from otterdog_e2e.naming import RunContext
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import PlanObject, PlanResult
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import CliResult, OtterdogCli

pytestmark = [pytest.mark.org_level]

DUMMY_SECRET = "********"  # what GitHub returns for a configured secret, and otterdog's "skip me" value
SIGNATURE_HEADER = "X-Hub-Signature-256"
TAIL = 3000


class UrlAliasNotAppliedError(AssertionError):
    """An org webhook URL change through ``aliases`` was not planned or not applied (H-ORG-HOOK-ALIAS, KB-004)."""


def hook(url: str, **fields: Any) -> str:
    """``orgs.newOrgWebhook('<url>') { <fields> }`` with json-encoded values (``secret=None`` writes ``null``)."""
    body = ", ".join(f"{key}: {json.dumps(value)}" for key, value in fields.items())
    return f"orgs.newOrgWebhook({json.dumps(url)}) {{ {body} }}"


def write(cli: OtterdogCli, renderer: OrgConfigRenderer, *hooks: str) -> None:
    """The baseline plus the given organization webhooks as the session workspace's configuration."""
    cli.workspace.write_org_config(renderer.render(ConfigFragments(webhooks=list(hooks))))


def plan(cli: OtterdogCli, run_ctx: RunContext, what: str, **flags: Any) -> tuple[CliResult, PlanResult]:
    """``plan -n -r e2e-<run>-* [flags]`` that must complete (exit 0, a ``Plan:`` summary)."""
    result = cli.plan_with(DiffOptions(repo_filter=run_ctx.repo_filter(), **flags))
    result.assert_ok(what)
    parsed = result.plan()
    assert parsed.add is not None and not parsed.aborted, f"{what}: no plan summary\n{result.output[-TAIL:]}"
    return result, parsed


def hook_objects(parsed: PlanResult, url: str) -> list[PlanObject]:
    """The org_webhook objects of a plan whose key is ``url``."""
    return [obj for obj in parsed.objects if obj.kind == "org_webhook" and obj.value == url]


def apply(cli: OtterdogCli, run_ctx: RunContext, helpers: type[WebhookHelpers], what: str, **flags: Any) -> CliResult:
    """``apply -f -n -r e2e-<run>-* [flags]`` that went through (WebhookHelpers.assert_applied)."""
    result = cli.apply_with(DiffOptions(repo_filter=run_ctx.repo_filter(), **flags))
    helpers.assert_applied(result, what)
    return result


def converge(cli: OtterdogCli, run_ctx: RunContext, helpers: type[WebhookHelpers], what: str) -> None:
    """Plan until this run's objects are a no-op (the converge backoff of the scenario engine)."""
    helpers.reaction(
        lambda: cli.plan(repo_filter=run_ctx.repo_filter()).plan(),
        until=lambda parsed: parsed.is_noop(run_ctx.needles()),
        what=f"plan converged after {what}",
        timeout=helpers.CONVERGE_TIMEOUT,
        interval=CONVERGE_BACKOFF,
    )


def live_hook(
    oracle: Oracle, helpers: type[WebhookHelpers], url: str, what: str, until: Any = lambda hook: hook is not None
) -> dict[str, Any]:
    """The org hook with config.url ``url`` once ``until`` holds for it (state after an otterdog apply: SUT)."""
    return helpers.reaction(lambda: oracle.org_hook_by_url(url), until=until, what=what, timeout=helpers.STATE_TIMEOUT)


def remove_run_hooks(cli: OtterdogCli, baseline: BaselineManager, run_ctx: RunContext, *urls: str) -> None:
    """The baseline configuration applied with the guarded ``apply -d`` (only this run's objects are removed)."""
    cli.workspace.write_org_config(baseline.text())
    removed = baseline.guarded_apply(cli, repo_filter=run_ctx.repo_filter(), delete=True)
    assert not removed.aborted_validation and not removed.failed_patches, f"removal failed:\n{removed.raw[-TAIL:]}"
    for url in urls:
        assert f'- remove org_webhook[url="{url}"]' in normalize_text(removed.raw), f"{url} was not removed"


def ping_delivery(
    oracle: Oracle, mutator: Mutator, helpers: type[WebhookHelpers], hook_id: int, what: str
) -> dict[str, Any]:
    """Ping the hook and return the new 'ping' delivery in full (request headers): GitHub logs it within minutes.
    Only deliveries delivered after GitHub's time of the ping count (deliveries_since): a creation ping or an earlier
    ping logged late is never taken for this one (BAT-10)."""
    known = {delivery.get("id") for delivery in oracle.org_hook_deliveries(hook_id)}
    pinged_at = mutator.ping_org_hook(hook_id)
    pings = helpers.reaction(
        lambda: [
            d
            for d in deliveries_since(oracle.org_hook_deliveries(hook_id), pinged_at, event="ping")
            if d.get("id") not in known
        ],
        until=bool,
        what=f"{what}: ping delivery of org hook {hook_id} in GitHub's delivery log",
        timeout=helpers.HOOK_DELIVERY_TIMEOUT,
        infra=True,
    )
    delivery = helpers.reaction(
        lambda: oracle.org_hook_delivery(hook_id, int(pings[0]["id"])) or {},
        until=lambda found: isinstance(found.get("request"), dict),
        what=f"{what}: request of delivery {pings[0]['id']}",
        timeout=helpers.STATE_TIMEOUT,
        infra=True,
    )
    return dict(delivery)


def request_headers(delivery: dict[str, Any]) -> dict[str, Any]:
    """The request headers of a delivery (header names compared case-insensitively)."""
    headers = (delivery.get("request") or {}).get("headers") or {}
    return {str(name).lower(): value for name, value in headers.items()}


@pytest.mark.scenario("H-ORG-HOOK-UPDATE", priority="P1")
@pytest.mark.tags("webhooks")
@pytest.mark.usefixtures("org_level_reset")
def test_org_webhook_settings_are_updated(
    otterdog: OtterdogCli,
    renderer: OrgConfigRenderer,
    baseline: BaselineManager,
    oracle: Oracle,
    run_ctx: RunContext,
    webhook_helpers: type[WebhookHelpers],
) -> None:
    """events, content_type, active and insecure_ssl are changed in one '~ org_webhook' change, then changed back;
    after each apply the oracle reads them (events, active, config) and the plan converges."""
    helpers = webhook_helpers
    url = run_ctx.hook_url("h-org-update")
    initial = {"active": True, "content_type": "json", "insecure_ssl": "0", "events": ["push"]}
    changed = {"active": False, "content_type": "form", "insecure_ssl": "1", "events": ["push", "repository"]}

    write(otterdog, renderer, hook(url, **initial))
    _, parsed = plan(otterdog, run_ctx, "plan (org webhook added)")
    assert [obj.op for obj in hook_objects(parsed, url)] == ["add"], parsed.raw[-TAIL:]
    apply(otterdog, run_ctx, helpers, "apply (org webhook added)")
    live = live_hook(oracle, helpers, url, f"org hook {url} created")
    assert live.get("active") is True and sorted(live.get("events") or []) == ["push"], live
    assert (live.get("config") or {}).get("content_type") == "json", live.get("config")
    assert str((live.get("config") or {}).get("insecure_ssl")) == "0", live.get("config")
    converge(otterdog, run_ctx, helpers, "the org webhook was added")

    write(otterdog, renderer, hook(url, **changed))
    result, parsed = plan(otterdog, run_ctx, "plan (org webhook settings changed)")
    objects = hook_objects(parsed, url)
    assert [obj.op for obj in objects] == ["change"], result.output[-TAIL:]
    assert set(objects[0].changed_keys) == {"active", "content_type", "events", "insecure_ssl"}, objects[0].body
    text = normalize_text(result.output)
    for line in ("true -> false", '"json" -> "form"', '"0" -> "1"', '+ "repository"'):
        assert line in text, f"the plan does not show {line!r}:\n{text[-TAIL:]}"
    apply(otterdog, run_ctx, helpers, "apply (org webhook settings changed)")
    live = live_hook(
        oracle, helpers, url, f"org hook {url} inactive, form, insecure", until=lambda h: h and h.get("active") is False
    )
    config = live.get("config") or {}
    assert sorted(live.get("events") or []) == ["push", "repository"], live.get("events")
    assert config.get("content_type") == "form" and str(config.get("insecure_ssl")) == "1", config
    converge(otterdog, run_ctx, helpers, "the org webhook settings changed")

    write(otterdog, renderer, hook(url, **initial))
    result, parsed = plan(otterdog, run_ctx, "plan (org webhook settings restored)")
    objects = hook_objects(parsed, url)
    assert [obj.op for obj in objects] == ["change"], result.output[-TAIL:]
    assert set(objects[0].changed_keys) == {"active", "content_type", "events", "insecure_ssl"}, objects[0].body
    apply(otterdog, run_ctx, helpers, "apply (org webhook settings restored)")
    live = live_hook(oracle, helpers, url, f"org hook {url} active again", until=lambda h: h and h.get("active"))
    config = live.get("config") or {}
    assert sorted(live.get("events") or []) == ["push"], live.get("events")
    assert config.get("content_type") == "json" and str(config.get("insecure_ssl")) == "0", config
    converge(otterdog, run_ctx, helpers, "the org webhook settings were restored")

    remove_run_hooks(otterdog, baseline, run_ctx, url)
    live_hook(oracle, helpers, url, f"{url} removed", until=lambda h: h is None)


@pytest.mark.scenario("H-ORG-HOOK-SECRET", priority="P1")
@pytest.mark.tags("webhooks", "secrets")
@pytest.mark.usefixtures("org_level_reset")
@pytest.mark.timeout(1500, func_only=True)  # two delivery-log waits (up to 300 s each) on top of six plans and applies
def test_org_webhook_secret(
    otterdog: OtterdogCli,
    renderer: OrgConfigRenderer,
    baseline: BaselineManager,
    oracle: Oracle,
    mutator: Mutator,
    run_ctx: RunContext,
    webhook_helpers: type[WebhookHelpers],
) -> None:
    """A plain secret is applied once (GitHub signs the deliveries, reports '********'), never compared afterwards,
    forced by --update-webhooks (url filter), removed with a planned warning (deliveries no longer signed); a hook
    whose configured secret is the dummy '********' is skipped (Info, never created)."""
    helpers = webhook_helpers
    secured = run_ctx.hook_url("h-org-secret")
    dummy = run_ctx.hook_url("h-org-secret-dummy")
    value = f"e2e-dummy-{run_ctx.run_id}"
    fields = {"content_type": "json", "events": ["push"]}

    write(otterdog, renderer, hook(secured, secret=value, **fields), hook(dummy, secret=DUMMY_SECRET, **fields))
    validation = otterdog.validate(verbose=True)
    text = normalize_text(validation.output)
    assert validation.validation().ok, text[-TAIL:]
    expected = [
        f"Warning: org_webhook[url=\"{secured}\"] has a secret '{value}' that does not use a credential provider.",
        (
            f"Info: org_webhook[url=\"{dummy}\"] has a secret set, but only a dummy secret '{DUMMY_SECRET}' is "
            "provided in the configuration, will be skipped."
        ),
    ]
    missing = [line for line in expected if line not in text]
    assert not missing, f"validate -v does not report {missing}:\n{text[-TAIL:]}"
    _, parsed = plan(otterdog, run_ctx, "plan (secured org webhook added)")
    assert [obj.op for obj in hook_objects(parsed, secured)] == ["add"], parsed.raw[-TAIL:]
    assert not hook_objects(parsed, dummy), f"the dummy-secret hook is planned:\n{parsed.raw[-TAIL:]}"
    apply(otterdog, run_ctx, helpers, "apply (secured org webhook added)")
    live = live_hook(oracle, helpers, secured, f"org hook {secured} created")
    assert (live.get("config") or {}).get("secret") == DUMMY_SECRET, f"no secret reported: {live.get('config')}"
    assert oracle.org_hook_by_url(dummy) is None, "otterdog created the hook whose secret is the dummy"
    converge(otterdog, run_ctx, helpers, "the secured org webhook was added (values are never compared)")

    signed = ping_delivery(oracle, mutator, helpers, int(live["id"]), "secured hook")
    signature = str(request_headers(signed).get(SIGNATURE_HEADER.lower()) or "")
    assert signature.startswith("sha256="), f"the delivery is not signed: {sorted(request_headers(signed))}"

    result, parsed = plan(otterdog, run_ctx, "plan --update-webhooks", update_webhooks=True, update_filter=secured)
    assert [obj.op for obj in hook_objects(parsed, secured)] == ["forced"], result.output[-TAIL:]
    applied = apply(otterdog, run_ctx, helpers, "apply --update-webhooks", update_webhooks=True, update_filter=secured)
    assert f'! org_webhook[url="{secured}"]' in normalize_text(applied.output), applied.output[-TAIL:]
    converge(otterdog, run_ctx, helpers, "the forced update")

    write(otterdog, renderer, hook(secured, secret=None, **fields))
    result, parsed = plan(otterdog, run_ctx, "plan (org webhook secret removed)")
    objects = hook_objects(parsed, secured)
    assert [obj.op for obj in objects] == ["change"] and objects[0].changed_keys == ["secret"], result.output[-TAIL:]
    warning = f"Warning: removing secret for webhook with url '{secured}'"
    assert warning in normalize_text(result.output), result.output[-TAIL:]
    apply(otterdog, run_ctx, helpers, "apply (org webhook secret removed)")
    live = live_hook(
        oracle,
        helpers,
        secured,
        f"{secured} without secret",
        until=lambda h: h and not (h.get("config") or {}).get("secret"),
    )
    converge(otterdog, run_ctx, helpers, "the org webhook secret was removed")
    unsigned = ping_delivery(oracle, mutator, helpers, int(live["id"]), "hook without secret")
    assert SIGNATURE_HEADER.lower() not in request_headers(unsigned), "deliveries are still signed"

    remove_run_hooks(otterdog, baseline, run_ctx, secured)
    live_hook(oracle, helpers, secured, f"{secured} removed", until=lambda h: h is None)


@pytest.mark.scenario("H-ORG-HOOK-ALIAS", priority="P2")
@pytest.mark.known_bug("KB-004")
@pytest.mark.xfail(
    raises=UrlAliasNotAppliedError,
    strict=False,
    reason="KB-004: a webhook URL change through 'aliases' is never applied (url is excluded from diffs)",
)
@pytest.mark.tags("webhooks")
@pytest.mark.usefixtures("org_level_reset")
def test_org_webhook_url_change_through_aliases(
    otterdog: OtterdogCli,
    renderer: OrgConfigRenderer,
    oracle: Oracle,
    run_ctx: RunContext,
    webhook_helpers: type[WebhookHelpers],
) -> None:
    """docs/userguide/renaming.md: a new url with the old one in ``aliases`` updates the hook in place (no add, no
    remove). otterdog matches the live hook through the alias but never diffs the url (KB-004): the plan shows no
    change and the hook keeps its old url, so this test is an expected failure while the bug exists. Only the KB-004
    assertions raise UrlAliasNotAppliedError (the xfail's ``raises``): the first apply, the hook creation, oracle
    timeouts and the teardown's baseline reset (which removes the hook either way) stay strict (BAT-08)."""
    helpers = webhook_helpers
    before = run_ctx.hook_url("h-org-alias-before")
    after = run_ctx.hook_url("h-org-alias-after")
    fields = {"content_type": "json", "events": ["push"]}

    write(otterdog, renderer, hook(before, **fields))
    apply(otterdog, run_ctx, helpers, "apply (org webhook added)")
    live_hook(oracle, helpers, before, f"org hook {before} created")

    write(otterdog, renderer, hook(after, aliases=[before], **fields))
    result, parsed = plan(otterdog, run_ctx, "plan (org webhook url changed through aliases)")
    ops = [obj.op for url in (before, after) for obj in hook_objects(parsed, url)]
    assert "add" not in ops and "remove" not in ops, f"the alias was not matched:\n{result.output[-TAIL:]}"
    if ops != ["change"]:
        raise UrlAliasNotAppliedError(f"no change of the org webhook is planned for the new url:\n{result.output}")
    apply(otterdog, run_ctx, helpers, "apply (org webhook url changed through aliases)")
    live_hook(oracle, helpers, after, f"org hook renamed to {after}")
    if oracle.org_hook_by_url(before) is not None:
        raise UrlAliasNotAppliedError(f"the old url {before} still exists")
    converge(otterdog, run_ctx, helpers, "the org webhook url change")
