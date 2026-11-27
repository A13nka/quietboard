#!/usr/bin/env bash
# upgrade-host.sh – tauscht auf einem bestehenden Host nur `hc` und `updates-report` gegen die Fassung aus diesem
# Paket. Für Hosts, die von Hand oder mit älteren Skripten eingerichtet wurden. Agent, Timer, apt-Hook und
# Sicherheitsupdates bleiben unberührt; es wird kein Dienst neu gestartet.
#
#   sudo bash upgrade-host.sh               prüfen und zeigen, was sich ändern würde (ändert nichts)
#   sudo bash upgrade-host.sh --apply       austauschen; alte Fassungen bleiben als *.bak-qb liegen
#   sudo bash upgrade-host.sh --rollback    alte Fassungen zurückholen
#
# Optionen zu --apply:
#   --fix-stdin   Stellen, die Text in "hc ping" pipen, um " -" ergänzen (sonst fehlt dort künftig der Text)
#   --no-report   updates-report danach nicht gleich ausführen
#   --register    eigenes Melde-Token für diesen Host holen (ab Server v0.9) und in /etc/hc.conf eintragen; nutzt
#                 QB_INSTALL_TOKEN (Installer-Token aus der App) oder, solange erlaubt, das bisherige gemeinsame Token
# Fehlt HC_PING_BASE oder STATUS_INGEST_URL in /etc/hc.conf (ältere Skripte hatten dafür einen eingebauten Standard),
# die Werte mitgeben:
#   sudo QB_PING_BASE=http://<server>:8000/ping QB_INGEST_URL=http://<server>:8088/api/ingest/updates bash upgrade-host.sh --apply
set -euo pipefail

ROOT=${QB_ROOT:-}          # nur für Tests: alles unterhalb dieses Ordners
BIN=$ROOT/usr/local/bin
CONF=$ROOT/etc/hc.conf
BAK=.bak-qb
LIST=$ROOT/var/backups/quietboard-upgrade.list   # Dateien, die --fix-stdin geändert hat (für --rollback)
here=$(cd "$(dirname "$0")" && pwd)
FILES=(hc updates-report)

mode=check fix_stdin=0 report=1 register=0
for a in "$@"; do
  case $a in
    --apply) mode=apply ;;
    --rollback) mode=rollback ;;
    --fix-stdin) fix_stdin=1 ;;
    --no-report) report=0 ;;
    --register) register=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "Unbekannte Option: $a" >&2; exit 2 ;;
  esac
done
[ -n "$ROOT" ] || [ "$(id -u)" = 0 ] || { echo "Bitte als root ausführen (sudo bash $0 …)" >&2; exit 1; }

say() { printf '%s\n' "$*"; }
sum() { # kurze Prüfsumme oder "–"
  if [ ! -e "$1" ]; then echo "–"; elif command -v sha256sum >/dev/null; then sha256sum "$1" | cut -c1-12; else shasum -a 256 "$1" | cut -c1-12; fi
}
has_key() { grep -qE "^$1=" "$CONF" 2>/dev/null; }

# Stellen, die Text in "hc ping" pipen: "… | hc ping slug [art]" ohne "-" am Ende
PIPE_RE='\|[[:space:]]*(/usr/local/bin/)?hc ping [^|;&]*[^ |;&-][[:space:]]*$'
pipe_files() {
  local d
  for d in "$ROOT/etc/crontab" "$ROOT/etc/cron.d" "$ROOT/etc/cron.hourly" "$ROOT/etc/cron.daily" "$ROOT/etc/cron.weekly" \
    "$ROOT/etc/cron.monthly" "$ROOT/var/spool/cron/crontabs" "$ROOT/etc/systemd/system" "$ROOT/usr/local/bin" \
    "$ROOT/usr/local/sbin" "$ROOT/root" "$ROOT/opt"; do
    [ -e "$d" ] || continue
    find "$d" -maxdepth 3 -type f -size -512k ! -name "*$BAK" ! -path "$BIN/hc" ! -path "$here/*" 2>/dev/null
  done | sort -u | while IFS= read -r f; do
    grep -IqE "$PIPE_RE" "$f" 2>/dev/null && printf '%s\n' "$f"
  done
}

