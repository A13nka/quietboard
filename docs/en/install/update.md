# Updates and versions

## Versions

| Tag | Meaning |
| --- | --- |
| `latest` | newest stable version |
| `v0` / `v0.4` | newest version within 0.x or 0.4.x – bug fixes automatically, no big jumps |
| `v0.4.0` | exactly this version |
| `edge` | current development state (`main`), for testing only |

The version is stored in `.env` as `QB_VERSION`. The installer pins the newest release version (e.g. `v0.6.1`).

**Important:** with a pinned version, `docker compose pull` fetches exactly that version again and again. Updating then
means running the installer again (it moves a pinned version to the newest one) or changing the value in `.env` by
hand. If you want bug fixes automatically, set `QB_VERSION=v0` or `v0.6` – the installer leaves such floating tags in
place.

## Updating

Run the installer again – it shows which images it pulls, loads new versions and keeps `.env` and all data:

```bash
curl -fsSL https://github.com/A13nka/quietboard/releases/latest/download/install.sh | bash
```

Only the images, without a new `compose.yaml`:

```bash
cd ~/quietboard
docker compose pull && docker compose up -d
```

Before bigger version jumps: make a [backup](backup.md) and read the [changelog](https://github.com/A13nka/quietboard/blob/main/CHANGELOG.md).

## Updating hosts

Run the command from **System → Add host** again – it replaces agent, `hc` and update report with the current version and keeps the registration at the hub.

### Hosts by hand (without the installer)

For hosts that were set up by hand or with older scripts, or if only `hc` and `updates-report` should be renewed: the
release package contains `hosts/upgrade-host.sh`. It replaces **only** these two files. Agent, timer, apt hook and
security updates stay untouched, and no service is restarted.

```bash
V=v0.7.0                                   # desired version
W=$(mktemp -d) && cd "$W"
curl -fsSLO "https://github.com/A13nka/quietboard/releases/download/$V/quietboard-$V.tar.gz"
curl -fsSLO "https://github.com/A13nka/quietboard/releases/download/$V/SHA256SUMS"
sha256sum -c --ignore-missing SHA256SUMS   # must show "OK"
tar -xzf "quietboard-$V.tar.gz"
sudo bash "quietboard-$V/hosts/upgrade-host.sh"            # 1. check – changes nothing
sudo bash "quietboard-$V/hosts/upgrade-host.sh" --apply    # 2. replace
```

The check shows:

- which files change;
- which keys `/etc/hc.conf` contains (without values) and which are missing;
- which scripts or cron entries pipe text into `hc ping`. They now need a `-` at the end; with `--apply --fix-stdin` the script adds it.

If `HC_PING_BASE` or `STATUS_INGEST_URL` are missing, pass the values:

```bash
sudo QB_PING_BASE=http://<server>:8000/ping QB_INGEST_URL=http://<server>:8088/api/ingest/updates \
  bash "quietboard-$V/hosts/upgrade-host.sh" --apply
```

The old versions stay as `*.bak-qb`. To go back: `sudo bash …/upgrade-host.sh --rollback`.
