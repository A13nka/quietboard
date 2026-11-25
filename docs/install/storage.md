# Daten in eigenen Ordnern

Standardmäßig liegen die Daten in Docker-Volumes (`quietboard_status-data` usw.). Wer sie lieber in normalen Ordnern hat – etwa auf einer eigenen Platte, für ein Backup-Programm, das Ordner sichert, oder einfach, um sie zu sehen –, stellt das mit einer kleinen Zusatzdatei um.

## Neue Installation

`QB_DATA_DIR` beim ersten Aufruf mitgeben:

```bash
curl -fsSL https://github.com/A13nka/quietboard/releases/latest/download/install.sh \
  | ADMIN_EMAIL=du@example.org QB_DATA_DIR=/srv/quietboard bash
```

Der Installer legt die Ordner mit den passenden Rechten an (ohne `sudo`, über einen kurzen Hilfscontainer) und schreibt `~/quietboard/compose.override.yaml`. Docker Compose liest diese Datei automatisch; Updates (`install.sh` erneut ausführen) lassen sie unverändert.

Danach sieht es so aus:

| Ordner | Inhalt | Besitzer (UID) |
| --- | --- | --- |
| `/srv/quietboard/status` | Konten, Einstellungen, Update-Berichte, Meldungen | 10001 |
| `/srv/quietboard/healthchecks` | Checks und Verlauf (SQLite) | 999 |
| `/srv/quietboard/beszel` | Hosts und Metriken | root |
| `/srv/quietboard/bootstrap` | automatisch erzeugte Zugänge für Healthchecks | root (Datei: 10001, nur lesbar für die App) |
| `/srv/quietboard/signal` | Signal-Konto (nur mit Profil `signal`) | root |

## Von bestehenden Volumes umziehen

!!! warning "Vorher sichern"
    Einmal nach [Sicherung](backup.md) sichern. Der Umzug kopiert erst und löscht die alten Volumes erst danach.

```bash
cd ~/quietboard
D=/srv/quietboard
docker compose --profile signal --profile tunnel down          # stoppt alles, Daten bleiben
docker run --rm -v "$D:/d" alpine:3.22 sh -c \
  'mkdir -p /d/status /d/healthchecks /d/beszel /d/bootstrap /d/signal'
for v in status:status-data healthchecks:healthchecks-data beszel:beszel-data bootstrap:bootstrap signal:signal-data; do
  docker run --rm -v "quietboard_${v#*:}:/from:ro" -v "$D/${v%%:*}:/to" alpine:3.22 cp -a /from/. /to/ 2>/dev/null || true
done
docker run --rm -v "$D:/d" alpine:3.22 sh -c 'chown -R 10001 /d/status && chown -R 999:999 /d/healthchecks'
```

Prüfen, dass die Daten angekommen sind (`ls -l $D/*`), dann die Zusatzdatei anlegen und die alten Volumes entfernen – Compose legt sie danach als Verweise auf die Ordner neu an:

```bash
cat > compose.override.yaml <<EOF
volumes:
  status-data:       { driver: local, driver_opts: { type: none, o: bind, device: $D/status } }
  healthchecks-data: { driver: local, driver_opts: { type: none, o: bind, device: $D/healthchecks } }
  beszel-data:       { driver: local, driver_opts: { type: none, o: bind, device: $D/beszel } }
  bootstrap:         { driver: local, driver_opts: { type: none, o: bind, device: $D/bootstrap } }
  signal-data:       { driver: local, driver_opts: { type: none, o: bind, device: $D/signal } }
EOF
docker volume rm quietboard_status-data quietboard_healthchecks-data quietboard_beszel-data quietboard_bootstrap quietboard_signal-data
docker compose up -d
```

In der App unter *System* prüfen, dass Healthchecks und Beszel verbunden sind und die Hosts wieder erscheinen.

## Sichern

Mit Ordnern reicht es, den Stack kurz anzuhalten und den Ordner zu kopieren:

```bash
cd ~/quietboard && docker compose stop
sudo tar czf ~/quietboard-backup.tgz -C /srv quietboard ~/quietboard/.env ~/quietboard/config
docker compose start
```

Die SQLite-Dateien nicht im laufenden Betrieb kopieren – die Kopie kann sonst unvollständig sein. Das Archiv enthält Zugangsdaten: nur verschlüsselt außer Haus lagern.

## Gut zu wissen

- `docker compose down -v` löscht bei Ordnern nur die Verweise, nicht die Daten.
- Netzlaufwerke (NFS/SMB) sind für die SQLite-Dateien ungeeignet – lokale Platte verwenden.
- Ordner auf einem NAS-Volume (z. B. Synology `/volume1/docker/quietboard`) funktionieren, solange Docker auf demselben Gerät läuft.