if [ "$mode" = rollback ]; then
  n=0
  for f in "${FILES[@]}"; do
    if [ -e "$BIN/$f$BAK" ]; then mv "$BIN/$f$BAK" "$BIN/$f"; say "zurück: $BIN/$f"; n=$((n + 1)); fi
  done
  if [ -e "$CONF$BAK" ]; then mv "$CONF$BAK" "$CONF"; say "zurück: $CONF"; n=$((n + 1)); fi
  if [ -f "$LIST" ]; then
    while IFS= read -r f; do
      if [ -e "$f$BAK" ]; then mv "$f$BAK" "$f"; say "zurück: $f"; n=$((n + 1)); fi
    done < "$LIST"
    rm -f "$LIST"
  fi
  say "Rückweg fertig ($n Dateien)."
  exit 0
fi

# ---------------------------------------------------------------- Prüfen (beide Modi)
for f in "${FILES[@]}"; do
  [ -f "$here/$f" ] || { echo "$here/$f fehlt – Skript aus dem entpackten Paket (…/hosts/) starten" >&2; exit 1; }
  bash -n "$here/$f" || { echo "$here/$f: Syntaxfehler" >&2; exit 1; }
done
[ -f "$CONF" ] || { echo "$CONF fehlt – dieser Host ist anders eingerichtet. Neue Hosts: Befehl aus \"Host hinzufügen\"." >&2; exit 1; }

say "== Dateien (installiert → neu)"
for f in "${FILES[@]}"; do
  a=$(sum "$BIN/$f") b=$(sum "$here/$f")
  if [ "$a" = "$b" ]; then s="gleich"; elif [ "$a" = "–" ]; then s="neu"; else s="wird ersetzt"; fi
  printf '  %-15s %s → %s  (%s)\n' "$f" "$a" "$b" "$s"
done

say "== $CONF (nur Schlüssel)"
printf '  %s\n' "$(grep -oE '^[A-Z_]+=' "$CONF" | tr -d '=' | tr '\n' ' ')"
missing=()
for k in HC_PING_KEY STATUS_INGEST_TOKEN; do has_key "$k" || missing+=("$k"); done
add=()
if ! has_key HC_PING_BASE; then
  if [ -n "${QB_PING_BASE:-}" ]; then add+=("HC_PING_BASE=$QB_PING_BASE"); else missing+=("HC_PING_BASE (QB_PING_BASE=… mitgeben)"); fi
fi
if ! has_key STATUS_INGEST_URL; then
  if [ -n "${QB_INGEST_URL:-}" ]; then add+=("STATUS_INGEST_URL=$QB_INGEST_URL"); else missing+=("STATUS_INGEST_URL (QB_INGEST_URL=… mitgeben)"); fi
fi
for x in ${add[@]+"${add[@]}"}; do say "  wird ergänzt: $x"; done
for x in ${missing[@]+"${missing[@]}"}; do say "  FEHLT: $x"; done
has_key STATUS_HOST || say "  Hinweis: STATUS_HOST fehlt – der Host meldet sich als $(hostname -s)"
if grep -qE "^STATUS_INGEST_TOKEN=['\"]?qbh_" "$CONF"; then say "  Melde-Token: eigenes für diesen Host"
else say "  Melde-Token: gemeinsames (eigenes holen mit --register, ab Server v0.9)"; fi

