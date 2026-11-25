# Aktualisieren und Versionen

## Versionen

| Tag | Bedeutung |
| --- | --- |
| `latest` | neueste stabile Version (Standard) |
| `v0` / `v0.1` | neueste Version innerhalb von 0.x bzw. 0.1.x – automatisch Fehlerkorrekturen, keine großen Sprünge |
| `v0.1.0` | genau diese Version |
| `edge` | aktueller Entwicklungsstand (`main`), nur zum Testen |

Die Version steht in `.env` als `QB_VERSION` (fehlt sie, gilt `latest`; aus einem Release installiert ist sie fest eingetragen).

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
