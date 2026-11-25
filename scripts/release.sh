#!/usr/bin/env bash
# Release erstellen:  make release VERSION=0.1.0   (oder 0.2.0-rc1 für eine Vorabversion)
# 1. prüft: auf main, sauber, aktuell mit origin, CI auf diesem Commit grün
# 2. CHANGELOG.md: "## Unveröffentlicht" wird zu "## 0.1.0 – Datum", darüber ein neuer leerer Abschnitt
# 3. Commit + annotierter Tag v0.1.0, Push → der Image-Workflow baut :v0.1.0 :v0.1 :v0 :latest und das GitHub-Release
#    mit Installationspaket, install.sh, compose.yaml, SBOM und SHA256SUMS (scripts/make-dist.sh)
set -euo pipefail
cd "$(dirname "$0")/.."
v=${1:?Version angeben, z. B. 0.1.0}
v=${v#v}
[[ "$v" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?$ ]] || { echo "Version muss X.Y.Z (optional -rc1) sein" >&2; exit 1; }
tag="v$v"
[ "$(git branch --show-current)" = main ] || { echo "Nur von main aus" >&2; exit 1; }
[ -z "$(git status --porcelain)" ] || { echo "Arbeitsverzeichnis nicht sauber" >&2; exit 1; }
git fetch -q origin main --tags
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || { echo "main ist nicht auf dem Stand von origin/main" >&2; exit 1; }
git rev-parse -q --verify "refs/tags/$tag" >/dev/null && { echo "Tag $tag gibt es schon" >&2; exit 1; }
if command -v gh >/dev/null; then
  ci=$(gh run list -w CI --commit "$(git rev-parse HEAD)" --json conclusion -q '.[0].conclusion' 2>/dev/null || true)
  [ "$ci" = success ] || { echo "CI auf diesem Commit nicht grün (${ci:-kein Lauf})" >&2; exit 1; }
fi
grep -q '^## Unveröffentlicht' CHANGELOG.md || { echo "CHANGELOG.md: Abschnitt '## Unveröffentlicht' fehlt" >&2; exit 1; }
today=$(date +%Y-%m-%d)
awk -v v="$v" -v d="$today" '/^## Unveröffentlicht/ && !done {print "## Unveröffentlicht\n"; print "## " v " – " d; done=1; next} {print}' \
  CHANGELOG.md > CHANGELOG.md.tmp && mv CHANGELOG.md.tmp CHANGELOG.md
git add CHANGELOG.md
git commit -q -m "chore(release): $tag"
git tag -a "$tag" -m "QuietBoard $tag"
git push -q origin main "$tag"
echo "Release $tag angestoßen – Image-Workflow: gh run watch \$(gh run list -w Image -L 1 --json databaseId -q '.[0].databaseId')"
