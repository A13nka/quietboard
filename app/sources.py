"""Datenquellen ohne App-Zustand: Proxmox Backup Server, Versionsvergleich für watch_images.

Aus app/main.py herausgelöst (gleiches Verhalten); main.py importiert die Namen weiter.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import logging
import os
import re
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger("status")
TZ = ZoneInfo(os.environ.get("TZ") or "UTC")


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


_pbs_warned: set[str] = set()


def _fingerprint(resp: httpx.Response) -> str:
    """SHA-256 des Server-Zertifikats der Verbindung, über die `resp` kam (Hex, klein, ohne Doppelpunkte)."""
    stream = resp.extensions.get("network_stream")
    obj = stream.get_extra_info("ssl_object") if stream else None
    der = obj.getpeercert(binary_form=True) if obj else None
    return hashlib.sha256(der).hexdigest() if der else ""


def pbs_verify(check: str) -> tuple[bool | str, str]:
    """(verify-Wert für httpx, erwarteter Fingerprint) aus dem optionalen 5. Feld von PBS_TARGETS."""
    check = (check or "").strip()
    if check.lower() == "verify":
        return True, ""
    if check.lower().startswith("ca:"):
        return check[3:], ""
    fp = check.replace(":", "").lower()
    if fp and not re.fullmatch(r"[0-9a-f]{64}", fp):
        raise ValueError("PBS_TARGETS: Prüfung muss ein SHA-256-Fingerprint, ca:/pfad oder verify sein")
    return False, fp


async def fetch_pbs(name: str, url: str, token_id: str, secret: str, check: str = "") -> dict:
    verify, fp = pbs_verify(check)
    if verify is False and not fp and name not in _pbs_warned:
        _pbs_warned.add(name)
        log.warning("PBS %s: Zertifikat wird nicht geprüft – Fingerprint als 5. Feld in PBS_TARGETS eintragen (Doku: env)", name)
    async with httpx.AsyncClient(timeout=10, verify=verify) as cli:
        if fp:
            # Erst ohne Token prüfen, mit wem wir sprechen; danach jede Antwort (neue Verbindungen möglich)
            probe = await cli.get(f"{url}/api2/json/version")
            if _fingerprint(probe) != fp:
                raise ValueError(f"PBS {name}: Zertifikat passt nicht zum Fingerprint")
        headers = {"Authorization": f"PBSAPIToken={token_id}:{secret}"}
        r1 = (await cli.get(f"{url}/api2/json/status/datastore-usage", headers=headers)).raise_for_status()
        r2 = (
            await cli.get(f"{url}/api2/json/nodes/localhost/tasks", params={"running": 1, "limit": 20}, headers=headers)
        ).raise_for_status()
        if fp and not (_fingerprint(r1) == fp and _fingerprint(r2) == fp):
            raise ValueError(f"PBS {name}: Zertifikat passt nicht zum Fingerprint")
        ds, tasks = r1.json()["data"], r2.json()["data"]
    return {
        "online": True,
        "checked": now().isoformat(timespec="seconds"),
        "datastores": [{"store": d.get("store"), "total": d.get("total"), "used": d.get("used")} for d in ds],
        "running": [{"type": t.get("worker_type"), "id": t.get("worker_id"), "start": t.get("starttime")} for t in tasks],
    }


TAG_RE = re.compile(r"^(v?)(\d+(?:\.\d+)*)(.*)$")


def _ver(tag: str):
    m = TAG_RE.match(tag)
    if not m:
        return None
    return m.group(1), tuple(int(x) for x in m.group(2).split(".")), m.group(3)
