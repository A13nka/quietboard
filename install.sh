#!/usr/bin/env bash
# QuietBoard – Installation mit einem Befehl (Debian/Ubuntu mit Docker und Compose):
#
#   curl -fsSL https://raw.githubusercontent.com/A13nka/quietboard/main/install.sh | ADMIN_EMAIL=du@example.org bash
#
# Legt ~/quietboard an (QB_DIR), lädt compose.yaml, erzeugt .env mit allen Secrets, startet den Stack und
# zeigt danach den Befehl, mit dem jeder weitere Host angebunden wird. Erneut ausführen = aktualisieren
# (vorhandene .env und Daten bleiben erhalten).
#
# Optional per Umgebung: QB_VERSION (z. B. v0.1.0; Standard: neueste stabile Version = latest),
# PUBLIC_HOST (Adresse, unter der Hosts diesen Server erreichen; Standard: erste IP),
# TZ, SITE_NAME, STATUS_IMAGE, BIND_ADDR, QB_DIR, QB_BASE_URL (Quelle der Dateien).
# Aus einem Release geladen (…/releases/download/vX.Y.Z/install.sh) ist QB_VERSION bereits fest eingetragen.
set -euo pipefail
QB_DIR=${QB_DIR:-$HOME/quietboard}
QB_VERSION=${QB_VERSION:-}   # make-dist trägt hier die Release-Version ein
export QB_VERSION
# Dateien passend zur Version: Tag-Stand für Releases, sonst main
QB_BASE_URL=${QB_BASE_URL:-https://raw.githubusercontent.com/A13nka/quietboard/${QB_VERSION:-main}}
# Liegt das Skript in einem Ordner mit den übrigen Dateien (Repo, Test-VM), werden diese genommen.
src=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/compose.yaml" ]; then
  src=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fi

die() { echo "QuietBoard: $*" >&2; exit 1; }
command -v docker >/dev/null || die "Docker fehlt – Anleitung: https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "Docker Compose (Plugin) fehlt"
docker info >/dev/null 2>&1 || die "Kein Zugriff auf Docker – Benutzer in die Gruppe docker aufnehmen oder mit sudo ausführen"
command -v openssl >/dev/null || die "openssl fehlt (apt-get install openssl)"

mkdir -p "$QB_DIR/config"
cd "$QB_DIR"
fetch() { # <datei> [ziel]
  local target=${2:-$1}
  if [ -n "$src" ] && [ "$src" != "$PWD" ]; then cp "$src/$1" "$target"
  elif [ -z "$src" ]; then curl -fsSL "$QB_BASE_URL/$1" -o "$target"; fi
}
fetch compose.yaml
fetch .env.example
fetch generate-env.sh
chmod +x generate-env.sh
if [ ! -f config/checks.yaml ]; then
  fetch config/checks.example.yaml config/checks.example.yaml
  printf '# Checks-as-Code – Vorlage: checks.example.yaml\nsettings: {}\nhosts: {}\nchecks: []\n' > config/checks.yaml
fi

./generate-env.sh >/dev/null
grep -qE '^ADMIN_EMAIL=.+@.+' .env || die "ADMIN_EMAIL fehlt: erneut aufrufen mit ADMIN_EMAIL=du@example.org"

echo "QuietBoard: starte Dienste (erstes Mal: Images laden, ~1–3 Minuten) …"
docker compose up -d --quiet-pull --remove-orphans >/tmp/quietboard-up.log 2>&1 \
  || { tail -20 /tmp/quietboard-up.log >&2; die "docker compose up fehlgeschlagen"; }

get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- || true; }   # fehlender Eintrag = leer, kein Abbruch
port=$(get STATUS_PORT); port=${port:-8088}
for _ in $(seq 1 90); do
  curl -fs -o /dev/null "http://127.0.0.1:$port/healthz" && break
  sleep 2
done
curl -fsS -o /dev/null "http://127.0.0.1:$port/healthz" || die "App antwortet nicht – docker compose logs status"
for _ in $(seq 1 60); do
  hs=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(get INGEST_TOKEN)" "http://127.0.0.1:$port/api/install/host.sh")
  [ "$hs" = 200 ] && break
  sleep 2
done

host=$(get BESZEL_PUBLIC_URL | sed -E 's#^https?://##; s#[:/].*##')
code=$(docker compose logs status 2>/dev/null | grep -o 'Einrichtungscode: [A-Z0-9]\{4\}-[A-Z0-9]\{4\}' | tail -1 | cut -d' ' -f2 || true)
cat <<EOF

QuietBoard läuft.
  App           http://$host:$port${code:+   → Einrichtungscode: $code (Admin-Konto anlegen)}
  Healthchecks  $(get HC_PUBLIC_URL)
  Beszel        $(get BESZEL_PUBLIC_URL)
  Login für Healthchecks und Beszel: $(get ADMIN_EMAIL), Passwort: grep ADMIN_PASSWORD $QB_DIR/.env

Host anbinden – auf jedem Host ausführen, auch auf diesem Server (als root oder Benutzer mit sudo):
  curl -fsSL -H "Authorization: Bearer $(get INGEST_TOKEN)" http://$host:$port/api/install/host.sh | bash

EOF
[ "$hs" = 200 ] || echo "Hinweis: Host-Installer noch nicht bereit (HTTP $hs) – in einer Minute erneut versuchen."
