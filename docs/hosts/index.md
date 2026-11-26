# Hosts anbinden

Ein „Host“ ist jeder Rechner, den QuietBoard im Blick haben soll: Server, VMs, LXC-Container, NAS, Raspberry Pi – auch der quietboard-Server selbst.

## Debian, Ubuntu, Proxmox VE, PBS, Raspberry Pi OS – ein Befehl

In der App unter **System → Host hinzufügen** steht der Befehl. Er sieht so aus und wird auf dem Host ausgeführt (als root oder als Benutzer mit sudo):

```bash
curl -fsSL -H "Authorization: Bearer <token>" http://<server>:8088/api/install/host.sh | bash
```

Er installiert:

| Teil | Zweck |
| --- | --- |
| **Beszel-Agent** | CPU, RAM, Disk, Netzwerk, Container. Meldet sich per Token selbst beim Hub an. Als **Docker-Container**, wenn Docker läuft, sonst als **Binary mit systemd**. |
| **`hc`** | Ping-Helfer für eigene Skripte und Timer → [Jobs](../jobs.md) |
| **`updates-report`** | meldet ausstehende Updates täglich und nach jedem `apt`-Lauf (apt-Hook), inklusive „Neustart nötig“ |
| **Sicherheitsupdates** | `unattended-upgrades` nur für Debian-Security, ohne automatischen Neustart, Docker ausgenommen |

Optionen vor `bash`:

| Variable | Wirkung |
| --- | --- |
| `QB_HOST=nas` | Name in QuietBoard (Standard: bisheriger Name, bei neuen Hosts `hostname -s` in Kleinbuchstaben) |
| `QB_AGENT_MODE=binary` oder `docker` | Agent-Art erzwingen (Standard: automatisch) |
| `QB_SECURITY_UPDATES=0` | keine automatischen Sicherheitsupdates einrichten |

Beispiel: `… | QB_HOST=pve QB_SECURITY_UPDATES=0 bash`

Erneut ausführen ist gefahrlos (Aktualisieren): Name und eigene Zeilen in `/etc/hc.conf` (z. B. `MAILCOW_DIR`) bleiben,
das Agent-Programm wird gegen seine Prüfsumme geprüft. Ein vorhandener Container `beszel-agent`, den nicht QuietBoard
angelegt hat, wird mit Hinweis ersetzt. Der Token im Befehl erlaubt das Melden an diesen Server – nicht öffentlich
teilen, und den Befehl nur im LAN, per VPN oder über HTTPS ausführen ([Netzwerk](../install/network.md)).

!!! note "Agent und Docker"
    Als Binary kommt der Agent-Benutzer `beszel` in die Gruppe `docker`, damit er Container-Werte lesen kann. Diese
    Gruppe hat praktisch root-Rechte. Wer das nicht möchte: `QB_AGENT_MODE=docker` (Socket nur lesend eingebunden)
    oder den Benutzer danach mit `gpasswd -d beszel docker` wieder herausnehmen.

### Was QuietBoard je Host automatisch einrichtet

- **Alarme in Beszel:** Status (nach 5 Minuten offline), Disk > 90 % (10 min), RAM > 95 % (15 min). Beszel meldet an QuietBoard, QuietBoard benachrichtigt per Push/Mail/Signal. Anpassen in der Beszel-Oberfläche.
- **Updates:** erscheinen unter „Updates“, sortiert nach Dringlichkeit. Security-Updates, die länger als 48 Stunden offen sind, lösen eine Meldung aus – dann hat die Automatik nicht gegriffen.

## Docker-Hosts ohne Shell-Zugriff (Portainer, Dockge, NAS-Oberflächen)

Den Agent als Stack anlegen – Werte aus **System → Host hinzufügen** bzw. `/api/agent`:

```yaml
services:
  beszel-agent:
    image: henrygd/beszel-agent:0.21.2
    container_name: beszel-agent
    restart: unless-stopped
    network_mode: host
    environment:
      KEY: "ssh-ed25519 AAAA…"          # öffentlicher Schlüssel des Hubs
      TOKEN: "…"                        # Universal-Token
      HUB_URL: "http://<server>:8090"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - beszel-agent-data:/var/lib/beszel-agent
volumes:
  beszel-agent-data:
```

So funktioniert es auch auf UGREEN (UGOS), QNAP (Container Station), TrueNAS SCALE, Unraid und OMV. Update-Berichte und Jobs je Hersteller: [Weitere NAS](nas.md).

## Weitere Typen

- [Proxmox VE und Backup Server](proxmox.md) – Backups, Sync, Verify, GC und Prune als Jobs
- [Synology](synology.md) – Agent als Binary oder Container, DSM-Updates, NAS mit Zeitfenster
- [Weitere NAS](nas.md) – UGREEN, QNAP, TrueNAS, Unraid, OMV

## Einstellungen je Host

In der App unter *Hosts* einen Host aufklappen → *Einstellungen* (nur Admins):

- **Läuft dauerhaft:** ausschalten für Rechner, die nur zeitweise an sind (z. B. ein NAS, das nachts läuft). Sie gelten dann nicht als ausgefallen, die Morgenmeldung nennt nur, wann sie zuletzt gesehen wurden.
- **Weblinks:** eine Zeile pro Link, `Name = Adresse` (z. B. `Portainer = https://docker01.home.arpa:9443`). Die Links stehen in der aufgeklappten Zeile; Adressen im eigenen Netz sind mit „(VPN)“ markiert.

Die Einstellungen aus der Oberfläche haben Vorrang vor `hosts:` in `checks.yaml`.

## Host entfernen

1. Auf dem Host [deinstallieren](../install/backup.md#deinstallation) – sonst meldet sich der Agent gleich wieder an.
2. In der App: Host aufklappen → *Einstellungen* → **Host entfernen**. Das löscht ihn in Beszel samt Verlauf, seine Update-Berichte und Einstellungen. Jobs des Hosts bleiben und lassen sich unter *Jobs* einzeln löschen.
