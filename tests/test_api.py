import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import demo, main

AUTH = {"Authorization": "Bearer test-token"}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(main, "ALLOW_NO_AUTH", True)
    main.updates.clear()
    main.flags.clear()
    return TestClient(main.app)  # ohne Kontextmanager: keine Hintergrund-Tasks


def test_ui_requires_login_by_default(monkeypatch):
    monkeypatch.setattr(main, "ALLOW_NO_AUTH", False)
    r = TestClient(main.app).get("/api/state")
    assert r.status_code == 401


def test_ingest_requires_token(client):
    assert client.post("/api/ingest/updates", json={"host": "x"}).status_code == 401


def test_ingest_updates_and_state(client):
    body = {"host": "web01", "kind": "apt", "reboot": True, "items": [{"pkg": "openssl", "from": "1", "to": "2", "security": True}]}
    r = client.post("/api/ingest/updates", json=body, headers=AUTH)
    assert r.status_code == 200 and r.json()["count"] == 1
    hu = {h["host"]: h for h in client.get("/api/state").json()["host_updates"]}
    assert hu["web01"]["security"] == 1
    assert hu["web01"]["reboot"] is True


def test_ingest_empty_report_clears_host(client):
    client.post("/api/ingest/updates", json={"host": "web01", "items": [{"pkg": "a"}]}, headers=AUTH)
    client.post("/api/ingest/updates", json={"host": "web01", "items": []}, headers=AUTH)
    assert "web01|apt" not in main.updates


def test_ingest_error_keeps_last_report(client):
    """apt kaputt: letzter Stand bleibt, Fehler steht in „Achtung“; der nächste gute Bericht räumt ihn ab."""
    client.post("/api/ingest/updates", json={"host": "web01", "items": [{"pkg": "a", "to": "2"}]}, headers=AUTH)
    r = client.post("/api/ingest/updates", json={"host": "web01", "kind": "apt", "error": "dpkg kaputt"}, headers=AUTH)
    assert r.status_code == 200
    assert main.updates["web01|apt"]["items"][0]["pkg"] == "a"
    assert "dpkg kaputt" in main.report_problems()["web01"]
    assert any(a["kind"] == "update" and "web01" in a["title"] for a in main.attention())
    client.post("/api/ingest/updates", json={"host": "web01", "kind": "apt", "reboot": False, "items": []}, headers=AUTH)
    assert "web01" not in main.report_problems()


def test_stale_report_only_for_known_always_on_hosts(client, monkeypatch):
    old = (main.now() - dt.timedelta(hours=main.REPORT_STALE_H + 1)).isoformat(timespec="seconds")
    main.flags.update({"web01": {"reported": old}, "weg": {"reported": old}})
    monkeypatch.setitem(main.state, "hosts", [{"name": "web01", "status": "up"}])
    probs = main.report_problems()
    assert "veraltet" in probs["web01"] and "weg" not in probs
    main.flags["web01"]["reported"] = main.now().isoformat(timespec="seconds")
    assert main.report_problems() == {}


def test_notify_without_signal_does_not_fail(client):
    r = client.post("/api/ingest/notify", json={"title": "Backup fehlgeschlagen", "message": "rc=1"}, headers=AUTH)
    assert r.status_code == 200
    assert main.events[0]["prio"] == "normal"  # Fehlerwort erkannt


def test_demo_data_fills_state():
    state = {"checks": [], "hosts": [], "pbs": {}, "errors": {"x": "y"}}
    updates, flags, events = {}, {}, []
    demo._applied = False
    demo.apply(state, updates, flags, events, dt.datetime.now(dt.UTC))
    assert state["checks"] and state["hosts"] and updates and events
    assert state["errors"] == {}


def test_beszel_webhook_rejects_lan_clients_without_token(client):
    """Früher reichte jede private Absenderadresse – jetzt nur Beszel-Container oder Token."""
    r = client.post("/api/ingest/beszel", json={"title": "CPU", "message": "hoch"})
    assert r.status_code == 401


def test_beszel_webhook_accepts_token(client):
    r = client.post("/api/ingest/beszel?token=test-token", json={"title": "CPU", "message": "hoch"})
    assert r.status_code == 200


def test_beszel_webhook_accepts_beszel_container(client, monkeypatch):
    monkeypatch.setattr(main, "_resolve", lambda host: {"testclient"})
    r = client.post("/api/ingest/beszel", json={"title": "Disk", "message": "voll"})
    assert r.status_code == 200


def _install_script(client, monkeypatch):
    monkeypatch.setattr(main.CREDS, "hc_ping_key", "pingkey123")
    monkeypatch.setattr(main.CREDS, "agent_token", "tok'en$1")  # Sonderzeichen müssen sicher ankommen
    monkeypatch.setattr(main.CREDS, "hub_key", "ssh-ed25519 AAAAhub")
    return client.get("/api/install/host.sh", headers=AUTH)


