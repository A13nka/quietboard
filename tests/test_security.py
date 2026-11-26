"""Härtung: Zugriffsschutz, vertraute Proxys, Größenlimits, CSRF, Login-Sperre, Logs ohne Token."""

import asyncio
import logging
import secrets

import pytest
from fastapi.testclient import TestClient

from app import auth, main, security

AUTH = {"Authorization": "Bearer test-token"}
SAME = {"Sec-Fetch-Site": "same-origin"}
PLAIN = {"Sec-Fetch-Site": "same-origin", "Content-Type": "text/plain"}


@pytest.fixture
def anon(monkeypatch):
    """App mit Anmeldung (wie im Betrieb)."""
    monkeypatch.setattr(main, "ALLOW_NO_AUTH", False)
    return TestClient(main.app)


def _user(role="admin"):
    email = f"{secrets.token_hex(4)}@example.org"
    u = main.STORE.create_user(email, "geheim-geheim-1", role)
    return u, main.STORE.create_session(u["id"])


# ---------------------------------------------------------------- Host-Header (Pfad aus der URL)
@pytest.mark.parametrize("path", ["/api/state", "/api/settings", "/api/system", "/api/tokens"])
def test_host_header_cannot_reach_public_path(anon, path):
    assert anon.get(path, headers={"Host": "x/healthz?"}).status_code == 401
    assert anon.get(path, headers={"Host": "x/api/ingest/"}).status_code == 401


def test_push_subscribe_needs_login_even_with_crafted_host(anon):
    sub = {"endpoint": "https://fcm.googleapis.com/x", "keys": {"p256dh": "A" * 87, "auth": "A" * 22}}
    assert anon.post("/api/push/subscribe", json=sub, headers={"Host": "x/healthz?"}).status_code == 401


def test_route_guard_rejects_without_user():
    """Zweite Linie: unabhängig von der Middleware entscheidet die gewählte Route."""

    class R:
        def __init__(self, path, user):
            self.scope = {"route": type("Route", (), {"path": path})()}
            self.state = type("S", (), {"user": user})()

    with pytest.raises(main.HTTPException) as e:
        main._route_guard(R("/api/state", None))
    assert e.value.status_code == 401
    main._route_guard(R("/api/state", {"role": "viewer"}))
    main._route_guard(R("/healthz", None))
    main._route_guard(R("/api/ingest/updates", None))


# ---------------------------------------------------------------- Vertraute Proxys
def _through_shield(spec: str, client: str, headers: dict) -> dict:
    seen = {}

    async def app(scope, receive, send):
        seen.update(client=scope["client"][0], scheme=scope["scheme"], peer=scope["qb_peer"])

    mw = security.ShieldMiddleware(app, security.TrustedProxies(spec))
    scope = {
        "type": "http",
        "scheme": "http",
        "path": "/",
        "client": (client, 1234),
        "headers": [(k.encode(), v.encode()) for k, v in headers.items()],
    }
    asyncio.run(mw(scope, None, None))
    return seen


def test_forwarded_headers_ignored_from_untrusted_peer():
    s = _through_shield("172.30.0.0/24", "203.0.113.9", {"x-forwarded-for": "172.18.0.4", "x-forwarded-proto": "https"})
    assert s == {"client": "203.0.113.9", "scheme": "http", "peer": "203.0.113.9"}


def test_forwarded_headers_from_trusted_proxy():
    s = _through_shield("172.30.0.0/24", "172.30.0.5", {"x-forwarded-for": "1.2.3.4, 198.51.100.7", "x-forwarded-proto": "https"})
    assert s == {"client": "198.51.100.7", "scheme": "https", "peer": "172.30.0.5"}  # letzter Eintrag = vom Proxy
    s = _through_shield("172.30.0.0/24", "172.30.0.5", {"cf-connecting-ip": "198.51.100.8", "x-forwarded-for": "1.2.3.4"})
    assert s["client"] == "198.51.100.8"


def test_trusted_proxy_by_name(monkeypatch):
    monkeypatch.setattr(security.socket, "getaddrinfo", lambda name, port: [(0, 0, 0, "", ("172.30.0.9", 0))])
    assert "172.30.0.9" in security.TrustedProxies("cloudflared")
    assert "172.30.0.8" not in security.TrustedProxies("cloudflared")


