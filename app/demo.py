"""Beispieldaten für DEMO=true: zeigt die Oberfläche ohne Healthchecks und Beszel.

Genutzt für lokale Entwicklung, Screenshots und die spätere statische Demo.
Alle Namen sind erfunden.
"""

from __future__ import annotations

import datetime as dt

HOSTS = [
    # name, status, cpu, mem, disk
    ("proxmox", "up", 12.0, 61.0, 48.0),
    ("docker01", "up", 23.5, 72.0, 91.0),
    ("nas", "down", None, None, None),
    ("vps", "up", 4.1, 38.0, 55.0),
]

CHECKS = [
    # name, status, host, typ, prio
    ("proxmox/vzdump", "up", "proxmox", "backup", "kritisch"),
    ("proxmox/pbs-verify", "up", "proxmox", "verify", "normal"),
    ("docker01/restic-offsite", "down", "docker01", "backup", "kritisch"),
    ("docker01/certbot", "up", "docker01", "zertifikat", "normal"),
    ("vps/db-dump", "started", "vps", "backup", "kritisch"),
    ("nas/online", "grace", "nas", "fenster", "info"),
]

UPDATES = {
    "docker01|apt": [("openssl", "3.0.15-1", "3.0.17-1", True, 72), ("curl", "8.14.1-1", "8.14.1-2", False, 5)],
    "vps|apt": [("tzdata", "2025b-1", "2026a-1", False, 20)],
    "docker01|docker": [("Immich", "v1.140.0", "v1.141.1", False, 30)],
}

_applied = False


def apply(state: dict, updates: dict, flags: dict, events: list, now: dt.datetime) -> None:
    """Füllt den App-Zustand einmalig mit Beispieldaten."""
    global _applied
    iso = lambda d: d.isoformat(timespec="seconds")  # noqa: E731
    state["checks"] = [
        {
            "uuid": f"00000000-0000-4000-8000-{i:012d}",
            "name": n,
            "status": s,
            "last_ping": iso(now - dt.timedelta(hours=5 + i)),
            "next_ping": iso(now + dt.timedelta(hours=19 - i)),
            "last_duration": 60 * (i + 1),
            "host": h,
            "typ": t,
            "prio": p,
        }
        for i, (n, s, h, t, p) in enumerate(CHECKS)
    ]
    state["hosts"] = [
        {
            "id": f"demo{i}",
            "name": n,
            "status": s,
            "cpu": c,
            "mem": m,
            "disk": d,
            "uptime": 86400 * (3 + i) if s == "up" else None,
            "agent": "0.21.2",
            "updated": iso(now - dt.timedelta(minutes=1 if s == "up" else 600)),
        }
        for i, (n, s, c, m, d) in enumerate(HOSTS)
    ]
    state["errors"] = {}
    if _applied:
        return
    _applied = True
    for key, items in UPDATES.items():
        host, kind = key.split("|")
        updates[key] = {
            "host": host,
            "kind": kind,
            "checked": iso(now),
            "items": [
                {"pkg": p, "from": f, "to": t, "security": sec, "since": iso(now - dt.timedelta(hours=age))} for p, f, t, sec, age in items
            ],
        }
    flags["docker01"] = {"reboot": True, "checked": iso(now)}
    events.insert(
        0,
        {
            "ts": iso(now - dt.timedelta(hours=2)),
            "source": "notify",
            "title": "docker01: restic-offsite fehlgeschlagen",
            "message": "Fatal: unable to open repository (demo)",
            "prio": "normal",
        },
    )
