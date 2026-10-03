"""Package resources: the org config template (SPEC 11.4), the compose stack (SPEC 13.1) and the hypercorn config."""

from __future__ import annotations

import json
import re
import tomllib
from importlib.resources import files
from typing import Any

import jinja2
import pytest
import yaml

from otterdog_e2e import RESOURCE_NAMES, read_resource, resource
from otterdog_e2e.otterdog.render import CACHE_LIMIT_OVERRIDES, FRAGMENT_KEYS, ConfigFragments
from otterdog_e2e.webapp.stack import (
    COMPOSE_REQUIRED_VARIABLES,
    COMPOSE_VARIABLES,
    DTRACK_CONTAINER_PORT,
    DTRACK_INTERNAL_URL,
    DTRACK_MOCK_RESOURCE,
    DTRACK_PROFILE,
    DTRACK_SERVICE,
    SERVICES,
    read_dtrack_mock,
)

PROFILE = {
    "plan": "free",
    "billing_email": "billing@example.org",
    "description": "[otterdog-e2e] test org",
    "name": "E2E Org",
    "email": None,
    "blog": None,
    "location": None,
    "company": None,
    "twitter_username": None,
}


def render_org(**overrides: Any) -> str:
    """Render org.jsonnet.j2 the way OrgConfigRenderer is expected to (StrictUndefined, verbatim values)."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True, autoescape=False)  # noqa: S701 - jsonnet, not HTML
    variables: dict[str, Any] = {
        "import_path": "vendor/template/otterdog-defaults.libsonnet",
        "template_overrides": "",
        "project": "e2e-project",
        "org": "e2e-test-org",
        "settings": [f"{key}: {json.dumps(value)}" for key, value in PROFILE.items()],
        "custom_properties": [],
        "hide_cache_limit": False,
        "teams": [],
        "repositories": [],
        "fragments": ConfigFragments().to_mapping(),
    }
    variables.update(overrides)
    return env.from_string(read_resource("org.jsonnet.j2")).render(**variables)


def _balanced(text: str) -> bool:
    """Braces and brackets are balanced (outside of quoted strings, which the tests keep simple)."""
    return text.count("{") == text.count("}") and text.count("[") == text.count("]")


def test_resources_are_package_data() -> None:
    """Every resource is reachable through importlib.resources."""
    for name in RESOURCE_NAMES:
        assert (files("otterdog_e2e") / "resources" / name).is_file()
        assert resource(name).read_text()
    with pytest.raises(ValueError):
        resource("unknown.txt")


def test_org_template_minimal_render() -> None:
    """Baseline-only render: one import, the live profile in layer 1, an empty layer 2."""
    text = render_org()
    assert "local orgs0 = import 'vendor/template/otterdog-defaults.libsonnet';" in text
    assert "local orgs = orgs0;" in text
    assert "orgs.newOrg('e2e-project', 'e2e-test-org') {" in text
    assert '    description: "[otterdog-e2e] test org",' in text
    assert "    email: null," in text
    assert text.rstrip().endswith("} {\n}")
    assert "custom_properties+" not in text and "_repositories+" not in text
    assert _balanced(text)


def test_org_template_layers_overrides_and_baseline() -> None:
    """Cache-limit hiding (OC-06), baseline props/teams/repos stay in layer 1 as separate object layers."""
    text = render_org(
        template_overrides=CACHE_LIMIT_OVERRIDES,
        hide_cache_limit=True,
        settings=[
            *[f"{k}: {json.dumps(v)}" for k, v in PROFILE.items()],
            'workflows+: {"enabled_repositories": "all"}',
        ],
        custom_properties=["orgs.newCustomProperty('e2e-t3c7z8a5-base')"],
        teams=["orgs.newTeam('otterdog-admins') { members: ['e2e-admin'] }"],
        repositories=["orgs.newRepo('otterdog-e2e-configs') { description: 'configs' }"],
    )
    assert f"local orgs = orgs0 {CACHE_LIMIT_OVERRIDES};" in text
    layer1, layer2 = text.split("\n} {\n")
    # workflows from baseline settings and the hidden cache limit never share one object (duplicate field)
    assert layer1.split("orgs.newOrg(", 1)[1].count("workflows+:") == 2
    assert "  } + {\n    custom_properties+: [\n      orgs.newCustomProperty('e2e-t3c7z8a5-base'),\n    ],\n" in layer1
    assert "  } + {\n    workflows+: { max_cache_size_gb:: null },\n  }," in layer1
    assert "  teams+: [\n    orgs.newTeam('otterdog-admins') { members: ['e2e-admin'] },\n  ]," in layer1
    assert "  _repositories+: [\n    orgs.newRepo('otterdog-e2e-configs') { description: 'configs' },\n  ]," in layer1
    assert layer2.strip() == "}"
    assert _balanced(text)


def test_org_template_scenario_fragments() -> None:
    """Every fragment key lands in layer 2, verbatim, with trailing commas normalized."""
    fragments = ConfigFragments.from_mapping(
        {
            "settings": ["web_commit_signoff_required: false,"],
            "custom_properties": ["orgs.newCustomProperty('e2e-t3c7z8a5-tier')"],
            "teams": ["orgs.newTeam('e2e-t3c7z8a5-team')"],
            "secrets": ["orgs.newOrgSecret('E2E_T3C7Z8A5_S') { value: '********' }"],
            "variables": ["orgs.newOrgVariable('E2E_T3C7Z8A5_V') { value: 'x' }"],
            "webhooks": ["orgs.newOrgWebhook('https://otterdog-e2e.invalid/t3c7z8a5/org')"],
            "rulesets": ["orgs.newOrgRuleset('e2e-t3c7z8a5-rs')"],
            "roles": ["orgs.newOrgRole('e2e-t3c7z8a5-role')"],
            "repositories": ["orgs.newRepo('e2e-t3c7z8a5-basic') { description: '${{ github.sha }}' }"],
            "extra": ["// raw layer-2 field follows\n  _e2e_marker:: true"],
        }
    )
    layer2 = render_org(fragments=fragments.to_mapping()).split("\n} {\n")[1]
    assert "  settings+: {\n    web_commit_signoff_required: false,\n  } + {\n    custom_properties+: [" in layer2
    for key, field in (
        ("teams", "teams"),
        ("secrets", "secrets"),
        ("variables", "variables"),
        ("webhooks", "webhooks"),
    ):
        assert f"  {field}+: [\n    {getattr(fragments, key)[0]},\n  ]," in layer2
    for key, field in (("rulesets", "rulesets"), ("roles", "roles"), ("repositories", "_repositories")):
        assert f"  {field}+: [\n    {getattr(fragments, key)[0]},\n  ]," in layer2
    assert "'${{ github.sha }}'" in layer2  # values are never rendered a second time
    assert "_e2e_marker:: true," in layer2
    assert set(fragments.to_mapping()) == set(FRAGMENT_KEYS)


def test_org_template_is_strict() -> None:
    """A missing variable fails the render instead of producing a partial config."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - jsonnet, not HTML
    with pytest.raises(jinja2.UndefinedError):
        env.from_string(read_resource("org.jsonnet.j2")).render(import_path="x")


