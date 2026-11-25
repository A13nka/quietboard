# Reference: API

Every function of the interface goes through this API. Base: `http://<server>:8088`.

## Authentication

| Kind | For | How |
| --- | --- | --- |
| Session | browser, your own scripts | `POST /api/auth/login` `{"email","password"}` → cookie `qb_session`. Writing calls need a matching `Origin` header. |
| API token | your own scripts | `Authorization: Bearer qb_…` – created under System → API tokens, rights of the account, no `Origin` needed |
| Ingest token | hosts, webhooks | `Authorization: Bearer <INGEST_TOKEN>` (alternatively `X-Token` or `?token=`) |

## For hosts and webhooks (ingest token)

| Method, path | Body | Purpose |
| --- | --- | --- |
| `POST /api/ingest/updates` | `{"host","kind":"apt\|dsm\|docker\|…","items":[{"pkg","from","to","security"}],"reboot":bool}` | update report of a host (empty list = no updates) |
| `POST /api/ingest/notify` | `{"title","message","prio":"kritisch\|normal\|info","source"}` or just `{"message"}` | generic message; without `prio`, error words decide |
| `POST /api/ingest/pve?source=pve\|pbs&host=<name>` | PVE/PBS webhook | event → matching job or message |
| `POST /api/ingest/beszel` | Beszel webhook | only from the Beszel container or with token |
| `GET /api/install/host.sh` | – | filled-in host installer |

Priorities in the API keep their German names: `kritisch` (critical), `normal`, `info`.

## For signed-in users

| Method, path | Role | Purpose |
| --- | --- | --- |
| `GET /api/state` | all | overall state: summary, attention, checks, hosts, updates, messages (`?fresh=1`: poll first, at most every 10 s) |
| `GET /api/check/{uuid}/log` | all | last run of a check with log |
| `GET /api/settings` · `PUT /api/settings` | all · admin | `mail_to`, `digest_time`, `language` (`de`/`en`) |
| `POST /api/notify/test` | admin (push: all) | `{"channel":"mail\|push\|signal"}` |
| `POST /api/digest/test` | admin | send the morning digest now |
| `POST /api/checks` | admin | create a job: `{"host","job","mode":"cron\|period","schedule"\|"period","grace","prio","typ","src":"hc\|url\|pve\|pbs","ev","job_id","ds","desc"}` |
| `GET` · `PUT` · `DELETE /api/checks/{uuid}` | admin | read a job (form values) · change · delete |
| `GET /api/config/export` | admin | jobs and host settings as YAML (`checks.yaml` format) |
| `POST /api/config/import` | admin | `{"yaml": "...", "dry": true}` – preview or create/update, never deletes |
| `PUT /api/hosts/{name}/settings` · `DELETE /api/hosts/{name}` | admin | `{"always_on": bool, "links": [{"label","url"}]}` · remove a host (Beszel, updates, settings) |
| `GET/POST /api/tokens` · `DELETE /api/tokens/{id}` | all | own API tokens (admins see all) |
| `GET /api/jobs/help` | admin | ping address, webhook address, token, known hosts (for guides) |
| `POST /api/checks/{uuid}/pause\|resume` | admin | pause/resume a check |
| `POST /api/checks/{uuid}/prio` | admin | `{"prio":"kritisch\|normal\|info"}` |
| `GET /api/hosts/install-command` · `GET /api/agent` | admin | host command · agent values (KEY, TOKEN, HUB_URL) |
| `GET/POST /api/users` · `PATCH/DELETE /api/users/{id}` | admin | manage users |
| `GET /api/system` | all | version, state of the engines |
| `POST /api/auth/password` · `POST /api/auth/logout` | all | own password · sign out |
| `GET /healthz` | no sign-in | 200 as long as the app polls data (for external watchers) |

## Example: a message from a script

```bash
curl -fsS -H "Authorization: Bearer $INGEST_TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"Backup failed","message":"rc=2","prio":"kritisch","source":"nas"}' \
  http://<server>:8088/api/ingest/notify
```
