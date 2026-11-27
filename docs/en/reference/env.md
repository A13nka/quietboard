# Reference: `.env`

`install.sh` or `generate-env.sh` creates `.env` and fills in all secrets. Values passed to `install.sh` as environment variables (e.g. `ADMIN_EMAIL=… TZ=… bash`) end up there too. After changes: `docker compose up -d`.

## Basic settings

| Variable | Default | Meaning |
| --- | --- | --- |
| `ADMIN_EMAIL` | – (required) | admin login for Healthchecks and Beszel, first mail recipient |
| `TZ` | `Europe/Berlin` | time zone for the morning digest and display |
| `SITE_NAME` | `Homelab` | name in the interface and messages |
| `HC_PUBLIC_URL` | `http://<first IP>:8000` | address of the Healthchecks interface |
| `HC_PING_ENDPOINT` | `http://<first IP>:8000/ping/` | ping address the hosts use |
| `BESZEL_PUBLIC_URL` | `http://<first IP>:8090` | hub address for agents and browser |
| `QB_VERSION` | `latest` | app version: `latest`, `v0`, `v0.4`, `v0.4.0`, `edge` |

## Secrets (generated automatically)

| Variable | Meaning |
| --- | --- |
| `ADMIN_PASSWORD` | password of the Healthchecks and Beszel admin |
| `HC_SECRET_KEY` | Django secret of Healthchecks (signs e.g. the API keys) |
| `INGEST_TOKEN` | token of the hosts for update reports, messages and the host installer |
| `VAPID_PRIVATE_KEY` | key for Web Push |

## Optional

| Variable | Meaning |
| --- | --- |
| `BIND_ADDR` | only listen on this address (e.g. a VPN IP) |
| `HC_EXTRA_HOSTS` | more names/IPs under which Healthchecks should be reachable (comma-separated) |
| `STATUS_PORT`, `HC_PORT`, `BESZEL_PORT` | other host ports (default 8088, 8000, 8090) |
| `LANGUAGE` | language of messages (`de` or `en`, default `de`) as long as it was not changed in the app |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | mail for QuietBoard and Healthchecks |
| `VAPID_SUBJECT` | contact for push services (`mailto:…`) |
| `BESZEL_ALERT_DOWN_MIN` | minutes until the offline alert of new hosts (default 5) |
| `POLL_SECONDS` | polling interval of the engines (default 60) |
| `PBS_TARGETS` | Proxmox Backup Server: `name\|url\|tokenid\|secret[\|check]`, several separated by `;`. Certificate check (recommended): SHA-256 fingerprint from the PBS dashboard ("Show Fingerprint"), `ca:/path/ca.pem` or `verify` (public CA). Without it the certificate is not checked (warning in the log; probably on by default from v0.7) |
| `SIGNAL_NUMBER`, `SIGNAL_RECIPIENT` | Signal (profile `signal`) |
| `TUNNEL_TOKEN` | Cloudflare Tunnel (profile `tunnel`) |
| `ACCESS_TEAM`, `ACCESS_AUD` | Cloudflare Access as sign-in |
| `TRUSTED_PROXIES` | proxies whose forwarded headers (`X-Forwarded-For`, `X-Forwarded-Proto`, `CF-Connecting-IP`) are honoured: container names and/or networks, comma-separated (default `cloudflared`). These headers are ignored from everyone else |
| `CLOUDFLARE_PROXIES` | proxies whose `CF-Connecting-IP` is honoured (default `cloudflared`). Other trusted proxies provide the address only via `X-Forwarded-For` |
| `HEARTBEAT` | `0` turns off the heartbeat check `quietboard/app` in Healthchecks (on by default; recreated when missing) |
| `PUBLIC_URL` | address of the web UI, e.g. `https://status.example.org` – for links in Signal and mail messages (optional) |
| `PUBLIC_ORIGINS` | only needed if a proxy rewrites the `Host` header: addresses of the web UI, e.g. `https://status.example.org` |
| `HC_API_KEY`, `HC_PING_KEY`, `BESZEL_APP_USER`, `BESZEL_APP_PASS` | existing Healthchecks/Beszel instead of self-setup |
| `STATUS_IMAGE` | a completely different image (e.g. built locally) |
| `DEMO` | sample data instead of real engines |
| `ALLOW_NO_AUTH` | **for tests only:** app without sign-in |
