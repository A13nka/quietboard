# Netzwerk und HTTPS

QuietBoard braucht drei Ports. Alles andere bleibt im Docker-Netz.

| Port | Dienst | Wer muss ihn erreichen |
| --- | --- | --- |
| 8088 | App (Oberfläche, Ingest, Host-Installer) | Browser, Handy, alle Hosts |
| 8000 | Healthchecks (Pings, Admin-Oberfläche) | Hosts, die Jobs melden; Admin |
| 8090 | Beszel-Hub | Beszel-Agents auf den Hosts; Admin |

## Muss etwas ins Internet?

**Nein.** QuietBoard funktioniert vollständig im eigenen Netz – ohne Portfreigabe im Router, ohne Cloudflare, ohne öffentliche Domain. Hosts, Jobs, Updates, Alarme per Mail und Signal laufen alle intern. Nur zwei Dinge brauchen mehr:

| Wunsch | Was nötig ist |
| --- | --- |
| Übersicht unterwegs auf dem Handy | ein VPN ins Heimnetz (WireGuard, Tailscale, NetBird) – **oder** eine HTTPS-Freigabe (Reverse Proxy, Cloudflare Tunnel) |
| **Web Push** (Mitteilungen aufs Handy) | **HTTPS** mit gültigem Zertifikat – auch im LAN. Am einfachsten über Tailscale (siehe unten) oder einen Reverse Proxy mit eigener Domain |
| Mail-Benachrichtigungen | nur ausgehend: Zugang zu einem SMTP-Server |

Freigeben (wenn überhaupt) nur **Port 8088** (die App). Healthchecks (8000) und Beszel (8090) brauchen nur die eigenen Hosts – also LAN oder VPN, nie das offene Internet.

`BIND_ADDR` in `.env` legt fest, auf welcher Adresse die Ports lauschen (Standard: alle). Die Adressen, unter denen Hosts den Server erreichen, stehen in `HC_PUBLIC_URL`, `HC_PING_ENDPOINT` und `BESZEL_PUBLIC_URL`; `install.sh` setzt sie auf die erste IP des Servers. Nach einer Änderung: `docker compose up -d`.

## Variante 1: alles im selben LAN

Nichts weiter zu tun. Ports nicht ins Internet freigeben. Für Web Push auf dem Handy fehlt nur HTTPS (siehe unten).

## Variante 2: VPS als Zentrale, Hosts zu Hause (WireGuard oder Tailscale)

1. VPS und Heimnetz per WireGuard oder Tailscale verbinden.
2. In `.env` die VPN-Adresse des VPS eintragen und nur dort lauschen:
   ```ini
   BIND_ADDR=10.20.0.1
   HC_PUBLIC_URL=http://10.20.0.1:8000
   HC_PING_ENDPOINT=http://10.20.0.1:8000/ping/
   BESZEL_PUBLIC_URL=http://10.20.0.1:8090
   ```
3. `docker compose up -d`. Hosts bekommen ab jetzt den Installer-Befehl mit der VPN-Adresse.
4. Auf dem VPS die Ports zusätzlich in der Firewall sperren, z. B. `iptables -I DOCKER-USER -i <öffentliche-schnittstelle> -p tcp -m multiport --dports 8000,8080,8090 -j DROP` (Container-Ports, siehe DOCKER-USER-Kette).

## Variante 2b: Tailscale oder NetBird (Mesh-VPN)

Viele Homelabs verbinden ihre Rechner per Tailscale oder NetBird. Dann ist das VPN-Netz das „LAN“ für quietboard:

1. Tailscale/NetBird auf dem quietboard-Server und allen Hosts installieren.
2. Die Tailnet- bzw. NetBird-Adresse des Servers (z. B. `100.64.0.10` oder `quietboard.tailnet-name.ts.net`) als Adresse für die Hosts eintragen:
   ```bash
   cd ~/quietboard
   PUBLIC_HOST=100.64.0.10 ./generate-env.sh     # setzt leere Adressen; vorhandene in .env von Hand ändern
   docker compose up -d
   ```
   oder gleich bei der Installation: `… | PUBLIC_HOST=100.64.0.10 ADMIN_EMAIL=… bash`.
3. Optional `BIND_ADDR=100.64.0.10`, damit die Ports nur im VPN lauschen.
4. Die Hosts mit dem Befehl aus „Host hinzufügen“ anbinden – er enthält jetzt die VPN-Adresse.

**HTTPS für Web Push mit Tailscale:** `tailscale serve` stellt die App mit gültigem Zertifikat unter `https://<server>.<tailnet>.ts.net` bereit – nur für Geräte im Tailnet, ohne Portfreigabe:

```bash
sudo tailscale serve --bg 8088
```

Auf dem Handy (Tailscale-App aktiv) diese Adresse öffnen, zum Home-Bildschirm hinzufügen, Mitteilungen aktivieren. `tailscale funnel` würde die App zusätzlich öffentlich machen – nur nötig, wenn Geräte ohne Tailscale zugreifen sollen.

**NetBird:** gleiches Prinzip mit den NetBird-Adressen. Für HTTPS einen Reverse Proxy (unten) mit eigener Domain und DNS-Challenge verwenden – dann ist kein Port im Router nötig.

## Variante 3: Zugriff von außen über HTTPS

**Web Push braucht HTTPS** – auf dem iPhone zusätzlich die installierte App (Teilen → „Zum Home-Bildschirm“). Zwei Wege:

### Reverse Proxy (Caddy, Traefik, Nginx Proxy Manager)

Eine Subdomain auf `http://<server>:8088` zeigen lassen, z. B. mit Caddy:

```caddy
status.example.org {
    reverse_proxy 127.0.0.1:8088
}
```

Die App wertet `X-Forwarded-Proto` aus; Cookies sind dann automatisch „Secure“. Healthchecks und Beszel bei Bedarf genauso (eigene Subdomains), dann `HC_PUBLIC_URL`/`BESZEL_PUBLIC_URL` auf die HTTPS-Adressen setzen.

### Cloudflare Tunnel (Profil `tunnel`)

1. Cloudflare Zero Trust → Networks → Tunnels → Tunnel anlegen, Docker-Variante wählen, Token kopieren.
2. Public Hostname `status.example.org` → `http://status:8080` (Name des Containers im Compose-Netz).
3. In `.env`: `TUNNEL_TOKEN=…`, dann `docker compose --profile tunnel up -d`.

Optional davor **Cloudflare Access** (z. B. mit PocketID oder One-time PIN): `ACCESS_TEAM` und `ACCESS_AUD` in `.env` setzen. Wer durch Access kommt, ist in QuietBoard Admin; lokale Konten bleiben zusätzlich möglich.

## Externer Wächter

Fällt der quietboard-Server selbst aus, kann er das nicht melden. Ein zweites System sollte `http://<server>:8088/healthz` regelmäßig prüfen – z. B. Home Assistant (`rest`-Sensor + Automation) oder ein Healthchecks-Check auf einem anderen Server.
