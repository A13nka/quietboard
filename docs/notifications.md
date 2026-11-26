# Benachrichtigungen

Grundsatz: **Erfolg ist still, Fehler sind laut.** QuietBoard meldet sich bei Ausfällen sofort – und sonst einmal am Tag mit der Morgenmeldung.

## Wann wird gemeldet?

| Ereignis | Quelle |
| --- | --- |
| Host offline (5 min), Disk > 90 %, RAM > 95 % | Beszel-Alarme (automatisch eingerichtet) |
| Job fehlt oder meldet Fehler (Prio kritisch/normal), und wenn er wieder grün ist | QuietBoard (oder Healthchecks, siehe unten) |
| Security-Updates länger als 48 h offen | QuietBoard |
| Proxmox-Fehler ohne passenden Job, Meldungen mit Fehlerwörtern | Ingest |
| Healthchecks oder Beszel länger als 15 Minuten nicht erreichbar | QuietBoard |
| QuietBoard selbst läuft nicht mehr | Healthchecks (Lebenszeichen `quietboard/app`) |
| **Morgenmeldung** zur eingestellten Uhrzeit | QuietBoard |

Dieselbe Meldung (gleiche Quelle, gleicher Zustand) kommt innerhalb von 30 Minuten nur einmal; ein Wechsel – etwa „down“ nach „up“ – kommt immer durch. Das gilt auch über einen Neustart hinweg. Konnte kein Kanal zustellen, versucht QuietBoard es beim nächsten Abruf erneut.

## Job-Alarme: QuietBoard oder Healthchecks

Unter **System → Job-Alarme** legst du fest, wer Ausfälle von Jobs meldet:

- **QuietBoard** (Standard bei neuen Installationen): einheitliche, kurze Meldungen über alle Kanäle oben (Push, Mail, Signal), mehrere Ausfälle eines Abrufs in einer Nachricht. Die Mail-Empfänger aus den Einstellungen gelten auch hier.
- **Healthchecks**: die Integrationen, die in Healthchecks den einzelnen Jobs zugeordnet sind (so verhielt sich QuietBoard bis v0.5). Standard, wenn eine bestehende Healthchecks-Installation übernommen wurde – dort ändert sich nach dem Update nichts.

Beim Wechsel auf QuietBoard bietet die Seite an, die Integrationen von den Jobs zu lösen, damit nichts doppelt kommt. Die Integrationen selbst bleiben in Healthchecks; die bisherige Zuordnung wird gesichert, und der Rückweg zu „Healthchecks“ stellt sie wieder her.

**Lebenszeichen:** QuietBoard legt in Healthchecks den Check `quietboard/app` an und meldet sich dort bei jedem Abruf. Nur dieser Check behält immer die Integrationen von Healthchecks. Steht QuietBoard länger als etwa 15 Minuten, meldet Healthchecks das selbst. In der Jobs-Liste erscheint er nicht, sein Zustand steht unter System.

### So sehen Meldungen aus

```text
🔴 docker01/backup-restic fehlgeschlagen
Exitcode 1 · heute 03:12 · kritisch
Letzte Zeilen:
  ssh: connect to host nas port 22: No route to host
→ https://status.example.org/?c=…
```

```text
🔴 docker01/backup-restic überfällig
Keine Meldung seit gestern 03:04 (Zeitplan 0 3 * * *, Karenz 1h)
```

```text
✅ docker01/backup-restic wieder OK
War 6 h 12 min ausgefallen · Lauf dauerte 14 min
```

Mails enthalten zusätzlich bis zu 30 Logzeilen. Den Exitcode kennt QuietBoard von `hc run` (ab v0.6.0 auf dem Host; ältere `hc` melden nur „Fehler gemeldet“). Der Link erscheint, wenn `PUBLIC_URL` in `.env` gesetzt ist.

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

Beszel meldet an QuietBoard (Webhook); eigene Webhooks in Beszel bleiben erhalten. Healthchecks meldet je nach Einstellung oben über seine Integrationen – mindestens aber den Ausfall von QuietBoard selbst (Lebenszeichen).
