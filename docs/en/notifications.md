# Notifications

Principle: **success is silent, failures are loud.** QuietBoard notifies immediately when something fails – and otherwise once a day with the morning digest.

## When does it notify?

| Event | Source |
| --- | --- |
| Host offline (5 min), disk > 90 %, RAM > 95 % | Beszel alerts (set up automatically) |
| Job missing or reporting a failure (priority critical/normal) | Healthchecks → QuietBoard |
| Security updates pending for more than 48 h | QuietBoard |
| Proxmox failures without a matching job, messages containing error words | ingest |
| **Morning digest** at the configured time | QuietBoard |

Identical messages are combined for 30 minutes.

The language of these messages (German or English) is set under **System → Notifications → Language of messages**; `LANGUAGE=en` in `.env` sets the default.

## Channels

Configure under **System → Notifications**; every channel has “Send test”.

### Web Push (phone, desktop)

Needs **HTTPS** ([Network](install/network.md)). On the iPhone open the page in Safari, *Share → Add to Home Screen*, start the app from there and tap “Enable” under System. On Android/desktop the browser is enough.

### Mail

Put an SMTP server into `~/quietboard/.env` – the same block also serves Healthchecks:

```ini
SMTP_HOST=mail.example.org
SMTP_PORT=587          # 465 = SSL, 587 = STARTTLS
SMTP_TLS=True
SMTP_USER=quietboard@example.org
SMTP_PASSWORD=…
SMTP_FROM=quietboard@example.org
```

`docker compose up -d`, then enter the recipients under System (default: the first admin's address) and “Send test”.

### Signal (optional)

Own container in the profile `signal` with its own number (not your phone's – the number becomes its own Signal account):

1. `docker compose --profile signal up -d`
2. Solve the CAPTCHA: [signalcaptchas.org/registration/generate.html](https://signalcaptchas.org/registration/generate.html), copy the link behind “Open Signal” (`signalcaptcha://…`).
3. Register and confirm the code:
   ```bash
   docker compose exec signal-api curl -s -X POST -H 'Content-Type: application/json' \
     -d '{"captcha":"signalcaptcha://…"}' http://localhost:8080/v1/register/+1…
   docker compose exec signal-api curl -s -X POST http://localhost:8080/v1/register/+1…/verify/123456
   ```
4. In `.env`: `SIGNAL_NUMBER=+1…` and `SIGNAL_RECIPIENT=` (your own number or `group.…`), `docker compose up -d`.

### Morning digest

Time under System → Notifications. It is sent within a two-hour window after that time (in case the server is restarting), at most once a day – so after an installation in the evening you do not get a “morning digest” right away.

```text
☀️ Homelab 07:00 – all green
Jobs 12/12 · Hosts 6/6
Updates: 2 hosts · 7 packages · security 1
```

## Beszel and Healthchecks directly

Both keep their own notifications. Healthchecks mails check alerts itself through the “E-Mail” integration – so alerts arrive even if QuietBoard is down. Beszel reports to QuietBoard (webhook); your own webhooks in Beszel stay in place.
