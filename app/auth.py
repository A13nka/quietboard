"""Lokale Konten: Benutzer, Sitzungen, Einrichtungscode, Einstellungen (SQLite in /data/quietboard.db).

- Erster Start ohne Benutzer: Einrichtungscode im Log (docker compose logs status). Wer ihn kennt, legt den Admin an.
- Passwörter: scrypt (hashlib, ohne Zusatzpakete). Sitzungen: zufälliges Token im Cookie, in der DB nur als SHA-256.
- Rollen: admin (alles), viewer (nur lesen, eigenes Passwort, eigene Push-Geräte).
- API-Tokens für eigene Skripte (`qb_…`): gehören einem Benutzer, haben dessen Rolle, in der DB nur als SHA-256.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path

log = logging.getLogger("status.auth")

ROLES = ("admin", "viewer")
SESSION_DAYS = 30
MIN_PASSWORD = 10
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}
_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # ohne 0/O, 1/I/L


class AuthError(Exception):
    """Fehler mit Meldung für die Oberfläche."""


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, dklen=32, maxmem=64 * 1024 * 1024, **_SCRYPT)
    return "scrypt${n}${r}${p}${s}${h}".format(**_SCRYPT, s=base64.b64encode(salt).decode(), h=base64.b64encode(dk).decode())


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), dklen=32, maxmem=64 * 1024 * 1024)
        return hmac.compare_digest(dk, base64.b64decode(digest))
    except Exception:
        return False


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def check_password_rules(password: str) -> None:
    if len(password) < MIN_PASSWORD:
        raise AuthError(f"Passwort zu kurz (mindestens {MIN_PASSWORD} Zeichen)")


def normalize_email(email: str) -> str:
    email = (email or "").strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@") or len(email) > 254:
        raise AuthError("Ungültige E-Mail-Adresse")
    return email


class Store:
    """Kleine SQLite-Ablage. Ein Prozess, wenige Schreibzugriffe – eine Verbindung mit Lock reicht."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self._db.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._db.executescript(
                """
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, name TEXT NOT NULL DEFAULT '',
                    role TEXT NOT NULL, pw_hash TEXT NOT NULL, created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    created REAL NOT NULL, expires REAL NOT NULL, ua TEXT NOT NULL DEFAULT '');
                CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS api_tokens (
                    id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL, name TEXT NOT NULL, token_hash TEXT UNIQUE NOT NULL,
                    hint TEXT NOT NULL, created REAL NOT NULL, last_used REAL);
                """
            )
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        self.setup_code: str | None = None
        self._failures: dict[str, list[float]] = {}

    # ------------------------------------------------------------ Hilfen
    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._db.execute(sql, args).fetchall()

    def _x(self, sql: str, args: tuple = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, args)
            return cur.lastrowid or cur.rowcount

    # ------------------------------------------------------------ Einrichtung
    def has_users(self) -> bool:
        return bool(self._q("SELECT 1 FROM users LIMIT 1"))

    def ensure_setup_code(self) -> str | None:
        """Erzeugt bei Bedarf einen Einrichtungscode und schreibt ihn ins Log. None, wenn schon Benutzer existieren."""
        if self.has_users():
            self.setup_code = None
            return None
        if not self.setup_code:
            raw = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(8))
            self.setup_code = f"{raw[:4]}-{raw[4:]}"
        log.warning("Einrichtungscode: %s  – im Browser eingeben, um das Admin-Konto anzulegen", self.setup_code)
        return self.setup_code

    def complete_setup(self, code: str, email: str, password: str, name: str = "") -> dict:
        if self.has_users():
            raise AuthError("Bereits eingerichtet – bitte anmelden")
        given = (code or "").strip().upper().replace(" ", "")
        if len(given) == 8:
            given = f"{given[:4]}-{given[4:]}"
        if not (self.setup_code and hmac.compare_digest(given, self.setup_code)):
            raise AuthError("Einrichtungscode falsch – er steht im Log: docker compose logs status")
        user = self.create_user(email, password, "admin", name)
        self.setup_code = None
        log.info("Einrichtung abgeschlossen: Admin %s angelegt", user["email"])
        return user

    # ------------------------------------------------------------ Benutzer
    def create_user(self, email: str, password: str, role: str, name: str = "") -> dict:
        email = normalize_email(email)
        check_password_rules(password)
        if role not in ROLES:
            raise AuthError("Unbekannte Rolle")
        if self._q("SELECT 1 FROM users WHERE email=?", (email,)):
            raise AuthError("E-Mail-Adresse ist schon vergeben")
        uid = self._x(
            "INSERT INTO users(email, name, role, pw_hash, created) VALUES (?,?,?,?,?)",
            (email, name.strip()[:80], role, hash_password(password), time.time()),
        )
        return self.get_user(uid)

    def get_user(self, uid: int) -> dict | None:
        rows = self._q("SELECT id, email, name, role, created FROM users WHERE id=?", (uid,))
        return dict(rows[0]) if rows else None

    def list_users(self) -> list[dict]:
        return [dict(r) for r in self._q("SELECT id, email, name, role, created FROM users ORDER BY email")]

    def delete_user(self, uid: int, acting_uid: int) -> None:
        user = self.get_user(uid)
        if not user:
            raise AuthError("Benutzer nicht gefunden")
        if uid == acting_uid:
            raise AuthError("Eigenes Konto kann nicht gelöscht werden")
        if user["role"] == "admin" and self._q("SELECT COUNT(*) c FROM users WHERE role='admin'")[0]["c"] <= 1:
            raise AuthError("Der letzte Admin kann nicht gelöscht werden")
        self._x("DELETE FROM sessions WHERE user_id=?", (uid,))
        self._x("DELETE FROM api_tokens WHERE user_id=?", (uid,))
        self._x("DELETE FROM users WHERE id=?", (uid,))

    def set_role(self, uid: int, role: str, acting_uid: int) -> dict:
        if role not in ROLES:
            raise AuthError("Unbekannte Rolle")
        user = self.get_user(uid)
        if not user:
            raise AuthError("Benutzer nicht gefunden")
        if uid == acting_uid and role != "admin":
            raise AuthError("Eigene Admin-Rechte können nicht entzogen werden")
        self._x("UPDATE users SET role=? WHERE id=?", (role, uid))
        return self.get_user(uid)

    def change_password(self, uid: int, old: str, new: str) -> None:
        rows = self._q("SELECT pw_hash FROM users WHERE id=?", (uid,))
        if not rows or not verify_password(old, rows[0]["pw_hash"]):
            raise AuthError("Bisheriges Passwort falsch")
        check_password_rules(new)
        self._x("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new), uid))

    def set_password(self, uid: int, new: str) -> None:
        """Admin setzt ein Passwort zurück (oder CLI)."""
        check_password_rules(new)
        self._x("UPDATE users SET pw_hash=? WHERE id=?", (hash_password(new), uid))
        self._x("DELETE FROM sessions WHERE user_id=?", (uid,))

    # ------------------------------------------------------------ Anmeldung
    def _limited(self, key: str) -> bool:
        now = time.time()
        recent = [t for t in self._failures.get(key, []) if now - t < 900]
        self._failures[key] = recent
        return len(recent) >= 10

    def login(self, email: str, password: str, client: str = "") -> dict:
        key = f"{client}|{(email or '').strip().lower()}"
        if self._limited(key) or self._limited(client):
            raise AuthError("Zu viele Fehlversuche – in 15 Minuten erneut versuchen")
        rows = self._q("SELECT id, pw_hash FROM users WHERE email=?", ((email or "").strip().lower(),))
        ok = bool(rows) and verify_password(password or "", rows[0]["pw_hash"])
        if not rows:
            verify_password(password or "", hash_password("dummy-password"))  # gleiche Laufzeit wie bei echtem Konto
        if not ok:
            self._failures.setdefault(key, []).append(time.time())
            self._failures.setdefault(client, []).append(time.time())
            raise AuthError("E-Mail oder Passwort falsch")
        self._failures.pop(key, None)
        return self.get_user(rows[0]["id"])

    def create_session(self, uid: int, ua: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        self._x(
            "INSERT INTO sessions(token_hash, user_id, created, expires, ua) VALUES (?,?,?,?,?)",
            (_token_hash(token), uid, now, now + SESSION_DAYS * 86400, ua[:120]),
        )
        self._x("DELETE FROM sessions WHERE expires < ?", (now,))
        return token

    def session_user(self, token: str | None) -> dict | None:
        if not token:
            return None
        rows = self._q(
            "SELECT u.id, u.email, u.name, u.role FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token_hash=? AND s.expires > ?",
            (_token_hash(token), time.time()),
        )
        return dict(rows[0]) if rows else None

    def end_session(self, token: str | None) -> None:
        if token:
            self._x("DELETE FROM sessions WHERE token_hash=?", (_token_hash(token),))

    # ------------------------------------------------------------ API-Tokens
    def create_api_token(self, uid: int, name: str) -> tuple[str, dict]:
        name = (name or "").strip()[:60]
        if not name:
            raise AuthError("Bitte einen Namen angeben, z. B. „Backup-Skript nas“")
        if len(self._q("SELECT id FROM api_tokens WHERE user_id=?", (uid,))) >= 20:
            raise AuthError("Höchstens 20 Tokens pro Benutzer")
        token = "qb_" + secrets.token_urlsafe(32)
        tid = self._x(
            "INSERT INTO api_tokens(user_id, name, token_hash, hint, created) VALUES (?,?,?,?,?)",
            (uid, name, _token_hash(token), token[:7] + "…" + token[-4:], time.time()),
        )
        return token, self.list_api_tokens(uid, tid=tid)[0]

    def list_api_tokens(self, uid: int | None = None, tid: int | None = None) -> list[dict]:
        sql = "SELECT t.id, t.name, t.hint, t.created, t.last_used, u.email FROM api_tokens t JOIN users u ON u.id = t.user_id"
        cond, args = [], []
        if uid is not None:
            cond.append("t.user_id=?")
            args.append(uid)
        if tid is not None:
            cond.append("t.id=?")
            args.append(tid)
        return [dict(r) for r in self._q(sql + (" WHERE " + " AND ".join(cond) if cond else "") + " ORDER BY t.created", tuple(args))]

    def delete_api_token(self, tid: int, uid: int, is_admin: bool) -> None:
        rows = self._q("SELECT user_id FROM api_tokens WHERE id=?", (tid,))
        if not rows or (rows[0]["user_id"] != uid and not is_admin):
            raise AuthError("Token nicht gefunden")
        self._x("DELETE FROM api_tokens WHERE id=?", (tid,))

    def token_user(self, token: str | None) -> dict | None:
        if not token or not token.startswith("qb_"):
            return None
        rows = self._q(
            "SELECT t.id tid, u.id, u.email, u.name, u.role FROM api_tokens t JOIN users u ON u.id = t.user_id WHERE t.token_hash=?",
            (_token_hash(token),),
        )
        if not rows:
            return None
        self._x("UPDATE api_tokens SET last_used=? WHERE id=?", (time.time(), rows[0]["tid"]))
        user = dict(rows[0])
        user.pop("tid")
        return user | {"via": "token"}

    # ------------------------------------------------------------ Einstellungen
    def get_setting(self, key: str, default=None):
        rows = self._q("SELECT value FROM settings WHERE key=?", (key,))
        return json.loads(rows[0]["value"]) if rows else default

    def set_setting(self, key: str, value) -> None:
        self._x(
            "INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, json.dumps(value)),
        )
