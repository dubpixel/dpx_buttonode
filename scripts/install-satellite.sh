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

# ── Disable by default ────────────────────────────────────────────────────────
# Only one of buttons/satellite runs at a time. Default mode is Buttons.
# dpx-buttonode-ui Mode tab handles enable/disable at runtime.
systemctl disable satellite
echo "==> satellite.service: installed but DISABLED (default mode: buttons)"

# ── Fix HID device permissions ────────────────────────────────────────────────
# The Buttons USB Relay package owns /dev/hidraw* via udev GROUP="buttons".
# Satellite runs as the 'satellite' user — it needs to be in the buttons group
# to open Stream Deck / HID surfaces when in satellite mode.
usermod -aG buttons satellite
echo "==> satellite user added to 'buttons' group (HID device access)"

# ── Write mode persistence file ───────────────────────────────────────────────
echo "buttons" > /etc/dpx-mode
echo "==> /etc/dpx-mode: buttons (default)"

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

systemctl is-enabled satellite.service 2>/dev/null && echo "==> Service: enabled (unexpected)" \
    || echo "==> Service: disabled (correct)"
