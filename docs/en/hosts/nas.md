# Other NAS: UGREEN, QNAP, TrueNAS, Unraid, OMV

**Metrics and alerts work on every NAS with Docker:** create the Beszel agent as a container as described under [Adding hosts → Docker hosts without shell access](index.md#docker-hosts-without-shell-access-portainer-dockge-nas-interfaces). The values are in the app under **System → Add host → Show command → Manual**.

For **update reports** and **jobs** the way depends on the system. The recipes below are **untested** – there is no hardware to check them on. Feedback and corrections are welcome as an [issue](https://github.com/A13nka/quietboard/issues).

| System | Agent | Update report | Jobs |
| --- | --- | --- | --- |
| OpenMediaVault | host command (Debian) | automatic (apt) | `hc` |
| UGREEN (UGOS Pro) | host command or container | apt packages automatically, system updates not | `hc` |
| TrueNAS SCALE | container (custom app) | script via cron job, below | ping URL |
| Unraid | container | own script (User Scripts), below | ping URL |
| QNAP (QTS) | container (Container Station) | own script, below | ping URL |

## OpenMediaVault and UGREEN (Debian-based)

Run the normal command from **System → Add host** via SSH as root – like on any Debian host. It installs the agent (as a container if Docker runs), `hc`, the apt update report and automatic security updates.

On UGREEN, system and app updates come through UGOS's own update function; the report only shows the Debian packages. If you want to leave automatic security updates to the vendor: `… | QB_SECURITY_UPDATES=0 bash`.

## TrueNAS SCALE

1. **Agent:** *Apps → Discover Apps → Custom App* (or *Install via YAML*) with the Docker stack from [Adding hosts](index.md#docker-hosts-without-shell-access-portainer-dockge-nas-interfaces).
2. **Update report:** save the script below e.g. as `/mnt/<pool>/scripts/qb-truenas-report.sh`, make it executable and run it daily as root under *System → Advanced → Cron Jobs*.

```sh
#!/bin/sh
# QuietBoard: report an available TrueNAS update (untested; the API may differ between versions)
URL=http://<server>:8088/api/ingest/updates
TOKEN=<INGEST_TOKEN>
HOST=truenas
ITEMS=""
if midclt call update.check_available 2>/dev/null | grep -q '"AVAILABLE"'; then
  ITEMS='{"pkg":"TrueNAS","from":"","to":"update available","security":false}'
fi
curl -fsS -m 20 -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  --data-binary "{\"host\":\"$HOST\",\"kind\":\"truenas\",\"items\":[$ITEMS]}" "$URL"
```

Since TrueNAS 25.04 the call may be named differently depending on the version (`update.status`) – on errors, check `midclt call update.` with tab completion.

3. **Jobs:** snapshot and replication tasks have no ping hook. For your own scripts create a job with the template “Other software with a ping URL” and call the address shown at the end of the script.

## Unraid and QNAP

1. **Agent:** Unraid via *Apps* (Community Applications, search “beszel agent”) or as a Docker stack; QNAP in *Container Station* as an application with the Docker stack from [Adding hosts](index.md#docker-hosts-without-shell-access-portainer-dockge-nas-interfaces).
2. **Update report:** both systems show system updates in their own interface. To see them in QuietBoard, send the result of your own check script to the API (Unraid: plugin *User Scripts*, daily; QNAP: `crontab`):

```sh
# Example: report one available update – an empty list "items":[] means “nothing pending”
curl -fsS -m 20 -H "Authorization: Bearer <INGEST_TOKEN>" -H 'Content-Type: application/json' \
  --data-binary '{"host":"nas","kind":"unraid","items":[{"pkg":"Unraid OS","from":"7.1.2","to":"7.1.3","security":false}]}' \
  http://<server>:8088/api/ingest/updates
```

3. **Jobs:** for your own scripts, the template “Other software with a ping URL” as with TrueNAS.

The format of the update report is in the [API reference](../reference/api.md).
