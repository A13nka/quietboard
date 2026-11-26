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
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import auth, bootstrap, config, i18n, push
from . import jobs as jobs_mod
from .i18n import tr

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

# PBS_TARGETS="pbs1|https://pbs1.example.lan:8007|status@pbs!app|SECRET;pbs2|https://...|...|..."
PBS_TARGETS = [t.split("|") for t in E("PBS_TARGETS", "").split(";") if t.count("|") == 3]

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
    except Exception as exc:  # beschädigte Datei nicht crashen lassen
        log.error("Kann %s nicht lesen: %s", name, exc)
        return default


def _save(name: str, obj) -> None:
    p = DATA / name
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


updates: dict = _load("updates.json", {})  # key "<host>|<kind>" -> Bericht
events: list = _load("events.json", [])  # neueste zuerst, max 300
flags: dict = _load("flags.json", {})  # host -> {reboot, checked, sec_alerted}
SEC_GRACE_H = 48  # Security-Update gilt danach als überfällig
digest_state: dict = _load("digest.json", {})
push_subs: dict = _load("push.json", {})  # endpoint -> Subscription
push_state: dict = _load("push_state.json", {})  # check-uuid -> letzter Status
last_sent: dict[str, float] = {}

state: dict = {"generated": None, "checks": [], "hosts": [], "pbs": {}, "errors": {}}
cfg: dict = {}


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


async def send_signal(text: str, dedup_key: str | None = None, url: str = "/") -> bool:
    """Meldung an alle Kanäle: Web Push, Mail, Signal (Name historisch)."""
    if dedup_key:
        t = last_sent.get(dedup_key, 0)
        if time.time() - t < DEDUP_SECONDS:
            log.info("Meldung unterdrückt (Dedup): %s", dedup_key)
            return False
        last_sent[dedup_key] = time.time()
    lines = text.strip().splitlines() or [""]
    pushed = await push_all(lines[0], "\n".join(lines[1:]), url)
    subject = lines[0] if SITE_NAME in lines[0] else f"[{SITE_NAME}] {lines[0]}"
    mailed = await send_mail(subject, text)
    pushed += int(mailed)
    if not (SIGNAL_NUMBER and SIGNAL_RECIPIENT):
        if not pushed:
            log.warning("Kein Kanal hat zugestellt: %s", text[:80])
        return pushed > 0
    body = {"message": text, "number": SIGNAL_NUMBER, "recipients": [SIGNAL_RECIPIENT]}
    try:
        async with httpx.AsyncClient(timeout=30) as cli:
            r = await cli.post(f"{SIGNAL_URL}/v2/send", json=body)
            r.raise_for_status()
        return True
    except Exception as exc:
        log.error("Signal-Versand fehlgeschlagen: %s", exc)
        return pushed > 0


async def check_transitions() -> None:
    """Push bei Statuswechsel eines Checks (grün→rot, rot→grün). Healthchecks schickt Signal selbst."""
    if not state["checks"]:
        return
    first = not push_state
    changed = False
    for c in state["checks"]:
        cur = c["status"]
        if cur == "started":  # Laufzustand nicht merken, sonst geht rot→läuft→grün verloren
            continue
        prev = push_state.get(c["uuid"])
        if prev == cur:
            continue
        push_state[c["uuid"]] = cur
        changed = True
        if first or prev is None or c["prio"] not in PUSH_PRIOS:
            continue
        url = f"/?c={c['uuid']}"
        if cur == "down":
            await push_all(
                "🔴 " + tr("{name} ausgefallen", name=c["name"]), tr("Kein Ping zur erwarteten Zeit oder Fehler gemeldet."), url, c["uuid"]
            )
        elif prev == "down" and cur == "up":
            await push_all("✅ " + tr("{name} wieder OK", name=c["name"]), "", url, c["uuid"])
    if changed:
        _save("push_state.json", push_state)


