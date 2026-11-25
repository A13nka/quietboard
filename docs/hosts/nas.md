# Weitere NAS: UGREEN, QNAP, TrueNAS, Unraid, OMV

**Metriken und Alarme funktionieren auf jeder NAS mit Docker:** den Beszel-Agent als Container anlegen, wie unter [Hosts anbinden → Docker-Hosts ohne Shell-Zugriff](index.md#docker-hosts-ohne-shell-zugriff-portainer-dockge-nas-oberflachen) beschrieben. Die Werte stehen in der App unter **System → Host hinzufügen → Befehl anzeigen → Manuell**.

Für **Update-Berichte** und **Jobs** gibt es je nach System verschiedene Wege. Die folgenden Rezepte sind **ungetestet** – es fehlt Hardware zum Prüfen. Rückmeldungen und Korrekturen bitte als [Issue](https://github.com/A13nka/quietboard/issues).

| System | Agent | Update-Bericht | Jobs |
| --- | --- | --- | --- |
| OpenMediaVault | Host-Befehl (Debian) | automatisch (apt) | `hc` |
| UGREEN (UGOS Pro) | Host-Befehl oder Container | apt-Pakete automatisch, Systemupdates nicht | `hc` |
| TrueNAS SCALE | Container (Custom App) | Skript per Cron-Job, unten | Ping-URL |
| Unraid | Container | eigenes Skript (User Scripts), unten | Ping-URL |
| QNAP (QTS) | Container (Container Station) | eigenes Skript, unten | Ping-URL |

## OpenMediaVault und UGREEN (Debian-basiert)

Per SSH als root den normalen Befehl aus **System → Host hinzufügen** ausführen – wie auf jedem Debian-Host. Er installiert den Agent (als Container, wenn Docker läuft), `hc`, den Update-Bericht für apt und die automatischen Sicherheitsupdates.

Auf UGREEN kommen System- und App-Updates über die eigene Update-Funktion von UGOS; der Bericht zeigt nur die Debian-Pakete. Wer die automatischen Sicherheitsupdates dem Hersteller überlassen will: `… | QB_SECURITY_UPDATES=0 bash`.

## TrueNAS SCALE

1. **Agent:** *Apps → Discover Apps → Custom App* (bzw. *Install via YAML*) mit dem Docker-Stack aus [Hosts anbinden](index.md#docker-hosts-ohne-shell-zugriff-portainer-dockge-nas-oberflachen).
2. **Update-Bericht:** das Skript unten z. B. als `/mnt/<pool>/scripts/qb-truenas-report.sh` ablegen, ausführbar machen und unter *System → Advanced → Cron Jobs* täglich als root ausführen.

```sh
#!/bin/sh
# QuietBoard: verfügbares TrueNAS-Update melden (ungetestet; die API kann sich je Version unterscheiden)
URL=http://<server>:8088/api/ingest/updates
TOKEN=<INGEST_TOKEN>
HOST=truenas
ITEMS=""
if midclt call update.check_available 2>/dev/null | grep -q '"AVAILABLE"'; then
  ITEMS='{"pkg":"TrueNAS","from":"","to":"Update verfügbar","security":false}'
fi
curl -fsS -m 20 -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  --data-binary "{\"host\":\"$HOST\",\"kind\":\"truenas\",\"items\":[$ITEMS]}" "$URL"
```

Seit TrueNAS 25.04 heißt der Aufruf je nach Version anders (`update.status`) – bei Fehlern `midclt call update.` mit Tab-Vervollständigung prüfen.

3. **Jobs:** Snapshot- und Replikationsaufgaben haben keinen Ping-Haken. Für eigene Skripte einen Job mit der Vorlage „Andere Software mit Ping-URL“ anlegen und am Ende des Skripts die angezeigte Adresse aufrufen.

## Unraid und QNAP

1. **Agent:** Unraid über *Apps* (Community Applications, Suche „beszel agent“) oder als Docker-Stack; QNAP in der *Container Station* als Anwendung mit dem Docker-Stack aus [Hosts anbinden](index.md#docker-hosts-ohne-shell-zugriff-portainer-dockge-nas-oberflachen).
2. **Update-Bericht:** Beide Systeme melden System-Updates in ihrer eigenen Oberfläche. Wer sie in QuietBoard sehen will, schickt das Ergebnis eines eigenen Prüfskripts an die API (Unraid: Plugin *User Scripts*, täglich; QNAP: `crontab`):

```sh
# Beispiel: ein verfügbares Update melden – leere Liste "items":[] bedeutet „nichts offen“
curl -fsS -m 20 -H "Authorization: Bearer <INGEST_TOKEN>" -H 'Content-Type: application/json' \
  --data-binary '{"host":"nas","kind":"unraid","items":[{"pkg":"Unraid OS","from":"7.1.2","to":"7.1.3","security":false}]}' \
  http://<server>:8088/api/ingest/updates
```

3. **Jobs:** für eigene Skripte wie bei TrueNAS die Vorlage „Andere Software mit Ping-URL“.

Das Format des Update-Berichts steht in der [API-Referenz](../reference/api.md).