def test_beszel_webhook_ignores_forwarded_for(monkeypatch):
    monkeypatch.setattr(main, "_resolve", lambda host: {"172.18.0.4"})
    c = TestClient(main.app)
    r = c.post("/api/ingest/beszel", json={"title": "x"}, headers={"X-Forwarded-For": "172.18.0.4"})
    assert r.status_code == 401


def test_login_lock_not_bypassed_by_forwarded_for(anon):
    u, _ = _user()
    for i in range(12):
        anon.post("/api/auth/login", json={"email": u["email"], "password": "falsch-falsch"}, headers={"X-Forwarded-For": f"10.0.0.{i}"})
    r = anon.post("/api/auth/login", json={"email": u["email"], "password": "geheim-geheim-1"}, headers={"X-Forwarded-For": "10.9.9.9"})
    assert r.status_code == 401 and "Zu viele" in r.json()["detail"]


# ---------------------------------------------------------------- Größenlimits, Speicher
def test_large_body_rejected_outside_ingest(anon):
    r = anon.post("/api/auth/login", content=b'{"email":"' + b"a" * 2_000_000 + b'"}', headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_large_ingest_body_is_truncated_not_rejected():
    c = TestClient(main.app)
    msg = "Backup fehlgeschlagen\n" + "x" * 5_000_000
    r = c.post("/api/ingest/notify", content=msg.encode(), headers=AUTH)
    assert r.status_code == 200  # gekürzt (kein JSON mehr) → als Text angenommen
    assert main.events[0]["title"] == "Backup fehlgeschlagen"


def test_failures_only_recorded_for_real_failures():
    s = auth.Store(main.DATA / f"t-{secrets.token_hex(3)}.db")
    s.create_user("a@example.org", "geheim-geheim-1", "admin")
    for _ in range(30):
        with pytest.raises(auth.AuthError):
            s.login("a@example.org", "falsch-falsch", "1.1.1.1")
    assert len(s._failures) == 3  # Adresse+Konto, Adresse, Konto – gesperrte Versuche legen nichts mehr an
    for i in range(50):
        with pytest.raises(auth.AuthError):
            s.login("x" * 300, "egal", f"2.2.2.{i}")  # zu lange E-Mail: sofort abgelehnt, nichts gemerkt
    assert len(s._failures) == 3


def test_failure_keys_are_capped(monkeypatch):
    monkeypatch.setattr(auth, "FAIL_KEYS_MAX", 20)
    monkeypatch.setattr(auth, "verify_password", lambda p, h: False)
    s = auth.Store(main.DATA / f"t-{secrets.token_hex(3)}.db")
    for i in range(100):
        with pytest.raises(auth.AuthError):
            s.login(f"u{i}@example.org", "falsch-falsch", f"3.3.{i}.1")
    assert len(s._failures) <= 20


def test_account_lock_independent_of_address():
    s = auth.Store(main.DATA / f"t-{secrets.token_hex(3)}.db")
    s.create_user("b@example.org", "geheim-geheim-1", "admin")
    for i in range(auth.FAIL_PER_ACCOUNT):
        with pytest.raises(auth.AuthError):
            s.login("b@example.org", "falsch-falsch", f"4.4.4.{i}")
    with pytest.raises(auth.AuthError, match="Zu viele"):
        s.login("b@example.org", "geheim-geheim-1", "5.5.5.5")


def test_setup_code_changes_after_too_many_tries():
    s = auth.Store(main.DATA / f"t-{secrets.token_hex(3)}.db")
    first = s.ensure_setup_code()
    for _ in range(auth.SETUP_CODE_TRIES):
        with pytest.raises(auth.AuthError):
            s.complete_setup("AAAA-AAAA", "c@example.org", "geheim-geheim-1")
    assert s.setup_code and s.setup_code != first


# ---------------------------------------------------------------- CSRF
def test_session_write_needs_same_origin(anon):
    _, tok = _user()
    anon.cookies.set(main.SESSION_COOKIE, tok)
    body = {"digest_time": "07:00"}
    assert anon.put("/api/settings", json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    assert anon.put("/api/settings", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    assert anon.put("/api/settings", json=body).status_code == 403  # gar keine Herkunftsangabe
    assert anon.put("/api/settings", json=body, headers=SAME).status_code == 200
    assert anon.put("/api/settings", json=body, headers={"Origin": "http://testserver"}).status_code == 200


def test_session_write_needs_json(anon):
    _, tok = _user()
    anon.cookies.set(main.SESSION_COOKIE, tok)
    r = anon.put("/api/settings", content=b'{"digest_time":"07:00"}', headers=PLAIN)
    assert r.status_code == 415


def test_access_user_also_checked_for_origin(anon, monkeypatch):
    monkeypatch.setattr(main, "_access_user", lambda r: {"id": 0, "email": "a@x", "role": "admin", "via": "access"})
    body = {"email": "neu@example.org", "password": "geheim-geheim-1"}
    assert anon.post("/api/users", json=body, headers={"Origin": "https://evil.example"}).status_code == 403
    r = anon.post(
        "/api/users",
        content=b'{"email":"neu2@example.org","password":"geheim-geheim-1"}',
        headers=PLAIN,
    )
    assert r.status_code == 415


def test_forwarded_host_accepted_from_trusted_proxy(monkeypatch):
    req = type("Q", (), {})()
    req.headers = {"origin": "https://status.example.org", "host": "status-app:8080"}
    req.scope = {"qb_forwarded_host": "status.example.org"}
    assert main._same_origin(req)
    req.scope = {"qb_forwarded_host": ""}
    assert not main._same_origin(req)
    monkeypatch.setattr(main, "PUBLIC_ORIGIN_HOSTS", {"status.example.org"})
    assert main._same_origin(req)


# ---------------------------------------------------------------- Sitzungen, Rechte, Header, Logs
def test_password_change_ends_other_sessions(anon):
    u, tok = _user()
    other = main.STORE.create_session(u["id"])
    anon.cookies.set(main.SESSION_COOKIE, tok)
    r = anon.post(
        "/api/auth/password", json={"old": "geheim-geheim-1", "new": "neues-passwort-2"}, headers={"Sec-Fetch-Site": "same-origin"}
    )
    assert r.status_code == 200
    assert main.STORE.session_user(tok) is not None
    assert main.STORE.session_user(other) is None


def test_push_test_admin_only(anon):
    _, tok = _user("viewer")
    anon.cookies.set(main.SESSION_COOKIE, tok)
    h = {"Sec-Fetch-Site": "same-origin"}
    assert anon.post("/api/push/test", headers=h).status_code == 403
    assert anon.post("/api/notify/test", json={"channel": "push"}, headers=h).status_code == 403


def test_security_headers(anon):
    r = anon.get("/healthz")
    assert r.headers["x-frame-options"] == "DENY"
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_access_log_masks_tokens():
    rec = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        "",
        0,
        '%s - "%s %s HTTP/%s" %d',
        ("1.2.3.4:5", "POST", "/api/ingest/signal/SECRET123/v2/send?token=SECRET456&prio=normal", "1.1", 200),
        None,
    )
    security.TokenFilter().filter(rec)
    line = rec.getMessage()
    assert "SECRET" not in line and "/api/ingest/signal/***/v2/send?token=***&prio=normal" in line


def test_ingest_token_compare():
    assert main._token_ok("test-token")
    assert not main._token_ok("test-tokenX", "", "nope")


def test_truncated_pve_event_still_counts_as_error():
    c = TestClient(main.app)
    raw = '{"severity": "error", "title": "vzdump backup failed", "message": "' + "log " * 1_200_000
    r = c.post("/api/ingest/pve?host=pve", content=raw.encode(), headers=AUTH)
    assert r.status_code == 200
    assert main.events[0]["prio"] == "normal" and "vzdump backup failed" in main.events[0]["title"]


def test_outgoing_request_log_hides_ping_key_and_push_endpoint(caplog):
    import httpx

    security.install_log_filter()
    lg = logging.getLogger("httpx")
    fmt = 'HTTP Request: %s %s "%s %d %s"'
    with caplog.at_level(logging.INFO, logger="httpx"):
        lg.info(fmt, "POST", httpx.URL("http://healthchecks:8000/ping/abcdefghijklmnopqrstuv/quietboard-app"), "HTTP/1.1", 200, "OK")
        lg.info(fmt, "POST", httpx.URL("https://web.push.apple.com/FAKEendpointAbCdEf"), "HTTP/1.1", 201, "Created")
        lg.info(fmt, "GET", httpx.URL("https://pbs.lan:8007/api2/json/status"), "HTTP/1.1", 200, "OK")
    text = caplog.text
    assert "abcdefghijklmnopqrstuv" not in text and "/ping/***/quietboard-app" in text
    assert "FAKEendpointAbCdEf" not in text and "https://web.push.apple.com/***" in text
    assert "https://pbs.lan:8007/api2/json/status" in text
