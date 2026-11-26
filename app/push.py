"""Web Push (RFC 8030/8291/8292) ohne Zusatzbibliotheken: VAPID-JWT (ES256) + aes128gcm.

Schlüssel erzeugen:  python -m app.push genkey   → Zeile VAPID_PRIVATE_KEY=… für .env
"""

from __future__ import annotations

import base64
import json
import os
import struct
import sys
import time
from urllib.parse import urlparse

import jwt
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

# Nur echte Push-Dienste der Browserhersteller annehmen (kein SSRF über gefälschte Endpoints)
ALLOWED_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ub64u(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _hkdf(salt: bytes, ikm: bytes, info: bytes, length: int) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=length, salt=salt, info=info).derive(ikm)


def _pub_raw(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


class Vapid:
    def __init__(self, private_b64: str, subject: str):
        d = int.from_bytes(ub64u(private_b64), "big")
        self.key = ec.derive_private_key(d, ec.SECP256R1())
        self.public_b64 = b64u(_pub_raw(self.key.public_key()))
        self.subject = subject

    def headers(self, endpoint: str) -> dict:
        u = urlparse(endpoint)
        token = jwt.encode(
            {"aud": f"{u.scheme}://{u.netloc}", "exp": int(time.time()) + 12 * 3600, "sub": self.subject}, self.key, algorithm="ES256"
        )
        return {"Authorization": f"vapid t={token}, k={self.public_b64}"}


def valid_subscription(sub: dict) -> bool:
    try:
        u = urlparse(sub["endpoint"])
        keys = sub["keys"]
        return (
            u.scheme == "https"
            and any(u.hostname == h or u.hostname.endswith("." + h) for h in ALLOWED_HOSTS)
            and len(ub64u(keys["p256dh"])) == 65
            and len(ub64u(keys["auth"])) == 16
        )
    except Exception:
        return False


def encrypt(payload: bytes, p256dh_b64: str, auth_b64: str) -> bytes:
    """RFC 8291 / RFC 8188 (aes128gcm), ein Record."""
    ua_pub_raw, auth = ub64u(p256dh_b64), ub64u(auth_b64)
    ua_pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ua_pub_raw)
    as_priv = ec.generate_private_key(ec.SECP256R1())
    as_pub_raw = _pub_raw(as_priv.public_key())
    shared = as_priv.exchange(ec.ECDH(), ua_pub)
    ikm = _hkdf(auth, shared, b"WebPush: info\x00" + ua_pub_raw + as_pub_raw, 32)
    salt = os.urandom(16)
    cek = _hkdf(salt, ikm, b"Content-Encoding: aes128gcm\x00", 16)
    nonce = _hkdf(salt, ikm, b"Content-Encoding: nonce\x00", 12)
    ct = AESGCM(cek).encrypt(nonce, payload + b"\x02", None)
    return salt + struct.pack("!IB", 4096, len(as_pub_raw)) + as_pub_raw + ct


MAX_PAYLOAD = 3000  # Bytes vor der Verschlüsselung; ein Record fasst 4096, Push-Dienste erlauben ~4 KB


def payload(message: dict) -> bytes:
    """JSON für die Mitteilung, notfalls gekürzt – nach Bytes, nicht nach Zeichen (Emojis/Umlaute zählen mehrfach)."""
    message = {**message, "title": str(message.get("title", ""))[:150], "body": str(message.get("body", ""))[:1500]}
    data = json.dumps(message, ensure_ascii=False).encode()
    while len(data) > MAX_PAYLOAD and message["body"]:
        message["body"] = message["body"][: max(0, len(message["body"]) - max(20, (len(data) - MAX_PAYLOAD) // 2))].rstrip() + "…"
        if len(message["body"]) <= 1:
            message["body"] = ""
        data = json.dumps(message, ensure_ascii=False).encode()
    return data


def request_args(vapid: Vapid, sub: dict, message: dict, ttl: int = 86400, urgency: str = "high") -> dict:
    data = payload(message)
    body = encrypt(data, sub["keys"]["p256dh"], sub["keys"]["auth"])
    headers = {
        **vapid.headers(sub["endpoint"]),
        "TTL": str(ttl),
        "Urgency": urgency,
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
    }
    return {"url": sub["endpoint"], "content": body, "headers": headers}


if __name__ == "__main__" and sys.argv[1:] == ["genkey"]:
    k = ec.generate_private_key(ec.SECP256R1())
    print("VAPID_PRIVATE_KEY=" + b64u(k.private_numbers().private_value.to_bytes(32, "big")))
