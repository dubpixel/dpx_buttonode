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

# NOT enabled directly. dpx-mode-select.service (below) is now the only
# thing that starts this at boot -- only as the no-persisted-mode
# fallback -- instead of both it and the current mode service racing
# multi-user.target with Conflicts= picking whichever happens to win
# (dpx#12, confirmed nondeterministic on hardware). The [Install] block
# stays so `systemctl enable dpx-deck-splash.service` still works for
# anyone who wants the old always-auto-start behavior back.
echo "==> dpx-deck-splash.service: installed (started via dpx-mode-select.service, not auto-enabled)"

# ── Recovery: bring the splash back if a mode service dies for good ────────
# OnFailure= only fires when a unit's ActiveState actually reaches
# "failed" -- with Restart=on-failure, systemd holds the unit in
# "activating (auto-restart)" between individual retry attempts, and
# only lands in "failed" once StartLimitBurst is exhausted. So this
# fires once per real, permanent outage, not once per transient restart
# (dpx#11 -- "what's not clear is when the splash comes back"). Purely
# event-driven, no polling loop.
#
# Drop-ins, not edits to the vendor unit files themselves -- all three
# mode services ship from their own .deb packages (Buttons/Satellite/
# Companion), not this repo, and a drop-in survives a package upgrade
# that a direct edit wouldn't.
for MODE_UNIT in bitfocus-buttons-usb-relay.service satellite.service companion.service; do
    mkdir -p "/etc/systemd/system/${MODE_UNIT}.d"
    cat > "/etc/systemd/system/${MODE_UNIT}.d/dpx-recovery.conf" << 'UNIT'
[Unit]
OnFailure=dpx-deck-splash.service
UNIT
done
echo "==> OnFailure=dpx-deck-splash.service drop-ins installed for all 3 mode services"

# ── Boot-time mode selection: exactly one of {persisted mode, splash} ──────
# The other half of dpx#12/dpx#11: decide once, at boot, which single
# thing should run instead of leaving it to a Conflicts= race. Reads
# /etc/dpx-mode (same file switch_mode() in dpx-buttonode-ui.py writes)
# and starts that mode's service; falls back to the splash if nothing's
# persisted or the target service refuses to start. Mirrors
# get_dpx_mode()'s own "buttons" default for consistency.
cat > /usr/local/bin/dpx-mode-select.sh << 'SCRIPT'
#!/usr/bin/env bash
set -u
MODE="$(cat /etc/dpx-mode 2>/dev/null || echo "buttons")"
case "$MODE" in
    buttons)   SVC="bitfocus-buttons-usb-relay.service" ;;
    satellite) SVC="satellite.service" ;;
    companion) SVC="companion.service" ;;
    *)         SVC="bitfocus-buttons-usb-relay.service" ;;
esac
systemctl start "$SVC" || systemctl start dpx-deck-splash.service
SCRIPT
chmod +x /usr/local/bin/dpx-mode-select.sh

cat > /etc/systemd/system/dpx-mode-select.service << 'UNIT'
[Unit]
Description=Start the persisted dpx-buttonode mode (fallback: deck splash)
Documentation=https://github.com/dubpixel/dpx_buttonode
After=dpx-set-hostname.service

[Service]
Type=oneshot
ExecStart=/usr/local/bin/dpx-mode-select.sh

[Install]
WantedBy=multi-user.target
UNIT

systemctl enable dpx-mode-select.service
echo "==> dpx-mode-select.service: enabled"

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
