# Bestehende Installation übernehmen

Wer Healthchecks und Beszel schon betreibt, kann QuietBoard darüber setzen, ohne neu anzufangen: Checks, Verlauf, Hosts und Agents bleiben, auf den Hosts ändert sich nichts. Voraussetzung: dieselben Versionen wie in QuietBoards `compose.yaml` (derzeit Healthchecks **v5.0.3**, Beszel **0.21.2**) – sonst zuerst die alte Installation auf diese Versionen bringen.

## 1. `.env` anlegen

Im neuen Ordner (z. B. `~/quietboard`) einmal `install.sh` laufen lassen ist hier **nicht** der richtige Weg, weil es sofort startet. Stattdessen die Dateien holen und `.env` von Hand vorbereiten:

```bash
mkdir -p ~/quietboard/config && cd ~/quietboard
V=$(curl -fsSL https://api.github.com/repos/A13nka/quietboard/releases/latest | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
for f in compose.yaml .env.example generate-env.sh; do curl -fsSLO "https://raw.githubusercontent.com/A13nka/quietboard/$V/$f"; done
chmod +x generate-env.sh
```

In `.env` die Werte der alten Installation eintragen, **bevor** `generate-env.sh` läuft (es füllt nur leere Felder):

| Variable | Wert |
| --- | --- |
| `HC_SECRET_KEY` | `SECRET_KEY` der alten Healthchecks-Installation – **unbedingt gleich**, sonst gelten Sitzungen und Signaturen nicht mehr |
| `HC_API_KEY`, `HC_PING_KEY` | API-Key (Schreibrecht) und Ping-Key des Projekts. Sind beide gesetzt, ändert QuietBoard an Healthchecks **nichts** (keine neuen Keys, kein neues Passwort) |
| `INGEST_TOKEN` | Token, mit dem Hosts bisher Update-Berichte schicken (falls vorhanden) – sonst neu |
| `HC_PUBLIC_URL`, `HC_PING_ENDPOINT`, `BESZEL_PUBLIC_URL` | die bisherigen Adressen (`SITE_ROOT`, `PING_ENDPOINT`, `APP_URL`) |
| `HC_EXTRA_HOSTS` | weitere Namen/IPs aus dem alten `ALLOWED_HOSTS` |
| `SMTP_*` | die alten `EMAIL_*`-Werte von Healthchecks |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | Dein bisheriger Beszel-Login (empfohlen) **oder** eine neue Adresse. QuietBoard nutzt diesen Beszel-Admin für den Nur-Lesen-Zugang, den Agent-Token neuer Hosts und die Standard-Alarme. Bei der bisherigen Adresse gilt danach `ADMIN_PASSWORD` als Beszel-Passwort – trägst du dort dein jetziges Passwort ein, ändert sich nichts. Beszel-Mails dieses Kontos übernimmt QuietBoard (Mail-Kanal) |
| `BESZEL_APP_USER`, `BESZEL_APP_PASS` | **leer lassen** – QuietBoard richtet seinen Zugang selbst ein |
| `SIGNAL_*`, `TUNNEL_TOKEN`, `ACCESS_*`, `VAPID_PRIVATE_KEY`, `PBS_TARGETS` | wie bisher, falls genutzt (gleicher VAPID-Schlüssel = vorhandene Push-Abos bleiben) |

Danach `./generate-env.sh` für die übrigen Secrets.

## 2. Daten übernehmen

Mit einer `compose.override.yaml` zeigt QuietBoard auf die vorhandenen Ordner (Pfade anpassen):

```yaml
volumes:
  healthchecks-data: { driver: local, driver_opts: { type: none, o: bind, device: /pfad/alt/data/healthchecks } }
  beszel-data:       { driver: local, driver_opts: { type: none, o: bind, device: /pfad/alt/data/beszel } }
  signal-data:       { driver: local, driver_opts: { type: none, o: bind, device: /pfad/alt/data/signal } }
```

Ordner einer früheren Status-App mit `updates.json`, `events.json` usw. lassen sich als `status-data` genauso übernehmen. Die Rechte müssen passen: Healthchecks UID 999, QuietBoard UID 10001.

`checks.yaml` (falls vorhanden) nach `~/quietboard/config/` kopieren.

## 3. Umschalten

```bash
cd /pfad/alt && docker compose stop          # alte Container anhalten (Ports frei, Daten bleiben)
cd ~/quietboard && docker compose up -d
docker compose logs healthchecks-init        # muss „keine Änderung (Übernahme)“ melden
```

Prüfen: In der App erscheinen alle Checks und Hosts, *System* zeigt Healthchecks und Beszel verbunden. Hosts, `hc`-Pings und Agents laufen unverändert weiter.

Der App-Container ist im Docker-Netz auch unter dem Namen `status-app` erreichbar. Tunnel-Ziele und Beszel-Webhooks einer Vorgänger-App mit diesem Namen funktionieren also weiter; einen zweiten Webhook zur App legt QuietBoard dann nicht an.

**Zurück:** `docker compose down` in `~/quietboard`, dann die alte Installation wieder starten – die Daten bleiben kompatibel. Vorher trotzdem [sichern](backup.md).
