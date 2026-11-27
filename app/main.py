"""QuietBoard: Ansicht über Healthchecks, Beszel, PBS und Update-Meldungen.

Nur lesend gegenüber den Motoren. Eigene Aufgaben:
- Morgenmeldung (Web Push, optional Signal)
- Ingest: Update-Berichte der Hosts, PVE/PBS-Webhooks (→ Healthchecks-Ping), Beszel-Alarme, generische Meldungen
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import datetime as dt
import hmac
import ipaddress
import json
import logging
import os
import re
import smtplib
import socket
import ssl
import time
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
import jwt
import yaml
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import alerts, auth, bootstrap, config, i18n, push, security
from . import jobs as jobs_mod
from .i18n import tr
from .sources import TAG_RE, _fingerprint, _ver, fetch_pbs, pbs_verify  # noqa: F401 (TAG_RE, _fingerprint: Altnamen)

log = logging.getLogger("status")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------- Einstellungen
E = os.getenv
TZ = ZoneInfo(E("TZ", "UTC"))
DATA = Path(E("DATA_DIR", "/data"))
STATIC = Path(__file__).parent / "static"
HOSTS_DIR = Path(E("HOSTS_DIR", str(Path(__file__).resolve().parents[1] / "hosts")))
POLL = int(E("POLL_SECONDS", "60"))

HC_URL = E("HC_URL", "http://healthchecks:8000").rstrip("/")
HC_PUBLIC = E("HC_PUBLIC_URL", "").rstrip("/")

BESZEL_URL = E("BESZEL_URL", "http://beszel:8090").rstrip("/")
BESZEL_PUBLIC = E("BESZEL_PUBLIC_URL", "").rstrip("/")
# Zugänge zu den Motoren: Umgebung oder automatische Einrichtung (app/bootstrap.py)
CREDS = bootstrap.load()

# PBS_TARGETS="pbs1|https://pbs1.example.lan:8007|status@pbs!app|SECRET[|prüfung];pbs2|https://...|...|..."
# prüfung (optional): SHA-256-Fingerprint des Zertifikats (PBS-Dashboard → „Fingerprint anzeigen“),
# ca:/pfad/zur/ca.pem oder verify (System-CAs). Ohne Angabe wird das Zertifikat nicht geprüft (Warnung im Log).
PBS_TARGETS = [(t.split("|") + [""])[:5] for t in E("PBS_TARGETS", "").split(";") if t.count("|") in (3, 4)]

SIGNAL_URL = E("SIGNAL_URL", "http://signal-api:8080").rstrip("/")
SIGNAL_NUMBER = E("SIGNAL_NUMBER", "")
SIGNAL_RECIPIENT = E("SIGNAL_RECIPIENT", "")  # group.xxxxx oder Telefonnummer

INGEST_TOKEN = E("INGEST_TOKEN", "")
# Zusätzlich erlaubte Absendernetze für den Beszel-Webhook (Standard: keine – nur der Beszel-Container selbst)
INTERNAL_NETS = [ipaddress.ip_network(n) for n in E("INTERNAL_NETS", "").split(",") if n.strip()]
BESZEL_HOST = urlparse(BESZEL_URL).hostname or "beszel"

ACCESS_TEAM = E("ACCESS_TEAM", "")  # <team>.cloudflareaccess.com -> nur <team>
ACCESS_AUD = E("ACCESS_AUD", "")
ALLOW_NO_AUTH = E("ALLOW_NO_AUTH", "0") == "1"  # nur für lokale Tests
APP_VERSION = E("APP_VERSION", "dev")
# Mail (gleicher SMTP-Block wie Healthchecks)
SMTP = {
    "host": E("SMTP_HOST", ""),
    "port": int(E("SMTP_PORT", "587") or 587),
    "user": E("SMTP_USER", ""),
    "password": E("SMTP_PASSWORD", ""),
    "from": E("SMTP_FROM", ""),
    "tls": E("SMTP_TLS", "True").lower() in ("1", "true", "yes"),
}
DEMO = E("DEMO", "0").lower() in ("1", "true", "yes")  # Beispieldaten statt Motoren
SITE_NAME = E("SITE_NAME", "Homelab")

VAPID = push.Vapid(E("VAPID_PRIVATE_KEY"), E("VAPID_SUBJECT", "mailto:admin@example.org")) if E("VAPID_PRIVATE_KEY") else None
PUSH_PRIOS = ("kritisch", "normal")
# Adresse der Oberfläche für Links in Signal/Mail (optional; Push öffnet die App ohnehin)
PUBLIC_URL = (E("PUBLIC_URL", "") or E("PUBLIC_ORIGINS", "").split(",")[0]).strip().rstrip("/")

DEDUP_SECONDS = 1800
# Keine Verbindungs-Wiederverwendung: Healthchecks v5 (gunicorn sync) schließt ohnehin nach jeder Anfrage;
# v4 (uWSGI) brach wiederverwendete Verbindungen hart ab. Siehe docs/decisions/0005-keepalive-healthchecks.md
NO_KEEPALIVE = httpx.Limits(max_keepalive_connections=0)

# ---------------------------------------------------------------- Persistenz
DATA.mkdir(parents=True, exist_ok=True)
STORE = auth.Store(DATA / "quietboard.db")  # Konten, Sitzungen, Einstellungen
i18n.set_language_source(lambda: STORE.get_setting("language") or (E("LANGUAGE", "") or "de")[:2])


def _load(name: str, default):
    p = DATA / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except Exception as exc:  # beschädigte Datei nicht crashen lassen – und nicht beim nächsten Speichern überschreiben
        keep = p.with_name(f"{name}.kaputt-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}")
        try:
            p.replace(keep)
            log.error("Kann %s nicht lesen (%s) – beiseitegelegt als %s, starte leer", name, exc, keep.name)
        except OSError:
            log.error("Kann %s nicht lesen: %s", name, exc)
        return default


def _save(name: str, obj) -> None:
    """Atomar und dauerhaft: erst vollständig in eine Temp-Datei (fsync), dann umbenennen (auch nach Stromausfall
    liegt entweder der alte oder der neue Stand vor, nie ein halber)."""
    p = DATA / name
    tmp = p.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False, indent=1))
        fh.flush()
        os.fsync(fh.fileno())
    tmp.replace(p)
    with contextlib.suppress(OSError):
        fd = os.open(DATA, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


updates: dict = _load("updates.json", {})  # key "<host>|<kind>" -> Bericht
events: list = _load("events.json", [])  # neueste zuerst, max 300
flags: dict = _load("flags.json", {})  # host -> {reboot, checked, sec_alerted}
SEC_GRACE_H = 48  # Security-Update gilt danach als überfällig
REPORT_STALE_H = 72  # Update-Bericht eines Hosts gilt danach als veraltet
digest_state: dict = _load("digest.json", {})
push_subs: dict = _load("push.json", {})  # endpoint -> Subscription
push_state: dict = _load("push_state.json", {})  # check-uuid -> letzter gemeldeter Status
alert_state: dict = _load("alerts.json", {"down_since": {}})  # wann ein Job rot wurde (für „war … ausgefallen“)
# Unterdrückung gleicher Meldungen: Schlüssel -> {fp: Inhalt/Zustand, ts}. In einer Datei, damit ein Neustart
# (z. B. durch ein nächtliches Backup) nicht dieselbe Meldung erneut auslöst.
dedup: dict = _load("dedup.json", {})

state: dict = {"generated": None, "checks": [], "hosts": [], "pbs": {}, "errors": {}, "error_since": {}, "heartbeat": None}
cfg: dict = {
    "settings": {},
    "hosts": {},
    "checks": [],
    "watch_images": [],
    "_problems": [],
}  # bis checks.yaml geladen ist (oder wenn sie fehlerhaft ist)


def now() -> dt.datetime:
    return dt.datetime.now(TZ)


def add_event(source: str, title: str, message: str, prio: str = "info") -> None:
    events.insert(
        0, {"ts": now().isoformat(timespec="seconds"), "source": source, "title": title[:200], "message": message[:4000], "prio": prio}
    )
    del events[300:]
    _save("events.json", events)


# ---------------------------------------------------------------- Signal
async def push_all(title: str, body: str = "", url: str = "/", tag: str | None = None) -> int:
    """Web-Push an alle registrierten Geräte. Rückgabe: Anzahl erfolgreich zugestellt."""
    if not (VAPID and push_subs):
        return 0
    msg = {"title": title, "body": body, "url": url, "tag": tag or title[:60]}
    ok, dead = 0, []
    async with httpx.AsyncClient(timeout=15) as cli:
        for ep, sub in list(push_subs.items()):
            try:
                r = await cli.post(**push.request_args(VAPID, sub, msg))
                if r.status_code in (404, 410):
                    dead.append(ep)
                elif r.status_code >= 400:
                    log.warning("Push an %s: HTTP %s %s", urlparse(ep).hostname, r.status_code, r.text[:200])
                else:
                    ok += 1
            except Exception as exc:
                log.warning("Push fehlgeschlagen: %s", exc)
    for ep in dead:
        push_subs.pop(ep, None)
    if dead:
        _save("push.json", push_subs)
        log.info("%d abgelaufene Push-Registrierung(en) entfernt", len(dead))
    return ok


def mail_recipients() -> list[str]:
    return [m for m in STORE.get_setting("mail_to", []) if m]


def _send_mail_sync(to: list[str], subject: str, body: str) -> None:
    msg = EmailMessage()
    msg["From"] = SMTP["from"] or SMTP["user"]
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    msg.set_content(body)
    if SMTP["port"] == 465:
        with smtplib.SMTP_SSL(SMTP["host"], SMTP["port"], timeout=20, context=ssl.create_default_context()) as srv:
            if SMTP["user"]:
                srv.login(SMTP["user"], SMTP["password"])
            srv.send_message(msg)
        return
    with smtplib.SMTP(SMTP["host"], SMTP["port"], timeout=20) as srv:
        if SMTP["tls"]:
            srv.starttls(context=ssl.create_default_context())
        if SMTP["user"]:
            srv.login(SMTP["user"], SMTP["password"])
        srv.send_message(msg)


async def send_mail(subject: str, body: str, to: list[str] | None = None) -> bool:
    to = to or mail_recipients()
    if not (SMTP["host"] and to):
        return False
    try:
        await asyncio.to_thread(_send_mail_sync, to, subject, body)
        return True
    except Exception as exc:
        log.error("Mail-Versand fehlgeschlagen: %s", exc)
        return False


def channels_configured() -> bool:
    """Gibt es überhaupt einen Weg, eine Meldung zuzustellen?"""
    return bool((VAPID and push_subs) or (SMTP["host"] and mail_recipients()) or (SIGNAL_NUMBER and SIGNAL_RECIPIENT))


def _dedup_hit(key: str, fp: str) -> bool:
    e = dedup.get(key)
    return bool(e) and e.get("fp") == fp and time.time() - e.get("ts", 0) < DEDUP_SECONDS


def _dedup_note(key: str, fp: str) -> None:
    t = time.time()
    for k in [k for k, e in dedup.items() if t - e.get("ts", 0) > DEDUP_SECONDS * 4]:
        dedup.pop(k)
    dedup[key] = {"fp": fp, "ts": t}
    _save("dedup.json", dedup)


async def send_signal(text: str, dedup_key: str | None = None, url: str = "/", fp: str | None = None, mail_text: str | None = None) -> bool:
    """Meldung an alle Kanäle: Web Push, Mail, Signal (Name historisch). True, wenn mindestens ein Kanal zugestellt hat.

    Dedup: Gleicher Schlüssel UND gleicher Inhalt (fp, Standard: erste Zeile) innerhalb von 30 min wird unterdrückt.
    Ein anderer Zustand (z. B. „down“ nach „up“) kommt immer durch. Gemerkt wird erst nach erfolgreicher Zustellung –
    schlägt alles fehl, darf der nächste Versuch durch."""
    lines = text.strip().splitlines() or [""]
    fp = fp if fp is not None else lines[0]
    if dedup_key and _dedup_hit(dedup_key, fp):
        log.info("Meldung unterdrückt (gleiche Meldung vor weniger als %d min): %s", DEDUP_SECONDS // 60, dedup_key)
        return False
    delivered = await push_all(lines[0], "\n".join(lines[1:]), url)
    subject = lines[0] if SITE_NAME in lines[0] else f"[{SITE_NAME}] {lines[0]}"
    delivered += int(await send_mail(subject, mail_text or text))
    if SIGNAL_NUMBER and SIGNAL_RECIPIENT:
        body = {"message": text, "number": SIGNAL_NUMBER, "recipients": [SIGNAL_RECIPIENT]}
        try:
            async with httpx.AsyncClient(timeout=30) as cli:
                r = await cli.post(f"{SIGNAL_URL}/v2/send", json=body)
                r.raise_for_status()
            delivered += 1
        except Exception as exc:
            log.error("Signal-Versand fehlgeschlagen: %s", exc)
    if not delivered:
        log.warning("Kein Kanal hat zugestellt: %s", text[:80])
        return False
    if dedup_key:
        _dedup_note(dedup_key, fp)
    return True


async def _last_ping_info(uuid: str) -> dict:
    """Letzter Ping eines Jobs: Fehler gemeldet? Zeitpunkt, Log. Leer, wenn Healthchecks nicht antwortet."""
    try:
        async with httpx.AsyncClient(timeout=10, headers={"X-Api-Key": CREDS.hc_api_key}, limits=NO_KEEPALIVE) as cli:
            pings = (await cli.get(f"{HC_URL}/api/v3/checks/{uuid}/pings/")).raise_for_status().json().get("pings", [])
            p = next((p for p in pings if p.get("type") not in ("start", "log")), None)
            if not p:
                return {}
            body = None
            if p.get("body_url"):
                b = await cli.get(f"{HC_URL}{urlparse(p['body_url']).path}")
                body = b.text[-20000:] if b.status_code == 200 else None
            return {"failed": p.get("type") == "fail", "date": p.get("date"), "body": body}
    except Exception as exc:
        log.warning("Letzter Ping von %s nicht lesbar: %s", uuid, exc)
        return {}


async def check_transitions() -> None:
    """Statuswechsel der Jobs melden (grün→rot, rot→grün).

    Modus "app": QuietBoard meldet über alle eigenen Kanäle (Push, Mail, Signal), mehrere Ausfälle eines Abrufs in einer
    Nachricht. Der Zustand gilt erst als gemeldet, wenn ein Kanal zugestellt hat – sonst nächster Versuch beim nächsten
    Abruf. Modus "hc": Healthchecks meldet über seine Integrationen, QuietBoard schickt zusätzlich nur Web Push."""
    if not state["checks"]:
        return
    first = not push_state  # allererster Lauf: nur merken, nichts melden
    now_ = now()
    since = alert_state.setdefault("down_since", {})
    downs, ups, changed = [], [], False
    for c in state["checks"]:
        cur, uid = c["status"], c["uuid"]
        if cur == "started":  # Laufzustand nicht merken, sonst geht rot→läuft→grün verloren
            continue
        prev = push_state.get(uid)
        if prev == cur:
            # Nie gemeldeter Ausfall, der sich von selbst erledigt hat: Beginn vergessen (sonst später „War 3 d ausgefallen“)
            if cur != "down" and since.pop(uid, None):
                changed = True
            continue
        if cur == "down" and prev != "down":
            since.setdefault(uid, now_.isoformat(timespec="seconds"))
        alert = not first and c["prio"] in PUSH_PRIOS
        if alert and cur == "down":
            downs.append(c)  # auch neue Jobs (prev None), die gleich ausfallen
        elif alert and prev == "down" and cur == "up":
            ups.append(c)
        else:
            push_state[uid] = cur
            changed = True
            if cur != "down":
                since.pop(uid, None)
    if job_alerts_mode() == "hc":
        for c in downs:
            await push_all(
                "🔴 " + tr("{name} ausgefallen", name=c["name"]),
                tr("Kein Ping zur erwarteten Zeit oder Fehler gemeldet."),
                f"/?c={c['uuid']}",
                c["uuid"],
            )
        for c in ups:
            await push_all("✅ " + tr("{name} wieder OK", name=c["name"]), "", f"/?c={c['uuid']}", c["uuid"])
        delivered = {c["uuid"] for c in downs + ups}
    else:
        delivered = set()
        if downs:
            infos = {c["uuid"]: await _last_ping_info(c["uuid"]) for c in downs}
            text, mail, url = alerts.down_message(downs, infos, now_, PUBLIC_URL)
            if await send_signal(text, url=url, mail_text=mail) or not channels_configured():
                delivered |= {c["uuid"] for c in downs}
        if ups:
            text, url = alerts.up_message(ups, since, now_)
            if await send_signal(text, url=url) or not channels_configured():
                delivered |= {c["uuid"] for c in ups}
    for c in downs + ups:
        if c["uuid"] in delivered:
            push_state[c["uuid"]] = c["status"]
            changed = True
            if c["status"] == "up":
                since.pop(c["uuid"], None)
    known = {c["uuid"] for c in state["checks"]}
    for uid in [u for u in push_state if u not in known]:  # gelöschte Jobs vergessen
        push_state.pop(uid)
        since.pop(uid, None)
        changed = True
    if changed:
        _save("push_state.json", push_state)
        _save("alerts.json", alert_state)


# ---------------------------------------------------------------- Datenquellen
async def fetch_checks(cli: httpx.AsyncClient) -> list[dict]:
    r = await cli.get(f"{HC_URL}/api/v3/checks/", headers={"X-Api-Key": CREDS.hc_api_key})
    r.raise_for_status()
    prio = {c["name"]: c["prio"] for c in cfg.get("checks", [])}
    out = []
    for c in r.json()["checks"]:
        tags = dict(t.split(":", 1) for t in c.get("tags", "").split() if ":" in t)
        if tags.get("src") == "app":  # Lebenszeichen von QuietBoard selbst – kein Job
            state["heartbeat"] = {"uuid": c.get("uuid") or c.get("unique_key"), "status": c.get("status"), "last_ping": c.get("last_ping")}
            continue
        status = c.get("status")
        if c.get("started") and status not in ("down",):
            status = "started"
        out.append(
            {
                "uuid": c.get("uuid") or c.get("unique_key"),
                "name": c["name"],
                "status": status,
                "last_ping": c.get("last_ping"),
                "next_ping": c.get("next_ping"),
                "last_duration": c.get("last_duration"),
                "schedule": c.get("schedule"),
                "tz": c.get("tz"),
                "timeout": c.get("timeout"),
                "grace": c.get("grace"),
                "host": tags.get("host", ""),
                "typ": tags.get("typ", ""),
                "prio": tags.get("prio") or prio.get(c["name"], "normal"),  # Healthchecks-Tag gewinnt (GUI ändert dort)
                "slug": c.get("slug") or config.slug(c["name"]),
                "src": tags.get("src", ""),
                "match": jobs_mod.match_from_tags(tags),
            }
        )
    return out


async def fetch_hosts(cli: httpx.AsyncClient) -> list[dict]:
    auth = await cli.post(
        f"{BESZEL_URL}/api/collections/users/auth-with-password", json={"identity": CREDS.beszel_user, "password": CREDS.beszel_pass}
    )
    auth.raise_for_status()
    token = auth.json()["token"]
    r = await cli.get(
        f"{BESZEL_URL}/api/collections/systems/records", params={"perPage": 200, "sort": "name"}, headers={"Authorization": token}
    )
    r.raise_for_status()
    out = []
    for s in r.json().get("items", []):
        info = s.get("info") or {}
        out.append(
            {
                "id": s.get("id"),
                "name": s.get("name"),
                "status": s.get("status"),
                "cpu": info.get("cpu"),
                "mem": info.get("mp"),
                "disk": info.get("dp"),
                "uptime": info.get("u"),
                "agent": info.get("v"),
                "updated": s.get("updated"),
            }
        )
    return out


async def check_watch_images(cli: httpx.AsyncClient) -> None:
    """Docker-Hub-Images aus checks.yaml (watch_images) auf neuere Tags gleichen Schemas prüfen."""
    seen: set[str] = set()
    for w in cfg.get("watch_images", []) or []:
        image, _, tag = w["image"].rpartition(":")
        cur = _ver(tag)
        if not cur:
            continue
        repo = image if "/" in image else f"library/{image}"
        # schon hier als gesehen merken: ein Fehler von Docker Hub (z. B. 429) darf bekannte Updates nicht löschen
        seen.add(f"{w.get('host', 'registry')}|{w.get('kind', 'docker')}:{w.get('label', image)}")
        try:
            r = await cli.get(f"https://hub.docker.com/v2/repositories/{repo}/tags", params={"page_size": 100, "ordering": "last_updated"})
            r.raise_for_status()
        except Exception as exc:
            state["errors"][f"registry:{image}"] = str(exc)
            continue
        state["errors"].pop(f"registry:{image}", None)
        best = None
        ignore = {str(x) for x in (w.get("ignore") or [])}
        for t in r.json().get("results", []):
            if t["name"] in ignore:
                continue
            v = _ver(t["name"])
            if v and v[0] == cur[0] and v[2] == cur[2] and len(v[1]) == len(cur[1]) and v[1] > cur[1]:
                if not best or v[1] > best[1]:
                    best = (t["name"], v[1])
        key = f"{w.get('host', 'registry')}|{w.get('kind', 'docker')}:{w.get('label', image)}"
        if best:
            updates[key] = {
                "host": w.get("host", "registry"),
                "kind": w.get("kind", "docker"),
                "checked": now().isoformat(timespec="seconds"),
                "items": [{"pkg": w.get("label", image), "from": tag, "to": best[0], "security": False}],
            }
        else:
            updates.pop(key, None)
        seen.add(key)
    for key in set(digest_state.get("watch_keys", [])) - seen:  # aus watch_images entfernte Einträge
        updates.pop(key, None)
    digest_state["watch_keys"] = sorted(seen)
    _save("updates.json", updates)


BESZEL_WEBHOOK = E("BESZEL_WEBHOOK", "generic://status:8080/api/ingest/beszel?template=json&disabletls=yes")
BESZEL_ALERT_DOWN_MIN = int(E("BESZEL_ALERT_DOWN_MIN", "5") or 5)


async def ensure_alerts() -> None:
    """Neue Hosts bekommen Standard-Alarme, Beszel meldet an die App (→ Push, Mail, Signal)."""
    admin_email, admin_password = E("ADMIN_EMAIL", ""), E("ADMIN_PASSWORD", "")
    ids = {h["id"] for h in state["hosts"] if h.get("id")}
    new = ids - bootstrap.alerts_done()
    if not (new and admin_email and admin_password and CREDS.beszel_ready):
        return
    try:
        done = await bootstrap.ensure_beszel_alerts(BESZEL_URL, admin_email, admin_password, new, BESZEL_WEBHOOK, BESZEL_ALERT_DOWN_MIN)
        bootstrap.mark_alerts_done(done)
        log.info("Beszel-Alarme für %d neue(n) Host(s) eingerichtet", len(done))
    except Exception as exc:
        log.warning("Beszel-Alarme: %s", exc)


_last_refresh = 0.0
_refresh_lock = asyncio.Lock()
_bg_tasks: set[asyncio.Task] = set()  # Referenzen halten, sonst kann der GC laufende Tasks einsammeln


async def refresh() -> None:
    """Nie zwei Abrufe gleichzeitig (sonst z. B. doppelte Beszel-Alarme oder konkurrierende Einrichtung).
    Läuft schon einer, wartet der Aufrufer auf dessen Ergebnis statt einen zweiten zu starten."""
    if _refresh_lock.locked():
        async with _refresh_lock:
            return
    async with _refresh_lock:
        await _refresh()


def refresh_soon(delay: float) -> None:
    """Abruf in `delay` Sekunden anstoßen (z. B. nach einem Ingest), mit gehaltener Task-Referenz."""

    def start():
        t = asyncio.create_task(refresh())
        _bg_tasks.add(t)
        t.add_done_callback(_bg_tasks.discard)

    asyncio.get_running_loop().call_later(delay, start)


async def _refresh() -> None:
    global cfg, _last_refresh
    _last_refresh = time.monotonic()
    try:
        cfg = config.load()
        if cfg["_problems"]:
            state["errors"]["checks.yaml"] = "; ".join(cfg["_problems"][:5])
        else:
            state["errors"].pop("checks.yaml", None)  # repariert → Warnung weg
    except Exception as exc:
        state["errors"]["checks.yaml"] = str(exc)
    if DEMO:
        from . import demo

        demo.apply(state, updates, flags, events, now())
        state["generated"] = now().isoformat(timespec="seconds")
        return
    await bootstrap.ensure(CREDS)
    async with httpx.AsyncClient(timeout=15, limits=NO_KEEPALIVE) as cli:
        jobs = {
            "healthchecks": fetch_checks(cli) if CREDS.hc_api_key else None,
            "beszel": fetch_hosts(cli) if CREDS.beszel_user else None,
        }
        for name, coro in jobs.items():
            if coro is None:
                state["errors"][name] = CREDS.errors.get(name, "nicht konfiguriert")
                continue
            try:
                result = await coro
                state["checks" if name == "healthchecks" else "hosts"] = result
                state["errors"].pop(name, None)
            except Exception as exc:
                state["errors"][name] = f"nicht erreichbar: {type(exc).__name__} {exc}".strip()
                log.warning("%s: %s %s", name, type(exc).__name__, exc)
                if (
                    name == "beszel"
                    and isinstance(exc, httpx.HTTPStatusError)
                    and exc.response.status_code in (400, 401, 403)
                    and not E("BESZEL_USER")
                ):
                    # Gespeicherter App-Zugang gilt nicht mehr (z. B. Beszel-Daten zurückgespielt): neu einrichten lassen
                    log.warning("Beszel: App-Zugang abgelehnt – wird beim nächsten Abruf neu eingerichtet")
                    CREDS.beszel_user = CREDS.beszel_pass = ""
        if "healthchecks" not in state["errors"]:
            try:
                await ensure_job_alert_mode()
                await ensure_heartbeat()
            except Exception as exc:
                log.warning("Job-Alarme/Lebenszeichen einrichten: %s", exc)
        await ensure_alerts()
        try:
            await check_transitions()
            await check_sec_overdue()
        except Exception:
            log.exception("Push-Auswertung fehlgeschlagen")
        for name, url, tid, sec, check in PBS_TARGETS:
            try:
                state["pbs"][name] = await fetch_pbs(name, url, tid, sec, check)
            except Exception as exc:
                if isinstance(exc, ValueError):
                    log.warning("%s", exc)
                prev = state["pbs"].get(name, {})
                state["pbs"][name] = {**prev, "online": False, "running": []}  # offline: keine "laufenden" Tasks anzeigen
        watch_cfg = json.dumps(cfg.get("watch_images"), sort_keys=True)
        if digest_state.get("watch_checked") != now().date().isoformat() or digest_state.get("watch_cfg") != watch_cfg:
            try:
                await check_watch_images(cli)
            except Exception as exc:
                log.warning("watch_images: %s", exc)
            digest_state["watch_checked"] = now().date().isoformat()
            digest_state["watch_cfg"] = watch_cfg
            _save("digest.json", digest_state)
        try:
            await check_source_outage()
        except Exception:
            log.exception("Quellen-Auswertung fehlgeschlagen")
    state["generated"] = now().isoformat(timespec="seconds")
    await ping_heartbeat()


# ---------------------------------------------------------------- Job-Alarme: Modus, Lebenszeichen, Quellen
HEARTBEAT_NAME, HEARTBEAT_SLUG = "quietboard/app", "quietboard-app"
SOURCE_ALERT_MIN = 15  # so lange darf eine Quelle (Healthchecks, Beszel) gestört sein, bevor gemeldet wird
SOURCES_WATCHED = ("healthchecks", "beszel")


async def ensure_job_alert_mode() -> None:
    """Beim ersten Start mit dieser Version festlegen, wer Job-Ausfälle meldet.
    QuietBoard ("app"), wenn Healthchecks nur die eigene Integration „E-Mail“ hat und kein Job Kanäle trägt (neue
    Installation) – sonst bleibt es bei Healthchecks ("hc"), damit sich bei übernommenen Installationen nichts
    ändert und nichts doppelt kommt. Umstellen: System → Benachrichtigungen."""
    if STORE.get_setting("job_alerts") in ("app", "hc"):
        return
    chans = (await _hc("GET", "/api/v3/channels/")).json()["channels"]
    foreign = [c for c in chans if not (c.get("kind") == "email" and c.get("name") == "E-Mail")]
    checks = (await _hc("GET", "/api/v3/checks/")).json()["checks"]
    assigned = [c for c in checks if c.get("channels") and "src:app" not in c.get("tags", "")]
    mode = "hc" if foreign or assigned else "app"
    STORE.set_setting("job_alerts", mode)
    log.info(
        "Job-Alarme über: %s (%d weitere Integrationen, %d Jobs mit Kanälen)",
        "Healthchecks" if mode == "hc" else "QuietBoard",
        len(foreign),
        len(assigned),
    )


async def ensure_heartbeat() -> None:
    """Check quietboard/app anlegen: QuietBoard pingt ihn bei jedem Abruf. Bleibt der Ping aus, meldet Healthchecks
    selbst über seine Integrationen – so fällt auch ein Ausfall von QuietBoard auf. Fehlt er (gelöscht, Healthchecks
    neu aufgesetzt), wird er neu angelegt. Abschalten: HEARTBEAT=0 in .env."""
    if state.get("heartbeat") or not (CREDS.hc_api_key and CREDS.hc_ping_key) or E("HEARTBEAT", "1") == "0":
        return
    if STORE.get_setting("heartbeat_created"):
        log.warning("Lebenszeichen %s fehlt in Healthchecks – lege es neu an (abschalten: HEARTBEAT=0)", HEARTBEAT_NAME)
    body = {
        "name": HEARTBEAT_NAME,
        "slug": HEARTBEAT_SLUG,
        "tags": "host:quietboard typ:wartung prio:kritisch src:app",
        "desc": tr("Lebenszeichen von QuietBoard. Wird rot, wenn die App nicht mehr läuft."),
        "timeout": 300,
        "grace": 600,
        "channels": "*",  # alle Integrationen von Healthchecks: der einzige Alarm, der ohne QuietBoard funktioniert
        "unique": ["slug"],
    }
    c = (await _hc("POST", "/api/v3/checks/", json=body)).json()
    STORE.set_setting("heartbeat_created", True)
    state["heartbeat"] = {"uuid": c.get("uuid") or c.get("unique_key"), "status": c.get("status"), "last_ping": None}
    log.info("Lebenszeichen %s in Healthchecks angelegt", HEARTBEAT_NAME)


async def ping_heartbeat() -> None:
    if not (state.get("heartbeat") and CREDS.hc_ping_key) or DEMO:
        return
    try:
        async with httpx.AsyncClient(timeout=10, limits=NO_KEEPALIVE) as cli:
            await cli.post(f"{HC_URL}/ping/{CREDS.hc_ping_key}/{HEARTBEAT_SLUG}", content=APP_VERSION.encode())
    except Exception as exc:
        log.warning("Lebenszeichen nicht gesendet: %s", exc)


async def check_source_outage() -> None:
    """Healthchecks oder Beszel länger als SOURCE_ALERT_MIN gestört → einmal melden, bei Rückkehr Entwarnung."""
    track = state.setdefault("error_since", {})
    t = now()
    for name in SOURCES_WATCHED:
        err = state["errors"].get(name)
        entry = track.get(name)
        if err and not entry:
            track[name] = {"since": t.isoformat(timespec="seconds"), "alerted": False}
        elif err and not entry["alerted"]:
            minutes = (t - dt.datetime.fromisoformat(entry["since"])).total_seconds() / 60
            if minutes >= SOURCE_ALERT_MIN and await send_signal(
                "🟠 " + tr("{q} gestört seit {m} min", q=name, m=int(minutes)) + f"\n{err[:300]}",
                dedup_key=f"src:{name}",
                fp="down",
                url="/?t=sy",
            ):
                entry["alerted"] = True
        elif not err and entry:
            track.pop(name)
            if entry["alerted"]:
                await send_signal("✅ " + tr("{q} wieder erreichbar", q=name), dedup_key=f"src:{name}", fp="up", url="/?t=sy")


# ---------------------------------------------------------------- Auswertung
def host_cfg(name: str) -> dict:
    return (cfg.get("hosts") or {}).get(name, {})


def _overdue(i: dict) -> bool:
    try:
        return bool(i.get("security")) and (now() - dt.datetime.fromisoformat(i["since"])).total_seconds() > SEC_GRACE_H * 3600
    except Exception:
        return False


def host_updates() -> list[dict]:
    """Updates je Host zusammengefasst, sortiert nach Dringlichkeit."""
    hosts: dict = {}

    def h_(name):
        return hosts.setdefault(
            name, {"host": name, "packages": 0, "security": 0, "sec_overdue": 0, "sec_overdue_pkgs": [], "kinds": [], "reboot": False}
        )

    for u in updates.values():
        h = h_(u["host"])
        h["packages"] += len(u["items"])
        if u["kind"] not in h["kinds"]:  # z. B. mehrere Docker-Image-Berichte → ein Schild „docker“
            h["kinds"].append(u["kind"])
        for i in u["items"]:
            if i.get("security"):
                h["security"] += 1
                if _overdue(i):
                    h["sec_overdue"] += 1
                    h["sec_overdue_pkgs"].append(i["pkg"])
    for name, f in flags.items():
        if f.get("reboot"):
            h_(name)["reboot"] = True
    return sorted(hosts.values(), key=lambda h: (-h["sec_overdue"], -h["security"], -int(h["reboot"]), -h["packages"], h["host"]))


def report_problems() -> dict[str, str]:
    """Hosts, deren Update-Bericht fehlschlug oder seit REPORT_STALE_H nicht kam (nur dauerhaft laufende, bekannte Hosts)."""
    out = {}
    known = {h["name"] for h in state["hosts"] if host_extra(h["name"])["always_on"]}
    limit = now() - dt.timedelta(hours=REPORT_STALE_H)
    for name, f in flags.items():
        if f.get("report_error"):
            out[name] = tr("Fehler beim Prüfen: {msg}", msg=f["report_error"]["msg"])
            continue
        last = max(f.get("reported") or "", f.get("checked") or "")
        if name in known and last:
            try:
                if dt.datetime.fromisoformat(last) < limit:
                    out[name] = tr("veraltet, letzter Bericht {t}", t=last[:16].replace("T", " "))
            except ValueError:
                pass
    return out


async def check_sec_overdue() -> None:
    """Einmalige Meldung, wenn Security-Updates länger als SEC_GRACE_H offen sind (Automatik hat nicht gegriffen)."""
    overdue = {h["host"]: h for h in host_updates() if h["sec_overdue"]}
    changed = False
    for name, h in overdue.items():
        sig = ",".join(sorted(h["sec_overdue_pkgs"]))
        f = flags.setdefault(name, {})
        if f.get("sec_alerted") != sig:
            sent = await send_signal(
                "🟠 "
                + tr("{name}: {n} Security-Update(s) seit über {h} h offen", name=name, n=h["sec_overdue"], h=SEC_GRACE_H)
                + "\n"
                + ", ".join(h["sec_overdue_pkgs"][:6]),
                url="/?t=up",
            )
            if sent or not channels_configured():  # erst nach Zustellung merken – sonst nächster Abruf erneut
                f["sec_alerted"] = sig
                changed = True
    for name, f in flags.items():
        if f.get("sec_alerted") and name not in overdue:
            f.pop("sec_alerted")
            changed = True
    if changed:
        _save("flags.json", flags)


def attention() -> list[dict]:
    items = []
    for c in state["checks"]:
        if c["status"] in ("down", "grace"):
            items.append(
                {
                    "level": "bad" if c["status"] == "down" else "warn",
                    "kind": "check",
                    "title": c["name"],
                    "detail": tr("überfällig/fehlgeschlagen") if c["status"] == "down" else tr("Karenzzeit läuft"),
                    "uuid": c["uuid"],
                }
            )
    for h in state["hosts"]:
        if host_extra(h["name"])["always_on"] and h["status"] not in ("up", "paused"):
            items.append({"level": "bad", "kind": "host", "title": tr("{name} offline", name=h["name"]), "detail": h["status"]})
        if (h.get("disk") or 0) >= 90:
            items.append({"level": "warn", "kind": "host", "title": f"{h['name']} · Disk", "detail": f"{h['disk']:.0f} %"})
    for h in host_updates():
        if h["sec_overdue"]:
            items.append(
                {
                    "level": "bad",
                    "kind": "update",
                    "title": tr("{host} · Security-Update überfällig", host=h["host"]),
                    "detail": tr("seit über {h} h offen: {pkgs}", h=SEC_GRACE_H, pkgs=", ".join(h["sec_overdue_pkgs"][:3])),
                }
            )
    for name, msg in report_problems().items():
        items.append({"level": "warn", "kind": "update", "title": tr("{host} · Update-Bericht", host=name), "detail": msg})
    cutoff = (now() - dt.timedelta(hours=24)).isoformat()
    for ev in events:
        if ev["ts"] < cutoff:
            break
        # Alle Quellen (pve, pbs, notify, dockhand, nas, synology, …); Beszel-Meldungen stecken schon im Host-Status
        if ev["prio"] in ("kritisch", "normal") and ev["source"] != "beszel":
            items.append({"level": "warn", "kind": "event", "title": ev["title"], "detail": ev["message"][:300]})
    for name in SOURCES_WATCHED:  # ohne Quelle ist „alles grün“ keine Aussage
        if state["errors"].get(name):
            items.insert(
                0, {"level": "bad", "kind": "source", "title": tr("{q} nicht erreichbar", q=name), "detail": state["errors"][name][:200]}
            )
    return items


def summary() -> dict:
    checks = state["checks"]
    ok = sum(1 for c in checks if c["status"] in ("up", "started", "new", "paused"))
    # Alle Hosts zählen, außer solchen mit Zeitfenster (checks.yaml: always_on: false)
    hosts = [h for h in state["hosts"] if host_extra(h["name"])["always_on"]]
    up = sum(1 for h in hosts if h["status"] == "up")
    hu = host_updates()
    return {
        "checks_ok": ok,
        "checks_total": len(checks),
        "hosts_up": up,
        "hosts_total": len(hosts),
        "updates": sum(h["packages"] for h in hu),
        "security": sum(h["security"] for h in hu),
        "sec_overdue": sum(h["sec_overdue"] for h in hu),
        "upd_hosts": sum(1 for h in hu if h["packages"]),
        "reboot_hosts": sum(1 for h in hu if h["reboot"]),
    }


def digest_text() -> str:
    s = summary()
    att = attention()
    head = (
        "☀️ " + SITE_NAME + " " + now().strftime("%H:%M") + " – " + (tr("alles grün") if not att else tr("{n} Punkt(e) offen", n=len(att)))
    )
    lines = [head]
    for a in att[:8]:
        lines.append(("🔴 " if a["level"] == "bad" else "🟡 ") + f"{a['title']}: {a['detail']}")
    lines.append(f"Jobs {s['checks_ok']}/{s['checks_total']} · Hosts {s['hosts_up']}/{s['hosts_total']}")
    for h in state["hosts"]:  # Hosts mit Zeitfenster (always_on: false): wann zuletzt gesehen
        if not host_extra(h["name"])["always_on"] and h.get("updated"):
            lines.append(tr("{name} zuletzt gesehen: {t}", name=h["name"], t=h["updated"][:16].replace("T", " ")))
    lines.append(
        tr("Updates: {h} Hosts · {p} Pakete · Security {s}", h=s["upd_hosts"], p=s["updates"], s=s["security"])
        + (tr(" (überfällig {n})", n=s["sec_overdue"]) if s["sec_overdue"] else "")
        + (tr(" · Neustart nötig: {n}", n=s["reboot_hosts"]) if s["reboot_hosts"] else "")
    )
    if state["errors"]:
        lines.append("⚠️ " + tr("Quellen: {q}", q=", ".join(state["errors"])))
    hb = state.get("heartbeat") or {}
    if hb and hb.get("status") == "down":
        lines.append("⚠️ " + tr("Lebenszeichen {n} war ausgefallen", n=HEARTBEAT_NAME))
    return "\n".join(lines)


# ---------------------------------------------------------------- Hintergrund
async def poller() -> None:
    while True:
        try:
            await refresh()
        except Exception:
            log.exception("refresh fehlgeschlagen")
        await asyncio.sleep(POLL)


DIGEST_WINDOW_MIN = 120  # nach der eingestellten Zeit höchstens so lange nachholen (z. B. nach einem Neustart)


def digest_due(t: str, current: dt.datetime, sent_on: str | None) -> bool:
    """Morgenmeldung fällig? Nur im Fenster [t, t + 2 h] und höchstens einmal am Tag –
    sonst käme nach einer Installation am Abend sofort eine "Morgenmeldung"."""
    try:
        hh, mm = (int(x) for x in t.split(":"))
    except ValueError:
        hh, mm = 7, 0
    start = current.replace(hour=hh, minute=mm, second=0, microsecond=0)
    return sent_on != current.date().isoformat() and start <= current < start + dt.timedelta(minutes=DIGEST_WINDOW_MIN)


async def digest_loop() -> None:
    while True:
        try:
            t = STORE.get_setting("digest_time") or config._hhmm((cfg.get("settings") or {}).get("digest_time", "07:00"))
            today = now().date().isoformat()
            if digest_due(t, now(), digest_state.get("sent")) and state["generated"]:
                if await send_signal(digest_text()):
                    digest_state["sent"] = today
                    _save("digest.json", digest_state)
        except Exception:
            log.exception("Morgenmeldung fehlgeschlagen")
        await asyncio.sleep(30)


@contextlib.asynccontextmanager
async def lifespan(_app: FastAPI):
    STORE.ensure_setup_code()
    tasks = [asyncio.create_task(poller()), asyncio.create_task(digest_loop())]
    yield
    for t in tasks:
        t.cancel()


SESSION_COOKIE = "qb_session"
# Ohne Anmeldung erreichbar: Gesundheitsprüfung, Ingest/Installer (eigener Token), Anmeldeseiten und statische Dateien
PUBLIC_PATHS = ("/healthz", "/login", "/setup", "/sw.js", "/manifest.webmanifest", "/api/auth/state", "/api/auth/login", "/api/auth/setup")
PUBLIC_PREFIXES = ("/api/ingest/", "/api/install/", "/static/")
UNSAFE = ("POST", "PUT", "PATCH", "DELETE")


def _is_public(path: str) -> bool:
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def _route_guard(request: Request) -> None:
    """Zweite Verteidigungslinie je Route: entscheidet nach der Route, die der Router tatsächlich gewählt hat –
    unabhängig davon, was die Middleware gesehen hat. Nicht öffentliche Routen brauchen einen angemeldeten Benutzer."""
    route = request.scope.get("route")
    if _is_public(getattr(route, "path", "")):
        return
    if not getattr(request.state, "user", None):
        raise HTTPException(401, "Anmeldung erforderlich")


app = FastAPI(title="Status", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan, dependencies=[Depends(_route_guard)])


# ---------------------------------------------------------------- Zugriffsschutz
_jwk = jwt.PyJWKClient(f"https://{ACCESS_TEAM}.cloudflareaccess.com/cdn-cgi/access/certs") if ACCESS_TEAM else None
# Zusätzliche Adressen, unter denen die Oberfläche aufgerufen wird (nur nötig, wenn ein Proxy den Host-Header ändert)
PUBLIC_ORIGIN_HOSTS = {urlparse(o.strip()).netloc for o in E("PUBLIC_ORIGINS", "").split(",") if o.strip()}


def _access_user(request: Request) -> dict | None:
    """Cloudflare Access als vorgeschaltete Anmeldung (optional): gültiges JWT = Admin."""
    token = request.headers.get("cf-access-jwt-assertion") or request.cookies.get("CF_Authorization")
    if not (_jwk and ACCESS_AUD and token):
        return None
    try:
        key = _jwk.get_signing_key_from_jwt(token).key
        claims = jwt.decode(token, key, algorithms=["RS256"], audience=ACCESS_AUD, issuer=f"https://{ACCESS_TEAM}.cloudflareaccess.com")
        return {"id": 0, "email": claims.get("email", "access"), "name": "", "role": "admin", "via": "access"}
    except Exception as exc:
        log.warning("Access-JWT abgelehnt: %s", exc)
        return None


def _same_origin(request: Request) -> bool:
    """Schutz gegen fremde Seiten, die im Namen des Browsers schreiben (CSRF).

    Sec-Fetch-Site setzt der Browser selbst (fremde Seiten können es nicht fälschen) – das gilt zuerst und funktioniert
    auch hinter Proxys, die den Host-Header ändern. Ältere Browser: Origin/Referer gegen Host (bzw. X-Forwarded-Host
    eines vertrauten Proxys oder PUBLIC_ORIGINS). Ganz ohne Herkunftsangabe: ablehnen."""
    sfs = request.headers.get("sec-fetch-site")
    if sfs:
        return sfs in ("same-origin", "none")
    origin = request.headers.get("origin") or request.headers.get("referer")
    if not origin:
        return False
    allowed = {request.headers.get("host", ""), request.scope.get("qb_forwarded_host", "")} | PUBLIC_ORIGIN_HOSTS
    return urlparse(origin).netloc in allowed - {""}


def _has_body(request: Request) -> bool:
    return request.headers.get("content-length", "0") not in ("", "0") or "transfer-encoding" in request.headers


WARNINGS: dict = {}  # einmalige Betriebshinweise für System → Übersicht (z. B. nicht eingetragener Proxy)


@app.middleware("http")
async def access_guard(request: Request, call_next):
    # Nicht request.url.path: die URL setzt Starlette aus dem Host-Header zusammen – ein Header wie
    # "Host: x/healthz?" ließe den Wächter einen öffentlichen Pfad sehen. scope["path"] ist, was der Router bedient.
    path = request.scope["path"]
    request.state.user = None
    if request.scope.get("qb_untrusted_forward") and not WARNINGS.get("untrusted_proxy"):
        WARNINGS["untrusted_proxy"] = request.scope.get("qb_peer") or "?"
        log.warning(
            "Anfrage über einen Proxy (%s), der nicht in TRUSTED_PROXIES steht: X-Forwarded-* werden ignoriert, die "
            "Verbindung gilt als http (Cookies ohne Secure, Adressen mit http://). Proxy eintragen – Doku: Netzwerk.",
            WARNINGS["untrusted_proxy"],
        )
    if _is_public(path):
        return await call_next(request)
    if ALLOW_NO_AUTH:
        # Ohne Anmeldung (nur für Tests/Demo): Browser-Anfragen fremder Seiten trotzdem abweisen – sonst könnte jede
        # Webseite über den Browser eines Nutzers im LAN Admin-Aktionen auslösen. Skripte ohne Origin dürfen.
        if (
            request.method in UNSAFE
            and (request.headers.get("origin") or request.headers.get("sec-fetch-site"))
            and not _same_origin(request)
        ):
            return JSONResponse({"detail": "Anfrage von fremder Seite abgelehnt"}, status_code=403)
        request.state.user = {"id": 0, "email": "ohne-anmeldung", "name": "", "role": "admin", "via": "none"}
        return await call_next(request)
    user = _access_user(request)
    bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if user is None and bearer.startswith("qb_"):
        user = STORE.token_user(bearer)  # API-Token: kein Cookie, daher keine CSRF-Prüfung nötig
        if user is None:
            return JSONResponse({"detail": "API-Token ungültig oder widerrufen"}, status_code=401)
    if user is None:
        user = STORE.session_user(request.cookies.get(SESSION_COOKIE))
    if user is None:
        if request.method == "GET" and not path.startswith("/api/"):
            return RedirectResponse("/setup" if not STORE.has_users() else "/login", status_code=303)
        return JSONResponse({"detail": "Anmeldung erforderlich", "setup": not STORE.has_users()}, status_code=401)
    # Sitzungs-Cookie und Cloudflare Access schickt der Browser von selbst mit – auch für fremde Seiten. Deshalb für
    # schreibende Anfragen Herkunft prüfen und nur JSON annehmen (ein Formular einer fremden Seite kann kein JSON senden).
    if user.get("via") != "token" and request.method in UNSAFE:
        if not _same_origin(request):
            log.warning(
                "Schreibende Anfrage abgelehnt (Herkunft): %s %s, Origin=%s, Host=%s, Sec-Fetch-Site=%s",
                request.method,
                path,
                request.headers.get("origin", "-"),
                request.headers.get("host", "-"),
                request.headers.get("sec-fetch-site", "-"),
            )
            return JSONResponse({"detail": "Anfrage von fremder Seite abgelehnt"}, status_code=403)
        if _has_body(request) and not request.headers.get("content-type", "").startswith("application/json"):
            return JSONResponse({"detail": "Nur JSON erlaubt"}, status_code=415)
    request.state.user = user
    return await call_next(request)


# Vor allem anderen (äußerste Schicht): vertraute Proxys, Größenlimit, Sicherheits-Header
app.add_middleware(
    security.ShieldMiddleware,
    trusted=security.TrustedProxies(E("TRUSTED_PROXIES", "cloudflared")),
    cloudflare=security.TrustedProxies(E("CLOUDFLARE_PROXIES", "cloudflared")),
)
security.install_log_filter()


class UserError(HTTPException):
    """Fehler mit Text-Vorlage und Werten: `detail` bleibt ein fertiger (deutscher) Text für Skripte, dazu kommen
    `msg` (Vorlage) und `args`, damit die Oberfläche auch zusammengesetzte Texte übersetzen kann."""

    def __init__(self, status_code: int, template: str, /, **args):
        super().__init__(status_code, template.format(**args))
        self.msg, self.msg_args = template, {k: str(v) for k, v in args.items()}


@app.exception_handler(UserError)
async def _user_error(request: Request, exc: UserError):
    return JSONResponse({"detail": exc.detail, "msg": exc.msg, "args": exc.msg_args}, status_code=exc.status_code)


def require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Nur für Admins")
    return user


def legacy_ingest_allowed() -> bool:
    """Gemeinsames INGEST_TOKEN (alle Hosts) – gilt, bis der Admin es unter System abschaltet."""
    return bool(STORE.get_setting("legacy_ingest_token", True))


legacy_use: dict = _load("legacy_use.json", {})  # "<ip> <pfad>" -> letzte Nutzung des gemeinsamen Tokens


def _note_legacy(request: Request) -> None:
    peer = request.scope.get("qb_peer") or (request.client.host if request.client else "?")
    path = security.mask_tokens(request.url.path)
    key = f"{peer} {path}"
    t = now().isoformat(timespec="seconds")
    if (legacy_use.get(key) or "")[:13] != t[:13]:  # höchstens einmal pro Stunde speichern
        legacy_use[key] = t
        for k in sorted(legacy_use, key=legacy_use.get)[:-100]:
            legacy_use.pop(k)
        _save("legacy_use.json", legacy_use)


def _identity(*given: str) -> dict | None:
    """Wer meldet? {"kind": "host", "host": name} | {"kind": "installer"} | {"kind": "legacy"} oder None.
    Das gemeinsame Token wird zeitkonstant verglichen; Host- und Installer-Tokens nur als Hash gespeichert."""
    for g in given:
        if not g:
            continue
        host = STORE.host_for_token(g)
        if host:
            return {"kind": "host", "host": host}
        if STORE.installer_ok(g):
            return {"kind": "installer"}
    if INGEST_TOKEN and legacy_ingest_allowed():
        want = INGEST_TOKEN.encode()
        if any([hmac.compare_digest(g.encode(), want) for g in given if g]):
            return {"kind": "legacy"}
    return None


def require_token(request: Request, *, installer: bool = False) -> dict:
    """Ingest-Zugang: Token per Bearer-Header, X-Token-Header oder ?token= (für Absender ohne eigene Header, z. B. Bridges).
    Installer-Tokens gelten nur dort, wo `installer=True` (Host-Installer und Anmeldung)."""
    candidates = (
        request.headers.get("authorization", "").removeprefix("Bearer ").strip(),
        request.headers.get("x-token", ""),
        request.query_params.get("token", ""),
    )
    who = _identity(*candidates)
    if not who or (who["kind"] == "installer" and not installer):
        raise HTTPException(401, "Token fehlt oder falsch")
    if who["kind"] == "legacy":
        _note_legacy(request)
    return who


def _token_ok(*given: str) -> bool:
    """Für den Token im Pfad (Bridge): gemeinsames Token oder Host-Token."""
    who = _identity(*given)
    return bool(who) and who["kind"] != "installer"


def _resolve(host: str) -> set[str]:
    try:
        return {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        return set()


def require_beszel(request: Request) -> None:
    """Beszel-Webhook: nur vom Beszel-Container (per Namensauflösung), aus INTERNAL_NETS oder mit Ingest-Token.
    Ein pauschales "privates Netz" reicht nicht – sonst dürfte jedes Gerät im LAN Meldungen einspielen.
    Geprüft wird die echte Gegenstelle der Verbindung, nie eine weitergeleitete Adresse (X-Forwarded-For)."""
    client = request.scope.get("qb_peer") or (request.client.host if request.client else "")
    if client and client in _resolve(BESZEL_HOST):
        return
    try:
        if any(ipaddress.ip_address(client) in n for n in INTERNAL_NETS):
            return
    except ValueError:
        pass
    require_token(request)


# ---------------------------------------------------------------- API
@app.get("/healthz")
async def healthz():
    age = None
    if state["generated"]:
        age = (now() - dt.datetime.fromisoformat(state["generated"])).total_seconds()
    ok = age is not None and age < POLL * 5
    return JSONResponse({"ok": ok, "age": age, "errors": list(state["errors"])}, status_code=200 if ok else 503)


_PRIV = re.compile(r"^(10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|127\.)|\.(lokal|local|lan|fritz\.box|home\.arpa)$|\.lokal\.|^[^.]+$")


def host_settings() -> dict:
    """In der Oberfläche gesetzte Host-Einstellungen {name: {always_on, links: [{label, url}]}}."""
    return STORE.get_setting("hosts", {}) or {}


def host_extra(beszel_name: str, gui: dict | None = None) -> dict:
    """always_on und Weblinks: Oberfläche (settings.hosts) vor checks.yaml (hosts.<name>.url: str oder {Label: URL})."""
    conf = next((v for v in (cfg.get("hosts") or {}).values() if v.get("beszel") == beszel_name), {})
    g = (host_settings() if gui is None else gui).get(beszel_name, {})
    url = conf.get("url") or {}
    if isinstance(url, str):
        url = {"Weboberfläche": url}
    if not isinstance(url, dict):
        url = {}
    if "links" in g:
        url = {li["label"]: li["url"] for li in g["links"]}
    links = []
    for label, u in url.items():
        if not _URL.fullmatch(str(u)):  # nur http(s) – auch aus checks.yaml
            continue
        hostpart = re.sub(r"^\w+://", "", str(u)).split("/")[0].split(":")[0]
        links.append({"label": str(label), "url": str(u), "vpn": bool(_PRIV.search(hostpart))})
    return {"always_on": g.get("always_on", conf.get("always_on", True)), "links": links, "custom": bool(g)}


@app.get("/api/state")
async def api_state(fresh: int = 0):
    """fresh=1 (Knopf ↻): Daten sofort neu holen statt bis zur nächsten Abfrage zu warten – höchstens alle 10 s."""
    if fresh and not DEMO:
        if time.monotonic() - _last_refresh >= 10:
            await refresh()
        elif _refresh_lock.locked():
            await refresh()  # wartet auf den laufenden Abruf
    hs = host_settings()
    return {
        "generated": state["generated"],
        "summary": summary(),
        "attention": attention(),
        "checks": state["checks"],
        "hosts": [{**h, **host_extra(h["name"], hs)} for h in state["hosts"]],
        "pbs": state["pbs"],
        "updates": sorted(updates.values(), key=lambda u: (u["kind"], u["host"])),
        "host_updates": host_updates(),
        "events": events[:40],
        "errors": state["errors"],
        "links": {"hc": HC_PUBLIC, "beszel": BESZEL_PUBLIC},
    }


HOST_FILES = (
    "hc",
    "updates-report",
    "updates-report.service",
    "updates-report.timer",
    "unattended-security.sh",
    "install-host.sh",
    "synology-setup.sh",
    "dsm-report",
)


def _sh_quote(v: str) -> str:
    return "'" + v.replace("'", "'\\''") + "'"


@app.get("/api/install/host.sh")
async def install_host_script(request: Request):
    """Fertig ausgefüllter Host-Installer – ein Befehl pro Host:
        curl -fsSL -H "Authorization: Bearer <INGEST_TOKEN>" http://<server>:8088/api/install/host.sh | bash
    Als root läuft es direkt, als normaler Benutzer holt es sich die Rechte per sudo.
    Der Token steht im Header, nicht in der URL (sonst landet er im Zugriffslog).
    Optional vor `bash` (z. B. `| QB_HOST=nas bash`): QB_HOST=name, QB_AGENT_MODE=docker|binary, QB_SECURITY_UPDATES=0."""
    who = require_token(request, installer=True)
    if who["kind"] == "host":  # ein Host-Token darf keine Zugangsdaten anderer Hosts laden
        raise HTTPException(403, "Mit einem Host-Token gibt es keinen Installer – Befehl aus „Host hinzufügen“ verwenden")
    if not (CREDS.hc_ping_key and CREDS.agent_token and CREDS.hub_key):
        raise HTTPException(503, "Healthchecks/Beszel noch nicht eingerichtet")
    base = str(request.base_url).rstrip("/")
    presented = request.headers.get("authorization", "").removeprefix("Bearer ").strip() or request.headers.get("x-token", "")
    values = {
        "QB_PING_BASE": E("HC_PING_ENDPOINT", "").rstrip("/") or f"{urlparse(base).scheme}://{urlparse(base).hostname}:8000/ping",
        "QB_PING_KEY": CREDS.hc_ping_key,
        "QB_INGEST_URL": f"{base}/api/ingest/updates",
        # Der Host holt sich bei der Installation sein eigenes Token (QB_REGISTER_URL). Das gemeinsame Token steht
        # nur noch als Rückfall drin, wenn der Befehl damit aufgerufen wurde.
        "QB_INGEST_TOKEN": INGEST_TOKEN if who["kind"] == "legacy" else "",
        "QB_REGISTER_URL": f"{base}/api/install/register",
        "QB_INSTALL_TOKEN": presented,
        "QB_HUB_URL": BESZEL_PUBLIC or f"{urlparse(base).scheme}://{urlparse(base).hostname}:8090",
        "QB_AGENT_KEY": CREDS.hub_key,
        "QB_AGENT_TOKEN": CREDS.agent_token,
    }
    lines = [
        "#!/usr/bin/env bash",
        f"# QuietBoard – Host-Installer, erzeugt {now().isoformat(timespec='seconds')} von {base}",
        "# Enthält Zugangsdaten für diesen Server: nicht weitergeben, nicht speichern.",
        "set -euo pipefail",
        # Vorgabe, außer der Aufrufer setzt den Wert selbst (z. B. sudo QB_HUB_URL=… bash)
        *(f"{k}=${{{k}:-{_sh_quote(v)}}}; export {k}" for k, v in values.items()),
        "QB_FILES=$(mktemp -d); trap 'rm -rf \"$QB_FILES\"' EXIT",
    ]
    for name in HOST_FILES:
        data = base64.b64encode((HOSTS_DIR / name).read_bytes()).decode()
        lines += [f"base64 -d > \"$QB_FILES/{name}\" <<'QB_EOF'", *(data[i : i + 76] for i in range(0, len(data), 76)), "QB_EOF"]
    lines += [
        'chmod +x "$QB_FILES"/*',
        "# Als root direkt; sonst Rechte per sudo holen (QB_*-Werte als Datei mitgeben, sudo setzt die Umgebung zurück)",
        'if [ "$(id -u)" = 0 ]; then',
        '  bash "$QB_FILES/install-host.sh"',
        "else",
        '  command -v sudo >/dev/null || { echo "QuietBoard: bitte als root ausführen (sudo fehlt)" >&2; exit 1; }',
        # Werte als Datei (nur für diesen Benutzer lesbar), nicht als Argumente – sonst in der Prozessliste sichtbar
        '  (umask 077; for v in ${!QB_@}; do printf "%s=%q\\n" "$v" "${!v}"; done > "$QB_FILES/qb.env")',
        '  sudo bash "$QB_FILES/install-host.sh" --env "$QB_FILES/qb.env"',
        "fi",
        "",
    ]
    return Response("\n".join(lines), media_type="text/x-shellscript", headers={"Cache-Control": "no-store"})


@app.post("/api/install/register")
async def install_register(request: Request):
    """Host anmelden: gibt ein eigenes Melde-Token für genau diesen Host zurück (ein früheres wird ungültig).
    Mit Installer-Token oder – solange erlaubt – dem gemeinsamen Token. Body: {"host": "<name>"}."""
    who = require_token(request, installer=True)
    if who["kind"] == "host":
        raise HTTPException(403, "Mit einem Host-Token kann kein Host angemeldet werden")
    b = await _body(request)
    host = b.get("host")
    if not isinstance(host, str) or not HOST_RE.fullmatch(host):
        raise HTTPException(400, "host fehlt oder ungültig")
    token = STORE.create_host_token(host)
    log.info("Host %s angemeldet (eigenes Melde-Token, über %s)", host, who["kind"])
    return {"host": host, "token": token}


@app.get("/api/host-tokens")
async def host_tokens_list(request: Request):
    require_admin(request)
    return {"tokens": STORE.list_host_tokens(), "legacy_allowed": legacy_ingest_allowed(), "legacy_use": legacy_use}


@app.delete("/api/host-tokens/{host}")
async def host_tokens_delete(host: str, request: Request):
    require_admin(request)
    if not STORE.delete_host_token(host):
        raise HTTPException(404, "Kein Token für diesen Host")
    return {"ok": True}


@app.post("/api/hosts/installer-token")
async def install_token(request: Request):
    """Admin: kurzlebiges Installer-Token (1 h) und den fertigen Befehl für „Host hinzufügen“."""
    me = require_admin(request)
    token, expires = STORE.create_installer_token(str(me.get("email") or me.get("id")))
    base = str(request.base_url).rstrip("/")
    cmd = f'curl -fsSL -H "Authorization: Bearer {token}" {base}/api/install/host.sh | bash'
    return {"command": cmd, "expires": dt.datetime.fromtimestamp(expires, TZ).isoformat(timespec="seconds")}


@app.get("/api/agent")
async def api_agent(request: Request):
    require_admin(request)
    """Zugangsdaten für neue Beszel-Agents (Grundlage für den Kopier-Block "Host hinzufügen")."""
    if not (CREDS.agent_token and CREDS.hub_key):
        raise HTTPException(503, CREDS.errors.get("beszel", "Beszel noch nicht eingerichtet"))
    return {"hub_url": BESZEL_PUBLIC or BESZEL_URL, "key": CREDS.hub_key, "token": CREDS.agent_token}


@app.get("/api/check/{uuid}/log")
async def api_check_log(uuid: str):
    if not re.fullmatch(r"[0-9a-f-]{36}", uuid):
        raise HTTPException(400)
    async with httpx.AsyncClient(timeout=15, headers={"X-Api-Key": CREDS.hc_api_key}, limits=NO_KEEPALIVE) as cli:
        r = await cli.get(f"{HC_URL}/api/v3/checks/{uuid}/pings/")
        r.raise_for_status()
        pings = r.json().get("pings", [])
        if not pings:
            return {"text": "Noch keine Pings.", "date": None, "type": None}
        p = pings[0]
        text = ""
        if p.get("body_url"):
            path = urlparse(p["body_url"]).path  # absolute URL zeigt auf SITE_ROOT, intern abrufen
            b = await cli.get(f"{HC_URL}{path}")
            if b.status_code == 200:
                text = b.text
        return {
            "text": text[-4000:] or "(kein Log übermittelt)",
            "date": p.get("date"),
            "type": p.get("type"),
            "duration": p.get("duration"),
        }


# ---------------------------------------------------------------- Ingest (über WireGuard, Token)
HOST_RE = re.compile(r"[A-Za-z0-9._-]{1,80}")


async def _json_or_text(request: Request) -> dict:
    """Body als Objekt; kein JSON oder kein Objekt (Liste, Text) → {"message": <Text>} statt Fehler 500."""
    try:
        b = await request.json()
    except Exception:
        return {"message": (await request.body()).decode(errors="replace")}
    return b if isinstance(b, dict) else {"message": json.dumps(b, ensure_ascii=False)[:4000]}


@app.post("/api/ingest/updates")
async def ingest_updates(request: Request):
    """Body: {host, kind: apt|dsm|docker|scanner|mailcow, items: [{pkg, from, to, security}], reboot?: bool}"""
    who = require_token(request)
    try:
        b = await request.json()
    except Exception:
        raise HTTPException(400, "Kein gültiges JSON") from None
    if not isinstance(b, dict) or not isinstance(b.get("host"), str) or not HOST_RE.fullmatch(b["host"]):
        raise HTTPException(400, "host fehlt oder ungültig")
    if not isinstance(b.get("items", []), list):
        raise HTTPException(400, "items muss eine Liste sein")
    if who["kind"] == "host" and b["host"] != who["host"]:
        raise UserError(403, "Dieses Token gilt nur für den Host {host}", host=who["host"])
    host, kind = b["host"], str(b.get("kind", "apt"))[:20]
    key = f"{host}|{kind}"
    ts = now().isoformat(timespec="seconds")
    f = flags.setdefault(host, {})
    if b.get("error"):
        # Host konnte den Stand nicht ermitteln (z. B. apt kaputt): letzten Bericht behalten, Fehler anzeigen
        f["report_error"] = {"kind": kind, "msg": str(b["error"])[:200], "ts": ts}
        _save("flags.json", flags)
        return {"ok": True, "count": None}
    if (f.get("report_error") or {}).get("kind") == kind:
        f.pop("report_error")
    f["reported"] = ts
    prev = {i["pkg"]: i.get("since") for i in updates.get(key, {}).get("items", [])}
    items = []
    for i in [i for i in (b.get("items") or []) if isinstance(i, dict)][:500]:
        it = {
            "pkg": str(i.get("pkg", ""))[:120],
            "from": str(i.get("from", ""))[:60],
            "to": str(i.get("to", ""))[:60],
            "security": bool(i.get("security")),
        }
        it["since"] = prev.get(it["pkg"]) or ts  # seit wann offen (für "überfällig")
        items.append(it)
    if items:
        updates[key] = {"host": host, "kind": kind, "checked": ts, "items": items}
    else:
        updates.pop(key, None)
    _save("updates.json", updates)
    if "reboot" in b:
        f.update({"reboot": bool(b["reboot"]), "checked": ts})
    _save("flags.json", flags)
    if not DEMO and host not in {h["name"] for h in state["hosts"]}:
        # Neuer Host (erster Bericht direkt nach der Installation): gleich nachsehen, ob sein Agent schon da ist
        refresh_soon(5)
    return {"ok": True, "count": len(items)}


@app.post("/api/ingest/pve")
async def ingest_pve(request: Request, source: str = "pve", host: str = "pve"):
    """PVE/PBS-Webhook. Query: source=pve|pbs, host=<name aus checks.yaml match.host>."""
    require_token(request)
    try:
        b = await request.json()
    except Exception:
        # Kein gültiges JSON (z. B. bei sehr langem Log gekürzt): Schweregrad und Titel aus dem Text lesen,
        # damit ein Fehler trotzdem als Fehler gilt.
        raw = (await request.body()).decode(errors="replace")
        sev = re.search(r'"severity"\s*:\s*"(\w+)"', raw)
        ttl = re.search(r'"title"\s*:\s*"([^"]{1,200})"', raw)
        b = {"severity": sev.group(1) if sev else "unknown", "title": ttl.group(1) if ttl else "unlesbares Event", "message": raw}
    if not isinstance(b, dict):
        b = {"severity": "unknown", "title": "unlesbares Event", "message": json.dumps(b, ensure_ascii=False)[:4000]}
    severity = str(b.get("severity", "info")).lower()
    fields = b.get("fields") if isinstance(b.get("fields"), dict) else {}
    title, message = str(b.get("title", "")), str(b.get("message", ""))
    hits = config.match_event(cfg, source, host, fields)
    seen = {c["slug"] for c in hits}
    gui_jobs = {"checks": [c for c in state["checks"] if c.get("match")]}  # in der Oberfläche angelegte Jobs
    hits += [c for c in config.match_event(gui_jobs, source, host, fields) if c["slug"] not in seen]
    failed = severity == "error"
    pinged, lost = [], []
    if hits and CREDS.hc_ping_key:
        async with httpx.AsyncClient(timeout=15, limits=NO_KEEPALIVE) as cli:
            for c in hits:
                url = f"{HC_URL}/ping/{CREDS.hc_ping_key}/{c['slug']}" + ("/fail" if failed else "")
                try:
                    r = await cli.post(url, content=f"{title}\n\n{message}"[:90000].encode())
                    # 404 = Check fehlt in Healthchecks, 409 = Slug doppelt: Meldung käme nirgends an
                    (pinged if r.status_code < 300 else lost).append((c, f"HTTP {r.status_code}"))
                except Exception as exc:
                    lost.append((c, type(exc).__name__))
                    log.error("Ping %s fehlgeschlagen: %s", c["slug"], exc)
    if pinged:
        add_event(source, f"{host}: {title}", message, "info")
        refresh_soon(2)  # Job-Status gleich anzeigen
    if lost:
        # Job passt, aber Healthchecks hat die Meldung nicht angenommen: selbst melden, nie still verschlucken
        names = ", ".join(f"{c['name']} ({why})" for c, why in lost)
        prio = "normal" if failed or severity == "unknown" else "info"
        add_event(source, tr("{host}: {title} (Job nicht erreichbar)", host=host, title=title), f"{names}\n\n{message}", prio)
        if failed or severity == "unknown":
            await send_signal(
                f"🔴 {host}: {title}\n" + tr("Healthchecks hat die Meldung nicht angenommen: {names}", names=names),
                dedup_key=f"pve:{host}:{title}",
            )
    if not hits or (not pinged and not lost):
        # Unbekanntes Event: nie still verschlucken, wenn es ein Fehler ist
        prio = "normal" if failed or severity == "unknown" else "info"
        add_event(source, tr("{host}: {title} (ohne Check)", host=host, title=title), message, prio)
        if failed or severity == "unknown":
            await send_signal(
                f"🔴 {host}: {title}\n(" + tr("kein passender Job – unter Jobs anlegen") + ")", dedup_key=f"pve:{host}:{title}"
            )
    return {"ok": True, "matched": [c["name"] for c in hits]}


@app.post("/api/ingest/beszel")
async def ingest_beszel(request: Request):
    """Beszel-Benachrichtigung (Shoutrrr generic, template=json). Nur vom Beszel-Container oder mit Token."""
    require_beszel(request)
    b = await _json_or_text(request)
    title, message = str(b.get("title", "Beszel")), str(b.get("message", ""))
    add_event("beszel", title, message, "normal")
    # Schlüssel ohne Zustandswort: „web01 is down“ und „web01 is up“ gehören zusammen; gleicher Zustand innerhalb
    # von 30 min wird unterdrückt, ein Wechsel kommt immer durch (auch down → up → down).
    subject = re.sub(r"\b(is\s+)?(down|up)\b|[^\w .:/-]", "", title, flags=re.I).strip() or title
    await send_signal(f"🖥️ {title}\n{message}", dedup_key=f"beszel:{subject}", fp=title)
    return {"ok": True}


ERROR_WORDS = re.compile(r"fehl|error|fail|❌|🔴|critical|kritisch|abgebrochen|rollback", re.I)


@app.post("/api/ingest/notify")
async def ingest_notify(request: Request):
    """Generische Meldung. Body: {source, title, message, prio: kritisch|normal|info}
    Versteht auch den signal-api-Body {"message": ...} (für bestehende Bridges).
    Query: ?source=…&prio=… überschreiben; ohne prio: Fehlerwörter → normal, sonst info."""
    require_token(request)
    b = await _json_or_text(request)
    message = str(b.get("message", ""))
    title = str(b.get("title") or (message.strip().splitlines() or ["Meldung"])[0])[:200]
    prio = (
        request.query_params.get("prio") or str(b.get("prio") or "") or ("normal" if ERROR_WORDS.search(title + " " + message) else "info")
    )
    source = request.query_params.get("source") or str(b.get("source", "notify"))
    add_event(source, title, message, prio)
    if prio in ("kritisch", "normal"):
        # gleicher Titel von verschiedenen Hosts (z. B. „Backup fehlgeschlagen“) unterscheidet sich im Text
        await send_signal(
            f"{'🔴' if prio == 'kritisch' else '🟡'} {title}\n{message}"[:2000], dedup_key=f"n:{source}:{title}", fp=message[:1000]
        )
    return {"ok": True}


@app.post("/api/ingest/signal/{token}")
@app.post("/api/ingest/signal/{token}/v2/send")
async def ingest_signal_compat(token: str, request: Request):
    """Drop-in für Absender, die signal-api erwarten (z. B. dockhand-signal-bridge).
    SIGNAL_API_URL=http://<server>:8088/api/ingest/signal/<INGEST_TOKEN>  (Bridge hängt /v2/send an)."""
    if not _token_ok(token):
        raise HTTPException(401, "Token fehlt oder falsch")
    b = await _json_or_text(request)
    message = str(b.get("message", ""))
    title = (message.strip().splitlines() or ["Meldung"])[0][:200]
    prio = request.query_params.get("prio") or ("normal" if ERROR_WORDS.search(message) else "info")
    source = request.query_params.get("source", "dockhand")
    add_event(source, title, message, prio)
    if prio in ("kritisch", "normal"):
        await send_signal(f"{'🔴' if prio == 'kritisch' else '🟡'} {message}"[:2000], dedup_key=f"n:{source}:{title}", fp=message[:1000])
    return {"timestamp": str(int(time.time() * 1000))}


