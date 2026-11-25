import pytest

from app import config, jobs


def test_build_cron_job():
    body, prio = jobs.build(
        {
            "host": "Docker01",
            "job": "restic-offsite",
            "mode": "cron",
            "schedule": " 0  3 * * * ",
            "grace": "2h",
            "prio": "kritisch",
            "typ": "backup",
        },
        "Europe/Berlin",
    )
    assert prio == "kritisch"
    assert body["name"] == "docker01/restic-offsite"
    assert body["slug"] == "docker01-restic-offsite"
    assert body["schedule"] == "0 3 * * *" and body["tz"] == "Europe/Berlin"
    assert body["grace"] == 7200 and "timeout" not in body
    assert body["tags"] == "host:docker01 typ:backup prio:kritisch src:hc"


def test_build_period_job():
    body, _ = jobs.build({"host": "vps", "job": "certbot", "mode": "period", "period": "1d", "grace": "6h"}, "UTC")
    assert body["timeout"] == 86400 and "schedule" not in body


@pytest.mark.parametrize(
    "data,err",
    [
        ({"host": "Docker 01", "job": "x"}, "Host"),
        ({"host": "h", "job": "a/b"}, "Name"),
        ({"host": "h", "job": "x", "schedule": "täglich"}, "Cron"),
        ({"host": "h", "job": "x", "schedule": "0 3 * * *", "grace": "30s"}, "1 Minute"),
        ({"host": "h", "job": "x", "schedule": "0 3 * * *", "prio": "hoch"}, "Priorität"),
        ({"host": "h", "job": "x", "mode": "period", "period": "bald"}, "Intervall"),
        ({"host": "pve", "job": "backup", "schedule": "0 1 * * *", "src": "pve", "ev": ""}, "Ereignis"),
    ],
)
def test_build_rejects_invalid(data, err):
    with pytest.raises(jobs.JobError, match=err):
        jobs.build(data, "UTC")


def test_pve_job_tags_match_webhook_events():
    body, _ = jobs.build(
        {"host": "pve", "job": "backup", "schedule": "0 1 * * *", "src": "pve", "ev": "vzdump", "job_id": "backup-1a2b"}, "UTC"
    )
    tags = dict(t.split(":", 1) for t in body["tags"].split())
    m = jobs.match_from_tags(tags)
    assert m == {"source": "pve", "host": "pve", "type": ["vzdump"], "job_id": "backup-1a2b"}
    check = {"name": body["name"], "slug": body["slug"], "match": m}
    assert config.match_event({"checks": [check]}, "pve", "pve", {"type": "vzdump", "job-id": "backup-1a2b"}) == [check]
    assert config.match_event({"checks": [check]}, "pve", "pve", {"type": "vzdump", "job-id": "other"}) == []
    assert config.match_event({"checks": [check]}, "pbs", "pve", {"type": "vzdump"}) == []


def test_update_keeps_name_and_foreign_tags():
    current = {"name": "nas/sync", "tags": "host:nas typ:sync prio:normal src:hc team:ops"}
    body, prio = jobs.build({"mode": "period", "period": "12h", "grace": "1h", "prio": "info", "typ": "sync"}, "UTC", current=current)
    assert body["name"] == "nas/sync" and "slug" not in body
    assert body["tags"] == "team:ops host:nas typ:sync prio:info src:hc"
    assert prio == "info"


def test_to_form_roundtrip():
    c = {
        "name": "docker01/backup",
        "slug": "docker01-backup",
        "tags": "host:docker01 typ:backup prio:kritisch src:hc",
        "grace": 7200,
        "schedule": "0 3 * * *",
        "tz": "UTC",
    }
    f = jobs.to_form(c)
    assert f["mode"] == "cron" and f["grace"] == "2h" and f["job"] == "backup" and f["slug"] == "docker01-backup"
    body, _ = jobs.build(f, "UTC", current=c)
    assert body["schedule"] == "0 3 * * *" and body["grace"] == 7200


def test_human():
    assert [jobs.human(s) for s in (60, 5400, 7200, 86400, 90)] == ["1m", "90m", "2h", "1d", "90s"]


def test_yaml_roundtrip_keeps_proxmox_match_and_source():
    hc = {
        "name": "pbs/gc",
        "slug": "pbs-gc",
        "tags": "host:pbs typ:gc prio:normal src:pbs ev:gc ds:store1",
        "grace": 7200,
        "schedule": "30 4 * * *",
        "tz": "UTC",
    }
    y = jobs.to_yaml_check(hc, "UTC")
    assert y == {
        "name": "pbs/gc",
        "tags": {"host": "pbs", "typ": "gc", "prio": "normal", "src": "pbs"},
        "schedule": "30 4 * * *",
        "grace": "2h",
        "match": {"source": "pbs", "host": "pbs", "type": "gc", "datastore": "store1"},
    }
    body, prio = jobs.from_yaml_check(y, "UTC")
    assert body["name"] == "pbs/gc" and body["slug"] == "pbs-gc" and prio == "normal"
    assert set(body["tags"].split()) == set(hc["tags"].split())


def test_yaml_checks_from_hc_sync_format():
    """Ein Eintrag wie in checks.example.yaml (ohne src, mit match) wird zum PVE-Job."""
    body, prio = jobs.from_yaml_check(
        {
            "name": "proxmox/vzdump",
            "tags": {"host": "proxmox", "typ": "backup", "prio": "kritisch"},
            "schedule": "0 1 * * *",
            "grace": "3h",
            "match": {"source": "pve", "host": "proxmox", "type": ["vzdump"]},
        },
        "Europe/Berlin",
    )
    assert prio == "kritisch" and body["tz"] == "Europe/Berlin"
    assert "src:pve" in body["tags"] and "ev:vzdump" in body["tags"]
    with pytest.raises(jobs.JobError):
        jobs.from_yaml_check({"name": "x", "schedule": "täglich"}, "UTC")