def test_org_template_documents_its_variables() -> None:
    """The jsonnet comment at the top documents every template variable."""
    header = read_resource("org.jsonnet.j2").split("*/", 1)[0]
    for name in (
        "import_path",
        "template_overrides",
        "project, org",
        "settings",
        "custom_properties",
        "hide_cache_limit",
        "teams",
        "repositories",
        "fragments",
    ):
        assert name in header, name
    assert "{{" not in header and "{%" not in header


# --- compose -------------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def compose() -> dict[str, Any]:
    """Parsed compose.e2e.yaml."""
    return yaml.safe_load(read_resource("compose.e2e.yaml"))


# settings otterdog's webapp refuses to start without (otterdog/webapp/config.py REQUIRED_NON_EMPTY_SETTINGS minus
# ASSETS_ROOT, which has a default) plus the secrets it needs
WEBAPP_ENV = {
    "BASE_URL",
    "APP_ROOT",
    "MONGO_URI",
    "REDIS_URI",
    "GHPROXY_URI",
    "GITHUB_ADMIN_TEAMS",
    "GITHUB_APPROVAL_TEAMS",
    "GITHUB_WEBHOOK_ENDPOINT",
    "GITHUB_WEBHOOK_VALIDATION_CONTEXT",
    "GITHUB_WEBHOOK_SYNC_CONTEXT",
    "GITHUB_APP_ID",
    "GITHUB_APP_PRIVATE_KEY",
    "PROJECTS_BASE_URL",
    "DEPENDENCY_TRACK_URL",
    "DEPENDENCY_TRACK_TOKEN",
    "OTTERDOG_CONFIG_OWNER",
    "OTTERDOG_CONFIG_REPO",
    "OTTERDOG_CONFIG_PATH",
    "OTTERDOG_CONFIG_TOKEN",
    "GITHUB_WEBHOOK_SECRET",
    "SECRET_KEY",
    "DEBUG",
    "CACHE_CONTROL",
    "BLUEPRINT_CHECK_INTERVAL",
    "PULL_REQUEST_STATISTICS_CACHE_TTL",
}