@app.get("/api/push/key")
async def push_key():
    if not VAPID:
        raise HTTPException(503, "VAPID_PRIVATE_KEY fehlt")
    return {"key": VAPID.public_b64}


PUSH_PER_USER = 10


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    b = await _body(request)
    sub = {"endpoint": b.get("endpoint"), "keys": b.get("keys") if isinstance(b.get("keys"), dict) else {}}
    if not isinstance(sub["endpoint"], str) or not push.valid_subscription(sub):
        raise HTTPException(400, "ungültige Push-Registrierung")
    user = getattr(request.state, "user", None) or {}
    owner = str(user.get("email") or user.get("id") or "")
    known = push_subs.get(sub["endpoint"])
    if not known and owner and sum(1 for s in push_subs.values() if s.get("owner") == owner) >= PUSH_PER_USER:
        raise HTTPException(400, "Höchstens 10 Geräte pro Konto – Mitteilungen auf einem alten Gerät ausschalten")
    push_subs[sub["endpoint"]] = {
        **sub,
        "since": (known or {}).get("since") or now().isoformat(timespec="seconds"),
        "ua": request.headers.get("user-agent", "")[:120],
        "owner": owner,
    }
    _save("push.json", push_subs)
    if not known:
        log.info("Neues Push-Gerät registriert (%d gesamt)", len(push_subs))
    return {"ok": True, "count": len(push_subs)}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    b = await _body(request)
    push_subs.pop(str(b.get("endpoint")), None)
    _save("push.json", push_subs)
    return {"ok": True, "count": len(push_subs)}


