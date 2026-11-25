# FAQ und Fehlersuche

**Die App zeigt „Quelle gestört: healthchecks“ oder „beszel“.**
`docker compose ps` – laufen alle Dienste? `docker compose logs healthchecks-init beszel-init status` zeigt die Einrichtung. Kurz nach einem Neustart ist die Meldung normal, sie verschwindet mit dem nächsten Abruf.

**Wo finde ich den Einrichtungscode?**
`docker compose logs status | grep Einrichtungscode`. Ist schon ein Konto angelegt, gibt es keinen Code mehr – dann [Notfall-CLI](accounts.md#passwort-vergessen-admin-ausgesperrt).

**Ein Host erscheint nicht.**
Auf dem Host: `systemctl status beszel-agent` bzw. `docker logs beszel-agent`. Erreicht er `BESZEL_PUBLIC_URL` (Port 8090)? Stimmt die Adresse (VPN, Firewall)? Nach einer Adressänderung den Installer-Befehl erneut ausführen.

**Healthchecks antwortet mit „Bad Request (400)“.**
Die aufgerufene Adresse steht nicht in `HC_PUBLIC_URL`/`HC_PING_ENDPOINT`. Weitere Namen mit `HC_EXTRA_HOSTS=name1,name2` in `.env` erlauben – oder die Adressen anpassen – und `docker compose up -d`.

**Push-Mitteilungen lassen sich nicht aktivieren.**
Web Push braucht HTTPS. Auf dem iPhone zusätzlich die installierte App (Zum Home-Bildschirm) – im normalen Safari-Tab geht es nicht.

**Ich bekomme keine Mails.**
`SMTP_*` in `.env` gesetzt und `docker compose up -d`? Unter System → Benachrichtigungen „Test senden“; Fehler stehen in `docker compose logs status`.

**Wie viel Speicher braucht QuietBoard?**
Etwa 330 MB für den ganzen Stack, mit Signal etwa 510 MB. 1 GB RAM reicht, 2 GB sind bequem.

**Kann ich meine bestehenden Healthchecks/Beszel weiterverwenden?**
Ja: `HC_API_KEY`, `HC_PING_KEY`, `BESZEL_APP_USER`, `BESZEL_APP_PASS` in `.env` setzen; die Selbsteinrichtung wird dann übersprungen. Die mitgelieferten Container kannst du in einer eigenen `compose.override.yaml` deaktivieren.

**Ist QuietBoard ein Ersatz für Uptime Kuma?**
Nein, eher eine Ergänzung: Uptime Kuma prüft Erreichbarkeit von Diensten. QuietBoard kümmert sich um Hosts, Jobs (Backups!) und Updates – und bündelt alles in einer ruhigen Meldung.
