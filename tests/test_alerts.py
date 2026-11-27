"""v0.6.0 „Verlässliche Alarme“: Nachrichtenformat, Melde-Modus, Dedup, Kanäle, Import, Quellen."""

import asyncio
import datetime as dt
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from app import alerts, config, jobs, main, push

AUTH = {"Authorization": "Bearer test-token"}
UTC = dt.UTC
NOW = dt.datetime(2026, 11, 26, 8, 0, tzinfo=UTC)


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------- Nachrichtenformat
def test_when_today_yesterday_older():
    assert alerts.when("2026-11-26T03:12:00+00:00", NOW) == "heute 03:12"
    assert alerts.when("2026-11-25T03:04:00+00:00", NOW) == "gestern 03:04"
    assert alerts.when("2026-11-20T03:04:00+00:00", NOW) == "20.11. 03:04"
    assert alerts.when(None, NOW) == "nie"


def test_duration():
    assert alerts.duration(40) == "40 s"
    assert alerts.duration(14 * 60) == "14 min"
    assert alerts.duration(6 * 3600 + 12 * 60) == "6 h 12 min"


def _job(name="docker01/backup-restic", **kw):
    return {"uuid": "u-" + name, "name": name, "prio": "kritisch", "status": "down", "schedule": "0 3 * * *", "grace": 3600} | kw


def test_failed_job_message_with_exit_code_and_log():
    body = "start\nFatal: unable to open repository\nssh: connect to host nas port 22: No route to host\n[hc] exit 1, 840s\n"
    text, mail, url = alerts.down_message(
        [_job()], {"u-docker01/backup-restic": {"failed": True, "date": "2026-11-26T03:12:00+00:00", "body": body}}, NOW
    )
    lines = text.splitlines()
    assert lines[0] == "🔴 docker01/backup-restic fehlgeschlagen"
    assert lines[1] == "Exitcode 1 · heute 03:12 · kritisch"
    assert "  ssh: connect to host nas port 22: No route to host" in lines
    assert "[hc] exit" not in text
    assert url == "/?c=u-docker01/backup-restic" and "Letzte Zeilen:" in mail


def test_overdue_job_message():
    text, _, _ = alerts.down_message([_job(last_ping="2026-11-25T03:04:00+00:00")], {}, NOW)
    assert text.splitlines()[1].startswith("Keine Meldung seit gestern 03:04 (Zeitplan 0 3 * * *, Karenz 1h)")


def test_several_downs_are_bundled():
    js = [_job("nas/backup-pull"), _job("docker01/backup-restic"), _job("pve/vzdump")]
    infos = {"u-docker01/backup-restic": {"failed": True, "body": "[hc] exit 2, 1s"}}
    text, mail, url = alerts.down_message(js, infos, NOW, "https://status.example.org")
    assert text.splitlines()[0] == "🔴 3 Jobs ausgefallen"
    assert "• docker01/backup-restic – fehlgeschlagen" in text and "• nas/backup-pull – überfällig" in text
    assert url == "/?t=jobs" and text.endswith("→ https://status.example.org/?t=jobs")


def test_up_message_with_downtime():
    c = _job(status="up", last_duration=14 * 60)
    text, _ = alerts.up_message([c], {c["uuid"]: "2026-11-26T01:48:00+00:00"}, NOW)
    assert text == "✅ docker01/backup-restic wieder OK\nWar 6 h 12 min ausgefallen · Lauf dauerte 14 min"


# ---------------------------------------------------------------- Statuswechsel und Melde-Modus
@pytest.fixture
def transitions(monkeypatch):
    sent, pushed = [], []

    async def fake_send(text, dedup_key=None, url="/", fp=None, mail_text=None):
        sent.append(text)
        return fake_send.ok

    async def fake_push(title, body="", url="/", tag=None):
        pushed.append(title)
        return 1

    fake_send.ok = True
    monkeypatch.setattr(main, "send_signal", fake_send)
    monkeypatch.setattr(main, "push_all", fake_push)
    monkeypatch.setattr(main, "_last_ping_info", lambda uuid: asyncio.sleep(0, {}))
    monkeypatch.setattr(main, "_save", lambda *a: None)
    monkeypatch.setattr(main, "push_state", {"seed": "up"})  # kein „erster Lauf“
    monkeypatch.setattr(main, "alert_state", {"down_since": {}})
    monkeypatch.setattr(main, "channels_configured", lambda: True)
    monkeypatch.setitem(main.state, "checks", [])
    main.STORE.set_setting("job_alerts", "app")
    yield sent, pushed, fake_send
    main.STORE.set_setting("job_alerts", "hc")


