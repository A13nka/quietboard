#!/usr/bin/env bash
# End-to-End: frische Installation in einem Wegwerf-Compose-Projekt (eigene Volumes, andere Ports).
# Prüft die Machbarkeitstests aus Phase 0:
#   1. healthchecks-init + beszel-init richten beide Motoren ohne GUI ein
#   2. Checks aus checks.yaml landen per hc_sync in Healthchecks und erscheinen in der App
#   3. ein Beszel-Agent meldet sich nur mit dem Universal-Token aus der App an
#   4. ein zweiter Start ändert keine Zugänge
# Phase 1: Einrichtungscode → Admin-Konto, Anmeldung per Cookie, Rechte des Betrachters, Mail über Mailpit.
# Läuft lokal (make e2e) und in der CI. Räumt am Ende alles ab.
set -euo pipefail
cd "$(dirname "$0")/.."
export COMPOSE_PROJECT_NAME=quietboard-e2e
export STATUS_PORT=18088 HC_PORT=18000 BESZEL_PORT=18090 BIND_ADDR=127.0.0.1
export STATUS_IMAGE=${STATUS_IMAGE:-quietboard:e2e}
export TZ=UTC MAILPIT_PORT=18025 POLL_SECONDS=5 CHECKS_FILE=/config/checks.example.yaml
export ADMIN_EMAIL=admin@example.org
ADMIN_PASSWORD=$(openssl rand -hex 16)
HC_SECRET_KEY=$(openssl rand -hex 32)
INGEST_TOKEN=$(openssl rand -hex 24)
export ADMIN_PASSWORD HC_SECRET_KEY INGEST_TOKEN
C=(docker compose -f compose.yaml -f dev/compose.test.yaml --env-file /dev/null)
JAR=$(mktemp)
PW=e2e-admin-passwort-123
S="http://127.0.0.1:$STATUS_PORT"
AGENT=quietboard-e2e-agent

cleanup() {
  docker rm -f "$AGENT" >/dev/null 2>&1 || true
  "${C[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -f "$JAR"
}
trap cleanup EXIT
fail() { echo "FEHLER: $*" >&2; "${C[@]}" logs --tail 40 >&2 || true; exit 1; }
# Prüft den App-Zustand mit einem Python-Ausdruck über d (= /api/state); Exitcode 0, wenn wahr
state_ok() { curl -fsS -b "$JAR" "$S/api/state" | python3 -c "import json,sys; d=json.load(sys.stdin); sys.exit(0 if ($1) else 1)"; }
wait_until() { # <beschreibung> <sekunden> <befehl...>
  local what=$1 secs=$2; shift 2
  for _ in $(seq 1 "$secs"); do "$@" >/dev/null 2>&1 && { echo "ok   $what"; return 0; }; sleep 1; done
  fail "$what (nach ${secs}s)"
}
expect() { # <beschreibung> <befehl...>  – einmalige Prüfung
  local what=$1; shift
  if "$@" >/dev/null 2>&1; then echo "ok   $what"; else fail "$what"; fi
}
secrets_sum() {
  "${C[@]}" exec -T status sh -c 'cat /bootstrap/healthchecks.json /data/beszel.json' | sha256sum | cut -c1-16
}

[ "$STATUS_IMAGE" = "quietboard:e2e" ] && docker build -q -t quietboard:e2e . >/dev/null
"${C[@]}" up -d --quiet-pull >/dev/null 2>&1 || fail "docker compose up"

wait_until "Healthchecks erreichbar"       90 curl -fsS -o /dev/null "http://127.0.0.1:$HC_PORT/api/v3/status/"
wait_until "Beszel erreichbar"             90 curl -fsS -o /dev/null "http://127.0.0.1:$BESZEL_PORT/api/health"
wait_until "App erreichbar"                90 curl -fsS -o /dev/null "$S/healthz"

