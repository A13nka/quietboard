# Sicherung, Umzug, Deinstallation

## Was gesichert werden muss

| Was | Wo | Inhalt |
| --- | --- | --- |
| `.env` | `~/quietboard/.env` | alle Secrets und Einstellungen |
| `config/` | `~/quietboard/config/` | `checks.yaml` |
| Volumes | `quietboard_status-data`, `quietboard_healthchecks-data`, `quietboard_beszel-data`, `quietboard_bootstrap` (+ `quietboard_signal-data`) | Konten, Checks, Verlauf, Zugänge |

## Sichern

Liegen die Daten in Ordnern statt in Volumes, geht es einfacher – siehe [Daten in eigenen Ordnern](storage.md#sichern).

```bash
cd ~/quietboard
docker compose stop
( set -e   # bricht beim ersten Fehler ab – dann nichts löschen, Ausgabe prüfen
  mkdir -p backup
  for v in status-data healthchecks-data beszel-data bootstrap signal-data; do
    docker volume inspect quietboard_$v >/dev/null 2>&1 || continue   # signal-data nur mit Profil signal
    docker run --rm -v quietboard_$v:/v:ro -v "$PWD/backup":/b alpine:3.22 tar czf /b/$v.tgz -C /v .
    docker run --rm -v "$PWD/backup":/b:ro alpine:3.22 tar tzf /b/$v.tgz >/dev/null   # Archiv lesbar?
  done
  cp .env config/checks.yaml backup/
  if [ -f compose.override.yaml ]; then cp compose.override.yaml backup/; fi
  echo "Sicherung vollständig"
)
docker compose start
```

Erst wenn „Sicherung vollständig“ erscheint, ist die Sicherung brauchbar. Ältere Sicherungen erst löschen, wenn die neue
außer Haus angekommen und geprüft ist.

`backup/` enthält danach Secrets – nur verschlüsselt außer Haus lagern (z. B. restic, Borg, Backrest).

## Wiederherstellen / Umzug auf einen neuen Server

1. Auf dem neuen Server einmal `install.sh` ausführen (legt Ordner und Volumes an), dann `docker compose down`.
2. `.env`, `checks.yaml` und – falls vorhanden – `compose.override.yaml` zurückkopieren, Volumes zurückspielen.
   Jedes Archiv wird erst geprüft, dann das Volume geleert:
   ```bash
   for v in status-data healthchecks-data beszel-data bootstrap signal-data; do
     [ -f backup/$v.tgz ] || continue
     docker run --rm -v quietboard_$v:/v -v "$PWD/backup":/b:ro alpine:3.22 \
       sh -c "tar tzf /b/$v.tgz >/dev/null && find /v -mindepth 1 -delete && tar xzf /b/$v.tgz -C /v" \
       || { echo "Fehler bei $v – abgebrochen"; break; }
   done
   docker compose up -d
   ```
3. Ändert sich die Adresse: `HC_PUBLIC_URL`, `HC_PING_ENDPOINT`, `BESZEL_PUBLIC_URL` anpassen und auf den Hosts den Installer-Befehl erneut ausführen.

## Deinstallation

Server:

```bash
cd ~/quietboard && docker compose --profile signal --profile tunnel down -v   # -v löscht alle Daten!
cd ~ && rm -rf ~/quietboard
```

Host:

```bash
sudo systemctl disable --now beszel-agent updates-report.timer 2>/dev/null; sudo docker rm -f beszel-agent 2>/dev/null
sudo rm -f /usr/local/bin/{hc,updates-report,beszel-agent} /etc/hc.conf /etc/beszel-agent.env \
  /etc/systemd/system/{beszel-agent.service,updates-report.service,updates-report.timer} \
  /etc/apt/apt.conf.d/99updates-report /etc/apt/apt.conf.d/52unattended-quietboard
sudo systemctl daemon-reload
```

Die automatischen Sicherheitsupdates (`unattended-upgrades`) bleiben installiert; die quietboard-Einstellung dazu ist mit dem letzten Befehl entfernt.