def _set(status, name="h/job", prio="normal"):
    main.state["checks"] = [{"uuid": "j1", "name": name, "status": status, "prio": prio}]
    run(main.check_transitions())


def test_down_up_down_all_reported(transitions):
    sent, _, _ = transitions
    for st in ("up", "down", "up", "down"):
        _set(st)
    assert [t.splitlines()[0] for t in sent] == ["🔴 h/job überfällig", "✅ h/job wieder OK", "🔴 h/job überfällig"]


def test_undelivered_alert_is_retried(transitions):
    sent, _, fake = transitions
    _set("up")
    fake.ok = False
    _set("down")
    _set("down")
    assert len(sent) == 2 and main.push_state["j1"] == "up"  # noch nicht als gemeldet vermerkt
    fake.ok = True
    _set("down")
    _set("down")
    assert len(sent) == 3 and main.push_state["j1"] == "down"


def test_new_job_that_fails_immediately_is_reported(transitions):
    sent, _, _ = transitions
    _set("down", name="neu/job")
    assert sent and "neu/job" in sent[0]


def test_info_jobs_and_first_run_stay_quiet(transitions, monkeypatch):
    sent, _, _ = transitions
    _set("up", prio="info")
    _set("down", prio="info")
    assert not sent
    monkeypatch.setattr(main, "push_state", {})
    _set("down")
    assert not sent  # allererster Lauf: nur merken


def test_hc_mode_only_pushes(transitions):
    sent, pushed, _ = transitions
    main.STORE.set_setting("job_alerts", "hc")
    _set("up")
    _set("down")
    assert not sent and pushed == ["🔴 h/job ausgefallen"]


def test_detect_mode_new_install_vs_adopted(monkeypatch):
    def fake_hc(chans, checks):
        async def _hc(method, path, **kw):
            data = {"channels": chans} if "channels" in path else {"checks": checks}
            return httpx.Response(200, json=data, request=httpx.Request(method, "http://hc" + path))

        return _hc

    main.STORE.set_setting("job_alerts", None)
    monkeypatch.setattr(main, "_hc", fake_hc([{"id": "e", "name": "E-Mail", "kind": "email"}], [{"name": "a", "channels": ""}]))
    run(main.ensure_job_alert_mode())
    assert main.STORE.get_setting("job_alerts") == "app"
    main.STORE.set_setting("job_alerts", None)
    monkeypatch.setattr(main, "_hc", fake_hc([{"id": "s", "name": "Signal", "kind": "webhook"}], []))
    run(main.ensure_job_alert_mode())
    assert main.STORE.get_setting("job_alerts") == "hc"
    main.STORE.set_setting("job_alerts", None)
    monkeypatch.setattr(main, "_hc", fake_hc([{"id": "e", "name": "E-Mail", "kind": "email"}], [{"name": "a", "channels": "e"}]))
    run(main.ensure_job_alert_mode())
    assert main.STORE.get_setting("job_alerts") == "hc"  # Jobs mit Kanälen: sonst käme alles doppelt
    main.STORE.set_setting("job_alerts", "hc")


