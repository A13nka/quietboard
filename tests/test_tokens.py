"""Tokens je Host und Installer-Token (v0.9): wer darf was, und das gemeinsame Token bleibt abwärtskompatibel."""

import time

import pytest
from fastapi.testclient import TestClient

from app import main

LEGACY = {"Authorization": "Bearer test-token"}


def bearer(t):
    return {"Authorization": f"Bearer {t}"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ALLOW_NO_AUTH", True)
    monkeypatch.setattr(main.CREDS, "hc_ping_key", "pingkey123")
    monkeypatch.setattr(main.CREDS, "agent_token", "agenttok")
    monkeypatch.setattr(main.CREDS, "hub_key", "ssh-ed25519 AAAAhub")
    main.updates.clear()
    main.flags.clear()
    main.STORE.set_setting("legacy_ingest_token", True)
    yield TestClient(main.app)
    main.STORE.set_setting("legacy_ingest_token", True)
    for t in main.STORE.list_host_tokens():
        main.STORE.delete_host_token(t["host"])


def register(client, host, auth=LEGACY):
    r = client.post("/api/install/register", json={"host": host}, headers=auth)
    assert r.status_code == 200, r.text
    return r.json()["token"]


def report(client, host, auth):
    return client.post("/api/ingest/updates", json={"host": host, "items": []}, headers=auth)


def test_host_token_only_for_own_name(client):
    tok = register(client, "web01")
    assert tok.startswith("qbh_")
    assert report(client, "web01", bearer(tok)).status_code == 200
    r = report(client, "pve", bearer(tok))
    assert r.status_code == 403 and r.json()["args"] == {"host": "web01"}


def test_host_token_cannot_load_installer_or_register(client):
    tok = register(client, "web01")
    assert client.get("/api/install/host.sh", headers=bearer(tok)).status_code == 403
    assert client.post("/api/install/register", json={"host": "pve"}, headers=bearer(tok)).status_code == 403


def test_host_token_works_for_messages_and_bridge(client):
    tok = register(client, "web01")
    assert client.post("/api/ingest/notify", json={"title": "x", "message": "y"}, headers=bearer(tok)).status_code == 200
    assert client.post(f"/api/ingest/signal/{tok}/v2/send", json={"message": "hi"}).status_code == 200


def test_reregister_invalidates_old_token(client):
    old = register(client, "web01")
    new = register(client, "web01")
    assert report(client, "web01", bearer(old)).status_code == 401
    assert report(client, "web01", bearer(new)).status_code == 200


def test_installer_token_loads_installer_without_shared_token(client):
    tok, _ = main.STORE.create_installer_token("admin@example.org")
    r = client.get("/api/install/host.sh", headers=bearer(tok))
    assert r.status_code == 200
    assert "test-token" not in r.text  # das gemeinsame Token steckt nicht im Installer
    assert "QB_INGEST_TOKEN=${QB_INGEST_TOKEN:-''}" in r.text
    assert "/api/install/register" in r.text
    host_tok = register(client, "neu01", bearer(tok))
    assert report(client, "neu01", bearer(host_tok)).status_code == 200


def test_installer_token_is_not_a_report_token(client):
    tok, _ = main.STORE.create_installer_token("admin")
    assert report(client, "web01", bearer(tok)).status_code == 401


def test_installer_token_expires(client):
    tok, _ = main.STORE.create_installer_token("admin", ttl=-1)
    assert client.get("/api/install/host.sh", headers=bearer(tok)).status_code == 401


def test_shared_token_still_works_and_can_be_switched_off(client):
    assert report(client, "web01", LEGACY).status_code == 200  # abwärtskompatibel
    host_tok = register(client, "web01")
    assert client.put("/api/settings", json={"legacy_ingest_token": False}).status_code == 200
    assert report(client, "web01", LEGACY).status_code == 401
    assert report(client, "web01", bearer(host_tok)).status_code == 200  # Host-Tokens gelten weiter
    cmd = client.get("/api/hosts/install-command").json()
    assert "qbi_" in cmd["command"] and cmd["expires"]


def test_shared_token_use_is_listed(client):
    main.legacy_use.clear()
    report(client, "web01", LEGACY)
    j = client.get("/api/host-tokens").json()
    assert j["legacy_allowed"] is True and any("/api/ingest/updates" in k for k in j["legacy_use"])


def test_admin_can_revoke_host_token(client):
    tok = register(client, "web01")
    assert client.delete("/api/host-tokens/web01").status_code == 200
    assert report(client, "web01", bearer(tok)).status_code == 401
    assert client.delete("/api/host-tokens/web01").status_code == 404


def test_installer_token_route_is_admin_only(client, monkeypatch):
    monkeypatch.setattr(main, "ALLOW_NO_AUTH", False)
    assert TestClient(main.app).post("/api/hosts/installer-token").status_code in (401, 403)


def test_host_token_last_used_is_noted(client):
    tok = register(client, "web01")
    report(client, "web01", bearer(tok))
    row = next(t for t in main.STORE.list_host_tokens() if t["host"] == "web01")
    assert row["last_used"] and row["last_used"] <= time.time()