# ---------------------------------------------------------------- Datenquellen
async def fetch_checks(cli: httpx.AsyncClient) -> list[dict]:
    r = await cli.get(f"{HC_URL}/api/v3/checks/", headers={"X-Api-Key": CREDS.hc_api_key})
    r.raise_for_status()
    prio = {c["name"]: c["prio"] for c in cfg.get("checks", [])}
    out = []
    for c in r.json()["checks"]:
        tags = dict(t.split(":", 1) for t in c.get("tags", "").split() if ":" in t)
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


async def fetch_pbs(name: str, url: str, token_id: str, secret: str) -> dict:
    headers = {"Authorization": f"PBSAPIToken={token_id}:{secret}"}
    async with httpx.AsyncClient(timeout=10, verify=False, headers=headers) as cli:
        ds = (await cli.get(f"{url}/api2/json/status/datastore-usage")).raise_for_status().json()["data"]
        tasks = (
            (await cli.get(f"{url}/api2/json/nodes/localhost/tasks", params={"running": 1, "limit": 20})).raise_for_status().json()["data"]
        )
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


async def check_watch_images(cli: httpx.AsyncClient) -> None:
    """Docker-Hub-Images aus checks.yaml (watch_images) auf neuere Tags gleichen Schemas prüfen."""
    seen: set[str] = set()
    for w in cfg.get("watch_images", []) or []:
        image, _, tag = w["image"].rpartition(":")
        cur = _ver(tag)
        if not cur:
            continue
        repo = image if "/" in image else f"library/{image}"
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


async def refresh() -> None:
    global cfg, _last_refresh
    _last_refresh = time.monotonic()
    try:
        cfg = config.load()
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
                state["errors"][name] = f"nicht erreichbar: {exc}"
                log.warning("%s: %s", name, exc)
        await ensure_alerts()
        try:
            await check_transitions()
            await check_sec_overdue()
        except Exception:
            log.exception("Push-Auswertung fehlgeschlagen")
        for name, url, tid, sec in PBS_TARGETS:
            try:
                state["pbs"][name] = await fetch_pbs(name, url, tid, sec)
            except Exception:
                prev = state["pbs"].get(name, {})
                state["pbs"][name] = {**prev, "online": False, "running": []}  # offline: keine "laufenden" Tasks anzeigen
        watch_cfg = json.dumps(cfg.get("watch_images"), sort_keys=True)
        if digest_state.get("watch_checked") != now().date().isoformat() or digest_state.get("watch_cfg") != watch_cfg:
            await check_watch_images(cli)
            digest_state["watch_checked"] = now().date().isoformat()
            digest_state["watch_cfg"] = watch_cfg
            _save("digest.json", digest_state)
    state["generated"] = now().isoformat(timespec="seconds")


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


async def check_sec_overdue() -> None:
    """Einmalige Meldung, wenn Security-Updates länger als SEC_GRACE_H offen sind (Automatik hat nicht gegriffen)."""
    overdue = {h["host"]: h for h in host_updates() if h["sec_overdue"]}
    changed = False
    for name, h in overdue.items():
        sig = ",".join(sorted(h["sec_overdue_pkgs"]))
        f = flags.setdefault(name, {})
        if f.get("sec_alerted") != sig:
            f["sec_alerted"] = sig
            changed = True
            await send_signal(
                "🟠 "
                + tr("{name}: {n} Security-Update(s) seit über {h} h offen", name=name, n=h["sec_overdue"], h=SEC_GRACE_H)
                + "\n"
                + ", ".join(h["sec_overdue_pkgs"][:6]),
                url="/?t=up",
            )
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
    cutoff = (now() - dt.timedelta(hours=24)).isoformat()
    for ev in events:
        if ev["ts"] < cutoff:
            break
        if ev["prio"] in ("kritisch", "normal") and ev["source"] in ("pve", "pbs", "notify"):
            items.append({"level": "warn", "kind": "event", "title": ev["title"], "detail": ev["message"][:300]})
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
            t = STORE.get_setting("digest_time") or (cfg.get("settings") or {}).get("digest_time", "07:00")
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


