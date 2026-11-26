"""Sprache der Meldungen, die der Server erzeugt (Morgenmeldung, Push, Mail, Signal, „Braucht Aufmerksamkeit“).

Deutsch ist der Ausgangstext und zugleich der Schlüssel. Die Sprache stellt ein Admin unter System → Benachrichtigungen ein
(Einstellung `language`, Standard aus der Umgebung `LANGUAGE`, sonst Deutsch). Die Oberfläche selbst übersetzt im
Browser (static/i18n.js) und folgt der Sprache des Browsers bzw. des Benutzers.
"""

from __future__ import annotations

import os
from collections.abc import Callable

LANGUAGES = ("de", "en")

EN = {
    "{name} ausgefallen": "{name} is down",
    "Kein Ping zur erwarteten Zeit oder Fehler gemeldet.": "No ping at the expected time, or a failure was reported.",
    "{name} wieder OK": "{name} is OK again",
    "{name}: {n} Security-Update(s) seit über {h} h offen": "{name}: {n} security update(s) pending for more than {h} h",
    "überfällig/fehlgeschlagen": "overdue/failed",
    "Karenzzeit läuft": "grace period running",
    "{name} offline": "{name} offline",
    "{host} · Security-Update überfällig": "{host} · security update overdue",
    "seit über {h} h offen: {pkgs}": "pending for more than {h} h: {pkgs}",
    "alles grün": "all green",
    "{n} Punkt(e) offen": "{n} item(s) open",
    "{name} zuletzt gesehen: {t}": "{name} last seen: {t}",
    "Updates: {h} Hosts · {p} Pakete · Security {s}": "Updates: {h} hosts · {p} packages · security {s}",
    " (überfällig {n})": " (overdue {n})",
    " · Neustart nötig: {n}": " · reboot required: {n}",
    "Quellen: {q}": "Sources: {q}",
    "{host}: {title} (ohne Check)": "{host}: {title} (no job)",
    "kein passender Job – unter Jobs anlegen": "no matching job – create one under Jobs",
    "Mitteilungen von QuietBoard funktionieren.": "Notifications from QuietBoard work.",
    "Mails von QuietBoard kommen an.": "Mail from QuietBoard arrives.",
    "Test von QuietBoard": "Test from QuietBoard",
    "{name} fehlgeschlagen": "{name} failed",
    # Job-Alarme (app/alerts.py) und Quellen
    ", Karenz {g}": ", grace {g}",
    "Exitcode {rc}": "exit code {rc}",
    "Fehler gemeldet": "failure reported",
    "Healthchecks hat die Meldung nicht angenommen: {names}": "Healthchecks did not accept the event: {names}",
    "Keine Meldung seit {t}": "No ping since {t}",
    "Lauf dauerte {d}": "run took {d}",
    "Lebenszeichen von QuietBoard. Wird rot, wenn die App nicht mehr läuft.": (
        "Heartbeat of QuietBoard. Turns red when the app stops running."
    ),
    "Lebenszeichen {n} war ausgefallen": "Heartbeat {n} was down",
    "Letzte Zeilen:": "Last lines:",
    "War {d} ausgefallen": "Was down for {d}",
    "Zeitplan {s}": "schedule {s}",
    "alle {p}": "every {p}",
    "fehlgeschlagen": "failed",
    "gestern {t}": "yesterday {t}",
    "heute {t}": "today {t}",
    "nie": "never",
    "{host}: {title} (Job nicht erreichbar)": "{host}: {title} (job not reachable)",
    "{n} Jobs ausgefallen": "{n} jobs down",
    "{n} Jobs wieder OK": "{n} jobs OK again",
    "{q} gestört seit {m} min": "{q} unavailable for {m} min",
    "{q} nicht erreichbar": "{q} unreachable",
    "{q} wieder erreichbar": "{q} reachable again",
    "überfällig": "overdue",
}

_lang: Callable[[], str] = lambda: os.getenv("LANGUAGE", "de")[:2]  # noqa: E731 – main.py ersetzt das durch die Einstellung


def set_language_source(fn: Callable[[], str]) -> None:
    global _lang
    _lang = fn


def lang() -> str:
    try:
        value = _lang()
    except Exception:
        value = "de"
    return value if value in LANGUAGES else "de"


def tr(text: str, **kw) -> str:
    out = EN.get(text, text) if lang() == "en" else text
    return out.format(**kw) if kw else out
