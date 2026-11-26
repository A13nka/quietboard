#!/usr/bin/env bash
# QuietBoard – Installation mit einem Befehl (Debian/Ubuntu mit Docker und Compose):
#
#   curl -fsSL https://raw.githubusercontent.com/A13nka/quietboard/main/install.sh | ADMIN_EMAIL=du@example.org bash
#
# Legt ~/quietboard an (QB_DIR), lädt compose.yaml, erzeugt .env mit allen Secrets, startet den Stack und
# zeigt danach den Befehl, mit dem jeder weitere Host angebunden wird. Erneut ausführen = aktualisieren
# (vorhandene .env und Daten bleiben erhalten).
#
# Optional per Umgebung: QB_VERSION (Image-Tag, z. B. v0.6.1, v0 oder latest; Standard: neueste Release-Version),
# PUBLIC_HOST (Adresse, unter der Hosts diesen Server erreichen; Standard: erste IP),
# TZ, SITE_NAME, STATUS_IMAGE, BIND_ADDR, QB_DIR, QB_BASE_URL (Quelle der Dateien),
# QB_DATA_DIR (z. B. /srv/quietboard: Daten in Ordnern statt Docker-Volumes – nur bei der Erstinstallation).
# Aus einem Release geladen (…/releases/download/vX.Y.Z/install.sh) ist die Version bereits fest eingetragen.
set -euo pipefail
QB_DIR=${QB_DIR:-$HOME/quietboard}
QB_RELEASE=""   # make-dist trägt hier die Release-Version ein (vX.Y.Z)
# Liegt das Skript in einem Ordner mit den übrigen Dateien (Repo, Test-VM), werden diese genommen.
src=""
if [ -n "${BASH_SOURCE[0]:-}" ] && [ -f "$(dirname "${BASH_SOURCE[0]}")/compose.yaml" ]; then
  src=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
fi
# Image-Tag (QB_VERSION) und Stand der Dateien (ref) sind getrennt: v0, v0.6 oder latest gibt es nur als Image-Tag.
want=${QB_VERSION:-}
if [ -z "$want" ] && [ -f "$QB_DIR/.env" ]; then
  # Gleitende Tags (v0, v0.6, latest, edge) aus der vorhandenen .env behalten; eine feste Version wird aktualisiert.
  cur=$(grep -E '^QB_VERSION=' "$QB_DIR/.env" | tail -1 | cut -d= -f2- | sed 's/[[:space:]]*#.*//' || true)
  case $cur in v[0-9]*.*.*|"") ;; *) want=$cur ;; esac
fi
case $want in
  v[0-9]*.*.*) ref=$want ;;
  edge) ref=main ;;
  *) ref=$QB_RELEASE ;;
esac
if [ -z "$ref" ] && [ -z "${QB_BASE_URL:-}" ] && [ -z "$src" ]; then
  # neueste Release-Version: github.com/…/releases/latest leitet auf …/releases/tag/vX.Y.Z weiter
  ref=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/A13nka/quietboard/releases/latest 2>/dev/null \
    | sed -n 's#.*/releases/tag/\(v[0-9][^/]*\)$#\1#p' || true)
  [ -n "$ref" ] || { echo "QuietBoard: neueste Version nicht ermittelbar – mit QB_VERSION=vX.Y.Z erneut aufrufen" >&2; exit 1; }
fi
QB_VERSION=${want:-$ref}
export QB_VERSION
QB_BASE_URL=${QB_BASE_URL:-https://raw.githubusercontent.com/A13nka/quietboard/${ref:-main}}

# Sprache der Ausgabe: LANGUAGE=de|en, sonst nach der Server-Locale (de_* → Deutsch, sonst Englisch)
case "${LANGUAGE:-${LC_ALL:-${LANG:-}}}" in de*) QL=de ;; *) QL=en ;; esac
m() { if [ "$QL" = de ]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }   # m "deutsch" "english"
die() { echo "QuietBoard: $*" >&2; exit 1; }
command -v docker >/dev/null || die "$(m "Docker fehlt – Anleitung" "Docker is missing – see"): https://docs.docker.com/engine/install/"
docker compose version >/dev/null 2>&1 || die "$(m "Docker Compose (Plugin) fehlt" "Docker Compose (plugin) is missing")"
docker info >/dev/null 2>&1 || die "$(m "Kein Zugriff auf Docker – Benutzer in die Gruppe docker aufnehmen oder mit sudo ausführen" "No access to Docker – add your user to the docker group or run with sudo")"
command -v openssl >/dev/null || die "$(m "openssl fehlt" "openssl is missing") (apt-get install openssl)"

