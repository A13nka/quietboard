# Changelog

Alle nennenswerten Änderungen. Versionen folgen [Semantic Versioning](https://semver.org/lang/de/);
Releases entstehen mit `make release VERSION=X.Y.Z`: Image-Tags `vX.Y.Z`, `vX.Y`, `vX`, `latest` und ein GitHub-Release
mit Quellcode, Installationspaket, `install.sh`, `compose.yaml`, SBOM und Prüfsummen.

## Unveröffentlicht

## 0.9.0 – 2026-11-27

### Hinweis zur Anbindung der Hosts
Abwärtskompatibel: Hosts mit älteren Skripten und das gemeinsame `INGEST_TOKEN` funktionieren unverändert weiter.

- **Neu angebundene Hosts** bekommen bei der Installation ein **eigenes Melde-Token**. Es gilt nur für ihren
  eigenen Namen und lädt keinen Installer.
- **Bestehende Hosts** holen es sich mit `upgrade-host.sh --apply --register`. Dabei ändert sich nur der Wert von
  `STATUS_INGEST_TOKEN` in `/etc/hc.conf`.
- Unter *System → Melde-Tokens der Hosts* stehen alle Tokens. Dort lässt sich das gemeinsame Token abschalten,
  sobald es niemand mehr nutzt (die Liste zeigt, wer es zuletzt benutzt hat).

### Neu
- Tokens je Host:
  - Ein übernommener Host kann keine Berichte mehr für andere Hosts schicken und den Installer mit allen Zugangsdaten
    nicht laden.
  - Ist das gemeinsame Token abgeschaltet, enthält der Befehl aus „Host hinzufügen“ ein Installer-Token, das nach
    1 h abläuft.
- Warnung (Log und System), wenn ein Proxy vor der App sitzt, der nicht in `TRUSTED_PROXIES` steht.
- CI prüft die festgelegten Pakete mit `pip-audit`.

### Behoben
- Sicherheit:
  - FastAPI/starlette, uvicorn, PyJWT und PyYAML auf aktuelle Versionen mit bekannten Lücken-Behebungen.
  - Enge Größengrenzen für Anfragen: Ein großer JSON-Körper an die Anmeldung konnte die App ohne Konto zum Absturz
    bringen. Das Speicherlimit der App steigt auf 192 MB.
  - `CF-Connecting-IP` gilt nur noch von `cloudflared` (`CLOUDFLARE_PROXIES`). Hinter Nginx Proxy Manager & Co.
    konnte ein Client seine Adresse sonst selbst wählen.
  - Viele Fehlversuche auf ein Konto bremsen es (ein Versuch je 30 s), statt es zu sperren – sonst ließe es sich von
    außen dauerhaft blockieren.
  - Push-Geräte werden beim Abmelden und beim Löschen eines Kontos entfernt.
  - Auch ohne Anmeldung (`ALLOW_NO_AUTH`, nur für Tests) werden schreibende Anfragen fremder Seiten abgewiesen.
- Alarme:
  - Nach dem Zurückschalten der Job-Alarme auf Healthchecks bekommen Jobs, die im Modus „QuietBoard“ angelegt
    wurden, wieder Integrationen.
  - „Security-Update überfällig“ wird wiederholt, bis die Meldung zugestellt ist.
  - Ein nie zugestellter, von selbst behobener Ausfall führt später nicht mehr zu „War 3 d ausgefallen“.
  - Ein gelöschtes Lebenszeichen `quietboard/app` wird neu angelegt (`HEARTBEAT=0` schaltet es ab).
- Hosts:
  - Der Synology-Installer funktioniert auch über sudo.
  - Den Host-Befehl erneut ausführen, während `unattended-upgrades` läuft, bricht nicht mehr ab (apt wartet bis 5 min auf die Sperre).
  - `updates-report` erkennt Security-Updates auch, wenn apt hinter der Quelle noch Abhängigkeiten anhängt.
- Ein Fehler von Docker Hub (z. B. 429) löscht keine bekannten Image-Updates mehr.
- Doku: Ein Proxy direkt auf dem Server braucht das Gateway des Docker-Netzes in `TRUSTED_PROXIES`.

## 0.8.0 – 2026-11-26

Nur der Server ändert sich; Hosts brauchen nichts.

### Behoben
- Oberfläche: Aufgeklappte Abschnitte und noch nicht gespeicherte Eingaben bleiben beim automatischen Neuladen (alle 30 s) erhalten.
- Ist der Server nicht erreichbar, zeigt die App den letzten Stand deutlich als „offline – Stand vom …“ (mit Datum, wenn nicht von heute) statt ihn als aktuell auszugeben.
- Datendateien werden dauerhaft gespeichert (fsync, atomar). Eine unlesbare Datei wird als `*.kaputt-<Zeit>` beiseitegelegt statt beim nächsten Speichern überschrieben.
- Fehlerhafte Eingaben an Ingest- und Push-Routen ergeben 400 statt 500; Meldungen mit ungewöhnlichem Inhalt (Liste, reiner Text) kommen trotzdem an.
- Der letzte lokale Admin kann nicht mehr herabgestuft werden (auch nicht von Admins über Cloudflare Access); unbekannte Konten ergeben 404.
- Höchstens 10 Push-Geräte pro Konto.
- Fehlermeldungen wie „Job … gibt es schon“ erscheinen jetzt auch auf Englisch.
- `install.sh` schreibt sein Log in eine eigene Temp-Datei.

### Intern
- Lieferkette:
  - GitHub Actions auf Commit-Hashes, Basis-Image `python:3.13.18-slim` per Digest; Dependabot hält sie aktuell.
  - Alle Python-Abhängigkeiten mit Prüfsummen in `requirements.lock` (`make lock`); das Image installiert nur diese Datei.
- CI: gitleaks prüft die ganze Git-Historie; Images werden erst nach bestandener CI gebaut.
- `app/sources.py`: PBS-Abruf und Versionsvergleich aus `main.py` herausgelöst.

## 0.7.0 – 2026-11-26

### Hinweis zur Anbindung der Hosts
Der Server lässt sich allein aktualisieren – Hosts mit älteren Skripten melden weiter wie bisher. Die neuen Fassungen
von `hc` und `updates-report` bekommen Hosts auf zwei Wegen:

- **Mit QuietBoard eingerichtet:** den Befehl aus *System → Host hinzufügen* erneut ausführen.
- **Von Hand oder mit älteren Skripten eingerichtet:** `hosts/upgrade-host.sh` aus dem Release-Paket. Es tauscht nur
  diese zwei Dateien, prüft vorher und zeigt, was sich ändert, und kann alles zurückdrehen (siehe
  [Aktualisieren → Hosts von Hand](docs/install/update.md)).

Zwei Änderungen im Verhalten:

- `hc ping` liest Text von stdin nur noch mit `-` am Ende (`… | hc ping <slug> log -`). Das Umstellungsskript
  findet solche Stellen und ergänzt das `-` auf Wunsch.
- `hc` und `updates-report` brauchen `HC_PING_BASE` und `STATUS_INGEST_URL` in `/etc/hc.conf`. Ältere Fassungen hatten
  dafür einen eingebauten Standard.

### Behoben
- **`hc run` führt den Befehl immer aus,** auch wenn die Konfiguration fehlt oder nicht lesbar ist (vorher brach es ab, und z. B. das Backup lief gar nicht). Der Start-Ping wartet nur noch 20 s statt bis zu 2 min. Für Jobs ohne root: `/etc/hc-ping.conf` (nur Ping-Daten).
- **`updates-report`:** Scheitert `apt`, meldet der Host einen Fehler statt „alles aktuell“, die App behält den letzten Stand und zeigt den Fehler. „Security“ nur noch aus der Paketquelle, nicht aus dem Paketnamen. Berichte älter als 3 Tage erscheinen als „veraltet“.
- **Host-Installer:** behält eigene Zeilen in `/etc/hc.conf` (z. B. `MAILCOW_DIR`) und den bisherigen Host-Namen; neue Hosts heißen `hostname -s` in Kleinbuchstaben. Werte werden gequotet, das Agent-Programm gegen seine Prüfsumme geprüft, und beim sudo-Weg stehen die Zugangsdaten nicht mehr in der Prozessliste. Vor dem Ersetzen eines fremden `beszel-agent`-Containers kommt ein Hinweis.
- `generate-env.sh`: Fehlte der Zeilenumbruch am Ende der `.env`, wurde der erste neue Wert an den letzten angehängt (Secret unbrauchbar).
- `install.sh` aus `main` installiert die neueste Release-Version (Dateien und Image passen zusammen); `QB_VERSION=v0` oder `latest` funktionieren, gleitende Tags in `.env` bleiben beim erneuten Ausführen. Warnung bei öffentlicher Adresse ohne `BIND_ADDR`.
- `healthchecks-init` bricht mit Erklärung ab, wenn `ADMIN_EMAIL` geändert wurde, statt ein zweites Konto mit neuen Keys anzulegen; die Schlüsseldatei bleibt nicht im Init-Container liegen.
- Ping-Key von Healthchecks und Push-Adressen stehen nicht mehr im Klartext im Log.

### Neu
- PBS: Zertifikat per Fingerprint, eigener CA oder öffentlicher CA prüfen (5. Feld in `PBS_TARGETS`). Ohne Angabe wie bisher ungeprüft, mit Warnung im Log.

### Doku
- Netzwerk: Docker umgeht ufw – Beispiel mit `DOCKER-USER`; Host-Befehl nur im LAN, per VPN oder über HTTPS.
- Sicherung und Umzug brechen bei Fehlern ab, prüfen die Archive und sichern `compose.override.yaml` mit.
- Aktualisieren bei fester Version in `.env`; Agent-Benutzer und Gruppe `docker`.

## 0.6.0 – 2026-11-26

### Neu
- **Job-Alarme über QuietBoard:** kurze, einheitliche Meldungen über alle Kanäle (Push, Mail, Signal) – „fehlgeschlagen“ mit Exitcode und letzten Logzeilen, „überfällig“ mit letzter Meldung und Zeitplan, „wieder OK“ mit Ausfalldauer. Mehrere Ausfälle eines Abrufs kommen in einer Nachricht. Umschaltbar unter System → Job-Alarme; übernommene Installationen bleiben bei Healthchecks, bis du umstellst (Integrationen werden dabei gesichert und lassen sich wiederherstellen).
- **Lebenszeichen `quietboard/app`:** QuietBoard meldet sich bei jedem Abruf in Healthchecks; steht die App, meldet Healthchecks das selbst.
- Meldung, wenn Healthchecks oder Beszel länger als 15 Minuten nicht erreichbar sind; „Braucht Aufmerksamkeit“ und Morgenmeldung zeigen fehlende Quellen statt „alles grün“.
- `hc run` hängt Exitcode und Dauer ans Log an (für die Meldung). Hosts bekommen die neue Fassung mit dem Befehl aus „Host hinzufügen“.
- `PUBLIC_URL` für Links in Meldungen.

### Behoben
- Bearbeiten eines Jobs, Prioritätsänderung und YAML-Import setzten die Integrationen des Jobs in Healthchecks auf „E-Mail“ zurück; eigene Tags ohne Doppelpunkt gingen verloren. Jetzt bleiben sie; bei einer Prioritätsänderung werden nur die von QuietBoard verwalteten Integrationen getauscht. `hc_sync` setzt Kanäle nur noch, wenn `checks.yaml` sie festlegt.
- Gleiche Meldungen wurden nur nach Titel zusammengefasst: „down → up → down“ innerhalb von 30 Minuten verschluckte den zweiten Ausfall, und gleiche Titel verschiedener Hosts gingen verloren. Fehlgeschlagener Versand blockierte die Wiederholung. Unterdrückung jetzt nach Quelle und Zustand, erst nach erfolgreicher Zustellung, und übersteht Neustarts.
- Proxmox-Webhook: Nahm Healthchecks den Ping nicht an (Job gelöscht, Slug doppelt), ging die Meldung still verloren – jetzt meldet QuietBoard sie selbst.
- Meldungen aus eigenen Quellen (`source=nas`, `synology`, `dockhand` …) erscheinen unter „Braucht Aufmerksamkeit“.
- Neue Jobs, die gleich beim ersten Lauf ausfallen, werden gemeldet.
- Zwei Jobs mit derselben Ping-Adresse (z. B. `nightly.db` und `nightly-db`) werden abgelehnt.
- YAML-Import prüft erst alles und schreibt bei einem Fehler nichts; vorhandene Checks mit ungewöhnlichen Namen und OnCalendar-Zeitplänen lassen sich aktualisieren.
- `checks.yaml`: einzelne fehlerhafte Einträge (`digest_time: 10:30` ohne Anführungszeichen, leerer Host-Eintrag, `watch_images` ohne Image) werden übersprungen und gemeldet, statt Oberfläche oder Morgenmeldung lahmzulegen.
- Abrufe laufen nicht mehr gleichzeitig (konnte Beszel-Alarme doppelt anlegen).
- Beszel: ein ungültig gewordener App-Zugang wird neu eingerichtet; mit `BESZEL_APP_USER` funktioniert „Host hinzufügen“.
- Web Push: zu lange Nachrichten (Emojis) werden nach Bytes gekürzt.

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