# ---------------------------------------------------------------- Dedup
def test_dedup_by_key_and_content(monkeypatch):
    delivered = []
    monkeypatch.setattr(main, "dedup", {})
    monkeypatch.setattr(main, "_save", lambda *a: None)
    monkeypatch.setattr(main, "push_all", lambda *a, **k: asyncio.sleep(0, 1))
    monkeypatch.setattr(main, "send_mail", lambda *a, **k: asyncio.sleep(0, False))
    monkeypatch.setattr(main, "SIGNAL_NUMBER", "")

    async def go(text, fp=None):
        delivered.append(await main.send_signal(text, dedup_key="beszel:web01", fp=fp))

    run(go("web01 is down"))
    run(go("web01 is down"))  # gleich → unterdrückt
    run(go("web01 is up"))  # anderer Zustand → kommt
    run(go("web01 is down"))  # wieder down → kommt
    assert delivered == [True, False, True, True]


def test_failed_delivery_is_not_remembered(monkeypatch):
    monkeypatch.setattr(main, "dedup", {})
    monkeypatch.setattr(main, "_save", lambda *a: None)
    monkeypatch.setattr(main, "push_all", lambda *a, **k: asyncio.sleep(0, 0))
    monkeypatch.setattr(main, "send_mail", lambda *a, **k: asyncio.sleep(0, False))
    monkeypatch.setattr(main, "SIGNAL_NUMBER", "")
    assert not run(main.send_signal("x", dedup_key="k"))
    assert "k" not in main.dedup


def test_beszel_dedup_key_ignores_state_words(monkeypatch):
    seen = []

    async def fake(text, dedup_key=None, url="/", fp=None, mail_text=None):
        seen.append((dedup_key, fp))
        return True

    monkeypatch.setattr(main, "send_signal", fake)
    monkeypatch.setattr(main, "_resolve", lambda host: {"testclient"})
    c = TestClient(main.app)
    c.post("/api/ingest/beszel", json={"title": "web01 is down", "message": "m"})
    c.post("/api/ingest/beszel", json={"title": "web01 is up", "message": "m"})
    assert seen[0][0] == seen[1][0] and seen[0][1] != seen[1][1]


def test_notify_same_title_different_hosts_both_sent(monkeypatch):
    seen = []

    async def fake(text, dedup_key=None, url="/", fp=None, mail_text=None):
        seen.append((dedup_key, fp))
        return True

    monkeypatch.setattr(main, "send_signal", fake)
    c = TestClient(main.app)
    c.post("/api/ingest/notify", json={"title": "Backup fehlgeschlagen", "message": "host a"}, headers=AUTH)
    c.post("/api/ingest/notify", json={"title": "Backup fehlgeschlagen", "message": "host b"}, headers=AUTH)
    assert seen[0][1] != seen[1][1]


# ---------------------------------------------------------------- Kanäle beim Bearbeiten
class FakeHC:
    def __init__(self, check):
        self.check, self.posts = check, []

    async def __call__(self, method, path, **kw):
        req = httpx.Request(method, "http://hc" + path)
        if path == "/api/v3/channels/":
            return httpx.Response(200, json={"channels": [{"id": "mail", "name": "E-Mail", "kind": "email"}]}, request=req)
        if method == "GET" and path.startswith("/api/v3/checks/") and path != "/api/v3/checks/":
            return httpx.Response(200, json=self.check, request=req)
        if method == "GET":
            return httpx.Response(200, json={"checks": [self.check]}, request=req)
        self.posts.append((path, kw.get("json")))
        return httpx.Response(200, json=self.check, request=req)


@pytest.fixture
def hc(monkeypatch):
    check = {
        "uuid": "11111111-2222-3333-4444-555555555555",
        "name": "web/backup",
        "slug": "web-backup",
        "tags": "host:web typ:backup prio:normal src:hc wichtig offsite",
        "schedule": "0 3 * * *",
        "tz": "UTC",
        "grace": 3600,
        "channels": "mail,mywebhook",
    }
    fake = FakeHC(check)
    monkeypatch.setattr(main, "_hc", fake)
    monkeypatch.setattr(main, "refresh", lambda: asyncio.sleep(0))
    monkeypatch.setattr(main, "ALLOW_NO_AUTH", True)
    monkeypatch.setattr(main.CREDS, "hc_api_key", "k")
    return fake


