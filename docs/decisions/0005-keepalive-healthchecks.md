# 0005 – Keep-alive gegen Healthchecks v5: kein Problem mehr, Einstellung bleibt

Datum: 2026-11-24 · Status: angenommen

**Kontext:** Mit Healthchecks v4.3 (uWSGI) brachen wiederverwendete HTTP-Verbindungen hart ab. Die App setzt deshalb `max_keepalive_connections=0`. Seit v5 läuft Healthchecks mit gunicorn. Machbarkeitstest aus Phase 0: 1.000 API-Aufrufe mit Keep-alive ohne Abbruch.

**Messung** (`python -m tools.keepalive_test`, Healthchecks v5.0.3, lokal):

| Lauf | Fehler | Antworten mit `Connection: close` |
| --- | --- | --- |
| 1.000 Aufrufe direkt hintereinander | 0 | 1.000 |
| 200 Aufrufe, je 0,5 s Pause | 0 | 200 |
| 5 Aufrufe, je 6 s Pause | 0 | 5 |

**Ergebnis:** Keine Abbrüche. gunicorn läuft im Healthchecks-Image mit „sync“-Workern, die kein Keep-alive unterstützen und jede Verbindung nach der Antwort selbst schließen. Eine Wiederverwendung findet also gar nicht statt – weder mit noch ohne die Einstellung.

**Entscheidung:** `max_keepalive_connections=0` bleibt. Es entspricht dem Serververhalten, kostet nichts und schützt, falls jemand eine ältere Healthchecks-Version anbindet. Der E2E-Test prüft 200 Aufrufe ohne Verbindungsfehler als Schutz gegen Rückschritte bei künftigen Healthchecks-Versionen.