@app.post("/api/push/test")
async def push_test(request: Request):
    require_admin(request)
    return {"sent": await push_all("🔔 Test", tr("Mitteilungen von QuietBoard funktionieren."), "/", "test"), "devices": len(push_subs)}


@app.post("/api/digest/test")
async def digest_test(request: Request):
    require_admin(request)
    """Morgenmeldung sofort senden (geschützt durch Access)."""
    return {"sent": await send_signal(digest_text()), "text": digest_text()}


# ---------------------------------------------------------------- Konten
def _cookie(resp: Response, request: Request, token: str) -> None:
    resp.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=auth.SESSION_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        path="/",
    )


def _public_user(u: dict | None) -> dict | None:
    return {k: u.get(k) for k in ("id", "email", "name", "role", "via")} if u else None


# Passwort-Hashing (scrypt, 16 MB je Lauf) nicht in der Event-Loop und höchstens zweimal gleichzeitig –
# sonst legen ein paar Login-Versuche die ganze App lahm bzw. sprengen mem_limit.
_SCRYPT_SLOTS = asyncio.Semaphore(2)


async def _hashing(fn, *args):
    async with _SCRYPT_SLOTS:
        return await asyncio.to_thread(fn, *args)


async def _body(request: Request) -> dict:
    try:
        b = await request.json()
        return b if isinstance(b, dict) else {}
    except Exception:
        return {}