def test_edit_without_prio_change_keeps_channels_and_tags(hc):
    form = jobs.to_form(hc.check) | {"desc": "neue Notiz"}
    r = TestClient(main.app).put(f"/api/checks/{hc.check['uuid']}", json=form)
    assert r.status_code == 200
    _, body = hc.posts[-1]
    assert "channels" not in body
    assert "wichtig" in body["tags"] and "offsite" in body["tags"]


def test_prio_change_swaps_only_managed_channels(hc):
    r = TestClient(main.app).post(f"/api/checks/{hc.check['uuid']}/prio", json={"prio": "info"})
    assert r.status_code == 200
    _, body = hc.posts[-1]
    assert body["channels"] == "mywebhook"  # „E-Mail“ ist für info nicht vorgesehen, der eigene Webhook bleibt


def test_import_with_error_writes_nothing(hc):
    doc = "checks:\n  - name: web/backup\n    schedule: '0 4 * * *'\n  - name: 'kaputt'\n    schedule: täglich\n"
    r = TestClient(main.app).post("/api/config/import", json={"yaml": doc, "dry": False})
    assert r.status_code == 200 and r.json()["applied"] is False
    assert not hc.posts


def test_import_rejects_slug_clash(hc):
    doc = "checks:\n  - name: web/backup.x\n    schedule: '0 4 * * *'\n  - name: web/backup-x\n    schedule: '0 4 * * *'\n"
    r = TestClient(main.app).post("/api/config/import", json={"yaml": doc, "dry": True})
    errors = [a for a in r.json()["checks"] if a["action"] == "Fehler"]
    assert errors and "web-backup-x" in errors[0]["detail"]


def test_import_updates_existing_check_with_unusual_name(hc):
    hc.check["name"] = "Web Backup"
    doc = "checks:\n  - name: Web Backup\n    schedule: '0 4 * * *'\n"
    r = TestClient(main.app).post("/api/config/import", json={"yaml": doc, "dry": False})
    assert r.json()["applied"] is True and r.json()["checks"][0]["action"] == "aktualisieren"
    path, body = hc.posts[-1]
    assert path.endswith(hc.check["uuid"]) and body["name"] == "Web Backup" and "channels" not in body


def test_create_rejects_slug_of_other_job(hc, monkeypatch):
    monkeypatch.setitem(main.state, "checks", [{"name": "web/nightly-db", "slug": "web-nightly-db", "uuid": "x"}])
    form = {"host": "web", "job": "nightly.db", "schedule": "0 3 * * *"}
    r = TestClient(main.app).post("/api/checks", json=form)
    assert r.status_code == 409 and "web-nightly-db" in r.json()["detail"]


def test_oncalendar_schedule_accepted():
    body, _ = jobs.build({"host": "h", "job": "x", "schedule": "*-*-* 03:00:00"}, "UTC")
    assert body["schedule"] == "*-*-* 03:00:00"


# ---------------------------------------------------------------- checks.yaml
def test_checks_yaml_tolerates_bad_entries(tmp_path, monkeypatch):
    f = tmp_path / "checks.yaml"
    f.write_text(
        "settings:\n  digest_time: 10:30\nhosts:\n  nas:\nchecks:\n  - just-a-string\n  - name: ok/job\n"
        "watch_images:\n  - label: ohne image\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CHECKS_FILE", f)
    cfg = config.load()
    assert cfg["settings"]["digest_time"] == "10:30"
    assert cfg["hosts"]["nas"] == {}
    assert [c["name"] for c in cfg["checks"]] == ["ok/job"]
    assert cfg["watch_images"] == [] and len(cfg["_problems"]) == 2


def test_state_with_empty_host_entry_works(monkeypatch):
    monkeypatch.setattr(main, "cfg", {"settings": {}, "hosts": {"nas": {"beszel": "nas", "url": ["x"]}}, "checks": []})
    monkeypatch.setitem(main.state, "hosts", [{"name": "nas", "status": "up"}])
    assert main.host_extra("nas")["links"] == []


