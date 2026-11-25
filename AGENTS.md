# AGENTS.md – rules for coding agents and contributors

QuietBoard: metrics, jobs and updates of a homelab in one calm view; sets itself up. Human-facing guide: [CONTRIBUTING.md](CONTRIBUTING.md).

## Principles
- Success is silent, failures are loud. One morning digest instead of many single messages.
- Engines (Beszel, Healthchecks) and the view (this app) stay separate; if the app fails, the engines keep alerting.
- No service without login. No mandatory external service. One compose file, one `.env`, one command.
- Every GUI action is also possible via API/CLI/YAML. Only necessary containers.

## Coding rules
- Code, identifiers, commit messages: English. The UI is German today; prepare new texts as keys (i18n is coming, `locales/`).
- Every container has a `mem_limit`. Upstream images are pinned to exact versions.
- **No secrets, no personal values** (domains, IPs, hostnames, mail addresses, phone numbers). Examples use `example.org`, `home.arpa`, made-up hosts. gitleaks runs in pre-commit and CI.
- Runtime data only in Docker volumes, never in the project folder. No symlinks.
- venv and caches live in `~/.cache/quietboard` (see Makefile).
- Before every commit: `make lint test`. For changes to compose or ingest also `make e2e`.
- Scripts in `bootstrap/` are embedded in `compose.yaml` – run `make configs` after changing them.

## Workflow
One topic = one branch (`feat/…`, `fix/…`, `docs/…`) = one pull request against `main`. CI (lint, tests, e2e, license check, docs) must be green.

## Commands
`make help` · `make setup` · `make dev` · `make dev-fakehost` · `make test` · `make lint` · `make e2e` · `make configs` · `make release VERSION=…`

## Layout
- `app/` FastAPI app + PWA (`static/`); `app/demo.py` sample data (`DEMO=true`); `app/bootstrap.py` credentials, Beszel setup and alerts; `app/auth.py` accounts, sessions, settings (SQLite)
- `bootstrap/` scripts for `healthchecks-init`, embedded in `compose.yaml`
- `tools/hc_sync.py` checks.yaml → Healthchecks · `tools/keepalive_test.py` connection test against Healthchecks (used by e2e)
- `hosts/` scripts for monitored hosts (`hc`, `updates-report`, security updates, Beszel agent, Synology)
- `config/checks.example.yaml` sample configuration (matches the demo data)
- `dev/fakehost/` simulated host · `scripts/` e2e, release, checks · `docs/` documentation website (MkDocs)
- `docs/decisions/` architecture decisions referenced from code
