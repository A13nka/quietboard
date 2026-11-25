"""Bootstrap: Zugänge laden und Beszel per API einrichten (gegen eine simulierte Beszel-API)."""

import asyncio
import json
import stat

import httpx
import pytest

from app import bootstrap


class FakeBeszel:
    """Minimaler PocketBase/Beszel-Ersatz für die Aufrufe aus app/bootstrap.py."""

    def __init__(self):
        self.superusers = {"admin@example.org": "su-pass"}
        self.users: dict[str, dict] = {}
        self.tokens: list[dict] = []
        self.settings: dict[str, dict] = {}
        self.alerts: list[dict] = []
        self.calls: list[str] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path, method = request.url.path, request.method
        self.calls.append(f"{method} {path}")
        body = json.loads(request.content) if request.content else {}
        if path == "/api/collections/_superusers/auth-with-password":
            ok = self.superusers.get(body["identity"]) == body["password"]
            return httpx.Response(200, json={"token": "su-token"}) if ok else httpx.Response(400, json={})
        if path == "/api/collections/users/auth-with-password":
            u = next((u for u in self.users.values() if u["email"] == body["identity"]), None)
            if u and u["password"] == body["password"]:
                return httpx.Response(200, json={"token": f"user-token-{u['id']}"})
            return httpx.Response(400, json={})
        if path == "/api/collections/users/records" and method == "GET":
            email = request.url.params["filter"].split("'")[1]
            return httpx.Response(200, json={"items": [u for u in self.users.values() if u["email"] == email]})
        if path == "/api/collections/users/records" and method == "POST":
            uid = f"u{len(self.users) + 1}"
            self.users[uid] = {"id": uid, "email": body["email"], "password": body["password"], "role": body["role"]}
            return httpx.Response(200, json=self.users[uid])
        if path.startswith("/api/collections/users/records/") and method == "PATCH":
            u = self.users[path.rsplit("/", 1)[-1]]
            u.update(password=body["password"], role=body["role"])
            return httpx.Response(200, json=u)
        if path == "/api/collections/universal_tokens/records" and method == "GET":
            uid = request.url.params["filter"].split("'")[1]
            return httpx.Response(200, json={"items": [t for t in self.tokens if t["user"] == uid]})
        if path == "/api/collections/universal_tokens/records" and method == "POST":
            self.tokens.append(body)
            return httpx.Response(200, json=body)
        if path == "/api/collections/user_settings/records" and method == "GET":
            uid = request.url.params["filter"].split("'")[1]
            return httpx.Response(200, json={"items": [v for v in self.settings.values() if v["user"] == uid]})
        if path == "/api/collections/user_settings/records" and method == "POST":
            rid = f"s{len(self.settings) + 1}"
            email = next(u["email"] for u in self.users.values() if u["id"] == body["user"])
            # echtes Beszel-Verhalten: beim Anlegen werden die Werte durch Vorgaben ersetzt
            self.settings[rid] = {"id": rid, "user": body["user"], "settings": {"chartTime": "1h", "emails": [email]}}
            return httpx.Response(200, json=self.settings[rid])
        if path.startswith("/api/collections/user_settings/records/") and method == "PATCH":
            rec = self.settings[path.rsplit("/", 1)[-1]]
            rec["settings"] = body["settings"]
            return httpx.Response(200, json=rec)
        if path == "/api/collections/alerts/records" and method == "GET":
            f = request.url.params["filter"]
            sid, uid = f.split("'")[1], f.split("'")[3]
            return httpx.Response(200, json={"items": [a for a in self.alerts if a["system"] == sid and a["user"] == uid]})
        if path == "/api/collections/alerts/records" and method == "POST":
            self.alerts.append(body)
            return httpx.Response(200, json=body)
        if path == "/api/beszel/getkey":
            return httpx.Response(200, json={"key": "ssh-ed25519 AAAAhubkey", "v": "0.21.2"})
        return httpx.Response(404, json={})


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(bootstrap, "DATA", tmp_path / "data")
    monkeypatch.setattr(bootstrap, "BOOTSTRAP_DIR", tmp_path / "bootstrap")
    (tmp_path / "data").mkdir()
    (tmp_path / "bootstrap").mkdir()
    return tmp_path


def run(fake, **kw):
    async def go():
        async with httpx.AsyncClient(base_url="http://beszel", transport=httpx.MockTransport(fake.handler)) as cli:
            return await bootstrap.setup_beszel("http://beszel", "admin@example.org", "su-pass", client=cli, **kw)

    return asyncio.run(go())


