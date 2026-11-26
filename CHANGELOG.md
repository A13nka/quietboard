# Changelog

Alle nennenswerten Änderungen. Versionen folgen [Semantic Versioning](https://semver.org/lang/de/);
Releases entstehen mit `make release VERSION=X.Y.Z`: Image-Tags `vX.Y.Z`, `vX.Y`, `vX`, `latest` und ein GitHub-Release
mit Quellcode, Installationspaket, `install.sh`, `compose.yaml`, SBOM und Prüfsummen.

## Unveröffentlicht

## 0.5.3 – 2026-11-26

### Sicherheit
- Zugriffsschutz und Anmeldung gehärtet. Allen Installationen wird das Update empfohlen; Details folgen nach dem Release (siehe `SECURITY.md`).
- Weitergeleitete Header (`X-Forwarded-For`, `X-Forwarded-Proto`) gelten nur noch von vertrauten Proxys (`TRUSTED_PROXIES`, Standard `cloudflared`). Wer einen anderen Reverse-Proxy vor der App betreibt, trägt dessen Containernamen oder Netz dort ein.
- Schreibende Anfragen aus dem Browser müssen von der eigenen Seite kommen und JSON senden – jetzt auch bei Anmeldung über Cloudflare Access.
- Login-Sperre zusätzlich je Konto; Passwortänderung meldet alle anderen Sitzungen ab; Test-Mitteilungen nur für Admins.
- Antworten mit Sicherheits-Headern (kein Einbetten in fremde Seiten); Ingest-Token erscheint nicht mehr im Zugriffslog.

### Behoben
- Proxmox-Webhook: War `checks.yaml` fehlerhaft oder fehlte sie, antwortete die App mit Fehler 500 und das Ereignis ging verloren. Sehr lange Meldungen werden gekürzt statt abgelehnt; ein gekürzter Fehler bleibt ein Fehler.
- Die Warnung zu `checks.yaml` verschwindet, sobald die Datei wieder lesbar ist (vorher erst nach einem Neustart).
- Docker meldet den Container beim Start nicht mehr kurz als „unhealthy“.

## 0.5.2 – 2026-11-26

### Behoben
- `hc`, `updates-report`, `dsm-report`: wiederholen jetzt auch bei „Verbindung abgelehnt“ (bis zu 2 Minuten). Startete Healthchecks gerade neu – etwa durch ein nächtliches Volume-Backup –, ging die Abschlussmeldung eines Jobs verloren und der Job wurde rot. Hosts bekommen die neue Fassung mit dem Befehl aus „Host hinzufügen“.
- iOS-App: Die Leiste unten verrutschte auf kurzen Seiten (z. B. Updates) nach oben.
- Updates: Mehrere Docker-Berichte eines Hosts zeigten das Schild „docker“ mehrfach.

## 0.5.1 – 2026-11-25

### Behoben
- Beszel: Gibt es schon einen Webhook zur App (z. B. einer Vorgänger-App unter `status-app`), legt QuietBoard keinen zweiten an – sonst kam jeder Alarm doppelt.

### Geändert
- Übernahme: Der bisherige Beszel-Login kann als `ADMIN_EMAIL` weiterverwendet werden (Doku).

## 0.5.0 – 2026-11-25

### Neu
- **Bestehende Healthchecks/Beszel-Installation übernehmen** (Doku DE/EN): Sind `HC_API_KEY` und `HC_PING_KEY` gesetzt, ändert `healthchecks-init` nichts mehr (vorher wurden API-Key und Admin-Passwort neu gesetzt). Der App-Container ist zusätzlich als `status-app` erreichbar. e2e prüft beides.

## 0.4.1 – 2026-11-25

### Neu
- **Installer auf Englisch:** `install.sh` spricht Deutsch bei deutscher Server-Locale, sonst Englisch; `LANGUAGE=de|en` erzwingt eine Sprache.
- **Weitere NAS** (UGREEN, QNAP, TrueNAS SCALE, Unraid, OMV): Doku-Seite mit Wegen für Agent, Update-Berichte und Jobs – ausdrücklich ungetestet.
- **Englische Dokumentation** unter `/en/` mit Sprachumschalter; das englische README verlinkt dorthin.

### Geändert
- Doku: Zeitfenster-NAS über die Oberfläche statt `checks.yaml`, FAQ zu Chrome/macOS („Lokales Netzwerk“) und zum Server als eigenem Host, aktuelle Speicherangaben.

## 0.4.0 – 2026-11-25

### Neu
- **Englische Oberfläche:** Anmeldung und App auf Deutsch und Englisch; Sprache nach Browser, umstellbar unter System → Konto. Ein Test stellt sicher, dass jeder Text eine Übersetzung hat.
- **Sprache der Meldungen** (Morgenmeldung, Push, Mail, Signal, „Braucht Aufmerksamkeit“) unter System → Benachrichtigungen; Vorbelegung mit `LANGUAGE` in `.env`.

## 0.3.0 – 2026-11-25

### Neu
- **Host-Einstellungen in der Oberfläche:** „läuft dauerhaft“ (sonst Zeitfenster, z. B. NAS nachts) und Weblinks je Host; haben Vorrang vor `checks.yaml`. **Host entfernen** löscht ihn in Beszel samt Verlauf, Update-Berichten und Einstellungen.
- **API-Tokens** für eigene Skripte (System → API-Tokens): Rechte wie das Konto, nur einmal sichtbar, „zuletzt benutzt“, widerrufbar.
- **YAML-Export/-Import** (System → Konfiguration): Jobs inkl. Proxmox-Zuordnung und Host-Einstellungen im `checks.yaml`-Format; Import mit Vorschau, löscht nie.

## 0.2.4 – 2026-11-25

### Geändert
- `install.sh` zeigt, welche Images geladen werden, mit dem Docker-Fortschritt (statt still im Hintergrund).

## 0.2.3 – 2026-11-25

### Behoben
- Anmeldeseite zeigte nach der Einrichtung weiterhin die Felder „Einrichtungscode“ und „Name“ (CSS überstimmte `hidden`).

## 0.2.2 – 2026-11-25

### Geändert
- `install.sh` zeigt den Einrichtungscode nur noch, solange kein Konto existiert (beim Update erschien sonst der alte Code).
- `install.sh` nennt den Installationsordner (`QB_DIR`, Standard `~/quietboard`) und zeigt am Ende nummerierte nächste Schritte – inklusive „diesen Server selbst als Host anbinden“.

### Behoben
- Beszel-Agent als Binary: eigenes beschreibbares `/tmp` (`PrivateTmp`), damit die Health-Datei angelegt werden kann (vorher „read-only file system“ im Journal).

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
