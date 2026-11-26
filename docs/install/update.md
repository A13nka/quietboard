# Aktualisieren und Versionen

## Versionen

| Tag | Bedeutung |
| --- | --- |
| `latest` | neueste stabile Version |
| `v0` / `v0.1` | neueste Version innerhalb von 0.x bzw. 0.1.x – automatisch Fehlerkorrekturen, keine großen Sprünge |
| `v0.1.0` | genau diese Version |
| `edge` | aktueller Entwicklungsstand (`main`), nur zum Testen |

Die Version steht in `.env` als `QB_VERSION`. Der Installer trägt die neueste Release-Version fest ein (z. B. `v0.6.1`).

**Wichtig:** Steht dort eine feste Version, holt `docker compose pull` immer wieder genau diese. Aktualisieren heißt dann:
den Installer erneut ausführen (er stellt eine feste Version auf die neueste um) oder den Wert in `.env` von Hand ändern.
Wer Fehlerkorrekturen automatisch möchte, trägt `QB_VERSION=v0` oder `v0.6` ein – solche gleitenden Tags lässt der
Installer stehen.

## Aktualisieren

```bash
cd ~/quietboard
docker compose pull && docker compose up -d
```

Neue Fassungen von `compose.yaml` (z. B. neue Dienste oder Upstream-Versionen von Healthchecks/Beszel) kommen mit dem Installer – erneutes Ausführen ist gefahrlos, `.env` und alle Daten bleiben:

```bash
curl -fsSL https://github.com/A13nka/quietboard/releases/latest/download/install.sh | bash
```

Vor größeren Versionssprüngen: [Sicherung](backup.md) und [Changelog](https://github.com/A13nka/quietboard/blob/main/CHANGELOG.md) lesen.

## Hosts aktualisieren

Den Befehl aus **System → Host hinzufügen** erneut ausführen – er ersetzt Agent, `hc` und Update-Bericht durch die aktuelle Fassung und lässt die Anmeldung beim Hub bestehen.

### Hosts von Hand (ohne Installer)

Für Hosts, die von Hand oder mit älteren Skripten eingerichtet wurden, oder wenn nur `hc` und `updates-report`
erneuert werden sollen: Das Release-Paket enthält `hosts/upgrade-host.sh`. Es tauscht **nur** diese zwei Dateien.
Agent, Timer, apt-Hook und Sicherheitsupdates bleiben unberührt, kein Dienst wird neu gestartet.

```bash
V=v0.7.0                                   # gewünschte Version
W=$(mktemp -d) && cd "$W"
curl -fsSLO "https://github.com/A13nka/quietboard/releases/download/$V/quietboard-$V.tar.gz"
curl -fsSLO "https://github.com/A13nka/quietboard/releases/download/$V/SHA256SUMS"
sha256sum -c --ignore-missing SHA256SUMS   # muss „OK“ zeigen
tar -xzf "quietboard-$V.tar.gz"
sudo bash "quietboard-$V/hosts/upgrade-host.sh"            # 1. prüfen – ändert nichts
sudo bash "quietboard-$V/hosts/upgrade-host.sh" --apply    # 2. austauschen
```

Die Prüfung zeigt:

- welche Dateien sich ändern;
- welche Schlüssel in `/etc/hc.conf` stehen (ohne Werte) und welche fehlen;
- welche Skripte oder Cron-Einträge Text in `hc ping` pipen. Sie brauchen künftig ein `-` am Ende; mit `--apply --fix-stdin` ergänzt das Skript es.

Fehlen `HC_PING_BASE` oder `STATUS_INGEST_URL`, die Werte mitgeben:

```bash
sudo QB_PING_BASE=http://<server>:8000/ping QB_INGEST_URL=http://<server>:8088/api/ingest/updates \
  bash "quietboard-$V/hosts/upgrade-host.sh" --apply
```

Die alten Fassungen bleiben als `*.bak-qb` liegen. Zurück geht es mit `sudo bash …/upgrade-host.sh --rollback`.
