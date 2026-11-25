# Installation

QuietBoard runs as a Docker Compose stack on a Linux server: a small VPS, a VM or a mini PC in your homelab.

## Requirements

| | Minimum | Recommended |
| --- | --- | --- |
| System | Debian 12/13 or Ubuntu 22.04+ (other Linux systems with Docker work too) | Debian 13 |
| CPU / RAM | 1 vCPU / 1 GB | 2 vCPU / 2 GB |
| Disk | 10 GB free | 20 GB |
| Software | Docker Engine with the Compose plugin, `curl`, `openssl` | – |

Measured on a 2 GB VM without swap: the whole stack needs about 350 MB (Healthchecks ≈ 270 MB, app ≈ 70 MB, Beszel ≈ 15 MB); Signal adds ≈ 180 MB.

Install Docker if it is missing: [docs.docker.com/engine/install](https://docs.docker.com/engine/install/). Then add your user to the `docker` group (`sudo usermod -aG docker $USER`, log in again).

## One-command installation

```bash
curl -fsSL https://github.com/A13nka/quietboard/releases/latest/download/install.sh | ADMIN_EMAIL=you@example.org bash
```

The script

1. creates `~/quietboard` (another location: `QB_DIR=/opt/quietboard` before `bash`; the folder must be writable for your user) and downloads `compose.yaml`,
2. creates `.env` with all secrets (mode 600) and detects the server's IP address,
3. shows which images it pulls and starts the services – Healthchecks and Beszel set themselves up,
4. prints the addresses, the **setup code** and the command for adding hosts.

```text
QuietBoard läuft – installiert in /home/you/quietboard
  App           http://192.0.2.10:8088
  Healthchecks  http://192.0.2.10:8000
  Beszel        http://192.0.2.10:8090
  Login für Healthchecks und Beszel: you@example.org, Passwort: grep ADMIN_PASSWORD /home/you/quietboard/.env

Nächste Schritte:
  1. http://192.0.2.10:8088 öffnen und das Admin-Konto anlegen – Einrichtungscode: K7QM-3XPA
  2. Diesen Server selbst als Host anbinden (als root oder Benutzer mit sudo):
       curl -fsSL -H "Authorization: Bearer …" http://192.0.2.10:8088/api/install/host.sh | bash
  3. Jeden weiteren Host mit demselben Befehl anbinden (steht auch in der App unter System → Host hinzufügen).
```

(The installer output is German for now: “next steps” – 1. open the app and create the admin account with the setup code, 2. connect this server itself as a host, 3. connect every other host with the same command.)

!!! tip "The server is a host, too"
    The installer only sets up QuietBoard itself. To see the server in the host list (CPU, RAM, disk, updates), run the host command from step 2 on it once – exactly like on any other machine.

Options as environment variables before `bash`: `QB_VERSION=v0.4.0` (a specific version), `PUBLIC_HOST=status.example.org` (address under which hosts reach the server), `TZ=Europe/Berlin`, `SITE_NAME=Homelab`, `LANGUAGE=en` (language of notifications), `QB_DIR=/opt/quietboard`, `QB_DATA_DIR=/srv/quietboard` (data in folders instead of Docker volumes, see [Data in your own folders](storage.md)).

## First steps after installation

1. **Open the app** (`http://<server>:8088`) and create the admin account with the setup code. The code is also in the log: `docker compose logs status | grep Einrichtungscode`.
2. **System → Add host:** run the command shown on every host – including the QuietBoard server itself. The host appears under “Hosts” within a few seconds.
3. **System → Notifications:** check the mail recipients and the time of the morning digest, set the language of notifications, click “Send test”. Mail needs an SMTP server in `.env` ([Notifications](../notifications.md)).
4. **On your phone:** open the app in the browser, add it to the home screen, enable notifications under System (needs HTTPS, see [Network](network.md)).
5. **Monitor jobs** (backups, scripts): [Jobs and checks](../jobs.md).

## From the release bundle

If you prefer not to pipe into bash: download `quietboard-vX.Y.Z.tar.gz` and `SHA256SUMS` from [Releases](https://github.com/A13nka/quietboard/releases), verify, unpack and start:

```bash
sha256sum -c SHA256SUMS --ignore-missing
tar xzf quietboard-v*.tar.gz && cd quietboard-v*/
ADMIN_EMAIL=you@example.org ./install.sh
```

## Next

- [Network and HTTPS](network.md) · [Updates and versions](update.md) · [Backup and uninstall](backup.md)
