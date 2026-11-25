# Changelog

Alle nennenswerten Änderungen. Versionen folgen [Semantic Versioning](https://semver.org/lang/de/);
Releases entstehen mit `make release VERSION=X.Y.Z`: Image-Tags `vX.Y.Z`, `vX.Y`, `vX`, `latest` und ein GitHub-Release
mit Quellcode, Installationspaket, `install.sh`, `compose.yaml`, SBOM und Prüfsummen.

## Unveröffentlicht

## 0.1.1 – 2026-11-25

### Neu
- Dokumentation (MkDocs): Installation, Netzwerk (LAN, VPN, Tailscale/NetBird, Reverse Proxy, Cloudflare Tunnel), Update, Sicherung, Hosts, Proxmox, Synology, Jobs, Benachrichtigungen, Konten, Referenz, FAQ. README auf Englisch und Deutsch, CONTRIBUTING, SECURITY.
- Synology: Host-Installer erkennt DSM, installiert `hc` und `dsm-report`, behält einen vorhandenen Binary-Agent.
- „Host hinzufügen“ zeigt auch die Agent-Werte für manuelle Einrichtung (Docker-Stack, NAS, vorhandener Agent).
- `HC_EXTRA_HOSTS`: weitere Namen, unter denen Healthchecks erreichbar ist.

### Behoben
- Release: SBOM wurde wegen Großbuchstaben im Image-Namen nicht erzeugt.

## 0.1.0 – 2026-11-24

### Neu
- Selbsteinrichtung: Healthchecks (Admin, Projekt, Keys, Mail-Integration) und Beszel (Benutzer, Agent-Token) ohne Klicks in deren Oberflächen.
- Installation mit einem Befehl (`install.sh`), jeder Host mit einem Befehl (`/api/install/host.sh`); Beszel-Agent als Docker-Container oder Binary.
- Lokale Konten (Admin, Betrachter) mit Einrichtungscode beim ersten Start, Login-Sperre nach Fehlversuchen, Notfall-CLI (`python -m tools.cli`).
- Tab „System“: Konto, Host hinzufügen, Benachrichtigungen (Mail, Web Push, Signal) mit „Test senden“, Morgenmeldung, Benutzer, Zustand der Motoren.
- Mail als Kanal (SMTP aus `.env`), Checks in der Oberfläche pausieren und priorisieren.
- Releases für Code und Images; Version wählbar mit `QB_VERSION` (z. B. `v0.1.0`, `v0`, `latest`, `edge`).
- Beszel-Alarme werden automatisch eingerichtet: Webhook an die App, je Host Status (5 min), Disk > 90 %, RAM > 95 %. Ausfall → Push, Mail, Signal.

### Behoben
- Morgenmeldung nur noch im Zeitfenster nach der eingestellten Uhrzeit (kam nach einer Installation am Abend sofort).
- `hc ping` hing bei offener Standardeingabe; Text jetzt nur mit `-`.
- Installer funktioniert auch ohne `sudo` (root-only-Systeme) und bricht nicht mehr still ab.

### Sicherheit
- Beszel-Webhook nimmt nur noch Meldungen vom Beszel-Container oder mit Token an.
- Healthchecks `ALLOWED_HOSTS` aus den öffentlichen Adressen statt `*`.
