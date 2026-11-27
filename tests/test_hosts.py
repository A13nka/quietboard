"""Shell-Helfer auf den Hosts und bei der Installation (laufen mit bash, ohne Netz nach außen)."""

import http.server
import shutil
import subprocess
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HC = ROOT / "hosts" / "hc"


def test_hc_run_without_config_still_runs_command():
    out = subprocess.run(
        ["bash", str(HC), "run", "x-job", "--", "sh", "-c", "echo lief; exit 3"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HC_CONF": "/nonexistent/hc.conf"},
        timeout=30,
    )
    assert out.returncode == 3
    assert "lief" in out.stdout
    assert "keine Ping-Daten" in out.stderr


def test_hc_ping_without_config_fails():
    out = subprocess.run(
        ["bash", str(HC), "ping", "x-job"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HC_CONF": "/nonexistent"},
        timeout=30,
    )
    assert out.returncode == 1


@pytest.fixture
def ping_server():
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            got.append((self.path, self.rfile.read(n).decode()))
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/ping", got
    srv.shutdown()


def test_hc_run_reports_start_and_exit_code(ping_server, tmp_path):
    base, got = ping_server
    conf = tmp_path / "hc.conf"
    conf.write_text(f"HC_PING_BASE={base}\nHC_PING_KEY=k3y\n")
    out = subprocess.run(
        ["bash", str(HC), "run", "x-job", "--", "sh", "-c", "echo zeile1; exit 2"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "HC_CONF": str(conf)},
        timeout=60,
    )
    assert out.returncode == 2, out.stderr
    paths = [p for p, _ in got]
    assert paths[0].startswith("/ping/k3y/x-job/start?rid=")
    assert paths[1].startswith("/ping/k3y/x-job/2?rid=")
    assert "zeile1" in got[1][1] and "[hc] exit 2, " in got[1][1]


def test_generate_env_without_trailing_newline(tmp_path):
    if not shutil.which("openssl"):
        pytest.skip("openssl fehlt")
    for f in ("generate-env.sh", ".env.example"):
        shutil.copy(ROOT / f, tmp_path / f)
    (tmp_path / ".env").write_text("ADMIN_EMAIL=a@example.org\nHC_SECRET_KEY=behalten")  # ohne Umbruch am Ende
    out = subprocess.run(["bash", str(tmp_path / "generate-env.sh")], capture_output=True, text=True, timeout=60)
    assert out.returncode == 0, out.stderr
    lines = (tmp_path / ".env").read_text().splitlines()
    assert "HC_SECRET_KEY=behalten" in lines
    assert any(ln.startswith("INGEST_TOKEN=") and len(ln) > len("INGEST_TOKEN=") for ln in lines)


UPGRADE = ROOT / "hosts" / "upgrade-host.sh"
LEGACY_CONF = "HC_PING_KEY=k3y\nSTATUS_INGEST_TOKEN=tok\nSTATUS_HOST=web01\nMAILCOW_DIR=/opt/x"  # ohne Adressen, ohne Umbruch


def _legacy_host(tmp_path):
    (tmp_path / "etc" / "cron.d").mkdir(parents=True)
    (tmp_path / "usr" / "local" / "bin").mkdir(parents=True)
    (tmp_path / "etc" / "hc.conf").write_text(LEGACY_CONF)
    (tmp_path / "usr" / "local" / "bin" / "hc").write_text("#!/bin/sh\necho alt\n")
    (tmp_path / "usr" / "local" / "bin" / "updates-report").write_text("#!/bin/sh\necho alt\n")
    (tmp_path / "etc" / "cron.d" / "backup").write_text(
        "0 3 * * * root /opt/backup.sh 2>&1 | hc ping pve-backup log\n5 3 * * * root hc ping plain\n"
    )


def _upgrade(tmp_path, *args, **env):
    e = {"PATH": "/usr/bin:/bin:/usr/sbin:/sbin", "QB_ROOT": str(tmp_path), **env}
    return subprocess.run(["bash", str(UPGRADE), *args], capture_output=True, text=True, env=e, timeout=60)


def test_upgrade_check_changes_nothing_and_names_missing_values(tmp_path):
    _legacy_host(tmp_path)
    out = _upgrade(tmp_path)
    assert out.returncode == 1, out.stdout + out.stderr
    assert "FEHLT: HC_PING_BASE" in out.stdout and "FEHLT: STATUS_INGEST_URL" in out.stdout
    assert "hc ping pve-backup log" in out.stdout  # Pipe-Stelle gefunden, „plain“ nicht
    assert "plain" not in out.stdout
    assert (tmp_path / "etc" / "hc.conf").read_text() == LEGACY_CONF
    assert not list(tmp_path.rglob("*.bak-qb"))


def test_upgrade_apply_and_rollback(tmp_path):
    _legacy_host(tmp_path)
    env = {"QB_PING_BASE": "http://srv:8000/ping", "QB_INGEST_URL": "http://srv:8088/api/ingest/updates"}
    out = _upgrade(tmp_path, "--apply", "--fix-stdin", **env)
    assert out.returncode == 0, out.stdout + out.stderr
    conf = (tmp_path / "etc" / "hc.conf").read_text().splitlines()
    assert conf[:4] == LEGACY_CONF.splitlines()  # alte Zeilen unverändert, MAILCOW_DIR bleibt
    assert "HC_PING_BASE=http://srv:8000/ping" in conf and "STATUS_INGEST_URL=http://srv:8088/api/ingest/updates" in conf
    assert oct((tmp_path / "etc" / "hc.conf").stat().st_mode & 0o777) == "0o600"
    hc = tmp_path / "usr" / "local" / "bin" / "hc"
    assert hc.read_text() == HC.read_text()
    cron = (tmp_path / "etc" / "cron.d" / "backup").read_text()
    assert "| hc ping pve-backup log -\n" in cron and "root hc ping plain\n" in cron
    # zweiter Lauf: Sicherungen bleiben die Originale
    assert _upgrade(tmp_path, "--apply", **env).returncode == 0
    assert (tmp_path / "usr" / "local" / "bin" / "hc.bak-qb").read_text() == "#!/bin/sh\necho alt\n"
    out = _upgrade(tmp_path, "--rollback")
    assert out.returncode == 0, out.stderr
    assert (tmp_path / "etc" / "hc.conf").read_text() == LEGACY_CONF
    assert hc.read_text() == "#!/bin/sh\necho alt\n"
    assert "| hc ping pve-backup log\n" in (tmp_path / "etc" / "cron.d" / "backup").read_text()
    assert not list(tmp_path.rglob("*.bak-qb"))


def test_upgrade_register_replaces_only_the_token(tmp_path):
    got = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            got.append((self.path, self.headers.get("Authorization"), self.rfile.read(n).decode()))
            body = b'{"host": "web01", "token": "qbh_NEU123"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        _legacy_host(tmp_path)
        base = f"http://127.0.0.1:{srv.server_address[1]}"
        env = {"QB_PING_BASE": f"{base}/ping", "QB_INGEST_URL": f"{base}/api/ingest/updates"}
        out = _upgrade(tmp_path, "--apply", "--register", **env)
        assert out.returncode == 0, out.stdout + out.stderr
        assert got and got[0][0] == "/api/install/register" and got[0][1] == "Bearer tok" and '"host":"web01"' in got[0][2]
        conf = (tmp_path / "etc" / "hc.conf").read_text().splitlines()
        assert "STATUS_INGEST_TOKEN='qbh_NEU123'" in conf and "STATUS_INGEST_TOKEN=tok" not in conf
        assert "MAILCOW_DIR=/opt/x" in conf and "STATUS_HOST=web01" in conf
        assert _upgrade(tmp_path, "--rollback").returncode == 0
        assert (tmp_path / "etc" / "hc.conf").read_text() == LEGACY_CONF
    finally:
        srv.shutdown()
