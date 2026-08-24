#!/usr/bin/env bash
# install-deck-splash.sh
# Runs inside the Armbian image chroot via Packer.
# Installs dpx-deck-splash: draws IP + mDNS hostname on the Stream Deck's
# keys during the boot window before Buttons/Satellite/Companion claims
# the device.
#
# Runs AFTER install-buttons.sh (needs the `buttons` group + udev rule
# that package creates for hidraw access) and should run before
# install-satellite.sh/install-companion.sh, order doesn't matter for
# those two since they only add themselves to the `buttons` group.

set -euo pipefail

echo "==> Installing dpx-deck-splash"

# ── Dependencies ────────────────────────────────────────────────────────────
# Deliberately NOT installed into the system Python — dpx-buttonode-ui.py
# is stdlib-only on purpose, and this is a different concern with real
# dependencies. Isolated in its own venv.
#
# libhidapi-hidraw0 (not libhidapi-libusb0) matters: the Buttons .deb's
# udev rule (60-bitfocus-buttons.rules) grants group `buttons` access to
# /dev/hidraw* specifically. hidapi has two Linux backends — hidraw and
# libusb — and only the hidraw backend respects that udev rule. Installing
# the libusb variant would silently need different (unconfigured)
# permissions.
apt-get update -q
apt-get install -y --no-install-recommends \
    python3-venv \
    libhidapi-hidraw0 \
    fonts-dejavu-core

python3 -m venv /opt/dpx-deck-splash/venv
/opt/dpx-deck-splash/venv/bin/pip install --quiet --upgrade pip
/opt/dpx-deck-splash/venv/bin/pip install --quiet streamdeck pillow

# ── Script + user ────────────────────────────────────────────────────────────
install -m 0755 /tmp/dpx-deck-splash.py /usr/local/bin/dpx-deck-splash.py

# Low-priv user, `buttons` group only (hidraw access) — never runs as root.
if ! id -u dpx-splash >/dev/null 2>&1; then
    adduser --system --no-create-home --shell /usr/sbin/nologin dpx-splash
fi
usermod -aG buttons dpx-splash

# ── systemd unit ──────────────────────────────────────────────────────────
# Conflicts= gives a clean hand-off: the instant bitfocus-buttons-usb-relay
# starts (at boot, or via a later /mode switch back to buttons), systemd
# stops us automatically — no manual coordination needed. Deliberately NOT
# After=network-online.target: showing "no network yet" during that window
# is the entire point of this service.
cat > /etc/systemd/system/dpx-deck-splash.service << 'UNIT'
[Unit]
Description=Stream Deck HID status splash (IP/mDNS) before Buttons/Satellite/Companion claims the device
Documentation=https://github.com/dubpixel/dpx_buttonode
After=dpx-set-hostname.service
Before=bitfocus-buttons-usb-relay.service
Conflicts=bitfocus-buttons-usb-relay.service

[Service]
Type=simple
ExecStart=/opt/dpx-deck-splash/venv/bin/python3 /usr/local/bin/dpx-deck-splash.py
Restart=on-failure
RestartSec=3
User=dpx-splash
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
UNIT

systemctl enable dpx-deck-splash.service
echo "==> dpx-deck-splash.service: enabled"

echo "==> dpx-deck-splash installed successfully"
