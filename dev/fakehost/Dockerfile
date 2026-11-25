# Simulierter Debian-Host für die lokale Entwicklung.
# Führt das echte hosts/updates-report aus (per Bind-Mount) und schickt gelegentlich Meldungen.
FROM debian:13-slim
RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends curl ca-certificates >/dev/null \
    && rm -rf /var/lib/apt/lists/*
COPY run.sh /run.sh
CMD ["bash", "/run.sh"]
