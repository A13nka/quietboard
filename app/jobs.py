"""Jobs über die Oberfläche: Formularwerte ↔ Healthchecks-Check (Name, Zeitplan, Karenz, Tags).

Ein Job ist ein Healthchecks-Check mit dem Namen `<host>/<job>` und Tags:
    host:<host> typ:<typ> prio:<prio> src:<hc|url|pve|pbs> [ev:<typ,…> job:<id> ds:<datastore>]
`src` sagt, wie sich der Job meldet: `hc` (Helfer auf dem Host), `url` (andere Software mit Ping-URL),
`pve`/`pbs` (Proxmox-Webhook; `ev`, `job`, `ds` wählen die passenden Ereignisse aus).
checks.yaml bleibt als Alternative erhalten; dort definierte Checks werden wie bisher abgeglichen.
"""

from __future__ import annotations

import re

from . import config

PRIOS = ("kritisch", "normal", "info")
TYPES = ("backup", "sync", "zertifikat", "skript", "wartung", "verify", "gc", "prune", "sonstiges")
SOURCES = ("hc", "url", "pve", "pbs")
MANAGED_TAGS = ("host", "typ", "prio", "src", "ev", "job", "ds")
DEFAULT_CHANNELS = {"kritisch": ["E-Mail"], "normal": ["E-Mail"], "info": []}

_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,47}")
_TAGVAL = re.compile(r"[A-Za-z0-9._:,-]{1,80}")
_MIN, _MAX = 60, 365 * 86400


class JobError(ValueError):
    """Ungültige Eingabe – Text geht als Fehlermeldung an die Oberfläche."""


def _dur(value: object, what: str) -> int:
    try:
        sec = config.seconds(str(value).strip())
    except ValueError:
        raise JobError(f"{what}: Zeitangabe wie 30m, 2h oder 1d") from None
    if not _MIN <= sec <= _MAX:
        raise JobError(f"{what}: zwischen 1 Minute und 365 Tagen")
    return sec


def human(sec: int | None) -> str:
    """3600 → 1h, 5400 → 90m, 86400 → 1d (für das Bearbeiten-Formular)."""
    if not sec:
        return ""
    for unit, n in (("d", 86400), ("h", 3600), ("m", 60)):
        if sec % n == 0:
            return f"{sec // n}{unit}"
    return f"{sec}s"


def _tags(tag_str: str) -> dict:
    return dict(t.split(":", 1) for t in (tag_str or "").split() if ":" in t)


def match_from_tags(tags: dict) -> dict | None:
    """Tags eines GUI-Jobs → match-Block wie in checks.yaml (für PVE/PBS-Webhooks)."""
    src = tags.get("src")
    if src not in ("pve", "pbs"):
        return None
    m: dict = {"source": src, "host": tags.get("host", "")}
    if tags.get("ev"):
        m["type"] = tags["ev"].split(",")
    if tags.get("job"):
        m["job_id"] = tags["job"]
    if tags.get("ds"):
        m["datastore"] = tags["ds"]
    return m


def build(d: dict, tz: str, current: dict | None = None, extra_tags: dict | None = None) -> tuple[dict, str]:
    """Formular → Healthchecks-Body. Beim Bearbeiten (current = Check aus Healthchecks) bleiben Name und Slug.

    Gibt (body, prio) zurück; die Kanäle setzt der Aufrufer passend zur Priorität."""
    if current:
        name = current["name"]
        host = name.split("/", 1)[0]
    else:
        host = str(d.get("host", "")).strip().lower()
        job = str(d.get("job", "")).strip().lower()
        if not _NAME.fullmatch(host):
            raise JobError("Host: Kleinbuchstaben, Ziffern, Punkt, Binde- oder Unterstrich")
        if not _NAME.fullmatch(job):
            raise JobError("Name: Kleinbuchstaben, Ziffern, Punkt, Binde- oder Unterstrich, z. B. restic-offsite")
        name = f"{host}/{job}"

    prio = d.get("prio") or "normal"
    if prio not in PRIOS:
        raise JobError("Priorität: kritisch, normal oder info")
    typ = str(d.get("typ") or "skript").strip().lower()
    if not _NAME.fullmatch(typ):
        raise JobError("Art: ein Wort, z. B. " + ", ".join(TYPES[:4]))
    src = d.get("src") or "hc"
    if src not in SOURCES:
        raise JobError("Meldeweg unbekannt")

    tags = {k: v for k, v in _tags((current or {}).get("tags", "")).items() if k not in MANAGED_TAGS}
    tags.update({str(k): str(v) for k, v in (extra_tags or {}).items() if k not in MANAGED_TAGS and _TAGVAL.fullmatch(str(v))})
    tags.update(host=host, typ=typ, prio=prio, src=src)
    if src in ("pve", "pbs"):
        ev = str(d.get("ev") or "").strip().lower().replace(" ", "")
        if not ev or not _TAGVAL.fullmatch(ev):
            raise JobError("Ereignis: z. B. vzdump (PVE) oder verify, gc, prune, sync (PBS)")
        tags["ev"] = ev
        for key, field in (("job", "job_id"), ("ds", "ds")):
            val = str(d.get(field) or "").strip()
            if val:
                if not _TAGVAL.fullmatch(val):
                    raise JobError("Job-ID/Datastore: nur Buchstaben, Ziffern, Punkt, Binde- oder Unterstrich")
                tags[key] = val

    body: dict = {
        "name": name,
        "tags": config.tag_string(tags),
        "desc": str(d.get("desc") or "")[:500],
        "grace": _dur(d.get("grace") or "1h", "Darf dauern"),
    }
    if not current:
        body["slug"] = config.slug(name)
    if (d.get("mode") or "cron") == "cron":
        schedule = " ".join(str(d.get("schedule") or "").split())
        if len(schedule.split()) != 5:
            raise JobError('Zeitplan: Cron mit 5 Feldern, z. B. "0 3 * * *" (täglich 3:00)')
        body.update(schedule=schedule, tz=str(d.get("tz") or tz))
    else:
        body["timeout"] = _dur(d.get("period"), "Intervall")
    return body, prio


