# otterdog-e2e developer entry points: `make help` lists the targets and the variables they read.
# Every harness target runs .venv/bin/otterdog-e2e (create the venv with `make init`).
#
#   make offline                          offline tier of release:latest (no GitHub)
#   make cli TARGET=free                  live CLI tier on targets/free.yaml
#   make web-ui TARGET=free               web-UI tier (bot login; docs/web-ui-testing.md)
#   make one SCENARIO='cli.repo.*' TARGET=free SUT=branch:main
#   make lint-scenarios                   every live scenario step validated offline (before submitting a scenario)
#   make inject ARGS='--fragment repositories=scenarios/fragments/repo-basic.jsonnet --print'
#   make pr PR=792 SHA=<40-hex> TARGET=free
#   make bootstrap TARGET=free APPLY=1
#   make docs                             strict build of the documentation site (poetry install --with docs)

SHELL := /bin/bash
.DEFAULT_GOAL := help

# The user's real otterdog configuration root must never reach anything started from here (the harness also drops
# every OTTER* variable from the environment of the processes it starts).
unexport OTTERDOG_CONFIG_ROOT

VENV ?= .venv
E2E := $(VENV)/bin/otterdog-e2e
PYTHON := $(VENV)/bin/python
POETRY ?= poetry
# Python files outside the package: the MkDocs hooks of the documentation site
HOOKS := docs_hooks.py