def test_setup_creates_users_token_and_key(dirs):
    fake = FakeBeszel()
    result = run(fake)
    roles = sorted(u["role"] for u in fake.users.values())
    assert roles == ["admin", "readonly"]
    assert result["user"] == "quietboard-app@example.org"
    assert result["hub_key"].startswith("ssh-ed25519")
    assert len(fake.tokens) == 1 and fake.tokens[0]["token"] == result["agent_token"]
    saved = dirs / "data" / "beszel.json"
    assert json.loads(saved.read_text()) == result
    assert stat.S_IMODE(saved.stat().st_mode) == 0o600


def test_second_run_changes_nothing(dirs):
    fake = FakeBeszel()
    first = run(fake)
    fake.calls.clear()
    second = run(fake)
    assert second == first
    assert fake.calls == ["POST /api/collections/users/auth-with-password"]  # nur Login-Prüfung
    assert len(fake.tokens) == 1


def test_existing_token_is_reused(dirs):
    fake = FakeBeszel()
    first = run(fake)
    (dirs / "data" / "beszel.json").unlink()  # App-Volume verloren
    second = run(fake)
    assert second["agent_token"] == first["agent_token"]
    assert len(fake.tokens) == 1


def test_load_prefers_environment(dirs):
    (dirs / "bootstrap" / "healthchecks.json").write_text(json.dumps({"api_key": "hcw_file", "ping_key": "pk"}))
    creds = bootstrap.load({"HC_API_KEY": "hcw_env"})
    assert creds.hc_api_key == "hcw_env"
    assert creds.hc_ping_key == "pk"


def test_ensure_reports_missing_admin(dirs):
    creds = asyncio.run(bootstrap.ensure(bootstrap.Credentials(), env={}))
    assert "healthchecks" in creds.errors and "beszel" in creds.errors


def run_alerts(fake, ids, webhook="generic://status:8080/api/ingest/beszel?template=json"):
    async def go():
        async with httpx.AsyncClient(base_url="http://beszel", transport=httpx.MockTransport(fake.handler)) as cli:
            return await bootstrap.ensure_beszel_alerts("http://beszel", "admin@example.org", "su-pass", ids, webhook, 5, client=cli)

    return asyncio.run(go())


def test_alerts_webhook_and_defaults(dirs):
    fake = FakeBeszel()
    run(fake)  # Admin anlegen
    done = run_alerts(fake, {"sys1", "sys2"})
    assert done == {"sys1", "sys2"}
    rec = next(iter(fake.settings.values()))["settings"]
    assert rec["webhooks"] == ["generic://status:8080/api/ingest/beszel?template=json"]
    assert rec["emails"] == []  # Mails verschickt die App, nicht Beszel
    names = sorted((a["system"], a["name"], a["min"]) for a in fake.alerts)
    assert ("sys1", "Status", 5) in names and ("sys2", "Disk", 10) in names
    assert len(fake.alerts) == 6


def test_alerts_idempotent_and_keep_user_settings(dirs):
    fake = FakeBeszel()
    run(fake)
    run_alerts(fake, {"sys1"})
    rec = next(iter(fake.settings.values()))
    rec["settings"]["webhooks"].append("ntfy://eigener-kanal")  # vom Nutzer ergänzt
    fake.alerts = [a for a in fake.alerts if a["name"] != "Memory"]  # vom Nutzer gelöscht … wird ergänzt
    run_alerts(fake, {"sys1"})
    assert rec["settings"]["webhooks"] == ["generic://status:8080/api/ingest/beszel?template=json", "ntfy://eigener-kanal"]
    assert sorted(a["name"] for a in fake.alerts) == ["Disk", "Memory", "Status"]


def test_alerts_done_is_persisted(dirs):
    fake = FakeBeszel()
    run(fake)
    bootstrap.mark_alerts_done({"sys1"})
    bootstrap.mark_alerts_done({"sys2"})
    assert bootstrap.alerts_done() == {"sys1", "sys2"}


def test_alerts_keep_existing_app_webhook_of_predecessor(dirs):
    """Übernahme: Ein vorhandener Webhook zur App (alter Containername) wird nicht verdoppelt."""
    fake = FakeBeszel()
    run(fake)
    run_alerts(fake, {"sys1"}, webhook="generic://status-app:8080/api/ingest/beszel?template=json")
    run_alerts(fake, {"sys2"})  # QuietBoard mit seinem eigenen Webhook-Namen
    rec = next(iter(fake.settings.values()))["settings"]
    assert rec["webhooks"] == ["generic://status-app:8080/api/ingest/beszel?template=json"]
