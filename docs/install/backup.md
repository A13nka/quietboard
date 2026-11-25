# Sicherung, Umzug, Deinstallation

## Was gesichert werden muss

| Was | Wo | Inhalt |
| --- | --- | --- |
| `.env` | `~/quietboard/.env` | alle Secrets und Einstellungen |
| `config/` | `~/quietboard/config/` | `checks.yaml` |
| Volumes | `quietboard_status-data`, `quietboard_healthchecks-data`, `quietboard_beszel-data`, `quietboard_bootstrap` (+ `quietboard_signal-data`) | Konten, Checks, Verlauf, Zugänge |

## Sichern

```bash
cd ~/quietboard
docker compose stop
mkdir -p backup
for v in status-data healthchecks-data beszel-data bootstrap signal-data; do
  docker run --rm -v quietboard_$v:/v -v "$PWD/backup":/b alpine tar czf /b/$v.tgz -C /v . 2>/dev/null || true
done
cp .env config/checks.yaml backup/
docker compose start
```

`backup/` enthält danach Secrets – nur verschlüsselt außer Haus lagern (z. B. restic, Borg, Backrest).

## Wiederherstellen / Umzug auf einen neuen Server

1. Auf dem neuen Server einmal `install.sh` ausführen (legt Ordner und Volumes an), dann `docker compose down`.
2. `.env` und `checks.yaml` zurückkopieren, Volumes zurückspielen:
   ```bash
   for v in status-data healthchecks-data beszel-data bootstrap signal-data; do
     [ -f backup/$v.tgz ] && docker run --rm -v quietboard_$v:/v -v "$PWD/backup":/b alpine sh -c "rm -rf /v/* && tar xzf /b/$v.tgz -C /v"
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
