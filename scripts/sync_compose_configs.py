"""Schreibt die Skripte aus bootstrap/ als eingebettete Configs ans Ende von compose.yaml.

Warum eingebettet: Einsteiger laden nur compose.yaml und .env herunter – es darf keine weiteren Dateien brauchen.
Aufruf:  python3 scripts/sync_compose_configs.py          (schreibt)
         python3 scripts/sync_compose_configs.py --check  (Exitcode 1, wenn compose.yaml veraltet ist)
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "compose.yaml"
MARKER = "# --- Ab hier generiert von scripts/sync_compose_configs.py – nicht von Hand ändern.\n"
CONFIGS = {
    "hc-bootstrap": ROOT / "bootstrap" / "healthchecks_init.py",
    "hc-local-settings": ROOT / "bootstrap" / "hc_local_settings.py",
}


def render() -> str:
    out = [MARKER, "configs:\n"]
    for name, path in CONFIGS.items():
        text = path.read_text(encoding="utf-8")
        if "$" in text:
            raise SystemExit(f"{path}: enthält '$' – Compose würde es als Variable interpretieren")
        out.append(f"  {name}:\n    content: |\n")
        out.extend(f"      {line}\n" if line else "\n" for line in text.rstrip("\n").split("\n"))
    return "".join(out)


def main() -> int:
    current = COMPOSE.read_text(encoding="utf-8")
    head = current.split(MARKER, 1)[0].rstrip("\n") + "\n\n"
    wanted = head + render()
    if "--check" in sys.argv:
        if current != wanted:
            print("compose.yaml ist veraltet: python3 scripts/sync_compose_configs.py", file=sys.stderr)
            return 1
        return 0
    COMPOSE.write_text(wanted, encoding="utf-8")
    print("compose.yaml aktualisiert")
    return 0


if __name__ == "__main__":
    sys.exit(main())
