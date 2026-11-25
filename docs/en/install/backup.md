# Backup, migration, uninstall

## What needs to be backed up

| What | Where | Content |
| --- | --- | --- |
| `.env` | `~/quietboard/.env` | all secrets and settings |
| `config/` | `~/quietboard/config/` | `checks.yaml` |
| Volumes | `quietboard_status-data`, `quietboard_healthchecks-data`, `quietboard_beszel-data`, `quietboard_bootstrap` (+ `quietboard_signal-data`) | accounts, checks, history, credentials |

Tip: *System → Configuration (YAML) → Export* additionally saves all jobs and host settings as a readable file.

## Backing up

If the data lives in folders instead of volumes, it is simpler – see [Data in your own folders](storage.md#backing-up).

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

`backup/` then contains secrets – only store it off-site encrypted (e.g. restic, Borg, Backrest).

## Restore / move to a new server

1. Run `install.sh` once on the new server (creates folders and volumes), then `docker compose down`.
2. Copy back `.env` and `checks.yaml`, restore the volumes:
   ```bash
   for v in status-data healthchecks-data beszel-data bootstrap signal-data; do
     [ -f backup/$v.tgz ] && docker run --rm -v quietboard_$v:/v -v "$PWD/backup":/b alpine sh -c "rm -rf /v/* && tar xzf /b/$v.tgz -C /v"
   done
   docker compose up -d
   ```
3. If the address changes: adjust `HC_PUBLIC_URL`, `HC_PING_ENDPOINT`, `BESZEL_PUBLIC_URL` and run the installer command on the hosts again.

## Uninstall

Server:

```bash
cd ~/quietboard && docker compose --profile signal --profile tunnel down -v   # -v deletes all data!
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

Automatic security updates (`unattended-upgrades`) stay installed; the QuietBoard setting for them is removed by the last command.
