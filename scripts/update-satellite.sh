#!/usr/bin/env bash
# update-satellite.sh
# On-device Companion Satellite update, triggered from the web UI's Updates
# tab via `systemd-run --no-block` (see apply_component_update() in
# dpx-buttonode-ui.py). Deliberately NOT a reuse of install-satellite.sh —
# that script unconditionally disables Buttons, enables satellite, and
# writes /etc/dpx-mode, which would silently switch a live device's active
# mode. This script only fetches + installs the new build and restarts the
# service if (and only if) satellite is already the active mode.
#
# Installed at: /usr/local/bin/update-satellite.sh
# Progress:     /var/log/dpx-update-satellite.log (tailed by the Updates tab)
# Status:       /var/lib/dpx-update-satellite.status (running/ok/failed)

set -uo pipefail

LOG_FILE="/var/log/dpx-update-satellite.log"
STATUS_FILE="/var/lib/dpx-update-satellite.status"
RELEASE_FILE="/etc/dpx-buttonode-release"

exec >>"$LOG_FILE" 2>&1
echo "=== update-satellite.sh started $(date -u +%FT%TZ) ==="
echo "running" > "$STATUS_FILE"

fail() {
    echo "==> FAILED: $1"
    echo "failed" > "$STATUS_FILE"
    exit 1
}

# Download the official install script to a temp file (avoids curl|bash anti-pattern).
curl -fsSL \
    https://raw.githubusercontent.com/bitfocus/companion-satellite/main/pi-image/install.sh \
    -o /tmp/satellite-update-install.sh || fail "could not download upstream install script"

chmod +x /tmp/satellite-update-install.sh

# Rebuilds in place under /opt/companion-satellite. Relying on the same
# assumption install-satellite.sh does: if this exits non-zero partway
# (network drop, disk full), the upstream installer does not tear down the
# previous working install first — so a failed run here just leaves the old
# build running, no separate rollback needed.
export SATELLITE_BUILD="stable"
/tmp/satellite-update-install.sh || fail "installer exited non-zero — previous install left in place"

rm -f /tmp/satellite-update-install.sh

SAT_VERSION=$(/opt/fnm/aliases/default/bin/node -e \
    "console.log(require('/opt/companion-satellite/satellite/package.json').version)" 2>/dev/null || echo "unknown")

if [ "$SAT_VERSION" = "unknown" ]; then
    fail "new build produced no readable version — treating as a failed update, previous install left untouched"
fi

if grep -q '^SATELLITE_VERSION=' "$RELEASE_FILE" 2>/dev/null; then
    sed -i "s/^SATELLITE_VERSION=.*/SATELLITE_VERSION=${SAT_VERSION}/" "$RELEASE_FILE"
else
    echo "SATELLITE_VERSION=${SAT_VERSION}" >> "$RELEASE_FILE"
fi
echo "==> SATELLITE_VERSION recorded: ${SAT_VERSION}"

# Only restart if satellite is the currently active mode — never force-switch mode.
if [ "$(cat /etc/dpx-mode 2>/dev/null)" = "satellite" ]; then
    systemctl restart satellite
    echo "==> satellite.service restarted (was active mode)"
else
    echo "==> satellite not the active mode — new build installed but dormant"
fi

echo "ok" > "$STATUS_FILE"
echo "=== update-satellite.sh finished $(date -u +%FT%TZ) ==="