app = FastAPI(title="Status", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)


# ---------------------------------------------------------------- Zugriffsschutz
_jwk = jwt.PyJWKClient(f"https://{ACCESS_TEAM}.cloudflareaccess.com/cdn-cgi/access/certs") if ACCESS_TEAM else None


SESSION_COOKIE = "qb_session"
# Ohne Anmeldung erreichbar: Gesundheitsprüfung, Ingest/Installer (eigener Token), Anmeldeseiten und statische Dateien
PUBLIC_PATHS = ("/healthz", "/login", "/setup", "/sw.js", "/manifest.webmanifest", "/api/auth/state", "/api/auth/login", "/api/auth/setup")
PUBLIC_PREFIXES = ("/api/ingest/", "/api/install/", "/static/")
UNSAFE = ("POST", "PUT", "PATCH", "DELETE")


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
    """Schutz gegen fremde Seiten, die im Namen des Browsers schreiben (CSRF)."""
    host = request.headers.get("host", "")
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        return urlparse(origin).netloc == host
    return request.headers.get("sec-fetch-site", "same-origin") in ("same-origin", "none")


@app.middleware("http")
async def access_guard(request: Request, call_next):
    path = request.url.path
    request.state.user = None
    if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
        return await call_next(request)
    if ALLOW_NO_AUTH:
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
        if user and request.method in UNSAFE and not _same_origin(request):
            return JSONResponse({"detail": "Anfrage von fremder Seite abgelehnt"}, status_code=403)
    if user is None:
        if request.method == "GET" and not path.startswith("/api/"):
            return RedirectResponse("/setup" if not STORE.has_users() else "/login", status_code=303)
        return JSONResponse({"detail": "Anmeldung erforderlich", "setup": not STORE.has_users()}, status_code=401)
    request.state.user = user
    return await call_next(request)


def require_admin(request: Request) -> dict:
    user = getattr(request.state, "user", None)
    if not user or user.get("role") != "admin":
        raise HTTPException(403, "Nur für Admins")
    return user


def require_token(request: Request) -> None:
    # Token per Bearer-Header, X-Token-Header oder ?token= (für Absender ohne eigene Header, z. B. Bridges)
    candidates = {
        request.headers.get("authorization", "").removeprefix("Bearer ").strip(),
        request.headers.get("x-token", ""),
        request.query_params.get("token", ""),
    }
    if not INGEST_TOKEN or INGEST_TOKEN not in candidates:
        raise HTTPException(401, "Token fehlt oder falsch")


def _resolve(host: str) -> set[str]:
    try:
        return {ai[4][0] for ai in socket.getaddrinfo(host, None)}
    except OSError:
        return set()


def require_beszel(request: Request) -> None:
    """Beszel-Webhook: nur vom Beszel-Container (per Namensauflösung), aus INTERNAL_NETS oder mit Ingest-Token.
    Ein pauschales "privates Netz" reicht nicht – sonst dürfte jedes Gerät im LAN Meldungen einspielen."""
    client = request.client.host if request.client else ""
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
    if "links" in g:
        url = {li["label"]: li["url"] for li in g["links"]}
    links = []
    for label, u in url.items():
        hostpart = re.sub(r"^\w+://", "", str(u)).split("/")[0].split(":")[0]
        links.append({"label": str(label), "url": str(u), "vpn": bool(_PRIV.search(hostpart))})
    return {"always_on": g.get("always_on", conf.get("always_on", True)), "links": links, "custom": bool(g)}


