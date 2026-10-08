"""SUT facet of the session context (SPEC 5.5, SPEC 15): the systems under test and the otterdog drivers.

SutFacet resolves the SUT of each role (head: --e2e-sut, base: --e2e-base-sut with ``auto`` = the merge base, reset:
the trusted --e2e-reset-sut), installs its CLI (host venv for trusted SUTs or one granted host trust with
--e2e-trust-code, the CLI of the SUT image otherwise), builds webapp images and templates, and creates the otterdog
drivers (renderer, baseline manager, workspaces, CLIs) and the base/head sides of the differential (SutPair).
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, NamedTuple

from otterdog_e2e.context.helpers import (
    describe_error,
    in_ci,
    interactive_terminal,
    printed_version,
    workspace_literals,
)
from otterdog_e2e.context.live import LiveFacet
from otterdog_e2e.context.state import AUTO_BASE, HTTP_CACHE_DIR, ContextError

if TYPE_CHECKING:
    from otterdog_e2e.observe import ObservationRecorder
    from otterdog_e2e.otterdog.baseline import BaselineManager
    from otterdog_e2e.otterdog.output import NormalizeContext
    from otterdog_e2e.otterdog.render import OrgConfigRenderer
    from otterdog_e2e.otterdog.runner import OtterdogCli
    from otterdog_e2e.otterdog.workspace import ConfigWorkspace
    from otterdog_e2e.scenarios.engine import SutSide
    from otterdog_e2e.sut.cli_install import InstalledCli
    from otterdog_e2e.sut.image import BuiltImage
    from otterdog_e2e.sut.spec import ResolvedSut
    from otterdog_e2e.sut.template import TemplateRef

logger = logging.getLogger(__name__)

SUT_ROLES = ("head", "base", "reset")
OBSERVATIONS_DIR = "observations"
OFFLINE_CONFIG_REPO = ".otterdog"


class SutPair(NamedTuple):
    """Base and head sides of a differential run (unpackable: ``base, head = sut_pair``)."""

    base: SutSide
    head: SutSide


class SutFacet(LiveFacet):
    """Systems under test of the roles, otterdog drivers and differential sides of a session."""

    # --- systems under test ---------------------------------------------------------------------------------------
    def spec_for(self, role: str) -> str:
        """SUT spec of a role: head (--e2e-sut), base (--e2e-base-sut, ``auto`` = merge base), reset."""
        if role == "head":
            return self.options.sut
        if role == "reset":
            return self.options.reset_sut
        if role != "base":
            raise ValueError(f"unknown SUT role {role!r}, expected one of {SUT_ROLES}")
        base = self.options.base_sut
        if not base:
            raise ContextError("no base SUT: pass --e2e-base-sut (or set E2E_BASE_SUT)")
        if base != AUTO_BASE:
            return base
        base_sha = self.resolve(self.options.sut).base_sha
        if not base_sha:
            raise ContextError(
                f"--e2e-base-sut auto: {self.options.sut!r} has no merge base (only pr:, path: and dirty: SUTs have"
                " one); pass the base explicitly, e.g. --e2e-base-sut sha:<parent commit> or tag:v1.6.1"
            )
        return f"sha:{base_sha}"

    def resolve(self, spec: str) -> ResolvedSut:
        """resolve_sut of a spec string (once per context)."""

        def build() -> ResolvedSut:
            """Parse and resolve the spec."""
            from otterdog_e2e.sut.spec import parse_sut_spec, resolve_sut

            return resolve_sut(parse_sut_spec(spec), self.settings, http=self.public_http())

        return self._memo(f"resolved:{spec}", build)

    def installed(self, role: str) -> InstalledCli:
        """InstalledCli of a role: host venv for trusted SUTs, the CLI of the SUT image otherwise (SPEC 5.5)."""
        return self._memo(f"installed:{role}", lambda: self._install(role))

    def _install(self, role: str) -> InstalledCli:
        """Install (or wrap) the CLI of a role and record it in run.json."""
        from otterdog_e2e.safety import SafetyError
        from otterdog_e2e.sut.cli_install import image_cli, install_cli

        resolved = self.resolve(self.spec_for(role))
        if role == "reset" and not resolved.trusted:
            raise SafetyError(f"the reset SUT {resolved.label} is not trusted: resets never run untrusted code")
        if resolved.trusted:
            installed = install_cli(resolved, self.settings)
        else:
            granted = self._host_trust(resolved)
            if granted is not None:
                installed = install_cli(granted, self.settings)
            else:
                installed = image_cli(resolved, self.image_for(role))
        self._record_sut(role, installed)
        return installed

    def _host_trust(self, resolved: ResolvedSut) -> ResolvedSut | None:
        """--e2e-trust-code <sha>: cli_install.grant_host_trust for the untrusted SUT of exactly that sha (from an
        interactive terminal, never in CI: SafetyError otherwise); None when the code does not name this SUT (it then
        runs in its docker image)."""
        code = (self.options.trust_code or "").strip().lower()
        if not code:
            return None
        if code != resolved.sha:
            logger.warning("--e2e-trust-code %s does not name %s: it runs in its docker image", code, resolved.label)
            return None
        from otterdog_e2e.safety import SafetyError
        from otterdog_e2e.sut.cli_install import grant_host_trust

        if in_ci(self.environ):
            raise SafetyError("--e2e-trust-code is refused when CI is set")
        return grant_host_trust(resolved, code, interactive=interactive_terminal(), environ=self.environ)

    def sut_trusted(self, role: str = "head") -> bool | None:
        """Trust of a role's SUT (gating, SPEC 5.5): decided by its spec (pr: never; release, tag, branch:main, path,
        dirty: always), else by resolve_sut (sha: and other branches, which may fetch the upstream mirror); None when
        it cannot be decided (the SUT fixtures then report the resolution error)."""

        def build() -> bool | None:
            """Parse, then resolve only when the spec does not decide."""
            from otterdog_e2e.sut.spec import parse_sut_spec

            try:
                spec = self.spec_for(role)
                parsed = parse_sut_spec(spec)
                if parsed.kind == "pr" or parsed.trusted:
                    return parsed.trusted
                return bool(self.resolve(spec).trusted)
            except Exception as exc:  # noqa: BLE001 - undecided here; the fixtures surface the real error
                logger.warning("cannot tell whether the %s SUT is trusted: %s", role, describe_error(exc))
                return None

        return self._memo(f"trusted:{role}", build)

    def _record_sut(self, role: str, installed: InstalledCli) -> None:
        """Store a SUT and its printed version in run.json."""
        key = {"head": "sut", "base": "base", "reset": "reset_sut"}[role]
        versions = {**(self.run_info.get("versions") or {}), role: installed.version_output.strip()}
        self.write_run_info(**{key: {**installed.sut.to_json(), "runtime": installed.runtime}}, versions=versions)
        if role == "head":
            self.extras["sut_label"] = installed.sut.label

    def sut_label(self) -> str:
        """Label of the SUT under test once installed, else its spec."""
        return str(self.extras.get("sut_label") or self.options.sut)

    def sut_version(self) -> str | None:
        """PEP 440 version of the SUT under test (resolve_sut, no install); None when it cannot be resolved (the SUT
        fixtures then report the resolution error)."""
        try:
            return str(self.resolve(self.options.sut).version) or None
        except Exception as exc:  # noqa: BLE001 - unknown version: callers fall back to their default behaviour
            logger.warning("cannot resolve the version of the SUT %s: %s", self.options.sut, describe_error(exc))
            return None

    def image_for(self, role: str) -> BuiltImage:
        """Webapp image of a role (head: --e2e-webapp-image when given)."""

        def build() -> BuiltImage:
            """Build (or describe the prebuilt) image."""
            from otterdog_e2e.sut.image import build_webapp_image, prebuilt_image

            if role == "head" and self.options.webapp_image:
                return prebuilt_image(self.options.webapp_image)
            return build_webapp_image(self.resolve(self.spec_for(role)))

        return self._memo(f"image:{role}", build)

    def docker_available(self) -> bool:
        """True when the docker daemon answers (checked once)."""

        def build() -> bool:
            """Ask docker."""
            from otterdog_e2e.sut.image import docker_available

            try:
                return bool(docker_available())
            except Exception as exc:  # noqa: BLE001 - any failure means docker cannot be used
                logger.info("docker is not available: %s", describe_error(exc))
                return False

        return self._memo("docker", build)

    def template_for(self, role: str) -> TemplateRef:
        """Base template of a role's SUT per target.template_mode. Publishing to the defaults repo happens only while
        this session holds the org lease (ContextError otherwise); the published or reused tag is then recorded in the
        lease (OrgLease.reference) so a concurrent janitor keeps it (SEC-17)."""

        def build() -> TemplateRef:
            """Resolve (and maybe publish) the template."""
            from otterdog_e2e.sut.template import TemplatePublisher, needs_publisher, resolve_template

            target = self.require_target()
            resolved = self.resolve(self.spec_for(role))
            lease, publisher = None, None
            if needs_publisher(target.template_mode, resolved):
                lease = self.require_lease(f"publishing the template of {resolved.label}")
                publisher = TemplatePublisher(
                    self.http("admin", write=True), self.require_verified(), target.defaults_repo
                )
            template = resolve_template(
                target.template_mode,
                resolved,
                upstream_repo=self.settings.upstream_repo,
                publisher=publisher,
                url=target.template_url,
            )
            if lease is not None and template.tag:
                lease.reference(f"tags/{template.tag}")
            return template

        return self._memo(f"template:{role}", build)

    # --- otterdog drivers -----------------------------------------------------------------------------------------
    def renderer(self, template: TemplateRef) -> OrgConfigRenderer:
        """OrgConfigRenderer of the org: live profile (keys GitHub did not return stay hidden, i.e. unmanaged), baseline
        of the run, cache limit hidden when unsupported."""
        from otterdog_e2e.capabilities import Cap
        from otterdog_e2e.otterdog.render import OrgConfigRenderer, build_baseline, org_profile

        target, verified = self.require_target(), self.require_verified()
        return OrgConfigRenderer(
            template=template,
            org=target.org,
            plan=verified.plan,
            org_profile=org_profile(verified.org_json),
            baseline=build_baseline(target, self.run_ctx),
            marker=target.marker,
            hide_cache_limit=not self.require_capabilities().has(Cap.ACTIONS_CACHE_LIMIT),
        )

    def baseline_manager(self, reset_cli: OtterdogCli, renderer: OrgConfigRenderer) -> BaselineManager:
        """BaselineManager of the run (trusted reset CLI, purgeable = ledger runs, protected repos of the target)."""
        from otterdog_e2e.otterdog.baseline import BaselineManager

        target = self.require_target()
        manager = BaselineManager(
            reset_cli=reset_cli,
            renderer=renderer,
            target=target,
            run_ctx=self.run_ctx,
            oracle=self.oracle(),
            purgeable=self.purgeable,
            protected_repos=target.protected_repos(self.run_ctx),
        )
        manager.write_check = self.check_lease_not_lost
        return manager

    def workspace(self, name: str, template: TemplateRef) -> ConfigWorkspace:
        """A ConfigWorkspace of the test org in scratch/workspaces/<name> with otterdog.json written."""
        from otterdog_e2e.otterdog.workspace import ConfigWorkspace

        target = self.require_target()
        workspace = ConfigWorkspace(
            self.scratch / "workspaces" / name,
            org=target.org,
            template=template,
            config_repo=target.config_repo_for(self.run_ctx),
        )
        workspace.write_otterdog_json()
        return workspace

    def offline_workspace(self, name: str) -> ConfigWorkspace:
        """A ConfigWorkspace of the offline org with the offline template placeholder (vendoring is up to the user)."""
        from otterdog_e2e.otterdog.workspace import ConfigWorkspace
        from otterdog_e2e.scenarios.offline import OFFLINE_ORG
        from otterdog_e2e.sut.template import offline_template

        workspace = ConfigWorkspace(
            self.scratch / "workspaces" / name,
            org=OFFLINE_ORG,
            template=offline_template(),
            config_repo=OFFLINE_CONFIG_REPO,
        )
        workspace.write_otterdog_json()
        return workspace

    def unique_name(self, hint: str) -> str:
        """``<seq>-<hint>`` with filesystem-safe characters (fresh workspaces)."""
        seq = int(self.extras.get("name_seq", 0)) + 1
        self.extras["name_seq"] = seq
        return f"{seq:03d}-{re.sub(r'[^A-Za-z0-9_.-]+', '_', hint)[:60]}"

    def cli(
        self,
        installed: InstalledCli,
        workspace: ConfigWorkspace,
        *,
        name: str,
        artifacts: str | None = None,
        identity: str = "admin",
        recorder: ObservationRecorder | None = None,
        offline: bool = False,
    ) -> OtterdogCli:
        """OtterdogCli with its own scratch (scratch/cli/<name>) and artifacts subdir (None = the run dir: SUT)."""
        from otterdog_e2e.otterdog.runner import OtterdogCli

        cli = OtterdogCli(
            installed,
            workspace,
            verified=None if offline else self.require_verified(),
            identity=None if offline else self.require_identity(identity),
            scratch=self.scratch / "cli" / name,
            artifacts_dir=self.artifacts_dir / artifacts if artifacts else self.artifacts_dir,
            settings=self.settings,
            recorder=recorder,
            offline=offline,
            http_cache=not self.options.no_http_cache,
            http_cache_root=self.scratch / HTTP_CACHE_DIR,
        )
        if not offline:
            cli.live_check = self.check_lease_not_lost
        return cli

    # --- differential ---------------------------------------------------------------------------------------------
    def recorder(self, role: str) -> ObservationRecorder:
        """ObservationRecorder of a differential side (observations/<role>.jsonl), one per role."""

        def build() -> ObservationRecorder:
            """Create the recorder."""
            from otterdog_e2e.observe import ObservationRecorder

            installed = self.installed(role)
            return ObservationRecorder(
                installed.sut.label,
                role,
                self.artifacts_dir / OBSERVATIONS_DIR / f"{role}.jsonl",
                normalize_ctx=self.normalize_context(installed),
            )

        return self._memo(f"recorder:{role}", build)

    def normalize_context(self, installed: InstalledCli) -> NormalizeContext:
        """Literals hiding run-specific strings (scratch path, run prefixes, printed version) in observations."""
        from otterdog_e2e.otterdog.output import NormalizeContext

        literals = [
            (str(self.scratch), "<SCRATCH>"),
            (self.run_ctx.prefix, "e2e-<RUN>"),
            (self.run_ctx.const_prefix, "E2E_<RUN>_"),
            (self.run_ctx.run_id, "<RUN>"),
        ]
        version = printed_version(installed.version_output)
        if version:
            literals.append((version, "<VERSION>"))
        return NormalizeContext(literals=literals)

    def sut_pair(self, *, live: bool) -> SutPair:
        """Base/head SutSides (cached per mode): offline sides use the offline workspace and template placeholder,
        live sides each SUT's own template; both record observations."""
        mode = "live" if live else "offline"
        return self._memo(f"pair:{mode}", lambda: SutPair(self._side("base", live=live), self._side("head", live=live)))

    def _side(self, role: str, *, live: bool) -> SutSide:
        """One SutSide (CLI artifacts under <role>/<mode>/ so reports attribute base and head); its workspace root
        is hidden in its observations (workspace_literals)."""
        from otterdog_e2e.scenarios.engine import SutSide
        from otterdog_e2e.sut.template import offline_template

        mode = "live" if live else "offline"
        installed = self.installed(role)
        template = self.template_for(role) if live else offline_template()
        name = f"diff-{mode}-{role}"
        workspace = self.workspace(name, template) if live else self.offline_workspace(name)
        recorder = self.recorder(role)
        cli = self.cli(installed, workspace, name=name, artifacts=f"{role}/{mode}", recorder=recorder, offline=not live)
        if recorder.normalize_ctx is not None:
            known = recorder.normalize_ctx.literals
            known.extend(pair for pair in workspace_literals(cli) if pair not in known)
        return SutSide(role=role, installed=installed, cli=cli, recorder=recorder, template=template)
