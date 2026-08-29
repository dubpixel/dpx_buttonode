#!/usr/bin/env bash
# install-dashboard.sh
# Runs inside the image chroot via Packer (both variants — Dashboard is
# orthogonal to the Buttons/Satellite/Companion mode system, not gated by
# `variant`).
#
# Installs tomhillmeyer/companion-dashboard as an opt-in on-unit kiosk
# display. Adapted from their own install-linux-server-systemd.sh (X11 +
# openbox + Electron kiosk on tty7), but installed DISABLED — the web UI's
# Devices tab toggle is what enables/starts it, not first boot.
#
# Dashboard service name: dpx-dashboard
# Dashboard has its own first-run/remote-config UI for pointing at a
# Companion instance — nothing here pre-configures that, by design.

set -euo pipefail

echo "==> Installing Companion Dashboard (opt-in kiosk display)"

# ── Dependencies ────────────────────────────────────────────────────────────
# X11 + minimal window manager + Electron's runtime deps. avahi-daemon is
# already installed elsewhere in the pipeline.
apt-get update -q
apt-get install -yq \
    xserver-xorg xserver-xorg-video-fbdev xserver-xorg-input-all \
    xserver-xorg-legacy xinit x11-xserver-utils openbox mesa-utils \
    libgl1-mesa-dri unclutter nodejs npm libcap2-bin
apt-get clean

echo "==> Dependencies installed"

# ── Fetch latest Companion Dashboard .deb (arm64) ───────────────────────────
DASHBOARD_ASSET_URL=$(curl -fsSL \
    https://api.github.com/repos/tomhillmeyer/companion-dashboard/releases/latest \
    | grep -o '"browser_download_url": *"[^"]*arm64[^"]*\.deb"' \
    | head -1 \
    | sed -E 's/.*"(https[^"]+)"/\1/')

if [ -z "$DASHBOARD_ASSET_URL" ]; then
    echo "==> ERROR: could not resolve an arm64 .deb from the latest companion-dashboard release" >&2
    exit 1
fi

echo "==> Downloading: ${DASHBOARD_ASSET_URL}"
curl -fsSL -o /tmp/companion-dashboard.deb "$DASHBOARD_ASSET_URL"

dpkg -i /tmp/companion-dashboard.deb || apt-get install -f -yq
rm -f /tmp/companion-dashboard.deb

echo "==> Companion Dashboard package installed"

# ── Low-priv user ────────────────────────────────────────────────────────────
# No `buttons` group — Dashboard never touches the Stream Deck / HID
# devices, only Companion's REST API over the network.
if ! id -u dpx-dashboard >/dev/null 2>&1; then
    adduser --system --shell /bin/bash dpx-dashboard
fi

# ── X session launch files ──────────────────────────────────────────────────
DASH_HOME="/home/dpx-dashboard"
mkdir -p "$DASH_HOME"

cat > "$DASH_HOME/.xinitrc" << 'XINITRC'
#!/bin/sh
xset -dpms
xset s off
xset s noblank
unclutter -idle 0.5 -root &
openbox-session &
exec companion-dashboard --kiosk --no-sandbox
XINITRC
chmod +x "$DASH_HOME/.xinitrc"

chown -R dpx-dashboard:dpx-dashboard "$DASH_HOME"

# ── systemd unit ─────────────────────────────────────────────────────────────
# Adapted from companion-dashboard's own install-linux-server-systemd.sh
# unit, but runs as User=root, not User=dpx-dashboard, and drops
# StandardInput=tty/TTYPath/TTYReset/TTYVHangup entirely. A sibling project
# (dpx_openPanel, same Pi 4 kiosk problem, issue #6) hit this exact
# combination crash-looping with "xf86OpenConsole: Cannot open virtual
# console 1 (Permission denied)" -- a systemd User= service does not get a
# real logind session for VT access, so X can't open the console under a
# non-root user without a PAM-managed login session (which TTYPath alone
# doesn't provide). Root has console access outright, sidestepping the
# whole problem -- confirmed fix in that project. `--no-sandbox` is
# already required for Chromium/Electron as root (also confirmed there),
# and is already in the .xinitrc's exec line above.
#
# Installed but NOT enabled/started -- this is an opt-in toggle
# (dpx-buttonode-ui Devices tab), not auto-start on boot like their own
# default. Getty-autologin block skipped entirely: the unit launches X
# directly on tty7 itself, no need to touch tty1.
cat > /etc/systemd/system/dpx-dashboard.service << 'UNIT'
[Unit]
Description=Companion Dashboard Display Service
After=network-online.target graphical.target
Wants=network-online.target

[Service]
Type=simple
User=root
Environment=DISPLAY=:0
Environment=XAUTHORITY=/home/dpx-dashboard/.Xauthority
ExecStartPre=/bin/sleep 5
ExecStart=/usr/bin/xinit /home/dpx-dashboard/.xinitrc -- /usr/bin/X :0 vt7 -nolisten tcp -noreset
Restart=on-failure
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=graphical.target
UNIT

systemctl daemon-reload
echo "==> dpx-dashboard.service: installed, NOT enabled (opt-in via Devices tab)"

# setcap cap_net_bind_service on the Electron binary would only matter if
# Dashboard's own remote-config server binds :80 — not confirmed (nothing
# else in this project uses :80, but Dashboard's actual default port for
# that server wasn't verified against its source this pass). Skipping
# rather than guessing; revisit if real hardware testing shows it needs it.

# ── Record install in build metadata ────────────────────────────────────────
echo "DASHBOARD_INSTALLED=1" >> /etc/dpx-buttonode-release

echo "==> Companion Dashboard installed successfully"
