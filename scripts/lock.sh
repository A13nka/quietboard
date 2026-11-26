#!/usr/bin/env bash
# requirements.lock aus requirements.txt erzeugen: alle (auch indirekten) Abhängigkeiten fest, mit Prüfsummen.
# Das Image installiert nur diese Datei (pip --require-hashes). Aufruf: make lock
set -euo pipefail
cd "$(dirname "$0")/.."
base=$(sed -n 's/^FROM //p' Dockerfile | head -1)   # gleiche Python-Version wie im Image
docker run --rm -v "$PWD:/w" -w /w "$base" sh -c \
  'pip install -q --root-user-action=ignore uv==0.13.10 && uv pip compile requirements.txt --generate-hashes --universal --python-version 3.13 --no-header --quiet -o /tmp/lock && cat /tmp/lock' > requirements.lock.tmp
{
  echo "# Erzeugt aus requirements.txt (direkte Abhängigkeiten) mit:  make lock"
  echo "# Alle indirekten Abhängigkeiten fest, mit Prüfsummen; das Image installiert nur diese Datei (--require-hashes)."
  cat requirements.lock.tmp
} > requirements.lock
rm -f requirements.lock.tmp
grep -cE '^[a-z]' requirements.lock | sed 's/$/ Pakete festgelegt/'
