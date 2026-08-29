#!/usr/bin/env bash
# upload-mirror.sh
# LOCAL helper — run this on your machine when a new Bitfocus Buttons
# USB Relay version drops.
#
# What it does:
#   1. Uploads the .tar.gz to the 'buttons-deb-mirror' GitHub Release
#   2. The daily scheduled workflow (or a manual run) then detects
#      the new version and kicks off a full matrix build automatically.
#
# Usage:
#   ./scripts/upload-mirror.sh /path/to/bitfocus-buttons-usb-relay-headless_X.Y.Z_arm64.tar.gz
#
# Requirements:
#   gh  — GitHub CLI, logged in (brew install gh && gh auth login)

set -euo pipefail

MIRROR_TAG="buttons-deb-mirror"
REPO="dubpixel/dpx_buttonode"

# ── Validate input ───────────────────────────────────────────────────────────

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <path-to-tarball.tar.gz>"
    echo ""
    echo "Example:"
    echo "  $0 ~/Downloads/bitfocus-buttons-usb-relay-headless_0.2.0_arm64.tar.gz"
    exit 1
fi

TARBALL="$1"

if [[ ! -f "$TARBALL" ]]; then
    echo "ERROR: File not found: $TARBALL"
    exit 1
fi

if [[ "$TARBALL" != *.tar.gz ]]; then
    echo "ERROR: Expected a .tar.gz file, got: $(basename "$TARBALL")"
    exit 1
fi

FILENAME=$(basename "$TARBALL")
VERSION=$(echo "$FILENAME" | sed 's/.*_\(.*\)_arm64.tar.gz/\1/')

echo "==> File    : $FILENAME"
echo "==> Version : $VERSION"
echo "==> Target  : github.com/${REPO} @ ${MIRROR_TAG}"
echo ""

# ── Ensure mirror release exists ─────────────────────────────────────────────

if ! gh release view "$MIRROR_TAG" --repo "$REPO" &>/dev/null; then
    echo "==> Creating mirror release '${MIRROR_TAG}'..."
    gh release create "$MIRROR_TAG" \
        --repo "$REPO" \
        --title "Buttons USB Relay — Package Mirror" \
        --notes "Maintained mirror of the Bitfocus Buttons USB Relay ARM64 package.
Do not delete this release — it is used by the automated build pipeline.

To update: run \`scripts/upload-mirror.sh <new-tarball.tar.gz>\`" \
        --prerelease
    echo "==> Mirror release created."
fi

# ── Upload (replace existing asset with same name) ───────────────────────────

echo "==> Uploading to '${MIRROR_TAG}' release..."

gh release upload "$MIRROR_TAG" \
    --repo "$REPO" \
    --clobber \
    "$TARBALL"

echo ""
echo "==> Upload complete!"
echo ""
echo "    The daily build check will detect version ${VERSION} automatically."
echo "    To trigger a build immediately:"
echo ""
echo "      gh workflow run release-action.yaml --repo ${REPO}"
echo ""
