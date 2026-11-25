# Installation

QuietBoard läuft als Docker-Compose-Stack auf einem Linux-Server: einem kleinen VPS, einer VM oder einem Mini-PC im Homelab.

## Voraussetzungen

| | Minimum | Empfohlen |
| --- | --- | --- |
| System | Debian 12/13 oder Ubuntu 22.04+ (andere Linux-Systeme mit Docker gehen auch) | Debian 13 |
| CPU / RAM | 1 vCPU / 1 GB | 2 vCPU / 2 GB |
| Disk | 10 GB frei | 20 GB |
| Software | Docker Engine mit Compose-Plugin, `curl`, `openssl` | – |

Gemessen auf einer 2-GB-VM ohne Swap: Der ganze Stack braucht etwa 330 MB (Healthchecks ≈ 270 MB, App ≈ 70 MB, Beszel ≈ 15 MB); mit Signal kommen ≈ 180 MB dazu.

Docker installieren (falls noch nicht vorhanden): [docs.docker.com/engine/install](https://docs.docker.com/engine/install/). Danach den eigenen Benutzer in die Gruppe `docker` aufnehmen (`sudo usermod -aG docker $USER`, neu anmelden).

## Installation mit einem Befehl

```bash
curl -fsSL https://github.com/A13nka/quietboard/releases/latest/download/install.sh | ADMIN_EMAIL=du@example.org bash
```

Das Skript

1. legt `~/quietboard` an und lädt `compose.yaml`,
2. erzeugt `.env` mit allen Secrets (Rechte 600) und erkennt die IP-Adresse des Servers,
3. startet die Dienste – Healthchecks und Beszel richten sich dabei selbst ein,
4. zeigt die Adressen, den **Einrichtungscode** und den Befehl zum Anbinden weiterer Hosts.

```text
QuietBoard läuft.
  App           http://192.0.2.10:8088   → Einrichtungscode: K7QM-3XPA (Admin-Konto anlegen)
  Healthchecks  http://192.0.2.10:8000
  Beszel        http://192.0.2.10:8090
  Login für Healthchecks und Beszel: du@example.org, Passwort: grep ADMIN_PASSWORD ~/quietboard/.env

Host anbinden – auf jedem Host ausführen, auch auf diesem Server (als root oder Benutzer mit sudo):
  curl -fsSL -H "Authorization: Bearer …" http://192.0.2.10:8088/api/install/host.sh | bash
```

Optionen per Umgebung vor `bash`: `QB_VERSION=v0.1.0` (bestimmte Version), `PUBLIC_HOST=status.example.org` (Adresse, unter der Hosts den Server erreichen), `TZ=Europe/Berlin`, `SITE_NAME=Homelab`, `QB_DIR=/opt/quietboard`.

## Erste Schritte nach der Installation

1. **App öffnen** (`http://<server>:8088`) und mit dem Einrichtungscode das Admin-Konto anlegen. Der Code steht auch im Log: `docker compose logs status | grep Einrichtungscode`.
2. **System → Host hinzufügen:** den angezeigten Befehl auf jedem Host ausführen – auch auf dem quietboard-Server selbst. Nach wenigen Sekunden erscheint der Host unter „Hosts“.
3. **System → Benachrichtigungen:** Mail-Empfänger und Uhrzeit der Morgenmeldung prüfen, „Test senden“. Für Mail muss in `.env` ein SMTP-Server stehen ([Benachrichtigungen](../notifications.md)).
4. **Auf dem Handy:** App im Browser öffnen, zum Home-Bildschirm hinzufügen, unter System „Mitteilungen aktivieren“ (braucht HTTPS, siehe [Netzwerk](network.md)).
5. **Jobs** (Backups, Skripte) überwachen: [Jobs und Checks](../jobs.md).

## Aus dem Release-Paket

Wer nichts per `curl | bash` ausführen möchte: unter [Releases](https://github.com/A13nka/quietboard/releases) `quietboard-vX.Y.Z.tar.gz` und `SHA256SUMS` laden, prüfen, entpacken, starten:

```bash
sha256sum -c SHA256SUMS --ignore-missing
tar xzf quietboard-v0.1.1.tar.gz && cd quietboard-v0.1.1
ADMIN_EMAIL=du@example.org ./install.sh
```

## Solange das Repository privat ist

GitHub liefert Dateien und Images privater Repositories nur mit Anmeldung aus – `curl … | bash` und `docker pull` scheitern dann. So geht es trotzdem:

1. **Token für Images** anlegen: github.com → Settings → Developer settings → Personal access tokens → *Tokens (classic)* → nur `read:packages`.
2. **Paket auf den Server bringen** (auf dem eigenen Rechner, mit angemeldetem `gh`):
   ```bash
   gh release download v0.1.1 -R A13nka/quietboard -p 'quietboard-v0.1.1.tar.gz'
   scp quietboard-v0.1.1.tar.gz <benutzer>@<server>:
   ```
3. **Auf dem Server** einmal bei GHCR anmelden und installieren:
   ```bash
   docker login ghcr.io -u <github-name>        # Passwort = Token aus Schritt 1
   tar xzf quietboard-v0.1.1.tar.gz && cd quietboard-v0.1.1
   ADMIN_EMAIL=du@example.org ./install.sh
   ```

Hosts anbinden funktioniert danach normal: Der Host-Installer kommt von deinem quietboard-Server, der Beszel-Agent von den öffentlichen Beszel-Releases.

## Weiter

- [Netzwerk und HTTPS](network.md) · [Aktualisieren und Versionen](update.md) · [Sicherung und Deinstallation](backup.md)
