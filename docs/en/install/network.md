# Network and HTTPS

QuietBoard needs three ports. Everything else stays inside the Docker network.

| Port | Service | Who needs to reach it |
| --- | --- | --- |
| 8088 | App (interface, ingest, host installer) | browser, phone, all hosts |
| 8000 | Healthchecks (pings, admin interface) | hosts that report jobs; admin |
| 8090 | Beszel hub | Beszel agents on the hosts; admin |

## Does anything have to be on the internet?

**No.** QuietBoard works entirely inside your own network – no port forwarding, no Cloudflare, no public domain. Hosts, jobs, updates, alerts by mail and Signal all work internally. Only two things need more:

| You want | What you need |
| --- | --- |
| The overview on your phone while away | a VPN into your home network (WireGuard, Tailscale, NetBird) – **or** an HTTPS publication (reverse proxy, Cloudflare Tunnel) |
| **Web Push** (notifications on the phone) | **HTTPS** with a valid certificate – even in the LAN. Easiest via Tailscale (see below) or a reverse proxy with your own domain |
| Mail notifications | outgoing only: access to an SMTP server |

If you publish anything, publish only **port 8088** (the app). Healthchecks (8000) and Beszel (8090) only need your own hosts – LAN or VPN, never the open internet.

`BIND_ADDR` in `.env` sets the address the ports listen on (default: all). The addresses under which hosts reach the server are `HC_PUBLIC_URL`, `HC_PING_ENDPOINT` and `BESZEL_PUBLIC_URL`; `install.sh` sets them to the server's first IP. After a change: `docker compose up -d`.

## Option 1: everything in the same LAN

Nothing else to do. Do not forward the ports to the internet. For Web Push on the phone you only need HTTPS (see below).

## Option 2: VPS as the hub, hosts at home (WireGuard or Tailscale)

1. Connect the VPS and your home network with WireGuard or Tailscale.
2. Put the VPN address of the VPS into `.env` and listen only there:
   ```ini
   BIND_ADDR=10.20.0.1
   HC_PUBLIC_URL=http://10.20.0.1:8000
   HC_PING_ENDPOINT=http://10.20.0.1:8000/ping/
   BESZEL_PUBLIC_URL=http://10.20.0.1:8090
   ```
3. `docker compose up -d`. From now on hosts get the installer command with the VPN address.
4. Additionally block the ports in the VPS firewall, e.g. `iptables -I DOCKER-USER -i <public-interface> -p tcp -m multiport --dports 8000,8080,8090 -j DROP` (container ports, see the DOCKER-USER chain).

## Option 2b: Tailscale or NetBird (mesh VPN)

Many homelabs connect their machines with Tailscale or NetBird. Then the VPN network is the “LAN” for QuietBoard:

1. Install Tailscale/NetBird on the QuietBoard server and on all hosts.
2. Use the server's tailnet or NetBird address (e.g. `100.64.0.10` or `quietboard.tailnet-name.ts.net`) as the address for the hosts:
   ```bash
   cd ~/quietboard
   PUBLIC_HOST=100.64.0.10 ./generate-env.sh     # fills empty addresses; change existing ones in .env by hand
   docker compose up -d
   ```
   or right at installation: `… | PUBLIC_HOST=100.64.0.10 ADMIN_EMAIL=… bash`.
3. Optionally `BIND_ADDR=100.64.0.10`, so the ports only listen inside the VPN.
4. Connect the hosts with the command from “Add host” – it now contains the VPN address.

**HTTPS for Web Push with Tailscale:** `tailscale serve` publishes the app with a valid certificate at `https://<server>.<tailnet>.ts.net` – only for devices in your tailnet, without port forwarding:

```bash
sudo tailscale serve --bg 8088
```

Open this address on your phone (Tailscale app active), add it to the home screen, enable notifications. `tailscale funnel` would additionally make the app public – only needed if devices without Tailscale should have access.

**NetBird:** same principle with the NetBird addresses. For HTTPS use a reverse proxy (below) with your own domain and a DNS challenge – then no router port is needed.

## Option 3: access from outside via HTTPS

**Web Push needs HTTPS** – on the iPhone also the installed app (Share → “Add to Home Screen”). Two ways:

### Reverse proxy (Caddy, Traefik, Nginx Proxy Manager)

Point a subdomain to `http://<server>:8088`, e.g. with Caddy:

```caddy
status.example.org {
    reverse_proxy 127.0.0.1:8088
}
```

If the proxy runs as a container in the same Compose project, add its name to `TRUSTED_PROXIES` (e.g. `TRUSTED_PROXIES=caddy`; `cloudflared` is already included). The app then honours `X-Forwarded-For`/`X-Forwarded-Proto`, and cookies are automatically “Secure”. From all other senders it ignores these headers – otherwise anyone could claim a false address. If the proxy runs directly on the server (as above), everything works without an entry; the sign-in throttling then counts all proxy users together. Publish Healthchecks and Beszel the same way if needed (own subdomains) and set `HC_PUBLIC_URL`/`BESZEL_PUBLIC_URL` to the HTTPS addresses.

### Cloudflare Tunnel (profile `tunnel`)

1. Cloudflare Zero Trust → Networks → Tunnels → create a tunnel, choose Docker, copy the token.
2. Public hostname `status.example.org` → `http://status:8080` (container name in the Compose network).
3. In `.env`: `TUNNEL_TOKEN=…`, then `docker compose --profile tunnel up -d`.

Optionally put **Cloudflare Access** in front (e.g. with PocketID or one-time PIN): set `ACCESS_TEAM` and `ACCESS_AUD` in `.env`. Whoever passes Access is an admin in QuietBoard; local accounts keep working.

## External watcher

If the QuietBoard server itself goes down, it cannot report it. A second system should check `http://<server>:8088/healthz` regularly – e.g. Home Assistant (`rest` sensor + automation) or a Healthchecks check on another server.
