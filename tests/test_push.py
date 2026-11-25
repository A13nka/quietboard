import base64

from app import push


def _b64(n: int) -> str:
    return base64.urlsafe_b64encode(b"\x04" * n).rstrip(b"=").decode()


def test_rejects_foreign_push_endpoint():
    sub = {"endpoint": "https://evil.example.org/x", "keys": {"p256dh": _b64(65), "auth": _b64(16)}}
    assert not push.valid_subscription(sub)


def test_accepts_browser_push_endpoint():
    sub = {"endpoint": "https://fcm.googleapis.com/fcm/send/abc", "keys": {"p256dh": _b64(65), "auth": _b64(16)}}
    assert push.valid_subscription(sub)