@app.get("/api/auth/state")
async def auth_state(request: Request):
    user = None
    if ALLOW_NO_AUTH:
        user = {"id": 0, "email": "ohne-anmeldung", "role": "admin", "via": "none"}
    else:
        user = _access_user(request) or STORE.session_user(request.cookies.get(SESSION_COOKIE))
    return {"setup_needed": not STORE.has_users(), "user": _public_user(user), "site": SITE_NAME}


@app.post("/api/auth/setup")
async def auth_setup(request: Request):
    b = await _body(request)
    try:
        name = b.get("name", "")
        user = await _hashing(
            STORE.complete_setup, b.get("code", ""), b.get("email", ""), b.get("password", ""), name if isinstance(name, str) else ""
        )
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None
    if b.get("email") and not STORE.get_setting("mail_to"):
        STORE.set_setting("mail_to", [user["email"]])  # Alarm-Mails zunächst an den Admin
    resp = JSONResponse({"ok": True, "user": _public_user(user)})
    _cookie(resp, request, STORE.create_session(user["id"], request.headers.get("user-agent", "")))
    return resp


@app.post("/api/auth/login")
async def auth_login(request: Request):
    b = await _body(request)
    try:
        user = await _hashing(STORE.login, b.get("email", ""), b.get("password", ""), request.client.host if request.client else "")
    except auth.AuthError as exc:
        raise HTTPException(401, str(exc)) from None
    resp = JSONResponse({"ok": True, "user": _public_user(user)})
    _cookie(resp, request, STORE.create_session(user["id"], request.headers.get("user-agent", "")))
    return resp


