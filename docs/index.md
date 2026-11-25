# QuietBoard

**QuietBoard bündelt Metriken, Jobs und Updates deines Homelabs, schweigt bei Erfolg und meldet sich einmal am Morgen – und richtet sich selbst ein.**

QuietBoard ersetzt [Beszel](https://github.com/henrygd/beszel) und [Healthchecks](https://github.com/healthchecks/healthchecks) nicht. Es macht beide ohne Fachwissen nutzbar und legt eine Ansicht darüber – im Browser und als App auf dem Handy.

## Was du bekommst

- **Eine Übersicht:** Hosts (CPU, RAM, Disk), Jobs (Backups, Skripte, Proxmox-Aufgaben) und ausstehende Updates – sortiert nach dem, was Aufmerksamkeit braucht.
- **Ruhe bei Erfolg, Alarm bei Fehlern:** Push aufs Handy, Mail oder Signal, wenn ein Host ausfällt, ein Backup fehlt oder Security-Updates liegen bleiben. Sonst eine kurze **Morgenmeldung**.
- **Selbsteinrichtung:** Ein Befehl installiert alles. Healthchecks und Beszel richten sich selbst ein, ohne Klicks in deren Oberflächen.
- **Ein Befehl pro Host:** Agent, Job-Helfer, Update-Bericht und automatische Sicherheitsupdates.
- **Kein Zwangsdienst:** Alles läuft bei dir. Cloudflare, Tailscale & Co. sind optional.

## So funktioniert es

```text
 Hosts ──Agent──────────▶ Beszel ──Alarm──┐
   │                                      ▼
   ├──hc (Jobs)─────────▶ Healthchecks ──▶ QuietBoard ──▶ Push · Mail · Signal
   │                                      ▲                 └▶ Morgenmeldung
   └──Update-Bericht─────────────────────┘
 Proxmox VE/PBS ──Webhook────────────────┘
```

Beszel und Healthchecks sind die Motoren: Sie messen und alarmieren weiter, auch wenn QuietBoard einmal ausfällt. QuietBoard bündelt, konfiguriert und zeigt an.

## Weiter

- [Installation](install/index.md) – in etwa 15 Minuten vom leeren Server zur ersten grünen Übersicht
- [Hosts anbinden](hosts/index.md) · [Jobs und Checks](jobs.md) · [Benachrichtigungen](notifications.md)
