# Proxmox VE und Proxmox Backup Server

Der PVE-Host selbst und jede PBS-Instanz werden zuerst wie jeder Debian-Host angebunden ([Hosts anbinden](index.md)). Zusätzlich melden PVE und PBS ihre Aufgaben – Backups, Sync, Verify, Garbage Collection, Prune – per Webhook an QuietBoard. Erfolg ist still, Fehler sind laut.

## 1. Checks für die Aufgaben anlegen

In `~/quietboard/config/checks.yaml` (Vorlage: `checks.example.yaml`) je Aufgabe einen Check mit `match`-Block:

```yaml
checks:
  - name: pve/backup
    tags: { host: pve, typ: backup, prio: kritisch }
    schedule: "45 1 * * *"         # wann der Job startet
    grace: 2h                      # wie lange er höchstens dauert
    match: { source: pve, host: pve, type: vzdump }

  - name: pbs/gc
    tags: { host: pbs, typ: gc, prio: normal }
    schedule: "30 4 * * *"
    grace: 2h
    match: { source: pbs, host: pbs, type: gc }
```

`type` ist der PVE/PBS-Ereignistyp (`vzdump`, `prune`, `gc`, `verify`, `sync`, `replication` …), optional `datastore` oder `job_id`. Danach abgleichen:

```bash
docker compose exec status python -m tools.hc_sync --dry   # Vorschau
docker compose exec status python -m tools.hc_sync         # anlegen
```

## 2. Webhook in PVE/PBS einrichten

PVE: *Datacenter → Notifications*, PBS: *Configuration → Notifications*.

1. **Notification Targets → Add → Webhook**, Name `quietboard`:
   - Method `POST`, URL `http://<server>:8088/api/ingest/pve?source=pve&host=pve`
     (PBS: `source=pbs&host=pbs` – `host` genau wie im `match`-Block)
   - Header `Content-Type: application/json` und `Authorization: Bearer {{ secrets.token }}`
   - Secret `token` = `INGEST_TOKEN` aus `~/quietboard/.env`
   - Body:
     ```
     {"severity":"{{ severity }}","title":{{ json title }},"message":{{ json message }},"fields":{{ json fields }}}
     ```
2. **Notification Matchers → Add**, Target `quietboard`, ohne Filter.
3. **PBS:** pro Datastore unter *Options → Notification* den Modus „Notification System“ wählen. **PVE:** im Backup-Job „Notification system“.
4. Mit *Test* prüfen: In QuietBoard erscheint unter „Meldungen“ ein Eintrag.

Ein erfolgreicher Lauf pingt den passenden Check; ein Fehler setzt ihn auf rot. Fehler ohne passenden Check werden nie verschluckt: Sie erscheinen als Meldung und lösen eine Benachrichtigung aus.

## 3. Datastore-Füllstand (optional)

Mit einem Read-only-API-Token (Rolle *Audit* auf `/`) zeigt QuietBoard Belegung und laufende Aufgaben der PBS-Datastores. In `.env`:

```ini
PBS_TARGETS=pbs|https://pbs.home.arpa:8007|status@pbs!quietboard|<secret>
```

Mehrere Instanzen mit `;` trennen, danach `docker compose up -d`.