@app.post("/api/auth/logout")
async def auth_logout(request: Request):
    STORE.end_session(request.cookies.get(SESSION_COOKIE))
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    return resp


@app.post("/api/auth/password")
async def auth_password(request: Request):
    user = request.state.user
    if not user.get("id"):
        raise HTTPException(400, "Dieses Konto wird außerhalb von QuietBoard verwaltet")
    b = await _body(request)
    try:
        await _hashing(STORE.change_password, user["id"], b.get("old", ""), b.get("new", ""), request.cookies.get(SESSION_COOKIE))
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True}


@app.get("/api/users")
async def users_list(request: Request):
    require_admin(request)
    return {"users": STORE.list_users()}


@app.post("/api/users")
async def users_create(request: Request):
    require_admin(request)
    b = await _body(request)
    try:
        name = b.get("name", "")
        user = await _hashing(
            STORE.create_user, b.get("email", ""), b.get("password", ""), b.get("role", "viewer"), name if isinstance(name, str) else ""
        )
        return {"user": user}
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None


@app.patch("/api/users/{uid}")
async def users_update(uid: int, request: Request):
    me = require_admin(request)
    b = await _body(request)
    if not STORE.get_user(uid):
        raise HTTPException(404, "Benutzer nicht gefunden")
    try:
        if "password" in b:
            await _hashing(STORE.set_password, uid, b["password"])
        if "role" in b:
            STORE.set_role(uid, b["role"], me.get("id", 0))
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"user": STORE.get_user(uid)}


