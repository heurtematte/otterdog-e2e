"""Webapp facet of the session context (SPEC 15, F10): the webapp of the target and its isolated test cases.

WebappFacet builds the deployment (a compose WebappStack for the relay transport, else an ExternalWebapp), starts it in
the SPEC 15 order, reloads and stops it, commits its otterdog.json, and creates the config repo flow, the delivery
relay and the webapp cases (begin_webapp_case / end_webapp_case). ``extras["dtrack_mock"]`` (set by the plugin when a
selected item uses the ``dtrack_mock`` fixture) starts the compose stack with the Dependency-Track mock; dtrack_mock()
returns its client (enabling it on a running stack when needed); blueprint_helper() wires a blueprints.BlueprintHelper
to a webapp case.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, TypeGuard, cast

from otterdog_e2e.context.helpers import describe_error
from otterdog_e2e.context.state import ContextError
from otterdog_e2e.context.sut import SutFacet

if TYPE_CHECKING:
    from otterdog_e2e.blueprints import BlueprintHelper
    from otterdog_e2e.config_repo import ConfigRepoFlow
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.sut.template import TemplateRef
    from otterdog_e2e.webapp.api import WebappApi
    from otterdog_e2e.webapp.stack import DtrackMock, ExternalWebapp, WebappStack
    from otterdog_e2e.webhooks.relay import DeliveryRelay

    Deployment = WebappStack | ExternalWebapp

logger = logging.getLogger(__name__)

WEBAPP_READY_TIMEOUT = 300.0


@dataclass
class WebappCase:
    """State of one isolated webapp test (F10), created by E2EContext.begin_webapp_case."""

    flow: ConfigRepoFlow
    api: WebappApi
    org: str
    baseline_text: str
    started_at: datetime
    seen_comment_ids: frozenset[str] = frozenset()


class WebappFacet(SutFacet):
    """Webapp deployment, its otterdog.json, config repo flow, relay and isolated cases of a session."""

    # --- webapp ---------------------------------------------------------------------------------------------------
    def config_token(self) -> str:
        """OTTERDOG_CONFIG_TOKEN: the config_reader token, else the admin token for trusted SUTs only (SEC-11)."""
        if "config_reader" in self.identities:
            return self.identities["config_reader"].token
        if self.resolve(self.options.sut).trusted:
            return self.require_identity("admin").token
        raise ContextError("untrusted SUT: the webapp tier needs a config_reader identity (E2E_CONFIG_READ_TOKEN)")

    def webapp_deployment(self) -> Deployment:
        """WebappStack (transport relay) or ExternalWebapp (transport external) of the target, not started."""
        from otterdog_e2e.webapp.stack import ExternalWebapp, WebappSettings, WebappStack

        target, verified = self.require_target(), self.require_verified()
        spec = target.webapp
        if spec.transport == "external":
            if not spec.external_url:
                raise ContextError("webapp transport 'external' needs webapp.external_url (E2E_EXTERNAL_URL)")
            return ExternalWebapp(
                spec.external_url, init_url=spec.external_init_url, allow_remote=self.options.allow_remote_webapp
            )
        if spec.transport != "relay":
            raise ContextError(f"webapp transport {spec.transport!r} cannot serve webapp tests")
        app = self.require_app_credentials()
        # the stack hands the private key to the SUT image (untrusted PR images included): re-checked at every start
        self.verify_app()
        settings = WebappSettings(
            org=target.org,
            configs_repo=target.configs_repo,
            config_token=self.config_token(),
            app=app,
            validation_context=spec.validation_context,
            sync_context=spec.sync_context,
            admin_team=target.admin_team,
            approval_team=target.approval_team,
            workers=spec.workers,
            port=spec.port,
            dtrack_mock=bool(self.extras.get("dtrack_mock")),
        )
        return WebappStack(
            settings,
            verified=verified,
            image=self.image_for("head").tag,
            run_ctx=self.run_ctx,
            scratch=self.scratch / "webapp",
            artifacts_dir=self.artifacts_dir,
        )

    def start_webapp(self, baseline: BaselineManager, template: TemplateRef) -> Deployment:
        """SPEC 15 order: stack up -> config repo main = baseline -> otterdog.json in the configs repo ->
        /internal/init -> wait_ready; records the ready time used as the relay's ``since``."""
        deployment = self.webapp_deployment()
        if _is_stack(deployment):
            deployment.up()
        try:
            baseline.push(self.config_flow(baseline))
            self.publish_otterdog_json(template)
            deployment.init()
            self._wait_ready(deployment)
        except BaseException:
            self.stop_webapp(deployment)
            raise
        self.extras["webapp_ready_at"] = datetime.now(UTC)
        self._record_webapp_version(deployment)
        return deployment

    def reload_webapp(self, deployment: Deployment) -> None:
        """/internal/init (otterdog.json, global policies and blueprints, installations) and wait until the webapp is
        ready for the org again."""
        deployment.init()
        self._wait_ready(deployment)

    def _wait_ready(self, deployment: Deployment) -> None:
        """wait_ready of a stack or an external webapp (which needs the org)."""
        if _is_stack(deployment):
            deployment.wait_ready(timeout=WEBAPP_READY_TIMEOUT)
        else:
            external = cast("ExternalWebapp", deployment)
            external.wait_ready(org=self.require_target().org, timeout=WEBAPP_READY_TIMEOUT)

    def _record_webapp_version(self, deployment: Deployment) -> None:
        """Store the version shown by the webapp in run.json (compose stacks only)."""
        if _is_stack(deployment):
            try:
                version = deployment.deployed_version()
            except Exception as exc:  # noqa: BLE001 - informational only
                logger.warning("could not read the webapp version: %s", describe_error(exc))
                return
            self.write_run_info(versions={**(self.run_info.get("versions") or {}), "webapp": version})

    def stop_webapp(self, deployment: Deployment) -> None:
        """Save the logs and stop a compose stack (external webapps are left alone)."""
        if _is_stack(deployment):
            try:
                deployment.save_logs()
            except Exception as exc:  # noqa: BLE001 - the stack must go down even without logs
                logger.warning("could not save the webapp logs: %s", describe_error(exc))
            finally:
                deployment.down()

    def publish_otterdog_json(
        self, template: TemplateRef, *, organization: Mapping[str, Sequence[str] | None] | None = None
    ) -> None:
        """Commit the webapp's otterdog.json to the configs repo (only when its content changes); ``organization``
        overrides the org entry's admin_teams / approval_teams (a list of team names or patterns; None drops the key,
        so the GITHUB_ADMIN_TEAMS / GITHUB_APPROVAL_TEAMS of the webapp apply). Call it again without overrides to
        restore the run's file, and reload_webapp() to make the webapp read it."""
        from otterdog_e2e.otterdog.workspace import webapp_otterdog_json

        target = self.require_target()
        data = webapp_otterdog_json(target, template, config_repo=target.config_repo_for(self.run_ctx))
        if organization:
            entry = data["organizations"][0]
            for key, value in check_organization_overrides(organization).items():
                if value is None:
                    entry.pop(key, None)
                else:
                    entry[key] = value
        content = json.dumps(data, indent=2) + "\n"
        oracle = self.oracle()
        branch = oracle.default_branch(target.configs_repo) or "main"
        if oracle.file_content(target.configs_repo, "otterdog.json", ref=branch) == content:
            return
        message = f"otterdog-e2e: otterdog.json of run {self.run_ctx.run_id}"
        self.mutator("admin").commit_files(target.configs_repo, branch, {"otterdog.json": content}, message)

    def config_flow(
        self,
        baseline: BaselineManager,
        *,
        relay: DeliveryRelay | None = None,
        bot_login: str | None = None,
    ) -> ConfigRepoFlow:
        """ConfigRepoFlow on the run's org config repo, guarded by BaselineManager.guard_config_change (SEC-07)."""
        from otterdog_e2e.config_repo import ConfigRepoFlow

        target = self.require_target()
        return ConfigRepoFlow(
            org=target.org,
            repo=target.config_repo_for(self.run_ctx),
            oracle=self.oracle(),
            mutators=self.mutators(),
            run_ctx=self.run_ctx,
            validation_context=target.webapp.validation_context,
            sync_context=target.webapp.sync_context,
            guard=baseline.guard_config_change,
            bot_login=bot_login,
            relay=relay,
        )

    def start_relay(self, deployment: Deployment) -> DeliveryRelay:
        """DeliveryRelay forwarding the installation's deliveries since the webapp ready time, started."""
        from otterdog_e2e.webhooks.relay import DeliveryRelay

        relay = DeliveryRelay(
            self.app_auth(),
            forward_url=deployment.webhook_url,
            secret=self.require_app_credentials().webhook_secret,
            since=self.extras.get("webapp_ready_at") or datetime.now(UTC),
            installation_id=self.installation_id(),
            org=self.require_target().org,
            artifacts_dir=self.artifacts_dir,
            allow_remote=self.options.allow_remote_webapp,
        )
        relay.start()
        return relay

    def begin_webapp_case(self, flow: ConfigRepoFlow, api: WebappApi, baseline: BaselineManager) -> WebappCase:
        """F10 before: config repo main == baseline (reset_main otherwise), webapp quiet, comment ids snapshot."""
        text = baseline.text()
        if flow.main_config() != text:
            flow.reset_main(text, message=f"otterdog-e2e {self.run_ctx.run_id}: reset to baseline")
        org = self.require_target().org
        api.quiesce(org_id=org)
        return WebappCase(
            flow=flow,
            api=api,
            org=org,
            baseline_text=text,
            started_at=datetime.now(UTC),
            seen_comment_ids=self._open_pr_comment_ids(flow),
        )

    def _open_pr_comment_ids(self, flow: ConfigRepoFlow) -> frozenset[str]:
        """Ids of the comments on the open PRs of the config repo."""
        oracle = self.oracle()
        ids: set[str] = set()
        for pull in oracle.pulls(flow.repo):
            ids.update(str(comment.get("id")) for comment in oracle.pr_comments(flow.repo, int(pull["number"])))
        return frozenset(ids)

    def end_webapp_case(
        self, case: WebappCase, *, baseline: BaselineManager, reset_cli: OtterdogCli, org_level: bool
    ) -> None:
        """F10 after: close PRs/branches, main back to baseline, guarded ``apply -d -r <p>-*``, full reset for
        org_level tests; every step runs, failures are raised together."""

        def reset_main() -> None:
            """Restore the baseline on main when a test changed it."""
            if case.flow.main_config() != case.baseline_text:
                case.flow.reset_main(case.baseline_text, message=f"otterdog-e2e {self.run_ctx.run_id}: restore")

        steps: list[tuple[str, Callable[[], Any]]] = [
            ("close PRs and delete branches", case.flow.cleanup),
            ("reset config repo main", reset_main),
            ("remove run objects", lambda: self.remove_run_objects(baseline, reset_cli)),
        ]
        if org_level:
            steps.append(("baseline reset", baseline.reset))
        errors = []
        for what, step in steps:
            try:
                step()
            except Exception as exc:  # noqa: BLE001 - every cleanup step runs; failures are raised together
                errors.append(f"{what}: {describe_error(exc)}")
        if errors:
            raise ContextError("webapp case cleanup failed: " + "; ".join(errors))

    def remove_run_objects(self, baseline: BaselineManager, reset_cli: OtterdogCli) -> None:
        """Baseline-only config + guarded ``apply -d -r e2e-<run>-*`` with the trusted reset CLI."""
        reset_cli.workspace.write_org_config(baseline.text())
        baseline.guarded_apply(reset_cli, repo_filter=self.run_ctx.repo_filter(), delete=True)

    def dtrack_mock(self, deployment: Deployment) -> DtrackMock:
        """Client of the Dependency-Track mock of a compose stack, started (with the webapp recreated to use it) when
        the stack runs without it; ContextError for an external webapp (its DEPENDENCY_TRACK_URL is not ours)."""
        from otterdog_e2e.webapp.stack import WebappStackError

        if not _is_stack(deployment):
            raise ContextError("the Dependency-Track mock needs the compose webapp stack (webapp transport relay)")
        try:
            return deployment.dtrack() if deployment.dtrack_enabled else deployment.enable_dtrack_mock()
        except WebappStackError as exc:
            raise ContextError(f"Dependency-Track mock unavailable: {describe_error(exc)}") from exc

    def blueprint_helper(self, case: WebappCase, *, relay: DeliveryRelay | None = None) -> BlueprintHelper:
        """BlueprintHelper of a webapp case: org config repo of the run, the configs repo, the admin Mutator, the
        case's flow and API, the relay, the larger-runner capability (billing guard) and the purgeable runs."""
        from otterdog_e2e.blueprints import BlueprintHelper
        from otterdog_e2e.capabilities import Cap

        target = self.require_target()
        return BlueprintHelper(
            org=target.org,
            configs_repo=target.configs_repo,
            config_repo=target.config_repo_for(self.run_ctx),
            run_ctx=self.run_ctx,
            oracle=self.oracle(),
            mutator=self.mutator("admin"),
            api=case.api,
            flow=case.flow,
            relay=relay,
            larger_runners=self.require_capabilities().has(Cap.LARGER_RUNNERS),
            purgeable=self.purgeable,
        )


ORGANIZATION_OVERRIDES = frozenset({"admin_teams", "approval_teams"})  # keys of publish_otterdog_json(organization=)


def check_organization_overrides(overrides: Mapping[str, Any]) -> dict[str, list[str] | None]:
    """Validated otterdog.json org-entry overrides: ORGANIZATION_OVERRIDES keys, lists of non-empty strings or None
    (ValueError)."""
    checked: dict[str, list[str] | None] = {}
    for key, value in overrides.items():
        if key not in ORGANIZATION_OVERRIDES:
            raise ValueError(
                f"otterdog.json key {key!r} cannot be overridden (allowed: {sorted(ORGANIZATION_OVERRIDES)})"
            )
        if value is None:
            checked[key] = None
            continue
        if isinstance(value, str) or not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError(f"{key} must be a list of team names or patterns, got {value!r}")
        checked[key] = list(value)
    return checked


def _is_stack(deployment: Any) -> TypeGuard[WebappStack]:
    """True for a compose WebappStack (it can be stopped), False for an ExternalWebapp (duck-typed for fakes)."""
    return hasattr(deployment, "down")
