# Zusätzliche Healthchecks-Einstellungen (wird als hc/local_settings.py eingebunden).
# ALLOWED_HOSTS aus den öffentlichen Adressen ableiten, plus der interne Name für die App.
# Quelle für den Inhalt in compose.yaml (configs: hc-local-settings). Kein Dollarzeichen verwenden.
import os
from urllib.parse import urlparse

_hosts = {urlparse(os.getenv(name, "")).hostname for name in ("SITE_ROOT", "PING_ENDPOINT")}
_hosts |= {"healthchecks", "localhost", "127.0.0.1"}
_hosts |= {h.strip() for h in os.getenv("EXTRA_ALLOWED_HOSTS", "").split(",")}
ALLOWED_HOSTS = sorted(h for h in _hosts if h)
