# Healthchecks-Ersteinrichtung ohne GUI. Läuft im Healthchecks-Image per `manage.py shell` (Django-Kontext).
# Legt Admin, Projekt, API-/Ping-Keys und die Integration "E-Mail" an und schreibt die Klartext-Keys
# nach /tmp/hc.json. Der Aufrufer (healthchecks-init in compose.yaml) legt die Datei mit Rechten 600
# für die App ab. Healthchecks speichert API-Keys nur gehasht – sie lassen sich später nicht mehr auslesen.
#
# Zweiter Start: Ist die Ziel-Datei vorhanden und das Projekt hat einen Key, passiert nichts.
# Übernahme (HC_API_KEY und HC_PING_KEY in .env): passiert ebenfalls nichts.
# Fehlt die Datei (z. B. Volume der App gelöscht), werden neue Keys erzeugt.
#
# Quelle für den Inhalt in compose.yaml (configs: hc-bootstrap). Nach Änderungen:
#   python3 scripts/sync_compose_configs.py
# Kein Dollarzeichen verwenden: Compose würde es als Variable lesen.
import json
import os
import sys
import uuid

from django.contrib.auth.models import User
from hc.accounts.models import Profile, Project
from hc.api.models import Channel

TARGET = "/bootstrap/healthchecks.json"
OUT = "/tmp/hc.json"

# Übernahme einer bestehenden Installation: Keys stehen in .env (HC_API_KEY, HC_PING_KEY) → nichts anfassen,
# sonst würden API-Key und Admin-Passwort des vorhandenen Projekts neu gesetzt.
if os.environ.get("HC_API_KEY") and os.environ.get("HC_PING_KEY"):
    print("healthchecks-init: vorhandene Keys aus .env, keine Änderung (Übernahme)")
    sys.exit(0)

email = os.environ["ADMIN_EMAIL"].strip().lower()
password = os.environ["ADMIN_PASSWORD"]
site_name = os.environ.get("SITE_NAME") or "Homelab"

user = User.objects.filter(email=email).first()
project = Project.objects.filter(owner=user).order_by("id").first() if user else None

if os.path.exists(TARGET) and project is not None and project.api_key:
    print("healthchecks-init: bereits eingerichtet, keine Änderung")
    sys.exit(0)

if user is None:
    user = User(username=str(uuid.uuid4())[:30], email=email)
user.is_staff = True
user.is_superuser = True
user.set_password(password)
user.save()
Profile.objects.for_user(user)

if project is None:
    project = Project(owner=user, name=site_name, badge_key=user.username)
project.show_slugs = True
api_key = project.set_api_key()
api_key_readonly = project.set_api_key_readonly()
ping_key = project.ping_key or project.set_ping_key()
project.save()

if not Channel.objects.filter(project=project, kind="email").exists():
    Channel.objects.create(project=project, kind="email", name="E-Mail", value=email, email_verified=True)

with open(OUT, "w", encoding="utf-8") as fh:
    json.dump(
        {
            "project": str(project.code),
            "api_key": api_key,
            "api_key_readonly": api_key_readonly,
            "ping_key": ping_key,
            "admin_email": email,
        },
        fh,
    )
print(f"healthchecks-init: Projekt '{project.name}' eingerichtet, Keys übergeben")