@app.get("/api/state")
async def api_state(fresh: int = 0):
    """fresh=1 (Knopf ↻): Daten sofort neu holen statt bis zur nächsten Abfrage zu warten – höchstens alle 10 s."""
    if fresh and not DEMO:
        async with _refresh_lock:
            if time.monotonic() - _last_refresh >= 10:
                await refresh()
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
    require_token(request)
    if not (CREDS.hc_ping_key and CREDS.agent_token and CREDS.hub_key):
        raise HTTPException(503, "Healthchecks/Beszel noch nicht eingerichtet")
    base = str(request.base_url).rstrip("/")
    values = {
        "QB_PING_BASE": E("HC_PING_ENDPOINT", "").rstrip("/") or f"{urlparse(base).scheme}://{urlparse(base).hostname}:8000/ping",
        "QB_PING_KEY": CREDS.hc_ping_key,
        "QB_INGEST_URL": f"{base}/api/ingest/updates",
        "QB_INGEST_TOKEN": INGEST_TOKEN,
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
        "# Als root direkt; sonst Rechte per sudo holen (QB_*-Werte ausdrücklich mitgeben, sudo setzt die Umgebung zurück)",
        'if [ "$(id -u)" = 0 ]; then',
        '  bash "$QB_FILES/install-host.sh"',
        "else",
        '  command -v sudo >/dev/null || { echo "QuietBoard: bitte als root ausführen (sudo fehlt)" >&2; exit 1; }',
        '  qb_env=(); for v in ${!QB_@}; do qb_env+=("$v=${!v}"); done',
        '  sudo env "${qb_env[@]}" bash "$QB_FILES/install-host.sh"',
        "fi",
        "",
    ]
    return Response("\n".join(lines), media_type="text/x-shellscript", headers={"Cache-Control": "no-store"})


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
@app.post("/api/ingest/updates")
async def ingest_updates(request: Request):
    """Body: {host, kind: apt|dsm|docker|scanner|mailcow, items: [{pkg, from, to, security}], reboot?: bool}"""
    require_token(request)
    b = await request.json()
    host, kind = str(b["host"]), str(b.get("kind", "apt"))
    key = f"{host}|{kind}"
    prev = {i["pkg"]: i.get("since") for i in updates.get(key, {}).get("items", [])}
    ts = now().isoformat(timespec="seconds")
    items = []
    for i in (b.get("items") or [])[:500]:
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
        flags.setdefault(host, {}).update({"reboot": bool(b["reboot"]), "checked": ts})
        _save("flags.json", flags)
    if not DEMO and host not in {h["name"] for h in state["hosts"]}:
        # Neuer Host (erster Bericht direkt nach der Installation): gleich nachsehen, ob sein Agent schon da ist
        asyncio.get_running_loop().call_later(5, lambda: asyncio.create_task(refresh()))
    return {"ok": True, "count": len(items)}


@app.post("/api/ingest/pve")
async def ingest_pve(request: Request, source: str = "pve", host: str = "pve"):
    """PVE/PBS-Webhook. Query: source=pve|pbs, host=<name aus checks.yaml match.host>."""
    require_token(request)
    try:
        b = await request.json()
    except Exception:
        b = {"severity": "unknown", "title": "unlesbares Event", "message": (await request.body()).decode(errors="replace")}
    severity = str(b.get("severity", "info")).lower()
    fields = b.get("fields") or {}
    title, message = str(b.get("title", "")), str(b.get("message", ""))
    hits = config.match_event(cfg, source, host, fields)
    seen = {c["slug"] for c in hits}
    gui_jobs = {"checks": [c for c in state["checks"] if c.get("match")]}  # in der Oberfläche angelegte Jobs
    hits += [c for c in config.match_event(gui_jobs, source, host, fields) if c["slug"] not in seen]
    failed = severity == "error"
    if hits and CREDS.hc_ping_key:
        async with httpx.AsyncClient(timeout=15, limits=NO_KEEPALIVE) as cli:
            for c in hits:
                url = f"{HC_URL}/ping/{CREDS.hc_ping_key}/{c['slug']}" + ("/fail" if failed else "")
                try:
                    await cli.post(url, content=f"{title}\n\n{message}"[:90000].encode())
                except Exception as exc:
                    log.error("Ping %s fehlgeschlagen: %s", c["slug"], exc)
        add_event(source, f"{host}: {title}", message, "info")
        asyncio.get_running_loop().call_later(2, lambda: asyncio.create_task(refresh()))  # Job-Status gleich anzeigen
    else:
        # Unbekanntes Event: nie still verschlucken, wenn es ein Fehler ist
        prio = "normal" if failed else "info"
        add_event(source, tr("{host}: {title} (ohne Check)", host=host, title=title), message, prio)
        if failed:
            await send_signal(
                f"🔴 {host}: {title}\n(" + tr("kein passender Job – unter Jobs anlegen") + ")", dedup_key=f"pve:{host}:{title}"
            )
    return {"ok": True, "matched": [c["name"] for c in hits]}


