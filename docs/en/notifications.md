# Notifications

Principle: **success is silent, failures are loud.** QuietBoard notifies immediately when something fails – and otherwise once a day with the morning digest.

## When does it notify?

| Event | Source |
| --- | --- |
| Host offline (5 min), disk > 90 %, RAM > 95 % | Beszel alerts (set up automatically) |
| Job missing or reporting a failure (priority critical/normal), and when it is green again | QuietBoard (or Healthchecks, see below) |
| Security updates pending for more than 48 h | QuietBoard |
| Proxmox failures without a matching job, messages containing error words | ingest |
| Healthchecks or Beszel unreachable for more than 15 minutes | QuietBoard |
| QuietBoard itself stopped running | Healthchecks (heartbeat `quietboard/app`) |
| **Morning digest** at the configured time | QuietBoard |

The same message (same source, same state) is sent only once within 30 minutes; a change – e.g. "down" after "up" – always gets through. This also holds across restarts. If no channel could deliver, QuietBoard retries with the next poll.

## Job alerts: QuietBoard or Healthchecks

Under **System → Job alerts** you choose who reports failed jobs:

- **QuietBoard** (default for new installations): uniform, short messages via all channels above (push, mail, signal), several failures of one poll in one message. The mail recipients from the settings apply here too.
- **Healthchecks**: the integrations assigned to the individual jobs in Healthchecks (QuietBoard's behaviour up to v0.5). Default when an existing Healthchecks installation was adopted – nothing changes there after the update.

When switching to QuietBoard, the page offers to detach the integrations from the jobs so nothing arrives twice. The integrations themselves stay in Healthchecks; the previous assignment is backed up, and switching back to "Healthchecks" restores it.

**Heartbeat:** QuietBoard creates the check `quietboard/app` in Healthchecks and pings it on every poll. Only this check always keeps the Healthchecks integrations. If QuietBoard is down for more than about 15 minutes, Healthchecks reports it itself. It does not appear in the job list; its state is shown under System.

### What messages look like

```text
🔴 docker01/backup-restic failed
exit code 1 · today 03:12 · kritisch
Last lines:
  ssh: connect to host nas port 22: No route to host
→ https://status.example.org/?c=…
```

```text
🔴 docker01/backup-restic overdue
No ping since yesterday 03:04 (schedule 0 3 * * *, grace 1h)
```

```text
✅ docker01/backup-restic is OK again
Was down for 6 h 12 min · run took 14 min
```

Mails also contain up to 30 log lines. QuietBoard learns the exit code from `hc run` (v0.6.0 on the host; older `hc` only report "failure reported"). The link appears when `PUBLIC_URL` is set in `.env`.

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

Beszel reports to QuietBoard (webhook); your own webhooks in Beszel stay in place. Healthchecks reports via its integrations depending on the setting above – but always at least the failure of QuietBoard itself (heartbeat).
