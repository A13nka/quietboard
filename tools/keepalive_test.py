"""Machbarkeitstest: Hält Healthchecks wiederverwendete HTTP-Verbindungen (Keep-alive) aus?

Hintergrund: Mit Healthchecks v4 (uWSGI) brachen Keep-alive-Verbindungen hart ab, deshalb nutzt die App
max_keepalive_connections=0. Seit v5 läuft Healthchecks mit gunicorn.

Aufruf im laufenden Stack:
    docker compose exec status python -m tools.keepalive_test [anzahl] [pause_sekunden]
Exitcode 0 = keine Fehler.
"""

from __future__ import annotations

import os
import sys
import time

import httpx

from app import bootstrap


def main() -> int:
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    pause = float(sys.argv[2]) if len(sys.argv) > 2 else 0.0
    key = bootstrap.load().hc_api_key
    if not key:
        print("Kein Healthchecks-API-Key", file=sys.stderr)
        return 2
    url = os.getenv("HC_URL", "http://healthchecks:8000").rstrip("/") + "/api/v3/checks/"
    errors: list[str] = []
    closed = 0  # Antworten mit "Connection: close" → Server beendet die Verbindung selbst, kein Keep-alive
    t0 = time.monotonic()
    with httpx.Client(headers={"X-Api-Key": key}, timeout=10, limits=httpx.Limits(max_keepalive_connections=5)) as cli:
        for i in range(n):
            try:
                r = cli.get(url)
                r.raise_for_status()
                closed += r.headers.get("connection", "").lower() == "close"
            except Exception as exc:
                errors.append(f"#{i}: {type(exc).__name__}: {exc}")
            if pause:
                time.sleep(pause)
    dt = time.monotonic() - t0
    print(f"{n} Aufrufe in {dt:.1f} s, {len(errors)} Fehler, {closed} Antworten mit 'Connection: close'")
    if closed == n - len(errors):
        print("Server schließt nach jeder Anfrage selbst (kein Keep-alive) – Wiederverwendung findet nicht statt.")
    for e in errors[:10]:
        print("  " + e)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