TARGET ?= $(E2E_TARGET)
SUT ?= $(or $(E2E_SUT),release:latest)
BASE_SUT ?= $(E2E_BASE_SUT)
SCENARIO ?=
SUITE ?=
ARGS ?=
APPLY ?=
OLDER_THAN ?= 6h
RUN_ID ?=
FORCE_TAKEOVER ?=
PR ?=
SHA ?=
FORWARD_TO ?= http://127.0.0.1:5000/github-webhook/receive
SINCE ?= 10m
KEEP ?= 3
ARTIFACTS ?= $(or $(E2E_ARTIFACTS),artifacts)
# newest run directory below the artifacts root (evaluated only by the targets that use it)
RUN ?= $(shell ls -1td "$(ARTIFACTS)"/*/ 2>/dev/null | head -n 1)

.PHONY: help init unit lint format typecheck check offline lint-scenarios cli webhooks webapp web-ui enterprise \
	differential e2e one inject pr doctor bootstrap janitor relay report scrub cache-prune sut docs docs-serve clean \
	require-target require-base require-scenario require-pr require-docs

help: ## Show this help
	@echo "Targets:"
	@grep -hE '^[a-z][a-z0-9-]*:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-14s %s\n", $$1, $$2}'
	@echo
	@echo "Variables: TARGET=$(TARGET) SUT=$(SUT) BASE_SUT=$(BASE_SUT) SCENARIO=<glob> SUITE=<tiers> ARGS=<pytest args>"
	@echo "           APPLY=1 OLDER_THAN=$(OLDER_THAN) RUN_ID=<id> PR=<n> SHA=<40-hex> RUN=<artifacts dir> KEEP=$(KEEP)"

init: ## Create .venv with the harness and its dev tools (poetry install --with dev)
	$(POETRY) install --with dev

unit: ## Unit tier: harness self-tests (no network, no docker)
	$(PYTHON) -m pytest -q -p no:cacheprovider tests/unit $(ARGS)

lint: ## ruff check and ruff format --check
	$(VENV)/bin/ruff check src tests $(HOOKS)
	$(VENV)/bin/ruff format --check src tests $(HOOKS)

format: ## ruff format and safe ruff fixes
	$(VENV)/bin/ruff format src tests $(HOOKS)
	$(VENV)/bin/ruff check --fix src tests $(HOOKS)

typecheck: ## mypy on src (and the documentation hooks)
	$(VENV)/bin/mypy src $(HOOKS)

check: lint typecheck unit ## lint + typecheck + unit

offline: ## Offline tier of SUT (no GitHub; docker for the webapp part)
	$(E2E) run --suite offline --sut "$(SUT)" $(ARGS)

lint-scenarios: ## Offline lint of every live scenario step with SUT (validate --local; no GitHub, no docker)
	$(E2E) run --suite offline --sut "$(SUT)" -k lint $(ARGS)

cli: require-target ## Live CLI tier of SUT on TARGET
	$(E2E) run --target "$(TARGET)" --sut "$(SUT)" --suite cli $(ARGS)

webhooks: require-target ## Live webhooks tier of SUT on TARGET
	$(E2E) run --target "$(TARGET)" --sut "$(SUT)" --suite webhooks $(ARGS)

webapp: require-target ## Webapp tier of SUT on TARGET (GitHub App + docker, or E2E_TRANSPORT=external)
	$(E2E) run --target "$(TARGET)" --sut "$(SUT)" --suite webapp $(ARGS)

web-ui: require-target ## Web-UI tier of SUT on TARGET: otterdog logs in as the admin bot (web credentials, trusted SUT)
	$(E2E) run --target "$(TARGET)" --sut "$(SUT)" --suite web_ui --allow-web-ui $(ARGS)

enterprise: require-target ## Enterprise-only tier of SUT on TARGET (plan enterprise)
	$(E2E) run --target "$(TARGET)" --sut "$(SUT)" --suite enterprise $(ARGS)

differential: require-base ## Offline (+ live with TARGET) differential of SUT against BASE_SUT
	$(E2E) run $(if $(TARGET),--target "$(TARGET)") --sut "$(SUT)" --base-sut "$(BASE_SUT)" --suite offline,differential $(ARGS)

e2e: ## Every tier of SUT (live tiers are skipped without TARGET; differential with BASE_SUT)
	$(E2E) run $(if $(TARGET),--target "$(TARGET)") --sut "$(SUT)" $(if $(BASE_SUT),--base-sut "$(BASE_SUT)") $(if $(SUITE),--suite "$(SUITE)") $(ARGS)

one: require-scenario ## Only the scenarios matching SCENARIO=<glob[,glob]> (live ones need TARGET)
	$(E2E) run $(if $(TARGET),--target "$(TARGET)") --sut "$(SUT)" $(if $(BASE_SUT),--base-sut "$(BASE_SUT)") --scenario "$(SCENARIO)" $(if $(SUITE),--suite "$(SUITE)") $(ARGS)

inject: ## Try jsonnet files with SUT without a scenario: ARGS='--fragment KIND=FILE ...' (offline unless TARGET)
	$(E2E) inject $(if $(TARGET),--target "$(TARGET)") --sut "$(SUT)" $(ARGS)

pr: require-pr ## Test otterdog PR=<n> pinned at SHA=<40-hex> (differential vs its base; live tiers with TARGET)
	$(E2E) pr "$(PR)" --sha "$(SHA)" $(if $(TARGET),--target "$(TARGET)") $(if $(SUITE),--suite "$(SUITE)")

doctor: require-target ## Read-only checks of TARGET (environment, identities, org, repos, teams, App, tools)
	$(E2E) doctor --target "$(TARGET)"

bootstrap: require-target ## Prepare TARGET (dry run; APPLY=1 writes the marker, repos, baseline, App checks)
	$(E2E) bootstrap --target "$(TARGET)" $(if $(APPLY),--apply)

janitor: require-target ## Leftovers of runs older than OLDER_THAN (or RUN_ID) on TARGET; APPLY=1 deletes them
	$(E2E) janitor --target "$(TARGET)" --older-than "$(OLDER_THAN)" $(if $(RUN_ID),--run-id "$(RUN_ID)") $(if $(FORCE_TAKEOVER),--force-takeover) $(if $(APPLY),--apply)

relay: require-target ## Forward the App deliveries of TARGET to FORWARD_TO (holds the org lease; Ctrl-C stops)
	$(E2E) relay --target "$(TARGET)" --forward-to "$(FORWARD_TO)" --since "$(SINCE)"

report: ## Print the summary of RUN=<artifacts dir> (default: the newest run)
	$(E2E) report "$(RUN)"

scrub: ## Scrub RUN=<artifacts dir> (exit 1 when a file leaked a secret)
	$(E2E) scrub-artifacts "$(RUN)"

cache-prune: ## Keep only the KEEP newest builds, sources, runs and images in the harness cache
	$(E2E) cache prune --keep "$(KEEP)"

sut: ## Resolve SUT and print it as JSON (label, sha, version, trust)
	$(E2E) sut resolve "$(SUT)"

# Material for MkDocs prints a banner about MkDocs 2 on every build: the docs group pins mkdocs<2
docs: require-docs ## Strict build of the documentation site into site/ (broken links and anchors fail)
	NO_MKDOCS_2_WARNING=true $(VENV)/bin/mkdocs build --strict

docs-serve: require-docs ## Live preview of the documentation site on http://127.0.0.1:8000/otterdog-e2e/
	NO_MKDOCS_2_WARNING=true $(VENV)/bin/mkdocs serve

clean: ## Remove Python caches (never the artifacts nor the harness cache)
	find src tests -name __pycache__ -type d -prune -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache

require-target:
	@test -n "$(TARGET)" || { echo "set TARGET=<name> (targets/<name>.yaml) or export E2E_TARGET" >&2; exit 2; }

require-base:
	@test -n "$(BASE_SUT)" || { echo "set BASE_SUT=<spec> (auto = merge base of SUT)" >&2; exit 2; }

require-scenario:
	@test -n "$(SCENARIO)" || { echo "set SCENARIO=<scenario id glob>" >&2; exit 2; }

require-docs:
	@test -x "$(VENV)/bin/mkdocs" || { echo "install the documentation tools first: $(POETRY) install --with docs" >&2; exit 2; }

require-pr:
	@[[ "$(PR)" =~ ^[0-9]+$$ && "$(SHA)" =~ ^[0-9a-f]{40}$$ ]] || { echo "set PR=<number> SHA=<40-hex head commit>" >&2; exit 2; }