@app.post("/api/ingest/beszel")
async def ingest_beszel(request: Request):
    """Beszel-Benachrichtigung (Shoutrrr generic, template=json). Nur vom Beszel-Container oder mit Token."""
    require_beszel(request)
    try:
        b = await request.json()
    except Exception:
        b = {"title": "Beszel", "message": (await request.body()).decode(errors="replace")}
    title, message = str(b.get("title", "Beszel")), str(b.get("message", ""))
    add_event("beszel", title, message, "normal")
    await send_signal(f"🖥️ {title}\n{message}", dedup_key=f"beszel:{title}")
    return {"ok": True}


ERROR_WORDS = re.compile(r"fehl|error|fail|❌|🔴|critical|kritisch|abgebrochen|rollback", re.I)


@app.post("/api/ingest/notify")
async def ingest_notify(request: Request):
    """Generische Meldung. Body: {source, title, message, prio: kritisch|normal|info}
    Versteht auch den signal-api-Body {"message": ...} (für bestehende Bridges).
    Query: ?source=…&prio=… überschreiben; ohne prio: Fehlerwörter → normal, sonst info."""
    require_token(request)
    try:
        b = await request.json()
    except Exception:
        b = {"message": (await request.body()).decode(errors="replace")}
    message = str(b.get("message", ""))
    title = str(b.get("title") or (message.strip().splitlines() or ["Meldung"])[0])[:200]
    prio = request.query_params.get("prio") or b.get("prio") or ("normal" if ERROR_WORDS.search(title + " " + message) else "info")
    source = request.query_params.get("source") or str(b.get("source", "notify"))
    add_event(source, title, message, prio)
    if prio in ("kritisch", "normal"):
        await send_signal(f"{'🔴' if prio == 'kritisch' else '🟡'} {title}\n{message}"[:2000], dedup_key=f"n:{title}")
    return {"ok": True}


@app.post("/api/ingest/signal/{token}")
@app.post("/api/ingest/signal/{token}/v2/send")
async def ingest_signal_compat(token: str, request: Request):
    """Drop-in für Absender, die signal-api erwarten (z. B. dockhand-signal-bridge).
    SIGNAL_API_URL=http://<server>:8088/api/ingest/signal/<INGEST_TOKEN>  (Bridge hängt /v2/send an)."""
    if not INGEST_TOKEN or token != INGEST_TOKEN:
        raise HTTPException(401, "Token fehlt oder falsch")
    try:
        b = await request.json()
    except Exception:
        b = {"message": (await request.body()).decode(errors="replace")}
    message = str(b.get("message", ""))
    title = (message.strip().splitlines() or ["Meldung"])[0][:200]
    prio = request.query_params.get("prio") or ("normal" if ERROR_WORDS.search(message) else "info")
    source = request.query_params.get("source", "dockhand")
    add_event(source, title, message, prio)
    if prio in ("kritisch", "normal"):
        await send_signal(f"{'🔴' if prio == 'kritisch' else '🟡'} {message}"[:2000], dedup_key=f"n:{title}")
    return {"timestamp": str(int(time.time() * 1000))}


