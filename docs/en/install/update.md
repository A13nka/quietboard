# Updates and versions

## Versions

| Tag | Meaning |
| --- | --- |
| `latest` | newest stable version (default) |
| `v0` / `v0.4` | newest version within 0.x or 0.4.x – bug fixes automatically, no big jumps |
| `v0.4.0` | exactly this version |
| `edge` | current development state (`main`), for testing only |

The version is stored in `.env` as `QB_VERSION` (if it is missing, `latest` applies; installed from a release it is pinned).

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
