#!/usr/bin/env bash
# Endlosschleife: Update-Bericht + gelegentlich eine Meldung an QuietBoard.
set -u
cat > /etc/hc.conf <<CONF
STATUS_INGEST_URL=${STATUS_URL}/api/ingest/updates
STATUS_INGEST_TOKEN=${INGEST_TOKEN}
STATUS_HOST=${FAKE_HOST:-fakehost}
CONF
n=0
while true; do
  bash /usr/local/bin/updates-report && echo "fakehost: Update-Bericht gesendet"
  if (( n % 5 == 0 )); then
    curl -fsS -m 10 -o /dev/null -H "Authorization: Bearer ${INGEST_TOKEN}" -H 'Content-Type: application/json' \
      --data-binary "{\"source\":\"fakehost\",\"title\":\"${FAKE_HOST:-fakehost}: Testmeldung ${n}\",\"message\":\"Simulierte Meldung aus dev/fakehost\",\"prio\":\"info\"}" \
      "${STATUS_URL}/api/ingest/notify" && echo "fakehost: Meldung gesendet"
  fi
  n=$((n + 1))
  sleep "${INTERVAL:-120}"
done