@app.get("/api/push/key")
async def push_key():
    if not VAPID:
        raise HTTPException(503, "VAPID_PRIVATE_KEY fehlt")
    return {"key": VAPID.public_b64}


@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    b = await request.json()
    sub = {"endpoint": b.get("endpoint"), "keys": b.get("keys") or {}}
    if not push.valid_subscription(sub):
        raise HTTPException(400, "ungültige Push-Registrierung")
    known = push_subs.get(sub["endpoint"])
    push_subs[sub["endpoint"]] = {
        **sub,
        "since": (known or {}).get("since") or now().isoformat(timespec="seconds"),
        "ua": request.headers.get("user-agent", "")[:120],
    }
    _save("push.json", push_subs)
    if not known:
        log.info("Neues Push-Gerät registriert (%d gesamt)", len(push_subs))
    return {"ok": True, "count": len(push_subs)}


@app.post("/api/push/unsubscribe")
async def push_unsubscribe(request: Request):
    b = await request.json()
    push_subs.pop(str(b.get("endpoint")), None)
    _save("push.json", push_subs)
    return {"ok": True, "count": len(push_subs)}


@app.post("/api/push/test")
async def push_test():
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
        user = STORE.complete_setup(b.get("code", ""), b.get("email", ""), b.get("password", ""), b.get("name", ""))
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
        user = STORE.login(b.get("email", ""), b.get("password", ""), request.client.host if request.client else "")
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
        STORE.change_password(user["id"], b.get("old", ""), b.get("new", ""))
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
        return {"user": STORE.create_user(b.get("email", ""), b.get("password", ""), b.get("role", "viewer"), b.get("name", ""))}
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None


@app.patch("/api/users/{uid}")
async def users_update(uid: int, request: Request):
    me = require_admin(request)
    b = await _body(request)
    try:
        if "password" in b:
            STORE.set_password(uid, b["password"])
        if "role" in b:
            STORE.set_role(uid, b["role"], me.get("id", 0))
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"user": STORE.get_user(uid)}


@app.delete("/api/users/{uid}")
async def users_delete(uid: int, request: Request):
    me = require_admin(request)
    try:
        STORE.delete_user(uid, me.get("id", 0))
    except auth.AuthError as exc:
        raise HTTPException(400, str(exc)) from None
    return {"ok": True}


