# Referenz: `.env`

`install.sh` bzw. `generate-env.sh` legt `.env` an und füllt alle Secrets. Werte, die per Umgebung an `install.sh` übergeben werden (z. B. `ADMIN_EMAIL=… TZ=… bash`), landen ebenfalls dort. Nach Änderungen: `docker compose up -d`.

## Grundeinstellungen

| Variable | Standard | Bedeutung |
| --- | --- | --- |
| `ADMIN_EMAIL` | – (Pflicht) | Admin-Login für Healthchecks und Beszel, erster Mail-Empfänger |
| `TZ` | `Europe/Berlin` | Zeitzone für Morgenmeldung und Anzeige |
| `SITE_NAME` | `Homelab` | Name in Oberfläche und Meldungen |
| `HC_PUBLIC_URL` | `http://<erste IP>:8000` | Adresse der Healthchecks-Oberfläche |
| `HC_PING_ENDPOINT` | `http://<erste IP>:8000/ping/` | Ping-Adresse, die Hosts verwenden |
| `BESZEL_PUBLIC_URL` | `http://<erste IP>:8090` | Hub-Adresse für Agents und Browser |
| `QB_VERSION` | `latest` | App-Version: `latest`, `v0`, `v0.4`, `v0.4.0`, `edge` |

## Secrets (automatisch erzeugt)

| Variable | Bedeutung |
| --- | --- |
| `ADMIN_PASSWORD` | Passwort für Healthchecks- und Beszel-Admin |
| `HC_SECRET_KEY` | Django-Secret von Healthchecks (signiert u. a. die API-Keys) |
| `INGEST_TOKEN` | Token der Hosts für Update-Berichte, Meldungen und den Host-Installer |
| `VAPID_PRIVATE_KEY` | Schlüssel für Web Push |

## Optional

| Variable | Bedeutung |
| --- | --- |
| `BIND_ADDR` | nur auf dieser Adresse lauschen (z. B. VPN-IP) |
| `HC_EXTRA_HOSTS` | weitere Namen/IPs, unter denen Healthchecks erreichbar sein soll (Komma-getrennt) |
| `STATUS_PORT`, `HC_PORT`, `BESZEL_PORT` | andere Host-Ports (Standard 8088, 8000, 8090) |
| `LANGUAGE` | Sprache der Meldungen (`de` oder `en`, Standard `de`), solange sie nicht in der App umgestellt wurde |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_TLS`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` | Mail für QuietBoard und Healthchecks |
| `VAPID_SUBJECT` | Kontakt für Push-Dienste (`mailto:…`) |
| `BESZEL_ALERT_DOWN_MIN` | Minuten bis zum Offline-Alarm neuer Hosts (Standard 5) |
| `POLL_SECONDS` | Abrufintervall der Motoren (Standard 60) |
| `PBS_TARGETS` | Proxmox-Backup-Server: `name\|url\|tokenid\|secret`, mehrere mit `;` |
| `SIGNAL_NUMBER`, `SIGNAL_RECIPIENT` | Signal (Profil `signal`) |
| `TUNNEL_TOKEN` | Cloudflare Tunnel (Profil `tunnel`) |
| `ACCESS_TEAM`, `ACCESS_AUD` | Cloudflare Access als Anmeldung |
| `HC_API_KEY`, `HC_PING_KEY`, `BESZEL_APP_USER`, `BESZEL_APP_PASS` | bestehende Healthchecks/Beszel statt Selbsteinrichtung |
| `STATUS_IMAGE` | ganz anderes Image (z. B. lokal gebaut) |
| `DEMO` | Beispieldaten statt echter Motoren |
| `ALLOW_NO_AUTH` | **nur für Tests:** App ohne Anmeldung |
