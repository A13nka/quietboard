"""Texte für Job-Alarme (Signal, Mail, Push) – kurz, das Wichtigste zuerst.

Reine Funktionen ohne Netzwerk, damit sie sich testen lassen. Die Sprache kommt über i18n.tr.
Muster: review/… bzw. docs/notifications.md (Abschnitt „So sehen Meldungen aus“).
"""

from __future__ import annotations

import datetime as dt
import re

from .i18n import tr
from .jobs import human

# Letzte Zeile, die `hc run` an das Log anhängt: "[hc] exit 1 · 14m"
EXIT_RE = re.compile(r"^\[hc\] exit (\d+)", re.M)
SHORT_LINES = 3  # Signal/Push
MAIL_LINES = 30


def _parse(iso: str | None) -> dt.datetime | None:
    if not iso:
        return None
    try:
        t = dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.UTC)  # ohne Zeitzone: UTC (so liefert PocketBase/Beszel)


def when(iso: str | None, now: dt.datetime) -> str:
    """„heute 03:12“, „gestern 03:04“, sonst „24.11. 03:04“ – in der Zeitzone von `now`."""
    t = _parse(iso)
    if t is None:
        return tr("nie")
    t = t.astimezone(now.tzinfo)
    hm = t.strftime("%H:%M")
    if t.date() == now.date():
        return tr("heute {t}", t=hm)
    if t.date() == (now - dt.timedelta(days=1)).date():
        return tr("gestern {t}", t=hm)
    return t.strftime("%d.%m. ") + hm


def duration(seconds: float | int | None) -> str:
    """6 h 12 min, 14 min, 40 s."""
    if seconds is None:
        return ""
    s = int(seconds)
    if s < 60:
        return f"{s} s"
    m = s // 60
    if m < 60:
        return f"{m} min"
    h, m = divmod(m, 60)
    if h < 48:
        return f"{h} h {m} min" if m else f"{h} h"
    d, h = divmod(h, 24)
    return f"{d} d {h} h" if h else f"{d} d"


def log_tail(body: str | None, n: int) -> list[str]:
    """Letzte n nicht leeren Zeilen, ohne die Abschlusszeile von hc."""
    lines = [ln.rstrip() for ln in (body or "").splitlines() if ln.strip() and not EXIT_RE.match(ln)]
    return [ln[:200] for ln in lines[-n:]]


def exit_code(body: str | None) -> int | None:
    m = list(EXIT_RE.finditer(body or ""))
    return int(m[-1].group(1)) if m else None


def _expected(c: dict) -> str:
    if c.get("schedule"):
        return tr("Zeitplan {s}", s=c["schedule"])
    return tr("alle {p}", p=human(c.get("timeout")) or "?")


def reason(c: dict, info: dict, now: dt.datetime) -> tuple[str, str]:
    """(Kurzform des Zustands, Detailzeile) für einen ausgefallenen Job.
    info: {"failed": bool, "body": str|None} vom letzten Ping (leer, wenn unbekannt)."""
    if info.get("failed"):
        rc = exit_code(info.get("body"))
        what = tr("fehlgeschlagen")
        detail = (tr("Exitcode {rc}", rc=rc) if rc is not None else tr("Fehler gemeldet")) + " · " + when(info.get("date"), now)
        return what, detail
    what = tr("überfällig")
    grace = human(c.get("grace"))
    detail = (
        tr("Keine Meldung seit {t}", t=when(c.get("last_ping"), now))
        + f" ({_expected(c)}"
        + (tr(", Karenz {g}", g=grace) + ")" if grace else ")")
    )
    return what, detail


def down_message(checks: list[dict], infos: dict, now: dt.datetime, base_url: str = "") -> tuple[str, str, str]:
    """(Text für Signal/Push, Text für Mail, Link) für einen oder mehrere ausgefallene Jobs."""
    if len(checks) == 1:
        c = checks[0]
        info = infos.get(c["uuid"], {})
        what, detail = reason(c, info, now)
        head = f"🔴 {c['name']} {what}"
        line2 = detail + (f" · {c['prio']}" if c.get("prio") == "kritisch" else "")
        url = f"/?c={c['uuid']}"
        short, mail = [head, line2], [head, line2]
        tail_s, tail_m = log_tail(info.get("body"), SHORT_LINES), log_tail(info.get("body"), MAIL_LINES)
        if tail_s:
            short += [tr("Letzte Zeilen:"), *("  " + ln for ln in tail_s)]
            mail += ["", tr("Letzte Zeilen:"), *("  " + ln for ln in tail_m)]
        if base_url:
            short.append(f"→ {base_url}{url}")
            mail += ["", f"→ {base_url}{url}"]
        return "\n".join(short), "\n".join(mail), url
    url = "/?t=jobs"
    head = "🔴 " + tr("{n} Jobs ausgefallen", n=len(checks))
    short, mail = [head], [head]
    for c in checks:
        info = infos.get(c["uuid"], {})
        what, detail = reason(c, info, now)
        short.append(f"• {c['name']} – {what}")
        mail += ["", f"• {c['name']} – {what}", f"  {detail}", *("    " + ln for ln in log_tail(info.get("body"), 10))]
    if base_url:
        short.append(f"→ {base_url}{url}")
        mail += ["", f"→ {base_url}{url}"]
    return "\n".join(short), "\n".join(mail), url


def up_message(checks: list[dict], down_since: dict, now: dt.datetime) -> tuple[str, str]:
    """(Text, Link) für wieder grüne Jobs."""

    def one(c):
        parts = []
        since = _parse(down_since.get(c["uuid"]))
        if since:
            parts.append(tr("War {d} ausgefallen", d=duration((now - since).total_seconds())))
        if c.get("last_duration"):
            parts.append(tr("Lauf dauerte {d}", d=duration(c["last_duration"])))
        return " · ".join(parts)

    if len(checks) == 1:
        c = checks[0]
        detail = one(c)
        return "✅ " + tr("{name} wieder OK", name=c["name"]) + (f"\n{detail}" if detail else ""), f"/?c={c['uuid']}"
    lines = ["✅ " + tr("{n} Jobs wieder OK", n=len(checks))] + [f"• {c['name']}" + (f" – {one(c)}" if one(c) else "") for c in checks]
    return "\n".join(lines), "/?t=jobs"
