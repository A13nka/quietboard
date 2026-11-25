# 0004 – certifi (MPL-2.0) im Image erlaubt

Datum: 2026-11-23 · Status: angenommen

**Kontext:** Die Lizenzprüfung der CI hat `certifi` gefunden, die Zertifikatssammlung, die `httpx` mitbringt. certifi steht unter MPL-2.0. Das Konzept (Abschnitt 5) ging davon aus, dass unser Image keine Copyleft-Lizenz enthält – das stimmt damit nicht ganz.

**Einordnung:** MPL-2.0 ist eine schwache Copyleft-Lizenz auf Dateiebene. Pflichten entstehen nur für die MPL-Dateien selbst: Lizenztext mitliefern und auf den Quellcode verweisen. Unser eigener Code bleibt MIT. certifi wird unverändert genutzt. Keine Rechtsberatung.

**Entscheidung:** certifi steht ausdrücklich auf der Ausnahmeliste der CI-Lizenzprüfung. Jede weitere Copyleft-Lizenz lässt die CI weiterhin scheitern.

**Folgen:** `THIRD_PARTY_NOTICES.md` (wird noch erzeugt) nennt certifi mit MPL-2.0-Text und Link auf den Quellcode. Konzept Abschnitt 5 entsprechend korrigieren.
