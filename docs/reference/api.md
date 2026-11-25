# Referenz: API

Alle Funktionen der Oberfläche laufen über diese API. Basis: `http://<server>:8088`.

## Anmeldung

| Art | Für | Wie |
| --- | --- | --- |
| Sitzung | Browser, eigene Skripte | `POST /api/auth/login` `{"email","password"}` → Cookie `qb_session`. Schreibende Aufrufe brauchen einen passenden `Origin`-Header. |
| Ingest-Token | Hosts, Webhooks | `Authorization: Bearer <INGEST_TOKEN>` (alternativ `X-Token` oder `?token=`) |

## Für Hosts und Webhooks (Ingest-Token)

| Methode, Pfad | Body | Zweck |
| --- | --- | --- |
| `POST /api/ingest/updates` | `{"host","kind":"apt\|dsm\|docker\|…","items":[{"pkg","from","to","security"}],"reboot":bool}` | Update-Bericht eines Hosts (leere Liste = keine Updates) |
| `POST /api/ingest/notify` | `{"title","message","prio":"kritisch\|normal\|info","source"}` oder nur `{"message"}` | generische Meldung; ohne `prio` entscheiden Fehlerwörter |
| `POST /api/ingest/pve?source=pve\|pbs&host=<name>` | PVE/PBS-Webhook | Ereignis → passender Check oder Meldung |
| `POST /api/ingest/beszel` | Beszel-Webhook | nur vom Beszel-Container oder mit Token |
| `GET /api/install/host.sh` | – | fertig ausgefüllter Host-Installer |

## Für angemeldete Benutzer

| Methode, Pfad | Rolle | Zweck |
| --- | --- | --- |
| `GET /api/state` | alle | Gesamtzustand: Zusammenfassung, Aufmerksamkeit, Checks, Hosts, Updates, Meldungen (`?fresh=1`: vorher neu abfragen, höchstens alle 10 s) |
| `GET /api/check/{uuid}/log` | alle | letzter Lauf eines Checks mit Log |
| `GET /api/settings` · `PUT /api/settings` | alle · Admin | `mail_to`, `digest_time` |
| `POST /api/notify/test` | Admin (Push: alle) | `{"channel":"mail\|push\|signal"}` |
| `POST /api/digest/test` | Admin | Morgenmeldung jetzt senden |
| `POST /api/checks` | Admin | Job anlegen: `{"host","job","mode":"cron\|period","schedule"\|"period","grace","prio","typ","src":"hc\|url\|pve\|pbs","ev","job_id","ds","desc"}` |
| `GET` · `PUT` · `DELETE /api/checks/{uuid}` | Admin | Job lesen (Formularwerte) · ändern · löschen |
| `GET /api/jobs/help` | Admin | Ping-Adresse, Webhook-Adresse, Token, bekannte Hosts (für Anleitungen) |
| `POST /api/checks/{uuid}/pause\|resume` | Admin | Check pausieren/fortsetzen |
| `POST /api/checks/{uuid}/prio` | Admin | `{"prio":"kritisch\|normal\|info"}` |
| `GET /api/hosts/install-command` · `GET /api/agent` | Admin | Host-Befehl · Agent-Werte (KEY, TOKEN, HUB_URL) |
| `GET/POST /api/users` · `PATCH/DELETE /api/users/{id}` | Admin | Benutzer verwalten |
| `GET /api/system` | alle | Version, Zustand der Motoren |
| `POST /api/auth/password` · `POST /api/auth/logout` | alle | eigenes Passwort · abmelden |
| `GET /healthz` | ohne Anmeldung | 200, solange die App Daten abruft (für externe Wächter) |

## Beispiel: Meldung aus einem Skript

```bash
curl -fsS -H "Authorization: Bearer $INGEST_TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"Backup fehlgeschlagen","message":"rc=2","prio":"kritisch","source":"nas"}' \
  http://<server>:8088/api/ingest/notify
```
