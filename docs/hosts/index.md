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
| `QB_HOST=nas` | Name in QuietBoard (Standard: `hostname -s`) |
| `QB_AGENT_MODE=binary` oder `docker` | Agent-Art erzwingen (Standard: automatisch) |
| `QB_SECURITY_UPDATES=0` | keine automatischen Sicherheitsupdates einrichten |

Beispiel: `… | QB_HOST=pve QB_SECURITY_UPDATES=0 bash`

Erneut ausführen ist gefahrlos (Aktualisieren). Der Token im Befehl erlaubt das Melden an diesen Server – nicht öffentlich teilen.

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

So funktioniert es auch auf UGREEN (UGOS), QNAP (Container Station), TrueNAS SCALE, Unraid und OMV. Updates dieser Systeme meldet QuietBoard dann noch nicht – Anleitungen je Hersteller folgen.

## Weitere Typen

- [Proxmox VE und Backup Server](proxmox.md) – Backups, Sync, Verify, GC und Prune als Jobs
- [Synology](synology.md) – Agent als Binary oder Container, DSM-Updates, NAS mit Zeitfenster

## Host entfernen

Auf dem Host [deinstallieren](../install/backup.md#deinstallation), in Beszel das System löschen.
