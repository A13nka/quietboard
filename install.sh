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
# TZ, SITE_NAME, STATUS_IMAGE, BIND_ADDR, QB_DIR, QB_BASE_URL (Quelle der Dateien),
# QB_DATA_DIR (z. B. /srv/quietboard: Daten in Ordnern statt Docker-Volumes – nur bei der Erstinstallation).
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

echo "QuietBoard: installiere nach $QB_DIR (andere Stelle: QB_DIR=/pfad vor bash)"
mkdir -p "$QB_DIR/config" || die "Kann $QB_DIR nicht anlegen – Ordner mit Schreibrecht wählen, z. B. QB_DIR=\$HOME/quietboard"
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

# Daten in Ordnern statt Docker-Volumes: legt die Ordner mit passenden Rechten an und schreibt compose.override.yaml
# (wird von docker compose automatisch gelesen und von Updates nicht angefasst).
if [ -n "${QB_DATA_DIR:-}" ] && [ ! -f compose.override.yaml ]; then
  case $QB_DATA_DIR in /*) ;; *) die "QB_DATA_DIR muss ein absoluter Pfad sein, z. B. /srv/quietboard" ;; esac
  if docker volume inspect "${COMPOSE_PROJECT_NAME:-quietboard}_status-data" >/dev/null 2>&1; then
    die "Es gibt schon Docker-Volumes dieser Installation – Umzug in Ordner: siehe Doku, Abschnitt Daten in eigenen Ordnern"
  fi
  # über einen Container, damit kein sudo nötig ist (status läuft als UID 10001, Healthchecks als 999)
  docker run --rm -v "$QB_DATA_DIR:/d" alpine:3.22 sh -c \
    'mkdir -p /d/status /d/healthchecks /d/beszel /d/bootstrap /d/signal && chown 10001 /d/status && chown 999:999 /d/healthchecks' \
    || die "Konnte $QB_DATA_DIR nicht anlegen"
  {
    echo "# Daten in Ordnern statt Docker-Volumes (angelegt von install.sh, QB_DATA_DIR=$QB_DATA_DIR)"
    echo "volumes:"
    for v in status-data:status healthchecks-data:healthchecks beszel-data:beszel bootstrap:bootstrap signal-data:signal; do
      echo "  ${v%%:*}: { driver: local, driver_opts: { type: none, o: bind, device: $QB_DATA_DIR/${v#*:} } }"
    done
  } > compose.override.yaml
  echo "QuietBoard: Daten liegen in $QB_DATA_DIR (siehe compose.override.yaml)"
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
# Einrichtungscode nur zeigen, solange noch kein Konto existiert (beim Update steht im Log noch der alte)
step1="öffnen und anmelden"
if curl -fsS -m 5 "http://127.0.0.1:$port/api/auth/state" 2>/dev/null | grep -q '"setup_needed":true'; then
  code=$(docker compose logs status 2>/dev/null | grep -o 'Einrichtungscode: [A-Z0-9]\{4\}-[A-Z0-9]\{4\}' | tail -1 | cut -d' ' -f2 || true)
  step1="öffnen und das Admin-Konto anlegen${code:+ – Einrichtungscode: $code}"
fi
cat <<EOF

QuietBoard läuft – installiert in $QB_DIR
  App           http://$host:$port
  Healthchecks  $(get HC_PUBLIC_URL)
  Beszel        $(get BESZEL_PUBLIC_URL)
  Login für Healthchecks und Beszel: $(get ADMIN_EMAIL), Passwort: grep ADMIN_PASSWORD $QB_DIR/.env

Nächste Schritte:
  1. http://$host:$port $step1
  2. Diesen Server selbst als Host anbinden (als root oder Benutzer mit sudo):
       curl -fsSL -H "Authorization: Bearer $(get INGEST_TOKEN)" http://$host:$port/api/install/host.sh | bash
  3. Jeden weiteren Host mit demselben Befehl anbinden (steht auch in der App unter System → Host hinzufügen).

EOF
[ "$hs" = 200 ] || echo "Hinweis: Host-Installer noch nicht bereit (HTTP $hs) – in einer Minute erneut versuchen."
