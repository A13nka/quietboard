"""Lokale Konten: Einrichtungscode, Anmeldung, Rollen, Sitzungen und Zugriffsschutz der Oberfläche."""

import pytest
from fastapi.testclient import TestClient

from app import auth, main

PW = "richtig-langes-passwort"


@pytest.fixture
def store(tmp_path):
    return auth.Store(tmp_path / "qb.db")


@pytest.fixture
def client(store, monkeypatch):
    monkeypatch.setattr(main, "STORE", store)
    monkeypatch.setattr(main, "ALLOW_NO_AUTH", False)
    return TestClient(main.app, base_url="http://qb.test")


def setup_admin(client, store):
    code = store.ensure_setup_code()
    r = client.post("/api/auth/setup", json={"code": code, "email": "Admin@Example.org", "password": PW})
    assert r.status_code == 200, r.text
    return r


# ------------------------------------------------------------ Store
def test_password_hash_roundtrip():
    h = auth.hash_password(PW)
    assert h.startswith("scrypt$") and PW not in h
    assert auth.verify_password(PW, h)
    assert not auth.verify_password("falsch-falsch", h)


def test_setup_code_only_without_users(store):
    code = store.ensure_setup_code()
    assert code and len(code) == 9 and code[4] == "-"
    with pytest.raises(auth.AuthError):
        store.complete_setup("AAAA-AAAA", "a@example.org", PW)
    store.complete_setup(code.lower().replace("-", ""), "a@example.org", PW)  # Groß/Klein und Bindestrich egal
    assert store.ensure_setup_code() is None
    with pytest.raises(auth.AuthError):
        store.complete_setup(code, "b@example.org", PW)


def test_login_rate_limit(store):
    store.create_user("a@example.org", PW, "admin")
    for _ in range(10):
        with pytest.raises(auth.AuthError):
            store.login("a@example.org", "falsch-falsch", "1.2.3.4")
    with pytest.raises(auth.AuthError, match="Zu viele"):
        store.login("a@example.org", PW, "1.2.3.4")
    assert store.login("a@example.org", PW, "5.6.7.8")["email"] == "a@example.org"


def test_last_admin_and_self_protection(store):
    a = store.create_user("a@example.org", PW, "admin")
    v = store.create_user("v@example.org", PW, "viewer")
    with pytest.raises(auth.AuthError):
        store.delete_user(a["id"], v["id"])  # letzter Admin
    with pytest.raises(auth.AuthError):
        store.set_role(a["id"], "viewer", a["id"])  # sich selbst degradieren
    store.delete_user(v["id"], a["id"])
    assert [u["email"] for u in store.list_users()] == ["a@example.org"]


def test_short_password_rejected(store):
    with pytest.raises(auth.AuthError, match="zu kurz"):
        store.create_user("a@example.org", "kurz", "admin")


