#!/usr/bin/env python3
"""
dpx-deck-splash — draws a boot-time status screen (IP + mDNS hostname) onto
an attached Elgato Stream Deck, before Buttons/Satellite/Companion claims
the device.

Installed: /usr/local/bin/dpx-deck-splash.py
Service:   dpx-deck-splash.service (After=dpx-set-hostname.service,
           Before=/Conflicts=bitfocus-buttons-usb-relay.service — see the
           unit file for the full hand-off story)

Phase 1 scope: read-only display. No keypress handling, no mode/network
switching — that's Phase 2/3 (see VSCODE... no, see the project plan /
AGENTS.md). This script only draws; it never touches systemctl, netplan,
or /etc/dpx-mode.

Unlike dpx-buttonode-ui.py, this script is NOT stdlib-only on purpose —
drawing to the deck needs real HID + image handling, which is a different
job than the always-on config UI. Dependencies (streamdeck, Pillow) live in
a dedicated venv at /opt/dpx-deck-splash/venv, installed by
scripts/install-deck-splash.sh, so they never touch the system Python used
by dpx-buttonode-ui.py.

Requires: `buttons` group membership (inherited hidraw permission via the
udev rule the Buttons .deb installs: KERNEL=="hidraw*",
ATTRS{idVendor}=="0fd9", GROUP="buttons") — this only works if hidapi is
using the hidraw backend, not the libusb backend. See
scripts/install-deck-splash.sh for the specific apt package that enforces
this.
"""

import re
import socket
import subprocess
import sys
import time

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from PIL import Image, ImageDraw, ImageFont

REFRESH_SECONDS = 5          # how often to re-check IP/hostname while idle
RETRY_SECONDS = 3            # how often to retry finding a deck if none present
FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]


def run(cmd):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout.strip()
    except FileNotFoundError:
        return ""


def get_ip():
    out = run(["ip", "-4", "addr", "show", "scope", "global"])
    m = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", out)
    return m.group(1) if m else None


def get_mdns_name():
    """avahi publishes the system hostname by default, no override in this
    repo — so the mDNS name is just '<hostname>.local'."""
    return f"{socket.gethostname()}.local"


def load_font(size):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def render_key(deck, text, font_size=16):
    """One key, centered text, black background — deliberately simple,
    hardcoded for exactly the two fields we need (IP octet, hostname
    segment). Not a general text-wrap engine.

    Shrinks the font until the text fits the key width (with a small
    margin) rather than letting a longer word (e.g. "buttonode") run off
    the edge — segments are whole words now (see chunk_hostname), so
    lengths vary more than the old fixed-character-count chunking did.
    """
    image = PILHelper.create_key_image(deck)
    draw = ImageDraw.Draw(image)
    margin = image.width * 0.12
    size = font_size
    while size > 7:
        font = load_font(size)
        bbox = draw.textbbox((0, 0), text, font=font)
        w = bbox[2] - bbox[0]
        if w <= image.width - margin:
            break
        size -= 1
    h = bbox[3] - bbox[1]
    w = bbox[2] - bbox[0]
    pos = ((image.width - w) / 2, (image.height - h) / 2)
    draw.text(pos, text, font=font, fill="white")
    return PILHelper.to_native_key_format(deck, image)


def blank_key(deck):
    image = PILHelper.create_key_image(deck)
    return PILHelper.to_native_key_format(deck, image)


def chunk_ip(ip, n):
    """Split an IP into up to n chunks, one octet per chunk where possible."""
    if not ip:
        placeholder = ["no", "IP"]
        return (placeholder + [""] * n)[:n]
    octets = ip.split(".")
    if n >= len(octets):
        return octets + [""] * (n - len(octets))
    # fewer keys than octets — just show the last two combined
    return [".".join(octets[:2]), ".".join(octets[2:])] + [""] * max(n - 2, 0)


def chunk_hostname(name, n):
    """Split 'dpx-buttonode-XXXX.local' across n keys on natural word
    boundaries (-, .), one whole word per key — not a fixed character
    count. render_key() shrinks the font to fit whatever lands on a key,
    so a longer segment like "buttonode" still renders whole instead of
    getting chopped mid-word (e.g. old output: "dpx-bu"/"ttonod"/"e-2199").
    If there are more segments than keys, the overflow gets folded into
    the last key rather than silently dropped.
    """
    segments = re.split(r"[-.]", name)
    segments = [s for s in segments if s]
    if len(segments) > n:
        segments = segments[:n - 1] + ["-".join(segments[n - 1:])]
    return segments + [""] * (n - len(segments))


def draw_splash(deck, ip, mdns_name):
    rows, cols = deck.key_layout()
    total = deck.key_count()

    ip_row = chunk_ip(ip, cols) if rows >= 1 else []
    host_row = chunk_hostname(mdns_name, cols) if rows >= 2 else []

    for i in range(total):
        r, c = divmod(i, cols)
        if r == 0 and c < len(ip_row) and ip_row[c]:
            deck.set_key_image(i, render_key(deck, ip_row[c]))
        elif r == 1 and c < len(host_row) and host_row[c]:
            deck.set_key_image(i, render_key(deck, host_row[c], font_size=12))
        else:
            deck.set_key_image(i, blank_key(deck))


def run_splash_loop():
    last_ip = None
    while True:
        decks = DeviceManager().enumerate()
        if not decks:
            time.sleep(RETRY_SECONDS)
            continue
        deck = decks[0]
        try:
            deck.open()
            deck.reset()
            deck.set_brightness(60)
            print(f"dpx-deck-splash: opened {deck.deck_type()} ({deck.key_count()} keys)")
            while True:
                ip = get_ip()
                if ip != last_ip:
                    draw_splash(deck, ip, get_mdns_name())
                    last_ip = ip
                    print(f"dpx-deck-splash: displaying ip={ip}")
                time.sleep(REFRESH_SECONDS)
        except Exception as e:
            # Most likely cause: Buttons/Satellite/Companion just claimed
            # the device (systemd Conflicts= will be stopping us right
            # about now anyway), or the deck was unplugged. Either way,
            # back off and let systemd's Conflicts= ordering do its job —
            # don't crash-loop noisily.
            print(f"dpx-deck-splash: lost device ({e}), backing off", file=sys.stderr)
            try:
                deck.close()
            except Exception:
                pass
            time.sleep(RETRY_SECONDS)


if __name__ == "__main__":
    try:
        run_splash_loop()
    except KeyboardInterrupt:
        pass