def test_install_script_requires_token(client):
    assert client.get("/api/install/host.sh").status_code == 401


def test_install_script_values_and_override(client, monkeypatch, tmp_path):
    import subprocess

    r = _install_script(client, monkeypatch)
    assert r.status_code == 200
    # Root-Weg erzwingen und statt der Installation die Werte ausgeben
    script = r.text.replace('if [ "$(id -u)" = 0 ]; then', "if true; then")
    script = script.replace('  bash "$QB_FILES/install-host.sh"', '  env | grep ^QB_ | sort; ls "$QB_FILES"')
    path = tmp_path / "host.sh"
    path.write_text(script)
    assert subprocess.run(["bash", "-n", str(path)]).returncode == 0
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, env={"PATH": "/usr/bin:/bin", "QB_HUB_URL": "http://x:1"})
    assert out.returncode == 0, out.stderr
    assert "QB_PING_KEY=pingkey123" in out.stdout
    assert "QB_AGENT_TOKEN=tok'en$1" in out.stdout
    assert "QB_AGENT_KEY=ssh-ed25519 AAAAhub" in out.stdout
    assert "QB_HUB_URL=http://x:1" in out.stdout  # vom Aufrufer überschrieben
    assert "QB_INGEST_URL=http://testserver/api/ingest/updates" in out.stdout
    for name in main.HOST_FILES:
        assert name in out.stdout


def test_install_script_uses_sudo_for_normal_users(client, monkeypatch, tmp_path):
    """Ohne root: Rechte per sudo; die QB_*-Werte gehen als Datei mit (nicht in der Prozessliste), auch mit Sonderzeichen."""
    import subprocess

    r = _install_script(client, monkeypatch)
    script = r.text.replace('if [ "$(id -u)" = 0 ]; then', "if false; then")
    (tmp_path / "bin").mkdir()
    fake_sudo = tmp_path / "bin" / "sudo"
    fake_sudo.write_text(
        '#!/bin/bash\necho "ARGS:$*"; ls -l "$4" | cut -c1-10; . "$4"\necho "KEY=$QB_AGENT_KEY"; echo "TOK=$QB_AGENT_TOKEN"\n'
    )
    fake_sudo.chmod(0o755)
    path = tmp_path / "host.sh"
    path.write_text(script)
    out = subprocess.run(["bash", str(path)], capture_output=True, text=True, env={"PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"})
    assert out.returncode == 0, out.stderr
    args = next(ln for ln in out.stdout.splitlines() if ln.startswith("ARGS:"))
    assert args.startswith("ARGS:bash ") and "/install-host.sh --env " in args
    assert "tok" not in args and "AAAA" not in args
    assert "-rw-------" in out.stdout
    assert "KEY=ssh-ed25519 AAAAhub" in out.stdout
    assert "TOK=tok'en$1" in out.stdout


@pytest.mark.parametrize(
    ("now_hm", "sent", "due"),
    [
        ("06:59", None, False),
        ("07:00", None, True),
        ("08:59", None, True),
        ("09:00", None, False),
        ("22:22", None, False),
        ("07:30", "2026-11-24", False),
    ],
)
def test_digest_only_in_window(now_hm, sent, due):
    h, m = map(int, now_hm.split(":"))
    current = dt.datetime(2026, 11, 24, h, m)
    assert main.digest_due("07:00", current, sent) is due


def test_host_updates_list_each_kind_once(monkeypatch):
    """Mehrere Docker-Image-Berichte eines Hosts ergeben ein Schild „docker“, nicht zwei."""
    from app import main

    item = {"pkg": "img", "from": "1", "to": "2", "security": False, "since": "2026-01-01T00:00:00+00:00"}
    monkeypatch.setattr(
        main,
        "updates",
        {
            "d1|docker:a": {"host": "d1", "kind": "docker", "checked": "", "items": [item]},
            "d1|docker:b": {"host": "d1", "kind": "docker", "checked": "", "items": [item]},
            "d1|apt": {"host": "d1", "kind": "apt", "checked": "", "items": [item]},
        },
    )
    h = next(x for x in main.host_updates() if x["host"] == "d1")
    assert h["kinds"] == ["docker", "apt"] and h["packages"] == 3


def test_user_routes_unknown_id_is_404(client):
    assert client.patch("/api/users/999", json={"role": "viewer"}).status_code == 404
    assert client.delete("/api/users/999").status_code == 404


def test_corrupt_data_file_is_kept_aside(tmp_path, monkeypatch, caplog):
    monkeypatch.setattr(main, "DATA", tmp_path)
    (tmp_path / "events.json").write_text("{kaputt")
    assert main._load("events.json", []) == []
    assert not (tmp_path / "events.json").exists()
    assert list(tmp_path.glob("events.json.kaputt-*"))
    main._save("events.json", [{"a": 1}])
    assert main._load("events.json", []) == [{"a": 1}]