# Konten: ohne Anmeldung nichts sehen, Einrichtungscode aus dem Log, Admin anlegen
expect "Ohne Anmeldung: /api/state 401" test "$(curl -s -o /dev/null -w '%{http_code}' "$S/api/state")" = 401
expect "Ohne Anmeldung: Startseite leitet zur Einrichtung" sh -c "curl -s -o /dev/null -w '%{redirect_url}' $S/ | grep -q '/setup$'"
code=$("${C[@]}" logs status 2>&1 | grep -o 'Einrichtungscode: [A-Z0-9]\{4\}-[A-Z0-9]\{4\}' | tail -1 | cut -d' ' -f2)
expect "Einrichtungscode im Log" test -n "$code"
expect "Falscher Code abgelehnt" test "$(curl -s -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d '{"code":"AAAA-AAAA","email":"admin@example.org","password":"'"$PW"'"}' "$S/api/auth/setup")" = 400
expect "Admin-Konto mit Code angelegt" curl -fsS -c "$JAR" -H 'Content-Type: application/json' -d '{"code":"'"$code"'","email":"admin@example.org","password":"'"$PW"'"}' "$S/api/auth/setup"
expect "Mit Sitzung: /api/state 200" curl -fsS -o /dev/null -b "$JAR" "$S/api/state"
H=(-b "$JAR" -H "Origin: $S" -H 'Content-Type: application/json')
wait_until "Motoren ohne GUI eingerichtet" 90 state_ok 'not ({"healthchecks", "beszel"} & set(d["errors"]))'
code=$(curl -s -o /dev/null -w '%{http_code}' -H 'Host: evil.example' "http://127.0.0.1:$HC_PORT/api/v3/status/")
expect "Healthchecks lehnt fremde Host-Header ab ($code)" test "$code" = 400

expect "Healthchecks: 200 API-Aufrufe ohne Verbindungsfehler" "${C[@]}" exec -T status python -m tools.keepalive_test 200

# Checks aus der Beispielkonfiguration anlegen
"${C[@]}" exec -T status python -m tools.hc_sync >/dev/null || fail "hc_sync"
want=$(grep -c '^  - name:' config/checks.example.yaml)
wait_until "$want Checks in der App" 30 state_ok "len(d['checks']) == $want"