def test_compose_services_and_exposure(compose: dict[str, Any]) -> None:
    """webapp, mongodb, redis (+ the dtrack-mock of profile dtrack); only the webapp and the mock (dummy data) are
    published, on 127.0.0.1 (SEC-13)."""
    services = compose["services"]
    assert set(services) == {"webapp", "mongodb", "redis", "dtrack-mock"} == set(SERVICES)
    assert services["webapp"]["ports"] == ["127.0.0.1:${E2E_WEBAPP_PORT:-5000}:5000"]
    assert "ports" not in services["mongodb"] and "ports" not in services["redis"]
    assert all(service.get("restart") == "no" for service in services.values())
    assert not any("env_file" in service for service in services.values())
    assert [name for name, service in services.items() if "profiles" in service] == ["dtrack-mock"]
    assert services["mongodb"]["image"] == "mongo:8.3.4"
    assert services["redis"]["image"] == "valkey/valkey:9.1.0-alpine3.23"
    assert services["mongodb"]["tmpfs"] == ["/data/db"]
    assert services["redis"]["command"] == ["valkey-server", "--save", "", "--appendonly", "no"]
    depends = services["webapp"]["depends_on"]
    assert depends == {"mongodb": {"condition": "service_healthy"}, "redis": {"condition": "service_healthy"}}
    assert "/internal/health" in " ".join(services["webapp"]["healthcheck"]["test"])


def test_compose_webapp_environment(compose: dict[str, Any]) -> None:
    """Every required webapp setting is provided; values follow SPEC 13.1."""
    env = compose["services"]["webapp"]["environment"]
    assert set(env) >= WEBAPP_ENV
    assert env["CACHE_CONTROL"] == ""
    assert env["DEBUG"] == "True"
    assert env["GHPROXY_URI"] == "https://api.github.com"
    assert env["MONGO_URI"] == "mongodb://mongodb:27017/otterdog_e2e"
    assert env["REDIS_URI"] == "redis://redis:6379"
    assert env["GITHUB_APP_PRIVATE_KEY"] == "/run/secrets/github_app_key"
    assert env["GITHUB_WEBHOOK_ENDPOINT"] == "/github-webhook/receive"
    assert env["OTTERDOG_CONFIG_PATH"] == "otterdog.json"
    assert env["DEPENDENCY_TRACK_URL"] == "${E2E_DEPENDENCY_TRACK_URL:-http://127.0.0.1:9}"  # nothing listens there
    assert env["PROJECTS_BASE_URL"] == "https://otterdog-e2e.invalid/projects/"
    assert env["BLUEPRINT_CHECK_INTERVAL"] == "0" and env["PULL_REQUEST_STATISTICS_CACHE_TTL"] == "0"
    assert all(isinstance(value, str) for value in env.values())


def test_compose_secret_and_hypercorn_mount(compose: dict[str, Any]) -> None:
    """The App key is a compose secret file; the hypercorn config is mounted read-only."""
    assert compose["secrets"]["github_app_key"]["file"].startswith("${E2E_GITHUB_APP_KEY_FILE:?")
    webapp = compose["services"]["webapp"]
    assert webapp["secrets"] == ["github_app_key"]
    (volume,) = webapp["volumes"]
    assert volume["target"] == "/app/hypercorn-cfg.toml" and volume["read_only"] is True
    assert volume["source"].startswith("${E2E_HYPERCORN_CFG:?")