# ------------------------------------------------------------ Oberfläche und API
def test_fresh_install_redirects_to_setup(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/setup"
    r = client.get("/api/state")
    assert r.status_code == 401 and r.json()["setup"] is True


def test_setup_logs_in_and_sets_mail_recipient(client, store):
    r = setup_admin(client, store)
    assert "httponly" in r.headers["set-cookie"].lower()
    assert client.get("/api/state").status_code == 200
    assert client.get("/api/auth/state").json()["user"]["role"] == "admin"
    assert store.get_setting("mail_to") == ["admin@example.org"]
    assert client.get("/setup", follow_redirects=False).headers["location"] == "/login"


def test_logout_ends_session(client, store):
    setup_admin(client, store)
    assert client.post("/api/auth/logout", headers={"Origin": "http://qb.test"}).status_code == 200
    assert client.get("/api/state").status_code == 401
    assert client.get("/", follow_redirects=False).headers["location"] == "/login"


def test_viewer_cannot_use_admin_functions(client, store):
    setup_admin(client, store)
    client.post("/api/users", json={"email": "v@example.org", "password": PW, "role": "viewer"}, headers={"Origin": "http://qb.test"})
    viewer = TestClient(main.app, base_url="http://qb.test")
    assert viewer.post("/api/auth/login", json={"email": "v@example.org", "password": PW}).status_code == 200
    assert viewer.get("/api/state").status_code == 200
    for method, path in [
        ("GET", "/api/users"),
        ("GET", "/api/hosts/install-command"),
        ("GET", "/api/agent"),
        ("POST", "/api/digest/test"),
        ("PUT", "/api/settings"),
    ]:
        r = viewer.request(method, path, json={}, headers={"Origin": "http://qb.test"})
        assert r.status_code == 403, (method, path, r.status_code)


def test_foreign_origin_rejected(client, store):
    setup_admin(client, store)
    r = client.put("/api/settings", json={"digest_time": "06:30"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.put("/api/settings", json={"digest_time": "06:30"}, headers={"Origin": "http://qb.test"})
    assert r.status_code == 200 and r.json()["digest_time"] == "06:30"


def test_wrong_login_message_is_generic(client, store):
    setup_admin(client, store)
    other = TestClient(main.app, base_url="http://qb.test")
    a = other.post("/api/auth/login", json={"email": "admin@example.org", "password": "falsch-falsch"})
    b = other.post("/api/auth/login", json={"email": "gibts@nicht.org", "password": "falsch-falsch"})
    assert a.status_code == b.status_code == 401 and a.json() == b.json()


def test_settings_validation(client, store):
    setup_admin(client, store)
    h = {"Origin": "http://qb.test"}
    assert client.put("/api/settings", json={"digest_time": "25:00"}, headers=h).status_code == 400
    assert client.put("/api/settings", json={"mail_to": "kaputt"}, headers=h).status_code == 400
    r = client.put("/api/settings", json={"mail_to": "a@example.org, b@example.org"}, headers=h)
    assert r.json()["mail_to"] == ["a@example.org", "b@example.org"]


def test_public_paths_stay_public(client):
    assert client.get("/login").status_code == 200
    assert client.get("/api/auth/state").status_code == 200
    assert client.post("/api/ingest/updates", json={}).status_code == 401  # eigener Token, nicht Login


def test_cli_add_and_reset(tmp_path, monkeypatch, capsys):
    from tools import cli

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert cli.main(["--json", "add", "a@example.org", "--role", "admin"]) == 0
    pw1 = __import__("json").loads(capsys.readouterr().out)["password"]
    assert cli.main(["--json", "passwd", "a@example.org"]) == 0
    pw2 = __import__("json").loads(capsys.readouterr().out)["password"]
    store = auth.Store(tmp_path / "quietboard.db")
    assert pw1 != pw2
    assert store.login("a@example.org", pw2, "x")["role"] == "admin"
    assert cli.main(["users"]) == 0 and "a@example.org" in capsys.readouterr().out


# ------------------------------------------------------------ API-Tokens
def test_api_token_lifecycle(client, store):
    setup_admin(client, store)
    origin = {"Origin": "http://qb.test"}
    r = client.post("/api/tokens", json={"name": "Skript"}, headers=origin)
    assert r.status_code == 200, r.text
    token = r.json()["token"]
    assert token.startswith("qb_") and token not in str(store.list_api_tokens())  # nur der Hash liegt in der DB
    bare = TestClient(main.app, base_url="http://qb.test")  # ohne Cookie
    auth_h = {"Authorization": f"Bearer {token}"}
    assert bare.get("/api/state", headers=auth_h).status_code == 200
    assert bare.post("/api/tokens", json={"name": "x"}, headers=auth_h).status_code == 403  # Token legt keine Tokens an
    assert bare.get("/api/state", headers={"Authorization": "Bearer qb_falsch"}).status_code == 401
    tid = client.get("/api/tokens").json()["tokens"][0]["id"]
    assert client.delete(f"/api/tokens/{tid}", headers=origin).status_code == 200
    assert bare.get("/api/state", headers=auth_h).status_code == 401


def test_viewer_token_has_viewer_rights(client, store):
    setup_admin(client, store)
    viewer = store.create_user("v@example.org", PW, "viewer")
    token, _ = store.create_api_token(viewer["id"], "nur lesen")
    bare = TestClient(main.app, base_url="http://qb.test")
    h = {"Authorization": f"Bearer {token}"}
    assert bare.get("/api/state", headers=h).status_code == 200
    assert bare.get("/api/hosts/install-command", headers=h).status_code == 403
    store.delete_user(viewer["id"], acting_uid=1)
    assert bare.get("/api/state", headers=h).status_code == 401  # Tokens gelöschter Benutzer gelten nicht mehr


def test_host_settings_override_and_validation(client, store):
    setup_admin(client, store)
    origin = {"Origin": "http://qb.test"}
    r = client.put(
        "/api/hosts/nas/settings", json={"always_on": False, "links": [{"label": "x", "url": "javascript:alert(1)"}]}, headers=origin
    )
    assert r.status_code == 400
    r = client.put(
        "/api/hosts/nas/settings", json={"always_on": False, "links": [{"label": "NAS", "url": "https://nas.home.arpa"}]}, headers=origin
    )
    assert r.status_code == 200
    assert main.host_extra("nas") == {
        "always_on": False,
        "links": [{"label": "NAS", "url": "https://nas.home.arpa", "vpn": True}],
        "custom": True,
    }


def test_last_admin_cannot_be_demoted_even_by_access_admin(tmp_path):
    """Admins ohne lokales Konto (Access, acting_uid=0) konnten früher alle lokalen Admins herabstufen."""
    st = auth.Store(tmp_path / "a.db")
    u = st.create_user("admin@example.org", "langes-passwort-1", "admin")
    with pytest.raises(auth.AuthError):
        st.set_role(u["id"], "viewer", 0)
    v = st.create_user("zwei@example.org", "langes-passwort-2", "admin")
    assert st.set_role(v["id"], "viewer", 0)["role"] == "viewer"
