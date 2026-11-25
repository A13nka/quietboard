# Changelog

Alle nennenswerten Änderungen. Versionen folgen [Semantic Versioning](https://semver.org/lang/de/);
Releases entstehen mit `make release VERSION=X.Y.Z`: Image-Tags `vX.Y.Z`, `vX.Y`, `vX`, `latest` und ein GitHub-Release
mit Quellcode, Installationspaket, `install.sh`, `compose.yaml`, SBOM und Prüfsummen.

## Unveröffentlicht

## 0.2.1 – 2026-11-25

### Behoben
- Listen auf schmalen Bildschirmen: Host- und Job-Namen werden nicht mehr abgeschnitten („docke…“). Bei Platzmangel werden zuerst die kleinen Schilder ausgeblendet, dann bricht die Zusatzinfo rechts um; nur sehr lange Titel werden gekürzt.

## 0.2.0 – 2026-11-25

### Neu
- **Jobs in der Oberfläche anlegen, bearbeiten und löschen** – mit Vorlagen (Backup-Skript, Cronjob, Zertifikat, Proxmox VE, Proxmox Backup Server, Software mit Ping-URL). Nach dem Anlegen und in jeder Job-Zeile steht eine fertig ausgefüllte Anleitung (hc-Befehl, Cron-Zeile, Ping-Adresse oder Proxmox-Webhook) mit Kopieren-Knöpfen. `checks.yaml` bleibt als Alternative.
- Proxmox-Webhooks treffen auch Jobs, die in der Oberfläche angelegt wurden.
- `QB_DATA_DIR=/pfad` beim Installieren: Daten in Ordnern statt Docker-Volumes; Doku „Daten in eigenen Ordnern“ inkl. Umzug bestehender Installationen.
- Knopf ↻ holt die Daten sofort neu; neue Hosts erscheinen direkt nach ihrem ersten Bericht.

### Behoben
- Übersicht zeigte „0/0 Hosts“, solange Hosts nicht in `checks.yaml` eingetragen waren – jetzt zählen alle Hosts (außer solchen mit Zeitfenster).
- „Kopieren“ funktionierte ohne HTTPS (Zugriff über `http://<IP>`) nicht.
- Prioritätswechsel stellt jetzt auch die Benachrichtigungswege in Healthchecks passend ein.

## 0.1.2 – 2026-11-25

### Geändert
- Name in der Oberfläche, in Meldungen und in der Doku: **QuietBoard** (technische Namen wie Image, Ordner und Volumes bleiben `quietboard`).
- Neues Repository mit frischer Historie; README auf Englisch und Deutsch neu gestaltet (Screenshots, Schnellstart, Diagramm), Logo in der Doku.

### Neu
- `AGENTS.md` mit Regeln für Mitwirkende und Coding-Agents; `make screenshots` erzeugt die README-Bilder aus dem Demo-Modus.

### Behoben
- `install.sh`: Der Hinweis „Host-Installer noch nicht bereit“ zeigte den Einrichtungscode statt des HTTP-Status.
- `generate-env.sh` brach auf macOS ohne Meldung ab (`hostname -I` fehlt dort).
- Release-Workflow: Image-Name für die SBOM wird aus dem Repository abgeleitet statt fest eingetragen.

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
