"""Datenquellen ohne App-Zustand: Proxmox Backup Server, Versionsvergleich für watch_images.

Aus app/main.py herausgelöst (gleiches Verhalten); main.py importiert die Namen weiter.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import hashlib
import logging
import os
import re
import ssl
from urllib.parse import urlparse
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


_pinned: dict[tuple[str, str], ssl.SSLContext] = {}
_NO_CHECK_TIME = 0x200000  # X509_V_FLAG_NO_CHECK_TIME: wie bei PVE zählt nur der Fingerprint, nicht das Ablaufdatum


async def _pinned_context(name: str, url: str, fp: str) -> ssl.SSLContext:
    """TLS-Kontext, der im Handshake genau das Zertifikat mit diesem Fingerprint annimmt.

    Das Zertifikat wird einmal ohne Anfrage (nur Handshake) geholt und mit dem Fingerprint verglichen; danach ist es
    der einzige Vertrauensanker. So verlässt das PBS-Token die App nie über eine Verbindung, deren Gegenstelle noch
    nicht geprüft ist (Review 3a-N4) – auch nicht bei neuen Verbindungen."""
    ctx = _pinned.get((url, fp))
    if ctx:
        return ctx
    u = urlparse(url)
    pem = await asyncio.to_thread(ssl.get_server_certificate, (u.hostname, u.port or 443), timeout=10)
    if hashlib.sha256(ssl.PEM_cert_to_DER_cert(pem)).hexdigest() != fp:
        raise ValueError(f"PBS {name}: Zertifikat passt nicht zum Fingerprint")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False  # PBS-Zertifikate lauten meist auf den Rechnernamen, nicht auf die Adresse
    ctx.verify_mode = ssl.CERT_REQUIRED
    ctx.load_verify_locations(cadata=pem)
    ctx.verify_flags = ssl.VERIFY_X509_PARTIAL_CHAIN | _NO_CHECK_TIME  # das Zertifikat selbst ist der Anker
    _pinned[(url, fp)] = ctx
    return ctx


def _cert_error(exc: BaseException) -> bool:
    """Steckt in der Kette (httpx → httpcore → ssl) ein abgelehntes Zertifikat?"""
    seen = 0
    while exc is not None and seen < 10:
        if isinstance(exc, ssl.SSLCertVerificationError):
            return True
        exc, seen = exc.__cause__ or exc.__context__, seen + 1
    return False


async def fetch_pbs(name: str, url: str, token_id: str, secret: str, check: str = "") -> dict:
    verify, fp = pbs_verify(check)
    if verify is False and not fp and name not in _pbs_warned:
        _pbs_warned.add(name)
        log.warning("PBS %s: Zertifikat wird nicht geprüft – Fingerprint als 5. Feld in PBS_TARGETS eintragen (Doku: env)", name)
    if fp:
        verify = await _pinned_context(name, url, fp)
    try:
        async with httpx.AsyncClient(timeout=10, verify=verify) as cli:
            headers = {"Authorization": f"PBSAPIToken={token_id}:{secret}"}
            r1 = (await cli.get(f"{url}/api2/json/status/datastore-usage", headers=headers)).raise_for_status()
            r2 = (
                await cli.get(f"{url}/api2/json/nodes/localhost/tasks", params={"running": 1, "limit": 20}, headers=headers)
            ).raise_for_status()
            ds, tasks = r1.json()["data"], r2.json()["data"]
    except httpx.ConnectError as exc:
        if fp and _pinned.pop((url, fp), None) and _cert_error(exc):
            raise ValueError(f"PBS {name}: Zertifikat passt nicht zum Fingerprint") from None
        raise
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
