"""Schutzschicht vor der App (reines ASGI, vor dem Router):

- Vertraute Proxys: Weitergeleitete Header (X-Forwarded-For/-Proto/-Host, CF-Connecting-IP) gelten nur, wenn die
  **echte** Gegenstelle ein vertrauter Proxy ist (TRUSTED_PROXIES: CIDRs und/oder Containernamen, Standard
  `cloudflared`). Die echte Gegenstelle bleibt in scope["qb_peer"] für Prüfungen wie den Beszel-Webhook.
- Größenlimit für Anfragekörper: Oberfläche/Anmeldung 1 MB (sonst 413); Ingest wird nie abgelehnt, sondern gekürzt –
  ein langes Log darf keinen Alarm verhindern.
- Sicherheits-Header auf allen Antworten.
- Zugriffslog ohne Token (Pfad-Token der signal-api-Kompatibilität, ?token=).
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import re
import socket
import time

# Größe des Anfragekörpers je Route. JSON wird beim Einlesen etwa 20-mal so groß (Python-Objekte) – ohne enge
# Grenze für die Anmelderouten könnte jeder ohne Konto den Container (128 MB) mit wenigen Anfragen sprengen.
AUTH_BODY_LIMIT = 16_000  # /api/auth/* (Login, Einrichtung) – ohne Anmeldung erreichbar
IMPORT_BODY_LIMIT = 250_000  # YAML-Import (bis 200 000 Zeichen)
INGEST_BODY_LIMIT = 1_000_000  # Meldungen von Hosts (PVE-Logs werden ohnehin gekürzt)
BODY_LIMIT = 64_000  # alles andere
INGEST_PREFIX = "/api/ingest/"


def body_limit(path: str) -> int:
    if path.startswith("/api/auth/"):
        return AUTH_BODY_LIMIT
    if path == "/api/config/import":
        return IMPORT_BODY_LIMIT
    if path.startswith(INGEST_PREFIX):
        return INGEST_BODY_LIMIT
    return BODY_LIMIT


SECURITY_HEADERS = [
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"frame-ancestors 'none'"),
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"same-origin"),
]


# ---------------------------------------------------------------- Vertraute Proxys
class TrustedProxies:
    """CIDRs werden direkt geprüft, Namen per DNS aufgelöst (30 s zwischengespeichert).

    Die Auflösung läuft im Hintergrund (Thread-Pool der Event-Loop): Eine Anfrage liest nur den Zwischenspeicher und
    wartet nie auf DNS – sonst stünde bei gestörtem Upstream-DNS die ganze App. Einzige Ausnahme ist die allererste
    Anfrage nach dem Start (`ready`)."""

    TTL = 30
    TIMEOUT = 5

    def __init__(self, spec: str):
        self.nets: list = []
        self.names: list[str] = []
        for item in (s.strip() for s in spec.split(",")):
            if not item:
                continue
            try:
                self.nets.append(ipaddress.ip_network(item, strict=False))
            except ValueError:
                self.names.append(item)
        self._cache: tuple[float | None, set[str]] = (None, set())
        self._task: asyncio.Task | None = None

    def _lookup_sync(self) -> set[str]:
        ips: set[str] = set()
        for name in self.names:
            try:
                ips |= {ai[4][0] for ai in socket.getaddrinfo(name, None)}
            except OSError:
                pass
        return ips

    async def update(self) -> None:
        loop = asyncio.get_running_loop()
        ips: set[str] = set()
        for name in self.names:
            try:
                infos = await asyncio.wait_for(loop.getaddrinfo(name, None), self.TIMEOUT)
                ips |= {ai[4][0] for ai in infos}
            except (OSError, TimeoutError):
                pass
        self._cache = (time.monotonic(), ips)

    async def ready(self) -> None:
        """Nur bis zur ersten Auflösung warten (direkt nach dem Start), danach sofort zurück."""
        if self.names and self._cache[0] is None:
            await self.update()

    def ips(self) -> set[str]:
        at, ips = self._cache
        if at is None or time.monotonic() - at >= self.TTL:
            self._kick()
        return self._cache[1]

    def _kick(self) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:  # ohne Event-Loop (Werkzeuge, Tests): direkt auflösen
            self._cache = (time.monotonic(), self._lookup_sync())
            return
        if self._task and not self._task.done() and self._task.get_loop() is loop:
            return
        self._task = loop.create_task(self.update())

    def __contains__(self, ip: str) -> bool:
        if not ip:
            return False
        try:
            addr = ipaddress.ip_address(ip)
        except ValueError:
            return False
        if any(addr in n for n in self.nets):
            return True
        return bool(self.names) and ip in self.ips()


def _header(headers: list, name: bytes) -> str:
    for k, v in headers:
        if k == name:
            return v.decode("latin-1").strip()
    return ""


def _valid_ip(s: str) -> str:
    try:
        return str(ipaddress.ip_address(s.strip().strip("[]")))
    except ValueError:
        return ""


class ShieldMiddleware:
    def __init__(self, app, trusted: TrustedProxies, cloudflare: TrustedProxies | None = None):
        self.app = app
        self.trusted = trusted
        # CF-Connecting-IP setzt nur Cloudflare (cloudflared). Hinter Nginx Proxy Manager, Caddy & Co. könnte der
        # Client den Header selbst mitschicken – dort gilt nur X-Forwarded-For.
        self.cloudflare = cloudflare

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)
        await self.trusted.ready()
        if self.cloudflare:
            await self.cloudflare.ready()
        headers = scope.get("headers") or []
        peer = (scope.get("client") or ("", 0))[0]
        scope["qb_peer"] = peer
        scope["qb_forwarded_host"] = ""
        scope["qb_untrusted_forward"] = False
        if peer in self.trusted:
            # Cloudflare liefert die echte Adresse in CF-Connecting-IP; sonst der letzte Eintrag von X-Forwarded-For
            # (den hat der vertraute Proxy selbst angehängt – weiter links steht, was der Client behauptet).
            client = _valid_ip(_header(headers, b"cf-connecting-ip")) if self.cloudflare and peer in self.cloudflare else ""
            if not client:
                xff = [p for p in _header(headers, b"x-forwarded-for").split(",") if p.strip()]
                client = _valid_ip(xff[-1]) if xff else ""
            if client:
                scope["client"] = (client, 0)
            proto = _header(headers, b"x-forwarded-proto").lower()
            if proto in ("http", "https"):
                scope["scheme"] = "https" if proto == "https" else "http"
            scope["qb_forwarded_host"] = _header(headers, b"x-forwarded-host").split(",")[0].strip()
        elif _header(headers, b"x-forwarded-proto") or _header(headers, b"x-forwarded-for"):
            # Ein Proxy, der nicht in TRUSTED_PROXIES steht: Header werden ignoriert (richtig), aber dann gilt die
            # Verbindung als http – Cookies ohne Secure, erzeugte Adressen mit http://. Die App warnt darüber.
            scope["qb_untrusted_forward"] = True
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        path = scope.get("path", "")
        ingest = path.startswith(INGEST_PREFIX)
        limit = body_limit(path)
        length = _header(headers, b"content-length")
        if not ingest and length.isdigit() and int(length) > limit:
            await _send_simple(send, 413, b'{"detail":"Anfrage zu gro\\u00df"}')
            return

        seen = 0

        async def limited_receive():
            nonlocal seen
            if seen > limit:  # Rest nicht mehr lesen – Körper ist beim Limit abgeschnitten
                return {"type": "http.request", "body": b"", "more_body": False}
            msg = await receive()
            if msg["type"] == "http.request":
                body = msg.get("body", b"")
                if seen + len(body) > limit:
                    body = body[: max(0, limit - seen)]
                    seen = limit + 1
                    return {"type": "http.request", "body": body, "more_body": False}
                seen += len(body)
            return msg

        async def send_with_headers(msg):
            if msg["type"] == "http.response.start":
                have = {k.lower() for k, _ in msg.get("headers", [])}
                msg["headers"] = list(msg.get("headers", [])) + [h for h in SECURITY_HEADERS if h[0] not in have]
            await send(msg)

        await self.app(scope, limited_receive, send_with_headers)


async def _send_simple(send, status: int, body: bytes) -> None:
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), *SECURITY_HEADERS],
        }
    )
    await send({"type": "http.response.body", "body": body})


# ---------------------------------------------------------------- Zugriffslog ohne Token
_TOKEN_IN_PATH = re.compile(r"(/api/ingest/signal/)[^/?\s]+")
_TOKEN_IN_QUERY = re.compile(r"((?:^|[?&])token=)[^&\s]*")
# Ausgehende Anfragen (httpx): Ping-Key bzw. UUID von Healthchecks, Push-Adressen der Browser (sind selbst Zugangsdaten)
_PING_KEY = re.compile(r"(/ping/)[^/?\s\"]+")
_PUSH_ENDPOINT = re.compile(r"(https://[^/\s\"]*(?:push|fcm)[^/\s\"]*/)[^\s\"]+")


def mask_tokens(s: str) -> str:
    s = _TOKEN_IN_QUERY.sub(r"\1***", _TOKEN_IN_PATH.sub(r"\1***", s))
    return _PUSH_ENDPOINT.sub(r"\1***", _PING_KEY.sub(r"\1***", s))


class TokenFilter(logging.Filter):
    """uvicorn.access übergibt (client, method, full_path, http_version, status) als args, httpx die URL als Objekt."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(mask_tokens(str(a)) if isinstance(a, str) or type(a).__name__ == "URL" else a for a in record.args)
        elif isinstance(record.msg, str):
            record.msg = mask_tokens(record.msg)
        return True


def install_log_filter() -> None:
    logging.getLogger("uvicorn.access").addFilter(TokenFilter())
    logging.getLogger("httpx").addFilter(TokenFilter())
