#!/usr/bin/env bash
# Baut die Release-Dateien für eine Version nach dist/:
#   quietboard-vX.Y.Z.tar.gz   Installationspaket (entpacken, ADMIN_EMAIL=… ./install.sh)
#   install.sh, compose.yaml   einzeln, auf diese Version festgelegt
#   SHA256SUMS                 Prüfsummen aller Dateien in dist/
# Aufruf: scripts/make-dist.sh 0.1.0   (make dist VERSION=0.1.0; der Release-Workflow ruft es auch auf)
set -euo pipefail
cd "$(dirname "$0")/.."
v=${1:?Version angeben, z. B. 0.1.0}
v=v${v#v}
name="quietboard-$v"
rm -rf dist && mkdir -p "dist/$name/config" "dist/$name/hosts"

cp compose.yaml .env.example generate-env.sh install.sh LICENSE THIRD_PARTY_NOTICES.md CHANGELOG.md README.md "dist/$name/"
cp config/checks.example.yaml "dist/$name/config/"
cp hosts/hc hosts/hc.conf.example hosts/updates-report hosts/updates-report.service hosts/updates-report.timer \
  hosts/unattended-security.sh hosts/install-host.sh hosts/upgrade-host.sh hosts/synology-setup.sh hosts/dsm-report hosts/beszel-agent.compose.yml "dist/$name/hosts/"

# Auf diese Version festlegen: Image-Tag in compose.yaml, Version und Download-Quelle in install.sh
sed -i.bak "s#\${QB_VERSION:-latest}#\${QB_VERSION:-$v}#" "dist/$name/compose.yaml"
sed -i.bak "s#^QB_RELEASE=\"\"#QB_RELEASE=$v#" "dist/$name/install.sh"
rm -f "dist/$name"/*.bak
grep -q "quietboard:\${QB_VERSION:-$v}" "dist/$name/compose.yaml" || { echo "compose.yaml: Version nicht eingetragen" >&2; exit 1; }
grep -q "^QB_RELEASE=$v " "dist/$name/install.sh" || { echo "install.sh: Version nicht eingetragen" >&2; exit 1; }
chmod +x "dist/$name/install.sh" "dist/$name/generate-env.sh" "dist/$name/hosts/hc" "dist/$name/hosts/updates-report" "dist/$name/hosts/dsm-report" "dist/$name"/hosts/*.sh

# Reproduzierbares Archiv: feste Reihenfolge, Zeitstempel, Besitzer
mtime=$(git log -1 --format=%cI 2>/dev/null || date -u +%Y-%m-%dT%H:%M:%SZ)
if tar --version 2>/dev/null | grep -q GNU; then
  tar --sort=name --mtime="$mtime" --owner=0 --group=0 --numeric-owner -C dist -czf "dist/$name.tar.gz" "$name"
else
  tar -C dist -czf "dist/$name.tar.gz" "$name"   # macOS (bsdtar): ohne Reproduzierbarkeits-Optionen
fi
cp "dist/$name/install.sh" "dist/$name/compose.yaml" dist/
rm -rf "dist/${name:?}"
(cd dist && shasum -a 256 ./* | sed 's# \./# #' > SHA256SUMS)
ls -l dist
