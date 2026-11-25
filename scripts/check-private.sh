#!/usr/bin/env bash
# Sucht persönliche Werte (Domains, IPs, Namen) in allen Dateien, die ins Repo gehören.
# Die Muster stehen in .private-patterns (eine Regex pro Zeile, # = Kommentar).
# Diese Datei ist absichtlich NICHT im Repo – sonst stünden die Werte ja doch drin.
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .private-patterns ] || { echo "check-private: keine .private-patterns – übersprungen"; exit 0; }
pat=$(grep -vE '^\s*(#|$)' .private-patterns | paste -sd'|' -)
[ -n "$pat" ] || exit 0
if git rev-parse --git-dir >/dev/null 2>&1; then
  files=$(git ls-files -co --exclude-standard | grep -vE '^\.private-patterns$' || true)
else
  files=$(find . -type f -not -path './.git/*' -not -path './.venv/*' -not -name '.env' -not -name '.private-patterns')
fi
# shellcheck disable=SC2086
if hits=$(printf '%s\n' $files | tr '\n' '\0' | xargs -0 grep -nIiE "$pat" 2>/dev/null); then
  echo "check-private: persönliche Werte gefunden:" >&2
  echo "$hits" >&2
  exit 1
fi
echo "check-private: sauber"
