#!/usr/bin/env bash
# install-satellite.sh
# Runs inside the Armbian image chroot via Packer.
# Installs Companion Satellite (headless) using the official install script,
# then disables it by default. Mode switching is handled by dpx-buttonode-ui.
#
# Satellite service name: satellite
# Satellite REST API:     http://localhost:9999/api/config
# Satellite config file:  /boot/satellite-config (COMPANION_IP= / COMPANION_PORT=)

set -euo pipefail

echo "==> Installing Companion Satellite (headless, stable build)"

# Download the official install script to a temp file (avoids curl|bash anti-pattern)
curl -fsSL \
    https://raw.githubusercontent.com/bitfocus/companion-satellite/main/pi-image/install.sh \
    -o /tmp/satellite-official-install.sh

chmod +x /tmp/satellite-official-install.sh

# Run official install — builds from source inside the chroot.
# Requires internet access (provided by Packer's /run/systemd bind mount).
# Sets SATELLITE_BUILD=stable to pin to the latest stable release.
export SATELLITE_BUILD="stable"
/tmp/satellite-official-install.sh

rm -f /tmp/satellite-official-install.sh

echo "==> Companion Satellite installed"

# ── Default mode: Satellite ────────────────────────────────────────────────────
# Only one of buttons/satellite/companion runs at a time. Default mode is
# Companion Satellite, not Buttons — most units are meant to sit in a
# Companion-driven setup out of the box; Buttons is the opt-in mode now.
# The Buttons .deb's own postinst auto-enables+starts
# bitfocus-buttons-usb-relay.service — undo that here since this script
# runs after install-buttons.sh and is where the real default gets decided.
# dpx-buttonode-ui Mode tab handles enable/disable at runtime either way.
systemctl disable --now bitfocus-buttons-usb-relay
systemctl enable satellite
echo "==> satellite.service: enabled (default mode)"
echo "==> bitfocus-buttons-usb-relay.service: disabled (opt-in via Mode tab)"

# ── Fix HID device permissions ────────────────────────────────────────────────
# The Buttons USB Relay package owns /dev/hidraw* via udev GROUP="buttons".
# Satellite runs as the 'satellite' user — it needs to be in the buttons group
# to open Stream Deck / HID surfaces when in satellite mode.
usermod -aG buttons satellite
echo "==> satellite user added to 'buttons' group (HID device access)"

# ── Write mode persistence file ───────────────────────────────────────────────
echo "satellite" > /etc/dpx-mode
echo "==> /etc/dpx-mode: satellite (default)"

# ── Record satellite version in build metadata ────────────────────────────────
SAT_VERSION=$(/opt/fnm/aliases/default/bin/node -e \
  "console.log(require('/opt/companion-satellite/satellite/package.json').version)" 2>/dev/null || echo "unknown")
echo "SATELLITE_VERSION=${SAT_VERSION}" >> /etc/dpx-buttonode-release
echo "==> Satellite version: ${SAT_VERSION}"

# ── Verify install ────────────────────────────────────────────────────────────
if [ -d "/opt/companion-satellite" ]; then
    echo "==> Companion Satellite: OK (/opt/companion-satellite exists)"
else
    echo "==> WARNING: /opt/companion-satellite not found — satellite may not have installed correctly"
    echo "==> Run 'sudo satellite-update' on the device to recover"
fi

systemctl is-enabled satellite.service 2>/dev/null && echo "==> Service: enabled (correct)" \
    || echo "==> Service: disabled (unexpected)"
systemctl is-enabled bitfocus-buttons-usb-relay.service >/dev/null 2>&1 && echo "==> WARNING: bitfocus-buttons-usb-relay still enabled" \
    || echo "==> bitfocus-buttons-usb-relay.service: disabled (correct)"
