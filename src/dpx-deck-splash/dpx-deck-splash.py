#!/usr/bin/env python3
"""
dpx-deck-splash — draws a boot-time status screen (IP + mDNS hostname) onto
an attached Elgato Stream Deck, before Buttons/Satellite/Companion claims
the device.

Installed: /usr/local/bin/dpx-deck-splash.py
Service:   dpx-deck-splash.service (After=dpx-set-hostname.service,
           Before=/Conflicts=bitfocus-buttons-usb-relay.service — see the
           unit file for the full hand-off story)

Phase 2/3: if the deck has a third key row, the first two keys in it are
action buttons — MODE (cycles Buttons -> Satellite -> Companion) and NET
(toggles DHCP <-> last-known-static). This script never touches systemctl,
netplan, or /etc/dpx-mode directly — it shells out via `sudo` to
dpx-buttonode-ui.py's `--cycle-mode`/`--toggle-net` CLI subcommands (see
/etc/sudoers.d/dpx-splash, installed by install-deck-splash.sh), which is
where that logic actually lives. Keeps this process's own privilege
footprint at exactly `buttons` group membership — nothing more — even
though it can now trigger real system changes.

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
import threading
import time

from StreamDeck.DeviceManager import DeviceManager
from StreamDeck.ImageHelpers import PILHelper
from PIL import Image, ImageDraw, ImageFont

PORT = 8080                  # dpx-buttonode-ui's port — shown alongside the IP
REFRESH_SECONDS = 5          # how often to re-check IP/hostname while idle
RETRY_SECONDS = 3            # how often to retry finding a deck if none present
DEBOUNCE_SECONDS = 2         # ignore repeat presses of the same action key within this window
UI_SCRIPT = "/usr/local/bin/dpx-buttonode-ui.py"
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
    """Split an IP into up to n chunks, one octet per chunk where possible.
    If there's room for all 4 octets plus one more key, the last key shows
    the web UI port — easy to miss that the URL needs ":8080" otherwise.
    """
    if not ip:
        placeholder = ["no", "IP"]
        return (placeholder + [""] * n)[:n]
    octets = ip.split(".")
    if n > len(octets):
        return octets + [f":{PORT}"] + [""] * (n - len(octets) - 1)
    if n == len(octets):
        return octets
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


def action_key_indices(deck):
    """Key indices for the MODE and NET action buttons, or (None, None) if
    the deck doesn't have a third row to put them in (e.g. a 2-row Mini) —
    Phase 2/3 is simply unavailable on decks that small, not an error."""
    rows, cols = deck.key_layout()
    if rows < 3:
        return None, None
    return 2 * cols, 2 * cols + 1


def draw_splash(deck, ip, mdns_name):
    rows, cols = deck.key_layout()
    total = deck.key_count()
    mode_key, net_key = action_key_indices(deck)

    ip_row = chunk_ip(ip, cols) if rows >= 1 else []
    host_row = chunk_hostname(mdns_name, cols) if rows >= 2 else []

    for i in range(total):
        r, c = divmod(i, cols)
        if i == mode_key:
            deck.set_key_image(i, render_key(deck, "MODE", font_size=14))
        elif i == net_key:
            deck.set_key_image(i, render_key(deck, "NET", font_size=14))
        elif r == 0 and c < len(ip_row) and ip_row[c]:
            deck.set_key_image(i, render_key(deck, ip_row[c]))
        elif r == 1 and c < len(host_row) and host_row[c]:
            deck.set_key_image(i, render_key(deck, host_row[c], font_size=12))
        else:
            deck.set_key_image(i, blank_key(deck))


def run_privileged(subcommand):
    """Shell out via sudo to the exact CLI subcommand on dpx-buttonode-ui.py
    that /etc/sudoers.d/dpx-splash whitelists. This process never runs the
    mode-switch/network-toggle logic itself or gains any privilege beyond
    `buttons` group membership — sudo is the only door, and it opens onto
    exactly one of two fixed, argument-free commands."""
    try:
        r = subprocess.run(
            ["sudo", "-n", "/usr/bin/python3", UI_SCRIPT, subcommand],
            capture_output=True, text=True, timeout=30,
        )
        msg = (r.stdout or r.stderr).strip()
        print(f"dpx-deck-splash: {subcommand} -> {msg or ('ok' if r.returncode == 0 else 'failed')}")
    except Exception as e:
        print(f"dpx-deck-splash: {subcommand} failed to run ({e})", file=sys.stderr)


def make_key_callback():
    """Returns a callback for deck.set_key_callback(). Debounced per key —
    a single physical press can otherwise fire faster than a multi-second
    mode-switch/network-toggle can safely be re-triggered."""
    last_press = {}

    def on_key(deck, key, pressed):
        if not pressed:
            return
        now = time.monotonic()
        if now - last_press.get(key, 0) < DEBOUNCE_SECONDS:
            return
        last_press[key] = now
        mode_key, net_key = action_key_indices(deck)
        if key == mode_key:
            threading.Thread(target=run_privileged, args=("--cycle-mode",), daemon=True).start()
        elif key == net_key:
            threading.Thread(target=run_privileged, args=("--toggle-net",), daemon=True).start()

    return on_key


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
            deck.set_key_callback(make_key_callback())
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
