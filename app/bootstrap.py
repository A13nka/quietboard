"""Zugänge zu den Motoren: aus der Umgebung, sonst automatisch eingerichtet.

- Healthchecks: healthchecks-init (compose.yaml) legt Projekt und Keys an und übergibt sie in
  /bootstrap/healthchecks.json. Hier wird die Datei nur gelesen.
- Beszel: beszel-init legt den Superuser an (ADMIN_EMAIL/ADMIN_PASSWORD). Die App richtet damit per API ein:
  Admin-Benutzer, readonly-Benutzer für die App, dauerhaften Universal-Token für Agents und liest den
  öffentlichen Schlüssel des Hubs. Ergebnis in /data/beszel.json (Rechte 600).

Alles ist idempotent. Werte aus der Umgebung (Bestandsinstallationen) haben Vorrang.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
from dataclasses import dataclass, field
from pathlib import Path

import httpx

log = logging.getLogger("status.bootstrap")

BOOTSTRAP_DIR = Path(os.getenv("BOOTSTRAP_DIR", "/bootstrap"))
DATA = Path(os.getenv("DATA_DIR", "/data"))


@dataclass
class Credentials:
    hc_api_key: str = ""
    hc_ping_key: str = ""
    beszel_user: str = ""
    beszel_pass: str = ""
    agent_token: str = ""
    hub_key: str = ""
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def hc_ready(self) -> bool:
        return bool(self.hc_api_key)

    @property
    def beszel_ready(self) -> bool:
        return bool(self.beszel_user and self.beszel_pass)


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        log.error("Kann %s nicht lesen: %s", path, exc)
        return {}


def _write_private(path: Path, obj: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(path)


def load(env=os.environ) -> Credentials:
    """Bekannte Zugänge ohne Netzwerkzugriff zusammenstellen."""
    hc = _read_json(BOOTSTRAP_DIR / "healthchecks.json")
    bz = _read_json(DATA / "beszel.json")
    return Credentials(
        hc_api_key=env.get("HC_API_KEY") or hc.get("api_key", ""),
        hc_ping_key=env.get("HC_PING_KEY") or hc.get("ping_key", ""),
        beszel_user=env.get("BESZEL_USER") or bz.get("user", ""),
        beszel_pass=env.get("BESZEL_PASS") or bz.get("password", ""),
        agent_token=bz.get("agent_token", ""),
        hub_key=bz.get("hub_key", ""),
    )


def _app_email(admin_email: str) -> str:
    domain = admin_email.rsplit("@", 1)[-1] if "@" in admin_email else "example.org"
    return f"quietboard-app@{domain}"


async def _auth(cli: httpx.AsyncClient, collection: str, email: str, password: str) -> dict:
    r = await cli.post(f"/api/collections/{collection}/auth-with-password", json={"identity": email, "password": password})
    r.raise_for_status()
    return r.json()


async def _find_user(cli: httpx.AsyncClient, headers: dict, email: str) -> dict | None:
    r = await cli.get("/api/collections/users/records", params={"filter": f"email='{email}'", "perPage": 1}, headers=headers)
    r.raise_for_status()
    items = r.json().get("items", [])
    return items[0] if items else None


async def _ensure_user(cli: httpx.AsyncClient, headers: dict, email: str, password: str, role: str) -> dict:
    user = await _find_user(cli, headers, email)
    body = {"password": password, "passwordConfirm": password, "role": role, "verified": True}
    if user is None:
        r = await cli.post("/api/collections/users/records", json={"email": email, **body}, headers=headers)
    else:
        r = await cli.patch(f"/api/collections/users/records/{user['id']}", json=body, headers=headers)
    r.raise_for_status()
    return r.json()


async def setup_beszel(base_url: str, admin_email: str, admin_password: str, client: httpx.AsyncClient | None = None) -> dict:
    """Beszel per API einrichten. Rückgabe wie /data/beszel.json."""
    path = DATA / "beszel.json"
    saved = _read_json(path)
    own = client is None
    cli = client or httpx.AsyncClient(base_url=base_url, timeout=15)
    try:
        if saved.get("user") and saved.get("password") and saved.get("agent_token") and saved.get("hub_key"):
            try:  # schon eingerichtet und der App-Zugang funktioniert → nichts tun
                await _auth(cli, "users", saved["user"], saved["password"])
                return saved
            except httpx.HTTPStatusError:
                log.warning("Beszel: gespeicherter App-Zugang ungültig, richte neu ein")

        su = await _auth(cli, "_superusers", admin_email, admin_password)
        headers = {"Authorization": su["token"]}
        admin = await _ensure_user(cli, headers, admin_email, admin_password, "admin")

        app_email = saved.get("user") or _app_email(admin_email)
        app_pass = secrets.token_urlsafe(24)
        await _ensure_user(cli, headers, app_email, app_pass, "readonly")

        r = await cli.get(
            "/api/collections/universal_tokens/records", params={"filter": f"user='{admin['id']}'", "perPage": 1}, headers=headers
        )
        r.raise_for_status()
        items = r.json().get("items", [])
        if items:
            token = items[0]["token"]
        else:
            token = secrets.token_urlsafe(32)
            r = await cli.post("/api/collections/universal_tokens/records", json={"user": admin["id"], "token": token}, headers=headers)
            r.raise_for_status()

        user_auth = await _auth(cli, "users", admin_email, admin_password)
        r = await cli.get("/api/beszel/getkey", headers={"Authorization": user_auth["token"]})
        r.raise_for_status()
        hub_key = r.json()["key"]

        result = {"user": app_email, "password": app_pass, "agent_token": token, "hub_key": hub_key}
        _write_private(path, result)
        log.info("Beszel eingerichtet: App-Benutzer %s, Universal-Token für Agents aktiv", app_email)
        return result
    finally:
        if own:
            await cli.aclose()


async def ensure(creds: Credentials, env=os.environ) -> Credentials:
    """Fehlende Zugänge nachladen bzw. einrichten. Fehler landen in creds.errors, nie als Ausnahme."""
    fresh = load(env)
    creds.hc_api_key = creds.hc_api_key or fresh.hc_api_key
    creds.hc_ping_key = creds.hc_ping_key or fresh.hc_ping_key
    if not creds.hc_ready:
        creds.errors["healthchecks"] = "Einrichtung ausstehend (healthchecks-init)"
    else:
        creds.errors.pop("healthchecks", None)

    if not creds.beszel_ready:
        admin_email, admin_password = env.get("ADMIN_EMAIL", ""), env.get("ADMIN_PASSWORD", "")
        if not (admin_email and admin_password):
            creds.errors["beszel"] = "nicht konfiguriert (ADMIN_EMAIL/ADMIN_PASSWORD fehlen)"
            return creds
        try:
            bz = await setup_beszel(env.get("BESZEL_URL", "http://beszel:8090").rstrip("/"), admin_email, admin_password)
            creds.beszel_user, creds.beszel_pass = bz["user"], bz["password"]
            creds.agent_token, creds.hub_key = bz["agent_token"], bz["hub_key"]
            creds.errors.pop("beszel", None)
        except Exception as exc:
            creds.errors["beszel"] = f"Einrichtung fehlgeschlagen: {exc}"
            log.warning("Beszel-Einrichtung: %s", exc)
    return creds


# ---------------------------------------------------------------- Beszel-Alarme
# Standardgrenzen je System (Konzept: Status 5 min · Disk > 90 % 10 min · RAM > 95 % 15 min)
def default_alerts(down_min: int) -> list[dict]:
    return [
        {"name": "Status", "value": 0, "min": down_min},
        {"name": "Disk", "value": 90, "min": 10},
        {"name": "Memory", "value": 95, "min": 15},
    ]


async def delete_beszel_system(base_url: str, admin_email: str, admin_password: str, name: str) -> bool:
    """Host aus Beszel entfernen (Superuser). False, wenn es ihn dort nicht gibt."""
    async with httpx.AsyncClient(base_url=base_url, timeout=15) as cli:
        su = await _auth(cli, "_superusers", admin_email, admin_password)
        h = {"Authorization": su["token"]}
        r = await cli.get("/api/collections/systems/records", params={"filter": f"name={json.dumps(name)}", "perPage": 5}, headers=h)
        r.raise_for_status()
        items = r.json().get("items", [])
        for it in items:
            (await cli.delete(f"/api/collections/systems/records/{it['id']}", headers=h)).raise_for_status()
        return bool(items)


async def ensure_beszel_alerts(
    base_url: str,
    admin_email: str,
    admin_password: str,
    system_ids: set[str],
    webhook: str,
    down_min: int = 5,
    client: httpx.AsyncClient | None = None,
) -> set[str]:
    """Webhook an die App eintragen und für neue Systeme die Standard-Alarme anlegen.
    Rückgabe: System-IDs, die jetzt versorgt sind. Bestehende Alarme und weitere Webhooks bleiben unberührt.
    Hinweis: Beszel überschreibt beim Anlegen von user_settings die Werte – deshalb anlegen, dann aktualisieren."""
    own = client is None
    cli = client or httpx.AsyncClient(base_url=base_url, timeout=15)
    try:
        su = await _auth(cli, "_superusers", admin_email, admin_password)
        h = {"Authorization": su["token"]}
        admin = await _find_user(cli, h, admin_email)
        if not admin:
            raise RuntimeError("Beszel-Admin fehlt")
        uid = admin["id"]

        r = await cli.get("/api/collections/user_settings/records", params={"filter": f"user='{uid}'", "perPage": 1}, headers=h)
        r.raise_for_status()
        items = r.json().get("items", [])
        if not items:
            r = await cli.post("/api/collections/user_settings/records", json={"user": uid, "settings": {}}, headers=h)
            r.raise_for_status()
            items = [r.json()]
        rec = items[0]
        settings = dict(rec.get("settings") or {})
        hooks = list(settings.get("webhooks") or [])
        if webhook not in hooks or settings.get("emails"):
            settings.update(webhooks=[*hooks, webhook] if webhook not in hooks else hooks, emails=[])  # Mails verschickt die App
            settings.setdefault("chartTime", "1h")
            r = await cli.patch(f"/api/collections/user_settings/records/{rec['id']}", json={"settings": settings}, headers=h)
            r.raise_for_status()
            log.info("Beszel: Benachrichtigungen gehen an die App (%s)", webhook.split("?")[0])

        done: set[str] = set()
        for sid in sorted(system_ids):
            r = await cli.get(
                "/api/collections/alerts/records", params={"filter": f"system='{sid}' && user='{uid}'", "perPage": 50}, headers=h
            )
            r.raise_for_status()
            have = {a["name"] for a in r.json().get("items", [])}
            for alert in default_alerts(down_min):
                if alert["name"] not in have:
                    r = await cli.post("/api/collections/alerts/records", json={"user": uid, "system": sid, **alert}, headers=h)
                    r.raise_for_status()
            done.add(sid)
        return done
    finally:
        if own:
            await cli.aclose()


def alerts_done() -> set[str]:
    return set(_read_json(DATA / "beszel.json").get("alerts_for", []))


def mark_alerts_done(ids: set[str]) -> None:
    path = DATA / "beszel.json"
    data = _read_json(path)
    if data:
        data["alerts_for"] = sorted(set(data.get("alerts_for", [])) | ids)
        _write_private(path, data)