@app.delete("/api/users/{uid}")
async def users_delete(uid: int, request: Request):
    me = require_admin(request)
    user = STORE.get_user(uid)
    if not user:
        raise HTTPException(404, "Benutzer nicht gefunden")
    try:
        STORE.delete_user(uid, me.get("id", 0))
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None
    # Geräte des gelöschten Kontos bekommen keine Alarme mehr
    gone = [e for e, s in push_subs.items() if s.get("owner") in (user["email"], str(uid))]
    for e in gone:
        push_subs.pop(e)
    if gone:
        _save("push.json", push_subs)
    return {"ok": True}


# ---------------------------------------------------------------- Einstellungen, Kanäle, System
def _settings() -> dict:
    return {
        "mail_to": mail_recipients(),
        "digest_time": STORE.get_setting("digest_time") or config._hhmm((cfg.get("settings") or {}).get("digest_time", "07:00")),
        "channels": {"mail": bool(SMTP["host"]), "push": bool(VAPID), "signal": bool(SIGNAL_NUMBER and SIGNAL_RECIPIENT)},
        "language": i18n.lang(),
        "job_alerts": job_alerts_mode(),
        "legacy_ingest_token": legacy_ingest_allowed(),
        "hc_channels_backup": (DATA / HC_CHANNELS_BACKUP).exists(),
    }