echo "QuietBoard: $(m "installiere nach $QB_DIR (andere Stelle: QB_DIR=/pfad vor bash)" "installing to $QB_DIR (other location: QB_DIR=/path before bash)")"
mkdir -p "$QB_DIR/config" || die "$(m "Kann $QB_DIR nicht anlegen – Ordner mit Schreibrecht wählen" "Cannot create $QB_DIR – choose a writable folder"), QB_DIR=\$HOME/quietboard"
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
  case $QB_DATA_DIR in /*) ;; *) die "$(m "QB_DATA_DIR muss ein absoluter Pfad sein" "QB_DATA_DIR must be an absolute path"), /srv/quietboard" ;; esac
  if docker volume inspect "${COMPOSE_PROJECT_NAME:-quietboard}_status-data" >/dev/null 2>&1; then
    die "$(m "Es gibt schon Docker-Volumes dieser Installation – Umzug in Ordner: siehe Doku, Daten in eigenen Ordnern" "Docker volumes of this installation already exist – moving to folders: see the docs, Data in your own folders")"
  fi
  # über einen Container, damit kein sudo nötig ist (status läuft als UID 10001, Healthchecks als 999)
  docker run --rm -v "$QB_DATA_DIR:/d" alpine:3.22 sh -c \
    'mkdir -p /d/status /d/healthchecks /d/beszel /d/bootstrap /d/signal && chown 10001 /d/status && chown 999:999 /d/healthchecks' \
    || die "$(m "Konnte $QB_DATA_DIR nicht anlegen" "Could not create $QB_DATA_DIR")"
  {
    echo "# Daten in Ordnern statt Docker-Volumes (angelegt von install.sh, QB_DATA_DIR=$QB_DATA_DIR)"
    echo "volumes:"
    for v in status-data:status healthchecks-data:healthchecks beszel-data:beszel bootstrap:bootstrap signal-data:signal; do
      echo "  ${v%%:*}: { driver: local, driver_opts: { type: none, o: bind, device: $QB_DATA_DIR/${v#*:} } }"
    done
  } > compose.override.yaml
  echo "QuietBoard: $(m "Daten liegen in $QB_DATA_DIR (siehe compose.override.yaml)" "data is stored in $QB_DATA_DIR (see compose.override.yaml)")"
fi

./generate-env.sh >/dev/null
grep -qE '^ADMIN_EMAIL=.+@.+' .env || die "$(m "ADMIN_EMAIL fehlt: erneut aufrufen mit ADMIN_EMAIL=du@example.org" "ADMIN_EMAIL is missing: run again with ADMIN_EMAIL=you@example.org")"
get() { grep -E "^$1=" .env | head -1 | cut -d= -f2- || true; }   # fehlender Eintrag = leer, kein Abbruch
# Öffentliche Adresse ohne BIND_ADDR: Die Ports sind dann aus dem Internet erreichbar – Docker umgeht ufw/iptables-INPUT.
bind=$(get BIND_ADDR)
if [ -z "$bind" ] || [ "$bind" = 0.0.0.0 ]; then
  for ip in $(hostname -I 2>/dev/null || true); do
    case $ip in 10.*|192.168.*|127.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*|100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*|169.254.*|f[cd]*|fe80*|::1) continue ;; esac
    echo "QuietBoard: $(m "WARNUNG – öffentliche Adresse $ip und kein BIND_ADDR: Die Ports 8088/8000/8090 sind aus dem Internet erreichbar (Docker umgeht ufw). BIND_ADDR=<LAN/VPN-IP> in .env setzen oder Firewall-Regeln in DOCKER-USER – siehe Doku Netzwerk." "WARNING – public address $ip and no BIND_ADDR: ports 8088/8000/8090 are reachable from the internet (Docker bypasses ufw). Set BIND_ADDR=<LAN/VPN IP> in .env or add DOCKER-USER firewall rules – see the network docs.")" >&2
    break
  done
fi

# Images sichtbar laden (beim Update: neue Versionen); lokal gebaute Images (STATUS_IMAGE) dürfen fehlen
echo "QuietBoard: $(m "lade Images (erstes Mal ~1–3 Minuten):" "pulling images (first time ~1–3 minutes):")"
docker compose config --images 2>/dev/null | sort -u | sed 's/^/  - /'
docker compose pull --ignore-pull-failures || die "$(m "Images konnten nicht geladen werden – Internetverbindung prüfen" "Could not pull images – check the internet connection")"
echo "QuietBoard: $(m "starte Dienste …" "starting services …")"
uplog=$(mktemp)   # eigene Temp-Datei (ein fester Pfad in /tmp kann einem anderen Benutzer gehören)
docker compose up -d --remove-orphans >"$uplog" 2>&1 \
  || { tail -20 "$uplog" >&2; rm -f "$uplog"; die "docker compose up $(m "fehlgeschlagen" "failed")"; }
rm -f "$uplog"

port=$(get STATUS_PORT); port=${port:-8088}
for _ in $(seq 1 90); do
  curl -fs -o /dev/null "http://127.0.0.1:$port/healthz" && break
  sleep 2
done
curl -fsS -o /dev/null "http://127.0.0.1:$port/healthz" || die "$(m "App antwortet nicht" "App does not respond") – docker compose logs status"
for _ in $(seq 1 60); do
  hs=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $(get INGEST_TOKEN)" "http://127.0.0.1:$port/api/install/host.sh")
  [ "$hs" = 200 ] && break
  sleep 2
done

host=$(get BESZEL_PUBLIC_URL | sed -E 's#^https?://##; s#[:/].*##')
# Einrichtungscode nur zeigen, solange noch kein Konto existiert (beim Update steht im Log noch der alte)
step1=$(m "http://$host:$port öffnen und anmelden" "Open http://$host:$port and sign in")
if curl -fsS -m 5 "http://127.0.0.1:$port/api/auth/state" 2>/dev/null | grep -q '"setup_needed":true'; then
  code=$(docker compose logs status 2>/dev/null | grep -o 'Einrichtungscode: [A-Z0-9]\{4\}-[A-Z0-9]\{4\}' | tail -1 | cut -d' ' -f2 || true)
  step1="$(m "http://$host:$port öffnen und das Admin-Konto anlegen" "Open http://$host:$port and create the admin account")${code:+ – $(m Einrichtungscode "setup code"): $code}"
fi
if [ "$QL" = de ]; then
cat <<EOF

QuietBoard läuft – installiert in $QB_DIR
  App           http://$host:$port
  Healthchecks  $(get HC_PUBLIC_URL)
  Beszel        $(get BESZEL_PUBLIC_URL)
  Login für Healthchecks und Beszel: $(get ADMIN_EMAIL), Passwort: grep ADMIN_PASSWORD $QB_DIR/.env

Nächste Schritte:
  1. $step1
  2. Diesen Server selbst als Host anbinden (als root oder Benutzer mit sudo):
       curl -fsSL -H "Authorization: Bearer $(get INGEST_TOKEN)" http://$host:$port/api/install/host.sh | bash
  3. Jeden weiteren Host mit demselben Befehl anbinden (steht auch in der App unter System → Host hinzufügen).

EOF
else
cat <<EOF

QuietBoard is running – installed in $QB_DIR
  App           http://$host:$port
  Healthchecks  $(get HC_PUBLIC_URL)
  Beszel        $(get BESZEL_PUBLIC_URL)
  Login for Healthchecks and Beszel: $(get ADMIN_EMAIL), password: grep ADMIN_PASSWORD $QB_DIR/.env

Next steps:
  1. $step1
  2. Connect this server itself as a host (as root or a user with sudo):
       curl -fsSL -H "Authorization: Bearer $(get INGEST_TOKEN)" http://$host:$port/api/install/host.sh | bash
  3. Connect every other host with the same command (also in the app under System → Add host).

EOF
fi
[ "$hs" = 200 ] || echo "$(m "Hinweis: Host-Installer noch nicht bereit" "Note: host installer not ready yet") (HTTP $hs) – $(m "in einer Minute erneut versuchen" "try again in a minute")."
