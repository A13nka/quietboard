"""Gemeinsame Test-Einstellungen: App mit Beispielkonfiguration und Wegwerf-Datenordner laden."""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Muss vor dem Import von app.main gesetzt sein (Modul liest die Umgebung beim Import).
os.environ.setdefault("DATA_DIR", tempfile.mkdtemp(prefix="quietboard-test-"))
os.environ.setdefault("CHECKS_FILE", str(ROOT / "config" / "checks.example.yaml"))
os.environ.setdefault("INGEST_TOKEN", "test-token")
os.environ.setdefault("TZ", "UTC")
