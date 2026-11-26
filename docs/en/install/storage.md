# Data in your own folders

By default the data lives in Docker volumes (`quietboard_status-data` etc.). If you prefer plain folders – e.g. on a separate disk, for a backup tool that backs up folders, or simply to see them – switch with a small extra file.

## New installation

Pass `QB_DATA_DIR` on the first run:

```bash
curl -fsSL https://github.com/A13nka/quietboard/releases/latest/download/install.sh \
  | ADMIN_EMAIL=you@example.org QB_DATA_DIR=/srv/quietboard bash
```

The installer creates the folders with the right permissions (without `sudo`, via a short helper container) and writes `~/quietboard/compose.override.yaml`. Docker Compose reads this file automatically; updates (running `install.sh` again) leave it unchanged.

The result:

| Folder | Content | Owner (UID) |
| --- | --- | --- |
| `/srv/quietboard/status` | accounts, settings, update reports, messages | 10001 |
| `/srv/quietboard/healthchecks` | checks and history (SQLite) | 999 |
| `/srv/quietboard/beszel` | hosts and metrics | root |
| `/srv/quietboard/bootstrap` | generated credentials for Healthchecks | root (file: 10001, readable only by the app) |
| `/srv/quietboard/signal` | Signal account (only with the `signal` profile) | root |

## Moving from existing volumes

!!! warning "Back up first"
    Make a [backup](backup.md) once. The migration copies first and deletes the old volumes only afterwards.

```bash
cd ~/quietboard
D=/srv/quietboard
docker compose --profile signal --profile tunnel down          # stops everything, data stays
docker run --rm -v "$D:/d" alpine:3.22 sh -c \
  'mkdir -p /d/status /d/healthchecks /d/beszel /d/bootstrap /d/signal'
for v in status:status-data healthchecks:healthchecks-data beszel:beszel-data bootstrap:bootstrap signal:signal-data; do
  docker volume inspect "quietboard_${v#*:}" >/dev/null 2>&1 || continue   # e.g. signal-data without the signal profile
  docker run --rm -v "quietboard_${v#*:}:/from:ro" -v "$D/${v%%:*}:/to" alpine:3.22 cp -a /from/. /to/ \
    || { echo "copying ${v#*:} failed – do NOT remove the old volumes"; break; }
done
docker run --rm -v "$D:/d" alpine:3.22 sh -c 'chown -R 10001 /d/status && chown -R 999:999 /d/healthchecks'
```

Check that the data arrived (`ls -l $D/*`), then create the extra file and remove the old volumes – Compose then recreates them as references to the folders:

```bash
cat > compose.override.yaml <<EOF
volumes:
  status-data:       { driver: local, driver_opts: { type: none, o: bind, device: $D/status } }
  healthchecks-data: { driver: local, driver_opts: { type: none, o: bind, device: $D/healthchecks } }
  beszel-data:       { driver: local, driver_opts: { type: none, o: bind, device: $D/beszel } }
  bootstrap:         { driver: local, driver_opts: { type: none, o: bind, device: $D/bootstrap } }
  signal-data:       { driver: local, driver_opts: { type: none, o: bind, device: $D/signal } }
EOF
docker volume rm quietboard_status-data quietboard_healthchecks-data quietboard_beszel-data quietboard_bootstrap quietboard_signal-data
docker compose up -d
```

In the app under *System*, check that Healthchecks and Beszel are connected and the hosts show up again.

## Backing up

With folders it is enough to stop the stack briefly and copy the folder:

```bash
cd ~/quietboard && docker compose stop
sudo tar czf ~/quietboard-backup.tgz -C /srv quietboard ~/quietboard/.env ~/quietboard/config
docker compose start
```

Do not copy the SQLite files while the stack is running – the copy may be incomplete. The archive contains credentials: only store it off-site encrypted.

## Good to know

- With folders, `docker compose down -v` only deletes the references, not the data.
- Network shares (NFS/SMB) are not suitable for the SQLite files – use a local disk.
- Folders on a NAS volume (e.g. Synology `/volume1/docker/quietboard`) work as long as Docker runs on the same device.