# ---------------------------------------------------------------- PVE, Quellen, Aufmerksamkeit
def test_pve_event_alerts_when_healthchecks_rejects_ping(monkeypatch):
    sent = []
    monkeypatch.setitem(main.state, "checks", [{"name": "pve/vzdump", "slug": "pve-vzdump", "match": {"source": "pve", "host": "pve"}}])
    monkeypatch.setattr(main.CREDS, "hc_ping_key", "pk")

    async def fake(text, **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(main, "send_signal", fake)

    class Cli:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def post(self, url, content=b""):
            return httpx.Response(404, request=httpx.Request("POST", url))

    monkeypatch.setattr(main.httpx, "AsyncClient", Cli)
    r = TestClient(main.app).post("/api/ingest/pve?host=pve", json={"severity": "error", "title": "vzdump failed"}, headers=AUTH)
    assert r.status_code == 200
    assert sent and "nicht angenommen" in sent[0] and "HTTP 404" in sent[0]


def test_attention_covers_all_event_sources_and_missing_sources(monkeypatch):
    ts = main.now().isoformat(timespec="seconds")
    monkeypatch.setattr(
        main,
        "events",
        [
            {"ts": ts, "source": "nas", "title": "Backup fehlgeschlagen", "message": "", "prio": "kritisch"},
            {"ts": ts, "source": "beszel", "title": "web01 is down", "message": "", "prio": "normal"},
        ],
    )
    monkeypatch.setitem(main.state, "errors", {"beszel": "nicht erreichbar: ReadTimeout"})
    monkeypatch.setitem(main.state, "checks", [])
    monkeypatch.setitem(main.state, "hosts", [])
    items = main.attention()
    titles = [i["title"] for i in items]
    assert "Backup fehlgeschlagen" in titles and "web01 is down" not in titles
    assert items[0]["kind"] == "source"
    assert "alles grün" not in main.digest_text()


def test_source_outage_alerted_once_after_grace(monkeypatch):
    sent = []

    async def fake(text, **kw):
        sent.append(text)
        return True

    monkeypatch.setattr(main, "send_signal", fake)
    monkeypatch.setitem(main.state, "error_since", {})
    monkeypatch.setitem(main.state, "errors", {"beszel": "nicht erreichbar"})
    run(main.check_source_outage())
    assert not sent
    main.state["error_since"]["beszel"]["since"] = (main.now() - dt.timedelta(minutes=20)).isoformat()
    run(main.check_source_outage())
    run(main.check_source_outage())
    assert len(sent) == 1 and "beszel" in sent[0]
    main.state["errors"] = {}
    run(main.check_source_outage())
    assert len(sent) == 2 and sent[1].startswith("✅")


# ---------------------------------------------------------------- Push-Größe
def test_push_payload_limited_by_bytes():
    data = push.payload({"title": "🔴" * 100, "body": "🔥" * 1500, "url": "/"})
    assert len(data) <= push.MAX_PAYLOAD
    assert json.loads(data)["title"]


def test_undelivered_outage_that_recovers_forgets_its_start(transitions):
    """Review 3b M3: Ausfall nie zugestellt, Job wieder grün → kein „War 3 d ausgefallen“ beim nächsten Mal."""
    sent, _, fake = transitions
    _set("up")
    fake.ok = False
    _set("down")
    assert "j1" in main.alert_state["down_since"]
    _set("up")
    assert "j1" not in main.alert_state["down_since"]


def test_sec_overdue_alert_retried_until_delivered(transitions, monkeypatch):
    """Review 3a/3b: Meldung „Security-Update überfällig“ wurde vor dem Senden als erledigt gemerkt."""
    sent, _, fake = transitions
    monkeypatch.setattr(main, "flags", {})
    monkeypatch.setattr(main, "host_updates", lambda: [{"host": "web01", "sec_overdue": 1, "sec_overdue_pkgs": ["openssl"]}])
    fake.ok = False
    run(main.check_sec_overdue())
    assert not main.flags.get("web01", {}).get("sec_alerted")
    fake.ok = True
    run(main.check_sec_overdue())
    assert main.flags["web01"]["sec_alerted"] == "openssl"
    n = len(sent)
    run(main.check_sec_overdue())
    assert len(sent) == n  # einmal reicht
