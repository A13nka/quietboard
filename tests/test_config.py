import pytest

from app import config


def test_slug():
    assert config.slug("docker01/Backup Pull") == "docker01-backup-pull"


@pytest.mark.parametrize(("value", "expected"), [("90", 90), ("5m", 300), ("2h", 7200), ("1d", 86400), (42, 42)])
def test_seconds(value, expected):
    assert config.seconds(value) == expected


def test_seconds_invalid():
    with pytest.raises(ValueError):
        config.seconds("zwei Stunden")


def test_example_config_loads():
    cfg = config.load()
    assert cfg["checks"], "Beispielkonfiguration enthält keine Checks"
    assert all("slug" in c and "prio" in c for c in cfg["checks"])


def test_match_event_vzdump():
    cfg = config.load()
    hits = config.match_event(cfg, "pve", "proxmox", {"type": "vzdump"})
    assert [c["name"] for c in hits] == ["proxmox/vzdump"]
    assert config.match_event(cfg, "pve", "proxmox", {"type": "replication"}) == []


def test_compose_embeds_current_bootstrap_scripts():
    """compose.yaml enthält die Skripte aus bootstrap/ – nach Änderungen `make configs` ausführen."""
    import subprocess
    import sys
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    r = subprocess.run([sys.executable, str(root / "scripts" / "sync_compose_configs.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
