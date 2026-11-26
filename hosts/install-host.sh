#!/usr/bin/env bash
# Bindet einen Debian/Ubuntu-Host an QuietBoard an. Normalerweise nicht direkt aufrufen, sondern über die App:
#   curl -fsSL -H "Authorization: Bearer <INGEST_TOKEN>" http://<server>:8088/api/install/host.sh | bash
# Die App setzt dabei alle QB_*-Werte und legt die übrigen Dateien aus hosts/ daneben.
#
# Werte (von der App vorgegeben, per Umgebung überschreibbar):
#   QB_PING_BASE, QB_PING_KEY        Healthchecks-Pings (hc)
#   QB_INGEST_URL, QB_INGEST_TOKEN   Update-Berichte an die App (updates-report)
#   QB_HUB_URL, QB_AGENT_KEY, QB_AGENT_TOKEN   Beszel-Agent (meldet sich per Universal-Token selbst an)
# Optional:
#   QB_HOST=name                 Name in QuietBoard (Standard: hostname -s)
#   QB_AGENT_MODE=auto|docker|binary   Standard auto: Docker, wenn vorhanden, sonst Binary + systemd
#   QB_SECURITY_UPDATES=1|0      automatische Debian-Sicherheitsupdates (Standard 1; ohne Reboot, Docker ausgenommen)
set -euo pipefail
# Werte als Datei statt über die Kommandozeile (sudo env … wäre in der Prozessliste sichtbar)
if [ "${1:-}" = --env ] && [ -r "${2:-}" ]; then
  # shellcheck disable=SC1090
  . "$2"
fi
BESZEL_VERSION=0.21.2
# Prüfsummen aus beszel_0.21.2_checksums.txt des Beszel-Releases (bei neuer Version mit anpassen)
declare -A BESZEL_SHA256=(
  [amd64]=0359a4c3b9d800ba865b2be4081c7f0df8ba29a8c5c0ac76e72f490f28496909
  [arm64]=4f5dcea27c3f9e2ba30218e7d7039f4df548ded1c470df9eefe00975722aad13
  [arm]=57075d4ae419a50d5d378a23dbc40fef12cf9dedaa4fd2f3fce23620d6ca0a3f
)
for v in QB_PING_BASE QB_PING_KEY QB_INGEST_URL QB_INGEST_TOKEN QB_HUB_URL QB_AGENT_KEY QB_AGENT_TOKEN; do
  [ -n "${!v:-}" ] || { echo "$v fehlt – Installer bitte über die quietboard-App abrufen" >&2; exit 1; }
done
# Name: ausdrücklich gesetzt > bisheriger Name aus /etc/hc.conf (bestehende Hosts nicht umbenennen) > hostname -s klein
if [ -z "${QB_HOST:-}" ] && [ -r /etc/hc.conf ]; then
  QB_HOST=$(sed -n "s/^STATUS_HOST=['\"]\{0,1\}\([^'\"]*\)['\"]\{0,1\}$/\1/p" /etc/hc.conf | tail -1)
fi
QB_HOST=${QB_HOST:-$(hostname -s | tr '[:upper:]' '[:lower:]')}
[[ $QB_HOST =~ ^[A-Za-z0-9._-]{1,64}$ ]] || { echo "Ungültiger Hostname '$QB_HOST' (erlaubt: Buchstaben, Ziffern, . _ -)" >&2; exit 1; }
QB_AGENT_MODE=${QB_AGENT_MODE:-auto}
QB_SECURITY_UPDATES=${QB_SECURITY_UPDATES:-1}
here=$(cd "$(dirname "$0")" && pwd)
[ "$(id -u)" = 0 ] || { echo "Bitte als root ausführen (sudo bash)" >&2; exit 1; }
# Synology (DSM): kein apt/systemd-Unit-Weg – eigenes Skript (Agent behalten oder als Container)
if [ -f /etc/synoinfo.conf ]; then exec bash "$here/synology-setup.sh"; fi
command -v apt-get >/dev/null || { echo "Nur Debian/Ubuntu werden unterstützt" >&2; exit 1; }
command -v curl >/dev/null || { apt-get update -qq && apt-get install -y -qq curl ca-certificates >/dev/null; }
if [ "$QB_AGENT_MODE" = auto ]; then
  if command -v docker >/dev/null && docker info >/dev/null 2>&1; then QB_AGENT_MODE=docker; else QB_AGENT_MODE=binary; fi
fi
echo "QuietBoard: binde $QB_HOST an (Agent: $QB_AGENT_MODE, Sicherheitsupdates: $QB_SECURITY_UPDATES)"

