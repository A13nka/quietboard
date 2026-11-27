#!/bin/bash
# QuietBoard auf einer Synology (DSM 7). Wird von install-host.sh aufgerufen, wenn /etc/synoinfo.conf existiert.
# Richtet ein: hc (Ping-Helfer), dsm-report (Paket-Updates), Konfiguration in /usr/local/etc (übersteht DSM-Updates).
# Beszel-Agent:
#   QB_AGENT_MODE=keep (Standard)  vorhandenen Agent behalten – die Werte für KEY/TOKEN/HUB_URL werden angezeigt
#   QB_AGENT_MODE=docker           Agent als Container (Container Manager muss installiert sein)
# Aufgabenplanung (DSM → Systemsteuerung → Aufgabenplaner) richtet DSM selbst ein – das Skript zeigt die Einträge.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausführen (sudo -i)" >&2; exit 1; }
QB_HOST=${QB_HOST:-$(hostname -s | tr '[:upper:]' '[:lower:]')}
[[ $QB_HOST =~ ^[A-Za-z0-9._-]{1,64}$ ]] || { echo "Ungültiger Hostname '$QB_HOST' (erlaubt: Buchstaben, Ziffern, . _ -)" >&2; exit 1; }
# Die Datei wird von hc/dsm-report als root eingelesen: Werte quotieren, damit nichts darin ausgeführt wird
sq() { local q="'\\''"; printf "'%s'" "${1//\'/$q}"; }
QB_AGENT_MODE=${QB_AGENT_MODE:-keep}
[ "$QB_AGENT_MODE" = auto ] && QB_AGENT_MODE=keep
CONF=/usr/local/etc/quietboard.conf
echo "QuietBoard: Synology erkannt – binde $QB_HOST an (Agent: $QB_AGENT_MODE)"

mkdir -p /usr/local/etc /usr/local/bin
(
  umask 077
  cat > "$CONF" <<EOF
# QuietBoard – angelegt von synology-setup.sh
HC_PING_BASE=$(sq "$QB_PING_BASE")
HC_PING_KEY=$(sq "$QB_PING_KEY")
STATUS_INGEST_URL=$(sq "$QB_INGEST_URL")
STATUS_INGEST_TOKEN=$(sq "$QB_INGEST_TOKEN")
STATUS_HOST=$(sq "$QB_HOST")
EOF
)
install -m 0755 "$here/hc" "$here/dsm-report" /usr/local/bin/
echo "== hc und dsm-report installiert (Konfiguration: $CONF)"

if [ "$QB_AGENT_MODE" = docker ]; then
  command -v docker >/dev/null || { echo "Container Manager fehlt – im Paket-Zentrum installieren oder QB_AGENT_MODE=keep" >&2; exit 1; }
  docker rm -f beszel-agent >/dev/null 2>&1 || true
  docker run -d --name beszel-agent --restart unless-stopped --network host --memory 64m \
    -v /var/run/docker.sock:/var/run/docker.sock:ro -v beszel-agent-data:/var/lib/beszel-agent \
    -e KEY="$QB_AGENT_KEY" -e TOKEN="$QB_AGENT_TOKEN" -e HUB_URL="$QB_HUB_URL" -e LISTEN=45876 \
    henrygd/beszel-agent:0.21.2 >/dev/null && echo "== Beszel-Agent läuft als Container"
else
  cat <<EOF
== Beszel-Agent: vorhandenen Agent behalten
   Trage in der Konfiguration deines Agents diese drei Werte ein und starte ihn neu:
     KEY=$QB_AGENT_KEY
     TOKEN=$QB_AGENT_TOKEN
     HUB_URL=$QB_HUB_URL
   Der Agent meldet sich dann selbst an und erscheint unter "Hosts".
EOF
fi

echo "== Erster Bericht"
/usr/local/bin/dsm-report && echo "dsm-report: gemeldet"
cat <<EOF

Fertig. Bitte im DSM-Aufgabenplaner (Systemsteuerung → Aufgabenplaner → Erstellen) anlegen, Benutzer root:
  1. Geplante Aufgabe → Benutzerdefiniertes Skript, täglich (bei Nacht-NAS ~30 min nach dem Einschalten):
       /usr/local/bin/dsm-report
  2. Ausgelöste Aufgabe → Hochfahren (nur, wenn die NAS nicht dauernd läuft):
       /usr/local/bin/hc ping $QB_HOST-online
     und in checks.yaml einen Check "$QB_HOST/online" mit dem Einschaltzeitpunkt anlegen.
EOF
