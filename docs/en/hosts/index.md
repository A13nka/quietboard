# Adding hosts

A “host” is any machine QuietBoard should keep an eye on: servers, VMs, LXC containers, NAS, Raspberry Pi – including the QuietBoard server itself.

## Debian, Ubuntu, Proxmox VE, PBS, Raspberry Pi OS – one command

The command is shown in the app under **System → Add host**. It looks like this and is run on the host (as root or as a user with sudo):

```bash
curl -fsSL -H "Authorization: Bearer <token>" http://<server>:8088/api/install/host.sh | bash
```

It installs:

| Part | Purpose |
| --- | --- |
| **Beszel agent** | CPU, RAM, disk, network, containers. Registers itself at the hub with a token. As a **Docker container** if Docker runs, otherwise as a **binary with systemd**. |
| **`hc`** | ping helper for your own scripts and timers → [Jobs](../jobs.md) |
| **`updates-report`** | reports pending updates daily and after every `apt` run (apt hook), including “reboot required” |
| **Security updates** | `unattended-upgrades` for Debian security only, without automatic reboot, Docker excluded |

Options before `bash`:

| Variable | Effect |
| --- | --- |
| `QB_HOST=nas` | name in QuietBoard (default: `hostname -s`) |
| `QB_AGENT_MODE=binary` or `docker` | force the agent type (default: automatic) |
| `QB_SECURITY_UPDATES=0` | do not set up automatic security updates |

Example: `… | QB_HOST=pve QB_SECURITY_UPDATES=0 bash`

Running it again is safe (it updates). The token in the command allows reporting to this server – do not share it publicly.

### What QuietBoard sets up per host automatically

- **Alerts in Beszel:** status (offline for 5 minutes), disk > 90 % (10 min), RAM > 95 % (15 min). Beszel reports to QuietBoard, QuietBoard notifies via push/mail/Signal. Adjust them in the Beszel interface.
- **Updates:** appear under “Updates”, sorted by urgency. Security updates pending for more than 48 hours trigger a notification – the automation did not work then.

## Docker hosts without shell access (Portainer, Dockge, NAS interfaces)

Create the agent as a stack – values from **System → Add host** or `/api/agent`:

```yaml
services:
  beszel-agent:
    image: henrygd/beszel-agent:0.21.2
    container_name: beszel-agent
    restart: unless-stopped
    network_mode: host
    environment:
      KEY: "ssh-ed25519 AAAA…"          # public key of the hub
      TOKEN: "…"                        # universal token
      HUB_URL: "http://<server>:8090"
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - beszel-agent-data:/var/lib/beszel-agent
volumes:
  beszel-agent-data:
```

This also works on UGREEN (UGOS), QNAP (Container Station), TrueNAS SCALE, Unraid and OMV. QuietBoard does not report updates of these systems yet – guides per vendor will follow.

## More types

- [Proxmox VE and Backup Server](proxmox.md) – backups, sync, verify, GC and prune as jobs
- [Synology](synology.md) – agent as binary or container, DSM updates, NAS with a time window

## Settings per host

In the app under *Hosts*, expand a host → *Settings* (admins only):

- **Always on:** switch off for machines that only run part of the time (e.g. a NAS that runs at night). They are then not considered down; the morning digest only says when they were last seen.
- **Web links:** one line per link, `name = address` (e.g. `Portainer = https://docker01.home.arpa:9443`). The links are shown in the expanded row; addresses in your own network are marked “(VPN)”.

Settings from the interface take precedence over `hosts:` in `checks.yaml`.

## Removing a host

1. [Uninstall](../install/backup.md#uninstall) on the host – otherwise the agent registers again right away.
2. In the app: expand the host → *Settings* → **Remove host**. This deletes it in Beszel including its history, its update reports and its settings. Jobs of the host remain and can be deleted one by one under *Jobs*.
