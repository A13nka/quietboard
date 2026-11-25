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

Benutzer anlegen unter **System → Benutzer**. Passwörter: mindestens 10 Zeichen, gespeichert mit scrypt. Nach 10 Fehlversuchen ist die Anmeldung für 15 Minuten gesperrt. Sitzungen gelten 30 Tage.

Healthchecks und Beszel haben eigene Admin-Zugänge: `ADMIN_EMAIL` und `ADMIN_PASSWORD` aus `.env`.

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
