# FAQ and troubleshooting

**The app shows “Source unavailable: healthchecks” or “beszel”.**
`docker compose ps` – are all services running? `docker compose logs healthchecks-init beszel-init status` shows the setup. Shortly after a restart the message is normal; it disappears with the next poll.

**Where do I find the setup code?**
`docker compose logs status | grep Einrichtungscode`. Once an account exists there is no code any more – then use the [emergency CLI](accounts.md#forgot-password-admin-locked-out).

**A host does not show up.**
On the host: `systemctl status beszel-agent` or `docker logs beszel-agent`. Does it reach `BESZEL_PUBLIC_URL` (port 8090)? Is the address right (VPN, firewall)? After an address change, run the installer command again. And remember: the QuietBoard server itself only appears after you run the host command on it, too.

**Chrome on macOS shows `ERR_ADDRESS_UNREACHABLE` for the app.**
macOS requires the “Local Network” permission for apps that reach devices in your LAN: *System Settings → Privacy & Security → Local Network → Google Chrome* on, then restart Chrome.

**Healthchecks answers “Bad Request (400)”.**
The address used is not in `HC_PUBLIC_URL`/`HC_PING_ENDPOINT`. Allow more names with `HC_EXTRA_HOSTS=name1,name2` in `.env` – or adjust the addresses – and `docker compose up -d`.

**Push notifications cannot be enabled.**
Web Push needs HTTPS. On the iPhone also the installed app (Add to Home Screen) – it does not work in a normal Safari tab.

**I do not get any mail.**
`SMTP_*` set in `.env` and `docker compose up -d`? Under System → Notifications “Send test”; errors are in `docker compose logs status`.

**How much memory does QuietBoard need?**
About 350 MB for the whole stack, about 530 MB with Signal. 1 GB RAM is enough, 2 GB is comfortable.

**Can I keep using my existing Healthchecks/Beszel?**
Yes – see [Adopting an existing installation](install/adopt.md). Checks, history, hosts and agents stay; nothing changes on the hosts.

**Is QuietBoard a replacement for Uptime Kuma?**
No, rather a complement: Uptime Kuma checks whether services are reachable. QuietBoard takes care of hosts, jobs (backups!) and updates – and bundles everything into one calm message.
