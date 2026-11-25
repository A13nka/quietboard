# Synology

**Normalfall: Agent als Container.** Wie auf UGREEN, QNAP, Unraid oder TrueNAS läuft der Beszel-Agent auch auf einer Synology am einfachsten im *Container Manager* – als Projekt mit dem Docker-Stack aus [Hosts anbinden](index.md#docker-hosts-ohne-shell-zugriff-portainer-dockge-nas-oberflachen). Die Werte stehen in der App unter **System → Host hinzufügen → Befehl anzeigen → Manuell**.

Wer zusätzlich DSM-Updates und Jobs melden möchte oder Docker auf der NAS nicht nutzen will (Agent als Binary), nimmt den Installer-Befehl – siehe unten.

> Stand: vorbereitet, auf echter Hardware noch nicht abgenommen. Rückmeldungen bitte als Issue.

## Mit dem Befehl aus „Host hinzufügen“

Per SSH auf die Synology (*Systemsteuerung → Terminal & SNMP → SSH aktivieren*), root werden, Befehl ausführen:

```bash
sudo -i
curl -fsSL -H "Authorization: Bearer <token>" http://<server>:8088/api/install/host.sh | bash
```

Der Installer erkennt DSM und

- installiert `hc` und `dsm-report` nach `/usr/local/bin`, Konfiguration nach `/usr/local/etc/quietboard.conf` (übersteht DSM-Updates),
- meldet die verfügbaren Paket-Updates einmal sofort,
- **lässt einen vorhandenen Beszel-Agent in Ruhe** und zeigt die drei Werte an, die du dort einträgst:
  ```ini
  KEY=ssh-ed25519 AAAA…
  TOKEN=…
  HUB_URL=http://<server>:8090
  ```
  Danach den Agent neu starten – er meldet sich selbst an und erscheint unter „Hosts“.
- zeigt die Einträge für den Aufgabenplaner (siehe unten).

Lieber den Agent als Container (Container Manager muss installiert sein): `… | QB_AGENT_MODE=docker bash`.

Die drei Agent-Werte stehen auch in der App unter **System → Host hinzufügen → Befehl anzeigen → Manuell**.

## Agent als Binary (vorhandene Installation)

Wo die Werte stehen, hängt davon ab, wie der Agent installiert wurde:

| Installation | Werte ändern in |
| --- | --- |
| Beszel-Installskript / eigener Dienst | Umgebungsdatei bzw. Unit des Dienstes (`KEY`, `TOKEN`, `HUB_URL`), dann Dienst neu starten |
| Aufgabenplaner („Hochfahren“-Aufgabe startet den Agent) | im Skript der Aufgabe, dann Aufgabe einmal ausführen |

Der alte Eintrag des Systems im bisherigen Hub kann danach gelöscht werden.

## Aufgabenplaner

*Systemsteuerung → Aufgabenplaner → Erstellen*, Benutzer **root**:

1. **Geplante Aufgabe → Benutzerdefiniertes Skript**, täglich: `/usr/local/bin/dsm-report`
2. **Nur bei NAS, die nicht dauernd laufen** (z. B. nachts für Backups): *Ausgelöste Aufgabe → Hochfahren*:
   `/usr/local/bin/hc ping <name>-online`

## NAS mit Zeitfenster

Eine NAS, die nur nachts läuft, soll tagsüber keinen Alarm auslösen:

- In `config/checks.yaml` unter `hosts` mit `always_on: false` eintragen – die App zeigt sie dann als „aus (geplant)“ statt rot, und die Morgenmeldung nennt, wann sie zuletzt da war.
- Einen Check `<name>/online` mit dem Einschaltzeitpunkt anlegen; fehlt der Ping, war die NAS im Fenster nicht da – das ist ein echter Alarm.
- In Beszel beim System den Status-Alarm ausschalten (sonst meldet Beszel jeden Morgen „down“).

```yaml
hosts:
  nas: { beszel: nas, always_on: false, url: { DSM: "https://nas.home.arpa:5001" } }
checks:
  - name: nas/online
    tags: { host: nas, typ: fenster, prio: normal }
    schedule: "0 2 * * *"
    grace: 2h
```

## Jobs auf der Synology

Hyper Backup, Snapshot-Replikation & Co. melden über die DSM-Benachrichtigungen per Webhook (*Systemsteuerung → Benachrichtigung → Webhooks*) an `http://<server>:8088/api/ingest/notify?token=<INGEST_TOKEN>&source=synology`. Eigene Skripte melden mit `hc run <check> -- <befehl>`.
