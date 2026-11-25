# Benachrichtigungen

Grundsatz: **Erfolg ist still, Fehler sind laut.** QuietBoard meldet sich bei Ausfällen sofort – und sonst einmal am Tag mit der Morgenmeldung.

## Wann wird gemeldet?

| Ereignis | Quelle |
| --- | --- |
| Host offline (5 min), Disk > 90 %, RAM > 95 % | Beszel-Alarme (automatisch eingerichtet) |
| Job fehlt oder meldet Fehler (Prio kritisch/normal) | Healthchecks → QuietBoard |
| Security-Updates länger als 48 h offen | QuietBoard |
| Proxmox-Fehler ohne passenden Check, Meldungen mit Fehlerwörtern | Ingest |
| **Morgenmeldung** zur eingestellten Uhrzeit | QuietBoard |

Gleiche Meldungen werden 30 Minuten lang zusammengefasst.

## Kanäle

Einstellen unter **System → Benachrichtigungen**; jeder Kanal hat „Test senden“.

### Web Push (Handy, Desktop)

Braucht **HTTPS** ([Netzwerk](install/network.md)). Auf dem iPhone die Seite in Safari öffnen, *Teilen → Zum Home-Bildschirm*, die App von dort starten und unter System „Aktivieren“ tippen. Auf Android/Desktop genügt der Browser.

### Mail

SMTP-Server in `~/quietboard/.env` eintragen – derselbe Block versorgt auch Healthchecks:

```ini
SMTP_HOST=mail.example.org
SMTP_PORT=587          # 465 = SSL, 587 = STARTTLS
SMTP_TLS=True
SMTP_USER=quietboard@example.org
SMTP_PASSWORD=…
SMTP_FROM=quietboard@example.org
```

`docker compose up -d`, dann unter System die Empfänger eintragen (Standard: die Adresse des ersten Admins) und „Test senden“.

### Signal (optional)

Eigener Container im Profil `signal` mit einer eigenen Nummer (nicht die deines Handys – die Nummer wird ein eigenes Signal-Konto):

1. `docker compose --profile signal up -d`
2. CAPTCHA lösen: [signalcaptchas.org/registration/generate.html](https://signalcaptchas.org/registration/generate.html), Link hinter „Open Signal“ kopieren (`signalcaptcha://…`).
3. Registrieren und Code bestätigen:
   ```bash
   docker compose exec signal-api curl -s -X POST -H 'Content-Type: application/json' \
     -d '{"captcha":"signalcaptcha://…"}' http://localhost:8080/v1/register/+49…
   docker compose exec signal-api curl -s -X POST http://localhost:8080/v1/register/+49…/verify/123456
   ```
4. In `.env`: `SIGNAL_NUMBER=+49…` und `SIGNAL_RECIPIENT=` (eigene Nummer oder `group.…`), `docker compose up -d`.

### Morgenmeldung

Uhrzeit unter System → Benachrichtigungen. Gesendet wird in einem Fenster von zwei Stunden nach der Uhrzeit (falls der Server gerade neu startet), höchstens einmal am Tag – nach einer Installation am Abend kommt also nicht sofort eine „Morgenmeldung“.

```text
☀️ Homelab 07:00 – alles grün
Jobs 12/12 · Hosts 6/6
Updates: 2 Hosts · 7 Pakete · Security 1
```

## Beszel und Healthchecks direkt

Beide behalten ihre eigenen Benachrichtigungen. Healthchecks mailt bei Check-Alarmen über die Integration „E-Mail“ selbst – so kommen Alarme auch an, wenn QuietBoard einmal steht. Beszel meldet an QuietBoard (Webhook); eigene Webhooks in Beszel bleiben erhalten.
