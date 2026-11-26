"""PBS-Abruf: Zertifikat per Fingerprint prüfen (selbst signiert, wie bei PBS üblich)."""

import asyncio
import datetime as dt
import hashlib
import http.server
import json
import ssl
import threading

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from app import main


@pytest.fixture(scope="module")
def pbs(tmp_path_factory):
    d = tmp_path_factory.mktemp("pbs")
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "pbs.test")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(1)
        .not_valid_before(now - dt.timedelta(days=1))
        .not_valid_after(now + dt.timedelta(days=1))
        .sign(key, hashes.SHA256())
    )
    (d / "c.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "k.pem").write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            seen.append((self.path, self.headers.get("Authorization")))
            body = json.dumps({"data": []}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(d / "c.pem", d / "k.pem")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    fp = hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()
    yield f"https://127.0.0.1:{srv.server_address[1]}", fp, seen
    srv.shutdown()


def test_matching_fingerprint_with_colons(pbs):
    url, fp, _ = pbs
    colons = ":".join(fp[i : i + 2] for i in range(0, 64, 2)).upper()
    r = asyncio.run(main.fetch_pbs("p", url, "id", "sec", colons))
    assert r["online"] is True


def test_wrong_fingerprint_sends_no_token(pbs):
    url, _, seen = pbs
    seen.clear()
    with pytest.raises(ValueError):
        asyncio.run(main.fetch_pbs("p", url, "id", "sec", "0" * 64))
    assert seen and all(auth is None for _, auth in seen)  # nur die Probe ohne Token


def test_without_check_still_works(pbs):
    url, _, _ = pbs
    assert asyncio.run(main.fetch_pbs("p", url, "id", "sec"))["online"] is True


def test_invalid_check_value():
    with pytest.raises(ValueError):
        main.pbs_verify("abc")
    assert main.pbs_verify("verify") == (True, "")
    assert main.pbs_verify("ca:/x.pem") == ("/x.pem", "")
