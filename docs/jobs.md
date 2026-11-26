# Jobs und Checks

Ein **Job** ist alles, was regelmäßig laufen soll: Backups, Synchronisationen, Zertifikatserneuerung, eigene Skripte, Proxmox-Backups. QuietBoard legt für jeden Job einen Check in Healthchecks an. Meldet sich der Job nicht rechtzeitig oder mit Fehler, wird er rot – und QuietBoard sagt Bescheid.

## Job anlegen (Oberfläche)

*Jobs → + Job anlegen* (nur Admins):

1. **Was soll überwacht werden?** Eine Vorlage wählen – sie füllt sinnvolle Werte vor:

    | Vorlage | Meldet sich über |
    | --- | --- |
    | Backup-Skript (restic, borg, rsync …) | Helfer `hc` auf dem Host |
    | Skript oder Cronjob auf einem Host | Helfer `hc` |
    | Zertifikat erneuern (certbot, acme.sh …) | Helfer `hc` |
    | Proxmox VE: Backup-Job (vzdump) | Webhook aus PVE |
    | Proxmox Backup Server: Verify, GC, Prune, Sync | Webhook aus PBS |
    | Andere Software mit Ping-URL (Backrest …) | Aufruf einer Adresse |

2. **Host** und **Name** (z. B. `docker01` und `restic-offsite`). Daraus entsteht der Job `docker01/restic-offsite`.
3. **Wann läuft er?** Zu festen Zeiten (Cron, z. B. `0 3 * * *` = täglich 3:00) oder regelmäßig alle x Zeit (`12h`, `1d`).
4. **Darf dauern:** wie lange er nach dem geplanten Start brauchen darf, bevor es Alarm gibt (`2h`).
5. **Priorität:** *kritisch* und *normal* melden sich per Push/Mail, *info* wird nur angezeigt.

Nach dem Anlegen zeigt QuietBoard genau, was auf dem Host, in Proxmox oder in der anderen Software einzutragen ist – mit Kopieren-Knöpfen. Dieselbe Anleitung steht später in jeder aufgeklappten Job-Zeile unter *So meldet sich dieser Job*. Dort lassen sich Jobs auch **bearbeiten**, **pausieren** und **löschen**.

Ein neuer Job steht auf „neu“, bis er sich das erste Mal meldet.

## Jobs melden: `hc`

Auf jedem angebundenen Host ist `hc` installiert:

```bash
hc run docker01-restic-offsite -- restic backup /data    # meldet Start, Ende, Exitcode und die letzten 20 KB Log
hc ping docker01-certbot                                  # einfacher Erfolgs-Ping
hc ping docker01-certbot fail                             # Fehler melden
echo "Details" | hc ping docker01-certbot log -           # Text mitsenden ("-" liest stdin)
```

Der Kurzname (Slug) ist der Job-Name mit `-` statt `/`. In Cron: `0 3 * * * root /usr/local/bin/hc run <slug> -- /pfad/zum/skript.sh`, in systemd: `ExecStart=/usr/local/bin/hc run <slug> -- /pfad/zum/skript.sh`.

Das Log eines fehlgeschlagenen Laufs steht in der App direkt in der aufgeklappten Zeile.

`hc run` führt den Befehl immer aus – auch wenn Healthchecks nicht erreichbar oder die Konfiguration nicht lesbar ist
(dann nur mit Warnung). **Jobs ohne root:** `/etc/hc.conf` ist nur für root lesbar, weil dort auch der Ingest-Token
steht. Für andere Benutzer eine Datei nur mit den Ping-Daten anlegen:

```bash
sudo sh -c 'grep -E "^HC_PING_(BASE|KEY)=" /etc/hc.conf > /etc/hc-ping.conf'
sudo groupadd -f hc && sudo chgrp hc /etc/hc-ping.conf && sudo chmod 640 /etc/hc-ping.conf
sudo usermod -aG hc <benutzer>
```

`hc` nimmt `/etc/hc-ping.conf`, wenn `/etc/hc.conf` nicht lesbar ist (oder ausdrücklich `HC_CONF=/pfad`).

## Andere Absender

| Absender | Weg |
| --- | --- |
| Proxmox VE / PBS | Vorlage „Proxmox …“ – Webhook einmal pro PVE/PBS einrichten, siehe [Proxmox](hosts/proxmox.md) |
| Backrest | Vorlage „Andere Software mit Ping-URL“ → *Plan → Hooks → Healthchecks*, Adresse aus der Anleitung |
| Synology, Watchtower, DockHand, beliebige Skripte | Meldungen ohne festen Zeitplan: `POST /api/ingest/notify` mit Token → [API](reference/api.md) |

## Sichern und übertragen (YAML)

Unter **System → Konfiguration (YAML)**:

- **Exportieren** lädt alle Jobs und Host-Einstellungen als `quietboard-config.yaml` herunter – im selben Format wie `checks.yaml`.
- **Importieren:** Datei wählen oder Text einfügen → *Vorschau* zeigt, was angelegt oder aktualisiert wird, und meldet fehlerhafte Einträge → *Übernehmen*. Der Import löscht nie etwas.

So lässt sich ein Stand sichern, auf einen neuen Server übertragen oder in Git versionieren.

## Alternative: Checks als Code (`checks.yaml`)

Wer Jobs lieber in einer Datei pflegt (z. B. in Git), kann sie in `~/quietboard/config/checks.yaml` beschreiben (Vorlage: `checks.example.yaml` daneben) und abgleichen:

```yaml
settings:
  tz: Europe/Berlin
  channels:                 # Healthchecks-Integrationen je Priorität (eingerichtet ist "E-Mail")
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
docker compose exec status python -m tools.hc_sync --dry   # Vorschau
docker compose exec status python -m tools.hc_sync         # anlegen/aktualisieren (löscht nie)
```

Beides lässt sich mischen. Einen Job aber nur an einer Stelle pflegen: Der Abgleich überschreibt Änderungen aus der Oberfläche an Jobs, die auch in `checks.yaml` stehen.

`checks.yaml` kennt außerdem `hosts:` – Weblinks je Host und Hosts mit Zeitfenster (`always_on: false`, z. B. ein NAS, das nur nachts läuft; solche Hosts zählen nicht als „offline“).
