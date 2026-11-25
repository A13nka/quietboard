# Synology

**Usual case: agent as a container.** As on UGREEN, QNAP, Unraid or TrueNAS, the Beszel agent runs most easily in the *Container Manager* on a Synology too – as a project with the Docker stack from [Adding hosts](index.md#docker-hosts-without-shell-access-portainer-dockge-nas-interfaces). The values are in the app under **System → Add host → Show command → Manual**.

If you also want to report DSM updates and jobs, or do not want to use Docker on the NAS (agent as a binary), use the installer command – see below.

> Status: prepared, not yet verified on real hardware. Feedback welcome as an issue.

## With the command from “Add host”

SSH into the Synology (*Control Panel → Terminal & SNMP → enable SSH*), become root, run the command:

```bash
sudo -i
curl -fsSL -H "Authorization: Bearer <token>" http://<server>:8088/api/install/host.sh | bash
```

The installer detects DSM and

- installs `hc` and `dsm-report` to `/usr/local/bin`, configuration to `/usr/local/etc/quietboard.conf` (survives DSM updates),
- reports the available package updates once right away,
- **leaves an existing Beszel agent alone** and shows the three values to enter there:
  ```ini
  KEY=ssh-ed25519 AAAA…
  TOKEN=…
  HUB_URL=http://<server>:8090
  ```
  Then restart the agent – it registers itself and appears under “Hosts”.
- shows the entries for the Task Scheduler (see below).

Prefer the agent as a container (Container Manager must be installed): `… | QB_AGENT_MODE=docker bash`.

## Agent as a binary (existing installation)

Where the values live depends on how the agent was installed:

| Installation | Change the values in |
| --- | --- |
| Beszel install script / own service | the environment file or unit of the service (`KEY`, `TOKEN`, `HUB_URL`), then restart the service |
| Task Scheduler (a “Boot-up” task starts the agent) | the script of the task, then run the task once |

The old entry of the system in the previous hub can be deleted afterwards.

## Task Scheduler

*Control Panel → Task Scheduler → Create*, user **root**:

1. **Scheduled Task → User-defined script**, daily: `/usr/local/bin/dsm-report`
2. **Only for a NAS that does not run all the time** (e.g. at night for backups): *Triggered Task → Boot-up*:
   `/usr/local/bin/hc ping <name>-online`

## NAS with a time window

A NAS that only runs at night should not raise alerts during the day:

- In the app under *Hosts*, expand the NAS → *Settings* → switch off **Always on**. The app then shows it as “off (scheduled)” instead of red, and the morning digest says when it was last seen.
- Under *Jobs*, create a job `<name>/online` (template “Script or cron job”, schedule = power-on time, e.g. `0 2 * * *`, may take `2h`). If the ping is missing, the NAS was not there in its window – that is a real alert.
- In Beszel, switch off the status alert for the system (otherwise Beszel reports “down” every morning).

??? note "Alternative: in checks.yaml"
    ```yaml
    hosts:
      nas: { beszel: nas, always_on: false, url: { DSM: "https://nas.home.arpa:5001" } }
    checks:
      - name: nas/online
        tags: { host: nas, typ: window, prio: normal }
        schedule: "0 2 * * *"
        grace: 2h
    ```

## Jobs on the Synology

Hyper Backup, Snapshot Replication & co. report through the DSM notifications via webhook (*Control Panel → Notification → Webhooks*) to `http://<server>:8088/api/ingest/notify?token=<INGEST_TOKEN>&source=synology`. Your own scripts report with `hc run <check> -- <command>`.
