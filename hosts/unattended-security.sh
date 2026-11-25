#!/bin/bash
# Automatische Sicherheitsupdates (nur Debian-Security), kein Auto-Reboot, Docker ausgenommen.
set -e
export DEBIAN_FRONTEND=noninteractive
apt-get install -y -q unattended-upgrades >/dev/null
cat > /etc/apt/apt.conf.d/52unattended-quietboard <<'CONF'
// QuietBoard: automatisch NUR Debian-Security. Alles andere beim Wartungstermin.
#clear Unattended-Upgrade::Origins-Pattern;
Unattended-Upgrade::Origins-Pattern { "origin=Debian,codename=${distro_codename}-security,label=Debian-Security"; };
Unattended-Upgrade::Package-Blacklist { "docker-ce"; "docker-ce-cli"; "containerd.io"; "docker-buildx-plugin"; "docker-compose-plugin"; "docker-ce-rootless-extras"; };
Unattended-Upgrade::Automatic-Reboot "false";
Unattended-Upgrade::Remove-Unused-Kernel-Packages "true";
CONF
cat > /etc/apt/apt.conf.d/20auto-upgrades <<'CONF'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
# needrestart: Dienste nur auflisten, nichts automatisch neu starten (Docker & Co. bleiben unberührt)
if [ -d /etc/needrestart ]; then
  mkdir -p /etc/needrestart/conf.d
  echo "\$nrconf{restart} = 'l';" > /etc/needrestart/conf.d/50-quietboard.conf
fi
o=$(unattended-upgrade --dry-run -d 2>&1 | grep -m1 -i "allowed origins" || true)
echo "OK unattended $(hostname): ${o:-Konfiguration gesetzt}"
