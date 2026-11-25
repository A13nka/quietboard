"""quietboard-CLI im Container – vor allem für den Notfall (Passwort vergessen, kein Admin mehr).

    docker compose exec status python -m tools.cli users
    docker compose exec status python -m tools.cli add du@example.org [--role admin|viewer]
    docker compose exec status python -m tools.cli passwd du@example.org      # neues Passwort wird erzeugt
    docker compose exec status python -m tools.cli role du@example.org admin
    docker compose exec status python -m tools.cli setup-code                 # nur ohne Benutzer
Mit --json maschinenlesbar (für Skripte und KI-Assistenten).
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
from pathlib import Path

from app import auth


def _store() -> auth.Store:
    return auth.Store(Path(os.getenv("DATA_DIR", "/data")) / "quietboard.db")


def _find(store: auth.Store, email: str) -> dict:
    email = email.strip().lower()
    user = next((u for u in store.list_users() if u["email"] == email), None)
    if not user:
        raise SystemExit(f"Kein Benutzer {email}")
    return user


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="python -m tools.cli", description="quietboard-Konten verwalten")
    p.add_argument("--json", action="store_true", help="Ausgabe als JSON")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("users", help="Benutzer auflisten")
    a = sub.add_parser("add", help="Benutzer anlegen (Passwort wird erzeugt)")
    a.add_argument("email")
    a.add_argument("--role", choices=auth.ROLES, default="viewer")
    pw = sub.add_parser("passwd", help="Passwort zurücksetzen (neues wird erzeugt, alle Sitzungen enden)")
    pw.add_argument("email")
    r = sub.add_parser("role", help="Rolle ändern")
    r.add_argument("email")
    r.add_argument("role", choices=auth.ROLES)
    sub.add_parser("setup-code", help="Einrichtungscode anzeigen (nur solange es keinen Benutzer gibt)")
    args = p.parse_args(argv)
    store = _store()

    def out(obj, text: str) -> None:
        print(json.dumps(obj, ensure_ascii=False) if args.json else text)

    try:
        if args.cmd == "users":
            users = store.list_users()
            out(users, "\n".join(f"{u['email']:40} {u['role']}" for u in users) or "(keine Benutzer)")
        elif args.cmd == "add":
            password = secrets.token_urlsafe(12)
            user = store.create_user(args.email, password, args.role)
            out({**user, "password": password}, f"{user['email']} ({user['role']}) angelegt. Passwort: {password}")
        elif args.cmd == "passwd":
            user = _find(store, args.email)
            password = secrets.token_urlsafe(12)
            store.set_password(user["id"], password)
            out({"email": user["email"], "password": password}, f"Neues Passwort für {user['email']}: {password}")
        elif args.cmd == "role":
            user = _find(store, args.email)
            store._x("UPDATE users SET role=? WHERE id=?", (args.role, user["id"]))  # CLI darf auch den letzten Admin ändern
            out(store.get_user(user["id"]), f"{user['email']} ist jetzt {args.role}")
        elif args.cmd == "setup-code":
            if store.has_users():
                raise SystemExit("Es gibt schon Benutzer – Einrichtungscode nicht mehr nötig")
            raise SystemExit("Der Einrichtungscode lebt im laufenden App-Prozess: docker compose logs status | grep Einrichtungscode")
    except auth.AuthError as exc:
        print(f"Fehler: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
