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
BESZEL_VERSION=0.21.2
for v in QB_PING_BASE QB_PING_KEY QB_INGEST_URL QB_INGEST_TOKEN QB_HUB_URL QB_AGENT_KEY QB_AGENT_TOKEN; do
  [ -n "${!v:-}" ] || { echo "$v fehlt – Installer bitte über die quietboard-App abrufen" >&2; exit 1; }
done
QB_HOST=${QB_HOST:-$(hostname -s)}
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
(
  umask 077
  cat > /etc/hc.conf <<EOF
# QuietBoard – angelegt von install-host.sh
HC_PING_BASE=$QB_PING_BASE
HC_PING_KEY=$QB_PING_KEY
STATUS_INGEST_URL=$QB_INGEST_URL
STATUS_INGEST_TOKEN=$QB_INGEST_TOKEN
STATUS_HOST=$QB_HOST
EOF
)
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
  docker rm -f beszel-agent >/dev/null 2>&1 || true
  docker run -d --name beszel-agent --restart unless-stopped --network host --memory 64m \
    -v /var/run/docker.sock:/var/run/docker.sock:ro -v beszel-agent-data:/var/lib/beszel-agent \
    -e KEY="$QB_AGENT_KEY" -e TOKEN="$QB_AGENT_TOKEN" -e HUB_URL="$QB_HUB_URL" -e LISTEN=45876 \
    "henrygd/beszel-agent:$BESZEL_VERSION" >/dev/null
  sleep 3
  [ "$(docker inspect -f '{{.State.Running}}' beszel-agent)" = true ] && echo "beszel-agent: läuft (Docker)"
else
  arch=$(dpkg --print-architecture)
  case "$arch" in amd64|arm64) ;; armhf) arch=arm ;; *) echo "Architektur $arch nicht unterstützt" >&2; exit 1 ;; esac
  tmp=$(mktemp -d)
  curl -fsSL "https://github.com/henrygd/beszel/releases/download/v$BESZEL_VERSION/beszel-agent_linux_$arch.tar.gz" | tar -xz -C "$tmp" beszel-agent
  install -m 0755 "$tmp/beszel-agent" /usr/local/bin/beszel-agent
  rm -rf "$tmp"
  id beszel >/dev/null 2>&1 || useradd --system --home-dir /var/lib/beszel-agent --shell /usr/sbin/nologin beszel
  if getent group docker >/dev/null; then usermod -aG docker beszel; fi   # Container-Metriken, falls Docker vorhanden
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
