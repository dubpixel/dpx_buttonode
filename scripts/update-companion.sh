#!/usr/bin/env bash
# update-companion.sh
# On-device full Bitfocus Companion update (Full variant only), triggered
# from the web UI's Updates tab via `systemd-run --no-block` (see
# apply_component_update() in dpx-buttonode-ui.py). Deliberately NOT a reuse
# of install-companion.sh — that script unconditionally disables companion
# at the end (Satellite is the shipped default), which would silently
# switch a live device's active mode. This script only fetches + installs
# the new build and restarts the service if (and only if) companion is
# already the active mode.
#
# Installed at: /usr/local/bin/update-companion.sh
# Progress:     /var/log/dpx-update-companion.log (tailed by the Updates tab)
# Status:       /var/lib/dpx-update-companion.status (running/ok/failed)

set -uo pipefail

LOG_FILE="/var/log/dpx-update-companion.log"
STATUS_FILE="/var/lib/dpx-update-companion.status"
RELEASE_FILE="/etc/dpx-buttonode-release"

exec >>"$LOG_FILE" 2>&1
echo "=== update-companion.sh started $(date -u +%FT%TZ) ==="
echo "running" > "$STATUS_FILE"

fail() {
    echo "==> FAILED: $1"
    echo "failed" > "$STATUS_FILE"
    exit 1
}

# Dependencies are already present from the image build — this is just a
# cheap idempotent re-assert in case the running system has drifted.
apt-get update -q || fail "apt-get update failed"
apt-get install -yq git zip unzip curl libusb-1.0-0-dev libudev-dev wget python3 \
    libfontconfig1 libatomic1 || fail "dependency install failed"
apt-get install -yq libasound2t64 2>/dev/null || apt-get install -yq libasound2 2>/dev/null || true

# Download the official install script to a temp file (avoids curl|bash anti-pattern).
curl -fsSL \
    https://raw.githubusercontent.com/bitfocus/companion-pi/main/install.sh \
    -o /tmp/companion-update-install.sh || fail "could not download upstream install script"

chmod +x /tmp/companion-update-install.sh

# Downloads a pre-built arm64 binary in place under /opt/companion. Same
# assumption install-companion.sh relies on: a failed run here (network
# drop, disk full) does not tear down the previous working install first.
export COMPANION_BUILD="stable"
/tmp/companion-update-install.sh || fail "installer exited non-zero — previous install left in place"

rm -f /tmp/companion-update-install.sh

COMPANION_VERSION="unknown"
if [ -f "/opt/companion/BUILD" ]; then
    COMPANION_VERSION=$(cat /opt/companion/BUILD | tr -d '[:space:]')
elif [ -f "/opt/companion/package.json" ]; then
    COMPANION_VERSION=$(node -e "console.log(require('/opt/companion/package.json').version)" 2>/dev/null || echo "unknown")
fi

if [ "$COMPANION_VERSION" = "unknown" ]; then
    fail "new build produced no readable version — treating as a failed update, previous install left untouched"
fi

if grep -q '^COMPANION_VERSION=' "$RELEASE_FILE" 2>/dev/null; then
    sed -i "s/^COMPANION_VERSION=.*/COMPANION_VERSION=${COMPANION_VERSION}/" "$RELEASE_FILE"
else
    echo "COMPANION_VERSION=${COMPANION_VERSION}" >> "$RELEASE_FILE"
fi
echo "==> COMPANION_VERSION recorded: ${COMPANION_VERSION}"

# Only restart if companion is the currently active mode — never force-switch mode.
if [ "$(cat /etc/dpx-mode 2>/dev/null)" = "companion" ]; then
    systemctl restart companion
    echo "==> companion.service restarted (was active mode)"
else
    echo "==> companion not the active mode — new build installed but dormant"
fi

echo "ok" > "$STATUS_FILE"
echo "=== update-companion.sh finished $(date -u +%FT%TZ) ==="
