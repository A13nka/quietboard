"""Gemeinsame Konfiguration: checks.yaml laden, Slugs und Zeitangaben."""

from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

CHECKS_FILE = Path(os.getenv("CHECKS_FILE", "/config/checks.yaml"))


def slug(name: str) -> str:
    """docker01/backup-pull -> docker01-backup-pull (Healthchecks erlaubt nur a-z0-9-_)."""
    s = name.lower().replace("/", "-")
    s = re.sub(r"[^a-z0-9_-]+", "-", s)
    return re.sub(r"-{2,}", "-", s).strip("-")


def seconds(value: str | int) -> int:
    if isinstance(value, int):
        return value
    m = re.fullmatch(r"\s*(\d+)\s*([smhd]?)\s*", str(value))
    if not m:
        raise ValueError(f"Ungültige Zeitangabe: {value!r}")
    n, unit = int(m.group(1)), m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def tag_string(tags: dict) -> str:
    return " ".join(f"{k}:{v}" for k, v in tags.items())


def _hhmm(value) -> str:
    """digest_time: "07:30" bleibt; YAML liest 10:30 ohne Anführungszeichen als Zahl 630 (Minuten)."""
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < 24 * 60:
        return f"{value // 60:02d}:{value % 60:02d}"
    return str(value)


def load() -> dict:
    """checks.yaml lesen. Einzelne fehlerhafte Einträge werden übersprungen und in cfg["_problems"] gemeldet,
    statt die ganze Datei (und damit jeden Abruf) scheitern zu lassen."""
    with CHECKS_FILE.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    if not isinstance(raw, dict):
        raise ValueError("checks.yaml: oberste Ebene muss settings/hosts/checks enthalten")
    problems: list[str] = []

    def section(name: str, kind: type, default):
        v = raw.get(name)
        if v is None:
            return default
        if not isinstance(v, kind):
            problems.append(f"{name}: falscher Typ, ignoriert")
            return default
        return v

    cfg: dict = {k: v for k, v in raw.items() if k not in ("settings", "hosts", "checks", "watch_images")}
    cfg["settings"] = section("settings", dict, {})
    if "digest_time" in cfg["settings"]:
        cfg["settings"]["digest_time"] = _hhmm(cfg["settings"]["digest_time"])
    cfg["hosts"] = {str(k): (v if isinstance(v, dict) else {}) for k, v in section("hosts", dict, {}).items()}
    cfg["checks"] = []
    for i, c in enumerate(section("checks", list, [])):
        if not isinstance(c, dict) or not c.get("name"):
            problems.append(f"checks[{i}]: ohne name, ignoriert")
            continue
        c["name"] = str(c["name"])
        c["slug"] = slug(c["name"])
        if not isinstance(c.get("tags"), dict):
            c["tags"] = {}
        c["prio"] = str(c["tags"].get("prio", "normal"))
        if c.get("match") is not None and not isinstance(c["match"], dict):
            problems.append(f"{c['name']}: match ignoriert (kein Block)")
            c["match"] = None
        cfg["checks"].append(c)
    cfg["watch_images"] = []
    for i, w in enumerate(section("watch_images", list, [])):
        if isinstance(w, dict) and isinstance(w.get("image"), str) and ":" in w["image"]:
            cfg["watch_images"].append(w)
        else:
            problems.append(f"watch_images[{i}]: braucht image: name:tag, ignoriert")
    cfg["_problems"] = problems
    return cfg


def match_event(cfg: dict, source: str, host: str, fields: dict) -> list[dict]:
    """Findet Checks, deren match-Block auf ein PVE/PBS-Event passt."""
    hits = []
    etype = str(fields.get("type", "")).lower()
    for c in cfg.get("checks") or []:
        m = c.get("match")
        if not m or m.get("source") != source or m.get("host") != host:
            continue
        types = m.get("type")
        if types:
            types = [types] if isinstance(types, str) else types
            if etype not in [t.lower() for t in types]:
                continue
        ok = True
        for key in ("job_id", "datastore"):
            want = m.get(key)
            if want and str(fields.get(key.replace("_", "-"), fields.get(key, ""))) != str(want):
                ok = False
        if ok:
            hits.append(c)
    return hits