# Agent nur mit Token aus der App anmelden
agent=$(curl -fsS -b "$JAR" "$S/api/agent") || fail "/api/agent"
key=$(echo "$agent" | python3 -c 'import json,sys; print(json.load(sys.stdin)["key"])')
token=$(echo "$agent" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
docker run -d --name "$AGENT" --hostname e2e-agent --network "${COMPOSE_PROJECT_NAME}_default" \
  -e KEY="$key" -e TOKEN="$token" -e HUB_URL=http://beszel:8090 -e LISTEN=45876 henrygd/beszel-agent:0.21.2 >/dev/null
wait_until "Agent per Token angemeldet und in der App sichtbar" 90 \
  state_ok 'any(h["name"] == "e2e-agent" and h["status"] == "up" for h in d["hosts"])'

# Update-Bericht eines Hosts einspielen und in der Ansicht wiederfinden
curl -fsS -o /dev/null -H "Authorization: Bearer $INGEST_TOKEN" -H 'Content-Type: application/json' \
  --data-binary '{"host":"e2e-host","kind":"apt","reboot":true,"items":[{"pkg":"openssl","from":"1","to":"2","security":true}]}' \
  "$S/api/ingest/updates"
expect "Update-Bericht sichtbar" state_ok 'any(h["host"] == "e2e-host" for h in d["host_updates"])'
code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$S/api/ingest/updates")
expect "Ingest ohne Token abgelehnt ($code)" test "$code" = 401

# Host-Befehl aus der Oberfläche und Installer dahinter
cmd=$(curl -fsS -b "$JAR" "$S/api/hosts/install-command" | python3 -c 'import json,sys; print(json.load(sys.stdin)["command"])')
expect "Host-Befehl abrufbar und Installer dahinter gültig" sh -c "echo '$cmd' | grep -q '/api/install/host.sh | bash' && curl -fsS -H 'Authorization: Bearer $INGEST_TOKEN' $S/api/install/host.sh | bash -n"

# Check pausieren und Priorität ändern (über Healthchecks)
uuid=$(curl -fsS -b "$JAR" "$S/api/state" | python3 -c "import json,sys; print([c['uuid'] for c in json.load(sys.stdin)['checks'] if c['name']=='docker01/certbot'][0])")
expect "Check pausieren" curl -fsS -o /dev/null "${H[@]}" -X POST "$S/api/checks/$uuid/pause"
expect "Check ist pausiert" state_ok "any(c['uuid']=='$uuid' and c['status']=='paused' for c in d['checks'])"
expect "Priorität auf kritisch" curl -fsS -o /dev/null "${H[@]}" -d '{"prio":"kritisch"}' "$S/api/checks/$uuid/prio"
expect "Priorität übernommen" state_ok "any(c['uuid']=='$uuid' and c['prio']=='kritisch' for c in d['checks'])"
expect "Check fortsetzen" curl -fsS -o /dev/null "${H[@]}" -X POST "$S/api/checks/$uuid/resume"

echo "== Jobs in der Oberfläche: anlegen, Proxmox-Webhook, bearbeiten, löschen"
expect "Job anlegen (PVE-Backup)" curl -fsS -o /dev/null "${H[@]}" \
  -d '{"host":"pve","job":"backup","mode":"cron","schedule":"0 1 * * *","grace":"3h","prio":"kritisch","typ":"backup","src":"pve","ev":"vzdump"}' "$S/api/checks"
expect "Doppelter Job abgelehnt (409)" test "$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" -d '{"host":"pve","job":"backup","schedule":"0 1 * * *"}' "$S/api/checks")" = 409
expect "Ungültiger Cron abgelehnt (400)" test "$(curl -s -o /dev/null -w '%{http_code}' "${H[@]}" -d '{"host":"x","job":"y","schedule":"99 1 * * *"}' "$S/api/checks")" = 400
curl -fsS -o /dev/null -H "Authorization: Bearer $INGEST_TOKEN" -H 'Content-Type: application/json' \
  -d '{"severity":"info","title":"vzdump backup status: successful","message":"ok","fields":{"type":"vzdump"}}' "$S/api/ingest/pve?source=pve&host=pve"
wait_until "PVE-Webhook meldet den Job grün" 20 state_ok "any(c['name']=='pve/backup' and c['status']=='up' for c in d['checks'])"
juuid=$(curl -fsS -b "$JAR" "$S/api/state" | python3 -c "import json,sys; print([c['uuid'] for c in json.load(sys.stdin)['checks'] if c['name']=='pve/backup'][0])")
expect "Job bearbeiten (Intervall, info)" curl -fsS -o /dev/null "${H[@]}" -X PUT -d '{"mode":"period","period":"1d","grace":"2h","prio":"info","typ":"backup","src":"pve","ev":"vzdump"}' "$S/api/checks/$juuid"
expect "Änderung übernommen" sh -c "curl -fsS -b '$JAR' '$S/api/checks/$juuid' | grep -q '\"period\":\"1d\"'"
expect "Job löschen" curl -fsS -o /dev/null "${H[@]}" -X DELETE "$S/api/checks/$juuid"
expect "Job ist weg" state_ok "not any(c['name']=='pve/backup' for c in d['checks'])"

echo "== API-Token, YAML-Export/-Import, Host-Einstellungen"
tok=$(curl -fsS "${H[@]}" -d '{"name":"e2e"}' "$S/api/tokens" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
expect "API-Token liest den Zustand" curl -fsS -o /dev/null -H "Authorization: Bearer $tok" "$S/api/state"
expect "Export enthält die Jobs aus checks.yaml" sh -c "curl -fsS -b '$JAR' '$S/api/config/export' | grep -q 'name: docker01/certbot'"
expect "Import per API-Token legt neuen Job an" sh -c "curl -fsS -H 'Authorization: Bearer $tok' -H 'Content-Type: application/json' \
  -d '{\"yaml\":\"checks:\\n  - name: e2e/import\\n    period: 1d\\n    grace: 1h\\n\",\"dry\":false}' '$S/api/config/import' | grep -q anlegen"
expect "Importierter Job sichtbar" state_ok "any(c['name']=='e2e/import' for c in d['checks'])"
expect "Host-Einstellung speichern" curl -fsS -o /dev/null "${H[@]}" -X PUT -d '{"always_on":false,"links":[{"label":"Web","url":"https://e2e.example.org"}]}' "$S/api/hosts/e2e-host/settings"
tid=$(curl -fsS -b "$JAR" "$S/api/tokens" | python3 -c 'import json,sys; print(json.load(sys.stdin)["tokens"][0]["id"])')
expect "API-Token widerrufen" curl -fsS -o /dev/null "${H[@]}" -X DELETE "$S/api/tokens/$tid"
expect "Widerrufener Token abgelehnt (401)" test "$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $tok" "$S/api/state")" = 401

