# QuietBoard – Entwicklungsbefehle.  make help
SHELL := /bin/bash
DEV   := docker compose -f compose.yaml -f dev/compose.dev.yaml
# venv und Caches liegen bewusst außerhalb des Projektordners (sauberer Checkout, kein Sync von Rechnerabhängigem).
CACHE := $(HOME)/.cache/quietboard
VENV  := $(CACHE)/venv
PY    := $(VENV)/bin/python
export PYTHONPYCACHEPREFIX := $(CACHE)/pycache
export RUFF_CACHE_DIR      := $(CACHE)/ruff

.PHONY: help setup env notices configs dist release dev dev-fakehost down logs test lint check-private e2e screenshots

help:   ## Diese Übersicht
	@grep -hE '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-15s %s\n", $$1, $$2}'

setup:  ## venv + Entwicklungswerkzeuge + pre-commit (pro Rechner einmal)
	python3 -m venv $(VENV)
	$(PY) -m pip install -q -r requirements-dev.txt
	$(VENV)/bin/pre-commit install
	@echo "fertig – weiter mit: make dev"

env:    ## .env anlegen und Secrets erzeugen (nur lokal, nie committen)
	./generate-env.sh
	@grep -q '^BIND_ADDR=' .env || echo 'BIND_ADDR=127.0.0.1' >> .env
	@grep -qE '^ADMIN_EMAIL=.+' .env || { sed -i.bak '/^ADMIN_EMAIL=$$/d' .env && rm -f .env.bak && echo 'ADMIN_EMAIL=admin@example.org' >> .env; }

dev: env  ## App lokal mit Beispieldaten starten → http://localhost:8088
	$(DEV) up -d --build
	@echo "→ http://localhost:8088   (Healthchecks :8000, Beszel :8090)"

dev-fakehost: env  ## zusätzlich einen simulierten Host starten
	$(DEV) --profile fakehost up -d --build

down:   ## lokale Umgebung stoppen (Daten bleiben in Docker-Volumes)
	$(DEV) --profile fakehost down

logs:   ## Logs der App
	$(DEV) logs -f status

lock:   ## requirements.lock aus requirements.txt neu erzeugen (alle Abhängigkeiten fest, mit Prüfsummen)
	scripts/lock.sh

test:   ## Unit- und API-Tests
	$(PY) -m pytest -q -p no:cacheprovider

lint:   ## ruff + shellcheck (per Docker, feste Version)
	$(VENV)/bin/ruff check .
	$(VENV)/bin/ruff format --check .
	docker run --rm -e LANG=C.UTF-8 -v "$(CURDIR):/mnt" -w /mnt koalaman/shellcheck:v0.11.0 install.sh hosts/*.sh hosts/hc hosts/updates-report generate-env.sh dev/fakehost/run.sh scripts/*.sh $(wildcard deploy/*/*.sh)

check-private: ## persönliche Werte (.private-patterns, nicht im Repo) im Repo suchen
	@scripts/check-private.sh

notices: ## THIRD_PARTY_NOTICES.md neu erzeugen (vor jedem Release)
	scripts/gen-notices.sh

configs: ## Skripte aus bootstrap/ in compose.yaml einbetten
	python3 scripts/sync_compose_configs.py

dist:   ## Release-Dateien lokal bauen: make dist VERSION=0.1.0 (Paket, install.sh, compose.yaml, SHA256SUMS)
	scripts/make-dist.sh $(VERSION)

release: ## Release erstellen: make release VERSION=0.1.0 (Tag → Image vX.Y.Z, vX.Y, vX, latest)
	scripts/release.sh $(VERSION)

screenshots: ## README-Screenshots aus dem laufenden Demo-Modus (make dev) neu erzeugen
	node scripts/screenshots.mjs

e2e:    ## frische Installation in Wegwerf-Projekt hochfahren und prüfen (wie CI)
	scripts/e2e.sh

# Optionale, nicht veröffentlichte Ziele (z. B. eigene Testumgebung)
-include deploy/*/local.mk
