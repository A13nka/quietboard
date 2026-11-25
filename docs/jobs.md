# Jobs und Checks

Ein **Job** ist alles, was regelmäßig laufen soll: Backups, Synchronisationen, Zertifikatserneuerung, eigene Skripte. Für jeden Job gibt es in Healthchecks einen **Check**. Meldet sich der Job nicht rechtzeitig oder mit Fehler, wird der Check rot – und QuietBoard sagt Bescheid.

## Checks anlegen: `checks.yaml`

Alle Checks stehen in `~/quietboard/config/checks.yaml` (Vorlage: `checks.example.yaml` daneben):

```yaml
settings:
  tz: Europe/Berlin
  channels:                 # Healthchecks-Integrationen je Priorität (eingerichtet ist "E-Mail")
    kritisch: [E-Mail]
    normal: [E-Mail]
    info: []

hosts:                      # optional: Weblinks, Hosts mit Zeitfenster
  docker01: { beszel: docker01, always_on: true, url: { Portainer: "https://docker01.home.arpa:9443" } }

checks:
  - name: docker01/restic-offsite
    tags: { host: docker01, typ: backup, prio: kritisch }
    schedule: "0 3 * * *"   # Cron: wann der Job startet
    grace: 2h               # wie lange er höchstens dauern darf
  - name: docker01/certbot
    tags: { host: docker01, typ: zertifikat, prio: normal }
    period: 1d              # statt Cron: alle x Zeit
    grace: 6h
```

Abgleichen (legt an und aktualisiert, löscht nie):

```bash
cd ~/quietboard
docker compose exec status python -m tools.hc_sync --dry   # Vorschau
docker compose exec status python -m tools.hc_sync         # anwenden, zeigt die Ping-Adressen
```

Prioritäten: **kritisch** und **normal** lösen Push aus, **info** nur einen Eintrag. In der App lassen sich Checks unter „Jobs“ auch direkt pausieren und umpriorisieren.

## Jobs melden: `hc`

Auf jedem angebundenen Host ist `hc` installiert:

```bash
hc run docker01-restic-offsite -- restic backup /data    # meldet Start, Ende, Exitcode und die letzten 20 KB Log
hc ping docker01-certbot                                  # einfacher Erfolgs-Ping
hc ping docker01-certbot fail                             # Fehler melden
echo "Details" | hc ping docker01-certbot log -           # Text mitsenden ("-" liest stdin)
```

Der Slug ist der Check-Name mit `-` statt `/`. In systemd-Timern: `ExecStart=/usr/local/bin/hc run <slug> -- /pfad/zum/skript.sh`, in Cron: `hc run <slug> -- …` vor den Befehl.

Das Log eines fehlgeschlagenen Laufs steht in der App direkt in der aufgeklappten Zeile.

## Andere Absender

| Absender | Weg |
| --- | --- |
| Proxmox VE / PBS | Webhook → [Proxmox](hosts/proxmox.md) |
| Backrest | Plan → Hooks → Healthchecks, URL `http://<server>:8000/ping/<ping-key>/<slug>` |
| Synology, Watchtower, DockHand, beliebige Skripte | `POST /api/ingest/notify` mit Token → [API](reference/api.md) |
| Alles mit Healthchecks-Unterstützung | Ping-URL aus `hc_sync` |
