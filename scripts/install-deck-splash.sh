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
# libhidapi-libusb0, NOT libhidapi-hidraw0 — confirmed on real hardware
# (Stream Deck MK.2). The `streamdeck` PyPI package (0.9.8) ships exactly
# one real transport, StreamDeck/Transport/LibUSBHIDAPI.py — there is no
# hidraw-native path in this library at all, so it hard-requires
# libhidapi-libusb.so regardless of which backend "should" be simpler.
# That in turn means USB-level permissions, not hidraw permissions: the
# Buttons .deb's udev rule only grants `buttons` group access to
# /dev/hidraw* (KERNEL=="hidraw*"), which does nothing for libusb — hence
# the separate udev rule below on /dev/bus/usb/* instead.
apt-get update -q
apt-get install -y --no-install-recommends \
    python3-venv \
    libhidapi-libusb0 \
    fonts-dejavu-core

python3 -m venv /opt/dpx-deck-splash/venv
/opt/dpx-deck-splash/venv/bin/pip install --quiet --upgrade pip
/opt/dpx-deck-splash/venv/bin/pip install --quiet streamdeck pillow

# ── Script + user ────────────────────────────────────────────────────────────
install -m 0755 /tmp/dpx-deck-splash.py /usr/local/bin/dpx-deck-splash.py

# Low-priv user, `buttons` group only — never runs as root.
if ! id -u dpx-splash >/dev/null 2>&1; then
    adduser --system --no-create-home --shell /usr/sbin/nologin dpx-splash
fi
usermod -aG buttons dpx-splash

# ── udev: USB-level access for the libusb HIDAPI transport ─────────────────
# See the dependency comment above — streamdeck needs to open
# /dev/bus/usb/*, not /dev/hidraw*. Buttons' own udev rule doesn't cover
# this, so it's a separate rule here.
cat > /etc/udev/rules.d/61-dpx-deck-splash.rules << 'UDEV'
SUBSYSTEM=="usb", ATTR{idVendor}=="0fd9", MODE="0660", GROUP="buttons"
UDEV
udevadm control --reload-rules || true

# ── systemd unit ──────────────────────────────────────────────────────────
# Conflicts= on all three mode services (not just Buttons) gives a clean
# hand-off no matter which one is actually active — Satellite is the
# default mode now, and it draws to the deck itself once connected to a
# Companion server, so it needs the same yield-on-start treatment Buttons
# always had. The instant any of the three starts (at boot, or via a
# later mode switch — including one triggered from this very service's
# own MODE key), systemd stops us automatically, no manual coordination
# needed. Deliberately NOT After=network-online.target: showing "no
# network yet" during that window is the entire point of this service.
cat > /etc/systemd/system/dpx-deck-splash.service << 'UNIT'
[Unit]
Description=Stream Deck HID status splash (IP/mDNS) before Buttons/Satellite/Companion claims the device
Documentation=https://github.com/dubpixel/dpx_buttonode
After=dpx-set-hostname.service
Before=bitfocus-buttons-usb-relay.service satellite.service companion.service
Conflicts=bitfocus-buttons-usb-relay.service satellite.service companion.service

[Service]
Type=simple
# PYTHONUNBUFFERED: without it, print() output sits in a block-io buffer
# indefinitely under systemd (no tty) — confirmed on hardware, the service
# was working correctly but its own success/failure logging wasn't
# reaching the journal in real time. Not cosmetic-only; it made a real
# working state look silently stuck during debugging.
Environment=PYTHONUNBUFFERED=1
ExecStart=/opt/dpx-deck-splash/venv/bin/python3 /usr/local/bin/dpx-deck-splash.py
Restart=on-failure
RestartSec=3
User=dpx-splash
StandardOutput=journal
StandardError=journal
# KillMode=process, NOT the default control-group — confirmed on hardware
# this is load-bearing, not just tidiness. A MODE/NET keypress spawns a
# `sudo ...` child in a daemon thread; that child's own action (starting
# whichever mode service the user just switched to) is exactly what
# triggers Conflicts= to stop THIS service. With the default
# control-group KillMode, systemd kills the whole cgroup — including that
# in-flight sudo child — the moment the conflict fires, cutting
# switch_mode()/toggle_net() off mid-execution (observed: the systemctl
# start succeeded, but execution never reached the /etc/dpx-mode write
# that comes after it). KillMode=process only signals the main PID, so
# the already-running privileged child is left alone to finish.
KillMode=process

[Install]
WantedBy=multi-user.target
UNIT

systemctl enable dpx-deck-splash.service
echo "==> dpx-deck-splash.service: enabled"

# ── sudoers: the ONLY door from dpx-splash (buttons group, nothing else)
# to actually changing system state ─────────────────────────────────────────
# The deck does its own select/cycle/edit UI locally (short press advances
# a candidate, long press commits) and only calls in here with the final
# chosen value. --apply-mode/--toggle-net are fully enumerated/argument-
# free, nothing to smuggle through. --pin-static <ip> can't be enumerated
# the same way (any of ~4 billion IPs) — its sudoers line is a loose glob
# gate, and pin_static()'s own validate_ip() call in dpx-buttonode-ui.py
# is the REAL validation. The glob still blocks anything not starting
# with digit.digit.digit.digit shaped input.
cat > /etc/sudoers.d/dpx-splash << 'SUDOERS'
dpx-splash ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/bin/dpx-buttonode-ui.py --apply-mode buttons
dpx-splash ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/bin/dpx-buttonode-ui.py --apply-mode satellite
dpx-splash ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/bin/dpx-buttonode-ui.py --apply-mode companion
dpx-splash ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/bin/dpx-buttonode-ui.py --toggle-net
dpx-splash ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/bin/dpx-buttonode-ui.py --pin-static [0-9]*.[0-9]*.[0-9]*.[0-9]*
dpx-splash ALL=(root) NOPASSWD: /usr/bin/python3 /usr/local/bin/dpx-buttonode-ui.py --toggle-dashboard
SUDOERS
chmod 0440 /etc/sudoers.d/dpx-splash
visudo -cf /etc/sudoers.d/dpx-splash
echo "==> /etc/sudoers.d/dpx-splash installed and validated"

echo "==> dpx-deck-splash installed successfully"