@app.get("/api/tokens")
async def tokens_list(request: Request):
    user = request.state.user
    if user.get("via") in ("none", "access") or not user.get("id"):
        return {"tokens": [], "available": False}
    mine = STORE.list_api_tokens(user["id"])
    others = [t for t in STORE.list_api_tokens() if t["id"] not in {m["id"] for m in mine}] if user["role"] == "admin" else []
    return {"tokens": mine, "others": others, "available": True}


@app.post("/api/tokens")
async def tokens_create(request: Request):
    user = request.state.user
    if user.get("via") == "token":
        raise HTTPException(403, "Tokens nur in der Oberfläche anlegen")
    if not user.get("id"):
        raise HTTPException(400, "API-Tokens gibt es nur mit lokalen Konten")
    try:
        token, info = STORE.create_api_token(user["id"], (await _body(request)).get("name", ""))
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None
    log.info("API-Token angelegt: %s (%s)", info["name"], user["email"])
    return {"token": token, "info": info}


@app.delete("/api/tokens/{tid}")
async def tokens_delete(tid: int, request: Request):
    user = request.state.user
    try:
        STORE.delete_api_token(tid, user.get("id", 0), user.get("role") == "admin")
    except auth.AuthError as exc:
        raise HTTPException(404, str(exc)) from None
    return {"ok": True}


@app.get("/api/settings")
async def settings_get():
    return _settings()


@app.put("/api/settings")
async def settings_put(request: Request):
    require_admin(request)
    b = await _body(request)
    if "mail_to" in b:
        raw = b["mail_to"] if isinstance(b["mail_to"], list) else str(b["mail_to"]).replace(";", ",").split(",")
        try:
            STORE.set_setting("mail_to", sorted({auth.normalize_email(m) for m in raw if str(m).strip()}))
        except auth.AuthError as exc:
            raise HTTPException(400, str(exc)) from None
    if "digest_time" in b:
        t = str(b["digest_time"]).strip()
        if not re.fullmatch(r"([01]\d|2[0-3]):[0-5]\d", t):
            raise HTTPException(400, "Uhrzeit im Format HH:MM")
        STORE.set_setting("digest_time", t)
    if "language" in b:
        if b["language"] not in i18n.LANGUAGES:
            raise HTTPException(400, "Sprache: de oder en")
        STORE.set_setting("language", b["language"])
    if "legacy_ingest_token" in b:
        if not isinstance(b["legacy_ingest_token"], bool):
            raise HTTPException(400, "legacy_ingest_token: true oder false")
        STORE.set_setting("legacy_ingest_token", b["legacy_ingest_token"])
    if "job_alerts" in b:
        mode = b["job_alerts"]
        if mode not in ("app", "hc"):
            raise HTTPException(400, "Job-Alarme: app oder hc")
        before = job_alerts_mode()
        STORE.set_setting("job_alerts", mode)  # vorher setzen: die Kanalwahl für "hc" hängt am Modus
        try:
            if mode == "app" and b.get("detach_hc_channels"):
                await _detach_hc_channels()
            if mode == "hc" and b.get("restore_hc_channels"):
                await _restore_hc_channels()
            if mode == "hc" and before == "app":
                # Jobs, die im Modus „QuietBoard“ angelegt wurden, haben keine Integration – sonst blieben sie stumm
                await _fill_empty_channels()
        except httpx.HTTPError as exc:
            STORE.set_setting("job_alerts", before)
            raise _hc_error(exc) from None
        log.info("Job-Alarme über: %s", "QuietBoard" if mode == "app" else "Healthchecks")
    return _settings()


HC_CHANNELS_BACKUP = "hc-channels-backup.json"


async def _detach_hc_channels() -> int:
    """Integrationen von allen Jobs lösen (außer dem Lebenszeichen), damit nichts doppelt kommt. Die Integrationen
    bleiben in Healthchecks; die bisherige Zuordnung wird gesichert (Zurück: _restore_hc_channels)."""
    checks = (await _hc("GET", "/api/v3/checks/")).json()["checks"]
    path = DATA / HC_CHANNELS_BACKUP
    backup = _load(HC_CHANNELS_BACKUP, {}) if path.exists() else {}
    n = 0
    for c in checks:
        uid = c.get("uuid") or c.get("unique_key")
        if "src:app" in c.get("tags", "") or not c.get("channels"):
            continue
        backup.setdefault(uid, c["channels"])  # erste Sicherung gewinnt (mehrfaches Umschalten verliert nichts)
        _save(HC_CHANNELS_BACKUP, backup)  # vor jeder Änderung sichern
        await _hc("POST", f"/api/v3/checks/{uid}", json={"channels": ""})
        n += 1
    log.info("Integrationen von %d Job(s) gelöst, Zuordnung gesichert in %s", n, HC_CHANNELS_BACKUP)
    return n


async def _fill_empty_channels() -> int:
    """Allen Jobs ohne Integration die Standard-Integrationen ihrer Priorität geben (nicht dem Lebenszeichen)."""
    n = 0
    for c in (await _hc("GET", "/api/v3/checks/")).json()["checks"]:
        uid = c.get("uuid") or c.get("unique_key")
        if not uid or "src:app" in (c.get("tags") or "").split() or (c.get("channels") or ""):
            continue
        ids = await _channel_ids(jobs_mod.prio_of(c))
        if ids:
            await _hc("POST", f"/api/v3/checks/{uid}", json={"channels": ids})
            n += 1
    if n:
        log.info("Integrationen für %d Job(s) ohne Kanal gesetzt", n)
    return n


async def _restore_hc_channels() -> int:
    if not (DATA / HC_CHANNELS_BACKUP).exists():
        return 0
    backup = _load(HC_CHANNELS_BACKUP, {})
    known = {c.get("uuid") or c.get("unique_key") for c in (await _hc("GET", "/api/v3/checks/")).json()["checks"]}
    n = 0
    for uid, channels in backup.items():
        if uid in known:
            await _hc("POST", f"/api/v3/checks/{uid}", json={"channels": channels})
            n += 1
    (DATA / HC_CHANNELS_BACKUP).rename(DATA / (HC_CHANNELS_BACKUP + ".restored"))
    log.info("Integrationen von %d Job(s) wiederhergestellt", n)
    return n


@app.post("/api/notify/test")
async def notify_test(request: Request):
    b = await _body(request)
    require_admin(request)
    channel = b.get("channel")
    if channel == "push":
        return {"ok": bool(await push_all("🔔 Test", tr("Mitteilungen von QuietBoard funktionieren."), "/", "test"))}
    if channel == "mail":
        if not SMTP["host"]:
            raise HTTPException(400, "Kein SMTP-Server in .env (SMTP_HOST)")
        if not mail_recipients():
            raise HTTPException(400, "Keine Empfänger eingetragen")
        ok = await send_mail(f"[{SITE_NAME}] Test", tr("Mails von QuietBoard kommen an."))
        if not ok:
            raise HTTPException(502, "Versand fehlgeschlagen – Log der App prüfen")
        return {"ok": True}
    if channel == "signal":
        if not (SIGNAL_NUMBER and SIGNAL_RECIPIENT):
            raise HTTPException(400, "Signal nicht eingerichtet")
        return {"ok": await send_signal("🔔 " + tr("Test von QuietBoard"))}
    raise HTTPException(400, "Unbekannter Kanal")


@app.get("/api/system")
async def system_info():
    hc_err, bz_err = state["errors"].get("healthchecks"), state["errors"].get("beszel")
    return {
        "version": APP_VERSION,
        "generated": state["generated"],
        "engines": {
            "app": {"ok": state["generated"] is not None, "detail": "läuft"},
            "healthchecks": {"ok": not hc_err, "detail": hc_err or f"{len(state['checks'])} Checks", "url": HC_PUBLIC},
            "beszel": {"ok": not bz_err, "detail": bz_err or f"{len(state['hosts'])} Hosts", "url": BESZEL_PUBLIC},
        },
        "push_devices": len(push_subs),
        "warnings": WARNINGS,
        "heartbeat": state.get("heartbeat"),
        "job_alerts": job_alerts_mode(),
        "auth": "access" if _jwk else ("none" if ALLOW_NO_AUTH else "local"),
        "users": len(STORE.list_users()),
    }


_URL = re.compile(r"https?://[^\s\"'<>]{1,300}")


@app.put("/api/hosts/{name}/settings")
async def host_settings_put(name: str, request: Request):
    """Host-Einstellungen aus der Oberfläche: {always_on: bool, links: [{label, url}]}."""
    require_admin(request)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
        raise HTTPException(400, "Ungültiger Hostname")
    b = await _body(request)
    links = []
    for li in (b.get("links") or [])[:10]:
        label, url = str(li.get("label", "")).strip()[:40], str(li.get("url", "")).strip()
        if not url:
            continue
        if not _URL.fullmatch(url):
            raise UserError(400, "Link muss mit http:// oder https:// beginnen: {url}", url=url[:60])
        links.append({"label": label or "Weboberfläche", "url": url})
    hs = host_settings()
    hs[name] = {"always_on": bool(b.get("always_on", True)), "links": links}
    STORE.set_setting("hosts", hs)
    return {"ok": True, "host": host_extra(name)}


@app.delete("/api/hosts/{name}")
async def host_delete(name: str, request: Request):
    """Host vergessen: aus Beszel entfernen, Update-Berichte und Einstellungen löschen. Agent vorher deinstallieren,
    sonst meldet er sich mit dem Universal-Token gleich wieder an."""
    require_admin(request)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
        raise HTTPException(400, "Ungültiger Hostname")
    removed = False
    if not DEMO:
        try:
            removed = await bootstrap.delete_beszel_system(BESZEL_URL, E("ADMIN_EMAIL", ""), E("ADMIN_PASSWORD", ""), name)
        except Exception as exc:
            raise HTTPException(502, f"Beszel: {type(exc).__name__}") from None
    for key in [k for k, u in updates.items() if u["host"] == name]:
        updates.pop(key)
    _save("updates.json", updates)
    if flags.pop(name, None) is not None:
        _save("flags.json", flags)
    hs = host_settings()
    if hs.pop(name, None) is not None:
        STORE.set_setting("hosts", hs)
    await refresh()
    return {"ok": True, "beszel": removed}


@app.get("/api/hosts/install-command")
async def host_install_command(request: Request):
    """Der eine Befehl für "Host hinzufügen" – nur für Admins. Solange das gemeinsame Token erlaubt ist, enthält er
    dieses (gleicher Befehl wie von install.sh); sonst ein Installer-Token, das nach 1 h abläuft.
    In beiden Fällen holt sich der Host bei der Installation sein eigenes Melde-Token."""
    me = require_admin(request)
    if not (CREDS.hc_ping_key and CREDS.agent_token and CREDS.hub_key):
        raise HTTPException(503, "Healthchecks/Beszel noch nicht eingerichtet")
    base = str(request.base_url).rstrip("/")
    expires = None
    if legacy_ingest_allowed() and INGEST_TOKEN:
        token = INGEST_TOKEN
    else:
        token, exp = STORE.create_installer_token(str(me.get("email") or me.get("id")))
        expires = dt.datetime.fromtimestamp(exp, TZ).isoformat(timespec="seconds")
    cmd = f'curl -fsSL -H "Authorization: Bearer {token}" {base}/api/install/host.sh | bash'
    return {"command": cmd, "base": base, "expires": expires}


# ---------------------------------------------------------------- Check-Regeln (pausieren, Priorität)
PRIOS = ("kritisch", "normal", "info")


async def _hc(method: str, path: str, **kw) -> httpx.Response:
    async with httpx.AsyncClient(timeout=15, headers={"X-Api-Key": CREDS.hc_api_key}, limits=NO_KEEPALIVE) as cli:
        r = await cli.request(method, f"{HC_URL}{path}", **kw)
        r.raise_for_status()
        return r


