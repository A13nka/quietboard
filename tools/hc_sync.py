"""Gleicht config/checks.yaml mit Healthchecks ab (anlegen/aktualisieren, nie löschen).

Aufruf:
    docker compose run --rm status python -m tools.hc_sync          # Änderungen anwenden
    docker compose run --rm status python -m tools.hc_sync --dry    # nur anzeigen

Benötigt HC_URL und HC_API_KEY (Schreib-Key des Projekts) aus der Umgebung.
Gibt am Ende die Ping-URLs aus.
"""

from __future__ import annotations

import os
import sys

import httpx

from app import bootstrap, config

HC_URL = os.getenv("HC_URL", "http://healthchecks:8000").rstrip("/")
CREDS = bootstrap.load()
HC_KEY = CREDS.hc_api_key
PING_BASE = os.getenv("HC_PING_ENDPOINT", "http://localhost:8000/ping/").rstrip("/")
PING_KEY = CREDS.hc_ping_key or "<ping-key>"


def main() -> int:
    dry = "--dry" in sys.argv
    if not HC_KEY:
        print("Kein Healthchecks-API-Key (weder HC_API_KEY noch /bootstrap/healthchecks.json)", file=sys.stderr)
        return 1
    cfg = config.load()
    tz = cfg["settings"].get("tz", os.getenv("TZ", "UTC"))
    prio_channels = cfg["settings"].get("channels", {})

    # Pro Anfrage neue Verbindung (siehe docs/decisions/0005-keepalive-healthchecks.md)
    with httpx.Client(base_url=HC_URL, headers={"X-Api-Key": HC_KEY}, timeout=20, limits=httpx.Limits(max_keepalive_connections=0)) as cli:
        chans = cli.get("/api/v3/channels/").raise_for_status().json()["channels"]
        by_name = {c["name"]: c["id"] for c in chans}
        existing = {c["name"]: c for c in cli.get("/api/v3/checks/").raise_for_status().json()["checks"]}

        missing = {n for names in prio_channels.values() for n in names} - by_name.keys()
        if missing:
            print(f"WARNUNG: Integrationen fehlen in Healthchecks: {', '.join(sorted(missing))}")

        for c in cfg["checks"]:
            ids = [by_name[n] for n in prio_channels.get(c["prio"], []) if n in by_name]
            body = {
                "name": c["name"],
                "slug": c["slug"],
                "tags": config.tag_string(c["tags"]),
                "desc": c.get("desc", ""),
                "grace": config.seconds(c.get("grace", "1h")),
                "unique": ["name"],
            }
            # Kanäle nur setzen, wenn checks.yaml sie festlegt – sonst blieben bestehende Zuordnungen nicht erhalten
            if prio_channels:
                body["channels"] = ",".join(ids)
            if "schedule" in c:
                body.update(schedule=c["schedule"], tz=tz)
            else:
                body["timeout"] = config.seconds(c.get("period", "1d"))

            action = "aktualisieren" if c["name"] in existing else "anlegen"
            print(f"{action:13} {c['name']:32} prio={c['prio']:8} {body.get('schedule', body.get('timeout'))}")
            if not dry:
                cli.post("/api/v3/checks/", json=body).raise_for_status()

        extra = sorted(set(existing) - {c["name"] for c in cfg["checks"]})
        if extra:
            print("\nIn Healthchecks, aber nicht in checks.yaml (nicht gelöscht):")
            for n in extra:
                print(f"  - {n}")

    print("\nPing-URLs (Slug-Variante):")
    for c in cfg["checks"]:
        if not c.get("match"):
            print(f"  {c['name']:32} {PING_BASE}/{PING_KEY}/{c['slug']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