def to_form(c: dict) -> dict:
    """Healthchecks-Check → Werte fürs Bearbeiten-Formular."""
    tags = _tags(c.get("tags", ""))
    host, _, job = c["name"].partition("/")
    cron = bool(c.get("schedule"))
    return {
        "host": tags.get("host", host),
        "job": job or c["name"],
        "mode": "cron" if cron else "period",
        "schedule": c.get("schedule", "") if cron else "",
        "tz": c.get("tz", ""),
        "period": "" if cron else human(c.get("timeout")),
        "grace": human(c.get("grace")),
        "prio": tags.get("prio", "normal"),
        "typ": tags.get("typ", "skript"),
        "src": tags.get("src", "hc"),
        "ev": tags.get("ev", ""),
        "job_id": tags.get("job", ""),
        "ds": tags.get("ds", ""),
        "desc": c.get("desc", ""),
        "slug": c.get("slug") or config.slug(c["name"]),
    }


# ---------------------------------------------------------------- YAML (checks.yaml-Format)
def to_yaml_check(c: dict, tz: str) -> dict:
    """Healthchecks-Check → Eintrag für checks.yaml (auch mit hc_sync nutzbar)."""
    tags = _tags(c.get("tags", ""))
    out: dict = {"name": c["name"], "tags": {k: v for k, v in tags.items() if k not in ("ev", "job", "ds")}}
    if tags.get("src") == "hc":
        out["tags"].pop("src")
    if c.get("schedule"):
        out["schedule"] = c["schedule"]
        if c.get("tz") and c["tz"] != tz:
            out["tz"] = c["tz"]
    else:
        out["period"] = human(c.get("timeout"))
    out["grace"] = human(c.get("grace"))
    if c.get("desc"):
        out["desc"] = c["desc"]
    m = match_from_tags(tags)
    if m:
        if len(m.get("type", [])) == 1:
            m["type"] = m["type"][0]
        out["match"] = m
    return out


def from_yaml_check(c: dict, tz: str) -> tuple[dict, str]:
    """Eintrag aus checks.yaml → Healthchecks-Body (wie build, PVE/PBS-match wird zu Tags)."""
    if not isinstance(c, dict) or not c.get("name"):
        raise JobError("Eintrag ohne name")
    name = str(c["name"]).strip().lower()
    host, sep, job = name.partition("/")
    if not sep:
        host, job = (c.get("tags") or {}).get("host", "sonstige"), name
    tags = {str(k): str(v) for k, v in (c.get("tags") or {}).items()}
    m = c.get("match") or {}
    types = m.get("type")
    d = {
        "host": host,
        "job": job,
        "mode": "cron" if c.get("schedule") else "period",
        "schedule": c.get("schedule", ""),
        "tz": c.get("tz") or tz,
        "period": c.get("period", "1d"),
        "grace": c.get("grace", "1h"),
        "prio": tags.get("prio", "normal"),
        "typ": tags.get("typ", "skript"),
        "src": tags.get("src") or m.get("source") or "hc",
        "ev": ",".join(types) if isinstance(types, list) else (types or ""),
        "job_id": m.get("job_id", ""),
        "ds": m.get("datastore", ""),
        "desc": c.get("desc", ""),
    }
    if d["src"] in ("pve", "pbs") and not d["ev"]:
        d["ev"] = "vzdump" if d["src"] == "pve" else "verify"
    body, prio = build(d, tz, extra_tags={k: v for k, v in tags.items() if k != "host"})
    body["name"] = str(c["name"]).strip()  # Name wie in der Datei (so passt er zu bestehenden Checks)
    body["slug"] = config.slug(body["name"])
    return body, prio