# Mail über Mailpit: Empfänger setzen, Test senden, Morgenmeldung
expect "Mail-Empfänger speichern" curl -fsS -o /dev/null "${H[@]}" -X PUT -d '{"mail_to":"ops@example.org","digest_time":"06:45"}' "$S/api/settings"
expect "Test-Mail senden" curl -fsS -o /dev/null "${H[@]}" -d '{"channel":"mail"}' "$S/api/notify/test"
expect "Morgenmeldung senden" curl -fsS -o /dev/null "${H[@]}" -X POST "$S/api/digest/test"
wait_until "Beide Mails bei ops@example.org angekommen" 20 sh -c "curl -fsS http://127.0.0.1:$MAILPIT_PORT/api/v1/messages | python3 -c \"import json,sys; m=json.load(sys.stdin)['messages']; sys.exit(not (len(m) >= 2 and all(x['To'][0]['Address']=='ops@example.org' for x in m)))\""

# Betrachter: sieht alles, darf nichts verwalten
expect "Betrachter anlegen" curl -fsS -o /dev/null "${H[@]}" -d '{"email":"viewer@example.org","password":"'"$PW"'","role":"viewer"}' "$S/api/users"
VJAR=$(mktemp)
expect "Betrachter meldet sich an" curl -fsS -o /dev/null -c "$VJAR" -H 'Content-Type: application/json' -d '{"email":"viewer@example.org","password":"'"$PW"'"}' "$S/api/auth/login"
expect "Betrachter sieht den Zustand" curl -fsS -o /dev/null -b "$VJAR" "$S/api/state"
expect "Betrachter bekommt keinen Host-Befehl (403)" test "$(curl -s -o /dev/null -w '%{http_code}' -b "$VJAR" "$S/api/hosts/install-command")" = 403
expect "Betrachter darf keine Jobs anlegen (403)" test "$(curl -s -o /dev/null -w '%{http_code}' -b "$VJAR" -H "Origin: $S" -H 'Content-Type: application/json' -d '{"host":"a","job":"b","schedule":"0 1 * * *"}' "$S/api/checks")" = 403
expect "Fremde Seite darf nicht schreiben (403)" test "$(curl -s -o /dev/null -w '%{http_code}' -b "$JAR" -H 'Origin: https://evil.example' -H 'Content-Type: application/json' -X PUT -d '{}' "$S/api/settings")" = 403
rm -f "$VJAR"

# Zweiter Start: Zugänge bleiben gleich, alles läuft weiter
before=$(secrets_sum)
"${C[@]}" up -d --force-recreate >/dev/null 2>&1
wait_until "App nach Neustart erreichbar" 90 curl -fsS -o /dev/null "$S/healthz"
expect "Zweiter Start ändert keine Zugänge" test "$(secrets_sum)" = "$before"
wait_until "Nach Neustart beide Motoren verbunden" 60 state_ok 'not d["errors"] and d["checks"] and d["hosts"]'
expect "Sitzung übersteht den Neustart" curl -fsS -o /dev/null -b "$JAR" "$S/api/state"
expect "Notfall-CLI listet die Konten" sh -c "${C[*]} exec -T status python -m tools.cli users | grep -q viewer@example.org"

docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}' | grep -E "quietboard-e2e" || true
echo "E2E bestanden"