def _hc_error(exc: httpx.HTTPError) -> HTTPException:
    """Fehler von Healthchecks verständlich weitergeben (400 = ungültige Eingabe, z. B. Cron)."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 400:
        try:
            msg = exc.response.json().get("error", "")
        except Exception:
            msg = exc.response.text[:200]
        return UserError(400, "Healthchecks lehnt ab: {msg}", msg=msg)
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return HTTPException(404, "Job nicht gefunden (inzwischen gelöscht?)")
    return UserError(502, "Healthchecks nicht erreichbar: {e}", e=type(exc).__name__)


def job_alerts_mode() -> str:
    """Wer meldet Job-Ausfälle: "app" (QuietBoard über alle eigenen Kanäle) oder "hc" (Integrationen von Healthchecks).
    Solange nichts festgelegt ist: "hc" – so verhielt sich QuietBoard bisher."""
    m = STORE.get_setting("job_alerts")
    return m if m in ("app", "hc") else "hc"


async def _managed_ids(prio: str) -> set[str]:
    """Integrationen, die QuietBoard einer Priorität zuordnet (settings.channels bzw. Standard „E-Mail“).
    Im Modus "app" keine: Dann meldet QuietBoard selbst, Healthchecks soll für Jobs still bleiben."""
    if job_alerts_mode() == "app":
        return set()
    names = ((cfg.get("settings") or {}).get("channels") or jobs_mod.DEFAULT_CHANNELS).get(prio, [])
    if not names:
        return set()
    by_name = {c["name"]: c["id"] for c in (await _hc("GET", "/api/v3/channels/")).json()["channels"]}
    return {by_name[n] for n in names if n in by_name}


async def _channel_ids(prio: str) -> str:
    """Kanäle für einen NEUEN Job."""
    return ",".join(sorted(await _managed_ids(prio)))


async def _channels_after_prio(current: dict, new_prio: str) -> str | None:
    """Kanäle nach einer Prioritätsänderung: nur die von QuietBoard verwalteten austauschen, alle anderen (von Hand
    in Healthchecks zugewiesenen) bleiben. None = nichts ändern."""
    old_prio = jobs_mod.prio_of(current)
    if old_prio == new_prio or job_alerts_mode() == "app":
        return None
    have = {c for c in (current.get("channels") or "").split(",") if c}
    return ",".join(sorted((have - await _managed_ids(old_prio)) | await _managed_ids(new_prio)))


def _slug_taken(slug: str, except_name: str | None = None) -> str | None:
    """Name eines anderen Jobs mit demselben Slug (Healthchecks könnte Pings dann keinem zuordnen: 409)."""
    return next((c["name"] for c in state["checks"] if c.get("slug") == slug and c["name"] != except_name), None)


def _tz() -> str:
    return (cfg.get("settings") or {}).get("tz") or E("TZ", "") or "UTC"


def _uuid_ok(uuid: str) -> None:
    if not re.fullmatch(r"[0-9a-f-]{36}", uuid):
        raise HTTPException(400)


@app.get("/api/jobs/help")
async def jobs_help(request: Request):
    """Alles, was die Oberfläche für Anleitungen braucht (Ping-Adresse, Webhook, bekannte Hosts)."""
    require_admin(request)
    base = str(request.base_url).rstrip("/")
    hosts = sorted({h["name"] for h in state["hosts"]} | {c["host"] for c in state["checks"] if c.get("host")})
    ping = E("HC_PING_ENDPOINT", "").rstrip("/") or f"{urlparse(base).scheme}://{urlparse(base).hostname}:8000/ping"
    return {
        "hosts": hosts,
        "ping_url": f"{ping}/{CREDS.hc_ping_key or '<ping-key>'}",
        "webhook": f"{base}/api/ingest/pve",
        "token": INGEST_TOKEN,
        "tz": _tz(),
        "types": jobs_mod.TYPES,
    }


@app.post("/api/checks")
async def check_create(request: Request):
    require_admin(request)
    if not CREDS.hc_api_key:
        raise HTTPException(503, "Healthchecks ist noch nicht eingerichtet")
    try:
        body, prio = jobs_mod.build(await _body(request), _tz())
    except jobs_mod.JobError as exc:
        raise HTTPException(400, str(exc)) from None
    if any(c["name"] == body["name"] for c in state["checks"]):
        raise UserError(409, "Job {name} gibt es schon", name=body["name"])
    other = _slug_taken(body["slug"])
    if other:
        raise UserError(409, "Ping-Adresse {slug} gehört schon zu {other} – bitte anderen Namen wählen", slug=body["slug"], other=other)
    try:
        body["channels"] = await _channel_ids(prio)
        created = (await _hc("POST", "/api/v3/checks/", json=body)).json()
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None
    await refresh()
    uuid = created.get("uuid") or created.get("unique_key")
    return {"ok": True, "check": next((c for c in state["checks"] if c["uuid"] == uuid), None), "form": jobs_mod.to_form(created)}


@app.get("/api/checks/{uuid}")
async def check_get(uuid: str, request: Request):
    require_admin(request)
    _uuid_ok(uuid)
    try:
        return jobs_mod.to_form((await _hc("GET", f"/api/v3/checks/{uuid}")).json())
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None


@app.put("/api/checks/{uuid}")
async def check_update(uuid: str, request: Request):
    require_admin(request)
    _uuid_ok(uuid)
    try:
        current = (await _hc("GET", f"/api/v3/checks/{uuid}")).json()
        body, prio = jobs_mod.build(await _body(request), _tz(), current=current)
        channels = await _channels_after_prio(current, prio)  # sonst bleiben die Kanäle, wie sie sind
        if channels is not None:
            body["channels"] = channels
        await _hc("POST", f"/api/v3/checks/{uuid}", json=body)
    except jobs_mod.JobError as exc:
        raise HTTPException(400, str(exc)) from None
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None
    await refresh()
    return {"ok": True, "check": next((c for c in state["checks"] if c["uuid"] == uuid), None)}


@app.delete("/api/checks/{uuid}")
async def check_delete(uuid: str, request: Request):
    require_admin(request)
    _uuid_ok(uuid)
    try:
        await _hc("DELETE", f"/api/v3/checks/{uuid}")
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None
    await refresh()
    return {"ok": True}


@app.get("/api/config/export")
async def config_export(request: Request):
    """Jobs und Host-Einstellungen als checks.yaml-Datei (Import: System → Konfiguration oder hc_sync)."""
    require_admin(request)
    tz = _tz()
    try:
        checks = (await _hc("GET", "/api/v3/checks/")).json()["checks"] if CREDS.hc_api_key else []
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None
    checks = [c for c in checks if "src:app" not in c.get("tags", "")]  # Lebenszeichen gehört nicht in die Datei
    hs = host_settings()
    hosts = {}
    for name in sorted({h["name"] for h in state["hosts"]} | set(hs)):
        x = host_extra(name, hs)
        if x["custom"] or not x["always_on"] or x["links"]:
            hosts[name] = {"beszel": name, "always_on": x["always_on"]} | (
                {"url": {li["label"]: li["url"] for li in x["links"]}} if x["links"] else {}
            )
    doc = {
        "settings": {"tz": tz} | ({"channels": cfg["settings"]["channels"]} if (cfg.get("settings") or {}).get("channels") else {}),
        "hosts": hosts,
        "checks": [jobs_mod.to_yaml_check(c, tz) for c in sorted(checks, key=lambda c: c["name"])],
    }
    head = (
        f"# QuietBoard – Jobs und Hosts, exportiert {now().strftime('%d.%m.%Y %H:%M')}\n"
        "# Import: System → Konfiguration (legt an und aktualisiert, löscht nie)\n"
    )
    text = head + yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=140)
    return Response(text, media_type="application/yaml", headers={"Content-Disposition": 'attachment; filename="quietboard-config.yaml"'})


@app.post("/api/config/import")
async def config_import(request: Request):
    """Body: {"yaml": "...", "dry": true|false}. Legt Jobs an/aktualisiert sie und übernimmt Host-Einstellungen – löscht nie.
    Erst wird alles geprüft; gibt es einen Fehler, wird nichts geschrieben (kein halber Import)."""
    require_admin(request)
    b = await _body(request)
    text = b.get("yaml", "")
    if not isinstance(text, str) or len(text) > 500_000:
        raise HTTPException(400, "YAML fehlt oder ist zu groß (höchstens 500 000 Zeichen)")
    try:
        doc = yaml.safe_load(text) or {}
    except yaml.YAMLError as exc:
        raise UserError(400, "YAML fehlerhaft: {e}", e=str(exc).splitlines()[0]) from None
    if (
        not isinstance(doc, dict)
        or not isinstance(doc.get("checks") or [], list)
        or not isinstance(doc.get("hosts") or {}, dict)
        or not isinstance(doc.get("settings") or {}, dict)
    ):
        raise HTTPException(400, "Erwartet: settings, hosts, checks wie in checks.yaml")
    dry = bool(b.get("dry", True))
    tz = str((doc.get("settings") or {}).get("tz") or _tz())
    checks_in = doc.get("checks") or []
    if checks_in and not CREDS.hc_api_key:
        raise HTTPException(503, "Healthchecks ist noch nicht eingerichtet")
    try:
        existing = {c["name"]: c for c in (await _hc("GET", "/api/v3/checks/")).json()["checks"]} if checks_in else {}
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None

    # 1. Prüfen
    actions, plan, slugs = [], [], {}
    for c in checks_in:
        label = str(c.get("name", "?")).strip() if isinstance(c, dict) else "?"
        cur = existing.get(label)
        try:
            body, prio = jobs_mod.from_yaml_check(c, tz, current=cur)
        except jobs_mod.JobError as exc:
            actions.append({"name": label, "action": "Fehler", "detail": str(exc)})
            continue
        slug = (cur or {}).get("slug") or body.get("slug") or config.slug(label)
        clash = slugs.get(slug) or next((n for n, e in existing.items() if (e.get("slug") or config.slug(n)) == slug and n != label), None)
        if clash:
            actions.append({"name": label, "action": "Fehler", "detail": f"Ping-Adresse {slug} gehört schon zu {clash}"})
            continue
        slugs[slug] = label
        plan.append((label, body, prio, cur))
        actions.append({"name": label, "action": "aktualisieren" if cur else "anlegen"})
    hosts, hs = [], host_settings()
    for key, h in (doc.get("hosts") or {}).items():
        h = h if isinstance(h, dict) else {}
        name = str(h.get("beszel") or key)
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name):
            actions.append({"name": f"Host {name[:40]}", "action": "Fehler", "detail": "Ungültiger Hostname"})
            continue
        url = h.get("url") or {}
        if isinstance(url, str):
            url = {"Weboberfläche": url}
        if not isinstance(url, dict):
            url = {}
        links = [{"label": str(k)[:40], "url": str(v)} for k, v in list(url.items())[:10] if _URL.fullmatch(str(v))]
        hosts.append({"name": name, "always_on": bool(h.get("always_on", True)), "links": len(links)})
        hs[name] = {"always_on": bool(h.get("always_on", True)), "links": links}
    has_errors = any(a["action"] == "Fehler" for a in actions)
    if dry or has_errors:
        return {"dry": True, "checks": actions, "hosts": hosts, "applied": False}

    # 2. Schreiben
    done = {}
    for label, body, prio, cur in plan:
        try:
            if cur:
                channels = await _channels_after_prio(cur, prio)  # sonst bleiben die Kanäle des Checks
                if channels is not None:
                    body["channels"] = channels
                await _hc("POST", f"/api/v3/checks/{cur.get('uuid') or cur.get('unique_key')}", json=body)
            else:
                body["channels"] = await _channel_ids(prio)
                await _hc("POST", "/api/v3/checks/", json=body)
        except httpx.HTTPError as exc:
            done[label] = {"name": label, "action": "Fehler", "detail": _hc_error(exc).detail}
    actions = [done.get(a["name"], a) for a in actions]
    if hosts:
        STORE.set_setting("hosts", hs)
    await refresh()
    return {"dry": False, "checks": actions, "hosts": hosts, "applied": True}


@app.post("/api/checks/{uuid}/{action}")
async def check_action(uuid: str, action: str, request: Request):
    require_admin(request)
    if not re.fullmatch(r"[0-9a-f-]{36}", uuid):
        raise HTTPException(400)
    try:
        if action in ("pause", "resume"):
            await _hc("POST", f"/api/v3/checks/{uuid}/{action}")
        elif action == "prio":
            prio = (await _body(request)).get("prio")
            if prio not in PRIOS:
                raise HTTPException(400, "Priorität: kritisch, normal oder info")
            current = (await _hc("GET", f"/api/v3/checks/{uuid}")).json()
            tags = [t for t in current.get("tags", "").split() if not t.startswith("prio:")] + [f"prio:{prio}"]
            upd = {"tags": " ".join(tags)}
            channels = await _channels_after_prio(current, prio)
            if channels is not None:
                upd["channels"] = channels
            await _hc("POST", f"/api/v3/checks/{uuid}", json=upd)
        else:
            raise HTTPException(404)
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None
    await refresh()
    return {"ok": True, "check": next((c for c in state["checks"] if c["uuid"] == uuid), None)}


@app.get("/login")
async def login_page():
    return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-cache"})


@app.get("/setup")
async def setup_page():
    if STORE.has_users():
        return RedirectResponse("/login", status_code=303)
    STORE.ensure_setup_code()  # Code erneut ins Log, falls er dort schon weggescrollt ist
    return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- Frontend
@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/sw.js")
async def sw():
    return FileResponse(STATIC / "sw.js", media_type="application/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
async def manifest():
    return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
