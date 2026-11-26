# Security policy

## Reporting a vulnerability

Please **do not open a public issue**. Use GitHub's private reporting instead: *Security → Report a vulnerability* in this repository. You will get an answer within a few days; fixes are released as soon as possible and credited if you wish.

## Supported versions

Only the latest release (`latest`) receives security fixes during 0.x.

## Design notes

- No dashboard without login: local accounts (scrypt, session cookie, login throttling, CSRF origin check) or Cloudflare Access.
- Hosts authenticate with the ingest token, normally in a header. Senders that can only use URLs (`?token=`, `/api/ingest/signal/<token>`) work too; the token is masked in the access log.
- Forwarded headers (`X-Forwarded-For`, …) are only honoured from trusted proxies (`TRUSTED_PROXIES`).
- Secrets are generated on install (`.env`, mode 600); Healthchecks API keys are handed to the app via a file with mode 600.
- The Beszel webhook only accepts the Beszel container or a valid token.
- Images are built in CI with a license check; each release ships an SPDX SBOM and SHA-256 checksums.
