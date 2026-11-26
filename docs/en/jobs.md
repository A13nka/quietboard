# Jobs and checks

A **job** is anything that should run regularly: backups, synchronisations, certificate renewals, your own scripts, Proxmox backups. QuietBoard creates a check in Healthchecks for every job. If the job does not report in time or reports a failure, it turns red – and QuietBoard lets you know.

## Creating a job (interface)

*Jobs → + Add job* (admins only):

1. **What should be monitored?** Choose a template – it pre-fills sensible values:

    | Template | Reports via |
    | --- | --- |
    | Backup script (restic, borg, rsync …) | `hc` helper on the host |
    | Script or cron job on a host | `hc` helper |
    | Renew certificate (certbot, acme.sh …) | `hc` helper |
    | Proxmox VE: backup job (vzdump) | webhook from PVE |
    | Proxmox Backup Server: verify, GC, prune, sync | webhook from PBS |
    | Other software with a ping URL (Backrest …) | calling an address |

2. **Host** and **name** (e.g. `docker01` and `restic-offsite`). This becomes the job `docker01/restic-offsite`.
3. **When does it run?** At fixed times (cron, e.g. `0 3 * * *` = daily 3:00) or every x (`12h`, `1d`).
4. **May take:** how long it may run after the scheduled start before an alert (`2h`).
5. **Priority:** *critical* and *normal* notify by push/mail, *info* is only shown.

After creating it, QuietBoard shows exactly what to enter on the host, in Proxmox or in the other software – with copy buttons. The same guide is later available in every expanded job row under *How this job reports*. There you can also **edit**, **pause** and **delete** jobs.

A new job stays “new” until it reports for the first time.

## Reporting jobs: `hc`

`hc` is installed on every connected host:

```bash
hc run docker01-restic-offsite -- restic backup /data    # reports start, end, exit code and the last 20 KB of log
hc ping docker01-certbot                                  # simple success ping
hc ping docker01-certbot fail                             # report a failure
echo "details" | hc ping docker01-certbot log -           # send text ("-" reads stdin)
```

The short name (slug) is the job name with `-` instead of `/`. In cron: `0 3 * * * root /usr/local/bin/hc run <slug> -- /path/to/script.sh`, in systemd: `ExecStart=/usr/local/bin/hc run <slug> -- /path/to/script.sh`.

The log of a failed run is shown right in the expanded row in the app.

`hc run` always runs the command – even if Healthchecks is unreachable or the configuration is not readable (then only
with a warning). **Jobs without root:** `/etc/hc.conf` is readable by root only, because it also holds the ingest
token. For other users, create a file with just the ping data:

```bash
sudo sh -c 'grep -E "^HC_PING_(BASE|KEY)=" /etc/hc.conf > /etc/hc-ping.conf'
sudo groupadd -f hc && sudo chgrp hc /etc/hc-ping.conf && sudo chmod 640 /etc/hc-ping.conf
sudo usermod -aG hc <user>
```

`hc` uses `/etc/hc-ping.conf` when `/etc/hc.conf` is not readable (or explicitly `HC_CONF=/path`).

## Other senders

| Sender | Way |
| --- | --- |
| Proxmox VE / PBS | template “Proxmox …” – set up the webhook once per PVE/PBS, see [Proxmox](hosts/proxmox.md) |
| Backrest | template “Other software with a ping URL” → *Plan → Hooks → Healthchecks*, address from the guide |
| Synology, Watchtower, DockHand, any script | messages without a fixed schedule: `POST /api/ingest/notify` with token → [API](reference/api.md) |

## Back up and transfer (YAML)

Under **System → Configuration (YAML)**:

- **Export** downloads all jobs and host settings as `quietboard-config.yaml` – in the same format as `checks.yaml`.
- **Import:** choose a file or paste text → *Preview* shows what will be created or updated and reports broken entries → *Apply*. The import never deletes anything.

This way you can save a state, move it to a new server or version it in Git.

## Alternative: checks as code (`checks.yaml`)

If you prefer to keep jobs in a file (e.g. in Git), describe them in `~/quietboard/config/checks.yaml` (template: `checks.example.yaml` next to it) and sync:

```yaml
settings:
  tz: Europe/Berlin
  channels:                 # Healthchecks integrations per priority ("E-Mail" is set up)
    kritisch: [E-Mail]
    normal: [E-Mail]
    info: []

checks:
  - name: docker01/restic-offsite
    tags: { host: docker01, typ: backup, prio: kritisch }
    schedule: "0 3 * * *"
    grace: 2h
```

```bash
cd ~/quietboard
docker compose exec status python -m tools.hc_sync --dry   # preview
docker compose exec status python -m tools.hc_sync         # create/update (never deletes)
```

The priorities in the file keep their German names: `kritisch` (critical), `normal`, `info`.

Both ways can be mixed. Maintain each job in only one place, though: the sync overwrites changes made in the interface for jobs that are also in `checks.yaml`.

`checks.yaml` also knows `hosts:` – web links per host and hosts with a time window (`always_on: false`, e.g. a NAS that only runs at night; such hosts are not counted as “offline”). Both can also be set in the interface.
