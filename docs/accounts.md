# Konten und Anmeldung

Kein Dienst ohne Login: QuietBoard zeigt ohne Anmeldung nichts an.

## Erster Start

Beim ersten Start gibt es noch kein Konto. Die App schreibt einen **Einrichtungscode** ins Log (und `install.sh` zeigt ihn an). Wer ihn kennt, legt unter `http://<server>:8088` das erste Admin-Konto an:

```bash
docker compose logs status | grep Einrichtungscode
```

Der Code gilt, bis das erste Konto existiert; nach einem Neustart gibt es einen neuen.

## Rollen

| Rolle | Darf |
| --- | --- |
| **Admin** | alles: Hosts anbinden, Benutzer, Einstellungen, Checks pausieren, Morgenmeldung testen |
| **Betrachter** | alles sehen, eigenes Passwort ändern, Push auf eigenen Geräten |

Benutzer anlegen unter **System → Benutzer**. Passwörter: mindestens 10 Zeichen, gespeichert mit scrypt. Nach 10 Fehlversuchen von einer Adresse (bzw. 20 für ein Konto insgesamt) ist die Anmeldung für 15 Minuten gesperrt. Wer sein Passwort ändert, wird auf allen anderen Geräten abgemeldet. Sitzungen gelten 30 Tage.

Healthchecks und Beszel haben eigene Admin-Zugänge: `ADMIN_EMAIL` und `ADMIN_PASSWORD` aus `.env`.

## Sprache

Die Oberfläche gibt es auf Deutsch und Englisch. Sie folgt der Sprache des Browsers; umstellen lässt sie sich unter **System → Konto → Sprache** (gilt für diesen Browser).

Meldungen, die der Server erzeugt – Morgenmeldung, Push, Mail, Signal und „Braucht Aufmerksamkeit“ –, haben eine eigene Einstellung: **System → Benachrichtigungen → Sprache der Meldungen** (Admins; Standard Deutsch, vorbelegbar mit `LANGUAGE=en` in `.env`).

## API-Tokens für eigene Skripte

Unter **System → API-Tokens** legt jeder Benutzer Tokens für eigene Skripte an (z. B. für Home Assistant oder ein Dashboard). Ein Token hat dieselben Rechte wie das Konto – ein Token eines Betrachters kann also nur lesen.

```bash
curl -H "Authorization: Bearer qb_…" http://<server>:8088/api/state
```

Der Token wird nur einmal angezeigt; gespeichert ist nur eine Prüfsumme. Die Liste zeigt, wann ein Token zuletzt benutzt wurde. *Widerrufen* sperrt ihn sofort. Admins sehen und widerrufen auch die Tokens anderer Benutzer. Wird ein Benutzer gelöscht, gelten seine Tokens nicht mehr.

Nicht zu verwechseln mit dem Zugangsschlüssel für Hosts (`INGEST_TOKEN`), mit dem Hosts ihre Berichte schicken.

## Passwort vergessen, Admin ausgesperrt

Die Notfall-CLI im Container hilft:

```bash
cd ~/quietboard
docker compose exec status python -m tools.cli users
docker compose exec status python -m tools.cli passwd du@example.org     # neues Passwort wird erzeugt
docker compose exec status python -m tools.cli role du@example.org admin
docker compose exec status python -m tools.cli add neu@example.org --role admin
```

## Cloudflare Access (optional)

Steht QuietBoard hinter Cloudflare Access, kann Access die Anmeldung übernehmen: `ACCESS_TEAM` (Team-Name) und `ACCESS_AUD` (Application Audience Tag) in `.env` setzen. Wer durch Access kommt, ist Admin. Lokale Konten funktionieren weiterhin.
