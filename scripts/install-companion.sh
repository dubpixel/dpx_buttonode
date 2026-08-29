#!/usr/bin/env bash
# install-companion.sh
# Runs inside the Armbian image chroot via Packer (Full variant only).
# Installs full Bitfocus Companion using the official companion-pi installer,
# then disables it by default. Mode switching is handled by dpx-buttonode-ui.
#
# Companion service name: companion
# Companion web UI:       http://<device>:8000
# Companion config:       /etc/companion/config.yaml (v4+)

set -euo pipefail

echo "==> Installing Bitfocus Companion (full, stable build)"

# Install required dependencies
apt-get update -q
apt-get install -yq git zip unzip curl libusb-1.0-0-dev libudev-dev wget python3 \
    libfontconfig1 libatomic1
# libasound2t64 on Ubuntu 24.04 (Noble); fall back to libasound2 on older systems
apt-get install -yq libasound2t64 2>/dev/null || apt-get install -yq libasound2 2>/dev/null || true
apt-get clean

echo "==> Dependencies installed"

# Download the official install script to a temp file (avoids curl|bash anti-pattern)
curl -fsSL \
    https://raw.githubusercontent.com/bitfocus/companion-pi/main/install.sh \
    -o /tmp/companion-official-install.sh

chmod +x /tmp/companion-official-install.sh

# Run official install — downloads pre-built arm64 binary from GitHub.
# No build step (unlike satellite). Requires internet access.
export COMPANION_BUILD="stable"
/tmp/companion-official-install.sh

rm -f /tmp/companion-official-install.sh

echo "==> Bitfocus Companion installed"

# ── Install the on-device update script ───────────────────────────────────────
# Invoked by dpx-buttonode-ui.py's Updates tab (apply_component_update()) via
# systemd-run --no-block. See scripts/update-companion.sh for why this is a
# separate script rather than a re-run of this one.
install -m 0755 /tmp/update-companion.sh /usr/local/bin/update-companion.sh
echo "==> update-companion.sh installed to /usr/local/bin"

# ── Disable by default ────────────────────────────────────────────────────────
# Only one service runs at a time. Default mode is Satellite (set in
# install-satellite.sh, which runs AFTER this one on Full-variant builds —
# deliberately: companion-pi's installer purges /opt/fnm as a final step,
# which Satellite still depends on, so Satellite must always install last.
# See the ordering note in dpx-buttonode.pkr.hcl).
# dpx-buttonode-ui Mode tab handles enable/disable at runtime.
systemctl disable companion
echo "==> companion.service: installed but DISABLED (default mode: satellite)"

# ── Fix HID device permissions ────────────────────────────────────────────────
# The Buttons USB Relay package owns /dev/hidraw* via udev GROUP="buttons".
# Companion runs as the 'companion' user — it needs to be in the buttons group
# to open Stream Deck / HID surfaces when in companion mode.
usermod -aG buttons companion
echo "==> companion user added to 'buttons' group (HID device access)"

# ── Record Companion version in build metadata ────────────────────────────────
COMPANION_VERSION="unknown"
# Try reading from the BUILD file companion-pi installs
if [ -f "/opt/companion/BUILD" ]; then
    COMPANION_VERSION=$(cat /opt/companion/BUILD | tr -d '[:space:]')
elif [ -f "/opt/companion/package.json" ]; then
    COMPANION_VERSION=$(node -e "console.log(require('/opt/companion/package.json').version)" 2>/dev/null || echo "unknown")
fi
echo "COMPANION_VERSION=${COMPANION_VERSION}" >> /etc/dpx-buttonode-release
echo "==> Companion version: ${COMPANION_VERSION}"

# ── Record variant in build metadata ─────────────────────────────────────────
echo "VARIANT=full" >> /etc/dpx-buttonode-release
echo "==> Image variant: full"

# ── Verify install ────────────────────────────────────────────────────────────
if [ -d "/opt/companion" ]; then
    echo "==> Bitfocus Companion: OK (/opt/companion exists)"
else
    echo "==> WARNING: /opt/companion not found — companion may not have installed correctly"
    echo "==> Run 'sudo companion-update' on the device to recover"
    exit 1
fi

systemctl is-enabled companion.service 2>/dev/null && echo "==> Service: enabled (unexpected)" \
    || echo "==> Service: disabled (correct)"
