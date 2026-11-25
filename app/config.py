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


def load() -> dict:
    with CHECKS_FILE.open(encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}
    cfg.setdefault("settings", {})
    cfg.setdefault("hosts", {})
    cfg.setdefault("checks", [])
    for c in cfg["checks"]:
        c["slug"] = slug(c["name"])
        c.setdefault("tags", {})
        c["prio"] = c["tags"].get("prio", "normal")
    return cfg


def match_event(cfg: dict, source: str, host: str, fields: dict) -> list[dict]:
    """Findet Checks, deren match-Block auf ein PVE/PBS-Event passt."""
    hits = []
    etype = str(fields.get("type", "")).lower()
    for c in cfg["checks"]:
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