def test_compose_variables_match_stack_contract() -> None:
    """The interpolation variables of the file are exactly webapp.stack.COMPOSE_VARIABLES (required ones use :?)."""
    text = "\n".join(
        line for line in read_resource("compose.e2e.yaml").splitlines() if not line.lstrip().startswith("#")
    )
    references = re.findall(r"\$\{([A-Z0-9_]+)(:\?|:-)?", text)
    assert {name for name, _ in references} == set(COMPOSE_VARIABLES)
    assert {name for name, kind in references if kind == ":?"} == set(COMPOSE_REQUIRED_VARIABLES)
    assert all(kind for _, kind in references), "every variable needs a default or an error message"


def test_compose_dtrack_mock_service(compose: dict[str, Any]) -> None:
    """The Dependency-Track mock: profile dtrack, python:3.12-alpine running the mounted mock script read-only as
    nobody on a read-only root, no capabilities, published on a random 127.0.0.1 port, healthy on /health."""
    mock = compose["services"][DTRACK_SERVICE]
    assert mock["profiles"] == [DTRACK_PROFILE]
    assert mock["image"] == "${E2E_DTRACK_MOCK_IMAGE:-python:3.12-alpine}" and mock["pull_policy"] == "missing"
    assert mock["command"] == ["python", "/mock/dtrack_mock.py"]
    (volume,) = mock["volumes"]
    assert volume == {
        "type": "bind",
        "source": f"./{DTRACK_MOCK_RESOURCE}",
        "target": "/mock/dtrack_mock.py",
        "read_only": True,
    }
    assert mock["ports"] == [{"target": DTRACK_CONTAINER_PORT, "host_ip": "127.0.0.1"}]
    assert mock["user"] == "65534:65534" and mock["read_only"] is True and mock["cap_drop"] == ["ALL"]
    assert mock["security_opt"] == ["no-new-privileges:true"]
    assert "/health" in " ".join(mock["healthcheck"]["test"])
    assert mock["environment"]["DTRACK_MOCK_PORT"] == str(DTRACK_CONTAINER_PORT)
    assert mock["environment"]["DTRACK_MOCK_STATUS"] == "${E2E_DTRACK_MOCK_STATUS:-200}"
    assert f"http://{DTRACK_SERVICE}:{DTRACK_CONTAINER_PORT}" == DTRACK_INTERNAL_URL
    assert "dtrack-mock" not in compose["services"]["webapp"].get("depends_on", {})  # optional: never a dependency


def test_dtrack_mock_resource_is_package_data() -> None:
    """resources/dtrack_mock.py ships with the package (pyproject includes resources/*) and runs on the stdlib only."""
    source = read_dtrack_mock()
    assert (files("otterdog_e2e") / "resources" / DTRACK_MOCK_RESOURCE).is_file()
    imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
    assert imports <= {
        "__future__",
        "base64",
        "binascii",
        "json",
        "logging",
        "os",
        "signal",
        "threading",
        "uuid",
        "datetime",
        "http",
        "typing",
        "urllib",
    }, imports


# --- hypercorn -----------------------------------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("variables", "workers", "loglevel"), [({}, 1, "info"), ({"workers": 3, "loglevel": "debug"}, 3, "debug")]
)
def test_hypercorn_template(variables: dict[str, Any], workers: int, loglevel: str) -> None:
    """The rendered hypercorn config is valid TOML binding 0.0.0.0:5000 with access logs on stdout."""
    env = jinja2.Environment(undefined=jinja2.StrictUndefined)  # noqa: S701 - TOML, not HTML
    config = tomllib.loads(env.from_string(read_resource("hypercorn.toml.j2")).render(**variables))
    assert config["bind"] == "0.0.0.0:5000"
    assert config["workers"] == workers
    assert config["accesslog"] == "-"
    assert config["loglevel"] == loglevel
