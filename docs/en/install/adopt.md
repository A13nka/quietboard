# Adopting an existing installation

If you already run Healthchecks and Beszel, you can put QuietBoard on top without starting over: checks, history, hosts and agents stay, nothing changes on the hosts. Requirement: the same versions as in QuietBoard's `compose.yaml` (currently Healthchecks **v5.0.3**, Beszel **0.21.2**) – otherwise bring the old installation to these versions first.

## 1. Create `.env`

Running `install.sh` is **not** the right way here, because it starts right away. Instead fetch the files and prepare `.env` by hand:

```bash
mkdir -p ~/quietboard/config && cd ~/quietboard
V=$(curl -fsSL https://api.github.com/repos/A13nka/quietboard/releases/latest | grep -o '"tag_name": *"[^"]*"' | cut -d'"' -f4)
for f in compose.yaml .env.example generate-env.sh; do curl -fsSLO "https://raw.githubusercontent.com/A13nka/quietboard/$V/$f"; done
chmod +x generate-env.sh
```

Put the values of the old installation into `.env` **before** running `generate-env.sh` (it only fills empty fields):

| Variable | Value |
| --- | --- |
| `HC_SECRET_KEY` | `SECRET_KEY` of the old Healthchecks installation – **must be the same**, otherwise sessions and signatures become invalid |
| `HC_API_KEY`, `HC_PING_KEY` | API key (write access) and ping key of the project. If both are set, QuietBoard changes **nothing** in Healthchecks (no new keys, no new password) |
| `INGEST_TOKEN` | the token hosts used to send update reports (if any) – otherwise new |
| `HC_PUBLIC_URL`, `HC_PING_ENDPOINT`, `BESZEL_PUBLIC_URL` | the previous addresses (`SITE_ROOT`, `PING_ENDPOINT`, `APP_URL`) |
| `HC_EXTRA_HOSTS` | further names/IPs from the old `ALLOWED_HOSTS` |
| `SMTP_*` | the old `EMAIL_*` values of Healthchecks |
| `ADMIN_EMAIL`, `ADMIN_PASSWORD` | your existing Beszel login (recommended) **or** a new address. QuietBoard uses this Beszel admin for its read-only login, the agent token for new hosts and the default alerts. With your existing address, `ADMIN_PASSWORD` becomes the Beszel password – put your current password there and nothing changes. QuietBoard takes over Beszel mails of this account (mail channel) |
| `BESZEL_APP_USER`, `BESZEL_APP_PASS` | **leave empty** – QuietBoard sets up its own access |
| `SIGNAL_*`, `TUNNEL_TOKEN`, `ACCESS_*`, `VAPID_PRIVATE_KEY`, `PBS_TARGETS` | as before, if used (same VAPID key = existing push subscriptions keep working) |

Then run `./generate-env.sh` for the remaining secrets.

## 2. Adopt the data

With a `compose.override.yaml`, QuietBoard points to the existing folders (adjust the paths):

```yaml
volumes:
  healthchecks-data: { driver: local, driver_opts: { type: none, o: bind, device: /path/old/data/healthchecks } }
  beszel-data:       { driver: local, driver_opts: { type: none, o: bind, device: /path/old/data/beszel } }
  signal-data:       { driver: local, driver_opts: { type: none, o: bind, device: /path/old/data/signal } }
```

Folders of a previous status app with `updates.json`, `events.json` etc. can be adopted as `status-data` the same way. Permissions must match: Healthchecks UID 999, QuietBoard UID 10001.

Copy `checks.yaml` (if any) to `~/quietboard/config/`.

## 3. Switch over

```bash
cd /path/old && docker compose stop          # stop the old containers (ports free, data stays)
cd ~/quietboard && docker compose up -d
docker compose logs healthchecks-init        # must report “keine Änderung (Übernahme)” (no change, adoption)
```

Check: all checks and hosts appear in the app, *System* shows Healthchecks and Beszel connected. Hosts, `hc` pings and agents keep running unchanged.

Inside the Docker network the app container is also reachable as `status-app`. Tunnel targets and Beszel webhooks of a predecessor app with that name keep working; QuietBoard then does not add a second webhook to the app.

**Back:** `docker compose down` in `~/quietboard`, then start the old installation again – the data stays compatible. Still make a [backup](backup.md) first.