# ---------------------------------------------------------------- Einstellungen, Kanäle, System
def _settings() -> dict:
    return {
        "mail_to": mail_recipients(),
        "digest_time": STORE.get_setting("digest_time") or (cfg.get("settings") or {}).get("digest_time", "07:00"),
        "channels": {"mail": bool(SMTP["host"]), "push": bool(VAPID), "signal": bool(SIGNAL_NUMBER and SIGNAL_RECIPIENT)},
        "language": i18n.lang(),
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
    return _settings()


@app.post("/api/notify/test")
async def notify_test(request: Request):
    b = await _body(request)
    channel = b.get("channel")
    if channel == "push":
        return {"ok": bool(await push_all("🔔 Test", tr("Mitteilungen von QuietBoard funktionieren."), "/", "test"))}
    require_admin(request)
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
            raise HTTPException(400, f"Link muss mit http:// oder https:// beginnen: {url[:60]}")
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
    """Der eine Befehl für "Host hinzufügen" (enthält den Ingest-Token – nur für Admins)."""
    require_admin(request)
    if not (CREDS.hc_ping_key and CREDS.agent_token and CREDS.hub_key):
        raise HTTPException(503, "Healthchecks/Beszel noch nicht eingerichtet")
    base = str(request.base_url).rstrip("/")
    cmd = f'curl -fsSL -H "Authorization: Bearer {INGEST_TOKEN}" {base}/api/install/host.sh | bash'
    return {"command": cmd, "base": base}


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
        return HTTPException(400, f"Healthchecks lehnt ab: {msg}")
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        return HTTPException(404, "Job nicht gefunden (inzwischen gelöscht?)")
    return HTTPException(502, f"Healthchecks nicht erreichbar: {type(exc).__name__}")


async def _channel_ids(prio: str) -> str:
    names = ((cfg.get("settings") or {}).get("channels") or jobs_mod.DEFAULT_CHANNELS).get(prio, [])
    if not names:
        return ""
    by_name = {c["name"]: c["id"] for c in (await _hc("GET", "/api/v3/channels/")).json()["channels"]}
    return ",".join(by_name[n] for n in names if n in by_name)


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
        raise HTTPException(409, f"Job {body['name']} gibt es schon")
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
        body["channels"] = await _channel_ids(prio)
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
    """Body: {"yaml": "...", "dry": true|false}. Legt Jobs an/aktualisiert sie und übernimmt Host-Einstellungen – löscht nie."""
    require_admin(request)
    b = await _body(request)
    try:
        doc = yaml.safe_load(str(b.get("yaml", ""))[:500_000]) or {}
    except yaml.YAMLError as exc:
        raise HTTPException(400, f"YAML fehlerhaft: {str(exc).splitlines()[0]}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("checks", []), list) or not isinstance(doc.get("hosts", {}), dict):
        raise HTTPException(400, "Erwartet: settings, hosts, checks wie in checks.yaml")
    dry = bool(b.get("dry", True))
    tz = (doc.get("settings") or {}).get("tz") or _tz()
    if doc.get("checks") and not CREDS.hc_api_key:
        raise HTTPException(503, "Healthchecks ist noch nicht eingerichtet")
    try:
        existing = {c["name"]: c for c in (await _hc("GET", "/api/v3/checks/")).json()["checks"]} if doc.get("checks") else {}
    except httpx.HTTPError as exc:
        raise _hc_error(exc) from None
    actions = []
    for c in doc.get("checks") or []:
        try:
            body, prio = jobs_mod.from_yaml_check(c, tz)
        except jobs_mod.JobError as exc:
            label = str(c.get("name", "?")) if isinstance(c, dict) else "?"
            actions.append({"name": label, "action": "Fehler", "detail": str(exc)})
            continue
        cur = existing.get(body["name"])
        act = {"name": body["name"], "action": "aktualisieren" if cur else "anlegen"}
        if not dry:
            try:
                body["channels"] = await _channel_ids(prio)
                if cur:
                    body.pop("slug", None)
                    await _hc("POST", f"/api/v3/checks/{cur.get('uuid') or cur.get('unique_key')}", json=body)
                else:
                    await _hc("POST", "/api/v3/checks/", json=body)
            except httpx.HTTPError as exc:
                act = {"name": body["name"], "action": "Fehler", "detail": _hc_error(exc).detail}
        actions.append(act)
    hosts = []
    hs = host_settings()
    for key, h in (doc.get("hosts") or {}).items():
        h = h or {}
        name = str(h.get("beszel") or key)
        url = h.get("url") or {}
        if isinstance(url, str):
            url = {"Weboberfläche": url}
        links = [{"label": str(k)[:40], "url": str(v)} for k, v in url.items() if _URL.fullmatch(str(v))]
        hosts.append({"name": name, "always_on": bool(h.get("always_on", True)), "links": len(links)})
        hs[name] = {"always_on": bool(h.get("always_on", True)), "links": links}
    if not dry:
        if hosts:
            STORE.set_setting("hosts", hs)
        await refresh()
    return {"dry": dry, "checks": actions, "hosts": hosts}


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
            await _hc("POST", f"/api/v3/checks/{uuid}", json={"tags": " ".join(tags), "channels": await _channel_ids(prio)})
        else:
            raise HTTPException(404)
    except httpx.HTTPError as exc:
        raise HTTPException(502, f"Healthchecks: {exc}") from None
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
