#!/usr/bin/env bash
# Legt .env aus .env.example an (falls nicht vorhanden) und füllt leere Secrets kryptografisch sicher.
# Vorhandene Werte werden nicht überschrieben – außer sie werden ausdrücklich per Umgebung übergeben (z. B. ADMIN_EMAIL=…).
set -euo pipefail
cd "$(dirname "$0")"
umask 077
[ -f .env ] || { cp .env.example .env; chmod 600 .env; echo ".env angelegt"; }
# Von Hand bearbeitete .env ohne Zeilenumbruch am Ende: sonst landet der erste angehängte Wert in der letzten Zeile
if [ -s .env ] && [ -n "$(tail -c1 .env)" ]; then echo >> .env; fi

fill() { # <name> <wert>   – setzt nur, wenn der Eintrag fehlt oder leer ist
  grep -qE "^$1=" .env || { echo "$1=" >> .env; }
  if grep -qE "^$1=$" .env; then
    local tmp; tmp=$(mktemp)
    awk -v k="$1" -v v="$2" 'BEGIN{FS=OFS="="} $1==k && $2=="" {print k "=" v; next} {print}' .env > "$tmp"
    cat "$tmp" > .env && rm -f "$tmp"
    echo "$1 erzeugt"
  fi
}

# Werte aus der Umgebung übernehmen (für die Installation mit einem Befehl / Automatisierung)
for v in ADMIN_EMAIL TZ SITE_NAME STATUS_IMAGE ALLOW_NO_AUTH POLL_SECONDS DEMO BIND_ADDR SMTP_HOST SMTP_PORT SMTP_TLS SMTP_USER SMTP_FROM BESZEL_ALERT_DOWN_MIN QB_VERSION LANGUAGE; do
  if [ -n "${!v:-}" ]; then
    grep -v "^$v=" .env > .env.tmp || true
    echo "$v=${!v}" >> .env.tmp && cat .env.tmp > .env && rm -f .env.tmp
  fi
done
# Öffentliche Adressen: PUBLIC_HOST oder erste IP dieses Rechners (macOS: localhost)
first_ip=$(hostname -I 2>/dev/null | awk '{print $1}' || true)   # macOS kennt -I nicht
host=${PUBLIC_HOST:-$first_ip}
host=${host:-localhost}
fill HC_PUBLIC_URL "http://$host:8000"
fill HC_PING_ENDPOINT "http://$host:8000/ping/"
fill BESZEL_PUBLIC_URL "http://$host:8090"
fill ADMIN_PASSWORD "$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 24)"
fill HC_SECRET_KEY "$(openssl rand -hex 32)"
fill INGEST_TOKEN "$(openssl rand -hex 24)"
# VAPID: privater EC-Schlüssel P-256, roh (32 Byte) als base64url. Nur openssl + coreutils (kein xxd/python nötig):
# SEC1-DER eines P-256-Schlüssels beginnt mit 30 77 02 01 01 04 20, danach folgen die 32 Byte des privaten Schlüssels.
vapid=$(openssl ecparam -name prime256v1 -genkey -noout -outform DER 2>/dev/null \
  | tail -c +8 | head -c 32 | base64 | tr '+/' '-_' | tr -d '=\n')
[ "${#vapid}" = 43 ] && fill VAPID_PRIVATE_KEY "$vapid"
grep -qE '^ADMIN_EMAIL=.+' .env || echo "HINWEIS: ADMIN_EMAIL in .env eintragen (Login für Healthchecks/Beszel, Ziel für Alarm-Mails)"
echo "fertig – .env prüfen und fehlende Werte eintragen"
