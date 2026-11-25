# QuietBoard

**QuietBoard brings together the metrics, jobs and updates of your homelab. It stays silent when everything works, sends one message in the morning – and sets itself up.**

QuietBoard does not replace [Beszel](https://github.com/henrygd/beszel) and [Healthchecks](https://github.com/healthchecks/healthchecks). It makes both usable without expert knowledge and puts one view on top – in the browser and as an app on your phone.

## What you get

- **One overview:** hosts (CPU, RAM, disk), jobs (backups, scripts, Proxmox tasks) and pending updates – sorted by what needs attention.
- **Quiet on success, loud on failure:** push to your phone, mail or Signal when a host goes down, a backup is missing or security updates pile up. Otherwise a short **morning digest**.
- **Sets itself up:** one command installs everything. Healthchecks and Beszel configure themselves – no clicking through their interfaces.
- **One command per host:** agent, job helper, update report and automatic security updates.
- **Jobs in a few clicks:** templates for backup scripts, cron jobs, certificates, Proxmox VE/PBS and software with a ping URL.
- **No mandatory cloud:** everything runs on your own hardware. Cloudflare, Tailscale and friends are optional.

## How it works

```text
 hosts ──agent──────────▶ Beszel ──alert──┐
   │                                      ▼
   ├──hc (jobs)─────────▶ Healthchecks ──▶ QuietBoard ──▶ push · mail · Signal
   │                                      ▲                 └▶ morning digest
   └──update report──────────────────────┘
 Proxmox VE/PBS ──webhook────────────────┘
```

Beszel and Healthchecks are the engines: they keep measuring and alerting even if QuietBoard itself is down. QuietBoard bundles, configures and displays.

## Next

- [Installation](install/index.md) – from an empty server to the first green overview in about 15 minutes
- [Adding hosts](hosts/index.md) · [Jobs and checks](jobs.md) · [Notifications](notifications.md)