@pytest.mark.parametrize(
    "body",
    [{}, {"host": 5}, {"host": "a b"}, {"host": "web01", "items": "x"}, [1, 2], "text"],
)
def test_ingest_updates_bad_input_is_400(client, body):
    assert client.post("/api/ingest/updates", json=body, headers=AUTH).status_code == 400


def test_ingest_updates_skips_non_object_items(client):
    r = client.post("/api/ingest/updates", json={"host": "web01", "items": ["x", {"pkg": "a", "to": "2"}]}, headers=AUTH)
    assert r.status_code == 200 and r.json()["count"] == 1


@pytest.mark.parametrize("path", ["/api/ingest/notify", "/api/ingest/pve", "/api/ingest/signal/test-token"])
@pytest.mark.parametrize("body", [[1, 2], "nur text", 42])
def test_ingest_odd_bodies_do_not_crash(client, path, body):
    assert client.post(path, json=body, headers=AUTH).status_code == 200


def test_push_subscribe_bad_body_is_400(client):
    assert client.post("/api/push/subscribe", json=[1]).status_code == 400
    assert client.post("/api/push/subscribe", json={"endpoint": 5}).status_code == 400


def test_push_subscriptions_limited_per_account(client, monkeypatch):
    monkeypatch.setattr(main.push, "valid_subscription", lambda sub: True)
    monkeypatch.setattr(main, "push_subs", {})
    monkeypatch.setattr(main, "_save", lambda *a: None)
    for i in range(main.PUSH_PER_USER):
        assert client.post("/api/push/subscribe", json={"endpoint": f"https://web.push.apple.com/{i}", "keys": {}}).status_code == 200
    assert client.post("/api/push/subscribe", json={"endpoint": "https://web.push.apple.com/x", "keys": {}}).status_code == 400
    # dasselbe Gerät erneut anmelden geht weiter
    assert client.post("/api/push/subscribe", json={"endpoint": "https://web.push.apple.com/0", "keys": {}}).status_code == 200


def test_user_error_has_template_and_args(client):
    r = client.post("/api/config/import", json={"yaml": "a: [unclosed"})
    assert r.status_code == 400
    j = r.json()
    assert j["msg"] == "YAML fehlerhaft: {e}" and j["detail"].startswith("YAML fehlerhaft: ") and "e" in j["args"]


def test_hc_error_with_msg_placeholder():
    """Platzhalter dürfen wie Parameter heißen (früher: TypeError bei {msg})."""
    import httpx

    resp = httpx.Response(400, json={"error": "invalid cron"}, request=httpx.Request("POST", "http://hc/api"))
    e = main._hc_error(httpx.HTTPStatusError("x", request=resp.request, response=resp))
    assert e.status_code == 400 and e.detail == "Healthchecks lehnt ab: invalid cron" and e.msg_args == {"msg": "invalid cron"}


def test_switch_back_to_hc_gives_channelless_jobs_their_integrations(client, monkeypatch):
    """Review 3b H2: Jobs aus dem Modus „QuietBoard“ blieben nach dem Zurückschalten ohne Integration."""
    calls = []

    class R:
        def __init__(self, j):
            self._j = j

        def json(self):
            return self._j

    checks = [
        {"uuid": "11111111-1111-1111-1111-111111111111", "tags": "host:web01 prio:normal", "channels": ""},
        {"uuid": "22222222-2222-2222-2222-222222222222", "tags": "host:web01 prio:normal", "channels": "c1"},
        {"uuid": "33333333-3333-3333-3333-333333333333", "tags": "host:quietboard src:app", "channels": ""},
    ]

    async def fake_hc(method, path, **kw):
        calls.append((method, path, kw.get("json")))
        if path == "/api/v3/checks/":
            return R({"checks": checks})
        if path == "/api/v3/channels/":
            return R({"channels": [{"name": "E-Mail", "id": "mail-id"}]})
        return R({})

    monkeypatch.setattr(main, "_hc", fake_hc)
    main.STORE.set_setting("job_alerts", "app")
    try:
        assert client.put("/api/settings", json={"job_alerts": "hc"}).status_code == 200
    finally:
        main.STORE.set_setting("job_alerts", None)
    posts = [c for c in calls if c[0] == "POST"]
    assert posts == [("POST", "/api/v3/checks/11111111-1111-1111-1111-111111111111", {"channels": "mail-id"})]


def test_deleting_user_removes_their_push_devices(client, monkeypatch):
    monkeypatch.setattr(main, "_save", lambda *a: None)
    u = main.STORE.create_user("weg@example.org", "langes-passwort-9", "viewer")
    monkeypatch.setattr(main, "push_subs", {"https://a/1": {"owner": "weg@example.org"}, "https://a/2": {"owner": "bleibt@example.org"}})
    assert client.delete(f"/api/users/{u['id']}").status_code == 200
    assert list(main.push_subs) == ["https://a/2"]