echo "== hc und updates-report"
install -m 0755 "$here/hc" "$here/updates-report" /usr/local/bin/
# Nur die eigenen Schlüssel setzen; andere Zeilen (z. B. MAILCOW_DIR) bleiben erhalten
sq() { local q="'\\''"; printf "'%s'" "${1//\'/$q}"; }
set_conf() { # <datei> <schlüssel> <wert>
  local tmp; tmp=$(mktemp)
  grep -v "^$2=" "$1" > "$tmp" 2>/dev/null || true
  printf '%s=%s\n' "$2" "$(sq "$3")" >> "$tmp"
  cat "$tmp" > "$1"; rm -f "$tmp"
}
[ -f /etc/hc.conf ] || { (umask 077; echo "# QuietBoard – angelegt von install-host.sh" > /etc/hc.conf); }
chmod 600 /etc/hc.conf; chown root:root /etc/hc.conf
set_conf /etc/hc.conf HC_PING_BASE "$QB_PING_BASE"
set_conf /etc/hc.conf HC_PING_KEY "$QB_PING_KEY"
set_conf /etc/hc.conf STATUS_INGEST_URL "$QB_INGEST_URL"
set_conf /etc/hc.conf STATUS_INGEST_TOKEN "$QB_INGEST_TOKEN"
set_conf /etc/hc.conf STATUS_HOST "$QB_HOST"
install -m 0644 "$here/updates-report.service" "$here/updates-report.timer" /etc/systemd/system/
cat > /etc/apt/apt.conf.d/99updates-report <<'EOF'
// QuietBoard: nach jedem apt-Lauf den Update-Stand melden (asynchron, blockiert apt nicht)
DPkg::Post-Invoke { "systemctl start --no-block updates-report.service 2>/dev/null || true"; };
EOF
systemctl daemon-reload
systemctl enable --now updates-report.timer >/dev/null

if [ "$QB_SECURITY_UPDATES" = 1 ]; then
  echo "== automatische Sicherheitsupdates"
  bash "$here/unattended-security.sh"
fi

echo "== Beszel-Agent $BESZEL_VERSION ($QB_AGENT_MODE)"
if [ "$QB_AGENT_MODE" = docker ]; then
  systemctl disable --now beszel-agent.service >/dev/null 2>&1 || true   # Wechsel von Binary auf Docker
  if docker inspect beszel-agent >/dev/null 2>&1; then
    if [ "$(docker inspect -f '{{index .Config.Labels "quietboard.agent"}}' beszel-agent)" != 1 ]; then
      echo "Hinweis: Vorhandener Container beszel-agent (nicht von QuietBoard angelegt) wird ersetzt." >&2
      echo "         Bisherige Einstellungen: $(docker inspect -f '{{range .Mounts}}{{.Source}}:{{.Destination}} {{end}}' beszel-agent)" >&2
    fi
    docker rm -f beszel-agent >/dev/null
  fi
  docker run -d --name beszel-agent --label quietboard.agent=1 --restart unless-stopped --network host --memory 64m \
    -v /var/run/docker.sock:/var/run/docker.sock:ro -v beszel-agent-data:/var/lib/beszel-agent \
    -e KEY="$QB_AGENT_KEY" -e TOKEN="$QB_AGENT_TOKEN" -e HUB_URL="$QB_HUB_URL" -e LISTEN=45876 \
    "henrygd/beszel-agent:$BESZEL_VERSION" >/dev/null
  sleep 3
  [ "$(docker inspect -f '{{.State.Running}}' beszel-agent)" = true ] && echo "beszel-agent: läuft (Docker)"
else
  arch=$(dpkg --print-architecture)
  case "$arch" in amd64|arm64) ;; armhf) arch=arm ;; *) echo "Architektur $arch nicht unterstützt" >&2; exit 1 ;; esac
  tmp=$(mktemp -d)
  curl -fsSL -o "$tmp/agent.tar.gz" "https://github.com/henrygd/beszel/releases/download/v$BESZEL_VERSION/beszel-agent_linux_$arch.tar.gz"
  echo "${BESZEL_SHA256[$arch]}  $tmp/agent.tar.gz" | sha256sum -c --quiet - \
    || { echo "Prüfsumme des Beszel-Agents stimmt nicht – Abbruch" >&2; rm -rf "$tmp"; exit 1; }
  tar -xzf "$tmp/agent.tar.gz" -C "$tmp" beszel-agent
  install -m 0755 "$tmp/beszel-agent" /usr/local/bin/beszel-agent
  rm -rf "$tmp"
  id beszel >/dev/null 2>&1 || useradd --system --home-dir /var/lib/beszel-agent --shell /usr/sbin/nologin beszel
  # Container-Metriken, falls Docker vorhanden. Achtung: Die Gruppe docker hat praktisch root-Rechte (Doku: Hosts).
  if getent group docker >/dev/null; then usermod -aG docker beszel; fi
  (
    umask 077
    cat > /etc/beszel-agent.env <<EOF
KEY=$QB_AGENT_KEY
TOKEN=$QB_AGENT_TOKEN
HUB_URL=$QB_HUB_URL
LISTEN=45876
EOF
  )
  cat > /etc/systemd/system/beszel-agent.service <<'EOF'
[Unit]
Description=Beszel Agent (QuietBoard)
Wants=network-online.target
After=network-online.target

[Service]
EnvironmentFile=/etc/beszel-agent.env
ExecStart=/usr/local/bin/beszel-agent
User=beszel
Restart=on-failure
RestartSec=10
StateDirectory=beszel-agent
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
# eigenes, beschreibbares /tmp: der Agent legt dort seine Health-Datei ab (sonst "read-only file system")
PrivateTmp=yes

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now beszel-agent.service >/dev/null
  systemctl restart beszel-agent.service
  sleep 2
  systemctl is-active --quiet beszel-agent && echo "beszel-agent: läuft (systemd)"
fi

echo "== Erster Bericht"
/usr/local/bin/updates-report && echo "updates-report: gemeldet"
echo "fertig: $QB_HOST ist angebunden"
