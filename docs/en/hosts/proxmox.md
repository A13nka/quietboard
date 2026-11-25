# Proxmox VE and Proxmox Backup Server

The PVE host itself and every PBS instance are first connected like any Debian host ([Adding hosts](index.md)). In addition, PVE and PBS report their tasks – backups, sync, verify, garbage collection, prune – to QuietBoard via webhook. Success is silent, failures are loud.

## 1. Create jobs for the tasks

In the app: *Jobs → + Add job* → template **Proxmox VE: backup job (vzdump)** or **Proxmox Backup Server: verify, GC, prune, sync**.

- **Proxmox host:** a name for this PVE/PBS instance, e.g. `pve` or `pbs`. It also appears in the webhook address later.
- **Schedule:** when the job starts in Proxmox (cron, e.g. `0 1 * * *`); **may take:** how long it takes at most.
- **Event:** `vzdump` (PVE backup) or `verify`, `gc`, `prune`, `sync` (PBS). Optionally only a specific job ID or datastore.

After creating it, the app shows the filled-in values for the webhook (step 2) with copy buttons.

??? note "Alternative: in checks.yaml"
    ```yaml
    checks:
      - name: pve/backup
        tags: { host: pve, typ: backup, prio: kritisch }
        schedule: "45 1 * * *"
        grace: 2h
        match: { source: pve, host: pve, type: vzdump }
    ```
    Then `docker compose exec status python -m tools.hc_sync`. `type` is the PVE/PBS event type, optionally `datastore` or `job_id`. The priorities in the file are `kritisch` (critical), `normal` and `info`.

## 2. Set up the webhook in PVE/PBS

PVE: *Datacenter → Notifications*, PBS: *Configuration → Notifications*.

1. **Notification Targets → Add → Webhook**, name `quietboard`:
   - Method `POST`, URL `http://<server>:8088/api/ingest/pve?source=pve&host=pve`
     (PBS: `source=pbs&host=pbs` – `host` exactly as given for the job)
   - Headers `Content-Type: application/json` and `Authorization: Bearer {{ secrets.token }}`
   - Secret `token` = `INGEST_TOKEN` from `~/quietboard/.env`
   - Body:
     ```
     {"severity":"{{ severity }}","title":{{ json title }},"message":{{ json message }},"fields":{{ json fields }}}
     ```
2. **Notification Matchers → Add**, target `quietboard`, no filter.
3. **PBS:** per datastore under *Options → Notification* choose the mode “Notification System”. **PVE:** in the backup job choose “Notification system”.
4. Check with *Test*: an entry appears in QuietBoard under “Messages”.

A successful run pings the matching job; a failure turns it red. Failures without a matching job are never swallowed: they appear as a message and trigger a notification.

## 3. Datastore usage (optional)

With a read-only API token (role *Audit* on `/`), QuietBoard shows usage and running tasks of the PBS datastores. In `.env`:

```ini
PBS_TARGETS=pbs|https://pbs.home.arpa:8007|status@pbs!quietboard|<secret>
```

Separate several instances with `;`, then `docker compose up -d`.