say "== Stellen, die Text in \"hc ping\" pipen (brauchen künftig ein \"-\" am Ende)"
pipes=()
while IFS= read -r f; do pipes+=("$f"); done < <(pipe_files)
if [ ${#pipes[@]} = 0 ]; then say "  keine"; fi
for f in ${pipes[@]+"${pipes[@]}"}; do
  grep -nE "$PIPE_RE" "$f" | sed "s|^|  $f:|"
done

if [ "$mode" = check ]; then
  if [ ${#missing[@]} -gt 0 ]; then say "Erst die fehlenden Werte klären, dann --apply."; exit 1; fi
  opt=""; if [ ${#pipes[@]} -gt 0 ]; then opt=" --fix-stdin"; fi
  say "Nichts geändert. Austauschen mit: sudo bash $0 --apply$opt"
  exit 0
fi

# ---------------------------------------------------------------- Austauschen
[ ${#missing[@]} = 0 ] || { echo "Abbruch, nichts geändert: Werte fehlen (siehe oben)." >&2; exit 1; }
say "== Austauschen"
# Sicherungen nur beim ersten Lauf anlegen (zweiter Lauf überschreibt die Originale nicht)
[ -e "$CONF$BAK" ] || cp -a "$CONF" "$CONF$BAK"
for f in "${FILES[@]}"; do
  if [ -e "$BIN/$f" ] && [ ! -e "$BIN/$f$BAK" ]; then cp -a "$BIN/$f" "$BIN/$f$BAK"; fi
done
if [ ${#add[@]} -gt 0 ]; then
  if [ -n "$(tail -c1 "$CONF")" ]; then echo >> "$CONF"; fi   # Zeilenumbruch am Ende sicherstellen
  for x in "${add[@]}"; do printf '%s\n' "$x" >> "$CONF"; done
fi
chmod 600 "$CONF"
[ -n "$ROOT" ] || chown root:root "$CONF"
mkdir -p "$BIN"
for f in "${FILES[@]}"; do install -m 0755 "$here/$f" "$BIN/$f"; say "  $BIN/$f"; done

if [ "$register" = 1 ]; then
  # shellcheck disable=SC1090
  url=$( . "$CONF"; printf '%s' "${QB_REGISTER_URL:-${STATUS_INGEST_URL%/api/ingest/updates}/api/install/register}")
  # shellcheck disable=SC1090
  name=$( . "$CONF"; printf '%s' "${STATUS_HOST:-$(hostname -s)}")
  # shellcheck disable=SC1090
  auth=${QB_INSTALL_TOKEN:-$( . "$CONF"; printf '%s' "${STATUS_INGEST_TOKEN:-}")}
  hdr=$(mktemp); chmod 600 "$hdr"; printf 'Authorization: Bearer %s\n' "$auth" > "$hdr"
  tok=$(curl -fsS -m 20 -H @"$hdr" -H 'Content-Type: application/json' --data-binary "{\"host\":\"$name\"}" "$url" 2>/dev/null \
    | sed -n 's/.*"token": *"\(qbh_[A-Za-z0-9_-]*\)".*/\1/p') || true
  rm -f "$hdr"
  if [ -n "$tok" ]; then
    t=$(mktemp); grep -v '^STATUS_INGEST_TOKEN=' "$CONF" > "$t" || true
    printf "STATUS_INGEST_TOKEN='%s'\n" "$tok" >> "$t"; cat "$t" > "$CONF"; rm -f "$t"
    say "  eigenes Melde-Token für $name eingetragen"
  else
    say "  Anmeldung fehlgeschlagen ($url) – Melde-Token unverändert. Server ab v0.9? Token gültig?"
  fi
fi
if [ "$fix_stdin" = 1 ] && [ ${#pipes[@]} -gt 0 ]; then
  mkdir -p "$(dirname "$LIST")"
  for f in "${pipes[@]}"; do
    case $f in "$ROOT/var/spool/cron/crontabs/"*) say "  von Hand (crontab -e): $f"; continue ;; esac
    [ -e "$f$BAK" ] || cp -a "$f" "$f$BAK"
    t=$(mktemp)
    sed -E 's/(\|[[:space:]]*(\/usr\/local\/bin\/)?hc ping [^|;&]*[^ |;&-])[[:space:]]*$/\1 -/' "$f" > "$t"
    cat "$t" > "$f"; rm -f "$t"   # cat: Rechte und Besitzer der Datei bleiben
    grep -qxF "$f" "$LIST" 2>/dev/null || printf '%s\n' "$f" >> "$LIST"
    say "  \"-\" ergänzt: $f"
  done
fi

say "== Prüfen"
# shellcheck disable=SC1090
( . "$CONF"; for k in HC_PING_BASE HC_PING_KEY STATUS_INGEST_URL STATUS_INGEST_TOKEN; do
    if [ -n "${!k:-}" ]; then say "  $k gesetzt"; else say "  $k LEER"; fi
  done )
if [ "$report" = 1 ] && [ -z "$ROOT" ]; then
  if "$BIN/updates-report"; then say "  updates-report: gemeldet (in der App: Updates → Stand)"; else say "  updates-report: Exit $? – Ausgabe oben prüfen"; fi
fi
say "Fertig. Zurück mit: sudo bash $0 --rollback"
